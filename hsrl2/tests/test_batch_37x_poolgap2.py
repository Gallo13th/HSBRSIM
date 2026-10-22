"""批次 37x_poolgap2 行为层测试（10 张当前池内 combat/经济卡 + 金色）。

覆盖（全部真实引擎路径）:
  - EoT: 真实 `game.end_recruit_phase()` EoT 阶段分发 + 直接
    `run_script_hook(entity, "end_of_turn")`
  - 战斗: 真实 `game.run_combat` / `_process_single_death`（Avenge 计数）
  - 亡语: 真实 `game.destroy_minion` → `check_deaths` → `trigger_deathrattle`
  - 售出: 真实 `game.sell_minion`（on_sell 钩子）
  - 战吼: 真实 `game.play_minion`（战吼/金色双触发路径）
  - 法术: 真实 `game.play_spell`（`tavern_spell_cast` 后置广播）
  - 酒馆持久 Buff: 真实 `game.add_tavern_entity` / `refresh_tavern` /
    `buy_from_tavern`
  - 池记账: 真实 `spell_pool.available/total_remaining/acquire`

每卡都有正对照（钩子换 no-op 后必失败）与负对照（非相邻 / 非目标种族 /
对手施放 / 非池法术 / 满手 / 池耗尽）。

DEFERRED 台账守卫: 本批 34 张 DEFERRED 卡不得出现在 REGISTRY
（Deity / Discard / 载荷缺失 / 触发链无上限 四类，见 batch 文件
§DEFERRED 台账）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import GainKeyword, LoseKeyword
from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_37x_poolgap2 as B
from hsrl2.tags import CardType, GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 37, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def dummy(hero: Hero, name: str = "Dummy", atk: int = 1,
          health: int = 50, race: Race | None = None) -> Minion:
    game = hero.game
    m = Minion(f"TEST_{name}", name, atk=atk, health=health)
    m.game = game
    m.controller = hero
    m.zone = Zone.PLAY
    if race is not None:
        m.set(GameTag.RACE, race)
    hero.board.append(m)
    game._update_positions(hero)
    return m


def hand_minion(game: Game, hero: Hero, card_id: str,
                golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert hero.add_to_hand(m)
    return m


def tavern_add(game: Game, hero: Hero, card_id: str) -> Minion:
    """把一只随从放入酒馆展示区（走真实 `add_tavern_entity` 接线）。"""
    m = game.create_minion(card_id, controller=hero)
    game.add_tavern_entity(hero, m)
    return m


def enter_combat(game: Game, a: Hero, b: Hero) -> None:
    game.in_combat = True
    game._active_combat = (a, b)


def kill(game: Game, m: Minion) -> None:
    m.health = 0
    game._process_single_death(m)


def elemental_id() -> str:
    for d in get_db().pool_minions():
        if Race.ELEMENTAL in d.races and REGISTRY.get(d.id) is None:
            return d.id
    raise AssertionError("no plain elemental pool minion")


def mech_id() -> str:
    # 排除 ALL/双类型（Amalgam 也吃元素光环——否则"机械不变"断言会误红）
    for d in get_db().pool_minions():
        if (Race.MECH in d.races and Race.ELEMENTAL not in d.races
                and Race.ALL not in d.races and REGISTRY.get(d.id) is None):
            return d.id
    raise AssertionError("no plain mech pool minion")


def base_stats(card_id: str) -> tuple:
    d = get_db().get(card_id)
    return (d.atk, d.health)


def one_cost_spell_ids() -> list:
    return [d.id for d in get_db().pool_spells() if d.cost == 1]


# ══════════════════════════════════════════════════════════════════════
# 结构性: 注册表 / 金色 CardDef / DEFERRED 台账守卫
# ══════════════════════════════════════════════════════════════════════


class TestRegistryAndCardDefs(unittest.TestCase):
    """@engine-only 结构性: 注册表 / 金色独立 CardDef / num 纪律。"""

    def test_registered_all_ids(self):
        expected = [
            B.YOUNG_MURK_EYE, B.YOUNG_MURK_EYE_G,
            B.RELENTLESS_DEFLECTOR, B.RELENTLESS_DEFLECTOR_G,
            B.UNDERROT_SPAWN, B.UNDERROT_SPAWN_G,
            B.BUBBLE_GUNNER, B.BUBBLE_GUNNER_G,
            B.DUNE_DWELLER, B.DUNE_DWELLER_G,
            B.LIVING_AZERITE, B.LIVING_AZERITE_G,
            B.DARK_PUPPETEER, B.DARK_PUPPETEER_G,
            B.UNWILLING_SLACKER, B.UNWILLING_SLACKER_G,
            B.ZOATROID, B.ZOATROID_G,
            B.IRON_GROUNDSKEEPER, B.IRON_GROUNDSKEEPER_G,
        ]
        self.assertEqual(len(expected), 20)
        for cid in expected:
            self.assertIn(cid, REGISTRY, cid)

    def test_pool_and_golden_defs(self):
        db = get_db()
        for cid in (B.YOUNG_MURK_EYE, B.RELENTLESS_DEFLECTOR,
                    B.UNDERROT_SPAWN, B.BUBBLE_GUNNER, B.DUNE_DWELLER,
                    B.LIVING_AZERITE, B.DARK_PUPPETEER,
                    B.UNWILLING_SLACKER, B.ZOATROID,
                    B.IRON_GROUNDSKEEPER):
            d = db.get(cid)
            self.assertIsNotNone(d, cid)
            self.assertTrue(d.is_pool_minion, cid)
        for base in (B.YOUNG_MURK_EYE, B.RELENTLESS_DEFLECTOR,
                     B.UNDERROT_SPAWN, B.BUBBLE_GUNNER, B.DUNE_DWELLER,
                     B.LIVING_AZERITE, B.DARK_PUPPETEER,
                     B.UNWILLING_SLACKER, B.ZOATROID,
                     B.IRON_GROUNDSKEEPER):
            self.assertIsNotNone(db.get(base + "_G"), base)

    def test_template_numbers(self):
        db = get_db()
        self.assertEqual(db.get(B.UNDERROT_SPAWN).num(0), 1)
        self.assertEqual(db.get(B.UNDERROT_SPAWN_G).num(0), 2)
        self.assertEqual(db.get(B.DUNE_DWELLER).num(0), 1)
        self.assertEqual(db.get(B.DUNE_DWELLER).num(1), 1)
        self.assertEqual(db.get(B.LIVING_AZERITE).num(0), 4)
        self.assertEqual(db.get(B.LIVING_AZERITE).num(1), 3)
        self.assertEqual(db.get(B.DARK_PUPPETEER).num(0), 4)
        self.assertEqual(db.get(B.DARK_PUPPETEER_G).num(0), 8)
        self.assertEqual(db.get(B.IRON_GROUNDSKEEPER).num(0), 2)
        self.assertEqual(db.get(B.IRON_GROUNDSKEEPER_G).num(0), 4)
        self.assertEqual(db.get(B.RELENTLESS_DEFLECTOR).avenge_target, 3)
        self.assertEqual(db.get(B.RELENTLESS_DEFLECTOR_G).avenge_target, 3)

    def test_payload_tokens_exist(self):
        db = get_db()
        tok = db.get(B.ABERRANT_TENTACLE)
        self.assertIsNotNone(tok)
        self.assertEqual((tok.atk, tok.health), (0, 2))
        self.assertIn("taunt", tok.keywords)
        self.assertTrue(db.get(B.FORTIFY).is_pool_spell)

    def test_deferred_cards_not_registered(self):
        """剩余 DEFERRED 仅 BG28_583 Geomagus（触发链无权威上限）。

        谱系: 载荷批（FG32_336/BG35_881/BG34_170/171/BG36_366/367/
        112/115）、F-06（BG35_882）、F-07（BG36_103/318/110）、
        F-08 Discard（BG28_582/BG36_100/BG36_320/BGFYM_005 等）均已注册。
        """
        for cid in ("BG28_583",):
            self.assertNotIn(cid, REGISTRY, cid)

    def test_scripts_class_mapping(self):
        self.assertIs(REGISTRY[B.YOUNG_MURK_EYE_G],
                      B.YoungMurkEyeGoldenScript)
        self.assertIs(REGISTRY[B.LIVING_AZERITE_G],
                      B.LivingAzeriteGoldenScript)
        self.assertIs(REGISTRY[B.RELENTLESS_DEFLECTOR_G],
                      B.RelentlessDeflectorScript)
        self.assertIs(REGISTRY[B.IRON_GROUNDSKEEPER_G],
                      B.IronGroundskeeperScript)


# ══════════════════════════════════════════════════════════════════════
# BG22_403 Young Murk-Eye
# ══════════════════════════════════════════════════════════════════════


class TestYoungMurkEye(unittest.TestCase):
    """BG22_403 — EoT 触发相邻随从战吼（金色 twice）。"""

    def _beta(self, game, hero):
        """相邻带战吼随从（Bubble Gunner；同批真实战吼）。"""
        return put(game, B.BUBBLE_GUNNER, hero)

    def test_left_neighbor_battlecry_triggered(self):
        game = make_game(seed=70)
        a = game.heroes[0]
        beta = self._beta(game, a)
        eye = put(game, B.YOUNG_MURK_EYE, a)      # 板序 [Bubble, Murk]
        game.run_script_hook(eye, "end_of_turn")
        self.assertTrue(beta.get(GameTag.BONUS_KEYWORDS))

    def test_right_neighbor_battlecry_triggered(self):
        game = make_game(seed=71)
        a = game.heroes[0]
        eye = put(game, B.YOUNG_MURK_EYE, a)
        beta = self._beta(game, a)                # 板序 [Murk, Bubble]
        game.run_script_hook(eye, "end_of_turn")
        self.assertTrue(beta.get(GameTag.BONUS_KEYWORDS))

    def test_both_neighbors_triggered(self):
        game = make_game(seed=72)
        a = game.heroes[0]
        left = self._beta(game, a)
        eye = put(game, B.YOUNG_MURK_EYE, a)
        right = self._beta(game, a)
        game.run_script_hook(eye, "end_of_turn")
        self.assertTrue(left.get(GameTag.BONUS_KEYWORDS))
        self.assertTrue(right.get(GameTag.BONUS_KEYWORDS))

    def test_non_adjacent_not_triggered(self):
        game = make_game(seed=73)
        a = game.heroes[0]
        far = self._beta(game, a)
        dummy(a, "Spacer")                        # 隔开
        eye = put(game, B.YOUNG_MURK_EYE, a)
        game.run_script_hook(eye, "end_of_turn")
        self.assertFalse(far.get(GameTag.BONUS_KEYWORDS))

    def test_golden_triggers_each_neighbor_twice(self):
        game = make_game(seed=74)
        a = game.heroes[0]
        beta = self._beta(game, a)
        eye = put(game, B.YOUNG_MURK_EYE, a, golden=True)
        grants = []
        game.events.register(Listener(
            event="bonus_keyword_granted", owner=beta,
            callback=lambda g, **kw: grants.append(kw["tag"])))
        game.run_script_hook(eye, "end_of_turn")
        self.assertEqual(len(grants), 2)

    def test_no_neighbors_no_crash(self):
        game = make_game(seed=75)
        a = game.heroes[0]
        eye = put(game, B.YOUNG_MURK_EYE, a)
        dummy(a, "NotBattlecry")                  # 相邻但无战吼
        game.run_script_hook(eye, "end_of_turn")
        self.assertFalse(eye.dead)

    def test_real_eot_phase_via_end_recruit_phase(self):
        """真实 `end_recruit_phase` 的 EoT 阶段分发（非直接钩子）。"""
        game = make_game(seed=76)
        a = game.heroes[0]
        beta = self._beta(game, a)
        put(game, B.YOUNG_MURK_EYE, a)
        game.end_recruit_phase()
        self.assertTrue(beta.get(GameTag.BONUS_KEYWORDS))


# ══════════════════════════════════════════════════════════════════════
# BG34_405 Relentless Deflector
# ══════════════════════════════════════════════════════════════════════


class TestRelentlessDeflector(unittest.TestCase):
    """BG34_405 — 有圣盾时获得 Taunt；Avenge (3) 获得圣盾。"""

    def test_no_divine_shield_no_taunt(self):
        game = make_game(seed=80)
        a = game.heroes[0]
        d = put(game, B.RELENTLESS_DEFLECTOR, a)
        self.assertFalse(d.has(GameTag.TAUNT))

    def test_gain_divine_shield_grants_taunt(self):
        game = make_game(seed=81)
        a = game.heroes[0]
        d = put(game, B.RELENTLESS_DEFLECTOR, a)
        game.run_actions(GainKeyword(d, GameTag.DIVINE_SHIELD))
        self.assertTrue(d.has(GameTag.TAUNT))

    def test_lose_divine_shield_removes_taunt(self):
        game = make_game(seed=82)
        a = game.heroes[0]
        d = put(game, B.RELENTLESS_DEFLECTOR, a)
        game.run_actions(GainKeyword(d, GameTag.DIVINE_SHIELD))
        game.run_actions(LoseKeyword(d, GameTag.DIVINE_SHIELD))
        self.assertFalse(d.has(GameTag.TAUNT))

    def test_non_ds_keyword_loss_keeps_taunt(self):
        game = make_game(seed=83)
        a = game.heroes[0]
        d = put(game, B.RELENTLESS_DEFLECTOR, a)
        game.run_actions(GainKeyword(d, GameTag.DIVINE_SHIELD))
        d.set(GameTag.WINDFURY, True)
        game.run_actions(LoseKeyword(d, GameTag.WINDFURY))
        self.assertTrue(d.has(GameTag.TAUNT))

    def test_avenge_three_deaths_grants_shield_and_taunt(self):
        game = make_game(seed=84)
        a, b = game.heroes
        d = put(game, B.RELENTLESS_DEFLECTOR, a)
        enter_combat(game, a, b)
        for i in range(3):
            kill(game, dummy(a, f"V{i}", 1, 5))
        self.assertTrue(d.has(GameTag.DIVINE_SHIELD))
        self.assertTrue(d.has(GameTag.TAUNT))

    def test_two_deaths_no_avenge(self):
        game = make_game(seed=85)
        a, b = game.heroes
        d = put(game, B.RELENTLESS_DEFLECTOR, a)
        enter_combat(game, a, b)
        for i in range(2):
            kill(game, dummy(a, f"V{i}", 1, 5))
        self.assertFalse(d.has(GameTag.DIVINE_SHIELD))

    def test_golden_same_behavior(self):
        game = make_game(seed=86)
        a, b = game.heroes
        d = put(game, B.RELENTLESS_DEFLECTOR, a, golden=True)
        enter_combat(game, a, b)
        for i in range(3):
            kill(game, dummy(a, f"V{i}", 1, 5))
        self.assertTrue(d.has(GameTag.DIVINE_SHIELD))
        self.assertTrue(d.has(GameTag.TAUNT))


# ══════════════════════════════════════════════════════════════════════
# BG36_116 Underrot Spawn
# ══════════════════════════════════════════════════════════════════════


class TestUnderrotSpawn(unittest.TestCase):
    """BG36_116 — 亡语召唤 0/2 Taunt Tentacle + 全板 +N Attack。"""

    def test_deathrattle_summons_token_and_buffs_all(self):
        game = make_game(seed=90)
        a = game.heroes[0]
        u = put(game, B.UNDERROT_SPAWN, a)
        ally = dummy(a, "Ally", 1, 20)
        game.destroy_minion(u)
        tokens = [m for m in a.board if m.card_id == B.ABERRANT_TENTACLE]
        self.assertEqual(len(tokens), 1)
        self.assertEqual((tokens[0].health, tokens[0].taunt), (2, True))
        self.assertEqual(tokens[0].atk, 0 + 1)    # 召唤后 +1 Attack 含 token
        self.assertEqual(ally.atk, 1 + 1)

    def test_golden_two_tokens_and_plus_two_attack(self):
        game = make_game(seed=91)
        a = game.heroes[0]
        u = put(game, B.UNDERROT_SPAWN, a, golden=True)
        ally = dummy(a, "Ally", 1, 20)
        game.destroy_minion(u)
        tokens = [m for m in a.board if m.card_id == B.ABERRANT_TENTACLE]
        self.assertEqual(len(tokens), 2)
        for t in tokens:
            self.assertEqual((t.atk, t.health), (2, 2))
        self.assertEqual(ally.atk, 1 + 2)

    def test_full_board_overflow_still_buffs(self):
        game = make_game(seed=92)
        a = game.heroes[0]
        u = put(game, B.UNDERROT_SPAWN, a)
        while len(a.board) < 7:
            dummy(a, f"D{len(a.board)}", 1, 20)
        game.trigger_deathrattle(u, hero=a)       # 未移除宿主 → 满场
        self.assertEqual(len(a.board), 7)
        self.assertEqual(u.atk, 2 + 1)            # token 落空，但 +1 Attack 生效

    def test_combat_death_snapshot_restores_board(self):
        """真实 run_combat: 亡语在战内结算，战后棋盘按快照复原。"""
        game = make_game(seed=93)
        a, b = game.heroes
        u = put(game, B.UNDERROT_SPAWN, a)
        dummy(b, "Big", 50, 100)
        game.run_combat(a, b)
        self.assertIn(u, a.board)                 # 快照复原（战前战团）


# ══════════════════════════════════════════════════════════════════════
# BG31_149 Bubble Gunner
# ══════════════════════════════════════════════════════════════════════


class TestBubbleGunner(unittest.TestCase):
    """BG31_149 — 战吼获得随机 Bonus Keyword（金色 2 次）。"""

    def test_play_grants_one_bonus_keyword(self):
        game = make_game(seed=100)
        a = game.heroes[0]
        m = hand_minion(game, a, B.BUBBLE_GUNNER)
        self.assertTrue(game.play_minion(a, m))
        kws = m.get(GameTag.BONUS_KEYWORDS) or frozenset()
        self.assertEqual(len(kws), 1)
        tag = next(iter(kws))
        self.assertTrue(m.has(tag))

    def test_golden_grants_two(self):
        game = make_game(seed=101)
        a = game.heroes[0]
        m = hand_minion(game, a, B.BUBBLE_GUNNER, golden=True)
        grants = []
        game.events.register(Listener(
            event="bonus_keyword_granted", owner=m,
            callback=lambda g, **kw: grants.append(kw["tag"])))
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(len(grants), 2)
        self.assertLessEqual(len(m.get(GameTag.BONUS_KEYWORDS)), 2)

    def test_non_bonus_keyword_not_used(self):
        """六集口径: 只允许 RULES §9.6 的 Bonus Keyword（fail-loud 守护）。"""
        game = make_game(seed=102)
        a = game.heroes[0]
        m = hand_minion(game, a, B.BUBBLE_GUNNER)
        self.assertRaises(Exception, game.grant_bonus_keyword, m,
                          GameTag.POISONOUS)


# ══════════════════════════════════════════════════════════════════════
# BG31_815 Dune Dweller
# ══════════════════════════════════════════════════════════════════════


class TestDuneDweller(unittest.TestCase):
    """BG31_815 — 战吼: 酒馆元素 +1/+1 this game（金色 twice）。"""

    def test_battlecry_buffs_tavern_elementals_only(self):
        game = make_game(seed=110)
        a = game.heroes[0]
        eid, mid = elemental_id(), mech_id()
        e_atk, e_hp = base_stats(eid)
        m_atk, m_hp = base_stats(mid)
        el = tavern_add(game, a, eid)
        mc = tavern_add(game, a, mid)
        m = hand_minion(game, a, B.DUNE_DWELLER)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual((el.atk, el.health), (e_atk + 1, e_hp + 1))
        self.assertEqual((mc.atk, mc.health), (m_atk, m_hp))
        self.assertEqual(len(getattr(a, "tavern_buffs", [])), 1)

    def test_golden_applies_twice(self):
        game = make_game(seed=111)
        a = game.heroes[0]
        eid = elemental_id()
        e_atk, e_hp = base_stats(eid)
        el = tavern_add(game, a, eid)
        m = hand_minion(game, a, B.DUNE_DWELLER, golden=True)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual((el.atk, el.health), (e_atk + 2, e_hp + 2))
        self.assertEqual(len(getattr(a, "tavern_buffs", [])), 2)

    def test_new_tavern_entry_gets_persistent_buff(self):
        game = make_game(seed=112)
        a = game.heroes[0]
        eid = elemental_id()
        e_atk, e_hp = base_stats(eid)
        m = hand_minion(game, a, B.DUNE_DWELLER)
        self.assertTrue(game.play_minion(a, m))
        fresh = tavern_add(game, a, eid)
        self.assertEqual((fresh.atk, fresh.health), (e_atk + 1, e_hp + 1))

    def test_bought_elemental_keeps_buff(self):
        game = make_game(seed=113)
        a = game.heroes[0]
        eid = elemental_id()
        e_atk, e_hp = base_stats(eid)
        el = tavern_add(game, a, eid)
        m = hand_minion(game, a, B.DUNE_DWELLER)
        self.assertTrue(game.play_minion(a, m))
        a.gold = 10
        self.assertTrue(game.buy_from_tavern(a, el))
        self.assertEqual((el.atk, el.health), (e_atk + 1, e_hp + 1))


# ══════════════════════════════════════════════════════════════════════
# BG28_707 Living Azerite
# ══════════════════════════════════════════════════════════════════════


class TestLivingAzerite(unittest.TestCase):
    """BG28_707 — 施放酒馆法术 → 酒馆元素 +4/+3 this game（金色 twice）。"""

    def _cast_coin(self, game, hero):
        s = game.create_spell("BG28_810", controller=hero)
        hero.hand.append(s)
        s.zone = Zone.HAND
        self.assertTrue(game.play_spell(hero, s))

    def test_tavern_spell_buffs_tavern_elementals(self):
        game = make_game(seed=120)
        a = game.heroes[0]
        eid, mid = elemental_id(), mech_id()
        e_atk, e_hp = base_stats(eid)
        m_atk, m_hp = base_stats(mid)
        put(game, B.LIVING_AZERITE, a)
        el = tavern_add(game, a, eid)
        mc = tavern_add(game, a, mid)
        self._cast_coin(game, a)
        self.assertEqual((el.atk, el.health), (e_atk + 4, e_hp + 3))
        self.assertEqual((mc.atk, mc.health), (m_atk, m_hp))
        self.assertEqual(len(getattr(a, "tavern_buffs", [])), 1)

    def test_golden_applies_twice(self):
        game = make_game(seed=121)
        a = game.heroes[0]
        eid = elemental_id()
        e_atk, e_hp = base_stats(eid)
        put(game, B.LIVING_AZERITE, a, golden=True)
        el = tavern_add(game, a, eid)
        self._cast_coin(game, a)
        self.assertEqual((el.atk, el.health), (e_atk + 8, e_hp + 6))
        self.assertEqual(len(getattr(a, "tavern_buffs", [])), 2)

    def test_opponent_cast_does_not_trigger(self):
        game = make_game(seed=122)
        a, b = game.heroes
        eid = elemental_id()
        e_atk, e_hp = base_stats(eid)
        put(game, B.LIVING_AZERITE, a)
        el = tavern_add(game, a, eid)
        self._cast_coin(game, b)
        self.assertEqual((el.atk, el.health), (e_atk, e_hp))

    def test_non_pool_spell_does_not_trigger(self):
        """Spellcraft 生成法术不是 is_pool_spell → 不广播 tavern_spell_cast。"""
        game = make_game(seed=123)
        a = game.heroes[0]
        eid = elemental_id()
        e_atk, e_hp = base_stats(eid)
        put(game, B.LIVING_AZERITE, a)
        el = tavern_add(game, a, eid)
        s = game.create_spell("BG23_000t", controller=a)
        a.hand.append(s)
        s.zone = Zone.HAND
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual((el.atk, el.health), (e_atk, e_hp))


# ══════════════════════════════════════════════════════════════════════
# BG36_104 Dark Puppeteer
# ══════════════════════════════════════════════════════════════════════


class TestDarkPuppeteer(unittest.TestCase):
    """BG36_104 — 亡语: 酒馆法术额外 +4 Health this game（金色 +8）。"""

    def test_deathrattle_adds_extra_health(self):
        game = make_game(seed=130)
        a = game.heroes[0]
        m = put(game, B.DARK_PUPPETEER, a)
        game.destroy_minion(m)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), 4)

    def test_golden_adds_eight(self):
        game = make_game(seed=131)
        a = game.heroes[0]
        m = put(game, B.DARK_PUPPETEER, a, golden=True)
        game.destroy_minion(m)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), 8)

    def test_stacks_across_two_copies(self):
        game = make_game(seed=132)
        a = game.heroes[0]
        game.destroy_minion(put(game, B.DARK_PUPPETEER, a))
        game.destroy_minion(put(game, B.DARK_PUPPETEER, a))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), 8)


# ══════════════════════════════════════════════════════════════════════
# BG36_101 Unwilling Slacker
# ══════════════════════════════════════════════════════════════════════


class TestUnwillingSlacker(unittest.TestCase):
    """BG36_101 — 亡语: 随机 1-Cost 酒馆法术入手（金色 2 张）。"""

    def test_deathrattle_gets_one_cost_spell(self):
        game = make_game(seed=140)
        a = game.heroes[0]
        before = game.spell_pool.total_remaining()
        m = put(game, B.UNWILLING_SLACKER, a)
        game.destroy_minion(m)
        self.assertEqual(len(a.hand), 1)
        spell = a.hand[0]
        self.assertEqual(get_db().get(spell.card_id).cost, 1)
        self.assertEqual(game.spell_pool.total_remaining(), before - 1)

    def test_golden_gets_two(self):
        game = make_game(seed=141)
        a = game.heroes[0]
        m = put(game, B.UNWILLING_SLACKER, a, golden=True)
        game.destroy_minion(m)
        self.assertEqual(len(a.hand), 2)
        for s in a.hand:
            self.assertEqual(get_db().get(s.card_id).cost, 1)

    def test_full_hand_goes_to_pending_queue(self):
        game = make_game(seed=142)
        a = game.heroes[0]
        m = put(game, B.UNWILLING_SLACKER, a)
        while not a.hand_full():
            a.add_to_hand(game.create_spell("BG28_810", controller=a))
        game.destroy_minion(m)
        self.assertEqual(len(a.hand), 10)
        self.assertEqual(len(game.pending_hand_queue), 1)

    def test_pool_exhausted_no_crash(self):
        game = make_game(seed=143)
        a = game.heroes[0]
        m = put(game, B.UNWILLING_SLACKER, a)
        for cid in one_cost_spell_ids():
            while game.spell_pool.acquire(cid):
                pass
        game.destroy_minion(m)
        self.assertEqual(a.hand, [])


# ══════════════════════════════════════════════════════════════════════
# BG36_098 Zoatroid
# ══════════════════════════════════════════════════════════════════════


class TestZoatroid(unittest.TestCase):
    """BG36_098 — 售出: 获得 0/2 Taunt Tentacle（金色 2 个）。"""

    def test_sell_gets_tentacle(self):
        game = make_game(seed=150)
        a = game.heroes[0]
        z = put(game, B.ZOATROID, a)
        self.assertTrue(game.sell_minion(a, z))
        self.assertEqual(len(a.hand), 1)
        token = a.hand[0]
        self.assertEqual(token.card_id, B.ABERRANT_TENTACLE)
        self.assertEqual((token.atk, token.health), (0, 2))
        self.assertTrue(token.has(GameTag.TAUNT))

    def test_golden_gets_two_tentacles(self):
        game = make_game(seed=151)
        a = game.heroes[0]
        z = put(game, B.ZOATROID, a, golden=True)
        self.assertTrue(game.sell_minion(a, z))
        self.assertEqual([m.card_id for m in a.hand],
                         [B.ABERRANT_TENTACLE, B.ABERRANT_TENTACLE])

    def test_full_hand_goes_to_pending_queue(self):
        game = make_game(seed=152)
        a = game.heroes[0]
        z = put(game, B.ZOATROID, a)
        while not a.hand_full():
            a.add_to_hand(game.create_minion("BG25_008", controller=a))
        self.assertTrue(game.sell_minion(a, z))
        self.assertEqual(len(game.pending_hand_queue), 1)


# ══════════════════════════════════════════════════════════════════════
# BG27_000 Iron Groundskeeper
# ══════════════════════════════════════════════════════════════════════


class TestIronGroundskeeper(unittest.TestCase):
    """BG27_000 — 战吼: 获得 2 张 Fortify（金色 4 张总份数）。"""

    def test_battlecry_gets_two_fortify(self):
        game = make_game(seed=160)
        a = game.heroes[0]
        before = game.spell_pool.total_remaining()
        m = hand_minion(game, a, B.IRON_GROUNDSKEEPER)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual([s.card_id for s in a.hand],
                         [B.FORTIFY, B.FORTIFY])
        self.assertEqual(game.spell_pool.total_remaining(), before - 2)

    def test_golden_gets_four(self):
        """金色 NUM_1=4 = 总份数；引擎战吼 ×2 → 每次按基础 2 份。"""
        game = make_game(seed=161)
        a = game.heroes[0]
        m = hand_minion(game, a, B.IRON_GROUNDSKEEPER, golden=True)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(len(a.hand), 4)
        self.assertTrue(all(s.card_id == B.FORTIFY for s in a.hand))

    def test_full_hand_queues_all_copies(self):
        game = make_game(seed=162)
        a = game.heroes[0]
        m = hand_minion(game, a, B.IRON_GROUNDSKEEPER)
        while not a.hand_full():
            a.add_to_hand(game.create_minion("BG25_008", controller=a))
        self.assertTrue(game.play_minion(a, m))
        # 手牌 10 打出本体后 9 张 → 第 1 份补入（10）、第 2 份排队
        self.assertEqual(len(a.hand), 10)
        self.assertEqual(len(game.pending_hand_queue), 1)

    def test_pool_exhausted_no_crash(self):
        game = make_game(seed=163)
        a = game.heroes[0]
        m = hand_minion(game, a, B.IRON_GROUNDSKEEPER)
        while game.spell_pool.acquire(B.FORTIFY):
            pass
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(a.hand, [])


if __name__ == "__main__":
    unittest.main()
