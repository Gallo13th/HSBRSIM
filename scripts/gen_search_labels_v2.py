#!/usr/bin/env python3
"""搜索标签 **v2**：rollout 叶评估（回合末真实 Σ）+ 关键决策 + DAgger 行为口径。

与 v1（``scripts/gen_sandbox_search_labels.py``）的区别（``docs/ECONOMY_SANDBOX.md`` §10）：

1. **叶值 = 回合末真实 Σ**：候选动作后用当前策略 rollout 到本回合末，叶值 =
   ``log1p(回合末战团 Σ)``（``hsbg/az/train/sandbox_rollout.py``）。不再用未训练 /
   弱排序的 scalar value 头。
2. **只搜关键决策**：``--search-when {carrier_in_shop,carrier_in_hand,spell_in_hand,
   carrier_on_board,tier4plus,carrier_or_spell,any}``（默认 ``carrier_or_spell``），
   每回合最多 ``--search-max-per-turn 3`` 次。
3. **DAgger 式口径**：**行为永远按 π_base 采样**（不受搜索结果影响），π_search 只做
   标签；每步记录 ``obs / π_search top-k / π_base top-k / π_base top-1 / 搜索统计``。
   这样标签分布不被搜索采样噪声污染（v1 用 π_search 采样，轨迹 −11%）。

同时直接测「**搜索动作 vs 策略动作的回合末 Σ 差**」：
每个搜索决策的候选都带 ``sigma_end``（回合末真实 Σ），所以
``Δ = sigma_end(argmax Q) − sigma_end(π_base top-1)`` 是**因果配对**的（引擎确定性）。

用法::

  PYTHONPATH=rust/python:. python scripts/gen_search_labels_v2.py \
      --checkpoint runs/az_entity_s16b/model.pt --device cuda:7 \
      --games 300 --golds 10 --envs 16 --search-sims 0 \
      --search-when carrier_or_spell --search-max-per-turn 3 \
      --out data/search_labels_v2/sandbox_v2_g10.jsonl.gz
"""

from __future__ import annotations

import argparse
import gzip
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

from hsbg.az.train.economy_sandbox import (END_TURN, N_ACTIONS, OBS_CARDS,  # noqa: E402
                                           OBS_FLOATS, EconomySandbox,
                                           SandboxConfig, SandboxObs,
                                           carrier_ids, stack_obs)
from hsbg.az.train.sandbox_rollout import (RolloutConfig, RolloutResult,  # noqa: E402
                                           RolloutSearcher, _L,
                                           sigmas_from_features)
from hsbg.az.train.sandbox_search import (MOVE_HI, MOVE_LO, SearchConfig,  # noqa: E402
                                          SearchRunner, action_kind)

from scripts.gen_sandbox_search_labels import (encode_obs,  # noqa: E402
                                               kl_nats, topk_pi)


def _torch():
    import torch
    return torch


def _pct(vals: Sequence[float], q: float) -> Optional[float]:
    if not vals:
        return None
    return float(np.percentile(np.asarray(vals, dtype=np.float64), q))


def _mean(vals: Sequence[float]) -> Optional[float]:
    if not vals:
        return None
    return float(np.mean(np.asarray(vals, dtype=np.float64)))


def _sample(pi: np.ndarray, rng: np.random.Generator) -> int:
    p = np.asarray(pi, dtype=np.float64)
    p = np.where(np.isfinite(p) & (p > 0), p, 0.0)
    s = float(p.sum())
    if s <= 0:
        return END_TURN
    return int(rng.choice(N_ACTIONS, p=p / s))


