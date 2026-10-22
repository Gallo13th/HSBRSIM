"""Hero — 战棋玩家英雄（金币/护甲/酒馆等级/手牌/棋盘/酒馆展示）。"""

from __future__ import annotations

from typing import Dict, List, Optional, TYPE_CHECKING

import hsrl2.constants as C
from hsrl2.entity import Entity
from hsrl2.events import Listener
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import CardType, GameTag, Zone

if TYPE_CHECKING:
    from hsrl2.game import Game


class Hero(Entity):
    def __init__(self, card_id: str, name: str = "", *,
                 base_health: int = C.HERO_BASE_HEALTH, armor: int = 0):
        super().__init__(card_id, name, card_type=CardType.HERO)
        self.set(GameTag.HEALTH2, base_health)
        # BASE_HEALTH 供 Entity.max_health 读取（"regain X Health" 类效果
        # 需封顶值；2026-09-01 审计: Hero 此前 max_health 恒 0）
        self.set(GameTag.BASE_HEALTH, base_health)
        self.set(GameTag.ARMOR, armor)
        self.set(GameTag.TAVERN_TIER, 1)
        self.set(GameTag.UPGRADE_COST, C.BASE_UPGRADE_COSTS[2])
        self.set(GameTag.GOLD, 0)
        # 区域容器
        self.board: List[Minion] = []
        self.hand: List[Entity] = []
        self.tavern: List[Entity] = []
        self.graveyard: List[Entity] = []
        self.trinkets: List[Entity] = []
        self.quest: Optional[Entity] = None       # 当前任务实体（无任务=None）
        self.quest_rewards: List[Entity] = []     # 任务奖励实体（hook 已接线）
        # 上一场战斗的战前棋盘快照（RULES §4.8a——幽灵阵容/对手引用
        # 数据源）。必须在 __init__ 里定义: 招募期可读的对手 API
        # （Murloc Holmes "your next opponent had last combat"）在第 1
        # 回合就会读到它，而 end_recruit_phase 要到首次战斗前才赋值。
        self.last_combat_board: List[Minion] = []
        # F-06: 本回合元素打出数（hero 级公开属性；每回合
        # `Game._begin_recruit_for` 清零，`Game.play_minion` 普通打出路径
        # 递增；读取点 `Game.elementals_played_this_turn(hero)`。
        # 37.0 Conflagration/Firelands "Improved by each Elemental you
        # played this turn" 的数据源；与游戏长 COUNTER_ELEMENTALS_PLAYED
        # 独立（后者语义 "this game"，不改写）。
        self.elementals_played_this_turn: int = 0
        # F-07: 隐藏 Deity（旧神）目标状态（37.0 Aberration 子系统）。
        # 惰性创建（`Game.deity(hero)`）；官方开局随机二选一
        # C'Thun/Y'Shaarj，选择与进度/属性见 `hsrl2/deity.py`。
        self.deity = None
        # F-15: 官方 `BG_OldGod` sigil（Secret Deity [DNT]）显式注入状态；
        # 默认 None，未注入时零副作用（只记录身份/进度，不改变 F-07）。
        self.deity_sigil = None
        # F-08: 本局已弃牌数（Discard 子系统；"each card you've discarded
        # this game" 家族读取点——Parasitic Fleshling / Harbinger Aph'lass）
        self.cards_discarded_this_game: int = 0
        self._quest_progress: int = 0
        self._quest_reward_id: Optional[str] = None
        # 任务已完成（发奖后置位）——`Game.advance_quest_progress` 的唯一
        # 二次计分闸（QUEST_DEFERRED_SPEC §2.1 蓝图; 2026-09-18 落地）。
        self._quest_completed: bool = False
        # ── 额外触发配额（RULES §6.20，2026-09-02 主线原语）──
        # 脚本侧声明（永久额度）: hero.extra_triggers[key] = N
        #   "eot_extra"        每个己方 EoT 效果额外触发 N 次
        #   "soc_extra"        每个己方 SoC 效果额外触发 N 次
        #   "soc_first"        每场战斗**前 N 个**己方 SoC 效果额外触发 1 次
        #   "dr_first"         每场战斗**前 N 个**己方亡语额外触发 1 次
        #   "spell_first"      每回合**前 N 个**己方法术额外结算 1 次
        #   "spellcraft_first" 同上，仅限法术塑造（Spellcraft）法术
        #   "hp_uses"          英雄技能每回合可用次数 +N
        #   "bc_times"/"bc_race" 指定种族随从的战吼额外触发 N 次
        # 引擎在对应触发点消费"已用次数"（extra_trigger_used），
        # 每回合/每场战斗开始时重置（见 _begin_recruit_for /
        # CombatScheduler.run）。
        self.extra_triggers: Dict[str, int] = {}
        self.extra_trigger_used: Dict[str, int] = {}
        # ── 家族"给予者加成"读取点（RULES §7.4.15，2026-09-13 主线原语）──
        # `hero.giver_bonus_rules: [(source, 基础卡 id, {atk,health,copies})]`
        # ——Portrait 类饰品对**载荷效果量**的加成（"Your <卡名>s give an
        # extra +X/+Y" / "give an extra copy"）。载荷脚本经
        # `game.giver_bonus(hero, source.card_id)` 读取（SOP §12 禁止读
        # 他脚本私有属性）；金色载荷按基础卡 id 归一、数值仍取各自
        # CardDef；只汇总 `source` 仍在场（trinkets/quest_rewards/board）
        # 的规则——效果实体被替换即失效。仅写入方 = 绑定该饰品的英雄
        # （owner 隔离）。
        self.giver_bonus_rules: list = []
        # ── 家族"行为开关"读取点（RULES §7.4.16，2026-09-13 主线原语）──
        # `hero.family_flags: [(source, 基础卡 id, 开关名)]`——Portrait 类
        # 饰品对载荷**行为/分支**的改写（§7.4.15 只承载**数值**加成），
        # 如 "Your Bristlebachs play Blood Gems on **all friendly
        # minions**"（Bristlebach Portrait `BG32_MagicItem_274`）。载荷
        # 脚本经 `game.family_flag(hero, source.card_id, 开关名)` 读取
        # （SOP §12 禁止读他脚本私有属性）；金色载荷按基础卡 id 归一；
        # 只汇总 `source` 仍在场（trinkets/quest_rewards/board）的规则
        # ——效果实体被替换即失效（同 §7.4.15 口径）。
        self.family_flags: list = []
        # ── 家族"类型身份改写"读取点（RULES §7.4.16 类型维度，2026-09-21）──
        # `hero.family_races: [(source, 基础卡 id, frozenset[Race])]`——
        # Portrait 类饰品对载荷**类型身份**的改写（"Your Brann
        # Bronzebeards are both Murlocs and Dragons" / "Your Whelp
        # Smugglers are Dragons" / "Your Lightfang Enforcers have all
        # minion types" / "Your Drakkari Enchanters are both Mechs and
        # Elementals"）。读取点 = `Minion.races`（owner 视角: 棋盘/手牌/
        # 酒馆/发现）与 `Game.effective_races`（CardDef 候选过滤）。
        # 只汇总 `source` 仍在场（trinkets/quest_rewards/board）的规则
        # ——效果实体被替换即失效（同 `family_flags` 口径）。
        self.family_races: list = []
        # ── 吞噬目标选择策略读取点（RULES §7.4.16 扩展，2026-09-19 主线原语）──
        # `hero.consume_policies: [(source, 策略名)]`——"Your **Demons**
        # always consume the **highest-Health** minion in the Tavern"
        # （Implicator Portrait `BG32_MagicItem_824`）。与 `family_flags`
        # 的区别: 键是**种族范围**而非卡家族 id（消费方为不同家族的
        # 恶魔吞噬路径，见 `Game.pick_consume_victim`）。只汇总 `source`
        # 仍在场（trinkets/quest_rewards/board）的策略——效果实体被替换/
        # 移除即失效（同 §7.4.15/§7.4.16 口径）。仅写入方 = 绑定该饰品的
        # 英雄（owner 隔离）。
        self.consume_policies: list = []
        # ── 英雄技能槽（RULES §9.3，2026-09-02 主线原语）──
        # 第二技能槽: 异变/任务奖励在 on_bind 中声明（如
        # BG32_Anomaly_001 "Start with 'Growing Collection' as your
        # second Hero Power"）; 每技能独立的每回合/每局使用计数
        # （主技能仍保留 HERO_POWER_USED_THIS_TURN/USES_THIS_GAME 累计 tag）
        self._second_power_id: Optional[str] = None
        self._power_uses_this_turn: Dict[str, int] = {}
        self._power_uses_this_game: Dict[str, int] = {}
        # ── 免费随从购买配额（RULES §7.4.4，2026-09-02 主线原语）──
        # 每来源独立记账: [{source, count, used, race, keyword, turn}]
        # （旧的单 counter + 限定 tag 模型在多来源并存时互相覆盖——
        #  对抗审查 MAJOR: "海盗免费"与"战吼免费"退化为"海盗战吼才免费"）。
        # `turn` 标记写入回合，跨回合自动失效（饰品被替换后不残留）。
        self._free_minion_buy_quotas: list = []
        # ── 饰品获得记账（RULES §7.4.2/§7.4.3，2026-09-02 主线修复）──
        # **每英雄独立**: "a Trinket **you** already have" 是 per-player
        # 口径——对手持有的同名饰品不得从我的候选池剔除（旧实现用
        # game 级集合，实测对手拿到 X 后我的池里 X 永久消失）。
        self.trinkets_granted: set = set()
        # ── tier 维度光环（RULES §6.19，2026-09-02 主线原语）──
        # "Your minions from Tier N or lower have +X/+Y"（Horde Keychain
        # 等）。{source_uuid: (source_entity, max_tier, atk, health)}——
        # 读取点在 `Entity._aura_atk/_aura_health`（仅棋盘随从）;
        # 读取时校验 source 仍属于该英雄 → 饰品被替换即自动失效。
        self.tier_auras: dict = {}
        # ── 卡家族光环（RULES §6.19，2026-09-02 主线原语）──
        # "your <卡名家族> have +X/+Y this game"（Eternal Portrait
        # BG36_MagicItem_216 等）: {key: (source, frozenset(card_ids),
        # atk, health)}——读取点 `Entity._aura_atk/_aura_health`（任意区域
        # "wherever this is"）; 家族按 TRIPLE_BASE_CARD_ID 回落匹配（金色
        # 实体算同族）; source 离场即失效。**增量式**注册: 同 key 重复调用
        # 按差值更新（累积型文本如"每个友方亡灵死亡 +1/+1"）。
        self.card_auras: dict = {}
        # ── "指定来源授予的属性跨战斗持久化"读取点（RULES §3.5 例外 4，
        # 2026-09-18 主线原语）──
        # `hero.persist_sources: [(source, frozenset(card_ids))]`——Portrait
        # 类饰品把**载荷的 give** 标为跨战斗持久（Cyclist Portrait
        # `BG36_MagicItem_362` "Your Showy Cyclists' Deathrattles give
        # **permanent** stats"）。载荷脚本经
        # `game.minion_persist_source(hero, minion)` 读取（SOP §12 禁止读
        # 他脚本私有属性）→ 命中则 `Buff(persist=True)`; 家族按
        # `TRIPLE_BASE_CARD_ID` 回落匹配（金色同族）; 只汇总 `source`
        # 仍在场（trinkets/quest_rewards/board）的规则——效果实体被替换/
        # 移除即失效（同 §7.4.15/§7.4.16 口径）。仅写入方 = 绑定该饰品的
        # 英雄（owner 隔离）。
        self.persist_sources: list = []
        # ── "额外关键词展示位" 与 "条件化购买价" 规则（RULES §7.4.5/§7.4.9）
        # [ (source, keywords, count) ] / [ (source, predicate, cost) ] ——
        # source 离场（饰品被替换）即失效
        self._tavern_extra_keyword: list = []
        self._tavern_cost_rules: list = []
        # 按种族的三连阈值: {Race: n}（Designer Eyepatch
        # BG30_MagicItem_439 "only need 2 copies of a Pirate"; Race.ALL 命中一切）
        self.triple_threshold_race: dict = {}
        # ── "Your <X>s' Spellcrafts are permanent" 规则（2026-09-02）──
        # [(source_entity, predicate(source_minion) -> bool)]: 被动实体
        # （饰品/奖励）声明的永久化规则; 生成法术时按来源随从匹配。
        self.permanent_spellcraft_rules: list = []

    # ── 额外触发配额 API ──

    def clear(self, tag: GameTag) -> None:
        """覆盖 Entity.clear。

        清 `HERO_POWER_USED_THIS_TURN` 语义 = "本回合技能计数归零"
        （引擎 `_begin_recruit_for` 每回合重置、`replace_hero_power`
        换技能重置，两处都经此点）→ 每技能独立计数（RULES §9.3）同步
        清零，避免"清 tag 后主技能恢复但第二技能仍被记为已用"。
        """
        super().clear(tag)
        if tag == GameTag.HERO_POWER_USED_THIS_TURN:
            self._power_uses_this_turn = {}

    def extra_trigger(self, key: str) -> int:
        """永久额度（脚本声明值；未声明 = 0）。"""
        return int(self.extra_triggers.get(key, 0))

    def consume_extra_trigger(self, key: str) -> bool:
        """消费一次"前 N 次"配额: 还有剩余则记一次已用并返回 True。"""
        used = int(self.extra_trigger_used.get(key, 0))
        if used >= self.extra_trigger(key):
            return False
        self.extra_trigger_used[key] = used + 1
        return True

    def reset_extra_trigger_uses(self, *keys: str) -> None:
        for key in keys:
            self.extra_trigger_used[key] = 0

    # ── 属性 ──

    @property
    def health(self) -> int:
        return self.get(GameTag.HEALTH2, 0)

    @health.setter
    def health(self, value: int) -> None:
        self.set(GameTag.HEALTH2, max(0, value))

    @property
    def armor(self) -> int:
        return self.get(GameTag.ARMOR, 0)

    @armor.setter
    def armor(self, value: int) -> None:
        self.set(GameTag.ARMOR, max(0, value))

    @property
    def gold(self) -> int:
        return self.get(GameTag.GOLD, 0)

    @gold.setter
    def gold(self, value: int) -> None:
        """回合内收入可超过基础量，持有上限 99（RULES §1.4）。

        金币**增加**时广播 `gold_gained(hero=, amount=)`（观察点覆盖
        所有收入路径: 回合收入 / 售卖 / `GainGold` / 脚本直改——
        `BG32_MagicItem_350` Splinter of Aurum "After you gain Gold"）。
        上限截断后的实际增量才是 amount（99 上限溢出不算获得）。
        """
        before = self.get(GameTag.GOLD, 0)
        after = min(max(0, value), C.GOLD_HOLD_CAP)
        self.set(GameTag.GOLD, after)
        if after > before:
            game = getattr(self, "game", None)
            if game is not None:
                game.events.fire(game, "gold_gained", hero=self,
                                 amount=after - before)

    @property
    def tavern_tier(self) -> int:
        return self.get(GameTag.TAVERN_TIER, 1)

    @property
    def upgrade_cost(self) -> int:
        return self.get(GameTag.UPGRADE_COST, C.BASE_UPGRADE_COSTS[2])

    @property
    def is_alive(self) -> bool:
        return self.health + self.armor > 0

    @property
    def frozen_tavern(self) -> bool:
        return self.has(GameTag.FROZEN)

    @property
    def income_cap(self) -> int:
        """每回合基础收入上限（默认 10; Strike Oil 类效果递增）。"""
        return C.GOLD_INCOME_CAP + self.get(GameTag.INCOME_CAP_BONUS, 0)

    # ── 伤害（先护甲后生命, RULES §1.3）──

    def take_damage(self, amount: int) -> int:
        if amount <= 0:
            return 0
        # 异变 BG27_Anomaly_006 "hero can only take 1 damage at a time"
        cap = getattr(self, "_damage_flat_cap", None)
        if cap is not None:
            amount = min(amount, cap)
        health_before = self.health
        armor_before = self.armor
        absorbed_by_armor = min(self.armor, amount)
        self.armor = self.armor - absorbed_by_armor
        remaining = amount - absorbed_by_armor
        if remaining > 0:
            self.health = self.health - remaining
        # 英雄受伤事件（护甲吸收也算受伤 — 官方 Floating Watcher 语义;
        # 携带伤害前生命/护甲——Rewind 类效果（Soul Rewinder）据以
        # 全量回溯该伤害实例，含护甲部分）
        if self.game is not None:
            from hsrl2.events import HERO_DAMAGE_TAKEN
            self.game.events.fire(self.game, HERO_DAMAGE_TAKEN,
                                  hero=self, amount=amount,
                                  health_before=health_before,
                                  armor_before=armor_before)
        return amount

    # ── 棋盘辅助 ──

    def living_minions(self) -> List[Minion]:
        return [m for m in self.board if not m.dead]

    def board_full(self) -> bool:
        return len(self.board) >= C.BOARD_SIZE

    def hand_full(self) -> bool:
        return len(self.hand) >= C.HAND_SIZE

    def add_to_hand(self, entity: Entity) -> bool:
        """满手牌返回 False — 调用方决定排队等待或丢弃（RULES §3.3: 等待）。

        入手钩子: on_enter_hand（Bream Counter 手牌联动 / Aureate
        Laureate 恒金 / Search Through Time 锁定类效果的触发点）。
        """
        if self.hand_full():
            return False
        entity.zone = Zone.HAND
        self.hand.append(entity)
        if self.game is not None:
            # "获得一张牌"事件（Trusty Crowbar `BG35_MagicItem_713`
            # "After you get a card" 类; 引擎此前只有实体级
            # `on_enter_hand`，无 hero 级"获得"广播——2026-09-02）
            self.game.events.fire(self.game, "card_gained",
                                  hero=self, card=entity)
            if isinstance(entity, Minion):
                # 统一“获得随从”入手事件（单点；BG32_234 Dastardly
                # Drust 等按 Pirate 过滤的监听器使用）——只在真正进手
                # 时广播一次，购买路径不会与 minion_bought 重复计数。
                self.game.minion_gained(self, entity)
            self.game.run_script_hook(entity, "on_enter_hand")
        return True
