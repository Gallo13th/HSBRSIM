# 审计协议（Audit Protocol）

> 适用：8 小时自主审计轮（Lead + teammates 并行）。
> 上位约定：[AGENTS.md](../AGENTS.md)（仓库级规则）；
> 协作规则：[MULTI_AGENT_RULES.md](MULTI_AGENT_RULES.md)；
> Live 协作：[LIVE_AUTOMATION_PROTOCOL.md](LIVE_AUTOMATION_PROTOCOL.md) §10；
> gap 台账：[LIVE_TO_SIM_GAP.md](LIVE_TO_SIM_GAP.md)；
> 口径/冲突登记：[AUDIT_CONSISTENCY.md](AUDIT_CONSISTENCY.md)。

---

## 0. 五条原则

1. **证据先行**：没有落到文件/命令/行号的结论不算结论。E2 以下不得报 P0，E3 以下不得标 `fixed`。
2. **只读优先**：审计默认只读（代码、数据、截图、日志）；需要写代码时按写范围预约，见 [MULTI_AGENT_RULES.md](MULTI_AGENT_RULES.md) §2。
3. **可复现**：每条 gap 必须给「命令 + 输出路径」，其他 agent 在 5 分钟内能复跑；只贴 stdout 不算。
4. **分层归因**：`live UI / env 动作 / 引擎规则 / 数据脚本` 四层分开记；**数据旧不是引擎 bug**（AGENTS §5），live 识别不到位也不是引擎缺失。
5. **不制造回归**：任何修复必须过 §7 门槛；禁止为了让测试变绿而删测试、放宽断言或 `skip` 掩盖。已知红只能 `xfail(reason="gap-id")` 并登记 gap。

---

## 1. 审计输入（Inputs）

| ID | 输入 | 路径 / 来源 | 格式 | 用途 | 有效性要求（不满足则不作为证据） |
|---|---|---|---|---|---|
| I1 | Live 截图 | `runs/live/<run_id>/screenshots/**/*.png` | PNG（全分辨率） | UI 状态、按钮/目标/弹层、失败现场 | 文件名以 `HHMMSS` 开头；能在 `actions.jsonl` 找到同秒动作；截图前已 `_focus()` |
| I2 | 动作日志 | `runs/live/<run_id>/actions.jsonl` | JSONL | 动作序列、决策分值、no_effect、失败 | 每行含 `ts/actions/kind/note`；`note` 符合 §5.2 命名协议 |
| I3 | 状态快照 | `runs/live/<run_id>/settled/turn_XX.json`、`state_*.json` | JSON（`hsbg.live_state.v1`） | 资源/场面/合法性判定 | 含 `schema/phase/turn/gold/legal`；采样时刻与动作可对应 |
| I4 | 诊断包 | `runs/live/<run_id>/diagnostics/<...>/meta.json` | JSON + 5 帧 | 卡住/弹层/失焦定位 | `meta.json` 指到 5 帧 + 5 份 state，路径可解析 |
| I5 | 代码 | `hsbg/**`、`hsrl2/**`、`tests/**`、`scripts/**`、`tools/**` | Python | 行为断言、file:line 证据 | 记录当前工作树状态（行号以本会话 read 为准）；不引用过期行号 |
| I6 | 文档 | `docs/**` | Markdown | 既有结论/契约/优先级 | 引用时给 `文档:行`；结论冲突按 §9 裁决 |
| I7 | 数据 | `data/bg_*.json`、`data/bg_summary.json` | JSON | 池/卡/技能/饰品覆盖统计 | 以 `python` 实测计数，不抄文档旧数字 |
| I8 | 测试结果 | pytest / smoke / verify_all 输出 | stdout/日志 | 回归与基线证据 | 记录「命令 + 时间 + passed/failed/耗时」；不引用历史常量 |
| I9 | 审计脚本产物 | `runs/audit/*.json` | JSON | 覆盖矩阵、三方对账 | 产物带生成命令与时间戳；与 I7 同源 |
| I10 | 真实对局日志 | `runs/live/**/Power.log`、`hsbg/live/logwatch.py` 输出 | 文本/JSON | 服务端结算对照（gold/health/combat） | 只作旁证；与游戏内截图冲突时以可复现证据为准 |
| I11 | 任务板 / 消息 | `team_task_list/get`、agent 消息 | 会话内 | 协作证据（谁在做什么） | **不能**作为机制/代码证据；仅用于协作与归因 |

