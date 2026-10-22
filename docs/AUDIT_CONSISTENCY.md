# 审计一致性审查（AUDIT_CONSISTENCY）

> 审查对象：[AUDIT_LIVE_TO_SIM.md](AUDIT_LIVE_TO_SIM.md)（252 行）、
> [AUDIT_ENV_ACTIONS.md](AUDIT_ENV_ACTIONS.md)（518 行）、
> [AUDIT_ENGINE_MECHANICS.md](AUDIT_ENGINE_MECHANICS.md)（861 行），
> 及它们引用的 [LIVE_TO_SIM_GAP.md](LIVE_TO_SIM_GAP.md)、[ENV_SPEC.md](ENV_SPEC.md)、[ENGINE_API.md](ENGINE_API.md)。
> 审查方式：**只读**——文档全文/关键节通读 + `data/*.json` / `REGISTRY` / 数据脚本实测计数；
> 审查时间：2026-10-22 23:20（Asia/Shanghai）；当前工作树（其他 agent 正在并行修改代码，代码行号可能继续变化）。
>
> **结论先行**：三篇审计的「机制判断」大体互相印证（尤其引擎侧 G-* 与 env 侧 P0-*/P1-*），
> 但存在 **10 处一致性缺陷**：3 处优先级/口径冲突会直接影响 8h 排期（C01/C02/C03），
> 4 处过期常量/表述矛盾（C04/C07/C08），3 处跨文档编号缺映射（C10/M01）。
> 详见 §3 冲突清单、§4 映射表、§5 重复内容、§6 缺失项、§7 统一口径。
> 本文只登记问题与建议，不修改三篇审计正文（owner 各自修）。

---

## 1. 审查方法与边界

- 通读三篇审计的 TL;DR、机制总表、缺口总表、证据索引、附录清单；
- 对「数字类断言」做只读实测（`json` 计数、`REGISTRY` 覆盖、`CardDB` 派生池），命令见 §8；
- 对「file:line 类断言」抽查 `game.py`/`spec.py` 锚点是否仍有效；
- **未做**：运行 pytest/对局复跑（代码正在被其他 agent 修改，跑基线会互相干扰）；
  因此「测试覆盖/行为断言」只做文档间交叉核对，不重新裁决。
- 优先级以 [AUDIT_PROTOCOL.md](AUDIT_PROTOCOL.md) §5.2 判据为复核标准。

---

## 2. 实测基线（2026-10-22 23:20，只读）

| 项 | 实测值 | 命令/来源 | 三篇审计中的说法 |
|---|---:|---|---|
| BG 卡 def（含金色/令牌） | **3534** | `data/bg_cards.json` | 3534 ✅ 三篇一致 |
| 池内随从 | **273** | `bg_pool_minions.json` | 273 ✅ |
| 池内法术 | **76** | `bg_pool_spells.json` | 76 ✅ |
| 池内随从无 `REGISTRY` 脚本 | **13** | 见 §8 命令 | AUDIT_LIVE_TO_SIM:100 写 13 ✅ |
| 池内法术无脚本 | **4** | 同上 | AUDIT_LIVE_TO_SIM:101 写 4 ✅ |
| 英雄 / 英雄技能 def | **118 / 165** | `bg_summary.json` | 118/165 ✅ |
| Dark Gift 数据条数 | **47** | `bg_dark_gifts.json`、`CardDB.dark_gifts()` | ENGINE 47 ✅；**ENV:180/504 写 43 ❌**；ENGINE_API:1441 写 43 ❌ |
| 饰品 def / 商店可提供 / 无脚本 | **409 / 357 / 41** | `bg_summary.json`；`CardDB.trinket_offer_pool()` | ENGINE G-R1 写 409/357/41 ✅ |
| `REGISTRY` 脚本总数 | **1460** | `len(REGISTRY)` | ENGINE:8 写 1,460 ✅ |
| `choose_options` 脚本 | **15**（14 个标记 def + `BG31_893`） | `REGISTRY` 属性扫描 | ENGINE:838 写 15 ✅；AUDIT_LIVE_TO_SIM:90 写「14 个 def」✅（两者分母不同） |
| `choose_one` 标记 def / base id | **44 / 25** | 数据扫描 | ENGINE:83/§5.3 写 44/23 base ❓（base 口径不同，见 C03） |
| 标题含 "Choose One" 的 def / base | **50 / 30** | 朴素 `"Choose One" in text` | ENGINE:83 写「标题正则 38 def / 23 base」❓（口径未写明，无法复现） |
| `choose_one` 标记且池内 base | **15**（10 随从 + 5 法术） | 数据扫描 | 三篇写「池内真实 12 = 7 随从 + 5 法术」❓（差 3 张"提及型"，见 C03） |
| `hsrl2/tests` 测试函数 | **140 文件 / 4720 `def test_`** | 见 §8 | ENGINE:8 写 140/约 4,720 ✅；AGENTS:10/49（修复前）写「4164 passed」❌（见 C07） |
| `tests` 测试函数 | **48 文件 / 567 `def test_`** | 见 §8 | 文档未给基线 |
| `hsrl2/game.py` 行数 | **5698** | `python` 行数 | AGENTS:11 写 5204 ❌（见 C07）；审计引用的 5015/5156/5623 锚点仍有效 ✅ |

