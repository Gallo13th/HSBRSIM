"""KNOWN-DET-1 回归：跨进程（PYTHONHASHSEED）确定性。

背景
----
HSBRSIM 的引擎 ``hsrl2`` 里存在把 ``set``/``frozenset`` 迭代顺序直接喂给
``game.rng.choice/sample`` 的代码路径；``str`` 的哈希值受解释器启动时的
``PYTHONHASHSEED`` 随机化影响 → **同一 seed + 同一动作序列**在两个进程里会
抽到不同的卡，产生不同的轨迹（同进程连续两次 rollout 却一致，所以普通确定性
测试测不到）。

已修与已知残留：

* F-36（engine-fixer）：``hsrl2/scripts/choose_one_authority.py`` 的
  ``pool_choose_one_{minion,spell}_ids()`` 返回 ``frozenset``，
  ``BrambleTunnelerScript.rally`` / ``FandralsFortuneScript.on_play`` 直接
  迭代后喂 RNG → 已改 ``sorted()``；回归见
  ``hsrl2/tests/test_hashseed_determinism.py``。
* 本文件负责**环境层**回归：用完整 ``BattlegroundsEnv``（含对手招募期）在
  两个 ``PYTHONHASHSEED`` 子进程里跑同一固定 rollout，逐位比较轨迹指纹。

用法（也可当最小复现脚本，不依赖 pytest）
------------------------------------------
::

    cd /Users/letiangao/HSAgent/HSBRSIM

    # 手动比较两个 hashseed（不一致时退出码 1，并打印首个分歧 step）
    python3 tests/test_env_determinism_hashseed.py --seed 2 --hashseeds 0,1
    python3 tests/test_env_determinism_hashseed.py --seed 3 --hashseeds 0,1

    # 单 worker（测试内部用；输出 trace JSON）
    PYTHONHASHSEED=0 python3 tests/test_env_determinism_hashseed.py --worker --seed 2

    # pytest 回归
    python3 -m pytest tests/test_env_determinism_hashseed.py -q

约束：> **不得**通过固定 ``PYTHONHASHSEED`` 让测试变绿；断言的是"不同
hashseed 下轨迹必须相同"。本文件只读引擎，不修改 ``hsrl2/**``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import pytest

#: 仓库根（子进程 PYTHONPATH 与 worker 自举用）
REPO_ROOT = Path(__file__).resolve().parents[1]

#: 参与 pytest 的已知敏感用例（seed, opponent, num_players）：
#: * seed=2/3 + random 对手：Sky Admiral Rogers "random Bounty" 曾因
#:   ``BOUNTY_SPELL_IDS`` frozenset 迭代顺序跨进程分裂；
#: * seed=4001 + random 对手：F-36 的最小复现（choose_one frozenset）；
#: * seed=0 + heuristic 对手：常规路径对照（不应依赖 hash 序）。
KNOWN_CASES: Tuple[Tuple[int, str, int], ...] = (
    (2, "random", 8),
    (3, "random", 8),
    (4001, "random", 8),
    (0, "heuristic", 8),
)

#: 默认比较的 hashseed（引擎对 str 哈希敏感；0 表示确定性哈希，1/4/7 为随机化）
DEFAULT_HASHSEEDS: Tuple[str, ...] = ("0", "1")

#: 单个 rollout 的最大步数（短轨迹，控制测试耗时）
MAX_STEPS = 160


# ══════════════════════════════════════════════════════════════════════
# 轨迹（同进程）：固定 seed + 确定性动作选择 → 逐步指纹
# ══════════════════════════════════════════════════════════════════════


def _candidate_key(cand: Any) -> List[Any]:
    return [str(cand.kind), cand.src_zone, int(cand.src_slot), cand.tgt_zone,
            int(cand.tgt_slot), int(cand.position), int(cand.option)]


def rollout_trace(
    seed: int,
    opponent: str = "random",
    num_players: int = 8,
    max_steps: int = MAX_STEPS,
) -> List[Dict[str, Any]]:
    """跑一条固定 rollout，返回逐步状态（**不含 uuid/时间等进程相关量**）。

    动作选择用 ``random.Random(seed).randrange(len(legal_actions))``——只依赖
    seed 与候选**顺序**；因此两条轨迹若不同，差异只能来自环境/引擎内部。
    """
    from hsbg.env.game_env import BattlegroundsEnv

    env = BattlegroundsEnv(num_players=int(num_players),
                           opponent=str(opponent), seed=int(seed))
    try:
        env.reset(seed=int(seed))
        rng = random.Random(int(seed))
        trace: List[Dict[str, Any]] = []
        while len(trace) < int(max_steps):
            actions = env.legal_actions()
            if not actions:
                break
            idx = rng.randrange(len(actions))
            chosen = _candidate_key(actions[idx])
            obs, reward, terminated, truncated, info = env.step(idx)
            pending = obs.pending_choice
            trace.append({
                "step": len(trace),
                "turn": int(obs.turn),
                "phase": str(obs.phase),
                "action": chosen,
                "n_cand": len(obs.candidates),
                "cands": [_candidate_key(c) for c in obs.candidates],
                "reward": round(float(reward), 9),
                "alive": int(info.get("alive_count", -1)),
                "rank": int(info.get("rank", -1)),
                "health": int(info.get("health", -1)),
                "board": [[t.card_id, int(t.atk), int(t.health)]
                          for t in obs.board],
                "hand": [[t.card_id, int(t.cost)] for t in obs.hand],
                "tavern": [[t.card_id, int(t.atk), int(t.health), int(t.cost)]
                           for t in obs.tavern],
                "lobby": [[int(p.health), int(p.armor), int(p.tier),
                           bool(p.alive), int(p.eliminated_rank)]
                          for p in obs.lobby],
                "pending": (None if pending is None else
                            [str(pending.kind),
                             [t.card_id for t in pending.options]]),
            })
            if terminated or truncated:
                break
        return trace
    finally:
        env.close()


def fingerprint(trace: Sequence[Dict[str, Any]]) -> str:
    """轨迹指纹（sha256 前 16 位；稳定 JSON 序列化）。"""
    blob = json.dumps(trace, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ══════════════════════════════════════════════════════════════════════
# worker（子进程入口）：PYTHONHASHSEED 由父进程环境变量决定
# ══════════════════════════════════════════════════════════════════════


def _ensure_repo_on_path() -> None:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def worker_payload(
    seed: int,
    opponent: str = "random",
    num_players: int = 8,
    max_steps: int = MAX_STEPS,
) -> Dict[str, Any]:
    _ensure_repo_on_path()
    trace = rollout_trace(seed, opponent, num_players, max_steps)
    return {
        "seed": int(seed),
        "opponent": str(opponent),
        "num_players": int(num_players),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", "<unset>"),
        "steps": len(trace),
        "fingerprint": fingerprint(trace),
        "trace": trace,
    }


def _worker_main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description="hashseed 确定性 worker")
    ap.add_argument("--worker", action="store_true", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--opponent", default="random")
    ap.add_argument("--num-players", type=int, default=8)
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS)
    args = ap.parse_args(list(argv))
    print(json.dumps(worker_payload(args.seed, args.opponent,
                                    args.num_players, args.max_steps),
                     ensure_ascii=False))
    return 0


# ══════════════════════════════════════════════════════════════════════
# 子进程调用 / 手动比较 CLI
# ══════════════════════════════════════════════════════════════════════


def _worker_script() -> str:
    return str(Path(__file__).resolve())


def run_worker_subprocess(
    hashseed: str,
    seed: int,
    opponent: str = "random",
    num_players: int = 8,
    max_steps: int = MAX_STEPS,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """在 ``PYTHONHASHSEED=hashseed`` 的子进程里跑 worker，返回 payload。"""
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(hashseed)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    proc = subprocess.run(
        [sys.executable, _worker_script(), "--worker",
         "--seed", str(int(seed)), "--opponent", str(opponent),
         "--num-players", str(int(num_players)),
         "--max-steps", str(int(max_steps))],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT),
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"worker(PYTHONHASHSEED={hashseed}, seed={seed}) 失败:\n"
            f"{proc.stderr[-3000:]}")
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


def _first_divergence(a: Sequence[Dict[str, Any]],
                      b: Sequence[Dict[str, Any]]) -> str:
    n = min(len(a), len(b))
    for k in range(n):
        if a[k] != b[k]:
            diff = [field for field in a[k]
                    if a[k].get(field) != b[k].get(field)]
            return (f"首个分歧 step={k}（turn={a[k]['turn']}, "
                    f"phase={a[k]['phase']}, 字段={diff}）：\n"
                    f"  A={json.dumps(a[k], ensure_ascii=False)[:1200]}\n"
                    f"  B={json.dumps(b[k], ensure_ascii=False)[:1200]}")
    if len(a) != len(b):
        return f"步数不同：{len(a)} vs {len(b)}（公共前缀完全一致）"
    return "轨迹完全一致"


def _compare_main(argv: Sequence[str]) -> int:
    _ensure_repo_on_path()
    ap = argparse.ArgumentParser(description="跨 PYTHONHASHSEED 轨迹对比")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--opponent", default="random")
    ap.add_argument("--num-players", type=int, default=8)
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS)
    ap.add_argument("--hashseeds", default="0,1")
    args = ap.parse_args(list(argv))
    seeds = [s.strip() for s in str(args.hashseeds).split(",") if s.strip()]
    payloads: List[Dict[str, Any]] = []
    for hashseed in seeds:
        payload = run_worker_subprocess(
            hashseed, args.seed, args.opponent, args.num_players,
            args.max_steps)
        payloads.append(payload)
        print(f"PYTHONHASHSEED={hashseed}: steps={payload['steps']} "
              f"fingerprint={payload['fingerprint']}")
    base = payloads[0]
    ok = True
    for payload in payloads[1:]:
        if (payload["fingerprint"] != base["fingerprint"]
                or payload["trace"] != base["trace"]):
            ok = False
            print(f"\n✗ 轨迹不一致 vs PYTHONHASHSEED="
                  f"{payload['pythonhashseed']}：")
            print(_first_divergence(base["trace"], payload["trace"]))
    if ok:
        print("\n✓ 所有 PYTHONHASHSEED 下轨迹逐位一致")
        return 0
    return 1


# ══════════════════════════════════════════════════════════════════════
# pytest 回归
# ══════════════════════════════════════════════════════════════════════


def test_worker_rollout_is_nontrivial() -> None:
    """worker 轨迹必须真的跑了若干步（防止空轨迹让一致性断言假绿）。"""
    payload = run_worker_subprocess("0", 2, "random", 8, MAX_STEPS)
    assert payload["steps"] > 10
    assert payload["fingerprint"]
    assert payload["pythonhashseed"] == "0"


@pytest.mark.parametrize("seed,opponent,num_players", KNOWN_CASES)
def test_cross_process_hashseed_trace_identical(seed: int, opponent: str,
                                               num_players: int) -> None:
    """同 seed 同动作序列，不同 PYTHONHASHSEED 的独立进程轨迹必须逐位一致。"""
    payloads = [run_worker_subprocess(hs, seed, opponent, num_players)
                for hs in DEFAULT_HASHSEEDS]
    steps = [payload["steps"] for payload in payloads]
    assert max(steps) > 10
    fps = [payload["fingerprint"] for payload in payloads]
    assert len(set(fps)) == 1, (
        f"seed={seed} opponent={opponent} 跨 PYTHONHASHSEED 轨迹不一致："
        f"{list(zip(DEFAULT_HASHSEEDS, fps, steps))}\n"
        + _first_divergence(payloads[0]["trace"], payloads[1]["trace"]))


def test_same_process_two_rollouts_identical() -> None:
    """对照：同一进程内连跑两次必须一致（普通确定性测试的既有保证）。"""
    for seed, opponent, num_players in KNOWN_CASES[:3]:
        trace_a = rollout_trace(seed, opponent, num_players, MAX_STEPS)
        trace_b = rollout_trace(seed, opponent, num_players, MAX_STEPS)
        assert trace_a == trace_b, (
            f"seed={seed} 同进程两次 rollout 不一致")
        assert len(trace_a) > 10


def test_in_process_trace_matches_subprocess_worker() -> None:
    """同进程轨迹 == 子进程（PYTHONHASHSEED=0）轨迹；保证 worker 路径不变形。"""
    in_process = rollout_trace(2, "random", 8, MAX_STEPS)
    worker = run_worker_subprocess("0", 2, "random", 8, MAX_STEPS)
    assert fingerprint(in_process) == worker["fingerprint"], (
        _first_divergence(worker["trace"], in_process))


# ══════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════

def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--worker" in args:
        return _worker_main(args)
    return _compare_main(args)


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
