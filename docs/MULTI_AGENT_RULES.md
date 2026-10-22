# 多智能体协作规则（Multi-Agent Rules）

> 适用场景：多 agent 共享同一工作目录 `C:\HSagent`、并行开发/审计（含 8 小时自主工作轮）。
> 权威关系：**仓库约定**见 [AGENTS.md](../AGENTS.md) → **协作/任务板/消息**见本文 →
> **单任务细节**见任务描述（`team_task_get`）。
> 配套：[AUDIT_PROTOCOL.md](AUDIT_PROTOCOL.md)（审计方法/证据/gap schema）、
> [LIVE_AUTOMATION_PROTOCOL.md](LIVE_AUTOMATION_PROTOCOL.md) §10（live 专项协作）。

---

## 0. 一句话规则

**一个文件同一时间只有一个 writer；一个任务同一时间只有一个 owner；没有证据的「完成」不算完成。**

---

## 1. 成员与角色

| 角色 | 职责 | 不做什么 | 主要写范围 |
|---|---|---|---|
| **Lead** | 拆任务、维护任务板、裁决冲突、批准跨 scope/核心改动、合入门禁、30min 快照、07:00 报告、唯一 `git commit` 权 | 不亲自承担全部实现；不绕过测试；不让两人同文件并行 | 根配置、`hsbg/env/spec.py`、`hsbg/paths.py`、`docs/`（仲裁）、`scripts/`、`git` |
| **protocol-writer** | 协议/审计文档、口径一致性审查、写范围与流程维护 | 不改代码、不 git commit、不碰别人占用的文档 | `docs/AUDIT_PROTOCOL.md`、`docs/MULTI_AGENT_RULES.md`、`docs/AUDIT_CONSISTENCY.md`、`docs/LIVE_COLLAB_SECTION.md`、`AGENTS.md` |
| **live-automator** | 启动链、英雄选择、live 动作实现、真实对局验证 | 不改 env/engine 核心；不同时开第二个 bot | `hsbg/live/**`、`tests/test_live_*.py`、`docs/LIVE_AUTOMATION_PROTOCOL.md` |
| **live-gap-analyst / live-analyst** | 从截图/`actions.jsonl` 提炼 live gap、复核证据 | 不写代码、不启动 bot 抢前台 | `runs/live/analysis/**`（只读代码/日志） |
| **env-builder / env-auditor** | env 动作/观测补齐与审计 | 不改引擎核心；不改 live | `hsbg/env/**`、`tests/test_env_*.py`、`docs/ENV_SPEC.md` 相关、`docs/AUDIT_ENV_ACTIONS.md` |
| **engine-analyst / card-script-builder** | 引擎机制、卡牌/技能脚本、引擎审计 | 不改 env/live；`game.py` 等核心需 Lead 批准 | `hsrl2/scripts/**`、`hsrl2/tests/test_batch_*`、`docs/ENGINE_*`、`docs/AUDIT_ENGINE_MECHANICS.md` |
| **policy-builder / bridge-analyst**（按轮次） | 策略/训练、真实对局桥 | 同上跨层规则 | `hsbg/policy|train`、`hsbg/bridge`、对应 tests |

- 角色名称与实例以 `team_task_list` 的 `ownerName` 为准；本轮成员变化时 **Lead 更新本表**。
- 一个 teammate 可以同时拥有多个任务，但**同一时间只做一条**（见 §3.4）。

---

## 2. 写范围（Write Scopes）

### 2.1 三条原则

1. **按层/目录划分**：代码目录按 owner 划分（§2.2）；`docs/` 按**文件**划分，
   「`docs/**` 可写」指的是「本任务列出的文档」，不是全部文档。
2. **共享文件只有 Lead 可改**：根配置、`AGENTS.md`、`hsbg/env/spec.py`、依赖清单、
   `git` 历史；其他 agent 需要改时走「Lead 授权 / 由 Lead 合并」。
3. **最小 diff**：能改 1 行不改 10 行；不做整文件格式化、不重排、不重命名他人文件。

### 2.2 写范围表（与 AGENTS §4 对齐）

