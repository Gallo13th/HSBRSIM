"""``BattlegroundsEnv`` —— 酒馆战棋单智能体强化学习环境。

对外 API 严格遵循 ``docs/ENV_SPEC.md``：

.. code-block:: python

    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=42)
    obs = env.reset(seed=42)                      # -> spec.Observation
    obs, reward, terminated, truncated, info = env.step(action)
    env.legal_actions()                           # == tuple(obs.candidates)
    env.action_mask()                             # 长度 == len(candidates)
    env.observation_space / env.action_space      # 兼容外观（dict / None）
    env.close()

step 内部顺序（ENV_SPEC §4）
--------------------------
1. 校验动作是**当前候选之一**（signature 比对；也接受下标）；
2. 应用到引擎（异常/拒绝 → ``invalid_action``，状态不推进）；
3. 结算 ``PendingChoice``：非智能体的自动结算；智能体的暴露为
   ``phase="choice"`` 观测（``auto_choice=True`` 时也自动结算）；
4. 若动作为 ``end_turn``：驱动 7 名对手招募 → ``game.end_recruit_phase()``
   （配对/战斗/幽灵战/淘汰/下一回合）→ 结算战斗奖励 → 淘汰/结束判定。

已知边界（引擎限制，见 driver 模块文档）
--------------------------------------
- ``end_recruit_phase`` 内（EoT 效果 / 战斗）产生的 PendingChoice **无法**
  暂停成 choice 决策步，一律自动结算；新回合开始后才出现的智能体选择
  （任务/饰品三选一）会保留为 ``phase="choice"`` 观测。
- 名次由环境记录淘汰顺序：``rank = 被淘汰时存活人数 + 1``，冠军 = 1。
- 确定性：``reset(seed)`` + 同一动作序列 ⇒ 完全相同的观测/奖励轨迹。

防 no-op 死循环（PPO 真环境冒烟暴露）
------------------------------------
1. **每回合动作预算** ``max_actions_per_turn``（默认 40）：本回合成功动作数
   达到预算后，候选只保留 ``end_turn``（``choose`` 选择步不受影响）；
   回合切换自动重置。正常对局每回合通常 ≤30 动作。
2. **freeze 单向候选**：只在"当前未冻结"时生成 ``freeze``，不提供解冻
   （否则随机策略会在 free toggle 上无限循环，实测曾占满 4000 步）。
3. **无进展保护**：同一回合连续 3 次动作后关键状态（金币/生命/等级/手牌/
   酒馆/棋盘/冻结标记/战力）完全无变化 → 同样只保留 ``end_turn``。
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from hsrl2.events import COMBAT_END, HERO_ELIMINATED, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.rng import GameRNG

from hsbg.agents.base import EnvContext
from hsbg.agents.registry import make_opponent
from hsbg.env import driver, observation
from hsbg.env.spec import (
    ActionKind,
    CandidateAction,
    EnvConfig,
    Observation,
    OBS_DIMS,
    PHASE_CHOICE,
    PHASE_GAME_OVER,
    PHASE_RECRUIT,
    RewardConfig,
)

__all__ = ["BattlegroundsEnv"]

_CARD_TYPE_HERO_NAME = "HERO"


def _placement_value(rank: int, num_players: int) -> float:
    """名次 → [-1, +1]（第 1 名 +1，最后一名 -1）。"""
    if num_players <= 1:
        return 1.0
    rank = max(1, min(int(rank), int(num_players)))
    return 1.0 - 2.0 * (rank - 1) / (num_players - 1)


def _board_power(hero: Hero) -> int:
    """棋盘战力 = Σ(atk + health)（用于 ``board_power_delta`` 奖励项）。"""
    total = 0
    for m in hero.board:
        try:
            total += int(getattr(m, "atk", 0) or 0)
            total += int(getattr(m, "health", 0) or 0)
        except Exception:                                 # noqa: BLE001
            continue
    return total


@dataclass
class _TurnStats:
    """一回合（end_turn 结算）内的战斗统计。"""

    dealt: int = 0
    taken: int = 0
    won: int = 0
    lost: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {"dealt": self.dealt, "taken": self.taken,
                "won": self.won, "lost": self.lost}


class BattlegroundsEnv:
    """8 人酒馆战棋环境（单智能体 + 脚本对手）。"""

    #: 供向量化/gym 包装识别的元数据
    metadata = {"render_modes": [], "num_players": 8}

    def __init__(self, num_players: int = 8, agent_index: int = 0,
                 opponent: str = "heuristic", hero_id: Optional[str] = None,
                 anomaly: Optional[str] = None, max_turns: int = 40,
                 max_steps: int = 4000, auto_choice: bool = False,
                 seed: Optional[int] = None,
                 reward: Optional[RewardConfig] = None,
                 *,
                 data_dir: Optional[str] = None,
                 max_opponent_actions: int = 160,
                 opponent_kwargs: Optional[Dict[str, Any]] = None,
                 max_actions_per_turn: int = 40) -> None:
        num_players = int(num_players)
        if not 2 <= num_players <= 8:
            raise ValueError(f"num_players must be 2..8, got {num_players}")
        agent_index = int(agent_index)
        if not 0 <= agent_index < num_players:
            raise ValueError(f"agent_index out of range: {agent_index}")
        if isinstance(reward, dict):
            reward = RewardConfig(**reward)
        max_actions_per_turn = int(max_actions_per_turn)
        if max_actions_per_turn <= 0:
            raise ValueError("max_actions_per_turn must be positive")
        cfg_kwargs: Dict[str, Any] = dict(
            num_players=num_players, agent_index=agent_index,
            opponent=str(opponent), hero_id=hero_id, anomaly=anomaly,
            max_turns=int(max_turns), max_steps=int(max_steps),
            auto_choice=bool(auto_choice), seed=seed,
            reward=reward if reward is not None else RewardConfig())
        # 前向兼容：若 spec.EnvConfig 已加入该字段则写入配置（否则作为
        # 环境层受保护参数保留 —— 不改 spec.py，见 ENV_SPEC/Lead 同步）。
        if "max_actions_per_turn" in getattr(EnvConfig, "__dataclass_fields__",
                                             {}):
            cfg_kwargs["max_actions_per_turn"] = max_actions_per_turn
        self.config = EnvConfig(**cfg_kwargs)
        self._max_actions_per_turn = int(
            getattr(self.config, "max_actions_per_turn",
                    max_actions_per_turn))
        self._no_progress_limit = 3
        self._budget_turn = 0
        self._actions_this_turn = 0
        self._no_progress = 0
        self.db = driver.get_card_db(data_dir)
        self._data_dir = data_dir
        self._max_opponent_actions = int(max_opponent_actions)
        self._opponent_kwargs = dict(opponent_kwargs or {})

        self.game: Optional[Game] = None
        self._all_heroes: List[Hero] = []
        self._agent: Optional[Hero] = None
        self._policies: List[Any] = []
        self._rank_by_hero: Dict[int, int] = {}
        self._elimination_order: List[Hero] = []

        self._step_actions: Optional[driver.StepActions] = None
        self._obs: Optional[Observation] = None
        self._step_count = 0
        self._turn_count = 0
        self._done = False
        self._seed: Optional[int] = None
        self._episode = 0
        self._turn_stats = _TurnStats()
        self._stats = {"episodes": 0, "steps": 0, "invalid": 0,
                       "choice_errors": 0, "opponent_rejects": 0,
                       "engine_errors": 0,
                       # 覆盖度/裁剪/预算/无进展审计计数（audit_env_coverage）
                       "choice_steps": 0,
                       "budget_exhausted": 0,
                       "noop_actions": 0,
                       "candidates_generated": 0,
                       "candidates_trimmed": 0,
                       "plays_dropped": 0,
                       "max_candidates_generated": 0,
                       "max_candidates": 0,
                       "hero_power_targeted": 0,
                       "play_minion_targeted": 0,
                       "play_spell_targeted": 0,
                       "magnetic_attach": 0,
                       "dual_target_power_candidates": 0}
        self._errors: List[str] = []
        self._engine_error: Optional[str] = None
        self._was_truncated = False
        self._closed = False

    # ══════════════════════════════════════════════════════════════
    # 兼容外观 / 只读属性
    # ══════════════════════════════════════════════════════════════

    @property
    def unwrapped(self) -> "BattlegroundsEnv":
        return self

    @property
    def observation_space(self) -> Dict[str, Any]:
        """观测的**逻辑尺寸**（dict 外观；不依赖 gymnasium）。"""
        dims = asdict(OBS_DIMS)
        dims["version"] = observation.ENTITY_TOKEN_VERSION
        dims["kind"] = "entity_tokens"
        return dims

    @property
    def action_space(self) -> None:
        """动态候选动作空间（无固定动作数）→ ``None``。"""
        return None

    @property
    def agent_hero(self) -> Optional[Hero]:
        return self._agent

    @property
    def num_players(self) -> int:
        """玩家数（评测/工具按此属性读取大厅规模）。"""
        return int(self.config.num_players)

    @property
    def max_actions_per_turn(self) -> int:
        return int(self._max_actions_per_turn)

    @property
    def heroes(self) -> Tuple[Hero, ...]:
        return tuple(self._all_heroes)

    @property
    def current_observation(self) -> Optional[Observation]:
        return self._obs

    @property
    def seed(self) -> Optional[int]:
        return self._seed

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def __repr__(self) -> str:                            # pragma: no cover
        return (f"BattlegroundsEnv(players={self.config.num_players}, "
                f"opponent={self.config.opponent!r}, seed={self._seed}, "
                f"turn={self._turn_count})")

    # ══════════════════════════════════════════════════════════════
    # 环境生命周期
    # ══════════════════════════════════════════════════════════════

    def _resolve_seed(self, seed: Optional[int]) -> int:
        if seed is not None:
            return int(seed) & 0x7FFFFFFF
        if self.config.seed is not None:
            return int(self.config.seed) & 0x7FFFFFFF
        # 未指定种子时用系统熵（new code 禁止 import random；AGENTS §3）
        return int.from_bytes(os.urandom(4), "little") & 0x7FFFFFFF

    def _hero_pool(self) -> List[str]:
        ids: List[str] = []
        for d in self.db._by_id.values():
            try:
                is_hero = int(getattr(d, "card_type", -1)) == 3
            except Exception:                             # noqa: BLE001
                is_hero = False
            if not is_hero:
                continue
            cid = str(getattr(d, "id", ""))
            if cid.startswith(("TB_BaconShop_HERO", "BG")):
                ids.append(cid)
        ids.sort()
        if not ids:
            raise RuntimeError("CardDB 中没有可用英雄卡（数据缺失）")
        return ids

    def reset(self, seed: Optional[int] = None,
              options: Optional[Dict[str, Any]] = None) -> Observation:
        """创建英雄/对局并返回首个决策观测（招募或选择阶段）。"""
        self._closed = False
        self._seed = self._resolve_seed(seed)
        self._episode += 1
        self._stats["episodes"] += 1
        self._step_count = 0
        self._rank_by_hero = {}
        self._elimination_order = []
        self._errors = []
        self._turn_stats = _TurnStats()
        self._done = False
        self._was_truncated = False
        self._budget_turn = 1
        self._actions_this_turn = 0
        self._no_progress = 0

        num_players = int(self.config.num_players)
        pool = self._hero_pool()
        # 英雄抽取使用**独立** RNG（不消耗 game.rng 的随机流）
        rng = GameRNG((self._seed * 1000003 + 17) & 0x7FFFFFFF)
        agent_hero_index = 0
        cfg_hero = self.config.hero_id
        if cfg_hero is not None:
            if cfg_hero not in pool:
                raise ValueError(f"unknown hero_id {cfg_hero!r}")
            agent_card = cfg_hero
        else:
            agent_card = rng.choice(pool, label="agent_hero")
        rest = [cid for cid in pool if cid != agent_card]
        rng.shuffle(rest, label="hero_pool")
        hero_cards: List[str] = []
        for i in range(num_players):
            if i == self.config.agent_index:
                hero_cards.append(agent_card)
            else:
                hero_cards.append(rest.pop() if rest else agent_card)
        heroes = [Hero(cid, f"P{i}") for i, cid in enumerate(hero_cards)]

        game = Game(heroes, self.db, seed=self._seed,
                    anomaly=self.config.anomaly)
        self.game = game
        self._all_heroes = heroes
        self._agent = heroes[self.config.agent_index]
        self._agent_index = int(self.config.agent_index)

        # 对手策略（每个对手一个独立实例，带各自每回合状态）
        self._policies = [None] * num_players
        for i in range(num_players):
            if i == self._agent_index:
                continue
            self._policies[i] = make_opponent(self.config.opponent,
                                              **self._opponent_kwargs)

        # 名次 / 战斗统计监听（owner = 智能体英雄 → 随其淘汰自动注销）
        game.events.register(Listener(
            event=HERO_ELIMINATED, owner=self._agent,
            callback=self._on_hero_eliminated))
        game.events.register(Listener(
            event=COMBAT_END, owner=self._agent,
            callback=self._on_combat_end))

        game.start_game()
        self._turn_count = int(game.turn)
        # 开局选择（部分英雄技能 on_bind 会挂起发现/三选一）
        pending = self._drain_choices()
        self._obs = self._observe(pending=pending)
        return self._obs

    def close(self) -> None:
        """释放引擎引用（不触发任何引擎副作用）。"""
        self._closed = True
        self.game = None
        self._step_actions = None
        self._obs = None
        self._all_heroes = []
        self._agent = None
        self._policies = []

    # ══════════════════════════════════════════════════════════════
    # 动作 API
    # ══════════════════════════════════════════════════════════════

    def legal_actions(self) -> Tuple[CandidateAction, ...]:
        """当前步的合法候选动作（== ``obs.candidates``）。"""
        if self._step_actions is None:
            return ()
        return self._step_actions.candidates

    def action_mask(self) -> Tuple[bool, ...]:
        return tuple(True for _ in self.legal_actions())

    def num_actions(self) -> int:
        return len(self.legal_actions())

    # ══════════════════════════════════════════════════════════════
    # step
    # ══════════════════════════════════════════════════════════════

    def step(self, action: Any) -> Tuple[Observation, float, bool, bool,
                                         Dict[str, Any]]:
        """执行一个动作。``action`` 可以是候选下标 / CandidateAction /
        ActionDescriptor。

        **终止契约**（所有分支共用 `_termination_check`）：
        - 智能体死亡 / 游戏结束 / `max_steps` / `max_turns` → terminated 或
          truncated；
        - 兜底：若观测已进入 ``phase="game_over"``（或无候选）但 ``_done``
          尚未置位，本方法**立即收口为 terminated**，绝不返回
          ``(obs, invalid, False, False)`` 的无效循环。
        """
        if self.game is None:
            raise RuntimeError("env.step() called before reset()")
        if self._done:
            # 已终局后再 step：不是非法动作，而是"回合外调用"——返回
            # terminated=True 且不推进步数（禁止 invalid 循环的兼容行为）
            info = self._make_info(terminated_reason="episode_done")
            info["invalid"] = False
            info["wrong_action"] = True
            info["episode_done"] = True
            info["warning"] = "step_after_done"
            return self._obs, 0.0, True, bool(self._truncated), info

        # 兜底终止：上一次观测已终局但 _done 未置位（旧状态/外部强制/
        # 非 end_turn 动作致死残余）→ 立即返回 terminated，不消耗步数
        stale = self._termination_check()
        if stale is not None:
            return stale

        rc = self.config.reward
        self._step_count += 1
        self._stats["steps"] += 1

        descriptor = self._resolve_action(action)
        if descriptor is None:
            # 非候选动作：若当前状态已终局（无候选）先收口，禁止 invalid 循环
            stale = self._termination_check()
            if stale is not None:
                return stale
            # 非候选动作：状态不推进
            self._stats["invalid"] += 1
            reward = float(rc.invalid_action) if rc.invalid_action else 0.0
            info = self._make_info(terminated_reason="invalid_action")
            info["invalid"] = True
            info["wrong_action"] = True
            info["action_error"] = "not a current candidate"
            return self._obs, reward, False, False, info

        is_end_turn = descriptor.kind == "end_turn"
        if not is_end_turn:
            fp_before = self._progress_fingerprint()
            result = driver.apply_action(self.game, self._agent, descriptor)
            if not result.success:
                # 候选被引擎拒绝（理论上不应发生）→ 视为非法动作，不推进
                self._stats["invalid"] += 1
                reward = float(rc.invalid_action) if rc.invalid_action else 0.0
                info = self._make_info(terminated_reason="engine_rejected")
                info["invalid"] = True
                info["wrong_action"] = True
                info["action_error"] = result.error
                info["action_error_type"] = result.error_type
                return self._obs, reward, False, False, info
            # 回合动作预算 / 无进展保护（choose 是引擎强制结算步，不计数）
            if descriptor.kind != ActionKind.CHOOSE.value:
                self._actions_this_turn += 1
                if self._progress_fingerprint() == fp_before:
                    self._no_progress += 1
                    self._stats["noop_actions"] += 1
                else:
                    self._no_progress = 0
            pending = self._drain_choices()
            if pending is not None:
                self._obs = self._observe(pending=pending)
                # 选择推进后同样检查终止（选择类效果也可能致死/结束游戏）
                terminal = self._termination_check()
                if terminal is not None:
                    return terminal
                return (self._obs, float(rc.step_penalty), False, False,
                        self._make_info())
            self._obs = self._observe()
            # 统一终止判定：自伤类英雄技能/战吼等非 end_turn 动作也可致死、
            # 也可能触发 max_steps/max_turns → 必须在此收口
            terminal = self._termination_check()
            if terminal is not None:
                return terminal
            return (self._obs, float(rc.step_penalty), False, False,
                    self._make_info())

        # ── end_turn：整回合推进 ──
        return self._end_turn_step()

    # ══════════════════════════════════════════════════════════════
    # 内部：动作解析 / 观测
    # ══════════════════════════════════════════════════════════════

    def _resolve_action(self, action: Any
                        ) -> Optional[driver.ActionDescriptor]:
        if self._step_actions is None:
            return None
        descriptors = self._step_actions.descriptors
        if isinstance(action, bool):
            return None
        if isinstance(action, int):
            if 0 <= action < len(descriptors):
                return descriptors[int(action)]
            return None
        sig = None
        if isinstance(action, CandidateAction):
            sig = action.signature()
        elif isinstance(action, driver.ActionDescriptor):
            sig = action.signature()
        elif isinstance(action, (tuple, list)):
            try:
                sig = CandidateAction(*action).signature()
            except Exception:                             # noqa: BLE001
                return None
        else:
            return None
        for d, cand in zip(descriptors, self._step_actions.candidates):
            if cand.signature() == sig:
                return d
        return None

    @property
    def _truncated(self) -> bool:
        return bool(getattr(self, "_was_truncated", False))

    # ── 回合动作预算 / 无进展保护 ──

    def _sync_turn_budget(self, turn: int) -> None:
        """回合切换时重置动作预算与无进展计数。"""
        if int(turn) != self._budget_turn:
            self._budget_turn = int(turn)
            self._actions_this_turn = 0
            self._no_progress = 0

    def _budget_exhausted(self) -> bool:
        """本回合动作预算是否用尽（或已连续多步无进展）。

        用尽后候选只保留 ``end_turn``（``choose`` 由选择阶段单独枚举，
        不受影响），避免"随机策略反复选免费 no-op 动作"拖满 ``max_steps``。
        """
        return (self._actions_this_turn >= self._max_actions_per_turn
                or self._no_progress >= self._no_progress_limit)

    # ── 统一终止判定（所有 step 分支共用，见 ENV_SPEC §终止契约）──

    def _agent_rank(self) -> int:
        """智能体当前名次（淘汰时用记录的 rank；存活时按血量估计）。"""
        agent = self._agent
        recorded = self._rank_by_hero.get(id(agent))
        if recorded:
            return int(recorded)
        if not agent.is_alive:
            return max(1, self._free_alive_count() + 1)
        return int(observation.estimate_rank(agent, self._all_heroes,
                                             self._rank_by_hero))

    def _terminal_reward(self, *, rank: Optional[int] = None,
                         timeout: bool = False) -> float:
        """终局奖励基数（step_penalty + placement / timeout）。"""
        rc = self.config.reward
        reward = float(rc.step_penalty)
        if rank is not None:
            reward += float(rc.placement) * _placement_value(
                int(rank), int(self.config.num_players))
        if timeout:
            reward += float(rc.timeout)
        return reward

    def _terminal_obs_info(self, reason: str, *, reward: float,
                           truncated: bool,
                           combat: Optional[Dict[str, int]] = None
                           ) -> Tuple[Observation, float, bool, bool,
                                      Dict[str, Any]]:
        """统一终止出口：置 done、清残余选择、game_over 观测、标准 info。"""
        self._done = True
        self._was_truncated = bool(truncated)
        self._drain_all_choices()
        self._obs = self._observe(phase=PHASE_GAME_OVER)
        info = self._make_info(combat=combat, terminated_reason=reason)
        info["agent_rank"] = int(self._agent_rank())
        info["elimination_order"] = [
            str(h.card_id) for h in self._elimination_order]
        info["truncated"] = bool(truncated)
        return (self._obs, float(reward), not truncated, truncated, info)

    def _termination_check(self, *, combat: Optional[Dict[str, int]] = None
                           ) -> Optional[Tuple[Observation, float, bool, bool,
                                               Dict[str, Any]]]:
        """统一终止判定（非 end_turn / end_turn / choice 分支共用）。

        判定顺序：淘汰 → 全胜结束 → ``max_steps`` → ``max_turns`` →
        **兜底契约**（``obs.phase == game_over`` 或无候选但 ``_done`` 未置位）。

        修复的阻断 bug：自伤类英雄技能（如 TB_BaconShop_HP_049 "Take 2
        damage"）在**非 end_turn** 分支把智能体打死时，旧实现直接返回
        ``(obs, r, False, False)``；此后 ``obs.candidates`` 为空，继续 step
        只会返回 ``invalid=True`` 且永不终止（实测 seed=24 无限循环）。
        """
        if self._done:
            return None
        agent = self._agent
        game = self.game
        if not agent.is_alive:
            rank = self._agent_rank()
            return self._terminal_obs_info(
                "eliminated", truncated=False,
                reward=self._terminal_reward(rank=rank), combat=combat)
        if game.finished:
            return self._terminal_obs_info(
                "game_over", truncated=False,
                reward=self._terminal_reward(rank=1), combat=combat)
        if self._step_count >= int(self.config.max_steps):
            return self._terminal_obs_info(
                "max_steps", truncated=True,
                reward=self._terminal_reward(timeout=True), combat=combat)
        if int(game.turn) > int(self.config.max_turns):
            return self._terminal_obs_info(
                "max_turns", truncated=True,
                reward=self._terminal_reward(timeout=True), combat=combat)
        obs = self._obs
        if obs is not None and (getattr(obs, "phase", "") == PHASE_GAME_OVER
                                or not obs.candidates):
            # 兜底：观测已终局（或候选为空）而 _done 未置位 → 强制收口，
            # 绝不把这类状态当作 invalid 动作无限循环
            eliminated = not agent.is_alive
            reason = "eliminated" if eliminated else "game_over"
            return self._terminal_obs_info(
                reason, truncated=False,
                reward=self._terminal_reward(
                    rank=self._agent_rank() if eliminated else 1),
                combat=combat)
        return None


    def _account_step(self, step_actions: Any) -> None:
        """按候选类别/目标变体累计审计计数（audit_env_coverage 用）。"""
        stats = self._stats
        for cand, desc in zip(step_actions.candidates,
                              step_actions.descriptors):
            kind = cand.kind
            if kind == ActionKind.HERO_POWER.value:
                if cand.tgt_zone:
                    stats["hero_power_targeted"] += 1
                if desc.note == "targets=2":
                    stats["dual_target_power_candidates"] += 1
            elif kind == ActionKind.PLAY_MINION.value:
                if cand.tgt_zone:
                    stats["play_minion_targeted"] += 1
                if getattr(desc, "magnetic", False):
                    stats["magnetic_attach"] += 1
            elif kind == ActionKind.PLAY_SPELL.value:
                if cand.tgt_zone:
                    stats["play_spell_targeted"] += 1

    def _progress_fingerprint(self) -> Tuple:
        """招募期内"关键状态"指纹（用于检测无进展动作）。

        覆盖金币/生命/等级/手牌/酒馆/棋盘/冻结标记/场面战力：
        任何真实推进都会改变指纹；纯 toggle/空转动作不会。
        """
        hero = self._agent
        if hero is None:
            return ()
        try:
            return (
                int(hero.gold),
                int(hero.health),
                int(hero.armor),
                int(hero.tavern_tier),
                int(hero.upgrade_cost),
                bool(hero.frozen_tavern),
                len(hero.hand),
                len(hero.board),
                len(hero.tavern),
                tuple(str(e.card_id) for e in hero.hand),
                tuple(str(e.card_id) for e in hero.tavern),
                tuple(str(m.card_id) for m in hero.board),
                _board_power(hero),
            )
        except Exception:                                 # noqa: BLE001
            return ()

    def _observe(self, *, pending: Any = None,
                 phase: Optional[str] = None) -> Observation:
        game = self.game
        agent = self._agent
        forced = phase
        self._sync_turn_budget(int(game.turn))
        if pending is None and game.pending_choices:
            head = game.pending_choices[0]
            if getattr(head, "owner", None) is agent:
                pending = head
        if pending is not None:
            zones = driver.collect_zones(game, agent)
            descriptors = driver.enumerate_choice(game, pending, zones)
            candidates = tuple(d.to_candidate() for d in descriptors)
            self._step_actions = driver.StepActions(
                zones=zones, descriptors=descriptors, candidates=candidates)
            phase = PHASE_CHOICE
        elif forced == PHASE_GAME_OVER or not agent.is_alive or game.finished:
            zones = driver.collect_zones(game, agent)
            self._step_actions = driver.StepActions(
                zones=zones, descriptors=[], candidates=())
            phase = PHASE_GAME_OVER
        else:
            self._step_actions = driver.enumerate_step(
                game, agent, stats=self._stats)
            phase = PHASE_RECRUIT
            if self._budget_exhausted():
                # 预算用尽/无进展 → 只允许结束回合
                self._stats["budget_exhausted"] += 1
                end = driver.ActionDescriptor(
                    kind=ActionKind.END_TURN.value)
                self._step_actions = driver.StepActions(
                    zones=self._step_actions.zones, descriptors=[end],
                    candidates=(end.to_candidate(),))
        if phase == PHASE_CHOICE:
            self._stats["choice_steps"] += 1
        elif phase == PHASE_RECRUIT:
            self._account_step(self._step_actions)
        zones = self._step_actions.zones
        candidates = self._step_actions.candidates
        # 观测 v2: extra 与 info["obs_extra"] 同源（这里只构建一次；
        # build_observation 内部做纯数据深拷贝，保证每个 obs 相互独立）
        extra = observation.build_extra_state(
            game, agent, zones=zones,
            lobby_heroes=self._all_heroes,
            eliminated_rank=self._rank_by_hero,
            turn_stats=self._turn_stats.as_dict(),
            env_stats=self._stats,
        )
        obs = observation.build_observation(
            game, agent, candidates,
            phase=phase,
            pending=pending if phase == PHASE_CHOICE else None,
            zones=zones,
            lobby_heroes=self._all_heroes,
            eliminated_rank=self._rank_by_hero,
            total_players=self.config.num_players,
            turn=int(game.turn),
            log=f"turn={int(game.turn)} phase={phase} "
                f"n_cand={len(candidates)}",
            extra=extra,
        )
        return obs

    # ══════════════════════════════════════════════════════════════
    # 内部：PendingChoice 结算
    # ══════════════════════════════════════════════════════════════

    def _drain_choices(self) -> Any:
        """结算选择：非智能体的自动；智能体的按 ``auto_choice`` 决定。"""
        game = self.game
        if not game.pending_choices:
            return None
        policy_fn = None
        if self.config.auto_choice:
            policy_fn = lambda choice: driver.default_pick_index(choice, game)
        errors: List[str] = []
        pending = driver.resolve_pending_choices(
            game, self._agent, policy_fn, errors=errors)
        if errors:
            self._errors.extend(errors)
            self._stats["choice_errors"] += len(errors)
        return pending

    def _drain_all_choices(self) -> None:
        """自动结算**全部**选择（含智能体）——用于不可暂停的阶段。"""
        game = self.game
        if not game.pending_choices:
            return
        errors: List[str] = []
        driver.resolve_pending_choices(game, None, None, errors=errors)
        if errors:
            self._errors.extend(errors)
            self._stats["choice_errors"] += len(errors)

    # ══════════════════════════════════════════════════════════════
    # 内部：事件回调
    # ══════════════════════════════════════════════════════════════

    def _on_hero_eliminated(self, game: Game, hero: Any = None,
                            **kwargs: Any) -> None:
        """记录淘汰次序：``rank = 被淘汰时存活人数 + 1``。"""
        try:
            alive = sum(1 for h in game.heroes if h.is_alive)
            self._rank_by_hero[id(hero)] = int(alive) + 1
            self._elimination_order.append(hero)
        except Exception:                                 # noqa: BLE001
            pass

    def _on_combat_end(self, game: Game, hero_a: Any = None,
                       hero_b: Any = None, result: Any = None,
                       **kwargs: Any) -> None:
        """统计本回合智能体的战斗伤害（造成/承受）。"""
        if result is None:
            return
        try:
            damage = int(getattr(result, "capped_damage", 0) or 0)
            winner = getattr(result, "winner", None)
            loser = getattr(result, "loser", None)
            agent = self._agent
            if loser is agent:
                self._turn_stats.taken += damage
                self._turn_stats.lost += 1
            elif winner is agent:
                self._turn_stats.dealt += damage
                self._turn_stats.won += 1
        except Exception:                                 # noqa: BLE001
            pass

    # ══════════════════════════════════════════════════════════════
    # 内部：对手招募驱动
    # ══════════════════════════════════════════════════════════════

    def _policy_for(self, hero: Hero) -> Any:
        try:
            idx = self._all_heroes.index(hero)
        except ValueError:
            return None
        if 0 <= idx < len(self._policies):
            return self._policies[idx]
        return None

    def _drive_opponents(self, *, stop_if_agent_dead: bool = True) -> None:
        """驱动全部存活对手完成招募阶段（受 ``max_opponent_actions`` 保护）。"""
        game = self.game
        agent = self._agent
        for hero in list(game.heroes):
            if hero is agent or not hero.is_alive:
                continue
            policy = self._policy_for(hero)
            if policy is None:
                continue
            zones = driver.collect_zones(game, hero)
            for _ in range(self._max_opponent_actions):
                if not hero.is_alive:
                    break
                if stop_if_agent_dead and not agent.is_alive:
                    break
                ctx = EnvContext(game=game, zones=zones,
                                 agent_hero=agent, turn=int(game.turn))
                try:
                    desc = policy.choose(game, hero, ctx)
                except Exception:                         # noqa: BLE001
                    desc = None
                if desc is None:
                    break
                result = driver.apply_action(game, hero, desc)
                if not result.success:
                    self._stats["opponent_rejects"] += 1
                    self._errors.append(
                        f"opponent_rejected:{result.kind}:{result.error}")
                    break
                self._drain_all_choices()
                zones = driver.collect_zones(game, hero)

    # ══════════════════════════════════════════════════════════════
    # 内部：end_turn 回合推进
    # ══════════════════════════════════════════════════════════════

    def _run_end_recruit_phase(self) -> None:
        """调用 ``game.end_recruit_phase()``，期间产生的选择自动结算。

        - ``ChoiceQueue`` 让「入队即结算」：``EoT`` 效果 / 战斗 / 幽灵战中
          的 PendingChoice 无法暂停成决策步，就地结算（lead 引擎集成要点 1）；
        - **新回合开始后**才出现的智能体选择（任务/饰品三选一）不自动结算，
          留在队列里，阶段结束后作为 ``phase="choice"`` 观测暴露。
        """
        game = self.game
        agent = self._agent
        turn_before = int(game.turn)
        errors: List[str] = []

        def _hold(choice: Any) -> bool:
            if getattr(choice, "owner", None) is not agent:
                return False
            return int(game.turn) > turn_before

        old = game.pending_choices
        queue = driver.ChoiceQueue(game, hold_fn=_hold, errors=errors)
        game.pending_choices = queue
        engine_error = None
        try:
            game.end_recruit_phase()
        except Exception as exc:                          # noqa: BLE001
            engine_error = f"{type(exc).__name__}: {exc}"
        finally:
            # 把残余（held 的智能体选择）搬回原列表，恢复引擎属性
            leftovers = list(queue)
            game.pending_choices = old
            old.extend(leftovers)
        if errors:
            self._errors.extend(errors)
            self._stats["choice_errors"] += len(errors)
        if engine_error is not None:
            self._stats["engine_errors"] += 1
            self._errors.append(f"end_recruit_phase:{engine_error}")
            self._engine_error = engine_error

    def _end_turn_step(self) -> Tuple[Observation, float, bool, bool,
                                      Dict[str, Any]]:
        rc = self.config.reward
        game = self.game
        agent = self._agent
        self._engine_error = None
        health_before = int(agent.health)
        power_before = _board_power(agent)
        self._turn_stats = _TurnStats()

        # 1) 对手招募阶段
        self._drive_opponents()
        # 2) 配对 → 战斗 → 幽灵战 → 淘汰 → 下一回合
        self._run_end_recruit_phase()
        self._turn_count = int(game.turn)

        # 3) 回合奖励项
        health_after = int(agent.health)
        power_after = _board_power(agent)
        stats = self._turn_stats
        reward = 0.0
        reward += rc.health_delta * float(health_after - health_before)
        reward += rc.combat_damage * float(stats.dealt - stats.taken) / 10.0
        reward += rc.board_power_delta * float(power_after - power_before) / 50.0
        if agent.is_alive:
            reward += float(rc.survival)
        reward += float(rc.step_penalty)

        terminated = False
        truncated = False
        reason = ""
        self._was_truncated = False

        if not agent.is_alive:
            terminated = True
            reason = "eliminated"
            rank = int(self._rank_by_hero.get(id(agent),
                                              self._free_alive_count() + 1))
            reward += rc.placement * _placement_value(
                rank, self.config.num_players)
        elif game.finished:
            terminated = True
            reason = "game_over"
            rank = 1
            reward += rc.placement * _placement_value(
                rank, self.config.num_players)
        else:
            # 截断判定（回合上限 / 步数上限）
            if (int(game.turn) > int(self.config.max_turns)
                    or self._step_count >= int(self.config.max_steps)):
                truncated = True
                reason = ("max_turns"
                          if int(game.turn) > int(self.config.max_turns)
                          else "max_steps")
                reward += float(rc.timeout)
            if self._step_count >= int(self.config.max_steps):
                truncated = True
            self._was_truncated = truncated

        if self._engine_error is not None and not terminated:
            # 引擎异常：无法保证状态一致 → 结束本局（训练进程不崩）
            terminated = True
            reason = reason or "engine_error"

        if terminated or truncated:
            # 统一终止出口（与非 end_turn 分支同一条路径）
            result = self._terminal_obs_info(
                reason, reward=float(reward), truncated=bool(truncated),
                combat=stats.as_dict())
            if self._engine_error is not None:
                result[4]["engine_error"] = self._engine_error
            return result

        # 4) 下一回合决策观测（可能先是选择步）
        pending = self._drain_choices()
        self._obs = self._observe(pending=pending)
        info = self._make_info(combat=stats.as_dict())
        return self._obs, float(reward), False, False, info

    def _free_alive_count(self) -> int:
        """当前存活玩家数（含尚未被引擎移除的濒死英雄）."""
        try:
            return sum(1 for h in self._all_heroes if h.is_alive)
        except Exception:                                 # noqa: BLE001
            return 0

    # ══════════════════════════════════════════════════════════════
    # info
    # ══════════════════════════════════════════════════════════════

    def _make_info(self, *, combat: Optional[Dict[str, int]] = None,
                   terminated_reason: str = "") -> Dict[str, Any]:
        game = self.game
        agent = self._agent
        turn = int(getattr(game, "turn", 0))
        alive_count = self._free_alive_count()
        rank = observation.estimate_rank(agent, self._all_heroes,
                                         self._rank_by_hero)
        phase = getattr(self._obs, "phase", PHASE_RECRUIT) \
            if self._obs is not None else PHASE_RECRUIT
        info: Dict[str, Any] = {
            "turn": turn,
            "rank": int(rank),
            "health": int(agent.health),
            "armor": int(agent.armor),
            "alive_count": int(alive_count),
            "combat": dict(combat or {}),
            "wrong_action": False,
            "invalid": False,
            "terminated_reason": str(terminated_reason),
            "seed": int(self._seed) if self._seed is not None else -1,
            "episode": int(self._episode),
            "episode_steps": int(self._step_count),
            "phase": phase,
            "engine_errors": int(self._stats["engine_errors"]),
            "choice_errors": int(self._stats["choice_errors"]),
        }
        # 观测 v2: info["obs_extra"] 复用当前 obs.extra（同源、不重复构建）。
        # 保留该键兼容旧消费方；新代码优先读 obs.extra / obs.get_extra()。
        if self._obs is not None:
            info["obs_extra"] = self._obs.extra
        else:
            try:
                info["obs_extra"] = self.extra_state()
            except Exception as exc:                      # noqa: BLE001
                self._errors.append(
                    f"obs_extra:{type(exc).__name__}: {exc}")
        return info

    def extra_state(self) -> Dict[str, Any]:
        """构建当前决策状态 dict（观测 v2 ``Observation.extra`` 的同一数据源）。

        纯数据（可 pickle、无引擎对象）；**只读**，不修改引擎状态/不消耗 RNG。
        ``_observe`` 每步用本函数构建一次并注入 ``obs.extra``，
        ``info["obs_extra"]`` 复用该对象（同源、不重复构建）。
        """
        if self.game is None:
            return {}
        return observation.build_extra_state(
            self.game, self._agent,
            lobby_heroes=self._all_heroes,
            eliminated_rank=self._rank_by_hero,
            turn_stats=self._turn_stats.as_dict(),
            env_stats=self._stats,
        )
