"""回合内自枚举 + 两两胜率搜索（train-free）。

正确目标（用户澄清）：
- 只搜索**当前回合**（到 end_turn），绝不模拟后续回合、不做 full-game rollout、不用名次/价值网；
- 枚举本回合可达状态 S（end_turn 前的战团/经济状态）；
- 对 S 做两两战斗（``simulate_turn_combat``/``simulate_combat``，公共 seed），
  score(s)=mean win_rate(s vs other states)；
- 当前每个合法动作 a：执行 a（不推进回合）→ 完成本回合枚举 → 用可达状态的 max/mean 分数
  作为 a 的价值；选 argmax 执行；到新状态再重搜下一步（receding horizon）；
- 直到 end_turn；下一回合重新开始。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from hsbg import planning
from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.env import observation
from hsbg.planning.model import RandomRolloutPolicy
from hsbg.search.forward import ACTION_END_TURN, EngineForwardModel
from hsbg.search.types import MacroAction

__all__ = [
    "TurnSearchConfig", "TurnState", "TurnSearchResult",
    "enumerate_turn_states", "pairwise_winrate_matrix", "TurnSearch",
]


@dataclass
class TurnSearchConfig:
    #: 每决策枚举状态上限（16–32）
    states_budget: int = 24
    #: 每个当前动作的完成回合样本数
    samples_per_action: int = 2
    #: 动作价值聚合："max" / "mean"
    action_aggregate: str = "max"
    #: 完成回合的策略："heuristic"/"random"/"bc"
    completion_policy: str = "heuristic"
    #: 随机种子（枚举/战斗公共随机数）
    seed: int = 0
    #: 两两战斗采样次数
    combat_samples: int = 1
    #: 单状态枚举最大动作步数（防死循环）
    max_steps_per_turn: int = 40
    #: 状态评分方式："pairwise"（全两两战斗）/"value"（仅对照）/
    #: "value_prune_pairwise"（value 剪枝到 top-K，最终 pairwise 选动作）
    state_scorer: str = "pairwise"
    #: value_prune_pairwise 的 finalist 动作数 K
    prune_top_k: int = 4
    #: 是否记录本地枚举 trace（sidecar 数据生成；默认关闭）
    record_trace: bool = False
    #: 是否按真实对手加权（当前默认两两等权）
    opponent_weighted: bool = False

    def __post_init__(self) -> None:
        self.states_budget = max(4, int(self.states_budget))
        self.samples_per_action = max(1, int(self.samples_per_action))
        if self.action_aggregate not in ("max", "mean"):
            raise ValueError("action_aggregate 必须是 max/mean")
        if self.completion_policy not in ("heuristic", "random", "bc"):
            raise ValueError("completion_policy 必须是 heuristic/random/bc")
        if self.state_scorer not in ("pairwise", "value", "value_prune_pairwise"):
            raise ValueError("state_scorer 必须是 pairwise/value/value_prune_pairwise")
        self.prune_top_k = max(2, int(self.prune_top_k))
        self.combat_samples = max(1, int(self.combat_samples))

    def as_dict(self) -> Dict[str, Any]:
        return {"states_budget": self.states_budget,
                "samples_per_action": self.samples_per_action,
                "action_aggregate": self.action_aggregate,
                "completion_policy": self.completion_policy,
                "seed": self.seed, "combat_samples": self.combat_samples,
                "max_steps_per_turn": self.max_steps_per_turn,
                "state_scorer": self.state_scorer,
                "prune_top_k": self.prune_top_k,
                "record_trace": self.record_trace,
                "opponent_weighted": self.opponent_weighted}


@dataclass
class TurnState:
    model: EngineForwardModel
    actions: Tuple[Any, ...]
    source: str = ""


@dataclass
class TurnSearchResult:
    action: Optional[Any]
    action_scores: Dict[str, float]
    n_states: int
    n_combats: int
    elapsed_s: float
    state_scores: List[float] = field(default_factory=list)
    turn: int = 0
    oracle_used: bool = False
    n_value_evals: int = 0
    #: 最终动作是否由 pairwise 分决定（value 只作剪枝）
    final_choice_by_pairwise: bool = True
    finalist_actions: List[str] = field(default_factory=list)
    pairwise_action_scores: Dict[str, float] = field(default_factory=dict)
    value_action_scores: Dict[str, float] = field(default_factory=dict)
    #: 本地枚举 trace（record_trace=True 时）
    trace: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"action": None if self.action is None
                else self.action.signature(),
                "action_scores": {k: round(v, 4)
                                  for k, v in self.action_scores.items()},
                "n_states": self.n_states, "n_combats": self.n_combats,
                "elapsed_s": round(self.elapsed_s, 3),
                "state_scores": [round(x, 4) for x in self.state_scores],
                "turn": self.turn, "oracle_used": self.oracle_used,
                "n_value_evals": self.n_value_evals,
                "final_choice_by_pairwise": self.final_choice_by_pairwise,
                "finalist_actions": self.finalist_actions,
                "pairwise_action_scores": {k: round(v, 4) for k, v
                                           in self.pairwise_action_scores.items()},
                "value_action_scores": {k: round(v, 4) for k, v
                                        in self.value_action_scores.items()}}


# ══════════════════════════════════════════════════════════════════════
# 枚举
# ══════════════════════════════════════════════════════════════════════
def _completion_chooser(policy: str, seed: int, evaluator=None):
    if policy == "bc" and evaluator is not None:
        def chooser(model: EngineForwardModel):
            top = evaluator.top_action(model)
            return None if top is None else top[0]
        return chooser
    if policy == "random":
        rnd = RandomRolloutPolicy(seed=int(seed), end_turn_prob=0.2)

        def chooser(model: EngineForwardModel):
            try:
                d = rnd.choose_action(model.game, model.hero)
                return None if d is None else d.to_candidate()
            except Exception:  # noqa: BLE001
                return None
        return chooser
    hp = HeuristicPolicy()

    def chooser(model: EngineForwardModel):
        try:
            d = hp.choose(model.game, model.hero)
            return None if d is None else d.to_candidate()
        except Exception:  # noqa: BLE001
            return None
    return chooser


def _complete_turn(model: EngineForwardModel, chooser, *,
                   seed: int, max_steps: int,
                   max_states_left: int) -> List[TurnState]:
    """从 model 采样若干“到 end_turn 前”的状态（不推进回合）。"""
    out: List[TurnState] = []
    root_turn = model.turn
    for sample in range(1, 2):
        cur = model.clone()
        actions: List[Any] = []
        for _ in range(max(1, max_steps)):
            if cur.turn != root_turn:
                break
            cands = cur.candidates()
            if not cands:
                break
            cand = chooser(cur)
            if cand is None or cand.signature() not in {
                    c.signature() for c in cands}:
                # 选择 end_turn 收尾
                ends = [c for c in cands if c.kind == ACTION_END_TURN]
                if not ends:
                    break
                cand = ends[0]
            if str(cand.kind) == ACTION_END_TURN:
                actions.append(cand)
                out.append(TurnState(model=cur.clone(),
                                     actions=tuple(actions),
                                     source="completion"))
                break
            if not cur.apply(cand, advance_end_turn=False):
                break
            actions.append(cand)
            if len(out) >= max_states_left:
                break
        if out:
            break
    return out


def enumerate_turn_states(model: EngineForwardModel,
                          config: Optional[TurnSearchConfig] = None,
                          *, evaluator=None) -> Dict[int, List[TurnState]]:
    """返回 {首动作签名: [可达 turn-end 状态]}；不执行 end_turn 推进。"""
    cfg = config or TurnSearchConfig()
    root = model.clone()
    root_turn = root.turn
    cands = root.candidates()
    out: Dict[int, List[TurnState]] = {}
    seen = set()
    total = 0
    for ai, action in enumerate(cands):
        if total >= cfg.states_budget:
            break
        key = action.signature()
        out.setdefault(key, [])
        if str(action.kind) == ACTION_END_TURN:
            st = TurnState(model=root.clone(), actions=(action,), source="end_turn")
            out[key].append(st)
            total += 1
            continue
        for s in range(cfg.samples_per_action):
            if total >= cfg.states_budget:
                break
            cur = root.clone()
            if not cur.apply(action, advance_end_turn=False):
                continue
            chooser = _completion_chooser(
                cfg.completion_policy, cfg.seed + ai * 97 + s * 13, evaluator)
            states = _complete_turn(
                cur, chooser, seed=cfg.seed + ai * 97 + s * 13,
                max_steps=cfg.max_steps_per_turn,
                max_states_left=cfg.states_budget - total)
            for st in states:
                # 强制同回合
                if st.model.turn != root_turn:
                    continue
                sig = (action.signature(), st.actions[-1].signature()
                       if st.actions else ())
                try:
                    from hsbg import planning as _p
                    dg = _p.digest(st.model.game)
                except Exception:  # noqa: BLE001
                    dg = repr(sig)
                if dg in seen:
                    continue
                seen.add(dg)
                out[key].append(st)
                total += 1
                if total >= cfg.states_budget:
                    break
    return out


# ══════════════════════════════════════════════════════════════════════
# 两两战斗胜率
# ══════════════════════════════════════════════════════════════════════
def pairwise_winrate_matrix(states: Sequence[TurnState],
                            template: EngineForwardModel, *,
                            seed: int = 0, samples: int = 1
                            ) -> Tuple[np.ndarray, int]:
    """对状态集合做两两战斗，返回 (winrate[i,j], n_combats)。"""
    n = len(states)
    mat = np.zeros((n, n), dtype=np.float64)
    if n == 0:
        return mat, 0
    template_game = template.clone()
    try:
        from hsrl2.game import _frozen_clone
    except Exception:  # noqa: BLE001
        _frozen_clone = None
    heroes = [h for h in template_game.game.heroes if bool(getattr(h, "is_alive", True))]
    if len(heroes) < 2:
        return mat, 0
    ha, hb = heroes[0], heroes[1]
    idx_a = template_game.game.heroes.index(ha)
    idx_b = template_game.game.heroes.index(hb)
    n_combats = 0
    for i in range(n):
        for j in range(i + 1, n):
            wins = 0.0
            for k in range(max(1, int(samples))):
                g = planning.clone(template_game.game)
                try:
                    a = g.heroes[idx_a]
                    b = g.heroes[idx_b]
                except Exception:  # noqa: BLE001
                    break
                # boards from states
                src_a = states[i].model.game
                src_b = states[j].model.game
                try:
                    ha_src = states[i].model.hero
                    hb_src = states[j].model.hero
                except Exception:  # noqa: BLE001
                    continue
                a.health = max(1, int(getattr(ha_src, "health", 30)))
                b.health = max(1, int(getattr(hb_src, "health", 30)))
                a.board = ([_frozen_clone(m) for m in ha_src.board]
                           if _frozen_clone else list(ha_src.board))
                b.board = ([_frozen_clone(m) for m in hb_src.board]
                           if _frozen_clone else list(hb_src.board))
                try:
                    planning.rng_set_state(
                        g.rng, planning.rng_get_state(template_game.game.rng))
                    g.rng = planning.rng_fork(g.rng, seed=int(seed) + i * 1009
                                              + j * 9176 + k * 31)
                    res = g.run_combat(a, b, alive_count=8)
                except Exception:  # noqa: BLE001
                    continue
                n_combats += 1
                winner = getattr(res, "winner", None)
                loser = getattr(res, "loser", None)
                if winner is a:
                    wins += 1.0
                elif winner is None and loser is None:
                    wins += 0.5
            rate = wins / max(1, samples)
            mat[i, j] = rate
            mat[j, i] = 1.0 - rate
    return mat, n_combats


# ══════════════════════════════════════════════════════════════════════
# 决策
# ══════════════════════════════════════════════════════════════════════
class TurnSearch:
    def __init__(self, config: Optional[TurnSearchConfig] = None,
                 evaluator=None) -> None:
        self.config = config or TurnSearchConfig()
        self.evaluator = evaluator

    def decide(self, model: EngineForwardModel) -> TurnSearchResult:
        cfg = self.config
        t0 = time.perf_counter()
        if model.is_terminal():
            return TurnSearchResult(None, {}, 0, 0,
                                    time.perf_counter() - t0)
        root_turn = model.turn
        by_action = enumerate_turn_states(model, cfg, evaluator=self.evaluator)
        flat: List[TurnState] = []
        idx_map: Dict[Any, List[int]] = {}
        for key, states in by_action.items():
            idx_map[key] = []
            for st in states:
                if st.model.turn != root_turn:
                    continue
                idx_map[key].append(len(flat))
                flat.append(st)
        if not flat:
            return TurnSearchResult(None, {}, 0, 0,
                                    time.perf_counter() - t0, turn=root_turn)
        n = len(flat)
        n_combats = 0
        n_value_evals = 0
        actions = list(model.candidates())
        action_by_key = {a.signature(): a for a in actions}
        finalists: List[str] = []
        pairwise_action_scores: Dict[str, float] = {}
        value_action_scores: Dict[str, float] = {}
        final_choice_by_pairwise = True
        mat = None
        if cfg.state_scorer == "pairwise":
            mat, n_combats = pairwise_winrate_matrix(
                flat, model, seed=int(cfg.seed), samples=cfg.combat_samples)
            scores = np.array([
                float(np.sum(mat[i])) / max(1, n - 1) for i in range(n)
            ])
            for action in actions:
                ids = idx_map.get(action.signature(), [])
                if not ids:
                    continue
                vals = [scores[i] for i in ids]
                pairwise_action_scores[str(action.signature())] = (
                    max(vals) if cfg.action_aggregate == "max"
                    else float(np.mean(vals)))
            finalists = [k for k in pairwise_action_scores]
        else:
            if self.evaluator is None:
                raise ValueError("state_scorer=value/value_prune_pairwise 需要 evaluator")
            vb = self.evaluator.value_batch([st.model for st in flat])
            utility = np.asarray(vb["value"], dtype=np.float64)
            value_norm = (utility + 1.0) / 2.0
            n_value_evals = n
            # 每个动作取 value 最高的状态；value 仅用于排序/剪枝
            best_state: Dict[str, int] = {}
            for action in actions:
                ids = idx_map.get(action.signature(), [])
                if not ids:
                    continue
                best_state[str(action.signature())] = max(
                    ids, key=lambda i: value_norm[i])
                value_action_scores[str(action.signature())] = float(
                    value_norm[best_state[str(action.signature())]])
            if cfg.state_scorer == "value":
                # 仅对照：value 直接决定（不用于结论）
                final_choice_by_pairwise = False
                finalists = list(value_action_scores)
                scores = value_norm
            else:
                # value 剪枝到 top-K 动作，最终只用 pairwise 分选动作
                k = min(max(2, int(cfg.prune_top_k)), len(best_state))
                top_keys = sorted(value_action_scores,
                                  key=lambda x: -value_action_scores[x])[:k]
                finalists = top_keys
                finalist_states = [flat[best_state[key]] for key in top_keys]
                sub_mat, n_combats = pairwise_winrate_matrix(
                    finalist_states, model, seed=int(cfg.seed),
                    samples=cfg.combat_samples)
                sub_scores = np.array([
                    float(np.sum(sub_mat[j])) / max(1, len(top_keys) - 1)
                    for j in range(len(top_keys))
                ])
                for j, key in enumerate(top_keys):
                    pairwise_action_scores[key] = float(sub_scores[j])
                scores = np.zeros(n, dtype=np.float64)
                for j, key in enumerate(top_keys):
                    scores[best_state[key]] = float(sub_scores[j])
        action_scores: Dict[str, float] = {}
        best_action = None
        best_val = -1e18
        # pairwise 模式/剪枝模式最终 argmax 均来自 pairwise_action_scores
        score_map = (pairwise_action_scores if final_choice_by_pairwise
                     else value_action_scores)
        for action in actions:
            key = str(action.signature())
            if key not in score_map:
                continue
            val = float(score_map[key])
            action_scores[key] = val
            if val > best_val:
                best_val = val
                best_action = action
        trace = None
        if cfg.record_trace:
            st_rows = []
            for i, st in enumerate(flat):
                try:
                    obs = observation.build_observation(
                        st.model.game, st.model.hero, st.model.candidates(),
                        phase="recruit", turn=st.model.turn,
                        total_players=st.model.total_players, extra=None)
                except Exception:  # noqa: BLE001
                    obs = None
                board = [{"card_id": str(m.card_id), "atk": int(m.atk),
                          "health": int(m.health),
                          "golden": bool(getattr(m, "golden", False)),
                          "keywords": list(getattr(m, "keywords", ()) or ())}
                         for m in st.model.hero.board]
                st_rows.append({
                    "score": float(scores[i]),
                    "turn": int(st.model.turn),
                    "tier": int(getattr(st.model.hero, "tier", 0)),
                    "hero_health": int(getattr(st.model.hero, "health", 0)),
                    "alive_count": int(getattr(st.model, "alive_count", 8)),
                    "board": board,
                    "actions": [a.signature() for a in st.actions],
                    "obs": obs,
                })
            trace = {"turn": root_turn, "n_states": n,
                     "matrix": None if mat is None else mat.tolist(),
                     "states": st_rows,
                     "action_scores": dict(action_scores)}
        return TurnSearchResult(
            action=best_action, action_scores=action_scores,
            n_states=n, n_combats=n_combats,
            elapsed_s=time.perf_counter() - t0,
            state_scores=[float(x) for x in scores], turn=root_turn,
            n_value_evals=n_value_evals,
            final_choice_by_pairwise=final_choice_by_pairwise,
            finalist_actions=finalists,
            pairwise_action_scores=pairwise_action_scores,
            value_action_scores=value_action_scores,
            trace=trace)
