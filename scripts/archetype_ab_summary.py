#!/usr/bin/env python3
"""流派软偏置 A/B 汇总（三臂 × 训练 meta × 三个固定量具）。

读取::

    runs/az_arch_ab/<arm>/history.jsonl            # 训练逐 iter 记录
    runs/az_arch_ab/eval_<arm>/human_panel_144.json
    runs/az_arch_ab/eval_<arm>/c0_gate_128.json
    runs/az_arch_ab/eval_<arm>/quality_64.json

输出一份 JSON + 一份可直接粘进 ``docs/ARCHETYPE_BIAS.md`` 的 markdown 表。
**只读**：不训练、不评测，方便复算。

用法::

    python scripts/archetype_ab_summary.py --arms A,B,C \
        --root runs/az_arch_ab --out runs/az_arch_ab/summary.json
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional, Sequence

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 三个固定量具里要抓的字段（缺失自动跳过）。
HUMAN_KEYS = ("model_mean_rank", "bot_mean_rank", "mean_diff", "ci_low", "ci_high",
              "model_top4", "bot_top4", "model_win", "bot_win", "n",
              "illegal", "truncated")
QUALITY_KEYS = ("mean_rank", "top4", "win", "death_turn_p50", "death_strength_p50",
                "strength_ratio_t9", "strength_ratio_t12", "strength_ratio_t15",
                "tier_ge5_t9", "tier_ge5_t12", "tier_ge5_t15",
                "moves_per_turn_mean", "moves_per_turn_p90",
                "net_board_unchanged_ratio", "games")
ARCH_SUM_KEYS = ("archetype_decisions", "archetype_detected", "archetype_bias_applied",
                 "archetype_level_archetype", "archetype_level_tribe",
                 "archetype_level_none", "archetype_bias_actions",
                 "archetype_bias_sum")


def _load_json(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001 - 半截文件按缺失处理
        return None


def _panel(path: str) -> Optional[Dict[str, Any]]:
    """评测 JSON → 第一个 panel 的指标（c0_gate/human_panel 同结构）。"""
    doc = _load_json(path)
    if not doc:
        return None
    panels = doc.get("panels") or []
    if not panels:
        return None
    p = panels[0]
    out = {k: p.get(k) for k in HUMAN_KEYS}
    out["passed"] = bool(p.get("passed"))
    out["protocol"] = doc.get("protocol")
    out["model_decisions"] = p.get("model_decisions")
    return out


def _training(hist_path: str) -> Dict[str, Any]:
    if not os.path.isfile(hist_path):
        return {}
    rows: List[Dict[str, Any]] = []
    with open(hist_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if r.get("iter") is not None:
                rows.append(r)
    if not rows:
        return {}
    rows.sort(key=lambda r: int(r["iter"]))
    total_dec = sum(int(r.get("collect", {}).get("decisions", 0) or 0) for r in rows)
    seconds = float(rows[-1].get("seconds", 0.0) or 0.0)
    arch: Dict[str, Any] = {}
    names: Dict[str, int] = {}
    for r in rows:
        c = r.get("collect") or {}
        for k in ARCH_SUM_KEYS:
            if k in c:
                arch[k] = arch.get(k, 0) + (float(c[k]) if k.endswith("_sum")
                                            else int(c[k] or 0))
        for name, n in (c.get("archetype_names") or {}).items():
            names[str(name)] = names.get(str(name), 0) + int(n)
    prob = [float((r.get("collect") or {}).get("archetype_mean_prob", 0.0) or 0.0)
            for r in rows if (r.get("collect") or {}).get("archetype_detected")]
    out = {
        "iters": int(rows[-1]["iter"]) + 1,
        "decisions": int(total_dec),
        "seconds": round(seconds, 1),
        "sec_per_iter": round(seconds / max(1, len(rows)), 2),
        "archetype": {
            **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in arch.items()},
            "archetype_mean_prob": (round(sum(prob) / len(prob), 4) if prob else None),
            "archetype_names": dict(sorted(names.items(), key=lambda kv: (-kv[1], kv[0]))),
        },
        "final_collect": {k: v for k, v in
                          (rows[-1].get("collect") or {}).items()
                          if k in ("decisions", "wall_s", "decisions_per_s",
                                   "human_board_attempt", "human_board_applied",
                                   "human_board_rejected", "move_guard_forced")},
    }
    return out


def _arm(root: str, arm: str) -> Dict[str, Any]:
    base = os.path.join(root, arm)
    ev = os.path.join(root, f"eval_{arm}")
    return {
        "arm": arm,
        "training": _training(os.path.join(base, "history.jsonl")),
        "human_panel_144": _panel(os.path.join(ev, "human_panel_144.json")),
        "c0_gate_128": _panel(os.path.join(ev, "c0_gate_128.json")),
        "quality_64": _load_json(os.path.join(ev, "quality_64.json")),
        "checkpoint": os.path.join(base, "model.pt"),
    }


def _fmt(v: Any, digits: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def _pct(num: Any, den: Any) -> str:
    try:
        n, d = float(num), float(den)
        return f"{100.0 * n / d:.1f}%" if d > 0 else "—"
    except Exception:  # noqa: BLE001
        return "—"


def to_markdown(summary: Dict[str, Any]) -> str:
    arms = [a["arm"] for a in summary["arms"]]
    lines: List[str] = []

    def row(label: str, getter) -> str:
        cells = []
        for a in summary["arms"]:
            try:
                cells.append(_fmt(getter(a)))
            except Exception:  # noqa: BLE001
                cells.append("—")
        return f"| {label} | " + " | ".join(cells) + " |"

    lines.append("### 训练（同超参，cuda:7，40 iters）")
    lines.append("| 指标 | " + " | ".join(arms) + " |")
    lines.append("|---|" + "---:|" * len(arms))
    lines.append(row("iterations", lambda a: a["training"].get("iters")))
    lines.append(row("learner decisions", lambda a: a["training"].get("decisions")))
    lines.append(row("训练秒（含 actor）", lambda a: a["training"].get("seconds")))
    lines.append(row("秒/iter", lambda a: a["training"].get("sec_per_iter")))
    lines.append(row("偏置决策数", lambda a: a["training"].get("archetype", {}).get(
        "archetype_decisions")))
    lines.append(row("检测命中数", lambda a: a["training"].get("archetype", {}).get(
        "archetype_detected")))
    lines.append(row("实际加 bias 的决策数",
                     lambda a: a["training"].get("archetype", {}).get(
                         "archetype_bias_applied")))
    lines.append(row("命中率(检出/决策)",
                     lambda a: _pct(a["training"].get("archetype", {}).get(
                         "archetype_detected"),
                         a["training"].get("archetype", {}).get("archetype_decisions"))))
    lines.append(row("偏置应用率(应用/决策)",
                     lambda a: _pct(a["training"].get("archetype", {}).get(
                         "archetype_bias_applied"),
                         a["training"].get("archetype", {}).get("archetype_decisions"))))
    def _levels(a) -> str:
        arch = a["training"].get("archetype") or {}
        lv = arch.get("archetype_level_archetype")
        tr = arch.get("archetype_level_tribe")
        if lv is None and tr is None:
            return "—"
        return f"{lv} / {tr}"

    lines.append(row("流派级 / 种族级 命中", _levels))
    lines.append(row("命中类平均概率",
                     lambda a: a["training"].get("archetype", {}).get(
                         "archetype_mean_prob")))
    lines.append(row("Top 命中流派",
                     lambda a: ", ".join(
                         f"{k}:{v}" for k, v in list(a["training"].get(
                             "archetype", {}).get("archetype_names", {}).items())[:4])
                     or "—"))

    for key, title in (("human_panel_144", "人类战团面板（144 局，配对 bot 基线）"),
                       ("c0_gate_128", "C0 gate（128 局 vs 引擎 bot）")):
        lines.append("")
        lines.append(f"### {title}")
        lines.append("| 指标 | " + " | ".join(arms) + " |")
        lines.append("|---|" + "---:|" * len(arms))
        lines.append(row("model mean_rank", lambda a, k=key: (a[k] or {}).get(
            "model_mean_rank")))
        lines.append(row("bot mean_rank", lambda a, k=key: (a[k] or {}).get(
            "bot_mean_rank")))
        lines.append(row("Δ mean_rank（model-bot）", lambda a, k=key: (a[k] or {}).get(
            "mean_diff")))
        lines.append(row("95% CI", lambda a, k=key: "%s … %s" % (
            _fmt((a[k] or {}).get("ci_low")), _fmt((a[k] or {}).get("ci_high")))))
        lines.append(row("model top4", lambda a, k=key: (a[k] or {}).get("model_top4")))
        lines.append(row("model win", lambda a, k=key: (a[k] or {}).get("model_win")))
        lines.append(row("model decisions", lambda a, k=key: (a[k] or {}).get(
            "model_decisions")))

    lines.append("")
    lines.append("### 质量监控（64 局，t12/t15 强度比、tier、换位）")
    lines.append("| 指标 | " + " | ".join(arms) + " |")
    lines.append("|---|" + "---:|" * len(arms))
    for k in QUALITY_KEYS:
        lines.append(row(k, lambda a, k=k: (a["quality_64"] or {}).get(k)))
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="流派软偏置 A/B 汇总（只读）")
    ap.add_argument("--root", default=os.path.join(ROOT, "runs/az_arch_ab"))
    ap.add_argument("--arms", default="A,B,C")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    arms = [a.strip() for a in str(args.arms).split(",") if a.strip()]
    summary = {"root": os.path.abspath(args.root),
               "arms": [_arm(args.root, a) for a in arms]}
    md = to_markdown(summary)
    print(md)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out + ".tmp", "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        os.replace(args.out + ".tmp", args.out)
        with open(os.path.splitext(args.out)[0] + ".md", "w", encoding="utf-8") as f:
            f.write(md + "\n")
        print(f"\n[out] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
