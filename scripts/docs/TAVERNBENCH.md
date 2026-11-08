# TavernBench 决策质量评测（HSBRSIM 集成指南）

> **定位**：TavernBench 是 AutoTavern 发布的 **LLM/Agent 决策质量基准**
> （960 任务 / 40 场景 / 8 类别，其中 368 任务为论文固定评测集），
> 自带评分代码、任务标签、模拟器状态与已发布模型答案。
> HSBRSIM 以 **只读 vendored** 方式引入（`benchmarks/tavernbench/`），
> 作为「LLM 在酒馆战棋静态局面上的决策质量」标准评测能力；
> 它**不是** HSBRSIM RL 策略的 self-play 评测替代品（边界见 §7）。
>
> 引入来源：`MCG-NJU/AutoTavern` commit `fb61201`
> (`TavernGym and TavernBench v1.0.0`)，游戏 patch 36.6.3，MIT 许可；
> 归因与文件哈希见 [`benchmarks/tavernbench/MANIFEST.json`](../benchmarks/tavernbench/MANIFEST.json)、
> [`LICENSE`](../benchmarks/tavernbench/LICENSE)、[`NOTICE`](../benchmarks/tavernbench/NOTICE)。

---

## 1. 仓库内位置

```text
benchmarks/tavernbench/              # vendored 基准（≈13 MB）
├── LICENSE / NOTICE                 # MIT 许可 + 第三方游戏内容权利声明（Blizzard）
├── MANIFEST.json                    # 来源 commit/版本、36 个数据/答案/代码文件的 sha256+size
├── README.md                        # 本目录说明（指向本文档）
├── data/
│   ├── full/                        # 全量 960 任务
│   │   ├── prompts.jsonl            # 960 条：模型看到的 system/prompt/answer_format
│   │   ├── labels.jsonl             # 960 条：答案 + 评分口径（scoring）
│   │   └── states.jsonl.gz          # 720 条：30 个对局场景的 taverngym 状态 JSON
│   └── eval/                        # 论文固定评测集 368 任务
│       ├── prompts.jsonl            # 368 条
│       ├── labels.jsonl             # 368 条
│       └── states.jsonl.gz          # 288 条（= 368 − 10 个规则场景的 80 题）
├── results/
│   ├── eval/<system>/answers.jsonl  # 已发布答案：TavernAgent + 10 个 LLM + Jev = 12 系统
│   └── tools/<model>/answers.jsonl  # 工具使用（tool-use）答案：5 系统 × 144 题
├── tavernbench/                     # 上游评分/报告/渲染/runner 代码（原样未改）
│   ├── score.py                     # 单题评分（8 种 scoring 口径）
│   ├── report.py                    # 「系统 × 场景/类别」汇总表
│   ├── chance.py                    # 随机选项基线
│   ├── engine.py / render.py        # taverngym 状态→动作/文本渲染（评分不依赖）
│   └── run_openai.py / run_claude.py / run_jev.py / run_tools.py  # 模型 runner
├── expected/eval_report.json        # golden：AutoTavern 原仓库同一命令生成的评分报告
└── .gitignore                       # 重新纳入 data/*.jsonl、results/**/answers.jsonl
```

**体积与文件数**：39 个文件、约 13 MB（data 9.6 MB / results 3.4 MB / 代码 124 KB）。
根 `.gitignore` 的 `*.jsonl` 会误伤基准数据，vendored 目录内的 `.gitignore`
用否定规则 `!data/**/*.jsonl`、`!results/**/answers.jsonl` 重新纳入；
`git status --untracked-files=all benchmarks/` 可确认全部数据/答案均会入库。

> 评分与 `report` 只需 Python 标准库；`taverngym` **不是** 评分依赖，
> 只有「在任务状态上执行/模拟动作」的工具评测（`run_tools.py`）与
> 状态合法性检查才需要它。

---

## 2. 数据集结构（960 / 368 / 40 / 8）

| 项 | 全量 `data/full` | 评测集 `data/eval` |
|---|---|---|
| 任务数 | 960 | 368 |
| 场景数 | 40 | 40 |
| 类别数 | 8 | 8 |
| 状态数（`states.jsonl.gz`） | 720（30 个对局场景） | 288（30 个对局场景） |
| 用途 | 训练/提示词研究/更多样本 | 论文主表口径，所有系统都答这一套 |

**评测集抽样规则**（`data/eval`）：37 个场景各取 8 题；D4（16）、N1（29）、N2（27）
三个对局场景整场景纳入 → 37×8 + 16+29+27 = 368。

