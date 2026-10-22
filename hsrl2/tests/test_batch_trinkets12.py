"""批次 trinkets12 行为层测试（8 张饰品, 作业单 2026-09-11）。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线）;
    另有 1 例走真实商店 `_offer_trinkets` 三选一 + PendingChoice.choose
  - 关联卡授予: `game.grant_trinket_related_card`（RULES §7.4.6）
  - 攻击: 真实 `combat.execute_immediate_attack`（BEFORE_ATTACK）
  - 法术塑造: 真实召唤 `BG23_000` → on_summon 授予 `BG23_000t` →
    真实 `game.play_spell`（spellcraft_cast 广播）
  - 发现: 真实 `Discover` Action + `PendingChoice.choose`
    （card_discovered 广播）/ 直接 fire 同事件做正负对照
  - 磁力: 真实 `game.play_minion(magnetic_target=…)`（magnetized 广播）
  - 召唤: 真实 `game.summon` / `game.play_minion`
  - 池: `minion_pool.available` / `spell_pool.available` 前后差

覆盖（SOP §16 空转测试判定法）: 每个测试方法至少含一条**正效果**断言
（无饰品对照多与正例写在同一方法内，或直接对同事件做正负对照），
owner 隔离（2 英雄），跨战斗/跨回合语义，池空/无候选落空，
CardDef.num 双向钉死。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Discover
from hsrl2.actions.discover import _pool_candidates
from hsrl2.combat import execute_immediate_attack
from hsrl2.db import CardDB
from hsrl2.events import AFTER_ATTACK, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有卡（CardDB 按名核实——禁止凭记忆写 id）
QUILBOAR_T1 = "BG20_100"      # Razorfen Geomancer 2/1 T1 野猪人（池）
QUILBOAR_T2 = "BG20_101"      # Roadboar 2/4 T2 野猪人（池）
PLAIN_T2 = "BG31_177"         # Mechagnome Interpreter 3/1 T2 机械（池）
PLAIN_T3 = "BG23_004"         # Deep-Sea Angler 2/3 T3 纳迦（池）
PLAIN_T4 = "BG20_104"         # Bonker 2/7 T4 野猪人（池）
PLAIN_T5 = "BG21_004"         # Insatiable Ur'zul 4/6 T5 恶魔（池）
MAGNETIC = "BG26_146"         # Lullabot 2/2 T1 磁力机械（池）
HOST_MECH = "BG_BOT_911"      # Annoy-o-Module 2/4 T3 机械（脚本未注册→
                              # 磁力宿主零干扰; CardDB 按名核实）
TAVERN_SPELL = "BG28_168"     # Shiny Ring T3 池法术
DARK_GIFT_ENTITY = "BG36_MidGameEffect_000t"   # 非卡牌效果实体

JAR = "BG30_MagicItem_546"
GLOWSCALE = "BG30_MagicItem_548"
SURPRISE = "BG30_MagicItem_555"
PRIMALFIN = "BG30_MagicItem_702"
ELECTRO = "BG30_MagicItem_709"
SINSTONE = "BG30_MagicItem_801"
FISH = "BG30_MagicItem_821"
HORDE = "BG30_MagicItem_843t"

GLOWSCALE_TOKEN = "BG34_Giant_035"     # evolution 链目标（token）
SURPRISE_TOKEN = "BG26_175"            # evolution 链目标（池随从）
PRIMALFIN_TOKEN = "BGS_020"            # evolution 链目标（池随从）
FISH_TOKEN = "TB_BaconShop_HP_105t"    # evolution 链目标（token）

# 2026-09-14 batch_trinkets27 解冻 GLOWSCALE（548——`spell_resolved`
# 后置施法时点，RULES §7.4.12）与 "BG30_MagicItem_701"（The Eye of
# Sargeras——实体级 `HEALTH_BUY` 以生命代金协议 RULES §7.4.7 + 入馆观察
# 点 `tavern_entity_added` RULES §7.4.9）→ 两者移出本 DEFERRED 台账
# （现由 batch_trinkets27 注册，守卫见 test_batch_trinkets27）
# 777 Goose Portrait 已由 batch_goose_lucky_egg 注册（2026-09-17——载荷
# `BG29_801` 已有 batch_remaining2，次生载荷 `BG30_104`/`_G` 由本批补齐）
# → 移出本 DEFERRED 台账（守卫见 test_batch_goose_lucky_egg）
# 803 Kaboom Bot Portrait 已由 batch_trinkets39 注册（2026-09-18——家族
# 亡语伤害加成读取点 = RULES §7.4.16 `family_flags` + 载荷侧
# `FLAG_KABOOM_DR_BONUS`；金色逐实例 +10 口径见 batch_remaining2
# `KaboomBotScript` docstring）→ 移出本 DEFERRED 台账
# 868 Rewinder / 869 Felblood Portrait 已由 batch_trinkets31 注册
# （2026-09-19——868: "also gain Attack" 增量 = 同句 Health 额 +
# 第二关联卡 `BGS_004`; 869: 两载荷注册 + `FLAG_FELBLOOD_ALSO`）→ 移出
DEFERRED = (
    "BG30_MagicItem_707", "BG30_MagicItem_711",
)
# 825 Smuggler Portrait 已由 batch_family_races 注册（2026-09-21，
# RACES 家族类型身份改写 + Tavern/Discover 作用域）→ 移出本台账
# （守卫见 test_batch_family_races）
# 804 Ancient Wishbone / 822 Twin Sky Lanterns 已由 batch_trinkets32 注册
# （`hp_times` 技能效果翻倍配额 / `combat_slot_freed` 首召唤物副本，
# 2026-09-15）→ 移出本 DEFERRED 台账（守卫见 test_batch_trinkets32）
# 828 Shaker Portrait / 944 Redeemer Portrait 已由 batch_trinkets33 注册
# （`hero.giver_bonus` 家族给予者加成通道，2026-09-13）→ 移出本台账

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 700) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind_trinket(game: Game, hero: Hero, tid: str):
    """真实授予路径: grant_trinket（RULES §7.4.3——on_bind 接线）。"""
    e = game.grant_trinket(hero, tid)
    assert e is not None, f"{tid} 未授予"
    return e


def offer_and_buy(game: Game, hero: Hero, tid: str, kind: str):
    """真实饰品商店路径: _offer_trinkets → PendingChoice → resolve。"""
    hero.gold = 50
    game._offer_trinkets(hero, kind)
    choice = game.pending_choices.pop(0)
    choice.options = [get_db().get(tid)]
    choice.choose(0)
    return hero.trinkets[-1]


def put(game: Game, hero: Hero, m: Minion) -> Minion:
    assert game.summon(hero, m)
    return m


def tank(game: Game, hero: Hero, card_id: str, *, atk: int = 2,
         health: int = 60) -> Minion:
    """高耐久测试随从（避免攻击测试里出现死亡干扰计数）。"""
    m = game.create_minion(card_id, controller=hero)
    m.set(GameTag.BASE_ATK, atk)
    m.set(GameTag.BASE_HEALTH, health)
    return put(game, hero, m)


def pool_avail(game: Game, card_id: str) -> int:
    return game.minion_pool.available(card_id)


def spell_pool_total(game: Game) -> int:
    return sum(game.spell_pool.available(d.id)
               for d in get_db().pool_spells())


def drain(game: Game, card_id: str) -> int:
    """抽干某池卡的剩余副本（返回抽走份数）。"""
    n = 0
    while game.minion_pool.acquire(card_id):
        n += 1
    return n


def minion_hand(game: Game, hero: Hero):
    return [e for e in hero.hand if isinstance(e, Minion)]


def real_minion_discover(game: Game, hero: Hero):
    """真实发现路径（Discover 预留三选项 → choose(0) → 入手）。"""
    cands = _pool_candidates(game)[:10]
    assert cands
    game.run_actions(Discover(hero, count=3, candidates=cands,
                              kind="discover_minion"))
    assert game.pending_choices, "Discover 未产生选择"
    choice = game.pending_choices.pop(0)
    assert len(choice.options) == 3
    choice.choose(0)
    return choice.options[0]


def fire_discovered(game: Game, hero: Hero, option: str, *, kind="discover_minion"):
    """广播发现完成事件（引擎真实广播点 `PendingChoice.choose`）。"""
    game.events.fire(game, "card_discovered", kind=kind, hero=hero,
                     option=option)


# ══════════════ BG30_MagicItem_546 Jar o' Gems ══════════════


class TestJarOGems(unittest.TestCase):
    """每场战斗每 2 个友方随从攻击 → 对全部己方野猪人施放鲜血宝石。"""

    TID = JAR

    def _setup(self, seed, with_trinket=True):
        g = make_game(seed)
        a, b = g.heroes
        if with_trinket:
            bind_trinket(g, a, self.TID)
        quils = [tank(g, a, QUILBOAR_T2, atk=2, health=60),
                 tank(g, a, QUILBOAR_T1, atk=2, health=60)]
        plain = tank(g, a, PLAIN_T2, atk=2, health=60)
        attacker = tank(g, a, PLAIN_T3, atk=2, health=60)
        defender = tank(g, b, PLAIN_T5, atk=0, health=200)
        g.in_combat = True
        return g, a, b, quils, plain, attacker, defender

    def test_two_attacks_play_gem_on_all_quilboar(self):
        g, a, b, quils, plain, atk, dfd = self._setup(1701)
        g.in_combat = False
        execute_immediate_attack(g, atk, dfd)      # 招募期不触发（对照）
        self.assertEqual(quils[0].get(GameTag.GEMS_PLAYED_ON, 0), 0)
        g.in_combat = True
        for _ in range(2):
            execute_immediate_attack(g, atk, dfd)
        gem = get_db().get("BG20_GEM")
        for q in quils:
            self.assertEqual(q.get(GameTag.GEMS_PLAYED_ON), 1)
            self.assertEqual(q.atk, 2 + gem.num(0))
            self.assertEqual(q.health, 60 + gem.num(1))
        self.assertEqual(plain.get(GameTag.GEMS_PLAYED_ON, 0), 0)

    def test_one_attack_whiffs_then_second_triggers(self):
        g, a, b, quils, plain, atk, dfd = self._setup(1702)
        execute_immediate_attack(g, atk, dfd)
        self.assertEqual(quils[0].get(GameTag.GEMS_PLAYED_ON, 0), 0)
        execute_immediate_attack(g, atk, dfd)
        self.assertEqual(quils[0].get(GameTag.GEMS_PLAYED_ON), 1)
        self.assertEqual(quils[1].get(GameTag.GEMS_PLAYED_ON), 1)

    def test_procs_over_and_over_within_one_combat(self):
        """论坛实测证据: "attack 2 … proc over and over"（可重复触发）。"""
        g, a, b, quils, plain, atk, dfd = self._setup(1703)
        for _ in range(4):
            execute_immediate_attack(g, atk, dfd)
        for q in quils:
            self.assertEqual(q.get(GameTag.GEMS_PLAYED_ON), 2)
        self.assertEqual(plain.get(GameTag.GEMS_PLAYED_ON, 0), 0)

    def test_gem_lands_after_attack_damage(self):
        """时点: 文本 "After 2 friendly minions attack" → 宝石在该次攻击的
        伤害**之后**落地（2026-09-02 对抗审查 MAJOR: 旧实现挂
        BEFORE_ATTACK → 第 2 次攻击多打 1 点且本该阵亡者存活）。"""
        g, a, b, quils, plain, atk, dfd = self._setup(1705)
        deltas = []
        g.events.register(Listener(
            event=AFTER_ATTACK, owner=a,
            callback=lambda gg, attacker=None, **kw:
                deltas.append((attacker is atk, dfd.health))))
        hp0 = dfd.health
        for _ in range(2):
            execute_immediate_attack(g, atk, dfd)
        # 第 1 次攻击伤害 = 基础 2（此时尚未触发宝石）
        self.assertEqual(hp0 - deltas[0][1], 2)
        # 第 2 次攻击伤害仍 = 基础 2（宝石在本次伤害之后才落下）
        self.assertEqual(deltas[0][1] - deltas[1][1], 2)

    def test_start_of_combat_resets_counter(self):
        g, a, b, quils, plain, atk, dfd = self._setup(1704)
        trinket = a.trinkets[0]
        execute_immediate_attack(g, atk, dfd)      # 计数 1
        g.run_script_hook(trinket, "start_of_combat", ctx={})   # 每场清零
        execute_immediate_attack(g, atk, dfd)      # 重置后只 1 → 不触发
        self.assertEqual(quils[0].get(GameTag.GEMS_PLAYED_ON, 0), 0)
        execute_immediate_attack(g, atk, dfd)      # 第 2 次 → 触发
        self.assertEqual(quils[0].get(GameTag.GEMS_PLAYED_ON), 1)

    def test_opponent_attacks_not_counted(self):
        g, a, b, quils, plain, atk, dfd = self._setup(1705)
        opp_atk = tank(g, b, PLAIN_T3, atk=2, health=60)
        hero_def = tank(g, a, PLAIN_T4, atk=0, health=200)
        for _ in range(3):
            execute_immediate_attack(g, opp_atk, hero_def)
        self.assertEqual(quils[0].get(GameTag.GEMS_PLAYED_ON, 0), 0)
        for _ in range(2):                          # 正对照: 本人 2 次触发
            execute_immediate_attack(g, atk, dfd)
        self.assertEqual(quils[0].get(GameTag.GEMS_PLAYED_ON), 1)

    def test_without_trinket_control(self):
        g, a, b, quils, plain, atk, dfd = self._setup(1706,
                                                      with_trinket=False)
        for _ in range(2):
            execute_immediate_attack(g, atk, dfd)
        for q in quils:
            self.assertEqual(q.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        g2, a2, b2, q2, p2, at2, d2 = self._setup(1706)   # 正对照: 同 seed
        for _ in range(2):
            execute_immediate_attack(g2, at2, d2)
        self.assertEqual(q2[0].get(GameTag.GEMS_PLAYED_ON), 1)

    def test_no_quilboar_whiffs_without_error(self):
        g = make_game(1707)
        a, b = g.heroes
        bind_trinket(g, a, self.TID)
        plain = tank(g, a, PLAIN_T2, atk=2, health=60)
        attacker = tank(g, a, PLAIN_T3, atk=2, health=60)
        defender = tank(g, b, PLAIN_T5, atk=0, health=200)
        g.in_combat = True
        for _ in range(2):
            execute_immediate_attack(g, attacker, defender)
        self.assertEqual(plain.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        q = tank(g, a, QUILBOAR_T2, atk=2, health=60)   # 正对照
        for _ in range(2):
            execute_immediate_attack(g, attacker, defender)
        self.assertEqual(q.get(GameTag.GEMS_PLAYED_ON), 1)

    def test_shop_path_binds_effect(self):
        """真实商店购买路径（_offer_trinkets）确实接线。"""
        g = make_game(1708)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual([t.card_id for t in a.trinkets], [self.TID])
        q = tank(g, a, QUILBOAR_T2, atk=2, health=60)
        attacker = tank(g, a, PLAIN_T3, atk=2, health=60)
        defender = tank(g, b, PLAIN_T5, atk=0, health=200)
        g.in_combat = True
        for _ in range(2):
            execute_immediate_attack(g, attacker, defender)
        self.assertEqual(q.get(GameTag.GEMS_PLAYED_ON), 1)


# ══════════════ BG30_MagicItem_555 Surprise Portrait ══════════════


class TestSurprisePortrait(unittest.TestCase):
    """Get Elemental of Surprise（池随从——占池/池空落空）。"""

    TID = SURPRISE

    def test_grants_pool_minion_and_consumes_pool(self):
        g = make_game(1741)
        a, b = g.heroes
        before = pool_avail(g, SURPRISE_TOKEN)
        bind_trinket(g, a, self.TID)
        self.assertEqual([m.card_id for m in minion_hand(g, a)],
                         [SURPRISE_TOKEN])
        self.assertEqual(pool_avail(g, SURPRISE_TOKEN), before - 1)
        self.assertTrue(get_db().get(SURPRISE_TOKEN).is_pool_minion)
        self.assertEqual(minion_hand(g, b), [])

    def test_pool_exhausted_whiffs(self):
        g = make_game(1742)
        a = g.heroes[0]
        drain(g, SURPRISE_TOKEN)
        self.assertEqual(pool_avail(g, SURPRISE_TOKEN), 0)
        bind_trinket(g, a, self.TID)
        self.assertEqual(minion_hand(g, a), [])
        g2 = make_game(1742)                                # 正对照
        a2 = g2.heroes[0]
        bind_trinket(g2, a2, self.TID)
        self.assertEqual([m.card_id for m in minion_hand(g2, a2)],
                         [SURPRISE_TOKEN])

    def test_without_trinket_control(self):
        g = make_game(1743)
        a = g.heroes[0]
        before = pool_avail(g, SURPRISE_TOKEN)
        self.assertEqual(minion_hand(g, a), [])
        self.assertEqual(pool_avail(g, SURPRISE_TOKEN), before)
        bind_trinket(g, a, self.TID)                        # 正对照
        self.assertEqual(pool_avail(g, SURPRISE_TOKEN), before - 1)


# ══════════════ BG30_MagicItem_702 Primalfin Portrait ══════════════


class TestPrimalfinPortrait(unittest.TestCase):
    """Get Primalfin Lookout; 发现随从后随机一张酒馆法术。"""

    TID = PRIMALFIN

    def test_grants_primalfin_lookout_from_pool(self):
        g = make_game(1751)
        a, b = g.heroes
        before = pool_avail(g, PRIMALFIN_TOKEN)
        bind_trinket(g, a, self.TID)
        self.assertEqual([m.card_id for m in minion_hand(g, a)],
                         [PRIMALFIN_TOKEN])
        self.assertEqual(pool_avail(g, PRIMALFIN_TOKEN), before - 1)
        self.assertEqual(minion_hand(g, b), [])

    def test_discover_minion_grants_tavern_spell(self):
        g = make_game(1752)
        a = g.heroes[0]
        bind_trinket(g, a, self.TID)
        spells_before = spell_pool_total(g)
        spells0 = [e for e in a.hand if not isinstance(e, Minion)]
        real_minion_discover(g, a)
        spells1 = [e for e in a.hand if not isinstance(e, Minion)]
        self.assertEqual(len(spells1), len(spells0) + 1)
        self.assertIn(spells1[-1].card_id,
                      [d.id for d in get_db().pool_spells()])
        self.assertEqual(spell_pool_total(g), spells_before - 1)

    def test_discover_spell_does_not_trigger(self):
        g = make_game(1753)
        a = g.heroes[0]
        bind_trinket(g, a, self.TID)
        hand0 = len(a.hand)
        fire_discovered(g, a, TAVERN_SPELL, kind="discover_tavern_spell")
        self.assertEqual(len(a.hand), hand0)                # 法术发现不触发
        fire_discovered(g, a, PLAIN_T2)                     # 正对照: 随从
        self.assertEqual(len(a.hand), hand0 + 1)

    def test_opponent_discover_not_triggered(self):
        g = make_game(1754)
        a, b = g.heroes
        bind_trinket(g, a, self.TID)
        hand0 = len(a.hand)
        fire_discovered(g, b, PLAIN_T2)
        self.assertEqual(len(a.hand), hand0)
        fire_discovered(g, a, PLAIN_T2)                     # 正对照
        self.assertEqual(len(a.hand), hand0 + 1)

    def test_no_candidates_whiffs(self):
        g = make_game(1755)
        a = g.heroes[0]
        bind_trinket(g, a, self.TID)
        a.set(GameTag.TAVERN_TIER, 0)     # tech_level>=1 → 无候选
        hand0 = len(a.hand)
        fire_discovered(g, a, PLAIN_T2)
        self.assertEqual(len(a.hand), hand0)
        a.set(GameTag.TAVERN_TIER, 6)                       # 正对照
        fire_discovered(g, a, PLAIN_T2)
        self.assertEqual(len(a.hand), hand0 + 1)

    def test_without_trinket_control(self):
        g = make_game(1756)
        a = g.heroes[0]
        hand0 = len(a.hand)
        fire_discovered(g, a, PLAIN_T2)
        self.assertEqual(len(a.hand), hand0)
        bind_trinket(g, a, self.TID)                        # 正对照
        hand1 = len(a.hand)
        fire_discovered(g, a, PLAIN_T2)
        self.assertEqual(len(a.hand), hand1 + 1)


# ══════════════ BG30_MagicItem_709 Electromagnetic Device ══════════════


class TestElectromagneticDevice(unittest.TestCase):
    """Discover 磁力机械; 友方随从被磁力时 +3/+3。"""

    TID = ELECTRO

    def _magnetic_candidates(self, g):
        return [cid for cid in _pool_candidates(g, Race.MECH)
                if "magnetic" in get_db().get(cid).keywords]

    def _magnetic_avail(self, g):
        return sum(pool_avail(g, cid) for cid in self._magnetic_candidates(g))

    def test_discovers_magnetic_mech_with_reservation(self):
        g = make_game(1761)
        a = g.heroes[0]
        before = self._magnetic_avail(g)
        bind_trinket(g, a, self.TID)
        self.assertEqual(len(g.pending_choices), 1)
        choice = g.pending_choices[0]
        self.assertEqual(choice.kind, "discover_minion")
        self.assertEqual(len(choice.options), 3)
        for cid in choice.options:
            self.assertIn("magnetic", get_db().get(cid).keywords)
            self.assertIn(get_db().get(cid).race, (Race.MECH, Race.ALL))
        # 预留语义: 三选项各占池 1 份
        self.assertEqual(self._magnetic_avail(g), before - 3)
        g.pending_choices.pop(0).choose(0)
        self.assertEqual(len(a.hand), 1)
        self.assertIn("magnetic", get_db().get(a.hand[0].card_id).keywords)
        self.assertEqual(self._magnetic_avail(g), before - 1)

    def test_magnetize_buffs_host(self):
        g = make_game(1762)
        a, b = g.heroes
        bind_trinket(g, a, self.TID)
        g.pending_choices.pop(0).choose(0)         # 结算发现
        host = tank(g, a, HOST_MECH, atk=3, health=60)
        mag = g.create_minion(MAGNETIC, controller=a)
        a.add_to_hand(mag)
        mag_atk, mag_hp = mag.atk, mag.max_health
        before = (host.atk, host.health)
        self.assertTrue(g.play_minion(a, mag, magnetic_target=host))
        self.assertEqual((host.atk, host.health),
                         (before[0] + mag_atk + 3, before[1] + mag_hp + 3))

    def test_opponent_host_not_buffed(self):
        g = make_game(1763)
        a, b = g.heroes
        bind_trinket(g, a, self.TID)
        g.pending_choices.pop(0).choose(0)
        own = tank(g, a, HOST_MECH, atk=3, health=60)
        opp = tank(g, b, HOST_MECH, atk=3, health=60)
        mag1 = g.create_minion(MAGNETIC, controller=a)
        a.add_to_hand(mag1)
        mag2 = g.create_minion(MAGNETIC, controller=b)
        b.add_to_hand(mag2)
        own_before = (own.atk, own.health)
        opp_before = (opp.atk, opp.health)
        opp_mag_atk, opp_mag_hp = mag2.atk, mag2.max_health
        self.assertTrue(g.play_minion(a, mag1, magnetic_target=own))
        self.assertTrue(g.play_minion(b, mag2, magnetic_target=opp))
        self.assertEqual(own.atk, own_before[0] + mag1.atk + 3)
        self.assertEqual(own.health, own_before[1] + mag1.max_health + 3)
        # 对手宿主只并入磁力本体属性（owner 隔离）
        self.assertEqual(opp.atk, opp_before[0] + opp_mag_atk)
        self.assertEqual(opp.health, opp_before[1] + opp_mag_hp)

    def test_without_trinket_control(self):
        g = make_game(1764)
        a = g.heroes[0]
        host = tank(g, a, HOST_MECH, atk=3, health=60)
        mag = g.create_minion(MAGNETIC, controller=a)
        a.add_to_hand(mag)
        mag_atk, mag_hp = mag.atk, mag.max_health
        before = (host.atk, host.health)
        self.assertTrue(g.play_minion(a, mag, magnetic_target=host))
        self.assertEqual((host.atk, host.health),
                         (before[0] + mag_atk, before[1] + mag_hp))
        g2 = make_game(1764)                                # 正对照
        a2 = g2.heroes[0]
        bind_trinket(g2, a2, self.TID)
        g2.pending_choices.pop(0).choose(0)
        host2 = tank(g2, a2, HOST_MECH, atk=3, health=60)
        mag2 = g2.create_minion(MAGNETIC, controller=a2)
        a2.add_to_hand(mag2)
        b2 = (host2.atk, host2.health)
        self.assertTrue(g2.play_minion(a2, mag2, magnetic_target=host2))
        self.assertEqual(host2.atk, b2[0] + mag2.atk + 3)
        self.assertEqual(host2.health, b2[1] + mag2.max_health + 3)

    def test_no_magnetic_candidates_no_choice(self):
        g = make_game(1765)
        a = g.heroes[0]
        for cid in self._magnetic_candidates(g):
            drain(g, cid)
        bind_trinket(g, a, self.TID)
        self.assertEqual(g.pending_choices, [])
        g2 = make_game(1765)                                # 正对照
        a2 = g2.heroes[0]
        bind_trinket(g2, a2, self.TID)
        self.assertEqual(len(g2.pending_choices), 1)


# ══════════════ BG30_MagicItem_801 Sinstone Sticker ══════════════


class TestSinstoneSticker(unittest.TestCase):
    """每回合前 num(1) 次发现卡牌 → 额外一张副本。"""

    TID = SINSTONE

    def test_extra_copy_first_n_times_per_turn(self):
        g = make_game(1771)
        a = g.heroes[0]
        limit = get_db().get(self.TID).num(1)
        bind_trinket(g, a, self.TID)
        options = (PLAIN_T2, PLAIN_T3, QUILBOAR_T1, PLAIN_T4)
        for i in range(limit):
            cid = options[i]
            before = pool_avail(g, cid)
            fire_discovered(g, a, cid)
            self.assertEqual(pool_avail(g, cid), before - 1,
                             f"第 {i + 1} 次发现应得副本（占池）")
        # 额度用尽 → 不再发放
        before = pool_avail(g, PLAIN_T5)
        fire_discovered(g, a, PLAIN_T5)
        self.assertEqual(pool_avail(g, PLAIN_T5), before)

    def test_spell_discover_gets_copy(self):
        g = make_game(1773)
        a = g.heroes[0]
        bind_trinket(g, a, self.TID)
        before = g.spell_pool.available(TAVERN_SPELL)
        fire_discovered(g, a, TAVERN_SPELL, kind="discover_spell")
        copies = [e for e in a.hand if e.card_id == TAVERN_SPELL]
        self.assertEqual(len(copies), 1)
        self.assertEqual(g.spell_pool.available(TAVERN_SPELL), before - 1)

    def test_golden_discover_gets_golden_copy(self):
        """金色发现（Treasure Hoard `Discover(golden=True)`）→ 副本同为
        金色（2026-09-02 对抗审查 MINOR: 旧实现恒发基础卡）。"""
        g = make_game(1775)
        a = g.heroes[0]
        bind_trinket(g, a, self.TID)
        g.minion_pool.ensure_available(PLAIN_T2, copies=3)
        Discover(a, count=1, candidates=[PLAIN_T2], golden=True,
                 kind="discover_minion").do(g)
        g.pending_choices.pop(0).choose(0)
        got = [e for e in a.hand if e.card_id in (PLAIN_T2,)]
        golds = [e for e in a.hand if getattr(e, "is_golden", False)]
        self.assertEqual(len(golds), 2)                    # 本体 + 副本
        self.assertTrue(all(e.card_id == PLAIN_T2 for e in got))
        for e in golds:
            self.assertTrue(e.get(GameTag.GILDED_NOT_TRIPLED, False))

    def test_dark_gift_not_copied(self):
        g = make_game(1774)
        a = g.heroes[0]
        bind_trinket(g, a, self.TID)
        hand0 = len(a.hand)
        fire_discovered(g, a, DARK_GIFT_ENTITY, kind="dark_gift")
        self.assertEqual(len(a.hand), hand0)
        fire_discovered(g, a, PLAIN_T2)                     # 正对照
        self.assertEqual(len(a.hand), hand0 + 1)

    def test_resets_next_turn(self):
        g = make_game(1775)
        a = g.heroes[0]
        limit = get_db().get(self.TID).num(1)
        bind_trinket(g, a, self.TID)
        for cid in (PLAIN_T2, PLAIN_T3)[:limit]:
            fire_discovered(g, a, cid)
        before = pool_avail(g, PLAIN_T4)
        fire_discovered(g, a, PLAIN_T4)
        self.assertEqual(pool_avail(g, PLAIN_T4), before)   # 额度用尽
        g.turn += 1                                         # 新回合
        before = pool_avail(g, PLAIN_T5)
        fire_discovered(g, a, PLAIN_T5)
        self.assertEqual(pool_avail(g, PLAIN_T5), before - 1)

    def test_opponent_discover_not_copied(self):
        g = make_game(1776)
        a, b = g.heroes
        bind_trinket(g, a, self.TID)
        hand0 = len(a.hand)
        fire_discovered(g, b, PLAIN_T2)
        self.assertEqual(len(a.hand), hand0)
        fire_discovered(g, a, PLAIN_T2)                     # 正对照
        self.assertEqual(len(a.hand), hand0 + 1)

    def test_pool_empty_copy_whiffs(self):
        g = make_game(1777)
        a = g.heroes[0]
        bind_trinket(g, a, self.TID)
        drain(g, PLAIN_T2)
        hand0 = len(a.hand)
        fire_discovered(g, a, PLAIN_T2)
        self.assertEqual(len(a.hand), hand0)                # 池空 → 落空
        fire_discovered(g, a, PLAIN_T3)                     # 正对照
        self.assertEqual(len(a.hand), hand0 + 1)

    def test_real_discover_path_grants_copy(self):
        g = make_game(1779)
        a = g.heroes[0]
        bind_trinket(g, a, self.TID)
        hand0 = len(a.hand)
        picked = real_minion_discover(g, a)
        self.assertEqual(len(a.hand), hand0 + 2)            # 本体 + 副本
        self.assertEqual(
            len([m for m in minion_hand(g, a) if m.card_id == picked]), 2)

    def test_without_trinket_control(self):
        g = make_game(1778)
        a = g.heroes[0]
        real_minion_discover(g, a)
        self.assertEqual(len(a.hand), 1)
        g2 = make_game(1778)                                # 正对照
        a2 = g2.heroes[0]
        bind_trinket(g2, a2, self.TID)
        real_minion_discover(g2, a2)
        self.assertEqual(len(a2.hand), 2)


# ══════════════ BG30_MagicItem_821 Fish Portrait ══════════════


class TestFishPortrait(unittest.TestCase):
    """Get a Fish of N'Zoth（token, 零池操作）。"""

    TID = FISH

    def test_grants_fish_token(self):
        g = make_game(1781)
        a, b = g.heroes
        before = pool_avail(g, FISH_TOKEN)
        bind_trinket(g, a, self.TID)
        self.assertEqual([m.card_id for m in minion_hand(g, a)],
                         [FISH_TOKEN])
        self.assertFalse(get_db().get(FISH_TOKEN).is_pool_minion)
        self.assertEqual(pool_avail(g, FISH_TOKEN), before)
        self.assertEqual(minion_hand(g, b), [])
        self.assertEqual(g.trinket_related_card(self.TID).id, FISH_TOKEN)

    def test_without_trinket_control(self):
        g = make_game(1782)
        a = g.heroes[0]
        self.assertEqual(minion_hand(g, a), [])
        bind_trinket(g, a, self.TID)                        # 正对照
        self.assertEqual([m.card_id for m in minion_hand(g, a)],
                         [FISH_TOKEN])


