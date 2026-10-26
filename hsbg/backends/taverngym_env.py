"""TavernGym 后端适配器：AutoTavern 的 Rust 引擎 → HSBRSIM ``EnvLike`` 契约。

背景
----
`AutoTavern <https://github.com/>`_ 项目用 Rust 实现了一套酒馆战棋模拟器，
并以 ``taverngym``（abi3 wheel, Rust 1.98 + PyO3）暴露 Python 接口：

* 游戏数据版本 **36.6.3.253932**（HSBRSIM 基线是 **37.0.0.255130**，两者不同）；
* 动作空间固定 **245 维**（``N_ACTIONS=245``）+ 精确 legal mask；
* 官方 RL 观测是定长向量（``features`` 3227 f32 + ``cards`` 124 i32），
  另有调试用 ``Game.view(seat)`` JSON（含卡牌 id/名称/全文/战斗回放）；
* 单座环境 ``BattlegroundsEnv`` 与 ``SoloEnv``；多局并行 ``BatchEnv``；
* 精确存档 ``Game.state_json()`` / ``Game.from_json()``。

本模块把 ``taverngym.Game`` 包装成 HSBRSIM 的 :class:`hsbg.rl.api.EnvLike`：

* ``reset(seed) -> Observation``；``step(action) -> (obs, reward, terminated,
  truncated, info)``；``close()``；
* 观测使用 ``hsbg.env.spec`` 的实体 token 契约（``Observation.version`` 沿用
  spec 当前值，不修改 spec）；
* 候选动作由精确 mask 映射为 ``CandidateAction``（"固定动作空间 + 精确掩码"
  的参照实现）；``extra["taverngym"]["flat_action_indices"]`` 给出候选下标 →
  TavernGym 扁平动作下标的对应关系；
* ``info`` 含 ``rank / invalid / backend``，并附带 245 维原始 mask 与动作下标；
* ``save_state()`` / ``load_state()`` 基于 ``Game.state_json()/from_json()``，
  可精确恢复对局与适配器计数。

两种观测源（``obs_source``）
---------------------------
``"features"``（默认，推荐）
    用官方 RL 观测 ``Game.observe(seat)``（3227 floats + 124 card indices）。
    **只含公开信息**（POMDP 干净）、单次约 2~6 µs，适合基准/采集。
    由本模块按 ``taverngym.obs`` 布局逐位解码成实体 token。限制：没有实体
    uuid（``EntityToken.entity_id`` 恒 0）、没有战斗回放细节、pending
    ``target`` 选项拿不到目标实体 id（只能拿到卡牌 id 或空）。
``"view"``
    用 ``Game.view(seat)`` JSON（调试视图）。字段最全（实体 uuid、卡牌中英文
    名、英雄选择护甲、pending 目标的 eid、上一场战斗摘要），但单次约 3~12 ms
    （含战斗回放序列化），只建议做对照验证/可视化，不建议跑大批量。
    注意：``view()`` 本身含**隐藏信息**（对手当前棋盘、他人手牌数），本适配器
    **只取公开字段**（``seen_board``/大厅标量/本方状态），不会把隐藏信息放进
    观测；但该 JSON 的构造开销与"调试视图"定位需要读者知悉。

与 hsrl2 后端的已知差异（详见 ``docs/TAVERNGYM_BACKEND.md``）
-----------------------------------------------------------
1. 游戏数据 36.6.3 vs 37.0.0：卡池/数值/英雄不同，同名卡也可能数值不同；
   策略不能直接迁移（卡牌 id 词表、动作空间、种族集合都不同）。
2. 动作空间：TavernGym 是 245 维固定空集 + mask；HSBRSIM 是动态候选集
   （通常 0~64）。本适配器把 mask 内的动作全部展开成候选，因此
   ``len(obs.candidates)`` 可能 **大于** ``spec.CANDIDATE_MAX=64``（最多 245）；
   训练侧按 ``CANDIDATE_MAX`` padding 的编码器需要截断（会丢动作），所以本
   后端定位为**参照/评测**，不直接用于现有策略训练。
3. 槽位上限：spec 的 ``TAVERN_MAX=7``/``TRINKET_MAX=2``/``CHOICE_OPTION_MAX=5``
   小于 TavernGym 的 ``N_SHOP=8``/饰品上限 8/``N_CHOICE=16``；本适配器**不截断**
   （截断会让候选引用了不存在的槽位），超限槽位只在文档中说明。
4. 阶段/回合：TavernGym 的 ``turn=0`` 是英雄选择阶段；本适配器把
   ``Observation.turn`` 映射为 ``max(1, turn)``（spec 约定 1 起），原始值放在
   ``extra["taverngym"]["turn_raw"]``。
5. 奖励：TavernGym 官方是**稀疏名次奖励**（1st=+1, 8th=-1）+ 非法动作惩罚。
   本适配器用 ``spec.RewardConfig`` 的 ``placement/invalid_action/step_penalty/
   timeout`` 项；``health_delta/combat_damage/board_power_delta`` 等 shaping
   项**未实现**（置 0），需要时由训练侧自行设计（文档已注明）。
6. ``ActionKind`` 里没有 "cancel"（取消目标选择）；TavernGym 有
   ``A_CANCEL``，本适配器用 ``kind="cancel"`` 表示（非 spec 枚举，文档注明）。

线程/进程
--------
``taverngym.Game`` 可在任意进程内创建（PyO3 对象不可跨进程 pickle）；
本适配器的观测是纯数据，可 pickle。多进程采集时遵循 ``hsbg.rl`` 的 spawn 规则。

本模块**只读** ``taverngym`` 的公开 API，不修改 AutoTavern 仓库。
"""

from __future__ import annotations

import json
import operator
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from hsbg.env.spec import (
    ActionKind,
    CANDIDATE_MAX,
    CARD_TYPE_HERO,
    CARD_TYPE_HERO_POWER,
    CARD_TYPE_MINION,
    CARD_TYPE_QUEST,
    CARD_TYPE_REWARD,
    CARD_TYPE_SPELL,
    CARD_TYPE_TRINKET,
    CARD_TYPE_UNKNOWN,
    CandidateAction,
    EntityToken,
    HeroToken,
    LobbyPlayer,
    Observation,
    OBS_DIMS,
    PendingChoice,
    PHASE_CHOICE,
    PHASE_GAME_OVER,
    PHASE_RECRUIT,
    RewardConfig,
    ZONE_BOARD,
    ZONE_CHOICE,
    ZONE_HAND,
    ZONE_NONE,
    ZONE_OPPONENT,
    ZONE_POWER,
    ZONE_QUEST,
    ZONE_TAVERN,
    ZONE_TRINKET,
)

try:  # pragma: no cover - 依赖是否安装由调用方决定
    # 本项目已放弃 hsrl2，主模拟器是 AutoTavern fork 的 Rust ``hsbg_engine``。
    # 保留 taverngym fallback 仅用于读取上游参照实现。
    import hsbg_engine as _tg
except ImportError:  # pragma: no cover
    try:
        import taverngym as _tg
    except ImportError:
        _tg = None

__all__ = [
    "BACKEND_NAME",
    "TavernGymEnv",
    "make_taverngym_env",
    "taverngym_available",
    "TAVERNGYM_INSTALL_HINT",
]

#: 后端名（写进 ``info["backend"]`` / JSONL header）
BACKEND_NAME = "hsbg_engine"

#: 安装提示（``taverngym_available()`` 为 False 时抛出）
TAVERNGYM_INSTALL_HINT = (
    "未安装 taverngym（AutoTavern 的 Rust 引擎扩展）。安装步骤"
    "（macOS / Linux / Windows 通用）：\n"
    "  1) 安装 Rust 工具链（https://rustup.rs）；AutoTavern 的 rust-toolchain.toml\n"
    "     固定 1.98.1，rustup 进入仓库目录会自动装该版本；\n"
    "  2) 在 AutoTavern 仓库根目录执行 `pip install .`（maturin 构建\n"
    "     crates/taverngym-py，产物为 taverngym/_core.abi3.so / .pyd）；\n"
    "  3) 验证：`python -c \"import taverngym; print(taverngym.version())\"`。\n"
    "详见 HSBRSIM docs/TAVERNGYM_BACKEND.md。"
)


# ══════════════════════════════════════════════════════════════════════
# 依赖可用性
# ══════════════════════════════════════════════════════════════════════


def taverngym_available() -> bool:
    """``taverngym`` 是否可导入（pip 包 + 编译好的 native 扩展）。"""
    return _tg is not None


def _require_taverngym() -> Any:
    if _tg is None:  # pragma: no cover - 环境已装好，正常测试不会走到
        raise ImportError(TAVERNGYM_INSTALL_HINT)
    return _tg


# ══════════════════════════════════════════════════════════════════════
# 固定布局：动作空间 / 观测向量（从 taverngym.layout() 推导，不硬编码数字）
# ══════════════════════════════════════════════════════════════════════

#: TavernGym 种族位顺序（``crates/taverngym/src/types.rs::Races::NAMES``）；
#: 观测里 ``MINION`` 的种族 one-hot 与全局 ``lobby_races`` 均按此顺序。
_TG_RACE_NAMES: Tuple[str, ...] = (
    "BEAST", "DEMON", "DRAGON", "ELEMENTAL", "MECHANICAL", "MURLOC",
    "PIRATE", "QUILBOAR", "UNDEAD", "ABERRATION", "NAGA",
)

#: TavernGym 关键词位顺序（``types.rs::Kw::NAMES``）。
_TG_KEYWORD_NAMES: Tuple[str, ...] = (
    "TAUNT", "DIVINE_SHIELD", "WINDFURY", "REBORN", "VENOMOUS", "POISONOUS",
    "STEALTH", "MAGNETIC", "MEGA_WINDFURY", "CLEAVE", "IMMUNE",
    "IMMUNE_ATTACKING",
)

#: TavernGym 种族 → ``hsbg.env.spec.RACES`` 名（ABERRATION 不是 spec 标准种族，
#: 保留原名，``EntityToken.race_bits()`` 会落到 ``none`` 位）。
_RACE_TO_SPEC: Dict[str, str] = {
    "BEAST": "beast", "DEMON": "demon", "DRAGON": "dragon",
    "ELEMENTAL": "elemental", "MECHANICAL": "mech", "MURLOC": "murloc",
    "PIRATE": "pirate", "QUILBOAR": "quilboar", "UNDEAD": "undead",
    "ABERRATION": "aberration", "NAGA": "naga", "ALL": "all",
}

#: TavernGym 关键词 → spec 关键词名（IMMUNE* 不在 spec 词表，统一 ``other``）。
_KEYWORD_TO_SPEC: Dict[str, str] = {
    "TAUNT": "taunt", "DIVINE_SHIELD": "divine_shield", "WINDFURY": "windfury",
    "REBORN": "reborn", "VENOMOUS": "venomous", "POISONOUS": "poisonous",
    "STEALTH": "stealth", "MAGNETIC": "magnetic",
    "MEGA_WINDFURY": "mega_windfury", "CLEAVE": "cleave",
    "IMMUNE": "other", "IMMUNE_ATTACKING": "other",
}

#: ``card_static`` 前 10 列是卡牌种类 one-hot，顺序同 Rust ``CardKind``。
_CARD_KIND_FLAGS: Tuple[str, ...] = (
    "minion", "tavern_spell", "spell", "hero", "hero_power",
    "trinket_lesser", "trinket_greater", "dark_gift", "quest", "quest_reward",
)

#: 卡牌种类 → spec ``card_type``（``dark_gift`` 在 spec 中无对应，置 unknown）。
_CARD_KIND_TO_SPEC: Dict[str, str] = {
    "minion": CARD_TYPE_MINION,
    "tavern_spell": CARD_TYPE_SPELL,
    "spell": CARD_TYPE_SPELL,
    "hero": CARD_TYPE_HERO,
    "hero_power": CARD_TYPE_HERO_POWER,
    "trinket_lesser": CARD_TYPE_TRINKET,
    "trinket_greater": CARD_TYPE_TRINKET,
    "dark_gift": CARD_TYPE_UNKNOWN,
    "quest": CARD_TYPE_QUEST,
    "quest_reward": CARD_TYPE_REWARD,
}

