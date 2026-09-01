"""批次 hero_actives2 主动英雄技能语义测试（作业单 2026-08-23，22 技能）。

驱动协议（game.use_hero_power 新特性）:
  - available 门槛（turn/tier/冷却/满手/快照）→ False 且金币不动
  - uses_per_game 计数（HERO_POWER_USES_THIS_GAME）→ 耗尽 False
  - cost_override 动态费（Elise 递增 / Togwaggle/Nobundo 回合衰减 /
    raw 无 cost 键 = 免费 0——CardDef.cost=3 为构造缺省假值）
  - target_count=2 双目标链（Vol'jin）——两个连续 PendingChoice
  - next_opponent_warband 快照（Tess/Scabbs/Holmes——直接注入
    game._next_opponent_snapshot，引擎 game.py:1467 数据面）
数值断言一律从 CardDef raw/num() 计算（TEST_SOP §4）。
"""

from __future__ import annotations

import unittest
from collections import Counter
from pathlib import Path

from hsrl2 import constants as C
from hsrl2 import entity
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

PLAIN_T1 = "BG25_001"          # Risen Rider T1（Rafaam 测试同款）
UNDEAD_T2 = "BG25_011"         # Nerubian Deathswarmer T2 Undead
COINER = "BG23_002"            # Shell Collector——战吼得 Tavern Coin
SHINY_RING = "BG28_168"        # Give your minions +1/+1（无目标池法术）
TAVERN_COIN = "BG28_810"       # Tavern Coin

MAGNETIC_MECHS = {"BG26_146", "BG26_147", "BG32_172", "BG35_341",
                  "BG_BOT_911", "BG_DEEP_015"}

KING_VARIANT_IDS = ["TB_BaconShop_HP_041" + s
                    for s in "a b c d f g h i j k".split()]


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(hero_a_card: str, seed: int = 42) -> Game:
    return Game([Hero(hero_a_card, "A"), Hero("TEST_HERO_B", "B")],
                get_db(), seed=seed)


def raw_cost(power_id: str) -> int:
    """power 金币费（batch 口径: raw 缺 cost 键 = 0）。"""
    d = get_db().get(power_id)
    return d.raw.get("cost", 0)


def power_id_of(hero: Hero) -> str:
    d = get_db().get(hero.card_id)
    return d.hero_power_id


def board_minion(game: Game, hero: Hero, card_id: str,
                 buff: tuple[int, int] | None = None) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    game.summon(hero, m)
    if buff is not None:
        m.add_buff(entity.Buff(atk=buff[0], health=buff[1]))
    return m


def tavern_minion(game: Game, hero: Hero, card_id: str) -> Minion:
    game.minion_pool.acquire(card_id)
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def choose(game: Game, kind: str, index: int = 0):
    choice = game.pending_choices.pop(0)
    assert choice.kind == kind, f"expect {kind}, got {choice.kind}"
    pick = choice.options[index]
    choice.choose(index)
    return pick


class TestRegistryState(unittest.TestCase):
    """批次注册面: 22 技能 + 10 Rat King 变体全部在册。"""

    def test_all_powers_registered(self):
        for pid in ("TB_BaconShop_HP_064", "TB_BaconShop_HP_015",
                    "BG23_HERO_306p", "TB_BaconShop_HP_022",
                    "TB_BaconShop_HP_039t", "TB_BaconShop_HP_702t",
                    "BG25_HERO_105p", "TB_BaconShop_HP_047",
                    "BG23_HERO_305p", "BG31_HERO_003p", "BG28_HERO_400p",
                    "TB_BaconShop_HP_076", "TB_BaconShop_HP_046",
                    "BG31_HERO_005p", "TB_BaconShop_HP_077",
                    "TB_BaconShop_HP_041", "BG20_HERO_201p",
                    "BG21_HERO_010p", "BG20_HERO_301p", "BG21_HERO_020p",
                    "TB_BaconShop_HP_081", "BG23_HERO_303p2"):
            self.assertIn(pid, REGISTRY)
        for vid in KING_VARIANT_IDS:
            self.assertIn(vid, REGISTRY)


class TestAlexstrasza(unittest.TestCase):
    """TB_BaconShop_HP_064 — tier 4 门槛解锁 Discover a Dragon。"""

    def test_below_tier4_rejected(self):
        game = make_game("TB_BaconShop_HERO_56")
        a = game.heroes[0]
        a.gold = 10
        a.set(GameTag.TAVERN_TIER, 3)
        self.assertFalse(game.use_hero_power(a))
        self.assertEqual(a.gold, 10)

    def test_tier4_discovers_dragon_from_pool(self):
        game = make_game("TB_BaconShop_HERO_56")
        a = game.heroes[0]
        a.gold = 10
        a.set(GameTag.TAVERN_TIER, 4)
        self.assertTrue(game.use_hero_power(a))
        choice = game.pending_choices[0]
        self.assertEqual(choice.kind, "discover_minion")
        d = get_db().get(choice.options[0])
        self.assertIn(d.race, (Race.DRAGON, Race.ALL))
        avail = game.minion_pool.available(choice.options[0])
        pick = choose(game, "discover_minion")
        self.assertEqual(a.gold, 10 - raw_cost("TB_BaconShop_HP_064"))
        self.assertIn(pick, [m.card_id for m in a.hand
                             if isinstance(m, Minion)])
        self.assertEqual(game.minion_pool.available(pick), avail - 1)


