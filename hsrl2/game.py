"""Game — 回合状态机 + 招募经济 + 战斗编排 + 伤害/幽灵。

修复目标（REFACTOR_PLAN §5）:
  P1 池 draw/return 配对（刷新回池、出售回池、淘汰回池、Discover 占池）
  P3 金币: 基础收入覆盖式重置、回合内收入叠加、持有上限 99
  P4 升级费下限 0
  P5 冻结: 整馆冻结、手动刷新保留、无发明 buff
  P6 满手牌生成卡等待
  P7 Spellcraft 打出立即给法术（脚本钩子 on_play 处理）
  C6 死亡处理: 亡语先、复生后（保留 buff/金色，1 血，原位）
"""

from __future__ import annotations

import copy
import uuid
from typing import (Any, Dict, List, Mapping, Optional, Sequence, Tuple,
                    TYPE_CHECKING)

import hsrl2.constants as C
from hsrl2 import darkgifts as DG
from hsrl2 import matchmaking
from hsrl2.combat import CombatScheduler
from hsrl2.deity import (DEITY_IDS, DeitySigilState, DeityState,
                         threshold_from_db)
from hsrl2.entity import Buff, Entity
from hsrl2.events import MINION_PLAYED, SPELL_BOUGHT, EventBus, Listener
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.pools import MinionPool, SpellPool
from hsrl2.queue import Action, ActionQueue
from hsrl2.rng import GameRNG
from hsrl2.spell import Spell
from hsrl2.tags import (RACE_SET_ALL, CardType, GameTag, Race, Zone,
                        race_set)

if TYPE_CHECKING:
    from hsrl2.db import CardDB


# PERSIST tag 已入册 tags.py（1045）——Tarecgosa's Blessing Dark Gift
PERSIST_TAG = GameTag.PERSIST_COMBAT_CHANGES

# 以 "discover" 前缀入队但**不是发现卡牌**的选择 kind——不得广播
# `card_discovered`（"After you Discover a **card**" 不含英雄技能）。
# `discover_hero_power`: Cosmic Reward / Finley / 异变第二技能槽三选一。
_NON_CARD_DISCOVER_KINDS = frozenset({"discover_hero_power"})

# 任务系统的**公告 token**（非任务卡本体）: 文本 "In 3 turns, choose one
# of three Quests!"，语义由 `Game._offer_quests` 本身（T4 三选一）实现。
# 实测（2026-09-18）二者 card_type=SPELL、`QUEST_PROGRESS_TOTAL`(535)=3，
# 因此**同时满足** `quest_defs()` 的"SPELL + id 含 quest + tag 535"三条
# 谓词——本集合是排除它们的**唯一**条件（不是冗余）。注册它们即"注册但
# 空转"的第三态，故 `quest_defs()` 显式排除。
_QUEST_ANNOUNCE_TOKENS = frozenset({
    "BG24_Quest_Bob", "BG33_Anomaly_008_Quest",
})


def is_quest_card(d) -> bool:
    """单卡判定: 是否为 `Game.quest_defs()` 口径的**可进度化任务卡**。

    这是 `Game.quest_defs()` 与两个审计工具
    （`tools/audit_script_wiring.py::category_of`、
    `tools/audit_card_registry_v2.py::_quest_defs`）的**唯一同源谓词**
    （2026-09-18 对抗审查: 此前两工具各自用 id 前缀/正则，口径不同——
    wiring 21 vs registry 21 但集合互异）。谓词:
      `card_type == CardType.SPELL`
      且 `id` 不含 `_QUEST_ANNOUNCE_TOKENS`
      且 id 小写含 "quest"
      且 `CardDef.quest_progress_total`（CardDefs tag 535）真值。
    """
    return (d is not None
            and d.card_type == CardType.SPELL
            and d.id not in _QUEST_ANNOUNCE_TOKENS
            and "quest" in d.id.lower()
            and bool(d.quest_progress_total))


def quest_defs_from_db(db) -> list:
    """`Game.quest_defs()` 的同源实现（审计工具直接调用，勿另写口径）。"""
    return [d for d in db._by_id.values() if is_quest_card(d)]

# **Bonus Keyword** 官方定义域 = 6 张（wiki.gg `Battlegrounds/Bonus_Keyword`
# oldid 830663; RULES §9.6）: Divine Shield / Reborn / Stealth / Taunt /
# Venomous / Windfury。**不含** Poisonous / Cleave（那是 Dark Gift/PERSIST
# 的 8 集口径，两者不可混用——2026-09-02 对抗审查 F1 教训）。
BONUS_KEYWORD_TAGS = (
    GameTag.TAUNT,
    GameTag.DIVINE_SHIELD,
    GameTag.WINDFURY,
    GameTag.VENOMOUS,
    GameTag.REBORN,
    GameTag.STEALTH,
)

# PERSIST 随从战斗后覆写保留的关键词集合（RULES §3.5 例外: Dark Gift 永久保留）
_PERSIST_KEYWORD_TAGS = (
    GameTag.TAUNT,
    GameTag.DIVINE_SHIELD,
    GameTag.WINDFURY,
    GameTag.POISONOUS,
    GameTag.VENOMOUS,
    GameTag.REBORN,
    GameTag.STEALTH,
    GameTag.CLEAVE,
)


def _frozen_clone(m: Minion) -> Minion:
    """幽灵快照克隆 (RULES §4.8: 幽灵阵容不成长不变化)。

    copy.copy + 独立 tags/buffs:
      - tags 逐值独立（实体引用类值如 KILLER 直接丢弃，避免 deepcopy
        拉出整张对象图）
      - _buffs 为新列表、新 Buff 对象（copy.copy 共享列表会污染原实体）
      - PERSIST_TAG 一并剥离 — 持久化语义不适用于冻结副本，
        否则幽灵战斗的变化会写入记录
    """
    clone = copy.copy(m)
    clone.uuid = uuid.uuid4().hex[:12]
    clone.tags = {}
    for tag, value in m.tags.items():
        if isinstance(value, Entity):
            continue
        clone.tags[tag] = copy.deepcopy(value)
    clone._buffs = [copy.copy(b) for b in m._buffs]
    clone.controller = None
    clone.game = m.game
    clone.clear(PERSIST_TAG)
    return clone


class GameStateError(RuntimeError):
    """非法操作（引擎契约违反）。"""


class PendingChoice:
    """发现/选择待决。队列化 — 旧引擎单槽覆盖 bug 的修复。"""

    def __init__(self, owner: Hero, options: Sequence[Any], kind: str,
                 resolve_callback=None):
        self.owner = owner
        self.options = list(options)
        self.kind = kind            # "discover_minion" / "dark_gift" / ...
        self.resolve_callback = resolve_callback

    def choose(self, index: int) -> None:
        if not 0 <= index < len(self.options):
            raise GameStateError(f"choice index {index} out of range")
        pick = self.options[index]
        if self.resolve_callback:
            self.resolve_callback(pick)
        # 发现类选择完成事件（Hooktusk "After you Discover a card" 等）
        # 非卡牌选择（英雄技能三选一）不计入 "Discover a **card**"——
        # 否则 Hooktusk 类 "After you Discover a card" 被动会被技能发现
        # 误触发（2026-09-13 对抗验证实测: Cosmic Reward / Finley 选项
        # 令游荡的 Hooktusk 给海盗白加 buff）。
        if (self.kind.startswith("discover")
                and self.kind not in _NON_CARD_DISCOVER_KINDS) \
                or self.kind == "triple_reward" \
                or self.kind == "dark_gift":
            if self.owner.game is not None:
                self.owner.game.events.fire(
                    self.owner.game, "card_discovered",
                    kind=self.kind, hero=self.owner,
                    option=pick if isinstance(pick, str) else None,
                    # 金色发现（Treasure Hoard `Discover(golden=True)`）→
                    # "get an extra copy of it" 类效果须发金色副本
                    # （2026-09-02 对抗审查: 旧 payload 无 golden 位）
                    golden=bool(getattr(self, "discover_golden", False)))


