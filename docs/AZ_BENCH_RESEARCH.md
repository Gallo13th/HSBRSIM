# AlphaZero 不完全信息搜索：TavernBench × hsbg_engine Bench 调研（v0.1）

> **任务**：task-1（bench 研究员，只读调研）。**唯一写文件**：本文件。
> **时间**：2026-10-26 晚；截止 2026-10-27 07:00（Asia/Shanghai）。
> **证据标注约定**（全文统一）：
> - **【实测-本机】**：本工作目录（Windows，`C:\HSagent`，Python 3.13）上可复现的只读检查；
> - **【实测-dev】**：远程开发机 `bicourse-glt`（`~/projects/HSBRSIM`，Python 3.14.9，
>   `hsbg_engine` release 构建）上由本次调研实际运行得到（命令见 §7）；
> - **【文档】**：仓库内既有文档的既有结论（不重跑，不视为本次实测）；
> - **【静态】**：只读源码/数据的静态阅读结论。
>
> **本地限制（重要）**：本机 **没有** Rust 工具链（`cargo`/`rustc` 不在 PATH），
> `rust/target` 不存在，`C:\Python313\python.exe` 无法 `import hsbg_engine`/`taverngym`。
> 因此**契约/数据结构**用本机静态分析 + JSON 解析确认；**所有引擎行为实测**都在
> dev 机 `bicourse-glt` 的既有 release 构建上完成（未安装任何新依赖，未改代码/数据）。

---

## 0. TL;DR（给 Lead 的 9 条结论）

1. **TavernBench 状态可直接被 `hsbg_engine` 加载**（关键前提已实测）：
   `benchmarks/tavernbench/data/{eval,full}/states.jsonl.gz` 里全部 288/720 条状态行的
   `card_table` 指纹 = `10833040883741191591`（`0x9656b149b0ad6da7`），与 dev 机
   `hsbg_engine`（37.0.0.255130 数据，3983 张卡）**逐位一致**；`pool.counts` 长度也同为
   3983。【实测-dev】
2. **加载结果**：eval 288 行中 280 行含 `state` 字段，**280/280 全部 `Game.from_json` 成功**；
   其余 8 行是 D1 的「多候选状态」行（`states` 数组，每个候选状态也能加载）。full 720 行中
   696 行含 `state`，**696/696 成功**，24 行为 D1 多状态行。全部落在 `recruit` 阶段，
   turn 4–14。【实测-dev】
3. **标签可被引擎精确复现**（这是 bench 的黄金地基）：对 17 个「可执行动作」场景
   （P1–P5/O1–O5/T1–T5/E3/D3/D5），按 `states.jsonl.gz` 里的 `options[i].ops` / `perms[i]`
   回放动作、再用 `debug combat_preview` 评估下一场战斗：
   - **eval 104 任务：top-1 与标签 104/104 一致**，逐选项胜率与标签 `values` 的 MAE
     ≤ 0.0057（多数 ≤ 2e-4，n=1024 采样）；
   - **full 312 任务 / 3624 个候选选项：top-1 312/312 一致，0 个非法动作**，MAE ≤ 0.0049；
   - 成本：3624 选项 × n=1024 = 371 万场战斗，单进程 **81.06 s（≈45.8k combat/s，
     44.7 option/s）**。【实测-dev，§7.3】
4. **战斗预测类标签同样可复现**：B1（先手）8/8；B2/R2（win/tie/loss）8/8 且与标签 `meta`
   逐项一致（MAE=0）；B3/B6（Brier）brier≈1e-4/2e-4、argmax 8/8 与 7/8；B4（期望受伤）
   相对误差 1.7%；B5（致死概率）绝对误差 1.7%。【实测-dev】
5. **hsbg_engine 提供两套现成搜索入口**（`hsbg_engine._core`）：
   - `mcts_search(game, seat, simulations, c_puct, temperature, eval_fn, seed,
     dirichlet_alpha, dirichlet_epsilon, rollout)` → `(pi f32[245], action, root_value, visits)`；
   - `turn_search(game, seat, states_budget, samples_per_action, combat_samples,
     max_steps_per_turn, seed, aggregate)` → `(scores f32[245], action, best_score, n_states, n_combats)`。
   两者都接受**已加载的 `Game` 对象**，因此 TavernBench 状态可以直接作为搜索根。【静态+实测-dev】
6. **但两个现成搜索的目标函数与 TavernBench 标签不一致**（已实测到反例）：`turn_search` 优化
   「本回合候选状态之间两两胜率」，而 TavernBench 的 17 个可执行场景标签是「对**指定对手**
   的下一场胜率」。实测 T5（8 题）`turn_search` top-1 0/8、平均 regret 0.490；
   `mcts_search(rollout=True, sims=4)` 0/8；反例 T5-000：`turn_search` 选 `Sell(5)`（action 21，
   自评 score=1.0），但其结果对真实对手胜率 0.0，而标签最优是 0.8213。T2 则 8/8。
   → bench 必须把「搜索目标」与「标签目标」分开报告，不能直接拿 turn_search 当答题器。【实测-dev】
7. **可用于「搜索质量」验证的场景是 30 个有状态场景，分三层**（§3）：
   - 17 个**可执行动作题**（144 eval / 432 full 任务）：标签 = 离散候选下一场胜率的 argmax，
     可精确复现 → 最适合验证「搜索是否找到标签最优动作」；
   - 7 个**战斗预测题** B1–B6/R2（56 eval 任务）：标签是数值/概率 → 适合验证**搜索价值校准**
     （不是动作策略）；
   - 5 个**长程规划题** N1–N2/D4/D1/D2（88 eval 任务）：标签来自 128 次整局模拟的
     `mean_place` → 只能整局 rollout 做排序一致性，成本高且对手 bot 口径不同。
   另外 10 个无状态规则题（R1/R3–R7/E1/E2/E4/E5，80 eval 任务）**不能**做引擎 bench。
8. **动作/观测契约**：`N_ACTIONS=245`、`OBS_FLOATS=3227`、`OBS_CARDS=124`、
   `N_CARDS=3984`（含 0 空位）——与 AT/TavernBench（`tavernbench/engine.py` 的
   `A_BUY=8, A_SELL=16, A_ACTIVATE=23, A_CHOOSE=30, A_PLAY=46, A_MAGNETIZE=126, A_MOVE=196`,
   `N_POS=8, N_BOARD=7`）逐位一致。【实测-dev + 静态】
9. **复现成本与缺口**：本地不能构建引擎，bench 命令应在 dev 机执行（§7）；仓库**没有**
   RL 训练集/模型 checkpoint/搜索 run 产物（`runs/` 只有 webui 输出）、**没有** TavernAgent
   权重（`docs/TAVERNBENCH.md` §6）、**没有** item generator；`hsbg/az/`（队友在写）是
   不完全信息搜索原型，可作为被测系统接入（§4.3）。

---

## 1. TavernBench 数据盘点

### 1.1 目录与文件（vendored 只读副本）

来源与许可见 `benchmarks/tavernbench/README.md:9-20`：AutoTavern `fb61201`
（TavernGym/TavernBench v1.0.0，patch 36.6.3，MIT）。HSBRSIM 侧说明见
`docs/TAVERNBENCH.md`。

```text
benchmarks/tavernbench/                       （≈13 MB，上游文件未改）
├── MANIFEST.json                             sha256/size + 上游 commit
├── data/full/{prompts,labels}.jsonl 960 行   states.jsonl.gz 720 行（30 个对局场景）
├── data/eval/{prompts,labels}.jsonl 368 行   states.jsonl.gz 288 行
├── expected/eval_report.json                 golden：chance + 12 系统 × 40 场景评分
├── results/eval/<12 systems>/answers.jsonl   已发布 LLM/TavernAgent/Jev 答案
├── results/tools/<5 systems>/answers.jsonl   工具使用（tool-use）答案 5×144
└── tavernbench/{score,report,chance,engine,render,run_*.py}   上游代码原样
```