> 说明：✅ = 实测一致；❌ = 与实测冲突；❓ = 分母/口径未写明，无法直接判定对错（进入 C03）。
> 行号锚点抽查：`game.py:1126/1154/5015/5156/5623` 全部落在有效范围内且语义匹配（当前工作树）。

---

## 3. 冲突清单（C01–C10）

严重度：**S1** = 影响排期/结论可信度；**S2** = 影响交接/复现；**S3** = 文档卫生。

### C01（S1）同一能力「换位/重排」三套优先级

| 文档:行 | 内容 |
|---|---|
| `AUDIT_ENV_ACTIONS.md:393`（§3 表 7b） | 棋盘换位/重排 **❌ 不支持（P0）** |
| `AUDIT_ENV_ACTIONS.md:402`（P0-1）、`:434`（P0 测试） | 无换位动作为 **P0**，建议加 `move_minion` + `ActionKind.MOVE_MINION` |
| `AUDIT_LIVE_TO_SIM.md:113`、`:185` | 随从换位/重排完全不支持 **P0**；P0 清单 #6「env 补 move/reorder」 |
| `LIVE_TO_SIM_GAP.md:57`（L05） | 随从换位/重排 **P2**；建议「先记录 gap」 |
| `LIVE_TO_SIM_GAP.md:135`（L20） | env 无 move/reorder **P1** |

**冲突**：同一能力出现 P0 / P1 / P2 三个级别，且 L05 的建议（"先记录"）与 P0 结论相反。
**影响**：8h 排期无法确定是否投入 env+引擎改动；task-1 若按 P0 做，与 gap 台账 P2 矛盾。
**裁定建议**：按 AUDIT_PROTOCOL §5.2，属「训练动作空间空洞」→ **P0**；L05/L20 统一升 P0 并互相 `related_ids`；
L05 的"先记录 gap"改为"引擎无公开 API，先最小扩 API 再补 env 动作"。
**修复动作**：Lead 裁决 → 改 LIVE_TO_SIM_GAP L05/L20 优先级（1 行）；三篇审计保留各自层结论即可（ENV/LIVE 已 P0）。

### C02（S1）Dark Gift 数量 43 vs 47（过期常量）

