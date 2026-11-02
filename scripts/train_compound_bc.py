"""复利 BC 蒸馏：把 ``CompoundPolicy`` 的沙盒动作标签蒸馏进学生策略

教师见 ``scripts/compound_script.py``（`CompoundPolicy` 买 8.8–15.4 张放大器/局），
数据由 ``scripts/gen_compound_bc.py`` 产出到 ``data/scaling/compound_bc/*.npz``。
本脚本只做**监督学习**（masked CE，可选用教师 soft 标签），不做 PPO、不改任何共享模块。

用法::

    PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
    export PYTHONPATH=rust/python:.

    # 小模型（0.667M）：d128 × 2 层
    $PY scripts/train_compound_bc.py --data data/scaling/compound_bc \
        --arch entity --d-model 128 --n-layers 2 --device cuda:7 \
        --epochs 2 --lr 3e-5 --batch-size 256 --holdout 0.05 \
        --out runs/compound_bc

    # 主模型（14.9M）：d384 × 8 层
    $PY scripts/train_compound_bc.py --d-model 384 --n-layers 8 --lr 3e-5

数据契约（每个 npz 是**多个决策摊平**的一批，至少含）::

    obs       (n, 3351) float32   = 前 3227 观测 + 后 124 卡牌（也接受 (n,3227) + cards）
    action    (n,)     int64      ∈ [0, 245)，必须合法（mask[action] = True）
    mask      (n, 245) bool/uint8
    tier/turn/gold  (n,)  可选，仅统计用
    episode_id      (n,)  可选，**holdout 按局切**（避免同一局的动作同时进 train/val）
    final_t15_sigma (n,)  可选，``--min-sigma`` 过滤低质量局
    r12_15          (n,)  可选，仅统计用
    soft/probs      (n, 245) float32 可选 → 走教师 soft-label CE（默认 auto：有就用）

产物（``--out``）::

    ckpt_<size>.pt    torch checkpoint（``save_checkpoint`` 格式，含 meta，可直接回完整游戏）
    meta_<size>.json  训练样本数 / CE / top1 / holdout 明细 / 数据文件 sha 摘要
    log_<size>.jsonl  逐 epoch 记录（便于曲线）

**与现有 BC 的关系**：本脚本只新增文件、只写 ``runs/compound_bc/``，不 import 也不修改
``scripts/train_economy_sandbox.py`` / ``hsbg/az/train/*``；CE 口径（``masked_log_softmax`` +
``gather``）与 ``scripts/train_economy_sandbox.py::_bc_fit`` 逐项一致。
"""

from __future__ import annotations

import argparse
import glob
import hashlib
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

# 与 hsbg/env/obs_std.py + action_space_std.py 一致的硬契约（写死，防止数据错位静默通过）
OBS_FLOATS = 3227
OBS_CARDS = 124
OBS_TOTAL = OBS_FLOATS + OBS_CARDS
N_ACTIONS = 245

#: 两种目标尺寸（``docs/COMPOUND_BC.md`` §2）：0.667M 用于筛选数据/快速迭代，
#: 14.9M (= d384×8，与 s14 主策略同构) 才是「能否进主策略」的判据。
SIZE_PRESETS: Dict[str, Tuple[int, int, int]] = {
    "small": (128, 2, 8),
    "main": (384, 8, 8),
}


def _torch():
    try:
        import torch  # noqa: PLC0415
        return torch
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("torch 不可用：BC 训练需要 `pip install torch`") from exc


# ── 数据加载 ────────────────────────────────────────────────────────────────


def _first(d: Dict[str, np.ndarray], *keys: str) -> Optional[np.ndarray]:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _as_bool_mask(x: np.ndarray, n: int) -> np.ndarray:
    m = np.asarray(x)
    if m.ndim != 2 or m.shape != (n, N_ACTIONS):
        raise ValueError(f"mask 形状应为 ({n}, {N_ACTIONS})，得到 {m.shape}")
    if m.dtype == np.bool_:
        return m
    if np.issubdtype(m.dtype, np.floating):
        return m > 0.5
    return m.astype(np.int64) != 0


