"""动态脚本数据通道（官方 TAG_SCRIPT_DATA_NUM_1..5）语义测试。

背景：官方 enumID 1068–1072 = TAG_SCRIPT_DATA_NUM_1..5；引擎 `GameTag`
的 1068/1069/1070 是内部语义（LOCKED_IN_HAND/PERSIST_DOUBLE/
GILDED_NOT_TRIPLED），不能改值。本批新增**独立命名空间**
`hsrl2.tags.ScriptDataNum` + `Entity._script_data` 独立字典：

* 数值取官方真实 enumID（可对照日志/数据）；
* 存储与 `Entity.tags` 完全隔离（不污染内部 tag 语义）；
* 读取优先级：动态值 > CardDef 静态 `script_data_num_n`；
* 外部注入 API：`Game.set_entity_script_data` /
  `Game.inject_script_data_from_trace`（官方轨迹重建用）。

覆盖：枚举/映射、内部 tag 不变、通道读写、CardDef 默认值、
Eternal Knight 动态属性（默认簿记 + 官方注入计数 4 → 20/10）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.tags import (
    NUM_DYNAMIC_COUNT,
    OFFICIAL_TAG_TO_SCRIPT_DATA_NUM,
    SCRIPT_DATA_NUM_TO_OFFICIAL_TAG,
    GameTag,
    ScriptDataNum,
)

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_ETERNAL_KNIGHT = "BG25_008"          # 4/2: Has +4/+2 for each friendly
_ETERNAL_KNIGHT_GOLDEN = "BG25_008_G"  # 8/4

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 42) -> Game:
    return Game([Hero("TEST_HERO_A", "A"), Hero("TEST_HERO_B", "B")],
                get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero,
        golden: bool = False):
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m)
    return m


class TestScriptDataNamespace(unittest.TestCase):
    def test_official_enum_values(self):
        """数值 = 官方真实 enumID（CardDefs.Bacon.xml / key_enums 一致）。"""
        self.assertEqual(int(ScriptDataNum.NUM_1), 2)
        self.assertEqual(int(ScriptDataNum.NUM_2), 3)
        self.assertEqual(int(ScriptDataNum.NUM_3), 2889)
        self.assertEqual(int(ScriptDataNum.NUM_4), 2919)
        self.assertEqual(int(ScriptDataNum.NUM_5), 2920)
        self.assertEqual(NUM_DYNAMIC_COUNT, ScriptDataNum.NUM_3)

    def test_official_enum_names_from_authoritative_sources(self):
        """与官方数据/客户端枚举交叉核对（防 1068..1072 旧误判回流）。"""
        xml = ROOT / "reversed" / "hsdata_255130" / "CardDefs.Bacon.xml"
        if xml.exists():
            text = xml.read_text(encoding="utf-8", errors="replace")
            for member, name in (
                    (ScriptDataNum.NUM_1, "TAG_SCRIPT_DATA_NUM_1"),
                    (ScriptDataNum.NUM_2, "TAG_SCRIPT_DATA_NUM_2"),
                    (ScriptDataNum.NUM_3, "TAG_SCRIPT_DATA_NUM_3"),
                    (ScriptDataNum.NUM_4, "TAG_SCRIPT_DATA_NUM_4"),
                    (ScriptDataNum.NUM_5, "TAG_SCRIPT_DATA_NUM_5")):
                needle = f'enumID="{int(member)}" name="{name}"'
                self.assertIn(needle, text)

    def test_official_mapping_roundtrip(self):
        for member in ScriptDataNum:
            self.assertIs(OFFICIAL_TAG_TO_SCRIPT_DATA_NUM[int(member)], member)
            self.assertEqual(SCRIPT_DATA_NUM_TO_OFFICIAL_TAG[member],
                             int(member))
        self.assertEqual(set(OFFICIAL_TAG_TO_SCRIPT_DATA_NUM),
                         {2, 3, 2889, 2919, 2920})

    def test_internal_game_tags_unchanged(self):
        """**禁止**改动 1068/1069/1070 的内部语义（本批核心约束）。"""
        self.assertEqual(int(GameTag.LOCKED_IN_HAND), 1068)
        self.assertEqual(int(GameTag.PERSIST_DOUBLE), 1069)
        self.assertEqual(int(GameTag.GILDED_NOT_TRIPLED), 1070)

    def test_channel_does_not_collide_with_internal_tags(self):
        """动态脚本值不能落进 tags（否则 1068 会变成 LOCKED_IN_HAND）。"""
        game = make_game()
        m = put(game, _ETERNAL_KNIGHT, game.heroes[0])
        m.clear_script_data()
        m.set_script_data(1, 99)                 # 官方 NUM_1
        self.assertEqual(m.get_script_data(1), 99)
        self.assertFalse(m.has(GameTag.LOCKED_IN_HAND))
        self.assertNotIn(GameTag.LOCKED_IN_HAND, m.tags)
        # 内部 tag 语义独立：可以直接写 LOCKED_IN_HAND 且不影响脚本通道
        m.set(GameTag.LOCKED_IN_HAND, True)
        self.assertTrue(m.has(GameTag.LOCKED_IN_HAND))
        self.assertEqual(m.get_script_data(1), 99)

    def test_channel_roundtrip_and_validation(self):
        game = make_game()
        m = put(game, _ETERNAL_KNIGHT, game.heroes[0])
        m.set_script_data(2, 7)
        self.assertEqual(m.get_script_data(2), 7)
        self.assertEqual(m.script_data, {1: 4, 2: 7})   # NUM_1 由 CardDef 初始化
        m.set_script_data(2, None)                       # 清除 → 回落 CardDef
        self.assertIsNone(m.get_script_data(2))
        self.assertEqual(m.script_data_or_card(2), 2)
        with self.assertRaises(ValueError):
            m.set_script_data(6, 1)
        with self.assertRaises(ValueError):
            m.set_script_data(0, 1)
        m.clear_script_data()
        self.assertEqual(m.script_data, {})

    def test_carddef_static_defaults_in_channel(self):
        """创建实体时用 CardDef 静态 num 填充通道（Eternal Knight 4/2）。"""
        game = make_game()
        m = put(game, _ETERNAL_KNIGHT, game.heroes[0])
        self.assertEqual(m.get_script_data(1), 4)
        self.assertEqual(m.get_script_data(2), 2)
        self.assertIsNone(m.get_script_data(3))          # 动态计数默认无值
        golden = put(game, _ETERNAL_KNIGHT_GOLDEN, game.heroes[1],
                     golden=True)
        self.assertEqual(golden.get_script_data(1), 8)
        self.assertEqual(golden.get_script_data(2), 4)

    def test_inject_from_trace_keys(self):
        game = make_game()
        m = put(game, _ETERNAL_KNIGHT, game.heroes[0])
        game.inject_script_data_from_trace(
            m, {"ScriptDataNum1": 4, "ScriptDataNum3": 4})
        self.assertEqual(m.get_script_data(1), 4)
        self.assertEqual(m.get_script_data(3), 4)
        # 官方 enumID 形式的键（日志 tag=2 → NUM_1）也接受
        game.inject_script_data_from_trace(m, {"2": 6})
        self.assertEqual(m.get_script_data(1), 6)
        game.inject_script_data_from_trace(m, {"2889": 5})   # NUM_3
        self.assertEqual(m.get_script_data(3), 5)

    def test_set_entity_script_data_api(self):
        game = make_game()
        m = put(game, _ETERNAL_KNIGHT, game.heroes[0])
        game.set_entity_script_data(m, {3: 4})
        self.assertEqual(game.get_entity_script_data(m, 3), 4)


class TestEternalKnightDynamicState(unittest.TestCase):
    def test_default_bookkeeping_unchanged(self):
        """未注入时行为与旧实现完全一致（默认死亡簿记路径）。"""
        game = make_game()
        hero = game.heroes[0]
        m = put(game, _ETERNAL_KNIGHT, hero)
        self.assertEqual((m.atk, m.max_health), (4, 2))   # 0 死 → 回落基值
        hero.deaths_by_card_id = {_ETERNAL_KNIGHT: 2}
        self.assertEqual((m.atk, m.max_health), (12, 6))  # 4+2*4 / 2+2*2

    def test_injected_official_count_reproduces_stats(self):
        """官方轨迹：Eternal Knight 20/10（本局 4 只死亡）→ 注入 NUM_3=4。"""
        game = make_game()
        hero = game.heroes[0]
        m = put(game, _ETERNAL_KNIGHT, hero)
        game.set_entity_script_data(m, {3: 4})
        self.assertEqual((m.atk, m.max_health), (20, 10))

    def test_injected_golden_count(self):
        game = make_game()
        hero = game.heroes[0]
        m = put(game, _ETERNAL_KNIGHT_GOLDEN, hero, golden=True)
        game.set_entity_script_data(m, {3: 2})
        self.assertEqual((m.atk, m.max_health), (8 + 2 * 8, 4 + 2 * 4))

    def test_injected_count_combines_with_bookkeeping(self):
        """注入值 + 引擎簿记都计入（外部重建与自博弈互不破坏）。"""
        game = make_game()
        hero = game.heroes[0]
        m = put(game, _ETERNAL_KNIGHT, hero)
        hero.deaths_by_card_id = {_ETERNAL_KNIGHT: 1}
        game.set_entity_script_data(m, {3: 1})
        self.assertEqual((m.atk, m.max_health), (4 + 2 * 4, 2 + 2 * 2))


if __name__ == "__main__":
    unittest.main()
