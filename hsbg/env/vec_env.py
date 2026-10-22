"""向量化环境（训练入口）。

接口（ENV_SPEC §8）::

    vec = VecEnv(num_envs=8, env_kwargs={"num_players": 8}, seed=42)
    obs_list = vec.reset()                      # List[Observation]
    obs, rewards, dones, infos = vec.step(actions)
    vec.close()

- ``VecEnv`` 默认用 ``multiprocessing``（Windows 必须 **spawn**：
  worker 是模块级顶层函数，``if __name__ == "__main__"`` 安全）。
- ``SyncVecEnv`` 是同接口的单进程实现（调试 / 多进程受限环境的后备）；
  ``VecEnv(multiprocess=False)`` 等价于 ``SyncVecEnv``。
- 支持 auto-reset：``dones[i] == True`` 时该槽位的 ``obs[i]`` 已是新一局
  的首个观测，旧局终局观测放在 ``infos[i]["terminal_observation"]``。

确定性：第 ``i`` 个环境第 ``k`` 局的种子 = ``seed + i + k * num_envs``
（``seed=None`` 时各环境自行取系统熵）。
"""

from __future__ import annotations

import multiprocessing as mp
from typing import Any, Dict, List, Optional, Sequence, Tuple

from hsbg.env.game_env import BattlegroundsEnv
from hsbg.env.spec import Observation

__all__ = ["VecEnv", "SyncVecEnv"]

_CMD_RESET = "reset"
_CMD_STEP = "step"
_CMD_CLOSE = "close"


# ══════════════════════════════════════════════════════════════════════
# 多进程 worker（顶层函数：Windows spawn 必须可导入）
# ══════════════════════════════════════════════════════════════════════


def _worker_main(remote: Any, env_kwargs: Dict[str, Any],
                 seed: Optional[int], auto_reset: bool) -> None:
    """子进程主循环：持有 1 个环境，按命令 reset/step/close。"""
    env: Optional[BattlegroundsEnv] = None
    episode = 0
    try:
        env = BattlegroundsEnv(**env_kwargs)
        while True:
            try:
                cmd, data = remote.recv()
            except EOFError:
                break
            if cmd == _CMD_RESET:
                episode = 0
                base = data if data is not None else seed
                ep_seed = None if base is None else int(base)
                obs = env.reset(seed=ep_seed)
                remote.send(obs)
            elif cmd == _CMD_STEP:
                obs, reward, terminated, truncated, info = env.step(data)
                if (terminated or truncated) and auto_reset:
                    terminal = env.current_observation
                    episode += 1
                    ep_seed = None if seed is None \
                        else int(seed) + episode
                    new_obs = env.reset(seed=ep_seed)
                    info = dict(info)
                    info["terminal_observation"] = terminal
                    info["terminal"] = True
                    obs = new_obs
                remote.send((obs, float(reward), bool(terminated),
                             bool(truncated), info))
            elif cmd == _CMD_CLOSE:
                remote.send(True)
                break
            else:                                     # pragma: no cover
                remote.send(("error", f"unknown cmd {cmd!r}"))
    except Exception as exc:                          # noqa: BLE001
        try:
            remote.send(("worker_error", f"{type(exc).__name__}: {exc}"))
        except Exception:                             # noqa: BLE001
            pass
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:                         # noqa: BLE001
                pass
        try:
            remote.close()
        except Exception:                             # noqa: BLE001
            pass


# ══════════════════════════════════════════════════════════════════════
# VecEnv
# ══════════════════════════════════════════════════════════════════════


