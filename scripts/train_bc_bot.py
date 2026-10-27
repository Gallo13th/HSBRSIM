#!/usr/bin/env python3
"""冷启动合法 bot 示范（BC auxiliary）。

用途：当 C0 对完整 bot 全 rank8、PPO 优势恒为 0 时，先用引擎 bot 的合法动作做
监督冷启动，再转 PPO。它不是主训练流程；只用于 P0 冷启动兜底，结果必须仍用
C0 gate 对完整 bot 验证。

用法：
    python scripts/train_bc_bot.py --games 120 --epochs 2 --arch entity \
        --out runs/az_entity_bc
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import (N_ACTIONS, N_PLAYERS, load_engine, mask_from_bytes,
                                  obs_arrays, to_jsonable)
from hsbg.az.train.model import build_net, save_checkpoint


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=120)
    ap.add_argument("--max-samples", type=int, default=20000)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--arch", default="entity", choices=["tiny", "entity", "entity18m"])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="runs/az_entity_bc")
    args = ap.parse_args()
    import torch
    import torch.nn.functional as F
    from hsbg.az.train.ppo import forward_model, split_model_outputs

    torch.manual_seed(int(args.seed))
    np.random.seed(int(args.seed) % (2 ** 32))
    os.makedirs(args.out, exist_ok=True)
    E = load_engine()
    feats, cards, masks, actions = [], [], [], []
    t0 = time.time()
    for gi in range(int(args.games)):
        game = E.Game(seed=int(args.seed) + gi)
        steps = 0
        while not game.is_over() and steps < 50000 and len(actions) < args.max_samples:
            acted = False
            for p in range(N_PLAYERS):
                if not game.needs_action(p):
                    continue
                if int(p) == 0:
                    m = mask_from_bytes(game.legal_mask(0))
                    f, c = obs_arrays(game.observe(0))
                    a = int(game.bot_action(0))
                    if not (0 <= a < N_ACTIONS and bool(m[a])):
                        raise RuntimeError(f"bot_action illegal at game {gi}")
                    feats.append(f); cards.append(c); masks.append(m); actions.append(a)
                    game.step(0, a)
                else:
                    game.bot_play(int(p))
                steps += 1
                acted = True
                if game.is_over():
                    break
            if not acted:
                break
        if len(actions) >= args.max_samples:
            break
    print(f"[bc] samples={len(actions)} games={gi+1} collect={time.time()-t0:.1f}s",
          flush=True)
    if not actions:
        raise SystemExit("no samples")
    X = torch.from_numpy(np.stack(feats).astype(np.float32))
    C = torch.from_numpy(np.stack(cards).astype(np.int64))
    M = torch.from_numpy(np.stack(masks).astype(bool))
    A = torch.from_numpy(np.asarray(actions, dtype=np.int64))
    model = build_net(arch=args.arch)
    model.to(torch.device(args.device))
    opt = torch.optim.Adam(model.parameters(), lr=float(args.lr))
    n = len(actions)
    idx = np.arange(n)
    logs = []
    for ep in range(int(args.epochs)):
        rng = np.random.default_rng(int(args.seed) + ep)
        rng.shuffle(idx)
        total = 0.0
        correct = 0
        for s in range(0, n, int(args.batch)):
            sel = torch.from_numpy(idx[s:s + int(args.batch)]).long()
            xb, cb, mb, ab = (X[sel].to(args.device), C[sel].to(args.device),
                              M[sel].to(args.device), A[sel].to(args.device))
            out = forward_model(model, xb, cb, mb)
            logits, _, _ = split_model_outputs(out)
            logits = logits.masked_fill(~mb, -1e30)
            loss = F.cross_entropy(logits, ab)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 0.5)
            opt.step()
            total += float(loss.detach().cpu()) * len(sel)
            correct += int((logits.argmax(-1) == ab).sum().cpu())
        rec = {"epoch": ep + 1, "loss": total / n, "top1": correct / n}
        logs.append(rec)
        print(f"[bc] epoch {ep+1} loss={rec['loss']:.4f} top1={rec['top1']:.3f}", flush=True)
    ckpt = os.path.join(args.out, "model.pt")
    save_checkpoint(model, ckpt, meta={"arch": args.arch, "bc_samples": n,
                                       "bc_games": gi + 1})
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"args": to_jsonable(vars(args)), "samples": n,
                   "games": gi + 1, "epochs": logs,
                   "checkpoint": ckpt, "seconds": time.time() - t0},
                  f, ensure_ascii=False, indent=2)
    print(f"[bc] saved {ckpt}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
