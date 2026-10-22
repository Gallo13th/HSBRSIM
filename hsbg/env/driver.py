"""引擎驱动层 —— 合法动作枚举 / 应用 / PendingChoice 结算。

本模块把「与引擎对话」的细节从观测与策略中解耦：

- :func:`enumerate_actions`：枚举**当前必然合法**的引擎级动作
  (:class:`ActionDescriptor`)；
- :func:`apply_action`：把动作应用到引擎，捕获 ``GameStateError`` 等异常，
  返回 :class:`ApplyResult`（绝不向上抛异常）；
- :func:`resolve_pending_choices`：按「FIFO 弹出 → choose → 已弹出」契约
  结算 ``game.pending_choices``；
- :class:`ChoiceQueue`：``game.pending_choices`` 的「入队即自动结算」替身，
  用于 ``Game.end_recruit_phase()`` 这类**无法暂停**的同步阶段。

设计约定（对齐 ``docs/ENV_SPEC.md`` §3/§7 与 lead 的引擎集成要点）
---------------------------------------------------------------
1. **候选动作一定合法**：宁可少枚举，不可枚举非法动作。凡是无法确定
   目标合法性的动作不生成候选（例如脚本 ``target_candidates`` 返回的实体
   不在本步可寻址区域内时）。
2. **槽位同源**：驱动层只构造一次 :class:`Zones`（board/hand/tavern/... 的
   有序实体列表），``ActionDescriptor`` 直接携带 ``zone + slot``；
   ``hsbg.env.observation`` 用**同一份** ``Zones`` 生成 ``EntityToken``，
   保证候选动作的槽位下标与观测槽位一一对应。
3. **战斗不可暂停**：``Game.end_recruit_phase()`` 同步跑完所有配对战斗，
   战斗中产生的 ``PendingChoice`` 无法作为 ``phase="choice"`` 暴露给策略；
   该阶段内全部选择自动结算（见 :class:`ChoiceQueue`）。
4. 不做 I/O、不打印日志。
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import hsrl2.constants as C
from hsrl2.db import CardDB
from hsrl2.game import Game, GameStateError, PendingChoice
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import GameTag

from hsbg.env.spec import (
    CANDIDATE_MAX,
    ActionKind,
    CandidateAction,
    ZONE_BOARD,
    ZONE_HAND,
    ZONE_NONE,
    ZONE_TAVERN,
    ZONE_TRINKET,
)

__all__ = [
    "ActionDescriptor",
    "ApplyResult",
    "Zones",
    "ChoiceQueue",
    "get_card_db",
    "collect_zones",
    "enumerate_action",
    "enumerate_actions",
    "enumerate_step",
    "enumerate_choice",
    "apply_action",
    "resolve_pending_choices",
    "default_pick_index",
]


# ══════════════════════════════════════════════════════════════════════
# 卡牌数据库（进程内只读缓存）
# ══════════════════════════════════════════════════════════════════════


@functools.lru_cache(maxsize=4)
def _load_db(data_dir: str) -> CardDB:
    return CardDB.load(data_dir)


def get_card_db(data_dir: Optional[str] = None) -> CardDB:
    """返回进程级共享的只读 :class:`CardDB`（加载一次，约 90 ms）。

    引擎每个 ``Game`` 都自带 ``minion_pool`` / ``spell_pool``，``CardDB``
    本身不会被写入，因此多环境共享同一实例是安全的；多进程 worker 各自
    加载一份。
    """
    if data_dir is None:
        from hsbg.paths import DATA_DIR
        data_dir = str(DATA_DIR)
    return _load_db(str(data_dir))


# ══════════════════════════════════════════════════════════════════════
# 槽位视图（驱动枚举与观测生成的唯一事实来源）
# ══════════════════════════════════════════════════════════════════════


@dataclass
class Zones:
    """一步决策内各区域的实体有序列表（下标即观测槽位）。

    ``board/hand/tavern/trinkets`` 是**活实体**（引擎对象）；
    ``opponent_board`` 是上一场对手的战前战团快照（可能是冻结副本，
    不与引擎当前实体同一身份——只用于观测，不参与动作寻址）。
    """

    board: List[Any] = field(default_factory=list)
    hand: List[Any] = field(default_factory=list)
    tavern: List[Any] = field(default_factory=list)
    trinkets: List[Any] = field(default_factory=list)
    #: 英雄技能 CardDef 列表（下标 = ``game.hero_power_ids`` 顺序）
    powers: List[Any] = field(default_factory=list)
    power_ids: List[str] = field(default_factory=list)
    opponent_board: List[Any] = field(default_factory=list)
    #: id(实体) -> (zone, slot)；仅含**可寻址**的活实体区域
    index: Dict[int, Tuple[str, int]] = field(default_factory=dict)

    def list_for(self, zone: str) -> List[Any]:
        if zone == ZONE_BOARD:
            return self.board
        if zone == ZONE_HAND:
            return self.hand
        if zone == ZONE_TAVERN:
            return self.tavern
        if zone == ZONE_TRINKET:
            return self.trinkets
        return []

    def locate(self, entity: Any) -> Optional[Tuple[str, int]]:
        """实体当前的 ``(zone, slot)``；不在可寻址区域 → ``None``。"""
        if entity is None:
            return None
        return self.index.get(id(entity))


def collect_zones(game: Game, hero: Hero) -> Zones:
    """收集该英雄本步的槽位视图（快照，不复制实体）。"""
    board = list(hero.board)
    hand = list(hero.hand)
    tavern = list(hero.tavern)
    trinkets = list(hero.trinkets)
    power_ids = list(game.hero_power_ids(hero))
    powers: List[Any] = []
    for pid in power_ids:
        pdef = game.hero_power_def_for(hero, pid)
        if pdef is not None:
            powers.append(pdef)
    # 上一场对手战前战团（官方可见信息；无记录 → 空）
    opp_raw = game.last_opponent_warband(hero) or []
    opponent_board = list(opp_raw)
    index: Dict[int, Tuple[str, int]] = {}
    for zone, arr in ((ZONE_BOARD, board), (ZONE_HAND, hand),
                      (ZONE_TAVERN, tavern), (ZONE_TRINKET, trinkets)):
        for slot, ent in enumerate(arr):
            index[id(ent)] = (zone, slot)
    return Zones(board=board, hand=hand, tavern=tavern, trinkets=trinkets,
                 powers=powers, power_ids=power_ids,
                 opponent_board=opponent_board, index=index)


# ══════════════════════════════════════════════════════════════════════
# 动作描述符
# ══════════════════════════════════════════════════════════════════════


@dataclass
class ActionDescriptor:
    """引擎级动作描述（含观测槽位引用）。

    ``zone/slot`` 与 ``Zones`` 完全一致；``src_entity/tgt_entity`` 是引擎
    实体，供 :func:`apply_action` 直接调用引擎 API。
    """

    kind: str
    src_entity: Any = None
    src_zone: str = ZONE_NONE
    src_slot: int = -1
    tgt_entity: Any = None
    tgt_zone: str = ZONE_NONE
    tgt_slot: int = -1
    #: 打出随从的棋盘插入位置；-1 = 追加到最右
    position: int = -1
    #: choose 动作的选项下标
    option: int = -1
    #: 显式金币费用（-1 = 不适用）
    cost: int = -1
    #: hero_power 动作对应的技能 id
    power_id: str = ""
    #: 磁力吸附（与战吼目标语义互斥，见 ``play_minion``）
    magnetic: bool = False
    #: 调试备注（策略不得依赖）
    note: str = ""

    def to_candidate(self) -> CandidateAction:
        return CandidateAction(
            kind=self.kind,
            src_zone=self.src_zone,
            src_slot=self.src_slot,
            tgt_zone=self.tgt_zone,
            tgt_slot=self.tgt_slot,
            position=self.position,
            option=self.option,
            cost=self.cost,
        )

    def signature(self) -> Tuple[Any, ...]:
        return self.to_candidate().signature()


@dataclass
class ApplyResult:
    """动作应用结果（成功/失败原因，绝不抛异常）。"""

    success: bool
    kind: str = ""
    error: str = ""
    error_type: str = ""


@dataclass
class StepActions:
    """一步的完整动作集（槽位视图 + 描述符 + 契约候选动作）。"""

    zones: Zones
    descriptors: List[ActionDescriptor]
    candidates: Tuple[CandidateAction, ...]

    def __len__(self) -> int:  # pragma: no cover - 便捷
        return len(self.descriptors)


# ══════════════════════════════════════════════════════════════════════
# 动作枚举
# ══════════════════════════════════════════════════════════════════════


def _desc(kind: str, *, src: Any = None, zones: Optional[Zones] = None,
          tgt: Any = None, position: int = -1, option: int = -1,
          cost: int = -1, power_id: str = "", magnetic: bool = False,
          note: str = "") -> ActionDescriptor:
    """构造描述符，并从 ``zones`` 反查 src/tgt 槽位。"""
    src_zone, src_slot = (ZONE_NONE, -1)
    tgt_zone, tgt_slot = (ZONE_NONE, -1)
    if zones is not None:
        if src is not None:
            loc = zones.locate(src)
            if loc is not None:
                src_zone, src_slot = loc
        if tgt is not None:
            loc = zones.locate(tgt)
            if loc is not None:
                tgt_zone, tgt_slot = loc
    return ActionDescriptor(
        kind=kind, src_entity=src, src_zone=src_zone, src_slot=src_slot,
        tgt_entity=tgt, tgt_zone=tgt_zone, tgt_slot=tgt_slot,
        position=position, option=option, cost=cost, power_id=power_id,
        magnetic=magnetic, note=note)


def _card_def(game: Game, entity: Any) -> Any:
    cid = getattr(entity, "card_id", None)
    if cid is None:
        return None
    try:
        return game.db.get(cid)
    except Exception:                                     # noqa: BLE001
        return None


def _minion_buy_cost(game: Game, hero: Hero, entity: Any, d: Any) -> int:
    """买入报价（复刻 ``Game.buy_from_tavern`` 的**确定性**定价分支）。

    只复刻会**抬高**报价的分支（默认价 / 酒馆等级价 / 英雄覆写）与
    会**降低**报价的分支（免费随从配额 / 条件化购价 / 法术折扣）。
    ``_tavern_cost_rules`` 只可能降低价格，但它是 ``min(cost, c)``——
    复刻它需要执行脚本谓词；为了「候选必定合法」，这里只在能安全求值
    时取 ``min``，异常时保持原价（宁可贵一点：贵了只会少枚举）。
    """
    cost = int(entity.get(GameTag.COST, C.MINION_BUY_COST))
    if isinstance(entity, Minion):
        if getattr(game, "_minion_cost_is_tier", False):
            cost = int(getattr(entity, "tech_level", 1))
        override = hero.get(GameTag.TAVERN_MINION_COST_OVERRIDE, 0)
        if override:
            cost = int(override)
        for rule in list(getattr(hero, "_tavern_cost_rules", [])):
            try:
                src, pred, c = rule
            except Exception:                             # noqa: BLE001
                continue
            if src is not None and not (
                    src in hero.trinkets
                    or src in getattr(hero, "quest_rewards", [])
                    or src in hero.board):
                continue
            try:
                if pred(entity):
                    cost = min(cost, int(c))
            except Exception:                             # noqa: BLE001
                continue
        if _free_minion_buy_available(game, hero, entity):
            cost = 0
    elif d is not None and getattr(d, "is_pool_spell", False):
        pers = hero.get(GameTag.TAVERN_SPELL_COST_MOD, 0)
        if pers:
            cost = max(0, cost - int(pers))
        if hero.get(GameTag.FREE_SPELL_BUYS_THIS_TURN, 0) > 0:
            cost = 0
        else:
            discount = hero.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0)
            if discount > 0:
                cost = max(0, cost - int(discount))
    return max(0, cost)


def _free_minion_buy_available(game: Game, hero: Hero, entity: Any) -> bool:
    """只读判定：该实体能否吃到一个免费随从购买配额（不消费配额）。"""
    try:
        quotas = getattr(hero, "_free_minion_buy_quotas", []) or []
        for q in quotas:
            if q.get("turn") != game.turn:
                continue
            if q.get("used", 0) >= q.get("count", 0):
                continue
            if game._free_buy_qualifiers_match(entity, q.get("race"),
                                               q.get("keyword")):
                return True
        if quotas:
            return False
        n = hero.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0)
        if n > 0 and game._free_buy_qualifiers_match(
                entity, hero.get(GameTag.FREE_MINION_BUY_RACE, None),
                hero.get(GameTag.FREE_MINION_BUY_KEYWORD, None)):
            return True
    except Exception:                                     # noqa: BLE001
        return False
    return False


def _health_buy_possible(game: Game, hero: Hero, entity: Any, d: Any,
                         cost: int) -> bool:
    """该实体的报价是否可「以生命代金」，且当前生命足够。"""
    if cost <= 0:
        return False
    health_buy = bool(d is not None and getattr(d, "health_cost", False)) \
        or bool(entity.get(GameTag.HEALTH_BUY, False))
    if not health_buy and isinstance(entity, Spell) \
            and hero.get(GameTag.HEALTH_SPELL_BUYS_THIS_TURN, 0) > 0:
        health_buy = True
    if not health_buy and isinstance(entity, Minion) \
            and hero.get(GameTag.HEALTH_MINION_BUYS_THIS_TURN, 0) > 0:
        try:
            health_buy = bool(game._health_buy_race_matches(hero, entity))
        except Exception:                                 # noqa: BLE001
            health_buy = False
    return health_buy and (hero.health + hero.armor > cost)


def _forced_health_buy(game: Game, hero: Hero, entity: Any, d: Any,
                       cost: int) -> bool:
    """引擎语义：该购买是否**强制以生命支付**（金币再多也不可用金币）。

    复刻 ``Game.buy_from_tavern`` 的 health_buy 判定顺序：
    卡定义 ``health_cost``（Hasty Excavation）→ 实体 ``HEALTH_BUY`` tag →
    英雄级"本回合酒馆法术/随从以生命购买"配额（匹配种族）。
    强制生命支付时引擎只检查 ``health+armor > cost``，金币不足无关。
    """
    if cost <= 0:
        return False
    if d is not None and getattr(d, "health_cost", False):
        return True
    try:
        if entity.get(GameTag.HEALTH_BUY, False):
            return True
    except Exception:                                     # noqa: BLE001
        pass
    if isinstance(entity, Spell) \
            and hero.get(GameTag.HEALTH_SPELL_BUYS_THIS_TURN, 0) > 0:
        return True
    if isinstance(entity, Minion) \
            and hero.get(GameTag.HEALTH_MINION_BUYS_THIS_TURN, 0) > 0:
        try:
            return bool(game._health_buy_race_matches(hero, entity))
        except Exception:                                 # noqa: BLE001
            return False
    return False


def _enumerate_buys(game: Game, hero: Hero, zones: Zones) -> List[ActionDescriptor]:
    out: List[ActionDescriptor] = []
    if hero.hand_full():
        return out
    for slot, ent in enumerate(zones.tavern):
        d = _card_def(game, ent)
        cost = _minion_buy_cost(game, hero, ent, d)
        # 强制生命支付：只检查生命是否足够（引擎同口径）；否则金币/生命
        # 任一可用。旧实现只看金币 → 会枚举出引擎必然拒绝的候选
        # （覆盖度审计 opponent_rejected: BG28_571 实测样本）。
        if _forced_health_buy(game, hero, ent, d, cost):
            if hero.health + hero.armor <= cost:
                continue
        elif hero.gold < cost and not _health_buy_possible(
                game, hero, ent, d, cost):
            continue
        out.append(_desc(ActionKind.BUY.value, src=ent, zones=zones,
                         cost=cost))
    return out


def _enumerate_sells(game: Game, hero: Hero, zones: Zones) -> List[ActionDescriptor]:
    out: List[ActionDescriptor] = []
    for slot, m in enumerate(zones.board):
        # 招募期棋盘上的随从都可出售（引擎无额外门槛）
        out.append(_desc(ActionKind.SELL.value, src=m, zones=zones,
                         cost=-1, note=f"slot={slot}"))
    return out


def _position_variants(n_board: int) -> List[int]:
    """打出随从的插入位置：-1（最右）优先，然后 0..n_board-1。"""
    return [-1] + list(range(n_board))


def _script_targets(script: Any, source: Any, game: Game) -> List[Any]:
    """按脚本声明的 ``target_candidates`` 求目标集（异常 → 空集）。

    默认口径与引擎一致：脚本未声明 ``target_candidates`` 时 =
    控制者/英雄本人棋盘上的存活随从。**注意 source 可能是 Hero**
    （英雄技能 `needs_target` 路径）：Hero 没有 ``controller`` 属性，
    此时默认候选 = `hero.board`（引擎 `_hero_power_target_ok` 同源）。
    """
    fn = getattr(script, "target_candidates", None)
    try:
        if fn is not None:
            return list(fn(source, game))
        ctrl = getattr(source, "controller", None)
        if ctrl is None and hasattr(source, "board"):
            ctrl = source                    # source 是 Hero（英雄技能）
        if ctrl is None:
            return []
        return [m for m in ctrl.board if not m.dead]
    except Exception:                                     # noqa: BLE001
        return []


def _post_summon_targets(game: Game, hero: Hero, script: Any,
                         minion: Any, position: int) -> List[Any]:
    """求「随从入场**之后**」的 ``target_candidates``（引擎同口径）。

    引擎在 `play_minion` 里先 `summon` 再求 `target_candidates`
    （`hsrl2/game.py::play_minion`），因此「以自身为目标」等候选只有在
    入场后才出现。本函数把 minion **临时**放进 `hero.board` 再求值：

    - 只改 `hero.board` 列表与 `ZONE_POSITION` tag（纯读观察点，不 fire
      任何事件、不改 `zone`——避免 `Entity.zone` setter 的手牌监听器
      注销副作用）；
    - `try/finally` 保证任何异常下恢复原 board/位置 tag；
    - 本函数对引擎状态是**只读等价**的（结束后逐位还原）。

    与真实入场后的差异仅有：`on_summon` 钩子/召唤广播未运行（它们可能
    改变棋盘）。因此结果**可能少枚举**，不会多枚举出非法目标——落在
    引擎候选集外时引擎按"战吼落空"处理（仍是合法动作）。
    """
    board = hero.board
    pos = len(board) if position is None or position < 0 \
        else min(int(position), len(board))
    saved_positions = [(m, m.get(GameTag.ZONE_POSITION, 0)) for m in board]
    saved_self_pos = minion.get(GameTag.ZONE_POSITION, None)
    try:
        board.insert(pos, minion)
        for idx, m in enumerate(board):
            m.set(GameTag.ZONE_POSITION, idx)
        return _script_targets(script, minion, game)
    finally:
        try:
            if minion in board:
                board.remove(minion)
        finally:
            for m, old in saved_positions:
                m.set(GameTag.ZONE_POSITION, old)
            if saved_self_pos is None:
                minion.clear(GameTag.ZONE_POSITION)
            else:
                minion.set(GameTag.ZONE_POSITION, saved_self_pos)


def _play_minion_variants(game: Game, hero: Hero, zones: Zones,
                          slot: int, ent: Any) -> List[ActionDescriptor]:
    """手牌随从的打出变体（位置 / 磁力吸附 / 战吼目标）。

    定向战吼的目标按引擎**入场后**口径求值（`_post_summon_targets`）：
    包含「以自身为目标」以及被召唤流程改变后的候选；对每个插入位置分别
    求值（相邻类战吼依赖位置）。若入场后候选含本步无法用槽位引用的实体
    （如对手棋盘），额外提供一个**不指定目标**的变体——引擎会挂起
    `PendingChoice(kind="battlecry_target")`（作为 choice 步暴露），
    从而任何合法目标组合仍可表达（`phase="choice"` 全选项）。
    """
    d = _card_def(game, ent)
    if d is not None and getattr(d, "unplayable", False):
        return []
    if ent.has(GameTag.LOCKED_IN_HAND):
        return []

    script = getattr(ent, "scripts", None)
    needs_target = bool(script is not None
                        and getattr(script, "needs_target", False))
    has_choose = bool(script is not None
                      and getattr(script, "choose_options", None))
    is_magnetic = ent.has(GameTag.MAGNETIC)
    board_full = hero.board_full()

    variants: List[ActionDescriptor] = []

    # ── 磁力吸附：不占棋盘格，可越过「棋盘已满」 ──
    attach_variants: List[ActionDescriptor] = []
    if is_magnetic:
        for tslot, host in enumerate(zones.board):
            if host.dead or host.controller is not hero:
                continue
            try:
                ok = game._magnetic_valid(ent, host)
            except Exception:                             # noqa: BLE001
                ok = False
            if ok:
                attach_variants.append(_desc(
                    ActionKind.PLAY_MINION.value, src=ent, zones=zones,
                    tgt=host, position=-1, cost=0, magnetic=True))

    def _normal(position: int, tgt: Any = None) -> ActionDescriptor:
        return _desc(ActionKind.PLAY_MINION.value, src=ent, zones=zones,
                     tgt=tgt, position=position, cost=0)

    if is_magnetic and attach_variants:
        # 磁力 + 战吼：吸附会跳过战吼（引擎语义），两种玩法语义互斥且
        # CandidateAction 签名会撞车（无 magnetic 字段）→ 只枚举吸附。
        variants.extend(attach_variants)
        if not board_full and not needs_target and not has_choose:
            variants.extend(_normal(p) for p in _position_variants(
                len(zones.board)))
        return variants

    if board_full:
        return variants

    if needs_target and not has_choose:
        positions = _position_variants(len(zones.board))
        mapped = 0
        unmapped = 0
        for p in positions:
            cands = _post_summon_targets(game, hero, script, ent, p)
            for t in cands:
                if zones.locate(t) is None:
                    unmapped += 1
                    continue
                variants.append(_normal(p, tgt=t))
                mapped += 1
        if mapped == 0:
            # 无可槽位引用的目标：不指定目标（引擎挂起选择或落空），
            # 仍为合法动作（战吼落空/交给 choice 步）
            variants.append(_normal(-1))
        elif unmapped:
            # 存在不可引用目标（对手棋盘/引擎内部实体）→ 追加挂起选择
            # 变体，保证这些目标经 `phase="choice"` 仍可选择
            variants.append(_normal(-1))
        return variants

    variants.extend(_normal(p) for p in _position_variants(len(zones.board)))
    return variants



def _play_spell_variants(game: Game, hero: Hero, zones: Zones,
                         slot: int, ent: Any) -> List[ActionDescriptor]:
    """手牌法术的施放变体（按脚本 needs_target 规则）。"""
    d = _card_def(game, ent)
    if d is not None and getattr(d, "unplayable", False):
        return []
    if ent.has(GameTag.LOCKED_IN_HAND):
        return []

    script = getattr(ent, "scripts", None)
    if script is not None and getattr(script, "choose_options", None):
        # Choose One：引擎挂起 choose_one 选择（选项即动作），无需目标
        return [_desc(ActionKind.PLAY_SPELL.value, src=ent, zones=zones,
                      cost=0)]
    if script is not None and getattr(script, "needs_target", False):
        cands = _script_targets(script, ent, game)
        variants: List[ActionDescriptor] = []
        unmapped = 0
        for t in cands:
            if zones.locate(t) is None:
                unmapped += 1
                continue
            variants.append(_desc(ActionKind.PLAY_SPELL.value, src=ent,
                                  zones=zones, tgt=t, cost=0))
        if variants:
            # 有可寻址目标 → 只给显式目标变体（不生成"无目标"回退，
            # 避免策略选到"先扣费/移除卡再要求 target"的退化路径）
            return variants
        # 目标候选为空 / 全部不可寻址（隐藏信息区域）：**不生成候选**
        # （宁缺勿错）。实测依据: BG28_518 Chef's Choice 等脚本在
        # `play_spell(target=None)` + 无候选时抛 GameStateError
        # "ctx['target'] required"（候选被引擎拒绝的唯一样本）；其余
        # 定向法术虽会"落空消耗"，但生成无目标候选会让策略误以为可
        # 以安全施放。见 docs/ENV_INTERFACE_GAPS.md §A1。
        return []
    return [_desc(ActionKind.PLAY_SPELL.value, src=ent, zones=zones, cost=0)]


def _hand_play_groups(game: Game, hero: Hero,
                      zones: Zones) -> List[List[ActionDescriptor]]:
    """手牌打出的**全部**变体（按手牌槽位分组，不受 CANDIDATE_MAX 限制）。

    供覆盖度审计统计"若不受上限限制会生成多少候选"；正式枚举用
    :func:`_apply_hand_budget` 按预算裁剪。
    """
    groups: List[List[ActionDescriptor]] = []
    for slot, ent in enumerate(zones.hand):
        if isinstance(ent, Minion):
            v = _play_minion_variants(game, hero, zones, slot, ent)
        elif isinstance(ent, Spell):
            v = _play_spell_variants(game, hero, zones, slot, ent)
        else:
            v = []
        if v:
            groups.append(v)
    return groups


def _apply_hand_budget(groups: List[List[ActionDescriptor]],
                       budget: int) -> tuple:
    """按 ``budget`` 裁剪手牌变体组；返回 ``(kept, dropped_groups)``。

    **轮转分配**（round-robin）: 先保证每个手牌实体至少 1 个变体
    （按组顺序取第一个变体 = 最优变体），再把剩余预算轮流加给各组。
    这样避免"早出现的手牌实体吃掉全部预算、后面的实体整组消失"——
    后者会让策略在满手牌时看不到可用动作（覆盖度审计 ``plays_dropped``）。

    ``dropped_groups`` = 因预算不足而**完全未出现**的手牌实体组数。
    """
    out: List[ActionDescriptor] = []
    if budget <= 0:
        return out, len(groups)
    n = len(groups)
    kept: List[List[ActionDescriptor]] = [[] for _ in range(n)]
    # 第一轮: 每组一个
    for i in range(n):
        if budget <= 0:
            break
        kept[i].append(groups[i][0])
        budget -= 1
    # 后续轮转: 轮流追加
    while budget > 0:
        progressed = False
        for i in range(n):
            if budget <= 0:
                break
            if len(kept[i]) < len(groups[i]):
                kept[i].append(groups[i][len(kept[i])])
                budget -= 1
                progressed = True
        if not progressed:
            break
    dropped_groups = sum(1 for i in range(n) if not kept[i])
    for i in range(n):
        out.extend(kept[i])
    return out, dropped_groups


def _enumerate_hand_plays(game: Game, hero: Hero, zones: Zones,
                          budget: int) -> List[ActionDescriptor]:
    """手牌打出（随从 + 法术），按手牌槽位顺序，受 ``budget`` 约束。"""
    groups = _hand_play_groups(game, hero, zones)
    kept, _dropped = _apply_hand_budget(groups, budget)
    return kept


def _enumerate_upgrade(game: Game, hero: Hero) -> List[ActionDescriptor]:
    next_tier = None
    try:
        next_tier = game._next_existing_tier(hero)
    except Exception:                                     # noqa: BLE001
        next_tier = None
    if next_tier is None or getattr(game, "_upgrade_blocked", False):
        return []
    cost = max(C.UPGRADE_COST_FLOOR,
               hero.upgrade_cost + hero.get(GameTag.UPGRADE_COST_MOD, 0))
    if hero.gold < cost:
        return []
    return [_desc(ActionKind.UPGRADE.value, cost=int(cost))]


def _enumerate_reroll(game: Game, hero: Hero) -> List[ActionDescriptor]:
    if getattr(game, "_block_manual_refresh", False):
        return []
    free_left = hero.get(GameTag.FREE_REFRESH_REMAINING, 0)
    health_left = hero.get(GameTag.HEALTH_REFRESHES_LEFT, 0)
    cost = hero.get(GameTag.REFRESH_COST_OVERRIDE, C.REFRESH_COST)
    affordable = (
        free_left > 0
        or (health_left > 0 and hero.health + hero.armor > C.REFRESH_COST)
        or hero.gold >= cost)
    if not affordable:
        return []
    return [_desc(ActionKind.REROLL.value, cost=0 if free_left > 0 else int(cost))]


#: 单个来源（英雄技能/随从/法术）最多生成的目标变体数。限制原因:
#: CANDIDATE_MAX=64 下，尾部动作（卖/技能/Activate 等）必须保留可用性；
#: 无限目标变体会挤掉其它类别（覆盖度审计 ``candidates_trimmed``）。
_MAX_TARGET_VARIANTS_PER_SOURCE = 6


def _enumerate_hero_powers(game: Game, hero: Hero,
                           zones: Zones) -> List[ActionDescriptor]:
    out: List[ActionDescriptor] = []
    from hsrl2.scripts import REGISTRY
    for slot, pid in enumerate(zones.power_ids):
        pdef = game.hero_power_def_for(hero, pid)
        if pdef is None:
            continue
        script = REGISTRY.get(pid) or REGISTRY.get(pdef.id)
        if script is None or getattr(script, "passive", False):
            continue
        try:
            avail_fn = getattr(script, "available", None)
            if avail_fn is not None and not avail_fn(hero, game):
                continue
        except Exception:                                 # noqa: BLE001
            continue
        max_uses = getattr(script, "uses_per_turn", 1) \
            + hero.extra_trigger("hp_uses")
        if hero._power_uses_this_turn.get(pid, 0) >= max_uses:
            continue
        per_game = getattr(script, "uses_per_game", None)
        if per_game is not None \
                and hero._power_uses_this_game.get(pid, 0) >= per_game:
            continue
        try:
            cost = game.hero_power_cost(hero, pdef, script)
        except Exception:                                 # noqa: BLE001
            cost = int(getattr(pdef, "cost", 0) or 0)
        if cost and hero.gold < cost:
            continue
        needs_target = bool(getattr(script, "needs_target", False))
        target_count = int(getattr(script, "target_count", 1)) \
            if needs_target else 0
        if target_count > 1:
            # 多目标技能（Vol'jin Spirit Swap target_count=2 等）:
            # 引擎 `use_hero_power(hero, target=None)` 会依次挂起
            # `PendingChoice(kind="hero_power_target")` 收集 N 个目标，
            # 收集后以 **list** 传入脚本 ctx["target"]。因此本层只需生成
            # 一个「不指定目标」的合法候选（候选数 ≥ N 才可用），具体的
            # N 元组合经 choice 步表达——不牺牲任何目标组合，不做近似。
            cands = _script_targets(script, hero, game)
            if len(cands) < target_count:
                continue
            out.append(_desc(ActionKind.HERO_POWER.value, zones=zones,
                             cost=int(cost),
                             power_id=pid, note=f"targets={target_count}"))
            continue
        if not needs_target:
            out.append(_desc(ActionKind.HERO_POWER.value, zones=zones,
                             cost=int(cost), power_id=pid))
            continue
        cands = _script_targets(script, hero, game)
        mapped = 0
        for t in cands:
            if zones.locate(t) is None:
                continue
            if mapped >= _MAX_TARGET_VARIANTS_PER_SOURCE:
                break
            mapped += 1
            out.append(_desc(ActionKind.HERO_POWER.value, zones=zones,
                             tgt=t, cost=int(cost), power_id=pid))
        if mapped == 0:
            # 无合法目标 → 引擎 use_hero_power 返回 False（不是合法动作）
            continue
    return out


def _trim_tail_preserving(tail: List[ActionDescriptor],
                          room: int) -> List[ActionDescriptor]:
    """极端情形下裁剪尾部动作：优先保留高价值类别（升级/刷新/冻结/
    Dark Gift/技能），最后才裁卖随从/Activate。``end_turn`` 由调用方保证。

    正常对局不会触发（尾部动作 ≤ ~30 < CANDIDATE_MAX）；触发时也**不会**
    把英雄技能/升级整个丢掉（旧实现的硬截断会，覆盖度审计可见）。
    """
    if len(tail) <= room:
        return tail
    if room <= 0:
        return []

    def _prio(d: ActionDescriptor) -> int:
        if d.kind == ActionKind.UPGRADE.value:
            return 100
        if d.kind == ActionKind.REROLL.value:
            return 95
        if d.kind == ActionKind.FREEZE.value:
            return 90
        if d.kind == ActionKind.USE_DARK_GIFT.value:
            return 85
        if d.kind == ActionKind.HERO_POWER.value:
            return 80 if d.tgt_entity is None else 60
        if d.kind == ActionKind.ACTIVATE.value:
            return 40
        if d.kind == ActionKind.SELL.value:
            return 30
        return 10

    keep = sorted(range(len(tail)), key=lambda i: (-_prio(tail[i]), i))[:room]
    keep.sort()
    return [tail[i] for i in keep]


def _enumerate_activate(game: Game, hero: Hero,
                        zones: Zones) -> List[ActionDescriptor]:
    out: List[ActionDescriptor] = []
    for m in zones.board:
        if not m.has(GameTag.ACTIVATE):
            continue
        if m.has(GameTag.ACTIVATE_USED_THIS_TURN):
            continue
        cost = int(m.get(GameTag.ACTIVATE_COST, 1))
        if hero.gold < cost:
            continue
        out.append(_desc(ActionKind.ACTIVATE.value, src=m, zones=zones,
                         cost=cost))
    return out


def _enumerate_dark_gift(game: Game, hero: Hero) -> List[ActionDescriptor]:
    state = game.dark_gift_state.get(hero)
    uses_left = C.DARK_GIFT_USES_PER_GAME if state is None \
        else int(state.get("uses_left", 0))
    used_this_turn = False if state is None \
        else bool(state.get("used_this_turn", False))
    if game.turn < C.DARK_GIFT_START_TURN:
        return []
    if uses_left <= 0 or used_this_turn:
        return []
    if hero.gold < C.DARK_GIFT_COST:
        return []
    return [_desc(ActionKind.USE_DARK_GIFT.value, cost=C.DARK_GIFT_COST)]


def enumerate_actions(game: Game, hero: Hero,
                      zones: Optional[Zones] = None,
                      stats: Optional[Dict[str, Any]] = None
                      ) -> List[ActionDescriptor]:
    """枚举该英雄当前**全部合法**的招募期动作（含 ``end_turn``）。

    保守原则：无法证明合法（金币/手牌/棋盘/目标规则不确定）的动作不生成。

    重要：``freeze`` 只生成**单向**候选（仅未冻结时）。冻结/解冻免费且
    可无限切换，双向候选会让随机策略陷入 freeze 循环（实测拖满
    ``max_steps``）——环境层另设每回合动作预算兜底。

    ``stats``: 可选计数器 dict（环境/审计用）。写入键：
      - ``candidates_generated``: 裁剪前的变体总数（含手牌全变体）
      - ``candidates_trimmed``: 因 CANDIDATE_MAX 被裁掉的变体数
      - ``plays_dropped``: 因预算不足而完全未出现的手牌实体组数
      - ``max_candidates_generated``: 单步裁剪前变体数最大值
      - ``max_candidates``: 单步返回候选数最大值
    """
    if zones is None:
        zones = collect_zones(game, hero)
    if hero.get(GameTag.TURN_SKIPPED, False):
        out = [_desc(ActionKind.END_TURN.value)]
        if stats is not None:
            stats["candidates_generated"] = stats.get(
                "candidates_generated", 0) + 1
            stats["max_candidates"] = max(stats.get("max_candidates", 0), 1)
        return out

    head: List[ActionDescriptor] = []
    head.extend(_enumerate_buys(game, hero, zones))

    tail: List[ActionDescriptor] = []
    tail.extend(_enumerate_sells(game, hero, zones))
    tail.extend(_enumerate_hero_powers(game, hero, zones))
    tail.extend(_enumerate_activate(game, hero, zones))
    tail.extend(_enumerate_upgrade(game, hero))
    tail.extend(_enumerate_reroll(game, hero))
    # 冻结：**单向**候选（只在"当前未冻结"时生成）。冻结/解冻是免费且
    # 可无限切换的合法动作，若两个方向都生成，随机策略会无限 toggle
    # （实测 2991/3000 步都是 freeze）→ 破坏训练/评测。ENV_SPEC 同步。
    if not hero.frozen_tavern:
        tail.append(_desc(ActionKind.FREEZE.value, cost=0))
    tail.extend(_enumerate_dark_gift(game, hero))

    end_turn = _desc(ActionKind.END_TURN.value)
    # 尾部动作在极端情形（多技能槽 × 多目标 + 满场卖/Activate）下也可能
    # 超过 CANDIDATE_MAX；先按优先级裁剪尾部，再把手牌预算给打出变体。
    tail = _trim_tail_preserving(tail, CANDIDATE_MAX - len(head) - 1)
    budget = CANDIDATE_MAX - len(tail) - 1 - len(head)
    groups = _hand_play_groups(game, hero, zones)
    plays, dropped_groups = _apply_hand_budget(groups, max(0, budget))
    out = head + plays + tail + [end_turn]
    if len(out) > CANDIDATE_MAX:                          # 理论兜底
        while plays and len(out) > CANDIDATE_MAX:
            plays.pop()
        out = head + plays + tail + [end_turn]
    assert len(out) <= CANDIDATE_MAX, len(out)

    if stats is not None:
        generated = len(head) + sum(len(g) for g in groups) + len(tail) + 1
        stats["candidates_generated"] = stats.get(
            "candidates_generated", 0) + generated
        stats["candidates_trimmed"] = stats.get(
            "candidates_trimmed", 0) + max(0, generated - len(out))
        stats["plays_dropped"] = stats.get(
            "plays_dropped", 0) + int(dropped_groups)
        stats["max_candidates_generated"] = max(
            stats.get("max_candidates_generated", 0), generated)
        stats["max_candidates"] = max(stats.get("max_candidates", 0),
                                      len(out))
    return out


def enumerate_step(game: Game, hero: Hero,
                   zones: Optional[Zones] = None,
                   stats: Optional[Dict[str, Any]] = None) -> StepActions:
    """一步的完整动作集（一次收集槽位、一次枚举、一次转候选）。"""
    if zones is None:
        zones = collect_zones(game, hero)
    descriptors = enumerate_actions(game, hero, zones, stats=stats)
    candidates = tuple(d.to_candidate() for d in descriptors)
    return StepActions(zones=zones, descriptors=descriptors,
                       candidates=candidates)


def enumerate_choice(game: Game, choice: PendingChoice,
                     zones: Optional[Zones] = None
                     ) -> List[ActionDescriptor]:
    """``choose`` 候选：``option`` = 选项下标（0 起）。"""
    return [ActionDescriptor(kind=ActionKind.CHOOSE.value, option=i,
                             cost=-1) for i in range(len(choice.options))]


# ══════════════════════════════════════════════════════════════════════
# 动作应用
# ══════════════════════════════════════════════════════════════════════


def _apply_choose(game: Game, hero: Hero, desc: ActionDescriptor) -> bool:
    if not game.pending_choices:
        raise GameStateError("choose: no pending choice")
    choice = game.pending_choices[0]
    if getattr(choice, "owner", None) is not hero:
        raise GameStateError("choose: front pending choice is not mine")
    if not 0 <= desc.option < len(choice.options):
        raise GameStateError(f"choose: option {desc.option} out of range")
    # 契约: choose 只结算不出队 → 由本函数 pop（ENV_SPEC / AGENTS §3）
    game.pending_choices.pop(0)
    choice.choose(desc.option)
    return True


def apply_action(game: Game, hero: Hero,
                 desc: ActionDescriptor) -> ApplyResult:
    """把动作应用到引擎。

    - 捕获 ``GameStateError`` 与其它异常 → ``ApplyResult(success=False)``；
    - 引擎以 ``False`` 表示「操作不合法」的 API 同样转为失败；
    - **不结算**动作产生的 ``PendingChoice``（由调用方按上下文处理）。
    """
    kind = desc.kind
    try:
        if kind == ActionKind.BUY.value:
            ok = game.buy_from_tavern(hero, desc.src_entity)
        elif kind == ActionKind.SELL.value:
            ok = game.sell_minion(hero, desc.src_entity)
        elif kind == ActionKind.PLAY_MINION.value:
            position = None if desc.position < 0 else int(desc.position)
            kwargs: Dict[str, Any] = {"position": position}
            if desc.tgt_entity is not None:
                if desc.magnetic:
                    kwargs["magnetic_target"] = desc.tgt_entity
                else:
                    kwargs["target"] = desc.tgt_entity
            ok = game.play_minion(hero, desc.src_entity, **kwargs)
        elif kind == ActionKind.PLAY_SPELL.value:
            ok = game.play_spell(hero, desc.src_entity,
                                 target=desc.tgt_entity)
        elif kind == ActionKind.REROLL.value:
            game.refresh_tavern(hero)
            ok = True
        elif kind == ActionKind.UPGRADE.value:
            ok = game.upgrade_tavern(hero)
        elif kind == ActionKind.FREEZE.value:
            if hero.frozen_tavern:
                hero.clear(GameTag.FROZEN)
            else:
                game.freeze_tavern(hero)
            ok = True
        elif kind == ActionKind.HERO_POWER.value:
            ok = game.use_hero_power(
                hero, target=desc.tgt_entity,
                power_id=(desc.power_id or None))
        elif kind == ActionKind.ACTIVATE.value:
            ok = game.use_activate(hero, desc.src_entity)
        elif kind == ActionKind.USE_DARK_GIFT.value:
            ok = game.use_dark_gift(hero)
        elif kind == ActionKind.END_TURN.value:
            ok = True
        elif kind == ActionKind.CHOOSE.value:
            ok = _apply_choose(game, hero, desc)
        else:
            return ApplyResult(success=False, kind=kind,
                               error=f"unknown action kind {kind!r}",
                               error_type="UnknownAction")
        if not ok:
            return ApplyResult(success=False, kind=kind,
                               error="engine_rejected",
                               error_type="Rejected")
        return ApplyResult(success=True, kind=kind)
    except GameStateError as exc:
        return ApplyResult(success=False, kind=kind, error=str(exc),
                           error_type="GameStateError")
    except Exception as exc:                              # noqa: BLE001
        # 环境层必须吞掉一切异常：训练进程不得因单次动作崩溃。
        return ApplyResult(success=False, kind=kind,
                           error=f"{type(exc).__name__}: {exc}",
                           error_type=type(exc).__name__)


# ══════════════════════════════════════════════════════════════════════
# PendingChoice 结算
# ══════════════════════════════════════════════════════════════════════


def _entity_power(obj: Any) -> int:
    atk = getattr(obj, "atk", None)
    health = getattr(obj, "health", None)
    if atk is None and health is None:
        return 0
    try:
        return int(atk or 0) + int(health or 0)
    except Exception:                                     # noqa: BLE001
        return 0


def default_pick_index(choice: PendingChoice, game: Optional[Game] = None) -> int:
    """自动结算 PendingChoice 的启发式选项下标（确定性）。

    用于「无法暂停」的阶段（对手招募 / 战斗 / 回合结束）与
    ``auto_choice=True``：挑价值最高的选项，而不是随机。
    """
    kind = getattr(choice, "kind", "")
    options = list(getattr(choice, "options", []) or [])
    if not options:
        return 0
    if kind == "choose_one" or kind.startswith("choose_"):
        return 0
    if kind == "quest_offer":
        return 0
    if kind == "opponent" or kind == "holmes_guess":
        return 0
    best_i, best_score = 0, None
    for i, opt in enumerate(options):
        score = 0.0
        if opt is None:
            score = -1e6                     # 「放弃」类选项优先级最低
        else:
            score = float(_entity_power(opt))
            d = None
            cid = None
            if isinstance(opt, str):
                cid = opt
            elif isinstance(opt, tuple) and len(opt) == 2 \
                    and isinstance(opt[0], str):
                cid = opt[0]
                score += 0.5                 # dark_gift：同分时偏好带 gift 的
            elif not isinstance(opt, tuple):
                cid = getattr(opt, "id", None) \
                    or getattr(opt, "card_id", None)
            if cid is not None and game is not None:
                try:
                    cd = game.db.get(cid)
                except Exception:                         # noqa: BLE001
                    cd = None
                if cd is not None:
                    score += float(getattr(cd, "tech_level", 0) or 0) * 0.5
        if best_score is None or score > best_score:
            best_i, best_score = i, score
    return best_i


def resolve_pending_choices(
        game: Game,
        hero: Optional[Hero] = None,
        policy_fn: Optional[Any] = None,
        *,
        cap: int = 400,
        errors: Optional[List[str]] = None) -> Optional[PendingChoice]:
    """结算 ``game.pending_choices``（FIFO: 弹出 → choose → 已弹出）。

    参数
    ----
    hero:
        - ``None``：结算**全部**选择（自动启发式），用于对手/战斗阶段；
        - 给定英雄且 ``policy_fn is None``：结算**除该英雄外**的全部选择，
          遇到队首属于该英雄的选择时**不弹出并返回它**（作为
          ``phase="choice"`` 观测暴露给策略）；
        - 给定英雄且 ``policy_fn`` 给出：该英雄的选择也用
          ``policy_fn(choice) -> int`` 结算（``auto_choice=True``）。
    policy_fn:
        可选回调，签名 ``(choice) -> int``。
    errors:
        可选列表；被捕获的结算异常消息追加于此（环境层计数用）。

    返回：仍待该英雄决策的队首选择（没有则 ``None``）。
    """
    n = 0
    while game.pending_choices and n < cap:
        choice = game.pending_choices[0]
        owner = getattr(choice, "owner", None)
        is_agent = hero is not None and owner is hero
        if is_agent and policy_fn is None:
            return choice
        game.pending_choices.pop(0)
        n += 1
        try:
            if is_agent and policy_fn is not None:
                idx = int(policy_fn(choice))
            else:
                idx = default_pick_index(choice, game)
            if not 0 <= idx < len(choice.options):
                idx = 0
            choice.choose(idx)
        except Exception as exc:                          # noqa: BLE001
            if errors is not None:
                errors.append(f"{type(exc).__name__}: {exc}")
    return None


class ChoiceQueue(list):
    """``game.pending_choices`` 的替身：``append`` 即自动结算（FIFO）。

    用途：``Game.end_recruit_phase()`` 是**不可暂停**的同步阶段（EoT 效果
    → 配对战斗 → 幽灵战 → 淘汰 → 下一回合开始）。该阶段产生的
    ``PendingChoice`` 无法暴露成 ``phase="choice"`` 决策步，只能在产生时
    就地结算。把 ``game.pending_choices`` 临时替换为本类即可实现
    「入队即结算」，且保持与显式 FIFO 结算完全相同的队内顺序。

    ``hold_fn(choice) -> bool``：返回 True 时**不**自动结算（留在队列里），
    用于「新回合开始后属于智能体的选择」（任务/饰品三选一）——它们应在
    阶段结束后作为 choice 观测暴露。

    结算异常被捕获并记入 ``errors``，绝不向引擎调用栈传播。
    """

    def __init__(self, game: Game, *, picker: Any = None,
                 hold_fn: Any = None, cap: int = 2000,
                 errors: Optional[List[str]] = None):
        super().__init__()
        self._game = game
        self._picker = picker or (lambda c: default_pick_index(c, game))
        self._hold_fn = hold_fn
        self._cap = cap
        self._errors = errors if errors is not None else []
        self._busy = False
        self.drained = 0

    # list 的 append 是引擎唯一写入点；这里「入队即结算」
    def append(self, choice: Any) -> None:                # type: ignore[override]
        super().append(choice)
        if self._busy:
            return
        self._busy = True
        try:
            self._drain()
        finally:
            self._busy = False

    def _drain(self) -> None:
        while self and self.drained < self._cap:
            head = self[0]
            if self._hold_fn is not None and self._hold_fn(head):
                return
            self.pop(0)
            self.drained += 1
            try:
                idx = int(self._picker(head))
                if not 0 <= idx < len(head.options):
                    idx = 0
                head.choose(idx)
            except Exception as exc:                      # noqa: BLE001
                self._errors.append(f"{type(exc).__name__}: {exc}")


# 兼容别名：测试/工具里按枚举语义命名
enumerate_action = enumerate_actions
