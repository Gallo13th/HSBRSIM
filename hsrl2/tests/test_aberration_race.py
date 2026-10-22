"""37.0（build 255130）新种族 ABERRATION=126 回归测试。

覆盖升级 S3 结构修复的三层契约：
  1. 枚举层: `hsrl2.tags.Race.ABERRATION == 126`、DBF 映射、
     `STANDARD_RACES` / `RACE_SET_ALL` / `race_set` 展开；
  2. 数据层: CardDB 正确映射 card_race=126（禁止静默降级为 NONE）、
     池内 ABERRATION 随从可枚举；
  3. 引擎层: 只激活 ABERRATION 时酒馆刷新只出 ABERRATION 随从；
     ALL 型（Amalgam）拥有 ABERRATION 身份；
  4. fail-loud: 未知 card_race / race_tags 必须抛错（不得静默丢）。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.defs import CardDef
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import (DBF_RACE_TO_ENUM, RACE_SET_ALL, STANDARD_RACES,
                        Race, race_set)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 7) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")], get_db(),
             seed=seed)
    g.start_game()
    return g


class TestAberrationEnum(unittest.TestCase):
    def test_enum_value_matches_official_tag(self):
        # 官方 TAG_RACE.ABERRATION = 126（reversed/tag_diff.json
        # other_enums.race.official_only）
        self.assertEqual(int(Race.ABERRATION), 126)
        self.assertEqual(DBF_RACE_TO_ENUM[126], Race.ABERRATION)

    def test_standard_races_includes_aberration(self):
        self.assertIn(Race.ABERRATION, STANDARD_RACES)
        self.assertEqual(len(STANDARD_RACES), 11)     # 37.0 起 11 族
        self.assertIn(Race.ABERRATION, RACE_SET_ALL)
        self.assertEqual(race_set(Race.ALL), RACE_SET_ALL)

    def test_race_set_primary_and_extra(self):
        self.assertEqual(race_set(Race.ABERRATION),
                         frozenset({Race.ABERRATION}))
        self.assertEqual(race_set(Race.NONE, (Race.ABERRATION,)),
                         frozenset({Race.ABERRATION}))


class TestAberrationData(unittest.TestCase):
    def test_pool_minions_mapped(self):
        db = get_db()
        pool = db.pool_minions()
        aber = [d for d in pool if d.race == Race.ABERRATION]
        self.assertGreaterEqual(len(aber), 20)        # 255130 官方 25 张
        # 未静默降级：数据里的 card_race=126 必须全部映射到 ABERRATION
        raw = json.loads((DATA_DIR / "bg_cards.json").read_text(
            encoding="utf-8"))
        ids_126 = {c["id"] for c in raw if c.get("card_race") == 126}
        self.assertTrue(ids_126)
        for cid in ids_126:
            self.assertEqual(db.get(cid).race, Race.ABERRATION, cid)

    def test_known_37_0_cards(self):
        db = get_db()
        for cid in ("BG36_097", "BG36_098", "BG36_300", "BGFYM_005"):
            d = db.get(cid)
            self.assertIsNotNone(d, cid)
            self.assertEqual(d.race, Race.ABERRATION, cid)
            self.assertEqual(d.races, frozenset({Race.ABERRATION}), cid)

    def test_reclassified_old_cards(self):
        """37.0 官方把 4 张旧卡改为 ABERRATION（含金色变体）。"""
        db = get_db()
        for cid in ("BG27_002", "BG23_015", "BG_EX1_564"):
            self.assertEqual(db.get(cid).race, Race.ABERRATION, cid)

    def test_all_race_amalgam_has_aberration_identity(self):
        g = make_game()
        a = g.heroes[0]
        amalgam = g.create_minion("BG36_640", controller=a)   # ALL 型
        self.assertTrue(amalgam.has_race(Race.ABERRATION))
        self.assertIn(Race.ABERRATION, amalgam.races)

    def test_pool_candidates_under_aberration_only(self):
        g = make_game()
        pool = g.minion_pool
        pool.active_races = {Race.ABERRATION}
        cands = pool.candidates(7, 1)
        self.assertTrue(cands)
        db = get_db()
        # 无种族随从永远可用（RULES §2.4）；其余候选必须带 ABERRATION 身份
        for cid in cands:
            d = db.get(cid)
            self.assertTrue(d.race == Race.NONE
                            or Race.ABERRATION in d.races, cid)

    def test_tavern_refresh_with_aberration_guarantee(self):
        """ABERRATION 池内随从可正常出现在酒馆（per-slot race guarantee）。"""
        g = make_game()
        a = g.heroes[0]
        a._tavern_race_guarantee = (Race.ABERRATION, 2)
        g.refresh_tavern(a, free=True)
        drawn = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(drawn)
        for m in drawn[:2]:
            self.assertTrue(m.has_race(Race.ABERRATION), m.card_id)


class TestUnknownRaceFailsLoud(unittest.TestCase):
    def test_unknown_card_race_raises(self):
        with self.assertRaises(ValueError) as ctx:
            CardDef.from_json({"id": "TEST_UNKNOWN_RACE", "card_race": 999})
        self.assertIn("card_race", str(ctx.exception))

    def test_unknown_race_tag_raises(self):
        with self.assertRaises(ValueError) as ctx:
            CardDef.from_json({"id": "TEST_UNKNOWN_TAG",
                               "race_tags": ["NOT_A_RACE"]})
        self.assertIn("race_tags", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