class Game:
    def __init__(self, heroes: List[Hero], db: "CardDB", *,
                 seed: int | None = None, anomaly: Optional[str] = None,
                 damage_cap_override: Optional[int] = None):
        self.heroes = heroes
        self.db = db
        self.rng = GameRNG(seed)
        self.turn = 0
        self.in_combat = False
        # 官方伤害上限外部注入（2026-10-18，官方一致性 P1）：
        # 官方上限来自服务端 GameEntity tag `BACON_COMBAT_DAMAGE_CAP`(2089)
        # / `BACON_COMBAT_DAMAGE_CAP_ENABLED`(3403)；真实对局日志可读到时由
        # 外部注入（`set_damage_cap`），**默认 None = 保持原 turn 表不变**。
        self._damage_cap_override: Optional[int] = (
            int(damage_cap_override)
            if damage_cap_override is not None else None)
        self._damage_cap_uncapped: bool = False
        # 战斗快照**复原**窗口标记（"获得属性"抑制——ENGINE_BACKLOG §E
        # D2）: `run_combat` 的 finally 恢复块置 True，期间 `Entity.add_buff`
        # 不广播 `stats_gained`（复原 ≠ 获得）
        self._restore_no_gain = False
        # 行动来源作用域（`stats_gained.source` 的数据源——§E D7）:
        # `run_script_hook` 置为正在施动的实体; `ActionQueue.resolve`
        # 优先取动作显式 `source`，否则继承本值。
        self._action_source: Optional[Entity] = None
        self._active_combat: Optional[tuple] = None   # 当前战斗对（SoC/Avenge 用）
        # F-07: Deity（旧神）隐藏目标——本场战斗 Aberration 死亡记录 /
        # awaken 阈值缓存（见 hsrl2/deity.py）
        self._deity_combat_deaths: dict = {}
        self._deity_threshold: Optional[int] = None
        self.events = EventBus()
        self.queue = ActionQueue()
        self.minion_pool = MinionPool(db, self.rng)
        self.spell_pool = SpellPool(db, self.rng)
        self.pending_choices: List[PendingChoice] = []
        self.choice_policy: Optional[str] = "first"   # 自动策略: first/random
        self.combat_summon_log: List[Minion] = []
        self.combat_death_log: List[Minion] = []
        # 延迟到下回合的动作 / 满手牌排队等待的生成卡 (P6)
        self.deferred_actions: List[tuple] = []       # (hero, Action)
        self.pending_hand_queue: List[tuple] = []     # (hero, Entity)
        # 磁力栈: 宿主 uuid → 吸附的磁力随从 card_id 列表（亡语栈叠用）
        self._magnetic_stack: dict = {}
        # 战斗内 Transform 持久化（RULES §3.5 例外）: 变身是**永久卡身份
        # 变更**（非战斗 buff），战后棋盘复原时须重放——否则 SoC 变身类
        # 效果（"Make your highest-Tier Dragon Golden"——Yu'lon Sticker
        # `BG32_MagicItem_419`）在战后被回滚。[(old_uuid, new_entity)]
        self._combat_transforms: list = []
        self._last_minion_fired: set = set()
        self.finished: bool = False
        self._last_combat_results = {}
        # ── 异变/任务/饰品 系统状态 ──
        self.anomaly = anomaly               # 本局异变 card_id（None=标准局）
        self.max_tavern_tier = C.TAVERN_MAX_TIER  # 异变 Secrets of Norgannon=7
        # 酒馆**存在的档位集合**（升序元组; None = 标准连续阶梯 1..上限）。
        # 异变 BG27_Anomaly_101 "Only Tavern Tiers 1, 3, and 5 exist." /
        # BG27_Anomaly_102 "Only Tavern Tiers 2, 4, and 6 exist." 在此覆写。
        # 读取点: `upgrade_tavern`/`upgrade_tavern_free`（落点=下一存在档）、
        # `refresh_tavern`（随从+酒馆法术抽取白名单）、
        # `actions.discover._pool_candidates`（发现候选不得越出存在档）。
        self._tavern_tier_ladder: Optional[tuple] = None
        # 三连奖励档位 = 本人**当前**档位（BG27_Anomaly_101/102 文本
        # "Triple Rewards Discover a minion of your Tier."——引擎缺省为
        # 被三连随从的 tier+1）。
        self._triple_reward_of_own_tier: bool = False
        self._quest_offered: set = set()      # 已发任务 offer 的英雄
        # 已发饰品 offer 的 (英雄, 档位) ——按档位记账（T6 lesser / T9
        # greater 是两次独立 offer; 单一 hero 集合会让 Greater 永不发放，
        # 2026-09-01 审计修复）
        self._trinket_offered: set = set()
        # 已获得的饰品 id 的**全桌并集**（legacy 聚合/观察用; 判定一律走
        # `hero.trinkets_granted`——"you already have" 是 per-player 口径）
        self._trinkets_granted: set = set()
        # 配对簿记 / 幽灵记录 / 战斗记忆（幽灵对手记 None）
        self._opponent_history: Dict[Hero, List[Optional[Hero]]] = {}
        self.ghost_records: List[dict] = []
        self.combat_memory: Dict[Hero, List[Optional[Hero]]] = {}
        # 本招募期已确定的战斗配对（招募阶段开始时预生成, RULES §4.8a）
        # ——Scabbs "next opponent's warband" / Murloc Holmes "your next
        # opponent had last combat" 必须在招募期读到**下一**对手; Tess
        # "your last opponent's warband" 读**上一**对手。数据文本要求
        # 两者是不同引用，单一"事后快照"无法同时支撑（2026-09-02 对抗
        # 审查裁定的引擎缺口）。
        self._pending_pairs: Optional[List[Tuple[Hero, Hero]]] = None
        self._pending_leftover: Optional[Hero] = None
        self._next_opponent: Dict[Hero, Hero] = {}
        # hero → 上一场战斗对手（含幽灵）的战前战团快照（Tess/R806）
        self._last_opponent_board: Dict[Hero, List] = {}
        # ── S14: Dark Gifts / Lockbox / Fodder 引擎级状态 ──
        # hero → {"uses_left": 3, "used_this_turn": False}（B1;
        # used_this_turn 在 _begin_recruit_for 重置）
        self.dark_gift_state: Dict[Hero, dict] = {}
        # 正在处理死亡的实体 uuid（重入保护——DEATH 事件在离场**之前**
        # 广播（官方顺序），DEATH 监听器内若嵌套 check_deaths()（如
        # "死亡时召唤并立即攻击" 家族），同一实体仍 dead+PLAY 会被二次
        # 收集 → 亡语/死亡计数双触发。2026-09-02 对抗审查实测
        # （Onyxia Avenge 第 4 次死亡触发 Whelp 攻击 → 同一 uuid 亡语 ×2）
        self._death_processing: set = set()
        # 已接线 on_bind 的 (hero, power_id)（RULES §9.5——幂等）
        self._wired_powers: set = set()
        # (gift_id, minion_uuid, turn, "APPLIED"|"DEFERRED") — DEFERRED
        # gift 不静默: 有日志可审计
        self.dark_gift_audit_log: List[Tuple[str, str, int, str]] = []
        # Persisting Horror: 复生时满血复活的实体（一次性，复活后移除）
        self._reborn_full_uuids: set = set()
        # Gilding: 金色但无三连奖励（三连奖励系统接线后消费; TODO）
        self._gilded_no_reward_uuids: set = set()
        # Sunken Persistence: Spellcraft 永久的随从 uuid。脚本层契约:
        # 由随从生成的 Spellcraft 法术实体须设 spellcraft_source_uuid
        # 属性 = 该随从 uuid，回合结束丢弃时据此豁免
        self._permanent_spellcraft_uuids: set = set()
        # 战斗内授予的亡语（`grant_combat_deathrattle`）: 每英雄的
        # [(minion, saved_overrides)]——run_combat 的 finally 统一恢复
        # （`_script_overrides` 不在 Minion 快照范围，2026-09-02 主线收口）
        self._combat_dr_grants: dict = {}
        # Demonology: hero → 待附加 Fodder 的刷新次数
        # Fodder 协议 v2: Dict[Hero, (剩余刷新次数, 每次附加枚数)]
        self._fodder_refresh_pending: Dict[Hero, tuple] = {}
        # 永久化拦截窗口（Lava Lurker——spell_resolving 事件中由脚本设置，
        # add_buff 消费后清除）
        self._permanence_pending: Optional[str] = None
        for h in heroes:
            h.game = self

    # ══════════════════ 招募回合流程 ══════════════════

    def start_game(self) -> None:
        self.turn = 1
        # 英雄被动技能接线（hero_passives 批协议: REGISTRY[power_id]
        # 的 on_bind(hero, game) 注册整局监听器/开局效果——The Curator
        # Amalgam / Patchwerk 血量 / Edwin 计数等）
        for h in self.heroes:
            power_def = self.hero_power_def(h)
            if power_def is not None:
                self.wire_hero_power_on_bind(h, power_def.id)
        # 异变全局应用（英雄接线后、首回合开始前——异变可改英雄起始
        # 状态如 10 金/5 甲; 脚本签名 on_bind(game)）
        if self.anomaly is not None:
            from hsrl2.scripts import REGISTRY as _REG
            adef = self.db.get(self.anomaly)
            if adef is not None and adef.card_type != CardType.BACON_ANOMALY:
                # fail-loud: 传错 id（如把异变授予的**英雄技能**
                # BG35_Anomaly_007t 当异变传入）会让 `on_bind(game)`
                # 签名不符 → TypeError 崩溃（smoke 脚手架曾因此踩中）
                raise GameStateError(
                    f"anomaly must be a BACON_ANOMALY card: {self.anomaly!r}")
            ascript = _REG.get(self.anomaly)
            if ascript is not None and hasattr(ascript, "on_bind"):
                # 异变 on_bind 同样是"接线派发": 期间注册、且 owner 为
                # 某英雄的监听器视为持久接线（ENGINE_BACKLOG #32 的显式
                # 作用域; 异变只在 start_game 应用, 不涉及战斗快照, 但
                # 语义保持一致）
                with self.events.persistent_bind_scope(*self.heroes):
                    ascript.on_bind(self)
        # 第二技能槽（RULES §9.3）: 异变/奖励 on_bind 中声明了
        # hero._second_power_id 之后补接线其 on_bind（顺序: 主技能 →
        # 异变 → 第二技能，保证第二技能的监听器在首回合开始前就位）
        for h in self.heroes:
            for pid in self.hero_power_ids(h):
                self.wire_hero_power_on_bind(h, pid)
        # 首回合配对预生成（招募期即可读"下一对手"——Scabbs/Holmes;
        # RULES §4.8a）
        self._precompute_pairing()
        for h in self.heroes:
            self._begin_recruit_for(h)

    def _begin_recruit_for(self, hero: Hero) -> None:
        """回合开始的全部副作用，按官方顺序。"""
        # 金币: 基础收入覆盖式重置（不储蓄），回合内收入叠加 (P3)
        hero.gold = C.gold_base_income(self.turn, hero.income_cap)
        # 延迟动作执行（上回合 ScheduleNextTurn 等）——在金币重置**之后**，
        # 使 GainGold 类延迟效果叠加在基础收入之上（官方"下回合获得 X 金"）
        due = [(h, a) for h, a in self.deferred_actions if h is hero or h is None]
        self.deferred_actions = [(h, a) for h, a in self.deferred_actions
                                 if not (h is hero or h is None)]
        for _, action in due:
            self.queue.enqueue(action)
        if due:
            self.queue.resolve(self)
        # 额外触发配额（每回合类）重置（RULES §6.20）
        hero.reset_extra_trigger_uses("spell_first", "spellcraft_first",
                                      "bc_first")
        # （英雄技能每回合计数随 HERO_POWER_USED_THIS_TURN 清零——
        #  见 Hero.clear 覆盖）
        # 回合计数清零
        hero.clear(GameTag.GOLD_SPENT_THIS_TURN)
        hero.clear(GameTag.CARDS_PLAYED_THIS_TURN)
        hero.clear(GameTag.TAVERN_SPELLS_CAST_THIS_TURN)
        hero.clear(GameTag.MINIONS_SOLD_THIS_TURN)
        # F-06: 本回合元素打出计数（Conflagration "this turn"）
        hero.elementals_played_this_turn = 0
        # 升级费递减 (P4): 每回合未升级 -1，下限 0；第 1 回合不减
        if self.turn > 1:
            hero.set(GameTag.UPGRADE_COST,
                     max(C.UPGRADE_COST_FLOOR, hero.upgrade_cost - C.UPGRADE_DECAY_PER_TURN))
        # Activate 每回合重置
        for m in hero.board:
            m.clear(GameTag.ACTIVATE_USED_THIS_TURN)
        hero.clear(GameTag.HERO_POWER_USED_THIS_TURN)
        # Dark Gift 每回合 1 次（S14; 官方 36.2 dev post）
        dg_state = self.dark_gift_state.get(hero)
        if dg_state is not None:
            dg_state["used_this_turn"] = False
        # SoT 效果: 饰品 → 任务奖励 → 随从
        for trinket in hero.trinkets:
            self.run_script_hook(trinket, "start_of_turn")
        for reward in getattr(hero, "quest_rewards", []):
            self.run_script_hook(reward, "start_of_turn")
        for m in list(hero.board):
            self.run_script_hook(m, "start_of_turn")
        # 手牌实体 SoT 钩子（B4 — Lockbox 倒计时等依赖）。
        # AMBIGUOUS: 手牌 SoT 相对棋盘 SoT 的官方顺序未公布，取"棋盘后"。
        for card in list(hero.hand):
            self.run_script_hook(card, "start_of_turn")
            # Lockbox 倒计时 (BG36_520t): "In 5 turns, break this open"
            # （初始 5 = CardDef.num(0)，create_spell 时入 tag）
            left = card.get(GameTag.LOCKBOX_TURNS_LEFT, 0)
            if left > 0:
                if left - 1 <= 0:
                    self._open_lockbox(hero, card)
                else:
                    card.set(GameTag.LOCKBOX_TURNS_LEFT, left - 1)
        self.events.fire(self, "turn_start", turn=self.turn, hero=hero)
        # Spellcraft 法术生成（RULES §6.13 每回合开始给予——
        # hsrl2/spellcraft.py，当前为骨架: 无 Spellcraft 脚本卡时 no-op）
        from hsrl2.spellcraft import generate_for_hero
        generate_for_hero(hero, self)
        # 满手牌排队的生成卡入队尝试 (P6: 等待不销毁)
        still_waiting = []
        for h, entity in self.pending_hand_queue:
            if h is hero and not h.hand_full():
                if h.add_to_hand(entity):
                    if isinstance(entity, Minion):
                        self.check_for_triple(h, entity)
                else:
                    still_waiting.append((h, entity))
            else:
                still_waiting.append((h, entity))
        self.pending_hand_queue = still_waiting
        # 刷新酒馆（冻结保留）
        self.refresh_tavern(hero, auto=True)
        # 任务 offer（第 4 回合一次; RULES §11.1 三对选一）
        if self.turn == C.QUEST_OFFER_TURN and hero not in self._quest_offered:
            self._quest_offered.add(hero)
            self._offer_quests(hero)
        # 饰品 shop（第 6/9 回合一次; RULES §7.4.1; BG32_MagicItem_271
        # "Buy your Greater Trinket next turn" 提前档覆写）
        offer_turn = None
        early = getattr(hero, "_trinket_early", {})
        for kind, t in early.items():
            if self.turn == t:
                offer_turn = kind
        if offer_turn is None and self.turn in C.TRINKET_OFFER_TURNS:
            offer_turn = C.TRINKET_OFFER_TURNS[self.turn]
        if offer_turn is not None and (hero, offer_turn) \
                not in self._trinket_offered:
            self._trinket_offered.add((hero, offer_turn))
            self._offer_trinkets(hero, offer_turn)

    # ── 延迟动作 / 手牌等待队列 ──

    def defer_until_next_turn(self, hero: Hero, action: Action) -> None:
        """效果推迟到 hero 的下一个招募阶段开始执行。"""
        self.deferred_actions.append((hero, action))

    def minion_gained(self, hero: Hero, minion: "Minion") -> None:
        """统一“获得一个随从”入手广播（单点，防重复）。

        由 `Hero.add_to_hand` 在实体真正进入手牌后调用**唯一一次**；
        `pending_hand_add` / `buy_from_tavern` / Discover / 生成卡等所有
        入手路径都经 `add_to_hand`，因此监听 `minion_gained` 不会因
        "购买 + 获得"双事件重复计数（与 `card_gained`（含法术）区分）。
        满手排队期间不广播，真正入手时才广播。
        """
        self.events.fire(self, "minion_gained", hero=hero, minion=minion)

    def pending_hand_add(self, hero: Hero, entity: Entity) -> bool:
        """生成卡进手牌；满手牌时排队等待而非销毁 (RULES §3.3)。

        随从入手后自动检查三连（获取/发现/Dark Gift 全路径的统一
        接线点——对抗审查 BUG-1 修复）。
        返回 True=已入手, False=已进入等待队列。
        """
        if hero.add_to_hand(entity):
            if isinstance(entity, Minion):
                self.check_for_triple(hero, entity)
            return True
        self.pending_hand_queue.append((hero, entity))
        return False

    # ── 酒馆刷新 (P1/P5) ──

    def refresh_tavern(self, hero: Hero, *, auto: bool = False,
                       free: bool = False, spells_only: bool = False,
                       races: Optional[set] = None,
                       copies_of_warband: bool = False,
                       keywords: Optional[set] = None,
                       consume_free: bool = True) -> None:
        """刷新酒馆。auto=True 为回合开始的自动刷新。

        规则:
          - 冻结整馆保留（随从+法术），手动刷新同样保留 (P5)
          - 未冻结的旧内容**回池** (P1 — 旧引擎直接丢弃导致池泄漏)
          - 消耗免费刷新次数优先于金币
          - spells_only=True: 只抽法术（Saloon's Finest "Refresh the
            Tavern with Tavern spells"——馆内展示全部为法术）
          - races: 本次刷新的种族白名单（Overseer's Orb "Refresh it
            with minions of your most common type"）; None 时回落
            game._tavern_race（异变 Only <race>）
          - hero._tavern_offer_tier_only（异变 Elven Elite）: 只抽
            与控制者酒馆等级同 tier 的随从
          - `GameTag.TAVERN_OFFER_TIER_EXACT`（hero 级）: 本次刷新的
            **全部**随从位取自恰好该档（Guiding Candle）
          - `GameTag.TAVERN_EXTRA_TIER_SLOTS` / `TAVERN_EXTRA_TIER`:
            额外 N 个展示位取自恰好 `TAVERN_EXTRA_TIER`（缺省
            `tavern_tier + 1`，封顶 `max_tavern_tier`）（Innkeeper's Stein）
          - `consume_free=False`: **引擎/卡牌赠送的免费刷新**不得消耗玩家
            自有 `FREE_REFRESH_REMAINING`（Warband Whistle "Gain a free
            Refresh"——2026-09-02 对抗验证 BUG-4）
          - `hero._tavern_race_guarantee = (race, n)`（hero 级，回落
            game 级）: 本次刷新的**前 n 个随从位专供**该种族
            （Scepter of Guidance——"always offers 2 {0}"）
        """
        if not auto and hero.get(GameTag.TURN_SKIPPED, False):
            return
        if not auto and getattr(self, "_block_manual_refresh", False):
            return
        if not auto and consume_free:
            free_remaining = hero.get(GameTag.FREE_REFRESH_REMAINING, 0)
            health_refreshes = hero.get(GameTag.HEALTH_REFRESHES_LEFT, 0)
            if free_remaining > 0:
                hero.set(GameTag.FREE_REFRESH_REMAINING, free_remaining - 1)
            elif health_refreshes > 0 and \
                    hero.health + hero.armor > C.REFRESH_COST:
                # Malchezaar: "Two Refreshes each turn cost Health instead
                # of Gold"——以 1 点生命支付（护甲先扣; 不足以支付时
                # 回落金币路径——与购买侧生存守卫一致）
                hero.set(GameTag.HEALTH_REFRESHES_LEFT, health_refreshes - 1)
                hero.take_damage(C.REFRESH_COST)
            elif not free:
                # 刷新费覆盖（Millhouse "Refreshes cost 2 Gold"）
                self.spend_gold(
                    hero, hero.get(GameTag.REFRESH_COST_OVERRIDE,
                                   C.REFRESH_COST))

        keep: List[Entity] = []
        if hero.frozen_tavern:
            keep = list(hero.tavern)
            hero.clear(GameTag.FROZEN)     # 整馆冻结只保留一轮刷新
        else:
            # 单卡冻结（"Freeze a minion" 类效果）: 实体级 FROZEN tag
            keep = [e for e in hero.tavern if e.has(GameTag.FROZEN)]
        for e in keep:                     # 单卡冻结同样只保留一轮
            e.clear(GameTag.FROZEN)
        # 旧内容回池 (P1)。金色化实体（异变 The Golden Arena）的
        # card_id 是金卡 id——回池须用基础卡 id，否则基础副本泄漏。
        for entity in hero.tavern:
            if entity in keep:
                continue
            if isinstance(entity, Minion):
                base_id = entity.get(GameTag.TRIPLE_BASE_CARD_ID, None) \
                    or entity.card_id
                self.minion_pool.release(base_id, 1)
            elif isinstance(entity, Spell):
                self.spell_pool.release(entity.card_id)

        count = max(0, C.TAVERN_OFFERS.get(hero.tavern_tier, 6)
                    + hero.get(GameTag.TAVERN_OFFER_MOD, 0) - len(keep))
        # 展示数固定覆写: hero 级优先（"Your Tavern always has 7 cards"
        # ——Glowing Gauntlet; game 级为全局限定异变，2026-09-02 加 hero 级
        # 以免绑定者的覆写污染对手酒馆）
        override = getattr(hero, "_tavern_offer_override", None)
        if override is None:
            override = getattr(self, "_tavern_offer_override", None)
        if override is not None:
            count = max(0, override - len(keep))
        # 冻结保留的法术同样占展示位（对抗审查 BUG-6: 冻结含法术的馆
        # 连续刷新曾导致法术无限膨胀——RULES §6.17 冻结同时影响随从与法术）
        kept_spells = sum(1 for e in keep if not isinstance(e, Minion))
        hero.tavern = list(keep)
        if copies_of_warband:
            # "Gain a free Refresh that contains **plain copies of minions
            # in your warband**"（Warband Whistle `BG35_MagicItem_930`）:
            # 内容 = 本人棋盘随从的白板副本（零池操作——副本非从池获取）;
            # 受持久酒馆 Buff 影响（add_tavern_entity 统一入口）
            for m in list(hero.board):
                if m.dead:
                    continue
                base_id = m.get(GameTag.TRIPLE_BASE_CARD_ID, None) \
                    or m.card_id
                copy = self.create_minion(base_id, controller=hero)
                if copy is not None:
                    self.add_tavern_entity(hero, copy)
            self.events.fire(self, "tavern_refresh", hero=hero, auto=auto)
            self.events.fire(self, "tavern_refresh_complete", hero=hero,
                             auto=auto)
            return
        if not spells_only:
            _race = races if races is not None \
                else getattr(self, "_tavern_race", None)
            race_filter = None
            if _race is not None:
                if isinstance(_race, (set, frozenset)):
                    race_filter = set(_race) | {Race.ALL}
                else:
                    race_filter = {_race, Race.ALL}
            min_tier = max(getattr(self, "_tavern_min_tier", 1),
                           getattr(hero, "_tavern_min_tier", 1))
            max_tier = hero.tavern_tier
            # 精确档位覆写（"Your first two Refreshes each turn contain
            # only Tier 6 cards"——Guiding Candle `BG32_MagicItem_366`）:
            # 本次**全部**随从位取自恰好该档; 优先于 Elven Elite 的
            # 同档限定（文本更强）
            exact_tier = hero.get(GameTag.TAVERN_OFFER_TIER_EXACT, 0) or None
            if exact_tier is not None:
                min_tier = max_tier = exact_tier
            elif getattr(hero, "_tavern_offer_tier_only", False):
                min_tier = max_tier = hero.tavern_tier   # Elven Elite
            # 存在档位白名单（异变 101/102 "Only Tavern Tiers X, Y, Z
            # exist."）: 本次抽取 = [min_tier, max_tier] ∩ 存在档集合。
            # 非存在档永不进入酒馆; 交集为空则本次无随从可抽（不注入、
            # 不近似——档位对应的随从在当局"不存在"）。
            tier_set = self._ladder_tier_filter(min_tier, max_tier)
            # per-slot 种族保证（"The Tavern always offers 2 {0} whenever
            # it is Refreshed"——Scepter of Guidance `BG27_Reward_812`）:
            # 前 N 个展示位**专供**该种族（含 `Race.ALL` 多类型随从），
            # 其余位走通用/白名单池。hero 级优先，回落 game 级异变。
            # 池不足 N → 按可得数（不注入、不近似）。RULES §7.4.14
            guarantee = getattr(hero, "_tavern_race_guarantee", None)
            if guarantee is None:
                guarantee = getattr(self, "_tavern_race_guarantee", None)
            guaranteed_ids: List[str] = []
            # 英雄视角类型身份（含家族类型改写）——825 的 Dev Comment
            # （wiki revid 814123）"Whelp Smugglers you see in the Tavern"。
            race_of = (lambda d: self.effective_races(hero, d))
            if guarantee is not None:
                g_race, g_n = guarantee
                n_g = min(max(0, int(g_n)), count)
                if n_g > 0:
                    g_races = (set(g_race) if isinstance(
                        g_race, (set, frozenset)) else {g_race})
                    guaranteed_ids = list(self.minion_pool.draw_tavern(
                        max_tier, n_g, races=g_races | {Race.ALL},
                        min_tier=min_tier, tiers=tier_set, race_of=race_of))
            drawn_ids = guaranteed_ids + list(self.minion_pool.draw_tavern(
                max_tier, count - len(guaranteed_ids), races=race_filter,
                min_tier=min_tier, keywords=keywords, tiers=tier_set,
                race_of=race_of))
            # 额外"关键词限定"展示位（"The Tavern offers an extra
            # **Magnetic Mech** whenever it is Refreshed"——Electrode
            # Attractor BG35_MagicItem_743）: hero 级规则
            for src, kws, n in list(getattr(hero,
                                            "_tavern_extra_keyword", [])):
                if src is not None and not (
                        src in hero.trinkets
                        or src in getattr(hero, "quest_rewards", [])
                        or src in hero.board):
                    continue
                drawn_ids += list(self.minion_pool.draw_tavern(
                    max_tier, n, races=race_filter, min_tier=min_tier,
                    keywords=set(kws), tiers=tier_set, race_of=race_of))
            # 额外"高一档"展示位（"The Tavern offers an extra minion of a
            # higher Tier whenever it is Refreshed"——Innkeeper's Stein
            # `BG30_MagicItem_423`）: 独立抽取，档位缺省 tavern_tier+1
            # （封顶 `max_tavern_tier`）
            extra_slots = hero.get(GameTag.TAVERN_EXTRA_TIER_SLOTS, 0)
            if extra_slots > 0:
                extra_tier = hero.get(GameTag.TAVERN_EXTRA_TIER, 0) \
                    or min(hero.tavern_tier + 1, self.max_tavern_tier)
                if extra_tier > 0:
                    drawn_ids += list(self.minion_pool.draw_tavern(
                        extra_tier, extra_slots, races=race_filter,
                        min_tier=extra_tier,
                        tiers=self._ladder_tier_filter(extra_tier,
                                                       extra_tier),
                        race_of=race_of))
            for card_id in drawn_ids:
                if getattr(self, "_tavern_golden", False):
                    # The Golden Arena "ALL minions are Golden"——金色
                    # 本体是独立卡定义，属性翻倍（如 Risen Rider 2/1
                    # → 4/2）。非三连金 → 回池 1 份（GILDED_NOT_TRIPLED）。
                    golden_def = self.db.golden_version(self.db.get(card_id))
                    if golden_def is not None:
                        m = self.create_minion(card_id, controller=hero,
                                               golden=True)
                        m.set(GameTag.GILDED_NOT_TRIPLED, True)
                    else:
                        m = self.create_minion(card_id, controller=hero)
                else:
                    m = self.create_minion(card_id, controller=hero)
                # 入馆统一入口: 持久酒馆 Buff + tavern_entity_added 广播
                # （RULES §7.4.9——"入馆即结算"类读取点不再各自 append）
                self.add_tavern_entity(hero, m)
        if spells_only:
            spell_count = count
        else:
            # 额外法术展示位: hero 级优先（Lubber Sticker "The Tavern
            # offers an extra Tavern spell whenever it is Refreshed"——
            # 饰品必须 hero 作用域，不得污染对手酒馆），回落 game 级异变
            spell_extra = getattr(hero, "_tavern_spell_extra", None)
            if spell_extra is None:
                spell_extra = getattr(self, "_tavern_spell_extra", 0)
            spell_count = max(0, C.TAVERN_SPELLS_PER_REFRESH
                              + spell_extra
                              - kept_spells)
        # 酒馆法术同样受"存在档位"白名单约束（异变 101/102——Tavern spell
        # 的 Tier 即 Tavern Tier，wiki Tavern spell "Like minions, Tavern
        # spells have Tiers, and can only be found in the Tavern once that
        # Tier has been reached."）
        for card_id in self.spell_pool.draw_tavern(
                hero.tavern_tier, spell_count,
                tiers=self._ladder_tier_filter(1, hero.tavern_tier)):
            s = self.create_spell(card_id, controller=hero)
            self.add_tavern_entity(hero, s)
        # Demonology Dark Gift / Trapped Clapper: "Add N Fodders to
        # your next K Refreshes" — 协议 v2: Dict[Hero, (剩余刷新次数,
        # 每次附加枚数)]。每次刷新附加 per_refresh 枚 Demon Fodder
        # token（BG35_150t，非池卡不占池; 其 "feeds itself" 行为由
        # 脚本层实现）
        pending_entry = self._fodder_refresh_pending.get(hero)
        if pending_entry:
            refreshes_left, per_refresh = pending_entry
            for _ in range(per_refresh):
                fodder = self.create_minion(C.FODDER_CARD_ID, controller=hero)
                self.add_tavern_entity(hero, fodder)
            if refreshes_left <= 1:
                del self._fodder_refresh_pending[hero]
            else:
                self._fodder_refresh_pending[hero] = \
                    (refreshes_left - 1, per_refresh)
        # auto=True = 引擎自动刷新（回合开始 / 买后自动），False = 玩家
        # 主动刷新——"Whenever you Refresh the Tavern N times" 类效果可据
        # 此区分（2026-09-02 补: 此前无标记，自动刷新也被计入）
        self.events.fire(self, "tavern_refresh", hero=hero, auto=auto)
        # 刷新窗口**结束**（本事件的所有监听器已跑完——包括在
        # `tavern_refresh` 里追加酒馆内容的效果，如 Laboratory Assistant
        # 的 Fodder）→ "After the Tavern is Refreshed, ..." 类被动在此
        # 结算才能看到完整的刷新后酒馆，且**与监听器注册顺序无关**
        # （2026-09-02 对抗审查: 在 tavern_refresh 内打标会漏掉同事件里
        # 更晚 append 的实体）。RULES §7.4.9
        self.events.fire(self, "tavern_refresh_complete", hero=hero,
                         auto=auto)

    def add_tavern_entity(self, hero: Hero, entity, *,
                          position: Optional[int] = None,
                          replace=None):
        """把一只随从/法术放入某英雄酒馆展示区的**统一入口**。

        职责（与 `inject_tavern_minion` 的展示修正互补）:
          - 应用 `hero.tavern_buffs` 持久酒馆 Buff（新入馆随从）
          - `zone = TAVERN` + append/insert/replace
          - 广播 `tavern_entity_added`（hero=, entity=）——"whenever a
            minion enters the Tavern" / 依赖"入馆即结算"的饰品读取点
            （Cursed Crystal `BG35_MagicItem_150`）。事件在**入馆后**
            广播，故监听器可安全改属性/加 buff。
        `replace`: 就地替换该实体（Snarky Shark / Galakrond 换卡族——
        保持酒馆槽位）。返回该实体。
        """
        from hsrl2.minion import Minion as _MinionCls
        d = self.db.get(entity.card_id)
        if d is not None and isinstance(entity, _MinionCls):
            from hsrl2.entity import Buff as BuffEnchant
            for tb in getattr(hero, "tavern_buffs", []):
                if tb.matches(d):
                    entity.add_buff(BuffEnchant(atk=tb.atk, health=tb.health,
                                                source_id=tb.source_id))
        entity.zone = Zone.TAVERN
        if replace is not None and replace in hero.tavern:
            hero.tavern[hero.tavern.index(replace)] = entity
        elif position is None:
            hero.tavern.append(entity)
        else:
            hero.tavern.insert(position, entity)
        self.events.fire(self, "tavern_entity_added", hero=hero,
                         entity=entity)
        return entity

    # ── 买/卖/打出 (P1/P6/P7) ──

    def _health_buy_race_matches(self, hero: Hero, entity) -> bool:
        """"One <race> each turn costs Health instead of Gold" 的限定匹配。

        `HEALTH_BUY_RACE` 未设（0/None）→ 任意随从; 设了 → 该种族（全种族
        随从视为所有类型，RULES §8）。
        """
        want = hero.get(GameTag.HEALTH_BUY_RACE, 0) or None
        if want is None:
            return True
        # 类型身份集合（AC-3）: 双类型随从对任一限定类型命中; ALL 展开为
        # 全 10 族（旧 `entity.race == Race.ALL` 语义不变）。
        return entity.has_race(Race(want))

    def buy_from_tavern(self, hero: Hero, entity: Entity) -> bool:
        if entity not in hero.tavern:
            return False
        if hero.hand_full():
            return False
        if hero.get(GameTag.TURN_SKIPPED, False):
            return False
        cost = entity.get(GameTag.COST, C.MINION_BUY_COST)
        # 随从购买价平价覆盖（Sindragosa/Millhouse "Minions cost (2)"
        # ——作用于随从不作用于法术）; 免费购买次数优先于覆盖价
        # （Aranna "the first minion you buy each turn is free"）
        if isinstance(entity, Minion):
            if getattr(self, "_minion_cost_is_tier", False):
                cost = entity.tech_level
            override = hero.get(GameTag.TAVERN_MINION_COST_OVERRIDE, 0)
            if override:
                cost = override
            # 条件化购买价（"**Magnetic** Mechs cost (2)" /
            # "Refresh with Battlecry minions. They cost (1)"——743/755）:
            # hero 级规则 [(source, predicate, cost)]，取最低命中价;
            # source 离场即失效
            for src, pred, c in list(getattr(hero,
                                             "_tavern_cost_rules", [])):
                if src is not None and not (
                        src in hero.trinkets
                        or src in getattr(hero, "quest_rewards", [])
                        or src in hero.board):
                    continue
                try:
                    hit = bool(pred(entity))
                except Exception:                       # noqa: BLE001
                    hit = False
                if hit:
                    cost = min(cost, int(c))
            # hero 级 API（脚本用）: 统一注册点
            # （`hero._tavern_cost_rules` 由脚本直接 append）
            # 免费随从购买（Aranna 全类型 / Grifter Portrait "first Pirate"
            # / Warcry Totem "first two Battlecry minions"）——可带种族或
            # 关键词限定（RULES §7.4.4）; 多来源各自独立配额（不互相覆盖）
            if self._take_free_minion_buy(hero, entity):
                cost = 0
        # 酒馆法术折扣（Ominous Seer "下一个酒馆法术便宜 1 金"）
        d = self.db.get(entity.card_id)
        # 酒馆法术折扣（Ominous Seer "Your next Tavern spell costs (1)
        # less" / Primordial Terrarium 等）。**只在购买真正成交时消耗**:
        # 折扣先只作用于本次报价，金币/生命不足而失败时 tag 必须保留
        # （2026-09-02 对抗审查 E2: 旧实现在 gold 检查之前就清零 →
        # 一次失败购买白烧掉"下一个法术"的折扣）。
        applied_spell_discount = False
        free_spell_buy = False
        if d is not None and d.is_pool_spell:
            # 持久折扣（Beyond the Mirage "Tavern spells cost (1) less"）
            pers = hero.get(GameTag.TAVERN_SPELL_COST_MOD, 0)
            if pers:
                cost = max(0, cost - pers)
            # "The first N Tavern spells you buy each turn are free"
            # （Peacebloom Candle; RULES §7.4.4）优先于折扣
            if hero.get(GameTag.FREE_SPELL_BUYS_THIS_TURN, 0) > 0:
                cost = 0
                free_spell_buy = True
            else:
                discount = hero.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0)
                if discount > 0:
                    cost = max(0, cost - discount)
                    applied_spell_discount = True
        # 健康购买（Hasty Excavation "costs Health to buy instead of Gold"）
        # 官方语义: 以生命支付（护甲先扣），生命不足以支付时不可购买。
        # 三种来源（RULES §7.4.7）:
        #   1. 卡自身 `health_cost`（Hasty Excavation）
        #   2. 实体级 `HEALTH_BUY`（BG35_MagicItem_152 给酒馆最高等级随从打标）
        #   3. 英雄级本回合配额 `HEALTH_MINION_BUYS_THIS_TURN` +
        #      `HEALTH_BUY_RACE`（BG32_MagicItem_821 恶魔）/
        #      `HEALTH_SPELL_BUYS_THIS_TURN`（BG32_MagicItem_822 酒馆法术）
        # 配额与实体标记均为**强制**（文本 "costs Health instead of Gold"，
        # 不提供改用金币的选择——与 Hasty Excavation 同口径）; 生命不足 →
        # 购买失败且不消费配额。
        health_quota_tag = None
        health_buy = cost > 0 and (
            bool(d is not None and d.health_cost)
            or bool(entity.get(GameTag.HEALTH_BUY, False)))
        if not health_buy and cost > 0 and isinstance(entity, Spell) \
                and hero.get(GameTag.HEALTH_SPELL_BUYS_THIS_TURN, 0) > 0:
            health_buy = True
            health_quota_tag = GameTag.HEALTH_SPELL_BUYS_THIS_TURN
        if not health_buy and cost > 0 and isinstance(entity, Minion) \
                and hero.get(GameTag.HEALTH_MINION_BUYS_THIS_TURN, 0) > 0 \
                and self._health_buy_race_matches(hero, entity):
            health_buy = True
            health_quota_tag = GameTag.HEALTH_MINION_BUYS_THIS_TURN
        paid_with_health = False
        if health_buy:
            if hero.health + hero.armor > cost:
                hero.take_damage(cost)
                paid_with_health = True
            else:
                return False
        if not paid_with_health:
            if hero.gold < cost:
                return False
            self.spend_gold(hero, cost)
        if paid_with_health and health_quota_tag is not None:
            hero.set(health_quota_tag, hero.get(health_quota_tag, 0) - 1)
        if free_spell_buy:
            hero.set(GameTag.FREE_SPELL_BUYS_THIS_TURN,
                     hero.get(GameTag.FREE_SPELL_BUYS_THIS_TURN, 0) - 1)
        elif applied_spell_discount:
            hero.set(GameTag.NEXT_SPELL_COST_REDUCTION, 0)
        hero.tavern.remove(entity)
        # 法术购买事件（Magicfin Mycologist "after you buy a Tavern
        # spell" 等——随从走 minion_bought）
        if isinstance(entity, Spell):
            self.events.fire(self, SPELL_BOUGHT, spell=entity, hero=hero)
        # 统一走 add_to_hand（on_enter_hand 钩子——Bream Counter/
        # Aureate Laureate 购买路径; unfreeze 批上报缺口 #2）
        # 买入手牌失败（含 `spell_bought`/`on_enter_hand` 监听器刚刚占满
        # 最后一个手牌位）→ 排队等待而非静默销毁（RULES §3.3; 2026-09-02
        # 对抗审查观察项: Magicfin Sticker 类监听器可占满手牌）
        if not hero.add_to_hand(entity):
            self.pending_hand_queue.append((hero, entity))
        if isinstance(entity, Minion):
            self.events.fire(self, "minion_bought", minion=entity)
            self.check_for_triple(hero, entity)   # 三连检查（购买入口）
        # 异变 Golganneth's Tempest: "It Refreshes itself after you buy a
        # card"（auto=True 绕过手动刷新封锁——该异变禁的是玩家主动刷新）
        if getattr(self, "_refresh_on_buy", False):
            self.refresh_tavern(hero, auto=True)
        return True

    def inject_tavern_minion(self, hero: Hero, card_id: str, *,
                             position: Optional[int] = None,
                             golden: Optional[bool] = None):
        """向酒馆展示区注入一只随从——**唯一**入口（RULES §2.5/§7）。

        与 `refresh_tavern` 抽卡后的处理保持一致，消除各脚本自行
        `create_minion + tavern.append` 造成的修正旁路（对抗审查实测:
        Ysera 额外龙在 The Golden Arena 下非金色、Elven Elite 下越档）:

          - `game._tavern_golden`（The Golden Arena）→ 金卡本体 +
            GILDED_NOT_TRIPLED（非三连金，回池 1 份）
          - `golden=True` 显式要求金色（复制金色源——Varden/Tess）
          - `hero.tavern_buffs` 持久面按 matches() 自动应用
          - zone=TAVERN + 追加（或按 position 插入）

        池记账不在此处: 抽卡语义由调用方 `minion_pool.acquire`，复制体
        语义不占池（Rafaam/Tess 先例）。
        返回注入的实体。
        """
        d = self.db.get(card_id)
        if d is None:
            raise KeyError(f"unknown minion card_id {card_id}")
        want_golden = bool(golden) or (
            getattr(self, "_tavern_golden", False)
            and self.db.golden_version(d) is not None)
        m = self.create_minion(card_id, controller=hero, golden=want_golden)
        if want_golden:
            m.set(GameTag.GILDED_NOT_TRIPLED, True)
        return self.add_tavern_entity(hero, m, position=position)

    def set_free_minion_buys(self, hero: Hero, count: int, *,
                             source: str, race=None, keyword=None) -> None:
        """单一入口写"本回合免费随从购买"配额（RULES §7.4.4）。

        多来源（异变 FirstBuyFree / Aranna / Spectral Sight /
        Grifter Portrait / Warcry Totem）**各自独立记账**——同一英雄
        同时持有多张此类效果时不会互相覆盖（2026-09-02 对抗审查 MAJOR:
        旧的单 counter + 限定 tag 模型让"海盗免费"与"战吼免费"退化为
        "海盗且战吼才免费"，且两份额度一并作废）。

        - 每个 `source` 一条配额; 同 source 重复写入 = 重置其已用次数
          （"each turn" 覆盖式语义）
        - **仅本回合有效**: 写入时记录 `game.turn`，跨回合自动失效
        - `race`: Race 值或 None（不限）; `keyword`: GameTag 值或 None
        """
        for q in hero._free_minion_buy_quotas:
            if q["source"] == source:
                q.update(count=int(count), used=0, race=race,
                         keyword=keyword, turn=self.turn)
                self._sync_free_minion_buy_tag(hero)
                return
        hero._free_minion_buy_quotas.append({
            "source": source, "count": int(count), "used": 0,
            "race": race, "keyword": keyword, "turn": self.turn})
        self._sync_free_minion_buy_tag(hero)

    def _sync_free_minion_buy_tag(self, hero: Hero) -> None:
        """把"本回合剩余免费随从购买数"镜像到旧 tag（观察/兼容读取）。

        消费路径以**独立配额**为准（`_take_free_minion_buy` 只在无任何
        配额来源时才回落旧 tag），镜像值不会被二次消费。
        """
        hero.set(GameTag.FREE_MINION_BUYS_THIS_TURN,
                 sum(max(0, q["count"] - q["used"])
                     for q in hero._free_minion_buy_quotas
                     if q["turn"] == self.turn))

    def free_minion_buys_left(self, hero: Hero) -> int:
        """本回合剩余免费随从购买次数（多来源求和; 诊断/观察用）。"""
        if hero._free_minion_buy_quotas:
            return sum(max(0, q["count"] - q["used"])
                       for q in hero._free_minion_buy_quotas
                       if q["turn"] == self.turn)
        return hero.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0)

    @staticmethod
    def _free_buy_qualifiers_match(entity, race_lim, kw_lim) -> bool:
        """种族/关键词限定是否适用于该随从（RULES §7.4.4）。"""
        if race_lim:
            want = Race(race_lim)
            # 类型身份集合（AC-3）; ALL 展开为全 10 族（旧哨兵语义不变）。
            if not entity.has_race(want):
                return False
        if kw_lim is not None and not entity.has(GameTag(kw_lim)):
            return False
        return True

    def _take_free_minion_buy(self, hero: Hero, entity) -> bool:
        """尝试以"免费"成交该随从: 命中则消费一次额度并返回 True。

        优先级: 独立来源配额（`set_free_minion_buys`）→ 旧单 tag 协议
        （`FREE_MINION_BUYS_THIS_TURN` + 限定 tag; 兼容既有脚本/测试）。
        只在**成交路径**调用（失败的购买不得消费额度）。
        """
        for q in hero._free_minion_buy_quotas:
            if q["turn"] != self.turn or q["used"] >= q["count"]:
                continue
            if self._free_buy_qualifiers_match(entity, q["race"],
                                               q["keyword"]):
                q["used"] += 1
                self._sync_free_minion_buy_tag(hero)
                return True
        # 旧 tag 协议仅在**完全没有**独立配额来源时回落（否则镜像 tag
        # 会造成二次消费）
        if hero._free_minion_buy_quotas:
            return False
        n = hero.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0)
        if n > 0 and self._free_buy_qualifiers_match(
                entity,
                hero.get(GameTag.FREE_MINION_BUY_RACE, None),
                hero.get(GameTag.FREE_MINION_BUY_KEYWORD, None)):
            hero.set(GameTag.FREE_MINION_BUYS_THIS_TURN, n - 1)
            return True
        return False

    def _free_minion_buy_matches(self, hero: Hero, entity: Minion) -> bool:
        """（兼容保留）旧 tag 协议的限定匹配。"""
        return self._free_buy_qualifiers_match(
            entity, hero.get(GameTag.FREE_MINION_BUY_RACE, None),
            hero.get(GameTag.FREE_MINION_BUY_KEYWORD, None))

    def sell_minion(self, hero: Hero, minion: Minion) -> bool:
        if minion not in hero.board and minion not in hero.hand:
            return False
        # on_sell 效果
        self.run_script_hook(minion, "on_sell")
        value = C.MINION_SELL_VALUE
        # SELL_VALUE 覆写用 **tag 存在性**判定: `0` 是合法覆写（"出售价
        # 为 0 金" 类异变 BG27_Anomaly_721），真值判定会把它吞掉
        if GameTag.SELL_VALUE in minion.tags:
            value = minion.get(GameTag.SELL_VALUE)
        elif GameTag.SELL_VALUE_OVERRIDE in hero.tags:
            # 英雄级出售价覆写（异变 Uncompensated Upset "sell for (0)"）
            value = hero.get(GameTag.SELL_VALUE_OVERRIDE)
        hero.gold += value
        # 本回合已售随从计数（hero 级; "for each minion you've sold this
        # turn" 家族读取点——Darnassus Pie / Windfall Portrait）
        hero.set(GameTag.MINIONS_SOLD_THIS_TURN,
                 hero.get(GameTag.MINIONS_SOLD_THIS_TURN, 0) + 1)
        self.events.fire(self, "minion_sold", minion=minion)
        # 回池 (P1): 金色 3 份
        if minion in hero.board:
            hero.board.remove(minion)
        if minion in hero.hand:
            hero.hand.remove(minion)
        self.minion_pool.release_minion_entity(minion)
        minion.zone = Zone.REMOVED   # 已回池；不进 graveyard（防淘汰时二次回池）
        self.events.unregister_owner(minion)
        return True

    def discard_card(self, hero: Hero, card, *, source=None) -> bool:
        """弃掉 `hero` 手牌中的一张卡（F-08 Discard 子系统唯一入口）。

        - 仅手牌；从手牌移入 graveyard（弃牌 ≠ 打出/出售：不触发
          on_play/on_sell，不回池——池副本视为被消耗，证据不足，记档）
        - `hero.cards_discarded_this_game += 1`（Parasitic Fleshling /
          Harbinger "each card you've discarded this game" 数据源）
        - 广播 `card_discarded(hero=, card=, source=)`（"Whenever you
          discard a card" 家族监听点）
        - 分发放 `on_discard` 钩子（"If you discard this, cast it
          twice" 家族：Sludge Corrosion / Energizing Chamber）
        """
        if card is None or card not in hero.hand:
            return False
        hero.hand.remove(card)
        card.zone = Zone.GRAVEYARD
        hero.cards_discarded_this_game = getattr(
            hero, "cards_discarded_this_game", 0) + 1
        self.events.fire(self, "card_discarded",
                         hero=hero, card=card, source=source)
        self.run_script_hook(card, "on_discard",
                             ctx={"hero": hero, "source": source})
        return True

    def play_minion(self, hero: Hero, minion: Minion,
                    position: Optional[int] = None,
                    target: Optional[Entity] = None,
                    magnetic_target: Optional[Minion] = None) -> bool:
        if hero.get(GameTag.TURN_SKIPPED, False):
            return False
        """从手牌打出随从。

        Magnetic (RULES §6.14): 磁力随从可指定 magnetic_target（友方
        机械）吸附而非召唤——属性/关键词并入宿主，亡语效果栈叠保留。

        定向战吼 (RULES §6.10 + wiki [Targeted] 先例): 脚本类声明
        ``needs_target = True`` 时，未提供 target 则产生
        PendingChoice(kind="battlecry_target")，玩家选择后继续打出流程;
        无合法候选 → 战吼落空但随从照常入场（官方: 不可定向的战吼
        上场仍成立）。

        Choose One: 脚本类声明 ``choose_options = [(key, label), ...]``
        时，产生 PendingChoice(kind="choose_one")，选定 key 传入
        ctx={"choose": key} 后触发 on_play 钩子。
        """
        # UNPLAYABLE: CardDef.unplayable 权威 + 实体级手牌锁定
        # （Search Through Time "Lock it in your hand until next turn"）
        d = self.db.get(minion.card_id)
        if minion not in hero.hand or (d is not None and d.unplayable) \
                or minion.has(GameTag.LOCKED_IN_HAND):
            return False
        # 磁力吸附路径（先于满板检查——吸附不占板位）
        if magnetic_target is not None and minion.has(GameTag.MAGNETIC):
            if (magnetic_target.controller is not hero
                    or magnetic_target.dead
                    or magnetic_target.zone != Zone.PLAY
                    or not self._magnetic_valid(minion, magnetic_target)):
                return False
            hero.hand.remove(minion)
            self.attach_magnetic(hero, minion, magnetic_target)
            self.events.fire(self, "card_played", card=minion)
            # 声明成真（ENGINE_BACKLOG #21）: `minion_played` 此前零生产点
            self.events.fire(self, MINION_PLAYED, minion=minion)
            return True
        if hero.board_full():
            self.events.fire(self, "minion_overflow", minion=minion)
            return False

        script = minion.scripts
        # 官方打出顺序: 随从入场 → (Choose One 选择 / 战吼目标选择) → 结算。
        # 战吼可以以打出随从**自身**为目标（先入场是必要前提）。
        hero.hand.remove(minion)
        hero.set(GameTag.CARDS_PLAYED_THIS_TURN,
                 hero.get(GameTag.CARDS_PLAYED_THIS_TURN, 0) + 1)
        self.summon(hero, minion, position)

        # Choose One 分流（RULES: 打出时二选一）。双效合并: 棋盘
        # CHOOSE_BOTH 光环（Thorned Trailblazer）或实体自带 CHOOSE_BOTH
        # tag（Fandral's Fortune 发现的恒双效卡）时跳过选择直接双效
        both = (hero.get(GameTag.CHOOSE_BOTH, False)     # 光环类（308）
                or any(m.has(GameTag.CHOOSE_BOTH) for m in hero.board)
                or minion.has(GameTag.CHOOSE_BOTH))
        if script is not None and getattr(script, "choose_options", None):
            if both:
                return self._run_play_effects(hero, minion, target=target,
                                              choose="both")
            options = list(script.choose_options)
            self.pending_choices.append(PendingChoice(
                hero, [k for k, _ in options], "choose_one",
                resolve_callback=lambda key: self._run_play_effects(
                    hero, minion, target=target, choose=key)))
            return True

        # 定向战吼分流
        if script is not None and getattr(script, "needs_target", False):
            cand_fn = getattr(script, "target_candidates", None)
            candidates = (list(cand_fn(minion, self))
                          if cand_fn is not None
                          else [m for m in hero.board if not m.dead])
            if target is not None:
                if target not in candidates:
                    # 非法目标: 随从已入场（不可撤回），战吼落空
                    return self._run_play_effects(hero, minion)
            elif candidates:
                self.pending_choices.append(PendingChoice(
                    hero, candidates, "battlecry_target",
                    resolve_callback=lambda pick: self._run_play_effects(
                        hero, minion, target=pick)))
                return True
            # 无候选: 战吼落空，随从已入场
        return self._run_play_effects(hero, minion, target=target)

    def _run_play_effects(self, hero: Hero, minion: Minion,
                          target: Optional[Entity] = None,
                          choose: Optional[str] = None) -> bool:
        """打出后的效果结算: 战吼（金色×2/Brann×2）→ 死亡检查 →
        card_played 广播 → 手牌三连的金色打出时发放三连奖励。"""
        ctx = {}
        if target is not None:
            ctx["target"] = target
        if choose is not None:
            ctx["choose"] = choose
        # 战吼: 金色双倍 (金色卡定义自带数值；触发次数=2)，Brann 叠加
        # （金色 Brann 族 ×3——倍率累加，对抗审查 BUG-7 同族修复）
        extra_bc = sum(2 if m.is_golden else 1
                       for m in hero.board
                       if m.has(GameTag.BATTLECRY_DOUBLER))
        times = 1
        if minion.is_golden:
            times *= 2
        times += extra_bc
        # 战吼额外触发（RULES §6.20）: bc_times 单独声明 = 全部己方战吼
        # +N（Gilnean War Horn "Your Battlecries trigger an extra time"）;
        # 同时声明 bc_race = 仅该种族（Dragon's Eye "Your Dragons'
        # Battlecries..."）
        # 全局配额（Gilnean War Horn "Your Battlecries trigger an extra
        # time"）与**种族限定**配额（Dragon's Eye "Your Dragons'
        # Battlecries..."）是两个独立 key（2026-09-02 对抗审查 D3: 旧版用
        # 单个 bc_race 让种族限定**改写**了全局配额 → 同时拥有两张卡时全局
        # +N 被静默降级为仅龙）
        times += hero.extra_trigger("bc_times")
        # **每回合限定**的战吼配额（RULES §6.20 `bc_first`）: "Your first
        # N Battlecries each turn trigger an extra time"（War Drum）——
        # 与 `bc_times`（永久全量）分开，避免脚本侧清零覆盖其它来源
        # （2026-09-02 对抗审查/批 14 台账）。**只有真正会触发战吼的随从**
        # 才消费配额（2026-09-02 对抗审查证伪: 旧版先打白板即吃掉配额）
        if self._has_battlecry_hook(minion) \
                and hero.consume_extra_trigger("bc_first"):
            # `bc_first_times`（默认 1）= 每次额外触发**几次**——
            # War Drum 35.2.0 后的文本 "One Battlecry each turn triggers
            # **two** extra times"（num(0)=1 个战吼 / num(1)=2 次）
            times += max(1, hero.extra_trigger("bc_first_times") or 1)
        _bc_race = hero.extra_triggers.get("bc_race")
        if _bc_race is not None:
            # 类型身份集合（AC-3）——双类型随从对任一限定类型命中
            # （wiki `Multi-type minion` revid 855346）。
            if minion.has_race(Race(_bc_race)):
                times += hero.extra_trigger("bc_times_race")
        for _ in range(times):
            self.run_script_hook(minion, "battlecry", ctx=ctx or None)
            # 每次战吼触发计数 + 广播（Brann/金色双倍各计一次——
            # 官方 "for each Battlecry you've triggered" 按触发次数计）。
            # 门禁用 `has_battlecry`（2026-09-13, RULES §7.4.17）: 关键词
            # tag 或脚本钩子（金卡数据缺口）或**已生效的条件化战吼**
            # （Selfless Portrait）都算"触发了一次战吼"。
            if self.has_battlecry(minion):
                hero.set(GameTag.COUNTER_BATTLECRIES,
                         hero.get(GameTag.COUNTER_BATTLECRIES, 0) + 1)
                self.events.fire(self, "battlecry_trigger", minion=minion)
        self.check_deaths()
        # 本局金色打出计数（Maritime Extortionist / Hooktusk 数据源）——
        # 先于 card_played 广播（监听器读计数须含正在打出的这张）
        if minion.is_golden:
            hero.set(GameTag.GOLDEN_MINIONS_PLAYED,
                     hero.get(GameTag.GOLDEN_MINIONS_PLAYED, 0) + 1)
        # "Whenever you play a card" 类（Dexterity 等）监听源
        self.events.fire(self, "card_played", card=minion)
        self.events.fire(self, MINION_PLAYED, minion=minion)
        # 元素打出簿记（"for each Elemental you played this game"——
        # BG26_537 Flourishing Frostling 动态属性读数）与
        # `elemental_played` 广播（events.py 常量此前零 fire）
        _is_elemental = minion.has_race(Race.ELEMENTAL)
        if _is_elemental:
            hero.set(GameTag.COUNTER_ELEMENTALS_PLAYED,
                     hero.get(GameTag.COUNTER_ELEMENTALS_PLAYED, 0) + 1)
            # F-06: 本回合元素打出计数（"Improved by each Elemental you
            # played this turn"——Conflagration/Firelands 读取；
            # `_begin_recruit_for` 清零）。与游戏长 COUNTER_ELEMENTALS_
            # PLAYED 同一写入点，但**不**改写后者（既有卡行为不变）。
            hero.elementals_played_this_turn = \
                getattr(hero, "elementals_played_this_turn", 0) + 1
            self.events.fire(self, "elemental_played", minion=minion)
        # 三连奖励: 手牌合成的金色打出时发放（RULES §10.3）
        if minion.is_golden and minion.has(GameTag.TRIPLE_REWARD_PENDING):
            self._grant_triple_reward(hero, minion)
        # 打出后三连检查（2 手牌 + 打出第 3 张路径——官方时序: 战吼
        # 结算后合成，金色替换场上位置; 对抗审查 BUG-1 接线）
        if not minion.is_golden:
            self.check_for_triple(hero, minion)
        return True

    # ── 三连合成 (RULES §10) ──

    def check_for_triple(self, hero: Hero, acquired: Minion) -> None:
        """一张随从进入手牌/棋盘后检查三连（购买/获取/打出路径统一入口）。

        RULES §10.1: 收集 3 个相同非金色随从 → 自动合成金色版本。
        RULES §10.2: 金色保留三个原始随从的**全部**增益（buff 求并叠加）。
        区域规则:
          - 参与副本 ≥1 在棋盘 → 金色出现在棋盘（最左参与副本的位置），
            奖励立即发放（官方: 场上合成即弹发现窗）
          - 全部在手牌 → 金色入手，打出时发放奖励（TRIPLE_REWARD_PENDING）
        池记账: 3 份基础卡已在购买/获取时扣减，合成不额外占池; 金色出售
        返还 3 份（release_minion_entity 已实现）。

        替代合成（Elemental of Surprise BG26_175 "can triple with any
        Elemental as a substitute"）: 手牌/棋盘存在该卡时，2 张同名
        元素 + 1 张任意元素（替代位）亦可合成——替代副本作为第三份
        参与合并。
        """
        if acquired.is_golden or not isinstance(acquired, Minion):
            return
        d = self.db.get(acquired.card_id)
        if d is None or not d.is_pool_minion:
            return   # token 不三连

        def _combine(base_card_id: str, participants):
            base_def = self.db.get(base_card_id)
            if base_def is None or not base_def.is_pool_minion:
                return
            golden_def = self.db.golden_version(base_def)
            if golden_def is None:
                self.dark_gift_audit_log.append(
                    f"MISSING_GOLDEN_DEF: {base_card_id}")
                return
            golden = self.create_minion(golden_def.id, controller=hero,
                                        golden=True)
            golden.set(GameTag.TRIPLE_BASE_CARD_ID, base_card_id)
            for m in participants:
                m.copy_buffs_to(golden)
            board_participants = [m for m in participants if m in hero.board]
            if board_participants:
                pos = min(hero.board.index(m) for m in board_participants)
                for m in participants:
                    if m in hero.board:
                        hero.board.remove(m)
                    if m in hero.hand:
                        hero.hand.remove(m)
                    m.zone = Zone.REMOVED
                    # 被并随从离场 → 注销其全部监听器（修复: 此前遗漏导致
                    # 三连后旧监听器永久残留，如 Czarina 三连后触发 3+1 次）
                    self.events.unregister_owner(m)
                self.summon(hero, golden, pos)
                self.events.fire(self, "triple_combined", golden=golden)
                # 奖励替代（Clocksworth "give Tavern Coins instead of
                # Triple Rewards"）: N 张 Tavern Coin 直入手，不弹发现
                coins_n = hero.get(GameTag.TRIPLE_REWARD_COINS, 0)
                if hero.get(GameTag.TRIPLE_NO_REWARD, False):
                    pass   # 异变 801 "you do not get Triple Rewards"
                elif coins_n:
                    self._grant_tavern_coins(hero, coins_n)
                else:
                    self._grant_triple_reward(hero, golden)
            else:
                for m in participants:
                    hero.hand.remove(m)
                    m.zone = Zone.REMOVED
                    self.events.unregister_owner(m)
                coins_n = hero.get(GameTag.TRIPLE_REWARD_COINS, 0)
                if coins_n:
                    # 硬币即时到手，无需 pending 奖励标记
                    self._grant_tavern_coins(hero, coins_n)
                else:
                    golden.set(GameTag.TRIPLE_REWARD_PENDING, True)
                # 满手排队（对抗审查: add_to_hand 失败金色静默消失）
                self.pending_hand_add(hero, golden)
                self.events.fire(self, "triple_combined", golden=golden)

        copies = [m for m in hero.hand + hero.board
                  if isinstance(m, Minion)
                  and m.card_id == acquired.card_id and not m.is_golden]
        # 三连阈值（Clocksworth "You only need 2 copies to make minions
        # Golden"——默认 3）
        threshold = hero.get(GameTag.TRIPLE_THRESHOLD, 3)
        # **按种族**的三连阈值（"You only need 2 copies of a **Pirate** to
        # make it Golden"——Designer Eyepatch BG30_MagicItem_439）:
        # `hero.triple_threshold_race = {Race: n}`（全种族 ALL 命中一切;
        # hero 级全局 `TRIPLE_THRESHOLD` 仍是兜底/覆盖基础值）
        _acquired_def = self.db.get(acquired.card_id)
        _race = getattr(_acquired_def, "race", None)
        for _r, _n in list(getattr(hero, "triple_threshold_race",
                                   {}).items()):
            if _race == _r or _race == Race.ALL or _r == Race.ALL:
                threshold = min(threshold, int(_n))
        if len(copies) >= threshold:
            _combine(acquired.card_id, copies[:threshold])
            return
        # Elemental of Surprise (BG26_175) 替代合成——全池重扫（与到达
        # 顺序无关，对抗审查 BUG-2 修复）。官方依据: wiki patch notes
        # "using Elemental of Surprise to triple Marine Matriarch" /
        # "tripling an All type minion"——175 是百搭第三份，双向合法:
        #   A) 2×BG26_175 + 任意 1 张其他元素（含 ALL）→ 金色 = 175 金
        #   B) 2×同名元素（含 ALL）+ 1×BG26_175 → 金色 = 该元素金
        SUB_CARD = "BG26_175"
        pool_all = [m for m in hero.hand + hero.board
                    if isinstance(m, Minion) and not m.is_golden]
        surprises = [m for m in pool_all if m.card_id == SUB_CARD]
        elem_others = [m for m in pool_all
                       if m.card_id != SUB_CARD
                       and m.has_race(Race.ELEMENTAL)]
        if len(surprises) >= 2 and elem_others:
            _combine(SUB_CARD, surprises[:2] + [elem_others[0]])
            return
        if surprises:
            groups: dict = {}
            for m in elem_others:
                groups.setdefault(m.card_id, []).append(m)
            for cid, group in groups.items():
                if len(group) >= 2:
                    _combine(cid, group[:2] + [surprises[0]])
                    return

    def _grant_tavern_coins(self, hero: Hero, n: int) -> None:
        """Tavern Coin（BG28_810，T1 池法术）×n 入手（满手排队）。"""
        COIN = "BG28_810"
        for _ in range(n):
            coin = self.create_spell(COIN, controller=hero)
            if coin is None:
                self.dark_gift_audit_log.append(
                    f"MISSING_TAVERN_COIN: {COIN}")
                return
            if not hero.add_to_hand(coin):
                self.pending_hand_add(hero, coin)

    def _grant_triple_reward(self, hero: Hero, golden: Minion) -> None:
        """三连奖励: 发现一张 tier+1 的随从（T6 → T6, RULES §10.3）。

        异变 BG27_Anomaly_101/102 文本覆盖档位口径: "Triple Rewards
        **Discover** a minion of your Tier."（`_triple_reward_of_own_tier`）
        → 奖励档 = 本人**当前**酒馆档位（在结算"三连成立"这一刻读取;
        本函数在 `check_for_triple` / 金色打出路径同步调用，档位不可能
        在两者之间变化，故无快照时序问题）。

        AMBIGUOUS: 发现选项是否受池约束——按官方"发现受共享池限制"
        （RULES §6.18）实现，Discover Action 已池感知。
        """
        golden.clear(GameTag.TRIPLE_REWARD_PENDING)
        base_tier = self.db.get(golden.get(GameTag.TRIPLE_BASE_CARD_ID,
                                           golden.card_id))
        tier = base_tier.tech_level if base_tier else golden.tech_level
        if self._triple_reward_of_own_tier:
            reward_tier = hero.tavern_tier
        else:
            reward_tier = min(tier + 1, self.max_tavern_tier)
        from hsrl2.actions.discover import Discover
        self.run_actions(Discover(hero, count=3, max_tier=reward_tier,
                                  min_tier=reward_tier,
                                  kind="triple_reward"))

    def summon(self, hero: Hero, minion: Minion,
               position: Optional[int] = None) -> bool:
        if hero.board_full():
            self.events.fire(self, "minion_overflow", minion=minion)
            return False
        minion.game = self            # 直建实体补挂 game（buff_applied 等）
        minion.controller = hero
        minion.zone = Zone.PLAY
        # 满血入场（含种族光环生命部分——"wherever they are" 对新入场
        # 随从同样生效且不显示受损态; ApplyRaceAura 对已在场者的对称处理
        # 见 actions/racefx.py）
        # 防御: 入场实体必须存活（快照/副本路径可能带上 DEAD 状态 tag →
        # 死着入场不能攻击且立即进死亡链——2026-09-02 对抗验证 BUG-440）
        minion.clear(GameTag.DEAD)
        minion.set(GameTag.HEALTH, minion.max_health)
        if position is None or position > len(hero.board):
            position = len(hero.board)
        hero.board.insert(position, minion)
        self._update_positions(hero)
        self.events.fire(self, "summon", minion=minion)
        self.run_script_hook(minion, "on_summon")
        if self.in_combat:
            self.combat_summon_log.append(minion)
        return True

    def _battlecry_doubled(self, hero: Hero) -> bool:
        """Brann 式光环: 棋盘上存在即生效（离场失效 — 生命周期修复）。
        异变 BG27_Anomaly_802 全局 +1 触发。"""
        if getattr(self, "_extra_bc_dr", False):
            return True
        return any(m.has(GameTag.BATTLECRY_DOUBLER) for m in hero.board)

    # ── Magnetic 磁力吸附 (RULES §6.14) ──

    def _magnetic_valid(self, magnetic_minion: Minion,
                        target: Minion) -> bool:
        """吸附目标合法性: 友方机械。

        数据例外（CardDef 文本/数据核实）:
        - Prosthetic Hand (BG_DEEP_015): "Can Magnetize to Mechs
          **or Undead**"
        - Technical Element (BG31_859): Mechs 或 Elementals
        - Mecha-Jaraxxus 的 4 张 token（BG25_807t/t2/t3/t4）:
          "Can **Magnetize** to Mechs *and* **Demons**"（Mecha-Jaraxxus
          Sticker `BG30_MagicItem_942` 授予；2026-09-02 对抗审查发现
          此前对恶魔宿主全部 False）
        """
        valid = {Race.MECH}
        mid = magnetic_minion.card_id
        if mid in ("BG_DEEP_015", "BG_DEEP_015_G"):
            valid.add(Race.UNDEAD)
        elif mid in ("BG31_859", "BG31_859_G"):
            valid.add(Race.ELEMENTAL)
        elif mid.split("_G")[0] in ("BG25_807t", "BG25_807t2",
                                   "BG25_807t3", "BG25_807t4"):
            valid.add(Race.DEMON)
        # 类型身份集合（AC-3）: 任一合法类型命中即合法; ALL 宿主经
        # `has_race` 展开为全 10 族（旧 `Race.ALL` 哨兵语义不变）。
        return any(target.has_race(r) for r in valid)

    def attach_magnetic(self, hero: Hero, magnetic_minion: Minion,
                        host: Minion) -> None:
        """磁力吸附结算 (RULES §6.14):
          - 攻击/生命相加——按磁力随从**实体当前值**（含 buff——官方
            语义: 吸附的是实体属性而非卡面定义; Wave2 G1 修正）
          - 关键词并入（圣盾/嘲讽/复生/风怒/剧毒/猛毒等）
          - 磁力随从的亡语**栈叠**保留: 宿主死亡时依次触发
          - 宿主仍占一个格子; 磁力随从离场（不进 graveyard、不回池——
            官方: 被磁力的随从在主体被出售时返还池中）
        """
        host.set(GameTag.BASE_ATK,
                 host.get(GameTag.BASE_ATK, 0) + magnetic_minion.atk)
        hp_gain = magnetic_minion.max_health
        host.set(GameTag.BASE_HEALTH, host.get(GameTag.BASE_HEALTH, 0) + hp_gain)
        host.set(GameTag.HEALTH, host.health + hp_gain)
        md = self.db.get(magnetic_minion.card_id)
        for kw, tag in _KEYWORD_TAG_MAP.items():
            if md is not None and kw in md.keywords:
                host.set(tag, True)
        # 亡语栈叠（宿主死亡时按吸附顺序触发）
        self._magnetic_stack.setdefault(host.uuid, []).append(
            magnetic_minion.card_id)
        if md.keywords and "deathrattle" in md.keywords:
            host.set(GameTag.DEATHRATTLE, True)
        magnetic_minion.zone = Zone.REMOVED
        self.events.fire(self, "magnetized", host=host,
                         attached=magnetic_minion)

    def play_spell(self, hero: Hero, spell: Spell,
                   target: Optional[Entity] = None) -> bool:
        if hero.get(GameTag.TURN_SKIPPED, False):
            return False
        """从手牌施放法术。

        定向法术（needs_target=True 声明，与 play_minion 同构）: 未提供
        target → PendingChoice(kind="spell_target")，选定后结算; 无候选
        → 效果落空但法术照常消耗（官方: 无法术目标时法术仍可施放）。

        计数分流（官方语义）:
          - **酒馆法术**（is_pool_spell）才计入 TAVERN_SPELLS_CAST_* 并
            广播 tavern_spell_cast——"每施放一个酒馆法术"类效果的数据源
          - Spellcraft 法术单独广播 spellcraft_cast
          - 血宝石/Dark Gift 等生成法术: 只广播 card_played
        """
        d = self.db.get(spell.card_id)
        if spell not in hero.hand or (d is not None and d.unplayable) \
                or spell.has(GameTag.LOCKED_IN_HAND):
            return False

        script = spell.scripts
        # Choose One 法术（脚本声明 choose_options，与随从同构）。
        # both_options 光环（Thorned Trailblazer "has both effects combined"）
        # 生效时跳过选择、直接以 choose="both" 双效结算
        if script is not None and getattr(script, "choose_options", None):
            both = (hero.get(GameTag.CHOOSE_BOTH, False)
                    or any(m.has(GameTag.CHOOSE_BOTH) for m in hero.board))
            if both:
                return self._finish_play_spell(hero, spell, target=target,
                                               card_def=d, choose="both")
            options = list(script.choose_options)

            def _choose_finish(key):
                self._finish_play_spell(hero, spell, target=target,
                                        card_def=d, choose=key)
            self.pending_choices.append(PendingChoice(
                hero, [k for k, _ in options], "choose_one",
                resolve_callback=_choose_finish))
            return True
        if script is not None and getattr(script, "needs_target", False) \
                and target is None:
            cand_fn = getattr(script, "target_candidates", None)
            candidates = (list(cand_fn(spell, self))
                          if cand_fn is not None
                          else [m for m in hero.board if not m.dead])
            if candidates:
                self.pending_choices.append(PendingChoice(
                    hero, candidates, "spell_target",
                    resolve_callback=lambda pick: self._finish_play_spell(
                        hero, spell, target=pick, card_def=d)))
                return True
            # 无候选: 落空但照常消耗
        return self._finish_play_spell(hero, spell, target=target, card_def=d)

    def _resolve_cast_permanence(self, hero: Hero, spell: Spell,
                                 target: Optional[Entity]) -> bool:
        """**施放期永久化解析**（手牌路径与效果施法共用，RULES §7.4.7a）。

        生成期已标记 `permanent_spellcraft` **或**施放时按
        `spellcraft_source_uuid` 反查来源随从仍命中有效规则 → 把标记
        **回写**到法术实体（载荷脚本读同一标记，如 Weary Portrait 的
        Reinvigoration 关键词分支），并把本次施放的**目标**置为待翻转
        实体（`_permanence_pending`，Lava Lurker 拦截窗口）。
        缺回写则"绑定当回合、法术已先生成"的时序下载荷看不到永久化
        （BG32_MagicItem_933 对抗审查 BUG-1）。
        """
        if not isinstance(target, Minion):
            return False
        perm = bool(getattr(spell, "permanent_spellcraft", False))
        if not perm:
            src_uuid = getattr(spell, "spellcraft_source_uuid", None)
            if src_uuid is not None:
                src = next((x for x in hero.board
                            if x.uuid == src_uuid and not x.dead), None)
                if src is not None \
                        and self._permanent_spellcraft_matches(hero, src):
                    perm = True
        if perm:
            spell.permanent_spellcraft = True
            self._permanence_pending = target.uuid
        return perm

    def combat_spell_extra_casts(self, hero: Hero) -> int:
        """战斗内法术额外施放次数（默认 0；Maelstrom Emergent 等写入）。

        契约:
          - 默认 0 → `cast_spell_effect` 行为逐位不变；
          - 非负整数；来源 = hero 级属性 `_combat_spell_extra_casts`
            （由卡脚本设置，例如 "Your spells cast an extra time in
            combat." = 1）；
          - 只有 `cast_spell_effect`（效果施法）且 `game.in_combat`
            时消费；招募期/手牌打出不走此通道（当前无卡需要）。
        """
        if hero is None:
            return 0
        try:
            value = int(getattr(hero, "_combat_spell_extra_casts", 0) or 0)
        except (TypeError, ValueError):
            return 0
        return max(0, value)

    def cast_spell_effect(self, hero: Hero, card_id: str,
                          target: Optional[Entity] = None,
                          source: Optional[Entity] = None) -> bool:
        """**效果施法**（"Cast X"，非手牌打出）——统一入口。

        统一裁定（batch_rally2 先例，RULES §6.16 注）:
        - 不经手牌、不耗金币、**不动法术池**（"施放即回池"在效果路径下
          净变化为 0）
        - 不计 `TAVERN_SPELLS_CAST_*`、不广播 `tavern_spell_cast` /
          `card_played` / `spell_bought`（事件语义为手牌打出）
        - 定向法术（脚本 `needs_target=True`）: `target=None` 时从
          `target_candidates`（未声明则本人存活随从）**随机**取一个;
          无候选 → 落空返回 False（不抛错中断回合）
        - `target` 已给但已离场/死亡 → 落空返回 False
        - `source`（2026-09-14 第二十四轮）: **重施放**场景传原始法术实体
          （如 Lovely Locket `BG36_MagicItem_211`）→ 继承其
          `spellcraft_source_uuid` 并复用施放期永久化解析（
          `_resolve_cast_permanence`，RULES §7.4.7a）; 缺此参数则
          "permanent Spellcraft" 在该入口失效（`ENGINE_BACKLOG` #26）。
        返回 True=已结算（含落空但流程完成）; False=未结算。
        """
        d = self.db.get(card_id)
        if d is None or d.card_type not in (CardType.SPELL,
                                            CardType.BACON_SPELL):
            return False
        prev_pending = getattr(self, "_permanence_pending", None)
        from hsrl2.scripts import REGISTRY
        script = REGISTRY.get(card_id)
        spell = self.create_spell(card_id, controller=hero)
        spell.scripts = script
        if source is not None:
            src_uuid = getattr(source, "spellcraft_source_uuid", None)
            if src_uuid is not None:
                spell.spellcraft_source_uuid = src_uuid
            # 同一法术**已解析**的永久化标记一并继承: 来源已离场/饰品已失效
            # 时签名反查会失手，但同一份法术在直施路径仍判永久 → 两条施放
            # 路径对同一法术必须同结论（对抗审查 FALSIFIER 1）。
            if getattr(source, "card_id", None) == card_id \
                    and getattr(source, "permanent_spellcraft", False):
                spell.permanent_spellcraft = True
        # ── 战斗内额外施放（F-12 原语）──
        extra = self.combat_spell_extra_casts(hero) if self.in_combat else 0
        casts = 1 + extra
        resolved = 0
        for cast_no in range(1, casts + 1):
            if script is not None and getattr(script, "needs_target",
                                              False):
                if target is None:
                    cand_fn = getattr(script, "target_candidates", None)
                    candidates = (list(cand_fn(spell, self))
                                  if cand_fn is not None
                                  else [m for m in hero.board if not m.dead])
                    if not candidates:
                        if cast_no == 1:
                            return False      # 无合法目标 → 落空
                        break
                    target = self.rng.choice(
                        candidates, label="cast_spell_effect_target")
                if target is None or getattr(target, "dead", False) \
                        or (isinstance(target, Minion)
                            and target not in hero.board):
                    if cast_no == 1:
                        return False
                    break                    # 目标已失效 → 停止额外施放
            # 每次施放广播 `spell_resolving`（与手牌路径同源——效果施法同样
            # 是"施放了一个法术"）: 永久化拦截窗口与"施放后"类被动监听器
            # （Blessing Portrait 的手牌同类型分支 / 计数类饰品）据此生效。
            # 仍**不**计入 `TAVERN_SPELLS_CAST_*`、不广播 `tavern_spell_cast` /
            # `card_played` / `spell_bought`（RULES §7.4.7b）
            # 永久化解析（与手牌路径同源）: `source=` 继承来源随从 → 命中规则则
            # 标记并置待翻转目标（ENGINE_BACKLOG #26 修复）。
            self._resolve_cast_permanence(hero, spell, target)
            self.events.fire(self, "spell_resolving", spell=spell,
                             target=target, cast_no=cast_no)
            if script is not None and getattr(script, "on_play", None):
                result = script.on_play(spell, self, {"target": target})
                self.run_actions(result)
            self.events.fire(self, "spell_resolved", spell=spell,
                             target=target, cast_no=cast_no)
            resolved += 1
        # 嵌套施法（如 Coral Spear 在 `spell_resolving` 中再施放）必须**恢复**
        # 外层窗口——盲目清零会让外层目标的 temporary buff 翻转丢失
        # （对抗审查 FALSIFIER 2，2026-09-14 第二十四轮）。
        if prev_pending is not None:
            self._permanence_pending = prev_pending
        else:
            self._permanence_pending = None
        return resolved > 0

    def _finish_play_spell(self, hero: Hero, spell: Spell,
                           target: Optional[Entity],
                           card_def=None,
                           choose: Optional[str] = None) -> bool:
        hero.hand.remove(spell)
        if spell.has(GameTag.SPELLCRAFT):
            self.events.fire(self, "spellcraft_cast", spell=spell)
        # Balinda Stonehearth: "Your spells that target friendly minions
        # cast twice"——定向友方随从的法术效果多施（棋盘扫描光环，离场
        # 失效; 金色 Balinda "cast three times" → 额外+2; 计数/事件按
        # 施放次数计——对抗审查 BUG-7: 布尔改倍率累加）
        from hsrl2.minion import Minion as _MinionType
        extra_casts = sum(2 if m.is_golden else 1
                          for m in hero.board
                          if m.has(GameTag.SPELL_DOUBLER))
        double_cast = (
            isinstance(target, _MinionType)
            and target.controller is hero
            and not target.dead
            and extra_casts > 0)
        ctx = {"target": target}
        if choose is not None:
            ctx["choose"] = choose
        casts = 1 + extra_casts if double_cast else 1
        # "Your first spell each turn casts an extra time"（Replica
        # Cathedral）与 "Your first two Spellcraft spells each turn cast an
        # extra time"（Sushi Roll）是两个**独立**配额; 法术塑造法术同时
        # 属于"spell"，故两个配额都可消费（2026-09-02 对抗审查 D2: 旧版
        # 二选一 → Spellcraft 法术不消费 spell_first，Cathedral 的"第一个
        # 法术"被跳过）
        if spell.has(GameTag.SPELLCRAFT) \
                and hero.consume_extra_trigger("spellcraft_first"):
            casts += 1
        if hero.consume_extra_trigger("spell_first"):
            casts += 1
        # "Your Tavern spells cast an extra time"（Temporal Tampering
        # `BG28_Reward_501`）: hero 级**永久**额度（`extra_triggers`——
        # 不消费/不按回合重置，每个酒馆法术都多结算一次）; 门禁 =
        # `card_def.is_pool_spell`（只对酒馆法术生效，Spellcraft/
        # 血宝石/Dark Gift 等生成法术不适用）。与 Balinda 的棋盘
        # `SPELL_DOUBLER` 光环、`spell_first` 配额**独立叠加**
        # （三者语义互不覆盖）。RULES §7.4.14
        if card_def is not None and card_def.is_pool_spell:
            casts += hero.extra_trigger("tavern_spell_extra_cast")
        for _ in range(casts):
            if card_def is not None and card_def.is_pool_spell:
                hero.set(GameTag.TAVERN_SPELLS_CAST_THIS_TURN,
                         hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_TURN, 0) + 1)
                hero.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME,
                         hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0) + 1)
            # 永久化拦截窗口（Lava Lurker: spell_resolving 事件中脚本
            # 设置 game._permanence_pending，add_buff 翻转 temporary）
            # 规则式永久化（"Your X's Spellcrafts are permanent"）:
            # 生成时已标记 `permanent_spellcraft` **或施放时反查来源随从
            # 仍命中有效规则** → 把本次施放的**目标**设为待翻转实体。
            # 施放时反查覆盖"法术先于饰品生成/入手"的时序（2026-09-02
            # 对抗审查证伪 BG32_MagicItem_920: 绑定前同回合生成的法术
            # 未被标记 → 永久化失效），RULES §7.4.7a。
            self._resolve_cast_permanence(hero, spell, target)
            self.events.fire(self, "spell_resolving", spell=spell,
                             target=target, cast_no=_)
            self.run_script_hook(spell, "on_play", ctx=ctx)
            if getattr(self, "_permanence_pending", None) is not None:
                self._permanence_pending = None
            # 每次施放**效果结算后**的后置广播（per-cast）——"After you
            # cast a spell on a minion, ..." 类被动的精确时点（RULES
            # §7.4.12; `spell_resolving` 是前置时点，只适合"永久化拦截"
            # 与"每次施放计数"）
            self.events.fire(self, "spell_resolved", spell=spell,
                             target=target, cast_no=_)
        # tavern_spell_cast 在法术**效果结算后**广播（官方 29.2.2 bugfix
        # 语义: "after you cast" 触发器看到的是已结算场面——Wave3 反馈
        # 的时序修正; 双施时按施放次数广播）
        if card_def is not None and card_def.is_pool_spell:
            # 全局 "last Tavern spell you cast" 读取点（**引擎维护**，
            # 与监听器无关 → 饰品绑定前同回合施放的法术同样可见;
            # BG36_MagicItem_372 Sphere of Memory / BG35_123 / Nobundo
            # 原先各自维护监听器协议，2026-09-02 主线收口）
            hero._last_tavern_spell_id = spell.card_id
            for _ in range(casts):
                self.events.fire(self, "tavern_spell_cast", spell=spell)
        spell.zone = Zone.REMOVED
        if card_def is not None and card_def.is_pool_spell:
            self.spell_pool.release(spell.card_id)
        # "Whenever you play a card" 类（Dexterity 等）监听源;
        # target 一并广播（Wave2 G2: "cast a spell on a Mech" 类监听依赖）
        self.events.fire(self, "card_played", card=spell, target=target)
        return True

    # ── 升级 (P4) ──

    def _ladder_tier_filter(self, min_tier: int,
                            max_tier: int) -> Optional[set]:
        """存在档集合 ∩ `[min_tier, max_tier]`。

        None = 无阶梯覆写（标准局，不做集合过滤——调用方沿用区间语义）。
        异变 101/102 在 `_tavern_tier_ladder` 声明"只有这些档存在"。
        """
        ladder = self._tavern_tier_ladder
        if ladder is None:
            return None
        return {t for t in ladder if min_tier <= t <= max_tier}

    def _next_existing_tier(self, hero: Hero) -> Optional[int]:
        """升级落点 = 严格高于本人档位的**最小存在档**（无 → None）。

        标准局 = `hero.tavern_tier + 1`（封顶 `max_tavern_tier`）;
        异变 101/102 = 阶梯中的下一档（封顶即阶梯末档，与
        `max_tavern_tier` 无关——"Only Tavern Tiers 1, 3, and 5 exist"
        下 T6/T7 不存在，即使他卡解锁 T7）。
        """
        ladder = self._tavern_tier_ladder
        if ladder is None:
            nxt = hero.tavern_tier + 1
            return nxt if nxt <= self.max_tavern_tier else None
        for t in ladder:
            if t > hero.tavern_tier:
                return t
        return None

    def tavern_spell_candidates(self, min_tier: Optional[int] = None,
                                max_tier: Optional[int] = None,
                                pool_aware: bool = True) -> List[str]:
        """"随机/发现一张酒馆法术"的**统一候选入口**（存在档白名单感知）。

        与 `actions.discover._pool_candidates`（随从侧）对称: 脚本层
        自建 `[d.id for d in db.pool_spells() …]` 候选必须经此收口，
        否则异变 101/102 下非存在档法术仍可被脚本效果触达
        （2026-09-02 对抗审查 must-fix: Book of Medivh `BG30_MagicItem_420`
        在 101 的 T3 曾给出含 T2 的选项）。

        - `min_tier`/`max_tier` = 档位区间; **None = 该侧不设区间**
          （沿用调用点既有口径——不自动取 `hero.tavern_tier`，故
          "全池"调用点标准局行为逐位不变）; "≤ 酒馆等级"调用点显式传
          `max_tier=hero.tavern_tier`，"恰好 Tier N"传 min=max=N。
        - 再经 `_ladder_tier_filter(min_tier, max_tier)` 存在档白名单:
          非存在档法术在当局不存在 → 不得成为任何抽取/发现候选
          （"Only Tavern Tiers 1, 3, and 5 exist."）。标准局
          （`_tavern_tier_ladder is None`）= 不过滤。
        - `pool_aware=True`（缺省）要求 `spell_pool.available > 0`
          （池约束 RULES §2.3/§6.18）; `False` 供只读枚举（效果直施
          路径不占池——Lavish Cape 族）。
        """
        lo = 1 if min_tier is None else min_tier
        ladder_hi = (max_tier if max_tier is not None
                     else max(self.max_tavern_tier, 7))
        tiers = self._ladder_tier_filter(lo, ladder_hi)
        out: List[str] = []
        for d in self.db.pool_spells():
            if min_tier is not None and d.tech_level < min_tier:
                continue
            if max_tier is not None and d.tech_level > max_tier:
                continue
            if tiers is not None and d.tech_level not in tiers:
                continue
            if pool_aware and self.spell_pool.available(d.id) <= 0:
                continue
            out.append(d.id)
        return out

    def _upgrade_cost_after(self, new_tier: int) -> int:
        """升级后挂起的**下一次**升级基价（每回合衰减在回合开始扣减）。

        口径 = **步数索引**（第 k 次升级用标准序列第 k 档基价）:
        `BASE_UPGRADE_COSTS[2 + step]`。标准阶梯 step = `new_tier − 1`
        → 原式 `BASE_UPGRADE_COSTS[new_tier + 1]` 不变（行为等价）;
        阶梯上 step = 落点在阶梯中的下标（101: 1→3 后为 `BASE[3]=7`，
        非"目标档 + 1"的 `BASE[4]=8`）。依据: wiki Tavern Tier
        "Upgrading starts at 5 Coins, and each upgrade costs more than
        the last."——按**升级次数**递进，卡面未改价格。
        """
        ladder = self._tavern_tier_ladder
        if ladder is None:
            step = new_tier - 1
        elif new_tier in ladder:
            step = ladder.index(new_tier)
        else:
            step = new_tier - 1
        return C.BASE_UPGRADE_COSTS.get(2 + step, 11)

    def upgrade_tavern(self, hero: Hero) -> bool:
        if hero.get(GameTag.TURN_SKIPPED, False):
            return False
        if getattr(self, "_upgrade_blocked", False):
            return False
        next_tier = self._next_existing_tier(hero)
        if next_tier is None:
            return False
        # 升级费加值（Millhouse "costs (1) more"）+ 每回合衰减
        cost = max(C.UPGRADE_COST_FLOOR,
                   hero.upgrade_cost + hero.get(GameTag.UPGRADE_COST_MOD, 0))
        if hero.gold < cost:
            return False
        self.spend_gold(hero, cost)
        hero.set(GameTag.TAVERN_TIER, next_tier)
        hero.set(GameTag.UPGRADE_COST, self._upgrade_cost_after(next_tier))
        self.events.fire(self, "tavern_upgraded", hero=hero, tier=next_tier)
        return True

    def upgrade_tavern_free(self, hero: Hero) -> None:
        """免费升级（异变 005 "It upgrades itself every 2 turns"）。"""
        next_tier = self._next_existing_tier(hero)
        if next_tier is None:
            return
        hero.set(GameTag.TAVERN_TIER, next_tier)
        hero.set(GameTag.UPGRADE_COST, self._upgrade_cost_after(next_tier))
        self.events.fire(self, "tavern_upgraded", hero=hero, tier=next_tier)

    def freeze_tavern(self, hero: Hero) -> None:
        """整馆冻结 (P5) — 下一次刷新（自动或手动）保留全部内容。"""
        hero.set(GameTag.FROZEN, True)

    # ── 金币 (P3) ──

    def spend_gold(self, hero: Hero, amount: int) -> None:
        if amount <= 0:
            return
        if hero.gold < amount:
            raise GameStateError(f"{hero.name} cannot spend {amount} (has {hero.gold})")
        hero.gold -= amount
        hero.set(GameTag.GOLD_SPENT_THIS_TURN,
                 hero.get(GameTag.GOLD_SPENT_THIS_TURN, 0) + amount)
        self.events.fire(self, "gold_spent", amount=amount, hero=hero)

    # ── S14: Activate ──

    def use_activate(self, hero: Hero, minion: Minion) -> bool:
        if not minion.has(GameTag.ACTIVATE):
            return False
        if minion.has(GameTag.ACTIVATE_USED_THIS_TURN):
            return False
        if minion.controller is not hero or minion not in hero.board:
            return False
        cost = minion.get(GameTag.ACTIVATE_COST, 1)
        if hero.gold < cost:
            return False
        self.spend_gold(hero, cost)
        minion.set(GameTag.ACTIVATE_USED_THIS_TURN, True)
        self.run_script_hook(minion, "activate")
        self.events.fire(self, "activate_used", minion=minion)
        return True

    # ── 英雄技能 (RULES §9.2) ──

    def hero_power_def(self, hero: Hero):
        """hero 当前英雄技能 CardDef。

        静态绑定 = db Tag380 链; 替换协议（Rat King 轮换/Ragnaros
        Sulfuras/Finley 换技能等）优先读 hero._active_power_id 覆写
        （replace_hero_power 维护）。
        """
        replaced = getattr(hero, "_active_power_id", None)
        if replaced is not None:
            d = self.db.get(replaced)
            if d is not None:
                return d
        d = self.db.get(hero.card_id)
        if d is None or d.hero_power_id is None:
            return None
        return self.db.get(d.hero_power_id)

    def run_on_bind(self, entity, *, ctx=None):
        """执行 `on_bind` 接线（ENGINE_BACKLOG #31/#32）。

        进入**显式接线作用域**（`EventBus.persistent_bind_scope`），身份
        集合 = 本次绑定实体 + 接收英雄（`ctx["hero"]`，缺省回落到
        `entity.controller`）。期间注册的监听器**只有 owner 命中该集合
        （按身份）**才标记为持久接线（`Listener.survives_combat`）→
        即使该实体是在**战斗中**被授予（技能替换 / 饰品 on_bind 施放
        法术 / 任务奖励），其监听器也在战斗快照回滚后保留。

        作用域**不含** on_bind 副作用召唤出的临时实体: 那些实体的
        `on_summon` 监听器仍是战斗作用域并随快照丢弃（ENGINE_BACKLOG
        #32a——旧 `grant_depth` 全局深度计数会把它们一并标记为持久）。
        战斗作用域注册（如 `start_of_combat` 内注册）同样不受影响,
        仍随快照丢弃。
        """
        hero = ctx.get("hero") if isinstance(ctx, dict) else None
        if hero is None:
            hero = getattr(entity, "controller", None)
        with self.events.persistent_bind_scope(entity, hero):
            return self.run_script_hook(entity, "on_bind", ctx=ctx)

    def wire_hero_power_on_bind(self, hero: Hero, power_id: str) -> None:
        """为 hero 接线某英雄技能的 `on_bind`（幂等——同 (hero,技能) 一次）。

        接线时机（RULES §9.5）:
        - 主技能: `start_game` 首轮
        - 第二技能槽（异变/奖励在 on_bind 中声明）: 异变 on_bind 之后补一轮
        - **运行时才确定**的技能（Discover 选择、任务奖励中途获得）:
          由调用方经 `set_second_hero_power` 或本方法显式接线
          （脚本不再需要跨批次 import 私有帮助函数）
        """
        key = (id(hero), power_id)
        if key in self._wired_powers:
            return
        self._wired_powers.add(key)
        from hsrl2.scripts import REGISTRY
        script = REGISTRY.get(power_id)
        if script is not None and hasattr(script, "on_bind"):
            # 接线作用域 = 该英雄（技能监听器普遍 owner=hero——Nether
            # Portal 的 TURN_START / Pocket Cyclone 经 EasterlyWinds
            # 注册的 TAVERN_REFRESH; ENGINE_BACKLOG #31/#32）
            with self.events.persistent_bind_scope(hero):
                script.on_bind(hero, self)

    def set_second_hero_power(self, hero: Hero, power_id: str) -> None:
        """授予第二英雄技能槽并接线其 `on_bind`（RULES §9.5 脚本入口）。

        第二槽已被占用 / 技能不在 CardDB → 抛 GameStateError（fail-loud，
        禁止静默覆盖）。
        """
        if getattr(hero, "_second_power_id", None) is not None:
            raise GameStateError(
                f"second hero power slot already occupied by "
                f"{hero._second_power_id}")
        if self.db.get(power_id) is None:
            raise GameStateError(
                f"set_second_hero_power: unknown power {power_id}")
        hero._second_power_id = power_id
        self.wire_hero_power_on_bind(hero, power_id)

    def hero_power_def_for(self, hero: Hero, power_id: str):
        """按 id 解析技能 CardDef（主技能走 hero_power_def 的替换链，
        第二技能槽直接查 db）。"""
        main = self.hero_power_def(hero)
        if main is not None and main.id == power_id:
            return main
        return self.db.get(power_id)

    def hero_power_ids(self, hero: Hero) -> list:
        """本英雄可用技能 id 列表 = 主技能 + 第二技能槽（RULES §9.3）。

        第二技能槽由异变/奖励脚本在 on_bind 中写
        `hero._second_power_id` 声明；每技能各自的每回合/每局次数独立。
        例外（RULES §9.5 Crystal Ball 族）: 槽位可被"饰品副本"占用
        （`set_second_slot_trinket`）——此时槽位标记是饰品 id，**不**
        计入可用技能（它不是技能，`use_hero_power` 不得扣费误用），
        但其实体在 `hero.trinkets` 中照常生效。
        """
        ids = []
        main = self.hero_power_def(hero)
        if main is not None:
            ids.append(main.id)
        second = getattr(hero, "_second_power_id", None)
        if second is not None and second not in ids:
            d = self.db.get(second)
            if d is not None and d.card_type == CardType.HERO_POWER:
                ids.append(second)
        return ids

    def refund_hero_power_use(self, hero: Hero, power_id: str) -> None:
        """回滚一次已记账的英雄技能使用（挂起期结算落空时由脚本调用）。

        计数发生在**结算点** `_finish_hero_power`（定向/选择类技能的目标
        或选项在挂起期才结算；非定向技能发起即结算）。若最终效果落空
        （选项被并发授予 / 授予失败），脚本应回滚计数——否则
        `uses_per_game=1` 的技能会变成"可用性 True 但 use 恒 False"的
        **死技能**（2026-09-02 对抗审查 MINOR: Mystery Cube Power 实测）。
        引擎已自动作废的结算（金币不足 / 目标离场 / 超出每回合或每局
        配额——2026-09-13 对抗验证 MAJOR 复查点）**不计数**，无需回滚。
        只回滚**计数**（每回合/每局 + 全局累计 tag）; 费用退还由脚本
        自行决定（引擎对挂起期金币不足的情形本就不扣费不计数）。
        """
        hero._power_uses_this_turn[power_id] = max(
            0, hero._power_uses_this_turn.get(power_id, 0) - 1)
        if power_id in hero._power_uses_this_game:
            hero._power_uses_this_game[power_id] = max(
                0, hero._power_uses_this_game[power_id] - 1)
        hero.set(GameTag.HERO_POWER_USED_THIS_TURN, max(
            0, hero.get(GameTag.HERO_POWER_USED_THIS_TURN, 0) - 1))
        hero.set(GameTag.HERO_POWER_USES_THIS_GAME, max(
            0, hero.get(GameTag.HERO_POWER_USES_THIS_GAME, 0) - 1))

    def replace_hero_power(self, hero: Hero, new_power_id: str) -> None:
        """替换英雄技能（Rat King 每回合轮换 / Sulfuras / Finley）。

        官方语义: 新技能从替换时刻起生效（本回合即可用，除非新技能
        自身限制; uses_per_turn 计数随技能身份切换重置——Rat King 每
        回合换新技能 = 每回合都可用一次）。
        """
        if self.db.get(new_power_id) is None:
            raise GameStateError(
                f"replace_hero_power: unknown power {new_power_id}")
        hero._active_power_id = new_power_id
        hero.clear(GameTag.HERO_POWER_USED_THIS_TURN)
        hero._power_uses_this_turn.pop(new_power_id, None)

    def hero_power_cost(self, hero: Hero, power_def, script) -> int:
        """技能费（动态覆写点——Elise 递增/Nobundo/Togwaggle/Patches
        "next costs (1) less"）。脚本声明 ``cost_override(hero, game)
        -> int``; 未声明读 power CardDef.cost; 结果下限 0。"""
        override_fn = getattr(script, "cost_override", None)
        if override_fn is not None:
            return max(0, override_fn(hero, self))
        return power_def.cost

    def use_hero_power(self, hero: Hero, target=None,
                       power_id: Optional[str] = None) -> bool:
        if hero.get(GameTag.TURN_SKIPPED, False):
            return False
        """使用英雄技能 (RULES §9.2)。

        - 费用: power CardDef.cost，脚本可声明 ``cost_override(hero,
          game) -> int`` 动态覆写（Elise 递增类）
        - 次数: 默认每回合 1 次; ``uses_per_turn = N``; 回合开始清零;
          每局次数（"Once per game" 类）经 ``uses_per_game = N`` +
          hero 级计数 tag 声明式支持
        - 可用性: ``available(hero, game) -> bool``（门槛/冷却/解锁）
        - 目标: ``needs_target`` + ``target_candidates``（单目标）;
          双目标（Vol'jin "Choose 2"）: ``target_count = 2`` 声明 →
          依次两个 PendingChoice，全部选定后结算
        - 替换: replace_hero_power 维护的 _active_power_id 优先
        - 第二技能槽 (RULES §9.3): hero_power_ids(hero) = 主技能 +
          `hero._second_power_id`; power_id 参数选择使用哪一个（默认
          主技能），两者次数/费用/可用性各自独立
        """
        ids = self.hero_power_ids(hero)
        if power_id is None:
            if not ids:
                return False
            power_id = ids[0]
        if power_id not in ids:
            return False
        power_def = self.hero_power_def_for(hero, power_id)
        if power_def is None:
            return False
        from hsrl2.scripts import REGISTRY  # 延迟导入避免循环依赖
        script = REGISTRY.get(power_def.id)
        if script is None:
            return False   # 技能未迁移——不可用（诚实缺省，不静默近似）
        if getattr(script, "passive", False):
            return False
        # 可用性协议: 脚本声明 available(hero, game)——门槛/冷却/
        # Unlocks/上对手无随从等; 默认恒可用
        avail_fn = getattr(script, "available", None)
        if avail_fn is not None and not avail_fn(hero, self):
            return False
        # 额外使用次数（RULES §6.20——Sous Chef Sticker "+1 use each turn"）
        max_uses = getattr(script, "uses_per_turn", 1) \
            + hero.extra_trigger("hp_uses")
        # 每技能独立计数（RULES §9.3——第二技能槽不与主技能抢次数）
        used = hero._power_uses_this_turn.get(power_id, 0)
        if used >= max_uses:
            return False
        # 每局次数（"Once/Twice per game"）
        per_game = getattr(script, "uses_per_game", None)
        if per_game is not None:
            used_game = hero._power_uses_this_game.get(power_id, 0)
            if used_game >= per_game:
                return False
        cost = self.hero_power_cost(hero, power_def, script)
        if cost and hero.gold < cost:
            return False

        n_targets = getattr(script, "target_count", 1) \
            if getattr(script, "needs_target", False) else 0
        if n_targets <= 0 or target is not None:
            return self._finish_hero_power(hero, power_def, script, target)

        cand_fn = getattr(script, "target_candidates", None)
        candidates = (list(cand_fn(hero, self))
                      if cand_fn is not None
                      else [m for m in hero.board if not m.dead])
        if len(candidates) < n_targets:
            return False   # 候选不足不可用（金币未扣）

        def _chain(picked, remaining):
            """依次收集 n_targets 个目标（每个选定后重估候选——
            第一个目标死亡/离场时自动从后续候选剔除）。"""
            if remaining <= 0:
                self._finish_hero_power(
                    hero, power_def, script,
                    picked[0] if n_targets == 1 else picked)
                return
            fresh = [c for c in candidates if c not in picked]
            if len(fresh) < remaining:
                # 候选枯竭（前序选择致离场）: 已选目标照常结算，
                # 缺位目标为 None（脚本自决落空）
                picks = picked + [None] * remaining
                self._finish_hero_power(
                    hero, power_def, script,
                    picks[0] if n_targets == 1 else picks)
                return
            self.pending_choices.append(PendingChoice(
                hero, fresh, "hero_power_target",
                resolve_callback=lambda pick, p=picked, r=remaining:
                    _chain(p + [pick], r - 1)))

        _chain([], n_targets)
        return True

    def _finish_hero_power(self, hero: Hero, power_def, script,
                           target=None) -> bool:
        cost = self.hero_power_cost(hero, power_def, script)
        # 定向技能目标选择挂起期间金币可能被花光（自动化建模时序——
        # 官方 UI 中选择即时完成无挂起窗口）。resolve 时复查，不足则
        # 该次使用作废（不扣费、不计数、无效果）——官方不允许负金币。
        if cost and hero.gold < cost:
            return False
        # 定向技能目标在选择挂起期间可能离场（自动化时序；官方 UI 中
        # 即时完成无挂起窗口）。目标 Minion 必须仍存活且仍在某个可见
        # 区域（任意英雄棋盘 / 手牌 / 酒馆）——失效则本次使用作废
        # （不扣费、不计数、无效果），与金币复查同构。
        # 2026-09-01 全对局压测: Cookie "Stir the Pot" 因目标在
        # gold_spent 监听器中离场而崩溃; 注意目标域不限友方棋盘
        # （Xyrella/Baz'hial 指向酒馆、Maiev 指向手牌）。
        if getattr(script, "needs_target", False) \
                and not self._hero_power_target_ok(hero, script, target):
            return False
        # 次数/每局配额复查（2026-09-13 对抗验证 MAJOR）: 定向技能的
        # 目标选择**挂起期间**可以再次发起 `use_hero_power`——计数发生在
        # 结算点（本方法），故 N 个挂起结算会全部通过 → `uses_per_turn=2`
        # 被叠加成 N 次（实测 5 次全部 True，Malygos TB_BaconShop_HP_052
        # 同）。与金币/目标复查同构: 结算时复查，超额则该次使用作废
        # （不扣费、不计数、无效果）。
        max_uses = getattr(script, "uses_per_turn", 1) \
            + hero.extra_trigger("hp_uses")
        if hero._power_uses_this_turn.get(power_def.id, 0) >= max_uses:
            return False
        per_game = getattr(script, "uses_per_game", None)
        if per_game is not None \
                and hero._power_uses_this_game.get(power_def.id, 0) >= per_game:
            return False
        if cost:
            self.spend_gold(hero, cost)
        hero.set(GameTag.HERO_POWER_USED_THIS_TURN,
                 hero.get(GameTag.HERO_POWER_USED_THIS_TURN, 0) + 1)
        # 每技能独立计数（RULES §9.3）+ 全局累计 tag（"after you use your
        # Hero Power" 类效果读 tag，不受技能身份影响）
        hero._power_uses_this_turn[power_def.id] = \
            hero._power_uses_this_turn.get(power_def.id, 0) + 1
        # 每局次数记账（uses_per_game 声明的技能）
        if getattr(script, "uses_per_game", None) is not None:
            hero.set(GameTag.HERO_POWER_USES_THIS_GAME,
                     hero.get(GameTag.HERO_POWER_USES_THIS_GAME, 0) + 1)
            hero._power_uses_this_game[power_def.id] = \
                hero._power_uses_this_game.get(power_def.id, 0) + 1
        # 扣费会广播 gold_spent——监听器可能在此时移走目标
        # （2026-09-01 压测: See the Light / Imprison / Graveyard Shift
        # 的馆内目标被扣费监听器移除后脚本抛 GameStateError）。
        # 此时费用与计次已发生（官方 UI 不会允许选失效目标），按
        # "效果落空"处理，不再调用脚本。
        # "Your Hero Power **triggers twice**"（Ancient Wishbone
        # `BG30_MagicItem_804`）: 一次使用结算 N+1 次（与 `hp_uses`
        # "每回合多使用几次" 是两个独立口径——RULES §6.20）
        times = 1 + (hero.extra_trigger("hp_times") if hero is not None else 0)
        for _ in range(times):
            if hasattr(script, "hero_power"):
                if getattr(script, "needs_target", False) \
                        and not self._hero_power_target_ok(hero, script,
                                                          target):
                    break
                result = script.hero_power(hero, self, {"target": target})
                self.run_actions(result)
        self.events.fire(self, "hero_power_used", hero=hero,
                         power_id=power_def.id)
        return True

    def _hero_power_target_ok(self, hero: Hero, script, target) -> bool:
        """定向技能目标当前是否仍在**脚本自身候选域**内。

        以 `script.target_candidates(hero, game)` 重新求值（默认 = 友方
        存活棋盘随从）——比"任意可见区域"精确: Xyrella/Maiev/Baz'hial
        要求目标仍在**酒馆**（被买走转入手牌即失效），Cookie 要求仍在
        **棋盘**（被移除即失效）。
        """
        if target is None:
            return True   # 落空目标由脚本自决（候选枯竭路径）
        cand_fn = getattr(script, "target_candidates", None)
        if cand_fn is not None:
            fresh = list(cand_fn(hero, self))
        else:
            fresh = [m for m in hero.board if not m.dead]
        targets = target if isinstance(target, (list, tuple)) else [target]
        return all(_t is None or _t in fresh for _t in targets)

    # ══════════════════ S14: Dark Gifts ══════════════════

    def use_dark_gift(self, hero: Hero) -> bool:
        if hero.get(GameTag.TURN_SKIPPED, False):
            return False
        """S14 Dark Gift 使用（官方 36.2 dev post）。

        - 第 3 回合起可用、每次 3 金、每回合 1 次、每局 3 次
          （constants: DARK_GIFT_*）
        - 条件不满足返回 False（玩家操作合法性，不抛异常）
        - 合法但候选耗尽 → 消耗金币与次数后无提供（官方池耗尽行为），
          返回 True 且不产生 PendingChoice
        """
        state = self.dark_gift_state.setdefault(
            hero, {"uses_left": C.DARK_GIFT_USES_PER_GAME,
                   "used_this_turn": False})
        if self.turn < C.DARK_GIFT_START_TURN:
            return False
        if state["uses_left"] <= 0 or state["used_this_turn"]:
            return False
        if hero.gold < C.DARK_GIFT_COST:
            return False
        self.spend_gold(hero, C.DARK_GIFT_COST)
        state["uses_left"] -= 1
        state["used_this_turn"] = True

        candidates = DG.eligible_minions(self.db, self.minion_pool,
                                         hero, self.turn)
        if not candidates:
            return True     # 池耗尽: 无提供（官方效果落空行为）
        trio = self._draw_gift_trio(hero, candidates)
        options = self._pair_gifts(hero, trio, candidates)
        # 预留（2026-09-01 压测修复）: 提供项生成即 acquire，resolve 时
        # 保留选中、释放其余。旧实现 resolve 才 acquire——同一回合另一
        # Dark Gift/商店取走该副本时 GameStateError 崩溃。
        options = [(cid, gid) for (cid, gid) in options
                   if self.minion_pool.acquire(cid)]
        if not options:
            return True     # 极端池状态无法配对——同上落空

        def resolve(pick: Tuple[str, str]) -> None:
            card_id, gift_id = pick
            if pick not in options:
                raise GameStateError(
                    f"dark gift pick {pick} 不在提供选项中 {options}")
            for cid, _gid in options:
                if cid != card_id:
                    self.minion_pool.release(cid, 1)
            m = self.create_minion(card_id, controller=hero)
            self.apply_dark_gift(m, gift_id)
            self.pending_hand_add(hero, m)
            self.events.fire(self, "dark_gift_given", minion=m,
                             gift_id=gift_id)

        self.pending_choices.append(PendingChoice(
            hero, options, "dark_gift", resolve_callback=resolve))
        return True

    def _draw_gift_trio(self, hero: Hero, candidates: List[str]) -> List[str]:
        """抽 3 个不同随从。

        - 提供权重官方未公布（2026-08-23 查证 dev post 无数值）——
          按候选 card_id 均匀抽样（UNVERIFIED 缺省）。
        - Turn>=6 保证式构造（dev post 原文 "guaranteed"——P2 重构
          2026-08-23: 直接替换一个非匹配 slot，等价且与措辞对齐）。
        """
        k = min(3, len(candidates))
        trio = self.rng.sample(candidates, k, label="dark_gift_minions")
        if self.turn < 6 or not hero.board:
            return trio
        common = DG.most_common_board_race(hero, self.rng)
        if common is None:
            return trio
        if any(self.db.get(cid).race in (common, Race.ALL)
               for cid in trio):
            return trio
        matching = [cid for cid in candidates
                    if self.db.get(cid).race in (common, Race.ALL)
                    and cid not in trio]
        if not matching:
            return trio     # 池内已无该种族候选 → 跳过保证
        # 保证式: 将一个非匹配 slot 替换为最常见种族候选
        for idx in range(len(trio)):
            if self.db.get(trio[idx]).race not in (common, Race.ALL):
                trio[idx] = self.rng.choice(matching,
                                            label="dark_gift_race_fill")
                break
        return trio

    def _pair_gifts(self, hero: Hero, trio: List[str],
                    candidates: List[str],
                    turn: Optional[int] = None) -> List[Tuple[str, str]]:
        """trio 每个随从配一个互不相同且合法的 gift。

        某随从无合法 gift → 从候选换随从重抽 ≤20 次（AMBIGUOUS: 官方
        未公布该行为，以重抽近似）; 仍失败则该位落空（提供少于 3 个）。
        `turn`: gift 窗口判定回合（默认 `game.turn`）——开局/特殊授予路径
        在 T6 前也要求合法 gift（`_pair_gift_options` 同口径）。
        """
        eff_turn = self.turn if turn is None else turn
        min_tier = min(self.db.get(cid).tech_level for cid in trio)
        used: set = set()
        options: List[Tuple[str, str]] = []
        for i in range(len(trio)):
            cid = trio[i]
            gift = self._pair_one_gift(hero, cid, min_tier, used,
                                       turn=eff_turn)
            tried = {cid}
            while gift is None and len(tried) <= 20:
                alts = [c for c in candidates
                        if c not in trio and c not in tried]
                if not alts:
                    break
                alt = self.rng.choice(alts, label="dark_gift_minion_redraw")
                tried.add(alt)
                gift = self._pair_one_gift(hero, alt, min_tier, used,
                                           turn=eff_turn)
                if gift is not None:
                    trio[i] = alt
            if gift is not None:
                used.add(gift)
                options.append((trio[i], gift))
        return options

    def _pair_one_gift(self, hero: Hero, cid: str, min_tier: int,
                       used: set, turn: Optional[int] = None) -> Optional[str]:
        d = self.db.get(cid)
        opts = DG.eligible_gifts(
            self.db, d, turn=self.turn if turn is None else turn, hero=hero,
            lobby_dragons_ok=self._lobby_dragons_ok(),
            minion_pool=self.minion_pool, offering_min_tier=min_tier)
        opts = [(g, w) for g, w in opts if g not in used]
        if not opts:
            return None
        # AMBIGUOUS: 官方未公布 gift 配对权重——加权抽样（稀有 ×0.5）
        return DG.weighted_choice(self.rng, opts)

    def _lobby_dragons_ok(self) -> bool:
        ar = self.minion_pool.active_races
        return ar is None or Race.DRAGON in ar

    def apply_dark_gift(self, minion: Minion, gift_id: str) -> None:
        """S14 Dark Gift 效果分派（公共 API——英雄技能等可复用）。

        DEFERRED_GIFTS 成员: 记审计日志、效果不生效——唯一允许的
        "未实现"形态（见 darkgifts.DEFERRED_GIFTS 与作业报告）。
        """
        d = self.db.get(gift_id)
        if d is None or gift_id not in DG.GIFT_WINDOWS:
            raise GameStateError(f"unknown dark gift {gift_id}")
        minion.set(GameTag.DARK_GIFT, gift_id)   # 审计: 记录获得的 gift
        if gift_id in DG.DEFERRED_GIFTS:
            self.dark_gift_audit_log.append(
                (gift_id, minion.uuid, self.turn, "DEFERRED"))
            return
        handler = _DARK_GIFT_EFFECTS.get(gift_id)
        if handler is None:
            raise GameStateError(f"unhandled dark gift {gift_id}")
        handler(self, minion, d.name)
        self.dark_gift_audit_log.append(
            (gift_id, minion.uuid, self.turn, "APPLIED"))

    # ══════════════════ S14: 招募期攻击 (Fishbait) ══════════════════

    def recruit_phase_attack(self, attacker: Minion,
                             tavern_target: Entity) -> None:
        """招募期攻击（S14 Lionfish/Snarky Shark: 棋盘随从攻击酒馆区随从）。

        官方卡面: "Your left-most Beast attacks it."（BG36_206/201）。
        语义:
          - 双向同时伤害，source 互指（KILLER 由 take_damage 设置，
            Fishbait 亡语 "Give the minion that killed this +5/+5" 据此）
          - 酒馆目标死亡: fire "death" → 亡语 → 从酒馆移除、不回池
            （该场景目标恒为 Fishbait token; AMBIGUOUS: 若为池卡是否
            回池未公布，按不回池实现）
          - 攻击者死亡: check_deaths → _process_single_death 正常路径
            （招募期死亡回池，池守恒）
          - 与战斗攻击同构: before_attack / Rally（伤害前）/ after_attack
            照常; 顺劈与 Venomous 不参与（酒馆区无相邻语义，AMBIGUOUS）
        """
        hero = attacker.controller
        if hero is None or attacker not in hero.board:
            raise GameStateError(
                "recruit_phase_attack: attacker not on a board")
        if tavern_target not in hero.tavern:
            raise GameStateError(
                "recruit_phase_attack: target not in attacker's tavern")
        self.events.fire(self, "before_attack", attacker=attacker,
                         defender=tavern_target)
        self.run_rally(attacker, {"target": tavern_target})
        atk_power = attacker.atk
        def_power = (tavern_target.atk
                     if isinstance(tavern_target, Minion)
                     and not tavern_target.dead else 0)
        if atk_power > 0 and isinstance(tavern_target, Minion):
            dealt = tavern_target.take_damage(atk_power, source=attacker)
            if dealt:
                self.events.fire(self, "damage", minion=tavern_target,
                                 amount=dealt, source=attacker)
        if def_power > 0:
            taken = attacker.take_damage(def_power, source=tavern_target)
            if taken:
                self.events.fire(self, "damage", minion=attacker,
                                 amount=taken, source=tavern_target)
        if (isinstance(tavern_target, Minion) and tavern_target.dead
                and tavern_target in hero.tavern):
            self.events.fire(self, "death", minion=tavern_target)
            self.run_script_hook(tavern_target, "deathrattle")
            hero.tavern.remove(tavern_target)
            tavern_target.zone = Zone.REMOVED
            self.events.unregister_owner(tavern_target)
        self.check_deaths()
        self.events.fire(self, "after_attack", attacker=attacker,
                         defender=tavern_target)

    # ══════════════════ S14: Lockbox ══════════════════

    def open_lockbox_early(self, hero: Hero, turns: int = 1) -> bool:
        """提前开启 Lockbox（Lockbox Portrait BG36_MagicItem_301:
        "it opens {0} turns sooner"——脚本层调用本 API）。
        找到手牌中的 Lockbox 减 turns 回合，归零即开启。"""
        if turns is None:
            turns = 1            # 数据缺口（脚本未给出数值）→ 至少提前 1
        for card in hero.hand:
            if card.get(GameTag.LOCKBOX_TURNS_LEFT, 0) > 0:
                left = card.get(GameTag.LOCKBOX_TURNS_LEFT) - turns
                if left <= 0:
                    self._open_lockbox(hero, card)
                else:
                    card.set(GameTag.LOCKBOX_TURNS_LEFT, left)
                return True
        return False

    def _open_lockbox(self, hero: Hero, lockbox: Entity) -> None:
        """开启 Lockbox: 随机有种族金色随从入手。

        BG36_520t: "break this open and get a random Golden minion with a
        type!"。金色 = 池基础卡扣减 min(3, 剩余) 份后按金色卡定义创建。
        AMBIGUOUS: 池不足 3 份时是否仍给——按仍给实现（作业单约定）;
        候选优先取池内仍有副本者，全部耗尽时退回全量有种族定义（仍给）。
        """
        typed = [d for d in self.db.pool_minions() if DG.has_race(d)]
        avail = [d.id for d in typed
                 if self.minion_pool.available(d.id) > 0]
        cands = avail if avail else [d.id for d in typed]
        if not cands:
            return
        base_id = self.rng.choice(cands, label="lockbox_golden")
        got = min(3, self.minion_pool.available(base_id))
        for _ in range(got):
            if not self.minion_pool.acquire(base_id):
                raise GameStateError(
                    f"lockbox acquire failed for {base_id}")
        golden = self.create_minion(base_id, controller=hero, golden=True)
        if got < 3:
            # 池不足 3 份仍给（作业单 AMBIGUOUS 约定）→ 非完整三连金:
            # 回池按 1 份（RULES §2.3 Reno 口径——否则"扣 1 退 3"泄漏）
            golden.set(GameTag.GILDED_NOT_TRIPLED, True)
        self.pending_hand_add(hero, golden)

        if lockbox in hero.hand:
            hero.hand.remove(lockbox)
        lockbox.zone = Zone.REMOVED

    # ══════════════════ 死亡处理 (C6) ══════════════════

    combat_summon_log: List[Minion]

    def check_deaths(self) -> None:
        from hsrl2.queue import CombatLoopError  # 顶部 import 会循环依赖，延迟于此
        wave = 0
        while True:
            dead: List[Minion] = []
            for h in self.heroes:
                for m in h.board:
                    if m.dead and m.zone == Zone.PLAY \
                            and m.uuid not in self._death_processing:
                        dead.append(m)
            if not dead:
                return
            wave += 1
            if wave > C.DEATH_MAX_WAVES:
                raise CombatLoopError(
                    f"death waves exceeded {C.DEATH_MAX_WAVES}")
            for m in dead:
                self._process_single_death(m)
            # 战斗内"你的最后一个随从死亡后"（本 wave 的亡语/复生已结算）
            if self.in_combat:
                self._fire_last_minion_died()

    def _process_single_death(self, m: Minion) -> None:
        """死亡处理入口: 重入保护（同一实体只处理一次）。

        DEATH 事件在**离场之前**广播（官方顺序），因此 DEATH 监听器内
        触发 effects 再嵌套 `check_deaths()` 时，本实体仍是
        `dead + zone==PLAY` → 会被二次收集并重复结算亡语/死亡计数。
        处理中标记在嵌套收集与 `check_deaths` 两处同时生效。
        """
        if m.uuid in self._death_processing:
            return
        self._death_processing.add(m.uuid)
        try:
            self._process_death_inner(m)
        finally:
            self._death_processing.discard(m.uuid)

    def _process_death_inner(self, m: Minion) -> None:
        """单随从死亡处理——官方顺序 (RULES §6.9 + Hearthstone 通用):

        1. death 事件
        2. **离场**: 从棋盘移除、让出板位（亡语召唤物填入此位;
           满 7/7 场亡语召唤依然成立）、graveyard、监听器注销
           （复生路径暂缓注销——见步骤 4）
        3. 亡语触发（含磁力栈叠; source 已 GRAVEYARD，效果锚点
           source.controller; 亡语召唤位置 = ctx["position"] 或
           source 的 ZONE_POSITION 残值 = 刚让出的板位）
        4. 复生: 原位 1 血回归（保留 buff/金色/关键词，仅移除复生;
           Persisting Horror Dark Gift: 满状态复活，一次性）
        5. Avenge 计数（任何友方死亡，含复生死亡）

        离场先于亡语同时修复:
          - 重入双亡语（亡语内嵌套 check_deaths 不会再收集——zone 已
            非 PLAY）
          - 亡语召唤占位（死者的 ZONE_POSITION 残值 = 释放板位:
            移除只重排其右侧随从，死者自身 tag 未被动过）
        """
        hero = m.controller
        # 1. death 事件
        self.events.fire(self, "death", minion=m)
        # F-07: 战斗内友方 Aberration 死亡 → Deity 进度/死亡记录
        # （须在离场前取死亡瞬间的攻/最大生命——Y'Shaarj 亡语复生用）
        self._note_aberration_death(m)
        # 2. 离场（复生路径保留实体，稍后原位回归）
        will_reborn = m.reborn
        freed_pos = m.get(GameTag.ZONE_POSITION, 0)
        board_before_hook = list(hero.board) if hero else []
        if hero and m in hero.board:
            hero.board.remove(m)
            self._update_positions(hero)
            if self.in_combat:
                # 死亡快照**在离场瞬间**记录（此时属性未被亡语/复生影响
                # ——"died with its maximum stats" 与 "exact copy" 都要这
                # 一份），随后广播腾位事件（消费者可在事件内直接读快照）。
                # 2026-09-02: 顺序 = 快照 → 腾位广播（早于亡语/复生，避免
                # 复生/亡语补位把空位填掉导致事件漏发）
                self._record_combat_dead_snap(m, hero)
                if len(hero.board) < C.BOARD_SIZE:
                    self.events.fire(self, "combat_slot_freed", hero=hero)
        if will_reborn:
            m.zone = Zone.SETASIDE      # 处理期间不占 PLAY（防嵌套收集）
        else:
            m.zone = Zone.GRAVEYARD
            if hero:
                hero.graveyard.append(m)
            self.events.unregister_owner(m)
        # 3. 亡语（含磁力栈叠亡语——run_script_hook 的效果合并）
        #    官方: Deathrattles are resolved before Reborn
        #    (hearthstone.wiki.gg/wiki/Reborn#Notes)
        #    Titus Rivendare: 亡语翻倍光环（棋盘存在即生效——亡语者
        #    自身死亡时 Titus 仍在场则翻倍，官方语义）
        self.trigger_deathrattle(m, hero=hero, position=freed_pos)
        # 战斗死亡日志（Kangor's Apprentice "first 2 Mechs that died this
        # combat" 类——按死亡顺序记录，战斗开始时清空）
        if self.in_combat:
            self.combat_death_log.append(m)
        # 每英雄按 card_id 的累计死亡簿记（Eternal Knight "for each
        # friendly Eternal Knight that died this game"——跨战斗持久）
        if hero is not None:
            if not hasattr(hero, "deaths_by_card_id"):
                hero.deaths_by_card_id = {}
            hero.deaths_by_card_id[m.card_id] = \
                hero.deaths_by_card_id.get(m.card_id, 0) + 1
        # 招募期死亡回池——置于亡语**之后**（否则死亡副本先回流池，
        # 会被自身亡语的"随机获取 X"重新抽到——Sly Raptor 自抽缺陷）
        if not will_reborn and not self.in_combat:
            self.minion_pool.release_minion_entity(m)
        # 4. 复生: 原位 1 血回归（Persisting Horror: 满状态，一次性）。
        #    插位规则: 从 freed_pos 起跳过亡语期间新入场的召唤物——
        #    官方可观测行为: 亡语召唤物占据死者板位，复活体排在其后
        #    (Deathrattles resolved before Reborn)
        if will_reborn:
            m.clear(GameTag.REBORN)
            m.clear(GameTag.DEAD)
            if m.uuid in self._reborn_full_uuids:
                self._reborn_full_uuids.discard(m.uuid)
                m.set(GameTag.HEALTH, m.max_health)
            else:
                m.set(GameTag.HEALTH, 1)
            m.zone = Zone.PLAY
            if hero is not None:
                new_uuids = {x.uuid for x in hero.board
                             if x not in board_before_hook}
                pos = freed_pos
                while (pos < len(hero.board)
                       and hero.board[pos].uuid in new_uuids):
                    pos += 1
                hero.board.insert(pos, m)
                self._update_positions(hero)
            # F-14: Reborn 是**卡面基础关键词的新副本**（官方 Power.log
            # a07dc...：BGS_034 复生实体 FULL_ENTITY 带 DIVINE_SHIELD=1，
            # 随后 REBORN=0）。死亡瞬间被消耗掉的关键词（圣盾等）必须在
            # 复生体上恢复；否则复生后无 DS 会被立即再次击杀，改变结果。
            card_def = self.db.get(m.card_id)
            if card_def is not None:
                for keyword in getattr(card_def, "keywords", ()) or ():
                    if keyword == "reborn":
                        continue          # 复生关键词本身已消耗
                    tag = _KEYWORD_TAG_MAP.get(keyword)
                    if tag is not None and not m.has(tag):
                        m.set(tag, True)
            self.events.fire(self, "reborn", minion=m)
        # 5. Avenge: 任何友方死亡都计数（含复生死亡）— RULES §6.11
        #    2026-09-01 扩展: 计数源 = 棋盘随从 **+ 饰品 + 任务奖励**
        #    （trinket/reward 实体无 AVENGE tag，脚本以类属性
        #    `avenge_threshold` 声明阈值）。此前只扫 hero.board →
        #    饰品/奖励上的 Avenge 卡注册即 no-op。
        #    **仅战斗内计数**（2026-09-01 对抗审计）: Avenge 是战斗关键词，
        #    招募期死亡（自伤/吞噬/健康购买等）不得累计或触发——
        #    旧实现无战斗守卫，招募期死亡可在战斗外触发 Avenge。
        if hero and (self.in_combat or self._active_combat is not None):
            avengers = list(hero.board) + list(getattr(hero, "trinkets", [])) \
                + list(getattr(hero, "quest_rewards", []))
            for other in avengers:
                if other is m:
                    continue
                threshold = other.get(GameTag.AVENGE_TARGET, 0)
                if not threshold:
                    script = getattr(other, "scripts", None)
                    threshold = getattr(script, "avenge_threshold", 0) or 0
                if not threshold:
                    continue
                n = other.get(GameTag.AVENGE_COUNTER, 0) + 1
                other.set(GameTag.AVENGE_COUNTER, n)
                if n >= threshold:
                    other.set(GameTag.AVENGE_COUNTER, 0)
                    self.run_script_hook(other, "avenge")
        # F-07: Deity awaken 尝试放在死亡结算尾部（亡语/复生/Avenge
        # 之后），已记录的 Aberration 死亡进度达到阈值时召唤 Deity。
        if hero is not None:
            self._maybe_awaken_deity(hero)

    # ══════════════════ 战斗编排 ══════════════════

    def end_recruit_phase(self) -> None:
        """招募阶段收尾 → 战斗编排 → 淘汰 → 下一回合 (RULES §1.2 回合结构)。

        顺序（RULES §1.2/§3.5/§4.8/§5/§6.13）:
          1. 存活英雄的回合结束效果: 饰品 → 任务奖励 → 棋盘随从左→右，
             每个 hook 后 check_deaths（EoT 效果可致死，如自残恶魔）
          2. 丢弃手牌中未使用的 Spellcraft 法术（回合结束消失, RULES §6.13）
          3. 快照存活英雄 board → last_combat_board（幽灵/记忆来源, RULES §4.8）
          4. 取用招募期开始时预生成的配对（_take_pairing; RULES §4.8a），
             逐对 run_combat 并 fire "combat_end"
          5. 奇数 leftover → run_ghost_combat（幽灵战, RULES §4.8）
          6. _process_eliminations（淘汰回池, RULES §2.3）
          7. 存活 ≤1 → finished；否则 turn+1 并对每个存活英雄开始新招募回合
        """
        alive = [h for h in self.heroes if h.is_alive]
        for h in alive:
            h.clear(GameTag.TURN_SKIPPED)   # 跳回合只锁一个招募期
        # turn_end 广播（Ragnaros/Sulfuras/C'Thun 类 EoT 被动——
        # hero_passives 批上报缺口; 于 EoT 效果之前、与 TURN_START 对称）
        self.events.fire(self, "turn_end", turn=self.turn)
        # 1. EoT: 每个 hook 后结死（自残类 EoT 可当场死亡）
        for hero in alive:
            # Drakkari Enchanter: EoT 翻倍光环（棋盘存在即生效; 金色
            # Drakkari = ×3——官方金色文本 "trigger three times"）。
            # 文本 "Your end of turn effects trigger twice" 覆盖**全部**
            # 己方 EoT 效果——随从、饰品、任务奖励都算（2026-09-02 对抗
            # 审查 E1: 旧实现只翻倍棋盘随从 → Charging Staff/Gilded
            # Anchor/Aggem Sticker/Exquisite Dishware/Enigmatic Headstone
            # 全部少触发一次）
            # 额外触发配额（RULES §6.20——"Your end of turn effects
            # trigger an extra time"，Ghastly Sticker）与 Drakkari 叠加
            eot_times = 1 + hero.extra_trigger("eot_extra")
            for x in hero.board:
                if x.has(GameTag.END_OF_TURN_DOUBLER):
                    eot_times += 2 if x.is_golden else 1
            for _ in range(eot_times):
                for trinket in list(hero.trinkets):
                    self.run_script_hook(trinket, "end_of_turn")
                    self.check_deaths()
                for reward in list(getattr(hero, "quest_rewards", [])):
                    self.run_script_hook(reward, "end_of_turn")
                    self.check_deaths()
            for m in list(hero.board):
                for _ in range(eot_times):
                    self.run_script_hook(m, "end_of_turn")
                    self.check_deaths()
        # 2. Spellcraft 法术回合结束丢弃 (RULES §6.13)
        #    例外 (Sunken Persistence Dark Gift): 该随从生成的 Spellcraft
        #    永久——脚本层契约: 生成时在法术实体上设 spellcraft_source_uuid
        #    **只丢弃法术实体**: `create_minion` 也会给带 `spellcraft_id`
        #    的**随从**打 SPELLCRAFT tag（用于每回合生成法术），旧实现按
        #    tag 判定 → 手牌里的法术塑造随从被当成法术在回合结束销毁
        #    （2026-09-02 对抗审查实测: BG27_514 Sea Witch Zar'jira 入手后
        #     `end_recruit_phase` 直接 REMOVED）。
        for hero in alive:
            for card in list(hero.hand):
                if (isinstance(card, Spell)
                        and card.has(GameTag.SPELLCRAFT)
                        and card.zone == Zone.HAND
                        and getattr(card, "spellcraft_source_uuid", None)
                        not in self._permanent_spellcraft_uuids):
                    hero.hand.remove(card)
                    card.zone = Zone.REMOVED
        # 3. 战前棋盘快照（幽灵阵容与战斗记忆的数据来源）
        for hero in alive:
            hero.last_combat_board = list(hero.board)
        # 4. 配对 + 顺序战斗。damage cap 按本阶段**开始时**的存活人数
        #    （官方: 同一回合战斗同时结算，先死者不影响同回合上限判定, RULES §5.2）
        #    配对在招募阶段开始时已预生成（_precompute_pairing）——本处
        #    取用同一份，保证 Scabbs/Holmes 在读到的"下一对手"就是真正
        #    开打的对手; 存活集变化/测试直驱时兜底重算。
        phase_alive = len(alive)
        pairs, leftover = self._take_pairing(alive)
        for p1, p2 in pairs:
            self._last_opponent_board[p1] = list(p2.last_combat_board or [])
            self._last_opponent_board[p2] = list(p1.last_combat_board or [])
        for h in alive:
            h.fought_ghost_last = False
        for p1, p2 in pairs:
            result = self.run_combat(p1, p2, alive_count=phase_alive)
            self.combat_memory.setdefault(p1, []).append(p2)
            self.combat_memory.setdefault(p2, []).append(p1)
            self.events.fire(self, "combat_end", hero_a=p1, hero_b=p2,
                             result=result)
        # 5. 奇数人 → 幽灵战
        if leftover is not None:
            self.run_ghost_combat(leftover, alive_count=phase_alive)
            leftover.fought_ghost_last = True
        # 6. 淘汰结算
        self._process_eliminations()
        # 7. 终局判定 / 下一回合
        alive = [h for h in self.heroes if h.is_alive]
        if len(alive) <= 1:
            self.finished = True
            return
        self.turn += 1
        # 新招募期开始即确定本回合对手 (RULES §4.8a)
        self._precompute_pairing()
        for hero in alive:
            self._begin_recruit_for(hero)

    def _precompute_pairing(self) -> None:
        """招募阶段开始时确定本回合战斗配对 (RULES §4.8a)。

        规则依据: 官方在招募阶段开始即确定本回合对手（酒馆内即显示
        下一对手）——Scabbs "I Spy: Discover a plain copy of a minion
        from your **next** opponent's warband" 与 Murloc Holmes
        "Guess which one your **next** opponent had last combat" 都在
        招募阶段读取下一对手; Tess "Bob's Burgles ... your **last**
        opponent's warband" 读上一对手。三张卡的数据文本要求"下一对手"
        与"上一对手"是两个不同引用，故配对必须提前于招募期确定并缓存。

        输入（alive 集合 / _opponent_history / fought_ghost_last）在
        整个招募期内不变（英雄只在战斗阶段掉血、淘汰在战斗后结算），
        因此招募期开始时配对与招募期结束时配对各义等价，唯一差别是
        rng 流位置——预生成把配对抽取提前到招募期开始。
        """
        alive = [h for h in self.heroes if h.is_alive]
        pairs, leftover = matchmaking.pair_players(
            alive, self.rng, self._opponent_history)
        # RULES §4.8: 不会连续两次面对克尔苏加德（除非只剩 2 名玩家）——
        # 上阶段刚打幽灵者若再次轮为 leftover，与一对中的玩家交换名额
        if (leftover is not None and len(alive) > 2
                and getattr(leftover, "fought_ghost_last", False)
                and pairs):
            swap = pairs[0][0]
            pairs[0] = (leftover, pairs[0][1])
            leftover = swap
        self._pending_pairs = pairs
        self._pending_leftover = leftover
        self._next_opponent = {}
        for p1, p2 in pairs:
            self._next_opponent[p1] = p2
            self._next_opponent[p2] = p1

    def _take_pairing(self, alive):
        """取本回合配对（预生成优先; 存活集变化则重算兜底）。"""
        cached = self._pending_pairs
        participants = ({h for pair in cached for h in pair}
                        if cached is not None else set())
        if self._pending_leftover is not None:
            participants.add(self._pending_leftover)
        if cached is None or participants != set(alive):
            self._precompute_pairing()
        pairs = self._pending_pairs or []
        leftover = self._pending_leftover
        self._pending_pairs = None
        self._pending_leftover = None
        return list(pairs), leftover

    def _has_deathrattle_hook(self, m) -> bool:
        """实体是否会真的触发亡语（含磁力栈叠的同钩子）。"""
        script = getattr(m, "scripts", None)
        if script is not None \
                and getattr(script, "deathrattle", None) is not None:
            return True
        from hsrl2.scripts import REGISTRY
        for aid in self._magnetic_stack.get(m.uuid, []):
            cls = REGISTRY.get(aid)
            if cls is not None and getattr(cls, "deathrattle",
                                           None) is not None:
                return True
        return False

    def granted_battlecry(self, m) -> bool:
        """**条件化战吼**是否当前生效（RULES §7.4.17）。

        Portrait 类饰品可在**持有期间**给家族载荷追加战吼: 载荷脚本以类属性
        `battlecry_flag` 声明开关名（= 家族行为开关通道 §7.4.16 的 flag），
        饰品 on_bind 用 `add_family_flag` 写入。生效期与 flag 同口径
        （`source` 离场/饰品被替换 → 战吼同步消失）。

        权威: 32.4 补丁说明（2025-06-02, playhearthstone.com blog 24205006）
        "Snicker Snacks: Fixed a bug where it couldn't trigger Selfless Hero's
        effect when **it has a Battlecry from Selfless Portrait**" —— 印证持
        `BG32_MagicItem_804` 时 Selfless Hero **具有战吼**，且该战吼可被
        "trigger a Battlecry" 类效果（Snicker Snacks）正常触发; 反向也意味着
        **无饰品时它没有战吼**。
        """
        script = getattr(m, "scripts", None)
        flag = getattr(script, "battlecry_flag", None)
        if not flag:
            return False
        hero = getattr(m, "controller", None)
        if hero is None:
            return False
        return self.family_flag(hero, m.card_id, flag)

    def has_battlecry(self, m) -> bool:
        """实体是否**会真的触发战吼**（统一门禁，RULES §7.4.17）。

        通道: `BATTLECRY` tag（关键词通道）/ 脚本 `battlecry` 钩子
        （金卡定义不带关键词的数据缺口）/ 实体级 `_script_overrides`
        （`set_script_override("battlecry", …)`，视为无条件）/ 磁力栈叠的
        同钩子（带 `battlecry_flag` 的附件按**附件卡 id** 查同一 hero 的
        开关）。声明了 `battlecry_flag` 的**条件化钩子**仅在
        `granted_battlecry` 生效时计入——否则"无饰品时"的自私英雄会误吃
        War Drum `bc_first` 配额、误计入"战吼随从"计数、误入"最左战吼"
        目标集（2026-09-13 实测）。

        例外（有意不覆盖）: **酒馆/数据驱动**的关键词过滤（`CardDef.keywords`、
        `_free_buy_qualifiers_match` 的任意 tag 限定、Chillmere Mosaic 的
        刷新筛选）按卡面/实体关键词判定——尚未拥有的酒馆报价不吃 Portrait
        授予，且当前 Portrait 家族均为非池卡（不可出现在酒馆）。
        """
        if m.has(GameTag.BATTLECRY):
            return True
        script = getattr(m, "scripts", None)
        if script is not None and getattr(script, "battlecry", None) is not None:
            if not getattr(script, "battlecry_flag", None) \
                    or self.granted_battlecry(m):
                return True
        # 实体级脚本 override（`set_script_override("battlecry", fn)`）也是
        # 真战吼来源——2026-09-13 对抗验证 MINOR: `TriggerBattlecry` 的新
        # 门禁若不认 override，会把"仅由 override 提供战吼"的随从静默
        # 挡掉（当前唯一生产者 batch_unfreeze 的基底脚本已自带 battlecry，
        # 故只是潜在缺口）。override 视为**无条件**钩子（非 Portrait 授予）。
        overrides = getattr(m, "_script_overrides", None) or {}
        if overrides.get("battlecry") is not None:
            return True
        from hsrl2.scripts import REGISTRY
        hero = getattr(m, "controller", None)
        for aid in self._magnetic_stack.get(m.uuid, []):
            cls = REGISTRY.get(aid)
            if cls is None or getattr(cls, "battlecry", None) is None:
                continue
            flag = getattr(cls, "battlecry_flag", None)
            if not flag:
                return True
            # 磁力附件自带条件化战吼: 按**附件自身卡 id** 查同一 hero 的
            # 开关（附件不是独立实体，没有自己的 controller）——2026-09-13
            # 对抗验证 MINOR 补齐（此前带 flag 的附件被一律忽略）。
            if hero is not None and aid:
                try:
                    if self.family_flag(hero, aid, flag):
                        return True
                except GameStateError:
                    continue
        return False

    def _has_battlecry_hook(self, m) -> bool:
        """`has_battlecry` 的兼容别名（历史名; 语义见 `has_battlecry`）。

        `bc_first`（"Your first Battlecry each turn..."）**只有真正带战吼的
        随从**才消费配额——旧版任意随从打出都吃配额，玩家先打一张白板再打
        战吼就拿不到额外触发（2026-09-02 对抗审查证伪 BG32_MagicItem_416;
        与 `dr_first`/`_has_deathrattle_hook`、`soc_first`/`_has_soc_hook`
        同构）。
        """
        return self.has_battlecry(m)

    def trigger_deathrattle(self, target, *, hero=None, position: int = 0,
                            count: bool = True) -> int:
        """触发一个亡语——**统一入口**（真实死亡与"Trigger a Deathrattle"
        效果共用，RULES §6.20）。

        "Trigger a Deathrattle"（Floating Candle Set `BG36_MagicItem_208t`
        / Deathstrider / JaWS / Secret Schematic 等）与真实亡语**等价**:
        必须应用 Titus `DEATHRATTLE_DOUBLER` 倍率、`dr_extra` 永久额外
        触发、`dr_first` 每场战斗配额，并计入 `COUNTER_DEATHRATTLES` +
        广播 `deathrattle_trigger`。旧实现各脚本直接
        `run_script_hook(m, "deathrattle")` → 绕开全部配额（2026-09-02
        对抗审查证伪: Plaguerunner 亡语增量在 Titus 在场与不在场同为
        +4）。

        - `hero`: 归属英雄（默认取 `target.controller`——死亡路径由
          调用方传入，因为此时实体可能已离场）
        - `position`: 亡语上下文里的死亡板位（召唤物填位用）
        - `count=False`: 不计数/不广播（仅用于确实不该计的重复结算）
        返回实际触发次数。
        """
        if hero is None:
            hero = getattr(target, "controller", None)
        # dr_extra 永久全部亡语 +N（Turbulent Tombs）
        dr_times = 1 + (hero.extra_trigger("dr_extra")
                        if hero is not None else 0)
        if getattr(self, "_extra_bc_dr", False):
            dr_times += 1
        # "Your first Deathrattle each combat triggers an extra time"
        # （RULES §6.20; 配额每场战斗重置——仅战斗内消费）。**只有真正带
        # 亡语钩子的实体**才消费配额（2026-09-02 对抗审查 D1: 旧版任意
        # 战斗中死亡都吃配额 → 首个亡语拿不到额外触发; 与 soc_first 的
        # `_has_soc_hook` 同构）
        if hero is not None and self.in_combat \
                and self._has_deathrattle_hook(target) \
                and hero.consume_extra_trigger("dr_first"):
            dr_times += 1
        for x in (hero.board if hero is not None else []):
            if x is target or not x.has(GameTag.DEATHRATTLE_DOUBLER):
                continue
            dr_times += 2 if x.is_golden else 1
        for _ in range(dr_times):
            self.run_script_hook(target, "deathrattle",
                                 ctx={"position": position})
        # 计数/广播的资格 = **真的会触发亡语**（CardDef DEATHRATTLE tag 或
        # 脚本 `deathrattle` 钩子 / 磁力栈同钩子）。只有钩子的实体
        # （Fish of N'Zoth `TB_BaconShop_HP_105t` / 金色 `TB_BaconUps_307`）
        # 此前效果已结算却不计数，令 BG35_342 Falling Sky Golem / Dark Gift
        # "Death's Embrace" 少计（2026-09-13 对抗验证实测）。
        if count and hero is not None and (
                target.has(GameTag.DEATHRATTLE)
                or self._has_deathrattle_hook(target)):
            # 计数 + 广播（宿主 + 每个带亡语的磁力附件各计一次）
            n_attached_dr = sum(
                1 for aid in self._magnetic_stack.get(target.uuid, [])
                if "deathrattle" in (self.db.get(aid).keywords
                                     if self.db.get(aid) else frozenset()))
            total = 1 + n_attached_dr
            hero.set(GameTag.COUNTER_DEATHRATTLES,
                     hero.get(GameTag.COUNTER_DEATHRATTLES, 0) + total)
            for _ in range(total):
                self.events.fire(self, "deathrattle_trigger", minion=target)
        return dr_times

    def _has_rally_hook(self, m) -> bool:
        """实体是否会真的触发 Rally（含磁力栈叠的同钩子）。"""
        script = getattr(m, "scripts", None)
        if script is not None and getattr(script, "rally", None) is not None:
            return True
        from hsrl2.scripts import REGISTRY
        for aid in self._magnetic_stack.get(m.uuid, []):
            cls = REGISTRY.get(aid)
            if cls is not None and getattr(cls, "rally", None) is not None:
                return True
        return False

    def trigger_friendly_rallies(self, hero: Hero,
                                 ctx: Optional[dict] = None) -> int:
        """触发该英雄棋盘上**全部**己方 Rally 效果（`rally_extra` 配额与
        脚本钩子同 `run_rally`）。

        文本族: "At the end of your turn, trigger all friendly **Rallies**"
        （Insurrectionist's Blade `BG36_MagicItem_214`）。返回触发次数。
        """
        n = 0
        for m in list(hero.board):
            if getattr(m, "dead", False):
                continue
            if not self._has_rally_hook(m):
                continue
            self.run_rally(m, dict(ctx or {}))
            n += 1
        return n

    def run_rally(self, attacker, ctx: dict) -> None:
        """Rally 触发（攻击宣告时、伤害前；RULES §6.16/§6.20）。

        额外触发配额: `rally_extra` = 全部己方 Rally 效果额外触发 N 次
        （Rallying Cry "Your Rallies trigger an extra time"）。
        """
        hero = getattr(attacker, "controller", None)
        times = 1 + (hero.extra_trigger("rally_extra") if hero is not None
                     else 0)
        for _ in range(times):
            self.run_actions(attacker.call_script("rally", ctx=ctx))

    def run_ghost_combat(self, hero: Hero, alive_count: int | None = None):
        """奇数存活者的幽灵战 (RULES §4.8 Kel'Thuzad / Ghost)。

        - ghost 来源: self.ghost_records[-1]（最近被淘汰者的冻结快照）。
          无记录 → 本回合跳过战斗（早期无人淘汰时奇数人的官方行为）
        - 幽灵阵容为淘汰时的冻结副本，不成长不变化 (RULES §4.8)
        - hero 败: 伤害 = ghost.tavern_tier + Σ 幽灵存活随从 tech_level
          (RULES §5.1)，过 damage_cap(turn, 真实存活人数) (RULES §5.2)
        - hero 胜/平: hero 不受伤；幽灵为临时实体，战后整体丢弃
          （对其造成的伤害不可见）
        - 幽灵临时 append 进 self.heroes（CombatScheduler/check_deaths 遍历
          self.heroes，缺席则幽灵随从死亡处理失效），finally 中移除；
          任何提前 return 都走 finally
        - ghost.health 置 0: 使 _alive_count 不把幽灵计入存活人数 —
          damage_cap 按真实玩家数计算 (RULES §5.2 "存活玩家数 ≤ 4 解除")
        - hero 的对手历史/战斗记忆记 None 对手
        - AMBIGUOUS: 幽灵棋盘 SoC 是否照常重触发待实测验证（wiki 无明确
          记载），当前按正常战斗语义处理
        """
        if not self.ghost_records:
            return None
        record = self.ghost_records[-1]
        ghost = Hero("TB_BaconShop_HERO_KelThuzad", record["name"],
                     base_health=C.HERO_BASE_HEALTH, armor=0)
        ghost.game = self
        ghost.set(GameTag.TAVERN_TIER, record["tavern_tier"])
        ghost.health = 0   # 非真实玩家: 不计入 damage_cap 的存活人数
        board = list(record["board"])
        for m in board:
            m.controller = ghost
            m.zone = Zone.PLAY
        ghost.board = board
        self.heroes.append(ghost)
        try:
            result = self.run_combat(hero, ghost, alive_count=alive_count)
            self._opponent_history.setdefault(hero, []).append(None)
            self._opponent_history[hero] = self._opponent_history[hero][-2:]
            self.combat_memory.setdefault(hero, []).append(None)
            # 幽灵同样是"上一对手"（Tess/R806 的对手引用语义: 幽灵战
            # 没有 Hero 实体，故直接记其战前战团快照）
            self._last_opponent_board[hero] = list(record["board"])
            # 幽灵战同样广播 combat_end（Overconfidence "next combat" 类
            # 触发器含幽灵战——Wave4 反馈缺口）
            self.events.fire(self, "combat_end", hero_a=hero, hero_b=ghost,
                             result=result)
            return result
        finally:
            if ghost in self.heroes:
                self.heroes.remove(ghost)
            for m in ghost.board:
                m.controller = None

    # ── 对手引用 API（RULES §4.8a）──

    def next_opponent(self, hero: Hero) -> Optional[Hero]:
        """本回合战斗对手（招募期开始时已配对确定; 幽灵/未配对 → None）。"""
        return self._next_opponent.get(hero)

    def next_opponent_warband(self, hero: Hero):
        """Scabbs "next opponent's warband"——下一对手**当前**战团。

        招募期读取（配对已在招募期开始确定, RULES §4.8a）; 无对手
        （幽灵战/未配对，如首回合前的淘汰）→ None。
        """
        opp = self._next_opponent.get(hero)
        return list(opp.board) if opp is not None else None

    def last_opponent(self, hero: Hero) -> Optional[Hero]:
        """上一场战斗对手（幽灵战 → None，读战团用 last_opponent_warband）。"""
        mem = self.combat_memory.get(hero) or []
        return mem[-1] if mem else None

    def last_opponent_warband(self, hero: Hero):
        """Tess "last opponent's warband" / R806——上一场对手的战前战团
        快照（含幽灵战的幽灵阵容; 无战斗记录 → None）。"""
        snap = self._last_opponent_board.get(hero)
        return list(snap) if snap else None

    def _process_eliminations(self) -> None:
        """战斗全部结束后结算淘汰 (RULES §2.3 / REFACTOR_PLAN P8)。

        health ≤ 0 的英雄（is_alive 语义: health>0，不改 hero.py）:
          1. 棋盘随从逐个回池（金色 3 份, RULES §2.3）
          2. 手牌: Minion 同上回池; Spell 仅限池内法术（db.is_pool_spell）
          3. 酒馆展示区 tavern 同样回池
          4. 生成 ghost_record（棋盘冻结快照 + tavern_tier + name）append 到
             self.ghost_records (RULES §4.8)
          5. fire "hero_eliminated" 事件
        淘汰者从 self.heroes 移除（否则后续回合 check_deaths 仍会扫描其
        棋盘、且本函数重复调用会重复回池）；health 保持 0。
        """
        eliminated = [h for h in self.heroes if h.health <= 0]
        for hero in eliminated:
            for m in list(hero.board):
                self.minion_pool.release_minion_entity(m)
                m.zone = Zone.REMOVED
            for card in list(hero.hand):
                if isinstance(card, Minion):
                    self.minion_pool.release_minion_entity(card)
                elif isinstance(card, Spell):
                    d = self.db.get(card.card_id)
                    if d is not None and d.is_pool_spell:
                        self.spell_pool.release(card.card_id)
                card.zone = Zone.REMOVED
            for e in list(hero.tavern):
                if isinstance(e, Minion):
                    self.minion_pool.release_minion_entity(e)
                else:
                    d = self.db.get(e.card_id)
                    if d is not None and d.is_pool_spell:
                        self.spell_pool.release(e.card_id)
                e.zone = Zone.REMOVED
            self.ghost_records.append({
                "name": hero.name,
                "board": [_frozen_clone(m) for m in hero.board],
                "tavern_tier": hero.tavern_tier,
            })
            self.events.fire(self, "hero_eliminated", hero=hero)
            self.heroes.remove(hero)
            # 区域清空 + 监听器注销——否则已淘汰英雄的 `turn_end` /
            # `turn_start` 监听器在后续回合仍会触发，读到 zone=REMOVED 的
            # 陈旧实体（2026-09-13 压测 seed 5066 实测: 淘汰者的
            # BG24_Reward_309 "两端随从吞噬酒馆随从" 对已 REMOVED 的酒馆
            # 随从调用 ConsumeMinion → GameStateError 中断整局）。
            # 淘汰者不再行动（RULES §2.3）。
            owners = (list(hero.board) + list(hero.hand) + list(hero.tavern)
                      + list(getattr(hero, "trinkets", None) or [])
                      + list(getattr(hero, "quest_rewards", None) or []))
            for lst in (hero.board, hero.hand, hero.tavern):
                lst.clear()
            for owner in owners:
                self.events.unregister_owner(owner)
            self.events.unregister_owner(hero)

    def run_combat(self, hero_a: Hero, hero_b: Hero,
                   alive_count: int | None = None):
        """执行一场战斗。战斗状态在快照后修改，战后恢复 (Tarecgosa 类
        保留机制通过 persist 标记处理)。

        alive_count: 本战斗阶段开始时的存活人数（damage cap 判定用，
        RULES §5.2 同回合战斗同时结算）；None = 实时统计。
        """
        self.in_combat = True
        self.combat_summon_log = []
        self.combat_death_log = []   # 按死亡顺序（Kangor 类消费）
        self._combat_transforms = []  # 战斗内变身记录（战后重放）
        # F-07: Deity 每场战斗重置（进度 / 本场 Aberration 死亡记录）
        self._reset_deity_combat()
        self._last_minion_fired = set()   # "最后一个随从死亡"每场一次
        for _h in (hero_a, hero_b):
            _h._combat_dead_snaps = []      # 本场死亡快照（按顺序）
        snapshots = {}
        board_before = {}
        for hero in (hero_a, hero_b):
            board_before[hero] = list(hero.board)
            for m in hero.board:
                snapshots[m] = m.snapshot_state()
        # 监听器表快照: 战斗中死亡的随从会触发 unregister_owner，但战后
        # 棋盘整体复原（随从复活）——监听器必须随之复原，否则持久触发器
        # （Tichondrius 等）在随从首次战死后静默失效。
        # 已触发的 once 监听器在**恢复时**按 _fired 标记过滤（快照时点
        # 尚未触发）——防复活重复触发。
        events_snapshot = {ev: list(lst)
                           for ev, lst in self.events._listeners.items()}
        # 磁力栈快照: 战斗内吸附（Assembler Portrait `BG36_MagicItem_841`
        # 等）产生的附件必须随战斗结束消失——旧实现不入快照 → 每场战斗
        # 重复追加、亡语/钩子栈无界累积（2026-09-02 对抗审查上报缺口）。
        mag_snapshot = {k: list(v)
                        for k, v in self._magnetic_stack.items()}
        # finally 块在**战斗异常**时也必须能恢复棋盘——这些容器必须在
        # try 之前初始化，否则异常路径下 finally 抛 UnboundLocalError
        # 掩盖原始错误（2026-09-01 全对局压测发现）
        poet_persist: dict = {}
        persist_totals: dict = {}
        dmg_deltas: dict = {}
        try:
            scheduler = CombatScheduler(self, hero_a, hero_b)
            result = scheduler.run()
            # 上局战斗结果记录（Tortollan Blue Shell "If you lost your
            # last combat" 类条件的数据源）
            hero_a._last_combat_result = (
                "win" if result.winner is hero_a
                else "loss" if result.loser is hero_a else "draw")
            hero_b._last_combat_result = (
                "win" if result.winner is hero_b
                else "loss" if result.loser is hero_b else "draw")
            damage = self._compute_damage(result)
            if damage and result.loser is not None:
                n_alive = alive_count if alive_count is not None \
                    else self._alive_count()
                if self._damage_cap_uncapped:
                    cap = None                     # 官方 _ENABLED=0：无上限
                elif self._damage_cap_override is not None:
                    cap = int(self._damage_cap_override)
                else:
                    cap = C.damage_cap(self.turn, n_alive)
                actual = min(damage, cap) if cap is not None else damage
                result.damage_dealt = damage
                result.capped_damage = actual

            # ══ 官方伤害时序（2026-08-22 修正，压测 Soul Rewinder
            # 不死疑点裁决）: 战败伤害施加在**战后棋盘**上——战斗中
            # 死亡的随从仍在墓地、其监听器已在死亡处理时注销
            # （Soul Rewinder 战死→不回溯; Tichondrius 战死→不触发）。
            # 复活/快照恢复发生在伤害**之后**（下回合开始时全队复原），
            # 因此伤害窗口内触发器写入的增益必须以"增量重放"跨过
            # 恢复（否则被快照回滚——SA6 期旧缺陷）。══

            # 1. PERSIST/Poet 捕获——基于**伤害前**战后状态（战斗期增益;
            #    伤害窗口增益走通用 delta 路径，防双计）
            poet_persist: dict = {}
            for hero in (hero_a, hero_b):
                poets = [m for m in board_before[hero]
                         if m.has(GameTag.ADJACENT_PERSIST_SOURCE)]
                if not poets:
                    continue
                # 倍率: 金色 Poet "double stats"（BG29_813_G XML 文本）
                # → 2×; 基础 Poet 1×
                mult = 2 if any(p.is_golden for p in poets) else 1
                poet_pos = {board_before[hero].index(p) for p in poets}
                for idx, m in enumerate(board_before[hero]):
                    if m not in snapshots:
                        continue
                    if not any(abs(idx - p) == 1 for p in poet_pos):
                        continue
                    if not m.has_race(Race.DRAGON):
                        continue
                    poet_persist[m] = (
                        m.atk, m.max_health,
                        {t: m.has(t) for t in self._persist_keyword_tags(m)},
                        mult,
                    )
            persist_totals = {
                m: (m.atk, m.max_health,
                    {t: m.has(t) for t in self._persist_keyword_tags(m)})
                for hero in (hero_a, hero_b)
                for m in board_before[hero]
                if m in snapshots and m.has(PERSIST_TAG)
            }
            # 2. 伤害窗口标记（buff 身份 + 关键词态）
            dmg_markers = {
                m: ({id(b) for b in m._buffs},
                    {t: m.has(t) for t in self._persist_keyword_tags(m)})
                for hero in (hero_a, hero_b) for m in board_before[hero]
            }
            # 3. 施加伤害（战后棋盘; 战死者监听器缺席）
            if result.capped_damage and result.loser is not None:
                result.loser.take_damage(result.capped_damage)
            # 4. 捕获伤害窗口增量（幸存触发器写入的 buff/关键词）
            dmg_deltas = {}
            for hero in (hero_a, hero_b):
                for m in board_before[hero]:
                    marker_ids, marker_kws = dmg_markers[m]
                    new_buffs = [b for b in m._buffs
                                 if id(b) not in marker_ids]
                    new_kws = [t for t, present in marker_kws.items()
                               if not present and m.has(t)]
                    if new_buffs or new_kws:
                        dmg_deltas[m] = (new_buffs, new_kws)
            self._last_combat_results[(hero_a, hero_b)] = result
        finally:
            # 战斗状态恢复 (RULES §3.5): 战斗中获得的变化不延续到招募阶段。
            # 例外 1: PERSIST_COMBAT_CHANGES 随从保留战斗期增益（总量已
            #   在伤害前捕获——persist_totals）
            # 例外 2: Persistent Poet 相邻龙保留战斗增益（poet_persist，
            #   战前相邻为准，AMBIGUOUS: 战内移位不追踪）
            # 例外 3: 伤害窗口增量（dmg_deltas——战败伤害触发器写入的
            #   增益，官方随复活保留）在恢复后重放
            # 例外 4: `Buff(persist=True)` **按来源**跨战斗持久化
            #   （Bewitched Ribbon `BG35_MagicItem_923` / Cyclist Portrait
            #   `BG36_MagicItem_362` 的 "permanently"）。先取快照（此时
            #   战斗尚未回滚），恢复后用 `add_buff` 重放——只重放该批
            #   附魔，同一实体的其它战内变化照常回滚（与例外 1 的单实体
            #   全量通道正交; §A11）。
            # ── "获得属性"抑制（ENGINE_BACKLOG §E D2）──
            # 本 finally 块的全部属性写入都是**复原**：`restore_state`
            # 后的 persist 通道重放、Poet 相邻龙重放、伤害窗口增量重放
            # （后者直接 `_buffs.append`，本就不经 `add_buff`——§E2 #6）。
            # 它们把战斗中已经"获得过一次"的属性重新装回实体，**不是**
            # 新一轮"获得"——否则"每当……获得攻击力"类监听会在每场战斗
            # 结束后被引擎自己的恢复机制再触发一次。故整块置
            # `_restore_no_gain`（`Entity.add_buff` 据此不广播
            # `stats_gained`；`buff_applied` 不受影响）。try/finally 保证
            # 异常路径下标记必然清空（否则该局此后永久静默）。
            self._restore_no_gain = True
            try:
                persist_buffs: dict = {}
                for hero in (hero_a, hero_b):
                    for m in board_before[hero]:
                        if m not in snapshots:
                            continue
                        kept = [b for b in m._buffs if getattr(b, "persist",
                                                               False)]
                        if kept:
                            persist_buffs[m] = kept
                for hero in (hero_a, hero_b):
                    for m in board_before[hero]:
                        if m not in snapshots:
                            continue
                        if m in persist_totals:
                            # 战斗属性保留（倍率: PERSIST_DOUBLE → 2×——
                            # Tarecgosa gift/golden Poet "double stats";
                            # 池卡 Tarecgosa 1×）。恢复后按"捕获总增益 × 倍率"
                            # 重放为永久 Buff（等效保留原增益，翻倍时放大）
                            mult = 2 if m.has(GameTag.PERSIST_DOUBLE) else 1
                            post_atk_total, post_health_total, post_keywords = \
                                persist_totals[m]
                            m.restore_state(snapshots[m])
                            # 例外 4 已拥有该实体的 `persist` 附魔 → 本通道的
                            # 增量必须扣除其份量，否则经 `m.atk` 差额**双计**
                            # （同一实体同时带 PERSIST_COMBAT_CHANGES 且吃
                            # Bewitched Ribbon 时的 2026-09-18 实测缺陷;
                            # 回归见 test_batch_trinkets31
                            # ::test_persist_channel_and_entity_persist_no_double_count）
                            _p_atk = sum(b.atk for b in persist_buffs.get(m, ()))
                            _p_health = sum(b.health
                                            for b in persist_buffs.get(m, ()))
                            g_atk = post_atk_total - m.atk - _p_atk
                            g_health = (post_health_total - m.max_health
                                        - _p_health)
                            if g_atk > 0 or g_health > 0:
                                m.add_buff(Buff(atk=max(0, g_atk) * mult,
                                                health=max(0, g_health) * mult))
                            for tag, present in post_keywords.items():
                                if present:
                                    m.set(tag, True)
                                else:
                                    m.clear(tag)
                            # 战斗伤害不延续: HEALTH 重算为 max_health
                            m.set(GameTag.HEALTH, m.max_health)
                        else:
                            m.restore_state(snapshots[m])
                        # 例外 4: 按来源持久化的附魔在恢复后重放（`add_buff`
                        # 同步抬升当前血——恢复态满血，故不会超上限）。
                        # **去重**: 快照里已含的 persist 附魔（战斗前就已获得
                        # 的那份）恢复时已回来, 不得再次 add_buff——否则每场
                        # 战斗都会重复叠加一次（对抗验证实测 4/5 → 5/6 → 6/7…）。
                        # 必须按**对象身份**判定: 值相等会漏掉"第二场战斗
                        # 新建的同值附魔"。
                        _snap_buffs = snapshots[m].get("buffs", ())
                        for b in persist_buffs.get(m, ()):
                            if any(b is x for x in _snap_buffs):
                                continue
                            m.add_buff(b)
                        m.set(GameTag.DEAD, False)
                        m.clear(GameTag.EXHAUSTED)
                        m.clear(GameTag.WINDFURY_ATTACKS)
                        m.clear(GameTag.VENOMOUS_CONSUMED)
                    # 战斗召唤物（不在 board_before 中的）从 board 移除
                    hero.board = list(board_before[hero])
                # Persistent Poet 相邻龙回放（post 总增益已在恢复前捕获;
                # 倍率含金色 Poet double stats）
                for m, (p_atk, p_health, p_kws, mult) in poet_persist.items():
                    g_atk = p_atk - m.atk
                    g_health = p_health - m.max_health
                    if g_atk > 0 or g_health > 0:
                        m.add_buff(Buff(atk=max(0, g_atk) * mult,
                                        health=max(0, g_health) * mult))
                    for tag, present in p_kws.items():
                        if present:
                            m.set(tag, True)
                    m.set(GameTag.HEALTH, m.max_health)
                # 伤害窗口增量重放（战败伤害触发器的增益——Tichondrius/
                # Soul Rewinder 幸存体的 buff 官方随复活保留）
                for m, (new_buffs, new_kws) in dmg_deltas.items():
                    for b in new_buffs:
                        # `persist` 附魔走例外 4 通道（此处重放会双计）
                        if getattr(b, "persist", False):
                            continue
                        if b not in m._buffs:
                            m._buffs.append(b)
                            if b.health > 0:
                                m.set(GameTag.HEALTH, m.health + b.health)
                    for t in new_kws:
                        m.set(t, True)
                # 战斗内授予的亡语 override 恢复（_script_overrides 不在
                # Minion 快照内 → 必须显式还原; 2026-09-02 主线收口）
                for hero in (hero_a, hero_b):
                    self._restore_combat_deathrattles(hero)
                # 磁力栈恢复（战斗内吸附不延续到招募阶段; RULES §3.5/§6.14）
                self._magnetic_stack = {k: list(v)
                                        for k, v in mag_snapshot.items()}
                # 监听器表复原（与棋盘快照同步——战斗内的注册/注销不延续;
                # 战斗中已触发的 once 监听器不复活。战死随从的监听器随
                # 复活回归——供**未来**回合使用，本战斗伤害已结算完毕）
                # 战斗中注册的**持久接线**监听器（`on_bind` 作用域内注册、
                # 且 owner 为绑定实体或接收英雄——如战斗内授予的饰品/任务
                # 奖励/替换的英雄技能）必须在战后保留（ENGINE_BACKLOG
                # #30/#31/#32）。`survives_combat` 在注册时按**身份**标记
                # （见 `EventBus.persistent_bind_scope`）: on_bind 副作用
                # 召唤出的临时实体（owner=该随从）与其它战斗作用域注册
                # （含战前已存在实体在 start_of_combat 等时点注册者）仍随
                # 快照丢弃。
                _kept = [(ev, l)
                         for ev, lst in self.events._listeners.items()
                         for l in lst
                         if not any(l is p
                                    for p in events_snapshot.get(ev, ()))
                         and l.survives_combat]
                self.events._listeners = {
                    ev: [l for l in lst if not (l.once and l._fired)]
                    for ev, lst in events_snapshot.items()
                }
                for ev, l in _kept:
                    self.events._listeners.setdefault(ev, []).append(l)
                    if self.events._live_ids is not None:
                        self.events._live_ids.add(id(l))
                # 战斗内 Transform 重放（RULES §3.5 例外）: 把复原后的旧实体
                # 原位换回战斗内变身出的新实体，并重跑 `on_transform` 重接线
                # （监听器表刚被快照覆盖，新实体的被动必须重新注册）
                for old_uuid, new in list(self._combat_transforms):
                    for hero in (hero_a, hero_b):
                        idx = next((i for i, m in enumerate(hero.board)
                                    if m.uuid == old_uuid), None)
                        if idx is None:
                            continue
                        old = hero.board[idx]
                        if new is old:
                            continue
                        new.zone = Zone.PLAY
                        new.clear(GameTag.DEAD)
                        new.set(GameTag.HEALTH, new.max_health)
                        new.clear(GameTag.EXHAUSTED)
                        hero.board[idx] = new
                        # 旧实体已离场: 显式置 `REMOVED`。
                        # 必要性（ENGINE_BACKLOG #40）: 上一行监听器表复原
                        # （`events_snapshot`）会把旧实体在战斗内
                        # Transform 时已注销的监听器**复活**；且
                        # `restore_state` 已把旧实体 zone 复原为 `PLAY`
                        # （它仍在 `board_before` 中）——若只换出棋盘不移出
                        # 区域，旧实体成为"离场但 zone=PLAY"的静默第三态，
                        # 监听器永久残留。`zone=REMOVED` 经 `Entity.zone`
                        # setter 自动注销其全部监听器（自愈式收口）。
                        old.zone = Zone.REMOVED
                        self._update_positions(hero)
                        self.run_script_hook(new, "on_transform",
                                            ctx={"old": old})
                        break
                self._combat_transforms = []
                # 监听器表复原后的**离场收口**（ENGINE_BACKLOG #40）:
                # 上面 `events_snapshot` 是**全局**监听器表的快照复原
                # （只看"是否战斗前已存在"，不区分 owner 是否仍在场）——
                # 战斗期间永久离场的随从（如战斗内 `on_death` → 入手 →
                # 三连合并把死者并入金色置 `zone=REMOVED`；或战斗内
                # Transform 被换出的旧实体）的监听器会被一并复活。
                # `Entity.zone` setter 已在离场瞬间注销过一次，这里是
                # 快照复原**之后**的第二道收口: 棋盘复原完成后仍处
                # `REMOVED`/`GRAVEYARD` 的随从即永久离场者 → 丢弃其被
                # 复活的监听器。手牌/酒馆/场上的随从不受影响
                # （`LOCKED_IN_HAND` 解锁 tick 等离场监听器仍须存活）。
                _gone = {}
                for _ev, _lst in self.events._listeners.items():
                    for _l in _lst:
                        _o = _l.owner
                        if isinstance(_o, Minion) and _o.zone in (
                                Zone.REMOVED, Zone.GRAVEYARD):
                            _gone[id(_o)] = _o
                for _o in _gone.values():
                    self.events.unregister_owner(_o)
                # 战后**棋盘已复原**的观察点（快照还原之后）——供"战后收敛"
                # 类脚本使用（Tarecgosa Sticker `BG32_MagicItem_417` 需要把
                # 被快照复活的旧标记再清一次; 2026-09-02 对抗验证 BUG-2）
                self.events.fire(self, "combat_restored", hero_a=hero_a,
                                 hero_b=hero_b)
            finally:
                self._restore_no_gain = False
            self.in_combat = False
        return result

    def destroy_minion(self, minion, *, source=None, hero=None,
                       process_deaths: bool = True) -> bool:
        """**摧毁（Destroy）统一入口**——"Destroy a minion" 类效果。

        Destroy 与伤害的差别（wiki mechanics "Destroy"）: 无视圣盾/免疫、
        非伤害、`health = 0` → 走完整死亡链（亡语/复生/回池照常）。
        本入口额外广播 **`minion_destroyed`**（`hero=` 施动方、
        `minion=`、`source=`、`in_combat=`）——"After/Whenever **you
        destroy** a minion outside combat"（Kel'Thuzad Portrait
        `BG32_MagicItem_204` / Maw Caster Portrait `BG32_MagicItem_205`）
        的**唯一**观察点。旧实现各处直接 `health = 0`，事件无施动者、
        无法与战斗死亡区分（ENGINE_BACKLOG §A #4）。

        - `hero`: 施动方（默认取 `source.controller`，无 source 时取
          随从自己的 controller）
        - `process_deaths=False`: 调用方自行在更外层跑死亡链
          （亡语连锁场景——事件仍立即广播）
        返回 True = 本次确实摧毁了一个存活实体。
        """
        if minion is None or getattr(minion, "dead", False) \
                or getattr(minion, "zone", None) != Zone.PLAY:
            return False
        owner = hero if hero is not None else getattr(source, "controller",
                                                     None)
        if owner is None:
            owner = getattr(minion, "controller", None)
        minion.set(GameTag.HEALTH, 0)
        if process_deaths:
            self.check_deaths()
        self.events.fire(self, "minion_destroyed", hero=owner,
                         minion=minion, source=source,
                         in_combat=bool(self.in_combat))
        return True

    def make_golden_until_next_turn(self, minion) -> bool:
        """**临时金色**——"Make a friendly minion Golden until next turn"
        （The Golden Hammer `BG24_Reward_719t` Spellcraft / Greta Gold-Gun
        `BG25_044t`），RULES §7.4.14。

        与"永久金色化"（Reno / Golden Touch）的区别是**到期回滚**:
        - 实体换为**金色独立卡定义**（`db.golden_version`），保留全部附魔
          （`Transform` keep_buffs）
        - 打 `GILDED_NOT_TRIPLED`: 这不是三连金 → 金色状态被出售/淘汰时
          只回池 1 份（RULES §2.3 Reno 口径）
        - 登记**控制者下一个招募阶段开始**（`turn_start`，单 tick，
          SOP §16 模式 16）回滚为非金; 回滚同样保留附魔与关键词
        - 已是金色 → 无变化返回 True（不重复登记回滚）; 目标不在棋盘 /
          无金色定义 → 落空返回 False（不抛错——定向效果目标失效契约）
        - 回滚监听器 owner = 金色实体 → 出售/招募期死亡自动注销;
          战斗中战死经 `run_combat` 复原后监听器仍在（SOP §8）
        """
        hero = getattr(minion, "controller", None)
        if hero is None or minion not in getattr(hero, "board", []) \
                or getattr(minion, "dead", False):
            return False
        base_id = minion.get(GameTag.TRIPLE_BASE_CARD_ID, None) \
            or minion.card_id
        base_def = self.db.get(base_id)
        if base_def is None or self.db.golden_version(base_def) is None:
            return False
        if minion.is_golden:
            return True
        from hsrl2.actions.stats import Transform
        idx = hero.board.index(minion)
        self.run_actions(Transform(minion, base_id, gilded_not_tripled=True,
                                   force_golden=True))
        new = hero.board[idx]
        new._temporary_golden_origin = base_id

        def _revert(game, hero=None, **kw):
            # 到期回滚: 仅当仍是同一临时金色实体（未被再次变形）且在场
            if getattr(new, "_temporary_golden_origin", None) != base_id:
                return
            if new.controller is None or new not in new.controller.board \
                    or getattr(new, "dead", False):
                return
            game.run_actions(Transform(new, base_id, force_golden=False))
            new._temporary_golden_origin = None

        self.events.register(Listener(
            event="turn_start", owner=new, once=True,
            condition=lambda hero=None, _h=hero, **kw: hero is _h,
            callback=_revert))
        return True

    def _compute_damage(self, result) -> int:
        """伤害 = 胜方酒馆等级 + Σ存活随从 tier (token=T1, 金色无加成)。"""
        if result.winner is None:
            return 0
        return result.winner.tavern_tier + sum(
            m.tech_level for m in result.winner.living_minions())

    def _alive_count(self) -> int:
        return sum(1 for h in self.heroes if h.is_alive)

    # ══════════════════ 官方精确性注入 API（只读式外部注入） ═══════════════
    #
    # 2026-10-18（官方一致性 P1）：官方伤害上限由**服务端** GameEntity
    # tag 下发（`BACON_COMBAT_DAMAGE_CAP`=2089 / `_ENABLED`=3403），
    # 本引擎的 turn 表（C.damage_cap）只是其近似。真实对局日志可读到 tag 时，
    # 由 replay harness 调用这里的 API 注入；**不改变默认 turn 表**。

    def set_damage_cap(self, value: Optional[int], *,
                       enabled: bool = True) -> None:
        """注入官方伤害上限。

        Parameters
        ----------
        value:
            官方 ``BACON_COMBAT_DAMAGE_CAP`` 数值（伤害上限）。
        enabled:
            ``False`` = 官方 ``_ENABLED=0``（本回合无上限）。默认 True。
        """
        if not enabled:
            self._damage_cap_uncapped = True
            self._damage_cap_override = None
            return
        self._damage_cap_uncapped = False
        self._damage_cap_override = None if value is None else int(value)

    def clear_damage_cap(self) -> None:
        """恢复默认 turn 表行为（默认 = 不注入）。"""
        self._damage_cap_override = None
        self._damage_cap_uncapped = False

    @property
    def damage_cap_override(self) -> Optional[int]:
        return self._damage_cap_override

    @property
    def damage_cap_disabled(self) -> bool:
        """官方 ``_ENABLED=0``（无上限）是否生效。"""
        return self._damage_cap_uncapped

    # ── 动态脚本数据注入（官方 TAG_SCRIPT_DATA_NUM_1..5）─────────────
    #
    # 见 hsrl2/tags.py `ScriptDataNum`：数值取官方 enumID，但存放在
    # Entity._script_data 独立字典，绝不与 GameTag 内部语义撞号。

    def set_entity_script_data(self, entity: "Entity",
                               values: Mapping[int, int]) -> None:
        """把官方脚本数值注入实体（键 = 1..5）。

        用途：官方轨迹里 minion 带动态 ``ScriptDataNum*``（累计计数/
        当前值）时由 harness 重建；未注入的索引保持 CardDef 静态值。
        """
        for num, value in values.items():
            entity.set_script_data(num, value)

    def get_entity_script_data(self, entity: "Entity", num: int,
                               default: Optional[int] = None) -> Optional[int]:
        return entity.get_script_data(num, default)

    def inject_script_data_from_trace(self, entity: "Entity",
                                      data: Mapping[str, Any]) -> None:
        """从日志标签字典注入（键形如 ``ScriptDataNum1`` 或官方 enumID）。

        官方 enumID：NUM_1=2 / NUM_2=3 / NUM_3=2889 / NUM_4=2919 /
        NUM_5=2920（见 ``hsrl2.tags.ScriptDataNum``）。
        """
        from hsrl2.tags import OFFICIAL_TAG_TO_SCRIPT_DATA_NUM
        for key, value in data.items():
            text = str(key)
            if text.startswith("ScriptDataNum"):
                try:
                    index = int(text[len("ScriptDataNum"):])
                except (TypeError, ValueError):
                    continue
            else:
                try:
                    tag = int(text)
                except (TypeError, ValueError):
                    continue
                member = OFFICIAL_TAG_TO_SCRIPT_DATA_NUM.get(tag)
                if member is None:
                    continue
                index = int(member.name.split("_")[1])   # NUM_3 → 3
            entity.set_script_data(index, int(value))

    # ══════════════════ 实体工厂 ══════════════════

    def _script_for(self, d):
        """卡定义 → 脚本类（**金色无脚本时回落基础卡脚本**）。

        文本族: 金色 token 无独立脚本（Fishy Sticker `BG30_MagicItem_821t2`
        召唤的金色 Fish of N'Zoth `TB_BaconUps_307`、Kaboom Bot 金色
        `TB_BaconUps_028` 等）——旧实现只查金色 id → `scripts=None` →
        整卡白板（ENGINE_BACKLOG §B15）。回落时脚本一律按**实体自身
        CardDef**（金色定义）取数值，故数值口径仍正确。
        """
        from hsrl2.scripts import REGISTRY  # 延迟导入避免循环依赖
        cls = REGISTRY.get(d.id)
        if cls is not None:
            return cls
        if getattr(d, "is_golden_def", False) and d.triple_base_id:
            base = self.db.by_dbf(d.triple_base_id)
            if base is not None:
                return REGISTRY.get(base.id)
        return None

    def create_minion(self, card_id: str, *, controller=None,
                      golden: bool = False) -> Optional[Minion]:
        d = self.db.get(card_id)
        if d is None:
            raise KeyError(f"unknown minion card_id {card_id}")
        if golden:
            gd = self.db.golden_version(d)
            if gd is not None:
                d = gd
        m = Minion(d.id, d.name, atk=d.atk, health=d.health,
                   race=d.race, tech_level=d.tech_level, races=d.races)
        m.game = self
        m.controller = controller
        # 动态脚本数据通道初始化（官方 TAG_SCRIPT_DATA_NUM_1..5 静态默认值；
        # 动态累计值由脚本生产点/外部注入覆盖，见 tags.ScriptDataNum）
        m.init_script_data_from_carddef(d)
        for kw in d.keywords:
            tag = _KEYWORD_TAG_MAP.get(kw)
            if tag is not None:
                m.set(tag, True)
        if d.avenge_target:
            m.set(GameTag.AVENGE, True)
            m.set(GameTag.AVENGE_TARGET, d.avenge_target)
        # Activate（F-08 修正）: 数据导出在 cost=0 时**省略**
        # `activate_cost`（falsy），旧实现 `is not None` 会把
        # Mangled Bandit / Brain Rotter / Abyssal Envoy /
        # Mindbending Recruiter / N'raqi Frostcaller 的 Activate 整卡
        # 漏标 → use_activate 永远 False。以 XML 关键词 `activate`
        # 为权威标记，缺省 cost=0（卡面 "Activate ({2})" 显示 0）。
        if d.activate_cost is not None or "activate" in d.keywords:
            m.set(GameTag.ACTIVATE, True)
            m.set(GameTag.ACTIVATE_COST, int(d.activate_cost or 0))
        # Spellcraft 随从标记（CardDef.spellcraft_id → SPELLCRAFT tag）
        if d.spellcraft_id is not None:
            m.set(GameTag.SPELLCRAFT, True)
        if golden:
            # 金色实体: 记录基础卡 id — 出售/淘汰时返还基础卡 3 份
            base_def = self.db.by_dbf(d.triple_base_id) if d.is_golden_def else None
            base_id = base_def.id if base_def is not None else card_id
            m.set(GameTag.TRIPLE_BASE_CARD_ID, base_id)
            m.set(GameTag.GOLDEN, True)
        # 脚本绑定: card_id → REGISTRY（金色无脚本时回落基础卡脚本）
        m.scripts = self._script_for(self.db.get(m.get(GameTag.CARD_ID)))
        # 异变 Incubation Mutation "Minions with no type have all minion
        # types"——全局生效（酒馆/棋盘/手牌/生成物一致）
        if getattr(self, "_notype_is_all", False) and m.race == Race.NONE:
            m.set(GameTag.RACE, Race.ALL)
            m.set(GameTag.RACES, RACE_SET_ALL)
        self.events.fire(self, "entity_created", entity=m)
        return m

    def create_entity(self, card_id: str, *, controller=None) -> "Entity":
        """通用实体创建（饰品/任务/奖励——card_type 44 等非随从法术）。"""
        d = self.db.get(card_id)
        if d is None:
            raise KeyError(f"unknown card_id {card_id}")
        from hsrl2.entity import Entity as _E
        e = _E(d.id, d.name, card_type=d.card_type)
        e.game = self
        e.controller = controller
        e.init_script_data_from_carddef(d)
        e.scripts = self._script_for(d)
        # Spellcraft 标记（CardDef.spellcraft_id → SPELLCRAFT tag）——
        # 与 create_minion 同口径。饰品/任务奖励也可带 Spellcraft
        # （BG30_MagicItem_429 Demonblood Gourd 等），
        # `spellcraft.generate_for_hero` 据此生成每回合法术
        if d.spellcraft_id is not None:
            e.set(GameTag.SPELLCRAFT, True)
        return e

    # ── 任务系统 (RULES §11.1) ──

    def quest_defs(self) -> list:
        """全部**可进度化**任务卡定义。

        筛选口径（数据驱动，不用 id 前缀硬编码；实现 =
        `quest_defs_from_db(self.db)`，谓词见模块级 `is_quest_card`）:
          - `CardType.SPELL`（任务卡在数据里是 card_type 5）
          - `CardDef.quest_progress_total` 真值（CardDefs tag 535）
          - id 小写含 "quest"（区分同 tag 535 的非任务实体）
          - id 不在 `_QUEST_ANNOUNCE_TOKENS`（公告 token 显式排除）

        **实测计数（2026-09-18 数据定格，`CardDB.load(data/)` 3683 定义）**:
        带 tag 535 的定义共 **42** 个（旧文档写 66，为假）——含奖励
        `BG24_Reward_134` / `BG27_Reward_812`、普通酒馆法术 `BG28_519`、
        异变 `BG27_Anomaly_307`、饰品 `BG30_MagicItem_973` 等，card_type
        横跨 SPELL(5) / BACON_QUEST_REWARD(40) / BACON_SPELL(42) /
        BACON_ANOMALY(43) / BACON_TRINKET(44)。前三条谓词命中 **22** 张
        （BG24_Quest_* 16 + Bob + BG27 3 + BG28 1 + BG33 1）；排除两张
        公告 token 后得 **20** 张 = 19 注册 + `BG24_Quest_328`（DEFERRED）。
        两张公告 Spell token（`BG24_Quest_Bob` /
        `BG33_Anomaly_008_Quest`，文本 "In 3 turns, choose one of three
        Quests!"）实测 card_type=SPELL 且 tag 535=3，**同时满足**前三条
        谓词 → `_QUEST_ANNOUNCE_TOKENS` 是排除它们的唯一条件，**不冗余**。
        它们的语义已由 `_offer_quests` 本身的第 4 回合三选一实现，
        注册它们即"注册但空转"的第三态。
        """
        return quest_defs_from_db(self.db)

    def quest_offer_pool(self) -> list:
        """可发放任务 = `quest_defs() ∩ REGISTRY`（池门禁）。

        未注册（无进度脚本）的任务卡**永不发出**——否则 `hero.quest`
        会指向一个既无监听器、又无目标的空转实体（铁律: 禁止
        "注册但空转"/静默第三态）。
        """
        from hsrl2.scripts import REGISTRY
        return [d for d in self.quest_defs() if REGISTRY.get(d.id) is not None]

    def quest_script(self, hero: Hero):
        """`hero.quest` 的脚本类（无任务/未注册 → None）。"""
        quest = getattr(hero, "quest", None)
        if quest is None:
            return None
        from hsrl2.scripts import REGISTRY
        return REGISTRY.get(quest.card_id)

    def quest_target(self, hero: Hero) -> Optional[int]:
        """任务脚本的 `target`（非计数器任务 / 无任务 → None）。

        `target` 是任务完成阈值（计数式）或达标阈值（阈值式，如
        `BG27_Quest_801` "warband total Attack"）。数值权威 =
        `CardDef.quest_progress_total`（CardDefs tag 535）= 各卡页 wiki
        "New baseline requirement" 的当前值（2026-09-18 逐卡核对，见
        `docs/agents/QUEST_DEFERRED_SPEC.md`）——脚本字面量与数据字段
        的一致性由 `test_batch_quests.py` 的交叉校验守卫锁定。
        """
        script = self.quest_script(hero)
        return getattr(script, "target", None) if script is not None else None

    def advance_quest_progress(self, hero: Hero, amount: int = 1) -> bool:
        """任务进度**唯一入口**（计数式）。返回 True = 本次调用完成了任务。

        契约（QUEST_DEFERRED_SPEC §2.1 蓝图）:
          - 无任务 / 任务脚本无 `target` / 已领奖 → False（不累加）
          - `hero._quest_progress` 累加 `amount`；达 `quest_target` →
            `complete_quest(hero)` 发奖并置 `_quest_completed` 阻止二次计分
          - `amount <= 0` → False（阈值式任务用 `set_quest_progress`）

        机制留在引擎（脚本只声明"监听哪个事件 + 目标值"），因此本方法
        是唯一进度写入点——变异它（改阈值 / 去掉完成判定）必须能让
        行为测试失败。
        """
        if amount <= 0:
            return False
        if getattr(hero, "_quest_completed", False):
            return False
        if getattr(hero, "quest", None) is None:
            return False
        target = self.quest_target(hero)
        if target is None:
            return False
        hero._quest_progress += amount
        if hero._quest_progress >= target:
            hero._quest_completed = True
            self.complete_quest(hero)
            return True
        return False

    def set_quest_progress(self, hero: Hero, value: int) -> bool:
        """阈值式任务的**当前值**写入（如 warband 总攻击力）。

        与 `advance_quest_progress` 共用完成判定；`value` 反映的是
        "当前状态量"而非累加次数，故**只升不降**（防止状态回落后进度
        倒退——阈值式任务的语义是"曾经达到过"）。
        """
        if getattr(hero, "_quest_completed", False):
            return False
        if getattr(hero, "quest", None) is None:
            return False
        target = self.quest_target(hero)
        if target is None:
            return False
        if value <= hero._quest_progress:
            return False
        hero._quest_progress = value
        if value >= target:
            hero._quest_completed = True
            self.complete_quest(hero)
            return True
        return False

    def _offer_quests(self, hero: Hero) -> None:
        """第 4 回合: 三对"任务+奖励"选一对。

        任务候选 = `quest_offer_pool()`（全部**已注册**任务卡，含
        `BG27_Quest_*`/`BG28_Quest_*` 同族）; 奖励 = `BG24_Reward_*`
        实体。配对规则官方未公布 → 随机配对（Malygos "官方权重未公布
        → 等权"裁定先例），三对不同 quest 各配一张随机 reward。

        **2026-09-18 状态**: 任务目标值按项目所有者裁定的权威序落地
        ——数值 = wiki 各卡页 "New baseline requirement" 的当前值 =
        CardDefs `QUEST_PROGRESS_TOTAL`（逐卡 URL/oldid/引文见
        `docs/agents/QUEST_DEFERRED_SPEC.md`）。`BG24_Quest_328` 保持
        DEFERRED: 卡数据携带 `quest_progress_total=1`（tag 535）——**不是
        缺目标值**；阻塞是 "Win the game." 的胜义无权威（第 1 名 / 前 4 /
        单场战斗胜利三者无法消歧）。两张公告 Spell token 由
        `_QUEST_ANNOUNCE_TOKENS` 从 `quest_defs()` 排除（非注册态），
        故不在候选池。
        """
        quests = [d.id for d in self.quest_offer_pool()]
        rewards = [d.id for d in self.db._by_id.values()
                   if d.id.startswith("BG24_Reward_")]
        if not quests or not rewards:
            return
        q3 = self.rng.sample(quests, min(3, len(quests)),
                             label="quest_offer")
        pairs = [(q, self.rng.choice(rewards, label="quest_reward_pair"))
                 for q in q3]

        def resolve(pair):
            qid, rid = pair
            quest_entity = self.create_entity(qid, controller=hero)
            hero.quest = quest_entity
            hero._quest_progress = 0
            hero._quest_completed = False
            # 奖励**先**暂存: `on_bind` 可能当场达标（阈值式任务，如
            # BG27_Quest_801 "warband total Attack" 在第 4 回合已 ≥28）
            # → `complete_quest` 必须能立刻发放（顺序颠倒会丢奖励）。
            hero._quest_reward_id = rid
            self.run_on_bind(quest_entity, ctx={"hero": hero})

        self.pending_choices.append(PendingChoice(
            hero, pairs, "quest_offer", resolve_callback=resolve))

    def complete_quest(self, hero: Hero) -> None:
        """任务完成: 发放任务奖励（hero.quest_rewards——SoC/EoT/SoT
        钩子已全线接线）。

        唯一发奖入口: 已发奖（`_quest_reward_id is None`）→ no-op，
        二次调用不重复发奖。
        """
        rid = getattr(hero, "_quest_reward_id", None)
        if rid is None:
            return
        reward = self.create_entity(rid, controller=hero)
        hero.quest_rewards.append(reward)
        self.run_on_bind(reward, ctx={"hero": hero})
        hero._quest_reward_id = None

    # ── 饰品系统 (RULES §7.4) ──

    def grant_card_copy_to_hand(self, hero: Hero, card_def,
                                golden: bool = False) -> bool:
        """授予一张**白板**副本进手牌（"Get a <卡>" 族的统一入口）。

        RULES §7.4.6（饰品关联卡协议）+ §2.3/§2.4（池记账）+ SOP §3:
        - `MINION` 且 `is_pool_minion`: 先 `minion_pool.acquire` 占池;
          池中无副本 → 本次获取**落空**（返回 False，RULES §2.4
          "池中无副本的随从不可被任何玩家获取"）——与 Discover /
          GetRandom / `{0}` 奖励副本（batch_quest_rewards4
          `_grant_reward_copy`）同一口径
        - `SPELL` / `BACON_SPELL` 且 `is_pool_spell`: `spell_pool.acquire`
          占池; 池空 → 落空
        - 其它（token / 池外专属卡）: 零池操作（`release` 亦 no-op）
        - 副本为**白板**（不复制任何 buff——文本无"保留附魔"）
        - `golden=True`（或直接传入金色独立定义）: 副本为**金色本体**
          并打 `GILDED_NOT_TRIPLED`（非三连金——选项/本副本只占池 1 份
          基础副本，出售回池亦 1 份，RULES §2.3; 与 `Discover(golden=True)`
          同口径）。用于 "get an extra copy of it" 遇到金色发现
          （Sinstone Sticker × Treasure Hoard，2026-09-02 对抗审查）。
          **池记账按基础卡定义判定**（`triple_base_id` 回落）——金色独立
          定义的 `is_pool_minion=False`，按它判定会"跳过 acquire 但仍按
          TRIPLE_BASE_CARD_ID 释放 1 份"→ 池净 +1（2026-09-02 对抗审查
          实测 BG36_MagicItem_363）。
        - 满手 → `pending_hand_add` 入等待队列（RULES §3.3）
        返回 True=副本**已产生**（已入手或已入等待队列——队列必然交付）/
        False=落空（池中无副本 / 卡定义非法）。额度类脚本（"N times per
        game/combat"）据返回值决定是否扣减：**满手排队必须算成功**，
        否则玩家可以靠满手反复绕过额度（2026-09-02 对抗审查证伪
        BG36_MagicItem_217 Funeral Wreath / BG35_MagicItem_931
        Transcribing Typewriter）。

        注: 需要"此刻是否真的已进手牌"的调用方请自行检查
        `game.pending_hand_queue`（`pending_hand_add` 的原始返回值）。
        """
        if card_def is None:
            return False
        if card_def.card_type == CardType.MINION:
            # 池记账以**基础卡定义**为准（RULES §2.3）: 金色"Get a Golden
            # <池随从>"传入的是金色独立定义（`is_pool_minion=False`），
            # 若按它判定就会跳过 acquire 却在出售时按 TRIPLE_BASE_CARD_ID
            # 释放 1 份 → 池净 +1（2026-09-02 对抗审查实测: BG36_MagicItem_363
            # Escapee Portrait 交付金色 Enterprising Escapee 卖出后池 9→10）。
            pool_def = card_def
            if card_def.is_golden_def and card_def.triple_base_id is not None:
                pool_def = self.db.by_dbf(card_def.triple_base_id) or card_def
            if pool_def.is_pool_minion:
                if not self.minion_pool.acquire(pool_def.id):
                    return False
            copy = self.create_minion(card_def.id, controller=hero,
                                      golden=bool(golden))
            if copy is None:
                return False
            if golden or card_def.is_golden_def:
                copy.set(GameTag.GILDED_NOT_TRIPLED, True)
            self.pending_hand_add(hero, copy)
            return True
        if card_def.card_type in (CardType.SPELL, CardType.BACON_SPELL):
            if card_def.is_pool_spell:
                if not self.spell_pool.acquire(card_def.id):
                    return False
            spell = self.create_spell(card_def.id, controller=hero)
            if spell is None:
                return False
            self.pending_hand_add(hero, spell)
            return True
        return False

    def add_permanent_spellcraft_rule(self, hero: Hero, source,
                                      predicate) -> None:
        """注册"你的某类随从的 Spellcraft 永久化"规则（被动实体调用）。

        文本族: "Your Thaumaturgists' **Spellcrafts** are permanent"
        （`BG32_MagicItem_920`）/ Weary Portrait（`BG32_MagicItem_933`）。
        `predicate(source_minion) -> bool` 在**生成** Spellcraft 法术时
        对该随从求值; 命中则法术标记 `permanent_spellcraft`，结算时其
        temporary buff 被翻转为永久（RULES §6.13 永久化拦截窗口）。
        生命周期: 读取规则时校验 `source` 仍属于该英雄（饰品被替换即失效）。
        """
        hero.permanent_spellcraft_rules.append((source, predicate))

    def _permanent_spellcraft_matches(self, hero, minion) -> bool:
        """该随从的 Spellcraft 是否被某条有效规则永久化。"""
        for source, predicate in list(
                getattr(hero, "permanent_spellcraft_rules", [])):
            if not (source in hero.trinkets
                    or source in getattr(hero, "quest_rewards", [])
                    or source in hero.board):
                continue                      # source 已离场 → 规则失效
            if predicate(minion):
                return True
        return False

    def grant_combat_deathrattle(self, hero: Hero, minion,
                                 extra_fn) -> None:
        """**战斗内授予亡语**（RULES §3.5/§6.13 注）。

        语义: 原生亡语**先**结算、追加效果**后**置（官方 Dark Gift 亡语
        附加顺序）; 追加效果返回的 Action(s) 与原生结果合并返回（引擎按
        返回值逐个结算）。`DEATHRATTLE` tag 由战斗快照恢复回滚、
        `_script_overrides` 由 `run_combat` 的 finally 统一恢复（不依赖
        脚本侧 COMBAT_END 监听）。

        用于 "This minion gains 'Deathrattle: …' during combat" 族
        （Tamsin/Bru'kan Earth/Hoggy Bank/Sky Golem 等）。
        """
        saved = dict(minion._script_overrides)
        prev_override = minion._script_overrides.get("deathrattle")
        scripts_fn = (getattr(minion.scripts, "deathrattle", None)
                      if minion.scripts is not None else None)

        def chained(source, g, ctx):
            if prev_override is not None:
                result = (prev_override(source, g, ctx)
                          if callable(prev_override) else prev_override)
            elif scripts_fn is not None:
                result = scripts_fn(source, g, ctx)
            else:
                result = None
            extra = extra_fn(source, g, ctx)
            if extra is None:
                return result
            extra_list = list(extra) if isinstance(extra, (list, tuple)) \
                else [extra]
            if result is None:
                return extra_list
            result_list = list(result) if isinstance(result, (list, tuple)) \
                else [result]
            return result_list + extra_list

        minion.set_script_override("deathrattle", chained)
        minion.set(GameTag.DEATHRATTLE, True)
        self._combat_dr_grants.setdefault(id(hero), []).append(
            (minion, saved))

    def _restore_combat_deathrattles(self, hero: Hero) -> None:
        """战斗结束恢复本英雄全部战斗内授予的亡语 override。"""
        for minion, saved in self._combat_dr_grants.pop(id(hero), []):
            minion._script_overrides.clear()
            minion._script_overrides.update(saved)

    def add_card_aura(self, source, card_ids, atk: int = 0,
                      health: int = 0) -> None:
        """注册/更新**卡家族光环**（RULES §6.19）。

        文本族: "your **Eternal Knights** have +X/+Y this game"
        （Eternal Portrait `BG36_MagicItem_216`）/ "your <卡名> have ..."。
        - `card_ids`: 家族卡 id 集合（金色经 `TRIPLE_BASE_CARD_ID` 回落匹配）
        - **增量式**: 同 `source` 重复调用按与上次的差值更新（累积型文本:
          触发一次累加一次）; 当前棋盘/手牌/酒馆中的同族实体同步抬升血量
        - 任意区域生效（"wherever this is"）; source 离场即失效
        """
        hero = getattr(source, "controller", None)
        if hero is None:
            return
        key = getattr(source, "uuid", None) or str(id(source))
        fam = frozenset(card_ids)
        prev = hero.card_auras.get(key)
        d_atk = int(atk) - (prev[2] if prev else 0)
        d_health = int(health) - (prev[3] if prev else 0)
        hero.card_auras[key] = (source, fam, int(atk), int(health))
        if d_health:
            for zone_list in (hero.board, hero.hand, hero.tavern):
                for e in list(zone_list):
                    cid = getattr(e, "card_id", None)
                    bid = e.get(GameTag.TRIPLE_BASE_CARD_ID, None) or cid
                    if cid in fam or bid in fam:
                        e.set(GameTag.HEALTH, e.health + d_health)

    def _base_card_id(self, card_id: str) -> str:
        """卡 id → **基础卡 id**（金色无独立基础时回落自身）。"""
        d = self.db.get(card_id)
        if d is not None and getattr(d, "is_golden_def", False) \
                and d.triple_base_id:
            base = self.db.by_dbf(d.triple_base_id)
            if base is not None:
                return base.id
        return card_id

    def add_giver_bonus(self, hero, card_id: str, *, atk: int = 0,
                        health: int = 0, copies: int = 0,
                        source=None) -> None:
        """家族"给予者加成"通道（RULES §7.4.15，2026-09-13 主线原语）。

        文本族: "Your **Nalaa the Redeemers** give an extra +X/+Y"
        （Redeemer Portrait `BG30_MagicItem_944`）/ "Your **Zesty
        Shakers** give an extra copy of the spell"（Shaker Portrait
        `BG30_MagicItem_828`）。

        - `card_id` 按**基础卡 id** 归一（金色载荷与基础同族；`num` 由
          各自 CardDef 读取，此处只叠加"额外量"）
        - 载荷脚本经 `giver_bonus(hero, source.card_id)` 读取（SOP §12
          禁止读他脚本私有属性）
        - `source` = 写规则的效果实体（饰品/任务奖励）; 读取时校验其
          仍在 `hero.trinkets`/`quest_rewards`/棋盘 → 已离场即失效
          （同 `_card_aura_active` / `permanent_spellcraft_rules` 口径）。
          `source=None` = 永久规则（测试/引擎直写）。
        """
        if hero is None:
            raise GameStateError("add_giver_bonus: hero is None")
        if not isinstance(card_id, str) or not card_id:
            raise GameStateError(f"add_giver_bonus: bad card_id {card_id!r}")
        base = self._base_card_id(card_id)
        hero.giver_bonus_rules.append(
            (source, base, {"atk": int(atk), "health": int(health),
                            "copies": int(copies)}))

    def giver_bonus(self, hero, card_id: str) -> Dict[str, int]:
        """读家族给予者加成（无加成 → 全 0 的**只读**副本）。

        只汇总 `source` 仍在场（hero.trinkets / quest_rewards / board）
        的规则; 效果实体被替换/移除后加成同步失效。
        """
        if hero is None:
            raise GameStateError("giver_bonus: hero is None")
        base = self._base_card_id(card_id)
        total = {"atk": 0, "health": 0, "copies": 0}
        for source, bid, deltas in list(
                getattr(hero, "giver_bonus_rules", [])):
            if bid != base:
                continue
            if source is not None and not (
                    source in hero.trinkets
                    or source in getattr(hero, "quest_rewards", [])
                    or source in hero.board):
                continue                      # source 已离场 → 规则失效
            for key in total:
                total[key] += deltas.get(key, 0)
        return total

    def add_family_flag(self, hero, card_id: str, flag: str,
                        *, source=None) -> None:
        """家族"行为开关"通道（RULES §7.4.16，2026-09-13 主线原语）。

        文本族: "Your **Bristlebachs** play Blood Gems on **all friendly
        minions**"（Bristlebach Portrait `BG32_MagicItem_274`）——Portrait
        改写载荷效果的**目标集合/行为分支**；`§7.4.15 giver_bonus` 只承载
        **数值**加成，二者互补（前者管"打谁/是否多做一件事"，后者管
        "+多少"）。

        - `card_id` 按**基础卡 id** 归一（金色载荷与基础同族命中）
        - 载荷脚本经 `family_flag(hero, source.card_id, flag)` 读取
          （SOP §12 禁止读他脚本私有属性）
        - `source` = 写规则的效果实体（饰品/任务奖励）; 读取时校验其
          仍在 `hero.trinkets`/`quest_rewards`/棋盘 → 已离场即失效
          （同 `giver_bonus` / `_card_aura_active` 口径）。`source=None`
          = 永久规则（测试/引擎直写）。
        - `flag` 必须是非空 str: 拼写错误 fail-loud，禁止静默 False
        """
        if hero is None:
            raise GameStateError("add_family_flag: hero is None")
        if not isinstance(card_id, str) or not card_id:
            raise GameStateError(f"add_family_flag: bad card_id {card_id!r}")
        if not isinstance(flag, str) or not flag:
            raise GameStateError(f"add_family_flag: bad flag {flag!r}")
        base = self._base_card_id(card_id)
        hero.family_flags.append((source, base, flag))

    def family_flag(self, hero, card_id: str, flag: str) -> bool:
        """读家族行为开关（无该开关 → False）。

        只汇总 `source` 仍在场（hero.trinkets / quest_rewards / board）
        的规则; 效果实体被替换/移除后开关同步失效。金色载荷经基础卡 id
        归一同族命中。

        `card_id` / `flag` 与写点同样校验（非空 str，否则 `GameStateError`）
        ——2026-09-13 对抗验证 MINOR: 读点此前静默 `False`，未初始化/拼错的
        card_id 会**静默丢失**目标集改写（正是本通道要防的"静默半实现"）。
        """
        if hero is None:
            raise GameStateError("family_flag: hero is None")
        if not isinstance(card_id, str) or not card_id:
            raise GameStateError(f"family_flag: bad card_id {card_id!r}")
        if not isinstance(flag, str) or not flag:
            raise GameStateError(f"family_flag: bad flag {flag!r}")
        base = self._base_card_id(card_id)
        for source, bid, name in list(getattr(hero, "family_flags", [])):
            if bid != base or name != flag:
                continue
            if source is not None and not (
                    source in hero.trinkets
                    or source in getattr(hero, "quest_rewards", [])
                    or source in hero.board):
                continue                      # source 已离场 → 规则失效
            return True
        return False

    def add_family_races(self, hero, card_id: str, races, *,
                         source=None) -> None:
        """家族**类型身份改写**通道（RULES §7.4.16 家族通道的类型维度）。

        文本族: "Your **Brann Bronzebeards** are both Murlocs and Dragons"
        （Bronzebeard Portrait `BG30_MagicItem_418`）/ "Your **Whelp
        Smugglers** are Dragons"（Smuggler Portrait `BG30_MagicItem_825`）/
        "Your **Lightfang Enforcers** have all minion types"（Enforcer
        Portrait `BG30_MagicItem_971`）/ "Your **Drakkari Enchanters** are
        both Mechs and Elementals"（Drakkari Portrait `BG32_MagicItem_179`）
        ——Portrait 改写载荷**家族的类型身份**。与 `add_family_flag`
        （行为分支） / `add_giver_bonus`（数值）并列，是家族通道的类型维度。

        - `card_id` 按**基础卡 id** 归一（金色载荷与基础同族命中）
        - `races`: Race 可迭代; 经 `race_set` 展开（`Race.ALL` → 全 10 族）。
          **空集合 fail-loud**——"改写为零个类型"只能是拼写/调用错误，
          静默 no-op 会让饰品成为第三态。
        - `source` = 写规则的效果实体（饰品/任务奖励）; 读取时校验其仍在
          `hero.trinkets`/`quest_rewards`/棋盘 → 已离场即失效（同
          `add_family_flag` / `giver_bonus` 口径）。`source=None` = 永久
          规则（测试/引擎直写）。
        """
        if hero is None:
            raise GameStateError("add_family_races: hero is None")
        if not isinstance(card_id, str) or not card_id:
            raise GameStateError(f"add_family_races: bad card_id {card_id!r}")
        expanded = race_set(Race.NONE, races)
        if not expanded:
            raise GameStateError(
                f"add_family_races: empty races for {card_id!r}")
        base = self._base_card_id(card_id)
        hero.family_races.append((source, base, expanded))

    def family_races(self, hero, card_id: str):
        """读家族类型改写（无 → None）; 多来源同族取**并集**。

        只汇总 `source` 仍在场（hero.trinkets / quest_rewards / board）的
        规则; 效果实体被替换/移除后改写同步失效。金色经基础卡 id 归一同
        族命中。

        作用域（owner 视角）: 该覆写经 `Minion.races` 对**该 owner 的**
        实体生效（棋盘/手牌/酒馆/发现候选）——825 的官方 Dev Comment
        （Patch 30.2.0.205267，wiki revid 814123）"This applies to Whelp
        Smugglers you see in the Tavern or Discover as well, not just the
        ones in your warband."；对手实体 controller 不同 → 不命中。
        """
        if hero is None:
            raise GameStateError("family_races: hero is None")
        base = self._base_card_id(card_id)
        rules = getattr(hero, "family_races", None)
        if not rules:
            return None
        out = None
        for source, bid, races in list(rules):
            if bid != base:
                continue
            if source is not None and not (
                    source in hero.trinkets
                    or source in getattr(hero, "quest_rewards", [])
                    or source in hero.board):
                continue                      # source 已离场 → 规则失效
            out = races if out is None else (out | races)
        return out

    def effective_races(self, hero, card_def) -> frozenset:
        """**该英雄视角下**某卡定义的类型身份（含家族类型改写）。

        用途: 池/酒馆/发现候选的**种族过滤**（候选是 `CardDef` 而非实例，
        无法走 `Minion.races`）。无改写 → `CardDef.races`（数据身份）。

        权威: 825 的 Dev Comment（wiki revid 814123）——"你看到的"
        Whelp Smuggler（含 Tavern/Discover）即 Dragon; 因此对持有该饰品
        的英雄，"Discover a Dragon" 必须能给出 Whelp Smuggler。
        """
        override = self.family_races(hero, card_def.id)
        if override is not None:
            return override
        return card_def.races

    def add_consume_policy(self, hero, kind: str, *, source=None) -> None:
        """吞噬**目标选择策略**通道（RULES §7.4.16 扩展，2026-09-19 主线原语）。

        文本族: "Your **Demons** always consume the **highest-Health** minion
        in the Tavern"（Implicator Portrait `BG32_MagicItem_824`）——Portrait
        改写持有者**全部恶魔**吞噬效果的目标选择策略。与 `family_flags`
        的区别: 后者的键是**卡家族 id**，而 "Your Demons" 是**种族范围**
        （Ur'zul / Mind Muck / Methodical Madness / False Implicator 等
        不同家族的恶魔吞噬路径都要改），按卡 id 归一无法承载。

        - `kind` 必须是非空 str（唯一取值 `CONSUME_POLICY_HIGHEST_HEALTH`，
          定义在 `hsrl2.actions.consume`）——拼写错误/None fail-loud，
          禁止静默 no-op。
        - `source` = 写规则的效果实体（饰品/任务奖励）; 读取时校验其仍在
          `hero.trinkets`/`quest_rewards`/`board` → 已离场即失效（同
          `add_family_flag` / `add_giver_bonus` / `_card_aura_active`
          口径）。`source=None` = 永久规则（测试/引擎直写）。
        """
        if hero is None:
            raise GameStateError("add_consume_policy: hero is None")
        from hsrl2.actions.consume import CONSUME_POLICY_HIGHEST_HEALTH
        if kind != CONSUME_POLICY_HIGHEST_HEALTH:
            # 关闭集合校验: 拼错的 kind 会因为落到"无策略"分支而**静默降级
            # 为均匀随机**（对抗验证实测: 全量套件无法察觉）→ 必须 fail-loud。
            raise GameStateError(
                f"add_consume_policy: unknown kind {kind!r} "
                f"(唯一取值 {CONSUME_POLICY_HIGHEST_HEALTH!r})")
        hero.consume_policies.append((source, kind))

    def consume_policy(self, hero) -> Optional[str]:
        """读吞噬目标选择策略（无 → None）。

        只汇总 `source` 仍在场（hero.trinkets / quest_rewards / board）
        的规则; 效果实体被替换/移除后策略同步失效（与 `family_flag` 同构）。
        """
        if hero is None:
            raise GameStateError("consume_policy: hero is None")
        for source, kind in list(getattr(hero, "consume_policies", [])):
            if source is not None and not (
                    source in hero.trinkets
                    or source in getattr(hero, "quest_rewards", [])
                    or source in hero.board):
                continue                      # source 已离场 → 规则失效
            return kind
        return None

    def pick_consume_victim(self, consumer, candidates, *, label: str):
        """从 `candidates` 选吞噬目标（Implicator Portrait 策略读取点）。

        - **调用方须先保证 `candidates` 非空**（空候选 = 效果落空，由各卡
          在调用前自行 `return`；本方法不做空集兜底）。
        - 无策略 / consumer 非**本人恶魔**（race DEMON 或 ALL）
          → 均匀随机（既有 `game.rng.choice` 口径; `label` 由调用方给出，
          保持各卡原有随机流标签）
        - 策略 = `CONSUME_POLICY_HIGHEST_HEALTH` 且 consumer 是本人恶魔
          → `max_health` 最大者; **并列极大**时在并列集内 `game.rng.choice`
          （卡面 "always consume the highest-Health minion" 未定义同值
          次序 → 保留引擎随机确定性协议，不发明 tie-break 身份序）
        """
        from hsrl2.actions.consume import CONSUME_POLICY_HIGHEST_HEALTH
        hero = getattr(consumer, "controller", None)
        _has_race = getattr(consumer, "has_race", None)
        if (candidates and hero is not None
                and self.consume_policy(hero) == CONSUME_POLICY_HIGHEST_HEALTH
                and _has_race is not None and _has_race(Race.DEMON)):
            best = max(m.max_health for m in candidates)
            top = [m for m in candidates if m.max_health == best]
            if len(top) == 1:
                return top[0]
            return self.rng.choice(top, label=label)
        return self.rng.choice(candidates, label=label)

    def add_persist_source(self, hero, source, card_ids) -> None:
        """登记"指定来源授予的属性**跨战斗持久化**"规则（RULES §3.5 例外 4）。

        文本族: "Your **Showy Cyclists'** Deathrattles give **permanent**
        stats"（Cyclist Portrait `BG36_MagicItem_362`）。

        - `card_ids`: 家族卡 id 集合（金色经 `TRIPLE_BASE_CARD_ID` 回落匹配）
        - `source` = 写规则的效果实体（饰品/任务奖励）; 读取时校验其仍在
          `hero.trinkets`/`quest_rewards`/棋盘 → 已离场即失效（同
          `add_giver_bonus` / `add_family_flag` / `_card_aura_active` 口径）
        - 累积式: 同一 `source` 重复登记合并集合（副本饰品各写一份）
        - 载荷脚本经 `Game.minion_persist_source(hero, minion)` 读取
          （SOP §12 禁止读他脚本私有属性），命中则该次 `Buff` 标
          `persist=True` → `run_combat` 恢复阶段按该标记重放（引擎
          `run_combat` 的"例外 4"通道）
        """
        if hero is None:
            raise GameStateError("add_persist_source: hero is None")
        if source is None:
            raise GameStateError("add_persist_source: source is None")
        ids = frozenset(card_ids)
        if not ids:
            raise GameStateError("add_persist_source: empty card_ids")
        for i, (src, existing) in enumerate(hero.persist_sources):
            if src is source:
                hero.persist_sources[i] = (src, existing | ids)
                return
        hero.persist_sources.append((source, ids))

    def _persist_source_entry(self, hero, minion):
        """命中"跨战斗持久化"来源规则的条目 `(source, ids)`（无 → None）。

        只汇总 `source` 仍在场（hero.trinkets / quest_rewards / board）
        的规则; 效果实体被替换/移除后规则同步失效。家族按
        `TRIPLE_BASE_CARD_ID` 回落匹配（金色载荷同族命中）。
        """
        if hero is None or minion is None:
            return None
        cid = getattr(minion, "card_id", None)
        bid = minion.get(GameTag.TRIPLE_BASE_CARD_ID, None) or cid
        for source, ids in list(getattr(hero, "persist_sources", [])):
            if source is not None and not (
                    source in hero.trinkets
                    or source in getattr(hero, "quest_rewards", [])
                    or source in hero.board):
                continue                      # source 已离场 → 规则失效
            if cid in ids or bid in ids:
                return (source, ids)
        return None

    def minion_persist_source(self, hero, minion) -> bool:
        """该随从当前是否命中"跨战斗持久化"来源规则（无 → False）。"""
        return self._persist_source_entry(hero, minion) is not None

    def persist_source_id(self, hero, minion) -> str:
        """命中来源规则的**来源卡 id**（无 → `""`）——`Buff.source_id` 审计用。"""
        entry = self._persist_source_entry(hero, minion)
        return getattr(entry[0], "card_id", "") if entry else ""

    def elementals_played_this_turn(self, hero) -> int:
        """`hero` 本回合已打出的元素随从数（F-06 公开读取点）。

        - 写入: `Game.play_minion` 普通打出路径（元素随从，战吼结算后）
          → `Hero.elementals_played_this_turn += 1`
        - 清零: `Game._begin_recruit_for` 每回合开始
        - 语义 = 官方 "Elemental you played this turn"；**不含**召唤、
          **不含**磁力吸附（与游戏长 `COUNTER_ELEMENTALS_PLAYED` 同口径，
          37.0 池内无 Elemental+Magnetic，实际不可达）。
        """
        return int(getattr(hero, "elementals_played_this_turn", 0))

    # ── Deity（旧神）隐藏目标（F-07；见 hsrl2/deity.py / ENGINE_NOTES） ──

    def deity(self, hero):
        """取得/惰性创建 `hero` 的隐藏 Deity 状态（`DeityState`）。

        官方开局随机二选一（C'Thun/Y'Shaarj，隐藏）。为保持
        `game.rng` 流逐位不变（env 确定性/差分可复现），选择从
        `GameRNG.seed_value` + 英雄序号确定性派生，**不消耗 rng**
        （F-07 记档 deviation）。
        """
        state = getattr(hero, "deity", None)
        if state is None:
            seed = getattr(self.rng, "seed_value", None)
            seed = 0 if seed is None else abs(int(seed))
            try:
                hero_index = self.heroes.index(hero)
            except ValueError:
                hero_index = 0
            card_id = DEITY_IDS[(seed + hero_index) % len(DEITY_IDS)]
            state = DeityState(card_id=card_id)
            hero.deity = state
        return state

    def select_deity(self, hero, card_id) -> "DeityState":
        """测试/日志注入: 显式指定 `hero` 的 Deity（C'Thun/Y'Shaarj）。"""
        if card_id not in DEITY_IDS:
            raise GameStateError(f"unknown deity card_id {card_id!r}")
        state = DeityState(card_id=card_id)
        hero.deity = state
        return state

    def give_deity_stats(self, hero, atk: int, health: int) -> "DeityState":
        """"Give your Deity +atk/+health" 的唯一写入点（F-07）。"""
        state = self.deity(hero)
        state.atk += int(atk)
        state.health += int(health)
        return state

    def inject_deity_state(self, hero, *, card_id: str,
                           atk: int = 1, health: int = 1,
                           progress: int = 0, awakened: bool = False,
                           sigil_card_id: Optional[str] = None,
                           golden: bool = False,
                           board_tokens: Optional[list] = None
                           ) -> "DeityState":
        """F-15: 显式注入官方战斗边界 Deity 快照（默认行为不变）。

        仅由 diff-harness/测试在构建战斗前调用；未调用时 `hero.deity`
        仍是惰性状态，所有旧路径逐位不变。注入状态标记 `injected=True`，
        `_reset_deity_combat` 不会覆盖其 progress/awakened（官方边界快照
        是权威值）；sigil 记录 `BG_OldGod` 对象；`board_tokens` 可在战斗
        边界召唤 Deity token（每项 dict：card_id/atk/health/golden/
        position/keywords）。
        """
        if card_id not in DEITY_IDS:
            raise GameStateError(f"unknown deity card_id {card_id!r}")
        state = DeityState(card_id=card_id, golden=bool(golden),
                           atk=int(atk), health=int(health),
                           progress=int(progress),
                           awakened=bool(awakened),
                           sigil_card_id=sigil_card_id,
                           injected=True)
        hero.deity = state
        if sigil_card_id:
            self.inject_deity_sigil(hero, sigil_card_id,
                                    progress=int(progress),
                                    awakened=bool(awakened))
        for token in board_tokens or []:
            self.inject_deity_board_token(hero, **dict(token))
        return state

    def inject_deity_sigil(self, hero, card_id: str = "BG_OldGod",
                           *, progress: int = 0,
                           awakened: bool = False) -> "DeitySigilState":
        """F-15: 注入官方 `BG_OldGod` sigil 对象（默认 None/零副作用）。"""
        sigil = DeitySigilState(card_id=str(card_id),
                                progress=int(progress),
                                awakened=bool(awakened))
        hero.deity_sigil = sigil
        state = self.deity(hero)
        state.sigil_card_id = str(card_id)
        state.injected = True
        return sigil

    def inject_deity_board_token(self, hero, *, card_id: Optional[str] = None,
                                 atk: Optional[int] = None,
                                 health: Optional[int] = None,
                                 golden: bool = False,
                                 position: Optional[int] = None,
                                 keywords: Optional[list] = None
                                 ) -> "Minion":
        """F-15: 在战斗边界召唤一个 Deity token 到指定站位。

        默认 card_id = 当前 Deity 的 token id；未注入 Deity 时用惰性
        state。满场/创建失败 → GameStateError（fail-loud，不静默丢）。
        """
        state = self.deity(hero)
        cid = card_id or state.token_card_id
        token = self.create_minion(cid, controller=hero,
                                   golden=bool(golden))
        if token is None:
            raise GameStateError(f"deity token create failed: {cid!r}")
        if atk is not None:
            token.set(GameTag.BASE_ATK, int(atk))
            token.set(GameTag.ATK, int(atk))
        if health is not None:
            token.set(GameTag.BASE_HEALTH, int(health))
            token.set(GameTag.HEALTH, int(health))
        for keyword in keywords or []:
            tag = _KEYWORD_TAG_MAP.get(str(keyword))
            if tag is not None:
                token.set(tag, True)
        if not self.summon(hero, token, position):
            raise GameStateError(
                f"deity token summon failed (board full): {cid!r}")
        return token

    def set_deity_progress(self, hero, progress: int,
                           awakened: Optional[bool] = None) -> "DeityState":
        """设置 Deity progress（可同时设置 awakened）；注入态。"""
        state = self.deity(hero)
        state.progress = int(progress)
        if awakened is not None:
            state.awakened = bool(awakened)
        state.injected = True
        return state

    def set_deity_sigil(self, hero, sigil_card_id: Optional[str]
                        ) -> "DeityState":
        """记录官方 `BG_OldGod` sigil card id（不参与战斗结算）。"""
        state = self.deity(hero)
        state.sigil_card_id = sigil_card_id
        state.injected = True
        if sigil_card_id:
            hero.deity_sigil = DeitySigilState(card_id=str(sigil_card_id),
                                               progress=state.progress,
                                               awakened=state.awakened)
        else:
            hero.deity_sigil = None
        return state

    def deity_threshold(self) -> int:
        """awaken 阈值（官方 `BG_OldGod` NUM_1；数据 255130 = 4）。"""
        if self._deity_threshold is None:
            self._deity_threshold = threshold_from_db(self.db)
        return self._deity_threshold

    def deity_combat_deaths(self, hero) -> list:
        """本场战斗友方 Aberration 死亡序列 [(card_id, 攻, 最大生命)]。"""
        return list(self._deity_combat_deaths.get(hero, []))

    def _reset_deity_combat(self) -> None:
        """每场战斗开始: 清空 Aberration 死亡记录、重置进度/awaken 标记。"""
        self._deity_combat_deaths = {}
        for hero in self.heroes:
            state = getattr(hero, "deity", None)
            if state is not None and not state.injected:
                state.progress = 0
                state.awakened = False

    def _note_aberration_death(self, m) -> None:
        """战斗内友方 Aberration 死亡: 记录（Y'Shaarj 读取）+ 推进进度。"""
        if not self.in_combat:
            return
        hero = getattr(m, "controller", None)
        if hero not in self.heroes:
            return
        if not m.has_race(Race.ABERRATION):
            return
        state = self.deity(hero)
        base_id = m.get(GameTag.TRIPLE_BASE_CARD_ID, None) or m.card_id
        self._deity_combat_deaths.setdefault(hero, []).append(
            (base_id, int(m.atk), int(m.max_health)))
        if state.awakened:
            return
        state.progress += 1

    def _maybe_awaken_deity(self, hero) -> bool:
        """本场进度达到阈值 → 召唤 Deity token（每场至多一次）。

        - 属性 = 当前隐藏 Deity 状态（1/1 + "give your Deity" 增益）
        - 位置 = `Game.summon` 默认最右空位（官方未公布位置，边界记档）
        - 满场 → 本次不召唤；后续友方 Aberration 死亡会重试
        - C'Thun：awaken 后对其它友方随从均分 floor(atk/N)/floor(health/N)
          （F-16；真实 Power.log 证据；N=0 边界 DEFERRED）；Y'Shaarj
          亡语由脚本实现
        """
        state = getattr(hero, "deity", None)
        if state is None or state.awakened:
            return False
        if state.progress < self.deity_threshold():
            return False
        token = self.create_minion(state.card_id, controller=hero,
                                   golden=state.golden)
        if token is None:
            return False
        token.set(GameTag.BASE_ATK, int(state.atk))
        token.set(GameTag.BASE_HEALTH, int(state.health))
        token.set(GameTag.HEALTH, int(state.health))
        if not self.summon(hero, token):
            return False
        # F-16: C'Thun awaken split（真实 Power.log 证据）:
        # 对每个**其它**存活友方随从加 floor(atk/N)/floor(health/N)，
        # N = 其它友方随从数，余数丢弃；N=0 无目标（边界保留不猜）。
        # 金/非金同一公式（证据仅覆盖 BGFYM_000；金色按同一实现）。
        if state.card_id == "BGFYM_000":
            others = [m for m in hero.board
                      if m is not token and not m.dead]
            n = len(others)
            if n:
                atk = int(state.atk) // n
                health = int(state.health) // n
                if atk or health:
                    from hsrl2.actions import Buff as _Buff
                    self.run_actions([
                        _Buff(m, atk=atk, health=health) for m in others])
        state.awakened = True
        self.events.fire(self, "deity_awakened", hero=hero,
                         deity=state, minion=token)
        return True

    def grant_bonus_keyword(self, entity, tag) -> None:
        """授予一个 **Bonus Keyword**（RULES §9.6 六张）并记录在实体上。

        - 记录进 `GameTag.BONUS_KEYWORDS`（供 "gains its **Bonus
          Keywords**"（Consuming Claw `BG36_MagicItem_801`）移转与
          "keep Bonus Keywords"（Tarecgosa Sticker `BG32_MagicItem_417`）读取）
        - 非六集成员 → fail-loud（禁止把 Poisonous/Cleave 当 Bonus Keyword）
        - 广播 `bonus_keyword_granted(minion=, tag=)`
        """
        if tag not in BONUS_KEYWORD_TAGS:
            raise GameStateError(
                f"{tag} is not a Bonus Keyword (RULES §9.6)")
        entity.set(tag, True)
        cur = set(entity.get(GameTag.BONUS_KEYWORDS, ()) or ())
        cur.add(tag)
        entity.set(GameTag.BONUS_KEYWORDS, frozenset(cur))
        self.events.fire(self, "bonus_keyword_granted", minion=entity,
                         tag=tag)

    def random_bonus_keyword(self):
        """随机一个 Bonus Keyword（六集均匀; 走 `game.rng`）。"""
        return self.rng.choice(list(BONUS_KEYWORD_TAGS),
                               label="random_bonus_keyword")

    def _persist_keyword_tags(self, m) -> tuple:
        """该实体战斗持久化时保留的关键词集合。

        默认 8 集（Dark Gift/PERSIST）; 带 `PERSIST_BONUS_ONLY`（417
        Tarecgosa Sticker "keep **Bonus Keywords**"）时**只**保留官方
        六集（不含 Poisonous/Cleave）。
        """
        if m.has(GameTag.PERSIST_BONUS_ONLY):
            return BONUS_KEYWORD_TAGS
        return _PERSIST_KEYWORD_TAGS

    def keyword_tags_of(self, entity) -> frozenset:
        """该实体当前为 True 的**关键词** tag 集合（白名单）。

        **不**包含状态 tag（DEAD/ZONE/HEALTH/…）——供死亡快照/副本复原
        使用（旧实现用"所有 True tag" → 把 `DEAD` 一并记入，复原后副本
        **死着入场**、不能攻击且立即触发自身亡语——2026-09-02 对抗验证
        BUG（Boom Controller BG30_MagicItem_440））。
        """
        kw_tags = frozenset(_KEYWORD_TAG_MAP.values()) | {
            GameTag.DEATHRATTLE, GameTag.BATTLECRY, GameTag.AVENGE,
            GameTag.ACTIVATE, GameTag.SPELLCRAFT, GameTag.CHOOSE_ONE}
        return frozenset(t for t, v in entity.tags.items()
                         if v is True and t in kw_tags)

    def _record_combat_dead_snap(self, m, hero) -> None:
        """战斗内死亡快照（**离场瞬间**记录，早于亡语/复生）。

        每英雄按死亡顺序累积; 供 "summon your **first Demon** that died
        with its **maximum stats**"（S'Thara Sticker `BG32_MagicItem_907`）
        与 "an **exact copy** of your first Mech that died"（Boom Controller
        `BG30_MagicItem_440`）读取。

        **轻量快照**（不 deepcopy tags——死亡时 tags 可能含 KILLER 实体
        引用，`snapshot_state()` 的 deepcopy 会沿引用爆炸; 2026-09-02
        实测 8 次死亡耗时 132 秒）; `buffs` 为**独立** `Buff` 实例
        （"exact copy" 不得共享附魔对象）。
        """
        if hero is None:
            return
        if not hasattr(hero, "_combat_dead_snaps"):
            hero._combat_dead_snaps = []
        # 属性口径 = base + 附魔（**不含光环/动态脚本钩子**）——消费者把
        # 快照值写回 BASE_ATK/HEALTH 或减 Σ附魔复原基础值，光环由新实体
        # 在棋盘上实时重算; 记录 `m.atk`（含光环）会与实时光环双计
        # （2026-09-13 对抗验证 MAJOR，`Entity.stats_without_aura`）。
        snap_atk, snap_health = m.stats_without_aura()
        hero._combat_dead_snaps.append({
            "card_id": m.card_id,
            "golden": m.is_golden,
            "race": m.race,
            "atk": snap_atk,
            "max_health": snap_health,
            "keywords": tuple(self.keyword_tags_of(m)),   # 白名单（不含 DEAD）
            "buffs": [Buff(atk=b.atk, health=b.health,
                           temporary=b.temporary,
                           source_id=b.source_id,
                           dark_gift=b.dark_gift,
                           gem=b.gem, persist=b.persist)
                      for b in m._buffs],
        })

    def _fire_last_minion_died(self) -> None:
        """战斗内: 某英雄棋盘不再有存活随从时广播 `last_minion_died`
        （每场战斗每英雄一次）。

        文本族: "After your last minion dies each combat"（S'Thara Sticker
        `BG32_MagicItem_907` / Soul Fermenter `BG35_MagicItem_732`）。
        幽灵（health<=0 的临时 Hero）与已淘汰者不计。
        """
        for hero in self.heroes:
            if hero in self._last_minion_fired:
                continue
            if hero.health <= 0 and hero.armor <= 0:
                continue
            if not getattr(hero, "_combat_dead_snaps", None):
                continue      # 本场**无随从死亡**（如空板从未出兵）→ 不触发
            if any(not x.dead for x in hero.board):
                continue
            self._last_minion_fired.add(hero)
            self.events.fire(self, "last_minion_died", hero=hero)

    def add_tier_aura(self, source, max_tier: int, atk: int,
                      health: int) -> None:
        """注册 **tier 维度光环**（RULES §6.19——"Your minions from
        Tier N or lower have +X/+Y"，如 `BG30_MagicItem_843t` Horde
        Keychain / `AURA=1` 数据族）。

        与 `hero.race_auras`（种族维度）并列: 读取点
        `Entity._aura_atk/_aura_health`，只作用于**该英雄棋盘上的**随从
        （`zone == BOARD`），因此对任何入板路径（summon / Transform /
        Jandice 换入）恒生效——这是"真光环"相对"入场即 buff"的关键差异
        （2026-09-02 对抗审查: 后者漏掉非 summon 路径）。

        生命周期: 读取时校验 `source` 仍属于该英雄（trinkets /
        quest_rewards / board）→ 饰品被替换/移除即自动失效，无需清理钩子。
        """
        from hsrl2.entity import Entity as _E
        if not isinstance(source, _E) or source.controller is None:
            raise GameStateError("add_tier_aura: source needs controller")
        hero = source.controller
        hero.tier_auras[source.uuid] = (
            source, int(max_tier), int(atk), int(health))
        # 与 ApplyRaceAura 同口径: 光环生命加成同步抬升**当前**血量
        # （在场匹配随从 +health 增量; 未来入场者由 summon 满血重算）
        if health:
            for m in list(hero.board):
                if getattr(m, "tech_level", 99) <= int(max_tier):
                    m.set(GameTag.HEALTH, m.health + int(health))

    def trinket_related_card(self, trinket_id: str):
        """饰品的**关联卡**定义（"Get a <卡>" / "Cast <法术>" 族的 {0}）。

        数据链（RULES §7.4.6）: `CardDef.evolution_card_id` → `db.by_dbf`
        （与异变授予第二技能用的同一个字段; 对饰品它指向该饰品的关联
        卡——Portrait 族指向被授予的随从、Tome/Sticker 族指向被授予/
        施放的法术）。解析失败 → None（调用方整卡落空，不近似）。
        """
        d = self.db.get(trinket_id)
        if d is None or d.evolution_card_id is None:
            return None
        return self.db.by_dbf(d.evolution_card_id)

    def grant_trinket_related_card(self, hero: Hero, trinket_id: str) -> bool:
        """授予饰品关联卡的副本进手牌（"Get a <卡>" 统一实现）。"""
        return self.grant_card_copy_to_hand(
            hero, self.trinket_related_card(trinket_id))

    def grant_trinket_related_card_entity(self, hero: Hero, trinket_id: str):
        """授予饰品关联卡并返回**该副本实体**（"Get a <卡>. Set its stats
        to X/Y" 族，如 Smuggler Portrait `BG30_MagicItem_825`）。

        与 `grant_trinket_related_card` 完全同口径（数据链 + 池记账 +
        满手排队），差别只在返回值:
          - 成功入手 → 返回手牌中的该副本实体;
          - 满手排队 → 返回 `pending_hand_queue` 中的待交付实体
            （"Set its stats" 仍作用于该副本，交付后即为 X/Y）;
          - 数据链缺失 / 池中无副本（落空）→ None。
        """
        rel = self.trinket_related_card(trinket_id)
        if rel is None:
            return None
        before = len(hero.hand)
        if not self.grant_card_copy_to_hand(hero, rel):
            return None
        if len(hero.hand) > before and hero.hand[before].card_id == rel.id:
            return hero.hand[before]
        for h, e in reversed(self.pending_hand_queue):
            if h is hero and getattr(e, "card_id", None) == rel.id:
                return e
        return None


    @staticmethod
    def _trinket_subsets(d) -> set:
        """饰品关联的随从类型集合（subset_* 标志）。"""
        from hsrl2.tags import Race
        mapping = {
            "subset_beast": Race.BEAST, "subset_murloc": Race.MURLOC,
            "subset_mech": Race.MECH, "subset_demon": Race.DEMON,
            "subset_dragon": Race.DRAGON, "subset_pirate": Race.PIRATE,
            "subset_elemental": Race.ELEMENTAL,
            "subset_quilboar": Race.QUILBOAR, "subset_naga": Race.NAGA,
            "subset_undead": Race.UNDEAD,
        }
        return {r for flag, r in mapping.items() if d.raw.get(flag)}

    def _type_association(self, hero: Hero) -> Optional[set]:
        """战场类型关联（RULES §7.4.2: T6 需 2 只 / T9 需 3 只;
        ≥3 种不同 = Menagerie）。返回 None=无关联。"""
        counts = {}
        for m in hero.board:
            if m.dead or m.race in (Race.NONE, Race.ALL):
                continue
            counts[m.race] = counts.get(m.race, 0) + 1
        threshold = C.TRINKET_TYPE_THRESHOLD.get(self.turn, 3)
        associated = {r for r, n in counts.items() if n >= threshold}
        if len(associated) >= C.TRINKET_MENAGERIE_TYPES:
            return "MENAGERIE"
        return associated or None

    def grant_trinket(self, hero: Hero, trinket_id: str,
                      source: str = "grant", duplicate: bool = False):
        """直接授予一张饰品（RULES §7.4.3——非商店路径的唯一入口）。

        文本族: "Get a random Trinket" / "transform into a copy of it" /
        "replace this"（Mystery Cube / Souvenir Stand / Trip Vouchers /
        Rune of Transmutation / Orb of the Unknown / Crystal Ball 族）。

        - 跨局不重复记账（`_trinkets_granted`）; 已获得过 → 返回 None
          ——**除非** `duplicate=True`（"transform into a copy of it" 族:
          官方允许持有同一饰品的两份副本，如 Souvenir Stand 复制已购
          Greater / Crystal Ball 把第二技能槽变成所购饰品的副本;
          RULES §7.4.3 副本条款）
        - create_entity → hero.trinkets.append → run_script_hook(on_bind,
          ctx={"hero": hero})
        - fire "trinket_granted"（hero=, trinket=, source=）
        返回实体。
        """
        d = self.db.get(trinket_id)
        if d is None:
            raise KeyError(f"unknown trinket {trinket_id}")
        if not duplicate and trinket_id in hero.trinkets_granted:
            return None
        e = self.create_entity(trinket_id, controller=hero)
        hero.trinkets.append(e)
        hero.trinkets_granted.add(trinket_id)
        self._trinkets_granted.add(trinket_id)      # 全桌并集（观察用）
        self.run_on_bind(e, ctx={"hero": hero})
        self.events.fire(self, "trinket_granted", hero=hero, trinket=e,
                         source=source)
        return e

    def copy_trinket(self, hero: Hero, trinket_id: str, *,
                     replace=None, source: str = "copy"):
        """复制一份饰品给 hero（"transforms into a copy of it" 原语）。

        RULES §7.4.3 副本条款:
        - **不走跨局去重**（`duplicate=True`）——复制的语义就是"已拥有
          的那张再来一份"（两份同时生效: 光环/监听各注册一次）
        - `replace` 给出时先移除该实体并注销其监听（Mystery Cube /
          Souvenir Stand / Crystal Ball 的 "this transforms" 部分）
        - 返回新实体; 池/金币不涉及（饰品无池）
        """
        if replace is not None:
            if replace in hero.trinkets:
                hero.trinkets.remove(replace)
            self.events.unregister_owner(replace)
        return self.grant_trinket(hero, trinket_id, source=source,
                                  duplicate=True)

    def set_second_slot_trinket(self, hero: Hero, trinket_id: str, *,
                                replace=None, source: str = "second_slot"):
        """第二英雄技能槽变为"某饰品的副本"（RULES §9.5 Crystal Ball 族）。

        官方文本: BG35_Anomaly_007t/008t "When you buy a Lesser/Greater
        Trinket, this transforms into a copy of it." —— 技能槽本身变成
        该饰品的一份副本，因此:
        - 槽位标记 `hero._second_power_id` 改写为该**饰品 id**（槽位仍
          被占用: 不能再获得第二技能，`set_second_hero_power` 会抛错）
        - `hero_power_ids` 只列真正的 HERO_POWER 卡（复制来的饰品不是
          技能，不会被 `use_hero_power` 当作技能误用扣费）
        - 副本实体进入 `hero.trinkets`（Avenge/EoT/开局战斗 等扫描域），
          经 `copy_trinket` 走副本路径（跨局去重豁免 + on_bind 接线）
        """
        if self.db.get(trinket_id) is None:
            raise GameStateError(f"unknown card {trinket_id}")
        if replace is not None:
            if replace in hero.trinkets:
                hero.trinkets.remove(replace)
            self.events.unregister_owner(replace)
        hero._second_power_id = trinket_id
        return self.grant_trinket(hero, trinket_id, source=source,
                                  duplicate=True)

    def grant_random_trinket(self, hero: Hero, kind: str | None = None,
                             source: str = "grant"):
        """随机授予一张**未获得过**的饰品（kind: "lesser"/"greater"）。"""
        school = 11 if kind == "lesser" else 12 if kind == "greater" \
            else None
        pool = [d for d in self.db.trinket_offer_pool()
                if d.id not in hero.trinkets_granted
                and (school is None or d.spell_school == school)]
        if not pool:
            return None
        d = self.rng.choice(pool, label="grant_random_trinket")
        return self.grant_trinket(hero, d.id, source=source)

    def replace_trinket(self, hero: Hero, old, new_id: str) -> None:
        """用新饰品替换 hero 的某张饰品（旧实体移除，新实体 on_bind）。"""
        if old in hero.trinkets:
            hero.trinkets.remove(old)
        self.events.unregister_owner(old)
        return self.grant_trinket(hero, new_id, source="replace")

    def _offer_trinkets(self, hero: Hero, kind: str) -> None:
        """饰品商店: `C.TRINKET_CHOICES`（=4）选 1（+放弃选项）。

        候选 = `db.trinket_offer_pool()`（排除 token 与升级变体）中
        **本档位**的未获得饰品（跨局不重复, RULES §7.4.2）;
        档位由 `spell_school` 表达: lesser=11 / greater=12
        （2026-09-01 审计修复——旧实现忽略 kind，T6 会混入 Greater、
        T9 混入 Lesser）;
        采样等权（官方类型关联权重未公布——Malygos 裁定先例）;
        保证约束（§7.4.2）: ≥1 无类型 + ≥1 费 ≤2。
        """
        # "Your next Trinket is a Lesser Trinket"（Mysterious Orb
        # `BG35_MagicItem_818`）: hero 级覆写读取点，**消费即清**
        forced = getattr(hero, "_next_trinket_kind", None)
        if forced is not None:
            kind = forced
            hero._next_trinket_kind = None
        school = 11 if kind == "lesser" else 12 if kind == "greater" else None
        pool = [d for d in self.db.trinket_offer_pool()
                if d.id not in hero.trinkets_granted
                and (school is None or d.spell_school == school)]
        if not pool:
            return
        assoc = self._type_association(hero)
        # 采样 3 个; 无类型保证
        pick = self.rng.sample(pool, min(C.TRINKET_CHOICES, len(pool)),
                               label="trinket_offer")
        if not any(not self._trinket_subsets(d) for d in pick):
            untyped = [d for d in pool if not self._trinket_subsets(d)]
            if untyped and len(pick) > 1:
                pick[-1] = self.rng.choice(untyped, label="trinket_untyped")
        if not any((d.cost or 0) <= 2 for d in pick):
            cheap = [d for d in pool if (d.cost or 0) <= 2]
            if cheap and len(pick) > 1:
                pick[0] = self.rng.choice(cheap, label="trinket_cheap")

        def resolve(d):
            if d is None:
                return   # 放弃
            if hero.gold < (d.cost or 0):
                return
            if d.cost:
                self.spend_gold(hero, d.cost)
            e = self.create_entity(d.id, controller=hero)
            hero.trinkets.append(e)
            hero.trinkets_granted.add(d.id)
            self._trinkets_granted.add(d.id)
            self.run_on_bind(e, ctx={"hero": hero})
            # 购买事件（RULES §7.4.3——"When you buy a Lesser/Greater
            # Trinket" 类效果的数据源: Crystal Ball 族 / Souvenir Stand）
            self.events.fire(self, "trinket_bought", hero=hero,
                             trinket=e, kind=kind)

        self.pending_choices.append(PendingChoice(
            hero, list(pick) + [None], "trinket_offer",
            resolve_callback=resolve))

    def create_spell(self, card_id: str, *, controller=None) -> Optional[Spell]:
        d = self.db.get(card_id)
        if d is None:
            raise KeyError(f"unknown spell card_id {card_id}")
        s = Spell(d.id, d.name, cost=d.cost)
        s.game = self
        s.controller = controller
        s.init_script_data_from_carddef(d)
        # Lockbox 手牌倒计时实体（初始回合数 = CardDef.num(0) 权威）
        if d.id == C.LOCKBOX_CARD_ID:
            s.set(GameTag.LOCKBOX_TURNS_LEFT,
                  d.num(0) if d.num(0) is not None else C.LOCKBOX_TURNS)
        # 脚本绑定（与 create_minion 同构）
        from hsrl2.scripts import REGISTRY
        s.scripts = REGISTRY.get(s.get(GameTag.CARD_ID))
        # SPELLCRAFT 标记（法术本体带 Spellcraft 关键词的定义）
        if d.dark_gift:
            pass   # Dark Gift 是法术型实体但非 Spellcraft
        self.events.fire(self, "entity_created", entity=s)
        return s

    # ══════════════════ 脚本/动作执行 ══════════════════

    def run_script_hook(self, entity: Entity, hook: str, ctx: Any = None) -> None:
        """执行脚本钩子并把返回的 Action(s) 送入队列解析。

        磁力效果合并 (RULES §6.14 "效果合并"): 宿主触发某钩子时，
        其吸附的磁力随从的**同钩子**效果以宿主为 source 一并触发
        （吸附顺序）。仅对 Minion 实体生效。

        **行动来源作用域**（`game._action_source`）: 钩子执行期间置为
        `entity`（正在施动的实体）——脚本返回的 Action 若未显式声明
        `source`，队列继承该值（`ActionQueue.resolve` 解析顺序），
        `Entity.add_buff` 由此把来源写进 `stats_gained.source`
        （ENGINE_BACKLOG §E D7）。`finally` 恢复外层值（嵌套
        `run_actions` 安全）。
        """
        prev_source = getattr(self, "_action_source", None)
        self._action_source = entity
        try:
            result = entity.call_script(hook, ctx)
            self.run_actions(result)
            if isinstance(entity, Minion):
                for attached_id in self._magnetic_stack.get(entity.uuid, []):
                    from hsrl2.scripts import REGISTRY
                    script_cls = REGISTRY.get(attached_id)
                    if script_cls is None:
                        continue   # 脚本未迁移——效果暂缺（audit 由缺口审计盯）
                    fn = getattr(script_cls, hook, None)
                    if fn is None:
                        continue
                    attached_result = fn(entity, self, ctx)
                    self.run_actions(attached_result)
        finally:
            self._action_source = prev_source
        # "Whenever your <X> **trigger**" 观察点（RULES §7.4.10c）:
        # 钩子实际分发后广播（仅在有监听者时才建 kwargs——热路径开销≈0）
        if self.events._listeners.get("minion_triggered"):
            self.events.fire(self, "minion_triggered", minion=entity,
                             hook=hook, ctx=ctx)

    def run_actions(self, actions) -> None:
        if actions is None:
            return
        if isinstance(actions, Action):
            self.queue.enqueue(actions)
        elif isinstance(actions, (list, tuple)):
            self.queue.enqueue_all(actions)
        self.queue.resolve(self)

    def _update_positions(self, hero: Hero) -> None:
        for i, m in enumerate(hero.board):
            m.set(GameTag.ZONE_POSITION, i)