### 1.2 计数与抽样规则（全部本地核验，与 `docs/TAVERNBENCH.md:59-93` 一致）

| 项 | full | eval |
|---|---:|---:|
| 任务（prompts/labels） | 960 | 368 |
| 场景 / 类别 | 40 / 8 | 40 / 8 |
| 状态行（states） | 720 | 288 |
| 任务带状态 | 720（30 场景） | 288（30 场景） |
| 无状态任务 | 240（10 场景） | 80（10 场景） |

- eval 抽样：37 个场景各 8 题，D4=16、N1=29、N2=27 整场景纳入 → 37×8+16+29+27=368
  （`docs/TAVERNBENCH.md:67-68`）。
- 8 类 = combat / positioning / ordering / targets / selection / strategy / rules / economy；
  场景→类别映射见 `docs/TAVERNBENCH.md:70-82`。
- `states.jsonl.gz` 每行 `{"id", "state"} + 场景附加字段`（见 §1.4），
  `state` 是 `taverngym.Game.from_json` 可加载的完整 8 人游戏状态 JSON。
- **无状态的 10 个场景** = `report.py:22` 的 `RULE` 集合：
  `R1,R3,R4,R5,R6,R7,E1,E2,E4,E5`（规则执行/费用推理，纯文本题）。

### 1.3 场景总表（eval n / 有状态 / 标签口径 / bench 分层）

「Chance / TavernAgent / 最佳 LLM」来自 `expected/eval_report.json` 的逐场景 acc
（chance 行由 `chance.py` 的随机选项基线生成，不是真实系统）：
**TavernAgent 是「用引擎工具」的系统，在 17 个可执行动作场景上平均 0.986**，
即本 bench 的「工具/搜索天花板参照」；最佳 LLM 是 10 个 LLM 中该场景的最高值。

| 场景 | 类别 | 有状态 | eval/full n | 标签口径 | bench 层 | chance | TavernAgent | 最佳 LLM |
|---|---|:--:|---|---|---|---:|---:|---:|
| B1 | combat | ✓ | 8/24 | 先手方（you/opp/random） | B 预测 | 0.33 | 1.00 | 1.00 |
| B2 | combat | ✓ | 8/24 | win/tie/loss（单结果） | B 预测 | 0.33 | 1.00 | 1.00 |
| B3 | combat | ✓ | 8/24 | win/tie/loss 概率（Brier） | B 预测 | 0.00 | 1.00 | 0.75 |
| B4 | combat | ✓ | 8/24 | 期望受伤（num rel） | B 预测 | 0.00 | 1.00 | 0.88 |
| B5 | combat | ✓ | 8/24 | 致死概率（num abs） | B 预测 | 0.00 | 1.00 | 0.88 |
| B6 | combat | ✓ | 8/24 | win/tie/loss 概率（Brier） | B 预测 | 0.12 | 1.00 | 0.38 |
| P1–P5 | positioning | ✓ | 8/24 ×5 | 5 个排列中胜率最高（`perms`） | A 动作 | 0.20 | 1.00* | 0.50–0.62 |
| O1–O5 | ordering | ✓ | 8/24 ×5 | 动作顺序最优（`options`） | A 动作 | 0.17–0.24 | 1.00 | 0.50–0.88 |
| T1–T5 | targets | ✓ | 8/24 ×5 | 目标/位置最优（`options`） | A 动作 | 0.18–0.30 | 0.88–1.00 | 0.38–1.00 |
| E3 | economy | ✓ | 8/24 | 购买组合/顺序最优（`options`，最多 157 项） | A 动作 | 0.12 | 1.00 | 0.75 |
| D3 | selection | ✓ | 8/24 | 发现选项最优（`options`） | A 动作 | 0.33 | 1.00 | 0.75 |
| D5 | selection | ✓ | 8/24 | 手牌选择最优（`options`） | A 动作 | 0.33 | 1.00 | 0.88 |
| D2 | selection | ✓ | 8/24 | 饰品选择（`map`: Choose 30–33） | C 长程 | 0.25 | 0.12 | 0.50 |
| D4 | selection | ✓ | 16/16 | 发现选项（`map`: Choose，`seat` 字段） | C 长程 | 0.33 | 0.81 | 0.56 |
| D1 | selection | ✓ | 8/24 | 英雄选择（4 个候选状态） | C 长程 | 0.25 | 0.25 | 0.50 |
| N1/N2 | strategy | ✓ | 29+27 整场景 | 4 个计划首动作（`map`: action→字母） | C 长程 | 0.25 | 0.83/0.67 | 0.52/0.56 |
| R1 | rules | ✗ | 8/24 | 合法动作集合 | D 文本 | 0.00 | 1.00 | 1.00 |
| R2 | rules | ✓ | 8/24 | 战斗结果 | B 预测 | 0.33 | 1.00 | 1.00 |
| R3–R7 | rules | ✗ | 8/24 ×5 | 数值/属性列表 | D 文本 | 0.00 | 1.00 | 0.75–1.00 |
| E1/E2/E4/E5 | economy | ✗ | 8/24 ×4 | 金币/费用/是否可（整数/是否） | D 文本 | 0.00/0.50 | 1.00 | 0.88–1.00 |

\* P4 的 TavernAgent 是 0.88；其余 P 为 1.00。chance 与最佳 LLM 的逐场景值取自
`expected/eval_report.json`（可复算，见 §7.1）。

**17 个「可执行动作」场景 = P1–P5, O1–O5, T1–T5, E3, D3, D5**，共 **144 eval / 432 full
任务**；它们正是上游 `run_tools.py:35` 的 `TOOL_SCENARIOS`（工具可测子集）。
其子集均值：chance **0.227**；TavernAgent **0.986**；最佳单个 LLM（gpt-6-astra）**0.625**；
claude-sonnet-5.5 0.549；Jev 0.333；deepseek-v4.1-flash 0.236。【实测-本机，读 golden】

### 1.4 `states.jsonl.gz` 结构与「场景附加字段」（bench 的关键）

每行 `{"id": ..., "state": <JSON 字符串>}`，另按场景携带以下字段之一/多个
（全部在 eval/full 上枚举核对）：

| 字段 | 出现场景 | 语义 / 用法 |
|---|---|---|
| `state` | 28 个场景（274/280 行） | 完整 8 人 Game JSON；`Game.from_json(state)` 恢复 |
| `states` | D1（8/24 行） | **4 个候选状态 JSON 字符串**（4 个英雄各一局）；标签答案 0..3 = 选第几个 |
| `options` | E3,O1–O5,T1–T5,D3,D5 | 候选动作方案列表：`[{"answer": <选项键>, "ops": [op,...]}]`；`ops` 是 `engine.py apply_ops` 的动作描述（buy/play/sell/spell/spell_target/play_target/activate_target/power_target/magnetize/choose/play_last） |
| `perms` + `answers` | P1–P5 | `perms[i]` = 第 i 个选项的战团排列（原战团下标的排列），`answers[i]` = 该排列对应字母（A–E） |
| `map` | D2,D4,N1,N2 | 键→答案映射：D2/D4 是 `"30"/"31"…`（=`Choose(k)` 动作下标）→ 选项号；N1/N2 是 `"11"/"1"/"0"/"3"`（**245 动作下标**）→ 计划字母 A–D |
| `seat` | D4,N1,N2 | 该题视角座位；**不一定是 0**（实测 D4=5、N1=0、N2=6） |
| `health` + `cap` | B5 | 致死概率题的当前血量与伤害上限（12/15 等） |
| `answers`（独立） | D1 | `[0,1,2,3]`，与 `states` 下标对应 |

