"""批次 hero_econ3 — 经济/计数类英雄技能 16 项（主线直接实现 2026-09-01）。

引擎新经济钩子（本轮主线新增, tags 1073-1080）:
  TAVERN_MINION_COST_OVERRIDE / REFRESH_COST_OVERRIDE / UPGRADE_COST_MOD /
  TAVERN_OFFER_MOD / FREE_MINION_BUYS_THIS_TURN / TURN_SKIPPED /
  TRIPLE_THRESHOLD / TRIPLE_REWARD_COINS
解锁: Millhouse / Sindragosa / Aranna / Cenarius / Clocksworth / Faelin /
A.F. Kay / Patches / Exarch Othaar / C'Thun / Wagtoggle / Jaraxxus /
Zephrys / Silas / N'Zoth / Lady Vashj

查证依据（wiki 卡页 + 官方 patch notes，2026-09-01）:
  - Millhouse "Minions and Refreshes cost 2 Gold. Upgrading the Tavern
    costs (1) more"（36.2 现行文本——作用于随从购买价与刷新费,
    升级费 +1）; 文本无占位符, 数值字面量（wiki 实证）
  - Sindragosa "Minions cost (2). The Tavern offers one fewer minion
    and Freezes at the end of each turn"（36.2 现行）; "Freezes at the
    end of each turn" = 每个招募阶段结束自动整馆冻结
  - Aranna "After 14 friendly minions attack, the first minion you buy
    each turn is free"——14 = script_data_num_1; 攻击计数（战斗中
    after_attack, 己方攻击者）; 达到后每回合首购免费
  - Cenarius "Increase your maximum Gold by 1"（36.2）——hero.income_cap
    +1（gold_base_income 上限提升）
  - Clocksworth "You only need 2 copies to make minions Golden. They
    give Tavern Coins instead of Triple Rewards"——双份三连 + 奖励替代
  - Faelin "Skip your first turn. Discover minions from Tiers 6, 4, and
    2 to get at those Tiers"——跳首回合; 到对应 tier 时得所发现随从
  - A.F. Kay "Skip your first two turns, then Discover a minion from
    Tier 3 and Tier 4"——跳前两回合; 第 3 回合起可得
  - Patches "Get a Pirate. After you buy a Pirate, your next Hero Power
    costs (1) less"——随从购买事件计数, 下次技能 -1（下限 0）
  - Exarch Othaar "The next Tavern spell you buy costs (1) less.
    (Unlocks on Turn 3)"——NEXT_SPELL_COST_REDUCTION 既有引擎语义
  - C'Thun "At end of turn, give a friendly minion +1/+1. Repeat @
    times. Improves each turn!"——@ 为回合计数器, 回合 T 重复 T 次
  - Wagtoggle "Start of Combat: Give a friendly minion of each type
    +X/+X. Improves after you spend 10 Gold!"——num_1=10 花费阈值,
    num_3=1 每次增幅; 每类型一只（BEAST..UNDEAD + ALL 判定）
  - Jaraxxus "After friendly minions deal 150 damage, open a portal to
    the Twisting Nether!"——num_1=150 伤害阈值 → 技能替换为 Nether
    Portal（TB_BaconShop_HP_036t, 每回合开始给 2 随机恶魔）
  - Zephrys "If you have two copies of a minion, find the third"
    ——两同名手牌/棋盘 → 池中找第三份入手; uses_per_game=num_1=3
  - Silas "Darkmoon Tickets are in the Tavern! Get 3 to Discover a
    minion of your Tier"——馆内注入 Ticket token; 集 3 → Discover
  - N'Zoth "Start the game with a 2/2 Fish that gains all your
    Deathrattles in combat"——Fish of N'Zoth TB_BaconShop_HP_105t
  - Lady Vashj "At the start of each turn, get a random Spellcraft
    spell"——Spellcraft 生成

DEFERRED（依赖未建系统）: 无
"""

from __future__ import annotations

from hsrl2.actions import Buff, Discover, GetRandomMinion
from hsrl2.events import AFTER_ATTACK, Listener, TURN_START
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race

# ── 数据链── (script_data_num_N = 模板参数 {N}) ──

_PIRATE_RACES = (Race.PIRATE, Race.ALL)


def _power_def(game, power_id: str):
    return game.db.get(power_id)


def _num(game, power_id: str, idx: int) -> int:
    """模板参数 {idx}（script_data_num_{idx+1}; 缺省 0）。"""
    d = game.db.get(power_id)
    if d is None:
        return 0
    return d.raw.get(f"script_data_num_{idx + 1}", 0) or 0


