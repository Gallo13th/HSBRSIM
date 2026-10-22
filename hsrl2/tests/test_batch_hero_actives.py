"""批次 hero_actives 主动英雄技能语义测试（作业单 2026-08-23，16 技能）。

驱动协议（game.use_hero_power）:
  - 定向技能: use_hero_power(hero) → True + pending_choices[0].kind ==
    "hero_power_target" → choose(0) → _finish_hero_power（扣费在选定后）
  - uses_per_turn 耗尽 / 金币不足 / 无合法目标 → False 且金币不动
  - Edwin 计数走 on_bind 显式接线（hero_passives 批同协议——主线
    start_game 接线缺口，测试显式调用）
数值断言一律从 CardDef.num()/cost 计算（TEST_SOP §4）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2 import constants as C
from hsrl2 import entity
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.pools import SpellPool
from hsrl2.scripts import REGISTRY
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

PLAIN_T1 = "BG25_001"          # Risen Rider T1——未注册脚本（驱动用）


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(card_id: str = "TEST_HERO_B", name: str = "B") -> Hero:
    return Hero(card_id, name)


def make_game(hero_a: Hero, seed: int = 42) -> Game:
    return Game([hero_a, make_hero()], get_db(), seed=seed)


def power_cost(hero: Hero) -> int:
    d = get_db().get(hero.card_id)
    return get_db().get(d.hero_power_id).cost


def put_tavern_minion(game: Game, hero: Hero, card_id: str,
                      buff: tuple[int, int] | None = None) -> Minion:
    """馆内展示随从（不占池——测试只驱动区域语义，池断言用前后差）。"""
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    if buff is not None:
        m.add_buff(entity.Buff(atk=buff[0], health=buff[1]))
    return m


def choose_target(game: Game, kind: str = "hero_power_target"):
    choice = game.pending_choices.pop(0)
    assert choice.kind == kind, f"expect {kind}, got {choice.kind}"
    pick = choice.options[0]
    choice.choose(0)
    return pick


class TestRegistryState(unittest.TestCase):
    """批次注册面: 16 技能 OK; Inge AMBIGUOUS 不注册。"""

    def test_ok_powers_registered(self):
        for pid in ("BG20_HERO_101p", "BG20_HERO_103p",
                    "TB_BaconShop_HP_001", "TB_BaconShop_HP_010",
                    "TB_BaconShop_HP_024", "TB_BaconShop_HP_028",
                    "TB_BaconShop_HP_040", "TB_BaconShop_HP_049",
                    "TB_BaconShop_HP_052", "TB_BaconShop_HP_053",
                    "TB_BaconShop_HP_068", "TB_BaconShop_HP_074",
                    "TB_BaconShop_HP_075", "TB_BaconShop_HP_084",
                    "BG28_HERO_801p", "BG34_HERO_001p"):
            self.assertIn(pid, REGISTRY)

    def test_inge_registered_in_combat3(self):
        # combat3 批已解冻 Inge（攻/血交替 × 每回合 2 次, wiki 交替
        # 语义实证——"Swaps to Health next turn!"）——不再是 AMBIGUOUS
        self.assertIn("BG26_HERO_102p", REGISTRY)


class TestXyrella(unittest.TestCase):
    """BG20_HERO_101p See the Light — Choose tavern minion, set 2/2, to hand."""

    def test_steal_sets_stats_to_2_and_pool_net_zero(self):
        game = make_game(Hero("BG20_HERO_101", "Xyrella"))
        a = game.heroes[0]
        a.gold = 10
        m = put_tavern_minion(game, a, PLAIN_T1, buff=(3, 3))
        base_def = get_db().get(PLAIN_T1)
        self.assertNotEqual((m.atk, m.max_health), (2, 2))
        avail = game.minion_pool.available(PLAIN_T1)
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(len(game.pending_choices), 1)
        picked = choose_target(game)
        self.assertIs(picked, m)
        self.assertEqual(a.gold, 10 - power_cost(a))
        self.assertIn(m, a.hand)
        self.assertEqual((m.atk, m.health, m.max_health), (2, 2, 2))
        self.assertNotIn(m, a.tavern)
        self.assertEqual(game.minion_pool.available(PLAIN_T1), avail)

    def test_no_tavern_minions_unusable(self):
        game = make_game(Hero("BG20_HERO_101", "Xyrella"))
        a = game.heroes[0]
        a.gold = 10
        self.assertFalse(game.use_hero_power(a))
        self.assertEqual(a.gold, 10)

    def test_insufficient_gold(self):
        game = make_game(Hero("BG20_HERO_101", "Xyrella"))
        a = game.heroes[0]
        a.gold = power_cost(a) - 1
        put_tavern_minion(game, a, PLAIN_T1)
        self.assertFalse(game.use_hero_power(a))
        self.assertEqual(a.gold, power_cost(a) - 1)


class TestBlackthorn(unittest.TestCase):
    """BG20_HERO_103p Bloodbound — Get 2 Blood Gems, twice per turn."""

    def test_two_gems_twice_per_turn_then_exhausted(self):
        game = make_game(Hero("BG20_HERO_103", "Blackthorn"))
        a = game.heroes[0]
        a.gold = 10
        cost = power_cost(a)
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(len(a.hand), 2)
        self.assertTrue(all(s.card_id == "BG20_GEM" for s in a.hand))
        self.assertEqual(a.gold, 10 - cost)
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(len(a.hand), 4)
        self.assertEqual(a.gold, 10 - 2 * cost)
        self.assertFalse(game.use_hero_power(a))   # 每回 2 次
        self.assertEqual(len(a.hand), 4)

    def test_insufficient_gold(self):
        game = make_game(Hero("BG20_HERO_103", "Blackthorn"))
        a = game.heroes[0]
        a.gold = 0
        self.assertFalse(game.use_hero_power(a))


class TestEdwin(unittest.TestCase):
    """TB_BaconShop_HP_001 Sharpen Blades — +num(1)/+num(1), improves
    after every num(0) cards bought."""

    def setUp(self):
        # TB_BaconShop_HERO_01 = Edwin VanCleef → TB_BaconShop_HP_001
        self.game = make_game(Hero("TB_BaconShop_HERO_01", "Edwin"))
        # TB_BaconShop_HERO_01 = Edwin VanCleef
        self.a = self.game.heroes[0]
        self.d = get_db().get("TB_BaconShop_HP_001")
        REGISTRY["TB_BaconShop_HP_001"].on_bind(self.a, self.game)
        self.target = self.game.create_minion(PLAIN_T1,
                                              controller=self.a)
        self.game.summon(self.a, self.target)

    def _use(self) -> None:
        self.a.gold = 10
        self.assertTrue(self.game.use_hero_power(self.a))
        choose_target(self.game)

    def test_base_value_without_buys(self):
        self.a.gold = 10
        atk0 = self.target.atk
        self.assertTrue(self.game.use_hero_power(self.a))
        choose_target(self.game)
        self.assertEqual(self.target.atk, atk0 + self.d.num(1))
        self.assertEqual(self.target.max_health,
                         get_db().get(PLAIN_T1).health + self.d.num(1))

    def test_improves_after_threshold_card_buys(self):
        self.a.gold = 30
        # 4 张互不相同的 T1（每 id ≤2 份含板上目标——不触发三连）
        t1_ids = [d.id for d in get_db().pool_minions()
                  if d.tech_level == 1][:4]
        self.assertEqual(len(set(t1_ids)), 4)
        for cid in t1_ids:
            m = self.game.create_minion(cid, controller=self.a)
            m.zone = Zone.TAVERN
            self.a.tavern.append(m)
            self.assertTrue(self.game.buy_from_tavern(self.a, m))
        atk0 = self.target.atk
        self._use()
        self.assertEqual(self.target.atk, atk0 + self.d.num(1) + 1)

    def test_spells_count_and_opponent_not_counted(self):
        self.a.gold = 30
        sid = "BG28_805"    # Strike Oil T2 池法术
        self.assertTrue(self.game.spell_pool.acquire(sid))
        s = self.game.create_spell(sid, controller=self.a)
        s.zone = Zone.TAVERN
        self.a.tavern.append(s)
        self.assertTrue(self.game.buy_from_tavern(self.a, s))
        b = self.game.heroes[1]
        bm = self.game.create_minion(PLAIN_T1, controller=b)
        bm.zone = Zone.TAVERN
        b.tavern.append(bm)
        b.gold = 10
        self.assertTrue(self.game.buy_from_tavern(b, bm))
        self.assertEqual(getattr(self.a, "_edwin_buys", 0), 1)


class TestGeorge(unittest.TestCase):
    """TB_BaconShop_HP_010 Boon of Light — targeted Divine Shield."""

    def test_gives_divine_shield_with_choice_flow(self):
        game = make_game(Hero("TB_BaconShop_HERO_15", "George"))
        a = game.heroes[0]
        a.gold = 10
        m = game.create_minion(PLAIN_T1, controller=a)
        game.summon(a, m)
        self.assertTrue(game.use_hero_power(a))
        picked = choose_target(game)
        self.assertIs(picked, m)
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))
        self.assertEqual(a.gold, 10 - power_cost(a))

    def test_empty_board_unusable_no_charge(self):
        game = make_game(Hero("TB_BaconShop_HERO_15", "George"))
        a = game.heroes[0]
        a.gold = 10
        self.assertFalse(game.use_hero_power(a))
        self.assertEqual(a.gold, 10)


class TestLichKing(unittest.TestCase):
    """TB_BaconShop_HP_024 Reborn Rites — Reborn until next turn."""

    def test_reborn_granted_then_expires_at_next_turn_start(self):
        game = make_game(Hero("TB_BaconShop_HERO_22", "Lich King"))
        a = game.heroes[0]
        b = game.heroes[1]
        a.gold = 10
        # BG23_000 无原生关键词（BG25_001 Risen Rider 自带 Reborn 不可用）
        m = game.create_minion("BG23_000", controller=a)
        game.summon(a, m)
        self.assertFalse(m.has(GameTag.REBORN))
        self.assertTrue(game.use_hero_power(a))
        picked = choose_target(game)
        self.assertIs(picked, m)
        self.assertTrue(m.has(GameTag.REBORN))
        # "until next turn" = 控制者的**下一个**招募阶段开始（单 tick，
        # 对照 spells._expire_at_next_turn——对抗审查 MAJOR 修复）
        game.events.fire(game, "turn_start", turn=2, hero=b)
        self.assertTrue(m.has(GameTag.REBORN))   # 他人回合不消耗
        game.events.fire(game, "turn_start", turn=2, hero=a)
        self.assertFalse(m.has(GameTag.REBORN))

    def test_granted_reborn_lasts_through_combat_then_clears(self):
        """真实路径: 授予 → 当回合战斗（复生生效）→ 次回合开始清除。"""
        game = make_game(Hero("TB_BaconShop_HERO_22", "Lich King"))
        a = game.heroes[0]
        a.gold = 10
        m = game.create_minion("BG23_000", controller=a)
        game.summon(a, m)
        self.assertTrue(game.use_hero_power(a))
        choose_target(game)
        self.assertTrue(m.has(GameTag.REBORN))
        game.end_recruit_phase()                    # 战斗 + turn → 2
        self.assertFalse(m.has(GameTag.REBORN))     # 下一招募阶段已清除

    def test_innate_reborn_not_stripped(self):
        game = make_game(Hero("TB_BaconShop_HERO_22", "Lich King"))
        a = game.heroes[0]
        a.gold = 10
        m = game.create_minion(PLAIN_T1, controller=a)
        m.set(GameTag.REBORN, True)     # 原生复生（Risen Rider 自带）
        game.summon(a, m)
        self.assertTrue(game.use_hero_power(a))
        choose_target(game)
        game.events.fire(game, "turn_start", turn=2, hero=a)
        self.assertTrue(m.has(GameTag.REBORN))   # 不误清（未注册过期监听）


class TestPyramad(unittest.TestCase):
    """TB_BaconShop_HP_040 Brick by Brick — steal random tavern minion,
    double its Health."""

    def test_single_minion_deterministic_double_health(self):
        game = make_game(Hero("TB_BaconShop_HERO_39", "Pyramad"))
        a = game.heroes[0]
        a.gold = 10
        d = get_db().get(PLAIN_T1)
        m = put_tavern_minion(game, a, PLAIN_T1, buff=(1, 2))
        atk0, hp0 = m.atk, m.max_health
        avail = game.minion_pool.available(PLAIN_T1)
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(a.gold, 10 - power_cost(a))
        self.assertIn(m, a.hand)
        self.assertEqual(m.atk, atk0)            # 攻击不变
        self.assertEqual(m.max_health, hp0 * 2)  # 上限×2
        self.assertEqual(m.health, hp0 * 2)      # 当前血同步翻倍
        self.assertEqual(game.minion_pool.available(PLAIN_T1), avail)
        self.assertEqual(d.name, "Risen Rider")

    def test_empty_tavern_falls_flat_gold_spent(self):
        game = make_game(Hero("TB_BaconShop_HERO_39", "Pyramad"))
        a = game.heroes[0]
        a.gold = 10
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(a.gold, 10 - power_cost(a))
        self.assertEqual(a.hand, [])


class TestMaiev(unittest.TestCase):
    """TB_BaconShop_HP_068 Imprison — lock tavern card in hand, unlock
    after 2 turns."""

    def test_lock_in_hand_and_unlock_after_two_turns(self):
        game = make_game(Hero("TB_BaconShop_HERO_62", "Maiev"))
        a = game.heroes[0]
        a.gold = 10
        m = put_tavern_minion(game, a, PLAIN_T1)
        self.assertTrue(game.use_hero_power(a))
        picked = choose_target(game)
        self.assertIs(picked, m)
        self.assertIn(m, a.hand)
        self.assertTrue(m.has(GameTag.LOCKED_IN_HAND))
        self.assertFalse(game.play_minion(a, m))   # 锁定不可打出
        game.events.fire(game, "turn_start", turn=2, hero=a)
        self.assertFalse(game.play_minion(a, m))   # 第 1 回合仍锁
        game.events.fire(game, "turn_start", turn=3, hero=a)
        self.assertTrue(game.play_minion(a, m))    # 第 2 回合解锁
        self.assertIn(m, a.board)


class TestEudora(unittest.TestCase):
    """TB_BaconShop_HP_074 Buried Treasure — dig num(0)=4 → golden."""

    def _dig_once(self, game, a):
        a.clear(GameTag.HERO_POWER_USED_THIS_TURN)   # 模拟回合推进
        a.gold = 10
        self.assertTrue(game.use_hero_power(a))

    def test_golden_on_nth_dig_pool_and_reset(self):
        game = make_game(Hero("TB_BaconShop_HERO_64", "Eudora"))
        a = game.heroes[0]
        d = get_db().get("TB_BaconShop_HP_074")
        for i in range(d.num(0) - 1):
            self._dig_once(game, a)
            self.assertEqual([c for c in a.hand if c.is_golden], [])
        self._dig_once(game, a)
        goldens = [c for c in a.hand if isinstance(c, Minion) and c.is_golden]
        self.assertEqual(len(goldens), 1)
        base = goldens[0].get(GameTag.TRIPLE_BASE_CARD_ID)
        golden_def = get_db().golden_version(get_db().get(base))
        self.assertEqual(goldens[0].card_id, golden_def.id)
        self.assertFalse(goldens[0].has(GameTag.TRIPLE_REWARD_PENDING))
        # 计数重置: 再挖 num(0)-1 次无**新**金色（金色 #1 仍在手）
        for _ in range(d.num(0) - 1):
            self._dig_once(game, a)
        self.assertEqual(len([c for c in a.hand
                               if isinstance(c, Minion) and c.is_golden]), 1)
        self._dig_once(game, a)
        self.assertEqual(len([c for c in a.hand
                               if isinstance(c, Minion) and c.is_golden]), 2)

    def test_once_per_turn(self):
        game = make_game(Hero("TB_BaconShop_HERO_64", "Eudora"))
        a = game.heroes[0]
        a.gold = 10
        self.assertTrue(game.use_hero_power(a))
        self.assertFalse(game.use_hero_power(a))

    def test_purged_card_excluded_from_drained_pool_fallback(self):
        """池耗尽 fallback 的候选列表必须排除**永久移除**的卡。

        2026-09-13 对抗验证 MINOR: `cands = avail or [全量池 id]` 会让被
        `MinionPool.purge`（Emergency Landing / Eject!）清掉的卡经"凭空
        生成金卡"路径回归（实测 7/1000 次）。此处直接观测脚本交给 RNG 的
        候选列表（确定性断言——比对随机发放结果稳健），并附发放结果面。
        """
        game = make_game(Hero("TB_BaconShop_HERO_64", "Eudora"))
        a = game.heroes[0]
        d = get_db().get("TB_BaconShop_HP_074")
        pool = game.minion_pool
        ids = [x.id for x in get_db().pool_minions()]
        target = ids[0]
        pool.purge(target)
        for cid in ids[1:]:                 # 抽干其余全部副本 → fallback 分支
            while pool.available(cid) > 0:
                self.assertTrue(pool.acquire(cid))
        self.assertEqual(pool.candidates(max_tier=7), [])    # 正对照: 池空
        seen: list = []
        real_choice = game.rng.choice

        def spy(seq, label=""):
            if label == "buried_treasure":
                seen.append(list(seq))
            return real_choice(seq, label)

        game.rng.choice = spy
        try:
            for _ in range(3):
                a.hand.clear()
                for _ in range(int(d.num(0))):
                    self._dig_once(game, a)
        finally:
            game.rng.choice = real_choice
        self.assertTrue(seen)               # 正对照: 确实走了 fallback 分支
        for cands in seen:
            self.assertNotIn(target, cands)
        bases = {c.get(GameTag.TRIPLE_BASE_CARD_ID) or c.card_id
                 for c in a.hand
                 if isinstance(c, Minion) and c.is_golden}
        self.assertTrue(bases)              # 正对照: fallback 仍在发卡
        self.assertNotIn(target, bases)     # 被 purge 的卡不得复活


class TestMalygos(unittest.TestCase):
    """TB_BaconShop_HP_052 Arcane Alteration — replace a hand card with a
    random same-Tier one, twice per turn."""

    def test_replace_minion_same_tier_and_pool_swap(self):
        game = make_game(Hero("TB_BaconShop_HERO_58", "Malygos"))
        a = game.heroes[0]
        a.gold = 10
        old = game.create_minion(PLAIN_T1, controller=a)
        a.hand.append(old)
        old.zone = Zone.HAND
        old_tier = get_db().get(PLAIN_T1).tech_level
        avail_old = game.minion_pool.available(PLAIN_T1)
        self.assertTrue(game.use_hero_power(a))
        picked = choose_target(game)
        self.assertIs(picked, old)
        self.assertEqual(len(a.hand), 1)
        new = a.hand[0]
        self.assertIsNot(new, old)
        self.assertEqual(get_db().get(new.card_id).tech_level, old_tier)
        self.assertEqual(game.minion_pool.available(PLAIN_T1),
                         avail_old + 1)   # 旧卡回池

    def test_replace_pool_spell_same_tier(self):
        game = make_game(Hero("TB_BaconShop_HERO_58", "Malygos"))
        a = game.heroes[0]
        a.gold = 10
        sid = "BG28_805"
        self.assertTrue(game.spell_pool.acquire(sid))
        avail = game.spell_pool.available(sid)   # 占 1 份后余量
        old = game.create_spell(sid, controller=a)
        a.hand.append(old)
        old.zone = Zone.HAND
        tier = get_db().get(sid).tech_level
        self.assertTrue(game.use_hero_power(a))
        choose_target(game)
        self.assertEqual(len(a.hand), 1)
        new = a.hand[0]
        self.assertIsInstance(new, Spell)
        self.assertNotEqual(new.card_id, sid)
        self.assertEqual(get_db().get(new.card_id).tech_level, tier)
        self.assertEqual(game.spell_pool.available(sid),
                         avail + 1)   # 旧回池

    def test_twice_per_turn_and_empty_hand_unusable(self):
        game = make_game(Hero("TB_BaconShop_HERO_58", "Malygos"))
        a = game.heroes[0]
        a.gold = 10
        self.assertFalse(game.use_hero_power(a))   # 空手无候选
        for _ in range(2):
            m = game.create_minion(PLAIN_T1, controller=a)
            a.hand.append(m)
            m.zone = Zone.HAND
        self.assertTrue(game.use_hero_power(a))
        choose_target(game)
        self.assertTrue(game.use_hero_power(a))
        choose_target(game)
        self.assertFalse(game.use_hero_power(a))   # 每回 2 次

    def test_replaced_minion_listeners_unregistered_and_stats_frozen(self):
        """被替换入 `REMOVED` 的手牌随从必须注销其**打出前注册**的监听器。

        真实路径: 真实 `apply_dark_gift(DG.SPELL_SIPHON_SMALL)`
        （`_make_counter_gift` 在手牌随从上注册 `tavern_spell_cast` 监听，
        无 `zone` 守卫）→ 真实 `use_hero_power` + 定向选择（把该随从移入
        `REMOVED`）→ 真实 `play_spell`（酒馆法术广播 `tavern_spell_cast`）。
        断言: (a) 被替换随从的监听器已注销; (b) 施法后其属性不再增长。
        负对照: 未被替换的同款 Dark Gift 随从（在场）照常 +2/+2——证明
        事件路径确实触发、断言非空洞。
        变异探针: 去掉 `Entity.zone` setter 的"随从进入
        `REMOVED`/`GRAVEYARD` 即注销"分支 → (a)/(b) 均失败（修复前实测:
        `target` 属性 +2/+2）。
        """
        from hsrl2 import darkgifts as DG
        game = make_game(Hero("TB_BaconShop_HERO_58", "Malygos"))
        a = game.heroes[0]
        a.gold = 10
        target = game.create_minion(PLAIN_T1, controller=a)
        a.hand.append(target)
        target.zone = Zone.HAND
        game.apply_dark_gift(target, DG.SPELL_SIPHON_SMALL)
        # 负对照载体: 同款 gift、合法在场（未被替换）
        keeper = game.create_minion(PLAIN_T1, controller=a)
        game.summon(a, keeper)
        game.apply_dark_gift(keeper, DG.SPELL_SIPHON_SMALL)

        def owners():
            return [l.owner for l in
                    game.events._listeners.get("tavern_spell_cast", [])]

        self.assertIn(target, owners())            # 前置: 离场前监听器存在
        self.assertIn(keeper, owners())
        before_target = (target.atk, target.max_health)
        before_keeper = (keeper.atk, keeper.max_health)

        self.assertTrue(game.use_hero_power(a))
        picked = choose_target(game)
        self.assertIs(picked, target)
        self.assertEqual(target.zone, Zone.REMOVED)
        # (a) 随从进入 REMOVED（自手牌）→ 监听器注销
        self.assertNotIn(target, owners())

        # 真实施法广播 tavern_spell_cast（酒馆法术）
        sp = game.create_spell("BG28_810", controller=a)
        a.hand.append(sp)
        sp.zone = Zone.HAND
        self.assertTrue(game.play_spell(a, sp))
        # (b) 已离场随从属性冻结; 负对照照常增长
        self.assertEqual((target.atk, target.max_health), before_target)
        self.assertEqual((keeper.atk - before_keeper[0],
                          keeper.max_health - before_keeper[1]), (2, 2))


class TestJandice(unittest.TestCase):
    """TB_BaconShop_HP_084 Swap, Lock, & Shop It — targeted friendly
    non-Golden ↔ random tavern minion."""

    def test_swap_keeps_buffs_and_positions(self):
        game = make_game(Hero("TB_BaconShop_HERO_71", "Jandice"))
        a = game.heroes[0]
        a.gold = 10
        mine = game.create_minion(PLAIN_T1, controller=a)
        mine.add_buff(entity.Buff(atk=5, health=5))
        game.summon(a, mine)
        shop = put_tavern_minion(game, a, "BG23_000")
        self.assertTrue(game.use_hero_power(a))
        picked = choose_target(game)
        self.assertIs(picked, mine)
        self.assertEqual(a.board, [shop])          # 馆内随从上板
        self.assertEqual(a.tavern, [mine])         # 我的随从入馆
        self.assertEqual(shop.zone, Zone.PLAY)
        self.assertEqual(mine.zone, Zone.TAVERN)
        self.assertEqual((mine.atk, mine.max_health),
                         (get_db().get(PLAIN_T1).atk + 5,
                          get_db().get(PLAIN_T1).health + 5))  # buff 保留
        self.assertEqual(a.gold, 10 - power_cost(a))

    def test_golden_only_board_unusable(self):
        game = make_game(Hero("TB_BaconShop_HERO_71", "Jandice"))
        a = game.heroes[0]
        a.gold = 10
        g = game.create_minion(PLAIN_T1, controller=a, golden=True)
        game.summon(a, g)
        put_tavern_minion(game, a, "BG23_000")
        self.assertFalse(game.use_hero_power(a))   # 非金色随从无候选

    def test_swap_unregisters_swapped_minion_listeners(self):
        """离场注销: 入馆的友方随从的 in-play 监听器必须失效。

        真实路径: 真实 `summon`（`BG26_174` Soul Rewinder 的 `on_summon`
        注册 `HERO_DAMAGE_TAKEN` 回退监听）→ 真实 `use_hero_power` 交换 →
        断言 (a) 该实体的监听器全部注销、(b) 之后英雄受伤**不再被回退**。
        变异探针: 去掉 `JandiceScript.hero_power` 末尾的
        `game.events.unregister_owner(target)` → 监听器残留 → (a)/(b)
        均失败（压测 seed 909199 永不结束即此泄漏; 见
        `docs/agents/ENGINE_BACKLOG.md` 监听器泄漏条目）。
        """
        from hsrl2.events import HERO_DAMAGE_TAKEN
        game = make_game(Hero("TB_BaconShop_HERO_71", "Jandice"))
        a = game.heroes[0]
        a.gold = 10
        rewinder = game.create_minion("BG26_174", controller=a)
        game.summon(a, rewinder)
        self.assertIn(rewinder, [l.owner for l in
                                 game.events._listeners.get(
                                     HERO_DAMAGE_TAKEN, [])])
        put_tavern_minion(game, a, "BG23_000")
        self.assertTrue(game.use_hero_power(a))
        picked = choose_target(game)
        self.assertIs(picked, rewinder)
        self.assertEqual(rewinder.zone, Zone.TAVERN)
        # (a) 监听器随离场注销
        self.assertNotIn(rewinder, [l.owner for l in
                                    game.events._listeners.get(
                                        HERO_DAMAGE_TAKEN, [])])
        # (b) 实践中: 受伤不再被回退（无残留监听器 rewinding 英雄伤害）
        before = (a.health, a.armor)
        a.take_damage(3)
        self.assertEqual((a.health, a.armor),
                         (before[0] - 3, before[1]))


class TestBazhial(unittest.TestCase):
    """TB_BaconShop_HP_049 Graveyard Shift — steal tavern card, take 2."""

    def test_steal_card_and_take_damage_armor_first(self):
        game = make_game(Hero("TB_BaconShop_HERO_25", "Baz'hial", armor=5))
        a = game.heroes[0]
        a.gold = 10
        m = put_tavern_minion(game, a, PLAIN_T1)
        self.assertTrue(game.use_hero_power(a))
        picked = choose_target(game)
        self.assertIs(picked, m)
        self.assertIn(m, a.hand)
        self.assertNotIn(m, a.tavern)
        self.assertEqual(a.armor, 3)     # 2 点先扣护甲
        self.assertEqual(a.health, C.HERO_BASE_HEALTH)
        self.assertEqual(a.gold, 10 - power_cost(a))


class TestRafaam(unittest.TestCase):
    """TB_BaconShop_HP_053 I'll Take That! — next combat, plain copy of
    first minion you kill."""

    def _setup_combat(self, game, a):
        atk = game.create_minion(PLAIN_T1, controller=a)
        atk.add_buff(entity.Buff(atk=9, health=9))     # 10/10
        game.summon(a, atk)
        b = game.heroes[1]
        for _ in range(2):
            game.summon(b, game.create_minion(PLAIN_T1, controller=b))

    def test_first_enemy_death_copied_plain_not_from_pool(self):
        game = make_game(Hero("TB_BaconShop_HERO_45", "Rafaam"))
        a = game.heroes[0]
        a.gold = 10
        avail = game.minion_pool.available(PLAIN_T1)
        self._setup_combat(game, a)
        self.assertTrue(game.use_hero_power(a))
        game.run_combat(a, game.heroes[1])
        copies = [c for c in a.hand if isinstance(c, Minion)]
        self.assertEqual(len(copies), 1)              # 双杀只复制首个
        d = get_db().get(PLAIN_T1)
        self.assertEqual(copies[0].card_id, PLAIN_T1)
        self.assertEqual((copies[0].atk, copies[0].max_health),
                         (d.atk, d.health))           # plain=无 buff
        self.assertEqual(game.minion_pool.available(PLAIN_T1), avail)

    def test_armed_only_for_next_combat(self):
        game = make_game(Hero("TB_BaconShop_HERO_45", "Rafaam"))
        a = game.heroes[0]
        a.gold = 10
        self._setup_combat(game, a)
        self.assertTrue(game.use_hero_power(a))
        game.events.fire(game, "turn_start", turn=2, hero=a)   # 作废
        game.run_combat(a, game.heroes[1])
        self.assertEqual([c for c in a.hand if isinstance(c, Minion)], [])


class TestToki(unittest.TestCase):
    """TB_BaconShop_HP_028 Temporal Tavern — refresh incl. two tier+1."""

    def test_refresh_includes_exactly_two_higher_tier_minions(self):
        game = make_game(Hero("TB_BaconShop_HERO_28", "Toki"))
        a = game.heroes[0]
        a.gold = 10
        a.set(GameTag.TAVERN_TIER, 2)
        self.assertTrue(game.use_hero_power(a))
        minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertEqual(len(minions), C.TAVERN_OFFERS[2])
        higher = [m for m in minions if m.tech_level == 3]
        self.assertEqual(len(higher), 2)
        self.assertEqual(a.gold, 10 - power_cost(a))   # 不另扣刷新费

    def test_t6_injects_from_tier7_pool(self):
        game = make_game(Hero("TB_BaconShop_HERO_28", "Toki"))
        a = game.heroes[0]
        a.gold = 10
        a.set(GameTag.TAVERN_TIER, 6)
        t7_avail = sum(game.minion_pool.available(d.id)
                       for d in get_db().pool_minions()
                       if d.tech_level == 7)
        self.assertTrue(game.use_hero_power(a))
        minions = [e for e in a.tavern if isinstance(e, Minion)]
        n7 = len([m for m in minions if m.tech_level == 7])
        self.assertEqual(n7, min(2, t7_avail))

    def test_golden_arena_tavern_return_uses_base_card_id(self):
        """对抗审查 MAJOR: 馆内实体是金色 card_id 时回池必须走
        TRIPLE_BASE_CARD_ID——否则 release 静默 no-op（基础副本泄漏）。

        差分法: 同 seed 跑两次（普通馆 vs The Golden Arena 金馆），
        池总量变化必须一致（金色化不改变池记账）。"""
        def pool_total(g):
            return sum(g.minion_pool.available(d.id)
                       for d in get_db().pool_minions())

        def run(golden):
            game = make_game(Hero("TB_BaconShop_HERO_28", "Toki"), seed=7)
            a = game.heroes[0]
            a.gold = 10
            a.set(GameTag.TAVERN_TIER, 2)
            game._tavern_golden = golden
            before = pool_total(game)
            self.assertTrue(game.use_hero_power(a))
            return pool_total(game) - before

        self.assertEqual(run(True), run(False))

    def test_single_card_frozen_tavern_minion_is_kept(self):
        """对抗审查 MAJOR: 单卡冻结（实体级 FROZEN）馆内随从不得被替换。"""
        game = make_game(Hero("TB_BaconShop_HERO_28", "Toki"))
        a = game.heroes[0]
        a.gold = 10
        a.set(GameTag.TAVERN_TIER, 2)
        frozen = put_tavern_minion(game, a, PLAIN_T1)
        frozen.set(GameTag.FROZEN, True)
        self.assertTrue(game.use_hero_power(a))
        self.assertIn(frozen, a.tavern)      # 冻结项保留原位

    # ── 异变 101/102 存在档白名单（真实 start_game + use_hero_power）──

    ODDS = "BG27_Anomaly_101"            # Only Tavern Tiers 1, 3, and 5
    EVEN = "BG27_Anomaly_102"            # Only Tavern Tiers 2, 4, and 6

    @staticmethod
    def _tokis(anomaly, tier: int, seed: int = 5150):
        """真实 `start_game`（异变 on_bind 落阶梯）+ 真实 `use_hero_power`。

        返回 (game, hero, 馆内随从 tech_level 列表)。
        """
        g = Game([Hero("TB_BaconShop_HERO_28", "Toki"), make_hero()],
                 get_db(), seed=seed, anomaly=anomaly)
        g.start_game()
        a = g.heroes[0]
        a.gold = 99
        a.set(GameTag.TAVERN_TIER, tier)
        g.refresh_tavern(a)
        assert g.use_hero_power(a)
        return g, a, [m.tech_level for m in a.tavern
                      if isinstance(m, Minion)]

    def test_odds_t1_does_not_inject_nonexistent_tier2(self):
        """101 在 T1: T2 不存在 → "two from a Tier higher" 落空; 酒馆
        保持正常展示位数（不得缩小）; 也不跳档到 T3。"""
        g, a, tiers = self._tokis(self.ODDS, 1)
        self.assertEqual(g._tavern_tier_ladder, (1, 3, 5))
        self.assertEqual(len(tiers), C.TAVERN_OFFERS[1])   # 刷新照常
        self.assertEqual(set(tiers), {1})                  # 无 T2、不跳 T3
        # 正对照: 标准局同 seed/同 T1 → 恰 2 只 T2 被注入
        _c, _b, ctrl = self._tokis(None, 1)
        self.assertEqual(len(ctrl), C.TAVERN_OFFERS[1])
        self.assertEqual(ctrl.count(2), 2)

    def test_even_t2_does_not_inject_nonexistent_tier3(self):
        """102 在 T2: T3 不存在 → 落空; 馆内只见存在档 T2。"""
        g, a, tiers = self._tokis(self.EVEN, 2)
        self.assertEqual(g._tavern_tier_ladder, (2, 4, 6))
        self.assertEqual(len(tiers), C.TAVERN_OFFERS[2])
        self.assertEqual(set(tiers), {2})
        # 正对照: 标准局同 seed/同 T2 → 恰 2 只 T3 被注入
        _c, _b, ctrl = self._tokis(None, 2)
        self.assertEqual(ctrl.count(3), 2)

    def test_odds_t3_does_not_inject_nonexistent_tier4(self):
        """101 在 T3: T4 不存在 → 落空; 正常档 {1,3} 照常展示。"""
        g, a, tiers = self._tokis(self.ODDS, 3)
        self.assertEqual(len(tiers), C.TAVERN_OFFERS[3])
        self.assertTrue(set(tiers) <= {1, 3})
        self.assertNotIn(4, tiers)


class TestHooktusk(unittest.TestCase):
    """TB_BaconShop_HP_075 Trash for Treasure — remove friendly, discover
    a lower-Tier minion."""

    def _t2_id(self) -> str:
        return next(d.id for d in get_db().pool_minions()
                    if d.tech_level == 2)

    def test_remove_without_pool_return_then_discover_tier_lower(self):
        game = make_game(Hero("TB_BaconShop_HERO_67", "Hooktusk"))
        a = game.heroes[0]
        a.gold = 10
        t2 = self._t2_id()
        m = game.create_minion(t2, controller=a)
        game.summon(a, m)
        avail_t2 = game.minion_pool.available(t2)
        self.assertTrue(game.use_hero_power(a))
        choose_target(game)
        self.assertNotIn(m, a.board)                 # 移除
        self.assertEqual(game.minion_pool.available(t2), avail_t2)  # 不回池
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "discover_minion")
        self.assertTrue(all(get_db().get(cid).tech_level == 1
                            for cid in choice.options))
        t1_held = game.minion_pool.available(choice.options[0])
        choice.choose(0)
        self.assertEqual(len(a.hand), 1)
        self.assertEqual(get_db().get(a.hand[0].card_id).tech_level, 1)
        # 预留语义: 选项生成时已占池
        self.assertEqual(game.minion_pool.available(choice.options[0]),
                         t1_held)

    def test_t1_target_discovers_nothing(self):
        game = make_game(Hero("TB_BaconShop_HERO_67", "Hooktusk"))
        a = game.heroes[0]
        a.gold = 10
        m = game.create_minion(PLAIN_T1, controller=a)   # T1 → 无更低 tier
        game.summon(a, m)
        self.assertTrue(game.use_hero_power(a))
        choose_target(game)
        self.assertNotIn(m, a.board)
        self.assertEqual(game.pending_choices, [])   # 无候选落空


class TestChromie(unittest.TestCase):
    """BG34_HERO_001p Mana Per Minute — refresh with Tavern spells."""

    def test_tavern_becomes_all_spells(self):
        game = make_game(Hero("BG34_HERO_001", "Chromie"))
        a = game.heroes[0]
        a.gold = 10
        a.set(GameTag.TAVERN_TIER, 2)
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(len(a.tavern), C.TAVERN_OFFERS[2])
        self.assertTrue(all(isinstance(e, Spell) for e in a.tavern))
        self.assertEqual(a.gold, 10 - power_cost(a))


class TestHollidae(unittest.TestCase):
    """BG28_HERO_801p Blessing of the Nine Frogs — random Tavern spell."""

    def test_get_random_tier_capped_tavern_spell(self):
        game = make_game(Hero("BG28_HERO_801", "Holli'dae"))
        a = game.heroes[0]
        a.gold = 10
        a.set(GameTag.TAVERN_TIER, 2)
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(len(a.hand), 1)
        s = a.hand[0]
        self.assertIsInstance(s, Spell)
        d = get_db().get(s.card_id)
        self.assertTrue(d.is_pool_spell)
        self.assertLessEqual(d.tech_level, 2)
        self.assertEqual(game.spell_pool.available(s.card_id),
                         SpellPool.POOL_COPIES_BY_TIER[d.tech_level] - 1)  # 占池
        self.assertEqual(a.gold, 10 - power_cost(a))


if __name__ == "__main__":
    unittest.main()
