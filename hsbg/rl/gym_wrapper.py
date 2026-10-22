"""Gymnasium 兼容包装（``gymnasium`` 为**可选依赖**）。

三个层次
--------
* :class:`GymBattlegroundsEnv` —— 把 ``EnvLike``（真实环境或 Mock）包装成
  ``gymnasium.Env``：
    - ``observation_space`` = ``Dict``（实体 token 张量 + 全局标量 + 候选张量 +
      mask，与 ``hsbg.policy.encoder.ObservationEncoder`` 的输出逐字段一致，
      因此后续可直接接 SB3 / 自研训练管线）；
    - ``action_space`` = ``Discrete(CANDIDATE_MAX)``（**静态空间**），真实可选
      动作由 :meth:`action_masks` 给出（``True`` = 合法候选，sb3-contrib
      ``MaskablePPO`` 兼容）；
    - 越界动作不抛异常：回退 ``end_turn`` 并在 ``info["invalid_action"]`` 标记
      （保证 ``check_env`` / 对手脚本不会因采样到 padding 下标崩溃）。
* 包装器：:class:`TimeLimit` / :class:`RecordEpisode`（JSONL，与
  ``hsbg.rl.collector`` 同一 schema）/ :class:`AutoResetWrapper`。
* 工厂与冒烟：:func:`make_gym_env` / :func:`check_env_smoke`。

未安装 ``gymnasium`` 时：本模块仍可 import，但实例化任何 gym 类会抛
``ImportError`` 并提示安装命令；``hsbg.rl`` 其余部分不受影响。
"""

from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from hsbg.env.spec import CANDIDATE_MAX, CandidateAction, Observation
from hsbg.rl.api import (
    SCHEMA_VERSION,
    fallback_index,
    header_record,
    obs_summary,
)
from hsbg.rl.envs import env_backend_name, make_env

try:  # gymnasium 是可选依赖：未安装时降级为"可 import、不可实例化"
    import gymnasium as gym
    from gymnasium import spaces

    GYMNASIUM_AVAILABLE = True
    GYMNASIUM_VERSION: Optional[str] = getattr(gym, "__version__", None)
except ImportError:  # pragma: no cover - 取决于环境是否安装
    gym = None  # type: ignore[assignment]
    spaces = None  # type: ignore[assignment]
    GYMNASIUM_AVAILABLE = False
    GYMNASIUM_VERSION = None

_INSTALL_HINT = (
    "需要可选依赖 gymnasium：`python -m pip install gymnasium`；"
    "不安装时不影响 hsbg.rl.collector / hsbg.rl.evaluate（它们不依赖 gym）。"
)

#: gym.Env 基类（未安装时退化为 object，保证模块可 import）
_GymEnvBase = gym.Env if GYMNASIUM_AVAILABLE else object
_GymWrapperBase = gym.Wrapper if GYMNASIUM_AVAILABLE else object


def gymnasium_available() -> bool:
    """是否安装了 gymnasium。"""
    return bool(GYMNASIUM_AVAILABLE)


def _require_gymnasium() -> None:
    if not GYMNASIUM_AVAILABLE:
        raise ImportError(_INSTALL_HINT)


# ══════════════════════════════════════════════════════════════════════
# 观测空间
# ══════════════════════════════════════════════════════════════════════


@lru_cache(maxsize=1)
def default_encoder():
    """默认 :class:`ObservationEncoder`（词表来自 ``data/``，进程内缓存）。"""
    from hsbg.policy.encoder import CardVocab, ObservationEncoder

    return ObservationEncoder(CardVocab.from_data_dir())


def build_observation_space(encoder=None) -> Any:
    """按编码器实际尺寸构造 ``spaces.Dict``（与 ``collate`` 输出逐字段一致）。"""
    _require_gymnasium()
    encoder = encoder or default_encoder()
    dims = encoder.dims
    E = int(dims.num_entities)
    C = int(dims.candidate_max)
    vocab_size = max(len(encoder.vocab), 2)
    from hsbg.policy.encoder import MAX_ZONE_SLOTS, NUM_ACTION_KINDS

    return spaces.Dict({
        "entity_card": spaces.Box(0, vocab_size - 1, (E,), dtype=np.int64),
        "entity_num": spaces.Box(-20.0, 20.0, (E, int(dims.entity_num_dim)),
                                 dtype=np.float32),
        "entity_mask": spaces.Box(0.0, 1.0, (E,), dtype=np.float32),
        "entity_zone": spaces.Box(0, int(dims.num_zones) - 1, (E,), dtype=np.int64),
        "entity_pos": spaces.Box(0, MAX_ZONE_SLOTS, (E,), dtype=np.int64),
        "global": spaces.Box(-20.0, 20.0, (int(dims.global_dim),),
                             dtype=np.float32),
        "cand_kind": spaces.Box(0, NUM_ACTION_KINDS - 1, (C,), dtype=np.int64),
        "cand_num": spaces.Box(-20.0, 20.0, (C, int(dims.cand_num_dim)),
                               dtype=np.float32),
        "cand_src": spaces.Box(0, E - 1, (C,), dtype=np.int64),
        "cand_tgt": spaces.Box(0, E - 1, (C,), dtype=np.int64),
        "cand_mask": spaces.Box(0.0, 1.0, (C,), dtype=np.float32),
    })