def _value_head_search(runner: SearchRunner, envs: Sequence[EconomySandbox],
                       f: np.ndarray, c: np.ndarray, m: np.ndarray,
                       priors: np.ndarray, values: np.ndarray,
                       seeds: Sequence[int]) -> List[RolloutResult]:
    """``--leaf-mode value_head``：v1 的 PUCT（拟合 value 头做叶评估）适配到 v2 记录口径。"""
    res = runner.run(list(envs), f, c, m, priors, values, seeds=list(seeds))
    out: List[RolloutResult] = []
    for r, pr in zip(res, priors):
        cands = np.asarray(r.cands, dtype=np.int64)
        q = np.asarray([float(r.q[int(a)]) for a in cands], dtype=np.float64)
        p = np.asarray(pr, dtype=np.float64)[cands]
        base_idx = int(np.argmax(p)) if cands.size else 0
        best_idx = int(np.argmax(q)) if q.size else 0
        out.append(RolloutResult(
            pi=np.asarray(r.pi, dtype=np.float32), cands=cands, q=q,
            sigma_end=np.full(len(cands), -1, dtype=np.int64),
            tier_end=np.zeros(len(cands), dtype=np.int64),
            carriers_end=np.zeros(len(cands), dtype=np.int64),
            base=int(cands[base_idx]) if cands.size else END_TURN,
            base_q=float(q[base_idx]) if q.size else 0.0,
            best=int(cands[best_idx]) if cands.size else END_TURN,
            best_q=float(q[best_idx]) if q.size else 0.0,
            sigma_base=-1, sigma_best=-1,
            value=float(r.root_value), q_std=float(np.std(q)) if q.size else 0.0,
            tau=0.0, pi_top1_mass=float(np.max(r.pi)) if r.pi.size else 0.0,
            elapsed_s=float(r.elapsed_s), leaf_steps=int(r.leaf_value_calls),
            truncated=0))
    return out


