"""Live 回合内 turn-search（只读 live state；不训练、不写引擎）。

- 输入：`tools.live_state_mem.read_live_state()` 的 dict（board/hand/shop/gold/tier/legal）
- 枚举本回合可达战团（buy→hand、play→board、end_turn；sell/refresh/upgrade 坐标未在
  当前 livebot 配置中，先不执行，fallback heuristic）
- 用引擎 `run_combat` 对可达战团两两裁决（公共 seed），选 argmax；**不模拟后续回合**
- 输出 `LiveAction`（buy/play/end_turn + index），供 UI 层执行。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from hsbg.env.game_env import BattlegroundsEnv
from hsbg.planning import hidden, clone
from hsrl2.tags import GameTag


@dataclass
class MinionSpec:
    card_id: str
    atk: int
    hp: int
    golden: bool = False
    keywords: Tuple[str, ...] = ()

    def key(self) -> tuple:
        return (self.card_id, self.atk, self.hp, self.golden,
                tuple(sorted(self.keywords)))


@dataclass
class LiveAction:
    kind: str                    # buy / play / end_turn
    index: int = -1              # shop/hand index
    note: str = ""
    score: float = 0.0

    def format(self) -> str:
        return f"{self.kind}[{self.index}] score={self.score:.3f} {self.note}".strip()


@dataclass
class LiveSearchResult:
    action: LiveAction
    n_states: int
    n_combats: int
    elapsed_s: float
    candidate_scores: Dict[str, float] = field(default_factory=dict)
    error: str = ""


def _num(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _minion_from_live(item: Dict[str, Any]) -> Optional[MinionSpec]:
    """live state 的 board/hand item → MinionSpec；spell/无 atk 返回 None。"""
    card_id = str(item.get("card") or item.get("card_id") or "").strip()
    # live state 的 board 会包含英雄/英雄技能 token（如 BG21_HERO_030t），
    # 它们不是可战斗随从；过滤掉，避免高估 board 占位/强度。
    cid_upper = card_id.upper()
    if "HERO_" in cid_upper or cid_upper.startswith("TB_BACONSHOP_HERO"):
        return None
    atk = item.get("atk")
    hp = item.get("hp", item.get("health"))
    if atk is None and isinstance(item.get("minion"), dict):
        atk = item["minion"].get("atk")
        hp = hp if hp is not None else item["minion"].get("hp")
    if not card_id or atk is None or hp is None:
        return None
    try:
        a, h = int(atk), int(hp)
    except (TypeError, ValueError):
        return None
    if h <= 0:
        return None
    return MinionSpec(card_id=card_id, atk=a, hp=h,
                      golden=bool(item.get("golden")),
                      keywords=tuple(item.get("keywords") or ()))


def _specs(state: Dict[str, Any]) -> Tuple[List[MinionSpec], List[MinionSpec],
                                            List[MinionSpec]]:
    board = [m for x in (state.get("board") or [])
             if (m := _minion_from_live(x)) is not None]
    hand = [m for x in (state.get("hand") or [])
            if (m := _minion_from_live(x)) is not None]
    shop = [m for x in (state.get("shop") or [])
            if (m := _minion_from_live(x)) is not None]
    return board, hand, shop


def _combat_win(template_game, a: Sequence[MinionSpec], b: Sequence[MinionSpec],
                seed: int) -> Optional[float]:
    # 优先用 env-builder 的 live_warband（精确 CardDB/run_combat，无副作用）；
    # 失败/不可用时回退到本模块合成盘面。
    try:
        from hsbg.planning import live_warband as lw
        wa = lw.build_warband(
            [{"card_id": m.card_id, "atk": m.atk, "health": m.hp,
              "golden": m.golden, "keywords": list(m.keywords)} for m in a],
            "board", seed=int(seed))
        wb = lw.build_warband(
            [{"card_id": m.card_id, "atk": m.atk, "health": m.hp,
              "golden": m.golden, "keywords": list(m.keywords)} for m in b],
            "board", seed=int(seed) + 1)
        if wa.minions and wb.minions:
            res = lw.simulate_combat_warbands(wa, wb, seed=int(seed),
                                              alive_count=8)
            if res.winner_side in ("a", "b", "draw"):
                return {"a": 1.0, "b": 0.0, "draw": 0.5}[res.winner_side]
    except Exception:  # noqa: BLE001
        pass
    try:
        g = clone(template_game)
        ha, hb = g.heroes[0], g.heroes[1]
        sa = [{"card_id": m.card_id, "atk": m.atk, "health": m.hp,
               "golden": m.golden, "keywords": list(m.keywords)} for m in a]
        sb = [{"card_id": m.card_id, "atk": m.atk, "health": m.hp,
               "golden": m.golden, "keywords": list(m.keywords)} for m in b]
        hidden.inject_hidden_state(g, ha, board=sa, clear=True)
        hidden.inject_hidden_state(g, hb, board=sb, clear=True)
        if not ha.board or not hb.board:
            return None
        try:
            g.rng = __import__("hsbg.planning", fromlist=["rng_fork"]).rng_fork(
                g.rng, seed=int(seed))
        except Exception:  # noqa: BLE001
            pass
        res = g.run_combat(ha, hb, alive_count=8)
        if res.winner is ha:
            return 1.0
        if res.winner is hb:
            return 0.0
        return 0.5
    except Exception:  # noqa: BLE001
        return None


def _dedupe(boards: Sequence[Tuple[MinionSpec, ...]]) -> List[Tuple[MinionSpec, ...]]:
    out = []
    seen = set()
    for b in boards:
        k = tuple(m.key() for m in b)
        if k not in seen:
            seen.add(k)
            out.append(tuple(b))
    return out


def _complete_first(board: Tuple[MinionSpec, ...], hand: List[MinionSpec],
                    shop: List[MinionSpec], gold: int,
                    *, max_depth: int = 3,
                    max_states: int = 12) -> List[Tuple[MinionSpec, ...]]:
    """从一个首动作后状态，贪心/穷举补完本回合（buy→hand、play→board）。"""
    out: List[Tuple[MinionSpec, ...]] = [tuple(board)]

    def rec(b: Tuple[MinionSpec, ...], h: List[MinionSpec],
            s: List[MinionSpec], g: int, depth: int) -> None:
        if depth > max_depth or len(out) >= max_states:
            return
        # play hand minions（免费）
        for j, m in enumerate(h):
            if len(b) >= 7:
                break
            nb = tuple(list(b) + [m])
            nh = h[:j] + h[j + 1:]
            out.append(nb)
            rec(nb, nh, s, g, depth + 1)
            if len(out) >= max_states:
                return
        # buy affordable → hand，随后 play
        for j, m in enumerate(s):
            if g < 3 or len(h) >= 9:
                continue
            nh = list(h) + [m]
            ns = s[:j] + s[j + 1:]
            out.append(tuple(b))
            rec(b, nh, ns, g - 3, depth + 1)
            if len(out) >= max_states:
                return

    rec(tuple(board), list(hand), list(shop), int(gold), 0)
    return _dedupe(out)


def search_live_turn(state: Dict[str, Any], *, states_budget: int = 8,
                     seed: int = 0) -> LiveSearchResult:
    """枚举当前回合可达战团并 pairwise 评分，返回首个 UI 动作。"""
    import time
    t0 = time.perf_counter()
    board, hand, shop = _specs(state)
    gold = _num(state.get("gold"), 0)
    turn = _num(state.get("turn"), 0)
    actions: Dict[str, Dict[str, Any]] = {}
    # 首动作 = end_turn（当前战团）
    actions["end_turn"] = {"kind": "end_turn", "index": -1,
                           "boards": [tuple(board)]}
    # 首动作 = play 手牌 j
    for j, m in enumerate(hand):
        nb = tuple(list(board) + [m]) if len(board) < 7 else tuple(board)
        actions[f"play:{j}"] = {"kind": "play", "index": j, "boards": [nb]}
    # 首动作 = buy 商店 i（进手牌）→ 补完
    for i, m in enumerate(shop):
        if gold < 3 or len(hand) >= 9:
            continue
        nh = list(hand) + [m]
        boards = _complete_first(tuple(board), nh, shop[:i] + shop[i + 1:],
                                 gold - 3, max_states=max(2, states_budget))
        actions[f"buy:{i}"] = {"kind": "buy", "index": i, "boards": boards}
    # 限制总状态数
    all_boards = []
    for a in actions.values():
        all_boards.extend(a["boards"])
    all_boards = _dedupe(all_boards)[:max(4, int(states_budget))]
    # 建模板 Game
    env = BattlegroundsEnv(seed=int(seed) + 1, opponent="heuristic")
    env.reset(seed=int(seed) + 1)
    template = env.game
    scores: Dict[str, float] = {}
    combats = 0
    try:
        for key, a in actions.items():
            vals = []
            for b in a["boards"][:max(1, states_budget)]:
                if not b:
                    vals.append(0.5)
                    continue
                wins = []
                for other in all_boards:
                    if not other or other == b:
                        continue
                    w = _combat_win(template, b, other,
                                    seed=int(seed) * 1_003 + turn * 97
                                    + hash(key) % 1000 + len(wins))
                    if w is not None:
                        wins.append(w)
                        combats += 1
                vals.append(float(sum(wins) / len(wins)) if wins else 0.5)
            scores[key] = max(vals) if vals else 0.5
    finally:
        env.close()
    # 排序：有金币时优先买/打，平局不要让 end_turn 抢占（否则会"满金结束回合"）
    best_key = max(scores, key=lambda k: (scores[k], k != "end_turn", k))
    if scores.get(best_key, 0.5) <= 0.5:
        for k, act in actions.items():
            if act["kind"] == "buy" and gold >= 3 and len(hand) < 9:
                best_key = k
                break
            if act["kind"] == "play" and len(board) < 7:
                best_key = k
                break
    a = actions[best_key]
    return LiveSearchResult(
        action=LiveAction(kind=a["kind"], index=int(a["index"]),
                          score=float(scores[best_key]),
                          note=f"turn={turn} gold={gold} n_states={len(all_boards)}"),
        n_states=len(all_boards), n_combats=combats,
        elapsed_s=time.perf_counter() - t0,
        candidate_scores={k: round(float(v), 4) for k, v in scores.items()},
        error="")


__all__ = ["MinionSpec", "LiveAction", "LiveSearchResult", "search_live_turn"]