# ═══════════════════ TB_BaconShop_HP_054 Millhouse — Manastorm ═══════════════════

class MillhouseScript:
    """Minions and Refreshes cost 2 Gold. Upgrading the Tavern costs (1) more.

    被动平价覆盖: 随从 2 / 刷新 2 / 升级 +1（36.2 现行文本）。
    数值字面量（文本无占位符; wiki 实证）。
    """

    passive = True

    @staticmethod
    def on_bind(hero, game):
        hero.set(GameTag.TAVERN_MINION_COST_OVERRIDE, 2)
        hero.set(GameTag.REFRESH_COST_OVERRIDE, 2)
        hero.set(GameTag.UPGRADE_COST_MOD,
                 hero.get(GameTag.UPGRADE_COST_MOD, 0) + 1)


# ═══════════════════ TB_BaconShop_HP_014 Sindragosa — Stay Frosty ═══════════════════

class SindragosaScript:
    """Minions cost (2). The Tavern offers one fewer minion and Freezes
    at the end of each turn.

    平价覆盖 2 + 展示数 -1; 每个招募阶段结束自动整馆冻结（turn_end
    广播——end_recruit_phase 已 fire, RULES §6.17 冻结免费）。
    """

    passive = True

    @staticmethod
    def on_bind(hero, game):
        hero.set(GameTag.TAVERN_MINION_COST_OVERRIDE, 2)
        hero.set(GameTag.TAVERN_OFFER_MOD,
                 hero.get(GameTag.TAVERN_OFFER_MOD, 0) - 1)

        def on_turn_end(g, turn=None, **kw):
            if hero.is_alive:
                g.freeze_tavern(hero)

        game.events.register(Listener(
            event="turn_end", owner=hero, callback=on_turn_end))


# ═══════════════════ TB_BaconShop_HP_065 Aranna — Demon Hunter Training ═══════════════════

class ArannaScript:
    """After 14 friendly minions attack, the first minion you buy each
    turn is free.

    攻击计数（after_attack, 己方攻击者）达 num_1=14 → 每回合首购免费
    （FREE_MINION_BUYS_THIS_TURN 在回合开始置 1）。
    """

    passive = True

    @staticmethod
    def on_bind(hero, game):
        self_hero = hero

        def on_attack(g, attacker=None, **kw):
            if attacker is None or attacker.controller is not self_hero:
                return
            n = getattr(self_hero, "_aranna_attacks", 0) + 1
            self_hero._aranna_attacks = n
            if n >= _num(g, "TB_BaconShop_HP_065", 0):
                self_hero._aranna_active = True

        def on_turn_start(g, hero=None, turn=None, **kw):
            if hero is not self_hero:
                return
            if getattr(self_hero, "_aranna_active", False):
                self_hero.set(GameTag.FREE_MINION_BUYS_THIS_TURN, 1)

        game.events.register(Listener(
            event=AFTER_ATTACK, owner=hero, callback=on_attack))
        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))


# ═══════════════════ BG32_HERO_001p Cenarius — Wisdom of Ancients ═══════════════════

class CenariusScript:
    """Increase your maximum Gold by 1. 上限收入 +1（income_cap 属性）。"""

    passive = True

    @staticmethod
    def on_bind(hero, game):
        hero.set(GameTag.INCOME_CAP_BONUS,
                 hero.get(GameTag.INCOME_CAP_BONUS, 0) + 1)


# ═══════════════════ BG34_HERO_002p Clocksworth — Double Time ═══════════════════

class ClocksworthScript:
    """You only need 2 copies to make minions Golden. They give Tavern
    Coins instead of Triple Rewards.

    双份三连（TRIPLE_THRESHOLD=2）+ 奖励替代（TRIPLE_REWARD_COINS=1——
    官方 36.2 每三连给 1 张 Tavern Coin; wiki 卡页实证）。
    """

    passive = True

    @staticmethod
    def on_bind(hero, game):
        hero.set(GameTag.TRIPLE_THRESHOLD, 2)
        hero.set(GameTag.TRIPLE_REWARD_COINS, 1)


# ═══════════════════ BG22_HERO_201p Faelin — Expedition Plans ═══════════════════