| 文档:行 | 内容 |
|---|---|
| `AUDIT_ENV_ACTIONS.md:180` | 引 `ENGINE_API.md:331,1152,1441`（**43 个 gift**） |
| `AUDIT_ENV_ACTIONS.md:504` | `data/bg_dark_gifts.json`（**43 个 Dark Gift**） |
| `ENGINE_API.md:1441` | `db.dark_gifts() # 43 个 Dark Gift` |
| 实测 | `bg_dark_gifts.json` / `CardDB.dark_gifts()` = **47** |
| `AUDIT_ENGINE_MECHANICS.md` 全文 | **47 / 47 窗口 / 42 handler / 5 DEFERRED** ✅ |

**冲突**：env 审计与权威 API 文档使用过期数据（43），与数据文件/引擎审计（47）不符。
**影响**：Dark Gift 覆盖结论（47/47 有数据、42 handler）被错误引用；外部读者会以为缺 4 张。
**修复动作**：改 `AUDIT_ENV_ACTIONS.md:180,504` 与 `ENGINE_API.md:1441` 为 **47**，并注明「47 def / 42 handler / 5 DEFERRED」；
owner：env-auditor + Lead（ENGINE_API 属 Lead/engine-analyst scope）。
**复现**：`python -c "import json; print(len(json.load(open('data/bg_dark_gifts.json',encoding='utf-8'))))"` → 47。

### C03（S1）Choose One「44 def 分解」不可对账 + 14/15 混用

`AUDIT_ENGINE_MECHANICS.md:92-96` 的分解：

```text
44 标记 def = 14（引擎 choose_options：7 随从 + 7 金色）
            + 9（误报）
            + 5（池法术自建协议）
            + 10（base 卡无脚本）
→ 14+9+5+10 = 38，剩余 6 个 def 未说明
```

**交叉核对发现 4 个具体问题**：

1. **成员重叠**：`BG31_892` 同时出现在「9 个误报」（`:85`）和「5 张自建（含 BG31_892 由 batch_unfreeze 特判）」（`:157`）；
   真实分类应二选一（自建协议 = 真实抉择卡，不是误报）。
2. **成员重叠**：`BG31_329` 同时出现在「9 误报」（`:85`）与「10 个 base 无脚本」清单（`:96`）。
3. **base/def 混用**：`:96` 写「10 个 base 卡无脚本」，但其清单含 `BG30_117(+t/_Gt)` 与 `_G` 变体，**实际约 20 个 def / 10 个 base**；
   在 def 级分解中按 10 计，账自然对不上。
4. **口径不可复现**：`:83` 写「标题正则命中 38 def / 23 base」，未给正则与排除规则；
   实测朴素 `"Choose One" in text` = **50 def / 30 base**，flag base = **25**（与「标 25 base」一致）。
   另 `:48` 又写「真 23 base / 标 25 base」，与 `:83` 的「38 def / 23 base」并列出现，base 数含义前后不一致。

**下游放大**：`AUDIT_LIVE_TO_SIM.md:73,90,180,231` 与 `LIVE_TO_SIM_GAP.md:130`（L15）复制了
「引擎 14 / 自建 5 / 10 base 无脚本」三分裂口径，把「14 个 def」与「15 个脚本」混用；
读者无法判断缺口到底是 6 个还是 10 个 def。

**影响**：task-2/task-3 的 Choose One 工作量估算偏小（漏 6 个 def）；修复验收标准（"池内 12 实体全统一"）与 44/14/10 口径不匹配。
**修复动作**：由 engine-mech-auditor 输出**每 def 一行**的分类矩阵（列：`id | base_id | choose_one_flag | title_hit | in_pool | script_protocol(engine/self-built/none) | category`），
放进 `runs/audit/choose_one_matrix.json` 并在审计文档给「矩阵 → 汇总数字」的映射；
优先修 `9 误报` 与 `5 自建` 的成员重叠（BG31_892/BG31_329），再统一 def/base 表述。

### C04（S2）「引擎是否有换位 API」表述矛盾

