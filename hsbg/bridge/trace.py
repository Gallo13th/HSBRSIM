"""官方战斗轨迹（``official_combat_trace.v1``）抽取与序列化。

本模块把「官方真实对局里发生的一场战斗」抽象成可差分、可回归的 JSON 轨迹。
两种数据源：

1. ``source="hdt_bobsbuddy"`` —— **HDT 的 BobsBuddy 会话日志**
   （``%APPDATA%\\HearthstoneDeckTracker\\Logs\\hdt_log*.txt``）。
   这是本机**唯一现成的真实酒馆战棋战斗语料**：日志里 ``BobsBuddyInvoker``
   每场战斗打印
   - ``----- Simulation Input -----``：双方英雄技能、手牌、战团（按站位顺序，
     含攻击/生命/关键词/脚本计数），
   - ``----- Simulation Output -----``：BobsBuddy（第二实现）10000 次模拟的
     Win/Tie/Loss 概率，
   - ``ValidateSimulationResultAsync >> result=Win|Loss|Tie``：**官方实际结果**
     （BobsBuddy 自校验用，来自官方战斗结算）。
   注意：BobsBuddy 不是官方实现，其概率仅作「第二实现参照」；``result=`` 才是
   官方轨迹。

2. ``source="powerlog"`` —— **Power.log / HDT 录像**（zip 内 ``output_log.txt``）。
   按 ``BACON_IN_COMBAT_PHASE`` 上升/下降沿切分战斗（缺失时用
   ATTACK/DEATHS/POWER block 簇 + TURN 推进做兜底），重建战团快照与
   attack/damage/death/summon/trigger 事件流。**本机全部 1365 个录像都是
   2 人构筑局，没有真实 BG Power.log**，因此该路径目前只有合成样例验证
   （见 ``tests/test_diff_trace.py``）；一旦采集到真实 BG ``Power.log``，
   用 ``tools/diff_extract_replays.py --powerlog ...`` 即可直接产出轨迹。

设计约束
--------
* 标准库 only（与 ``hsbg.bridge.powerlog`` 一致），不 import hsrl2；
  卡 id 解析/引擎构造在 ``tools/diff_replay_combat.py`` 里做。
* **无法确定的字段写 ``None`` 并计入 ``missing_fields``，禁止猜测填充**。
* **匿名化**：不保存原始文件名（含 BattleTag）、玩家名、GameAccountId；
  只保存 ``sha256(来源文件名)[:12]`` 派生的 ``episode_id``。
* 解析必须容错：未知行只计数，不抛异常。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

# ══════════════════════════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════════════════════════

SCHEMA = "official_combat_trace.v1"
TRACEIZER_VERSION = "0.1"

SOURCE_BOBSBUDDY = "hdt_bobsbuddy"
SOURCE_POWERLOG = "powerlog"

RESULT_WIN = "win"
RESULT_LOSS = "loss"
RESULT_TIE = "tie"

#: BobsBuddy 战团行里出现的关键词/标记 → 规范化关键词名。
#:
#: 实测（679 场真实战斗全量扫描）只出现这些写法；``Div`` / ``Poison``
#: 是 BobsBuddy 的简写（全量 679 场里 ``Div`` 832 次、``Poison`` 3 次，
#: 无未映射标记）。
KEYWORD_TOKENS: Dict[str, str] = {
    "G": "golden",                     # BobsBuddy 用 G 标记金色
    "Golden": "golden",
    "Taunt": "taunt",
    "Div": "divine_shield",
    "Divine Shield": "divine_shield",
    "Poison": "poisonous",
    "Pois": "poisonous",
    "Poisonous": "poisonous",
    "Ven": "venomous",
    "Venomous": "venomous",
    "Reborn": "reborn",
    "Windfury": "windfury",
    "Mega-Windfury": "mega_windfury",
    "Cleave": "cleave",
    "Stealth": "stealth",
    "Elusive": "elusive",
    "Immune": "immune",
}

#: Power.log 的 tag 名 → 规范化关键词名
TAG_KEYWORDS: Dict[str, str] = {
    "TAUNT": "taunt",
    "DIVINE_SHIELD": "divine_shield",
    "POISONOUS": "poisonous",
    "VENOMOUS": "venomous",
    "REBORN": "reborn",
    "WINDFURY": "windfury",
    "MEGA_WINDFURY": "mega_windfury",
    "CLEAVE": "cleave",
    "STEALTH": "stealth",
    "ELUSIVE": "elusive",
}

# ── BobsBuddy 日志行正则 ──────────────────────────────────────────────
_RE_SIM_INPUT = "----- Simulation Input -----"
_RE_SIM_INPUT_END = "----- End of Input -----"
_RE_SIM_OUTPUT = "----- Simulation Output -----"
_RE_TURN_START = re.compile(
    r"HandleTurnStart >> --- (Player|Opponent) turn (\d+) ---")
_RE_HERO_POWER = re.compile(
    r"^(Player|Opponent): heroPower=(\S+), used=(\w+), data=(-?\d+)")
_RE_EXTRA_POWER = re.compile(
    r"^(Player|Opponent): extraHeroPower=(\S+), used=(\w+), data=(-?\d+)")
_RE_OUTPUT_RATES = re.compile(
    r"WinRate=([\d.]+)% \(Lethal=([\d.]+)%\), TieRate=([\d.]+)%, "
    r"LossRate=([\d.]+)% \(Lethal=([\d.]+)%\)")
_RE_OUTPUT_ITER = re.compile(r"Iterations=(\d+)")
_RE_VALIDATE = re.compile(
    r"\bresult=(\w+), lethalResult=(\w+)")
_RE_ATTACKING = re.compile(
    r"Updating entities with attacker=(.+?), defender=(.+?)$")
_RE_SNAPSHOT_BOARD = re.compile(
    r"SnapshotCurrentBoard >> Snapshotting board state for (.+?) "
    r"with player id (\d+) \((\d+) entities")
#: 「额外检测效果」段（BobsBuddy 检测到的战斗外效果；S.=Secrets）
_RE_DETECTED = re.compile(
    r"^Detected the following (player|opponent) ([A-Za-z]+)\.$")

#: BobsBuddy 战团条目：``[Name Atk/Health, 关键词, Key=Value, ...]``
_RE_BOARD_ENTRY = re.compile(r"^\[(?P<body>.+)\]$")
#: 名字里可能带逗号（"Goldrinn, the Great Wolf"）；名字不含 `数字/数字`
_RE_STAT_HEAD = re.compile(
    r"^(?P<name>.+?)\s+(?P<atk>\d+)/(?P<health>\d+)(?P<rest>.*)$")
#: 任务/奖励实体：``BG24_Quest_124 (4/10): BG24_HERO_100_Buddyt``
_RE_QUEST_ENTRY = re.compile(
    r"^(?P<name>.+?)\s*\((?P<progress>\d+)/(?P<total>\d+)\):\s*(?P<card_id>\S+)")

# ── Power.log 行正则（与 hsbg.bridge.powerlog 同口径）────────────────
_RE_LINE = re.compile(
    r"^(?P<level>[DIWE])\s+(?P<ts>\d{2}:\d{2}:\d{2}\.\d+)\s+"
    r"(?P<source>[\w.]+)\(\)\s+-\s*(?P<content>.*?)\s*$")
_RE_GAME_ENTITY = re.compile(r"^GameEntity EntityID=(\d+)")
_RE_PLAYER = re.compile(
    r"^Player EntityID=(\d+) PlayerID=(\d+)(.*)$")
_RE_FULL_CREATE = re.compile(r"^FULL_ENTITY - Creating ID=(\d+) CardID=(\S*)")
_RE_FULL_UPDATE = re.compile(r"^FULL_ENTITY - Updating (.+?) CardID=(\S*)$")
_RE_SHOW = re.compile(
    r"^(?:SHOW_ENTITY|CHANGE_ENTITY) - Updating Entity=(.+?) CardID=(\S*)")
_RE_TAG_CHANGE = re.compile(
    r"^TAG_CHANGE Entity=(.+?)\s+tag=(\S+)\s+value=(\S*)")
_RE_TAG_META = re.compile(r"^tag=(\S+)\s+value=(\S*)$")
_RE_ID_IN_REF = re.compile(r"\bid=(\d+)")
_RE_BLOCK_TYPE = re.compile(r"BlockType=(\S+)")
_RE_BLOCK_ENTITY = re.compile(r"Entity=(.+?)(?=\s+EffectCardId=|\s*$)")
_RE_BLOCK_TARGET = re.compile(
    r"Target=(.+?)(?=\s+SubOption=|\s+TriggerKeyword=|\s*$)")
_RE_BLOCK_EFFECT_CARD = re.compile(r"EffectCardId=(\S*)")
_RE_BLOCK_EFFECT_INDEX = re.compile(r"EffectIndex=(-?\d+)")

#: Power.log 里判定「这是酒馆战棋」的硬信号。
#:
#: ⚠️ 实测教训（本机 1,365 个录像）：``BACON_TRIPLE_UPGRADE_MINION_ID``
#: 在 **103 个 2 人构筑局**里出现过（单条实体 tag），单凭它会误判；
#: ``CardID=BG<数字>`` 同理（2 个构筑局引用了 ``BG31_BOB`` token）。
#: 因此严格口径 = 8 个 Player 实体（BG 是 8 人局）或以下 BG 独占信号。
BG_HARD_MARKERS = (
    "BACON_IN_COMBAT_PHASE",     # 战斗阶段标记（BG 独占）
    "PLAYER_TECH_LEVEL",         # 玩家酒馆等级（BG 独占）
    "TB_BaconShop",              # BG 商店/英雄实体前缀
)


def count_powerlog_players(text: str) -> int:
    """数 Power.log 里的 Player 实体个数（BG 应为 8）。"""
    return len(set(re.findall(r"Player EntityID=(\d+) PlayerID=(\d+)", text)))


# ══════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════


def anonymize_source(name: str) -> str:
    """把含隐私（BattleTag/玩家名）的来源文件名变成稳定匿名 id。"""
    digest = hashlib.sha256(str(name).encode("utf-8", errors="replace")).hexdigest()
    return "ep_" + digest[:12]


def make_trace_id(source: str, episode_id: str, combat_index: int,
                  turn: Optional[int], signature: str = "") -> str:
    """轨迹 id：来源+局+战斗序号+回合+战团签名（不含玩家信息）的稳定哈希。"""
    payload = f"{source}|{episode_id}|{combat_index}|{turn}|{signature}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _int_or_none(text: Any) -> Optional[int]:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def _float_or_none(text: Any) -> Optional[float]:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════


@dataclass
class TraceMinion:
    """战团里的一个随从（快照时点）。"""

    slot: int                                   # 0 起的站位（左→右）
    name: str = ""                              # 官方/日志里的卡名
    card_id: Optional[str] = None               # Power.log 直接有；BobsBuddy 只有名字
    atk: Optional[int] = None
    health: Optional[int] = None
    golden: bool = False
    keywords: List[str] = field(default_factory=list)
    tags: Dict[str, str] = field(default_factory=dict)   # 脚本计数/亡语等附加信息
    annotations: List[str] = field(default_factory=list)  # 未映射的日志标记

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"slot": self.slot}
        if self.name:
            out["name"] = self.name
        out["card_id"] = self.card_id
        out["atk"] = self.atk
        out["health"] = self.health
        out["golden"] = bool(self.golden)
        if self.keywords:
            out["keywords"] = list(self.keywords)
        if self.tags:
            out["tags"] = dict(self.tags)
        if self.annotations:
            out["annotations"] = list(self.annotations)
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceMinion":
        return cls(
            slot=int(data.get("slot", 0)),
            name=str(data.get("name") or ""),
            card_id=data.get("card_id"),
            atk=data.get("atk"),
            health=data.get("health"),
            golden=bool(data.get("golden", False)),
            keywords=list(data.get("keywords") or []),
            tags={str(k): str(v) for k, v in (data.get("tags") or {}).items()},
            annotations=list(data.get("annotations") or []),
        )


@dataclass
class Warband:
    """一方战团 + 英雄上下文（战斗开始瞬间）。"""

    side: str                                   # "player" | "opponent"
    hero_card_id: Optional[str] = None
    hero_name: Optional[str] = None
    hero_power_id: Optional[str] = None
    hero_power_used: Optional[bool] = None
    hero_power_data: Optional[int] = None
    second_hero_power_id: Optional[str] = None
    health: Optional[int] = None
    armor: Optional[int] = None
    tier: Optional[int] = None
    minions: List[TraceMinion] = field(default_factory=list)
    hand: List[TraceMinion] = field(default_factory=list)
    unsupported: List[Dict[str, Any]] = field(default_factory=list)
    #: BobsBuddy 额外检测到的「战斗外效果」（本机实测只有 BG 秘密）：
    #: ``[{"kind": "S", "value": "PackTactics"}]``。这些效果**参与**官方
    #: 战斗结算（如 Pack Tactics: 友方随从被攻击时召唤 3/3 复制），但本
    #: harness 不复现它们 → 记为 CONTEXT_GAP，不算引擎 bug。
    detected: List[Dict[str, str]] = field(default_factory=list)
    #: Deity（旧神）隐藏状态快照（可选；powerlog 六字段）：
    #: deity_card_id/deity_atk/deity_health/deity_progress/
    #: deity_awakened/deity_sigil_card_id + deity_hidden。
    deity: Optional[Dict[str, Any]] = None
    missing_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "side": self.side,
            "hero_card_id": self.hero_card_id,
            "hero_name": self.hero_name,
            "hero_power_id": self.hero_power_id,
            "hero_power_used": self.hero_power_used,
            "hero_power_data": self.hero_power_data,
            "second_hero_power_id": self.second_hero_power_id,
            "health": self.health,
            "armor": self.armor,
            "tier": self.tier,
            "minions": [m.to_dict() for m in self.minions],
            "hand": [m.to_dict() for m in self.hand],
            "unsupported": list(self.unsupported),
            "detected": [dict(item) for item in self.detected],
            "missing_fields": list(self.missing_fields),
        }
        if self.deity is not None:
            out["deity"] = dict(self.deity)
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Warband":
        return cls(
            side=str(data.get("side") or ""),
            hero_card_id=data.get("hero_card_id"),
            hero_name=data.get("hero_name"),
            hero_power_id=data.get("hero_power_id"),
            hero_power_used=data.get("hero_power_used"),
            hero_power_data=data.get("hero_power_data"),
            second_hero_power_id=data.get("second_hero_power_id"),
            health=data.get("health"),
            armor=data.get("armor"),
            tier=data.get("tier"),
            minions=[TraceMinion.from_dict(x) for x in data.get("minions") or []],
            hand=[TraceMinion.from_dict(x) for x in data.get("hand") or []],
            unsupported=list(data.get("unsupported") or []),
            detected=[dict(x) for x in data.get("detected") or []],
            deity=dict(data["deity"]) if data.get("deity") else None,
            missing_fields=list(data.get("missing_fields") or []),
        )


@dataclass
class CombatEvent:
    """战斗事件（按日志顺序）。``slot`` 是该事件时点快照里的站位。"""

    seq: int
    kind: str                                   # attack/damage/death/summon/trigger
    actor_slot: Optional[int] = None
    target_slot: Optional[int] = None
    actor_side: Optional[str] = None
    target_side: Optional[str] = None
    amount: Optional[int] = None
    card_id: Optional[str] = None
    effect_card_id: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "seq": self.seq,
            "kind": self.kind,
            "actor_slot": self.actor_slot,
            "target_slot": self.target_slot,
            "actor_side": self.actor_side,
            "target_side": self.target_side,
            "amount": self.amount,
            "card_id": self.card_id,
            "effect_card_id": self.effect_card_id,
        }
        if self.detail:
            out["detail"] = dict(self.detail)
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CombatEvent":
        return cls(
            seq=int(data.get("seq", 0)),
            kind=str(data.get("kind") or ""),
            actor_slot=data.get("actor_slot"),
            target_slot=data.get("target_slot"),
            actor_side=data.get("actor_side"),
            target_side=data.get("target_side"),
            amount=data.get("amount"),
            card_id=data.get("card_id"),
            effect_card_id=data.get("effect_card_id"),
            detail=dict(data.get("detail") or {}),
        )


@dataclass
class OfficialCombatTrace:
    """一场官方战斗的完整轨迹（``official_combat_trace.v1``）。"""

    trace_id: str
    source: str
    episode_id: str
    player: Warband
    opponent: Warband
    combat_index: int = 0
    turn: Optional[int] = None
    events: List[CombatEvent] = field(default_factory=list)
    official_result: Optional[str] = None        # win/loss/tie（player 视角）
    official_lethal: Optional[str] = None        # NoOneDied / ... (BobsBuddy)
    official_damage: Optional[Dict[str, int]] = None  # 英雄实际承受伤害（powerlog）
    #: 官方伤害上限（Power.log GameEntity tag
    #: ``BACON_COMBAT_DAMAGE_CAP``=2089 / ``..._ENABLED``=3403；缺失=None）。
    damage_cap: Optional[int] = None
    damage_cap_enabled: Optional[bool] = None
    #: 官方对局随机种子（Power.log GameEntity ``tag=GAME_SEED``；HDT 源无）。
    #: 仅作分析字段：官方 RNG 算法/整局消耗序列与引擎不同，不能直接复现
    #: attack order；见 docs/DIFF_HARNESS.md §9.6。
    game_seed: Optional[int] = None
    bb_rates: Optional[Dict[str, float]] = None  # 第二实现参照（非官方）
    bb_iterations: Optional[int] = None
    heroes: Optional[Dict[str, str]] = None      # attacker/defender 英雄名
    boundary_mode: Optional[str] = None          # powerlog 战斗切分依据
    missing_fields: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    schema: str = SCHEMA
    traceizer_version: str = TRACEIZER_VERSION

    # ── 序列化 ──────────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        out = {
            "schema": self.schema,
            "traceizer_version": self.traceizer_version,
            "trace_id": self.trace_id,
            "source": self.source,
            "episode_id": self.episode_id,
            "combat_index": self.combat_index,
            "turn": self.turn,
            "player": self.player.to_dict(),
            "opponent": self.opponent.to_dict(),
            "events": [e.to_dict() for e in self.events],
            "official_result": self.official_result,
            "official_lethal": self.official_lethal,
            "official_damage": dict(self.official_damage)
            if self.official_damage else None,
            "damage_cap": self.damage_cap,
            "damage_cap_enabled": self.damage_cap_enabled,
            "bb_rates": dict(self.bb_rates) if self.bb_rates else None,
            "bb_iterations": self.bb_iterations,
            "heroes": dict(self.heroes) if self.heroes else None,
            "boundary_mode": self.boundary_mode,
            "missing_fields": list(self.missing_fields),
            "notes": list(self.notes),
        }
        # 可选字段：只在有值时写出（旧 HDT 轨迹 JSON 保持完全不变）
        if self.game_seed is not None:
            out["game_seed"] = int(self.game_seed)
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OfficialCombatTrace":
        return cls(
            trace_id=str(data.get("trace_id") or ""),
            source=str(data.get("source") or ""),
            episode_id=str(data.get("episode_id") or ""),
            player=Warband.from_dict(data.get("player") or {}),
            opponent=Warband.from_dict(data.get("opponent") or {}),
            combat_index=int(data.get("combat_index", 0)),
            turn=data.get("turn"),
            events=[CombatEvent.from_dict(x) for x in data.get("events") or []],
            official_result=data.get("official_result"),
            official_lethal=data.get("official_lethal"),
            official_damage=data.get("official_damage"),
            damage_cap=data.get("damage_cap"),
            damage_cap_enabled=data.get("damage_cap_enabled"),
            game_seed=data.get("game_seed"),
            bb_rates=({str(k): float(v) for k, v in (data.get("bb_rates") or {}).items()}
                      if data.get("bb_rates") else None),
            bb_iterations=data.get("bb_iterations"),
            heroes=data.get("heroes"),
            boundary_mode=data.get("boundary_mode"),
            missing_fields=list(data.get("missing_fields") or []),
            notes=list(data.get("notes") or []),
            schema=str(data.get("schema") or SCHEMA),
            traceizer_version=str(data.get("traceizer_version") or ""),
        )

    # ── 摘要 ────────────────────────────────────────────────────────
    def signature(self) -> str:
        """战团签名（用于 trace_id / 跨源同局匹配，不含玩家信息）。

        优先用 ``card_id``（Power.log 原生有、HDT 经名称索引补齐后也有），
        缺失时退回名字——这样 Power.log 与 HDT 同局战团可以逐卡对齐。
        """
        parts = []
        for side in (self.player, self.opponent):
            cards = ",".join(
                f"{m.card_id or m.name or '?'}:{m.atk}/{m.health}"
                f"{'G' if m.golden else ''}" for m in side.minions)
            parts.append(f"{side.hero_power_id or ''}[{cards}]")
        return " vs ".join(parts)

    def summary(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "source": self.source,
            "turn": self.turn,
            "player_minions": len(self.player.minions),
            "opponent_minions": len(self.opponent.minions),
            "events": len(self.events),
            "official_result": self.official_result,
            "bb_rates": self.bb_rates,
            "missing_fields": list(self.missing_fields),
        }


# ══════════════════════════════════════════════════════════════════════
# 持久化
# ══════════════════════════════════════════════════════════════════════


def save_trace(trace: OfficialCombatTrace, out_dir: Path | str) -> Path:
    """把轨迹写到 ``<out_dir>/<trace_id>.json``（UTF-8，确定性缩进）。"""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{trace.trace_id}.json"
    path.write_text(
        json.dumps(trace.to_dict(), ensure_ascii=False, indent=1, sort_keys=False)
        + "\n",
        encoding="utf-8",
    )
    return path


def load_trace(path: Path | str) -> OfficialCombatTrace:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return OfficialCombatTrace.from_dict(data)


def iter_trace_paths(traces_dir: Path | str) -> Iterator[Path]:
    directory = Path(traces_dir)
    if not directory.exists():
        return
    for path in sorted(directory.glob("*.json")):
        if path.name == "index.json":
            continue
        yield path


def load_traces(traces_dir: Path | str,
                limit: Optional[int] = None) -> List[OfficialCombatTrace]:
    out: List[OfficialCombatTrace] = []
    for path in iter_trace_paths(traces_dir):
        out.append(load_trace(path))
        if limit is not None and len(out) >= int(limit):
            break
    return out


# ══════════════════════════════════════════════════════════════════════
# 源 1：HDT BobsBuddy 会话日志 → 轨迹
# ══════════════════════════════════════════════════════════════════════


def _split_commas_outside_brackets(text: str) -> List[str]:
    """按顶层逗号切分（``Deathrattles=[A, B]`` 的内部逗号不切）。"""
    parts: List[str] = []
    depth = 0
    cur: List[str] = []
    for ch in text:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def parse_bobsbuddy_board_entry(body: str) -> Dict[str, Any]:
    """解析一条 BobsBuddy 战团条目（``[Name Atk/Health, 关键词, Key=Value]``）。

    返回 dict：``kind`` ∈ ``minion`` / ``quest`` / ``unparsed``，外加
    name/atk/health/keywords/tags/annotations。
    """
    body = str(body).strip()
    quest = _RE_QUEST_ENTRY.match(body)
    if quest:
        return {
            "kind": "quest",
            "name": quest.group("name").strip(),
            "progress": _int_or_none(quest.group("progress")),
            "total": _int_or_none(quest.group("total")),
            "card_id": quest.group("card_id"),
        }
    head = _RE_STAT_HEAD.match(body)
    if head is None:
        return {"kind": "unparsed", "raw": body}
    info: Dict[str, Any] = {
        "kind": "minion",
        "name": head.group("name").strip(),
        "atk": int(head.group("atk")),
        "health": int(head.group("health")),
        "keywords": [],
        "tags": {},
        "annotations": [],
    }
    for part in _split_commas_outside_brackets(head.group("rest")):
        if "=" in part:
            key, value = part.split("=", 1)
            info["tags"][key.strip()] = value.strip()
        elif part in KEYWORD_TOKENS:
            info["keywords"].append(KEYWORD_TOKENS[part])
        else:
            info["annotations"].append(part)
    return info


def _minion_from_bobbsbuddy(info: Dict[str, Any], slot: int) -> TraceMinion:
    keywords = [k for k in info.get("keywords", []) if k != "golden"]
    return TraceMinion(
        slot=slot,
        name=str(info.get("name") or ""),
        card_id=None,                       # BobsBuddy 不打印 CardID（diff 时按名字解析）
        atk=info.get("atk"),
        health=info.get("health"),
        golden="golden" in info.get("keywords", []),
        keywords=keywords,
        tags=dict(info.get("tags") or {}),
        annotations=list(info.get("annotations") or []),
    )


def _parse_bobbsbuddy_block(lines: Sequence[str], start: int) -> Dict[str, Any]:
    """解析 ``Simulation Input`` 块（``start`` 指向块首行之后）。

    除 Player/Opponent/Hand/战团外，还解析 BobsBuddy 的「额外检测效果」段：

    ::

        Detected the following player S.
        PackTactics
        Detected the following opponent S.
        VenomstrikeTrap

    ``S.`` = Secrets（BG 秘密）。这些效果参与官方战斗结算，必须记录为
    上下文（CONTEXT_GAP），否则会被误判成引擎分歧。
    """
    block: Dict[str, Any] = {
        "player": {"board": [], "hand": [], "unsupported": [], "detected": []},
        "opponent": {"board": [], "hand": [], "unsupported": [], "detected": []},
    }
    side: Optional[str] = None
    pending_detected: Optional[tuple] = None    # (side, kind)
    i = start
    while i < len(lines):
        raw = lines[i]
        content = raw.split(">> ", 1)[-1] if ">> " in raw else raw
        if _RE_SIM_INPUT_END in raw:
            return block
        detected_match = _RE_DETECTED.match(content.strip())
        if detected_match:
            who = ("player" if detected_match.group(1) == "player"
                   else "opponent")
            pending_detected = (who, detected_match.group(2))
            i += 1
            continue
        if pending_detected is not None:
            value = content.strip()
            if value and value != "---":
                who, kind = pending_detected
                block[who]["detected"].append({"kind": kind, "value": value})
                pending_detected = None
                i += 1
                continue
            pending_detected = None
        matched = _RE_HERO_POWER.match(content) or _RE_EXTRA_POWER.match(content)
        if matched:
            who = "player" if matched.group(1) == "Player" else "opponent"
            side = who
            is_extra = "extraHeroPower" in content
            target = block[who]
            if is_extra:
                target["second_hero_power_id"] = matched.group(2)
            else:
                target["hero_power_id"] = matched.group(2)
                target["hero_power_used"] = matched.group(3) == "True"
                target["hero_power_data"] = _int_or_none(matched.group(4))
            i += 1
            continue
        hand_match = re.match(r"^Hand:\s?(.*)$", content)
        if hand_match:
            rest = hand_match.group(1).strip()
            target = block[side or "player"]
            if rest:
                for entry in re.finditer(r"\[([^\[\]]*)\]", rest):
                    info = parse_bobsbuddy_board_entry(entry.group(1))
                    if info["kind"] == "minion":
                        target["hand"].append(
                            _minion_from_bobbsbuddy(info, len(target["hand"])))
                    else:
                        target["unsupported"].append(info)
            i += 1
            continue
        entry = _RE_BOARD_ENTRY.match(content)
        if entry:
            target = block[side or "player"]
            info = parse_bobsbuddy_board_entry(entry.group("body"))
            if info["kind"] == "minion":
                target["board"].append(
                    _minion_from_bobbsbuddy(info, len(target["board"])))
            else:
                target["unsupported"].append(info)
        i += 1
    return block


def _scan_after_for_result(lines: Sequence[str], start: int) -> Dict[str, Any]:
    """从 ``start`` 向后（到下一个 Simulation Input 前）找 Output/官方结果/英雄名。"""
    found: Dict[str, Any] = {}
    limit = min(len(lines), start + 200)
    i = start
    while i < limit:
        raw = lines[i]
        if _RE_SIM_INPUT in raw:
            break
        content = raw.split(">> ", 1)[-1] if ">> " in raw else raw
        rate = _RE_OUTPUT_RATES.search(content)
        if rate:
            found["bb_rates"] = {
                "win": float(rate.group(1)) / 100.0,
                "tie": float(rate.group(3)) / 100.0,
                "loss": float(rate.group(4)) / 100.0,
                "lethal_win": float(rate.group(2)) / 100.0,
                "lethal_loss": float(rate.group(5)) / 100.0,
            }
        iteration = _RE_OUTPUT_ITER.search(content)
        if iteration:
            found["bb_iterations"] = _int_or_none(iteration.group(1))
        validate = _RE_VALIDATE.search(content)
        if validate:
            found["official_result"] = validate.group(1).lower()
            found["official_lethal"] = validate.group(2)
        attacking = _RE_ATTACKING.search(content)
        if attacking:
            found["heroes"] = {
                "attacker": attacking.group(1).strip(),
                "defender": attacking.group(2).strip(),
            }
        i += 1
    return found


def parse_hdt_bobsbuddy_text(
    text: str,
    *,
    episode_id: str,
    source_name: str = "",
    max_combats: Optional[int] = None,
) -> Tuple[List[OfficialCombatTrace], Dict[str, Any]]:
    """解析一份 HDT 会话日志文本 → 战斗轨迹列表 + 解析统计。

    ``source_name`` 只用来派生匿名 id；**不会**写进轨迹。
    """
    lines = text.splitlines()
    stats: Dict[str, Any] = {
        "lines": len(lines),
        "sim_inputs": 0,
        "parsed": 0,
        "with_official_result": 0,
        "with_bb_rates": 0,
        "skipped": {},
    }
    traces: List[OfficialCombatTrace] = []
    turn: Optional[int] = None
    i = 0
    while i < len(lines):
        line = lines[i]
        turn_match = _RE_TURN_START.search(line)
        if turn_match:
            turn = int(turn_match.group(2))
        if _RE_SIM_INPUT not in line:
            i += 1
            continue
        stats["sim_inputs"] += 1
        block = _parse_bobbsbuddy_block(lines, i + 1)
        found = _scan_after_for_result(lines, i + 1)
        missing: List[str] = []
        player = Warband(
            side="player",
            hero_power_id=block["player"].get("hero_power_id"),
            hero_power_used=block["player"].get("hero_power_used"),
            hero_power_data=block["player"].get("hero_power_data"),
            second_hero_power_id=block["player"].get("second_hero_power_id"),
            minions=block["player"]["board"],
            hand=block["player"]["hand"],
            unsupported=block["player"]["unsupported"],
            detected=block["player"]["detected"],
        )
        opponent = Warband(
            side="opponent",
            hero_power_id=block["opponent"].get("hero_power_id"),
            hero_power_used=block["opponent"].get("hero_power_used"),
            hero_power_data=block["opponent"].get("hero_power_data"),
            second_hero_power_id=block["opponent"].get("second_hero_power_id"),
            minions=block["opponent"]["board"],
            hand=block["opponent"]["hand"],
            unsupported=block["opponent"]["unsupported"],
            detected=block["opponent"]["detected"],
        )
        for band in (player, opponent):
            if band.hero_power_id is None:
                band.missing_fields.append("hero_power_id")
            missing.extend(f"{band.side}.{m}" for m in band.missing_fields)
            if band.hand:
                missing.append(f"{band.side}.hand_not_modeled")
        result = found.get("official_result")
        if result is None:
            missing.append("official_result")
        if "bb_rates" not in found:
            missing.append("bb_rates")
        trace = OfficialCombatTrace(
            trace_id=make_trace_id(
                SOURCE_BOBSBUDDY, episode_id, len(traces), turn,
                signature=";".join(
                    f"{m.name}:{m.atk}/{m.health}" for m in player.minions)),
            source=SOURCE_BOBSBUDDY,
            episode_id=episode_id,
            combat_index=len(traces),
            turn=turn,
            player=player,
            opponent=opponent,
            events=[],
            official_result=result,
            official_lethal=found.get("official_lethal"),
            bb_rates=found.get("bb_rates"),
            bb_iterations=found.get("bb_iterations"),
            heroes=found.get("heroes"),
            boundary_mode="bobsbuddy_sim",
            missing_fields=missing,
        )
        if not trace.player.minions and not trace.opponent.minions:
            stats["skipped"]["both_boards_empty"] = \
                stats["skipped"].get("both_boards_empty", 0) + 1
            i += 1
            continue
        traces.append(trace)
        stats["parsed"] += 1
        if result is not None:
            stats["with_official_result"] += 1
        if "bb_rates" in found:
            stats["with_bb_rates"] += 1
        if max_combats is not None and len(traces) >= int(max_combats):
            break
        i += 1
    return traces, stats


def resolve_trace_card_ids(
    traces: Sequence[OfficialCombatTrace],
    name_to_card: Dict[str, str],
) -> Dict[str, int]:
    """用「卡名 → card_id」索引补齐 HDT 轨迹缺失的 card_id。

    背景（2026-10-18，HDT 1.59.3）：BobsBuddy ``Simulation Input`` 的
    战团行只有名字/属性/关键词（``[Southsea Busker 3/1]``），不含
    ``cardId=``；HDT 1.53 旧会话也大多如此。旧 JSON 里 HDT 轨迹的
    ``card_id``/``hero_card_id`` 因此为 None——分布对照没问题，但
    **战团签名/逐卡归因无法交叉**。本函数用 CardDB 名称索引补齐，
    仅在 card_id 为空时填（Power.log 原始 id 不被覆盖）。

    返回统计：``{"resolved_minions": n, "resolved_hand": n,
    "resolved_heroes": n, "unresolved_minions": n}``。
    """
    index: Dict[str, str] = {}
    for name, card_id in (name_to_card or {}).items():
        if not name or not card_id:
            continue
        index[str(name)] = str(card_id)
        index.setdefault(str(name).casefold(), str(card_id))

    def lookup(name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        return index.get(str(name)) or index.get(str(name).casefold())

    stats = {"resolved_minions": 0, "resolved_hand": 0,
             "resolved_heroes": 0, "unresolved_minions": 0}
    for trace in traces:
        for band in (trace.player, trace.opponent):
            for minion in band.minions:
                if minion.card_id:
                    continue
                found = lookup(minion.name)
                if found:
                    minion.card_id = found
                    stats["resolved_minions"] += 1
                else:
                    stats["unresolved_minions"] += 1
            for minion in band.hand:
                if minion.card_id:
                    continue
                found = lookup(minion.name)
                if found:
                    minion.card_id = found
                    stats["resolved_hand"] += 1
        if trace.heroes:
            for side_name, band in (("player", trace.player),
                                    ("opponent", trace.opponent)):
                if band.hero_card_id:
                    continue
                hero_name = trace.heroes.get(
                    "attacker" if side_name == "player" else "defender")
                found = lookup(hero_name)
                if found:
                    band.hero_card_id = found
                    stats["resolved_heroes"] += 1
    return stats


def iter_hdt_bobsbuddy_traces(
    log_dir: Path | str,
    *,
    limit_files: Optional[int] = None,
    max_combats_per_file: Optional[int] = None,
) -> Tuple[List[OfficialCombatTrace], Dict[str, Any]]:
    """扫描目录下全部 ``hdt_log*.txt``，抽取 BobsBuddy 战斗轨迹。"""
    directory = Path(log_dir)
    files = sorted(directory.glob("hdt_log*.txt")) if directory.exists() else []
    if limit_files is not None:
        files = files[: int(limit_files)]
    traces: List[OfficialCombatTrace] = []
    report: Dict[str, Any] = {"files_scanned": 0, "files": [], "parsed": 0}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:  # pragma: no cover - 只读环境异常
            report["files"].append({"file": path.name, "error": str(exc)})
            continue
        report["files_scanned"] += 1
        episode_id = anonymize_source(path.name)
        file_traces, stats = parse_hdt_bobsbuddy_text(
            text, episode_id=episode_id, source_name=path.name,
            max_combats=max_combats_per_file)
        report["files"].append({"episode_id": episode_id, **stats})
        report["parsed"] += len(file_traces)
        traces.extend(file_traces)
    report["traces"] = len(traces)
    return traces, report


# ══════════════════════════════════════════════════════════════════════
# 源 2：Power.log（HDT 录像 / 游戏 Logs\\Power.log）→ 轨迹
# ══════════════════════════════════════════════════════════════════════


def is_battlegrounds_powerlog(text: str) -> bool:
    """严格酒馆战棋判定。

    只看 BG 独信号：8 个 Player 实体，或 ``BACON_IN_COMBAT_PHASE`` /
    ``PLAYER_TECH_LEVEL`` / ``TB_BaconShop``。**不**用
    ``CardID=BG<数字>`` 与 ``BACON_TRIPLE_UPGRADE_MINION_ID``（本机
    1,365 个录像里 103 个 2 人构筑局带后者、2 个引用 ``BG31_BOB``，
    单凭它们会误判，见 docs/DIFF_HARNESS.md §2.1）。
    """
    if count_powerlog_players(text) >= 8:
        return True
    return any(marker in text for marker in BG_HARD_MARKERS)


@dataclass
class _PEntity:
    eid: int
    card_id: str = ""
    tags: Dict[str, str] = field(default_factory=dict)

    def tag(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return self.tags.get(name, default)

    def int_tag(self, name: str, default: Optional[int] = None) -> Optional[int]:
        return _int_or_none(self.tags.get(name)) if name in self.tags else default


class _PowerlogCombatBuilder:
    """极简 Power.log 状态机：维护实体表 + 战斗边界 + 战斗事件流。"""

    def __init__(self) -> None:
        self.entities: Dict[int, _PEntity] = {}
        self.players: Dict[int, int] = {}        # player_id -> player entity id
        self.player_accounts: Dict[int, str] = {}  # player_id -> account raw
        self.local_player_id: Optional[int] = None
        self.game_entity_eid: int = 1
        self.episode_id: str = "powerlog"
        self.pending_eid: int = 0
        self.turn: Optional[int] = None
        self.in_combat = False
        self.bacon_phase_seen = False
        self.boundary_mode = ""
        # 当前战斗
        self._combat: Optional[Dict[str, Any]] = None
        self._pending_combat: Optional[Dict[str, Any]] = None
        self._combat_index = 0
        self._block_stack: List[Dict[str, Any]] = []
        # 战斗内英雄伤害跟踪：player_id -> {eid, start_total, min_total}
        self._hero_track: Dict[int, Dict[str, Any]] = {}
        # 战斗开始时已在 SETASIDE 的实体（用于识别战团副本还原，非召唤）
        self._combat_pre_setaside: set = set()
        # 真实 BG 日志里非战斗期也会出现攻击（如酒馆内攻击），用 turn 兜底
        self._attack_after_turn: Optional[int] = None
        # 官方伤害上限（GameEntity tag；默认 None = 日志未给）
        self.damage_cap: Optional[int] = None
        # 官方对局随机种子（GameEntity tag=GAME_SEED；分析字段）
        self.game_seed: Optional[int] = None
        self.damage_cap_enabled: Optional[bool] = None

    # ── 实体 ───────────────────────────────────────────────────────
    def entity(self, eid: int) -> _PEntity:
        ent = self.entities.get(eid)
        if ent is None:
            ent = _PEntity(eid=eid)
            self.entities[eid] = ent
        return ent

    def _resolve_ref(self, ref: str) -> int:
        text = str(ref or "").strip()
        if not text:
            return 0
        match = _RE_ID_IN_REF.search(text)
        if match:
            return int(match.group(1))
        if text.isdigit():
            return int(text)
        if "GameEntity" in text:
            return int(self.game_entity_eid or 1)
        return 0

    def _apply_tag(self, eid: int, tag: str, value: str) -> None:
        ent = self.entity(eid)
        ent.tags[tag] = value

    def _on_zone_change(self, eid: int, old_zone: Optional[str],
                        new_zone: str) -> None:
        """战斗中实体进 PLAY=召唤 / 进 GRAVEYARD=死亡（事件）。

        只记录 **MINION**：真实 BG 日志里附魔/法术/饰品/英雄技能/商店按钮
        也会频繁进 PLAY；不过滤会把召唤数/终局存活算错（8 人日志实测）。
        """
        if self._combat is None:
            return
        ent = self.entity(eid)
        if ent.tag("CARDTYPE") != "MINION":
            return
        if new_zone == "GRAVEYARD" and old_zone == "PLAY":
            self._combat["events"].append({
                "kind": "death", "eid": eid,
                "card_id": ent.card_id or None,
                "side": self._side_of(eid),
            })
        elif new_zone == "PLAY" and old_zone not in (None, "PLAY"):
            if old_zone == "SETASIDE" and self._is_restored_warboard(eid, ent):
                return
            self._combat["events"].append({
                "kind": "summon", "eid": eid,
                "card_id": ent.card_id or None,
                "side": self._side_of(eid),
            })

    def _update_hero_raw(self, eid: int, ent: "_PEntity") -> None:
        """战斗窗口内跟踪英雄等效生命（HEALTH+ARMOR−DAMAGE），仅 PLAY 区。

        真实日志英雄受伤常用 ``tag=DAMAGE``（HEALTH 不一定变）；战斗结束
        清理时 HERO 实体会被移除/重置，因此只记录 PLAY 区内的下降。
        对手英雄每场是不同 HERO 实体（eid 会变）→ 首次在 PLAY 出现时定基线。
        合成/旧格式血量在 Player 实体上 → 单独兜底跟踪。
        """
        combat = self._combat or self._pending_combat
        if combat is None:
            return
        # 合成/旧格式：Player 实体 HEALTH 变化兜底
        for pid, peid in self.players.items():
            if eid != peid:
                continue
            track = (combat.get("player_hp_raw") or {}).get(pid)
            if track is None:
                return
            health = ent.int_tag("HEALTH")
            if health is None:
                return
            total = int(health) + int(ent.int_tag("ARMOR", 0) or 0)
            track["min_total"] = min(int(track["min_total"]), total)
            return
        if ent.tag("CARDTYPE") != "HERO":
            return
        card_id = ent.card_id or ""
        if card_id.startswith(("TB_BaconShop_HERO_PH", "TB_BaconShopBob",
                               "TB_BaconShop_HERO_KelThuzad")):
            return
        if ent.tag("ZONE") != "PLAY":
            return
        health = ent.int_tag("HEALTH")
        if health is None:
            return
        controller = ent.int_tag("CONTROLLER")
        player_id = combat.get("player_id")
        opponent_id = combat.get("opponent_id")
        if controller == player_id:
            pid = player_id
        elif controller == opponent_id:
            pid = opponent_id
        else:
            return
        total = (int(health)
                 + int(ent.int_tag("ARMOR", 0) or 0)
                 - int(ent.int_tag("DAMAGE", 0) or 0))
        raw = combat.setdefault("hero_raw", {})
        track = raw.get(pid)
        if track is None or track.get("eid") != eid:
            raw[pid] = {"eid": eid, "start_total": total, "min_total": total}
        else:
            has_attacked = any(
                e.get("kind") == "attack" for e in combat.get("events") or [])
            if total > int(track["start_total"]):
                # armor/health 首次揭示：重设基线（不是回血）
                track["start_total"] = total
                track["min_total"] = total
            elif has_attacked:
                # 仅首个 ATTACK 后的下降算本场伤害；之前的下降可能是
                # 上一场末尾延迟应用的伤害（C 局 round9 假伤害）。
                track["min_total"] = min(int(track["min_total"]), total)

    def _hero_damage(self, combat: Dict[str, Any]) -> Dict[str, Optional[int]]:
        out: Dict[str, Optional[int]] = {"player": None, "opponent": None}
        raw = combat.get("hero_raw") or {}
        for side, pid in (("player", combat.get("player_id")),
                          ("opponent", combat.get("opponent_id"))):
            track = raw.get(pid) if pid is not None else None
            if not track:
                continue
            start, low = track.get("start_total"), track.get("min_total")
            if start is not None and low is not None:
                out[side] = max(0, int(start) - int(low))
        # 合成/旧格式：血量在 Player 实体上；两路取 max（真实格式
        # HERO 实体为准，合成格式 Player 实体为准）。
        player_hp = combat.get("player_hp_raw") or {}
        for side, pid in (("player", combat.get("player_id")),
                          ("opponent", combat.get("opponent_id"))):
            track = player_hp.get(pid) if pid is not None else None
            if not track:
                continue
            delta = max(0, int(track["start_total"]) - int(track["min_total"]))
            out[side] = delta if out[side] is None else max(out[side], delta)
        return out

    def _side_of(self, eid: int) -> Optional[str]:
        ent = self.entities.get(eid)
        if ent is None:
            return None
        owner = ent.int_tag("CONTROLLER")
        if owner is None:
            return None
        if self._combat is not None:
            if owner == self._combat["player_id"]:
                return "player"
            if owner == self._combat["opponent_id"]:
                return "opponent"
        return None

    def _controller_player(self, eid: int) -> Optional[int]:
        ent = self.entities.get(eid)
        if ent is None:
            return None
        return ent.int_tag("CONTROLLER")

    # ── 战斗开始/结束 ──────────────────────────────────────────────
    def _is_restored_warboard(self, eid: int, ent: "_PEntity") -> bool:
        """``SETASIDE→PLAY`` 是否只是**战团副本还原**（不是召唤）。

        真实 8 人日志（2026-10-18 e057 案例）：战斗开始时会为玩家战团创建
        SETASIDE 副本（带 ``COPIED_FROM_ENTITY_ID`` / ``BACON_DIED_LAST_COMBAT``
        标记），战斗结束再还原回 PLAY。旧逻辑一律记 summon → 终局存活数
        虚增 → 官方结果被误判（该场实际双方全灭 = tie）。判定依据：
        * ``COPIED_FROM_ENTITY_ID`` 非 0（副本来源）；
        * ``BACON_DIED_LAST_COMBAT``=1（上轮战团标记）；
        * 战斗开始时已在 SETASIDE 的实体（``_combat_pre_setaside``）。
        真正从手牌/牌库等进入 PLAY 的召唤走其它 old_zone，不受影响。
        """
        copied = str(ent.tag("COPIED_FROM_ENTITY_ID", "0") or "0")
        if copied not in ("0", "", "None"):
            return True
        died = str(ent.tag("BACON_DIED_LAST_COMBAT", "0") or "0")
        if died not in ("0", "", "None"):
            return True
        return eid in getattr(self, "_combat_pre_setaside", set())

    def _start_combat(self, reason: str) -> None:
        """战斗窗口开始：**不立即快照**（真实 8 人 BG 日志里对手战团
        在 combat 期间才进入 PLAY / 可见；本机旧逻辑在 phase=1 立刻
        snapshot 只能拿到本地板 → 全部 skip）。

        改为延迟快照：首次 ATTACK block 或双方 PLAY 区都有随从时
        `_maybe_lock_snapshot()` 锁定；player=本地 PlayerID，opponent=
        另一 Player 实体（Bob 侧）。
        """
        self._finalize_pending()
        local = self.local_player_id
        if local not in self.players:
            local = next(iter(self.players), None)
        opponent = next((pid for pid in self.players if pid != local), None)
        self._combat = {
            "reason": reason,
            "player_id": local, "opponent_id": opponent,
            "start_turn": self.turn,
            "events": [],
            "snapshot": None,
            "hero_snapshot": None,
        }
        self._hero_track = {}
        # 官方英雄掉血跟踪：pid -> {eid, start_total, min_total}
        # 不依赖快照/对手揭示（C 局 round3/4/5 的 tie 误判即快照口径导致）。
        combat_hero: Dict[int, Dict[str, Any]] = {}
        for pid in (local, opponent):
            if pid is None:
                continue
            info = self._hero_info(pid)
            if info.get("zone") == "PLAY" and info.get("health") is not None:
                total = int(info["health"]) + int(info.get("armor") or 0)
                combat_hero[pid] = {"eid": info.get("eid"),
                                    "start_total": total,
                                    "min_total": total}
        self._combat["hero_raw"] = combat_hero
        player_hp: Dict[int, Dict[str, int]] = {}
        for pid in (local, opponent):
            peid = self.players.get(pid) if pid is not None else None
            pent = self.entities.get(peid) if peid is not None else None
            health = pent.int_tag("HEALTH") if pent is not None else None
            if health is not None:
                player_hp[pid] = {"start_total": int(health),
                                  "min_total": int(health)}
        self._combat["player_hp_raw"] = player_hp
        self._combat["final_counts"] = {}
        # 战斗开始时已在 SETASIDE 的实体（战团副本还原 detection）
        self._combat_pre_setaside = {
            eid for eid, ent in self.entities.items()
            if ent.tag("ZONE") == "SETASIDE"
        }
        self.in_combat = True
        self.boundary_mode = reason

    def _hero_entity(self, player_id: Optional[int]
                     ) -> Optional[Tuple[int, "_PEntity"]]:
        """该玩家在战场上的英雄实体（排除 Bob/占位/幽灵）。

        BG Power.log 只有 2 个 Player 实体；8 个真实英雄是 SETASIDE
        实体（带 PLAYER_ID）。本地英雄在 PLAY；对手本场英雄在战斗期间
        以 PLAY/controller=对手 的 HERO 实体出现。
        """
        if player_id is None:
            return None
        best: Optional[Tuple[int, "_PEntity"]] = None
        best_zone_rank = -1
        for eid, ent in self.entities.items():
            if ent.tag("CARDTYPE") != "HERO":
                continue
            if ent.int_tag("CONTROLLER") != player_id:
                continue
            card_id = ent.card_id or ""
            if card_id.startswith(("TB_BaconShop_HERO_PH", "TB_BaconShopBob",
                                   "TB_BaconShop_HERO_KelThuzad")):
                continue
            zone = ent.tag("ZONE")
            rank = 2 if zone == "PLAY" else (1 if zone == "SETASIDE" else 0)
            # 同一 controller 下可能有其他玩家的预览英雄；PLAYER_ID 与
            # 本地 PlayerID 一致才是本场真实英雄（对手英雄 PLAYER_ID
            # 属于对手玩家，无法匹配 → 保持原 rank/eid 规则）。
            if ent.int_tag("PLAYER_ID") == player_id:
                rank += 10
            if rank < best_zone_rank:
                continue
            if rank == best_zone_rank and best is not None and eid < best[0]:
                continue
            best = (eid, ent)
            best_zone_rank = rank
        return best

    def _hero_info(self, player_id: Optional[int]) -> Dict[str, Any]:
        info: Dict[str, Any] = {"health": None, "armor": None, "tier": None,
                                "hero_card_id": None, "eid": None,
                                "zone": None}
        found = self._hero_entity(player_id)
        if found is not None:
            eid, hero = found
            info["eid"] = eid
            info["health"] = hero.int_tag("HEALTH")
            info["armor"] = hero.int_tag("ARMOR")
            info["tier"] = hero.int_tag("PLAYER_TECH_LEVEL")
            info["hero_card_id"] = hero.card_id or None
            info["zone"] = hero.tag("ZONE")
        if info["tier"] is None:
            peid = self.players.get(player_id) if player_id is not None else None
            pent = self.entities.get(peid) if peid is not None else None
            if pent is not None:
                info["tier"] = pent.int_tag("PLAYER_TECH_LEVEL") \
                    or pent.int_tag("TAVERN_TIER")
        if info["health"] is None and player_id is not None:
            # 合成旧格式：HEALTH/ARMOR 在 Player 实体上（真实 8 人日志在
            # HERO 实体上）。HERO_ENTITY tag 优先。
            peid = self.players.get(player_id)
            pent = self.entities.get(peid) if peid is not None else None
            hero_eid = pent.int_tag("HERO_ENTITY") if pent is not None else None
            hero_ent = self.entities.get(hero_eid) if hero_eid else None
            if hero_ent is not None:
                info["eid"] = hero_eid
                info["health"] = hero_ent.int_tag("HEALTH") \
                    or hero_ent.int_tag("BASE_HEALTH")
                info["armor"] = hero_ent.int_tag("ARMOR")
                info["hero_card_id"] = hero_ent.card_id or info["hero_card_id"]
                if info["health"] is None and pent is not None:
                    # 合成旧格式：血量在 Player 实体上 → 跟踪 eid 也切到
                    # Player 实体，保证 HEALTH 变化能计入英雄伤害。
                    info["eid"] = peid
                    info["health"] = pent.int_tag("HEALTH")
                    info["armor"] = pent.int_tag("ARMOR")
            elif pent is not None:
                info["health"] = pent.int_tag("HEALTH")
                info["armor"] = pent.int_tag("ARMOR")
        return info

    def _snapshot_heroes(self) -> Dict[int, Dict[str, Optional[int]]]:
        out: Dict[int, Dict[str, Optional[int]]] = {}
        for player_id in (self._combat or {}).get("player_id"), \
                (self._combat or {}).get("opponent_id"):
            if player_id is None:
                continue
            out[player_id] = self._hero_info(player_id)
        return out

    def _lock_snapshot(self, boards: Dict[int, List[Dict[str, Any]]]) -> None:
        combat = self._combat
        if combat is None:
            return
        combat["snapshot"] = boards
        combat["hero_snapshot"] = self._snapshot_heroes()
        # 英雄伤害跟踪：start=health+armor；min=战斗内最低（仅 PLAY 区）
        self._hero_track = {}
        for pid, info in (combat.get("hero_snapshot") or {}).items():
            health, armor = info.get("health"), info.get("armor")
            if health is None:
                continue
            total = int(health) + int(armor or 0)
            self._hero_track[pid] = {
                "eid": info.get("eid"),
                "start_total": total,
                "min_total": total,
            }

    def _maybe_lock_snapshot(self) -> None:
        combat = self._combat
        if combat is None or combat.get("snapshot") is not None:
            return
        boards = self._snapshot_boards()
        local = combat.get("player_id")
        opponent = combat.get("opponent_id")
        player_board = boards.get(local, []) if local is not None else []
        opp_board = boards.get(opponent, []) if opponent is not None else []
        attacked = any(event.get("kind") == "attack"
                       for event in combat.get("events") or [])
        # 真实 8 人 BG：对手战团在战斗窗口内**逐步**进入 PLAY（先出现的是
        # 预览/首个随从）→ 不能"双方都有随从"就锁。首个 ATTACK block 是
        # 战团已完整揭示的正确时点；无攻击的战斗在 finish 时兜底。
        if not attacked:
            return
        if not player_board and not opp_board:
            return
        opp_hero = self._hero_info(opponent) if opponent is not None else {}
        if (opp_hero.get("eid") is not None
                and opp_hero.get("zone") != "PLAY"):
            return
        self._lock_snapshot(boards)

    def _snapshot_boards(self) -> Dict[int, List[Dict[str, Any]]]:
        """按 CONTROLLER 汇总当前 PLAY 区随从（含 ZONE_POSITION 排序）。"""
        boards: Dict[int, List[Dict[str, Any]]] = {}
        for eid, ent in self.entities.items():
            if ent.tag("ZONE") != "PLAY":
                continue
            if ent.tag("CARDTYPE") != "MINION":
                continue
            owner = ent.int_tag("CONTROLLER")
            if owner is None:
                continue
            board = boards.setdefault(owner, [])
            atk = ent.int_tag("ATK")
            health = ent.int_tag("HEALTH")
            damage = ent.int_tag("DAMAGE", 0) or 0
            base_health = ent.int_tag("BASE_HEALTH")
            if health is None and base_health is not None:
                health = base_health - damage
            slot = ent.int_tag("ZONE_POSITION", len(board))
            keywords = [norm for tag, norm in TAG_KEYWORDS.items()
                        if str(ent.tag(tag, "0")) not in ("0", "", "None")]
            info = {
                "slot": int(slot if slot is not None else len(board)),
                "eid": eid,
                "card_id": ent.card_id or None,
                "atk": atk,
                "health": health,
                "golden": str(ent.tag("PREMIUM", "0")) not in ("0", "", "None"),
                "keywords": keywords,
                "tier": ent.int_tag("TECH_LEVEL"),
                "zone_position": int(slot) if slot is not None else None,
            }
            board.append(info)
        for board in boards.values():
            board.sort(key=lambda r: (r["zone_position"] is None,
                                      r["zone_position"] or 0))
            for idx, info in enumerate(board):
                info["slot"] = idx
        return boards

    def _finish_combat(self, reason: str) -> None:
        combat = self._combat
        if combat is None:
            return
        # 官方稳定终局窗口：phase=0 时清理标签尚未应用，PLAY 区 MINION
        # 数即战后存活；排除 enchantment/spell/按钮（_snapshot_boards 已过滤）。
        boards = self._snapshot_boards()
        if combat.get("snapshot") is None:
            self._lock_snapshot(boards)
        # 终局存活数：排除战团副本还原（SETASIDE 副本回到 PLAY，不算
        # 战斗幸存者；e057 回归）。
        final_counts: Dict[int, int] = {}
        for pid in (combat.get("player_id"), combat.get("opponent_id")):
            if pid is None:
                continue
            count = 0
            for eid, ent in self.entities.items():
                if ent.tag("CARDTYPE") != "MINION":
                    continue
                if ent.tag("ZONE") != "PLAY":
                    continue
                if ent.int_tag("CONTROLLER") != pid:
                    continue
                if self._is_restored_warboard(eid, ent):
                    continue
                count += 1
            final_counts[pid] = count
        combat["final_counts"] = final_counts
        # **延迟 finalize**：战斗伤害在 phase=0 之后才写入英雄 tag；
        # 保留 pending 继续跟踪 hero_raw，直到下一 TURN/下一场战斗前，
        # 再 build trace（否则 round8/9 伤害会串到下一场）。
        combat["end_reason"] = reason
        self._pending_combat = combat
        self._combat = None
        self.in_combat = False
        self._hero_track = {}

    def _finalize_pending(self) -> None:
        combat = self._pending_combat
        if combat is None:
            return
        self._pending_combat = None
        ok = self._build_trace(combat)
        if ok:
            self._combat_index += 1

    def _pick_combatants(self, events: List[Dict[str, Any]]) -> Tuple[Optional[int], Optional[int]]:
        for event in events:
            if event.get("kind") != "attack":
                continue
            actor = self._controller_player(event.get("actor_eid") or 0)
            target = self._controller_player(event.get("target_eid") or 0)
            if actor is not None and target is not None and actor != target:
                return actor, target
        return None, None

    def _build_trace(self, combat: Dict[str, Any]) -> bool:
        events_raw = combat["events"]
        player_id = combat.get("player_id")
        opponent_id = combat.get("opponent_id")
        if player_id is None or opponent_id is None:
            player_id, opponent_id = self._pick_combatants(events_raw)
        if player_id is None:
            # 用英雄掉血兜底（BG 战败方英雄扣血）
            damaged = combat.get("damaged_players") or []
            if len(damaged) == 2:
                player_id, opponent_id = damaged[0], damaged[1]
        if player_id is None:
            self.skipped_battles = getattr(self, "skipped_battles", 0) + 1
            return False
        combat["player_id"], combat["opponent_id"] = player_id, opponent_id
        snap = combat.get("snapshot") or {}
        player_board = snap.get(player_id, [])
        opp_board = snap.get(opponent_id, [])
        if not player_board and not opp_board:
            self.skipped_battles = getattr(self, "skipped_battles", 0) + 1
            return False
        eid_to_slot: Dict[int, Tuple[str, int]] = {}
        for side, board in (("player", player_board), ("opponent", opp_board)):
            for info in board:
                eid_to_slot[info["eid"]] = (side, info["slot"])
        events: List[CombatEvent] = []
        for raw in events_raw:
            kind = raw.get("kind")
            actor_eid = raw.get("actor_eid")
            target_eid = raw.get("target_eid")
            if "eid" in raw:                      # death/summon 用 eid 表达
                if kind == "death":
                    target_eid = raw.get("eid")
                elif kind == "summon":
                    actor_eid = raw.get("eid")
            actor = eid_to_slot.get(actor_eid) if actor_eid else None
            target = eid_to_slot.get(target_eid) if target_eid else None
            if kind == "attack" and actor is None and target is None:
                # 攻击者/目标都不在战斗快照里（比如打英雄）仍保留
                pass
            events.append(CombatEvent(
                seq=len(events),
                kind=str(kind),
                actor_slot=actor[1] if actor else None,
                target_slot=target[1] if target else None,
                actor_side=actor[0] if actor else raw.get("side"),
                target_side=target[0] if target else raw.get("target_side"),
                amount=raw.get("amount"),
                card_id=raw.get("card_id"),
                effect_card_id=raw.get("effect_card_id"),
                detail={k: v for k, v in raw.items()
                        if k not in ("kind", "actor_eid", "target_eid",
                                     "amount", "card_id", "effect_card_id",
                                     "side", "target_side")},
            ))
        player = self._warband("player", player_id, player_board, combat)
        opponent = self._warband("opponent", opponent_id, opp_board, combat)
        result, result_missing, damage = self._official_result(
            combat, player, opponent)
        missing: List[str] = ["official_result"] if result is None else []
        missing.extend(result_missing)
        # 日志截断（EOF 收尾且无任何战斗事件）→ 结果不可判定，不猜
        if combat.get("end_reason") == "eof" and not events_raw:
            result = None
            if "truncated_combat" not in missing:
                missing.append("truncated_combat")
        for band in (player, opponent):
            missing.extend(f"{band.side}.{f}" for f in band.missing_fields)
        trace = OfficialCombatTrace(
            trace_id=make_trace_id(
                SOURCE_POWERLOG, self.episode_id, self._combat_index,
                combat.get("start_turn"),
                signature=";".join(
                    f"{m.card_id}:{m.atk}/{m.health}" for m in player.minions)),
            source=SOURCE_POWERLOG,
            episode_id=self.episode_id,
            combat_index=self._combat_index,
            turn=combat.get("start_turn"),
            player=player,
            opponent=opponent,
            events=events,
            official_result=result,
            official_damage=damage,
            damage_cap=self.damage_cap,
            damage_cap_enabled=self.damage_cap_enabled,
            game_seed=self.game_seed,
            boundary_mode=combat.get("reason"),
            missing_fields=missing,
            notes=([f"end={combat.get('end_reason')}"]
                   + (["result_conflict"]
                      if combat.get("result_conflict") else [])),
        )
        self.traces.append(trace)
        return True

    def _warband(self, side: str, player_id: int,
                 board: List[Dict[str, Any]],
                 combat: Dict[str, Any]) -> Warband:
        minions = [
            TraceMinion(
                slot=info["slot"],
                name="",
                card_id=info["card_id"],
                atk=info["atk"],
                health=info["health"],
                golden=info["golden"],
                keywords=list(info["keywords"]),
                tags={},
            )
            for info in board
        ]
        band = Warband(side=side, minions=minions)
        player_eid = self.players.get(player_id)
        if player_eid is None:
            band.missing_fields.append("player_entity")
            return band
        hero_snapshot = (combat.get("hero_snapshot") or {}).get(player_id) or {}
        band.health = hero_snapshot.get("health")
        band.armor = hero_snapshot.get("armor")
        band.tier = hero_snapshot.get("tier")
        band.hero_card_id = hero_snapshot.get("hero_card_id")
        pent = self.entities.get(player_eid)
        if pent is not None:
            hero_eid = pent.int_tag("HERO_ENTITY")
            band.hero_power_id = self._hero_power_of(player_eid, hero_eid)
        for field_name in ("hero_card_id", "health"):
            if getattr(band, field_name) is None:
                band.missing_fields.append(field_name)
        return band

    def _hero_power_of(self, player_eid: int, hero_eid: Optional[int]) -> Optional[str]:
        if hero_eid is None:
            return None
        for eid, ent in self.entities.items():
            if ent.int_tag("CONTROLLER") != self.entities[player_eid].int_tag(
                    "PLAYER_ID"):
                continue
            if ent.tag("CARDTYPE") == "HERO_POWER" and ent.card_id:
                return ent.card_id
        return None

    def _official_result(self, combat: Dict[str, Any],
                         player: Warband,
                         opponent: Warband
                         ) -> Tuple[Optional[str], List[str], Optional[Dict[str, int]]]:
        """Power.log 胜负判定（存活为主 + 英雄掉血纠偏，不猜）。

        * 主判据仍是「快照初始 + 战斗内 summon − death」的终局存活数
          （B 局 10/10 依赖该口径，且与 e057 tie 一致）；
        * **仅当存活判为平局**时，用官方英雄实际掉血（PLAY 区
          HEALTH+ARMOR−DAMAGE 下降）纠偏：单侧掉血 → 该侧败；
          两侧都掉血 → 保留 tie 并记 ``result_conflict``；
        * 对手未揭示/快照缺失 → ``None``（不猜）。
        """
        snap = combat.get("snapshot") or {}
        p0 = len(snap.get(combat.get("player_id"), []))
        o0 = len(snap.get(combat.get("opponent_id"), []))
        p_surv, o_surv = p0, o0
        for event in combat.get("events") or []:
            side = event.get("side")
            kind = event.get("kind")
            if kind == "death":
                if side == "player":
                    p_surv -= 1
                elif side == "opponent":
                    o_surv -= 1
            elif kind == "summon":
                if side == "player":
                    p_surv += 1
                elif side == "opponent":
                    o_surv += 1
        p_surv, o_surv = max(0, p_surv), max(0, o_surv)
        damage = self._hero_damage(combat)
        p_dmg, o_dmg = damage["player"], damage["opponent"]
        evidence = {"hero_damage": dict(damage),
                    "survivors": {"player": p_surv,
                                  "opponent": o_surv}}
        combat["result_evidence"] = evidence
        missing: List[str] = []
        conflict = False

        if p_surv > 0 and o_surv == 0:
            result: Optional[str] = RESULT_WIN
        elif o_surv > 0 and p_surv == 0:
            result = RESULT_LOSS
        elif p_surv == 0 and o_surv == 0:
            result = RESULT_TIE
        else:
            result = None

        # 英雄信号纠偏：只在存活平局时启用（B 局非平局不动，防回归）
        if result == RESULT_TIE:
            if p_dmg is not None and p_dmg > 0 and (o_dmg == 0):
                result = RESULT_LOSS
            elif o_dmg is not None and o_dmg > 0 and (p_dmg == 0):
                result = RESULT_WIN
            elif p_dmg is not None and o_dmg is None and p_dmg > 0:
                result = RESULT_LOSS
            elif o_dmg is not None and p_dmg is None and o_dmg > 0:
                result = RESULT_WIN
            elif p_dmg is not None and o_dmg is not None \
                    and p_dmg > 0 and o_dmg > 0:
                conflict = True
        # 存活数歧义（双方都有存活）→ 单侧英雄掉血兜底；仍无法判定则 None
        if result is None and p_dmg is not None and o_dmg is not None:
            if p_dmg > 0 and o_dmg == 0:
                result = RESULT_LOSS
            elif o_dmg > 0 and p_dmg == 0:
                result = RESULT_WIN
        if result is None and p_dmg is not None and o_dmg is None:
            result = RESULT_LOSS if p_dmg > 0 else None
        if result is None and o_dmg is not None and p_dmg is None:
            result = RESULT_WIN if o_dmg > 0 else None
        if result is None:
            missing.append("official_result")
        if conflict:
            missing.append("result_conflict")
            combat["result_conflict"] = True
        return result, missing, (damage if p_dmg is not None
                                 or o_dmg is not None else None)

    # ── 行处理 ────────────────────────────────────────────────────
    def feed_line(self, raw_line: str) -> None:
        line = raw_line.rstrip("\r\n")
        match = _RE_LINE.match(line)
        if match is None:
            return
        source = match.group("source")
        if not source.startswith("GameState."):
            return
        content = match.group("content")
        if content == "CREATE_GAME":
            self.entities.clear()
            self.players.clear()
            self.player_accounts.clear()
            self.local_player_id = None
            self.turn = None
            self.in_combat = False
            self.bacon_phase_seen = False
            if self._pending_combat is not None:
                self._finalize_pending()
            self._combat = None
            self._block_stack = []
            self._hero_track = {}
            self._combat_pre_setaside = set()
            self.damage_cap = None
            self.damage_cap_enabled = None
            self.game_seed = None
            return
        game_entity = _RE_GAME_ENTITY.match(content)
        if game_entity:
            self.pending_eid = int(game_entity.group(1))
            self.game_entity_eid = self.pending_eid
            self.entity(self.pending_eid)
            return
        player = _RE_PLAYER.match(content)
        if player:
            self.pending_eid = int(player.group(1))
            pid = int(player.group(2))
            self.players[pid] = self.pending_eid
            account = (player.group(3) or "").strip()
            if account:
                self.player_accounts[pid] = account
                hi = re.search(r"hi=(\d+)", account)
                if (self.local_player_id is None and hi is not None
                        and hi.group(1) not in ("0", "")):
                    self.local_player_id = pid
            self.entity(self.pending_eid)
            return
        creating = _RE_FULL_CREATE.match(content)
        if creating:
            self.pending_eid = int(creating.group(1))
            ent = self.entity(self.pending_eid)
            card_id = creating.group(2)
            if card_id:
                ent.card_id = card_id
            return
        update = _RE_FULL_UPDATE.match(content) or _RE_SHOW.match(content)
        if update:
            ref = update.group(1)
            card_id = update.group(2)
            eid = self._resolve_ref(ref)
            if eid:
                self.pending_eid = eid
                ent = self.entity(eid)
                if card_id:
                    ent.card_id = card_id
                self._merge_ref_tags(ent, ref)
            return
        tag_change = _RE_TAG_CHANGE.match(content)
        if tag_change:
            ref = tag_change.group(1)
            eid = self._resolve_ref(ref)
            if not eid:
                return
            tag, value = tag_change.group(2), tag_change.group(3)
            self._handle_tag_change(eid, tag, value, ref=ref)
            self._maybe_lock_snapshot()
            return
        meta = _RE_TAG_META.match(content)
        if meta and self.pending_eid:
            self._handle_tag_change(self.pending_eid, meta.group(1),
                                    meta.group(2))
            self._maybe_lock_snapshot()
            return
        if content.startswith("BLOCK_START"):
            self._handle_block_start(content)
            self._maybe_lock_snapshot()
            return
        if content.startswith("BLOCK_END"):
            if self._block_stack:
                self._block_stack.pop()
            return

    def _merge_ref_tags(self, ent: _PEntity, ref: str) -> None:
        zone = re.search(r"\bzone=(\S+)", ref)
        if zone:
            ent.tags.setdefault("ZONE", zone.group(1))
        player = re.search(r"\bplayer=(\d+)", ref)
        if player:
            ent.tags["CONTROLLER"] = player.group(1)
        match = re.search(r"\bcardId=(\S+)", ref)
        if match and not ent.card_id:
            ent.card_id = match.group(1)

    def _track_hero_delta(self, eid: int, ent: "_PEntity") -> None:
        """战斗内英雄 HEALTH/ARMOR 跟踪（仅 PLAY 区，排除结束清理重置）。"""
        combat = self._combat
        if combat is None or not self._hero_track:
            return
        for track in self._hero_track.values():
            if track.get("eid") != eid:
                continue
            if ent.tag("ZONE") != "PLAY":
                return
            health = ent.int_tag("HEALTH")
            if health is None:
                return
            total = int(health) + int(ent.int_tag("ARMOR", 0) or 0)
            track["min_total"] = min(int(track["min_total"]), total)
            return

    def _handle_tag_change(self, eid: int, tag: str, value: str,
                           ref: Optional[str] = None) -> None:
        ent = self.entity(eid)
        if ref:
            self._merge_ref_tags(ent, ref)
        old = ent.tags.get(tag)
        ent.tags[tag] = value
        self._track_hero_delta(eid, ent)
        self._update_hero_raw(eid, ent)
        if tag == "TURN":
            turn = _int_or_none(value)
            if turn is not None and turn > 0:
                self.turn = turn
                if self._pending_combat is not None:
                    self._finalize_pending()
                if self.in_combat and self.boundary_mode == "heuristic_blocks":
                    self._finish_combat("turn_advance")
            return
        if tag == "BACON_IN_COMBAT_PHASE":
            self.bacon_phase_seen = True
            on = str(value) not in ("0", "", "None")
            if on and not self.in_combat:
                self._start_combat("bacon_phase")
            elif not on and self.in_combat:
                self._finish_combat("bacon_phase_end")
            return
        # 官方伤害上限（服务端 GameEntity tag；供 harness 注入引擎）：
        # BACON_COMBAT_DAMAGE_CAP(2089) / BACON_COMBAT_DAMAGE_CAP_ENABLED(3403)
        if tag in ("BACON_COMBAT_DAMAGE_CAP",
                   "BACON_COMBAT_DAMAGE_CAP_ENABLED"):
            if tag.endswith("_ENABLED"):
                self.damage_cap_enabled = str(value) not in ("0", "", "None")
            else:
                self.damage_cap = _int_or_none(value)
            return
        if tag == "GAME_SEED":
            self.game_seed = _int_or_none(value)
            return
        if tag == "ZONE":
            self._on_zone_change(eid, old, value)
            return
        if self._combat is None:
            return
        if tag in ("PROPOSED_ATTACKER", "PROPOSED_DEFENDER"):
            block = self._block_stack[-1] if self._block_stack else None
            if block is None or block.get("block_type") != "ATTACK":
                return
            value_eid = _int_or_none(value) or 0
            if tag == "PROPOSED_ATTACKER" and value_eid:
                block["actor_eid"] = value_eid
            elif tag == "PROPOSED_DEFENDER" and value_eid:
                block["target_eid"] = value_eid
                if not block.get("attack_recorded"):
                    block["attack_recorded"] = True
                    actor_eid = block.get("actor_eid") or 0
                    target_eid = block.get("target_eid") or 0
                    self._combat["events"].append({
                        "kind": "attack", "actor_eid": actor_eid,
                        "target_eid": target_eid,
                        "side": self._side_of(actor_eid),
                        "target_side": self._side_of(target_eid),
                    })
            return
        if tag == "DAMAGE":
            new_damage = _int_or_none(value)
            old_damage = _int_or_none(old) if old is not None else 0
            if new_damage is not None and old_damage is not None:
                delta = new_damage - old_damage
                if delta > 0:
                    self._combat["events"].append({
                        "kind": "damage", "target_eid": eid,
                        "amount": delta, "target_side": self._side_of(eid),
                        "card_id": ent.card_id or None,
                    })

    def _handle_block_start(self, content: str) -> None:
        block_type_match = _RE_BLOCK_TYPE.search(content)
        block_type = block_type_match.group(1) if block_type_match else ""
        entity_ref = _RE_BLOCK_ENTITY.search(content)
        target_ref = _RE_BLOCK_TARGET.search(content)
        effect_card = _RE_BLOCK_EFFECT_CARD.search(content)
        actor_eid = self._resolve_ref(entity_ref.group(1)) if entity_ref else 0
        target_eid = self._resolve_ref(target_ref.group(1)) if target_ref else 0
        block = {
            "block_type": block_type,
            "actor_eid": actor_eid,
            "effect_card_id": effect_card.group(1) if effect_card else "",
        }
        # 没有 BACON_IN_COMBAT_PHASE 的日志（老/其他版本）：ATTACK 簇兜底
        if (not self.bacon_phase_seen and not self.in_combat
                and block_type == "ATTACK"):
            self._start_combat("heuristic_blocks")
        if self._combat is None:
            return
        if block_type == "ATTACK":
            # 真实 8 人日志：BLOCK_START 的 Target=0，真实目标由紧随的
            # TAG_CHANGE GameEntity PROPOSED_DEFENDER=<eid> 给出 →
            # 延迟到 _handle_tag_change 记录。合成旧格式/HDT 直接给了
            # Target 引用 → 立即记录（保持旧测试与格式兼容）。
            if target_eid:
                block["attack_recorded"] = True
                self._combat["events"].append({
                    "kind": "attack", "actor_eid": actor_eid,
                    "target_eid": target_eid,
                    "side": self._side_of(actor_eid),
                    "target_side": self._side_of(target_eid),
                })
        elif block_type == "TRIGGER":
            # 官方 TRIGGER block 暂不进入可比事件流：引擎事件捕获只有
            # attack/damage/death/summon（脚本钩子触发没有同构事件），
            # 保留会让事件级对齐永远在第一个 trigger 处失配。TRIGGER
            # 信息（effect/card_id）仍可用于后续人工归因，但本版事件
            # 级差分只比较四类可比事件。
            pass
        elif block_type in ("DEATHS", "POWER"):
            block["block_index"] = len(self._block_stack)
        self._block_stack.append(block)

    def finish(self) -> None:
        if self.in_combat:
            self._finish_combat("eof")
        self._finalize_pending()


def parse_bg_powerlog_text(
    text: str,
    *,
    episode_id: str = "powerlog",
    source_name: str = "",
    max_combats: Optional[int] = None,
) -> Tuple[List[OfficialCombatTrace], Dict[str, Any]]:
    """从 Power.log 文本抽取 BG 战斗轨迹（需要真实 BG 日志；本机暂无）。"""
    builder = _PowerlogCombatBuilder()
    builder.traces = []
    builder.skipped_battles = 0
    builder.episode_id = episode_id or "powerlog"
    for line in text.splitlines():
        builder.feed_line(line)
        if (max_combats is not None and len(builder.traces) >= int(max_combats)):
            break
    builder.finish()
    stats = {
        "lines": text.count("\n") + 1 if text else 0,
        "combats": len(builder.traces),
        "skipped_battles": builder.skipped_battles,
        "boundary_mode": builder.boundary_mode or "",
        "bacon_phase_seen": builder.bacon_phase_seen,
        "episode_id": episode_id,
    }
    return builder.traces, stats


# ══════════════════════════════════════════════════════════════════════
# 统计
# ══════════════════════════════════════════════════════════════════════

#: 轨迹字段完整率统计口径（出现 = 非 None / 非空列表）
COMPLETENESS_FIELDS = (
    "official_result", "turn", "hero_power_id", "hero_card_id",
    "bb_rates", "events", "player.minions", "opponent.minions",
)


def trace_statistics(traces: Sequence[OfficialCombatTrace]) -> Dict[str, Any]:
    """聚合统计：来源/结果分布/字段完整率/缺失字段计数。"""
    from collections import Counter

    sources = Counter(t.source for t in traces)
    results = Counter(t.official_result for t in traces)
    missing = Counter()
    for trace in traces:
        for item in trace.missing_fields:
            missing[item] += 1
        for band in (trace.player, trace.opponent):
            for item in band.missing_fields:
                missing[f"{band.side}.{item}"] += 1
    total = len(traces)

    def _has(trace: OfficialCombatTrace, name: str) -> bool:
        if name == "official_result":
            return trace.official_result is not None
        if name == "turn":
            return trace.turn is not None
        if name == "hero_power_id":
            return trace.player.hero_power_id is not None
        if name == "hero_card_id":
            return trace.player.hero_card_id is not None
        if name == "bb_rates":
            return bool(trace.bb_rates)
        if name == "events":
            return bool(trace.events)
        if name == "player.minions":
            return bool(trace.player.minions)
        if name == "opponent.minions":
            return bool(trace.opponent.minions)
        raise KeyError(name)

    completeness = {
        name: round(sum(1 for t in traces if _has(t, name)) / total, 4)
        if total else 0.0
        for name in COMPLETENESS_FIELDS
    }
    return {
        "traces": total,
        "sources": dict(sources),
        "results": {str(k): v for k, v in results.items() if k is not None}
        | ({"null": results.get(None, 0)} if results.get(None) else {}),
        "field_completeness": completeness,
        "missing_field_counts": dict(missing.most_common()),
        "avg_player_minions": round(
            sum(len(t.player.minions) for t in traces) / total, 2) if total else 0.0,
        "avg_opponent_minions": round(
            sum(len(t.opponent.minions) for t in traces) / total, 2) if total else 0.0,
        "with_bb_rates": sum(1 for t in traces if t.bb_rates),
    }


__all__ = [
    "SCHEMA", "TRACEIZER_VERSION", "SOURCE_BOBSBUDDY", "SOURCE_POWERLOG",
    "RESULT_WIN", "RESULT_LOSS", "RESULT_TIE",
    "KEYWORD_TOKENS", "TAG_KEYWORDS", "BG_HARD_MARKERS",
    "TraceMinion", "Warband", "CombatEvent", "OfficialCombatTrace",
    "anonymize_source", "make_trace_id",
    "parse_bobsbuddy_board_entry", "parse_hdt_bobsbuddy_text",
    "iter_hdt_bobsbuddy_traces",
    "is_battlegrounds_powerlog", "count_powerlog_players",
    "parse_bg_powerlog_text",
    "save_trace", "load_trace", "iter_trace_paths", "load_traces",
    "trace_statistics", "COMPLETENESS_FIELDS",
]
