"""清尾批 unfreeze 语义测试（作业单 2026-08-22，15 张解冻卡）。

驱动约定（TEST_SOP / 既有批次同款）:
  - Rally: CombatScheduler(game,a,b)._execute_attack(attacker, defender)
    单次攻击驱动（rally 在伤害前触发）
  - 数值期望一律 CardDef.num() 计算; token/字面量处注明
  - 每卡 ≥1 正例 + 负例
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.combat import CombatScheduler
from hsrl2.constants import BOARD_SIZE
from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY, bind_all
from hsrl2.scripts.batches.batch_unfreeze import (
    CHOOSE_ONE_MINION_IDS,
    CHOOSE_ONE_SPELL_IDS,
)
from hsrl2.tags import GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

GEM_ID = "BG20_GEM"
GOLEM_ID = "BG30_MagicItem_442t"       # Jailbird Golem token（数据核实）

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


def dummy(hero: Hero, atk: int = 0, health: int = 100) -> Minion:
    m = make_minion("Dummy", atk, health)
    game = hero.game
    game.summon(hero, m)
    return m


def gem_values(game: Game, hero: Hero) -> tuple[int, int]:
    d = get_db().get(GEM_ID)
    return (d.num(0) + hero.get(GameTag.BLOOD_GEM_BONUS_ATK, 0),
            d.num(1) + hero.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0))


def attack(game: Game, attacker: Minion, defender: Minion) -> None:
    a, b = game.heroes[0], game.heroes[1]
    CombatScheduler(game, a, b)._execute_attack(attacker, defender)


def hand_spell(game: Game, hero: Hero, card_id: str,
               spellcraft: bool = False):
    s = game.create_spell(card_id, controller=hero)
    if spellcraft:
        s.set(GameTag.SPELLCRAFT, True)
    hero.hand.append(s)
    s.zone = Zone.HAND
    return s


def drain_spell_pool(game: Game, keep: set[str],
                     max_tier: int = 6) -> None:
    """测试收窄: 占用除 keep 外的全部 ≤max_tier 池法术副本。"""
    for sd in get_db().pool_spells():
        if sd.id in keep or sd.tech_level > max_tier:
            continue
        while game.spell_pool.available(sd.id) > 0:
            assert game.spell_pool.acquire(sd.id)


def drain_minion_pool(game: Game, keep: set[str]) -> None:
    for cid in CHOOSE_ONE_MINION_IDS | CHOOSE_ONE_SPELL_IDS:
        if cid in keep:
            continue
        pool = (game.minion_pool if cid in CHOOSE_ONE_MINION_IDS
                else game.spell_pool)
        while pool.available(cid) > 0:
            assert pool.acquire(cid)


class TestRegistryState(unittest.TestCase):
    """批次注册面: 15 卡（28 id 含金色）全部注册。"""

    IDS = (
        "BG36_333", "BG36_333_G",
        "BG23_009", "BG23_009_G",
        "BG26_524", "BG26_524_G",
        "BG36_508", "BG36_508_G",
        "BG31_892", "BG28_698",
        "BG36_344", "BG36_344_G",
        "BG33_825", "BG33_825_G",
        "BG35_883", "BG35_883_G",
        "BG29_813", "BG29_813_G",
        "BG21_015", "BG21_015_G",
        "BG24_018", "BG24_018_G",
        "BG26_137", "BG26_137_G",
        "BG32_236", "BG32_236_G",
        "BG35_814", "BG35_814_G",
    )

    def test_all_registered(self):
        for cid in self.IDS:
            self.assertIn(cid, REGISTRY, f"{cid} should be registered")

    def test_hook_presence_matches_data_keywords(self):
        db = get_db()
        self.assertTrue(hasattr(REGISTRY["BG36_333"], "rally"))
        self.assertEqual(db.get("BG36_333").keywords &
                         {"rally"}, {"rally"})
        for cid in ("BG36_508", "BG36_508_G"):
            self.assertTrue(hasattr(REGISTRY[cid], "activate"))
            self.assertIsNotNone(db.get(cid).activate_cost)

    def test_param_mapping_matches_data(self):
        db = get_db()
        # Cagey: {0}=费用=activate_cost, {1}=施放数
        for cid, cost, casts in (("BG36_508", 1, 2), ("BG36_508_G", 1, 4)):
            self.assertEqual(db.get(cid).num(0), cost)
            self.assertEqual(db.get(cid).num(1), casts)
            self.assertEqual(db.get(cid).num(0),
                             db.get(cid).activate_cost)
        self.assertEqual(db.get("BG23_009").num(0), 1)
        self.assertEqual(db.get("BG23_009_G").num(0), 2)
        self.assertEqual(db.get("BG26_524").num(0), 2)
        self.assertEqual(db.get("BG26_524_G").num(0), 4)
        self.assertEqual((db.get("BG36_344").num(0),
                          db.get("BG36_344").num(1)), (1, 1))
        self.assertEqual((db.get("BG36_344_G").num(0),
                          db.get("BG36_344_G").num(1)), (2, 2))
        self.assertEqual((db.get("BG26_137").num(0),
                          db.get("BG26_137").num(1)), (6, 6))
        self.assertEqual((db.get("BG26_137_G").num(0),
                          db.get("BG26_137_G").num(1)), (12, 12))
        self.assertEqual(db.get("BG35_814").num(0), 6)
        self.assertEqual(db.get("BG35_814_G").num(0), 6)


class TestJailbirdJuggernaut(unittest.TestCase):
    """BG36_333 — Rally: Golem(stats=Blood Gems) 立即先攻目标。"""

    def _attack_with_gems(self, game, gems: int, golden: bool = False):
        a, b = game.heroes
        jb = put(game, "BG36_333", a, golden=golden)
        if gems:
            from hsrl2.actions.bloodgem import PlayBloodGems
            PlayBloodGems(jb, gems).do(game)
        target = dummy(b, atk=0, health=100)
        attack(game, jb, target)
        return a, jb, target

    def test_golem_stats_and_first_attack(self):
        game = make_game(seed=300)
        a, jb, target = self._attack_with_gems(game, gems=3)
        gem_atk, gem_hp = gem_values(game, a)
        golems = [m for m in a.board if m.card_id == GOLEM_ID]
        self.assertEqual(len(golems), 1)
        g = golems[0]
        self.assertEqual((g.atk, g.max_health), (3 * gem_atk, 3 * gem_hp))
        # 先攻（Golem）+ 本体攻击（宝石已 buff 本体攻）
        d = get_db().get("BG36_333")
        self.assertEqual(target.health,
                         100 - 3 * gem_atk - (d.atk + 3 * gem_atk))
        # 反击 0 → Golem 存活
        self.assertFalse(g.dead)

    def test_zero_gems_summons_dead_golem(self):
        game = make_game(seed=301)
        a, jb, target = self._attack_with_gems(game, gems=0)
        living_golems = [m for m in a.board
                         if m.card_id == GOLEM_ID and not m.dead]
        self.assertEqual(living_golems, [])      # 0/0 → 召唤即死
        d = get_db().get("BG36_333")
        self.assertEqual(target.health, 100 - d.atk)  # 仅本体攻击

    def test_golden_doubles_golem_stats(self):
        game = make_game(seed=302)
        a, jb, target = self._attack_with_gems(game, gems=2, golden=True)
        gem_atk, gem_hp = gem_values(game, a)
        golems = [m for m in a.board if m.card_id == GOLEM_ID]
        self.assertEqual(len(golems), 1)         # 单个 Golem（非两个）
        self.assertEqual((golems[0].atk, golems[0].max_health),
                         (2 * gem_atk * 2, 2 * gem_hp * 2))

    def test_full_board_discards_golem(self):
        game = make_game(seed=303)
        a = game.heroes[0]
        jb = put(game, "BG36_333", a)
        while len(a.board) < BOARD_SIZE:
            game.summon(a, make_minion(f"F{len(a.board)}", 1, 1))
        from hsrl2.actions.bloodgem import PlayBloodGems
        PlayBloodGems(jb, 3).do(game)
        target = dummy(game.heroes[1])
        attack(game, jb, target)
        d = get_db().get("BG36_333")
        gem_atk, _ = gem_values(game, a)
        self.assertEqual(                     # 满场 → 无 Golem 无先攻
            target.health, 100 - (d.atk + 3 * gem_atk))


class TestLavaLurker(unittest.TestCase):
    """BG23_009 — 首个 Spellcraft 施放永久化（temporary 翻转）。"""

    def _cast_on(self, game, hero, lurker, spell_id="BG23_007t"):
        s = hand_spell(game, hero, spell_id, spellcraft=True)
        self.assertTrue(game.play_spell(hero, s, target=lurker))
        return [b for b in lurker.buffs
                if b.source_id == spell_id]

    def test_first_spellcraft_permanent(self):
        game = make_game(seed=310)
        a = game.heroes[0]
        lurker = put(game, "BG23_009", a)
        buffs = self._cast_on(game, a, lurker)
        self.assertTrue(buffs)
        self.assertTrue(all(not b.temporary for b in buffs))

    def test_second_same_turn_stays_temporary(self):
        game = make_game(seed=311)
        a = game.heroes[0]
        lurker = put(game, "BG23_009", a)
        self._cast_on(game, a, lurker, "BG23_007t")
        buffs2 = self._cast_on(game, a, lurker, "BG23_000t")
        self.assertTrue(all(b.temporary for b in buffs2))  # 次数耗尽

    def test_spellcraft_on_other_target_not_flipped(self):
        game = make_game(seed=312)
        a = game.heroes[0]
        lurker = put(game, "BG23_009", a)
        other = put(game, "BG21_015", a)          # 无效果随从
        s = hand_spell(game, a, "BG23_007t", spellcraft=True)
        game.play_spell(a, s, target=other)
        self.assertTrue(all(b.temporary
                            for b in other.buffs
                            if b.source_id == "BG23_007t"))
        self.assertEqual(lurker.buffs, [])

    def test_golden_two_per_turn(self):
        game = make_game(seed=313)
        a = game.heroes[0]
        lurker = put(game, "BG23_009", a, golden=True)
        first = self._cast_on(game, a, lurker, "BG23_007t")
        second = self._cast_on(game, a, lurker, "BG23_000t")
        third = self._cast_on(game, a, lurker, "BG23_008t")
        self.assertTrue(all(not b.temporary for b in first + second))
        self.assertTrue(all(b.temporary for b in third))

    def test_uses_reset_next_turn(self):
        game = make_game(seed=314)
        a = game.heroes[0]
        lurker = put(game, "BG23_009", a)
        self._cast_on(game, a, lurker)
        game._begin_recruit_for(a)                 # turn_start → 重置
        buffs = self._cast_on(game, a, lurker)
        self.assertTrue(all(not b.temporary for b in buffs))


class TestMalchezaar(unittest.TestCase):
    """BG26_524 — 每回合 num(0) 次刷新以生命支付。"""

    def test_refreshes_cost_health_then_gold(self):
        game = make_game(seed=320)
        a = game.heroes[0]
        n = get_db().get("BG26_524").num(0)
        put(game, "BG26_524", a)
        self.assertEqual(a.get(GameTag.HEALTH_REFRESHES_LEFT), n)
        a.gold = 10
        hp0 = a.health + a.armor
        for i in range(n):                    # n 次扣血
            game.refresh_tavern(a, auto=False)
            self.assertEqual(a.gold, 10)
            self.assertEqual(a.health + a.armor, hp0 - (i + 1))
        game.refresh_tavern(a, auto=False)    # 用尽 → 金币
        self.assertEqual(a.gold, 9)

    def test_resets_each_turn(self):
        game = make_game(seed=321)
        a = game.heroes[0]
        n = get_db().get("BG26_524").num(0)
        put(game, "BG26_524", a)
        a.set(GameTag.HEALTH_REFRESHES_LEFT, 0)    # 模拟用尽
        game._begin_recruit_for(a)
        self.assertEqual(a.get(GameTag.HEALTH_REFRESHES_LEFT), n)

    def test_sold_clears_tag(self):
        game = make_game(seed=322)
        a = game.heroes[0]
        m = put(game, "BG26_524", a)
        self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(a.get(GameTag.HEALTH_REFRESHES_LEFT), 0)
        a.gold = 10
        game.refresh_tavern(a, auto=False)         # 无光环 → 扣金
        self.assertEqual(a.gold, 9)

    def test_without_malchezaar_costs_gold(self):
        game = make_game(seed=323)
        a = game.heroes[0]
        a.gold = 10
        game.refresh_tavern(a, auto=False)
        self.assertEqual(a.gold, 9)
        self.assertEqual(a.get(GameTag.HEALTH_REFRESHES_LEFT), 0)

    def test_golden_four_refreshes(self):
        game = make_game(seed=324)
        a = game.heroes[0]
        put(game, "BG26_524", a, golden=True)
        self.assertEqual(a.get(GameTag.HEALTH_REFRESHES_LEFT),
                         get_db().get("BG26_524_G").num(0))


class TestCageyConjurer(unittest.TestCase):
    """BG36_508 — Activate: 直施 num(1) 个随机酒馆法术（目标自身）。"""

    def test_casts_count_spells(self):
        game = make_game(seed=330)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 6)
        drain_spell_pool(game, keep={"BG33_815"})   # 仅 Wealthy Bounty
        conjurer = put(game, "BG36_508", a)
        a.gold = 10
        self.assertTrue(game.use_activate(a, conjurer))
        cost = get_db().get("BG36_508").activate_cost
        casts = get_db().get("BG36_508").num(1)
        # 费用 + 每施放 GainGold(amount=2)（Wealthy 文本字面量）
        self.assertEqual(a.gold, 10 - cost + 2 * casts)

    def test_golden_casts_four(self):
        game = make_game(seed=331)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 6)
        drain_spell_pool(game, keep={"BG33_815"})
        conjurer = put(game, "BG36_508", a, golden=True)
        a.gold = 10
        self.assertTrue(game.use_activate(a, conjurer))
        cost = get_db().get("BG36_508_G").activate_cost
        casts = get_db().get("BG36_508_G").num(1)
        self.assertEqual(casts, 4)
        self.assertEqual(a.gold, 10 - cost + 2 * casts)

    def test_targeted_spell_targets_self(self):
        game = make_game(seed=332)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 6)
        drain_spell_pool(game, keep={"BG28_897"})  # 定向 +{0}/+{1}
        conjurer = put(game, "BG36_508", a)
        atk0, hp0 = conjurer.atk, conjurer.max_health
        a.gold = 10
        self.assertTrue(game.use_activate(a, conjurer))
        d = get_db().get("BG28_897")
        casts = get_db().get("BG36_508").num(1)
        self.assertEqual(conjurer.atk, atk0 + d.num(0) * casts)
        self.assertEqual(conjurer.max_health, hp0 + d.num(1) * casts)

    def test_empty_pool_whiffs(self):
        game = make_game(seed=333)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 6)
        drain_spell_pool(game, keep=set())
        conjurer = put(game, "BG36_508", a)
        a.gold = 10
        self.assertTrue(game.use_activate(a, conjurer))   # 消耗照常
        self.assertEqual(a.gold, 10 - get_db().get("BG36_508").activate_cost)


class TestFandralsFortune(unittest.TestCase):
    """BG31_892 — Discover Choose One 卡，恒双效。"""

    def test_discover_marks_minion_combined(self):
        game = make_game(seed=340)
        a = game.heroes[0]
        drain_minion_pool(game, keep={"BG30_123"})  # 仅 Fearless Foodie
        s = hand_spell(game, a, "BG31_892")
        self.assertTrue(game.play_spell(a, s))
        pc = game.pending_choices.pop(0)
        self.assertEqual(pc.kind, "discover_choose_one")
        self.assertEqual(list(pc.options), ["BG30_123"])
        pc.choose(0)
        foodie = [c for c in a.hand if c.card_id == "BG30_123"]
        self.assertEqual(len(foodie), 1)
        self.assertTrue(foodie[0].has(GameTag.CHOOSE_BOTH))
        # 池感知: 副本被占（T4 池 11 份 → 10）
        from hsrl2.constants import POOL_COPIES_BY_TIER
        self.assertEqual(
            game.minion_pool.available("BG30_123"),
            POOL_COPIES_BY_TIER[4] - 1)

    def test_combined_minion_casts_both_branches(self):
        game = make_game(seed=341)
        a = game.heroes[0]
        drain_minion_pool(game, keep={"BG30_123"})
        s = hand_spell(game, a, "BG31_892")
        game.play_spell(a, s)
        game.pending_choices.pop(0).choose(0)
        foodie = [c for c in a.hand if c.card_id == "BG30_123"][0]
        self.assertTrue(game.play_minion(a, foodie))
        # 恒双效: 无 choose_one 选择窗
        self.assertEqual(
            [pc for pc in game.pending_choices
             if pc.kind == "choose_one"], [])
        d = get_db().get("BG30_123")
        # improve 分支: BLOOD_GEM_BONUS 递增 num(0)/num(1)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK), d.num(0))
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH), d.num(1))
        # gems 分支: GetBloodGems(num(2))
        gems = [c for c in a.hand if c.card_id == GEM_ID]
        self.assertEqual(len(gems), d.num(2))

    def test_combined_spell_casts_both_without_prompt(self):
        game = make_game(seed=342)
        a = game.heroes[0]
        drain_minion_pool(game, keep={"BG31_881"})  # 仅 Time Management
        s = hand_spell(game, a, "BG31_892")
        game.play_spell(a, s)
        pc = game.pending_choices.pop(0)
        self.assertEqual(list(pc.options), ["BG31_881"])
        pc.choose(0)
        tm = [c for c in a.hand if c.card_id == "BG31_881"][0]
        self.assertTrue(tm.has(GameTag.CHOOSE_BOTH))
        m = put(game, "BG21_015", a)                # 承接 now 分支 buff
        atk0, hp0 = m.atk, m.max_health
        self.assertTrue(game.play_spell(a, tm))
        # 双效: 无选择窗 + now 分支立即全体 +num(0)/num(1)
        self.assertEqual(
            [pc for pc in game.pending_choices
             if pc.kind == "choose_one"], [])
        d = get_db().get("BG31_881")
        self.assertEqual(m.atk, atk0 + d.num(0))
        self.assertEqual(m.max_health, hp0 + d.num(1))

    def test_normal_choose_one_minion_still_prompts(self):
        game = make_game(seed=343)
        a = game.heroes[0]
        foodie = game.create_minion("BG30_123", controller=a)
        a.add_to_hand(foodie)
        self.assertTrue(game.play_minion(a, foodie))
        self.assertEqual(
            [pc.kind for pc in game.pending_choices
             if pc.kind == "choose_one"], ["choose_one"])


class TestGemConfiscation(unittest.TestCase):
    """BG28_698 — 直施 2 宝石 + 目标窃取相邻随从全部宝石。"""

    def test_plays_gems_and_steals_from_neighbors(self):
        from hsrl2.actions.bloodgem import PlayBloodGems
        game = make_game(seed=350)
        a = game.heroes[0]
        left = put(game, "BG21_015", a)
        target = put(game, "BG21_015", a)
        right = put(game, "BG21_015", a)
        far = put(game, "BG21_015", a)
        PlayBloodGems(left, 3).do(game)
        PlayBloodGems(right, 2).do(game)
        s = hand_spell(game, a, "BG28_698")
        self.assertTrue(game.play_spell(a, s, target=target))
        # 目标: 2 颗新宝石 + 窃取 3 + 2
        self.assertEqual(target.get(GameTag.GEMS_PLAYED_ON), 7)
        self.assertEqual(left.get(GameTag.GEMS_PLAYED_ON), 0)
        self.assertEqual(right.get(GameTag.GEMS_PLAYED_ON), 0)
        self.assertEqual(far.get(GameTag.GEMS_PLAYED_ON), 0)  # 非相邻
        gem_atk, gem_hp = gem_values(game, a)
        self.assertEqual(target.atk,
                         get_db().get("BG21_015").atk
                         + gem_atk * 7)
        self.assertEqual(left.atk, get_db().get("BG21_015").atk)

    def test_edge_target_single_neighbor(self):
        from hsrl2.actions.bloodgem import PlayBloodGems
        game = make_game(seed=351)
        a = game.heroes[0]
        only = put(game, "BG21_015", a)          # 最左
        target = put(game, "BG21_015", a)        # 边缘位: 仅左邻
        PlayBloodGems(only, 4).do(game)
        s = hand_spell(game, a, "BG28_698")
        self.assertTrue(game.play_spell(a, s, target=target))
        self.assertEqual(target.get(GameTag.GEMS_PLAYED_ON), 4 + 2)
        self.assertEqual(only.get(GameTag.GEMS_PLAYED_ON), 0)

    def test_no_target_whiffs(self):
        game = make_game(seed=352)
        a = game.heroes[0]
        s = hand_spell(game, a, "BG28_698")
        # 空棋盘: needs_target 无候选 → 落空但照常消耗
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(a.hand, [])


class TestHooktusk(unittest.TestCase):
    """BG36_344 — After you Discover: 其他 Pirates +num（Improved by 金色）。"""

    def _discover(self, game, hero):
        from hsrl2.actions.discover import Discover
        game.run_actions(Discover(hero, count=3, kind="discover_minion"))
        game.pending_choices.pop(0).choose(0)

    def test_discover_buffs_other_pirates(self):
        game = make_game(seed=360)
        a = game.heroes[0]
        hooktusk = put(game, "BG36_344", a)
        pirate = put(game, "BG33_825", a)        # Proud Privateer=海盗
        beast = make_minion("Z", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        atk0 = pirate.atk
        self._discover(game, a)
        d = get_db().get("BG36_344")
        gmp = a.get(GameTag.GOLDEN_MINIONS_PLAYED, 0)
        self.assertEqual(pirate.atk, atk0 + d.num(0) + gmp)
        self.assertEqual(beast.atk, 2)           # 非 Pirate
        self.assertEqual(hooktusk.atk,
                         get_db().get("BG36_344").atk)  # "other" 排除自身

    def test_improved_by_golden_minions_played(self):
        game = make_game(seed=361)
        a = game.heroes[0]
        put(game, "BG36_344", a)
        pirate = put(game, "BG33_825", a)
        a.set(GameTag.GOLDEN_MINIONS_PLAYED, 3)
        atk0 = pirate.atk
        self._discover(game, a)
        d = get_db().get("BG36_344")
        self.assertEqual(pirate.atk, atk0 + d.num(0) + 3)  # 加法改进

    def test_dark_gift_kind_ignored(self):
        game = make_game(seed=362)
        a = game.heroes[0]
        put(game, "BG36_344", a)
        pirate = put(game, "BG33_825", a)
        atk0 = pirate.atk
        game.events.fire(game, "card_discovered",
                         kind="dark_gift", hero=a, option=None)
        self.assertEqual(pirate.atk, atk0)       # 非 Discover 不触发

    def test_triple_reward_kind_triggers(self):
        game = make_game(seed=363)
        a = game.heroes[0]
        put(game, "BG36_344", a)
        pirate = put(game, "BG33_825", a)
        atk0 = pirate.atk
        game.events.fire(game, "card_discovered",
                         kind="triple_reward", hero=a, option=None)
        d = get_db().get("BG36_344")
        self.assertEqual(pirate.atk,
                         atk0 + d.num(0) + a.get(
                             GameTag.GOLDEN_MINIONS_PLAYED, 0))

    def test_opponent_discover_ignored(self):
        game = make_game(seed=364)
        a, b = game.heroes
        put(game, "BG36_344", a)
        pirate_a = put(game, "BG33_825", a)
        atk0 = pirate_a.atk
        game.events.fire(game, "card_discovered",
                         kind="discover_minion", hero=b, option=None)
        self.assertEqual(pirate_a.atk, atk0)


class TestProudPrivateer(unittest.TestCase):
    """BG33_825 — Bounties cast twice（金色 ×3）。"""

    def test_wealthy_bounty_casts_twice(self):
        game = make_game(seed=370)
        a = game.heroes[0]
        put(game, "BG33_825", a)
        a.gold = 10
        assert game.spell_pool.acquire("BG33_815")
        s = hand_spell(game, a, "BG33_815")
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(a.gold, 10 + 2 * 2)     # GainGold(2) ×2 施

    def test_golden_casts_three_times(self):
        game = make_game(seed=371)
        a = game.heroes[0]
        put(game, "BG33_825", a, golden=True)
        a.gold = 10
        assert game.spell_pool.acquire("BG33_815")
        s = hand_spell(game, a, "BG33_815")
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(a.gold, 10 + 2 * 3)

    def test_non_bounty_single_cast(self):
        game = make_game(seed=372)
        a = game.heroes[0]
        put(game, "BG33_825", a)
        target = put(game, "BG21_015", a)
        atk0, hp0 = target.atk, target.max_health
        assert game.spell_pool.acquire("BG28_897")
        s = hand_spell(game, a, "BG28_897")
        self.assertTrue(game.play_spell(a, s, target=target))
        d = get_db().get("BG28_897")
        self.assertEqual(target.atk, atk0 + d.num(0))       # 单施
        self.assertEqual(target.max_health, hp0 + d.num(1))

    def test_per_cast_counting_and_events(self):
        """Evidence: 逐施计数/广播（Balinda 引擎双施同构 + S13 指南
        "every cast scaled"）——追加施放各计 1 次 TAVERN_SPELLS_CAST
        并逐次广播 tavern_spell_cast。"""
        game = make_game(seed=373)
        a = game.heroes[0]
        put(game, "BG33_825", a)
        casts_seen = []
        game.events.register(Listener(
            event="tavern_spell_cast", owner=a,
            callback=lambda g, spell=None, **kw:
                casts_seen.append(spell.card_id)))
        assert game.spell_pool.acquire("BG33_815")
        s = hand_spell(game, a, "BG33_815")
        before = a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0)
        self.assertTrue(game.play_spell(a, s))
        # 主施 1 + 追加 1 = 2 施 → 计数 +2、广播 2 次
        self.assertEqual(
            a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0), before + 2)
        self.assertEqual(casts_seen.count("BG33_815"), 2)


class TestBalinda(unittest.TestCase):
    """BG35_883 — 定向友方法术双施（引擎 SPELL_DOUBLER 消费）。"""

    def test_tag_declared_and_double_cast(self):
        game = make_game(seed=380)
        a = game.heroes[0]
        balinda = put(game, "BG35_883", a)
        self.assertTrue(balinda.has(GameTag.SPELL_DOUBLER))
        target = put(game, "BG21_015", a)
        atk0 = target.atk
        assert game.spell_pool.acquire("BG28_897")
        s = hand_spell(game, a, "BG28_897")
        game.play_spell(a, s, target=target)
        d = get_db().get("BG28_897")
        self.assertEqual(target.atk, atk0 + d.num(0) * 2)
        self.assertEqual(a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME), 2)

    def test_without_balinda_single_cast(self):
        game = make_game(seed=381)
        a = game.heroes[0]
        target = put(game, "BG21_015", a)
        atk0 = target.atk
        assert game.spell_pool.acquire("BG28_897")
        s = hand_spell(game, a, "BG28_897")
        game.play_spell(a, s, target=target)
        self.assertEqual(target.atk, atk0 + get_db().get("BG28_897").num(0))

    def test_golden_triple_cast(self):
        game = make_game(seed=382)
        a = game.heroes[0]
        put(game, "BG35_883", a, golden=True)
        target = put(game, "BG21_015", a)
        atk0 = target.atk
        assert game.spell_pool.acquire("BG28_897")
        s = hand_spell(game, a, "BG28_897")
        game.play_spell(a, s, target=target)
        d = get_db().get("BG28_897")
        self.assertEqual(target.atk, atk0 + d.num(0) * 3)


class TestPersistentPoet(unittest.TestCase):
    """BG29_813 — 相邻龙保留战斗增益（金色 double）。"""

    @staticmethod
    def _combat_buff(m, atk, hp):
        """战斗内增益（SoC 时点 temporary buff——战后默认回退）。"""
        def soc(src, game, ctx):
            from hsrl2 import entity
            src.add_buff(entity.Buff(atk=atk, health=hp, temporary=True))
        m.set_script_override("start_of_combat", soc)

    def test_adjacent_dragon_keeps_combat_buff(self):
        game = make_game(seed=390)
        a, b = game.heroes
        poet = put(game, "BG29_813", a)
        dragon = make_minion("D", 4, 4, race=Race.DRAGON)
        game.summon(a, dragon)                 # 相邻龙（合成随从无脚本）
        plain = make_minion("P2", 5, 5, race=Race.DRAGON)
        game.summon(a, plain)                  # 非相邻龙
        self._combat_buff(dragon, 2, 3)
        self._combat_buff(plain, 5, 5)
        game.run_combat(a, b)
        self.assertEqual(dragon.atk, 4 + 2)         # Poet 相邻保留
        self.assertEqual(dragon.max_health, 4 + 3)
        self.assertEqual(plain.atk, 5)              # 非相邻回退
        self.assertTrue(poet.has(GameTag.ADJACENT_PERSIST_SOURCE))

    def test_non_dragon_adjacent_not_kept(self):
        game = make_game(seed=391)
        a, b = game.heroes
        put(game, "BG29_813", a)
        beast = make_minion("B", 2, 2, race=Race.BEAST)
        game.summon(a, beast)
        self._combat_buff(beast, 3, 3)
        game.run_combat(a, b)
        self.assertEqual(beast.atk, 2)           # 非 Dragon 回退

    def test_golden_poet_doubles(self):
        game = make_game(seed=392)
        a, b = game.heroes
        put(game, "BG29_813", a, golden=True)
        dragon = make_minion("D2", 4, 4, race=Race.DRAGON)
        game.summon(a, dragon)
        self._combat_buff(dragon, 2, 2)
        game.run_combat(a, b)
        self.assertEqual(dragon.atk, 4 + 4)      # double stats


class TestTarecgosa(unittest.TestCase):
    """BG21_015 — 永久保留战斗增益（金色 double）。"""

    def test_keeps_combat_buff(self):
        game = make_game(seed=400)
        a, b = game.heroes
        tare = put(game, "BG21_015", a)
        self.assertTrue(tare.has(GameTag.PERSIST_COMBAT_CHANGES))
        self.assertFalse(tare.has(GameTag.PERSIST_DOUBLE))
        TestPersistentPoet._combat_buff(tare, 3, 4)
        atk0, hp0 = tare.atk, tare.max_health
        game.run_combat(a, b)
        self.assertEqual((tare.atk, tare.max_health),
                         (atk0 + 3, hp0 + 4))

    def test_plain_minion_reverts(self):
        game = make_game(seed=401)
        a, b = game.heroes
        plain = make_minion("P", 5, 5)
        game.summon(a, plain)
        TestPersistentPoet._combat_buff(plain, 3, 3)
        game.run_combat(a, b)
        self.assertEqual((plain.atk, plain.max_health), (5, 5))

    def test_golden_doubles_kept_buff(self):
        game = make_game(seed=402)
        a, b = game.heroes
        tare = put(game, "BG21_015", a, golden=True)
        self.assertTrue(tare.has(GameTag.PERSIST_DOUBLE))
        TestPersistentPoet._combat_buff(tare, 3, 0)
        atk0 = tare.atk
        game.run_combat(a, b)
        self.assertEqual(tare.atk, atk0 + 6)     # double


class TestTortollanBlueShell(unittest.TestCase):
    """BG24_018 — 上局战败则卖 5（金色 10）。"""

    def test_loss_sells_for_five(self):
        game = make_game(seed=410)
        a = game.heroes[0]
        m = put(game, "BG24_018", a)
        a._last_combat_result = "loss"
        a.gold = 0
        self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(a.gold, 5)

    def test_golden_loss_sells_for_ten(self):
        game = make_game(seed=411)
        a = game.heroes[0]
        m = put(game, "BG24_018", a, golden=True)
        a._last_combat_result = "loss"
        a.gold = 0
        self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(a.gold, 10)

    def test_win_sells_for_one(self):
        game = make_game(seed=412)
        a = game.heroes[0]
        m = put(game, "BG24_018", a)
        a._last_combat_result = "win"
        a.gold = 0
        self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(a.gold, 1)

    def test_no_combat_record_sells_for_one(self):
        game = make_game(seed=413)
        a = game.heroes[0]
        m = put(game, "BG24_018", a)
        a.gold = 0
        self.assertFalse(hasattr(a, "_last_combat_result"))
        self.assertTrue(game.sell_minion(a, m))
        self.assertEqual(a.gold, 1)


class TestBreamCounter(unittest.TestCase):
    """BG26_137 — 手牌中打出 Murloc 后成长。"""

    def test_grows_on_murloc_played(self):
        game = make_game(seed=420)
        a = game.heroes[0]
        bream = game.create_minion("BG26_137", controller=a)
        a.add_to_hand(bream)
        murloc = make_minion("M", 1, 1, race=Race.MURLOC)
        a.add_to_hand(murloc)
        self.assertTrue(game.play_minion(a, murloc))
        d = get_db().get("BG26_137")
        self.assertEqual(bream.atk, d.atk + d.num(0))
        self.assertEqual(bream.max_health, d.health + d.num(1))

    def test_all_race_counts(self):
        game = make_game(seed=421)
        a = game.heroes[0]
        bream = game.create_minion("BG26_137", controller=a)
        a.add_to_hand(bream)
        amalgam = make_minion("AM", 1, 1, race=Race.ALL)
        a.add_to_hand(amalgam)
        game.play_minion(a, amalgam)
        d = get_db().get("BG26_137")
        self.assertEqual(bream.atk, d.atk + d.num(0))

    def test_non_murloc_no_growth(self):
        game = make_game(seed=422)
        a = game.heroes[0]
        bream = game.create_minion("BG26_137", controller=a)
        a.add_to_hand(bream)
        beast = make_minion("Z", 1, 1, race=Race.BEAST)
        a.add_to_hand(beast)
        game.play_minion(a, beast)
        d = get_db().get("BG26_137")
        self.assertEqual(bream.atk, d.atk)

    def test_after_played_no_longer_grows(self):
        game = make_game(seed=423)
        a = game.heroes[0]
        bream1 = game.create_minion("BG26_137", controller=a)
        a.add_to_hand(bream1)
        bream2 = game.create_minion("BG26_137", controller=a)
        a.add_to_hand(bream2)
        game.play_minion(a, bream1)               # 打出手牌中的 Bream
        atk_after_play = bream1.atk
        murloc = make_minion("M2", 1, 1, race=Race.MURLOC)
        a.add_to_hand(murloc)
        game.play_minion(a, murloc)
        self.assertEqual(bream1.atk, atk_after_play)   # 离手不触发
        d = get_db().get("BG26_137")
        # 仍在手的成长两次: 打出 bream1（自身是 Murloc）+ 打出 M2
        self.assertEqual(bream2.atk, d.atk + 2 * d.num(0))

    def test_golden_values(self):
        game = make_game(seed=424)
        a = game.heroes[0]
        bream = game.create_minion("BG26_137", controller=a,
                                   golden=True)
        a.add_to_hand(bream)
        murloc = make_minion("M3", 1, 1, race=Race.MURLOC)
        a.add_to_hand(murloc)
        game.play_minion(a, murloc)
        d = get_db().get("BG26_137_G")
        self.assertEqual(bream.atk, d.atk + d.num(0))
        self.assertEqual(bream.max_health, d.health + d.num(1))


class TestAureateLaureate(unittest.TestCase):
    """BG32_236 — 恒金 + 无三连奖励。"""

    def test_always_golden_no_reward(self):
        game = make_game(seed=430)
        a = game.heroes[0]
        m = game.create_minion("BG32_236", controller=a)
        self.assertFalse(m.is_golden)
        a.add_to_hand(m)
        self.assertTrue(m.is_golden)
        self.assertIn(m.uuid, game._gilded_no_reward_uuids)
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))  # 卡面 DS

    def test_immune_to_triple(self):
        game = make_game(seed=431)
        a = game.heroes[0]
        for _ in range(3):
            base = game.create_minion("BG32_236", controller=a)
            a.add_to_hand(base)                   # 每份入手即恒金
        # 恒金不入三连: 三张原样在手、全部恒金
        self.assertEqual([c.card_id for c in a.hand], ["BG32_236"] * 3)
        self.assertTrue(all(c.is_golden for c in a.hand))
        self.assertEqual(a.hand, [c for c in a.hand
                                  if not c.has(GameTag.TRIPLE_REWARD_PENDING)])

    def test_golden_version_same_behavior(self):
        game = make_game(seed=432)
        a = game.heroes[0]
        m = game.create_minion("BG32_236", controller=a, golden=True)
        a.add_to_hand(m)
        self.assertTrue(m.is_golden)
        self.assertIn(m.uuid, game._gilded_no_reward_uuids)


class TestScarletSurvivor(unittest.TestCase):
    """BG35_814 — 达到 num(0) 攻击获得 DS（一次性）。"""

    def test_initial_below_threshold_no_ds(self):
        game = make_game(seed=440)
        a = game.heroes[0]
        m = put(game, "BG35_814", a)
        d = get_db().get("BG35_814")
        self.assertLess(d.atk, d.num(0))           # 3 < 6
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))

    def test_reaching_threshold_grants_ds(self):
        game = make_game(seed=441)
        a = game.heroes[0]
        m = put(game, "BG35_814", a)
        d = get_db().get("BG35_814")
        game.run_actions(BuffAtk(m, d.num(0) - d.atk))
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))

    def test_below_threshold_no_ds(self):
        game = make_game(seed=442)
        a = game.heroes[0]
        m = put(game, "BG35_814", a)
        d = get_db().get("BG35_814")
        game.run_actions(BuffAtk(m, d.num(0) - d.atk - 1))
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))

    def test_once_only_no_retrigger(self):
        game = make_game(seed=443)
        a = game.heroes[0]
        m = put(game, "BG35_814", a)
        d = get_db().get("BG35_814")
        game.run_actions(BuffAtk(m, d.num(0) - d.atk))
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))
        m.clear(GameTag.DIVINE_SHIELD)             # 模拟盾破
        game.run_actions(BuffAtk(m, 1))            # 再次越过阈值
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))  # "Once" 已消耗

    def test_golden_immediate_ds(self):
        game = make_game(seed=444)
        a = game.heroes[0]
        gd = get_db().get("BG35_814_G")
        self.assertGreaterEqual(gd.atk, gd.num(0))
        m = put(game, "BG35_814", a, golden=True)
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))


def BuffAtk(target, amount):
    from hsrl2.actions import Buff as _B
    return _B(target, atk=amount)


if __name__ == "__main__":
    bind_all(get_db())
    unittest.main()
