"""F-37：Reborn（复生）受召唤上限 7 约束（不变量门禁捕获，2026-10-26）。

**现象**（`scripts/validate_env.py --games 20 --check-invariants` 捕获）：
`seed=5019: hero[P6]: board=8 > 上限 7`（turn 14 稳定状态）。最小链路：
Activate 摧毁己方带 Reborn 随从 → 死亡时亡语召唤填满棋盘（7）→ Reborn
分支仍 `hero.board.insert(...)` **不做 board_full 检查** → 8 只。

**参照证据**：AutoTavern `crates/taverngym/src/engine.rs::reborn` 通过
`self.summon(...)` 返回复生体——召唤失败（棋盘满）时复生体**不返回**；
其 `invariants.rs` 硬约束 `board <= 7`；官方「Reborn 是召唤、受棋盘上限」
（hearthstone.wiki.gg/wiki/Reborn）。

**修复**：`hsrl2/game.py::_process_death_inner` Reborn 分支插入前检查
`hero.board_full()`；满则复生体不返回（按普通死亡处理：进墓地、注销
监听器、招募期回池；不 fire `reborn`）。未满局面行为逐位不变。

本文件是**修复前应失败**的回归测试。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2 import constants as C
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.tags import GameTag

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
PLAIN = "BG33_140"          # River Skipper 1/1 白板（既有测试 fixture）

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 7) -> Game:
    import hsrl2.scripts  # noqa: F401
    return Game([Hero("TEST_REBORN_A", "A"), Hero("TEST_REBORN_B", "B")],
                get_db(), seed=seed)


def summon(game: Game, hero: Hero, *, reborn: bool = False,
           deathrattle_summon: bool = False):
    m = game.create_minion(PLAIN, controller=hero)
    if reborn:
        m.set(GameTag.REBORN, True)
    if deathrattle_summon:
        def _dr(source, g, ctx=None):
            token = g.create_minion(PLAIN, controller=hero)
            g.summon(hero, token)
            return None
        m.set_script_override("deathrattle", _dr)
    game.summon(hero, m)
    return m


class TestRebornBoardCap(unittest.TestCase):
    def setUp(self):
        self.game = make_game(seed=37)
        self.hero = self.game.heroes[0]
        self.reborn_events = []
        self.game.events.register(self._listener())

    def _listener(self):
        from hsrl2.events import Listener
        return Listener(
            event="reborn", owner=self.hero,
            callback=lambda game, **kw: self.reborn_events.append(kw["minion"]))

    def test_full_board_reborn_does_not_enter(self):
        """7 只满场：复生随从被摧毁 + 亡语召唤填满 → 复生体不得入场（≤7）。"""
        for _ in range(6):
            summon(self.game, self.hero)
        victim = summon(self.game, self.hero, reborn=True,
                        deathrattle_summon=True)
        self.assertEqual(len(self.hero.board), C.BOARD_SIZE)

        self.assertIs(self.game.destroy_minion(victim), True)

        self.assertLessEqual(
            len(self.hero.board), C.BOARD_SIZE,
            f"Reborn 插满盘导致 board={len(self.hero.board)} > "
            f"{C.BOARD_SIZE}（F-37）")
        self.assertNotIn(victim, self.hero.board,
                         "棋盘已满时复生体不得入场")
        self.assertEqual(self.reborn_events, [],
                         "复生体未返回时不得 fire reborn 事件")
        self.assertNotEqual(victim.zone.name, "PLAY")

    def test_under_cap_reborn_returns(self):
        """未满对照：复生体照常入场（默认行为不变）。"""
        for _ in range(4):
            summon(self.game, self.hero)
        victim = summon(self.game, self.hero, reborn=True,
                        deathrattle_summon=True)   # 5 只

        self.assertIs(self.game.destroy_minion(victim), True)

        self.assertIn(victim, self.hero.board,
                      "未满时 Reborn 必须照常返回")
        self.assertEqual(len(self.hero.board), 6,
                         "4 白板 + 亡语召唤 1 + 复生 1 = 6")
        self.assertEqual(self.reborn_events, [victim])

    def test_full_board_reborn_without_filler_still_returns(self):
        """7 只满场、但死亡未产生新召唤（空出 1 位）→ 复生照常入场。"""
        for _ in range(6):
            summon(self.game, self.hero)
        victim = summon(self.game, self.hero, reborn=True)   # 7 只
        self.assertEqual(len(self.hero.board), C.BOARD_SIZE)

        self.assertIs(self.game.destroy_minion(victim), True)

        self.assertIn(victim, self.hero.board,
                      "死亡让出板位后复生应正常回归（不误判满场）")
        self.assertEqual(len(self.hero.board), C.BOARD_SIZE)
        self.assertEqual(self.reborn_events, [victim])


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