# ══════════════ BG30_MagicItem_843t Horde Keychain ══════════════


class TestHordeKeychain(unittest.TestCase):
    """Your minions from Tier 3 or lower have +7/+5。"""

    TID = HORDE

    def test_tier3_or_lower_buffed(self):
        g = make_game(1791)
        a = g.heroes[0]
        mins = [put(g, a, g.create_minion(cid, controller=a))
                for cid in (QUILBOAR_T1, PLAIN_T2, PLAIN_T3,
                            PLAIN_T4, PLAIN_T5)]
        snap = [ (m.atk, m.health) for m in mins ]
        bind_trinket(g, a, self.TID)
        for m, base in zip(mins[:3], snap[:3]):
            self.assertEqual(m.atk, base[0] + 7)
            self.assertEqual(m.health, base[1] + 5)
        for m, base in zip(mins[3:], snap[3:]):
            self.assertEqual((m.atk, m.health), base)       # T4/T5 不变

    def test_new_summon_buffed(self):
        g = make_game(1792)
        a = g.heroes[0]
        bind_trinket(g, a, self.TID)
        m = put(g, a, g.create_minion(PLAIN_T2, controller=a))
        self.assertEqual(m.atk, get_db().get(PLAIN_T2).atk + 7)
        self.assertEqual(m.health, get_db().get(PLAIN_T2).health + 5)
        card = g.create_minion(QUILBOAR_T1, controller=a)   # 打出路径
        a.add_to_hand(card)
        self.assertTrue(g.play_minion(a, card))
        self.assertEqual(card.atk, get_db().get(QUILBOAR_T1).atk + 7)
        self.assertEqual(card.health, get_db().get(QUILBOAR_T1).health + 5)

    def test_opponent_minions_unaffected(self):
        g = make_game(1793)
        a, b = g.heroes
        bind_trinket(g, a, self.TID)
        own = put(g, a, g.create_minion(PLAIN_T2, controller=a))
        opp = put(g, b, g.create_minion(PLAIN_T2, controller=b))
        self.assertEqual(own.atk, get_db().get(PLAIN_T2).atk + 7)
        self.assertEqual(opp.atk, get_db().get(PLAIN_T2).atk)

    def test_without_trinket_control(self):
        g = make_game(1794)
        a = g.heroes[0]
        m = put(g, a, g.create_minion(PLAIN_T2, controller=a))
        self.assertEqual(m.atk, get_db().get(PLAIN_T2).atk)
        bind_trinket(g, a, self.TID)                        # 正对照
        m2 = put(g, a, g.create_minion(PLAIN_T2, controller=a))
        self.assertEqual(m2.atk, get_db().get(PLAIN_T2).atk + 7)
        self.assertEqual(m2.health, get_db().get(PLAIN_T2).health + 5)


