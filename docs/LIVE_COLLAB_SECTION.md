# Live 协作章节（待合并片段）

> **用途**：`docs/LIVE_AUTOMATION_PROTOCOL.md` 的 **§10 协作协议（持续开发）** 替换片段。
> **合并方式**（Lead）：
> 1. 用本文 `## 10` 起的正文替换原文件的 `## 10. 协作协议（持续开发）` 小节；
> 2. 保留原 §11「安全与隐私」、§12「快速命令」及其后文；
> 3. 合并后删除本文件，并在 `docs/LIVE_AUTOMATION_PROTOCOL.md` 文末链接
>    [AUDIT_PROTOCOL.md](AUDIT_PROTOCOL.md)、[MULTI_AGENT_RULES.md](MULTI_AGENT_RULES.md)、
>    [AUDIT_CONSISTENCY.md](AUDIT_CONSISTENCY.md)。
> **不改动**：§1–§9（范围/组件/run 目录/状态/动作/截图/动作矩阵/验证/生命周期）。
> **权威关系**：仓库级约定见 [AGENTS.md](../AGENTS.md)；跨角色协作/任务板规则见
> [MULTI_AGENT_RULES.md](MULTI_AGENT_RULES.md)（本文只写 live 场景下的落地细节）。

---

## 10. 协作协议（持续开发）

> 目标：让「真实客户端操作 → 采集 → 定位 → 热修 → 验证 → 反哺模拟器」在 8 小时自主轮内
> 可持续、可并行、可交接；任何人都能接手另一人的 run 与 gap。

### 10.1 角色与写入范围

| 角色 | 写入范围 | 主要职责 |
|---|---|---|
| **Lead** | `hsbg/env/spec.py`、`hsbg/paths.py`、`docs/`（仲裁）、`tests/test_integration.py`、`tests/test_live*`、`scripts/`、根配置、`git commit` | 决策、任务板、优先级、合入门禁、30min 快照、07:00 报告 |
| **live-automator** | `hsbg/live/**`、`tests/test_live_*.py`、`docs/LIVE_AUTOMATION_PROTOCOL.md` | 启动链、英雄选择、live 动作实现、真实对局复跑 |
| **live-gap-analyst / live-analyst** | `runs/live/analysis/**`（只读代码/截图/日志） | 从 `actions.jsonl` + 截图提炼 gap，登记到 `docs/LIVE_TO_SIM_GAP.md` |
| **env-builder / env-auditor** | `hsbg/env/**`、`tests/test_env_*.py`、`docs/ENV_SPEC.md`、`docs/AUDIT_ENV_ACTIONS.md` | env 动作/观测补齐与审计 |
| **engine-analyst / card-script-builder** | `hsrl2/scripts/**`、`hsrl2/tests/**`、`docs/ENGINE_*`、`docs/AUDIT_ENGINE_MECHANICS.md`；`hsrl2/game.py` 等核心需 Lead 批准 | 引擎机制/脚本覆盖 |
| **protocol-writer** | `docs/AUDIT_PROTOCOL.md`、`docs/MULTI_AGENT_RULES.md`、`docs/AUDIT_CONSISTENCY.md`、`AGENTS.md` | 协议/口径/一致性审查 |

规则：

- 同一文件同一时间**只有一个 writer**；同一目录不同文件可并行（详见 MULTI_AGENT_RULES §4）。
- 跨范围修改：先读文件 → 最小 diff → 在消息里明确告知 Lead 与原 owner，不得整文件重写/格式化。
- `hsbg/live/**` 的热修由 live-automator 做；牵涉 env/引擎的缺口**不在 live 内硬修**，转任务。

### 10.2 任务板（claim / complete）

live 相关任务一律走共享任务板（`team_task_list` / `team_task_get` / `team_task_update`）：

```text
pending → claim(expected_revision) → in_progress → complete
                     ↘ blocked（blocked_by 未完成时不得 claim）
```

- **claim 必带 revision**（CAS 乐观锁）；返回冲突说明别人先改了 → 重新 list/get 再决定。
- claim 前先看 `writeScopes` 与 `writeScopeWarnings`；与本任务写范围重叠时先问 Lead。
- 采集类任务（`live run`）必须在描述里写清：目标操作、`run_id` 前缀、最大时长、验收标准。
- **complete 条件**（缺一不可）：
  1. 验收标准逐条满足；
  2. 证据落盘：`runs/live/<run_id>/`（actions + 截图 + state），gap 表已更新；
  3. 回归门禁通过（§10.11）；
  4. 给 Lead 发完成消息（四段格式，MULTI_AGENT_RULES §5）。
- 发现任务范围外的问题：不顺手修，登记 gap + 消息 Lead（可新建任务由 Lead 决定）。
- 超过 30 分钟无进展 → release 任务并 handoff（§10.5）。

