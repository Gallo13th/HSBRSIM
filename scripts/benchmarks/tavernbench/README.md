# TavernBench（vendored 副本）

本目录是 **AutoTavern 发布的 TavernBench** 的只读 vendored 副本，供 HSBRSIM
做「LLM/Agent 决策质量」标准评测。**上游文件原样未改**；HSBRSIM 侧使用说明见
[`docs/TAVERNBENCH.md`](../../docs/TAVERNBENCH.md)。

## 来源

| 项 | 值 |
|---|---|
| 上游仓库 | [MCG-NJU/AutoTavern](https://github.com/MCG-NJU/AutoTavern) |
| commit | `fb61201`（`TavernGym and TavernBench v1.0.0`） |
| 发布版本 | TavernBench v1.0.0（TavernGym 1.0.0） |
| 游戏版本 | patch **36.6.3**（client 36.6.3.253932） |
| 复制内容 | `AutoTavern/tavernbench/{data,results,tavernbench}` + `AutoTavern/LICENSE` + `AutoTavern/NOTICE` |
| 复制日期 | 2026-10-26 |
| 许可 | **MIT License**，Copyright (c) 2026 The AutoTavern Authors（见 [`LICENSE`](LICENSE)） |

> 第三方游戏内容（卡牌/英雄/机制名称与数值等）权利归 Blizzard Entertainment，
> 仅用于规则模拟与 AI 研究；详见 [`NOTICE`](NOTICE)。本副本不含 `.git`。

## 内容

```text
data/full/    全量 960 任务（prompts/labels/states）
data/eval/    论文固定评测集 368 任务（40 场景 / 8 类别）
results/      已发布答案：eval 12 系统（TavernAgent + 10 LLM + Jev）、tools 5 系统
tavernbench/  评分(score.py)/报告(report.py)/基线(chance.py)/模型 runner（原样）
expected/     golden 评分报告（AutoTavern 原仓库同一命令生成，用于 HSBRSIM --check 对拍）
MANIFEST.json 上游 commit/版本 + 36 个数据/答案/代码文件的 sha256/size（完整性校验）
```

## 使用

在 HSBRSIM 根目录（推荐，自动处理 PYTHONPATH）：

```bash
python3 scripts/run_tavernbench.py --check                 # 完整性 + 评分复现
python3 scripts/run_tavernbench.py                         # 已发布系统主表
python3 scripts/run_tavernbench.py --systems tavernagent,jev --json out.json
```

或在当前目录直接用上游命令评分（仅需 Python 标准库）：

```bash
python3 -m tavernbench.report --set data/eval --runs results/eval \
    --systems tavernagent,gpt-6-astra,claude-opus-5.5,jev
python3 -m tavernbench.score --set data/eval --answers results/eval/jev/answers.jsonl
```

**请勿修改本目录内上游文件**：需要更新时按
[`docs/TAVERNBENCH.md`](../../docs/TAVERNBENCH.md) §6 的重新 vendor 流程整体替换，
并同步 `MANIFEST.json` 与 `expected/eval_report.json`。

## 引用

```bibtex
@misc{ma2026build,
  title  = {Build, Don't Play: Self-Improving {LLM} Research Agents Develop a Hearthstone
            Battlegrounds {AI} That Rivals Top Players},
  author = {Ma, Changlian and Wang, Limin},
  year   = {2026},
  url    = {https://github.com/MCG-NJU/AutoTavern}
}
```

上游文档：`docs/TAVERNBENCH.md`（AutoTavern 仓库内）· `docs/TAVERNGYM.md` ·
`docs/CONTENT.md`。
