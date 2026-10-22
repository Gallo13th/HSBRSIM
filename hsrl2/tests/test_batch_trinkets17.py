"""批次 trinkets17 行为层测试（17 张注册饰品 + 1 张 Spellcraft 法术,
3 张 DEFERRED 台账, 2026-09-13）。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线）
  - SoT/EoT: `game.run_script_hook(trinket, "start_of_turn"/"end_of_turn")`
    （引擎真实分发点）+ `game.refresh_tavern` / `game.buy_from_tavern`
  - SoC: 真实 `game.run_combat`（Crocheted Sungill / 战斗内死亡触发）
  - 死/亡语: `game._process_single_death`（招募期路径）与真实战斗
  - 法术: 真实 `game.play_spell`（Spellcraft 定向 + 池法术施放）
  - 池: `minion_pool.available` 前后差

覆盖（SOP §16 空转测试判定法 + TEST_SOP §3 最低矩阵）: 每个测试方法至少
一条**正效果**断言（多数与同 setup 的无饰品/未触发对照写在同一方法内）;
owner 隔离（2 英雄）; 一次性/跨回合/每回合语义; 满手排队 / 空场落空 /
资源不足落空; `CardDef.num` 双向钉死; 随机局面构造成确定性（满候选
sample 全中 / 单候选）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.actions import Buff
from hsrl2.events import SUMMON, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.spell import Spell
from hsrl2.spellcraft import generate_for_hero
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# ── 测试用既有卡（CardDB 按名核实——禁止凭记忆写 id）──
DEMON_CONSUMER = "BG26_523"    # Tichondrius T5 3/3（无战吼/无打出触发）
DEMON_PLAYED = "BG26_524"      # Malchezaar T3 2/1（无战吼/无打出触发）
UNDEAD = "BG25_008"            # Eternal Knight T2 4/2 亡灵
TAUNT = "BG25_001"             # Risen Rider T1 2/1 嘲讽（带复生）
NO_TAUNT = "BG25_013"          # Rot Hide Gnoll T1 1/4（无关键词）
DR_NEUTRAL = "BG32_880"        # Friendly Geist 6/3 亡语（不改棋盘）
MAGNETIC = "BG26_146"          # Lullabot T1 2/2 磁力
HOST = "BG_BOT_312"            # Replicating Menace 3/2 机械（非池）
SPELL_STATS_ALL = "BG28_168"   # Shiny Ring（Give your minions +1/+1）
GEM = "BG20_GEM"               # 香草血宝石（非池法术）
FODDER = "BG35_150t"           # Demon Fodder token

# ── 本批 id ──
GOLDRUBBER = "BG32_MagicItem_953"
AURIC = "BG32_MagicItem_954"
SUNGILL = "BG32_MagicItem_960"
BEHEMOTH = "BG32_MagicItem_998"
CURSED = "BG35_MagicItem_150"
DEFILER = "BG35_MagicItem_151"
TAPESTRY = "BG35_MagicItem_152"
URZUL = "BG35_MagicItem_154"
LEDGER = "BG35_MagicItem_155"
COIL = "BG35_MagicItem_300"
SKIPPER = "BG35_MagicItem_303"
CONCH = "BG35_MagicItem_305"
JAILER = "BG35_MagicItem_306"
JAILER_SPELL = "BG35_MagicItem_306t"
ERRGL = "BG35_MagicItem_309"
RADIO = "BG35_MagicItem_310"
SCRAPSMITH = "BG35_MagicItem_430"
AMULET = "BG35_MagicItem_432"

DEFERRED_IDS = (
)
# BG35_MagicItem_431t Thornspike Pauldron 已由 batch_trinkets30 注册
# （2026-09-15: `CardDef.num(4)` NUM_5 已导出 + `deathrattle_trigger`
#  统一广播点）→ 移出本台账。
# BG35_MagicItem_433 Vinespeaker Portrait 已由 batch_unlock_final 注册
# （2026-09-15: death 事件 + BLOOD_GEM_BONUS_HEALTH 读取点）——迁出本台账
MIGRATED_IDS = (
    "BG35_MagicItem_433",
)
REGISTERED_IDS = (
    GOLDRUBBER, AURIC, SUNGILL, BEHEMOTH, CURSED, DEFILER, TAPESTRY,
    URZUL, LEDGER, COIL, SKIPPER, CONCH, JAILER, JAILER_SPELL, ERRGL,
    RADIO, SCRAPSMITH, AMULET,
)

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 700) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str):
    e = game.grant_trinket(hero, tid)
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str, **kw) -> Minion:
    m = game.create_minion(card_id, controller=hero, **kw)
    assert game.summon(hero, m)
    return m


def put_hand(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    assert hero.hand.append(m) is None
    m.zone = Zone.HAND
    return m


def put_tavern(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def fill_hand(game: Game, hero: Hero) -> None:
    while not hero.hand_full():
        put_hand(game, hero, GEM)


def kill(game: Game, m: Minion) -> None:
    """招募期死亡（完整死亡链: death → 亡语 → 回池）。"""
    m.health = 0
    game._process_single_death(m)


def cast_pool_spell(game: Game, hero: Hero, card_id: str,
                    target=None) -> Spell:
    assert game.spell_pool.acquire(card_id)
    s = game.create_spell(card_id, controller=hero)
    assert hero.add_to_hand(s)
    assert game.play_spell(hero, s, target=target)
    return s


def gem_value() -> int:
    d = get_db().get(GEM)
    return d.num(0)


# ══════════════ 注册表 / DEFERRED 台账（结构性） ══════════════


class TestBatchTrinkets17Registry(unittest.TestCase):
    """结构性: 注册表与 DEFERRED 台账守卫（与脚本钩子无关——@engine-only）。"""

    def test_all_registered(self):
        for tid in REGISTERED_IDS:
            self.assertIsNotNone(REGISTRY.get(tid), tid)

    def test_deferred_ledger_not_registered(self):
        for tid in DEFERRED_IDS:
            self.assertIsNone(REGISTRY.get(tid), tid)

    def test_deferred_docstring_mentions_dependency(self):
        from hsrl2.scripts.batches import batch_trinkets17 as B
        doc = B.__doc__
        for tid in DEFERRED_IDS + MIGRATED_IDS:
            self.assertIn(tid, doc)


# ══════════════ BG32_MagicItem_953 Goldgrubber Portrait ══════════════


class TestGoldgrubberPortrait(unittest.TestCase):
    """953 — Get a Goldgrubber and an Aureate Laureate。"""

    def test_grants_both_related_cards(self):
        game = make_game()
        a = game.heroes[0]
        avail0 = game.minion_pool.available("BG32_236")
        bind(game, a, GOLDRUBBER)
        self.assertEqual([c.card_id for c in a.hand],
                         ["BGS_066", "BG32_236"])
        # Aureate Laureate 的 on_enter_hand "always Golden"
        self.assertTrue(a.hand[1].has(GameTag.GOLDEN))
        self.assertEqual(game.minion_pool.available("BG32_236"), avail0 - 1)

    def test_non_pool_goldgrubber_leaves_pool_untouched(self):
        game = make_game()
        a = game.heroes[0]
        avail0 = game.minion_pool.available("BGS_066")
        laureate0 = game.minion_pool.available("BG32_236")
        bind(game, a, GOLDRUBBER)
        self.assertEqual(game.minion_pool.available("BGS_066"), avail0)
        self.assertEqual(game.minion_pool.available("BG32_236"),
                         laureate0 - 1)                  # 正对照: 池卡占池

    def test_owner_isolation(self):
        game = make_game()
        a, b = game.heroes
        bind(game, b, GOLDRUBBER)
        self.assertEqual(len(a.hand), 0)
        self.assertEqual(len(b.hand), 2)

    def test_full_hand_queues_both(self):
        game = make_game()
        a = game.heroes[0]
        fill_hand(game, a)
        size0 = len(a.hand)
        bind(game, a, GOLDRUBBER)
        self.assertEqual(len(a.hand), size0)             # 未涨（满手）
        queued = sorted(e.card_id for h, e in game.pending_hand_queue
                        if h is a)
        self.assertEqual(queued, ["BG32_236", "BGS_066"])


# ══════════════ BG32_MagicItem_954 Auric Offering ══════════════


class TestAuricOffering(unittest.TestCase):
    """954 — EoT: 最左随从 +4/+3，每个友方金色随从再重复一次。"""

    def test_eot_buffs_only_leftmost(self):
        game = make_game()
        a = game.heroes[0]
        e = bind(game, a, AURIC)
        m1 = put(game, a, NO_TAUNT)
        m2 = put(game, a, DEMON_CONSUMER)
        b1 = (m1.atk, m1.max_health)
        b2 = (m2.atk, m2.max_health)
        game.run_script_hook(e, "end_of_turn")
        self.assertEqual((m1.atk, m1.max_health), (b1[0] + 4, b1[1] + 3))
        self.assertEqual((m2.atk, m2.max_health), b2)

    def test_repeats_for_each_golden_minion(self):
        game = make_game()
        a = game.heroes[0]
        e = bind(game, a, AURIC)
        m1 = put(game, a, NO_TAUNT)
        base = (m1.atk, m1.max_health)
        game.run_script_hook(e, "end_of_turn")
        self.assertEqual((m1.atk, m1.max_health),
                         (base[0] + 4, base[1] + 3))
        put(game, a, TAUNT, golden=True)                 # 1 只金色
        game.run_script_hook(e, "end_of_turn")
        self.assertEqual((m1.atk, m1.max_health),
                         (base[0] + 12, base[1] + 9))
        put(game, a, TAUNT, golden=True)                 # 2 只金色
        game.run_script_hook(e, "end_of_turn")
        self.assertEqual((m1.atk, m1.max_health),
                         (base[0] + 24, base[1] + 18))

    def test_golden_count_is_per_hero(self):
        game = make_game()
        a, b = game.heroes
        for _ in range(2):
            put(game, a, TAUNT, golden=True)             # 对手的金色不计
        e = bind(game, b, AURIC)
        target = put(game, b, NO_TAUNT)
        base = (target.atk, target.max_health)
        game.run_script_hook(e, "end_of_turn")
        self.assertEqual((target.atk, target.max_health),
                         (base[0] + 4, base[1] + 3))

    def test_empty_board_no_crash(self):
        game = make_game()
        a = game.heroes[0]
        e = bind(game, a, AURIC)
        game.run_script_hook(e, "end_of_turn")           # 不抛
        self.assertEqual(a.board, [])
        m = put(game, a, NO_TAUNT)                       # 正对照: 有效果路径
        base = (m.atk, m.max_health)
        game.run_script_hook(e, "end_of_turn")
        self.assertEqual((m.atk, m.max_health), (base[0] + 4, base[1] + 3))

    def test_carddef_num_absent_matches_literal_text(self):
        d = get_db().get(AURIC)
        self.assertIsNone(d.num(0))
        self.assertIsNone(d.num(1))


# ══════════════ BG32_MagicItem_960 Crocheted Sungill ══════════════


class TestCrochetedSungill(unittest.TestCase):
    """960 — SoC: 手牌最高生命随从 +4/+4；有空位时召唤其战斗限定副本。"""

    def _run(self, game, a, b):
        """真实战斗，收集战斗内 summon 事件（card_id, atk, max_health）。"""
        seen = []

        def on_summon(g, minion=None, **kw):
            if minion is not None:
                seen.append((minion.card_id, minion.atk, minion.max_health))

        game.events.register(Listener(event=SUMMON, owner=a,
                                      callback=on_summon))
        game.run_combat(a, b)
        return seen

    @staticmethod
    def _d():
        """DEMON_PLAYED（Malchezaar）37.0 基础属性 2/1→4/3，禁止硬编码。"""
        return get_db().get(DEMON_PLAYED)

    def test_soc_buffs_hand_minion_and_summons_combat_copy(self):
        game = make_game(seed=11)
        a, b = game.heroes
        e = bind(game, a, SUNGILL)
        put(game, a, NO_TAUNT)
        put(game, b, UNDEAD)
        d = self._d()
        hm = put_hand(game, a, DEMON_PLAYED)
        seen = self._run(game, a, b)
        # 手牌实体永久 +4/+4 且仍在手牌
        self.assertEqual((hm.atk, hm.max_health),
                         (d.atk + 4, d.health + 4))
        self.assertIn(hm, a.hand)
        # 战斗中召唤了副本（属性含 buff）
        self.assertIn((DEMON_PLAYED, d.atk + 4, d.health + 4), seen)
        # 战后副本消失（board 恢复战前）
        self.assertEqual([m.card_id for m in a.board], [NO_TAUNT])

    def test_picks_highest_health_hand_minion(self):
        game = make_game(seed=12)
        a, b = game.heroes
        bind(game, a, SUNGILL)
        put(game, a, NO_TAUNT)
        put(game, b, UNDEAD)
        d = self._d()
        low = put_hand(game, a, DEMON_PLAYED)
        high = put_hand(game, a, NO_TAUNT)               # 1/4
        self._run(game, a, b)
        self.assertEqual((high.atk, high.max_health), (5, 8))
        self.assertEqual((low.atk, low.max_health),
                         (d.atk, d.health))

    def test_board_full_defers_until_space(self):
        game = make_game(seed=13)
        a, b = game.heroes
        e = bind(game, a, SUNGILL)
        for _ in range(7):
            put(game, a, NO_TAUNT)
        foe = put(game, b, DR_NEUTRAL)
        game.run_actions(Buff(foe, atk=20, health=50))
        put_hand(game, a, DEMON_PLAYED)
        self.assertTrue(a.board_full())
        seen = self._run(game, a, b)
        # 战斗内腾位（己方 1/4 阵亡）后补召成功
        self.assertIsNotNone(getattr(e, "_sungill_copy", None))
        self.assertTrue(any(cid == DEMON_PLAYED for cid, _, _ in seen))

    def test_empty_hand_no_effect(self):
        game = make_game(seed=14)
        a, b = game.heroes
        e = bind(game, a, SUNGILL)
        put(game, a, NO_TAUNT)
        put(game, b, UNDEAD)
        seen = self._run(game, a, b)
        self.assertIsNone(getattr(e, "_sungill_copy", None))
        self.assertFalse(any(cid == DEMON_PLAYED for cid, _, _ in seen))
        # 正对照: 同一局补一张手牌后再战 → 副本出现且属性含 buff
        d = self._d()
        hm = put_hand(game, a, DEMON_PLAYED)
        seen2 = self._run(game, a, b)
        self.assertEqual((hm.atk, hm.max_health),
                         (d.atk + 4, d.health + 4))
        self.assertTrue(any(cid == DEMON_PLAYED for cid, _, _ in seen2))

    def test_opponent_hand_untouched(self):
        game = make_game(seed=15)
        a, b = game.heroes
        bind(game, a, SUNGILL)
        put(game, a, NO_TAUNT)
        put(game, b, UNDEAD)
        d = self._d()
        other = put_hand(game, b, DEMON_PLAYED)
        mine = put_hand(game, a, DEMON_PLAYED)           # 正对照: 本人被 buff
        self._run(game, a, b)
        self.assertEqual((other.atk, other.max_health),
                         (d.atk, d.health))
        self.assertEqual((mine.atk, mine.max_health),
                         (d.atk + 4, d.health + 4))


# ══════════════ BG32_MagicItem_998 Behemoth Portrait ══════════════


class TestBehemothPortrait(unittest.TestCase):
    """998 — Get an Arcane Behemoth。"""

    def test_grants_arcane_behemoth(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, BEHEMOTH)
        self.assertEqual([c.card_id for c in a.hand], ["BG31_360"])

    def test_owner_isolation(self):
        game = make_game()
        a, b = game.heroes
        bind(game, b, BEHEMOTH)
        self.assertEqual(len(a.hand), 0)
        self.assertEqual([c.card_id for c in b.hand], ["BG31_360"])

    def test_full_hand_queues(self):
        game = make_game()
        a = game.heroes[0]
        fill_hand(game, a)
        bind(game, a, BEHEMOTH)
        queued = [e.card_id for h, e in game.pending_hand_queue if h is a]
        self.assertEqual(queued, ["BG31_360"])


# ══════════════ BG35_MagicItem_303 Skipper Portrait ══════════════


class TestSkipperPortrait(unittest.TestCase):
    """303 — Get a Timewarped Skipper。"""

    def test_grants_timewarped_skipper(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, SKIPPER)
        self.assertEqual([c.card_id for c in a.hand], ["BG34_Giant_072"])

    def test_owner_isolation(self):
        game = make_game()
        a, b = game.heroes
        bind(game, b, SKIPPER)
        self.assertEqual(len(a.hand), 0)
        self.assertEqual([c.card_id for c in b.hand], ["BG34_Giant_072"])


# ══════════════ BG35_MagicItem_310 Radio Star Portrait ══════════════


class TestRadioStarPortrait(unittest.TestCase):
    """310 — Get a Timewarped Radio Star 并给它 Reborn。"""

    def test_grants_with_reborn(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, RADIO)
        self.assertEqual([c.card_id for c in a.hand], ["BG34_Giant_330"])
        self.assertTrue(a.hand[0].has(GameTag.REBORN))

    def test_reborn_persists_after_play(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, RADIO)
        card = a.hand[0]
        self.assertTrue(game.play_minion(a, card))
        self.assertTrue(card.has(GameTag.REBORN))
        self.assertIn(card, a.board)

    def test_control_plain_copy_has_no_reborn(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, RADIO)
        self.assertTrue(a.hand[0].has(GameTag.REBORN))   # 正对照: 授予物有
        plain = game.create_minion("BG34_Giant_330", controller=a)
        self.assertFalse(plain.has(GameTag.REBORN))

    def test_owner_isolation(self):
        game = make_game()
        a, b = game.heroes
        bind(game, b, RADIO)
        self.assertEqual(len(a.hand), 0)
        self.assertEqual([c.card_id for c in b.hand], ["BG34_Giant_330"])


# ══════════════ BG35_MagicItem_305 Conch Portrait ══════════════


class TestConchPortrait(unittest.TestCase):
    """305 — Get a Cloning Conch；每 num(1) 个回合开始重复。"""

    def test_grants_and_repeats_every_period(self):
        game = make_game()
        a = game.heroes[0]
        e = bind(game, a, CONCH)
        d = get_db().get(CONCH)
        self.assertEqual([c.card_id for c in a.hand], ["BG28_601"])
        game.run_script_hook(e, "start_of_turn")         # 第 1 个 SoT
        self.assertEqual(len(a.hand), 1)
        game.run_script_hook(e, "start_of_turn")         # 第 num(0) 个 SoT
        self.assertEqual(len(a.hand), 2)
        self.assertEqual(getattr(e, "_conch_left"), d.num(1))
        game.run_script_hook(e, "start_of_turn")
        self.assertEqual(len(a.hand), 2)
        game.run_script_hook(e, "start_of_turn")         # 第 2 个周期
        self.assertEqual(len(a.hand), 3)

    def test_owner_isolation(self):
        game = make_game()
        a, b = game.heroes
        e = bind(game, b, CONCH)
        game.run_script_hook(e, "start_of_turn")
        game.run_script_hook(e, "start_of_turn")
        self.assertEqual(len(b.hand), 2)
        self.assertEqual(len(a.hand), 0)


# ══════════════ BG35_MagicItem_309 Errgl Sticker ══════════════


class TestErrglSticker(unittest.TestCase):
    """309 — 随机 Get Mama/Papa Mrrglton；每回合开始重复。"""

    def test_grants_one_of_two_and_repeats(self):
        game = make_game(seed=21)
        a = game.heroes[0]
        avail0 = {i: game.minion_pool.available(i)
                  for i in ("BG35_140", "BG35_141")}
        e = bind(game, a, ERRGL)
        self.assertEqual(len(a.hand), 1)
        self.assertIn(a.hand[0].card_id, ("BG35_140", "BG35_141"))
        # 37.0（255130）: Mama/Papa Mrrglton 均已退出池内随从
        # （is_pool_minion=False）→ 交付为零池操作（`grant_card_copy_to_hand`）。
        self.assertEqual(
            {i: game.minion_pool.available(i) for i in avail0}, avail0)
        game.run_script_hook(e, "start_of_turn")
        self.assertEqual(len(a.hand), 2)
        self.assertIn(a.hand[1].card_id, ("BG35_140", "BG35_141"))

    def test_owner_isolation(self):
        game = make_game(seed=22)
        a, b = game.heroes
        e = bind(game, b, ERRGL)
        game.run_script_hook(e, "start_of_turn")
        self.assertEqual(len(a.hand), 0)
        self.assertEqual(len(b.hand), 2)

    def test_full_hand_queues(self):
        game = make_game(seed=23)
        a = game.heroes[0]
        fill_hand(game, a)
        bind(game, a, ERRGL)
        queued = [e.card_id for h, e in game.pending_hand_queue if h is a]
        self.assertEqual(len(queued), 1)
        self.assertIn(queued[0], ("BG35_140", "BG35_141"))


# ══════════════ BG35_MagicItem_306 Jailer Sticker ══════════════


class TestJailerSticker(unittest.TestCase):
    """306 — Spellcraft: 摧毁友方亡灵，随机获得一张亡灵。"""

    def test_engine_spellcraft_generation_each_turn(self):
        """引擎数据通道: `create_entity` 依 `spellcraft_id` 打 SPELLCRAFT
        tag，`generate_for_hero` 扫描 `hero.trinkets`（与饰品脚本钩子无关
        ——脚本类无 on_bind 副作用，属设计如此）。"""
        game = make_game()
        a = game.heroes[0]
        bind(game, a, JAILER)
        generate_for_hero(a, game)
        spells = [c for c in a.hand if c.card_id == JAILER_SPELL]
        self.assertEqual(len(spells), 1)
        self.assertTrue(spells[0].has(GameTag.SPELLCRAFT))

    def test_engine_control_without_trinket_generates_nothing(self):
        """引擎通道对照: 未绑定饰品则无 Spellcraft 实体可生成。"""
        game = make_game()
        a = game.heroes[0]
        generate_for_hero(a, game)
        self.assertEqual([c for c in a.hand if c.card_id == JAILER_SPELL], [])
        bind(game, a, JAILER)                            # 正对照: 绑定后生成
        generate_for_hero(a, game)
        self.assertEqual(len([c for c in a.hand
                              if c.card_id == JAILER_SPELL]), 1)

    def test_play_destroys_undead_and_gets_random_undead(self):
        game = make_game(seed=31)
        a = game.heroes[0]
        bind(game, a, JAILER)
        generate_for_hero(a, game)
        spell = [c for c in a.hand if c.card_id == JAILER_SPELL][0]
        victim = put(game, a, UNDEAD)
        total0 = game.minion_pool.total_remaining()
        self.assertTrue(game.play_spell(game.heroes[0], spell))
        self.assertEqual(len(game.pending_choices), 1)
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "spell_target")
        self.assertEqual(choice.options, [victim])
        choice.choose(0)
        self.assertTrue(victim.dead)
        self.assertEqual(victim.zone, Zone.GRAVEYARD)
        # 随机获得一张亡灵（池占 1 份; Amalgam 的全类型也属亡灵候选域）
        gained = [c for c in a.hand if isinstance(c, Minion)]
        self.assertEqual(len(gained), 1)
        self.assertIn(gained[0].race, (Race.UNDEAD, Race.ALL))
        # 摧毁回池 1 份 + 随机获取占池 1 份 → 池总量守恒
        self.assertEqual(game.minion_pool.total_remaining(), total0)

    def test_no_undead_target_fizzles_without_gain(self):
        game = make_game(seed=32)
        a = game.heroes[0]
        bind(game, a, JAILER)
        generate_for_hero(a, game)
        spell = [c for c in a.hand if c.card_id == JAILER_SPELL][0]
        put(game, a, MAGNETIC)                           # 机械（非亡灵）
        self.assertTrue(game.play_spell(a, spell))
        self.assertEqual(game.pending_choices, [])
        self.assertNotIn(spell, a.hand)                  # 法术照常消耗
        self.assertEqual([c for c in a.hand if isinstance(c, Minion)], [])
        # 正对照: 补一张亡灵后再施放（重生成法术）→ 摧毁并获取
        victim = put(game, a, UNDEAD)
        generate_for_hero(a, game)
        spell2 = [c for c in a.hand if c.card_id == JAILER_SPELL][0]
        self.assertTrue(game.play_spell(a, spell2))
        game.pending_choices.pop(0).choose(0)
        self.assertTrue(victim.dead)
        self.assertEqual(len([c for c in a.hand if isinstance(c, Minion)]), 1)

    def test_opponent_board_untouched(self):
        game = make_game(seed=33)
        a, b = game.heroes
        bind(game, a, JAILER)
        generate_for_hero(a, game)
        spell = [c for c in a.hand if c.card_id == JAILER_SPELL][0]
        foe = put(game, b, UNDEAD)
        game.play_spell(a, spell)                        # 本人无亡灵 → 落空
        self.assertFalse(foe.dead)
        self.assertIn(foe, b.board)
        mine = put(game, a, UNDEAD)                      # 正对照: 本人目标被毁
        generate_for_hero(a, game)
        spell2 = [c for c in a.hand if c.card_id == JAILER_SPELL][0]
        self.assertTrue(game.play_spell(a, spell2))
        game.pending_choices.pop(0).choose(0)
        self.assertTrue(mine.dead)
        self.assertFalse(foe.dead)


# ══════════════ BG35_MagicItem_150 Cursed Crystal ══════════════


class TestCursedCrystal(unittest.TestCase):
    """150 — 每次刷新后馆内随从 +num(0)/+num(1)「本回合」。"""

    def _minions(self, hero):
        return [e for e in hero.tavern if isinstance(e, Minion)]

    def test_refresh_buffs_tavern_minions(self):
        game = make_game()
        a = game.heroes[0]
        a.tavern.clear()
        bind(game, a, CURSED)
        game.refresh_tavern(a)
        d = get_db().get(CURSED)
        mins = self._minions(a)
        self.assertTrue(mins)
        for m in mins:
            base = get_db().get(m.card_id)
            self.assertEqual(m.atk, base.atk + d.num(0))
            self.assertEqual(m.max_health, base.health + d.num(1))

    def test_bind_does_not_retro_buff_current_tavern(self):
        game = make_game()
        a = game.heroes[0]
        a.tavern.clear()
        m = put_tavern(game, a, NO_TAUNT)
        base = (m.atk, m.max_health)
        bind(game, a, CURSED)
        self.assertEqual((m.atk, m.max_health), base)
        # 正对照: 同实体在下一次刷新后（冻结保留）获得 buff
        m.set(GameTag.FROZEN, True)
        game.refresh_tavern(a)
        self.assertEqual((m.atk, m.max_health), (base[0] + 3, base[1] + 3))

    def test_same_entity_stacks_per_refresh(self):
        """每次刷新各授予一份（文本 "After the Tavern is Refreshed, give
        its minions +X/+Y this turn"——旧实现自造"同回合只 buff 一次"
        去重，本条即证伪旧实现）。"""
        game = make_game()
        a = game.heroes[0]
        a.tavern.clear()
        bind(game, a, CURSED)
        a.gold = 30
        m = put_tavern(game, a, NO_TAUNT)
        m.set(GameTag.FROZEN, True)
        game.refresh_tavern(a)
        d = get_db().get(CURSED)
        once = (m.atk, m.max_health)
        self.assertEqual(once, (d.num(0) + 1, d.num(1) + 4))
        m.set(GameTag.FROZEN, True)
        game.refresh_tavern(a)
        self.assertEqual((m.atk, m.max_health),
                         (once[0] + d.num(0), once[1] + d.num(1)))

    def test_refresh_window_entry_gets_one_grant(self):
        """刷新窗口内入馆的实体（Laboratory Assistant 的 Fodder 路径）得
        一份——旧实现按注册顺序打标 → 同一事件里更晚入馆的 Fodder 恒
        不被 buff（本条为突变对照）。"""
        game = make_game()
        a = game.heroes[0]
        a.tavern.clear()
        bind(game, a, CURSED)
        d = get_db().get(CURSED)
        fodder = game.create_minion(FODDER, controller=a)

        def late_listener(g, hero=None, **kw):
            if hero is a:
                g.add_tavern_entity(a, fodder)      # 比饰品更晚的监听器

        game.events.register(Listener(event="tavern_refresh", owner=a,
                                      callback=late_listener))
        game.refresh_tavern(a)
        base = get_db().get(FODDER)
        self.assertEqual((fodder.atk, fodder.max_health),
                         (base.atk + d.num(0), base.health + d.num(1)))
        # 再次刷新：窗口内新入馆的实体同样各得一份（非累积到新实体上）
        fodder2 = game.create_minion(FODDER, controller=a)

        def late_listener2(g, hero=None, **kw):
            if hero is a:
                g.add_tavern_entity(a, fodder2)

        game.events.register(Listener(event="tavern_refresh", owner=a,
                                      callback=late_listener2))
        game.refresh_tavern(a)
        self.assertEqual((fodder2.atk, fodder2.max_health),
                         (base.atk + d.num(0), base.health + d.num(1)))

    def test_turn_start_clears_tavern_resident_buff(self):
        game = make_game()
        a = game.heroes[0]
        a.tavern.clear()
        e = bind(game, a, CURSED)
        m = put_tavern(game, a, NO_TAUNT)
        m.set(GameTag.FROZEN, True)
        game.refresh_tavern(a)
        self.assertEqual(m.atk, 4)
        game.run_script_hook(e, "start_of_turn")
        self.assertEqual((m.atk, m.max_health), (1, 4))

    def test_bought_minion_keeps_buff_across_turn(self):
        game = make_game()
        a = game.heroes[0]
        a.tavern.clear()
        e = bind(game, a, CURSED)
        game.refresh_tavern(a)
        buyable = [m for m in self._minions(a)]
        self.assertTrue(buyable)
        m = buyable[0]
        buffed = (m.atk, m.max_health)
        d = get_db().get(CURSED)
        base = get_db().get(m.card_id)
        self.assertEqual(buffed, (base.atk + d.num(0),
                                  base.health + d.num(1)))  # 刷新已 buff
        a.gold = 30
        self.assertTrue(game.buy_from_tavern(a, m))
        game.run_script_hook(e, "start_of_turn")
        self.assertEqual((m.atk, m.max_health), buffed)
        self.assertIn(m, a.hand)

    def test_auto_refresh_also_triggers(self):
        game = make_game()
        a = game.heroes[0]
        a.tavern.clear()
        bind(game, a, CURSED)
        game.refresh_tavern(a, auto=True)
        for m in self._minions(a):
            self.assertEqual(m.atk, get_db().get(m.card_id).atk + 3)

    def test_opponent_tavern_not_buffed(self):
        game = make_game()
        a, b = game.heroes
        a.tavern.clear()
        b.tavern.clear()
        bind(game, b, CURSED)
        game.refresh_tavern(a)                           # 对手刷新
        for m in self._minions(a):
            self.assertEqual(m.atk, get_db().get(m.card_id).atk)
        game.refresh_tavern(b)
        self.assertTrue(all(m.atk > get_db().get(m.card_id).atk
                            for m in self._minions(b)))


# ══════════════ BG35_MagicItem_151 Defiler Portrait ══════════════


class TestDefilerPortrait(unittest.TestCase):
    """151 — Get a Woodland Defiler；酒馆中的 Fodder +num(0)/+num(1)。"""

    def _fodders(self, hero):
        return [e for e in hero.tavern if e.card_id == FODDER]

    def test_grants_woodland_defiler(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, DEFILER)
        self.assertEqual([c.card_id for c in a.hand], ["BG35_151"])

    def test_fodder_gets_buff_on_refresh(self):
        game = make_game()
        a = game.heroes[0]
        a.tavern.clear()
        bind(game, a, DEFILER)
        d = get_db().get(DEFILER)
        game._fodder_refresh_pending[a] = (1, 1)
        game.refresh_tavern(a)
        fodders = self._fodders(a)
        self.assertEqual(len(fodders), 1)
        base = get_db().get(FODDER)
        self.assertEqual((fodders[0].atk, fodders[0].max_health),
                         (base.atk + d.num(0), base.health + d.num(1)))

    def test_second_refresh_new_fodder_not_stacked(self):
        game = make_game()
        a = game.heroes[0]
        a.tavern.clear()
        bind(game, a, DEFILER)
        d = get_db().get(DEFILER)
        for _ in range(2):
            game._fodder_refresh_pending[a] = (1, 1)
            game.refresh_tavern(a)
            fodders = self._fodders(a)
            self.assertEqual(len(fodders), 1)
            base = get_db().get(FODDER)
            self.assertEqual(fodders[0].atk, base.atk + d.num(0))
            self.assertEqual(fodders[0].max_health, base.health + d.num(1))

    def test_laboratory_assistant_fodder_gets_buff(self):
        """真实 Laboratory Assistant `BG35_150` 路径的 Fodder 也命中。

        旧实现只在 `tavern_refresh` 事件里打标并按注册顺序生效 → 同一
        事件内更晚入馆的 Fodder 恒吃不到（本条为突变对照）。
        """
        game = make_game()
        a = game.heroes[0]
        a.tavern.clear()
        bind(game, a, DEFILER)
        d = get_db().get(DEFILER)
        la = put(game, a, "BG35_150")            # Laboratory Assistant
        self.assertTrue(la.has(GameTag.BATTLECRY))
        game.run_script_hook(la, "battlecry")
        game.refresh_tavern(a)
        fodders = [e for e in a.tavern if e.card_id == FODDER]
        self.assertEqual(len(fodders), 1)
        base = get_db().get(FODDER)
        self.assertEqual((fodders[0].atk, fodders[0].max_health),
                         (base.atk + d.num(0), base.health + d.num(1)))

    def test_golden_fodder_token_also_matched(self):
        """金色 token `BG35_150t_G` 同属资格集（旧实现漏判）。"""
        game = make_game()
        a = game.heroes[0]
        a.tavern.clear()
        bind(game, a, DEFILER)
        d = get_db().get(DEFILER)
        gold = game.create_minion(FODDER, controller=a, golden=True)
        game.add_tavern_entity(a, gold)
        base = get_db().get(gold.card_id)
        self.assertEqual(gold.card_id, FODDER + "_G")
        self.assertEqual((gold.atk, gold.max_health),
                         (base.atk + d.num(0), base.health + d.num(1)))

    def test_bought_fodder_keeps_buff(self):
        """实体级永久 Buff: 买入（离馆）后属性保留。"""
        game = make_game()
        a = game.heroes[0]
        a.tavern.clear()
        bind(game, a, DEFILER)
        d = get_db().get(DEFILER)
        game._fodder_refresh_pending[a] = (1, 1)
        game.refresh_tavern(a)
        f = self._fodders(a)[0]
        buffed = (f.atk, f.max_health)
        a.gold = 30
        self.assertTrue(game.buy_from_tavern(a, f))
        self.assertEqual((f.atk, f.max_health), buffed)
        base = get_db().get(FODDER)
        self.assertEqual(buffed, (base.atk + d.num(0), base.health + d.num(1)))

    def test_non_fodder_tavern_minion_untouched(self):
        game = make_game()
        a = game.heroes[0]
        a.tavern.clear()
        bind(game, a, DEFILER)
        m = put_tavern(game, a, NO_TAUNT)
        m.set(GameTag.FROZEN, True)
        game._fodder_refresh_pending[a] = (1, 1)
        game.refresh_tavern(a)
        self.assertEqual((m.atk, m.max_health), (1, 4))
        fodder = self._fodders(a)                        # 正对照: Fodder 被 buff
        self.assertEqual(len(fodder), 1)
        self.assertEqual((fodder[0].atk, fodder[0].max_health), (6, 6))

    def test_opponent_fodder_untouched(self):
        game = make_game()
        a, b = game.heroes
        a.tavern.clear()
        b.tavern.clear()
        bind(game, a, DEFILER)                           # 只有 A 有饰品
        game._fodder_refresh_pending[a] = (1, 1)
        game._fodder_refresh_pending[b] = (1, 1)
        game.refresh_tavern(a)
        self.assertEqual((self._fodders(a)[0].atk,
                          self._fodders(a)[0].max_health), (6, 6))  # 本人
        game.refresh_tavern(b)
        for f in self._fodders(b):
            self.assertEqual((f.atk, f.max_health), (2, 2))          # 对手


# ══════════════ BG35_MagicItem_152 Demonic Tapestry ══════════════


class TestDemonicTapestry(unittest.TestCase):
    """152 — 主动刷新 num(1) 次后，馆内最高档随从以生命代金购买。"""

    def _setup(self, seed=41):
        game = make_game(seed=seed)
        h = game.heroes[0]
        h.tavern.clear()
        lo = put_tavern(game, h, NO_TAUNT)               # T1
        hi = put_tavern(game, h, "BG28_633")             # Felboar T5
        e = bind(game, h, TAPESTRY)
        return game, h, e, lo, hi

    def _manual_refresh(self, game, h, lo, hi):
        lo.set(GameTag.FROZEN, True)
        hi.set(GameTag.FROZEN, True)
        h.gold = 30
        game.refresh_tavern(h)

    def test_player_refreshes_only_count_toward_threshold(self):
        game, h, e, lo, hi = self._setup()
        d = get_db().get(TAPESTRY)
        h.gold = 30
        for _ in range(3):
            game.refresh_tavern(h, auto=True)
        self.assertEqual(getattr(e, "_tapestry_left"), d.num(0))
        self.assertFalse(getattr(e, "_tapestry_unlocked"))
        self.assertFalse(hi.has(GameTag.HEALTH_BUY))

    def test_unlock_marks_highest_tier_only(self):
        game, h, e, lo, hi = self._setup()
        d = get_db().get(TAPESTRY)
        for _ in range(d.num(0) - 1):
            self._manual_refresh(game, h, lo, hi)
        self.assertFalse(hi.has(GameTag.HEALTH_BUY))     # 未达标（正对照）
        self._manual_refresh(game, h, lo, hi)
        self.assertTrue(getattr(e, "_tapestry_unlocked"))
        self.assertTrue(hi.has(GameTag.HEALTH_BUY))
        self.assertFalse(lo.has(GameTag.HEALTH_BUY))

    def test_buy_with_health_and_marker_moves_to_next(self):
        game, h, e, lo, hi = self._setup()
        d = get_db().get(TAPESTRY)
        for _ in range(d.num(0)):
            self._manual_refresh(game, h, lo, hi)
        cost = hi.get(GameTag.COST, 3)
        gold0 = h.gold
        hp0 = h.health
        self.assertTrue(game.buy_from_tavern(h, hi))
        self.assertEqual(h.gold, gold0)                  # 未花金币
        self.assertEqual(h.health, hp0 - cost)           # 以生命支付
        self.assertFalse(hi.has(GameTag.HEALTH_BUY))
        self.assertTrue(lo.has(GameTag.HEALTH_BUY))      # 次高接替

    def test_before_unlock_buy_costs_gold(self):
        game, h, e, lo, hi = self._setup()
        h.gold = 30
        hp0 = h.health
        gold0 = h.gold
        cost = hi.get(GameTag.COST, 3)
        self.assertTrue(game.buy_from_tavern(h, hi))
        self.assertEqual(h.gold, gold0 - cost)
        self.assertEqual(h.health, hp0)
        # 正对照: 解锁后新建的馆内最高档随从以生命支付
        d = get_db().get(TAPESTRY)
        new_hi = put_tavern(game, h, "BG28_633")
        for _ in range(d.num(0)):
            self._manual_refresh(game, h, new_hi, lo)
        self.assertTrue(new_hi.has(GameTag.HEALTH_BUY))
        hp1 = h.health
        gold1 = h.gold
        self.assertTrue(game.buy_from_tavern(h, new_hi))
        self.assertEqual(h.health, hp1 - new_hi.get(GameTag.COST, 3))
        self.assertEqual(h.gold, gold1)

    def test_insufficient_health_keeps_marker(self):
        game, h, e, lo, hi = self._setup()
        d = get_db().get(TAPESTRY)
        for _ in range(d.num(0)):
            self._manual_refresh(game, h, lo, hi)
        h.health = 1
        h.armor = 0
        self.assertFalse(game.buy_from_tavern(h, hi))
        self.assertIn(hi, h.tavern)
        self.assertTrue(hi.has(GameTag.HEALTH_BUY))

    def test_opponent_tavern_has_no_marker(self):
        game, h, e, lo, hi = self._setup()
        other = game.heroes[1]
        other.tavern.clear()
        put_tavern(game, other, "BG28_633")
        d = get_db().get(TAPESTRY)
        for _ in range(d.num(0)):
            self._manual_refresh(game, h, lo, hi)
        self.assertTrue(hi.has(GameTag.HEALTH_BUY))      # 正对照: 本人有标
        self.assertFalse(any(m.has(GameTag.HEALTH_BUY)
                             for m in other.tavern if isinstance(m, Minion)))


# ══════════════ BG35_MagicItem_154 Ur'zul Sticker ══════════════


class TestUrzulSticker(unittest.TestCase):
    """154 — 打出恶魔后，另一个友方恶魔吞噬馆内随机随从。"""

    def test_play_demon_makes_other_demon_consume(self):
        game = make_game(seed=51)
        a = game.heroes[0]
        a.tavern.clear()
        bind(game, a, URZUL)
        consumer = put(game, a, DEMON_CONSUMER)          # 3/3
        victim = put_tavern(game, a, NO_TAUNT)           # 1/4
        played = put_hand(game, a, DEMON_PLAYED)
        base = (consumer.atk, consumer.max_health)
        self.assertTrue(game.play_minion(a, played))
        self.assertEqual((consumer.atk, consumer.max_health),
                         (base[0] + victim.atk, base[1] + victim.max_health))
        self.assertEqual(a.tavern, [])                   # 受害者被吞噬
        self.assertEqual(victim.zone, Zone.REMOVED)

    def test_only_played_demon_no_consumer(self):
        game = make_game(seed=52)
        a = game.heroes[0]
        a.tavern.clear()
        bind(game, a, URZUL)
        victim = put_tavern(game, a, NO_TAUNT)
        played = put_hand(game, a, DEMON_PLAYED)
        self.assertTrue(game.play_minion(a, played))
        self.assertIn(victim, a.tavern)
        # 正对照: 有第二个恶魔时吞噬发生（消费者随机 → 断言总量）
        consumer = put(game, a, DEMON_CONSUMER)
        played2 = put_hand(game, a, DEMON_PLAYED)
        victim_atk = victim.atk
        victim_hp = victim.max_health
        before = {id(x): (x.atk, x.max_health) for x in (played, consumer)}
        self.assertTrue(game.play_minion(a, played2))
        self.assertNotIn(victim, a.tavern)
        gained_atk = sum(x.atk - before[id(x)][0] for x in (played, consumer))
        gained_hp = sum(x.max_health - before[id(x)][1]
                        for x in (played, consumer))
        self.assertEqual((gained_atk, gained_hp), (victim_atk, victim_hp))

    def test_non_demon_play_does_not_trigger(self):
        game = make_game(seed=53)
        a = game.heroes[0]
        a.tavern.clear()
        bind(game, a, URZUL)
        consumer = put(game, a, DEMON_CONSUMER)
        victim = put_tavern(game, a, NO_TAUNT)
        played = put_hand(game, a, NO_TAUNT)             # 非恶魔
        base = (consumer.atk, consumer.max_health)
        self.assertTrue(game.play_minion(a, played))
        self.assertIn(victim, a.tavern)
        self.assertEqual((consumer.atk, consumer.max_health), base)
        # 正对照: 打出恶魔则触发
        played2 = put_hand(game, a, DEMON_PLAYED)
        self.assertTrue(game.play_minion(a, played2))
        self.assertNotIn(victim, a.tavern)

    def test_magnetize_path_does_not_trigger(self):
        game = make_game(seed=54)
        a = game.heroes[0]
        a.tavern.clear()
        bind(game, a, URZUL)
        consumer = put(game, a, DEMON_CONSUMER)
        victim = put_tavern(game, a, NO_TAUNT)
        host = put(game, a, HOST)                        # 机械宿主
        mag = game.create_minion(DEMON_PLAYED, controller=a)
        mag.set(GameTag.MAGNETIC, True)                  # 磁力路径（合成探针）
        a.hand.append(mag)
        base = (consumer.atk, consumer.max_health)
        self.assertTrue(game.play_minion(a, mag, magnetic_target=host))
        self.assertIn(victim, a.tavern)                  # 未触发吞噬
        self.assertEqual((consumer.atk, consumer.max_health), base)
        # 正对照: 同一恶魔走普通打出路径则触发
        normal = put_hand(game, a, DEMON_PLAYED)
        self.assertTrue(game.play_minion(a, normal))
        self.assertNotIn(victim, a.tavern)

    def test_opponent_demon_does_not_trigger(self):
        game = make_game(seed=55)
        a, b = game.heroes
        a.tavern.clear()
        bind(game, a, URZUL)
        consumer = put(game, a, DEMON_CONSUMER)
        victim = put_tavern(game, a, NO_TAUNT)
        base = (consumer.atk, consumer.max_health)
        played = put_hand(game, b, DEMON_PLAYED)
        self.assertTrue(game.play_minion(b, played))
        self.assertIn(victim, a.tavern)
        self.assertEqual((consumer.atk, consumer.max_health), base)
        # 正对照: 本人打出恶魔则触发
        played2 = put_hand(game, a, DEMON_PLAYED)
        self.assertTrue(game.play_minion(a, played2))
        self.assertNotIn(victim, a.tavern)


# ══════════════ BG35_MagicItem_155 Felburned Ledger ══════════════


class TestFelburnedLedger(unittest.TestCase):
    """155 — 英雄受伤后本回合酒馆法术额外 +num(0)/+num(1)。"""

    def test_damage_grants_extra_and_real_spell_uses_it(self):
        game = make_game()
        a = game.heroes[0]
        d = get_db().get(LEDGER)
        e = bind(game, a, LEDGER)
        target = put(game, a, NO_TAUNT)
        base = (target.atk, target.max_health)
        a.take_damage(1)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), d.num(0))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), d.num(1))
        cast_pool_spell(game, a, SPELL_STATS_ALL)
        spell = get_db().get(SPELL_STATS_ALL)
        self.assertEqual(target.atk, base[0] + spell.num(0) + d.num(0))
        self.assertEqual(target.max_health,
                         base[1] + spell.num(1) + d.num(1))
        game.run_script_hook(e, "start_of_turn")         # 跨回合回退
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 0)

    def test_control_without_damage_gives_base_only(self):
        game = make_game()
        a = game.heroes[0]
        d = get_db().get(LEDGER)
        bind(game, a, LEDGER)
        target = put(game, a, NO_TAUNT)
        base = (target.atk, target.max_health)
        cast_pool_spell(game, a, SPELL_STATS_ALL)
        spell = get_db().get(SPELL_STATS_ALL)
        self.assertEqual((target.atk, target.max_health),
                         (base[0] + spell.num(0), base[1] + spell.num(1)))
        # 正对照: 受伤后同一法术多给 num(0)/num(1)
        a.take_damage(1)
        mid = (target.atk, target.max_health)
        cast_pool_spell(game, a, SPELL_STATS_ALL)
        self.assertEqual(target.atk, mid[0] + spell.num(0) + d.num(0))
        self.assertEqual(target.max_health,
                         mid[1] + spell.num(1) + d.num(1))

    def test_two_damage_instances_stack_then_revert(self):
        game = make_game()
        a = game.heroes[0]
        d = get_db().get(LEDGER)
        e = bind(game, a, LEDGER)
        a.take_damage(1)
        a.take_damage(1)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 2 * d.num(0))
        game.run_script_hook(e, "start_of_turn")
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 0)

    def test_revert_preserves_other_sources(self):
        game = make_game()
        a = game.heroes[0]
        d = get_db().get(LEDGER)
        e = bind(game, a, LEDGER)
        a.set(GameTag.TAVERN_SPELL_EXTRA_ATK, 5)
        a.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 7)
        a.take_damage(1)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK),
                         5 + d.num(0))                   # 受伤确实叠加
        game.run_script_hook(e, "start_of_turn")
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 5)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), 7)

    def test_armor_absorb_counts_as_damage(self):
        game = make_game()
        a = game.heroes[0]
        d = get_db().get(LEDGER)
        bind(game, a, LEDGER)
        a.armor = 5
        a.take_damage(1)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), d.num(0))

    def test_opponent_damage_no_effect(self):
        game = make_game()
        a, b = game.heroes
        d = get_db().get(LEDGER)
        bind(game, a, LEDGER)
        b.take_damage(3)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 0)
        a.take_damage(1)                                 # 正对照: 本人受伤叠加
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), d.num(0))


# ══════════════ BG35_MagicItem_300 Copper Coil ══════════════


class TestCopperCoil(unittest.TestCase):
    """300 — 每次磁力吸附给宿主 +num(0)/+num(1) 并递增。"""

    def test_bonus_improves_each_magnetize(self):
        game = make_game()
        a = game.heroes[0]
        d = get_db().get(COIL)
        bind(game, a, COIL)
        host = put(game, a, HOST)
        mag = get_db().get(MAGNETIC)
        for k in (1, 2):
            base = (host.atk, host.max_health)
            unit = game.create_minion(MAGNETIC, controller=a)
            a.hand.append(unit)
            self.assertTrue(game.play_minion(a, unit, magnetic_target=host))
            expected = (mag.atk + k * d.num(0),
                        mag.health + k * d.num(1))
            self.assertEqual(
                (host.atk - base[0], host.max_health - base[1]), expected)

    def test_non_magnetic_play_does_not_advance(self):
        game = make_game()
        a = game.heroes[0]
        d = get_db().get(COIL)
        bind(game, a, COIL)
        host = put(game, a, HOST)
        plain = put_hand(game, a, NO_TAUNT)
        self.assertTrue(game.play_minion(a, plain))
        unit = game.create_minion(MAGNETIC, controller=a)
        a.hand.append(unit)
        base = (host.atk, host.max_health)
        self.assertTrue(game.play_minion(a, unit, magnetic_target=host))
        self.assertEqual(host.atk - base[0], get_db().get(MAGNETIC).atk
                         + d.num(0))                     # 仍是第一档

    def test_opponent_magnetize_no_bonus(self):
        game = make_game()
        a, b = game.heroes
        bind(game, a, COIL)                              # 只有 A 有饰品
        own_host = put(game, a, HOST)                    # 正对照: 本人有加成
        own_unit = game.create_minion(MAGNETIC, controller=a)
        a.hand.append(own_unit)
        base = (own_host.atk, own_host.max_health)
        self.assertTrue(game.play_minion(a, own_unit,
                                         magnetic_target=own_host))
        d = get_db().get(COIL)
        mag = get_db().get(MAGNETIC)
        self.assertEqual((own_host.atk - base[0],
                          own_host.max_health - base[1]),
                         (mag.atk + d.num(0), mag.health + d.num(1)))
        host = put(game, b, HOST)
        unit = game.create_minion(MAGNETIC, controller=b)
        b.hand.append(unit)
        base = (host.atk, host.max_health)
        self.assertTrue(game.play_minion(b, unit, magnetic_target=host))
        self.assertEqual((host.atk - base[0], host.max_health - base[1]),
                         (mag.atk, mag.health))


# ══════════════ BG35_MagicItem_430 Scrapsmith Portrait ══════════════


class TestScrapsmithPortrait(unittest.TestCase):
    """430 — Get a Bristlemane Scrapsmith；友方嘲讽死亡后给己方 Scrapsmith
    施放永久血宝石。"""

    def test_grants_scrapsmith(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, SCRAPSMITH)
        self.assertEqual([c.card_id for c in a.hand], ["BG24_707"])

    def test_taunt_death_plays_gem_on_scrapsmith(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, SCRAPSMITH)
        smith = put(game, a, "BG24_707")
        taunt = put(game, a, TAUNT)
        base = (smith.atk, smith.max_health)
        kill(game, taunt)
        g = gem_value()
        self.assertEqual((smith.atk, smith.max_health),
                         (base[0] + g, base[1] + g))
        self.assertEqual(smith.get(GameTag.GEMS_PLAYED_ON, 0), 1)

    def test_non_taunt_death_no_gem(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, SCRAPSMITH)
        smith = put(game, a, "BG24_707")
        plain = put(game, a, NO_TAUNT)
        taunt = put(game, a, TAUNT)
        base = (smith.atk, smith.max_health)
        kill(game, plain)
        self.assertEqual((smith.atk, smith.max_health), base)
        kill(game, taunt)                                # 正对照: 嘲讽触发
        self.assertGreater(smith.get(GameTag.GEMS_PLAYED_ON, 0), 0)

    def test_no_scrapsmith_no_effect(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, SCRAPSMITH)
        taunt = put(game, a, TAUNT)
        kill(game, taunt)                                # 不抛
        smith = put(game, a, "BG24_707")                 # 正对照: 有则触发
        taunt2 = put(game, a, TAUNT)
        kill(game, taunt2)
        self.assertEqual(smith.get(GameTag.GEMS_PLAYED_ON, 0), 1)

    def test_opponent_taunt_death_no_effect(self):
        game = make_game()
        a, b = game.heroes
        bind(game, a, SCRAPSMITH)
        smith = put(game, a, "BG24_707")
        foe_taunt = put(game, b, TAUNT)
        base = (smith.atk, smith.max_health)
        kill(game, foe_taunt)
        self.assertEqual((smith.atk, smith.max_health), base)
        own_taunt = put(game, a, TAUNT)                  # 正对照: 己方嘲讽
        kill(game, own_taunt)
        self.assertEqual(smith.get(GameTag.GEMS_PLAYED_ON, 0), 1)

    def test_combat_taunt_death_triggers(self):
        game = make_game(seed=61)
        a, b = game.heroes
        bind(game, a, SCRAPSMITH)
        smith = put(game, a, "BG24_707")
        game.run_actions(Buff(smith, health=100))        # 保证触发时仍存活
        put(game, a, "BG29_300")                         # 2/6 嘲讽（无复生）
        foe = put(game, b, DR_NEUTRAL)
        game.run_actions(Buff(foe, atk=20, health=50))
        played = []
        game.events.register(Listener(
            event="blood_gem_played", owner=a,
            callback=lambda g, target=None, **kw: played.append(target)))
        game.run_combat(a, b)
        self.assertIn(smith, played)                     # 战斗内触发过宝石


# ══════════════ BG35_MagicItem_432 Blood Amulet ══════════════


class TestBloodAmulet(unittest.TestCase):
    """432 — 触发亡语后对 num(0) 个随机友方随从各施放 1 颗永久血宝石。"""

    def test_deathrattle_plays_gem_on_capped_random_minions(self):
        game = make_game(seed=71)
        a = game.heroes[0]
        d = get_db().get(AMULET)
        bind(game, a, AMULET)
        dr = put(game, a, DR_NEUTRAL)
        m1 = put(game, a, NO_TAUNT)
        m2 = put(game, a, NO_TAUNT)
        m3 = put(game, a, NO_TAUNT)
        base = [(m.atk, m.max_health) for m in (m1, m2, m3)]
        kill(game, dr)
        g = gem_value()
        self.assertEqual([m.get(GameTag.GEMS_PLAYED_ON, 0)
                          for m in (m1, m2, m3)], [1, 1, 1])
        self.assertEqual([(m.atk, m.max_health) for m in (m1, m2, m3)],
                         [(b[0] + g, b[1] + g) for b in base])
        self.assertEqual(d.num(0), 3)

    def test_fewer_minions_all_get_gem(self):
        game = make_game(seed=72)
        a = game.heroes[0]
        bind(game, a, AMULET)
        dr = put(game, a, DR_NEUTRAL)
        only = put(game, a, NO_TAUNT)
        kill(game, dr)
        self.assertEqual(only.get(GameTag.GEMS_PLAYED_ON, 0), 1)

    def test_non_deathrattle_death_no_gem(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, AMULET)
        target = put(game, a, NO_TAUNT)
        plain = put(game, a, NO_TAUNT)
        kill(game, plain)
        self.assertEqual(target.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        dr = put(game, a, DR_NEUTRAL)                    # 正对照: 亡语触发
        kill(game, dr)
        self.assertEqual(target.get(GameTag.GEMS_PLAYED_ON, 0), 1)

    def test_empty_board_no_crash(self):
        game = make_game(seed=74)
        a = game.heroes[0]
        bind(game, a, AMULET)
        dr = put(game, a, DR_NEUTRAL)
        kill(game, dr)                                   # 无存活友方 → 落空
        mate = put(game, a, NO_TAUNT)                    # 正对照: 有存活则给
        dr2 = put(game, a, DR_NEUTRAL)
        kill(game, dr2)
        self.assertEqual(mate.get(GameTag.GEMS_PLAYED_ON, 0), 1)

    def test_opponent_deathrattle_no_effect(self):
        game = make_game(seed=75)
        a, b = game.heroes
        bind(game, a, AMULET)
        mine = put(game, a, NO_TAUNT)
        foe_dr = put(game, b, DR_NEUTRAL)
        kill(game, foe_dr)
        self.assertEqual(mine.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        own_dr = put(game, a, DR_NEUTRAL)                # 正对照: 己方亡语
        kill(game, own_dr)
        self.assertEqual(mine.get(GameTag.GEMS_PLAYED_ON, 0), 1)


if __name__ == "__main__":
    unittest.main()