实例（来自实际数据）：

```text
N1-000 map = {"11": "A", "1": "B", "0": "C", "3": "D"}
  → 245 动作：11=Buy(3)（买酒馆3号位 Strike Oil）=A；1=Refresh=B；0=EndTurn=C；3=Upgrade=D
D2-000 map = {"30": 0, "31": 1, "32": 2, "33": 3}
  → 状态里 me.pending.kind="trinket"，me.pending.options 4 个饰品；legal=[30,31,32,33]（Choose(0..3)）
E3-000 options[16] = {"answer": [1,2], "ops": [{"kind":"buy","eid":46,"play":true},
                     {"kind":"buy","eid":47,"play":true}]}   # 键 = "1,2"
T5-000 options 共 7 项，每项 ops = [{"kind":"sell","eid":33+i},{"kind":"play","eid":40}]
```

**陷阱**：D2 的状态在第 0 座、但 D4 的视角座位是 `seat=5`；直接对 `seat=0` 调
`legal_mask(0)` 会得到空 mask（实测 D4-000 `legal=[]`）。bench 必须以
`entry.get("seat", 0)` 作为被控座位。

### 1.5 评分口径（`tavernbench/score.py` + `report.py` + `chance.py`）

8 种 `scoring`（`score.py:1-10, 74-128`；分布：eval 232 exact / 48 value_json /
40 value_map_str / 16 brier / 8 set / 8 value_map / 8 numeric_rel / 8 numeric_abs）：

| 口径 | correct | graded | 备注 |
|---|---|---|---|
| `exact` | 与标签相等（字符串忽略大小写；列表全等） | 0/1 | 占多数 |
| `brier` | 归一化后最可能项=标签且 Brier≤0.1 | `1−Brier/2` | B3/B6 |
| `numeric_rel` | `|a−b|≤max(1, 0.25·|b|)` | `1−min(1,relerr)` | B4、T1?（T1 是 exact） |
| `numeric_abs` | `|a−b|≤tol`（默认 0.1） | `1−min(1,Δ)` | B5（tol 0.15） |
| `set` | 集合相等 | 0/1 | R1 |
| `value_map` | 答案是 `values` 的键，`v≥best−tol` | `v/best` | E3（键如 "1,2"） |
| `value_map_str` | 同上（键去空格/逗号、大写） | `v/best` | O1–O5（键如 "BDCA"） |
| `value_json` | 同上（键 = `json.dumps(answer)`） | `v/best` | T2–T5/D3/D5 |

- **作废规则**（`score.py:46-60`）：`error`/`is_error`、`finish_reason ∈
  {length,incomplete,content_filter,tool_calls,timeout,error}`、非结构化答案超 4096
  token 预算 → 0 分；解析不出 JSON → 0 分。
- **汇总**（`report.py:22-33, 87-97`）：`RULE` 集合 10 个场景记 rule 分，其余 30 个记 play 分；
  分 = **场景等权均值**（不是题等权）；类别列只含 play 场景；S* 双向题用 balanced acc（本发布集
  不含 S*）；缺答案=错；`real_time_play` 只计 ≤1.0 s 的答案（`report.py:33, 60-67`）。
- **chance 基线**（`chance.py:17-47`）：choice 题 1/k；Brier 用均匀三元组；value_* 用
  「落在 best−tol 内的候选比例」；数值/集合题记 0。

> bench 复用建议：**不要改 vendored `tavernbench/`**。评分可直接用
> `python3 -m tavernbench.report --set data/eval --runs <dir> --systems <name>`（仅标准库），
> 或复用 `score.py:score_item` 的口径解释；但「搜索动作标签」需要自己按 §3/§4 的
> 引擎侧 oracle 复现，不能只依赖文本评分。

---

## 2. 如何用状态 JSON 恢复对局（含实测验证）

### 2.1 最小可用代码（dev 机实测通过）

```python
import sys, json
import hsbg_engine as E

# 复用 vendored tavernbench/engine.py 的三行 shim（它 import taverngym._core）：
sys.modules["taverngym"] = E
sys.modules["taverngym._core"] = E._core
sys.path.insert(0, "benchmarks/tavernbench")
from tavernbench import engine as TB          # TB.from_state / TB.preview / TB.apply_ops / TB.legal

row = json.loads(next(open_states_line))      # {"id":..., "state":..., 或附加字段}
g = TB.from_state(row["state"])               # == E.Game.from_json(row["state"])
assert json.loads(g.view(0))["phase"] == "recruit"
```

**【实测-dev】** 该 shim 在 dev 机可用：`TB.from_state/TB.preview/TB.apply_ops/TB.legal/
TB.view/TB.board_stats` 全部工作（`TB.preview` 内部走 `debug combat_preview`，
返回 win/tie/loss/dmg 与 n）。`render.py` 只提供 `minion_line/zone/card_rules/header/prompt`
（`render.py:36-83`），`state_text` 在 `run_tools.py:67-85` 里，不在 `render.py`。

**等价手写路径**（不依赖 shim，本次全部实测用这条）：

```python
g = E.Game.from_json(state_json)              # PyO3: lib.rs:144-153（check_loaded 见 engine.rs:140-161）
legal = [i for i, b in enumerate(g.legal_mask(seat)) if b]      # lib.rs:93-97
obs = g.observe(seat)                          # (f32[3227] bytes, i32[124] bytes)；lib.rs:104-108
v = json.loads(g.view(seat))                   # debug::view：JSON 可读视图；lib.rs:161-165
g.step(seat, action_index)                     # 非法抛 ValueError；lib.rs:98-103
preview = json.loads(g.debug('{"cmd":"combat_preview","a":0,"b":1,"n":1024,"details":false}'))
```

### 2.2 关键前提：卡表指纹一致（为什么能加载 36.6.3 状态）

- 引擎 `Game` 序列化含 `card_table: u64`（`engine.rs:123-126`），
  `check_loaded()` 拒绝「用另一张卡表写的状态」（`engine.rs:144-161`）；
  指纹 = 对 `data/cards.json` 的卡 id 按表顺序做 FNV-1a（`cards.rs:379-392`）。
- **【实测-dev】** dev 机 `hsbg_engine`（数据 `meta.client_version=37.0.0.255130`，
  `meta.count=3983`）的指纹 = **10833040883741191591（0x9656b149b0ad6da7）**；
  TavernBench eval 288 行 + full 720 行（含 D1 的 4 个候选状态）里的 `card_table`
  **全部等于该值**，`pool.counts` 长度也全部 = 3983。
- 结论：`data/p2` 的 37 数据管线保留了 AT 36.6.3 的卡表**顺序/长度**（`meta` 里
  `mapped_count=3695 + compat_count=288 = 3983`），所以 36.6.3 的状态在本构建上
  **可以逐位加载**。这是本 bench 可行的硬前提；换数据/重排卡表即失效
  （`docs/DATA_37_MIGRATION.md`、`rust/FORK.md` §7 需同步记录）。

### 2.3 实测加载统计

| 数据集 | 行数 | 含 `state` | 加载成功 | 多状态行（D1） | phase | turn 范围 |
|---|---:|---:|---:|---:|---|---|
| eval | 288 | 280 | **280/280** | 8 | 全部 `recruit` | 4–14 |
| full | 720 | 696 | **696/696** | 24 | 全部 `recruit` | 4–14 |

（eval 的 turn 计数：t4=23, t5=13, t6=40, t7=27, t8=39, t9=33, t10=35, t11=28,
t12=28, t13=13, t14=1。）

