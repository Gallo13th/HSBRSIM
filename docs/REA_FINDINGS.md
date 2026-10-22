# REA 逆向报告 — BobsBuddy 战斗算法 · 客户端常量 · 与 hsrl2 的分歧

> 生成：rea-operator，2026-10-18。配套产物在 `reversed/rea/`。
> 目标（全部只读）：`C:\Program Files (x86)\Hearthstone`（37.0.0.255130）、
> `%USERPROFILE%\AppData\Local\HearthstoneDeckTracker\app-1.53.0`。
> 详细逐条对比：`reversed/rea/bobsbuddy_vs_hsrl2.md`；BobsBuddy 算法与证据索引：
> `reversed/rea/bobsbuddy/README.md`；客户端常量：`reversed/rea/client_constants.json`。

---

## 1. TL;DR

1. **REA 跑通了**（`rea-agents 6.7.0` + 项目内便携 Node v24.13.0），托管静态分析 provider
   `rea-dotnet-static v1` 在 BobsBuddy.dll / HsMod.dll 上**完整可用**；对 23MB 的
   Assembly-CSharp.dll **成员级不可用**（REA 内部 metadata 64MiB 预算），但 artifact 级可用，
   类型级结论沿用既有 ilspycmd/Mono.Cecil 产物。REA **不做 C# 反编译**，方法体用 ilspycmd 补齐
   （这不算"REA 不可用"：REA 的定位是 metadata/CIL 证据，两者互补）。
2. **BobsBuddy 是极佳的参照实现**，其战斗算法已逐段取证。与本项目引擎对比得到
   **6 个 P0 级分歧**（复生属性、猛毒/剧毒时机、顺劈同组、伤害上限来源、死亡波次批处理、SoC 顺序）、
   4 个 P1、3 个 P2，以及 6 项一致（可作交叉验证）。
3. **伤害上限不是本地公式**：`input.DamageCap` 来自服务端 GameEntity tag
   `BACON_COMBAT_DAMAGE_CAP`(2089)，由 `BACON_COMBAT_DAMAGE_CAP_ENABLED`(3403) 门控。
   → **bridge 应从 Power.log 抓这两个 tag**，引擎已有 `_damage_cap_override` 注入点。
4. **客户端规则常量**：客户端只有 tag/枚举（GAME_TAG 1214 项），**没有**升级费用、金币、刷新概率表
   （DBF 的 Battlegrounds* 表全是外观类），进一步证实这些数值是服务端/协议驱动。
   与 `docs/OFFICIAL_EXACTNESS.md` 的既有结论一致：**客户端无战斗模拟器**（新增证据：
   `Assets.Global/BaconCombatStep` 只有 COPY_OPPONENT_BOARD / DETERMINE_WINNER 等表现步骤）。
5. **HsMod 无战棋自动化/模拟**：只有战斗表现加速、隐藏 Bob 台词、对手手牌数显示等 QoL。
6. **本轮未改引擎**（遵守 scope）。P0 修复建议与最小测试见 §5。

---

## 2. REA 可用性（A 任务）

### 2.1 环境

| 项 | 值 | 证据 |
|----|----|------|
| 系统 Node | v22.15.0（**不满足** REA 的 `^22.19 || ^24.11 || >=26`） | `node -v`；`rea-install/node_modules/rea-agents/package.json -> engines.node` |
| 便携 Node | **v24.13.0**，npm 11.6.2 | `reversed/rea/node/node.exe --version` |
| 安装位置 | `reversed/rea/node/`（解压自 nodejs.org/dist/v24.13.0/node-v24.13.0-win-x64.zip） | 本目录 |
| REA | **rea-agents 6.7.0**（`rea@6.7.0`） | `reversed/rea/rea-install/node_modules/rea-agents/package.json -> version` |
| 安装方式 | `npm install rea-agents@latest` 到 `reversed/rea/rea-install`（**未执行 `rea setup`**，不写任何 agent/MCP 配置） | 本目录 |
| provider | `rea-dotnet-static` v1（REA 托管静态分析） | `reversed/rea/rea_capabilities.txt` |

系统 Node 未改动（只在本 shell/脚本内 `PATH` 前置便携 Node），符合任务约束。

### 2.2 `rea --help`（原始命令与输出摘要）

```powershell
$env:PATH = "C:\HSagent\reversed\rea\node;$env:PATH"
C:\HSagent\reversed\rea\rea-install\node_modules\.bin\rea.cmd --help
# 等价的 npx 形式（首次验证时使用，已保存原始输出）：
npx -y rea-agents@latest --help      # -> reversed/rea/rea_help_raw.txt
```

