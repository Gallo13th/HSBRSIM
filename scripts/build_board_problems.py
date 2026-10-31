#!/usr/bin/env python3
"""构造**场面题**（board problems）：在当前权重的自对弈关键局面上出题。

设计见 ``docs/RESEARCH_PLAN_V2.md`` §4.1 与 ``docs/BOARD_PROBLEMS.md``。核心不是「拿人类
轨迹做 BC」，而是：

1. 用**当前 s14 权重**按训练分布 rollout（人类战团 5 席 p0.9 + 镜像 2 席 p0.2 +
   move-guard 1），只在**关键局面**出题：每回合起点 + 决策分叉点（可升本 / 三连 /
   核心随从）；
2. 每道题存：观测（features+cards+合法动作，f32 可逐位复现）、当前策略动作、
   **人类参考动作 top-k**（按 ``(turn,tier)`` 从 Firestone/10k+ 动作分布匹配，且必须
   落在当前局面的合法掩码内、经过 move_guard）、以及 **t+3 回合的战团强度/tier 真实值**
   （rollout 后回填）；
3. 统计：题目数、覆盖 turn、参考解匹配率/缺失率、标签可用率、Move 守卫。

用法::

    PYTHONPATH=rust/python:. python scripts/build_board_problems.py \
      --checkpoint runs/az_entity_s14/model.pt --device cuda:7 \
      --games 16 --seed 20200 --out data/board_problems/problems.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from hsbg.az.train.board_problems import (  # noqa: E402
    DEFAULT_BC_SAMPLES,
    DEFAULT_PROBLEM_PATH,
    DEFAULT_REF_FLOORS,
    ProblemCollectConfig,
    build_reference_table,
    collect_problems,
    write_problems,
)
from hsbg.az.train.common import engine_available  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402


def _parse_floors(spec: str):
    out = []
    for part in str(spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return tuple(sorted(set(out), reverse=True)) or DEFAULT_REF_FLOORS


def main() -> int:
    ap = argparse.ArgumentParser(description="构造场面题（自对弈关键局面 + 人类参考解）")
    ap.add_argument("--checkpoint", default="runs/az_entity_s14/model.pt",
                    help="出题用的权重（默认 s14 当前权重）")
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--games", type=int, default=16,
                    help="rollout 局数（默认 16 ≈ 200–600 道题）")
    ap.add_argument("--seed", type=int, default=20200)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--learner-seat", type=int, default=0)
    ap.add_argument("--horizon", type=int, default=3, help="短程标签视界（默认 t+3）")
    ap.add_argument("--min-turn", type=int, default=1,
                    help="最小出题回合（默认 1：跳过 turn 0 的选英雄局面）")
    ap.add_argument("--keep-turn-start", type=int, default=1, choices=[0, 1],
                    help="1=每回合起点必出一道题（默认）")
    ap.add_argument("--max-fork-per-turn", type=int, default=2,
                    help="每回合最多保留几个分叉点（默认 2）")
    ap.add_argument("--core-min-tier", type=int, default=3,
                    help="核心随从判据的最低 tier（默认 3）")
    ap.add_argument("--obs-dtype", default="f32", choices=["f32", "f16"],
                    help="观测存储精度（f32 可逐位复现；f16 体积减半）")
    ap.add_argument("--top-k", type=int, default=8, help="参考解保留的 top-k 动作数")
    ap.add_argument("--min-support", type=int, default=40,
                    help="参考分布某层级的最小样本支撑（不足则退化到更粗层级）")
    ap.add_argument("--reference-samples", default=DEFAULT_BC_SAMPLES,
                    help="人类动作来源（默认 data/firestone_bc/bc_samples.jsonl.gz）")
    ap.add_argument("--mmr-floors", default=",".join(str(f) for f in DEFAULT_REF_FLOORS),
                    help="参考解 MMR 阶梯（默认 10000,8000,6000：优先 10k+）")
    ap.add_argument("--reference-limit", type=int, default=0,
                    help="只扫前 N 条人类样本（0=全部；调试用）")
    # 训练分布（与 s14 一致）
    ap.add_argument("--human-boards",
                    default="data/real_library/library_real_quasi_full.jsonl")
    ap.add_argument("--human-board-p", type=float, default=0.9)
    ap.add_argument("--human-board-seats", type=int, default=5)
    ap.add_argument("--human-board-fidelity", default="full",
                    choices=["board", "hand", "full"])
    ap.add_argument("--mirror-snaps", default="runs/library/snaps_champ")
    ap.add_argument("--mirror-seats", type=int, default=2)
    ap.add_argument("--mirror-p", type=float, default=0.2)
    ap.add_argument("--mirror-sample", default="p75")
    ap.add_argument("--move-guard", type=int, default=1, choices=[0, 1])
    ap.add_argument("--move-cap", type=int, default=3)
    ap.add_argument("--move-repeat-limit", type=int, default=2)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--out", default=DEFAULT_PROBLEM_PATH)
    ap.add_argument("--stats-out", default="",
                    help="统计 JSON 路径（默认 <out 去扩展>.meta.json）")
    ap.add_argument("--limit-games", type=int, default=0,
                    help="只跑前 N 局（0=全部；调试用）")
    args = ap.parse_args()

    if not engine_available():
        print("[error] hsbg_engine 不可用（需要 build/install rust 引擎）", file=sys.stderr)
        return 2
    if int(args.games) <= 0:
        print("[error] --games 必须 > 0", file=sys.stderr)
        return 2
    if int(args.horizon) <= 0:
        print("[error] --horizon 必须 > 0", file=sys.stderr)
        return 2

    t0 = time.time()
    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    norm_mean, norm_std = meta.get("norm_mean"), meta.get("norm_std")
    print(f"[net] checkpoint={args.checkpoint} arch={meta.get('arch')} "
          f"norm={'on' if norm_mean is not None else 'off'}", flush=True)

    floors = _parse_floors(args.mmr_floors)
    _t = time.time()
    table = build_reference_table(str(args.reference_samples), floors=floors,
                                  limit=(int(args.reference_limit) or None))
    print(f"[ref] 人类动作分布: path={table.path} floors={list(floors)} "
          f"rows={ {int(k): int(v) for k, v in table.rows.items()} } "
          f"load={time.time() - _t:.1f}s", flush=True)
    if all(int(v) == 0 for v in table.rows.values()):
        print("[error] 参考动作分布为空（bc_samples 路径/MMR 过滤有问题）",
              file=sys.stderr)
        return 2

    cfg = ProblemCollectConfig(
        games=int(args.games), seed=int(args.seed), max_steps=int(args.max_steps),
        learner_seat=int(args.learner_seat), horizon=int(args.horizon),
        min_turn=int(args.min_turn),
        max_fork_per_turn=int(args.max_fork_per_turn),
        keep_turn_start=bool(int(args.keep_turn_start)),
        core_min_tier=int(args.core_min_tier),
        human_boards=str(args.human_boards),
        human_board_p=float(args.human_board_p),
        human_board_seats=int(args.human_board_seats),
        human_board_fidelity=str(args.human_board_fidelity),
        mirror_snaps=str(args.mirror_snaps),
        mirror_seats=int(args.mirror_seats),
        mirror_p=float(args.mirror_p),
        mirror_sample=str(args.mirror_sample),
        temperature=float(args.temperature),
        move_guard=bool(int(args.move_guard)),
        move_cap=int(args.move_cap),
        move_repeat_limit=int(args.move_repeat_limit),
        obs_dtype=str(args.obs_dtype))
    if int(args.limit_games) > 0:
        cfg.games = min(cfg.games, int(args.limit_games))

    result = collect_problems(
        model, cfg, device=str(args.device), reference=table,
        top_k=int(args.top_k), min_support=int(args.min_support),
        norm_mean=norm_mean, norm_std=norm_std, progress=True)
    if not result.problems:
        print("[error] 没有产出任何题目（rollout 太短/参考表为空？）", file=sys.stderr)
        return 2

    path, meta_path = write_problems(result, str(args.out),
                                     (str(args.stats_out) or None))
    with open(meta_path, "r", encoding="utf-8") as fh:
        stats = json.load(fh)
    stats["checkpoint"] = str(args.checkpoint)
    stats["checkpoint_arch"] = str(meta.get("arch"))
    stats["norm_applied"] = bool(norm_mean is not None)
    stats["reference"] = table.to_json()
    stats["total_seconds"] = round(time.time() - t0, 1)
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"[problems] wrote {len(result.problems)} problems -> {path} "
          f"(meta={meta_path}) in {time.time() - t0:.1f}s", flush=True)
    print(json.dumps({
        "problems": stats["problems"],
        "decisions": stats["decisions"],
        "turn_min": stats["turn_min"], "turn_max": stats["turn_max"],
        "by_turn": stats["by_turn"], "by_tag": stats["by_tag"],
        "ref_match_rate": round(float(stats["ref_match_rate"]), 4),
        "ref_missing_rate": round(float(stats["ref_missing_rate"]), 4),
        "ref_level": stats["ref_level"], "ref_floor": stats["ref_floor"],
        "ref_mass_legal_mean": round(float(stats["ref_mass_legal_mean"]), 4),
        "policy_top1_in_ref_rate": round(
            float(stats["policy_top1_in_ref_rate"]), 4),
        "label_available": stats["label_available"],
        "label_missing": stats["label_missing"],
        "tier_up_rate": round(float(stats["tier_up_rate"]), 4),
        "strength_p50": [round(float(stats["strength_before_p50"]), 1),
                         round(float(stats["strength_after_p50"]), 1)],
        "move_n_p50": stats["move_n_p50"], "move_n_max": stats["move_n_max"],
        "human_board_applied": int(
            (stats.get("human_board") or {}).get("human_board_applied", 0)),
        "human_board_attempt": int(
            (stats.get("human_board") or {}).get("human_board_attempt", 0)),
        "mirror_applied": int((stats.get("mirror") or {}).get("mirror_applied", 0)),
        "skipped": stats["skipped"],
    }, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