**座位/行动状态**：eval 280 行中 215 行 8 座全部 `needs_action=True`（同时招募），
其余行只有部分座位需要行动（含 pending choice 的行，见 §4.4 P 的 5 个 pending 状态）。
→ **bench 必须以 `g.needs_action(seat)` 为先决条件**，否则 `mcts_search`/`turn_search`
根 mask 为空（`search.rs:399-410` 会返回空 π、action=0）。

### 2.4 恢复后还要做的事（bench 语义）

1. **视角座位**：`entry.get("seat", 0)`；D4=5、N1=0、N2=6（实测）。
2. **pending choice**：部分状态一开始就有 pending（例如 P1-002 hero_power、
   P2-001 discover、P5-005 hero_power）；必须先用 `Choose(k)` 解决，再做题目要求的动作，
   否则 `Move`/`Play` 不在 legal mask 里（实测这 5 题只有 identity 排列可达）。
3. **对手是谁**：`scene_state()`（`engine.py:95-106`）把 `players[0].next_opponent=1`，
   并把玩家 1 的战团写进 `scouted`（字段存在：`state.rs:944, 956`），
   所以「下一场战斗的对手」固定是 seat 1；`TB.preview(g, a=ME, b=OPP)` 的默认值即可。
4. **隐藏信息红线**：`state_json` 含 8 座**全部**隐藏信息（手牌/金币/酒馆/战团）。
   题目状态用于**评分/oracle**没问题；但被测搜索/策略的**决策输入**只能来自
   `observe(seat)` + 公开信息（`docs/AZ_MCTS_SELFPLAY_DESIGN.md:194-205` 的 D3）。
   bench 报告里必须区分「oracle 评测」与「公开信息决策」。

---

## 3. hsbg_engine / AutoTavern 可用接口盘点

### 3.1 构建/版本事实（dev 机）

```text
E.version() = 1.0.0
E.data_info() = {'cards': 3983, 'game_version': '37.0.0.255130',
                 'server_rules_version': '37.0.0', 'n_cards': 3984}
E.build_info() = {'source_hash': '0fbf5da6e317622f', 'profile': 'release',
                  'file': '.../rust/python/hsbg_engine/_core.abi3.so'}
layout: N_ACTIONS=245, OBS_FLOATS=3227, OBS_CARDS=124
Python 3.14.9（PYTHONPATH=rust/python）
```

公开 API 与上游 TavernGym 1.0.0 逐位一致（仅包名改为 `hsbg_engine`，
`rust/python/hsbg_engine/__init__.py:1-13`）；新增 `db_info()/data_info()/build_info()`。

### 3.2 `Game`（8 座全控；搜索根/回放首选）

| 方法/属性 | 文件:行 | 用途 | bench 注意 |
|---|---|---|---|
| `Game(seed, config_json=None)` | `hsbg-engine-py/src/lib.rs:70-76` | 新开一局 | 与 TavernBench 无关 |
| `Game.from_json(str)` | `lib.rs:144-153` + `engine.rs:140-161` | **从 TavernBench 状态恢复** | 卡表指纹不符会拒绝 |
| `state_json()` | `lib.rs:139-143` | 精确存档（serde） | 含全部隐藏信息 → 只用于回放/评分/确定性 |
| `copy()` | `lib.rs:157-160` | 深拷贝（含 RNG） | 搜索/选项评估的成本主项 |
| `step(p, action)` | `lib.rs:98-103` | 应用 245 动作下标 | 非法抛 `ValueError` |
| `legal_mask(p)` | `lib.rs:93-97` | 245 长度 u8 mask | 搜索前必须非空 |
| `observe(p)` | `lib.rs:104-108` | `(f32[3227], i32[124])` 字节 | 策略/价值网络唯一输入 |
| `view(p)` | `lib.rs:161-165` | JSON 可读视图 | bench 读 shop/hand/board/pending 用它（非策略输入） |
| `debug(cmd_json)` | `lib.rs:166-173` | `set_player/add_minion/clear_zone/.../combat_preview` | 场景重建、oracle 评估 |
| `bot_action(p)` / `bot_play(p)` | `lib.rs:109-122` | 内置 bot 决策/打完 | `bot_action` 不移动 RNG |
| `turn`/`num_players`/`is_over`/`needs_action(p)`/`placements()` | `lib.rs:78-97, 123-125` | 状态查询 | `needs_action` 是搜索前置 |
| `health()`/`truncated_combats`/`turn_limit_end` | `lib.rs:126-138` | 诊断 | 用于 bench 稳定性统计 |

`debug` 命令全集（`debug.rs:961-1100`）：`set_player, set_turn, add_minion, add_spell,
remove, edit_minion, clear_zone, refresh_shop, give_trinket, offer_trinkets, set_deity,
advance_countdowns, reset_limits, set_hero, offer_hero, reroll_hero, action_cap,
set_hero_power, open_timewarp, give_quest, give_reward, add_secret, combat_preview`。
→ TavernBench 的 `scene()/scene_state()`（`engine.py:72-106`）就是用这批命令构造的；
在 37 数据上可以**重建同构场景**（卡 id 需按表位置/ID 映射）。

### 3.3 `BattlegroundsEnv` / `SoloEnv` / `BatchEnv`（训练/评测侧）

| 类 | 文件:行 | 能力 | bench 限制 |
|---|---|---|---|
| `BattlegroundsEnv(seed,config,agent)` | `rust/python/hsbg_engine/env.py:18-52` | 单学习座 vs 7 bot；`reset/step` gym 五元组；obs=features/cards/action_mask；`state_json()` | **没有 `from_json`** → 不能从 TavernBench 状态起局 |
| `SoloEnv` | `lib.rs:180-230` | 同上 C++ 级；`step→(reward,done,illegal)`；`observe/legal_mask/state_json` | 同样**无 from_json** |
| `BatchEnv(n_games,seed,controlled,config,threads)` | `rust/python/hsbg_engine/batch.py:31-104`；`lib.rs:239-352` | 批量观测/步进；`save(i)/load(i,s)`；`game(i)` 取 `Game` 副本；`threads` 不影响结果 | `save/load` 是 JSON 字符串；可从 `save` 恢复再 `load`（适合并行 rollout） |

### 3.4 `mcts_search`（逐步 MCTS，Rust 核）

签名（`lib.rs:560-634`）：

```python
pi_bytes, action, root_value, visits = E.mcts_search(
    game, seat, simulations=8, c_puct=1.5, temperature=1.0,
    eval_fn=None,          # eval_fn(features_bytes, cards_bytes, mask_bytes, seat) -> (policy_bytes f32[245], value)
    seed=0, dirichlet_alpha=0.3, dirichlet_epsilon=0.25, rollout=False)
```

实现要点（`rust/crates/hsbg-engine/src/search.rs:1-13, 20-39, 90-142, 301-522`）：

- **只对 `seat` 的 245 动作建树**；其余座位由**引擎 bot** 在边内推进
  （`advance_to_seat` → `bot::play_turn`），**不建对手分支、无显式 chance 节点**；
- 节点存完整 `Game`（clone 含 RNG）；PUCT；终局 utility =
  `1 − 2·(placement−1)/(n−1)`（`search.rs:90-99`）；价值备份是**标量**（不做符号翻转）；
- `eval_fn` 每节点首次扩展调用一次（总 ≤ simulations+1）；`rollout=True` 时叶节点
  不调 eval：先验=合法均匀，价值=`bot_rollout_value` 用 bot 打到终局（`search.rs:144-173`）；
- 返回 π 按 mask 兜底清零/归一化；随机性全由 `seed` 决定（可复现）；
- **限制**：搜索期间持 GIL（有 eval 回调时）；无批量/异步叶评估；无显式 chance 节点。
  `docs/RUST_ENGINE.md:446-476` 是同一份说明。

### 3.5 `turn_search`（回合内枚举 + pairwise 战斗）

签名（`lib.rs:674-726`）：

