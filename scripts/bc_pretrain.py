#!/usr/bin/env python3
"""BC 预训练 warm-start（阶段 A：先把模型训成“像人类”的起点，再交给 PPO + KL anchor）。

与现有 ``bc_coef=0.004`` 的**辅助正则**不同，本脚本把真实人类对局（Firestone 回放）
当作**主监督目标**做真正的监督预训练：

1. :func:`hsbg.az.train.bc_aux.load_bc_samples` 读 ``data/firestone_bc/bc_samples.jsonl.gz``
   并按 MMR / 动作白名单 / 动作下标过滤；
2. 从 ``--init`` checkpoint 续训（默认 ``runs/az_entity_s8b/model.pt``）或 ``--from-scratch``；
3. Adam + 分层 BC 损失（9 类动作类型 CE + 3983 类卡牌身份 CE，权重 1.0 / 0.5），
   默认不做 value（BC 样本无名次标签，``--value-coef`` 只保留接口）；
4. 留 ``--holdout`` 比例的样本算 eval CE，每 ``--log-every`` 步打印 loss/type/card/acc；
5. ``--preserve-rl 1``（默认）时，训练前记录原策略在 holdout 上的分布，训练后报告
   ``KL(pre‖post)``，超过 ``--max-kl`` 时告警（提示可能遗忘 RL 起点）；
6. 保存 ``--out/model.pt``，meta 带 ``bc_pretrained=True`` / ``bc_steps`` / ``samples`` 等。

**实证注意（见 docs/BC_PRETRAIN.md §5/§9）**：分层 BC 默认只监督 9 类白名单动作，
Move 族（196..244）完全不受约束，而 entity 的 Move logits 是棋盘 token 的双线性项；实测
200 步 @ lr 1e-4 会把 moves/turn 从 2.4 推到 17.3、top4 从 96% 打到 29%。修复路径：
``--bc-include-reposition 1``（reposition 作为第 10 类纳入 type CE）和/或
``--bc-move-anchor-coef``（Move 段 MSE 锚到初始权重）。两者**默认关闭**，关闭时与
历史 9 类实现逐位等价。

训练完成后如何接 PPO（锚住 BC 起点）见 ``docs/BC_PRETRAIN.md``::

    python scripts/train_entity_sync.py \
        --checkpoint runs/bc_pretrain/model.pt --anchor-beta 0.1 ...

用法::

    # 现状对照（9 类，无 Move 监督）
    PYTHONPATH=rust/python:. python scripts/bc_pretrain.py \
        --init runs/az_entity_s8b/model.pt --limit 20000 --steps 200 \
        --device cuda:7 --out runs/bc_pretrain

    # 实验 B：reposition（Move 196..244）作为第 10 类纳入 BC
    python scripts/bc_pretrain.py --init runs/az_entity_s8b/model.pt --limit 20000 \
        --steps 200 --bc-include-reposition 1 --out runs/bc_pretrain_moveB

    # 实验 C：B + Move logits 定向锚定（coef*MSE(θ, θ_init)）
    python scripts/bc_pretrain.py --init runs/az_entity_s8b/model.pt --limit 20000 \
        --steps 200 --bc-include-reposition 1 --bc-move-anchor-coef 0.1 \
        --out runs/bc_pretrain_moveC

    # 稀有类别加权（reposition 放大 2 倍）
    python scripts/bc_pretrain.py ... --bc-include-reposition 1 \
        --bc-class-weight "reposition=2"

    # 可选：全 245 分布 KL 蒸馏锚定（实验性；实测 β=1 仍会漂移，见 docs §5.2）
    python scripts/bc_pretrain.py --init runs/az_entity_s8b/model.pt --limit 20000 \
        --steps 200 --anchor-beta 1.0 --anchor-temperature 2.0 --out runs/bc_pretrain_anchor

    # 单测/冒烟（CPU、tiny、合成数据）
    python scripts/bc_pretrain.py --from-scratch --arch tiny --device cpu \
        --samples /tmp/bc.jsonl.gz --cards /tmp/cards.json --steps 3 --batch 256
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hsbg.az.train.bc_aux import (  # noqa: E402
    BC_MOVE_SLICE,
    BC_REPOSITION_TYPE,
    DEFAULT_BC_ACTION_TYPES,
    DEFAULT_BC_SAMPLES_PATH,
    DEFAULT_MMR_MIN,
    bc_card_head_size,
    bc_hier_loss,
    bc_obs_batch,
    load_bc_samples,
    parse_bc_class_weights,
)
from hsbg.az.train.model import (  # noqa: E402
    attach_bc_card_head,
    attach_move_head_split,
    build_net,
    load_checkpoint,
    save_checkpoint,
)

DEFAULT_INIT = os.path.join(ROOT, "runs", "az_entity_s8b", "model.pt")
DEFAULT_OUT = os.path.join(ROOT, "runs", "bc_pretrain")


# ══════════════════════════════════════════════════════════════════════════
# 0. 工具
# ══════════════════════════════════════════════════════════════════════════
def _torch():
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("torch 不可用：BC 预训练需要 `pip install torch`") from exc
    return torch


def _jsonable(value: Any) -> Any:
    """递归转成可 ``json.dump`` 的纯 Python 类型（numpy 标量/数组）。"""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def split_holdout(n: int, frac: float, seed: int = 0) -> Tuple[np.ndarray, np.ndarray]:
    """按 ``seed`` 随机切 holdout，返回 ``(train_idx, holdout_idx)``。

    保证：两段**不重叠**、并集恰为 ``0..n-1``；``frac<=0`` 时不留 holdout；
    ``n<2`` 时也不留（否则没有训练样本可跑）。
    """
    n = int(n)
    if n < 0:
        raise ValueError(f"样本数不能为负：{n}")
    frac = float(frac)
    if not (0.0 <= frac < 1.0):
        raise ValueError(f"holdout 比例必须落在 [0,1)：{frac}")
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    perm = rng.permutation(n).astype(np.int64)
    k = int(round(frac * float(n)))
    if n >= 2 and frac > 0.0:
        k = max(1, min(n - 1, k))
    else:
        k = 0
    return perm[k:].copy(), perm[:k].copy()


def _resolve_device(torch: Any, requested: str) -> str:
    dev = str(requested or "cpu").strip() or "cpu"
    if dev.startswith("cuda") and not bool(torch.cuda.is_available()):
        print(f"[warn] cuda 不可用：请求 {dev} -> 回退 cpu", flush=True)
        return "cpu"
    return dev


def _batch_tensors(torch: Any, device: Any, batch: Any) -> Dict[str, Any]:
    """``BCObsBatch`` -> 设备上的 torch 张量（显式 dtype，避免 bool/int 混用）。"""

    def _t(arr: Any, dtype: Any) -> Any:
        return torch.from_numpy(np.ascontiguousarray(arr)).to(device=device,
                                                             dtype=dtype)

    counts = np.asarray(batch.class_counts, dtype=np.int64)
    return {
        "x": _t(batch.features, torch.float32),
        "cards": _t(batch.cards, torch.int64),
        "action_mask": _t(batch.action_mask, torch.bool),
        "type_ids": _t(batch.type_ids, torch.int64),
        "target_class": _t(batch.class_ids, torch.int64),
        "target_action": _t(batch.action_index, torch.int64),
        "weights": _t(batch.weights, torch.float32),
        "card_target": _t(batch.card_target, torch.int64),
        "card_valid": _t(batch.card_valid, torch.bool),
        "class_weight": _t(batch.class_weight, torch.float32),
        "class_counts": counts,
        "n_types": int(counts.size),
    }


def _forward_bc(model: Any, features: Any, cards: Any, mask: Any):
    """一次前向 -> ``(policy_logits, card_logits|None)``。

    优先走模型自带的 ``forward_bc``（tiny/entity 都有，一次前向同时出两个头）；
    测试替身没有该方法时退回普通 ``forward``（只有类型级 CE）。
    """
    import inspect

    fn = getattr(model, "forward_bc", None)
    if fn is not None:
        try:
            accepts_mask = "mask" in inspect.signature(fn).parameters
        except (TypeError, ValueError):  # pragma: no cover - 内建 forward
            accepts_mask = False
        out = fn(features, cards, mask) if accepts_mask else fn(features, cards)
        if not isinstance(out, (tuple, list)) or len(out) != 2:
            raise ValueError("forward_bc 必须返回 (policy_logits, card_logits|None)")
        return out[0], out[1]
    out = model(features, cards, mask)
    if not isinstance(out, (tuple, list)):
        raise ValueError("模型 forward 必须返回元组")
    return out[0], None


def _hier_loss(model: Any, batch: Dict[str, Any], args: argparse.Namespace,
               torch: Any) -> Tuple[Dict[str, Any], Any]:
    """分层 BC 损失（与 PPO 的 BC 分支同一实现/同一权重）。"""
    policy_logits, card_logits = _forward_bc(
        model, batch["x"], batch["cards"], batch["action_mask"])
    policy_logits = policy_logits.float()
    if card_logits is not None:
        card_logits = card_logits.float()
    # class_counts 全 1 时 ``bc_class_balance_weights`` 得到全 1 权重（= 关闭类别平衡）
    n_types = int(batch["n_types"])
    counts = (np.asarray(batch["class_counts"], dtype=np.int64)
              if int(getattr(args, "class_balance", 1))
              else np.ones(n_types, dtype=np.int64))
    hier = bc_hier_loss(
        policy_logits, batch["type_ids"], batch["target_class"],
        action_mask=batch["action_mask"], card_logits=card_logits,
        card_target=batch["card_target"], card_valid=batch["card_valid"],
        weights=batch["weights"], class_counts=counts,
        class_weight=batch["class_weight"],
        type_weight=float(args.type_weight), card_weight=float(args.card_weight),
        n_types=n_types)
    return hier, policy_logits


def _move_anchor_mse(model: Any, teacher: Any, batch: Dict[str, Any],
                     policy_logits: Any, torch: Any) -> Any:
    """``MSE``（只取 Move 段 196..244）= ``--bc-move-anchor-coef`` 的正则项。

    参考值来自**加载时冻结的初始权重**（``teacher``）在同一个 batch 上的 Move logits。
    学生 logits 复用本步 BC 前向的结果（与 teacher 同 ``action_mask``），只在**实际
    候选 Move 位**上求均方误差，避免被 ``-1e9`` 掩码填充值放大。

    若本 batch 的 ``action_mask`` 里没有任何 Move 候选（9 类模式 / 棋盘都 < 2 张），
    退回**无掩码前向**（学生 + 教师各一次）在全部 49 个 Move logits 上求 MSE——这样
    单独打开锚定（不带 reposition 监督）时仍然有效。

    注意：``MSE(θ, θ_init)`` 在 ``θ=θ_init`` 处梯度为 0，因此训练**第 1 步**的更新
    与不加锚定时逐位相同；锚定从第 2 步开始生效（二次势阱）。
    """
    lo = int(BC_MOVE_SLICE.start)
    hi = int(BC_MOVE_SLICE.stop)
    x, cards = batch["x"], batch["cards"]
    am = batch["action_mask"]
    sel = am[:, lo:hi]
    if bool(sel.any()):
        with torch.no_grad():
            teacher_logits, _ = _forward_bc(teacher, x, cards, am)
        diff = policy_logits[:, lo:hi].float() - teacher_logits[:, lo:hi].float()
        d = diff[sel]
        return (d * d).mean()
    with torch.no_grad():
        teacher_logits, _ = _forward_bc(teacher, x, cards, None)
    student_logits, _ = _forward_bc(model, x, cards, None)
    diff = (student_logits[:, lo:hi].float()
            - teacher_logits[:, lo:hi].float())
    return (diff * diff).mean()


def _anchor_kl(teacher: Any, model: Any, batch: Dict[str, Any], *,
               scope: str, temperature: float, torch: Any) -> Any:
    """对**冻结的初始策略**做知识蒸馏：``KL(π_θ ‖ π_init)``（fp32，逐样本平均）。

    动机：分层 BC 只监督 9 类白名单动作（``type_ids`` 覆盖的动作），**Move/Freeze/
    DarkGift 等族完全不受约束**，而 entity 的 Move 头是棋盘 token 的双线性
    ``hb_i·hb_j``，其相对尺度会随 BC 梯度漂移，导致推理时 Move 抢占 argmax。
    这里在**全部 245 个动作**上把学生的分布锚回 init（``--anchor-scope all``），
    只允许白名单动作族在受控范围内移动。

    ``scope="bc"`` 时只在 BC 候选动作（``action_mask``）上比较（重新归一化）。
    ``temperature`` 越大越“看”低概率动作（标准蒸馏写法，梯度乘 T²）。
    """
    x, cards = batch["x"], batch["cards"]
    with torch.no_grad():
        teacher_logits, _ = _forward_bc(teacher, x, cards, None)
        teacher_logits = teacher_logits.float()
    student_logits, _ = _forward_bc(model, x, cards, None)
    student_logits = student_logits.float()
    if str(scope) == "bc":
        m = batch["action_mask"]
        teacher_logits = teacher_logits.masked_fill(~m, -1e30)
        student_logits = student_logits.masked_fill(~m, -1e30)
    t = float(temperature) if float(temperature) > 0.0 else 1.0
    t_logp = torch.log_softmax(teacher_logits / t, dim=-1)
    s_logp = torch.log_softmax(student_logits / t, dim=-1)
    p = s_logp.exp()
    return (p * (s_logp - t_logp)).sum(dim=-1).mean() * (t * t)


def _step_acc(policy_logits: Any, hier: Dict[str, Any], batch: Dict[str, Any],
              torch: Any) -> Tuple[float, float]:
    """本步 top-1：类型准确率（9 类）与动作准确率（245 维 masked argmax）。"""
    with torch.no_grad():
        type_pred = hier["type_logits"].argmax(dim=-1)
        type_acc = float((type_pred == batch["target_class"]).float().mean().cpu())
        logits = policy_logits.masked_fill(~batch["action_mask"], -1e30)
        act_pred = logits.argmax(dim=-1)
        act_acc = float((act_pred == batch["target_action"]).float().mean().cpu())
    return type_acc, act_acc


# ── holdout 评估 / KL ────────────────────────────────────────────────────
def _collect_holdout(torch: Any, model: Any, samples: Any, indices: np.ndarray,
                     *, batch_size: int, device: Any) -> Dict[str, Any]:
    """在 holdout 上跑一遍前向，收集 logits 与标签（eval 模式、fp32、no_grad）。"""
    if int(indices.size) == 0:
        return {"policy_logits": np.zeros((0, 245), dtype=np.float32),
                "card_logits": None, "action_mask": np.zeros((0, 245), dtype=bool),
                "type_ids": np.zeros((0, 245), dtype=np.int64),
                "target_class": np.zeros(0, dtype=np.int64),
                "target_action": np.zeros(0, dtype=np.int64),
                "weights": np.zeros(0, dtype=np.float32),
                "card_target": np.zeros(0, dtype=np.int64),
                "card_valid": np.zeros(0, dtype=bool),
                "class_counts": np.asarray(samples.class_counts, dtype=np.int64)}
    was_training = bool(getattr(model, "training", False))
    model.eval()
    out: Dict[str, List[np.ndarray]] = {"policy": [], "card": [], "mask": [],
                                        "tids": [], "target": [], "aidx": [],
                                        "weights": [], "card_tgt": [], "card_ok": []}
    with torch.no_grad():
        for start in range(0, int(indices.size), int(batch_size)):
            sub = indices[start:start + int(batch_size)]
            raw = bc_obs_batch(samples, indices=sub)
            bt = _batch_tensors(torch, device, raw)
            policy_logits, card_logits = _forward_bc(
                model, bt["x"], bt["cards"], bt["action_mask"])
            out["policy"].append(policy_logits.float().cpu().numpy())
            if card_logits is not None:
                out["card"].append(card_logits.float().cpu().numpy())
            out["mask"].append(np.asarray(raw.action_mask, dtype=bool))
            out["tids"].append(np.asarray(raw.type_ids, dtype=np.int64))
            out["target"].append(np.asarray(raw.class_ids, dtype=np.int64))
            out["aidx"].append(np.asarray(raw.action_index, dtype=np.int64))
            out["weights"].append(np.asarray(raw.weights, dtype=np.float32))
            out["card_tgt"].append(np.asarray(raw.card_target, dtype=np.int64))
            out["card_ok"].append(np.asarray(raw.card_valid, dtype=bool))
    if was_training:
        model.train()
    return {
        "policy_logits": np.concatenate(out["policy"], axis=0).astype(np.float32),
        "card_logits": (np.concatenate(out["card"], axis=0).astype(np.float32)
                        if out["card"] else None),
        "action_mask": np.concatenate(out["mask"], axis=0).astype(bool),
        "type_ids": np.concatenate(out["tids"], axis=0).astype(np.int64),
        "target_class": np.concatenate(out["target"], axis=0).astype(np.int64),
        "target_action": np.concatenate(out["aidx"], axis=0).astype(np.int64),
        "weights": np.concatenate(out["weights"], axis=0).astype(np.float32),
        "card_target": np.concatenate(out["card_tgt"], axis=0).astype(np.int64),
        "card_valid": np.concatenate(out["card_ok"], axis=0).astype(bool),
        "class_counts": np.asarray(samples.class_counts, dtype=np.int64),
    }


def _eval_ce(torch: Any, collected: Dict[str, Any],
             args: argparse.Namespace) -> Dict[str, Any]:
    """从收集到的 holdout logits 直接算子集 CE（与训练同一套加权/分层口径）。"""
    n = int(collected["policy_logits"].shape[0])
    if n == 0:
        return {"n": 0, "loss": None, "type_ce": None, "card_ce": None,
                "type_acc": None, "action_acc": None}
    policy_logits = torch.from_numpy(collected["policy_logits"])
    card_logits = (None if collected["card_logits"] is None
                   else torch.from_numpy(collected["card_logits"]))
    action_mask = torch.from_numpy(collected["action_mask"])
    type_ids = torch.from_numpy(collected["type_ids"].astype(np.int64))
    target_class = torch.from_numpy(collected["target_class"].astype(np.int64))
    target_action = torch.from_numpy(collected["target_action"].astype(np.int64))
    weights = torch.from_numpy(collected["weights"].astype(np.float32))
    card_target = torch.from_numpy(collected["card_target"].astype(np.int64))
    card_valid = torch.from_numpy(collected["card_valid"].astype(bool))
    counts = (np.asarray(collected["class_counts"], dtype=np.int64)
              if int(getattr(args, "class_balance", 1))
              else np.ones(int(np.asarray(collected["class_counts"]).size),
                           dtype=np.int64))
    n_types = int(np.asarray(collected["class_counts"]).size)
    hier = bc_hier_loss(
        policy_logits, type_ids, target_class, action_mask=action_mask,
        card_logits=card_logits, card_target=card_target,
        card_valid=card_valid, weights=weights,
        class_counts=counts,
        type_weight=float(args.type_weight), card_weight=float(args.card_weight),
        n_types=n_types)
    with torch.no_grad():
        logits = policy_logits.float().masked_fill(~action_mask, -1e30)
        type_acc = float((hier["type_logits"].argmax(-1) == target_class)
                         .float().mean())
        action_acc = float((logits.argmax(-1) == target_action).float().mean())
    return {
        "n": n,
        "loss": float(hier["loss"].detach()),
        "type_ce": float(hier["type_loss"].detach()),
        "card_ce": float(hier["card_loss"].detach()),
        "type_acc": type_acc,
        "action_acc": action_acc,
    }


def _masked_log_probs(logits: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """masked softmax 的 log 概率（mask 外 = -inf，行内数值稳定）。"""
    z = np.asarray(logits, dtype=np.float64).copy()
    m = np.asarray(mask, dtype=bool)
    z[~m] = -np.inf
    row_max = np.max(z, axis=-1, keepdims=True)
    # 每行至少有一个合法动作（bc_obs_batch 会强制补上真实动作），max 不会全 -inf
    exp = np.exp(z - row_max)
    lse = row_max + np.log(np.sum(exp, axis=-1, keepdims=True))
    return z - lse


def policy_kl(pre_logits: np.ndarray, post_logits: np.ndarray,
              mask: np.ndarray) -> np.ndarray:
    """逐样本 ``KL(pre‖post) = Σ_a p_pre(a)·(log p_pre(a) − log p_post(a))``。

    ``mask`` = 合法/候选动作集合（与训练/评测同一近似动作掩码）；mask 外的项不参与，
    避免 ``0·inf`` 产生 NaN。
    """
    m = np.asarray(mask, dtype=bool)
    lp = _masked_log_probs(pre_logits, m)
    lq = _masked_log_probs(post_logits, m)
    p = np.exp(lp)
    diff = np.zeros_like(lp)
    # 只在合法动作上做差：mask 外 lp/lq 都是 -inf，先减再 where 会产生 inf-inf 警告
    diff[m] = lp[m] - lq[m]
    return np.sum(p * diff, axis=-1)


def _kl_summary(pre: Dict[str, Any], post: Dict[str, Any],
                max_kl: float) -> Dict[str, Any]:
    m = pre["action_mask"]
    kl = policy_kl(pre["policy_logits"], post["policy_logits"], m)
    pre_arg = np.argmax(np.where(m, pre["policy_logits"], -np.inf), axis=-1)
    post_arg = np.argmax(np.where(m, post["policy_logits"], -np.inf), axis=-1)
    return {
        "n": int(kl.size),
        "kl_mean": float(np.mean(kl)),
        "kl_p50": float(np.percentile(kl, 50)),
        "kl_p95": float(np.percentile(kl, 95)),
        "kl_max": float(np.max(kl)),
        "top1_agree": float(np.mean(pre_arg == post_arg)),
        "max_kl": float(max_kl),
        "exceeds_max_kl": bool(float(np.mean(kl)) > float(max_kl)),
    }


# ══════════════════════════════════════════════════════════════════════════
# 1. CLI
# ══════════════════════════════════════════════════════════════════════════
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="BC 预训练 warm-start（人类对局监督 -> 再 PPO + KL anchor）")
    # 数据
    ap.add_argument("--samples", default=DEFAULT_BC_SAMPLES_PATH,
                    help="BC 样本 JSONL(.gz) 路径")
    ap.add_argument("--cards", default=None,
                    help="BC 卡表路径（默认仓库 rust 卡表；单测用合成卡表）")
    ap.add_argument("--mmr-min", type=int, default=DEFAULT_MMR_MIN,
                    help="MMR 下限（默认 6000）")
    ap.add_argument("--action-types", default="",
                    help="逗号分隔动作类型白名单（空 = 默认 9 类）")
    ap.add_argument("--limit", type=int, default=0, help="样本上限（0 = 全部）")
    ap.add_argument("--holdout", type=float, default=0.05,
                    help="holdout 比例（默认 0.05）")
    # 模型
    ap.add_argument("--init", default=DEFAULT_INIT,
                    help="初始 checkpoint（默认 runs/az_entity_s8b/model.pt）")
    ap.add_argument("--from-scratch", action="store_true",
                    help="忽略 --init，随机初始化（配合 --arch）")
    ap.add_argument("--arch", default="entity",
                    choices=["tiny", "entity", "entity18m"],
                    help="--from-scratch 时使用的网络结构（默认 entity）")
    ap.add_argument("--hidden", type=int, default=256, help="tiny 隐藏维")
    ap.add_argument("--d-model", type=int, default=384, help="entity d_model")
    ap.add_argument("--n-layers", type=int, default=8, help="entity 层数")
    ap.add_argument("--n-heads", type=int, default=8, help="entity 头数")
    ap.add_argument("--seq-head", type=int, default=0, choices=[0, 1],
                    help="from-scratch 时是否建动作序列辅助头（默认 0）")
    ap.add_argument("--move-head-split", type=int, default=0, choices=[0, 1],
                    help="from-scratch 建/续训追加有向 Move 头（默认 0）")
    ap.add_argument("--card-dim", type=int, default=0,
                    help="卡牌身份头维度（0 = 按卡表条目数）")
    # 优化
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--eval-batch", type=int, default=512)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--steps", type=int, default=0,
                    help="总优化步上限（0 = epochs × ceil(n_train/batch)）")
    ap.add_argument("--grad-clip", type=float, default=1.0)
    ap.add_argument("--amp", default="bf16", choices=["bf16", "off"])
    ap.add_argument("--type-weight", type=float, default=1.0)
    ap.add_argument("--card-weight", type=float, default=0.5)
    ap.add_argument("--class-balance", type=int, default=1, choices=[0, 1],
                    help="1=类型 CE 用类别频率倒数加权（PPO 辅助 BC 的默认口径，"
                         "会大幅上采样 upgrade/hero_power 等稀有动作）；"
                         "0=自然频率（更忠实模仿人类动作分布）")
    ap.add_argument("--bc-include-reposition", type=int, default=0, choices=[0, 1],
                    help="1 = 把 reposition（Move 196..244）作为第 10 类纳入分层 BC "
                         "（默认 0 = 历史 9 类，逐位等价）")
    ap.add_argument("--bc-class-weight", default="",
                    help='稀有类别权重覆盖，如 "reposition=2,upgrade=4"（空 = 不覆盖；'
                         'reposition 需要 --bc-include-reposition 1）')
    ap.add_argument("--bc-move-anchor-coef", type=float, default=0.0,
                    help="Move 段（196..244）MSE 锚定系数：coef*MSE(θ, θ_init)，"
                         "默认 0 = 关闭；第 1 步更新与关闭时逐位相同（二次势阱）")
    ap.add_argument("--value-coef", type=float, default=0.0,
                    help="value 损失权重（BC 样本无名次标签 -> 只保留接口，>0 会告警并忽略）")
    ap.add_argument("--anchor-beta", type=float, default=0.0,
                    help="KL(π_θ‖π_init) 蒸馏锚定权重（0=关闭；防 BC 把 Move 头带飞）")
    ap.add_argument("--anchor-scope", default="all", choices=["all", "bc"],
                    help="锚定分布范围：all=全部 245 动作（默认），bc=仅 BC 候选动作")
    ap.add_argument("--anchor-temperature", type=float, default=1.0,
                    help="蒸馏温度 T（越大越看低概率动作，梯度乘 T²）")
    ap.add_argument("--seed", type=int, default=0)
    # 日志 / 保留 RL
    ap.add_argument("--log-every", type=int, default=20)
    ap.add_argument("--eval-every", type=int, default=0,
                    help="每隔多少步评 holdout CE（0 = 自动 max(1, total//10)）")
    ap.add_argument("--preserve-rl", type=int, default=1, choices=[0, 1],
                    help="1 = 训练前后在 holdout 上量 KL(pre‖post)（默认）")
    ap.add_argument("--max-kl", type=float, default=2.0,
                    help="KL 告警阈值（默认 2.0 nats）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出目录（含 model.pt）")
    ap.add_argument("--report", default="", help="报告 JSON（默认 <out>/report.json）")
    return ap.parse_args(argv)


# ══════════════════════════════════════════════════════════════════════════
# 2. 主流程
# ══════════════════════════════════════════════════════════════════════════
def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if int(args.batch) <= 0 or int(args.eval_batch) <= 0:
        print("[error] --batch / --eval-batch 必须 > 0", file=sys.stderr)
        return 2
    if int(args.epochs) <= 0 or int(args.steps) < 0:
        print("[error] --epochs 必须 > 0，--steps 必须 >= 0", file=sys.stderr)
        return 2
    if float(args.holdout) < 0.0 or float(args.holdout) >= 1.0:
        print("[error] --holdout 必须在 [0,1)", file=sys.stderr)
        return 2
    if int(args.preserve_rl) and float(args.max_kl) <= 0.0:
        print("[error] --max-kl 必须 > 0", file=sys.stderr)
        return 2
    if float(args.anchor_beta) < 0.0:
        print("[error] --anchor-beta 必须 >= 0", file=sys.stderr)
        return 2
    if float(args.bc_move_anchor_coef) < 0.0:
        print("[error] --bc-move-anchor-coef 必须 >= 0", file=sys.stderr)
        return 2
    if not args.from_scratch and not os.path.isfile(args.init):
        print(f"[error] --init 不存在: {args.init}"
              f"（或用 --from-scratch）", file=sys.stderr)
        return 2
    if args.cards is not None and not os.path.isfile(args.cards):
        print(f"[error] --cards 不存在: {args.cards}", file=sys.stderr)
        return 2
    if not os.path.isfile(args.samples):
        print(f"[error] --samples 不存在: {args.samples}", file=sys.stderr)
        return 2

    try:
        torch = _torch()
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    torch.manual_seed(int(args.seed))
    np.random.seed(int(args.seed) % (2 ** 32))
    device = _resolve_device(torch, args.device)
    use_amp = (str(args.amp).lower() in ("bf16", "bfloat16")
               and str(device).startswith("cuda"))
    os.makedirs(args.out, exist_ok=True)

    if float(args.value_coef) > 0.0:
        print("[warn] BC 样本没有名次/价值标签：--value-coef>0 被忽略（本次不做 value 损失）",
              flush=True)

    # ── 1) 数据 ──────────────────────────────────────────────────────────
    action_types: Optional[Tuple[str, ...]] = None
    if str(args.action_types).strip():
        action_types = tuple(x.strip() for x in str(args.action_types).split(",")
                             if x.strip())
    # 可选第 10 类 reposition（Move 196..244）：默认关闭 = 历史 9 类
    if int(args.bc_include_reposition):
        base_types = tuple(action_types or DEFAULT_BC_ACTION_TYPES)
        action_types = (base_types if BC_REPOSITION_TYPE in base_types
                        else base_types + (BC_REPOSITION_TYPE,))
    # 稀有类别权重覆盖："reposition=2,upgrade=4"（空 = 不覆盖）
    try:
        class_weight_overrides = parse_bc_class_weights(
            str(args.bc_class_weight), action_types or DEFAULT_BC_ACTION_TYPES)
    except ValueError as exc:
        print(f"[error] --bc-class-weight 非法: {exc}", file=sys.stderr)
        return 2
    n_types = len(action_types or DEFAULT_BC_ACTION_TYPES)
    t0 = time.time()
    try:
        samples = load_bc_samples(
            args.samples, mmr_min=int(args.mmr_min),
            limit=(int(args.limit) if int(args.limit) > 0 else None),
            action_types=action_types, cards_path=args.cards,
            class_weight_overrides=(class_weight_overrides or None))
    except Exception as exc:  # noqa: BLE001 - 数据/卡表错误要给人话
        print(f"[error] 加载 BC 样本失败: {exc!r}", file=sys.stderr)
        return 2
    load_s = time.time() - t0
    n_total = int(len(samples))
    if n_total < 2:
        print(f"[error] 过滤后样本太少：{n_total} 条", file=sys.stderr)
        return 2
    print(f"[data] {args.samples} samples={n_total} "
          f"mmr_min={int(args.mmr_min)} load={load_s:.1f}s", flush=True)
    print(f"[data] class_distribution={json.dumps(samples.class_distribution(), ensure_ascii=False)}",
          flush=True)

    train_idx, hold_idx = split_holdout(n_total, float(args.holdout),
                                        int(args.seed))
    n_train, n_hold = int(train_idx.size), int(hold_idx.size)
    if n_train <= 0:
        print("[error] holdout 后没有训练样本（请减小 --holdout）", file=sys.stderr)
        return 2
    print(f"[data] train={n_train} holdout={n_hold} "
          f"({float(n_hold) / max(1, n_total):.3f}) seed={int(args.seed)}", flush=True)

    # ── 2) 模型 ──────────────────────────────────────────────────────────
    card_dim = int(args.card_dim) if int(args.card_dim) > 0 else 0
    if card_dim <= 0 and float(args.card_weight) > 0.0:
        card_dim = int(bc_card_head_size(args.cards))
    meta_in: Dict[str, Any] = {}
    norm_mean = norm_std = None
    if args.from_scratch:
        kwargs: Dict[str, Any] = {
            "arch": args.arch,
            "seq_head": bool(int(args.seq_head)),
            "bc_card_head": bool(float(args.card_weight) > 0.0),
            "move_head_split": bool(int(args.move_head_split)),
        }
        if kwargs["bc_card_head"]:
            kwargs["bc_card_dim"] = card_dim
        if args.arch == "tiny":
            kwargs["hidden"] = int(args.hidden)
        else:
            kwargs["d_model"] = int(args.d_model)
            kwargs["n_layers"] = int(args.n_layers)
            kwargs["n_heads"] = int(args.n_heads)
        model = build_net(**kwargs)
        print(f"[net] from-scratch arch={args.arch} card_head={kwargs['bc_card_head']}"
              f" card_dim={card_dim if kwargs['bc_card_head'] else 0}", flush=True)
    else:
        model, meta_in = load_checkpoint(args.init, device=device)
        norm_mean = meta_in.get("norm_mean")
        norm_std = meta_in.get("norm_std")
        print(f"[net] init={args.init} arch={meta_in.get('arch', '?')} "
              f"trainer_updates={meta_in.get('trainer_updates', '?')}", flush=True)
        if float(args.card_weight) > 0.0 and getattr(model, "card_head", None) is None:
            attach_bc_card_head(model, dim=(card_dim or None))
            print(f"[net] init 无 card_head：已追加 Linear(., {card_dim})", flush=True)
        if int(args.move_head_split) and not getattr(model, "move_head_split", False):
            attach_move_head_split(model)
            print("[net] 已追加有向 Move 头（move_from/move_to）", flush=True)
    model.to(torch.device(device))
    n_params = int(sum(p.numel() for p in model.parameters()))
    print(f"[net] device={device} amp={'bf16' if use_amp else 'off'} "
          f"params={n_params:,}", flush=True)
    # KL / Move 锚定：冻结一份训练前的策略做参考（--anchor-beta 或
    # --bc-move-anchor-coef > 0 才建，额外 ~1x 参数内存）
    teacher = None
    if float(args.anchor_beta) > 0.0 or float(args.bc_move_anchor_coef) > 0.0:
        teacher = copy.deepcopy(model).to(torch.device(device))
        teacher.eval()
        for p in teacher.parameters():
            p.requires_grad_(False)
        if float(args.anchor_beta) > 0.0:
            print(f"[bc] anchor: KL(π_θ‖π_init) beta={float(args.anchor_beta)} "
                  f"scope={args.anchor_scope} T={float(args.anchor_temperature)}",
                  flush=True)
        if float(args.bc_move_anchor_coef) > 0.0:
            print(f"[bc] move-anchor: coef*MSE(move_logits[196:245], init) "
                  f"coef={float(args.bc_move_anchor_coef)}（第 1 步无梯度，"
                  f"从第 2 步生效）", flush=True)

    opt = torch.optim.Adam(model.parameters(), lr=float(args.lr))
    steps_per_epoch = int(math.ceil(n_train / float(args.batch)))
    total_steps = int(steps_per_epoch) * int(args.epochs)
    if int(args.steps) > 0:
        total_steps = min(total_steps, int(args.steps))
    total_steps = max(1, total_steps)
    eval_every = (int(args.eval_every) if int(args.eval_every) > 0
                  else max(1, total_steps // 10))
    print(f"[bc] batch={int(args.batch)} lr={float(args.lr)} steps={total_steps} "
          f"(≈{total_steps * int(args.batch) / max(1, n_train):.2f} epoch) "
          f"type_w={float(args.type_weight)} card_w={float(args.card_weight)} "
          f"class_balance={int(args.class_balance)} n_types={n_types} "
          f"include_reposition={int(args.bc_include_reposition)} "
          f"class_weight={json.dumps(class_weight_overrides, ensure_ascii=False)} "
          f"move_anchor_coef={float(args.bc_move_anchor_coef)} "
          f"clip={float(args.grad_clip)} eval_every={eval_every}", flush=True)

    # ── 3) 训练前 holdout 基线（eval CE + 原策略分布）─────────────────────
    pre = _collect_holdout(torch, model, samples, hold_idx,
                           batch_size=int(args.eval_batch), device=device)
    base = _eval_ce(torch, pre, args)
    eval_curve: List[Dict[str, Any]] = [{
        "step": 0, "type_ce": base["type_ce"], "card_ce": base["card_ce"],
        "type_acc": base["type_acc"], "action_acc": base["action_acc"]}]
    print(f"[eval] step 0/{total_steps} type_ce={_fmt(base['type_ce'])} "
          f"card_ce={_fmt(base['card_ce'])} type_acc={_fmt(base['type_acc'])} "
          f"action_acc={_fmt(base['action_acc'])}", flush=True)

    # ── 4) 训练 ──────────────────────────────────────────────────────────
    model.train()
    curve: List[Dict[str, Any]] = []
    step = 0
    rng = np.random.default_rng(int(args.seed) + 1)
    t_train = time.time()
    stopped = False
    for epoch in range(int(args.epochs)):
        order = rng.permutation(n_train)
        for start in range(0, n_train, int(args.batch)):
            if step >= total_steps:
                stopped = True
                break
            sel = train_idx[order[start:start + int(args.batch)]]
            raw = bc_obs_batch(samples, indices=sel)
            batch = _batch_tensors(torch, device, raw)
            opt.zero_grad(set_to_none=True)
            if use_amp:
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    hier, policy_logits = _hier_loss(model, batch, args, torch)
                    loss = hier["loss"]
            else:
                hier, policy_logits = _hier_loss(model, batch, args, torch)
                loss = hier["loss"]
            anchor_kl = None
            if teacher is not None and float(args.anchor_beta) > 0.0:
                anchor_kl = _anchor_kl(
                    teacher, model, batch, scope=str(args.anchor_scope),
                    temperature=float(args.anchor_temperature), torch=torch)
                loss = loss + float(args.anchor_beta) * anchor_kl
            move_anchor = None
            if teacher is not None and float(args.bc_move_anchor_coef) > 0.0:
                move_anchor = _move_anchor_mse(model, teacher, batch,
                                               policy_logits, torch)
                loss = loss + float(args.bc_move_anchor_coef) * move_anchor
            if not bool(torch.isfinite(loss)):
                print(f"[error] step {step + 1} loss 非有限: {float(loss)}",
                      file=sys.stderr)
                return 3
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),
                                           float(args.grad_clip))
            opt.step()
            step += 1
            type_acc, act_acc = _step_acc(policy_logits, hier, batch, torch)
            rec = {"step": step, "loss": float(loss.detach()),
                   "type_loss": float(hier["type_loss"].detach()),
                   "card_loss": float(hier["card_loss"].detach()),
                   "type_acc": type_acc, "action_acc": act_acc,
                   "anchor_kl": (float(anchor_kl.detach())
                                 if anchor_kl is not None else None),
                   "move_anchor": (float(move_anchor.detach())
                                   if move_anchor is not None else None),
                   "lr": float(opt.param_groups[0]["lr"])}
            curve.append(rec)
            if int(args.log_every) > 0 and (step % int(args.log_every) == 0
                                            or step == total_steps):
                anchor_note = ("" if rec.get("anchor_kl") is None
                               else f" anchor={_fmt(rec['anchor_kl'])}")
                move_note = ("" if rec.get("move_anchor") is None
                             else f" move_mse={_fmt(rec['move_anchor'])}")
                print(f"[bc] step {step}/{total_steps} loss={_fmt(rec['loss'])} "
                      f"type={_fmt(rec['type_loss'])} card={_fmt(rec['card_loss'])} "
                      f"acc={_fmt(rec['type_acc'])} act={_fmt(rec['action_acc'])}"
                      f"{anchor_note}{move_note}", flush=True)
            if step % eval_every == 0 and step < total_steps:
                model.eval()
                mid = _collect_holdout(torch, model, samples, hold_idx,
                                       batch_size=int(args.eval_batch),
                                       device=device)
                model.train()
                m = _eval_ce(torch, mid, args)
                eval_curve.append({"step": step, "type_ce": m["type_ce"],
                                   "card_ce": m["card_ce"],
                                   "type_acc": m["type_acc"],
                                   "action_acc": m["action_acc"]})
                print(f"[eval] step {step}/{total_steps} type_ce={_fmt(m['type_ce'])} "
                      f"card_ce={_fmt(m['card_ce'])} type_acc={_fmt(m['type_acc'])} "
                      f"action_acc={_fmt(m['action_acc'])}", flush=True)
        if stopped:
            break
    train_s = time.time() - t_train

    # ── 5) 训练后 holdout（eval CE + KL）──────────────────────────────────
    post = _collect_holdout(torch, model, samples, hold_idx,
                            batch_size=int(args.eval_batch), device=device)
    final = _eval_ce(torch, post, args)
    eval_curve.append({"step": step, "type_ce": final["type_ce"],
                       "card_ce": final["card_ce"],
                       "type_acc": final["type_acc"],
                       "action_acc": final["action_acc"]})
    print(f"[eval] final step {step} type_ce={_fmt(final['type_ce'])} "
          f"card_ce={_fmt(final['card_ce'])} type_acc={_fmt(final['type_acc'])} "
          f"action_acc={_fmt(final['action_acc'])}", flush=True)

    kl: Dict[str, Any] = {}
    if int(args.preserve_rl):
        kl = _kl_summary(pre, post, float(args.max_kl))
        print(f"[kl] pre‖post mean={kl['kl_mean']:.5f} p50={kl['kl_p50']:.5f} "
              f"p95={kl['kl_p95']:.5f} max={kl['kl_max']:.4f} "
              f"top1_agree={kl['top1_agree']:.4f} (max_kl={kl['max_kl']})",
              flush=True)
        if kl["exceeds_max_kl"]:
            print(f"[bc][warn] KL(pre‖post)={kl['kl_mean']:.4f} > max_kl="
                  f"{kl['max_kl']:.2f}：策略已显著偏离 RL 起点，"
                  f"续训 PPO 可能遗忘（建议降低 lr/步数或提高 --anchor-beta）",
                  flush=True)

    # ── 6) 保存 ──────────────────────────────────────────────────────────
    meta_out: Dict[str, Any] = {k: v for k, v in dict(meta_in).items()
                                if k not in ("norm_mean", "norm_std")}
    # tiny 的 hidden 维不进 state_dict 形状之外的信息：写进 meta 才能被
    # ``load_checkpoint`` 按原维度重建（entity 的 d_model 由 save_checkpoint 自己写）。
    if not hasattr(model, "d_model") and hasattr(model, "policy_head"):
        meta_out["hidden"] = int(model.policy_head.in_features)
    meta_out.update({
        "bc_pretrained": True,
        "bc_steps": int(step),
        "samples": int(n_total),
        "bc_samples": int(n_train),
        "bc_holdout": int(n_hold),
        "bc_epochs": int(args.epochs),
        "bc_lr": float(args.lr),
        "bc_batch": int(args.batch),
        "bc_type_weight": float(args.type_weight),
        "bc_card_weight": float(args.card_weight),
        "bc_class_balance": int(args.class_balance),
        "bc_include_reposition": int(args.bc_include_reposition),
        "bc_n_types": int(n_types),
        "bc_class_weight": dict(class_weight_overrides),
        "bc_move_anchor_coef": float(args.bc_move_anchor_coef),
        "bc_move_anchor_last": (curve[-1].get("move_anchor") if curve else None),
        "bc_init": ("" if args.from_scratch else os.path.abspath(args.init)),
        "bc_from_scratch": bool(args.from_scratch),
        "bc_loss": float(curve[-1]["loss"]) if curve else None,
        "bc_holdout_type_ce": final["type_ce"],
        "bc_holdout_card_ce": final["card_ce"],
        "bc_holdout_type_acc": final["type_acc"],
        "bc_kl_pre_post": (kl["kl_mean"] if kl else None),
        "bc_anchor_beta": float(args.anchor_beta),
        "bc_anchor_kl": (curve[-1].get("anchor_kl") if curve else None),
        "bc_generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })
    ckpt_path = os.path.join(args.out, "model.pt")
    save_checkpoint(model, ckpt_path, meta=meta_out,
                    norm_mean=norm_mean, norm_std=norm_std)

    report_path = (args.report if str(args.report).strip()
                   else os.path.join(args.out, "report.json"))
    os.makedirs(os.path.dirname(os.path.abspath(report_path)) or ".", exist_ok=True)
    report = {
        "checkpoint": os.path.abspath(ckpt_path),
        "args": {k: args.__dict__[k] for k in sorted(args.__dict__)},
        "data": {
            "samples": n_total, "train": n_train, "holdout": n_hold,
            "mmr_min": int(args.mmr_min),
            "action_types": list(action_types or DEFAULT_BC_ACTION_TYPES),
            "n_types": int(n_types),
            "class_weight": dict(class_weight_overrides),
            "class_distribution": samples.class_distribution(),
            "load_s": load_s,
        },
        "model": {"arch": meta_out.get("arch"), "params": n_params,
                  "init": meta_out.get("bc_init"),
                  "from_scratch": bool(args.from_scratch)},
        "train": {"steps": int(step), "batch": int(args.batch),
                  "lr": float(args.lr), "amp": "bf16" if use_amp else "off",
                  "class_balance": int(args.class_balance),
                  "anchor_beta": float(args.anchor_beta),
                  "anchor_scope": str(args.anchor_scope),
                  "anchor_temperature": float(args.anchor_temperature),
                  "include_reposition": int(args.bc_include_reposition),
                  "class_weight": dict(class_weight_overrides),
                  "move_anchor_coef": float(args.bc_move_anchor_coef),
                  "train_s": train_s,
                  "samples_per_s": (int(step) * int(args.batch)
                                    / max(1e-9, train_s)),
                  "curve": curve},
        "eval": {"curve": eval_curve, "final": final},
        "kl": kl,
        "final_meta": {k: meta_out[k] for k in (
            "bc_pretrained", "bc_steps", "samples", "bc_samples", "bc_holdout",
            "bc_loss", "bc_holdout_type_ce", "bc_holdout_card_ce",
            "bc_holdout_type_acc", "bc_kl_pre_post", "bc_anchor_beta",
            "bc_anchor_kl", "bc_include_reposition", "bc_n_types",
            "bc_class_weight", "bc_move_anchor_coef", "bc_move_anchor_last")
            if k in meta_out},
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(_jsonable(report), f, ensure_ascii=False, indent=2)

    print(f"[bc] done steps={int(step)} elapsed={train_s:.1f}s "
          f"({int(step) * int(args.batch) / max(1e-9, train_s):.0f} samples/s)", flush=True)
    print(f"[bc] saved {ckpt_path} report={report_path}", flush=True)
    print(json.dumps({"bc_steps": int(step),
                      "holdout_type_ce": final["type_ce"],
                      "holdout_type_acc": final["type_acc"],
                      "kl_mean": kl.get("kl_mean"),
                      "checkpoint": os.path.abspath(ckpt_path)},
                     ensure_ascii=False), flush=True)
    return 0


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):  # pragma: no cover - 防御
        return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