class TestMillificent(unittest.TestCase):
    """TB_BaconShop_HP_015 — tier 4 门槛解锁 Discover Magnetic Mech。"""

    def test_below_tier4_rejected(self):
        game = make_game("TB_BaconShop_HERO_17")
        a = game.heroes[0]
        a.gold = 10
        self.assertFalse(game.use_hero_power(a))

    def test_tier4_candidates_all_magnetic_mechs(self):
        game = make_game("TB_BaconShop_HERO_17")
        a = game.heroes[0]
        a.gold = 10
        a.set(GameTag.TAVERN_TIER, 4)
        self.assertTrue(game.use_hero_power(a))
        choice = game.pending_choices[0]
        self.assertTrue(choice.options)
        for oid in choice.options:
            self.assertIn(oid, MAGNETIC_MECHS)


class TestSylvanas(unittest.TestCase):
    """BG23_HERO_306p — turn 3 门槛 + 双方死亡集 plain copy。"""

    def _combat_with_deaths(self, game):
        a = game.heroes[0]
        b = game.heroes[1]
        board_minion(game, a, PLAIN_T1, buff=(9, 9))    # 10/10 击杀者
        board_minion(game, a, PLAIN_T1)                  # 炮灰（亦战死）
        for _ in range(2):
            board_minion(game, b, UNDEAD_T2)             # 敌方死者
        return game.run_combat(a, b)

    def test_turn3_gate_and_enemy_deaths_offered(self):
        game = make_game("BG23_HERO_306")
        a = game.heroes[0]
        a.gold = 10
        from hsrl2.scripts.batches.batch_hero_actives2 import SylvanasScript
        SylvanasScript.on_bind(a, game)             # 战斗前接线（start_game 语义）
        result = self._combat_with_deaths(game)
        game.events.fire(game, "combat_end", hero_a=a,
                         hero_b=game.heroes[1], result=result)
        game.turn = 2
        self.assertFalse(game.use_hero_power(a))
        game.turn = 3
        self.assertTrue(game.use_hero_power(a))
        choice = game.pending_choices[0]
        # 敌方 UNDEAD_T2 死亡入选项——证伪"仅友方死亡"口径
        self.assertIn((UNDEAD_T2, False), choice.options)
        avail = game.minion_pool.available(UNDEAD_T2)
        idx = choice.options.index((UNDEAD_T2, False))
        pick = choose(game, "discover_minion", index=idx)
        card_id, golden = pick
        self.assertEqual(a.gold, 10 - raw_cost("BG23_HERO_306p"))
        copies = [m for m in a.hand if isinstance(m, Minion)]
        self.assertEqual(copies[0].card_id, card_id)
        d = get_db().get(card_id)
        self.assertEqual((copies[0].atk, copies[0].max_health),
                         (d.atk, d.health))          # plain = 无 buff
        self.assertFalse(copies[0].is_golden)
        self.assertEqual(game.minion_pool.available(UNDEAD_T2), avail)

    def test_full_hand_gate(self):
        game = make_game("BG23_HERO_306")
        a = game.heroes[0]
        a.gold = 10
        self._combat_with_deaths(game)
        game.turn = 3
        while not a.hand_full():
            a.add_to_hand(game.create_minion(PLAIN_T1, controller=a))
        self.assertFalse(game.use_hero_power(a))     # 34.4.0 bugfix

    def test_no_deaths_recorded_unusable(self):
        game = make_game("BG23_HERO_306")
        a = game.heroes[0]
        a.gold = 10
        game.turn = 5
        self.assertFalse(game.use_hero_power(a))


class TestShudderwock(unittest.TestCase):
    """TB_BaconShop_HP_022 — turn 3 门槛 + TriggerBattlecry + cost 0。"""

    def test_turn3_gate(self):
        game = make_game("TB_BaconShop_HERO_23")
        a = game.heroes[0]
        a.gold = 10
        board_minion(game, a, COINER)
        game.turn = 2
        self.assertFalse(game.use_hero_power(a))

    def test_triggers_battlecry_free(self):
        game = make_game("TB_BaconShop_HERO_23")
        a = game.heroes[0]
        a.gold = 10
        game.turn = 3
        board_minion(game, a, COINER)
        self.assertTrue(game.use_hero_power(a))
        choose(game, "hero_power_target")
        coins = [s for s in a.hand
                 if isinstance(s, Spell) and s.card_id == TAVERN_COIN]
        self.assertEqual(len(coins), 1)              # Shell Collector 战吼
        self.assertEqual(a.gold, 10)                 # cost=0（raw 无 cost 键）