| 路径 | 默认 owner | 备注 |
|---|---|---|
| `hsbg/env/spec.py`、`hsbg/paths.py` | Lead | 契约/路径；改字段 = 升 version + 同步 `docs/ENV_SPEC.md` |
| `hsbg/env/**` 其余 | env-builder | `tests/test_env_*.py` 同 |
| `hsbg/live/**` | live-automator | `tests/test_live_*.py` 同 |
| `hsbg/policy/**`、`hsbg/train/**` | policy-builder | `tests/test_policy_*.py`、`scripts/train_*.py` |
| `hsbg/agents/**` | env-builder | `tests/test_agents_*.py` |
| `hsbg/bridge/**` | bridge-analyst | `tools/powerlog_*.py`、`tests/test_bridge_*.py` |
| `hsrl2/scripts/**`、`hsrl2/tests/**` | card-script-builder / engine-analyst | 分批文件划分，避免同文件并行 |
| `hsrl2/game.py`、`combat.py`、`queue.py`、`tags.py` | Lead 批准后单人 | 先失败测试 → 改 → `hsrl2/tests` 全绿 → `ENGINE_NOTES.md` |
| `data/**`、`tools/generate_bg_data.py`、`tools/version_sync.py` | Lead 批准后单人 | 数据基线变更影响面大 |
| `docs/**` | 各自文档 owner | 见 §1；协议文档归 protocol-writer/Lead |
| `AGENTS.md`、根配置 | Lead | protocol-writer 仅在任务明确授权时改链接/写权限小节 |
| `runs/**` | 产物，谁跑谁写 | 不入库；不同 agent 用不同 `run_id`/子目录 |

### 2.3 写前自检（3 问）

1. 目标文件是否在我的写范围内？（task `writeScopes` + §2.2）
2. 是否有人在改它？（`team_task_list` 里其他 `in_progress` 任务的 `writeScopes` 是否重叠）
3. 是否存在更小的 diff？（edit 片段 vs 整文件 write）

### 2.4 跨 scope 修改

允许但必须：
1. 先 read 当前完整内容；
2. 只改最小片段，保留他人改动；
3. 完成后消息告知 **Lead + 原 owner**（写清文件、行范围、原因）；
4. 涉及 §2.2 的「Lead 批准类」文件，先拿批准再动手。

---

## 3. 任务板协议

### 3.1 工具与字段

`team_task_list` / `team_task_get` / `team_task_update`。
关键字段：`id`、`subject`、`description`（含验收标准）、`blocked_by`、
`writeScopes`、`ownerName`、`status`、`revision`。

### 3.2 生命周期

```text
（无）--create--> pending --claim--> in_progress --complete--> completed
                     |                    |
                     +--blocked_by 未完成--+（不可 claim）
                                        release --> pending（换 owner 由 Lead reassign）
```

- `pending` + `ready=true` 才可 claim；`blocked_by` 未全部完成时**不要** claim。
- 状态与事实一致：不能把部分完成标 `complete`；不能创建空任务刷进度。

### 3.3 claim / complete 规则

**claim**：

```text
team_task_get <id>   → 读最新 revision + writeScopes + blocked_by
team_task_update id=<id>, expected_revision=<rev>, action=claim
```

- 必须带 `expected_revision`（CAS）；失败 = 别人先改了 → 重新 get 后决策，**不要**覆盖。
- claim 前看 `writeScopeWarnings`：与本任务重叠 → 先问 Lead 或错峰。
- claim 成功后向 Lead 发一条消息：任务 id + 计划 + 预计产出。

**complete**：

- 验收标准逐条满足 + 证据（测试输出/文档路径/run_id）已给 Lead；
- 若仍有未完成项 → `release` 或保持 `in_progress` 并 handoff，不得 `complete`；
- 完成后更新相关文档/台账状态（gap 表、协议链接），避免「任务完成但台账没更新」。

### 3.4 并发上限

- 同一时间只做**一个** in_progress 任务（Lead 特殊指派除外）。
- 全队并行写同一目录可以，但**同一文件不行**；P0 并行修复不超过 3 条。
- 需要拆子任务：最多拆 1 层，子任务 `blocked_by` 指向父任务，写清 `writeScopes`；由 Lead 决定是否保留。

---

## 4. 并行写规则（禁止同一文件并行写）

### 4.1 硬规则