**场景 → 类别映射**（40 场景 / 8 类别，来自 `prompts.jsonl` 的 `category` 字段）：

| 类别 | 场景 | 评测集任务数 | 考察内容（上游 README 口径） |
|---|---|---|---|
| combat | B1–B6（6） | 48 | 战斗结果/伤害/致命风险预测 |
| positioning | P1–P5（5） | 40 | 战团站位（盾、顺劈、亡语） |
| ordering | O1–O5（5） | 40 | 出牌/法术/触发顺序 |
| targets | T1–T5（5） | 40 | 法术/技能/随从目标选择 |
| selection | D1–D5（5） | 48（D4 为 16） | 英雄/饰品/发现/购买选择 |
| strategy | N1–N2（2） | 56（29+27） | 回合计划（升级/购买/刷新/存钱） |
| rules | R1–R7（7） | 56 | 具体动作的规则执行合法性 |
| economy | E1–E5（5） | 40 | 金币/购买/升级费用推理 |

- 每条 `prompts.jsonl` 记录字段：`id`、`category`、`scenario`、`system`
  （基准自带 system prompt）、`max_output_tokens`、`prompt`（规则摘要 + 玩家视角 +
  相关卡牌规则文本）、`answer_format`（要求的 JSON 形状）。
- 每条 `labels.jsonl` 记录字段：`id`、`answer`（标准答案）、`scoring`
  （评分口径，见 §4；`value_*` 口径另有 `values`/`tol`）。
- `states.jsonl.gz` 每行 `{"id", "state"}`（部分含 `states` 一次性多选项），
  `state` 是 `taverngym.Game.from_json` 可加载的状态 JSON，仅 30 个对局场景有；
  10 个规则执行场景（`R1,R3–R7,E1,E2,E4,E5`）无需状态。
- **评分划分**：`report.py` 把上述 10 个场景记为 `rule`（规则分），其余 30 个记为
  `play`（对局分）；两分数都是「场景等权均值」，不是题目等权均值。

---

## 3. 复现命令

### 3.1 HSBRSIM 集成入口（推荐）

在 **HSBRSIM 根目录** 运行，无需 `cd`、无需手动设 `PYTHONPATH`：

```bash
# 校验数据完整性 + 复现已发布答案评分（不跑模型、不联网；约 0.7s）
python3 scripts/run_tavernbench.py --check
# → 26 项检查全 PASS（目录/许可/36 文件哈希/960·368·40·8/状态/答案覆盖/
#   labels 自评分/12 个已发布系统 + chance 的逐场景评分复现）

# 论文主表（12 个已发布系统，默认全部）
python3 scripts/run_tavernbench.py

# 只算指定系统
python3 scripts/run_tavernbench.py --systems tavernagent,gpt-6-astra,claude-opus-5.5,jev

# 换数据集/答案目录（相对 benchmarks/tavernbench/，也可传绝对路径）
python3 scripts/run_tavernbench.py --set data/full --runs results/tools

# 输出 JSON（与上游 `tavernbench.report --out` 格式完全一致，便于程序消费）
python3 scripts/run_tavernbench.py --json runs/tavernbench/eval_report.json

# 可选：与本机 AutoTavern 原仓库现场对拍（同一命令，JSON 应逐项一致）
python3 scripts/run_tavernbench.py --check --upstream /path/to/AutoTavern
```

`--check` 的检查项（26 项）分四组：

| 分组 | 内容 |
|---|---|
| 来源/许可 | 目录结构、评分代码、data/results/golden/MANIFEST 存在、MIT LICENSE、NOTICE 归因 |
| 数据完整性 | 960 任务（full）/368 任务（eval）、40 场景、8 类别、720/288 状态、评测集抽样规则、labels 与 prompts 一一对应、8 种评分口径分布、状态覆盖 30 个对局场景、id 唯一 |
| 答案覆盖 | 12 个 eval 系统 × 368（gemini-3.8-flash 缺 `P2-000`，按上游口径计错）、5 个 tool-use 系统 × 144、无 error 行 |
| 评分可复现 | 用 vendored `tavernbench.score` 验证 exact/set 标签自评分满分；用 `tavernbench.report` 重算 chance + 12 系统的全部场景分，与 golden `expected/eval_report.json` 逐项对拍（float 容差 1e-9） |

### 3.2 复现已发布主表（上游原始命令）