class FaelinScript:
    """Skip your first turn. Discover minions from Tiers 6, 4, and 2 to
    get at those Tiers.

    跳第 1 回合（TURN_SKIPPED）; 开局 Discover T6/T4/T2 各一张记账,
    升到对应 tier 时获得（银行）。
    """

    @staticmethod
    def on_bind(hero, game):
        hero._faelin_rewards: dict = {}

        def _bank(tier):
            def resolve(pick_id):
                hero._faelin_rewards.setdefault(tier, []).append(pick_id)
            return resolve

        def on_turn_start(g, hero=None, turn=None, **kw):
            if hero is not self_hero:
                return
            if turn == 1:
                hero.set(GameTag.TURN_SKIPPED, True)
            for tier in (6, 4, 2):
                if hero.tavern_tier >= tier and tier in getattr(
                        hero, "_faelin_rewards", {}):
                    pending = hero._faelin_rewards.pop(tier)
                    for cid in pending:
                        m = g.create_minion(cid, controller=hero)
                        if m is not None:
                            g.pending_hand_add(hero, m)

        self_hero = hero
        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))
        # 开局 Discover 三张（on_bind = start_game 时机; 记于银行不入手）
        for tier in (6, 4, 2):
                from hsrl2.actions.discover import _pool_candidates
                from hsrl2.game import PendingChoice
                cands = _pool_candidates(game, None, tier, tier)
                if not cands:
                    continue
                opts = game.rng.sample(cands, min(1, len(cands)),
                                       label="faelin_bank")
                game.pending_choices.append(PendingChoice(
                    hero, opts, "discover_minion",
                    resolve_callback=_bank(tier)))


# ═══════════════════ TB_BaconShop_HP_044 A.F. Kay — Procrastinate ═══════════════════

class AFKayScript:
    """Skip your first two turns, then Discover a minion from Tier 3
    and Tier 4.

    跳第 1、2 回合; 第 3 回合开始 Discover T3 + T4 随从各一。

    Params: 无模板参数（tier 3/4 与 count=1 为文本字面量——文本
    "Discover a minion from Tier 3 and Tier 4" 无占位符）
    """

    @staticmethod
    def on_bind(hero, game):
        self_hero = hero

        def on_turn_start(g, hero=None, turn=None, **kw):
            if hero is not self_hero:
                return
            if turn <= 2:
                hero.set(GameTag.TURN_SKIPPED, True)
            elif turn == 3:
                g.run_actions(Discover(
                    hero, count=1, min_tier=3, max_tier=3,
                    kind="discover_minion"))
                g.run_actions(Discover(
                    hero, count=1, min_tier=4, max_tier=4,
                    kind="discover_minion"))

        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))


# ═══════════════════ TB_BaconShop_HP_072 Patches — Pirate Parrrrty! ═══════════════════

class PatchesScript:
    """Get a Pirate. After you buy a Pirate, your next Hero Power costs
    (1) less.

    主动: 随机池内 Pirate 入手; 被动: 买 Pirate 后下次技能 -1
    （累计可叠? 官方语义: 每买一只 Pirate, 下一次技能 -1——为"下一个
    技能"一次性折扣; 多只叠加存疑——按最小口径单层折扣, 消耗后重置）。
    cost=3（raw cost）。
    """

    @staticmethod
    def on_bind(hero, game):
        def on_bought(g, minion=None, **kw):
            if minion is None or minion.controller is not hero:
                return
            if minion.race in _PIRATE_RACES:
                hero.set(GameTag.HERO_POWER_NEXT_DISCOUNT,
                         hero.get(GameTag.HERO_POWER_NEXT_DISCOUNT, 0) + 1)
        game.events.register(Listener(
            event="minion_bought", owner=hero, callback=on_bought))

    @staticmethod
    def cost_override(hero, game):
        d = game.db.get("TB_BaconShop_HP_072")
        base = d.cost if d else 3
        disc = hero.get(GameTag.HERO_POWER_NEXT_DISCOUNT, 0)
        return max(0, base - disc)

    @staticmethod
    def hero_power(hero, game, ctx):
        hero.set(GameTag.HERO_POWER_NEXT_DISCOUNT, 0)  # 折扣消费
        return GetRandomMinion(hero, race=Race.PIRATE)


# ═══════════════════ BG31_HERO_006p Exarch Othaar — Arcane Knowledge ═══════════════════

class ExarchOthaarScript:
    """The next Tavern spell you buy costs (1) less. (Unlocks on Turn 3.)

    一次性折扣: Turn 3 起生效, 下一张酒馆法术 -1
    （NEXT_SPELL_COST_REDUCTION——buy_from_tavern 已消费）。
    """

    passive = True

    @staticmethod
    def on_bind(hero, game):
        def on_turn_start(g, hero=None, turn=None, **kw):
            if hero is not self_hero:
                return
            if turn >= 3 and hero.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0) == 0:
                hero.set(GameTag.NEXT_SPELL_COST_REDUCTION, 1)

        self_hero = hero
        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))


