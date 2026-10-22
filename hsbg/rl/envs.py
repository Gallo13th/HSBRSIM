"""环境工厂 + 确定性 Mock 环境（``backend='mock'``）。

真实环境是 ``hsbg.env.game_env.BattlegroundsEnv``（运行完整的 ``hsrl2`` 引擎）。
为了让采集/评测/接口测试在没有引擎（或需要极快确定性回归）时也能跑，
这里提供一个**纯 Python、完全由 seed 决定**的合成环境
:class:`MockBattlegroundsEnv`：

* 观测结构 / 候选动作 / 奖励口径与 ``hsbg.env.spec`` 一致；
* 每局长度、候选数量、是否进入 ``choice`` 阶段都由 ``seed`` 决定；
* 终局在 ``info["rank"]`` 给出 1..num_players 的名次，便于统计名次分布。

``backend='auto'`` 时优先真实环境，不可用则回退 Mock（会打印一次提示）。
"""

from __future__ import annotations

import random
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from hsbg.env.spec import (
    ActionKind,
    CandidateAction,
    EntityToken,
    HeroToken,
    LobbyPlayer,
    Observation,
    PendingChoice,
    ZONE_BOARD,
    ZONE_CHOICE,
    ZONE_HAND,
    ZONE_NONE,
    ZONE_OPPONENT,
    ZONE_TAVERN,
)
from hsbg.rl.api import resolve_action

#: 环境后端名
BACKENDS: Tuple[str, ...] = ("auto", "real", "mock")


# ══════════════════════════════════════════════════════════════════════
# Mock 环境
# ══════════════════════════════════════════════════════════════════════