```bash
cd benchmarks/tavernbench
python3 -m tavernbench.report --set data/eval --runs results/eval \
    --systems tavernagent,claude-opus-5.5,claude-sonnet-5.5,gpt-6-astra,gpt-6.1-sol,\
gemini-3.8-flash,grok-4.7,glm-5.3,kimi-k2.6,intern-s2-preview,deepseek-v4.1-flash,jev
```

HSBRSIM 侧实测（2026-10-26，`python3 scripts/run_tavernbench.py`，与本机
AutoTavern 原仓库 `fb61201` 输出逐字节一致）：

```text
system                       play  rule    1v1 comba posit order targe selec strat econo  out_tok trunc
chance                       0.22  0.05   0.33  0.13  0.20  0.21  0.25  0.30  0.25  0.12        0 0.00
tavernagent                  0.91  1.00   1.00  1.00  0.97  1.00  0.97  0.64  0.75  1.00        0 0.00
claude-opus-5.5              0.52  0.93   1.00  0.67  0.33  0.60  0.53  0.41  0.38  0.50      310 0.00
claude-sonnet-5.5            0.53  0.85   1.00  0.58  0.45  0.68  0.53  0.39  0.29  0.50      346 0.00
gpt-6-astra                  0.63  0.95   1.00  0.75  0.55  0.72  0.55  0.50  0.54  0.75      186 0.00
gpt-6.1-sol                  0.46  0.56   1.00  0.50  0.42  0.47  0.28  0.55  0.43  0.38      305 0.00
gemini-3.8-flash             0.44  0.90   1.00  0.52  0.33  0.33  0.47  0.41  0.43  0.62     2772 0.16
grok-4.7                     0.22  0.79   1.00  0.29  0.00  0.05  0.20  0.38  0.37  0.12     6625 0.48
glm-5.3                      0.40  0.65   0.62  0.54  0.20  0.40  0.38  0.41  0.34  0.38      605 0.04
kimi-k2.6                    0.28  0.56   0.62  0.31  0.07  0.23  0.38  0.36  0.27  0.25     1577 0.23
intern-s2-preview            0.32  0.54   0.50  0.31  0.12  0.33  0.40  0.44  0.34  0.12        9 0.00
deepseek-v4.1-flash          0.26  0.29   0.75  0.29  0.17  0.15  0.33  0.25  0.19  0.38       21 0.00
jev                          0.37  0.35   0.75  0.56  0.25  0.20  0.45  0.40  0.17  0.12      369 0.00
```

表头各列：`play`/`rule` = 30/10 个场景的等权均值；类别列（`1v1`=rules、`comba`=combat…）
= 该类场景均值的平均，**只统计 play 场景**；`out_tok` = 平均输出 token 数；
`trunc` = 截断/超预算比例。`chance` 行是随机选项基线（由 `labels`+`prompts` 计算，
不是真实系统）。

### 3.3 实测证据（2026-10-26，macOS 15.2 / Python 3.12.2 / pytest 7.4.4）

| 命令 | 结果 |
|---|---|
| `python3 scripts/run_tavernbench.py --check` | exit 0，`CHECK PASSED: 26/26`，0.7s |
| `python3 scripts/run_tavernbench.py --check --upstream <AutoTavern>` | exit 0，`CHECK PASSED: 27/27`（含「与原仓库对拍」） |
| `AUTOTAVERN_ROOT=<AutoTavern> python3 -m pytest tests/test_tavernbench.py -q` | 11 passed |
| `python3 -m pytest tests/test_tavernbench.py -q` | 10 passed, 1 skipped（无原仓库 checkout 时跳过可选对拍） |
| 与上游拷贝一致性 | `diff -r benchmarks/tavernbench/{data,results,tavernbench} <AutoTavern>/tavernbench/...` 无差异 |

---

## 4. 评分口径（`tavernbench/score.py` + `report.py`）

每题输出 `(correct 0/1, graded score∈[0,1])`；8 种口径：

| `scoring` | 判定（correct） | 分数（graded） | 评测集题数 |
|---|---|---|---|
| `exact` | 与标签相等；字符串忽略大小写；列表比较需完全相等 | 0/1 | 232 |
| `brier` | 概率三元组（win/tie/loss）归一化后，最可能项与标签一致且 Brier ≤ 0.1 | `1 − Brier/2` | 16 |
| `numeric_rel` | `|a−b| ≤ max(1, tol·|b|)`，`tol` 默认 0.25 | `1 − min(1, 相对误差)` | 8 |
| `numeric_abs` | `|a−b| ≤ tol`，`tol` 默认 0.1 | `1 − min(1, 绝对误差)` | 8 |
| `set` | 集合（忽略顺序/大小写）完全相等 | 0/1 | 8 |
| `value_map` | 答案是 `label["values"]` 的键；`v ≥ best − tol` 记为 correct | `v / best` | 8 |
| `value_map_str` | 同上（键为规范化字符串，去空格/逗号、大写） | `v / best` | 40 |
| `value_json` | 同上（键为 `json.dumps(answer)` 的 JSON 值键） | `v / best` | 48 |

