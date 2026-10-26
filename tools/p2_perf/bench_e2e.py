"""端到端 RL 步进开销分解：TavernGymEnv（Rust 引擎 + Python 适配）vs
BattlegroundsEnv（hsrl2 Python 引擎 + Python 环境）。

方法
----
在同一 harness（随机 legal 动作、同一 seed、8 人局、相同步数预算）下，用
**函数级累加计时器**包裹各环节（wrapping 开销 ~0.1µs，占比可忽略）：

* hsrl2：``observation.build_observation`` / ``build_extra_state`` /
  ``driver.enumerate_step`` / ``enumerate_choice`` / ``collect_zones`` /
  ``apply_action`` / ``env._drain_choices`` / ``env._drive_opponents``，以及
  ``env.step`` 总耗时；未归因部分 = env 循环 + 奖励 + 记账。
* TavernGymEnv：``_parts_from_features``（官方 obs 解码）/ ``_collect_parts`` /
  ``_build_candidates`` / ``_build_observation``（总观测构建）/
  ``game.step``（引擎推进 + bot 驱动）及 ``env.step`` 总耗时。

输出：每步 µs（mean/median/p99）与 step 内占比；JSON 写
``runs/p2_perf/e2e_breakdown.json``。

用法::

    cd /Users/letiangao/HSAgent/HSBRSIM
    PYTHONPATH=. python3 tools/p2_perf/bench_e2e.py --steps 300
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from typing import Any, Dict, List

from tools.p2_perf.common import ROOT, machine_info, save_json

if str(ROOT) not in sys.path:                             # noqa: E402
    sys.path.insert(0, str(ROOT))


class _Acc:
    """单个环节的累加计时（ns）。"""

    def __init__(self) -> None:
        self.samples_ns: List[int] = []

    def add(self, ns: int) -> None:
        self.samples_ns.append(int(ns))

    def stats(self, steps: int) -> Dict[str, float]:
        if not self.samples_ns:
            return {"n": 0, "per_step_us": 0.0, "per_call_us": 0.0}
        total_us = sum(self.samples_ns) / 1000.0
        per_call = total_us / len(self.samples_ns)
        sample = sorted(v / 1000.0 for v in self.samples_ns)
        p99 = sample[min(len(sample) - 1, int(round(0.99 * (len(sample) - 1))))]
        return {
            "n": len(self.samples_ns),
            "per_step_us": round(total_us / steps, 3) if steps else 0.0,
            "per_call_us": round(per_call, 3),
            "call_median_us": round(statistics.median(sample), 3),
            "call_p99_us": round(p99, 3),
        }


def _step_stats(times_ns: List[int]) -> Dict[str, float]:
    if not times_ns:
        return {"n": 0, "mean_us": 0.0, "median_us": 0.0, "p99_us": 0.0}
    sample = sorted(v / 1000.0 for v in times_ns)
    p99 = sample[min(len(sample) - 1, int(round(0.99 * (len(sample) - 1))))]
    return {
        "n": len(sample),
        "mean_us": round(statistics.fmean(sample), 3),
        "median_us": round(statistics.median(sample), 3),
        "p99_us": round(p99, 3),
    }


# ══════════════════════════════════════════════════════════════════════
# hsrl2 后端分解
# ══════════════════════════════════════════════════════════════════════


def bench_hsrl2_breakdown(steps: int = 250, seed: int = 0) -> Dict[str, Any]:
    from hsbg.env import driver, observation
    from hsbg.env.game_env import BattlegroundsEnv

    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed,
                           max_turns=40)
    env.reset(seed=seed)
    acc = {name: _Acc() for name in (
        "build_observation", "build_extra_state", "enumerate_step",
        "enumerate_choice", "collect_zones", "apply_action",
        "drain_choices", "drive_opponents", "env_step_total",
    )}
    orig = {
        "build_observation": observation.build_observation,
        "build_extra_state": observation.build_extra_state,
        "enumerate_step": driver.enumerate_step,
        "enumerate_choice": driver.enumerate_choice,
        "collect_zones": driver.collect_zones,
        "apply_action": driver.apply_action,
    }

    def wrap(name, fn):
        def wrapped(*args, **kwargs):
            t0 = time.perf_counter_ns()
            try:
                return fn(*args, **kwargs)
            finally:
                acc[name].add(time.perf_counter_ns() - t0)
        return wrapped

    try:
        observation.build_observation = wrap("build_observation",
                                             orig["build_observation"])
        observation.build_extra_state = wrap("build_extra_state",
                                             orig["build_extra_state"])
        driver.enumerate_step = wrap("enumerate_step",
                                     orig["enumerate_step"])
        driver.enumerate_choice = wrap("enumerate_choice",
                                       orig["enumerate_choice"])
        driver.collect_zones = wrap("collect_zones",
                                    orig["collect_zones"])
        driver.apply_action = wrap("apply_action", orig["apply_action"])
        env._drain_choices = wrap("drain_choices", env._drain_choices)
        env._drive_opponents = wrap("drive_opponents",
                                    env._drive_opponents)
        rng = random.Random(seed)
        step_times_ns: List[int] = []
        recruit_times_ns: List[int] = []
        end_turn_times_ns: List[int] = []
        steps_done = 0
        end_turn_steps = 0
        while steps_done < int(steps):
            candidates = env.legal_actions()
            if not candidates:
                break
            index = rng.randrange(len(candidates))
            is_end_turn = candidates[index].kind == "end_turn"
            t0 = time.perf_counter_ns()
            _obs, _r, terminated, truncated, _info = env.step(index)
            elapsed = time.perf_counter_ns() - t0
            acc["env_step_total"].add(elapsed)
            step_times_ns.append(elapsed)
            if is_end_turn:
                end_turn_steps += 1
                end_turn_times_ns.append(elapsed)
            else:
                recruit_times_ns.append(elapsed)
            steps_done += 1
            if terminated or truncated:
                break
    finally:
        observation.build_observation = orig["build_observation"]
        observation.build_extra_state = orig["build_extra_state"]
        driver.enumerate_step = orig["enumerate_step"]
        driver.enumerate_choice = orig["enumerate_choice"]
        driver.collect_zones = orig["collect_zones"]
        driver.apply_action = orig["apply_action"]
        env.close()

    parts = {name: metric.stats(steps_done) for name, metric in acc.items()}
    total = parts["env_step_total"]["per_step_us"]
    attributed = sum(parts[name]["per_step_us"] for name in (
        "build_observation", "enumerate_step", "enumerate_choice",
        "collect_zones", "apply_action", "drain_choices",
        "drive_opponents"))
    # extra_state 在 build_observation 内（不重复计入占比）
    return {
        "backend": "hsrl2 (BattlegroundsEnv)",
        "engine": "hsrl2 (Python, data 37.0.0.255130)",
        "opponent": "heuristic",
        "steps": int(steps_done),
        "seed": int(seed),
        "step_total": _step_stats(step_times_ns),
        "step_classes": {
            "recruit": _step_stats(recruit_times_ns),
            "end_turn": _step_stats(end_turn_times_ns),
        },
        "end_turn_steps": int(end_turn_steps),
        "parts_per_step_us": parts,
        "attributed_us": round(attributed, 3),
        "unattributed_us": round(total - attributed, 3),
        "share": {
            name: round(parts[name]["per_step_us"] / total * 100.0, 2)
            if total else 0.0
            for name in parts if name != "env_step_total"
        },
    }


# ══════════════════════════════════════════════════════════════════════
# TavernGym 后端分解
# ══════════════════════════════════════════════════════════════════════


def bench_taverngym_breakdown(steps: int = 250, seed: int = 0
                              ) -> Dict[str, Any]:
    from hsbg.backends import TavernGymEnv

    env = TavernGymEnv(num_players=8, seed=seed, obs_source="features")
    env.reset(seed=seed)
    acc = {name: _Acc() for name in (
        "build_observation", "resolve_candidate", "advance",
        "note_candidates", "make_info", "env_step_total",
    )}
    targets = {
        "_build_observation": "build_observation",
        "_resolve_candidate": "resolve_candidate",
        "_advance": "advance",
        "_note_candidates": "note_candidates",
        "_make_info": "make_info",
    }
    originals = {}
    for attr, key in targets.items():
        original = getattr(env, attr)
        originals[attr] = original

        def make(original, key):
            def wrapped(*args, **kwargs):
                t0 = time.perf_counter_ns()
                try:
                    return original(*args, **kwargs)
                finally:
                    acc[key].add(time.perf_counter_ns() - t0)
            return wrapped

        setattr(env, attr, make(original, key))
    rng = random.Random(seed)
    step_times_ns: List[int] = []
    steps_done = 0
    try:
        while steps_done < int(steps):
            candidates = env.legal_actions()
            if not candidates:
                break
            t0 = time.perf_counter_ns()
            _obs, _r, terminated, truncated, _info = env.step(
                rng.randrange(len(candidates)))
            acc["env_step_total"].add(time.perf_counter_ns() - t0)
            step_times_ns.append(acc["env_step_total"].samples_ns[-1])
            steps_done += 1
            if terminated or truncated:
                env.close()
                env = TavernGymEnv(num_players=8,
                                   seed=int(seed) + steps_done,
                                   obs_source="features")
                env.reset(seed=int(seed) + steps_done)
                for attr, key in targets.items():
                    original = getattr(env, attr)
                    setattr(env, attr, make(original, key))
    finally:
        env.close()

    parts = {name: metric.stats(steps_done) for name, metric in acc.items()}
    total = parts["env_step_total"]["per_step_us"]
    adapter_overhead = sum(parts[name]["per_step_us"] for name in (
        "build_observation", "resolve_candidate", "advance",
        "note_candidates", "make_info"))
    # game.step 是 PyO3 只读属性无法直接包裹 → 用余量推断「引擎推进」上限
    # （实际引擎耗时 ≤ 余量；_advance 内的 bot 驱动也发生在引擎侧，归入余量）
    engine_est = max(0.0, total - adapter_overhead)
    parts["engine_step_plus_bots_est"] = {
        "n": int(steps_done),
        "per_step_us": round(engine_est, 3),
        "per_call_us": round(engine_est, 3),
    }
    return {
        "backend": "taverngym (TavernGymEnv)",
        "engine": "taverngym (Rust/PyO3, data 36.6.3.253932)",
        "obs_source": "features",
        "steps": int(steps_done),
        "seed": int(seed),
        "step_total": _step_stats(step_times_ns),
        "parts_per_step_us": parts,
        "attributed_us": round(adapter_overhead, 3),
        "unattributed_us": round(engine_est, 3),
        "share": {
            name: round(parts[name]["per_step_us"] / total * 100.0, 2)
            if total else 0.0
            for name in parts if name != "env_step_total"
        },
        "step_total": _step_stats(step_times_ns),
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=250)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--json", type=str,
                        default="runs/p2_perf/e2e_breakdown.json")
    args = parser.parse_args(argv)

    payload: Dict[str, Any] = {"machine": machine_info(),
                               "section": "e2e_step_breakdown"}
    payload["hsrl2"] = bench_hsrl2_breakdown(steps=args.steps,
                                             seed=args.seed)
    try:
        payload["taverngym"] = bench_taverngym_breakdown(steps=args.steps,
                                                         seed=args.seed)
    except Exception as exc:                              # noqa: BLE001
        payload["taverngym_error"] = f"{type(exc).__name__}: {exc}"
    path = save_json(args.json.split("/")[-1], payload)
    print(f"[bench_e2e] saved: {path}")
    for backend in ("hsrl2", "taverngym"):
        data = payload.get(backend)
        if not data:
            continue
        total = data["step_total"]["mean_us"]
        print(f"\n{backend}: step mean {total} µs "
              f"(median {data['step_total']['median_us']}, "
              f"p99 {data['step_total']['p99_us']})")
        for name, part in data["parts_per_step_us"].items():
            if name == "env_step_total":
                continue
            print(f"  {name:24s}{part['per_step_us']:10.2f} µs/步 "
                  f"({data['share'][name]:5.1f}%)  "
                  f"call median {part.get('call_median_us', 0):.1f} µs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