# ══════════════════ S14 Dark Gift 效果实现 ══════════════════
# 每个 handler: (game, minion, gift_name)。数值出处: data/bg_dark_gifts.json
# （XML 权威; 模板参数缺失时文本即权威）+ 官方 dev post。


def _chain_hook(entity: Entity, hook: str, fn) -> None:
    """在实体既有 hook 行为**之后**追加 fn（官方: gift 是额外效果——
    亡语 gift 明确"原生先触发再追加"; EoT/rally/SoT 顺序未公布，
    按亡语同构处理，AMBIGUOUS）。已有 override 时链式保留。"""
    prev_override = entity._script_overrides.get(hook)
    scripts_fn = (getattr(entity.scripts, hook, None)
                  if entity.scripts is not None else None)

    def chained(source, game, ctx):
        if prev_override is not None:
            result = (prev_override(source, game, ctx)
                      if callable(prev_override) else prev_override)
        elif scripts_fn is not None:
            result = scripts_fn(source, game, ctx)
        else:
            result = None
        fn(source, game, ctx)
        return result

    entity.set_script_override(hook, chained)


def _soc_listener(game: "Game", m: Minion, fn) -> None:
    """注册 SoC 监听（owner=随从，离场自动注销）。

    官方语义: gift 效果与随从自身 SoC 叠加。用事件监听而非
    set_script_override——后者会遮蔽随从原生 SoC 脚本。
    AMBIGUOUS: 与随从原生 SoC 的相对顺序未公布，事件在原生
    SoC 钩子之后广播 → listener 后触发。"""
    game.events.register(Listener(
        event="start_of_combat", owner=m,
        condition=lambda hero=None, **kw: hero is m.controller,
        callback=lambda g, **kw: fn(g),
    ))