### 10.3 依赖与顺序

典型依赖链（`blocked_by` 表达硬依赖，软依赖用消息协商）：

```text
live 现象（截图/actions）
  → live_ui 缺口（live-automator 可自修）
  → env_action/observation 缺口（env-builder）
  → engine_rule 缺口（engine-analyst，核心改动需 Lead 批准）
  → data/script 缺口（card-script-builder）
```

- **live 动作实现前**先确认 env 侧语义（`hsbg/env/spec.py` 的 `ActionKind`/目标字段），
  live 只负责「如何用鼠标表达 + 如何验证」（见 §7 动作矩阵与 AUDIT_LIVE_TO_SIM §1.2）。
- **引擎改动未合并前**，live 不得依赖新 API；可在 gap 标 `depends_on`。
- **同一 live 客户端只能有一个操作者**：launcher/click_bot 会抢前台与鼠标，多个 agent 同时跑会互相破坏证据。
  需要并行分析时，只读方读已有 run 目录，不启动 bot。
- 优先级由 Lead 每 2h 刷新；P0 并行不超过 3 条（AUDIT_PROTOCOL §5.2）。

### 10.4 热修循环（Hotfix Loop）

> 适用：单局/单动作失败、坐标漂移、状态滞后、弹层卡住等**live 层**问题。
> 不适用：引擎规则缺失、env 观测语义缺失（转任务，见 §10.3）。

```text
① 触发：no_effect / 连续失败 / 状态异常 / 对局卡死（有 screenshot + actions + state）
② 取证（≤10 min）：读 actions 上下文 + 失败截图 + 对应 state；必要时 _diagnostic_burst
③ 定位：live 坐标/时序/状态判定/状态机分支（给 file:line）
④ 最小修复：只改 hsbg/live 内的最小片段；不重排、不重构、不动 env/engine
⑤ 单点验证：同局面/同 seed 复跑 ≥1 局，确认该动作不再 no_effect
⑥ 回归：pytest tests -q（+ 涉及 env 时 pytest hsrl2/tests -q）
⑦ 文档：更新 gap 表（状态 fixed/verified + 复现命令）；协议有变同步 §7 动作矩阵
⑧ 交接：修复摘要 + 证据路径 + 剩余风险，消息 Lead / 相关 owner
```

热修纪律：

- 一次只修一个问题；同一文件连续热修 ≥3 次 → 停下来报告 Lead（可能应重写局部状态机）。
- 修复必须能被「复现命令」验证；只改坐标不做状态验证不算修好。
- 修复引入新失败 → 回滚该最小片段（不 `git reset` 别人的改动），记录到 gap 备注。
- 单个热修时间盒：≤20 min；超时降级为「E2 记录 + 交接」。

### 10.5 交接（Handoff）

**触发**：任务完成但有后续；超时/阻塞；Lead 重排；换人；live 客户端不可用。

**交接单模板**（消息 + 写进任务描述，二者缺一不可）：

```text
HANDOFF <task-id> <from> → <to|lead>
状态：done | partial | blocked
已完成：<1-3 条，含文件/行为>
未完成：<1-3 条，含卡点>
证据：<run_id / 截图 / actions 行 / file:line / gap id>
复现：<命令>
写范围：<下一步可以动哪些文件>
风险/坑：<坐标时效、窗口分辨率、账号/客户端状态、已知 flaky 测试>
下一步建议：<优先级 + 验收标准>
```

- 交接 = **任务板状态更新 + 消息 + 文档（gap/协议）更新** 三件套；只发消息不算交接。
- 接收方先 read 证据再动手；有疑问先问，不猜。
- live 交接必须说明：当前客户端状态（在大厅/对局/崩溃）、窗口分辨率/缩放、`run_id` 与最近一次成功动作。

### 10.6 冲突处理

| 冲突类型 | 处理 |
|---|---|
| **写冲突**（同一文件） | 立即停止写入；re-read 当前内容；谁先 claim/谁 owner 谁保留；用最小片段 rebase 自己的改动；必要时 Lead 裁决 |
| **结论冲突**（审计/机制判断不一致） | 以「可复现证据」为准：代码实测 > 测试结果 > 文档结论 > 口头；冲突登记到 `docs/AUDIT_CONSISTENCY.md` |
| **优先级冲突**（同一缺口 P0/P1/P2 不一致） | 按 AUDIT_PROTOCOL §5.2 判据重判；Lead 记录最终优先级 |
| **live 客户端冲突**（两个 agent 同时操作） | 只允许一个操作者；后来者停止并等待；任何情况下不得 kill 别人的 bot 进程 |
| **范围冲突**（必须跨 scope 修改） | 先读 + 最小片段 + 消息告知 Lead 与原 owner；核心文件（game.py 等）必须先获批 |

