"""B 路线：用本地 turn-search 枚举状态的 pairwise 得分训练 value head。

数据：runs/value_data/turn_search_localpair.pkl
  samples=(Observation, action)、scores=本地 pairwise score(0..1)、episode_ids、turns/tiers
训练：冻结 encoder，只训 scalar_head（MSE+BCE），按 episode 70/15/15。
评估：held-out Spearman(value, local pairwise score)、MAE、AUC。
输出：runs/value_net/turn_search_localpair/
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np
import torch
import torch.nn.functional as F

from hsbg.policy.model import EntityTransformerPolicy


def spearman(x, y) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size < 2 or x.std() == 0 or y.std() == 0:
        return 0.0

    def rank(v):
        order = np.argsort(v, kind="mergesort")
        r = np.empty(len(v), dtype=float)
        r[order] = np.arange(len(v), dtype=float)
        for val in np.unique(v):
            idx = np.where(v == val)[0]
            if idx.size > 1:
                r[idx] = r[idx].mean()
        return r

    return float(np.corrcoef(rank(x), rank(y))[0, 1])


def auc(y, p) -> float:
    y = np.asarray(y, dtype=np.int32)
    p = np.asarray(p, dtype=np.float64)
    pos, neg = p[y == 1], p[y == 0]
    if pos.size == 0 or neg.size == 0:
        return 0.0
    allv = np.concatenate([pos, neg])
    order = np.argsort(allv, kind="mergesort")
    ranks = np.empty(len(allv), dtype=float)
    ranks[order] = np.arange(1, len(allv) + 1)
    for v in np.unique(allv):
        idx = np.where(allv == v)[0]
        if idx.size > 1:
            ranks[idx] = ranks[idx].mean()
    return float((ranks[:pos.size].sum() -
                  pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


def make_split(episodes: Sequence[int], seed: int = 0) -> Dict[int, str]:
    eps = sorted(set(int(e) for e in episodes))
    rng = random.Random(seed)
    rng.shuffle(eps)
    n = len(eps)
    a, b = int(round(0.70 * n)), int(round(0.15 * n))
    out = {e: "train" for e in eps[:a]}
    out.update({e: "val" for e in eps[a:a + b]})
    out.update({e: "test" for e in eps[a + b:]})
    return out


@torch.no_grad()
def evaluate(policy, encoder, samples, labels, turns, *, device="cpu",
             bs=512) -> Dict[str, Any]:
    policy.eval()
    preds, ys, ts = [], [], []
    for start in range(0, len(samples), bs):
        obs = [o for o, _ in samples[start:start + bs]]
        batch = encoder.collate(obs)
        batch = {k: (v.to(device) if isinstance(v, torch.Tensor) else v)
                 for k, v in batch.items()}
        out = policy.forward_full(batch)
        v = out["value"].detach().cpu().numpy().astype(float)
        preds.extend(((v + 1.0) / 2.0).tolist())
        ys.extend(np.asarray(labels[start:start + bs], dtype=float).tolist())
        ts.extend(list(turns[start:start + bs]))
    pred = np.asarray(preds)
    y = np.asarray(ys)
    top = (y >= np.median(y)).astype(np.int32) if y.size else np.zeros(0, dtype=int)
    by_turn: Dict[int, float] = {}
    for t in sorted(set(ts)):
        idx = [i for i, x in enumerate(ts) if int(x) == int(t)]
        if len(idx) >= 8:
            by_turn[int(t)] = spearman(pred[idx], y[idx])
    return {"n": int(y.size),
            "spearman": spearman(pred, y),
            "spearman_by_turn": by_turn,
            "mean_by_turn": float(np.mean(list(by_turn.values())))
            if by_turn else 0.0,
            "mae": float(np.mean(np.abs(pred - y))) if y.size else None,
            "mse": float(np.mean((pred - y) ** 2)) if y.size else None,
            "auc_top_half": auc(top, pred)}


def pairwise_rank_loss(pred, y, groups, *, max_pairs=512) -> torch.Tensor:
    """同一决策内按 label 排序的 pairwise logistic loss。"""
    losses = []
    n = 0
    by_group: Dict[Any, List[int]] = {}
    for i, g in enumerate(groups):
        by_group.setdefault(g, []).append(i)
    for g, idxs in by_group.items():
        if len(idxs) < 2:
            continue
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                dy = float(y[i] - y[j])
                if abs(dy) < 1e-6:
                    continue
                sign = 1.0 if dy > 0 else -1.0
                losses.append(F.softplus(-(pred[i] - pred[j]) * sign))
                n += 1
                if n >= max_pairs:
                    break
            if n >= max_pairs:
                break
        if n >= max_pairs:
            break
    if not losses:
        return torch.zeros((), device=pred.device)
    return torch.stack(losses).mean()


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="runs/value_data/turn_search_localpair.pkl")
    p.add_argument("--base-checkpoint", default="runs/bc/official_320/policy_bc.pt")
    p.add_argument("--out-dir", default="runs/value_net/turn_search_localpair")
    p.add_argument("--device", default="cuda", choices=["cpu", "cuda"])
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--w-rank", type=float, default=0.5)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-seconds", type=float, default=900.0)
    args = p.parse_args(argv)

    import pickle
    t0 = time.time()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device(args.device if args.device != "cuda"
                          or torch.cuda.is_available() else "cpu")
    with open(args.data, "rb") as f:
        data = pickle.load(f)
    samples = data["samples"]
    labels = [float(x) for x in data["scores"]]
    eps = [int(x) for x in data["episode_ids"]]
    turns = [int(x) for x in data["turns"]]
    decisions = [int(x) for x in data.get("decisions", [0] * len(samples))]
    groups = [(eps[i], decisions[i]) for i in range(len(samples))]
    split = make_split(eps, args.seed)
    idx = {"train": [], "val": [], "test": []}
    for i, e in enumerate(eps):
        idx[split.get(int(e), "train")].append(i)
    print(f"states={len(samples)} episodes={len(set(eps))} "
          f"split={ {k: len(v) for k, v in idx.items()} }", flush=True)

    policy = EntityTransformerPolicy.load(args.base_checkpoint, map_location="cpu")
    encoder = policy.make_encoder()
    policy.config.value_mode = "scalar"
    policy.to(device)
    for p_ in policy.parameters():
        p_.requires_grad_(False)
    for p_ in policy.scalar_head.parameters():
        p_.requires_grad_(True)
    opt = torch.optim.AdamW(policy.scalar_head.parameters(), lr=args.lr,
                            weight_decay=1e-4)
    base = EntityTransformerPolicy.load(args.base_checkpoint, map_location="cpu")
    base_enc = base.make_encoder()
    base_val = evaluate(base, base_enc, [samples[i] for i in idx["val"]],
                        [labels[i] for i in idx["val"]],
                        [turns[i] for i in idx["val"]], device="cpu")
    base_test = evaluate(base, base_enc, [samples[i] for i in idx["test"]],
                         [labels[i] for i in idx["test"]],
                         [turns[i] for i in idx["test"]], device="cpu")
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    best = {"val": {"spearman": -2.0}}
    best_state = None
    hist = []
    for epoch in range(1, args.epochs + 1):
        policy.train()
        order = list(idx["train"])
        random.Random(args.seed + epoch).shuffle(order)
        total, steps = 0.0, 0
        for start in range(0, len(order), args.batch_size):
            if time.time() - t0 > args.max_seconds:
                break
            bi = order[start:start + args.batch_size]
            obs = [samples[i][0] for i in bi]
            y = torch.as_tensor([labels[i] for i in bi], dtype=torch.float32,
                                device=device)
            batch = encoder.collate(obs)
            batch = {k: (v.to(device) if isinstance(v, torch.Tensor) else v)
                     for k, v in batch.items()}
            out_f = policy.forward_full(batch)
            pred = (out_f["value"] + 1.0) / 2.0
            loss = F.mse_loss(pred, y) + 0.2 * F.binary_cross_entropy(
                pred.clamp(1e-6, 1 - 1e-6), y)
            if args.w_rank > 0:
                loss = loss + args.w_rank * pairwise_rank_loss(
                    pred, [labels[i] for i in bi],
                    [groups[i] for i in bi])
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss.item())
            steps += 1
        val = evaluate(policy, encoder, [samples[i] for i in idx["val"]],
                       [labels[i] for i in idx["val"]],
                       [turns[i] for i in idx["val"]], device=str(device))
        test = evaluate(policy, encoder, [samples[i] for i in idx["test"]],
                        [labels[i] for i in idx["test"]],
                        [turns[i] for i in idx["test"]], device=str(device))
        rec = {"epoch": epoch, "loss": total / max(1, steps),
               "val": val, "test": test, "wall_s": round(time.time() - t0, 1)}
        hist.append(rec)
        with open(out / "train_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"epoch {epoch}: loss={rec['loss']:.4f} "
              f"val_rho={val['spearman']:.3f} "
              f"val_mae={val['mae'] if val['mae'] is not None else float('nan'):.3f} "
              f"test_rho={test['spearman']:.3f}", flush=True)
        if val["spearman"] > best["val"]["spearman"]:
            best = {"val": val, "test": test, "epoch": epoch}
            best_state = {k: v.detach().cpu().clone()
                          for k, v in policy.state_dict().items()}
    if best_state is not None:
        policy.load_state_dict(best_state)
    policy.eval()
    ckpt = out / "policy_localpair.pt"
    policy.save(ckpt, meta={"trainer": "value_localpair",
                            "target": "local pairwise score",
                            "config": vars(args), "best": best})
    (out / "checkpoint.pt").write_bytes(ckpt.read_bytes())
    report = {"data": args.data, "samples": len(samples),
              "episodes": len(set(eps)),
              "split": {k: len(v) for k, v in idx.items()},
              "config": vars(args), "best": best,
              "base_metrics": {"val": base_val, "test": base_test},
              "history": hist, "checkpoint": str(ckpt),
              "wall_s": round(time.time() - t0, 1),
              "note": "冻结 encoder，只训 scalar_head；标签=本地 pairwise score"}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(
        {"best": best, "base_metrics": {"val": base_val, "test": base_test},
         "samples": len(samples), "episodes": len(set(eps))},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"best": best, "base": {"val": base_val, "test": base_test}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
