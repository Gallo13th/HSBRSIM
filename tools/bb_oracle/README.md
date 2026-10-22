# BobsBuddy 离线 oracle（最小可用）

本地调用 HDT 的 `BobsBuddy.dll`（.NET netstandard 库），输入双方战斗边界
状态，输出 n 次模拟的 win/tie/loss、平均伤害与耗时。**独立于 HDT
GameV2/实体数据库**；只依赖 HearthDb 静态卡库 + BobsBuddy 自身卡脚本。

## 依赖

- HDT 安装目录（默认 `%USERPROFILE%\AppData\Local\HearthstoneDeckTracker\app-1.59.3`）
  内 `BobsBuddy.dll`、`HearthDb.dll`、`BobsBuddy.Common.dll`；
- Python 3.13 + `pythonnet`（`python -m pip install pythonnet`）；
- 无需 HDT 运行、无需 dotnet 编译；pythonnet 直接加载 netstandard DLL。

如目录不同：`--dll-dir <dir>` 或环境变量 `BOBSBUDDY_DLL_DIR`。

## 用法

```powershell
cd C:\HSagent
# 1) 直接喂 JSON（schema 见 schema.json）
python tools/bb_oracle/bb_oracle.py --input test_input.json --iterations 3000 --threads 4
# 2) 从 official_combat_trace 转（自动映射 card_id/atk/health/golden/keywords/
#    ScriptDataNum tags；Enchantments 等未映射字段会进 ignored_fields）
python tools/bb_oracle/bb_oracle.py --trace runs/official_traces_hdt2/7210c2dcf328ffe3.json
# 3) 写文件
python tools/bb_oracle/bb_oracle.py --input x.json --out runs/bb_oracle/out.json
```

输出示例：

```json
{
  "ok": true,
  "win": 0.0,
  "tie": 0.497,
  "loss": 0.503,
  "av_damage": -0.99,
  "median_damage": -2.0,
  "simulation_count": 3000,
  "ignored_fields": [],
  "elapsed_s": 2.79,
  "sec_per_1000": 0.93
}
```

`ok=false` 表示 DLL/卡创建/模拟异常；`ignored_fields` 列出 BB 无法接收
或本 oracle 未映射的字段（Enchantments、trinkets、quests 等），差分时
应把对应样本记为 `unsupported`，而不是当作 BB 已覆盖。

## 最小 smoke（HDT 既有 BB 概率对照）

`official_traces_hdt2`（HDT BobsBuddy 日志自带 bb_rates）：

| trace | oracle（3000 次） | HDT bb_rates | 结论 |
|---|---|---|---|
| `7210c2dcf328ffe3` | tie .503 / loss .497 | tie .497 / loss .503 | 对齐（~0.6pp） |
| `eb66c6d07040bc4f` | win .504 / tie .496 | win .5 / tie .5 | 对齐（~0.4pp） |
| `62533201dc326471` | win .162 / tie .457 / loss .381 | win .753 / tie .186 / loss .061 | **不对齐**：trace 只给了 Enchantments，BB 未接收 → 覆盖缺口 |

性能：单线程 ~0.85–1.0 s / 1000 次；4 线程 ~0.27 s / 1000 次（本机）。

## 限制

- BB 的 `Enchantments`、trinkets、quests/objectives、secrets、hand、
  anomaly 等状态无法从当前 traceizer 的 `tags` 完整重建；本工具不猜。
- BB 的 `ScriptDataNum1..4` 可映射；`Minion` 的 dynamic 属性最终值可用
  `atk/health` 快照值覆盖，但**enchantment 身份/来源**无法表达。
- RNG 由 BB 内部 `Random` 驱动，无公开 seed；同输入多次运行是独立采样，
  不是官方 GAME_SEED 的逐事件复现。
- 仅建议作为**状态采样差分**的第三方 oracle；不承诺穷举状态空间。