**输入齐全性自检**：任何一个「缺 live 截图」或「缺 actions 对照」的 gap，只能标 E1/E2，不能进 P0 修复队列。

---

## 2. 证据等级（E0–E4）

| 等级 | 定义 | 能支撑的结论 | 典型例子 |
|---|---|---|---|
| **E0** | 未验证断言（口头/猜测/"看代码应该是"） | 只能作为线索，不得写进 gap 表 | "我记得 freeze 没实现" |
| **E1** | 单帧截图或单行日志，无对照 | 只能登记「观察项」，不得判层/定 P0 | 一张英雄选择页截图 |
| **E2** | 截图 + `actions.jsonl`（+state）对照，能说清「哪个动作 → 期望什么 → 实际什么」 | 可报 bug、可定 `live_ui`/`lifecycle` 类 P0/P1 | `drag_play_BG36_345.png` + `no_effect` 行 + state 无变化 |
| **E3** | E2 + 代码路径/数据实测（`file:line` 或 `python -c` 输出） | 可归因到 env/engine/data，能提修复方案 | 定位到 `game.py:1517-1518` 未读 `CHOOSE_BOTH` |
| **E4** | E3 + 运行复现（pytest / smoke / live 同局面复跑）+ 修复后回归通过 | 可标 `verified`，可作为报告结论 | 补测试 + `pytest tests -q` 绿 + live 复跑无同类 no-effect |

**使用规则**

- 报 P0 至少 E2，且必须写清「影响面」（训练动作空间/错误信号/崩溃/真实交互等价）。
- 提交修复方案至少 E3；标 `fixed` 必须 E3 且附测试；标 `verified` 必须 E4 且附复跑命令与时间。
- 同一 gap 的证据升级时，更新 gap 行的 `evidence_level`，不要新开重复 ID。
- 禁止把 E2 的「live 观察」当成引擎机制结论（见 §11 反模式）。

---

## 3. 分层审计模型

```text
真实客户端 UI  →  Live 层（截图/动作/状态/验证）
                        ↓ 动作语义以 spec.py 为准
                 Env 层（ActionKind/候选/目标/观测/step）
                        ↓ 引擎 API
                 Engine 层（hsrl2：机制/结算/PendingChoice）
                        ↓ 数据/脚本
                 Data/Scripts 层（data/*.json + REGISTRY）
```

| 层 | 审计对象 | 必查项 | 产出/权威文档 |
|---|---|---|---|
| **Live** | `hsbg/live/**` | 动作矩阵覆盖（买/卖/打/刷/升/冻结/技能/发动/黑暗之赐/结束回合/换位）、`no_effect` 率、`start_combat` 误触、目标选择高亮、脏帧处理、截图完整性 | [LIVE_AUTOMATION_PROTOCOL.md](LIVE_AUTOMATION_PROTOCOL.md) §4–§8；gap 记 `live_ui` |
| **Env** | `hsbg/env/**` | `ActionKind` 覆盖、目标可寻址、观测语义（gift_id/power_id/label）、choice 暂停边界、确定性（同 seed 一致）、测试覆盖 | [ENV_SPEC.md](ENV_SPEC.md)、[AUDIT_ENV_ACTIONS.md](AUDIT_ENV_ACTIONS.md)、[LIVE_TO_SIM_GAP.md](LIVE_TO_SIM_GAP.md) |
| **Engine** | `hsrl2/**` | 机制 API 完整性、`PendingChoice` 契约（不出队/幂等）、脚本覆盖、事件/时机、回归测试厚度 | [ENGINE_API.md](ENGINE_API.md)、[ENGINE_NOTES.md](ENGINE_NOTES.md)、[AUDIT_ENGINE_MECHANICS.md](AUDIT_ENGINE_MECHANICS.md) |
| **Data/Scripts** | `data/*.json`、`hsrl2/scripts/**` | 池卡/技能/饰品的 `REGISTRY` 覆盖、数据字段权威性（`choose_one` 文本兜底）、37.0 新卡缺口 | [AUDIT_ENGINE_MECHANICS.md](AUDIT_ENGINE_MECHANICS.md) §3、[DATA_REBUILD.md](DATA_REBUILD.md) |