def load_npz(path: str) -> Dict[str, np.ndarray]:
    """读单个 npz -> 统一字段（不做过滤，不做 dtype 之外的修复）。

    观测两种布局都支持：
    ① ``obs`` 为 ``(n, 3351)``（前 3227 浮点 + 后 124 卡牌，卡牌可能被存成 float，取整）；
    ② ``obs`` 为 ``(n, 3227)`` 且另有 ``cards`` (n, 124)。
    """
    with np.load(path, allow_pickle=False) as z:
        d = {str(k): z[k] for k in z.files}
    obs = _first(d, "obs", "features", "obs_std", "obs_flat")
    if obs is None:
        raise ValueError(f"{path}: 缺 'obs' 字段（现有 {sorted(d)}）")
    obs = np.asarray(obs)
    if obs.ndim != 2:
        raise ValueError(f"{path}: obs 应为二维，得到 {obs.shape}")
    n = int(obs.shape[0])
    if obs.shape[1] == OBS_TOTAL:
        if obs.dtype == np.float16:
            raise ValueError(
                f"{path}: obs 合并布局 + float16 会丢卡牌 id 精度（>2048 溢出）；"
                "请用 features(float16) + cards(int16) 的独立布局")
        feats = np.ascontiguousarray(obs[:, :OBS_FLOATS], dtype=np.float32)
        cards = np.rint(np.asarray(obs[:, OBS_FLOATS:], dtype=np.float64)).astype(np.int64)
    elif obs.shape[1] == OBS_FLOATS:
        cards = _first(d, "cards", "obs_cards", "card_ids")
        if cards is None:
            raise ValueError(f"{path}: obs 只有 {OBS_FLOATS} 列，必须另给 'cards' (n,{OBS_CARDS})")
        cards = np.rint(np.asarray(cards, dtype=np.float64)).astype(np.int64)
        if cards.shape != (n, OBS_CARDS):
            raise ValueError(f"{path}: cards 形状应为 ({n},{OBS_CARDS})，得到 {cards.shape}")
        # 教师数据 features 是 float16（体积减半）：**保持原 dtype**，逐 batch 再转 float32
        feats = np.asarray(obs)
        if feats.dtype != np.float16:
            feats = np.ascontiguousarray(feats, dtype=np.float32)
    else:
        raise ValueError(f"{path}: obs 列数 {obs.shape[1]} 不是 {OBS_FLOATS} 或 {OBS_TOTAL}")
    if not np.isfinite(feats).all():
        raise ValueError(f"{path}: obs 含 NaN/Inf")

    mask = _first(d, "mask", "masks", "legal")
    if mask is None:
        raise ValueError(f"{path}: 缺 'mask' 字段（现有 {sorted(d)}）")
    maskb = _as_bool_mask(mask, n)
    if not maskb.any(axis=1).all():
        raise ValueError(f"{path}: 有 {int((~maskb.any(axis=1)).sum())} 行没有任何合法动作")

    act = _first(d, "action", "actions", "a", "target_action")
    if act is None:
        raise ValueError(f"{path}: 缺 'action' 字段（现有 {sorted(d)}）")
    action = np.asarray(act).reshape(-1).astype(np.int64)
    if action.shape[0] != n:
        raise ValueError(f"{path}: action 长度 {action.shape[0]} != n={n}")

    out: Dict[str, np.ndarray] = {"obs": feats, "cards": cards, "mask": maskb,
                                  "action": action}
    soft = _first(d, "soft", "probs", "target_probs", "policy", "soft_label")
    if soft is not None:
        s = np.asarray(soft, dtype=np.float32)
        if s.shape != (n, N_ACTIONS):
            raise ValueError(f"{path}: soft 形状应为 ({n},{N_ACTIONS})，得到 {s.shape}")
        s = np.where(maskb, np.maximum(s, 0.0), 0.0)
        tot = s.sum(axis=1, keepdims=True)
        bad = (tot <= 0.0).reshape(-1)
        if bad.any():  # 空标签 → 退化成一热（用 action），不丢样本
            s[bad] = 0.0
            s[bad, action[bad]] = 1.0
            tot[bad] = 1.0
        out["soft"] = np.ascontiguousarray(s / tot, dtype=np.float32)
    for key, aliases in (("tier", ("tier",)), ("turn", ("turn",)),
                         ("gold", ("gold",)),
                         ("episode_id", ("episode_id", "episode", "game_id")),
                         ("final_t15_sigma", ("final_t15_sigma", "sigma_t15", "t15_sigma")),
                         ("r12_15", ("r12_15", "ratio_12_15")),
                         ("action_kind", ("action_kind", "kind")),
                         ("is_amp_buy", ("is_amp_buy",)),
                         ("is_carrier_buy", ("is_carrier_buy",))):
        v = _first(d, *aliases)
        if v is not None:
            out[key] = np.asarray(v).reshape(-1)
    # 教师数据把「整局标签」放在 ep_* 数组里（按 episode_id 索引）：摊平成逐决策
    eid = out.get("episode_id")
    if eid is not None:
        eid = eid.astype(np.int64)
        out["episode_id"] = eid
        for key, epkey in (("final_t15_sigma", "ep_sigma_t15"),
                           ("r12_15", "ep_r12_15")):
            if key in out:
                continue
            ep = _first(d, epkey)
            if ep is not None:
                out[key] = np.asarray(ep).reshape(-1)[eid]
    # 官方验证集切分（教师 ep_split：0=train / 1=val，按**局**留出 10%）
    split = _first(d, "ep_split", "split")
    if split is not None:
        s = np.asarray(split).reshape(-1)
        if s.shape[0] == n:
            out["is_val"] = s.astype(np.int64) != 0
        elif eid is not None and s.shape[0] == int(eid.max()) + 1:
            out["is_val"] = s.astype(np.int64)[eid] != 0
        else:
            raise ValueError(f"{path}: split 长度 {s.shape[0]} 与行数 {n} / 局数不匹配")
    return out


def _subsample_episodes(d: Dict[str, np.ndarray], frac: float) -> Dict[str, np.ndarray]:
    """按**局**确定性地只留 ``frac`` 比例的样本（用于控制 DAgger : base 混比）。

    必须按局抽样：只留一部分决策会破坏「同一局的动作相关性」和 ``ep_split`` 的语义。
    选择规则是确定性的（无 RNG）：``(eid * 2654435761) % 1000 < frac*1000``，
    同一份数据在任何机器/任何次运行都得到同一子集。
    """
    if not (0.0 < float(frac) < 1.0):
        return d
    cut = int(round(float(frac) * 1000))
    if "episode_id" in d:
        eid = np.asarray(d["episode_id"]).astype(np.int64)
        h = (eid * 2654435761) % 1000
        keep = h < cut
        if not keep.any():                      # 极端小数据时至少留一局
            e0 = int(eid.min())
            keep = eid == e0
        return {k: v[keep] for k, v in d.items()}
    n = int(d["action"].shape[0])
    keep = (np.arange(n) * 2654435761) % 1000 < cut
    return {k: v[keep] for k, v in d.items()}