```python
scores_bytes, action, best_score, n_states, n_combats = E.turn_search(
    game, seat, states_budget=24, samples_per_action=1, combat_samples=1,
    max_steps_per_turn=40, seed=0, aggregate="max")   # scores = f32[245]
```

算法（`turn_search.rs:1-10`）：当前合法动作 a → 应用 a → 用**精简 heuristic**
补完本回合（EndTurn 前停住）→ 枚举 ≤ states_budget 个回合末状态 → 状态两两
`simulate_combat`（**优化的是候选状态之间的平均胜率**）→ 每个动作取可达状态 max/mean →
argmax。**不是**「对指定对手的下一场胜率」，也没有跨回合预测；`Cancel` 不参与、
`Freeze` 单向（`docs/TURN_SEARCH_RUST.md:9-39`）。

### 3.6 `combat_preview`（bench 的 oracle 评估器）

`debug({"cmd":"combat_preview","a":0,"b":1,"n":N,"details":bool})`：
对 `a` vs `b` 重跑 N 场战斗（N clamp 1..5000），每次 `rng = Game.seed ^ (const·(i+1))`
（`debug.rs:1612-1628`）→ 返回 `n/win_a/win_b/tie/avg_damage_by_a/avg_damage_by_b`；
`details=true` 额外返回逐场 `trials`（`winner/truncated/damage_dealt/damage_taken/
lethal_win/lethal_loss`），B4/B5 的期望受伤与致死概率就用它。`combat_preview` 不修改原 `game`。

### 3.7 **不存在的接口 / 数据（明确记录）**

| 缺口 | 证据 |
|---|---|
| 本机无 `hsbg_engine` 构建、无 cargo/rustc | `rust/target` 不存在；`C:\Python313\python.exe -c "import hsbg_engine"` → ModuleNotFoundError |
| `SoloEnv`/`BattlegroundsEnv` 无 `from_json`（不能从题库状态起局） | `lib.rs:180-230`、`env.py:18-52` 只有 `state_json` |
| 无正式 determinization / `BeliefSampler` / `Game::resample_hidden` 接口 | `docs/AZ_MCTS_SELFPLAY_DESIGN.md:863-874`（§7.6 仍是设计）；Rust 侧无对应函数（grep 无） |
| `mcts_search` 无批量叶评估、持 GIL、无 chance 节点 | `docs/RUST_ENGINE.md:473-476`；`docs/AZ_1K_VALIDATION.md:69-75` |
| 无 RL 训练集 / AZ 模型 checkpoint / 搜索 run 产物 | `runs/` 仅 `runs/webui/*.json`；`docs/AZ_1K_VALIDATION.md:61-67` 说产物已清理；`docs/CLEANUP_20261024.md` 记录 `runs/warband_value/model_60k` 已删除 |
| 无 TavernAgent 权重/训练代码；无 item generator | `docs/TAVERNBENCH.md:280-286` |
| TavernBench 无「搜索系统」答案（只有 LLM/TavernAgent/Jev） | `results/{eval,tools}/` 目录 |

---

## 4. 可复现的 Bench 方案（针对「不完全信息搜索质量」）

### 4.0 前置与产物约定

- 在 **dev 机** `bicourse-glt` 的 `~/projects/HSBRSIM` 执行（本地无引擎）；
  环境：`PYTHONPATH=rust/python python3`，Python 3.14.9，`hsbg_engine` release 构建
  已在 `rust/python/hsbg_engine/_core.abi3.so`。
- 建议新增一个只读 bench 脚本（本次任务不允许写代码，故只给方案）：
  `scripts/az_tavernbench_bench.py`；产物写 `runs/az_bench/<timestamp>/report.json`
  （`runs/` 已 gitignore）。**不改** `benchmarks/tavernbench/**`、**不改** `hsbg/az/**` 既有文件。
- 所有配置显式记录：`data_version=37.0.0.255130`、`engine source_hash`、
  `bench set=eval|full`、`n`（combat 采样）、`sims/determinizations/seed`。

### 4.1 Tier 0：状态载入 smoke（30 秒级）

对 `data/eval` 与 `data/full` 全部状态行：`Game.from_json`，统计成功数、phase、
`needs_action(seat)`、pending 数、以及 `state_json()→from_json→state_json()` 往返字节相等。

**验收**：eval 280/280、full 696/696 成功（另 8/24 行分别对本行 `states[i]` 全成功）；
phase 全为 `recruit`；往返字节相等率 100%（引擎侧保证见 `docs/RUST_ENGINE.md:285-287`）。

### 4.2 Tier 1：Oracle 标签复现（bench 的「标尺」）

对 17 个可执行场景的每个任务：

```python
g = Game.from_json(row["state"])
for opt in row["options"]:            # 或 P 的 perms[i]（用 Move 合成排列，见 4.4）
    gg = g.copy(); apply_ops(gg, opt["ops"])    # 复用 TB.apply_ops 或 §2.1 手写（已实测等价）
    win = debug(gg, combat_preview, a=0, b=1, n=1024)["win_a"]
label_best = argmax(opt -> label["values"][key(opt)])       # T1 用 label["meta"][i]
```

**验收（本次实测已达，作为回归基线）**：
eval 104 任务 top-1 = 104/104，逐选项 MAE ≤ 0.0057（多数 ≤ 2e-4）；
full 312 任务 / 3624 选项 top-1 = 312/312、0 非法动作，MAE ≤ 0.0049；
`n=1024` 下 3624 选项 ≈ 81 s（45.8k combat/s）单进程。
→ 若复现低于 **top-1 ≥ 0.98**，说明引擎/数据/`apply_ops` 语义出问题，**先修 bench 再做搜索评测**。

### 4.3 Tier 2：搜索质量（17 场景，144 eval / 432 full 任务）

**被测系统**（同一 harness、同一 seed 集）：

| 系统 | 入口 | 说明 |
|---|---|---|
| `oracle-option` | 4.2 的枚举 | 天花板（标签复现器） |
| `random-legal` | 随机合法动作 | 下限；参考 chance=0.227 |
| `bot` | `Game.bot_action(seat)` | 引擎内置策略 |
| `turn_search` | `E.turn_search(..., states_budget=8/16, combat_samples=8)` | Rust 回合内 pairwise 搜索 |
| `mcts_rollout` | `E.mcts_search(..., simulations=4/16, rollout=True)` | 纯搜索（bot rollout 叶值） |
| `az_search` | `hsbg.az.search(game, seat, config=SearchConfig(simulations=..., determinizations=K, seed=...))` | 队友的 PIMC/determinization 原型（`hsbg/az/__init__.py:5-18`），**bench 侧只调用公开接口** |
| `az_search + NN` | 同上 + `eval_fn` | 若后续有策略/价值 checkpoint（当前**不存在**） |

**每题流程**：`g=from_json` → `seat=entry.get("seat",0)` → 若 pending 先按固定规则
Choose/解决 → `search(g, seat)` → 取得 action → `step` → 若仍有 pending（O/T/E3 多步题：
`search` 只给第一步）则**继续按同一系统逐步决策**直到题目要求的动作序列结束/回合结束 →
用 `combat_preview(n=1024)` 评估「对 seat 1 的下一场胜率」。

**指标**（每场景 + 子集汇总；报告均值 ± bootstrap 95% CI）：

1. `legal_rate`：搜索输出动作合法率（要求 **1.0**；非法直接记 0 分并计入错误）；
2. `top1_agree`：系统最终局面/选项是否等于「标签最优选项」（与 4.2 的 oracle 一致）；
3. `regret`：`value(oracle_best) − value(system_chosen)`（胜率单位，越小越好；oracle 自身为 0）；
4. `spearman`：系统对候选集合的排序与标签 `values` 的 Spearman ρ（适用于 O/E3 等大候选集）；
5. `solve_rate`：在**只允许 1 次 `step`** 的严格模式下，系统是否直接产出题目要求的完整动作
   （O/E3 多选题需要多步 → 记录 `needs_multi_step` 比例，避免低估单步搜索）；
