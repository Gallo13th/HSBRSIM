"""批次 37x_missing1 行为层测试（5 张高频缺脚本卡 + 1 张替换卡）。

覆盖（全部走真实引擎路径）:
  - 召唤/亡语: 真实 `game.summon` / 真实死亡流程 `game.destroy_minion`
    → `check_deaths` → `trigger_deathrattle` / 真实 `game.run_combat`
  - 攻击触发: 真实 `combat.execute_immediate_attack`（`before_attack` 广播）
  - 购买计数: 真实 `game.start_game` + 真实 `game.buy_from_tavern`
    （`minion_bought` / `spell_bought` 广播）
  - Spellcraft: 真实 `game.play_minion` → `grant_spellcraft_spell`
  - 法术: 真实 `game.play_spell` / `game.cast_spell_effect`
  - 过期: 真实 `game._begin_recruit_for`（`turn_start` 广播）
每类都有**正效果断言**（钩子换 no-op 后必失败）+ 负对照（对手/非目标/
招募期无战斗对/满场落空）。

DEFERRED 台账守卫: BG31_171 已由卡牌审计第二轮（F-18，raw HDT
配对证据）注册；本文件只保留其它卡的 DEFERRED 守卫。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_37x_missing1 as B
from hsrl2.tags import GameTag, Zone

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


def put(game: Game, card_id: str, hero: Hero, position: int | None = None,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m, position)
    return m


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def dummy(hero: Hero, atk: int = 0, health: int = 100) -> Minion:
    m = make_minion("Dummy", atk, health)
    m.game = hero.game
    m.controller = hero
    m.zone = Zone.PLAY
    hero.board.append(m)
    return m


def enter_combat(game: Game, a: Hero, b: Hero) -> None:
    """进入战斗上下文（引擎 run_combat 内部状态的最小等价物）。"""
    game.in_combat = True
    game._active_combat = (a, b)


def hand_card(game: Game, hero: Hero, card_id: str,
              golden: bool = False):
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert hero.add_to_hand(m)
    return m


def hand_spell(game: Game, hero: Hero, card_id: str):
    s = game.create_spell(card_id, controller=hero)
    assert hero.add_to_hand(s)
    return s


def board_ids(hero: Hero) -> list:
    return [m.card_id for m in hero.board]


class TestRegistryAndCardDefs(unittest.TestCase):
    """@engine-only 结构性: 注册表 / DEFERRED 台账 / 数据链 / num 纪律。"""

    def test_registered_ids(self):
        expected = [
            B.SURF_N_SURF, B.SURF_N_SURF_G, B.CRAB_MOUNT, B.CRAB_MOUNT_G,
            B.TWILIGHT_HATCHLING, B.TWILIGHT_HATCHLING_G,
            B.RING_BEARER, B.RING_BEARER_G,
            B.GLUTTONOUS_TROGG, B.GLUTTONOUS_TROGG_G,
            B.PUFFERQUIL, B.PUFFERQUIL_G,
        ]
        for cid in expected:
            self.assertIn(cid, REGISTRY, cid)

    def test_moonsteel_juggernaut_registered_after_audit(self):
        """BG31_171/F-18 已有配对证据（SCN1 当前/SCN2 +6/+12）→ 已注册。"""
        self.assertIn("BG31_171", REGISTRY)
        self.assertIn("BG31_171_G", REGISTRY)
        self.assertTrue(hasattr(B, "MoonsteelJuggernautScript"))

    def test_golden_card_defs_exist(self):
        db = get_db()
        for base, golden in (
                (B.TWILIGHT_HATCHLING, B.TWILIGHT_HATCHLING_G),
                (B.RING_BEARER, B.RING_BEARER_G),
                (B.GLUTTONOUS_TROGG, B.GLUTTONOUS_TROGG_G),
                (B.PUFFERQUIL, B.PUFFERQUIL_G),
                (B.SURF_N_SURF, B.SURF_N_SURF_G)):
            g = db.golden_version(db.get(base))
            self.assertIsNotNone(g, base)
            self.assertEqual(g.id, golden)

    def test_token_card_defs(self):
        db = get_db()
        whelp = db.get(B.TWILIGHT_WHELP)
        self.assertEqual((whelp.atk, whelp.health), (3, 3))
        crab = db.get(B.CRAB)
        self.assertEqual((crab.atk, crab.health), (3, 2))
        crab_g = db.get(B.CRAB_G)
        self.assertEqual((crab_g.atk, crab_g.health), (6, 4))
        ring = db.get(B.SHINY_RING)
        self.assertEqual((ring.num(0), ring.num(1)), (1, 1))
        self.assertTrue(ring.is_pool_spell)

    def test_num_discipline(self):
        db = get_db()
        ht = db.get(B.TWILIGHT_HATCHLING)
        self.assertEqual((ht.num(0), ht.num(1)), (3, 3))
        trogg = db.get(B.GLUTTONOUS_TROGG)
        self.assertEqual(
            (trogg.num(0), trogg.num(1), trogg.num(2)), (4, 4, 4))
        trogg_g = db.get(B.GLUTTONOUS_TROGG_G)
        self.assertEqual(
            (trogg_g.num(0), trogg_g.num(1), trogg_g.num(2)), (4, 8, 8))


# ══════════════════════════════════════════════════════════════════════
# BG34_630 Twilight Hatchling
# ══════════════════════════════════════════════════════════════════════


class TestTwilightHatchling(unittest.TestCase):
    def test_deathrattle_summons_whelp_that_attacks_immediately(self):
        game = make_game(seed=1001)
        a, b = game.heroes
        hatchling = put(game, B.TWILIGHT_HATCHLING, a)
        target = dummy(b, atk=0, health=10)
        enter_combat(game, a, b)
        game.destroy_minion(hatchling)
        # 3/3 Whelp 入场
        self.assertIn(B.TWILIGHT_WHELP, board_ids(a))
        whelp = next(m for m in a.board if m.card_id == B.TWILIGHT_WHELP)
        self.assertEqual((whelp.atk, whelp.max_health), (3, 3))
        # 立即攻击: 敌方唯一目标承受 3 点（0 攻不反击）
        self.assertEqual(target.health, 10 - 3)

    def test_golden_summons_two_whelps_both_attack(self):
        game = make_game(seed=1002)
        a, b = game.heroes
        hatchling = put(game, B.TWILIGHT_HATCHLING, a, golden=True)
        self.assertEqual(hatchling.card_id, B.TWILIGHT_HATCHLING_G)
        target = dummy(b, atk=0, health=20)
        enter_combat(game, a, b)
        game.destroy_minion(hatchling)
        whelps = [m for m in a.board if m.card_id == B.TWILIGHT_WHELP]
        self.assertEqual(len(whelps), 2)
        for w in whelps:
            self.assertEqual((w.atk, w.max_health), (3, 3))
        self.assertEqual(target.health, 20 - 6)     # 两只各打 3

    def test_no_immediate_attack_outside_combat(self):
        game = make_game(seed=1003)
        a, b = game.heroes
        hatchling = put(game, B.TWILIGHT_HATCHLING, a)
        target = dummy(b, atk=0, health=10)
        game.destroy_minion(hatchling)              # 招募期死亡: 无战斗对
        self.assertIn(B.TWILIGHT_WHELP, board_ids(a))
        self.assertEqual(target.health, 10)         # 不攻击

    def test_full_board_summon_fizzles(self):
        game = make_game(seed=1004)
        a, b = game.heroes
        for _ in range(7):
            put(game, B.TWILIGHT_WHELP, a)
        self.assertTrue(a.board_full())
        hatchling = game.create_minion(B.TWILIGHT_HATCHLING, controller=a)

        class _Dead:
            pass

        before = len(a.board)
        B.TwilightHatchlingScript.deathrattle(
            hatchling, game, {"position": 0})
        self.assertEqual(len(a.board), before)      # 满场: 落空不崩溃

    def test_real_combat_summons_whelp(self):
        """真实 run_combat 路径: 战斗死亡 → 召唤 Whelp（事件探针）。"""
        game = make_game(seed=1005)
        a, b = game.heroes
        hatchling = put(game, B.TWILIGHT_HATCHLING, a)
        dummy(b, atk=8, health=8)                   # b 会打死 hatchling
        summoned = []
        from hsrl2.events import SUMMON, Listener

        game.events.register(Listener(
            event=SUMMON, owner=a,
            callback=lambda g, minion=None, **kw: summoned.append(
                getattr(minion, "card_id", None))))
        game.run_combat(a, b)
        self.assertIn(B.TWILIGHT_WHELP, summoned)


# ══════════════════════════════════════════════════════════════════════
# BG34_921 Ring Bearer
# ══════════════════════════════════════════════════════════════════════


class TestRingBearer(unittest.TestCase):
    def test_friendly_attack_casts_shiny_ring_before_damage(self):
        game = make_game(seed=1101)
        a, b = game.heroes
        bearer = put(game, B.RING_BEARER, a)
        attacker = put(game, B.TWILIGHT_WHELP, a)   # 3/3
        target = dummy(b, atk=0, health=30)
        enter_combat(game, a, b)
        from hsrl2.combat import execute_immediate_attack
        execute_immediate_attack(game, attacker, target)
        # 全板 +1/+1（含攻方/自身）; 攻方本次伤害含增益
        self.assertEqual(attacker.atk, 3 + 1)
        self.assertEqual(bearer.atk, 5 + 1)
        self.assertEqual(bearer.max_health, 10 + 1)
        self.assertEqual(target.health, 30 - 4)

    def test_opponent_attack_does_not_trigger(self):
        game = make_game(seed=1102)
        a, b = game.heroes
        bearer = put(game, B.RING_BEARER, a)
        enemy = dummy(b, atk=2, health=10)
        our_dummy = dummy(a, atk=0, health=30)
        enter_combat(game, a, b)
        from hsrl2.combat import execute_immediate_attack
        execute_immediate_attack(game, enemy, our_dummy)
        self.assertEqual(bearer.atk, 5)
        self.assertEqual(bearer.max_health, 10)
        self.assertEqual(our_dummy.health, 30 - 2)  # 未增益

    def test_golden_casts_twice(self):
        game = make_game(seed=1103)
        a, b = game.heroes
        bearer = put(game, B.RING_BEARER, a, golden=True)
        self.assertEqual(bearer.card_id, B.RING_BEARER_G)
        attacker = put(game, B.TWILIGHT_WHELP, a)
        target = dummy(b, atk=0, health=30)
        enter_combat(game, a, b)
        from hsrl2.combat import execute_immediate_attack
        execute_immediate_attack(game, attacker, target)
        self.assertEqual(attacker.atk, 3 + 2)
        self.assertEqual(bearer.atk, 10 + 2)
        self.assertEqual(target.health, 30 - 5)

    def test_self_attack_triggers(self):
        game = make_game(seed=1104)
        a, b = game.heroes
        bearer = put(game, B.RING_BEARER, a)
        target = dummy(b, atk=0, health=30)
        enter_combat(game, a, b)
        from hsrl2.combat import execute_immediate_attack
        execute_immediate_attack(game, bearer, target)
        self.assertEqual(bearer.atk, 5 + 1)         # 自身也吃 Shiny Ring
        self.assertEqual(target.health, 30 - 6)     # 伤害含增益

    def test_real_combat_rolls_back(self):
        """完整 run_combat: 战斗内 buff 战后回滚（RULES §3.5）。"""
        game = make_game(seed=1105)
        a, b = game.heroes
        bearer = put(game, B.RING_BEARER, a)
        attacker = put(game, B.TWILIGHT_WHELP, a)
        dummy(b, atk=0, health=40)
        game.run_combat(a, b)
        self.assertEqual(bearer.atk, 5)
        self.assertEqual(bearer.max_health, 10)
        self.assertEqual(attacker.atk, 3)

    def test_dead_ring_bearer_stops_triggering(self):
        game = make_game(seed=1106)
        a, b = game.heroes
        bearer = put(game, B.RING_BEARER, a)
        attacker = put(game, B.TWILIGHT_WHELP, a)
        target = dummy(b, atk=0, health=30)
        enter_combat(game, a, b)
        game.destroy_minion(bearer)                 # 离场 → 监听器注销
        from hsrl2.combat import execute_immediate_attack
        execute_immediate_attack(game, attacker, target)
        self.assertEqual(attacker.atk, 3)
        self.assertEqual(target.health, 30 - 3)


# ══════════════════════════════════════════════════════════════════════
# BG35_801 Gluttonous Trogg
# ══════════════════════════════════════════════════════════════════════


class TestGluttonousTrogg(unittest.TestCase):
    def _started_game(self, seed: int):
        game = make_game(seed=seed)
        game.start_game()
        a, b = game.heroes
        a.gold = 60
        return game, a, b

    @staticmethod
    def _buy_one(game: Game, hero: Hero) -> bool:
        if not hero.tavern:
            game.refresh_tavern(hero)
        for e in list(hero.tavern):
            if game.buy_from_tavern(hero, e):
                return True
        return False

    def test_triggers_after_fourth_buy_once(self):
        game, a, b = self._started_game(seed=1201)
        trogg = put(game, B.GLUTTONOUS_TROGG, a)
        for _ in range(3):
            self.assertTrue(self._buy_one(game, a))
        self.assertEqual((trogg.atk, trogg.max_health), (2, 3))   # 未触发
        self.assertTrue(self._buy_one(game, a))                   # 第 4 张
        self.assertEqual((trogg.atk, trogg.max_health), (2 + 4, 3 + 4))
        # 一次性: 继续买（含刷新后）不再触发
        a.gold = 60
        for _ in range(3):
            self.assertTrue(self._buy_one(game, a))
        self.assertEqual((trogg.atk, trogg.max_health), (6, 7))

    def test_counts_spell_purchases_too(self):
        game, a, b = self._started_game(seed=1202)
        trogg = put(game, B.GLUTTONOUS_TROGG, a)
        # 先买馆内法术（tavern 含 1 张酒馆法术）
        from hsrl2.spell import Spell

        spells = [e for e in a.tavern if isinstance(e, Spell)]
        self.assertTrue(spells)
        self.assertTrue(game.buy_from_tavern(a, spells[0]))
        for _ in range(3):
            self.assertTrue(self._buy_one(game, a))
        self.assertEqual((trogg.atk, trogg.max_health), (6, 7))

    def test_minion_purchases_alone_trigger(self):
        game, a, b = self._started_game(seed=1203)
        trogg = put(game, B.GLUTTONOUS_TROGG, a)
        from hsrl2.minion import Minion

        bought = 0
        while bought < 4:
            mins = [e for e in a.tavern if isinstance(e, Minion)]
            if not mins:
                game.refresh_tavern(a)
                mins = [e for e in a.tavern if isinstance(e, Minion)]
            self.assertTrue(game.buy_from_tavern(a, mins[0]))
            bought += 1
        self.assertEqual((trogg.atk, trogg.max_health), (6, 7))

    def test_golden_gains_eight_eight(self):
        game, a, b = self._started_game(seed=1204)
        trogg = put(game, B.GLUTTONOUS_TROGG, a, golden=True)
        self.assertEqual(trogg.card_id, B.GLUTTONOUS_TROGG_G)
        for _ in range(4):
            self.assertTrue(self._buy_one(game, a))
        self.assertEqual((trogg.atk, trogg.max_health), (4 + 8, 6 + 8))

    def test_opponent_purchases_do_not_count(self):
        game, a, b = self._started_game(seed=1205)
        trogg = put(game, B.GLUTTONOUS_TROGG, a)
        b.gold = 60
        for _ in range(4):
            self.assertTrue(self._buy_one(game, b))
        self.assertEqual((trogg.atk, trogg.max_health), (2, 3))

    def test_purchases_before_summon_do_not_count(self):
        game, a, b = self._started_game(seed=1206)
        for _ in range(4):
            self.assertTrue(self._buy_one(game, a))
        trogg = put(game, B.GLUTTONOUS_TROGG, a)
        self.assertEqual((trogg.atk, trogg.max_health), (2, 3))


# ══════════════════════════════════════════════════════════════════════
# BG27_004 Surf n' Surf + BG27_004t/Gt Crab Mount
# ══════════════════════════════════════════════════════════════════════


class TestSurfNSurf(unittest.TestCase):
    def test_playing_grants_spellcraft_spell(self):
        game = make_game(seed=1301)
        a, b = game.heroes
        m = hand_card(game, a, B.SURF_N_SURF)
        self.assertTrue(game.play_minion(a, m))
        spells = [e for e in a.hand if e.card_id == B.CRAB_MOUNT]
        self.assertEqual(len(spells), 1)
        self.assertTrue(spells[0].has(GameTag.SPELLCRAFT))

    def test_golden_grants_golden_spell(self):
        game = make_game(seed=1302)
        a, b = game.heroes
        m = hand_card(game, a, B.SURF_N_SURF, golden=True)
        self.assertTrue(game.play_minion(a, m))
        self.assertEqual(m.card_id, B.SURF_N_SURF_G)
        self.assertTrue([e for e in a.hand if e.card_id == B.CRAB_MOUNT_G])

    def test_next_turn_generates_another_spell(self):
        game = make_game(seed=1303)
        game.start_game()
        a, b = game.heroes
        m = hand_card(game, a, B.SURF_N_SURF)
        self.assertTrue(game.play_minion(a, m))
        a.hand.clear()                              # 清掉立即授予的那张
        game._begin_recruit_for(a)                  # 真实回合开始
        self.assertTrue([e for e in a.hand if e.card_id == B.CRAB_MOUNT])


class TestCrabMount(unittest.TestCase):
    def _cast(self, game: Game, a: Hero, spell_id: str,
              target: Minion) -> None:
        spell = hand_spell(game, a, spell_id)
        self.assertTrue(game.play_spell(a, spell, target=target))

    def test_grants_deathrattle_summons_3_2_crab(self):
        game = make_game(seed=1401)
        a, b = game.heroes
        target = put(game, B.TWILIGHT_HATCHLING, a)   # 1/1 靶子
        self._cast(game, a, B.CRAB_MOUNT, target)
        self.assertTrue(target.has(GameTag.DEATHRATTLE))
        dummy(b, atk=0, health=10)
        enter_combat(game, a, b)
        game.destroy_minion(target)
        crabs = [m for m in a.board if m.card_id == B.CRAB]
        self.assertEqual(len(crabs), 1)
        self.assertEqual((crabs[0].atk, crabs[0].max_health), (3, 2))

    def test_golden_spell_summons_6_4_crab(self):
        game = make_game(seed=1402)
        a, b = game.heroes
        target = put(game, B.TWILIGHT_HATCHLING, a)
        self._cast(game, a, B.CRAB_MOUNT_G, target)
        dummy(b, atk=0, health=10)
        enter_combat(game, a, b)
        game.destroy_minion(target)
        crabs = [m for m in a.board if m.card_id == B.CRAB_G]
        self.assertEqual(len(crabs), 1)
        self.assertEqual((crabs[0].atk, crabs[0].max_health), (6, 4))

    def test_expires_at_next_turn_start(self):
        game = make_game(seed=1403)
        a, b = game.heroes
        target = put(game, B.TWILIGHT_WHELP, a)      # 无原生亡语
        self.assertFalse(target.has(GameTag.DEATHRATTLE))
        self._cast(game, a, B.CRAB_MOUNT, target)
        self.assertTrue(target.has(GameTag.DEATHRATTLE))
        game._begin_recruit_for(a)                  # 真实下一回合开始
        self.assertFalse(target.has(GameTag.DEATHRATTLE))
        self.assertNotIn("deathrattle", target._script_overrides)

    def test_native_deathrattle_tag_preserved_after_expiry(self):
        """目标原生带亡语: 过期只移除授予的附加，不清原生 DEATHRATTLE。"""
        game = make_game(seed=1407)
        a, b = game.heroes
        target = put(game, B.TWILIGHT_HATCHLING, a)  # 原生亡语
        self.assertTrue(target.has(GameTag.DEATHRATTLE))
        self._cast(game, a, B.CRAB_MOUNT, target)
        game._begin_recruit_for(a)
        self.assertTrue(target.has(GameTag.DEATHRATTLE))
        self.assertNotIn("deathrattle", target._script_overrides)

    def test_stacks_with_native_deathrattle(self):
        """同一目标两次 Crab Mount + 原生亡语 → 全部结算（顺序: 原生先）。"""
        game = make_game(seed=1404)
        a, b = game.heroes
        hatchling = put(game, B.TWILIGHT_HATCHLING, a)  # 原生: 召唤 Whelp
        self._cast(game, a, B.CRAB_MOUNT, hatchling)
        self._cast(game, a, B.CRAB_MOUNT, hatchling)
        dummy(b, atk=0, health=50)
        enter_combat(game, a, b)
        game.destroy_minion(hatchling)
        self.assertIn(B.TWILIGHT_WHELP, board_ids(a))
        self.assertEqual(
            len([m for m in a.board if m.card_id == B.CRAB]), 2)

    def test_no_target_fizzles(self):
        game = make_game(seed=1405)
        a, b = game.heroes
        spell = hand_spell(game, a, B.CRAB_MOUNT)
        # 无目标且无候选 → 引擎落空，法术照常消耗
        self.assertTrue(game.play_spell(a, spell))
        self.assertNotIn(spell, a.hand)

    def test_crab_fills_freed_slot_on_full_board(self):
        """满场时死亡触发: 死者让出的板位立即被 Crab 填上（官方亡语召唤
        填位语义——与"满场落空"区分: 落空只发生在无空位可填时）。"""
        game = make_game(seed=1406)
        a, b = game.heroes
        target = put(game, B.TWILIGHT_WHELP, a)     # 无原生亡语
        self._cast(game, a, B.CRAB_MOUNT, target)
        dummy(b, atk=0, health=10)
        for _ in range(6):                          # target + 6 = 满 7
            put(game, B.TWILIGHT_WHELP, a)
        self.assertTrue(a.board_full())
        enter_combat(game, a, b)
        game.destroy_minion(target)                 # 让出 1 个板位
        self.assertEqual(len(a.board), 7)
        self.assertEqual(
            len([m for m in a.board if m.card_id == B.CRAB]), 1)


# ══════════════════════════════════════════════════════════════════════
# BG25_039 Pufferquil
# ══════════════════════════════════════════════════════════════════════


class TestPufferquil(unittest.TestCase):
    #: 定向法术（Angler's Lure, +2/+6 与 Taunt; needs_target=True）
    TARGET_SPELL = "BG23_004t"

    def test_spell_on_this_grants_venomous_until_next_turn(self):
        game = make_game(seed=1501)
        a, b = game.heroes
        puffer = put(game, B.PUFFERQUIL, a)
        spell = hand_spell(game, a, self.TARGET_SPELL)
        self.assertTrue(game.play_spell(a, spell, target=puffer))
        self.assertTrue(puffer.has(GameTag.VENOMOUS))
        game._begin_recruit_for(a)                  # 下一回合开始
        self.assertFalse(puffer.has(GameTag.VENOMOUS))

    def test_spell_on_other_minion_does_not_trigger(self):
        game = make_game(seed=1502)
        a, b = game.heroes
        puffer = put(game, B.PUFFERQUIL, a)
        other = put(game, B.TWILIGHT_WHELP, a)
        spell = hand_spell(game, a, self.TARGET_SPELL)
        self.assertTrue(game.play_spell(a, spell, target=other))
        self.assertFalse(puffer.has(GameTag.VENOMOUS))

    def test_effect_cast_path_also_triggers(self):
        game = make_game(seed=1503)
        a, b = game.heroes
        puffer = put(game, B.PUFFERQUIL, a)
        self.assertTrue(game.cast_spell_effect(a, "BG20_GEM", target=puffer))
        self.assertTrue(puffer.has(GameTag.VENOMOUS))

    def test_preexisting_venomous_survives_expiry(self):
        game = make_game(seed=1504)
        a, b = game.heroes
        puffer = put(game, B.PUFFERQUIL, a)
        puffer.set(GameTag.VENOMOUS, True)          # 原生/其它来源毒液
        spell = hand_spell(game, a, self.TARGET_SPELL)
        self.assertTrue(game.play_spell(a, spell, target=puffer))
        game._begin_recruit_for(a)
        self.assertTrue(puffer.has(GameTag.VENOMOUS))

    def test_golden_venomous_is_permanent(self):
        game = make_game(seed=1505)
        a, b = game.heroes
        puffer = put(game, B.PUFFERQUIL, a, golden=True)
        self.assertEqual(puffer.card_id, B.PUFFERQUIL_G)
        spell = hand_spell(game, a, self.TARGET_SPELL)
        self.assertTrue(game.play_spell(a, spell, target=puffer))
        self.assertTrue(puffer.has(GameTag.VENOMOUS))
        game._begin_recruit_for(a)
        game._begin_recruit_for(b)
        self.assertTrue(puffer.has(GameTag.VENOMOUS))

    def test_combat_venomous_kills_after_gain(self):
        """获得 Venomous 后本场战斗毒液生效（真实单次攻击）。"""
        game = make_game(seed=1506)
        a, b = game.heroes
        puffer = put(game, B.PUFFERQUIL, a)
        spell = hand_spell(game, a, self.TARGET_SPELL)
        self.assertTrue(game.play_spell(a, spell, target=puffer))
        enemy = dummy(b, atk=0, health=30)
        enter_combat(game, a, b)
        from hsrl2.combat import execute_immediate_attack
        execute_immediate_attack(game, puffer, enemy)
        self.assertTrue(enemy.dead)                 # 毒液致命


if __name__ == "__main__":                          # pragma: no cover
    unittest.main()