**归因顺序**：先判层 → 再跨层（跨层缺口必须写 `depends_on`，例如 "live 冻结未实现" 依赖 "env FREEZE 已支持"）。同一现象在不同层有缺口时，**拆成多条 gap**，不要合并成一条含糊项。

---

## 4. 单条 gap 闭环流程（≤25 分钟）

1. **取任务**：`team_task_list` → `team_task_get` → `claim`（见 MULTI_AGENT_RULES §3）。
2. **采集**：按 §1 收齐 I1–I4；live 证据不足就先跑一轮 `click_bot.py`（§7.4）。
3. **静态核对**：read 代码/数据/文档，拿到 `file:line` 或实测计数；不要凭印象。
4. **判层 + 定证据等级**（§3 / §2），写一句话「现象 → 期望 → 实际」。
5. **登记 gap**：按 §6 schema 写入对应台账（LIVE_TO_SIM_GAP.md 或审计文档），ID 唯一。
6. **定级**：按 §5 判 P0/P1/P2；P0 必须写影响面与 owner。
7. **复现**：跑 §7 的最小命令，把输出/路径写进 gap（E3 必需）。
8. **修复或转派**：在自己的写范围内改；跨层缺口转给对应 owner（handoff §9）。
9. **回归 + 收尾**：过 §8 门槛；标 `fixed`/`verified`；更新台账统计；发消息给 Lead。

**超时降级**：25 分钟内无法闭环 → 按 E2 记录 + 复现命令 + 卡点，转 handoff，不硬撑。

---

## 5. 分级与分类

### 5.1 category（与 `docs/schemas/live_gap.schema.json` 对齐）

`live_ui` | `env_action` | `observation` | `engine_rule` | `data_script` | `lifecycle`

> schema 的 enum 目前只有前四项 + `lifecycle`；`data_script` 为本协议新增分类。
> 写入 `docs/schemas/live_gap.schema.json` 前需 Lead 同意（该文件属根配置 scope）。

### 5.2 优先级判据

| 级别 | 判据（满足任一） | 反例（不应标此级） |
|---|---|---|
| **P0** | ① 真实交互在 bot/env 中无法表达（动作空间空洞）② 产生错误训练信号（空转、默认选 0、假观测）③ 崩溃/不可恢复卡死 ④ 与真实客户端结果不等价且高频 | "数据旧"（AGENTS §5 已知）、单纯的文档缺章节 |
| **P1** | 关键交互部分不可达、观测语义不完整、无回归测试、优先级中等的 live 稳定性 | 未复现的偶发 |
| **P2** | 语义/契约/边界/文档卫生/优先级最低的覆盖缺口 | 有 P0 影响面时不得降级 |

**并行上限**：同一时间全队 P0 修复不超过 3 条（Lead 控制）；超出时按「错误信号 > 动作空洞 > 崩溃」排序，其余进 P1 队列。

---

## 6. Gap 记录 schema

### 6.1 JSON（扩展自 `docs/schemas/live_gap.schema.json`）

