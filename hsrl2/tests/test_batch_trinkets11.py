"""批次 trinkets11 行为层测试（台账片 1: 13 注册 + 7 DEFERRED; 429/432 由主线解冻）。

全部断言走真实引擎路径:
  - 购买: 真实 `game._offer_trinkets` 三选一 + PendingChoice.choose
    （resolve 扣费 → hero.trinkets → run_script_hook(on_bind)）
  - SoC / 战斗: 真实 `game.run_combat(a, b)`（读到 SoC 结算后状态的探针 =
    `START_OF_COMBAT` 事件——引擎在饰品/奖励/随从 SoC 钩子**之后**广播）
  - 战斗收尾: 真实 `game.end_recruit_phase()`（COMBAT_END 广播 = 战斗内
    授予的亡语 override 恢复点）
  - SoT: 真实 `game._begin_recruit_for(a)`
  - 死亡: 真实 `game.check_deaths()`（招募期）/ `game.combat_death_log`
    路径（战斗内）
  - 受伤: 真实 `hero.take_damage`（HERO_DAMAGE_TAKEN）
  - 池: `minion_pool.available` / `spell_pool.available` 前后差

覆盖（SOP §16 空转测试判定法——每个效果类都有正对照 + 无饰品对照）:
  - owner 隔离（两英雄: 每个效果都有"对手活动不生效"断言）
  - 跨回合/一次性语义（COMBAT_END 恢复、SoT 重复、AoE 阶段守卫）
  - 池占返（"Get" 占池、token 不占池、Summon 零池操作、池空落空）
  - 数值与 `CardDef.num` 双向钉死（阈值/基数/文本字面量前提）
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions.bloodgem import BLOOD_GEM_VARIANTS, PlayBloodGems
from hsrl2.db import CardDB
from hsrl2.events import MINION_OVERFLOW, START_OF_COMBAT, SUMMON, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_trinkets11 as B11
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有卡（CardDB 按名核实，非凭记忆 id）
ETERNAL_KNIGHT = "BG25_008"      # Eternal Knight 4/2 T2 Undead（池随从）
ETERNAL_KNIGHT_G = "BG25_008_G"  # 金色独立卡定义 8/4
AUTOMATON = "BG_TTN_401"         # Ancestral Automaton 3/4 T2 Mech（池随从）
TITUS = "BG25_354"               # Titus Rivendare 1/7 T5（池随从）
QUILBOAR = "BG20_100"            # Razorfen Geomancer 2/1 T1 Quilboar（无 Rally）
PLAIN = "BG33_140"               # River Skipper 1/1 T1 Murloc（无关键词）
PIRATE = "BG26_135"              # Southsea Busker 3/1 T1 海盗（战吼）
GOLEM = "BG30_MagicItem_442t"    # Blood Golem token（非池卡）
GEM_IDS = frozenset(BLOOD_GEM_VARIANTS.values())

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 900, anomaly: str | None = None) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed, anomaly=anomaly)
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


def offer_and_abandon(game: Game, hero: Hero, kind: str) -> None:
    """同一 rng 消耗路径但不获得饰品（对照用——保持两局 rng 状态一致）。"""
    hero.gold = 50
    game._offer_trinkets(hero, kind)
    choice = game.pending_choices.pop(0)
    choice.choose(len(choice.options) - 1)   # 末位 = None（放弃）


def put(game: Game, hero: Hero, m: Minion) -> Minion:
    assert game.summon(hero, m)
    return m


def soc_snapshot(game: Game, hero: Hero, fn) -> dict:
    """注册 SoC 后观测器: fn() 的返回值写入并返回 seen 字典。

    `START_OF_COMBAT` 每英雄各广播一次 → 按 `hero is` 过滤（闭包默认参数
    绑定，防晚绑定——SOP §11 item 1）。
    """
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


def drain_pool(game: Game, pred, keep: str | None = None) -> None:
    for d in get_db().pool_minions():
        if keep is not None and d.id == keep:
            continue
        if not pred(d):
            continue
        while game.minion_pool.available(d.id) > 0:
            game.minion_pool.acquire(d.id)


def pirate_pred(d) -> bool:
    # 类型身份集合（AC-3）: 双类型海盗身份同样计入（"pool empty" 需真正
    # 抽干全部海盗身份候选——wiki `Multi-type minion` revid 855346）。
    return Race.PIRATE in d.races


def make_tavern_minion(game: Game, hero: Hero, card_id: str = PLAIN):
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


class TestRegistryState(unittest.TestCase):
    """注册面 + 数据链/参数一致性（结构性）——@engine-only

    与脚本钩子无关（注册表/卡定义/档位/数据链），存活属预期。
    """

    IMPLEMENTED = (
        "BG30_MagicItem_301", "BG30_MagicItem_303", "BG30_MagicItem_310",
        "BG30_MagicItem_407", "BG30_MagicItem_410", "BG30_MagicItem_411",
        "BG30_MagicItem_420", "BG30_MagicItem_429", "BG30_MagicItem_432",
        "BG30_MagicItem_438t", "BG30_MagicItem_441", "BG30_MagicItem_442",
        "BG30_MagicItem_541",
    )
    # 2026-09-02 主线解冻 429（饰品版 Spellcraft 生成点）与 432（Venomous
    # 失去事件）——见 batch_trinkets11 模块 docstring 与引擎提交
    # 2026-09-14 batch_trinkets27 解冻 423 Innkeeper's Stein（展示位档位
    # 协议 TAVERN_EXTRA_TIER_SLOTS/TAVERN_EXTRA_TIER）→ 移出本 DEFERRED
    # 台账（该卡现由 batch_trinkets27 注册，守卫见 test_batch_trinkets27）
    DEFERRED = (
        "BG30_MagicItem_402", "BG30_MagicItem_416",
        "BG30_MagicItem_431",
    )
    # 418 Bronzebeard Portrait 已由 batch_family_races 注册（2026-09-21，
    # RACES 家族类型身份改写）→ 移出本 DEFERRED 台账
    # （守卫见 test_batch_family_races）
    # 440 Boom Controller 已由 batch_trinkets32 注册（`combat_slot_freed`
    # 腾位协议 + `_combat_dead_snaps` exact copy，2026-09-15）→ 移出本
    # DEFERRED 台账（守卫见 test_batch_trinkets32）
    # 439 Designer Eyepatch（已由 batch_misc_final 注册）/ 156 Flaming
    # Portrait（同）→ 迁出本 DEFERRED 台账（守卫见 test_batch_misc_final）
    KIND = {
        "BG30_MagicItem_301": "lesser", "BG30_MagicItem_303": "lesser",
        "BG30_MagicItem_310": "greater", "BG30_MagicItem_407": "lesser",
        "BG30_MagicItem_410": "lesser", "BG30_MagicItem_411": "lesser",
        "BG30_MagicItem_420": "lesser", "BG30_MagicItem_438t": "greater",
        "BG30_MagicItem_441": "greater", "BG30_MagicItem_442": "greater",
        "BG30_MagicItem_541": "greater",
    }
    CLASSES = {
        "BG30_MagicItem_429": "DemonbloodGourdScript",
        "BG30_MagicItem_432": "BelcherPortraitScript",
        "BG30_MagicItem_301": "EternalPortraitScript",
        "BG30_MagicItem_303": "AutomatonPortraitScript",
        "BG30_MagicItem_310": "RivendarePortraitScript",
        "BG30_MagicItem_407": "ShipInABottleScript",
        "BG30_MagicItem_410": "QuilligraphySetScript",
        "BG30_MagicItem_411": "HoggyBankScript",
        "BG30_MagicItem_420": "BookOfMedivhScript",
        "BG30_MagicItem_438t": "MugOfTheSireScript",
        "BG30_MagicItem_441": "TinyfinOnesieScript",
        "BG30_MagicItem_442": "BloodGolemStickerScript",
        "BG30_MagicItem_541": "NetherPendantScript",
    }

    def test_all_ids_registered(self):
        self.assertEqual(len(self.IMPLEMENTED), 13)
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)
            self.assertIs(REGISTRY[tid], getattr(B11, self.CLASSES[tid]), tid)
            self.assertIsNotNone(get_db().get(tid), tid)

    def test_deferred_ids_not_registered(self):
        """二态铁律: DEFERRED 卡必须**不注册**（SOP §6b）。"""
        # 418 已由 batch_family_races 注册（2026-09-21）→ 4 降为 3
        self.assertEqual(len(self.DEFERRED), 3)
        for tid in self.DEFERRED:
            self.assertNotIn(tid, REGISTRY, tid)
            self.assertIsNotNone(get_db().get(tid), tid)

    def test_offer_pool_membership(self):
        """商店池成员 + 档位（spell_school 11=Lesser / 12=Greater）。"""
        db = get_db()
        offer_ids = {d.id for d in db.trinket_offer_pool()}
        for tid, kind in self.KIND.items():
            self.assertIn(tid, offer_ids, tid)
            self.assertEqual(db.get(tid).spell_school,
                             11 if kind == "lesser" else 12, tid)

    def test_mug_of_the_sire_is_standalone_shop_trinket(self):
        """`_438t` 无同名本体 → 不是升级变体（作业单前置判断的运行时证据）。"""
        db = get_db()
        self.assertIn("BG30_MagicItem_438t",
                      {d.id for d in db.trinket_offer_pool()})
        names = [d.name for d in db.trinket_offer_pool()
                 if d.name == db.get("BG30_MagicItem_438t").name]
        self.assertEqual(names, ["Mug of the Sire"])

    def test_carddef_evolution_chain(self):
        """"Get an X" 全部经 `evolution_card_id` 数据链（零硬编码卡 id）。"""
        db = get_db()
        pairs = {
            "BG30_MagicItem_301": (ETERNAL_KNIGHT, True),
            # 37.0: Ancestral Automaton 退出池内随从（is_pool_minion=False）
            "BG30_MagicItem_303": (AUTOMATON, False),
            "BG30_MagicItem_310": (TITUS, True),
        }
        for tid, (target, is_pool) in pairs.items():
            d = db.get(tid)
            self.assertIsNotNone(d.evolution_card_id, tid)
            token = db.by_dbf(d.evolution_card_id)
            self.assertIsNotNone(token, tid)
            self.assertEqual(token.id, target, tid)
            self.assertEqual(token.is_pool_minion, is_pool, tid)

    def test_numeric_params_pinned(self):
        """数值权威: 类属性阈值 == CardDef.num; 文本字面量前提钉死。"""
        db = get_db()
        self.assertEqual(
            B11.QuilligraphySetScript.avenge_threshold,
            db.get("BG30_MagicItem_410").num(0))
        self.assertEqual(db.get("BG30_MagicItem_410").num(0), 3)
        self.assertEqual(db.get("BG30_MagicItem_541").num(0), 3)
        self.assertEqual(db.get("BG30_MagicItem_541").num(1), 2)
        for tid in ("BG30_MagicItem_407", "BG30_MagicItem_411",
                    "BG30_MagicItem_438t", "BG30_MagicItem_441",
                    "BG30_MagicItem_442"):
            self.assertIsNone(db.get(tid).num(0), tid)
            self.assertIsNone(db.get(tid).num(1), tid)


# ══════════════ BG30_MagicItem_301 Eternal Portrait ══════════════

class TestEternalPortrait(unittest.TestCase):
    TID = "BG30_MagicItem_301"

    def test_bind_gets_eternal_knight_from_pool(self):
        g = make_game(seed=3001)
        a = g.heroes[0]
        before = g.minion_pool.available(ETERNAL_KNIGHT)
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual([e.card_id for e in a.hand], [ETERNAL_KNIGHT])
        self.assertEqual(g.minion_pool.available(ETERNAL_KNIGHT), before - 1)

    def test_pool_exhausted_gets_nothing(self):
        g = make_game(seed=3002)
        a = g.heroes[0]
        drain_pool(g, lambda d: d.id == ETERNAL_KNIGHT)
        trinket = offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual(a.hand, [])                # 关联卡落空
        self.assertEqual(len(a.trinkets), 1)
        self.assertEqual(g.minion_pool.available(ETERNAL_KNIGHT), 0)
        # 正对照: 同一绑定钩子在池恢复后确实发放（池空才是落空原因）
        g.minion_pool.release(ETERNAL_KNIGHT, 1)
        g.run_script_hook(trinket, "on_bind", ctx={"hero": a})
        self.assertEqual([e.card_id for e in a.hand], [ETERNAL_KNIGHT])

    def _soc(self, seed, with_trinket):
        """双方各放同族探针: 本营必须被授予、敌营必须不被授予。"""
        g = make_game(seed=seed)
        a, b = g.heroes
        if with_trinket:
            offer_and_buy(g, a, self.TID, "lesser")
        probes = {}
        for side, hero in (("mine", a), ("theirs", b)):
            knight = put(g, hero, g.create_minion(ETERNAL_KNIGHT,
                                                  controller=hero))
            golden = put(g, hero, g.create_minion(ETERNAL_KNIGHT,
                                                  controller=hero,
                                                  golden=True))
            other = put(g, hero, g.create_minion(PLAIN, controller=hero))
            probes[side] = (knight, golden, other)
        seen = soc_snapshot(g, a, lambda: {
            side: ((k.has(GameTag.TAUNT), k.has(GameTag.REBORN)),
                   (gd.has(GameTag.TAUNT), gd.has(GameTag.REBORN)),
                   (o.has(GameTag.TAUNT), o.has(GameTag.REBORN)))
            for side, (k, gd, o) in probes.items()})
        g.run_combat(a, b)
        return seen.get("v")

    def test_soc_gives_taunt_and_reborn_to_knights_only(self):
        v = self._soc(3011, with_trinket=True)
        self.assertEqual(v["mine"][0], (True, True))      # 正对照
        self.assertEqual(v["mine"][1], (True, True))      # 金色同族
        self.assertEqual(v["mine"][2], (False, False))    # 非 Knight 不授予
        self.assertEqual(v["theirs"][0], (False, False))  # owner 隔离
        self.assertEqual(v["theirs"][1], (False, False))

    def test_control_without_trinket(self):
        v = self._soc(3012, with_trinket=False)
        self.assertEqual(v["mine"][0], (False, False))
        self.assertEqual(v["mine"][1], (False, False))
        self.assertEqual(v["theirs"][0], (False, False))

    def test_opponent_knights_not_granted(self):
        v = self._soc(3013, with_trinket=True)
        self.assertEqual(v["mine"][0], (True, True))      # 正对照: 本营确实生效
        self.assertEqual(v["theirs"][0], (False, False))  # owner 隔离
        self.assertEqual(v["theirs"][1], (False, False))


# ══════════════ BG30_MagicItem_303 Automaton Portrait ══════════════

class TestAutomatonPortrait(unittest.TestCase):
    TID = "BG30_MagicItem_303"

    def _soc(self, seed, with_trinket, full=False):
        g = make_game(seed=seed)
        a, b = g.heroes
        if with_trinket:
            offer_and_buy(g, a, self.TID, "lesser")
        for _ in range(7 if full else 1):
            put(g, a, g.create_minion(PLAIN, controller=a))
        overflow = []
        g.events.register(Listener(
            event=MINION_OVERFLOW, owner=a,
            callback=lambda gg, minion=None, **kw: overflow.append(minion)
            if minion is not None and minion.controller is a else None))
        seen = soc_snapshot(g, a, lambda: {
            "auto": sum(1 for m in a.board if m.card_id == AUTOMATON),
            "size": len(a.board),
        })
        pool_before = g.minion_pool.total_remaining()
        g.run_combat(a, b)
        return seen.get("v"), overflow, pool_before, g

    def test_soc_summons_one_automaton(self):
        v, overflow, pool_before, g = self._soc(3021, with_trinket=True)
        self.assertEqual(v["auto"], 1)
        self.assertEqual(v["size"], 2)               # 原 1 + 召唤 1
        self.assertEqual(g.minion_pool.total_remaining(), pool_before)  # Summon 不占池
        self.assertEqual(overflow, [])

    def test_full_board_no_summon_no_overflow(self):
        v, overflow, _, _ = self._soc(3022, with_trinket=True, full=True)
        self.assertEqual(v["auto"], 0)
        self.assertEqual(v["size"], 7)
        self.assertEqual(overflow, [])               # "有空位才召唤"≠失败召唤
        # 正对照: 同一饰品在腾出板位后再战确实召唤
        g = make_game(seed=3022)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        for _ in range(7):
            put(g, a, g.create_minion(PLAIN, controller=a))
        g.run_combat(a, b)
        a.board.pop()                                # 腾出 1 个板位
        seen2 = soc_snapshot(g, a, lambda: sum(
            1 for m in a.board if m.card_id == AUTOMATON))
        g.run_combat(a, b)
        self.assertEqual(seen2.get("v"), 1)

    def test_control_without_trinket(self):
        v, _, _, _ = self._soc(3023, with_trinket=False)
        self.assertEqual(v["auto"], 0)

    def test_opponent_board_untouched(self):
        g = make_game(seed=3024)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        put(g, b, g.create_minion(PLAIN, controller=b))
        seen = soc_snapshot(g, b, lambda: {
            "mine": [m.card_id for m in a.board],
            "theirs": [m.card_id for m in b.board],
        })
        g.run_combat(a, b)
        v = seen["v"]
        self.assertEqual(v["mine"], [AUTOMATON])          # 正对照
        self.assertEqual(v["theirs"], [PLAIN])            # owner 隔离


# ══════════════ BG30_MagicItem_310 Rivendare Portrait ══════════════

class TestRivendarePortrait(unittest.TestCase):
    TID = "BG30_MagicItem_310"

    def test_bind_gets_titus_from_pool(self):
        g = make_game(seed=3101)
        a = g.heroes[0]
        before = g.minion_pool.available(TITUS)
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual([e.card_id for e in a.hand], [TITUS])
        self.assertEqual(g.minion_pool.available(TITUS), before - 1)

    def _soc(self, seed, with_trinket):
        g = make_game(seed=seed)
        a, b = g.heroes
        if with_trinket:
            offer_and_buy(g, a, self.TID, "greater")
        probes = {}
        for side, hero in (("mine", a), ("theirs", b)):
            probes[side] = (
                put(g, hero, g.create_minion(TITUS, controller=hero)),
                put(g, hero, g.create_minion(PLAIN, controller=hero)))
        seen = soc_snapshot(g, a, lambda: {
            side: ((t.atk, t.max_health), (o.atk, o.max_health))
            for side, (t, o) in probes.items()})
        g.run_combat(a, b)
        return seen.get("v")

    def test_soc_doubles_titus_health_only(self):
        v = self._soc(3111, with_trinket=True)
        d = get_db().get(TITUS)
        p = get_db().get(PLAIN)
        self.assertEqual(v["mine"][0], (d.atk, d.health * 2))  # 正对照
        self.assertEqual(v["mine"][1], (p.atk, p.health))      # 非 Titus 不变
        self.assertEqual(v["theirs"][0], (d.atk, d.health))    # owner 隔离

    def test_control_without_trinket(self):
        v = self._soc(3112, with_trinket=False)
        d = get_db().get(TITUS)
        self.assertEqual(v["mine"][0], (d.atk, d.health))
        self.assertEqual(v["theirs"][0], (d.atk, d.health))

    def test_opponent_titus_not_doubled(self):
        v = self._soc(3113, with_trinket=True)
        d = get_db().get(TITUS)
        self.assertEqual(v["mine"][0], (d.atk, d.health * 2))  # 正对照
        self.assertEqual(v["theirs"][0], (d.atk, d.health))    # owner 隔离


# ══════════════ BG30_MagicItem_407 Ship in a Bottle ══════════════

class TestShipInABottle(unittest.TestCase):
    TID = "BG30_MagicItem_407"

    def _run(self, seed, with_trinket, full=False, drained=False):
        g = make_game(seed=seed)
        a, b = g.heroes
        if drained:
            drain_pool(g, pirate_pred)
        if with_trinket:
            offer_and_buy(g, a, self.TID, "lesser")
        if full:
            for _ in range(7):
                put(g, a, g.create_minion(PLAIN, controller=a))
        defender = put(g, b, g.create_minion(TITUS, controller=b))
        defender.set(GameTag.BASE_ATK, 0)          # 不反击 → 召唤体存活
        hp_before = defender.health
        summoned = []
        g.events.register(Listener(
            event=SUMMON, owner=a,
            callback=lambda gg, minion=None, **kw: summoned.append(
                (minion, minion.atk))
            if minion is not None and minion.controller is a else None))
        seen = soc_snapshot(g, a, lambda: {
            "dmg": hp_before - defender.health,
            "board": [m.card_id for m in a.board],
        })
        pool_before = g.minion_pool.total_remaining()
        g.run_combat(a, b)
        return g, seen.get("v"), summoned, pool_before

    def test_soc_summons_gets_copy_and_attacks(self):
        g, v, summoned, pool_before = self._run(3121, with_trinket=True)
        self.assertEqual(len(summoned), 1)
        pirate, atk_at_summon = summoned[0]
        self.assertTrue(pirate.has_race(Race.PIRATE))
        self.assertEqual(v["board"], [pirate.card_id])       # 召唤体在场
        self.assertEqual(v["dmg"], atk_at_summon)            # 立即攻击已发生
        self.assertEqual([e.card_id for e in g.heroes[0].hand],
                         [pirate.card_id])                   # "get" 入手同卡
        self.assertEqual(g.minion_pool.total_remaining(), pool_before - 1)

    def test_full_board_gets_copy_only(self):
        g, v, summoned, _ = self._run(3122, with_trinket=True, full=True)
        self.assertEqual(summoned, [])                       # 满板不召唤
        a = g.heroes[0]
        self.assertEqual(len(a.board), 7)
        self.assertEqual(len(a.hand), 1)
        self.assertIn(a.hand[0].race, (Race.PIRATE, Race.ALL))

    def test_pool_empty_no_effect(self):
        g, v, summoned, _ = self._run(3123, with_trinket=True, drained=True)
        self.assertEqual(summoned, [])
        a = g.heroes[0]
        self.assertEqual(a.hand, [])
        self.assertEqual(a.board, [])
        # 正对照: 池里放回 1 个海盗后同一饰品确实召唤并入手。
        # 断言分两层以对 RNG 稳健: (a) 召唤事件与"get"入手不依赖召唤体
        # 是否存活; (b) 敌方随从全为 0 攻（不反击）→ 召唤体必存活。
        g.minion_pool.release(PIRATE, 1)
        b = g.heroes[1]
        decoy = put(g, b, g.create_minion(PLAIN, controller=b))
        decoy.set(GameTag.BASE_ATK, 0)
        summoned2 = []
        g.events.register(Listener(
            event=SUMMON, owner=a,
            callback=lambda gg, minion=None, **kw: summoned2.append(
                minion.card_id)
            if minion is not None and minion.controller is a else None))
        seen2 = soc_snapshot(g, a, lambda: [m.card_id for m in a.board])
        g.run_combat(a, b)
        self.assertEqual(summoned2, [PIRATE])               # 召唤已发生
        self.assertEqual([e.card_id for e in a.hand], [PIRATE])   # "get" 入手
        self.assertEqual(seen2.get("v"), [PIRATE])          # 召唤体存活

    def test_control_without_trinket(self):
        g, v, summoned, _ = self._run(3124, with_trinket=False)
        self.assertEqual(summoned, [])
        self.assertEqual(g.heroes[0].hand, [])
        self.assertEqual(v["dmg"], 0)

    def test_opponent_actions_do_not_benefit_owner(self):
        g = make_game(seed=3125)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        put(g, b, g.create_minion(TITUS, controller=b))   # 高生命: 不被立即攻击杀死
        seen = soc_snapshot(g, b, lambda: {
            "mine": [m.card_id for m in a.board],
            "theirs": [m.card_id for m in b.board],
        })
        g.run_combat(a, b)
        v = seen["v"]
        self.assertEqual(len(v["mine"]), 1)               # 正对照: 本人有召唤
        self.assertEqual(v["theirs"], [TITUS])            # owner 隔离
        self.assertEqual([e.card_id for e in b.hand], []) # 对手无入手


# ══════════════ BG30_MagicItem_410 Quilligraphy Set ══════════════

class TestQuilligraphySet(unittest.TestCase):
    TID = "BG30_MagicItem_410"

    def test_avenge_improves_blood_gem_health_only(self):
        g = make_game(seed=3201)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        n = get_db().get(self.TID).num(0)
        victims = []
        for _ in range(n - 1):
            victims.append(put(g, a, g.create_minion(PLAIN, controller=a)))
        for v in victims:
            death_in_combat(g, v)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 0)
        extra = put(g, a, g.create_minion(PLAIN, controller=a))
        death_in_combat(g, extra)                    # 第 num(0) 次 → 达标
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 1)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 0)

    def test_gem_really_heals_one_more_than_control(self):
        gd = get_db().get("BG20_GEM")

        def play_one(seed, with_trinket):
            g = make_game(seed=seed)
            a = g.heroes[0]
            if with_trinket:
                offer_and_buy(g, a, self.TID, "lesser")
                for _ in range(get_db().get(self.TID).num(0)):
                    v = put(g, a, g.create_minion(PLAIN, controller=a))
                    death_in_combat(g, v)
            target = put(g, a, g.create_minion(PLAIN, controller=a))
            base_h = target.max_health
            g.run_actions(PlayBloodGems(target, 1))
            return base_h, target.max_health

        b0, h0 = play_one(3202, with_trinket=False)
        b1, h1 = play_one(3203, with_trinket=True)
        self.assertEqual(h0 - b0, gd.num(1))
        self.assertEqual(h1 - b1, gd.num(1) + 1)     # 正对照: 恰好 +1

    def test_recruit_phase_deaths_not_counted(self):
        g = make_game(seed=3204)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        n0 = get_db().get(self.TID).num(0)
        self.assertFalse(g.in_combat)
        for _ in range(n0):
            v = put(g, a, g.create_minion(PLAIN, controller=a))
            v.set(GameTag.HEALTH, 0)
            g.check_deaths()                         # 招募期死亡
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 0)
        # 正对照: 同样的 num(0) 次死亡发生在**战斗内**则恰好达标
        for _ in range(n0):
            v = put(g, a, g.create_minion(PLAIN, controller=a))
            death_in_combat(g, v)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 1)

    def test_opponent_deaths_not_counted(self):
        g = make_game(seed=3205)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        n0 = get_db().get(self.TID).num(0)
        for _ in range(n0):
            v = put(g, b, g.create_minion(PLAIN, controller=b))
            death_in_combat(g, v)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 0)
        for _ in range(n0):                          # 正对照: 本人死亡才计数
            v = put(g, a, g.create_minion(PLAIN, controller=a))
            death_in_combat(g, v)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 1)


# ══════════════ BG30_MagicItem_411 Hoggy Bank ══════════════

class TestHoggyBank(unittest.TestCase):
    TID = "BG30_MagicItem_411"

    def _combat(self, seed, with_trinket, owner="a"):
        g = make_game(seed=seed)
        a, b = g.heroes
        target = a if owner == "a" else b
        if with_trinket:
            offer_and_buy(g, a, self.TID, "lesser")
        quil = put(g, target, g.create_minion(QUILBOAR, controller=target))
        nonq = put(g, target, g.create_minion(PLAIN, controller=target))
        marks = soc_snapshot(g, a, lambda: (
            quil.has(GameTag.DEATHRATTLE),
            nonq.has(GameTag.DEATHRATTLE)))
        killer = g.create_minion(TITUS, controller=b if target is a else a)
        killer.set(GameTag.BASE_ATK, 99)
        put(g, b if target is a else a, killer)
        g.run_combat(a, b)
        gems = [e.card_id for e in target.hand if e.card_id in GEM_IDS]
        return g, marks.get("v"), gems, target

    def test_soc_grants_deathrattle_to_quilboar_only(self):
        _, v, _, _ = self._combat(3301, with_trinket=True)
        self.assertEqual(v, (True, False))

    def test_deathrattle_gets_two_blood_gems(self):
        _, _, gems, _ = self._combat(3302, with_trinket=True)
        self.assertEqual(gems, ["BG20_GEM", "BG20_GEM"])

    def test_control_without_trinket(self):
        _, v, gems, _ = self._combat(3303, with_trinket=False)
        self.assertEqual(v, (False, False))
        self.assertEqual(gems, [])

    def test_opponent_quilboar_not_granted(self):
        g = make_game(seed=3304)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        mine = put(g, a, g.create_minion(QUILBOAR, controller=a))
        theirs = put(g, b, g.create_minion(QUILBOAR, controller=b))
        v = soc_snapshot(g, a, lambda: (mine.has(GameTag.DEATHRATTLE),
                                        theirs.has(GameTag.DEATHRATTLE)))
        g.run_combat(a, b)
        self.assertEqual(v.get("v"), (True, False))  # 正对照 + owner 隔离

    def test_effect_is_this_combat_only(self):
        g = make_game(seed=3305)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        quil = put(g, a, g.create_minion(QUILBOAR, controller=a))
        during = soc_snapshot(g, a, lambda: bool(quil._script_overrides))
        g.end_recruit_phase()                        # 真实 SoC + COMBAT_END
        self.assertTrue(during.get("v"), "战斗内必须已授予亡语")   # 正对照
        self.assertEqual(quil._script_overrides, {})  # override 已恢复
        self.assertFalse(quil.has(GameTag.DEATHRATTLE))
        before = len([e for e in a.hand if e.card_id in GEM_IDS])
        death_in_combat(g, quil)                     # 战后死亡不再给宝石
        after = len([e for e in a.hand if e.card_id in GEM_IDS])
        self.assertEqual(after - before, 0)


# ══════════════ BG30_MagicItem_420 Book of Medivh ══════════════

class TestBookOfMedivh(unittest.TestCase):
    TID = "BG30_MagicItem_420"

    def test_bind_discovers_tavern_spell(self):
        g = make_game(seed=3401)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual(len(g.pending_choices), 1)
        choice = g.pending_choices.pop(0)
        self.assertIs(choice.owner, a)
        self.assertEqual(choice.kind, "discover_tavern_spell")
        self.assertEqual(len(choice.options), 3)
        for cid in choice.options:
            self.assertTrue(get_db().get(cid).is_pool_spell, cid)
        picked = choice.options[0]
        choice.choose(0)
        self.assertEqual([e.card_id for e in a.hand], [picked])

    def test_start_of_turn_discovers_again(self):
        g = make_game(seed=3402)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        g.pending_choices.clear()
        g.turn = 2
        g._begin_recruit_for(a)                      # 真实 SoT 分发
        self.assertEqual([c.kind for c in g.pending_choices],
                         ["discover_tavern_spell"])
        self.assertEqual([c.owner for c in g.pending_choices], [a])
        g._begin_recruit_for(b)                      # 对手 SoT 无选择
        self.assertEqual(len(g.pending_choices), 1)

    def test_pool_exhausted_no_choice(self):
        g = make_game(seed=3403)
        a = g.heroes[0]
        drain_pool(g, lambda d: True)                # 清空随从池（含伪装）
        while True:
            spells = [d.id for d in get_db().pool_spells()
                      if g.spell_pool.available(d.id) > 0]
            if not spells:
                break
            g.spell_pool.acquire(spells[0])
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual(g.pending_choices, [])
        # 正对照: 池中放回 1 张酒馆法术 → 同一饰品的 SoT 确实产出选择
        g.spell_pool.release("BG28_503")
        g.turn = 2
        g._begin_recruit_for(a)
        self.assertEqual([c.kind for c in g.pending_choices],
                         ["discover_tavern_spell"])

    # ── 异变 101/102 存在档白名单（真实 start_game + 真实饰品绑定）──
    # 2026-09-02 对抗审查 must-fix: 旧实现直接 `db.pool_spells()`
    # `min_tier <= tech_level <= tier`，101 的 T3 曾给出含 T2 的选项。

    def _option_tiers(self, game, hero) -> list:
        offer_and_buy(game, hero, self.TID, "lesser")
        choice = game.pending_choices.pop(0)
        assert choice.kind == "discover_tavern_spell"
        return sorted(get_db().get(cid).tech_level
                      for cid in choice.options)

    def test_anomaly_101_t3_options_exclude_nonexistent_tier2(self):
        """101 "Only Tavern Tiers 1, 3, and 5 exist" 下 T3 选项 ⊆ {1,3}。"""
        g = make_game(seed=3402, anomaly="BG27_Anomaly_101")
        a = g.heroes[0]
        a.set(GameTag.TAVERN_TIER, 3)
        tiers = self._option_tiers(g, a)
        self.assertEqual(len(tiers), 3)
        self.assertTrue(set(tiers) <= {1, 3}, tiers)
        self.assertNotIn(2, tiers)                   # 非存在档（泄漏复现）
        # 正对照（负控制）: 标准局同 seed/T3 确实给出 T2 选项
        c = make_game(seed=3402)
        b = c.heroes[0]
        b.set(GameTag.TAVERN_TIER, 3)
        self.assertIn(2, self._option_tiers(c, b))

    def test_anomaly_102_t4_options_only_existing_tiers(self):
        """102 "Only Tavern Tiers 2, 4, and 6 exist" 下 T4 选项 ⊆ {2,4,6}。"""
        g = make_game(seed=3401, anomaly="BG27_Anomaly_102")
        a = g.heroes[0]
        a.set(GameTag.TAVERN_TIER, 4)
        tiers = self._option_tiers(g, a)
        self.assertEqual(len(tiers), 3)
        self.assertTrue(set(tiers) <= {2, 4, 6}, tiers)
        # 正对照: 标准局同 seed/T4 至少给出一个非存在档（1 或 3）
        c = make_game(seed=3401)
        b = c.heroes[0]
        b.set(GameTag.TAVERN_TIER, 4)
        self.assertTrue({1, 3} & set(self._option_tiers(c, b)))


# ══════════════ BG30_MagicItem_438t Mug of the Sire ══════════════

class TestMugOfTheSire(unittest.TestCase):
    TID = "BG30_MagicItem_438t"

    def test_overflow_buffs_all_friendly_minions(self):
        g = make_game(seed=3501)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        board = [put(g, a, g.create_minion(PLAIN, controller=a))
                 for _ in range(7)]
        base = [m.atk for m in board]
        hand = g.create_minion(PLAIN, controller=a)
        a.hand.append(hand)
        self.assertFalse(g.play_minion(a, hand))     # 满员 → 召唤失败
        self.assertEqual([m.atk for m in board], [b + 5 for b in base])
        self.assertEqual(a.hand, [hand])             # 手牌随从未被消耗

    def test_successful_play_no_buff(self):
        g = make_game(seed=3502)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        first = put(g, a, g.create_minion(PLAIN, controller=a))
        base = first.atk
        hand = g.create_minion(PLAIN, controller=a)
        a.hand.append(hand)
        self.assertTrue(g.play_minion(a, hand))      # 有空位 → 正常入场
        self.assertEqual(first.atk, base)            # 无溢出 → 无加成
        # 正对照: 同 setup 下真正溢出（满员）时确实 +5 攻
        for _ in range(5):
            put(g, a, g.create_minion(PLAIN, controller=a))
        self.assertEqual(len(a.board), 7)
        over = g.create_minion(PLAIN, controller=a)
        a.hand.append(over)
        self.assertFalse(g.play_minion(a, over))
        self.assertEqual(first.atk, base + 5)

    def test_dead_minion_not_buffed(self):
        g = make_game(seed=3503)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        board = [put(g, a, g.create_minion(PLAIN, controller=a))
                 for _ in range(7)]
        corpse = board[-1]
        corpse.set(GameTag.HEALTH, 0)                # 未处理死亡: 仍占板位
        base = [m.atk for m in board[:-1]]
        hand = g.create_minion(PLAIN, controller=a)
        a.hand.append(hand)
        self.assertFalse(g.play_minion(a, hand))
        self.assertEqual([m.atk for m in board[:-1]],
                         [b + 5 for b in base])
        self.assertEqual(corpse.atk, get_db().get(PLAIN).atk)

    def test_opponent_overflow_not_buffed(self):
        g = make_game(seed=3504)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        mine = put(g, a, g.create_minion(PLAIN, controller=a))
        base = mine.atk
        for _ in range(7):
            put(g, b, g.create_minion(PLAIN, controller=b))
        hand = g.create_minion(PLAIN, controller=b)
        b.hand.append(hand)
        b.gold = 50
        self.assertFalse(g.play_minion(b, hand))     # owner 隔离
        self.assertEqual(mine.atk, base)
        # 正对照: 本人满员召唤失败 → 本人随从 +5 攻
        for _ in range(6):
            put(g, a, g.create_minion(PLAIN, controller=a))
        mine_hand = g.create_minion(PLAIN, controller=a)
        a.hand.append(mine_hand)
        a.gold = 50
        self.assertFalse(g.play_minion(a, mine_hand))
        self.assertEqual(mine.atk, base + 5)

    def test_control_without_trinket(self):
        g = make_game(seed=3505)
        a = g.heroes[0]
        board = [put(g, a, g.create_minion(PLAIN, controller=a))
                 for _ in range(7)]
        base = [m.atk for m in board]
        hand = g.create_minion(PLAIN, controller=a)
        a.hand.append(hand)
        self.assertFalse(g.play_minion(a, hand))
        self.assertEqual([m.atk for m in board], base)


# ══════════════ BG30_MagicItem_441 Tinyfin Onesie ══════════════

class TestTinyfinOnesie(unittest.TestCase):
    TID = "BG30_MagicItem_441"

    def _soc(self, seed, with_trinket, hand_ids):
        g = make_game(seed=seed)
        a, b = g.heroes
        if with_trinket:
            offer_and_buy(g, a, self.TID, "greater")
        left = put(g, a, g.create_minion(PLAIN, controller=a))
        other = put(g, a, g.create_minion(PLAIN, controller=a))
        for cid in hand_ids:
            a.hand.append(g.create_minion(cid, controller=a))
        seen = soc_snapshot(g, a, lambda: {
            "left": (left.atk, left.max_health),
            "other": (other.atk, other.max_health),
        })
        g.run_combat(a, b)
        return seen.get("v")

    def test_leftmost_gains_stats_of_highest_health_in_hand(self):
        v = self._soc(3601, with_trinket=True,
                      hand_ids=[PLAIN, TITUS])       # Titus 1/7 最高生命
        p, t = get_db().get(PLAIN), get_db().get(TITUS)
        self.assertEqual(v["left"], (p.atk + t.atk, p.health + t.health))
        self.assertEqual(v["other"], (p.atk, p.health))   # 非最左不变

    def test_control_without_trinket(self):
        v = self._soc(3602, with_trinket=False, hand_ids=[TITUS])
        p = get_db().get(PLAIN)
        self.assertEqual(v["left"], (p.atk, p.health))

    def test_empty_hand_no_change(self):
        v = self._soc(3603, with_trinket=True, hand_ids=[])
        p = get_db().get(PLAIN)
        self.assertEqual(v["left"], (p.atk, p.health))
        # 正对照: 同一饰品在手里有随从时确实授予属性
        v2 = self._soc(3603, with_trinket=True, hand_ids=[TITUS])
        t = get_db().get(TITUS)
        self.assertEqual(v2["left"], (p.atk + t.atk, p.health + t.health))

    def test_opponent_leftmost_not_buffed(self):
        g = make_game(seed=3604)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        left_a = put(g, a, g.create_minion(PLAIN, controller=a))
        a.hand.append(g.create_minion(TITUS, controller=a))
        left_b = put(g, b, g.create_minion(PLAIN, controller=b))
        b.hand.append(g.create_minion(TITUS, controller=b))
        seen = soc_snapshot(g, a, lambda: (left_a.atk, left_a.max_health))
        g.run_combat(a, b)
        p, t = get_db().get(PLAIN), get_db().get(TITUS)
        self.assertEqual(seen.get("v"), (p.atk + t.atk, p.health + t.health))
        self.assertEqual((left_b.atk, left_b.max_health),      # owner 隔离
                         (p.atk, p.health))


# ══════════════ BG30_MagicItem_442 Blood Golem Sticker ══════════════

class TestBloodGolemSticker(unittest.TestCase):
    TID = "BG30_MagicItem_442"

    def _recruit_death(self, seed, with_trinket, gems, owner="a"):
        g = make_game(seed=seed)
        a, b = g.heroes
        target = a if owner == "a" else b
        if with_trinket:
            offer_and_buy(g, a, self.TID, "greater")
        quil = put(g, target, g.create_minion(QUILBOAR, controller=target))
        if gems:
            quil.set(GameTag.GEMS_PLAYED_ON, gems)
        summoned = []
        g.events.register(Listener(
            event=SUMMON, owner=a,
            callback=lambda gg, minion=None, **kw: summoned.append(minion)
            if minion is not None and minion.controller is target else None))
        quil.set(GameTag.HEALTH, 0)
        g.check_deaths()
        golems = [m for m in summoned if m.card_id == GOLEM]
        return g, target, golems

    def test_death_summons_golem_with_gem_stats(self):
        _, _, golems = self._recruit_death(3701, True, gems=2)
        self.assertEqual(len(golems), 1)
        gd = get_db().get("BG20_GEM")
        self.assertEqual((golems[0].atk, golems[0].max_health),
                         (2 * gd.num(0), 2 * gd.num(1)))

    def test_improved_gems_raise_golem_stats(self):
        """Golem 属性 = 血宝石**当前**价值（ImproveBloodGems 实时反映）。"""
        g = make_game(seed=3702)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        a.set(GameTag.BLOOD_GEM_BONUS_ATK, 1)
        a.set(GameTag.BLOOD_GEM_BONUS_HEALTH, 1)
        quil = put(g, a, g.create_minion(QUILBOAR, controller=a))
        quil.set(GameTag.GEMS_PLAYED_ON, 1)
        quilt_atk = quil.atk
        quil.set(GameTag.HEALTH, 0)
        g.check_deaths()
        golems = [m for m in a.board if m.card_id == GOLEM]
        self.assertEqual(len(golems), 1)
        self.assertEqual((golems[0].atk, golems[0].max_health), (2, 2))
        self.assertGreater(quilt_atk, 0)

    def test_zero_gems_summons_zero_zero(self):
        _, _, golems = self._recruit_death(3703, True, gems=0)
        self.assertEqual(len(golems), 1)
        self.assertEqual((golems[0].atk, golems[0].max_health), (0, 0))

    def test_non_quilboar_death_no_golem(self):
        g = make_game(seed=3704)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        other = put(g, a, g.create_minion(ETERNAL_KNIGHT, controller=a))
        other.set(GameTag.GEMS_PLAYED_ON, 3)
        other.set(GameTag.HEALTH, 0)
        g.check_deaths()
        self.assertEqual([m for m in a.board if m.card_id == GOLEM], [])
        # 正对照: 同样宝石数的 **Quilboar** 死亡则召唤 Golem
        quil = put(g, a, g.create_minion(QUILBOAR, controller=a))
        quil.set(GameTag.GEMS_PLAYED_ON, 3)
        quil.set(GameTag.HEALTH, 0)
        g.check_deaths()
        self.assertEqual(len([m for m in a.board if m.card_id == GOLEM]), 1)

    def test_control_without_trinket(self):
        _, _, golems = self._recruit_death(3705, False, gems=2)
        self.assertEqual(golems, [])

    def test_opponent_quilboar_death_no_golem(self):
        g, the_target, golems = self._recruit_death(3706, True, gems=2,
                                                    owner="b")
        self.assertEqual(golems, [])                 # owner 隔离
        # 正对照: 本人 Quilboar 死亡确实召唤
        a = g.heroes[0]
        mine = put(g, a, g.create_minion(QUILBOAR, controller=a))
        mine.set(GameTag.GEMS_PLAYED_ON, 2)
        mine.set(GameTag.HEALTH, 0)
        g.check_deaths()
        self.assertEqual(len([m for m in a.board if m.card_id == GOLEM]), 1)

    def test_full_board_flush_inside_combat(self):
        g = make_game(seed=3707)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        quil = put(g, a, g.create_minion(QUILBOAR, controller=a))
        quil.set(GameTag.GEMS_PLAYED_ON, 3)
        for _ in range(6):
            put(g, a, g.create_minion(PLAIN, controller=a))
        self.assertEqual(len(a.board), 7)
        killer = g.create_minion(TITUS, controller=b)
        killer.set(GameTag.BASE_ATK, 99)
        put(g, b, killer)
        observed = []

        def cb(gg, **kw):
            observed.extend(m for m in a.board if m.card_id == GOLEM)

        from hsrl2.events import AFTER_ATTACK
        g.events.register(Listener(event=AFTER_ATTACK, owner=a, callback=cb))
        g.run_combat(a, b)
        self.assertTrue(observed, "满板死亡的 Quilboar 应在腾位后补召 Golem")
        self.assertEqual((observed[0].atk, observed[0].max_health), (3, 3))


# ══════════════ BG30_MagicItem_541 Nether Pendant ══════════════

class TestNetherPendant(unittest.TestCase):
    TID = "BG30_MagicItem_541"

    def test_bind_buffs_current_tavern_minions(self):
        g = make_game(seed=3801)
        a = g.heroes[0]
        m = make_tavern_minion(g, a)
        p = get_db().get(PLAIN)
        offer_and_buy(g, a, self.TID, "greater")
        n1 = get_db().get(self.TID).num(1)
        self.assertEqual((m.atk, m.max_health), (p.atk + n1, p.health + n1))
        self.assertEqual([tb.atk for tb in a.tavern_buffs], [n1])

    def _refresh_stats(self, seed, with_trinket):
        g = make_game(seed=seed)
        a = g.heroes[0]
        g.heroes[1].gold = 50
        a.gold = 50
        if with_trinket:
            offer_and_buy(g, a, self.TID, "greater")
        else:
            offer_and_abandon(g, a, "greater")       # 同 rng 消耗
        g.refresh_tavern(a)
        return {m.card_id: (m.atk, m.max_health)
                for m in a.tavern if isinstance(m, Minion)}

    def test_refresh_applies_to_new_tavern_minions(self):
        base = self._refresh_stats(3802, with_trinket=False)
        buffed = self._refresh_stats(3802, with_trinket=True)
        self.assertTrue(base)
        self.assertEqual(set(base), set(buffed))
        n1 = get_db().get(self.TID).num(1)
        for cid, (atk, health) in base.items():
            b_atk, b_health = buffed[cid]
            self.assertEqual((b_atk, b_health),
                             (atk + n1, health + n1), cid)

    def test_improves_every_n_out_of_combat_damage(self):
        g = make_game(seed=3803)
        a = g.heroes[0]
        m = make_tavern_minion(g, a)
        p = get_db().get(PLAIN)
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual((m.atk, m.max_health),
                         (p.atk + get_db().get(self.TID).num(1),
                          p.health + get_db().get(self.TID).num(1)))
        n0 = get_db().get(self.TID).num(0)
        n1 = get_db().get(self.TID).num(1)
        for _ in range(n0 - 1):
            a.take_damage(1)
        self.assertEqual([tb.atk for tb in a.tavern_buffs], [n1])
        a.take_damage(1)                             # 第 num(0) 次 → Improve
        self.assertEqual([tb.atk for tb in a.tavern_buffs], [n1 + 1])
        self.assertEqual((m.atk, m.max_health),
                         (p.atk + n1 + 1, p.health + n1 + 1))
        injected = g.inject_tavern_minion(a, PLAIN)
        p = get_db().get(PLAIN)
        self.assertEqual((injected.atk, injected.max_health),
                         (p.atk + n1 + 1, p.health + n1 + 1))

    def test_in_combat_damage_not_counted(self):
        g = make_game(seed=3804)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        n0 = get_db().get(self.TID).num(0)
        n1 = get_db().get(self.TID).num(1)
        g.in_combat = True
        for _ in range(n0 + 1):
            a.take_damage(1)
        g.in_combat = False
        self.assertEqual([tb.atk for tb in a.tavern_buffs], [n1])

    def test_opponent_damage_not_counted(self):
        g = make_game(seed=3805)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        n0 = get_db().get(self.TID).num(0)
        n1 = get_db().get(self.TID).num(1)
        for _ in range(n0 + 1):
            b.take_damage(1)                         # owner 隔离
        self.assertEqual([tb.atk for tb in a.tavern_buffs], [n1])
        self.assertEqual(getattr(b, "tavern_buffs", []), [])
        m = make_tavern_minion(g, b)
        p = get_db().get(PLAIN)
        self.assertEqual((m.atk, m.max_health), (p.atk, p.health))
        for _ in range(n0):                          # 正对照: 本人受伤才 Improve
            a.take_damage(1)
        self.assertEqual([tb.atk for tb in a.tavern_buffs], [n1 + 1])


# ══════════════ BG30_MagicItem_432 Belcher Portrait ══════════════

class TestBelcherPortrait(unittest.TestCase):
    """Whenever a friendly minion loses Venomous, it gains +4/+4
    permanently（2026-09-02 主线解冻: 引擎补 Venomous 失去事件）。"""

    TID = "BG30_MagicItem_432"
    GAIN = 4

    def test_venomous_loss_buffs_permanently(self):
        g = make_game(seed=3201)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        # Venomous 消耗的前提: 受击者**存活**（普通伤害已致死时无意义）
        venom = put(g, a, Minion("TEST_BELCH_A", "A", atk=3, health=5))
        venom.set(GameTag.VENOMOUS, True)
        victim = put(g, b, Minion("TEST_BELCH_D", "D", atk=0, health=20))
        atk_before, hp_before = venom.atk, venom.max_health
        g.end_recruit_phase()          # 真实阶段推进（含 COMBAT_END 广播）
        # 战后（棋盘已复原）仍保留 +4/+4 = "permanently"
        self.assertEqual(venom.atk, atk_before + self.GAIN)
        self.assertEqual(venom.max_health, hp_before + self.GAIN)

    def test_control_without_trinket(self):
        g = make_game(seed=3202)
        a, b = g.heroes
        venom = put(g, a, Minion("TEST_BELCH_A2", "A", atk=3, health=5))
        venom.set(GameTag.VENOMOUS, True)
        put(g, b, Minion("TEST_BELCH_D2", "D", atk=0, health=20))
        atk_before = venom.atk
        g.end_recruit_phase()
        self.assertEqual(venom.atk, atk_before)

    def test_opponent_loss_not_buffed(self):
        g = make_game(seed=3203)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        mine = put(g, a, Minion("TEST_BELCH_M", "M", atk=2, health=5))
        theirs = put(g, b, Minion("TEST_BELCH_T", "T", atk=3, health=5))
        theirs.set(GameTag.VENOMOUS, True)
        put(g, a, Minion("TEST_BELCH_V", "V", atk=0, health=20))
        atk_mine, atk_theirs = mine.atk, theirs.atk
        g.end_recruit_phase()
        self.assertEqual(mine.atk, atk_mine)               # 本人未被误 buff
        self.assertEqual(theirs.atk, atk_theirs)           # 对手随从不受影响
        self.assertIn(self.TID, [t.card_id for t in a.trinkets])


# ══════════════ BG30_MagicItem_429 Demonblood Gourd ══════════════

class TestDemonbloodGourd(unittest.TestCase):
    """Spellcraft: 定向吞噬酒馆随机随从并继承其属性（2026-09-02 主线
    解冻: 引擎支持饰品版 Spellcraft 生成点）。"""

    TID = "BG30_MagicItem_429"
    SPELL = "BG30_MagicItem_429t"

    def test_trinket_generates_spell_and_cast_consumes(self):
        g = make_game(seed=3301)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        e = next(t for t in a.trinkets if t.card_id == self.TID)
        self.assertTrue(e.has(GameTag.SPELLCRAFT))
        from hsrl2.spellcraft import generate_for_hero
        generate_for_hero(a, g)
        spell = next(c for c in a.hand if c.card_id == self.SPELL)
        target = put(g, a, g.create_minion("BG25_001", controller=a))
        prey = g.create_minion("BG33_140", controller=a)
        prey.zone = Zone.TAVERN
        a.tavern = [prey]
        p_atk, p_hp = prey.atk, prey.max_health
        t_atk, t_hp = target.atk, target.max_health
        a.gold = 20
        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertNotIn(prey, a.tavern)                   # 被吞噬
        self.assertTrue(prey.dead or prey.zone == Zone.REMOVED)
        self.assertEqual(target.atk, t_atk + p_atk)        # 继承属性
        self.assertEqual(target.max_health, t_hp + p_hp)

    def test_control_without_trinket_generates_nothing(self):
        g = make_game(seed=3302)
        a = g.heroes[0]
        from hsrl2.spellcraft import generate_for_hero
        generate_for_hero(a, g)
        self.assertEqual([c.card_id for c in a.hand], [])

    def test_empty_tavern_whiffs(self):
        g = make_game(seed=3303)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        target = put(g, a, g.create_minion("BG25_001", controller=a))
        a.tavern = []
        from hsrl2.spellcraft import generate_for_hero
        generate_for_hero(a, g)
        spell = next(c for c in a.hand if c.card_id == self.SPELL)
        t_atk = target.atk
        a.gold = 20
        self.assertTrue(g.play_spell(a, spell, target=target))   # 不崩溃
        self.assertEqual(target.atk, t_atk)                # 无收益落空


if __name__ == "__main__":
    unittest.main()