| 文档:行 | 内容 |
|---|---|
| `AUDIT_ENV_ACTIONS.md:353` | **引擎侧也没有公开重排 API**：只有内部 `_update_positions`（`game.py:5124-5126`）与 Jandice 换位 |
| `AUDIT_ENV_ACTIONS.md:402` | 「引擎亦无公开 API」 |
| `AUDIT_LIVE_TO_SIM.md:80` | 「引擎有 `position`；env 无显式 move」 |
| `LIVE_TO_SIM_GAP.md:57,135` | 「引擎 `position` 参数存在」/「引擎有 `position`」 |

**冲突**：字面上「引擎有 position」与「引擎无公开 API」相反。
**实情**：`position` 只是 `play_minion(position=...)` 的**插入位置参数**，不是重排/移动 API；两者可同时成立。
**影响**：交接时容易误判"引擎已支持换位，只差 env 动作"，导致 task-1 走错路径。
**修复动作**：统一表述为「引擎仅有 play 时的 `position` 插入参数；**无公开 move/reorder API**（内部 `_update_positions` 不可直接调用）」，
改 `AUDIT_LIVE_TO_SIM.md:80`、`LIVE_TO_SIM_GAP.md:57,135` 措辞。

### C05（S2）三连奖励/发现：live 优先级 P0 vs P1

- `LIVE_TO_SIM_GAP.md:56`（L04）：三连奖励/发现确认 **P0**（"统一 choice 处理"）。
- `AUDIT_LIVE_TO_SIM.md:193`（P1 #3）：「饰品商店/三连奖励统一 `choice` 状态机」**P1**。
- `AUDIT_ENV_ACTIONS.md:388`（6a）：机制支持，缺测试/非暂停期自动结算 **P1**。
- `AUDIT_ENGINE_MECHANICS.md`（G-F1）：通用 Discover 只支持随从 **P2**。

**冲突**：L04 报 P0，AUDIT_LIVE_TO_SIM 报 P1。
**裁定建议**：机制已存在（三连/发现链路完备），live 侧是"部分实现 + 无回归"→ **P1**；
若真实对局出现"三连后卡住无法继续"再升 P0（需 live 证据，E2）。Lead 记录最终级别。

### C06（S2）法术实体 `CHOOSE_BOTH`：P1 vs 被合并进 P0

- `AUDIT_ENGINE_MECHANICS.md:140,777`（G-C3）：**P1**（脚本有 `_CombinedChooseOneProxy` 代理绕过）。
- `LIVE_TO_SIM_GAP.md:138`（L23）：把 `G-C1/C2/C3` 一起列 **P0**。

**冲突**：C3 在引擎审计是 P1，在 gap 台账被抬成 P0。
**裁定建议**：C1/C2 保持 P0；C3 保持 P1（有代理绕过，非静默零效果主因），或由 Lead 在 L23 备注「C3 为 P1，与 C1/C2 同批修复」。
避免同一行内混级。

### C07（S3）文档基线常量过期（非审计错误）

- `AGENTS.md:10`「4164 项测试全绿」、`:11`「game.py（5204 行）」、`:49`「当前 4164 passed」（**修复前**行号；本轮已改为「以本地 pytest 输出为准」）。
- 实测：`hsrl2/tests` 140 文件 / **4720** 个 `def test_`；`tests` 48 文件 / 567；`game.py` **5698** 行。
- `AUDIT_ENGINE_MECHANICS.md:8` 的「140 文件 / 约 4,720 个 test 函数」与实测一致 ✅。

**影响**：读者无法判断基线；"4164 passed" 与 4720 个 test 函数不可能同时是当前值（陈旧）。
**修复动作**：文档改为「命令 + 采集时间」，不写死数字；
`AGENTS.md` 由 protocol-writer 在本轮修正（已改为「以本地 pytest 输出为准」），其余审计文档建议同样处理。

### C08（S3）`ENV_SPEC.md` 内部版本不一致（ENV P2-7 仍存在）

