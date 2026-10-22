"""策略评测入口：加载 checkpoint，跑 ``--games`` 局，打印平均名次/胜率/前四率。

示例::

    python scripts/evaluate_policy.py --checkpoint runs/smoke_ppo/policy_final.pt \
        --games 16 --baseline heuristic

会同时评测**训练策略**与**基线**（``random`` / ``heuristic``），输出对照表，
便于判断策略是否真的优于随机/脚本对手。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from hsbg.policy.model import load_policy_and_encoder
from hsbg.train.evaluate import evaluate_agent, make_agent
from hsbg.train.logger import format_metrics_table, write_json
from hsbg.train.setup import (
    describe_env,
    env_kwargs_for_real,
    resolve_device,
    resolve_out_dir,
    seed_everything,
)
from hsbg.train.vec_env import make_vec_env


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="评测策略 checkpoint（平均名次 / 胜率 / 前四率）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--checkpoint", required=True, help="策略 checkpoint 路径")
    p.add_argument("--games", type=int, default=16, help="评测局数")
    p.add_argument("--baseline", default="heuristic", choices=["random", "heuristic", "none"],
                   help="对照基线（none=只评策略）")
    p.add_argument("--num-envs", type=int, default=2, help="并行环境数")
    p.add_argument("--env", default="auto", choices=["auto", "mock", "real"])
    p.add_argument("--opponent", default="heuristic", help="真环境对手策略名")
    p.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "cuda:0", "cuda:1"])
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--sample", action="store_true", help="按概率采样动作（默认贪心）")
    p.add_argument("--num-players", type=int, default=8)
    p.add_argument("--max-steps-per-episode", type=int, default=800,
                   help="单局步数上限；超限按最差名次记负场（防策略死循环）")
    p.add_argument("--out", default=None, help="可选：结果 JSON/CSV 输出目录")
    return p


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    started = time.time()
    seed_everything(args.seed)
    device = resolve_device(args.device)
    checkpoint = Path(args.checkpoint)
    if not checkpoint.is_absolute() and not checkpoint.exists():
        checkpoint = _ROOT / checkpoint
    if not checkpoint.exists():
        raise SystemExit(f"checkpoint 不存在: {args.checkpoint}")

    policy, encoder = load_policy_and_encoder(checkpoint, map_location="cpu")
    policy.to(device)
    print(f"[evaluate] checkpoint={checkpoint}")
    print(f"[evaluate] params={policy.count_parameters():,} vocab={len(encoder.vocab)} "
          f"device={device} greedy={not args.sample}")

    env_kwargs = env_kwargs_for_real(args.opponent) if args.env != "mock" else None
    env = make_vec_env(args.num_envs, mode=args.env, seed=args.seed, env_kwargs=env_kwargs)
    print(f"[evaluate] env={describe_env(env)}  games={args.games}")

    rows = []
    results = {}
    try:
        policy_agent = make_agent(
            "policy", policy=policy, encoder=encoder,
            device=device, greedy=not args.sample,
        )
        names = [("policy", policy_agent)]
        if args.baseline != "none":
            names.append((args.baseline, make_agent(args.baseline, seed=args.seed)))
        for name, agent in names:
            t0 = time.time()
            result = evaluate_agent(
                agent, env, games=args.games, num_players=args.num_players,
                seed=args.seed,
                max_steps_per_episode=args.max_steps_per_episode,
            )
            row = {"agent": name, **result.as_dict(), "wall_s": round(time.time() - t0, 2)}
            rows.append(row)
            results[name] = row
            print(f"[evaluate] {name}: {result.format()}  ({row['wall_s']}s)")
    finally:
        env.close()

    print("\n[evaluate] 结果表")
    print(format_metrics_table(rows))

    if args.baseline != "none" and "policy" in results and args.baseline in results:
        p = results["policy"]
        b = results[args.baseline]
        if b["mean_rank"] > 0 and p["games"] > 0:
            delta = (b["mean_rank"] - p["mean_rank"]) / b["mean_rank"] * 100.0
            better = p["mean_rank"] <= b["mean_rank"]
            note = ""
            if p.get("timeout_games"):
                note = f"（其中 {p['timeout_games']} 局超时判负，说明策略可能不会 end_turn）"
            print(
                f"\n  策略 vs {args.baseline}: 平均名次 {p['mean_rank']:.3f} vs "
                f"{b['mean_rank']:.3f}（相对改善 {delta:+.1f}%），"
                f"{'策略更优' if better else '策略更差'}{note}"
            )
    if args.out:
        out_dir = resolve_out_dir(args.out)
        write_json(out_dir / "eval_results.json", {
            "checkpoint": str(checkpoint),
            "env": describe_env(env),
            "games": args.games,
            "greedy": not args.sample,
            "seed": args.seed,
            "results": rows,
            "wall_time_s": time.time() - started,
        })
        print(f"\n  结果已写入 {out_dir / 'eval_results.json'}")
    print(f"\n[evaluate] 总耗时 {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