def _plain_copy_to_hand(game: "Game", m: Minion, gname: str = "") -> None:
    """plain copy 进手牌（Double Vision / Replication; 不召唤、不占池——
    复制自有随从不消耗池副本）。金色 source → 金色 copy。"""
    hero = m.controller
    if hero is None:
        return
    if m.is_golden:
        base_id = m.get(GameTag.TRIPLE_BASE_CARD_ID, None) or m.card_id
        copy = game.create_minion(base_id, controller=hero, golden=True)
    else:
        copy = game.create_minion(m.card_id, controller=hero)
    game.pending_hand_add(hero, copy)


# ── 纯数值 / 关键词 ──

def _gift_fortitude(game, m, gname):
    # "+5/+5."（XML 文本; 模板参数未导出，文本即权威）
    m.add_buff(Buff(5, 5, dark_gift=gname))


def _gift_harpys_talons(game, m, gname):
    # "Divine Shield, Windfury"
    m.set(GameTag.DIVINE_SHIELD, True)
    m.set(GameTag.WINDFURY, True)


def _gift_toxicity(game, m, gname):
    m.set(GameTag.VENOMOUS, True)          # "Venomous"


def _gift_furtiveness(game, m, gname):
    m.set(GameTag.STEALTH, True)           # "Stealth"


