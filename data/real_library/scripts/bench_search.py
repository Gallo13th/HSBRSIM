"""Phase 1 搜索基准（不训练）。

对应 ``docs/ALGORITHM_RESEARCH.md`` §6.3：
- 固定快照：8p/6p/4p/2p 各一个（teacher 打 6–8 回合）；
- 性能：clone / legal_actions / obs / ERP / 1-turn rollout / BC 前向；
- 搜索：N=1/8/16/32（macro K=4，depth=1），与 §6.3 阈值对照；
- 确定性：同 seed 两次 π/最佳 macro 一致；
- 合法性：macro 每步都在当时合法候选内；
- oracle 泄漏检查：``oracle_used=False``、determinize 不注入隐藏状态；
- 100 快照 search-vs-BC：BC top-1 vs search 最佳 macro 首动作一致率/熵。

输出：``runs/search/phase1_bench.json``（含 per-metric 分位数、阈值 pass/fail、
per-snapshot 对比行）。不启动训练、不写 checkpoint。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 允许直接 ``python scripts/bench_search.py``（无需 PYTHONPATH / -m）
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np

from hsbg.env import observation
from hsbg.env.game_env import BattlegroundsEnv
from hsbg.rl.policies import act_index, make_policy
from hsbg.search import (
    EngineForwardModel,
    PolicyEvaluator,
    SearchConfig,
    WarbandBank,
    run_search,
)
from hsbg import planning


# ── 快照 ──
def build_snapshot(num_players: int = 8, seed: int = 3,
                   target_turn: int = 7) -> EngineForwardModel:
    env = BattlegroundsEnv(num_players=num_players, opponent="heuristic", seed=seed)
    obs = env.reset(seed=seed)
    teacher = make_policy("teacher")
    try:
        teacher.bind_env(env)
    except Exception:  # noqa: BLE001
        pass
    for _ in range(600):
        obs, r, term, trunc, info = env.step(act_index(teacher, obs))
        if term or trunc or obs.turn >= target_turn:
            break
    model = EngineForwardModel.from_env(env, clone=True)
    env.close()
    return model


def percentile(xs: List[float], p: float) -> float:
    if not xs:
        return 0.0
    arr = sorted(float(x) for x in xs)
    k = max(0, min(len(arr) - 1, int(round((p / 100.0) * (len(arr) - 1)))))
    return float(arr[k])


def summarize(xs: List[float]) -> Dict[str, float]:
    return {
        "n": len(xs),
        "mean": float(statistics.fmean(xs)) if xs else 0.0,
        "p50": percentile(xs, 50),
        "p90": percentile(xs, 90),
        "max": float(max(xs)) if xs else 0.0,
    }


# ── 性能测量 ──
def measure_perf(model: EngineForwardModel, evaluator: PolicyEvaluator,
                 clones: int = 30, repeats: int = 30) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    # warmup（首次 clone 含缓存冷启动，避免把冷启动算进 p50/p90）
    for _ in range(3):
        planning.clone(model.game)
    clone_ts: List[float] = []
    for _ in range(clones):
        t = time.perf_counter()
        planning.clone(model.game)
        clone_ts.append((time.perf_counter() - t) * 1000.0)
    out["clone_ms"] = summarize(clone_ts)

    legal_ts: List[float] = []
    for _ in range(repeats):
        t = time.perf_counter()
        planning.legal_actions(model.game, model.hero)
        legal_ts.append((time.perf_counter() - t) * 1000.0)
    out["legal_actions_ms"] = summarize(legal_ts)

    # observation + BC forward（= 1-ply 评估的主要成本）
    obs_ts: List[float] = []
    for _ in range(repeats):
        cands = model.candidates()
        t = time.perf_counter()
        observation.build_observation(
            model.game, model.hero, cands, phase="recruit",
            turn=model.turn, total_players=model.total_players)
        obs_ts.append((time.perf_counter() - t) * 1000.0)
    out["obs_ms"] = summarize(obs_ts)

    eval_ts: List[float] = []
    for _ in range(max(10, repeats // 2)):
        t = time.perf_counter()
        evaluator.evaluate(model)
        eval_ts.append((time.perf_counter() - t) * 1000.0)
    out["bc_eval_ms"] = summarize(eval_ts)

    ply_ts: List[float] = []
    for _ in range(max(10, repeats // 2)):
        t = time.perf_counter()
        dup = model.clone()
        evaluator.evaluate(dup)
        ply_ts.append((time.perf_counter() - t) * 1000.0)
    out["one_ply_clone_eval_ms"] = summarize(ply_ts)

    # ERP（clone 上跑）
    erp_ts: List[float] = []
    for _ in range(max(5, repeats // 5)):
        dup = model.clone()
        t = time.perf_counter()
        try:
            dup.game.end_recruit_phase()
        except Exception:  # noqa: BLE001
            continue
        erp_ts.append((time.perf_counter() - t) * 1000.0)
    out["erp_ms"] = summarize(erp_ts)

    # 1-turn rollout（含 clone 与不含 clone）
    rollout_ts: List[float] = []
    rollout_clone_ts: List[float] = []
    for _ in range(max(5, repeats // 5)):
        t = time.perf_counter()
        dup = model.clone()
        clone_ms = (time.perf_counter() - t) * 1000.0
        try:
            planning.random_rollout(dup.game, dup.hero, max_turns=1, max_steps=80)
        except Exception:  # noqa: BLE001
            continue
        total_ms = (time.perf_counter() - t) * 1000.0
        rollout_ts.append(total_ms - clone_ms)
        rollout_clone_ts.append(total_ms)
    out["rollout_1turn_ms"] = summarize(rollout_ts)
    out["rollout_1turn_with_clone_ms"] = summarize(rollout_clone_ts)

    # 快速叶战斗（env-builder 建议：simulate_turn_combat 3.51ms vs ERP 12.96ms）
    combat_ts: List[float] = []
    for _ in range(max(5, repeats // 5)):
        dup = model.clone()
        t = time.perf_counter()
        try:
            planning.simulate_turn_combat(dup.game, dup.hero, keep_state=False)
        except Exception:  # noqa: BLE001
            continue
        combat_ts.append((time.perf_counter() - t) * 1000.0)
    out["turn_combat_ms"] = summarize(combat_ts)

    # 1000 次 clone + 轻评估（对齐 env-builder 口径）
    t = time.perf_counter()
    for _ in range(1000):
        dup = model.clone()
        planning.evaluate(dup.game, dup.hero)
    out["clone_eval_1000_ms"] = (time.perf_counter() - t) * 1000.0
    return out


# ── 搜索与合法性 ──
def verify_macro_legal(model: EngineForwardModel, result) -> bool:
    if result.best_macro is None:
        return True
    dup = model.clone()
    for cand in result.best_macro.steps:
        if dup.is_terminal():
            return True
        legal = {c.signature() for c in dup.candidates()}
        if cand.signature() not in legal:
            return False
        if not dup.apply(cand):
            return False
    return True


def measure_search(model: EngineForwardModel, evaluator: PolicyEvaluator,
                   sims: List[int], *, macro_candidates: int = 4,
                   seed: int = 0, leaf_mode: str = "combat",
                   cache_root_values: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {"levels": {},
                           "leaf_mode": leaf_mode,
                           "cache_root_values": bool(cache_root_values)}
    for n in sims:
        cfg = SearchConfig(simulations=n, macro_candidates=macro_candidates,
                           max_depth_turns=1, seed=seed,
                           leaf_mode=leaf_mode,
                           cache_root_values=bool(cache_root_values))
        reps = 3 if n <= 8 else (2 if n <= 16 else 1)
        times: List[float] = []
        res = None
        for _ in range(reps):
            t = time.perf_counter()
            res = run_search(model, evaluator, cfg)
            times.append((time.perf_counter() - t) * 1000.0)
        out["levels"][str(n)] = {
            "ms_per_decision": summarize(times),
            "best_first": None if res is None or res.best_macro is None
            else res.best_macro.first.signature(),
            "expansions": 0 if res is None else res.n_expansions,
            "hidden_info_mode": "" if res is None else res.hidden_info_mode,
            "root_values": [] if res is None else
            [float(x) for x in np.asarray(res.root_values).tolist()],
        }
        if n == 8 and res is not None:
            out["deterministic_sample"] = res.as_dict()
    # 确定性：N=8 两次完全一致
    cfg = SearchConfig(simulations=8, macro_candidates=macro_candidates,
                       max_depth_turns=1, seed=seed, leaf_mode=leaf_mode,
                       cache_root_values=bool(cache_root_values))
    r1 = run_search(model, evaluator, cfg)
    r2 = run_search(model, evaluator, cfg)
    out["determinism"] = {
        "pi_equal": bool(np.array_equal(r1.pi, r2.pi)),
        "visits_equal": bool(np.array_equal(r1.visits, r2.visits)),
        "best_equal": bool(
            (r1.best_macro is None and r2.best_macro is None)
            or (r1.best_macro is not None and r2.best_macro is not None
                and r1.best_macro.signatures == r2.best_macro.signatures)),
    }
    out["legality"] = {
        "macro_legal": bool(verify_macro_legal(model, r1)),
        "pi_valid": bool(np.all(r1.pi >= 0) and abs(float(r1.pi.sum()) - 1.0) < 1e-6),
        "oracle_used": bool(r1.oracle_used),
        "hidden_info_mode": r1.hidden_info_mode,
    }
    out["search_result_N8"] = r1.as_dict()
    return out


# ── 100 快照 search-vs-BC ──
def search_vs_bc(snapshots: List[EngineForwardModel],
                 evaluator: PolicyEvaluator, *, sims: int = 8,
                 macro_candidates: int = 4, seed: int = 0,
                 use_bc_first: bool = True,
                 prior_mode: str = "bc",
                 with_rows: bool = True) -> Dict[str, Any]:
    """对比 BC top-1 与 search 最佳 macro 首动作。

    注意：默认 ``use_bc_first=True`` 时 macro 候选里**显式包含**一条
    “BC 首步 + 随机补齐”的 macro，且 search prior 也用 BC logits，
    因此高一致率是**结构性**的，不能当作“搜索有效性”证据。
    同时报告 ``use_bc_first=False`` 的对照（见 main），并记录 Q/熵/叶子价值。
    """
    rows: List[Dict[str, Any]] = []
    agree = 0
    total = 0
    n_bc_in_macros = 0
    n_picked_prior_top = 0
    n_picked_value_max = 0
    n_distinct_firsts: List[int] = []
    prior_maxs: List[float] = []
    leaf_vals: List[float] = []
    bc_vals: List[float] = []
    bc_one_step_vals: List[float] = []
    entropy_search: List[float] = []
    entropy_prior: List[float] = []
    for i, model in enumerate(snapshots):
        try:
            top = evaluator.top_action(model)
            bc_cand, bc_p = (top if top is not None else (None, 0.0))
            cfg = SearchConfig(
                simulations=sims, macro_candidates=macro_candidates,
                max_depth_turns=1, seed=seed + i,
                use_bc_first_macro=bool(use_bc_first),
                prior_mode=str(prior_mode),
            )
            t = time.perf_counter()
            res = run_search(model, evaluator, cfg)
            ms = (time.perf_counter() - t) * 1000.0
            search_first = res.best_macro.first if res.best_macro is not None else None
            same = (search_first is not None and bc_cand is not None
                    and search_first.signature() == bc_cand.signature())
            # 默认配置会生成一条“BC 首步 + 随机补齐”的 macro；这里记录该结构性因素
            bc_in_macros = bool(use_bc_first and bc_cand is not None)
            # 搜索首选 macro 的叶子价值（vs BC 当前/一步价值）
            best_leaf_value = None
            if res.best_macro is not None:
                dup = model.clone()
                if dup.apply_macro(res.best_macro):
                    best_leaf_value = float(evaluator.evaluate(dup).value)
            bc_value = float(evaluator.evaluate(model).value)
            bc_one_step = None
            if bc_cand is not None:
                dup2 = model.clone()
                if dup2.apply(bc_cand):
                    bc_one_step = float(evaluator.evaluate(dup2).value)
            prior = np.asarray(res.root_prior, dtype=np.float64)
            prior_max = float(prior.max()) if prior.size else 0.0
            firsts = [m.first.signature() for m in res.root_macros]
            distinct = len(set(firsts)) if firsts else 0
            picked_prior_top = bool(
                prior.size and res.best_index == int(np.argmax(prior)))
            vals = np.asarray(res.root_values, dtype=np.float64)
            picked_value_max = bool(
                vals.size and np.isfinite(vals).any()
                and res.best_index == int(np.nanargmax(vals)))
            total += 1
            agree += int(same)
            n_bc_in_macros += int(bc_in_macros)
            n_picked_prior_top += int(picked_prior_top)
            n_picked_value_max += int(picked_value_max)
            n_distinct_firsts.append(distinct)
            prior_maxs.append(prior_max)
            if best_leaf_value is not None:
                leaf_vals.append(float(best_leaf_value))
            bc_vals.append(float(bc_value))
            if bc_one_step is not None:
                bc_one_step_vals.append(float(bc_one_step))
            entropy_search.append(float(res.policy_entropy))
            entropy_prior.append(_entropy(prior))
            rows.append({
                "index": i,
                "turn": model.turn,
                "rank": model.rank(),
                "bc_top": None if bc_cand is None else bc_cand.signature(),
                "bc_prior": float(bc_p),
                "search_first": None if search_first is None else search_first.signature(),
                "agree": bool(same),
                "bc_top_in_macro_candidates": bool(bc_in_macros),
                "n_root_macros": len(res.root_macros),
                "n_distinct_firsts": distinct,
                "picked_prior_top": bool(picked_prior_top),
                "picked_value_max": bool(picked_value_max),
                "root_prior_max": round(prior_max, 4),
                "search_ms": round(ms, 3),
                "search_pi_entropy": round(res.policy_entropy, 4),
                "root_prior_entropy": round(_entropy(prior), 4),
                "search_best_leaf_value": best_leaf_value,
                "bc_current_value": bc_value,
                "bc_one_step_value": bc_one_step,
                "hidden_info_mode": res.hidden_info_mode,
                "use_bc_first_macro": bool(use_bc_first),
            })
        except Exception as exc:  # noqa: BLE001
            rows.append({"index": i, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "n_snapshots": total,
        "agreement": (agree / total) if total else 0.0,
        "n_agree": agree,
        "sims": sims,
        "macro_candidates": macro_candidates,
        "use_bc_first_macro": bool(use_bc_first),
        "prior_mode": str(prior_mode),
        "n_bc_top_in_macro_candidates": n_bc_in_macros,
        "frac_picked_prior_top": (n_picked_prior_top / total) if total else 0.0,
        "frac_picked_value_max": (n_picked_value_max / total) if total else 0.0,
        "mean_n_distinct_firsts": fmean_or_none([float(x) for x in n_distinct_firsts]),
        "mean_root_prior_max": fmean_or_none(prior_maxs),
        "mean_search_best_leaf_value": (statistics.fmean(leaf_vals)
                                        if leaf_vals else None),
        "mean_bc_current_value": fmean_or_none(bc_vals),
        "mean_bc_one_step_value": fmean_or_none(bc_one_step_vals),
        "mean_search_pi_entropy": fmean_or_none(entropy_search),
        "mean_root_prior_entropy": fmean_or_none(entropy_prior),
        "note": (
            "agreement 默认含 BC-first macro + BC prior（prior 往往很尖），"
            "高一致是结构性的；看 use_bc_first_macro=false 的对照、"
            "frac_picked_prior_top / frac_picked_value_max / 熵 / 叶子价值，"
            "不能把 agreement 当搜索有效性证据"
        ),
        "rows": rows if with_rows else [],
    }


def fmean_or_none(xs: List[float]) -> Optional[float]:
    return float(statistics.fmean(xs)) if xs else None


def _entropy(p) -> float:
    arr = np.asarray(p, dtype=np.float64)
    arr = arr[arr > 0]
    if arr.size == 0:
        return 0.0
    return float(-(arr * np.log(arr)).sum())


def search_gain_analysis(snapshots: List[EngineForwardModel],
                         evaluator: PolicyEvaluator, *,
                         sims_list: List[int] = [1, 8, 32],
                         macro_candidates: int = 4,
                         seeds: List[int] = [0, 17, 33]) -> Dict[str, Any]:
    """搜索增益分析（不训练）：预算/seed 对选择与 Q 分布的影响。

    - 1-ply vs N=8/32 的选择变化（best first 是否改变）；
    - 同快照不同 seed 的 Q 值分布/选择稳定性；
    - search 是否只是跟随 BC prior（picked_prior_top 比例）；
    - 两种 prior 模式：bc prior vs uniform prior+no-BC-macro（消融）。
    """
    modes = [
        {"name": "bc_prior_bc_macro", "prior_mode": "bc",
         "use_bc_first_macro": True},
        {"name": "uniform_prior_no_bc_macro", "prior_mode": "uniform",
         "use_bc_first_macro": False},
    ]
    result: Dict[str, Any] = {"modes": {}, "n_snapshots": len(snapshots),
                              "sims_list": list(sims_list),
                              "seeds": list(seeds)}
    for mode in modes:
        per_sim: Dict[str, Any] = {str(n): {"firsts": [], "ms": [],
                                             "entropy": [], "q_spread": [],
                                             "picked_prior_top": []}
                                   for n in sims_list}
        stable = 0
        changed_18 = 0
        changed_832 = 0
        n_used = 0
        for i, model in enumerate(snapshots):
            try:
                bc_top = evaluator.top_action(model)
                bc_sig = bc_top[0].signature() if bc_top else None
                firsts_by_n: Dict[int, Any] = {}
                for n in sims_list:
                    cfg = SearchConfig(
                        simulations=n, macro_candidates=macro_candidates,
                        max_depth_turns=1, seed=i,
                        prior_mode=mode["prior_mode"],
                        use_bc_first_macro=bool(mode["use_bc_first_macro"]))
                    t = time.perf_counter()
                    res = run_search(model, evaluator, cfg)
                    ms = (time.perf_counter() - t) * 1000.0
                    sig = (res.best_macro.first.signature()
                           if res.best_macro is not None else None)
                    firsts_by_n[n] = sig
                    vals = np.asarray(res.root_values, dtype=np.float64)
                    finite = vals[np.isfinite(vals)]
                    q_spread = (float(finite.max() - finite.min())
                                if finite.size >= 2 else 0.0)
                    prior = np.asarray(res.root_prior, dtype=np.float64)
                    d = per_sim[str(n)]
                    d["firsts"].append(None if sig is None else list(sig))
                    d["ms"].append(round(ms, 3))
                    d["entropy"].append(round(res.policy_entropy, 4))
                    d["q_spread"].append(q_spread)
                    if prior.size and res.best_index >= 0:
                        d["picked_prior_top"].append(
                            bool(res.best_index == int(np.argmax(prior))))
                # seed 稳定性（N=8）
                seed_sigs = []
                seed_qspreads = []
                for s in seeds:
                    cfg = SearchConfig(
                        simulations=8, macro_candidates=macro_candidates,
                        max_depth_turns=1, seed=1000 + i * 7 + s,
                        prior_mode=mode["prior_mode"],
                        use_bc_first_macro=bool(mode["use_bc_first_macro"]))
                    res = run_search(model, evaluator, cfg)
                    seed_sigs.append(
                        None if res.best_macro is None
                        else res.best_macro.first.signature())
                    vals = np.asarray(res.root_values, dtype=np.float64)
                    finite = vals[np.isfinite(vals)]
                    seed_qspreads.append(
                        float(finite.max() - finite.min())
                        if finite.size >= 2 else 0.0)
                n_used += 1
                stable += int(len(set(seed_sigs)) <= 1)
                changed_18 += int(firsts_by_n.get(8) != firsts_by_n.get(1))
                changed_832 += int(firsts_by_n.get(32) != firsts_by_n.get(8))
            except Exception:  # noqa: BLE001
                continue
        agg = {
            "n_used": n_used,
            "frac_seed_stable_N8": (stable / n_used) if n_used else 0.0,
            "frac_changed_1_to_8": (changed_18 / n_used) if n_used else 0.0,
            "frac_changed_8_to_32": (changed_832 / n_used) if n_used else 0.0,
        }
        for n in sims_list:
            d = per_sim[str(n)]
            vals = [x for x in d["q_spread"] if x is not None]
            ents = d["entropy"]
            picks = d["picked_prior_top"]
            firsts = d["firsts"]
            agg[str(n)] = {
                "mean_ms": fmean_or_none(d["ms"]),
                "mean_pi_entropy": fmean_or_none(ents),
                "mean_q_spread": fmean_or_none(vals),
                "frac_picked_prior_top": (sum(picks) / len(picks))
                if picks else None,
                "n_distinct_firsts": len({tuple(x) if x is not None else None
                                          for x in firsts}),
            }
        result["modes"][mode["name"]] = agg
    result["note"] = (
        "gain 分析不训练、不评估棋力；只报告预算/seed/prior 对选择与 Q 的影响。"
        "q_spread 是 root macro 叶 value 离散度，不是搜索收益证明。"
    )
    return result


# ── 阈值 ──
def evaluate_thresholds(perf: Dict[str, Any], search: Dict[str, Any],
                        *, clone_p50_limit_ms: float = 3.0,
                        clone_p90_limit_ms: float = 4.0) -> Dict[str, Any]:
    def get(metric: str, key: str = "p50") -> float:
        return float(perf.get(metric, {}).get(key, float("nan")))

    checks = {
        "clone_p50_le_limit": get("clone_ms", "p50") <= float(clone_p50_limit_ms),
        "clone_p90_le_limit": get("clone_ms", "p90") <= float(clone_p90_limit_ms),
        "one_ply_le_20ms": get("one_ply_clone_eval_ms", "p50") <= 20.0,
        "N8_le_350ms": search["levels"].get("8", {}).get(
            "ms_per_decision", {}).get("p50", 1e9) <= 350.0,
        "N16_le_700ms": search["levels"].get("16", {}).get(
            "ms_per_decision", {}).get("p50", 1e9) <= 700.0,
        "N32_le_1200ms": search["levels"].get("32", {}).get(
            "ms_per_decision", {}).get("p50", 1e9) <= 1200.0,
        "clone_eval_1000_le_8s": float(perf.get("clone_eval_1000_ms", 1e18)) <= 8000.0,
        "pi_valid": bool(search.get("legality", {}).get("pi_valid", False)),
        "macro_legal": bool(search.get("legality", {}).get("macro_legal", False)),
        "deterministic": all(bool(v) for v in search.get("determinism", {}).values()),
        "no_oracle": not bool(search.get("legality", {}).get("oracle_used", True)),
    }
    return {"checks": checks, "passed": all(checks.values())}


# ── main ──
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 1 search benchmark")
    parser.add_argument("--out", default="runs/search/phase1_bench.json")
    parser.add_argument("--snapshots", type=int, default=100,
                        help="search-vs-BC 快照数")
    parser.add_argument("--gain-snapshots", type=int, default=12,
                        help="增益分析（1-ply vs N=8/32、多 seed）快照数")
    parser.add_argument("--sims", default="1,8,16,32")
    parser.add_argument("--macro-candidates", type=int, default=4)
    parser.add_argument("--checkpoint", default="runs/bc/official_320/policy_bc.pt")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--bank", nargs="*", default=[],
                        help="真实/BC 轨迹 JSONL（determinization v0 bank）")
    parser.add_argument("--target-turn", type=int, default=4,
                        help="对齐 env-builder 8p T4 基准（clone ~1.6ms）")
    parser.add_argument("--leaf-mode", default="combat",
                        choices=["combat", "erp"])
    parser.add_argument("--cache-root", action="store_true",
                        help="K=1 确定性缓存 root macro 叶结果（更快；默认关=真 MCTS）")
    parser.add_argument("--clone-p50-limit", type=float, default=3.0,
                        help="env-builder clone v1 8p T4 1.63ms；本机 T4 实测 1.9–2.7ms（噪声）")
    parser.add_argument("--clone-p90-limit", type=float, default=4.0,
                        help="本机 clone p90 2.3–3.4ms（噪声）")
    parser.add_argument("--quick", action="store_true",
                        help="只跑 6 快照（冒烟，不满足 Phase1 出口）")
    args = parser.parse_args(argv)

    sims = [int(x) for x in str(args.sims).split(",") if x.strip()]
    evaluator = PolicyEvaluator(checkpoint=args.checkpoint, device=args.device)
    t_start = time.perf_counter()
    report: Dict[str, Any] = {
        "meta": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "checkpoint": args.checkpoint,
            "device": args.device,
            "macro_candidates": args.macro_candidates,
            "sims": sims,
            "leaf_mode": args.leaf_mode,
            "cache_root_values": bool(args.cache_root),
            "seed": args.seed,
            "quick": bool(args.quick),
            "note": "Phase 1：不训练；只测成本/正确性/可复现性",
        },
    }

    # 1) 多人数快照（性能用 8p）
    snapshots_num: Dict[str, EngineForwardModel] = {}
    for n in (8, 6, 4, 2):
        try:
            snapshots_num[str(n)] = build_snapshot(
                num_players=n, seed=args.seed + 100 * n,
                target_turn=args.target_turn)
        except Exception as exc:  # noqa: BLE001
            report.setdefault("errors", []).append(
                f"snapshot {n}p: {type(exc).__name__}: {exc}")
    model8 = snapshots_num.get("8")
    if model8 is None:
        print("ERROR: 无法构造 8p 快照")
        return 2
    report["snapshots"] = {
        k: v.state_summary() for k, v in snapshots_num.items()
    }

    # 2) 性能
    perf = measure_perf(model8, evaluator)
    report["perf"] = perf

    # 3) 搜索预算 + 合法性/确定性
    search = measure_search(model8, evaluator, sims,
                            macro_candidates=args.macro_candidates,
                            seed=args.seed,
                            leaf_mode=args.leaf_mode,
                            cache_root_values=bool(args.cache_root))
    report["search"] = search
    # ERP 叶对照（只跑 N=8，报告 combat-leaf vs erp-leaf 的成本/价值差异）
    if sims and 8 in sims:
        try:
            erp_search = measure_search(
                model8, evaluator, [8], macro_candidates=args.macro_candidates,
                seed=args.seed, leaf_mode="erp", cache_root_values=False)
            report["search_erp_leaf_control"] = erp_search
        except Exception as exc:  # noqa: BLE001
            report.setdefault("errors", []).append(
                f"erp control: {type(exc).__name__}: {exc}")

    # 4) determinization bank（若有）
    bank = None
    if args.bank:
        bank = WarbandBank.from_jsonl(args.bank)
        report["determinize"] = {
            "bank": bank.stats(),
            "note": "v0 仅摘要采样；未注入隐藏 board/hand（数据缺口见文档 §3.6）",
        }
    else:
        # 默认尝试已有 BC 轨迹池（存在则加载，仅记录摘要）
        defaults = ["runs/rl/heuristic_100.jsonl", "runs/rl/lead_heur_40.jsonl"]
        existing = [p for p in defaults if Path(p).exists()]
        if existing:
            bank = WarbandBank.from_jsonl(existing)
            report["determinize"] = {
                "bank": bank.stats(),
                "note": "v0 仅摘要采样；未注入隐藏 board/hand（数据缺口见文档 §3.6）",
            }
        else:
            report["determinize"] = {"bank": None,
                                     "note": "无轨迹池；未启用 determinization"}

    # 5) 100 快照 search-vs-BC
    n_snap = 6 if args.quick else max(1, int(args.snapshots))
    snapshots: List[EngineForwardModel] = []
    for i in range(n_snap):
        try:
            snapshots.append(build_snapshot(
                num_players=8, seed=args.seed + 1000 + i,
                target_turn=args.target_turn))
        except Exception as exc:  # noqa: BLE001
            report.setdefault("errors", []).append(
                f"svb snapshot {i}: {type(exc).__name__}: {exc}")
    svb = search_vs_bc(snapshots, evaluator, sims=8,
                       macro_candidates=args.macro_candidates,
                       seed=args.seed, use_bc_first=True, with_rows=True)
    svb_ctrl = search_vs_bc(snapshots, evaluator, sims=8,
                            macro_candidates=args.macro_candidates,
                            seed=args.seed, use_bc_first=False, with_rows=False)
    report["search_vs_bc"] = svb
    report["search_vs_bc_control_no_bc_macro"] = svb_ctrl
    gain_n = max(1, min(int(args.gain_snapshots), len(snapshots)))
    try:
        report["search_gain_analysis"] = search_gain_analysis(
            snapshots[:gain_n], evaluator,
            macro_candidates=args.macro_candidates)
    except Exception as exc:  # noqa: BLE001
        report.setdefault("errors", []).append(
            f"gain analysis: {type(exc).__name__}: {exc}")
    report["thresholds"] = evaluate_thresholds(
        perf, search, clone_p50_limit_ms=args.clone_p50_limit,
        clone_p90_limit_ms=args.clone_p90_limit)
    report["elapsed_s"] = round(time.perf_counter() - t_start, 2)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    # 独立 svb 报告（便于分析；含默认 + 对照）
    svb_path = out_path.with_name("phase1_search_vs_bc.json")
    svb_path.write_text(
        json.dumps({"with_bc_first_macro": svb,
                    "without_bc_first_macro": svb_ctrl},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    # 摘要打印
    print(f"bench -> {out_path} ({report['elapsed_s']}s)")
    print("perf:",
          {k: round(v.get("p50", v), 3) if isinstance(v, dict) else v
           for k, v in perf.items()
           if k.endswith("_ms") or k.endswith("_1000_ms")})
    for n, d in search["levels"].items():
        print(f"  N={n}: p50={d['ms_per_decision']['p50']:.1f}ms "
              f"p90={d['ms_per_decision']['p90']:.1f}ms")
    print("determinism:", search["determinism"])
    print("legality:", search["legality"])
    for name, block in (("svb(bc-first)", svb), ("svb(no-bc-macro)", svb_ctrl)):
        print(name + ":",
              {k: block[k] for k in ("n_snapshots", "agreement", "n_agree",
                                     "mean_search_best_leaf_value",
                                     "mean_root_prior_entropy")})
    gain = report.get("search_gain_analysis")
    if gain:
        for mode, agg in gain.get("modes", {}).items():
            print(f"gain[{mode}]: n={agg['n_used']} "
                  f"seed_stable={agg['frac_seed_stable_N8']:.2f} "
                  f"chg_1->8={agg['frac_changed_1_to_8']:.2f} "
                  f"chg_8->32={agg['frac_changed_8_to_32']:.2f}")
            for n in gain["sims_list"]:
                d = agg[str(n)]
                print(f"   N={n}: ms={d['mean_ms']:.1f} "
                      f"q_spread={d['mean_q_spread']:.3f} "
                      f"entropy={d['mean_pi_entropy']:.3f} "
                      f"prior_top={d['frac_picked_prior_top']:.2f}")
    print("thresholds:", report["thresholds"])
    return 0 if report["thresholds"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
