#!/usr/bin/env python
"""从已收集的 BCDataset 训练行为克隆策略（不重新采样）。

用法::

    python scripts/train_bc_dataset.py --dataset runs/bc_data/heuristic_200.pkl \
        --epochs 20 --device auto --out runs/bc/heuristic_200

产物：``policy_bc.pt``（含词表/BC config）、``report.json``、训练曲线 CSV。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.policy.encoder import CardVocab, ObservationEncoder, collect_card_ids  # noqa: E402
from hsbg.policy.model import PolicyConfig, build_policy  # noqa: E402
from hsbg.train.bc import BCConfig, BCDataset, BCTrainer  # noqa: E402
from hsbg.train.setup import resolve_device, resolve_out_dir  # noqa: E402


def _json_default(obj):
    """numpy/torch 标量 → JSON 可序列化（report.json 用）。"""
    item = getattr(obj, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:  # noqa: BLE001
            pass
    return str(obj)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="从 BCDataset 训练 BC 策略")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--rank-ce-coef", type=float, default=0.1)
    ap.add_argument("--dim", type=int, default=128)
    ap.add_argument("--layers", type=int, default=4)
    ap.add_argument("--heads", type=int, default=4)
    ap.add_argument("--ff-dim", type=int, default=256)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="runs/bc")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    started = time.time()
    device = resolve_device(args.device)
    out_dir = resolve_out_dir(args.out)

    # 词表：数据目录全量卡 + 数据集观测中出现的卡（防漏）
    vocab = CardVocab.from_data_dir(ROOT / "data")
    extra = set()
    ds = BCDataset.load(args.dataset)
    for obs, _a in ds.samples:
        extra |= collect_card_ids(obs)
    new = sorted(c for c in extra if c not in vocab)
    if new:
        vocab.extend(new)
    encoder = ObservationEncoder(vocab)
    policy = build_policy(encoder, dim=args.dim, layers=args.layers,
                          heads=args.heads, ff_dim=args.ff_dim)
    print(f"[train_bc_dataset] dataset={len(ds)} samples from "
          f"{ds.num_episodes} episodes | vocab={len(vocab)} "
          f"params={policy.count_parameters():,} device={device}")

    config = BCConfig(lr=args.lr, epochs=args.epochs,
                      batch_size=args.batch_size, val_frac=args.val_frac,
                      rank_ce_coef=args.rank_ce_coef, seed=args.seed,
                      device=device)
    trainer = BCTrainer(policy, encoder, config, device=device)
    result = trainer.fit(ds, verbose=not args.quiet)

    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "policy_bc.pt"
    trainer.save_checkpoint(ckpt, meta={
        "dataset": str(args.dataset),
        "dataset_size": len(ds),
        "val_accuracy": result["val_accuracy"],
        "script": "scripts/train_bc_dataset.py",
    })
    report = {
        "dataset": str(args.dataset),
        "samples": len(ds),
        "episodes": ds.num_episodes,
        "val_accuracy": result["val_accuracy"],
        "random_baseline": result["random_baseline"],
        "checkpoint": str(ckpt),
        "wall_time_s": result.get("wall_time_s", time.time() - started),
        "history": result["history"],
        "config": config.to_dict(),
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8")
    print(f"[train_bc_dataset] val_acc={result['val_accuracy']:.4f} "
          f"(random {result['random_baseline']:.4f}) -> {ckpt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
