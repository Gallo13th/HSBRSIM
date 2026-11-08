"""玩具 8 人 POMDP 环境：让 `hsbg/az` 的搜索/测试在**没有 Rust 引擎的机器上**也能跑。

用途：
- `tests/test_az_search.py` 的本地单元测试（信息隔离、确定性、合法动作、回退）；
- 演示"公开信息 vs 隐藏信息"的分离：对手的当前战团/金币/手牌/商店是隐藏量，
  观测里只有公开的血量/等级 + **上一次见到的战团强度**；
- `determinize_world(seat, rng)` 只从公开信息采样隐藏世界（bootstrap 版 belief sampler）。

不是规则精确的 BG 模拟器：只保留搜索需要的结构
（信息集、chance、终局名次、合法动作、确定性 seed）。
"""

from __future__ import annotations

import pickle
import random
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

N_ACTIONS = 8
N_PLAYERS = 8
END_TURN = 0
BUY0 = 1
UPGRADE = 4
ROLL = 5
SELL = 6
FREEZE = 7
MAX_TURNS = 20
FLOATS = 32
CARDS = 8

BUY_COST = 3
UPGRADE_COST = 5
ROLL_COST = 1


def _utility(placement: int, n: int = N_PLAYERS) -> float:
    if placement <= 0 or n < 2:
        return 0.0
    return float(1.0 - 2.0 * (float(placement) - 1.0) / float(n - 1))