- `docs/ENV_SPEC.md:38`：「`version` 协议版本（当前 **1**）」。
- `docs/ENV_SPEC.md:55`：「`Observation.version` = **2**」。
- 实测 `hsbg/env/spec.py`：Observation version = 2（ENV 审计 P2-7 已登记，未修复）。

**影响**：契约文档自相矛盾，新 agent 易按 v1 写观测。
**修复动作**：env owner 修文档（非本任务 scope）；修复前在 ENV_SPEC 顶部加一行「以 `spec.py` 为准，version=2」。

### C09（S3）跨层目标优先级缺依赖说明（不要求拉平）

- LIVE 侧目标选择 **P0**（`AUDIT_LIVE_TO_SIM.md:182`）；env 侧目标回退 **P1**（`AUDIT_ENV_ACTIONS.md:409-410`）；引擎侧 target 元数据 **P1/P2**（G-T1/G-T2）。
- 各层级别不同本身合理（live 稳定性 ≠ 引擎契约），但**文档没有写"跨层依赖"**，读者会以为互相矛盾。
**修复动作**：gap 增加 `depends_on`/`related_ids`（AUDIT_PROTOCOL §6.1 已定义字段）；
在 LIVE_TO_SIM_GAP L06/L25 备注依赖关系，无需拉平优先级。

### C10（S2）三套编号（G-* / P*-* / L##）缺映射

同一缺口在不同文档有三套编号，且没有一处给完整映射：

| 机制 | engine | env | live gap |
|---|---|---|---|
| 随从换位/重排 | （无 G 编号；结论"无公开 API"） | P0-1 | L05(P2) / L20(P1) |
| Dark Gift 配对 id 不可观测 | G-D6/G-D7（数据侧） | P0-2 | L17（live 侧） |
| EoT/淘汰/对手期自动结算 | （无） | P0-3 / P1-6 | **缺 L 编号**（见 M01） |
| Choose One 组合/双效/协议 | G-C1…G-C6 | P2-5（latent） | L15 / L23 |
| Choose One label 观测 | （无） | P1-4 | 缺 |
| 英雄技能无脚本（17/118） | G-H1/G-H2 | （相关：P1-3 身份） | L21 |
| 饰品 offer 未过滤（41/357） | G-R1/G-R2 | P2-3 | L22 |
| PendingChoice 契约 | G-P1/G-C7 | （无） | L24 |
| target 元数据/回退 | G-T1/G-T2/G-T3 | P1-1/P1-2 | L25 |
| 三连/发现/饰品测试 | G-F1/G-F2 | P1-5 | L04 |
| ACTIVATE 双触发/目标 | G-A1/G-A3 | P2-4 | L19 |
| `CHOICE_OPTION_MAX=5` | （无） | P2-2 | 缺 |

**修复动作**：本文件 §4 给出初版映射；后续在 gap 表中用 `related_ids` 落字段，收尾由 Lead 决定保留哪套编号（建议保留 G-*/P*-* 作为机制编号，L## 只用于 live 可观测项）。

---

## 4. 编号映射（初版，可直接抄进 gap 表 `related_ids`）

```text
L04  三连奖励/发现确认          ↔ env P1-5(测试) / engine G-F1, G-F2
L05  随从换位/重排(早期)        ↔ env P0-1 / L20（合并）
L06  目标法术稳定命中           ↔ env P1-1, P1-2 / engine G-T1, G-T2
L15  Choose One 三分裂          ↔ engine G-C1…G-C6 / env P2-5
L17  live Dark Gift 购买/三选一 ↔ env P0-2 / engine G-D1…G-D7
L19  live Activate              ↔ env P2-4 / engine G-A1, G-A3, G-A4
L20  env 无 move/reorder        ↔ env P0-1 / L05（合并）
L21  17 英雄主技能无脚本        ↔ engine G-H1, G-H2
L22  饰品 offer 未过 REGISTRY   ↔ engine G-R1, G-R2 / env P2-3
L23  Choose One 组合/双效       ↔ engine G-C1, G-C2, G-C3(P1)
L24  PendingChoice 不出队/幂等  ↔ engine G-P1, G-C7
L25  数据层无 target 元数据     ↔ engine G-T1
（建议新增）
L26  EoT/淘汰/对手期选择自动结算 ↔ env P0-3, P1-6
L27  CHOICE_OPTION_MAX=5 截断    ↔ env P2-2
L28  live 无冻结/结束回合        ↔ env FREEZE/END_TURN 已支持（live_ui）
```

