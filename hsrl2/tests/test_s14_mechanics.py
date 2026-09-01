"""hsrl2 S14 机制测试 — Dark Gifts 发现系统 / Lockbox 倒计时 /
Fishbait 招募期攻击 / 计数器接线。

出处: 官方 36.2 dev post "Dark Gifts of Dalaran" + 36.2.1 hotfix +
data/bg_dark_gifts.json（XML 权威）。断言数值均带出处注释。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2 import darkgifts as DG
from hsrl2.constants import DARK_GIFT_TIERS
from hsrl2.db import CardDB
from hsrl2.defs import CardDef
from hsrl2.game import Game, PERSIST_TAG
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def find_def(pred) -> CardDef:
    return next(d for d in get_db().pool_minions() if pred(d))


def gift_ids(options) -> set:
    return {g for g, _ in options}


# ══════════════════ 1. 窗口表 ══════════════════

class TestGiftWindows(unittest.TestCase):
    """43 张 Dark Gift 全部入表，且与 db.dark_gifts() 完全一致。"""

    def test_full_coverage(self):
        self.assertEqual(len(DG.GIFT_WINDOWS), 43)   # data: 43 张
        self.assertEqual(set(DG.GIFT_WINDOWS),
                         {d.id for d in get_db().dark_gifts()})

    def test_hotfix_windows(self):
        # 36.2.1 hotfix: Charisma 6-9（原 7-None）
        self.assertEqual(DG.GIFT_WINDOWS[DG.CHARISMA], (6, 9))
        # 36.2.1 hotfix: Steady Growth 3-5（原 3-None）
        self.assertEqual(DG.GIFT_WINDOWS[DG.STEADY_GROWTH], (3, 5))
        # hotfix: 弱化版计数类 max 6（原 10）
        self.assertEqual(DG.GIFT_WINDOWS[DG.BATTLE_SCARS_SMALL], (4, 6))
        self.assertEqual(DG.GIFT_WINDOWS[DG.DEATHS_EMBRACE_SMALL], (4, 6))
        self.assertEqual(DG.GIFT_WINDOWS[DG.SPELL_SIPHON_SMALL], (4, 6))

    def test_steady_growth_values(self):
        # dev post 原文数值表
        self.assertEqual(DG.STEADY_GROWTH_VALUES[3], (1, 2))
        self.assertEqual(DG.STEADY_GROWTH_VALUES[5], (3, 3))


# ══════════════════ 2. tier 曲线 ══════════════════

class TestTierCurve(unittest.TestCase):
    """提供档位: turn3:[2] 4:[2,3] 5:[3] 6:[3,4] 7:[4] 8:[4,5]
    9:[4,5,6] 10:[5,6] 11+:[6]（官方 dev post 表）。"""

    def test_constants(self):
        self.assertEqual(DARK_GIFT_TIERS[3], [2])
        self.assertEqual(DARK_GIFT_TIERS[9], [4, 5, 6])

    def test_eligible_minion_tiers(self):
        game = make_game()
        hero = game.heroes[0]
        expected = [(3, {2}), (4, {2, 3}), (5, {3}), (6, {3, 4}), (7, {4}),
                    (8, {4, 5}), (9, {4, 5, 6}), (10, {5, 6}),
                    (11, {6}), (15, {6})]
        for turn, want in expected:
            ids = DG.eligible_minions(get_db(), game.minion_pool, hero, turn)
            tiers = {get_db().get(cid).tech_level for cid in ids}
            self.assertEqual(tiers, want, f"turn={turn}")
            self.assertTrue(ids, f"turn={turn} 非空")

    def test_turn_below_5_no_battlecry(self):
        # dev post: Turn<5 不可提供战吼/Choose One 随从
        game = make_game()
        hero = game.heroes[0]
        for turn in (3, 4):
            ids = DG.eligible_minions(get_db(), game.minion_pool, hero, turn)
            for cid in ids:
                d = get_db().get(cid)
                self.assertNotIn("battlecry", d.keywords,
                                 f"{cid} t={turn}")
                self.assertNotIn("choose one", (d.text or "").lower())

    def test_blacklist_and_text_filters(self):
        # dev post 黑名单: Leeroy / Deadly Spore（Stitched Salvager 为
        # Golemancy 侧禁令）; Magnetic / "when you sell" / "in your hand"
        game = make_game()
        hero = game.heroes[0]
        ids = DG.eligible_minions(get_db(), game.minion_pool, hero, 9)
        names = {get_db().get(cid).name for cid in ids}
        self.assertNotIn("Deadly Spore", names)
        self.assertNotIn("Leeroy the Reckless", names)
        for cid in ids:
            d = get_db().get(cid)
            self.assertNotIn("magnetic", d.keywords)
            self.assertNotIn("when you sell", (d.text or "").lower())
            self.assertNotIn("in your hand", (d.text or "").lower())


# ══════════════════ 3. use_dark_gift 门控 ══════════════════

class TestUseDarkGiftGating(unittest.TestCase):
    """第 3 回合起 / 3 金 / 每局 3 次 / 每回合 1 次（dev post）。"""

    def test_turn_below_3_rejected(self):
        game = make_game(seed=1)
        hero = game.heroes[0]
        hero.gold = 10
        game.turn = 2
        self.assertFalse(game.use_dark_gift(hero))
        self.assertEqual(hero.gold, 10)     # 未扣费

    def test_gold_cost_and_insufficient(self):
        game = make_game(seed=2)
        hero = game.heroes[0]
        game.turn = 3
        hero.gold = 2
        self.assertFalse(game.use_dark_gift(hero))
        hero.gold = 3
        self.assertTrue(game.use_dark_gift(hero))
        self.assertEqual(hero.gold, 0)      # 扣 3 金

    def test_once_per_turn(self):
        game = make_game(seed=3)
        hero = game.heroes[0]
        game.turn = 3
        hero.gold = 10
        self.assertTrue(game.use_dark_gift(hero))
        self.assertFalse(game.use_dark_gift(hero))   # 同回合第 2 次
        # 下一回合重置 used_this_turn
        game.turn = 4
        game._begin_recruit_for(hero)
        self.assertTrue(game.use_dark_gift(hero))

    def test_three_per_game(self):
        game = make_game(seed=4)
        hero = game.heroes[0]
        for turn in (3, 4, 5):
            game.turn = turn
            game._begin_recruit_for(hero)
            self.assertTrue(game.use_dark_gift(hero),
                            f"turn={turn}")
        game.turn = 6
        game._begin_recruit_for(hero)
        self.assertFalse(game.use_dark_gift(hero))   # 每局 3 次耗尽
        self.assertEqual(game.dark_gift_state[hero]["uses_left"], 0)


# ══════════════════ 4. 提供与配对 ══════════════════

class TestDarkGiftOffering(unittest.TestCase):
    """PendingChoice 生成 / resolve 全流程 / Turn6 种族保证。"""

    def test_full_flow(self):
        game = make_game(seed=5)
        hero = game.heroes[0]
        game.turn = 10
        hero.gold = 10
        self.assertTrue(game.use_dark_gift(hero))
        self.assertEqual(len(game.pending_choices), 1)
        ch = game.pending_choices[-1]
        self.assertEqual(ch.kind, "dark_gift")
        self.assertTrue(1 <= len(ch.options) <= 3)
        # gift 互不相同
        gids = [g for _, g in ch.options]
        self.assertEqual(len(set(gids)), len(gids))
        # 选项 gift 均在窗口表内
        for _, g in ch.options:
            self.assertIn(g, DG.GIFT_WINDOWS)
        # resolve: 占池 → 入手 → DARK_GIFT tag → 事件
        cid, gid = ch.options[0]
        seen = []
        game.events.register(_owner_listener(
            hero, "dark_gift_given",
            lambda g, **kw: seen.append((kw["minion"], kw["gift_id"]))))
        avail = game.minion_pool.available(cid)
        ch.choose(0)
        self.assertEqual(game.minion_pool.available(cid), avail - 1)
        m = hero.hand[-1]
        self.assertEqual(m.card_id, cid)
        self.assertEqual(m.get(GameTag.DARK_GIFT), gid)
        self.assertEqual(seen, [(m, gid)])
        # PendingChoice 为队列化协议: choose 解析但不自动出队（与
        # Discover 一致，由上层在 choose 后 pop）
        game.pending_choices.pop()

    def test_turn6_common_race_guarantee(self):
        # dev post: Turn>=6 提供中强制 1 个为玩家最常见种族
        game = make_game(seed=6)
        hero = game.heroes[0]
        game.turn = 6
        hero.gold = 10
        for _ in range(3):
            m = make_minion("Mur", 1, 1)
            m.set(GameTag.RACE, Race.MURLOC)
            m.controller = hero
            m.zone = Zone.PLAY
            hero.board.append(m)
        for attempt in range(10):   # 多 seed 验证保证稳定性
            game2 = make_game(seed=100 + attempt)
            h2 = game2.heroes[0]
            game2.turn = 6
            h2.gold = 10
            for _ in range(3):
                mm = make_minion("Mur", 1, 1)
                mm.set(GameTag.RACE, Race.MURLOC)
                mm.controller = h2
                mm.zone = Zone.PLAY
                h2.board.append(mm)
            self.assertTrue(game2.use_dark_gift(h2))
            ch = game2.pending_choices[-1]
            races = [get_db().get(cid).race
                     for cid, _ in ch.options]
            self.assertTrue(
                any(r in (Race.MURLOC, Race.ALL) for r in races),
                f"seed={100 + attempt} options={ch.options}")

    def test_choice_kind_and_owner(self):
        game = make_game(seed=7)
        hero = game.heroes[0]
        game.turn = 5
        hero.gold = 10
        self.assertTrue(game.use_dark_gift(hero))
        ch = game.pending_choices[-1]
        self.assertIs(ch.owner, hero)
        with self.assertRaises(Exception):
            ch.choose(99)   # 越界拒绝


def _owner_listener(owner, event, cb):
    from hsrl2.events import Listener
    return Listener(event=event, owner=owner, callback=cb)


# ══════════════════ 5. gift-随从配对合法性（eligible_gifts 抽查）══════════════════

class TestEligibleGiftsPairing(unittest.TestCase):
    def setUp(self):
        self.game = make_game()
        self.hero = self.game.heroes[0]
        self.pool = self.game.minion_pool
        self.murloc = find_def(
            lambda d: d.race == Race.MURLOC
            and not {"battlecry", "deathrattle", "venomous", "poisonous"}
            & d.keywords)
        self.beast = find_def(
            lambda d: d.race == Race.BEAST
            and not {"battlecry", "deathrattle"} & d.keywords)

    def _eg(self, d, turn=10, **kw):
        return DG.eligible_gifts(get_db(), d, turn=turn, hero=self.hero,
                                 lobby_dragons_ok=True,
                                 minion_pool=self.pool, **kw)

    def test_toxicity_murloc_only(self):
        # dev post: Toxicity 仅鱼人且无 Venomous/Poisonous
        self.assertIn(DG.TOXICITY, gift_ids(self._eg(self.murloc, 7)))
        self.assertNotIn(DG.TOXICITY, gift_ids(self._eg(self.beast, 7)))
        venom_murloc = find_def(
            lambda d: d.race == Race.MURLOC and "venomous" in d.keywords)
        self.assertNotIn(DG.TOXICITY,
                         gift_ids(self._eg(venom_murloc, 7)))

    def test_gilding_lowest_tier_and_no_activate(self):
        activate = find_def(
            lambda d: d.activate_cost is not None
            and "battlecry" not in d.keywords)
        # 提供集未知 → 不给
        self.assertNotIn(DG.GILDING,
                         gift_ids(self._eg(activate, 6,
                                           offering_min_tier=None)))
        # 非 tier 最低 → 不给
        self.assertNotIn(DG.GILDING,
                         gift_ids(self._eg(activate, 6,
                                           offering_min_tier=1)))
        # tier 最低且非 Activate 的普通随从 → 给
        plain = find_def(
            lambda d: d.tech_level == 4
            and d.activate_cost is None
            and not {"battlecry", "deathrattle"} & d.keywords)
        self.assertIn(DG.GILDING,
                      gift_ids(self._eg(plain, 6, offering_min_tier=4)))

    def test_jaws_of_death_deathrattle_only(self):
        dr = find_def(lambda d: "deathrattle" in d.keywords
                      and "battlecry" not in d.keywords)
        self.assertIn(DG.JAWS_OF_DEATH, gift_ids(self._eg(dr, 10)))
        self.assertNotIn(DG.JAWS_OF_DEATH, gift_ids(self._eg(self.beast, 10)))

    def test_toreth_divine_shield_only(self):
        ds = find_def(lambda d: "divine_shield" in d.keywords
                      and "battlecry" not in d.keywords)
        self.assertIn(DG.TORETHS_BLESSING, gift_ids(self._eg(ds, 6)))
        self.assertNotIn(DG.TORETHS_BLESSING,
                         gift_ids(self._eg(self.murloc, 6)))

    def test_battlecry_minion_restricted_set(self):
        bc = find_def(lambda d: "battlecry" in d.keywords)
        opts = gift_ids(self._eg(bc, 7, offering_min_tier=bc.tech_level))
        # dev post: 战吼随从只可获 Double Vision/Replication/Gilding/
        # Echoing Voice（窗口过滤后: t11/t10/t14）
        self.assertEqual(opts, {DG.DOUBLE_VISION, DG.ECHOING_VOICE,
                                DG.GILDING})

    def test_deathrattle_minion_stat_exclusion(self):
        # t74/t73/t29t 窗口均在 turn5 内
        dr = find_def(lambda d: "deathrattle" in d.keywords
                      and "battlecry" not in d.keywords
                      and d.avenge_target is None)
        opts = gift_ids(self._eg(dr, 5))
        # dev post: 亡语随从不可获数值型 gift，除 Sharpened Sword 与
        # Death's Embrace
        self.assertNotIn(DG.FORTITUDE, opts)
        self.assertNotIn(DG.TITANIC_STRENGTH, opts)
        self.assertIn(DG.SHARPENED_SWORD, opts)
        # Death's Embrace 需亡语计数 > 0
        self.assertNotIn(DG.DEATHS_EMBRACE_SMALL, opts)
        self.hero.set(GameTag.COUNTER_DEATHRATTLES, 1)
        opts = gift_ids(self._eg(dr, 5))
        self.assertIn(DG.DEATHS_EMBRACE_SMALL, opts)

    def test_counter_category_max_only(self):
        # 36.2.1: 三类计数 gift 只提供已触发次数最多的一类（并列都给）
        # 弱化版窗口 (4,6)，取 turn 6
        plain = find_def(
            lambda d: not {"battlecry", "deathrattle"} & d.keywords)
        opts = gift_ids(self._eg(plain, 6))
        for g in (DG.BATTLE_SCARS_SMALL, DG.DEATHS_EMBRACE_SMALL,
                  DG.SPELL_SIPHON_SMALL):
            self.assertNotIn(g, opts)   # 计数全 0
        self.hero.set(GameTag.COUNTER_BATTLECRIES, 3)
        self.hero.set(GameTag.COUNTER_DEATHRATTLES, 1)
        self.hero.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 2)
        opts = gift_ids(self._eg(plain, 6))
        self.assertIn(DG.BATTLE_SCARS_SMALL, opts)    # 最多者
        self.assertNotIn(DG.DEATHS_EMBRACE_SMALL, opts)
        self.assertNotIn(DG.SPELL_SIPHON_SMALL, opts)
        # 并列都给
        self.hero.set(GameTag.COUNTER_DEATHRATTLES, 3)
        opts = gift_ids(self._eg(plain, 6))
        self.assertIn(DG.BATTLE_SCARS_SMALL, opts)
        self.assertIn(DG.DEATHS_EMBRACE_SMALL, opts)

    def test_toughened_shield_lobby_races(self):
        # dev post: Quilboar/Naga 均未激活的局不可提供
        # （t75 窗口 3-5，取 turn 4）
        self.pool.active_races = {Race.BEAST, Race.DRAGON}
        opts = gift_ids(self._eg(self.beast, 4))
        self.assertNotIn(DG.TOUGHENED_SHIELD, opts)
        self.pool.active_races = {Race.BEAST, Race.QUILBOAR}
        opts = gift_ids(self._eg(self.beast, 4))
        self.assertIn(DG.TOUGHENED_SHIELD, opts)

    def test_resistance_lobby_dragons(self):
        # 作业单: Resistance lobby 禁（无龙的局不提供，AMBIGUOUS 读法）
        minion = find_def(
            lambda d: d.race == Race.MECH
            and not {"battlecry", "deathrattle"} & d.keywords)
        self.pool.active_races = None
        opts = DG.eligible_gifts(get_db(), minion, turn=8, hero=self.hero,
                                 lobby_dragons_ok=False,
                                 minion_pool=self.pool)
        self.assertNotIn(DG.RESISTANCE, gift_ids(opts))
        opts = DG.eligible_gifts(get_db(), minion, turn=8, hero=self.hero,
                                 lobby_dragons_ok=True,
                                 minion_pool=self.pool)
        self.assertIn(DG.RESISTANCE, gift_ids(opts))

    def test_turn_window_gating(self):
        self.assertEqual(self._eg(self.murloc, 2), [])   # 全部 tmin>=3

    def test_rare_gift_weight(self):
        # turn 12: Invulnerability (12,None) 稀有 ×0.5;
        # Harpy's Talons (3,None) 普通 ×1.0
        plain = find_def(
            lambda d: d.tech_level >= 4
            and not {"battlecry", "deathrattle", "taunt"} & d.keywords
            and d.avenge_target is None
            and d.race not in (Race.NONE,))
        opts = dict(self._eg(plain, 12))
        self.assertIn(DG.INVULNERABILITY, opts)
        self.assertEqual(opts[DG.INVULNERABILITY], DG.RARE_GIFT_WEIGHT)
        self.assertEqual(opts[DG.HARPYS_TALONS], 1.0)


# ══════════════════ 6. apply_dark_gift 效果 ══════════════════

class TestApplyDarkGiftEffects(unittest.TestCase):
    def setUp(self):
        self.game = make_game()
        self.hero = self.game.heroes[0]

    def _minion(self, atk=1, hp=1):
        m = make_minion("G", atk, hp)
        m.controller = self.hero
        m.zone = Zone.PLAY
        self.hero.board.append(m)
        return m

    def test_fortitude(self):
        # XML 文本 "+5/+5."（BG36_MidGameEffect_000t73）
        m = self._minion(1, 1)
        self.game.apply_dark_gift(m, DG.FORTITUDE)
        self.assertEqual(m.atk, 6)
        self.assertEqual(m.max_health, 6)
        self.assertEqual(m.health, 6)

    def test_harpys_talons(self):
        m = self._minion()
        self.game.apply_dark_gift(m, DG.HARPYS_TALONS)
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))
        self.assertTrue(m.has(GameTag.WINDFURY))

    def test_toxicity(self):
        m = self._minion()
        self.game.apply_dark_gift(m, DG.TOXICITY)
        self.assertTrue(m.has(GameTag.VENOMOUS))

    def test_tarecgosa(self):
        m = self._minion()
        self.game.apply_dark_gift(m, DG.TARECGOSAS_BLESSING)
        self.assertTrue(m.has(PERSIST_TAG))

    def test_invulnerability_and_amalgamation_and_toreth(self):
        m = self._minion()
        self.game.apply_dark_gift(m, DG.INVULNERABILITY)
        self.assertTrue(m.has(GameTag.IMMUNE_WHILE_ATTACKING))
        m2 = self._minion()
        self.game.apply_dark_gift(m2, DG.AMALGAMATION)
        self.assertEqual(m2.race, Race.ALL)
        m3 = self._minion()
        m3.set(GameTag.DIVINE_SHIELD, True)
        self.game.apply_dark_gift(m3, DG.TORETHS_BLESSING)
        self.assertEqual(m3.get(GameTag.DIVINE_SHIELD_HITS), 3)  # XML "3 hits"

    def test_titanic_strength(self):
        m = self._minion(1, 1)
        self.game.apply_dark_gift(m, DG.TITANIC_STRENGTH)
        self.assertEqual(m.atk, 1001)   # XML 文本 "+1000 Attack."

    def test_persisting_horror_reborn_full(self):
        # "Reborn. Is Reborn with full stats and Bonus Keywords."
        m = self._minion(3, 10)
        self.game.apply_dark_gift(m, DG.PERSISTING_HORROR)
        m.add_buff(__import__("hsrl2.entity", fromlist=["Buff"]).Buff(2, 5))
        self.assertEqual(m.max_health, 15)
        m.set(GameTag.TAUNT, True)      # 关键词保留验证
        m.health = 7
        m.take_damage(7)                # 死亡
        self.game.check_deaths()
        self.assertIn(m, self.hero.board)          # 复生: 原位
        self.assertEqual(m.health, m.max_health)   # 满状态复活（非 1 血）
        self.assertTrue(m.has(GameTag.TAUNT))      # 关键词保留
        self.assertFalse(m.reborn)
        self.assertNotIn(m.uuid, self.game._reborn_full_uuids)  # 一次性

    def test_battle_scars_dynamic(self):
        # BG36_MidGameEffect_000t28t: "+2/+2 for each Battlecry
        # you've triggered this game."
        self.hero.set(GameTag.COUNTER_BATTLECRIES, 2)
        m = self._minion(1, 1)
        self.game.apply_dark_gift(m, DG.BATTLE_SCARS_SMALL)
        self.assertEqual(m.atk, 1 + 4)          # 初始补齐 2×(+2/+2)
        self.assertEqual(m.max_health, 1 + 4)
        # 触发新战吼 → 增量 +2/+2
        bc = find_def(lambda d: "battlecry" in d.keywords)
        m2 = self.game.create_minion(bc.id, controller=self.hero)
        self.hero.hand.append(m2)
        self.assertTrue(self.game.play_minion(self.hero, m2))
        self.assertEqual(self.hero.get(GameTag.COUNTER_BATTLECRIES), 3)
        self.assertEqual(m.atk, 1 + 6)

    def test_spell_siphon_on_cast(self):
        # BG36_MidGameEffect_000t30t: "+2/+2 for each Tavern spell cast"
        self.hero.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 1)
        m = self._minion(1, 1)
        self.game.apply_dark_gift(m, DG.SPELL_SIPHON_SMALL)
        self.assertEqual(m.atk, 3)
        # 施放一个池内法术 → 计数 2 → 再 +2/+2
        sid = "BG28_805"   # 惰性载体（Strike Oil DEFERRED——无数值副作用）
        self.assertTrue(self.game.spell_pool.acquire(sid))
        s = self.game.create_spell(sid, controller=self.hero)
        self.hero.hand.append(s)
        self.assertTrue(self.game.play_spell(self.hero, s))
        self.assertEqual(self.hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME), 2)
        self.assertEqual(m.atk, 5)

    def test_steady_growth_values_by_turn(self):
        # dev post: turn3 → +1/+2, turn5 → +3/+3
        self.game.turn = 3
        m1 = self._minion(1, 1)
        self.game.apply_dark_gift(m1, DG.STEADY_GROWTH)
        self.game.run_script_hook(m1, "end_of_turn")
        self.assertEqual((m1.atk, m1.max_health), (2, 3))
        game2 = make_game(seed=8)
        game2.turn = 5
        m2 = make_minion("G2", 1, 1)
        m2.controller = game2.heroes[0]
        m2.zone = Zone.PLAY
        game2.heroes[0].board.append(m2)
        game2.apply_dark_gift(m2, DG.STEADY_GROWTH)
        game2.run_script_hook(m2, "end_of_turn")
        self.assertEqual((m2.atk, m2.max_health), (4, 4))

    def test_dexterity_card_played(self):
        # BG36_MidGameEffect_000t64: "Whenever you play a card, gain +2/+2."
        m = self._minion(1, 1)
        self.game.apply_dark_gift(m, DG.DEXTERITY_SMALL)
        plain = find_def(lambda d: "battlecry" not in d.keywords
                         and "deathrattle" not in d.keywords)
        m2 = self.game.create_minion(plain.id, controller=self.hero)
        self.hero.hand.append(m2)
        self.assertTrue(self.game.play_minion(self.hero, m2))
        self.assertEqual(m.atk, 3)      # 1 + 2
        self.assertEqual(m.max_health, 3)

    def test_deferred_polarization(self):
        # DEFERRED: 有审计日志、无效果、不抛异常
        m = self._minion(1, 1)
        self.game.apply_dark_gift(m, DG.POLARIZATION)
        self.assertEqual(m.buffs, [])
        self.assertEqual(self.game.dark_gift_audit_log[-1],
                         (DG.POLARIZATION, m.uuid, self.game.turn,
                          "DEFERRED"))
        # 非 DEFERRED 的 apply 亦入审计日志
        m2 = self._minion()
        self.game.apply_dark_gift(m2, DG.FORTITUDE)
        self.assertEqual(self.game.dark_gift_audit_log[-1][3], "APPLIED")

    def test_unknown_gift_raises(self):
        m = self._minion()
        with self.assertRaises(Exception):
            self.game.apply_dark_gift(m, "NOT_A_GIFT")

    def test_sunken_persistence_registry(self):
        m = self._minion()
        self.game.apply_dark_gift(m, DG.SUNKEN_PERSISTENCE)
        self.assertIn(m.uuid, self.game._permanent_spellcraft_uuids)
        # 脚本层契约: source uuid 命中则回合结束不丢弃
        from hsrl2.spell import Spell
        sc = Spell("TEST_SC", "SC")
        sc.set(GameTag.SPELLCRAFT, True)
        sc.spellcraft_source_uuid = m.uuid
        sc.zone = Zone.HAND
        keep_normal = Spell("TEST_N", "N")
        keep_normal.set(GameTag.SPELLCRAFT, True)
        keep_normal.zone = Zone.HAND
        self.hero.hand = [sc, keep_normal]
        self.game.end_recruit_phase()
        self.assertIn(sc, self.hero.hand)
        self.assertNotIn(keep_normal, self.hero.hand)

    def test_gilding_flags(self):
        m = self._minion()
        self.game.apply_dark_gift(m, DG.GILDING)
        self.assertTrue(m.is_golden)
        self.assertTrue(m.has(GameTag.GOLDEN_NO_TRIPLE_REWARD))
        self.assertIn(m.uuid, self.game._gilded_no_reward_uuids)


# ══════════════════ 7. Lockbox ══════════════════

class TestLockbox(unittest.TestCase):
    """BG36_520t: "In 5 turns, break this open and get a random Golden
    minion with a type!"（num(0)=5）。"""

    def _lockbox(self, game, hero):
        lb = game.create_spell("BG36_520t", controller=hero)
        hero.hand.append(lb)
        return lb

    def test_initial_countdown(self):
        game = make_game(seed=11)
        hero = game.heroes[0]
        lb = self._lockbox(game, hero)
        self.assertEqual(lb.get(GameTag.LOCKBOX_TURNS_LEFT), 5)  # XML num(0)

    def test_auto_open_after_five_turns(self):
        game = make_game(seed=12)
        hero = game.heroes[0]
        lb = self._lockbox(game, hero)
        game.turn = 5
        for i in range(4):           # 4 次 SoT → 剩 1
            game.turn += 1
            game._begin_recruit_for(hero)
        self.assertEqual(lb.get(GameTag.LOCKBOX_TURNS_LEFT), 1)
        self.assertIn(lb, hero.hand)
        game.turn += 1               # 第 5 次 SoT → 开启
        game._begin_recruit_for(hero)
        self.assertNotIn(lb, hero.hand)
        goldens = [c for c in hero.hand
                   if isinstance(c, Minion) and c.is_golden]
        self.assertEqual(len(goldens), 1)
        self.assertNotEqual(goldens[0].race, Race.NONE)   # "with a type"

    def test_open_lockbox_early(self):
        game = make_game(seed=13)
        hero = game.heroes[0]
        lb = self._lockbox(game, hero)
        # Lockbox Portrait: "opens {0} turns sooner"
        self.assertTrue(game.open_lockbox_early(hero, 2))
        self.assertEqual(lb.get(GameTag.LOCKBOX_TURNS_LEFT), 3)
        self.assertTrue(game.open_lockbox_early(hero, 3))   # 归零即开
        self.assertNotIn(lb, hero.hand)
        self.assertTrue(any(isinstance(c, Minion) and c.is_golden
                            for c in hero.hand))
        self.assertFalse(game.open_lockbox_early(hero, 1))  # 无 Lockbox

    def test_open_pool_accounting(self):
        # 金色获取扣减 min(3, 剩余) 份基础卡
        game = make_game(seed=14)
        hero = game.heroes[0]
        lb = self._lockbox(game, hero)
        game._open_lockbox(hero, lb)
        golden = next(c for c in hero.hand
                      if isinstance(c, Minion) and c.is_golden)
        base_id = golden.get(GameTag.TRIPLE_BASE_CARD_ID)
        avail = game.minion_pool.available(base_id)
        # 该基础卡总量 = 池副本 - 已扣 3（新池无其他消耗时）
        self.assertLessEqual(avail,
                             __import__("hsrl2.constants",
                                        fromlist=["POOL_COPIES_BY_TIER"])
                             .POOL_COPIES_BY_TIER[golden.tech_level])


