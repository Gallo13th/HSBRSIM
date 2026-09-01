# SOP: 语义测试 (Effect Testing)

> 适用: 为脚本卡写测试。测试验证的是 **Formal spec**（脚本 docstring
> 第 2 段），不是实现细节。作业范围: 仅 `hsrl2/tests/`。

## 1. 文件与命名

- 文件: `hsrl2/tests/test_cards_<主题>.py`（如 `test_cards_s14_activate.py`）
- 类: `Test<CardNameCamelCase>`
- 方法: `test_<行为>_<场景>`——读方法名即知验证哪条 spec

## 2. 测试模板

```python
import unittest
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import GameTag

_db = None
def get_db():
    global _db
    if _db is None:
        _db = CardDB.load("data")
    return _db

def make_game(seed=42):
    heroes = [Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")]
    return Game(heroes, get_db(), seed=seed)

class TestKelpKeeper(unittest.TestCase):
    """BG36_701 Kelp Keeper — Activate(1): Trigger a friendly minion's Battlecry."""

    def test_activate_triggers_battlecry(self):
        game = make_game()
        a = game.heroes[0]
        kelp = game.create_minion("BG36_701", controller=a)
        target = game.create_minion("BGS_018", controller=a)  # 任一带战吼的卡
        game.summon(a, kelp, 0)
        game.summon(a, target, 1)
        atk_before = target.atk
        gold_before = a.gold
        ok = game.use_activate(a, kelp)
        self.assertTrue(ok)
        self.assertEqual(a.gold, gold_before - 1)   # 扣 1 金
        # ... 验证战吼效果已触发

    def test_activate_once_per_turn(self):
        game = make_game()
        a = game.heroes[0]
        kelp = game.create_minion("BG36_701", controller=a)
        game.summon(a, kelp)
        a.gold = 10
        self.assertTrue(game.use_activate(a, kelp))
        self.assertFalse(game.use_activate(a, kelp))  # 同回合第二次
```

## 3. 每张卡的最低覆盖矩阵

| 卡类型 | 必测 |
|--------|------|
| 战吼 | 效果数值正确（**用 CardDef.num() 期望值**）/ 金色触发 2 次 / Brann 叠加 2 次 |
| 亡语 | 死亡触发 / 召唤物数量与位置 / 复生不吞亡语（先亡语后复生） |
| SoC | 战斗前触发 / 触发顺序在饰品之后英雄技能之前 |
| Avenge | 计数达阈值触发 / 未达标不触发 / 触发后计数清零 |
| Rally | 伤害结算**前**触发 / ctx 目标正确 |
| Activate | 扣金币 / 每回合 1 次 / 金币不足拒绝 |
| 死亡时效果 | 战斗内死亡 vs 招募期死亡（in_combat 语义） |
| 满场/满手 | 满场不召唤(MINION_OVERFLOW) / 满手排队等待 |
| 池交互 | Get/Discover 占池（available 减少）/ token 不占池 |

## 4. 断言数值时

**期望值从 CardDef 计算，不复制字面量**:

```python
d = get_db().get("BG26_523")          # Tichondrius
n0, n1 = d.num(0), d.num(1)           # 权威参数
self.assertEqual(buffed.atk, base + n0)
```

这样补丁数值变动时测试自动跟随，只有**语义**错误才会红。

## 5. 确定性

- 每个测试 `make_game(seed=<固定>)`
- 随机目标类效果: 用种子 + 重跑两次断言相同结果，或构造无随机场景
  （单一目标、满场等）
- 需要特定卡进酒馆: 直接 `game.create_minion` + 手动放入 zone，
  不要依赖池抽取随机性

## 6. 运行与验收

```bash
python -m pytest hsrl2/tests/test_cards_<主题>.py -v   # 新测试全绿
python -m pytest hsrl2/tests/ -q                       # 全量回归全绿
```

全量回归若红: **先判断是自己的测试错还是引擎错**。引擎错 → 停止作业，
报告 `ENGINE_BUG: <复现最小化用例>`；绝不修改引擎代码或 constants.py。

## 7. 作业单返回格式

```
测试完成: <n> cases 覆盖 <m> 张卡
- PASS: test_activate_triggers_battlecry (BG36_701)
- ENGINE_BUG: 复现 — <最小用例代码>
- SPEC_GAP: <卡的 spec 不明确的点>
pytest 全量: <末行输出>
```

## 8. 经验库（持续追加）

- 2026-08-21: `game.run_combat` 战后恢复快照——断言战斗内状态要用
  CombatResult 或 before/after 快照，不能战后读 board
- 2026-08-21: 手动执行单次攻击用 `CombatScheduler(game,a,b)._execute_attack(x,y)`
  可绕过完整循环做精确时序断言（圣盾/剧毒/AFTER_ATTACK 顺序）
- 2026-08-21: 死亡处理单随调用 `game._process_single_death(m)`（先把
  m.health 置 0）可隔离测复生/亡语顺序
- 2026-08-21: 脚本绑定已由 `game.create_minion/create_spell` 自动完成
  （按 card_id 查 REGISTRY，金色 id 独立命中）——测试 `put()` 辅助中的
  手动绑定已冗余但无害
- 2026-08-21: Targeted 效果（PendingChoice）测试模式: 断言
  `len(game.pending_choices)==1` 且 kind 正确 → `choice=pop(0);
  choice.choose(0)`（单候选时确定性）
- 2026-08-21: 断言英雄伤害触发链（Tichondrius）: 战斗路径用
  `game.run_combat` 后直接断言 buff 已落在复原棋盘上（伤害在恢复后施加）