输出摘要：`rea@6.7.0 — Reverse engineer anything from your terminal or agent.`
子命令 **160+**，与本项目相关的托管 .NET 能力：

| 子命令 | 作用 |
|--------|------|
| `inspect-managed-artifact <dll>` | PE/CLI 身份、metadata 表行数、assembly、references、资源；**sha256 锚定** |
| `inspect-managed-members <dll> --type <T>` | 指定类型的字段/方法/签名/CIL 锚点/调用边/字段访问/`ldstr` 字符串 |
| `inspect-managed-native-boundaries` | P/Invoke 边界声明 |
| `project-managed-application-graph` / `compare-managed-members` | 应用图/跨版本成员比对 |
| `decompile` | **原生**函数（Hopper/Ghidra/IDA）——不适用于托管 DLL |
| `doctor` / `capabilities` / `providers` | 就绪度/能力/提供者 |

`rea doctor`（节选，`--format` 默认 toon）：
```
healthy: false
  node: ok (24.13.0)
  host: ok (win32 x64)
  hopper/ghidra/ida-registration/jadx/kuna: missing_analysis_engine
  skill:identity / registration:{claude_code,codex,copilot_cli,cursor,dsh,vscode}: config_drift
```
说明：`healthy:false` 只反映**原生逆向引擎缺失**与**未做 MCP 注册**。
本项目目标是 .NET 托管程序集，`rea-dotnet-static` 是内置 provider，**不需要** Hopper/Ghidra/IDA，
也**不需要** `rea setup` → 因此没有修改任何 agent 配置。

### 2.3 实跑证据（原始命令 + 输出摘要）

#### (a) BobsBuddy.dll（1,282,560 bytes）

```powershell
rea inspect-managed-artifact "…\app-1.53.0\BobsBuddy.dll" --format json
# -> reversed/rea/bobsbuddy/rea_artifact.json
```
摘要：`sha256=26dd65ca3db6eb548b4d689def280d125fc6d63d7bb873955e1f58df19dd822a`；
`format=pe`, `architecture=x86`（machine=332），assembly `BobsBuddy 1.34.11.0`，metadata 表 23 类；
module `BobsBuddy.dll`；references = `BobsBuddy.Common 1.0.0.0`、`HearthDb 35.6.2.0`、`netstandard 2.0.0.0`；
嵌入式资源 `BobsBuddy.Embedded.KnownBaconCards.xml`（`data_length=438146`，
`data_sha256=f69072d052f50157…`）；`coverage.state=complete`。

```powershell
rea inspect-managed-members "…\BobsBuddy.dll" --type BobsBuddy.Simulation.Simulator --format json
# -> reversed/rea/bobsbuddy/rea_Simulator_members.json（1.8MB 原始证据）
```
摘要（实测）：`coverage.state=complete`；**99 方法 / 25 字段 / 787 member_refs / 2617 call_edges /
660 field_accesses / 57 个 ldstr 字符串**；provider `rea-dotnet-static v1`；`confidence=observed`；
`authority=shipped-artifact`。压缩摘要（方法名 + token + IL sha256）已落盘为
`reversed/rea/bobsbuddy/rea_simulator_methods.json`。
同一命令对 `BobsBuddy.Simulation.Minion`：**153 方法**、coverage complete
（见 `reversed/rea/bobsbuddy/rea_script_test/rea_summary.json`）。

#### (b) Assembly-CSharp.dll（23,114,752 bytes）

```powershell
rea inspect-managed-artifact "…\Hearthstone_Data\Managed\Assembly-CSharp.dll" --format json
# -> reversed/rea/client_official/rea_artifact.json  => OK：sha256=786376bddad54470…, references=75, coverage=complete

rea inspect-managed-members "…\Assembly-CSharp.dll" --type TB_BaconShop --format json
# -> reversed/rea/client_official/rea_summary.json
#    coverage.state = "unavailable"
#    issue: { code: "resource-limit", scope: "metadata.representation", offset: 9990872,
#             detail: "Managed metadata exceeds the 67108864 byte representation budget" }
#    limitations: ["The CLI metadata could not be admitted; managed member inspection is unavailable."]
```
→ **精确的不可用原因**：REA 把 CLI metadata 展开为内部表示时超过 **64MiB** 预算（在 offset 9,990,872 处）。
这不是权限/网络/license 问题，也不是 provider 缺失，而是**实现上限**。
替代覆盖：仓库已有 `reversed/net/`（ilspycmd + Mono.Cecil：14,390 类型 / 113,222 方法 / 893 枚举），
本轮用 `ilspycmd -t` 定点补齐（如 `Assets.Global`、`TB_BaconShop`）。
建议：**大程序集用 ilspycmd/Mono.Cecil，小/中程序集用 REA**（REA 的调用边与字段访问图更强）。