#: ``GLOBAL_F`` 中前 42 个标量的下标（``crates/taverngym/src/obs.rs``）。
G_TURN = 0
G_HERO_SELECT = 1
G_GAME_OVER = 2
G_ALIVE = 3
G_ME_ALIVE = 4
G_HEALTH = 5
G_ARMOR = 6
G_GOLD = 7
G_MAX_GOLD_BONUS = 8
G_GOLD_NEXT = 9
G_TIER = 10
G_UPGRADE_PRICE = 11
G_REFRESH_PRICE = 12
G_MINION_PRICE = 13
G_FREE_REFRESHES = 14
G_FROZEN = 15
G_POWER0_USABLE = 16
G_POWER0_PRICE = 17
G_POWER0_USES_GAME = 18
G_POWER1_USABLE = 19
G_POWER1_PRICE = 20
G_POWER1_USES_GAME = 21
G_CAN_DARK_GIFT = 22
G_DARK_GIFT_USES = 23
G_TRINKETS_LEN = 24
G_DEITY_ATK = 25
G_DEITY_HP = 26
G_WON_LAST = 27
G_LOST_LAST = 28
G_SPELL_ATK = 29
G_SPELL_HP = 30
G_GEM_ATK = 31
G_GEM_HP = 32
G_BOARD_LEN = 33
G_HAND_LEN = 34
G_DEITY_PRESENT = 35
G_HAND_QUEUE = 36
G_NEXT_IS_GHOST = 37
G_TAVERN_ATK = 38
G_TAVERN_HP = 39
G_EFFECTS = 40
G_CHRONUM = 41
G_LOBBIES = 42        # 42..42+RACES_COUNT 是 lobby_races one-hot

#: ``MINION_F`` 内偏移（``push_minion``）。
M_PRESENT = 0
M_ATK = 1
M_HP = 2
M_MAX_HP = 3
M_TIER = 4
M_GOLDEN = 5
M_ATTACHED = 6
M_SHIELD_HITS = 7
M_KEYWORDS = 8
#: 种族位在 ``M_KEYWORDS + KW_COUNT``。

#: ``ITEM_F`` 内偏移（``push_item``）。
I_PRESENT = 0
I_IS_MINION = 1
I_COST = 2
I_LOCKED = 3
I_TEMPORARY = 4
I_COMBINED = 5
I_FROZEN = 6          # hand: doomed this turn
I_KEPT = 7
I_MARKED = 8
I_MINION = 9          # 随从块起点（``I_MINION + MINION_F == ITEM_F``）
I_SPELL_TIER = 13     # 法术：present,minion,cost,lock,temp,comb,frozen,kept,marked,
                      #        1.0, data/6, 0, 0, tier/6, ...
                      # 相对 ITEM_F 起点；见 obs.rs::push_item。

#: pending choice 种类（``PENDING_KINDS=9`` 的 one-hot 顺序）。
_PENDING_KINDS: Tuple[str, ...] = (
    "none", "hero", "discover", "choose_one", "target", "hero_power",
    "trinket", "quest", "timewarp",
)

#: TavernGym pending 种类 → spec ``PendingChoice.kind``（none 不出现）。
_PENDING_TO_SPEC: Dict[str, str] = {
    "hero": "hero",
    "discover": "discover",
    "choose_one": "choose_one",
    "target": "target",
    "hero_power": "hero_power",
    "trinket": "trinket",
    "quest": "quest",
    "timewarp": "timewarp",
}


@dataclass(frozen=True)
class _Layout:
    """TavernGym 动作/观测布局（全部来自 ``taverngym.layout()``，构建时校验）。"""

    # 动作空间
    n_actions: int
    n_board: int
    n_hand: int
    n_shop: int
    n_choice: int
    n_pos: int
    n_powers: int
    a_end: int
    a_refresh: int
    a_freeze: int
    a_upgrade: int
    a_hero_power: int
    a_dark_gift: int
    a_cancel: int
    a_buy: int
    a_sell: int
    a_activate: int
    a_choose: int
    a_play: int
    a_magnetize: int
    a_move: int
    # 观测向量
    minion_f: int
    item_f: int
    global_f: int
    quest_f: int
    n_quests: int
    n_secrets: int
    opp_f: int
    n_opp: int
    pending_kinds: int
    races_count: int
    kw_count: int
    obs_floats: int
    obs_cards: int
    # 浮点块偏移
    off_quests: int
    off_pending: int
    off_board: int
    off_hand: int
    off_shop: int
    off_choices: int
    off_opps: int
    off_opp_boards: int
    # 卡牌块偏移
    c_hero: int
    c_powers: int
    c_deity: int
    c_pending: int
    c_quests: int
    c_secrets: int
    c_board: int
    c_hand: int
    c_shop: int
    c_choices: int
    c_trinkets: int
    c_opp_heroes: int
    c_opp_boards: int

    # ── 便捷 ──
    @property
    def action_kind_widths(self) -> Dict[str, int]:
        return {
            "buy": self.a_sell - self.a_buy,
            "sell": self.a_activate - self.a_sell,
            "activate": self.a_choose - self.a_activate,
            "choose": self.a_play - self.a_choose,
            "play": self.a_magnetize - self.a_play,
            "magnetize": self.a_move - self.a_magnetize,
            "move": self.n_actions - self.a_move,
        }


_LAYOUT_CACHE: Optional[_Layout] = None


def _tg_layout() -> _Layout:
    """构建并校验 TavernGym 布局；版本/构建不匹配时立刻报错（fail fast）。"""
    global _LAYOUT_CACHE
    if _LAYOUT_CACHE is not None:
        return _LAYOUT_CACHE
    tg = _require_taverngym()
    raw: Dict[str, int] = {str(k): int(v) for k, v in tg.layout()}
    need = (
        "N_ACTIONS", "N_SHOP", "N_BOARD", "N_HAND", "N_CHOICE", "N_POS",
        "N_POWERS", "A_END", "A_REFRESH", "A_FREEZE", "A_UPGRADE",
        "A_HERO_POWER", "A_DARK_GIFT", "A_CANCEL", "A_BUY", "A_SELL",
        "A_ACTIVATE", "A_CHOOSE", "A_PLAY", "A_MAGNETIZE", "A_MOVE",
        "MINION_F", "ITEM_F", "GLOBAL_F", "N_QUESTS", "QUEST_F",
        "N_SECRETS", "OPP_F", "N_OPP", "PENDING_KINDS", "OBS_FLOATS",
        "OBS_CARDS",
    )
    missing = [k for k in need if k not in raw]
    if missing:
        raise RuntimeError(f"TavernGym layout 缺少字段 {missing}；引擎版本不兼容")

    global_f = raw["GLOBAL_F"]
    races_count = global_f - G_LOBBIES
    kw_count = raw["MINION_F"] - M_KEYWORDS - races_count
    if races_count != len(_TG_RACE_NAMES):
        raise RuntimeError(
            f"TavernGym 种族位数量 {races_count} != 本适配器表 "
            f"{len(_TG_RACE_NAMES)}；请更新 _TG_RACE_NAMES")
    if kw_count != len(_TG_KEYWORD_NAMES):
        raise RuntimeError(
            f"TavernGym 关键词位数量 {kw_count} != 本适配器表 "
            f"{len(_TG_KEYWORD_NAMES)}；请更新 _TG_KEYWORD_NAMES")

    minion_f = raw["MINION_F"]
    item_f = raw["ITEM_F"]
    quest_f = raw["QUEST_F"]
    opp_f = raw["OPP_F"]
    n_quests = raw["N_QUESTS"]
    n_opp = raw["N_OPP"]
    n_board = raw["N_BOARD"]
    n_hand = raw["N_HAND"]
    n_shop = raw["N_SHOP"]
    n_choice = raw["N_CHOICE"]

    off_quests = global_f
    off_pending = off_quests + n_quests * quest_f
    off_board = off_pending + raw["PENDING_KINDS"]
    off_hand = off_board + n_board * minion_f
    off_shop = off_hand + n_hand * item_f
    off_choices = off_shop + n_shop * item_f
    off_opps = off_choices + n_choice * item_f
    off_opp_boards = off_opps + n_opp * opp_f
    expect_floats = off_opp_boards + n_opp * n_board * minion_f
    if expect_floats != raw["OBS_FLOATS"]:
        raise RuntimeError(
            f"TavernGym 观测浮点布局不匹配：推导 {expect_floats} != "
            f"OBS_FLOATS {raw['OBS_FLOATS']}")

    c_hero = 0
    c_powers = c_hero + 1
    c_deity = c_powers + raw["N_POWERS"]
    c_pending = c_deity + 1
    c_quests = c_pending + 1
    c_secrets = c_quests + 3 * n_quests
    c_board = c_secrets + raw["N_SECRETS"]
    c_hand = c_board + n_board
    c_shop = c_hand + n_hand
    c_choices = c_shop + n_shop
    c_trinkets = c_choices + n_choice
    c_opp_heroes = c_trinkets + 8
    c_opp_boards = c_opp_heroes + n_opp
    expect_cards = c_opp_boards + n_opp * n_board
    if expect_cards != raw["OBS_CARDS"]:
        raise RuntimeError(
            f"TavernGym 观测卡牌布局不匹配：推导 {expect_cards} != "
            f"OBS_CARDS {raw['OBS_CARDS']}")

    lay = _Layout(
        n_actions=raw["N_ACTIONS"], n_board=n_board, n_hand=n_hand,
        n_shop=n_shop, n_choice=n_choice, n_pos=raw["N_POS"],
        n_powers=raw["N_POWERS"],
        a_end=raw["A_END"], a_refresh=raw["A_REFRESH"],
        a_freeze=raw["A_FREEZE"], a_upgrade=raw["A_UPGRADE"],
        a_hero_power=raw["A_HERO_POWER"], a_dark_gift=raw["A_DARK_GIFT"],
        a_cancel=raw["A_CANCEL"], a_buy=raw["A_BUY"], a_sell=raw["A_SELL"],
        a_activate=raw["A_ACTIVATE"], a_choose=raw["A_CHOOSE"],
        a_play=raw["A_PLAY"], a_magnetize=raw["A_MAGNETIZE"],
        a_move=raw["A_MOVE"],
        minion_f=minion_f, item_f=item_f, global_f=global_f,
        quest_f=quest_f, n_quests=n_quests,
        n_secrets=raw["N_SECRETS"], opp_f=opp_f, n_opp=n_opp,
        pending_kinds=raw["PENDING_KINDS"], races_count=races_count,
        kw_count=kw_count, obs_floats=raw["OBS_FLOATS"],
        obs_cards=raw["OBS_CARDS"],
        off_quests=off_quests, off_pending=off_pending, off_board=off_board,
        off_hand=off_hand, off_shop=off_shop, off_choices=off_choices,
        off_opps=off_opps, off_opp_boards=off_opp_boards,
        c_hero=c_hero, c_powers=c_powers, c_deity=c_deity,
        c_pending=c_pending, c_quests=c_quests, c_secrets=c_secrets,
        c_board=c_board, c_hand=c_hand, c_shop=c_shop, c_choices=c_choices,
        c_trinkets=c_trinkets, c_opp_heroes=c_opp_heroes,
        c_opp_boards=c_opp_boards,
    )
    # 动作区间宽度自检（对照 crates/taverngym/src/actions.rs）
    widths = lay.action_kind_widths
    if (widths["buy"] != n_shop or widths["sell"] != n_board
            or widths["activate"] != n_board or widths["choose"] != n_choice
            or widths["play"] != n_hand * raw["N_POS"]
            or widths["magnetize"] != n_hand * n_board
            or widths["move"] != n_board * n_board):
        raise RuntimeError(f"TavernGym 动作区间宽度不匹配：{widths}")
    _LAYOUT_CACHE = lay
    return lay


# ══════════════════════════════════════════════════════════════════════
# 卡牌静态表（种类/费用/基础数值；id/名称按需从 card_info 取）
# ══════════════════════════════════════════════════════════════════════


