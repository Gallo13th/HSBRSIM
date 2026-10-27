#!/usr/bin/env python3
"""Entity 同步 PPO 基线（单进程、持久 Adam/LR/RNG）。

与 `train_az_ppo.py` 的区别：
- 默认 `arch=entity`（14.8M）；
- 同一个进程跨 iteration 保留 model / Adam / LambdaLR / numpy RNG；
- 同时原子保存 `model.pt`（给评测）与 `trainer.pt`（优化器/调度器/RNG）；
- 支持 `--trainer-state` 精确续训；不再每轮重建 Adam。

仍使用当前串行采集（P0 第 2 轮）；批量叶/并发 actor 在 P0 第 3 轮。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import engine_available, engine_info, to_jsonable  # noqa: E402
from hsbg.az.train.model import build_net, load_checkpoint, save_checkpoint  # noqa: E402
from hsbg.az.train.ppo import (  # noqa: E402
    CollectConfig,
    PPOConfig,
    PPOEvaluator,
    collect_ppo_batch,
    torch_available,
)
from hsbg.az.train.ppo_trainer import PPOTrainer  # noqa: E402


def _atomic_torch_save(obj: Any, path: str) -> None:
    import torch
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    torch.save(obj, tmp)
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Entity 同步 PPO 基线（持久 trainer）")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--iterations", type=int, default=0)
    ap.add_argument("--games", type=int, default=4)
    ap.add_argument("--arch", default="entity", choices=["tiny", "entity"])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--sims", type=int, default=4)
    ap.add_argument("--determinizations", type=int, default=1)
    ap.add_argument("--opponent", default="bot", choices=["bot", "self"])
    ap.add_argument("--behavior", default="net", choices=["net", "mcts", "mixed"])
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--minibatch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--lr-min-ratio", type=float, default=0.1)
    ap.add_argument("--max-updates", type=int, default=100000)
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--target-kl", type=float, default=0.05)
    ap.add_argument("--pi-coef", type=float, default=0.1)
    ap.add_argument("--entropy-coef", type=float, default=0.005)
    ap.add_argument("--max-actions-per-turn", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--checkpoint", default="")
    ap.add_argument("--trainer-state", default="")
    ap.add_argument("--out", default="runs/az_entity_sync")
    args = ap.parse_args()
    args.out = os.path.abspath(args.out)

    if not engine_available():
        print("[error] hsbg_engine 不可用", file=sys.stderr)
        return 2
    if not torch_available():
        print("[error] torch 不可用", file=sys.stderr)
        return 2
    import torch
    os.makedirs(args.out, exist_ok=True)
    eng = engine_info()
    print(f"[engine] {json.dumps(eng, ensure_ascii=False)}", flush=True)

    norm_mean = norm_std = None
    if args.checkpoint:
        model, meta = load_checkpoint(args.checkpoint, device=args.device)
        arch = str(meta.get("arch", args.arch))
        norm_mean, norm_std = meta.get("norm_mean"), meta.get("norm_std")
        print(f"[net] checkpoint={args.checkpoint} arch={arch}", flush=True)
    elif args.trainer_state and os.path.isfile(args.trainer_state):
        # 只能先有同结构模型再 load_state；trainer state 内含 model state
        model = build_net(arch=args.arch)
        meta = {"arch": args.arch}
        arch = args.arch
        print(f"[net] empty model for trainer-state={args.trainer_state}", flush=True)
    else:
        model = build_net(arch=args.arch)
        meta = {"arch": args.arch}
        arch = args.arch
    model.to(torch.device(args.device))
    print(f"[net] arch={arch} params={sum(p.numel() for p in model.parameters()):,}",
          flush=True)

    p_cfg = PPOConfig(
        epochs=int(args.epochs), minibatch=int(args.minibatch), lr=float(args.lr),
        clip=float(args.clip), target_kl=float(args.target_kl),
        entropy_coef=float(args.entropy_coef), pi_coef=float(args.pi_coef),
        device=str(args.device), seed=int(args.seed))
    trainer: Optional[PPOTrainer] = None
    if args.trainer_state and os.path.isfile(args.trainer_state):
        trainer = PPOTrainer.load(model, args.trainer_state, config=p_cfg,
                                  device=args.device)
        print(f"[trainer] loaded updates={trainer.updates} "
              f"lr={trainer.optimizer.param_groups[0]['lr']:.3g}", flush=True)
    else:
        trainer = PPOTrainer(model, p_cfg, lr_min_ratio=float(args.lr_min_ratio),
                             max_updates=int(args.max_updates))

    search_fn = search_cfg = None
    if int(args.sims) > 0:
        try:
            from hsbg.az import SearchConfig, search as az_search
        except Exception as exc:  # noqa: BLE001
            print(f"[error] search unavailable: {exc!r}", file=sys.stderr)
            return 2
        search_cfg = SearchConfig(simulations=int(args.sims),
                                  determinizations=int(args.determinizations),
                                  seed=int(args.seed))
        search_fn = az_search

    evaluator = PPOEvaluator(model, device=args.device,
                             norm_mean=norm_mean, norm_std=norm_std)
    t0 = time.time()
    deadline = t0 + float(args.minutes) * 60.0
    i = 0
    last_len = 0.0
    history = []
    while time.time() < deadline:
        if args.iterations > 0 and i >= args.iterations:
            break
        if last_len > 0 and (deadline - time.time()) < max(60.0, last_len):
            print("[loop] remaining time < last iteration; stop", flush=True)
            break
        c_cfg = CollectConfig(
            games=int(args.games), seed=int(args.seed) + i * 1000,
            opponent=str(args.opponent), behavior=str(args.behavior),
            max_actions_per_turn=int(args.max_actions_per_turn))
        iter_start = time.time()
        batch, collect_meta = collect_ppo_batch(
            model, c_cfg, search_fn=search_fn, search_config=search_cfg,
            eval_fn=evaluator, device=str(args.device),
            seed=int(args.seed) + i * 1000, gamma=1.0, lam=0.95,
            norm_mean=norm_mean, norm_std=norm_std, progress=True)
        errs = batch.validate()
        if errs:
            print(f"[error] batch invalid: {errs}", file=sys.stderr)
            return 3
        stats = trainer.update(batch)
        rec = {"iter": i, "collect": collect_meta, "ppo": stats,
               "seconds": time.time() - t0}
        history.append(rec)
        print(f"[iter {i}] samples={len(batch)} updates={stats['trainer_updates']} "
              f"lr={stats['lr']:.3g} total={stats['epochs'][-1]['total']:.4f}",
              flush=True)
        # 原子保存 model + trainer
        ckpt = os.path.join(args.out, "model.pt")
        tmp_ckpt = ckpt + ".tmp"
        save_checkpoint(model, tmp_ckpt,
                        meta={**meta, "arch": arch, "trainer_updates": trainer.updates},
                        norm_mean=norm_mean, norm_std=norm_std)
        os.replace(tmp_ckpt, ckpt)
        trainer.save(os.path.join(args.out, "trainer.pt"))
        with open(os.path.join(args.out, "history.json"), "w", encoding="utf-8") as f:
            json.dump({"args": vars(args), "history": history,
                       "elapsed_s": time.time() - t0}, f, ensure_ascii=False, indent=2)
        last_len = time.time() - iter_start
        i += 1

    summary = {"iterations": i, "updates": trainer.updates,
               "elapsed_s": time.time() - t0, "config": vars(args),
               "history": history}
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(to_jsonable(summary), f, ensure_ascii=False, indent=2)
    print(f"[done] iters={i} updates={trainer.updates} "
          f"elapsed={time.time()-t0:.0f}s -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