#### (c) HsMod.dll（745,984 bytes）

```powershell
rea inspect-managed-artifact "…\BepInEx\plugins\HsMod.dll" --format json
# -> reversed/rea/hsmod/artifact.json
# sha256=6b3f26b7b8eee7f3…, assembly=HsMod 4.1.0.0, references=20, metadata=complete, coverage=complete
```

### 2.4 REA 的定位与限制（如实记录）

| 项 | 状态 |
|----|------|
| 原生二进制（Hopper/Ghidra/IDA/jadx/Kuna） | **缺失**（`doctor`: `missing_analysis_engine`）。本项目 .NET 目标不需要 |
| MCP/agent 注册 | 未做（`config_drift`），且**故意不做**（任务约束：不改 DSH/Claude 配置） |
| 托管 C# 反编译 | **不支持**（provider 自述 "never loads the target assembly, resolves dependencies through a CLR, decompiles C#, or executes target code"）→ 用 ilspycmd 补 |
| Assembly-CSharp 成员级 | **不可用**（resource-limit，64MiB metadata 预算） |
| SQLite inspector | 需要 Node ≥24.15（本机 24.13.0）——本项目未用到 |
| 网络 | 正常（nodejs.org / npm registry 均可达，用于装 Node 与 REA） |
| license/provider key | 不需要 |

---

## 3. BobsBuddy 战斗算法要点（B 任务 1）

> 完整证据与行号见 `reversed/rea/bobsbuddy/README.md`；下文 `BB:` = 反编译文件行号，
> `INV:` = `reversed/rea/hdt_bobsbuddy/BobsBuddyInvoker.cs` 行号。

### 3.1 它是什么

`BobsBuddy, Version=1.34.11.0`（1817 类型/5991 方法）：**纯战斗模拟库**。
HDT 负责读真实对局状态（HearthDb + 内存/Power.log）构造 `Input`，BobsBuddy 克隆棋盘跑
**10000 场 Monte Carlo**（`INV:46`、`INV:1171`，线程数 = CPU/2，单线程 1500ms 超时），
输出胜/平/负率、lethal 率、平均/中位伤害（`Output`，BB:10284-10399）。
遇到未实现交互会抛 `UnsupportedInteractionException` 并整体放弃该次预测（**不静默近似**）。

### 3.2 攻击轮转

- `Fight()`：最多 500 次 `OneRound`，任一方棋盘空（`eitherSideWon`）或双方无有效攻击者
  （`noValidAttackers`）则停（BB:6891-6905）。
- `OneRound()`：`CheckForStealth()` → 若当前方无有效攻击者则换边（双方都无 → 返回=僵局）→
  取该方**最左未攻击过**的有效攻击者 → `AttackWithMinion` → 置 `hasAttacked` → 换边（BB:7043-7098）。
  该方全部攻击过则整方重置 `hasAttacked` 重新从头（= 轮转，不是"每场一次"）。
- 有效攻击者 = 存活 && 攻击力>0 && 未被禁止攻击（BB:755-762）。

### 3.3 单次攻击（`PerformAttack` BB:6457-6600）

顺序：选目标 → 失去潜行触发 → Rally 计数（1 + 光环/任务奖励）→ 攻击时奥秘 →
"友方攻击时"触发 → 攻击者 `IOnAttack` → `IOnRally` → 被攻击者 `OnIsAttacked` / "友方被攻击" →
**resolve 触发并结死** → 若目标仍存活，构造**同一个伤害组**：
`[攻击力→目标] + (顺劈? 左右邻居) + (非"攻击时免疫"? [目标攻击力→攻击者])` → `ProcessDamage(组)` →
`OnAfterAttack` / `OnWasAttacked` 等触发注册（由外层 resolve）。

**风怒/超级风怒**：`AttackWithMinion` 循环 `num2 = mega?4 : windfury?2 : 1` 次，每次**重新选目标**，
每次之后 resolve 触发+死亡+复生，再跑双方 `OnAfterAttackStep`（BB:6402-6450）。

### 3.4 伤害结算（`ProcessDamage` BB:7470-7591）

