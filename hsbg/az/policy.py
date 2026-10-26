"""冷启动策略/价值估计器与基线 agent（不依赖 NN，AlphaZero 训练闭环的 bootstrap）。

为什么需要：`docs/AZ_1K_VALIDATION.md` 的实测表明，从零随机网络 + 低 sims 搜索会退化
（41% 根动作为 EndTurn、名次 8）。搜索要"产出足够质量的对局/决策"，必须先有可用的
叶评估（先验 + 价值）+ 安全回退；本模块提供：

- `heuristic_prior(obs)`：仅用公开观测的规则先验（买入/升级/技能/结束回合的偏好）；
- `heuristic_value(obs)`：公开可观测局面的期望名次效用近似（血量/护甲/战团强度/等级）；
- `uniform_evaluator` / `heuristic_evaluator` / `RolloutEvaluator`（截断 rollout，Python 后端）；
- 基线 agent：`RandomAgent` / `HeuristicAgent` / `BotAgent` / `SearchAgent`。

所有估计器都只接收 `ObsView`（observe 的 features/cards/mask），不接受隐藏状态。
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from . import env_api as EA
from .puct import masked_prior, sample_action

# 动作段边界（同 env_api / ACTION_SPACE_STD）
_A_END = EA.A_END
_A_REFRESH = EA.A_REFRESH
_A_FREEZE = EA.A_FREEZE
_A_UPGRADE = EA.A_UPGRADE
_A_HERO_POWER = EA.A_HERO_POWER
_A_DARK_GIFT = EA.A_DARK_GIFT
_A_CANCEL = EA.A_CANCEL
_A_BUY = EA.A_BUY
_A_SELL = EA.A_SELL
_A_ACTIVATE = EA.A_ACTIVATE
_A_CHOOSE = EA.A_CHOOSE
_A_PLAY = EA.A_PLAY
_A_MAGNETIZE = EA.A_MAGNETIZE
_A_MOVE = EA.A_MOVE


def _legal_between(mask: np.ndarray, lo: int, hi: int) -> np.ndarray:
    idx = np.arange(lo, min(hi, mask.shape[0]), dtype=np.int64)
    return idx[mask[idx]]


def _try_public(obs: EA.ObsView):
    """取公开信息；非标准观测（toy/测试 env）解码失败时返回 None。"""
    try:
        return obs.public
    except Exception:  # noqa: BLE001 - 非 3227 观测（toy）
        return None


def _generic_prior(obs: EA.ObsView) -> np.ndarray:
    """非标准 env（toy）的通用先验：合法动作均匀，轻微偏好非 EndTurn。"""
    mask = np.asarray(obs.mask, dtype=bool)
    w = np.where(mask, 1.0, 0.0).astype(np.float32)
    if mask.shape[0] > 0 and mask[0]:
        w[0] = 0.35
    return masked_prior(w, mask)


def heuristic_prior(obs: EA.ObsView) -> np.ndarray:
    """规则先验（确定性、只读 ObsView）。返回 f32[245]，非法动作为 0，和=1。"""
    pub = _try_public(obs)
    if pub is None:
        return _generic_prior(obs)
    mask = np.asarray(obs.mask, dtype=bool)
    n = mask.shape[0]
    w = np.where(mask, 0.02, 0.0).astype(np.float32)

    # 0) 待选（Discover/ChooseOne/Target 等）：优先把质量放在选择类动作上
    choose = _legal_between(mask, _A_CHOOSE, _A_PLAY)
    play = _legal_between(mask, _A_PLAY, _A_MAGNETIZE)
    if choose.size:
        w[choose] += 3.0
    if pub.has_pending_choice and choose.size:
        # 有待选项目（Discover/ChooseOne 等）且 Choose 合法：在合法动作里较均匀探索，
        # 避免规则先验误判；若 Choose 不在合法集中（target/trinket 等），继续走常规规则。
        w[mask] += 0.3
        return masked_prior(w, mask)

    # 1) 买入：优先可负担的酒馆随从；棋盘已满则不加
    board_full = pub.board_len >= EA.N_BOARD
    affordable_buys = 0
    for slot, price in enumerate(pub.shop_prices):
        a = _A_BUY + slot
        if a >= n or not mask[a]:
            continue
        if pub.gold >= price and not board_full:
            w[a] += 3.0
            affordable_buys += 1
        else:
            w[a] += 0.05

    # 2) 升级：金币富余且未满级
    if mask[_A_UPGRADE]:
        can_up = pub.tier < 6 and pub.gold >= pub.upgrade_price + 2
        w[_A_UPGRADE] += 2.0 if can_up else 0.2

    # 3) 英雄技能：可用且费用可负担
    for a in (_A_HERO_POWER, _A_HERO_POWER + 1):
        if a < n and mask[a]:
            w[a] += 1.2

    # 4) 刷新：没有可买时更愿意刷
    if mask[_A_REFRESH]:
        w[_A_REFRESH] += 0.15 if affordable_buys else 0.9

    # 5) 打出/出售/技能触发/磁力/移动
    # 买入的随从进手牌，必须 Play 到棋盘才形成战力；手牌非空时 Play 权重必须压过 EndTurn，
    # 否则规则先验会"买了不打出、直接结束回合"（实测 rank 8 的退化路径）。
    if pub.hand_len > 0 and play.size:
        w[play] += 5.0
    sell = _legal_between(mask, _A_SELL, _A_ACTIVATE)
    if sell.size:
        w[sell] += 0.15
    act = _legal_between(mask, _A_ACTIVATE, _A_CHOOSE)
    if act.size:
        w[act] += 0.6
    if mask[_A_DARK_GIFT]:
        w[_A_DARK_GIFT] += 0.4
    if mask[_A_CANCEL]:
        w[_A_CANCEL] += 0.1
    if mask[_A_FREEZE]:
        w[_A_FREEZE] += 0.05
    for a in range(_A_MAGNETIZE, n):
        if mask[a]:
            w[a] += 0.03

    # 6) 结束回合：有钱可买或手牌可打时不要结束
    if mask[_A_END]:
        must_play = pub.hand_len > 0 and play.size > 0
        if must_play:
            w[_A_END] += 0.02
        elif pub.gold <= 0 or board_full or affordable_buys == 0:
            w[_A_END] += 0.9
        else:
            w[_A_END] += 0.15

    return masked_prior(w, mask)


def heuristic_value(obs: EA.ObsView, seat: Optional[int] = None) -> float:
    """公开可观测局面的期望 utility 近似（∈[-1,1]，8 人名次口径的粗代理）。

    只用：己方血量/护甲/等级/棋盘 atk+hp、存活人数、对手公开血量。不是训练价值目标
    （训练仍只用终局名次，D9），只作搜索叶评估的 cold-start bootstrap。
    """
    pub = _try_public(obs)
    if pub is None:
        return 0.0
    turn = float(max(0, pub.turn))
    hp = float(pub.health + pub.armor)
    power = float(pub.board_power)
    expected_power = 6.0 + 5.0 * turn
    v = 0.45 * np.tanh((hp - 20.0) / 20.0)
    v += 0.38 * np.tanh((power - expected_power) / 25.0)
    v += 0.17 * np.tanh((float(pub.tier) - 3.0) / 2.0)
    alive_opps = [o for o in pub.opponents if o.present and o.alive]
    if alive_opps:
        mean_opp_hp = float(np.mean([o.health + o.armor for o in alive_opps]))
        v += 0.10 * np.tanh((hp - mean_opp_hp) / 25.0)
    return float(np.clip(v, -1.0, 1.0))


# ── evaluator 可调用对象（统一签名：call(obs, seat, game=None)）──────────────


class UniformEvaluator:
    """均匀合法先验 + value=0（纯探索基线；对应 Rust rollout=False 且无模型）。"""

    name = "uniform"
    accepts_game = False

    def __call__(self, obs: EA.ObsView, seat: int, game: Any = None):
        n = int(obs.mask.sum())
        prior = obs.mask.astype(np.float32) / float(n) if n > 0 else np.zeros_like(
            obs.mask, dtype=np.float32)
        return prior, 0.0


class HeuristicEvaluator:
    """规则先验 + 公开局面价值（默认冷启动评估器，无 NN 也能跑出非退化搜索）。"""

    name = "heuristic"
    accepts_game = False

    def __call__(self, obs: EA.ObsView, seat: int, game: Any = None):
        return heuristic_prior(obs), heuristic_value(obs, seat)


class BotPriorEvaluator:
    """引擎脚本 bot 动作做先验 + 公开局面价值（game-aware，需要 Python 搜索后端）。

    动机：纯规则先验比引擎 bot 弱很多（实测 rank 8 vs 2.6）。把 bot 的单步选择作为
    **先验**（而非 rollout 的终局价值，后者 off-policy 偏差大）可以让搜索围绕脚本策略
    做有限前瞻，同时保留少量规则先验质量用于探索其它动作。
    """

    name = "bot_prior"
    accepts_game = True

    def __init__(self, blend: float = 0.75):
        self.blend = float(np.clip(blend, 0.0, 1.0))

    def __call__(self, obs: EA.ObsView, seat: int, game: Any = None):
        prior = heuristic_prior(obs)
        if game is None:
            return prior, heuristic_value(obs, seat)
        try:
            a = int(EA.bot_action(game, int(seat)))
        except Exception:  # noqa: BLE001
            return prior, heuristic_value(obs, seat)
        mask = np.asarray(obs.mask, dtype=bool)
        if 0 <= a < mask.shape[0] and bool(mask[a]):
            prior = (1.0 - self.blend) * prior
            prior[a] += self.blend
            prior = masked_prior(prior, mask)
        return prior, heuristic_value(obs, seat)


class RolloutEvaluator:
    """截断 rollout 叶价值：用规则策略推进 `horizon` 个"单座决策"后取启发式价值。

    只在 Python 搜索后端生效（需要 env 对象）；Rust 回调只有观测，回退到启发式价值。
    相比 `bot::play_turn` 打到终局（off-policy 不匹配，见 AZ_PURE_SEARCH_TEST.md），
    截断 rollout 只外推很近的未来，偏差更小、成本可控。
    """

    name = "rollout"
    accepts_game = True

    def __init__(self, horizon: int = 8, *, heuristic=None):
        self.horizon = int(max(0, horizon))
        self._heuristic = heuristic or HeuristicEvaluator()

    def __call__(self, obs: EA.ObsView, seat: int, game: Any = None):
        prior, _ = self._heuristic(obs, seat)
        if game is None or self.horizon <= 0:
            return prior, heuristic_value(obs, seat)
        g = game.copy()
        for _ in range(self.horizon):
            if EA.is_over(g):
                break
            acted = False
            for p in range(EA.num_players(g)):
                if EA.needs_action(g, p):
                    try:
                        EA.step(g, p, int(np.argmax(heuristic_prior(EA.observe(g, p)))))
                    except Exception:  # noqa: BLE001 - 非法动作：跳过该座位
                        break
                    acted = True
                    break
            if not acted:
                break
        return prior, heuristic_value(EA.observe(g, seat), seat)


class CallableEvaluator:
    """把外部 `fn(obs, seat)` 包成 evaluator。"""

    def __init__(self, fn, name: str = "custom"):
        self.fn = fn
        self.name = name
        self.accepts_game = False

    def __call__(self, obs: EA.ObsView, seat: int, game: Any = None):
        return self.fn(obs, seat)


def make_evaluator(name: str = "heuristic", **kwargs):
    """工厂：'uniform' | 'heuristic' | 'rollout' | 'bot_prior' | 'none'。"""
    key = (name or "heuristic").lower()
    if key in ("none", "heuristic", "heuristic_v0"):
        return HeuristicEvaluator()
    if key == "uniform":
        return UniformEvaluator()
    if key in ("rollout", "truncated_rollout"):
        return RolloutEvaluator(**kwargs)
    if key in ("bot_prior", "bot"):
        return BotPriorEvaluator(**kwargs)
    raise ValueError(f"未知 evaluator: {name}")


# ── 基线 agents ──────────────────────────────────────────────────────────────


class Agent:
    """最小 agent 协议：`act(game, seat) -> int`。"""

    name = "agent"

    def act(self, game: Any, seat: int) -> int:  # pragma: no cover
        raise NotImplementedError

    def reset(self, seed: int = 0) -> None:  # 可选：每局重置内部 RNG
        pass


class RandomAgent(Agent):
    """均匀随机合法动作（固定 seed 可复现）。"""

    def __init__(self, seed: int = 0):
        self.name = "random"
        self.rng = random.Random(int(seed))

    def reset(self, seed: int = 0) -> None:
        self.rng = random.Random(int(seed))

    def act(self, game: Any, seat: int) -> int:
        legal = np.flatnonzero(EA.legal_mask(game, seat))
        if legal.size == 0:
            return 0
        return int(legal[self.rng.randrange(int(legal.size))])


class HeuristicAgent(Agent):
    """规则先验 argmax（search-off 基线；也是 self-play 的快速策略）。"""

    name = "heuristic"

    def act(self, game: Any, seat: int) -> int:
        obs = EA.observe(game, seat)
        legal = np.flatnonzero(obs.mask)
        if legal.size == 0:
            return 0
        p = heuristic_prior(obs)
        return int(np.argmax(p))


class BotAgent(Agent):
    """引擎内置脚本 bot（`Game.bot_action`）。"""

    name = "bot"

    def act(self, game: Any, seat: int) -> int:
        return EA.bot_action(game, seat)


class SearchAgent(Agent):
    """搜索策略：每次决策调用 `hsbg.az.search`，返回动作；保留最后结果用于诊断。"""

    def __init__(self, config=None, *, evaluator=None, belief=None,
                 backend: str = "auto", name: Optional[str] = None):
        self._config = config
        self._evaluator = evaluator
        self._belief = belief
        self.backend = backend
        self.name = name or "search"
        self.last = None
        self.results: List[Any] = []
        self.n_fallbacks = 0

    def act(self, game: Any, seat: int) -> int:
        from .search import search  # 延迟导入避免环

        res = search(game, seat, config=self._config, eval_fn=self._evaluator,
                     belief=self._belief, engine_backend=self.backend)
        self.last = res
        self.results.append(res)
        if getattr(res, "fallback", False):
            self.n_fallbacks += 1
        # 安全回退：搜索动作必须合法（理论上已保证；防御性检查）
        mask = EA.legal_mask(game, seat)
        if 0 <= int(res.action) < mask.shape[0] and bool(mask[int(res.action)]):
            return int(res.action)
        return EA.bot_action(game, seat)

    def reset(self, seed: int = 0) -> None:
        self.results = []
        self.last = None
        self.n_fallbacks = 0


__all__ = [
    "Agent", "BotAgent", "CallableEvaluator", "HeuristicAgent", "HeuristicEvaluator",
    "RandomAgent", "RolloutEvaluator", "SearchAgent", "UniformEvaluator",
    "heuristic_prior", "heuristic_value", "make_evaluator",
]
