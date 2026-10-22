"""批次 trinkets8 行为层测试（21 张既有原语饰品）。

全部断言走真实引擎路径:
  - 购买: 真实 `game._offer_trinkets` 三选一 + PendingChoice.choose
    （resolve 回调扣费 → hero.trinkets → run_script_hook(on_bind)）
  - SoT/EoT: 真实 `game.end_recruit_phase()`
  - SoC / 战斗: 真实 `game.run_combat(a, b)`（战斗内探针读 SoC 结算后
    或事件流）
  - 召唤: 真实 `game.summon`（战斗内/招募期分别驱动）
  - 购买: 真实 `game.buy_from_tavern`
  - 圣盾移除: 真实 `hsrl2.actions.LoseKeyword`（DIVINE_SHIELD_LOST）
  - 攻击: 真实 `hsrl2.combat.execute_immediate_attack`（BEFORE_ATTACK）
  - 刷新: 真实 `game.refresh_tavern`
  - 死亡/Avenge: 真实 `game._process_single_death`（in_combat 探针）
  - 法术/随从打出: 真实 `game.play_spell` / `game.play_minion`
  - 池: `minion_pool.available` / `spell_pool.available` 前后差

覆盖（SOP §16 空转测试判定法——每个效果类都有正对照 + 无饰品对照）:
  - owner 隔离（2 英雄; 每个效果都有"对手活动不生效"断言）
  - 每回合/每场战斗语义（SoT 重复发放、每回合/每场额度与重置）
  - 池占返（随机获取占池、Discover 三选一预留/释放、token 不占池、
    指定池随从占池）
  - 数值与 CardDef.num 双向钉死
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Buff, GainKeyword, LoseKeyword
from hsrl2.actions.bloodgem import BLOOD_GEM_VARIANTS
from hsrl2.combat import execute_immediate_attack
from hsrl2.db import CardDB
from hsrl2.events import BEFORE_ATTACK, START_OF_COMBAT, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_trinkets8 as B8
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有卡（CardDB 按名核实，非凭记忆 id）
ELEMENTAL = "BG31_816"        # Fire Baller 4/3 T2 元素（无关键词）
NON_ELEMENTAL = "BG33_140"    # River Skipper 1/1 T1 鱼人（无关键词）
MURLOC = "BG33_140"           # River Skipper T1 鱼人（无关键词）
NON_MURLOC = "BG26_146"       # Lullabot 2/2 T1 机械（magnetic）
MECH = "BG31_177"             # Mechagnome Interpreter 3/1 T2 机械（无关键词）
BEAST = "BG36_206"            # Snarky Shark 4/5 T4 野兽（无关键词）
NON_BEAST = "BG26_146"        # Lullabot T1 机械
DRAGON = "BG35_814"           # Scarlet Survivor 3/3 T1 龙（无关键词）
NON_DRAGON = "BG33_140"       # River Skipper T1 鱼人
NAGA = "BG23_000"             # Mini-Myrmidon 1/4 T1 纳迦
BATTLECRY_1 = "BG26_135"      # Southsea Busker 3/1 T1 海盗（战吼）
BATTLECRY_2 = "BG31_330"      # Ominous Seer 2/1 T1 纳迦（战吼）
PLAIN_1 = "BG33_140"          # River Skipper（无关键词）
PLAIN_2 = "BG26_146"          # Lullabot（机械，无战吼）
RALLY_MINION = "BG20_101"     # Roadboar T2 野猪人（Rally 关键词）
TARGET_TAVERN = "BG36_211"    # Cage Gnawer 2/7 T4 野兽（酒馆注入靶）
BASSGILL = "BG26_350"         # BG32_MagicItem_301 evolution 链目标（token）
BUTCHERING = "BG28_604"       # BG30_MagicItem_406 evolution 链目标（token）
SELLEMENTAL = "BGS_115"       # BG32_MagicItem_831 evolution 链目标（池随从）
SPELL_PLAIN = "BG28_800"      # Careful Investment（池法术，无定向）
SPELL_TARGET = "BG28_503"     # Fortify（定向 T1 池法术）

_db = None


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 900):
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def offer_and_buy(game, hero, tid: str, kind: str):
    """真实饰品商店路径: _offer_trinkets → PendingChoice → resolve。"""
    hero.gold = 50
    game._offer_trinkets(hero, kind)
    choice = game.pending_choices.pop(0)
    choice.options = [get_db().get(tid)]
    choice.choose(0)
    return hero.trinkets[-1]


def offer_and_abandon(game, hero, kind: str):
    """同一 rng 消耗路径但不获得饰品（对照用——保持两局 rng 状态一致）。"""
    hero.gold = 50
    game._offer_trinkets(hero, kind)
    choice = game.pending_choices.pop(0)
    choice.choose(len(choice.options) - 1)   # 末位 = None（放弃）


def probe(scripts: dict):
    return type("Probe", (), dict(scripts))


def probe_minion(hook: str, bucket: list, *, atk=1, health=5) -> Minion:
    m = Minion(f"PROBE_{hook}", "P", atk=atk, health=health)
    m.scripts = probe({
        hook: staticmethod(lambda s, g, c=None, **kw: bucket.append(s) or None)})
    return m


def put(game, hero, m: Minion):
    assert game.summon(hero, m)
    return m


def play_from_hand(game, hero, card_id: str, *, spell: bool, target=None):
    """真实入手 + 打出路径（随从/法术）。"""
    if spell:
        assert game.spell_pool.acquire(card_id)
        e = game.create_spell(card_id, controller=hero)
        hero.add_to_hand(e)
        assert game.play_spell(hero, e, target=target)
    else:
        e = game.create_minion(card_id, controller=hero)
        hero.add_to_hand(e)
        assert game.play_minion(hero, e)
    return e


def death_in_combat(game, victim):
    """战斗内直接驱动死亡处理（真实 `_process_single_death` 路径）。"""
    prev = game.in_combat
    game.in_combat = True
    try:
        victim.health = 0
        game._process_single_death(victim)
    finally:
        game.in_combat = prev


def pool_sum(game, pred):
    return sum(game.minion_pool.available(d.id)
               for d in get_db().pool_minions() if pred(d))


def has_kw(d, kw):
    return kw in d.keywords


def race_in(race):
    def pred(d):
        return d.race in (race, Race.ALL)
    return pred


class TestRegistryState(unittest.TestCase):
    """注册面 + 文本/数据一致性（结构性，@engine-only 语义——与钩子无关）。"""

    IMPLEMENTED = (
        "BG30_MagicItem_982", "BG30_MagicItem_545", "BG35_MagicItem_851",
        "BG36_MagicItem_850", "BG32_MagicItem_930", "BG32_MagicItem_171",
        "BG30_MagicItem_910", "BG32_MagicItem_363", "BG30_MagicItem_886",
        "BG30_MagicItem_540", "BG30_MagicItem_978", "BG32_MagicItem_301",
        "BG32_MagicItem_306", "BG36_MagicItem_213", "BG35_MagicItem_752",
        "BG30_MagicItem_406", "BG32_MagicItem_831", "BG32_MagicItem_415",
        "BG30_MagicItem_973", "BG35_MagicItem_862", "BG35_MagicItem_434",
    )
    KIND = {
        "BG30_MagicItem_982": "lesser", "BG30_MagicItem_545": "greater",
        "BG35_MagicItem_851": "lesser", "BG36_MagicItem_850": "greater",
        "BG32_MagicItem_930": "lesser", "BG32_MagicItem_171": "greater",
        "BG30_MagicItem_910": "greater", "BG32_MagicItem_363": "greater",
        "BG30_MagicItem_886": "greater", "BG30_MagicItem_540": "greater",
        "BG30_MagicItem_978": "lesser", "BG32_MagicItem_301": "greater",
        "BG32_MagicItem_306": "greater", "BG36_MagicItem_213": "greater",
        "BG35_MagicItem_752": "greater", "BG30_MagicItem_406": "greater",
        "BG32_MagicItem_831": "lesser", "BG32_MagicItem_415": "greater",
        "BG30_MagicItem_973": "lesser", "BG35_MagicItem_862": "greater",
        "BG35_MagicItem_434": "lesser",
    }
    CLASSES = {
        "BG30_MagicItem_982": "ShamanPrayerBeadsScript",
        "BG30_MagicItem_545": "FridgeMagnetScript",
        "BG35_MagicItem_851": "WaterWheelScript",
        "BG36_MagicItem_850": "CookiesStirringRodScript",
        "BG32_MagicItem_930": "ArchaicScrollScript",
        "BG32_MagicItem_171": "DivineSignetScript",
        "BG30_MagicItem_910": "MechagonAdapterScript",
        "BG32_MagicItem_363": "FaerieDragonScaleScript",
        "BG30_MagicItem_886": "ReinforcedShieldScript",
        "BG30_MagicItem_540": "SlammaStickerScript",
        "BG30_MagicItem_978": "BlingtronsSunglassesScript",
        "BG32_MagicItem_301": "BassgillPortraitScript",
        "BG32_MagicItem_306": "HeraldStickerScript",
        "BG36_MagicItem_213": "LightfeatherStickerScript",
        "BG35_MagicItem_752": "YoungMurkEyeStickerScript",
        "BG30_MagicItem_406": "ButchersSickleScript",
        "BG32_MagicItem_831": "SellementalPortraitScript",
        "BG32_MagicItem_415": "BattleHornScript",
        "BG30_MagicItem_973": "MinionBaitScript",
        "BG35_MagicItem_862": "UpstartEmbersScript",
        "BG35_MagicItem_434": "JewelryBoxScript",
    }

    def test_registry_all_registered(self):
        self.assertEqual(len(self.IMPLEMENTED), 21)
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)
            self.assertIs(REGISTRY[tid], getattr(B8, self.CLASSES[tid]), tid)
            self.assertIsNotNone(get_db().get(tid), tid)

    def test_offer_pool_membership(self):
        db = get_db()
        offer_ids = {d.id for d in db.trinket_offer_pool()}
        for tid, kind in self.KIND.items():
            self.assertIn(tid, offer_ids, tid)
            school = 11 if kind == "lesser" else 12
            self.assertEqual(db.get(tid).spell_school, school, tid)

    def test_card_definition_params(self):
        db = get_db()
        self.assertEqual(db.get("BG30_MagicItem_982").num(0), 2)
        self.assertEqual(db.get("BG30_MagicItem_545").num(0), 3)
        self.assertEqual(db.get("BG35_MagicItem_851").num(0), 2)
        self.assertEqual(db.get("BG36_MagicItem_850").num(0), 5)
        self.assertEqual(db.get("BG32_MagicItem_930").num(1), 8)   # 37.0: 7→8
        self.assertEqual(db.get("BG32_MagicItem_171").num(1), 4)
        self.assertEqual(db.get("BG30_MagicItem_910").num(0), 3)
        self.assertEqual(db.get("BG32_MagicItem_363").num(1), 3)
        self.assertEqual(db.get("BG30_MagicItem_886").num(1), 5)
        self.assertEqual(db.get("BG30_MagicItem_973").num(0), Race.NAGA)

    def test_avenge_thresholds_match(self):
        # Avenge 阈值是类属性（import 期无法读 CardDef）→ 测试钉死
        self.assertEqual(B8.FridgeMagnetScript.avenge_threshold,
                         get_db().get("BG30_MagicItem_545").num(0))
        self.assertEqual(B8.BattleHornScript.avenge_threshold, 2)

    def test_carddef_evolution_chain(self):
        db = get_db()
        pairs = {
            "BG32_MagicItem_301": (BASSGILL, False),
            "BG30_MagicItem_406": (BUTCHERING, False),
            "BG32_MagicItem_831": (SELLEMENTAL, True),
        }
        for tid, (target, is_pool) in pairs.items():
            d = db.get(tid)
            self.assertIsNotNone(d.evolution_card_id, tid)
            token = db.by_dbf(d.evolution_card_id)
            self.assertIsNotNone(token, tid)
            self.assertEqual(token.id, target, tid)
            self.assertEqual(token.is_pool_minion, is_pool, tid)


# ══════════════ BG30_MagicItem_982 Shaman Prayer Beads ══════════════

class TestShamanPrayerBeads(unittest.TestCase):
    TID = "BG30_MagicItem_982"

    def _buy(self, g, hero, card_id):
        m = g.inject_tavern_minion(hero, card_id)
        hero.gold = 50
        self.assertTrue(g.buy_from_tavern(hero, m))

    def test_two_battlecries_grant_random_battlecry(self):
        g = make_game(seed=2001)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        before = pool_sum(g, lambda d: has_kw(d, "battlecry"))
        self._buy(g, a, BATTLECRY_1)                 # 第 1 个 → 未达标
        self.assertEqual(len(a.hand), 1)
        self._buy(g, a, BATTLECRY_2)                 # 第 2 个 → 发放
        self.assertEqual(len(a.hand), 3)
        granted = a.hand[-1]
        self.assertTrue(
            has_kw(get_db().get(granted.card_id), "battlecry"))
        self.assertEqual(
            pool_sum(g, lambda d: has_kw(d, "battlecry")), before - 1)

    def test_non_battlecry_purchases_not_counted(self):
        g = make_game(seed=2002)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        self._buy(g, a, PLAIN_1)
        self._buy(g, a, PLAIN_2)
        self.assertEqual(len(a.hand), 2)             # 无发放

    def test_control_without_trinket(self):
        g = make_game(seed=2003)
        a = g.heroes[0]
        self._buy(g, a, BATTLECRY_1)
        self._buy(g, a, BATTLECRY_2)
        self.assertEqual(len(a.hand), 2)

    def test_opponent_battlecries_not_counted(self):
        g = make_game(seed=2004)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        self._buy(g, b, BATTLECRY_1)
        self._buy(g, b, BATTLECRY_2)
        self.assertEqual(a.hand, [])                 # owner 隔离


# ══════════════ BG30_MagicItem_545 Fridge Magnet ══════════════

class TestFridgeMagnet(unittest.TestCase):
    TID = "BG30_MagicItem_545"

    def _kill(self, g, hero, n):
        victims = [put(g, hero, g.create_minion(PLAIN_1, controller=hero))
                   for _ in range(n)]
        for v in victims:
            death_in_combat(g, v)

    def test_avenge_grants_magnetic_minion(self):
        g = make_game(seed=2011)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        n = get_db().get(self.TID).num(0)
        before = pool_sum(g, lambda d: has_kw(d, "magnetic"))
        self._kill(g, a, n)
        self.assertEqual(len(a.hand), 1)
        self.assertTrue(
            has_kw(get_db().get(a.hand[0].card_id), "magnetic"))
        self.assertEqual(
            pool_sum(g, lambda d: has_kw(d, "magnetic")), before - 1)

    def test_below_threshold_whiffs(self):
        g = make_game(seed=2012)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        n = get_db().get(self.TID).num(0)
        self._kill(g, a, n - 1)
        self.assertEqual(a.hand, [])

    def test_control_without_trinket(self):
        g = make_game(seed=2013)
        a = g.heroes[0]
        n = get_db().get(self.TID).num(0)
        self._kill(g, a, n)
        self.assertEqual(a.hand, [])

    def test_opponent_deaths_not_counted(self):
        g = make_game(seed=2014)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        n = get_db().get(self.TID).num(0)
        self._kill(g, b, n)
        self.assertEqual(a.hand, [])                 # owner 隔离


# ══════════════ BG35_MagicItem_851 Water Wheel ══════════════

class TestWaterWheel(unittest.TestCase):
    TID = "BG35_MagicItem_851"

    def test_elementals_grant_spells_up_to_turn_limit(self):
        g = make_game(seed=2021)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        limit = get_db().get(self.TID).num(0)
        before = g.spell_pool.total_remaining()
        for _ in range(limit):
            play_from_hand(g, a, ELEMENTAL, spell=False)
        spells = [e for e in a.hand if isinstance(e, Spell)]
        self.assertEqual(len(spells), limit)
        self.assertEqual(g.spell_pool.total_remaining(), before - limit)
        play_from_hand(g, a, ELEMENTAL, spell=False)   # 超额度
        self.assertEqual(len([e for e in a.hand if isinstance(e, Spell)]),
                         limit)

    def test_non_elemental_not_counted(self):
        g = make_game(seed=2022)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        play_from_hand(g, a, NON_ELEMENTAL, spell=False)
        self.assertEqual([e for e in a.hand if isinstance(e, Spell)], [])

    def test_turn_limit_resets(self):
        g = make_game(seed=2023)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        limit = get_db().get(self.TID).num(0)
        for _ in range(limit):
            play_from_hand(g, a, ELEMENTAL, spell=False)
        g.end_recruit_phase()                         # 真实推进回合
        play_from_hand(g, a, ELEMENTAL, spell=False)
        self.assertEqual(len([e for e in a.hand if isinstance(e, Spell)]),
                         limit + 1)

    def test_control_without_trinket(self):
        g = make_game(seed=2024)
        a = g.heroes[0]
        for _ in range(2):
            play_from_hand(g, a, ELEMENTAL, spell=False)
        self.assertEqual([e for e in a.hand if isinstance(e, Spell)], [])

    def test_opponent_elementals_not_counted(self):
        g = make_game(seed=2025)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        for _ in range(2):
            play_from_hand(g, b, ELEMENTAL, spell=False)
        self.assertEqual([e for e in a.hand if isinstance(e, Spell)], [])


# ══════════════ BG36_MagicItem_850 Cookie's Stirring Rod ══════════════

class TestCookiesStirringRod(unittest.TestCase):
    TID = "BG36_MagicItem_850"

    def test_five_murlocs_grant_two_spells(self):
        g = make_game(seed=2031)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        threshold = get_db().get(self.TID).num(0)
        before = g.spell_pool.total_remaining()
        for _ in range(threshold - 1):
            play_from_hand(g, a, MURLOC, spell=False)
        self.assertEqual([e for e in a.hand if isinstance(e, Spell)], [])
        play_from_hand(g, a, MURLOC, spell=False)     # 达阈值
        spells = [e for e in a.hand if isinstance(e, Spell)]
        self.assertEqual(len(spells), 2)
        self.assertEqual(g.spell_pool.total_remaining(), before - 2)

    def test_non_murlocs_not_counted(self):
        g = make_game(seed=2032)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        threshold = get_db().get(self.TID).num(0)
        for _ in range(threshold):
            play_from_hand(g, a, NON_MURLOC, spell=False)
        self.assertEqual([e for e in a.hand if isinstance(e, Spell)], [])

    def test_control_without_trinket(self):
        g = make_game(seed=2033)
        a = g.heroes[0]
        for _ in range(5):
            play_from_hand(g, a, MURLOC, spell=False)
        self.assertEqual([e for e in a.hand if isinstance(e, Spell)], [])

    def test_opponent_murlocs_not_counted(self):
        g = make_game(seed=2034)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        for _ in range(5):
            play_from_hand(g, b, MURLOC, spell=False)
        self.assertEqual([e for e in a.hand if isinstance(e, Spell)], [])


# ══════════════ BG32_MagicItem_930 Archaic Scroll ══════════════

class TestArchaicScroll(unittest.TestCase):
    TID = "BG32_MagicItem_930"

    def _cast(self, g, hero, n):
        for _ in range(n):
            play_from_hand(g, hero, SPELL_PLAIN, spell=True)

    def test_seven_spells_grant_naga(self):
        g = make_game(seed=2041)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        threshold = get_db().get(self.TID).num(1)
        before = pool_sum(g, race_in(Race.NAGA))
        self._cast(g, a, threshold - 1)
        self.assertEqual(a.hand, [])
        self._cast(g, a, 1)                           # 达阈值
        self.assertEqual(len(a.hand), 1)
        self.assertIn(get_db().get(a.hand[0].card_id).race,
                      (Race.NAGA, Race.ALL))
        self.assertEqual(pool_sum(g, race_in(Race.NAGA)), before - 1)
        self._cast(g, a, 1)                           # 计数已清零
        self.assertEqual(len(a.hand), 1)

    def test_double_cast_counts_each_cast(self):
        """双施（SPELL_DOUBLER）按**施放次数**计（2026-09-02 对抗审查:
        `card_played` 每次打出只广播一次 → 双施漏计）。"""
        from hsrl2.tags import GameTag
        g = make_game(seed=2044)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        threshold = get_db().get(self.TID).num(1)
        doubler = Minion("TEST_DBL", "D", atk=1, health=1)
        doubler.set(GameTag.SPELL_DOUBLER, True)
        self.assertTrue(g.summon(a, doubler))
        # SPELL_DOUBLER 只对"定向友方随从"的法术生效 → 用定向池法术
        # `BG28_897`（Tavern Dish Banana, +2/+2）指向 doubler 自身
        target = Minion("TEST_DBL_TGT", "T", atk=1, health=1)
        self.assertTrue(g.summon(a, target))
        for _ in range((threshold + 1) // 2 - 1):
            play_from_hand(g, a, "BG28_897", spell=True, target=target)
        self.assertEqual(a.hand, [])
        play_from_hand(g, a, "BG28_897", spell=True, target=target)
        self.assertEqual(len(a.hand), 1)
        self.assertIn(get_db().get(a.hand[0].card_id).race,
                      (Race.NAGA, Race.ALL))

    def test_control_without_trinket(self):
        g = make_game(seed=2042)
        a = g.heroes[0]
        self._cast(g, a, 7)
        self.assertEqual(a.hand, [])

    def test_opponent_spells_not_counted(self):
        g = make_game(seed=2043)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        self._cast(g, b, 7)
        self.assertEqual(a.hand, [])                  # owner 隔离


# ══════════════ BG32_MagicItem_171 Divine Signet ══════════════

class TestDivineSignet(unittest.TestCase):
    TID = "BG32_MagicItem_171"

    def _lose_shield(self, g, m):
        g.run_actions(LoseKeyword(m, GameTag.DIVINE_SHIELD))

    def test_shield_loss_grants_spell_up_to_combat_limit(self):
        g = make_game(seed=2051)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        limit = get_db().get(self.TID).num(1)
        m = put(g, a, g.create_minion(PLAIN_1, controller=a))
        m.set(GameTag.DIVINE_SHIELD, True)
        g.in_combat = True
        for _ in range(limit):
            self._lose_shield(g, m)
        spells = [e for e in a.hand if isinstance(e, Spell)]
        self.assertEqual(len(spells), limit)
        self._lose_shield(g, m)                       # 超额
        self.assertEqual(len([e for e in a.hand if isinstance(e, Spell)]),
                         limit)

    def test_limit_resets_on_start_of_combat(self):
        g = make_game(seed=2052)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        limit = get_db().get(self.TID).num(1)
        m = put(g, a, g.create_minion(PLAIN_1, controller=a))
        m.set(GameTag.DIVINE_SHIELD, True)
        g.in_combat = True
        for _ in range(limit):
            self._lose_shield(g, m)
        self._lose_shield(g, m)
        self.assertEqual(len([e for e in a.hand if isinstance(e, Spell)]),
                         limit)
        g.run_combat(a, b)                            # 真实 SoC 重置
        g.in_combat = True
        m.set(GameTag.DIVINE_SHIELD, True)
        self._lose_shield(g, m)
        self.assertEqual(len([e for e in a.hand if isinstance(e, Spell)]),
                         limit + 1)

    def test_recruit_phase_loss_not_counted(self):
        g = make_game(seed=2053)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        m = put(g, a, g.create_minion(PLAIN_1, controller=a))
        m.set(GameTag.DIVINE_SHIELD, True)
        self.assertFalse(g.in_combat)
        self._lose_shield(g, m)
        self.assertEqual([e for e in a.hand if isinstance(e, Spell)], [])

    def test_opponent_shield_loss_not_counted(self):
        g = make_game(seed=2054)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        m = put(g, b, g.create_minion(PLAIN_1, controller=b))
        m.set(GameTag.DIVINE_SHIELD, True)
        g.in_combat = True
        self._lose_shield(g, m)
        self.assertEqual([e for e in a.hand if isinstance(e, Spell)], [])


# ══════════════ BG30_MagicItem_910 Mechagon Adapter ══════════════

class TestMechagonAdapter(unittest.TestCase):
    TID = "BG30_MagicItem_910"

    def test_mech_regains_shield_up_to_combat_limit(self):
        g = make_game(seed=2061)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        limit = get_db().get(self.TID).num(0)
        m = put(g, a, g.create_minion(MECH, controller=a))
        g.in_combat = True
        for i in range(limit):
            g.run_actions(LoseKeyword(m, GameTag.DIVINE_SHIELD))
            self.assertTrue(m.has(GameTag.DIVINE_SHIELD),
                            f"use {i + 1} should re-grant Divine Shield")
        g.run_actions(LoseKeyword(m, GameTag.DIVINE_SHIELD))
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))   # 额度耗尽

    def test_limit_resets_and_non_mech_whiffs(self):
        g = make_game(seed=2062)
        a, b = g.heroes
        trinket = offer_and_buy(g, a, self.TID, "greater")
        limit = get_db().get(self.TID).num(0)
        mech = put(g, a, g.create_minion(MECH, controller=a))
        plain = put(g, a, g.create_minion(PLAIN_1, controller=a))
        g.in_combat = True
        for _ in range(limit):
            g.run_actions(LoseKeyword(mech, GameTag.DIVINE_SHIELD))
        g.run_actions(LoseKeyword(mech, GameTag.DIVINE_SHIELD))
        self.assertFalse(mech.has(GameTag.DIVINE_SHIELD))
        # 非机械即使额度在也不授予
        plain.set(GameTag.DIVINE_SHIELD, True)
        g.run_actions(LoseKeyword(plain, GameTag.DIVINE_SHIELD))
        self.assertFalse(plain.has(GameTag.DIVINE_SHIELD))
        # 真实 SoC 重置
        g.run_combat(a, b)
        g.in_combat = True
        mech.clear(GameTag.DIVINE_SHIELD)
        g.run_actions(LoseKeyword(mech, GameTag.DIVINE_SHIELD))
        self.assertTrue(mech.has(GameTag.DIVINE_SHIELD))
        self.assertIsNotNone(trinket)

    def test_control_without_trinket(self):
        g = make_game(seed=2063)
        a = g.heroes[0]
        m = put(g, a, g.create_minion(MECH, controller=a))
        g.in_combat = True
        g.run_actions(LoseKeyword(m, GameTag.DIVINE_SHIELD))
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))

    def test_opponent_mech_not_granted(self):
        g = make_game(seed=2064)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        m = put(g, b, g.create_minion(MECH, controller=b))
        g.in_combat = True
        g.run_actions(LoseKeyword(m, GameTag.DIVINE_SHIELD))
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))   # owner 隔离


# ══════════════ BG32_MagicItem_363 Faerie Dragon Scale ══════════════

class TestFaerieDragonScale(unittest.TestCase):
    TID = "BG32_MagicItem_363"

    def _attack(self, g, dragon, defender):
        execute_immediate_attack(g, dragon, defender)

    def test_dragon_attack_grants_shield_up_to_limit(self):
        g = make_game(seed=2071)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        limit = get_db().get(self.TID).num(1)
        dragon = put(g, a, g.create_minion(DRAGON, controller=a))
        defender = put(g, b, g.create_minion(NON_DRAGON, controller=b))
        # 探针注册在饰品监听器**之后** → BEFORE_ATTACK 分发时读到授予后
        # 状态（圣盾在本次攻击的伤害结算前生效，随后被反击消耗）
        seen = []
        g.events.register(Listener(
            event=BEFORE_ATTACK, owner=a,
            callback=lambda gg, attacker=None, **kw: seen.append(
                dragon.has(GameTag.DIVINE_SHIELD))
            if attacker is dragon else None))
        g.in_combat = True
        for i in range(limit):
            dragon.clear(GameTag.DIVINE_SHIELD)
            self._attack(g, dragon, defender)
        self.assertEqual(seen, [True] * limit)
        dragon.clear(GameTag.DIVINE_SHIELD)
        self._attack(g, dragon, defender)
        self.assertFalse(seen[-1])                   # 额度耗尽

    def test_non_dragon_attack_whiffs(self):
        g = make_game(seed=2072)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        attacker = put(g, a, g.create_minion(NON_DRAGON, controller=a))
        defender = put(g, b, g.create_minion(NON_DRAGON, controller=b))
        g.in_combat = True
        self._attack(g, attacker, defender)
        self.assertFalse(attacker.has(GameTag.DIVINE_SHIELD))

    def test_control_without_trinket(self):
        g = make_game(seed=2073)
        a, b = g.heroes
        dragon = put(g, a, g.create_minion(DRAGON, controller=a))
        defender = put(g, b, g.create_minion(NON_DRAGON, controller=b))
        g.in_combat = True
        self._attack(g, dragon, defender)
        self.assertFalse(dragon.has(GameTag.DIVINE_SHIELD))

    def test_opponent_dragon_not_granted(self):
        g = make_game(seed=2074)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        dragon = put(g, b, g.create_minion(DRAGON, controller=b))
        defender = put(g, a, g.create_minion(NON_DRAGON, controller=a))
        g.in_combat = True
        self._attack(g, dragon, defender)
        self.assertFalse(dragon.has(GameTag.DIVINE_SHIELD))  # owner 隔离


# ══════════════ BG30_MagicItem_886 Reinforced Shield ══════════════

class TestReinforcedShield(unittest.TestCase):
    TID = "BG30_MagicItem_886"

    def test_combat_summons_get_shield_up_to_limit(self):
        g = make_game(seed=2081)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        limit = get_db().get(self.TID).num(1)
        g.in_combat = True
        granted = 0
        for _ in range(limit):
            m = g.create_minion(PLAIN_1, controller=a)
            g.summon(a, m)
            if m.has(GameTag.DIVINE_SHIELD):
                granted += 1
        self.assertEqual(granted, limit)
        extra = g.create_minion(PLAIN_2, controller=a)
        g.summon(a, extra)
        self.assertFalse(extra.has(GameTag.DIVINE_SHIELD))   # 额度耗尽

    def test_recruit_phase_summons_not_granted(self):
        g = make_game(seed=2082)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        self.assertFalse(g.in_combat)
        m = g.create_minion(PLAIN_1, controller=a)
        g.summon(a, m)
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))

    def test_control_without_trinket(self):
        g = make_game(seed=2083)
        a = g.heroes[0]
        g.in_combat = True
        m = g.create_minion(PLAIN_1, controller=a)
        g.summon(a, m)
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))

    def test_opponent_summons_not_granted(self):
        g = make_game(seed=2084)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        g.in_combat = True
        m = g.create_minion(PLAIN_1, controller=b)
        g.summon(b, m)
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))       # owner 隔离


# ══════════════ BG30_MagicItem_540 Slamma Sticker ══════════════

class TestSlammaSticker(unittest.TestCase):
    TID = "BG30_MagicItem_540"

    def test_combat_beast_summon_doubles_attack(self):
        g = make_game(seed=2091)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        g.in_combat = True
        m = g.create_minion(BEAST, controller=a)
        base = get_db().get(BEAST).atk
        self.assertEqual(base, 4)
        g.summon(a, m)
        self.assertEqual(m.atk, base * 2)

    def test_recruit_phase_summon_not_doubled(self):
        g = make_game(seed=2092)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        self.assertFalse(g.in_combat)
        m = g.create_minion(BEAST, controller=a)
        g.summon(a, m)
        self.assertEqual(m.atk, get_db().get(BEAST).atk)

    def test_non_beast_not_doubled(self):
        g = make_game(seed=2093)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        g.in_combat = True
        m = g.create_minion(NON_BEAST, controller=a)
        g.summon(a, m)
        self.assertEqual(m.atk, get_db().get(NON_BEAST).atk)

    def test_control_without_trinket(self):
        g = make_game(seed=2094)
        a = g.heroes[0]
        g.in_combat = True
        m = g.create_minion(BEAST, controller=a)
        g.summon(a, m)
        self.assertEqual(m.atk, get_db().get(BEAST).atk)

    def test_opponent_beast_not_doubled(self):
        g = make_game(seed=2095)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        g.in_combat = True
        m = g.create_minion(BEAST, controller=b)
        g.summon(b, m)
        self.assertEqual(m.atk, get_db().get(BEAST).atk)     # owner 隔离


# ══════════════ BG30_MagicItem_978 Blingtron's Sunglasses ══════════════

class TestBlingtronsSunglasses(unittest.TestCase):
    TID = "BG30_MagicItem_978"

    def test_combat_mech_summon_shields_a_friendly_mech(self):
        g = make_game(seed=2101)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        put(g, a, g.create_minion(BEAST, controller=a))   # 非机械宿主
        g.in_combat = True
        m = g.create_minion(MECH, controller=a)
        g.summon(a, m)
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))

    def test_recruit_phase_summon_not_triggered(self):
        g = make_game(seed=2102)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertFalse(g.in_combat)
        m = g.create_minion(MECH, controller=a)
        g.summon(a, m)
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))

    def test_summoning_non_mech_not_triggered(self):
        g = make_game(seed=2103)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        g.in_combat = True
        mech = put(g, a, g.create_minion(MECH, controller=a))
        mech.clear(GameTag.DIVINE_SHIELD)                # 清掉自身召唤授予
        beast = g.create_minion(BEAST, controller=a)
        g.summon(a, beast)
        self.assertFalse(mech.has(GameTag.DIVINE_SHIELD))

    def test_control_without_trinket(self):
        g = make_game(seed=2104)
        a = g.heroes[0]
        g.in_combat = True
        m = g.create_minion(MECH, controller=a)
        g.summon(a, m)
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))

    def test_opponent_mech_summon_not_granting(self):
        g = make_game(seed=2105)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        g.in_combat = True
        mine = put(g, a, g.create_minion(MECH, controller=a))
        mine.clear(GameTag.DIVINE_SHIELD)                # 清掉自身召唤授予
        m = g.create_minion(MECH, controller=b)
        g.summon(b, m)
        self.assertFalse(mine.has(GameTag.DIVINE_SHIELD))    # owner 隔离
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))


# ══════════════ BG32_MagicItem_301 Bassgill Portrait ══════════════

class TestBassgillPortrait(unittest.TestCase):
    TID = "BG32_MagicItem_301"

    def test_bind_grants_bassgill_and_combat_murlocs_shielded(self):
        g = make_game(seed=2111)
        a, b = g.heroes
        before = g.minion_pool.total_remaining()
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual([e.card_id for e in a.hand], [BASSGILL])
        self.assertEqual(g.minion_pool.total_remaining(), before)  # token
        g.in_combat = True
        m = g.create_minion(MURLOC, controller=a)
        g.summon(a, m)
        self.assertTrue(m.has(GameTag.DIVINE_SHIELD))
        self.assertEqual(b.hand, [])

    def test_recruit_phase_murloc_not_shielded(self):
        g = make_game(seed=2112)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        self.assertFalse(g.in_combat)
        m = g.create_minion(MURLOC, controller=a)
        g.summon(a, m)
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))

    def test_non_murloc_not_shielded(self):
        g = make_game(seed=2113)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        g.in_combat = True
        m = g.create_minion(NON_MURLOC, controller=a)
        g.summon(a, m)
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))

    def test_control_without_trinket(self):
        g = make_game(seed=2114)
        a = g.heroes[0]
        self.assertEqual(a.hand, [])
        g.in_combat = True
        m = g.create_minion(MURLOC, controller=a)
        g.summon(a, m)
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))

    def test_opponent_murloc_not_shielded(self):
        g = make_game(seed=2115)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        g.in_combat = True
        m = g.create_minion(MURLOC, controller=b)
        g.summon(b, m)
        self.assertFalse(m.has(GameTag.DIVINE_SHIELD))       # owner 隔离


# ══════════════ BG32_MagicItem_306 Herald Sticker ══════════════

class TestHeraldSticker(unittest.TestCase):
    TID = "BG32_MagicItem_306"

    def _soc(self, seed, with_trinket, owner="a"):
        g = make_game(seed=seed)
        a, b = g.heroes
        target = a if owner == "a" else b
        if with_trinket:
            offer_and_buy(g, a, self.TID, "greater")
        calls = []
        probes = []
        for _ in range(2):
            m = probe_minion("deathrattle", calls, atk=0, health=50)
            put(g, target, m)
            probes.append(m)
        plain = probe_minion("rally", calls, atk=0, health=50)
        put(g, target, plain)
        g.run_combat(a, b)
        return calls, probes, plain

    def test_all_friendly_deathrattles_trigger(self):
        calls, probes, plain = self._soc(2121, with_trinket=True)
        self.assertEqual(calls.count(probes[0]), 1)
        self.assertEqual(calls.count(probes[1]), 1)
        self.assertEqual(calls.count(plain), 0)      # 非亡语不触发

    def test_control_without_trinket(self):
        calls, probes, _ = self._soc(2122, with_trinket=False)
        self.assertEqual(calls, [])

    def test_opponent_deathrattles_not_triggered(self):
        calls, probes, _ = self._soc(2123, with_trinket=True, owner="b")
        self.assertEqual(calls, [])                  # owner 隔离


# ══════════════ BG36_MagicItem_213 Lightfeather Sticker ══════════════

class TestLightfeatherSticker(unittest.TestCase):
    TID = "BG36_MagicItem_213"

    def _soc(self, seed, with_trinket, owner="a"):
        g = make_game(seed=seed)
        a, b = g.heroes
        target = a if owner == "a" else b
        if with_trinket:
            offer_and_buy(g, a, self.TID, "greater")
        rally = put(g, target, g.create_minion(RALLY_MINION,
                                               controller=target))
        other = put(g, target, g.create_minion(BEAST, controller=target))
        seen = {}
        g.events.register(Listener(
            event=START_OF_COMBAT, owner=a,
            callback=lambda gg, hero=None, **kw: seen.update(
                {"rally": rally.has(GameTag.DIVINE_SHIELD),
                 "other": other.has(GameTag.DIVINE_SHIELD)})
            if hero is target else None))
        g.run_combat(a, b)
        return seen

    def test_rally_minions_get_shield(self):
        seen = self._soc(2131, with_trinket=True)
        self.assertTrue(seen["rally"])
        self.assertFalse(seen["other"])              # 非 Rally 不授予

    def test_control_without_trinket(self):
        seen = self._soc(2132, with_trinket=False)
        self.assertFalse(seen["rally"])

    def test_opponent_rally_not_granted(self):
        seen = self._soc(2133, with_trinket=True, owner="b")
        self.assertFalse(seen["rally"])              # owner 隔离


# ══════════════ BG35_MagicItem_752 Young Murk-Eye Sticker ══════════════

class TestYoungMurkEyeSticker(unittest.TestCase):
    TID = "BG35_MagicItem_752"

    def _eot(self, seed, with_trinket, owner="a"):
        g = make_game(seed=seed)
        a, b = g.heroes
        target = a if owner == "a" else b
        if with_trinket:
            offer_and_buy(g, a, self.TID, "greater")
        calls = []
        probes = []
        for _ in range(3):
            m = probe_minion("battlecry", calls, atk=0, health=40)
            put(g, target, m)
            probes.append(m)
        g.end_recruit_phase()
        return calls, probes

    def test_left_and_right_battlecries_trigger(self):
        calls, probes = self._eot(2141, with_trinket=True)
        self.assertEqual(calls.count(probes[0]), 1)
        self.assertEqual(calls.count(probes[2]), 1)
        self.assertEqual(calls.count(probes[1]), 0)  # 中间不触发

    def test_control_without_trinket(self):
        calls, probes = self._eot(2142, with_trinket=False)
        self.assertEqual(calls, [])

    def test_opponent_board_not_triggered(self):
        calls, probes = self._eot(2143, with_trinket=True, owner="b")
        self.assertEqual(calls, [])                  # owner 隔离


# ══════════════ BG30_MagicItem_406 Butcher's Sickle ══════════════

class TestButchersSickle(unittest.TestCase):
    TID = "BG30_MagicItem_406"

    def test_gets_butchering_each_turn(self):
        """Butchering 是**池酒馆法术**（card_type=42）——必须发 Spell 实体
        且占法术池（2026-09-02 对抗审查 CRITICAL: 旧实现发成 Minion）。"""
        g = make_game(seed=2151)
        a, b = g.heroes
        minion_before = g.minion_pool.total_remaining()
        spell_before = g.spell_pool.available(BUTCHERING)
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual([e.card_id for e in a.hand], [BUTCHERING])
        self.assertIsInstance(a.hand[0], Spell)             # 法术实体
        self.assertEqual(g.spell_pool.available(BUTCHERING),
                         spell_before - 1)                   # 占法术池
        self.assertEqual(g.minion_pool.total_remaining(), minion_before)
        g.end_recruit_phase()
        got = [e for e in a.hand if e.card_id == BUTCHERING]
        self.assertEqual(len(got), 2)
        self.assertTrue(all(isinstance(e, Spell) for e in got))
        self.assertEqual(g.spell_pool.available(BUTCHERING),
                         spell_before - 2)                   # 第二张也占池
        self.assertEqual(b.hand, [])

    def test_spell_pool_exhausted_whiffs(self):
        """池法术耗尽 → 本次获取落空（RULES §2.4），不给 Minion 实体。"""
        g = make_game(seed=2153)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        a.hand.clear()
        while g.spell_pool.acquire(BUTCHERING):
            pass
        hand_n = len(a.hand)
        self.assertFalse(B8._grant_card(g, a, BUTCHERING))
        self.assertEqual(len(a.hand), hand_n)

    def test_control_without_trinket(self):
        g = make_game(seed=2152)
        a = g.heroes[0]
        self.assertEqual(a.hand, [])


# ══════════════ BG32_MagicItem_831 Sellemental Portrait ══════════════

class TestSellementalPortrait(unittest.TestCase):
    TID = "BG32_MagicItem_831"

    def test_gets_sellemental_each_turn(self):
        g = make_game(seed=2161)
        a, b = g.heroes
        before = g.minion_pool.available(SELLEMENTAL)
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual([e.card_id for e in a.hand], [SELLEMENTAL])
        self.assertEqual(g.minion_pool.available(SELLEMENTAL), before - 1)
        g.end_recruit_phase()
        got = [e for e in a.hand if e.card_id == SELLEMENTAL]
        self.assertEqual(len(got), 2)
        self.assertEqual(g.minion_pool.available(SELLEMENTAL), before - 2)
        self.assertEqual(b.hand, [])

    def test_control_without_trinket(self):
        g = make_game(seed=2162)
        a = g.heroes[0]
        self.assertEqual(a.hand, [])


# ══════════════ BG32_MagicItem_415 Battle Horn ══════════════

class TestBattleHorn(unittest.TestCase):
    TID = "BG32_MagicItem_415"

    def test_discover_battlecry_minion_with_reservation(self):
        g = make_game(seed=2171)
        a = g.heroes[0]
        before = pool_sum(g, lambda d: has_kw(d, "battlecry"))
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual(len(g.pending_choices), 1)
        choice = g.pending_choices[0]
        self.assertEqual(choice.kind, "discover_minion")
        self.assertEqual(len(choice.options), 3)
        # 预留语义: 三选项已占池
        self.assertEqual(
            pool_sum(g, lambda d: has_kw(d, "battlecry")), before - 3)
        for cid in choice.options:
            self.assertIn("battlecry", get_db().get(cid).keywords)
        g.pending_choices.pop(0)
        choice.choose(0)
        self.assertEqual(len(a.hand), 1)
        self.assertIn("battlecry", get_db().get(a.hand[0].card_id).keywords)
        self.assertEqual(
            pool_sum(g, lambda d: has_kw(d, "battlecry")), before - 1)

    def test_avenge_triggers_friendly_battlecry(self):
        g = make_game(seed=2172)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        g.pending_choices.pop(0).choose(0)           # 结算发现
        calls = []
        probe_m = probe_minion("battlecry", calls, atk=0, health=50)
        put(g, a, probe_m)
        victims = [put(g, a, g.create_minion(PLAIN_1, controller=a))
                   for _ in range(B8.BattleHornScript.avenge_threshold)]
        for v in victims:
            death_in_combat(g, v)
        self.assertEqual(calls.count(probe_m), 1)

    def test_below_threshold_whiffs(self):
        g = make_game(seed=2173)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        g.pending_choices.pop(0).choose(0)
        calls = []
        put(g, a, probe_minion("battlecry", calls, atk=0, health=50))
        victim = put(g, a, g.create_minion(PLAIN_1, controller=a))
        death_in_combat(g, victim)
        self.assertEqual(calls, [])

    def test_opponent_deaths_not_counted(self):
        g = make_game(seed=2174)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        g.pending_choices.pop(0).choose(0)
        calls = []
        put(g, a, probe_minion("battlecry", calls, atk=0, health=50))
        victims = [put(g, b, g.create_minion(PLAIN_1, controller=b))
                   for _ in range(2)]
        for v in victims:
            death_in_combat(g, v)
        self.assertEqual(calls, [])                  # owner 隔离


# ══════════════ BG30_MagicItem_973 Minion Bait ══════════════

class TestMinionBait(unittest.TestCase):
    TID = "BG30_MagicItem_973"

    def _nagas(self, hero):
        return [e for e in hero.tavern
                if isinstance(e, Minion)
                and get_db().get(e.card_id).race in (Race.NAGA, Race.ALL)]

    def _pair(self, seed, subject):
        """同 seed、同 rng 消耗路径的（有饰品, 无饰品）两局。

        subject="a" 时两局都刷新本人; subject="b" 时两局都刷新对手。
        有饰品局的 on_bind 走 offer_and_buy、对照局走 offer_and_abandon
        （都不消耗额外 rng，故 refresh 抽取完全一致）。
        """
        g1 = make_game(seed=seed)
        offer_and_buy(g1, g1.heroes[0], self.TID, "lesser")
        g2 = make_game(seed=seed)
        offer_and_abandon(g2, g2.heroes[0], "lesser")
        for g in (g1, g2):
            g.heroes[0].gold = 50
            g.heroes[1].gold = 50
        if subject == "a":
            g1.refresh_tavern(g1.heroes[0])
            g2.refresh_tavern(g2.heroes[0])
        else:
            g1.refresh_tavern(g1.heroes[1])
            g2.refresh_tavern(g2.heroes[1])
        return g1, g2

    def test_refresh_injects_two_extra_nagas(self):
        g1, g2 = self._pair(2181, "a")
        a1, a2 = g1.heroes[0], g2.heroes[0]
        self.assertEqual(len(self._nagas(a1)), len(self._nagas(a2)) + 2)
        for e in self._nagas(a1):
            self.assertIn(get_db().get(e.card_id).race, (Race.NAGA, Race.ALL))
        # 占池: 有饰品局多消耗 2 份纳迦
        self.assertEqual(pool_sum(g1, race_in(Race.NAGA)),
                         pool_sum(g2, race_in(Race.NAGA)) - 2)

    def test_same_seed_control_differs_by_two(self):
        g1, g2 = self._pair(2182, "a")
        self.assertEqual(len(self._nagas(g1.heroes[0])) -
                         len(self._nagas(g2.heroes[0])), 2)

    def test_opponent_refresh_not_injected(self):
        g1, g2 = self._pair(2183, "b")               # 两局都刷新对手
        b1, b2 = g1.heroes[1], g2.heroes[1]
        self.assertEqual(len(self._nagas(b1)), len(self._nagas(b2)))
        self.assertEqual(pool_sum(g1, race_in(Race.NAGA)),
                         pool_sum(g2, race_in(Race.NAGA)))   # owner 隔离


# ══════════════ BG35_MagicItem_862 Upstart Embers ══════════════

class TestUpstartEmbers(unittest.TestCase):
    TID = "BG35_MagicItem_862"

    def _setup(self, g, hero, with_trinket):
        if with_trinket:
            offer_and_buy(g, hero, self.TID, "greater")
        target = g.inject_tavern_minion(hero, TARGET_TAVERN)
        g.run_actions(Buff(target, atk=2, health=20))
        target.set(GameTag.FROZEN, True)             # 单卡冻结跨刷新保留
        return target

    def test_refresh_doubles_highest_health_minion(self):
        g = make_game(seed=2191)
        a = g.heroes[0]
        target = self._setup(g, a, with_trinket=True)
        atk, hp = target.atk, target.max_health
        a.gold = 50
        g.refresh_tavern(a)
        self.assertEqual(target.atk, atk * 2)
        self.assertEqual(target.max_health, hp * 2)

    def test_control_without_trinket(self):
        g = make_game(seed=2192)
        a = g.heroes[0]
        target = self._setup(g, a, with_trinket=False)
        atk, hp = target.atk, target.max_health
        a.gold = 50
        g.refresh_tavern(a)
        self.assertEqual(target.atk, atk)
        self.assertEqual(target.max_health, hp)

    def test_auto_refresh_not_doubled(self):
        """"After you Refresh" = 玩家**主动**刷新; 引擎自动刷新（auto=True）
        不计入（2026-09-02 对抗审查: 旧实现忽略 auto → 每回合白送）。"""
        g = make_game(seed=2194)
        a = g.heroes[0]
        target = self._setup(g, a, with_trinket=True)
        atk, hp = target.atk, target.max_health
        g.refresh_tavern(a, auto=True)
        self.assertEqual(target.atk, atk)                    # 未翻倍
        self.assertEqual(target.max_health, hp)
        # 实体 FROZEN 在刷新时被消费 → 重新冻结后再做主动刷新正对照
        target.set(GameTag.FROZEN, True)
        a.gold = 50
        g.refresh_tavern(a)                                  # 主动 → 翻倍
        self.assertEqual(target.atk, atk * 2)
        self.assertEqual(target.max_health, hp * 2)

    def test_opponent_refresh_not_doubled(self):
        g = make_game(seed=2193)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        target_b = self._setup(g, b, with_trinket=False)
        target_a = g.inject_tavern_minion(a, TARGET_TAVERN)
        g.run_actions(Buff(target_a, atk=2, health=20))
        target_a.set(GameTag.FROZEN, True)
        a_atk = target_a.atk
        b.gold = 50
        g.refresh_tavern(b)                          # 对手刷新
        self.assertEqual(target_b.atk, get_db().get(TARGET_TAVERN).atk + 2)
        self.assertEqual(target_a.atk, a_atk)        # owner 隔离


# ══════════════ BG35_MagicItem_434 Jewelry Box ══════════════

class TestJewelryBox(unittest.TestCase):
    TID = "BG35_MagicItem_434"

    def _gem_ids(self):
        return {BLOOD_GEM_VARIANTS[v] for v in BLOOD_GEM_VARIANTS
                if v is not None}

    def test_gets_variant_gem_each_turn(self):
        g = make_game(seed=2201)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual(len(a.hand), 1)
        self.assertTrue(isinstance(a.hand[0], Spell))
        self.assertIn(a.hand[0].card_id, self._gem_ids())
        g.end_recruit_phase()
        gems = [e for e in a.hand if e.card_id in self._gem_ids()]
        self.assertEqual(len(gems), 2)
        self.assertEqual(b.hand, [])

    def test_variant_is_one_of_three(self):
        g = make_game(seed=2202)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        card_id = a.hand[0].card_id
        self.assertIn(card_id, self._gem_ids())
        self.assertEqual(len(self._gem_ids()), 3)

    def test_control_without_trinket(self):
        g = make_game(seed=2203)
        a = g.heroes[0]
        self.assertEqual(a.hand, [])


if __name__ == "__main__":
    unittest.main()