对组内每个条目：0 伤害跳过 → 圣盾全额吸收（并立即跑破盾触发）→ 防伤效果 →
`overkill = max(0, amount - health)` → `baseHealth -= amount` → 记录"受到伤害/造成伤害"触发 →
**剧毒/猛毒直接 `baseHealth = -10000`**（猛毒同时消耗；**不要求来源存活**）→ 死亡奥秘 →
"第 N 次受伤"触发 → 若扣血前存活且现在死亡 → `OnKilled` / `OnOverkill` → 记录英雄技能伤害触发。
**整组扣完血后才统一 resolve 所有记录触发**。

### 3.5 死亡 / 亡语 / 复生 / Avenge（BB:7128-7981）

```
do {
  ResolveDeaths()                  # 双方（先后随机）收集本波死者，注册亡语触发，跑 Avenge，登记复生，最后移除
  ResolveTriggersInCurrentScope()  # 统一跑亡语
  ResolveReborn()                  # 统一复生（若该实体还有未跑完亡语则延后）
} while (有变化)
```
- 同侧死亡排序：**战斗内召唤的随从排最后**（`orderby CreatedDuringCombat ? 1 : 0`，稳定）。
- 每个死者的顺序：`IDeathrattleAttacksImmediately` 特例 → 亡语注册（含 Titus/任务等**翻倍次数**）→
  **Avenge**（先英雄技能，再其他）→ **复生登记**（延迟）→ 死亡奥秘 → "友方死亡后"触发 → 手牌触发。
- Avenge：`AvengeCounter++`，`% requirement == 0` 触发；同批死亡的其他 Avenge 实体不参与本次计数。
- 复生：默认 `CloneAsVanilla()`（**丢弃 buff/enchantment**）→ 1 血 → 按卡牌 `RebornBehavior`
  决定是否保留 enchantments / 关键字（taunt/windfury/曾有圣盾）/ max 攻血。

### 3.6 召唤上限与效果顺序

- 召唤：`side.Count >= 7` → 失败（触发 `FailedToSummonNoSpace`）（BB:8857）。
- 召唤触发顺序：`OnMinionSummoned` → 友方 `IOnFriendlyMinionSummoned` → `IOnSummoned` →
  `OnMinionSummonedByFriendly` → `IAfterFriendlyMinionSummoned` → 攻击力倍增类（BB:8935-8992）。
- 战斗内召唤的随从 `CreatedDuringCombat=true`（影响死亡排序；BB:8929-8932）。

### 3.7 开局战斗效果（SoC）顺序（BB:8265-8524）

`OnCombatStartSetup`（先 player 侧全部实体，再 opponent）→ **Anomaly** → **任务奖励** → **饰品** →
**英雄技能** → **Objectives** → **手牌**（仅 `ISummonFromHand`）→ 奥秘检查 →
**随从两侧交替**（先"棋盘大"的一侧；平则随机）。SoC 结算完再决定**先攻**（随从多者先，平随机）。

### 3.8 伤害上限（BB:6982-7041 + INV:652-655）

```
num = Σ(我方存活 tier) - Σ(对方存活 tier)
num += (num>0 ? 我方 tavern tier : num<0 ? -对方 tavern tier : 0)
if (DamageCap > 0) num = clamp(num, -DamageCap, +DamageCap)
num += 对方战前掉血 / num -= 我方战前掉血
```
`DamageCap` 来自服务端 tag（见 §2/§6），**不是**本地 turn 表。

### 3.9 随机分支如何采样

- **均匀分布**：`SafeRandom` 用 `System.Random.Next(min,max)`；列表随机 = 均匀下标（BB:1385-1452）。
- 默认种子 `Environment.TickCount + 每线程自增`；`ForceNextBaseSeed(seed)` 可复现（单测路径）。
- 概率 = 10000 次独立模拟的频率，**无加权/无重要性采样**。
- 每场模拟从克隆模板重建状态 → **战斗内 buff 每场自动清零**；输入棋盘的持久数值由 HDT 读取。

---

## 4. 与 hsrl2 战斗引擎的对比（B 任务 1 的下半）

> 逐条详细版（含代码/行号/最小测试建议）：**`reversed/rea/bobsbuddy_vs_hsrl2.md`**。
> 引擎位置：`hsrl2/combat.py`（CB）、`hsrl2/game.py`（GM）、`hsrl2/minion.py`（MN）、
> `hsrl2/constants.py`（C）。

### 4.1 P0（会改变胜负/伤害，建议优先修）

