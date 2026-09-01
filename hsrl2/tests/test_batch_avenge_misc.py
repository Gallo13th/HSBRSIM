"""批次 avenge_misc 卡牌语义测试（作业单 2026-08-21，12 张）。

覆盖: BG22_202 Tad / BG24_715 Patient Scout / BG29_300 Very Hungry
Winterfinner（DEFERRED 断言）/ BG31_816 Fire Baller / BG31_818 Snow
Baller / BG31_835 Deathly Striker / BG32_324 Drustfallen Butcher /
BG33_140 River Skipper / BG36_181 Air Baller / BG36_703 Twilight
Tidehunter / BG36_704 Shamanic Tidecaller / BGS_115 Sellemental。

数值断言一律从 CardDef.num() 计算（TEST_SOP §4）。触发方式: on_sell 走
game.sell_minion; 受伤/Avenge 用 Hit Action 驱动（check_deaths →
_process_single_death → avenge/亡语）; card_played 监听用 play_spell
（未注册脚本的池法术 BG28_604 作施放驱动）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

import hsrl2.constants as C
from hsrl2.actions import Hit
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches.batch_avenge_misc import WATER_DROPLET_ID
from hsrl2.tags import Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

_BUTCHERING_ID = "BG28_604"   # 未注册脚本的池法术——施放驱动用


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero, position: int | None = None,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m, position)
    return m


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def summon_plain(game: Game, hero: Hero, m: Minion,
                 position: int | None = None) -> Minion:
    game.summon(hero, m, position)
    return m


def hand_minion(hero: Hero, m: Minion) -> Minion:
    hero.hand.append(m)
    m.zone = Zone.HAND
    return m


def kill(game: Game, victim: Minion) -> None:
    """Hit 致死 → check_deaths → _process_single_death（Avenge 计数）。"""
    game.run_actions(Hit(victim, victim.health))


def pool_copies(card_id: str) -> int:
    d = get_db().get(card_id)
    tier = min(max(d.tech_level, 1), 7)
    return C.POOL_COPIES_BY_TIER[tier]


def cast_at(game: Game, hero: Hero, target) -> None:
    """施放一张未注册脚本的池法术（占池 → 入手 → play_spell 定向）。"""
    assert game.spell_pool.acquire(_BUTCHERING_ID)
    s = game.create_spell(_BUTCHERING_ID, controller=hero)
    hero.hand.append(s)
    s.zone = Zone.HAND
    assert game.play_spell(hero, s, target=target)


class TestRegistryState(unittest.TestCase):
    """批次注册面: 11 卡 OK（含金色 22 id）; Winterfinner DEFERRED 不注册。"""

    def test_all_cards_registered(self):
        for cid in ("BG22_202", "BG22_202_G", "BG24_715", "BG24_715_G",
                    "BG31_816", "BG31_816_G", "BG31_818", "BG31_818_G",
                    "BG31_835", "BG31_835_G", "BG32_324", "BG32_324_G",
                    "BG33_140", "BG33_140_G", "BG36_181", "BG36_181_G",
                    "BG36_703", "BG36_703_G", "BG36_704", "BG36_704_G",
                    "BGS_115", "TB_BaconUps_156"):
            self.assertIn(cid, REGISTRY)

    def test_winterfinner_unblocked_and_registered(self):
        # damage 事件已覆盖攻击路径（主线修复）→ batch_misc 解冻实现
        self.assertIn("BG29_300", REGISTRY)


class TestTad(unittest.TestCase):
    """BG22_202 — on_sell: get a random Murloc（金色 2）。"""

    def test_sell_gets_pool_murloc(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        tad = put(game, "BG22_202", a)
        self.assertTrue(game.sell_minion(a, tad))
        self.assertEqual(len(a.hand), 1)
        gained = a.hand[0]
        d = get_db().get(gained.card_id)
        self.assertIn(d.race, (Race.MURLOC, Race.ALL))
        self.assertEqual(game.minion_pool.available(gained.card_id),
                         pool_copies(gained.card_id) - 1)

    def test_golden_gets_two(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        tad = put(game, "BG22_202", a, golden=True)
        game.sell_minion(a, tad)
        self.assertEqual(len(a.hand), 2)
        for m in a.hand:
            self.assertIn(get_db().get(m.card_id).race,
                          (Race.MURLOC, Race.ALL))


class TestPatientScout(unittest.TestCase):
    """BG24_715 — on_sell: Discover Tier(=turn) 封顶 6（金色 2 次）。"""

    def test_sell_discovers_current_turn_tier(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        scout = put(game, "BG24_715", a)
        game.turn = 3
        game.sell_minion(a, scout)
        self.assertEqual(len(game.pending_choices), 1)
        choice = game.pending_choices[0]
        self.assertEqual(len(choice.options), 3)
        for opt in choice.options:
            self.assertEqual(get_db().get(opt).tech_level, 3)
        pick = choice.options[0]
        before = game.minion_pool.available(pick)
        choice.choose(0)
        self.assertEqual(a.hand[-1].card_id, pick)
        self.assertEqual(game.minion_pool.available(pick), before - 1)

    def test_tier_capped_at_six(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        scout = put(game, "BG24_715", a)
        game.turn = 9
        game.sell_minion(a, scout)
        for opt in game.pending_choices[0].options:
            self.assertEqual(get_db().get(opt).tech_level, 6)

    def test_golden_two_discoveries(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        scout = put(game, "BG24_715", a, golden=True)
        game.turn = 2
        game.sell_minion(a, scout)
        self.assertEqual(len(game.pending_choices), 2)
        for choice in game.pending_choices:
            for opt in choice.options:
                self.assertEqual(get_db().get(opt).tech_level, 2)


class TestFireBaller(unittest.TestCase):
    """BG31_816 — on_sell +Attack; Improve 共享累积（Playerbound）。"""

    def test_first_sell_base_attack_only(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        d = get_db().get("BG31_816")
        m = summon_plain(game, a, make_minion("M", 5, 5))
        baller = put(game, "BG31_816", a)
        game.sell_minion(a, baller)
        self.assertEqual(m.atk, 5 + d.num(0))
        self.assertEqual(m.max_health, 5)      # num(1) 缺失 = 血分量 0
        self.assertEqual(a.baller_improvement, (d.num(0), 0))

    def test_second_sell_improved(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        d = get_db().get("BG31_816")
        m = summon_plain(game, a, make_minion("M", 5, 5))
        game.sell_minion(a, put(game, "BG31_816", a))
        game.sell_minion(a, put(game, "BG31_816", a))
        # 第二只: (num(0) + I_a)/(num(1) + I_h)，I=(num(0), 0)
        self.assertEqual(m.atk, 5 + d.num(0) + d.num(0) + d.num(0))
        self.assertEqual(m.max_health, 5)
        self.assertEqual(a.baller_improvement, (d.num(0) * 2, 0))

    def test_golden_uses_golden_nums(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        gd = get_db().get("BG31_816_G")
        m = summon_plain(game, a, make_minion("M", 5, 5))
        game.sell_minion(a, put(game, "BG31_816", a, golden=True))
        self.assertEqual(m.atk, 5 + gd.num(0))
        self.assertEqual(a.baller_improvement, (gd.num(0), 0))


class TestSnowBaller(unittest.TestCase):
    """BG31_818 — on_sell +Health（模板索引 {1}）; 与 Fire 共享 Improve。"""

    def test_first_sell_base_health_only(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        d = get_db().get("BG31_818")
        m = summon_plain(game, a, make_minion("M", 5, 5))
        game.sell_minion(a, put(game, "BG31_818", a))
        self.assertEqual(m.atk, 5)             # num(0) 缺失 = 攻分量 0
        self.assertEqual(m.max_health, 5 + d.num(1))
        self.assertEqual(a.baller_improvement, (0, d.num(1)))

    def test_cross_family_improvement_shared(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        fire_d = get_db().get("BG31_816")
        snow_d = get_db().get("BG31_818")
        m = summon_plain(game, a, make_minion("M", 5, 5))
        game.sell_minion(a, put(game, "BG31_818", a))   # I=(0, snow)
        game.sell_minion(a, put(game, "BG31_816", a))   # I 供 Fire 读数
        # Fire 读数含 Snow 贡献的 I_h: atk=num(0)+I_a, hp=num(1)+I_h
        self.assertEqual(m.atk, 5 + fire_d.num(0))
        self.assertEqual(m.max_health,
                         5 + snow_d.num(1)
                         + (fire_d.num(1) or 0) + snow_d.num(1))
        self.assertEqual(a.baller_improvement,
                         (fire_d.num(0), snow_d.num(1)))


class TestAirBaller(unittest.TestCase):
    """BG36_181 — on_sell +{0}/+{1}; improve 贡献 (2,2)。"""

    def test_first_sell_both_components(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        d = get_db().get("BG36_181")
        m = summon_plain(game, a, make_minion("M", 5, 5))
        game.sell_minion(a, put(game, "BG36_181", a))
        self.assertEqual(m.atk, 5 + d.num(0))
        self.assertEqual(m.max_health, 5 + d.num(1))
        self.assertEqual(a.baller_improvement, (d.num(0), d.num(1)))

    def test_air_then_fire_reads_improvement(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        air_d = get_db().get("BG36_181")
        fire_d = get_db().get("BG31_816")
        m = summon_plain(game, a, make_minion("M", 5, 5))
        game.sell_minion(a, put(game, "BG36_181", a))   # I=(2,2)
        game.sell_minion(a, put(game, "BG31_816", a))   # Fire 读 I
        self.assertEqual(m.atk, 5 + air_d.num(0) + fire_d.num(0) + air_d.num(0))
        self.assertEqual(m.max_health, 5 + air_d.num(1) + air_d.num(1))
        self.assertEqual(a.baller_improvement,
                         (air_d.num(0) + fire_d.num(0), air_d.num(1)))


class TestDeathlyStriker(unittest.TestCase):
    """BG31_835 — Avenge(4) 随机 Undead 入手; DR 从手牌复制召唤。"""

    def _avenge_ready(self, game, hero, golden=False):
        striker = put(game, "BG31_835", hero, golden=golden)
        for i in range(4):
            summon_plain(game, hero, make_minion(f"V{i}", 1, 1))
        return striker

    def test_avenge_gets_undead_and_deathrattle_copies_from_hand(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        striker = self._avenge_ready(game, a)
        victims = [m for m in a.board if m is not striker]
        for v in victims:
            kill(game, v)
        self.assertEqual(a.board, [striker])
        # Avenge(4): 1 只随机 Undead 入手（占池）
        self.assertEqual(len(a.hand), 1)
        gained = a.hand[0]
        gd = get_db().get(gained.card_id)
        self.assertIn(gd.race, (Race.UNDEAD, Race.ALL))
        self.assertEqual(game.minion_pool.available(gained.card_id),
                         pool_copies(gained.card_id) - 1)
        # DR: 死亡时从手牌复制召唤（原件留手、副本不占池）
        kill(game, striker)
        self.assertEqual(len(a.board), 1)
        copy = a.board[0]
        self.assertEqual(copy.card_id, gained.card_id)
        self.assertIn(gained, a.hand)
        self.assertEqual(game.minion_pool.available(gained.card_id),
                         pool_copies(gained.card_id) - 1)

    def test_golden_gets_two_undead(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        striker = self._avenge_ready(game, a, golden=True)
        victims = [m for m in a.board if m is not striker]
        for v in victims:
            kill(game, v)
        self.assertEqual(len(a.hand), 2)
        for m in a.hand:
            self.assertIn(get_db().get(m.card_id).race,
                          (Race.UNDEAD, Race.ALL))
        kill(game, striker)
        self.assertEqual(len(a.board), 2)     # 两只均复制召唤
        self.assertEqual({m.card_id for m in a.board},
                         {m.card_id for m in a.hand})

    def test_deathrattle_without_record_noop(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        striker = put(game, "BG31_835", a)
        kill(game, striker)
        self.assertEqual(a.board, [])
        self.assertEqual(a.hand, [])


class TestDrustfallenButcher(unittest.TestCase):
    """BG32_324 — Avenge(4): Get a Butchering（evolution 链 BG28_604）。"""

    def _avenge(self, game, hero, golden=False):
        butcher = put(game, "BG32_324", hero, golden=golden)
        for i in range(4):
            summon_plain(game, hero, make_minion(f"V{i}", 1, 1))
        for v in [m for m in hero.board if m is not butcher]:
            kill(game, v)
        return butcher

    def test_avenge_gets_butchering_occupying_spell_pool(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        avail = game.spell_pool.available(_BUTCHERING_ID)
        self._avenge(game, a)
        self.assertEqual([c.card_id for c in a.hand], [_BUTCHERING_ID])
        self.assertEqual(game.spell_pool.available(_BUTCHERING_ID),
                         avail - 1)

    def test_golden_two_copies(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        avail = game.spell_pool.available(_BUTCHERING_ID)
        self._avenge(game, a, golden=True)
        # 两份均自池 acquire（per-tier 副本充足，金色总额达成）
        self.assertEqual([c.card_id for c in a.hand],
                         [_BUTCHERING_ID, _BUTCHERING_ID])
        self.assertEqual(game.spell_pool.available(_BUTCHERING_ID),
                         avail - 2)


class TestRiverSkipper(unittest.TestCase):
    """BG33_140 — on_sell: get a random Tier 1 minion（金色 2）。"""

    def test_sell_gets_tier_one(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        skipper = put(game, "BG33_140", a)
        game.sell_minion(a, skipper)
        self.assertEqual(len(a.hand), 1)
        gained = a.hand[0]
        self.assertEqual(get_db().get(gained.card_id).tech_level, 1)
        self.assertEqual(game.minion_pool.available(gained.card_id),
                         pool_copies(gained.card_id) - 1)

    def test_golden_gets_two(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        skipper = put(game, "BG33_140", a, golden=True)
        game.sell_minion(a, skipper)
        self.assertEqual(len(a.hand), 2)
        for m in a.hand:
            self.assertEqual(get_db().get(m.card_id).tech_level, 1)


class TestTwilightTidehunter(unittest.TestCase):
    """BG36_703 — 对本体制放法术 → 手牌最左随从 +{0}/+{1}。"""

    def test_spell_on_this_buffs_leftmost_hand_minion(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        d = get_db().get("BG36_703")
        tide = put(game, "BG36_703", a)
        other = summon_plain(game, a, make_minion("O", 4, 4))
        spell = game.create_spell(_BUTCHERING_ID, controller=a)
        a.hand.append(spell)                  # 更靠左的法术被跳过
        left = hand_minion(a, make_minion("L", 2, 3))
        right = hand_minion(a, make_minion("R", 5, 6))
        cast_at(game, a, target=tide)
        self.assertEqual(left.atk, 2 + d.num(0))
        self.assertEqual(left.max_health, 3 + d.num(1))
        self.assertEqual(right.atk, 5)
        self.assertEqual(right.max_health, 6)
        self.assertEqual(tide.atk, d.atk)      # 不 buff 自身
        self.assertEqual(other.atk, 4)

    def test_spell_on_other_target_no_trigger(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        tide = put(game, "BG36_703", a)
        other = summon_plain(game, a, make_minion("O", 4, 4))
        left = hand_minion(a, make_minion("L", 2, 3))
        cast_at(game, a, target=other)
        self.assertEqual(left.atk, 2)
        self.assertEqual(left.max_health, 3)

    def test_golden_uses_golden_nums(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        gd = get_db().get("BG36_703_G")
        tide = put(game, "BG36_703", a, golden=True)
        left = hand_minion(a, make_minion("L", 2, 3))
        cast_at(game, a, target=tide)
        self.assertEqual(left.atk, 2 + gd.num(0))
        self.assertEqual(left.max_health, 3 + gd.num(1))


class TestShamanicTidecaller(unittest.TestCase):
    """BG36_704 — 对 Murloc 施法 → 手牌+棋盘 Murloc 各 +{0}/+{1}。"""

    def test_spell_on_murloc_buffs_murlocs_everywhere(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        d = get_db().get("BG36_704")
        caller = put(game, "BG36_704", a)     # 自身 Murloc
        murloc = summon_plain(game, a,
                              make_minion("M", 2, 3, race=Race.MURLOC))
        beast = summon_plain(game, a,
                             make_minion("B", 4, 5, race=Race.BEAST))
        hand_m = hand_minion(a, make_minion("HM", 2, 2, race=Race.MURLOC))
        hand_b = hand_minion(a, make_minion("HB", 3, 3, race=Race.BEAST))
        cast_at(game, a, target=murloc)
        self.assertEqual(caller.atk, d.atk + d.num(0))       # 含自身
        self.assertEqual(caller.max_health, d.health + d.num(1))
        self.assertEqual(murloc.atk, 2 + d.num(0))           # 含目标
        self.assertEqual(murloc.max_health, 3 + d.num(1))
        self.assertEqual(hand_m.atk, 2 + d.num(0))           # 手牌 Murloc
        self.assertEqual(hand_m.max_health, 2 + d.num(1))
        self.assertEqual(beast.atk, 4)                       # 非 Murloc 不变
        self.assertEqual(hand_b.atk, 3)

    def test_spell_on_non_murloc_no_trigger(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        put(game, "BG36_704", a)
        beast = summon_plain(game, a,
                             make_minion("B", 4, 5, race=Race.BEAST))
        hand_m = hand_minion(a, make_minion("HM", 2, 2, race=Race.MURLOC))
        cast_at(game, a, target=beast)
        self.assertEqual(hand_m.atk, 2)
        self.assertEqual(hand_m.max_health, 2)

    def test_amalgam_target_counts_as_murloc(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        d = get_db().get("BG36_704")
        put(game, "BG36_704", a)
        amalgam = summon_plain(game, a,
                               make_minion("A", 1, 1, race=Race.ALL))
        hand_m = hand_minion(a, make_minion("HM", 2, 2, race=Race.MURLOC))
        cast_at(game, a, target=amalgam)
        self.assertEqual(hand_m.atk, 2 + d.num(0))
        self.assertEqual(hand_m.max_health, 2 + d.num(1))


class TestSellemental(unittest.TestCase):
    """BGS_115 — on_sell: get a 3/3 Elemental token（金色 2）。"""

    def test_sell_gets_water_droplet_token(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        sel = put(game, "BGS_115", a)
        game.sell_minion(a, sel)
        self.assertEqual([c.card_id for c in a.hand], [WATER_DROPLET_ID])
        drop_d = get_db().get(WATER_DROPLET_ID)
        self.assertEqual(a.hand[0].atk, drop_d.atk)
        self.assertEqual(a.hand[0].max_health, drop_d.health)
        self.assertEqual(drop_d.race, Race.ELEMENTAL)
        # token 非池卡: 不占池（available 恒 0）
        self.assertEqual(game.minion_pool.available(WATER_DROPLET_ID), 0)

    def test_golden_gets_two(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        sel = put(game, "BGS_115", a, golden=True)
        game.sell_minion(a, sel)
        self.assertEqual(len(a.hand), 2)
        self.assertEqual({c.card_id for c in a.hand}, {WATER_DROPLET_ID})


if __name__ == "__main__":
    unittest.main()