- **同一文件同一时间仅一个 writer**；同一目录不同文件可并行。
- 同一文件的不同段落**也算**冲突（文件级锁语义）。
- 代码生成器、格式化器、批量重写脚本均视为写操作，需独占并先告知。
- 不允许：`git checkout -- .`、`git reset --hard`、`git clean`、批量 `black/ruff --fix` 全仓、
  删除/移动他人文件、覆盖未读内容。

### 4.2 高冲突文件（默认错峰）

`AGENTS.md`、`docs/LIVE_AUTOMATION_PROTOCOL.md`、`docs/LIVE_TO_SIM_GAP.md`、
`docs/ENV_SPEC.md`、`hsbg/env/spec.py`、`hsrl2/game.py`、
`hsrl2/scripts/batches/batch_choose_one.py`、`hsrl2/scripts/batches/batch_misc.py`。

### 4.3 正确姿势

1. 写前 30 秒内重新 `read`（避免基于旧内容写）；
2. 用 `edit` 替换最小片段，不用整文件 `write`（除新建文件）；
3. 写完立即消息相关方（「我改了 X 文件 Y-Z 行」）；
4. 遇到 `FS_STALE_VERSION`：read 最新 → 把自己的意图 rebase 到新内容 → 重试；
   **不要**回退别人的内容。

---

## 5. 消息协议（Message Format）

### 5.1 何时发

| 时机 | 要求 |
|---|---|
| claim 任务后 | 1 条：任务 id + 计划 |
| 有实质进展 | 阶段完成/关键发现时发；不必逐步汇报 |
| 阻塞/需要决策 | **立即**发，写清卡点 + 需要谁做什么 |
| 发现跨 scope 风险/冲突 | 立即发（Lead + 相关 owner） |
| 完成 | 收尾消息：产出路径 + 验收证据 + 剩余风险 |
| 每 30min 快照窗口 | 有变化发四段；无变化发 `no change` 一行 |

### 5.2 四段格式（必须）

```text
[任务] task-N / 状态: doing | blocked | done | risk
[证据] 文件路径 / 命令 / file:line / 输出摘要
[结论] 1-3 条改动或发现（写清影响面）
[下一步] 谁做什么；需要 Lead 决策的写 DECISION-REQUEST: <问题 + 选项 + 建议>
```

### 5.3 纪律

- ≤15 行；同一主题合并；不刷屏；大段日志给**路径**不给粘贴。
- 结论必须能被证据支撑；不确定要标「待验证/E2」。
- 不给其他 teammate 直接下工作指令（跨角色协调经 Lead；技术讨论可以，改范围/优先级不行）。
- 不使用模糊词（「大概」「应该没问题」）替代证据；不说「完成」但没证据。

### 5.4 常用模板

```text
# 阻塞
[任务] task-3 / 状态: blocked
[证据] 运行 `python -m pytest hsrl2/tests -q` 失败：test_batch_choose_one.py::... 
[结论] 依赖的 choose_options 语义未合并（task-2 G-C1），继续会重复实现
[下一步] 等 task-2；DECISION-REQUEST: 是否先做不依赖组合协议的 10 个 base 脚本？

# 完成
[任务] task-1 / 状态: done
[证据] docs/AUDIT_PROTOCOL.md（新增）；`python -m pytest tests -q` 未跑（纯文档）；链接自检 links ok
[结论] 审计协议/协作规则/一致性审查 3 篇文档完成；发现 3 个协议冲突（见 AUDIT_CONSISTENCY C01-C03）
[下一步] Lead 合并 LIVE_COLLAB_SECTION；env 侧按 task-1 继续
```

---

## 6. Handoff 协议

### 6.1 触发条件

任务完成但有后续 / 超时或阻塞 / Lead 重排 / 换人 / 轮次结束。

### 6.2 交接单（必须四要素：任务板 + 消息 + 文档 + 证据）

```text
HANDOFF <task-id> <from> → <to|lead>
状态：done | partial | blocked
已完成：<1-3 条，含文件/行为>
未完成：<1-3 条，含卡点>
证据：<文件路径 / run_id / gap-id / file:line / 测试名>
复现：<命令>
写范围：<下一步允许改哪些文件>
风险/坑：<坐标时效、分辨率、账号状态、flaky 测试、并行冲突>
下一步建议：<优先级 + 验收标准>
```

