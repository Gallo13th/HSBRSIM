"""向量化环境适配层（只依赖 ``hsbg.env.spec`` 契约 + Mock 实现）。

真环境由 env-builder 提供；本模块提供：

* :class:`VecEnv` —— 训练侧依赖的最小协议（鸭子类型，不强制继承）。
* :class:`SyncVecEnv` —— 把若干单环境串行包装成 VecEnv（真 env 未提供
  ``hsbg.env.vec_env`` 时的兜底）。
* :class:`MockVecEnv` —— 合成观测向量环境，用于在真 env 就绪前自测策略/
  训练管线；会生成变长候选动作（偶发超过 ``CANDIDATE_MAX`` 以测试截断）。
* :func:`make_vec_env` —— "真 env 可用就用真 env，否则 Mock" 的自动选择。

接口约定（与 ``docs/ENV_SPEC.md`` §8 一致）::

    env.reset() -> List[Observation]
    env.step(actions) -> (List[Observation], np.ndarray, np.ndarray, List[dict])
    env.close()

``step`` 的 done 语义：``dones[i] = terminated[i] or truncated[i]``，且**自动
reset**（done 的 env 该步返回新 episode 的首个观测）。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

import numpy as np

from hsbg.env.spec import (
    CANDIDATE_MAX,
    PLAYER_MAX,
    Observation,
)
from hsbg.policy.synthetic import FAKE_CARD_IDS, random_observation


@runtime_checkable
class VecEnv(Protocol):
    """训练侧依赖的最小向量环境协议。"""

    num_envs: int

    def reset(self) -> List[Observation]:  # pragma: no cover - 协议定义
        ...

    def step(
        self, actions: Sequence[int]
    ) -> Tuple[List[Observation], np.ndarray, np.ndarray, List[Dict[str, Any]]]:  # pragma: no cover
        ...

    def close(self) -> None:  # pragma: no cover - 协议定义
        ...


def is_vec_env(obj: Any) -> bool:
    """鸭子类型检查：同时具备 num_envs / reset / step / close。"""
    return all(hasattr(obj, name) for name in ("num_envs", "reset", "step", "close"))


# ══════════════════════════════════════════════════════════════════════
# 单环境 → VecEnv 适配
# ══════════════════════════════════════════════════════════════════════


def normalize_step_result(result: Any) -> Tuple[Observation, float, bool, bool, Dict[str, Any]]:
    """把 ``env.step`` 的多种返回形态统一成 5 元组。

    兼容：``StepResult`` / ``(obs, reward, terminated, truncated, info)`` /
    ``(obs, reward, done, info)``。
    """
    if hasattr(result, "observation"):
        return (
            result.observation,
            float(getattr(result, "reward", 0.0)),
            bool(getattr(result, "terminated", False)),
            bool(getattr(result, "truncated", False)),
            dict(getattr(result, "info", {}) or {}),
        )
    if not isinstance(result, tuple):
        raise TypeError(f"不支持的 env.step 返回类型: {type(result)!r}")
    if len(result) == 5:
        obs, reward, terminated, truncated, info = result
        return obs, float(reward), bool(terminated), bool(truncated), dict(info or {})
    if len(result) == 4:
        obs, reward, done, info = result
        return obs, float(reward), bool(done), False, dict(info or {})
    if len(result) == 2:
        obs, reward = result
        return obs, float(reward), False, False, {}
    raise TypeError(f"不支持的 env.step 元组长度: {len(result)}")


class SyncVecEnv:
    """把多个单环境（``reset``/``step`` 五元组风格）串行包装成 VecEnv。

    真环境层若已提供 ``hsbg.env.vec_env``，训练侧优先用它；本类只做兜底，
    保证策略/训练管线不阻塞在环境实现上。
    """

    def __init__(
        self,
        envs: Sequence[Any],
        *,
        auto_reset: bool = True,
        seeds: Optional[Sequence[int]] = None,
    ) -> None:
        self.envs = list(envs)
        self.num_envs = len(self.envs)
        if self.num_envs == 0:
            raise ValueError("SyncVecEnv 至少需要 1 个环境")
        self.auto_reset = auto_reset
        self.seeds = list(seeds) if seeds is not None else None
        self._seeded = False

    @classmethod
    def from_factory(
        cls,
        factory: Callable[[int], Any],
        num_envs: int,
        *,
        seeds: Optional[Sequence[int]] = None,
    ) -> "SyncVecEnv":
        envs = [factory(i) for i in range(num_envs)]
        return cls(envs, seeds=seeds)

    # ── VecEnv API ──
    def reset(self) -> List[Observation]:
        obs_list: List[Observation] = []
        for i, env in enumerate(self.envs):
            seed = self.seeds[i] if self.seeds is not None else None
            obs_list.append(_reset_env(env, seed))
        self._seeded = True
        return obs_list

    def step(
        self, actions: Sequence[int]
    ) -> Tuple[List[Observation], np.ndarray, np.ndarray, List[Dict[str, Any]]]:
        if len(actions) != self.num_envs:
            raise ValueError(
                f"动作数({len(actions)}) != num_envs({self.num_envs})"
            )
        obs_list: List[Observation] = []
        rewards = np.zeros(self.num_envs, dtype=np.float32)
        dones = np.zeros(self.num_envs, dtype=bool)
        infos: List[Dict[str, Any]] = []
        for i, env in enumerate(self.envs):
            obs, reward, terminated, truncated, info = normalize_step_result(
                env.step(int(actions[i]))
            )
            done = bool(terminated or truncated)
            info = dict(info)
            info.setdefault("terminated", bool(terminated))
            info.setdefault("truncated", bool(truncated))
            if done and self.auto_reset:
                seed = None
                if self.seeds is not None:
                    self.seeds[i] = int(self.seeds[i]) + 1
                    seed = self.seeds[i]
                obs = _reset_env(env, seed)
            rewards[i] = reward
            dones[i] = done
            obs_list.append(obs)
            infos.append(info)
        return obs_list, rewards, dones, infos

    def close(self) -> None:
        for env in self.envs:
            close = getattr(env, "close", None)
            if callable(close):
                close()

    def __len__(self) -> int:
        return self.num_envs


def _reset_env(env: Any, seed: Optional[int]) -> Observation:
    """兼容 ``reset()`` / ``reset(seed=...)`` / ``reset(seed)`` 三种签名。"""
    if seed is None:
        try:
            return env.reset()
        except TypeError:
            return env.reset(seed=None)
    try:
        return env.reset(seed=seed)
    except TypeError:
        return env.reset(seed)


# ══════════════════════════════════════════════════════════════════════
# Mock 向量环境
# ══════════════════════════════════════════════════════════════════════


def placement_to_reward(rank: int, num_players: int = PLAYER_MAX) -> float:
    """名次 → [-1, 1] 奖励（与 ``RewardConfig.placement`` 公式一致）。"""
    if num_players <= 1:
        return 0.0
    rank = int(min(max(rank, 1), num_players))
    return 1.0 - 2.0 * (rank - 1) / (num_players - 1)


class MockVecEnv:
    """合成观测的向量环境（随机观测 + 随机长度 episode）。

    行为
    ----
    * 每步观测用 :func:`hsbg.policy.synthetic.random_observation` 生成，候选
      动作变长（含偶尔 > ``CANDIDATE_MAX`` 的超长分支）。
    * episode 长度随机（``episode_steps_range``）；结束时给出名次奖励。
    * 非法动作（下标越界）不会崩溃：``info["invalid"]=True`` 并给惩罚。
    * 与真环境一样 auto-reset；同一个 ``seed`` 完全可复现。
    """

    def __init__(
        self,
        num_envs: int = 2,
        seed: int = 0,
        *,
        num_players: int = PLAYER_MAX,
        episode_steps_range: Tuple[int, int] = (20, 60),
        candidate_max: int = CANDIDATE_MAX + 6,
        card_ids: Optional[Sequence[str]] = None,
        reward_scale: float = 1.0,
        step_reward_std: float = 0.01,
        truncated_prob: float = 0.1,
    ) -> None:
        if num_envs < 1:
            raise ValueError("num_envs 必须 >= 1")
        self.num_envs = int(num_envs)
        self.seed = int(seed)
        self.num_players = int(num_players)
        self.episode_steps_range = (int(episode_steps_range[0]), int(episode_steps_range[1]))
        self.candidate_max = int(candidate_max)
        self.card_ids = tuple(card_ids) if card_ids is not None else FAKE_CARD_IDS
        self.reward_scale = float(reward_scale)
        self.step_reward_std = float(step_reward_std)
        self.truncated_prob = float(truncated_prob)
        self._rngs = [np.random.default_rng(self.seed * 1000 + i) for i in range(self.num_envs)]
        self._episode_seed = [self.seed * 1000 + i for i in range(self.num_envs)]
        self._episode_len = [0] * self.num_envs
        self._episode_step = [0] * self.num_envs
        self._episode_return = [0.0] * self.num_envs
        self._reset_count = [0] * self.num_envs
        self._obs: List[Optional[Observation]] = [None] * self.num_envs

    # ── VecEnv API ──
    def reset(self) -> List[Observation]:
        self._obs = [self._new_episode(i) for i in range(self.num_envs)]
        return list(self._obs)  # type: ignore[arg-type]

    def step(
        self, actions: Sequence[int]
    ) -> Tuple[List[Observation], np.ndarray, np.ndarray, List[Dict[str, Any]]]:
        if len(actions) != self.num_envs:
            raise ValueError(f"动作数({len(actions)}) != num_envs({self.num_envs})")
        rewards = np.zeros(self.num_envs, dtype=np.float32)
        dones = np.zeros(self.num_envs, dtype=bool)
        infos: List[Dict[str, Any]] = []
        for i in range(self.num_envs):
            rng = self._rngs[i]
            obs = self._obs[i]
            assert obs is not None, "step 前必须先 reset"
            info: Dict[str, Any] = {
                "turn": int(obs.turn),
                "invalid": False,
                "terminated": False,
                "truncated": False,
                "seed": int(self._episode_seed[i]),
                "episode_steps": int(self._episode_step[i]),
                "reward": 0.0,
            }
            action = int(actions[i])
            reward = float(rng.normal(0.0, self.step_reward_std))
            # 非法动作（越界）→ 惩罚，不推进 episode 计数
            if action < 0 or action >= max(len(obs.candidates), 1):
                info["invalid"] = True
                reward += -0.05
                info["reward"] = reward
                rewards[i] = reward * self.reward_scale
                infos.append(info)
                continue
            self._episode_step[i] += 1
            self._episode_return[i] += reward
            terminated = self._episode_step[i] >= self._episode_len[i]
            truncated = False
            if terminated:
                truncated = bool(rng.random() < self.truncated_prob)
                rank = int(rng.integers(1, self.num_players + 1))
                reward += placement_to_reward(rank, self.num_players)
                info["rank"] = rank
                info["placement_reward"] = placement_to_reward(rank, self.num_players)
                info["episode_steps"] = int(self._episode_step[i])
                info["terminated"] = not truncated
                info["truncated"] = truncated
                info["episode_return"] = float(self._episode_return[i])
                dones[i] = True
            rewards[i] = reward * self.reward_scale
            info["reward"] = float(rewards[i])
            infos.append(info)
            if dones[i]:
                self._obs[i] = self._new_episode(i)
            else:
                self._obs[i] = random_observation(
                    rng,
                    card_ids=self.card_ids,
                    num_players=self.num_players,
                    turn=min(int(obs.turn) + (1 if self._episode_step[i] % 6 == 0 else 0), 30),
                )
        return list(self._obs), rewards, dones, infos  # type: ignore[arg-type]

    def close(self) -> None:
        self._obs = [None] * self.num_envs

    def __len__(self) -> int:
        return self.num_envs

    # ── 内部 ──
    def _new_episode(self, i: int) -> Observation:
        self._episode_seed[i] += 1
        seed = int(self._episode_seed[i])
        self._rngs[i] = np.random.default_rng(seed)
        self._episode_len[i] = int(self._rngs[i].integers(*self.episode_steps_range))
        self._episode_step[i] = 0
        self._episode_return[i] = 0.0
        self._reset_count[i] += 1
        return random_observation(
            self._rngs[i],
            card_ids=self.card_ids,
            num_players=self.num_players,
            turn=1,
            candidate_count=None if self._reset_count[i] % 7 else 3,
        )


# ══════════════════════════════════════════════════════════════════════
# 自动选择真 env / Mock
# ══════════════════════════════════════════════════════════════════════


def try_make_real_vec_env(
    num_envs: int,
    *,
    seed: int = 0,
    env_kwargs: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Optional[VecEnv]:
    """尝试构造真环境 VecEnv；不可用返回 ``None``（不抛异常）。"""
    env_kwargs = dict(env_kwargs or {})
    try:  # 1) 环境层自带向量化（见 docs/ENV_SPEC §8）
        from hsbg.env.vec_env import VecEnv as RealVecEnv  # type: ignore

        return RealVecEnv(num_envs=num_envs, env_kwargs=env_kwargs, seed=seed)
    except Exception:
        pass
    try:  # 2) 单环境 + SyncVecEnv 兜底
        from hsbg.env import BattlegroundsEnv  # type: ignore

        seeds = [seed + i for i in range(num_envs)]

        def _factory(i: int) -> Any:
            return BattlegroundsEnv(seed=seeds[i], **env_kwargs)

        return SyncVecEnv.from_factory(_factory, num_envs, seeds=seeds)
    except Exception:
        return None


def make_vec_env(
    num_envs: int = 2,
    *,
    mode: str = "auto",
    seed: int = 0,
    env_kwargs: Optional[Dict[str, Any]] = None,
    mock_kwargs: Optional[Dict[str, Any]] = None,
) -> VecEnv:
    """``mode``: ``auto``/``real`` → 真 env 优先；``mock`` → 合成环境。"""
    mode = (mode or "auto").lower()
    if mode in ("mock", "synthetic"):
        return MockVecEnv(num_envs=num_envs, seed=seed, **(mock_kwargs or {}))
    env = try_make_real_vec_env(num_envs, seed=seed, env_kwargs=env_kwargs)
    if env is not None:
        return env
    if mode == "real":
        raise RuntimeError(
            "真环境不可用（hsbg.env 尚未实现）。请改用 --env mock 或稍后重试。"
        )
    return MockVecEnv(num_envs=num_envs, seed=seed, **(mock_kwargs or {}))


__all__ = [
    "VecEnv",
    "is_vec_env",
    "SyncVecEnv",
    "MockVecEnv",
    "normalize_step_result",
    "placement_to_reward",
    "try_make_real_vec_env",
    "make_vec_env",
]
