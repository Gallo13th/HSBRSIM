#!/usr/bin/env python3
"""在**纯经济沙盒**里训练缩放策略（PPO，可选 teacher BC 热身）。

沙盒见 ``hsbg/az/train/economy_sandbox.py``：只有 recruit 阶段、无对手/无战斗/
无血量/无排名，15 回合、每回合固定金币，奖励是战团 Σ 的 log1p 曲线
（``--sandbox-reward``），不是名次。

起点：``runs/az_entity_s14/model.pt``（或 ``--from-scratch``）。用**同一套
obs_std 3227+124 / 245 动作 / 同一实体 Transformer**，所以权重可以直接放回
完整游戏（迁移验证见 ``scripts/quality_monitor.py``）。

配方（2026-10-31 修正，对齐 ``docs/ECONOMY_SANDBOX.md`` §6）
------------------------------------------------------------
1. **采集与训练同一 dtype**（``--dtype fp32`` 默认，或 ``bf16`` 采集也开 autocast）：
   并在启动时用真实观测做一次 logprob 自检（``max|Δlogp|`` 超容差直接报错）。
   历史上「采集 fp32 / 训练 bf16」会让同一个动作的 logprob 差 0.44 nats →
   ``approx_kl≈0.3`` → KL 早停把每次更新都跳过（策略不动）。
2. **batch 必须是 ``minibatch×grad_accum`` 的整数倍**：启动断言 + 采样侧把
   已完成轨迹裁到整数倍、余数留到下一次更新（不丢样本、不留"残余组"）。
3. 默认 ``lr=3e-6``、``minibatch=1024``、``grad_accum=8``（有效 8192）、
   ``batch_decisions=16384``、``epochs=1``（dd3 的稳定档；lr≥1.5e-5 会退化）。
4. **按每局 L_T（终局强度）记进度**：``ep_LT_*``（奖励望远镜求和 = L_T），
   **不看**逐决策均值 ``ret_mean``（会被"少做动作"抬高）。
5. **金币课程** ``--sandbox-gold-ramp "0:99,2M:30,6M:15,10M:10"``：按累计决策数
   切换每回合金币（新 reset 的局立刻生效）；评测用当前档位。
6. ``--sandbox-free-tier6 1`` 打开 ceiling_probe 的 ``--cheat tier6`` 口径
   （开局 tier6 + 升级免费），默认 0 = 真实经济。

小模型
------
``--arch tiny`` **不可用**：``TinyAZNet`` 没有标量 value 头（只返回
``(logits, 8-rank logits)``），沙盒 PPO 的 GAE 需要 scalar value；且它的观测编码是
3227→MLP，和完整游戏的 entity token 编码不一致（不能直接回迁）。**支持的小模型
是同一架构的小 entity**：``--arch entity --d-model 256 --n-layers 4``（3.57M
参数，观测/动作/value 头与 14.8M 的 s14 逐项一致，checkpoint 可直接回完整游戏）。

典型用法::

  # 主臂：s14 起点 + 金币课程 + 10M 决策
  python scripts/train_economy_sandbox.py \
      --checkpoint runs/az_entity_s14/model.pt --device cuda:7 \
      --out runs/economy_sandbox/s16_sb_main --decisions 10000000 \
      --sandbox-gold-ramp "0:99,2M:30,6M:15,10M:10" \
      --eval-every 1000000 --eval-games 32 --save-every 1000000

  # 小模型从零（3.57M）
  python scripts/train_economy_sandbox.py --from-scratch \
      --arch entity --d-model 256 --n-layers 4 --decisions 2000000
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
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    N_ACTIONS, OBS_CARDS, OBS_FLOATS, END_TURN, EconomySandbox, SandboxConfig,
    SandboxObs, SandboxPolicies, VectorEconomySandbox, carrier_ids, stack_obs,
    summarize)


def _torch():
    import torch
    return torch


# ── 参数解析辅助 ────────────────────────────────────────────────────────────


def _num(s: str) -> int:
    """``"2M"`` -> 2_000_000；``"500k"`` -> 500_000；``"12345"`` -> 12345。"""
    t = str(s).strip().lower().replace("_", "")
    m = 1.0
    if t.endswith("m"):
        m, t = 1e6, t[:-1]
    elif t.endswith("k"):
        m, t = 1e3, t[:-1]
    return int(round(float(t) * m))


def parse_ramp(spec: str, *, name: str = "ramp", vmin: int = 0,
               vmax: int = 99) -> List[Tuple[int, int]]:
    """解析 ``"0:99,2M:30,6M:15,10M:10"`` -> ``[(0,99),(2000000,30),...]``（升序）。

    ``vmin/vmax`` 是档位值域（金币 0..99、每回合动作上限 1..200 等）。
    """
    if not spec or not str(spec).strip():
        return []
    pts: List[Tuple[int, int]] = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"{name} 项 {part!r} 需要 'decisions:value'")
        a, b = part.split(":", 1)
        pts.append((_num(a), int(float(b))))
    pts.sort(key=lambda x: x[0])
    if pts[0][0] != 0:
        raise ValueError(f"{name} 的第一个点必须是 0")
    for d, g in pts:
        if d < 0 or not (int(vmin) <= g <= int(vmax)):
            raise ValueError(f"{name} 非法点 {d}:{g}"
                             f"（decisions>=0，取值在 {vmin}..{vmax}）")
    for (d0, _g0), (d1, _g1) in zip(pts, pts[1:]):
        if d1 <= d0:
            raise ValueError(f"{name} 的阈值必须严格递增")
    return pts


def parse_gold_ramp(spec: str) -> List[Tuple[int, int]]:
    """金币课程解析（取值 0..99）。"""
    return parse_ramp(spec, name="gold-ramp", vmin=0, vmax=99)


def parse_cap_ramp(spec: str) -> List[Tuple[int, int]]:
    """每回合动作上限课程解析（取值 1..200）。"""
    return parse_ramp(spec, name="action-cap-ramp", vmin=1, vmax=200)


def gold_at(ramp: Sequence[Tuple[int, int]], decisions: int, default: int) -> int:
    """当前决策数对应的金币档位。"""
    g = int(default)
    for th, gg in ramp:
        if int(decisions) >= int(th):
            g = int(gg)
    return g


# ── 模型 ────────────────────────────────────────────────────────────────────


def build_model(args) -> Tuple[Any, Dict[str, Any]]:
    from hsbg.az.train.model import build_net, load_checkpoint
    if args.checkpoint:
        model, meta = load_checkpoint(args.checkpoint, device="cpu")
        meta = dict(meta or {})
        print(f"[sandbox] 载入 {args.checkpoint} arch={meta.get('arch')} "
              f"d_model={meta.get('d_model')} layers={meta.get('n_layers')}", flush=True)
        return model, meta
    if args.arch == "tiny":
        raise SystemExit(
            "[sandbox] --arch tiny 不可用（已核实，见模块 docstring「小模型」）：\n"
            "  · TinyAZNet 只返回 (policy_logits, 8-rank logits)，**没有标量 value 头**，\n"
            "    而沙盒 PPO 用 GAE + value_loss=mse 必须有 scalar value；\n"
            "  · 它的观测编码是 3227→MLP，与完整游戏的 entity token 编码不一致，\n"
            "    权重无法直接回迁（违反「观测/动作头一致」这条前提）。\n"
            "  改用同一架构的小 entity：--arch entity --d-model 256 --n-layers 4"
            "（3.57M 参数，头完全一致）。")
    model = build_net(arch="entity", d_model=int(args.d_model),
                      n_layers=int(args.n_layers), n_heads=int(args.n_heads))
    meta = {"arch": "entity", "d_model": int(args.d_model),
            "n_layers": int(args.n_layers), "n_heads": int(args.n_heads)}
    n = sum(p.numel() for p in model.parameters())
    print(f"[sandbox] 从零构建 entity d_model={args.d_model} layers={args.n_layers} "
          f"params={n / 1e6:.2f}M", flush=True)
    return model, meta


# ── 前向 / 采样 ─────────────────────────────────────────────────────────────


def _to_tensors(feats, cards, masks, device):
    torch = _torch()
    f = torch.from_numpy(np.ascontiguousarray(feats, dtype=np.float32)).to(device)
    c = torch.from_numpy(np.ascontiguousarray(cards, dtype=np.int64)).to(device)
    m = torch.from_numpy(np.ascontiguousarray(masks, dtype=bool)).to(device)
    return f, c, m


def _autocast_ctx(dtype: str):
    """采集/训练共用的 autocast：``fp32`` -> 无 autocast；``bf16`` -> CUDA bf16。"""
    torch = _torch()
    if str(dtype) == "bf16" and torch.cuda.is_available():
        return torch.autocast("cuda", dtype=torch.bfloat16)
    return contextlib.nullcontext()


def batch_act(model, feats, cards, masks, device, *, sample: bool = True,
              chunk: int = 4096, dtype: str = "fp32",
              bias: Optional[np.ndarray] = None):
    """批量策略：返回 (actions, logprobs, values)（numpy）。

    ``dtype`` 必须与训练一致（``PPOConfig.amp``）：采集与训练不同 dtype 会让
    logprob 不一致 → ratio 起点偏离 1 → KL 早停。

    ``bias``（``f32[n, 245]``，复利核心牌先验／背景惩罚）**只改采样分布**：
    采样用 ``logits + bias``，但返回的 ``logprobs`` 仍是**无偏** logits 的对数似然。
    这样 PPO 的 ``ratio = exp(new - old)`` 在第一次更新时仍严格等于 1（不会被 KL
    早停打掉），而梯度会把策略往「先验偏好的动作」推 —— 等价于用先验做行为整形。
    """
    torch = _torch()
    from hsbg.az.train.ppo import forward_model
    model.eval()
    n = len(masks)
    acts = np.empty(n, dtype=np.int64)
    logps = np.empty(n, dtype=np.float32)
    vals = np.empty(n, dtype=np.float32)
    with torch.no_grad(), _autocast_ctx(dtype):
        for s in range(0, n, chunk):
            e = min(n, s + chunk)
            f, c, m = _to_tensors(feats[s:e], cards[s:e], masks[s:e], device)
            logits, _rank, value = forward_model(model, f, c, m)
            logits = logits.float().masked_fill(~m, -1e9)
            logp_all = torch.log_softmax(logits, dim=-1)
            if bias is not None:
                bt = torch.from_numpy(
                    np.ascontiguousarray(bias[s:e], dtype=np.float32)).to(device)
                s_logits = (logits + bt).masked_fill(~m, -1e9)
            else:
                s_logits = logits
            if sample:
                # 无 bias 时保持旧路径（``logp_all.exp()``）逐位不变
                probs = (logp_all.exp() if bias is None
                         else torch.softmax(s_logits, dim=-1))
                a = torch.multinomial(probs, 1).squeeze(1)
            else:
                a = s_logits.argmax(dim=-1)
            lp = logp_all.gather(1, a.unsqueeze(1)).squeeze(1)
            acts[s:e] = a.detach().cpu().numpy()
            logps[s:e] = lp.detach().cpu().numpy()
            vals[s:e] = value.detach().float().cpu().numpy()
    return acts, logps, vals


def prior_bias_rows(prior, obs: Sequence[SandboxObs], game_ids: Sequence[int],
                    *, seat: int = 0) -> Optional[np.ndarray]:
    """一批观测 → ``f32[n, 245]`` 先验 bias；``prior is None`` 时返回 ``None``（逐位等价）。

    走 :meth:`hsbg.az.train.compound_prior.CompoundPrior.bias`（与正式采集同一套口径：
    只给合法的 Buy/Choose 位写值、只加不减 + 可选背景惩罚）。
    """
    if prior is None:
        return None
    out = np.zeros((len(obs), 245), dtype=np.float32)
    touched = False
    for i, o in enumerate(obs):
        b = prior.bias(o.features, o.cards, o.mask,
                       game_id=int(game_ids[i]), seat=int(seat))
        if b is not None:
            out[i] = b
            touched = True
    return out if touched else None


def check_logprob_consistency(model, obs_batch: Sequence[SandboxObs], device: str,
                              *, dtype: str, n: int = 64) -> float:
    """启动自检：**采集路径**与**训练路径**的 logprob 必须一致（同一 dtype 口径）。

    这正是历史上让 PPO 完全失效的那类 bug 的护栏（采集 fp32 / 训练 bf16 →
    同一个动作 logprob 差 0.44 nats → approx_kl≈0.3 → 每次更新都被 KL 早停跳过）。
    超容差直接 ``AssertionError``，不进入训练。
    """
    torch = _torch()
    from hsbg.az.train.ppo import forward_model
    f, c, m = stack_obs(list(obs_batch)[:max(2, int(n))])
    a, lp_collect, _v = batch_act(model, f, c, m, device, sample=False, dtype=dtype)
    model.eval()
    with torch.no_grad():
        ft, ct, mt = _to_tensors(f, c, m, device)
        with _autocast_ctx(dtype):
            logits, _r, _v2 = forward_model(model, ft, ct, mt)
        logits = logits.float().masked_fill(~mt, -1e9)
        at = torch.from_numpy(a).to(device)
        lp_train = torch.log_softmax(logits, dim=-1).gather(
            1, at.unsqueeze(1)).squeeze(1)
        diff = float((lp_train
                      - torch.from_numpy(lp_collect.astype(np.float32)).to(device)
                      ).abs().max().detach().cpu())
    tol = 1e-4 if str(dtype) == "fp32" else 2e-2
    print(f"[sandbox] dtype 自检 dtype={str(dtype)} n={len(m)} "
          f"max|Δlogp|={diff:.3e} tol={tol:g}", flush=True)
    if not (diff <= tol):
        raise AssertionError(
            f"采集/训练 logprob 不一致：max|Δlogp|={diff:.4g} > {tol:g}。"
            f"采集 dtype={dtype} 与训练 amp 必须相同（统一 fp32 或统一 bf16）。")
    return diff


# ── 轨迹 → PPOBatch ─────────────────────────────────────────────────────────


def episode_ready_steps(traj: Sequence[Dict[str, Any]], *, gamma: float, lam: float,
                        ep_index: int) -> Tuple[List[Dict[str, Any]], float, int]:
    """把一条**完整**轨迹转成逐决策记录（附 adv/ret/每局 L_T）。"""
    from hsbg.az.train.ppo import compute_gae
    n = len(traj)
    r = np.asarray([float(s["reward"]) for s in traj], dtype=np.float32)
    v = np.asarray([float(s["value"]) for s in traj], dtype=np.float32)
    d = np.zeros(n, dtype=np.float32)
    d[-1] = 1.0
    adv, ret = compute_gae(r, v, d, gamma=float(gamma), lam=float(lam))
    out: List[Dict[str, Any]] = []
    for i, s in enumerate(traj):
        rec = dict(s)
        rec["adv"] = float(adv[i])
        rec["ret"] = float(ret[i])
        rec["ep"] = int(ep_index)
        rec["done"] = bool(i == n - 1)
        out.append(rec)
    # ``board_delta``/``log_strength`` 的奖励是望远镜求和 -> 整局求和 = L_T
    return out, float(r.sum()), n


def build_ppo_batch(records: Sequence[Dict[str, Any]]) -> Any:
    """由已算好 adv/ret 的逐决策记录拼一个 ``PPOBatch``（可跨局）。"""
    from hsbg.az.train.ppo import PPOBatch
    n = len(records)
    feats = np.asarray([s["features"] for s in records], dtype=np.float32)
    cards = np.asarray([s["cards"] for s in records], dtype=np.int32)
    masks = np.asarray([s["mask"] for s in records], dtype=bool)
    actions = np.asarray([int(s["action"]) for s in records], dtype=np.int64)
    old_logps = np.asarray([float(s["logprob"]) for s in records], dtype=np.float32)
    values = np.asarray([float(s["value"]) for s in records], dtype=np.float32)
    rewards = np.asarray([float(s["reward"]) for s in records], dtype=np.float32)
    adv = np.asarray([float(s["adv"]) for s in records], dtype=np.float32)
    ret = np.asarray([float(s["ret"]) for s in records], dtype=np.float32)
    turns = np.asarray([int(s["turn"]) for s in records], dtype=np.int32)
    eps = np.asarray([int(s.get("ep", 0)) for s in records], dtype=np.int64)
    # 校验器要求每个 episode 恰好 1 个 done；跨 update 结转会把一局切开，
    # 所以按「本批内每局最后一个决策」打 done（GAE 已在整局上算好，done 只做记录）
    dones = np.zeros(n, dtype=np.float32)
    _last: Dict[int, int] = {}
    for i, e in enumerate(eps):
        _last[int(e)] = i
    for i in _last.values():
        dones[i] = 1.0
    return PPOBatch(
        features=feats, cards=cards, masks=masks, actions=actions,
        old_logprobs=old_logps, values=values, rewards=rewards, dones=dones,
        advantages=adv, returns=ret,
        seats=np.zeros(n, dtype=np.int32),
        game_ids=eps,
        ranks=np.ones(n, dtype=np.int64),
        turns=turns,
        target_pi=np.zeros((n, N_ACTIONS), dtype=np.float32),
        has_pi=np.zeros(n, dtype=bool),
        episode_ids=eps.astype(np.int32),
        forced=np.zeros(n, dtype=bool),
        meta={"sandbox": True, "episodes": int(len(np.unique(eps)))})


# ── 评测 ────────────────────────────────────────────────────────────────────


def evaluate(model, cfg: SandboxConfig, games: int, device: str,
             seed0: int = 900000, n_envs: int = 48, *,
             sample: bool = False, dtype: str = "fp32",
             carrier_audit: int = 0, prior=None,
             core_ids: Optional[Sequence[str]] = None,
             trinket_ids: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """评测：``sample=False`` 走 greedy（argmax），``sample=True`` 按 T=1 采样。

    注意：完整游戏里的行为策略（``PPOSelfPlayPolicy``，``CollectConfig.temperature``）
    也是**采样**的，所以迁移口径以 ``sample=True`` 为主；greedy 只作诊断
    （策略在 245 维上接近确定性时 argmax 会退化成「一直 EndTurn」）。

    ``carrier_audit=1`` 时额外统计「对载体施法数」：与完整游戏
    ``quality_monitor --carrier-audit 1`` 同口径 —— 目标选择（动作 30..45）
    命中的 option eid 属于载体时 +1（每次目标选择多取一次 ``view(0)`` ≈0.45ms）。
    """
    vec = VectorEconomySandbox(cfg, n_envs=min(n_envs, max(1, games)), seed0=seed0,
                               core_ids=core_ids)
    obs = vec.reset()
    cids = set(carrier_ids()) if carrier_audit else set()
    trs = {str(x) for x in (trinket_ids or ())}
    casts = [0] * vec.n_envs
    eps: List[Dict[str, Any]] = []
    while len(eps) < games:
        f, c, m = stack_obs(obs)
        pb = (prior_bias_rows(prior, obs, [int(e.seed) for e in vec.envs])
              if prior is not None else None)
        a, _lp, _v = batch_act(model, f, c, m, device, sample=bool(sample),
                               dtype=dtype, bias=pb)
        if cids:
            for i in range(vec.n_envs):
                try:
                    if not bool(m[i][30:46].any()):
                        continue
                    v = json.loads(vec.envs[i].g.view(0))
                    me = v.get("me") or {}
                    pend = me.get("pending") or {}
                    if str(pend.get("kind")) != "target":
                        continue
                    # 注意：引擎 ``Pending::Target`` 的 JSON 键是 **targets**（eid 列表），
                    # 不是 ``options``（scripts/quality_monitor.py 用的是 options →
                    # 完整游戏的 ``casts_on_carrier`` 恒为 0，是那个脚本的 bug）。
                    opts = list(pend.get("targets") or [])
                    ceids = {int(x.get("eid")) for x in (me.get("board") or [])
                             if str(x.get("id")) in cids}
                    ai = int(a[i])
                    if 30 <= ai < 46 and ceids:
                        j = ai - 30
                        if j < len(opts) and isinstance(opts[j], int) \
                                and int(opts[j]) in ceids:
                            casts[i] += 1
                except Exception:  # noqa: BLE001 - 审计失败不影响评测
                    continue
        obs, _r, dones, infos = vec.step(a)
        for i, d in enumerate(dones):
            if not d:
                continue
            ep = infos[i].get("episode")
            if ep is None:
                continue
            if cids:
                ep = dict(ep)
                ep["casts_on_carrier"] = int(casts[i])
                casts[i] = 0
            if trs:
                # 饰品命中率：本局「曾经拥有过」的饰品里，有多少张属于目标阵容的关键饰品
                ep = dict(ep)
                picked = {str(x) for x in (ep.get("trinket_ids") or ())}
                hits = sorted(picked & trs)
                ep["trinket_hits"] = len(hits)
                ep["trinket_hit"] = bool(hits)
                ep["trinket_hit_ids"] = hits
            eps.append(ep)
    rep = summarize(eps[:games])
    rep["mode"] = "sample" if sample else "greedy"
    rep["gold"] = int(cfg.gold_per_turn)
    rep["free_tier6"] = bool(cfg.free_tier6)
    rep["trinkets"] = (None if cfg.trinkets is None else bool(cfg.trinkets))
    # 终局强度的 L 口径（与训练奖励同一条曲线）
    rep["LT_p50"] = math.log1p(max(0.0, float(rep["sigma_t15_p50"]))) / \
        math.log1p(float(cfg.strength_ref))
    rep["LT_t12_p50"] = math.log1p(max(0.0, float(rep["sigma_t12_p50"]))) / \
        math.log1p(float(cfg.strength_ref))
    return rep


# ── BC 热身（可选）──────────────────────────────────────────────────────────


def _bc_fit(model, f, c, m, a, device, *, epochs: int, lr: float,
            minibatch: int, seed0: int, tag: str = "bc") -> Dict[str, Any]:
    """在固定样本上做 CE 训练（两条 BC 数据来源共用）。"""
    torch = _torch()
    from hsbg.az.train.ppo import masked_log_softmax_torch
    model.to(torch.device(device))
    opt = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=float(lr))
    rng = np.random.default_rng(seed0)
    n = len(a)
    hist = []
    for ep in range(int(epochs)):
        order = rng.permutation(n)
        tot, cnt, hit = 0.0, 0, 0
        for s in range(0, n, int(minibatch)):
            idx = order[s:s + int(minibatch)]
            ft, ct, mt = _to_tensors(f[idx], c[idx], m[idx], device)
            logits, _r2, _v = model(ft, ct, mt)
            logp = masked_log_softmax_torch(logits.float(), mt)
            at = torch.from_numpy(np.ascontiguousarray(a[idx])).to(device)
            loss = -logp.gather(1, at.unsqueeze(1)).squeeze(1).mean()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += float(loss.detach().cpu()) * len(idx)
            cnt += len(idx)
            hit += int((logp.argmax(-1) == at).sum().detach().cpu())
        rec = {"epoch": ep + 1, "ce": tot / max(1, cnt), "top1": hit / max(1, cnt),
               "samples": n}
        hist.append(rec)
        print(f"[{tag}] epoch {ep + 1}/{epochs} ce={rec['ce']:.4f} "
              f"top1={rec['top1']:.3f} n={n}", flush=True)
    return {"history": hist, "samples": n}


def bc_warmstart(model, cfg: SandboxConfig, decisions: int, device: str,
                 *, teacher: str = "teacher", epochs: int = 2, lr: float = 1e-4,
                 minibatch: int = 512, seed0: int = 500000) -> Dict[str, Any]:
    """用**脚本策略**（teacher/carrier_teacher/spell）的轨迹做 CE 热身。"""
    env = EconomySandbox(cfg)
    obs = env.reset(seed0)
    pol = SandboxPolicies(env.g, teacher, seed=seed0)
    feats, cards, masks, acts = [], [], [], []
    while len(acts) < decisions:
        a = pol.act(env.g, obs.mask)
        feats.append(obs.features)
        cards.append(obs.cards)
        masks.append(obs.mask)
        acts.append(int(a))
        obs, _r, done, _info = env.step(a)
        if done:
            obs = env.reset(seed0 + 7 + len(acts))
            pol = SandboxPolicies(env.g, teacher, seed=seed0 + len(acts))
    f = np.asarray(feats, dtype=np.float32)
    c = np.asarray(cards, dtype=np.int32)
    m = np.asarray(masks, dtype=bool)
    a = np.asarray(acts, dtype=np.int64)
    rep = _bc_fit(model, f, c, m, a, device, epochs=epochs, lr=lr,
                  minibatch=minibatch, seed0=seed0)
    rep["teacher"] = teacher
    return rep


def bc_from_checkpoint(model, cfg: SandboxConfig, decisions: int, device: str,
                       ckpt: str, *, epochs: int = 2, lr: float = 1e-4,
                       minibatch: int = 1024, seed0: int = 600000,
                       n_envs: int = 64, dtype: str = "fp32") -> Dict[str, Any]:
    """用**另一个 checkpoint 的策略**在沙盒里采样（T=1）做 CE 热身。

    这是把小模型（``--arch entity --d-model 256 --n-layers 4``）拉到 s14 起点
    （~600）的低成本办法：BC 300k 决策约 1 分钟，之后的 PPO 再只负责"超过 s14"。
    """
    from hsbg.az.train.model import load_checkpoint
    tmodel, _meta = load_checkpoint(ckpt, device=device)
    vec = VectorEconomySandbox(cfg, n_envs=int(n_envs), seed0=int(seed0))
    obs = vec.reset()
    feats: List[np.ndarray] = []
    cards: List[np.ndarray] = []
    masks: List[np.ndarray] = []
    acts: List[int] = []
    while len(acts) < int(decisions):
        f, c, m = stack_obs(obs)
        a, _lp, _v = batch_act(tmodel, f, c, m, device, sample=True, dtype=dtype)
        for i in range(len(obs)):
            feats.append(f[i])
            cards.append(c[i])
            masks.append(m[i])
            acts.append(int(a[i]))
        obs, _r, _d, _infos = vec.step(a)
    del tmodel
    f = np.asarray(feats[:int(decisions)], dtype=np.float32)
    c = np.asarray(cards[:int(decisions)], dtype=np.int32)
    m = np.asarray(masks[:int(decisions)], dtype=bool)
    a = np.asarray(acts[:int(decisions)], dtype=np.int64)
    print(f"[bc] 教师 {ckpt} 采样 {len(a)} 决策（gold={cfg.gold_per_turn}，T=1）",
          flush=True)
    rep = _bc_fit(model, f, c, m, a, device, epochs=epochs, lr=lr,
                  minibatch=minibatch, seed0=seed0)
    rep["teacher"] = f"ckpt:{ckpt}"
    return rep



# ── 主训练 ──────────────────────────────────────────────────────────────────


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="纯经济沙盒 PPO 训练")
    ap.add_argument("--checkpoint", default="runs/az_entity_s14/model.pt")
    ap.add_argument("--from-scratch", action="store_true")
    ap.add_argument("--arch", default="entity", choices=["entity", "tiny"],
                    help="tiny 不可用（无 scalar value 头）；小模型用 "
                         "--arch entity --d-model 256 --n-layers 4")
    ap.add_argument("--d-model", type=int, default=384)
    ap.add_argument("--n-layers", type=int, default=8)
    ap.add_argument("--n-heads", type=int, default=8)
    ap.add_argument("--out", default="runs/economy_sandbox/sb")
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--seed", type=int, default=0)
    # 预算
    ap.add_argument("--decisions", type=int, default=3_000_000,
                    help="沙盒决策预算（包含所有 seat0 决策）")
    ap.add_argument("--minutes", type=float, default=0.0, help="0 = 不限")
    ap.add_argument("--envs", type=int, default=96)
    ap.add_argument("--batch-decisions", type=int, default=16384,
                    help="每次 PPO 更新的更新批次（必须是 minibatch×grad_accum 的整数倍）")
    # 沙盒
    ap.add_argument("--turns", type=int, default=15)
    ap.add_argument("--gold-per-turn", type=int, default=10)
    ap.add_argument("--sandbox-gold-ramp", default="",
                    help='金币课程，例如 "0:99,2M:30,6M:15,10M:10"（按累计决策数切换）')
    ap.add_argument("--sandbox-action-cap-ramp", default="",
                    help='每回合动作上限课程，例如 "0:120,2M:40,4M:20"（按累计决策数切换；'
                         '切换时重建环境）')
    ap.add_argument("--sandbox-free-tier6", dest="sandbox_free_tier6", type=int,
                    default=0, help="1 = 开局 tier6 + 升级免费（ceiling_probe 口径），默认 0")
    ap.add_argument("--gold-mode", default="fixed", choices=["fixed", "add", "growth", "set"],
                    help="收入口径：fixed=每回合重置为 --gold-per-turn（= 旧 set，默认，逐位等价）；"
                         "add=引擎收入 + gold_per_turn + gold_add×(turn−1)；"
                         "growth=引擎收入 + scale×(base×(1+rate)^(turn−1) + per_carrier×载体数)")
    ap.add_argument("--gold-add", type=int, default=0,
                    help="add 模式每回合额外收入的斜率（第 t 回合 +gold_add×(t−1) 金）")
    ap.add_argument("--gold-growth-rate", type=float, default=0.0,
                    help="growth 模式每回合复利率（0.15 = 每回合 ×1.15）")
    ap.add_argument("--gold-per-carrier", type=int, default=0,
                    help="growth 模式每个上回合在场载体额外给的金币")
    ap.add_argument("--sandbox-income-scale", dest="income_scale", type=float, default=1.0,
                    help="注入项整体缩放（上界探针；默认 1.0 逐位等价）")
    ap.add_argument("--gold-cap", type=int, default=99,
                    help="注入后的金币上限（0 = 不封顶）")
    ap.add_argument("--action-cap", type=int, default=40)
    ap.add_argument("--action-cap-per-gold", dest="action_cap_per_gold", type=int,
                    default=0,
                    help="闸门 1（docs/GATE_ACTION_BUFF.md）：每回合有效动作上限 = "
                         "--action-cap + floor(回合开始金币/K)。0 = 关（默认，逐位等价）；"
                         "建议 3 = 每 3 金 +1 动作。只影响 learner 的动作上限。")
    ap.add_argument("--tavern-buff-scale", dest="tavern_buff_scale", type=float,
                    default=1.0,
                    help="闸门 2（docs/GATE_ACTION_BUFF.md）：酒馆永久 buff 的增量整体缩放。"
                         "1.0 = 引擎原样（默认，逐位等价）；>1 = 上界探针"
                         "（Python 侧近似：酒馆随从的 buff 部分按 S 补足）")
    ap.add_argument("--num-players", type=int, default=8)
    ap.add_argument("--sandbox-reward", dest="reward", default="log_strength",
                    choices=["log_strength", "auc_strength", "final_strength",
                             "board_delta", "t12_t15", "exp_growth"])
    ap.add_argument("--sandbox-reward-mix", dest="reward_mix", default="")
    ap.add_argument("--sandbox-trinkets", dest="sandbox_trinkets", type=int, default=-1,
                    help="饰品开关：-1 = 引擎默认（第 6/9 回合 4 选 1，与改动前逐位一致）；"
                         "1 = 显式开启（钉住 6/9 回合 + 4 选项）；0 = 关闭")
    ap.add_argument("--sandbox-hand-slot-mode", dest="hand_slot_mode", default="strict",
                    choices=["strict", "swap"],
                    help="手牌位模式（docs/SANDBOX_ECON.md §3）：strict = 只用引擎 mask"
                         "（默认，逐位等价）；swap = 棋盘 7+手牌 10 满时允许"
                         "「卖最弱非核心 → 打出手牌随从 → 再买」，1 决策仍算 1 动作")
    ap.add_argument("--sandbox-growth-w-final", dest="growth_w_final", type=float, default=1.0,
                    help="exp_growth: 终局强度 L_T 的权重 w1")
    ap.add_argument("--sandbox-growth-w-super", dest="growth_w_super", type=float, default=0.2,
                    help="exp_growth: 超线性（ΔlnΣ − 基线斜率）的权重 w2（value 头是 tanh，"
                         "整局回报要留在 ~[-2,2]：w1=1.0 + w2=0.2 + w3=0.3 是安全上限）")
    ap.add_argument("--sandbox-growth-slope-base", dest="growth_slope_base", type=float,
                    default=0.35, help="exp_growth: 基线对数斜率（低于它不加分）")
    ap.add_argument("--sandbox-growth-from", dest="growth_from", type=int, default=10,
                    help="exp_growth: 从第几回合开始给超线性奖励")
    ap.add_argument("--sandbox-growth-w-ratio", dest="growth_w_ratio", type=float, default=0.0,
                    help="exp_growth: 指数段（t12→t15 ≥3×）的权重 w3")
    ap.add_argument("--comps-json", default="data/scaling/comps_top.json",
                    help="Firestone 阵容数据（scripts/comp_lines_fetch.py 产物）")
    ap.add_argument("--core-from-comps", dest="core_from_comps", type=int, default=0,
                    help="1 = 用 comps_top.json 的核心牌并集做「核心牌命中率」度量"
                         "（默认 0 = 用 compound_cards.json）")
    ap.add_argument("--trinket-target-from-comps", dest="trinket_target_from_comps", type=int,
                    default=1,
                    help="1 = 用 comps_top.json 的关键饰品并集做「饰品命中率」度量（默认 1）")
    ap.add_argument("--strength-ref", type=float, default=30000.0)
    ap.add_argument("--lobby-types", default="")
    # 复利链条核心牌先验（默认关；见 hsbg/az/train/compound_prior.py + docs/COMPOUND_CHAINS.md）
    ap.add_argument("--compound-prior-coef", type=float, default=0.0,
                    help="对「当前流派核心牌」的 Buy/Choose 动作加 +coef logit（只加不减；"
                         "0=关，逐位等价旧路径）")
    ap.add_argument("--archetype-background-penalty", type=float, default=0.0,
                    help="对「其他流派核心牌」（非公用牌）加 -penalty logit（0=关）")
    ap.add_argument("--compound-archetype", default="",
                    help='指定目标流派（如 "DEMON" / "demon_boost_shop"）；空=用分类器判定')
    ap.add_argument("--compound-table", default="",
                    help="复利卡表路径（默认 data/scaling/compound_cards.json）")
    ap.add_argument("--compound-prior-min-prob", type=float, default=0.6,
                    help="分类器判定的置信度门槛（与 archetype_bias 同口径）")
    ap.add_argument("--compound-core-metric", type=int, default=-1,
                    help="1=统计「目标流派核心牌在场数」，0=关，-1=auto"
                         "（有先验或指定了 --compound-archetype 时开）")
    # PPO
    ap.add_argument("--lr", type=float, default=3e-6,
                    help="默认 3e-6（dd3 稳定档；lr≥1.5e-5 在 25 万决策内退化）")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--minibatch", type=int, default=1024)
    ap.add_argument("--grad-accum", type=int, default=8,
                    help="微批累加数（有效 minibatch = minibatch×grad_accum）")
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--target-kl", type=float, default=0.05)
    ap.add_argument("--kl-early-stop", type=int, default=1,
                    help="1 = KL 超阈的 minibatch 不更新（默认）；0 = 只记录")
    ap.add_argument("--gamma", type=float, default=1.0)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--entropy-coef", type=float, default=0.004)
    ap.add_argument("--value-coef", type=float, default=0.5)
    ap.add_argument("--value-head-coef", type=float, default=1.0)
    ap.add_argument("--max-grad-norm", type=float, default=1.0)
    ap.add_argument("--dtype", default="fp32", choices=["fp32", "bf16"],
                    help="采集与训练统一 dtype（默认 fp32；bf16 两边都开 autocast）")
    # BC 热身
    ap.add_argument("--bc-decisions", type=int, default=0)
    ap.add_argument("--bc-epochs", type=int, default=2)
    ap.add_argument("--bc-lr", type=float, default=1e-4)
    ap.add_argument("--bc-teacher", default="teacher",
                    choices=["teacher", "carrier_teacher", "spell", "greedy"])
    ap.add_argument("--bc-teacher-from", default="",
                    help="用另一个 checkpoint（如 runs/az_entity_s14/model.pt）在沙盒里采样做 BC，"
                         "把小模型拉到 s14 起点；非空时覆盖 --bc-teacher")
    # 评测
    ap.add_argument("--eval-every", type=int, default=1_000_000,
                    help="每多少沙盒决策评测一次（0 = 只评首尾）")
    ap.add_argument("--eval-games", type=int, default=32)
    ap.add_argument("--eval-seed-base", type=int, default=900000)
    ap.add_argument("--save-every", type=int, default=1_000_000)
    args = ap.parse_args(argv)

    torch = _torch()
    torch.manual_seed(int(args.seed))
    np.random.seed(int(args.seed))
    os.makedirs(args.out, exist_ok=True)
    hist_path = os.path.join(args.out, "history.jsonl")
    hist_f = open(hist_path, "w", encoding="utf-8")

    def log_rec(rec: Dict[str, Any]) -> None:
        rec = dict(rec)
        rec["t"] = time.time()
        hist_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        hist_f.flush()

    ramp = parse_gold_ramp(args.sandbox_gold_ramp)
    gold0 = gold_at(ramp, 0, int(args.gold_per_turn))
    cap_ramp = parse_cap_ramp(args.sandbox_action_cap_ramp)
    cap0 = gold_at(cap_ramp, 0, int(args.action_cap))

    cfg = SandboxConfig(
        turns=int(args.turns), gold_per_turn=int(args.gold_per_turn),
        gold_mode=str(args.gold_mode), action_cap=int(cap0),
        action_cap_per_gold=int(args.action_cap_per_gold),
        tavern_buff_scale=float(args.tavern_buff_scale),
        gold_add=int(args.gold_add),
        gold_growth_rate=float(args.gold_growth_rate),
        gold_per_carrier=int(args.gold_per_carrier),
        income_scale=float(args.income_scale),
        gold_cap=int(args.gold_cap),
        num_players=int(args.num_players), reward=str(args.reward),
        reward_mix=str(args.reward_mix), strength_ref=float(args.strength_ref),
        lobby_types=tuple(x.strip().upper() for x in args.lobby_types.split(",") if x.strip()),
        free_tier6=bool(int(args.sandbox_free_tier6)),
        trinkets=(None if int(args.sandbox_trinkets) < 0
                  else bool(int(args.sandbox_trinkets))),
        hand_slot_mode=str(args.hand_slot_mode),
        growth_w_final=float(args.growth_w_final),
        growth_w_super=float(args.growth_w_super),
        growth_slope_base=float(args.growth_slope_base),
        growth_from=int(args.growth_from),
        growth_w_ratio=float(args.growth_w_ratio),
        seed=int(args.seed))
    cfg.validate()
    print(f"[sandbox] cfg={json.dumps(cfg.engine_config(), ensure_ascii=False)}", flush=True)

    print(f"[sandbox] gold ramp={ramp or '(无，固定 %d)' % int(args.gold_per_turn)} "
          f"start_gold={gold0} action-cap ramp={cap_ramp or '(无，固定 %d)' % int(args.action_cap)} "
          f"start_cap={cap0} free_tier6={bool(int(args.sandbox_free_tier6))} "
          f"gate1(K)={int(args.action_cap_per_gold)} "
          f"gate2(S)={float(args.tavern_buff_scale)} "
          f"dtype={args.dtype}", flush=True)

    if args.from_scratch:
        args.checkpoint = ""
    model, meta = build_model(args)

    # ── 复利核心牌先验（默认关：两个系数都为 0 时**不构造**对象）──────────
    prior = None
    core_ids: Optional[List[str]] = None
    prior_summary: Dict[str, Any] = {}
    _coef = float(args.compound_prior_coef)
    _pen = float(args.archetype_background_penalty)
    if _coef > 0.0 or _pen > 0.0:
        from hsbg.az.train.compound_prior import (  # noqa: PLC0415
            DEFAULT_COMPOUND, CompoundPrior, engine_card_id_lookup)
        prior = CompoundPrior(
            coef=_coef, background_penalty=_pen,
            compound_path=(str(args.compound_table) or DEFAULT_COMPOUND),
            archetype=str(args.compound_archetype or ""),
            min_prob=float(args.compound_prior_min_prob),
            card_index_of=engine_card_id_lookup())
        prior_summary = prior.summary()
        print(f"[compound] 先验开：coef={_coef} penalty={_pen} "
              f"target={args.compound_archetype or '(分类器判定)'} "
              f"detector={prior_summary['detector']} "
              f"tribes={prior_summary['n_tribes']} archetypes={prior_summary['n_archetypes']} "
              f"common={prior_summary['n_common']} ids={prior_summary['n_all_ids']}",
              flush=True)
        log_rec({"event": "compound_prior", **prior_summary})
    # 核心牌在场度量：目标流派核心集（指定了流派用它，否则用全流派核心集）
    if int(args.compound_core_metric) != 0 and (
            int(args.compound_core_metric) > 0 or prior is not None
            or bool(args.compound_archetype)):
        from hsbg.az.train.compound_prior import (  # noqa: PLC0415
            DEFAULT_COMPOUND, all_core_ids, core_ids_for)
        _tbl = str(args.compound_table) or DEFAULT_COMPOUND
        if str(args.compound_archetype):
            core_ids = core_ids_for(str(args.compound_archetype), path=_tbl)
        else:
            core_ids = all_core_ids(path=_tbl)
        print(f"[compound] 核心牌度量开：{len(core_ids)} 张 "
              f"(target={args.compound_archetype or 'ALL'})", flush=True)

    # ── Firestone 阵容（scripts/comp_lines_fetch.py）→ 核心牌 / 关键饰品命中率 ──
    comps_summary: Dict[str, Any] = {}
    trinket_ids: Optional[List[str]] = None
    if bool(int(args.core_from_comps)) or bool(int(args.trinket_target_from_comps)):
        _cpath = str(args.comps_json)
        if not os.path.isabs(_cpath):
            _cpath = os.path.join(ROOT, _cpath)
        if os.path.exists(_cpath):
            with open(_cpath, encoding="utf-8") as _f:
                _comps = json.load(_f)
            _cs = _comps.get("comps") or []
            if bool(int(args.core_from_comps)):
                core_ids = sorted({str(c["id"]) for x in _cs
                                   for c in (x.get("core_cards") or ())
                                   if str(c.get("id"))})
            trinket_ids = sorted({str(t["id"]) for x in _cs
                                  for t in (x.get("trinkets") or ())
                                  if str(t.get("id"))})
            comps_summary = {
                "path": os.path.relpath(_cpath, ROOT),
                "n_comps": len(_cs),
                "core_ids": len(core_ids or ()),
                "trinket_ids": len(trinket_ids or ()),
                "top": [x.get("name") for x in _cs[:10]],
            }
            print(f"[comps] {len(_cs)} 套阵容；核心牌 {len(core_ids or ())} 张"
                  f"（core_from_comps={bool(int(args.core_from_comps))}）；"
                  f"关键饰品 {len(trinket_ids)} 张", flush=True)
            log_rec({"event": "comps", **comps_summary})
        else:
            print(f"[comps][warn] 找不到 {_cpath}，跳过命中率度量", flush=True)
    if cfg.trinkets is None and int(args.sandbox_trinkets) < 0:
        trinket_ids = None      # 没开饰品计量就别算命中率

    # ── 配方断言（启动即失败，不要训练到一半才发现）─────────────────────
    mb = max(1, int(args.minibatch))
    accum = max(1, int(args.grad_accum))
    eff = mb * accum
    bd = int(args.batch_decisions)
    if bd % eff != 0:
        raise SystemExit(
            f"[sandbox][断言失败] --batch-decisions={bd} 不是 "
            f"minibatch×grad_accum={mb}×{accum}={eff} 的整数倍。\n"
            f"  否则每个 update 会剩一个「残余组」（在一次 Adam step 之后才评估）→ "
            f"KL 必超阈值 → 早停 → 整次更新被丢弃。\n"
            f"  建议 --batch-decisions {int(math.ceil(bd / eff) * eff)}。")
    if str(args.dtype) != str(args.dtype).lower():
        raise SystemExit("[sandbox][断言失败] --dtype 必须是小写 fp32/bf16")
    print(f"[sandbox] eff minibatch = {mb}×{accum} = {eff}；"
          f"batch_decisions={bd} = {bd // eff} 组/epoch；"
          f"updates 上限≈{max(1, int(math.ceil(args.decisions / eff)))}", flush=True)

    bc_rep = None
    if int(args.bc_decisions) > 0:
        t0 = time.perf_counter()
        if str(args.bc_teacher_from):
            bc_rep = bc_from_checkpoint(
                model, cfg.replaced(gold_per_turn=int(gold0)),
                int(args.bc_decisions), args.device, str(args.bc_teacher_from),
                epochs=int(args.bc_epochs), lr=float(args.bc_lr),
                minibatch=int(args.minibatch), seed0=int(args.eval_seed_base) + 1000,
                dtype=str(args.dtype))
        else:
            bc_rep = bc_warmstart(model, cfg.replaced(gold_per_turn=int(gold0)),
                                  int(args.bc_decisions), args.device,
                                  teacher=str(args.bc_teacher),
                                  epochs=int(args.bc_epochs), lr=float(args.bc_lr),
                                  seed0=int(args.eval_seed_base) + 1000)
        bc_rep["seconds"] = time.perf_counter() - t0
        log_rec({"event": "bc", **bc_rep})
        _save(model, args.out, "bc", meta, cfg, args, extra={"bc": bc_rep})

    # ── PPO ────────────────────────────────────────────────────────────────
    from hsbg.az.train.ppo import PPOConfig
    from hsbg.az.train.ppo_trainer import PPOTrainer

    n_updates = max(1, int(math.ceil(float(args.decisions) / float(eff))))
    pcfg = PPOConfig(
        epochs=int(args.epochs), minibatch=int(args.minibatch), lr=float(args.lr),
        clip=float(args.clip), gamma=float(args.gamma), lam=float(args.lam),
        entropy_coef=float(args.entropy_coef), value_coef=float(args.value_coef),
        value_head_coef=float(args.value_head_coef), value_loss="mse",
        pi_coef=0.0, seq_coef=0.0, bc_coef=0.0, dpo_coef=0.0,
        anchor_coef=0.0, grad_accum=int(accum),
        target_kl=float(args.target_kl), max_grad_norm=float(args.max_grad_norm),
        kl_early_stop=bool(int(args.kl_early_stop)),
        amp=str(args.dtype), device=str(args.device), seed=int(args.seed),
        normalize_advantage=True, compile_train=0, log_every=0)
    trainer = PPOTrainer(model, pcfg, lr_min_ratio=0.3, max_updates=n_updates)
    model.to(torch.device(args.device))

    # 采样环境（金币课程：初始档位）
    vec = VectorEconomySandbox(cfg.replaced(gold_per_turn=gold0),
                               n_envs=int(args.envs), seed0=int(args.seed) * 1000,
                               core_ids=core_ids)
    obs = vec.reset()

    # ── 启动 dtype/logprob 自检（真实观测，不进入训练前就失败）──────────
    check_logprob_consistency(model, obs, args.device, dtype=str(args.dtype))

    buf: List[List[Dict[str, Any]]] = [[] for _ in range(int(args.envs))]
    ready: List[Dict[str, Any]] = []      # 已完成轨迹的逐决策记录（跨 update 结转）
    ep_LTs: List[float] = []
    ep_lens: List[int] = []
    episodes = 0
    decisions = 0
    next_eval = int(args.eval_every) if int(args.eval_every) > 0 else None
    next_save = int(args.save_every)
    t_start = time.perf_counter()
    last_eval: Dict[str, Any] = {}
    best: Dict[str, Any] = {"t12": -1.0, "decisions": 0}

    def run_eval(tag: str, *, final: bool = False) -> Dict[str, Any]:
        games = int(args.eval_games) * (2 if final else 1)
        both = {}
        gnow = gold_at(ramp, decisions, int(args.gold_per_turn)) if ramp \
            else int(args.gold_per_turn)
        cnow = gold_at(cap_ramp, decisions, int(cap0)) if cap_ramp else int(cap0)
        ev_cfg = cfg.replaced(gold_per_turn=int(gnow), action_cap=int(cnow))
        for mode in ("greedy", "sample"):
            ev = evaluate(model, ev_cfg, games, args.device,
                          seed0=int(args.eval_seed_base), sample=(mode == "sample"),
                          dtype=str(args.dtype), prior=prior, core_ids=core_ids,
                          trinket_ids=trinket_ids)
            both[mode] = ev
            log_rec({"event": "eval", "mode": mode, "decisions": decisions,
                     "update": trainer.updates, "final": bool(final),
                     "gold": int(gnow), "action_cap": int(cnow), "tag": tag, **ev})
        g = both["greedy"]
        s = both["sample"]
        print(f"[eval] {tag} (gold={gnow} cap={cnow}) sample: t12 p50={s['sigma_t12_p50']:.0f} "
              f"p90={s['sigma_t12_p90']:.0f} t15 p50={s['sigma_t15_p50']:.0f} "
              f"tier={s['tier_p50']:.0f} carrier={s['carrier_rate']:.2f} "
              f"spells={s['spells_p50']:.0f} tav={s['tavern_buff_p50']:.0f}"
              + (f" core={s['core_t15_p50']:.0f}" if "core_t15_p50" in s else "")
              + (f" trk={s.get('trinkets_p50', 0):.0f}/{s.get('trinket_hit_rate', 0):.2f}"
                 if "trinket_hit_rate" in s else "")
              + f" | growth: slope_late={s.get('growth_slope_late_p50', 0):.3f} "
              f"curv={s.get('growth_curv_p50', 0):+.4f} "
              f"r12_15={s.get('growth_ratio_12_15_p50', 0):.2f} "
              f"exp_rate={s.get('exp_segment_rate', 0):.2f}"
              + f" goldens={s.get('goldens_p50', 0):.0f}"
              + (f" g1: act={s.get('actions_total_p50', 0):.0f}"
                 f"/cap{s.get('action_cap_eff_mean', 0):.0f}"
                 f"/bound{s.get('turns_cap_bound_mean', 0):.0f}"
                 if "actions_total_p50" in s else "")
              + (f" g2: tavS={s.get('tavern_buff_scaled_p50', 0):.0f}"
                 f"/ex{s.get('tavern_extra_p50', 0):.0f}"
                 if "tavern_extra_p50" in s else "")
              + f" | "
              f"greedy: t12={g['sigma_t12_p50']:.0f} t15={g['sigma_t15_p50']:.0f} "
              f"tier={g['tier_p50']:.0f} carrier={g['carrier_rate']:.2f} "
              f"spells={g['spells_p50']:.0f}"
              + (f" core={g['core_t15_p50']:.0f}" if "core_t15_p50" in g else "")
              + (f" trk_hit={g.get('trinket_hit_rate', 0):.2f}"
                 if "trinket_hit_rate" in g else ""),
              flush=True)
        both["primary"] = s
        if s["sigma_t12_p50"] > best["t12"]:
            best.update({"t12": float(s["sigma_t12_p50"]),
                         "t15": float(s["sigma_t15_p50"]),
                         "decisions": int(decisions), "tag": tag,
                         "gold": int(gnow), "action_cap": int(cnow)})
        return both

    if next_eval is not None:
        last_eval = run_eval("0")

    while decisions < int(args.decisions):
        if args.minutes and (time.perf_counter() - t_start) / 60.0 >= args.minutes:
            print("[sandbox] 到时间上限，停止", flush=True)
            break
        # 金币课程：跨过阈值就给所有环境换档（新 reset 的局立刻生效）
        gnow = gold_at(ramp, decisions, int(args.gold_per_turn)) if ramp \
            else int(args.gold_per_turn)
        cnow = gold_at(cap_ramp, decisions, int(cap0)) if cap_ramp else int(cap0)
        if int(gnow) != int(vec.gold_per_turn):
            vec.set_gold_per_turn(int(gnow))
            print(f"[sandbox] gold ramp -> {gnow}/回合 @ {decisions / 1e3:.0f}k 决策",
                  flush=True)
            log_rec({"event": "gold_ramp", "decisions": int(decisions),
                     "gold": int(gnow)})
        # 每回合动作上限课程：切档要重建环境（RulesConfig 的 turn_action_caps 固定）
        if int(cnow) != int(vec.cfg.action_cap):
            vec = VectorEconomySandbox(
                cfg.replaced(gold_per_turn=int(gnow), action_cap=int(cnow)),
                n_envs=int(args.envs), seed0=int(args.seed) * 1000 + int(decisions),
                core_ids=core_ids)
            obs = vec.reset()
            buf = [[] for _ in range(int(args.envs))]
            print(f"[sandbox] action-cap ramp -> {cnow}/回合 @ {decisions / 1e3:.0f}k 决策"
                  "（环境重建）", flush=True)
            log_rec({"event": "action_cap_ramp", "decisions": int(decisions),
                     "action_cap": int(cnow)})
        f, c, m = stack_obs(obs)
        turn_now = [o.turn for o in obs]
        pb = (prior_bias_rows(prior, obs, [int(e.seed) for e in vec.envs])
              if prior is not None else None)
        a, lp, v = batch_act(model, f, c, m, args.device, sample=True,
                             dtype=str(args.dtype), bias=pb)
        if prior is not None:
            # 偏置器的历史特征要看到「己方实际动作」（与正式采集同口径）
            for i in range(int(args.envs)):
                prior.note_action(int(a[i]), game_id=int(vec.envs[i].seed), seat=0)
        nobs, rewards, dones, infos = vec.step(a)
        for i in range(int(args.envs)):
            buf[i].append({"features": f[i], "cards": c[i], "mask": m[i],
                           "action": int(a[i]), "logprob": float(lp[i]),
                           "value": float(v[i]), "reward": float(rewards[i]),
                           "turn": int(turn_now[i])})
            if dones[i]:
                steps, LT, ln = episode_ready_steps(
                    buf[i], gamma=float(args.gamma), lam=float(args.lam),
                    ep_index=episodes)
                episodes += 1
                ready.extend(steps)
                ep_LTs.append(LT)
                ep_lens.append(ln)
                buf[i] = []
        obs = nobs
        decisions += int(args.envs)

        if len(ready) >= bd:
            take = (len(ready) // eff) * eff
            chunk, ready = ready[:take], ready[take:]
            rec_LT = np.asarray(ep_LTs, dtype=np.float64) if ep_LTs else np.zeros(1)
            rec_len = np.asarray(ep_lens, dtype=np.float64) if ep_lens else np.ones(1)
            batch = build_ppo_batch(chunk)
            try:
                stats = trainer.update(batch)
            except Exception as exc:  # noqa: BLE001 - 不让一个坏批次杀死整轮
                print(f"[sandbox][warn] update 失败: {type(exc).__name__}: {exc}",
                      flush=True)
                log_rec({"event": "update_failed", "decisions": decisions,
                         "error": f"{type(exc).__name__}: {exc}"})
                continue
            el = time.perf_counter() - t_start
            ep_returns = None
            e0 = stats.get("epochs", [{}])
            last = e0[-1] if e0 else {}
            rec = {"event": "update", "decisions": decisions,
                   "updates": trainer.updates, "samples": len(batch),
                   "batch_take": int(take), "carry": int(len(ready)),
                   "gold": int(gnow),
                   "policy_loss": last.get("policy_loss"),
                   "value_loss": last.get("value_loss"),
                   "entropy": last.get("entropy"),
                   "approx_kl": last.get("approx_kl"),
                   "clip_frac": last.get("clip_frac"),
                   "adv_mean": float(np.mean(batch.advantages)),
                   "ret_mean": float(np.mean(batch.returns)),
                   # 进度看每局 L_T（终局强度），不看逐决策均值
                   "ep_LT_mean": float(np.mean(rec_LT)),
                   "ep_LT_p50": float(np.median(rec_LT)),
                   "ep_LT_p90": float(np.percentile(rec_LT, 90)),
                   "ep_LT_max": float(np.max(rec_LT)),
                   "ep_LT_last10": float(np.mean(rec_LT[-10:])),
                   "ep_len_mean": float(np.mean(rec_len)),
                   "episodes": int(episodes),
                   "decisions_per_s": float(decisions / max(el, 1e-9)),
                   "secs": el}
            log_rec(rec)
            ep_LTs, ep_lens = [], []
            if trainer.updates % 5 == 0:
                eta = (int(args.decisions) - decisions) / max(
                    1e-9, decisions / max(el, 1e-9)) / 60.0
                print(f"[ppo] d={decisions / 1e3:.0f}k upd={trainer.updates} "
                      f"pi={rec['policy_loss']:.4f} v={rec['value_loss']:.4f} "
                      f"ent={rec['entropy']:.3f} kl={rec['approx_kl']:.4f} "
                      f"LT={rec['ep_LT_mean']:.3f} epL={rec['ep_len_mean']:.0f} "
                      f"dec/s={rec['decisions_per_s']:.0f} eta={eta:.0f}min",
                      flush=True)

        if next_eval is not None and decisions >= next_eval:
            last_eval = run_eval(f"{decisions / 1e3:.0f}k")
            while next_eval is not None and decisions >= next_eval:
                next_eval += int(args.eval_every)
        if decisions >= next_save:
            _save(model, args.out, f"step_{decisions}", meta, cfg, args,
                  extra={"decisions": decisions, "updates": trainer.updates,
                         "best": best})
            torch.save(trainer.state_dict(), os.path.join(args.out, "trainer.pt"))
            next_save += int(args.save_every)

    # 收尾评测 + 存权重
    ev = run_eval("final", final=True)
    _save(model, args.out, "final", meta, cfg, args,
          extra={"decisions": decisions, "updates": trainer.updates,
                 "best": best})
    torch.save(trainer.state_dict(), os.path.join(args.out, "trainer.pt"))
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"decisions": decisions, "updates": trainer.updates,
                   "seconds": time.perf_counter() - t_start,
                   "decisions_per_s": decisions / max(1e-9,
                                                      time.perf_counter() - t_start),
                   "episodes": episodes, "best": best, "eval": ev, "bc": bc_rep,
                   "gold_ramp": ramp, "action_cap_ramp": cap_ramp,
                   "compound_prior": (prior.to_meta() if prior is not None else {}),
                   "compound_summary": prior_summary,
                   "compound_core_ids": (core_ids or []),
                   "config": _cfg_dict(cfg), "args": vars(args)},
                  fh, ensure_ascii=False, indent=1)
    hist_f.close()
    return 0


def _cfg_dict(cfg: SandboxConfig) -> Dict[str, Any]:
    return {k: (list(v) if isinstance(v, tuple) else v)
            for k, v in cfg.__dict__.items()}


def _save(model, out: str, tag: str, meta: Dict[str, Any], cfg: SandboxConfig,
          args, *, extra: Optional[Dict[str, Any]] = None) -> None:
    from hsbg.az.train.model import save_checkpoint
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"model_{tag}.pt")
    m = dict(meta or {})
    m.update({"sandbox": True, "sandbox_config": _cfg_dict(cfg),
              "sandbox_gold_ramp": str(getattr(args, "sandbox_gold_ramp", "")),
              "dtype": str(getattr(args, "dtype", "fp32")),
              "trained_by": "scripts/train_economy_sandbox.py"})
    if extra:
        m.update({k: v for k, v in extra.items() if k != "eval"})
    save_checkpoint(model, path, meta=m)
    # 固定名字的最新权重（迁移验证就是加载它）
    save_checkpoint(model, os.path.join(out, "model.pt"), meta=m)


if __name__ == "__main__":
    raise SystemExit(main())