# ══════════════════════════════════════════════════════════════════════
# Gymnasium 环境
# ══════════════════════════════════════════════════════════════════════


class GymBattlegroundsEnv(_GymEnvBase):
    """把 ``EnvLike`` 包装为 ``gymnasium.Env``（单智能体、动态候选）。"""

    metadata = {"render_modes": [], "render.modes": []}

    def __init__(
        self,
        env: Any = None,
        *,
        backend: str = "auto",
        seed: Optional[int] = None,
        num_players: int = 8,
        opponent: str = "heuristic",
        env_kwargs: Optional[Dict[str, Any]] = None,
        mock_kwargs: Optional[Dict[str, Any]] = None,
        encoder: Any = None,
        invalid_action_penalty: float = 0.0,
        max_episode_steps: Optional[int] = None,
    ) -> None:
        _require_gymnasium()
        super().__init__()
        self.env = env if env is not None else make_env(
            backend=backend,
            seed=seed,
            num_players=num_players,
            opponent=opponent,
            env_kwargs=env_kwargs,
            mock_kwargs=mock_kwargs,
        )
        self.encoder = encoder or default_encoder()
        self.observation_space = build_observation_space(self.encoder)
        self.action_space = spaces.Discrete(CANDIDATE_MAX)
        self.invalid_action_penalty = float(invalid_action_penalty)
        self.max_episode_steps = (int(max_episode_steps)
                                  if max_episode_steps is not None else None)
        self.render_mode: Optional[str] = None
        self._obs: Optional[Observation] = None
        self._done = False
        self._episode_step = 0
        self._episode_seed: Optional[int] = None
        self.num_players = int(getattr(self.env, "num_players", num_players) or num_players)

    # ── 核心 API ──
    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
        _require_gymnasium()
        # gymnasium 的 seed 确定性检查要求重置自身 RNG 种子
        super().reset(seed=seed)
        obs = self.env.reset(seed=seed, options=options)
        self._obs = obs
        self._done = False
        self._episode_step = 0
        self._episode_seed = seed if seed is not None else getattr(self.env, "seed", None)
        return self._encode(obs), self._make_info(obs)

    def step(
        self, action: Any
    ) -> Tuple[Dict[str, np.ndarray], float, bool, bool, Dict[str, Any]]:
        _require_gymnasium()
        if self._obs is None:
            raise RuntimeError("GymBattlegroundsEnv.step() called before reset()")
        obs = self._obs
        candidates = tuple(obs.candidates or ())
        n = len(candidates)
        try:
            idx = int(action)
        except (TypeError, ValueError):
            idx = -1
        invalid = False
        reward = 0.0
        if not 0 <= idx < n:
            invalid = True
            idx = fallback_index(obs) if n else 0
        if n == 0:
            # 无候选（终局观测）：直接按 terminated 返回，避免向环境传非法动作
            self._done = True
            info = self._make_info(obs)
            info.update({"invalid_action": True, "terminal": True,
                         "no_candidates": True})
            return self._encode(obs), 0.0, True, False, info
        cand: CandidateAction = candidates[idx]
        next_obs, env_reward, terminated, truncated, env_info = self.env.step(cand)
        info = self._make_info(next_obs)
        info.update({
            "invalid_action": bool(invalid),
            "action_index": int(idx),
            "action_kind": str(getattr(cand.kind, "value", cand.kind)),
            "terminated_reason": str(env_info.get("terminated_reason", "")),
            "rank": int(env_info.get("rank", -1) or -1),
            "turn": int(env_info.get("turn", getattr(next_obs, "turn", 0)) or 0),
        })
        reward = float(env_reward)
        if invalid and self.invalid_action_penalty:
            reward += self.invalid_action_penalty
        self._obs = next_obs
        self._episode_step += 1
        if not (terminated or truncated) and self.max_episode_steps is not None:
            if self._episode_step >= self.max_episode_steps:
                truncated = True
                info["TimeLimit.truncated"] = True
        self._done = bool(terminated or truncated)
        return self._encode(next_obs), reward, bool(terminated), bool(truncated), info

    # ── 动态候选辅助 ──
    def action_masks(self) -> np.ndarray:
        """sb3-contrib ``MaskablePPO`` 兼容：长度 ``CANDIDATE_MAX`` 的 bool 掩码。"""
        _require_gymnasium()
        mask = np.zeros(CANDIDATE_MAX, dtype=bool)
        n = self.num_actions()
        if n > 0:
            mask[: min(n, CANDIDATE_MAX)] = True
        return mask

    #: 别名（sb3-contrib 旧版本用 ``action_mask``）
    def action_mask(self) -> np.ndarray:
        return self.action_masks()

    def legal_actions(self) -> Tuple[CandidateAction, ...]:
        if self._obs is None:
            return ()
        return tuple(self._obs.candidates or ())

    def num_actions(self) -> int:
        return len(self.legal_actions())

    @property
    def num_players(self) -> int:
        return self._num_players

    @num_players.setter
    def num_players(self, value: int) -> None:
        self._num_players = int(value)

    @property
    def current_observation(self) -> Optional[Observation]:
        return self._obs

    @property
    def seed_value(self) -> Optional[int]:
        return self._episode_seed

    # ── 内部 ──
    def _encode(self, obs: Observation) -> Dict[str, np.ndarray]:
        return self.encoder.encode_obs(obs)

    def _make_info(self, obs: Observation) -> Dict[str, Any]:
        n = len(obs.candidates or ())
        return {
            "n_candidates": int(min(n, CANDIDATE_MAX)),
            "phase": str(getattr(obs, "phase", "")),
            "turn": int(getattr(obs, "turn", 0) or 0),
            "episode_step": int(self._episode_step),
            "env": env_backend_name(self.env),
        }

    def render(self):  # noqa: D102 - 无渲染
        return None

    def close(self) -> None:
        close = getattr(self.env, "close", None)
        if callable(close):
            close()
        self._obs = None


