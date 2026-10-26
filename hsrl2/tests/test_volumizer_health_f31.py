"""F-31：Volumizer 光环下 minion 的 health 不得大于 max_health（不变量回归）。

**现象（env-upgrader 实测，2026-10-26）**
2 人局先 summon Red Volumizer（`BG34_170t` 3/1）再 summon Blue
（`BG34_170t2` 1/3，"your Volumizers have +3 Health this game"）：
Blue 的授予逻辑把**所有** Volumizer 的当前 HEALTH 抬 +3，但 Red 脚本
只实现 `atk` 动态钩子、没有 `health` 钩子 → Red `health=4 / max_health=1`，
违反「health ≤ max_health」结构性不变量（`hsbg/env/invariants.py` 可检出）。

**根因**
`hsrl2/scripts/batches/batch_37x_payloadgap1.py`:
- `_grant_volumizer_aura` 对 hero 级 `volumizer_aura_health` 增量 + 同步抬
  当前在场 Volumizer 的 HEALTH（与 ApplyRaceAura 可观测行为一致）；
- `BlueVolumizerScript` / `GreenVolumizerScript` 的 `health` 钩子读取该
  计数（`_static_total_health(source) + gain`）→ 最大血同步；
- `RedVolumizerScript` **缺 health 钩子** → 最大血不叠加。

**修复**：Red 补与 atk 对称的 health 钩子（"your Volumizers have +X Health"
是**全体** Volumizer 的光环，Red 也吃 Blue/Green 的 health 光环）。
默认无 Volumizer 时行为逐位不变。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

RED = "BG34_170t"          # 3/1
RED_G = "BG34_170t_G"      # 6/2
BLUE = "BG34_170t2"        # 1/3, +3 Health
BLUE_G = "BG34_170t2_G"    # 2/6, +6 Health
GREEN = "BG34_170t3"       # 3/3, +1/+1

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 7) -> Game:
    import hsrl2.scripts  # noqa: F401
    return Game([Hero("TEST_VOL_A", "A"), Hero("TEST_VOL_B", "B")],
                get_db(), seed=seed)


def summon(game: Game, hero: Hero, card_id: str):
    m = game.create_minion(card_id, controller=hero)
    assert game.summon(hero, m)
    return m


def summon_golden(game: Game, hero: Hero, base_id: str):
    """金色实体必须经 `golden=True` 创建（写 TRIPLE_BASE_CARD_ID，
    脚本按基础卡 id 绑定/解析数值——直接传 `_G` id 会被视为非池 token）。"""
    m = game.create_minion(base_id, controller=hero, golden=True)
    assert game.summon(hero, m)
    return m


class TestVolumizerHealthInvariant(unittest.TestCase):
    def test_red_health_after_blue_aura(self):
        """Red 先入场、Blue 后入场：Blue 的 +3 Health 光环必须也抬高
        Red 的最大血（当前血由 grant 同步抬升）→ health == max_health。"""
        game = make_game(seed=101)
        hero = game.heroes[0]
        red = summon(game, hero, RED)
        blue = summon(game, hero, BLUE)
        red_def = get_db().get(RED)
        # Red 卡面 3/1 + Blue 授予 +3 Health
        self.assertEqual(red.max_health, red_def.health + 3)
        self.assertEqual(red.health, red.max_health,
                         f"Red health={red.health} > max_health="
                         f"{red.max_health}（F-31 不变量违反）")
        # Blue 自身：卡面 1/3 + 自己授予的 +3
        blue_def = get_db().get(BLUE)
        self.assertEqual(blue.max_health, blue_def.health + 3)
        self.assertEqual(blue.health, blue.max_health)

    def test_red_health_after_green_aura(self):
        game = make_game(seed=103)
        hero = game.heroes[0]
        red = summon(game, hero, RED)
        summon(game, hero, GREEN)          # Green: +1/+1 to Volumizers
        red_def = get_db().get(RED)
        self.assertEqual(red.max_health, red_def.health + 1)
        self.assertEqual(red.health, red.max_health)

    def test_aura_accumulates(self):
        game = make_game(seed=107)
        hero = game.heroes[0]
        red = summon(game, hero, RED)
        summon(game, hero, BLUE)           # +3 Health
        summon(game, hero, GREEN)          # +1/+1
        red_def = get_db().get(RED)
        self.assertEqual(red.max_health, red_def.health + 3 + 1)
        self.assertEqual(red.health, red.max_health)

    def test_golden_blue_aura_applies_to_red(self):
        game = make_game(seed=109)
        hero = game.heroes[0]
        red = summon_golden(game, hero, RED)
        summon_golden(game, hero, BLUE)    # 金色 Blue: +6 Health
        red_def = get_db().get(RED_G)      # 金色 Red 卡面 6/2
        self.assertEqual(red.max_health, red_def.health + 6)
        self.assertEqual(red.health, red.max_health)

    def test_future_red_summon_after_aura(self):
        """光环已存在时后入场的 Red 满血入场（health == max_health）。"""
        game = make_game(seed=113)
        hero = game.heroes[0]
        summon(game, hero, BLUE)           # +3 Health 光环
        red = summon(game, hero, RED)
        red_def = get_db().get(RED)
        self.assertEqual(red.max_health, red_def.health + 3)
        self.assertEqual(red.health, red.max_health)

    def test_no_volumizer_no_aura_state(self):
        """默认无 Volumizer 路径逐位不变：hero 上无光环计数。"""
        game = make_game(seed=127)
        hero = game.heroes[0]
        summon(game, hero, "BG33_140")
        self.assertEqual(getattr(hero, "volumizer_aura_health", 0), 0)
        self.assertEqual(getattr(hero, "volumizer_aura_atk", 0), 0)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