def load_dataset(spec: str) -> Tuple[Dict[str, np.ndarray], List[Dict[str, Any]]]:
    """``spec`` = 目录 / 单个 npz / 逗号分隔 / glob / ``path@frac``（按局抽样到 frac 比例）。"""
    paths: List[str] = []
    fracs: List[float] = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        frac = 1.0
        if "@" in part:                      # path@frac：按局抽样（控制 DAgger 混比）
            part, _, fstr = part.rpartition("@")
            frac = float(fstr)
        if os.path.isdir(part):
            hits = sorted(glob.glob(os.path.join(part, "*.npz")))
            paths.extend(hits)
            fracs.extend([frac] * len(hits))
        elif any(ch in part for ch in "*?["):
            hits = sorted(glob.glob(part))
            paths.extend(hits)
            fracs.extend([frac] * len(hits))
        elif os.path.isfile(part):
            paths.append(part)
            fracs.append(frac)
        else:
            raise FileNotFoundError(f"数据路径不存在：{part}")
    # 去重 + 稳定顺序（同一文件被两种写法命中时不重复计数）
    seen, uniq, uniq_frac = set(), [], []
    for p, fr in zip(paths, fracs):
        rp = os.path.realpath(p)
        if rp in seen:
            continue
        seen.add(rp)
        uniq.append(p)
        uniq_frac.append(float(fr))
    paths, fracs = uniq, uniq_frac
    if not paths:
        raise FileNotFoundError(
            f"没有找到 npz：{spec}（教师数据若未就绪，先用 --make-synthetic 造 smoke 数据）")
    chunks: Dict[str, List[np.ndarray]] = {}
    files: List[Dict[str, Any]] = []
    for p, fr in zip(paths, fracs):
        d = load_npz(p)
        if fr < 1.0:
            n0 = int(d["action"].shape[0])
            d = _subsample_episodes(d, fr)
            print(f"[bc] 按局抽样 {os.path.basename(p)} @{fr:g}："
                  f"{n0} -> {d['action'].shape[0]} 行", flush=True)
        for k, v in d.items():
            chunks.setdefault(k, []).append(v)
        files.append({"path": os.path.relpath(p, ROOT) if p.startswith(ROOT) else p,
                      "rows": int(d["action"].shape[0]),
                      "frac": float(fr),
                      "has_soft": "soft" in d,
                      "sha256_8": _sha8(p)})
    out: Dict[str, np.ndarray] = {}
    for k, vs in chunks.items():
        out[k] = np.concatenate(vs, axis=0) if len(vs) > 1 else vs[0]
    return out, files