# ══════════════════════════════════════════════════════════════════════
# 包装器
# ══════════════════════════════════════════════════════════════════════


class _DynamicActionMixin:
    """包装器透传动态候选辅助（sb3-contrib / 自定义循环需要）。"""

    def action_masks(self) -> np.ndarray:  # type: ignore[override]
        fn = getattr(self.env, "action_masks", None)
        if callable(fn):
            return np.asarray(fn())
        raise AttributeError("底层环境没有 action_masks()")

    def action_mask(self) -> np.ndarray:
        return self.action_masks()

    def legal_actions(self) -> Tuple[CandidateAction, ...]:
        fn = getattr(self.env, "legal_actions", None)
        return tuple(fn()) if callable(fn) else ()

    def num_actions(self) -> int:
        fn = getattr(self.env, "num_actions", None)
        if callable(fn):
            return int(fn())
        return len(self.legal_actions())

    @property
    def num_players(self) -> int:
        return int(getattr(self.env, "num_players", 8) or 8)

    @property
    def current_observation(self) -> Optional[Observation]:
        fn = getattr(self.env, "current_observation", None)
        return fn


class TimeLimit(_DynamicActionMixin, _GymWrapperBase):
    """单局步数上限（``truncated=True``，不做 auto-reset）。"""

    def __init__(self, env: Any, max_episode_steps: int = 500) -> None:
        _require_gymnasium()
        if max_episode_steps <= 0:
            raise ValueError("max_episode_steps 必须 > 0")
        super().__init__(env)
        self.max_episode_steps = int(max_episode_steps)
        self._elapsed = 0

    def reset(self, *, seed: Optional[int] = None,
              options: Optional[Dict[str, Any]] = None):
        self._elapsed = 0
        return self.env.reset(seed=seed, options=options)

    def step(self, action: Any):
        obs, reward, terminated, truncated, info = self.env.step(action)
        self._elapsed += 1
        if not (terminated or truncated) and self._elapsed >= self.max_episode_steps:
            truncated = True
            info = dict(info)
            info["TimeLimit.truncated"] = True
        return obs, reward, terminated, truncated, info