- `value_*` 是模拟器**采样噪声**下的取值映射：`label["values"]` 每个候选的模拟
  胜率/伤害/得分，`tol` 容忍噪声（上游用 TavernGym 模拟标注）。
- **作废规则**（`score.py`）：`error`/`is_error`、`finish_reason ∈
  {length, incomplete, content_filter, tool_calls, timeout, error}`、
  非结构化答案输出超过 4096 token 预算 → 直接 0 分；`response` 解析不出
  JSON、或 JSON 无法按口径解释 → 0 分。
- **汇总规则**（`report.py`）：
  - 每个场景先算场景正确率；`S*` 双向策略场景（本发布集未包含）用 balanced accuracy；
  - `category` 分 = 该类别内 **play 场景**正确率的均值（规则场景不进类别列）；
  - `play` = 30 个对局场景等权均值；`rule_score` = 10 个规则场景等权均值；
  - 缺答案按错处理（`gemini-3.8-flash` 缺 `P2-000`，与上游一致）；
  - `real_time_play`（JSON 里的成本字段）= 只计 ≤1.0s 的答案，其余计错，
    是论文「实时分」口径；普通表格不展示。
- 单文件版评分（不汇总）：`python3 -m tavernbench.score --set data/eval
  --answers results/eval/jev/answers.jsonl [--json]`（在 `benchmarks/tavernbench/` 下）。

---

## 5. 如何提交自定义模型答案

### 5.1 格式

每个系统一个目录：`<runs>/<system_name>/answers.jsonl`，一行一个任务（最终记录，
重复 id 以最后一行为准）：

```json
{"id": "B2-000", "model": "my-model", "response": "{\"answer\": \"win\"}",
 "input_tokens": 1832, "output_tokens": 12, "latency_s": 0.8,
 "finish_reason": "stop", "error": null}
```

必需字段：`id`（任务 id，取自对应 `prompts.jsonl`）、`response`（模型原始文本，
评分器会从文本中提取第一个 JSON 对象）。可选字段：`model`、`error`/`is_error`
（非空直接判 0）、`finish_reason`、`input_tokens`/`output_tokens`、`latency_s`；
Jev 这类结构化答案用 `mode: "structured"`（不受 4096 token 文本预算约束）。

```bash
# 答案放好后用 HSBRSIM 入口评分（system 名 = 目录名）
python3 scripts/run_tavernbench.py --runs path/to/my_runs --systems my-model
```

### 5.2 用上游 runner 生成答案

在 `benchmarks/tavernbench/` 下（runner 依赖 `openai`/`httpx`/`requests`，
评分本身不需要；可 `pip install openai httpx requests`）：

```bash
python3 -m tavernbench.run_openai --set data/eval --model MODEL \
    --out answers/MODEL/answers.jsonl --base-url https://api.example.com/v1 \
    --key-env API_KEY          # 任何 OpenAI 兼容网关均可（含内部 aigateway）
python3 -m tavernbench.run_claude --set data/eval --model sonnet --out answers/sonnet/answers.jsonl
python3 -m tavernbench.run_jev --set data/full --out answers/jev/answers.jsonl
python3 -m tavernbench.run_tools --set data/eval --model MODEL --out answers/MODEL/answers.jsonl
```

runner 都是**可续跑**的（已答 id 跳过）；`run_tools` 需要本机安装 `taverngym`
（HSBRSIM 默认不装该依赖）。答案目录名即系统名，最后用 §5.1 的方式评分。

---

## 6. 数据完整性与维护

`--check` 的基线数字（改动数据即会红）：

| 检查 | 基线 |
|---|---|
| `data/full` prompts/labels/states | 960 / 960 / 720 |
| `data/eval` prompts/labels/states | 368 / 368 / 288 |
| 场景 / 类别 | 40 / 8 |
| 评测集场景大小 | 37×8 + D4=16 + N1=29 + N2=27 |
| `MANIFEST.json` 文件哈希 | 36 个文件 sha256+size 一致 |
| 已发布答案 | 12 eval 系统 × 368（gemini 367）+ 5 tools 系统 × 144 |
| exact/set 标签自评分 | 240 个全部满分 |
| 评分复现 | chance + 12 系统 × 40 场景逐项等于 golden |