class TestYogg(unittest.TestCase):
    """TB_BaconShop_HP_039t — 被动: turn 3 起每回合施放随机池法术。"""

    def test_passive_not_clickable(self):
        game = make_game("TB_BaconShop_HERO_35")
        a = game.heroes[0]
        game.turn = 5
        self.assertFalse(game.use_hero_power(a))

    def test_unlocked_at_turn3_casts_direct(self):
        game = make_game("TB_BaconShop_HERO_35")
        a = game.heroes[0]
        from hsrl2.scripts.batches.batch_hero_actives2 import YoggScript
        YoggScript.on_bind(a, game)
        m = board_minion(game, a, PLAIN_T1)
        base = (m.atk, m.max_health)
        game.spell_pool._available = Counter({SHINY_RING: 1})
        game.turn = 2
        game.events.fire(game, "turn_start", turn=2, hero=a)
        self.assertEqual((m.atk, m.max_health), base)   # 未解锁不施放
        game.turn = 3
        game.events.fire(game, "turn_start", turn=3, hero=a)
        d = get_db().get(SHINY_RING)
        self.assertEqual((m.atk, m.max_health),
                         (base[0] + d.num(0), base[1] + d.num(1)))
        # 直施: 不计酒馆法术施放数、池净零（acquire→release）
        self.assertEqual(
            a.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0), 0)
        self.assertEqual(game.spell_pool.available(SHINY_RING), 1)

    def test_unregistered_spells_excluded(self):
        game = make_game("TB_BaconShop_HERO_35")
        a = game.heroes[0]
        from hsrl2.scripts.batches.batch_hero_actives2 import YoggScript
        YoggScript.on_bind(a, game)
        m = board_minion(game, a, PLAIN_T1)
        base = (m.atk, m.max_health)
        game.spell_pool._available = Counter({"BG31_242": 5})  # Duos 未注册
        game.turn = 3
        game.events.fire(game, "turn_start", turn=3, hero=a)
        self.assertEqual((m.atk, m.max_health), base)


class TestJailer(unittest.TestCase):
    """TB_BaconShop_HP_702t — tier 2 门槛 + Destroy + 随机 Undead。"""

    def test_tier1_rejected(self):
        game = make_game("TB_BaconShop_HERO_702")
        a = game.heroes[0]
        a.gold = 10
        board_minion(game, a, UNDEAD_T2)
        self.assertFalse(game.use_hero_power(a))     # 34.6.2 bugfix 语义
        self.assertEqual(a.gold, 10)

    def test_destroy_and_random_undead(self):
        game = make_game("TB_BaconShop_HERO_702")
        a = game.heroes[0]
        a.gold = 10
        a.set(GameTag.TAVERN_TIER, 2)
        undead = board_minion(game, a, UNDEAD_T2)
        avail_undead = sum(
            game.minion_pool.available(d.id)
            for d in game.db.pool_minions()
            if d.race in (Race.UNDEAD, Race.ALL))
        self.assertTrue(game.use_hero_power(a))
        pick = choose(game, "hero_power_target")
        self.assertIs(pick, undead)
        self.assertNotIn(undead, a.board)            # Destroy 离场
        self.assertEqual(a.board, [])
        got = [m for m in a.hand if isinstance(m, Minion)]
        self.assertEqual(len(got), 1)
        self.assertIn(got[0].race, (Race.UNDEAD, Race.ALL))
        self.assertEqual(a.gold, 10 - raw_cost("TB_BaconShop_HP_702t"))
        after_undead = sum(
            game.minion_pool.available(d.id)
            for d in game.db.pool_minions()
            if d.race in (Race.UNDEAD, Race.ALL))
        # 被毁 UNDEAD_T2 回池 +1、随机获取 -1
        self.assertEqual(after_undead, avail_undead)

    def test_no_undead_unusable(self):
        game = make_game("TB_BaconShop_HERO_702")
        a = game.heroes[0]
        a.gold = 10
        a.set(GameTag.TAVERN_TIER, 2)
        board_minion(game, a, COINER)               # Murloc——非 Undead
        self.assertFalse(game.use_hero_power(a))


class TestETC(unittest.TestCase):
    """BG25_HERO_105p — tier 2 门槛 + Discover a Buddy（不占池）。"""

    def test_tier1_rejected(self):
        game = make_game("BG25_HERO_105")
        a = game.heroes[0]
        a.gold = 10
        self.assertFalse(game.use_hero_power(a))

    def test_discovers_buddy_without_pool(self):
        game = make_game("BG25_HERO_105")
        a = game.heroes[0]
        a.gold = 10
        a.set(GameTag.TAVERN_TIER, 2)
        before = game.minion_pool.total_remaining()
        self.assertTrue(game.use_hero_power(a))
        choice = game.pending_choices[0]
        self.assertTrue(all(oid.endswith("_Buddy")
                            for oid in choice.options))
        pick = choose(game, "discover_minion")
        self.assertIn(pick, [m.card_id for m in a.hand
                             if isinstance(m, Minion)])
        self.assertEqual(game.minion_pool.total_remaining(), before)
        self.assertEqual(a.gold, 10 - raw_cost("BG25_HERO_105p"))


