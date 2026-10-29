#!/usr/bin/env python
"""计划搜索（AlphaZero 类）性能基准 v2：clone / forward / RNG / 战斗 / 搜索吞吐。

用法::

    python scripts/bench_planning.py
    python scripts/bench_planning.py --players 8 --turns 4 --repeats 7
    python scripts/bench_planning.py --json runs/planning_bench.json
    python scripts/bench_planning.py --sims 8,16,32,64 --endgame

输出（JSON 落盘 + 控制台摘要）：
- ``clone_early/clone_mid/clone_endgame``：fast vs deepcopy vs raw 的
  min/mean/median/p90/max、heap 增量、pickle 可用性；
- ``forward``：legal_actions / apply / end_recruit_phase / rollout / evaluate；
- ``combat``：战斗期 clone、``simulate_combat`` 无副作用成本与隔离校验；
- ``rng``：get_state/set_state/fork 成本与正确性；
- ``search_throughput``：N=8/16/32/64 浅层模拟（clone+1 动作+evaluate）吞吐；
- ``memory``：clone heap 增量 + 进程 RSS。

结论同步到 ``docs/ALGORITHM_RESEARCH.md`` §4.2 / §6.3。
"""

from __future__ import annotations

import argparse
import copy
import json
import pickle
import statistics
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsrl2.db import CardDB  # noqa: E402
from hsrl2.events import BEFORE_ATTACK, Listener  # noqa: E402
from hsrl2.game import Game  # noqa: E402
from hsrl2.hero import Hero  # noqa: E402

from hsbg.agents.base import choose_option_index  # noqa: E402
from hsbg.agents.heuristic import HeuristicPolicy  # noqa: E402
from hsbg.env import BattlegroundsEnv, driver  # noqa: E402
from hsbg.planning import model  # noqa: E402
from hsbg.planning import rng as planning_rng  # noqa: E402


# ══════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════