def _gift_tarecgosas_blessing(game, m, gname):
    # "Permanently keeps Bonus Keywords and double stats gained in combat."
    # （XML 文本——对抗审查 BUG-3: gift 是 double，池卡 Tarecgosa 是 1×）
    m.set(PERSIST_TAG, True)
    m.set(GameTag.PERSIST_DOUBLE, True)


def _gift_invulnerability(game, m, gname):
    # "Immune while attacking."（战斗调度器 IMMUNE_WHILE_ATTACKING 已支持）
    m.set(GameTag.IMMUNE_WHILE_ATTACKING, True)


def _gift_gilding(game, m, gname):
    # "This is Golden, but doesn't give a Triple Reward."
    m.set(GameTag.GOLDEN, True)
    m.set(GameTag.GOLDEN_NO_TRIPLE_REWARD, True)
    # 非三连金色: 回池按 1 份（RULES §2.3 Reno 条目同族——Gilding
    # 语义 = Reno 式金色化，2026-08-22 与 GILDED_NOT_TRIPLED 统一）
    m.set(GameTag.GILDED_NOT_TRIPLED, True)
    game._gilded_no_reward_uuids.add(m.uuid)


def _gift_amalgamation(game, m, gname):
    m.set(GameTag.RACE, Race.ALL)          # "Has all minion types."