### 6.3 规则

- 交接 = **任务板状态更新 + 消息 + 文档/台账更新** 三件套；只发消息不算交接。
- 接收方先 read 证据再动手；有疑问先问，不猜。
- 交接后原 owner 不再写同一批文件（除非 Lead 重新指派）。
- 轮次结束（07:00）必须给 Lead 一份可独立阅读的交接摘要（模板见 LIVE 协作章节 §10.8）。

---

## 7. 依赖与顺序

- **硬依赖**用任务板 `blocked_by` 表达，并在依赖完成后 `set_dependencies` 更新（CAS）。
- **软依赖**（文档引用、优先级、证据复用）用消息协商，必须写进任务描述的「依赖/风险」。
- 典型顺序：审计结论（E3）→ 失败测试 → 修复 → 回归 → gap `fixed/verified` → 文档同步。
- 引擎核心改动必须 **先 Lead 批准**，再进入实现（AGENTS §1）。
- 依赖方未完成时不得「先按猜测实现」；如必须并行，接口先约定并写进任务描述。
- 依赖关系变化（新增/解除）必须通知 Lead，避免别按旧顺序等待。

**本轮已知依赖示例**（随任务板变化）：

| 任务 | 依赖 | 说明 |
|---|---|---|
| env move/reorder（task-1） | 引擎公开 reorder API（需 Lead 批准 hsrl2 改动） | 引擎无公开 API 时先做只读 gap 记录 |
| 卡牌脚本（task-3） | 引擎 `choose_options` 组合协议（task-2） | 同写 `hsrl2/scripts` → 按 batches 文件划分 |
| live 新动作（task-4） | env 动作语义稳定（spec ActionKind） | live 不依赖未合并的 env API |
| 协议文档（task-5） | 无（只读现状） | 引用代码现状，不做行为断言 |

---

## 8. 超时 / 失败 / 异常处理

### 8.1 时间盒（8h 轮）

| 情况 | 阈值 | 动作 |
|---|---|---|
| 单步无进展 | 10 min | 自检路径/命令/权限；换方法或缩小范围 |
| 任务无实质进展 | 30 min | 发阻塞消息（§5.4）+ 快照说明；按 Lead 指示继续或 release |
| 任务硬超时 | 45–60 min | 降级交付（E2 记录 + 复现命令 + handoff），不得硬撑 |
| 门禁反复红 | 2 次 | 停止修复，隔离文件，报 Lead；禁止删测试/放宽断言 |
| live 连续 no-effect | 同回合 3 次 | 停止该局，保存 diagnostics，登记 gap |
| 工具/环境故障 | 即时 | 记录错误原文；能绕则绕；不能绕则报 Lead（不重复重试 >3 次） |

### 8.2 失败三态

1. **可重试**（网络/窗口/临时占用）→ 退避重试 ≤2 次，记录；
2. **方法错**（假设不成立）→ 停止，改方案，更新任务描述；
3. **需升级**（权限/决策/跨 scope）→ 立即报 Lead，附证据与选项。

### 8.3 崩溃/重启恢复

- 先 `team_task_list` 看任务板状态，再读最新文档/`runs/audit` 产物；
- 不重复跑已完成的 gate；重新 claim 前确认 owner 与 revision；
- 恢复后第一条消息说明「丢了什么、证据在哪、下一步」；
- `runs/` 产物是恢复锚点：所有关键证据必须落盘，不能只在会话上下文里。

### 8.4 禁止行为

假装完成、静默放弃、无限重试、kill 别人的进程、把失败归因别人而不给证据、
跨 scope「顺手修」、未记录就覆盖他人改动。

---

## 9. 冲突处理

### 9.1 冲突类型与处理

| 类型 | 判定 | 处理 |
|---|---|---|
| 写冲突 | 两方要改同一文件 | 先 claim/owner 优先；后来者停止，rebase 最小改动，必要时 Lead 裁决 |
| 结论冲突 | 审计/机制判断不一致 | 可复现证据优先：代码实测 > 测试 > 文档 > 口头；登记 `docs/AUDIT_CONSISTENCY.md` |
| 优先级冲突 | 同一 gap 多处 P0/P1/P2 不一致 | 按 AUDIT_PROTOCOL §5.2 重判；Lead 记录最终值 |
| scope 冲突 | 必须改别人范围才能完成 | 消息 Lead + 原 owner；Lead 授权后按最小 diff 执行 |
| 重复劳动 | 两方做同一件事 | 立即停下核对任务板；保留证据更完整的一方，另一方转审核/补充 |

