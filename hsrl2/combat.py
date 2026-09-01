"""战斗调度器 — v2 核心正确性交付。

修复的旧引擎 P0 缺陷（编号对应 docs/REFACTOR_PLAN.md §4）:
  C1 风怒连续攻击（两次之间不插入对方攻击）
  C2 一方攻击者耗尽→跳过该方继续，仅在"一方无存活随从"或"双方均无法攻击"时结束
  C3 双向伤害同时结算；Venomous 存活判定在双向伤害之后
  C4 AFTER_ATTACK 在伤害与死亡结算之后广播
  C5 顺劈与主目标同窗口结算（宣告时锁定实体引用）
  C6 复生: 原位、1 血、保留 buff/金色/关键词（除复生本身）；亡语先、复生后
  C7 剧毒需 actual_damage>0；圣盾抵消不触发
  C9 0 攻随从跳过
  C10 多嘲讽随机 / 先攻=多者、平随机 / SoC 先于先攻判定
  C12 SoC 顺序: 饰品 → 任务奖励 → 随从 → 英雄技能
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING

import hsrl2.constants as C
from hsrl2.minion import Minion
from hsrl2.queue import CombatLoopError
from hsrl2.tags import GameTag, Zone

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero


@dataclass
class CombatResult:
    winner: Optional["Hero"]        # None = 平局
    loser: Optional["Hero"]
    damage_dealt: int = 0           # 对败方造成的原始伤害
    capped_damage: int = 0          # 应用上限后的伤害
    attacker_first: Optional["Hero"] = None
    rounds: int = 0


def execute_immediate_attack(game: "Game", attacker: Minion,
                             defender: Minion) -> None:
    """立即执行一次攻击（非轮转调度——"attacks it first / attacks
    immediately" 家族）。

    用于: Jailbird Juggernaut Rally 召唤 Golem 先攻目标、招募期
    Fishbait 攻击之外的战内强制攻击。完整走单次攻击语义（Rally/
    同时双向伤害/顺劈/剧毒/AFTER_ATTACK——与轮转攻击同一条代码路径）。
    """
    if attacker.controller is None or defender.controller is None:
        raise ValueError("execute_immediate_attack: both combatants need "
                         "controllers")
    sched = CombatScheduler(game, attacker.controller, defender.controller)
    sched._execute_attack(attacker, defender)


class CombatScheduler:
    def __init__(self, game: "Game", hero_a: "Hero", hero_b: "Hero"):
        self.game = game
        self.a = hero_a
        self.b = hero_b
        self.rounds = 0

    # ── 入口 ──

    def run(self) -> CombatResult:
        game, a, b = self.game, self.a, self.b
        for m in a.board + b.board:
            m.reset_for_combat()          # Venomous 每场重置 (C8/S14)
        # 当前战斗对暴露（SoC "all other minions" 含敌方的卡——
        # Boom-in-a-Box 类——经 game._active_combat 定位对手）
        game._active_combat = (a, b)
        try:
            self._start_of_combat_phase()     # C12: SoC 先于先攻判定
            attacker_side, defender_side = self._determine_first()
            result = self._attack_loop(attacker_side, defender_side)
            result.attacker_first = attacker_side
            return result
        finally:
            game._active_combat = None

    # ── SoC 阶段 (C12: 饰品→任务奖励→随从→英雄技能) ──

    def _start_of_combat_phase(self) -> None:
        game = self.game
        for hero in (self.a, self.b):
            # 1. 饰品
            for trinket in hero.trinkets:
                game.run_script_hook(trinket, "start_of_combat")
            # 2. 任务奖励
            for reward in getattr(hero, "quest_rewards", []):
                game.run_script_hook(reward, "start_of_combat")
            # 3. 随从（棋盘左→右; 执行期间死亡者跳过）
            for m in list(hero.board):
                if m.dead:
                    continue
                game.run_script_hook(m, "start_of_combat")
                game.check_deaths()
            # 3b. 手牌 SoC——仅声明 hand_soc=True 的脚本触发
            #     （Flighty Scout "If this minion is in your hand" 类;
            #     普通 SoC 随从在手牌不触发）
            from hsrl2.minion import Minion as _Minion
            for card in list(hero.hand):
                if not isinstance(card, _Minion):
                    continue
                script = card.scripts
                if script is not None and getattr(script, "hand_soc", False):
                    game.run_script_hook(card, "start_of_combat",
                                         ctx={"in_hand": True})
            # 4. 英雄技能（监听 START_OF_COMBAT 事件的被动）
            game.events.fire(game, "start_of_combat", hero=hero)
            game.check_deaths()

    # ── 先攻判定 (C10) ──

    def _determine_first(self) -> tuple:
        na, nb = len(self.a.living_minions()), len(self.b.living_minions())
        if na > nb:
            return self.a, self.b
        if nb > na:
            return self.b, self.a
        return (self.a, self.b) if self.game.rng.random() < 0.5 else (self.b, self.a)

    # ── 攻击循环 (C1/C2/C9) ──
    #
    # 真实规则模型（游标轮转）:
    #   - 双方交替攻击；每方的攻击顺序为左→右，一轮走完后回到最左
    #     （随从可多次攻击 — 修复 v1 "每场一次" 的重大错误）
    #   - 风怒随从轮到时**连续攻击两次** (C1)
    #   - 0 攻随从被跳过，不占用攻击轮 (C9)
    #   - 一方无存活随从 → 结束；双方均无可用攻击者 → 平局 (C2)

    def _attack_loop(self, attacker_side, defender_side) -> CombatResult:
        cursor = {id(self.a): 0, id(self.b): 0}
        consecutive_stalls = 0

        def next_attacker(side):
            board = [m for m in side.board if not m.dead]
            n = len(board)
            if n == 0:
                return None
            start = cursor[id(side)] % n
            for offset in range(n):
                m = board[(start + offset) % n]
                if m.can_attack():
                    return m
            return None

        while True:
            self.rounds += 1
            if self.rounds > C.COMBAT_MAX_ATTACK_ROUNDS:
                raise CombatLoopError("combat exceeded max attack rounds")

            # 终局: 一方无存活随从
            if not attacker_side.living_minions() or not defender_side.living_minions():
                break

            attacker = next_attacker(attacker_side)
            if attacker is None:
                # C2: 该方无可用攻击者（全 0 攻）→ 跳过轮转给对方；
                # 对方也无法攻击 → 僵局平局
                if next_attacker(defender_side) is None:
                    break
                attacker_side, defender_side = defender_side, attacker_side
                continue

            defender = self._choose_target(defender_side)
            if defender is None:
                # 攻击方无有效目标（对方全部潜行）→ 跳过攻击轮转；
                # 连续两轮无目标（双方互瞪）→ 僵局平局
                consecutive_stalls += 1
                if consecutive_stalls >= 2:
                    break
                attacker_side, defender_side = defender_side, attacker_side
                continue
            consecutive_stalls = 0

            # 推进游标到攻击者的下一位
            board = [m for m in attacker_side.board if not m.dead]
            try:
                idx = board.index(attacker)
                cursor[id(attacker_side)] = idx + 1
            except ValueError:
                pass

            self._execute_attack(attacker, defender)

            # C1: 风怒 → 同一随从立即连续再攻击一次
            if attacker.windfury and not attacker.dead and attacker.can_attack():
                defender2 = self._choose_target(defender_side)
                if defender2 is not None:
                    self._execute_attack(attacker, defender2)

            attacker_side, defender_side = defender_side, attacker_side

        winner = None
        loser = None
        alive_a = bool(self.a.living_minions())
        alive_b = bool(self.b.living_minions())
        if alive_a and not alive_b:
            winner, loser = self.a, self.b
        elif alive_b and not alive_a:
            winner, loser = self.b, self.a
        return CombatResult(winner=winner, loser=loser,
                            attacker_first=None, rounds=self.rounds)

    def _choose_target(self, side: "Hero") -> Optional[Minion]:
        """目标选择 (RULES §4.4): 随机，嘲讽强制优先，潜行不可被攻击。"""
        living = [m for m in side.living_minions() if not m.has(GameTag.STEALTH)]
        if not living:
            return None
        taunts = [m for m in living if m.taunt]
        pool = taunts if taunts else living    # 嘲讽强制，多嘲讽随机 (C10)
        return self.game.rng.choice(pool, label="attack_target")

    # ── 单次攻击结算 (C3/C4/C5/C7) ──

    def _execute_attack(self, attacker: Minion, defender: Minion) -> None:
        game = self.game
        game.events.fire(game, "before_attack", attacker=attacker, defender=defender)

        # Rally: 攻击宣告时、伤害前 (RULES §6.16)
        rally = attacker.call_script("rally", ctx={"target": defender})
        game.run_actions(rally)

        # ── 同时双向伤害 (C3): 宣告时快照攻击力，先判定再统一施加 ──
        atk_power = attacker.atk
        def_hp_before = defender.health          # 受击前血量（超额伤害语义）
        def_power = defender.atk if not defender.dead else 0

        # 剧毒/猛毒资格预判（需实际造成伤害 C7）
        attacker_deals = atk_power > 0
        defender_counters = def_power > 0
        # 攻击时免疫 (Warpwing BG24_004 / Invulnerability Dark Gift):
        # 攻击者不承受反击伤害
        attacker_immune = attacker.has(GameTag.IMMUNE_WHILE_ATTACKING)

        actual_to_defender = defender.take_damage(atk_power, source=attacker) \
            if attacker_deals else 0
        actual_to_attacker = attacker.take_damage(def_power, source=defender) \
            if (defender_counters and not attacker_immune) else 0
        # damage 事件（"Whenever this takes damage" 触发器——与 Hit Action
        # 同口径，攻击主/反击路径全覆盖）
        if actual_to_defender:
            game.events.fire(game, "damage", minion=defender,
                             amount=actual_to_defender, source=attacker)
        if actual_to_attacker:
            game.events.fire(game, "damage", minion=attacker,
                             amount=actual_to_attacker, source=defender)

        # 顺劈 (C5): 攻击者效果，仅攻击方向；主目标相邻实体（宣告时锁定）
        if attacker.cleave and not attacker.dead:
            pos = defender.zone_position
            board = defender.controller.board if defender.controller else []
            adjacent = [m for m in board
                        if not m.dead and abs(m.zone_position - pos) == 1]
            for adj in adjacent:
                adj_actual = adj.take_damage(atk_power, source=attacker)
                if adj_actual:
                    game.events.fire(game, "damage", minion=adj,
                                     amount=adj_actual, source=attacker)

        # 死亡波次（亡语→复生, C6）
        game.check_deaths()

        # Venomous 判定 (C3/C8): 双向伤害结算后，攻击者仍存活才触发
        if (actual_to_defender > 0 and attacker.venomous_active
                and not attacker.dead and not defender.dead):
            defender.set(GameTag.DEAD, True)
            defender.set(GameTag.KILLER, attacker)
            attacker.set(GameTag.VENOMOUS_CONSUMED, True)
        if (actual_to_attacker > 0 and defender.venomous_active
                and not defender.dead and not attacker.dead):
            attacker.set(GameTag.DEAD, True)
            attacker.set(GameTag.KILLER, defender)
            defender.set(GameTag.VENOMOUS_CONSUMED, True)
        # Poisonous: 无限量、无存活要求，只需实际伤害
        if actual_to_defender > 0 and attacker.poisonous and not defender.dead:
            defender.set(GameTag.DEAD, True)
            defender.set(GameTag.KILLER, attacker)
        if actual_to_attacker > 0 and defender.poisonous and not attacker.dead:
            attacker.set(GameTag.DEAD, True)
            attacker.set(GameTag.KILLER, defender)

        game.check_deaths()

        # AFTER_ATTACK: 伤害与死亡结算之后 (C4); excess_damage 携带
        # 超额值（Wildfire Elemental "deal excess damage"——仅击杀时>0）
        excess = atk_power - def_hp_before if defender.dead else 0
        game.events.fire(game, "after_attack",
                         attacker=attacker, defender=defender,
                         excess_damage=max(0, excess),
                         defender_hp_before=def_hp_before)
        game.events.fire(game, "after_attacked", defender=defender)
