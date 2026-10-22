"""批次 consume 语义测试（作业单 2026-08-21）。

覆盖 batch_consume.py 全部注册卡: BG21_004 Insatiable Ur'zul /
BG23_357 Mind Muck / BG28_633 Felboar / BG34_500 Flaming Enforcer /
BG36_851 Spark Snapper / BG36_853 Glambot / BG32_330 Flighty Scout /
BG36_620 Boom-in-a-Box / BG36_351 Moat Custodian（含金色）。

引擎契约重点验证: card_played target kwarg（Glambot）、_active_combat
战斗对（Boom-in-a-Box 第三方隔离）、hand_soc 手牌 SoC 协议
（Flighty Scout / Boom-in-a-Box 手牌负例）、attach_magnetic 实体属性
并入（Snapper/Glambot 动态尺寸 Satellite）。数值断言一律从 CardDef
num()/atk/health 计算。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.entity import Buff as Enchant
from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_consume as bc
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

UR_ZUL = "BG21_004"
MIND_MUCK = "BG23_357"
FELBOAR = "BG28_633"
ENFORCER = "BG34_500"
SNAPPER = "BG36_851"
GLAMBOT = "BG36_853"
SCOUT = "BG32_330"
BOOM = "BG36_620"
MOAT = "BG36_351"
MECH_HOST = "BG26_147"       # Accord-o-Tron（SoT 金币不属性干扰）
SHINY_RING = "BG28_805"      # 惰性载体池法术（Strike Oil 暂 DEFERRED——施放无副作用）
BLOOD_GEM = "BG20_GEM"       # 非池法术（血宝石）

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str) -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def find_def(race: Race | None = None, tier: int | None = None,
             min_health: int | None = None, exclude_bc: bool = True):
    """按种族/tier/血量找池卡（默认排除 battlecry——无 PendingChoice
    副作用，test_consume_tavern 同款）。"""
    for d in sorted(get_db().pool_minions(), key=lambda x: x.id):
        if race is not None and d.race != race:
            continue
        if tier is not None and d.tech_level != tier:
            continue
        if min_health is not None and d.health < min_health:
            continue
        if exclude_bc and "battlecry" in d.keywords:
            continue
        return d
    raise AssertionError(f"no pool def: race={race} tier={tier} "
                         f"min_health={min_health}")


def find_inert_def(race: Race | None = None, tier: int | None = None,
                   min_health: int | None = None):
    """找无注册脚本的惰性池卡——作触发监听卡的目标/被打出卡，避免
    其他卡的效果干扰断言（如 Mind Muck 测试的目标恶魔不能是
    Ur'zul 自身）。

    2026-08-22 修订: unfreeze/counters 批次注册了全部无关键词恶魔后
    首选通道常空——回落通道接受已注册但**无场面效果钩子**的卡
    （on_summon 仅注册监听/置 hero tag 的光环卡如 Malchezaar 对
    本文件断言无干扰; 有 battlecry/rally/亡语/动态属性/activate/
    EoT/SoT/on_sell 钩子的一律排除）。"""
    picked = None
    for d in sorted(get_db().pool_minions(), key=lambda x: x.id):
        if race is not None and d.race != race:
            continue
        if tier is not None and d.tech_level != tier:
            continue
        if min_health is not None and d.health < min_health:
            continue
        if d.keywords:
            continue
        script = REGISTRY.get(d.id)
        if script is None:
            return d
        if picked is None:
            unsafe = ("battlecry", "deathrattle", "rally",
                      "start_of_combat", "avenge", "activate",
                      "atk", "health", "on_sell", "end_of_turn",
                      "start_of_turn", "on_enter_hand", "on_play")
            if not any(hasattr(script, h) for h in unsafe):
                picked = d
    if picked is not None:
        return picked
    raise AssertionError(f"no inert pool def: race={race} tier={tier} "
                         f"min_health={min_health}")


def put(game: Game, card_id: str, hero: Hero, golden: bool = False,
        zero_atk: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    if zero_atk:
        m.set(GameTag.BASE_ATK, 0)
    game.summon(hero, m)
    return m


def to_hand(game: Game, card_id: str, hero: Hero,
            golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    hero.hand.append(m)
    return m


def put_in_tavern(game: Game, hero: Hero, card_id: str) -> Minion:
    assert game.minion_pool.acquire(card_id)
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def spell_to_hand(game: Game, hero: Hero, card_id: str):
    d = get_db().get(card_id)
    if d.is_pool_spell:
        assert game.spell_pool.acquire(card_id)
    s = game.create_spell(card_id, controller=hero)
    hero.hand.append(s)
    return s


class TestInsatiableUrZul(unittest.TestCase):
    def test_play_demon_consumes_random_tavern_minion(self):
        game = make_game(seed=41)
        a = game.heroes[0]
        dd = get_db().get(UR_ZUL)
        uez = put(game, UR_ZUL, a)
        self.assertTrue(uez.has(GameTag.TAUNT))
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        victim = put_in_tavern(game, a, vd.id)
        demon = to_hand(game, find_def(race=Race.DEMON).id, a)

        self.assertTrue(game.play_minion(a, demon))

        # 馆内唯一候选 → 随机确定性; 属性获得 = 受害者 atk/max_health
        self.assertEqual(uez.atk, dd.atk + vd.atk)
        self.assertEqual(uez.max_health, dd.health + vd.health)
        self.assertEqual(len(a.tavern), 0)
        self.assertEqual(victim.zone, Zone.REMOVED)

    def test_play_non_demon_does_not_trigger(self):
        game = make_game(seed=42)
        a = game.heroes[0]
        dd = get_db().get(UR_ZUL)
        uez = put(game, UR_ZUL, a)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        put_in_tavern(game, a, vd.id)
        beast = to_hand(game, vd.id, a)

        self.assertTrue(game.play_minion(a, beast))

        self.assertEqual(uez.atk, dd.atk)
        self.assertEqual(uez.max_health, dd.health)
        self.assertEqual(len(a.tavern), 1)

    def test_play_ur_zul_itself_triggers(self):
        # Ur'zul 是 Demon——打出自身同样触发（Interpreter 官方语义）
        game = make_game(seed=43)
        a = game.heroes[0]
        dd = get_db().get(UR_ZUL)
        uez = put(game, UR_ZUL, a)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        put_in_tavern(game, a, vd.id)
        another = to_hand(game, UR_ZUL, a)

        game.play_minion(a, another)

        self.assertEqual(uez.atk, dd.atk + vd.atk)
        self.assertEqual(len(a.tavern), 0)

    def test_golden_gains_double(self):
        game = make_game(seed=44)
        a = game.heroes[0]
        gd = get_db().get(f"{UR_ZUL}_G")
        uez = put(game, UR_ZUL, a, golden=True)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        put_in_tavern(game, a, vd.id)
        demon = to_hand(game, find_def(race=Race.DEMON).id, a)

        game.play_minion(a, demon)

        self.assertEqual(uez.atk, gd.atk + 2 * vd.atk)
        self.assertEqual(uez.max_health, gd.health + 2 * vd.health)
        self.assertEqual(len(a.tavern), 0)

    def test_empty_tavern_fizzles(self):
        game = make_game(seed=45)
        a = game.heroes[0]
        dd = get_db().get(UR_ZUL)
        uez = put(game, UR_ZUL, a)
        demon = to_hand(game, find_def(race=Race.DEMON).id, a)

        game.play_minion(a, demon)

        self.assertEqual(uez.atk, dd.atk)
        self.assertEqual(uez.max_health, dd.health)


class TestMindMuck(unittest.TestCase):
    def _play_muck(self, game, a, golden=False):
        muck = to_hand(game, MIND_MUCK, a, golden=golden)
        self.assertTrue(game.play_minion(a, muck))
        pc = game.pending_choices[-1]
        self.assertEqual(pc.kind, "battlecry_target")
        return pc

    def test_choose_demon_it_consumes_tavern_minion(self):
        game = make_game(seed=51)
        a = game.heroes[0]
        dd = find_inert_def(race=Race.DEMON)
        demon = put(game, dd.id, a)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        victim = put_in_tavern(game, a, vd.id)

        pc = self._play_muck(game, a)
        self.assertIn(demon, pc.options)
        pc.choose(pc.options.index(demon))

        # 吞噬者是**目标恶魔**（非 Mind Muck 自身）
        self.assertEqual(demon.atk, dd.atk + vd.atk)
        self.assertEqual(demon.max_health, dd.health + vd.health)
        self.assertEqual(len(a.tavern), 0)
        self.assertEqual(victim.zone, Zone.REMOVED)

    def test_candidates_exclude_non_demon(self):
        game = make_game(seed=52)
        a = game.heroes[0]
        beast = put(game, find_def(race=Race.BEAST, tier=1).id, a)
        muck = to_hand(game, MIND_MUCK, a)

        game.play_minion(a, muck)
        pc = game.pending_choices[-1]

        self.assertNotIn(beast, pc.options)
        # Mind Muck 自身是 Demon 且先入场 → 合法目标
        self.assertTrue(any(m.card_id == MIND_MUCK for m in pc.options))

    def test_empty_tavern_fizzles(self):
        game = make_game(seed=53)
        a = game.heroes[0]
        dd = find_inert_def(race=Race.DEMON)
        demon = put(game, dd.id, a)
        atk0, hp0 = demon.atk, demon.max_health

        pc = self._play_muck(game, a)
        pc.choose(pc.options.index(demon))

        self.assertEqual(demon.atk, atk0)
        self.assertEqual(demon.max_health, hp0)

    def test_golden_single_consume_double_stats(self):
        # 金色文本 "gain double its stats" = 单次吞噬双倍（非两次吞噬）
        game = make_game(seed=54)
        a = game.heroes[0]
        dd = find_inert_def(race=Race.DEMON)
        demon = put(game, dd.id, a)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        v1 = put_in_tavern(game, a, vd.id)
        v2 = put_in_tavern(game, a, vd.id)

        pc = self._play_muck(game, a, golden=True)
        pc.choose(pc.options.index(demon))

        self.assertEqual(demon.atk, dd.atk + 2 * vd.atk)
        self.assertEqual(demon.max_health, dd.health + 2 * vd.health)
        # 恰吞噬 1 只（引擎金色战吼 2 次由守卫抑制）
        self.assertEqual(len(a.tavern), 1)
        consumed = v1 if v1.zone == Zone.REMOVED else v2
        self.assertEqual(consumed.zone, Zone.REMOVED)


class TestFelboar(unittest.TestCase):
    def _cast(self, game, a, card_id, target=None):
        s = spell_to_hand(game, a, card_id)
        self.assertTrue(game.play_spell(a, s, target=target))

    def test_consumes_after_threshold_tavern_spells(self):
        game = make_game(seed=61)
        a = game.heroes[0]
        fd = get_db().get(FELBOAR)
        threshold = fd.num(1)
        self.assertIsNotNone(threshold)
        felboar = put(game, FELBOAR, a)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        victim = put_in_tavern(game, a, vd.id)

        for i in range(threshold - 1):
            self._cast(game, a, SHINY_RING)
        self.assertEqual(felboar.atk, fd.atk)
        self.assertEqual(len(a.tavern), 1)

        self._cast(game, a, SHINY_RING)   # 第 threshold 次

        self.assertEqual(felboar.atk, fd.atk + vd.atk)
        self.assertEqual(felboar.max_health, fd.health + vd.health)
        self.assertEqual(len(a.tavern), 0)

    def test_blood_gem_not_counted(self):
        # 血宝石非酒馆法术（wiki "Tavern spell-related"）——不计入
        game = make_game(seed=62)
        a = game.heroes[0]
        fd = get_db().get(FELBOAR)
        felboar = put(game, FELBOAR, a)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        put_in_tavern(game, a, vd.id)
        gem = spell_to_hand(game, a, BLOOD_GEM)

        game.play_spell(a, gem, target=felboar)

        self.assertEqual(getattr(felboar, "_felboar_casts", 0), 0)
        self.assertEqual(len(a.tavern), 1)

    def test_counter_rolls_over(self):
        game = make_game(seed=63)
        a = game.heroes[0]
        fd = get_db().get(FELBOAR)
        threshold = fd.num(1)
        felboar = put(game, FELBOAR, a)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)

        for _ in range(2 * threshold):
            put_in_tavern(game, a, vd.id)
            self._cast(game, a, SHINY_RING)

        # 每 threshold 次触发一次 → 2 次吞噬（各随机一只，共放入
        # 2×threshold 只、消耗 2 只）
        self.assertEqual(felboar.atk, fd.atk + 2 * vd.atk)
        self.assertEqual(len(a.tavern), 2 * threshold - 2)

    def test_golden_gains_double(self):
        game = make_game(seed=64)
        a = game.heroes[0]
        fd = get_db().get(FELBOAR)
        gd = get_db().get(f"{FELBOAR}_G")
        threshold = gd.num(1)
        felboar = put(game, FELBOAR, a, golden=True)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        victim = put_in_tavern(game, a, vd.id)

        for _ in range(threshold):
            self._cast(game, a, SHINY_RING)

        self.assertEqual(felboar.atk, gd.atk + 2 * vd.atk)
        self.assertEqual(felboar.max_health, gd.health + 2 * vd.health)
        self.assertEqual(victim.zone, Zone.REMOVED)


class TestFlamingEnforcer(unittest.TestCase):
    def test_consumes_highest_health_tavern_minion(self):
        game = make_game(seed=71)
        a = game.heroes[0]
        ed = get_db().get(ENFORCER)
        enf = put(game, ENFORCER, a)
        low = put_in_tavern(game, a,
                            find_def(race=Race.BEAST, tier=1).id)
        high = put_in_tavern(game, a,
                             find_def(race=Race.BEAST, tier=1).id)
        high.add_buff(Enchant(0, 5))   # max_health +5 → 唯一最高

        game.run_script_hook(enf, "end_of_turn")

        self.assertEqual(enf.atk, ed.atk + high.atk)
        self.assertEqual(enf.max_health, ed.health + high.max_health)
        self.assertEqual(high.zone, Zone.REMOVED)
        self.assertIn(low, a.tavern)

    def test_empty_tavern_fizzles(self):
        game = make_game(seed=72)
        a = game.heroes[0]
        ed = get_db().get(ENFORCER)
        enf = put(game, ENFORCER, a)

        game.run_script_hook(enf, "end_of_turn")

        self.assertEqual(enf.atk, ed.atk)
        self.assertEqual(enf.max_health, ed.health)

    def test_golden_gains_double(self):
        game = make_game(seed=73)
        a = game.heroes[0]
        gd = get_db().get(f"{ENFORCER}_G")
        enf = put(game, ENFORCER, a, golden=True)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        victim = put_in_tavern(game, a, vd.id)

        game.run_script_hook(enf, "end_of_turn")

        self.assertEqual(enf.atk, gd.atk + 2 * vd.atk)
        self.assertEqual(enf.max_health, gd.health + 2 * vd.health)
        self.assertEqual(len(a.tavern), 0)


class TestSparkSnapper(unittest.TestCase):
    def test_satellite_grows_with_improve(self):
        game = make_game(seed=81)
        a = game.heroes[0]
        d = get_db().get(SNAPPER)
        step = d.num(1)
        put(game, SNAPPER, a)
        m1 = to_hand(game, MECH_HOST, a)
        m2 = to_hand(game, MECH_HOST, a)
        md = get_db().get(MECH_HOST)

        game.play_minion(a, m1)
        self.assertEqual(m1.atk, md.atk + step)
        self.assertEqual(m1.max_health, md.health + step)
        self.assertEqual(game._magnetic_stack[m1.uuid], [bc.SATELLITE_ID])

        game.play_minion(a, m2)   # 第二次触发: improve 后 2×step
        self.assertEqual(m2.atk, md.atk + 2 * step)
        self.assertEqual(m2.max_health, md.health + 2 * step)

    def test_non_mech_does_not_trigger(self):
        game = make_game(seed=82)
        a = game.heroes[0]
        beast = to_hand(game, find_def(race=Race.BEAST, tier=1).id, a)

        game.play_minion(a, beast)

        self.assertNotIn(beast.uuid, game._magnetic_stack)

    def test_magnetic_path_does_not_trigger(self):
        # 磁力吸附路径 card_played 的 zone 已 REMOVED → 不触发
        # （文本 "play a Mech"，无 "or Magnetize"）
        game = make_game(seed=83)
        a = game.heroes[0]
        put(game, SNAPPER, a)
        host = put(game, MECH_HOST, a)
        lullabot = to_hand(game, "BG26_146", a)
        ld = get_db().get("BG26_146")

        game.play_minion(a, lullabot, magnetic_target=host)

        # 宿主只得 Lullabot 的 +2/+2，无 Satellite
        hd = get_db().get(MECH_HOST)
        self.assertEqual(host.atk, hd.atk + ld.atk)
        self.assertEqual(host.max_health, hd.health + ld.health)
        self.assertEqual(game._magnetic_stack[host.uuid], ["BG26_146"])

    def test_play_snapper_itself_triggers(self):
        game = make_game(seed=84)
        a = game.heroes[0]
        d = get_db().get(SNAPPER)
        step = d.num(1)
        put(game, SNAPPER, a)          # 场上 Snapper 的监听器
        snapper2 = to_hand(game, SNAPPER, a)

        game.play_minion(a, snapper2)  # 自身是 Mech → 吸附给自己

        # 两只 Snapper 的监听器各触发一次（各自 improve 计数 0 起步）
        self.assertEqual(snapper2.atk, d.atk + 2 * step)
        self.assertEqual(snapper2.max_health, d.health + 2 * step)

    def test_golden_step_from_golden_def(self):
        game = make_game(seed=85)
        a = game.heroes[0]
        gd = get_db().get(f"{SNAPPER}_G")
        step = gd.num(1)
        put(game, SNAPPER, a, golden=True)
        m1 = to_hand(game, MECH_HOST, a)
        m2 = to_hand(game, MECH_HOST, a)
        md = get_db().get(MECH_HOST)

        game.play_minion(a, m1)
        game.play_minion(a, m2)

        self.assertEqual(m1.atk, md.atk + step)
        self.assertEqual(m2.atk, md.atk + 2 * step)


class TestGlambot(unittest.TestCase):
    def test_spell_on_mech_magnetizes_satellite(self):
        # 血宝石以 Mech 为目标施放——"cast a spell on a Mech"（任意法术）
        game = make_game(seed=91)
        a = game.heroes[0]
        d = get_db().get(GLAMBOT)
        put(game, GLAMBOT, a)
        host = put(game, MECH_HOST, a)
        hd = get_db().get(MECH_HOST)
        gem_d = get_db().get(BLOOD_GEM)
        gem = spell_to_hand(game, a, BLOOD_GEM)

        game.play_spell(a, gem, target=host)

        # 宿主: 宝石 +num(0)/num(1) + Satellite num(0)/num(1)
        self.assertEqual(host.atk, hd.atk + gem_d.num(0) + d.num(0))
        self.assertEqual(host.max_health,
                         hd.health + gem_d.num(1) + d.num(1))
        self.assertEqual(game._magnetic_stack[host.uuid],
                         [bc.SATELLITE_ID])

    def test_untargeted_spell_does_not_trigger(self):
        game = make_game(seed=92)
        a = game.heroes[0]
        host = put(game, MECH_HOST, a)

        self._cast_ring(game, a)

        self.assertNotIn(host.uuid, game._magnetic_stack)

    def test_spell_on_non_mech_does_not_trigger(self):
        game = make_game(seed=93)
        a = game.heroes[0]
        put(game, GLAMBOT, a)
        beast = put(game, find_def(race=Race.BEAST, tier=1).id, a)
        gem = spell_to_hand(game, a, BLOOD_GEM)

        game.play_spell(a, gem, target=beast)

        self.assertNotIn(beast.uuid, game._magnetic_stack)

    def test_golden_attaches_twice(self):
        game = make_game(seed=94)
        a = game.heroes[0]
        d = get_db().get(f"{GLAMBOT}_G")
        put(game, GLAMBOT, a, golden=True)
        host = put(game, MECH_HOST, a)
        hd = get_db().get(MECH_HOST)
        gem_d = get_db().get(BLOOD_GEM)
        gem = spell_to_hand(game, a, BLOOD_GEM)

        game.play_spell(a, gem, target=host)

        self.assertEqual(host.atk, hd.atk + gem_d.num(0) + 2 * d.num(0))
        self.assertEqual(host.max_health,
                         hd.health + gem_d.num(1) + 2 * d.num(1))
        self.assertEqual(game._magnetic_stack[host.uuid],
                         [bc.SATELLITE_ID, bc.SATELLITE_ID])

    def _cast_ring(self, game, a):
        s = spell_to_hand(game, a, SHINY_RING)
        game.play_spell(a, s)


class TestFlightyScout(unittest.TestCase):
    def test_hand_soc_summons_copy_and_keeps_original(self):
        game = make_game(seed=101)
        a, b = game.heroes
        d = get_db().get(SCOUT)
        scout = to_hand(game, SCOUT, a)
        buffed_atk = d.atk + 2
        scout.add_buff(Enchant(2, 2))   # "a copy of it" 含 buff

        game.run_combat(a, b)

        # 副本经 combat_summon_log 可观测（战后随 board 恢复消失）
        copies = [m for m in game.combat_summon_log
                  if m.card_id == SCOUT]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].atk, buffed_atk)
        self.assertIn(scout, a.hand)    # 原件保留
        self.assertEqual(scout.atk, buffed_atk)

    def test_board_path_does_not_trigger(self):
        game = make_game(seed=102)
        a, b = game.heroes
        put(game, SCOUT, b, zero_atk=True)

        game.run_combat(a, b)

        self.assertEqual(game.combat_summon_log, [])

    def test_golden_copy_double_stats(self):
        game = make_game(seed=103)
        a, b = game.heroes
        gd = get_db().get(f"{SCOUT}_G")
        scout = to_hand(game, SCOUT, a, golden=True)

        game.run_combat(a, b)

        copies = [m for m in game.combat_summon_log
                  if m.card_id == f"{SCOUT}_G"]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].atk, 2 * gd.atk)
        self.assertEqual(copies[0].max_health, 2 * gd.health)


class TestBoomInABox(unittest.TestCase):
    def _collect_damage(self, game):
        log = []
        game.events.register(Listener(
            event="damage", owner=game.heroes[0],
            callback=lambda g, minion=None, amount=0, source=None, **kw:
                log.append((minion, amount, source))))
        return log

    def test_soc_damages_all_other_minions_both_boards(self):
        game = make_game(seed=111)
        a, b = game.heroes
        d = get_db().get(BOOM)
        dmg = d.num(0)
        boom = put(game, BOOM, a, zero_atk=True)
        m_a = put(game, find_def(race=Race.BEAST, tier=1).id, a,
                  zero_atk=True)
        m_b1 = put(game, find_def(race=Race.BEAST, tier=1).id, b,
                   zero_atk=True)
        m_b2 = put(game, find_def(race=Race.BEAST, tier=1).id, b,
                   zero_atk=True)
        log = self._collect_damage(game)

        game.run_combat(a, b)

        # 仅统计 Boom 的 SoC 造成的伤害（source 过滤——引擎修复后
        # 反击伤害也正确广播 damage 事件，不再混入）
        hits = {id(m): n for m, n, src in log if src is boom}
        self.assertEqual(hits.get(id(m_a)), dmg)
        self.assertEqual(hits.get(id(m_b1)), dmg)
        self.assertEqual(hits.get(id(m_b2)), dmg)
        self.assertNotIn(id(boom), hits)   # 自身不受

    def test_third_hero_board_isolated(self):
        # >2 人局: _active_combat 之外的英雄棋盘不受影响
        game = make_game(seed=112, heroes=[make_hero("A"), make_hero("B"),
                                           make_hero("C")])
        a, b, c = game.heroes
        put(game, BOOM, a, zero_atk=True)
        m_c = put(game, find_def(race=Race.BEAST, tier=1).id, c,
                  zero_atk=True)
        hp0 = m_c.health
        log = self._collect_damage(game)

        game.run_combat(a, b)

        self.assertFalse(any(m is m_c for m, _ in log))
        self.assertEqual(m_c.health, hp0)

    def test_golden_two_waves(self):
        game = make_game(seed=113)
        a, b = game.heroes
        gd = get_db().get(f"{BOOM}_G")
        dmg = gd.num(0)
        boom = put(game, BOOM, a, golden=True, zero_atk=True)
        tank = put(game, find_def(race=Race.BEAST, tier=1,
                                  min_health=4).id, a, zero_atk=True)
        tank.add_buff(Enchant(0, dmg * 2))   # 血量 > 2 轮伤害 → 存活两轮
        log = self._collect_damage(game)

        game.run_combat(a, b)

        waves = [n for m, n, _src in log if m is tank]
        self.assertEqual(waves, [dmg, dmg])
        self.assertFalse(any(m is boom for m, _, _s in log))

    def test_hand_does_not_trigger(self):
        # hand_soc 未声明——手牌中的 Boom-in-a-Box SoC 不触发
        game = make_game(seed=114)
        a, b = game.heroes
        to_hand(game, BOOM, a)
        m_a = put(game, find_def(race=Race.BEAST, tier=1).id, a,
                  zero_atk=True)
        m_b = put(game, find_def(race=Race.BEAST, tier=1).id, b,
                  zero_atk=True)
        log = self._collect_damage(game)

        game.run_combat(a, b)

        self.assertEqual(log, [])


class TestMoatCustodian(unittest.TestCase):
    def test_rally_stacks_elemental_extra_tags(self):
        game = make_game(seed=121)
        a = game.heroes[0]
        d = get_db().get(MOAT)
        moat = put(game, MOAT, a)

        game.run_script_hook(moat, "rally", ctx={"target": None})

        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), d.num(0))
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0),
                         d.num(1))

        game.run_script_hook(moat, "rally", ctx={"target": None})

        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0),
                         2 * d.num(0))
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0),
                         2 * d.num(1))

    def test_golden_values_from_golden_def(self):
        game = make_game(seed=122)
        a = game.heroes[0]
        gd = get_db().get(f"{MOAT}_G")
        moat = put(game, MOAT, a, golden=True)

        game.run_script_hook(moat, "rally", ctx={"target": None})

        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), gd.num(0))
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0),
                         gd.num(1))

    def test_elemental_buff_consumes_tags(self):
        # 读写闭环: Moat 设置 → elemental_buff 消费（基值 + tag）
        game = make_game(seed=123)
        a = game.heroes[0]
        d = get_db().get(MOAT)
        moat = put(game, MOAT, a)
        vd = find_def(race=Race.BEAST, tier=1, min_health=3)
        m = put(game, vd.id, a)

        game.run_script_hook(moat, "rally", ctx={"target": None})
        game.run_actions(bc.elemental_buff(m, 1, 1))

        self.assertEqual(m.atk, vd.atk + 1 + d.num(0))
        self.assertEqual(m.max_health, vd.health + 1 + d.num(1))


class TestRegistryResolution(unittest.TestCase):
    def test_registry_resolves_implementations(self):
        # 注册冲突治理: batch_magnetic 的 DEFERRED 占位必须被本批实现替换
        self.assertIs(REGISTRY.get(SNAPPER), bc.SparkSnapperScript)
        self.assertIs(REGISTRY.get(f"{SNAPPER}_G"), bc.SparkSnapperScript)
        self.assertIs(REGISTRY.get(GLAMBOT), bc.GlambotScript)
        self.assertIs(REGISTRY.get(f"{GLAMBOT}_G"),
                      bc.GlambotGoldenScript)
        # 其余 7 张 + 金色
        for cid, cls in (
            (UR_ZUL, bc.InsatiableUrZulScript),
            (f"{UR_ZUL}_G", bc.InsatiableUrZulGoldenScript),
            (MIND_MUCK, bc.MindMuckScript),
            (f"{MIND_MUCK}_G", bc.MindMuckGoldenScript),
            (FELBOAR, bc.FelboarScript),
            (f"{FELBOAR}_G", bc.FelboarGoldenScript),
            (ENFORCER, bc.FlamingEnforcerScript),
            (f"{ENFORCER}_G", bc.FlamingEnforcerGoldenScript),
            (SCOUT, bc.FlightyScoutScript),
            (f"{SCOUT}_G", bc.FlightyScoutGoldenScript),
            (BOOM, bc.BoomInABoxScript),
            (f"{BOOM}_G", bc.BoomInABoxGoldenScript),
            (MOAT, bc.MoatCustodianScript),
            (f"{MOAT}_G", bc.MoatCustodianScript),
        ):
            self.assertIs(REGISTRY.get(cid), cls, cid)

    def test_snapper_golden_uses_golden_num(self):
        # 金色实体经金色 CardDef 取数（同脚本类、金色 id 注册）
        gd = get_db().get(f"{SNAPPER}_G")
        self.assertEqual(gd.num(1), 2 * get_db().get(SNAPPER).num(1))


if __name__ == "__main__":
    unittest.main()
