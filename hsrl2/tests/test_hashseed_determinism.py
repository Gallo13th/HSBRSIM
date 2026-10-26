"""F-36 / KNOWN-DET-1：引擎不得依赖 `str` 哈希顺序（跨进程确定性）。

**问题（env-upgrader 实测，2026-10-26）**
同 seed + 同动作序列，在 `PYTHONHASHSEED=0` 与 `=1` 两个进程中跑完整
rollout（seed=4001）前 129 步一致、之后 reward/存活数分裂。同进程两次
rollout 逐位一致，故既有确定性测试（同进程）测不到。

**根因（本文件锁定）**
`Bramble Tunneler BG36_331`（Rally: Get a random Choose One card）与
`Fandral's Fortune BG31_892`（Discover 3 Choose One options）的候选来自
`hsrl2/scripts/choose_one_authority.py::pool_choose_one_{minion,spell}_ids`，
返回类型是 **`frozenset[str]`**；其迭代顺序随 str 哈希种子变化。
两个脚本把该迭代结果直接作为 `game.rng.choice/sample` 的候选列表 →
同一 rng index 在不同进程落到不同卡（`bramble_hand` BG32_237 vs
BG36_332；`fandral_options` 第 3/4 项不同）→ 状态分裂。

**第 3 处（WS7 环境级 sweep 发现，2026-10-26）**
`SkyAdmiralRogersScript.on_gold_spent`（`hsrl2/scripts/batches/batch_misc.py`）
同样把 `hsrl2/constants.py::BOUNTY_SPELL_IDS`（**frozenset**）的迭代结果
直接作为 `rng.choice(label="rogers_bounty")` 候选 → 不同 hashseed 抽到
不同 Bounty（BG33_813 vs BG33_814）；环境级测试
`tests/test_env_determinism_hashseed.py` seed=2/3 稳定复现。

**修复**：三处候选列表在喂 RNG 前 `sorted()`（均匀随机语义不变，仅把
index→card 映射固定为字典序）。回归测试用**子进程 + 不同
PYTHONHASHSEED** 比引擎输出（同进程测试原理上无法覆盖该缺陷）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

#: 子进程探针：走两条真实脚本路径（不手写候选逻辑），输出确定性的卡 id。
_PROBE = r"""
import json
from pathlib import Path
import hsrl2.scripts  # noqa: F401
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts.batches.batch_rally2 import BrambleTunnelerScript
from hsrl2.scripts.batches.batch_unfreeze import FandralsFortuneScript

db = CardDB.load(Path("data"))


def new_game(seed):
    return Game([Hero("TEST_HS_A", "A"), Hero("TEST_HS_B", "B")],
                db, seed=seed)


out = {}
# 1) Bramble Tunneler rally：候选 = frozenset ∩ 池 → rng.choice
g = new_game(7)
h = g.heroes[0]
m = g.create_minion("BG36_331", controller=h)
g.summon(h, m)
BrambleTunnelerScript.rally(m, g, None)
out["bramble_hand"] = [e.card_id for e in h.hand]

# 2) Fandral's Fortune：spell 候选 = frozenset 迭代 → rng.sample
g2 = new_game(11)
h2 = g2.heroes[0]
sp = g2.create_spell("BG31_892", controller=h2)
FandralsFortuneScript.on_play(sp, g2, None)
out["fandral_options"] = (list(g2.pending_choices[0].options)
                          if g2.pending_choices else [])

# 3) Sky Admiral Rogers BG33_823：BOUNTY_SPELL_IDS frozenset → rng.choice
g3 = new_game(13)
h3 = g3.heroes[0]
h3.gold = 100
rogers = g3.create_minion("BG33_823", controller=h3)
g3.summon(h3, rogers)         # summon 触发脚本 on_summon 注册 GOLD_SPENT 监听
g3.spend_gold(h3, 9)          # 阈值 num(2)=9 → 发放 1 个 random Bounty
out["rogers_hand"] = [e.card_id for e in h3.hand]

print(json.dumps(out, sort_keys=True))
"""


def run_probe(hashseed: int) -> dict:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(hashseed)
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise AssertionError(
            f"probe (PYTHONHASHSEED={hashseed}) failed:\n{proc.stderr}")
    return json.loads(proc.stdout)


class TestHashSeedIndependentRng(unittest.TestCase):
    """同 seed 的引擎随机抽取不得随 PYTHONHASHSEED 变化。"""

    def test_choose_one_candidates_hashseed_independent(self):
        baseline = run_probe(0)
        for hs in (1, 2, 3):
            self.assertEqual(
                run_probe(hs), baseline,
                f"PYTHONHASHSEED={hs} 与 0 的引擎输出不同 → 候选列表顺序"
                f"依赖 str 哈希（F-36/KNOWN-DET-1）")

    def test_baseline_is_semantically_valid(self):
        out = run_probe(0)
        self.assertEqual(len(out["bramble_hand"]), 1,
                         "Bramble Tunneler 每次 rally 应获得 1 张卡")
        self.assertEqual(len(out["fandral_options"]), 3,
                         "Fandral's Fortune 应提供 3 个选项")
        self.assertEqual(len(set(out["fandral_options"])), 3,
                         "Fandral's Fortune 选项不得重复")
        self.assertEqual(len(out["rogers_hand"]), 1,
                         "Sky Admiral Rogers 花 9 金应获得 1 个 Bounty")
        from hsrl2.constants import BOUNTY_SPELL_IDS
        self.assertIn(out["rogers_hand"][0], BOUNTY_SPELL_IDS,
                      "Rogers 发放的必须是 Bounty 法术")


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