```json
{
  "id": "L26",
  "operation": "board_reorder",
  "layer": "env_access",
  "category": "env_action",
  "priority": "P0",
  "evidence_level": "E3",
  "observed_at": "2026-10-22T23:20:00+08:00",
  "evidence": {
    "actions_jsonl": "runs/live/clickbot_every/actions.jsonl",
    "screenshot": "runs/live/clickbot_every/screenshots/actions/220022_a0692_drag_play_BG36_345.png",
    "state": "runs/live/clickbot_every/settled/turn_11.json",
    "action_note": "drag:board[2]->board[0]",
    "code_refs": ["hsbg/env/spec.py:68-86", "hsbg/env/driver.py:849-1027"],
    "repro": "python scripts/audit_env_coverage.py --games 20 --seed 7"
  },
  "expected": "board 顺序改变且 ZONE_POSITION 同步",
  "actual": "无 reorder 动作；env 只能通过 play position 间接决定站位",
  "depends_on": ["engine_public_move_api"],
  "related_ids": ["P0-1", "L20", "L05"],
  "owner": "env-builder",
  "status": "open",
  "fix_test": null,
  "verified_at": null,
  "notes": "优先级冲突见 AUDIT_CONSISTENCY.md C02"
}
```

**必填字段**：`id/operation/layer/category/priority/evidence_level/evidence/expected/actual/status/owner`。
**新增相对 schema 的字段**：`layer`、`evidence_level`、`depends_on`、`related_ids`、`fix_test`、`notes`。
（schema 允许 `additionalProperties: true`，可直接落盘；升级正式 schema 需 Lead 同意。）

### 6.2 Markdown 行（`LIVE_TO_SIM_GAP.md` 表格式）

```text
| L26 | 棋盘换位/重排 | 截图+actions；env 无动作 | 未实现 | 引擎无公开 reorder API | P0 | E3 | 复现命令 | env-builder |
```

列顺序建议固定为：`ID | 操作 | 证据 | bot 现状 | 模拟器现状 | 优先级 | 证据等级 | 复现 | owner/status`。
若现有表结构不同，**只追加列尾信息，不重排既有表**（减少 diff 冲突）。

### 6.3 ID 规则

| 前缀 | 归属台账 | 说明 |
|---|---|---|
| `L##` | `LIVE_TO_SIM_GAP.md` | live 可观测缺口（真实交互 ↔ bot/env） |
| `G-*` | `AUDIT_ENGINE_MECHANICS.md` | 引擎机制缺口（`G-R1`/`G-H1`/`G-C1`…） |
| `P0-*`/`P1-*`/`P2-*` | `AUDIT_ENV_ACTIONS.md` | env 覆盖缺口（历史命名，保号不改） |
| `AUD-<YYYYMMDD>-##` | 当轮审计临时项 | 轮内登记；收尾并入上表并保留 `related_ids` |

**禁止**同一缺口同时用两个编号长期存在；新增时填 `related_ids` 指向旧编号，收尾由 Lead 决定保留哪个。
跨文档映射见 [AUDIT_CONSISTENCY.md](AUDIT_CONSISTENCY.md) §4。

### 6.4 状态机

```text
open → triaged（已判层定级） → fixing（有人 claim） → fixed（有测试/最小修复） → verified（E4 复跑通过）
                                        ↘ wontfix（必须写理由 + Lead 同意）
```

- 任何状态变更必须附证据（测试名/命令输出/文档路径）；`wontfix` 必须写为什么不做。
- `fixed` 不等于 `verified`：前者有修复+测试，后者有真实/live 复跑。

---

## 7. 复现命令（Repro）

> 统一在 `C:\HSagent` 根目录执行；PowerShell。所有命令默认只读，除明确标注。

### 7.1 全量门禁（一键，推荐每 4h / 07:00）

```powershell
python scripts/verify_all.py                 # 全量：~4-5 分钟，exit 0 = 全绿
python scripts/verify_all.py --fast          # 快速：~1.5 分钟（跳过 smoke/bench/official_consistency）
python scripts/verify_all.py --json runs/verify_all.json
```

