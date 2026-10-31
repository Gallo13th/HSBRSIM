#!/usr/bin/env python3
"""缩放策略四臂 A/B：A 现状 / B 金币课程 / C +教师 / D +过程价值。

从 s15 的 stage 起点权重出发，每臂 50 iteration（与 s15 相同的采集/PPO 口径），
训练后跑 `quality_monitor --games 192` 与 `human_panel_eval --games 256`。
所有产物在 ``runs/ab_scaling/``；每臂独立子进程 + 日志，可断点续跑（已有 >=iters
条 history 的臂会跳过训练）。

用法::

    nohup python scripts/run_scaling_ab.py > runs/ab_scaling/run.log 2>&1 &
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "runs", "ab_scaling")
START = os.path.join(OUT, "start_model.pt")
START_SRC = os.path.join(ROOT, "runs", "az_entity_s15", "snapshots",
                         "step_000301", "model.pt")
PY = sys.executable

#: 与 s15 当前 run 完全一致的公共参数（只留出被 A/B 的四个开关）
COMMON = [
    "--arch", "entity", "--device", "cuda:7",
    "--processes", "8", "--gpus", "7", "--threads", "8", "--games", "192",
    "--sims", "0", "--epochs", "1", "--minibatch", "1024", "--grad-accum", "8",
    "--amp", "bf16", "--lr", "1.2e-6", "--lr-min-ratio", "0.5",
    "--max-updates", "3000", "--clip", "0.2", "--target-kl", "0.02",
    "--lam", "0.995", "--max-grad-norm", "1.0", "--entropy-coef", "0.001",
    "--pi-coef", "0.0", "--anchor-beta", "0.1", "--anchor-iterations", "200",
    "--anchor-beta-tail", "0.02", "--compile-train", "1", "--anchor-amp", "1",
    "--pipeline", "1", "--lockstep", "1", "--leaf-wait-ms", "0",
    "--human-board-fast-inject", "1", "--archetype-cache", "0",
    "--shaping-coef", "0", "--move-guard", "1", "--move-cap", "3",
    "--move-repeat-limit", "2", "--archetype-bias-coef", "0.5",
    "--archetype-min-prob", "0.6",
    "--mirror-snaps", "runs/library/snaps_champ", "--mirror-seats", "2",
    "--mirror-p", "0.2", "--mirror-sample", "p75", "--mirror-seat-random", "1",
    "--human-boards", "data/real_library/library_real_quasi_full.jsonl",
    "--human-board-fidelity", "full", "--human-board-p", "0.9",
    "--human-board-seats", "5", "--human-board-sample", "auto",
    "--human-board-set-tier", "1",
    "--seq-coef", "0.05", "--bc-coef", "0.004", "--bc-type-weight", "1.0",
    "--bc-card-weight", "0.5", "--bc-batch", "128", "--bc-every", "4",
    "--bc-compile", "1", "--dpo-coef", "0.02", "--dpo-every", "1",
    "--dpo-beta", "0.1", "--dpo-batch", "128",
    "--gpu-free-check", "0", "--seed", "21100",
    "--eval-every-decisions", "100000000",
    "--snapshot-every", "10", "--keep-snapshots", "2",
]

ARMS = {
    "A": [],
    "B": ["--curriculum-stage", "warmup", "--curriculum-gold-mult", "3.0",
          "--curriculum-anneal-decisions", "10000000"],
    "C": ["--curriculum-stage", "warmup", "--curriculum-gold-mult", "3.0",
          "--curriculum-anneal-decisions", "10000000",
          "--teacher-bc-coef", "0.02"],
    "D": ["--curriculum-stage", "warmup", "--curriculum-gold-mult", "3.0",
          "--curriculum-anneal-decisions", "10000000",
          "--teacher-bc-coef", "0.02", "--process-value-coef", "0.05"],
}


def _run(cmd, log_path, timeout=7200):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    t0 = time.time()
    with open(log_path, "a", encoding="utf-8") as log:
        log.write("\n$ " + " ".join(cmd) + "\n")
        log.flush()
        p = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           timeout=timeout)
    print(f"[run] rc={p.returncode} {time.time() - t0:.0f}s -> {log_path}",
          flush=True)
    return p.returncode


def _history_iters(path):
    n = 0
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if "iter" in r:
                n += 1
    return n


def _quality_summary(path):
    if not os.path.isfile(path):
        return {}
    d = json.load(open(path, encoding="utf-8"))
    rows = {int(r["turn"]): r for r in d.get("by_turn", [])}
    out = {"games": d.get("games"), "mean_rank": d.get("mean_rank"),
           "top4": d.get("top4"), "win": d.get("win"),
           "death_turn_p50": d.get("death_turn_p50"),
           "death_strength_p50": d.get("death_strength_p50")}
    for t in (12, 13, 14, 15):
        r = rows.get(t) or {}
        out[f"ratio_t{t}"] = r.get("ratio_p50")
        out[f"ours_t{t}"] = r.get("ours_p50")
    out["tier_p50_t12"] = d.get("tier_p50_t12")
    return out


def _human_summary(path):
    if not os.path.isfile(path):
        return {}
    d = json.load(open(path, encoding="utf-8"))
    p = (d.get("panels") or [{}])[0]
    inj = p.get("injection") or {}
    return {"model_mean_rank": p.get("model_mean_rank"),
            "model_top4": p.get("model_top4"),
            "model_win": p.get("model_win"),
            "illegal": p.get("illegal"), "truncated": p.get("truncated"),
            "passed": p.get("passed"),
            "human_applied": inj.get("human_board_applied"),
            "human_attempt": inj.get("human_board_attempt")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=50)
    ap.add_argument("--arms", default="A,B,C,D")
    ap.add_argument("--skip-eval", type=int, default=0)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    if not os.path.isfile(START):
        if not os.path.isfile(START_SRC):
            print(f"[error] start checkpoint 不存在: {START_SRC}", file=sys.stderr)
            return 2
        subprocess.run(["cp", START_SRC, START], check=True)
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    summary_path = os.path.join(OUT, "summary.jsonl")
    for arm in arms:
        if arm not in ARMS:
            print(f"[warn] 未知臂 {arm}", file=sys.stderr)
            continue
        arm_dir = os.path.join(OUT, f"arm{arm}")
        hist = os.path.join(arm_dir, "history.jsonl")
        n_hist = _history_iters(hist)
        if n_hist < args.iters:
            os.makedirs(arm_dir, exist_ok=True)
            cmd = [PY, os.path.join(ROOT, "scripts", "train_entity_sync.py"),
                   "--checkpoint", START,
                   "--iterations", str(int(args.iters)),
                   "--minutes", "120",
                   "--out", arm_dir] + COMMON + ARMS[arm]
            print(f"[arm {arm}] train: history={n_hist} < {args.iters}", flush=True)
            rc = _run(cmd, os.path.join(OUT, f"train_{arm}.log"))
            if rc != 0:
                print(f"[arm {arm}] train failed rc={rc}", file=sys.stderr)
                return rc
        else:
            print(f"[arm {arm}] skip train (history={n_hist})", flush=True)
        model = os.path.join(arm_dir, "model.pt")
        if int(args.skip_eval):
            continue
        q_out = os.path.join(OUT, f"quality_{arm}.json")
        h_out = os.path.join(OUT, f"human_{arm}.json")
        if not os.path.isfile(q_out):
            qcmd = [PY, os.path.join(ROOT, "scripts", "quality_monitor.py"),
                    "--checkpoint", model, "--device", "cuda:7",
                    "--games", "192", "--seed-base", "520000",
                    "--policy", "selfplay", "--out", q_out]
            _run(qcmd, os.path.join(OUT, f"quality_{arm}.log"), timeout=3600)
        if not os.path.isfile(h_out):
            hcmd = [PY, os.path.join(ROOT, "scripts", "human_panel_eval.py"),
                    "--checkpoint", model, "--arch", "entity", "--device", "cuda:7",
                    "--games", "256", "--seats", "8", "--seed-base", "420000",
                    "--smoke", "--quantile", "auto", "--bootstrap", "1000",
                    "--baseline-bot", "0", "--out", h_out]
            _run(hcmd, os.path.join(OUT, f"human_{arm}.log"), timeout=3600)
        rec = {"arm": arm, "iters": int(args.iters),
               "quality": _quality_summary(q_out),
               "human": _human_summary(h_out),
               "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print("[summary] " + json.dumps(rec, ensure_ascii=False), flush=True)
    print("[done]", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
