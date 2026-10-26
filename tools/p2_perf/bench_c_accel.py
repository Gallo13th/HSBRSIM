"""C 加速可行性微基准：真实 Python 热函数 vs Cython 编译版（纯 Python 模式）。

对象
----
从真实对局状态出发，对 3 个代表性热函数做 ≥1000 次微基准（median/p99）：

1. ``hsbg.env.observation.entity_token`` —— 观测实体 token 构建
   （step 内被调用 N 次：棋盘/手牌/酒馆/对手/选项）；
2. ``hsbg.env.observation.build_observation`` —— 整步观测构建
   （obs 构建 ≈ TavernGymEnv 端到端 78% 的大头，也是 hsrl2 step 的 ~30%）；
3. ``hsbg.planning.model.clone`` —— 引擎状态深拷贝（搜索/快照热路径）。

方法
----
把模块**原样复制**到 ``/tmp/p2_perf_cbuild/*.pyx`` 用 Cython（纯 Python
模式，无类型标注改动）编译 → 同输入对比纯 Python 版本；再尝试 mypyc
（记录成功/失败原因）。这样得到的是**"零改造成本"下的 C 加速上限**；
若要做「有类型/数据布局改造」的 C 扩展，需另算（见 docs/PERF_ROUTE.md §4）。

用法::

    cd /Users/letiangao/HSAgent/HSBRSIM
    PYTHONPATH=. python3 tools/p2_perf/bench_c_accel.py --iters 1000
    # 结果写入 runs/p2_perf/c_accel.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from tools.p2_perf.common import ROOT, machine_info, save_json, summarize

BUILD_DIR = Path("/tmp/p2_perf_cbuild")
CYTHON_TARGET = Path("/tmp/p2_perf_cython")
MODULES = {
    "observation": ROOT / "hsbg" / "env" / "observation.py",
    "model": ROOT / "hsbg" / "planning" / "model.py",
}


def _ensure_cython() -> Dict[str, Any]:
    """确保可 import Cython；缺失时 ``pip install --target /tmp``（不写项目依赖）。"""
    info: Dict[str, Any] = {"installed": False, "method": None, "error": None}
    try:
        import Cython
        info.update(installed=True, method="already-installed",
                    version=str(Cython.__version__))
        return info
    except ImportError:
        pass
    cmd = [sys.executable, "-m", "pip", "install", "--target",
           str(CYTHON_TARGET), "Cython"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        if out.returncode != 0:
            info["error"] = (out.stderr or out.stdout)[-800:]
            return info
        sys.path.insert(0, str(CYTHON_TARGET))
        import Cython
        info.update(installed=True, method=f"pip --target {CYTHON_TARGET}",
                    version=str(Cython.__version__))
    except Exception as exc:                              # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _prepare_cython_modules() -> Dict[str, Any]:
    """复制真实模块为 .pyx 并用 pyximport 编译（纯 Python 模式）。"""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    for name, path in MODULES.items():
        shutil.copyfile(path, BUILD_DIR / f"p2_{name}_cy.pyx")
        shutil.copyfile(path, BUILD_DIR / f"p2_{name}_cy.py")
    import pyximport
    pyximport.install(build_dir=str(BUILD_DIR), language_level=3,
                      inplace=False, reload_support=False)
    sys.path.insert(0, str(BUILD_DIR))
    return {"build_dir": str(BUILD_DIR)}


def _median_bench(fn: Callable[[], Any], iters: int,
                  warmup: int = 20) -> Dict[str, Any]:
    for _ in range(warmup):
        fn()
    samples: List[float] = []
    for _ in range(int(iters)):
        t0 = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - t0) / 1000.0)
    return summarize(samples)


def _speedup(py: Dict[str, Any], fast: Dict[str, Any]) -> float:
    median = float(fast.get("median_us") or 0.0)
    return round(float(py.get("median_us") or 0.0) / median, 2) if median else 0.0


def _try_mypyc() -> Dict[str, Any]:
    """尝试 mypyc 编译 observation.py 副本（记录结果；不强求成功）。"""
    info: Dict[str, Any] = {"attempted": True, "ok": False, "error": None}
    src = MODULES["observation"]
    target = BUILD_DIR / "p2_observation_mypyc.py"
    try:
        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        out = subprocess.run(
            [sys.executable, "-m", "mypyc", "--ignore-missing-imports",
             str(target)],
            capture_output=True, text=True, timeout=180,
            cwd=str(BUILD_DIR))
        info["returncode"] = out.returncode
        if out.returncode == 0:
            info["ok"] = True
        else:
            info["error"] = (out.stderr or out.stdout)[-1200:]
    except Exception as exc:                              # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _make_state(seed: int = 0, steps: int = 20) -> Tuple[Any, Any, List[Tuple[Any, Any]],
                                                          Dict[str, Any]]:
    """推进到中局，返回 (env, game, token 样本, build_observation kwargs)。"""
    from hsbg.env.game_env import BattlegroundsEnv

    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed,
                           max_turns=40)
    env.reset(seed=seed)
    for _ in range(int(steps)):
        candidates = env.legal_actions()
        if not candidates:
            break
        index = (len(candidates) - 1
                 if len(candidates) % 3 == 0 else 0)
        _obs, _r, terminated, truncated, _info = env.step(index)
        if terminated or truncated:
            break
    tokens: List[Tuple[Any, Any]] = []
    for hero in env.game.heroes:
        for entity in list(hero.board) + list(hero.hand) + list(hero.tavern):
            tokens.append((env.game, entity))
    step_actions = env._step_actions
    kwargs = {
        "game": env.game,
        "hero": env.agent_hero,
        "candidates": tuple(step_actions.candidates),
        "phase": "recruit",
        "pending": None,
        "zones": step_actions.zones,
        "lobby_heroes": env._all_heroes,
        "eliminated_rank": env._rank_by_hero,
        "total_players": 8,
        "turn": int(env.game.turn),
        "log": "bench",
    }
    return env, env.game, tokens, kwargs


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iters", type=int, default=1000)
    parser.add_argument("--clone-iters", type=int, default=400)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--json", type=str,
                        default="runs/p2_perf/c_accel.json")
    args = parser.parse_args(argv)

    payload: Dict[str, Any] = {"machine": machine_info(),
                               "section": "c_acceleration"}
    cython_info = _ensure_cython()
    payload["cython"] = cython_info
    if not cython_info.get("installed"):
        payload["verdict"] = "Cython 安装失败；见 cython.error（附 C 扩展可行性定性分析）"
        save_json(args.json.split("/")[-1], payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:2000])
        return 1

    build_info = _prepare_cython_modules()
    payload["build"] = build_info
    payload["mypyc"] = _try_mypyc()

    env, game, tokens, obs_kwargs = _make_state(seed=args.seed)
    import hsbg.env.observation as py_obs
    import hsbg.planning.model as py_model
    import p2_model_cy as cy_model
    import p2_observation_cy as cy_obs

    # 输出一致性 sanity（编译版必须与纯 Python 等价）
    sample_token = tokens[0]
    assert (py_obs.entity_token(sample_token[0], sample_token[1],
                                zone="board", slot=0)
            == cy_obs.entity_token(sample_token[0], sample_token[1],
                                   zone="board", slot=0))
    obs_py = py_obs.build_observation(**obs_kwargs)
    obs_cy = cy_obs.build_observation(**obs_kwargs)
    assert obs_py == obs_cy, "Cython build_observation 输出与纯 Python 不一致"

    results: Dict[str, Any] = {}
    # 1) entity_token
    def run_token(mod):
        for gm, entity in tokens:
            mod.entity_token(gm, entity, zone="board", slot=0)

    iters = int(args.iters)
    results["entity_token"] = {
        "what": f"{len(tokens)} 个实体各构 token 一次 = 1 iteration",
        "python": _median_bench(lambda: run_token(py_obs), iters),
        "cython": _median_bench(lambda: run_token(cy_obs), iters),
    }
    results["entity_token"]["speedup"] = _speedup(
        results["entity_token"]["python"], results["entity_token"]["cython"])

    # 2) build_observation
    results["build_observation"] = {
        "what": "整步观测构建（8 人局中局）",
        "python": _median_bench(
            lambda: py_obs.build_observation(**obs_kwargs), iters),
        "cython": _median_bench(
            lambda: cy_obs.build_observation(**obs_kwargs), iters),
    }
    results["build_observation"]["speedup"] = _speedup(
        results["build_observation"]["python"],
        results["build_observation"]["cython"])

    # 3) clone（引擎状态深拷贝；400 次即可，单次 ~2ms）
    clone_iters = int(args.clone_iters)
    results["clone"] = {
        "what": "model.clone(game)（8 人局中局，含回调重绑）",
        "python": _median_bench(lambda: py_model.clone(game), clone_iters),
        "cython": _median_bench(lambda: cy_model.clone(game), clone_iters),
    }
    results["clone"]["speedup"] = _speedup(
        results["clone"]["python"], results["clone"]["cython"])
    payload["results"] = results

    # C 加速的 Amdahl 上限（基于 e2e 分解中 obs 占比）
    payload["amdahl"] = {
        "note": "端到端加速上限 = 1/(1-f+f/s)；f=环节占比，s=C 加速比",
        "examples": [
            {"f": f, "s": 2.0,
             "ceiling": round(1.0 / (1.0 - f + f / 2.0), 2)}
            for f in (0.25, 0.5, 0.78)
        ],
    }
    path = save_json(args.json.split("/")[-1], payload)
    print(f"[bench_c_accel] saved: {path}")
    print(f"cython {cython_info.get('version')} via {cython_info.get('method')}")
    for name, item in results.items():
        py = item["python"]
        cy = item["cython"]
        print(f"{name:20s} python median {py['median_us']:9.2f} µs  "
              f"cython {cy['median_us']:9.2f} µs  "
              f"speedup {item['speedup']}×  "
              f"(p99 {py['p99_us']:.1f} → {cy['p99_us']:.1f})")
    mypyc = payload["mypyc"]
    print(f"mypyc: ok={mypyc.get('ok')} rc={mypyc.get('returncode')} "
          f"error={str(mypyc.get('error'))[:160]}")
    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