| # | 分歧 | BobsBuddy | hsrl2 | 证据 |
|---|------|-----------|-------|------|
| P0-1 | **复生属性** | `CloneAsVanilla()`：丢 buff/金色加成，1 血，仅按 `RebornBehavior` 保留关键字 | 同一实体放回，**保留 buff/金色/关键词** | BB:934-983 / GM:2543-2565 |
| P0-2 | **猛毒/剧毒时机** | 扣血阶段 `baseHealth=-10000`，**不要求攻击者存活**，与普通伤害同波 | 双向伤害+第一波死亡结算**之后**才判，猛毒要求 `not attacker.dead` | BB:7533-7548 / CB:307-337 |
| P0-3 | **顺劈同组** | 顺劈与主目标/反击同一伤害组，**攻击者被反击打死也生效** | `if attacker.cleave and not attacker.dead` → 攻击者死则顺劈丢失 | BB:6552-6581 / CB:295-304 |
| P0-4 | **伤害上限来源** | 服务端 tag 2089（3403 门控） | 本地 turn 表 5/10/15，存活≤4 取消 | INV:652-655 / C:42-57 |
| P0-5 | **死亡波次批处理** | 整批：收集 → 全部亡语 → 全部复生；战斗内召唤物排最后死；双方先后随机 | 逐随从：离场→亡语→**立刻复生**→Avenge；固定顺序；无 CreatedDuringCombat 排序 | BB:7128-7757 / GM:2438-2590 |
| P0-6 | **SoC 顺序** | Anomaly→任务奖励→饰品→英雄技能→Objectives→手牌→随从（**两侧交替**）；先手侧=棋盘大者/平随机 | 饰品→任务奖励→随从→手牌→英雄技能；固定 `a` 侧全跑完再 `b` | BB:8265-8524 / CB:129-156 |

### 4.2 P1（可观测差异，建议排期）

| # | 分歧 | 说明 | 证据 |
|---|------|------|------|
| P1-1 | **Mega-Windfury 缺失** | 引擎有 `GameTag.MEGA_WINDFURY=826`，但 `combat.py` 只判 `windfury`（2 次）；BobsBuddy 支持 4 次 | BB:6408-6414, 6608 / CB:232-236 |
| P1-2 | **伤害组同时性** | BobsBuddy 同组全部先扣血再统一触发；引擎逐条扣血+触发（"受到伤害"监听的中间状态/顺序不同） | BB:7470-7591 / CB:281-304 |
| P1-3 | **Avenge 同波死者** | BobsBuddy 排除整批死者并先算英雄技能；引擎只排除当前死者，且**复生后**再算 Avenge（复生体可能获得计数） | BB:7635/7714-7720 / GM:2577-2590 |
| P1-4 | **死亡侧顺序随机化** | BobsBuddy 随机决定先算哪一侧（作者对"同时死亡"的建模）；引擎固定。**不建议照抄**（引擎需确定性，AGENTS §3），但应记录为已知不确定点 | BB:7626-7632 / GM:2443 |

### 4.3 P2（语义/边角）

| # | 分歧 | 说明 | 证据 |
|---|------|------|------|
| P2-1 | 潜行规则 | BobsBuddy 每轮 `CheckForStealth`（0 攻潜行失潜行；全员潜行→全部解除）；引擎仅"潜行不可被选为目标" | BB:7108-7126 / CB:253 |
| P2-2 | 平局伤害 | BobsBuddy 对僵局仍算 Σtier 差（统计用途）；引擎平局=0（更贴规则，**不建议改**） | BB:7002-7031 / GM:3499-3504 |
| P2-3 | 攻击前死亡结算时点 | 净效果相同（目标已死则 0 伤害），仅亡语 resolve 时点不同 | BB:6550-6581 / CB:272-284, MN:166 |

### 4.4 一致项（可作交叉验证，说明引擎主干正确）

- 目标选择：嘲讽强制优先、多嘲讽**均匀随机**、潜行不可被攻击（BB:1051 / CB:251-258）。
- 先攻：随从多者先、平随机（BB:8464-8491 / CB:160-166）。
- 风怒同一轮连续两次、第 2 次**重新选目标**（BB:6402-6450 / CB:232-236）。
- 攻击轮转：双方交替、左侧优先、一方空即结束、风怒同轮连击（BB:7043 / CB:177-238）。
- 召唤上限 7（BB:8857）。
- 随机采样分布均匀（BB:1385-1452）——BobsBuddy 是 Monte Carlo，引擎是单次确定性采样，
  用途不同（RL 必须确定性，当前做法正确）。
- 伤害公式主体：`胜方 tavern tier + Σ存活随从 tier`（BB:7002-7019 / GM:3499-3504）。

### 4.5 "我们缺实现"清单

1. Mega-Windfury（4 次攻击）。
2. 潜行轮转规则（`CheckForStealth`）。
3. 伤害组（damage group）语义——多目标同时扣血后再统一触发（当前仅顺劈/主目标逐条）。
4. `CreatedDuringCombat` 死亡排序。
5. `OnAfterAttackStep` 类钩子（攻击步骤结束后的双方扫描）。
6. Rally 次数修正器（如 `BG34_Giant_376` 光环）。

