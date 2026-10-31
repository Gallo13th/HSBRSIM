#!/usr/bin/env python3
"""独立 exam 配对评测：冻结 checkpoint × 独立 seed 面板（只评测，不训练）。

与 ``scripts/human_panel_eval.py`` **完全同口径**（复用其 ``_panel``）：board-only
人类战团注入、``--quantile auto``、512 局 = 8 seat × 64 局。唯一区别是：

- seed 面板来自**独立 exam 区块**（默认 730001 起，每面板 512 个连续 seed），
  与开发面板 seed 420000 不重叠；
- 同一面板内所有 checkpoint 用**同一批 game seed**，因此可按 seed/seat 配对；
- 不跑 engine-bot 基线（``baseline_bot=0``），配对基线是另一个 checkpoint（s9d）。

用法::

    P=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
    PYTHONPATH=rust/python:. $P scripts/exam_paired_eval.py \
        --ckpt s9d=runs/exam/ckpts/s9d.pt --ckpt s10_40M=runs/exam/ckpts/s10_40M.pt \
        --panel-seed-bases 730001,730513,731025,731537 \
        --device cuda:7 --shard 0 --nshards 4 --out-dir runs/exam

每个任务写 ``runs/exam/<name>_p<k>.json``；已存在且完整则跳过（可断点续跑）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import human_panel_eval as hpe  # noqa: E402
from hsbg.az.train.human_board_pool import load_pool  # noqa: E402


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _valid(path: str, seats: int, per_seat: int) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:  # noqa: BLE001
        return False
    ps = (d.get("details") or {}).get("per_seat") or {}
    if len(ps) != seats:
        return False
    for s in range(seats):
        row = ps.get(f"seat_{s}") or {}
        rms = (row.get("model") or {}).get("rank_sequence")
        if not rms or len(rms) != per_seat:
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="独立 exam 配对评测（human board 面板）")
    ap.add_argument("--ckpt", action="append", required=True,
                    help="name=path；可重复")
    ap.add_argument("--panel-seed-bases", default="730001,730513,731025,731537")
    ap.add_argument("--games", type=int, default=512)
    ap.add_argument("--seats", type=int, default=8)
    ap.add_argument("--quantile", default="auto")
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "runs", "exam"))
    ap.add_argument("--human-boards", default="")
    ap.add_argument("--arch", default="entity")
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--max-steps", type=int, default=50000)
    ap.add_argument("--max-actions-per-turn", type=int, default=40)
    ap.add_argument("--only", default="", help="逗号分隔的 name 子集（调试用）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.games % args.seats != 0:
        print("[exam:error] --games 必须能被 --seats 整除", file=sys.stderr)
        return 2
    per_seat = args.games // args.seats
    bases = [int(x) for x in str(args.panel_seed_bases).split(",") if str(x).strip()]
    ckpts: List[Dict[str, Any]] = []
    for spec in args.ckpt:
        name, _, path = spec.partition("=")
        if not path:
            name, path = os.path.basename(spec).replace(".pt", ""), spec
        path = path if os.path.isabs(path) else os.path.join(ROOT, path)
        ckpts.append({"name": name, "path": path})
    if args.only:
        keep = {s.strip() for s in str(args.only).split(",") if s.strip()}
        ckpts = [c for c in ckpts if c["name"] in keep]
    human_boards = str(args.human_boards or os.path.join(
        ROOT, "data", "real_library", "library_real_degraded.jsonl"))
    pool = load_pool(human_boards, sample=str(args.quantile))
    if pool is None:
        print(f"[exam:error] 人类战团池为空: {human_boards}", file=sys.stderr)
        return 2

    tasks = [(ci_ckpt, pi, base) for ci_ckpt in ckpts
             for pi, base in enumerate(bases)]
    tasks = [t for i, t in enumerate(tasks) if i % args.nshards == args.shard]
    os.makedirs(args.out_dir, exist_ok=True)
    print(f"[exam] shard={args.shard}/{args.nshards} device={args.device} "
          f"tasks={len(tasks)} pool_kept={pool.kept} quantile={args.quantile} "
          f"human_boards={human_boards}", flush=True)
    for c, pi, base in tasks:
        out = os.path.join(args.out_dir, f"{c['name']}_p{pi + 1}.json")
        if _valid(out, args.seats, per_seat):
            print(f"[exam] skip {os.path.basename(out)} (already complete)", flush=True)
            continue
        if args.dry_run:
            print(f"[exam] would run {c['name']} panel{pi + 1} seeds={base}"
                  f"..{base + args.games - 1}", flush=True)
            continue
        t0 = time.time()
        print(f"[exam] start {c['name']} panel{pi + 1} seed_base={base} "
              f"device={args.device}", flush=True)
        panel = hpe._panel(
            base, args.games, args.seats, per_seat,
            model_path=c["path"], arch=args.arch, device=args.device,
            bootstrap=args.bootstrap, max_steps=args.max_steps,
            max_actions_per_turn=args.max_actions_per_turn,
            pool=pool, quantile=str(args.quantile), baseline_bot=False,
            require_protocol=True, tag=f"{c['name']}_p{pi + 1}")
        payload = {
            "protocol": "exam_paired_v1",
            "panel": "human_board",
            "exam": True,
            "checkpoint_name": c["name"],
            "checkpoint": c["path"],
            "checkpoint_sha256": _sha256(c["path"]),
            "arch": args.arch,
            "device": args.device,
            "panel_index": pi + 1,
            "seed_base": int(base),
            "seed_range": [int(base), int(base) + args.games - 1],
            "games": int(args.games),
            "seats": int(args.seats),
            "per_seat": int(per_seat),
            "quantile": str(args.quantile),
            "human_boards": human_boards,
            "human_board_fidelity": "board",
            "baseline": "none (paired vs s9d checkpoint, not engine bot)",
            "wall_seconds": round(time.time() - t0, 1),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "model_mean_rank": panel.get("model_mean_rank"),
            "model_top4": panel.get("model_top4"),
            "model_win": panel.get("model_win"),
            "n": panel.get("n"),
            "passed": panel.get("passed"),
            "reasons": panel.get("reasons"),
            "illegal": panel.get("illegal"),
            "truncated": panel.get("truncated"),
            "truncated_combats": panel.get("truncated_combats"),
            "injection": panel.get("injection"),
            "model_decisions": panel.get("model_decisions"),
            "model_seconds": panel.get("model_seconds"),
            "details": panel.get("details"),
        }
        tmp = out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, out)
        print(f"[exam] done {os.path.basename(out)} "
              f"mean_rank={payload['model_mean_rank']} top4={payload['model_top4']} "
              f"win={payload['model_win']} n={payload['n']} "
              f"{payload['wall_seconds']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
