"""final_unfreeze 尾批语义测试（作业单 2026-08-23，3 张解冻卡 + 核实组）。

驱动约定（TEST_SOP / test_batch_unfreeze 同款）:
  - Wildfire: CombatScheduler(game,a,b)._execute_attack 单次攻击驱动，
    after_attack 在死亡结算后触发（excess 引擎携带）
  - Magicfin: buy_from_tavern 走真实购买路径（spell_bought 契约）
  - 数值期望一律 CardDef.num() / 引擎视图计算; 字面量处注明
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.combat import CombatScheduler
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

WILDFIRE = "BGS_126"
WILDFIRE_GOLDEN = "TB_BaconUps_166"      # db.golden_version 链（数据核实）
MYCOLOGIST = "BG33_891"
APPRENTICE = "BG33_890t"                 # wiki Related cards 权威 token
SHINY_RING = "BG28_168"                  # 非定向: 全体 +num(0)/+num(1)
SACRED_GIFT = "BG28_507"                 # 定向: Give a minion Divine Shield

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


def attack(game: Game, attacker: Minion, defender: Minion) -> None:
    a, b = game.heroes[0], game.heroes[1]
    CombatScheduler(game, a, b)._execute_attack(attacker, defender)


def stock_spell(game: Game, hero: Hero, card_id: str) -> Spell:
    """往 hero 酒馆展示区放一张池法术（test_batch_activate 同款）。"""
    assert game.spell_pool.acquire(card_id), f"spell pool empty: {card_id}"
    s = game.create_spell(card_id, controller=hero)
    s.zone = Zone.TAVERN
    hero.tavern.append(s)
    return s


def stock_minion(game: Game, hero: Hero, card_id: str) -> Minion:
    assert game.minion_pool.acquire(card_id), f"pool empty: {card_id}"
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


class TestRegistryState(unittest.TestCase):
    """批次注册面: 5 id 注册; 核实组 7 id 明确不注册（引擎数据通道）。"""

    REGISTERED = (WILDFIRE, WILDFIRE_GOLDEN, MYCOLOGIST,
                  "BG33_891_G", APPRENTICE)
    UNREGISTERED = ("BG_DEEP_015", "BG_DEEP_015_G", "BG25_001",
                    "BG_BOT_911", "BGS_119", "BGS_131", "BG26_175")

    def test_registered(self):
        for cid in self.REGISTERED:
            self.assertIn(cid, REGISTRY, f"{cid} should be registered")

    def test_unregistered_by_design(self):
        for cid in self.UNREGISTERED:
            self.assertNotIn(cid, REGISTRY,
                             f"{cid} is engine/data-channel only")

    def test_golden_link(self):
        db = get_db()
        self.assertEqual(db.golden_version(db.get(WILDFIRE)).id,
                         WILDFIRE_GOLDEN)
        self.assertEqual(db.golden_version(db.get(MYCOLOGIST)).id,
                         "BG33_891_G")

    def test_param_mapping_matches_data(self):
        db = get_db()
        self.assertEqual(db.get(MYCOLOGIST).num(0), 1)     # Once per turn
        self.assertEqual(db.get("BG33_891_G").num(0), 2)   # Twice per turn
        # Wildfire 无模板参数（excess 运行时计算）
        self.assertIsNone(db.get(WILDFIRE).num(0))
        # token 1/1 Murloc 非池卡（数据权威）
        t = db.get(APPRENTICE)
        self.assertEqual((t.atk, t.health), (1, 1))
        self.assertEqual(t.race, Race.MURLOC)
        self.assertFalse(t.is_pool_minion)


class TestWildfireElemental(unittest.TestCase):
    """BGS_126 — 击杀后超额伤害溅射相邻敌人（金色双侧）。"""

    def _setup_enemy_board(self, game, victim_hp: int):
        """敌方板位 [左邻, 受害者, 右邻] → 返回 (左邻, 右邻)。"""
        b = game.heroes[1]
        left = make_minion("Left", 0, 100)
        game.summon(b, left, 0)
        victim = make_minion("Victim", 0, victim_hp)
        game.summon(b, victim, 1)
        right = make_minion("Right", 0, 100)
        game.summon(b, right, 2)
        return left, right

    def test_excess_damage_to_single_adjacent(self):
        """单邻位（受害者在边位）: 5 攻 2 血 → 唯一相邻吃 3。"""
        game = make_game(seed=700)
        a, b = game.heroes
        wf = put(game, WILDFIRE, a)
        wf.set(GameTag.BASE_ATK, 5)          # 作业单设定: 5 攻
        neighbor = make_minion("Neighbor", 0, 100)
        game.summon(b, neighbor, 0)
        victim = make_minion("Victim", 0, 2)  # 2 血
        game.summon(b, victim, 1)
        self.assertEqual(wf.atk, 5)
        attack(game, wf, victim)
        self.assertTrue(victim.dead)
        self.assertEqual(neighbor.health, 100 - 3)   # excess = 5-2

    def test_excess_damage_random_one_of_two(self):
        """双邻位: 基础版恰好其一受超额（wiki [Random] tag）。"""
        game = make_game(seed=701)
        a, _ = game.heroes
        wf = put(game, WILDFIRE, a)          # 6 攻（数据权威）
        left, right = self._setup_enemy_board(game, victim_hp=2)
        attack(game, wf, game.heroes[1].board[1])
        damaged = [m for m in (left, right) if m.health < 100]
        self.assertEqual(len(damaged), 1)
        self.assertEqual(damaged[0].health, 100 - (wf.atk - 2))

    def test_golden_hits_both_adjacent(self):
        game = make_game(seed=702)
        a, _ = game.heroes
        wf = put(game, WILDFIRE, a, golden=True)
        self.assertEqual(wf.card_id, WILDFIRE_GOLDEN)
        self.assertEqual(wf.atk, 12)         # 金色卡面（数据权威）
        left, right = self._setup_enemy_board(game, victim_hp=2)
        attack(game, wf, game.heroes[1].board[1])
        self.assertEqual(left.health, 100 - (12 - 2))
        self.assertEqual(right.health, 100 - (12 - 2))

    def test_exact_kill_no_excess(self):
        """恰好击杀（无余量）→ 相邻不受击。"""
        game = make_game(seed=703)
        a, _ = game.heroes
        wf = put(game, WILDFIRE, a)          # 6 攻
        left, right = self._setup_enemy_board(game, victim_hp=6)
        attack(game, wf, game.heroes[1].board[1])
        self.assertEqual(left.health, 100)
        self.assertEqual(right.health, 100)

    def test_no_kill_no_trigger(self):
        """未击杀（目标存活）→ 不触发。"""
        game = make_game(seed=704)
        a, _ = game.heroes
        wf = put(game, WILDFIRE, a)
        left, right = self._setup_enemy_board(game, victim_hp=10)
        victim = game.heroes[1].board[1]
        attack(game, wf, victim)
        self.assertFalse(victim.dead)
        self.assertEqual(left.health, 100)
        self.assertEqual(right.health, 100)

    def test_other_attacker_does_not_trigger(self):
        """非本体攻击击杀 → 本体监听器不响应（负例）。"""
        game = make_game(seed=705)
        a, _ = game.heroes
        put(game, WILDFIRE, a)               # 在场但不出手
        other = make_minion("Other", 5, 100)
        game.summon(a, other)
        left, right = self._setup_enemy_board(game, victim_hp=2)
        attack(game, other, game.heroes[1].board[1])
        self.assertEqual(left.health, 100)
        self.assertEqual(right.health, 100)

    def test_divine_shield_absorb_no_kill(self):
        """圣盾抵消 → 未击杀 → 不触发（引擎 excess=0 通道）。"""
        game = make_game(seed=706)
        a, _ = game.heroes
        wf = put(game, WILDFIRE, a)
        left, right = self._setup_enemy_board(game, victim_hp=2)
        victim = game.heroes[1].board[1]
        victim.set(GameTag.DIVINE_SHIELD, True)
        attack(game, wf, victim)
        self.assertFalse(victim.dead)
        self.assertEqual(left.health, 100)
        self.assertEqual(right.health, 100)


class TestMagicfinMycologist(unittest.TestCase):
    """BG33_891 — 每次购买酒馆法术后获得被教 1/1 学徒。"""

    def _buy_spell(self, game, hero, card_id=SHINY_RING) -> Spell:
        """购买一张池法术（spell_pool 每张 1 份——重复购买用不同 id）。"""
        hero.gold = 10
        s = stock_spell(game, hero, card_id)
        self.assertTrue(game.buy_from_tavern(hero, s))
        return s

    def _apprentices(self, hero) -> list:
        return [c for c in hero.hand if c.card_id == APPRENTICE]

    def test_buy_spell_gets_taught_apprentice(self):
        game = make_game(seed=710)
        a, _ = game.heroes
        put(game, MYCOLOGIST, a)
        s = self._buy_spell(game, a)
        toks = self._apprentices(a)
        self.assertEqual(len(toks), 1)
        self.assertEqual((toks[0].atk, toks[0].max_health), (1, 1))
        self.assertEqual(toks[0].race, Race.MURLOC)
        self.assertEqual(toks[0]._taught_spell_id, s.card_id)

    def test_once_per_turn_limit(self):
        game = make_game(seed=711)
        a, _ = game.heroes
        put(game, MYCOLOGIST, a)
        self._buy_spell(game, a, SHINY_RING)
        self._buy_spell(game, a, "BG28_169")  # 同回合第二张不同法术
        self.assertEqual(len(self._apprentices(a)), 1)

    def test_resets_next_turn(self):
        game = make_game(seed=712)
        a, _ = game.heroes
        put(game, MYCOLOGIST, a)
        self._buy_spell(game, a, SHINY_RING)
        game.turn += 1
        self._buy_spell(game, a, "BG28_169")
        self.assertEqual(len(self._apprentices(a)), 2)

    def test_golden_twice_per_turn_incremental(self):
        """金色 2 程 + 35.2.0 hotfix: 每次购买只消耗一个充能。"""
        game = make_game(seed=713)
        a, _ = game.heroes
        mf = put(game, MYCOLOGIST, a, golden=True)
        self.assertEqual(mf.card_id, "BG33_891_G")
        self._buy_spell(game, a, SHINY_RING)
        self.assertEqual(len(self._apprentices(a)), 1)   # 未双耗
        self._buy_spell(game, a, "BG28_169")
        self.assertEqual(len(self._apprentices(a)), 2)
        self._buy_spell(game, a, "BG28_500")  # 第三张: 程尽
        self.assertEqual(len(self._apprentices(a)), 2)

    def test_buying_minion_does_not_trigger(self):
        game = make_game(seed=714)
        a, _ = game.heroes
        put(game, MYCOLOGIST, a)
        a.gold = 10
        m = stock_minion(game, a, "BG25_008")   # Eternal Knight（池卡）
        self.assertTrue(game.buy_from_tavern(a, m))
        self.assertEqual(self._apprentices(a), [])

    def test_two_mycologists_independent(self):
        """多副本各自独立计程（per-source 回合戳）。"""
        game = make_game(seed=715)
        a, _ = game.heroes
        put(game, MYCOLOGIST, a, 0)
        put(game, MYCOLOGIST, a, 1)
        self._buy_spell(game, a)
        self.assertEqual(len(self._apprentices(a)), 2)


class TestMagicfinApprentice(unittest.TestCase):
    """BG33_890t — 战吼直施被教法术; 不可三连。"""

    def _taught_token(self, game, hero, spell_id):
        put(game, MYCOLOGIST, hero)
        hero.gold = 10
        s = stock_spell(game, hero, spell_id)
        self.assertTrue(game.buy_from_tavern(hero, s))
        toks = [c for c in hero.hand if c.card_id == APPRENTICE]
        self.assertEqual(len(toks), 1)
        return toks[0]

    def test_battlecry_casts_untargeted_spell(self):
        """被教 Shiny Ring: 打出学徒 = 全体随从 +num(0)/+num(1)。"""
        game = make_game(seed=720)
        a, _ = game.heroes
        token = self._taught_token(game, a, SHINY_RING)
        friend = put(game, "BG25_008", a)    # Eternal Knight 白板
        before = (friend.atk, friend.max_health)
        self.assertTrue(game.play_minion(a, token))
        d = get_db().get(SHINY_RING)
        self.assertEqual(
            (friend.atk, friend.max_health),
            (before[0] + d.num(0), before[1] + d.num(1)))

    def test_battlecry_casts_targeted_spell_via_choice(self):
        """被教 Sacred Gift: 打出学徒 → spell_target 选择 → 目标得圣盾。"""
        game = make_game(seed=721)
        a, _ = game.heroes
        token = self._taught_token(game, a, SACRED_GIFT)
        friend = put(game, "BG25_008", a)
        self.assertFalse(friend.divine_shield)
        self.assertTrue(game.play_minion(a, token))
        pc = next((p for p in game.pending_choices
                   if p.kind == "spell_target"), None)
        self.assertIsNotNone(pc)
        pc.choose(pc.options.index(friend))
        self.assertTrue(friend.divine_shield)

    def test_untaught_token_battlecry_whiffs(self):
        game = make_game(seed=722)
        a, _ = game.heroes
        token = game.create_minion(APPRENTICE, controller=a)
        a.hand.append(token)
        token.zone = Zone.HAND
        friend = put(game, "BG25_008", a)
        before = (friend.atk, friend.max_health)
        self.assertTrue(game.play_minion(a, token))   # 落空但入场
        self.assertEqual(token.zone, Zone.PLAY)
        self.assertEqual((friend.atk, friend.max_health), before)

    def test_apprentice_cannot_be_tripled(self):
        """3 张学徒不合成（引擎非池卡跳过 check_for_triple）。"""
        game = make_game(seed=723)
        a, _ = game.heroes
        for _ in range(3):
            t = game.create_minion(APPRENTICE, controller=a)
            game.pending_hand_add(a, t)
        self.assertEqual(len(a.hand), 3)
        self.assertFalse(any(c.is_golden for c in a.hand))


class TestProstheticHand(unittest.TestCase):
    """BG_DEEP_015 — Magnetic+Reborn 关键词 + 磁力目标 Undead 扩展
    （_magnetic_valid 数据化，无脚本）。"""

    def _hand_minion(self, game, hero, card_id="BG_DEEP_015"):
        m = game.create_minion(card_id, controller=hero)
        hero.hand.append(m)
        m.zone = Zone.HAND
        return m

    def test_keywords_from_data(self):
        game = make_game(seed=730)
        a = game.heroes[0]
        for cid, golden in (("BG_DEEP_015", False),
                            ("BG_DEEP_015_G", True)):
            m = game.create_minion(cid, controller=a, golden=golden)
            self.assertTrue(m.has(GameTag.MAGNETIC), cid)
            self.assertTrue(m.reborn, cid)

    def test_magnetize_to_mech_and_undead(self):
        game = make_game(seed=731)
        a = game.heroes[0]
        for builder in (lambda: make_minion("Mech", 1, 1,
                                            race=Race.MECH),
                        lambda: make_minion("Undead", 1, 1,
                                            race=Race.UNDEAD)):
            host = builder()
            game.summon(a, host)
            hand = self._hand_minion(game, a)
            self.assertTrue(game.play_minion(a, hand,
                                              magnetic_target=host),
                            f"magnetize to {host.race} should work")
            self.assertEqual(host.reborn, True)   # 关键词并入
            self.assertEqual(host.get(GameTag.BASE_ATK, 0), 1 + 3)

    def test_magnetize_to_elemental_rejected(self):
        game = make_game(seed=732)
        a = game.heroes[0]
        host = make_minion("Elemental", 1, 1, race=Race.ELEMENTAL)
        game.summon(a, host)
        hand = self._hand_minion(game, a)
        self.assertFalse(game.play_minion(a, hand,
                                          magnetic_target=host))
        self.assertEqual(hand.zone, Zone.HAND)   # 未消耗


class TestPureKeywordCards(unittest.TestCase):
    """纯关键词卡核实——create_minion 后关键词 tag 在册（数据通道）。"""

    def test_risen_rider_taunt_reborn(self):
        game = make_game(seed=740)
        m = game.create_minion("BG25_001",
                               controller=game.heroes[0])
        self.assertTrue(m.taunt)
        self.assertTrue(m.reborn)

    def test_annoymodule_magnetic_ds_taunt(self):
        game = make_game(seed=741)
        m = game.create_minion("BG_BOT_911",
                               controller=game.heroes[0])
        self.assertTrue(m.has(GameTag.MAGNETIC))
        self.assertTrue(m.divine_shield)
        self.assertTrue(m.taunt)

    def test_crackling_cyclone_ds_windfury(self):
        game = make_game(seed=742)
        m = game.create_minion("BGS_119",
                               controller=game.heroes[0])
        self.assertTrue(m.divine_shield)
        self.assertTrue(m.windfury)

    def test_deadly_spore_venomous(self):
        game = make_game(seed=743)
        m = game.create_minion("BGS_131",
                               controller=game.heroes[0])
        self.assertTrue(m.has(GameTag.VENOMOUS))
        self.assertTrue(m.venomous_active)

    def test_elemental_of_surprise_triple_engine_builtin(self):
        """BG26_175 三连引擎内建（check_for_triple SUB_CARD 全池重扫）。
        全量覆盖见 test_engine_primitives.
        TestElementalSurpriseSubstitution（本测试为存在性复核）。"""
        game = make_game(seed=744)
        a = game.heroes[0]
        s1 = game.create_minion("BG26_175", controller=a)
        s2 = game.create_minion("BG26_175", controller=a)
        other = next(d for d in get_db().pool_minions()
                     if d.race == Race.ELEMENTAL and d.id != "BG26_175"
                     and game.minion_pool.available(d.id) > 0)
        elem = game.minion_pool.acquire(other.id)
        assert elem
        e1 = game.create_minion(other.id, controller=a)
        for m in (s1, e1):
            game.pending_hand_add(a, m)
        game.pending_hand_add(a, s2)      # 第三份到达触发重扫
        goldens = [c for c in a.hand + a.board if c.is_golden]
        self.assertEqual(len(goldens), 1)
        self.assertEqual(goldens[0].card_id, "BG26_175_G")


if __name__ == "__main__":
    unittest.main()
