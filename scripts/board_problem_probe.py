#!/usr/bin/env python3
"""场面题离线探针：在**完整题目池**上评估各 ckpt 的题目 CE / 参考 top-1 / 强度头。

为什么需要它：40–60 iter 的训练日志里每步只抽 128 道题（噪声大），而且 human 面板对这种
小系数扰动不敏感。这里用**固定全池**（315 题、无采样）测四个量，直接回答「辅助信号学到没」：

- `soft_ce`：题目状态上的 soft-label CE（越低越好；均匀分布 = ln245 = 5.50）；
- `top1_acc`：策略 argmax 命中人类参考 top-1 的比例；
- `in_ref_k`：策略在题目上的 argmax 落在参考解 top-k 内的比例；
- `strength_mse` / `strength_bce` / `tier_acc`：强度辅助头（无头 ckpt 记为 null）。

用法::

    PYTHONPATH=rust/python:. python scripts/board_problem_probe.py \
      --ckpt s14=runs/az_entity_s14/model.pt --ckpt A=runs/ab_board/armA/model.pt \
      --ckpt B=runs/ab_board/armB/model.pt --out runs/ab_board/probe.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from hsbg.az.train.board_problems import (  # noqa: E402
    DEFAULT_PROBLEM_PATH,
    load_problem_pool,
    problem_bc_soft_ce,
    problem_obs_batch,
    strength_aux_loss,
)


def _probe(model, pool, *, topk: int = 8) -> dict:
    import torch
    from hsbg.az.train.ppo import forward_problem_model
    n = len(pool)
    idx = np.arange(n)
    out = {"problems": int(n)}
    # 分块前向（全池一次也行，但分块对显存更稳）
    logits_all, pred_all = [], []
    with torch.no_grad():
        for s in range(0, n, 64):
            b = problem_obs_batch(pool, idx[s:s + 64])
            x = torch.from_numpy(b.features)
            c = torch.from_numpy(b.cards.astype(np.int64))
            m = torch.from_numpy(b.mask)
            lg, pred = forward_problem_model(model, x, c, m)
            logits_all.append(lg.float().cpu())
            if pred is not None:
                pred_all.append(pred.float().cpu())
    import torch
    logits = torch.cat(logits_all, dim=0)
    batch = problem_obs_batch(pool, idx)
    pbc = problem_bc_soft_ce(logits, batch)
    out["soft_ce"] = float(pbc["loss"])
    out["top1_acc"] = float(pbc["top1_acc"])
    out["policy_in_ref"] = float(pbc["policy_in_ref"])
    # argmax 落在参考 top-k（用同一批 soft label 的非零项）
    soft = torch.from_numpy(batch.soft)
    pred = logits.argmax(dim=-1)
    valid = torch.from_numpy(batch.bc_valid)
    hit = soft.gather(1, pred.unsqueeze(1)).squeeze(1) > 0
    out["argmax_in_ref_k"] = (float((hit & valid).sum())
                              / max(int(valid.sum()), 1))
    if pred_all:
        pred2 = torch.cat(pred_all, dim=0)
        aux = strength_aux_loss(pred2, batch)
        out["strength_mse"] = float(aux["mse"])
        out["strength_bce"] = float(aux["bce"])
        out["tier_acc"] = float(aux["tier_up_acc"])
        # 强度预测（**增量** log1p 差）与真实增量的相关性（校准诊断）
        d_true = (np.log1p(np.maximum(pool.strength_after, 0.0))
                  - np.log1p(np.maximum(pool.strength_before, 0.0)))
        d_pred = (pred2[:, 0].numpy() * float(pool.norm.get("std", 1.0))
                  + float(pool.norm.get("mean", 0.0)))
        mask = pool.aux_valid
        if int(mask.sum()) > 2:
            out["delta_pearson"] = float(np.corrcoef(
                d_true[mask], d_pred[mask])[0, 1])
            out["delta_pred_std"] = float(np.std(d_pred[mask]))
            # 还原成 t+3 原始强度后与真实强度的相关性（报告口径）
            s_pred_abs = np.expm1(np.log1p(np.maximum(
                pool.strength_before, 0.0)) + d_pred)
            out["strength_pearson_abs"] = float(np.corrcoef(
                pool.strength_after[mask], s_pred_abs[mask])[0, 1])
    else:
        out["strength_mse"] = None
        out["strength_bce"] = None
        out["tier_acc"] = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", action="append", default=[],
                    help="name=path（可多次）")
    ap.add_argument("--pool", default=DEFAULT_PROBLEM_PATH)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--fresh-seed", type=int, default=0,
                    help="给无头 ckpt 追加**随机初始化**头的种子（参考起点）")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if not args.ckpt:
        print("[error] 至少给一个 --ckpt name=path", file=sys.stderr)
        return 2
    pool = load_problem_pool(str(args.pool))
    if len(pool) == 0:
        print(f"[error] 题目池为空: {args.pool}", file=sys.stderr)
        return 2
    print(f"[probe] pool={args.pool} n={len(pool)} norm={pool.norm}", flush=True)
    out = {"pool": str(args.pool), "problems": int(len(pool)),
           "norm": dict(pool.norm), "arms": {}}
    from hsbg.az.train.model import attach_strength_head, load_checkpoint
    import torch
    for spec in args.ckpt:
        if "=" not in spec:
            print(f"[error] --ckpt 需要 name=path: {spec!r}", file=sys.stderr)
            return 2
        name, path = spec.split("=", 1)
        model, meta = load_checkpoint(path.strip(), device=str(args.device))
        row = {"checkpoint": path.strip(), "has_head": bool(
            getattr(model, "strength_head", None) is not None),
            "trainer_updates": meta.get("trainer_updates")}
        row.update(_probe(model, pool)
                   if row["has_head"] else _probe_no_head(model, pool))
        if not row["has_head"]:
            # 参考起点：同一权重 + 随机初始化头（同 seed 可复现）
            torch.manual_seed(int(args.fresh_seed))
            attach_strength_head(model, norm=pool.norm)
            ref = _probe(model, pool)
            for k in ("strength_mse", "strength_bce", "tier_acc",
                      "delta_pearson", "delta_pred_std",
                      "strength_pearson_abs"):
                if k in ref:
                    row[f"{k}_fresh_head"] = ref[k]
        out["arms"][name.strip()] = row
        print(f"[probe] {name.strip()}: " + json.dumps(
            {k: (round(v, 4) if isinstance(v, float) else v)
             for k, v in row.items() if k not in ("checkpoint",)}, ensure_ascii=False),
            flush=True)
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0


def _probe_no_head(model, pool) -> dict:
    """无头 ckpt：只测题目 CE（``forward_problem`` 回退到普通前向）。"""
    return _probe(model, pool)


if __name__ == "__main__":
    raise SystemExit(main())
