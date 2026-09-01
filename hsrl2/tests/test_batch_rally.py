"""批次 rally 语义测试（作业单 2026-08-21，10 张 Rally 池随从）。

覆盖: BG25_016 Sin'dorei Straight Shot / BG27_017 Obsidian Ravager /
BG33_318 Bile Spitter / BG33_323 Dustbone Devastator / BG33_822 Bigwig
Bandit / BG33_886 Tusked Camper / BG33_924 Blue Whelp / BG34_140 Expert
Aviator / BG34_319 Highkeeper Ra / BG34_320 The Last One Standing。

Rally 触发驱动: CombatScheduler(game,a,b)._execute_attack(attacker,
defender) 单次攻击（TEST_SOP 经验库——rally 在伤害前触发）; 数值
期望一律 CardDef.num() 计算。已知数据缺口（报告主线）: 金色卡定义
不携带关键词标志 → 金色断言仅覆盖脚本行为（rally 经 card_id 绑定）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.combat import CombatScheduler
from hsrl2.constants import BOARD_SIZE
from hsrl2.db import CardDB
from hsrl2.events import KEYWORD_LOST, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY, bind_all
from hsrl2.scripts.batches.batch_rally import (
    ALL_BG_RACES,
    BOUNTY_SPELL_IDS,
)
from hsrl2.tags import GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
XML_PATH = ROOT / "hsdata" / "CardDefs.xml"

GEM_ID = "BG20_GEM"   # 血宝石基础值唯一来源（bloodgem.py 同源）

_db = None


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


def dummy(hero: Hero, health: int = 100) -> Minion:
    return make_minion("Dummy", 0, health)


def gem_values(game: Game, hero: Hero) -> tuple[int, int]:
    d = get_db().get(GEM_ID)
    return (d.num(0) + hero.get(GameTag.BLOOD_GEM_BONUS_ATK, 0),
            d.num(1) + hero.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0))


class TestSindoreiStraightShot(unittest.TestCase):
    """BG25_016 — DS+Windfury; Rally: Remove Reborn and Taunt from
    the target."""

    def test_rally_removes_reborn_and_taunt_from_target(self):
        game = make_game(seed=100)
        a, b = game.heroes
        shot = put(game, "BG25_016", a)
        target = dummy(b)
        target.set(GameTag.REBORN, True)
        target.set(GameTag.TAUNT, True)
        game.summon(b, target)
        CombatScheduler(game, a, b)._execute_attack(shot, target)
        self.assertFalse(target.has(GameTag.REBORN))
        self.assertFalse(target.has(GameTag.TAUNT))
        # DS/Windfury 来自 data 权威关键词（攻击不消耗自身 DS）
        self.assertTrue(shot.has(GameTag.DIVINE_SHIELD))
        self.assertTrue(shot.has(GameTag.WINDFURY))

    def test_rally_target_without_keywords_no_loss_event(self):
        game = make_game(seed=101)
        a, b = game.heroes
        shot = put(game, "BG25_016", a)
        target = dummy(b)
        game.summon(b, target)
        losses = []
        game.events.register(Listener(
            event=KEYWORD_LOST, owner=target,
            callback=lambda g, minion=None, tag=None, **kw:
                losses.append(tag)))
        CombatScheduler(game, a, b)._execute_attack(shot, target)
        self.assertEqual(losses, [])   # 未持有的关键词不产生事件


class TestObsidianRavager(unittest.TestCase):
    """BG27_017 — Rally: Deal damage equal to this minion's Attack to
    the target and an adjacent minion."""

    def test_rally_hits_target_and_single_adjacent_before_attack(self):
        game = make_game(seed=102)
        a, b = game.heroes
        ravager = put(game, "BG27_017", a)
        atk = get_db().get("BG27_017").atk
        target = dummy(b)
        game.summon(b, target)                       # pos 0
        neighbor = dummy(b)
        game.summon(b, neighbor)                     # pos 1 唯一相邻
        CombatScheduler(game, a, b)._execute_attack(ravager, target)
        # rally 独立伤害 + 攻击伤害（rally 先于伤害，RULES §6.16）
        self.assertEqual(target.health, 100 - atk * 2)
        self.assertEqual(neighbor.health, 100 - atk)  # 仅 rally 伤害
        self.assertEqual(ravager.health,
                         get_db().get("BG27_017").health)   # 0 攻无反击

    def test_rally_without_adjacent_hits_target_only(self):
        game = make_game(seed=103)
        a, b = game.heroes
        ravager = put(game, "BG27_017", a)
        target = dummy(b)
        game.summon(b, target)
        CombatScheduler(game, a, b)._execute_attack(ravager, target)
        self.assertEqual(target.health,
                         100 - get_db().get("BG27_017").atk * 2)

    def test_golden_rally_hits_all_neighbors(self):
        game = make_game(seed=104)
        a, b = game.heroes
        ravager = put(game, "BG27_017", a, golden=True)
        self.assertEqual(ravager.card_id, "BG27_017_G")
        atk = get_db().get("BG27_017_G").atk
        left, target, right = dummy(b), dummy(b), dummy(b)
        for m in (left, target, right):
            game.summon(b, m)
        CombatScheduler(game, a, b)._execute_attack(ravager, target)
        self.assertEqual(target.health, 100 - atk * 2)
        self.assertEqual(left.health, 100 - atk)
        self.assertEqual(right.health, 100 - atk)


class TestBileSpitter(unittest.TestCase):
    """BG33_318 — Venomous; Rally: Give another friendly Murloc
    Venomous."""

    def test_rally_gives_another_murloc_venomous(self):
        game = make_game(seed=105)
        a, b = game.heroes
        spitter = put(game, "BG33_318", a)
        murloc = make_minion("Murloc", 1, 5, race=Race.MURLOC)
        game.summon(a, murloc)
        CombatScheduler(game, a, b)._execute_attack(spitter, dummy(b))
        self.assertTrue(murloc.has(GameTag.VENOMOUS))
        self.assertFalse(murloc.has(GameTag.VENOMOUS_CONSUMED))

    def test_rally_no_other_murloc_no_effect(self):
        game = make_game(seed=106)
        a, b = game.heroes
        spitter = put(game, "BG33_318", a)
        beast = make_minion("Beast", 1, 1, race=Race.BEAST)
        game.summon(a, beast)
        CombatScheduler(game, a, b)._execute_attack(spitter, dummy(b))
        self.assertFalse(beast.has(GameTag.VENOMOUS))

    def test_amalgam_counts_as_murloc(self):
        game = make_game(seed=107)
        a, b = game.heroes
        spitter = put(game, "BG33_318", a)
        amalgam = make_minion("Amal", 1, 1, race=Race.ALL)
        game.summon(a, amalgam)
        CombatScheduler(game, a, b)._execute_attack(spitter, dummy(b))
        self.assertTrue(amalgam.has(GameTag.VENOMOUS))

    def test_granted_venomous_rolls_back_after_combat(self):
        game = make_game(seed=108)
        a, b = game.heroes
        spitter = put(game, "BG33_318", a, position=0)   # 首攻=spitter
        murloc = make_minion("Murloc", 1, 5, race=Race.MURLOC)
        game.summon(a, murloc)
        game.summon(b, dummy(b))
        game.run_combat(a, b)
        # RULES §3.5: 战斗内授予的 Venomous 快照恢复回滚;
        # spitter 自身 Venomous 是战前快照内容 → 保留
        self.assertFalse(murloc.has(GameTag.VENOMOUS))
        self.assertTrue(spitter.has(GameTag.VENOMOUS))

    def test_golden_rally_gives_two_murlocs(self):
        game = make_game(seed=109)
        a, b = game.heroes
        spitter = put(game, "BG33_318", a, golden=True)
        m1 = make_minion("M1", 1, 5, race=Race.MURLOC)
        m2 = make_minion("M2", 1, 5, race=Race.MURLOC)
        game.summon(a, m1)
        game.summon(a, m2)
        CombatScheduler(game, a, b)._execute_attack(spitter, dummy(b))
        self.assertTrue(m1.has(GameTag.VENOMOUS))
        self.assertTrue(m2.has(GameTag.VENOMOUS))


class TestDustboneDevastator(unittest.TestCase):
    """BG33_323 — Rally: Your Undead have +{0} Attack this game
    (wherever they are)."""

    def _undead_hand_minion(self, game, hero) -> Minion:
        d = next(d for d in get_db().pool_minions()
                 if d.race == Race.UNDEAD)
        m = game.create_minion(d.id, controller=hero)
        hero.add_to_hand(m)
        return m

    def test_rally_undead_aura_attack_damage_and_wherever(self):
        game = make_game(seed=110)
        a, b = game.heroes
        d = get_db().get("BG33_323")
        dustbone = put(game, "BG33_323", a)
        beast = make_minion("Beast", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        hand_undead = self._undead_hand_minion(game, a)
        target = dummy(b)
        game.summon(b, target)
        CombatScheduler(game, a, b)._execute_attack(dustbone, target)
        # rally 光环先于伤害 → 本次攻击已含 +num(0)
        self.assertEqual(target.health, 100 - (d.atk + d.num(0)))
        # wherever they are: 手牌 Undead 同享; 非 Undead 不受
        self.assertEqual(hand_undead.atk,
                         get_db().get(hand_undead.card_id).atk + d.num(0))
        self.assertEqual(beast.atk, 2)

    def test_aura_persists_after_combat(self):
        game = make_game(seed=111)
        a, b = game.heroes
        d = get_db().get("BG33_323")
        dustbone = put(game, "BG33_323", a)
        # 低血靶: 首次攻击（含光环）即击杀 → 恰好 1 次 Rally
        game.summon(b, dummy(b, health=d.atk + d.num(0)))
        game.run_combat(a, b)
        self.assertEqual(dustbone.atk, d.atk + d.num(0))   # this game

    def test_golden_aura_uses_golden_value(self):
        game = make_game(seed=112)
        a, b = game.heroes
        dg = get_db().get("BG33_323_G")
        dustbone = put(game, "BG33_323", a, golden=True)
        target = dummy(b)
        game.summon(b, target)
        CombatScheduler(game, a, b)._execute_attack(dustbone, target)
        self.assertEqual(target.health, 100 - (dg.atk + dg.num(0)))


class TestBigwigBandit(unittest.TestCase):
    """BG33_822 — Rally: Get a random Bounty."""

    def test_rally_gets_bounty_into_hand_and_occupies_pool(self):
        game = make_game(seed=113)
        a, b = game.heroes
        snap = {cid: game.spell_pool.available(cid)
                for cid in BOUNTY_SPELL_IDS}
        bandit = put(game, "BG33_822", a)
        CombatScheduler(game, a, b)._execute_attack(bandit, dummy(b))
        bounties = [c for c in a.hand if c.card_id in BOUNTY_SPELL_IDS]
        self.assertEqual(len(bounties), 1)
        self.assertEqual(bounties[0].zone, Zone.HAND)
        self.assertEqual(game.spell_pool.available(bounties[0].card_id),
                         snap[bounties[0].card_id] - 1)

    def test_rally_pool_drained_fallback_generation(self):
        game = make_game(seed=114)
        a, b = game.heroes
        for cid in BOUNTY_SPELL_IDS:
            while game.spell_pool.available(cid):   # 抽干（per-tier 副本）
                assert game.spell_pool.acquire(cid)
        bandit = put(game, "BG33_822", a)
        CombatScheduler(game, a, b)._execute_attack(bandit, dummy(b))
        bounties = [c for c in a.hand if c.card_id in BOUNTY_SPELL_IDS]
        self.assertEqual(len(bounties), 1)   # 池空退化: 不占池生成

    def test_golden_rally_gets_two_distinct_bounties(self):
        game = make_game(seed=115)
        a, b = game.heroes
        bandit = put(game, "BG33_822", a, golden=True)
        CombatScheduler(game, a, b)._execute_attack(bandit, dummy(b))
        bounties = [c for c in a.hand if c.card_id in BOUNTY_SPELL_IDS]
        self.assertEqual(len(bounties), 2)
        self.assertEqual(len({c.card_id for c in bounties}), 2)

    @unittest.skipUnless(XML_PATH.exists(), "hsdata CardDefs.xml absent")
    def test_bounty_ids_match_xml_bacon_bounty_tag(self):
        """漂移守护: BOUNTY_SPELL_IDS == XML BACON_BOUNTY(4231) 且
        CARDTYPE=42 的全集（引擎未导出该 tag，防补丁漂移）。"""
        import re
        xml = XML_PATH.read_text(encoding="utf-8")
        found = set()
        for m in re.finditer(
                r'<Entity CardID="([^"]+)"[^>]*>(.*?)</Entity>', xml,
                re.S):
            cid, body = m.group(1), m.group(2)
            if ('name="BACON_BOUNTY"' in body
                    and re.search(r'name="CARDTYPE" type="Int" value="42"',
                                  body)):
                found.add(cid)
        self.assertEqual(found, set(BOUNTY_SPELL_IDS))


class TestTuskedCamper(unittest.TestCase):
    """BG33_886 — Rally: This plays a Blood Gem on itself."""

    def test_rally_plays_blood_gem_on_itself(self):
        game = make_game(seed=116)
        a, b = game.heroes
        d = get_db().get("BG33_886")
        camper = put(game, "BG33_886", a)
        CombatScheduler(game, a, b)._execute_attack(camper, dummy(b))
        g_atk, g_health = gem_values(game, a)
        self.assertEqual(camper.atk, d.atk + g_atk)
        self.assertEqual(camper.max_health, d.health + g_health)

    def test_hero_blood_gem_bonus_applies(self):
        game = make_game(seed=117)
        a, b = game.heroes
        a.set(GameTag.BLOOD_GEM_BONUS_ATK, 5)
        a.set(GameTag.BLOOD_GEM_BONUS_HEALTH, 3)
        d = get_db().get("BG33_886")
        camper = put(game, "BG33_886", a)
        CombatScheduler(game, a, b)._execute_attack(camper, dummy(b))
        g_atk, g_health = gem_values(game, a)
        self.assertEqual((g_atk, g_health),
                         (get_db().get(GEM_ID).num(0) + 5,
                          get_db().get(GEM_ID).num(1) + 3))
        self.assertEqual(camper.atk, d.atk + g_atk)
        self.assertEqual(camper.max_health, d.health + g_health)

    def test_golden_rally_plays_two_gems(self):
        game = make_game(seed=118)
        a, b = game.heroes
        dg = get_db().get("BG33_886_G")
        camper = put(game, "BG33_886", a, golden=True)
        CombatScheduler(game, a, b)._execute_attack(camper, dummy(b))
        g_atk, g_health = gem_values(game, a)
        self.assertEqual(camper.atk, dg.atk + g_atk * 2)
        self.assertEqual(camper.max_health, dg.health + g_health * 2)


class TestBlueWhelp(unittest.TestCase):
    """BG33_924 — Rally: Your Tavern spells give an extra +{0} Health
    this game."""

    def test_rally_stacks_extra_health_tag(self):
        game = make_game(seed=119)
        a, b = game.heroes
        d = get_db().get("BG33_924")
        whelp = put(game, "BG33_924", a)
        CombatScheduler(game, a, b)._execute_attack(whelp, dummy(b))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH),
                         d.num(0))
        CombatScheduler(game, a, b)._execute_attack(whelp, dummy(b))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH),
                         d.num(0) * 2)   # 每次 Rally 叠加

    def test_extra_health_feeds_tavern_spell_buff(self):
        from hsrl2.actions.racefx import tavern_spell_buff
        game = make_game(seed=120)
        a, b = game.heroes
        d = get_db().get("BG33_924")
        whelp = put(game, "BG33_924", a)
        CombatScheduler(game, a, b)._execute_attack(whelp, dummy(b))
        buff = tavern_spell_buff(whelp, 2, 3)
        self.assertEqual(buff.atk, 2)
        self.assertEqual(buff.health, 3 + d.num(0))

    def test_golden_uses_golden_value(self):
        game = make_game(seed=121)
        a, b = game.heroes
        dg = get_db().get("BG33_924_G")
        whelp = put(game, "BG33_924", a, golden=True)
        CombatScheduler(game, a, b)._execute_attack(whelp, dummy(b))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH),
                         dg.num(0))


class TestExpertAviator(unittest.TestCase):
    """BG34_140 — Rally: Summon the highest-Attack minion from your
    hand for this combat only（战斗副本模型，见脚本 docstring）。"""

    @staticmethod
    def _hand_minion(game, hero, card_id) -> Minion:
        # 真实池卡（副本经 create_minion 复制，需 db 可查的 card_id）
        m = game.create_minion(card_id, controller=hero)
        hero.add_to_hand(m)
        return m

    def test_rally_summons_highest_atk_copy_and_keeps_hand_card(self):
        game = make_game(seed=122)
        a, b = game.heroes
        aviator = put(game, "BG34_140", a)
        small = self._hand_minion(game, a, "BG33_323")   # 2 攻
        big = self._hand_minion(game, a, "BG27_017")     # 7 攻
        big_def = get_db().get("BG27_017")
        target = dummy(b)
        game.summon(b, target)
        CombatScheduler(game, a, b)._execute_attack(aviator, target)
        self.assertEqual(len(a.board), 2)
        summoned = a.board[-1]
        self.assertEqual(summoned.card_id, big.card_id)
        self.assertEqual(summoned.atk, big_def.atk)  # 快照复制当前属性
        # 副本模型: 手牌原件不离手（战斗中无手牌交互窗口）
        self.assertIn(big, a.hand)
        self.assertEqual(target.health, 100 - get_db().get("BG34_140").atk)

    def test_rally_no_minions_in_hand_no_effect(self):
        game = make_game(seed=123)
        a, b = game.heroes
        aviator = put(game, "BG34_140", a)
        target = dummy(b)
        game.summon(b, target)
        CombatScheduler(game, a, b)._execute_attack(aviator, target)
        self.assertEqual(len(a.board), 1)

    def test_rally_full_board_does_not_summon(self):
        game = make_game(seed=124)
        a, b = game.heroes
        aviator = put(game, "BG34_140", a, position=0)
        for i in range(BOARD_SIZE - 1):
            game.summon(a, make_minion(f"F{i}", 1, 1))
        self.assertTrue(a.board_full())
        big = self._hand_minion(game, a, "BG27_017")
        game.run_script_hook(aviator, "rally", ctx={"target": dummy(b)})
        self.assertEqual(len(a.board), BOARD_SIZE)   # 满板失败不召唤
        self.assertIn(big, a.hand)                    # 手牌保留

    def test_combat_copy_vanishes_after_combat(self):
        game = make_game(seed=125)
        a, b = game.heroes
        aviator = put(game, "BG34_140", a)
        big = self._hand_minion(game, a, "BG27_017")
        game.summon(b, dummy(b))
        game.run_combat(a, b)
        # "for this combat only": 副本不在战前快照 → 战后随 board 恢复
        # 消失; 手牌原件始终在手
        self.assertEqual([m.card_id for m in a.board],
                         [get_db().get("BG34_140").id])
        self.assertIn(big, a.hand)
        self.assertIn(big.card_id,
                      [m.card_id for m in game.combat_summon_log])

    def test_golden_rally_summons_two_highest(self):
        game = make_game(seed=126)
        a, b = game.heroes
        aviator = put(game, "BG34_140", a, golden=True)
        self.assertEqual(aviator.card_id, "BG34_140_G")
        self.assertEqual(get_db().get("BG34_140_G").num(0), 2)
        m3 = self._hand_minion(game, a, "BG33_886")   # 2 攻
        m5 = self._hand_minion(game, a, "BG34_319")   # 6 攻
        m9 = self._hand_minion(game, a, "BG34_320")   # 15 攻
        target = dummy(b)
        game.summon(b, target)
        CombatScheduler(game, a, b)._execute_attack(aviator, target)
        self.assertEqual(len(a.board), 3)          # aviator + 2 副本
        summoned = {m.card_id for m in a.board} - {aviator.card_id}
        self.assertEqual(summoned, {m5.card_id, m9.card_id})


class TestHighkeeperRa(unittest.TestCase):
    """BG34_319 — Battlecry, Deathrattle, and Rally: Get a random
    Tier 6 minion."""

    def _t6_pool_ids(self) -> set[str]:
        return {d.id for d in get_db().pool_minions()
                if d.tech_level == 6}

    def test_battlecry_gets_random_tier6(self):
        from hsrl2.constants import POOL_COPIES_BY_TIER
        game = make_game(seed=127)
        a = game.heroes[0]
        ra = game.create_minion("BG34_319", controller=a)
        a.add_to_hand(ra)
        self.assertTrue(game.play_minion(a, ra))
        gained = [c for c in a.hand if c is not ra]
        self.assertEqual(len(gained), 1)
        self.assertIn(gained[0].card_id, self._t6_pool_ids())
        self.assertEqual(game.minion_pool.available(gained[0].card_id),
                         POOL_COPIES_BY_TIER[6] - 1)   # acquire 占池

    def test_deathrattle_gets_random_tier6(self):
        game = make_game(seed=128)
        a = game.heroes[0]
        ra = put(game, "BG34_319", a)
        ra.health = 0
        game.check_deaths()
        gained = [c for c in a.hand]
        self.assertEqual(len(gained), 1)
        self.assertIn(gained[0].card_id, self._t6_pool_ids())

    def test_rally_gets_random_tier6(self):
        game = make_game(seed=129)
        a, b = game.heroes
        ra = put(game, "BG34_319", a)
        CombatScheduler(game, a, b)._execute_attack(ra, dummy(b))
        self.assertEqual(len(a.hand), 1)
        self.assertIn(a.hand[0].card_id, self._t6_pool_ids())

    def test_golden_all_three_hooks_get_two(self):
        game = make_game(seed=130)
        a, b = game.heroes
        ra = put(game, "BG34_319", a, golden=True)
        CombatScheduler(game, a, b)._execute_attack(ra, dummy(b))
        self.assertEqual(len(a.hand), 2)            # rally ×2
        a.hand.clear()
        ra.health = 0
        game.check_deaths()
        self.assertEqual(len(a.hand), 2)            # deathrattle ×2
        a.hand.clear()
        # battlecry: 引擎对 GOLDEN 触发 2 次 × 脚本单 Action
        ra2 = game.create_minion("BG34_319", controller=a, golden=True)
        a.add_to_hand(ra2)
        game.play_minion(a, ra2)
        gained = [c for c in a.hand if c is not ra2]
        self.assertEqual(len(gained), 2)


class TestTheLastOneStanding(unittest.TestCase):
    """BG34_320 — Rally: Give a friendly minion of each type
    +{0}/+{1} permanently."""

    def test_rally_buffs_one_minion_per_race_excluding_self(self):
        game = make_game(seed=131)
        a, b = game.heroes
        d = get_db().get("BG34_320")
        tlos = put(game, "BG34_320", a)
        murloc = make_minion("Murloc", 1, 1, race=Race.MURLOC)
        beast = make_minion("Beast", 1, 1, race=Race.BEAST)
        demon = make_minion("Demon", 1, 1, race=Race.DEMON)
        for m in (murloc, beast, demon):
            game.summon(a, m)
        CombatScheduler(game, a, b)._execute_attack(tlos, dummy(b))
        for m in (murloc, beast, demon):
            self.assertEqual(m.atk, 1 + d.num(0))
            self.assertEqual(m.max_health, 1 + d.num(1))
            self.assertEqual(len(m.buffs), 1)
        self.assertEqual(tlos.atk, d.atk)           # 自身排除
        self.assertEqual(tlos.buffs, [])

    def test_rally_alone_no_effect(self):
        game = make_game(seed=132)
        a, b = game.heroes
        tlos = put(game, "BG34_320", a)
        CombatScheduler(game, a, b)._execute_attack(tlos, dummy(b))
        self.assertEqual(tlos.buffs, [])
        self.assertEqual(game.deferred_actions, [])

    def test_amalgam_eligible_for_every_race(self):
        game = make_game(seed=133)
        a, b = game.heroes
        d = get_db().get("BG34_320")
        tlos = put(game, "BG34_320", a)
        amalgam = make_minion("Amal", 1, 1, race=Race.ALL)
        game.summon(a, amalgam)
        CombatScheduler(game, a, b)._execute_attack(tlos, dummy(b))
        self.assertEqual(len(amalgam.buffs), len(ALL_BG_RACES))
        self.assertEqual(amalgam.atk, 1 + d.num(0) * len(ALL_BG_RACES))

    def test_buff_persists_after_combat_via_replay(self):
        game = make_game(seed=134)
        a, b = game.heroes
        d = get_db().get("BG34_320")
        tlos = put(game, "BG34_320", a, position=0)
        murloc = make_minion("Murloc", 1, 1, race=Race.MURLOC)
        game.summon(a, murloc)
        # 低血靶: TLOS 首攻即击杀 → 恰好 1 次 Rally（murloc 未攻击）
        game.summon(b, dummy(b, health=d.atk))
        game.run_combat(a, b)
        # 快照恢复回滚战斗内即时 buff → 下一招募回合开始重放
        game._begin_recruit_for(a)
        self.assertEqual(murloc.atk, 1 + d.num(0))
        self.assertEqual(murloc.max_health, 1 + d.num(1))

    def test_golden_rally_two_passes(self):
        game = make_game(seed=135)
        a, b = game.heroes
        dg = get_db().get("BG34_320_G")
        tlos = put(game, "BG34_320", a, golden=True)
        murloc = make_minion("Murloc", 1, 1, race=Race.MURLOC)
        game.summon(a, murloc)
        CombatScheduler(game, a, b)._execute_attack(tlos, dummy(b))
        self.assertEqual(len(murloc.buffs), 2)
        self.assertEqual(murloc.atk, 1 + dg.num(0) * 2)
        self.assertEqual(murloc.max_health, 1 + dg.num(1) * 2)


class TestRallyBatchRegistry(unittest.TestCase):
    """注册表健康度: 10 卡 + 金色链完整 + bind_all 通过。"""

    IMPLEMENTED = [
        "BG25_016", "BG27_017", "BG33_318", "BG33_323", "BG33_822",
        "BG33_886", "BG33_924", "BG34_140", "BG34_319", "BG34_320",
    ]

    def test_registered_ids_exist_with_golden_chain(self):
        db = get_db()
        for cid in self.IMPLEMENTED:
            d = db.get(cid)
            self.assertIsNotNone(d, f"MISSING_DEF: {cid}")
            self.assertIn(cid, REGISTRY, f"MISSING_SCRIPT: {cid}")
            golden = db.golden_version(d)
            self.assertIsNotNone(golden, f"MISSING_GOLDEN: {cid}")
            self.assertIn(golden.id, REGISTRY,
                          f"MISSING_GOLDEN_SCRIPT: {cid}")
        self.assertGreaterEqual(bind_all(db), 2 * len(self.IMPLEMENTED))


if __name__ == "__main__":
    unittest.main()