class TestElise(unittest.TestCase):
    """TB_BaconShop_HP_047 — 恰好本 tier 发现 + 每用 +1 费。"""

    def test_cost_curve_and_exact_tier(self):
        game = make_game("TB_BaconShop_HERO_42")
        a = game.heroes[0]
        a.gold = 20
        a.set(GameTag.TAVERN_TIER, 2)
        base = raw_cost("TB_BaconShop_HP_047")
        game.turn = 1
        self.assertTrue(game.use_hero_power(a))
        choice = game.pending_choices[0]
        self.assertTrue(all(get_db().get(oid).tech_level == 2
                            for oid in choice.options))
        choose(game, "discover_minion")
        self.assertEqual(a.gold, 20 - (base + 0))
        a.clear(GameTag.HERO_POWER_USED_THIS_TURN)
        game.turn = 2
        self.assertTrue(game.use_hero_power(a))
        choose(game, "discover_minion")
        self.assertEqual(a.gold, 20 - (base + 0) - (base + 1))
        a.clear(GameTag.HERO_POWER_USED_THIS_TURN)
        game.turn = 3
        self.assertTrue(game.use_hero_power(a))
        choose(game, "discover_minion")
        self.assertEqual(a.gold, 20 - (base + 0) - (base + 1) - (base + 2))


class TestTogwaggle(unittest.TestCase):
    """BG23_HERO_305p — 24.0 Dev Comment 费用曲线 + Steal all cards。"""

    def _script_cost(self, game):
        from hsrl2.scripts.batches.batch_hero_actives2 import \
            TogwaggleScript
        hero = game.heroes[0]
        d = game.hero_power_def(hero)
        return game.hero_power_cost(hero, d, TogwaggleScript)

    def test_cost_curve_and_reset_on_use(self):
        game = make_game("BG23_HERO_305")
        a = game.heroes[0]
        base = raw_cost("BG23_HERO_305p")
        game.turn = 1
        self.assertEqual(self._script_cost(game), base)
        game.turn = 5
        self.assertEqual(self._script_cost(game), base - 4)
        a.gold = 20
        tavern_minion(game, a, PLAIN_T1)
        tavern_minion(game, a, UNDEAD_T2)
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(a.gold, 20 - (base - 4))
        self.assertEqual(a.tavern, [])               # Steal all cards
        stolen = [e for e in a.hand]
        self.assertEqual({e.card_id for e in stolen},
                         {PLAIN_T1, UNDEAD_T2})
        game.turn = 6
        self.assertEqual(self._script_cost(game), base - 1)   # 重置后周期

    def test_cost_floor_zero(self):
        game = make_game("BG23_HERO_305")
        game.turn = 30
        self.assertEqual(self._script_cost(game), 0)


class TestNobundo(unittest.TestCase):
    """BG31_HERO_003p — last tavern spell 副本 + 同款费用曲线。"""

    def _bind(self, game):
        from hsrl2.scripts.batches.batch_hero_actives2 import NobundoScript
        NobundoScript.on_bind(game.heroes[0], game)

    def test_unusable_before_any_cast(self):
        game = make_game("BG31_HERO_003")
        a = game.heroes[0]
        a.gold = 10
        game.turn = 4
        self._bind(game)
        self.assertFalse(game.use_hero_power(a))

    def test_cost_curve_copy_and_reset(self):
        game = make_game("BG31_HERO_003")
        a = game.heroes[0]
        self._bind(game)
        base = raw_cost("BG31_HERO_003p")
        game.turn = 1
        from hsrl2.scripts.batches.batch_hero_actives2 import NobundoScript
        d0 = game.hero_power_def(a)
        self.assertEqual(game.hero_power_cost(a, d0, NobundoScript), base)
        game.turn = 4
        self.assertEqual(game.hero_power_cost(a, d0, NobundoScript), 0)
        # 施放一个池法术（占池→施放回池）
        game.spell_pool.acquire(SHINY_RING)
        s = game.create_spell(SHINY_RING, controller=a)
        a.add_to_hand(s)
        board_minion(game, a, PLAIN_T1)
        self.assertTrue(game.play_spell(a, s))
        self.assertEqual(a._last_tavern_spell_id, SHINY_RING)
        avail = game.spell_pool.available(SHINY_RING)
        a.gold = 10
        self.assertTrue(game.use_hero_power(a))
        copies = [x for x in a.hand if isinstance(x, Spell)]
        self.assertEqual([x.card_id for x in copies], [SHINY_RING])
        self.assertEqual(a.gold, 10 - 0)             # turn 4 费用曲线到 0
        self.assertEqual(game.spell_pool.available(SHINY_RING),
                         avail - 1)                  # Get a copy 占池
        game.turn = 5
        self.assertEqual(game.hero_power_cost(a, d0, NobundoScript),
                         base - 1)                   # 使用后重置周期