def _gift_toreths_blessing(game, m, gname):
    # "This minion's Divine Shield takes 3 hits to break."（XML 文本）
    m.set(GameTag.DIVINE_SHIELD_HITS, 3)


def _gift_titanic_strength(game, m, gname):
    m.add_buff(Buff(1000, 0, dark_gift=gname))   # "+1000 Attack."（XML 文本）


def _gift_persisting_horror(game, m, gname):
    # "Reborn. Is Reborn with full stats and Bonus Keywords."
    # 关键词保留是复生默认语义; 满血由 _process_single_death 消费
    # _reborn_full_uuids 实现（一次性）
    m.set(GameTag.REBORN, True)
    game._reborn_full_uuids.add(m.uuid)


def _gift_sunken_persistence(game, m, gname):
    # "This minion's Spellcrafts are permanent."
    # 脚本层契约: 该随从生成的 Spellcraft 法术设 spellcraft_source_uuid
    game._permanent_spellcraft_uuids.add(m.uuid)


# ── 回合驱动（EoT / SoT 监听）──

def _gift_steady_growth(game, m, gname):
    # "At the end of your turn, gain +{1}/+{2}." — XML 模板参数为空，
    # 数值按获得回合查 STEADY_GROWTH_VALUES（dev post 原文）
    vals = DG.STEADY_GROWTH_VALUES.get(game.turn, (4, 4))

    def eot(source, g, ctx):
        source.add_buff(Buff(vals[0], vals[1], dark_gift=gname))
    _chain_hook(m, "end_of_turn", eot)


