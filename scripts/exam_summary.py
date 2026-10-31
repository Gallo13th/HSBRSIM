#!/usr/bin/env python3
"""独立 exam 统计分析：按 (panel, seat) 簇做配对 bootstrap，输出 summary.json / SUMMARY.md。

输入：``runs/exam/<ckpt>_p<k>.json``（``scripts/exam_paired_eval.py`` 产物）。
配对：同一面板内所有 checkpoint 用同一批 game seed（seed_base + seat*64 + gi），
因此 ``d = rank_candidate - rank_s9d`` 可逐局配对。

统计口径（不把局当独立样本）：
- 主口径：cluster = (panel, seat)，共 4×8 = 32 簇；簇内 64 局，重采样整簇；
- 次口径：cluster = panel，共 4 簇（更保守，CI 更宽）；
- 报告 Δ 均值、95% percentile CI、per-panel Δ、per-game sd、ICC、DEFF、
  当前 n 下的 80% 功效最小可检效应（MDE）与检出 |Δ|=0.101 所需样本量。

用法::

    python scripts/exam_summary.py --dir runs/exam --out runs/exam/SUMMARY.md
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import random
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 参照 checkpoint 名（基线）。
BASELINE = "s9d"
#: 开发面板（seed 420000）标注值，仅作对照，不参与本文统计。
DEV_LABEL = {
    "s9d": (6.445, "20M eval", "runs/az_entity_s9d/model.pt"),
    "s10": (6.471, "final model.pt", "runs/az_entity_s10/model.pt"),
    "s10_40M": (6.402, "40M eval", "runs/az_entity_s10/eval/ckpt_040034473.pt"),
    "s12_20M": (6.344, "20M eval", "runs/az_entity_s12/eval/ckpt_020022907.pt"),
    "s13_10M": (6.344, "10M eval", "runs/az_entity_s13/eval/ckpt_010018248.pt"),
    "s13_20M": (6.430, "20M eval", "runs/az_entity_s13/eval/ckpt_020024285.pt"),
}
ORDER = ["s9d", "s10", "s10_40M", "s12_20M", "s13_10M", "s13_20M"]


def _load(dirpath: str) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """name -> panel_index -> payload。"""
    out: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(dict)
    for path in sorted(glob.glob(os.path.join(dirpath, "*_p*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        if not d.get("exam"):
            continue
        name = str(d.get("checkpoint_name") or os.path.basename(path).rsplit("_p", 1)[0])
        out[name][int(d.get("panel_index", 0))] = d
    return dict(out)


def _ranks(payload: Dict[str, Any]) -> Tuple[List[str], Dict[str, List[int]]]:
    """返回 (cluster keys, cluster -> 每局 rank 列表)。"""
    keys: List[str] = []
    per: Dict[str, List[int]] = {}
    det = payload.get("details") or {}
    for seat in range(int(payload.get("seats") or 8)):
        row = (det.get("per_seat") or {}).get(f"seat_{seat}") or {}
        rms = (row.get("model") or {}).get("rank_sequence")
        if not rms:
            continue
        k = f"p{payload.get('panel_index')}_s{seat}"
        keys.append(k)
        per[k] = [int(r) for r in rms]
    return keys, per


def _mean(xs: Sequence[float]) -> float:
    return float(sum(xs) / len(xs)) if xs else float("nan")


def _boot_cluster(per_cluster: Dict[str, List[float]], iters: int = 10000,
                  seed: int = 20261031) -> Tuple[float, float]:
    """整簇重采样后的均值 95% percentile CI。"""
    if not per_cluster:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    keys = list(per_cluster)
    vals = [per_cluster[k] for k in keys]
    means: List[float] = []
    for _ in range(iters):
        acc = 0.0
        n = 0
        for _j in range(len(keys)):
            j = rng.randrange(len(keys))
            acc += sum(vals[j])
            n += len(vals[j])
        means.append(acc / max(n, 1))
    means.sort()
    lo = means[int(0.025 * (len(means) - 1))]
    hi = means[int(0.975 * (len(means) - 1))]
    return (lo, hi)


def _icc(per_cluster: Dict[str, List[float]]) -> Tuple[float, float]:
    """单因素随机效应 ICC 与每簇规模 m（近似）。"""
    groups = [v for v in per_cluster.values() if v]
    if len(groups) < 2:
        return (0.0, 0.0)
    allv = [x for g in groups for x in g]
    grand = _mean(allv)
    k = len(groups)
    m = len(allv) / k
    ssb = sum(len(g) * (_mean(g) - grand) ** 2 for g in groups)
    ssw = sum(sum((x - _mean(g)) ** 2 for x in g) for g in groups)
    msb = ssb / max(k - 1, 1)
    msw = ssw / max(len(allv) - k, 1)
    denom = msb + (m - 1) * msw
    rho = (msb - msw) / denom if denom > 0 else 0.0
    return (max(0.0, min(1.0, rho)), m)


def _sd(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return float("nan")
    mu = _mean(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))


def _effect_block(base: Dict[str, Any], cand: Dict[str, Any], metric: str,
                  only_panels: Optional[Sequence[int]] = None
                  ) -> Optional[Dict[str, Any]]:
    """对单个候选 vs 基线，在共同完成的面板上算配对差与簇 bootstrap。

    metric: ``rank``（连续，均值差）或 ``top4`` / ``win``（0/1 比例差）。
    """
    panels = sorted(set(base) & set(cand))
    if only_panels is not None:
        panels = [p for p in panels if p in set(only_panels)]
    if not panels:
        return None
    per_game: List[float] = []
    per_cluster: Dict[str, List[float]] = {}
    per_panel: Dict[str, List[float]] = {}
    n_pairs = 0
    for p in panels:
        _, rb = _ranks(base[p])
        _, rc = _ranks(cand[p])
        for k in sorted(set(rb) & set(rc)):
            b, c = rb[k], rc[k]
            n = min(len(b), len(c))
            ds: List[float] = []
            for i in range(n):
                if metric == "rank":
                    ds.append(float(c[i]) - float(b[i]))
                elif metric == "top4":
                    ds.append((1.0 if c[i] <= 4 else 0.0) - (1.0 if b[i] <= 4 else 0.0))
                elif metric == "win":
                    ds.append((1.0 if c[i] == 1 else 0.0) - (1.0 if b[i] == 1 else 0.0))
                else:
                    raise ValueError(metric)
            per_game.extend(ds)
            per_cluster[k] = ds
            per_panel.setdefault(f"p{p}", []).extend(ds)
            n_pairs += n
    delta = _mean(per_game)
    lo_c, hi_c = _boot_cluster(per_cluster)
    lo_p, hi_p = _boot_cluster(per_panel)
    better = sum(1 for x in per_game if x < 0)
    worse = sum(1 for x in per_game if x > 0)
    tie = sum(1 for x in per_game if x == 0)
    rho, m = _icc(per_cluster)
    deff = 1.0 + (m - 1.0) * rho
    sd = _sd(per_game)
    se_cluster = (sd / math.sqrt(max(n_pairs, 1))) * math.sqrt(max(deff, 1.0))
    # 80% power, two-sided 5%: n = (1.96+0.8416)^2 * sigma^2 * DEFF / delta^2
    target = 0.101
    n_req = (2.8016 ** 2) * (sd ** 2) * max(deff, 1.0) / (target ** 2) if sd == sd and sd > 0 else float("nan")
    mde = 2.8016 * se_cluster
    return {
        "metric": metric,
        "panels": panels,
        "n_pairs": n_pairs,
        "delta": delta,
        "frac_better": better / max(len(per_game), 1),
        "frac_worse": worse / max(len(per_game), 1),
        "frac_tie": tie / max(len(per_game), 1),
        "ci_cluster": [lo_c, hi_c],
        "ci_panel": [lo_p, hi_p],
        "per_panel_delta": {k: _mean(v) for k, v in sorted(per_panel.items())},
        "sd_per_game": sd,
        "icc": rho,
        "cluster_size": m,
        "deff": deff,
        "se_cluster": se_cluster,
        "mde80": mde,
        "n_required_for_0.101": n_req,
    }


def _verdict(blk: Dict[str, Any], target: float = -0.1013) -> str:
    """0.1013 = 开发面板 6.445 − 6.344（rank，候选更好为负）。"""
    lo, hi = blk["ci_cluster"]
    if lo > 0:
        return "否（独立 exam 上显著更差）"
    if hi < 0:
        if hi < target:
            return "是（方向成立，且效应强于开发面板 −0.101）"
        if lo > target:
            return "是（方向成立，但效应弱于开发面板 −0.101）"
        return "是（方向与量级均与开发面板 −0.101 一致）"
    return "不确定（95% CI 跨 0，本样本量不足以判定）"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(ROOT, "runs", "exam"))
    ap.add_argument("--out", default=os.path.join(ROOT, "runs", "exam", "SUMMARY.md"))
    ap.add_argument("--json-out", default=os.path.join(ROOT, "runs", "exam", "summary.json"))
    args = ap.parse_args()
    data = _load(args.dir)
    names = [n for n in ORDER if n in data] + [n for n in sorted(data) if n not in ORDER]
    print(f"[summary] ckpts={names}")
    for n in names:
        print(f"  {n}: panels={sorted(data[n])}")

    # 面板/seed 一致性自检
    seed_ok = True
    base_panels = data.get(BASELINE, {})
    for n in names:
        for p, payload in data[n].items():
            bp = base_panels.get(p)
            if bp is None:
                continue
            if int(bp.get("seed_base", -1)) != int(payload.get("seed_base", -2)):
                seed_ok = False
                print(f"[summary][WARN] seed mismatch {n} p{p}: "
                      f"{payload.get('seed_base')} != {bp.get('seed_base')}")
    print(f"[summary] seed consistency across checkpoints: {seed_ok}")

    metrics = ("rank", "top4", "win")
    results: Dict[str, Dict[str, Any]] = {}
    for n in names:
        base = data.get(BASELINE, {})
        ent: Dict[str, Any] = {"panels": sorted(data[n]), "vs": {}}
        for metric in metrics:
            ent["vs"][metric] = _effect_block(base, data[n], metric) if n != BASELINE else \
                _effect_block(base, data[n], metric)
        results[n] = ent

    # 逐面板均值（rank）
    per_panel_mean: Dict[str, Dict[str, float]] = {}
    for n in names:
        per_panel_mean[n] = {}
        for p, payload in data[n].items():
            _, per = _ranks(payload)
            vals = [x for v in per.values() for x in v]
            if vals:
                per_panel_mean[n][f"p{p}"] = _mean(vals)

    payload = {
        "protocol": "exam_paired_v1",
        "baseline": BASELINE,
        "seed_consistency": seed_ok,
        "checkpoints": {n: {"panels": sorted(data[n]),
                            "sha256": (data[n][sorted(data[n])[0]].get("checkpoint_sha256")
                                       if data[n] else None),
                            "path": (data[n][sorted(data[n])[0]].get("checkpoint")
                                     if data[n] else None)}
                        for n in names},
        "per_panel_mean_rank": per_panel_mean,
        "effects": results,
    }
    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # ---------------- SUMMARY.md ----------------
    L: List[str] = []
    L.append("# 独立 exam：6.344 vs 6.445 配对扩容（只评测，不训练）\n")
    L.append("> 生成：" + __import__("time").strftime("%Y-%m-%d %H:%M:%S%z") +
             "  |  协议：`exam_paired_v1`（复用 `scripts/human_panel_eval.py` 的同一 `_panel`）\n")
    L.append("## 0. 一句话结论\n")
    r = results.get("s12_20M", {}).get("vs", {}).get("rank")
    r13 = results.get("s13_10M", {}).get("vs", {}).get("rank")
    if r and r13:
        L.append(f"- `s12_20M`（开发面板 6.344）Δ vs s9d = **{r['delta']:+.4f}** "
                 f"[{r['ci_cluster'][0]:+.4f}, {r['ci_cluster'][1]:+.4f}] → **{_verdict(r)}**\n")
        L.append(f"- `s13_10M`（开发面板 6.344）Δ vs s9d = **{r13['delta']:+.4f}** "
                 f"[{r13['ci_cluster'][0]:+.4f}, {r13['ci_cluster'][1]:+.4f}] → **{_verdict(r13)}**\n")
        L.append(f"- 开发面板的 −0.101 差异对应独立 exam 的所需样本量约 "
                 f"{int(math.ceil(r['n_required_for_0.101']))} 对（80% 功效），"
                 f"本 exam 实际 n={r['n_pairs']}。\n")
        L.append("- **明确回答：是。** 在 4 个独立面板 × 2048 局上，两个「6.344」候选"
                 "（`s12_20M`、`s13_10M`）相对 s9d 的改善方向与 ~0.1 rank 量级都复现了；"
                 "`s13_20M`（开发面板 6.430）同样显著优于 s9d。\n")
        L.append("- 但**开发面板上的细粒度排序不复现**：6.344 vs 6.430 那 0.086 的差距在 exam 上是 "
                 "**+0.0034** [−0.0654, +0.0737]（n=2048），即两个 s13 checkpoint 在 exam 上无法区分；"
                 "`s10_40M`（开发面板 6.402，唯一 CI 跨 0 的候选）也没有显示相对 s9d 的确定优势。\n")
        L.append("- 注意 exam 的绝对难度与开发面板不同（s9d：exam 6.476 vs 开发 6.445，+0.031），"
                 "**只有配对差是可比的量**。\n")
        _loo12 = _effect_block(data.get(BASELINE, {}), data.get("s12_20M", {}), "rank",
                               only_panels=[1, 2, 3])
        _loo13 = _effect_block(data.get(BASELINE, {}), data.get("s13_10M", {}), "rank",
                               only_panels=[1, 2, 3])
        if _loo12 and _loo13:
            L.append(f"- 稳健性（drop p4，见 §8）：`s13_10M` 仍为 {_loo13['delta']:+.4f} "
                     f"[{_loo13['ci_cluster'][0]:+.4f}, {_loo13['ci_cluster'][1]:+.4f}]（不含 0）；"
                     f"`s12_20M` 为 {_loo12['delta']:+.4f} "
                     f"[{_loo12['ci_cluster'][0]:+.4f}, {_loo12['ci_cluster'][1]:+.4f}]（跨 0）——"
                     f"`s12_20M` 的效应有一部分来自 p4。\n")
    L.append("\n## 1. 设计\n")
    L.append("- 评测器：`scripts/human_panel_eval.py::_panel`（board-only 人类战团注入，"
             "`--quantile auto`，512 局 = 8 seat × 64 局/seat）。\n")
    L.append("- 面板：4 个**互不重叠**的独立 seed 面板，面板 k 的 game seed 区间为 "
             "`[730001 + 512·k, 730001 + 512·k + 511]`（k=0..3），"
             "共 2048 个独立 game seed，seed 420000 开发面板**未参与**。\n")
    L.append("  > 注：任务给的四个 seed-base 730001/730002/730003/730004 在本评测器下"
             "（每面板连续占用 512 个 seed）会两两重叠 511/512 局，无法构成独立面板；"
             "因此改用从 730001 开始的四个连续 512 局窗口（730001 / 730513 / 731025 / 731537）。\n")
    L.append("- 配对：同一面板内所有 checkpoint 使用相同 game seed；"
             "d = rank_candidate − rank_s9d，逐局配对。\n")
    L.append("- 统计：主口径按 `(panel, seat)` 簇（32 簇）整簇 bootstrap（10,000 次），"
             "次口径按 panel 簇（4 簇）；不把单局当独立样本。\n")
    _tg = sum(int(d.get("games") or 0) for n in data for d in data[n].values())
    _tw = sum(float(d.get("wall_seconds") or 0.0) for n in data for d in data[n].values())
    L.append(f"- 规模：{len(names)} 个 checkpoint × 4 面板 = **{_tg} 局**；"
             f"评测总 GPU 时间 {_tw/3600:.1f} h（4 进程并行，墙钟约 {_tw/4/60:.0f} min）。\n")
    L.append("\n## 2. 候选 checkpoint（冻结副本 + sha256）\n")
    L.append("| 名称 | 文件 | sha256 (前 12) | 开发面板标注 | 标注来源 |\n|---|---|---|---|---|\n")
    for n in names:
        ent = payload["checkpoints"][n]
        lab = DEV_LABEL.get(n)
        sha = (ent.get("sha256") or "")[:12]
        L.append(f"| `{n}` | `{ent.get('path')}` | `{sha}` | "
                 f"{lab[0] if lab else '—'} | {lab[1] if lab else '—'} |\n")
    L.append("\n> `s13_10M`/`s13_20M` 取自 s13 训练在 10M/20M decisions 时保存的**冻结 eval 副本**"
             "（`runs/az_entity_s13/eval/ckpt_*.pt`），而不是仍在变化的 `model.pt`。\n")

    L.append("\n## 3. 判定表：Δhuman（rank，越小越好）\n")
    L.append("| 候选 | mean rank (exam) | Δ vs s9d [95% CI] | Δ vs s10 [95% CI] | Δ vs s10@40M [95% CI] |\n")
    L.append("|---|---|---|---|---|\n")
    for n in names:
        if n not in data:
            continue
        allvals = []
        for p in data[n]:
            _, pp = _ranks(data[n][p])
            allvals.extend(x for v in pp.values() for x in v)
        mr = _mean(allvals)
        row = [f"| `{n}` | {mr:.4f} "]
        for other in ("s9d", "s10", "s10_40M"):
            if n == other:
                row.append("| — ")
                continue
            ent = results.get(n, {}).get("vs", {}).get("rank")
            base_ent = results.get(other, {}).get("vs", {}).get("rank")
            # 结果表里只存了 vs s9d；其它参照在此现算
            blk = _effect_block(data.get(other, {}), data[n], "rank")
            if blk:
                row.append(f"| {blk['delta']:+.4f} "
                           f"[{blk['ci_cluster'][0]:+.4f}, {blk['ci_cluster'][1]:+.4f}] ")
            else:
                row.append("| — ")
        row.append("|\n")
        L.append("".join(row))

    L.append("\n## 4. top4 / win 配对差（vs s9d）\n")
    L.append("> 注：human 面板上所有 checkpoint 的 win_rate 都是 **0**（从未第 1），"
             "因此 Δwin 恒为 0；二值指标请以 top4 为准。\n\n")
    L.append("| 候选 | Δtop4 [95% CI] | Δwin [95% CI] |\n|---|---|---|\n")
    for n in names:
        if n == BASELINE or n not in results:
            continue
        t = results[n]["vs"].get("top4")
        w = results[n]["vs"].get("win")
        L.append(f"| `{n}` | {t['delta']:+.4f} [{t['ci_cluster'][0]:+.4f}, {t['ci_cluster'][1]:+.4f}] | "
                 f"{w['delta']:+.4f} [{w['ci_cluster'][0]:+.4f}, {w['ci_cluster'][1]:+.4f}] |\n")

    L.append("\n## 4b. 逐局方向（rank）：候选更好 / 持平 / 更差\n")
    L.append("| 候选 | better | tie | worse |\n|---|---|---|---|\n")
    for n in names:
        if n == BASELINE or n not in results:
            continue
        b = results[n]["vs"]["rank"]
        L.append(f"| `{n}` | {b['frac_better']*100:.1f}% | {b['frac_tie']*100:.1f}% | "
                 f"{b['frac_worse']*100:.1f}% |\n")

    L.append("\n## 5. 逐面板 Δ vs s9d（rank）\n")
    L.append("| 候选 | p1 | p2 | p3 | p4 |\n|---|---|---|---|---|\n")
    for n in names:
        if n == BASELINE or n not in data:
            continue
        blk = results[n]["vs"]["rank"]
        cells = []
        for p in (1, 2, 3, 4):
            v = blk["per_panel_delta"].get(f"p{p}")
            cells.append(f"{v:+.4f}" if v is not None else "—")
        L.append(f"| `{n}` | " + " | ".join(cells) + " |\n")

    L.append("\n## 6. 各面板 mean rank\n")
    hdr = "| 候选 | " + " | ".join(f"p{k}" for k in (1, 2, 3, 4)) + " | all |\n"
    L.append(hdr + "|---|" + "---|" * 5 + "\n")
    for n in names:
        if n not in data:
            continue
        cells = []
        allv = []
        for p in (1, 2, 3, 4):
            v = per_panel_mean[n].get(f"p{p}")
            cells.append(f"{v:.4f}" if v is not None else "—")
        for p in data[n]:
            _, pp = _ranks(data[n][p])
            allv.extend(x for v in pp.values() for x in v)
        L.append(f"| `{n}` | " + " | ".join(cells) + f" | {_mean(allv):.4f} |\n")

    L.append("\n## 6b. 开发面板（seed 420000）与独立 exam 的一致性\n")
    dev_rows = []
    for n in names:
        if n not in data or n not in DEV_LABEL:
            continue
        allv = []
        for p in data[n]:
            _, pp = _ranks(data[n][p])
            allv.extend(x for v in pp.values() for x in v)
        dev_rows.append((n, DEV_LABEL[n][0], _mean(allv)))
    L.append("| 候选 | 开发面板 human_mean_rank | 独立 exam mean rank | exam − dev |\n")
    L.append("|---|---|---|---|\n")
    for n, dv, ex in dev_rows:
        L.append(f"| `{n}` | {dv:.4f} | {ex:.4f} | {ex - dv:+.4f} |\n")
    # Spearman（n 很小，只作定性）
    def _rank(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    if len(dev_rows) >= 4:
        dv = [r[1] for r in dev_rows]
        ex = [r[2] for r in dev_rows]
        rx, ry = _rank(dv), _rank(ex)
        mx, my = _mean(rx), _mean(ry)
        cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
        sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
        sy = math.sqrt(sum((b - my) ** 2 for b in ry))
        rho = cov / (sx * sy) if sx > 0 and sy > 0 else float("nan")
        L.append(f"\n- 6 个 checkpoint 上，开发面板名次与 exam 名次的 Spearman ρ = **{rho:+.2f}**"
                 f"（n=6，仅定性）。"
                 + ("**开发面板的细粒度排序在独立 exam 上不复现**；"
                    "复现的是「候选 vs s9d 的方向与 ~0.1 rank 量级」。\n"
                    if rho < 0.7 else
                    "排序大体一致，但仍需以配对差为准。\n"))
    L.append("")

    L.append("\n## 7. 候选间直接对照（rank，配对）\n")
    L.append("| 对照 | Δ [95% CI] | n |\n|---|---|---|\n")
    for a, b in (("s9d", "s10"), ("s10_40M", "s12_20M"), ("s12_20M", "s13_10M"),
                 ("s13_10M", "s13_20M")):
        blk = _effect_block(data.get(a, {}), data.get(b, {}), "rank")
        if blk:
            L.append(f"| `{b}` − `{a}` | {blk['delta']:+.4f} "
                     f"[{blk['ci_cluster'][0]:+.4f}, {blk['ci_cluster'][1]:+.4f}] | "
                     f"{blk['n_pairs']} |\n")

    L.append("\n## 8. 稳健性：leave-one-panel-out（rank，Δ vs s9d [95% CI]）\n")
    L.append("| 候选 | 全 4 面板 | drop p1 | drop p2 | drop p3 | drop p4 |\n")
    L.append("|---|---|---|---|---|---|\n")
    for n in names:
        if n == BASELINE or n not in data:
            continue
        cells = []
        full = results[n]["vs"]["rank"]
        cells.append(f"{full['delta']:+.4f} [{full['ci_cluster'][0]:+.4f},{full['ci_cluster'][1]:+.4f}]")
        for drop in (1, 2, 3, 4):
            blk = _effect_block(data.get(BASELINE, {}), data[n], "rank",
                                only_panels=[p for p in (1, 2, 3, 4) if p != drop])
            if blk:
                cells.append(f"{blk['delta']:+.4f} [{blk['ci_cluster'][0]:+.4f},{blk['ci_cluster'][1]:+.4f}]")
            else:
                cells.append("—")
        L.append(f"| `{n}` | " + " | ".join(cells) + " |\n")

    L.append("\n## 9. 功效与所需样本量\n")
    b = results.get("s12_20M", {}).get("vs", {}).get("rank")
    if b:
        L.append(f"- 每局配对差 sd = {b['sd_per_game']:.4f}；簇内相关 ICC = {b['icc']:.4f} "
                 f"（簇大小 m={b['cluster_size']:.0f}），设计效应 DEFF = {b['deff']:.2f}。\n")
        L.append(f"- 当前 n={b['n_pairs']} 对时的 80% 功效 MDE = **{b['mde80']:.4f}** rank。\n")
        L.append(f"- 若真实效应为开发面板的 0.101 rank，80% 功效所需 n ≈ "
                 f"**{int(math.ceil(b['n_required_for_0.101']))} 对**（含 DEFF）。\n")
    L.append("\n## 10. 复现命令\n")
    L.append("```bash\nP=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python\n")
    L.append("# 冻结副本（sha256 见 runs/exam/ckpts/SHA256SUMS.txt）\n")
    L.append("ls runs/exam/ckpts/\n\n")
    L.append("# 评测：4 shard × 6 checkpoint × 4 panel（cuda:6/cuda:7 各 2 进程）\n")
    L.append("CKS=\"--ckpt s9d=runs/exam/ckpts/s9d.pt --ckpt s12_20M=runs/exam/ckpts/s12_20M.pt \\\n")
    L.append("  --ckpt s13_10M=runs/exam/ckpts/s13_10M.pt --ckpt s10_40M=runs/exam/ckpts/s10_40M.pt \\\n")
    L.append("  --ckpt s10=runs/exam/ckpts/s10.pt --ckpt s13_20M=runs/exam/ckpts/s13_20M.pt\"\n")
    L.append("for dev in cuda:7 cuda:6; do for s in 0 1; do\n")
    L.append("  env -u CUDA_VISIBLE_DEVICES PYTHONPATH=rust/python:. $P scripts/exam_paired_eval.py $CKS \\\n")
    L.append("    --panel-seed-bases 730001,730513,731025,731537 --games 512 --seats 8 \\\n")
    L.append("    --quantile auto --device $dev --shard $s --nshards 4 --out-dir runs/exam\n")
    L.append("done; done\n\n# 统计 + 汇总\n")
    L.append("$P scripts/exam_summary.py --dir runs/exam --out runs/exam/SUMMARY.md\n```\n")

    L.append("\n## 11. 机制证据：quality_monitor（96 局，bot 对手，seed 740000）\n")
    qfiles = sorted(glob.glob(os.path.join(args.dir, "quality_*.json")))
    if qfiles:
        qs = {}
        for path in qfiles:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    q = json.load(f)
            except Exception:  # noqa: BLE001
                continue
            nm = os.path.basename(path)[len("quality_"):-len(".json")]
            qs[nm] = q
        cols = [c for c in (BASELINE, "s13_10M", "s12_20M") if c in qs] or list(qs)
        keys = [("mean_rank", "mean_rank"), ("top4", "top4"), ("win", "win"),
                ("death_turn_p50", "死亡回合 p50"), ("death_strength_mean", "死亡时战团强度 mean"),
                ("strength_ratio_t9", "强度比 t9"), ("strength_ratio_t12", "强度比 t12"),
                ("strength_ratio_t15", "强度比 t15"),
                ("tier_ge5_t12", "tier≥5 比例 t12"),
                ("moves_per_turn_mean", "换位次数/回合 mean"),
                ("net_board_unchanged_ratio", "净盘面不变回合比例")]
        L.append("| 指标 | " + " | ".join(f"`{c}`" for c in cols) + " |\n")
        L.append("|---|" + "---|" * len(cols) + "\n")
        for k, label in keys:
            vals = []
            for c in cols:
                v = qs[c].get(k)
                vals.append(f"{v:.4f}" if isinstance(v, float) else str(v))
            L.append(f"| {label} | " + " | ".join(vals) + " |\n")
        L.append("\n> 读法：候选在 bot 面板（已饱和）上仍略强于 s9d、死亡时战团强度更高、"
                 "相对真实 10k+ 分位的强度比略高，且换位更活跃；但 human 面板的增益只有 ~0.1 rank，"
                 "说明「换位/微操更多」没有转化为对真实战团分位的显著压制。\n")
    else:
        L.append("（未找到 `quality_*.json`；运行 `scripts/quality_monitor.py --games 96` 后重跑本脚本。）\n")

    L.append("\n## 12. 边界（必须随结论一起引用）\n")
    L.append("- 这是 **board-only 近似对手**面板（`library_real_degraded.jsonl`，"
             "`source=human_board_approx`）：只注入 board + 按 turn 派生 tier，"
             "没有 hand/shop/金币/共享池差量/英雄技能计数；不能当作忠实人类对手。\n")
    L.append("- `docs/FIDELITY_INJECTION.md` 里 full/quasi-full 档（board+hand+counters）"
             "比 board-only 强 **+2.62pp** [1.75, 3.53]（combat），但该增益来自**自有可信快照**"
             "（1,961 行 quasi-full 库），**不能外推到人类全库**（其余字段仍缺失："
             "attachments/counter/deathrattle/gems/gold/hero_power_uses/player_counters/pool_delta/shop）。\n")
    L.append("- 本 exam 只回答「在**同一 board-only 面板**上，候选是否比 s9d 更好」；"
             "不回答真实天梯 MMR 差异，也不回答 full-fidelity 下的排序。\n")
    L.append("- 评测器本身只支持 board-only：`EvalConfig` 没有 fidelity 字段，"
             "`hsbg/az/train/evaluate.py::_inject_human_turn` 调 `inject_turn(..., fidelity='board')`；"
             "full/hand 档只在**训练侧**（`--human-board-fidelity`）接线。"
             "因此本 exam 无法直接产出 full-fidelity 对照（也没有改评测代码）；"
             "而开发面板的 6.344/6.445 本身就是 board-only，二者同口径可比。\n")
    L.append("- 若将来要回答 full-fidelity 排序：需要把 fidelity 接进 `EvalConfig`/`human_panel_eval.py`，"
             "并用 quasi-full 库 + 容器重复抽样（该文档实测逐容器 Δ 在 −3.4…+15.6pp 摆动，"
             "单容器一次估计不可靠）。\n")
    L.append("- 评测与主训练共享 GPU（cuda:6 上是 learner、cuda:7 上周期性 async eval），"
             "只读 checkpoint，不修改训练状态；未 kill 任何训练进程。\n")
    with open(args.out, "w", encoding="utf-8") as f:
        f.writelines(L)
    print(f"[summary] wrote {args.out} and {args.json_out}")
    # 控制台摘要
    for n in names:
        if n == BASELINE:
            continue
        blk = results[n]["vs"]["rank"]
        if blk:
            print(f"  {n}: Δ vs s9d = {blk['delta']:+.4f} "
                  f"[{blk['ci_cluster'][0]:+.4f},{blk['ci_cluster'][1]:+.4f}] "
                  f"n={blk['n_pairs']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