class TestSnakeEyes(unittest.TestCase):
    """BG28_HERO_400p — d6 得金 + N 回合冷却（掷 1 下回合解锁）。"""

    def test_roll_gain_and_cooldown_window(self):
        game = make_game("BG28_HERO_400", seed=7)
        a = game.heroes[0]
        a.gold = 10
        game.turn = 5
        self.assertTrue(game.use_hero_power(a))
        roll = a._lucky_roll_unlock - game.turn
        self.assertIn(roll, (1, 2, 3, 4, 5, 6))
        self.assertEqual(a.gold, 10 - raw_cost("BG28_HERO_400p") + roll)
        game.turn = a._lucky_roll_unlock - 1
        self.assertFalse(game.use_hero_power(a))     # 冷却窗口内
        a.clear(GameTag.HERO_POWER_USED_THIS_TURN)
        game.turn = a._lucky_roll_unlock
        self.assertTrue(game.use_hero_power(a))      # T+N 解锁

    def test_roll1_unlocks_next_turn(self):
        game = make_game("BG28_HERO_400")
        a = game.heroes[0]
        a.gold = 10
        game.turn = 2
        a._lucky_roll_unlock = 3                     # 掷 1 → T+1 解锁
        self.assertFalse(game.use_hero_power(a))
        game.turn = 3
        self.assertTrue(game.use_hero_power(a))      # 35.0.0 bugfix 语义


class TestKragg(unittest.TestCase):
    """TB_BaconShop_HP_076 — once per game + 金额 = num(0)+(turn-1) + cost 0。"""

    def test_amount_curve_once_per_game_free(self):
        game = make_game("TB_BaconShop_HERO_68")
        a = game.heroes[0]
        a.gold = 5
        game.turn = 5
        d = get_db().get("TB_BaconShop_HP_076")
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(a.gold, 5 + d.num(0) + 4)   # cost=0 只增不减
        a.clear(GameTag.HERO_POWER_USED_THIS_TURN)
        game.turn = 9
        self.assertFalse(game.use_hero_power(a))     # 每局一次
        self.assertEqual(a.gold, 5 + d.num(0) + 4)


class TestReno(unittest.TestCase):
    """TB_BaconShop_HP_046 — once per game 金色化（Sanders 同构）。"""

    def test_goldenize_keeps_buffs_no_triple_reward(self):
        game = make_game("TB_BaconShop_HERO_41")
        a = game.heroes[0]
        a.gold = 10
        m = board_minion(game, a, PLAIN_T1, buff=(3, 4))
        base_def = get_db().get(PLAIN_T1)
        golden_def = get_db().golden_version(base_def)
        self.assertTrue(game.use_hero_power(a))
        pick = choose(game, "hero_power_target")
        self.assertIs(pick, m)
        new = a.board[0]
        self.assertEqual(new.card_id, golden_def.id)   # 金色=独立卡定义
        self.assertTrue(new.is_golden)
        self.assertTrue(new.has(GameTag.GOLDEN))
        self.assertTrue(new.has(GameTag.GILDED_NOT_TRIPLED))
        self.assertFalse(new.has(GameTag.TRIPLE_REWARD_PENDING))
        self.assertEqual((new.atk, new.max_health),
                         (golden_def.atk + 3, golden_def.health + 4))
        self.assertEqual(a.gold, 10)                 # cost=0

    def test_once_per_game_and_golden_excluded(self):
        game = make_game("TB_BaconShop_HERO_41")
        a = game.heroes[0]
        a.gold = 10
        plain = board_minion(game, a, PLAIN_T1)
        golden = game.create_minion(PLAIN_T1, controller=a, golden=True)
        game.summon(a, golden)
        self.assertTrue(game.use_hero_power(a))
        choice = game.pending_choices[0]
        self.assertEqual(choice.options, [plain])    # 金色不在候选
        choose(game, "hero_power_target")
        a.clear(GameTag.HERO_POWER_USED_THIS_TURN)
        self.assertFalse(game.use_hero_power(a))     # 每局一次


class TestZerek(unittest.TestCase):
    """BG31_HERO_005p — once per game 召唤 exact copy。"""

    def test_summons_exact_copy_with_buffs(self):
        game = make_game("BG31_HERO_005")
        a = game.heroes[0]
        a.gold = 10
        m = board_minion(game, a, PLAIN_T1, buff=(2, 3))
        self.assertTrue(game.use_hero_power(a))
        choose(game, "hero_power_target")
        self.assertEqual(len(a.board), 2)
        copy = a.board[-1]
        self.assertEqual(copy.card_id, PLAIN_T1)
        d = get_db().get(PLAIN_T1)
        self.assertEqual((copy.atk, copy.max_health),
                         (d.atk + 2, d.health + 3))  # exact = 含 buff
        self.assertEqual(a.gold, 10 - raw_cost("BG31_HERO_005p"))
        a.clear(GameTag.HERO_POWER_USED_THIS_TURN)
        self.assertFalse(game.use_hero_power(a))     # 每局一次

    def test_full_board_unusable(self):
        game = make_game("BG31_HERO_005")
        a = game.heroes[0]
        a.gold = 10
        while not a.board_full():
            board_minion(game, a, PLAIN_T1)
        self.assertFalse(game.use_hero_power(a))