def _gift_incubation(game, m, gname):
    # "+4/+4. In 2 turns, double this minion's stats."（XML 文本）
    m.add_buff(Buff(4, 4, dark_gift=gname))
    state = {"turns": 0, "done": False}

    def sot(g, hero=None, **kw):
        if hero is not m.controller or state["done"]:
            return
        state["turns"] += 1
        if state["turns"] >= 2:
            state["done"] = True
            # Evidence: wiki.gg/wiki/Multiply_attribute——HS 通用 double
            # = 当前值基数（血量翻倍同时抬当前与上限，受损差值保留）
            m.add_buff(Buff(m.atk, m.health, dark_gift=gname))
    game.events.register(Listener(event="turn_start", owner=m, callback=sot))


def _gift_replication(game, m, gname):
    # "At the end of every 2 turns, get a plain copy of this."
    # AMBIGUOUS: "every 2 turns" 的对齐点未公布——按获得后第 2 个 EoT 起
    state = {"turns": 0}

    def sot(g, hero=None, **kw):
        if hero is m.controller:
            state["turns"] += 1
    game.events.register(Listener(event="turn_start", owner=m, callback=sot))

    def eot(source, g, ctx):
        if state["turns"] >= 2:
            state["turns"] -= 2
            _plain_copy_to_hand(g, source, gname)
    _chain_hook(m, "end_of_turn", eot)