> 以上 4/5/6 是否在引擎别处已有等价实现需逐个确认（脚本层可能已覆盖），本轮只做战斗核心路径对比。

---

## 5. 建议修复与最小测试（**不要**直接改引擎；交 Lead 排期）

> 遵循 AGENTS.md：先在 `hsrl2/tests/` 或 `tests/test_engine_fixes.py` 写失败测试，再改核心文件。

### 5.1 优先级 1：猛毒/剧毒（P0-2）

- **建议**：把剧毒/猛毒判定移入 `take_damage` 或"伤害组"阶段，**不要求攻击者存活**；
  毒杀与普通伤害进**同一死亡波次**。
- **最小测试**：
  1. `1/1 Venomous` vs `5/5` 互殴 → 双方都死（当前：猛毒方死则对方活）。
  2. `1/1 Venomous` 攻击 `5/5` 且目标有圣盾 → 圣盾吸收，猛毒不消耗。
  3. 毒杀 + 普通死亡同回合 → Avenge 计数在**同一波**累加（构造 Avenge(3) + 2 名友方死亡）。

### 5.2 优先级 2：顺劈同组（P0-3）

- **建议**：顺劈伤害在攻击者反击死亡判定**之前**加入同一批伤害；或收集"本组伤害"后统一 apply。
- **最小测试**：`1/2 Cleave` 撞 `5/5`，两侧各 `1/1` → 两侧 1/1 死亡 + 攻击者死亡（当前：两侧存活）。

### 5.3 优先级 3：复生属性（P0-1）

- **建议**：默认复生 = 原版克隆（1 血、丢 buff/金色加成、关键字按规则），
  仅 `IRebornBehavior` 类卡牌保留；`Persisting Horror` 特例已有，可保留。
- **最小测试**：
  1. `3/3 Reborn` 被 buff 到 `5/5`，战死复生 → 断言复生体 `3/1`（当前 `5/1`）。
  2. 金色 Reborn 复生 → 断言是否非金色/原版（需先补 `CloneAsVanilla` 证据，见 §8）。
  3. 带圣盾 Reborn 默认不复生圣盾。
- ⚠️ 这是行为变更最大的修复，需 Lead 决策（可能影响 4164 项测试中的复生相关用例）。

### 5.4 优先级 4：伤害上限数据源（P0-4）

- **建议**：不改默认 turn 表（无 Power.log 时仍需要），但：
  1. `hsbg/bridge` 的 Power.log 解析新增 GameEntity `tag=2089/3403` 提取（存数据资产）；
  2. 引擎侧用 `_damage_cap_override`（GM:3139-3140 已存在）注入实测值；
  3. 文档标注 turn 表是 fallback。
- **最小测试**：构造 `game._damage_cap_override = 10` 且 turn=9/alive=6 → 断言伤害被钳到 10。

### 5.5 优先级 5：死亡波次批处理与 SoC 顺序（P0-5/P0-6）

- 死亡批处理改动风险高（亡语/复生/Avenge 全受影响），建议**先补测试固化现状**，再分小步改：
  1. 一批死者中 A 的亡语看到 B 是否已离场；
  2. 复生体是否被同波亡语 buff；
  3. 同波死者 Avenge 计数。
- SoC 顺序：把"任务奖励先于饰品"与"两侧交替"两个子项分别做（可先只改类别顺序，风险低）。

### 5.6 优先级 6：Mega-Windfury（P1-1）

- **建议**：`_attack_loop` 的风怒分支改为 `times = 4 if mega else 2 if windfury else 1`，每次重新选目标；
  `MEGA_WINDFURY` tag 已在 `hsrl2/tags.py:139`。
- **最小测试**：Mega-Windfury 1/1 连打 4 次（第 4 次应有攻击；当前只有 2 次）。

---

## 6. 客户端规则常量（B 任务 2）

完整结构化产物：**`reversed/rea/client_constants.json`**（每项带类型/字段/证据路径与行号）。

### 6.1 客户端是否有战斗预测/模拟类？→ **没有**（新增证据）

