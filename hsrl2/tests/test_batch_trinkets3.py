"""批次 trinkets3 行为层测试（18 张饰品）。

全部断言走真实引擎路径（真 SoC/EoT 钩子分发、真 run_combat、真
refresh_tavern、真 buy_from_tavern、真 sell_minion、真 spend_gold、
真 play_spell/play_minion、真死亡处理），期望值一律由 CardDef.num(0/1)
或文本字面量推导，不使用硬编码魔数副本。

覆盖:
  - owner 隔离（每张监听/光环类卡都有对手不受影响的断言）
  - SoC 增益战后快照回滚（Holy Mallet / Training Certificate /
    Bronze Timepiece）
  - 计数类阈值与清零（Lava Lamp / Fungalmancer Sticker）
  - 池交互（Eye of Dalaran / Lava Lamp / Fungalmancer / Exquisite
    Dishware 的随机获取占池）
  - 引擎读取点（NEXT_SPELL_COST_REDUCTION / UPGRADE_COST_MOD /
    _tavern_offer_override）
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.events import START_OF_COMBAT, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches.batch_trinkets3 import (
    BartendOTronOilcanScript,
    BootyBayBrewScript,
    BronzeTimepieceScript,
    ChargingStaffScript,
    EyeOfDalaranScript,
    FeralTalismanScript,
    FungalmancerStickerScript,
    GildedAnchorScript,
    GlowingGauntletScript,
    HolyMalletScript,
    LavaLampScript,
    TrainingCertificateScript,
    _ALL_MINION_RACES,
    _controlled_types,
)
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有卡（CardDB 按名核实，非凭记忆 id）
MURLOC = "BG22_202"          # Tad 2/2 Murloc
UNDEAD = "BG25_008"          # Eternal Knight 4/2 Undead
NOTYPE = "BG24_715"          # Patient Scout 1/1 无类型（有出售效果,仅用于死亡）
SELL_FODDER = "BG24_004"     # Warpwing 12/4 Dragon（无出售/死亡效果——纯出售料）
DRAGON3 = "BG35_814"         # Scarlet Survivor 3/3 Dragon（奇数攻 3）
ELEMENTAL = "BG31_816"       # Fire Baller 4/3 Elemental（仅 on_sell）
PIRATE_A = "BG_NEW1_027"     # Southsea Captain 3/3 Pirate
PIRATE_B = "BGS_053"         # Bloodsail Cannoneer 4/3 Pirate
PIRATE_C = "BGS_056"         # Ripsnarl Captain 3/3 Pirate
DS_MINION = "BGS_071"        # Deflect-o-Bot 3/2（Divine Shield）
ALL_MINION = "BG36_640"      # Gatekeeper Amalgam 6/6（All 类型）
SPELL_COST2 = "BG28_512"     # Enchanted Lasso（2 费酒馆法术）
SPELL_BENIGN = "BG28_800"    # Careful Investment（无场面效果的酒馆法术）

_db = None


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 70):
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def buy_trinket(game, hero, tid):
    """真实购买接线: create_entity + hero.trinkets + on_bind(ctx=hero)，
    与 game._offer_trinkets 的 resolve 路径一致。"""
    e = game.create_entity(tid, controller=hero)
    hero.trinkets.append(e)
    game.run_script_hook(e, "on_bind", ctx={"hero": hero})
    return e


def put(game, hero, card_id, position=None):
    m = game.create_minion(card_id, controller=hero)
    game.summon(hero, m, position)
    return m


def sell_fodder(game, hero, card_id=SELL_FODDER):
    m = game.create_minion(card_id, controller=hero)
    game.summon(hero, m)
    game.sell_minion(hero, m)
    return m


def pool_sum(game, ids):
    return sum(game.minion_pool.available(i) for i in ids)


def spell_pool_sum(game):
    return sum(game.spell_pool.available(d.id) for d in game.db.pool_spells())


class TestRegistry(unittest.TestCase):
    IMPLEMENTED = (
        "BG30_MagicItem_902", "BG30_MagicItem_962", "BG30_MagicItem_995",
        "BG30_MagicItem_984", "BG32_MagicItem_231", "BG32_MagicItem_276",
        "BG32_MagicItem_281", "BG30_MagicItem_924", "BG30_MagicItem_981",
        "BG30_MagicItem_951", "BG30_MagicItem_710", "BG30_MagicItem_419",
        "BG30_MagicItem_880", "BG30_MagicItem_989", "BG30_MagicItem_979",
        "BG30_MagicItem_705", "BG30_MagicItem_841", "BG32_MagicItem_284",
    )

    def test_all_registered(self):
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)
            self.assertIsNotNone(get_db().get(tid), tid)
        self.assertEqual(len(self.IMPLEMENTED), 18)

    def test_thresholds_match_carddef(self):
        db = get_db()
        # Lava Lamp 文本 "{1} minions" → 阈值 num(1)
        self.assertIn("{1}", db.get("BG30_MagicItem_951").text)
        # Fungalmancer 文本硬写 5、{0} 为剩余显示 → 阈值 num(0)
        self.assertIn("sell 5 minions",
                      db.get("BG30_MagicItem_710").text)
        # 卡片 script 类被绑定且类型正确
        self.assertIs(REGISTRY["BG30_MagicItem_902"], HolyMalletScript)
        self.assertIs(REGISTRY["BG30_MagicItem_962"],
                      TrainingCertificateScript)
        self.assertIs(REGISTRY["BG30_MagicItem_995"],
                      BronzeTimepieceScript)
        self.assertIs(REGISTRY["BG30_MagicItem_984"], ChargingStaffScript)
        self.assertIs(REGISTRY["BG32_MagicItem_231"], GildedAnchorScript)
        self.assertIs(REGISTRY["BG30_MagicItem_924"], BootyBayBrewScript)
        self.assertIs(REGISTRY["BG30_MagicItem_981"], EyeOfDalaranScript)
        self.assertIs(REGISTRY["BG30_MagicItem_951"], LavaLampScript)
        self.assertIs(REGISTRY["BG30_MagicItem_710"],
                      FungalmancerStickerScript)
        self.assertIs(REGISTRY["BG30_MagicItem_880"], FeralTalismanScript)
        self.assertIs(REGISTRY["BG30_MagicItem_841"], GlowingGauntletScript)
        self.assertIs(REGISTRY["BG30_MagicItem_705"],
                      BartendOTronOilcanScript)


# ══════════════════ BG30_MagicItem_902 Holy Mallet ══════════════════

class TestHolyMallet(unittest.TestCase):
    TID = "BG30_MagicItem_902"

    def test_left_and_right_most_gain_divine_shield(self):
        g = make_game(seed=101)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        left = put(g, a, MURLOC, 0)
        mid = put(g, a, UNDEAD, 1)
        right = put(g, a, DRAGON3, 2)
        put(g, b, MURLOC, 0)
        g.run_script_hook(a.trinkets[0], "start_of_combat")
        self.assertTrue(left.has(GameTag.DIVINE_SHIELD))
        self.assertFalse(mid.has(GameTag.DIVINE_SHIELD))
        self.assertTrue(right.has(GameTag.DIVINE_SHIELD))
        # owner 隔离: 对手最左随从不获圣盾
        self.assertFalse(b.board[0].has(GameTag.DIVINE_SHIELD))

    def test_single_minion_granted_once(self):
        g = make_game(seed=102)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        only = put(g, a, MURLOC, 0)
        g.run_script_hook(a.trinkets[0], "start_of_combat")
        self.assertTrue(only.has(GameTag.DIVINE_SHIELD))
        # 每次 SoC 恰好一次 GainKeyword（keyword_gained 事件计数）
        n = []
        g.events.register(Listener(
            event="keyword_gained", owner=only,
            callback=lambda gg, **kw: n.append(1)))
        only.clear(GameTag.DIVINE_SHIELD)
        g.run_script_hook(a.trinkets[0], "start_of_combat")
        self.assertEqual(len(n), 1)

    def test_empty_board_whiffs(self):
        g = make_game(seed=103)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        self.assertIsNone(
            g.run_script_hook(a.trinkets[0], "start_of_combat"))

    def test_run_combat_rolls_back_divine_shield(self):
        g = make_game(seed=104)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        m = put(g, a, MURLOC, 0)
        put(g, b, DRAGON3, 0)
        # 战斗内探针（登记在饰品监听之后 → 观察到的已是本饰品效果）:
        # 证明"加上又回滚"而非"从未加过"（对抗审查: 旧测试 no-op 也能过）
        seen = []
        g.events.register(Listener(
            event=START_OF_COMBAT, owner=a,
            callback=lambda gg, hero=None, **kw: (
                seen.append(m.has(GameTag.DIVINE_SHIELD))
                if hero is a else None)))
        g.run_combat(a, b)
        self.assertEqual(seen, [True])          # 战斗内确实获得圣盾
        self.assertFalse(
            any(m.has(GameTag.DIVINE_SHIELD) for m in a.board))


# ══════════════════ BG30_MagicItem_962 Training Certificate ══════════════

class TestTrainingCertificate(unittest.TestCase):
    TID = "BG30_MagicItem_962"

    def test_two_lowest_attack_doubled(self):
        g = make_game(seed=111)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        low = put(g, a, NOTYPE, 0)      # 1/1
        mid = put(g, a, MURLOC, 1)      # 2/2
        high = put(g, a, UNDEAD, 2)     # 4/2
        put(g, b, MURLOC, 0)
        g.run_script_hook(a.trinkets[0], "start_of_combat")
        self.assertEqual((low.atk, low.max_health), (2, 2))
        self.assertEqual((mid.atk, mid.max_health), (4, 4))
        self.assertEqual((high.atk, high.max_health), (4, 2))
        # owner 隔离
        self.assertEqual((b.board[0].atk, b.board[0].max_health), (2, 2))

    def test_single_minion_only_one_doubled(self):
        g = make_game(seed=112)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        only = put(g, a, MURLOC, 0)     # 2/2
        g.run_script_hook(a.trinkets[0], "start_of_combat")
        self.assertEqual((only.atk, only.max_health), (4, 4))

    def test_run_combat_rolls_back_stats(self):
        g = make_game(seed=113)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        low = put(g, a, NOTYPE, 0)
        put(g, b, DRAGON3, 0)
        seen = []
        g.events.register(Listener(
            event=START_OF_COMBAT, owner=a,
            callback=lambda gg, hero=None, **kw: (
                seen.append((low.atk, low.max_health))
                if hero is a else None)))
        g.run_combat(a, b)
        self.assertEqual(seen, [(2, 2)])       # 战斗内确实翻倍
        self.assertEqual((low.atk, low.max_health), (1, 1))


# ══════════════════ BG30_MagicItem_995 Bronze Timepiece ══════════════

class TestBronzeTimepiece(unittest.TestCase):
    TID = "BG30_MagicItem_995"

    def test_health_equal_half_attack_rounded_down(self):
        g = make_game(seed=121)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        one = put(g, a, NOTYPE, 0)      # 1 攻 → +0
        two = put(g, a, MURLOC, 1)      # 2 攻 → +1
        four = put(g, a, UNDEAD, 2)     # 4 攻 → +2
        odd = put(g, a, DRAGON3, 3)     # 3 攻 → +1（向下取整）
        put(g, b, MURLOC, 0)
        g.run_script_hook(a.trinkets[0], "start_of_combat")
        self.assertEqual(one.max_health, 1)          # 1 // 2 == 0
        self.assertEqual(two.max_health, 3)
        self.assertEqual(four.max_health, 4)
        self.assertEqual(odd.max_health, 4)          # 3 // 2 == 1（非 2）
        self.assertEqual(odd.atk, 3)                 # 只加生命
        # owner 隔离
        self.assertEqual(b.board[0].max_health, 2)

    def test_zero_attack_minion_gets_nothing(self):
        g = make_game(seed=122)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        m = put(g, a, MURLOC, 0)
        m.set(GameTag.BASE_ATK, 0)
        g.run_script_hook(a.trinkets[0], "start_of_combat")
        self.assertEqual(m.max_health, 2)

    def test_run_combat_rolls_back_health(self):
        g = make_game(seed=123)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        m = put(g, a, UNDEAD, 0)        # 4/2 → 4/4
        put(g, b, DRAGON3, 0)
        seen = []
        g.events.register(Listener(
            event=START_OF_COMBAT, owner=a,
            callback=lambda gg, hero=None, **kw: (
                seen.append(m.max_health) if hero is a else None)))
        g.run_combat(a, b)
        self.assertEqual(seen, [4])     # 战斗内确实 +2
        self.assertEqual(m.max_health, 2)


# ══════════════════ BG30_MagicItem_984 Charging Staff ══════════════

class TestChargingStaff(unittest.TestCase):
    TID = "BG30_MagicItem_984"

    def test_eot_buffs_only_divine_shield_minions(self):
        g = make_game(seed=131)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        ds = put(g, a, DS_MINION, 0)    # 3/2 圣盾
        plain = put(g, a, MURLOC, 1)    # 2/2
        put(g, b, DS_MINION, 0)
        g.run_script_hook(a.trinkets[0], "end_of_turn")
        self.assertEqual(ds.atk, 6)
        self.assertEqual(plain.atk, 2)
        # owner 隔离
        self.assertEqual(b.board[0].atk, 3)

    def test_two_eot_stack(self):
        g = make_game(seed=132)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        ds = put(g, a, DS_MINION, 0)
        g.run_script_hook(a.trinkets[0], "end_of_turn")
        g.run_script_hook(a.trinkets[0], "end_of_turn")
        self.assertEqual(ds.atk, 9)

    def test_full_end_recruit_phase_applies_eot(self):
        g = make_game(seed=133)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        ds = put(g, a, DS_MINION, 0)
        put(g, b, DS_MINION, 0)
        g.end_recruit_phase()
        self.assertEqual(ds.atk, 6)     # EoT 永久增益跨战斗保留


# ══════════════════ BG32_MagicItem_231 Gilded Anchor ══════════════

class TestGildedAnchor(unittest.TestCase):
    TID = "BG32_MagicItem_231"

    def test_eot_buffs_only_golden_minions(self):
        g = make_game(seed=141)
        a, b = g.heroes
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        golden = g.create_minion(MURLOC, controller=a, golden=True)
        g.summon(a, golden, 0)
        plain = put(g, a, MURLOC, 1)
        gold_b = g.create_minion(MURLOC, controller=b, golden=True)
        g.summon(b, gold_b, 0)
        g_atk, g_hp = golden.atk, golden.max_health
        b_atk, b_hp = gold_b.atk, gold_b.max_health
        g.run_script_hook(a.trinkets[0], "end_of_turn")
        self.assertEqual((golden.atk, golden.max_health),
                         (g_atk + d.num(0), g_hp + d.num(1)))
        self.assertEqual((plain.atk, plain.max_health), (2, 2))
        # owner 隔离: 对手金色随从不变
        self.assertEqual((gold_b.atk, gold_b.max_health), (b_atk, b_hp))

    def test_no_golden_whiffs(self):
        g = make_game(seed=142)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        put(g, a, MURLOC, 0)
        self.assertIsNone(
            g.run_script_hook(a.trinkets[0], "end_of_turn"))


# ══════════════════ BG32_MagicItem_276 Enigmatic Headstone ══════════════

class TestEnigmaticHeadstone(unittest.TestCase):
    TID = "BG32_MagicItem_276"

    def test_eot_undead_aura_stacks_and_covers_new_minions(self):
        g = make_game(seed=151)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        undead = put(g, a, UNDEAD, 0)
        murloc = put(g, a, MURLOC, 1)
        put(g, b, UNDEAD, 0)
        g.run_script_hook(a.trinkets[0], "end_of_turn")
        self.assertEqual(a.race_auras.get(Race.UNDEAD), (2, 0))
        self.assertEqual(undead.atk, 6)
        self.assertEqual(murloc.atk, 2)
        # 之后新召唤的亡灵同样享受（wherever they are）
        new = put(g, a, UNDEAD, 2)
        self.assertEqual(new.atk, 6)
        # 每回合 repeat → 叠加
        g.run_script_hook(a.trinkets[0], "end_of_turn")
        self.assertEqual(a.race_auras.get(Race.UNDEAD), (4, 0))
        # owner 隔离
        self.assertIsNone(getattr(b, "race_auras", None))


# ══════════════════ BG32_MagicItem_281 Wizard's Pipe ══════════════

class TestWizardsPipe(unittest.TestCase):
    TID = "BG32_MagicItem_281"

    def _spell_for(self, g, hero):
        s = g.create_spell(SPELL_BENIGN, controller=hero)
        hero.add_to_hand(s)
        return s

    def test_tavern_spell_buffs_no_type_minions(self):
        g = make_game(seed=161)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        no_type = put(g, a, NOTYPE, 0)      # 1/1
        typed = put(g, a, MURLOC, 1)        # 2/2
        self.assertTrue(g.play_spell(a, self._spell_for(g, a)))
        self.assertEqual((no_type.atk, no_type.max_health), (5, 5))
        self.assertEqual((typed.atk, typed.max_health), (2, 2))

    def test_opponent_cast_does_not_trigger(self):
        g = make_game(seed=162)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        no_type = put(g, a, NOTYPE, 0)
        self.assertTrue(g.play_spell(b, self._spell_for(g, b)))
        self.assertEqual((no_type.atk, no_type.max_health), (1, 1))

    def test_no_no_type_minion_whiffs(self):
        g = make_game(seed=163)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        typed = put(g, a, MURLOC, 0)
        self.assertTrue(g.play_spell(a, self._spell_for(g, a)))
        self.assertEqual((typed.atk, typed.max_health), (2, 2))

    def test_non_pool_spell_does_not_trigger(self):
        g = make_game(seed=164)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        no_type = put(g, a, NOTYPE, 0)
        # 血宝石是定向法术且非池法术 → 不广播 tavern_spell_cast
        from hsrl2.actions.bloodgem import GetBloodGems
        g.run_actions(GetBloodGems(a, 1))
        gem = next(e for e in a.hand if e.card_id == "BG20_GEM")
        self.assertTrue(g.play_spell(a, gem, target=no_type))
        self.assertEqual((no_type.atk, no_type.max_health), (2, 2))


# ══════════════════ BG30_MagicItem_924 Booty Bay Brew ══════════════════

class TestBootyBayBrew(unittest.TestCase):
    TID = "BG30_MagicItem_924"

    def test_spend_gold_buffs_two_random_pirates(self):
        g = make_game(seed=171)
        a, b = g.heroes
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        p1 = put(g, a, PIRATE_A, 0)
        p2 = put(g, a, PIRATE_B, 1)
        p3 = put(g, a, PIRATE_C, 2)
        cat = put(g, a, MURLOC, 3)          # 非海盗
        a.gold = 10
        g.spend_gold(a, 3)
        changed = [m for m in (p1, p2, p3)
                   if (m.atk, m.max_health)
                   != (get_db().get(m.card_id).atk,
                       get_db().get(m.card_id).health)]
        self.assertEqual(len(changed), 2)
        total_atk = sum(m.atk - get_db().get(m.card_id).atk
                        for m in (p1, p2, p3))
        total_hp = sum(m.max_health - get_db().get(m.card_id).health
                       for m in (p1, p2, p3))
        self.assertEqual(total_atk, 2 * d.num(0))
        self.assertEqual(total_hp, 2 * d.num(1))
        self.assertEqual((cat.atk, cat.max_health), (2, 2))

    def test_second_spend_triggers_again(self):
        g = make_game(seed=172)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        p1 = put(g, a, PIRATE_A, 0)
        p2 = put(g, a, PIRATE_B, 1)
        a.gold = 10
        g.spend_gold(a, 3)
        g.spend_gold(a, 2)
        # 两次花费 → 每次给两个海盗（只有 2 个 → 两次都命中同一对）
        self.assertEqual(p1.atk, 3 + 2 * d.num(0))
        self.assertEqual(p2.atk, 4 + 2 * d.num(0))

    def test_opponent_spend_does_not_trigger(self):
        g = make_game(seed=173)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        p1 = put(g, a, PIRATE_A, 0)
        b.gold = 10
        g.spend_gold(b, 3)
        self.assertEqual((p1.atk, p1.max_health), (3, 3))

    def test_no_pirate_whiffs(self):
        g = make_game(seed=174)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        cat = put(g, a, MURLOC, 0)
        a.gold = 10
        g.spend_gold(a, 3)
        self.assertEqual((cat.atk, cat.max_health), (2, 2))


# ══════════════════ BG30_MagicItem_981 The Eye of Dalaran ══════════════

class TestEyeOfDalaran(unittest.TestCase):
    TID = "BG30_MagicItem_981"

    def test_no_type_death_grants_pool_tavern_spell(self):
        g = make_game(seed=181)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        before = spell_pool_sum(g)
        m = put(g, a, NOTYPE, 0)
        m.set(GameTag.HEALTH, 0)
        g.check_deaths()
        spells = [e for e in a.hand if isinstance(e, Spell)]
        self.assertEqual(len(spells), 1)
        self.assertTrue(get_db().get(spells[0].card_id).is_pool_spell)
        self.assertEqual(spell_pool_sum(g), before - 1)
        self.assertEqual([e for e in b.hand], [])

    def test_typed_death_does_not_trigger(self):
        g = make_game(seed=182)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        m = put(g, a, MURLOC, 0)
        m.set(GameTag.HEALTH, 0)
        g.check_deaths()
        self.assertEqual([e for e in a.hand if isinstance(e, Spell)], [])

    def test_opponent_no_type_death_does_not_trigger(self):
        g = make_game(seed=183)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        m = put(g, b, NOTYPE, 0)
        m.set(GameTag.HEALTH, 0)
        g.check_deaths()
        self.assertEqual([e for e in a.hand if isinstance(e, Spell)], [])


# ══════════════════ BG30_MagicItem_951 Lava Lamp ══════════════════

class TestLavaLamp(unittest.TestCase):
    TID = "BG30_MagicItem_951"

    def _elemental_ids(self, g):
        return [d.id for d in g.db.pool_minions()
                if d.race in (Race.ELEMENTAL, Race.ALL)]

    def test_threshold_counter_grants_random_elemental(self):
        g = make_game(seed=191)
        a, b = g.heroes
        d = get_db().get(self.TID)
        threshold = d.num(1)
        buy_trinket(g, a, self.TID)
        elem_ids = self._elemental_ids(g)
        before = pool_sum(g, elem_ids)
        for _ in range(threshold - 1):
            sell_fodder(g, a)
        self.assertEqual([e for e in a.hand if isinstance(e, Minion)], [])
        self.assertEqual(pool_sum(g, elem_ids), before)
        sell_fodder(g, a)
        drawn = [e for e in a.hand if isinstance(e, Minion)]
        self.assertEqual(len(drawn), 1)
        self.assertIn(drawn[0].race, (Race.ELEMENTAL, Race.ALL))
        self.assertEqual(pool_sum(g, elem_ids), before - 1)
        # 计数已清零: 再卖 threshold-1 个不再触发
        for _ in range(threshold - 1):
            sell_fodder(g, a)
        self.assertEqual(len([e for e in a.hand if isinstance(e, Minion)]), 1)

    def test_opponent_sells_do_not_count(self):
        g = make_game(seed=192)
        a, b = g.heroes
        d = get_db().get(self.TID)
        buy_trinket(g, a, self.TID)
        for _ in range(d.num(1)):
            sell_fodder(g, b)
        self.assertEqual([e for e in a.hand if isinstance(e, Minion)], [])


# ══════════════════ BG30_MagicItem_710 Fungalmancer Sticker ══════════════

class TestFungalmancerSticker(unittest.TestCase):
    TID = "BG30_MagicItem_710"

    def test_five_sells_grant_random_murloc(self):
        g = make_game(seed=201)
        a, b = g.heroes
        d = get_db().get(self.TID)
        threshold = d.num(0)
        buy_trinket(g, a, self.TID)
        murloc_ids = [dd.id for dd in g.db.pool_minions()
                      if dd.race in (Race.MURLOC, Race.ALL)]
        before = pool_sum(g, murloc_ids)
        for _ in range(threshold - 1):
            sell_fodder(g, a)
        self.assertEqual([e for e in a.hand if isinstance(e, Minion)], [])
        sell_fodder(g, a)
        drawn = [e for e in a.hand if isinstance(e, Minion)]
        self.assertEqual(len(drawn), 1)
        self.assertIn(drawn[0].race, (Race.MURLOC, Race.ALL))
        self.assertEqual(pool_sum(g, murloc_ids), before - 1)

    def test_opponent_sells_do_not_count(self):
        g = make_game(seed=202)
        a, b = g.heroes
        top = get_db().get(self.TID).num(0)
        buy_trinket(g, a, self.TID)
        for _ in range(top):
            sell_fodder(g, b)
        self.assertEqual([e for e in a.hand if isinstance(e, Minion)], [])


# ══════════════════ BG30_MagicItem_419 Exquisite Dishware ══════════════

class TestExquisiteDishware(unittest.TestCase):
    TID = "BG30_MagicItem_419"

    def test_one_random_minion_per_controlled_type(self):
        g = make_game(seed=211)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        put(g, a, MURLOC, 0)
        put(g, a, UNDEAD, 1)
        g.run_script_hook(a.trinkets[0], "end_of_turn")
        drawn = [e for e in a.hand if isinstance(e, Minion)]
        self.assertEqual(len(drawn), 2)
        self.assertTrue(any(m.race in (Race.MURLOC, Race.ALL)
                            for m in drawn))
        self.assertTrue(any(m.race in (Race.UNDEAD, Race.ALL)
                            for m in drawn))
        self.assertEqual([e for e in b.hand], [])

    def test_no_type_board_whiffs(self):
        g = make_game(seed=212)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        put(g, a, NOTYPE, 0)
        self.assertEqual(_controlled_types(a), ())
        self.assertIsNone(
            g.run_script_hook(a.trinkets[0], "end_of_turn"))
        self.assertEqual([e for e in a.hand if isinstance(e, Minion)], [])

    def test_all_type_minion_covers_every_standard_race(self):
        g = make_game(seed=213)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        put(g, a, ALL_MINION, 0)
        self.assertEqual(set(_controlled_types(a)), set(_ALL_MINION_RACES))
        g.run_script_hook(a.trinkets[0], "end_of_turn")
        drawn = [e for e in a.hand if isinstance(e, Minion)]
        # 37.0: 标准种族 11 族 > 手牌上限 10 → 第 11 只进 pending_hand_queue
        # （引擎满手排队语义 RULES §3.3）。断言覆盖 = 手牌 ∪ 排队。
        queued = [e for h, e in g.pending_hand_queue
                  if h is a and isinstance(e, Minion)]
        all_drawn = drawn + queued
        self.assertEqual(len(all_drawn), len(_ALL_MINION_RACES))
        for race in _ALL_MINION_RACES:
            self.assertTrue(
                any(m.race in (race, Race.ALL) for m in all_drawn),
                f"missing type {race}")

    def test_empty_board_whiffs(self):
        g = make_game(seed=214)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        self.assertIsNone(
            g.run_script_hook(a.trinkets[0], "end_of_turn"))


# ══════════════════ BG30_MagicItem_880 Feral Talisman ══════════════

class TestFeralTalisman(unittest.TestCase):
    TID = "BG30_MagicItem_880"

    def test_all_typed_minions_get_2_1(self):
        g = make_game(seed=221)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        murloc = put(g, a, MURLOC, 0)       # 2/2 → 4/3
        undead = put(g, a, UNDEAD, 1)       # 4/2 → 6/3
        amalgam = put(g, a, ALL_MINION, 2)  # 6/6 → 8/7
        put(g, b, MURLOC, 0)
        self.assertEqual((murloc.atk, murloc.max_health), (4, 3))
        self.assertEqual((undead.atk, undead.max_health), (6, 3))
        self.assertEqual((amalgam.atk, amalgam.max_health), (8, 7))
        # owner 隔离
        self.assertEqual((b.board[0].atk, b.board[0].max_health), (2, 2))

    def test_hand_and_future_minions_covered(self):
        g = make_game(seed=222)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        hand = g.create_minion(MURLOC, controller=a)
        a.add_to_hand(hand)
        self.assertEqual((hand.atk, hand.max_health), (4, 3))
        new = put(g, a, UNDEAD, 0)
        self.assertEqual((new.atk, new.max_health), (6, 3))


# ══════════════════ BG30_MagicItem_989 Artisanal Urn ══════════════

class TestArtisanalUrn(unittest.TestCase):
    TID = "BG30_MagicItem_989"

    def test_undead_aura_and_owner_isolation(self):
        g = make_game(seed=231)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        undead = put(g, a, UNDEAD, 0)       # 4/2 → 7/2
        murloc = put(g, a, MURLOC, 1)       # 2/2 不变
        b_undead = put(g, b, UNDEAD, 0)
        self.assertEqual(undead.atk, 7)
        self.assertEqual(murloc.atk, 2)
        self.assertEqual(b_undead.atk, 4)
        new = put(g, a, UNDEAD, 2)
        self.assertEqual(new.atk, 7)


# ══════════════════ BG30_MagicItem_979 Primordial Terrarium ════════════

class TestPrimordialTerrarium(unittest.TestCase):
    TID = "BG30_MagicItem_979"

    def _tavern_spell(self, g, hero, card_id=SPELL_COST2):
        s = g.create_spell(card_id, controller=hero)
        s.zone = Zone.TAVERN
        hero.tavern.append(s)
        return s

    def test_play_elemental_discounts_next_tavern_spell(self):
        g = make_game(seed=241)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        elem = g.create_minion(ELEMENTAL, controller=a)
        a.add_to_hand(elem)
        self.assertTrue(g.play_minion(a, elem))
        # 打出元素 → tag=1
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION), 1)
        # 真实购买 2 费酒馆法术 → 只花 1 金，tag 清零
        a.gold = 10
        cheap = self._tavern_spell(g, a)
        self.assertTrue(g.buy_from_tavern(a, cheap))
        self.assertEqual(a.gold, 9)
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION), 0)
        # 无折扣时恢复全价
        full = self._tavern_spell(g, a)
        self.assertTrue(g.buy_from_tavern(a, full))
        self.assertEqual(a.gold, 7)

    def test_discount_stacks_per_elemental(self):
        g = make_game(seed=244)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        for _ in range(2):
            m = g.create_minion(ELEMENTAL, controller=a)
            a.add_to_hand(m)
            self.assertTrue(g.play_minion(a, m))
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION), 2)
        a.gold = 10
        cheap = self._tavern_spell(g, a)       # 2 费 - 2 = 0
        self.assertTrue(g.buy_from_tavern(a, cheap))
        self.assertEqual(a.gold, 10)
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION), 0)

    def test_non_elemental_play_does_not_trigger(self):
        g = make_game(seed=242)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        m = g.create_minion(MURLOC, controller=a)
        a.add_to_hand(m)
        self.assertTrue(g.play_minion(a, m))
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0), 0)

    def test_opponent_elemental_does_not_trigger(self):
        g = make_game(seed=243)
        a, b = g.heroes
        buy_trinket(g, a, self.TID)
        m = g.create_minion(ELEMENTAL, controller=b)
        b.add_to_hand(m)
        self.assertTrue(g.play_minion(b, m))
        self.assertEqual(a.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0), 0)


# ══════════════ BG30_MagicItem_705 Bartend-o-Tron's Oilcan ══════════════

class TestBartendOTronOilcan(unittest.TestCase):
    TID = "BG30_MagicItem_705"

    def test_bind_and_each_turn_reduce_upgrade_cost(self):
        g = make_game(seed=251)
        a, b = g.heroes
        base = a.upgrade_cost
        base_b = b.upgrade_cost
        buy_trinket(g, a, self.TID)
        self.assertEqual(a.get(GameTag.UPGRADE_COST_MOD), -3)
        # 真实升级少付 3 金
        a.gold = 20
        cost = max(0, base - 3)
        self.assertTrue(g.upgrade_tavern(a))
        self.assertEqual(a.gold, 20 - cost)
        self.assertEqual(a.tavern_tier, 2)
        # 每回合开始重复（累计 -6）
        g.run_script_hook(a.trinkets[0], "start_of_turn")
        self.assertEqual(a.get(GameTag.UPGRADE_COST_MOD), -6)
        # owner 隔离
        self.assertEqual(b.get(GameTag.UPGRADE_COST_MOD, 0), 0)
        self.assertEqual(b.upgrade_cost, base_b)

    def test_next_turn_start_hook_through_begin_recruit(self):
        g = make_game(seed=252)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        g.end_recruit_phase()          # 新回合 _begin_recruit_for → SoT
        self.assertEqual(a.get(GameTag.UPGRADE_COST_MOD), -6)


# ══════════════════ BG30_MagicItem_841 Glowing Gauntlet ══════════════

class TestGlowingGauntlet(unittest.TestCase):
    TID = "BG30_MagicItem_841"

    def test_tavern_buff_and_offer_override(self):
        g = make_game(seed=261)
        a, b = g.heroes
        d = get_db().get(self.TID)
        b_before = [(m.card_id, m.atk, m.max_health)
                    for m in b.tavern if isinstance(m, Minion)]
        buy_trinket(g, a, self.TID)
        a.gold = 10
        g.refresh_tavern(a)
        a_minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertEqual(len(a_minions), 7)      # override 读取点生效
        for m in a_minions:
            base = get_db().get(m.card_id)
            self.assertEqual((m.atk, m.max_health),
                             (base.atk + d.num(0),
                              base.health + d.num(1)))
        # 持久面: 再次刷新，新入馆随从同样获得
        g.refresh_tavern(a)
        a_minions2 = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertEqual(len(a_minions2), 7)
        for m in a_minions2:
            base = get_db().get(m.card_id)
            self.assertEqual((m.atk, m.max_health),
                             (base.atk + d.num(0),
                              base.health + d.num(1)))
        # owner 隔离（数值面 hero 作用域）: 对手酒馆随从不变
        b_after = [(m.card_id, m.atk, m.max_health)
                   for m in b.tavern if isinstance(m, Minion)]
        self.assertEqual(b_after, b_before)


# ══════════════════ BG32_MagicItem_284 Aggem Sticker ══════════════

class TestAggemSticker(unittest.TestCase):
    TID = "BG32_MagicItem_284"

    def test_blood_gems_on_one_minion_per_type(self):
        g = make_game(seed=271)
        a, b = g.heroes
        d = get_db().get(self.TID)
        gem = get_db().get("BG20_GEM")
        gem_atk, gem_hp = gem.num(0), gem.num(1)
        buy_trinket(g, a, self.TID)
        murloc = put(g, a, MURLOC, 0)       # 2/2
        undead = put(g, a, UNDEAD, 1)       # 4/2
        no_type = put(g, a, NOTYPE, 2)      # 1/1
        put(g, b, MURLOC, 0)
        g.run_script_hook(a.trinkets[0], "end_of_turn")
        n = d.num(0)
        self.assertEqual((murloc.atk, murloc.max_health),
                         (2 + n * gem_atk, 2 + n * gem_hp))
        self.assertEqual((undead.atk, undead.max_health),
                         (4 + n * gem_atk, 2 + n * gem_hp))
        self.assertEqual(murloc.get(GameTag.GEMS_PLAYED_ON), n)
        self.assertEqual(undead.get(GameTag.GEMS_PLAYED_ON), n)
        # 无类型不是类型 → 不受影响
        self.assertEqual((no_type.atk, no_type.max_health), (1, 1))
        self.assertEqual(no_type.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        # owner 隔离
        self.assertEqual((b.board[0].atk, b.board[0].max_health), (2, 2))

    def test_two_eot_stack_gem_counts(self):
        g = make_game(seed=272)
        a = g.heroes[0]
        d = get_db().get(self.TID)
        gem = get_db().get("BG20_GEM")
        buy_trinket(g, a, self.TID)
        murloc = put(g, a, MURLOC, 0)
        g.run_script_hook(a.trinkets[0], "end_of_turn")
        g.run_script_hook(a.trinkets[0], "end_of_turn")
        n = 2 * d.num(0)
        self.assertEqual(murloc.get(GameTag.GEMS_PLAYED_ON), n)
        self.assertEqual((murloc.atk, murloc.max_health),
                         (2 + n * gem.num(0), 2 + n * gem.num(1)))

    def test_empty_board_whiffs(self):
        g = make_game(seed=273)
        a = g.heroes[0]
        buy_trinket(g, a, self.TID)
        self.assertIsNone(
            g.run_script_hook(a.trinkets[0], "end_of_turn"))


if __name__ == "__main__":
    unittest.main()