class TestTess(unittest.TestCase):
    """TB_BaconShop_HP_077 — 上对手战前板 plain copy 刷新酒馆。"""

    def test_no_snapshot_rejected(self):
        game = make_game("TB_BaconShop_HERO_50")
        a = game.heroes[0]
        a.gold = 10
        self.assertFalse(game.use_hero_power(a))     # 27.0 bugfix 语义
        self.assertEqual(a.gold, 10)

    def test_refresh_with_plain_copies(self):
        game = make_game("TB_BaconShop_HERO_50")
        a = game.heroes[0]
        b = game.heroes[1]
        a.gold = 10
        old = tavern_minion(game, a, PLAIN_T1)
        avail_old = game.minion_pool.available(PLAIN_T1)
        enemy = board_minion(game, b, UNDEAD_T2, buff=(5, 5))
        avail_enemy = game.minion_pool.available(UNDEAD_T2)
        game._next_opponent_snapshot = {a: list(b.board)}
        self.assertTrue(game.use_hero_power(a))
        self.assertEqual(len(a.tavern), 1)           # 馆内 = 快照副本
        copy = a.tavern[0]
        self.assertEqual(copy.card_id, UNDEAD_T2)
        d = get_db().get(UNDEAD_T2)
        self.assertEqual((copy.atk, copy.max_health),
                         (d.atk, d.health))          # plain 无 buff
        self.assertEqual(game.minion_pool.available(PLAIN_T1),
                         avail_old + 1)              # 旧内容回池
        self.assertEqual(game.minion_pool.available(UNDEAD_T2),
                         avail_enemy)                # 副本不占池
        self.assertEqual(a.gold, 10 - raw_cost("TB_BaconShop_HP_077"))


class TestRatKing(unittest.TestCase):
    """TB_BaconShop_HP_041 — 随机轮换（不连庄/限 active_races）+ 变体可用。"""

    def _bind(self, game):
        from hsrl2.scripts.batches.batch_hero_actives2 import RatKingScript
        RatKingScript.on_bind(game.heroes[0], game)

    def test_on_bind_activates_variant_and_rotates(self):
        game = make_game("TB_BaconShop_HERO_12", seed=3)
        a = game.heroes[0]
        self._bind(game)
        prev = a._active_power_id
        self.assertIn(prev, KING_VARIANT_IDS)
        for _ in range(30):                          # 轮换不连庄
            game.events.fire(game, "turn_start",
                             turn=game.turn + 1, hero=a)
            current = a._active_power_id
            self.assertNotEqual(current, prev)       # "twice in a row" 禁
            self.assertIn(current, KING_VARIANT_IDS)
            prev = current

    def test_rotation_respects_active_races(self):
        game = make_game("TB_BaconShop_HERO_12", seed=5)
        a = game.heroes[0]
        game.minion_pool.active_races = {Race.MECH, Race.BEAST}
        self._bind(game)
        allowed = {"TB_BaconShop_HP_041a", "TB_BaconShop_HP_041b"}
        for _ in range(20):
            self.assertIn(a._active_power_id, allowed)
            game.events.fire(game, "turn_start",
                             turn=game.turn + 1, hero=a)

    def test_variant_power_discovers_its_race(self):
        game = make_game("TB_BaconShop_HERO_12", seed=11)
        a = game.heroes[0]
        a.gold = 10
        self._bind(game)
        self.assertTrue(game.use_hero_power(a))
        choice = game.pending_choices[0]
        self.assertEqual(choice.kind, "discover_minion")
        variant_race = get_db().get(a._active_power_id)
        # 变体文本 "King of X"——按 id 后缀映射种族断言
        suffix_race = {
            "a": Race.BEAST, "b": Race.MECH, "c": Race.MURLOC,
            "d": Race.DEMON, "f": Race.DRAGON, "g": Race.PIRATE,
            "h": Race.ELEMENTAL, "i": Race.QUILBOAR, "j": Race.NAGA,
            "k": Race.UNDEAD}
        race = suffix_race[a._active_power_id[-1]]
        for oid in choice.options:
            self.assertIn(get_db().get(oid).race,
                          (race, Race.ALL))
        choose(game, "discover_minion")
        self.assertEqual(a.gold, 10 - raw_cost(a._active_power_id))