### 9.2 裁决顺序

**代码/数据实测 > 测试结果 > 文档结论 > 口头/印象**。
旧文档与实测冲突时，以实测为准并**更新文档**（登记冲突，不留悬案）。

### 9.3 三条铁律

1. 不覆盖别人未提交的改动；
2. 不在别人 in_progress 的文件上「顺手改」；
3. 冲突必须登记（任务描述或 AUDIT_CONSISTENCY），不能只在消息里说过就忘。

---

## 10. Lead 汇总职责

1. **任务板**：拆任务、定 `writeScopes`、维护 `blocked_by`、reassign、控制并行（P0 ≤3）。
2. **决策记录**：`DECISION`（scope 变更、核心改动批准、优先级重排）写进任务描述或文档；
   决策必须含「结论 + 理由 + 影响文件」。
3. **每 30min 快照**：汇总状态/证据/阻塞/下一步；无变化也留一行（LIVE 协作章节 §10.7）。
4. **冲突裁决**：按 §9.2 顺序裁决并记录；维护「唯一权威源」。
5. **合入门禁**：只有 Lead 能宣布「门禁通过」；只有 Lead 执行 `git commit`（若授权）；
   合并前抽查 `git diff` 与测试结果。
6. **07:00 报告**：按 LIVE 协作章节 §10.8 模板产出；必须含 gate 实测结果、gap 变化、残留风险。
7. **不做**：替所有 teammate 读代码（抽样即可）、绕过测试、让两人同文件并行、把无证据结论写进报告。

---

## 11. 违规与纠正

| 违规 | 检测方式 | 处理 |
|---|---|---|
| 越 scope 写 | `git status`/文件归属 vs task `writeScopes` | 停止写入；Lead 确认；必要时回退该片段（保留他人改动） |
| 未登记 gap/冲突 | 台账缺失、消息无证据 | 补齐台账；重发四段消息 |
| 未过门禁即宣称完成 | 无测试输出/`verify_all` 结果 | 重新跑门禁；任务不得 complete |
| 假完成/静默放弃 | 任务板 vs 实际产物 | Lead reopen；记录一次 |
| 删除/覆盖他人改动 | 文件 diff 异常 | 立即恢复；责任人说明；重复发生由 Lead 调整分工 |
| 同时操作 live 客户端 | 前台/鼠标冲突、run 目录交错 | 立即停止非 owner；保留一份有效证据 |

纠正原则：**对事不对人、先止损再复盘、记录在案不重复**。

---

## 12. 附：消息模板速查

| 场景 | 模板 |
|---|---|
| claim | `[任务] task-N / 状态: doing / [计划] 1)…2)… / [预计] <time>` |
| 进展 | `[任务] task-N / 状态: doing / [证据] <path> / [结论] <1条> / [下一步] <1条>` |
| 阻塞 | 见 §5.4 阻塞模板（含 DECISION-REQUEST） |
| 完成 | 见 §5.4 完成模板（证据 + 验收 + 剩余风险） |
| 交接 | 见 §6.2 HANDOFF 模板 |
| 冲突 | `[冲突] 文件/结论 / 双方证据 / 我建议按 <规则> 处理 / 请 Lead 裁决` |
| 快照 | 见 LIVE 协作章节 §10.7 |

---

## 相关文档

- 审计协议：[AUDIT_PROTOCOL.md](AUDIT_PROTOCOL.md)
- Live 协作章节片段：[LIVE_COLLAB_SECTION.md](LIVE_COLLAB_SECTION.md)（待 Lead 合并进 `LIVE_AUTOMATION_PROTOCOL.md` §10；本文引用 §10.x 前以该片段为准）
- 口径与冲突：[AUDIT_CONSISTENCY.md](AUDIT_CONSISTENCY.md)
- 仓库约定：[AGENTS.md](../AGENTS.md)
- gap 台账：[LIVE_TO_SIM_GAP.md](LIVE_TO_SIM_GAP.md)
