"""引擎 forward model 适配层（Phase 1）。

封装 env-builder 的 ``hsbg.planning`` v1 接口（clone / legal_actions / apply /
drain_choices / rng fork / simulate_combat），只暴露搜索需要的最小 API：

- ``clone()``：独立副本（不污染原对局）；
- ``candidates() -> tuple[CandidateAction]``：当前合法候选；
- ``apply(cand)``：应用一个候选；``end_turn`` 会自动推进 ``end_recruit_phase``；
- ``apply_macro(macro)``：按序应用 macro（最后一个应为 ``end_turn``）；
- ``is_terminal()`` / ``rank()`` / ``terminal_utility()``；
- ``drain_choices()``：Phase 1 的选择步用引擎默认策略结算（不建 choice 子搜索）；
- ``fork_rng(seed)``：chance node / 可复现采样（K=1 时可选）。

不修改 ``hsbg/planning`` 或引擎；只读式调用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from hsbg import planning
from hsbg.env.driver import ActionDescriptor
from hsbg.env.spec import CandidateAction
from hsrl2.game import Game
from hsrl2.hero import Hero

from hsbg.search.types import MacroAction, placement_utility

__all__ = ["EngineForwardModel", "ACTION_END_TURN"]

#: end_turn 的 kind 字符串（避免循环 import driver.ActionKind）
ACTION_END_TURN = "end_turn"


@dataclass
class EngineForwardModel:
    """可 clone 的对局状态 + 搜索引擎需要的读写原语（单智能体视角）。"""

    game: Game
    hero_card_id: str
    total_players: int = 8
    hero_index_hint: int = -1
    _hero: Optional[Hero] = field(default=None, repr=False, compare=False)

    # ── 构造 / 复制 ──
    @classmethod
    def from_game(cls, game: Game, hero: Any = None,
                  *, total_players: int = 8,
                  clone: bool = False) -> "EngineForwardModel":
        """用引擎 ``Game`` 构造；默认不 clone（调用方负责隔离）。"""
        g = planning.clone(game) if clone else game
        if hero is None:
            if not g.heroes:
                raise ValueError("game 没有英雄")
            hero = g.heroes[0]
        else:
            # hero 可能来自原 game：按原索引/身份映射到 g
            if hero not in game.heroes:
                raise ValueError("hero 不在 game.heroes")
            idx = game.heroes.index(hero)
            hero = g.heroes[idx]
        idx2 = g.heroes.index(hero)
        return cls(game=g, hero_card_id=str(hero.card_id),
                   total_players=int(total_players), hero_index_hint=idx2)

    @classmethod
    def from_env(cls, env: Any, *, clone: bool = False) -> "EngineForwardModel":
        """从 ``BattlegroundsEnv`` 构造（默认不 clone；bench 输入用 clone=True）。"""
        game = getattr(env, "game", None)
        hero = getattr(env, "_agent", None)
        if game is None or hero is None:
            raise ValueError("env 未 reset 或缺少 game/_agent")
        total = int(getattr(env, "num_players", 8))
        return cls.from_game(game, hero, total_players=total, clone=clone)

    def clone(self) -> "EngineForwardModel":
        """独立副本；``hero`` 在副本中按 card_id 延迟解析。"""
        dup = planning.clone(self.game)
        return EngineForwardModel(
            game=dup, hero_card_id=self.hero_card_id,
            total_players=self.total_players,
            hero_index_hint=self.hero_index_hint, _hero=None,
        )

    # ── 状态读取 ──
    @property
    def hero(self) -> Hero:
        if self._hero is not None and self._hero in self.game.heroes:
            return self._hero
        for h in self.game.heroes:
            if str(h.card_id) == self.hero_card_id:
                self._hero = h
                return h
        raise ValueError(f"hero {self.hero_card_id} 不在 game.heroes（可能已被淘汰）")

    @property
    def turn(self) -> int:
        return int(getattr(self.game, "turn", 0))

    @property
    def alive_count(self) -> int:
        return int(sum(1 for h in self.game.heroes if bool(getattr(h, "is_alive", False))))

    def is_terminal(self) -> bool:
        """智能体死亡 / 游戏结束 = 终局；注意英雄可能已从 game.heroes 移除。"""
        try:
            hero = self.hero
        except ValueError:
            return True
        return bool(planning.is_terminal(self.game, hero))

    def rank(self) -> int:
        """估计名次：死亡 → 存活数+1；冠军 → 1；存活 → 按血量粗估（与 planning 一致）。"""
        try:
            hero = self.hero
        except ValueError:
            return max(1, self.alive_count + 1)
        if not bool(getattr(hero, "is_alive", False)):
            return max(1, self.alive_count + 1)
        if bool(getattr(self.game, "finished", False)):
            return 1
        my_hp = int(getattr(hero, "health", 0) or 0) + int(getattr(hero, "armor", 0) or 0)
        better = sum(
            1 for h in self.game.heroes
            if h is not hero and bool(getattr(h, "is_alive", False))
            and int(getattr(h, "health", 0) or 0) + int(getattr(h, "armor", 0) or 0) > my_hp
        )
        return 1 + better

    def terminal_utility(self) -> float:
        return placement_utility(self.rank(), self.total_players)

    def state_summary(self) -> Dict[str, Any]:
        try:
            hero = self.hero
            return {
                "turn": self.turn,
                "rank": self.rank(),
                "alive_count": self.alive_count,
                "health": int(getattr(hero, "health", 0) or 0),
                "board": len(getattr(hero, "board", ()) or ()),
                "hand": len(getattr(hero, "hand", ()) or ()),
                "terminal": self.is_terminal(),
            }
        except ValueError:
            return {"turn": self.turn, "rank": self.rank(),
                    "alive_count": self.alive_count, "terminal": True}

    # ── 动作读取 / 应用 ──
    def drain_choices(self) -> bool:
        """用引擎默认策略结算该英雄的 PendingChoice（Phase 1 不做 choice 子搜索）。"""
        try:
            planning.drain_choices(self.game, self.hero)
            return True
        except Exception:  # noqa: BLE001 - 搜索不能因单个选择失败崩溃
            return False

    def legal_actions(self) -> List[ActionDescriptor]:
        return planning.legal_actions(self.game, self.hero)

    def candidates(self) -> Tuple[CandidateAction, ...]:
        if self.is_terminal():
            return ()
        self.drain_choices()
        out: List[CandidateAction] = []
        for desc in self.legal_actions():
            try:
                out.append(desc.to_candidate())
            except Exception:  # noqa: BLE001
                continue
        return tuple(out)

    def apply(self, cand: CandidateAction, *,
              advance_end_turn: bool = True) -> bool:
        """应用一个候选；``end_turn`` 成功后（可选）推进引擎宏回合。

        ``advance_end_turn=False`` 用于 macro 生成/“战斗叶”优化：只应用候选，
        不跑 ``end_recruit_phase``（后续用 ``planning.simulate_turn_combat``）。
        """
        if self.is_terminal():
            return False
        res = planning.apply(self.game, self.hero, cand)
        if not bool(getattr(res, "success", False)):
            # 兜底：按 signature 重新匹配（CandidateAction 的槽位可能过期）
            try:
                desc = next(
                    (d for d in self.legal_actions()
                     if d.to_candidate().signature() == cand.signature()), None)
                if desc is None:
                    return False
                res = planning.apply(self.game, self.hero, desc)
            except Exception:  # noqa: BLE001
                return False
        if not bool(getattr(res, "success", False)):
            return False
        self.drain_choices()
        if str(getattr(cand, "kind", "")) == ACTION_END_TURN and advance_end_turn:
            if not self.is_terminal():
                try:
                    self.game.end_recruit_phase()
                except Exception:  # noqa: BLE001
                    return False
                self.drain_choices()
        return True

    def apply_macro(self, macro: MacroAction, *,
                    advance_end_turn: bool = True) -> bool:
        for cand in macro.steps:
            if self.is_terminal():
                return False
            if not self.apply(cand, advance_end_turn=advance_end_turn):
                return False
        return True

    def apply_macro_before_end(self, macro: MacroAction) -> bool:
        """只应用 macro 中 end_turn 之前的招募动作（叶子 combat 评估用）。"""
        for cand in macro.steps:
            if str(getattr(cand, "kind", "")) == ACTION_END_TURN:
                return True
            if self.is_terminal():
                return False
            if not self.apply(cand, advance_end_turn=False):
                return False
        return True

    # ── 叶节点快速评估（env-builder 建议：simulate_turn_combat 替代 ERP） ──
    def combat_leaf(self) -> Tuple[Optional[Dict[str, Any]], Optional["EngineForwardModel"]]:
        """无副作用地跑本回合战斗，返回 (summary, 战斗后副本模型)。

        用 ``planning.simulate_turn_combat(keep_state=True)``（8p 实测 ~3.5ms，
        比完整 ERP ~13ms 便宜）；副本可作为快速叶价值输入。失败返回 (None, None)。
        """
        try:
            summary, dup = planning.simulate_turn_combat(
                self.game, self.hero, keep_state=True)
        except Exception:  # noqa: BLE001
            return None, None
        if dup is None:
            return summary, None
        try:
            model = EngineForwardModel(
                game=dup, hero_card_id=self.hero_card_id,
                total_players=self.total_players,
                hero_index_hint=self.hero_index_hint, _hero=None)
            # 触发一次 hero 解析；英雄可能已战死（仍可读 rank/utility）
            _ = model.hero
            return summary, model
        except Exception:  # noqa: BLE001
            return summary, None


    # ── RNG（chance node 用；Phase 1 K=1 不强制） ──
    def rng_state(self) -> Dict[str, Any]:
        return planning.rng_get_state(self.game.rng)

    def set_rng_state(self, state: Dict[str, Any]) -> None:
        planning.rng_set_state(self.game.rng, state)

    def fork_rng(self, seed: Optional[int] = None) -> None:
        """用 fork 出的 RNG 替换当前游戏 RNG（不扰动原对局之外的对象）。"""
        self.game.rng = planning.rng_fork(self.game.rng, seed=seed)