| 证据 | 内容 |
|------|------|
| 方法名扫描 | `Assembly-CSharp` 全程序集 `Simulate*` 仅 5 个，全部与战斗无关（网络断线模拟、SelectorWheel、任务模拟×2、收包模拟） |
| 类型名扫描 | `simulation` 关键词类型 **0** 个；`prediction` **0** 个；`combat` 15 个均为皮肤/UI/教程 |
| 客户端战斗步骤枚举 | `Assets.Global/BaconCombatStep` = `INVALID, COPY_OPPONENT_BOARD, END_OF_MINION_COMBAT, END_OF_COMBAT, DETERMINE_WINNER, PREPARE_COPY_BOARD, START_COMBAT_TRACKER`（`reversed/rea/client/Assets_Global.cs:478-487`）→ 客户端只**复制对手棋盘**并播放表现 |
| 战斗状态机 | `PowerTaskList` / `PowerProcessor` 由服务器驱动（`reversed/net/decompiled/PowerTaskList.cs`、`reversed/net/SUMMARY.md` §2.2） |
| REA | artifact 级确认 sha256/75 引用；成员级因 resource-limit 不可用（见 §2.3b） |

### 6.2 客户端可见的规则常量/枚举

| 常量 | 值 | 证据 |
|------|----|------|
| `BACON_COMBAT_DAMAGE_CAP` | **2089** | `reversed/net/key_enums.json -> game_tag.values` |
| `BACON_COMBAT_DAMAGE_CAP_ENABLED` | **3403** | 同上；消费点 `hdt_bobsbuddy/BobsBuddyInvoker.cs:652-655` |
| `FIRST_PLAYER` | 24 | 同上 |
| `PLAYER_TECH_LEVEL` / `TECH_LEVEL` | 1377 / 1440 | 同上 |
| `BACON_MAX_PLAYER_TECH_LEVEL` | 1494 | 同上（上限服务端下发） |
| 经济类 tag | `BACON_OVERRIDE_BG_COST=2437`、`BACON_REDUCE_BUY_COST=2438`、`BACON_FREE_REFRESH_COUNT=4536`、`BACON_PLAYER_EXTRA_GOLD_NEXT_TURN=4286`、`BACON_COSTS_HEALTH_TO_BUY=2911`、血宝石 1844/2827 | 同上 |
| `BaconCombatStep` / `BoardVisualState` | 见 §6.1 / `{NONE,SHOP,COMBAT}` | `reversed/rea/client/Assets_Global.cs:471-487` |

### 6.3 酒馆升级费用 / 每回合金币 / 刷新概率权重 → **客户端没有数值表**

- 客户端 DBF 中 Battlegrounds* 表只有：`BATTLEGROUNDS_BOARD_SKIN / EMOTE / FINISHER / GUIDE_SKIN /
  HERO_SKIN / LANDING / SEASON`（`reversed/net/decompiled/GameDbf.cs:47-59,567-591,1430`），
  **没有** `SHOP_COST` / `SHOP_ODDS` / `TAVERN_TIER` 之类表。
- `TB_BaconShop` 只有刷新按钮/升级按钮/Bob 台词等表现逻辑（`reversed/net/decompiled/TB_BaconShop.cs`）。
- → 升级费用曲线、每回合金币、刷新权重由**服务端**决定；客户端仅显示。
  工程侧继续用 `data/` + `hsdata/CardDefs.xml`，并用 Power.log 校准；**不要**期望从客户端程序集提取档位表。
- 同理：**伤害上限档位**也来自服务端 tag（§6.2），客户端没有 5/10/15 的表。

---

## 7. HsMod.dll 能力清单（B 任务 3，仅扫描不深挖）

`HsMod 4.1.0.0`，65 类型，BepInEx 5 (Harmony) 插件。REA artifact 完整
（`reversed/rea/hsmod/artifact.json`，sha256 `6b3f26b7…`），全量反编译见 `reversed/rea/hsmod/src/`。

| 类别 | 能力 | 证据 |
|------|------|------|
| 战棋表现加速 | `PatchBattlegrounds`：`IsQuickModeEnableValue` 时跳过 `AttackSpellController` / `DeathSpellController` / `TriggerSpellController` / `SubSpellController` / `SideQuestSpellController` 的 `OnProcessTaskList` 播放，并让 `GameState.IsUsingFastActorTriggers` 返回 true | `hsmod/src/HsMod.decompiled.cs` 中 `PatchBattlegrounds`（约 2439-2700 行）；`PatchGetBobActor`/`PatchPlayBobLineWithoutText`/`PatchHandleGameOverWithTiming` 隐藏 Bob 台词与动画 |
| 对手手牌数 | `PatchRealtimeCardNum`（`CollectionCardCount.UpdateVisibility`） | 同上 |
| 金卡显示 | `PatchGetPremiumType`（战棋也能显示金色） | 同上 |
| 对手信息 | `PlayerLeaderboardManager.SetNextOpponent / SetCurrentOpponent`、`BnetPlayer.GetBestName` | 同上 |
| 反上报/反断连 | `ExceptionReporter.*`、`InactivePlayerKicker`、`AlertPopup`、`keySimulateDisconnect` | 同上 |
| 其它 QoL | 分辨率/帧率、跳过开包动画、表情、乱斗、WebServer/WebPage 遥控 | 同上 |

