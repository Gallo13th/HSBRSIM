"""训练“当前回合相对强度”value head：冻结 encoder，回归 pairwise 胜率标签。

数据：runs/value_data/turn_search_winrate_labels.npz（indices/winrate/turn/tier/episode_id）
训练：只训 scalar_head（tanh），目标 utility=2*winrate-1；MSE + BCE。
输出：runs/value_net/turn_search_winrate/{checkpoint.pt, policy_winrate.pt, report.json}
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np
import torch
import torch.nn.functional as F

from hsbg.policy.model import EntityTransformerPolicy
from hsbg.train.bc import BCDataset


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
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


def auc(y: np.ndarray, p: np.ndarray) -> float:
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


def load_split(path: str, episodes: Sequence[int], dataset_name: str,
               seed: int = 0) -> Dict[int, str]:
    p = Path(path)
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        if dataset_name and isinstance(data.get(dataset_name), dict):
            v = data[dataset_name]
            if isinstance(v.get("episode_to_split"), dict) and v["episode_to_split"]:
                return {int(k): str(s) for k, s in v["episode_to_split"].items()}
        for key, val in data.items():
            if key == "bc":
                continue
            if isinstance(val, dict) and isinstance(val.get("episode_to_split"), dict) \
                    and val["episode_to_split"]:
                return {int(k): str(s) for k, s in
                        val["episode_to_split"].items()}
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
def evaluate(policy, encoder, samples, labels, *, device="cpu", bs=512
             ) -> Dict[str, Any]:
    policy.eval()
    preds, ys = [], []
    for start in range(0, len(samples), bs):
        obs = [o for o, _ in samples[start:start + bs]]
        batch = encoder.collate(obs)
        batch = {k: (v.to(device) if isinstance(v, torch.Tensor) else v)
                 for k, v in batch.items()}
        out = policy.forward_full(batch)
        v = out["value"].detach().cpu().numpy().astype(float)
        p = (v + 1.0) / 2.0
        preds.extend(p.tolist())
        ys.extend(np.asarray(labels[start:start + bs], dtype=float).tolist())
    pred = np.asarray(preds)
    y = np.asarray(ys)
    top = (y >= 0.5).astype(np.int32) if y.size else np.zeros(0, dtype=int)
    return {"n": int(y.size),
            "spearman": spearman(pred, y),
            "mae": float(np.mean(np.abs(pred - y))) if y.size else None,
            "mse": float(np.mean((pred - y) ** 2)) if y.size else None,
            "auc_winrate_ge_0.5": auc(top, pred),
            "mean_pred": float(pred.mean()) if y.size else None,
            "mean_label": float(y.mean()) if y.size else None,
            "label_std": float(y.std()) if y.size else None}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="runs/value_data/turn_search_20k.pkl")
    p.add_argument("--labels", default="runs/value_data/turn_search_winrate_labels.npz")
    p.add_argument("--base-checkpoint", default="runs/bc/official_320/policy_bc.pt")
    p.add_argument("--split", default="runs/value_split.json")
    p.add_argument("--out-dir", default="runs/value_net/turn_search_winrate")
    p.add_argument("--device", default="cuda", choices=["cpu", "cuda"])
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--max-seconds", type=float, default=900.0)
    args = p.parse_args(argv)

    t0 = time.time()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device(args.device if args.device != "cuda"
                          or torch.cuda.is_available() else "cpu")
    ds = BCDataset.load(args.data)
    z = np.load(args.labels)
    labels = {int(i): float(w) for i, w in zip(z["indices"], z["winrate"])}
    eps = [int(x) for x in ds.episode_ids]
    split = load_split(args.split, eps, Path(args.data).stem, args.seed)
    idx = {"train": [], "val": [], "test": []}
    for i, e in enumerate(eps):
        if i in labels:
            idx[split.get(int(e), "train")].append(i)
    samples = ds.samples
    print(f"labeled={len(labels)} split="
          f"{ {k: len(v) for k, v in idx.items()} }")

    policy = EntityTransformerPolicy.load(args.base_checkpoint, map_location="cpu")
    encoder = policy.make_encoder()
    policy.config.value_mode = "scalar"   # 只用 scalar_head 输出 tanh
    policy.to(device)
    for p_ in policy.parameters():
        p_.requires_grad_(False)
    for p_ in policy.scalar_head.parameters():
        p_.requires_grad_(True)
    opt = torch.optim.AdamW(policy.scalar_head.parameters(), lr=args.lr,
                            weight_decay=1e-4)

    # 旧 BC value head 对照：expected_rank 越低越强
    base = EntityTransformerPolicy.load(args.base_checkpoint, map_location="cpu")
    base_enc = base.make_encoder()
    base_val = evaluate(base, base_enc, [samples[i] for i in idx["val"]],
                        [labels[i] for i in idx["val"]], device="cpu")
    base_test = evaluate(base, base_enc, [samples[i] for i in idx["test"]],
                         [labels[i] for i in idx["test"]], device="cpu")
    # expected_rank 与 strength 反向；evaluate 用 value 与 winrate，故旧头
    # 的 spearman 实际是 value 与 label（旧 distribution value 为 utility）。
    print("baseline", json.dumps({"val": base_val, "test": base_test},
                                 ensure_ascii=False))

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    best = {"val": {"spearman": -2.0}}
    best_state = None
    hist = []
    for epoch in range(1, args.epochs + 1):
        policy.train()
        order = list(idx["train"])
        random.Random(args.seed + epoch).shuffle(order)
        total = 0.0
        steps = 0
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
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss.item())
            steps += 1
        val = evaluate(policy, encoder, [samples[i] for i in idx["val"]],
                       [labels[i] for i in idx["val"]], device=str(device))
        test = evaluate(policy, encoder, [samples[i] for i in idx["test"]],
                        [labels[i] for i in idx["test"]], device=str(device))
        rec = {"epoch": epoch, "loss": total / max(1, steps),
               "val": val, "test": test,
               "wall_s": round(time.time() - t0, 1)}
        hist.append(rec)
        with open(out / "train_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"epoch {epoch}: loss={rec['loss']:.4f} "
              f"val_spearman={val['spearman']:.3f} val_mae={val['mae']:.3f} "
              f"test_spearman={test['spearman']:.3f}")
        if val["spearman"] > best["val"]["spearman"]:
            best = {"val": val, "test": test, "epoch": epoch}
            best_state = {k: v.detach().cpu().clone()
                          for k, v in policy.state_dict().items()}
    if best_state is not None:
        policy.load_state_dict(best_state)
    policy.eval()
    ckpt = out / "policy_winrate.pt"
    policy.save(ckpt, meta={
        "trainer": "value_winrate",
        "target": "pairwise winrate (0..1)",
        "config": vars(args), "best": best,
        "base_metrics": {"val": base_val, "test": base_test},
    })
    (out / "checkpoint.pt").write_bytes(ckpt.read_bytes())
    report = {"created_at": "2026-10-20", "data": args.data,
              "labels": args.labels, "split_samples": {k: len(v) for k, v in idx.items()},
              "config": vars(args), "best": best,
              "base_metrics": {"val": base_val, "test": base_test},
              "history": hist, "checkpoint": str(ckpt),
              "wall_s": round(time.time() - t0, 1),
              "note": "只训 scalar_head；encoder 冻结；标签为 pairwise 胜率"}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(
        {"best": best, "base_metrics": {"val": base_val, "test": base_test},
         "split_samples": {k: len(v) for k, v in idx.items()}},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"best": best, "base": {"val": base_val, "test": base_test}},
                     ensure_ascii=False, indent=2))
    print("wrote", ckpt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