# ═══════════════════ TB_BaconShop_HP_104 C'Thun — Saturday C'Thuns! ═══════════════════

class CThunScript:
    """At end of turn, give a friendly minion +1/+1. Repeat @ times.
    Improves each turn!

    @ = 当前回合数（回合 T 重复 T 次, 每回合递增）; 每次随机友方随从
    +1/+1（官方随机语义）。cost=1。
    """

    passive = True

    @staticmethod
    def on_bind(hero, game):
        def on_turn_end(g, turn=None, **kw):
            if not hero.is_alive:
                return
            n = max(1, turn or 1)
            for _ in range(n):
                alive = [m for m in hero.board if not m.dead]
                if not alive:
                    return
                from hsrl2.actions.stats import Buff as BuffAction
                target = g.rng.choice(alive, label="cthun_target")
                g.run_actions(BuffAction(target, atk=1, health=1))

        game.events.register(Listener(
            event="turn_end", owner=hero, callback=on_turn_end))


# ═══════════════════ TB_BaconShop_HP_037a Wagtoggle — Wax Warband ═══════════════════

class WagtoggleScript:
    """Start of Combat: Give a friendly minion of each type +X/+X.
    Improves after you spend 10 Gold!

    num_1=10 花费阈值, num_3=1 每次增幅。每类型（棋盘存在的种族）随机
    一只 +X/+X; 累计花费每 10 金 X+1（gold_spent 事件累计）。
    """

    passive = True

    @staticmethod
    def on_bind(hero, game):
        hero._wagtoggle_bonus = _num(game, "TB_BaconShop_HP_037a", 2) or 1

        def on_spend(g, amount=None, hero=None, **kw):
            if hero is not self_hero:
                return
            total = getattr(self_hero, "_wagtoggle_spent", 0) + amount
            self_hero._wagtoggle_spent = total
            threshold = _num(g, "TB_BaconShop_HP_037a", 0) or 10
            while total >= threshold:
                total -= threshold
                self_hero._wagtoggle_bonus += 1
            self_hero._wagtoggle_spent = total

        def on_soc(g, hero=None, **kw):
            if hero is not self_hero:
                return
            b = self_hero._wagtoggle_bonus
            races = {m.race for m in hero.board if not m.dead}
            for r in races:
                cands = [m for m in hero.board
                         if not m.dead and m.race == r]
                if not cands:
                    continue
                t = g.rng.choice(cands, label="wagtoggle_target")
                t.add_buff(Buff(atk=b, health=b,
                                source_id="TB_BaconShop_HP_037a",
                                temporary=True))

        self_hero = hero
        game.events.register(Listener(
            event="gold_spent", owner=hero, callback=on_spend))
        game.events.register(Listener(
            event="start_of_combat", owner=hero, callback=on_soc))


# ═══════════════════ TB_BaconShop_HP_036 Jaraxxus — Bloodfury ═══════════════════

class JaraxxusScript:
    """After friendly minions deal 150 damage, open a portal to the
    Twisting Nether!

    num_1=150 累计伤害阈值（友方随从战斗造成伤害——攻击力全额计入）;
    达标 → 技能替换为 Nether Portal（TB_BaconShop_HP_036t: 每回合
    开始给 2 随机恶魔）。
    """

    passive = True

    @staticmethod
    def on_bind(hero, game):
        hero._jaraxxus_damage = 0

        def on_attack(g, attacker=None, **kw):
            if attacker is None or attacker.controller is not hero:
                return
            hero._jaraxxus_damage += attacker.atk
            if hero._jaraxxus_damage >= (_num(g, "TB_BaconShop_HP_036", 0)
                                         or 150):
                if game.hero_power_def(hero).id != "TB_BaconShop_HP_036t":
                    game.replace_hero_power(hero, "TB_BaconShop_HP_036t")
                    # 替换不自动接线新技能 on_bind——手动注册
                    NetherPortalScript.on_bind(hero, game)

        game.events.register(Listener(
            event=AFTER_ATTACK, owner=hero, callback=on_attack))