6. `sims/s`、`decisions/s`、`p50/p95 latency`；
7. `panics/errors/truncated_combats`：引擎异常与战斗被 guard 截断次数（`Game.truncated_combats`）。

**建议验收线（v0.1，待 Lead 定）**：
- 硬性：`legal_rate = 1.0`、0 engine error、Tier 1 复现 ≥0.98；
- 单步离散题（T1–T5/D3/D5）：`top1_agree ≥ 0.90`；
- 多步题（O1–O5/E3）：`top1_agree ≥ 0.75` 或 `spearman ≥ 0.90`；
- 17 场景整体 `top1_agree ≥ 0.85` 才能宣称「搜索质量接近标签口径」；
- 参考系：chance 0.227、最佳 LLM 0.625、TavernAgent 0.986、oracle 1.000。

**注意（已实测到的目标错配）**：`turn_search` 在 T5 上 0/8（mean regret 0.490），
因为它优化的是「候选状态互相之间的胜率」而不是「对指定对手的胜率」；T2 则 8/8。
所以**必须**把 `turn_search`/`mcts_rollout` 的结果与 oracle 分开报告，并在报告里写清
「搜索目标 ≠ 标签目标」的解释，否则会把目标错配误读成搜索失效。
（`docs/ALGORITHM_RESEARCH.md:1068-1130` 记录的是旧引擎/旧对手下的 pairwise 形态收益，
`docs/TURN_SEARCH_RUST.md:90-120` 记录 Rust 版在新引擎上 mean rank 8.00、未复现旧结论。）

### 4.4 Tier 3：P1–P5 排列搜索（Move 合成）

- `perms[i]` 是「原战团下标的一个排列」。bench 用 **legal Move 动作 BFS** 把当前棋盘
  重排到目标顺序，再 `combat_preview`：
  - 实测（eval 40 题）：**35/40 题的全部 5 个排列都可在 Move 深度 ≤6 内到达**，
    且 top-1 35/35 与标签一致，逐排列胜率与标签 `meta` MAE 0.0054–0.0072（单题最大 0.0118）；
  - **5/40 题（P1-002, P2-001, P2-002, P3-006, P5-005）状态里带 pending**
    （hero_power/discover），未解决前只有 identity 排列可达 → 必须先固定 Choose 规则
    （如取第一个合法项）再重排，并**单独标记**这 5 题的口径（标签是在有 pending 的状态上生成的，
    需要确认上游生成器当时如何处理 pending）。
- 搜索质量指标同 4.3（top1/regret/legal），但候选空间是 `5` 个给定排列；
  若测「开放式排列搜索」，则让搜索自己在 Move 空间里找，报告「是否命中标签的 5 个排列之一」。

### 4.5 Tier 4：长程规划题（N1,N2,D4,D1,D2；88 eval 任务）

标签是 **128 次整局模拟的 `mean_place`**（D4/N1/N2 的 `label["meta"]`），不是下一场胜率：

- 做法：从状态出发，被测系统每回合决策（其余 7 座由引擎 bot 驱动），打到终局，
  每个选项/首动作重复 **128 次**（与标签同 reps）→ 比较 `mean_place` 排序；
- **只比较相对排序**（Spearman/top-1），不要比较绝对值：上游 TavernAgent 用的对手策略
  与我们的 `bot::play_turn` 不同（`docs/TAVERNBENCH.md:280-286` 已声明标签由论文时期
  TavernGym 计算）；
- D2/D4 的 `map` 给出 `Choose(k)` 动作；D1 的 4 个候选是**不同英雄的整局状态**
  （`states[i]`），不是同一局的 4 个动作 → D1 更适合做「价值函数对开局英雄的排序」而不是搜索题；
- 成本高（4 选项 × 128 整局 ≈ 512 局/题；参考 `run_bot_games` 201.6 games/s
  见 `docs/AZ_MCTS_SELFPLAY_DESIGN.md:923-945`，单题数秒）。

### 4.6 Tier 5：不完全信息专项（determinization / belief / oracle gap）

这是「AlphaZero 不完全信息搜索」区别于 3.4 静态标注的核心，建议独立成表：

1. **determinization 稳定性**：同一任务、同一搜索配置，K 个世界线（K=1,2,4）下
   `π_top1` 动作一致率、动作分布 Jensen-Shannon / top-1 margin；
   验收建议：K≥4 时 top-1 一致率 ≥0.8（任务可复现级别）。
2. **oracle gap**（诊断用，禁止计入正式分数）：
   - `obs-search`：决策输入只用 `observe(seat)`（合法）；
   - `privileged-search`：允许用 `state_json` 的真实隐藏信息推进/评估；
   - 报告 `Δ = mean_place(obs) − mean_place(privileged)`（越大说明估计器越重要）；
   - 定义与判据见 `docs/AZ_MCTS_SELFPLAY_DESIGN.md:194-205, 370-391`。
3. **确定性/可复现**：同 seed + 同动作 ⇒ 逐位一致（`Game` 含 RNG；`mcts_search` 全随机由
   `SearchConfig.seed` 决定，`search.rs:20-39, 201-253`）。
4. **隐藏信息泄漏检查**：统计被测策略/搜索代码是否读取 `view/state_json` 中其他座位的
   隐藏字段（bench 侧可用「只给 obs 的接口 + grep 代码」双重检查；`D3` 决策见
   `docs/AZ_MCTS_SELFPLAY_DESIGN.md:63-72`）。

### 4.7 指标定义（汇总）

```text
legal_rate      = #legal_actions / #decisions
top1_agree      = 1[system_chosen_option == label_best_option]（A 类题）
regret          = win(label_best) − win(system_chosen)          （A 类题，胜率单位）
spearman        = rank corr(system_option_scores, label values) （A 类多选项）
mae_label       = mean |engine_win(option) − label_value(option)|（Tier-1 自检）
brier(self)     = Σ(p_engine − p_label)^2                       （B3/B6 校准）
die_absdiff     = |P_engine(death) − label|                     （B5）
mean_place      = 终局名次均值（越小越好；C 类题，128 reps）
delta_oracle    = mean_place(obs-only) − mean_place(privileged) （仅诊断）
sims_per_s      = simulations / wall_clock
determ_stability= top1 一致率 over K worlds
```

### 4.8 哪些标签**不能**直接当 RL 动作标签（红线）

| 标签类型 | 场景 | 能否当 RL 动作标签 | 原因 |
|---|---|---|---|
| `options[i].ops` 动作序列 | O1–O5,T1–T5,E3,D3,D5 | **可以**（已实测 3624/3624 合法） | 可精确映射到 245 动作；但语义是「**对下一场战斗胜率**的 argmax」，不是整局回报 |
| `perms[i]` 排列 | P1–P5 | **可以**（Move 合成；35/40 直接可达） | 同上；排列→Move 序列不唯一，需固定合成规则 |
| `map` 首动作 | N1,N2 | 可以（**仅第一步**） | 题目说「之后按自己的判断打」，完整动作序列未给出 |
| `map` Choose | D2,D4 | 可以（单动作） | 但标签口径是 128 reps 的整局 `mean_place`，不是一步回报 |
| 英雄候选状态 | D1 | **不可以**当 245 动作标签 | 4 个选项是**不同整局状态**（不同英雄），不是同一局的动作 |
| 战斗预测 | B1–B6,R2 | **不可以**当动作标签 | 是「环境预测/价值校准」目标（win/tie/loss、伤害、先手、致死概率） |
| 规则文本题 | R1,R3–R7,E1,E2,E4,E5 | **不可以**（无法在环境里执行） | 无状态、纯规则推理，只能做 LLM 文本评测 |
| 全部标签 | 40 场景 | **不可以**直接当 RL reward | 标签是**离线题库的静态答案**（多为单步 proxy），不是 rollout 回报；训练目标应仍为终局名次（`docs/AZ_MCTS_SELFPLAY_DESIGN.md:33` D9） |