def _bench(fn: Callable[[], Any], repeats: int = 7) -> Dict[str, float]:
    """返回 min/mean/median/p90/max（毫秒）。"""
    times: List[float] = []
    for _ in range(max(1, repeats)):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000.0)
    times.sort()
    n = len(times)
    return {
        "min_ms": times[0],
        "mean_ms": statistics.fmean(times),
        "median_ms": times[n // 2],
        "p90_ms": times[min(n - 1, int(round(0.9 * (n - 1))))],
        "p99_ms": times[min(n - 1, int(round(0.99 * (n - 1))))],
        "max_ms": times[-1],
        "repeats": n,
    }


def _rss_mb() -> float:
    """当前进程 RSS（MB）；优先 psutil，Windows 回退 psapi，其它 -1。"""
    try:
        import psutil  # type: ignore
        return float(psutil.Process().memory_info().rss) / (1024 * 1024)
    except Exception:                                     # noqa: BLE001
        pass
    try:
        import ctypes
        import ctypes.wintypes as wt

        class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.windll.kernel32
        handle = ctypes.c_void_p(kernel.GetCurrentProcess())
        fn = kernel.K32GetProcessMemoryInfo
        fn.argtypes = [ctypes.c_void_p,
                       ctypes.POINTER(_PROCESS_MEMORY_COUNTERS), wt.DWORD]
        fn.restype = wt.BOOL
        if not fn(handle, ctypes.byref(counters), counters.cb):
            return -1.0
        return float(counters.WorkingSetSize) / (1024 * 1024)
    except Exception:                                     # noqa: BLE001
        return -1.0


def _heap_delta_kb(fn: Callable[[], Any]) -> float:
    tracemalloc.start()
    snap0 = tracemalloc.take_snapshot()
    keep = fn()
    snap1 = tracemalloc.take_snapshot()
    delta = sum(stat.size_diff for stat in snap1.compare_to(snap0, "lineno"))
    tracemalloc.stop()
    assert keep is not None
    return delta / 1024.0


def _env_game(players: int, turns: int, seed: int = 0):
    """推进到第 ``turns`` 回合（招募期）的真实对局。"""
    env = BattlegroundsEnv(num_players=players, opponent="heuristic",
                           seed=seed)
    obs = env.reset(seed=seed)
    policy = HeuristicPolicy()
    while int(env.game.turn) < turns:
        if obs.phase == "choice":
            action = obs.candidates[choose_option_index(policy, obs, env.game)]
        else:
            desc = policy.choose(env.game, env.agent_hero)
            if desc is None:
                idx = next(i for i, c in enumerate(obs.candidates)
                           if c.kind == "end_turn")
                action = obs.candidates[idx]
            else:
                action = desc.to_candidate()
        obs, _r, term, trunc, _i = env.step(action)
        if term or trunc:
            break
    return env, env.game


def _combat_game(db: CardDB, seed: int = 5):
    a, b = Hero("TEST_A", "A"), Hero("TEST_B", "B")
    game = Game([a, b], db, seed=seed)
    game.start_game()
    for h in (a, b):
        h.health, h.armor = 40, 0
        h.gold = 10
        game.refresh_tavern(h)
        for cid in ("BG25_001", "BGS_119", "BG25_008", "BG34_630t"):
            game.summon(h, game.create_minion(cid, controller=h))
    return game, a, b


# ══════════════════════════════════════════════════════════════════════
# 分项基准
# ══════════════════════════════════════════════════════════════════════


def bench_clone(game: Game, repeats: int, label: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "label": label,
        "turn": int(game.turn),
        "players": len(game.heroes),
        "entities": sum(len(h.board) + len(h.hand) + len(h.tavern)
                        for h in game.heroes),
        "fast_clone": _bench(lambda: model.clone(game), repeats),
        "deepcopy_clone": _bench(
            lambda: model.clone(game, strategy="deepcopy"),
            max(2, repeats // 2)),
        "raw_deepcopy": _bench(lambda: copy.deepcopy(game),
                               max(2, repeats // 2)),
        "fast_clone_rebind_off": _bench(
            lambda: model.clone(game, rebind=False),
            max(2, repeats // 2)),
    }
    try:
        out["pickle_roundtrip"] = _bench(
            lambda: pickle.loads(pickle.dumps(game, protocol=5)),
            max(1, repeats // 3))
    except Exception as exc:                              # noqa: BLE001
        out["pickle_roundtrip"] = {"available": False,
                                   "error": f"{type(exc).__name__}: {exc}"[:160]}
    out["clone_heap_kb"] = _heap_delta_kb(lambda: model.clone(game))
    return out


def bench_forward(game: Game, repeats: int) -> Dict[str, Any]:
    hero = game.heroes[0]
    out: Dict[str, Any] = {}
    out["legal_actions"] = _bench(
        lambda: driver.enumerate_actions(game, game.heroes[0]), repeats * 5)
    actions = driver.enumerate_actions(game, hero)
    kinds: Dict[str, Any] = {}
    for desc in actions:
        kinds.setdefault(desc.kind, desc)
    apply_out: Dict[str, Any] = {}
    for kind in ("buy", "play_minion", "play_spell", "reroll", "upgrade",
                 "end_turn"):
        probe = model.clone(game)
        target = next((d for d in driver.enumerate_actions(
            probe, probe.heroes[0]) if d.kind == kind), None)
        if target is None:
            apply_out[kind] = {"available": False}
            continue
        preps = [model.clone(game) for _ in range(repeats)]
        times: List[float] = []
        ok = True
        for dup in preps:
            sig = target.signature()
            desc = next((d for d in driver.enumerate_actions(
                dup, dup.heroes[0]) if d.to_candidate().signature() == sig),
                None)
            if desc is None:
                ok = False
                continue
            t0 = time.perf_counter()
            res = driver.apply_action(dup, dup.heroes[0], desc)
            times.append((time.perf_counter() - t0) * 1000.0)
            ok = ok and bool(res.success)
        apply_out[kind] = {"available": True,
                           "mean_ms": statistics.fmean(times) if times else -1.0,
                           "success": bool(ok)}
    out["apply"] = apply_out

    def _one_turn():
        dup = model.clone(game)
        dup.end_recruit_phase()
        driver.resolve_pending_choices(dup, None)

    out["end_recruit_phase"] = _bench(_one_turn, max(2, repeats // 2))

    rollout_times: List[float] = []
    samples: List[Dict[str, Any]] = []
    for i in range(repeats):
        dup = model.clone(game)
        t0 = time.perf_counter()
        res = model.random_rollout(
            dup, dup.heroes[0],
            model.RandomRolloutPolicy(seed=100 + i, end_turn_prob=0.6))
        rollout_times.append((time.perf_counter() - t0) * 1000.0)
        if len(samples) < 3:
            samples.append(res.as_dict())
    rollout_times.sort()
    n = len(rollout_times)
    out["rollout_1turn"] = {
        "min_ms": rollout_times[0],
        "mean_ms": statistics.fmean(rollout_times),
        "median_ms": rollout_times[n // 2],
        "p90_ms": rollout_times[min(n - 1, int(round(0.9 * (n - 1))))],
        "max_ms": rollout_times[-1],
        "sample": samples,
    }
    out["evaluate"] = _bench(
        lambda: model.evaluate(game, game.heroes[0]), repeats * 10)
    # 快速叶价值 forward：只做战斗裁决（不初始化下一回合）
    out["simulate_turn_combat"] = _bench(
        lambda: model.simulate_turn_combat(game, game.heroes[0]),
        max(2, repeats // 2))
    return out


def _combat_signature(game: Game) -> tuple:
    heroes = tuple((h.card_id, int(h.health), int(h.armor),
                    tuple(m.card_id for m in h.board))
                   for h in game.heroes)
    return (int(game.turn), bool(game.finished), heroes,
            len(game.combat_death_log))


def bench_combat(db: CardDB, repeats: int) -> Dict[str, Any]:
    game, a, b = _combat_game(db)
    captured: Dict[str, Any] = {}

    def on_attack(g, **_kw):
        if "done" not in captured:
            captured["done"] = True
            captured["clone"] = _bench(lambda: model.clone(g),
                                       max(2, repeats // 2))
            captured["in_combat"] = bool(g.in_combat)
            captured["active"] = getattr(g, "_active_combat", None) is not None
        return None

    game.events.register(Listener(event=BEFORE_ATTACK, owner=a,
                                  callback=on_attack, once=True))
    t0 = time.perf_counter()
    game.run_combat(a, b, alive_count=8)
    combat_total = (time.perf_counter() - t0) * 1000.0

    game2, a2, b2 = _combat_game(db)
    sig_before = _combat_signature(game2)
    t0 = time.perf_counter()
    summary1, dup1 = model.simulate_combat(game2, a2, b2, alive_count=8)
    sim_ms = (time.perf_counter() - t0) * 1000.0
    sig_after = _combat_signature(game2)
    summary2, _dup2 = model.simulate_combat(game2, a2, b2, alive_count=8)
    return {
        "combat_total_ms": combat_total,
        "in_combat": captured.get("in_combat", False),
        "active_combat": captured.get("active", False),
        "combat_state_clone": captured.get("clone", {}),
        "simulate_combat_ms": sim_ms,
        "simulate_combat_repeatable": summary1 == summary2,
        "simulate_combat_no_side_effect": sig_before == sig_after,
        "simulate_combat_sample": {k: summary1[k] for k in
                                   ("winner", "loser", "capped_damage",
                                    "rounds", "finished")},
        "keep_state_is_clone": dup1 is not None and dup1 is not game2,
    }


def bench_rng(game: Game, repeats: int) -> Dict[str, Any]:
    rng = game.rng
    state = planning_rng.get_state(rng)
    f1 = planning_rng.fork(rng)
    f2 = planning_rng.fork(rng)
    draws1 = [f1.random() for _ in range(5)]
    draws2 = [f2.random() for _ in range(5)]
    target = planning_rng.fork(rng)
    st = planning_rng.get_state(target)
    planning_rng.set_state(target, st)
    return {
        "decisions": len(state["decisions"]),
        "get_state": _bench(lambda: planning_rng.get_state(rng),
                            repeats * 20),
        "set_state": _bench(lambda: planning_rng.set_state(
            planning_rng.fork(rng), state), repeats * 20),
        "fork": _bench(lambda: planning_rng.fork(rng), repeats * 20),
        "fork_same_state": planning_rng.state_equal(f1, f2),
        "fork_same_draws": draws1 == draws2,
        "set_state_roundtrip": planning_rng.state_equal(target, f1),
        "fork_seeded_decisions": len(
            planning_rng.fork(rng, seed=11).decisions),
    }


def bench_search_throughput(game: Game, sims_list: List[int],
                            repeats: int = 3) -> Dict[str, Any]:
    """浅层搜索吞吐：每个 sim = clone + 1 个随机动作 + evaluate。"""
    policy = model.RandomRolloutPolicy(seed=7)
    out: Dict[str, Any] = {}
    for sims in sims_list:
        times: List[float] = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            for _i in range(sims):
                dup = model.clone(game)
                actions = model.legal_actions(dup, dup.heroes[0])
                if actions:
                    model.apply(dup, dup.heroes[0],
                                actions[policy.rng.randint(0, len(actions) - 1)])
                model.evaluate(dup, dup.heroes[0])
            times.append((time.perf_counter() - t0) * 1000.0)
        mean = statistics.fmean(times)
        out[str(sims)] = {
            "total_ms": mean,
            "ms_per_sim": mean / sims,
            "sims_per_sec": 1000.0 / (mean / sims),
        }
    return out


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════


def bench_observation(game: Game, repeats: int) -> Dict[str, float]:
    """build_observation 成本（搜索节点重算 obs）。"""
    from hsbg.env import observation
    env_stub = None
    candidates = tuple(d.to_candidate() for d in
                       driver.enumerate_actions(game, game.heroes[0]))
    zones = driver.collect_zones(game, game.heroes[0])
    return _bench(lambda: observation.build_observation(
        game, game.heroes[0], candidates, zones=zones,
        lobby_heroes=list(game.heroes)), repeats * 5)


def bench_memory_leak(game: Game, clones: int = 100) -> Dict[str, float]:
    """连续 clone 的 RSS/堆增长（泄漏监测，单位 KB/次）。"""
    import gc
    rss0 = _rss_mb()
    heap0 = tracemalloc.get_traced_memory()[0] if tracemalloc.is_tracing() else 0
    for _ in range(clones):
        model.clone(game)
    gc.collect()
    rss1 = _rss_mb()
    return {
        "clones": clones,
        "rss_before_mb": rss0,
        "rss_after_mb": rss1,
        "rss_delta_kb": (rss1 - rss0) * 1024.0,
        "rss_per_clone_kb": ((rss1 - rss0) * 1024.0 / clones) if rss0 > 0 else -1.0,
    }


def bench_determinism(players: int, seeds: range, turns: int = 2) -> Dict[str, Any]:
    """clone 确定性抽样：同局面两份 clone 同动作序列 → digest/RNG 一致。"""
    from hsbg.planning.digest import digest
    ok = True
    samples = []
    for seed in seeds:
        env = BattlegroundsEnv(num_players=players, opponent="heuristic",
                               seed=seed)
        env.reset(seed=seed)
        _play_until_turn(env, turns)
        game = env.game
        a = model.clone(game)
        b = model.clone(game)
        policy = model.RandomRolloutPolicy(seed=1234)
        for _ in range(12):
            for dup in (a, b):
                acts = model.legal_actions(dup, dup.heroes[0])
                if not acts:
                    break
                model.apply(dup, dup.heroes[0],
                            acts[policy.rng.randint(0, len(acts) - 1)]
                            if False else acts[0])
                model.drain_choices(dup, dup.heroes[0])
        same = (digest(a) == digest(b)
                and a.rng._rng.getstate() == b.rng._rng.getstate())
        ok = ok and same
        samples.append({"seed": seed, "same": bool(same)})
        env.close()
    return {"all_same": bool(ok), "samples": samples}


def _play_until_turn(env, turns: int) -> Any:
    """用启发式推进到第 ``turns`` 回合（供确定性抽样用；同 _env_game）。"""
    obs = env._obs
    policy = HeuristicPolicy()
    while int(env.game.turn) < turns:
        if obs is None:
            obs = env.reset(seed=env.config.seed or 0)
        if obs.phase == "choice":
            action = obs.candidates[choose_option_index(policy, obs, env.game)]
        else:
            desc = policy.choose(env.game, env.agent_hero)
            if desc is None:
                idx = next(i for i, c in enumerate(obs.candidates)
                           if c.kind == "end_turn")
                action = obs.candidates[idx]
            else:
                action = desc.to_candidate()
        obs, _r, term, trunc, _i = env.step(action)
        if term or trunc:
            break
    return obs


def run(players: int = 8, turns: int = 4, repeats: int = 7,
        seed: int = 0, sims_list: Optional[List[int]] = None,
        include_endgame: bool = False) -> Dict[str, Any]:
    db = CardDB.load(str(ROOT / "data"))
    report: Dict[str, Any] = {
        "players": players, "turns": int(turns), "seed": seed,
        "repeats": repeats, "python": sys.version.split()[0],
        "rss_start_mb": _rss_mb(),
    }
    early_turn = 2
    mid_turn = max(2, int(turns))
    env1, game1 = _env_game(players, early_turn, seed=seed)
    env4, game4 = _env_game(players, mid_turn, seed=seed)
    report["clone_early"] = bench_clone(game1, repeats,
                                        f"{players}p-T{game1.turn}")
    report["clone_mid"] = bench_clone(game4, repeats,
                                      f"{players}p-T{game4.turn}")
    report["memory"] = {
        "clone_heap_kb": report["clone_mid"]["clone_heap_kb"],
        "rss_start_mb": _rss_mb(),
    }
    report["forward"] = bench_forward(game4, repeats)
    report["obs_build"] = bench_observation(game4, repeats)
    report["combat"] = bench_combat(db, repeats)
    report["rng"] = bench_rng(game4, repeats)
    report["memory"]["leak"] = bench_memory_leak(game4, clones=100)
    report["determinism"] = bench_determinism(
        players, range(0, 3), turns=min(3, mid_turn))
    report["search_throughput"] = bench_search_throughput(
        game4, sims_list or [8, 16, 32, 64], repeats=3)
    report["rss_end_mb"] = _rss_mb()
    if include_endgame:
        env8, game8 = _env_game(players, 8, seed=seed)
        if not game8.finished and int(game8.turn) >= 7:
            report["clone_endgame"] = bench_clone(
                game8, repeats, f"{players}p-T{game8.turn}")
        env8.close()

    fast_mid = report["clone_mid"]["fast_clone"]
    raw_mid = report["clone_mid"]["raw_deepcopy"]
    rng_cost = report["rng"]["fork"]["mean_ms"]
    report["feasibility"] = {
        "clone_p50_ms": fast_mid["median_ms"],
        "clone_p90_ms": fast_mid["p90_ms"],
        "clone_target_p90_le_2ms": fast_mid["p90_ms"] <= 2.0,
        "clone_speedup_vs_raw": raw_mid["mean_ms"] / max(1e-9, fast_mid["mean_ms"]),
        "clone_memory_kb": report["clone_mid"]["clone_heap_kb"],
        "rng_fork_ms": rng_cost,
        "rng_target_le_0_05ms": rng_cost <= 0.05,
        "sims_per_sec_32": report["search_throughput"].get(
            "32", {}).get("sims_per_sec", 0.0),
        "verdict": ("shallow search 可实时（N≤32）"
                    if fast_mid["p90_ms"] <= 2.0
                    else "clone 仍偏慢：建议 N≤16 或继续优化"),
    }
    env1.close()
    env4.close()
    return report


def _print_human(r: Dict[str, Any]) -> None:
    print("=" * 78)
    print(f"Planning benchmark v2  players={r['players']} "
          f"repeats={r['repeats']}  python={r['python']}")
    for key, label in (("clone_early", "clone @early"),
                       ("clone_mid", "clone @mid"),
                       ("clone_endgame", "clone @endgame")):
        d = r.get(key)
        if not d:
            continue
        f = d["fast_clone"]
        dc = d["deepcopy_clone"]
        raw = d["raw_deepcopy"]
        print("-" * 78)
        print(f"{label:16s} {d['label']:8s} entities={d['entities']:3d}")
        print(f"  fast clone       min={f['min_ms']:.2f} p50={f['median_ms']:.2f} "
              f"p90={f['p90_ms']:.2f} max={f['max_ms']:.2f} ms")
        print(f"  deepcopy clone   min={dc['min_ms']:.2f} p50={dc['median_ms']:.2f} "
              f"p90={dc['p90_ms']:.2f} max={dc['max_ms']:.2f} ms")
        print(f"  raw deepcopy     p50={raw['median_ms']:.2f} ms "
              f"(speedup x{raw['mean_ms'] / max(1e-9, f['mean_ms']):.1f})  "
              f"heap=+{d['clone_heap_kb']:.0f}KB")
        p = d.get("pickle_roundtrip")
        if isinstance(p, dict) and p.get("available") is not False:
            print(f"  pickle roundtrip p50={p['median_ms']:.2f} ms")
        elif isinstance(p, dict):
            print(f"  pickle            unavailable: {p.get('error', '')[:90]}")
    fw = r.get("forward", {})
    print("-" * 78)
    print(f"{'legal_actions':16s} p50={fw.get('legal_actions', {}).get('median_ms', 0):.3f} ms")
    for kind, d in fw.get("apply", {}).items():
        if d.get("available"):
            print(f"{'apply ' + kind:16s} mean={d['mean_ms']:.3f} ms success={d['success']}")
    print(f"{'end_recruit':16s} p50={fw.get('end_recruit_phase', {}).get('median_ms', 0):.2f} ms")
    print(f"{'rollout 1turn':16s} p50={fw.get('rollout_1turn', {}).get('median_ms', 0):.2f} ms")
    print(f"{'evaluate':16s} p50={fw.get('evaluate', {}).get('median_ms', 0):.3f} ms")
    print(f"{'turn_combat':16s} p50={fw.get('simulate_turn_combat', {}).get('median_ms', 0):.2f} ms"
          f"  (vs ERP p50={fw.get('end_recruit_phase', {}).get('median_ms', 0):.2f} ms)")
    comb = r.get("combat", {})
    print("-" * 78)
    print(f"combat state clone p50={comb.get('combat_state_clone', {}).get('median_ms', 0):.2f} ms "
          f"(in_combat={comb.get('in_combat')}, total={comb.get('combat_total_ms', 0):.1f} ms)")
    print(f"simulate_combat   {comb.get('simulate_combat_ms', 0):.2f} ms  "
          f"no_side_effect={comb.get('simulate_combat_no_side_effect')} "
          f"repeatable={comb.get('simulate_combat_repeatable')}")
    rng = r.get("rng", {})
    print("-" * 78)
    print(f"rng get/set/fork  "
          f"{rng.get('get_state', {}).get('mean_ms', 0)*1000:.2f}/"
          f"{rng.get('set_state', {}).get('mean_ms', 0)*1000:.2f}/"
          f"{rng.get('fork', {}).get('mean_ms', 0)*1000:.2f} us  "
          f"same_state={rng.get('fork_same_state')}")
    thr = r.get("search_throughput", {})
    if thr:
        print("-" * 78)
        for n in sorted(thr, key=lambda x: int(x)):
            d = thr[n]
            print(f"search N={n:>3s} sims: {d['total_ms']:7.1f} ms  "
                  f"{d['ms_per_sim']:.2f} ms/sim  {d['sims_per_sec']:6.0f} sims/s")
    feas = r.get("feasibility", {})
    print("-" * 78)
    print(f"clone p50={feas.get('clone_p50_ms', 0):.2f} ms  "
          f"p90={feas.get('clone_p90_ms', 0):.2f} ms  "
          f"heap={feas.get('clone_memory_kb', 0):.0f}KB  "
          f"speedup=x{feas.get('clone_speedup_vs_raw', 0):.1f}")
    print(f"rng fork={feas.get('rng_fork_ms', 0)*1000:.1f} us  "
          f"N=32 {feas.get('sims_per_sec_32', 0):.0f} sims/s  "
          f"RSS={r.get('rss_end_mb', -1):.1f}MB  | {feas.get('verdict')}")


def _print_multi_summary(agg: Dict[str, Any]) -> None:
    print("=" * 78)
    print("Planning benchmark v3（多人数汇总）")
    print(f"{'players':>7s} {'clone_p50':>9s} {'clone_p90':>9s} "
          f"{'clone_p99':>9s} {'ERP_p50':>8s} {'obs_p50':>8s} "
          f"{'combat_p50':>10s} {'sims/s(N32)':>11s}")
    for pl, sec in agg["sections"].items():
        mid = sec["clone_mid"]["fast_clone"]
        print(f"{pl:>7s} {mid['median_ms']:>8.2f}ms {mid['p90_ms']:>8.2f}ms "
              f"{mid.get('p99_ms', 0):>8.2f}ms "
              f"{sec['forward']['end_recruit_phase']['median_ms']:>7.2f}ms "
              f"{sec['obs_build']['median_ms']:>7.2f}ms "
              f"{sec['combat']['combat_state_clone'].get('median_ms', 0):>9.2f}ms "
              f"{sec['search_throughput'].get('32', {}).get('sims_per_sec', 0):>10.0f}")
    s = agg.get("summary", {})
    print("-" * 78)
    print(f"det (all seeds same): {s.get('determinism_all_same')}  "
          f"rng_fork_ms={s.get('rng_fork_ms', 0) * 1000:.1f}us  "
          f"leak_rss_per_clone_kb={s.get('leak_rss_per_clone_kb', 0):.2f}  "
          f"RSS={agg.get('rss_end_mb', -1):.1f}MB")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AlphaZero planning benchmark v3")
    ap.add_argument("--players", type=int, default=8,
                    help="单人数模式（--players-list 为空时使用）")
    ap.add_argument("--players-list", default="8,6,4,2",
                    help="多人数聚合（默认 8,6,4,2；空串=单人数模式）")
    ap.add_argument("--turns", type=int, default=4,
                    help="中期基准推进到第 N 回合（early 固定 T2）")
    ap.add_argument("--repeats", type=int, default=7)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sims", default="8,16,32,64",
                    help="搜索吞吐的 sims 列表，逗号分隔")
    ap.add_argument("--endgame", action="store_true",
                    help="额外测第 8 回合残局 clone")
    ap.add_argument("--json", default="runs/planning_bench.json")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    sims_list = [int(x) for x in args.sims.split(",") if x.strip()]
    players_list = [int(x) for x in args.players_list.split(",") if x.strip()]
    if not players_list:
        players_list = [args.players]
    sections: Dict[str, Any] = {}
    for players in players_list:
        if not args.quiet:
            print(f"\n>>> benchmarking players={players} ...")
        sections[str(players)] = run(
            players, args.turns, args.repeats, args.seed, sims_list,
            include_endgame=args.endgame)
    first = sections[str(players_list[0])]
    summary = {
        "clone_p50_ms": first["clone_mid"]["fast_clone"]["median_ms"],
        "clone_p90_ms": first["clone_mid"]["fast_clone"]["p90_ms"],
        "clone_p99_ms": first["clone_mid"]["fast_clone"].get("p99_ms", 0),
        "rng_fork_ms": first["rng"]["fork"]["mean_ms"],
        "leak_rss_per_clone_kb": first["memory"]["leak"].get(
            "rss_per_clone_kb", -1),
        "determinism_all_same": all(
            sec["determinism"]["all_same"] for sec in sections.values()),
        "players": players_list,
    }
    agg = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "python": sys.version.split()[0],
        "mode": "multi-players",
        "summary": summary,
        "sections": sections,
        "rss_end_mb": _rss_mb(),
    }
    if not args.quiet:
        if len(sections) == 1:
            _print_human(first)
        else:
            _print_multi_summary(agg)
    if args.json:
        p = Path(args.json)
        if not p.is_absolute():
            p = ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(agg, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        print(f"saved: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