---

## 5. 重复内容清单（D01–D08）

| ID | 重复位置 | 重复内容 | 建议 |
|---|---|---|---|
| **D01** | `AUDIT_LIVE_TO_SIM.md:106-122`（§3.3 表） | 与 `AUDIT_ENV_ACTIONS.md:397-426`（P0/P1/P2 表）同 8 项 | 以 ENV 审计为唯一源；LIVE 审计只留一句「详见 ENV 审计 + 差异项」 |
| **D02** | `AUDIT_LIVE_TO_SIM.md:124-139`（§3.4 表） | 与 `AUDIT_ENGINE_MECHANICS.md:20-33`（TL;DR）+ `:769-803`（缺口总表）同 9 项 | 以 ENGINE 审计为唯一源；LIVE 只链引用 |
| **D03** | `AUDIT_LIVE_TO_SIM.md:176-202`（§5 P0/P1/P2） | §3.3/§3.4 的第三份副本，且个别优先级不同（C05/C06） | 删除或改为"合成视图"并标注来源行 |
| **D04** | `LIVE_TO_SIM_GAP.md:124-140`（§6 L15–L25） | 前述审计结论的第四份副本（L15/L21–L25 均引审计文档） | 保留 gap 行但只写「结论 + 证据链接 + 优先级」；不复制分析 |
| **D05** | `LIVE_AUTOMATION_PROTOCOL.md:167-186`（§7 动作矩阵）、`LIVE_TO_SIM_GAP.md:11-36`（§1 动作分布）、`AUDIT_LIVE_TO_SIM.md:170-174`（§4.4 统计） | 三处「live 已实现/未实现」状态 | §7 动作为唯一源；gap §1 只留"最近 run 统计 + 日期"，审计文档引用 |
| **D06** | `AUDIT_LIVE_TO_SIM.md:237-244`（§9）、`AUDIT_ENGINE_MECHANICS.md:848-856`（§5.4）、`AUDIT_ENV_ACTIONS.md:447-449`（回归门槛）、`AGENTS.md:47-52`、`LIVE_AUTOMATION_PROTOCOL.md:254-264`（§12） | 复现命令/门槛 | 统一到 [AUDIT_PROTOCOL.md](AUDIT_PROTOCOL.md) §7/§8；各文档只留一行链接 |
| **D07** | `AGENTS.md:77-89`（§4）、`LIVE_COLLAB_SECTION.md`（§10.1）、本文对应规则 | 写范围表 | `AGENTS.md` §4 = 仓库级唯一源；LIVE 片段只列 live 相关角色并链引用 |
| **D08** | `AUDIT_ENV_ACTIONS.md:430-449`（测试建议）、`AUDIT_ENGINE_MECHANICS.md` 各缺口"验收"列 | 建议测试清单 | 保留各审计内（属于各自结论），不复制到协议文档；协议只管流程 |

> 重复本身不是错误（审计文档是快照），但**同一优先级写四份**会产生 C05/C06 这类漂移；
> 建议后续审计只维护「结论 + 唯一优先级」，细节留在原审计文档。

---

## 6. 缺失项（M01–M05）