class AutoResetWrapper(_DynamicActionMixin, _GymWrapperBase):
    """終局自动 reset（返回新局观测；旧终局观测放 ``info["terminal_observation"]``）。

    gymnasium 官方语义里 auto-reset 属于"向量/训练循环"职责；本包装器让
    单环境循环（例如 RL 框架）不必自己判断 done。``terminal_observation``
    是 gym 观测（编码后 dict），不是原始 ``Observation``。
    """

    def __init__(self, env: Any) -> None:
        _require_gymnasium()
        super().__init__(env)

    def step(self, action: Any):
        obs, reward, terminated, truncated, info = self.env.step(action)
        if terminated or truncated:
            info = dict(info)
            info["terminal_observation"] = obs
            info["terminal"] = True
            obs, _reset_info = self.env.reset()
            info["reset_info"] = _reset_info
        return obs, reward, terminated, truncated, info


class RecordEpisode(_DynamicActionMixin, _GymWrapperBase):
    """把每一步/每局写成 JSONL（schema 与 ``hsbg.rl.collector`` 一致）。

    * 首次写入（文件为空/不存在）会写一条 ``type="header"``；
    * 每步一条 ``type="step"``（含观测摘要），每局一条 ``type="episode"``；
    * ``reset()`` 在上一局未结束时视为提前中止（记 ``truncated=True``）。
    """

    def __init__(
        self,
        env: Any,
        path: Union[str, Path],
        *,
        per_step: bool = True,
        per_episode: bool = True,
        include_board: bool = True,
        policy: str = "gym",
        append: bool = True,
        flush: bool = True,
    ) -> None:
        _require_gymnasium()
        super().__init__(env)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.per_step = bool(per_step)
        self.per_episode = bool(per_episode)
        self.include_board = bool(include_board)
        self.policy = str(policy)
        self.flush = bool(flush)
        self._episode_id = 0
        self._step_index = 0
        self._episode_seed: Optional[int] = None
        self._episode_reward = 0.0
        self._episode_rows: List[Dict[str, Any]] = []
        self._episode_start = time.perf_counter()
        self._cur_obs: Optional[Observation] = None
        self._fh = open(self.path, "a" if append else "w", encoding="utf-8")
        if self.path.stat().st_size == 0:
            self._write(header_record(
                policy=self.policy, source="RecordEpisode",
                backend=env_backend_name(getattr(env, "env", env)),
                num_players=int(getattr(env, "num_players", 8) or 8),
            ))

    # ── 写出 ──
    def _write(self, row: Dict[str, Any]) -> None:
        self._fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        if self.flush:
            self._fh.flush()

    def _finish_episode(self, info: Dict[str, Any], *, truncated: bool = False) -> None:
        rank = int(info.get("rank", -1) or -1)
        turns = int(info.get("turn", 0) or 0)
        if not self.per_episode:
            self._episode_rows = []
            return
        row = {
            "type": "episode",
            "v": SCHEMA_VERSION,
            "episode_id": int(self._episode_id),
            "seed": int(self._episode_seed if self._episode_seed is not None else -1),
            "rank": rank,
            "total_reward": float(self._episode_reward),
            "turns": turns,
            "steps": int(self._step_index),
            "terminated": bool(info.get("terminated", False) and not truncated),
            "truncated": bool(truncated or info.get("truncated", False)),
            "reason": str(info.get("terminated_reason", "record_wrapper")),
            "invalid_actions": int(self._invalid_count),
            "policy": self.policy,
            "num_players": int(getattr(self.env, "num_players", 8) or 8),
            "wall_ms": round((time.perf_counter() - self._episode_start) * 1000.0, 3),
        }
        self._write(row)
        self._episode_id += 1
        self._episode_rows = []
        self._step_index = 0
        self._episode_reward = 0.0

    # ── gym API ──
    def reset(self, *, seed: Optional[int] = None,
              options: Optional[Dict[str, Any]] = None):
        if self._step_index > 0:
            # 上一局未走完就 reset：按提前中止记录
            self._finish_episode({"terminated_reason": "reset_before_done"}, truncated=True)
        obs, info = self.env.reset(seed=seed, options=options)
        self._episode_seed = seed
        self._step_index = 0
        self._episode_reward = 0.0
        self._invalid_count = 0
        self._episode_rows = []
        self._episode_start = time.perf_counter()
        self._cur_obs = self._underlying_obs()
        return obs, info

    def step(self, action: Any):
        if self._cur_obs is None:
            raise RuntimeError("RecordEpisode.step() called before reset()")
        cur_obs = self._cur_obs
        candidates = tuple(cur_obs.candidates or ())
        try:
            idx = int(action)
        except (TypeError, ValueError):
            idx = -1
        valid = 0 <= idx < len(candidates)
        cand = candidates[idx] if valid else (candidates[-1] if candidates else None)
        obs, reward, terminated, truncated, info = self.env.step(action)
        info = dict(info)
        invalid = bool(info.get("invalid_action", not valid))
        if invalid:
            self._invalid_count += 1
        self._episode_reward += float(reward)
        row = {
            "type": "step",
            "v": SCHEMA_VERSION,
            "episode_id": int(self._episode_id),
            "seed": int(self._episode_seed if self._episode_seed is not None else -1),
            "step": int(self._step_index),
            "turn": int(getattr(cur_obs, "turn", 0) or 0),
            "phase": str(getattr(cur_obs, "phase", "")),
            "action": int(idx),
            "action_kind": str(getattr(cand.kind, "value", cand.kind)) if cand else "",
            "action_signature": list(cand.signature()) if cand is not None else [],
            "reward": float(reward),
            "terminated": bool(terminated),
            "truncated": bool(truncated),
            "invalid": bool(invalid),
            "rank": int(info.get("rank", -1) or -1),
            "n_candidates": len(candidates),
            "candidate_max": CANDIDATE_MAX,
            "obs": obs_summary(cur_obs, include_board=self.include_board),
        }
        if self.per_step:
            self._write(row)
        else:
            self._episode_rows.append(row)
        self._step_index += 1
        self._cur_obs = self._underlying_obs()
        if terminated or truncated:
            info.setdefault("terminated", bool(terminated))
            info.setdefault("truncated", bool(truncated))
            self._finish_episode(info)
        return obs, reward, terminated, truncated, info

    def _underlying_obs(self) -> Optional[Observation]:
        """沿包装器链找到底层环境的 ``current_observation``（原始 Observation）。"""
        node: Any = self.env
        for _ in range(10):
            obs = getattr(node, "current_observation", None)
            if obs is not None:
                return obs
            node = getattr(node, "env", None)
            if node is None:
                break
        return None

    def close(self) -> None:
        if self._fh is not None and not self._fh.closed:
            self._fh.close()
        close = getattr(self.env, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "RecordEpisode":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


# ══════════════════════════════════════════════════════════════════════
# 工厂 / 冒烟检查
# ══════════════════════════════════════════════════════════════════════


def make_gym_env(
    *,
    env: Any = None,
    backend: str = "auto",
    seed: Optional[int] = None,
    num_players: int = 8,
    opponent: str = "heuristic",
    env_kwargs: Optional[Dict[str, Any]] = None,
    mock_kwargs: Optional[Dict[str, Any]] = None,
    encoder: Any = None,
    max_episode_steps: Optional[int] = None,
    time_limit: Optional[int] = None,
    record_path: Optional[Union[str, Path]] = None,
    auto_reset: bool = False,
) -> Any:
    """构造 Gym 环境的便捷工厂（可叠加 TimeLimit / RecordEpisode / AutoReset）。"""
    _require_gymnasium()
    gym_env: Any = GymBattlegroundsEnv(
        env=env,
        backend=backend,
        seed=seed,
        num_players=num_players,
        opponent=opponent,
        env_kwargs=env_kwargs,
        mock_kwargs=mock_kwargs,
        encoder=encoder,
        max_episode_steps=max_episode_steps,
    )
    limit = time_limit if time_limit is not None else max_episode_steps
    if limit is not None:
        gym_env = TimeLimit(gym_env, max_episode_steps=int(limit))
    if record_path is not None:
        gym_env = RecordEpisode(gym_env, record_path)
    if auto_reset:
        gym_env = AutoResetWrapper(gym_env)
    return gym_env


def check_env_smoke(env: Any = None, *, skip_render_check: bool = True,
                    backend: str = "mock", seed: int = 0) -> bool:
    """用 ``gymnasium.utils.env_checker.check_env`` 做一次完整接口冒烟。"""
    _require_gymnasium()
    from gymnasium.utils.env_checker import check_env

    target = env if env is not None else make_gym_env(
        backend=backend, seed=seed, mock_kwargs={"seed": seed}
    )
    try:
        check_env(target, skip_render_check=skip_render_check)
        return True
    finally:
        if env is None:
            close = getattr(target, "close", None)
            if callable(close):
                close()


__all__ = [
    "GYMNASIUM_AVAILABLE",
    "GYMNASIUM_VERSION",
    "gymnasium_available",
    "default_encoder",
    "build_observation_space",
    "GymBattlegroundsEnv",
    "TimeLimit",
    "AutoResetWrapper",
    "RecordEpisode",
    "make_gym_env",
    "check_env_smoke",
]
