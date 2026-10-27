#!/usr/bin/env python3
"""stage-1（KL anchor + sims=0 + 30M）训练曲线与评测汇总。

读取 `runs/<run>/eval/history.json` 与 `runs/<run>/history.json`，输出：
- 评测表（mean rank / top4 / win / 配对 Δ vs 基线，若有 paired_5M 文件）；
- 一条 PNG（左：C0 mean rank 曲线；右：collect decisions/s 与 PPO KL）。

用法：
  python scripts/analyze_stage1.py --run runs/az_entity_kl_30m
"""

from __future__ import annotations

import argparse
import json
import os
import time


def _load(path: str, retries: int = 5):
    for _ in range(retries):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            time.sleep(1.0)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/az_entity_kl_30m")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    run = args.run
    ev = _load(os.path.join(run, "eval", "history.json")) or {"evals": []}
    hist = _load(os.path.join(run, "history.json")) or {"history": []}

    print(f"== {run} ==")
    print("-- 512-game C0 evals (seed_base 420000) --")
    print(f"{'decisions':>10s} {'mean_rank':>9s} {'bot':>6s} {'top4':>6s} {'win':>6s} {'sec':>6s}")
    for r in ev.get("evals", []):
        if r.get("mean_rank") is None:
            print(f"{r['decisions']:>10d}   FAILED rc={r.get('rc')}")
            continue
        print(f"{r['decisions']:>10d} {r['mean_rank']:>9.4f} {r['bot_mean_rank']:>6.3f} "
              f"{r['top4']:>6.3f} {r['win']:>6.3f} {r['seconds']:>6.1f}")

    h = hist.get("history", [])
    if h:
        dec = sum(x["collect"]["decisions"] for x in h)
        print(f"\n-- training: {len(h)} iters, {dec/1e6:.2f}M decisions, "
              f"elapsed {h[-1]['seconds']/60:.0f} min --")
        win = h[-20:]
        print(f"last20 iter: samples/iter={sum(x['ppo']['samples'] for x in win)/len(win):.0f} "
              f"collect_dec/s={sum(x['collect']['decisions_per_s'] for x in win)/len(win):.0f} "
              f"kl={sum(x['ppo']['epochs'][0]['approx_kl'] for x in win)/len(win):.5f} "
              f"ent={sum(x['ppo']['epochs'][0]['entropy'] for x in win)/len(win):.4f} "
              f"val={sum(x['ppo']['epochs'][0]['value_loss'] for x in win)/len(win):.4f}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] matplotlib 不可用，跳过绘图: {exc!r}")
        return 0

    evs = [r for r in ev.get("evals", []) if r.get("mean_rank") is not None]
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    if evs:
        xs = [r["decisions"] / 1e6 for r in evs]
        ax[0].plot(xs, [r["mean_rank"] for r in evs], "o-", label="model mean rank")
        ax[0].plot(xs, [r["bot_mean_rank"] for r in evs], "s--", label="engine bot")
        ax[0].set_xlabel("training decisions (M)")
        ax[0].set_ylabel("C0 mean rank (lower better)")
        ax[0].set_title("C0 512-game eval")
        ax[0].legend()
        ax[0].grid(alpha=0.3)
    if h:
        xs = []
        acc = 0
        dps, kls = [], []
        for x in h:
            acc += x["collect"]["decisions"]
            xs.append(acc / 1e6)
            dps.append(x["collect"]["decisions_per_s"])
            kls.append(x["ppo"]["epochs"][0]["approx_kl"])
        ax[1].plot(xs, dps, lw=0.8, label="collect dec/s")
        ax[1].set_xlabel("training decisions (M)")
        ax[1].set_ylabel("decisions/s")
        ax2 = ax[1].twinx()
        ax2.plot(xs, kls, "r-", lw=0.8, alpha=0.7, label="approx KL")
        ax2.set_ylabel("approx KL")
        ax[1].set_title("throughput and KL")
        ax[1].grid(alpha=0.3)
    fig.tight_layout()
    out = args.out or os.path.join(run, "eval", "stage1_curves.png")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fig.savefig(out, dpi=130)
    print(f"[plot] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
