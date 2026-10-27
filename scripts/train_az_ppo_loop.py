#!/usr/bin/env python3
"""按时长循环运行 MCTS-guided PPO（当前流程），每 N 轮评测并保存历史。

每一步调用 scripts/train_az_ppo.py：
    采集（MCTS 引导自对弈 / vs bot） -> PPO -> checkpoint
外层只负责：
    - 时间预算（默认 60 分钟）
    - checkpoint 续训
    - 每 eval_every 轮固定 seed 评测（net vs 7 引擎 bot）
    - history/summary JSON

示例（1h）：
    python scripts/train_az_ppo_loop.py --minutes 60 --games 16 --arch tiny \
      --device cuda --sims 4 --opponent bot --epochs 2 --minibatch 256 \
      --lr 3e-4 --target-kl 0.1 --no-kl-early-stop --eval-every 5 \
      --eval-games 30 --out runs/az_ppo_1h
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.model import build_net, save_checkpoint  # noqa: E402


def _run(cmd: List[str], log: str, timeout: int = 900) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(log)) or ".", exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write("\n$ " + " ".join(cmd) + "\n")
        f.flush()
        try:
            proc = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                                  text=True, timeout=timeout)
            return int(proc.returncode)
        except subprocess.TimeoutExpired:
            f.write(f"\n[timeout] {timeout}s\n")
            return -9


def _load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description="按时长循环 MCTS-guided PPO")
    ap.add_argument("--minutes", type=float, default=60.0)
    ap.add_argument("--iterations", type=int, default=0)
    ap.add_argument("--games", type=int, default=16)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--arch", default="tiny", choices=["tiny", "entity", "entity18m"])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--sims", type=int, default=4)
    ap.add_argument("--determinizations", type=int, default=1)
    ap.add_argument("--opponent", default="bot", choices=["bot", "self"])
    ap.add_argument("--behavior", default="net", choices=["net", "mcts", "mixed"])
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--minibatch", type=int, default=256)
    ap.add_argument("--target-kl", type=float, default=0.1)
    ap.add_argument("--no-kl-early-stop", action="store_true")
    ap.add_argument("--pi-coef", type=float, default=0.5)
    ap.add_argument("--entropy-coef", type=float, default=0.005)
    ap.add_argument("--max-actions-per-turn", type=int, default=40)
    ap.add_argument("--eval-every", type=int, default=5)
    ap.add_argument("--eval-games", type=int, default=30)
    ap.add_argument("--final-games", type=int, default=16,
                    help="最终逐 seat 评测的每 seat 局数（8×该值）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="runs/az_ppo_1h")
    args = ap.parse_args()
    args.out = os.path.abspath(args.out)

    os.makedirs(args.out, exist_ok=True)
    current = os.path.join(args.out, "current")
    ckpt_dir = os.path.join(args.out, "checkpoints")
    os.makedirs(current, exist_ok=True)
    os.makedirs(ckpt_dir, exist_ok=True)
    history_path = os.path.join(args.out, "history.json")
    log_path = os.path.join(args.out, "train.log")
    history: List[Dict[str, Any]] = []
    t0 = time.time()
    deadline = t0 + float(args.minutes) * 60.0

    # 初始模型（未训练）+ 逐 seat 评测，作为配对基线
    initial_ckpt = os.path.join(args.out, "initial_model.pt")
    if not os.path.isfile(initial_ckpt):
        init_model = build_net(256, arch=args.arch)
        save_checkpoint(init_model, initial_ckpt, meta={"arch": args.arch})
    initial_dir = os.path.join(args.out, "eval_initial")
    os.makedirs(initial_dir, exist_ok=True)
    for seat in range(8):
        ev_path = os.path.join(initial_dir, f"seat_{seat}.json")
        if not os.path.isfile(ev_path):
            _run([sys.executable, "scripts/eval_az_checkpoint.py",
                  "--checkpoint", initial_ckpt, "--arch", args.arch,
                  "--device", args.device, "--games", str(args.final_games),
                  "--seed", "90000", "--policy-seat", str(seat),
                  "--out", ev_path], log_path, timeout=600)

    # 基线（只跑一次）
    base_path = os.path.join(args.out, "baseline.json")
    if not os.path.isfile(base_path):
        cmd = [sys.executable, "scripts/eval_az_checkpoint.py",
               "--policy", "random", "--games", str(args.eval_games),
               "--seed", "90000", "--out", base_path]
        _run(cmd, log_path)
        cmd = [sys.executable, "scripts/eval_az_checkpoint.py",
               "--policy", "bot", "--games", str(args.eval_games),
               "--seed", "90000", "--out",
               os.path.join(args.out, "baseline_bot.json")]
        _run(cmd, log_path)

    i = 0
    last_iter_seconds = 0.0
    while time.time() < deadline:
        if args.iterations > 0 and i >= args.iterations:
            break
        # 预留一个完整迭代的时间，避免最后一轮严重越界
        if last_iter_seconds > 0 and (deadline - time.time()) < max(90.0, last_iter_seconds):
            print("[loop] 剩余时间不足一个迭代，停止采集", flush=True)
            break
        ckpt = os.path.join(current, "model.pt")
        if not os.path.isfile(ckpt):
            ckpt = initial_ckpt
        cmd = [sys.executable, "scripts/train_az_ppo.py",
               "--games", str(args.games), "--epochs", str(args.epochs),
               "--arch", args.arch, "--device", args.device,
               "--sims", str(args.sims),
               "--determinizations", str(args.determinizations),
               "--opponent", args.opponent, "--behavior", args.behavior,
               "--lr", str(args.lr), "--clip", str(args.clip),
               "--minibatch", str(args.minibatch),
               "--target-kl", str(args.target_kl),
               "--pi-coef", str(args.pi_coef),
               "--entropy-coef", str(args.entropy_coef),
               "--max-actions-per-turn", str(args.max_actions_per_turn),
               "--seed", str(int(args.seed) + i * 1000),
               "--out", current, "--eval-games", "0"]
        if args.no_kl_early_stop:
            cmd.append("--no-kl-early-stop")
        if ckpt:
            cmd += ["--checkpoint", ckpt]
        print(f"[loop] iter {i:04d}  t={time.time()-t0:.0f}s", flush=True)
        rc = _run(cmd, log_path, timeout=max(300, int(6 * args.games * 60)))
        rep = _load_json(os.path.join(current, "report.json"))
        rec: Dict[str, Any] = {"iter": i, "rc": rc,
                               "seconds": time.time() - t0,
                               "collect": rep.get("collect"),
                               "ppo": rep.get("ppo"),
                               "data": rep.get("data")}
        if rc != 0:
            print(f"[loop] iter {i} failed rc={rc}; stop", flush=True)
            history.append(rec)
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump({"minutes": args.minutes, "elapsed_s": time.time() - t0,
                           "args": vars(args), "history": history, "failed": True},
                          f, ensure_ascii=False, indent=2)
            return 1
        ckpt_after = os.path.join(current, "model.pt")
        if os.path.isfile(ckpt_after):
            tmp = os.path.join(ckpt_dir, f".iter_{i:04d}.pt.tmp")
            shutil.copy2(ckpt_after, tmp)
            os.replace(tmp, os.path.join(ckpt_dir, f"iter_{i:04d}.pt"))
        # 周期性评测（首轮不存在的 ckpt 已在训练后产生）
        if args.eval_every > 0 and (i + 1) % args.eval_every == 0 and os.path.isfile(ckpt_after):
            ev_path = os.path.join(args.out, f"eval_iter_{i:04d}.json")
            if os.path.isfile(ev_path):
                os.unlink(ev_path)
            cmd = [sys.executable, "scripts/eval_az_checkpoint.py",
                   "--checkpoint", ckpt_after, "--arch", args.arch,
                   "--device", args.device, "--games", str(args.eval_games),
                   "--seed", "90000", "--out", ev_path]
            _run(cmd, log_path, timeout=600)
            ev = _load_json(ev_path)
            rec["eval"] = ev.get("results", {})
            net = (ev.get("results") or {}).get("net") or {}
            print(f"[loop] iter {i} eval mean_rank={net.get('mean_rank')} "
                  f"top4={net.get('top4_rate')}", flush=True)
        history.append(rec)
        last_iter_seconds = float(rec.get("seconds", 0) - (history[-2].get("seconds", 0) if len(history) > 1 else 0))
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump({"minutes": args.minutes, "elapsed_s": time.time() - t0,
                       "args": vars(args), "history": history}, f,
                      ensure_ascii=False, indent=2)
        i += 1

    # 最终评测：last checkpoint + baseline
    final_ckpt = os.path.join(current, "model.pt")
    summary: Dict[str, Any] = {"elapsed_s": time.time() - t0, "iterations": i,
                               "history": history,
                               "args": vars(args)}
    if os.path.isfile(final_ckpt):
        final_dir = os.path.join(args.out, "eval_final")
        os.makedirs(final_dir, exist_ok=True)
        final = {}
        for seat in range(8):
            final_path = os.path.join(final_dir, f"seat_{seat}.json")
            if os.path.isfile(final_path):
                os.unlink(final_path)
            _run([sys.executable, "scripts/eval_az_checkpoint.py",
                  "--checkpoint", final_ckpt, "--arch", args.arch,
                  "--device", args.device, "--games", str(args.final_games),
                  "--seed", "90000", "--policy-seat", str(seat),
                  "--out", final_path], log_path, timeout=600)
            final[f"seat_{seat}"] = _load_json(final_path)
        summary["final"] = final
        ranks = []
        for v in final.values():
            ranks.extend(((v.get("results") or {}).get("net") or {}).get("rank_sequence", []))
        if ranks:
            summary["final_mean_rank"] = sum(ranks) / len(ranks)
    initial_ranks = []
    for v in (summary.get("initial_eval") or {}).values():
        initial_ranks.extend(((v.get("results") or {}).get("net") or {}).get("rank_sequence", []))
    if not initial_ranks:
        for pth in sorted(glob.glob(os.path.join(initial_dir, "seat_*.json"))):
            initial_ranks.extend((_load_json(pth).get("results", {}).get("net", {})
                                  .get("rank_sequence", [])))
    if initial_ranks:
        summary["initial_mean_rank"] = sum(initial_ranks) / len(initial_ranks)
    summary["elapsed_s"] = time.time() - t0
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"[loop] done iterations={i} elapsed={summary['elapsed_s']:.0f}s -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