class TestVoljin(unittest.TestCase):
    """BG20_HERO_201p — 双目标链互得攻击，下一回合开始回退。"""

    def test_two_target_chain_swap_and_expiry(self):
        game = make_game("BG20_HERO_201")
        a = game.heroes[0]
        a.gold = 10
        d = get_db().get(PLAIN_T1)
        m1 = board_minion(game, a, PLAIN_T1, buff=(2, 0))    # atk+2
        m2 = board_minion(game, a, PLAIN_T1, buff=(5, 0))    # atk+5
        a1, a2 = m1.atk, m2.atk
        self.assertTrue(game.use_hero_power(a))
        p1 = choose(game, "hero_power_target", index=0)
        self.assertEqual(len(game.pending_choices), 1)  # 第二个 PendingChoice
        p2 = choose(game, "hero_power_target", index=0)
        self.assertEqual((p1, p2), (m1, m2))
        self.assertEqual((m1.atk, m2.atk), (a1 + a2, a2 + a1))
        self.assertEqual(a.gold, 10)                 # cost=0
        game.events.fire(game, "turn_start", turn=2, hero=a)
        self.assertEqual((m1.atk, m2.atk), (a1, a2))  # until next turn 回退

    def test_single_minion_rejected(self):
        game = make_game("BG20_HERO_201")
        a = game.heroes[0]
        a.gold = 10
        board_minion(game, a, PLAIN_T1)
        self.assertFalse(game.use_hero_power(a))     # 候选 <2
        self.assertEqual(a.gold, 10)


class TestScabbs(unittest.TestCase):
    """BG21_HERO_010p — 下对手战前板 plain copy 三选一（不占池）。"""

    def test_no_snapshot_rejected(self):
        game = make_game("BG21_HERO_010")
        a = game.heroes[0]
        a.gold = 10
        self.assertFalse(game.use_hero_power(a))

    def test_discover_plain_copy_from_warband(self):
        game = make_game("BG21_HERO_010")
        a = game.heroes[0]
        b = game.heroes[1]
        a.gold = 10
        board_minion(game, b, UNDEAD_T2, buff=(7, 7))
        golden = game.create_minion(PLAIN_T1, controller=b, golden=True)
        game.summon(b, golden)
        game._next_opponent_snapshot = {a: list(b.board)}
        avail_u = game.minion_pool.available(UNDEAD_T2)
        avail_p = game.minion_pool.available(PLAIN_T1)
        golden_pair = (golden.card_id, True)         # 金色实体 card_id = 金色卡定义
        self.assertTrue(game.use_hero_power(a))
        choice = game.pending_choices[0]
        self.assertEqual(sorted(map(str, choice.options)),
                         sorted(str(x) for x in
                                [(UNDEAD_T2, False), golden_pair]))
        pick = choose(game, "discover_minion")
        card_id, golden_flag = pick
        got = [m for m in a.hand if isinstance(m, Minion)]
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].card_id, card_id)
        self.assertEqual(got[0].is_golden, golden_flag)   # 金色源→金色
        d = get_db().get(card_id)
        self.assertEqual((got[0].atk, got[0].max_health),
                         (d.atk, d.health))           # plain 无 buff
        self.assertEqual(game.minion_pool.available(UNDEAD_T2), avail_u)
        self.assertEqual(game.minion_pool.available(PLAIN_T1), avail_p)
        self.assertEqual(a.gold, 10 - raw_cost("BG21_HERO_010p"))


class TestMutanus(unittest.TestCase):
    """BG20_HERO_301p — Sell + 随机溅射 +X/+Y（wiki Notes）。"""

    def test_sell_and_spit_add_stats(self):
        game = make_game("BG20_HERO_301")
        a = game.heroes[0]
        a.gold = 10
        victim = board_minion(game, a, PLAIN_T1, buff=(3, 4))
        receiver = board_minion(game, a, UNDEAD_T2)
        r_atk, r_hp = receiver.atk, receiver.max_health
        v_atk, v_hp = victim.atk, victim.health    # Spit = 被吃者全部数值
        avail = game.minion_pool.available(PLAIN_T1)
        self.assertTrue(game.use_hero_power(a))
        pick = choose(game, "hero_power_target")
        self.assertIs(pick, victim)
        self.assertNotIn(victim, a.board)
        self.assertEqual(a.gold, 10 + 1)             # cost=0 + 出售 +1 金
        self.assertEqual(game.minion_pool.available(PLAIN_T1),
                         avail + 1)                  # 出售回池
        self.assertEqual((receiver.atk, receiver.max_health),
                         (r_atk + v_atk, r_hp + v_hp))   # Spit = add X/Y

    def test_alone_stats_lost_but_sell_holds(self):
        game = make_game("BG20_HERO_301")
        a = game.heroes[0]
        a.gold = 10
        only = board_minion(game, a, PLAIN_T1)
        self.assertTrue(game.use_hero_power(a))
        choose(game, "hero_power_target")
        self.assertEqual(a.board, [])
        self.assertEqual(a.gold, 11)


