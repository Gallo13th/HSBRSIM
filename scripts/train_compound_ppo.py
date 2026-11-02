"""BC→PPO 微调：以复利 BC 权重为初始化，在无对战沙盒里**直接优化 Σ**（fixed20 现实收入）

为什么需要这一步：B C 的 masked CE 只度量「在已到达的状态上抄得像不像」，不优化终局强度
（见 ``docs/COMPOUND_BC.md`` §6）：单步保真度最高的 ckpt 整局 Σ 反而最低。PPO 直接对
「log Σ 望远镜奖励」做策略梯度，是唯一能动 Σ 的杠杆。

与 ``scripts/train_economy_sandbox.py`` 的差别（按任务要求实现，且**不改别人的文件**）：
- **KL anchor 到冻结的 BC 策略**：``β=0.1`` 前 ``--anchor-iterations``（默认 200）次更新，
  之后 ``β=--anchor-beta-tail``（0.02）。anchor 项是**精确的 full-KL**（``Σ_a π_θ(a)·(log π_θ(a)
  - log π_ref(a))``，只用合法位），T=0 时 KL 恒为 0 —— 所以「开局即等于 BC」是被构造保证的。
- **不加熵奖励**（默认 ``--entropy-coef 0``）：BC 策略的熵已经高于教师，实测 T=1 比 greedy 低
  29%（``docs/COMPOUND_BC.md`` §6.1），再加熵只会更糟。
- 其它配方沿用已修好的那份：采集/训练**同一 dtype**、``batch_decisions`` 必须是
  ``minibatch × grad_accum`` 的整数倍（启动断言 + 余数结转）、``lr 3e-6``、``target_kl 0.02`` 早停。

用法::

    PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
    export PYTHONPATH=rust/python:.
    $PY scripts/train_compound_ppo.py --checkpoint runs/compound_bc/ckpt_main_w8e10.pt \
        --out runs/compound_bc/ppo/main --decisions 1000000 --device cuda:7 \
        --gold-mode fixed --gold-per-turn 20 --lr 3e-6 \
        --anchor-beta 0.1 --anchor-iterations 200 --anchor-beta-tail 0.02

产物：``<out>/model.pt``（最新）+ ``model_step_<N>.pt`` 快照 + ``history.jsonl``（逐次更新与逐局 stats）
+ ``meta.json``。**能力判据与停止规则在外部**（``scripts/eval_compound_bc.py``）：一旦 Σ 低于 BC
起点就杀进程并回退到 BC 权重。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _torch():
    import torch  # noqa: PLC0415
    return torch


# ── 配置 ────────────────────────────────────────────────────────────────────


def apply_reward_variant(args, cfg):
    """把 ``--reward-variant`` 映射到 SandboxConfig 的奖励字段（**不改共享模块**）。

    四个变体（task-11）：
    - ``telescope``（≡ dense_dlog ≡ γ=1 的 pbrs，Φ=log1p(Σ)）：每回合 ΔL 密集奖励；
    - ``pbrs99``：同上但 γ=0.99（势函数折扣对齐终局折扣）；
    - ``convexity``：终局 L + ``max(0, ln(Σ15/Σ12) − ln3)`` 凸性奖励（只在 t ≥ turns）；
    - ``mix``：终局 L + 超线性 ΔlnΣ + 凸性（三件套加权）；
    - ``final``：只在最后一回合给 L（稀疏对照）。
    """
    v = str(getattr(args, "reward_variant", "") or "")
    if not v:
        return cfg
    if v in ("telescope", "dense_dlog"):
        return cfg.replaced(reward="log_strength")
    if v == "pbrs99":
        return cfg.replaced(reward="log_strength")
    if v == "convexity":
        return cfg.replaced(reward="exp_growth", growth_w_final=1.0,
                            growth_w_super=0.0, growth_w_ratio=1.0,
                            growth_target_ratio=3.0, growth_ref_turn=12,
                            growth_from=int(cfg.turns))
    if v == "mix":
        return cfg.replaced(reward="exp_growth", growth_w_final=1.0,
                            growth_w_super=0.2, growth_slope_base=0.35,
                            growth_from=10, growth_w_ratio=0.5,
                            growth_target_ratio=3.0, growth_ref_turn=12)
    if v == "final":
        return cfg.replaced(reward="final_strength")
    raise SystemExit(f"未知 --reward-variant {v}")


def build_cfg(args):
    from hsbg.az.train.economy_sandbox import SandboxConfig  # noqa: PLC0415
    cfg = SandboxConfig(
        turns=int(args.turns), gold_mode=str(args.gold_mode),
        gold_per_turn=int(args.gold_per_turn),
        gold_growth_rate=float(args.gold_growth_rate),
        gold_per_carrier=int(args.gold_per_carrier),
        gold_cap=int(args.gold_cap), action_cap=int(args.action_cap),
        action_cap_per_gold=int(args.action_cap_per_gold),
        tavern_buff_scale=float(args.tavern_buff_scale),
        num_players=int(args.num_players), reward=str(args.reward),
        reward_mix=str(args.reward_mix or ""),
        trinkets=(None if int(args.trinkets) < 0 else bool(args.trinkets)),
        lobby_types=tuple(),
        strength_ref=float(args.strength_ref),
        gold_profile=str(getattr(args, "gold_profile", "") or ""),
        tier_reward_coef=float(getattr(args, "tier_reward_coef", 0.0) or 0.0),
    )
    return apply_reward_variant(args, cfg)


def _autocast(dtype: str):
    torch = _torch()
    if str(dtype) == "bf16" and torch.cuda.is_available():
        return torch.autocast("cuda", dtype=torch.bfloat16)
    return contextlib.nullcontext()


def _tens(x: np.ndarray, device, kind: str = "f32"):
    torch = _torch()
    if kind == "f32":
        t = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))
    elif kind == "i64":
        t = torch.from_numpy(np.ascontiguousarray(x, dtype=np.int64))
    else:
        t = torch.from_numpy(np.ascontiguousarray(x, dtype=bool))
    return t.to(device)


# ── 前向 ────────────────────────────────────────────────────────────────────


def policy_forward(model, f, c, m, *, dtype: str = "fp32", chunk: int = 8192):
    """-> (logits[float32, n,245], value[float32, n])；内部按 chunk 切，省显存。"""
    torch = _torch()
    from hsbg.az.train.ppo import forward_model  # noqa: PLC0415
    n = int(m.shape[0])
    out_l = np.empty((n, int(m.shape[1])), dtype=np.float32)
    out_v = np.empty(n, dtype=np.float32)
    for s in range(0, n, int(chunk)):
        e = min(n, s + int(chunk))
        with torch.no_grad(), _autocast(dtype):
            logits, _rank, value = forward_model(model, f[s:e], c[s:e], m[s:e])
        out_l[s:e] = logits.float().detach().cpu().numpy()
        out_v[s:e] = value.float().detach().reshape(-1).cpu().numpy()
    return out_l, out_v


def sample_actions(logits: np.ndarray, masks: np.ndarray, *, seed_rng: np.random.Generator
                   ) -> Tuple[np.ndarray, np.ndarray]:
    """按 masked softmax 采样（numpy 侧，避免 GPU↔CPU 往返），返回 (action, logp)。"""
    z = np.where(masks, logits.astype(np.float64), -np.inf)
    mx = np.max(z, axis=1, keepdims=True)
    e = np.exp(z - mx)
    p = e / e.sum(axis=1, keepdims=True)
    n = p.shape[0]
    u = seed_rng.random(n)[:, None]
    cdf = np.cumsum(p, axis=1)
    a = np.minimum((cdf < u).sum(axis=1), p.shape[1] - 1).astype(np.int64)
    # 数值兜底：落在 0 概率位（理论上不会）就退回 argmax
    ok = p[np.arange(n), a] > 0
    a[~ok] = np.argmax(p[~ok], axis=1)
    logp = np.log(np.maximum(p[np.arange(n), a], 1e-30))
    return a, logp.astype(np.float32)


# ── GAE ─────────────────────────────────────────────────────────────────────


def compute_gae(rewards: np.ndarray, values: np.ndarray, dones: np.ndarray,
                last_values: np.ndarray, *, gamma: float, lam: float
                ) -> Tuple[np.ndarray, np.ndarray]:
    """rewards/values/dones：[T, N]；last_values：[N]（最后一步之后的 bootstrap 价值）。"""
    T, N = rewards.shape
    adv = np.zeros((T, N), dtype=np.float64)
    gae = np.zeros(N, dtype=np.float64)
    for t in range(T - 1, -1, -1):
        nonterm = 1.0 - dones[t].astype(np.float64)
        next_v = last_values if t == T - 1 else values[t + 1]
        delta = rewards[t] + gamma * next_v * nonterm - values[t]
        gae = delta + gamma * lam * nonterm * gae
        adv[t] = gae
    return adv, adv + values


# ── 训练 ────────────────────────────────────────────────────────────────────


def train(args) -> Dict[str, Any]:
    torch = _torch()
    from hsbg.az.train.economy_sandbox import (  # noqa: PLC0415
        VectorEconomySandbox)
    from hsbg.az.train.model import load_checkpoint, save_checkpoint  # noqa: PLC0415
    from hsbg.az.train.ppo import (  # noqa: PLC0415
        forward_model, masked_log_softmax_torch)
    import copy

    device = str(args.device)
    dtype = str(args.dtype)
    torch.manual_seed(int(args.seed))
    np.random.seed(int(args.seed) % 2 ** 31)
    rng_pol = np.random.default_rng(int(args.seed) + 1)     # 动作采样用的 numpy RNG

    cfg = build_cfg(args)
    mb = int(args.minibatch)
    ga = int(args.grad_accum)
    bd = int(args.batch_decisions)
    if bd % (mb * ga) != 0:
        raise SystemExit(
            f"--batch-decisions 必须是 minibatch×grad-accum 的整数倍：{bd} % "
            f"({mb}×{ga}) = {bd % (mb * ga)}；建议 {((bd // (mb * ga)) + 1) * mb * ga}")
    n_envs = int(args.envs)
    steps = max(1, bd // n_envs)

    model, meta = load_checkpoint(str(args.checkpoint), device=device)
    model.to(device)
    # **全程 eval**：实体模型有 dropout=0.1，train 模式下同一批观测的 logits 会变，
    # 导致 old logp 与更新时 logp 对不上（假 KL 0.1–0.26，每批都被 KL 早停打掉）。
    model.eval()
    ref = copy.deepcopy(model).to(device).eval()
    for p in ref.parameters():
        p.requires_grad_(False)
    n_param = int(sum(p.numel() for p in model.parameters()))
    print(f"[ppo] 起点 {args.checkpoint}（{meta.get('size')} {n_param / 1e6:.2f}M）；"
          f"envs={n_envs} steps/update={steps} batch={bd} minibatch={mb} ga={ga}", flush=True)
    print(f"[ppo] 配置 gold={cfg.gold_mode}/{cfg.gold_per_turn} reward={cfg.reward} "
          f"turns={cfg.turns} action_cap={cfg.action_cap} lr={args.lr} "
          f"anchor β={args.anchor_beta}→{args.anchor_beta_tail}@{args.anchor_iterations}",
          flush=True)

    opt = torch.optim.Adam([p for p in model.parameters() if p.requires_grad],
                           lr=float(args.lr))
    vec = VectorEconomySandbox(cfg, n_envs=n_envs, seed0=int(args.seed0))
    obs = vec.reset()
    from hsbg.az.train.economy_sandbox import stack_obs  # noqa: PLC0415

    os.makedirs(str(args.out), exist_ok=True)
    hist_path = os.path.join(str(args.out), "history.jsonl")
    hist_f = open(hist_path, "w", encoding="utf-8")
    decisions = 0
    updates = 0
    warmed = False
    stopped_early = False
    rows_hist: List[Dict[str, Any]] = []
    ep_sigma: List[float] = []
    t0 = time.time()
    best_sigma = -1.0
    try:
        while decisions < int(args.decisions):
            # ── 采集一个 batch（steps × n_envs）────────────────────────────
            # 采集必须在 eval 模式：train 模式下 dropout 会让「同一个权重」对同一批观测
            # 给出不同 logits → old logp 与更新后 logp 对不上，approx_kl 假性 0.3+
            # （踩过：smoke 里每批都 KL 早停，等于只做 1 个 minibatch 更新）。
            model.eval()
            F: List[np.ndarray] = []
            C: List[np.ndarray] = []
            M: List[np.ndarray] = []
            A: List[np.ndarray] = []
            LP: List[np.ndarray] = []
            V: List[np.ndarray] = []
            R: List[np.ndarray] = []
            D: List[np.ndarray] = []
            for _ in range(steps):
                f, c, m = stack_obs(obs)
                fT = _tens(f, device, "f32")
                cT = _tens(c, device, "i64")
                mT = _tens(m, device, "bool")
                logits, value = policy_forward(model, fT, cT, mT, dtype=dtype)
                a, logp = sample_actions(logits, m, seed_rng=rng_pol)
                obs, rew, dones, infos = vec.step([int(x) for x in a])
                d = np.asarray(dones, dtype=bool)
                for i, done in enumerate(d):
                    if done:
                        ep = infos[i].get("episode") or {}
                        if ep:
                            ep_sigma.append(float(ep.get("sigma_t15") or 0))
                F.append(f); C.append(c); M.append(m)
                A.append(a); LP.append(logp); V.append(value)
                R.append(np.asarray(rew, dtype=np.float32)); D.append(d)
                decisions += n_envs
            fA = np.concatenate(F, axis=0).astype(np.float32)     # [T*N, 3227]
            cA = np.concatenate(C, axis=0).astype(np.int64)
            mA = np.concatenate(M, axis=0).astype(bool)
            aA = np.concatenate(A, axis=0).astype(np.int64)
            lpA = np.concatenate(LP, axis=0).astype(np.float32)
            vA = np.concatenate(V, axis=0).astype(np.float32)
            rA = np.concatenate(R, axis=0).astype(np.float32)
            dA = np.concatenate(D, axis=0).astype(bool)
            T = len(F)
            r2 = rA.reshape(T, n_envs)
            v2 = vA.reshape(T, n_envs)
            d2 = dA.reshape(T, n_envs)
            # 尾部 bootstrap 价值
            f2, c2, m2 = stack_obs(obs)
            _, last_v = policy_forward(model, _tens(f2, device, "f32"),
                                       _tens(c2, device, "i64"),
                                       _tens(m2, device, "bool"), dtype=dtype)
            adv2, ret2 = compute_gae(r2, v2, d2, last_v, gamma=float(args.gamma),
                                     lam=float(args.lam))
            advA = adv2.reshape(-1).astype(np.float32)
            retA = ret2.reshape(-1).astype(np.float32)
            advA = (advA - advA.mean()) / (advA.std() + 1e-8)
            n = (len(aA) // mb) * mb          # 只用到 minibatch 的整数倍，余数丢弃
            if n <= 0:
                raise SystemExit(f"batch 太小：{len(aA)} 行 < minibatch {mb}")

            # ── value 预热（关键）：BC 起点的 value 头是**随机**的。诊断实测
            #    V∈[-0.98,+0.98]（|V| 均值 0.49），而真实整局 return∈[0.57,0.76]（中位 0.69）；
            #    GAE 的 advantage 与真实优势相关只有 0.55、符号一致率 52.8%（= 抛硬币）。
            #    **只训 value_head**：entity 的 value 头与策略共享 trunk，整网回传会把 trunk
            #    推歪，策略在 PPO 之前就漂了（踩过：anchor_kl 首行 0.205、130k 后 Σ 1646→524）。
            if int(args.value_warmup) > 0 and not warmed:
                vh = [p for nm, p in model.named_parameters()
                      if nm.startswith("value_head")]
                if not vh:
                    raise SystemExit("模型没有 value_head，--value-warmup 不适用")
                opt_v = torch.optim.Adam(vh, lr=float(args.value_lr))
                for _w in range(int(args.value_warmup)):
                    order = rng_pol.permutation(n)
                    for j in range(n // mb):
                        sel = order[j * mb:(j + 1) * mb]
                        fT = _tens(fA[sel], device, "f32")
                        cT = _tens(cA[sel], device, "i64")
                        mT = _tens(mA[sel], device, "bool")
                        retT = _tens(retA[sel], device, "f32")
                        with _autocast(dtype):
                            _lg, _rk, value = forward_model(model, fT, cT, mT)
                        vloss = torch.nn.functional.mse_loss(
                            value.float().reshape(-1), retT)
                        opt_v.zero_grad(set_to_none=True)
                        vloss.backward()
                        for nm, p in model.named_parameters():   # 丢掉 trunk 梯度
                            if not nm.startswith("value_head") and p.grad is not None:
                                p.grad = None
                        opt_v.step()
                model.zero_grad(set_to_none=True)
                with torch.no_grad():
                    fT = _tens(fA, device, "f32")
                    cT = _tens(cA, device, "i64")
                    mT = _tens(mA, device, "bool")
                    lg2, _rk, v_now = forward_model(model, fT, cT, mT)
                    v_err = float((v_now.float().reshape(-1)
                                   - _tens(retA, device, "f32")).abs().mean())
                    lp2 = masked_log_softmax_torch(lg2.float(), mT).gather(
                        1, _tens(aA, device, "i64").unsqueeze(1)).squeeze(1)
                    drift = float((lp2.cpu().numpy() - lpA).mean())
                print(f"[ppo] value 预热 {args.value_warmup} 遍：|V-return| 均值 "
                      f"{v_err:.4f}（BC 起点 ≈0.5）；**策略漂移 Δlogp={drift:+.6f}"
                      f"（必须≈0）**", flush=True)
                warmed = True

            # ── 更新（一个 batch 内按 minibatch 重复 epochs 遍）────────────
            idx = np.arange(n)
            sum_kl = sum_ent = sum_pg = sum_v = sum_anchor = 0.0
            n_upd = 0
            stop = False
            for _ep in range(int(args.epochs)):
                rng_pol.shuffle(idx)
                opt.zero_grad(set_to_none=True)
                n_mb = n // mb
                for j in range(n_mb):
                    sel = idx[j * mb:(j + 1) * mb]
                    fT = _tens(fA[sel], device, "f32")
                    cT = _tens(cA[sel], device, "i64")
                    mT = _tens(mA[sel], device, "bool")
                    aT = _tens(aA[sel], device, "i64")
                    oldT = _tens(lpA[sel], device, "f32")
                    advT = _tens(advA[sel], device, "f32")
                    retT = _tens(retA[sel], device, "f32")
                    with _autocast(dtype):
                        logits, _rank, value = forward_model(model, fT, cT, mT)
                    logits = logits.float()
                    logp_all = masked_log_softmax_torch(logits, mT)
                    logp = logp_all.gather(1, aT.unsqueeze(1)).squeeze(1)
                    ratio = torch.exp(logp - oldT)
                    pg = -torch.min(ratio * advT,
                                    torch.clamp(ratio, 1.0 - float(args.clip),
                                                1.0 + float(args.clip)) * advT).mean()
                    vloss = torch.nn.functional.mse_loss(value.float().reshape(-1), retT)
                    # 与冻结 BC 的 full-KL（精确，只在合法位上）
                    with torch.no_grad(), _autocast(dtype):
                        rlogits, _r, _v = forward_model(ref, fT, cT, mT)
                    rlogp_all = masked_log_softmax_torch(rlogits.float(), mT)
                    p = logp_all.exp()
                    kl_anchor = (p.detach() * (logp_all - rlogp_all)).sum(dim=-1).mean()
                    ent = -(p.detach() * logp_all).sum(dim=-1).mean()
                    beta = (float(args.anchor_beta) if updates < int(args.anchor_iterations)
                            else float(args.anchor_beta_tail))
                    loss = (pg + float(args.value_coef) * vloss
                            - float(args.entropy_coef) * ent + beta * kl_anchor)
                    (loss / ga).backward()      # 梯度累积：mb×ga 才是有效 batch
                    if (j + 1) % ga == 0 or (j + 1) == n_mb:
                        if float(args.max_grad_norm) > 0:
                            torch.nn.utils.clip_grad_norm_(model.parameters(),
                                                           float(args.max_grad_norm))
                        opt.step()
                        opt.zero_grad(set_to_none=True)
                    with torch.no_grad():
                        approx_kl = float((oldT - logp).mean())
                    n_upd += 1
                    updates += 1
                    sum_kl += approx_kl
                    sum_ent += float(ent)
                    sum_pg += float(pg)
                    sum_v += float(vloss)
                    sum_anchor += float(kl_anchor)
                    if float(args.target_kl) > 0 and approx_kl > float(args.target_kl):
                        stop = True
                        break
                if stop:
                    break
            row = {
                "decisions": int(decisions),
                "updates": int(updates),
                "n_upd_batch": int(n_upd),
                "approx_kl": sum_kl / max(1, n_upd),
                "entropy": sum_ent / max(1, n_upd),
                "policy_loss": sum_pg / max(1, n_upd),
                "value_loss": sum_v / max(1, n_upd),
                "anchor_kl": sum_anchor / max(1, n_upd),
                "beta": (float(args.anchor_beta) if updates <= int(args.anchor_iterations)
                         else float(args.anchor_beta_tail)),
                "ep_sigma_p50": float(np.percentile(ep_sigma[-64:], 50)) if ep_sigma else 0.0,
                "episodes": len(ep_sigma),
                "dec_per_s": round(decisions / max(1e-9, time.time() - t0), 0),
                "kl_early_stop": bool(stop),
                "seconds": round(time.time() - t0, 1),
            }
            hist_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            hist_f.flush()
            rows_hist.append(row)
            print("[ppo] " + json.dumps(row, ensure_ascii=False), flush=True)
            _thr = float(args.stop_if_sigma_below)
            _pat = int(args.stop_patience)
            if _thr > 0 and len(rows_hist) >= _pat and all(
                    (r0["ep_sigma_p50"] < _thr) for r0 in rows_hist[-_pat:]):
                print(f"[ppo] 早停：ep_sigma_p50 连续 {_pat} 次低于 {_thr}（退化保护）",
                      flush=True)
                stopped_early = True
                break
            # 快照
            if int(args.save_every) > 0 and decisions >= int(args.save_every) * (
                    (getattr(args, "_saved", 0)) + 1):
                tag = f"model_step_{decisions // 1000}k.pt"
                save_checkpoint(model, os.path.join(str(args.out), tag),
                                meta={"trained_by": "scripts/train_compound_ppo.py",
                                      "decisions": decisions, **{
                                          k: meta.get(k) for k in
                                          ("arch", "d_model", "n_layers", "n_heads",
                                           "size")}})
                args._saved = getattr(args, "_saved", 0) + 1
                save_checkpoint(model, os.path.join(str(args.out), "model.pt"),
                                meta={"trained_by": "scripts/train_compound_ppo.py",
                                      "decisions": decisions})
                print(f"[ppo] 快照 {tag}", flush=True)
            if decisions >= int(args.decisions):
                break
    finally:
        hist_f.close()

    save_checkpoint(model, os.path.join(str(args.out), "model.pt"),
                    meta={"trained_by": "scripts/train_compound_ppo.py",
                          "decisions": decisions})
    rep = {"out": str(args.out), "decisions": int(decisions), "updates": int(updates),
           "params": n_param, "cfg": {"gold_mode": cfg.gold_mode,
                                       "gold_per_turn": cfg.gold_per_turn,
                                       "reward": cfg.reward, "turns": cfg.turns},
           "ep_sigma_p50": float(np.percentile(ep_sigma, 50)) if ep_sigma else 0.0,
           "stopped_early": bool(stopped_early),
           "reward_variant": str(getattr(args, "reward_variant", "") or ""),
           "history": hist_path, "seconds": round(time.time() - t0, 1)}
    with open(os.path.join(str(args.out), "meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"args": vars(args), **rep}, fh, ensure_ascii=False, indent=1)
    print("[ppo] " + json.dumps(rep, ensure_ascii=False), flush=True)
    return rep


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="BC→PPO 微调（沙盒，直接优化 Σ）")
    ap.add_argument("--checkpoint", required=True, help="BC 权重（策略初始化 + KL anchor 的 ref）")
    ap.add_argument("--out", default="runs/compound_bc/ppo/main")
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--dtype", default="fp32", choices=["fp32", "bf16"])
    ap.add_argument("--decisions", type=int, default=1_000_000)
    ap.add_argument("--envs", type=int, default=96)
    ap.add_argument("--batch-decisions", dest="batch_decisions", type=int, default=16384)
    ap.add_argument("--minibatch", type=int, default=1024)
    ap.add_argument("--grad-accum", dest="grad_accum", type=int, default=8)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--lr", type=float, default=3e-6)
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--target-kl", dest="target_kl", type=float, default=0.02)
    ap.add_argument("--gamma", type=float, default=1.0)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--entropy-coef", dest="entropy_coef", type=float, default=0.0,
                    help="默认 0：BC 策略熵已偏高，加熵会让 T=1 更差（见 COMPOUND_BC §6.1）")
    ap.add_argument("--value-coef", dest="value_coef", type=float, default=0.5)
    ap.add_argument("--max-grad-norm", dest="max_grad_norm", type=float, default=1.0)
    ap.add_argument("--anchor-beta", dest="anchor_beta", type=float, default=0.1)
    ap.add_argument("--anchor-iterations", dest="anchor_iterations", type=int, default=200)
    ap.add_argument("--anchor-beta-tail", dest="anchor_beta_tail", type=float, default=0.02)
    ap.add_argument("--reward-variant", dest="reward_variant", default="",
                    help="telescope|pbrs99|convexity|mix|final（覆盖 --reward 与 growth_*）")
    ap.add_argument("--value-warmup", dest="value_warmup", type=int, default=0,
                    help=">0 时先用这么多遍回归把 value 头拟合到 return 再动策略"
                         "（诊断见 docs/COMPOUND_BC.md §9：BC 起点 value 头是随机的）")
    ap.add_argument("--value-lr", dest="value_lr", type=float, default=1e-3,
                    help="value 预热的学习率（只训 value_head）")
    ap.add_argument("--stop-if-sigma-below", dest="stop_if_sigma_below", type=float,
                    default=0.0, help=">0 时训练侧 ep_sigma_p50 连续低于它就早停")
    ap.add_argument("--stop-patience", dest="stop_patience", type=int, default=3)
    ap.add_argument("--save-every", dest="save_every", type=int, default=250_000)
    # 沙盒配置
    ap.add_argument("--turns", type=int, default=15)
    ap.add_argument("--gold-mode", dest="gold_mode", default="fixed",
                    choices=["fixed", "add", "growth", "set"])
    ap.add_argument("--gold-per-turn", dest="gold_per_turn", type=int, default=20)
    ap.add_argument("--gold-growth-rate", dest="gold_growth_rate", type=float, default=0.0)
    ap.add_argument("--gold-per-carrier", dest="gold_per_carrier", type=int, default=0)
    ap.add_argument("--gold-profile", dest="gold_profile", default="",
                    help="task-13：按回合金币曲线 \"3,4,5,...\"（空 = 用 gold_mode）；"
                         "完整对局实测 t1..t13 = 3,4,5,6,7,8,9,10,10,10,10,10,11")
    ap.add_argument("--tier-reward-coef", dest="tier_reward_coef", type=float,
                    default=0.0,
                    help="task-13：每回合 tier 增量 × coef 加进奖励（0 = 关）；"
                         "Titus/Drakkari 是 tier5、Gatekeeper 是 tier6")
    ap.add_argument("--gold-cap", dest="gold_cap", type=int, default=99)
    ap.add_argument("--action-cap", dest="action_cap", type=int, default=40)
    ap.add_argument("--action-cap-per-gold", dest="action_cap_per_gold", type=int,
                    default=0)
    ap.add_argument("--tavern-buff-scale", dest="tavern_buff_scale", type=float,
                    default=1.0)
    ap.add_argument("--num-players", dest="num_players", type=int, default=8)
    ap.add_argument("--reward", default="log_strength")
    ap.add_argument("--reward-mix", dest="reward_mix", default="")
    ap.add_argument("--trinkets", type=int, default=1)
    ap.add_argument("--strength-ref", dest="strength_ref", type=float, default=30000.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--seed0", type=int, default=930000, help="环境 seed 基")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if str(args.reward_variant) == "pbrs99":
        args.gamma = 0.99            # 势函数折扣对齐：终局折扣但势函数按 0.99
    rep = train(args)
    print(json.dumps(rep, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
