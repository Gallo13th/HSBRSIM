#!/usr/bin/env python3
"""DAgger 冷启动：用当前策略 rollout，查询 bot 动作作为标签，聚合重训。

这是 P0 冷启动兜底：BC 在 500k 样本上到 mean rank 5.0，但 C0 仍未过；
DAgger 让训练分布靠近当前策略，而不是纯 bot 分布。
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
                                  obs_arrays)
from hsbg.az.train.model import load_checkpoint, save_checkpoint
from hsbg.az.train.ppo import PPOEvaluator


def _collect(model, device, games: int, seed: int, *, use_model: bool):
    E = load_engine()
    ev = PPOEvaluator(model, device=device)
    fs, cs, ms, ys = [], [], [], []
    for gi in range(games):
        game = E.Game(seed=seed + gi)
        steps = 0
        while not game.is_over() and steps < 50000:
            acted = False
            for p in range(N_PLAYERS):
                if not game.needs_action(p):
                    continue
                if int(p) == 0:
                    f, c = obs_arrays(game.observe(0))
                    m = mask_from_bytes(game.legal_mask(0))
                    y = int(game.bot_action(0))
                    fs.append(f); cs.append(c); ms.append(m); ys.append(y)
                    if use_model:
                        plog, _ = ev.logits(f, c, m)
                        a = int(np.argmax(np.where(m, plog[0], -1e30)))
                        if not bool(m[a]):
                            a = y
                    else:
                        a = y
                    game.step(0, a)
                else:
                    game.bot_play(int(p))
                steps += 1
                acted = True
                if game.is_over():
                    break
            if not acted:
                break
    return (np.stack(fs).astype(np.float32), np.stack(cs).astype(np.int64),
            np.stack(ms).astype(bool), np.asarray(ys, dtype=np.int64))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--bot-games", type=int, default=100)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="runs/az_entity_dagger")
    args = ap.parse_args()
    import torch
    import torch.nn.functional as F
    from hsbg.az.train.ppo import forward_model, split_model_outputs

    torch.manual_seed(int(args.seed))
    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    t0 = time.time()
    f1, c1, m1, y1 = _collect(model, args.device, int(args.games),
                              int(args.seed) + 500000, use_model=True)
    f2, c2, m2, y2 = _collect(model, args.device, int(args.bot_games),
                              int(args.seed) + 600000, use_model=False)
    FEATS = np.concatenate([f1, f2]); C = np.concatenate([c1, c2])
    M = np.concatenate([m1, m2]); Y = np.concatenate([y1, y2])
    print(f"[dagger] model_states={len(f1)} bot_states={len(f2)} total={len(FEATS)} "
          f"collect={time.time()-t0:.1f}s", flush=True)
    X = torch.from_numpy(FEATS); CT = torch.from_numpy(C); MT = torch.from_numpy(M)
    YT = torch.from_numpy(Y)
    opt = torch.optim.Adam(model.parameters(), lr=float(args.lr))
    n = len(Y); idx = np.arange(n); logs = []
    for ep in range(int(args.epochs)):
        rng = np.random.default_rng(int(args.seed) + ep)
        rng.shuffle(idx)
        tot = 0.0; corr = 0
        for s in range(0, n, int(args.batch)):
            sel = torch.from_numpy(idx[s:s + int(args.batch)]).long()
            xb = X[sel].to(args.device); cb = CT[sel].to(args.device)
            mb = MT[sel].to(args.device); yb = YT[sel].to(args.device)
            out = forward_model(model, xb, cb, mb)
            logits, _, _ = split_model_outputs(out)
            logits = logits.masked_fill(~mb, -1e30)
            loss = F.cross_entropy(logits, yb)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 0.5)
            opt.step()
            tot += float(loss.detach().cpu()) * len(sel)
            corr += int((logits.argmax(-1) == yb).sum().cpu())
        rec = {"epoch": ep + 1, "loss": tot / n, "top1": corr / n}
        logs.append(rec)
        print(f"[dagger] epoch {ep+1} loss={rec['loss']:.4f} top1={rec['top1']:.3f}",
              flush=True)
    os.makedirs(args.out, exist_ok=True)
    ckpt = os.path.join(args.out, "model.pt")
    save_checkpoint(model, ckpt, meta={**meta, "dagger_model_states": len(f1),
                                       "dagger_bot_states": len(f2)})
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"args": vars(args), "model_states": len(f1),
                   "bot_states": len(f2), "epochs": logs,
                   "checkpoint": ckpt, "seconds": time.time() - t0},
                  f, ensure_ascii=False, indent=2)
    print(f"[dagger] saved {ckpt}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