**升级/重新 vendor 流程**（AutoTavern 发布新版本时）：

1. 记录上游 commit/tag/patch，`cp -R AutoTavern/tavernbench/{data,results,tavernbench}
   benchmarks/tavernbench/`（**不要**复制 `.git`、`__pycache__`），同步 LICENSE/NOTICE；
2. 在 AutoTavern 原仓库按 §3.2 命令重新生成 golden，替换
   `benchmarks/tavernbench/expected/eval_report.json`（`--out` 直接写该文件）；
3. 重新生成 `MANIFEST.json`：更新 `upstream` 元信息、golden 的 sha256、
   全部文件 sha256/size（脚本见 git 历史或按 `--check` 报错逐项更新）；
4. `python3 scripts/run_tavernbench.py --check` 全绿后，同步更新本节基线数字
   与 §2 统计（若任务数变化）。

**已知限制**（上游声明，非本仓库缺陷）：

- 标签由论文时期的 TavernGym 计算，当前模拟器含后续规则修复，**重算标签可能有
  极少数差异**（评分本身不重算，直接用 `labels.jsonl`）；
- `gemini-3.8-flash` 的 `P2-000` 无答案，按“缺答案=错”处理；
- item generators（题目生成器）未随 AutoTavern 发布；`run_tools` 需要 taverngym；
- 数据不含模型权重/训练代码（TavernAgent 权重未发布）。

---

## 7. 与 HSBRSIM RL 策略评测的边界（重要）

| 维度 | TavernBench（本目录） | HSBRSIM 自主策略评测 |
|---|---|---|
| 被测对象 | LLM / Agent 的**单步或短程决策** | 本项目 RL 策略（MCTS+PPO） |
| 评测形态 | 静态局面 + 固定 prompt，逐题打分（0/1 + 分级分） | 完整 8 人对局 self-play / 对脚本对手，统计名次/胜率 |
| 数据/版本 | taverngym 状态 JSON，patch 36.6.3 | hsbg_engine，数据基线 37.0.0.255790 |
| 动作空间 | 基准把答案**文本化**（选项/整数/序列） | 动态候选动作 + 实体 token 观测（与 TavernGym 245 动作不同） |
| 入口 | `scripts/run_tavernbench.py` / `tavernbench.report` | `scripts/c0_gate.py`、`scripts/eval_*.py`、`hsbg/eval/**` |
| 用途 | 「决策质量」外部基准、LLM baseline、提示词/工具使用实验 | 训练进展门禁、self-play 强度、与基线对比 |

**明确边界**：

1. **不可直接互相换算**：TavernBench 的 `play`/`rule` 分数与 HSBRSIM 的
   self-play 名次/胜率不是同一口径；不要用 TavernBench 分数替代本项目的训练/策略评测结论
   （评测口径见 `docs/TRAINING_RUNTIME_HANDOFF.md` §5 与 `hsbg/eval/**`）。
2. **不是 RL reward/训练信号**：它是离线静态题库的 LLM 评测，不提供环境
   rollout、奖励或梯度；`benchmarks/tavernbench` 只读，不被 `hsbg_engine`、
   `hsbg/**` 代码路径引用。
3. **HSBRSIM 的 RL 策略不能直接接入**：现有策略网络输出 hsbg_engine 37 动作/观测空间
   的 logits，TavernBench 要求「把 taverngym 状态渲染成 prompt 并产出
   JSON 答案」；两者版本（37.0.0 vs 36.6.3）与动作空间都不同，接入需自写
   适配器（不在本次范围内）。当前 vendored `tavernbench.engine/render` 保留
   上游实现，仅作参考。
4. **可以怎么用**：a) 作为外部 LLM/Agent 决策质量对照（例如未来给 HSBRSIM 的
   LLM 包装层/工具调用策略做标准评测）；b) 用已发布答案做评分器/提示词的
   离线回归；c) 研究「LLM 决策 → RL 策略」知识迁移时的独立质量探针。
5. **评分可独立运行**：不依赖 HSBRSIM 引擎、GPU、网络或任何模型；
   `--check` 可在 CI/无模型环境复现已发布分数（仅需 Python 标准库）。