| ID | 缺失 | 影响 | 建议 |
|---|---|---|---|
| **M01** | env P0-3「EoT/淘汰/对手期选择自动结算」没有对应 `L##` 编号 | live 复现该问题时无处登记，会重复分析 | 新增 `L26`，`related_ids=[P0-3,P1-6]` |
| **M02** | env P2-2「`CHOICE_OPTION_MAX=5`」、P2-3「trinket offer 不过滤买不起」、P1-3「双技能槽身份」无 live 编号 | live 遇到同类问题无法关联 | 按需建 L27/L28，或在 gap §6 加「env-only 缺口索引」 |
| **M03** | 三篇审计都没有「最后验证时间 + 复现命令 + 代码基线」字段 | 代码在变，读者无法判断结论是否过期（典型：C02 的 43） | 审计文档头部加 `last_verified` / `repro` / `baseline`（命令 + 时间） |
| **M04** | `AUDIT_LIVE_TO_SIM.md` §1–§2（架构/文档审计摘要）的 12 条"建议补文档"没有 owner/任务 | 建议悬空，不可能被执行 | Lead 转为任务或标 `wontfix`；优先级低（P2） |
| **M05** | 没有跨文档「优先级变更记录」 | 优先级被改编无痕迹（C01/C05/C06） | 在 `LIVE_TO_SIM_GAP.md` 顶部加「优先级变更日志（日期/ID/旧→新/理由/裁决人）」 |

---

## 7. 统一口径建议（供后续审计引用）

### 7.1 数字口径表

| 概念 | 唯一口径 | 实测值 | 禁止写法 |
|---|---|---:|---|
| 卡牌条目 | `data/bg_cards.json` 条目（含金色/令牌） | 3534 | 「卡牌数」混用池/非池 |
| 池内实体 | `bg_pool_minions.json` / `bg_pool_spells.json` | 273 / 76 | 「池内 12 实体」不写组成 |
| 英雄/技能 | `bg_summary.json` | 118 / 165 | — |
| 饰品 | def 409 / 商店可提供 357 / 无脚本 41 | 409/357/41 | 只写 357 不写分母 |
| Dark Gift | def 47 / handler 42 / DEFERRED 5 | 47 | **43（过期，见 C02）** |
| REGISTRY | `len(REGISTRY)` | 1460 | — |
| `choose_options` | **def 14**（7 随从×2）+ **脚本 15**（含 BG31_893）——必须写明分母 | 14/15 | 「引擎 14」与「脚本 15」混用 |
| `choose_one` 标记 | **def 44 / base 25**；池内分类见矩阵（C03） | 44/25 | 「真 23 base / 标 25 base」并列 |
| 测试基线 | `pytest` 输出 + 时间；函数数另记 | 4720 def / 140 文件 | 「4164 passed」当常量 |
| 行数 | Python 行数（`sum(1 for _ in open(...))`） | game.py 5698 | PowerShell 行数/旧值 |

### 7.2 优先级口径

- 判定以 [AUDIT_PROTOCOL.md](AUDIT_PROTOCOL.md) §5.2 为准；同一能力**只允许一个**最终级别，
  其他层的级别用「层内级别 + 依赖说明」表达（如 "env P0（依赖 engine P0）"）。
- 级别变更必须记入 gap 表「优先级变更日志」（M05）。

### 7.3 文档引用口径

- 引用数字必须带来源（文件/命令/时间）；引用行号必须标注「工作树快照（时间）」；
- 结论冲突先登 `AUDIT_CONSISTENCY.md`，再改文档，避免互相覆盖。

---

## 8. 附：复现命令（本次实测用）

