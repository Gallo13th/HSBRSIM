"""批次 goose_lucky_egg 行为层测试（3 张: Lucky Egg 基础/金色 + Goose
Portrait）。

全部断言走真实引擎路径:
  - 饰品: 真实 `game.grant_trinket`（数据链交付 + `on_bind` 接线）
  - 召唤计数: 真实 `game.summon`（广播 `SUMMON`）+ 真实 token 定义
    （`BG29_801t` / `BG29_801_Gt`）
  - 战吼/发现: 真实 `game.play_minion` → 真实 `PendingChoice.choose`
  - 变形: 真实 `Transform` Action（`hsrl2/actions/stats.py`）
  - 池记账: 真实 `game.minion_pool.acquire/release` 读数

覆盖口径: 每个行为方法都有**正效果断言**（钩子换 no-op 后必失败）+
负对照（非家族召唤 / 对手召唤 / 无候选落空 / 附魔不保留对照）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from hsrl2 import entity
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# ── 本批 id（CardDB 按名核实——禁止凭记忆写 id） ──
GOOSE_PORTRAIT = "BG30_MagicItem_777"
LUCKY_EGG = "BG30_104"
KABOOM_PAYLOAD = "BG_BOT_606"          # 非家族召唤物（负对照用）
LUCKY_EGG_G = "BG30_104_G"
SILVER_GOOSE = "BG29_801"
FLEDGLING = "BG29_801t"
FLEDGLING_G = "BG29_801_Gt"

_ALL_BATCH_IDS = (LUCKY_EGG, LUCKY_EGG_G, GOOSE_PORTRAIT)

_TEXT_SIGNATURES = {
    LUCKY_EGG: ("Battlecry: Discover a Golden Tier 3 minion to transform "
                "into."),
    LUCKY_EGG_G: ("Battlecry: Discover a Golden Tier 4 minion to transform "
                  "into."),
    GOOSE_PORTRAIT: ("Get a Silver Goose. After you summon 3 Silver "
                     "Fledglings, get a Lucky Egg."),
}

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def _norm(text: str) -> str:
    """卡面文本归一: 去 BBCode 标签、压平空白（卡面/数据换行差异）。"""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


def make_game(seed: int = 777) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def to_hand(game: Game, hero: Hero, card_id: str,
            golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    hero.hand.append(m)
    m.zone = Zone.HAND
    return m


def summon(game: Game, hero: Hero, card_id: str,
           golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def hand_ids(hero: Hero) -> list:
    return [m.card_id for m in hero.hand]


def board_ids(hero: Hero) -> list:
    return [m.card_id for m in hero.board]


class TestRegistryAndCardDefs(unittest.TestCase):
    """@engine-only 结构性: 注册表 / 数据链 / 池外前提 / num 纪律 /
    卡面文本漂移。"""

    def test_all_batch_ids_registered(self):
        missing = [cid for cid in _ALL_BATCH_IDS if cid not in REGISTRY]
        self.assertEqual(missing, [])

    def test_lucky_egg_data_chain(self):
        db = get_db()
        g = db.golden_version(db.get(LUCKY_EGG))
        self.assertIsNotNone(g)
        self.assertEqual(g.id, LUCKY_EGG_G)
        base = db.by_dbf(db.get(LUCKY_EGG_G).triple_base_id)
        self.assertIsNotNone(base)
        self.assertEqual(base.id, LUCKY_EGG)

    def test_goose_related_card_data_chain(self):
        db = get_db()
        rel = db.by_dbf(db.get(GOOSE_PORTRAIT).evolution_card_id)
        self.assertIsNotNone(rel)
        self.assertEqual(rel.id, SILVER_GOOSE)
        # 次生载荷数据链: 直接按 dbf 113130 查表（此前用
        # getattr(...,"evolution_card_id_2",None) or 113130 —— 该 tag
        # 未由 defs.py 导出, 恒走 fallback → 同义反复, 第三十七轮对抗
        # 验证指出）。
        secondary = db.by_dbf(113130)
        self.assertIsNotNone(secondary)
        self.assertEqual(secondary.id, LUCKY_EGG)

    def test_lucky_egg_is_out_of_pool(self):
        db = get_db()
        self.assertFalse(db.get(LUCKY_EGG).is_pool_minion)
        self.assertFalse(db.get(LUCKY_EGG_G).is_pool_minion)

    def test_num_discipline(self):
        """两卡与所有 token 均无模板参数（档位/阈值来自文本字面量）。"""
        db = get_db()
        for cid in (LUCKY_EGG, LUCKY_EGG_G, FLEDGLING, FLEDGLING_G):
            self.assertEqual(
                tuple(db.get(cid).num(i) for i in range(5)),
                (None, None, None, None, None), cid)
        self.assertEqual(db.get(GOOSE_PORTRAIT).num(0), 3)
        self.assertEqual(
            tuple(db.get(GOOSE_PORTRAIT).num(i) for i in range(1, 5)),
            (None, None, None, None))

    def test_fledgling_family_names_and_data_chain(self):
        db = get_db()
        self.assertEqual(db.get(FLEDGLING).name, "Silver Fledgling")
        self.assertEqual(db.get(FLEDGLING_G).name, "Silver Fledgling")
        base = db.by_dbf(db.get(FLEDGLING_G).triple_base_id)
        self.assertIsNotNone(base)
        self.assertEqual(base.id, FLEDGLING)

    def test_card_text_matches_carddef_and_docstring(self):
        db = get_db()
        import hsrl2.scripts.batches.batch_goose_lucky_egg as mod
        classes = {
            LUCKY_EGG: mod.LuckyEggScript,
            LUCKY_EGG_G: mod.LuckyEggGoldenScript,
            GOOSE_PORTRAIT: mod.GoosePortraitScript,
        }
        for cid, fragment in _TEXT_SIGNATURES.items():
            self.assertIn(fragment, _norm(db.get(cid).text), cid)
            doc = classes[cid].__doc__ or ""
            self.assertIn(fragment, _norm(doc), cid)


class TestGoosePortraitCounter(unittest.TestCase):
    """行为层: "After you summon 3 Silver Fledglings, get a Lucky Egg"。"""

    def _grant(self, seed: int = 777):
        game = make_game(seed)
        hero, opp = game.heroes
        trinket = game.grant_trinket(hero, GOOSE_PORTRAIT)
        self.assertIsNotNone(trinket)
        return game, hero, opp

    def test_grant_delivers_silver_goose(self):
        game, hero, _ = self._grant()
        self.assertEqual(hand_ids(hero), [SILVER_GOOSE])

    def test_third_fledgling_grants_lucky_egg(self):
        game, hero, _ = self._grant()
        summon(game, hero, FLEDGLING)
        summon(game, hero, FLEDGLING)
        self.assertNotIn(LUCKY_EGG, hand_ids(hero))
        summon(game, hero, FLEDGLING)
        self.assertEqual(hand_ids(hero).count(LUCKY_EGG), 1)

    def test_counter_resets_and_repeats(self):
        game, hero, _ = self._grant()
        for _ in range(3):
            summon(game, hero, FLEDGLING)
        self.assertEqual(hand_ids(hero).count(LUCKY_EGG), 1)
        for _ in range(3):
            summon(game, hero, FLEDGLING)
        self.assertEqual(hand_ids(hero).count(LUCKY_EGG), 2)

    def test_golden_fledgling_counts_in_same_family(self):
        """基础 2 只 + 金色 1 只 = 3 只 "Silver Fledglings"（同名家族）。"""
        game, hero, _ = self._grant()
        summon(game, hero, FLEDGLING)
        summon(game, hero, FLEDGLING)
        summon(game, hero, FLEDGLING_G)
        self.assertEqual(hand_ids(hero).count(LUCKY_EGG), 1)

    def test_non_fledgling_summon_not_counted(self):
        game, hero, _ = self._grant()
        # 三次**非家族**召唤（不同 id 以免三连合成）——只有 2 次时
        # 达不到阈值, 即使家族过滤被删除测试也不会失败（第三十七轮
        # 对抗验证指出的不敏感负对照）。
        summon(game, hero, SILVER_GOOSE)
        summon(game, hero, LUCKY_EGG)
        summon(game, hero, KABOOM_PAYLOAD)
        self.assertNotIn(LUCKY_EGG, hand_ids(hero))

    def test_opponent_fledgling_not_counted(self):
        game, hero, opp = self._grant()
        for _ in range(3):
            summon(game, opp, FLEDGLING)
        self.assertNotIn(LUCKY_EGG, hand_ids(hero))

    def test_counter_accumulates_across_turns(self):
        """文本无 "this turn" → 跨回合累积（2 + 1）。"""
        game, hero, _ = self._grant()
        summon(game, hero, FLEDGLING)
        summon(game, hero, FLEDGLING)
        game.end_recruit_phase()
        game.end_recruit_phase()
        summon(game, hero, FLEDGLING)
        self.assertEqual(hand_ids(hero).count(LUCKY_EGG), 1)


class TestLuckyEggDiscoverTransform(unittest.TestCase):
    """行为层: "Discover a Golden Tier N minion to transform into"。"""

    def _play(self, card_id: str, seed: int = 777):
        game = make_game(seed)
        hero = game.heroes[0]
        egg = to_hand(game, hero, card_id)
        ok = game.play_minion(hero, egg)
        self.assertTrue(ok)
        return game, hero, egg

    def test_base_creates_single_golden_discover_of_tier3(self):
        game, hero, egg = self._play(LUCKY_EGG)
        self.assertEqual(len(game.pending_choices), 1)
        pc = game.pending_choices[0]
        self.assertEqual(pc.kind, "discover_minion")
        self.assertTrue(pc.discover_golden)
        self.assertEqual(len(pc.options), 3)
        db = get_db()
        for cid in pc.options:
            self.assertEqual(db.get(cid).tech_level, 3, cid)
            self.assertTrue(db.get(cid).is_pool_minion, cid)
        self.assertIn(egg.card_id, board_ids(hero))

    def test_pick_transforms_into_golden_minion(self):
        game, hero, egg = self._play(LUCKY_EGG)
        pc = game.pending_choices.pop(0)
        pick = pc.options[0]
        idx = hero.board.index(egg)
        pc.choose(0)
        self.assertNotIn(egg, hero.board)
        new = hero.board[idx]
        self.assertEqual(new.card_id, get_db().golden_version(
            get_db().get(pick)).id)
        self.assertTrue(new.is_golden)
        self.assertTrue(new.has(GameTag.GILDED_NOT_TRIPLED))
        self.assertEqual(new.get(GameTag.TRIPLE_BASE_CARD_ID), pick)

    def test_pool_accounting_reserve_and_release(self):
        from hsrl2.actions.discover import _pool_candidates
        game = make_game(777)
        hero = game.heroes[0]
        before = {cid: game.minion_pool.available(cid)
                  for cid in _pool_candidates(game, None, 3, 3)}
        egg = to_hand(game, hero, LUCKY_EGG)
        self.assertTrue(game.play_minion(hero, egg))
        pc = game.pending_choices.pop(0)
        # 选择尚未结算时三个候选应已各预留 1 份（删除预留 → 此处失败）
        mid = {cid: game.minion_pool.available(cid) for cid in pc.options}
        for cid in pc.options:
            self.assertEqual(mid[cid], before[cid] - 1, f"未预留: {cid}")
        pick = pc.options[0]
        pc.choose(0)
        after = {cid: game.minion_pool.available(cid) for cid in pc.options}
        self.assertEqual(after[pick], before[pick] - 1,
                         "选中者未从池中扣除（预留缺失/泄漏）")
        for cid in pc.options:
            if cid != pick:
                # 未选者回池 → 相对**施放前**基线净变化为 0
                self.assertEqual(after[cid], before[cid], cid)

    def test_source_removed_before_resolve_releases_reserved_copy(self):
        """竞态守卫（ENGINE_BACKLOG #35 残余 i）: 选择建立后、结算前本体
        已离场（真实 `sell_minion`）→ `resolve` 释放预留的选中副本并
        落空，不凭空造实体（若守卫缺失，`Transform` 对离场目标 raise
        `GameStateError`，且选中副本泄漏在池外）。
        负对照: 同一 setup 不卖本体 → `test_pick_transforms_into_golden_
        minion` 断言确实变形。
        """
        from hsrl2.actions.discover import _pool_candidates
        game = make_game(777)
        hero = game.heroes[0]
        before = {cid: game.minion_pool.available(cid)
                  for cid in _pool_candidates(game, None, 3, 3)}
        egg = to_hand(game, hero, LUCKY_EGG)
        self.assertTrue(game.play_minion(hero, egg))
        pc = game.pending_choices.pop(0)
        # 真实离场路径: 结算前出售本体（招募期正常动作）
        self.assertTrue(game.sell_minion(hero, egg))
        self.assertNotIn(egg, hero.board)
        self.assertEqual(egg.zone, Zone.REMOVED)
        pc.choose(0)
        # 不凭空造实体（守卫落空）
        self.assertEqual(board_ids(hero), [])
        # 三个候选全部回池（选中者也被释放）→ 相对施放前基线净 0
        after = {cid: game.minion_pool.available(cid) for cid in pc.options}
        for cid in pc.options:
            self.assertEqual(after[cid], before[cid], f"未释放/泄漏: {cid}")

    def test_no_candidates_fizzles(self):
        game = make_game(777)
        hero = game.heroes[0]
        from hsrl2.actions.discover import _pool_candidates
        for cid in list(_pool_candidates(game, None, 3, 3)):
            while game.minion_pool.available(cid) > 0:
                if not game.minion_pool.acquire(cid):
                    break
        egg = to_hand(game, hero, LUCKY_EGG)
        self.assertTrue(game.play_minion(hero, egg))
        self.assertEqual(len(game.pending_choices), 0)
        self.assertIn(LUCKY_EGG, board_ids(hero))
        self.assertFalse(egg.is_golden)

    def test_enchantments_not_kept(self):
        """wiki Transform Notes: 变形不保留附魔 → keep_buffs=False。"""
        game = make_game(777)
        hero = game.heroes[0]
        egg = to_hand(game, hero, LUCKY_EGG)
        egg.add_buff(entity.Buff(atk=5, health=5))
        self.assertEqual(egg.atk, 7)
        self.assertTrue(game.play_minion(hero, egg))
        pc = game.pending_choices.pop(0)
        pick = pc.options[0]
        gdef = get_db().golden_version(get_db().get(pick))
        pc.choose(0)
        new = hero.board[0]
        self.assertEqual(new.card_id, gdef.id)
        self.assertEqual((new.atk, new.health), (gdef.atk, gdef.health))

    def test_opponent_hand_not_affected(self):
        game, hero, egg = self._play(LUCKY_EGG)
        opp = game.heroes[1]
        pc = game.pending_choices.pop(0)
        pc.choose(0)
        self.assertEqual(opp.hand, [])
        self.assertEqual(opp.board, [])

    def test_golden_egg_single_discover_of_tier4(self):
        """金色文本 = 档位升级（非 "twice"）→ 引擎的 2 次金色战吼触发
        只建立 1 个选择（实体级守卫）。"""
        # 必须用**真实金色实体**（create_minion(golden=True) 才置
        # GameTag.GOLDEN → 引擎触发 2 次战吼）; 此前用 LUCKY_EGG_G 卡面
        # 定义（golden=False）→ 只触发 1 次, 实体级守卫从未被覆盖
        # （第三十七轮对抗验证: 删除守卫仍 22/22 全绿）。三张幸运蛋合成
        # 即得此实体。
        game = make_game(777)
        hero = game.heroes[0]
        egg = to_hand(game, hero, LUCKY_EGG, golden=True)
        self.assertTrue(egg.is_golden, "前置: 必须是真实金色实体")
        self.assertTrue(game.play_minion(hero, egg))
        self.assertEqual(len(game.pending_choices), 1)
        pc = game.pending_choices[0]
        self.assertTrue(pc.discover_golden)
        db = get_db()
        for cid in pc.options:
            self.assertEqual(db.get(cid).tech_level, 4, cid)
        pick = pc.options[0]
        pc.choose(0)
        new = hero.board[0]
        self.assertEqual(new.card_id, db.golden_version(db.get(pick)).id)
        self.assertTrue(new.is_golden)

    def test_same_seed_same_options(self):
        g1, h1, _ = self._play(LUCKY_EGG, seed=4242)
        g2, h2, _ = self._play(LUCKY_EGG, seed=4242)
        self.assertEqual(g1.pending_choices[0].options,
                         g2.pending_choices[0].options)