---

## 5. 既有文档可复用内容 / 风险（按要求逐份提取）

### 5.1 `docs/TAVERNBENCH.md`（本仓库的集成说明）

- 可复用：数据结构/计数（§2，:59-93）、评分口径与作废规则（§4，:181-208）、
  完整性自检入口（§3.1，`python3 scripts/run_tavernbench.py --check`，26 项检查）、
  与 RL 评测的边界（§7，:290-318）。
- 风险/缺口：-**§7 明确「HSBRSIM 的 RL 策略不能直接接入」**（动作空间/版本不同，
  需自写适配器）；数据版本 36.6.3 vs 37.0.0（本次已用指纹证明**状态可加载**，
  但卡牌行为差异需按 Tier-1 复现扫描持续监控）；`--check` 只验评分复现，
  不验「状态可被本引擎加载」，本文件 §2.3 是补充证据。

### 5.2 `docs/AZ_MCTS_SELFPLAY_DESIGN.md`（AZ 搜索主设计）

- 可复用：D1–D11 决策（:21-35）；接口基线表（:46-56）与硬约束（:63-72，
  245 固定动作、EndTurn 宏动作、`Choose` 是独立动作、无隐藏信息注入 API）；POMDP/信息集/
  信念定义（:101-136）；determinization 多世界线（:370-391）；成本模型（:393-409，
  `C_dec ≈ S·(c_copy + L·c_step + c_eval)`）；与标准 AZ 假设的对照表（:411-422）；
  成对胜负矩阵（:426-483，适合「候选战团相对强度」评估，可替代 rollout 叶值）；
  M0 实测（:923-950：copy p50 2.45 µs、observe 1.63 µs、legal_mask 0.20 µs、
  step p50 3.1 µs、`run_bot_games` 201.6 games/s、`combat_preview` 2.6 µs/combat）；
  评测指标与门禁（:999-1021）；与 AT/TavernBench 可比性（:1023-1028，明确 37 vs 36.6.3、
  「可选 adapter：obs→TavernBench prompt/答案格式」——本文件 §4 正是这个 adapter 的 bench 版）；
  风险清单（:1269-1282）。
- 风险：determinization/belief 仍只是**设计**（§7.6 未实现）；oracle gap 需要
  「特权搜索」且不得进正式分数；成对矩阵只是相对评估（§3.10 注，:482-483），
  不能当终局名次的无偏估计；8 座全搜索成本高（估算 ~150 ms/局引擎部分，目标 1–4 games/s/core）。

### 5.3 `docs/ALGORITHM_RESEARCH.md`（算法调研/旧实验）

- 可复用：AZ 假设逐条核对表（:46-69，8 人常和/部分可观测/非确定性/动态候选）；
  隐藏信息处理方案（§2.3，:115-141）：determinization + 对手模型 + single-agent MDP PUCT，
  不做 minimax；determinization v0 与评估口径（§3.6，:301-364：战团分布匹配/战斗校准/
  oracle gap/泄漏检查/可复现——**这套评估口径可直接搬进 bench 的 Tier 5**）；
  turn_search 旧实验（§6.10/§6.14，:1068-1137：状态预算敏感、旧引擎 20 局 states16
  +1.05 CI[0.35,1.80] p=0.0034，但 Rust 新引擎未复现）；「战斗子游戏不搜索、用精确裁决」的
  结论（§2.1，:75-91，与 TavernBench B 类题完全一致）。
- 风险：该文档基于**旧 hsrl2 引擎/旧动作空间**（`hsrl2` 已停用）；文中 clone/step 成本与
  turn-search 数据不能直接当 Rust 引擎的预算；「搜索无增益/有增益」的历史结论口径不同，
  引用时必须带引擎版本（本文件 §0-6 已给出新引擎实测）。

### 5.4 既有搜索实验（直接决定 bench 的解释方式）

| 文档 | 结论（原文口径） | 对 bench 的影响 |
|---|---|---|
| `docs/AZ_PURE_SEARCH_TEST.md`（:20-55） | `rollout=True`（bot 全 rollout 叶值）在 1000 局下 mean rank **7.98**、heuristic 基线 4.507；作者结论是 **off-policy rollout 不匹配**、不是 MCTS bug | `mcts_rollout` 只能当「纯搜索上限的下限」基线；bench 里要标注 rollout 目标（placement）与标签（下一场胜率）不同 |
| `docs/AZ_1K_VALIDATION.md`（:20-59） | 1k 局 / 510,880 决策；数据采集 2.96 局/s；value-rank 相关 0.706；policy top-1 vs π 0.595；search-on mean rank 8.00；π 41.3% argmax=EndTurn | 冷启动搜索会把 π 退化成 EndTurn；bench 必须报告 `π 熵/argmax 分布/EndTurn 占比`，不能只看 loss/胜率 |
| `docs/TURN_SEARCH_RUST.md`（:90-120） | Rust turn_search 3 局 mean rank 8.00；旧 Python 版 mean rank 2.90 未复现；差异列表（heuristic 精简移植、对手 bot 不同、数据/动作版本） | `turn_search` 在 TavernBench 上只是基线之一；跨引擎不可比 |
| `docs/SEARCH_15TURN_BENCH.md`（:46-85） | 15 回合单座：width/depth/horizon 无稳定增益；seed 方差远大于 config 差；w2d2 代价 3.3× | 搜索预算/深度必须配「方差控制 + 足够 seeds」；bench 的 144/432 题要按题配对统计 |

---

## 6. 风险与开放问题（编号，供 Lead 决策）

- **R1 数据版本/指纹耦合**：TavernBench 状态只能在**保持 AT 卡表顺序**的 37 数据构建上加载。
  若后续数据重排/删卡导致 `card_table` 指纹变化，Tier 0 会整体失败（先修数据管线而不是改 bench）。
- **R2 标签是 proxy，不是回报**：17 个 A 类题的标签 = 「对指定对手的下一场胜率」；
  强搜索若优化整局名次会**系统性偏离标签**（实测 T5 已出现）。bench 必须同时报告
  「标签一致率」与「整局强度」（后者用 Tier 4/自对弈），不能混为一谈。
- **R3 搜索目标错配**：`turn_search` 的 pairwise 目标 ≠ 标签目标（§4.3 反例）；
  `mcts_rollout` 的终局 placement 目标也 ≠ 标签目标。接入时要么改评估器（用 combat
  preview/成对矩阵做叶值），要么明确标注「非标签口径」。
- **R4 对手模型不同**：TavernBench 标签由论文期 TavernGym 生成；本引擎对手是
  `bot::play_turn`（`search.rs:114-142`）。N/D 类绝对 `mean_place` 不可跨口径比较，
  只能比较排序或重算标签（重算代价：128 reps × 选项数）。
- **R5 不完全信息专项缺接口**：无正式 `BeliefSampler`/`resample_hidden`（§3.7）；
  `hsbg/az/belief.py` 是 Python 侧原型。Tier 5 的 determinization 稳定性/oracle gap
  只能基于现有 `hsbg.az` 接口 + `state_json` 诊断，**要防止把 oracle 搜索当正式分数**。
- **R6 状态里的 pending**：P 的 5/40 题（以及其它场景个别行）初始就有 pending choice；
  搜索/bench 必须先定义 Choose 规则并单独报告，否则会得到「只有 identity 动作可达」的假象。
