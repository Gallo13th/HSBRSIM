"""构建不确定卡审计候选清单：679 差分 + 300 状态 BB + 26 场真实 Power.log。

输出 `reversed/rea/audit_candidates_diff.md`（evidence-first，不改引擎）。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hsrl2.db import CardDB  # noqa: E402
from hsbg.bridge import trace as T  # noqa: E402

REPORT_679 = ROOT / "runs" / "diff_report_after_f19b.json"
BB_JSONL = ROOT / "runs" / "diff_bulk_bb_after_f15_gapaware.jsonl"
POWER_REPORTS = [
    ROOT / "runs" / "diff_report_powerlog.json",
    ROOT / "runs" / "diff_powerlog2.json",
    ROOT / "runs" / "diff_powerlog3_after_f14.json",
]
POWER_DIRS = [
    ROOT / "runs" / "official_traces_powerlog",
    ROOT / "runs" / "official_traces_powerlog2",
    ROOT / "runs" / "official_traces_powerlog3",
]
OUT = ROOT / "reversed" / "rea" / "audit_candidates_diff.md"

KNOWN_TOP = ["BG34_694", "BG35_432", "BG32_835", "BG36_300", "BG36_318",
             "BG36_523", "BG36_320_G", "BG36_106_G", "BG31_171",
             "BG28_583", "BG34_320", "BGS_004", "BG31_035", "BG26_174",
             "BG35_701", "BG32_822", "BG33_155"]
C_CLASS = ["BGS_004", "BG31_035", "BG26_174", "BG35_701", "BG32_822",
           "BG33_155"]

db = CardDB.load(ROOT / "data")


def name_of(card_id: str) -> str:
    d = db.get(card_id)
    return d.name if d is not None else ""


def text_of(card_id: str) -> str:
    d = db.get(card_id)
    return (getattr(d, "text", "") or "").replace("\n", " ")[:160]


cards: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
    "categories": set(),
    "div679": [],
    "missing_script": 0,
    "dynamic": 0,
    "adapter_skip": 0,
    "bb": [],
    "bb_known_gap": 0,
    "real": [],
    "real_event": [],
})


def add(card_id: Optional[str], category: Optional[str] = None) -> Dict[str, Any]:
    card = card_id or "?"
    entry = cards[card]
    if category:
        entry["categories"].add(category)
    return entry


# ── 679 差分 ─────────────────────────────────────────────────────────
report = json.loads(REPORT_679.read_text(encoding="utf-8"))
suspect_map = {s["card"]: s for s in report.get("suspect_cards") or []}
import re

for rec in report["records"]:
    trace = rec["trace"]
    gaps = rec.get("simulation", {}).get("context_gaps") or []
    # HDT 679 trace 无 card_id；从 context_gaps 的 card 前缀映射
    card_ids: Set[str] = set()
    for gap in gaps:
        m = re.match(r"(?:no_script|dynamic_script_data|deathrattle_annotation|"
                     r"hero_power_state:[^:]+):([A-Za-z0-9_]+)", gap)
        if m:
            card_ids.add(m.group(1))
    attributed = rec.get("attribution", {}).get("attribution")
    status = rec.get("comparison", {}).get("status")
    injected = rec.get("simulation", {}).get("script_data_injected") or []
    for card_id in card_ids:
        if not card_id:
            continue
        entry = add(card_id)
        gap_here = [g for g in gaps if card_id in g]
        if gap_here:
            if any(g.startswith("dynamic_script_data") for g in gap_here):
                entry["dynamic"] += 1
                entry["categories"].add("动态状态")
            if any(g.startswith("no_script") for g in gap_here):
                entry["missing_script"] += 1
                entry["categories"].add("脚本缺失")
        if status == "ENGINE_DIVERGENCE":
            entry["div679"].append({
                "trace_id": trace.get("trace_id"),
                "subclass": rec["comparison"].get("subclass"),
                "attribution": attributed,
                "l1": rec["comparison"].get("evidence", {}).get("l1_distance"),
                "official": trace.get("official_result"),
            })
            if attributed == "behavior_mismatch":
                entry["categories"].add("疑似卡牌效果")
        if attributed == "missing_script" and card_id in (
                rec.get("attribution", {}).get("suspect_cards") or []):
            entry["missing_script"] += 1
            entry["categories"].add("脚本缺失")
    for item in injected:
        card_id = item.get("card_id")
        if card_id:
            entry = add(card_id)
            if item.get("adapter_skip"):
                entry["adapter_skip"] += 1
                entry["categories"].add("动态状态")

for card_id, s in suspect_map.items():
    entry = add(card_id)
    entry["missing_script"] = max(entry["missing_script"],
                                  s.get("divergent_traces", 0)
                                  if s.get("no_engine_script") else 0)
    if s.get("no_engine_script"):
        entry["categories"].add("脚本缺失")
    if s.get("behavior_mismatch_traces"):
        entry["categories"].add("疑似卡牌效果")
for card_id, s in suspect_map.items():
    if s.get("divergent_traces"):
        cards[card_id]["div679_n_override"] = s["divergent_traces"]

for row in report.get("divergences") or []:
    for card_id in row.get("suspect_cards") or []:
        entry = add(card_id, "疑似卡牌效果")
        entry["div679"].append({
            "trace_id": row.get("trace_id"),
            "subclass": row.get("subclass"),
            "attribution": row.get("attribution"),
            "l1": row.get("l1_distance"),
            "official": row.get("official_result"),
        })

# ── BB 批量（F-15 gap-aware）─────────────────────────────────────────
if BB_JSONL.exists():
    for line in BB_JSONL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        detail = json.loads(line)
        if not detail.get("evaluated"):
            # known gap 仍记录参考
            pass
        for side in ("player", "opponent"):
            for card_id in (detail.get("state", {})
                            .get(side, {}).get("cards") or []):
                entry = add(card_id)
                if detail.get("known_context_gap"):
                    entry["bb_known_gap"] += 1
                    entry["categories"].add("状态口径缺口")
                else:
                    entry["bb"].append({
                        "state_id": detail.get("state_id"),
                        "tvd": detail.get("tvd"),
                        "turn": detail.get("turn"),
                        "engine": detail.get("engine_rates"),
                        "oracle": detail.get("oracle_rates"),
                        "source_trace": detail.get("source_trace"),
                    })
                    if (detail.get("tvd") or 0) >= 0.15:
                        entry["categories"].add("疑似卡牌效果")

# ── 真实 Power.log（26 场）──────────────────────────────────────────
power_trace: Dict[str, Any] = {}
for d in POWER_DIRS:
    for p in T.iter_trace_paths(d):
        t = T.load_trace(p)
        power_trace[t.trace_id] = t
power_records: Dict[str, Any] = {}
for path in POWER_REPORTS:
    if not path.exists():
        continue
    rep = json.loads(path.read_text(encoding="utf-8"))
    for rec in rep["records"]:
        power_records[rec["trace"]["trace_id"]] = rec
for tid, t in power_trace.items():
    rec = power_records.get(tid) or {}
    status = rec.get("comparison", {}).get("status")
    for side in (t.player, t.opponent):
        for m in side.minions:
            if not m.card_id:
                continue
            entry = add(m.card_id)
            entry["real"].append({
                "trace_id": tid,
                "turn": t.turn,
                "official": t.official_result,
                "status": status,
                "subclass": rec.get("comparison", {}).get("subclass"),
            })
            if status in ("ENGINE_DIVERGENCE", "CONTEXT_GAP"):
                ev = rec.get("event_diff") or {}
                if ev.get("diverged"):
                    entry["real_event"].append({
                        "trace_id": tid,
                        "classification": ev.get("classification"),
                        "official_event": ev.get("official"),
                        "engine_event": ev.get("engine"),
                        "index": ev.get("index"),
                    })

for card_id in KNOWN_TOP + C_CLASS:
    add(card_id)
    cards[card_id]["categories"].add("已知 TOP/审计名单")
for card_id in C_CLASS:
    cards[card_id]["categories"].add("C 类证据不足")

# ── 排序/评分 ───────────────────────────────────────────────────────
rows: List[Tuple[float, str, Dict[str, Any]]] = []
for card_id, entry in cards.items():
    bb = [x["tvd"] for x in entry["bb"] if x["tvd"] is not None]
    bb_mean = sum(bb) / len(bb) if bb else 0.0
    score = (3.0 * len(entry["real_event"])
             + 1.5 * len(entry["div679"])
             + 2.0 * (1.0 if entry["missing_script"] else 0.0)
             + 2.0 * (1.0 if entry["adapter_skip"] else 0.0)
             + 1.5 * (1.0 if entry["dynamic"] else 0.0)
             + 2.0 * bb_mean
             + 0.5 * min(1.0, len(entry["real"]) / 4.0))
    entry["bb_mean"] = round(bb_mean, 4)
    entry["bb_max"] = round(max(bb), 4) if bb else None
    entry["bb_n"] = len(bb)
    entry["real_n"] = len(entry["real"])
    entry["div679_n"] = max(len(entry["div679"]),
                            int(entry.get("div679_n_override") or 0))
    rows.append((score, card_id, entry))
def _has_evidence(cid: str, e: Dict[str, Any]) -> bool:
    if cid in KNOWN_TOP or cid in C_CLASS:
        return True
    return bool(e["div679_n"] or e["missing_script"] or e["dynamic"]
                or e["adapter_skip"] or e["real_event"]
                or (e["bb_max"] is not None and e["bb_max"] >= 0.15)
                or e["bb_known_gap"])

rows = [r for r in rows if _has_evidence(r[1], r[2])]
rows.sort(key=lambda x: (-x[0], x[1]))

# ── Markdown ────────────────────────────────────────────────────────
lines: List[str] = []
lines.append("# 不确定卡牌审计候选（差分证据，第二轮）")
lines.append("")
lines.append("> 数据源：679 场 HDT BobsBuddy 差分（`runs/diff_report.json`）、"
             "F-15 gap-aware 300 状态 BB 批量（`runs/diff_bulk_bb_after_f15_gapaware.jsonl`）、"
             "26 场真实 Power.log（A/B/C 三局，`runs/official_traces_powerlog*`）。")
lines.append("> 口径：证据优先；**TVD 是采样指标、C'Thun split 是已知 gap、BB 是第三方参照**；"
             "无真实 trace 的卡明确标注“仅单测”。")
lines.append("")
cat_counts = Counter()
for _, _, e in rows:
    for cat in e["categories"]:
        cat_counts[cat] += 1
lines.append("## 0. 总览")
lines.append("")
lines.append(f"- 候选卡 **{len(rows)}**；有真实 Power.log trace **{sum(1 for _,_,e in rows if e['real_n'])}**；"
             f"有 679 差分证据 **{sum(1 for _,_,e in rows if e['div679_n'])}**；"
             f"有 BB 高 TVD(≥0.15) **{sum(1 for _,_,e in rows if e['bb_max'] and e['bb_max']>=0.15)}**。")
lines.append("- 类别分布：" + "；".join(
    f"`{k}` {v}" for k, v in cat_counts.most_common()) + "。")
lines.append("")
lines.append("## 1. 候选总表（按证据强度）")
lines.append("")
lines.append("| # | 卡 | 名称 | 类别 | 679 分歧/缺脚本/动态 | BB n / mean / max TVD | 真实 trace | 备注 |")
lines.append("|---|---|---|---|---|---|---|---|")
for idx, (score, card_id, e) in enumerate(rows, 1):
    cats = "、".join(sorted(e["categories"])) or "—"
    bb = (f"{e['bb_n']} / {e['bb_mean']} / {e['bb_max']}"
          if e["bb_n"] else "—")
    note = "C 类" if card_id in C_CLASS else ("已知 TOP" if card_id in KNOWN_TOP else "")
    skip_note = "（skip %s）" % e["adapter_skip"] if e["adapter_skip"] else ""
    lines.append(
        "| %d | `%s` | %s | %s | %d / %d / %d%s | %s | %d | %s |"
        % (idx, card_id, name_of(card_id), cats,
           e["div679_n"], e["missing_script"], e["dynamic"],
           skip_note, bb, e["real_n"], note))
lines.append("")
lines.append("## 2. 重点卡证据明细")
lines.append("")
for idx, (score, card_id, e) in enumerate(rows[:25], 1):
    lines.append(f"### {idx}. `{card_id}` {name_of(card_id)}")
    lines.append("")
    if text_of(card_id):
        lines.append(f"- 卡面：{text_of(card_id)}")
    lines.append(f"- 类别：{', '.join(sorted(e['categories'])) or '—'}；"
                 f"679 分歧 {e['div679_n']}、缺脚本 {e['missing_script']}、"
                 f"动态 {e['dynamic']}" + (f"、adapter_skip {e['adapter_skip']}"
                                           if e['adapter_skip'] else ""))
    if e["div679"]:
        sample = e["div679"][:3]
        lines.append("- 679 样本：" + "；".join(
            f"`{x['trace_id']}` {x['subclass']} official={x['official']} L1={x['l1']}"
            for x in sample))
    if e["bb"]:
        top = sorted(e["bb"], key=lambda x: -(x["tvd"] or 0))[:3]
        lines.append("- BB 高 TVD 状态：" + "；".join(
            f"state{x['state_id']} turn{x['turn']} TVD={x['tvd']} "
            f"engine={x['engine']} oracle={x['oracle']}" for x in top))
    if e["real_event"]:
        lines.append("- 真实事件级首分歧：" + "；".join(
            f"`{x['trace_id']}` [{x['classification']}] idx={x['index']} "
            f"official={x['official_event']} engine={x['engine_event']}"
            for x in e["real_event"][:2]))
    elif e["real"]:
        lines.append("- 真实 trace：" + "；".join(
            f"`{x['trace_id']}` turn{x['turn']} official={x['official']} status={x['status']}"
            for x in e["real"][:3]))
    else:
        lines.append("- **无真实 Power.log trace → 仅单测/合成证据**")
    lines.append("")
lines.append("## 3. 按类清单")
lines.append("")
for category in ("脚本缺失", "动态状态", "状态口径缺口", "疑似卡牌效果", "C 类证据不足"):
    members = [cid for _, cid, e in rows if category in e["categories"]]
    lines.append(f"### {category}（{len(members)}）")
    lines.append("")
    lines.append("、".join(f"`{c}` {name_of(c)}" for c in members) or "—")
    lines.append("")
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("wrote", OUT, "candidates", len(rows))
print("category counts", dict(cat_counts))
print("top 15")
for score, cid, e in rows[:15]:
    print(f"  {cid} {name_of(cid)} cats={sorted(e['categories'])} "
          f"div679={e['div679_n']} bb={e['bb_n']}/{e['bb_mean']}/{e['bb_max']} "
          f"real={e['real_n']}")
