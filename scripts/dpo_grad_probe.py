#!/usr/bin/env python3
"""upgrade DPO 的**离线梯度占比**探针：‖g_dpo‖ / ‖g_ppo‖（不改权重、不训练）。

训练循环里的 "期望梯度占比" 需要一个不含 DPO 的 PPO 梯度作分母，而训练器里
（``--compile-train 1`` + bf16 + 16 actor）**没有**余量做第二次前向（实测直接 CUDA
OOM，且编译反向下 ``retain_graph=True`` 不可用）。因此把这一步拆成独立探针：

1. 用当前 checkpoint 采集 ``--games`` 局（默认 2 局，bot 对手、与训练同款采集配置）；
2. 构造训练同款 PPO 损失（policy/value/aux/seq/BC，``dpo_coef=0``）并求一次梯度范数
   ``‖g_ppo‖``（eager fp32 图）；
3. 从 ``bc_samples.jsonl.gz`` 的 upgrade 子集抽 ``--dpo-batch`` 条，求 one-sided DPO
   损失在 **coef=1** 时的梯度范数 ``‖g_dpo‖``；
4. 报告 ``share_per_coef = ‖g_dpo‖/‖g_ppo‖``（系数线性）：任意 ``coef`` 的单步梯度占比
   为 ``coef·share_per_coef``；按 ``--dpo-every`` 折算的平均占比再除以周期。

结果写 ``runs/dpo_grad_probe.json``；``scripts/train_entity_sync.py`` 启动时会读取它
打印 "实测梯度占比"（见 docs/DPO_UPGRADE.md）。

用法::

    PYTHONPATH=rust/python:. python scripts/dpo_grad_probe.py \
        --checkpoint runs/az_entity_s8b/model.pt --device cuda:7 --games 2 \
        --pi-coef 0.0 --seq-coef 0.05 --bc-coef 0.008 --out runs/dpo_grad_probe.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))

from hsbg.az.train.bc_aux import (  # noqa: E402
    BC_OBS_LAYOUT,
    bc_obs_batch,
    load_bc_samples,
)
from hsbg.az.train.dpo_upgrade import (  # noqa: E402
    dpo_pair_loss,
    load_upgrade_samples,
)
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import (  # noqa: E402
    CollectConfig,
    PPOConfig,
    collect_ppo_batch,
    ppo_losses,
)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _grad_norm(loss, params) -> float:
    """``loss`` 对参数的 L2 梯度范数（eager 图，retain_graph=False）。"""
    import torch

    gs = torch.autograd.grad(loss, params, retain_graph=False, allow_unused=True)
    sq = 0.0
    for g in gs:
        if g is not None:
            sq += float(g.detach().double().pow(2).sum())
    return math.sqrt(sq)


def main() -> int:
    ap = argparse.ArgumentParser(description="upgrade DPO 离线梯度占比探针")
    ap.add_argument("--checkpoint", default="runs/az_entity_s8b/model.pt")
    ap.add_argument("--arch", default="entity", choices=["tiny", "entity", "entity18m"])
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--games", type=int, default=2)
    ap.add_argument("--seed", type=int, default=15100)
    ap.add_argument("--lam", type=float, default=0.995)
    ap.add_argument("--minibatch", type=int, default=1024,
                    help="求 PPO 梯度的样本数（<=0 用整批）")
    ap.add_argument("--dpo-samples", default="data/firestone_bc/bc_samples.jsonl.gz")
    ap.add_argument("--dpo-beta", type=float, default=0.1)
    ap.add_argument("--dpo-batch", type=int, default=128)
    ap.add_argument("--dpo-every", type=int, default=4)
    ap.add_argument("--pi-coef", type=float, default=0.0)
    ap.add_argument("--seq-coef", type=float, default=0.05)
    ap.add_argument("--bc-coef", type=float, default=0.008)
    ap.add_argument("--bc-batch", type=int, default=128)
    ap.add_argument("--bc-mmr-min", type=int, default=6000)
    ap.add_argument("--bc-samples", default="data/firestone_bc/bc_samples.jsonl.gz")
    ap.add_argument("--bc-type-weight", type=float, default=1.0)
    ap.add_argument("--bc-card-weight", type=float, default=0.5)
    ap.add_argument("--move-guard", type=int, default=1, choices=[0, 1])
    ap.add_argument("--out", default="runs/dpo_grad_probe.json")
    args = ap.parse_args()
    import torch

    torch.manual_seed(int(args.seed))
    np.random.seed(int(args.seed) % (2 ** 32))

    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    arch = str(meta.get("arch", args.arch))
    model.eval()
    seq_on = bool(float(args.seq_coef) > 0.0 and getattr(model, "seq_head", None) is not None)
    if float(args.seq_coef) > 0.0 and not seq_on:
        print("[probe][warn] checkpoint 没有 seq 头 -> seq_coef=0", flush=True)
    card_on = bool(float(args.bc_card_weight) > 0.0
                   and getattr(model, "card_head", None) is not None)
    if float(args.bc_card_weight) > 0.0 and not card_on:
        print("[probe][warn] checkpoint 没有 card_head -> bc_card_weight=0", flush=True)

    # ── 1. 采集真实 PPO 批次（训练同款：bot 对手、net 行为、move-guard）────────
    t0 = time.time()
    c_cfg = CollectConfig(
        games=int(args.games), seed=int(args.seed), opponent="bot", behavior="net",
        max_actions_per_turn=40, max_steps=20000, move_guard=bool(int(args.move_guard)),
        lockstep=True, fast_act=True, seq_aux=bool(seq_on))
    batch, c_meta = collect_ppo_batch(
        model, c_cfg, device=args.device, seed=int(args.seed), gamma=1.0,
        lam=float(args.lam), progress=True)
    if len(batch) == 0:
        print("[error] 采集批次为空（全部截断？）", file=sys.stderr)
        return 2
    print(f"[probe] collect: decisions={len(batch)} games={int(args.games)} "
          f"wall={time.time() - t0:.1f}s", flush=True)

    n = int(len(batch)) if int(args.minibatch) <= 0 else min(int(args.minibatch), len(batch))
    idx = np.arange(n, dtype=np.int64)
    cfg = PPOConfig(
        epochs=1, minibatch=n, lr=1.0, seed=int(args.seed), device=str(args.device),
        amp="off", compile_train=0, pi_coef=float(args.pi_coef),
        seq_coef=(float(args.seq_coef) if seq_on else 0.0),
        entropy_coef=0.0, anchor_coef=0.0, value_coef=0.5,
        bc_coef=float(args.bc_coef), bc_batch=int(args.bc_batch),
        bc_type_weight=float(args.bc_type_weight),
        bc_card_weight=(float(args.bc_card_weight) if card_on else 0.0),
        bc_samples_path=str(args.bc_samples), bc_mmr_min=int(args.bc_mmr_min))

    # ── 2. 训练同款 BC 批次（平均系数口径，与 bc_every 无关）─────────────────
    bc_batch = None
    if float(args.bc_coef) > 0.0:
        pool = load_bc_samples(str(args.bc_samples), mmr_min=int(args.bc_mmr_min))
        if len(pool) == 0:
            print("[probe][warn] BC 池为空 -> 本次不含 BC 项", flush=True)
        else:
            rng = np.random.default_rng([int(args.seed), 0xBC])
            k = min(int(args.bc_batch), len(pool))
            bc_batch = bc_obs_batch(pool, BC_OBS_LAYOUT,
                                    indices=rng.choice(len(pool), size=k, replace=False))

    # ── 3. PPO 梯度范数（dpo_coef=0，与训练同一批损失项）──────────────────────
    params = [p for p in model.parameters() if p.requires_grad]
    ppo_out = ppo_losses(model, batch, cfg, indices=idx, anchor_logp=None,
                         train_forward=None, bc_batch=bc_batch,
                         bc_coef_override=float(args.bc_coef), dpo_batch=None)
    g_ppo = _grad_norm(ppo_out["total"], params)
    print(f"[probe] PPO: total={float(ppo_out['total']):.4f} n={n} "
          f"||g_ppo||={g_ppo:.6g}", flush=True)

    # ── 4. upgrade DPO 梯度范数（coef=1）────────────────────────────────────
    upool = load_upgrade_samples(str(args.dpo_samples))
    if len(upool) == 0:
        print("[error] upgrade 池为空", file=sys.stderr)
        return 2
    rng = np.random.default_rng([int(args.seed), 0x0D0])
    k = min(int(args.dpo_batch), len(upool))
    dpo = upool.take(rng.choice(len(upool), size=k, replace=False))
    dpo_loss, accept = dpo_pair_loss(model, dpo, float(args.dpo_beta),
                                     device=str(args.device))
    g_dpo = _grad_norm(dpo_loss, params)
    share_per_coef = float(g_dpo / g_ppo) if g_ppo > 0.0 else float("nan")
    print(f"[probe] DPO: loss={float(dpo_loss):.4f} accept={accept:.3f} n={k} "
          f"||g_dpo||={g_dpo:.6g}", flush=True)
    print(f"[probe] share_per_coef=||g_dpo||/||g_ppo||={share_per_coef:.6g} "
          f"-> coef=0.002 单步 {0.002 * share_per_coef * 100:.3f}%，"
          f"coef=0.005 单步 {0.005 * share_per_coef * 100:.3f}%", flush=True)

    out = {
        "checkpoint": args.checkpoint,
        "checkpoint_sha256": _sha256(args.checkpoint),
        "arch": arch,
        "device": str(args.device),
        "games": int(args.games),
        "seed": int(args.seed),
        "dpo_beta": float(args.dpo_beta),
        "dpo_batch": int(k),
        "dpo_every": int(args.dpo_every),
        "ppo": {"n": int(n), "total": float(ppo_out["total"]),
                "grad_norm": float(g_ppo),
                "seq_coef": float(args.seq_coef) if seq_on else 0.0,
                "bc_coef": float(args.bc_coef), "bc_card_weight": (
                    float(args.bc_card_weight) if card_on else 0.0)},
        "dpo": {"loss": float(dpo_loss), "accept_rate": float(accept),
                "grad_norm": float(g_dpo)},
        "share_per_coef": share_per_coef,
        "share_at": {f"{c:g}": {
            "step": float(c) * share_per_coef,
            "avg_per_iter": float(c) * share_per_coef
            / max(1, int(args.dpo_every))}
            for c in (0.002, 0.005)},
        "collect": {k2: c_meta.get(k2) for k2 in ("decisions", "wall_s")},
        "elapsed_s": time.time() - t0,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[probe] written {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
