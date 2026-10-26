"""AZ 自对弈/评测用的策略集合（统一 245 动作接口）。

两套调用面：
- ``Policy.decide(game, seat) -> Decision``：Game 级（可做搜索、可拿引擎 bot 动作）；
- ``Policy.act_batch(features, cards, mask, turn) -> int``：BatchEnv 级（无状态/轻量），
  用于 ``BatchEnv(controlled=range(8))`` 的 8 座快速自对弈。

约定：
- 所有策略只根据**合法掩码**选动作，非法动作率应为 0（评测脚本仍会二次校验）；
- 搜索类策略返回 visit 分布 ``pi`` 作为训练目标；非搜索策略返回 one-hot（BC 目标）；
- 引擎访问全部通过 ``common.load_engine()`` 惰性加载，本模块可在无引擎机器上 import。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

import numpy as np

from .common import (
    N_ACTIONS,
    group_of,
    load_engine,
    masked_normalize,
    one_hot_policy,
    uniform_mask_policy,
)

#: 叶评估器协议：``evaluator(features, cards, mask, seat) -> (prior[245], value)``
Evaluator = Callable[[np.ndarray, np.ndarray, np.ndarray, int], tuple[np.ndarray, float]]


@dataclass
class Decision:
    """单次决策结果（搜索策略带 ``pi``）。"""

    action: int
    pi: Optional[np.ndarray] = None
    info: Dict[str, Any] = field(default_factory=dict)


def _legal(mask: Any) -> np.ndarray:
    return np.asarray(mask, dtype=bool).reshape(-1)


class Policy:
    """策略基类：名字 + reset + Game/Batch 两个入口。"""

    name = "base"
    supports_pi = False

    def reset(self) -> None:
        """一局开始前重置内部状态（默认无状态）。"""

    def decide(self, game: Any, seat: int) -> Decision:  # pragma: no cover - 抽象
        raise NotImplementedError(f"{type(self).__name__}.decide")

    def act_batch(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
                  turn: int) -> int:  # pragma: no cover - 抽象
        raise NotImplementedError(f"{type(self).__name__}.act_batch")

    def __repr__(self) -> str:  # pragma: no cover - 调试
        return f"<{type(self).__name__} name={self.name}>"


# ── 随机 ──────────────────────────────────────────────────────────────────
class RandomPolicy(Policy):
    """合法动作上的均匀随机策略。"""

    name = "random"

    def __init__(self, seed: int = 0) -> None:
        self.seed = int(seed)
        self._rng = np.random.default_rng(self.seed)

    def reset(self) -> None:
        self._rng = np.random.default_rng(self.seed)

    def _choose(self, mask: np.ndarray) -> int:
        legal = np.flatnonzero(_legal(mask))
        if legal.size == 0:
            return 0
        return int(legal[int(self._rng.integers(legal.size))])

    def decide(self, game: Any, seat: int) -> Decision:
        mask = np.frombuffer(game.legal_mask(int(seat)), dtype=np.uint8).astype(bool)
        a = self._choose(mask)
        return Decision(a, one_hot_policy(a, mask), {"search": False, "policy": self.name})

    def act_batch(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
                  turn: int) -> int:
        return self._choose(mask)


# ── 引擎内置 bot ─────────────────────────────────────────────────────────
class EngineBotPolicy(Policy):
    """引擎内置脚本 bot（``game.bot_action``）。只支持 Game 级调用。

    注意：bot 读取完整状态（含隐藏信息），属于**特权基线**，不能作为 AZ 训练输入；
    仅用于固定基线对比（docs/AZ_MCTS_SELFPLAY_DESIGN.md §2.7 的 oracle 诊断口径）。
    """

    name = "engine_bot"

    def decide(self, game: Any, seat: int) -> Decision:
        a = int(game.bot_action(int(seat)))
        mask = np.frombuffer(game.legal_mask(int(seat)), dtype=np.uint8).astype(bool)
        return Decision(a, one_hot_policy(a, mask),
                        {"search": False, "policy": self.name, "privileged": True})


# ── 脚本启发式（只用观测掩码 + 回合数）──────────────────────────────────
class HeuristicPolicy(Policy):
    """无状态（除回合计数外）脚本启发式，作为训练/搜索的冷启动先验基线。

    规则（只在合法动作中选）：
    1. 选择类（Discover/Choose 阶段）→ 第一个合法 Choose；
    2. Play 手牌随从/法术 → 最低下标；
    3. Magnetize 磁力吸附 → 最低下标；
    4. Buy 酒馆随从 → 最低下标；
    5. 前中期（turn <= upgrade_until）且有金币 → Upgrade；
    6. DarkGift / HeroPower / Activate（每回合有上限）；
    7. 金币用不出去且刷新次数未用尽 → Refresh；
    8. 否则 EndTurn。

    每回合动作数超过 ``max_steps_per_turn`` 时强制 EndTurn（防退化，正式训练由搜索价值解决）。
    """

    name = "heuristic"

    #: 搜索/消费优先级（越靠前越先考虑）
    PRIORITY = ("choose", "play", "magnetize", "buy", "upgrade", "dark_gift",
                "hero_power", "activate", "refresh", "end_turn")

    def __init__(self, *, upgrade_until: int = 8, max_refresh_per_turn: int = 3,
                 max_activate_per_turn: int = 2, max_steps_per_turn: int = 40) -> None:
        self.upgrade_until = int(upgrade_until)
        self.max_refresh_per_turn = int(max_refresh_per_turn)
        self.max_activate_per_turn = int(max_activate_per_turn)
        self.max_steps_per_turn = int(max_steps_per_turn)
        self._state: Dict[int, Dict[str, int]] = {}

    def reset(self) -> None:
        self._state = {}

    # -- 内部状态：按座位记录本回合已用次数 --
    def _slot_state(self, key: int, turn: int) -> Dict[str, int]:
        st = self._state.get(key)
        if st is None or st.get("turn") != int(turn):
            st = {"turn": int(turn), "steps": 0, "refresh": 0, "activate": 0, "upgrade": 0}
            self._state[key] = st
        return st

    def _select(self, mask: np.ndarray, turn: int, st: Dict[str, int]) -> int:
        legal = np.flatnonzero(mask)
        if legal.size == 0:
            return 0
        st["steps"] += 1
        end_turn = int(mask[0]) if mask.size > 0 else 0
        # 防退化：同一回合动作过多 -> 结束回合
        if st["steps"] > self.max_steps_per_turn and end_turn:
            return 0
        by_group: Dict[str, list[int]] = {}
        for a in legal:
            by_group.setdefault(group_of(int(a)), []).append(int(a))
        for name in self.PRIORITY:
            idx = by_group.get(name)
            if not idx:
                continue
            if name == "choose":
                return idx[0]
            if name == "play":
                return idx[0]
            if name == "magnetize":
                return idx[0]
            if name == "buy":
                return idx[0]
            if name == "upgrade":
                if turn <= self.upgrade_until and st["upgrade"] < 2:
                    st["upgrade"] += 1
                    return idx[0]
                continue
            if name == "dark_gift":
                return idx[0]
            if name == "hero_power":
                return idx[0]
            if name == "activate":
                if st["activate"] < self.max_activate_per_turn:
                    st["activate"] += 1
                    return idx[0]
                continue
            if name == "refresh":
                if st["refresh"] < self.max_refresh_per_turn:
                    st["refresh"] += 1
                    return idx[0]
                continue
            if name == "end_turn":
                return 0
        if end_turn:
            return 0
        return int(legal[0])

    def decide(self, game: Any, seat: int) -> Decision:
        seat = int(seat)
        mask = np.frombuffer(game.legal_mask(seat), dtype=np.uint8).astype(bool)
        st = self._slot_state(seat, int(game.turn))
        a = self._select(mask, int(game.turn), st)
        return Decision(a, one_hot_policy(a, mask), {"search": False, "policy": self.name})

    def act_batch(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
                  turn: int) -> int:
        m = _legal(mask)
        # BatchEnv 无座位号：以 turn 为主键（同回合内所有未结束 slot 共用计数）
        st = self._slot_state(-1, int(turn))
        return self._select(m, int(turn), st)


# ── 策略网络 ──────────────────────────────────────────────────────────────
class NetworkPolicy(Policy):
    """加载 ``hsbg.az.train.model.TinyAZNet`` 的纯策略（search-off）。"""

    name = "net"

    def __init__(self, evaluator: Evaluator) -> None:
        self.evaluator = evaluator

    def decide(self, game: Any, seat: int) -> Decision:
        seat = int(seat)
        f_raw, c_raw = game.observe(seat)
        f = np.frombuffer(f_raw, dtype="<f4").copy()
        c = np.frombuffer(c_raw, dtype="<i4").copy()
        mask = np.frombuffer(game.legal_mask(seat), dtype=np.uint8).astype(bool)
        prior, value = self.evaluator(f, c, mask, seat)
        pi = masked_normalize(prior, mask)
        a = int(np.argmax(pi)) if float(pi.sum()) > 0 else int(np.flatnonzero(mask)[0])
        return Decision(a, pi, {"search": False, "policy": self.name, "value": float(value)})

    def act_batch(self, features: np.ndarray, cards: np.ndarray, mask: np.ndarray,
                  turn: int) -> int:
        prior, _value = self.evaluator(np.asarray(features, np.float32),
                                       np.asarray(cards, np.int32),
                                       np.asarray(mask, bool), -1)
        pi = masked_normalize(prior, mask)
        return int(np.argmax(pi)) if float(pi.sum()) > 0 else 0


# ── Rust 搜索核（hsbg_engine.mcts_search）────────────────────────────────
def _rust_eval_adapter(evaluator: Evaluator):
    """把 ndarray 评估器适配成 Rust ``mcts_search`` 的 bytes 回调。"""

    def eval_fn(features_bytes, cards_bytes, mask_bytes, seat):
        f = np.frombuffer(features_bytes, dtype="<f4")
        c = np.frombuffer(cards_bytes, dtype="<i4")
        m = np.frombuffer(mask_bytes, dtype=np.uint8).astype(bool)
        prior, value = evaluator(f, c, m, int(seat))
        return np.asarray(prior, dtype=np.float32).tobytes(), float(value)

    return eval_fn


class RustMCTSPolicy(Policy):
    """Rust 搜索核 PUCT（``hsbg_engine.mcts_search``）。

    - ``rollout=True``：叶价值 = 引擎 bot 全 rollout（P4-B 纯搜索模式，无需网络）；
    - ``evaluator``：叶价值 = 策略/价值网络（AlphaZero 口径）。
    注意：rollout 模式存在已知的 off-policy 价值偏差（docs/AZ_PURE_SEARCH_TEST.md §3）。
    """

    name = "search_rust"
    supports_pi = True

    def __init__(self, simulations: int = 8, c_puct: float = 1.5, temperature: float = 1.0,
                 seed: int = 0, rollout: bool = False, evaluator: Optional[Evaluator] = None,
                 dirichlet_alpha: float = 0.3, dirichlet_epsilon: float = 0.0) -> None:
        self.E = load_engine()
        self.simulations = int(simulations)
        self.c_puct = float(c_puct)
        self.temperature = float(temperature)
        self.seed = int(seed)
        self.rollout = bool(rollout)
        self.dirichlet_alpha = float(dirichlet_alpha)
        self.dirichlet_epsilon = float(dirichlet_epsilon)
        self.evaluator = evaluator
        self._eval_fn = None if (self.rollout or evaluator is None) else _rust_eval_adapter(evaluator)
        self._n = 0

    def reset(self) -> None:
        self._n = 0

    def decide(self, game: Any, seat: int) -> Decision:
        seat = int(seat)
        kw: Dict[str, Any] = dict(
            simulations=self.simulations,
            c_puct=self.c_puct,
            temperature=self.temperature,
            eval_fn=self._eval_fn,
            seed=self.seed + self._n,
            dirichlet_alpha=self.dirichlet_alpha,
            dirichlet_epsilon=self.dirichlet_epsilon,
        )
        self._n += 1
        if self.rollout:
            kw["rollout"] = True
        try:
            pi_b, action, root_value, visits = self.E.mcts_search(game, seat, **kw)
        except TypeError:
            # 旧构建无 rollout 形参：退回普通 eval 模式（uniform prior + value 0）
            kw.pop("rollout", None)
            pi_b, action, root_value, visits = self.E.mcts_search(game, seat, **kw)
        mask = np.frombuffer(game.legal_mask(seat), dtype=np.uint8).astype(bool)
        pi = masked_normalize(np.frombuffer(pi_b, dtype="<f4"), mask)
        a = int(action)
        if not (0 <= a < N_ACTIONS and bool(mask[a])):
            a = int(np.argmax(pi)) if float(pi.sum()) > 0 else int(np.flatnonzero(mask)[0])
        return Decision(a, pi, {"search": True, "policy": self.name,
                                "root_value": float(root_value), "visits": int(visits),
                                "simulations": self.simulations, "rollout": self.rollout})


# ── Python 原型搜索（hsbg/search/engine_mcts.py，只读复用）───────────────
class PythonMCTSPolicy(Policy):
    """复用既有 Python MCTS 原型（``hsbg.search.engine_mcts``）作为对照搜索策略。"""

    name = "search_py"
    supports_pi = True

    def __init__(self, simulations: int = 8, c_puct: float = 1.5, temperature: float = 1.0,
                 seed: int = 0, evaluator: Optional[Evaluator] = None,
                 dirichlet_alpha: float = 0.3, dirichlet_epsilon: float = 0.0) -> None:
        from hsbg.search.engine_mcts import MCTSConfig  # 惰性：无引擎机器也可 import 本模块

        self.MCTSConfig = MCTSConfig
        self.cfg = MCTSConfig(simulations=int(simulations), c_puct=float(c_puct),
                              temperature=float(temperature), seed=int(seed),
                              dirichlet_alpha=float(dirichlet_alpha),
                              dirichlet_epsilon=float(dirichlet_epsilon))
        self.evaluator = evaluator
        self._n = 0

    def reset(self) -> None:
        self._n = 0

    def decide(self, game: Any, seat: int) -> Decision:
        from hsbg.search.engine_mcts import search as py_search  # 惰性

        if self.evaluator is None:
            raise RuntimeError("PythonMCTSPolicy 需要 evaluator(features,cards,mask,seat)")
        seat = int(seat)
        cfg = self.MCTSConfig(**{**self.cfg.__dict__, "seed": self.cfg.seed + self._n})
        self._n += 1
        pi, action, stats = py_search(game, seat, self.evaluator, cfg)
        mask = np.frombuffer(game.legal_mask(seat), dtype=np.uint8).astype(bool)
        pi = masked_normalize(pi, mask)
        return Decision(int(action), pi, {"search": True, "policy": self.name,
                                         "root_value": float(stats.get("root_value", 0.0)),
                                         "visits": int(stats.get("visits", 0)),
                                         "simulations": self.cfg.simulations})


# ── hsbg.az 搜索原型（task-2，search-architect）───────────────────────────
def _normalize_search_result(res: Any) -> tuple[int, np.ndarray, Dict[str, Any]]:
    """把 task-2 的返回值规范化为 ``(action, pi, info)``（支持 dataclass/tuple/dict）。"""
    if isinstance(res, dict):
        action = res.get("action")
        pi = res.get("pi")
        info = {k: v for k, v in res.items() if k not in ("action", "pi")}
        return int(action), np.asarray(pi, dtype=np.float32), info
    if isinstance(res, (tuple, list)):
        # 兼容 hsbg.search.engine_mcts: (pi, action, stats)
        if len(res) >= 2 and np.ndim(res[0]) == 1 and np.size(res[0]) == N_ACTIONS:
            pi = np.asarray(res[0], dtype=np.float32)
            action = int(res[1])
            info = dict(res[2]) if len(res) > 2 and isinstance(res[2], dict) else {}
            return action, pi, info
        return int(res[0]), np.asarray(res[1], dtype=np.float32), {}
    # dataclass SearchResult
    action = int(getattr(res, "action"))
    pi = np.asarray(getattr(res, "pi"), dtype=np.float32)
    info = {
        "root_value": float(getattr(res, "root_value", 0.0)),
        "visits": int(getattr(res, "visits", 0)),
        "n_simulations": int(getattr(res, "n_simulations", 0)),
        "determinizations": int(getattr(res, "determinizations", 0)),
        "elapsed_s": float(getattr(res, "elapsed_s", 0.0)),
        "fallback": bool(getattr(res, "fallback", False)),
    }
    extra = getattr(res, "info", None)
    if isinstance(extra, dict):
        info.update(extra)
    return action, pi, info


class AZSearchPolicy(Policy):
    """接入 ``hsbg.az.search``（search-architect 的不完全信息搜索原型）。

    接口（2026-10-26 冻结）：``search(game, seat, *, config=None, eval_fn=None,
    engine_backend="auto", **cfg_overrides) -> SearchResult``。
    """

    name = "search_az"
    supports_pi = True

    def __init__(self, simulations: int = 16, determinizations: int = 1,
                 c_puct: float = 1.5, temperature: float = 1.0, seed: int = 0,
                 evaluator: Optional[Evaluator] = None, engine_backend: str = "auto",
                 dirichlet_alpha: float = 0.3, dirichlet_epsilon: float = 0.0,
                 search_config: Any = None) -> None:
        try:
            from hsbg.az import search as az_search  # type: ignore
            from hsbg.az import SearchConfig  # type: ignore
        except Exception as exc:  # noqa: BLE001 - task-2 尚未完成时给出可读错误
            raise RuntimeError(
                "hsbg.az 搜索原型不可用（task-2 未完成或 import 失败）："
                f"{exc!r}；可先用 --policies search_rust/search_py 兜底"
            ) from exc
        self._search = az_search
        self.SearchConfig = SearchConfig
        if search_config is not None:
            self.config = search_config
        else:
            self.config = SearchConfig(
                simulations=int(simulations), determinizations=int(determinizations),
                c_puct=float(c_puct), temperature=float(temperature), seed=int(seed),
                dirichlet_alpha=float(dirichlet_alpha),
                dirichlet_epsilon=float(dirichlet_epsilon),
            )
        self.evaluator = evaluator
        self.engine_backend = engine_backend
        self._n = 0
        self._base_seed = int(seed)

    def reset(self) -> None:
        self._n = 0

    def decide(self, game: Any, seat: int) -> Decision:
        seat = int(seat)
        kw: Dict[str, Any] = {"config": self.config, "eval_fn": self.evaluator,
                              "engine_backend": self.engine_backend,
                              "seed": self._base_seed + self._n}
        self._n += 1
        res = self._search(game, seat, **kw)
        action, pi, info = _normalize_search_result(res)
        mask = np.frombuffer(game.legal_mask(seat), dtype=np.uint8).astype(bool)
        pi = masked_normalize(pi, mask)
        if not (0 <= action < N_ACTIONS and bool(mask[action])):
            action = int(np.argmax(pi)) if float(pi.sum()) > 0 else int(np.flatnonzero(mask)[0])
        info = dict(info)
        info.update({"search": True, "policy": self.name})
        return Decision(action, pi, info)


# ── 工厂 ──────────────────────────────────────────────────────────────────
def make_policy(name: str, **kwargs: Any) -> Policy:
    """按名字构造策略。

    支持：``random`` / ``bot``(engine_bot) / ``heuristic`` / ``net`` /
    ``search_rust`` / ``search_rust_rollout`` / ``search_py`` / ``search_az``。
    """
    key = str(name).strip().lower()
    if key in ("random", "rand"):
        return RandomPolicy(seed=int(kwargs.get("seed", 0)))
    if key in ("bot", "engine_bot", "engine-bot"):
        return EngineBotPolicy()
    if key in ("heuristic", "heur"):
        return HeuristicPolicy(**{k: v for k, v in kwargs.items()
                                  if k in ("upgrade_until", "max_refresh_per_turn",
                                           "max_activate_per_turn", "max_steps_per_turn")})
    if key in ("net", "network", "policy_net"):
        if "evaluator" not in kwargs:
            raise ValueError("net 策略需要 evaluator=...")
        return NetworkPolicy(kwargs["evaluator"])
    if key in ("search_rust", "rust", "mcts_rust"):
        return RustMCTSPolicy(**{k: v for k, v in kwargs.items()
                                 if k in ("simulations", "c_puct", "temperature", "seed",
                                          "rollout", "evaluator", "dirichlet_alpha",
                                          "dirichlet_epsilon")})
    if key in ("search_rust_rollout", "rust_rollout", "rollout"):
        kw = {k: v for k, v in kwargs.items()
              if k in ("simulations", "c_puct", "temperature", "seed",
                       "dirichlet_alpha", "dirichlet_epsilon")}
        kw["rollout"] = True
        return RustMCTSPolicy(**kw)
    if key in ("search_py", "python", "mcts_py"):
        return PythonMCTSPolicy(**{k: v for k, v in kwargs.items()
                                   if k in ("simulations", "c_puct", "temperature", "seed",
                                            "evaluator", "dirichlet_alpha",
                                            "dirichlet_epsilon")})
    if key in ("search_az", "az", "mcts_az"):
        return AZSearchPolicy(**{k: v for k, v in kwargs.items()
                                 if k in ("simulations", "determinizations", "c_puct",
                                          "temperature", "seed", "evaluator",
                                          "engine_backend", "dirichlet_alpha",
                                          "dirichlet_epsilon", "search_config")})
    raise ValueError(f"未知策略: {name!r}")


__all__ = [
    "Decision",
    "Policy",
    "RandomPolicy",
    "EngineBotPolicy",
    "HeuristicPolicy",
    "NetworkPolicy",
    "RustMCTSPolicy",
    "PythonMCTSPolicy",
    "AZSearchPolicy",
    "make_policy",
    "_rust_eval_adapter",
    "_normalize_search_result",
]
