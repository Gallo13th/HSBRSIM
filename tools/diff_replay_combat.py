"""差分验证：官方战斗轨迹（``official_combat_trace.v1``）vs ``hsrl2`` 引擎复现。

用法
----
::

    python tools/diff_replay_combat.py --traces runs/official_traces --limit 10
    python tools/diff_replay_combat.py --traces runs/official_traces \\
        --limit 20 --seeds 64 --json runs/diff_report.json --md runs/diff_report.md

判定口径（详见 docs/DIFF_HARNESS.md）
------------------------------------
每个轨迹独立分类：

* ``DATA_GAP`` —— 战团里有引擎 ``data/`` 缺失（或名字解析不到）的卡。
  **不计入引擎 bug**，只计入数据版本缺口（可区分「37.0 新卡」与「未知卡」）。
* ``MATCH`` —— 引擎在 N 个种子下的胜负分布与参照一致：
  - 官方结果在引擎可达结果集内，
  - 且（若 BobsBuddy 概率可得）分布 L1 距离 < ``--l1-threshold``。
* ``ENGINE_DIVERGENCE`` —— 可复现的行为不一致，附带首个分歧证据，
  按严重度排序：
  1. ``deterministic_mismatch``：BobsBuddy 判定 100% 胜/负/平，引擎却不是；
  2. ``official_result_unreachable``：官方实际结果在引擎 N 种子可达集之外
     （单样本即证明引擎把官方结果排成零概率）；
  3. ``distribution_distance``：引擎胜负分布与 BobsBuddy（第二实现）
     L1 ≥ 阈值（BobsBuddy 非官方，故归为「引擎 vs 第二实现」证据）。

RNG 说明：官方战斗只给**一次**实际结果（单样本）；「结果与引擎众数不同但
仍在引擎可达集内」记为 ``RNG_SAMPLE`` 子类，算 MATCH，不冤枉引擎。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
#: 允许把引擎/数据切到隔离目录（如 ``tmp_diff_fix``）做修复前后对比：
#:   ``$env:HSBG_ENGINE_ROOT = "C:\HSagent\tmp_diff_fix"``
#: 该目录必须同时含 ``hsrl2/`` 与 ``data/``。
ENGINE_ROOT = Path(os.environ.get("HSBG_ENGINE_ROOT", str(ROOT))).resolve()
for _path in (str(ROOT), str(ENGINE_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from hsbg.bridge import trace as T  # noqa: E402
from hsrl2.db import CardDB  # noqa: E402
from hsrl2.events import Listener  # noqa: E402
from hsrl2.game import Game  # noqa: E402
from hsrl2.hero import Hero  # noqa: E402
from hsrl2.scripts import REGISTRY  # noqa: E402
from hsrl2.tags import CardType, GameTag  # noqa: E402

ENGINE_DATA_DIR = ENGINE_ROOT / "data"
OFFICIAL_DATA_255130 = ROOT / "reversed" / "data_255130" / "bg_cards.json"
DEFAULT_TRACES_DIR = ROOT / "runs" / "official_traces"
DEFAULT_JSON = ROOT / "runs" / "diff_report.json"
DEFAULT_MD = ROOT / "runs" / "diff_report.md"

STATUS_MATCH = "MATCH"
STATUS_DATA_GAP = "DATA_GAP"
STATUS_ENGINE_DIVERGENCE = "ENGINE_DIVERGENCE"
STATUS_CONTEXT_GAP = "CONTEXT_GAP"   # 日志上下文未建模（秘密/外部亡语/技能状态）
STATUS_SKIPPED = "SKIPPED"

#: 轨迹关键词 → 引擎 GameTag
ENGINE_KEYWORD_TAGS: Dict[str, Any] = {
    "taunt": GameTag.TAUNT,
    "divine_shield": GameTag.DIVINE_SHIELD,
    "poisonous": GameTag.POISONOUS,
    "venomous": GameTag.VENOMOUS,
    "reborn": GameTag.REBORN,
    "windfury": GameTag.WINDFURY,
    "mega_windfury": GameTag.MEGA_WINDFURY,
    "cleave": GameTag.CLEAVE,
    "stealth": GameTag.STEALTH,
}

#: 引擎内部未建模的关键词（记录为 context gap，不算 DATA_GAP）
UNSUPPORTED_KEYWORDS = {"elusive", "immune"}

#: ``hero_power_data`` 存「战斗内选择目标 game_id」的技能：日志不给目标，
#: 引擎无法重建 → blocking 上下文缺口。
#:   Teron Gorefiend BG25_HERO_103p: Start of Combat 销毁/复活所选随从，
#:   data = 目标的 game_id（如 376 / 1296 / 1913）。
COMBAT_TARGET_HERO_POWERS = {"BG25_HERO_103p"}

#: 招募期技能（data 与战斗结算无关；BobsBuddy 仍会打印，但不是缺口）
RECRUIT_ONLY_HERO_POWERS = {
    "TB_BaconShop_HP_020",   # The Great Akazamzarak（买/卖触发秘密）
    "BG20_HERO_102p",        # Overlord Saurfang
    "BG20_HERO_103p",        # Death Speaker Blackthorn（招募期）
    "BG20_HERO_280p5",       # Kurtrus Ashfallen
    "BG23_HERO_304p",        # Lady Vashj
    "BG27_HERO_801p2",       # Thorim, Stormlord（Discover T7）
}

#: 可从 ``data`` **重建**状态的技能：
#:   Ozumat BG23_HERO_201p 的 data = 当前 Tentacle 数值
#:   （data == num(0) 表示无加成；data=4 表示 +2 加成，已用官方轨迹
#:   886faa18f76e10dc 验证：重建后引擎 win 16/16 = 官方）。
RECONSTRUCTIBLE_HERO_POWER_STATE = {"BG23_HERO_201p"}

# ══════════════════════════════════════════════════════════════════════
# 官方动态 ScriptDataNum → 引擎注入（2026-10-18，测量口径修正）
# ══════════════════════════════════════════════════════════════════════
#
# BobsBuddy 会为部分实体打印官方 ``ScriptDataNum1/2/3/…``（"Improve 计数"
# 类动态初值，如 Ultraviolet Ascendant 的 9/6/2、Eternal Knight 的 4/2）。
# 引擎（应用 deliver2 后）有 ``Game.set_entity_script_data`` 通道，但旧脚本
# 未必读通道 → harness 需要：
#   1) 通用：把日志里的官方值注入通道（有值才注入，无值不改默认行为）；
#   2) 已知动态属性卡：用注入值**复算**（适配器设置引擎状态/基础值），
#      使引擎输出与官方一致（Eternal Knight / Ultraviolet 族）。
# 全部在 harness 侧完成，不修改引擎文件。

#: 官方 enumID → NUM 索引（与 root `hsrl2.tags.OFFICIAL_TAG_TO_SCRIPT_DATA_NUM`
#: 同步：NUM_1=2 / NUM_2=3 / NUM_3=2889 / NUM_4=2919 / NUM_5=2920）。
try:  # 引擎已应用 deliver2 时优先用引擎映射表
    from hsrl2.tags import (
        OFFICIAL_TAG_TO_SCRIPT_DATA_NUM as _ENGINE_OFFICIAL_SDN,
    )
    OFFICIAL_TAG_TO_NUM_INDEX: Dict[int, int] = {
        int(tag): int(member.name.split("_")[1])
        for tag, member in _ENGINE_OFFICIAL_SDN.items()
    }
except Exception:  # pragma: no cover - 旧引擎兜底
    OFFICIAL_TAG_TO_NUM_INDEX = {2: 1, 3: 2, 2889: 3, 2919: 4, 2920: 5}

#: 动态属性卡适配器（harness 侧复算；ids 为普通+金色）
#: 2026-10-18 engine-analyst 完成 8 族 NUM_3 迁移后登记：脚本 =
#: base + (hero_counter + NUM_3) × step；轨迹重放时 hero_counter=0，
#: 故由 printed atk/health 反推 count 注入 NUM_3 即可精确复现面板。
DYNAMIC_STAT_SCRIPT_IDS = {
    "BG25_008", "BG25_008_G",        # Eternal Knight：+num(0)/num(1) × 死亡数
    "BG35_921", "BG35_921_G",        # Abyssal Bruiser：+2/+1 × 酒馆法术数
    "BG_TTN_401", "BG_TTN_401_G",    # Ancestral Automaton：+3/+2 × 其他自动机
    "BG35_342", "BG35_342_G",        # Falling Sky Golem：+4/+2 × 亡语数
    "BG26_537", "BG26_537_G",        # Flourishing Frostling：+2/+1 × 元素数
    "BG36_524", "BG36_524_G",        # Maritime Extortionist：+7/+7 × 金卡数
    "BG25_013", "BG25_013_G",        # Rot Hide Gnoll：+1/+2 Attack × 本场死亡
    # 饰品（无 printed atk/health）：登记仅为口径一致；适配器 guard
    # `tm.atk/health is not None` 自动跳过，不产生注入。
    "BG36_MagicItem_216",
}

#: 动态属性适配器总开关（A/B 用：`HSBG_DISABLE_DYNAMIC_ADAPTER=1`）。
#: 关闭时：不反推 count、不注入 NUM_3（避免双计），缺口保留；
#: 用于量化"适配器恢复量"（对齐 engine-analyst 迁移的 A/B 口径）。
import os as _os
ENABLE_DYNAMIC_STAT_ADAPTER = (
    _os.environ.get("HSBG_DISABLE_DYNAMIC_ADAPTER") != "1")

#: 动态属性"每计数步长"回退表（CardDef num(0)/num(1) 缺失时使用；
#: 数值来自卡面文本/迁移测试——仅这些卡，**不是**通用猜测）。
#: BG_TTN_401 文本 "+3/+2"（金色 +6/+4），CardDef num 为空；
#: BG25_013 只加攻击 "+1 Attack"（金色 +2），health 步长 0。
DYNAMIC_STAT_STEPS: Dict[str, tuple] = {
    "BG_TTN_401": (3, 2),
    "BG_TTN_401_G": (6, 4),
    "BG25_013": (1, 0),
    "BG25_013_G": (2, 0),
}

ULTRAVIOLET_IDS = {"BG31_810", "BG31_810_G"}   # Improve 计数 → SoC 数值

#: Ultraviolet 适配器开关：**默认关闭**（2026-10-18 差分实测证据不足）。
#: 官方 tag NUM_1=9 / NUM_2=6（CardDef num=3/3，trace 17493f10c0afbbad）与
#: 引擎 "mult=1+count 同时乘两个分量" 公式冲突：count=2 得 9/9 ≠ 官方 9/6。
#: 强行注入 improve 计数会让该轨迹更差（win 50%→1.6%，官方 win/BB 90.4%）。
#: 正确语义需官方 Power.log 事件或引擎公式修正，本 harness 只保留通用注入
#: 并把它记为上下文缺口；开关留作证据到位后启用。
ENABLE_ULTRAVIOLET_ADAPTER = False

#: 官方 ScriptDataNum 动态计数约定槽位（与引擎 NUM_DYNAMIC_COUNT 同义）
DYNAMIC_COUNT_INDEX = 3

#: 已注册脚本**消费** ScriptDataNum 通道的卡 → 消费的通道序号集合。
#: 这些卡的官方动态值不再算 harness 缺口（引擎脚本会读通道生效）：
#:   * BG26_502/_G Deep Blue Crooner：脚本把官方 NUM_1/NUM_2 作为当前
#:     Deep Blues 数值施加并回写（batch_diff_driven3）。
#:   * 8 族动态属性（engine-analyst 迁移）：脚本读 NUM_3 基线；只有
#:     **适配器成功反推 count 并注入**时才清缺口（见 _apply_...）。
#:   * BG36_MagicItem_216 Eternal Portrait（饰品）：脚本读 NUM_3，但
#:     trace 不提供饰品实体；`_build_side` 仅处理随从 → 不产生注入；
#:     登记保留口径一致，适配器无 printed atk/health 时跳过（见函数）。
#:   * 2026-10-18 阶段 1（engine-analyst B 类 7 张迁移安全子集）：以下
#:     4 张（8 id）脚本读 NUM_1；engine-analyst 实测无副作用 → 登记
#:     `{1}` 消除对应 `dynamic_script_data:*:1` 缺口（仅当注入+消费）：
#:       BG24_715 Patient Scout / BG33_823 飞蟒 / BG26_199 Upbeat Duo /
#:       BG26_505 深海合唱（各含金色）。
#:     阶段 2 暂缓：BG35_801 / BG35_814 / BG26_529 —— 全量登记会暴露
#:     5 条既有 behavior_mismatch（原被 context_gap 遮蔽），等
#:     engine-analyst root cause 后再登记（见 deferred_primitives.md P2b）。
#:   * **派生值 4 张不登记消费**（Forest Rover `BG31_801` /
#:     Buzzing Vermin `BG31_826`? / Felemental `BG31_809` /
#:     Catacomb Crasher `BG30_129`）：其官方 NUM_1 是**派生值**（引擎可由
#:     规则计算），harness 按"引擎计算值"比较或豁免，不把官方派生 tag
#:     当消费输入（见 docs §4.2c 派生值比较口径）。
#: 维护约定：新脚本只要在 on_summon/on_play 里读 `get_script_data`/
#: `script_data_or_card`，就把对应卡 + 序号登记到这里，避免把"已建模
#: 动态值"误记为 context_gap（测量口径：注入 + 消费 = 可建模）。
CONSUMED_SCRIPT_DATA: Dict[str, frozenset] = {
    "BG26_502": frozenset({1, 2}),
    "BG26_502_G": frozenset({1, 2}),
    "BG35_921": frozenset({3}), "BG35_921_G": frozenset({3}),
    "BG_TTN_401": frozenset({3}), "BG_TTN_401_G": frozenset({3}),
    "BG35_342": frozenset({3}), "BG35_342_G": frozenset({3}),
    "BG26_537": frozenset({3}), "BG26_537_G": frozenset({3}),
    "BG36_524": frozenset({3}), "BG36_524_G": frozenset({3}),
    "BG25_013": frozenset({3}), "BG25_013_G": frozenset({3}),
    "BG25_008": frozenset({3}), "BG25_008_G": frozenset({3}),
    # ── 阶段 1（engine-analyst B 类迁移安全子集；脚本读 NUM_1）──
    "BG24_715": frozenset({1}), "BG24_715_G": frozenset({1}),
    "BG33_823": frozenset({1}), "BG33_823_G": frozenset({1}),
    "BG26_199": frozenset({1}), "BG26_199_G": frozenset({1}),
    "BG26_505": frozenset({1}), "BG26_505_G": frozenset({1}),
    # ── 阶段 2（root cause 完成，2026-10-18 裁定后登记；正确消费槽位）──
    # BG35_801 Gluttonous Trogg 读 NUM_1；BG35_814 Scarlet Survivor 读
    # NUM_2；BG26_529 Upbeat Frontdrake 读 NUM_1。
    "BG35_801": frozenset({1}), "BG35_801_G": frozenset({1}),
    "BG35_814": frozenset({2}), "BG35_814_G": frozenset({2}),
    "BG26_529": frozenset({1}), "BG26_529_G": frozenset({1}),
    "BG36_MagicItem_216": frozenset({3}),
}


def _consumed_script_data(card_id: str) -> frozenset:
    return CONSUMED_SCRIPT_DATA.get(card_id, frozenset())

SEVERITY_ORDER = {
    "deterministic_mismatch": 0,
    "official_result_unreachable": 1,
    "event_sequence": 2,
    "distribution_distance": 3,
    "nar": 9,
}


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════
# 卡名 → 卡 id 解析
# ══════════════════════════════════════════════════════════════════════


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).casefold())


class CardResolver:
    """把日志里的卡名解析成引擎 card_id。

    * 引擎数据优先（``data/``，当前 36.2.2 基线）；
    * 官方 37.0.0 数据（``reversed/data_255130/bg_cards.json``，可选）只用于
      **归类**数据缺口：卡在官方数据里存在但引擎没有 → 数据版本升级问题。
    """

    def __init__(self, db: CardDB,
                 official_cards_path: Path | str = OFFICIAL_DATA_255130):
        self.db = db
        self.by_name: Dict[str, str] = {}
        self.ambiguous: Dict[str, List[str]] = {}
        self._build_engine_index()
        self.official_names: set[str] = set()
        path = Path(official_cards_path)
        if path.exists():
            try:
                cards = json.loads(path.read_text(encoding="utf-8"))
                for card in cards:
                    name = card.get("name")
                    if name:
                        self.official_names.add(_norm_name(name))
            except (OSError, ValueError):  # pragma: no cover
                self.official_names = set()

    def _build_engine_index(self) -> None:
        best: Dict[str, Tuple[tuple, str]] = {}
        for d in self.db._by_id.values():          # noqa: SLF001 - 引擎无公开枚举
            if d.card_type != CardType.MINION or not d.name:
                continue
            score = (
                1 if getattr(d, "is_pool_minion", False) else 0,
                0 if getattr(d, "is_golden_def", False) else 1,
                int(getattr(d, "tech_level", 0) or 0),
                int(getattr(d, "dbf_id", 0) or 0),
            )
            key = _norm_name(d.name)
            prev = best.get(key)
            if prev is None or score > prev[0]:
                best[key] = (score, d.id)
            if prev is not None and prev[1] != d.id:
                ids = self.ambiguous.setdefault(key, [prev[1]])
                if d.id not in ids:
                    ids.append(d.id)
        self.by_name = {key: value[1] for key, value in best.items()}

    def resolve(self, name: str) -> Optional[str]:
        return self.by_name.get(_norm_name(name))

    def classify_gap(self, name: str) -> str:
        """卡名解析失败时的归类。"""
        if _norm_name(name) in self.official_names:
            return "engine_data_version_gap"   # 官方 37.0 有、引擎 data/ 没有
        return "unknown_card_name"


# ══════════════════════════════════════════════════════════════════════
# 引擎复现
# ══════════════════════════════════════════════════════════════════════


def _iter_defs(db: CardDB):
    return db._by_id.values()                  # noqa: SLF001


class HeroIndex:
    """hero_power_id → 英雄 card_id（BobsBuddy 日志只给技能 id）。"""

    def __init__(self, db: CardDB):
        self.db = db
        self.by_power: Dict[str, str] = {}
        self.default_hero: Optional[str] = None
        for d in _iter_defs(db):
            if d.card_type != CardType.HERO:
                continue
            if self.default_hero is None:
                self.default_hero = d.id
            power = getattr(d, "hero_power_id", None)
            if power:
                self.by_power.setdefault(power, d.id)
        if self.default_hero is None:  # pragma: no cover - 数据损坏时
            raise RuntimeError("CardDB 里没有任何 CardType.HERO")

    def resolve(self, hero_power_id: Optional[str]) -> Tuple[str, bool]:
        if hero_power_id and hero_power_id in self.by_power:
            return self.by_power[hero_power_id], True
        return self.default_hero, False  # type: ignore[return-value]


@dataclass
class SimulationResult:
    """单条轨迹的引擎复现结果。"""

    trace_id: str
    seeds: List[int] = field(default_factory=list)
    outcomes: List[str] = field(default_factory=list)   # player 视角 win/loss/tie
    rounds: List[int] = field(default_factory=list)
    damage_dealt: List[int] = field(default_factory=list)
    event_streams: List[List[Dict[str, Any]]] = field(default_factory=list)
    data_gaps: List[Dict[str, Any]] = field(default_factory=list)
    context_gaps: List[str] = field(default_factory=list)
    engine_card_ids: Dict[str, str] = field(default_factory=dict)
    hero_info: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    #: 官方 ScriptDataNum 注入记录（有值才注入；含适配器复算标记）
    script_data_injected: List[Dict[str, Any]] = field(default_factory=list)
    #: 用官方 GAME_SEED 额外跑一遍的诊断结果（不进入 seeds 统计）
    game_seed_attempt: Optional[Dict[str, Any]] = None
    #: Deity 注入诊断（sigil 引擎未建模/awakened 被战斗重置等）
    deity_notes: List[str] = field(default_factory=list)

    def rates(self) -> Dict[str, float]:
        total = len(self.outcomes)
        if not total:
            return {}
        counter = Counter(self.outcomes)
        return {key: counter.get(key, 0) / total
                for key in (T.RESULT_WIN, T.RESULT_TIE, T.RESULT_LOSS)}


_KEYWORD_ONLY_TEXT = re.compile(
    r"<b>(?:Taunt|Reborn|Divine Shield|Poisonous|Venomous|Windfury|"
    r"Mega-Windfury|Cleave|Stealth|Elusive)</b>|"
    r"\[x\]|</?b>|\s+", re.IGNORECASE)


def _card_needs_script(card_def) -> bool:
    """该卡是否需要效果脚本。

    关键区分：**白板随从没有脚本是正常的**（属性/关键词已由数据+tag 表达），
    只有卡面文本里还有「关键词以外」的效果描述（或亡语标记）才需要脚本。
    若不区分，会把「白板/纯关键词随从」误报成引擎缺口（首版实测：200 场里
    187 场被误判为 ``no_script``；例如 Risen Rider 文本只有 Taunt/Reborn）。
    """
    if card_def is None:
        return True
    text = _KEYWORD_ONLY_TEXT.sub("", (getattr(card_def, "text", "") or "")).strip()
    if text:
        return True
    if getattr(card_def, "deathrattle", False):
        return True
    return False


def _official_script_data(tags: Mapping[str, Any]) -> Dict[int, int]:
    """解析实体官方 ``ScriptDataNum1..5``（名字键或官方 enumID 键均可）。

    日志来源有两类写法：
      * BobsBuddy：``{"ScriptDataNum1": "9", "ScriptDataNum2": "6"}``
      * Power.log：``tag=2/tag=3/tag=2889/tag=2919/tag=2920``（官方 enumID）
    """
    out: Dict[int, int] = {}
    for key, value in (tags or {}).items():
        text = str(key)
        match = re.match(r"ScriptDataNum(\d+)", text, re.IGNORECASE)
        if match:
            index = int(match.group(1))
        else:
            tag = _int_or_none(text)
            index = OFFICIAL_TAG_TO_NUM_INDEX.get(tag) if tag is not None \
                else None
        if index is None or not 1 <= index <= 5:
            continue
        parsed = _int_or_none(value)
        if parsed is not None:
            out[index] = parsed
    return out


def _apply_official_script_data(game: Any, minion: Any, card_id: str,
                                tm: T.TraceMinion,
                                result: SimulationResult,
                                side: str) -> bool:
    """把官方 ScriptDataNum 注入引擎；返回是否走了「动态属性复算」适配器。

    * **通用**：有官方值才注入（``Game.set_entity_script_data``），无值不改
      引擎默认行为；旧引擎无该 API 时静默跳过（保持向后兼容）。
    * **Eternal Knight 族**（``DYNAMIC_STAT_SCRIPT_IDS``）：日志打印的
      atk/health 已含「本局死亡数 × num(0)/num(1)」加成。若直接写 BASE 数值
      再注入计数会**双计**（脚本会再叠加一次）。适配器改为：
        1) BASE 数值写回**卡面基础值**；
        2) 由 ``(printed - base) / num`` 反推官方死亡计数，注入 ``NUM_3``；
        3) 引擎动态属性脚本复算 → 精确等于官方 printed 数值。
      成功后移除 ``dynamic_stat_script`` 阻断缺口（该缺口已被注入消解）。
    * **Ultraviolet 族**（``ULTRAVIOLET_IDS``）：引擎 37.x 脚本把 Improve
      计数存在 Python 属性 ``_ultraviolet_improves``（先于 ScriptDataNum
      通道实现），harness 侧按官方 ``NUM_3`` 适配写入。
    """
    official = _official_script_data(tm.tags)
    # 注意：动态属性族即使 trace **没有** ScriptDataNum 标签，也能从
    # printed atk/health 反推 count（面板已含动态加成）→ 适配器必须先于
    # "无官方标签则跳过"的早退判断运行。
    # **金色感知**：create_minion(golden=True) 会把 minion.card_id 换成金色
    # CardDef（基础值与 num 都是金色版）。适配器反推计数/写基础值必须用
    # minion 实际 CardDef，否则金色会双重错算。
    card_def = game.db.get(getattr(minion, "card_id", card_id))
    if card_def is None:
        card_def = game.db.get(card_id)
    adapted = False
    values = dict(official)

    # ── 适配器 1：动态属性族（printed 面板 → 反推 count → 注入 NUM_3）──
    # 覆盖 engine-analyst 迁移的 8 族（+ Eternal Knight）：脚本公式 =
    # base + (hero_counter + NUM_3) × step；轨迹重放 hero_counter=0，
    # 故 BASE 写卡面基础值 + NUM_3=count 可精确复现 printed 面板。
    adapter_skip = None
    if (ENABLE_DYNAMIC_STAT_ADAPTER
            and card_id in DYNAMIC_STAT_SCRIPT_IDS
            and card_def is not None
            and tm.atk is not None and tm.health is not None):
        base_atk = int(getattr(card_def, "atk", 0) or 0)
        base_health = int(getattr(card_def, "health", 0) or 0)
        num_atk = getattr(card_def, "num", lambda _i: None)(0)
        num_health = getattr(card_def, "num", lambda _i: None)(1)
        fallback = DYNAMIC_STAT_STEPS.get(card_id)
        if fallback is not None:
            step_atk = fallback[0] if num_atk is None else int(num_atk)
            step_health = (fallback[1] if num_health is None
                           else int(num_health))
        else:
            step_atk = 0 if num_atk is None else int(num_atk)
            step_health = 0 if num_health is None else int(num_health)
        candidates = []
        mismatch = False
        if step_atk > 0:
            delta = int(tm.atk) - base_atk
            if delta >= 0 and delta % step_atk == 0:
                candidates.append(delta // step_atk)
            else:
                mismatch = True
        if step_health > 0:
            delta_h = int(tm.health) - base_health
            if delta_h >= 0 and delta_h % step_health == 0:
                candidates.append(delta_h // step_health)
            else:
                mismatch = True
        # 两个维度反推出的计数必须一致且非负；任一维度无法整除（面板
        # 还含其它附魔/光环/宝石）→ 无法分离，不强行清缺口，保留证据。
        count = None
        if not mismatch and candidates and len(set(candidates)) == 1:
            count = candidates[0]
        if count is not None:
            minion.set(GameTag.BASE_ATK, base_atk)
            minion.set(GameTag.BASE_HEALTH, base_health)
            minion.set(GameTag.ATK, base_atk)
            minion.set(GameTag.HEALTH, base_health)
            values[DYNAMIC_COUNT_INDEX] = int(count)
            result.context_gaps[:] = [
                gap for gap in result.context_gaps
                if gap != "dynamic_stat_script"
                and not gap.startswith(f"dynamic_script_data:{card_id}:")]
            adapted = True
        else:
            # 反推失败：不要把官方 NUM_3 直接注入（脚本会在 printed BASE
            # 之上再叠一次 → 双计）；移除该槽位、保留缺口待逐卡排查。
            values.pop(DYNAMIC_COUNT_INDEX, None)
            adapter_skip = (
                f"printed={tm.atk}/{tm.health} base={base_atk}/{base_health}"
                f" step={step_atk}/{step_health}")
    elif (not ENABLE_DYNAMIC_STAT_ADAPTER
          and card_id in DYNAMIC_STAT_SCRIPT_IDS):
        # A/B 关闭态：脚本仍会读 NUM_3 → 绝不能注入官方值（会双计），
        # 保留 printed BASE + 缺口（与迁移前行为一致）。
        values.pop(DYNAMIC_COUNT_INDEX, None)
        adapter_skip = "adapter_disabled"

    # ── 适配器 2：Ultraviolet 族（Improve 计数 → 引擎脚本属性）──
    # 默认关闭：官方 tag（NUM_1=9/NUM_2=6）与引擎公式（mult 同时乘两分量）
    # 冲突，注入会恶化结果；保留开关等待官方事件证据（见常量注释）。
    if (ENABLE_ULTRAVIOLET_ADAPTER and card_id in ULTRAVIOLET_IDS
            and DYNAMIC_COUNT_INDEX in values):
        try:
            minion._ultraviolet_improves = int(values[DYNAMIC_COUNT_INDEX])
            adapted = True
        except Exception:  # noqa: BLE001 - 纯 Python 属性，正常不会失败
            pass

    # ── 通道消费卡（脚本直接读 NUM_n，无需改基础值）──
    # 例：Deep Blue Crooner 的脚本把官方 NUM_1/NUM_2 当当前 Deep Blues
    # 数值读取并回写 → 官方动态值不再是"未建模缺口"（测量口径：注入+消费）。
    # 动态属性族：只有**适配器成功反推并注入 NUM_3**才算"注入+消费"；
    # 反推失败时必须保留缺口（不把"注入了但数值不对"当已建模）。
    consumed = _consumed_script_data(card_id)
    if card_id in DYNAMIC_STAT_SCRIPT_IDS and not adapted:
        consumed_hit = []
    else:
        consumed_hit = sorted(n for n in values if n in consumed)
    if consumed_hit:
        adapted = True

    if not values and not adapted \
            and card_id not in DYNAMIC_STAT_SCRIPT_IDS:
        return False

    # ── 通用注入（有值才注入；旧引擎无 API 时跳过）──
    setter = getattr(game, "set_entity_script_data", None)
    if setter is not None:
        try:
            setter(minion, values)
        except Exception:  # noqa: BLE001 - 注入失败不阻断差分
            pass
    payload = {
        "side": side,
        "card_id": card_id,
        "name": tm.name,
        "values": dict(values),
        "adapted": adapted,
        "consumed": consumed_hit,
    }
    if adapter_skip is not None:
        payload["adapter_skip"] = adapter_skip
    result.script_data_injected.append(payload)
    return adapted


def _build_side(game: Game, hero: Hero, warband: T.Warband,
                resolver: CardResolver,
                result: SimulationResult, side: str,
                *, inject_script_data: bool = True) -> List[Any]:
    """把轨迹战团构造成引擎 Minion（数值/关键词按日志精确写入）。"""
    placed = []
    for tm in warband.minions:
        card_id = resolver.resolve(tm.name) if tm.name else tm.card_id
        if card_id is None or game.db.get(card_id) is None:
            result.data_gaps.append({
                "side": side,
                "slot": tm.slot,
                "name": tm.name,
                "gap": "missing_card" if card_id else
                       resolver.classify_gap(tm.name),
            })
            continue
        try:
            minion = game.create_minion(card_id, controller=hero,
                                        golden=bool(tm.golden))
        except Exception as exc:  # noqa: BLE001 - 引擎异常要记录不能崩
            result.errors.append(f"{side}.slot{tm.slot}:{card_id}:{exc}")
            continue
        if minion is None:
            result.data_gaps.append({"side": side, "slot": tm.slot,
                                     "name": tm.name, "gap": "null_def"})
            continue
        if tm.atk is not None:
            minion.set(GameTag.BASE_ATK, tm.atk)
            minion.set(GameTag.ATK, tm.atk)
        if tm.health is not None:
            minion.set(GameTag.BASE_HEALTH, tm.health)
            minion.set(GameTag.HEALTH, tm.health)
        for keyword in tm.keywords:
            tag = ENGINE_KEYWORD_TAGS.get(keyword)
            if tag is not None:
                minion.set(tag, True)
            elif keyword in UNSUPPORTED_KEYWORDS:
                if "unsupported_keyword" not in result.context_gaps:
                    result.context_gaps.append("unsupported_keyword")
            else:
                result.context_gaps.append(f"unknown_keyword:{keyword}")
        card_def = game.db.get(card_id)
        for key, value in tm.tags.items():
            if key.lower().startswith("deathrattles"):
                # BobsBuddy 打印的是「该随从当前实际拥有的亡语列表」，其中
                # 可能含**外部授予**的亡语（Spellcraft/饰品/英雄技能，如
                # GenericDeathrattles.Crab）。发动机只按卡脚本复现自身亡语，
                # 因此该标注一律记为未建模上下文（blocking），不当作引擎 bug。
                note = f"deathrattle_annotation:{card_id}"
                if note not in result.context_gaps:
                    result.context_gaps.append(note)
        # 官方动态 ScriptDataNum：有值才注入；动态属性卡走复算适配器。
        if inject_script_data:
            adapted = _apply_official_script_data(
                game, minion, card_id, tm, result, side)
        else:
            adapted = False
        # 关键测量口径：只有**适配器/通道消费卡确认引擎消费了该通道**时，
        # 才清除 dynamic_script_data 缺口；否则（引擎脚本不读通道）官方动态
        # 值仍然无法被引擎利用 → 保留 blocking 缺口，避免把"注入了但引擎
        # 没用"误记成 behavior_mismatch（2026-10-18 差分实测教训）。
        consumed = (_consumed_script_data(card_id)
                    if inject_script_data else frozenset())
        for number, official_value in _official_script_data(tm.tags).items():
            if number in consumed:
                continue
            engine_value = getattr(
                card_def, f"script_data_num_{number}", None)
            if engine_value is None or int(engine_value) != int(official_value):
                note = f"dynamic_script_data:{card_id}:{number}"
                if note not in result.context_gaps:
                    result.context_gaps.append(note)
        game.summon(hero, minion)
        placed.append(minion)
        result.engine_card_ids.setdefault(tm.name, card_id)
        if _card_needs_script(game.db.get(card_id)) and card_id not in REGISTRY:
            note = f"no_script:{card_id}"
            if note not in result.context_gaps:
                result.context_gaps.append(note)
        script = getattr(minion, "scripts", None)
        if (not adapted and script is not None
                and (callable(getattr(script, "atk", None))
                     or callable(getattr(script, "health", None)))):
            if "dynamic_stat_script" not in result.context_gaps:
                result.context_gaps.append("dynamic_stat_script")
    return placed


class _EventRecorder:
    """战斗事件捕获（与轨迹事件同口径：attack/damage/death/summon）。"""

    def __init__(self, game: Game, slots: Dict[int, Tuple[str, int]]):
        self.game = game
        self.slots = slots
        self.events: List[Dict[str, Any]] = []
        self._register()

    def _side_slot(self, minion) -> Tuple[Optional[str], Optional[int]]:
        if minion is None:
            return None, None
        return self.slots.get(id(minion), (None, None))

    def _register(self) -> None:
        game = self.game

        def on_attack(g, attacker=None, defender=None, **_kw):
            aside, aslot = self._side_slot(attacker)
            dside, dslot = self._side_slot(defender)
            self.events.append({"kind": "attack", "actor_side": aside,
                                "actor_slot": aslot, "target_side": dside,
                                "target_slot": dslot})

        def on_damage(g, minion=None, amount=None, **_kw):
            side, slot = self._side_slot(minion)
            self.events.append({"kind": "damage", "target_side": side,
                                "target_slot": slot, "amount": amount})

        def on_death(g, minion=None, **_kw):
            side, slot = self._side_slot(minion)
            self.events.append({"kind": "death", "target_side": side,
                                "target_slot": slot,
                                "card_id": getattr(minion, "card_id", None)})

        def on_summon(g, minion=None, **_kw):
            side, slot = self._side_slot(minion)
            self.events.append({"kind": "summon", "actor_side": side,
                                "actor_slot": slot,
                                "card_id": getattr(minion, "card_id", None)})

        game.events.register(Listener(event="before_attack", owner=None,
                                      callback=on_attack))
        game.events.register(Listener(event="damage", owner=None,
                                      callback=on_damage))
        game.events.register(Listener(event="death", owner=None,
                                     callback=on_death))
        game.events.register(Listener(event="summon", owner=None,
                                     callback=on_summon))


def _hero_power_state_gap(db: CardDB, side: str,
                          band: T.Warband) -> Optional[str]:
    """``used/data`` 里哪些是真正无法重建的上下文缺口。

    2026-10-18 修正（rea-operator 证据）：``data`` 有 2 种语义——
    * **静态参数**：data == 技能 CardDef 的 ``script_data_num_1``
      （Ozumat data=2 == num(0)=2；For the Horde! data=3 == num(0)）→
      不是缺口；旧逻辑把它当 blocking，把真引擎 bug（Ozumat 召唤 7 只
      Tentacle）吞成了 CONTEXT_GAP；
    * **战斗内目标**：Teron Gorefiend 的 data = 被销毁/复活随从的
      game_id → 日志无法给出目标，记为 blocking 缺口。
    招募期技能（Akazamzarak/Saurfang/Kurtrus/Thorim...）与战斗无关。
    """
    data = band.hero_power_data
    power_id = band.hero_power_id
    if data in (None, 0) or not power_id:
        return None
    if power_id in COMBAT_TARGET_HERO_POWERS:
        return f"hero_power_target_unresolved:{side}:{power_id}:{data}"
    if power_id in RECONSTRUCTIBLE_HERO_POWER_STATE:
        return None                           # simulate_trace 会重建该状态
    power_def = db.get(power_id)
    static = getattr(power_def, "script_data_num_1", None) \
        if power_def is not None else None
    if static is not None:
        try:
            if int(static) == int(data):
                return None
        except (TypeError, ValueError):
            pass
    if power_id in RECRUIT_ONLY_HERO_POWERS:
        return None
    return f"hero_power_state:{side}:{power_id}:{data}"


def _inject_damage_cap(game: Any, trace: T.OfficialCombatTrace) -> Optional[str]:
    """把 trace 里的官方伤害上限注入引擎（官方一致性 P1）。

    官方上限来自 Power.log GameEntity tag ``BACON_COMBAT_DAMAGE_CAP`` /
    ``..._ENABLED``（见 ``hsbg.bridge.trace``）；引擎（应用修复包后）
    提供 ``Game.set_damage_cap(value, enabled=...)``。
    未给 tag → 不动默认 turn 表；引擎无该 API → 返回缺口原因。
    """
    if trace.damage_cap is None and trace.damage_cap_enabled is None:
        return None
    setter = getattr(game, "set_damage_cap", None)
    if setter is None:
        return "damage_cap_api_unavailable"
    enabled = trace.damage_cap_enabled is not False
    setter(trace.damage_cap, enabled=enabled)
    return None


def _reconstruct_hero_power_state(db: CardDB, game: Game, hero: Hero,
                                  band: T.Warband) -> None:
    """把日志里的 ``data`` 重建为引擎状态（目前只支持 Ozumat）。

    Ozumat: ``data`` = 当前 Tentacle 数值；引擎脚本用 ``hero._ozumat_bonus``
    （= 数值 - num(0)）计算召唤物属性。
    """
    power_id = band.hero_power_id
    if power_id not in RECONSTRUCTIBLE_HERO_POWER_STATE:
        return
    data = band.hero_power_data
    if data in (None, 0):
        return
    power_def = db.get(power_id)
    static = getattr(power_def, "script_data_num_1", None) or 0
    try:
        bonus = int(data) - int(static)
    except (TypeError, ValueError):
        return
    if bonus <= 0:
        return
    if power_id == "BG23_HERO_201p":
        hero._ozumat_bonus = bonus


def _inject_deity(game: Any, hero: Any, band: T.Warband,
                   result: SimulationResult) -> None:
    """把 trace/state 的 Deity 六字段注入引擎（F-15 API 优先）。

    F-15：``inject_deity_state`` 注入官方战斗边界快照（injected=True，
    `_reset_deity_combat` 不覆盖 progress/awakened）、sigil 对象与可选
    board tokens；旧引擎 fallback 到 select_deity/give_deity_stats。
    """
    deity = getattr(band, "deity", None) or {}
    if not deity:
        return
    card = deity.get("deity_card_id")
    if not card:
        result.context_gaps.append("deity_hidden")
        return
    notes = result.deity_notes
    atk = deity.get("deity_atk")
    health = deity.get("deity_health")
    progress = deity.get("deity_progress") or 0
    awakened = bool(deity.get("deity_awakened"))
    sigil = deity.get("deity_sigil_card_id")
    tokens = deity.get("deity_board_tokens") or []
    injected = False
    try:
        if hasattr(game, "inject_deity_state"):
            game.inject_deity_state(
                hero, card_id=str(card),
                atk=int(atk) if atk is not None else 1,
                health=int(health) if health is not None else 1,
                progress=int(progress), awakened=awakened,
                sigil_card_id=str(sigil) if sigil else None,
                board_tokens=tokens or None)
            injected = True
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"deity_inject_state:{card}:{exc}")
    if not injected:
        try:
            state = game.select_deity(hero, str(card))
            if atk is not None and health is not None:
                game.give_deity_stats(hero, int(atk) - 1, int(health) - 1)
                state = getattr(hero, "deity", state)
            state.progress = int(progress)
            state.awakened = awakened
            if awakened:
                notes.append("deity_awakened_not_injectable")
            if sigil:
                notes.append(f"deity_sigil_ignored:{sigil}")
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"deity_select:{card}:{exc}")
    if sigil and not injected:
        notes.append(f"deity_sigil_ignored:{sigil}")


def simulate_trace(trace: T.OfficialCombatTrace, db: CardDB,
                   resolver: CardResolver,
                   hero_index: HeroIndex,
                   *,
                   seeds: int = 64,
                   seed_base: int = 0,
                   hero_powers: str = "on_bind",
                   inject_script_data: bool = True,
                   capture_events: bool = False) -> SimulationResult:
    """用引擎复现一场战斗，返回 N 个独立种子的结果。"""
    result = SimulationResult(trace_id=trace.trace_id)
    hero_a_id, a_ok = hero_index.resolve(trace.player.hero_power_id)
    hero_b_id, b_ok = hero_index.resolve(trace.opponent.hero_power_id)
    result.hero_info = {
        "player_hero_id": hero_a_id,
        "player_hero_power_id": trace.player.hero_power_id,
        "player_power_resolved": a_ok,
        "opponent_hero_id": hero_b_id,
        "opponent_hero_power_id": trace.opponent.hero_power_id,
        "opponent_power_resolved": b_ok,
    }
    if not a_ok:
        result.context_gaps.append("player_hero_power_unknown")
    if not b_ok:
        result.context_gaps.append("opponent_hero_power_unknown")
    if trace.player.second_hero_power_id or trace.opponent.second_hero_power_id:
        result.context_gaps.append("second_hero_power_ignored")
    if trace.player.hand or trace.opponent.hand:
        result.context_gaps.append("hand_not_modeled")
    # 未建模的官方上下文（2026-10-18 修正：这类此前被误判成引擎 bug）：
    #   * BG 秘密（BobsBuddy 的 "Detected the following player S." 段，
    #     e.g. Pack Tactics 会在友方随从被攻击时召唤 3/3 复制）；
    #   * 动态属性脚本（Eternal Knight 之类副本数在引擎侧无法重建）；
    #   * 英雄技能状态（used/data）——**必须分类**：BobsBuddy 的 data 是
    #     技能 `power def` 的第一个 script_data（静态参数，如 Ozumat
    #     data=2 == num(0)=2）时不构成缺口；只有「战斗内选择目标」类技能
    #     （Teron Gorefiend: data 存目标 game_id）才无法重建。
    for side_name, band in (("player", trace.player),
                            ("opponent", trace.opponent)):
        for item in band.detected:
            result.context_gaps.append(
                f"detected_effect:{side_name}:{item.get('kind', '?')}:"
                f"{item.get('value', '?')}")
        gap = _hero_power_state_gap(db, side_name, band)
        if gap:
            result.context_gaps.append(gap)

    normal_seeds = [seed_base + offset for offset in range(int(seeds))]
    attempt_seed: Optional[int] = None
    if trace.game_seed is not None:
        # 诊断用：把官方 GAME_SEED 作为一个额外 seed 跑一遍（不进入 64
        # seeds 统计）。官方 RNG 算法/整局消耗与引擎 random.Random 不同，
        # 不能指望复现 attack order；此字段仅用于"seed 是否可对齐"分析。
        attempt_seed = int(trace.game_seed) % (2 ** 31 - 1)
        if attempt_seed <= 0:
            attempt_seed = 1
    seed_values = list(normal_seeds)
    if attempt_seed is not None and attempt_seed not in seed_values:
        seed_values.append(attempt_seed)

    for run_index, seed in enumerate(seed_values):
        is_attempt = (attempt_seed is not None
                      and run_index == len(seed_values) - 1
                      and seed == attempt_seed
                      and seed not in normal_seeds)
        hero_a = Hero(hero_a_id, "P")
        hero_b = Hero(hero_b_id, "O")
        game = Game([hero_a, hero_b], db, seed=seed)
        game.turn = int(trace.turn or 1)
        cap_issue = _inject_damage_cap(game, trace)
        if cap_issue and cap_issue not in result.context_gaps:
            result.context_gaps.append(cap_issue)
        if hero_powers == "on_bind":
            for hero, power_id in (
                    (hero_a, trace.player.hero_power_id),
                    (hero_b, trace.opponent.hero_power_id)):
                if power_id:
                    try:
                        game.wire_hero_power_on_bind(hero, power_id)
                    except Exception as exc:  # noqa: BLE001
                        result.errors.append(f"wire_power:{power_id}:{exc}")
        _reconstruct_hero_power_state(db, game, hero_a, trace.player)
        _reconstruct_hero_power_state(db, game, hero_b, trace.opponent)
        _inject_deity(game, hero_a, trace.player, result)
        _inject_deity(game, hero_b, trace.opponent, result)
        side_heroes = {"player": hero_a, "opponent": hero_b}
        slots: Dict[int, Tuple[str, int]] = {}
        for side, band, hero in (("player", trace.player, hero_a),
                                 ("opponent", trace.opponent, hero_b)):
            placed = _build_side(game, hero, band, resolver, result, side,
                                 inject_script_data=inject_script_data)
            for index, minion in enumerate(placed):
                slots[id(minion)] = (side, index)
        recorder = _EventRecorder(game, slots) \
            if (capture_events or is_attempt) else None
        try:
            combat = game.run_combat(hero_a, hero_b)
        except Exception as exc:  # noqa: BLE001 - 引擎异常不能中断批处理
            result.errors.append(f"seed{seed}:run_combat:{exc}")
            continue
        if combat.winner is hero_a:
            outcome = T.RESULT_WIN
        elif combat.winner is hero_b:
            outcome = T.RESULT_LOSS
        else:
            outcome = T.RESULT_TIE
        if recorder is None and is_attempt:
            recorder = _EventRecorder(game, slots)
        if is_attempt:
            result.game_seed_attempt = {
                "game_seed": int(trace.game_seed),
                "seed": seed,
                "outcome": outcome,
                "events": list(recorder.events) if recorder is not None else [],
            }
        else:
            result.seeds.append(seed)
            result.outcomes.append(outcome)
            result.rounds.append(int(getattr(combat, "rounds", 0) or 0))
            result.damage_dealt.append(
                int(getattr(combat, "damage_dealt", 0) or 0))
            if recorder is not None:
                result.event_streams.append(recorder.events)
    # 去重（每个种子都会重复记录一次缺口/错误）
    seen: set = set()
    unique_gaps = []
    for gap in result.data_gaps:
        key = (gap.get("side"), gap.get("slot"), gap.get("name"),
               gap.get("gap"))
        if key in seen:
            continue
        seen.add(key)
        unique_gaps.append(gap)
    result.data_gaps = unique_gaps
    result.errors = list(dict.fromkeys(result.errors))
    # ScriptDataNum 注入记录同样按种子去重（同一实体每种子重建一次）
    seen_inject: set = set()
    unique_injected = []
    for item in result.script_data_injected:
        key = (item.get("side"), item.get("card_id"), item.get("name"),
               tuple(sorted(item.get("values", {}).items())),
               bool(item.get("adapted")))
        if key in seen_inject:
            continue
        seen_inject.add(key)
        unique_injected.append(item)
    result.script_data_injected = unique_injected
    return result


# ══════════════════════════════════════════════════════════════════════
# 差分判定（纯函数，可单测）
# ═════════════════════════════════════════════════════════════════════


def _argmax_rates(rates: Mapping[str, float]) -> Optional[str]:
    if not rates:
        return None
    order = (T.RESULT_WIN, T.RESULT_TIE, T.RESULT_LOSS)
    best = max(order, key=lambda k: rates.get(k, 0.0))
    return best if rates.get(best, 0.0) > 0 else None


def compare_combat(
    outcomes: Sequence[str],
    *,
    official_result: Optional[str],
    bb_rates: Optional[Mapping[str, float]] = None,
    data_gaps: Sequence[Mapping[str, Any]] = (),
    context_gaps: Sequence[str] = (),
    l1_threshold: float = 0.15,
    deterministic_threshold: float = 0.999,
    unreachable_min_seeds: int = 32,
    deterministic_min_rate: float = 0.99,
) -> Dict[str, Any]:
    """对一场战斗的引擎结果做分类（纯函数，不碰引擎）。"""
    n = len(outcomes)
    counts = Counter(outcomes)
    engine_rates = {
        key: counts.get(key, 0) / n for key in
        (T.RESULT_WIN, T.RESULT_TIE, T.RESULT_LOSS)
    } if n else {}
    engine_mode = _argmax_rates(engine_rates)
    evidence: Dict[str, Any] = {
        "engine_seeds": n,
        "engine_rates": engine_rates,
        "engine_mode": engine_mode,
        "official_result": official_result,
        "bb_rates": dict(bb_rates) if bb_rates else None,
    }
    context = list(context_gaps)

    # ── 1. 数据缺口：不能模拟，不算引擎 bug ────────────────────────
    if data_gaps:
        return {
            "status": STATUS_DATA_GAP,
            "subclass": "missing_cards",
            "confidence": "high",
            "evidence": {**evidence,
                         "data_gaps": [dict(g) for g in data_gaps]},
            "context_gaps": context,
            "official_in_support": None,
            "l1_distance": None,
        }
    if n == 0:
        return {
            "status": STATUS_SKIPPED,
            "subclass": "no_engine_result",
            "confidence": "low",
            "evidence": evidence,
            "context_gaps": context,
            "official_in_support": None,
            "l1_distance": None,
        }

    official_in_support = (None if official_result is None
                           else official_result in counts)
    evidence["official_in_support"] = official_in_support
    l1 = None
    mode_match = None
    if bb_rates:
        bb_norm = {
            T.RESULT_WIN: float(bb_rates.get("win", 0.0)),
            T.RESULT_TIE: float(bb_rates.get("tie", 0.0)),
            T.RESULT_LOSS: float(bb_rates.get("loss", 0.0)),
        }
        total = sum(bb_norm.values()) or 1.0
        bb_norm = {k: v / total for k, v in bb_norm.items()}
        l1 = 0.5 * sum(abs(engine_rates.get(k, 0.0) - bb_norm.get(k, 0.0))
                       for k in bb_norm)
        bb_mode = _argmax_rates(bb_norm)
        mode_match = (bb_mode == engine_mode)
        evidence.update({"bb_rates_normalized": bb_norm, "bb_mode": bb_mode,
                         "mode_match": mode_match})

    confidence = "high" if not context else "medium"

    # ── 2. 确定性战斗：第二实现 100% 的结论，引擎必须一致 ─────────
    if bb_rates:
        bb_mode = evidence.get("bb_mode")
        bb_max = max(
            float(bb_rates.get("win", 0.0)),
            float(bb_rates.get("tie", 0.0)),
            float(bb_rates.get("loss", 0.0)))
        if bb_mode is not None and bb_max >= deterministic_threshold:
            actual = engine_rates.get(bb_mode, 0.0)
            if actual < deterministic_min_rate:
                return {
                    "status": STATUS_ENGINE_DIVERGENCE,
                    "subclass": "deterministic_mismatch",
                    "confidence": "high" if not context else "medium",
                    "evidence": {**evidence,
                                 "expected_outcome": bb_mode,
                                 "expected_rate": 1.0,
                                 "engine_rate_of_expected": actual},
                    "context_gaps": context,
                    "official_in_support": official_in_support,
                    "l1_distance": l1,
                }

    # ── 3. 官方结果在引擎可达集之外 ────────────────────────────────
    if (official_result is not None and not official_in_support
            and n >= int(unreachable_min_seeds)):
        return {
            "status": STATUS_ENGINE_DIVERGENCE,
            "subclass": "official_result_unreachable",
            "confidence": confidence,
            "evidence": {**evidence,
                         "official_result_missing_from_engine": official_result},
            "context_gaps": context,
            "official_in_support": False,
            "l1_distance": l1,
        }

    # ── 4. 分布距离（引擎 vs BobsBuddy 第二实现）──────────────────
    if l1 is not None and l1 >= float(l1_threshold):
        return {
            "status": STATUS_ENGINE_DIVERGENCE,
            "subclass": "distribution_distance",
            "confidence": confidence,
            "evidence": {**evidence, "l1_distance": l1},
            "context_gaps": context,
            "official_in_support": official_in_support,
            "l1_distance": l1,
        }

    # ── 5. 一致 ───────────────────────────────────────────────────
    if official_result is not None and official_result != engine_mode:
        subclass = "rng_sample"          # 单样本偏离众数但仍在可达集
    elif l1 is not None:
        subclass = "distribution_match"
    else:
        subclass = "outcome_match"
    return {
        "status": STATUS_MATCH,
        "subclass": subclass,
        "confidence": confidence,
        "evidence": {**evidence, "l1_distance": l1},
        "context_gaps": context,
        "official_in_support": official_in_support,
        "l1_distance": l1,
    }


def _event_dict(event: Any) -> Dict[str, Any]:
    """事件统一成 dict：HDT 轨迹是 dict，Power.log 轨迹是 CombatEvent
    dataclass（同一字段集合）→ 事件级对齐必须两者都能处理。"""
    if isinstance(event, Mapping):
        return dict(event)
    to_dict = getattr(event, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    return dict(getattr(event, "__dict__", {}))


def _event_key(event: Any) -> tuple:
    data = _event_dict(event)
    return (
        data.get("kind"),
        data.get("actor_side"), data.get("actor_slot"),
        data.get("target_side"), data.get("target_slot"),
        data.get("amount") if data.get("kind") == "damage" else None,
    )


def _classify_event_diff(off: Sequence[Dict[str, Any]],
                         eng: Sequence[Dict[str, Any]],
                         index: int) -> str:
    """首个事件分歧粗分类（供 Power.log 事件级报告/归因）。"""
    o, e = off[index], eng[index]
    ok, ek = o.get("kind"), e.get("kind")
    if ok != ek:
        return "event_kind"
    if ok == "attack":
        if ((o.get("actor_side"), o.get("actor_slot"))
                == (e.get("target_side"), e.get("target_slot"))
                and (o.get("target_side"), o.get("target_slot"))
                == (e.get("actor_side"), e.get("actor_slot"))):
            return "attack_side_swap"
        if o.get("actor_side") != e.get("actor_side"):
            return "attack_order_side"
        return "attack_order_slot"
    if ok == "damage":
        return "damage_amount" if o.get("amount") != e.get("amount") \
            else "damage_target"
    if ok == "death":
        return "death_order"
    if ok == "summon":
        return "summon_order"
    return "event_slots"


def compare_events(official_events: Sequence[Any],
                   engine_events: Sequence[Any]) -> Dict[str, Any]:
    """事件流对齐（按 seq，槽位口径），返回首个分歧。"""
    off = [_event_dict(e) for e in official_events]
    eng = [_event_dict(e) for e in engine_events]
    length = min(len(off), len(eng))
    for index in range(length):
        if _event_key(off[index]) != _event_key(eng[index]):
            return {
                "diverged": True,
                "index": index,
                "classification": _classify_event_diff(off, eng, index),
                "official": dict(off[index]),
                "engine": dict(eng[index]),
                "context_official": [dict(e) for e in off[max(0, index - 3):index + 3]],
                "context_engine": [dict(e) for e in eng[max(0, index - 3):index + 3]],
            }
    if len(off) != len(eng):
        return {
            "diverged": True,
            "index": length,
            "subclass": "tail_length",
            "official_len": len(off),
            "engine_len": len(eng),
        }
    return {"diverged": False, "events": len(off)}


# ══════════════════════════════════════════════════════════════════════
# 批量差分
# ══════════════════════════════════════════════════════════════════════


def sanity_check_trace(trace: T.OfficialCombatTrace) -> Optional[str]:
    """轨迹自洽性检查。返回跳过原因（None = 可用于差分）。

    真实日志里有少量**不可比**样本，若不剔除会污染分歧统计：

    * ``invalid_warband_size``：战团 > 7（正常 BG 上限；>7 说明日志把
      Duos 双方棋盘/观战视角拼在一起，例如 13 个随从）。
    * ``empty_warbands``：双方都空（没有战斗可复现）。
    * ``inconsistent_official_trace``：一侧空场却「空场方赢」（正常 BG
      不可能：空场=被打，必然失败）——来自 Duos/观战/断线重连日志。
    """
    player_n = len(trace.player.minions)
    opponent_n = len(trace.opponent.minions)
    if player_n > 7 or opponent_n > 7:
        return "invalid_warband_size"
    if player_n == 0 and opponent_n == 0:
        return "empty_warbands"
    result = trace.official_result
    if result is not None:
        if opponent_n == 0 and player_n > 0 and result != T.RESULT_WIN:
            return "inconsistent_official_trace"
        if player_n == 0 and opponent_n > 0 and result == T.RESULT_WIN:
            return "inconsistent_official_trace"
    return None


#: 分歧归因优先级（越小越优先处理）
ATTRIBUTION_PRIORITY = {
    "behavior_mismatch": 0,        # 无任何已知识别缺口 → 最可疑的引擎 bug
    "unmodeled_context": 1,
    "unmodeled_dynamic_state": 2,
    "missing_script": 3,           # 已知：引擎缺该卡脚本（可排期补）
    "consistent": 9,
}


def attribute_divergence(comparison: Mapping[str, Any],
                         context_gaps: Sequence[str]) -> Dict[str, Any]:
    """给分歧归因（决定它在报告里的优先级 / 是否算引擎 bug）。"""
    if comparison.get("status") not in (STATUS_ENGINE_DIVERGENCE,
                                        STATUS_CONTEXT_GAP):
        return {"attribution": "consistent", "suspect_cards": []}
    gaps = list(context_gaps)
    no_script = [g.split(":", 1)[1] for g in gaps if g.startswith("no_script:")]
    if no_script:
        return {"attribution": "missing_script", "suspect_cards": no_script}
    # 官方上下文未建模（blocking）：BG 秘密 / 外部亡语 / 技能累积状态 /
    # 动态属性脚本 —— 这些轨迹**不能**用来指控引擎行为错误。
    detected = [g for g in gaps if g.startswith("detected_effect:")]
    if detected:
        return {"attribution": "unmodeled_context", "suspect_cards": [],
                "context": detected}
    dynamic = [g for g in gaps if g.startswith(
        ("dynamic_script_data", "deathrattle_annotation", "hero_power_state",
         "hero_power_target_unresolved"))]
    if dynamic:
        return {"attribution": "unmodeled_dynamic_state",
                "suspect_cards": [], "context": dynamic}
    if "dynamic_stat_script" in gaps:
        return {"attribution": "unmodeled_context", "suspect_cards": [],
                "context": ["dynamic_stat_script"]}
    # 2026-10-18 root-cause 裁定（reversed/rea/behavior_mismatch_5_rootcause.md）：
    # `hand_not_modeled`（手牌未建模）与 `*_hero_power_unknown`（技能未知）
    # 属于**未建模上下文**，不得计为 behavior_mismatch——登记新卡后暴露的
    # 分歧仅是 context 判定残留，不是引擎/脚本 bug。
    informative = {"unsupported_keyword"}
    others = [g for g in gaps if g not in informative]
    if others:
        return {"attribution": "unmodeled_context",
                "suspect_cards": [], "context": others}
    return {"attribution": "behavior_mismatch", "suspect_cards": []}


def _trace_context(trace: T.OfficialCombatTrace) -> Dict[str, Any]:
    return {
        "trace_id": trace.trace_id,
        "source": trace.source,
        "episode_id": trace.episode_id,
        "combat_index": trace.combat_index,
        "turn": trace.turn,
        "heroes": dict(trace.heroes) if trace.heroes else None,
        "player": {
            "hero_power_id": trace.player.hero_power_id,
            "minions": [{"name": m.name, "card_id": m.card_id,
                        "atk": m.atk, "health": m.health,
                        "golden": m.golden, "keywords": list(m.keywords)}
                       for m in trace.player.minions],
            "hand": [m.name for m in trace.player.hand],
        },
        "opponent": {
            "hero_power_id": trace.opponent.hero_power_id,
            "minions": [{"name": m.name, "card_id": m.card_id,
                        "atk": m.atk, "health": m.health,
                        "golden": m.golden, "keywords": list(m.keywords)}
                       for m in trace.opponent.minions],
            "hand": [m.name for m in trace.opponent.hand],
        },
        "official_result": trace.official_result,
        "game_seed": trace.game_seed,
        # 官方先手分析字段：事件级 RNG 对齐用 events[0]（不是 strict 等价）
        "first_event": _event_dict(trace.events[0]) if trace.events else None,
        "bb_rates": trace.bb_rates,
    }


def diff_traces(traces: Sequence[T.OfficialCombatTrace],
                *,
                db: Optional[CardDB] = None,
                seeds: int = 64,
                seed_base: int = 0,
                limit: Optional[int] = None,
                hero_powers: str = "on_bind",
                l1_threshold: float = 0.15,
                tolerant_rate: float = 0.8,
                inject_script_data: bool = True,
                capture_events: bool = True,
                traces_dir: str = "") -> Dict[str, Any]:
    """批量差分，返回完整报告 dict。"""
    started = time.time()
    db = db or CardDB.load(ENGINE_DATA_DIR)
    resolver = CardResolver(db)
    hero_index = HeroIndex(db)
    selected = list(traces)
    if limit is not None:
        selected = selected[: int(limit)]
    records: List[Dict[str, Any]] = []
    sanity_skips: Counter = Counter()
    for trace in selected:
        sanity = sanity_check_trace(trace)
        if sanity is not None:
            sanity_skips[sanity] += 1
            records.append({
                "trace": _trace_context(trace),
                "simulation": {"seeds": [], "outcomes": [], "rates": {},
                               "context_gaps": [], "errors": []},
                "comparison": {
                    "status": STATUS_SKIPPED,
                    "subclass": f"trace_{sanity}",
                    "confidence": "high",
                    "evidence": {"reason": sanity},
                    "context_gaps": [],
                    "official_in_support": None,
                    "l1_distance": None,
                },
                "attribution": {"attribution": "skipped",
                                "suspect_cards": []},
            })
            continue
        sim = simulate_trace(
            trace, db, resolver, hero_index,
            seeds=seeds, seed_base=seed_base,
            hero_powers=hero_powers,
            inject_script_data=inject_script_data,
            capture_events=capture_events and bool(trace.events),
        )
        comparison = compare_combat(
            sim.outcomes,
            official_result=trace.official_result,
            bb_rates=trace.bb_rates,
            data_gaps=sim.data_gaps,
            context_gaps=sim.context_gaps,
            l1_threshold=l1_threshold,
        )
        attribution = attribute_divergence(comparison, sim.context_gaps)
        # 未建模的官方上下文（秘密/外部亡语/技能状态/动态脚本）即使结果与
        # 官方不一致，也不能算引擎行为错误 → 升级为独立的 CONTEXT_GAP 分类。
        if (comparison["status"] == STATUS_ENGINE_DIVERGENCE
                and attribution["attribution"] in ("unmodeled_context",
                                                    "unmodeled_dynamic_state")):
            comparison["status"] = STATUS_CONTEXT_GAP
            comparison["subclass"] = f"context:{attribution['attribution']}"
        record: Dict[str, Any] = {
            "trace": _trace_context(trace),
            "simulation": {
                "seeds": sim.seeds,
                "outcomes": sim.outcomes,
                "rates": sim.rates(),
                "rounds_mean": round(
                    sum(sim.rounds) / len(sim.rounds), 3) if sim.rounds else None,
                "damage_dealt_mean": round(
                    sum(sim.damage_dealt) / len(sim.damage_dealt), 2)
                if sim.damage_dealt else None,
                "engine_card_ids": sim.engine_card_ids,
                "hero_info": sim.hero_info,
                "context_gaps": sim.context_gaps,
                "errors": sim.errors[:5],
                "script_data_injected": sim.script_data_injected,
            },
            "comparison": comparison,
            "attribution": attribution,
        }
        if trace.official_damage and sim.damage_dealt:
            record["simulation"]["official_damage"] = trace.official_damage
        if comparison["status"] != STATUS_DATA_GAP and trace.events and sim.event_streams:
            best = None
            for index, stream in enumerate(sim.event_streams):
                diff = compare_events(trace.events, stream)
                if not diff["diverged"]:
                    best = {**diff, "seed_index": index}
                    break
                # 选**最长公共事件前缀**的种子（RNG 顺序不同时也给出最接近对齐）
                if best is None or (best.get("diverged")
                                    and diff.get("index", 0) < best.get("index", 0)):
                    best = {**diff, "seed_index": index}
            record["event_diff"] = best
            rng_order_caused = False
            rng_classes = ("attack_order_side", "attack_order_slot",
                           "attack_side_swap")
            if best and best["diverged"] and comparison["status"] == STATUS_MATCH:
                if best.get("classification") in rng_classes:
                    # 结果/状态已一致，仅攻击先手/顺序不同（官方 RNG vs
                    # 引擎 random.Random）→ 保持 MATCH，单列 RNG_ORDER。
                    best["rng_order"] = True
                    comparison["subclass"] = "rng_order_event"
                    comparison.setdefault("evidence", {})[
                        "event_divergence"] = best
                    record["attribution"] = {
                        "attribution": "rng_order",
                        "suspect_cards": [],
                        "context": [],
                    }
                else:
                    comparison["status"] = STATUS_ENGINE_DIVERGENCE
                    comparison["subclass"] = "event_sequence"
                    comparison["evidence"]["event_divergence"] = best
                    rng_order_caused = True
            # 已判 ENGINE_DIVERGENCE 且由事件顺序导致 → 标 RNG_ORDER
            if (rng_order_caused and best and best.get("diverged")
                    and best.get("classification") in rng_classes):
                comparison["subclass"] = "rng_order"
                comparison["evidence"]["rng_order"] = True
                best["rng_order"] = True
                record["attribution"] = {
                    "attribution": "rng_order",
                    "suspect_cards": [],
                    "context": [],
                }
        attempt = getattr(sim, "game_seed_attempt", None)
        if attempt:
            attempt_diff = (compare_events(trace.events, attempt["events"])
                            if attempt.get("events") else None)
            record["game_seed_attempt"] = {
                "game_seed": attempt.get("game_seed"),
                "seed": attempt.get("seed"),
                "outcome": attempt.get("outcome"),
                "event_diff": attempt_diff,
            }
        records.append(record)

    summary = _summarize(records, tolerant_rate=tolerant_rate)
    report = {
        "schema": "diff_report.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "engine_root": str(ENGINE_ROOT),
        "engine_data": str(ENGINE_DATA_DIR),
        "engine_card_defs": len(db),
        "official_reference": (str(OFFICIAL_DATA_255130)
                               if OFFICIAL_DATA_255130.exists() else None),
        "traces_dir": traces_dir or str(DEFAULT_TRACES_DIR),
        "settings": {
            "seeds_per_trace": seeds,
            "seed_base": seed_base,
            "hero_powers": hero_powers,
            "l1_threshold": l1_threshold,
            "tolerant_rate": tolerant_rate,
            "inject_script_data": inject_script_data,
            "limit": limit,
        },
        "sanity_skips": dict(sanity_skips),
        "summary": summary,
        "records": records,
        "divergences": _top_divergences(records),
        "data_gaps": _data_gap_summary(records),
        "suspect_cards": _suspect_cards(records),
        "elapsed_seconds": round(time.time() - started, 2),
    }
    return report


def _strict_records(records: Sequence[Mapping[str, Any]],
                    statuses: tuple) -> List[Mapping[str, Any]]:
    return [r for r in records if r["comparison"]["status"] in statuses]


def _expected_direction(record: Mapping[str, Any]) -> Optional[str]:
    """BobsBuddy 期望方向（最大概率结果）。"""
    bb = record["trace"].get("bb_rates") or {}
    if not bb:
        return None
    order = (T.RESULT_WIN, T.RESULT_TIE, T.RESULT_LOSS)
    best = max(order, key=lambda key: float(bb.get(key, 0.0)))
    return best if float(bb.get(best, 0.0)) > 0 else None


def _deterministic_metrics(records: Sequence[Mapping[str, Any]],
                           *, tolerant_rate: float) -> Dict[str, Any]:
    """确定性战斗（BobsBuddy 100% 结论）的 strict / tolerant 两套指标。

    * **strict**：引擎分布必须 100% 等于期望方向（沿用旧口径；
      ``compare_combat`` 已判定的状态）。
    * **tolerant（同分布阈值）**：允许 RNG 流移位——只要引擎在该方向上的
      比例 ≥ ``tolerant_rate``（默认 0.8），或官方单样本 == 引擎众数，
      即视为「方向一致」，不算引擎行为错误。
    """
    deterministic = [
        r for r in records
        if r["trace"].get("bb_rates")
        and max(float(r["trace"]["bb_rates"].get(key, 0.0))
                for key in (T.RESULT_WIN, T.RESULT_TIE, T.RESULT_LOSS)) >= 0.999
        and r["comparison"]["status"] in (STATUS_MATCH, STATUS_ENGINE_DIVERGENCE)
    ]
    strict_match = 0
    tolerant_match = 0
    tolerated_rng: List[Dict[str, Any]] = []
    for record in deterministic:
        if record["comparison"]["status"] == STATUS_MATCH:
            strict_match += 1
            tolerant_match += 1
            continue
        expected = _expected_direction(record)
        engine_rates = (record["comparison"].get("evidence", {})
                        .get("engine_rates") or {})
        engine_mode = (record["comparison"].get("evidence", {})
                       .get("engine_mode"))
        official = record["trace"].get("official_result")
        engine_rate_expected = float(engine_rates.get(expected, 0.0)) \
            if expected else 0.0
        if (engine_rate_expected >= tolerant_rate
                or (official is not None and official == engine_mode)):
            tolerant_match += 1
            tolerated_rng.append({
                "trace_id": record["trace"]["trace_id"],
                "expected_outcome": expected,
                "engine_rate_of_expected": round(engine_rate_expected, 4),
                "official": official,
                "subclass": record["comparison"].get("subclass"),
            })
    total = len(deterministic)
    return {
        "traces": total,
        "strict_match": strict_match,
        "strict_match_rate": round(strict_match / total, 4) if total else None,
        "tolerant_match": tolerant_match,
        "tolerant_match_rate": round(tolerant_match / total, 4)
        if total else None,
        "tolerated_rng_stream": tolerated_rng,
    }


def _summarize(records: Sequence[Mapping[str, Any]],
               *, tolerant_rate: float = 0.8) -> Dict[str, Any]:
    statuses = Counter(r["comparison"]["status"] for r in records)
    subclasses = Counter(r["comparison"]["subclass"] for r in records
                         if r["comparison"]["status"] == STATUS_ENGINE_DIVERGENCE)
    attributions = Counter(r.get("attribution", {}).get("attribution", "?")
                           for r in records
                           if r["comparison"]["status"] == STATUS_ENGINE_DIVERGENCE)
    with_result = sum(1 for r in records
                      if r["trace"].get("official_result") is not None)
    divergence = statuses.get(STATUS_ENGINE_DIVERGENCE, 0)
    data_gap = statuses.get(STATUS_DATA_GAP, 0)
    match = statuses.get(STATUS_MATCH, 0)
    skipped = statuses.get(STATUS_SKIPPED, 0)
    context_gap = statuses.get(STATUS_CONTEXT_GAP, 0)
    considered = max(1, len(records) - data_gap - skipped - context_gap)
    behavior_mismatch = sum(
        1 for r in records
        if r["comparison"]["status"] == STATUS_ENGINE_DIVERGENCE
        and r.get("attribution", {}).get("attribution") == "behavior_mismatch")
    # RNG_ORDER：首分歧为攻击先手/顺序/攻防互换（官方 RNG 与引擎不同），
    # 单列统计，不计 behavior_mismatch；其中结果已一致（MATCH）的样本
    # 只差 RNG 事件顺序 → rng_order_match。
    rng_order = sum(1 for r in records
                    if (r.get("event_diff") or {}).get("rng_order"))
    rng_order_match = sum(
        1 for r in records
        if r["comparison"]["status"] == STATUS_MATCH
        and (r.get("event_diff") or {}).get("rng_order"))
    # 事件级 strict = 结果一致且事件序列**完全一致**（无 RNG 顺序差异）
    event_strict_match = sum(
        1 for r in records
        if r["comparison"]["status"] == STATUS_MATCH
        and not (r.get("event_diff") or {}).get("diverged"))
    game_seed_attempts = [r["game_seed_attempt"] for r in records
                          if r.get("game_seed_attempt")]
    game_seed_attempt_match = sum(
        1 for item in game_seed_attempts
        if item.get("event_diff") is not None
        and not item["event_diff"].get("diverged"))

    # ── 干净子集 / context-aware ─────────────────────────────────────
    # 「干净子集」= 无已知阻断缺口（缺脚本/动态状态/秘密/技能状态/外部亡语）
    # 的轨迹：这一子集上的匹配率才最能代表引擎机制保真度。
    clean = [r for r in records
             if r["comparison"]["status"] in (STATUS_MATCH,
                                              STATUS_ENGINE_DIVERGENCE)
             and not _has_blocking_gap(r)]
    clean_match = sum(1 for r in clean
                      if r["comparison"]["status"] == STATUS_MATCH)
    clean_div = len(clean) - clean_match
    clean_det = _deterministic_metrics(clean, tolerant_rate=tolerant_rate)

    # ── strict（旧口径，含缺口轨迹；同时给 strict/tolerant 确定性） ──
    strict_det = _deterministic_metrics(records, tolerant_rate=tolerant_rate)
    official = [r for r in records
                if r["trace"].get("official_result") is not None
                and r["comparison"]["status"] in (STATUS_MATCH,
                                                  STATUS_ENGINE_DIVERGENCE)]
    official_agree = sum(
        1 for r in official
        if r["comparison"].get("evidence", {}).get("engine_mode")
        == r["trace"].get("official_result"))
    context_attributions = Counter(
        r.get("attribution", {}).get("attribution", "?")
        for r in records
        if r["comparison"]["status"] == STATUS_CONTEXT_GAP)

    # ── 动态 ScriptDataNum 注入统计（测量口径：注入后有多少轨迹被修正） ──
    injected_traces = []
    injected_minions = 0
    adapted_minions = 0
    for record in records:
        injected = record["simulation"].get("script_data_injected") or []
        if not injected:
            continue
        injected_minions += len(injected)
        adapted_minions += sum(1 for item in injected if item.get("adapted"))
        injected_traces.append({
            "trace_id": record["trace"]["trace_id"],
            "status": record["comparison"]["status"],
            "official": record["trace"].get("official_result"),
            "minions": injected,
        })

    strict = {
        "traces": len(records),
        "match": match,
        "engine_divergence": divergence,
        "context_gap": context_gap,
        "data_gap": data_gap,
        "skipped": skipped,
        "behavior_mismatch": behavior_mismatch,
        "match_rate": round(match / considered, 4),
        "divergence_rate": round(divergence / considered, 4),
        "deterministic": strict_det,
    }
    context_aware = {
        "clean_subset_traces": len(clean),
        "clean_match": clean_match,
        "clean_engine_divergence": clean_div,
        "clean_match_rate": round(clean_match / len(clean), 4)
        if clean else None,
        "excluded_traces": len(records) - len(clean) - data_gap - skipped,
        "behavior_mismatch": behavior_mismatch,
        "deterministic": clean_det,
    }
    return {
        # ── 兼容旧字段（= strict 口径）──
        "traces": len(records),
        "traces_with_official_result": with_result,
        "match": match,
        "data_gap": data_gap,
        "engine_divergence": divergence,
        "context_gap": context_gap,
        "context_gap_attribution": dict(context_attributions),
        "skipped": skipped,
        "match_rate": round(match / considered, 4),
        "data_gap_rate": round(data_gap / max(1, len(records)), 4),
        "divergence_rate": round(divergence / considered, 4),
        "divergence_subclasses": dict(subclasses),
        "divergence_attribution": dict(attributions),
        "behavior_mismatch": behavior_mismatch,
        # ── RNG 类事件分歧（单列；不计 behavior_mismatch）──
        "rng_order": rng_order,
        "rng_order_match": rng_order_match,
        "event_strict_match": event_strict_match,
        "rng_order_rate": round(rng_order / max(1, len(records)), 4),
        # ── 官方 GAME_SEED 诊断（用 seed 额外跑一局，不进 64 seeds 统计）──
        "game_seed_traces": sum(1 for r in records
                                if r["trace"].get("game_seed") is not None),
        "game_seed_attempts": len(game_seed_attempts),
        "game_seed_attempt_event_match": game_seed_attempt_match,
        "game_seed_attempt_agreement_rate": round(
            game_seed_attempt_match / len(game_seed_attempts), 4)
        if game_seed_attempts else None,
        "clean_subset_traces": len(clean),
        "clean_subset_match": clean_match,
        "clean_subset_match_rate": round(clean_match / len(clean), 4)
        if clean else None,
        "deterministic_traces": strict_det["traces"],
        "deterministic_match": strict_det["strict_match"],
        "deterministic_match_rate": strict_det["strict_match_rate"],
        "deterministic_tolerant_match": strict_det["tolerant_match"],
        "deterministic_tolerant_match_rate": strict_det["tolerant_match_rate"],
        "official_result_agrees_with_engine_mode": official_agree,
        "official_result_comparable": len(official),
        "official_result_agreement_rate": round(
            official_agree / len(official), 4) if official else None,
        "context_gap_traces": sum(1 for r in records
                                  if r["simulation"].get("context_gaps")),
        # ── 新口径：strict vs context-aware 两套指标 ──
        "tolerant_rate": tolerant_rate,
        "strict": strict,
        "context_aware": context_aware,
        # ── 动态 ScriptDataNum 注入统计 ──
        "script_data_injected_traces": len(injected_traces),
        "script_data_injected_minions": injected_minions,
        "script_data_adapted_minions": adapted_minions,
        "script_data_injected": injected_traces[:30],
    }


def _has_blocking_gap(record: Mapping[str, Any]) -> bool:
    """轨迹是否带「已知会改变战斗结果」的未建模缺口。

    * ``second_hero_power_ignored`` 是**未建模上下文**（第二英雄技能可能
      改变战斗），计入 blocking → 这类轨迹不算「干净子集」，也不产生
      ``behavior_mismatch``（2026-10-18 测量口径修正）。
    * ``hand_not_modeled`` 保留为提示性（BG 战斗中手牌极少影响结算），
      否则干净子集会缩到不可测量。
    """
    for gap in record["simulation"].get("context_gaps") or []:
        if gap.startswith(("no_script:", "dynamic_script_data",
                           "deathrattle_annotation", "unknown_keyword",
                           "detected_effect:", "hero_power_state:",
                           "hero_power_target_unresolved:")):
            return True
        if gap in ("unsupported_keyword", "dynamic_stat_script",
                   "second_hero_power_ignored"):
            return True
    return False


def _divergence_rank(record: Mapping[str, Any]) -> tuple:
    comparison = record["comparison"]
    attribution = record.get("attribution", {}).get("attribution") or "?"
    subclass = comparison.get("subclass") or ""
    l1 = comparison.get("l1_distance") or 0.0
    conf = 0 if comparison.get("confidence") == "high" else 1
    return (ATTRIBUTION_PRIORITY.get(attribution, 8),
            SEVERITY_ORDER.get(subclass, 5), conf, -float(l1 or 0.0))


def _top_divergences(records: Sequence[Mapping[str, Any]],
                     limit: int = 30) -> List[Dict[str, Any]]:
    rows = [r for r in records
            if r["comparison"]["status"] == STATUS_ENGINE_DIVERGENCE]
    rows.sort(key=_divergence_rank)
    out = []
    for record in rows[:limit]:
        comparison = record["comparison"]
        out.append({
            "trace_id": record["trace"]["trace_id"],
            "turn": record["trace"]["turn"],
            "source": record["trace"]["source"],
            "attribution": record.get("attribution", {}).get("attribution"),
            "suspect_cards": record.get("attribution", {}).get("suspect_cards"),
            "subclass": comparison.get("subclass"),
            "confidence": comparison.get("confidence"),
            "l1_distance": comparison.get("l1_distance"),
            "official_result": record["trace"].get("official_result"),
            "bb_rates": record["trace"].get("bb_rates"),
            "engine_rates": comparison.get("evidence", {}).get("engine_rates"),
            "player_minions": [
                f"{m['name']} {m['atk']}/{m['health']}"
                for m in record["trace"]["player"]["minions"]],
            "opponent_minions": [
                f"{m['name']} {m['atk']}/{m['health']}"
                for m in record["trace"]["opponent"]["minions"]],
            "player_hero_power": record["trace"]["player"]["hero_power_id"],
            "opponent_hero_power": record["trace"]["opponent"]["hero_power_id"],
            "context_gaps": record["simulation"]["context_gaps"],
            "event_divergence": record.get("event_diff"),
        })
    return out


def _data_gap_summary(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    names: Counter = Counter()
    kinds: Counter = Counter()
    rows = []
    for record in records:
        if record["comparison"]["status"] != STATUS_DATA_GAP:
            continue
        gaps = record["comparison"]["evidence"].get("data_gaps") or []
        for gap in gaps:
            names[gap.get("name") or "?"] += 1
            kinds[gap.get("gap") or "?"] += 1
        rows.append({
            "trace_id": record["trace"]["trace_id"],
            "turn": record["trace"]["turn"],
            "gaps": gaps,
            "official_result": record["trace"].get("official_result"),
        })
    return {
        "traces": len(rows),
        "by_kind": dict(kinds),
        "by_name_top": dict(names.most_common(30)),
        "records": rows[:30],
    }


def _suspect_cards(records: Sequence[Mapping[str, Any]],
                   limit: int = 15) -> List[Dict[str, Any]]:
    """分歧轨迹里的卡频次；``no_engine_script`` 是「机制未实现」强证据。"""
    counter: Counter = Counter()
    no_script: Counter = Counter()
    behavior: Counter = Counter()
    for record in records:
        if record["comparison"]["status"] != STATUS_ENGINE_DIVERGENCE:
            continue
        attribution = record.get("attribution", {}).get("attribution")
        no_script_ids = {g.split(":", 1)[1]
                         for g in record["simulation"].get("context_gaps") or []
                         if g.startswith("no_script:")}
        seen = set()
        for side in ("player", "opponent"):
            for minion in record["trace"][side]["minions"]:
                card_id = record["simulation"]["engine_card_ids"].get(
                    minion.get("name") or "")
                key = card_id or minion.get("name") or "?"
                if key in seen:
                    continue
                seen.add(key)
                counter[key] += 1
                if card_id and card_id in no_script_ids:
                    no_script[key] += 1
                if attribution == "behavior_mismatch":
                    behavior[key] += 1
    rows = []
    for key, count in counter.most_common(limit * 3):
        rows.append({"card": key, "divergent_traces": count,
                     "no_engine_script": no_script.get(key, 0),
                     "behavior_mismatch_traces": behavior.get(key, 0)})
    rows.sort(key=lambda r: (-r["behavior_mismatch_traces"],
                             -r["no_engine_script"],
                             -r["divergent_traces"]))
    return rows[:limit]


# ══════════════════════════════════════════════════════════════════════
# Markdown 报告
# ══════════════════════════════════════════════════════════════════════


def render_markdown(report: Mapping[str, Any], *, top: int = 10) -> str:
    summary = report["summary"]
    lines: List[str] = []
    lines.append("# 差分验证报告：官方 BG 战斗 vs hsrl2 引擎")
    lines.append("")
    lines.append(f"> 自动生成（{report['generated_at']}）；"
                 f"引擎数据 `{report['engine_data']}`（{report['engine_card_defs']} 张）；"
                 f"每场 {report['settings']['seeds_per_trace']} 个种子。")
    lines.append("")
    lines.append("## 1. 总览")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|------|----|")
    lines.append(f"| 轨迹总数 | {summary['traces']} |")
    lines.append(f"| 有官方实际结果 | {summary['traces_with_official_result']} |")
    lines.append(f"| MATCH | {summary['match']} |")
    lines.append(f"| ENGINE_DIVERGENCE | {summary['engine_divergence']} |")
    lines.append(f"| DATA_GAP（不计引擎 bug） | {summary['data_gap']} |")
    lines.append(f"| CONTEXT_GAP（官方上下文未建模，不计引擎 bug） | "
                 f"{summary.get('context_gap', 0)} |")
    lines.append(f"| SKIPPED（日志不可比样本） | {summary['skipped']} |")
    lines.append(f"| 匹配率（排除 DATA_GAP/CONTEXT_GAP/SKIPPED） | "
                 f"{summary['match_rate']:.1%} |")
    lines.append(f"| 分歧率（排除 DATA_GAP/CONTEXT_GAP/SKIPPED） | "
                 f"{summary['divergence_rate']:.1%} |")
    lines.append(f"| 数据缺口率 | {summary['data_gap_rate']:.1%} |")
    if summary.get("rng_order"):
        lines.append(f"| **RNG_ORDER**（攻击顺序类，不计行为不一致） | "
                     f"{summary['rng_order']} |")
    if summary.get("clean_subset_traces"):
        lines.append(f"| **干净子集**（无已知缺口）匹配率 | "
                     f"{summary['clean_subset_match_rate']:.1%} "
                     f"（{summary['clean_subset_match']}/"
                     f"{summary['clean_subset_traces']}） |")
    if summary.get("deterministic_match_rate") is not None:
        lines.append(f"| **确定性战斗**匹配率（BobsBuddy 100% 裁判） | "
                     f"{summary['deterministic_match_rate']:.1%} "
                     f"（{summary['deterministic_match']}/"
                     f"{summary['deterministic_traces']}） |")
    if summary.get("official_result_agreement_rate") is not None:
        lines.append(f"| 官方实际结果 == 引擎众数 | "
                     f"{summary['official_result_agreement_rate']:.1%} "
                     f"({summary['official_result_agrees_with_engine_mode']}/"
                     f"{summary['official_result_comparable']}) |")
    if summary.get("divergence_subclasses"):
        lines.append("")
        lines.append("分歧子类：" + "，".join(
            f"`{k}` {v}" for k, v in summary["divergence_subclasses"].items()))
    if summary.get("divergence_attribution"):
        lines.append("")
        lines.append("分歧归因：" + "，".join(
            f"`{k}` {v}" for k, v in summary["divergence_attribution"].items()))
    if summary.get("context_gap_attribution"):
        lines.append("")
        lines.append("上下文缺口归因（已从引擎分歧中剔除）：" + "，".join(
            f"`{k}` {v}"
            for k, v in summary["context_gap_attribution"].items()))
    if report.get("sanity_skips"):
        lines.append("")
        lines.append("不可比样本（日志缺陷，已剔除）：" + "，".join(
            f"`{k}` {v}" for k, v in report["sanity_skips"].items()))
    if summary.get("rng_order"):
        lines.append("")
        lines.append(f"**RNG_ORDER**（首事件分歧=攻击先手/顺序，官方 RNG vs "
                     f"引擎 `random.Random` 不同，不计行为不一致）："
                     f"**{summary['rng_order']}** 条"
                     f"（{summary.get('rng_order_rate', 0):.1%}）；"
                     f"其中结果/状态已一致（仅事件顺序不同）"
                     f"**{summary.get('rng_order_match', 0)}** 条按 MATCH 计。")
        lines.append("")
        lines.append(f"**事件级口径**：strict 事件对齐（结果一致且事件序列"
                     f"完全一致）= **{summary.get('event_strict_match', 0)}**；"
                     f"RNG 对齐（结果一致、允许攻击先手/顺序不同）= "
                     f"**{summary.get('match', 0)}**。")
    if summary.get("game_seed_traces"):
        lines.append("")
        lines.append(f"**GAME_SEED 分析字段**：{summary['game_seed_traces']} 条"
                     f"轨迹含官方 seed；用官方 seed 额外跑一局诊断"
                     f"（不进 {report['settings']['seeds_per_trace']} seeds 统计）："
                     f"{summary.get('game_seed_attempts', 0)} 次尝试，"
                     f"事件流完全对齐 "
                     f"{summary.get('game_seed_attempt_event_match', 0)} 次"
                     f"（官方 RNG 算法/整局消耗不同，预期为 0，"
                     f"仅作分析字段，不强行要求 attack order 一致）。")

    # ── 口径说明：strict vs context-aware（2026-10-18 测量口径修正）──
    strict = summary.get("strict") or {}
    ctx = summary.get("context_aware") or {}
    lines.append("")
    lines.append("## 1b. 测量口径：strict vs context-aware")
    lines.append("")
    lines.append("> 同一次运行同时输出两套口径。**上下文感知指标为推荐口径**；"
                 "strict 保留作对照（可能把 RNG 流移位/缺失上下文误计为引擎错误）。")
    lines.append("")
    lines.append("| 指标 | strict（全部可比轨迹） | context-aware（干净子集） |")
    lines.append("|------|------------------------|---------------------------|")
    lines.append(f"| 可比轨迹 | {strict.get('traces', 0)} | "
                 f"{ctx.get('clean_subset_traces', 0)} |")
    lines.append(f"| 排除（缺口/日志不可比） | "
                 f"{summary.get('skipped', 0) + summary.get('data_gap', 0) + ctx.get('excluded_traces', 0)} | "
                 f"{ctx.get('excluded_traces', 0)}（阻断缺口） |")
    lines.append(f"| MATCH | {strict.get('match', 0)} | "
                 f"{ctx.get('clean_match', 0)} |")
    lines.append(f"| ENGINE_DIVERGENCE | {strict.get('engine_divergence', 0)} | "
                 f"{ctx.get('clean_engine_divergence', 0)} |")
    lines.append(f"| 匹配率 | {(strict.get('match_rate') or 0):.1%} | "
                 f"{(ctx.get('clean_match_rate') or 0):.1%} |")
    lines.append(f"| **behavior_mismatch（必须 0）** | "
                 f"{summary.get('behavior_mismatch', 0)} | "
                 f"{ctx.get('behavior_mismatch', 0)} |")
    _sd = strict.get("deterministic") or {}
    _cd = ctx.get("deterministic") or {}
    lines.append(f"| 确定性战斗 strict 匹配率 | "
                 f"{( _sd.get('strict_match_rate') or 0):.1%} "
                 f"({_sd.get('strict_match', 0)}/{_sd.get('traces', 0)}) | "
                 f"{(_cd.get('strict_match_rate') or 0):.1%} "
                 f"({_cd.get('strict_match', 0)}/{_cd.get('traces', 0)}) |")
    lines.append(f"| 确定性战斗 **tolerant** 匹配率"
                 f"（同分布阈值 {summary.get('tolerant_rate', 0.8):.0%}） | "
                 f"{(_sd.get('tolerant_match_rate') or 0):.1%} | "
                 f"{(_cd.get('tolerant_match_rate') or 0):.1%} |")
    lines.append("")
    tolerated = (_sd.get("tolerated_rng_stream") or [])
    if tolerated:
        lines.append(f"确定性 RNG 流耐受（strict→tolerant 恢复 "
                     f"{len(tolerated)} 条，前 5 条）：")
        lines.append("")
        lines.append("| trace | 期望结果 | 引擎该方向比例 | 官方 | 子类 |")
        lines.append("|-------|----------|----------------|------|------|")
        for row in tolerated[:5]:
            lines.append(f"| `{row['trace_id']}` | `{row.get('expected_outcome')}` | "
                         f"{(row.get('engine_rate_of_expected') or 0):.1%} | "
                         f"`{row.get('official')}` | `{row.get('subclass')}` |")
        lines.append("")
    if summary.get("script_data_injected_traces"):
        lines.append(f"动态 ScriptDataNum 注入："
                     f"**{summary['script_data_injected_traces']} 条轨迹 / "
                     f"{summary['script_data_injected_minions']} 个实体**"
                     f"（其中 {summary.get('script_data_adapted_minions', 0)} 个"
                     f"走动态属性复算适配器；有值才注入、无值不改默认行为）。")
        lines.append("")
    lines.append("## 2. 分歧 TOP")
    lines.append("")
    divergences = report.get("divergences") or []
    if not divergences:
        lines.append("（无）")
    for index, row in enumerate(divergences[:top], start=1):
        lines.append(f"### D{index}. `{row['subclass']}` "
                     f"（归因 `{row.get('attribution')}`，"
                     f"{row['confidence']} 置信，turn {row['turn']}）")
        lines.append("")
        lines.append(f"- 轨迹：`{row['trace_id']}`（{row['source']}）")
        if row.get("suspect_cards"):
            lines.append(f"- 引擎缺脚本的卡："
                         f"{', '.join(f'`{c}`' for c in row['suspect_cards'])}")
        lines.append(f"- 官方实际结果：`{row['official_result']}`；"
                     f"BobsBuddy 第二实现概率：`{row['bb_rates']}`")
        lines.append(f"- 引擎 {report['settings']['seeds_per_trace']} 种子分布："
                     f"`{row['engine_rates']}`")
        if row.get("l1_distance") is not None:
            lines.append(f"- 分布 L1 距离：{row['l1_distance']:.3f}")
        lines.append(f"- 我方战团：{', '.join(row['player_minions']) or '（空）'}"
                     f"（技能 `{row['player_hero_power']}`）")
        lines.append(f"- 敌方战团：{', '.join(row['opponent_minions']) or '（空）'}"
                     f"（技能 `{row['opponent_hero_power']}`）")
        if row.get("context_gaps"):
            lines.append(f"- 上下文缺口：{', '.join(row['context_gaps'])}")
        event_diff = row.get("event_divergence")
        if event_diff and event_diff.get("diverged"):
            lines.append(f"- 首个事件分歧：官方 `{event_diff.get('official')}` "
                         f"vs 引擎 `{event_diff.get('engine')}`")
        lines.append("")
    lines.append("## 3. 数据缺口（引擎 data/ 版本问题，不是机制 bug）")
    lines.append("")
    gaps = report.get("data_gaps") or {}
    if not gaps.get("traces"):
        lines.append("（无）")
    else:
        lines.append(f"受影响轨迹：{gaps['traces']}；按原因：" +
                     "，".join(f"`{k}` {v}" for k, v in gaps["by_kind"].items()))
        lines.append("")
        lines.append("| 卡名 | 出现次数 |")
        lines.append("|------|----------|")
        for name, count in list(gaps["by_name_top"].items())[:15]:
            lines.append(f"| {name} | {count} |")
    lines.append("")
    lines.append("## 4. 分歧可疑卡（按出现频次）")
    lines.append("")
    suspects = report.get("suspect_cards") or []
    if not suspects:
        lines.append("（无）")
    else:
        lines.append("| 卡 | 分歧轨迹数 | 归因 behavior_mismatch | 引擎无脚本 |")
        lines.append("|----|------------|------------------------|------------|")
        for row in suspects[:15]:
            lines.append(f"| {row['card']} | {row['divergent_traces']} | "
                         f"{row.get('behavior_mismatch_traces', 0)} | "
                         f"{'是' if row['no_engine_script'] else ''} |")
    lines.append("")
    lines.append("## 5. 口径与局限")
    lines.append("")
    lines.append("- **官方实际结果**来自 HDT BobsBuddy 日志的 "
                 "`ValidateSimulationResultAsync >> result=`（官方战斗结算结果）。")
    lines.append("- **BobsBuddy 概率**是社区第二实现（10k 次模拟），不是官方；"
                 "`distribution_distance` 证据是「引擎 vs BobsBuddy」，"
                 "确定性战斗（100%）才可视为硬约束。")
    lines.append("- 本机**没有真实 BG Power.log**（全部 1,365 个 HDT 录像都是 2 人"
                 "构筑局），因此事件级 `compare_events` 只做了实现与单测，"
                 "真实数据上尚无输入；见 docs/DIFF_HARNESS.md。")
    lines.append("- 未建模上下文（手牌、第二英雄技能、动态 ScriptDataNum、"
                 "饰品/任务/异变）会降低分歧置信度（`confidence=medium`）。")
    lines.append("- 回归命令见 docs/DIFF_HARNESS.md §6。")
    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="官方 BG 战斗轨迹 vs hsrl2 引擎差分")
    parser.add_argument("--traces", default=str(DEFAULT_TRACES_DIR),
                        help="轨迹目录（official_combat_trace.v1 JSON）")
    parser.add_argument("--limit", type=int, default=None,
                        help="最多处理多少条轨迹")
    parser.add_argument("--seeds", type=int, default=64,
                        help="每条轨迹的引擎种子数（默认 64）")
    parser.add_argument("--seed-base", type=int, default=0)
    parser.add_argument("--hero-powers", choices=("none", "on_bind"),
                        default="on_bind",
                        help="是否接线英雄技能 on_bind（默认 on_bind）")
    parser.add_argument("--l1-threshold", type=float, default=0.15)
    parser.add_argument(
        "--no-script-data-injection", dest="inject_script_data",
        action="store_false",
        help="关闭官方 ScriptDataNum 注入（用于 A/B 对比注入恢复量；默认开启）")
    parser.set_defaults(inject_script_data=True)
    parser.add_argument(
        "--tolerant-rate", type=float, default=0.8,
        help="确定性战斗的「同分布阈值」：引擎在 BB 期望方向上的比例 ≥ 该值 "
             "即视为方向一致（默认 0.8；strict 指标仍保留）")
    parser.add_argument("--engine-data", default=str(ENGINE_DATA_DIR))
    parser.add_argument("--json", default=str(DEFAULT_JSON))
    parser.add_argument("--md", default=str(DEFAULT_MD))
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    traces = T.load_traces(args.traces, limit=args.limit)
    if not traces:
        print(f"[diff] 轨迹目录为空: {args.traces}", file=sys.stderr)
        return 2
    db = CardDB.load(args.engine_data)
    report = diff_traces(
        traces, db=db, seeds=args.seeds, seed_base=args.seed_base,
        limit=args.limit, hero_powers=args.hero_powers,
        l1_threshold=args.l1_threshold, tolerant_rate=args.tolerant_rate,
        inject_script_data=args.inject_script_data,
        traces_dir=args.traces)
    json_path = Path(args.json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    md_path = Path(args.md)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    if not args.quiet:
        summary = report["summary"]
        print(f"[diff] traces={summary['traces']} match={summary['match']} "
              f"divergence={summary['engine_divergence']} "
              f"data_gap={summary['data_gap']} skipped={summary['skipped']} "
              f"match_rate={summary['match_rate']:.1%} "
              f"divergence_rate={summary['divergence_rate']:.1%}")
        print(f"[diff] wrote {json_path} / {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