#: 合成实体使用的卡牌池（真实 id 便于编码器词表命中；也用少量未知 id 覆盖 <UNK>）
_MOCK_CARD_POOL: Tuple[Tuple[str, str], ...] = (
    ("BG19_010", "minion"),
    ("BG20_100", "minion"),
    ("BG28_168", "spell"),
    ("BG28_518", "spell"),
    ("BG20_HERO_100", "hero"),
    ("BG30_MagicItem_301", "trinket"),
    ("BG24_Reward_107", "reward"),
    ("BG27_Anomaly_000", "anomaly"),
    ("MOCK_UNKNOWN_CARD", "minion"),
)
_RACES_POOL: Tuple[str, ...] = ("beast", "demon", "dragon", "elemental", "mech", "murloc")
_KEYWORDS_POOL: Tuple[str, ...] = ("taunt", "divine_shield", "deathrattle", "battlecry")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class MockBattlegroundsEnv:
    """确定性合成环境（接口与 :class:`hsbg.env.BattlegroundsEnv` 对齐）。

    只实现 RL 接口层需要的部分：``reset/step/close/num_players/
    current_observation/legal_actions/action_mask``。观测/候选/奖励结构
    与真实环境一致，但数值是模拟的，**不能**用于评估策略真实棋力。
    """

    #: 供 gym 包装识别的元数据（与真实环境一致）
    metadata = {"render_modes": [], "num_players": 8}

    def __init__(
        self,
        num_players: int = 8,
        seed: int = 0,
        *,
        max_turns: int = 12,
        max_steps: int = 400,
        episode_steps: Tuple[int, int] = (80, 180),
        choice_prob: float = 0.18,
        heal_prob: float = 0.0,
        max_actions_per_turn: int = 40,
        name: str = "mock",
    ) -> None:
        self.num_players = int(num_players)
        self._seed = int(seed)
        self._env_seed = int(seed)
        self.max_turns = int(max_turns)
        self.max_steps = int(max_steps)
        self.episode_steps = (int(episode_steps[0]), int(episode_steps[1]))
        self.choice_prob = float(choice_prob)
        self.heal_prob = float(heal_prob)
        self.max_actions_per_turn = int(max_actions_per_turn)
        self.name = name
        self._rng = random.Random(self._env_seed)
        self._obs: Optional[Observation] = None
        self._entity_seq = 0
        self._reset_state()

    # ── 生命周期 ──
    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Observation:
        if seed is not None:
            self._env_seed = int(seed)
        elif options and "seed" in options:
            self._env_seed = int(options["seed"])
        self._rng = random.Random(self._env_seed)
        rng = self._rng
        self._reset_state()
        self._episode_len = rng.randint(*self.episode_steps)
        self._init_lobby()
        self._refresh_tavern()
        self._obs = self._build_obs()
        return self._obs

    def close(self) -> None:
        self._obs = None

    # ── 状态初始化 ──
    def _reset_state(self) -> None:
        self._turn = 1
        self._gold = 3
        self._tier = 1
        self._health = 30
        self._armor = 0
        self._board: List[EntityToken] = []
        self._hand: List[EntityToken] = []
        self._tavern: List[EntityToken] = []
        self._trinkets: List[EntityToken] = []
        self._quest: Optional[EntityToken] = None
        self._opponent_board: List[EntityToken] = []
        self._episode_step = 0
        self._actions_this_turn = 0
        self._alive_count = self.num_players
        self._rank = self.num_players
        self._pending: Optional[PendingChoice] = None
        self._terminated = False
        self._truncated = False
        self._episode_len = 30
        self._invalid_actions = 0
        self._player_healths: List[LobbyPlayer] = []

    # ── 观测构造 ──
    def _new_entity(self, zone: str, slot: int, card_type: Optional[str] = None) -> EntityToken:
        rng = self._rng
        self._entity_seq += 1
        card_id, default_type = _MOCK_CARD_POOL[rng.randrange(len(_MOCK_CARD_POOL))]
        races: Tuple[str, ...] = ()
        keywords: Tuple[str, ...] = ()
        tier = int(rng.randint(1, max(1, self._tier)))
        if (card_type or default_type) == "minion":
            races = tuple(
                _RACES_POOL[rng.randrange(len(_RACES_POOL))]
                for _ in range(int(rng.randint(0, 2)))
            )
            keywords = tuple(
                _KEYWORDS_POOL[rng.randrange(len(_KEYWORDS_POOL))]
                for _ in range(int(rng.randint(0, 2)))
            )
        return EntityToken(
            card_id=card_id,
            card_type=card_type or default_type,
            zone=zone,
            slot=int(slot),
            atk=int(rng.randint(0, 12)),
            health=int(rng.randint(1, 12)),
            tier=tier,
            cost=int(rng.randint(1, 3)),
            races=races,
            keywords=keywords,
            golden=bool(rng.random() < 0.08),
            entity_id=self._entity_seq,
            name=f"mock-{zone}-{slot}",
        )

    def _refresh_tavern(self) -> None:
        self._tavern = [
            self._new_entity(ZONE_TAVERN, i) for i in range(int(self._rng.randint(3, 7)))
        ]

    def _init_lobby(self) -> None:
        """生成整局固定的大厅快照（对手血量/等级只在 reset 时随机一次）。"""
        rng = self._rng
        players: List[LobbyPlayer] = [
            LobbyPlayer(
                name="P0", health=self._health, armor=self._armor,
                tier=self._tier, alive=True, is_agent=True,
            )
        ]
        for i in range(1, self.num_players):
            health = int(rng.randint(0, 30))
            players.append(LobbyPlayer(
                name=f"P{i}",
                health=health,
                armor=0,
                tier=int(rng.randint(1, 6)),
                alive=health > 0,
                is_agent=False,
            ))
        self._player_healths = players
        self._refresh_lobby()

    def _refresh_lobby(self) -> None:
        """同步智能体血量到大厅快照，并更新存活数与名次估计。"""
        players = list(self._player_healths)
        if not players:
            self._alive_count = 1
            self._rank = 1
            return
        players[0] = LobbyPlayer(
            name="P0",
            health=max(self._health, 0),
            armor=self._armor,
            tier=self._tier,
            alive=self._health > 0,
            is_agent=True,
        )
        self._player_healths = players
        alive = sum(1 for p in players if p.alive)
        self._alive_count = max(alive, 1)
        agent_alive = players[0].alive
        if agent_alive:
            # 名次估计：比智能体血量高的存活对手数量 + 1
            better = sum(
                1 for p in players[1:]
                if p.alive and p.health > self._health
            )
            self._rank = int(_clamp(1 + better, 1, self.num_players))
        else:
            self._rank = int(_clamp(self._alive_count + 1, 2, self.num_players))

    def _build_obs(self, phase: Optional[str] = None) -> Observation:
        phase = phase or ("choice" if self._pending is not None else "recruit")
        candidates = self._build_candidates(phase)
        hero = HeroToken(
            hero_id="BG20_HERO_100",
            health=self._health,
            armor=self._armor,
            tier=self._tier,
            gold=self._gold,
            upgrade_cost=max(1, 5 - self._tier),
            power_id="BG20_HERO_100p",
            power_cost=0,
            power_usable=True,
        )
        return Observation(
            version=1,
            turn=self._turn,
            phase=phase,
            hero=hero,
            board=tuple(self._board),
            hand=tuple(self._hand),
            tavern=tuple(self._tavern),
            trinkets=tuple(self._trinkets),
            quest=self._quest,
            opponent_board=tuple(self._opponent_board),
            lobby=tuple(self._player_healths),
            alive_count=self._alive_count,
            total_players=self.num_players,
            rank=self._rank,
            pending_choice=self._pending if phase == "choice" else None,
            candidates=tuple(candidates),
            log=f"mock turn={self._turn} phase={phase}",
        )

    def _build_candidates(self, phase: str) -> List[CandidateAction]:
        rng = self._rng
        out: List[CandidateAction] = []
        if phase == "choice" and self._pending is not None:
            for i in range(len(self._pending.options)):
                out.append(CandidateAction(
                    kind=ActionKind.CHOOSE.value, option=i, src_zone=ZONE_CHOICE,
                    src_slot=i,
                ))
            return out
        # 回合动作预算（与真实环境一致：用尽后只允许 end_turn，防 no-op 死循环）
        if self._actions_this_turn >= self.max_actions_per_turn:
            return [CandidateAction(kind=ActionKind.END_TURN.value, cost=-1)]
        # 购买（只列买得起的）
        for i, token in enumerate(self._tavern):
            if int(token.cost) <= self._gold:
                out.append(CandidateAction(
                    kind=ActionKind.BUY.value, src_zone=ZONE_TAVERN,
                    src_slot=i, cost=int(token.cost),
                ))
        # 打出手牌
        for i, token in enumerate(self._hand):
            if str(getattr(token, "card_type", "minion")) == "spell":
                out.append(CandidateAction(
                    kind=ActionKind.PLAY_SPELL.value, src_zone=ZONE_HAND,
                    src_slot=i, cost=0,
                ))
            else:
                tgt_zone, tgt_slot = ZONE_NONE, -1
                if self._board and rng.random() < 0.3:
                    tgt_zone, tgt_slot = ZONE_BOARD, int(rng.randrange(len(self._board)))
                out.append(CandidateAction(
                    kind=ActionKind.PLAY_MINION.value, src_zone=ZONE_HAND,
                    src_slot=i, tgt_zone=tgt_zone, tgt_slot=tgt_slot,
                    position=int(rng.randint(-1, len(self._board))), cost=0,
                ))
        # 出售
        for i, _token in enumerate(self._board):
            out.append(CandidateAction(
                kind=ActionKind.SELL.value, src_zone=ZONE_BOARD, src_slot=i,
            ))
        # 无目标/目标可选动作
        if self._gold >= 1:
            out.append(CandidateAction(kind=ActionKind.REROLL.value, cost=1))
        upgrade_cost = max(1, 5 - self._tier)
        if self._tier < 6 and self._gold >= upgrade_cost:
            out.append(CandidateAction(kind=ActionKind.UPGRADE.value, cost=upgrade_cost))
        out.append(CandidateAction(kind=ActionKind.FREEZE.value, cost=0))
        out.append(CandidateAction(kind=ActionKind.HERO_POWER.value, cost=0))
        if self._board and rng.random() < 0.2:
            out.append(CandidateAction(
                kind=ActionKind.ACTIVATE.value, src_zone=ZONE_BOARD,
                src_slot=int(rng.randrange(len(self._board))), cost=0,
            ))
        if rng.random() < 0.1:
            out.append(CandidateAction(kind=ActionKind.USE_DARK_GIFT.value, cost=0))
        out.append(CandidateAction(kind=ActionKind.END_TURN.value, cost=-1))
        return out

    # ── step ──
    def step(self, action: Any) -> Tuple[Observation, float, bool, bool, Dict[str, Any]]:
        if self._obs is None:
            raise RuntimeError("MockBattlegroundsEnv.step() called before reset()")
        obs = self._obs
        idx, cand, invalid = resolve_action(action, obs)
        if invalid:
            self._invalid_actions += 1
        reward = 0.0
        terminated = False
        truncated = False
        reason = ""
        self._episode_step += 1
        kind = str(getattr(cand.kind, "value", cand.kind)) if cand is not None else ""
        if kind not in ("", ActionKind.END_TURN.value, ActionKind.CHOOSE.value):
            self._actions_this_turn += 1

        if cand is None:
            terminated = True
            reason = "no_candidates"
        elif kind == ActionKind.END_TURN.value:
            self._turn += 1
            self._actions_this_turn = 0
            damage = int(self._rng.randint(0, 8))
            self._health -= damage
            reward += 0.02 * float(-damage)
            self._refresh_lobby()
            if self._health <= 0:
                terminated = True
                reason = "eliminated"
                self._health = 0
                # 名次 = 淘汰后剩余存活人数 + 1（8 人局最后一名 = 8）
                self._rank = int(_clamp(self._alive_count + 1, 2, self.num_players))
                self._refresh_lobby()
                reward += 1.0 - 2.0 * (self._rank - 1) / max(self.num_players - 1, 1)
            else:
                self._gold = min(3 + self._turn, 12)
                self._refresh_tavern()
                self._opponent_board = [
                    self._new_entity(ZONE_OPPONENT, i)
                    for i in range(int(self._rng.randint(0, 5)))
                ]
        elif kind == ActionKind.BUY.value and 0 <= idx:
            src = int(getattr(cand, "src_slot", -1) or -1)
            if 0 <= src < len(self._tavern):
                token = self._tavern.pop(src)
                cost = int(getattr(token, "cost", 0) or 0)
                if cost <= self._gold:
                    self._gold -= cost
                    self._hand.append(token)
                    reward += 0.001
        elif kind in (ActionKind.PLAY_MINION.value, ActionKind.PLAY_SPELL.value):
            src = int(getattr(cand, "src_slot", -1) or -1)
            if 0 <= src < len(self._hand):
                token = self._hand.pop(src)
                self._board.append(token)
                reward += 0.001
        elif kind == ActionKind.SELL.value:
            src = int(getattr(cand, "src_slot", -1) or -1)
            if 0 <= src < len(self._board):
                self._board.pop(src)
                self._gold += 1
        elif kind == ActionKind.REROLL.value:
            if self._gold >= 1:
                self._gold -= 1
                self._refresh_tavern()
        elif kind == ActionKind.UPGRADE.value:
            cost = max(1, 5 - self._tier)
            if self._gold >= cost and self._tier < 6:
                self._gold -= cost
                self._tier += 1
                reward += 0.01
        elif kind == ActionKind.ACTIVATE.value or kind == ActionKind.HERO_POWER.value:
            reward += 0.0
        elif kind == ActionKind.FREEZE.value:
            reward += 0.0
        elif kind == ActionKind.USE_DARK_GIFT.value:
            reward += 0.0
        elif kind == ActionKind.CHOOSE.value:
            self._pending = None
        else:
            # 未知动作：不推进
            reward += 0.0

        # 回合上限 / 步数上限
        if not terminated and self._turn > self.max_turns:
            truncated = True
            reason = "max_turns"
        if self._episode_step >= min(self.max_steps, self._episode_len):
            truncated = True
            reason = reason or "max_steps"

        # 偶尔进入 choice 阶段（引擎 PendingChoice 的模拟）
        if not terminated and not truncated:
            if self._pending is None and self._rng.random() < self.choice_prob:
                n_options = int(self._rng.randint(2, 5))
                options = tuple(
                    self._new_entity(ZONE_CHOICE, i) for i in range(n_options)
                )
                self._pending = PendingChoice(
                    kind="discover", options=options, for_agent=True,
                    prompt="mock choice",
                )
            elif self._pending is not None:
                pass
        phase = "choice" if self._pending is not None else "recruit"
        if terminated:
            phase = "game_over"
        self._obs = self._build_obs(phase=phase)
        info: Dict[str, Any] = {
            "turn": self._turn,
            "phase": phase,
            "rank": self._rank,
            "health": self._health,
            "alive_count": self._alive_count,
            "invalid": bool(invalid),
            "terminated_reason": reason,
            "episode_steps": self._episode_step,
            "seed": self._env_seed,
            "action_index": int(idx),
            "wrong_action": bool(invalid),
        }
        self._terminated = bool(terminated)
        self._truncated = bool(truncated)
        return self._obs, float(reward), bool(terminated), bool(truncated), info

    # ── 便捷属性（与真实环境对齐）──
    @property
    def current_observation(self) -> Optional[Observation]:
        return self._obs

    @property
    def seed(self) -> int:
        return self._env_seed

    def legal_actions(self) -> Tuple[CandidateAction, ...]:
        if self._obs is None:
            return ()
        return tuple(self._obs.candidates)

    def action_mask(self) -> Tuple[bool, ...]:
        return tuple(True for _ in self.legal_actions())

    def num_actions(self) -> int:
        return len(self.legal_actions())

    def __repr__(self) -> str:  # pragma: no cover - 调试
        return (f"MockBattlegroundsEnv(seed={self._env_seed}, turn={self._turn}, "
                f"step={self._episode_step}, phase={getattr(self._obs, 'phase', None)})")


