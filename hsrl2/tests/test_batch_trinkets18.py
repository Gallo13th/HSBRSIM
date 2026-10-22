"""批次 trinkets18 行为层测试（片 6/7 子集: 13 注册 + 1 Spellcraft 法术 + 2 DEFERRED;
702 已由 batch_trinkets25、713 已由 batch_trinkets23 注册，
732/743/755 已由 batch_unlock_final 注册迁出）。

全部断言走真实引擎路径:
  - 购买: 真实 `game._offer_trinkets` + `PendingChoice.choose`
    （resolve 扣费 → `hero.trinkets` → `run_script_hook(on_bind)`）
  - SoC: 真实 `game.run_combat(a, b)`（读到 SoC 结算后状态的探针 =
    `START_OF_COMBAT` 事件——引擎在饰品/奖励/随从 SoC 钩子**之后**广播）
  - EoT / SoT: 真实 `run_script_hook(trinket, "end_of_turn"/"start_of_turn")`
    （与引擎 `end_recruit_phase` / `_begin_recruit_for` 的调用点同构）
  - 死亡 / 战斗内死亡: 真实 `game._process_single_death` + `check_deaths`
  - 手牌法术: 真实 `game.play_spell`; 购买: 真实 `game.buy_from_tavern`
  - 池: `minion_pool.available` / `spell_pool.available` 前后差

覆盖（SOP §16 空转测试判定法）:
  - 每个效果类都有正对照（同 setup 无饰品 / 无触发的负例）
  - owner 隔离（两英雄: 对手活动不产生本人效果）
  - 跨回合 / 一次性语义（战斗快照回滚、COMBAT_END 恢复、每回合计数、
    cadence 周期）
  - 落空不消耗资源（池抽干 / 空棋盘 / 空手牌 → 无 Action 无副作用）
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2 import constants as C
from hsrl2.actions.bloodgem import PlayBloodGems
from hsrl2.db import CardDB
from hsrl2.events import START_OF_COMBAT, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_trinkets18 as B18
from hsrl2.spellcraft import generate_for_hero
from hsrl2.tags import GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有卡（CardDB 按名核实，非凭记忆 id）
BEAST = "BG26_802"        # Banana Slamma 3/6 T4 野兽（无关键词）
MECH = "BG_TTN_401"       # Ancestral Automaton 3/4 T2 机械（无关键词）
MURLOC = "BG33_140"       # River Skipper 1/1 T1 鱼人（无关键词）
PIRATE = "BG26_135"       # Southsea Busker 3/1 T1 海盗（战吼）
UNDEAD = "BG25_008"       # Eternal Knight 4/2 T2 亡灵（池随从）
BIG = "BG25_013"          # Rot Hide Gnoll 1/4 T1 亡灵（坦克用）
GEM = "BG20_GEM"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 900) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def make_game_real(hero_ids, seed: int = 900) -> Game:
    """真实英雄定义（Maxwell Sticker 需 hero CardDef.companion_id 数据链）。"""
    g = Game([Hero(hid, hid) for hid in hero_ids], get_db(), seed=seed)
    g.start_game()
    return g


def offer_and_buy(game: Game, hero: Hero, tid: str, kind: str):
    """真实饰品商店路径: _offer_trinkets → PendingChoice → resolve。"""
    hero.gold = 50
    game._offer_trinkets(hero, kind)
    choice = game.pending_choices.pop(0)
    choice.options = [get_db().get(tid)]
    choice.choose(0)
    return hero.trinkets[-1]


def put(game: Game, hero: Hero, m: Minion) -> Minion:
    assert game.summon(hero, m)
    return m


def soc_snapshot(game: Game, hero: Hero, fn) -> dict:
    """注册 SoC 后观测器（START_OF_COMBAT 每英雄各广播一次 → 按 hero 过滤）。"""
    seen: dict = {}

    def cb(g, hero=None, _h=hero, **kw):
        if hero is _h:
            seen["v"] = fn()

    game.events.register(Listener(event=START_OF_COMBAT, owner=hero,
                                  callback=cb))
    return seen


def death_in_combat(game: Game, victim: Minion) -> None:
    """战斗内直接驱动死亡处理（真实 `_process_single_death` 路径）。"""
    prev = game.in_combat
    game.in_combat = True
    try:
        victim.set(GameTag.HEALTH, 0)
        game._process_single_death(victim)
    finally:
        game.in_combat = prev


def hand_ids(hero: Hero) -> list:
    return [e.card_id for e in hero.hand]


def undead_pool_total(game: Game) -> int:
    return sum(game.minion_pool.available(d.id)
               for d in get_db().pool_minions() if d.race == Race.UNDEAD)


def hand_minions(hero: Hero) -> list:
    return [e for e in hero.hand if isinstance(e, Minion)]


def drain_pool(game: Game, pred, keep=None) -> None:
    for d in get_db().pool_minions():
        if keep is not None and d.id == keep:
            continue
        if not pred(d):
            continue
        while game.minion_pool.available(d.id) > 0:
            game.minion_pool.acquire(d.id)


class TestRegistryState(unittest.TestCase):
    """注册面 + 数据链/参数一致性（结构性——与脚本钩子无关）。

    @engine-only: 本类断言注册表/卡定义/数据链，钩子 no-op 后仍通过属预期。
    """

    IMPLEMENTED = (
        "BG35_MagicItem_435", "BG35_MagicItem_701", "BG35_MagicItem_712",
        "BG35_MagicItem_714", "BG35_MagicItem_733", "BG35_MagicItem_733t",
        "BG35_MagicItem_740", "BG35_MagicItem_741", "BG35_MagicItem_742",
        "BG35_MagicItem_750", "BG35_MagicItem_753", "BG35_MagicItem_754",
        "BG35_MagicItem_803", "BG35_MagicItem_817",
    )
    # BG35_MagicItem_713 Trusty Crowbar 已由 batch_trinkets23 注册
    # （hero 级 `card_gained` 事件）——迁出本台账
    # BG35_MagicItem_702 已由 batch_trinkets25 注册（Stegodon Portrait）。
    # BG35_MagicItem_818 Mysterious Orb 已由 batch_trinkets30 注册
    # （2026-09-15: `hero._next_trinket_kind` 消费点）——迁出本台账
    DEFERRED = (
        "BG35_MagicItem_812",
    )
    # 732/743/755 已由 batch_unlock_final 注册（2026-09-15: last_minion_died /
    # 关键词限定价格·展示位 / 战吼刷新）——迁出 DEFERRED 台账
    MIGRATED = (
        "BG35_MagicItem_732", "BG35_MagicItem_743", "BG35_MagicItem_755",
    )
    KIND = {
        "BG35_MagicItem_435": "greater", "BG35_MagicItem_701": "greater",
        "BG35_MagicItem_702": "lesser", "BG35_MagicItem_712": "greater",
        "BG35_MagicItem_713": "greater", "BG35_MagicItem_714": "greater",
        "BG35_MagicItem_732": "greater", "BG35_MagicItem_733": "greater",
        "BG35_MagicItem_740": "greater", "BG35_MagicItem_741": "greater",
        "BG35_MagicItem_742": "greater", "BG35_MagicItem_743": "greater",
        "BG35_MagicItem_750": "greater", "BG35_MagicItem_753": "greater",
        "BG35_MagicItem_754": "greater", "BG35_MagicItem_755": "greater",
        "BG35_MagicItem_803": "lesser", "BG35_MagicItem_812": "greater",
        "BG35_MagicItem_817": "lesser", "BG35_MagicItem_818": "lesser",
    }
    CLASSES = {
        "BG35_MagicItem_435": "BloodboundRingScript",
        "BG35_MagicItem_701": "FangAnkletScript",
        "BG35_MagicItem_712": "PrivateerPortraitScript",
        "BG35_MagicItem_714": "PowderKegScript",
        "BG35_MagicItem_733": "JailerStickerScript",
        "BG35_MagicItem_733t": "JailerStickerSpellScript",
        "BG35_MagicItem_740": "SkyGolemPortraitScript",
        "BG35_MagicItem_741": "BeatboxerPortraitScript",
        "BG35_MagicItem_742": "AccordOTronPortraitScript",
        "BG35_MagicItem_750": "MagicfinStickerScript",
        "BG35_MagicItem_753": "MurkyStickerScript",
        "BG35_MagicItem_754": "DramalocStickerScript",
        "BG35_MagicItem_803": "MaxwellStickerScript",
        "BG35_MagicItem_817": "LensCaseScript",
    }

    def test_all_ids_registered(self):
        self.assertEqual(len(self.IMPLEMENTED), 14)
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)
            self.assertIs(REGISTRY[tid], getattr(B18, self.CLASSES[tid]), tid)
            self.assertIsNotNone(get_db().get(tid), tid)

    def test_deferred_ids_not_registered(self):
        """二态铁律: DEFERRED 卡必须不注册（SOP §6b）。"""
        self.assertEqual(len(self.DEFERRED), 1)
        self.assertEqual(len(self.MIGRATED), 3)
        for tid in self.DEFERRED:
            self.assertNotIn(tid, REGISTRY, tid)
            self.assertIsNotNone(get_db().get(tid), tid)

    def test_offer_pool_membership_and_kind(self):
        """商店池成员 + 档位（spell_school 11=Lesser / 12=Greater）。"""
        db = get_db()
        offer_ids = {d.id for d in db.trinket_offer_pool()}
        for tid, kind in self.KIND.items():
            self.assertIn(tid, offer_ids, tid)
            self.assertEqual(db.get(tid).spell_school,
                             11 if kind == "lesser" else 12, tid)

    def test_numeric_params_pinned(self):
        """模板参数与测试期望值同源（CardDef 是唯一权威）。"""
        db = get_db()
        expected = {
            "BG35_MagicItem_701": (1, 1),
            "BG35_MagicItem_712": (2, None),
            "BG35_MagicItem_714": (3, None),
            "BG35_MagicItem_750": (2, 2),
            "BG35_MagicItem_753": (1, 2),
            "BG35_MagicItem_817": (2, 2),
            "BG35_MagicItem_818": (10, None),
        }
        for tid, (n0, n1) in expected.items():
            d = db.get(tid)
            self.assertEqual(d.num(0), n0, tid)
            self.assertEqual(d.num(1), n1, tid)

    def test_evolution_chains(self):
        """"Get a X" 全部经 `evolution_card_id` 数据链（零硬编码卡 id）。"""
        db = get_db()
        pairs = {
            "BG35_MagicItem_712": ("BG33_825", True),
            "BG35_MagicItem_740": ("BG35_342", True),
            "BG35_MagicItem_741": ("BG26_149", True),
            "BG35_MagicItem_742": ("BG26_147", True),
            "BG35_MagicItem_817": ("BG35_MagicItem_817t", False),
        }
        for tid, (target, is_pool) in pairs.items():
            d = db.get(tid)
            self.assertIsNotNone(d.evolution_card_id, tid)
            token = db.by_dbf(d.evolution_card_id)
            self.assertIsNotNone(token, tid)
            self.assertEqual(token.id, target, tid)
            self.assertEqual(token.is_pool_minion, is_pool, tid)

    def test_spellcraft_chain(self):
        d = get_db().get("BG35_MagicItem_733")
        spell = get_db().by_dbf(d.spellcraft_id)
        self.assertEqual(spell.id, "BG35_MagicItem_733t")
        self.assertFalse(spell.is_pool_spell)

    def test_stegodon_data_chain_missing(self):
        """702 的 DEFERRED 依据: XML 无关联卡 tag → 数据链恒 None。"""
        db = get_db()
        self.assertIsNone(db.get("BG35_MagicItem_702").evolution_card_id)
        self.assertIsNone(db.get("BG35_MagicItem_702").spellcraft_id)


# ══════════════ BG35_MagicItem_435 Bloodbound Ring ══════════════

class TestBloodboundRing(unittest.TestCase):
    TID = "BG35_MagicItem_435"

    def _setup(self, seed, with_trinket, owner_targets=True):
        g = make_game(seed=seed)
        a, b = g.heroes
        if with_trinket:
            offer_and_buy(g, a, self.TID, "greater")
        ds = put(g, a, g.create_minion(MECH, controller=a))
        ds.set(GameTag.DIVINE_SHIELD, True)
        plain = put(g, a, g.create_minion(MURLOC, controller=a))
        enemy_ds = put(g, b, g.create_minion(MECH, controller=b))
        enemy_ds.set(GameTag.DIVINE_SHIELD, True)
        gem = g.create_spell(GEM, controller=a)
        g.pending_hand_add(a, gem)
        snap = (ds.atk, ds.health, plain.atk, plain.health,
                enemy_ds.atk, enemy_ds.health)
        g.play_spell(a, gem, target=ds)
        return g, (ds, plain, enemy_ds), snap

    def test_hand_gem_triggers_extra_gem_on_divine_shield_minions(self):
        db = get_db()
        n0, n1 = db.get(GEM).num(0), db.get(GEM).num(1)
        g, (ds, plain, enemy_ds), snap = self._setup(4101, True)
        # 手牌宝石本身命中 ds（+n0/+n1），饰品追加一颗（再 +n0/+n1）
        self.assertEqual((ds.atk, ds.health),
                         (snap[0] + 2 * n0, snap[1] + 2 * n1))
        self.assertEqual((plain.atk, plain.health), (snap[2], snap[3]))
        self.assertEqual((enemy_ds.atk, enemy_ds.health),
                         (snap[4], snap[5]))          # owner 隔离

    def test_direct_play_gem_does_not_trigger(self):
        """直施 `PlayBloodGems` 不是 "from hand" → 不触发（正对照）。"""
        db = get_db()
        n0, n1 = db.get(GEM).num(0), db.get(GEM).num(1)
        g = make_game(seed=4102)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        ds = put(g, a, g.create_minion(MECH, controller=a))
        ds.set(GameTag.DIVINE_SHIELD, True)
        atk, hp = ds.atk, ds.health
        g.run_actions([PlayBloodGems(ds, 1)])
        self.assertEqual((ds.atk, ds.health), (atk + n0, hp + n1))
        # 正对照: 同 setup 下手牌打出会追加第二颗（+2×num）
        gem = g.create_spell(GEM, controller=a)
        g.pending_hand_add(a, gem)
        g.play_spell(a, gem, target=ds)
        self.assertEqual((ds.atk, ds.health),
                         (atk + n0 + 2 * n0, hp + n1 + 2 * n1))

    def test_no_divine_shield_minion_fizzles(self):
        db = get_db()
        n0, n1 = db.get(GEM).num(0), db.get(GEM).num(1)
        g = make_game(seed=4103)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        plain = put(g, a, g.create_minion(MURLOC, controller=a))
        gem = g.create_spell(GEM, controller=a)
        g.pending_hand_add(a, gem)
        atk, hp = plain.atk, plain.health
        g.play_spell(a, gem, target=plain)
        self.assertEqual((plain.atk, plain.health), (atk + n0, hp + n1))
        # 正对照: 场内出现圣盾随从时本饰品追加一颗宝石（+n0；与被指定
        # 目标无关——该颗宝石由饰品自身打给全部圣盾随从）
        ds = put(g, a, g.create_minion(MECH, controller=a))
        ds.set(GameTag.DIVINE_SHIELD, True)
        gem2 = g.create_spell(GEM, controller=a)
        g.pending_hand_add(a, gem2)
        d_atk = ds.atk
        g.play_spell(a, gem2, target=plain)
        self.assertEqual(ds.atk, d_atk + n0)


# ══════════════ BG35_MagicItem_701 Fang Anklet ══════════════

class TestFangAnklet(unittest.TestCase):
    TID = "BG35_MagicItem_701"

    def test_soc_buff_scales_with_beasts_summoned(self):
        db = get_db()
        n0, n1 = db.get(self.TID).num(0), db.get(self.TID).num(1)
        g = make_game(seed=4201)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        beast = put(g, a, g.create_minion(BEAST, controller=a))
        other = put(g, a, g.create_minion(MECH, controller=a))
        put(g, a, g.create_minion(BEAST, controller=a))     # 第 2 只 → ×3
        put(g, b, g.create_minion(BEAST, controller=b))     # 对手不计入
        base = (beast.atk, beast.health, other.atk)
        probe = soc_snapshot(g, a, lambda: (beast.atk, beast.health,
                                            other.atk))
        g.run_combat(a, b)
        self.assertEqual(probe.get("v"),
                         (base[0] + 3 * n0, base[1] + 3 * n1, base[2]))
        # "this combat" = 战后回滚
        self.assertEqual((beast.atk, beast.health), (base[0], base[1]))

    def test_control_without_trinket(self):
        db = get_db()
        n0, n1 = db.get(self.TID).num(0), db.get(self.TID).num(1)
        g = make_game(seed=4202)
        a, b = g.heroes
        beast = put(g, a, g.create_minion(BEAST, controller=a))
        put(g, a, g.create_minion(BEAST, controller=a))
        base = (beast.atk, beast.health)
        probe = soc_snapshot(g, a, lambda: (beast.atk, beast.health))
        g.run_combat(a, b)
        self.assertEqual(probe.get("v"), base)
        # 正对照: 同 setup 有饰品时确实 +3×num
        g2 = make_game(seed=4202)
        a2, b2 = g2.heroes
        offer_and_buy(g2, a2, self.TID, "greater")
        beast2 = put(g2, a2, g2.create_minion(BEAST, controller=a2))
        put(g2, a2, g2.create_minion(BEAST, controller=a2))
        base2 = beast2.atk
        p2 = soc_snapshot(g2, a2, lambda: beast2.atk)
        g2.run_combat(a2, b2)
        self.assertEqual(p2.get("v"), base2 + 3 * n0)
        self.assertEqual(n1, db.get(self.TID).num(1))

    def test_opponent_beast_summon_not_counted(self):
        db = get_db()
        n0 = db.get(self.TID).num(0)
        g = make_game(seed=4203)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        beast = put(g, a, g.create_minion(BEAST, controller=a))
        for _ in range(3):
            put(g, b, g.create_minion(BEAST, controller=b))
        base = beast.atk
        probe = soc_snapshot(g, a, lambda: beast.atk)
        g.run_combat(a, b)
        # 本人 1 只 → ×2；对手 3 只若被计入会是 ×5（区分度）
        self.assertEqual(probe.get("v"), base + 2 * n0)


# ══════════════ BG35_MagicItem_712 Privateer Portrait ══════════════

class TestPrivateerPortrait(unittest.TestCase):
    TID = "BG35_MagicItem_712"

    def test_bind_grants_privateer_and_bounties(self):
        db = get_db()
        count = db.get(self.TID).num(0)
        g = make_game(seed=4301)
        a, b = g.heroes
        pool_before = g.minion_pool.available("BG33_825")
        bounty_before = {cid: g.spell_pool.available(cid)
                         for cid in C.BOUNTY_SPELL_IDS}
        offer_and_buy(g, a, self.TID, "greater")
        ids = hand_ids(a)
        self.assertEqual(ids.count("BG33_825"), 1)
        self.assertEqual(g.minion_pool.available("BG33_825"),
                         pool_before - 1)
        bounties = [i for i in ids if i in C.BOUNTY_SPELL_IDS]
        self.assertEqual(len(bounties), count)
        for cid in C.BOUNTY_SPELL_IDS:
            self.assertEqual(g.spell_pool.available(cid),
                             bounty_before[cid] - bounties.count(cid), cid)
        self.assertEqual(hand_ids(b), [])

    def test_start_of_turn_grants_more_bounties(self):
        db = get_db()
        count = db.get(self.TID).num(0)
        g = make_game(seed=4302)
        a, b = g.heroes
        trinket = offer_and_buy(g, a, self.TID, "greater")
        first = len([i for i in hand_ids(a) if i in C.BOUNTY_SPELL_IDS])
        g.run_script_hook(trinket, "start_of_turn")
        second = len([i for i in hand_ids(a) if i in C.BOUNTY_SPELL_IDS])
        self.assertEqual(first, count)
        self.assertEqual(second, first + count)
        g.run_script_hook(trinket, "start_of_turn")
        self.assertEqual(
            len([i for i in hand_ids(a) if i in C.BOUNTY_SPELL_IDS]),
            second + count)
        # 对手不受影响（owner 隔离，正对照: 本人确实继续增加）
        self.assertEqual(hand_ids(b), [])

    def test_exhausted_bounty_pool_fizzles(self):
        db = get_db()
        count = db.get(self.TID).num(0)
        g = make_game(seed=4303)
        a = g.heroes[0]
        for cid in C.BOUNTY_SPELL_IDS:
            while g.spell_pool.available(cid) > 0:
                g.spell_pool.acquire(cid)
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual(
            [i for i in hand_ids(a) if i in C.BOUNTY_SPELL_IDS], [])
        self.assertEqual(hand_ids(a), ["BG33_825"])   # 关联卡照常交付
        self.assertEqual(count, 2)


# ══════════════ BG35_MagicItem_714 Powder Keg ══════════════

class TestPowderKeg(unittest.TestCase):
    TID = "BG35_MagicItem_714"

    def test_soc_grants_deathrattle_to_friendly_pirates_only(self):
        g = make_game(seed=4401)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        mine = put(g, a, g.create_minion(PIRATE, controller=a))
        theirs = put(g, b, g.create_minion(PIRATE, controller=b))
        seen = soc_snapshot(g, a, lambda: (mine.has(GameTag.DEATHRATTLE),
                                           theirs.has(GameTag.DEATHRATTLE)))
        g.run_combat(a, b)
        self.assertEqual(seen.get("v"), (True, False))

    def test_no_pirate_fizzles(self):
        g = make_game(seed=4402)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        beast = put(g, a, g.create_minion(BEAST, controller=a))
        seen = soc_snapshot(g, a, lambda: beast.has(GameTag.DEATHRATTLE))
        g.run_combat(a, b)
        self.assertFalse(seen.get("v"))
        # 正对照: 场上放入海盗后同一饰品确实授予亡语
        pirate = put(g, a, g.create_minion(PIRATE, controller=a))
        seen2 = soc_snapshot(g, a, lambda: pirate.has(GameTag.DEATHRATTLE))
        g.run_combat(a, b)
        self.assertTrue(seen2.get("v"))

    def test_deathrattle_summons_sky_pirate_with_attack_and_it_hits(self):
        g = make_game(seed=4403)
        a, b = g.heroes
        trinket = offer_and_buy(g, a, self.TID, "greater")
        pirate = put(g, a, g.create_minion(PIRATE, controller=a))
        enemy = put(g, b, g.create_minion(BIG, controller=b))
        enemy.set(GameTag.BASE_HEALTH, 10)
        enemy.set(GameTag.HEALTH, 10)
        p_atk = pirate.atk
        e_hp = enemy.health
        g.in_combat = True
        g._active_combat = (a, b)
        g.run_script_hook(trinket, "start_of_combat")
        death_in_combat(g, pirate)
        tokens = [m for m in g.combat_summon_log
                  if m.card_id == B18._SKY_PIRATE_ID]
        self.assertEqual(len(tokens), 1)                      # 召唤体
        self.assertEqual(tokens[0].atk, 1 + p_atk)            # 1/1 + src.atk
        self.assertEqual(enemy.health, e_hp - tokens[0].atk)  # 立即攻击

    def test_grant_restored_after_combat(self):
        """授予的亡语 override 由引擎 `run_combat` finally 统一恢复。"""
        g = make_game(seed=4404)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        pirate = put(g, a, g.create_minion(PIRATE, controller=a))
        self.assertEqual(pirate._script_overrides, {})
        seen = soc_snapshot(g, a, lambda: bool(pirate._script_overrides))
        g.run_combat(a, b)
        self.assertTrue(seen.get("v"))                  # 正对照: 战内已授予
        self.assertEqual(pirate._script_overrides, {})  # 战后已恢复
        self.assertFalse(pirate.has(GameTag.DEATHRATTLE))
        death_in_combat(g, pirate)                      # 战后死亡不再产出
        self.assertEqual([m for m in g.combat_summon_log
                          if m.card_id == B18._SKY_PIRATE_ID], [])


# ══════════════ BG35_MagicItem_733 / _733t Jailer Sticker ══════════════

class TestJailerSticker(unittest.TestCase):
    TID = "BG35_MagicItem_733"
    SPELL = "BG35_MagicItem_733t"

    def test_bind_grants_first_spellcraft_spell(self):
        g = make_game(seed=4501)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        spells = [e for e in a.hand if e.card_id == self.SPELL]
        self.assertEqual(len(spells), 1)
        self.assertTrue(spells[0].has(GameTag.SPELLCRAFT))
        self.assertEqual(hand_ids(b), [])

    def test_engine_generates_exactly_one_per_turn(self):
        """引擎负责每回合生成；脚本不得再写 start_of_turn（防双发）。"""
        g = make_game(seed=4502)
        a = g.heroes[0]
        trinket = offer_and_buy(g, a, self.TID, "greater")
        script = REGISTRY[self.TID]
        self.assertFalse(hasattr(script, "start_of_turn"))
        a.hand.clear()                       # 排除绑定那张的干扰
        generate_for_hero(a, g)
        self.assertEqual([e.card_id for e in a.hand], [self.SPELL])
        self.assertIsNotNone(trinket)

    def test_spell_destroys_undead_and_gets_two(self):
        g = make_game(seed=4503)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        target = put(g, a, g.create_minion(UNDEAD, controller=a))
        enemy = put(g, b, g.create_minion(UNDEAD, controller=b))
        total_before = undead_pool_total(g)
        a.hand.clear()
        spell = g.create_spell(self.SPELL, controller=a)
        g.pending_hand_add(a, spell)
        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertNotIn(target, a.board)
        self.assertTrue(target.dead)
        got = hand_minions(a)
        self.assertEqual(len(got), 2)
        for m in got:
            self.assertEqual(m.race, Race.UNDEAD)
        # 池配平: 目标回池 +1、两次随机获取各占 1 份 → 净 -1
        self.assertEqual(undead_pool_total(g), total_before - 1)
        # 对手亡灵不受影响（owner 隔离）
        self.assertIn(enemy, b.board)

    def test_no_undead_target_does_not_offer_choice(self):
        g = make_game(seed=4504)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        put(g, a, g.create_minion(MECH, controller=a))
        a.hand.clear()
        spell = g.create_spell(self.SPELL, controller=a)
        g.pending_hand_add(a, spell)
        self.assertTrue(g.play_spell(a, spell))     # 无候选 → 落空但照常消耗
        self.assertEqual(g.pending_choices, [])
        self.assertEqual(hand_minions(a), [])
        # 正对照: 放入亡灵后同一法术产生定向选择并结算
        target = put(g, a, g.create_minion(UNDEAD, controller=a))
        spell2 = g.create_spell(self.SPELL, controller=a)
        g.pending_hand_add(a, spell2)
        self.assertTrue(g.play_spell(a, spell2))
        self.assertEqual(len(g.pending_choices), 1)
        choice = g.pending_choices.pop(0)
        self.assertEqual(choice.kind, "spell_target")
        choice.choose(0)
        self.assertNotIn(target, a.board)
        self.assertEqual(len(hand_minions(a)), 2)


# ══════════════ BG35_MagicItem_740 Sky Golem Portrait ══════════════

class TestSkyGolemPortrait(unittest.TestCase):
    TID = "BG35_MagicItem_740"

    def test_bind_grants_falling_sky_golem(self):
        g = make_game(seed=4601)
        a, b = g.heroes
        before = g.minion_pool.available("BG35_342")
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual(hand_ids(a), ["BG35_342"])
        self.assertEqual(g.minion_pool.available("BG35_342"), before - 1)
        self.assertEqual(hand_ids(b), [])

    def test_soc_grants_deathrattle_to_own_minions_only(self):
        g = make_game(seed=4602)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        mine = put(g, a, g.create_minion(MECH, controller=a))
        theirs = put(g, b, g.create_minion(MECH, controller=b))
        seen = soc_snapshot(g, a, lambda: (mine.has(GameTag.DEATHRATTLE),
                                           theirs.has(GameTag.DEATHRATTLE)))
        g.run_combat(a, b)
        self.assertEqual(seen.get("v"), (True, False))

    def test_deathrattle_buff_is_permanent_for_survivors(self):
        """真实战斗: 亡语触发 → 幸存随从战后永久 +num(0)/+num(1)。"""
        db = get_db()
        n0, n1 = db.get(self.TID).num(0), db.get(self.TID).num(1)
        g = make_game(seed=4603)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        victim, survivor, enemy = self._combat_setup(g, a, b)
        base = (survivor.atk, survivor.health)
        g.end_recruit_phase()          # 真实 run_combat + COMBAT_END 顺序
        # 嘲讽受害者战死 → 亡语对当时存活者生效 → 战后恢复 + 重放 = 永久
        self.assertEqual((survivor.atk, survivor.health),
                         (base[0] + n0, base[1] + n1))

    def test_control_without_trinket_leaves_survivor_untouched(self):
        g = make_game(seed=4604)
        a, b = g.heroes
        victim, survivor, enemy = self._combat_setup(g, a, b)
        base = (survivor.atk, survivor.health)
        g.end_recruit_phase()
        self.assertEqual((survivor.atk, survivor.health), base)
        # 正对照: 同 setup + 饰品 → 幸存者永久 +num(0)/+num(1)
        n0 = get_db().get(self.TID).num(0)
        n1 = get_db().get(self.TID).num(1)
        g2 = make_game(seed=4604)
        a2, b2 = g2.heroes
        offer_and_buy(g2, a2, self.TID, "greater")
        _, surv2, _ = self._combat_setup(g2, a2, b2)
        base2 = (surv2.atk, surv2.health)
        g2.end_recruit_phase()
        self.assertEqual((surv2.atk, surv2.health),
                         (base2[0] + n0, base2[1] + n1))

    @staticmethod
    def _combat_setup(g, a, b):
        """嘲讽 0/1 受害者 + 1/3 幸存者（均为无动态钩子的鱼人）对 1/20 敌人。"""
        victim = put(g, a, g.create_minion(MURLOC, controller=a))
        victim.set(GameTag.BASE_ATK, 0)
        victim.set(GameTag.ATK, 0)
        victim.set(GameTag.BASE_HEALTH, 1)
        victim.set(GameTag.HEALTH, 1)
        victim.set(GameTag.TAUNT, True)
        survivor = put(g, a, g.create_minion(MURLOC, controller=a))
        survivor.set(GameTag.BASE_ATK, 1)
        survivor.set(GameTag.ATK, 1)
        survivor.set(GameTag.BASE_HEALTH, 3)
        survivor.set(GameTag.HEALTH, 3)
        enemy = put(g, b, g.create_minion(BIG, controller=b))
        enemy.set(GameTag.BASE_ATK, 1)
        enemy.set(GameTag.ATK, 1)
        enemy.set(GameTag.BASE_HEALTH, 20)
        enemy.set(GameTag.HEALTH, 20)
        return victim, survivor, enemy


# ══════════════ BG35_MagicItem_741 Beatboxer Portrait ══════════════

class TestBeatboxerPortrait(unittest.TestCase):
    TID = "BG35_MagicItem_741"

    def test_bind_gets_polarizing_beatboxer_from_pool(self):
        g = make_game(seed=4701)
        a, b = g.heroes
        before = g.minion_pool.available("BG26_149")
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual(hand_ids(a), ["BG26_149"])
        self.assertEqual(g.minion_pool.available("BG26_149"), before - 1)
        self.assertEqual(hand_ids(b), [])

    def test_pool_exhausted_fizzles(self):
        g = make_game(seed=4702)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")     # 正对照: 池有余即交付
        self.assertEqual(hand_ids(a), ["BG26_149"])
        while g.minion_pool.available("BG26_149") > 0:
            g.minion_pool.acquire("BG26_149")
        offer_and_buy(g, b, self.TID, "greater")
        self.assertEqual(hand_ids(b), [])


# ══════════════ BG35_MagicItem_742 Accord-o-Tron Portrait ══════════════

class TestAccordOTronPortrait(unittest.TestCase):
    TID = "BG35_MagicItem_742"

    def test_eot_magnetizes_to_left_and_right_mechs(self):
        db = get_db()
        d = db.get("BG26_147")
        g = make_game(seed=4801)
        a, b = g.heroes
        trinket = offer_and_buy(g, a, self.TID, "greater")
        left = put(g, a, g.create_minion(MECH, controller=a))
        mid = put(g, a, g.create_minion(MECH, controller=a))
        right = put(g, a, g.create_minion(MECH, controller=a))
        pool_before = g.minion_pool.available("BG26_147")
        base = [(m.atk, m.health) for m in (left, mid, right)]
        g.run_script_hook(trinket, "end_of_turn")
        self.assertEqual((left.atk, left.health),
                         (base[0][0] + d.atk, base[0][1] + d.health))
        self.assertEqual((right.atk, right.health),
                         (base[2][0] + d.atk, base[2][1] + d.health))
        self.assertEqual((mid.atk, mid.health), base[1])
        # 生成体直接吸附: 零池操作
        self.assertEqual(g.minion_pool.available("BG26_147"), pool_before)
        self.assertEqual(len(g._magnetic_stack.get(left.uuid, [])), 1)
        self.assertEqual(len(g._magnetic_stack.get(right.uuid, [])), 1)
        # 效果合并 (RULES §6.14): Accord-o-Tron 的 "SoT: gain 1 Gold"
        # 随宿主钩子一并生效（引擎磁力钩子合并通道）
        a.gold = 5
        g.run_script_hook(left, "start_of_turn")
        self.assertEqual(a.gold, 6)

    def test_single_mech_magnetized_once(self):
        db = get_db()
        d = db.get("BG26_147")
        g = make_game(seed=4802)
        a = g.heroes[0]
        trinket = offer_and_buy(g, a, self.TID, "greater")
        only = put(g, a, g.create_minion(MECH, controller=a))
        base = (only.atk, only.health)
        g.run_script_hook(trinket, "end_of_turn")
        self.assertEqual((only.atk, only.health),
                         (base[0] + d.atk, base[1] + d.health))
        self.assertEqual(len(g._magnetic_stack.get(only.uuid, [])), 1)

    def test_no_mech_and_opponent_board_fizzle(self):
        g = make_game(seed=4803)
        a, b = g.heroes
        trinket = offer_and_buy(g, a, self.TID, "greater")
        mine = put(g, a, g.create_minion(MURLOC, controller=a))
        enemy = put(g, b, g.create_minion(MECH, controller=b))
        base = (mine.atk, mine.health, enemy.atk, enemy.health)
        g.run_script_hook(trinket, "end_of_turn")
        self.assertEqual((mine.atk, mine.health, enemy.atk, enemy.health),
                         base)
        # 正对照: 本人放入机械后同一 EoT 钩子确实吸附
        d = get_db().get("BG26_147")
        mech = put(g, a, g.create_minion(MECH, controller=a))
        m_atk = mech.atk
        g.run_script_hook(trinket, "end_of_turn")
        self.assertEqual(mech.atk, m_atk + d.atk)


# ══════════════ BG35_MagicItem_750 Magicfin Sticker ══════════════

class TestMagicfinSticker(unittest.TestCase):
    TID = "BG35_MagicItem_750"

    def _buy_spell(self, game, hero, card_id="BG28_810"):
        spell = game.create_spell(card_id, controller=hero)
        spell.zone = 3
        hero.tavern.append(spell)
        hero.gold = 20
        return game.buy_from_tavern(hero, spell)

    def test_buying_tavern_spell_teaches_murloc(self):
        db = get_db()
        limit = db.get(self.TID).num(0)
        g = make_game(seed=4901)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        self.assertTrue(self._buy_spell(g, a, "BG28_810"))
        ids = hand_ids(a)
        self.assertEqual(ids.count(B18._MAGICFIN_APPRENTICE_ID), 1)
        token = hand_minions(a)[0]
        self.assertEqual(token.card_id, B18._MAGICFIN_APPRENTICE_ID)
        self.assertEqual(token._taught_spell_id, "BG28_810")
        self.assertEqual(limit, 2)

    def test_buying_minion_does_not_trigger(self):
        g = make_game(seed=4902)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        m = g.create_minion(MURLOC, controller=a)
        m.zone = 3
        a.tavern.append(m)
        a.gold = 20
        self.assertTrue(g.buy_from_tavern(a, m))
        self.assertNotIn(B18._MAGICFIN_APPRENTICE_ID, hand_ids(a))
        # 正对照: 同一 setup 下购买酒馆法术确实发 1/1 Murloc
        self.assertTrue(self._buy_spell(g, a, "BG28_810"))
        self.assertIn(B18._MAGICFIN_APPRENTICE_ID, hand_ids(a))

    def test_per_turn_limit_and_reset(self):
        db = get_db()
        limit = db.get(self.TID).num(0)
        g = make_game(seed=4903)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        for _ in range(limit + 1):
            self._buy_spell(g, a, "BG28_810")
        got = [i for i in hand_ids(a) if i == B18._MAGICFIN_APPRENTICE_ID]
        self.assertEqual(len(got), limit)
        # 跨回合（真实 _begin_recruit_for 推进 + 清空计数）后恢复额度
        g.turn += 1
        self.assertTrue(self._buy_spell(g, a, "BG28_810"))
        got = [i for i in hand_ids(a) if i == B18._MAGICFIN_APPRENTICE_ID]
        self.assertEqual(len(got), limit + 1)


# ══════════════ BG35_MagicItem_753 Murky Sticker ══════════════

class TestMurkySticker(unittest.TestCase):
    TID = "BG35_MagicItem_753"

    def test_eot_buffs_two_left_most_scaled_by_battlecries(self):
        db = get_db()
        n0, n1 = db.get(self.TID).num(0), db.get(self.TID).num(1)
        g = make_game(seed=5001)
        a, b = g.heroes
        trinket = offer_and_buy(g, a, self.TID, "greater")
        first = put(g, a, g.create_minion(MECH, controller=a))
        second = put(g, a, g.create_minion(MECH, controller=a))
        third = put(g, a, g.create_minion(MECH, controller=a))
        base = [(m.atk, m.health) for m in (first, second, third)]
        # 真实战吼触发一次（Southsea Busker 带 battlecry）
        busker = g.create_minion(PIRATE, controller=a)
        g.pending_hand_add(a, busker)
        g.play_minion(a, busker)
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), 1)
        g.run_script_hook(trinket, "end_of_turn")
        self.assertEqual((first.atk, first.health),
                         (base[0][0] + 2 * n0, base[0][1] + 2 * n1))
        self.assertEqual((third.atk, third.health), base[2])
        self.assertEqual(hand_ids(b), [])

    def test_control_without_trinket_and_empty_board_fizzle(self):
        db = get_db()
        n0, n1 = db.get(self.TID).num(0), db.get(self.TID).num(1)
        g = make_game(seed=5002)
        a = g.heroes[0]
        first = put(g, a, g.create_minion(MECH, controller=a))
        base = (first.atk, first.health)
        g.events.fire(g, "end_of_turn", turn=g.turn)     # 无饰品 → 无效果
        self.assertEqual((first.atk, first.health), base)
        # 空棋盘落空（有饰品也不报错）
        trinket = offer_and_buy(g, a, self.TID, "greater")
        a.board.clear()
        g.run_script_hook(trinket, "end_of_turn")
        self.assertEqual(a.board, [])
        self.assertEqual((n0, n1), (1, 2))
        # 正对照: 同一饰品在非空棋盘上给最左随从 +num(0)/+num(1)
        again = put(g, a, g.create_minion(MECH, controller=a))
        a_atk, a_hp = again.atk, again.health
        g.run_script_hook(trinket, "end_of_turn")
        self.assertEqual((again.atk, again.health),
                         (a_atk + n0, a_hp + n1))


# ══════════════ BG35_MagicItem_754 Dramaloc Sticker ══════════════

class TestDramalocSticker(unittest.TestCase):
    TID = "BG35_MagicItem_754"

    def test_soc_gives_murlocs_attack_of_best_hand_minion(self):
        g = make_game(seed=5101)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        murloc = put(g, a, g.create_minion(MURLOC, controller=a))
        other = put(g, a, g.create_minion(MECH, controller=a))
        enemy = put(g, b, g.create_minion(MURLOC, controller=b))
        weak = g.create_minion(MURLOC, controller=a)
        strong = g.create_minion(BEAST, controller=a)
        strong.set(GameTag.BASE_ATK, 9)
        strong.set(GameTag.ATK, 9)
        g.pending_hand_add(a, weak)
        g.pending_hand_add(a, strong)
        base = (murloc.atk, murloc.health, other.atk, enemy.atk)
        seen = soc_snapshot(g, a, lambda: (murloc.atk, murloc.health,
                                           other.atk, enemy.atk))
        g.run_combat(a, b)
        self.assertEqual(seen.get("v"),
                         (base[0] + 9, base[1], base[2], base[3]))

    def test_empty_hand_fizzles(self):
        g = make_game(seed=5102)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        murloc = put(g, a, g.create_minion(MURLOC, controller=a))
        base = murloc.atk
        seen = soc_snapshot(g, a, lambda: murloc.atk)
        g.run_combat(a, b)
        self.assertEqual(seen.get("v"), base)
        # 正对照: 手牌放入随从后同一饰品确实给攻击力
        hand = g.create_minion(BEAST, controller=a)
        hand.set(GameTag.BASE_ATK, 7)
        hand.set(GameTag.ATK, 7)
        g.pending_hand_add(a, hand)
        seen2 = soc_snapshot(g, a, lambda: murloc.atk)
        g.run_combat(a, b)
        self.assertEqual(seen2.get("v"), base + 7)


# ══════════════ BG35_MagicItem_803 Maxwell Sticker ══════════════

class TestMaxwellSticker(unittest.TestCase):
    TID = "BG35_MagicItem_803"
    WITH_BUDDY = "BG20_HERO_100"     # Rokara（companion_id=77876，数据核实）
    NO_BUDDY = "BG34_HERO_000"       # Murozond, Unbounded（无伙伴）

    def test_bind_gets_hero_buddy(self):
        db = get_db()
        g = make_game_real([self.WITH_BUDDY, self.NO_BUDDY], seed=5201)
        a, b = g.heroes
        buddy = db.by_dbf(db.get(a.card_id).companion_id)
        self.assertIsNotNone(buddy)
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual(hand_ids(a), [buddy.id])
        self.assertEqual(hand_ids(b), [])
        self.assertFalse(db.get(buddy.id).is_pool_minion)
        self.assertEqual(g.minion_pool.available(buddy.id), 0)

    def test_hero_without_buddy_fizzles(self):
        db = get_db()
        g = make_game_real([self.NO_BUDDY, self.WITH_BUDDY], seed=5202)
        a = g.heroes[0]
        self.assertIsNone(db.get(a.card_id).companion_id)
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual(hand_ids(a), [])
        # 正对照: 同局有伙伴的英雄 b 得到伙伴
        b = g.heroes[1]
        buddy = db.by_dbf(db.get(b.card_id).companion_id)
        offer_and_buy(g, b, self.TID, "lesser")
        self.assertEqual(hand_ids(b), [buddy.id])


# ══════════════ BG35_MagicItem_817 Lens Case ══════════════

class TestLensCase(unittest.TestCase):
    TID = "BG35_MagicItem_817"
    TOKEN = "BG35_MagicItem_817t"

    def test_bind_gets_one_lens(self):
        g = make_game(seed=5301)
        a, b = g.heroes
        spell_pool_before = g.spell_pool.available(self.TOKEN)
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual(hand_ids(a), [self.TOKEN])
        self.assertEqual(g.spell_pool.available(self.TOKEN),
                         spell_pool_before)      # 池外法术零池操作
        self.assertEqual(hand_ids(b), [])

    def test_repeat_every_num1_turns(self):
        db = get_db()
        every = db.get(self.TID).num(1)
        self.assertEqual(every, 2)
        g = make_game(seed=5302)
        a = g.heroes[0]
        trinket = offer_and_buy(g, a, self.TID, "lesser")
        for _ in range(every - 1):
            g.run_script_hook(trinket, "start_of_turn")
        self.assertEqual(hand_ids(a), [self.TOKEN])
        g.run_script_hook(trinket, "start_of_turn")
        self.assertEqual(hand_ids(a), [self.TOKEN, self.TOKEN])
        # 滚动: 再满 every-1 次不发放
        for _ in range(every - 1):
            g.run_script_hook(trinket, "start_of_turn")
        self.assertEqual(hand_ids(a), [self.TOKEN, self.TOKEN])

    def test_opponent_turn_start_does_not_grant(self):
        g = make_game(seed=5303)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        for _ in range(4):
            g.events.fire(g, "turn_start", turn=g.turn)
        self.assertEqual(hand_ids(b), [])
        self.assertEqual(hand_ids(a), [self.TOKEN])   # 正对照


if __name__ == "__main__":
    unittest.main()