- **R7 座位字段**：D4 的 `seat=5`、N2 `seat=6`；写死 `seat=0` 会得到空 mask，
  `mcts_search` 会返回 action=0/空 π（`search.rs:399-410`），看起来像「搜索失效」。
- **R8 性能/GIL**：`mcts_search` 有 eval 回调时持 GIL、无批量评估（§3.4）；
  Tier 2 规模（144/432 题 × 多 sims × 多系统）在 dev 机单进程可行（Tier-1 扫描 81 s），
  但带 NN 的系统需要另算（参考 `docs/AZ_1K_VALIDATION.md:30`：eval 回调是瓶颈）。
- **R9 评分文本口径**：官方分数依赖 JSON 解析/预算规则（§1.5）；搜索系统直接输出
  动作下标，需要写 **adapter 转成 label 的 answer 形状**（如 O 的字母顺序、E3 的
  tavern position 列表），否则 `tavernbench.score` 无法评分。adapter 必须与 bench 的
  动作语义严格一致（本文件 §1.4 的 `options`/`map`/`perms` 即映射依据）。
- **R10 产物/可复现**：仓库无 checkpoint/训练集（§3.7），bench 只能评「现有系统 +
  `hsbg/az` 原型」；所有数字必须附 seed、n、sims、source_hash，并写入
  `runs/az_bench/.../report.json`，否则不可复现（项目纪律见 `docs/AUDIT_PROTOCOL.md` §8）。

---

## 7. 本次实测命令与证据

### 7.1 本机（只读，无引擎）

```powershell
# 数据计数/场景表/评分统计（本机 Python 3.13）
C:\Python313\python.exe -c "import json,gzip,collections; ..."   # 见 §1 表格
# 读 golden 逐场景 acc（chance/TavernAgent/最佳 LLM）
C:\Python313\python.exe -c "import json; rep=json.load(open(r'C:\HSagent\benchmarks\tavernbench\expected\eval_report.json'))"
# 卡表指纹复算（FNV-1a over data/cards.json ids） → 10833040883741191591
```

### 7.2 dev 机环境/加载（`bicourse-glt`）

```bash
cd ~/projects/HSBRSIM && PYTHONPATH=rust/python python3 -c "
import hsbg_engine as E; print(E.version(), E.data_info(), E.build_info())"
# → 1.0.0 {'cards': 3983, ..., 'n_cards': 3984} {'source_hash': '0fbf5da6e317622f', 'profile': 'release', ...}

PYTHONPATH=rust/python python3 - <<'PY'
import gzip, json, hsbg_engine as E
for s in ("eval","full"):
    rows=[json.loads(l) for l in gzip.open(f"benchmarks/tavernbench/data/{s}/states.jsonl.gz","rt",encoding="utf-8")]
    ok=fail=multi=0; ph=set()
    for r in rows:
        if "state" not in r: multi+=1; continue
        g=E.Game.from_json(r["state"]); ok+=1; ph.add(json.loads(g.view(0))["phase"])
    print(s, len(rows), "with_state", len(rows)-multi, "ok", ok, "multi", multi, "phases", ph)
PY
# → eval 288 with_state 280 ok 280 multi 8 phases {'recruit'}
# → full 720 with_state 696 ok 696 multi 24 phases {'recruit'}
```

### 7.3 Tier-1 oracle 复现（eval + full，本次实测）

```bash
cd ~/projects/HSBRSIM && PYTHONPATH=rust/python python3 - <<'PY'
# 完整脚本：对 17 个可执行场景，逐 option apply_ops → combat_preview(n=1024) → 与 label 对比
# （脚本要点见 §4.2；本次直接内联运行，未落盘）
PY
# eval 104 任务：top1 104/104；MAE ≤ 0.0057（T1 最大，其余多数 ≤2e-4）
# full 312 任务 / 3624 选项：top1 312/312；MAE ≤ 0.0049；0 illegal ops
# 计时：3624 选项 × n=1024 = 3,710,976 combats → 81.06 s（45,778 combat/s，44.7 option/s）
```

### 7.4 B/R2 战斗预测复现（eval，n=2048；B4/B5 n=1024 details）

```text
B1 先手 acc 8/8
B2 win/tie/loss acc 8/8, 与 label meta 的 MAE 0.0000
B3 brier 0.0001, argmax 8/8
B4 期望受伤相对误差 0.0172（tol 0.25）
B5 致死概率绝对误差 0.0168（tol 0.15）
B6 brier 0.0002, argmax 7/8
R2 acc 8/8, meta MAE 0.0000
```

### 7.5 P（排列）复现（eval，n=1024）

```text
P1 7/8 可枚举（P1-002 pending）、top1 7/7、MAE 0.0059
P2 6/8（P2-001/P2-002 pending）、top1 6/6、MAE 0.0067
P3 7/8（P3-006 pending）、top1 7/7、MAE 0.0054
P4 8/8、top1 8/8、MAE 0.0064
P5 7/8（P5-005 pending）、top1 7/7、MAE 0.0072
```

### 7.6 搜索 pilot（eval T2/T5，每场景 8 题；先 1 步，pending 用第一个合法 Choose 解决）

```text
T2: turn_search(states16,combat8) top1 8/8, mean regret −0.003
    mcts_search(rollout=True, sims=4) top1 7/8, mean regret 0.002
T5: turn_search top1 0/8, mean regret 0.490
    mcts_search(rollout=True, sims=4) top1 0/8, mean regret 0.383
T5-000 明细：turn_search 选 action 21 (Sell(5)), score=1.0, n_states=2, n_combats=8；
            该局面对对手 preview win=0.0；标签最优 `values["2"] = 0.8213`。
```

### 7.7 原始来源（本文件引用的一手文件）

- 数据：`benchmarks/tavernbench/data/{eval,full}/{prompts,labels,states}.*`、
  `expected/eval_report.json`；
- 评分代码：`benchmarks/tavernbench/tavernbench/{score,report,chance,engine,render,run_tools}.py`；
- 引擎：`rust/python/hsbg_engine/{__init__,env,batch}.py`、
  `rust/crates/hsbg-engine-py/src/lib.rs`、
  `rust/crates/hsbg-engine/src/{search,turn_search,debug,engine,cards,state,config}.rs`；
- 文档：`docs/{TAVERNBENCH,AZ_MCTS_SELFPLAY_DESIGN,ALGORITHM_RESEARCH,RUST_ENGINE,TURN_SEARCH_RUST,SEARCH_15TURN_BENCH,AZ_PURE_SEARCH_TEST,AZ_1K_VALIDATION}.md`。

---

## 8. 给 Lead 的下一步建议（按优先级）

1. **先落 bench 标尺**（Tier 0+1）：`scripts/az_tavernbench_bench.py` 实现 §4.1/§4.2，
   把「状态可加载 + 标签可复现」固化为回归门禁（建议 top-1 ≥0.98 才放行搜索评测）。
2. **再接入被测系统**（Tier 2）：`turn_search`/`mcts_rollout`/`hsbg.az.search` 三个系统
   × {eval 144 任务}，先只报 legal_rate/top1/regret/sims/s；T5 反例要写进报告解释。
3. **不完全信息专项**（Tier 5）与 `hsbg/az` 的 `BeliefSampler` 对齐：K=1/2/4 稳定性 +
   oracle gap（诊断，不进正式分）。
4. **长程题（Tier 4）单独排期**：N/D 类 128 reps 的整局 rollout 成本高，且对手 bot
   口径与标签生成不同，只做排序一致性，不建议作为第一版门禁。
5. 明确**不采用**：无状态 10 场景（80 eval 题）做引擎 bench；把 B 类预测标签当动作标签；
   用 `state_json` 隐藏信息做正式策略输入。