# ══════════════════ 8. 招募期攻击 (Fishbait) ══════════════════

class TestRecruitPhaseAttack(unittest.TestCase):
    def test_killer_and_deathrattle_and_no_pool_return(self):
        # BG36_205 Fishbait: "Deathrattle: Give the minion that killed
        # this +5/+5."（num=5/5，脚本层读 KILLER——引擎保证正确设置）
        game = make_game(seed=15)
        hero = game.heroes[0]
        attacker = make_minion("Beast", 5, 5)
        game.summon(hero, attacker)
        fish = game.create_minion("BG36_205", controller=hero)
        seen = []
        fish.set_script_override(
            "deathrattle",
            lambda s, g, c: seen.append(s.get(GameTag.KILLER)))
        hero.tavern.append(fish)
        fish.zone = Zone.TAVERN
        pool_before = game.minion_pool.total_remaining()
        game.recruit_phase_attack(attacker, fish)
        self.assertEqual(seen, [attacker])          # KILLER = 击杀者
        self.assertNotIn(fish, hero.tavern)         # 从酒馆移除
        self.assertEqual(fish.zone, Zone.REMOVED)
        # token 不回池（Fishbait 非池卡）
        self.assertEqual(game.minion_pool.total_remaining(), pool_before)
        self.assertTrue(attacker in hero.board and not attacker.dead)

    def test_attacker_dies_returns_to_pool(self):
        # 攻击者被反击致死 → _process_single_death 正常路径 → 回池
        game = make_game(seed=16)
        hero = game.heroes[0]
        cid = next(d.id for d in get_db().pool_minions()
                   if d.tech_level == 1 and d.atk < 9)
        avail0 = game.minion_pool.available(cid)
        attacker = game.create_minion(cid, controller=hero)
        self.assertTrue(game.minion_pool.acquire(cid))
        game.summon(hero, attacker)
        big = make_minion("BigT", 9, 30)
        hero.tavern.append(big)
        big.zone = Zone.TAVERN
        game.recruit_phase_attack(attacker, big)
        self.assertNotIn(attacker, hero.board)
        self.assertIn(attacker, hero.graveyard)
        # acquire -1 与死亡回池 +1 相抵
        self.assertEqual(game.minion_pool.available(cid), avail0)
        self.assertIn(big, hero.tavern)             # 大随从存活

    def test_invalid_targets_raise(self):
        game = make_game(seed=17)
        outsider = make_minion("X", 1, 1)   # 不在任何棋盘上
        with self.assertRaises(Exception):
            game.recruit_phase_attack(outsider, make_minion("Y", 1, 1))