def _sha8(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()[:8]


def filter_dataset(d: Dict[str, np.ndarray], *, min_sigma: float = 0.0,
                   max_samples: int = 0) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
    """丢掉非法动作行 + 按 ``--min-sigma`` 过滤低质量局 + 可选截断。

    「非法」= action 越界，或 ``mask[action] == False``（教师脚本记录过回退，理论上为 0；
    真出现就丢弃并计数，**不静默修复**）。
    """
    n = int(d["action"].shape[0])
    a = d["action"]
    ok = (a >= 0) & (a < N_ACTIONS)
    ok &= d["mask"][np.arange(n), np.clip(a, 0, N_ACTIONS - 1)]
    stats: Dict[str, Any] = {"rows_raw": n, "rows_illegal_dropped": int((~ok).sum())}
    if not ok.all():
        d = {k: v[ok] for k, v in d.items()}
    if min_sigma > 0 and "final_t15_sigma" in d:
        keep = np.asarray(d["final_t15_sigma"], dtype=np.float64) >= float(min_sigma)
        stats["rows_low_sigma_dropped"] = int((~keep).sum())
        if not keep.all():
            d = {k: v[keep] for k, v in d.items()}
    if max_samples and d["action"].shape[0] > int(max_samples):
        idx = np.arange(int(max_samples))
        stats["rows_truncated_to"] = int(max_samples)
        d = {k: v[idx] for k, v in d.items()}
    stats["rows_used"] = int(d["action"].shape[0])
    if stats["rows_used"] <= 0:
        raise ValueError("过滤后没有样本（检查 --min-sigma 或数据本身）")
    return d, stats


def split_indices(n: int, holdout: float, seed: int,
                  episode_id: Optional[np.ndarray] = None,
                  is_val: Optional[np.ndarray] = None) -> Tuple[np.ndarray, np.ndarray]:
    """验证集切分：**官方 ``ep_split`` 优先**，否则按局（有 episode_id）随机留 ``holdout``。

    教师给的 ``ep_split`` 是「确定性 10% 留出、按局」——训练必须照抄，否则 val CE 与
    教师报告不可比；``--holdout 0`` + 有 ``ep_split`` 时就是纯官方切分。
    """
    if is_val is not None:
        v = np.asarray(is_val).reshape(-1).astype(bool)
        if v.shape[0] != n:
            raise ValueError(f"is_val 长度 {v.shape[0]} != n={n}")
        return np.where(~v)[0], np.where(v)[0]
    rng = np.random.default_rng(int(seed))
    if holdout <= 0:
        return np.arange(n), np.zeros(0, dtype=np.int64)
    k = max(1, int(round(float(holdout) * n))) if n > 1 else 0
    k = min(k, n - 1) if n > 1 else 0
    if k <= 0:
        return np.arange(n), np.zeros(0, dtype=np.int64)
    if episode_id is None:
        perm = rng.permutation(n)
        return np.sort(perm[k:]), np.sort(perm[:k])
    eid = np.asarray(episode_id).reshape(-1)
    uniq = np.unique(eid)
    rng.shuffle(uniq)
    val_eids: List[Any] = []
    seen = 0
    for e in uniq:
        if seen >= k:
            break
        val_eids.append(e)
        seen += int((eid == e).sum())
    is_val = np.isin(eid, np.asarray(val_eids))
    return np.where(~is_val)[0], np.where(is_val)[0]


# ── masked CE（numpy 参考实现 = 手算口径，测试与自检都用它）───────────────


def masked_ce_numpy(logits: np.ndarray, mask: np.ndarray, action: np.ndarray,
                    soft: Optional[np.ndarray] = None) -> np.ndarray:
    """逐样本 masked CE（numpy，float64）。

    硬标签：``-log softmax(logits)_a``，非法位取 ``-inf``（等价 ``masked_fill(-1e9)``）。
    soft 标签：``-Σ_i p_i log q_i``（p 已在 mask 外置 0，q 在 mask 外严格 0）。
    全无合法动作的行返回 ``nan``（调用方不应传入；加载器已拦截）。
    """
    z = np.asarray(logits, dtype=np.float64)
    m = np.asarray(mask, dtype=bool)
    if z.shape != m.shape:
        raise ValueError(f"logits/mask 形状不一致 {z.shape} vs {m.shape}")
    a = np.asarray(action).reshape(-1).astype(np.int64)
    out = np.full(z.shape[0], np.nan, dtype=np.float64)
    for i in range(z.shape[0]):
        mi = m[i]
        if not mi.any():
            continue
        zi = z[i][mi]
        mx = float(zi.max())
        logq = zi - (mx + math.log(float(np.exp(zi - mx).sum())))
        if soft is None:
            # action 在「合法位有序索引」里的位置
            idx = np.flatnonzero(mi)
            hit = np.flatnonzero(idx == a[i])
            if hit.size == 0:
                continue
            out[i] = -float(logq[int(hit[0])])
        else:
            p = np.asarray(soft[i], dtype=np.float64)[mi]
            out[i] = -float(np.dot(p, logq))
    return out


# ── 模型 ────────────────────────────────────────────────────────────────────


def build_model(arch: str, d_model: int, n_layers: int, n_heads: int):
    from hsbg.az.train.model import build_net  # noqa: PLC0415
    return build_net(arch=str(arch), d_model=int(d_model), n_layers=int(n_layers),
                     n_heads=int(n_heads))


def size_name(d_model: int, n_layers: int) -> str:
    for name, (dm, nl, _nh) in SIZE_PRESETS.items():
        if int(dm) == int(d_model) and int(nl) == int(n_layers):
            return name
    return f"d{int(d_model)}x{int(n_layers)}"


def _to_tensors(batch: Dict[str, np.ndarray], device, torch, *, with_soft: bool):
    f = torch.from_numpy(np.ascontiguousarray(batch["obs"], dtype=np.float32)).to(device)
    c = torch.from_numpy(np.ascontiguousarray(batch["cards"], dtype=np.int64)).to(device)
    m = torch.from_numpy(np.ascontiguousarray(batch["mask"], dtype=bool)).to(device)
    a = torch.from_numpy(np.ascontiguousarray(batch["action"], dtype=np.int64)).to(device)
    s = None
    if with_soft:
        s = torch.from_numpy(np.ascontiguousarray(batch["soft"], dtype=np.float32)).to(device)
    w = None
    if "weight" in batch:
        w = torch.from_numpy(
            np.ascontiguousarray(batch["weight"], dtype=np.float32)).to(device)
    return f, c, m, a, s, w


def _forward_ce(model, batch, device, torch, *, with_soft: bool):
    """一次前向 -> (loss, ce_hard_mean, top1, nll_per_row_numpy)。"""
    from hsbg.az.train.ppo import forward_model, masked_log_softmax_torch  # noqa: PLC0415
    f, c, m, a, s, w = _to_tensors(batch, device, torch, with_soft=with_soft)
    logits, _rank, _value = forward_model(model, f, c, m)
    logp = masked_log_softmax_torch(logits, m)
    nll = -logp.gather(1, a.unsqueeze(1)).squeeze(1)          # 硬标签 CE（每行）
    per_row = (-(s * logp).sum(dim=-1)) if with_soft else nll
    if w is not None:
        loss = (per_row * w).sum() / w.sum().clamp_min(1e-6)
    else:
        loss = per_row.mean()
    with torch.no_grad():
        pred = logits.float().masked_fill(~m, -1e9).argmax(dim=-1)
        top1 = float((pred == a).float().mean())
        ce_hard = float(nll.mean())
        nll_np = nll.detach().double().cpu().numpy()
    return loss, ce_hard, top1, nll_np


def evaluate_ce(model, data: Dict[str, np.ndarray], idx: np.ndarray, device,
                torch, *, batch_size: int = 512, soft_ok: bool = False,
                with_soft: bool = False) -> Dict[str, Any]:
    """在给定索引上算 CE / top1（逐 batch 加权平均，不拼大张量）。"""
    from hsbg.az.train.ppo import forward_model, masked_log_softmax_torch  # noqa: PLC0415
    model.eval()
    tot_n = 0
    sum_ce = 0.0
    sum_top1 = 0.0
    sum_soft = 0.0
    with torch.no_grad():
        for s0 in range(0, len(idx), int(batch_size)):
            sel = idx[s0:s0 + int(batch_size)]
            # 验证 CE 一律**不加权**（跨 run 可比）；加权只影响训练梯度
            batch = {k: (data[k][sel] if k in data else None) for k in
                     ("obs", "cards", "mask", "action", "soft")}
            batch = {k: v for k, v in batch.items() if v is not None}
            use_soft = bool(with_soft and "soft" in batch)
            loss, ce_hard, top1, _ = _forward_ce(
                model, batch, device, torch, with_soft=use_soft)
            nb = len(sel)
            tot_n += nb
            sum_ce += ce_hard * nb
            sum_top1 += top1 * nb
            sum_soft += float(loss) * nb
    model.train()
    rep = {"n": int(tot_n), "ce": (sum_ce / tot_n if tot_n else float("nan")),
           "top1": (sum_top1 / tot_n if tot_n else float("nan"))}
    if with_soft:
        rep["loss"] = (sum_soft / tot_n if tot_n else float("nan"))
    return rep


def ce_selfcheck(data: Dict[str, np.ndarray], device, torch, *,
                 n: int = 64, atol: float = 2e-4) -> Dict[str, Any]:
    """用**随机 logits** 校验 torch masked CE 与 numpy 手算完全一致（≤``atol``）。

    这是「CE 与手算一致」的运行期守卫：``masked_fill(-1e9)`` 与 numpy 的 ``-inf`` 语义
    必须逐位等价，否则教师标签的 CE 读数不可信。
    """
    rng = np.random.default_rng(20261101)
    k = int(min(n, data["action"].shape[0]))
    sel = rng.choice(data["action"].shape[0], size=k, replace=False)
    logits = rng.normal(0.0, 2.0, size=(k, N_ACTIONS)).astype(np.float32)
    mask = data["mask"][sel]
    action = data["action"][sel]
    want = masked_ce_numpy(logits, mask, action)
    zt = torch.from_numpy(logits).to(device)
    mt = torch.from_numpy(np.ascontiguousarray(mask)).to(device)
    at = torch.from_numpy(np.ascontiguousarray(action)).to(device)
    from hsbg.az.train.ppo import masked_log_softmax_torch  # noqa: PLC0415
    with torch.no_grad():
        logp = masked_log_softmax_torch(zt, mt)
        got = (-logp.gather(1, at.unsqueeze(1)).squeeze(1)).double().cpu().numpy()
    delta = float(np.nanmax(np.abs(got - want)))
    if not (delta <= atol):
        raise AssertionError(f"masked CE 自检失败：max|torch-numpy| = {delta:.3e} > {atol}")
    return {"n": k, "max_abs_delta": delta, "atol": atol}


#: ``action_kind`` 语义（教师 npz 的字段说明，``data/scaling/compound_bc/meta.json``）
KIND_NAMES = {0: "other", 1: "buy_amp", 2: "buy_carrier", 3: "buy_spell", 4: "buy_minion",
              5: "play_spell", 6: "play_minion", 7: "sell", 8: "upgrade", 9: "refresh",
              10: "end_turn", 11: "pending"}
KIND_IDS = {v: k for k, v in KIND_NAMES.items()}

#: **诊断专用**的动作下标 → 语义段（rust/crates/hsbg-engine/src/actions.rs）。
#: 只用于「学生 argmax 落在哪一段」的统计，**绝不参与损失**（损失只用 mask + CE）。
ACTION_CLASS_RANGES: Tuple[Tuple[str, int, int], ...] = (
    ("end_turn", 0, 0), ("refresh", 1, 1), ("freeze", 2, 2), ("upgrade", 3, 3),
    ("hero_power", 4, 4), ("dark_gift", 5, 6), ("cancel", 7, 7), ("buy", 8, 15),
    ("sell", 16, 22), ("choose(target)", 30, 45), ("play", 46, 125), ("move", 196, 202))


def action_class(a: int) -> str:
    """动作下标 → 语义段名（诊断用近似映射，未覆盖的返回 ``"?{a}"``）。"""
    ai = int(a)
    for name, lo, hi in ACTION_CLASS_RANGES:
        if lo <= ai <= hi:
            return name
    return f"?{ai}"


def action_weights(data: Dict[str, np.ndarray], *, mode: str = "off", coef: float = 8.0,
                   kinds: str = "buy_amp,buy_carrier,play_spell,upgrade",
                   alpha: float = 0.5) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
    """动作级重加权（BC 的稀有动作召回修复，参照 ``docs/BC_AUX.md`` 的 class-weight 思路）。

    ``manual``：把 ``kinds`` 列出的若干 ``action_kind`` 的**每行 CE 权重**乘以 ``coef``
    （默认 ×8：买放大器 / 买载体 / 打法术 / 升级 —— 都是「复利链上的动作」，teacher 各占
    1.9% / 1.7% / 13.9% / 1.1% 的决策）。``rarity``：``w_k = clip(freq_k**-alpha, 1, coef)``，
    与类别频率自动成反比（``alpha=0.5`` 是平方根平衡，最稳）。

    返回 ``(weight[n]|None, info)``；``weight=None`` 时训练路径**逐位不变**（默认关闭）。
    """
    kind = data.get("action_kind")
    if str(mode) == "off":
        return None, {"mode": "off"}
    if kind is None:
        print("[bc] 警告：数据没有 action_kind，动作级重加权跳过", flush=True)
        return None, {"mode": mode, "skipped": "no action_kind"}
    k = np.asarray(kind).astype(np.int64)
    n = k.shape[0]
    w = np.ones(n, dtype=np.float32)
    info: Dict[str, Any] = {"mode": str(mode), "coef": float(coef), "alpha": float(alpha)}
    if str(mode) == "manual":
        want: List[int] = []
        per_coef: Dict[int, float] = {}
        for name in str(kinds).split(","):
            name = name.strip()
            if not name:
                continue
            # 支持逐类系数："buy_amp:8,sell:3"（不写则用 --action-weight-coef）
            lab, _, c = name.partition(":")
            lab = lab.strip()
            if lab not in KIND_IDS:
                raise ValueError(f"未知动作类别 {lab}；可选 {sorted(KIND_IDS)}")
            kk = KIND_IDS[lab]
            want.append(kk)
            per_coef[kk] = float(c) if c.strip() else float(coef)
        for kk, cc in per_coef.items():
            w[k == kk] = cc
        info.update({"kinds": [f"{KIND_NAMES[i]}:{per_coef[i]:g}" for i in want],
                     "rows_weighted": int(np.isin(k, list(per_coef)).sum()),
                     "share_weighted": float(np.isin(k, list(per_coef)).mean()),
                     "weight_mean": float(w.mean())})
    elif str(mode) == "rarity":
        freq = np.bincount(k, minlength=len(KIND_NAMES)).astype(np.float64) / max(1, n)
        per = np.clip(np.power(np.maximum(freq, 1e-9), -float(alpha)), 1.0, float(coef))
        w = per[k].astype(np.float32)
        info.update({"per_kind": {KIND_NAMES.get(i, str(i)): float(per[i])
                                  for i in range(len(per)) if freq[i] > 0},
                     "weight_mean": float(w.mean())})
    else:
        raise ValueError(f"未知 --action-weight-mode {mode}（off/manual/rarity）")
    info["weight_p90"] = float(np.percentile(w, 90))
    return w, info


def diagnose(model, data: Dict[str, np.ndarray], idx: np.ndarray, device,
             torch, *, batch_size: int = 512) -> Dict[str, Any]:
    """holdout 上的**分层诊断**：整体 top1、按动作类别 top1、放大器购买的召回。

    为什么需要它：``CompoundPolicy`` 的放大器购买只占决策的 ~2%，整体 top1 65% 完全
    可能是「高频动作对、放大器全丢」。整局指标（放大器/局、t15 Σ）掉下来时必须先看
    这一层，否则会误判成「模型容量不够」。
    """
    from hsbg.az.train.ppo import forward_model  # noqa: PLC0415
    model.eval()
    kinds = data.get("action_kind")
    amp = data.get("is_amp_buy")
    preds = np.empty(len(idx), dtype=np.int64)
    with torch.no_grad():
        for s0 in range(0, len(idx), int(batch_size)):
            sel = idx[s0:s0 + int(batch_size)]
            f = torch.from_numpy(np.ascontiguousarray(data["obs"][sel],
                                                      dtype=np.float32)).to(device)
            c = torch.from_numpy(np.ascontiguousarray(data["cards"][sel],
                                                      dtype=np.int64)).to(device)
            m = torch.from_numpy(np.ascontiguousarray(data["mask"][sel],
                                                      dtype=bool)).to(device)
            logits, _r, _v = forward_model(model, f, c, m)
            p = logits.float().masked_fill(~m, -1e9).argmax(dim=-1)
            preds[s0:s0 + len(sel)] = p.detach().cpu().numpy()
    act = data["action"][idx]
    hit = preds == act
    out: Dict[str, Any] = {"n": int(len(idx)), "top1": float(hit.mean())}
    if kinds is not None:
        k = kinds[idx].astype(np.int64)
        per: Dict[str, Any] = {}
        for kv in sorted(set(k.tolist())):
            sel = k == kv
            per[KIND_NAMES.get(int(kv), f"k{int(kv)}")] = {
                "n": int(sel.sum()), "share": float(sel.mean()),
                "top1": float(hit[sel].mean())}
        out["by_kind"] = per
    if amp is not None:
        a = amp[idx].astype(bool)
        if a.any():
            pcls = np.asarray([action_class(int(x)) for x in preds])
            out["amp_buy"] = {
                "n": int(a.sum()), "share": float(a.mean()),
                # 教师买放大器的那一步，学生 argmax 是否**照抄**同一个动作
                "recall_exact": float(hit[a].mean()),
                # 学生的 argmax 落在哪一段（买任意槽 / 打牌 / 结束回合…）
                "pred_class": {c: float((pcls[a] == c).mean())
                               for c in sorted(set(pcls[a].tolist()))},
                "pred_any_buy": float(np.isin(pcls[a], ("buy",)).mean()),
                "pred_end_turn": float((pcls[a] == "end_turn").mean()),
            }
    model.train()
    return out


# ── 合成数据（教师数据未就绪时先跑通管线）───────────────────────────────────


def make_synthetic(out_dir: str, n: int = 512, *, n_episodes: int = 16, seed: int = 0,
                   soft: bool = True) -> List[str]:
    """造一个字段齐全的 npz（**只用于管线/单测 smoke**，不能当训练数据）。"""
    rng = np.random.default_rng(int(seed))
    os.makedirs(out_dir, exist_ok=True)
    n = int(n)
    obs = rng.normal(0.0, 1.0, size=(n, OBS_TOTAL)).astype(np.float32)
    cards = rng.integers(0, 512, size=(n, OBS_CARDS)).astype(np.float32)
    obs[:, OBS_FLOATS:] = cards
    mask = np.zeros((n, N_ACTIONS), dtype=bool)
    mask[:, 0] = True                                   # EndTurn 永远合法
    for i in range(n):                                  # 造 1–8 个合法动作
        k = int(rng.integers(1, 9))
        mask[i, rng.choice(np.arange(1, N_ACTIONS), size=k, replace=False)] = True
    legal = [np.flatnonzero(mask[i]) for i in range(n)]
    action = np.asarray([int(rng.choice(l)) for l in legal], dtype=np.int64)
    tier = rng.integers(1, 7, size=n)
    turn = rng.integers(1, 16, size=n)
    gold = rng.integers(0, 40, size=n)
    eid = rng.integers(0, int(n_episodes), size=n)
    sigma = rng.integers(600, 6000, size=n)
    r12_15 = rng.uniform(0.6, 2.5, size=n)
    payload: Dict[str, np.ndarray] = {
        "obs": obs, "action": action, "mask": mask, "tier": tier, "turn": turn,
        "gold": gold, "episode_id": eid, "final_t15_sigma": sigma, "r12_15": r12_15,
    }
    if soft:
        p = np.zeros((n, N_ACTIONS), dtype=np.float32)
        for i in range(n):
            p[i, action[i]] = 0.6
            rest = np.flatnonzero(mask[i])
            rest = rest[rest != action[i]]
            if rest.size:
                p[i, rest] = 0.4 / rest.size
        payload["soft"] = p
    path = os.path.join(out_dir, "synthetic_bc.npz")
    np.savez_compressed(path, **payload)
    return [path]


# ── 训练 ────────────────────────────────────────────────────────────────────


def _mini_batch(data: Dict[str, np.ndarray], sel: np.ndarray) -> Dict[str, np.ndarray]:
    return {k: data[k][sel] for k in
            ("obs", "cards", "mask", "action", "soft", "weight") if k in data}


def train(args) -> Dict[str, Any]:
    torch = _torch()
    t_start = time.time()
    dev = str(args.device)
    if dev.startswith("cuda") and not torch.cuda.is_available():
        print(f"[bc] 警告：{dev} 不可用，回退 cpu", flush=True)
        dev = "cpu"
        if ":" in str(args.device):
            idx = str(args.device).split(":")[1]
            if idx.isdigit() and int(idx) < torch.cuda.device_count():
                dev = f"cuda:{idx}"
    device = torch.device(dev)

    raw, files = load_dataset(str(args.data))
    data, fstats = filter_dataset(raw, min_sigma=float(args.min_sigma),
                                  max_samples=int(args.max_samples))
    with_soft = bool("soft" in data) and str(args.soft) != "off"
    if str(args.soft) == "on" and "soft" not in data:
        raise ValueError("--soft on 但数据里没有 soft 字段")

    n = int(data["action"].shape[0])
    use_official = "is_val" in data
    tr, va = split_indices(n, float(args.holdout), int(args.seed),
                           data.get("episode_id"), data.get("is_val"))
    split_src = "official(ep_split)" if use_official else (
        "episode_holdout" if "episode_id" in data else "row_holdout")
    if va.size == 0 and float(args.holdout) > 0:
        print("[bc] 警告：holdout 为空（样本或局数太少），全部当 train", flush=True)
    if float(args.sigma_weight) > 0:
        if "final_t15_sigma" not in data:
            raise ValueError("--sigma-weight >0 但数据里没有 final_t15_sigma/ep_sigma_t15")
        sig = np.asarray(data["final_t15_sigma"], dtype=np.float64)
        data["weight"] = np.clip(sig / 1500.0, 0.0, 8.0).astype(np.float32)
        print(f"[bc] 按终局 Σ 加权：(Σ/1500).clip(8)，均值 {data['weight'].mean():.2f}",
              flush=True)
    aw, aw_info = action_weights(
        data, mode=str(args.action_weight_mode), coef=float(args.action_weight_coef),
        kinds=str(args.action_weight_kinds), alpha=float(args.rarity_alpha))
    if aw is not None:
        data["weight"] = (aw * data["weight"]) if "weight" in data else aw
        print(f"[bc] 动作级重加权 {json.dumps(aw_info, ensure_ascii=False)}；"
              f"合成权重均值 {data['weight'].mean():.2f}", flush=True)

    size = str(args.size_name or "") or size_name(int(args.d_model), int(args.n_layers))
    model = build_model(str(args.arch), int(args.d_model), int(args.n_layers),
                        int(args.n_heads))
    n_param = int(sum(p.numel() for p in model.parameters()))
    model.to(device)
    opt = torch.optim.Adam([p for p in model.parameters() if p.requires_grad],
                           lr=float(args.lr))
    selfcheck = None
    if int(args.ce_selfcheck):
        selfcheck = ce_selfcheck(data, device, torch)
    print(f"[bc] size={size} arch={args.arch} d_model={args.d_model} "
          f"n_layers={args.n_layers} params={n_param / 1e6:.3f}M", flush=True)
    print(f"[bc] 样本 {n}（train {len(tr)} / val {len(va)}），soft={with_soft}，"
          f"split={split_src}，文件 {len(files)}，过滤 {fstats}", flush=True)

    rng = np.random.default_rng(int(args.seed))
    bs = int(args.batch_size)
    hist: List[Dict[str, Any]] = []
    os.makedirs(str(args.out), exist_ok=True)
    log_path = os.path.join(str(args.out), f"log_{size}.jsonl")
    log_f = open(log_path, "w", encoding="utf-8")
    try:
        for ep in range(int(args.epochs)):
            model.train()
            order = rng.permutation(tr)
            sum_loss = 0.0
            sum_ce = 0.0
            sum_top1 = 0.0
            seen = 0
            nb = 0
            for s0 in range(0, len(order), bs):
                sel = order[s0:s0 + bs]
                if len(sel) < 2:      # BatchNorm/torch 无所谓，但单样本 CE 噪声大，丢掉
                    continue
                batch = _mini_batch(data, sel)
                loss, ce_hard, top1, _ = _forward_ce(
                    model, batch, device, torch, with_soft=with_soft)
                opt.zero_grad(set_to_none=True)
                loss.backward()
                if float(args.max_grad_norm) > 0:
                    torch.nn.utils.clip_grad_norm_(model.parameters(),
                                                  float(args.max_grad_norm))
                opt.step()
                nb += 1
                seen += len(sel)
                sum_loss += float(loss.detach()) * len(sel)
                sum_ce += ce_hard * len(sel)
                sum_top1 += top1 * len(sel)
                if args.time_budget and (time.time() - t_start) > float(args.time_budget):
                    print(f"[bc] 时间预算 {args.time_budget}s 用尽，提前停（epoch {ep}）",
                          flush=True)
                    break
            row: Dict[str, Any] = {
                "epoch": ep, "updates": nb, "rows": int(seen),
                "ce_train": sum_ce / max(1, seen), "top1_train": sum_top1 / max(1, seen),
                "loss_train": sum_loss / max(1, seen),
            }
            if va.size:
                row["val"] = evaluate_ce(model, data, va, device, torch,
                                         batch_size=int(args.eval_batch),
                                         with_soft=with_soft)
            row["seconds"] = round(time.time() - t_start, 1)
            hist.append(row)
            log_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            log_f.flush()
            print("[bc] " + json.dumps(row, ensure_ascii=False), flush=True)
            if args.time_budget and (time.time() - t_start) > float(args.time_budget):
                break
    finally:
        log_f.close()

    # ── 收尾评测（全量 train / holdout）────────────────────────────────────
    final = {
        "n_train": int(len(tr)), "n_val": int(len(va)),
        "train": evaluate_ce(model, data, tr, device, torch,
                             batch_size=int(args.eval_batch), with_soft=with_soft),
    }
    if va.size:
        final["val"] = evaluate_ce(model, data, va, device, torch,
                                   batch_size=int(args.eval_batch), with_soft=with_soft)
        if int(args.diag):
            final["val_diag"] = diagnose(model, data, va, device, torch,
                                         batch_size=int(args.eval_batch))
            d = final["val_diag"]
            print("[bc] holdout 诊断：top1={:.3f}；amp-buy 召回 {}".format(
                d["top1"],
                "n/a" if "amp_buy" not in d else
                f"{d['amp_buy']['recall_exact']:.3f}（占 {d['amp_buy']['share']:.1%}）"),
                flush=True)
            if "by_kind" in d:
                rows = ", ".join(f"{k}:{v['top1']:.2f}({v['share']:.0%})"
                                 for k, v in d["by_kind"].items())
                print(f"[bc] 分类别 top1（占比）：{rows}", flush=True)

    meta: Dict[str, Any] = {
        "trained_by": "scripts/train_compound_bc.py",
        "task": "compound_bc_distill",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "arch": str(args.arch), "d_model": int(args.d_model),
        "n_layers": int(args.n_layers), "n_heads": int(args.n_heads),
        "params": n_param, "size": size,
        "n_samples": n, "n_train": int(len(tr)), "n_val": int(len(va)),
        "holdout": float(args.holdout), "split": split_src,
        "n_episodes": (int(np.unique(data["episode_id"]).size)
                       if "episode_id" in data else 0),
        "sigma_weight": float(args.sigma_weight),
        "action_weight": aw_info,
        "epochs": int(args.epochs),
        "lr": float(args.lr), "batch_size": bs, "seed": int(args.seed),
        "soft_labels": bool(with_soft), "min_sigma": float(args.min_sigma),
        "ce": final.get("val", final["train"]).get("ce"),
        "top1": final.get("val", final["train"]).get("top1"),
        "ce_train": final["train"].get("ce"), "top1_train": final["train"].get("top1"),
        "diag_val": final.get("val_diag"),
        "use_eval_split_for_meta": bool(va.size),
        "history": hist, "filter": fstats, "data_files": files,
        "ce_selfcheck": selfcheck,
        "data_spec": str(args.data),
    }
    from hsbg.az.train.model import save_checkpoint  # noqa: PLC0415
    ckpt = os.path.join(str(args.out), f"ckpt_{size}.pt")
    save_checkpoint(model, ckpt, meta=meta)
    meta_path = os.path.join(str(args.out), f"meta_{size}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f"[bc] 保存 {ckpt}（meta: {meta_path}）；"
          f"val CE={meta['ce']:.4f} top1={meta['top1']:.4f} "
          f"用时 {time.time() - t_start:.0f}s", flush=True)
    return {"checkpoint": ckpt, "meta": meta_path, "size": size, "params": n_param,
            "ce": meta["ce"], "top1": meta["top1"],
            "n_train": meta["n_train"], "n_val": meta["n_val"],
            "val_diag": final.get("val_diag")}


def build_parser() -> argparse.ArgumentParser:
    """CLI 定义（单独拿出来，单测要断言**默认值**不漂）。"""
    dm, nl, nh = SIZE_PRESETS["small"]
    ap = argparse.ArgumentParser(
        description="复利 BC 蒸馏（CompoundPolicy 教师 -> 学生策略，masked CE）")
    ap.add_argument("--data", default="data/scaling/compound_bc",
                    help="npz 目录 / 单文件 / glob / 逗号分隔")
    ap.add_argument("--out", default="runs/compound_bc")
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--arch", default="entity", choices=["entity", "entity18m"],
                    help="只支持 entity 系（与主策略同构，权重可回完整游戏）")
    ap.add_argument("--d-model", type=int, default=dm)
    ap.add_argument("--n-layers", type=int, default=nl)
    ap.add_argument("--n-heads", type=int, default=nh)
    ap.add_argument("--size-name", default="", help="产物名后缀；默认按 d_model/n_layers 推断")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--eval-batch", type=int, default=512)
    ap.add_argument("--holdout", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--soft", default="auto", choices=["auto", "on", "off"],
                    help="教师 soft 标签：auto=有就用")
    ap.add_argument("--min-sigma", type=float, default=0.0,
                    help="只保留 final_t15_sigma >= 该值的决策（教师端已过滤则无需再设）")
    ap.add_argument("--max-samples", type=int, default=0, help="0=全部（smoke 用）")
    ap.add_argument("--sigma-weight", type=float, default=0.0,
                    help=">0 时按 (终局 Σ/1500).clip(8) 加权 CE（默认 0 = 不加权）")
    ap.add_argument("--action-weight-mode", default="off",
                    choices=["off", "manual", "rarity"],
                    help="动作级重加权：manual=指定类别×coef，rarity=按类别频率反比")
    ap.add_argument("--action-weight-coef", type=float, default=8.0,
                    help="manual 的倍数 / rarity 的上限（默认 8）")
    ap.add_argument("--action-weight-kinds", default="buy_amp,buy_carrier,play_spell,upgrade",
                    help="manual 模式加权的动作类别；支持逐类系数 buy_amp:8,sell:3")
    ap.add_argument("--rarity-alpha", type=float, default=0.5,
                    help="rarity 模式：w_k = clip(freq_k^-alpha, 1, coef)")
    ap.add_argument("--max-grad-norm", type=float, default=1.0)
    ap.add_argument("--time-budget", type=float, default=0.0, help="秒；0=不限")
    ap.add_argument("--ce-selfcheck", type=int, default=1,
                    help="1=训练前用随机 logits 校验 torch CE 与 numpy 手算一致")
    ap.add_argument("--diag", type=int, default=1,
                    help="1=收尾时算 holdout 的分类别 top1 与放大器购买召回")
    ap.add_argument("--make-synthetic", type=int, default=0,
                    help=">0 时造 N 条合成 npz 到 --synth-out（smoke，不训练）")
    ap.add_argument("--synth-out", default="runs/compound_bc/synthetic")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if int(args.make_synthetic) > 0:
        paths = make_synthetic(str(args.synth_out), int(args.make_synthetic),
                               seed=int(args.seed))
        print(json.dumps({"synthetic": paths}, ensure_ascii=False))
        return 0
    rep = train(args)
    print(json.dumps(rep, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