class VecEnv:
    """多环境向量化封装（默认多进程；``multiprocess=False`` 时单进程）。"""

    def __init__(self, num_envs: int = 8,
                 env_kwargs: Optional[Dict[str, Any]] = None,
                 seed: Optional[int] = None, *,
                 multiprocess: bool = True,
                 auto_reset: bool = True,
                 start_method: str = "spawn") -> None:
        self.num_envs = int(num_envs)
        if self.num_envs <= 0:
            raise ValueError("num_envs must be positive")
        self.env_kwargs = dict(env_kwargs or {})
        self.seed = seed
        self.auto_reset = bool(auto_reset)
        self.multiprocess = bool(multiprocess)
        self._closed = False
        #: 最近一次 step 的 done / info（ENV_SPEC: 供训练循环读取）
        self.dones: List[bool] = [False] * self.num_envs
        self.infos: List[Dict[str, Any]] = [{} for _ in range(self.num_envs)]
        self._envs: List[BattlegroundsEnv] = []
        self._procs: List[Any] = []
        self._remotes: List[Any] = []
        self._episodes: List[int] = [0] * self.num_envs

        if self.multiprocess:
            ctx = mp.get_context(start_method)
            for i in range(self.num_envs):
                parent_remote, child_remote = ctx.Pipe()
                proc = ctx.Process(
                    target=_worker_main,
                    args=(child_remote, self.env_kwargs,
                          None if self.seed is None else int(self.seed) + i,
                          self.auto_reset),
                    daemon=True)
                proc.start()
                child_remote.close()
                self._remotes.append(parent_remote)
                self._procs.append(proc)
        else:
            for i in range(self.num_envs):
                self._envs.append(BattlegroundsEnv(**self.env_kwargs))

    # ── 生命周期 ──

    def reset(self, seed: Optional[int] = None,
              options: Any = None) -> List[Observation]:
        """重置全部环境并返回首个观测列表。"""
        self._check_open()
        base = self.seed if seed is None else seed
        seeds: List[Optional[int]] = []
        for i in range(self.num_envs):
            seeds.append(None if base is None else int(base) + i)
        if self.multiprocess:
            for remote, s in zip(self._remotes, seeds):
                remote.send((_CMD_RESET, s))
            return [self._recv(remote) for remote in self._remotes]
        return [env.reset(seed=s) for env, s in zip(self._envs, seeds)]

    def step(self, actions: Sequence[Any]
             ) -> Tuple[List[Observation], List[float], List[bool],
                        List[Dict[str, Any]]]:
        """向各环境推进一步（auto-reset 在环境内部完成）。"""
        self._check_open()
        actions = list(actions)
        if len(actions) != self.num_envs:
            raise ValueError(
                f"expected {self.num_envs} actions, got {len(actions)}")
        if self.multiprocess:
            for remote, action in zip(self._remotes, actions):
                remote.send((_CMD_STEP, action))
            raw = [self._recv(remote) for remote in self._remotes]
            obs, rewards, dones, infos = [], [], [], []
            for item in raw:
                o, r, term, trunc, info = item
                obs.append(o)
                rewards.append(r)
                dones.append(bool(term or trunc))
                infos.append(info)
        else:
            obs, rewards, dones, infos = [], [], [], []
            for idx, (env, action) in enumerate(zip(self._envs, actions)):
                o, r, term, trunc, info = env.step(action)
                if (term or trunc) and self.auto_reset:
                    terminal = env.current_observation
                    self._episodes[idx] += 1
                    ep_seed = None if self.seed is None else \
                        int(self.seed) + idx + self._episodes[idx] * self.num_envs
                    o = env.reset(seed=ep_seed)
                    info = dict(info)
                    info["terminal_observation"] = terminal
                    info["terminal"] = True
                obs.append(o)
                rewards.append(float(r))
                dones.append(bool(term or trunc))
                infos.append(info)
        self.dones = list(dones)
        self.infos = list(infos)
        return obs, rewards, dones, infos

    def close(self) -> None:
        """关闭全部 worker / 环境。"""
        if self._closed:
            return
        self._closed = True
        if self.multiprocess:
            for remote in self._remotes:
                try:
                    remote.send((_CMD_CLOSE, None))
                except Exception:                     # noqa: BLE001
                    pass
            for remote, proc in zip(self._remotes, self._procs):
                try:
                    remote.recv()
                except Exception:                     # noqa: BLE001
                    pass
                try:
                    remote.close()
                except Exception:                     # noqa: BLE001
                    pass
                try:
                    proc.join(timeout=2.0)
                except Exception:                     # noqa: BLE001
                    pass
            self._remotes = []
            self._procs = []
        else:
            for env in self._envs:
                try:
                    env.close()
                except Exception:                     # noqa: BLE001
                    pass
            self._envs = []

    # ── 工具 ──

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("VecEnv is closed")

    @staticmethod
    def _recv(remote: Any) -> Any:
        msg = remote.recv()
        if isinstance(msg, tuple) and msg and msg[0] == "worker_error":
            raise RuntimeError(f"VecEnv worker failed: {msg[1]}")
        return msg

    def __enter__(self) -> "VecEnv":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __len__(self) -> int:
        return self.num_envs


class SyncVecEnv(VecEnv):
    """单进程多环境（等价 ``VecEnv(multiprocess=False)``）。"""

    def __init__(self, num_envs: int = 8,
                 env_kwargs: Optional[Dict[str, Any]] = None,
                 seed: Optional[int] = None, *,
                 auto_reset: bool = True) -> None:
        super().__init__(num_envs=num_envs, env_kwargs=env_kwargs,
                         seed=seed, multiprocess=False,
                         auto_reset=auto_reset)
