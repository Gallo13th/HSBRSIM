"""环境层接口契约（唯一权威）。

本文件只依赖标准库，**不导入引擎**。环境、策略、训练、评测三方均以本
文件的数据结构为准；任何字段增删必须先改这里并同步 ``docs/ENV_SPEC.md``。

设计要点
--------
1. **实体中心观测**：棋盘/手牌/酒馆/饰品等按"槽位"序列化为定长实体 token
   列表 + 全局标量。策略侧无需理解引擎对象。
2. **候选动作集**：每一步不暴露固定动作空间，而暴露"合法候选动作"列表
   （通常 0~64 个）。策略对每个候选打分并做 masked argmax，天然适配
   动态棋盘与目标选择（战吼目标、磁力吸附、发现三选一等）。
3. **选择即动作**：引擎的 ``PendingChoice``（发现/三选一/任务/饰品）在
   智能体侧表现为 ``phase="choice"`` 的观测，候选动作仅有 ``choose``。
4. **零引擎依赖**：本模块可被 torch 训练进程、多进程 worker、离线回放
   工具同时导入。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ══════════════════════════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════════════════════════

#: 观测中各类槽位的最大数量（不足补 mask，超出截断并记录）
BOARD_MAX = 7
HAND_MAX = 10
TAVERN_MAX = 7
TRINKET_MAX = 2
OPPONENT_BOARD_MAX = 7
CHOICE_OPTION_MAX = 5
#: 每步候选动作上限（策略侧按此 padding）
CANDIDATE_MAX = 64
#: 最大可能玩家数（8 人酒馆）
PLAYER_MAX = 8

#: 实体所属区域
ZONE_BOARD = "board"
ZONE_HAND = "hand"
ZONE_TAVERN = "tavern"
ZONE_TRINKET = "trinket"
ZONE_QUEST = "quest"
ZONE_POWER = "power"
ZONE_OPPONENT = "opponent"   # 对手战团（可见部分）
ZONE_CHOICE = "choice"       # 发现/三选一选项
ZONE_NONE = ""
ENTITY_ZONES: Tuple[str, ...] = (
    ZONE_BOARD, ZONE_HAND, ZONE_TAVERN, ZONE_TRINKET,
    ZONE_QUEST, ZONE_POWER, ZONE_OPPONENT, ZONE_CHOICE,
)

#: 卡牌类型（字符串而非引擎枚举，保证跨进程稳定）
CARD_TYPE_MINION = "minion"
CARD_TYPE_SPELL = "spell"
CARD_TYPE_HERO = "hero"
CARD_TYPE_HERO_POWER = "hero_power"
CARD_TYPE_TRINKET = "trinket"
CARD_TYPE_QUEST = "quest"
CARD_TYPE_REWARD = "reward"
CARD_TYPE_ANOMALY = "anomaly"
CARD_TYPE_UNKNOWN = "unknown"


class ActionKind(str, enum.Enum):
    """候选动作类型。

    引擎调用映射见 ``hsbg/env/actions.py``。
    """

    BUY = "buy"                       # 从酒馆购买 -> 手牌
    SELL = "sell"                     # 出售棋盘随从
    PLAY_MINION = "play_minion"       # 从手牌打出随从
    PLAY_SPELL = "play_spell"         # 从手牌施放法术
    REROLL = "reroll"                 # 刷新酒馆
    UPGRADE = "upgrade"               # 升级酒馆
    FREEZE = "freeze"                 # 冻结/解冻酒馆
    HERO_POWER = "hero_power"         # 使用英雄技能（可带目标）
    ACTIVATE = "activate"             # 使用随从的 Activate 技能
    USE_DARK_GIFT = "use_dark_gift"   # S14 黑暗赠礼三选一
    END_TURN = "end_turn"             # 结束招募阶段（进入战斗）
    CHOOSE = "choose"                 # 结算 PendingChoice（option 下标）

    def __str__(self) -> str:  # pragma: no cover - 便于日志
        return self.value


#: 稳定动作类型索引（策略输入特征用，禁止重排）
ACTION_KIND_INDEX: Dict[str, int] = {
    k.value: i for i, k in enumerate(ActionKind)
}
NUM_ACTION_KINDS = len(ACTION_KIND_INDEX)

#: 稳定关键词索引（策略输入特征用，禁止重排；未知关键词走 OTHER）
KEYWORDS: Tuple[str, ...] = (
    "taunt", "divine_shield", "poisonous", "venomous", "reborn",
    "windfury", "mega_windfury", "cleave", "deathrattle", "battlecry",
    "start_of_combat", "rally", "avenge", "magnetic", "spellcraft",
    "activate", "stealth", "choose_one", "frenzy", "other",
)
KEYWORD_INDEX: Dict[str, int] = {k: i for i, k in enumerate(KEYWORDS)}
NUM_KEYWORDS = len(KEYWORDS)

#: 标准 10 种族（含 "all"/"none" 兜底位）
RACES: Tuple[str, ...] = (
    "beast", "demon", "dragon", "elemental", "mech",
    "murloc", "naga", "pirate", "quilboar", "undead",
    "all", "none",
)
RACE_INDEX: Dict[str, int] = {r: i for i, r in enumerate(RACES)}
NUM_RACES = len(RACES)

#: 游戏阶段
PHASE_RECRUIT = "recruit"
PHASE_CHOICE = "choice"
PHASE_GAME_OVER = "game_over"


# ══════════════════════════════════════════════════════════════════════
# 观测数据结构
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EntityToken:
    """一个游戏实体的观测快照（策略侧最小充分信息）。

    ``card_id`` 保留引擎原始 id（策略侧自行维护 vocab）。数值均已归一化
    前的整数，由策略侧做缩放。
    """

    card_id: str
    card_type: str = CARD_TYPE_MINION
    zone: str = ZONE_NONE
    slot: int = -1
    atk: int = 0
    health: int = 0
    tier: int = 0
    cost: int = 0
    races: Tuple[str, ...] = ()
    keywords: Tuple[str, ...] = ()
    golden: bool = False
    #: 引擎实体 uuid（同一局内稳定，仅用于调试/一致性校验）
    entity_id: int = 0
    #: 原始名称/文本（仅调试与日志，策略不得依赖）
    name: str = ""

    def keyword_bits(self) -> Tuple[int, ...]:
        bits = [0] * NUM_KEYWORDS
        for k in self.keywords:
            idx = KEYWORD_INDEX.get(k, KEYWORD_INDEX["other"])
            bits[idx] = 1
        return tuple(bits)

    def race_bits(self) -> Tuple[int, ...]:
        bits = [0] * NUM_RACES
        if not self.races:
            bits[RACE_INDEX["none"]] = 1
            return tuple(bits)
        for r in self.races:
            bits[RACE_INDEX.get(r, RACE_INDEX["none"])] = 1
        return tuple(bits)


@dataclass(frozen=True)
class HeroToken:
    """智能体英雄自身状态。"""

    hero_id: str
    health: int
    armor: int
    tier: int
    gold: int
    upgrade_cost: int
    power_id: str = ""
    power_cost: int = 0
    power_usable: bool = False
    #: 本回合是否还可使用 Activate
    tavern_tier_max: int = 6


@dataclass(frozen=True)
class LobbyPlayer:
    """大厅内一名玩家（对手信息为可见近似：血量/等级/存活/名次）。"""

    name: str
    health: int
    armor: int
    tier: int
    alive: bool
    is_agent: bool = False
    eliminated_rank: int = 0   # 0 = 未淘汰；1 = 冠军


@dataclass(frozen=True)
class PendingChoice:
    """引擎 PendingChoice 的观测表示。"""

    kind: str
    options: Tuple[EntityToken, ...]
    #: 是否为智能体必须亲自做出的选择（否则已由环境自动结算）
    for_agent: bool = True
    prompt: str = ""


@dataclass(frozen=True)
class CandidateAction:
    """一个合法候选动作。

    引用约定：``src_zone/src_slot`` / ``tgt_zone/tgt_slot`` 指向**当前观测**
    中同一 zone 的槽位下标（见 ``Observation`` 的各列表）。
    """

    kind: str
    src_zone: str = ZONE_NONE
    src_slot: int = -1
    tgt_zone: str = ZONE_NONE
    tgt_slot: int = -1
    #: 打出随从时的棋盘插入位置（0..len(board)）；-1 = 追加到最右
    position: int = -1
    #: choose 动作的选项下标
    option: int = -1
    #: 该动作的显式金币费用（用于特征；-1 = 未知/不适用）
    cost: int = -1

    def signature(self) -> Tuple[Any, ...]:
        return (self.kind, self.src_zone, self.src_slot,
                self.tgt_zone, self.tgt_slot, self.position, self.option)

    @property
    def kind_index(self) -> int:
        return ACTION_KIND_INDEX.get(self.kind, 0)


@dataclass
class Observation:
    """一步决策所需的完整观测。

    版本历史：
    * v1（初始）：实体槽 + 全局标量 + 候选。
    * v2（2026-10-18）：新增 ``extra`` —— 决策相关但非实体槽位的状态
      （酒馆冻结、技能剩余次数、任务进度、暗黑赠礼、对手身份、淘汰顺序、
      最近战斗结果等）。来源与 ``env.extra_state()`` 同源；键集合稳定，
      训练侧可选择性编码。`extra` 必须可 pickle，禁止放引擎对象。
    """

    #: 协议版本，跨进程缓存/checkpoint 兼容性检查用
    version: int = 2
    turn: int = 0
    phase: str = PHASE_RECRUIT
    #: 智能体英雄
    hero: Optional[HeroToken] = None
    #: 各区域实体（已按槽位排序）
    board: Tuple[EntityToken, ...] = ()
    hand: Tuple[EntityToken, ...] = ()
    tavern: Tuple[EntityToken, ...] = ()
    trinkets: Tuple[EntityToken, ...] = ()
    quest: Optional[EntityToken] = None
    #: 上一场对手的战团（官方可见信息）
    opponent_board: Tuple[EntityToken, ...] = ()
    #: 大厅
    lobby: Tuple[LobbyPlayer, ...] = ()
    alive_count: int = 0
    total_players: int = 0
    #: 当前名次（1 = 第一；存活时按血量估算的并列名次）
    rank: int = 0
    #: 待结算选择（phase == "choice" 时非空）
    pending_choice: Optional[PendingChoice] = None
    #: 本步合法候选动作（按此顺序输出动作下标）
    candidates: Tuple[CandidateAction, ...] = ()
    #: 额外决策状态（v2）：见类文档；纯数据（可 pickle），只读约定。
    #: 常用键：frozen_tavern(bool)、power_uses_left(dict)、second_power_id、
    #: quest_progress(int)、dark_gift_uses_left(int)、next_opponent(str|None)、
    #: last_opponent(str|None)、elimination_order(list[str])、
    #: last_combat(dict)、pending_hand_queue(int)、minion_flags(dict) 等。
    extra: Dict[str, Any] = field(default_factory=dict)
    #: 自由文本日志（调试）
    log: str = ""

    def get_extra(self, key: str, default: Any = None) -> Any:
        """读取 ``extra`` 字段（缺失返回 default）。"""
        return self.extra.get(key, default)

    # ── 便捷访问 ──
    def num_candidates(self) -> int:
        return len(self.candidates)

    def slots(self, zone: str) -> Tuple[EntityToken, ...]:
        return {
            ZONE_BOARD: self.board,
            ZONE_HAND: self.hand,
            ZONE_TAVERN: self.tavern,
            ZONE_TRINKET: self.trinkets,
            ZONE_OPPONENT: self.opponent_board,
        }.get(zone, ())

    def entity_at(self, zone: str, slot: int) -> Optional[EntityToken]:
        arr = self.slots(zone)
        if 0 <= slot < len(arr):
            return arr[slot]
        return None


@dataclass
class StepResult:
    """``env.step`` 的返回值（显式字段，避免 gym 依赖）。"""

    observation: Observation
    reward: float = 0.0
    terminated: bool = False
    truncated: bool = False
    info: Dict[str, Any] = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════
# 奖励配置
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RewardConfig:
    """奖励项权重（全部可配，默认值对齐"名次为主、场面为辅"）。

    終局奖励按名次线性映射::
        rank_reward = 1 - 2 * (rank - 1) / (num_players - 1)
    第 1 名 = +1，最后一名 = -1。
    """

    #: 终局名次奖励权重
    placement: float = 1.0
    #: 每回合英雄生命变化（受伤为负）
    health_delta: float = 0.02
    #: 每回合战斗造成的净伤害（对敌伤害 - 自身承伤），按 1/10 缩放
    combat_damage: float = 0.01
    #: 每回合棋盘战力（atk+health 总和）变化，按 1/50 缩放
    board_power_delta: float = 0.001
    #: 回合结束存活奖励（避免早死）
    survival: float = 0.0
    #: 无效动作/非法动作惩罚（环境侧防御性）
    invalid_action: float = -0.05
    #: 超时截断惩罚
    timeout: float = -0.5
    #: 每步固定时间惩罚（抑制拖延，默认 0）
    step_penalty: float = 0.0

    #: 是否启用奖励归一化（训练侧按折扣回报标准化）
    clip: float = 10.0


# ══════════════════════════════════════════════════════════════════════
# 环境配置
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EnvConfig:
    """环境构造配置（``BattlegroundsEnv(**asdict(cfg))`` 可直接展开）。"""

    num_players: int = 8
    #: 智能体控制的英雄下标（0 固定为智能体）
    agent_index: int = 0
    #: 对手策略名（见 hsbg.agents.registry）
    opponent: str = "heuristic"
    #: 智能体英雄 id（None = 随机）
    hero_id: Optional[str] = None
    #: 本局异变 id（None = 无异变）
    anomaly: Optional[str] = None
    #: 最大回合数（超过则 truncate）
    max_turns: int = 40
    #: 单局最大决策步数（防死循环）
    max_steps: int = 4000
    #: 自动结算智能体 PendingChoice 的启发式（None = 暴露给策略）
    auto_choice: bool = False
    #: 每回合动作预算：达到后候选只保留 end_turn（防 freeze/无进展动作无限循环；
    #: 正常对局每回合 ≤30 动作，40 足够宽松）。0/负数不允许。
    max_actions_per_turn: int = 40
    #: 单局最大决策步数（防死循环）
    max_steps: int = 4000
    #: 固定种子（None = 每次 reset 随机）
    seed: Optional[int] = None
    reward: RewardConfig = field(default_factory=RewardConfig)


#: 默认环境（8 人、启发式对手）
DEFAULT_ENV_CONFIG = EnvConfig()


# ══════════════════════════════════════════════════════════════════════
# 观测编码尺寸（策略侧使用；改这里必须同步 checkpoint 版本）
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ObsDims:
    """观测张量的逻辑尺寸（策略网络按此构建 embedding 表）。"""

    num_card_types: int = 8
    num_zones: int = len(ENTITY_ZONES)
    num_races: int = NUM_RACES
    num_keywords: int = NUM_KEYWORDS
    num_action_kinds: int = NUM_ACTION_KINDS
    board_max: int = BOARD_MAX
    hand_max: int = HAND_MAX
    tavern_max: int = TAVERN_MAX
    trinket_max: int = TRINKET_MAX
    opponent_max: int = OPPONENT_BOARD_MAX
    candidate_max: int = CANDIDATE_MAX
    #: 每实体 token 的数值特征维度：[atk, health, tier, cost, golden,
    #:                                   slot, card_type_onehot..., zone_onehot...]
    entity_num_dim: int = 32
    #: 全局标量维度：[turn, gold, tier, health, armor, upgrade_cost,
    #:                alive, total, rank, board_power, hand_size, ...]
    global_dim: int = 32


OBS_DIMS = ObsDims()
