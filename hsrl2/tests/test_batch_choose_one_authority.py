"""Choose One 权威判定（G-C5）测试 —— 数据标志漂移 + 统一实现。

被测模块: `hsrl2/scripts/choose_one_authority.py`
覆盖:
  1. 判定式: 标题格式 "Choose One -"（dash 可落在 </b> 外）∧
     非 Spellcraft 宿主；
  2. 全库统计: 权威 36 / 数据文本兜底 44 / 9 误报 / 3 漏报（37.0 基线）;
  3. 池候选域: 7 随从 + 4 法术（"random Choose One card" 语义）;
  4. 三处调用方回归（batch_choose_one / batch_rally2 / batch_unfreeze）
     与权威判定同源（不再有硬编码清单）。
"""

from __future__ import annotations

import unittest

from hsrl2.db import CardDB
from hsrl2.scripts.choose_one_authority import (
    choose_one_data_flag_ids,
    choose_one_flag_drift,
    choose_one_ids,
    is_choose_one_def,
    is_choose_one_entity,
    pool_choose_one_minion_ids,
    pool_choose_one_spell_ids,
)

_ROOTS = __file__.rsplit("hsrl2", 1)[0]
DATA_DIR = _ROOTS + "data"

# 数据标志 vs 权威判定差异（37.0 基线）:
# - 提及型误报 9（标题正则也不命中）
# - Spellcraft 宿主 2（标题命中但按判定式排除——文案属于被授予法术）
_MENTION_FALSE_POSITIVES = frozenset({
    "BG31_323", "BG31_323_G",       # Turbo Hogrider（触发条件提及）
    "BG31_327", "BG31_327_G",       # Thorned Trailblazer（双效光环）
    "BG31_329", "BG31_329_G",       # Boar Gamer（随机获取提及）
    "BG31_892",                     # Fandral's Fortune（发现/双效提及）
    "BG36_331", "BG36_331_G",       # Bramble Tunneler（随机获取提及）
})
_SPELLCRAFT_HOSTS = frozenset({"BG30_117", "BG30_117_G"})
_FLAG_NOT_AUTHORITATIVE = _MENTION_FALSE_POSITIVES | _SPELLCRAFT_HOSTS

# 3 漏报（真抉择卡但文本兜底未标记）
_MISSES = frozenset({
    "BG30_117t",     # Escape Eruption（Spellcraft 法术侧不跑检测）
    "BG30_117_Gt",   # Escape Eruption 金色
    "BG31_893",      # Gem Day（令牌）
})

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


class TestChooseOneAuthority(unittest.TestCase):
    """判定式与数据漂移。"""

    def test_full_db_counts(self):
        db = get_db()
        self.assertEqual(len(choose_one_ids(db)), 36)
        self.assertEqual(len(choose_one_data_flag_ids(db)), 44)

    def test_flag_drift_exact(self):
        db = get_db()
        false_positives, misses = choose_one_flag_drift(db)
        self.assertEqual(set(false_positives), set(_FLAG_NOT_AUTHORITATIVE))
        self.assertEqual(set(misses), set(_MISSES))

    def test_title_regex_accepts_bold_dash_outside(self):
        # BG31_842 布局: "<b>Choose One</b> - Give ..."（dash 在 </b> 外）
        self.assertTrue(is_choose_one_def(get_db().get("BG31_842")))
        self.assertTrue(is_choose_one_def(get_db().get("BG31_884")))

    def test_spellcraft_host_excluded_but_spell_included(self):
        db = get_db()
        # 宿主随从: 文案属于被授予的法术 → 不是抉择卡
        self.assertFalse(is_choose_one_def(db.get("BG30_117")))
        self.assertFalse(is_choose_one_def(db.get("BG30_117_G")))
        # 被授予的法术本体才是抉择卡（漏报修复）
        self.assertTrue(is_choose_one_def(db.get("BG30_117t")))
        self.assertTrue(is_choose_one_def(db.get("BG30_117_Gt")))

    def test_mention_type_cards_negative(self):
        db = get_db()
        for cid in sorted(_MENTION_FALSE_POSITIVES):
            self.assertFalse(is_choose_one_def(db.get(cid)), cid)

    def test_entity_helper_uses_card_db(self):
        game = type("G", (), {"db": get_db()})()

        class _E:
            def __init__(self, cid):
                self.card_id = cid

        self.assertTrue(is_choose_one_entity(game, _E("BG31_320")))
        self.assertFalse(is_choose_one_entity(game, _E("BG31_329")))
        self.assertFalse(is_choose_one_entity(game, _E("BG31_892")))
        self.assertFalse(is_choose_one_entity(game, None))
        self.assertFalse(is_choose_one_entity(
            game, type("E", (), {"card_id": "NOT_A_CARD"})()))


class TestPoolCandidateDomain(unittest.TestCase):
    """"random Choose One card" 候选域（池内真抉择卡）。"""

    def test_pool_sets(self):
        db = get_db()
        self.assertEqual(
            set(pool_choose_one_minion_ids(db)),
            {"BG27_084", "BG30_123", "BG31_320", "BG32_237",
             "BG36_330", "BG36_332", "BG36_341"})
        self.assertEqual(
            set(pool_choose_one_spell_ids(db)),
            {"BG31_880", "BG31_881", "BG31_886", "BG31_890"})

    def test_candidate_sets_are_subset_of_authority(self):
        db = get_db()
        auth = choose_one_ids(db)
        self.assertTrue(pool_choose_one_minion_ids(db) <= auth)
        self.assertTrue(pool_choose_one_spell_ids(db) <= auth)

    def test_no_hardcoded_lists_left_in_callers(self):
        """三处旧硬编码清单已删除——调用方只 import 权威函数。"""
        import inspect
        from hsrl2.scripts.batches import (
            batch_choose_one, batch_rally2, batch_unfreeze)
        for mod in (batch_choose_one, batch_rally2, batch_unfreeze):
            self.assertFalse(
                hasattr(mod, "CHOOSE_ONE_MINION_IDS"), mod.__name__)
            self.assertFalse(
                hasattr(mod, "CHOOSE_ONE_SPELL_IDS"), mod.__name__)
        # batch_rally2 / batch_unfreeze 的候选域直接来自权威函数
        for mod in (batch_rally2, batch_unfreeze):
            src = inspect.getsource(mod)
            self.assertIn("pool_choose_one_minion_ids", src, mod.__name__)
            self.assertIn("pool_choose_one_spell_ids", src, mod.__name__)

    def test_choose_one_candidate_scripts_implement_protocol(self):
        """池内真抉择卡：注册脚本必须实现选择协议分支（引擎
        `choose_options` 或既有自建协议的 on_play/battlecry 钩子——
        防"注册但无效果"的第三态）。"""
        from hsrl2.scripts.registry import REGISTRY
        db = get_db()
        for cid in sorted(pool_choose_one_minion_ids(db)
                          | pool_choose_one_spell_ids(db)):
            script = REGISTRY.get(cid)
            self.assertIsNotNone(script, cid)
            self.assertTrue(
                getattr(script, "choose_options", None)
                or getattr(script, "battlecry", None)
                or getattr(script, "on_play", None), cid)


if __name__ == "__main__":
    unittest.main()