class TestCookie(unittest.TestCase):
    """BG21_HERO_020p — 投锅 Remove + 集 3 类型 Discover + 锅清空。"""

    def test_pot_gather_then_discover_types(self):
        game = make_game("BG21_HERO_020")
        a = game.heroes[0]
        a.gold = 10
        d = get_db().get("BG21_HERO_020p")
        victims = []
        for cid in (PLAIN_T1, UNDEAD_T2, COINER):
            victims.append(board_minion(game, a, cid))
        avail_p = game.minion_pool.available(PLAIN_T1)
        for i in range(d.num(0) - 1):
            self.assertTrue(game.use_hero_power(a))
            choose(game, "hero_power_target")
            self.assertEqual(len(a.board), len(victims) - (i + 1))
            self.assertEqual(game.minion_pool.available(PLAIN_T1),
                             avail_p)                # Remove 不回池
            self.assertEqual(a.gold, 10)             # cost=0
            self.assertEqual(a._cookie_pot, [v.race for v in
                                             victims[:i + 1]])
            a.clear(GameTag.HERO_POWER_USED_THIS_TURN)   # 跨回合投锅
        self.assertEqual(len(game.pending_choices), 0)   # 未满 3 不发现
        self.assertTrue(game.use_hero_power(a))      # 第 3 投触发
        choose(game, "hero_power_target")
        choice = game.pending_choices[0]
        thrown_races = {v.race for v in victims} | {Race.ALL}
        for oid in choice.options:
            self.assertIn(get_db().get(oid).race, thrown_races)
        self.assertEqual(a._cookie_pot, [])          # 锅清空循环


class TestBarov(unittest.TestCase):
    """TB_BaconShop_HP_081 — 下场战斗胜方竞猜，猜对 3 Tavern Coin。"""

    def _wager(self, game, a, option_index):
        a.gold = 10
        self.assertTrue(game.use_hero_power(a))
        choice = game.pending_choices[0]
        self.assertEqual(choice.kind, "friendly_wager")
        self.assertEqual(choice.options, ["me", "opponent"])
        choose(game, "friendly_wager", index=option_index)

    def test_guess_self_win_pays_3_coins(self):
        game = make_game("TB_BaconShop_HERO_72")
        a, b = game.heroes
        self._wager(game, a, 0)
        board_minion(game, a, PLAIN_T1, buff=(9, 9))
        board_minion(game, b, PLAIN_T1)
        result = game.run_combat(a, b)
        game.events.fire(game, "combat_end", hero_a=a, hero_b=b,
                         result=result)
        coins = [s for s in a.hand
                 if isinstance(s, Spell) and s.card_id == TAVERN_COIN]
        self.assertEqual(len(coins), 3)
        self.assertEqual(a.gold, 10 - raw_cost("TB_BaconShop_HP_081"))

    def test_guess_self_loss_pays_nothing(self):
        game = make_game("TB_BaconShop_HERO_72")
        a, b = game.heroes
        self._wager(game, a, 0)
        board_minion(game, b, PLAIN_T1, buff=(9, 9))
        board_minion(game, a, PLAIN_T1)
        result = game.run_combat(a, b)
        game.events.fire(game, "combat_end", hero_a=a, hero_b=b,
                         result=result)
        self.assertEqual([s for s in a.hand
                          if isinstance(s, Spell)], [])

    def test_draw_pays_nothing(self):
        game = make_game("TB_BaconShop_HERO_72")
        a, b = game.heroes
        self._wager(game, a, 0)
        result = game.run_combat(a, b)               # 双空板 = 平局
        game.events.fire(game, "combat_end", hero_a=a, hero_b=b,
                         result=result)
        self.assertEqual([s for s in a.hand
                          if isinstance(s, Spell)], [])


class TestMurlocHolmes(unittest.TestCase):
    """BG23_HERO_303p2 — 二选一小游戏，猜对 1 Tavern Coin。"""

    def _setup(self):
        game = make_game("BG23_HERO_303")
        a, b = game.heroes
        a.gold = 10
        board_minion(game, b, UNDEAD_T2)
        game._next_opponent_snapshot = {a: list(b.board)}
        return game, a

    def test_no_snapshot_rejected(self):
        game = make_game("BG23_HERO_303")
        a = game.heroes[0]
        a.gold = 10
        self.assertFalse(game.use_hero_power(a))

    def test_correct_guess_pays_one_coin(self):
        game, a = self._setup()
        self.assertTrue(game.use_hero_power(a))
        choice = game.pending_choices[0]
        self.assertEqual(choice.kind, "holmes_guess")
        self.assertEqual(len(choice.options), 2)     # 恰一真一假
        self.assertIn((UNDEAD_T2, False), choice.options)
        real_index = choice.options.index((UNDEAD_T2, False))
        choose(game, "holmes_guess", index=real_index)
        coins = [s for s in a.hand
                 if isinstance(s, Spell) and s.card_id == TAVERN_COIN]
        self.assertEqual(len(coins), 1)
        self.assertEqual(a.gold, 10 - raw_cost("BG23_HERO_303p2"))

    def test_wrong_guess_pays_nothing(self):
        game, a = self._setup()
        self.assertTrue(game.use_hero_power(a))
        choice = game.pending_choices[0]
        real_index = choice.options.index((UNDEAD_T2, False))
        wrong = 1 - real_index
        choose(game, "holmes_guess", index=wrong)
        self.assertEqual([s for s in a.hand
                          if isinstance(s, Spell)], [])


if __name__ == "__main__":
    unittest.main()