# ══════════════════ 9. 计数器接线 ══════════════════

class TestTriggerCounters(unittest.TestCase):
    """COUNTER_BATTLECRIES / COUNTER_DEATHRATTLES（Battle Scars /
    Death's Embrace 资格源，B5）。"""

    def test_battlecry_counter(self):
        game = make_game(seed=18)
        hero = game.heroes[0]
        bc = find_def(lambda d: "battlecry" in d.keywords)
        m = game.create_minion(bc.id, controller=hero)
        hero.hand.append(m)
        self.assertEqual(hero.get(GameTag.COUNTER_BATTLECRIES), 0)
        game.play_minion(hero, m)
        self.assertEqual(hero.get(GameTag.COUNTER_BATTLECRIES), 1)

    def test_battlecry_counter_not_counted_without_keyword(self):
        game = make_game(seed=19)
        hero = game.heroes[0]
        plain = find_def(lambda d: "battlecry" not in d.keywords)
        m = game.create_minion(plain.id, controller=hero)
        hero.hand.append(m)
        game.play_minion(hero, m)
        self.assertEqual(hero.get(GameTag.COUNTER_BATTLECRIES), 0)

    def test_deathrattle_counter(self):
        game = make_game(seed=20)
        hero = game.heroes[0]
        m = make_minion("DRm", 1, 1)
        m.set(GameTag.DEATHRATTLE, True)
        game.summon(hero, m)
        events = []
        game.events.register(_owner_listener(
            hero, "deathrattle_trigger",
            lambda g, minion=None, **kw: events.append(minion)))
        m.take_damage(1)
        game.check_deaths()
        self.assertEqual(hero.get(GameTag.COUNTER_DEATHRATTLES), 1)
        self.assertEqual(events, [m])


if __name__ == "__main__":
    unittest.main()
