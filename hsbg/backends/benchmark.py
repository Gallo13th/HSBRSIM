"""后端吞吐基准：``hsrl2``（默认后端）vs ``taverngym``（参照后端）。

用法::

    # 两个后端各跑 5 局（random 策略），并跑引擎/观测微基准
    python3 -m hsbg.backends.benchmark --games 5 --seed 0

    # 只测 taverngym，且用 view 观测源；结果写 JSON
    python3 -m hsbg.backends.benchmark --backends taverngym \
        --obs-source view --games 3 --json runs/backends/bench_view.json

指标
----
* **端到端**（``run_episode``，含 reset + 观测构建 + 对手驱动）：
  games/s、steps/s、ms/局、ms/步、平均步数/回合、名次分布、非法动作数；
* **引擎裸吞吐**（taverngym only）：``run_bot_games``（8 座全 bot）games/s；
* **观测构建微基准**（taverngym only）：mask 获取、``observe()`` 官方观测解码、
  ``view()`` JSON（序列化+解析）的每步耗时；
* **hsrl2 基线**：``BattlegroundsEnv(opponent="heuristic")`` + 同一 random
  策略与同一批种子（公平对照：两者策略随机源相同）。

注意
----
* 本基准的随机器是 ``random.Random(seed)``，同 seed 两次运行结果完全一致；
* 数字随机器/负载波动，文档中的数字来自一次实测（macOS Apple Silicon）；
* 跑之前建议确认没有其它重负载进程，并记录 ``--games`` 与策略。
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from hsbg.rl.api import run_episode
from hsbg.rl.policies import make_policy

#: 默认基准局数
DEFAULT_GAMES = 5
#: hsrl2 后端单局步数上限（与 hsbg.env.spec.EnvConfig.max_steps 一致）
HSRL2_MAX_STEPS = 4000
#: taverngym 后端单局步数上限
TAVERNGYM_MAX_STEPS = 2000


# ══════════════════════════════════════════════════════════════════════
# 通用工具
# ══════════════════════════════════════════════════════════════════════


def _machine_info() -> Dict[str, Any]:
    """机器 / 解释器信息（写进基准 JSON，便于横向对比）。"""
    info: Dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version.split()[0],
        "cpu_count": _cpu_count(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        import taverngym  # noqa: F401

        info["taverngym_version"] = str(taverngym.version())
        info["taverngym_game_version"] = str(taverngym.game_version())
        info["taverngym_server_rules_version"] = str(
            taverngym.server_rules_version())
        info["taverngym_profile"] = str(taverngym.build_info().get("profile"))
        info["taverngym_source_hash"] = str(
            taverngym.build_info().get("source_hash"))
    except Exception as exc:  # noqa: BLE001 - 未安装时基准只跑 hsrl2
        info["taverngym_error"] = f"{type(exc).__name__}: {exc}"
    return info


def _cpu_count() -> int:
    try:
        import os

        return int(os.cpu_count() or 0)
    except Exception:  # pragma: no cover
        return 0


def _summarize_records(records: Sequence[Any], wall_seconds: float) -> Dict[str, Any]:
    """把若干 ``EpisodeRecord`` 汇总成基准指标（games/s、ms/步等）。"""
    n = len(records)
    steps = sum(int(r.steps) for r in records)
    turns = sum(int(r.turns) for r in records)
    ranks = [int(r.rank) for r in records]
    invalid = sum(int(r.invalid_actions) for r in records)
    truncated = sum(1 for r in records if r.truncated)
    errors = sum(1 for r in records if r.error)
    return {
        "episodes": n,
        "wall_seconds": round(float(wall_seconds), 6),
        "games_per_second": round(n / wall_seconds, 4) if wall_seconds > 0 else 0.0,
        "steps_total": int(steps),
        "turns_total": int(turns),
        "steps_per_second": round(steps / wall_seconds, 2) if wall_seconds > 0 else 0.0,
        "ms_per_game": round(wall_seconds / n * 1000.0, 3) if n else 0.0,
        "ms_per_step": round(wall_seconds / steps * 1000.0, 4) if steps else 0.0,
        "mean_steps": round(statistics.fmean(r.steps for r in records), 3) if n else 0.0,
        "mean_turns": round(statistics.fmean(r.turns for r in records), 3) if n else 0.0,
        "mean_rank": round(statistics.fmean(ranks), 4) if ranks else 0.0,
        "ranks": ranks,
        "invalid_actions": int(invalid),
        "truncated": int(truncated),
        "errors": int(errors),
    }


def _new_policy(name: str, seed: int) -> Any:
    return make_policy(name, seed=seed)


# ══════════════════════════════════════════════════════════════════════
# 端到端：hsrl2 后端
# ══════════════════════════════════════════════════════════════════════


def bench_hsrl2(
    games: int = DEFAULT_GAMES,
    seed: int = 0,
    policy: str = "random",
    *,
    opponent: str = "heuristic",
    num_players: int = 8,
) -> Dict[str, Any]:
    """``hsbg.env.BattlegroundsEnv``（hsrl2 引擎）端到端吞吐。"""
    from hsbg.env import BattlegroundsEnv

    seeds = [int(seed) + k for k in range(int(games))]
    records: List[Any] = []
    wall = 0.0
    for ep, ep_seed in enumerate(seeds):
        env = BattlegroundsEnv(
            num_players=int(num_players), opponent=str(opponent),
            seed=int(ep_seed))
        policy_impl = _new_policy(policy, ep_seed)
        t0 = time.perf_counter()
        rec = run_episode(
            env, policy_impl, seed=int(ep_seed), episode_id=ep,
            max_steps=HSRL2_MAX_STEPS)
        wall += time.perf_counter() - t0
        env.close()
        records.append(rec)
    out = {
        "backend": "hsrl2",
        "env": "hsbg.env.BattlegroundsEnv",
        "engine": "hsrl2 (vendored, data 37.0.0.255130)",
        "opponent": str(opponent),
        "policy": str(policy),
        "num_players": int(num_players),
        "max_steps": HSRL2_MAX_STEPS,
        "seeds": seeds,
    }
    out.update(_summarize_records(records, wall))
    return out


# ══════════════════════════════════════════════════════════════════════
# 端到端：taverngym 后端
# ══════════════════════════════════════════════════════════════════════


def bench_taverngym(
    games: int = DEFAULT_GAMES,
    seed: int = 0,
    policy: str = "random",
    *,
    obs_source: str = "features",
    num_players: int = 8,
) -> Dict[str, Any]:
    """``hsbg.backends.TavernGymEnv`` 端到端吞吐。"""
    from hsbg.backends import TavernGymEnv

    seeds = [int(seed) + k for k in range(int(games))]
    records: List[Any] = []
    wall = 0.0
    for ep, ep_seed in enumerate(seeds):
        env = TavernGymEnv(num_players=int(num_players), seed=int(ep_seed),
                           obs_source=str(obs_source))
        policy_impl = _new_policy(policy, ep_seed)
        t0 = time.perf_counter()
        rec = run_episode(
            env, policy_impl, seed=int(ep_seed), episode_id=ep,
            max_steps=TAVERNGYM_MAX_STEPS)
        wall += time.perf_counter() - t0
        env.close()
        records.append(rec)
    out = {
        "backend": "taverngym",
        "env": "hsbg.backends.TavernGymEnv",
        "engine": "taverngym (AutoTavern Rust, data 36.6.3.253932)",
        "policy": str(policy),
        "obs_source": str(obs_source),
        "num_players": int(num_players),
        "max_steps": TAVERNGYM_MAX_STEPS,
        "seeds": seeds,
    }
    out.update(_summarize_records(records, wall))
    return out


# ══════════════════════════════════════════════════════════════════════
# 引擎 / 观测微基准（taverngym only）
# ══════════════════════════════════════════════════════════════════════


def bench_taverngym_engine(games: int = 200, seed: int = 0) -> Dict[str, Any]:
    """引擎裸吞吐：``taverngym.run_bot_games``（8 座全 bot，C 侧执行）。"""
    import taverngym

    n = int(games)
    t0 = time.perf_counter()
    turns = taverngym.run_bot_games(n, seed=int(seed))
    wall = time.perf_counter() - t0
    return {
        "what": "taverngym.run_bot_games（8 座全 bot）",
        "games": n,
        "wall_seconds": round(wall, 6),
        "games_per_second": round(n / wall, 3) if wall > 0 else 0.0,
        "ms_per_game": round(wall / n * 1000.0, 4) if n else 0.0,
        "mean_turns": round(statistics.fmean(turns), 3) if turns else 0.0,
        "seed": int(seed),
    }


def bench_taverngym_micro(
    steps: int = 200, seed: int = 3
) -> Dict[str, Any]:
    """观测/动作微基准：mask、官方 obs 解码、view JSON、单步引擎推进。

    在**同一局**里逐步采样随机 legal 动作，分别计时：
    * ``legal_mask``：``Game.legal_mask(seat)``（bytes）；
    * ``features_decode``：``Game.observe(seat)`` + 本适配器 features 解码；
    * ``view_json``：``Game.view(seat)`` + ``json.loads``（调试视图）；
    * ``engine_step``：``Game.step`` + 对手 bot 推进（不含观测构建）。
    """
    from hsbg.backends.taverngym_env import TavernGymEnv

    env = TavernGymEnv(seed=int(seed), obs_source="features")
    env.reset(seed=int(seed))
    tg = env.game
    rng = __import__("random").Random(int(seed))
    timings = {"legal_mask_us": [], "features_decode_us": [],
               "view_json_us": [], "engine_step_us": []}
    steps_done = 0
    while steps_done < int(steps) and env.current_observation.candidates:
        seat = env.agent_index
        # 1) mask
        t0 = time.perf_counter()
        mask = tg.legal_mask(seat)
        timings["legal_mask_us"].append((time.perf_counter() - t0) * 1e6)
        legal = [i for i, b in enumerate(mask) if b]
        if not legal:
            break
        flat = rng.choice(legal)
        # 2) features 解码（直接调用适配器内部方法，避免重复构建完整 obs 的额外项）
        t0 = time.perf_counter()
        env._parts_from_features()   # noqa: SLF001 - 基准内部路径
        timings["features_decode_us"].append((time.perf_counter() - t0) * 1e6)
        # 3) view JSON
        t0 = time.perf_counter()
        json.loads(tg.view(seat))
        timings["view_json_us"].append((time.perf_counter() - t0) * 1e6)
        # 4) 单步引擎推进（用候选下标，走适配器 step 以包含 bot 推进）
        idx = env._flat_indices.index(int(flat))  # noqa: SLF001
        t0 = time.perf_counter()
        obs, _r, term, trunc, _info = env.step(idx)
        timings["engine_step_us"].append((time.perf_counter() - t0) * 1e6)
        steps_done += 1
        if term or trunc:
            env = TavernGymEnv(seed=int(seed) + steps_done, obs_source="features")
            env.reset(seed=int(seed) + steps_done)
            tg = env.game
    env.close()
    out: Dict[str, Any] = {"what": "taverngym 观测/动作微基准（单局随机动作）",
                           "steps": steps_done, "seed": int(seed)}
    for key, values in timings.items():
        if not values:
            out[key] = {"mean_us": 0.0, "median_us": 0.0}
            continue
        out[key] = {
            "mean_us": round(statistics.fmean(values), 3),
            "median_us": round(statistics.median(values), 3),
            "p95_us": round(sorted(values)[int(0.95 * (len(values) - 1))], 3),
        }
    return out


# ══════════════════════════════════════════════════════════════════════
# 汇总 / CLI
# ══════════════════════════════════════════════════════════════════════


def run_benchmarks(
    *,
    games: int = DEFAULT_GAMES,
    seed: int = 0,
    policy: str = "random",
    backends: Sequence[str] = ("hsrl2", "taverngym"),
    obs_sources: Sequence[str] = ("features", "view"),
    engine_games: int = 200,
    micro_steps: int = 200,
) -> Dict[str, Any]:
    """跑完整基准并返回可 JSON 化的结果字典。"""
    result: Dict[str, Any] = {
        "machine": _machine_info(),
        "config": {
            "games": int(games), "seed": int(seed), "policy": str(policy),
            "backends": list(backends), "obs_sources": list(obs_sources),
            "engine_games": int(engine_games), "micro_steps": int(micro_steps),
        },
    }
    if "hsrl2" in backends:
        result["hsrl2"] = bench_hsrl2(games=games, seed=seed, policy=policy)
    if "taverngym" in backends:
        result["taverngym"] = {
            "features": bench_taverngym(
                games=games, seed=seed, policy=policy, obs_source="features"),
        }
        if "view" in obs_sources:
            result["taverngym"]["view"] = bench_taverngym(
                games=max(1, min(int(games), 3)), seed=seed,
                policy=policy, obs_source="view")
        result["taverngym_engine"] = bench_taverngym_engine(
            games=engine_games, seed=seed)
        result["taverngym_micro"] = bench_taverngym_micro(
            steps=micro_steps, seed=seed + 3)
    return result


def format_report(result: Dict[str, Any]) -> str:
    """把基准结果格式化成 Markdown 表格（贴进文档用）。"""
    lines: List[str] = []
    machine = result.get("machine") or {}
    lines.append("### 基准环境")
    lines.append("")
    lines.append(f"- 机器：{machine.get('platform')} / {machine.get('machine')} "
                 f"({machine.get('cpu_count')} CPU)")
    lines.append(f"- Python：{machine.get('python')}")
    if "taverngym_version" in machine:
        lines.append(
            f"- taverngym：{machine.get('taverngym_version')} "
            f"(game {machine.get('taverngym_game_version')}, "
            f"profile {machine.get('taverngym_profile')})")
    lines.append("")
    lines.append("| 后端 | 策略 | 观测源 | 局数 | games/s | steps/s | "
                 "ms/局 | ms/步 | 平均步/局 | 平均回合 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    rows: List[Dict[str, Any]] = []
    if "hsrl2" in result:
        rows.append(result["hsrl2"])
    tg = result.get("taverngym") or {}
    for source in ("features", "view"):
        if source in tg:
            rows.append(tg[source])
    for row in rows:
        lines.append(
            f"| {row.get('backend')} | {row.get('policy')} | "
            f"{row.get('obs_source', '-')} | {row.get('episodes')} | "
            f"{row.get('games_per_second')} | {row.get('steps_per_second')} | "
            f"{row.get('ms_per_game')} | {row.get('ms_per_step')} | "
            f"{row.get('mean_steps')} | {row.get('mean_turns')} |")
    engine = result.get("taverngym_engine")
    if engine:
        lines.append("")
        lines.append("### 引擎裸吞吐（无观测/策略开销）")
        lines.append("")
        lines.append(f"- {engine['what']}：{engine['games_per_second']} games/s，"
                     f"{engine['ms_per_game']} ms/局（seed={engine['seed']}，"
                     f"平均 {engine['mean_turns']} 回合）")
    micro = result.get("taverngym_micro")
    if micro:
        lines.append("")
        lines.append("### 观测/动作微基准（taverngym，单局随机动作）")
        lines.append("")
        lines.append("| 项目 | mean µs | median µs | p95 µs |")
        lines.append("|---|---|---|---|")
        for key in ("legal_mask_us", "features_decode_us", "view_json_us",
                    "engine_step_us"):
            item = micro.get(key) or {}
            lines.append(f"| {key} | {item.get('mean_us')} | "
                         f"{item.get('median_us')} | {item.get('p95_us')} |")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="HSBRSIM 后端吞吐基准（hsrl2 vs taverngym）")
    parser.add_argument("--games", type=int, default=DEFAULT_GAMES,
                        help=f"端到端基准局数（默认 {DEFAULT_GAMES}）")
    parser.add_argument("--seed", type=int, default=0, help="起始种子")
    parser.add_argument("--policy", type=str, default="random",
                        help="策略名（hsbg.rl.policies.make_policy）")
    parser.add_argument("--backends", type=str, default="hsrl2,taverngym",
                        help="逗号分隔：hsrl2,taverngym")
    parser.add_argument("--obs-source", type=str, default="features",
                        help="taverngym 观测源：features/view/both")
    parser.add_argument("--engine-games", type=int, default=200,
                        help="引擎裸吞吐局数（taverngym.run_bot_games）")
    parser.add_argument("--micro-steps", type=int, default=200,
                        help="观测微基准步数")
    parser.add_argument("--json", type=str, default="",
                        help="结果写入 JSON 路径（可选）")
    parser.add_argument("--quiet", action="store_true", help="不打印报告")
    args = parser.parse_args(argv)

    backends = tuple(s.strip() for s in args.backends.split(",") if s.strip())
    if args.obs_source == "both":
        obs_sources: Sequence[str] = ("features", "view")
    else:
        obs_sources = (args.obs_source,)
    result = run_benchmarks(
        games=int(args.games), seed=int(args.seed), policy=str(args.policy),
        backends=backends, obs_sources=obs_sources,
        engine_games=int(args.engine_games), micro_steps=int(args.micro_steps))
    if not args.quiet:
        print(format_report(result))
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        if not args.quiet:
            print(f"\n[benchmark] 结果已写入 {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