class _CardCatalog:
    """``card_static`` + ``card_info`` 的轻量缓存。

    ``card_static()`` 返回 ``(列数, f32 bytes)``：行=卡牌 embedding 下标
    （0=空），列 = 10 个种类 one-hot + tier/atk/hp/cost/armor + 种族/英雄关联/
    关键词/机制位 + golden/池标记 + quest goal。这里只取种类与费用。
    """

    #: ``card_static`` 列下标：种类 0..9；随后依次 tier, atk, hp, cost, armor
    _COL_TIER = 10
    _COL_COST = 13

    def __init__(self) -> None:
        tg = _require_taverngym()
        ncol, blob = tg.card_static()
        self._ncol = int(ncol)
        self._static = np.frombuffer(blob, dtype="<f4").reshape(-1, self._ncol)
        self._info: Dict[int, Tuple[str, str, str, int]] = {}
        self._kind: Dict[int, str] = {}

    # ── 基本信息 ──
    def info(self, index: int) -> Tuple[str, str, str, int]:
        """(card_id, 英文名, 中文名, tier)；下标 0/越界返回空。"""
        idx = int(index)
        if idx <= 0 or idx >= self._static.shape[0]:
            return ("", "", "", 0)
        got = self._info.get(idx)
        if got is None:
            got = _tg.card_info(idx)  # type: ignore[union-attr]
            self._info[idx] = got
        return got

    def card_id(self, index: int) -> str:
        return self.info(index)[0]

    def name(self, index: int) -> str:
        return self.info(index)[1]

    def card_type(self, index: int) -> str:
        idx = int(index)
        if idx <= 0 or idx >= self._static.shape[0]:
            return CARD_TYPE_UNKNOWN
        got = self._kind.get(idx)
        if got is None:
            flags = self._static[idx, :len(_CARD_KIND_FLAGS)]
            kinds = [i for i, v in enumerate(flags) if v >= 0.5]
            if not kinds:
                got = CARD_TYPE_UNKNOWN
            else:
                got = _CARD_KIND_TO_SPEC.get(
                    _CARD_KIND_FLAGS[kinds[0]], CARD_TYPE_UNKNOWN)
            self._kind[idx] = got
        return got

    def static(self, index: int, col: int) -> float:
        idx = int(index)
        if idx <= 0 or idx >= self._static.shape[0]:
            return 0.0
        return float(self._static[idx, int(col)])

    def base_tier(self, index: int) -> int:
        return int(round(self.static(index, self._COL_TIER)))

    def base_cost(self, index: int) -> int:
        return int(round(self.static(index, self._COL_COST)))

    def static_kind_flags(self, index: int) -> Dict[str, bool]:
        """卡牌种类 one-hot（调试用；如 ``{"minion": True, ...}``）。"""
        idx = int(index)
        if idx <= 0 or idx >= self._static.shape[0]:
            return {}
        return {name: bool(self._static[idx, i] >= 0.5)
                for i, name in enumerate(_CARD_KIND_FLAGS)}


_CARD_CACHE: Optional[_CardCatalog] = None


def _catalog() -> _CardCatalog:
    global _CARD_CACHE
    if _CARD_CACHE is None:
        _CARD_CACHE = _CardCatalog()
    return _CARD_CACHE


# ══════════════════════════════════════════════════════════════════════
# 数值解码小工具
# ══════════════════════════════════════════════════════════════════════


def _i(value: float, scale: float = 1.0) -> int:
    """反归一化浮点特征 → int（f32 编码，四舍五入）。"""
    return int(round(float(value) * scale))


def _flag(value: float) -> bool:
    return float(value) >= 0.5


def _race_names_from_bits(value: int) -> Tuple[str, ...]:
    """种族位掩码 → spec 种族名元组；"全种族"（Races::ALL=全部位）→ ("all",)。"""
    bits = int(value)
    if bits and bits == (1 << len(_TG_RACE_NAMES)) - 1:
        return ("all",)
    out: List[str] = []
    for i, name in enumerate(_TG_RACE_NAMES):
        if bits >> i & 1:
            out.append(_RACE_TO_SPEC.get(name, name.lower()))
    return tuple(out)


def _keyword_names_from_bits(value: int) -> Tuple[str, ...]:
    """关键词位掩码 → spec 关键词名元组（去重；IMMUNE 类映射到 other）。"""
    bits = int(value)
    out: List[str] = []
    seen = set()
    for i, name in enumerate(_TG_KEYWORD_NAMES):
        if bits >> i & 1:
            mapped = _KEYWORD_TO_SPEC.get(name, name.lower())
            if mapped not in seen:
                seen.add(mapped)
                out.append(mapped)
    return tuple(out)


def _keyword_names_from_names(names: Sequence[str]) -> Tuple[str, ...]:
    """view JSON 的关键词名列表 → spec 名（去重）。"""
    out: List[str] = []
    seen = set()
    for name in names:
        mapped = _KEYWORD_TO_SPEC.get(str(name), str(name).lower())
        if mapped not in seen:
            seen.add(mapped)
            out.append(mapped)
    return tuple(out)


def _lobby_races_from_names(names: Sequence[str]) -> Tuple[str, ...]:
    return tuple(_RACE_TO_SPEC.get(str(n), str(n).lower()) for n in names)


def _placement_value(rank: int, num_players: int) -> float:
    """名次 → [-1, +1]（与 ``hsbg.env.spec.RewardConfig`` 的 placement 口径一致）。"""
    if num_players <= 1:
        return 1.0
    rank = max(1, min(int(rank), int(num_players)))
    return 1.0 - 2.0 * (rank - 1) / (num_players - 1)


def _action_name(flat: int) -> str:
    """``taverngym.action_name`` 的可读名（失败返回空串）。"""
    try:
        return str(_tg.action_name(int(flat)))  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - 越界/旧版本兜底
        return ""


# ══════════════════════════════════════════════════════════════════════
# 观测中间结构（两种观测源共用候选构造与 Observation 组装）
# ══════════════════════════════════════════════════════════════════════


@dataclass
class _ObsParts:
    """一次观测的原始字段（与观测来源无关）。"""

    raw_turn: int
    raw_phase: str
    hero: Optional[HeroToken]
    board: Tuple[EntityToken, ...]
    hand: Tuple[EntityToken, ...]
    tavern: Tuple[EntityToken, ...]
    trinkets: Tuple[EntityToken, ...]
    quest: Optional[EntityToken]
    opponent_board: Tuple[EntityToken, ...]
    lobby: Tuple[LobbyPlayer, ...]
    alive_count: int
    rank: int
    pending: Optional[PendingChoice]
    pending_options_extra: Tuple[Dict[str, Any], ...]
    extra: Dict[str, Any]


def _empty_entity(card_id: str = "", *, card_type: str = CARD_TYPE_UNKNOWN,
                  zone: str = ZONE_NONE, slot: int = -1,
                  entity_id: int = 0, name: str = "") -> EntityToken:
    return EntityToken(card_id=card_id, card_type=card_type, zone=zone,
                       slot=slot, entity_id=entity_id, name=name)


# ══════════════════════════════════════════════════════════════════════
# 主类
# ══════════════════════════════════════════════════════════════════════