# ══════════════════════════════════════════════════════════════════════
# 环境工厂
# ══════════════════════════════════════════════════════════════════════

_WARNED_FALLBACK = False


@lru_cache(maxsize=1)
def real_env_available() -> bool:
    """真实环境是否可导入（不创建实例，代价低且缓存）。"""
    try:
        from hsbg.env.game_env import BattlegroundsEnv  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def make_env(
    *,
    backend: str = "auto",
    seed: Optional[int] = None,
    num_players: int = 8,
    opponent: str = "heuristic",
    agent_index: int = 0,
    env_kwargs: Optional[Dict[str, Any]] = None,
    mock_kwargs: Optional[Dict[str, Any]] = None,
    verbose: bool = False,
):
    """按 backend 创建单环境（``real`` / ``mock`` / ``auto``）。"""
    global _WARNED_FALLBACK
    backend = str(backend or "auto").lower()
    if backend not in BACKENDS:
        raise ValueError(f"未知 backend {backend!r}，可选 {BACKENDS}")
    if backend in ("real", "auto") and real_env_available():
        from hsbg.env.game_env import BattlegroundsEnv

        kwargs: Dict[str, Any] = {
            "num_players": int(num_players),
            "agent_index": int(agent_index),
            "opponent": str(opponent),
        }
        kwargs.update(env_kwargs or {})
        if seed is not None and "seed" not in kwargs:
            kwargs["seed"] = int(seed)
        return BattlegroundsEnv(**kwargs)
    if backend == "real":
        raise RuntimeError(
            "backend='real' 但真实环境不可用（hsbg.env 导入失败）；"
            "请改用 backend='mock' 或检查引擎/环境层"
        )
    if backend == "auto" and not _WARNED_FALLBACK:
        print("[hsbg.rl] 真实环境不可用，回退 backend='mock'（合成环境，仅接口验证用）")
        _WARNED_FALLBACK = True
    kwargs = {"num_players": int(num_players), "seed": int(seed or 0)}
    kwargs.update(mock_kwargs or {})
    return MockBattlegroundsEnv(**kwargs)


def env_backend_name(env: Any) -> str:
    """报告用：``real`` / ``mock`` + 类名。"""
    name = type(env).__name__
    if isinstance(env, MockBattlegroundsEnv):
        return f"mock({name})"
    return f"real({name})"


__all__ = [
    "BACKENDS",
    "MockBattlegroundsEnv",
    "make_env",
    "env_backend_name",
    "real_env_available",
]
