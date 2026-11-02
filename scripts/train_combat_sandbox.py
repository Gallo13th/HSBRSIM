"""轻量战斗沙盒的 PPO 训练入口（task-14）

与 ``scripts/train_compound_ppo.py`` 同一套算法（value-warmup 只训 head、KL anchor 到冻结
参考策略、GAE、无熵奖励、梯度累积、退化早停），只把**环境**换成 ``CombatSandbox``
（每回合 1 场引擎原生战斗）并沿用已证明有效的经济/奖励项：
``gold_profile``（对齐完整对局收入）+ ``tier_reward_coef``（推 t5/t6 摸放大器）。

用法::

    PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
    export PYTHONPATH=rust/python:.
    $PY scripts/train_combat_sandbox.py --checkpoint runs/compound_bc/ckpt_w8e4.pt \
        --out runs/combat_sandbox/cs1 --decisions 300000 --device cuda:7 \
        --gold-profile 3,4,5,6,7,8,9,10,10,10,10,10,11 --tier-reward-coef 0.1 \
        --opponent-quantile p75 --eval-games 24
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
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


def build_cfg(args):
    from hsbg.az.train.combat_sandbox import CombatConfig  # noqa: PLC0415
    return CombatConfig(
        turns=int(args.turns), gold_mode=str(args.gold_mode),
        gold_per_turn=int(args.gold_per_turn), gold_cap=int(args.gold_cap),
        action_cap=int(args.action_cap), num_players=2,
        reward="log_strength", reward_mix="", strength_ref=float(args.strength_ref),
        trinkets=(None if int(args.trinkets) < 0 else bool(args.trinkets)),
        lobby_types=tuple(),
        gold_profile=str(args.gold_profile or ""),
        tier_reward_coef=float(args.tier_reward_coef),
        opponent_boards=str(args.opponent_boards),
        opponent_quantile=str(args.opponent_quantile),
        hp_start=int(args.hp_start),
        combat_reward_coef=float(args.combat_reward_coef),
        dmg_norm=float(args.dmg_norm),
        opponent_fidelity=str(args.opponent_fidelity),
    )


def _autocast(dtype: str):
    torch = _torch()
    if str(dtype) == "bf16" and torch.cuda.is_available():
        return torch.autocast("cuda", dtype=torch.bfloat16)
    return contextlib.nullcontext()


def _tens(x, device, kind: str = "f32"):
    torch = _torch()
    dtype = {"f32": np.float32, "i64": np.int64, "bool": np.bool_}[kind]
    return torch.from_numpy(np.ascontiguousarray(x, dtype=dtype)).to(device)


def policy_forward(model, f, c, m, *, dtype="fp32", chunk=8192):
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


def sample_actions(logits, masks, *, seed_rng):
    z = np.where(masks, logits.astype(np.float64), -np.inf)
    mx = np.max(z, axis=1, keepdims=True)
    e = np.exp(z - mx)
    p = e / e.sum(axis=1, keepdims=True)
    n = p.shape[0]
    u = seed_rng.random(n)[:, None]
    a = np.minimum((np.cumsum(p, axis=1) < u).sum(axis=1), p.shape[1] - 1).astype(np.int64)
    ok = p[np.arange(n), a] > 0
    a[~ok] = np.argmax(p[~ok], axis=1)
    logp = np.log(np.maximum(p[np.arange(n), a], 1e-30))
    return a, logp.astype(np.float32)


def compute_gae(rewards, values, dones, last_values, *, gamma, lam):
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


def evaluate(model, cfg, games: int, device: str, *, seed0: int = 950000,
             sample: bool = False) -> Dict[str, Any]:
    """轻量战斗沙盒评测：Σ / tier / 存活回合 / 胜率 / 伤害。"""
    from hsbg.az.train.combat_sandbox import CombatSandbox, summarize_combat  # noqa: PLC0415
    torch = _torch()
    torch.manual_seed(int(seed0) + 17)
    rng = np.random.default_rng(int(seed0) + 3)
    eps: List[Dict[str, Any]] = []
    for g in range(int(games)):
        env = CombatSandbox(cfg.replaced(seed=int(seed0) + g))
        obs = env.reset()
        while not env.done:
            f = obs.features[None, :]
            c = obs.cards[None, :]
            m = obs.mask[None, :]
            logits, _v = policy_forward(model, _tens(f, device, "f32"),
                                        _tens(c, device, "i64"),
                                        _tens(m, device, "bool"))
            if sample:
                a, _lp = sample_actions(logits, m, seed_rng=rng)
                act = int(a[0])
            else:
                act = int(np.argmax(np.where(m[0], logits[0], -np.inf)))
            obs, _r, _d, _i = env.step(act)
        eps.append(env.episode_summary())
    rep = summarize_combat(eps)
    rep["mode"] = "sample" if sample else "greedy"
    rep["opponent_quantile"] = str(cfg.opponent_quantile)
    return rep


def train(args) -> Dict[str, Any]:
    torch = _torch()
    from hsbg.az.train.combat_sandbox import VectorCombatSandbox  # noqa: PLC0415
    from hsbg.az.train.economy_sandbox import stack_obs  # noqa: PLC0415
    from hsbg.az.train.model import load_checkpoint, save_checkpoint  # noqa: PLC0415
    from hsbg.az.train.ppo import forward_model, masked_log_softmax_torch  # noqa: PLC0415

    device = str(args.device)
    dtype = str(args.dtype)
    torch.manual_seed(int(args.seed))
    rng_pol = np.random.default_rng(int(args.seed) + 1)
    cfg = build_cfg(args)
    mb, ga, bd = int(args.minibatch), int(args.grad_accum), int(args.batch_decisions)
    if bd % (mb * ga) != 0:
        raise SystemExit(f"--batch-decisions 必须是 {mb}×{ga} 的整数倍")
    n_envs = int(args.envs)
    steps = max(1, bd // n_envs)

    model, meta = load_checkpoint(str(args.checkpoint), device=device)
    model.to(device)
    model.eval()
    ref = copy.deepcopy(model).to(device).eval()
    for p in ref.parameters():
        p.requires_grad_(False)
    n_param = int(sum(p.numel() for p in model.parameters()))
    print(f"[cppo] 起点 {args.checkpoint}（{n_param / 1e6:.2f}M）；envs={n_envs} "
          f"steps={steps} batch={bd} mb={mb} ga={ga}；敌方 {cfg.opponent_quantile}；"
          f"gold_profile={cfg.gold_profile or '(gold_mode)'} tier_coef="
          f"{cfg.tier_reward_coef}", flush=True)
    opt = torch.optim.Adam([p for p in model.parameters() if p.requires_grad],
                           lr=float(args.lr))
    vec = VectorCombatSandbox(cfg, n_envs=n_envs, seed0=int(args.seed0))
    obs = vec.reset()
    os.makedirs(str(args.out), exist_ok=True)
    hist_f = open(os.path.join(str(args.out), "history.jsonl"), "w", encoding="utf-8")
    decisions = updates = 0
    warmed = False
    dead = 0
    ep_lines: List[Dict[str, Any]] = []
    t0 = time.time()
    stopped_early = False
    rows_hist: List[Dict[str, Any]] = []
    try:
        while decisions < int(args.decisions):
            model.eval()
            F, C, M, A, LP, V, R, D = [], [], [], [], [], [], [], []
            for _ in range(steps):
                f, c, m = stack_obs(obs)
                logits, value = policy_forward(model, _tens(f, device, "f32"),
                                               _tens(c, device, "i64"),
                                               _tens(m, device, "bool"), dtype=dtype)
                a, logp = sample_actions(logits, m, seed_rng=rng_pol)
                obs, rew, dones, infos = vec.step([int(x) for x in a])
                d = np.asarray(dones, dtype=bool)
                for i, done in enumerate(d):
                    if done:
                        ep = infos[i].get("episode") or {}
                        if ep:
                            dead += int(bool(ep.get("killed")))
                            ep_lines.append({k: ep.get(k) for k in
                                             ("sigma_t15", "win_rate", "wins",
                                              "losses", "damage_taken", "hp_end",
                                              "killed", "tier_t15", "turns")})
                F.append(f); C.append(c); M.append(m); A.append(a)
                LP.append(logp); V.append(value)
                R.append(np.asarray(rew, dtype=np.float32)); D.append(d)
                decisions += n_envs
            fA = np.concatenate(F).astype(np.float32)
            cA = np.concatenate(C).astype(np.int64)
            mA = np.concatenate(M).astype(bool)
            aA = np.concatenate(A).astype(np.int64)
            lpA = np.concatenate(LP).astype(np.float32)
            vA = np.concatenate(V).astype(np.float32)
            rA = np.concatenate(R).astype(np.float32)
            dA = np.concatenate(D).astype(bool)
            T = len(F)
            f2, c2, m2 = stack_obs(obs)
            _, last_v = policy_forward(model, _tens(f2, device, "f32"),
                                       _tens(c2, device, "i64"),
                                       _tens(m2, device, "bool"), dtype=dtype)
            adv2, ret2 = compute_gae(rA.reshape(T, n_envs), vA.reshape(T, n_envs),
                                     dA.reshape(T, n_envs), last_v,
                                     gamma=float(args.gamma), lam=float(args.lam))
            advA = adv2.reshape(-1).astype(np.float32)
            retA = ret2.reshape(-1).astype(np.float32)
            advA = (advA - advA.mean()) / (advA.std() + 1e-8)
            n = (len(aA) // mb) * mb
            if n <= 0:
                break
            if int(args.value_warmup) > 0 and not warmed:
                vh = [p for nm, p in model.named_parameters()
                      if nm.startswith("value_head")]
                opt_v = torch.optim.Adam(vh, lr=float(args.value_lr))
                for _w in range(int(args.value_warmup)):
                    order = rng_pol.permutation(n)
                    for j in range(n // mb):
                        sel = order[j * mb:(j + 1) * mb]
                        with _autocast(dtype):
                            _lg, _rk, value = forward_model(
                                model, _tens(fA[sel], device, "f32"),
                                _tens(cA[sel], device, "i64"),
                                _tens(mA[sel], device, "bool"))
                        vloss = torch.nn.functional.mse_loss(
                            value.float().reshape(-1), _tens(retA[sel], device, "f32"))
                        opt_v.zero_grad(set_to_none=True)
                        vloss.backward()
                        for nm, p in model.named_parameters():
                            if not nm.startswith("value_head") and p.grad is not None:
                                p.grad = None
                        opt_v.step()
                model.zero_grad(set_to_none=True)
                warmed = True
                with torch.no_grad():
                    _lg, _rk, v_now = forward_model(
                        model, _tens(fA, device, "f32"), _tens(cA, device, "i64"),
                        _tens(mA, device, "bool"))
                    verr = float((v_now.float().reshape(-1)
                                  - _tens(retA, device, "f32")).abs().mean())
                print(f"[cppo] value 预热 {args.value_warmup} 遍：|V-return|={verr:.4f}",
                      flush=True)
            idx = np.arange(n)
            rng_pol.shuffle(idx)
            opt.zero_grad(set_to_none=True)
            n_mb = n // mb
            sum_kl = sum_ent = sum_pg = sum_v = sum_anch = 0.0
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
                    logits, _rk, value = forward_model(model, fT, cT, mT)
                logits = logits.float()
                logp_all = masked_log_softmax_torch(logits, mT)
                logp = logp_all.gather(1, aT.unsqueeze(1)).squeeze(1)
                ratio = torch.exp(logp - oldT)
                pg = -torch.min(ratio * advT,
                                torch.clamp(ratio, 1.0 - float(args.clip),
                                            1.0 + float(args.clip)) * advT).mean()
                vloss = torch.nn.functional.mse_loss(value.float().reshape(-1), retT)
                with torch.no_grad(), _autocast(dtype):
                    rl, _r2, _v2 = forward_model(ref, fT, cT, mT)
                rlogp = masked_log_softmax_torch(rl.float(), mT)
                p = logp_all.exp()
                kl_anch = (p.detach() * (logp_all - rlogp)).sum(-1).mean()
                ent = -(p.detach() * logp_all).sum(-1).mean()
                beta = float(args.anchor_beta)
                loss = (pg + float(args.value_coef) * vloss - float(args.entropy_coef)
                        * ent + beta * kl_anch)
                (loss / ga).backward()
                if (j + 1) % ga == 0 or (j + 1) == n_mb:
                    torch.nn.utils.clip_grad_norm_(model.parameters(),
                                                   float(args.max_grad_norm))
                    opt.step()
                    opt.zero_grad(set_to_none=True)
                with torch.no_grad():
                    akl = float((oldT - logp).mean())
                updates += 1
                sum_kl += akl
                sum_ent += float(ent)
                sum_pg += float(pg)
                sum_v += float(vloss)
                sum_anch += float(kl_anch)
            rec = ep_lines[-40:]
            row = {"decisions": int(decisions), "updates": int(updates),
                   "approx_kl": sum_kl / max(1, n_mb), "entropy": sum_ent / max(1, n_mb),
                   "policy_loss": sum_pg / max(1, n_mb),
                   "value_loss": sum_v / max(1, n_mb),
                   "anchor_kl": sum_anch / max(1, n_mb), "beta": beta,
                   "episodes": len(ep_lines), "killed": int(dead),
                   "ep_sigma_p50": (float(np.percentile(
                       [float(e.get("sigma_t15") or 0) for e in rec], 50))
                       if rec else 0.0),
                   "win_rate_recent": (float(np.mean(
                       [float(e.get("win_rate") or 0) for e in rec])) if rec else 0.0),
                   "tier_p50": (float(np.percentile(
                       [float(e.get("tier_t15") or 0) for e in rec], 50))
                       if rec else 0.0),
                   "dec_per_s": round(decisions / max(1e-9, time.time() - t0), 0),
                   "seconds": round(time.time() - t0, 1)}
            hist_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            hist_f.flush()
            rows_hist.append(row)
            print("[cppo] " + json.dumps(row, ensure_ascii=False), flush=True)
            _thr = float(args.stop_if_sigma_below)
            if _thr > 0 and len(rows_hist) >= 3 and all(
                    r0["ep_sigma_p50"] < _thr for r0 in rows_hist[-3:]):
                print(f"[cppo] 早停：ep_sigma_p50 连续 3 次 < {_thr}", flush=True)
                stopped_early = True
                break
    finally:
        hist_f.close()
    save_checkpoint(model, os.path.join(str(args.out), "model.pt"),
                    meta={"trained_by": "scripts/train_combat_sandbox.py",
                          "decisions": decisions, "combat": True,
                          "opponent_quantile": str(cfg.opponent_quantile)})
    rep: Dict[str, Any] = {
        "out": str(args.out), "decisions": int(decisions), "updates": int(updates),
        "params": n_param, "stopped_early": bool(stopped_early),
        "cfg": {"gold_profile": cfg.gold_profile,
                "tier_reward_coef": cfg.tier_reward_coef,
                "opponent_quantile": cfg.opponent_quantile,
                "hp_start": cfg.hp_start, "combat_reward_coef": cfg.combat_reward_coef},
        "seconds": round(time.time() - t0, 1)}
    if int(args.eval_games) > 0:
        rep["eval_sandbox_greedy"] = evaluate(model, cfg, int(args.eval_games), device,
                                              seed0=int(args.seed0) + 100000)
        print("[cppo] eval " + json.dumps(
            {k: rep["eval_sandbox_greedy"][k] for k in
             ("games", "sigma_t15_p50", "tier_p50", "win_rate", "damage_taken_mean",
              "killed_rate", "turns_mean") if k in rep["eval_sandbox_greedy"]},
            ensure_ascii=False), flush=True)
    with open(os.path.join(str(args.out), "meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"args": vars(args), **rep}, fh, ensure_ascii=False, indent=1)
    print("[cppo] " + json.dumps(rep, ensure_ascii=False, default=str)[:400], flush=True)
    return rep


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="轻量战斗沙盒 PPO")
    ap.add_argument("--checkpoint", default="runs/compound_bc/ckpt_w8e4.pt")
    ap.add_argument("--out", default="runs/combat_sandbox/cs1")
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--dtype", default="fp32", choices=["fp32", "bf16"])
    ap.add_argument("--decisions", type=int, default=300_000)
    ap.add_argument("--envs", type=int, default=16)
    ap.add_argument("--batch-decisions", dest="batch_decisions", type=int, default=8192)
    ap.add_argument("--minibatch", type=int, default=512)
    ap.add_argument("--grad-accum", dest="grad_accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=3e-6)
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--gamma", type=float, default=1.0)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--entropy-coef", dest="entropy_coef", type=float, default=0.0)
    ap.add_argument("--value-coef", dest="value_coef", type=float, default=0.5)
    ap.add_argument("--max-grad-norm", dest="max_grad_norm", type=float, default=1.0)
    ap.add_argument("--anchor-beta", dest="anchor_beta", type=float, default=0.1)
    ap.add_argument("--value-warmup", dest="value_warmup", type=int, default=100)
    ap.add_argument("--value-lr", dest="value_lr", type=float, default=1e-3)
    ap.add_argument("--stop-if-sigma-below", dest="stop_if_sigma_below", type=float,
                    default=0.0)
    ap.add_argument("--turns", type=int, default=15)
    ap.add_argument("--gold-mode", dest="gold_mode", default="fixed")
    ap.add_argument("--gold-per-turn", dest="gold_per_turn", type=int, default=10)
    ap.add_argument("--gold-cap", dest="gold_cap", type=int, default=99)
    ap.add_argument("--gold-profile", dest="gold_profile",
                    default="3,4,5,6,7,8,9,10,10,10,10,10,11")
    ap.add_argument("--tier-reward-coef", dest="tier_reward_coef", type=float,
                    default=0.1)
    ap.add_argument("--action-cap", dest="action_cap", type=int, default=40)
    ap.add_argument("--trinkets", type=int, default=1)
    ap.add_argument("--strength-ref", dest="strength_ref", type=float, default=30000.0)
    ap.add_argument("--opponent-boards", dest="opponent_boards",
                    default="data/real_library/library_real_quasi_full.jsonl")
    ap.add_argument("--opponent-quantile", dest="opponent_quantile", default="p75",
                    choices=["p50", "p75", "p90"])
    ap.add_argument("--opponent-fidelity", dest="opponent_fidelity", default="full")
    ap.add_argument("--hp-start", dest="hp_start", type=int, default=30)
    ap.add_argument("--combat-reward-coef", dest="combat_reward_coef", type=float,
                    default=1.0)
    ap.add_argument("--dmg-norm", dest="dmg_norm", type=float, default=0.0)
    ap.add_argument("--eval-games", dest="eval_games", type=int, default=24)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--seed0", type=int, default=950000)
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    rep = train(args)
    print(json.dumps(rep, ensure_ascii=False, default=str)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