`verify_all` 依次执行：`engine_tests`、`project_tests`、`smoke_8p`、`env_validation`、`env_bench`、
`official_consistency`、`version_check`。任何一项失败 → exit 1，输出 `FAILED: <gate>`。

### 7.2 分项门禁

```powershell
python -m pytest hsrl2/tests -q                                   # 引擎回归
python -m pytest tests -q                                         # 项目新增测试
python tools/smoke_random_games.py --games 4 --seed 7             # 合入门槛：crashes=0
python tools/smoke_random_games.py --games 8 --seed 2000          # 深压
python scripts/validate_env.py --games 20 --json runs/env_validation.json
python tools/version_sync.py --check                              # 数据版本一致性
```

### 7.3 审计脚本（覆盖矩阵 / 对账）

```powershell
python scripts/audit_mechanism_coverage.py --out runs/audit/mechanism_coverage.json
python scripts/audit_env_coverage.py --games 20 --players 8 --seed 7 `
  --agent heuristic --json runs/audit/env_coverage.json          # 带门禁：失败 exit≠0
python scripts/audit_env_coverage.py --games 20 --seed 7 --no-gate --json runs/audit/env_coverage.json   # 只报告
```

### 7.4 Live 采集（写 `runs/live/**`，属可写产物）

```powershell
$run = "runs/live/audit_$(Get-Date -Format yyyyMMdd_HHmmss)"
python hsbg/live/click_bot.py --games 1 --max-seconds 900 --out-dir $run
# 复跑/对照时固定同一起始状态；采集结束立刻检查：
Get-Content "$run\actions.jsonl" | Select-String 'no_effect' | Measure-Object -Line
Get-ChildItem "$run\diagnostics" -ErrorAction SilentlyContinue | Select-Object Name
```

### 7.5 单点复现模板（写进 gap 的标准格式）

```powershell
# <gap-id> <一句话>
python -m pytest <test_file>::<test_name> -q
# 或（无测试时）
python -c "<最小复现脚本>"
# 或（live）
python hsbg/live/click_bot.py --games 1 --max-seconds 600 --out-dir runs/live/repro_<gap-id>
```

**注意**：部分 `scripts/*.py` 直接用 `python scripts/xxx.py` 时 `import hsbg` 会失败
（脚本目录在 `sys.path[0]`）。实测 `scripts/audit_value_data.py` 需要：

```powershell
python -m scripts.audit_value_data --help
```

审计命令统一优先用 `python -m scripts.<name>`；若脚本自己插入了根路径，两种写法都可以。

### 7.6 结果落盘

- 所有审计输出放 `runs/audit/<YYYYMMDD_HHMM>_<topic>/`（`runs/` 不入库）；
- gap 里引用相对路径；报告里同时给命令，保证他人可复跑；
- 命令失败时保留完整 stdout/stderr 到文件，不截断。

---

## 8. 回归门槛（Gate Matrix）

| 改动类型 | 必跑 | 可选/触发 | 通过标准 |
|---|---|---|---|
| **纯文档**（`docs/**`、`AGENTS.md`） | 链接/路径自检（见下） | — | 所有相对链接目标存在；不改代码/测试 |
| **Live**（`hsbg/live/**`、`tests/test_live_*`） | `python -m pytest tests -q`；live 冒烟 1 局 | 同局面复跑对照 | 无连续 3 次同类 `no_effect`；关键动作有截图+state |
| **Env**（`hsbg/env/**`、`tests/test_env_*`、`ENV_SPEC.md`） | `python -m pytest tests -q`；`validate_env.py`；确定性测试 | `audit_env_coverage.py` | 同 seed 两次 rollout 观测/动作序列一致；spec 版本同步 |
| **Engine**（`hsrl2/**`、`hsrl2/tests/**`） | `python -m pytest hsrl2/tests -q`；`pytest tests -q` | 定向批测 + `test_engine_fixes.py` | 引擎回归 0 failed；先写失败测试再改（AGENTS §1） |
| **数据/脚本**（`data/`、`hsrl2/scripts/**`、`tools/generate_bg_data.py`） | `pytest hsrl2/tests -q`；`audit_mechanism_coverage.py` | `audit_official_consistency.py` | 覆盖矩阵无「0 未知」项回退；数据版本一致 |
| **策略/训练**（`hsbg/policy`、`hsbg/train`） | `pytest tests -q`；短 PPO 冒烟 | 基准测试 | forward 形状/masked softmax 不含 NaN |
| **协议文档**（本文件、MULTI_AGENT_RULES、LIVE_AUTOMATION_PROTOCOL §10） | 与代码现状一致（抽查命令/路径） | — | 引用的文件/脚本/命令真实存在且可执行 |

**子命令**：

```powershell
# 文档链接自检（相对链接目标存在）
python -c "
import re, pathlib
root = pathlib.Path('.')
bad = []
for md in root.glob('docs/**/*.md'):
    txt = md.read_text(encoding='utf-8')
    for m in re.finditer(r'\[[^\]]*\]\(([^)#]+)(?:#[^)]*)?\)', txt):
        t = m.group(1).strip()
        if t.startswith(('http://','https://','mailto:')): continue
        if not (md.parent / t).exists() and not (root / t).exists():
            bad.append(f'{md}: {t}')