```powershell
# 数据计数
python -c "import json; d=json.load(open('data/bg_summary.json',encoding='utf-8')); print(d['patch'], d['total_bg_cards'], d['heroes'], d['hero_powers'], d['trinkets'], d['dark_gifts'])"
python -c "import json; print(len(json.load(open('data/bg_dark_gifts.json',encoding='utf-8'))))"   # 47

# REGISTRY / 池覆盖 / 饰品 offer 池
python -c "
from hsrl2.db import CardDB
from hsrl2.scripts import REGISTRY
print('registry', len(REGISTRY))
db = CardDB.load('data')
pool = db.trinket_offer_pool()
print('trinket offer', len(pool), 'no-script', len([t for t in pool if t.id not in REGISTRY]))
print('dark gifts', len(db.dark_gifts()))
"

# choose_one / choose_options 口径
python -c "
import json
from hsrl2.scripts import REGISTRY
cards=json.load(open('data/bg_cards.json',encoding='utf-8'))
flag=[c['id'] for c in cards if c.get('choose_one')]
eng=[k for k,v in REGISTRY.items() if hasattr(v,'choose_options')]
print('flag defs', len(flag), 'base', len({i.rsplit('_G',1)[0] for i in flag}))
print('choose_options scripts', len(eng))
"

# 测试/行数基线
python -c "
import pathlib
for p in ['hsrl2/tests','tests']:
    fs=list(pathlib.Path(p).glob('test_*.py'))
    n=sum(sum(1 for l in f.read_text(encoding='utf-8').splitlines() if l.strip().startswith('def test_')) for f in fs)
    print(p, 'files', len(fs), 'test funcs', n)
print('game.py lines', sum(1 for _ in open('hsrl2/game.py',encoding='utf-8')))
"
```

---

## 9. 修复顺序建议（docs-only 部分可立即做）

| 顺序 | 项 | 动作 | 建议 owner | 时间 |
|---|---|---|---|---|
| 1 | C02 | 43 → 47（3 处） | env-auditor / Lead | 5 min |
| 2 | C07 | AGENTS 基线改「以本地运行为准」；审计文档不写死数字 | protocol-writer（AGENTS 已改） / 各审计 owner | 5 min |
| 3 | C01/C05/C06 | Lead 裁决最终优先级 + 写变更日志 | Lead | 10 min |
| 4 | C04 | 统一"无公开 reorder API"表述（3 处） | protocol-writer / live-gap-analyst | 10 min |
| 5 | C03 | 输出 choose_one 每 def 矩阵 + 修成员重叠 | engine-mech-auditor | 30–60 min |
| 6 | C10/M01–M05 | 补 related_ids/L26/优先级日志/审计头字段 | Lead + gap owner | 20 min |
| 7 | D01–D08 | 去重复：以审计文档为结论源、gap 为状态源 | docs owner | 后续轮次 |

---

## 10. 结论（3 个最影响 8h 工作的冲突）

1. **C01 换位/重排三套优先级（P0/P1/P2）**——8h 内是否投入 env+引擎改动无法决策，task-1 与 gap 台账直接矛盾。
2. **C02 Dark Gift 43 vs 47**——权威 `ENGINE_API.md` 与 env 审计引用过期数字，外部读者会误判覆盖缺口。
3. **C03 Choose One 44 def 分解不可对账（漏 6 def、成员重叠、14/15 混用）**——直接影响 task-2/task-3 工作量与验收标准。

> 其余（C04–C10、D/M 项）为交接/复现/文档卫生问题，不阻塞但建议在 07:00 报告前修掉 C04/C07/C08。

---

## 相关文档

- 审计方法/证据等级/gap schema：[AUDIT_PROTOCOL.md](AUDIT_PROTOCOL.md)
- 协作规则/写范围：[MULTI_AGENT_RULES.md](MULTI_AGENT_RULES.md)
- 三篇被审查审计：[AUDIT_LIVE_TO_SIM.md](AUDIT_LIVE_TO_SIM.md)、[AUDIT_ENV_ACTIONS.md](AUDIT_ENV_ACTIONS.md)、[AUDIT_ENGINE_MECHANICS.md](AUDIT_ENGINE_MECHANICS.md)
- gap 台账：[LIVE_TO_SIM_GAP.md](LIVE_TO_SIM_GAP.md)
- 环境契约：[ENV_SPEC.md](ENV_SPEC.md)、引擎 API：[ENGINE_API.md](ENGINE_API.md)
