"""策略与基线评测：平均名次 / 胜率 / 前四率 / 平均回报。

支持两类"智能体"：

* :class:`PolicyAgent` —— 神经网络策略（贪心或采样）；
* :class:`RandomAgent` / :class:`HeuristicAgent` —— 候选级基线，用于对比。

评测对象是 ``VecEnv``（``reset/step/close``，自动 reset），因此同一套代码
既可用于真环境，也可用于 :class:`hsbg.train.vec_env.MockVecEnv`。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence

import numpy as np

from hsbg.env.spec import (
    PLAYER_MAX,
    ZONE_BOARD,
    ZONE_TAVERN,
    CandidateAction,
    Observation,
)
from hsbg.policy.encoder import ObservationEncoder


class Agent(Protocol):
    """评测用智能体协议：``act(obs_list) -> List[int]``。"""

    name: str

    def act(self, obs_list: Sequence[Observation]) -> List[int]:  # pragma: no cover
        ...


# ══════════════════════════════════════════════════════════════════════
# 智能体实现
# ══════════════════════════════════════════════════════════════════════


class PolicyAgent:
    """神经网络策略包装（批量推理）。"""

    def __init__(
        self,
        policy: Any,
        encoder: ObservationEncoder,
        *,
        device: str = "cpu",
        greedy: bool = True,
        name: str = "policy",
    ) -> None:
        import torch

        self.policy = policy
        self.encoder = encoder
        self.device = torch.device(device)
        self.greedy = greedy
        self.name = name
        self.policy.to(self.device)
        self.policy.eval()

    def act(self, obs_list: Sequence[Observation]) -> List[int]:
        import torch

        if not obs_list:
            return []
        batch = self.encoder.collate(obs_list, device=self.device)
        with torch.no_grad():
            actions, _, _ = self.policy.act(batch, greedy=self.greedy)
        return [int(a) for a in actions.tolist()]


class RandomAgent:
    """随机合法候选基线。"""

    def __init__(self, seed: int = 0, name: str = "random") -> None:
        self.rng = np.random.default_rng(seed)
        self.name = name

    def act(self, obs_list: Sequence[Observation]) -> List[int]:
        out: List[int] = []
        for obs in obs_list:
            n = len(obs.candidates or ())
            out.append(int(self.rng.integers(0, n)) if n > 0 else 0)
        return out


#: 启发式基线对各动作类型的基础偏好
_HEURISTIC_KIND_SCORE: Dict[str, float] = {
    "buy": 3.0,
    "play_minion": 2.6,
    "play_spell": 2.1,
    "upgrade": 1.6,
    "activate": 1.3,
    "choose": 2.0,
    "hero_power": 1.0,
    "reroll": 0.55,
    "use_dark_gift": 0.5,
    "sell": 0.3,
    "freeze": 0.1,
    "end_turn": 0.05,
}


class HeuristicAgent:
    """候选级启发式基线（只看公开观测，不读引擎状态）。

    规则（弱但稳定的参照系）：
    * 优先购买/打出（按目标实体质量加分）；
    * 血量危险时优先升级/买；棋盘满时卖最弱随从；
    * **每个回合最多决策 ``max_decisions_per_turn`` 次后强制 end_turn**——
      避免在"卖-买"或"刷新"上无限循环（真环境里必须保证 episode 会推进）。
    """

    def __init__(
        self,
        seed: int = 0,
        name: str = "heuristic",
        *,
        max_decisions_per_turn: int = 24,
    ) -> None:
        self.rng = np.random.default_rng(seed)
        self.name = name
        self.max_decisions_per_turn = int(max_decisions_per_turn)
        self._turn: List[int] = []
        self._turn_count: List[int] = []

    def reset(self) -> None:
        """重置内部"每回合决策数"计数（新一轮评测/收集前调用）。"""
        self._turn.clear()
        self._turn_count.clear()

    def act(self, obs_list: Sequence[Observation]) -> List[int]:
        # 槽位 i 的回合决策计数（评测时 agent 按固定顺序对并行环境决策）
        while len(self._turn) < len(obs_list):
            self._turn.append(-1)
            self._turn_count.append(0)
        out: List[int] = []
        for i, obs in enumerate(obs_list):
            turn = int(obs.turn)
            if turn != self._turn[i]:
                self._turn[i] = turn
                self._turn_count[i] = 0
            self._turn_count[i] += 1
            cands = obs.candidates or ()
            n = len(cands)
            if n == 0:
                out.append(0)
                continue
            # 强制推进：决策次数过多时优先 end_turn
            if self._turn_count[i] > self.max_decisions_per_turn:
                end_indices = [j for j, c in enumerate(cands) if self._kind(c) == "end_turn"]
                if end_indices:
                    out.append(int(end_indices[0]))
                    continue
            scores = np.asarray([self._score(obs, c) for c in cands], dtype=np.float64)
            best = float(scores.max())
            idx = np.flatnonzero(scores >= best - 1e-9)
            out.append(int(idx[int(self.rng.integers(0, len(idx)))]))
        return out

    @staticmethod
    def _kind(cand: CandidateAction) -> str:
        return getattr(cand.kind, "value", cand.kind)

    def _score(self, obs: Observation, cand: CandidateAction) -> float:
        kind = self._kind(cand)
        score = _HEURISTIC_KIND_SCORE.get(kind, 0.0)
        board = obs.board or ()
        hand = obs.hand or ()
        tavern = obs.tavern or ()
        # 买：优先高攻/高等级；买得起才有价值
        if kind == "buy" and 0 <= cand.src_slot < len(tavern):
            token = tavern[cand.src_slot]
            score += token.atk / 40.0 + token.health / 40.0 + token.tier / 20.0
        # 卖：优先卖最弱（实体属性低 → 减分少）
        elif kind == "sell" and 0 <= cand.src_slot < len(board):
            token = board[cand.src_slot]
            score -= (token.atk + token.health) / 60.0
            if len(board) <= 3:  # 场面太小不卖
                score -= 1.0
        # 打出手牌：随从优先高身材；磁力/战吼目标在己方棋盘时略加分
        elif kind in ("play_minion", "play_spell") and 0 <= cand.src_slot < len(hand):
            token = hand[cand.src_slot]
            score += token.atk / 40.0 + token.health / 40.0
            if cand.tgt_zone == ZONE_BOARD and 0 <= cand.tgt_slot < len(board):
                score += 0.1
        # 从酒馆指向目标（战吼指向酒馆）未买到的随从价值很低
        if cand.tgt_zone == ZONE_TAVERN and not (0 <= cand.tgt_slot < len(tavern)):
            score -= 0.5
        # 血量危险：更倾向于升级/买大哥
        hero = obs.hero
        if hero is not None and hero.health <= 10 and kind in ("buy", "play_minion", "upgrade"):
            score += 0.3
        return score


def make_agent(
    name: str,
    *,
    policy: Any = None,
    encoder: Optional[ObservationEncoder] = None,
    device: str = "cpu",
    greedy: bool = True,
    seed: int = 0,
) -> Agent:
    """按名字构造评测智能体（``policy`` / ``random`` / ``heuristic``）。"""
    name = (name or "policy").lower()
    if name in ("policy", "model", "trained"):
        if policy is None or encoder is None:
            raise ValueError("policy 基线需要同时提供 policy 与 encoder")
        return PolicyAgent(policy, encoder, device=device, greedy=greedy)
    if name in ("random", "rand"):
        return RandomAgent(seed=seed)
    if name in ("heuristic", "heuristic_env", "teacher"):
        return HeuristicAgent(seed=seed)
    raise ValueError(f"未知基线: {name}（可选 policy/random/heuristic）")


# ══════════════════════════════════════════════════════════════════════
# 评测循环
# ══════════════════════════════════════════════════════════════════════


@dataclass
class EvalResult:
    """一批评测的聚合结果。"""

    games: int = 0
    mean_rank: float = 0.0
    win_rate: float = 0.0
    top_half_rate: float = 0.0
    mean_return: float = 0.0
    mean_steps: float = 0.0
    missing_rank: int = 0
    #: 因单局步数超限被判负的局数（策略陷入循环/不会 end_turn 的信号）
    timeout_games: int = 0
    num_players: int = PLAYER_MAX
    ranks: List[int] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("ranks", None)
        return d

    def format(self) -> str:
        return (
            f"games={self.games} mean_rank={self.mean_rank:.3f} "
            f"win={self.win_rate:.3f} top_half={self.top_half_rate:.3f} "
            f"return={self.mean_return:.3f} steps={self.mean_steps:.1f}"
            + (f" timeouts={self.timeout_games}" if self.timeout_games else "")
        )


def evaluate_agent(
    agent: Agent,
    env: Any,
    *,
    games: int = 8,
    max_steps: Optional[int] = None,
    num_players: int = PLAYER_MAX,
    seed: Optional[int] = None,
    max_steps_per_episode: int = 800,
) -> EvalResult:
    """跑 ``games`` 局（向量环境并行计数），返回聚合名次/胜率。

    **死循环保护**：单局步数超过 ``max_steps_per_episode`` 视为"不会结束
    的一局"，按最差名次记一次负场（``timeout_games`` 计数），并在所有槽位
    都卡住时重置环境。这样即使策略陷入"反复 freeze/刷新"的循环，评测也能
    在有限时间内给出可信的负结果。
    """
    if games <= 0:
        raise ValueError("games 必须 >= 1")
    reset = getattr(agent, "reset", None)
    if callable(reset):
        reset()
    if seed is not None:
        _try_seed(env, seed)
    cap = max(1, int(max_steps_per_episode))
    obs_list = env.reset()
    num_envs = int(getattr(env, "num_envs", len(obs_list)))
    if max_steps is None:
        rounds = int(np.ceil(games / num_envs))
        max_steps = rounds * (cap + 200) + cap
    ep_return = np.zeros(num_envs, dtype=np.float64)
    ep_steps = np.zeros(num_envs, dtype=np.int64)
    stale = [False] * num_envs
    ranks: List[int] = []
    returns: List[float] = []
    lengths: List[int] = []
    missing = 0
    timeouts = 0
    steps = 0
    while len(ranks) < games and steps < max_steps:
        actions = agent.act(obs_list)
        obs_list, rewards, dones, infos = env.step(actions)
        steps += 1
        ep_return += np.asarray(rewards, dtype=np.float64)
        ep_steps += 1
        for i in range(num_envs):
            info = infos[i] if i < len(infos) else {}
            if bool(dones[i]):
                if stale[i]:
                    # 该局已按超时计入，忽略本次真实结算，避免重复计分
                    stale[i] = False
                else:
                    rank = int(info.get("rank", 0) or 0)
                    if rank <= 0:
                        missing += 1
                        rank = num_players  # 没有名次信息时按最差处理（保守）
                    ranks.append(rank)
                    returns.append(float(ep_return[i]))
                    lengths.append(int(ep_steps[i]))
                ep_return[i] = 0.0
                ep_steps[i] = 0
            elif ep_steps[i] >= cap and not stale[i]:
                # 单局超时：记为负场，继续观察，等真实结算到来时忽略
                stale[i] = True
                timeouts += 1
                ranks.append(num_players)
                returns.append(float(ep_return[i]))
                lengths.append(int(ep_steps[i]))
                ep_return[i] = 0.0
                ep_steps[i] = 0
        # 所有槽位都卡住（谁也不会再结束）→ 整环境重置，继续凑够 games
        if all(stale) and len(ranks) < games:
            obs_list = env.reset()
            stale = [False] * num_envs
            ep_return[:] = 0.0
            ep_steps[:] = 0
    if not ranks:
        return EvalResult(
            games=0, num_players=num_players, missing_rank=missing,
            timeout_games=timeouts,
        )
    rank_arr = np.asarray(ranks, dtype=np.float64)
    top_half = (rank_arr <= (num_players + 1) / 2.0).mean()
    return EvalResult(
        games=len(ranks),
        mean_rank=float(rank_arr.mean()),
        win_rate=float((rank_arr <= 1).mean()),
        top_half_rate=float(top_half),
        mean_return=float(np.mean(returns)),
        mean_steps=float(np.mean(lengths)),
        missing_rank=missing,
        timeout_games=timeouts,
        num_players=num_players,
        ranks=ranks,
    )


def evaluate_policy(
    policy: Any,
    encoder: ObservationEncoder,
    env: Any,
    *,
    games: int = 8,
    greedy: bool = True,
    device: str = "cpu",
    max_steps: Optional[int] = None,
    num_players: int = PLAYER_MAX,
    seed: Optional[int] = None,
    max_steps_per_episode: int = 800,
) -> EvalResult:
    """神经网络策略评测（``evaluate_agent`` 的便捷入口）。"""
    agent = PolicyAgent(policy, encoder, device=device, greedy=greedy)
    return evaluate_agent(
        agent, env, games=games, max_steps=max_steps,
        num_players=num_players, seed=seed,
        max_steps_per_episode=max_steps_per_episode,
    )


def _try_seed(env: Any, seed: int) -> None:
    """尽力给环境播种（不同实现签名不同，失败静默）。"""
    setter = getattr(env, "seed", None)
    if callable(setter):
        try:
            setter(seed)
            return
        except Exception:
            pass
    for name in ("_seed", "seed_"):
        if hasattr(env, name):
            try:
                setattr(env, name, seed)
            except Exception:
                pass


__all__ = [
    "Agent",
    "PolicyAgent",
    "RandomAgent",
    "HeuristicAgent",
    "make_agent",
    "EvalResult",
    "evaluate_agent",
    "evaluate_policy",
]