class ToyGame:
    """8 人简化酒馆战棋（公开/隐藏信息分离）。"""

    N_ACTIONS = N_ACTIONS
    N_PLAYERS = N_PLAYERS

    def __init__(self, seed: int = 0, max_turns: int = MAX_TURNS):
        self.seed = int(seed)
        self.rng = random.Random(int(seed))
        self.max_turns = int(max_turns)
        self.turn = 0
        self.over = False
        self.next_place = N_PLAYERS
        self.ending = False
        self.players: List[Dict[str, Any]] = []
        for p in range(N_PLAYERS):
            self.players.append({
                "health": 30,
                "armor": 0,
                "tier": 1,
                "placement": 0,
                "alive": True,
                "ended": False,
                # ---- 隐藏量（对手不可见；决策只允许通过 observe）----
                "gold": 3,
                "strength": 0,
                "board_count": 0,
                "hand": [],
                "shop": self._sample_shop(1),
                # ---- 公开快照：上一次战斗见到的战团强度 ----
                "seen_strength": 0,
                "seen_turn": 0,
            })

    # ── 内部 ────────────────────────────────────────────────────────────
    def _sample_shop(self, tier: int) -> List[int]:
        return [max(1, int(self.rng.uniform(1 + tier, 2 + 2.2 * tier))) for _ in range(3)]

    def _refresh_shop(self, p: int) -> None:
        pl = self.players[p]
        pl["shop"] = self._sample_shop(int(pl["tier"]))

    def _alive(self) -> List[int]:
        return [i for i, pl in enumerate(self.players) if pl["alive"]]

    def _place(self, p: int) -> None:
        pl = self.players[p]
        if pl["placement"] == 0:
            pl["placement"] = self.next_place
            self.next_place = max(1, self.next_place - 1)

    def _resolve_round(self) -> None:
        """所有存活座位都结束回合后：结算一轮（chance：商店刷新 + 战斗伤害）。"""
        self.turn += 1
        alive = self._alive()
        for p in alive:
            pl = self.players[p]
            pl["ended"] = False
            pl["gold"] = min(10, 2 + self.turn // 2 + (1 if self.turn % 3 == 0 else 0))
            self._refresh_shop(p)
        strengths = {p: float(self.players[p]["strength"]) for p in alive}
        if strengths:
            median = float(np.median(list(strengths.values())))
            for p in alive:
                dmg = 1 + int(max(0.0, median - strengths[p]) // 2.0)
                self.players[p]["health"] -= dmg
        for p in list(alive):
            if self.players[p]["health"] <= 0:
                self.players[p]["alive"] = False
                self.players[p]["strength"] = 0
                self.players[p]["board_count"] = 0
                self._place(p)
        alive = self._alive()
        # 公开信息：每人"见到"下一个存活对手的战团强度（公开快照）
        for p in alive:
            q = None
            for step in range(1, N_PLAYERS):
                cand = (p + step) % N_PLAYERS
                if self.players[cand]["alive"]:
                    q = cand
                    break
            if q is not None:
                self.players[p]["seen_strength"] = int(self.players[q]["strength"])
                self.players[p]["seen_turn"] = self.turn
        if len(alive) <= 1:
            for p in alive:
                self._place(p)
            self.over = True
        elif self.turn >= self.max_turns:
            order = sorted(alive, key=lambda i: (self.players[i]["health"],
                                                 self.players[i]["strength"]),
                           reverse=True)
            for p in order:
                self._place(p)
            self.over = True

    # ── env 协议 ────────────────────────────────────────────────────────
    def num_players(self) -> int:
        return N_PLAYERS

    def copy(self) -> "ToyGame":
        g = object.__new__(ToyGame)
        g.seed = self.seed
        g.rng = random.Random()
        g.rng.setstate(self.rng.getstate())
        g.max_turns = self.max_turns
        g.turn = self.turn
        g.over = self.over
        g.next_place = self.next_place
        g.ending = self.ending
        g.players = [dict(pl) for pl in self.players]
        for pl in g.players:
            pl["hand"] = list(pl["hand"])
            pl["shop"] = list(pl["shop"])
        return g

    def snapshot(self) -> bytes:
        return pickle.dumps(self)

    def is_over(self) -> bool:
        return bool(self.over)

    def needs_action(self, p: int) -> bool:
        pl = self.players[int(p)]
        return bool(pl["alive"] and not pl["ended"] and not self.over)

    def placements(self) -> List[int]:
        return [int(pl["placement"]) for pl in self.players]

    def legal_mask(self, p: int) -> np.ndarray:
        m = np.zeros(N_ACTIONS, dtype=np.uint8)
        if not self.needs_action(p):
            return m.astype(bool)
        pl = self.players[int(p)]
        m[END_TURN] = 1
        for i, s in enumerate(pl["shop"]):
            if s >= 0 and pl["gold"] >= BUY_COST:
                m[BUY0 + i] = 1
        if pl["gold"] >= UPGRADE_COST and pl["tier"] < 6:
            m[UPGRADE] = 1
        if pl["gold"] >= ROLL_COST:
            m[ROLL] = 1
        if pl["strength"] > 0:
            m[SELL] = 1
        m[FREEZE] = 1
        return m.astype(bool)

    def observe(self, p: int) -> Tuple[np.ndarray, np.ndarray]:
        """只返回公开 + 己方可见信息（不含对手隐藏量）。"""
        p = int(p)
        me = self.players[p]
        f = np.zeros(FLOATS, dtype=np.float32)
        f[0] = self.turn / 20.0
        f[1] = me["health"] / 40.0
        f[2] = me["armor"] / 20.0
        f[3] = me["tier"] / 6.0
        f[4] = me["gold"] / 10.0          # 己方金币：自己可见
        f[5] = me["strength"] / 40.0      # 己方战团：自己可见
        f[6] = min(me["board_count"], 7) / 7.0
        f[7] = len(me["hand"]) / 10.0
        f[8] = len(self._alive()) / 8.0
        f[9] = me["placement"] / 8.0
        slot = 10
        for k in range(N_PLAYERS - 1):
            q = (p + 1 + k) % N_PLAYERS
            opp = self.players[q]
            f[slot + 0] = opp["health"] / 40.0
            f[slot + 1] = opp["tier"] / 6.0
            f[slot + 2] = (opp["seen_strength"] if opp["alive"] else 0) / 40.0
            slot += 3
        cards = np.zeros(CARDS, dtype=np.int32)
        for i, c in enumerate(me["hand"][:CARDS]):
            cards[i] = int(c)
        return f, cards

    def step(self, p: int, action: int) -> None:
        p = int(p)
        a = int(action)
        if not self.needs_action(p):
            raise ValueError(f"seat {p} 当前不需要行动")
        mask = self.legal_mask(p)
        if not bool(mask[a]):
            raise ValueError(f"非法动作 {a} for seat {p} (turn {self.turn})")
        pl = self.players[p]
        if a == END_TURN:
            pl["ended"] = True
            if all(not self.players[q]["alive"] or self.players[q]["ended"]
                   for q in range(N_PLAYERS)):
                self._resolve_round()
            return
        if BUY0 <= a < BUY0 + 3:
            slot = a - BUY0
            pl["gold"] -= BUY_COST
            pl["strength"] += int(pl["shop"][slot])
            pl["board_count"] = min(7, pl["board_count"] + 1)
            pl["shop"][slot] = -1
            return
        if a == UPGRADE:
            pl["gold"] -= UPGRADE_COST
            pl["tier"] = min(6, int(pl["tier"]) + 1)
            self._refresh_shop(p)
            return
        if a == ROLL:
            pl["gold"] -= ROLL_COST
            self._refresh_shop(p)
            return
        if a == SELL:
            pl["strength"] = max(0, int(pl["strength"]) - max(1, int(pl["strength"]) // 4))
            pl["gold"] = min(10, int(pl["gold"]) + 1)
            pl["board_count"] = max(0, int(pl["board_count"]) - 1)
            return
        if a == FREEZE:
            return
        raise ValueError(f"未知动作 {a}")

    def terminal_value(self, p: int) -> Optional[float]:
        place = int(self.players[int(p)]["placement"])
        if place > 0:
            return _utility(place)
        if self.over:
            return 0.0
        return None

    # ── bot ─────────────────────────────────────────────────────────────
    def bot_action(self, p: int) -> int:
        """贪心脚本：优先买最强可负担随从 → 升级 → 刷新/结束。"""
        p = int(p)
        if not self.needs_action(p):
            return END_TURN
        pl = self.players[p]
        mask = self.legal_mask(p)
        best, best_s = END_TURN, -1
        for i, s in enumerate(pl["shop"]):
            a = BUY0 + i
            if mask[a] and s > best_s:
                best, best_s = a, int(s)
        if best_s > 0 and (best_s >= 1 + pl["tier"] or pl["gold"] >= 6):
            return best
        if mask[UPGRADE] and pl["gold"] >= UPGRADE_COST + 2:
            return UPGRADE
        if mask[ROLL] and pl["gold"] >= 2:
            return ROLL
        return END_TURN

    def bot_play(self, p: int) -> None:
        guard = 0
        while self.needs_action(p) and not self.over:
            guard += 1
            if guard > 64:
                break
            self.step(p, self.bot_action(p))

    # ── determinization（公开信息先验；仅采样隐藏量）─────────────────────
    def determinize_world(self, seat: int, rng: random.Random):
        """从公开信息采样隐藏世界：只改对手隐藏量，公开观测必须不变。"""
        obs_before = self.observe(seat)
        world = self.copy()
        n_inj = 0
        for q in range(N_PLAYERS):
            if q == int(seat) or not world.players[q]["alive"]:
                continue
            pl = world.players[q]
            tier = int(pl["tier"])
            seen = int(pl["seen_strength"])
            base = float(seen) if seen > 0 else float(2 + 2 * tier + len(world._alive()))
            pl["strength"] = max(0, int(base * rng.uniform(0.6, 1.4) + rng.randint(-2, 2)))
            pl["board_count"] = int(np.clip(round(pl["strength"] / 4.0), 0, 7))
            pl["gold"] = int(rng.randint(0, 10))
            pl["hand"] = [rng.randint(1, 12) for _ in range(rng.randint(0, 3))]
            pl["shop"] = [max(1, int(rng.uniform(1 + tier, 2 + 2.2 * tier)))
                          for _ in range(3)]
            n_inj += 1
        obs_after = world.observe(seat)
        same = (np.array_equal(obs_before[0], obs_after[0])
                and np.array_equal(obs_before[1], obs_after[1]))
        from .belief import DeterminizeInfo  # 延迟导入避免模块环

        info = DeterminizeInfo(
            mode="toy_public_prior_v0", injected_hidden=True, oracle=False,
            n_opponents=n_inj, n_injections=n_inj, obs_invariant=bool(same),
            note="toy：对手战团/金币/手牌/商店由公开 tier+seen 强度先验采样",
        )
        return world, info


__all__ = ["ToyGame", "N_ACTIONS", "N_PLAYERS", "END_TURN"]
