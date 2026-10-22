"""评测运行器：任何满足 ``reset/step`` 契约的环境 + 任何 ``policy(obs)->int``。

策略接口
--------
``policy(obs: Observation, rng) -> int``：返回 ``obs.candidates`` 的下标。
也可以直接返回 ``CandidateAction``（运行器会按 signature 查找下标）。

环境接口（``hsbg.env.BattlegroundsEnv`` 或兼容 mock）::

    obs = env.reset(seed=...)
    obs, reward, terminated, truncated, info = env.step(action)
    env.legal_actions() -> Tuple[CandidateAction, ...]
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from hsbg.eval.metrics import EvalResult, format_summary

PolicyFn = Callable[..., Any]


def _resolve_action_index(obs, action) -> Optional[int]:
    """把 int / CandidateAction 统一成候选下标。"""
    from hsbg.env.spec import CandidateAction
    cands = obs.candidates
    if isinstance(action, int):
        return action if 0 <= action < len(cands) else None
    if isinstance(action, CandidateAction):
        sig = action.signature()
        for i, c in enumerate(cands):
            if c.signature() == sig:
                return i
        return None
    # 允许策略返回 None（视为第一个合法动作之外的兜底由调用方处理）
    return None


def evaluate_policy(
    env,
    policy: PolicyFn,
    *,
    episodes: int = 20,
    seed: int = 0,
    name: str = "",
    log_every: int = 0,
    rng: Optional[random.Random] = None,
    max_steps_per_episode: int = 2000,
) -> EvalResult:
    """在固定种子上跑 ``episodes`` 局并汇总。

    ``max_steps_per_episode``: 防御性上限——未训练策略可能反复选择
    freeze/reroll 等无进展动作，导致单局跑满环境步数上限（评测会假死）。
    超过上限按 truncated 计。
    """
    rng = rng or random.Random(seed)
    num_players = getattr(env, "num_players", 8)
    result = EvalResult(num_players=num_players)
    t0 = time.perf_counter()
    for ep in range(episodes):
        obs = env.reset(seed=seed + ep)
        ep_reward = 0.0
        steps = 0
        invalid = 0
        terminated = truncated = False
        info: Dict[str, Any] = {}
        while True:
            if not obs.candidates:
                # 无候选（终局/异常观测）：结束本局，按当前 info/Rank 计
                truncated = True
                info = dict(info)
                info.setdefault("terminated_reason", "no_candidates")
                break
            idx = _resolve_action_index(obs, policy(obs, rng))
            if idx is None or idx < 0 or idx >= len(obs.candidates):
                # 策略给出无效动作：取最后一个候选（通常 end_turn）兜底
                idx = len(obs.candidates) - 1 if obs.candidates else 0
                invalid += 1
            obs, reward, terminated, truncated, info = env.step(
                obs.candidates[idx])
            ep_reward += float(reward)
            steps += 1
            if terminated or truncated:
                break
            if steps >= max_steps_per_episode:
                truncated = True
                info = dict(info)
                info.setdefault("terminated_reason", "eval_step_cap")
                break
        rank = int(info.get("rank", num_players))
        result.add(rank=rank, reward=ep_reward,
                   turns=int(info.get("turn", obs.turn)),
                   steps=steps, invalid=invalid, truncated=truncated,
                   reason=str(info.get("terminated_reason", "")))
        if log_every and (ep + 1) % log_every == 0:
            print(f"  [{name}] {ep + 1}/{episodes} mean_rank="
                  f"{sum(result.ranks) / len(result.ranks):.3f}")
    result.wall_seconds = time.perf_counter() - t0  # type: ignore[attr-defined]
    return result


def save_result(result: EvalResult, path: str | Path,
                extra: Optional[Dict[str, Any]] = None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = result.to_dict()
    if extra:
        payload["meta"] = extra
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return p


def print_result(result: EvalResult, name: str = "") -> None:
    print(format_summary(result, name))
    secs = getattr(result, "wall_seconds", None)
    if secs:
        print(f"wall_time={secs:.2f}s  games/s={len(result.ranks) / secs:.2f}")
