#!/usr/bin/env python3
"""监听训练目录的 5M 评测 ckpt，对每个 ckpt 跑 ``quality_monitor``（质量面板）。

训练入口（``scripts/train_entity_sync.py``）在 ``--eval-every-decisions`` 到点时会把
当刻权重落成 ``<out>/eval/ckpt_<decisions:09d>.pt`` 再异步跑 human 面板。本脚本只做
「发现 ckpt → 跑质量面板」，不碰训练进程：

    PYTHONPATH=rust/python:. python scripts/quality_watch.py \
        --out-dir runs/az_entity_s19 --games 96 --device cuda:2 \
        --thresholds 5000000,10000000 --max-wait-min 400

产物：``<out>/quality/quality_<tag>.json`` 与同名 ``.log``。已存在的 json 会跳过，
因此可以随时重启本脚本。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse_thresholds(spec: str) -> list:
    out = []
    for tok in str(spec or "").replace(" ", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        mult = 1
        if tok[-1] in "Mm":
            mult, tok = 10 ** 6, tok[:-1]
        elif tok[-1] in "Kk":
            mult, tok = 10 ** 3, tok[:-1]
        out.append(int(float(tok) * mult))
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, help="训练输出目录（含 eval/）")
    ap.add_argument("--thresholds", default="5000000,10000000",
                    help="按累计 decisions 的目标 ckpt（逗号分隔，支持 5M/10M）")
    ap.add_argument("--games", type=int, default=96)
    ap.add_argument("--seats", type=int, default=8)
    ap.add_argument("--seed-base", type=int, default=520000)
    ap.add_argument("--device", default="cuda:2")
    ap.add_argument("--poll", type=float, default=30.0, help="轮询间隔秒")
    ap.add_argument("--max-wait-min", type=float, default=400.0)
    ap.add_argument("--carrier-audit", type=int, default=1)
    ap.add_argument("--python", default=sys.executable)
    args = ap.parse_args()

    out = os.path.abspath(args.out_dir)
    qdir = os.path.join(out, "quality")
    os.makedirs(qdir, exist_ok=True)
    todo = _parse_thresholds(args.thresholds)
    print(f"[quality-watch] out={out} thresholds={todo} games={args.games} "
          f"device={args.device}", flush=True)
    # 训练侧 ckpt 名是「触发时刻的累计 decisions」（如 ckpt_010028407.pt），不是整 5M；
    # 因此按「第一个 ≥ 阈值的 ckpt」匹配（允许 1M 的越界窗口）。
    def _pick_ckpt(threshold: int):
        ed = os.path.join(out, "eval")
        if not os.path.isdir(ed):
            return None, None
        tags = []
        for fn in os.listdir(ed):
            if fn.startswith("ckpt_") and fn.endswith(".pt"):
                try:
                    tags.append(int(fn[5:-3]))
                except ValueError:
                    continue
        cand = sorted(t for t in tags if threshold <= t <= threshold + 1_000_000)
        if not cand:
            return None, None
        t = cand[0]
        return f"{t:09d}", os.path.join(ed, f"ckpt_{t:09d}.pt")

    t0 = time.time()
    while todo:
        for th in list(todo):
            tag, ckpt = _pick_ckpt(int(th))
            if ckpt is None:
                continue
            dst = os.path.join(qdir, f"quality_{tag}.json")
            if os.path.isfile(dst):
                todo.remove(th)
                continue
            cmd = [str(args.python), os.path.join(ROOT, "scripts", "quality_monitor.py"),
                   "--checkpoint", ckpt,
                   "--arch", "entity", "--device", str(args.device),
                   "--games", str(int(args.games)),
                   "--seed-base", str(int(args.seed_base)),
                   "--carrier-audit", str(int(args.carrier_audit)),
                   "--out", dst]
            log = os.path.join(qdir, f"quality_{tag}.log")
            print(f"[quality-watch] dec={tag} -> {dst}", flush=True)
            t1 = time.time()
            with open(log, "w", encoding="utf-8") as lf:
                rc = subprocess.call(cmd, cwd=ROOT, stdout=lf, stderr=lf, env=dict(
                    os.environ, PYTHONPATH=os.path.join(ROOT, "rust", "python")
                    + os.pathsep + ROOT))
            print(f"[quality-watch] dec={tag} rc={rc} "
                  f"({time.time() - t1:.0f}s)", flush=True)
            todo.remove(th)   # 失败也移出（日志里看原因），避免死循环
        if not todo:
            break
        if (time.time() - t0) / 60.0 > float(args.max_wait_min):
            print(f"[quality-watch] 超过 max-wait-min={args.max_wait_min}，剩余 {todo}",
                  flush=True)
            return 1
        time.sleep(float(args.poll))
    print("[quality-watch] done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