def generate(model, device: str, args, cfg_roll: RolloutConfig,
             sr: RolloutSearcher, vh_runner: Optional[SearchRunner],
             vh_cfg: Optional[SearchConfig]) -> Dict[str, Any]:
    golds = [int(x) for x in str(args.golds).split(",") if str(x).strip()]
    out_path = str(args.out)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    summary: Dict[str, Any] = {
        "version": "v2",
        "games_target": int(args.games), "golds": golds,
        "leaf_mode": str(args.leaf_mode),
        "rollout": {"topk": int(cfg_roll.topk), "turns": int(cfg_roll.turns),
                    "mode": str(cfg_roll.rollout_mode),
                    "samples": int(cfg_roll.rollout_samples),
                    "pi_mode": str(cfg_roll.pi_mode),
                    "q_temp": float(cfg_roll.q_temp),
                    "q_temp_scale": float(cfg_roll.q_temp_scale),
                    "adv_clip": float(cfg_roll.adv_clip),
                    "tier_bonus": float(cfg_roll.tier_bonus),
                    "carrier_bonus": float(cfg_roll.carrier_bonus)},
        "search_when": str(args.search_when),
        "search_max_per_turn": int(args.search_max_per_turn),
        "behavior": str(args.behavior),
    }
    n_done = 0
    n_steps = 0
    n_searched = 0
    n_skipped = 0
    t_start = time.time()
    kl_vals: List[float] = []
    agree: List[int] = []
    search_times: List[float] = []
    leaf_steps: List[int] = []
    truncs: List[int] = []
    q_stds: List[float] = []
    top1_mass: List[float] = []
    d_sigma_best: List[int] = []
    d_sigma_pi: List[int] = []
    d_L_best: List[float] = []
    best_eq_base = 0
    pi_eq_base = 0
    base_at_endturn = 0
    tags_carrier_shop = 0
    tags_carrier_hand = 0
    tags_spell_hand = 0
    tags_tier4 = 0
    searches_per_turn_hist: Dict[int, int] = {}
    probes: List[Tuple[Any, np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    ep_t12: List[int] = []
    ep_t15: List[int] = []
    ep_tier: List[int] = []
    ep_searches: List[int] = []
    n_probe_target = max(0, int(args.latency_probe))
    fh = gzip.open(out_path, "wt", encoding="utf-8", compresslevel=6)

    def emit(rec: Dict[str, Any]) -> None:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    try:
        envs_n = int(args.envs)
        total = int(args.games)
        started = 0
        slots: List[Dict[str, Any]] = []

        def new_slot() -> Dict[str, Any]:
            nonlocal started
            gold = golds[started % len(golds)]
            seed = int(args.seed0) + started
            env = EconomySandbox(SandboxConfig(gold_per_turn=gold))
            obs0 = env.reset(seed=seed)
            started += 1
            return {"env": env, "obs": obs0, "seed": seed, "step": 0,
                    "searched_turn": 0, "last_turn": int(env.g.turn),
                    "turn_searches": 0}

        while len(slots) < envs_n and started < total:
            slots.append(new_slot())
        last_print = time.time()
        while slots:
            f, c, m = stack_obs([s["obs"] for s in slots])
            t_fwd = time.time()
            priors, values = sr.policy(f, c, m)
            fwd_s = time.time() - t_fwd
            # 1) 关键决策判定（search_when + 每回合预算）
            search_idx: List[int] = []
            tags_list = [sr.tags(f[idx], c[idx]) for idx in range(len(slots))]
            for idx, slot in enumerate(slots):
                turn = int(slot["obs"].turn)
                if turn != slot["last_turn"]:
                    slot["last_turn"] = turn
                    slot["searched_turn"] = 0
                tg = tags_list[idx]
                if tg.carrier_in_shop:
                    tags_carrier_shop += 1
                if tg.carrier_in_hand:
                    tags_carrier_hand += 1
                if tg.spell_in_hand:
                    tags_spell_hand += 1
                if tg.tier >= 4:
                    tags_tier4 += 1
                legal = np.flatnonzero(m[idx])
                n_cand = int(((legal < MOVE_LO) | (legal >= MOVE_HI)).sum())
                if sr.should_search(tg, searched_this_turn=slot["searched_turn"]) \
                        and n_cand >= max(2, int(cfg_roll.min_cands)):
                    search_idx.append(idx)
            results: Dict[int, RolloutResult] = {}
            t_search = time.time()
            if search_idx:
                sub_envs = [slots[i]["env"] for i in search_idx]
                fs, cs, ms = f[search_idx], c[search_idx], m[search_idx]
                ps = priors[search_idx]
                if str(args.leaf_mode) == "rollout":
                    res = sr.search(sub_envs, fs, cs, ms, ps)
                else:
                    assert vh_runner is not None and vh_cfg is not None
                    res = _value_head_search(
                        vh_runner, sub_envs, fs, cs, ms, ps, values[search_idx],
                        seeds=[slots[i]["seed"] for i in search_idx])
                for k, i in enumerate(search_idx):
                    results[i] = res[k]
                    slots[i]["searched_turn"] += 1
                    slots[i]["turn_searches"] += 1
                if n_probe_target > len(probes):
                    for k, i in enumerate(search_idx):
                        if len(probes) >= n_probe_target:
                            break
                        probes.append((slots[i]["env"].clone(), fs[k].copy(),
                                       cs[k].copy(), ms[k].copy(), ps[k].copy()))
            batch_search_s = time.time() - t_search
            per_search = (batch_search_s / len(search_idx)) if search_idx else 0.0
            # 2) 行为动作 = π_base 采样（DAgger：行为不受搜索结果影响）+ 写标签
            acts = np.empty(len(slots), dtype=np.int64)
            for idx, slot in enumerate(slots):
                rng = np.random.default_rng(
                    int(slot["seed"]) * 1000003 + slot["step"] * 7919)
                res = results.get(idx)
                base_top1 = int(np.argmax(priors[idx]))
                rec: Dict[str, Any] = {}
                if res is not None:
                    # 标签 π_search
                    n_searched += 1
                    kl_vals.append(kl_nats(res.pi, priors[idx]))
                    agree.append(int(res.top1() == base_top1))
                    search_times.append(float(res.elapsed_s))
                    leaf_steps.append(int(res.leaf_steps))
                    truncs.append(int(res.truncated))
                    q_stds.append(float(res.q_std))
                    top1_mass.append(float(res.pi_top1_mass))
                    if int(res.best) == int(res.base):
                        best_eq_base += 1
                    if int(res.top1()) == int(base_top1):
                        pi_eq_base += 1
                    if int(base_top1) == END_TURN:
                        base_at_endturn += 1
                    if int(res.sigma_end[0]) >= 0:
                        j_best = int(np.argmax(res.q))
                        j_base = int(np.flatnonzero(res.cands == res.base)[0])
                        j_pi = int(np.flatnonzero(res.cands == res.top1())[0]) \
                            if res.top1() in set(int(x) for x in res.cands) else j_best
                        d_best = int(res.sigma_end[j_best]) - int(res.sigma_end[j_base])
                        d_pi = int(res.sigma_end[j_pi]) - int(res.sigma_end[j_base])
                        d_sigma_best.append(d_best)
                        d_sigma_pi.append(d_pi)
                        d_L_best.append(_L(int(res.sigma_end[j_best]))
                                        - _L(int(res.sigma_end[j_base])))
                    rec["search"] = {
                        "pi_top1": int(res.top1()), "pi_top1_mass":
                            round(float(res.pi_top1_mass), 4),
                        "best": int(res.best), "base": int(res.base),
                        "best_q": round(float(res.best_q), 6),
                        "base_q": round(float(res.base_q), 6),
                        "value": round(float(res.value), 6),
                        "q_std": round(float(res.q_std), 6),
                        "tau": round(float(res.tau), 6),
                        "cands": [int(a) for a in res.cands],
                        "pi_base_cands": [round(float(priors[idx][int(a)]), 8)
                                          for a in res.cands],
                        "q": [round(float(x), 6) for x in res.q],
                        "sigma_end": [int(x) for x in res.sigma_end],
                        "tier_end": [int(x) for x in res.tier_end],
                        "carriers_end": [int(x) for x in res.carriers_end],
                        "steps": int(res.leaf_steps),
                        "elapsed_s": round(float(res.elapsed_s), 6),
                        "truncated": int(res.truncated),
                    }
                rec.update({"type": "step", "seed": int(slot["seed"]),
                            "gold": int(slot["env"].gold_per_turn),
                            "turn": int(slot["obs"].turn), "step": int(slot["step"]),
                            "tier": int(tags_list[idx].tier),
                            "carriers": int(tags_list[idx].carriers_board),
                            "searched": int(res is not None),
                            "pi": topk_pi(res.pi, int(args.label_topk)) if res is not None else [],
                            "pi_base": topk_pi(priors[idx], int(args.label_topk)),
                            "pi_base_top1": base_top1,
                            "value": round(float(values[idx]), 4),
                            "sigma": int(sigmas_from_features(f[idx:idx + 1])[0]),
                            "obs": encode_obs(slot["obs"])})
                acts[idx] = _sample(priors[idx], rng)
                if res is not None and str(args.behavior) == "pi_search":
                    acts[idx] = _sample(res.pi, rng)
                rec["action"] = int(acts[idx])
                rec["kind"] = action_kind(int(acts[idx]))
                emit(rec)
                n_steps += 1
            # 3) 推进 + 补位
            keep: List[Dict[str, Any]] = []
            for idx, slot in enumerate(slots):
                env = slot["env"]
                o, _r, d, info = env.step(int(acts[idx]))
                slot["obs"] = o
                slot["step"] += 1
                if d:
                    ep = info.get("episode") or env.episode_summary()
                    emit({"type": "episode", "seed": int(slot["seed"]),
                          "gold": int(env.gold_per_turn),
                          "sigma_t12": int(ep.get("sigma_t12") or 0),
                          "sigma_t15": int(ep.get("sigma_t15") or 0),
                          "tier_final": int(ep.get("tier_final") or 0),
                          "carriers_max": int(ep.get("carriers_max") or 0),
                          "spells_t15": int(ep.get("spells_t15") or 0),
                          "tavern_buff_t15": int(ep.get("tavern_buff_t15") or 0),
                          "decisions": int(slot["step"]),
                          "searches": int(slot.get("turn_searches") or 0)})
                    ep_t12.append(int(ep.get("sigma_t12") or 0))
                    ep_t15.append(int(ep.get("sigma_t15") or 0))
                    ep_tier.append(int(ep.get("tier_final") or 0))
                    ep_searches.append(int(slot.get("turn_searches") or 0))
                    n_done += 1
                else:
                    keep.append(slot)
            slots = keep
            while len(slots) < envs_n and started < total:
                slots.append(new_slot())
            if time.time() - last_print > 30:
                last_print = time.time()
                print(f"[v2] games {n_done}/{total} steps={n_steps} "
                      f"searched={n_searched} active={len(slots)} "
                      f"elapsed={time.time() - t_start:.0f}s", flush=True)
    finally:
        fh.close()

    # 4) 串行单决策延迟（batch=1，任务口径「单次搜索 <500ms」）
    probe_stats: Dict[str, Any] = {"n": 0}
    if probes:
        ts: List[float] = []
        for env, pf, pc, pm, pp in probes:
            t0 = time.time()
            sr.search([env], pf[None, :], pc[None, :], pm[None, :], pp[None, :])
            ts.append(time.time() - t0)
        probe_stats = {"n": len(ts), "p50_ms": round(_pct(ts, 50) * 1000.0, 1),
                       "p95_ms": round(_pct(ts, 95) * 1000.0, 1),
                       "max_ms": round(float(max(ts)) * 1000.0, 1)}
        print(f"[v2] 串行单决策延迟: {probe_stats}", flush=True)

    elapsed = time.time() - t_start
    denom = max(1, n_searched)
    summary.update({
        "games": int(n_done), "steps": int(n_steps),
        "searched_steps": int(n_searched),
        "search_ratio": (float(n_searched) / n_steps if n_steps else 0.0),
        "seconds_per_game": round(float(elapsed) / max(1, n_done), 3),
        "elapsed_s": round(float(elapsed), 1),
        "amortized_search_ms_p50": round(_pct(search_times, 50) * 1000.0, 1)
        if search_times else None,
        "amortized_search_ms_p95": round(_pct(search_times, 95) * 1000.0, 1)
        if search_times else None,
        "serial_single_search": probe_stats,
        "kl_pi_base_mean": _mean(kl_vals), "kl_pi_base_p50": _pct(kl_vals, 50),
        "top1_agree_with_base": _mean(agree),
        "pi_top1_mass_mean": _mean(top1_mass),
        "q_std_mean": _mean(q_stds),
        "leaf_steps_mean": _mean(leaf_steps),
        "truncated_rollouts_mean": _mean(truncs),
        "best_eq_base_rate": (float(best_eq_base) / denom),
        "pi_top1_eq_base_rate": (float(pi_eq_base) / denom),
        "base_top1_is_endturn_rate": (float(base_at_endturn) / denom),
        "sigma_delta_best_minus_base": {
            "mean": _mean(d_sigma_best), "p50": _pct(d_sigma_best, 50),
            "p90": _pct(d_sigma_best, 90), "p10": _pct(d_sigma_best, 10),
            "frac_pos": (_mean([1.0 if x > 0 else 0.0 for x in d_sigma_best])),
            "frac_neg": (_mean([1.0 if x < 0 else 0.0 for x in d_sigma_best])),
            "n": len(d_sigma_best)},
        "sigma_delta_pi_minus_base": {
            "mean": _mean(d_sigma_pi), "p50": _pct(d_sigma_pi, 50),
            "p90": _pct(d_sigma_pi, 90), "p10": _pct(d_sigma_pi, 10),
            "frac_pos": (_mean([1.0 if x > 0 else 0.0 for x in d_sigma_pi])),
            "frac_neg": (_mean([1.0 if x < 0 else 0.0 for x in d_sigma_pi])),
            "n": len(d_sigma_pi)},
        "L_delta_best_minus_base_mean": _mean(d_L_best),
        "tag_presence_rate": {
            "carrier_in_shop": (tags_carrier_shop / max(1, n_steps)),
            "carrier_in_hand": (tags_carrier_hand / max(1, n_steps)),
            "spell_in_hand": (tags_spell_hand / max(1, n_steps)),
            "tier4plus": (tags_tier4 / max(1, n_steps))},
        "behavior_trajectory": {
            "t12_p50": _pct(ep_t12, 50), "t12_p90": _pct(ep_t12, 90),
            "t15_p50": _pct(ep_t15, 50), "t15_p90": _pct(ep_t15, 90),
            "tier_p50": _pct(ep_tier, 50),
            "searches_per_game_mean": _mean(ep_searches)},
        "out": out_path})
    sm_path = out_path[:-len(".jsonl.gz")] + ".summary.json" \
        if out_path.endswith(".jsonl.gz") else os.path.splitext(out_path)[0] + ".summary.json"
    with open(sm_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="沙盒搜索标签 v2（rollout 叶值 + DAgger）")
    ap.add_argument("--checkpoint", default="runs/az_entity_s16b/model.pt")
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--golds", default="10")
    ap.add_argument("--seed0", type=int, default=970000)
    ap.add_argument("--envs", type=int, default=16)
    ap.add_argument("--dtype", default="fp32", choices=["fp32", "bf16"])
    ap.add_argument("--label-topk", type=int, default=8)
    ap.add_argument("--latency-probe", type=int, default=8)
    # 叶值口径
    ap.add_argument("--leaf-mode", default="rollout", choices=["rollout", "value_head"])
    ap.add_argument("--rollout-turns", dest="rollout_turns", type=int, default=1,
                    help="rollout 到第几个回合末（1 = 本回合末）")
    ap.add_argument("--rollout-mode", default="greedy", choices=["greedy", "sample"])
    ap.add_argument("--rollout-samples", type=int, default=1,
                    help="sample 模式下每个候选采样几条 rollout（CRN，降方差）")
    ap.add_argument("--rollout-max-steps", type=int, default=128)
    ap.add_argument("--topk", type=int, default=8)
    ap.add_argument("--pi-mode", default="advantage", choices=["advantage", "softmax"])
    ap.add_argument("--q-temp", type=float, default=0.0, help="0 = 自适应 std(Q)")
    ap.add_argument("--q-temp-scale", type=float, default=1.0)
    ap.add_argument("--adv-clip", type=float, default=30.0,
                    help="优势项裁剪 nats（30=不裁；3–6=KL 信任域）")
    ap.add_argument("--tier-bonus", type=float, default=0.0)
    ap.add_argument("--carrier-bonus", type=float, default=0.0)
    # 关键决策
    ap.add_argument("--search-when", default="carrier_or_spell")
    ap.add_argument("--search-max-per-turn", type=int, default=3)
    ap.add_argument("--behavior", default="pi_base", choices=["pi_base", "pi_search"],
                    help="行为口径：pi_base = DAgger（v2 默认）；pi_search = 直接评估搜索策略")
    # value_head 分支（v1 口径对照）
    ap.add_argument("--search-sims", type=int, default=64)
    ap.add_argument("--search-c-puct", type=float, default=0.25)
    ap.add_argument("--value-head", default="")
    ap.add_argument("--out", default="data/search_labels_v2/sandbox_v2_g10.jsonl.gz")
    ap.add_argument("--limit-games", type=int, default=0, help="冒烟：只跑 N 局")
    args = ap.parse_args(argv)
    if int(args.limit_games) > 0:
        args.games = int(args.limit_games)

    from hsbg.az.train.model import load_checkpoint
    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    model.eval()
    print(f"[v2] ckpt={args.checkpoint} arch={meta.get('arch')} "
          f"d_model={meta.get('d_model')} layers={meta.get('n_layers')}", flush=True)

    cfg_roll = RolloutConfig(
        topk=int(args.topk), max_steps=int(args.rollout_max_steps),
        turns=int(args.rollout_turns), rollout_mode=str(args.rollout_mode),
        rollout_samples=int(args.rollout_samples),
        pi_mode=str(args.pi_mode), q_temp=float(args.q_temp),
        q_temp_scale=float(args.q_temp_scale), adv_clip=float(args.adv_clip),
        tier_bonus=float(args.tier_bonus),
        carrier_bonus=float(args.carrier_bonus),
        search_when=str(args.search_when),
        max_searches_per_turn=int(args.search_max_per_turn),
        seed=int(args.seed0))
    cfg_roll.validate()
    sr = RolloutSearcher(model, device=args.device, cfg=cfg_roll, dtype=str(args.dtype))
    vh_runner = None
    vh_cfg = None
    if str(args.leaf_mode) == "value_head":
        from scripts.gen_sandbox_search_labels import load_fitted_value_head
        if str(args.value_head):
            load_fitted_value_head(model, str(args.value_head), args.device)
            print(f"[v2] 载入拟合 value 头: {args.value_head}", flush=True)
        vh_cfg = SearchConfig(sims=int(args.search_sims), topk=int(args.topk),
                              depth_turns=int(args.rollout_turns),
                              max_plies=int(args.rollout_max_steps),
                              c_puct=float(args.search_c_puct),
                              max_searches_per_turn=int(args.search_max_per_turn),
                              value_mode="total", skip_move=True)
        vh_runner = SearchRunner(model, device=args.device, cfg=vh_cfg,
                                 dtype=str(args.dtype))
    summary = generate(model, args.device, args, cfg_roll, sr, vh_runner, vh_cfg)
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
