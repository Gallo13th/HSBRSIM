#!/usr/bin/env python
"""变异探针运行器（仅本地验证用，不入库/不 commit）。

对 `stats_gained` 原语、`batch_stats_gained` 与本轮纠错的副本/来源路径
施加 10 项定向变异，逐项跑相关测试文件，打印"存活（未转红）"用例列表。

用法: PYTHONPATH=. python tools/_mutation_probe_stats_gained.py

2026-09-20 对抗验证纠错记录:
  - 旧 M5（战后复原不抑制）**不再**是等价变异——真路径可达
    （Bewitched Ribbon + Tide Raiser 亡语战内施法 + BG34_Giant_064
    监听器）: 战内 `Buff(persist=True)` 不在战斗起始快照里 →
    `persist_buffs` 身份去重不跳过它 → 战后重放广播。新增回归
    `test_combat_incombat_persist_replay_does_not_rebroadcast` 杀死它。
  - 副本重放（`batch_trinkets32._restore_from_snapshot` /
    `batch_misc.SirensSong`）此前**无**抑制 → 新增 M8 探针。
  - `ActionQueue.resolve` 的来源跨动作泄漏 → 新增 M9 探针。
  - `_friendly` 酒馆/手牌边界 → 新增 M6 探针。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = [
    "hsrl2/tests/test_batch_stats_gained.py",
    "hsrl2/tests/test_batch_trinkets32.py",
]

MUTATIONS = [
    ("M1 生产点静默（add_buff 不广播 stats_gained）",
     "hsrl2/entity.py",
     '''            if not (_stats_gained_suppressed()
                    or getattr(self.game, "_restore_no_gain", False)):''',
     '''            if False:'''),
    ("M2 复制不抑制（copy_buffs_to 去掉抑制窗口）",
     "hsrl2/entity.py",
     "        with suppress_stats_gained():\n            for b in self._buffs:",
     "        if True:\n            for b in self._buffs:"),
    ("M3 载荷增量恒定（atk 传 1 而非 buff.atk）",
     "hsrl2/entity.py",
     "                    self.game, \"stats_gained\", minion=self,\n"
     "                    atk=buff.atk, health=buff.health,",
     "                    self.game, \"stats_gained\", minion=self,\n"
     "                    atk=1, health=buff.health,"),
    ("M4 删除类型过滤（BG21_013 的 Dragon 判定恒真）",
     "hsrl2/scripts/batches/batch_stats_gained.py",
     "            if minion.race not in (Race.DRAGON, Race.ALL):\n                return\n            g.run_actions(Buff(minion, health=amount))",
     "            g.run_actions(Buff(minion, health=amount))"),
    ("M5 战后复原不抑制（_restore_no_gain 恒 False）",
     "hsrl2/entity.py",
     "            if not (_stats_gained_suppressed()\n"
     "                    or getattr(self.game, \"_restore_no_gain\", False)):",
     "            if not (_stats_gained_suppressed()):"),
    ("M6 `_friendly` 去掉 Zone.PLAY 过滤（酒馆/手牌也计）",
     "hsrl2/scripts/batches/batch_stats_gained.py",
     "    return (ctrl is not None and ctrl is holder\n"
     "            and minion.zone == Zone.PLAY)",
     "    return (ctrl is not None and ctrl is holder)"),
    ("M7 Hunter of Gatherers 排除自身（旧错误实现）",
     "hsrl2/scripts/batches/batch_stats_gained.py",
     "            targets = [m for m in list(holder.board) if not m.dead]",
     "            targets = [m for m in list(holder.board)\n"
     "                       if m is not owner and not m.dead]"),
    ("M8 副本快照重放不抑制（batch_trinkets32）",
     "hsrl2/scripts/batches/batch_trinkets32.py",
     "    with suppress_stats_gained():\n        for buff in buffs:",
     "    if True:\n        for buff in buffs:"),
    ("M9 ActionQueue 不逐动作复位来源（跨动作泄漏）",
     "hsrl2/queue.py",
     "                # 逐动作复位: 未声明 source 的动作只继承**调用方作用域**\n"
     "                # （prev_source），不继承**上一个动作**的 source。\n"
     "                game._action_source = prev_source\n"
     "                if getattr(action, \"source\", None) is not None:",
     "                if getattr(action, \"source\", None) is not None:"),
    ("M10 SirensSong 手动复制循环不抑制",
     "hsrl2/scripts/batches/batch_misc.py",
     "            with entity.suppress_stats_gained():\n"
     "                for b in target.buffs:",
     "            if True:\n                for b in target.buffs:"),
]


def run_tests() -> tuple[int, list[str]]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *TESTS, "-q", "--no-header", "-rf"],
        cwd=ROOT, capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})
    failed = [ln.split(" ")[-1].strip()
              for ln in proc.stdout.splitlines() if ln.startswith("FAILED")]
    return proc.returncode, failed


def main() -> int:
    print("=== 基线（无变异） ===")
    code, failed = run_tests()
    print(f"exit={code} failed={len(failed)}")
    assert code == 0, "基线必须全绿"

    survivors = 0
    for name, rel, old, new in MUTATIONS:
        path = ROOT / rel
        original = path.read_text(encoding="utf-8")
        if old not in original:
            print(f"[{name}] !! 变异锚点未找到（{rel}）——探针失效")
            return 2
        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        try:
            code, failed = run_tests()
            print(f"\n=== {name} ===")
            print(f"exit={code} 转红用例={len(failed)}")
            for f in failed:
                print(f"  FAILED {f}")
            if code == 0:
                survivors += 1
                print("  !! 变异存活（测试未覆盖该路径）")
        finally:
            path.write_text(original, encoding="utf-8")
    print(f"\n=== 汇总: 有效变异 {len(MUTATIONS) - survivors}/"
          f"{len(MUTATIONS)} 全杀; 存活 {survivors} ===")
    return 0 if survivors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