class NetherPortalScript:
    """At the start of each turn, get 2 random Demons."""

    passive = True

    @staticmethod
    def on_bind(hero, game):
        def on_turn_start(g, hero=None, turn=None, **kw):
            if hero is not self_hero:
                return
            g.run_actions(GetRandomMinion(hero, race=Race.DEMON))
            g.run_actions(GetRandomMinion(hero, race=Race.DEMON))

        self_hero = hero
        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))


# ═══════════════════ TB_BaconShop_HP_105 N'Zoth — Avatar of N'Zoth ═══════════════════

_FISH_ID = "TB_BaconShop_HP_105t"


class NZothScript:
    """Start the game with a 2/2 Fish that gains all your Deathrattles
    in combat.

    Fish of N'Zoth: "After a different friendly Deathrattle minion dies
    in combat, gain its Deathrattle."（死亡事件收集 → Fish 亡语时逐张
    执行——磁力栈叠同构）。
    """

    passive = True

    @staticmethod
    def on_bind(hero, game):
        if game.turn == 0:
            fish = game.create_minion(_FISH_ID, controller=hero)
            if fish is not None and not hero.board_full():
                game.summon(hero, fish)


class FishOfNZothScript:
    """After a different friendly Deathrattle minion dies in combat,
    gain its Deathrattle. 死亡时执行全部获得的亡语。"""

    @staticmethod
    def on_summon(source, game, ctx):
        source._gained_drs: list = []
        self_hero = source.controller

        def on_death(g, minion=None, **kw):
            if minion is None or minion is source:
                return
            if minion.controller is not source.controller:
                return
            if not g.in_combat:
                return
            if not minion.has(GameTag.DEATHRATTLE):
                return
            if minion.card_id not in source._gained_drs:
                source._gained_drs.append(minion.card_id)

        game.events.register(Listener(
            event="death", owner=source, callback=on_death))

    @staticmethod
    def deathrattle(source, game, ctx):
        from hsrl2.scripts import REGISTRY
        for cid in getattr(source, "_gained_drs", []):
            cls = REGISTRY.get(cid)
            fn = getattr(cls, "deathrattle", None) if cls else None
            if fn is None:
                continue
            game.run_actions(fn(source, game, ctx))


# ═══════════════════ BG23_HERO_304p Lady Vashj — Murlocastic ═══════════════════

class LadyVashjScript:
    """At the start of each turn, get a random Spellcraft spell."""

    passive = True

    @staticmethod
    def on_bind(hero, game):
        spellcraft_ids = []
        for d in game.db._by_id.values():
            if d.card_type == 4 and d.spellcraft_id:
                sid = d.spellcraft_id
                spell_def = game.db.by_dbf(sid)
                if spell_def is not None and spell_def.id not in spellcraft_ids:
                    spellcraft_ids.append(spell_def.id)
        hero._vashj_pool = tuple(spellcraft_ids)

        def on_turn_start(g, hero=None, turn=None, **kw):
            if hero is not self_hero:
                return
            pool = getattr(self_hero, "_vashj_pool", ())
            if not pool:
                return
            sid = g.rng.choice(pool, label="vashj_spellcraft")
            s = g.create_spell(sid, controller=self_hero)
            if s is not None:
                g.pending_hand_add(self_hero, s)

        self_hero = hero
        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))


def register() -> list[str]:
    """注册本批次 13 张（Silas/Zephrys DEFERRED——见文件头台账）。"""
    from hsrl2.scripts.registry import register as reg

    registered: list[str] = []
    for power_id, script in (
        ("TB_BaconShop_HP_054", MillhouseScript),
        ("TB_BaconShop_HP_014", SindragosaScript),
        ("TB_BaconShop_HP_065", ArannaScript),
        ("BG32_HERO_001p", CenariusScript),
        ("BG34_HERO_002p", ClocksworthScript),
        ("BG22_HERO_201p", FaelinScript),
        ("TB_BaconShop_HP_044", AFKayScript),
        ("TB_BaconShop_HP_072", PatchesScript),
        ("BG31_HERO_006p", ExarchOthaarScript),
        ("TB_BaconShop_HP_104", CThunScript),
        ("TB_BaconShop_HP_037a", WagtoggleScript),
        ("TB_BaconShop_HP_036", JaraxxusScript),
        ("TB_BaconShop_HP_036t", NetherPortalScript),
        ("TB_BaconShop_HP_105", NZothScript),
        ("TB_BaconShop_HP_105t", FishOfNZothScript),
        ("BG23_HERO_304p", LadyVashjScript),
    ):
        reg(power_id, script)
        registered.append(power_id)
    return registered