升级路径：发现者 → 涉及方 → Lead（裁决并记录）。**不允许**把冲突留在文档里不登记、也不允许静默覆盖别人改动。

### 10.7 每 30 分钟状态快照

- **Lead** 每 30 min 汇总一次；每个 teammate 在**有变化时**于窗口前发一条（无变化可发 `no change`）。
- 快照必须能回答：谁在做什么、卡在哪、证据在哪、下一步、是否阻塞别人。
- 落盘（可选但推荐）：`runs/live/analysis/snapshot_<HHMM>.md` 或 `runs/audit/<time>_snapshot.md`。

**模板**（≤15 行）：

```text
[30min 快照] <HH:MM>
轮次：<run_id / 阶段>
状态：<teammate: 进行中/阻塞/完成>（逐人一行，写正在做的 task-id）
live：最近 run=<run_id>，动作数=<N>，no_effect=<N>，未决非 no-effect 问题=<0/1>
gate：pytest hsrl2=<绿/红/未跑>，pytest tests=<绿/红/未跑>，smoke=<绿/红/未跑>
gap：新增 <N>，fixed <N>，verified <N>；P0 队列=<ids>
阻塞/风险：<1-3 条 + 需要谁>
下一步（下 30min）：<1-3 条>
```

### 10.8 07:00 最终报告模板

> 8h 自主轮收尾报告；同时满足 Lead 汇总与交接需求。落盘为 `runs/audit/07_final_report.md`
> （或 `docs/FINAL_REPORT_<YYYYMMDD>.md`，由 Lead 决定），并在消息里给摘要。

````markdown
# HSagent 8h 自主工作报告（<YYYY-MM-DD> 23:00 → 07:00）

## 1. 概览
- 轮次目标：<3 条以内>
- 总体结论：<达成/部分达成/未达成>；一句话原因
- 交付：代码 <N> 处 / 测试 <N> 个 / 文档 <N> 篇 / gap 修复 <N> 条

## 2. 验收指标
| 指标 | 轮初 | 轮末 | 目标 | 结论 |
|---|---:|---:|---:|---|
| pytest hsrl2/tests（passed/failed） | | | 0 failed | |
| pytest tests（passed/failed） | | | 0 failed | |
| smoke seed=7 crashes | | | 0 | |
| live 动作数 / no_effect 率 | | | ↓ | |
| P0 gap（open/fixed） | | | 0 open | |
| 审计覆盖项（机制/env/live） | | | 无 0-未知 | |

> 数字必须来自本轮命令输出（附 `runs/verify_all.json`），不引用历史常量。

## 3. Live 运行摘要
- run_id / 局数 / 时长 / 分辨率与缩放
- 动作分布（buy/play/cast/refresh/freeze/hero_power/end_turn/...）
- 失败与诊断：no_effect 次数、密集诊断次数、卡住点
- 新发现 gap（L 编号 + 截图路径）

## 4. Gap 台账变化
| ID | 优先级 | 状态变化 | 证据 | 负责 |
|---|---|---|---|---|
| | | open→fixed/verified | | |

## 5. 代码/文档变更
- `hsbg/live/**`：<文件:行 + 行为变化 + 测试>
- `hsbg/env/**`：<...>
- `hsrl2/**`：<... + Lead 批准记录 + ENGINE_NOTES>
- `docs/**`：<...>
- 未合入/草稿：<分支或文件 + 原因>

## 6. 门禁结果
```powershell
python scripts/verify_all.py --json runs/verify_all.json
# 结果：<N>/<N> gates passed，耗时 <T>s；FAILED=<...>
```

## 7. 残留问题与风险
| 项 | 类型 | 影响 | 建议下一步 | 证据 |
|---|---|---|---|---|

## 8. 交接对象
- 下一轮优先做的 3 件事：<task-id / gap-id + 验收>
- 需要 Lead 决策：<DECISION-REQUEST 列表>
- 可丢弃/回滚：<...>

## 9. 附件
- `runs/audit/...`、`runs/live/<run_id>/`、`runs/verify_all.json`、相关截图
````

### 10.9 相关协议

- 审计协议（证据等级/gap schema/回归门槛/审计频率）：[AUDIT_PROTOCOL.md](AUDIT_PROTOCOL.md)
- 多智能体协作规则（写范围/任务板/消息/handoff/超时/冲突/Lead 职责）：[MULTI_AGENT_RULES.md](MULTI_AGENT_RULES.md)
- 口径与冲突登记：[AUDIT_CONSISTENCY.md](AUDIT_CONSISTENCY.md)
- gap 台账：[LIVE_TO_SIM_GAP.md](LIVE_TO_SIM_GAP.md)
- 环境契约：[ENV_SPEC.md](ENV_SPEC.md)
- 数据重建：[DATA_REBUILD.md](DATA_REBUILD.md)
