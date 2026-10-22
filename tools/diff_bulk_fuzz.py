"""离线批量差分 runner：真实战团状态 → 引擎 vs 第三方 oracle。

背景/边界
---------
* 官方服务端战斗裁决器在客户端不可见（`docs/OFFICIAL_EXACTNESS.md §7`），
  因此**不存在"官方实现级全量等价"**；本 runner 做的是**结果/事件/分布级**
  验证，BobsBuddy（BB）只是**第三方参照**，不是官方。
* 训练/评测需要近乎无限的状态空间；真实语料只能覆盖出现过的分布。本
  runner 从已采集语料采样战斗边界状态，并只在**观测到的分布范围内**做
  突变（属性分位、关键词组合、站位、战团大小），输出明确标注
  「采样覆盖，非穷举」。
* 当前 BB oracle 未接入（engine-analyst 在做）：`--oracle stub` 用独立的
  统计启发式（非官方、非 BB）验证管线；接入后 `--oracle bobsbuddy`
  走同一接口。**不要把 stub 结果当成官方/BB 结论。**

用法
----
::

    python tools/diff_bulk_fuzz.py --states 100 --engine-seeds 64 ^
        --oracle-sims 100 --oracle stub ^
        --out-jsonl runs/diff_bulk_fuzz_smoke.jsonl ^
        --out-md runs/diff_bulk_fuzz_smoke.md

输出：JSONL 明细（每状态一行）+ 汇总 Markdown（覆盖率/一致性/分层 TOP）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.bridge import trace as T  # noqa: E402

DEFAULT_TRACE_DIRS = [
    ROOT / "runs" / "official_traces_powerlog",
    ROOT / "runs" / "official_traces_powerlog2",
    ROOT / "runs" / "official_traces_powerlog3",
    ROOT / "runs" / "official_traces_hdt",
    ROOT / "runs" / "official_traces_hdt2",
    ROOT / "runs" / "official_traces_hdt3",
]
DEFAULT_LAST_GAMES = ROOT / "runs" / "bg_last_games_20261018.xml"
OUT_JSONL = ROOT / "runs" / "diff_bulk_fuzz_smoke.jsonl"
OUT_MD = ROOT / "runs" / "diff_bulk_fuzz_smoke.md"

#: CardDef/BgsLastGames 的数值 tag（仅取已知 ATK/HEALTH；未知 tag 忽略）
_LASTGAME_ATK_TAG = "47"
_LASTGAME_HEALTH_TAG = "45"


# ══════════════════════════════════════════════════════════════════════
# 状态采样
# ══════════════════════════════════════════════════════════════════════


class StatePool:
    """真实语料里的战团状态池 + 每张卡观测分布。"""

    def __init__(self) -> None:
        self.states: List[Dict[str, Any]] = []
        self.card_stats: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
        self.card_keyword_sets: Dict[str, Counter] = defaultdict(Counter)
        self.sources = Counter()

    def add_trace_dirs(self, dirs: Sequence[Path]) -> None:
        for directory in dirs:
            if not directory.exists():
                continue
            for path in T.iter_trace_paths(directory):
                try:
                    trace = T.load_trace(path)
                except (OSError, ValueError, KeyError):
                    continue
                self._add_trace(trace, source=directory.name)
                self.sources[directory.name] += 1

    def _add_trace(self, trace: T.OfficialCombatTrace, *, source: str) -> None:
        state = self._trace_to_state(trace, source=source)
        if state is None:
            return
        self.states.append(state)
        for side in ("player", "opponent"):
            for minion in state[side]["minions"]:
                card = minion.get("card_id") or minion.get("name") or "?"
                self.card_stats[card].append(
                    (int(minion.get("atk") or 0),
                     int(minion.get("health") or 0)))
                self.card_keyword_sets[card][tuple(sorted(
                    minion.get("keywords") or []))] += 1

    @staticmethod
    def _trace_to_state(trace: T.OfficialCombatTrace, *,
                        source: str) -> Optional[Dict[str, Any]]:
        player = [m.to_dict() for m in trace.player.minions]
        opponent = [m.to_dict() for m in trace.opponent.minions]
        if not player or not opponent:
            return None
        return {
            "source": source,
            "source_trace": trace.trace_id,
            "turn": trace.turn,
            "player": {
                "hero_power_id": trace.player.hero_power_id,
                "minions": player,
            },
            "opponent": {
                "hero_power_id": trace.opponent.hero_power_id,
                "minions": opponent,
            },
            "official_result": trace.official_result,
        }

    def add_bg_last_games(self, path: Path) -> None:
        """从 HDT `BgsLastGames.xml` 提取 45 局终局战团（仅观测值）。"""
        if not path.exists():
            return
        try:
            import xml.etree.ElementTree as ET
        except ImportError:  # pragma: no cover
            return
        try:
            root = ET.fromstring(path.read_text(encoding="utf-8",
                                                errors="replace"))
        except ET.ParseError:
            return
        for game in root.findall("Game"):
            board = game.find("FinalBoard")
            if board is None:
                continue
            minions: List[Dict[str, Any]] = []
            for minion in board.findall("Minion"):
                card = (minion.findtext("CardId") or "").strip()
                if not card:
                    continue
                tags = {tag.get("Tag"): tag.get("Value")
                        for tag in minion.findall("Tags")}
                atk = _to_int(tags.get(_LASTGAME_ATK_TAG))
                health = _to_int(tags.get(_LASTGAME_HEALTH_TAG))
                if atk is None or health is None:
                    continue
                minions.append({
                    "card_id": card, "name": "", "atk": atk,
                    "health": health, "golden": False,
                    "keywords": [], "tags": {},
                })
            if not minions:
                continue
            # 终局战团只有本地一方；生成镜像对手（同分布采样）以构成可差分状态
            self.states.append({
                "source": "bg_last_games",
                "source_trace": f"lastgame_{game.get('StartTime', '')}",
                "turn": None,
                "player": {
                    "hero_power_id": game.get("Hero"),
                    "minions": minions,
                },
                "opponent": {
                    "hero_power_id": None,
                    "minions": [],
                },
                "official_result": None,
                "needs_opponent": True,
            })
            self.sources["bg_last_games"] += 1
            for minion in minions:
                card = minion["card_id"]
                self.card_stats[card].append((minion["atk"], minion["health"]))
                self.card_keyword_sets[card][tuple()] += 1


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _copy_state(state: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(state, ensure_ascii=False))


def _observed_range(pool: StatePool, card: str,
                    fallback: Tuple[int, int]
                    ) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    values = pool.card_stats.get(card) or []
    if len(values) < 3:
        return fallback, fallback
    atks = sorted(v[0] for v in values)
    healths = sorted(v[1] for v in values)
    lo_i, hi_i = max(0, int(0.05 * (len(atks) - 1))), min(
        len(atks) - 1, int(0.95 * (len(atks) - 1)))
    return (max(0, atks[lo_i]), max(1, healths[lo_i])), \
        (max(1, atks[hi_i]), max(1, healths[hi_i]))


def mutate_state(pool: StatePool, state: Dict[str, Any],
                 rng: random.Random) -> Tuple[Dict[str, Any], List[str]]:
    """在观测分布内做小幅突变（不臆造未观测的属性/关键词）。"""
    out = _copy_state(state)
    mutations: List[str] = []
    if out.get("needs_opponent"):
        candidates = [s for s in pool.states if not s.get("needs_opponent")]
        if candidates:
            other = rng.choice(candidates)
            out["opponent"] = _copy_state(other)["opponent"]
            mutations.append("opponent_sampled")

    for side in ("player", "opponent"):
        minions = out[side]["minions"]
        if not minions:
            continue
        # 1) 属性分位内抖动
        if rng.random() < 0.5:
            for minion in minions:
                card = minion.get("card_id") or minion.get("name") or "?"
                lo, hi = _observed_range(
                    pool, card,
                    ((minion.get("atk") or 1), (minion.get("health") or 1)))
                if rng.random() < 0.5:
                    minion["atk"] = max(lo[0], min(hi[0], int(
                        minion.get("atk") or lo[0]) + rng.randint(-1, 1)))
                if rng.random() < 0.5:
                    minion["health"] = max(lo[1], min(hi[1], int(
                        minion.get("health") or lo[1]) + rng.randint(-1, 1)))
            mutations.append(f"{side}_stat_jitter")
        # 2) 关键词组合：从该卡观测组合里抽
        if rng.random() < 0.3:
            for minion in minions:
                card = minion.get("card_id") or minion.get("name") or "?"
                observed = pool.card_keyword_sets.get(card)
                if observed and rng.random() < 0.5:
                    combo = rng.choice(list(observed))
                    minion["keywords"] = list(combo)
            mutations.append(f"{side}_keyword_combo")
        # 3) 站位
        if rng.random() < 0.3 and len(minions) > 1:
            rng.shuffle(minions)
            mutations.append(f"{side}_shuffle")
        # 4) 战团大小：从同卡池已有状态里取一条模板替换一条（保持观测值）
        if rng.random() < 0.15 and minions:
            donors = [s for s in pool.states if s.get(side, {}).get("minions")]
            if donors:
                donor = rng.choice(donors)[side]["minions"]
                if donor:
                    minions[rng.randrange(len(minions))] = _copy_state(donor)[
                        rng.randrange(len(donor))]
                    mutations.append(f"{side}_size_swap")
    return out, mutations


# ══════════════════════════════════════════════════════════════════════
# oracle（第三方参照；当前 BB 接口未就绪 → stub）
# ══════════════════════════════════════════════════════════════════════


_KEYWORD_SCORE = {
    "divine_shield": 1.5, "reborn": 1.3, "taunt": 0.8,
    "windfury": 1.2, "mega_windfury": 1.8, "poisonous": 1.6,
    "venomous": 1.6, "cleave": 1.3, "stealth": 0.7, "elusive": 0.8,
}


def _team_score(minions: Sequence[Dict[str, Any]]) -> float:
    score = 0.0
    for minion in minions:
        atk = float(minion.get("atk") or 0)
        health = float(minion.get("health") or 0)
        score += atk * max(1.0, health) ** 0.5
        for keyword in minion.get("keywords") or []:
            score += _KEYWORD_SCORE.get(str(keyword).lower(), 0.2)
    return score


class Oracle:
    name = "base"

    def rates(self, state: Dict[str, Any], sims: int,
              rng: random.Random) -> Dict[str, float]:
        raise NotImplementedError


class StubOracle(Oracle):
    """**非官方、非 BB** 的独立启发式，仅用于验证管线闭环。"""

    name = "stub"

    def rates(self, state: Dict[str, Any], sims: int,
              rng: random.Random) -> Dict[str, float]:
        p = _team_score(state["player"]["minions"])
        o = _team_score(state["opponent"]["minions"])
        margin = math.log((p + 1.0) / (o + 1.0))
        win = 1.0 / (1.0 + math.exp(-margin * 0.9))
        tie = 0.08 * math.exp(-abs(margin))
        loss = max(0.0, 1.0 - win - tie)
        total = win + tie + loss
        # 小样本抖动（模拟第三方仿真的估算噪声）
        noise = 0.03 / max(1.0, math.sqrt(sims))
        win = max(0.0, win / total + rng.uniform(-noise, noise))
        tie = max(0.0, tie / total + rng.uniform(-noise / 2, noise / 2))
        loss = max(0.0, 1.0 - win - tie)
        total = win + tie + loss
        return {"win": win / total, "tie": tie / total,
                "loss": loss / total}


class BobsBuddyOracle(Oracle):
    """真实 BobsBuddy 离线 oracle（pythonnet + BobsBuddy.dll，非官方参照）。

    通过 ``tools/bb_oracle/bb_oracle.py::run_oracle`` 在进程内调用（DLL 只
    加载一次）；返回 ``win/tie/loss``、``av_damage``、``ignored_fields``。
    """

    name = "bobsbuddy"

    def __init__(self, *, dll_dir: Optional[str] = None,
                 threads: int = 4, time_limit_ms: int = 20000) -> None:
        self.dll_dir = dll_dir
        self.threads = int(threads)
        self.time_limit_ms = int(time_limit_ms)
        self._run_oracle = None

    def _oracle(self):
        if self._run_oracle is None:
            try:
                from tools.bb_oracle.bb_oracle import run_oracle
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"BobsBuddy oracle 不可用（pythonnet/路径）：{exc}")
            self._run_oracle = run_oracle
        return self._run_oracle

    def rates(self, state: Dict[str, Any], sims: int,
              rng: random.Random) -> Dict[str, Any]:
        payload = state.get("_bb_payload") or _state_to_bb_payload(state)
        payload = dict(payload)
        payload["iterations"] = int(sims)
        payload["threads"] = self.threads
        payload["time_limit_ms"] = self.time_limit_ms
        result = self._oracle()(payload, dll_dir=self.dll_dir,
                                iterations=int(sims),
                                threads=self.threads,
                                time_limit_ms=self.time_limit_ms)
        return result


# ══════════════════════════════════════════════════════════════════════
# 引擎复现
# ══════════════════════════════════════════════════════════════════════


def _build_official_trace(state: Dict[str, Any], index: int
                          ) -> T.OfficialCombatTrace:
    def band(side: str) -> T.Warband:
        data = state[side]
        minions = []
        for slot, minion in enumerate(data["minions"]):
            minions.append(T.TraceMinion(
                slot=slot,
                name=str(minion.get("name") or ""),
                card_id=minion.get("card_id"),
                atk=minion.get("atk"),
                health=minion.get("health"),
                golden=bool(minion.get("golden")),
                keywords=[str(k) for k in (minion.get("keywords") or [])],
                tags={str(k): str(v) for k, v in
                      (minion.get("tags") or {}).items()},
            ))
        deity = data.get("deity")
        if not deity and data.get("deity_card_id"):
            # bridge-analyst 的 state_corpus 六字段是平铺在 band 上的
            deity = {k: data.get(k) for k in (
                "deity_card_id", "deity_atk", "deity_health",
                "deity_progress", "deity_awakened",
                "deity_sigil_card_id")}
        return T.Warband(side=side, hero_power_id=data.get("hero_power_id"),
                         minions=minions,
                         deity=deity)
    return T.OfficialCombatTrace(
        trace_id=f"fuzz_{hashlib.sha256(str(index).encode()).hexdigest()[:16]}",
        source=T.SOURCE_POWERLOG,
        episode_id="bulk_fuzz",
        player=band("player"),
        opponent=band("opponent"),
        turn=state.get("turn"),
        official_result=None,
        boundary_mode="bulk_fuzz",
    )


def engine_rates(state: Dict[str, Any], index: int, *, seeds: int,
                 db: Any, resolver: Any, hero_index: Any
                 ) -> Dict[str, Any]:
    from tools.diff_replay_combat import simulate_trace
    trace = _build_official_trace(state, index)
    sim = simulate_trace(trace, db, resolver, hero_index,
                         seeds=seeds, capture_events=False)
    return {
        "rates": sim.rates(),
        "outcomes": dict(Counter(sim.outcomes)),
        "n": len(sim.outcomes),
        "damage_dealt_mean": (sum(sim.damage_dealt) / len(sim.damage_dealt)
                              if sim.damage_dealt else None),
        "errors": sim.errors[:3],
        "context_gaps": list(dict.fromkeys(sim.context_gaps))[:8],
    }


# ══════════════════════════════════════════════════════════════════════
# 统计 / 输出
# ══════════════════════════════════════════════════════════════════════


def _tvd(p: Dict[str, float], q: Dict[str, float]) -> float:
    keys = ("win", "tie", "loss")
    return 0.5 * sum(abs(float(p.get(k, 0)) - float(q.get(k, 0)))
                     for k in keys)


def _chi2(observed: Sequence[int], expected_probs: Sequence[float]) -> float:
    total = sum(observed)
    if total <= 0:
        return 0.0
    value = 0.0
    for count, prob in zip(observed, expected_probs):
        expected = total * max(1e-6, prob)
        if expected > 0:
            value += (count - expected) ** 2 / expected
    return value


def _state_to_bb_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    """把 runner state（trace/state_corpus 转换后）转成 bb_oracle schema。"""
    def side(data: Dict[str, Any]) -> Dict[str, Any]:
        minions = []
        for minion in data.get("minions") or []:
            script: Dict[str, int] = {}
            tags = minion.get("tags") or {}
            for key, value in tags.items():
                text = str(key)
                if text.startswith("ScriptDataNum"):
                    num = text.replace("ScriptDataNum", "") or "1"
                    try:
                        script[str(int(num))] = int(value)
                    except (TypeError, ValueError):
                        continue
            minions.append({
                "card_id": minion.get("card_id"),
                "atk": minion.get("atk"),
                "health": minion.get("health"),
                "golden": bool(minion.get("golden")),
                "keywords": [str(k) for k in (minion.get("keywords") or [])],
                "tier": minion.get("tier"),
                "script_data": script or None,
            })
        powers = []
        if data.get("hero_power_id"):
            power: Dict[str, Any] = {"card_id": data["hero_power_id"]}
            if data.get("hero_power_data") is not None:
                power["data"] = int(data["hero_power_data"])
            powers.append(power)
        deity = data.get("deity") or {}
        sigil_card = deity.get("deity_sigil_card_id")
        deity_card = deity.get("deity_card_id")
        if deity_card:
            existing = {str(m.get("card_id")) for m in minions}
            if str(deity_card) not in existing:
                minions.append({
                    "card_id": str(deity_card),
                    "atk": deity.get("deity_atk"),
                    "health": deity.get("deity_health"),
                    "golden": False,
                    "keywords": [],
                    "tier": data.get("tier"),
                    "is_deity": True,
                })
        payload = {
            "health": data.get("health"),
            "tier": data.get("tier"),
            "minions": minions,
            "hero_powers": powers,
        }
        if sigil_card:
            payload["friendly_deity_sigil"] = str(sigil_card)
        return payload
    return {"turn": state.get("turn"),
            "player": side(state["player"]),
            "opponent": side(state["opponent"])}


DEITY_FIELDS = (
    "deity_card_id", "deity_atk", "deity_health", "deity_progress",
    "deity_awakened", "deity_sigil_card_id",
)

#: HDT trace ScriptDataNum 槽位 → Power.log raw 槽位（Lead/engine-analyst
#: 2026-10-19 警告：Wrath 2↔1、Devout 2↔1、Soul 2↔3；仅对来自 HDT 的
#: state 做映射，Power.log raw 状态原样使用）。
HDT_SLOT_TO_RAW = {
    "BGS_004": {"1": "2"},    # Wrath Weaver
    "BG33_155": {"1": "2"},   # Devout Hellcaller
    "BG26_174": {"2": "3"},   # Soul Rewinder
}

#: state_corpus 中无法被当前 oracle 完整表达的 context 标记
_UNSUPPORTED_REASONS = (
    "anomaly", "trinket", "quest", "enchantment", "secret", "hand",
    "available_races",
)


def _corpus_unsupported_reasons(row: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    # hidden_context_reasons 是 schema 级通用声明（几乎每条都有 anomaly/
    # trinkets/quests），不代表该样本真的带这些状态；只按实际内容判定。
    if row.get("hidden_state"):
        reasons.append("hidden_state")
    for side in ("player", "opponent"):
        band = row.get(side) or {}
        for item in band.get("unsupported") or []:
            reasons.append(f"{side}.unsupported:{item}")
        if band.get("hand"):
            reasons.append(f"{side}.hand_not_modeled")
        if band.get("deity_hidden"):
            reasons.append(f"{side}.deity_hidden")
        deity = band.get("deity") or {}
        if deity.get("deity_hidden"):
            reasons.append(f"{side}.deity_hidden")
        for minion in band.get("minions") or []:
            if minion.get("enchantment_derived"):
                reasons.append(
                    f"{side}.enchantment_derived:{minion.get('card_id')}")
    return sorted(set(reasons))


def _state_from_corpus(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """bg_state_pair.v1 → 内部 state（保留真实属性/keywords/script data）。

    注意：HDT trace 的 ScriptDataNum 槽位与 Power.log raw 槽位不一致；
    这里只对 HDT 来源做已知三卡显式映射（HDT_SLOT_TO_RAW），Power.log
    raw 状态原样使用。未知 HDT 槽位不臆测，记录 slot source 供审计。
    """
    source = str(row.get("source") or "")

    def side(data: Dict[str, Any]) -> Dict[str, Any]:
        minions = []
        for minion in data.get("minions") or []:
            script: Dict[str, int] = {}
            for i in range(1, 5):
                value = minion.get(f"script_data_num_{i}")
                if value is not None:
                    script[str(i)] = int(value)
            if (source.startswith("hdt")
                    and minion.get("script_data_source") == "trace_tags"):
                mapped = HDT_SLOT_TO_RAW.get(str(minion.get("card_id")), {})
                script = {mapped.get(k, k): v for k, v in script.items()}
            minions.append({
                "card_id": minion.get("card_id"),
                "name": minion.get("name") or "",
                "atk": minion.get("atk"),
                "health": minion.get("health"),
                "golden": bool(minion.get("golden")),
                "keywords": list(minion.get("keywords") or []),
                "tags": script,
                "tier": minion.get("tier"),
            })
        deity = {}
        for key in DEITY_FIELDS:
            if key in data:
                deity[key] = data.get(key)
        if data.get("deity_hidden"):
            deity["deity_hidden"] = True
        return {
            "hero_power_id": data.get("hero_power_id"),
            "hero_power_data": data.get("hero_power_data"),
            "health": data.get("health"),
            "armor": data.get("armor"),
            "tier": data.get("tier"),
            "minions": minions,
            "deity": deity or None,
        }
    if not (row.get("player") and row.get("opponent")):
        return None
    state = {
        "source": row.get("source") or "state_corpus",
        "source_trace": row.get("trace_id") or row.get("state_id"),
        "state_id": row.get("state_id"),
        "turn": row.get("turn"),
        "official_result": row.get("official_result"),
        "player": side(row["player"]),
        "opponent": side(row["opponent"]),
        "expressible": not _corpus_unsupported_reasons(row),
        "unsupported_reasons": _corpus_unsupported_reasons(row),
    }
    state["_bb_payload"] = _state_to_bb_payload(state)
    return state


def load_state_corpus(path: Path) -> List[Dict[str, Any]]:
    states: List[Dict[str, Any]] = []
    if not path.exists():
        return states
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            state = _state_from_corpus(row)
            if state is not None:
                states.append(state)
    return states


def _state_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    def side(data: Dict[str, Any]) -> Dict[str, Any]:
        minions = data.get("minions") or []
        return {
            "hero_power_id": data.get("hero_power_id"),
            "size": len(minions),
            "cards": [m.get("card_id") or m.get("name") for m in minions],
            "atk_health": [[m.get("atk"), m.get("health")] for m in minions],
            "keywords": [sorted(m.get("keywords") or []) for m in minions],
        }
    return {"player": side(state["player"]),
            "opponent": side(state["opponent"])}


def _load_engine():
    from hsrl2.db import CardDB
    from hsbg.paths import DATA_DIR
    from tools.diff_replay_combat import CardResolver, HeroIndex
    db = CardDB.load(DATA_DIR)
    return db, CardResolver(db), HeroIndex(db)


#: Activate cost 无权威 tag 的卡（F-16..F-19 轮 DEFERRED；不猜 cost）
ACTIVATE_COST_CARDS = {
    "BG28_582", "BG28_582_G", "BG36_099", "BG36_099_G",
    "BG36_300", "BG36_300_G", "BG36_311", "BG36_311_G",
    "BG36_312", "BG36_312_G",
}


def _known_context_gap(state: Dict[str, Any]) -> Optional[str]:
    """已知 context gap（不进 agree 分母）。

    F-16 后 C'Thun awaken split 已按真实 Power.log 证据实现（floor/N），
    **不再**是 known gap；当前无 known gap（保留接口给后续证据缺口）。
    """
    return None


def _has_activate_cost_gap(state: Dict[str, Any]) -> bool:
    """状态含 Activate cost 无权威 tag 的卡：单列报告，不要求收敛。"""
    for side in ("player", "opponent"):
        for card in (state.get(side) or {}).get("minions") or []:
            if str(card.get("card_id")) in ACTIVATE_COST_CARDS:
                return True
    return False


def _rate_stats(values: Sequence[float]) -> Dict[str, Any]:
    if not values:
        return {}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "mean": round(sum(ordered) / len(ordered), 4),
        "p50": round(ordered[len(ordered) // 2], 4),
        "p90": round(ordered[min(len(ordered) - 1,
                                 int(0.9 * (len(ordered) - 1)))], 4),
        "max": round(ordered[-1], 4),
    }


def _stratify(details: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """按卡/关键词/stat 分位分层（仅 supported，mean/max TVD）。"""
    cards: Dict[str, List[float]] = defaultdict(list)
    keywords: Dict[str, List[float]] = defaultdict(list)
    stat_buckets: Dict[str, List[float]] = defaultdict(list)
    supported = [d for d in details if d.get("supported")]
    for detail in supported:
        tvd = detail["tvd"]
        healths = []
        for side in ("player", "opponent"):
            for idx, card in enumerate(detail["state"][side]["cards"]):
                cards[card or "?"].append(tvd)
                combo = detail["state"][side]["keywords"][idx]
                for keyword in combo or []:
                    keywords[keyword].append(tvd)
            healths.extend(int(h or 0) for _, h in
                           detail["state"][side]["atk_health"])
        if healths:
            q = sorted(healths)[len(healths) // 2]
            stat_buckets[f"health_p50_{q}"].append(tvd)
    def top(mapping: Dict[str, List[float]], limit: int = 10) -> List[dict]:
        rows = [{"key": k, "n": len(v),
                 "mean_tvd": round(sum(v) / len(v), 4),
                 "max_tvd": round(max(v), 4)}
                for k, v in mapping.items() if len(v) >= 2]
        return sorted(rows, key=lambda r: (-r["mean_tvd"], -r["n"]))[:limit]
    return {"by_card": top(cards), "by_keyword": top(keywords),
            "by_stat_bucket": top(stat_buckets)}


def run(args: argparse.Namespace) -> Dict[str, Any]:
    started = time.time()
    rng = random.Random(args.seed)
    states: List[Dict[str, Any]] = []
    pool_summary: Dict[str, Any] = {}
    if getattr(args, "states_file", None):
        all_states = load_state_corpus(Path(args.states_file))
        if getattr(args, "only_trace_ids", None):
            wanted = {x.strip() for x in str(args.only_trace_ids).split(",")
                      if x.strip()}
            all_states = [st for st in all_states
                          if str(st.get("source_trace")) in wanted]
        expressible = [st for st in all_states if st.get("expressible", True)]
        # 优先可完整表达样本；unsupported 比例按**全语料**统计，单列不进 TVD
        states = expressible or all_states
        pool_summary = {"source": str(args.states_file),
                        "total": len(all_states),
                        "expressible": len(expressible),
                        "unsupported_ratio_all": round(
                            (len(all_states) - len(expressible))
                            / max(1, len(all_states)), 4)}
        if not states:
            raise SystemExit(f"state 文件为空/不可读：{args.states_file}")
        target = int(args.states)
        if len(states) < target:
            # 可完整表达样本不足 → 在观测分布内突变补足（不臆造）
            pool = StatePool()
            pool.states = [_copy_state(st) for st in expressible]
            for st in pool.states:
                for side in ("player", "opponent"):
                    for minion in st[side]["minions"]:
                        card = (minion.get("card_id")
                                or minion.get("name") or "?")
                        pool.card_stats[card].append(
                            (int(minion.get("atk") or 0),
                             int(minion.get("health") or 0)))
                        pool.card_keyword_sets[card][tuple(sorted(
                            minion.get("keywords") or []))] += 1
            extra: List[Dict[str, Any]] = []
            while len(states) + len(extra) < target and expressible:
                base = rng.choice(expressible)
                mutated, muts = mutate_state(pool, base, rng)
                mutated["source"] = base.get("source")
                mutated["source_trace"] = base.get("source_trace")
                mutated["state_id"] = f"mut_{len(extra)}"
                mutated["turn"] = base.get("turn")
                mutated["mutations"] = muts
                mutated["expressible"] = True
                mutated["unsupported_reasons"] = []
                mutated["_bb_payload"] = _state_to_bb_payload(mutated)
                extra.append(mutated)
            states = states + extra
            pool_summary["mutated_to_target"] = len(extra)
    else:
        pool = StatePool()
        pool.add_trace_dirs([Path(p) for p in args.trace_dirs])
        pool.add_bg_last_games(Path(args.last_games))
        if not pool.states:
            raise SystemExit("没有可采样的真实状态（检查 --trace-dirs）")
        pool_summary = {"pools": dict(pool.sources),
                        "base_states": len(pool.states)}
        # 先取样，后续统一走 state 流程
        for _ in range(int(args.states)):
            base = rng.choice(pool.states)
            state, mutations = mutate_state(pool, base, rng)
            state["mutations"] = mutations
            states.append(state)

    db, resolver, hero_index = _load_engine()
    if args.oracle == "bobsbuddy":
        oracle: Oracle = BobsBuddyOracle(
            dll_dir=getattr(args, "dll_dir", None),
            threads=int(getattr(args, "bb_threads", 4)),
            time_limit_ms=int(getattr(args, "bb_time_limit_ms", 20000)))
    else:
        oracle = StubOracle()

    selected = states[: int(args.states)] if not getattr(
        args, "states_file", None) else states[: int(args.states)]
    details: List[Dict[str, Any]] = []
    unsupported_reasons = Counter()
    for index, state in enumerate(selected):
        engine = engine_rates(state, index, seeds=int(args.engine_seeds),
                              db=db, resolver=resolver,
                              hero_index=hero_index)
        oracle_rates: Dict[str, float] = {}
        oracle_extra: Dict[str, Any] = {}
        supported = bool(state.get("expressible", True))
        reasons = list(state.get("unsupported_reasons") or [])
        if supported:
            if oracle.name == "bobsbuddy":
                try:
                    result = oracle.rates(state, int(args.oracle_sims), rng)
                except Exception as exc:  # noqa: BLE001
                    result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                if not result.get("ok"):
                    supported = False
                    reasons.append(f"oracle_error:{result.get('error')}")
                ignored = result.get("ignored_fields") or []
                if ignored:
                    supported = False
                    reasons.extend(f"oracle_ignored:{x}" for x in ignored)
                oracle_rates = {k: float(result.get(k) or 0.0)
                                for k in ("win", "tie", "loss")}
                oracle_extra = {
                    "av_damage": result.get("av_damage"),
                    "median_damage": result.get("median_damage"),
                    "simulation_count": result.get("simulation_count"),
                    "elapsed_s": result.get("elapsed_s"),
                    "sec_per_1000": result.get("sec_per_1000"),
                }
            else:
                oracle_rates = oracle.rates(state, int(args.oracle_sims), rng)
        observed = [engine["outcomes"].get(k, 0)
                    for k in ("win", "tie", "loss")]
        if supported:
            tvd = _tvd(engine["rates"], oracle_rates)
            chi2 = _chi2(observed, [oracle_rates.get(k, 0)
                                    for k in ("win", "tie", "loss")])
        else:
            tvd = None
            chi2 = None
            for reason in reasons:
                unsupported_reasons[reason] += 1
        known_gap = (_known_context_gap(state)
                     if oracle.name == "bobsbuddy" else None)
        detail = {
            "state_id": index,
            "source": state.get("source"),
            "source_trace": state.get("source_trace"),
            "turn": state.get("turn"),
            "mutations": state.get("mutations") or [],
            "oracle": oracle.name,
            "oracle_is_official": False,
            "engine_seeds": int(args.engine_seeds),
            "oracle_sims": int(args.oracle_sims),
            "supported": supported,
            "evaluated": bool(supported and not known_gap),
            "known_context_gap": known_gap,
            "activate_cost_gap": _has_activate_cost_gap(state),
            "unsupported_reasons": reasons,
            "engine_rates": engine["rates"],
            "engine_damage_dealt_mean": engine.get("damage_dealt_mean"),
            "oracle_rates": oracle_rates,
            "oracle_extra": oracle_extra,
            "engine_outcomes": engine["outcomes"],
            "engine_errors": engine["errors"],
            "context_gaps": engine["context_gaps"],
            "tvd": round(tvd, 4) if tvd is not None else None,
            "chi2": round(chi2, 3) if chi2 is not None else None,
            "agree": bool(tvd is not None and tvd <= float(args.tolerance)),
            "state": _state_summary(state),
        }
        if (supported and oracle.name == "bobsbuddy"
                and oracle_extra.get("av_damage") is not None
                and engine.get("damage_dealt_mean") is not None):
            detail["damage_diff"] = round(
                float(engine["damage_dealt_mean"])
                - float(oracle_extra["av_damage"]), 3)
        details.append(detail)

    supported_details = [d for d in details if d["supported"]]
    evaluated_details = [d for d in details if d.get("evaluated")]
    known_gap_details = [d for d in details
                         if d.get("known_context_gap")]
    activate_gap_details = [d for d in details
                            if d.get("activate_cost_gap")]
    tvds = [d["tvd"] for d in evaluated_details if d["tvd"] is not None]
    agree = sum(1 for d in evaluated_details if d["agree"])
    damage_diffs = [d["damage_diff"] for d in evaluated_details
                    if d.get("damage_diff") is not None]
    cards = Counter()
    keyword_combos = Counter()
    stat_values: List[int] = []
    context_gap_states = 0
    for detail in details:
        if detail["context_gaps"]:
            context_gap_states += 1
        for side in ("player", "opponent"):
            for idx, card in enumerate(detail["state"][side]["cards"]):
                cards[card or "?"] += 1
                keyword_combos[tuple(detail["state"][side]["keywords"][idx])] += 1
            for atk, health in detail["state"][side]["atk_health"]:
                stat_values.append(int(atk or 0))
                stat_values.append(int(health or 0))
    summary = {
        "schema": "diff_bulk_fuzz.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "settings": {
            "states": len(details),
            "supported": len(supported_details),
            "evaluated": len(evaluated_details),
            "known_context_gap": len(known_gap_details),
            "activate_cost_gap": len(activate_gap_details),
            "unsupported": len(details) - len(supported_details),
            "engine_seeds": int(args.engine_seeds),
            "oracle_sims": int(args.oracle_sims),
            "oracle": oracle.name,
            "oracle_is_official": False,
            "tolerance_tvd": float(args.tolerance),
            "seed": int(args.seed),
            "states_file": getattr(args, "states_file", None),
            "dll_dir": getattr(args, "dll_dir", None),
            "bb_threads": getattr(args, "bb_threads", None),
        },
        "sampling": {
            **pool_summary,
            "mutation_kinds": dict(Counter(
                m for d in details for m in d["mutations"])),
        },
        "coverage": {
            "corpus_unsupported_ratio": pool_summary.get(
                "unsupported_ratio_all"),
            "corpus_total": pool_summary.get("total"),
            "unique_cards": len(cards),
            "top_cards": dict(cards.most_common(20)),
            "keyword_combos": len(keyword_combos),
            "stat_min": min(stat_values) if stat_values else None,
            "stat_p50": sorted(stat_values)[len(stat_values) // 2]
            if stat_values else None,
            "stat_max": max(stat_values) if stat_values else None,
            "states_with_engine_context_gaps": context_gap_states,
            "unsupported_ratio": (
                (len(details) - len(supported_details)) / max(1, len(details))
                if not pool_summary.get("unsupported_ratio_all") is not None
                else pool_summary["unsupported_ratio_all"]),
            "unsupported_reasons": dict(unsupported_reasons.most_common(20)),
            "note": "采样覆盖，非穷举；突变限观测分布内。",
        },
        "agreement": {
            "agree": agree,
            "total": len(evaluated_details),
            "agree_rate": round(agree / max(1, len(evaluated_details)), 4),
            "known_context_gap": len(known_gap_details),
            "known_context_gap_details": [
                {"state_id": d["state_id"], "source": d.get("source"),
                 "source_trace": d.get("source_trace"),
                 "turn": d.get("turn"), "gap": d["known_context_gap"],
                 "tvd_reference": d["tvd"],
                 "engine_rates": d["engine_rates"],
                 "oracle_rates": d["oracle_rates"]}
                for d in known_gap_details],
            "tvd": _rate_stats(tvds),
            "damage_diff": (_rate_stats([abs(v) for v in damage_diffs])
                            if damage_diffs else {}),
            "tolerance_tvd": float(args.tolerance),
        },
        "activate_cost_gap_details": [
            {"state_id": d["state_id"], "turn": d.get("turn"),
             "tvd_reference": d["tvd"],
             "cards": [c for side in ("player", "opponent")
                       for c in (d["state"][side]["cards"] or [])
                       if str(c) in ACTIVATE_COST_CARDS],
             "engine_rates": d["engine_rates"],
             "oracle_rates": d["oracle_rates"]}
            for d in activate_gap_details],
        "stratification": _stratify(details),
        "top_divergences": sorted(
            [d for d in evaluated_details if d["tvd"] is not None],
            key=lambda d: -d["tvd"])[:10],
        "caveat": (
            "BobsBuddy 为第三方参照，非官方实现；客户端无官方战斗裁决器，"
            "无法做实现级全量等价。采样覆盖，非穷举；unsupported 样本已单列，"
            "不混入 TVD。"),
        "elapsed_seconds": round(time.time() - started, 2),
    }
    return {"summary": summary, "details": details}


def render_markdown(result: Dict[str, Any]) -> str:
    summary = result["summary"]
    settings = summary["settings"]
    agreement = summary["agreement"]
    coverage = summary["coverage"]
    lines = ["# 离线批量差分：真实战团 → 引擎 vs BobsBuddy oracle", ""]
    lines.append(f"> 生成 {summary['generated_at']}；**{settings['states']} 状态** × "
                 f"引擎 {settings['engine_seeds']} seeds × oracle "
                 f"{settings['oracle_sims']} sims；oracle=`{settings['oracle']}`"
                 f"（**第三方参照，非官方**）。")
    lines.append("")
    lines.append("## 1. 一致性（仅可完整表达样本）")
    corpus_ratio = coverage.get("corpus_unsupported_ratio")
    lines.append(f"- 本批 selected **{settings.get('evaluated', settings['supported'])}"
                 f"/{settings['states']}** evaluated（supported {settings['supported']}；"
                 f"known gap {settings.get('known_context_gap', 0)}；"
                 f"unsupported {settings['unsupported']}，均单列不进 TVD）")
    if corpus_ratio is not None:
        lines.append(f"- 全语料 unsupported 比例（含手牌/enchantment 等）："
                     f"**{corpus_ratio:.1%}**"
                     f"（{coverage.get('corpus_total')} states；本批只取可完整"
                     f"表达样本，不足时在观测分布内突变补足）")
    tvd = agreement.get("tvd") or {}
    if tvd:
        lines.append(f"- 一致（TVD ≤ {agreement['tolerance_tvd']}）："
                     f"**{agreement['agree']}/{agreement['total']} = "
                     f"{agreement['agree_rate']:.1%}**；TVD mean "
                     f"{tvd.get('mean')} / p50 {tvd.get('p50')} / "
                     f"p90 {tvd.get('p90')} / max {tvd.get('max')}")
    damage = agreement.get("damage_diff") or {}
    if damage:
        lines.append(f"- |平均伤害差|：mean {damage.get('mean')} / "
                     f"p50 {damage.get('p50')} / p90 {damage.get('p90')}")
    lines.append("")
    activate = summary.get("activate_cost_gap_details") or []
    if activate:
        lines.append("")
        lines.append(f"### Activate cost 缺口单列（{len(activate)} 状态；不要求收敛）")
        lines.append("")
        lines.append("| state | turn | cards | TVD 参考 | engine(w/t/l) | oracle(w/t/l) |")
        lines.append("|---|---|---|---|---|---|")
        for row in activate[:20]:
            e, o = row["engine_rates"], row["oracle_rates"]
            e_txt = "%.2f/%.2f/%.2f" % (e.get("win", 0), e.get("tie", 0),
                                        e.get("loss", 0))
            o_txt = "%.2f/%.2f/%.2f" % (o.get("win", 0), o.get("tie", 0),
                                        o.get("loss", 0))
            lines.append(
                "| %s | %s | %s | %s | %s | %s |"
                % (row["state_id"], row.get("turn"),
                   ", ".join(row["cards"]), row.get("tvd_reference"),
                   e_txt, o_txt))
    lines.append("")
    lines.append("## 2. 覆盖（采样覆盖，非穷举）")
    lines.append(f"- 唯一卡 {coverage['unique_cards']}；关键词组合 "
                 f"{coverage['keyword_combos']}；stat 范围 "
                 f"[{coverage['stat_min']}, {coverage['stat_max']}]（中位 "
                 f"{coverage['stat_p50']}）；引擎 context gap 状态 "
                 f"{coverage['states_with_engine_context_gaps']}")
    if coverage.get("unsupported_reasons"):
        lines.append("")
        lines.append("unsupported 原因 TOP：" + "；".join(
            f"`{k}`×{v}" for k, v in
            list(coverage["unsupported_reasons"].items())[:10]))
    known = agreement.get("known_context_gap_details") or []
    if known:
        lines.append("")
        lines.append(f"### 已知 context gap（不计 agree 分母）：{len(known)} 条")
        lines.append("")
        lines.append("| state | turn | gap | TVD 参考 | engine(w/t/l) | oracle(w/t/l) |")
        lines.append("|---|---|---|---|---|---|")
        for row in known[:20]:
            e, o = row["engine_rates"], row["oracle_rates"]
            lines.append(
                f"| {row['state_id']} | {row.get('turn')} | "
                f"`{row['gap']}` | {row.get('tvd_reference')} | "
                f"{e.get('win', 0):.2f}/{e.get('tie', 0):.2f}/{e.get('loss', 0):.2f} | "
                f"{o.get('win', 0):.2f}/{o.get('tie', 0):.2f}/{o.get('loss', 0):.2f} |")
    lines.append("")
    lines.append("## 3. 分层 TOP（mean TVD，evaluated）")
    strata = summary.get("stratification") or {}
    for name, rows in (("按卡", strata.get("by_card")),
                       ("按关键词", strata.get("by_keyword"))):
        if not rows:
            continue
        lines.append("")
        lines.append(f"**{name}**")
        lines.append("")
        lines.append("| key | n | mean TVD | max TVD |")
        lines.append("|---|---|---|---|")
        for row in rows[:10]:
            lines.append(f"| `{row['key']}` | {row['n']} | "
                         f"{row['mean_tvd']:.3f} | {row['max_tvd']:.3f} |")
    lines.append("")
    lines.append("## 4. TOP 分歧状态")
    lines.append("")
    lines.append("| state | turn | TVD | engine(w/t/l) | oracle(w/t/l) |")
    lines.append("|---|---|---|---|---|")
    for detail in summary.get("top_divergences") or []:
        e, o = detail["engine_rates"], detail["oracle_rates"]
        lines.append(
            f"| {detail['state_id']} | {detail.get('turn')} | "
            f"{detail['tvd']:.3f} | "
            f"{e.get('win', 0):.2f}/{e.get('tie', 0):.2f}/{e.get('loss', 0):.2f} | "
            f"{o.get('win', 0):.2f}/{o.get('tie', 0):.2f}/{o.get('loss', 0):.2f} |")
    lines.append("")
    lines.append("## 5. 口径与限制")
    lines.append(f"- {summary['caveat']}")
    lines.append("- TVD 仅统计 supported 样本；unsupported 单列（ignored_fields/"
                 "enchantments/trinkets/quests/anomaly 等）不混入。")
    lines.append("- 采样来自真实语料/state_corpus，不含未观测状态的臆造；"
                 "不代表官方实现级等价。")
    lines.append("")
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="离线批量差分 runner（真实状态采样 → 引擎 vs oracle）")
    parser.add_argument("--states", type=int, default=100)
    parser.add_argument("--engine-seeds", type=int, default=64)
    parser.add_argument("--oracle-sims", type=int, default=100)
    parser.add_argument("--oracle", choices=("stub", "bobsbuddy"),
                        default="stub")
    parser.add_argument("--states-file", default=None,
                        help="state_corpus JSONL（优先于 --trace-dirs 采样）")
    parser.add_argument("--only-trace-ids", default=None,
                        help="逗号分隔 trace_id（仅重跑指定状态，调试用）")
    parser.add_argument("--dll-dir", default=None,
                        help="BobsBuddy.dll 目录（默认 app-1.59.3）")
    parser.add_argument("--bb-threads", type=int, default=4)
    parser.add_argument("--bb-time-limit-ms", type=int, default=20000)
    parser.add_argument("--tolerance", type=float, default=0.15,
                        help="TVD 容忍带（默认 0.15）")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--trace-dirs", nargs="*",
                        default=[str(p) for p in DEFAULT_TRACE_DIRS])
    parser.add_argument("--last-games", default=str(DEFAULT_LAST_GAMES))
    parser.add_argument("--out-jsonl", default=str(OUT_JSONL))
    parser.add_argument("--out-md", default=str(OUT_MD))
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = run(args)
    out_jsonl = Path(args.out_jsonl)
    if args.oracle == "bobsbuddy" and str(out_jsonl) == str(OUT_JSONL):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out_jsonl = ROOT / "runs" / f"diff_bulk_bb_{stamp}.jsonl"
        if str(args.out_md) == str(OUT_MD):
            args.out_md = str(ROOT / "runs" / f"diff_bulk_bb_{stamp}.md")
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8") as handle:
        for detail in result["details"]:
            handle.write(json.dumps(detail, ensure_ascii=False) + "\n")
    out_md = Path(args.out_md)
    out_md.write_text(render_markdown(result), encoding="utf-8")
    summary = result["summary"]
    tvd = summary["agreement"].get("tvd") or {}
    print(f"[bulk-fuzz] states={summary['settings']['states']} "
          f"supported={summary['settings']['supported']} "
          f"oracle={summary['settings']['oracle']} "
          f"agree={summary['agreement']['agree']}/"
          f"{summary['agreement']['total']} "
          f"tvd_mean={tvd.get('mean')} "
          f"-> {out_jsonl} / {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