def _gift_affinity(game, m, gname):
    # "At the end of every 2 turns, get a random minion of this type."
    from hsrl2.actions.discover import GetRandomMinion
    state = {"turns": 0}

    def sot(g, hero=None, **kw):
        if hero is m.controller:
            state["turns"] += 1
    game.events.register(Listener(event="turn_start", owner=m, callback=sot))

    def eot(source, g, ctx):
        if state["turns"] >= 2:
            state["turns"] -= 2
            g.run_actions(GetRandomMinion(source.controller,
                                          race=source.race))
    _chain_hook(m, "end_of_turn", eot)


def _gift_time_turning(game, m, gname):
    # "This minion's end of turn effects also trigger at start of turn."
    def sot(source, g, ctx):
        g.run_script_hook(source, "end_of_turn")
    _chain_hook(m, "start_of_turn", sot)


def _gift_echoing_voice(game, m, gname):
    # "At the end of your turn, trigger this minion's Battlecries."
    def eot(source, g, ctx):
        hero = source.controller
        if hero is None or source.zone != Zone.PLAY or source.dead:
            return
        # 触发次数与 play_minion 同构: 金色×2、Brann 类×2
        times = 1
        if source.is_golden:
            times *= 2
        if any(x.has(GameTag.BATTLECRY_DOUBLER) for x in hero.board):
            times *= 2
        for _ in range(times):
            g.run_script_hook(source, "battlecry")
            if g.has_battlecry(source):
                hero.set(GameTag.COUNTER_BATTLECRIES,
                         hero.get(GameTag.COUNTER_BATTLECRIES, 0) + 1)
                g.events.fire(g, "battlecry_trigger", minion=source)
    _chain_hook(m, "end_of_turn", eot)


# ── 战斗开始（SoC 监听）──

def _gift_transcendence(game, m, gname):
    # "Start of Combat: Triple this minion's stats."
    def fn(g):
        m.add_buff(Buff(2 * m.atk, 2 * m.health, dark_gift=gname))
    _soc_listener(game, m, fn)


def _gift_resistance(game, m, gname):
    # "Start of Combat: Double this minion's Health."
    def fn(g):
        m.add_buff(Buff(0, m.health, dark_gift=gname))
    _soc_listener(game, m, fn)


def _gift_hostility(game, m, gname):
    # "Start of Combat: Double this minion's Attack."
    def fn(g):
        m.add_buff(Buff(m.atk, 0, dark_gift=gname))
    _soc_listener(game, m, fn)


def _gift_admiration(game, m, gname):
    # "Start of Combat: Gain the Attack of the minion to the left."
    def fn(g):
        hero = m.controller
        if hero is None or m not in hero.board:
            return
        idx = hero.board.index(m)
        if idx > 0:
            left = hero.board[idx - 1]
            if not left.dead:
                m.add_buff(Buff(left.atk, 0, dark_gift=gname))
    _soc_listener(game, m, fn)


def _gift_jaws_of_death(game, m, gname):
    # "Start of Combat: Trigger this minion's Deathrattles."
    # AMBIGUOUS: 此触发是否计入 COUNTER_DEATHRATTLES 未公布——当前不计
    def fn(g):
        g.run_script_hook(m, "deathrattle")
    _soc_listener(game, m, fn)


# ── 动态计数（Battle Scars / Death's Embrace / Spell Siphon）──

def _make_counter_gift(per_atk: int, per_health: int, counter_tag: GameTag,
                       event_name: str, ctx_key: str):
    """计数型动态属性: 施加时按既有计数补齐，之后每次对应触发 +per。

    初始补齐 + 事件增量等价于 "Has +X/+X for each ... triggered this game"
    的动态读数（事件源按 controller 归属过滤）。"""
    def handler(game, m, gname):
        hero = m.controller
        n0 = hero.get(counter_tag, 0) if hero is not None else 0
        for _ in range(n0):
            m.add_buff(Buff(per_atk, per_health, dark_gift=gname))

        def cb(g, **kw):
            src = kw.get(ctx_key)
            if src is None or src.controller is not m.controller:
                return
            m.add_buff(Buff(per_atk, per_health, dark_gift=gname))
        game.events.register(Listener(event=event_name, owner=m,
                                      callback=cb))
    return handler


# ── 打牌触发（Dexterity / Sharpened Sword / Toughened Shield）──

def _make_card_played_gift(atk: int, health: int):
    """"Whenever you play a card, gain +X/+Y"——仅在棋盘上生效。"""
    def handler(game, m, gname):
        def cb(g, card=None, **kw):
            if m.zone != Zone.PLAY or m.dead:
                return
            if card is None or card.controller is not m.controller:
                return
            m.add_buff(Buff(atk, health, dark_gift=gname))
        game.events.register(Listener(event="card_played", owner=m,
                                      callback=cb))
    return handler


# ── 亡语追加（gift 亡语 = 额外亡语，原生先触发）──

def _gift_mystic_essence(game, m, gname):
    # "Deathrattle: Get a random Tavern spell."
    def dr(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        cands = g.tavern_spell_candidates(min_tier=1,
                                          max_tier=hero.tavern_tier,
                                          pool_aware=False)
        if not cands:
            cands = g.tavern_spell_candidates(pool_aware=False)
        # AMBIGUOUS: tier 范围未公布——按 ≤ 当前酒馆等级（与
        # SpellPool.draw_tavern 一致），空则全池; 统一入口同时施加
        # 存在档白名单（异变 101/102 非存在档法术不可达）
        available = [cid for cid in cands
                     if g.spell_pool.available(cid) > 0]
        if available:
            sid = g.rng.choice(available, label="mystic_essence_spell")
            if not g.spell_pool.acquire(sid):
                raise GameStateError(
                    f"mystic essence acquire failed for {sid}")
        else:
            sid = g.rng.choice(cands, label="mystic_essence_spell")
            # 池空: 生成不占池（作业单约定）
        g.pending_hand_add(hero, g.create_spell(sid, controller=hero))
    _chain_hook(m, "deathrattle", dr)


def _gift_fresh_perspective(game, m, gname):
    # "Deathrattle: Gain 2 free Refreshes."（XML 文本 "2"）
    def dr(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        hero.set(GameTag.FREE_REFRESH_REMAINING,
                 hero.get(GameTag.FREE_REFRESH_REMAINING, 0) + 2)
    _chain_hook(m, "deathrattle", dr)


def _gift_golemancy(game, m, gname):
    # "Deathrattle: Summon a Golem with this minion's stats."
    def dr(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        # AMBIGUOUS: data 导出无独立 "Golem" token 卡——按官方语义构造
        # 同属性 Golem（atk/max_health 快照），T1 token 不占池不回池
        golem = Minion("BG36_GOLEM_TOKEN", "Golem",
                       atk=source.atk, health=source.max_health,
                       tech_level=C.TOKEN_TECH_LEVEL)
        golem.game = g
        g.summon(hero, golem, position=source.zone_position)
    _chain_hook(m, "deathrattle", dr)


def _gift_offensive_sacrifice(game, m, gname):
    # "+10 Attack. Deathrattle: Give this minion's Attack to another
    #  friendly minion."（XML 文本 "+10 Attack"）
    m.add_buff(Buff(10, 0, dark_gift=gname))

    def dr(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        others = [x for x in hero.board if x is not source and not x.dead]
        if not others:
            return
        target = g.rng.choice(others, label="offensive_sacrifice_target")
        target.add_buff(Buff(source.atk, 0, dark_gift=gname))
    _chain_hook(m, "deathrattle", dr)


def _gift_defensive_sacrifice(game, m, gname):
    # "+10 Health. Deathrattle: Give this minion's max Health to another
    #  friendly minion."（XML 文本 "+10 Health"）
    m.add_buff(Buff(0, 10, dark_gift=gname))

    def dr(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        others = [x for x in hero.board if x is not source and not x.dead]
        if not others:
            return
        target = g.rng.choice(others, label="defensive_sacrifice_target")
        target.add_buff(Buff(0, source.max_health, dark_gift=gname))
    _chain_hook(m, "deathrattle", dr)


# ── Rally 追加（原生 rally 先触发）──

def _gift_charisma(game, m, gname):
    # "Rally: Get a random minion of your most common type."
    from hsrl2.actions.discover import GetRandomMinion

    def rally(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        common = DG.most_common_board_race(hero, g.rng)
        if common is None:
            return
        g.run_actions(GetRandomMinion(hero, race=common))
    _chain_hook(m, "rally", rally)


def _gift_consanguinity(game, m, gname):
    # "Rally: Get 2 Blood Gems." — Blood Gem = BG20_GEM（data 已验证，
    # 非池卡不占池）
    def rally(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        for _ in range(2):   # XML 文本 "2"
            g.pending_hand_add(hero, g.create_spell("BG20_GEM",
                                                    controller=hero))
    _chain_hook(m, "rally", rally)


def _gift_demonology(game, m, gname):
    # "Rally: Add a Fodder to your next 3 Refreshes."（XML 文本 "3"）
    # Fodder = Demon Fodder token（BG35_150t），refresh_tavern 消费
    def rally(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        # 协议 v2: (剩余刷新次数, 每次附加枚数)——同英雄多来源时
        # 次数累加、每次枚数取最大（保守合并; 无堆叠官方数据 AMBIGUOUS）
        prev = g._fodder_refresh_pending.get(hero, (0, 0))
        g._fodder_refresh_pending[hero] = (
            prev[0] + C.FODDER_REFRESHES, max(prev[1], 1))
    _chain_hook(m, "rally", rally)


# ── 直接获取 ──

def _gift_double_vision(game, m, gname):
    # "Get an extra copy of this." — plain copy 进手牌（不召唤）
    _plain_copy_to_hand(game, m, gname)


_DARK_GIFT_EFFECTS = {
    DG.OFFENSIVE_SACRIFICE: _gift_offensive_sacrifice,
    DG.DEFENSIVE_SACRIFICE: _gift_defensive_sacrifice,
    DG.ECHOING_VOICE: _gift_echoing_voice,
    DG.DOUBLE_VISION: _gift_double_vision,
    DG.PERSISTING_HORROR: _gift_persisting_horror,
    DG.HARPYS_TALONS: _gift_harpys_talons,
    DG.GILDING: _gift_gilding,
    DG.TORETHS_BLESSING: _gift_toreths_blessing,
    DG.JAWS_OF_DEATH: _gift_jaws_of_death,
    DG.REPLICATION: _gift_replication,
    DG.TIME_TURNING: _gift_time_turning,
    DG.AMALGAMATION: _gift_amalgamation,
    DG.BATTLE_SCARS_BIG: _make_counter_gift(3, 3, GameTag.COUNTER_BATTLECRIES,
                                            "battlecry_trigger", "minion"),
    DG.BATTLE_SCARS_SMALL: _make_counter_gift(2, 2, GameTag.COUNTER_BATTLECRIES,
                                              "battlecry_trigger", "minion"),
    DG.DEATHS_EMBRACE_BIG: _make_counter_gift(2, 2, GameTag.COUNTER_DEATHRATTLES,
                                              "deathrattle_trigger", "minion"),
    DG.DEATHS_EMBRACE_SMALL: _make_counter_gift(1, 1, GameTag.COUNTER_DEATHRATTLES,
                                                "deathrattle_trigger", "minion"),
    DG.SPELL_SIPHON_BIG: _make_counter_gift(3, 3, GameTag.TAVERN_SPELLS_CAST_THIS_GAME,
                                            "tavern_spell_cast", "spell"),
    DG.SPELL_SIPHON_SMALL: _make_counter_gift(2, 2, GameTag.TAVERN_SPELLS_CAST_THIS_GAME,
                                              "tavern_spell_cast", "spell"),
    DG.CHARISMA: _gift_charisma,
    DG.INCUBATION: _gift_incubation,
    DG.MYSTIC_ESSENCE: _gift_mystic_essence,
    DG.TARECGOSAS_BLESSING: _gift_tarecgosas_blessing,
    DG.STEADY_GROWTH: _gift_steady_growth,
    DG.FRESH_PERSPECTIVE: _gift_fresh_perspective,
    DG.INVULNERABILITY: _gift_invulnerability,
    DG.GOLEMANCY: _gift_golemancy,
    DG.SUNKEN_PERSISTENCE: _gift_sunken_persistence,
    DG.DEXTERITY_SMALL: _make_card_played_gift(2, 2),
    DG.DEXTERITY_BIG: _make_card_played_gift(4, 4),
    DG.DEMONOLOGY: _gift_demonology,
    DG.TOXICITY: _gift_toxicity,
    DG.RESISTANCE: _gift_resistance,
    DG.HOSTILITY: _gift_hostility,
    DG.TITANIC_STRENGTH: _gift_titanic_strength,
    DG.FORTITUDE: _gift_fortitude,
    DG.SHARPENED_SWORD: _make_card_played_gift(3, 0),
    DG.TOUGHENED_SHIELD: _make_card_played_gift(0, 3),
    DG.FURTIVENESS: _gift_furtiveness,
    DG.CONSANGUINITY: _gift_consanguinity,
    DG.TRANSCENDENCE: _gift_transcendence,
    DG.AFFINITY: _gift_affinity,
    DG.ADMIRATION: _gift_admiration,
}
# 分派表必须覆盖窗口表全部非 DEFERRED gift——缺失即引擎 bug，禁止静默
_missing = (set(DG.GIFT_WINDOWS) - set(DG.DEFERRED_GIFTS)
            - set(_DARK_GIFT_EFFECTS))
assert not _missing, f"dark gift handlers missing: {_missing}"


_KEYWORD_TAG_MAP = {
    "taunt": GameTag.TAUNT,
    "divine_shield": GameTag.DIVINE_SHIELD,
    "windfury": GameTag.WINDFURY,
    "poisonous": GameTag.POISONOUS,
    "venomous": GameTag.VENOMOUS,
    "reborn": GameTag.REBORN,
    "deathrattle": GameTag.DEATHRATTLE,
    "battlecry": GameTag.BATTLECRY,
    "cleave": GameTag.CLEAVE,
    "magnetic": GameTag.MAGNETIC,
    "start_of_combat": GameTag.START_OF_COMBAT,
    "rally": GameTag.RALLY,
    "activate": GameTag.ACTIVATE,
    "stealth": GameTag.STEALTH,
}
