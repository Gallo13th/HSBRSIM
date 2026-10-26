"""环境/引擎结构不变量（只读检查）与状态 digest。

移植来源
--------
AutoTavern ``crates/taverngym/src/invariants.rs``：

- ``check(g) -> Vec<String>``：结构不变量（棋盘/手牌/酒馆容量、tier、
  金币、存活血量、随从属性、实体唯一性、名次不重复）；
- ``pool_balance(g)`` / ``pool_species_violations(g)``：随从池守恒。

本模块把 ``check`` 移植到 HSBRSIM 的引擎（``hsrl2.Game``）与环境
（``hsbg.env.BattlegroundsEnv``）语义，并把 pool 守恒**登记为不移植**
（原因见 :func:`check_game` 文档末尾「与 AutoTavern 的差异」）。

设计契约（与 AutoTavern 一致）
---------------------------
1. **只读**：不修改引擎/环境状态、不消耗 RNG、不触发事件、不改 ``_stats``。
   调用方可在任意决策点调用（例如 ``scripts/validate_env.py`` 每一步后）。
2. **不崩溃**：所有检查防御式实现（``getattr`` + 局部 ``try/except``）；
   单个属性读取失败只记一条 ``check_error:*`` 违反项，继续检查其余部分。
3. **返回违反项列表**：空列表 = 通过；**不得**在内部 ``assert``/抛异常。

入口
----
- :func:`check_game`：纯引擎结构不变量（不依赖 env）；
- :func:`check_env`：在 :func:`check_game` 之上追加环境层不变量
  （名次追踪 / 大厅视图 / 候选动作 / ``obs`` 一致性）；
- :func:`state_digest`：稳定状态摘要（snapshot/restore 对拍与回归用，
  不含 ``id()`` / 地址 / 哈希顺序，跨进程稳定）；
- :func:`effective_tavern_capacity`：按引擎「额外展示位」机制估算的酒馆
  容量（供文档/审计；默认不参与硬断言，见下）。

与 AutoTavern ``invariants.rs`` 的差异（逐项）
--------------------------------------------
移植：
  * 每个英雄 ``board <= 7`` / ``hand <= 10`` / ``tavern <= 7``（后者见
    「已知偏差 1」，默认只做硬上限检查，7 是 spec 展示位契约）；
  * ``tier ∈ 1..7``、``gold >= 0``；
  * 存活 ⇒ ``health > 0``；
  * 棋盘无死亡随从；
  * ``atk >= 0``、``max_hp > 0``、``hp <= max_hp``；
  * 实体唯一性（同一对象/同一 uuid 不得同时出现在两个区域）；
  * 名次合法（见「已知偏差 2」）。

不移植 / 改写：
  1. **pool 守恒**（``pool_balance`` / ``pool_species_violations``）：
     HSBRSIM 明确允许「效果生成的副本不占池」（RULES §2.3；金色返还 3
     份、Reno 金色化返还 1 份、`purge` 永久移除、`_injected` 注入……），
     逐卡/总量守恒按设计就**不成立**；强行移植会每天报假警。改为在
     :func:`check_game` 内做**池簿记合法性**弱检查（剩余量非负、purge
     后不得回池、池剩余量不超过初始副本数上限），见
     :func:`_check_pools`。
  2. **酒馆容量硬约束 ``tavern <= 7``**：实测引擎会因**额外展示位**
     机制超过 7（详见「已知偏差 1」），默认只在
     ``strict_tavern_slots=True`` 时按 spec 契约报告。
  3. **名次不重复**：实测同回合多名玩家被淘汰时，环境记录的公式
     ``rank = 存活人数 + 1`` 会产生**并列名次**（AutoTavern 断言不重复）。
     默认按「非递增 + 上界」检查；``strict_unique_ranks=True`` 时把并列
     名次报告为违反项（详见「已知偏差 2」）。
  4. **池/界面容量**（``N_SHOP``/``N_CHOICE``/``N_POWERS``/``N_QUESTS``/
     ``N_SECRETS``）：HSBRSIM 的观测契约只有 ``spec.py`` 的
     ``CANDIDATE_MAX=64`` / 区域槽位上限；其余 AutoTavern 内部界面常量
     在此引擎不存在，省略。

已知偏差 1：酒馆展示位可以 > 7（真实引擎行为，非本次引入）
------------------------------------------------------------
引擎 ``Game.refresh_tavern`` 的展示位 = 基础位
``C.TAVERN_OFFERS[tier]``（T1=3 … T6=6）+ ``TAVERN_OFFER_MOD`` +
额外关键词位（Electrode Attractor）+ 额外档位位（Innkeeper's Stein）+
``TAVERN_SPELLS_PER_REFRESH=1`` 张酒馆法术 + Fodder token + 刷新后
效果追加（如 Varden ``BG22_HERO_004p`` 「After the Tavern is Refreshed,
copy its highest-Tier minion」）。所以 **8 张是合法状态**（实测
seed=3005 turn=9 酒馆 8 张：7 随从 + 1 法术）。

连带影响（已上报 Lead，登记为**观测契约缺口**，不属本模块可修范围）：
``spec.TAVERN_MAX = 7`` 但 ``observation.build_observation`` **不截断**
tavern，``policy/encoder.entity_index(slot=7)`` 返回 ``-1`` → 第 8 个
展示位在策略输入里**静默丢失**（动作仍可按候选下标选出，但无法指向该
实体）。默认不把 ``tavern > 7`` 记为违反项，避免对合法引擎状态报警；
``strict_tavern_slots=True`` 可显式检查该 spec 契约。

已知偏差 2：同回合多淘汰 → 名次并列
------------------------------------
``env._on_hero_eliminated`` 记录 ``rank = 被淘汰时 game.heroes 内存活数
+ 1``；同一 ``_process_eliminations`` 批次里多个英雄死亡时，公式对每个
死者都算出**同一个**名次（实测 seed=2003：P3/P4/P7 同回合死亡 → 名次
全部 = 5）。环境 docstring 明确该公式（"rank = 被淘汰时存活人数 + 1"），
故默认只检查：``1 <= rank <= N``、沿淘汰顺序**非递增**、
``rank <= N - i``（唯一名次上界）、与 ``game.heroes`` 的计数一致。
``strict_unique_ranks=True`` 时把并列名次报告为违反项（供审计/和官方
口径对齐时使用）。

环境层附加不变量（AutoTavern 无对应物，按 HSBRSIM env 语义新增）
---------------------------------------------------------------
* ``env._all_heroes is env.game.heroes`` 的**元素同一性**：该列表在
  ``reset`` 里与 ``Game.heroes`` 是**同一个 list 对象**（实测），淘汰时
  一起原地缩短。snapshot/restore 必须保留这个别名关系，否则后续淘汰的
  ``remove`` 只作用于 ``game.heroes``，大厅视图会漂移。
* ``len(game.heroes) + len(_elimination_order) == N``（监听器完整时）；
* ``_rank_by_hero`` / ``_elimination_order`` 与存活/淘汰集合一致；
* ``_turn_count == game.turn``、``stats['steps'] == _step_count``；
* ``_obs`` 与当前状态一致（phase / 候选 / 大厅 / 名次）；
* 候选动作结构合法（``<= CANDIDATE_MAX``、签名不重复、``action_mask``
  全 True、``legal_actions() == obs.candidates``）；
* ``PendingChoice`` 队列只剩智能体自己的选择（非智能体选择由 env 自动
  结算——ENV_SPEC §4 / TEST_SOP §8）；
* 有界历史容器不超上限（``_errors<=200``、``_auto_resolved_choices<=64``、
  ``_choice_failures<=64``——与 ``game_env`` 的写入上限一致）。
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Sequence, Tuple

import hsrl2.constants as C
from hsrl2.tags import CardType, GameTag

__all__ = [
    "check_game",
    "check_env",
    "state_digest",
    "effective_tavern_capacity",
]

#: ``_errors`` / ``_auto_resolved_choices`` / ``_choice_failures`` 的
#: 写入上限（与 ``hsbg/env/game_env.py`` 一致；只读检查用）
_ERRORS_CAP = 200
_AUTO_RESOLVED_CAP = 64
_CHOICE_FAILURES_CAP = 64


# ══════════════════════════════════════════════════════════════════════
# 防御式读取工具
# ══════════════════════════════════════════════════════════════════════


def _safe_int(value: Any, default: int = 0) -> int:
    """``int(value)`` 的防御版本（失败 → default）。"""
    try:
        return int(value)
    except Exception:                                     # noqa: BLE001
        return int(default)


def _safe_len(value: Any) -> int:
    try:
        return len(value)
    except Exception:                                     # noqa: BLE001
        return -1


def _hero_label(hero: Any) -> str:
    """英雄在违反项里的稳定标签（优先 seat 名 P0..P7）。"""
    try:
        name = str(getattr(hero, "name", "") or "")
    except Exception:                                     # noqa: BLE001
        name = ""
    if name:
        return name
    try:
        return str(getattr(hero, "card_id", "") or "?")
    except Exception:                                     # noqa: BLE001
        return "?"


def _entity_ref(entity: Any) -> str:
    """实体的稳定引用串（uuid 优先，禁止出现内存地址）。"""
    try:
        uid = getattr(entity, "uuid", None)
        if isinstance(uid, str) and uid:
            return uid
    except Exception:                                     # noqa: BLE001
        pass
    try:
        return str(getattr(entity, "card_id", "?"))
    except Exception:                                     # noqa: BLE001
        return "?"


def _entity_uuid(entity: Any) -> Optional[str]:
    try:
        uid = getattr(entity, "uuid", None)
        return uid if isinstance(uid, str) and uid else None
    except Exception:                                     # noqa: BLE001
        return None


def _is_minion(entity: Any) -> bool:
    """该实体是否随从（避免 import Minion 造成循环依赖，按 cardtype 判）。"""
    try:
        return int(entity.get(GameTag.CARDTYPE, -1)) == int(CardType.MINION)
    except Exception:                                     # noqa: BLE001
        try:
            return type(entity).__name__ == "Minion"
        except Exception:                                 # noqa: BLE001
            return False


def _is_spell(entity: Any) -> bool:
    try:
        return int(entity.get(GameTag.CARDTYPE, -1)) == int(CardType.SPELL)
    except Exception:                                     # noqa: BLE001
        try:
            return type(entity).__name__ == "Spell"
        except Exception:                                 # noqa: BLE001
            return False


# ══════════════════════════════════════════════════════════════════════
# 酒馆容量估算（额外展示位机制；仅文档/审计用）
# ══════════════════════════════════════════════════════════════════════


def effective_tavern_capacity(hero: Any, game: Any = None) -> Optional[int]:
    """按引擎「额外展示位」机制估算该英雄酒馆的**标称**容量。

    覆盖 ``Game.refresh_tavern`` 的可静态推导部分：
    基础位 ``C.TAVERN_OFFERS[tier]``（或 ``_tavern_offer_override``）+
    ``TAVERN_OFFER_MOD`` + 生效中的额外关键词位 +
    ``TAVERN_EXTRA_TIER_SLOTS`` + 酒馆法术位（``TAVERN_SPELLS_PER_REFRESH``
    + ``_tavern_spell_extra``）+ 刷新附加 Fodder（``_fodder_refresh_pending``）。

    **不含**「刷新后效果追加」类（Varden 复制、Laboratory Assistant 等），
    故返回值是**下界**，只用于审计/文档，不参与默认硬断言。任何读取失败
    → ``None``（调用方跳过）。
    """
    try:
        tier = _safe_int(getattr(hero, "tavern_tier", 1), 1)
        override = getattr(hero, "_tavern_offer_override", None)
        if override is None and game is not None:
            override = getattr(game, "_tavern_offer_override", None)
        if override is not None:
            base = _safe_int(override, 7)
        else:
            base = _safe_int(C.TAVERN_OFFERS.get(tier, 6), 6) + _safe_int(
                hero.get(GameTag.TAVERN_OFFER_MOD, 0), 0)
        extra_keyword = 0
        for rule in list(getattr(hero, "_tavern_extra_keyword", None) or []):
            try:
                src, _kws, n = rule
            except Exception:                             # noqa: BLE001
                continue
            if src is None:
                continue
            try:
                active = (src in (getattr(hero, "trinkets", None) or [])
                          or src in (getattr(hero, "quest_rewards", None) or [])
                          or src in (getattr(hero, "board", None) or []))
            except Exception:                             # noqa: BLE001
                active = False
            if active:
                extra_keyword += max(0, _safe_int(n, 0))
        extra_tier = max(0, _safe_int(
            hero.get(GameTag.TAVERN_EXTRA_TIER_SLOTS, 0), 0))
        spell_extra = getattr(hero, "_tavern_spell_extra", None)
        if spell_extra is None and game is not None:
            spell_extra = getattr(game, "_tavern_spell_extra", 0)
        spell_slots = max(0, _safe_int(C.TAVERN_SPELLS_PER_REFRESH, 1)
                          + _safe_int(spell_extra, 0))
        fodder = 0
        if game is not None:
            try:
                pending = (getattr(game, "_fodder_refresh_pending", None)
                           or {}).get(hero)
                if pending:
                    fodder = max(0, _safe_int(pending[1], 0))
            except Exception:                             # noqa: BLE001
                fodder = 0
        return int(base + extra_keyword + extra_tier + spell_slots + fodder)
    except Exception:                                     # noqa: BLE001
        return None


# ══════════════════════════════════════════════════════════════════════
# 结构检查（引擎层）
# ══════════════════════════════════════════════════════════════════════


def _check_hero_scalars(hero: Any, bad: List[str]) -> None:
    """英雄标量：tier / gold / 存活血量 / 护甲。"""
    who = _hero_label(hero)
    tier = _safe_int(getattr(hero, "tavern_tier", 1), 1)
    if not 1 <= tier <= 7:
        bad.append(f"hero[{who}]: tavern_tier={tier} 不在 1..7")
    gold = _safe_int(getattr(hero, "gold", 0), 0)
    if gold < 0:
        bad.append(f"hero[{who}]: gold={gold} < 0")
    health = _safe_int(getattr(hero, "health", 0), 0)
    armor = _safe_int(getattr(hero, "armor", 0), 0)
    if health < 0:
        bad.append(f"hero[{who}]: health={health} < 0")
    if armor < 0:
        bad.append(f"hero[{who}]: armor={armor} < 0")
    try:
        alive = bool(hero.is_alive)
    except Exception:                                     # noqa: BLE001
        alive = health + armor > 0
    if alive and health <= 0:
        bad.append(f"hero[{who}]: alive 但 health={health}（armor={armor}）")


def _check_hero_zones(hero: Any, bad: List[str],
                      seen_entities: Dict[int, str],
                      seen_uuids: Dict[str, str]) -> None:
    """区域容量 + 区域实体合法 + 实体唯一性（跨英雄全局）。"""
    who = _hero_label(hero)
    zones = (
        ("board", getattr(hero, "board", None), C.BOARD_SIZE),
        ("hand", getattr(hero, "hand", None), C.HAND_SIZE),
        # 酒馆展示位：基础位 + 额外展示位机制可超过 7（见模块文档
        # 「已知偏差 1」）→ 这里只做硬上限（含效果追加的宽松上界）。
        ("tavern", getattr(hero, "tavern", None), None),
    )
    for zone, arr, cap in zones:
        n = _safe_len(arr)
        if n < 0:
            bad.append(f"hero[{who}]: {zone} 不是可读序列")
            continue
        if cap is not None and n > cap:
            bad.append(f"hero[{who}]: {zone}={n} > 上限 {cap}")
        for slot, entity in enumerate(list(arr)):
            if entity is None:
                bad.append(f"hero[{who}]: {zone}[{slot}] is None")
                continue
            entity_tag = f"hero[{who}]:{zone}[{slot}]"
            oid = id(entity)
            prev = seen_entities.get(oid)
            if prev is not None:
                bad.append(f"{entity_tag}: 实体重复出现（已在 {prev}）")
            else:
                seen_entities[oid] = entity_tag
            uid = _entity_uuid(entity)
            if uid is not None:
                prev_uuid = seen_uuids.get(uid)
                if prev_uuid is not None:
                    bad.append(f"{entity_tag}: uuid={uid} 重复（已在 "
                               f"{prev_uuid}）")
                else:
                    seen_uuids[uid] = entity_tag
            if zone == "tavern":
                if not (_is_minion(entity) or _is_spell(entity)):
                    bad.append(f"{entity_tag}: 酒馆实体既非随从也非法术 "
                               f"({type(entity).__name__})")
            elif zone == "board":
                if not _is_minion(entity):
                    bad.append(f"{entity_tag}: 非随从实体进入 board "
                               f"({type(entity).__name__})")
            elif not (_is_minion(entity) or _is_spell(entity)):
                # 手牌区可同时含随从与酒馆法术（RULES §6.17）
                bad.append(f"{entity_tag}: 非法实体进入 hand "
                           f"({type(entity).__name__})")


def _check_minion_stats(hero: Any, bad: List[str]) -> None:
    """随从数值：棋盘不得有死亡随从；atk>=0；max_hp>0；hp<=max_hp。"""
    who = _hero_label(hero)
    board = getattr(hero, "board", None) or []
    for slot, m in enumerate(list(board)):
        try:
            name = str(getattr(m, "card_id", "?") or "?")
        except Exception:                                 # noqa: BLE001
            name = "?"
        try:
            if bool(m.dead):
                bad.append(f"hero[{who}]: 棋盘[{slot}] {name} 已死亡")
        except Exception as exc:                          # noqa: BLE001
            bad.append(f"hero[{who}]: 棋盘[{slot}] dead 读取失败: "
                       f"{type(exc).__name__}")
        try:
            atk = _safe_int(m.atk, 0)
            if atk < 0:
                bad.append(f"hero[{who}]: 棋盘[{slot}] {name} atk={atk} < 0")
        except Exception as exc:                          # noqa: BLE001
            bad.append(f"hero[{who}]: 棋盘[{slot}] {name} atk 读取失败: "
                       f"{type(exc).__name__}")
        try:
            hp = _safe_int(m.health, 0)
            max_hp = _safe_int(m.max_health, 0)
            if max_hp <= 0:
                bad.append(f"hero[{who}]: 棋盘[{slot}] {name} "
                           f"max_health={max_hp} <= 0")
            elif hp > max_hp:
                bad.append(f"hero[{who}]: 棋盘[{slot}] {name} "
                           f"health={hp} > max_health={max_hp}")
        except Exception as exc:                          # noqa: BLE001
            bad.append(f"hero[{who}]: 棋盘[{slot}] {name} 生命读取失败: "
                       f"{type(exc).__name__}")
    # 手牌/酒馆随从: 属性合法性（AutoTavern 对三区域统一检查）
    for zone in ("hand", "tavern"):
        arr = getattr(hero, zone, None) or []
        for slot, m in enumerate(list(arr)):
            if not _is_minion(m):
                continue
            try:
                atk = _safe_int(m.atk, 0)
                max_hp = _safe_int(m.max_health, 0)
            except Exception:                             # noqa: BLE001
                continue
            name = str(getattr(m, "card_id", "?") or "?")
            if atk < 0:
                bad.append(f"hero[{who}]: {zone}[{slot}] {name} atk={atk} < 0")
            if max_hp <= 0:
                bad.append(f"hero[{who}]: {zone}[{slot}] {name} "
                           f"max_health={max_hp} <= 0")


def _check_pools(game: Any, bad: List[str]) -> None:
    """池簿记合法性（替代 AutoTavern 的池守恒——见模块文档）。

    检查项（全部是 HSBRSIM 自身**必须**成立的簿记约束）：
      * 随从池/法术池剩余量非负；
      * 被 ``purge`` 的卡剩余量必须为 0（永久移除语义）；
      * 池 ``_available`` 的值必须是整数。

    **不检查剩余量上限**：RULES §2.3 明确「效果生成的副本不占池；该副本
    出售/淘汰时按常规回池」→ 池会**净增**（实测 seed=3200 中出现
    剩余 12 > 初始 11 的合法状态）。这正是 AutoTavern ``pool_balance``
    不能直接移植的原因。
    """
    for pool_name in ("minion_pool", "spell_pool"):
        pool = getattr(game, pool_name, None)
        if pool is None:
            continue
        available = getattr(pool, "_available", None)
        if not isinstance(available, dict):
            continue
        purged = getattr(pool, "_purged", None)
        for card_id, count in list(available.items()):
            try:
                n = int(count)
            except Exception:                             # noqa: BLE001
                bad.append(f"pool[{pool_name}]: {card_id} 剩余量不可解析: "
                           f"{type(count).__name__}")
                continue
            if n < 0:
                bad.append(f"pool[{pool_name}]: {card_id} 剩余量 {n} < 0")
                continue
            if purged is not None and card_id in purged and n > 0:
                bad.append(f"pool[{pool_name}]: {card_id} 已 purge 但剩余 "
                           f"{n} 份")


def check_game(game: Any, *, agent: Any = None,
               strict_tavern_slots: bool = False) -> List[str]:
    """纯引擎结构不变量检查（只读；返回违反项列表）。

    参数
    ----
    game : ``hsrl2.game.Game``
    agent : 可选；给定则额外检查「智能体英雄必须在大厅英雄列表里」。
    strict_tavern_slots : 是否按 ``spec.TAVERN_MAX=7`` 检查酒馆展示位
        （默认关闭——真实引擎会因额外展示位机制超过 7，见模块文档）。

    与 AutoTavern 的差异见模块 docstring；本函数**不含**环境层状态
    （名次追踪等），那部分在 :func:`check_env`。
    """
    bad: List[str] = []
    if game is None:
        return ["game is None"]
    try:
        heroes = list(getattr(game, "heroes", None) or [])
    except Exception as exc:                              # noqa: BLE001
        return [f"game.heroes 读取失败: {type(exc).__name__}: {exc}"]
    if not heroes:
        bad.append("game.heroes 为空")
    seen_ids: Dict[int, str] = {}
    seen_uuids: Dict[str, str] = {}
    for hero in heroes:
        if hero is None:
            bad.append("game.heroes 含 None")
            continue
        try:
            if getattr(hero, "game", None) is not game:
                bad.append(f"hero[{_hero_label(hero)}]: hero.game 不是本局 "
                           f"game")
        except Exception:                                 # noqa: BLE001
            pass
        _check_hero_scalars(hero, bad)
        _check_hero_zones(hero, bad, seen_ids, seen_uuids)
        _check_minion_stats(hero, bad)
        if strict_tavern_slots:
            n = _safe_len(getattr(hero, "tavern", None))
            if n > 7:
                bad.append(f"hero[{_hero_label(hero)}]: tavern={n} > "
                           f"spec.TAVERN_MAX=7")
    try:
        if agent is not None and all(h is not agent for h in heroes):
            bad.append(f"agent[{_hero_label(agent)}] 不在 game.heroes 中")
    except Exception:                                     # noqa: BLE001
        pass
    _check_pools(game, bad)
    return bad


# ══════════════════════════════════════════════════════════════════════
# 环境层不变量
# ══════════════════════════════════════════════════════════════════════


def _check_rank_tracking(env: Any, bad: List[str],
                         strict_unique_ranks: bool,
                         terminal: bool = False) -> None:
    """名次追踪：``_rank_by_hero`` / ``_elimination_order`` 一致性。

    ``terminal=True``（``env._done`` 后的终局面）时**放宽**两项只在前
    终局前成立的检查：终局出口会先注销智能体监听器，同回合后续淘汰不再
    被记录，因此「人数守恒」「最后一个淘汰者名次 = 当前存活+1」两类
    检查只对非终局状态成立。
    """
    game = getattr(env, "game", None)
    if game is None:
        return
    heroes = list(getattr(game, "heroes", None) or [])
    try:
        n_players = int(getattr(env.config, "num_players", len(heroes)))
    except Exception:                                     # noqa: BLE001
        n_players = len(heroes)
    elimination = list(getattr(env, "_elimination_order", None) or [])
    rank_map = getattr(env, "_rank_by_hero", None)
    if not isinstance(rank_map, dict):
        bad.append("_rank_by_hero 不是 dict")
        return
    # 淘汰顺序：对象不重复、不得仍在 game.heroes
    seen: Dict[int, int] = {}
    for i, hero in enumerate(elimination):
        if hero is None:
            bad.append("_elimination_order 含 None")
            continue
        if id(hero) in seen:
            bad.append(f"_elimination_order[{i}] 重复"
                       f"（已在 [{seen[id(hero)]}]）")
        else:
            seen[id(hero)] = i
        if any(h is hero for h in heroes):
            bad.append(f"_elimination_order[{i}] {_hero_label(hero)} 仍在 "
                       f"game.heroes")
    # 计数一致性（终局面可能因监听器注销而欠记账 → 跳过）
    if not terminal and len(heroes) + len(elimination) != n_players:
        bad.append(f"大厅人数 {len(heroes)} + 已淘汰 {len(elimination)} != "
                   f"num_players {n_players}")
    if len(rank_map) != len(elimination):
        bad.append(f"_rank_by_hero 条目 {len(rank_map)} != "
                   f"_elimination_order {len(elimination)}")
    # rank 映射的 key 必须恰好指向淘汰英雄
    known_ids = {id(h) for h in elimination}
    unknown = [key for key in rank_map if key not in known_ids]
    if unknown:
        bad.append(f"_rank_by_hero 含 {len(unknown)} 个非淘汰英雄的 key")
    ranks: List[int] = []
    for i, hero in enumerate(elimination):
        who = _hero_label(hero)
        if id(hero) not in rank_map:
            bad.append(f"_rank_by_hero 缺少淘汰英雄 {who}（第 {i} 个）")
            continue
        rank = _safe_int(rank_map.get(id(hero)), -1)
        ranks.append(rank)
        if not 1 <= rank <= n_players:
            bad.append(f"_rank_by_hero[{who}]={rank} 不在 1..{n_players}")
        if rank < 2:
            bad.append(f"_rank_by_hero[{who}]={rank} < 2（被淘汰不可能是"
                       f"冠军名次）")
        # 唯一名次上界：第 i 个被记录（0 基）的淘汰者名次 <= N - i
        if rank > n_players - i:
            bad.append(f"_rank_by_hero[{who}]={rank} > 唯一名次上界 "
                       f"{n_players - i}（第 {i} 个淘汰）")
        # 已淘汰者名次必须比当前存活人数更差（终局面可能有未记录的
        # 同回合淘汰 → 跳过该检查）
        alive_now = len(heroes)
        if not terminal and rank <= alive_now:
            bad.append(f"_rank_by_hero[{who}]={rank} <= 当前存活数 "
                       f"{alive_now}")
    # 沿淘汰顺序名次非递增（同回合并列允许）
    for a, b in zip(ranks, ranks[1:]):
        if b > a:
            bad.append(f"_rank_by_hero 名次非递增被破坏: {ranks}")
            break
    if strict_unique_ranks and len(ranks) != len(set(ranks)):
        bad.append(f"_rank_by_hero 名次并列: {sorted(ranks, reverse=True)}")


def _check_all_heroes_view(env: Any, bad: List[str],
                           terminal: bool = False) -> None:
    """``_all_heroes`` 与 ``game.heroes`` 的别名/内容一致性。

    ``terminal=True`` 时不检查「agent 必须在 game.heroes」——智能体被淘汰
    后引擎会把它从 heroes 移除（这是终局的正常形态）。
    """
    game = getattr(env, "game", None)
    if game is None:
        return
    game_heroes = list(getattr(game, "heroes", None) or [])
    all_heroes = getattr(env, "_all_heroes", None)
    if all_heroes is None:
        bad.append("env._all_heroes is None")
        return
    try:
        view = list(all_heroes)
    except Exception:                                     # noqa: BLE001
        bad.append("env._all_heroes 不是可读序列")
        return
    if len(view) != len(game_heroes):
        bad.append(f"env._all_heroes 长度 {len(view)} != game.heroes "
                   f"{len(game_heroes)}")
    for i, (a, b) in enumerate(zip(view, game_heroes)):
        if a is not b:
            bad.append(f"env._all_heroes[{i}] 与 game.heroes[{i}] 不是同一"
                       f"对象（大厅视图漂移）")
            break
    agent = getattr(env, "_agent", None)
    if agent is not None and not terminal:
        if not any(h is agent for h in game_heroes):
            bad.append("env._agent 不在 game.heroes 中")
        elif any(h is agent for h in view) is False:
            bad.append("env._agent 不在 _all_heroes 中")


def _check_env_counters(env: Any, bad: List[str]) -> None:
    """环境计数器/有界历史/终止标志一致性。"""
    game = getattr(env, "game", None)
    step_count = _safe_int(getattr(env, "_step_count", 0), 0)
    turn_count = _safe_int(getattr(env, "_turn_count", 0), 0)
    if step_count < 0:
        bad.append(f"_step_count={step_count} < 0")
    try:
        if game is not None and int(game.turn) != turn_count:
            bad.append(f"_turn_count={turn_count} != game.turn="
                       f"{int(game.turn)}")
    except Exception:                                     # noqa: BLE001
        pass
    stats = getattr(env, "_stats", None)
    if not isinstance(stats, dict):
        bad.append("_stats 不是 dict")
    else:
        if _safe_int(stats.get("steps", 0), 0) != step_count:
            bad.append(f"_stats['steps']={stats.get('steps')} != "
                       f"_step_count={step_count}")
        for key in ("episodes", "invalid", "choice_errors",
                    "opponent_rejects", "engine_errors"):
            if _safe_int(stats.get(key, 0), 0) < 0:
                bad.append(f"_stats[{key!r}] < 0")
    for attr, cap in (("_errors", _ERRORS_CAP),
                      ("_auto_resolved_choices", _AUTO_RESOLVED_CAP),
                      ("_choice_failures", _CHOICE_FAILURES_CAP)):
        arr = getattr(env, attr, None)
        if arr is None:
            bad.append(f"{attr} is None")
            continue
        n = _safe_len(arr)
        if n > cap:
            bad.append(f"{attr} 长度 {n} > 上限 {cap}")
    turn_stats = getattr(env, "_turn_stats", None)
    if turn_stats is None:
        bad.append("_turn_stats is None")
    else:
        for field in ("dealt", "taken", "won", "lost"):
            v = _safe_int(getattr(turn_stats, field, 0), 0)
            if v < 0:
                bad.append(f"_turn_stats.{field}={v} < 0")
    # terminated 标志: done 时 obs 必须是 game_over（终局出口契约）
    done = bool(getattr(env, "_done", False))
    obs = getattr(env, "_obs", None)
    if done:
        heroes = getattr(getattr(env, "game", None), "heroes", None)
        if _safe_len(heroes) == 0:
            bad.append("_done=True 但 game.heroes 为空")
        if obs is not None and str(getattr(obs, "phase", "")) != "game_over":
            bad.append(f"_done=True 但 obs.phase={getattr(obs, 'phase', '')!r}")
        if _safe_len(getattr(obs, "candidates", None)) > 0:
            bad.append("_done=True 但仍有候选动作")


def _check_obs_consistency(env: Any, bad: List[str]) -> None:
    """``_obs`` / ``_step_actions`` / ``legal_actions`` 与当前状态一致。"""
    game = getattr(env, "game", None)
    agent = getattr(env, "_agent", None)
    obs = getattr(env, "_obs", None)
    if game is None or agent is None:
        return
    try:
        legal = tuple(env.legal_actions())
    except Exception as exc:                              # noqa: BLE001
        bad.append(f"legal_actions() 抛异常: {type(exc).__name__}: {exc}")
        return
    try:
        mask = tuple(env.action_mask())
    except Exception as exc:                              # noqa: BLE001
        bad.append(f"action_mask() 抛异常: {type(exc).__name__}: {exc}")
        mask = ()
    if len(mask) != len(legal):
        bad.append(f"action_mask 长度 {len(mask)} != legal_actions "
                   f"{len(legal)}")
    if any(not bool(m) for m in mask):
        bad.append("action_mask 含 False（候选集必须全部可选）")
    if not 0 < len(legal) <= 64:
        if bool(getattr(env, "_done", False)):
            pass  # 终局允许 0 候选（下方单独检查）
        else:
            bad.append(f"候选动作数 {len(legal)} 不在 1..64")
    # 签名唯一
    try:
        sigs = [tuple(c.signature()) for c in legal]
        if len(sigs) != len(set(sigs)):
            bad.append(f"候选动作签名重复（{len(sigs)} 个候选 / "
                       f"{len(set(sigs))} 个唯一签名）")
    except Exception as exc:                              # noqa: BLE001
        bad.append(f"候选签名读取失败: {type(exc).__name__}")
    if obs is None:
        bad.append("_obs is None（决策步必须有观测）")
        return
    # legal_actions == obs.candidates（顺序一致）
    try:
        obs_sigs = [tuple(c.signature()) for c in obs.candidates]
        if obs_sigs != sigs:
            bad.append(f"legal_actions 与 obs.candidates 不一致"
                       f"（{len(sigs)} vs {len(obs_sigs)}）")
    except Exception as exc:                              # noqa: BLE001
        bad.append(f"obs.candidates 读取失败: {type(exc).__name__}")
    # 观测标量与状态一致
    try:
        if int(obs.turn) != int(game.turn):
            bad.append(f"obs.turn={obs.turn} != game.turn={game.turn}")
    except Exception:                                     # noqa: BLE001
        pass
    try:
        if obs.total_players != _safe_int(
                getattr(env.config, "num_players", 0), 0):
            bad.append(f"obs.total_players={obs.total_players} != "
                       f"config.num_players")
    except Exception:                                     # noqa: BLE001
        pass
    # 大厅视图
    try:
        game_heroes = list(game.heroes)
        lobby = tuple(obs.lobby)
        if len(lobby) != len(game_heroes):
            bad.append(f"obs.lobby 长度 {len(lobby)} != game.heroes "
                       f"{len(game_heroes)}")
        alive = sum(1 for h in game_heroes if bool(h.is_alive))
        if int(obs.alive_count) != alive:
            bad.append(f"obs.alive_count={obs.alive_count} != 存活数 {alive}")
        for i, (lp, hero) in enumerate(zip(lobby, game_heroes)):
            if str(lp.name) != str(hero.name):
                bad.append(f"obs.lobby[{i}].name={lp.name!r} != "
                           f"game.heroes[{i}].name={hero.name!r}")
                break
            if bool(lp.alive) != bool(hero.is_alive):
                bad.append(f"obs.lobby[{i}].alive 与引擎不一致")
                break
    except Exception as exc:                              # noqa: BLE001
        bad.append(f"obs 大厅一致性检查失败: {type(exc).__name__}: {exc}")
    # phase 契约
    try:
        phase = str(obs.phase)
        pending = list(getattr(game, "pending_choices", None) or [])
        agent_pending = any(getattr(ch, "owner", None) is agent
                            for ch in pending)
        if bool(getattr(env, "_done", False)):
            if phase != "game_over":
                bad.append(f"done 后 obs.phase={phase!r} != 'game_over'")
        elif not bool(agent.is_alive) or bool(getattr(game, "finished", False)):
            if phase != "game_over":
                bad.append(f"终局态 obs.phase={phase!r} != 'game_over'")
        elif agent_pending:
            if phase != "choice":
                bad.append(f"有待决选择但 obs.phase={phase!r} != 'choice'")
        else:
            if phase != "recruit":
                bad.append(f"招募期 obs.phase={phase!r} != 'recruit'")
    except Exception as exc:                              # noqa: BLE001
        bad.append(f"obs.phase 一致性检查失败: {type(exc).__name__}: {exc}")
    # PendingChoice 队列：只剩智能体自己的选择；智能体在队首时 obs 必须
    # 暴露该选择（ENV_SPEC §4 / TEST_SOP §8）
    try:
        pending = list(getattr(game, "pending_choices", None) or [])
        for i, ch in enumerate(pending):
            owner = getattr(ch, "owner", None)
            if i == 0 and owner is not agent:
                bad.append("pending_choices[0] 的 owner 不是智能体"
                           "（非智能体选择应由 env 自动结算，队首必须是"
                           "待智能体决策的选择）")
                break
            if not list(getattr(ch, "options", None) or []):
                bad.append(f"pending_choices[{i}] 选项为空")
        if pending and getattr(obs, "pending_choice", None) is None \
                and not bool(getattr(env, "_done", False)):
            bad.append("pending_choices 非空但 obs.pending_choice 为空")
    except Exception as exc:                              # noqa: BLE001
        bad.append(f"pending_choices 检查失败: {type(exc).__name__}: {exc}")


def check_env(env: Any, *, strict_tavern_slots: bool = False,
              strict_unique_ranks: bool = False) -> List[str]:
    """环境层结构不变量（只读；返回违反项列表；空 = 通过）。

    在 :func:`check_game` 之上追加：名次追踪、大厅视图别名、
    ``_obs``/``legal_actions`` 一致性、``PendingChoice`` 契约、
    计数器/有界历史。

    参数
    ----
    strict_tavern_slots : 透传 :func:`check_game`（默认关闭，原因见模块
        「已知偏差 1」）。
    strict_unique_ranks : 把同回合多淘汰造成的名次并列报告为违反项
        （默认关闭，原因见模块「已知偏差 2」）。
    """
    bad: List[str] = []
    if env is None:
        return ["env is None"]
    game = getattr(env, "game", None)
    if game is None:
        return ["env.game is None（reset 之前不可检查）"]
    terminal = bool(getattr(env, "_done", False))
    # 每个子检查独立 try/except：单点失败不阻断其余检查
    sections = (
        ("check_game", lambda: check_game(
            game, agent=None if terminal else getattr(env, "_agent", None),
            strict_tavern_slots=strict_tavern_slots)),
        ("rank_tracking", lambda: _check_rank_tracking(
            env, bad, strict_unique_ranks, terminal=terminal)),
        ("all_heroes_view", lambda: _check_all_heroes_view(
            env, bad, terminal=terminal)),
        ("env_counters", lambda: _check_env_counters(env, bad)),
        ("obs_consistency", lambda: _check_obs_consistency(env, bad)),
    )
    for name, fn in sections:
        try:
            result = fn()
            if isinstance(result, list):
                bad.extend(result)
        except Exception as exc:                          # noqa: BLE001
            bad.append(f"check_error:{name}:{type(exc).__name__}: {exc}")
    return bad


# ══════════════════════════════════════════════════════════════════════
# 稳定状态 digest（snapshot/restore 对拍用）
# ══════════════════════════════════════════════════════════════════════

#: digest 允许的原子类型（直接进 JSON-like 结构）
_ATOMIC = (str, bytes, int, float, bool, type(None))

#: ``_entity_state`` 不展开的实体属性（game/controller 防环; 区域容器单独
#: 展开为完整实体状态，避免重复遍历; tags/card_id/uuid 单独处理）
_SKIP_ENTITY_ATTRS = frozenset((
    "game", "controller", "tags", "uuid", "card_id",
    "board", "hand", "tavern", "trinkets", "quest_rewards", "quest",
))

#: ``state_digest`` 不重复展开的 game 属性（下面逐项单独处理）
_SKIP_GAME_ATTRS = frozenset((
    "db", "events", "rng", "minion_pool", "spell_pool", "heroes",
    "pending_choices", "deferred_actions", "pending_hand_queue",
    "ghost_records", "_last_combat_results",
))


def _safe_str(value: Any) -> str:
    try:
        return str(value)
    except Exception:                                     # noqa: BLE001
        return "?"


def _stable_value(value: Any, depth: int = 0,
                  seen: Optional[set] = None) -> Any:
    """把任意对象递归转为**稳定**纯数据（无地址/无哈希顺序/无 id()）。

    规则：
      * 原子类型原样；``enum`` → ``("enum", 类名, 值)``；
      * 引擎实体（有 ``uuid``）→ ``("entity", uuid, card_id, 类名)``
        **终止**（实体完整状态由 :func:`_entity_state` 单独展开）；
      * dict → 按 key 的稳定字符串排序后的 ``(k, v)`` 列表；
      * list/tuple → 列表；set/frozenset → 稳定排序后的列表；
      * 函数/方法 → ``("callable", qualname)``（闭包内容不展开）；
      * 其它对象 → ``("object", 类名, __dict__ 递归)``（深度上限 8）；
      * 环 → ``"<cycle>"``。
    """
    if type(value) in _ATOMIC:
        return value
    if depth > 8:
        return "<max-depth>"
    if seen is None:
        seen = set()
    oid = id(value)
    if oid in seen:
        return "<cycle>"
    import enum as _enum
    if isinstance(value, _enum.Enum):
        return ("enum", type(value).__name__,
                _stable_value(value.value, depth + 1, seen))
    try:
        uid = getattr(value, "uuid", None)
        if isinstance(uid, str) and uid:
            return ("entity", uid, _safe_str(getattr(value, "card_id", "")),
                    type(value).__name__)
    except Exception:                                     # noqa: BLE001
        pass
    if isinstance(value, dict):
        seen = seen | {oid}
        pairs = [(_stable_value(k, depth + 1, seen),
                  _stable_value(v, depth + 1, seen))
                 for k, v in value.items()]
        pairs.sort(key=lambda kv: repr(kv[0]))
        return ("dict", pairs)
    if isinstance(value, (list, tuple)):
        seen = seen | {oid}
        return [_stable_value(item, depth + 1, seen) for item in value]
    if isinstance(value, (set, frozenset)):
        seen = seen | {oid}
        items = [_stable_value(item, depth + 1, seen) for item in value]
        items.sort(key=repr)
        return ("set", items)
    if callable(value) and not isinstance(value, type):
        name = getattr(value, "__qualname__", None) \
            or getattr(value, "__name__", None) or type(value).__name__
        return ("callable", _safe_str(name))
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, dict):
        seen = seen | {oid}
        return ("object", type(value).__name__,
                _stable_value(attrs, depth + 1, seen))
    try:
        return ("repr", repr(value)[:200])
    except Exception:                                     # noqa: BLE001
        return ("type", type(value).__name__)


def _entity_state(entity: Any, depth: int = 0) -> Any:
    """实体的**完整**稳定状态（tags + 私有属性 + 区域内容递归）。

    英雄/随从/法术/饰品/任务奖励/选项实体都适用；``game``/``controller``
    不展开（防环），区域容器单独递归为完整实体状态（棋盘/手牌/酒馆/
    饰品/任务奖励），其余私有属性用 :func:`_stable_value`（其中再次出现
    的实体引用退化为身份元组，由对应实体的独立展开覆盖）。
    """
    if entity is None:
        return None
    if depth > 6:
        return _stable_value(entity, depth + 1)
    state: Dict[str, Any] = {
        "uuid": _entity_uuid(entity),
        "card_id": _safe_str(getattr(entity, "card_id", "")),
        "type": type(entity).__name__,
    }
    tags = getattr(entity, "tags", None)
    if isinstance(tags, dict):
        pairs = []
        for tag, val in tags.items():
            try:
                key = int(tag)
            except Exception:                             # noqa: BLE001
                key = _safe_str(tag)
            pairs.append((key, _stable_value(val, depth + 1)))
        pairs.sort(key=lambda kv: repr(kv[0]))
        state["tags"] = pairs
    attrs = getattr(entity, "__dict__", None)
    if isinstance(attrs, dict):
        extra = {key: val for key, val in attrs.items()
                 if key not in _SKIP_ENTITY_ATTRS}
        state["attrs"] = _stable_value(extra, depth + 1)
        scripts = attrs.get("scripts")
        if scripts is not None:
            state["scripts"] = (
                type(scripts).__name__,
                _stable_value(getattr(scripts, "__dict__", None), depth + 1))
    for zone_attr in ("board", "hand", "tavern", "trinkets",
                      "quest_rewards"):
        arr = getattr(entity, zone_attr, None)
        if isinstance(arr, (list, tuple)):
            state[zone_attr] = [_entity_state(item, depth + 1)
                                for item in list(arr)]
    quest = getattr(entity, "quest", None)
    if quest is not None and not isinstance(quest, (str, int, float, bool)):
        state["quest"] = _entity_state(quest, depth + 1)
    return state


def _snapshot_value(value: Any, depth: int = 0) -> Any:
    """队列/记录结构里的**实体展开**版本（实体 → 完整状态，其它递归）。"""
    if depth > 6:
        return _stable_value(value, depth + 1)
    if value is None or type(value) in _ATOMIC:
        return value
    try:
        if isinstance(getattr(value, "uuid", None), str):
            return _entity_state(value, depth + 1)
    except Exception:                                     # noqa: BLE001
        pass
    if isinstance(value, dict):
        pairs = [(_stable_value(k, depth + 1),
                  _snapshot_value(v, depth + 1))
                 for k, v in value.items()]
        pairs.sort(key=lambda kv: repr(kv[0]))
        return ("dict", pairs)
    if isinstance(value, (list, tuple)):
        return [_snapshot_value(item, depth + 1) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_snapshot_value(item, depth + 1) for item in value]
        items.sort(key=repr)
        return ("set", items)
    return _stable_value(value, depth + 1)


def _pool_digest(pool: Any) -> Any:
    if pool is None:
        return None
    return {
        "available": sorted(
            (_safe_str(k), _safe_int(v, 0))
            for k, v in (getattr(pool, "_available", None) or {}).items()),
        "purged": sorted(_safe_str(x) for x in
                         (getattr(pool, "_purged", None) or set())),
        "injected": sorted(_safe_str(x) for x in
                           (getattr(pool, "_injected", None) or set())),
        "active_races": sorted(
            _safe_str(x) for x in
            (getattr(pool, "active_races", None) or set())),
    }


def _rng_digest(game: Any) -> Any:
    """RNG 状态 digest（``random.Random.getstate()`` 是确定性元组）。"""
    rng = getattr(game, "rng", None)
    internal = getattr(rng, "_rng", None)
    try:
        version, internal_state, gauss = internal.getstate()
    except Exception:                                     # noqa: BLE001
        return None
    return {"version": int(version),
            "state": [int(x) for x in internal_state],
            "gauss": gauss}


def _choice_digest(choice: Any) -> Any:
    if choice is None:
        return None
    options = []
    for opt in list(getattr(choice, "options", None) or []):
        options.append(_snapshot_value(opt))
    return {
        "kind": _safe_str(getattr(choice, "kind", "")),
        "owner": _stable_value(getattr(choice, "owner", None)),
        "options": options,
        "resolved": bool(getattr(choice, "resolved", False)),
        "failed": bool(getattr(choice, "failed", False)),
    }


def state_digest(game: Any) -> str:
    """``Game`` 的稳定状态摘要（sha256 hex；跨进程/跨 clone 稳定）。

    覆盖：``turn`` 等标量 / 每个英雄**完整状态**（tags + 私有属性 +
    棋盘/手牌/酒馆/饰品/任务奖励实体）/ RNG 内部状态 / 随从池+法术池
    簿记 / ``PendingChoice`` 队列（含选项实体）/ ``deferred_actions`` /
    ``pending_hand_queue`` / ``ghost_records`` / 最近战斗摘要 / 其余
    game 私有状态（泛化遍历）。

    用途：snapshot→restore 对拍（``snapshot`` 测试断言恢复前后 digest
    相同）、回归/审计。**不含**事件监听器表（env 监听器在快照时被剥离，
    恢复时重建）与函数闭包内容；clone 的闭包重绑由行为测试覆盖。
    """
    if game is None:
        return "none"
    payload: Dict[str, Any] = {
        "turn": _safe_int(getattr(game, "turn", 0), 0),
        "finished": bool(getattr(game, "finished", False)),
        "in_combat": bool(getattr(game, "in_combat", False)),
        "heroes": [_entity_state(h) for h in
                   list(getattr(game, "heroes", None) or [])],
        "minion_pool": _pool_digest(getattr(game, "minion_pool", None)),
        "spell_pool": _pool_digest(getattr(game, "spell_pool", None)),
        "rng": _rng_digest(game),
        "pending_choices": [_choice_digest(ch) for ch in
                            list(getattr(game, "pending_choices", None)
                                 or [])],
        "deferred_actions": _snapshot_value(
            list(getattr(game, "deferred_actions", None) or [])),
        "pending_hand_queue": _snapshot_value(
            list(getattr(game, "pending_hand_queue", None) or [])),
        "ghost_records": _snapshot_value(
            list(getattr(game, "ghost_records", None) or [])),
        "last_combat_results": _stable_value({
            _safe_str(getattr(h, "name", "")): {
                "winner": _safe_str(getattr(getattr(res, "winner", None),
                                           "name", "")),
                "loser": _safe_str(getattr(getattr(res, "loser", None),
                                          "name", "")),
                "damage_dealt": _safe_int(
                    getattr(res, "damage_dealt", 0), 0),
                "capped_damage": _safe_int(
                    getattr(res, "capped_damage", 0), 0),
                "rounds": _safe_int(getattr(res, "rounds", 0), 0),
            }
            for h, res in (getattr(game, "_last_combat_results", None)
                           or {}).items()}),
    }
    # 其余 game 私有状态（回合标志/配对簿记/任务·饰品窗口/暗黑赠礼状态等）
    game_attrs = getattr(game, "__dict__", None)
    if isinstance(game_attrs, dict):
        rest = {key: val for key, val in game_attrs.items()
                if key not in _SKIP_GAME_ATTRS}
        payload["game_attrs"] = _stable_value(rest)
    blob = repr(payload).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
