"""Game — 回合状态机 + 招募经济 + 战斗编排 + 伤害/幽灵。

修复目标（REFACTOR_PLAN §5）:
  P1 池 draw/return 配对（刷新回池、出售回池、淘汰回池、Discover 占池）
  P3 金币: 基础收入覆盖式重置、回合内收入叠加、持有上限 99
  P4 升级费下限 0
  P5 冻结: 整馆冻结、手动刷新保留、无发明 buff
  P6 满手牌生成卡等待
  P7 Spellcraft 打出立即给法术（脚本钩子 on_play 处理）
  C6 死亡处理: 亡语先、复生后（保留 buff/金色，1 血，原位）
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

import hsrl2.constants as C
from hsrl2 import darkgifts as DG
from hsrl2 import matchmaking
from hsrl2.combat import CombatScheduler
from hsrl2.entity import Buff, Entity
from hsrl2.events import EventBus, Listener
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.pools import MinionPool, SpellPool
from hsrl2.queue import Action, ActionQueue
from hsrl2.rng import GameRNG
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

if TYPE_CHECKING:
    from hsrl2.db import CardDB


# PERSIST tag 已入册 tags.py（1045）——Tarecgosa's Blessing Dark Gift
PERSIST_TAG = GameTag.PERSIST_COMBAT_CHANGES

# PERSIST 随从战斗后覆写保留的关键词集合（RULES §3.5 例外: Dark Gift 永久保留）
_PERSIST_KEYWORD_TAGS = (
    GameTag.TAUNT,
    GameTag.DIVINE_SHIELD,
    GameTag.WINDFURY,
    GameTag.POISONOUS,
    GameTag.VENOMOUS,
    GameTag.REBORN,
    GameTag.STEALTH,
    GameTag.CLEAVE,
)


def _frozen_clone(m: Minion) -> Minion:
    """幽灵快照克隆 (RULES §4.8: 幽灵阵容不成长不变化)。

    copy.copy + 独立 tags/buffs:
      - tags 逐值独立（实体引用类值如 KILLER 直接丢弃，避免 deepcopy
        拉出整张对象图）
      - _buffs 为新列表、新 Buff 对象（copy.copy 共享列表会污染原实体）
      - PERSIST_TAG 一并剥离 — 持久化语义不适用于冻结副本，
        否则幽灵战斗的变化会写入记录
    """
    clone = copy.copy(m)
    clone.uuid = uuid.uuid4().hex[:12]
    clone.tags = {}
    for tag, value in m.tags.items():
        if isinstance(value, Entity):
            continue
        clone.tags[tag] = copy.deepcopy(value)
    clone._buffs = [copy.copy(b) for b in m._buffs]
    clone.controller = None
    clone.game = m.game
    clone.clear(PERSIST_TAG)
    return clone


class GameStateError(RuntimeError):
    """非法操作（引擎契约违反）。"""


class PendingChoice:
    """发现/选择待决。队列化 — 旧引擎单槽覆盖 bug 的修复。"""

    def __init__(self, owner: Hero, options: Sequence[Any], kind: str,
                 resolve_callback=None):
        self.owner = owner
        self.options = list(options)
        self.kind = kind            # "discover_minion" / "dark_gift" / ...
        self.resolve_callback = resolve_callback

    def choose(self, index: int) -> None:
        if not 0 <= index < len(self.options):
            raise GameStateError(f"choice index {index} out of range")
        pick = self.options[index]
        if self.resolve_callback:
            self.resolve_callback(pick)
        # 发现类选择完成事件（Hooktusk "After you Discover a card" 等）
        if self.kind.startswith("discover") or self.kind == "triple_reward" \
                or self.kind == "dark_gift":
            if self.owner.game is not None:
                self.owner.game.events.fire(
                    self.owner.game, "card_discovered",
                    kind=self.kind, hero=self.owner,
                    option=pick if isinstance(pick, str) else None)


class Game:
    def __init__(self, heroes: List[Hero], db: "CardDB", *,
                 seed: int | None = None):
        self.heroes = heroes
        self.db = db
        self.rng = GameRNG(seed)
        self.turn = 0
        self.in_combat = False
        self.events = EventBus()
        self.queue = ActionQueue()
        self.minion_pool = MinionPool(db, self.rng)
        self.spell_pool = SpellPool(db, self.rng)
        self.pending_choices: List[PendingChoice] = []
        self.choice_policy: Optional[str] = "first"   # 自动策略: first/random
        self.combat_summon_log: List[Minion] = []
        self.combat_death_log: List[Minion] = []
        # 延迟到下回合的动作 / 满手牌排队等待的生成卡 (P6)
        self.deferred_actions: List[tuple] = []       # (hero, Action)
        self.pending_hand_queue: List[tuple] = []     # (hero, Entity)
        # 磁力栈: 宿主 uuid → 吸附的磁力随从 card_id 列表（亡语栈叠用）
        self._magnetic_stack: dict = {}
        self.finished: bool = False
        self._last_combat_results = {}
        # 配对簿记 / 幽灵记录 / 战斗记忆（幽灵对手记 None）
        self._opponent_history: Dict[Hero, List[Optional[Hero]]] = {}
        self.ghost_records: List[dict] = []
        self.combat_memory: Dict[Hero, List[Optional[Hero]]] = {}
        # ── S14: Dark Gifts / Lockbox / Fodder 引擎级状态 ──
        # hero → {"uses_left": 3, "used_this_turn": False}（B1;
        # used_this_turn 在 _begin_recruit_for 重置）
        self.dark_gift_state: Dict[Hero, dict] = {}
        # (gift_id, minion_uuid, turn, "APPLIED"|"DEFERRED") — DEFERRED
        # gift 不静默: 有日志可审计
        self.dark_gift_audit_log: List[Tuple[str, str, int, str]] = []
        # Persisting Horror: 复生时满血复活的实体（一次性，复活后移除）
        self._reborn_full_uuids: set = set()
        # Gilding: 金色但无三连奖励（三连奖励系统接线后消费; TODO）
        self._gilded_no_reward_uuids: set = set()
        # Sunken Persistence: Spellcraft 永久的随从 uuid。脚本层契约:
        # 由随从生成的 Spellcraft 法术实体须设 spellcraft_source_uuid
        # 属性 = 该随从 uuid，回合结束丢弃时据此豁免
        self._permanent_spellcraft_uuids: set = set()
        # Demonology: hero → 待附加 Fodder 的刷新次数
        # Fodder 协议 v2: Dict[Hero, (剩余刷新次数, 每次附加枚数)]
        self._fodder_refresh_pending: Dict[Hero, tuple] = {}
        # 永久化拦截窗口（Lava Lurker——spell_resolving 事件中由脚本设置，
        # add_buff 消费后清除）
        self._permanence_pending: Optional[str] = None
        for h in heroes:
            h.game = self

    # ══════════════════ 招募回合流程 ══════════════════

    def start_game(self) -> None:
        self.turn = 1
        # 英雄被动技能接线（hero_passives 批协议: REGISTRY[power_id]
        # 的 on_bind(hero, game) 注册整局监听器/开局效果——The Curator
        # Amalgam / Patchwerk 血量 / Edwin 计数等）
        from hsrl2.scripts import REGISTRY
        for h in self.heroes:
            power_def = self.hero_power_def(h)
            if power_def is None:
                continue
            script = REGISTRY.get(power_def.id)
            if script is not None and hasattr(script, "on_bind"):
                script.on_bind(h, self)
        for h in self.heroes:
            self._begin_recruit_for(h)

    def _begin_recruit_for(self, hero: Hero) -> None:
        """回合开始的全部副作用，按官方顺序。"""
        # 金币: 基础收入覆盖式重置（不储蓄），回合内收入叠加 (P3)
        hero.gold = C.gold_base_income(self.turn, hero.income_cap)
        # 延迟动作执行（上回合 ScheduleNextTurn 等）——在金币重置**之后**，
        # 使 GainGold 类延迟效果叠加在基础收入之上（官方"下回合获得 X 金"）
        due = [(h, a) for h, a in self.deferred_actions if h is hero or h is None]
        self.deferred_actions = [(h, a) for h, a in self.deferred_actions
                                 if not (h is hero or h is None)]
        for _, action in due:
            self.queue.enqueue(action)
        if due:
            self.queue.resolve(self)
        # 回合计数清零
        hero.clear(GameTag.GOLD_SPENT_THIS_TURN)
        hero.clear(GameTag.CARDS_PLAYED_THIS_TURN)
        hero.clear(GameTag.TAVERN_SPELLS_CAST_THIS_TURN)
        # 升级费递减 (P4): 每回合未升级 -1，下限 0；第 1 回合不减
        if self.turn > 1:
            hero.set(GameTag.UPGRADE_COST,
                     max(C.UPGRADE_COST_FLOOR, hero.upgrade_cost - C.UPGRADE_DECAY_PER_TURN))
        # Activate 每回合重置
        for m in hero.board:
            m.clear(GameTag.ACTIVATE_USED_THIS_TURN)
        hero.clear(GameTag.HERO_POWER_USED_THIS_TURN)
        # Dark Gift 每回合 1 次（S14; 官方 36.2 dev post）
        dg_state = self.dark_gift_state.get(hero)
        if dg_state is not None:
            dg_state["used_this_turn"] = False
        # SoT 效果: 饰品 → 任务奖励 → 随从
        for trinket in hero.trinkets:
            self.run_script_hook(trinket, "start_of_turn")
        for reward in getattr(hero, "quest_rewards", []):
            self.run_script_hook(reward, "start_of_turn")
        for m in list(hero.board):
            self.run_script_hook(m, "start_of_turn")
        # 手牌实体 SoT 钩子（B4 — Lockbox 倒计时等依赖）。
        # AMBIGUOUS: 手牌 SoT 相对棋盘 SoT 的官方顺序未公布，取"棋盘后"。
        for card in list(hero.hand):
            self.run_script_hook(card, "start_of_turn")
            # Lockbox 倒计时 (BG36_520t): "In 5 turns, break this open"
            # （初始 5 = CardDef.num(0)，create_spell 时入 tag）
            left = card.get(GameTag.LOCKBOX_TURNS_LEFT, 0)
            if left > 0:
                if left - 1 <= 0:
                    self._open_lockbox(hero, card)
                else:
                    card.set(GameTag.LOCKBOX_TURNS_LEFT, left - 1)
        self.events.fire(self, "turn_start", turn=self.turn, hero=hero)
        # Spellcraft 法术生成（RULES §6.13 每回合开始给予——
        # hsrl2/spellcraft.py，当前为骨架: 无 Spellcraft 脚本卡时 no-op）
        from hsrl2.spellcraft import generate_for_hero
        generate_for_hero(hero, self)
        # 满手牌排队的生成卡入队尝试 (P6: 等待不销毁)
        still_waiting = []
        for h, entity in self.pending_hand_queue:
            if h is hero and not h.hand_full():
                if h.add_to_hand(entity):
                    if isinstance(entity, Minion):
                        self.check_for_triple(h, entity)
                else:
                    still_waiting.append((h, entity))
            else:
                still_waiting.append((h, entity))
        self.pending_hand_queue = still_waiting
        # 刷新酒馆（冻结保留）
        self.refresh_tavern(hero, auto=True)

    # ── 延迟动作 / 手牌等待队列 ──

    def defer_until_next_turn(self, hero: Hero, action: Action) -> None:
        """效果推迟到 hero 的下一个招募阶段开始执行。"""
        self.deferred_actions.append((hero, action))

    def pending_hand_add(self, hero: Hero, entity: Entity) -> bool:
        """生成卡进手牌；满手牌时排队等待而非销毁 (RULES §3.3)。

        随从入手后自动检查三连（获取/发现/Dark Gift 全路径的统一
        接线点——对抗审查 BUG-1 修复）。
        返回 True=已入手, False=已进入等待队列。
        """
        if hero.add_to_hand(entity):
            if isinstance(entity, Minion):
                self.check_for_triple(hero, entity)
            return True
        self.pending_hand_queue.append((hero, entity))
        return False

    # ── 酒馆刷新 (P1/P5) ──

    def refresh_tavern(self, hero: Hero, *, auto: bool = False,
                       free: bool = False, spells_only: bool = False) -> None:
        """刷新酒馆。auto=True 为回合开始的自动刷新。

        规则:
          - 冻结整馆保留（随从+法术），手动刷新同样保留 (P5)
          - 未冻结的旧内容**回池** (P1 — 旧引擎直接丢弃导致池泄漏)
          - 消耗免费刷新次数优先于金币
          - spells_only=True: 只抽法术（Saloon's Finest "Refresh the
            Tavern with Tavern spells"——馆内展示全部为法术）
        """
        if not auto and hero.get(GameTag.TURN_SKIPPED, False):
            return
        if not auto:
            free_remaining = hero.get(GameTag.FREE_REFRESH_REMAINING, 0)
            health_refreshes = hero.get(GameTag.HEALTH_REFRESHES_LEFT, 0)
            if free_remaining > 0:
                hero.set(GameTag.FREE_REFRESH_REMAINING, free_remaining - 1)
            elif health_refreshes > 0 and \
                    hero.health + hero.armor > C.REFRESH_COST:
                # Malchezaar: "Two Refreshes each turn cost Health instead
                # of Gold"——以 1 点生命支付（护甲先扣; 不足以支付时
                # 回落金币路径——与购买侧生存守卫一致）
                hero.set(GameTag.HEALTH_REFRESHES_LEFT, health_refreshes - 1)
                hero.take_damage(C.REFRESH_COST)
            elif not free:
                # 刷新费覆盖（Millhouse "Refreshes cost 2 Gold"）
                self.spend_gold(
                    hero, hero.get(GameTag.REFRESH_COST_OVERRIDE,
                                   C.REFRESH_COST))

        keep: List[Entity] = []
        if hero.frozen_tavern:
            keep = list(hero.tavern)
            hero.clear(GameTag.FROZEN)     # 冻结只保留一轮刷新
        # 旧内容回池 (P1)
        for entity in hero.tavern:
            if entity in keep:
                continue
            if isinstance(entity, Minion):
                self.minion_pool.release(entity.card_id, 1)
            elif isinstance(entity, Spell):
                self.spell_pool.release(entity.card_id)

        count = max(0, C.TAVERN_OFFERS.get(hero.tavern_tier, 6)
                    + hero.get(GameTag.TAVERN_OFFER_MOD, 0) - len(keep))
        # 冻结保留的法术同样占展示位（对抗审查 BUG-6: 冻结含法术的馆
        # 连续刷新曾导致法术无限膨胀——RULES §6.17 冻结同时影响随从与法术）
        kept_spells = sum(1 for e in keep if not isinstance(e, Minion))
        hero.tavern = list(keep)
        if not spells_only:
            for card_id in self.minion_pool.draw_tavern(hero.tavern_tier, count):
                m = self.create_minion(card_id, controller=hero)
                m.zone = Zone.TAVERN
                # 持久酒馆 Buff 应用（新入馆随从; 冻结保留项不重复应用）
                from hsrl2.actions.tavern_buff import BuffCurrentTavern  # noqa: F401
                for tb in getattr(hero, "tavern_buffs", []):
                    if tb.matches(self.db.get(card_id)):
                        from hsrl2.entity import Buff as BuffEnchant
                        m.add_buff(BuffEnchant(atk=tb.atk, health=tb.health,
                                               source_id=tb.source_id))
                hero.tavern.append(m)
        if spells_only:
            spell_count = count
        else:
            spell_count = max(0, C.TAVERN_SPELLS_PER_REFRESH - kept_spells)
        for card_id in self.spell_pool.draw_tavern(hero.tavern_tier, spell_count):
            s = self.create_spell(card_id, controller=hero)
            s.zone = Zone.TAVERN
            hero.tavern.append(s)
        # Demonology Dark Gift / Trapped Clapper: "Add N Fodders to
        # your next K Refreshes" — 协议 v2: Dict[Hero, (剩余刷新次数,
        # 每次附加枚数)]。每次刷新附加 per_refresh 枚 Demon Fodder
        # token（BG35_150t，非池卡不占池; 其 "feeds itself" 行为由
        # 脚本层实现）
        pending_entry = self._fodder_refresh_pending.get(hero)
        if pending_entry:
            refreshes_left, per_refresh = pending_entry
            for _ in range(per_refresh):
                fodder = self.create_minion(C.FODDER_CARD_ID, controller=hero)
                fodder.zone = Zone.TAVERN
                hero.tavern.append(fodder)
            if refreshes_left <= 1:
                del self._fodder_refresh_pending[hero]
            else:
                self._fodder_refresh_pending[hero] = \
                    (refreshes_left - 1, per_refresh)
        self.events.fire(self, "tavern_refresh", hero=hero)

    # ── 买/卖/打出 (P1/P6/P7) ──

    def buy_from_tavern(self, hero: Hero, entity: Entity) -> bool:
        if entity not in hero.tavern:
            return False
        if hero.hand_full():
            return False
        if hero.get(GameTag.TURN_SKIPPED, False):
            return False
        cost = entity.get(GameTag.COST, C.MINION_BUY_COST)
        # 随从购买价平价覆盖（Sindragosa/Millhouse "Minions cost (2)"
        # ——作用于随从不作用于法术）; 免费购买次数优先于覆盖价
        # （Aranna "the first minion you buy each turn is free"）
        if isinstance(entity, Minion):
            override = hero.get(GameTag.TAVERN_MINION_COST_OVERRIDE, 0)
            if override:
                cost = override
            if hero.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0) > 0:
                hero.set(GameTag.FREE_MINION_BUYS_THIS_TURN,
                         hero.get(GameTag.FREE_MINION_BUYS_THIS_TURN) - 1)
                cost = 0
        # 酒馆法术折扣（Ominous Seer "下一个酒馆法术便宜 1 金"）
        d = self.db.get(entity.card_id)
        if d is not None and d.is_pool_spell:
            discount = hero.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0)
            if discount > 0:
                cost = max(0, cost - discount)
                hero.set(GameTag.NEXT_SPELL_COST_REDUCTION, 0)
        # 健康购买（Hasty Excavation "costs Health to buy instead of Gold"）
        # 官方语义: 以生命支付（护甲先扣），生命不足以支付时不可购买
        paid_with_health = False
        if d is not None and d.is_pool_spell:
            discount = hero.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0)
            if discount > 0:
                cost = max(0, cost - discount)
                hero.set(GameTag.NEXT_SPELL_COST_REDUCTION, 0)
        # 健康购买（Hasty Excavation "costs Health to buy instead of Gold"）
        # 官方语义: 以生命支付（护甲先扣），生命不足以支付时不可购买
        paid_with_health = False
        if d is not None and d.health_cost:
            if hero.health + hero.armor > cost:
                hero.take_damage(cost)
                paid_with_health = True
            else:
                return False
        if not paid_with_health:
            if hero.gold < cost:
                return False
            self.spend_gold(hero, cost)
        hero.tavern.remove(entity)
        # 法术购买事件（Magicfin Mycologist "after you buy a Tavern
        # spell" 等——随从走 minion_bought）
        if isinstance(entity, Spell):
            self.events.fire(self, "spell_bought", spell=entity, hero=hero)
        # 统一走 add_to_hand（on_enter_hand 钩子——Bream Counter/
        # Aureate Laureate 购买路径; unfreeze 批上报缺口 #2）
        hero.add_to_hand(entity)
        if isinstance(entity, Minion):
            self.events.fire(self, "minion_bought", minion=entity)
            self.check_for_triple(hero, entity)   # 三连检查（购买入口）
        return True

    def sell_minion(self, hero: Hero, minion: Minion) -> bool:
        if minion not in hero.board and minion not in hero.hand:
            return False
        # on_sell 效果
        self.run_script_hook(minion, "on_sell")
        value = C.MINION_SELL_VALUE
        sell_override = minion.get(GameTag.SELL_VALUE, 0)
        if sell_override:
            value = sell_override
        hero.gold += value
        self.events.fire(self, "minion_sold", minion=minion)
        # 回池 (P1): 金色 3 份
        if minion in hero.board:
            hero.board.remove(minion)
        if minion in hero.hand:
            hero.hand.remove(minion)
        self.minion_pool.release_minion_entity(minion)
        minion.zone = Zone.REMOVED   # 已回池；不进 graveyard（防淘汰时二次回池）
        self.events.unregister_owner(minion)
        return True

    def play_minion(self, hero: Hero, minion: Minion,
                    position: Optional[int] = None,
                    target: Optional[Entity] = None,
                    magnetic_target: Optional[Minion] = None) -> bool:
        if hero.get(GameTag.TURN_SKIPPED, False):
            return False
        """从手牌打出随从。

        Magnetic (RULES §6.14): 磁力随从可指定 magnetic_target（友方
        机械）吸附而非召唤——属性/关键词并入宿主，亡语效果栈叠保留。

        定向战吼 (RULES §6.10 + wiki [Targeted] 先例): 脚本类声明
        ``needs_target = True`` 时，未提供 target 则产生
        PendingChoice(kind="battlecry_target")，玩家选择后继续打出流程;
        无合法候选 → 战吼落空但随从照常入场（官方: 不可定向的战吼
        上场仍成立）。

        Choose One: 脚本类声明 ``choose_options = [(key, label), ...]``
        时，产生 PendingChoice(kind="choose_one")，选定 key 传入
        ctx={"choose": key} 后触发 on_play 钩子。
        """
        # UNPLAYABLE: CardDef.unplayable 权威 + 实体级手牌锁定
        # （Search Through Time "Lock it in your hand until next turn"）
        d = self.db.get(minion.card_id)
        if minion not in hero.hand or (d is not None and d.unplayable) \
                or minion.has(GameTag.LOCKED_IN_HAND):
            return False
        # 磁力吸附路径（先于满板检查——吸附不占板位）
        if magnetic_target is not None and minion.has(GameTag.MAGNETIC):
            if (magnetic_target.controller is not hero
                    or magnetic_target.dead
                    or magnetic_target.zone != Zone.PLAY
                    or not self._magnetic_valid(minion, magnetic_target)):
                return False
            hero.hand.remove(minion)
            self.attach_magnetic(hero, minion, magnetic_target)
            self.events.fire(self, "card_played", card=minion)
            return True
        if hero.board_full():
            self.events.fire(self, "minion_overflow", minion=minion)
            return False

        script = minion.scripts
        # 官方打出顺序: 随从入场 → (Choose One 选择 / 战吼目标选择) → 结算。
        # 战吼可以以打出随从**自身**为目标（先入场是必要前提）。
        hero.hand.remove(minion)
        hero.set(GameTag.CARDS_PLAYED_THIS_TURN,
                 hero.get(GameTag.CARDS_PLAYED_THIS_TURN, 0) + 1)
        self.summon(hero, minion, position)

        # Choose One 分流（RULES: 打出时二选一）。双效合并: 棋盘
        # CHOOSE_BOTH 光环（Thorned Trailblazer）或实体自带 CHOOSE_BOTH
        # tag（Fandral's Fortune 发现的恒双效卡）时跳过选择直接双效
        both = (any(m.has(GameTag.CHOOSE_BOTH) for m in hero.board)
                or minion.has(GameTag.CHOOSE_BOTH))
        if script is not None and getattr(script, "choose_options", None):
            if both:
                return self._run_play_effects(hero, minion, target=target,
                                              choose="both")
            options = list(script.choose_options)
            self.pending_choices.append(PendingChoice(
                hero, [k for k, _ in options], "choose_one",
                resolve_callback=lambda key: self._run_play_effects(
                    hero, minion, target=target, choose=key)))
            return True

        # 定向战吼分流
        if script is not None and getattr(script, "needs_target", False):
            cand_fn = getattr(script, "target_candidates", None)
            candidates = (list(cand_fn(minion, self))
                          if cand_fn is not None
                          else [m for m in hero.board if not m.dead])
            if target is not None:
                if target not in candidates:
                    # 非法目标: 随从已入场（不可撤回），战吼落空
                    return self._run_play_effects(hero, minion)
            elif candidates:
                self.pending_choices.append(PendingChoice(
                    hero, candidates, "battlecry_target",
                    resolve_callback=lambda pick: self._run_play_effects(
                        hero, minion, target=pick)))
                return True
            # 无候选: 战吼落空，随从已入场
        return self._run_play_effects(hero, minion, target=target)

    def _run_play_effects(self, hero: Hero, minion: Minion,
                          target: Optional[Entity] = None,
                          choose: Optional[str] = None) -> bool:
        """打出后的效果结算: 战吼（金色×2/Brann×2）→ 死亡检查 →
        card_played 广播 → 手牌三连的金色打出时发放三连奖励。"""
        ctx = {}
        if target is not None:
            ctx["target"] = target
        if choose is not None:
            ctx["choose"] = choose
        # 战吼: 金色双倍 (金色卡定义自带数值；触发次数=2)，Brann 叠加
        # （金色 Brann 族 ×3——倍率累加，对抗审查 BUG-7 同族修复）
        extra_bc = sum(2 if m.is_golden else 1
                       for m in hero.board
                       if m.has(GameTag.BATTLECRY_DOUBLER))
        times = 1
        if minion.is_golden:
            times *= 2
        times += extra_bc
        for _ in range(times):
            self.run_script_hook(minion, "battlecry", ctx=ctx or None)
            # 每次战吼触发计数 + 广播（Brann/金色双倍各计一次——
            # 官方 "for each Battlecry you've triggered" 按触发次数计）
            if minion.has(GameTag.BATTLECRY):
                hero.set(GameTag.COUNTER_BATTLECRIES,
                         hero.get(GameTag.COUNTER_BATTLECRIES, 0) + 1)
                self.events.fire(self, "battlecry_trigger", minion=minion)
        self.check_deaths()
        # 本局金色打出计数（Maritime Extortionist / Hooktusk 数据源）——
        # 先于 card_played 广播（监听器读计数须含正在打出的这张）
        if minion.is_golden:
            hero.set(GameTag.GOLDEN_MINIONS_PLAYED,
                     hero.get(GameTag.GOLDEN_MINIONS_PLAYED, 0) + 1)
        # "Whenever you play a card" 类（Dexterity 等）监听源
        self.events.fire(self, "card_played", card=minion)
        # 三连奖励: 手牌合成的金色打出时发放（RULES §10.3）
        if minion.is_golden and minion.has(GameTag.TRIPLE_REWARD_PENDING):
            self._grant_triple_reward(hero, minion)
        # 打出后三连检查（2 手牌 + 打出第 3 张路径——官方时序: 战吼
        # 结算后合成，金色替换场上位置; 对抗审查 BUG-1 接线）
        if not minion.is_golden:
            self.check_for_triple(hero, minion)
        return True

    # ── 三连合成 (RULES §10) ──

    def check_for_triple(self, hero: Hero, acquired: Minion) -> None:
        """一张随从进入手牌/棋盘后检查三连（购买/获取/打出路径统一入口）。

        RULES §10.1: 收集 3 个相同非金色随从 → 自动合成金色版本。
        RULES §10.2: 金色保留三个原始随从的**全部**增益（buff 求并叠加）。
        区域规则:
          - 参与副本 ≥1 在棋盘 → 金色出现在棋盘（最左参与副本的位置），
            奖励立即发放（官方: 场上合成即弹发现窗）
          - 全部在手牌 → 金色入手，打出时发放奖励（TRIPLE_REWARD_PENDING）
        池记账: 3 份基础卡已在购买/获取时扣减，合成不额外占池; 金色出售
        返还 3 份（release_minion_entity 已实现）。

        替代合成（Elemental of Surprise BG26_175 "can triple with any
        Elemental as a substitute"）: 手牌/棋盘存在该卡时，2 张同名
        元素 + 1 张任意元素（替代位）亦可合成——替代副本作为第三份
        参与合并。
        """
        if acquired.is_golden or not isinstance(acquired, Minion):
            return
        d = self.db.get(acquired.card_id)
        if d is None or not d.is_pool_minion:
            return   # token 不三连

        def _combine(base_card_id: str, participants):
            base_def = self.db.get(base_card_id)
            if base_def is None or not base_def.is_pool_minion:
                return
            golden_def = self.db.golden_version(base_def)
            if golden_def is None:
                self.dark_gift_audit_log.append(
                    f"MISSING_GOLDEN_DEF: {base_card_id}")
                return
            golden = self.create_minion(golden_def.id, controller=hero,
                                        golden=True)
            golden.set(GameTag.TRIPLE_BASE_CARD_ID, base_card_id)
            for m in participants:
                for b in m._buffs:
                    golden.add_buff(b)
            board_participants = [m for m in participants if m in hero.board]
            if board_participants:
                pos = min(hero.board.index(m) for m in board_participants)
                for m in participants:
                    if m in hero.board:
                        hero.board.remove(m)
                    if m in hero.hand:
                        hero.hand.remove(m)
                    m.zone = Zone.REMOVED
                self.summon(hero, golden, pos)
                self.events.fire(self, "triple_combined", golden=golden)
                # 奖励替代（Clocksworth "give Tavern Coins instead of
                # Triple Rewards"）: N 张 Tavern Coin 直入手，不弹发现
                coins_n = hero.get(GameTag.TRIPLE_REWARD_COINS, 0)
                if coins_n:
                    self._grant_tavern_coins(hero, coins_n)
                else:
                    self._grant_triple_reward(hero, golden)
            else:
                for m in participants:
                    hero.hand.remove(m)
                    m.zone = Zone.REMOVED
                coins_n = hero.get(GameTag.TRIPLE_REWARD_COINS, 0)
                if coins_n:
                    # 硬币即时到手，无需 pending 奖励标记
                    self._grant_tavern_coins(hero, coins_n)
                else:
                    golden.set(GameTag.TRIPLE_REWARD_PENDING, True)
                # 满手排队（对抗审查: add_to_hand 失败金色静默消失）
                self.pending_hand_add(hero, golden)
                self.events.fire(self, "triple_combined", golden=golden)

        copies = [m for m in hero.hand + hero.board
                  if isinstance(m, Minion)
                  and m.card_id == acquired.card_id and not m.is_golden]
        # 三连阈值（Clocksworth "You only need 2 copies to make minions
        # Golden"——默认 3）
        threshold = hero.get(GameTag.TRIPLE_THRESHOLD, 3)
        if len(copies) >= threshold:
            _combine(acquired.card_id, copies[:threshold])
            return
        # Elemental of Surprise (BG26_175) 替代合成——全池重扫（与到达
        # 顺序无关，对抗审查 BUG-2 修复）。官方依据: wiki patch notes
        # "using Elemental of Surprise to triple Marine Matriarch" /
        # "tripling an All type minion"——175 是百搭第三份，双向合法:
        #   A) 2×BG26_175 + 任意 1 张其他元素（含 ALL）→ 金色 = 175 金
        #   B) 2×同名元素（含 ALL）+ 1×BG26_175 → 金色 = 该元素金
        SUB_CARD = "BG26_175"
        pool_all = [m for m in hero.hand + hero.board
                    if isinstance(m, Minion) and not m.is_golden]
        surprises = [m for m in pool_all if m.card_id == SUB_CARD]
        elem_others = [m for m in pool_all
                       if m.card_id != SUB_CARD
                       and m.race in (Race.ELEMENTAL, Race.ALL)]
        if len(surprises) >= 2 and elem_others:
            _combine(SUB_CARD, surprises[:2] + [elem_others[0]])
            return
        if surprises:
            groups: dict = {}
            for m in elem_others:
                groups.setdefault(m.card_id, []).append(m)
            for cid, group in groups.items():
                if len(group) >= 2:
                    _combine(cid, group[:2] + [surprises[0]])
                    return

    def _grant_tavern_coins(self, hero: Hero, n: int) -> None:
        """Tavern Coin（BG28_810，T1 池法术）×n 入手（满手排队）。"""
        COIN = "BG28_810"
        for _ in range(n):
            coin = self.create_spell(COIN, controller=hero)
            if coin is None:
                self.dark_gift_audit_log.append(
                    f"MISSING_TAVERN_COIN: {COIN}")
                return
            if not hero.add_to_hand(coin):
                self.pending_hand_add(hero, coin)

    def _grant_triple_reward(self, hero: Hero, golden: Minion) -> None:
        """三连奖励: 发现一张 tier+1 的随从（T6 → T6, RULES §10.3）。

        AMBIGUOUS: 发现选项是否受池约束——按官方"发现受共享池限制"
        （RULES §6.18）实现，Discover Action 已池感知。
        """
        golden.clear(GameTag.TRIPLE_REWARD_PENDING)
        base_tier = self.db.get(golden.get(GameTag.TRIPLE_BASE_CARD_ID,
                                           golden.card_id))
        tier = base_tier.tech_level if base_tier else golden.tech_level
        reward_tier = min(tier + 1, C.TAVERN_MAX_TIER)
        from hsrl2.actions.discover import Discover
        self.run_actions(Discover(hero, count=3, max_tier=reward_tier,
                                  min_tier=reward_tier,
                                  kind="triple_reward"))

    def summon(self, hero: Hero, minion: Minion,
               position: Optional[int] = None) -> bool:
        if hero.board_full():
            self.events.fire(self, "minion_overflow", minion=minion)
            return False
        minion.game = self            # 直建实体补挂 game（buff_applied 等）
        minion.controller = hero
        minion.zone = Zone.PLAY
        # 满血入场（含种族光环生命部分——"wherever they are" 对新入场
        # 随从同样生效且不显示受损态; ApplyRaceAura 对已在场者的对称处理
        # 见 actions/racefx.py）
        minion.set(GameTag.HEALTH, minion.max_health)
        if position is None or position > len(hero.board):
            position = len(hero.board)
        hero.board.insert(position, minion)
        self._update_positions(hero)
        self.events.fire(self, "summon", minion=minion)
        self.run_script_hook(minion, "on_summon")
        if self.in_combat:
            self.combat_summon_log.append(minion)
        return True

    def _battlecry_doubled(self, hero: Hero) -> bool:
        """Brann 式光环: 棋盘上存在即生效（离场失效 — 生命周期修复）。"""
        return any(m.has(GameTag.BATTLECRY_DOUBLER) for m in hero.board)

    # ── Magnetic 磁力吸附 (RULES §6.14) ──

    def _magnetic_valid(self, magnetic_minion: Minion,
                        target: Minion) -> bool:
        """吸附目标合法性: 友方机械。

        数据例外（CardDef 文本/数据核实）:
        - Prosthetic Hand (BG_DEEP_015): "Can Magnetize to Mechs
          **or Undead**"
        - Technical Element (BG31_859): Mechs 或 Elementals
        """
        valid = {Race.MECH, Race.ALL}
        mid = magnetic_minion.card_id
        if mid in ("BG_DEEP_015", "BG_DEEP_015_G"):
            valid.add(Race.UNDEAD)
        elif mid in ("BG31_859", "BG31_859_G"):
            valid.add(Race.ELEMENTAL)
        return target.race in valid

    def attach_magnetic(self, hero: Hero, magnetic_minion: Minion,
                        host: Minion) -> None:
        """磁力吸附结算 (RULES §6.14):
          - 攻击/生命相加——按磁力随从**实体当前值**（含 buff——官方
            语义: 吸附的是实体属性而非卡面定义; Wave2 G1 修正）
          - 关键词并入（圣盾/嘲讽/复生/风怒/剧毒/猛毒等）
          - 磁力随从的亡语**栈叠**保留: 宿主死亡时依次触发
          - 宿主仍占一个格子; 磁力随从离场（不进 graveyard、不回池——
            官方: 被磁力的随从在主体被出售时返还池中）
        """
        host.set(GameTag.BASE_ATK,
                 host.get(GameTag.BASE_ATK, 0) + magnetic_minion.atk)
        hp_gain = magnetic_minion.max_health
        host.set(GameTag.BASE_HEALTH, host.get(GameTag.BASE_HEALTH, 0) + hp_gain)
        host.set(GameTag.HEALTH, host.health + hp_gain)
        md = self.db.get(magnetic_minion.card_id)
        for kw, tag in _KEYWORD_TAG_MAP.items():
            if md is not None and kw in md.keywords:
                host.set(tag, True)
        # 亡语栈叠（宿主死亡时按吸附顺序触发）
        self._magnetic_stack.setdefault(host.uuid, []).append(
            magnetic_minion.card_id)
        if md.keywords and "deathrattle" in md.keywords:
            host.set(GameTag.DEATHRATTLE, True)
        magnetic_minion.zone = Zone.REMOVED
        self.events.fire(self, "magnetized", host=host,
                         attached=magnetic_minion)

    def play_spell(self, hero: Hero, spell: Spell,
                   target: Optional[Entity] = None) -> bool:
        if hero.get(GameTag.TURN_SKIPPED, False):
            return False
        """从手牌施放法术。

        定向法术（needs_target=True 声明，与 play_minion 同构）: 未提供
        target → PendingChoice(kind="spell_target")，选定后结算; 无候选
        → 效果落空但法术照常消耗（官方: 无法术目标时法术仍可施放）。

        计数分流（官方语义）:
          - **酒馆法术**（is_pool_spell）才计入 TAVERN_SPELLS_CAST_* 并
            广播 tavern_spell_cast——"每施放一个酒馆法术"类效果的数据源
          - Spellcraft 法术单独广播 spellcraft_cast
          - 血宝石/Dark Gift 等生成法术: 只广播 card_played
        """
        d = self.db.get(spell.card_id)
        if spell not in hero.hand or (d is not None and d.unplayable) \
                or spell.has(GameTag.LOCKED_IN_HAND):
            return False

        script = spell.scripts
        # Choose One 法术（脚本声明 choose_options，与随从同构）。
        # both_options 光环（Thorned Trailblazer "has both effects combined"）
        # 生效时跳过选择、直接以 choose="both" 双效结算
        if script is not None and getattr(script, "choose_options", None):
            both = any(m.has(GameTag.CHOOSE_BOTH) for m in hero.board)
            if both:
                return self._finish_play_spell(hero, spell, target=target,
                                               card_def=d, choose="both")
            options = list(script.choose_options)

            def _choose_finish(key):
                self._finish_play_spell(hero, spell, target=target,
                                        card_def=d, choose=key)
            self.pending_choices.append(PendingChoice(
                hero, [k for k, _ in options], "choose_one",
                resolve_callback=_choose_finish))
            return True
        if script is not None and getattr(script, "needs_target", False) \
                and target is None:
            cand_fn = getattr(script, "target_candidates", None)
            candidates = (list(cand_fn(spell, self))
                          if cand_fn is not None
                          else [m for m in hero.board if not m.dead])
            if candidates:
                self.pending_choices.append(PendingChoice(
                    hero, candidates, "spell_target",
                    resolve_callback=lambda pick: self._finish_play_spell(
                        hero, spell, target=pick, card_def=d)))
                return True
            # 无候选: 落空但照常消耗
        return self._finish_play_spell(hero, spell, target=target, card_def=d)

    def _finish_play_spell(self, hero: Hero, spell: Spell,
                           target: Optional[Entity],
                           card_def=None,
                           choose: Optional[str] = None) -> bool:
        hero.hand.remove(spell)
        if spell.has(GameTag.SPELLCRAFT):
            self.events.fire(self, "spellcraft_cast", spell=spell)
        # Balinda Stonehearth: "Your spells that target friendly minions
        # cast twice"——定向友方随从的法术效果多施（棋盘扫描光环，离场
        # 失效; 金色 Balinda "cast three times" → 额外+2; 计数/事件按
        # 施放次数计——对抗审查 BUG-7: 布尔改倍率累加）
        from hsrl2.minion import Minion as _MinionType
        extra_casts = sum(2 if m.is_golden else 1
                          for m in hero.board
                          if m.has(GameTag.SPELL_DOUBLER))
        double_cast = (
            isinstance(target, _MinionType)
            and target.controller is hero
            and not target.dead
            and extra_casts > 0)
        ctx = {"target": target}
        if choose is not None:
            ctx["choose"] = choose
        casts = 1 + extra_casts if double_cast else 1
        for _ in range(casts):
            if card_def is not None and card_def.is_pool_spell:
                hero.set(GameTag.TAVERN_SPELLS_CAST_THIS_TURN,
                         hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_TURN, 0) + 1)
                hero.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME,
                         hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0) + 1)
            # 永久化拦截窗口（Lava Lurker: spell_resolving 事件中脚本
            # 设置 game._permanence_pending，add_buff 翻转 temporary）
            self.events.fire(self, "spell_resolving", spell=spell,
                             target=target, cast_no=_)
            self.run_script_hook(spell, "on_play", ctx=ctx)
            if getattr(self, "_permanence_pending", None) is not None:
                self._permanence_pending = None
        # tavern_spell_cast 在法术**效果结算后**广播（官方 29.2.2 bugfix
        # 语义: "after you cast" 触发器看到的是已结算场面——Wave3 反馈
        # 的时序修正; 双施时按施放次数广播）
        if card_def is not None and card_def.is_pool_spell:
            for _ in range(casts):
                self.events.fire(self, "tavern_spell_cast", spell=spell)
        spell.zone = Zone.REMOVED
        if card_def is not None and card_def.is_pool_spell:
            self.spell_pool.release(spell.card_id)
        # "Whenever you play a card" 类（Dexterity 等）监听源;
        # target 一并广播（Wave2 G2: "cast a spell on a Mech" 类监听依赖）
        self.events.fire(self, "card_played", card=spell, target=target)
        return True

    # ── 升级 (P4) ──

    def upgrade_tavern(self, hero: Hero) -> bool:
        if hero.get(GameTag.TURN_SKIPPED, False):
            return False
        next_tier = hero.tavern_tier + 1
        if next_tier > C.TAVERN_MAX_TIER + 1:
            return False
        # 升级费加值（Millhouse "costs (1) more"）+ 每回合衰减
        cost = max(C.UPGRADE_COST_FLOOR,
                   hero.upgrade_cost + hero.get(GameTag.UPGRADE_COST_MOD, 0))
        if hero.gold < cost:
            return False
        self.spend_gold(hero, cost)
        hero.set(GameTag.TAVERN_TIER, next_tier)
        hero.set(GameTag.UPGRADE_COST,
                 C.BASE_UPGRADE_COSTS.get(next_tier + 1, 11))
        self.events.fire(self, "tavern_upgraded", hero=hero, tier=next_tier)
        return True

    def freeze_tavern(self, hero: Hero) -> None:
        """整馆冻结 (P5) — 下一次刷新（自动或手动）保留全部内容。"""
        hero.set(GameTag.FROZEN, True)

    # ── 金币 (P3) ──

    def spend_gold(self, hero: Hero, amount: int) -> None:
        if amount <= 0:
            return
        if hero.gold < amount:
            raise GameStateError(f"{hero.name} cannot spend {amount} (has {hero.gold})")
        hero.gold -= amount
        hero.set(GameTag.GOLD_SPENT_THIS_TURN,
                 hero.get(GameTag.GOLD_SPENT_THIS_TURN, 0) + amount)
        self.events.fire(self, "gold_spent", amount=amount, hero=hero)

    # ── S14: Activate ──

    def use_activate(self, hero: Hero, minion: Minion) -> bool:
        if not minion.has(GameTag.ACTIVATE):
            return False
        if minion.has(GameTag.ACTIVATE_USED_THIS_TURN):
            return False
        if minion.controller is not hero or minion not in hero.board:
            return False
        cost = minion.get(GameTag.ACTIVATE_COST, 1)
        if hero.gold < cost:
            return False
        self.spend_gold(hero, cost)
        minion.set(GameTag.ACTIVATE_USED_THIS_TURN, True)
        self.run_script_hook(minion, "activate")
        self.events.fire(self, "activate_used", minion=minion)
        return True

    # ── 英雄技能 (RULES §9.2) ──

    def hero_power_def(self, hero: Hero):
        """hero 当前英雄技能 CardDef。

        静态绑定 = db Tag380 链; 替换协议（Rat King 轮换/Ragnaros
        Sulfuras/Finley 换技能等）优先读 hero._active_power_id 覆写
        （replace_hero_power 维护）。
        """
        replaced = getattr(hero, "_active_power_id", None)
        if replaced is not None:
            d = self.db.get(replaced)
            if d is not None:
                return d
        d = self.db.get(hero.card_id)
        if d is None or d.hero_power_id is None:
            return None
        return self.db.get(d.hero_power_id)

    def replace_hero_power(self, hero: Hero, new_power_id: str) -> None:
        """替换英雄技能（Rat King 每回合轮换 / Sulfuras / Finley）。

        官方语义: 新技能从替换时刻起生效（本回合即可用，除非新技能
        自身限制; uses_per_turn 计数随技能身份切换重置——Rat King 每
        回合换新技能 = 每回合都可用一次）。
        """
        if self.db.get(new_power_id) is None:
            raise GameStateError(
                f"replace_hero_power: unknown power {new_power_id}")
        hero._active_power_id = new_power_id
        hero.clear(GameTag.HERO_POWER_USED_THIS_TURN)

    def hero_power_cost(self, hero: Hero, power_def, script) -> int:
        """技能费（动态覆写点——Elise 递增/Nobundo/Togwaggle/Patches
        "next costs (1) less"）。脚本声明 ``cost_override(hero, game)
        -> int``; 未声明读 power CardDef.cost; 结果下限 0。"""
        override_fn = getattr(script, "cost_override", None)
        if override_fn is not None:
            return max(0, override_fn(hero, self))
        return power_def.cost

    def use_hero_power(self, hero: Hero, target=None) -> bool:
        if hero.get(GameTag.TURN_SKIPPED, False):
            return False
        """使用英雄技能 (RULES §9.2)。

        - 费用: power CardDef.cost，脚本可声明 ``cost_override(hero,
          game) -> int`` 动态覆写（Elise 递增类）
        - 次数: 默认每回合 1 次; ``uses_per_turn = N``; 回合开始清零;
          每局次数（"Once per game" 类）经 ``uses_per_game = N`` +
          hero 级计数 tag 声明式支持
        - 可用性: ``available(hero, game) -> bool``（门槛/冷却/解锁）
        - 目标: ``needs_target`` + ``target_candidates``（单目标）;
          双目标（Vol'jin "Choose 2"）: ``target_count = 2`` 声明 →
          依次两个 PendingChoice，全部选定后结算
        - 替换: replace_hero_power 维护的 _active_power_id 优先
        """
        power_def = self.hero_power_def(hero)
        if power_def is None:
            return False
        from hsrl2.scripts import REGISTRY  # 延迟导入避免循环依赖
        script = REGISTRY.get(power_def.id)
        if script is None:
            return False   # 技能未迁移——不可用（诚实缺省，不静默近似）
        if getattr(script, "passive", False):
            return False
        # 可用性协议: 脚本声明 available(hero, game)——门槛/冷却/
        # Unlocks/上对手无随从等; 默认恒可用
        avail_fn = getattr(script, "available", None)
        if avail_fn is not None and not avail_fn(hero, self):
            return False
        max_uses = getattr(script, "uses_per_turn", 1)
        used = hero.get(GameTag.HERO_POWER_USED_THIS_TURN, 0)
        if used >= max_uses:
            return False
        # 每局次数（"Once/Twice per game"）
        per_game = getattr(script, "uses_per_game", None)
        if per_game is not None:
            used_game = hero.get(GameTag.HERO_POWER_USES_THIS_GAME, 0)
            if used_game >= per_game:
                return False
        cost = self.hero_power_cost(hero, power_def, script)
        if cost and hero.gold < cost:
            return False

        n_targets = getattr(script, "target_count", 1) \
            if getattr(script, "needs_target", False) else 0
        if n_targets <= 0 or target is not None:
            return self._finish_hero_power(hero, power_def, script, target)

        cand_fn = getattr(script, "target_candidates", None)
        candidates = (list(cand_fn(hero, self))
                      if cand_fn is not None
                      else [m for m in hero.board if not m.dead])
        if len(candidates) < n_targets:
            return False   # 候选不足不可用（金币未扣）

        def _chain(picked, remaining):
            """依次收集 n_targets 个目标（每个选定后重估候选——
            第一个目标死亡/离场时自动从后续候选剔除）。"""
            if remaining <= 0:
                self._finish_hero_power(
                    hero, power_def, script,
                    picked[0] if n_targets == 1 else picked)
                return
            fresh = [c for c in candidates if c not in picked]
            if len(fresh) < remaining:
                # 候选枯竭（前序选择致离场）: 已选目标照常结算，
                # 缺位目标为 None（脚本自决落空）
                picks = picked + [None] * remaining
                self._finish_hero_power(
                    hero, power_def, script,
                    picks[0] if n_targets == 1 else picks)
                return
            self.pending_choices.append(PendingChoice(
                hero, fresh, "hero_power_target",
                resolve_callback=lambda pick, p=picked, r=remaining:
                    _chain(p + [pick], r - 1)))

        _chain([], n_targets)
        return True

    def _finish_hero_power(self, hero: Hero, power_def, script,
                           target=None) -> bool:
        cost = self.hero_power_cost(hero, power_def, script)
        # 定向技能目标选择挂起期间金币可能被花光（自动化建模时序——
        # 官方 UI 中选择即时完成无挂起窗口）。resolve 时复查，不足则
        # 该次使用作废（不扣费、不计数、无效果）——官方不允许负金币。
        if cost and hero.gold < cost:
            return False
        if cost:
            self.spend_gold(hero, cost)
        hero.set(GameTag.HERO_POWER_USED_THIS_TURN,
                 hero.get(GameTag.HERO_POWER_USED_THIS_TURN, 0) + 1)
        # 每局次数记账（uses_per_game 声明的技能）
        if getattr(script, "uses_per_game", None) is not None:
            hero.set(GameTag.HERO_POWER_USES_THIS_GAME,
                     hero.get(GameTag.HERO_POWER_USES_THIS_GAME, 0) + 1)
        result = script.hero_power(hero, self, {"target": target}) \
            if hasattr(script, "hero_power") else None
        self.run_actions(result)
        self.events.fire(self, "hero_power_used", hero=hero,
                         power_id=power_def.id)
        return True

    # ══════════════════ S14: Dark Gifts ══════════════════

    def use_dark_gift(self, hero: Hero) -> bool:
        if hero.get(GameTag.TURN_SKIPPED, False):
            return False
        """S14 Dark Gift 使用（官方 36.2 dev post）。

        - 第 3 回合起可用、每次 3 金、每回合 1 次、每局 3 次
          （constants: DARK_GIFT_*）
        - 条件不满足返回 False（玩家操作合法性，不抛异常）
        - 合法但候选耗尽 → 消耗金币与次数后无提供（官方池耗尽行为），
          返回 True 且不产生 PendingChoice
        """
        state = self.dark_gift_state.setdefault(
            hero, {"uses_left": C.DARK_GIFT_USES_PER_GAME,
                   "used_this_turn": False})
        if self.turn < C.DARK_GIFT_START_TURN:
            return False
        if state["uses_left"] <= 0 or state["used_this_turn"]:
            return False
        if hero.gold < C.DARK_GIFT_COST:
            return False
        self.spend_gold(hero, C.DARK_GIFT_COST)
        state["uses_left"] -= 1
        state["used_this_turn"] = True

        candidates = DG.eligible_minions(self.db, self.minion_pool,
                                         hero, self.turn)
        if not candidates:
            return True     # 池耗尽: 无提供（官方效果落空行为）
        trio = self._draw_gift_trio(hero, candidates)
        options = self._pair_gifts(hero, trio, candidates)
        if not options:
            return True     # 极端池状态无法配对——同上落空

        def resolve(pick: Tuple[str, str]) -> None:
            card_id, gift_id = pick
            if not self.minion_pool.acquire(card_id):
                raise GameStateError(
                    f"dark gift pick {card_id} no longer available in pool")
            m = self.create_minion(card_id, controller=hero)
            self.apply_dark_gift(m, gift_id)
            self.pending_hand_add(hero, m)
            self.events.fire(self, "dark_gift_given", minion=m,
                             gift_id=gift_id)

        self.pending_choices.append(PendingChoice(
            hero, options, "dark_gift", resolve_callback=resolve))
        return True

    def _draw_gift_trio(self, hero: Hero, candidates: List[str]) -> List[str]:
        """抽 3 个不同随从。

        - 提供权重官方未公布（2026-08-23 查证 dev post 无数值）——
          按候选 card_id 均匀抽样（UNVERIFIED 缺省）。
        - Turn>=6 保证式构造（dev post 原文 "guaranteed"——P2 重构
          2026-08-23: 直接替换一个非匹配 slot，等价且与措辞对齐）。
        """
        k = min(3, len(candidates))
        trio = self.rng.sample(candidates, k, label="dark_gift_minions")
        if self.turn < 6 or not hero.board:
            return trio
        common = DG.most_common_board_race(hero, self.rng)
        if common is None:
            return trio
        if any(self.db.get(cid).race in (common, Race.ALL)
               for cid in trio):
            return trio
        matching = [cid for cid in candidates
                    if self.db.get(cid).race in (common, Race.ALL)
                    and cid not in trio]
        if not matching:
            return trio     # 池内已无该种族候选 → 跳过保证
        # 保证式: 将一个非匹配 slot 替换为最常见种族候选
        for idx in range(len(trio)):
            if self.db.get(trio[idx]).race not in (common, Race.ALL):
                trio[idx] = self.rng.choice(matching,
                                            label="dark_gift_race_fill")
                break
        return trio

    def _pair_gifts(self, hero: Hero, trio: List[str],
                    candidates: List[str]) -> List[Tuple[str, str]]:
        """trio 每个随从配一个互不相同且合法的 gift。

        某随从无合法 gift → 从候选换随从重抽 ≤20 次（AMBIGUOUS: 官方
        未公布该行为，以重抽近似）; 仍失败则该位落空（提供少于 3 个）。
        """
        min_tier = min(self.db.get(cid).tech_level for cid in trio)
        used: set = set()
        options: List[Tuple[str, str]] = []
        for i in range(len(trio)):
            cid = trio[i]
            gift = self._pair_one_gift(hero, cid, min_tier, used)
            tried = {cid}
            while gift is None and len(tried) <= 20:
                alts = [c for c in candidates
                        if c not in trio and c not in tried]
                if not alts:
                    break
                alt = self.rng.choice(alts, label="dark_gift_minion_redraw")
                tried.add(alt)
                gift = self._pair_one_gift(hero, alt, min_tier, used)
                if gift is not None:
                    trio[i] = alt
            if gift is not None:
                used.add(gift)
                options.append((trio[i], gift))
        return options

    def _pair_one_gift(self, hero: Hero, cid: str, min_tier: int,
                       used: set) -> Optional[str]:
        d = self.db.get(cid)
        opts = DG.eligible_gifts(
            self.db, d, turn=self.turn, hero=hero,
            lobby_dragons_ok=self._lobby_dragons_ok(),
            minion_pool=self.minion_pool, offering_min_tier=min_tier)
        opts = [(g, w) for g, w in opts if g not in used]
        if not opts:
            return None
        # AMBIGUOUS: 官方未公布 gift 配对权重——加权抽样（稀有 ×0.5）
        return DG.weighted_choice(self.rng, opts)

    def _lobby_dragons_ok(self) -> bool:
        ar = self.minion_pool.active_races
        return ar is None or Race.DRAGON in ar

    def apply_dark_gift(self, minion: Minion, gift_id: str) -> None:
        """S14 Dark Gift 效果分派（公共 API——英雄技能等可复用）。

        DEFERRED_GIFTS 成员: 记审计日志、效果不生效——唯一允许的
        "未实现"形态（见 darkgifts.DEFERRED_GIFTS 与作业报告）。
        """
        d = self.db.get(gift_id)
        if d is None or gift_id not in DG.GIFT_WINDOWS:
            raise GameStateError(f"unknown dark gift {gift_id}")
        minion.set(GameTag.DARK_GIFT, gift_id)   # 审计: 记录获得的 gift
        if gift_id in DG.DEFERRED_GIFTS:
            self.dark_gift_audit_log.append(
                (gift_id, minion.uuid, self.turn, "DEFERRED"))
            return
        handler = _DARK_GIFT_EFFECTS.get(gift_id)
        if handler is None:
            raise GameStateError(f"unhandled dark gift {gift_id}")
        handler(self, minion, d.name)
        self.dark_gift_audit_log.append(
            (gift_id, minion.uuid, self.turn, "APPLIED"))

    # ══════════════════ S14: 招募期攻击 (Fishbait) ══════════════════

    def recruit_phase_attack(self, attacker: Minion,
                             tavern_target: Entity) -> None:
        """招募期攻击（S14 Lionfish/Snarky Shark: 棋盘随从攻击酒馆区随从）。

        官方卡面: "Your left-most Beast attacks it."（BG36_206/201）。
        语义:
          - 双向同时伤害，source 互指（KILLER 由 take_damage 设置，
            Fishbait 亡语 "Give the minion that killed this +5/+5" 据此）
          - 酒馆目标死亡: fire "death" → 亡语 → 从酒馆移除、不回池
            （该场景目标恒为 Fishbait token; AMBIGUOUS: 若为池卡是否
            回池未公布，按不回池实现）
          - 攻击者死亡: check_deaths → _process_single_death 正常路径
            （招募期死亡回池，池守恒）
          - 与战斗攻击同构: before_attack / Rally（伤害前）/ after_attack
            照常; 顺劈与 Venomous 不参与（酒馆区无相邻语义，AMBIGUOUS）
        """
        hero = attacker.controller
        if hero is None or attacker not in hero.board:
            raise GameStateError(
                "recruit_phase_attack: attacker not on a board")
        if tavern_target not in hero.tavern:
            raise GameStateError(
                "recruit_phase_attack: target not in attacker's tavern")
        self.events.fire(self, "before_attack", attacker=attacker,
                         defender=tavern_target)
        rally = attacker.call_script("rally", ctx={"target": tavern_target})
        self.run_actions(rally)
        atk_power = attacker.atk
        def_power = (tavern_target.atk
                     if isinstance(tavern_target, Minion)
                     and not tavern_target.dead else 0)
        if atk_power > 0 and isinstance(tavern_target, Minion):
            dealt = tavern_target.take_damage(atk_power, source=attacker)
            if dealt:
                self.events.fire(self, "damage", minion=tavern_target,
                                 amount=dealt, source=attacker)
        if def_power > 0:
            taken = attacker.take_damage(def_power, source=tavern_target)
            if taken:
                self.events.fire(self, "damage", minion=attacker,
                                 amount=taken, source=tavern_target)
        if (isinstance(tavern_target, Minion) and tavern_target.dead
                and tavern_target in hero.tavern):
            self.events.fire(self, "death", minion=tavern_target)
            self.run_script_hook(tavern_target, "deathrattle")
            hero.tavern.remove(tavern_target)
            tavern_target.zone = Zone.REMOVED
            self.events.unregister_owner(tavern_target)
        self.check_deaths()
        self.events.fire(self, "after_attack", attacker=attacker,
                         defender=tavern_target)

    # ══════════════════ S14: Lockbox ══════════════════

    def open_lockbox_early(self, hero: Hero, turns: int = 1) -> bool:
        """提前开启 Lockbox（Lockbox Portrait BG36_MagicItem_301:
        "it opens {0} turns sooner"——脚本层调用本 API）。
        找到手牌中的 Lockbox 减 turns 回合，归零即开启。"""
        for card in hero.hand:
            if card.get(GameTag.LOCKBOX_TURNS_LEFT, 0) > 0:
                left = card.get(GameTag.LOCKBOX_TURNS_LEFT) - turns
                if left <= 0:
                    self._open_lockbox(hero, card)
                else:
                    card.set(GameTag.LOCKBOX_TURNS_LEFT, left)
                return True
        return False

    def _open_lockbox(self, hero: Hero, lockbox: Entity) -> None:
        """开启 Lockbox: 随机有种族金色随从入手。

        BG36_520t: "break this open and get a random Golden minion with a
        type!"。金色 = 池基础卡扣减 min(3, 剩余) 份后按金色卡定义创建。
        AMBIGUOUS: 池不足 3 份时是否仍给——按仍给实现（作业单约定）;
        候选优先取池内仍有副本者，全部耗尽时退回全量有种族定义（仍给）。
        """
        typed = [d for d in self.db.pool_minions() if DG.has_race(d)]
        avail = [d.id for d in typed
                 if self.minion_pool.available(d.id) > 0]
        cands = avail if avail else [d.id for d in typed]
        if not cands:
            return
        base_id = self.rng.choice(cands, label="lockbox_golden")
        for _ in range(min(3, self.minion_pool.available(base_id))):
            if not self.minion_pool.acquire(base_id):
                raise GameStateError(
                    f"lockbox acquire failed for {base_id}")
        golden = self.create_minion(base_id, controller=hero, golden=True)
        self.pending_hand_add(hero, golden)
        if lockbox in hero.hand:
            hero.hand.remove(lockbox)
        lockbox.zone = Zone.REMOVED

    # ══════════════════ 死亡处理 (C6) ══════════════════

    combat_summon_log: List[Minion]

    def check_deaths(self) -> None:
        from hsrl2.queue import CombatLoopError  # 顶部 import 会循环依赖，延迟于此
        wave = 0
        while True:
            dead: List[Minion] = []
            for h in self.heroes:
                for m in h.board:
                    if m.dead and m.zone == Zone.PLAY:
                        dead.append(m)
            if not dead:
                return
            wave += 1
            if wave > C.DEATH_MAX_WAVES:
                raise CombatLoopError(
                    f"death waves exceeded {C.DEATH_MAX_WAVES}")
            for m in dead:
                self._process_single_death(m)

    def _process_single_death(self, m: Minion) -> None:
        """单随从死亡处理——官方顺序 (RULES §6.9 + Hearthstone 通用):

        1. death 事件
        2. **离场**: 从棋盘移除、让出板位（亡语召唤物填入此位;
           满 7/7 场亡语召唤依然成立）、graveyard、监听器注销
           （复生路径暂缓注销——见步骤 4）
        3. 亡语触发（含磁力栈叠; source 已 GRAVEYARD，效果锚点
           source.controller; 亡语召唤位置 = ctx["position"] 或
           source 的 ZONE_POSITION 残值 = 刚让出的板位）
        4. 复生: 原位 1 血回归（保留 buff/金色/关键词，仅移除复生;
           Persisting Horror Dark Gift: 满状态复活，一次性）
        5. Avenge 计数（任何友方死亡，含复生死亡）

        离场先于亡语同时修复:
          - 重入双亡语（亡语内嵌套 check_deaths 不会再收集——zone 已
            非 PLAY）
          - 亡语召唤占位（死者的 ZONE_POSITION 残值 = 释放板位:
            移除只重排其右侧随从，死者自身 tag 未被动过）
        """
        hero = m.controller
        # 1. death 事件
        self.events.fire(self, "death", minion=m)
        # 2. 离场（复生路径保留实体，稍后原位回归）
        will_reborn = m.reborn
        freed_pos = m.get(GameTag.ZONE_POSITION, 0)
        board_before_hook = list(hero.board) if hero else []
        if hero and m in hero.board:
            hero.board.remove(m)
            self._update_positions(hero)
        if will_reborn:
            m.zone = Zone.SETASIDE      # 处理期间不占 PLAY（防嵌套收集）
        else:
            m.zone = Zone.GRAVEYARD
            if hero:
                hero.graveyard.append(m)
            self.events.unregister_owner(m)
        # 3. 亡语（含磁力栈叠亡语——run_script_hook 的效果合并）
        #    官方: Deathrattles are resolved before Reborn
        #    (hearthstone.wiki.gg/wiki/Reborn#Notes)
        #    Titus Rivendare: 亡语翻倍光环（棋盘存在即生效——亡语者
        #    自身死亡时 Titus 仍在场则翻倍，官方语义）
        dr_times = 1
        for x in (hero.board if hero is not None else []):
            if x is m or not x.has(GameTag.DEATHRATTLE_DOUBLER):
                continue
            dr_times += 2 if x.is_golden else 1
        for _ in range(dr_times):
            self.run_script_hook(m, "deathrattle", ctx={"position": freed_pos})
        # 亡语触发计数 + 广播（宿主 + 每个带亡语的磁力附件各计一次）
        if m.has(GameTag.DEATHRATTLE) and hero is not None:
            n_attached_dr = sum(
                1 for aid in self._magnetic_stack.get(m.uuid, [])
                if "deathrattle" in (self.db.get(aid).keywords
                                     if self.db.get(aid) else frozenset()))
            total = 1 + n_attached_dr
            hero.set(GameTag.COUNTER_DEATHRATTLES,
                     hero.get(GameTag.COUNTER_DEATHRATTLES, 0) + total)
            for _ in range(total):
                self.events.fire(self, "deathrattle_trigger", minion=m)
        # 战斗死亡日志（Kangor's Apprentice "first 2 Mechs that died this
        # combat" 类——按死亡顺序记录，战斗开始时清空）
        if self.in_combat:
            self.combat_death_log.append(m)
        # 每英雄按 card_id 的累计死亡簿记（Eternal Knight "for each
        # friendly Eternal Knight that died this game"——跨战斗持久）
        if hero is not None:
            if not hasattr(hero, "deaths_by_card_id"):
                hero.deaths_by_card_id = {}
            hero.deaths_by_card_id[m.card_id] = \
                hero.deaths_by_card_id.get(m.card_id, 0) + 1
        # 招募期死亡回池——置于亡语**之后**（否则死亡副本先回流池，
        # 会被自身亡语的"随机获取 X"重新抽到——Sly Raptor 自抽缺陷）
        if not will_reborn and not self.in_combat:
            self.minion_pool.release_minion_entity(m)
        # 4. 复生: 原位 1 血回归（Persisting Horror: 满状态，一次性）。
        #    插位规则: 从 freed_pos 起跳过亡语期间新入场的召唤物——
        #    官方可观测行为: 亡语召唤物占据死者板位，复活体排在其后
        #    (Deathrattles resolved before Reborn)
        if will_reborn:
            m.clear(GameTag.REBORN)
            m.clear(GameTag.DEAD)
            if m.uuid in self._reborn_full_uuids:
                self._reborn_full_uuids.discard(m.uuid)
                m.set(GameTag.HEALTH, m.max_health)
            else:
                m.set(GameTag.HEALTH, 1)
            m.zone = Zone.PLAY
            if hero is not None:
                new_uuids = {x.uuid for x in hero.board
                             if x not in board_before_hook}
                pos = freed_pos
                while (pos < len(hero.board)
                       and hero.board[pos].uuid in new_uuids):
                    pos += 1
                hero.board.insert(pos, m)
                self._update_positions(hero)
            self.events.fire(self, "reborn", minion=m)
        # 5. Avenge: 任何友方死亡都计数（含复生死亡）— RULES §6.11
        if hero:
            for other in hero.board:
                if other is m:
                    continue
                if other.has(GameTag.AVENGE):
                    n = other.get(GameTag.AVENGE_COUNTER, 0) + 1
                    other.set(GameTag.AVENGE_COUNTER, n)
                    target = other.get(GameTag.AVENGE_TARGET, 0)
                    if target and n >= target:
                        other.set(GameTag.AVENGE_COUNTER, 0)
                        self.run_script_hook(other, "avenge")

    # ══════════════════ 战斗编排 ══════════════════

    def end_recruit_phase(self) -> None:
        """招募阶段收尾 → 战斗编排 → 淘汰 → 下一回合 (RULES §1.2 回合结构)。

        顺序（RULES §1.2/§3.5/§4.8/§5/§6.13）:
          1. 存活英雄的回合结束效果: 饰品 → 任务奖励 → 棋盘随从左→右，
             每个 hook 后 check_deaths（EoT 效果可致死，如自残恶魔）
          2. 丢弃手牌中未使用的 Spellcraft 法术（回合结束消失, RULES §6.13）
          3. 快照存活英雄 board → last_combat_board（幽灵/记忆来源, RULES §4.8）
          4. pair_players 配对 (RULES §4.8)，逐对 run_combat 并 fire "combat_end"
          5. 奇数 leftover → run_ghost_combat（幽灵战, RULES §4.8）
          6. _process_eliminations（淘汰回池, RULES §2.3）
          7. 存活 ≤1 → finished；否则 turn+1 并对每个存活英雄开始新招募回合
        """
        alive = [h for h in self.heroes if h.is_alive]
        for h in alive:
            h.clear(GameTag.TURN_SKIPPED)   # 跳回合只锁一个招募期
        # turn_end 广播（Ragnaros/Sulfuras/C'Thun 类 EoT 被动——
        # hero_passives 批上报缺口; 于 EoT 效果之前、与 TURN_START 对称）
        self.events.fire(self, "turn_end", turn=self.turn)
        # 1. EoT: 每个 hook 后结死（自残类 EoT 可当场死亡）
        for hero in alive:
            for trinket in list(hero.trinkets):
                self.run_script_hook(trinket, "end_of_turn")
                self.check_deaths()
            for reward in list(getattr(hero, "quest_rewards", [])):
                self.run_script_hook(reward, "end_of_turn")
                self.check_deaths()
            for m in list(hero.board):
                # Drakkari Enchanter: EoT 翻倍光环（棋盘存在即生效;
                # 金色 Drakkari = ×3——官方金色文本 "trigger three times"）
                times = 1
                for x in hero.board:
                    if x is m or not x.has(GameTag.END_OF_TURN_DOUBLER):
                        continue
                    times += 2 if x.is_golden else 1
                for _ in range(times):
                    self.run_script_hook(m, "end_of_turn")
                    self.check_deaths()
        # 2. Spellcraft 法术回合结束丢弃 (RULES §6.13)
        #    例外 (Sunken Persistence Dark Gift): 该随从生成的 Spellcraft
        #    永久——脚本层契约: 生成时在法术实体上设 spellcraft_source_uuid
        for hero in alive:
            for card in list(hero.hand):
                if (card.has(GameTag.SPELLCRAFT) and card.zone == Zone.HAND
                        and getattr(card, "spellcraft_source_uuid", None)
                        not in self._permanent_spellcraft_uuids):
                    hero.hand.remove(card)
                    card.zone = Zone.REMOVED
        # 3. 战前棋盘快照（幽灵阵容与战斗记忆的数据来源）
        for hero in alive:
            hero.last_combat_board = list(hero.board)
        # 4. 配对 + 顺序战斗。damage cap 按本阶段**开始时**的存活人数
        #    （官方: 同一回合战斗同时结算，先死者不影响同回合上限判定, RULES §5.2）
        phase_alive = len(alive)
        pairs, leftover = matchmaking.pair_players(
            alive, self.rng, self._opponent_history)
        # 淘汰预标记（配对后、伤害前——本周配对对手的板快照供
        # Scabbs "next opponent's warband" 等在下一招募期读取:
        # _next_opponent_warband 记录的是**本阶段配对对手的战前板**，
        # 淘汰回池后其为冻结副本语义）
        # RULES §4.8: 不会连续两次面对克尔苏加德（除非只剩 2 名玩家）——
        # 上阶段刚打幽灵者若再次轮为 leftover，与一对中的玩家交换名额
        if (leftover is not None and len(alive) > 2
                and getattr(leftover, "fought_ghost_last", False)
                and pairs):
            swap = pairs[0][0]
            pairs[0] = (leftover, pairs[0][1])
            leftover = swap
        # 下一对手预告（Scabbs API）: 记录每个存活者本阶段对手的
        # 战前板快照——下一招募期 game.next_opponent_warband(hero) 可读
        self._next_opponent_snapshot = {}
        for p1, p2 in pairs:
            self._next_opponent_snapshot[p1] = list(p2.board)
            self._next_opponent_snapshot[p2] = list(p1.board)
        for h in alive:
            h.fought_ghost_last = False
        for p1, p2 in pairs:
            result = self.run_combat(p1, p2, alive_count=phase_alive)
            self.combat_memory.setdefault(p1, []).append(p2)
            self.combat_memory.setdefault(p2, []).append(p1)
            self.events.fire(self, "combat_end", hero_a=p1, hero_b=p2,
                             result=result)
        # 5. 奇数人 → 幽灵战
        if leftover is not None:
            self.run_ghost_combat(leftover, alive_count=phase_alive)
            leftover.fought_ghost_last = True
        # 6. 淘汰结算
        self._process_eliminations()
        # 7. 终局判定 / 下一回合
        alive = [h for h in self.heroes if h.is_alive]
        if len(alive) <= 1:
            self.finished = True
            return
        self.turn += 1
        for hero in alive:
            self._begin_recruit_for(hero)

    def run_ghost_combat(self, hero: Hero, alive_count: int | None = None):
        """奇数存活者的幽灵战 (RULES §4.8 Kel'Thuzad / Ghost)。

        - ghost 来源: self.ghost_records[-1]（最近被淘汰者的冻结快照）。
          无记录 → 本回合跳过战斗（早期无人淘汰时奇数人的官方行为）
        - 幽灵阵容为淘汰时的冻结副本，不成长不变化 (RULES §4.8)
        - hero 败: 伤害 = ghost.tavern_tier + Σ 幽灵存活随从 tech_level
          (RULES §5.1)，过 damage_cap(turn, 真实存活人数) (RULES §5.2)
        - hero 胜/平: hero 不受伤；幽灵为临时实体，战后整体丢弃
          （对其造成的伤害不可见）
        - 幽灵临时 append 进 self.heroes（CombatScheduler/check_deaths 遍历
          self.heroes，缺席则幽灵随从死亡处理失效），finally 中移除；
          任何提前 return 都走 finally
        - ghost.health 置 0: 使 _alive_count 不把幽灵计入存活人数 —
          damage_cap 按真实玩家数计算 (RULES §5.2 "存活玩家数 ≤ 4 解除")
        - hero 的对手历史/战斗记忆记 None 对手
        - AMBIGUOUS: 幽灵棋盘 SoC 是否照常重触发待实测验证（wiki 无明确
          记载），当前按正常战斗语义处理
        """
        if not self.ghost_records:
            return None
        record = self.ghost_records[-1]
        ghost = Hero("TB_BaconShop_HERO_KelThuzad", record["name"],
                     base_health=C.HERO_BASE_HEALTH, armor=0)
        ghost.game = self
        ghost.set(GameTag.TAVERN_TIER, record["tavern_tier"])
        ghost.health = 0   # 非真实玩家: 不计入 damage_cap 的存活人数
        board = list(record["board"])
        for m in board:
            m.controller = ghost
            m.zone = Zone.PLAY
        ghost.board = board
        self.heroes.append(ghost)
        try:
            result = self.run_combat(hero, ghost, alive_count=alive_count)
            self._opponent_history.setdefault(hero, []).append(None)
            self._opponent_history[hero] = self._opponent_history[hero][-2:]
            self.combat_memory.setdefault(hero, []).append(None)
            # 幽灵战同样广播 combat_end（Overconfidence "next combat" 类
            # 触发器含幽灵战——Wave4 反馈缺口）
            self.events.fire(self, "combat_end", hero_a=hero, hero_b=ghost,
                             result=result)
            return result
        finally:
            if ghost in self.heroes:
                self.heroes.remove(ghost)
            for m in ghost.board:
                m.controller = None

    def next_opponent_warband(self, hero: Hero):
        """Scabbs "next opponent's warband"——本招募期可读的下一场
        战斗对手板快照（上一配对阶段记录，随淘汰/新回合失效为 None）。"""
        snap = getattr(self, "_next_opponent_snapshot", None)
        return snap.get(hero) if snap else None

    def _process_eliminations(self) -> None:
        """战斗全部结束后结算淘汰 (RULES §2.3 / REFACTOR_PLAN P8)。

        health ≤ 0 的英雄（is_alive 语义: health>0，不改 hero.py）:
          1. 棋盘随从逐个回池（金色 3 份, RULES §2.3）
          2. 手牌: Minion 同上回池; Spell 仅限池内法术（db.is_pool_spell）
          3. 酒馆展示区 tavern 同样回池
          4. 生成 ghost_record（棋盘冻结快照 + tavern_tier + name）append 到
             self.ghost_records (RULES §4.8)
          5. fire "hero_eliminated" 事件
        淘汰者从 self.heroes 移除（否则后续回合 check_deaths 仍会扫描其
        棋盘、且本函数重复调用会重复回池）；health 保持 0。
        """
        eliminated = [h for h in self.heroes if h.health <= 0]
        for hero in eliminated:
            for m in list(hero.board):
                self.minion_pool.release_minion_entity(m)
                m.zone = Zone.REMOVED
            for card in list(hero.hand):
                if isinstance(card, Minion):
                    self.minion_pool.release_minion_entity(card)
                elif isinstance(card, Spell):
                    d = self.db.get(card.card_id)
                    if d is not None and d.is_pool_spell:
                        self.spell_pool.release(card.card_id)
                card.zone = Zone.REMOVED
            for e in list(hero.tavern):
                if isinstance(e, Minion):
                    self.minion_pool.release_minion_entity(e)
                else:
                    d = self.db.get(e.card_id)
                    if d is not None and d.is_pool_spell:
                        self.spell_pool.release(e.card_id)
                e.zone = Zone.REMOVED
            self.ghost_records.append({
                "name": hero.name,
                "board": [_frozen_clone(m) for m in hero.board],
                "tavern_tier": hero.tavern_tier,
            })
            self.events.fire(self, "hero_eliminated", hero=hero)
            self.heroes.remove(hero)

    def run_combat(self, hero_a: Hero, hero_b: Hero,
                   alive_count: int | None = None):
        """执行一场战斗。战斗状态在快照后修改，战后恢复 (Tarecgosa 类
        保留机制通过 persist 标记处理)。

        alive_count: 本战斗阶段开始时的存活人数（damage cap 判定用，
        RULES §5.2 同回合战斗同时结算）；None = 实时统计。
        """
        self.in_combat = True
        self.combat_summon_log = []
        self.combat_death_log = []   # 按死亡顺序（Kangor 类消费）
        snapshots = {}
        board_before = {}
        for hero in (hero_a, hero_b):
            board_before[hero] = list(hero.board)
            for m in hero.board:
                snapshots[m] = m.snapshot_state()
        # 监听器表快照: 战斗中死亡的随从会触发 unregister_owner，但战后
        # 棋盘整体复原（随从复活）——监听器必须随之复原，否则持久触发器
        # （Tichondrius 等）在随从首次战死后静默失效。
        # 已触发的 once 监听器在**恢复时**按 _fired 标记过滤（快照时点
        # 尚未触发）——防复活重复触发。
        events_snapshot = {ev: list(lst)
                           for ev, lst in self.events._listeners.items()}
        try:
            scheduler = CombatScheduler(self, hero_a, hero_b)
            result = scheduler.run()
            # 上局战斗结果记录（Tortollan Blue Shell "If you lost your
            # last combat" 类条件的数据源）
            hero_a._last_combat_result = (
                "win" if result.winner is hero_a
                else "loss" if result.loser is hero_a else "draw")
            hero_b._last_combat_result = (
                "win" if result.winner is hero_b
                else "loss" if result.loser is hero_b else "draw")
            damage = self._compute_damage(result)
            if damage and result.loser is not None:
                n_alive = alive_count if alive_count is not None \
                    else self._alive_count()
                cap = C.damage_cap(self.turn, n_alive)
                actual = min(damage, cap) if cap is not None else damage
                result.damage_dealt = damage
                result.capped_damage = actual

            # ══ 官方伤害时序（2026-08-22 修正，压测 Soul Rewinder
            # 不死疑点裁决）: 战败伤害施加在**战后棋盘**上——战斗中
            # 死亡的随从仍在墓地、其监听器已在死亡处理时注销
            # （Soul Rewinder 战死→不回溯; Tichondrius 战死→不触发）。
            # 复活/快照恢复发生在伤害**之后**（下回合开始时全队复原），
            # 因此伤害窗口内触发器写入的增益必须以"增量重放"跨过
            # 恢复（否则被快照回滚——SA6 期旧缺陷）。══

            # 1. PERSIST/Poet 捕获——基于**伤害前**战后状态（战斗期增益;
            #    伤害窗口增益走通用 delta 路径，防双计）
            poet_persist: dict = {}
            for hero in (hero_a, hero_b):
                poets = [m for m in board_before[hero]
                         if m.has(GameTag.ADJACENT_PERSIST_SOURCE)]
                if not poets:
                    continue
                # 倍率: 金色 Poet "double stats"（BG29_813_G XML 文本）
                # → 2×; 基础 Poet 1×
                mult = 2 if any(p.is_golden for p in poets) else 1
                poet_pos = {board_before[hero].index(p) for p in poets}
                for idx, m in enumerate(board_before[hero]):
                    if m not in snapshots:
                        continue
                    if not any(abs(idx - p) == 1 for p in poet_pos):
                        continue
                    if m.race not in (Race.DRAGON, Race.ALL):
                        continue
                    poet_persist[m] = (
                        m.atk, m.max_health,
                        {t: m.has(t) for t in _PERSIST_KEYWORD_TAGS},
                        mult,
                    )
            persist_totals = {
                m: (m.atk, m.max_health,
                    {t: m.has(t) for t in _PERSIST_KEYWORD_TAGS})
                for hero in (hero_a, hero_b)
                for m in board_before[hero]
                if m in snapshots and m.has(PERSIST_TAG)
            }
            # 2. 伤害窗口标记（buff 身份 + 关键词态）
            dmg_markers = {
                m: ({id(b) for b in m._buffs},
                    {t: m.has(t) for t in _PERSIST_KEYWORD_TAGS})
                for hero in (hero_a, hero_b) for m in board_before[hero]
            }
            # 3. 施加伤害（战后棋盘; 战死者监听器缺席）
            if result.capped_damage and result.loser is not None:
                result.loser.take_damage(result.capped_damage)
            # 4. 捕获伤害窗口增量（幸存触发器写入的 buff/关键词）
            dmg_deltas = {}
            for hero in (hero_a, hero_b):
                for m in board_before[hero]:
                    marker_ids, marker_kws = dmg_markers[m]
                    new_buffs = [b for b in m._buffs
                                 if id(b) not in marker_ids]
                    new_kws = [t for t, present in marker_kws.items()
                               if not present and m.has(t)]
                    if new_buffs or new_kws:
                        dmg_deltas[m] = (new_buffs, new_kws)
            self._last_combat_results[(hero_a, hero_b)] = result
        finally:
            # 战斗状态恢复 (RULES §3.5): 战斗中获得的变化不延续到招募阶段。
            # 例外 1: PERSIST_COMBAT_CHANGES 随从保留战斗期增益（总量已
            #   在伤害前捕获——persist_totals）
            # 例外 2: Persistent Poet 相邻龙保留战斗增益（poet_persist，
            #   战前相邻为准，AMBIGUOUS: 战内移位不追踪）
            # 例外 3: 伤害窗口增量（dmg_deltas——战败伤害触发器写入的
            #   增益，官方随复活保留）在恢复后重放
            for hero in (hero_a, hero_b):
                for m in board_before[hero]:
                    if m not in snapshots:
                        continue
                    if m in persist_totals:
                        # 战斗属性保留（倍率: PERSIST_DOUBLE → 2×——
                        # Tarecgosa gift/golden Poet "double stats";
                        # 池卡 Tarecgosa 1×）。恢复后按"捕获总增益 × 倍率"
                        # 重放为永久 Buff（等效保留原增益，翻倍时放大）
                        mult = 2 if m.has(GameTag.PERSIST_DOUBLE) else 1
                        post_atk_total, post_health_total, post_keywords = \
                            persist_totals[m]
                        m.restore_state(snapshots[m])
                        g_atk = post_atk_total - m.atk
                        g_health = post_health_total - m.max_health
                        if g_atk > 0 or g_health > 0:
                            m.add_buff(Buff(atk=max(0, g_atk) * mult,
                                            health=max(0, g_health) * mult))
                        for tag, present in post_keywords.items():
                            if present:
                                m.set(tag, True)
                            else:
                                m.clear(tag)
                        # 战斗伤害不延续: HEALTH 重算为 max_health
                        m.set(GameTag.HEALTH, m.max_health)
                    else:
                        m.restore_state(snapshots[m])
                    m.set(GameTag.DEAD, False)
                    m.clear(GameTag.EXHAUSTED)
                    m.clear(GameTag.WINDFURY_ATTACKS)
                    m.clear(GameTag.VENOMOUS_CONSUMED)
                # 战斗召唤物（不在 board_before 中的）从 board 移除
                hero.board = list(board_before[hero])
            # Persistent Poet 相邻龙回放（post 总增益已在恢复前捕获;
            # 倍率含金色 Poet double stats）
            for m, (p_atk, p_health, p_kws, mult) in poet_persist.items():
                g_atk = p_atk - m.atk
                g_health = p_health - m.max_health
                if g_atk > 0 or g_health > 0:
                    m.add_buff(Buff(atk=max(0, g_atk) * mult,
                                    health=max(0, g_health) * mult))
                for tag, present in p_kws.items():
                    if present:
                        m.set(tag, True)
                m.set(GameTag.HEALTH, m.max_health)
            # 伤害窗口增量重放（战败伤害触发器的增益——Tichondrius/
            # Soul Rewinder 幸存体的 buff 官方随复活保留）
            for m, (new_buffs, new_kws) in dmg_deltas.items():
                for b in new_buffs:
                    if b not in m._buffs:
                        m._buffs.append(b)
                        if b.health > 0:
                            m.set(GameTag.HEALTH, m.health + b.health)
                for t in new_kws:
                    m.set(t, True)
            # 监听器表复原（与棋盘快照同步——战斗内的注册/注销不延续;
            # 战斗中已触发的 once 监听器不复活。战死随从的监听器随
            # 复活回归——供**未来**回合使用，本战斗伤害已结算完毕）
            self.events._listeners = {
                ev: [l for l in lst if not (l.once and l._fired)]
                for ev, lst in events_snapshot.items()
            }
            self.in_combat = False
        return result

    def _compute_damage(self, result) -> int:
        """伤害 = 胜方酒馆等级 + Σ存活随从 tier (token=T1, 金色无加成)。"""
        if result.winner is None:
            return 0
        return result.winner.tavern_tier + sum(
            m.tech_level for m in result.winner.living_minions())

    def _alive_count(self) -> int:
        return sum(1 for h in self.heroes if h.is_alive)

    # ══════════════════ 实体工厂 ══════════════════

    def create_minion(self, card_id: str, *, controller=None,
                      golden: bool = False) -> Optional[Minion]:
        d = self.db.get(card_id)
        if d is None:
            raise KeyError(f"unknown minion card_id {card_id}")
        if golden:
            gd = self.db.golden_version(d)
            if gd is not None:
                d = gd
        m = Minion(d.id, d.name, atk=d.atk, health=d.health,
                   race=d.race, tech_level=d.tech_level)
        m.game = self
        m.controller = controller
        for kw in d.keywords:
            tag = _KEYWORD_TAG_MAP.get(kw)
            if tag is not None:
                m.set(tag, True)
        if d.avenge_target:
            m.set(GameTag.AVENGE, True)
            m.set(GameTag.AVENGE_TARGET, d.avenge_target)
        if d.activate_cost is not None:
            m.set(GameTag.ACTIVATE, True)
            m.set(GameTag.ACTIVATE_COST, d.activate_cost)
        # Spellcraft 随从标记（CardDef.spellcraft_id → SPELLCRAFT tag）
        if d.spellcraft_id is not None:
            m.set(GameTag.SPELLCRAFT, True)
        if golden:
            # 金色实体: 记录基础卡 id — 出售/淘汰时返还基础卡 3 份
            base_def = self.db.by_dbf(d.triple_base_id) if d.is_golden_def else None
            base_id = base_def.id if base_def is not None else card_id
            m.set(GameTag.TRIPLE_BASE_CARD_ID, base_id)
            m.set(GameTag.GOLDEN, True)
        # 脚本绑定: card_id（金色版为独立注册的 id）→ REGISTRY
        from hsrl2.scripts import REGISTRY  # 延迟导入避免循环依赖
        m.scripts = REGISTRY.get(m.get(GameTag.CARD_ID))
        self.events.fire(self, "entity_created", entity=m)
        return m

    def create_spell(self, card_id: str, *, controller=None) -> Optional[Spell]:
        d = self.db.get(card_id)
        if d is None:
            raise KeyError(f"unknown spell card_id {card_id}")
        s = Spell(d.id, d.name, cost=d.cost)
        s.game = self
        s.controller = controller
        # Lockbox 手牌倒计时实体（初始回合数 = CardDef.num(0) 权威）
        if d.id == C.LOCKBOX_CARD_ID:
            s.set(GameTag.LOCKBOX_TURNS_LEFT,
                  d.num(0) if d.num(0) is not None else C.LOCKBOX_TURNS)
        # 脚本绑定（与 create_minion 同构）
        from hsrl2.scripts import REGISTRY
        s.scripts = REGISTRY.get(s.get(GameTag.CARD_ID))
        # SPELLCRAFT 标记（法术本体带 Spellcraft 关键词的定义）
        if d.dark_gift:
            pass   # Dark Gift 是法术型实体但非 Spellcraft
        self.events.fire(self, "entity_created", entity=s)
        return s

    # ══════════════════ 脚本/动作执行 ══════════════════

    def run_script_hook(self, entity: Entity, hook: str, ctx: Any = None) -> None:
        """执行脚本钩子并把返回的 Action(s) 送入队列解析。

        磁力效果合并 (RULES §6.14 "效果合并"): 宿主触发某钩子时，
        其吸附的磁力随从的**同钩子**效果以宿主为 source 一并触发
        （吸附顺序）。仅对 Minion 实体生效。
        """
        result = entity.call_script(hook, ctx)
        self.run_actions(result)
        if isinstance(entity, Minion):
            for attached_id in self._magnetic_stack.get(entity.uuid, []):
                from hsrl2.scripts import REGISTRY
                script_cls = REGISTRY.get(attached_id)
                if script_cls is None:
                    continue   # 脚本未迁移——效果暂缺（audit 由缺口审计盯）
                fn = getattr(script_cls, hook, None)
                if fn is None:
                    continue
                attached_result = fn(entity, self, ctx)
                self.run_actions(attached_result)

    def run_actions(self, actions) -> None:
        if actions is None:
            return
        if isinstance(actions, Action):
            self.queue.enqueue(actions)
        elif isinstance(actions, (list, tuple)):
            self.queue.enqueue_all(actions)
        self.queue.resolve(self)

    def _update_positions(self, hero: Hero) -> None:
        for i, m in enumerate(hero.board):
            m.set(GameTag.ZONE_POSITION, i)


# ══════════════════ S14 Dark Gift 效果实现 ══════════════════
# 每个 handler: (game, minion, gift_name)。数值出处: data/bg_dark_gifts.json
# （XML 权威; 模板参数缺失时文本即权威）+ 官方 dev post。


def _chain_hook(entity: Entity, hook: str, fn) -> None:
    """在实体既有 hook 行为**之后**追加 fn（官方: gift 是额外效果——
    亡语 gift 明确"原生先触发再追加"; EoT/rally/SoT 顺序未公布，
    按亡语同构处理，AMBIGUOUS）。已有 override 时链式保留。"""
    prev_override = entity._script_overrides.get(hook)
    scripts_fn = (getattr(entity.scripts, hook, None)
                  if entity.scripts is not None else None)

    def chained(source, game, ctx):
        if prev_override is not None:
            result = (prev_override(source, game, ctx)
                      if callable(prev_override) else prev_override)
        elif scripts_fn is not None:
            result = scripts_fn(source, game, ctx)
        else:
            result = None
        fn(source, game, ctx)
        return result

    entity.set_script_override(hook, chained)


def _soc_listener(game: "Game", m: Minion, fn) -> None:
    """注册 SoC 监听（owner=随从，离场自动注销）。

    官方语义: gift 效果与随从自身 SoC 叠加。用事件监听而非
    set_script_override——后者会遮蔽随从原生 SoC 脚本。
    AMBIGUOUS: 与随从原生 SoC 的相对顺序未公布，事件在原生
    SoC 钩子之后广播 → listener 后触发。"""
    game.events.register(Listener(
        event="start_of_combat", owner=m,
        condition=lambda hero=None, **kw: hero is m.controller,
        callback=lambda g, **kw: fn(g),
    ))


def _plain_copy_to_hand(game: "Game", m: Minion, gname: str = "") -> None:
    """plain copy 进手牌（Double Vision / Replication; 不召唤、不占池——
    复制自有随从不消耗池副本）。金色 source → 金色 copy。"""
    hero = m.controller
    if hero is None:
        return
    if m.is_golden:
        base_id = m.get(GameTag.TRIPLE_BASE_CARD_ID, None) or m.card_id
        copy = game.create_minion(base_id, controller=hero, golden=True)
    else:
        copy = game.create_minion(m.card_id, controller=hero)
    game.pending_hand_add(hero, copy)


# ── 纯数值 / 关键词 ──

def _gift_fortitude(game, m, gname):
    # "+5/+5."（XML 文本; 模板参数未导出，文本即权威）
    m.add_buff(Buff(5, 5, dark_gift=gname))


def _gift_harpys_talons(game, m, gname):
    # "Divine Shield, Windfury"
    m.set(GameTag.DIVINE_SHIELD, True)
    m.set(GameTag.WINDFURY, True)


def _gift_toxicity(game, m, gname):
    m.set(GameTag.VENOMOUS, True)          # "Venomous"


def _gift_furtiveness(game, m, gname):
    m.set(GameTag.STEALTH, True)           # "Stealth"


def _gift_tarecgosas_blessing(game, m, gname):
    # "Permanently keeps Bonus Keywords and double stats gained in combat."
    # （XML 文本——对抗审查 BUG-3: gift 是 double，池卡 Tarecgosa 是 1×）
    m.set(PERSIST_TAG, True)
    m.set(GameTag.PERSIST_DOUBLE, True)


def _gift_invulnerability(game, m, gname):
    # "Immune while attacking."（战斗调度器 IMMUNE_WHILE_ATTACKING 已支持）
    m.set(GameTag.IMMUNE_WHILE_ATTACKING, True)


def _gift_gilding(game, m, gname):
    # "This is Golden, but doesn't give a Triple Reward."
    m.set(GameTag.GOLDEN, True)
    m.set(GameTag.GOLDEN_NO_TRIPLE_REWARD, True)
    # 非三连金色: 回池按 1 份（RULES §2.3 Reno 条目同族——Gilding
    # 语义 = Reno 式金色化，2026-08-22 与 GILDED_NOT_TRIPLED 统一）
    m.set(GameTag.GILDED_NOT_TRIPLED, True)
    game._gilded_no_reward_uuids.add(m.uuid)


def _gift_amalgamation(game, m, gname):
    m.set(GameTag.RACE, Race.ALL)          # "Has all minion types."


def _gift_toreths_blessing(game, m, gname):
    # "This minion's Divine Shield takes 3 hits to break."（XML 文本）
    m.set(GameTag.DIVINE_SHIELD_HITS, 3)


def _gift_titanic_strength(game, m, gname):
    m.add_buff(Buff(1000, 0, dark_gift=gname))   # "+1000 Attack."（XML 文本）


def _gift_persisting_horror(game, m, gname):
    # "Reborn. Is Reborn with full stats and Bonus Keywords."
    # 关键词保留是复生默认语义; 满血由 _process_single_death 消费
    # _reborn_full_uuids 实现（一次性）
    m.set(GameTag.REBORN, True)
    game._reborn_full_uuids.add(m.uuid)


def _gift_sunken_persistence(game, m, gname):
    # "This minion's Spellcrafts are permanent."
    # 脚本层契约: 该随从生成的 Spellcraft 法术设 spellcraft_source_uuid
    game._permanent_spellcraft_uuids.add(m.uuid)


# ── 回合驱动（EoT / SoT 监听）──

def _gift_steady_growth(game, m, gname):
    # "At the end of your turn, gain +{1}/+{2}." — XML 模板参数为空，
    # 数值按获得回合查 STEADY_GROWTH_VALUES（dev post 原文）
    vals = DG.STEADY_GROWTH_VALUES.get(game.turn, (4, 4))

    def eot(source, g, ctx):
        source.add_buff(Buff(vals[0], vals[1], dark_gift=gname))
    _chain_hook(m, "end_of_turn", eot)


def _gift_incubation(game, m, gname):
    # "+4/+4. In 2 turns, double this minion's stats."（XML 文本）
    m.add_buff(Buff(4, 4, dark_gift=gname))
    state = {"turns": 0, "done": False}

    def sot(g, hero=None, **kw):
        if hero is not m.controller or state["done"]:
            return
        state["turns"] += 1
        if state["turns"] >= 2:
            state["done"] = True
            # Evidence: wiki.gg/wiki/Multiply_attribute——HS 通用 double
            # = 当前值基数（血量翻倍同时抬当前与上限，受损差值保留）
            m.add_buff(Buff(m.atk, m.health, dark_gift=gname))
    game.events.register(Listener(event="turn_start", owner=m, callback=sot))


def _gift_replication(game, m, gname):
    # "At the end of every 2 turns, get a plain copy of this."
    # AMBIGUOUS: "every 2 turns" 的对齐点未公布——按获得后第 2 个 EoT 起
    state = {"turns": 0}

    def sot(g, hero=None, **kw):
        if hero is m.controller:
            state["turns"] += 1
    game.events.register(Listener(event="turn_start", owner=m, callback=sot))

    def eot(source, g, ctx):
        if state["turns"] >= 2:
            state["turns"] -= 2
            _plain_copy_to_hand(g, source, gname)
    _chain_hook(m, "end_of_turn", eot)


def _gift_affinity(game, m, gname):
    # "At the end of every 2 turns, get a random minion of this type."
    from hsrl2.actions.discover import GetRandomMinion
    state = {"turns": 0}

    def sot(g, hero=None, **kw):
        if hero is m.controller:
            state["turns"] += 1
    game.events.register(Listener(event="turn_start", owner=m, callback=sot))

    def eot(source, g, ctx):
        if state["turns"] >= 2:
            state["turns"] -= 2
            g.run_actions(GetRandomMinion(source.controller,
                                          race=source.race))
    _chain_hook(m, "end_of_turn", eot)


def _gift_time_turning(game, m, gname):
    # "This minion's end of turn effects also trigger at start of turn."
    def sot(source, g, ctx):
        g.run_script_hook(source, "end_of_turn")
    _chain_hook(m, "start_of_turn", sot)


def _gift_echoing_voice(game, m, gname):
    # "At the end of your turn, trigger this minion's Battlecries."
    def eot(source, g, ctx):
        hero = source.controller
        if hero is None or source.zone != Zone.PLAY or source.dead:
            return
        # 触发次数与 play_minion 同构: 金色×2、Brann 类×2
        times = 1
        if source.is_golden:
            times *= 2
        if any(x.has(GameTag.BATTLECRY_DOUBLER) for x in hero.board):
            times *= 2
        for _ in range(times):
            g.run_script_hook(source, "battlecry")
            if source.has(GameTag.BATTLECRY):
                hero.set(GameTag.COUNTER_BATTLECRIES,
                         hero.get(GameTag.COUNTER_BATTLECRIES, 0) + 1)
                g.events.fire(g, "battlecry_trigger", minion=source)
    _chain_hook(m, "end_of_turn", eot)


# ── 战斗开始（SoC 监听）──

def _gift_transcendence(game, m, gname):
    # "Start of Combat: Triple this minion's stats."
    def fn(g):
        m.add_buff(Buff(2 * m.atk, 2 * m.health, dark_gift=gname))
    _soc_listener(game, m, fn)


def _gift_resistance(game, m, gname):
    # "Start of Combat: Double this minion's Health."
    def fn(g):
        m.add_buff(Buff(0, m.health, dark_gift=gname))
    _soc_listener(game, m, fn)


def _gift_hostility(game, m, gname):
    # "Start of Combat: Double this minion's Attack."
    def fn(g):
        m.add_buff(Buff(m.atk, 0, dark_gift=gname))
    _soc_listener(game, m, fn)


def _gift_admiration(game, m, gname):
    # "Start of Combat: Gain the Attack of the minion to the left."
    def fn(g):
        hero = m.controller
        if hero is None or m not in hero.board:
            return
        idx = hero.board.index(m)
        if idx > 0:
            left = hero.board[idx - 1]
            if not left.dead:
                m.add_buff(Buff(left.atk, 0, dark_gift=gname))
    _soc_listener(game, m, fn)


def _gift_jaws_of_death(game, m, gname):
    # "Start of Combat: Trigger this minion's Deathrattles."
    # AMBIGUOUS: 此触发是否计入 COUNTER_DEATHRATTLES 未公布——当前不计
    def fn(g):
        g.run_script_hook(m, "deathrattle")
    _soc_listener(game, m, fn)


# ── 动态计数（Battle Scars / Death's Embrace / Spell Siphon）──

def _make_counter_gift(per_atk: int, per_health: int, counter_tag: GameTag,
                       event_name: str, ctx_key: str):
    """计数型动态属性: 施加时按既有计数补齐，之后每次对应触发 +per。

    初始补齐 + 事件增量等价于 "Has +X/+X for each ... triggered this game"
    的动态读数（事件源按 controller 归属过滤）。"""
    def handler(game, m, gname):
        hero = m.controller
        n0 = hero.get(counter_tag, 0) if hero is not None else 0
        for _ in range(n0):
            m.add_buff(Buff(per_atk, per_health, dark_gift=gname))

        def cb(g, **kw):
            src = kw.get(ctx_key)
            if src is None or src.controller is not m.controller:
                return
            m.add_buff(Buff(per_atk, per_health, dark_gift=gname))
        game.events.register(Listener(event=event_name, owner=m,
                                      callback=cb))
    return handler


# ── 打牌触发（Dexterity / Sharpened Sword / Toughened Shield）──

def _make_card_played_gift(atk: int, health: int):
    """"Whenever you play a card, gain +X/+Y"——仅在棋盘上生效。"""
    def handler(game, m, gname):
        def cb(g, card=None, **kw):
            if m.zone != Zone.PLAY or m.dead:
                return
            if card is None or card.controller is not m.controller:
                return
            m.add_buff(Buff(atk, health, dark_gift=gname))
        game.events.register(Listener(event="card_played", owner=m,
                                      callback=cb))
    return handler


# ── 亡语追加（gift 亡语 = 额外亡语，原生先触发）──

def _gift_mystic_essence(game, m, gname):
    # "Deathrattle: Get a random Tavern spell."
    def dr(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        cands = [d for d in g.db.pool_spells()
                 if d.tech_level <= hero.tavern_tier]
        if not cands:
            cands = list(g.db.pool_spells())
        # AMBIGUOUS: tier 范围未公布——按 ≤ 当前酒馆等级（与
        # SpellPool.draw_tavern 一致），空则全池
        available = [d.id for d in cands
                     if g.spell_pool.available(d.id) > 0]
        if available:
            sid = g.rng.choice(available, label="mystic_essence_spell")
            if not g.spell_pool.acquire(sid):
                raise GameStateError(
                    f"mystic essence acquire failed for {sid}")
        else:
            sid = g.rng.choice([d.id for d in cands],
                               label="mystic_essence_spell")
            # 池空: 生成不占池（作业单约定）
        g.pending_hand_add(hero, g.create_spell(sid, controller=hero))
    _chain_hook(m, "deathrattle", dr)


def _gift_fresh_perspective(game, m, gname):
    # "Deathrattle: Gain 2 free Refreshes."（XML 文本 "2"）
    def dr(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        hero.set(GameTag.FREE_REFRESH_REMAINING,
                 hero.get(GameTag.FREE_REFRESH_REMAINING, 0) + 2)
    _chain_hook(m, "deathrattle", dr)


def _gift_golemancy(game, m, gname):
    # "Deathrattle: Summon a Golem with this minion's stats."
    def dr(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        # AMBIGUOUS: data 导出无独立 "Golem" token 卡——按官方语义构造
        # 同属性 Golem（atk/max_health 快照），T1 token 不占池不回池
        golem = Minion("BG36_GOLEM_TOKEN", "Golem",
                       atk=source.atk, health=source.max_health,
                       tech_level=C.TOKEN_TECH_LEVEL)
        golem.game = g
        g.summon(hero, golem, position=source.zone_position)
    _chain_hook(m, "deathrattle", dr)


def _gift_offensive_sacrifice(game, m, gname):
    # "+10 Attack. Deathrattle: Give this minion's Attack to another
    #  friendly minion."（XML 文本 "+10 Attack"）
    m.add_buff(Buff(10, 0, dark_gift=gname))

    def dr(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        others = [x for x in hero.board if x is not source and not x.dead]
        if not others:
            return
        target = g.rng.choice(others, label="offensive_sacrifice_target")
        target.add_buff(Buff(source.atk, 0, dark_gift=gname))
    _chain_hook(m, "deathrattle", dr)


def _gift_defensive_sacrifice(game, m, gname):
    # "+10 Health. Deathrattle: Give this minion's max Health to another
    #  friendly minion."（XML 文本 "+10 Health"）
    m.add_buff(Buff(0, 10, dark_gift=gname))

    def dr(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        others = [x for x in hero.board if x is not source and not x.dead]
        if not others:
            return
        target = g.rng.choice(others, label="defensive_sacrifice_target")
        target.add_buff(Buff(0, source.max_health, dark_gift=gname))
    _chain_hook(m, "deathrattle", dr)


# ── Rally 追加（原生 rally 先触发）──

def _gift_charisma(game, m, gname):
    # "Rally: Get a random minion of your most common type."
    from hsrl2.actions.discover import GetRandomMinion

    def rally(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        common = DG.most_common_board_race(hero, g.rng)
        if common is None:
            return
        g.run_actions(GetRandomMinion(hero, race=common))
    _chain_hook(m, "rally", rally)


def _gift_consanguinity(game, m, gname):
    # "Rally: Get 2 Blood Gems." — Blood Gem = BG20_GEM（data 已验证，
    # 非池卡不占池）
    def rally(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        for _ in range(2):   # XML 文本 "2"
            g.pending_hand_add(hero, g.create_spell("BG20_GEM",
                                                    controller=hero))
    _chain_hook(m, "rally", rally)


def _gift_demonology(game, m, gname):
    # "Rally: Add a Fodder to your next 3 Refreshes."（XML 文本 "3"）
    # Fodder = Demon Fodder token（BG35_150t），refresh_tavern 消费
    def rally(source, g, ctx):
        hero = source.controller
        if hero is None:
            return
        # 协议 v2: (剩余刷新次数, 每次附加枚数)——同英雄多来源时
        # 次数累加、每次枚数取最大（保守合并; 无堆叠官方数据 AMBIGUOUS）
        prev = g._fodder_refresh_pending.get(hero, (0, 0))
        g._fodder_refresh_pending[hero] = (
            prev[0] + C.FODDER_REFRESHES, max(prev[1], 1))
    _chain_hook(m, "rally", rally)


# ── 直接获取 ──

def _gift_double_vision(game, m, gname):
    # "Get an extra copy of this." — plain copy 进手牌（不召唤）
    _plain_copy_to_hand(game, m, gname)


_DARK_GIFT_EFFECTS = {
    DG.OFFENSIVE_SACRIFICE: _gift_offensive_sacrifice,
    DG.DEFENSIVE_SACRIFICE: _gift_defensive_sacrifice,
    DG.ECHOING_VOICE: _gift_echoing_voice,
    DG.DOUBLE_VISION: _gift_double_vision,
    DG.PERSISTING_HORROR: _gift_persisting_horror,
    DG.HARPYS_TALONS: _gift_harpys_talons,
    DG.GILDING: _gift_gilding,
    DG.TORETHS_BLESSING: _gift_toreths_blessing,
    DG.JAWS_OF_DEATH: _gift_jaws_of_death,
    DG.REPLICATION: _gift_replication,
    DG.TIME_TURNING: _gift_time_turning,
    DG.AMALGAMATION: _gift_amalgamation,
    DG.BATTLE_SCARS_BIG: _make_counter_gift(3, 3, GameTag.COUNTER_BATTLECRIES,
                                            "battlecry_trigger", "minion"),
    DG.BATTLE_SCARS_SMALL: _make_counter_gift(2, 2, GameTag.COUNTER_BATTLECRIES,
                                              "battlecry_trigger", "minion"),
    DG.DEATHS_EMBRACE_BIG: _make_counter_gift(2, 2, GameTag.COUNTER_DEATHRATTLES,
                                              "deathrattle_trigger", "minion"),
    DG.DEATHS_EMBRACE_SMALL: _make_counter_gift(1, 1, GameTag.COUNTER_DEATHRATTLES,
                                                "deathrattle_trigger", "minion"),
    DG.SPELL_SIPHON_BIG: _make_counter_gift(3, 3, GameTag.TAVERN_SPELLS_CAST_THIS_GAME,
                                            "tavern_spell_cast", "spell"),
    DG.SPELL_SIPHON_SMALL: _make_counter_gift(2, 2, GameTag.TAVERN_SPELLS_CAST_THIS_GAME,
                                              "tavern_spell_cast", "spell"),
    DG.CHARISMA: _gift_charisma,
    DG.INCUBATION: _gift_incubation,
    DG.MYSTIC_ESSENCE: _gift_mystic_essence,
    DG.TARECGOSAS_BLESSING: _gift_tarecgosas_blessing,
    DG.STEADY_GROWTH: _gift_steady_growth,
    DG.FRESH_PERSPECTIVE: _gift_fresh_perspective,
    DG.INVULNERABILITY: _gift_invulnerability,
    DG.GOLEMANCY: _gift_golemancy,
    DG.SUNKEN_PERSISTENCE: _gift_sunken_persistence,
    DG.DEXTERITY_SMALL: _make_card_played_gift(2, 2),
    DG.DEXTERITY_BIG: _make_card_played_gift(4, 4),
    DG.DEMONOLOGY: _gift_demonology,
    DG.TOXICITY: _gift_toxicity,
    DG.RESISTANCE: _gift_resistance,
    DG.HOSTILITY: _gift_hostility,
    DG.TITANIC_STRENGTH: _gift_titanic_strength,
    DG.FORTITUDE: _gift_fortitude,
    DG.SHARPENED_SWORD: _make_card_played_gift(3, 0),
    DG.TOUGHENED_SHIELD: _make_card_played_gift(0, 3),
    DG.FURTIVENESS: _gift_furtiveness,
    DG.CONSANGUINITY: _gift_consanguinity,
    DG.TRANSCENDENCE: _gift_transcendence,
    DG.AFFINITY: _gift_affinity,
    DG.ADMIRATION: _gift_admiration,
}
# 分派表必须覆盖窗口表全部非 DEFERRED gift——缺失即引擎 bug，禁止静默
_missing = (set(DG.GIFT_WINDOWS) - set(DG.DEFERRED_GIFTS)
            - set(_DARK_GIFT_EFFECTS))
assert not _missing, f"dark gift handlers missing: {_missing}"


_KEYWORD_TAG_MAP = {
    "taunt": GameTag.TAUNT,
    "divine_shield": GameTag.DIVINE_SHIELD,
    "windfury": GameTag.WINDFURY,
    "poisonous": GameTag.POISONOUS,
    "venomous": GameTag.VENOMOUS,
    "reborn": GameTag.REBORN,
    "deathrattle": GameTag.DEATHRATTLE,
    "battlecry": GameTag.BATTLECRY,
    "cleave": GameTag.CLEAVE,
    "magnetic": GameTag.MAGNETIC,
    "start_of_combat": GameTag.START_OF_COMBAT,
    "rally": GameTag.RALLY,
    "activate": GameTag.ACTIVATE,
    "stealth": GameTag.STEALTH,
}