# ══════════════ 结构 / 台账守卫 ══════════════


class TestRegistryLedger(unittest.TestCase):
    """注册表与 DEFERRED 台账守卫（结构性——与钩子无关）。@engine-only"""

    IMPLEMENTED = (JAR, SURPRISE, PRIMALFIN, ELECTRO, SINSTONE,
                   FISH, HORDE)

    def test_all_implemented_registered(self):
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)

    def test_deferred_not_registered(self):
        for tid in DEFERRED:
            self.assertNotIn(tid, REGISTRY, f"{tid} 应为 DEFERRED")

    def test_numeric_params_match_carddef(self):
        d = get_db().get(GLOWSCALE)
        self.assertEqual((d.num(0), d.num(1)), (3, 3))
        self.assertEqual(get_db().get(JAR).num(0), 2)
        self.assertEqual((get_db().get(SINSTONE).num(0),
                          get_db().get(SINSTONE).num(1)), (2, 2))

    def test_related_card_data_chain(self):
        db = get_db()
        self.assertEqual(db.by_dbf(db.get(GLOWSCALE).evolution_card_id).id,
                         GLOWSCALE_TOKEN)
        self.assertEqual(db.by_dbf(db.get(SURPRISE).evolution_card_id).id,
                         SURPRISE_TOKEN)
        self.assertEqual(db.by_dbf(db.get(PRIMALFIN).evolution_card_id).id,
                         PRIMALFIN_TOKEN)
        self.assertEqual(db.by_dbf(db.get(FISH).evolution_card_id).id,
                         FISH_TOKEN)

    def test_deferred_ids_are_offer_pool_members(self):
        pool = {d.id for d in get_db().trinket_offer_pool()}
        for tid in DEFERRED + self.IMPLEMENTED:
            self.assertIn(tid, pool, tid)

    def test_deferred_count(self):
        # 777/803/868/869 已注册迁出; 825 已由 batch_family_races 注册
        # （2026-09-21）→ 3 降为 2
        self.assertEqual(len(DEFERRED), 2)


if __name__ == "__main__":
    unittest.main()
