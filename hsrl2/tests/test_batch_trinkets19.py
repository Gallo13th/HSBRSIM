"""批次 trinkets19 行为层测试（13 注册饰品 + 2 Spellcraft 法术本体 +
7 DEFERRED 台账）。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线 + Action 入队）
  - SoT: `game.run_script_hook(trinket, "start_of_turn")`（引擎真实分发点）
  - 解锁 tick: 真实 `turn_start` 事件（_begin_recruit_for 的广播点）
  - 刷新: 真实 `game.refresh_tavern`（冻结保留）+ 真实 `tavern_refresh`
    事件（`hero.tavern` 受控，避免随机抽取干扰）
  - 战斗: `game.in_combat = True` + `_process_single_death`（Avenge 路径）
  - 打出/施放: 真实 `game.play_minion` / `game.play_spell` /
    `game.sell_minion` / `game.buy_from_tavern`
  - 池: `minion_pool.available` / `spell_pool.available` 前后差

覆盖（SOP §16 空转测试判定法 + TEST_SOP §3 最低矩阵）: 每个行为类至少
一条**正效果**断言（并与同 setup 的负例对照写在同一方法内）; owner
隔离（2 英雄）; 一次性/跨回合/cadence 语义; 满手排队 / 空场落空 /
池抽干落空; `CardDef.num` 双向钉死; 随机局面构造成确定性（单候选 /
不足 4 个随从使 sample 全覆盖 / 单随从酒馆）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.entity import Buff as Enchant
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_trinkets19 as B19
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# ── 测试用既有卡（CardDB 按名核实——禁止凭记忆写 id）──
BEAST = "BG36_206"         # Snarky Shark 4/5 T4 野兽（仅卖出触发——测试中惰性）
DRAGON_A = "BG21_015"      # Tarecgosa 4/4 T2 龙（无打出/召唤触发）
DRAGON_B = "BG24_004"      # Warpwing 12/4 T6 龙（无打出/召唤触发）
ELEMENTAL = "BG31_816"     # Fire Baller 4/3 T2 元素（仅卖出触发）
NAGA = "BG23_000"          # Mini-Myrmidon 1/4 T1 纳迦（Spellcraft 源）
MYRMIDON_SPELL = "BG23_000t"   # Mini-Myrmidon 的 Spellcraft 法术
DUMMY = "BG25_013"         # Rot Hide Gnoll 1/4 T1 亡灵（坦克/祭品——无触发）
REWINDER = "BG26_174"      # Soul Rewinder 2/2 T2 恶魔——`on_summon` 注册
                           # `HERO_DAMAGE_TAKEN` 回退监听（离场注销探针）
SHINY_RING = "BG28_168"    # Shiny Ring: Give your minions +1/+1（池法术）

# ── 本批 id ──
KALEIDOSCOPE = "BG35_MagicItem_821"
DOUBLE_STITCH = "BG35_MagicItem_838"
DOUBLE_STITCH_SPELL = "BG35_MagicItem_838t"
CHROMATIC_TEAR = "BG35_MagicItem_840"
EGG_PORTRAIT = "BG35_MagicItem_842"
CLOUD_SERPENT = "BG35_MagicItem_849"
POCKET_CYCLONE = "BG35_MagicItem_850"
LIGHTNING = "BG35_MagicItem_852"
BALLER = "BG35_MagicItem_861"
AVALANCHE = "BG35_MagicItem_863"
LEAPFROGGER = "BG35_MagicItem_870"
OPHIDIAN = "BG35_MagicItem_872"
OPHIDIAN_SPELL = "BG35_MagicItem_872t"
GROUNDBREAKER = "BG35_MagicItem_924"
CORAL_SPEAR = "BG35_MagicItem_925"

# 关联卡（数据链目标）
EASTERLY_WINDS = "BG34_444"
TEMPERATURE_SHIFT = "BG31_819"
MOUNTING_AVALANCHE = "BG33_899"
GROUNDBREAKER_BASE = "BG31_035"
GROUNDBREAKER_GOLD = "BG31_035_G"
MIGHT_OF_STORMWIND = "BG35_951"
EGG_OF_ENDTIMES = "BG34_639"
TIMEWARPED_LEAPFROGGER = "BG34_Giant_031"

# BG35_MagicItem_834 Rylak Portrait / BG35_MagicItem_920 Bubble Crown 已由
# batch_trinkets30 注册（2026-09-15: `trigger_deathrattle` 统一入口 /
# `CardDef.num(4)` NUM_5 导出）——移出本台账。
# BG35_MagicItem_922 Tide Raiser Portrait 已由 batch_trinkets38 注册
# （2026-09-17: `cast_spell_effect` 广播 `spell_resolved` + 载荷已注册）
# ——移出本台账。
DEFERRED_IDS = (
    "BG35_MagicItem_820",      # Safety Patch（Secret 子系统）
    "BG35_MagicItem_823",      # Timeworn Candelabra（Minor Timewarp 无定义域）
    "BG35_MagicItem_921",      # Cowrie Necklace（"give stats" 类别无定义域）
    # BG35_MagicItem_923 Bewitched Ribbon 已由 batch_trinkets31 注册
    # （2026-09-18: `Buff(persist=True)` 按来源跨战斗持久化，RULES §3.5
    #  例外 4）→ 移出本台账
)
REGISTERED_IDS = (
    KALEIDOSCOPE, DOUBLE_STITCH, DOUBLE_STITCH_SPELL, CHROMATIC_TEAR,
    EGG_PORTRAIT, CLOUD_SERPENT, POCKET_CYCLONE, LIGHTNING, BALLER,
    AVALANCHE, LEAPFROGGER, OPHIDIAN, OPHIDIAN_SPELL, GROUNDBREAKER,
    CORAL_SPEAR,
)

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 1900) -> Game:
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
    """直接入手（不经三连检查——仅用于构造满手场景）。"""
    m = game.create_minion(card_id, controller=hero)
    assert hero.add_to_hand(m)
    return m


def put_tavern(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def set_atk(m: Minion, value: int) -> None:
    m.add_buff(Enchant(atk=value - m.atk))


def play_entity(game: Game, hero: Hero, card_id: str, **kw) -> Minion:
    """真实"从手牌打出"链路，返回入场实体。"""
    m = game.create_minion(card_id, controller=hero, **kw)
    assert game.pending_hand_add(hero, m)
    assert game.play_minion(hero, m), f"{card_id} 未能打出"
    return m


def play_from_hand(game: Game, hero: Hero, card_id: str, **kw) -> bool:
    m = game.create_minion(card_id, controller=hero, **kw)
    game.pending_hand_add(hero, m)
    return game.play_minion(hero, m)


def death_in_combat(game: Game, victim: Minion) -> None:
    """战斗内驱动一次真实死亡处理（Avenge 计数路径）。"""
    prev_c, prev_a = game.in_combat, game._active_combat
    game.in_combat = True
    game._active_combat = (victim.controller, game.heroes[1])
    try:
        victim.set(GameTag.HEALTH, 0)
        game._process_single_death(victim)
    finally:
        game.in_combat = prev_c
        game._active_combat = prev_a


def pool_spell_to_hand(game: Game, hero: Hero, card_id: str):
    assert game.spell_pool.acquire(card_id)
    s = game.create_spell(card_id, controller=hero)
    assert hero.add_to_hand(s)
    return s


def spellcraft_spell(hero: Hero):
    return [e for e in hero.hand if e.has(GameTag.SPELLCRAFT)]


def hand_ids(hero: Hero) -> list:
    return [e.card_id for e in hero.hand]


# ══════════════ 注册表 / DEFERRED 台账（结构性） ══════════════


class TestBatchTrinkets19Registry(unittest.TestCase):
    """@engine-only 结构性: 注册表 / DEFERRED 台账 / 数据链守卫。

    这些断言与脚本钩子无关（把钩子换成 no-op 仍应通过）——按 SOP §16
    末段显式标注，避免被空转审计误判为"行为测试空转"。
    """

    def test_all_registered(self):
        for tid in REGISTERED_IDS:
            self.assertIsNotNone(REGISTRY.get(tid), tid)

    def test_deferred_ledger_not_registered(self):
        for tid in DEFERRED_IDS:
            self.assertIsNone(REGISTRY.get(tid),
                              f"{tid} 应维持 DEFERRED（不注册）")

    def test_spellcraft_trinkets_have_no_start_of_turn(self):
        """防双发: 饰品的每回合法术生成由引擎负责，脚本不得再写 SoT。"""
        for tid in (DOUBLE_STITCH, OPHIDIAN):
            cls = REGISTRY[tid]
            self.assertFalse(hasattr(cls, "start_of_turn"), tid)

    def test_avenge_threshold_matches_carddef(self):
        d = get_db().get(CLOUD_SERPENT)
        self.assertEqual(B19.CloudSerpentHornScript.avenge_threshold,
                         d.num(0))

    def test_related_card_data_chain(self):
        db = get_db()
        # Spellcraft 族经 spellcraft_id; 其余经 evolution_card_id
        for tid, sid in ((DOUBLE_STITCH, DOUBLE_STITCH_SPELL),
                         (OPHIDIAN, OPHIDIAN_SPELL)):
            self.assertEqual(db.get(tid).spellcraft_id, db.get(sid).dbf_id,
                             tid)
        expect = {
            EGG_PORTRAIT: EGG_OF_ENDTIMES,
            POCKET_CYCLONE: EASTERLY_WINDS,
            BALLER: TEMPERATURE_SHIFT,
            AVALANCHE: MOUNTING_AVALANCHE,
            LEAPFROGGER: TIMEWARPED_LEAPFROGGER,
            GROUNDBREAKER: GROUNDBREAKER_BASE,
            CORAL_SPEAR: MIGHT_OF_STORMWIND,
        }
        for tid, rid in expect.items():
            d = db.get(tid)
            self.assertEqual(d.evolution_card_id, db.get(rid).dbf_id, tid)


# ══════════════ BG35_MagicItem_821 Kaleidoscope ══════════════


class TestKaleidoscope(unittest.TestCase):
    """Discover 一张 Tier 7 随从，锁入手牌 num(0)=2 回合。"""

    def test_bind_offers_tier7_discover(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, KALEIDOSCOPE)
        self.assertEqual(len(g.pending_choices), 1)
        choice = g.pending_choices[0]
        self.assertEqual(choice.kind, "discover_minion")
        self.assertIs(choice.owner, a)
        self.assertEqual(len(choice.options), 3)
        for cid in choice.options:
            self.assertEqual(get_db().get(cid).tech_level, 7)
            self.assertTrue(get_db().get(cid).is_pool_minion)

    def test_pick_reserves_pool_and_locks_card(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, KALEIDOSCOPE)
        choice = g.pending_choices.pop(0)
        pick = choice.options[0]
        others = [c for c in choice.options if c != pick]
        # 选项生成即预留（acquire）: 选中的保留、其余释放
        pick_reserved = g.minion_pool.available(pick)
        others_reserved = {c: g.minion_pool.available(c) for c in others}
        choice.choose(0)
        self.assertEqual(hand_ids(a), [pick])
        self.assertEqual(g.minion_pool.available(pick), pick_reserved)
        for c in others:
            self.assertEqual(g.minion_pool.available(c),
                             others_reserved[c] + 1)
        m = a.hand[0]
        self.assertTrue(m.has(GameTag.LOCKED_IN_HAND))
        self.assertFalse(g.play_minion(a, m))

    def test_unlock_after_num0_turn_starts(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, KALEIDOSCOPE)
        g.pending_choices.pop(0).choose(0)
        m = a.hand[0]
        turns = get_db().get(KALEIDOSCOPE).num(0)
        self.assertEqual(turns, 2)
        for tick in range(1, turns + 1):
            g.events.fire(g, "turn_start", turn=g.turn + tick, hero=a)
            locked = m.has(GameTag.LOCKED_IN_HAND)
            self.assertEqual(locked, tick < turns,
                             f"第 {tick} 个 turn_start 后 lock={locked}")
        self.assertTrue(g.play_minion(a, m))
        self.assertIn(m, a.board)

    def test_opponent_turn_start_does_not_unlock(self):
        g = make_game()
        a, b = g.heroes
        bind(g, a, KALEIDOSCOPE)
        g.pending_choices.pop(0).choose(0)
        m = a.hand[0]
        for turn in (2, 3):
            g.events.fire(g, "turn_start", turn=turn, hero=b)
            self.assertTrue(m.has(GameTag.LOCKED_IN_HAND))
        # 链未被对手消耗: 本人两个 turn_start 后照常解锁
        for turn in (2, 3):
            g.events.fire(g, "turn_start", turn=turn, hero=a)
        self.assertFalse(m.has(GameTag.LOCKED_IN_HAND))

    def test_no_tier7_candidates_falls_through(self):
        # 正对照: 同一绑定路径在有 T7 候选时确实开出发现
        g0 = make_game()
        bind(g0, g0.heroes[0], KALEIDOSCOPE)
        self.assertEqual(len(g0.pending_choices), 1)
        # 池抽干 → 落空（无 PendingChoice、不占池、不进手牌）
        g = make_game()
        a = g.heroes[0]
        for d in get_db().pool_minions():
            if d.tech_level != 7:
                continue
            while g.minion_pool.available(d.id) > 0:
                g.minion_pool.acquire(d.id)
        bind(g, a, KALEIDOSCOPE)
        self.assertEqual(len(g.pending_choices), 0)
        self.assertEqual(len(a.hand), 0)


# ══════════════ BG35_MagicItem_838 / 838t Double Stitch Needle ══════════════


class TestDoubleStitchNeedle(unittest.TestCase):
    """Spellcraft: 友方随从属性翻倍 → 收回手牌并锁 1 回合。"""

    def test_bind_grants_first_spellcraft_spell(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, DOUBLE_STITCH)
        self.assertEqual(hand_ids(a), [DOUBLE_STITCH_SPELL])
        self.assertTrue(a.hand[0].has(GameTag.SPELLCRAFT))

    def test_play_doubles_stats_and_returns_to_hand(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, DOUBLE_STITCH)
        target = put(g, a, BEAST)
        atk, mh = target.atk, target.max_health
        spell = a.hand[0]
        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertNotIn(target, a.board)
        self.assertIn(target, a.hand)
        self.assertEqual(target.atk, atk * 2)
        self.assertEqual(target.max_health, mh * 2)
        self.assertTrue(target.has(GameTag.LOCKED_IN_HAND))
        self.assertFalse(g.play_minion(a, target))

    def test_locked_for_one_turn_start_only(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, DOUBLE_STITCH)
        target = put(g, a, BEAST)
        g.play_spell(a, a.hand[0], target=target)
        g.events.fire(g, "turn_start", turn=2, hero=g.heroes[1])
        self.assertTrue(target.has(GameTag.LOCKED_IN_HAND))   # 对手不解锁
        g.events.fire(g, "turn_start", turn=2, hero=a)
        self.assertFalse(target.has(GameTag.LOCKED_IN_HAND))
        self.assertTrue(g.play_minion(a, target))

    def test_opponent_minion_is_not_a_valid_target(self):
        g = make_game()
        a, b = g.heroes
        bind(g, a, DOUBLE_STITCH)
        mine = put(g, a, BEAST)
        theirs = put(g, b, BEAST)
        mine_atk = mine.atk
        theirs_atk, theirs_mh = theirs.atk, theirs.max_health
        spell = a.hand[0]
        # 引擎默认候选 = 施放者棋盘（对手随从不在候选）; 显式传入对手实体
        # 也必须落空（on_play 守卫）
        self.assertTrue(g.play_spell(a, spell, target=theirs))
        self.assertEqual((theirs.atk, theirs.max_health),
                         (theirs_atk, theirs_mh))
        self.assertIn(theirs, b.board)
        self.assertNotIn(theirs, a.hand)
        self.assertEqual(mine.atk, mine_atk)

    def test_stale_target_falls_through(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, DOUBLE_STITCH)
        target = put(g, a, BEAST)
        atk, mh = target.atk, target.max_health
        a.board.remove(target)
        target.zone = Zone.REMOVED
        g._update_positions(a)
        spell = a.hand[0]
        self.assertTrue(g.play_spell(a, spell, target=target))
        self.assertNotIn(target, a.hand)
        self.assertEqual((target.atk, target.max_health), (atk, mh))

    def test_full_hand_still_returns_minion(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, DOUBLE_STITCH)
        target = put(g, a, BEAST)
        spell = a.hand[0]
        while not a.hand_full():
            put_hand(g, a, DUMMY)
        self.assertTrue(g.play_spell(a, spell, target=target))
        # 打出法术腾出 1 格 → 归还在手（满手也不销毁，RULES §3.3）
        self.assertIn(target, a.hand)
        self.assertNotIn(target, a.board)

    def test_return_to_hand_unregisters_minion_listeners(self):
        """离场注销（引擎不变式，ENGINE_BACKLOG #40）: 棋盘→手牌后该随从
        的 in-play 监听器必须失效，英雄伤害不再被回退。

        真实路径: 真实 `summon`（`BG26_174` Soul Rewinder 的 `on_summon`
        注册 `HERO_DAMAGE_TAKEN` 回退监听）→ 真实 `play_spell` 施放
        Double Stitch 法术（目标属性翻倍后收回手牌并锁 1 回合）。
        断言: (a) 离场后该实体的监听器全部注销; (b) 未离场的负对照随从
        监听器保留且仍能回退伤害; (c) 移除负对照后，受伤**不再被回退**
        （证明离场者无残留监听器）。
        变异探针: 去掉 `Entity.zone` setter 的离场注销 → (a)/(c) 均失败
        （修复前实测: owner 停在 `Zone.HAND` 且 `take_damage(3)` 后
        health 不变）。
        """
        from hsrl2.events import HERO_DAMAGE_TAKEN
        g = make_game()
        a = g.heroes[0]
        bind(g, a, DOUBLE_STITCH)
        # 被移动者（离场）+ 负对照（仍在板上的另一张 Rewinder）
        rewinder = put(g, a, REWINDER)
        witness = put(g, a, REWINDER)
        live = [l.owner for l in g.events._listeners.get(
            HERO_DAMAGE_TAKEN, [])]
        self.assertIn(rewinder, live)
        self.assertIn(witness, live)
        spell = spellcraft_spell(a)[0]
        self.assertTrue(g.play_spell(a, spell, target=rewinder))
        self.assertIn(rewinder, a.hand)
        self.assertNotIn(rewinder, a.board)
        owners = [l.owner for l in g.events._listeners.get(
            HERO_DAMAGE_TAKEN, [])]
        # (a) 离场者监听器注销; (b) 未离场者保留
        self.assertNotIn(rewinder, owners)
        self.assertIn(witness, owners)
        # (b) 负对照仍活着: 受伤被在场 Rewinder 回退
        before = (a.health, a.armor)
        a.take_damage(3)
        self.assertEqual((a.health, a.armor), before)
        # (c) 隔离离场者: 移除负对照后受伤不再被回退（无残留监听器）
        g.events.unregister_owner(witness)
        before = (a.health, a.armor)
        a.take_damage(3)
        self.assertEqual((a.health, a.armor), (before[0] - 3, before[1]))


# ══════════════ BG35_MagicItem_840 Chromatic Tear ══════════════


class TestChromaticTear(unittest.TestCase):
    """"Get a random Chromadrake" + 每回合开始重复。"""

    def test_bind_grants_random_chromadrake_without_pool(self):
        g = make_game()
        a = g.heroes[0]
        avail_before = {cid: g.minion_pool.available(cid)
                        for cid in B19._CHROMADRAKE_IDS}
        bind(g, a, CHROMATIC_TEAR)
        self.assertEqual(len(a.hand), get_db().get(CHROMATIC_TEAR).num(0))
        self.assertIn(a.hand[0].card_id, B19._CHROMADRAKE_IDS)
        for cid in B19._CHROMADRAKE_IDS:      # 非池卡: 池不变
            self.assertEqual(g.minion_pool.available(cid), avail_before[cid])

    def test_start_of_turn_grants_again(self):
        g = make_game()
        a = g.heroes[0]
        t = bind(g, a, CHROMATIC_TEAR)
        for expected in (2, 3):
            g.run_script_hook(t, "start_of_turn")
            self.assertEqual(len(a.hand), expected)
            self.assertIn(a.hand[-1].card_id, B19._CHROMADRAKE_IDS)

    def test_opponent_hand_unaffected(self):
        g = make_game()
        a, b = g.heroes
        bind(g, a, CHROMATIC_TEAR)
        self.assertEqual(len(a.hand), 1)          # 正对照: 绑定者拿到卡
        self.assertIn(a.hand[0].card_id, B19._CHROMADRAKE_IDS)
        self.assertEqual(len(b.hand), 0)


# ══════════════ BG35_MagicItem_842 Egg of the Endtimes Portrait ══════════════


class TestEggOfTheEndtimesPortrait(unittest.TestCase):
    """"Get an Egg of the Endtimes" + 每 num(1) 回合开始重复。"""

    def test_bind_grants_related_card(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, EGG_PORTRAIT)
        self.assertEqual(hand_ids(a), [EGG_OF_ENDTIMES])
        self.assertIn(a.hand[0], a.hand)

    def test_repeats_every_num1_turn_starts(self):
        g = make_game()
        a = g.heroes[0]
        t = bind(g, a, EGG_PORTRAIT)
        every = get_db().get(EGG_PORTRAIT).num(1)
        self.assertEqual(every, 2)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(a.hand), 1)       # 第 1 次不发放
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(a.hand), 2)       # 第 num(1) 次发放
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(a.hand), 2)       # 复位滚动
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(a.hand), 3)

    def test_opponent_hand_unaffected(self):
        g = make_game()
        a, b = g.heroes
        t = bind(g, a, EGG_PORTRAIT)
        g.run_script_hook(t, "start_of_turn")
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(a.hand), 2)          # 正对照: 绑定者收到
        self.assertEqual(len(b.hand), 0)


# ══════════════ BG35_MagicItem_849 Cloud Serpent Horn ══════════════


class TestCloudSerpentHorn(unittest.TestCase):
    """Avenge(3): 最右随从的攻击力给另一条友方龙。"""

    def _arm(self, g, a):
        bind(g, a, CLOUD_SERPENT)
        other = put(g, a, DRAGON_A)
        right = put(g, a, DRAGON_B)
        return other, right

    def test_avenge_gives_rightmost_attack_to_other_dragon(self):
        g = make_game()
        a = g.heroes[0]
        other, right = self._arm(g, a)
        other_atk, other_mh = other.atk, other.max_health
        right_atk = right.atk
        self.assertGreater(right_atk, 0)
        threshold = get_db().get(CLOUD_SERPENT).num(0)
        for _ in range(threshold - 1):
            dummy = put(g, a, DUMMY)
            death_in_combat(g, dummy)
        self.assertEqual(other.atk, other_atk)          # 未达阈值不触发
        dummy = put(g, a, DUMMY)
        death_in_combat(g, dummy)
        self.assertEqual(other.atk, other_atk + right_atk)
        self.assertEqual(other.max_health, other_mh)    # 只给攻击力
        self.assertEqual(right.atk, right_atk)          # 源不变

    def test_no_other_dragon_falls_through(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, CLOUD_SERPENT)
        only = put(g, a, DRAGON_A)      # 唯一龙 = 也是最右者 → 无"另一条"
        atk = only.atk
        threshold = get_db().get(CLOUD_SERPENT).num(0)
        for _ in range(threshold):
            dummy = put(g, a, DUMMY)
            death_in_combat(g, dummy)
        self.assertEqual(only.atk, atk)          # 落空: 无候选
        # 正对照: 补上"另一条龙"后同一阈值触发即有增益
        # （新龙成为最右者 → 目标 = 原本唯一的龙）
        new_right = put(g, a, DRAGON_A)
        new_right_atk = new_right.atk
        for _ in range(threshold):
            dummy = put(g, a, DUMMY)
            death_in_combat(g, dummy)
        self.assertEqual(only.atk, atk + new_right_atk)
        self.assertEqual(new_right.atk, new_right_atk)

    def test_recruit_phase_death_not_counted(self):
        g = make_game()
        a = g.heroes[0]
        other, right = self._arm(g, a)
        atk = other.atk
        for _ in range(get_db().get(CLOUD_SERPENT).num(0)):
            dummy = put(g, a, DUMMY)
            dummy.set(GameTag.HEALTH, 0)
            g._process_single_death(dummy)       # 招募期死亡
        self.assertEqual(other.atk, atk)
        trinket = a.trinkets[-1]
        self.assertEqual(trinket.get(GameTag.AVENGE_COUNTER, 0), 0)
        # 正对照: 同 setup 改到战斗内死亡 → 计数并触发增益
        for _ in range(get_db().get(CLOUD_SERPENT).num(0)):
            dummy = put(g, a, DUMMY)
            death_in_combat(g, dummy)
        self.assertEqual(other.atk, atk + right.atk)

    def test_opponent_deaths_not_counted(self):
        g = make_game()
        a, b = g.heroes
        other, right = self._arm(g, a)
        atk = other.atk
        for _ in range(get_db().get(CLOUD_SERPENT).num(0)):
            dummy = put(g, b, DUMMY)
            death_in_combat(g, dummy)
        self.assertEqual(other.atk, atk)          # 对手死亡不计数
        # 正对照: 本人战斗内死亡达阈值 → 增益发生
        for _ in range(get_db().get(CLOUD_SERPENT).num(0)):
            dummy = put(g, a, DUMMY)
            death_in_combat(g, dummy)
        self.assertEqual(other.atk, atk + right.atk)


# ══════════════ BG35_MagicItem_850 Pocket Cyclone ══════════════


class TestPocketCyclone(unittest.TestCase):
    """"Cast Easterly Winds" + 每回合开始再施放一次。"""

    def _tavern_one(self, g, a):
        a.tavern.clear()                 # 只留受控的 1 只（Easterly 随机目标确定）
        m = put_tavern(g, a, BEAST)
        a._tavern_offer_override = 1     # 冻结保留 1 只 → 不再抽新随从
        return m

    @staticmethod
    def _freeze(g, a, m):
        a.set(GameTag.FROZEN, True)
        for e in a.tavern:
            e.set(GameTag.FROZEN, True)

    def test_bind_casts_easterly_winds(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, POCKET_CYCLONE)
        m = self._tavern_one(g, a)
        d = get_db().get(EASTERLY_WINDS)
        atk, mh = m.atk, m.max_health
        self._freeze(g, a, m)
        g.refresh_tavern(a)
        self.assertEqual(m.atk, atk + d.num(0))
        self.assertEqual(m.max_health, mh + d.num(1))

    def test_each_turn_casts_again(self):
        g = make_game()
        a = g.heroes[0]
        t = bind(g, a, POCKET_CYCLONE)
        m = self._tavern_one(g, a)
        d = get_db().get(EASTERLY_WINDS)
        atk, mh = m.atk, m.max_health
        self._freeze(g, a, m)
        g.refresh_tavern(a)                        # 第 1 份效果
        self.assertEqual(m.atk, atk + d.num(0))
        self.assertEqual(m.max_health, mh + d.num(1))
        g.run_script_hook(t, "start_of_turn")      # 再施放一份（效果叠加）
        self._freeze(g, a, m)
        g.refresh_tavern(a)                        # 两份效果各触发一次
        self.assertEqual(m.atk, atk + 3 * d.num(0))
        self.assertEqual(m.max_health, mh + 3 * d.num(1))

    def test_opponent_refresh_no_buff(self):
        g = make_game()
        a, b = g.heroes
        bind(g, a, POCKET_CYCLONE)
        m = self._tavern_one(g, a)
        atk = m.atk
        self._freeze(g, a, m)
        g.refresh_tavern(b)                       # 对手刷新
        self.assertEqual(m.atk, atk)              # 不作用于本人酒馆
        # 正对照: 本人刷新 → 效果发生
        self._freeze(g, a, m)
        g.refresh_tavern(a)
        self.assertEqual(m.atk, atk + get_db().get(EASTERLY_WINDS).num(0))


# ══════════════ BG35_MagicItem_852 Lightning in a Bottle ══════════════


class TestLightningInABottle(unittest.TestCase):
    """刷新后: 馆内最高攻随从的属性给最低攻随从。"""

    def _setup(self, g, a):
        bind(g, a, LIGHTNING)
        a.tavern.clear()
        lo = put_tavern(g, a, BEAST)
        hi = put_tavern(g, a, DRAGON_B)
        set_atk(lo, 1)
        set_atk(hi, 9)
        return lo, hi

    def test_refresh_gives_highest_stats_to_lowest(self):
        g = make_game()
        a = g.heroes[0]
        lo, hi = self._setup(g, a)
        lo_atk, lo_mh = lo.atk, lo.max_health
        hi_atk, hi_mh = hi.atk, hi.max_health
        g.events.fire(g, "tavern_refresh", hero=a, auto=False)
        self.assertEqual(lo.atk, lo_atk + hi_atk)
        self.assertEqual(lo.max_health, lo_mh + hi_mh)
        self.assertEqual((hi.atk, hi.max_health), (hi_atk, hi_mh))

    def test_single_minion_tavern_transfers_to_itself(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, LIGHTNING)
        a.tavern.clear()
        solo = put_tavern(g, a, BEAST)
        set_atk(solo, 4)
        atk, mh = solo.atk, solo.max_health
        g.events.fire(g, "tavern_refresh", hero=a, auto=True)
        self.assertEqual(solo.atk, atk * 2)
        self.assertEqual(solo.max_health, mh * 2)

    def test_empty_tavern_falls_through(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, LIGHTNING)
        a.tavern.clear()
        g.events.fire(g, "tavern_refresh", hero=a, auto=False)  # 不抛错
        self.assertEqual(a.tavern, [])
        # 正对照: 馆内放入随从后同一事件确实生效
        m = put_tavern(g, a, BEAST)
        atk = m.atk
        g.events.fire(g, "tavern_refresh", hero=a, auto=False)
        self.assertEqual(m.atk, atk * 2)

    def test_opponent_refresh_does_not_touch_my_tavern(self):
        g = make_game()
        a, b = g.heroes
        lo, hi = self._setup(g, a)
        atk, mh = lo.atk, lo.max_health
        g.events.fire(g, "tavern_refresh", hero=b, auto=False)
        self.assertEqual((lo.atk, lo.max_health), (atk, mh))
        # 正对照: 本人刷新 → 转移发生
        g.events.fire(g, "tavern_refresh", hero=a, auto=False)
        self.assertGreater(lo.atk, atk)

    def test_only_tavern_minions_considered(self):
        """棋盘随从不在酒馆 → 不参与（作用域只限酒馆）。"""
        g = make_game()
        a = g.heroes[0]
        bind(g, a, LIGHTNING)
        a.tavern.clear()
        board_minion = put(g, a, BEAST)
        set_atk(board_minion, 99)
        solo = put_tavern(g, a, DRAGON_B)
        set_atk(solo, 3)
        atk, mh = solo.atk, solo.max_health
        g.events.fire(g, "tavern_refresh", hero=a, auto=False)
        self.assertEqual(solo.atk, atk * 2)          # 单馆内随从自我加倍
        self.assertEqual(solo.max_health, mh * 2)
        self.assertEqual(board_minion.atk, 99)       # 棋盘随从不受影响


# ══════════════ BG35_MagicItem_861 Baller Portrait ══════════════


class TestBallerPortrait(unittest.TestCase):
    """"Get a Temperature Shift" + 每打出 num(1)=10 张元素重复。"""

    def _play_elemental(self, g, a):
        m = play_entity(g, a, ELEMENTAL)
        g.sell_minion(a, m)

    def test_bind_grants_temperature_shift_and_pool(self):
        g = make_game()
        a = g.heroes[0]
        before = g.spell_pool.available(TEMPERATURE_SHIFT)
        bind(g, a, BALLER)
        self.assertEqual(hand_ids(a), [TEMPERATURE_SHIFT])
        self.assertEqual(g.spell_pool.available(TEMPERATURE_SHIFT),
                         before - 1)

    def test_eleven_elementals_repeat(self):
        g = make_game()
        a = g.heroes[0]
        t = bind(g, a, BALLER)
        every = get_db().get(BALLER).num(1)
        # 37.0（255130）: 官方把阈值 10 改为 11（NUM_2 10→11）
        self.assertEqual(every, 11)
        for _ in range(every - 1):
            self._play_elemental(g, a)
        self.assertEqual(len(a.hand), 1)             # 未达阈值不发放
        self.assertEqual(getattr(t, "_baller_n"), every - 1)
        self._play_elemental(g, a)
        self.assertEqual(len(a.hand), 2)             # 第 num(1) 张发放
        self.assertEqual(getattr(t, "_baller_n"), 0)

    def test_non_elemental_not_counted(self):
        g = make_game()
        a = g.heroes[0]
        t = bind(g, a, BALLER)
        for _ in range(get_db().get(BALLER).num(1)):
            m = play_entity(g, a, DUMMY)
            g.sell_minion(a, m)
        self.assertEqual(getattr(t, "_baller_n"), 0)
        self.assertEqual(len(a.hand), 1)

    def test_opponent_elementals_not_counted(self):
        g = make_game()
        a, b = g.heroes
        t = bind(g, a, BALLER)
        for _ in range(get_db().get(BALLER).num(1)):
            m = play_entity(g, b, ELEMENTAL)
            g.sell_minion(b, m)
        self.assertEqual(getattr(t, "_baller_n"), 0)
        self.assertEqual(len(a.hand), 1)


# ══════════════ BG35_MagicItem_863 Avalanche Sticker ══════════════


class TestAvalancheSticker(unittest.TestCase):
    """"Get a Mounting Avalanche" + 每卖出 num(1)=4 个随从重复。"""

    def test_bind_grants_mounting_avalanche_and_pool(self):
        g = make_game()
        a = g.heroes[0]
        before = g.spell_pool.available(MOUNTING_AVALANCHE)
        bind(g, a, AVALANCHE)
        self.assertEqual(hand_ids(a), [MOUNTING_AVALANCHE])
        # 37.0（255130）: Mounting Avalanche（BG33_899）已退出池内法术 →
        # 交付为**零池操作**（available 恒 0）；池内法术仍须占 1 份。
        if before > 0:
            self.assertEqual(g.spell_pool.available(MOUNTING_AVALANCHE),
                             before - 1)
        else:
            self.assertEqual(g.spell_pool.available(MOUNTING_AVALANCHE), 0)

    def test_four_sells_repeat(self):
        g = make_game()
        a = g.heroes[0]
        t = bind(g, a, AVALANCHE)
        every = get_db().get(AVALANCHE).num(1)
        self.assertEqual(every, 4)
        for _ in range(every - 1):
            m = put(g, a, DUMMY)
            g.sell_minion(a, m)
        self.assertEqual(len(a.hand), 1)
        self.assertEqual(getattr(t, "_avalanche_n"), every - 1)
        m = put(g, a, DUMMY)
        g.sell_minion(a, m)
        self.assertEqual(len(a.hand), 2)
        self.assertEqual(getattr(t, "_avalanche_n"), 0)

    def test_opponent_sells_not_counted(self):
        g = make_game()
        a, b = g.heroes
        t = bind(g, a, AVALANCHE)
        for _ in range(get_db().get(AVALANCHE).num(1)):
            m = put(g, b, DUMMY)
            g.sell_minion(b, m)
        self.assertEqual(getattr(t, "_avalanche_n"), 0)
        self.assertEqual(len(a.hand), 1)


# ══════════════ BG35_MagicItem_870 Leapfrogger Portrait ══════════════


class TestLeapfroggerPortrait(unittest.TestCase):
    """"Get a Timewarped Leapfrogger"（池外卡，纯交付）。"""

    def test_bind_grants_related_card(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, LEAPFROGGER)
        self.assertEqual(hand_ids(a), [TIMEWARPED_LEAPFROGGER])
        self.assertFalse(get_db().get(TIMEWARPED_LEAPFROGGER).is_pool_minion)

    def test_opponent_hand_unaffected(self):
        g = make_game()
        a, b = g.heroes
        bind(g, a, LEAPFROGGER)
        self.assertEqual(hand_ids(a), [TIMEWARPED_LEAPFROGGER])  # 正对照
        self.assertEqual(len(b.hand), 0)

    def test_full_hand_queues_grant(self):
        g = make_game()
        a = g.heroes[0]
        while not a.hand_full():
            put_hand(g, a, DUMMY)
        bind(g, a, LEAPFROGGER)
        self.assertTrue(a.hand_full())
        self.assertEqual(hand_ids(a), [DUMMY] * len(a.hand))
        self.assertEqual(len(g.pending_hand_queue), 1)
        self.assertEqual(g.pending_hand_queue[0][1].card_id,
                         TIMEWARPED_LEAPFROGGER)


# ══════════════ BG35_MagicItem_872 / 872t Ophidian Staff ══════════════


class TestOphidianStaff(unittest.TestCase):
    """Spellcraft: 定向一只野兽 +2/+2 与 Reborn。"""

    def test_bind_grants_first_spellcraft_spell(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, OPHIDIAN)
        self.assertEqual(hand_ids(a), [OPHIDIAN_SPELL])
        self.assertTrue(a.hand[0].has(GameTag.SPELLCRAFT))

    def test_play_buffs_beast_and_gives_reborn(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, OPHIDIAN)
        beast = put(g, a, BEAST)
        atk, mh = beast.atk, beast.max_health
        self.assertTrue(g.play_spell(a, a.hand[0], target=beast))
        self.assertEqual(beast.atk, atk + B19._OPHIDIAN_BONUS)
        self.assertEqual(beast.max_health, mh + B19._OPHIDIAN_BONUS)
        self.assertTrue(beast.has(GameTag.REBORN))

    def test_candidates_only_beasts(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, OPHIDIAN)
        beast = put(g, a, BEAST)
        other = put(g, a, DUMMY)
        spell = a.hand[0]
        cands = B19.OphidianStaffSpellScript.target_candidates(spell, g)
        self.assertIn(beast, cands)
        self.assertNotIn(other, cands)

    def test_no_beast_falls_through(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, OPHIDIAN)
        put(g, a, DUMMY)                 # 非野兽
        spell = a.hand[0]
        self.assertTrue(g.play_spell(a, spell))
        self.assertEqual(len(g.pending_choices), 0)
        self.assertEqual(a.board[0].atk, get_db().get(DUMMY).atk)
        self.assertFalse(a.board[0].has(GameTag.REBORN))

    def test_opponent_beast_not_target(self):
        g = make_game()
        a, b = g.heroes
        bind(g, a, OPHIDIAN)
        theirs = put(g, b, BEAST)
        atk = theirs.atk
        self.assertTrue(g.play_spell(a, a.hand[0], target=theirs))
        self.assertEqual(theirs.atk, atk)
        self.assertFalse(theirs.has(GameTag.REBORN))


# ══════════════ BG35_MagicItem_924 Groundbreaker Portrait ══════════════


class TestGroundbreakerPortrait(unittest.TestCase):
    """"Get a Groundbreaker"; 其增益同时给左边随从。"""

    def test_playing_naga_mirrors_stats_to_left(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, GROUNDBREAKER)
        left = put(g, a, BEAST)
        gb = put(g, a, GROUNDBREAKER_BASE)
        gb_def = get_db().get(GROUNDBREAKER_BASE)
        l_atk, l_mh = left.atk, left.max_health
        gb_atk, gb_mh = gb.atk, gb.max_health
        self.assertTrue(play_from_hand(g, a, NAGA))
        amount = gb_def.num(1) * (1 + a.get(
            GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0) // gb_def.num(0))
        self.assertEqual(gb.atk, gb_atk + amount)     # 本体行为正对照
        self.assertEqual(gb.max_health, gb_mh + amount)
        self.assertEqual(left.atk, l_atk + amount)    # 镜像到左邻
        self.assertEqual(left.max_health, l_mh + amount)

    def test_golden_groundbreaker_uses_golden_num(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, GROUNDBREAKER)
        left = put(g, a, BEAST)
        gb = put(g, a, GROUNDBREAKER_BASE, golden=True)
        self.assertEqual(gb.card_id, GROUNDBREAKER_GOLD)
        l_atk = left.atk
        self.assertTrue(play_from_hand(g, a, NAGA))
        self.assertEqual(left.atk, l_atk + get_db().get(
            GROUNDBREAKER_GOLD).num(1))

    def test_leftmost_groundbreaker_has_no_left_neighbor(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, GROUNDBREAKER)
        gb = put(g, a, GROUNDBREAKER_BASE)
        right = put(g, a, BEAST)
        r_atk = right.atk
        gb_atk = gb.atk
        self.assertTrue(play_from_hand(g, a, NAGA))
        self.assertGreater(gb.atk, gb_atk)            # 本体照常增益
        self.assertEqual(right.atk, r_atk)            # 右侧不受影响
        # 正对照: 另一局把 Groundbreaker 放在有左邻的位置 → 镜像发生
        g2 = make_game()
        b = g2.heroes[0]
        bind(g2, b, GROUNDBREAKER)
        left2 = put(g2, b, BEAST)
        put(g2, b, GROUNDBREAKER_BASE)
        l2_atk = left2.atk
        self.assertTrue(play_from_hand(g2, b, NAGA))
        self.assertGreater(left2.atk, l2_atk)

    def test_non_naga_not_counted(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, GROUNDBREAKER)
        left = put(g, a, BEAST)
        put(g, a, GROUNDBREAKER_BASE)
        l_atk = left.atk
        self.assertTrue(play_from_hand(g, a, BEAST))
        self.assertEqual(left.atk, l_atk)             # 非 Naga 不触发
        # 正对照: 打 Naga → 左邻获得
        self.assertTrue(play_from_hand(g, a, NAGA))
        self.assertGreater(left.atk, l_atk)

    def test_opponent_naga_no_effect(self):
        g = make_game()
        a, b = g.heroes
        bind(g, a, GROUNDBREAKER)
        left = put(g, a, BEAST)
        put(g, a, GROUNDBREAKER_BASE)
        l_atk = left.atk
        self.assertTrue(play_from_hand(g, b, NAGA))
        self.assertEqual(left.atk, l_atk)             # owner 隔离
        # 正对照: 本人打 Naga → 左邻获得
        self.assertTrue(play_from_hand(g, a, NAGA))
        self.assertGreater(left.atk, l_atk)


# ══════════════ BG35_MagicItem_925 Coral Spear ══════════════


class TestCoralSpear(unittest.TestCase):
    """每施放 Spellcraft 法术 → Cast Might of Stormwind。"""

    def _four(self, g, a):
        return [put(g, a, DUMMY) for _ in range(4)]

    def test_spellcraft_cast_casts_might_of_stormwind(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, CORAL_SPEAR)
        minions = self._four(g, a)
        mm = put(g, a, NAGA)               # spellcraft 源 → 入手 1 张法术
        spells = spellcraft_spell(a)
        self.assertEqual([s.card_id for s in spells], [MYRMIDON_SPELL])
        g.sell_minion(a, mm)               # 板上恰 4 只 → sample 全覆盖
        self.assertEqual(len([m for m in a.board if not m.dead]), 4)
        before = [(m.atk, m.max_health) for m in minions]
        target = minions[0]
        self.assertTrue(g.play_spell(a, spells[0], target=target))
        d = get_db().get(MIGHT_OF_STORMWIND)
        target_bonus = get_db().get(MYRMIDON_SPELL).num(0) or 2
        for idx, (m, (atk, mh)) in enumerate(zip(minions, before)):
            self.assertEqual(m.max_health, mh + d.num(1))
            extra = target_bonus if m is target else 0
            self.assertEqual(m.atk, atk + d.num(0) + extra)

    def test_non_spellcraft_spell_does_not_trigger(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, CORAL_SPEAR)
        minions = self._four(g, a)
        before = [(m.atk, m.max_health) for m in minions]
        ring = pool_spell_to_hand(g, a, SHINY_RING)
        self.assertTrue(g.play_spell(a, ring))
        for m, (atk, mh) in zip(minions, before):
            self.assertEqual(m.atk, atk + 1)         # 只有 Shiny Ring 的 +1/+1
            self.assertEqual(m.max_health, mh + 1)   # Might of Stormwind 未触发
        # 正对照: 改施放 Spellcraft 法术 → Might of Stormwind 生效
        src = put(g, a, NAGA)
        mm_spell = spellcraft_spell(a)[0]
        g.sell_minion(a, src)          # 板上恰 4 只 → sample 全覆盖
        mid = [(m.atk, m.max_health) for m in minions]
        self.assertTrue(g.play_spell(a, mm_spell, target=minions[0]))
        d = get_db().get(MIGHT_OF_STORMWIND)
        for m, (atk, mh) in zip(minions, mid):
            self.assertEqual(m.max_health, mh + d.num(1))

    def test_opponent_spellcraft_no_effect(self):
        g = make_game()
        a, b = g.heroes
        bind(g, a, CORAL_SPEAR)
        mine = self._four(g, a)
        before = [(m.atk, m.max_health) for m in mine]
        put(g, b, NAGA)
        spells = spellcraft_spell(b)
        self.assertTrue(g.play_spell(b, spells[0], target=b.board[0]))
        for m, (atk, mh) in zip(mine, before):
            self.assertEqual((m.atk, m.max_health), (atk, mh))
        # 正对照: 本人施放 Spellcraft → 本批饰品确实触发
        src = put(g, a, NAGA)
        mine_spells = spellcraft_spell(a)
        g.sell_minion(a, src)          # 板上恰 4 只 → sample 全覆盖
        self.assertTrue(g.play_spell(a, mine_spells[0], target=mine[0]))
        d = get_db().get(MIGHT_OF_STORMWIND)
        for m, (atk, mh) in zip(mine, before):
            self.assertEqual(m.max_health, mh + d.num(1))

    def test_empty_board_falls_through(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, CORAL_SPEAR)
        mm = put(g, a, NAGA)
        spells = spellcraft_spell(a)
        g.sell_minion(a, mm)
        self.assertEqual([m for m in a.board if not m.dead], [])
        self.assertTrue(g.play_spell(a, spells[0]))   # 不抛错
        self.assertEqual(g.pending_choices, [])
        self.assertNotIn(spells[0], a.hand)           # 法术照常消耗
        # 正对照: 有随从时同一链路确实结算 Might of Stormwind
        minions = [put(g, a, DUMMY) for _ in range(4)]
        mm2 = put(g, a, NAGA)          # 唯一 spellcraft 源
        spells2 = spellcraft_spell(a)
        g.sell_minion(a, mm2)          # 板上恰 4 只 → sample 全覆盖
        before = [m.max_health for m in minions]
        self.assertTrue(g.play_spell(a, spells2[0], target=minions[0]))
        d = get_db().get(MIGHT_OF_STORMWIND)
        for m, mh in zip(minions, before):
            self.assertEqual(m.max_health, mh + d.num(1))

    def test_double_cast_triggers_per_cast(self):
        """双施（SPELL_DOUBLER）按**施放次数**结算 Might of Stormwind。

        旧实现监听 `spellcraft_cast`（每次**打出**只 fire 一次）→ 双施
        只得 1 次 Might; 本条即证伪旧实现。Might 每次恰对 4 只随机友方
        随从 +num(1) 生命（Spellcraft 原法术不涉生命）→ 总生命增量是
        与随机性无关的确定性读数。
        """
        g = make_game()
        a = g.heroes[0]
        bind(g, a, CORAL_SPEAR)
        board = [put(g, a, DUMMY) for _ in range(4)]
        doubler = put(g, a, DUMMY)
        doubler.set(GameTag.SPELL_DOUBLER, True)
        src = put(g, a, NAGA)
        spell = spellcraft_spell(a)[0]
        g.sell_minion(a, src)
        d = get_db().get(MIGHT_OF_STORMWIND)
        before = sum(m.max_health for m in board) + doubler.max_health
        self.assertTrue(g.play_spell(a, spell, target=board[0]))
        after = sum(m.max_health for m in board) + doubler.max_health
        self.assertEqual(after - before, 2 * 4 * d.num(1))


# ══════════════ 引擎层探针（Avenge 场景 + 池账） ══════════════


class TestEngineProbes(unittest.TestCase):
    """@engine-only 交叉验证: 本批实现依赖的引擎契约（不注入本批钩子）。"""

    def test_avenge_counter_resets_each_combat(self):
        g = make_game()
        a, b = g.heroes
        bind(g, a, CLOUD_SERPENT)
        trinket = a.trinkets[-1]
        trinket.set(GameTag.AVENGE_COUNTER, 2)
        put(g, a, DRAGON_A)
        put(g, a, DRAGON_B)
        g.run_combat(a, b)
        self.assertEqual(trinket.get(GameTag.AVENGE_COUNTER, 0), 0)

    def test_plain_minion_fixture_stats(self):
        """测试夹具卡的关键词/种族前提（防 CardDB 数据漂移）。"""
        db = get_db()
        self.assertEqual(db.get(BEAST).race, Race.BEAST)
        self.assertEqual(db.get(DRAGON_A).race, Race.DRAGON)
        self.assertEqual(db.get(NAGA).race, Race.NAGA)
        self.assertEqual(db.get(ELEMENTAL).race, Race.ELEMENTAL)
        self.assertFalse(db.get(DUMMY).keywords & {"battlecry",
                                                   "deathrattle"})
