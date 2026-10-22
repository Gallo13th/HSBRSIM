"""行为克隆（BC）训练入口：收集教师示范 → 监督训练 → 保存 checkpoint。

示例::

    python scripts/train_bc.py --episodes 12 --device cpu --out runs/bc_smoke

教师选择：
* ``--teacher heuristic``（默认）—— 候选级启发式（``hsbg.train.evaluate.HeuristicAgent``）；
* ``--teacher random`` —— 随机候选（弱教师，仅用于管线自测）；
* ``--teacher policy`` + ``--init-from`` —— 用已有策略网络当教师（自蒸馏）。
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

from hsbg.policy.encoder import collect_card_ids
from hsbg.policy.model import build_policy, load_policy_and_encoder
from hsbg.train.bc import BCConfig, make_policy_teacher, train_bc
from hsbg.train.evaluate import HeuristicAgent, RandomAgent
from hsbg.train.logger import format_metrics_table
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
        description="BC 训练（教师示范 → 候选动作交叉熵）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--episodes", type=int, default=12, help="收集的教师对局数")
    p.add_argument("--num-envs", type=int, default=2)
    p.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "cuda:0", "cuda:1"])
    p.add_argument("--out", default="runs/bc", help="输出目录（相对仓库根）")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--env", default="auto", choices=["auto", "mock", "real"])
    p.add_argument("--opponent", default="heuristic", help="真环境的对手策略名")
    p.add_argument("--teacher", default="heuristic", choices=["heuristic", "random", "policy"])
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--val-frac", type=float, default=0.2)
    p.add_argument("--rank-ce-coef", type=float, default=0.1)
    p.add_argument("--dim", type=int, default=128)
    p.add_argument("--layers", type=int, default=4)
    p.add_argument("--heads", type=int, default=4)
    p.add_argument("--ff-dim", type=int, default=256)
    p.add_argument("--init-from", default=None, help="教师策略 checkpoint（--teacher policy 时使用）")
    p.add_argument("--data-dir", default=None)
    p.add_argument("--quiet", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    started = time.time()
    seed_everything(args.seed)
    device = resolve_device(args.device)
    out_dir = resolve_out_dir(args.out)

    env_kwargs = env_kwargs_for_real(args.opponent) if args.env != "mock" else None
    env = make_vec_env(args.num_envs, mode=args.env, seed=args.seed, env_kwargs=env_kwargs)
    print(f"[train_bc] env = {describe_env(env)}  device = {device}  out = {out_dir}")

    probe = list(env.reset())

    # ── 编码器 / 策略 ──
    encoder = build_encoder(data_dir=args.data_dir, observations=probe)
    if args.init_from:
        policy, encoder_from_ckpt = load_policy_and_encoder(args.init_from)
        # 以 checkpoint 词表为准，再补充探针观测里的新卡
        encoder = encoder_from_ckpt
        ids = set()
        for obs in probe:
            ids |= collect_card_ids(obs)
        new_ids = sorted(cid for cid in ids if cid not in encoder.vocab)
        if new_ids:
            encoder.vocab.extend(new_ids)
            policy.resize_card_embedding(encoder.vocab)
    else:
        policy = build_policy(
            encoder,
            dim=args.dim,
            layers=args.layers,
            heads=args.heads,
            ff_dim=args.ff_dim,
        )
    print(f"[train_bc] vocab={len(encoder.vocab)} params={policy.count_parameters():,}")

    # ── 教师 ──
    if args.teacher == "heuristic":
        teacher = HeuristicAgent(seed=args.seed)
    elif args.teacher == "random":
        teacher = RandomAgent(seed=args.seed)
    else:
        if not args.init_from:
            raise SystemExit("--teacher policy 需要配合 --init-from <checkpoint>")
        teacher = make_policy_teacher(policy, encoder, device=device, greedy=True)
    print(f"[train_bc] teacher = {teacher.name}")

    # ── 训练 ──
    config = BCConfig(
        lr=args.lr,
        epochs=args.epochs,
        batch_size=args.batch_size,
        val_frac=args.val_frac,
        rank_ce_coef=args.rank_ce_coef,
        seed=args.seed,
        device=device,
    )
    try:
        result = train_bc(
            env,
            policy,
            encoder,
            teacher=teacher,
            episodes=args.episodes,
            config=config,
            out_dir=out_dir,
            verbose=not args.quiet,
        )
    finally:
        env.close()

    history = result["history"]
    best_val = result["val_accuracy"]
    print("\n[train_bc] 训练完成")
    print(f"  样本={result['train_samples']}  验证={result['val_samples']}  "
          f"epochs={result['epochs']}  wall={result['wall_time_s']:.1f}s")
    print(f"  val_accuracy(best)={best_val:.4f}  random_baseline={result['random_baseline']:.4f}")
    print(f"  checkpoint={result['checkpoint']}")
    print(f"  dataset={result['dataset_path']}")
    if history:
        print("\n  训练曲线：")
        print(format_metrics_table([
            {
                "epoch": r["epoch"],
                "train_loss": f"{r['train_loss']:.4f}",
                "train_acc": f"{r['train_accuracy']:.3f}",
                "val_loss": f"{r.get('val_loss', float('nan')):.4f}",
                "val_acc": f"{r.get('val_accuracy', float('nan')):.3f}",
            }
            for r in history
        ]))
    print(f"\n[train_bc] 总耗时 {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