**结论**：**没有**自动买怪/自动刷新/战斗预测/模拟/内存读取（无 `ReadProcessMemory`、无 HearthMirror 使用）。
它对"官方实现一致性"没有可利用信息——除了一个**有用事实**：客户端战斗动画由 `*SpellController`
播放，验证了"战斗由服务器 PowerTaskList 驱动、客户端只演出"。

---

## 8. 阻塞与未完成（如实记录）

1. **本机无 Power.log**：`C:\Program Files (x86)\Hearthstone\Logs` 不存在（游戏近期未运行）。
   → 无法实测验证 BobsBuddy 的分歧结论（尤其复生属性、猛毒时机）。
   **建议**：下次运行游戏并开启 Power.log 后，采集 10-20 场战斗日志，做 BobsBuddy/引擎/官方三方对比。
2. **BobsBuddy 部分行为未展开**：
   - `Minion.CloneAsVanilla()` 的确切实现（是否保留 golden、baseAttack 处理）——当前复生结论基于
     `OnReborn` 调用点；补证据方法：`ilspycmd -t BobsBuddy.Minion`（文件已含该类，行 366-1330）。
   - 特殊卡的 `ChooseAttackTarget` 覆写（BB:18702/18758/30297）。
3. **REA 成员级对 Assembly-CSharp 不可用**（64MiB metadata 预算）——已用 ilspycmd 全覆盖替代，
   但 REA 的 call_edges/field_accesses 图对大程序集缺失。
4. **HsMod 只做能力清单**（任务要求"不深挖"）。
5. **未修改引擎**（遵守 scope；P0 修复交 Lead）。
6. `reversed/rea/bobsbuddy/rea_script_test/` 是对脚本的冒烟测试输出，可删。
7. 待补：`hand_size`（手牌上限）与部分英雄技能数值未在本轮取证。

---

## 9. 复现与验收

```powershell
cd C:\HSagent

# 1) 便携 Node + REA
reversed\rea\node\node.exe --version                                  # v24.13.0
$env:PATH = "C:\HSagent\reversed\rea\node;$env:PATH"
reversed\rea\rea-install\node_modules\.bin\rea.cmd --help              # rea@6.7.0
# （等价 npx：npx -y rea-agents@latest --help）

# 2) 通用脚本：给定 dll -> REA -> JSON
pwsh tools\rea_analyze_dotnet.ps1 `
  -DllPath "$env:LOCALAPPDATA\HearthstoneDeckTracker\app-1.53.0\BobsBuddy.dll" `
  -OutDir "C:\HSagent\reversed\rea\bobsbuddy" `
  -Types "BobsBuddy.Simulation.Simulator","BobsBuddy.Simulation.Minion"

# 3) 证据目录
dir reversed\rea\bobsbuddy
dir reversed\rea\hdt_bobsbuddy
dir reversed\rea\client

# 4) 文档
notepad docs\REA_FINDINGS.md
notepad reversed\rea\bobsbuddy_vs_hsrl2.md
```

验收对照：

| 验收项 | 状态 | 证据 |
|--------|------|------|
| 便携 node ≥24 | ✅ v24.13.0 | `reversed/rea/node/node.exe --version` |
| REA 可用 | ✅ 6.7.0，托管 provider 完整 | `reversed/rea/rea_help_raw.txt`、`bobsbuddy/rea_artifact.json` |
| BobsBuddy 分析产物有证据 | ✅ 全量反编译 + REA 证据 JSON + 逐条对比 | `reversed/rea/bobsbuddy/`、`reversed/rea/bobsbuddy_vs_hsrl2.md` |
| Assembly-CSharp 分析 | ⚠️ artifact 级 ✅；成员级 REA 不可用（resource-limit），ilspycmd 替代 | `reversed/rea/client_official/` |
| 客户端常量 | ✅ `client_constants.json` | `reversed/rea/client_constants.json` |
| HsMod 能力清单 | ✅ | 本文 §7 |
| 可复现脚本 | ✅ | `tools/rea_analyze_dotnet.ps1` |
| 未改配置/引擎 | ✅ | 未执行 `rea setup`；未写 `hsrl2/`、`hsbg/`、`data/`、`tests/` |