print('\n'.join(bad) if bad else 'links ok')
"
```

**门禁纪律**

1. 每次记录「命令 + 时间 + passed/failed/耗时」，**不要**在文档里引用历史数字当基线（本项目测试数与行数已漂移，实测见 AUDIT_CONSISTENCY §2）。
2. 已知红只允许 `xfail(reason="<gap-id>")`，并在 gap 表登记；不允许 `skip` 或删断言。
3. 改动 `hsbg/env/spec.py`（唯一契约）必须同步 `docs/ENV_SPEC.md` 并升 `Observation.version`。
4. 改动 `hsrl2/game.py`/`combat.py`/`queue.py`/`tags.py` 必须 Lead 事先批准（AGENTS §1）。
5. 合入前 baseline 变红（非本次改动引入）→ 停止修复，记录并通知 Lead，不得顺手改别人 scope。

**时间盒**：取证 ≤10 min → 修复 ≤20 min → 回归 ≤10 min；超时按 §4 降级交接。

---

## 9. 审计频率与 8h 节奏（Schedule）

| 周期 | 动作 | 负责人 | 产出 |
|---|---|---|---|
| 每 **30 min** | 状态快照（见 LIVE_AUTOMATION_PROTOCOL §10.7） | Lead（teammate 有变化时主动报） | 快照消息 / `runs/audit/<time>_snapshot.md` |
| 每 **2 h** | 重跑审计脚本（§7.3），刷新 gap 状态与覆盖矩阵 | 审计 owner | `runs/audit/...` + gap 表更新 |
| 每 **4 h** | 全量门禁 `verify_all.py` | Lead 指定 | `runs/verify_all.json` |
| 每局 live 结束 | 采集统计、更新 gap 表 §1 统计、检查 no-effect 率 | live owner | 本节产出 + gap 行 |
| 触发式 | 新 P0、gate 变红、数据/脚本合入、优先级重排 | 发现者 → Lead | 立即消息 + 台账更新 |
| **07:00** | 收尾全量门禁 + 最终报告（模板见 LIVE_AUTOMATION_PROTOCOL §10.8） | Lead | `docs/FINAL_REPORT` 或 `runs/audit/07_final_report.md` |

**轮次产物路径**

```text
runs/audit/<YYYYMMDD_HHMM>_<topic>/
├── inputs.md          # 本轮输入清单（run_id/截图数/actions 数/state 数）
├── findings.md        # 结论 + 证据等级 + file:line
├── repro/             # 复现命令输出
└── gate.txt           # 门禁命令与结果
```

**优先级刷新**：每 2h 由 Lead 重排一次 P0 队列；同一轮内 P0 队列不超过 3 条并行（§5.2）。

> 注：上文「LIVE_AUTOMATION_PROTOCOL §10.7/§10.8」指 Live 协作章节（30min 快照 / 07:00 报告）；
> 该章节合并前的内容见 [LIVE_COLLAB_SECTION.md](LIVE_COLLAB_SECTION.md)。

---

## 10. 报告与交接

### 10.1 单条审计结论模板

```text
[<gap-id>][<priority>][E<level>] <一句话>
现象：<live/env/engine 事实，含证据路径>
期望：<官方规则/契约/真实客户端行为>
根因：<file:line + 代码路径>（E3+）
影响：<训练信号/动作空间/真实交互>
复现：<命令>
建议：<最小修复 + 测试名>
```

### 10.2 交给修复方的 handoff（配合 MULTI_AGENT_RULES §6）

必须含：gap id、证据路径、复现命令、期望行为、建议最小 diff、写范围、验收测试、卡点与风险。
**只发消息不算交接**：要同时写进 gap 表状态 + 任务板。

---

## 11. 审计反模式（Anti-patterns）

| 反模式 | 后果 | 正确做法 |
|---|---|---|
| 只读代码就断言运行时行为 | 误报/漏报；修复方向错 | 至少跑到 E3 的实测命令；能跑测试就跑 |
| 用 live 截图推断引擎机制 | 层归因错误，转错 owner | 截图只证 live 现象；引擎结论要 file:line |
| 把"数据旧"当引擎 bug | 改错层、引入回归 | AGENTS §5；先看数据版本与 `version_sync` |
| "代码里没有 X" 但不给行号 | 无法复核 | 给 `file:line` 或 grep 命令 + 输出 |
| 跨 scope 顺手改/整文件格式化 | 覆盖别人改动、冲突 | 最小片段 + 先读 + 告知 owner |
| 同一缺口多个 ID | 台账重复、统计失真 | 新 ID 用 `related_ids` 关联；收尾统一 |
| E2 标 `verified` | 假完成 | 按 §2 分级，E4 才 verified |
| 审计产物不落盘 | 不可复现 | 输出到 `runs/audit/...` 并在 gap 引用 |

---

## 12. 附录：审计 checklist（复制使用）

```text
[ ] 输入齐全：截图 + actions.jsonl + state（+ diagnostics）
[ ] 现象可用一句话说清：动作 → 期望 → 实际
[ ] 已判层（live_ui / env_action / observation / engine_rule / data_script / lifecycle）
[ ] 有 file:line 或数据实测命令输出（E3）
[ ] 复现命令可跑通，输出已落盘
[ ] 优先级符合 §5.2 判据；P0 有影响面
[ ] gap ID 唯一，related_ids 已关联旧编号
[ ] 写范围符合 MULTI_AGENT_RULES §2
[ ] 回归门禁命令与结果已记录（§8）
[ ] 任务板状态更新 + 消息 Lead（四段格式）
```

---

## 相关文档

- 协作/任务板/消息：[MULTI_AGENT_RULES.md](MULTI_AGENT_RULES.md)
- Live 协作章节：[LIVE_COLLAB_SECTION.md](LIVE_COLLAB_SECTION.md)（Lead 合并后进入 LIVE_AUTOMATION_PROTOCOL §10）
- gap 台账：[LIVE_TO_SIM_GAP.md](LIVE_TO_SIM_GAP.md)
- 口径与冲突登记：[AUDIT_CONSISTENCY.md](AUDIT_CONSISTENCY.md)
- 环境契约：[ENV_SPEC.md](ENV_SPEC.md)
- 引擎 API：[ENGINE_API.md](ENGINE_API.md)
- 数据重建：[DATA_REBUILD.md](DATA_REBUILD.md)