class TavernGymEnv:
    """TavernGym（AutoTavern Rust 引擎）→ ``hsbg.rl.api.EnvLike`` 适配器。

    参数
    ----
    num_players : int
        座位数（TavernGym ``RulesConfig.num_players``，2..8；默认 8）。
    seed : int
        默认种子；``reset(seed=None)`` 用它（保证可复现，不读系统熵）。
    agent_index : int
        智能体座位（0 起）。
    config : dict | None
        ``taverngym.RulesConfig`` 覆盖项（JSON 键值）；未知键会由引擎报错。
    obs_source : {"features", "view"}
        观测来源；默认 ``"features"``（官方 RL 观测，公开信息、快）。
    reward : RewardConfig | None
        奖励口径（只用 placement/invalid_action/step_penalty/timeout）。
    max_steps : int
        单局最大决策步数（超限 truncated）。
    max_turns : int | None
        单局最大回合数（超限 truncated；None = 不限制，由引擎 100 回合保险兜底）。
    illegal_penalty : float | None
        非法动作惩罚；None 用 ``reward.invalid_action``。
    include_action_names : bool
        是否在 ``extra["taverngym"]["candidate_action_names"]`` 里附可读动作名
        （``taverngym.action_name``，调试用；关闭可省一点开销）。
    """

    #: 供 gym 包装识别的元数据
    metadata = {"render_modes": [], "name": BACKEND_NAME}

    def __init__(
        self,
        num_players: int = 8,
        seed: int = 0,
        *,
        agent_index: int = 0,
        config: Optional[Dict[str, Any]] = None,
        obs_source: str = "features",
        reward: Optional[RewardConfig] = None,
        max_steps: int = 4000,
        max_turns: Optional[int] = 40,
        illegal_penalty: Optional[float] = None,
        include_action_names: bool = True,
        name: str = BACKEND_NAME,
    ) -> None:
        _require_taverngym()
        if obs_source not in ("features", "view"):
            raise ValueError(
                f"obs_source 必须是 'features' 或 'view'，得到 {obs_source!r}")
        n = int(num_players)
        if not 2 <= n <= 8:
            raise ValueError(f"num_players 必须在 2..8，得到 {n}")
        if not 0 <= int(agent_index) < n:
            raise ValueError(f"agent_index 越界：{agent_index}（num_players={n}）")
        if int(max_steps) <= 0:
            raise ValueError("max_steps 必须 > 0")
        self.num_players = n
        self.agent_index = int(agent_index)
        self.obs_source = str(obs_source)
        if isinstance(reward, dict):
            reward = RewardConfig(**reward)
        self.reward = reward if reward is not None else RewardConfig()
        self.max_steps = int(max_steps)
        self.max_turns = None if max_turns is None else int(max_turns)
        self.include_action_names = bool(include_action_names)
        self.name = str(name)
        self._illegal_penalty = (float(self.reward.invalid_action)
                                 if illegal_penalty is None
                                 else float(illegal_penalty))
        self._seed = int(seed) & 0x7FFFFFFF
        #: 传给 taverngym 的 RulesConfig 覆盖项（含 num_players / max_turns 保险）
        self._config_overrides: Dict[str, Any] = dict(config or {})
        if ("num_players" in self._config_overrides
                and int(self._config_overrides["num_players"]) != n):
            raise ValueError(
                "config['num_players'] 与 num_players 参数冲突："
                f"{self._config_overrides['num_players']} != {n}")
        self._config_overrides["num_players"] = n
        if self.max_turns is not None:
            # 引擎自带的 max_turns 是诊断性保险（会"发明"名次），因此让它在
            # 适配器的显式截断之后才触发（+2 回合余量）。
            self._config_overrides["max_turns"] = max(
                int(self._config_overrides.get("max_turns", 0)),
                self.max_turns + 2,
            )
        self._config_json = json.dumps(self._config_overrides, sort_keys=True)
        #: 引擎默认配置 + 覆盖项（用于 Dark Gift/饰品等未直接暴露的规则值）
        self._cfg_effective: Dict[str, Any] = self._effective_config()
        self._layout = _tg_layout()
        self._catalog_ref = _catalog()

        # 运行期状态
        self._game: Optional[Any] = None
        self._obs: Optional[Observation] = None
        self._candidates: Tuple[CandidateAction, ...] = ()
        self._flat_indices: Tuple[int, ...] = ()
        self._mask: np.ndarray = np.zeros(self._layout.n_actions, dtype=np.uint8)
        self._episode = 0
        self._step_count = 0
        self._done = False
        self._truncated = False
        self._terminated_reason = ""
        self._stopped_reason = ""
        self._stats: Dict[str, int] = self._new_stats()
        #: load_state 次数（不写进 obs.extra，避免破坏 save→load→save 的字节一致性）
        self._restore_count = 0
        self._closed = False

    def _effective_config(self) -> Dict[str, Any]:
        """引擎默认 RulesConfig + 本实例覆盖项（只读派生值，用于 extra）。"""
        try:
            defaults: Dict[str, Any] = json.loads(
                _require_taverngym().default_config_json())
        except Exception:  # pragma: no cover - 防御旧版本
            defaults = {}
        defaults.update(self._config_overrides)
        return defaults

    # ══════════════════════════════════════════════════════════════
    # 只读属性 / 兼容外观
    # ══════════════════════════════════════════════════════════════

    @property
    def backend(self) -> str:
        return BACKEND_NAME

    @property
    def unwrapped(self) -> "TavernGymEnv":
        return self

    @property
    def seed(self) -> int:
        return int(self._seed)

    @property
    def episode(self) -> int:
        return int(self._episode)

    @property
    def episode_steps(self) -> int:
        return int(self._step_count)

    @property
    def current_observation(self) -> Optional[Observation]:
        return self._obs

    @property
    def game(self) -> Any:
        """底层 ``taverngym.Game``（只读用；直接修改会与观测缓存脱节）。"""
        return self._game

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    @property
    def observation_space(self) -> Dict[str, Any]:
        dims = asdict(OBS_DIMS)
        dims.update({"kind": "entity_tokens", "backend": BACKEND_NAME})
        return dims

    @property
    def action_space(self) -> None:
        """动态候选动作空间（无固定动作数）→ None；固定空间见 fixed_action_mask()。"""
        return None

    def __repr__(self) -> str:  # pragma: no cover - 调试
        return (f"TavernGymEnv(players={self.num_players}, "
                f"agent={self.agent_index}, seed={self._seed}, "
                f"episode={self._episode}, obs_source={self.obs_source!r})")

    # ── 动作 API ──

    def legal_actions(self) -> Tuple[CandidateAction, ...]:
        """当前决策步的候选动作（== ``obs.candidates``）。"""
        return self._candidates

    def action_mask(self) -> Tuple[bool, ...]:
        """候选动作掩码（恒为全 True；候选就是 legal 动作）。"""
        return tuple(True for _ in self._candidates)

    def num_actions(self) -> int:
        return len(self._candidates)

    def legal_action_indices(self) -> Tuple[int, ...]:
        """当前候选对应的 TavernGym 扁平动作下标（与 ``obs.candidates`` 对齐）。"""
        return self._flat_indices

    def fixed_action_mask(self) -> Tuple[bool, ...]:
        """TavernGym **固定 245 维**动作空间的精确 legal mask（从引擎实时取）。"""
        if self._game is None:
            return tuple(False for _ in range(self._layout.n_actions))
        raw = self._game.legal_mask(self.agent_index)
        return tuple(bool(v) for v in np.frombuffer(raw, dtype=np.uint8))

    def flat_index(self, candidate: Any) -> int:
        """``CandidateAction`` 或**候选下标** → TavernGym 扁平动作下标（-1=未知）。

        注意：整数参数按"候选下标"解释（``obs.candidates`` 的下标），
        不是 TavernGym 扁平动作下标；反向映射用 :meth:`candidate_index_for_flat`。
        """
        if isinstance(candidate, CandidateAction):
            sig = candidate.signature()
            for flat, cand in zip(self._flat_indices, self._candidates):
                if cand.signature() == sig:
                    return int(flat)
            return -1
        try:
            idx = int(candidate)
        except (TypeError, ValueError):
            return -1
        if 0 <= idx < len(self._flat_indices):
            return int(self._flat_indices[idx])
        return -1

    def candidate_index_for_flat(self, flat: int) -> int:
        """TavernGym 扁平动作下标 → 候选下标（-1=当前不是合法候选）。"""
        try:
            target = int(flat)
        except (TypeError, ValueError):
            return -1
        for idx, value in enumerate(self._flat_indices):
            if int(value) == target:
                return idx
        return -1

    # ══════════════════════════════════════════════════════════════
    # 生命周期
    # ══════════════════════════════════════════════════════════════

    def _new_stats(self) -> Dict[str, int]:
        return {
            "episodes": 0,
            "steps": 0,
            "invalid": 0,
            "bot_turns": 0,
            "advance_calls": 0,
            "candidates_generated": 0,
            "candidates_over_spec_max": 0,
            "terminal_rewards": 0,
        }

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Observation:
        """开新局并返回第一个决策观测（英雄选择/招募/选择阶段）。"""
        tg = _require_taverngym()
        self._closed = False
        if seed is None:
            seed = options.get("seed") if options else None
        if seed is None:
            seed = self._seed
        self._seed = int(seed) & 0x7FFFFFFF
        self._episode += 1
        self._step_count = 0
        self._done = False
        self._truncated = False
        self._terminated_reason = ""
        self._stopped_reason = ""
        self._stats = self._new_stats()
        self._stats["episodes"] = 1
        self._game = tg.Game(int(self._seed), self._config_json)
        self._advance()
        self._obs = self._build_observation()
        self._note_candidates()
        return self._obs

    def close(self) -> None:
        """释放引擎引用（不触发引擎副作用）。"""
        self._closed = True
        self._game = None
        self._obs = None
        self._candidates = ()
        self._flat_indices = ()
        self._mask = np.zeros(self._layout.n_actions, dtype=np.uint8)

    # ══════════════════════════════════════════════════════════════
    # step
    # ══════════════════════════════════════════════════════════════

    def step(
        self, action: Any
    ) -> Tuple[Observation, float, bool, bool, Dict[str, Any]]:
        """执行一个候选动作（``CandidateAction`` 或候选下标）。

        非法动作（下标越界/不在候选内/引擎拒绝）→ 状态不推进、
        ``reward = -penalty``、``info["invalid"]=True``，不抛异常。
        """
        if self._game is None:
            raise RuntimeError("TavernGymEnv.step() 在 reset() 之前被调用")
        if self._done:
            info = self._make_info(
                invalid=False, terminated_reason="episode_done",
                flat_action=-1, extra={"episode_done": True})
            info.pop("wrong_action", None)
            info["wrong_action"] = True
            info["episode_done"] = True
            return self._obs, 0.0, True, bool(self._truncated), info

        idx = self._resolve_candidate(action)
        if idx is None:
            return self._invalid_step(reason="not a current candidate")
        flat = int(self._flat_indices[idx])
        # 双保险：Mask 必须仍然为真（观测 → step 之间不应有状态变化，防误用）
        raw_mask = np.frombuffer(
            self._game.legal_mask(self.agent_index), dtype=np.uint8)
        if not (0 <= flat < len(raw_mask) and raw_mask[flat]):
            return self._invalid_step(reason=f"flat action {flat} not legal")
        try:
            self._game.step(self.agent_index, flat)
        except Exception as exc:  # noqa: BLE001 - 引擎拒绝非法动作 → invalid
            return self._invalid_step(
                reason=f"engine rejected: {type(exc).__name__}: {exc}")
        self._step_count += 1
        self._stats["steps"] += 1
        self._advance()
        terminal = self._terminal_check() or self._max_steps_or_turns()
        if terminal is not None:
            reason, truncated = terminal
            return self._terminal_step(reason, truncated, flat=flat)
        self._obs = self._build_observation()
        self._note_candidates()
        reward = float(self.reward.step_penalty)
        return (self._obs, reward, False, False,
                self._make_info(invalid=False, flat_action=flat))

    def _resolve_candidate(self, action: Any) -> Optional[int]:
        """``CandidateAction`` / 候选下标 → 候选位置；非法返回 None。

        只接受真正的整数（``int`` / ``numpy.integer`` / 实现 ``__index__`` 的
        对象）；``bool`` 与 ``float`` 一律视为非法动作（避免 1.5 被悄悄当成 1）。
        """
        candidates = self._candidates
        if isinstance(action, CandidateAction):
            for i, cand in enumerate(candidates):
                if cand.signature() == action.signature():
                    return i
            return None
        if isinstance(action, bool):
            return None
        try:
            idx = int(operator.index(action))
        except TypeError:
            return None
        if 0 <= idx < len(candidates):
            return idx
        return None

    def _invalid_step(
        self, *, reason: str
    ) -> Tuple[Observation, float, bool, bool, Dict[str, Any]]:
        """非法动作：不推进状态，返回原观测 + invalid 标记。"""
        self._stats["invalid"] += 1
        info = self._make_info(
            invalid=True,
            terminated_reason="invalid_action",
            flat_action=-1,
            extra={"invalid_reason": str(reason),
                   "action_error": "not a current candidate"},
        )
        info["action_error"] = "not a current candidate"
        return self._obs, float(self._illegal_penalty), False, False, info

    def _terminal_step(
        self, reason: str, truncated: bool, *, flat: int
    ) -> Tuple[Observation, float, bool, bool, Dict[str, Any]]:
        """终局收口：rank/奖励/info 统一出口。"""
        self._done = True
        self._truncated = bool(truncated)
        self._terminated_reason = str(reason)
        self._obs = self._build_observation(force_terminal=True)
        rank = int(self._final_rank())
        reward = float(self.reward.step_penalty)
        if truncated:
            reward += float(self.reward.timeout)
        elif rank > 0:
            reward += float(self.reward.placement) * _placement_value(
                rank, self.num_players)
            self._stats["terminal_rewards"] += 1
        info = self._make_info(
            invalid=False, terminated_reason=reason, flat_action=int(flat))
        info["truncated"] = bool(truncated)
        info["agent_rank"] = int(rank)
        info["alive_count"] = int(self._obs.alive_count) if self._obs else 0
        return self._obs, float(reward), not truncated, truncated, info

    # ══════════════════════════════════════════════════════════════
    # 引擎驱动（与 taverngym.SoloEnv::advance 同语义）
    # ══════════════════════════════════════════════════════════════

    def _is_terminal_state(self) -> bool:
        """适配器视角的终局：游戏结束 / 智能体被淘汰 / 引擎停止 / 步数/回合超限。"""
        if self._game is None:
            return True
        if self._stopped_reason:
            return True
        if self._game.is_over():
            return True
        try:
            if int(self._game.placements()[self.agent_index]) != 0:
                return True
        except Exception:  # pragma: no cover - 防御
            pass
        if self._step_count >= self.max_steps:
            return True
        if self.max_turns is not None and int(self._game.turn) > self.max_turns:
            return True
        return False

    def _advance(self) -> bool:
        """驱动非智能体座位，直到智能体必须决策（或对局结束）。

        与 ``taverngym.SoloEnv::advance`` 同序：先让所有需要动作的机器人座位
        行动；智能体需要动作后，再把其它座位本回合的待办清空（与 SoloEnv 的
        第二段循环一致，保证战斗前机器人回合已结束）。
        """
        game = self._game
        assert game is not None
        self._stats["advance_calls"] += 1
        agent = self.agent_index
        n = int(game.num_players)
        guard = 0
        while (not self._is_terminal_state()
               and not bool(game.needs_action(agent))):
            guard += 1
            if guard > 10_000:
                self._stopped_reason = "driver_guard"
                return False
            progressed = False
            for p in range(n):
                if p != agent and bool(game.needs_action(p)):
                    game.bot_play(p)
                    self._stats["bot_turns"] += 1
                    progressed = True
            if not progressed:
                if self._is_terminal_state():
                    return True
                self._stopped_reason = "no_progress"
                return False
        # 与 SoloEnv 一致：智能体决策前把其它座位待办清空
        for p in range(n):
            if p == agent:
                continue
            if not bool(game.needs_action(p)):
                continue
            if self._is_terminal_state():
                return True
            game.bot_play(p)
            self._stats["bot_turns"] += 1
            if (bool(game.needs_action(p))
                    and not bool(game.is_over())
                    and not self._stopped_reason):
                self._stopped_reason = "no_progress"
                return False
        return True

    def _terminal_check(self) -> Optional[Tuple[str, bool]]:
        """返回 ``(reason, truncated)``；未终局返回 None。"""
        if self._stopped_reason:
            return ("simulator_stopped", True)
        game = self._game
        assert game is not None
        if game.is_over():
            if bool(getattr(game, "turn_limit_end", False)):
                return ("engine_turn_limit", True)
            return ("game_over", False)
        try:
            placement = int(game.placements()[self.agent_index])
        except Exception:  # pragma: no cover
            placement = 0
        if placement != 0:
            return ("eliminated", False)
        return None

    def _max_steps_or_turns(self) -> Optional[Tuple[str, bool]]:
        if self._step_count >= self.max_steps:
            return ("max_steps", True)
        if (self.max_turns is not None
                and int(self._game.turn) > self.max_turns):  # type: ignore[union-attr]
            return ("max_turns", True)
        return None

    def _final_rank(self) -> int:
        """终局名次：优先进游戏 placements，其次观测里估计的名次。"""
        if self._game is not None:
            try:
                placement = int(self._game.placements()[self.agent_index])
            except Exception:  # pragma: no cover
                placement = 0
            if placement > 0:
                return placement
        if self._obs is not None and int(self._obs.rank or 0) > 0:
            return int(self._obs.rank)
        return 0

    def _current_rank(self) -> int:
        if self._game is not None:
            try:
                placement = int(self._game.placements()[self.agent_index])
            except Exception:  # pragma: no cover
                placement = 0
            if placement > 0:
                return placement
        if self._obs is not None:
            return int(self._obs.rank or 0)
        return 0

    # ══════════════════════════════════════════════════════════════
    # 观测组装
    # ══════════════════════════════════════════════════════════════

    def _mask_array(self) -> np.ndarray:
        assert self._game is not None
        raw = self._game.legal_mask(self.agent_index)
        return np.frombuffer(raw, dtype=np.uint8)

    def _note_candidates(self) -> None:
        """统计候选（只在 reset/step 的正常决策点调用，load_state 重建不计数）。

        同时把最新 ``env_stats`` 同步回当前观测的 ``extra``，保证
        ``save_state() → load_state()`` 后重建的观测与存档前逐字段相等。
        """
        n = len(self._candidates)
        self._stats["candidates_generated"] += n
        if n > CANDIDATE_MAX:
            self._stats["candidates_over_spec_max"] += 1
        if self._obs is not None:
            self._obs.extra["env_stats"] = dict(self._stats)

    def _build_observation(self, *, force_terminal: bool = False) -> Observation:
        """从引擎当前状态构建 ``Observation``（含候选动作）。"""
        parts = self._collect_parts()
        terminal = bool(force_terminal) or self._is_terminal_state()
        if terminal:
            mask = np.zeros(self._layout.n_actions, dtype=np.uint8)
            candidates: Tuple[CandidateAction, ...] = ()
            flat: Tuple[int, ...] = ()
            phase = PHASE_GAME_OVER
            pending = None
            rank = self._final_rank() or parts.rank
        else:
            mask = self._mask_array()
            candidates, flat = self._build_candidates(parts, mask)
            phase = PHASE_CHOICE if parts.pending is not None else PHASE_RECRUIT
            pending = parts.pending
            rank = parts.rank
        self._mask = np.asarray(mask, dtype=np.uint8)
        self._candidates = tuple(candidates)
        self._flat_indices = tuple(flat)

        extra = dict(parts.extra)
        tg_meta = dict(extra.get("taverngym") or {})
        tg_meta.update({
            "obs_source": self.obs_source,
            "version": str(_tg.version()),
            "game_version": str(_tg.game_version()),
            "server_rules_version": str(_tg.server_rules_version()),
            "n_actions": int(self._layout.n_actions),
            "n_candidates": len(self._candidates),
            "candidate_max": int(CANDIDATE_MAX),
            "candidates_over_spec_max": len(self._candidates) > CANDIDATE_MAX,
            "flat_action_indices": tuple(int(x) for x in self._flat_indices),
            "turn_raw": int(parts.raw_turn),
            "phase_raw": str(parts.raw_phase),
        })
        if self.include_action_names and self._flat_indices:
            tg_meta["candidate_action_names"] = tuple(
                _action_name(f) for f in self._flat_indices)
        extra["taverngym"] = tg_meta
        if self._candidates:
            extra["pending_choice_options"] = tuple(
                dict(item) for item in parts.pending_options_extra)
        extra["env_stats"] = dict(self._stats)

        obs = Observation(
            turn=max(1, int(parts.raw_turn)),
            phase=phase,
            hero=parts.hero,
            board=tuple(parts.board),
            hand=tuple(parts.hand),
            tavern=tuple(parts.tavern),
            trinkets=tuple(parts.trinkets),
            quest=parts.quest,
            opponent_board=tuple(parts.opponent_board),
            lobby=tuple(parts.lobby),
            alive_count=int(parts.alive_count),
            total_players=int(self.num_players),
            rank=int(rank),
            pending_choice=pending,
            candidates=self._candidates,
            extra=extra,
            log="",
        )
        return obs

    # ── 候选动作构造（两种观测源共用）──

    def _build_candidates(
        self, parts: _ObsParts, mask: np.ndarray
    ) -> Tuple[Tuple[CandidateAction, ...], Tuple[int, ...]]:
        """把 245 维 mask 内的动作展开成 ``CandidateAction``（按下标升序）。"""
        lay = self._layout
        board = parts.board
        hand = parts.hand
        tavern = parts.tavern
        n_board = len(board)
        n_hand = len(hand)
        n_shop = len(tavern)
        upgrade_cost = int(parts.hero.upgrade_cost) if parts.hero else -1
        power_cost = int(parts.hero.power_cost) if parts.hero else -1
        dark_gift_cost = int(self._cfg_effective.get("dark_gift_cost", 3))
        candidates: List[CandidateAction] = []
        flat: List[int] = []
        n = min(len(mask), lay.n_actions)
        for a in range(n):
            if not mask[a]:
                continue
            cand: Optional[CandidateAction] = None
            if a == lay.a_end:
                cand = CandidateAction(kind=ActionKind.END_TURN.value)
            elif a == lay.a_refresh:
                cand = CandidateAction(kind=ActionKind.REROLL.value)
            elif a == lay.a_freeze:
                cand = CandidateAction(kind=ActionKind.FREEZE.value)
            elif a == lay.a_upgrade:
                cand = CandidateAction(kind=ActionKind.UPGRADE.value,
                                       cost=upgrade_cost)
            elif lay.a_hero_power <= a < lay.a_dark_gift:
                slot = a - lay.a_hero_power
                cand = CandidateAction(kind=ActionKind.HERO_POWER.value,
                                       src_zone=ZONE_POWER, src_slot=slot,
                                       position=slot,
                                       cost=power_cost if slot == 0 else -1)
            elif a == lay.a_dark_gift:
                cand = CandidateAction(kind=ActionKind.USE_DARK_GIFT.value,
                                       cost=dark_gift_cost)
            elif a == lay.a_cancel:
                # TavernGym 独有：取消目标选择（spec ActionKind 无对应项）
                cand = CandidateAction(kind="cancel")
            elif lay.a_buy <= a < lay.a_sell:
                slot = a - lay.a_buy
                if slot >= n_shop:
                    continue
                cand = CandidateAction(kind=ActionKind.BUY.value,
                                       src_zone=ZONE_TAVERN, src_slot=slot,
                                       cost=int(tavern[slot].cost))
            elif lay.a_sell <= a < lay.a_activate:
                slot = a - lay.a_sell
                if slot >= n_board:
                    continue
                cand = CandidateAction(kind=ActionKind.SELL.value,
                                       src_zone=ZONE_BOARD, src_slot=slot)
            elif lay.a_activate <= a < lay.a_choose:
                slot = a - lay.a_activate
                if slot >= n_board:
                    continue
                cand = CandidateAction(kind=ActionKind.ACTIVATE.value,
                                       src_zone=ZONE_BOARD, src_slot=slot)
            elif lay.a_choose <= a < lay.a_play:
                option = a - lay.a_choose
                cand = CandidateAction(kind=ActionKind.CHOOSE.value,
                                       option=option)
            elif lay.a_play <= a < lay.a_magnetize:
                rel = a - lay.a_play
                h, pos = divmod(rel, lay.n_pos)
                if h >= n_hand:
                    continue
                token = hand[h]
                kind = (ActionKind.PLAY_MINION.value
                        if token.card_type == CARD_TYPE_MINION
                        else ActionKind.PLAY_SPELL.value)
                cand = CandidateAction(kind=kind, src_zone=ZONE_HAND,
                                       src_slot=h, position=pos)
            elif lay.a_magnetize <= a < lay.a_move:
                rel = a - lay.a_magnetize
                h, b = divmod(rel, lay.n_board)
                if h >= n_hand or b >= n_board:
                    continue
                cand = CandidateAction(kind=ActionKind.PLAY_MINION.value,
                                       src_zone=ZONE_HAND, src_slot=h,
                                       tgt_zone=ZONE_BOARD, tgt_slot=b)
            elif lay.a_move <= a < lay.n_actions:
                rel = a - lay.a_move
                src, dst = divmod(rel, lay.n_board)
                if src >= n_board:
                    continue
                cand = CandidateAction(kind=ActionKind.MOVE_MINION.value,
                                       src_zone=ZONE_BOARD, src_slot=src,
                                       position=dst)
            if cand is not None:
                candidates.append(cand)
                flat.append(a)
        return tuple(candidates), tuple(flat)

    # ── 观测源 1：官方 RL 观测（features + cards）──

    def _collect_parts(self) -> _ObsParts:
        if self.obs_source == "view":
            return self._parts_from_view()
        return self._parts_from_features()

    def _parts_from_features(self) -> _ObsParts:
        """解码 ``Game.observe(seat)``：features(N f32) + cards(N i32)。"""
        assert self._game is not None
        lay = self._layout
        cat = self._catalog_ref
        fb, cb = self._game.observe(self.agent_index)
        floats = np.frombuffer(fb, dtype="<f4")
        cards = np.frombuffer(cb, dtype="<i4")
        F: List[float] = floats.tolist()
        C: List[int] = cards.tolist()

        raw_turn = _i(F[G_TURN], 20.0)
        if _flag(F[G_GAME_OVER]):
            raw_phase = "game_over"
        elif _flag(F[G_HERO_SELECT]):
            raw_phase = "hero_select"
        else:
            raw_phase = "recruit"

        # ── 英雄 ──
        hero_idx = C[lay.c_hero]
        placement = 0
        try:
            placement = int(self._game.placements()[self.agent_index])
        except Exception:  # pragma: no cover
            placement = 0
        power0_idx = C[lay.c_powers]
        power1_idx = C[lay.c_powers + 1] if lay.n_powers > 1 else 0
        hero = HeroToken(
            hero_id=cat.card_id(hero_idx),
            health=_i(F[G_HEALTH], 40.0),
            armor=_i(F[G_ARMOR], 20.0),
            tier=_i(F[G_TIER], 6.0),
            gold=_i(F[G_GOLD], 10.0),
            upgrade_cost=_i(F[G_UPGRADE_PRICE], 10.0),
            power_id=cat.card_id(power0_idx),
            power_cost=_i(F[G_POWER0_PRICE], 5.0) if power0_idx else 0,
            power_usable=_flag(F[G_POWER0_USABLE]),
            tavern_tier_max=int(self._cfg_effective.get("max_regular_tier", 6)),
        )

        # ── 己方棋盘/手牌/酒馆 ──
        board: List[EntityToken] = []
        for i in range(lay.n_board):
            token = self._minion_from_features(
                F, C, lay.off_board + i * lay.minion_f,
                lay.c_board + i, zone=ZONE_BOARD, slot=i)
            if token is not None:
                board.append(token)
        hand: List[EntityToken] = []
        for i in range(lay.n_hand):
            token = self._item_from_features(
                F, C, lay.off_hand + i * lay.item_f,
                lay.c_hand + i, zone=ZONE_HAND, slot=i)
            if token is not None:
                hand.append(token)
        tavern: List[EntityToken] = []
        for i in range(lay.n_shop):
            token = self._item_from_features(
                F, C, lay.off_shop + i * lay.item_f,
                lay.c_shop + i, zone=ZONE_TAVERN, slot=i,
                cost_from_price=True)
            if token is not None:
                tavern.append(token)

        # ── 饰品 / 任务 ──
        trinkets: List[EntityToken] = []
        trinket_ids: List[str] = []
        for i in range(8):
            card_idx = C[lay.c_trinkets + i]
            if card_idx <= 0:
                continue
            token = EntityToken(
                card_id=cat.card_id(card_idx),
                card_type=cat.card_type(card_idx) or CARD_TYPE_TRINKET,
                zone=ZONE_TRINKET, slot=i,
                tier=cat.base_tier(card_idx),
                cost=cat.base_cost(card_idx),
                name=cat.name(card_idx),
            )
            trinkets.append(token)
            trinket_ids.append(token.card_id)
        quest: Optional[EntityToken] = None
        quest_extra: Optional[Dict[str, Any]] = None
        quest_progress = quest_target = 0
        for i in range(lay.n_quests):
            q_idx = C[lay.c_quests + i * 3]
            r_idx = C[lay.c_quests + i * 3 + 1]
            present = _flag(F[lay.off_quests + i * lay.quest_f])
            if not present and q_idx <= 0:
                continue
            # 官方观测里进度是 progress/goal 归一化值（0~1），无法无损还原
            # progress 与 goal 两边；这里记成千分比（0~1000）并在 extra 注明。
            ratio_q = float(F[lay.off_quests + i * lay.quest_f + 1])
            quest_progress = int(round(ratio_q * 1000.0))
            quest_target = 1000
            if q_idx > 0 and quest is None:
                quest = EntityToken(
                    card_id=cat.card_id(q_idx), card_type=CARD_TYPE_QUEST,
                    zone=ZONE_QUEST, slot=i, tier=cat.base_tier(q_idx),
                    cost=cat.base_cost(q_idx), name=cat.name(q_idx))
            quest_extra = {
                "card_id": cat.card_id(q_idx) if q_idx > 0 else "",
                "reward_id": cat.card_id(r_idx) if r_idx > 0 else "",
                "progress_ratio": round(ratio_q, 6),
                "progress_permille": int(quest_progress),
                "target_permille": 1000,
            }
            break

        # ── 对手（公开信息 + 上次见到的战团）──
        lobby: List[LobbyPlayer] = []
        agent_seat = self.agent_index
        opp_entries: List[Tuple[int, LobbyPlayer, int, int]] = []
        hero_select_phase = raw_phase == "hero_select"
        for i in range(lay.n_opp):
            base = lay.off_opps + i * lay.opp_f
            present = _flag(F[base])
            if not present:
                continue
            alive = _flag(F[base + 1])
            if hero_select_phase:
                # 官方 obs 在英雄选择阶段会**屏蔽**对手信息（obs.rs：
                # health=1.0、tier=1/6、placement=0、hero 卡下标 0），
                # 这里还原为"未知"默认值，不能把 1.0 当成真实血量。
                health, armor, tier = 30, 0, 1
                seen_len = opp_placement = 0
                was_last = False
                hero_card = 0
            else:
                health = _i(F[base + 2], 40.0)
                armor = _i(F[base + 3], 20.0)
                tier = _i(F[base + 4], 6.0)
                seen_len = _i(F[base + 5], 7.0)
                opp_placement = _i(F[base + 6], 8.0)
                was_last = _flag(F[base + 7])
                hero_card = C[lay.c_opp_heroes + i]
            player = LobbyPlayer(
                name=cat.card_id(hero_card) or f"opp{i}",
                health=health, armor=armor, tier=tier, alive=alive,
                is_agent=False, eliminated_rank=opp_placement)
            opp_entries.append((i, player, seen_len, 4 if was_last else 0))
        # lobby 顺序：智能体座位固定，其他玩家按 TavernGym 相对座位序
        lobby = list(opp for (_i, opp, _s, _f) in opp_entries)
        my_hp = hero.health + hero.armor
        if hero_select_phase:
            # 英雄选择阶段没有名次语义（双方阵容均未成型）→ 0=未知
            rank = 0
        elif placement > 0:
            rank = placement
        else:
            rank = 1 + sum(
                1 for (_i, opp, _s, _f) in opp_entries
                if opp.alive and (opp.health + opp.armor) > my_hp)
        self_seat_entry = LobbyPlayer(
            name=hero.hero_id or f"P{agent_seat}", health=hero.health,
            armor=hero.armor, tier=hero.tier, alive=placement == 0,
            is_agent=True, eliminated_rank=placement)
        lobby.insert(min(agent_seat, len(lobby)), self_seat_entry)
        # 上一场对手的战团（只取"己方见过"的 seen_board）
        opponent_board: List[EntityToken] = []
        last_opponent_id: Optional[str] = None
        next_opponent_id: Optional[str] = None
        for i, player, seen_len, last_flag in opp_entries:
            if last_flag:
                last_opponent_id = player.name
                for j in range(min(seen_len, lay.n_board)):
                    token = self._minion_from_features(
                        F, C,
                        lay.off_opp_boards + (i * lay.n_board + j) * lay.minion_f,
                        lay.c_opp_boards + i * lay.n_board + j,
                        zone=ZONE_OPPONENT, slot=j)
                    if token is not None:
                        opponent_board.append(token)
        for i, player, seen_len, _last in opp_entries:
            base = lay.off_opps + i * lay.opp_f
            if _flag(F[base + 8]):
                next_opponent_id = player.name
        alive_count = _i(F[G_ALIVE], 8.0)
        if alive_count <= 0:
            alive_count = (1 if placement == 0 else 0) + sum(
                1 for (_i, opp, _s, _f) in opp_entries if opp.alive)

        # ── pending choice ──
        pending, pending_extra = self._pending_from_features(F, C)

        # ── extra（尽量对齐 hsrl2 的键；缺失项留空/注明）──
        powers: List[Dict[str, Any]] = []
        for slot, card_idx in enumerate((power0_idx, power1_idx)[:lay.n_powers]):
            if card_idx <= 0:
                continue
            powers.append({
                "power_id": cat.card_id(card_idx),
                "cost": _i(F[G_POWER0_PRICE + slot * 3], 5.0),
                "usable": _flag(F[G_POWER0_USABLE + slot * 3]),
                "uses_game": _i(F[G_POWER0_USES_GAME + slot * 3], 5.0),
                "uses_turn": -1,  # 官方 obs 不含每回合剩余次数
            })
        second = powers[1] if len(powers) > 1 else None
        lobby_races = tuple(
            _RACE_TO_SPEC.get(_TG_RACE_NAMES[i], _TG_RACE_NAMES[i].lower())
            for i in range(lay.races_count)
            if _flag(F[G_LOBBIES + i]))
        # 官方 obs 里 r_idx 只用于任务块；Dark Gift 等规则值取配置默认
        dark_gift_uses_used = _i(F[G_DARK_GIFT_USES], 3.0)
        cap = int(self._cfg_effective.get("dark_gift_uses", 3))
        extra: Dict[str, Any] = {
            "version": int(Observation().version),
            "turn": int(raw_turn),
            "frozen_tavern": _flag(F[G_FROZEN]),
            "free_refresh_left": _i(F[G_FREE_REFRESHES], 3.0),
            "refresh_cost": _i(F[G_REFRESH_PRICE], 2.0),
            "powers": powers,
            "power_uses_left": {},
            "second_power_id": second["power_id"] if second else "",
            "second_power_cost": int(second["cost"]) if second else -1,
            "second_power_uses_left": -1 if second else 0,
            "dark_gift": {
                "available": _flag(F[G_CAN_DARK_GIFT]),
                "uses": dark_gift_uses_used,
                "max_uses": cap,
                "cost": int(self._cfg_effective.get("dark_gift_cost", 3)),
                "unlock_turn": int(
                    self._cfg_effective.get("dark_gift_unlock_turn", 3)),
                "used_this_turn": False,  # 官方 obs 未暴露
                "tiers": (),
                "next_tiers": (),
                "slots": (),
            },
            "dark_gift_uses_left": int(max(0, cap - dark_gift_uses_used)),
            "quest": quest_extra,
            "quest_progress": quest_progress,
            "quest_target": quest_target,
            "quest_completed": bool(quest_extra and
                                    quest_extra["progress_permille"] >= 1000),
            "quest_reward_ids": ([quest_extra["reward_id"]]
                                 if quest_extra and quest_extra["reward_id"]
                                 else []),
            "trinkets": [t.card_id for t in trinkets],
            "trinket_ids": trinket_ids,
            "board_states": [],       # 官方 obs 无 EXHAUSTED/FROZEN 等逐随从标志
            "hand_states": [],
            "minion_flags": {},
            "pending_hand_queue": _i(F[G_HAND_QUEUE], 5.0),
            "pending_hand_card_ids": [],
            "next_opponent": next_opponent_id,
            "next_opponent_info": None,
            "last_opponent": last_opponent_id,
            "last_opponent_info": None,
            "elimination": [
                {"hero_id": player.name, "name": player.name,
                 "rank": int(player.eliminated_rank)}
                for (_i, player, _s, _f) in opp_entries
                if player.eliminated_rank > 0
            ],
            "elimination_order": [],
            "last_combat": None,      # 官方 obs 不含战斗摘要（view 模式可得）
            "deaths_by_card_id": {},
            "lobby_races": lobby_races,
            "has_aberrations": "aberration" in lobby_races,
            "gold_next_turn": _i(F[G_GOLD_NEXT], 5.0),
            "max_gold_bonus": _i(F[G_MAX_GOLD_BONUS], 5.0),
            "tavern": {
                "minion_price": _i(F[G_MINION_PRICE], 3.0),
                "tavern_atk": _i(F[G_TAVERN_ATK], 10.0),
                "tavern_hp": _i(F[G_TAVERN_HP], 10.0),
            },
            "won_last_combat": _flag(F[G_WON_LAST]),
            "lost_last_combat": _flag(F[G_LOST_LAST]),
        }
        extra["elimination_order"] = [
            e["hero_id"] for e in sorted(
                extra["elimination"], key=lambda e: -int(e["rank"]))]
        extra["taverngym"] = {
            "raw_phase": raw_phase,
            "turn_raw": int(raw_turn),
            "power_count": len(powers),
        }
        return _ObsParts(
            raw_turn=int(raw_turn), raw_phase=str(raw_phase), hero=hero,
            board=tuple(board), hand=tuple(hand), tavern=tuple(tavern),
            trinkets=tuple(trinkets), quest=quest,
            opponent_board=tuple(opponent_board), lobby=tuple(lobby),
            alive_count=int(alive_count), rank=int(rank), pending=pending,
            pending_options_extra=pending_extra, extra=extra)

    def _minion_from_features(
        self, F: List[float], C: List[int], base: int, card_pos: int,
        *, zone: str, slot: int,
    ) -> Optional[EntityToken]:
        """解码一个随从块（``push_minion`` 布局）；空槽返回 None。"""
        if not _flag(F[base + M_PRESENT]):
            return None
        lay = self._layout
        cat = self._catalog_ref
        card_idx = int(C[card_pos])
        kw_bits = 0
        for i in range(lay.kw_count):
            if _flag(F[base + M_KEYWORDS + i]):
                kw_bits |= 1 << i
        race_bits = 0
        for i in range(lay.races_count):
            if _flag(F[base + M_KEYWORDS + lay.kw_count + i]):
                race_bits |= 1 << i
        return EntityToken(
            card_id=cat.card_id(card_idx),
            card_type=CARD_TYPE_MINION,
            zone=zone, slot=slot,
            atk=_i(F[base + M_ATK], 10.0),
            health=_i(F[base + M_HP], 10.0),
            tier=_i(F[base + M_TIER], 6.0),
            cost=0,
            races=_race_names_from_bits(race_bits),
            keywords=_keyword_names_from_bits(kw_bits),
            golden=_flag(F[base + M_GOLDEN]),
            entity_id=0,
            name=cat.name(card_idx),
        )

    def _item_from_features(
        self, F: List[float], C: List[int], base: int, card_pos: int,
        *, zone: str, slot: int, cost_from_price: bool = False,
    ) -> Optional[EntityToken]:
        """解码一个物品块（``push_item``：随从或法术）；空槽返回 None。"""
        if not _flag(F[base + I_PRESENT]):
            return None
        cat = self._catalog_ref
        card_idx = int(C[card_pos])
        cost = _i(F[base + I_COST], 5.0) if cost_from_price else 0
        if _flag(F[base + I_IS_MINION]):
            token = self._minion_from_features(
                F, C, base + I_MINION, card_pos, zone=zone, slot=slot)
            if token is None:  # pragma: no cover - 防御
                return None
            return EntityToken(
                card_id=token.card_id, card_type=token.card_type, zone=zone,
                slot=slot, atk=token.atk, health=token.health, tier=token.tier,
                cost=cost, races=token.races, keywords=token.keywords,
                golden=token.golden, entity_id=token.entity_id, name=token.name)
        return EntityToken(
            card_id=cat.card_id(card_idx),
            card_type=cat.card_type(card_idx) or CARD_TYPE_SPELL,
            zone=zone, slot=slot,
            tier=_i(F[base + I_SPELL_TIER], 6.0),
            cost=cost,
            name=cat.name(card_idx),
        )

    def _pending_from_features(
        self, F: List[float], C: List[int]
    ) -> Tuple[Optional[PendingChoice], Tuple[Dict[str, Any], ...]]:
        """官方 obs 的 pending choice：种类 one-hot + 选项物品块（数量由 mask 定）。"""
        lay = self._layout
        cat = self._catalog_ref
        kind_idx = 0
        for i in range(lay.pending_kinds):
            if _flag(F[lay.off_pending + i]):
                kind_idx = i
                break
        if kind_idx <= 0:
            return None, ()
        kind = _PENDING_KINDS[kind_idx]
        mask = self._mask_array()
        options: List[EntityToken] = []
        option_extra: List[Dict[str, Any]] = []
        for k in range(lay.n_choice):
            flat = lay.a_choose + k
            if flat >= len(mask) or not mask[flat]:
                continue
            base = lay.off_choices + k * lay.item_f
            card_pos = lay.c_choices + k
            card_idx = int(C[card_pos])
            token = self._item_from_features(
                F, C, base, card_pos, zone=ZONE_CHOICE, slot=k)
            if token is None:
                # hero / 目标（官方 obs 里 target 的实体信息不可得）→ 只给卡 id
                ctype = cat.card_type(card_idx) or CARD_TYPE_HERO
                token = _empty_entity(
                    cat.card_id(card_idx), card_type=ctype, zone=ZONE_CHOICE,
                    slot=k, name=cat.name(card_idx))
            cost = _i(F[base + I_COST], 5.0)
            options.append(token)
            label = cat.name(card_idx)
            option_extra.append({
                "index": int(k),
                "card_id": token.card_id,
                "secondary_id": None,
                "label": label or None,
                "name": token.name,
                "secondary_name": None,
                "cost": int(cost),
            })
        pending = PendingChoice(
            kind=_PENDING_TO_SPEC.get(kind, kind),
            options=tuple(options),
            for_agent=True,
            prompt="",
        )
        return pending, tuple(option_extra)

    # ── 观测源 2：Game.view(seat) JSON（调试视图，字段最全但慢）──

    def _parts_from_view(self) -> _ObsParts:
        assert self._game is not None
        view = json.loads(self._game.view(self.agent_index))
        me = view.get("me") or {}
        raw_turn = int(view.get("turn", 0))
        raw_phase = str(view.get("phase", "recruit"))
        agent_seat = self.agent_index

        hero_card = me.get("hero") or {}
        power = me.get("hero_power") or {}
        hero = HeroToken(
            hero_id=str(hero_card.get("id", "")),
            health=int(me.get("health", 0)),
            armor=int(me.get("armor", 0)),
            tier=int(me.get("tier", 0)),
            gold=int(me.get("gold", 0)),
            upgrade_cost=int(me.get("upgrade_price", 0)),
            power_id=str(power.get("id", "")),
            power_cost=int(power.get("price") or 0),
            power_usable=bool(power.get("usable", False)),
            tavern_tier_max=int(self._cfg_effective.get("max_regular_tier", 6)),
        )

        # ── 实体 ──
        def _view_token(raw: Dict[str, Any], *, zone: str, slot: int,
                        cost: int = 0) -> EntityToken:
            ctype = CARD_TYPE_SPELL if raw.get("type") == "spell" else CARD_TYPE_MINION
            if zone in (ZONE_TRINKET,):
                ctype = CARD_TYPE_TRINKET
            return EntityToken(
                card_id=str(raw.get("id", "")),
                card_type=ctype, zone=zone, slot=slot,
                atk=int(raw.get("atk", 0)), health=int(raw.get("hp", 0)),
                tier=int(raw.get("tier", 0)), cost=int(cost),
                races=_lobby_races_from_names(raw.get("races") or ()),
                keywords=_keyword_names_from_names(
                    raw.get("keywords") or ()),
                golden=bool(raw.get("golden", False)),
                entity_id=int(raw.get("eid", 0)),
                name=str(raw.get("name", "")),
            )

        board = tuple(
            _view_token(raw, zone=ZONE_BOARD, slot=i)
            for i, raw in enumerate(me.get("board") or ()))
        hand = tuple(
            _view_token(raw, zone=ZONE_HAND, slot=i)
            for i, raw in enumerate(me.get("hand") or ()))
        tavern_list: List[EntityToken] = []
        for i, raw in enumerate(me.get("shop") or ()):
            price = raw.get("price")
            cost = int(price) if price is not None else int(raw.get("cost", 0))
            tavern_list.append(
                _view_token(raw, zone=ZONE_TAVERN, slot=i, cost=cost))
        tavern = tuple(tavern_list)
        trinkets = tuple(
            EntityToken(
                card_id=str(raw.get("id", "")), card_type=CARD_TYPE_TRINKET,
                zone=ZONE_TRINKET, slot=i, tier=int(raw.get("tier", 0)),
                cost=int(raw.get("cost", 0)), name=str(raw.get("name", "")))
            for i, raw in enumerate(me.get("trinkets") or ()))
        quest: Optional[EntityToken] = None
        quest_extra: Optional[Dict[str, Any]] = None
        quests = me.get("quests") or ()
        if quests:
            q = quests[0]
            qcard = q.get("quest") or {}
            rcard = q.get("reward") or {}
            progress = int(q.get("progress", 0))
            target = int(q.get("goal", 0))
            quest = EntityToken(
                card_id=str(qcard.get("id", "")), card_type=CARD_TYPE_QUEST,
                zone=ZONE_QUEST, slot=0, tier=int(qcard.get("tier", 0)),
                cost=int(qcard.get("cost", 0)), name=str(qcard.get("name", "")))
            quest_extra = {
                "card_id": quest.card_id,
                "reward_id": str(rcard.get("id", "")),
                "progress": progress,
                "target": target,
                "completed": target > 0 and progress >= target,
            }

        # ── 大厅 / 对手 ──
        opponents_raw = list(view.get("opponents") or ())
        placement = int(me.get("placement", 0) or 0)
        my_hp = hero.health + hero.armor
        lobby: List[LobbyPlayer] = []
        last_opponent_id: Optional[str] = None
        next_opponent_id: Optional[str] = None
        opponent_board: List[EntityToken] = []
        seen_boards: Dict[int, List[Dict[str, Any]]] = {}
        for opp in opponents_raw:
            seen_boards[int(opp.get("id", 0))] = list(opp.get("seen_board") or ())
        ordered: List[Tuple[int, LobbyPlayer]] = []
        for opp in opponents_raw:
            hero_id = str((opp.get("hero") or {}).get("id", ""))
            seat_id = int(opp.get("id", 0))
            player = LobbyPlayer(
                name=hero_id or f"seat{seat_id}",
                health=int(opp.get("health", 0)),
                armor=int(opp.get("armor", 0)),
                tier=int(opp.get("tier", 0)),
                alive=bool(opp.get("alive", False)),
                is_agent=False,
                eliminated_rank=int(opp.get("placement", 0) or 0))
            ordered.append((seat_id, player))
            if opp.get("was_last_opponent"):
                last_opponent_id = player.name
                for j, raw in enumerate(seen_boards.get(seat_id) or ()):
                    opponent_board.append(
                        _view_token(raw, zone=ZONE_OPPONENT, slot=j))
            if opp.get("is_next_opponent"):
                next_opponent_id = player.name
        ordered.sort(key=lambda item: item[0])
        lobby = [player for (_seat, player) in ordered]
        if raw_phase == "hero_select":
            rank = 0   # 英雄选择阶段没有名次语义（0=未知）
        elif placement > 0:
            rank = placement
        else:
            rank = 1 + sum(
                1 for (_seat, opp) in ordered
                if opp.alive and (opp.health + opp.armor) > my_hp)
        lobby.insert(
            min(agent_seat, len(lobby)),
            LobbyPlayer(name=hero.hero_id or f"P{agent_seat}",
                        health=hero.health, armor=hero.armor, tier=hero.tier,
                        alive=placement == 0, is_agent=True,
                        eliminated_rank=placement))
        alive_count = int(view.get("alive", 0) or 0)

        # ── pending choice ──
        pending: Optional[PendingChoice] = None
        pending_extra: List[Dict[str, Any]] = []
        pend = me.get("pending")
        if isinstance(pend, dict) and pend.get("kind"):
            kind = str(pend["kind"])
            options: List[EntityToken] = []
            if kind == "target":
                # target 选项是 eid：映射回己方棋盘/酒馆/手牌实体
                eid_map: Dict[int, EntityToken] = {}
                for token in board:
                    if token.entity_id:
                        eid_map[token.entity_id] = token
                hid_map: Dict[int, EntityToken] = {}
                for i, raw in enumerate(me.get("hand") or ()):
                    hid_map[int(raw.get("hid", 0))] = hand[i]
                sid_map: Dict[int, EntityToken] = {}
                for i, raw in enumerate(me.get("shop") or ()):
                    sid_map[int(raw.get("sid", 0))] = tavern[i]
                for k, eid in enumerate(pend.get("targets") or ()):
                    eid = int(eid)
                    token = (eid_map.get(eid) or hid_map.get(eid)
                             or sid_map.get(eid))
                    if token is None:
                        token = _empty_entity(entity_id=eid,
                                              zone=ZONE_CHOICE, slot=k)
                    options.append(EntityToken(
                        card_id=token.card_id, card_type=token.card_type,
                        zone=ZONE_CHOICE, slot=k, atk=token.atk,
                        health=token.health, tier=token.tier, cost=-1,
                        races=token.races, keywords=token.keywords,
                        golden=token.golden, entity_id=eid, name=token.name))
                    pending_extra.append({
                        "index": int(k), "card_id": token.card_id,
                        "secondary_id": str(eid),
                        "label": None, "name": token.name,
                        "secondary_name": None, "cost": -1,
                    })
            else:
                for k, raw in enumerate(pend.get("options") or ()):
                    if not isinstance(raw, dict):
                        continue
                    if kind == "hero":
                        token = EntityToken(
                            card_id=str(raw.get("id", "")),
                            card_type=CARD_TYPE_HERO, zone=ZONE_CHOICE,
                            slot=k, health=int(raw.get("hp", 0)),
                            tier=int(raw.get("tier", 0)),
                            name=str(raw.get("name", "")))
                    elif raw.get("type") in ("minion", "spell"):
                        token = _view_token(raw, zone=ZONE_CHOICE, slot=k,
                                            cost=int(raw.get("cost", 0) or 0))
                    else:
                        token = EntityToken(
                            card_id=str(raw.get("id", "")),
                            card_type=(CARD_TYPE_REWARD
                                       if kind == "quest" else CARD_TYPE_TRINKET),
                            zone=ZONE_CHOICE, slot=k,
                            tier=int(raw.get("tier", 0)),
                            cost=int(raw.get("cost", 0) or 0),
                            name=str(raw.get("name", "")))
                    reward = raw.get("reward")
                    secondary_id = (str(reward.get("id", ""))
                                    if isinstance(reward, dict) else None)
                    secondary_name = (str(reward.get("name", ""))
                                      if isinstance(reward, dict) else None)
                    options.append(token)
                    pending_extra.append({
                        "index": int(k),
                        "card_id": token.card_id,
                        "secondary_id": secondary_id,
                        "label": secondary_name,
                        "name": token.name,
                        "secondary_name": secondary_name,
                        "cost": int(raw.get("cost", 0) or 0),
                    })
            pending = PendingChoice(
                kind=_PENDING_TO_SPEC.get(kind, kind),
                options=tuple(options), for_agent=True, prompt="")

        # ── extra ──
        powers_raw = list(me.get("hero_powers") or ())
        if not powers_raw and me.get("hero_power"):
            powers_raw = [me["hero_power"]]
        powers: List[Dict[str, Any]] = []
        for slot, raw in enumerate(powers_raw):
            powers.append({
                "power_id": str(raw.get("id", "")),
                "cost": int(raw.get("price") or 0),
                "usable": bool(raw.get("usable", False)),
                "uses_game": int(raw.get("uses_game", 0) or 0),
                "uses_turn": int(raw.get("uses_turn", 0) or 0),
                "passive": bool(raw.get("passive", False)),
            })
        second = powers[1] if len(powers) > 1 else None
        dark = dict(me.get("dark_gift") or {})
        elimination = [
            {"hero_id": player.name, "name": player.name,
             "rank": int(player.eliminated_rank)}
            for (_seat, player) in ordered if player.eliminated_rank > 0
        ]
        elimination_order = [
            e["hero_id"] for e in sorted(elimination,
                                         key=lambda e: -int(e["rank"]))]
        last_combat: Optional[Dict[str, Any]] = None
        combats = view.get("combats") or ()
        mine = [c for c in combats
                if c.get("a") == agent_seat or c.get("b") == agent_seat]
        if mine:
            c = mine[-1]
            last_combat = {
                "turn": int(c.get("turn", 0) or 0),
                "winner": c.get("winner"),
                "damage": int(c.get("damage", 0) or 0),
                "truncated": bool(c.get("truncated", False)),
            }
        extra: Dict[str, Any] = {
            "version": int(Observation().version),
            "turn": int(raw_turn),
            "frozen_tavern": bool(me.get("frozen", False)),
            "free_refresh_left": int(me.get("free_refreshes", 0) or 0),
            "refresh_cost": int(me.get("refresh_price", 0) or 0),
            "powers": powers,
            "power_uses_left": {
                str(p["power_id"]): int(p["uses_turn"]) for p in powers
            },
            "second_power_id": second["power_id"] if second else "",
            "second_power_cost": int(second["cost"]) if second else -1,
            "second_power_uses_left": int(second["uses_turn"]) if second else 0,
            "dark_gift": {
                "available": bool(dark.get("available", False)),
                "uses": int(dark.get("uses", 0) or 0),
                "max_uses": int(dark.get("max_uses", 0) or 0),
                "cost": int(dark.get("cost", 0) or 0),
                "unlock_turn": int(dark.get("unlock_turn", 0) or 0),
                "used_this_turn": bool(dark.get("used_this_turn", False)),
                "tiers": tuple(dark.get("tiers") or ()),
                "next_tiers": tuple(dark.get("next_tiers") or ()),
                "slots": tuple(dark.get("slots") or ()),
            },
            "dark_gift_uses_left": int(
                max(0, int(dark.get("max_uses", 0) or 0)
                    - int(dark.get("uses", 0) or 0))),
            "quest": quest_extra,
            "quest_progress": (int(quest_extra["progress"])
                               if quest_extra else 0),
            "quest_target": (int(quest_extra["target"])
                             if quest_extra else 0),
            "quest_completed": (bool(quest_extra["completed"])
                                if quest_extra else False),
            "quest_reward_ids": ([quest_extra["reward_id"]]
                                 if quest_extra
                                 and quest_extra["reward_id"] else []),
            "trinkets": [str((t or {}).get("id", ""))
                         for t in (me.get("trinkets") or ())],
            "trinket_ids": [t.card_id for t in trinkets],
            "board_states": [],
            "hand_states": [
                {"entity_id": int(raw.get("hid", 0)),
                 "card_id": str(raw.get("id", "")),
                 "locked_in_hand": bool(raw.get("locked", 0))}
                for raw in (me.get("hand") or ())
            ],
            "minion_flags": {},
            "pending_hand_queue": len(me.get("hand_queue") or ()),
            "pending_hand_card_ids": [
                str((raw or {}).get("id", ""))
                for raw in (me.get("hand_queue") or ())],
            "next_opponent": next_opponent_id,
            "next_opponent_info": None,
            "last_opponent": last_opponent_id,
            "last_opponent_info": None,
            "elimination": elimination,
            "elimination_order": elimination_order,
            "last_combat": last_combat,
            "deaths_by_card_id": {},
            "lobby_races": _lobby_races_from_names(
                view.get("lobby_races") or ()),
            "has_aberrations": bool(view.get("has_aberrations", False)),
            "max_gold": int(me.get("max_gold", 0) or 0),
            "tavern": {
                "minion_price": int(me.get("minion_price", 0) or 0),
                "tavern_atk": int(
                    (me.get("stats") or {}).get("tavern_atk", 0) or 0),
                "tavern_hp": int(
                    (me.get("stats") or {}).get("tavern_hp", 0) or 0),
            },
            "shop_frozen": tuple(
                bool(raw.get("frozen", False))
                for raw in (me.get("shop") or ())),
            "won_last_combat": bool(
                (me.get("stats") or {}).get("won_last", False)),
            "lost_last_combat": bool(
                (me.get("stats") or {}).get("lost_last", False)),
            "taverngym": {
                "raw_phase": raw_phase,
                "turn_raw": int(raw_turn),
                "power_count": len(powers),
                "lobby_races_raw": tuple(view.get("lobby_races") or ()),
            },
        }
        return _ObsParts(
            raw_turn=int(raw_turn), raw_phase=str(raw_phase), hero=hero,
            board=board, hand=hand, tavern=tavern, trinkets=trinkets,
            quest=quest, opponent_board=tuple(opponent_board),
            lobby=tuple(lobby), alive_count=int(alive_count),
            rank=int(rank), pending=pending,
            pending_options_extra=tuple(pending_extra), extra=extra)

    # ══════════════════════════════════════════════════════════════
    # info
    # ══════════════════════════════════════════════════════════════

    def _make_info(
        self,
        *,
        invalid: bool = False,
        terminated_reason: str = "",
        flat_action: int = -1,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构造与 hsrl2 后端尽量同构的 ``info``（JSONL 白名单字段齐全）。"""
        obs = self._obs
        hero = obs.hero if obs is not None else None
        game = self._game
        turn = int(game.turn) if game is not None else 0
        phase = str(getattr(obs, "phase", "")) if obs is not None else ""
        rank = self._current_rank()
        info: Dict[str, Any] = {
            "turn": turn,
            "rank": int(rank),
            "agent_rank": int(rank),
            "health": int(hero.health) if hero is not None else 0,
            "armor": int(hero.armor) if hero is not None else 0,
            "alive_count": int(obs.alive_count) if obs is not None else 0,
            "combat": {},
            "wrong_action": bool(invalid),
            "invalid": bool(invalid),
            "terminated_reason": str(terminated_reason),
            "seed": int(self._seed),
            "episode": int(self._episode),
            "episode_steps": int(self._step_count),
            "phase": phase,
            "backend": BACKEND_NAME,
            "flat_action": int(flat_action),
            "action_name": _action_name(flat_action) if flat_action >= 0 else "",
            "action_mask": tuple(int(x) for x in self._mask),
            "n_candidates": len(self._candidates),
            "taverngym_version": str(_tg.version()),  # type: ignore[union-attr]
            "taverngym_game_version": str(_tg.game_version()),  # type: ignore[union-attr]
            "obs_source": self.obs_source,
            "restore_count": int(self._restore_count),
        }
        if self._stopped_reason:
            info["simulator_stopped"] = str(self._stopped_reason)
        if extra:
            info.update({k: v for k, v in extra.items() if k not in info})
        return info

    # ══════════════════════════════════════════════════════════════
    # 精确存档 / 恢复（基于 taverngym state_json / from_json）
    # ══════════════════════════════════════════════════════════════

    #: 存档格式标识（load_state 校验用）
    STATE_FORMAT = "hsbg.backends.taverngym_env"
    STATE_VERSION = 1

    def save_state(self) -> str:
        """精确存档：引擎完整状态 JSON + 适配器计数（返回 JSON 字符串）。"""
        if self._game is None:
            raise RuntimeError("TavernGymEnv.save_state() 在 reset() 之前被调用")
        payload = {
            "format": self.STATE_FORMAT,
            "version": int(self.STATE_VERSION),
            "backend": BACKEND_NAME,
            "game_json": str(self._game.state_json()),
            "meta": {
                "seed": int(self._seed),
                "episode": int(self._episode),
                "step_count": int(self._step_count),
                "done": bool(self._done),
                "truncated": bool(self._truncated),
                "terminated_reason": str(self._terminated_reason),
                "stopped_reason": str(self._stopped_reason),
                "stats": dict(self._stats),
                "agent_index": int(self.agent_index),
                "num_players": int(self.num_players),
                "obs_source": str(self.obs_source),
                "config_overrides": dict(self._config_overrides),
                "max_steps": int(self.max_steps),
                "max_turns": (None if self.max_turns is None
                              else int(self.max_turns)),
                "illegal_penalty": float(self._illegal_penalty),
                "include_action_names": bool(self.include_action_names),
            },
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def load_state(self, state: Any) -> "TavernGymEnv":
        """从 :meth:`save_state` 的存档恢复（可继续 step，轨迹与存档点一致）。"""
        tg = _require_taverngym()
        if isinstance(state, (bytes, bytearray)):
            state = state.decode("utf-8")
        if isinstance(state, str):
            payload = json.loads(state)
        elif isinstance(state, dict):
            payload = state
        else:
            raise TypeError(
                f"load_state 需要 str/dict，得到 {type(state).__name__}")
        if not isinstance(payload, dict):
            raise ValueError("load_state 存档不是 JSON 对象")
        if payload.get("format") != self.STATE_FORMAT:
            raise ValueError(
                f"存档格式不匹配：{payload.get('format')!r} != "
                f"{self.STATE_FORMAT!r}")
        if int(payload.get("version", 0)) != self.STATE_VERSION:
            raise ValueError(
                f"存档版本不匹配：{payload.get('version')} != {self.STATE_VERSION}")
        game_json = payload.get("game_json")
        if not isinstance(game_json, str):
            raise ValueError("存档缺少 game_json")
        meta = dict(payload.get("meta") or {})
        game = tg.Game.from_json(game_json)
        if (bool(game.is_over()) is False
                and int(game.num_players) != int(meta.get("num_players",
                                                          game.num_players))):
            raise ValueError("存档 num_players 与引擎状态不一致")
        self._game = game
        self.num_players = int(meta.get("num_players", game.num_players))
        self.agent_index = int(meta.get("agent_index", self.agent_index))
        self._seed = int(meta.get("seed", self._seed))
        self._episode = int(meta.get("episode", 0))
        self._step_count = int(meta.get("step_count", 0))
        self._done = bool(meta.get("done", False))
        self._truncated = bool(meta.get("truncated", False))
        self._terminated_reason = str(meta.get("terminated_reason", ""))
        self._stopped_reason = str(meta.get("stopped_reason", ""))
        self._stats = {str(k): int(v)
                       for k, v in (meta.get("stats") or {}).items()}
        if not self._stats:
            self._stats = self._new_stats()
        self._restore_count = int(self._restore_count) + 1
        overrides = meta.get("config_overrides")
        if isinstance(overrides, dict):
            self._config_overrides = dict(overrides)
            self._config_json = json.dumps(self._config_overrides,
                                           sort_keys=True)
            self._cfg_effective = self._effective_config()
        self.obs_source = str(meta.get("obs_source", self.obs_source))
        self.max_steps = int(meta.get("max_steps", self.max_steps))
        saved_max_turns = meta.get("max_turns", self.max_turns)
        self.max_turns = None if saved_max_turns is None else int(saved_max_turns)
        if meta.get("illegal_penalty") is not None:
            self._illegal_penalty = float(meta["illegal_penalty"])
        self.include_action_names = bool(
            meta.get("include_action_names", self.include_action_names))
        self._closed = False
        self._obs = self._build_observation()
        return self


# ══════════════════════════════════════════════════════════════════════
# 工厂
# ══════════════════════════════════════════════════════════════════════


def make_taverngym_env(**kwargs: Any) -> TavernGymEnv:
    """创建 :class:`TavernGymEnv`（``hsbg.rl.envs.make_env`` 风格的工厂）。

    示例::

        env = make_taverngym_env(seed=0, obs_source="features")
    """
    return TavernGymEnv(**kwargs)
