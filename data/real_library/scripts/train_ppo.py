"""PPO 训练入口（可在真环境/Mock 环境上跑）。

示例::

    python scripts/train_ppo.py --total-steps 3000 --num-envs 2 --device cpu \
        --out runs/smoke_ppo

产物（``--out`` 目录下）：
``policy_final.pt``（checkpoint，含策略 config/词表/PPO config）、
``train_log.csv``、``eval_log.csv``（若启用评测）、``summary.json``。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 允许直接 `python scripts/train_ppo.py`（把仓库根加入 sys.path）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from hsbg.policy.encoder import collect_card_ids
from hsbg.policy.model import build_policy, load_policy_and_encoder
from hsbg.train.logger import format_metrics_table
from hsbg.train.ppo import PPOConfig, PPOTrainer
from hsbg.train.setup import (
    build_encoder,
    describe_env,
    env_kwargs_for_real,
    resolve_device,
    resolve_out_dir,
    seed_everything,
)
from hsbg.train.vec_env import MockVecEnv, make_vec_env


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="PPO 训练酒馆战棋策略（候选动作 masked softmax）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # 运行规模
    p.add_argument("--total-steps", type=int, default=3000, help="总环境交互步数")
    p.add_argument("--num-envs", type=int, default=2, help="并行环境数")
    p.add_argument("--n-steps", type=int, default=256, help="每轮 rollout 每环境步数")
    p.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "cuda:0", "cuda:1"])
    p.add_argument("--out", default="runs/ppo", help="输出目录（相对仓库根）")
    p.add_argument("--seed", type=int, default=0)
    # 环境
    p.add_argument("--env", default="auto", choices=["auto", "mock", "real"],
                   help="auto=真 env 可用就用，否则 Mock")
    p.add_argument("--opponent", default="heuristic", help="真环境的对手策略名")
    # 优化
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--epochs", type=int, default=4, help="PPO 更新 epoch 数")
    p.add_argument("--minibatch-size", type=int, default=256)
    p.add_argument("--gamma", type=float, default=0.99)
    p.add_argument("--lam", type=float, default=0.95)
    p.add_argument("--clip", type=float, default=0.2)
    p.add_argument("--entropy-coef", type=float, default=0.01)
    p.add_argument("--value-coef", type=float, default=0.5)
    p.add_argument("--rank-ce-coef", type=float, default=0.5)
    p.add_argument("--target-kl", type=float, default=0.02)
    p.add_argument("--max-grad-norm", type=float, default=0.5)
    p.add_argument("--reward-scale", type=float, default=1.0)
    # 奖励塑形覆盖（None = 用 hsbg.env.spec.RewardConfig 默认值）。
    # 稀疏终局奖励场景建议: --reward-placement 2.0 --reward-health 0.005
    # --reward-combat 0.005 --reward-board 0.0005 --gamma 0.995
    p.add_argument("--reward-placement", type=float, default=None)
    p.add_argument("--reward-health", type=float, default=None)
    p.add_argument("--reward-combat", type=float, default=None)
    p.add_argument("--reward-board", type=float, default=None)
    # 模型
    p.add_argument("--dim", type=int, default=128)
    p.add_argument("--layers", type=int, default=4)
    p.add_argument("--heads", type=int, default=4)
    p.add_argument("--ff-dim", type=int, default=256)
    p.add_argument("--value-mode", default="distribution", choices=["distribution", "scalar"])
    # 周期性动作
    p.add_argument("--eval-every", type=int, default=0, help="每 N 步评测一次（0=关闭）")
    p.add_argument("--eval-games", type=int, default=8)
    p.add_argument("--save-every", type=int, default=0, help="每 N 步保存 checkpoint（0=仅末尾）")
    p.add_argument("--init-from", default=None, help="从已有 checkpoint 续训")
    p.add_argument("--data-dir", default=None, help="卡牌数据目录（默认 data/）")
    p.add_argument("--quiet", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    started = time.time()
    seed_everything(args.seed)  # 训练可复现：python/numpy/torch 全局播种
    device = resolve_device(args.device)
    out_dir = resolve_out_dir(args.out)

    # ── 环境 ──
    env_kwargs = env_kwargs_for_real(args.opponent) if args.env != "mock" else None
    if env_kwargs is not None:
        reward_overrides = {}
        if args.reward_placement is not None:
            reward_overrides["placement"] = args.reward_placement
        if args.reward_health is not None:
            reward_overrides["health_delta"] = args.reward_health
        if args.reward_combat is not None:
            reward_overrides["combat_damage"] = args.reward_combat
        if args.reward_board is not None:
            reward_overrides["board_power_delta"] = args.reward_board
        if reward_overrides:
            env_kwargs["reward"] = reward_overrides
            print(f"[train_ppo] reward overrides = {reward_overrides}")
    env = make_vec_env(args.num_envs, mode=args.env, seed=args.seed, env_kwargs=env_kwargs)
    env_desc = describe_env(env)
    is_mock = isinstance(env, MockVecEnv)
    print(f"[train_ppo] env = {env_desc}  device = {device}  out = {out_dir}")

    # ── 观测探针：动态补充词表（真环境里可能有 data/ 未收录的卡）──
    probe = list(env.reset())

    # ── 模型 / 编码器 ──
    if args.init_from:
        policy, encoder = load_policy_and_encoder(args.init_from)
        ids = set()
        for obs in probe:
            ids |= collect_card_ids(obs)
        new_ids = sorted(cid for cid in ids if cid not in encoder.vocab)
        if new_ids:
            encoder.vocab.extend(new_ids)
            policy.resize_card_embedding(encoder.vocab)
        print(f"[train_ppo] 续训自 {args.init_from}（新增卡 {len(new_ids)}）")
    else:
        encoder = build_encoder(data_dir=args.data_dir, observations=probe)
        policy = build_policy(
            encoder,
            dim=args.dim,
            layers=args.layers,
            heads=args.heads,
            ff_dim=args.ff_dim,
            value_mode=args.value_mode,
        )
    print(f"[train_ppo] vocab={len(encoder.vocab)} params={policy.count_parameters():,}")

    # ── 训练配置 ──
    config = PPOConfig(
        lr=args.lr,
        gamma=args.gamma,
        lam=args.lam,
        clip=args.clip,
        entropy_coef=args.entropy_coef,
        value_coef=args.value_coef,
        rank_ce_coef=args.rank_ce_coef,
        epochs=args.epochs,
        minibatch_size=args.minibatch_size,
        max_grad_norm=args.max_grad_norm,
        target_kl=args.target_kl if args.target_kl > 0 else None,
        n_steps=args.n_steps,
        reward_scale=args.reward_scale,
        seed=args.seed,
        device=device,
    )
    trainer = PPOTrainer(policy, encoder, config, device=device)

    # ── 评测环境（可选，与训练环境隔离，seed 偏移）──
    eval_env = None
    if args.eval_every > 0:
        eval_env = make_vec_env(
            args.num_envs, mode=args.env, seed=args.seed + 1000, env_kwargs=env_kwargs
        )

    try:
        result = trainer.train(
            env,
            total_steps=args.total_steps,
            out_dir=out_dir,
            eval_env=eval_env,
            eval_every=args.eval_every,
            eval_games=args.eval_games,
            save_every=args.save_every,
            verbose=not args.quiet,
            extra_meta={
                "env": env_desc,
                "env_mode": "mock" if is_mock else "real",
                "num_envs": args.num_envs,
                "opponent": args.opponent,
                "script": "scripts/train_ppo.py",
            },
        )
    finally:
        env.close()
        if eval_env is not None:
            eval_env.close()

    # ── 汇总输出 ──
    history = result["history"]
    print("\n[train_ppo] 训练完成")
    print(f"  steps={result['steps']}  wall={result['wall_time_s']:.1f}s  "
          f"params={result['params']:,}")
    print(f"  checkpoint={result['checkpoint']}")
    if history:
        last = history[-1]
        print("  最后一行指标：")
        print(format_metrics_table([{
            "step": last.get("step", 0),
            "episode_return_mean": f"{last.get('episode_return_mean', 0):.4f}",
            "placement_mean": f"{last.get('placement_mean', 0):.3f}",
            "policy_loss": f"{last.get('policy_loss', 0):.4f}",
            "value_loss": f"{last.get('value_loss', 0):.4f}",
            "rank_ce": f"{last.get('rank_ce', 0):.4f}",
            "entropy": f"{last.get('entropy', 0):.4f}",
            "approx_kl": f"{last.get('approx_kl', 0):.5f}",
        }]))
        spans = {k: (min(r[k] for r in history), max(r[k] for r in history))
                 for k in ("policy_loss", "value_loss", "entropy") if all(k in r for r in history)}
        print("  loss/entropy 变化范围（确认训练在动）：")
        for name, (lo, hi) in spans.items():
            print(f"    {name}: {lo:.5f} → {hi:.5f}")
    if result.get("evals"):
        print("\n  评测：")
        print(format_metrics_table(result["evals"]))
    print(f"\n[train_ppo] 总耗时 {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
