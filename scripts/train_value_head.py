"""冻结 encoder，只训 value head（rank 分布 + utility MSE + top4 BCE）。

输入 turn-search 自对弈数据（BCDataset 格式）：
  runs/value_data/turn_search_20k.pkl
  samples=(Observation, action), ranks=1..8, episode_ids
按 episode 70/15/15 切分（优先读 runs/value_split.json；无则固定 seed 生成）。

输出 runs/value_net/turn_search_phase1/：
  policy_value.pt（完整 checkpoint，可直接给 PolicyEvaluator）
  report.json / train_log.jsonl

不训练策略/encoder；只更新 rank_head（+可选 scalar_head）。
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from datetime import datetime
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

DEFAULT_DATA = "runs/value_data/turn_search_20k.pkl"
DEFAULT_BASE = "runs/bc/official_320/policy_bc.pt"
DEFAULT_SPLIT = "runs/value_split.json"


# ── 指标 ──
def _auc(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y, dtype=np.int32)
    p = np.asarray(p, dtype=np.float64)
    pos = p[y == 1]
    neg = p[y == 0]
    if pos.size == 0 or neg.size == 0:
        return 0.0
    # Mann-Whitney U
    allv = np.concatenate([pos, neg])
    order = np.argsort(allv, kind="mergesort")
    ranks = np.empty(len(allv), dtype=np.float64)
    ranks[order] = np.arange(1, len(allv) + 1)
    # average ties
    for v in np.unique(allv):
        idx = np.where(allv == v)[0]
        if idx.size > 1:
            ranks[idx] = ranks[idx].mean()
    rpos = ranks[:pos.size].sum()
    return float((rpos - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


def _ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    y = np.asarray(y, dtype=np.float64)
    p = np.asarray(p, dtype=np.float64)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = 0.0
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        m = (p >= lo) & (p < hi if i < bins - 1 else p <= hi)
        if not m.any():
            continue
        total += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(total)


@torch.no_grad()
def evaluate(policy: EntityTransformerPolicy, encoder,
             samples: Sequence[Tuple[Any, int]], ranks: Sequence[int],
             *, device: str, batch_size: int = 512) -> Dict[str, Any]:
    policy.eval()
    er_all: List[np.ndarray] = []
    probs_all: List[np.ndarray] = []
    rank_all: List[np.ndarray] = []
    for start in range(0, len(samples), batch_size):
        chunk = samples[start:start + batch_size]
        rr = np.asarray(ranks[start:start + batch_size], dtype=np.int64)
        obs = [o for o, _ in chunk]
        batch = encoder.collate(obs)
        batch = {k: (v.to(device) if isinstance(v, torch.Tensor) else v)
                 for k, v in batch.items()}
        out = policy.forward_full(batch)
        er_all.append(out["expected_rank"].detach().cpu().numpy())
        probs_all.append(torch.softmax(out["rank_logits"], -1).detach().cpu().numpy())
        rank_all.append(rr)
    er = np.concatenate(er_all) if er_all else np.zeros(0)
    probs = np.concatenate(probs_all) if probs_all else np.zeros((0, 8))
    ranks_np = np.concatenate(rank_all) if rank_all else np.zeros(0, dtype=int)
    valid = (ranks_np >= 1) & (ranks_np <= probs.shape[1])
    if not valid.any():
        return {"n": 0, "mae": None, "rmse": None, "ce": None,
                "top4_auc": None, "ece": None}
    er = er[valid]
    probs = probs[valid]
    ranks_np = ranks_np[valid]
    u = 1.0 - 2.0 * (ranks_np - 1) / max(1, probs.shape[1] - 1)
    expected_u = (probs * (1.0 - 2.0 * (np.arange(probs.shape[1]) /
                                       max(1, probs.shape[1] - 1)))).sum(-1)
    mae = float(np.abs(er - ranks_np).mean())
    rmse = float(np.sqrt(np.mean((er - ranks_np) ** 2)))
    ce = float(-np.log(np.clip(probs[np.arange(len(ranks_np)),
                                      ranks_np - 1], 1e-9, 1.0)).mean())
    p_top4 = probs[:, :4].sum(-1)
    top4 = (ranks_np <= 4).astype(np.int32)
    return {"n": int(len(ranks_np)), "mae": mae, "rmse": rmse, "ce": ce,
            "top4_auc": _auc(top4, p_top4), "ece": _ece(top4, p_top4),
            "mean_expected_rank": float(er.mean()),
            "mean_actual_rank": float(ranks_np.mean())}


# ── 切分 ──
def load_split(path: str, episodes: Sequence[int], seed: int = 0,
               dataset_name: str = "") -> Tuple[Dict[int, str], Dict[str, Any]]:
    p = Path(path)
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        # 优先匹配当前数据集（如 turn_search_20k），避免误用 bc 的 split
        if dataset_name and isinstance(data.get(dataset_name), dict):
            v = data[dataset_name]
            if isinstance(v.get("episode_to_split"), dict) and v["episode_to_split"]:
                return ({int(k): str(s) for k, s in
                         v["episode_to_split"].items()}, v)
        for cand in (data.get("episode_to_split"),
                     data.get("bc", {}).get("episode_to_split")
                     if isinstance(data.get("bc"), dict) else None):
            if isinstance(cand, dict) and cand:
                return {int(k): str(v) for k, v in cand.items()}, data
        # collector 格式：{"turn_search_20k": {"episode_to_split": {...}}, ...}
        for key, val in data.items():
            if key == "bc":
                continue
            if isinstance(val, dict) and isinstance(val.get("episode_to_split"), dict) \
                    and val["episode_to_split"]:
                return ({int(k): str(v) for k, v in
                         val["episode_to_split"].items()}, val)
    eps = sorted(int(e) for e in episodes)
    rng = random.Random(int(seed))
    rng.shuffle(eps)
    n = len(eps)
    n_train = int(round(0.70 * n))
    n_val = int(round(0.15 * n))
    split = {e: "train" for e in eps[:n_train]}
    split.update({e: "val" for e in eps[n_train:n_train + n_val]})
    split.update({e: "test" for e in eps[n_train + n_val:]})
    return split, {"fallback": True, "seed": seed}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="冻结 encoder，只训 value head")
    parser.add_argument("--data", default=DEFAULT_DATA)
    parser.add_argument("--base-checkpoint", default=DEFAULT_BASE)
    parser.add_argument("--split", default=DEFAULT_SPLIT)
    parser.add_argument("--out-dir", default="runs/value_net/turn_search_phase1")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--w-utility", type=float, default=0.5)
    parser.add_argument("--w-top4", type=float, default=0.2)
    parser.add_argument("--label-smoothing", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-seconds", type=float, default=900.0)
    args = parser.parse_args(argv)

    t0 = time.time()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device(args.device if (args.device != "cuda"
                                         or torch.cuda.is_available()) else "cpu")
    data_path = Path(args.data)
    if not data_path.exists():
        print(f"[ERROR] 数据不存在: {data_path}（等 data-upgrade 采集）")
        return 2
    ds = BCDataset.load(data_path)
    n = len(ds.samples)
    ranks = [int(x) for x in ds.ranks]
    eps = [int(x) for x in ds.episode_ids]
    split, split_meta = load_split(args.split, eps, seed=args.seed,
                                   dataset_name=data_path.stem)
    idx = {"train": [], "val": [], "test": []}
    for i, e in enumerate(eps):
        idx[split.get(int(e), "train")].append(i)
    print(f"data={data_path} samples={n} episodes={len(set(eps))} "
          f"split={ {k: len(v) for k, v in idx.items()} }")

    policy = EntityTransformerPolicy.load(args.base_checkpoint, map_location="cpu")
    encoder = policy.make_encoder()
    policy.to(device)
    for p in policy.parameters():
        p.requires_grad_(False)
    trainable = list(policy.rank_head.parameters())
    if getattr(policy.config, "value_mode", "distribution") != "distribution":
        trainable = list(policy.rank_head.parameters())
    for p in trainable:
        p.requires_grad_(True)
    opt = torch.optim.AdamW(trainable, lr=args.lr,
                            weight_decay=args.weight_decay)

    # 旧 BC head 基线（同一 val/test）
    base_policy = EntityTransformerPolicy.load(args.base_checkpoint, map_location="cpu")
    base_enc = base_policy.make_encoder()
    base_metrics = {
        "val": evaluate(base_policy, base_enc,
                        [ds.samples[i] for i in idx["val"]],
                        [ranks[i] for i in idx["val"]], device="cpu"),
        "test": evaluate(base_policy, base_enc,
                         [ds.samples[i] for i in idx["test"]],
                         [ranks[i] for i in idx["test"]], device="cpu"),
    }
    print("baseline", json.dumps(base_metrics, ensure_ascii=False))

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "train_log.jsonl"
    best = {"val": {"mae": 1e9}, "test": {"mae": 1e9}}
    best_state = None
    history: List[Dict[str, Any]] = []
    for epoch in range(1, args.epochs + 1):
        policy.train()
        order = list(idx["train"])
        random.Random(args.seed + epoch).shuffle(order)
        total = 0.0
        steps = 0
        for start in range(0, len(order), args.batch_size):
            if time.time() - t0 > args.max_seconds:
                print("[WARN] max-seconds reached")
                break
            bi = order[start:start + args.batch_size]
            obs = [ds.samples[i][0] for i in bi]
            rr = torch.as_tensor([ranks[i] for i in bi], dtype=torch.long,
                                 device=device)
            valid = (rr >= 1) & (rr <= policy.config.num_players)
            if not bool(valid.any()):
                continue
            batch = encoder.collate(obs)
            batch = {k: (v.to(device) if isinstance(v, torch.Tensor) else v)
                     for k, v in batch.items()}
            out_f = policy.forward_full(batch)
            logits = out_f["rank_logits"]
            ce = F.cross_entropy(logits[valid], (rr[valid] - 1).clamp(0, 7),
                                 label_smoothing=args.label_smoothing)
            probs = torch.softmax(logits, -1)
            p_top4 = probs[:, :4].sum(-1)
            top4 = (rr <= 4).float()
            bce = F.binary_cross_entropy(
                p_top4[valid].clamp(1e-6, 1 - 1e-6), top4[valid])
            n_pl = policy.config.num_players
            u = 1.0 - 2.0 * (rr[valid] - 1).float() / max(1, n_pl - 1)
            expected_u = probs[valid].mul(
                1.0 - 2.0 * torch.arange(n_pl, device=device).float()
                / max(1, n_pl - 1)).sum(-1)
            mse = F.mse_loss(expected_u, u)
            loss = ce + args.w_utility * mse + args.w_top4 * bce
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss.item())
            steps += 1
        # eval
        val_m = evaluate(policy, encoder, [ds.samples[i] for i in idx["val"]],
                         [ranks[i] for i in idx["val"]], device=str(device))
        test_m = evaluate(policy, encoder, [ds.samples[i] for i in idx["test"]],
                          [ranks[i] for i in idx["test"]], device=str(device))
        rec = {"epoch": epoch, "train_loss": total / max(1, steps),
               "val": val_m, "test": test_m,
               "wall_s": round(time.time() - t0, 1)}
        history.append(rec)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"epoch {epoch}: loss={rec['train_loss']:.4f} "
              f"val_mae={val_m['mae'] if val_m['mae'] is not None else float('nan'):.3f} "
              f"val_ce={val_m['ce'] if val_m['ce'] is not None else float('nan'):.3f} "
              f"test_mae={test_m['mae'] if test_m['mae'] is not None else float('nan'):.3f}")
        if val_m.get("mae") is not None and val_m["mae"] < best["val"]["mae"]:
            best = {"val": val_m, "test": test_m, "epoch": epoch}
            best_state = {k: v.detach().cpu().clone()
                          for k, v in policy.state_dict().items()}
        if time.time() - t0 > args.max_seconds:
            break
    if best_state is not None:
        policy.load_state_dict(best_state)
    policy.eval()
    ckpt = out / "policy_value.pt"
    policy.save(ckpt, meta={
        "trainer": "value_head",
        "value_config": {"epochs": args.epochs, "lr": args.lr,
                         "batch_size": args.batch_size,
                         "w_utility": args.w_utility, "w_top4": args.w_top4,
                         "label_smoothing": args.label_smoothing,
                         "seed": args.seed, "data": str(data_path),
                         "split": str(args.split)},
        "best": best, "base_metrics": base_metrics,
    })
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "data": {"path": str(data_path), "samples": n,
                 "episodes": len(set(eps)),
                 "split_samples": {k: len(v) for k, v in idx.items()},
                 "split_meta": split_meta},
        "config": vars(args),
        "base_metrics": base_metrics,
        "best": best,
        "history": history,
        "checkpoint": str(ckpt),
        "wall_s": round(time.time() - t0, 1),
        "note": "只训 value head（rank 分布/utility/top4）；encoder 冻结；不训练策略",
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False,
                                               indent=2), encoding="utf-8")
    print(f"wrote {ckpt} and {out/'report.json'} ({report['wall_s']}s)")
    print(json.dumps({"best": best, "base": base_metrics},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
