# 真实对局数据桥（REAL_GAME_BRIDGE）

> 目标：摸清「真实游戏 ↔ 本项目」的数据桥，回答三个问题：
> 1）参考项目 **AgenticAssistant 0.5.3** 到底实现了什么（有没有本地模拟器/模型/自动操作）；
> 2）如何只读地从真实对局取数（Power.log → 可观测状态 → 动作序列 → 训练数据）；
> 3）线上 **36.6.3.253932** 与本项目引擎数据 **S14 / 36.2.2.249896** 差多少、怎么升级。
>
> 本文件的所有结论都标注了证据来源；数据差异由
> `python -m hsbg.bridge.catalog diff --out runs/data_diff_36.6.3.json` 生成，
> 原始统计见 [`runs/data_diff_36.6.3.json`](../runs/data_diff_36.6.3.json)。

---

## 0. TL;DR（先看结论）

| 问题 | 结论 |
|------|------|
| AgenticAssistant 有没有**本地模拟器 / 模型权重**？ | **没有**。251 个 PYZ 模块里没有 `torch/onnx/tensorflow/numpy`，发行包无模型文件；多个模块 docstring 明说 "never loads a local model or simulator"；UI 文案明确"模型和战斗模拟器均运行于服务器"。 |
| 有没有**自动点击游戏**？ | **没有**。无 `pyautogui/pynput/keyboard/mouse/pydirectinput`，无 `SendInput/PostMessage/keybd_event`；reader 的 docstring 写明 "No ... mouse backend ... imports"；唯一的"一键拔线"是 `SetTcpEntry` 断 TCP 连接，不是输入注入。 |
| 是不是**只读 Power.log**？ | **只读是对的，"仅日志"不准确**。客户端还内置**只读 Mono 进程内存读取器**（`bgcontroller.client.mono/memory`，`QUERY_INFORMATION\|VM_READ`，无注入/无写内存），且 `reader.py` 把内存快照当**当前局面主源**，Power.log 用于**历史/动作/战斗结果**。 |
| 会不会**上传原始日志/内存/昵称/账号**？ | 代码层面：不会。日志只做"窄白名单"语义抽取（`Extract a narrow allowlist from parsed logs, never upload raw log rows.`），`GameAccountId` 解析后丢弃，上传的是 DTO（局面/合法操作/AI 建议/轨迹）。服务端保留策略无法从客户端静态验证。 |
| 本机能用真实 Power.log 吗？ | **暂不能直接验证**：`C:\Program Files (x86)\Hearthstone\Logs` 不存在（还没在开启日志后打过一局）；但 `log.config` 的 `[Power]` 段已启用（`LogLevel=1 / FilePrinting=True / Verbose=True`）。探针工具会自动探测路径，找不到时走内置样例自测。 |
| 数据差多少？ | 线上 catalog **3983 张（折叠金色后 2749 张本体）**；本地引擎数据 **3683 个原始 id（折叠后 2560）**；id 交集 **2435**，**线上有而引擎缺 314 个本体 id**（其中 BG36 新卡池 84 个），引擎有而线上目录无 125 个（历史/轮换/令牌/异变为主）。详见 §4。 |

> **注意（2026-10-18）**：上表"数据差多少"是 36.6.3 catalog vs **36.2.2** 引擎数据
> 的历史基线；项目 `data/` 已升级到 **37.0.0.255130**（BG36 已全部覆盖）。
> 最新的 rizling 0.6.1（仍自报 36.6.3）↔ 255130 数据对齐与版本同步流程见
> [`docs/VERSION_SYNC.md`](VERSION_SYNC.md)。

---

## 1. 取证方法与可复现性

### 1.1 分析对象

| 对象 | 事实 |
|------|------|
| `C:\HSagent\AgenticAssistant\` | AgenticAssistant 0.5.3（Windows x64 远程内测版），**只读分析，未运行 exe** |
| `AgenticAssistant.exe` | 2,833,498 B；PyInstaller 6 打包，尾部 CArchive（`MEI\x0c\x0b\x0a\x0b\x0e`），`PYZ.pyz` **2,436,851 B / 251 个模块** |
| `AgenticUpdater.exe` | 13,225,739 B；PyInstaller 打包，177 个模块（自动更新器） |
| `_internal\bgassistant\data\catalog.json` | 886,570 B，`game_version = 36.6.3.253932`，3983 张卡 + 653 条皮肤映射 |
| `_internal\bgcontroller\data\game_tags.json` | 49,104 B，`GameTag(1259)` / `CardType(22)` / `Race(47)` / `Zone(10)` / `ChoiceType(4)` / `PlayState(9)` / `State(4)` / `Step(21)`；来源 python-hearthstone commit `b1819312...` |
| `release-manifest.json` | 0.5.3，built `20261018-001807`，Python 3.13.16，OpenSSL 3.5.9，1012 个文件 SHA256，`offline_smoke = {catalog_cards: 3983, dpapi: true, ui: true, forbidden_imports: []}` |

`catalog.json` 的结构（已用 python 采样统计）：

```jsonc
{
  "game_version": "36.6.3.253932",
  "cards": [ {
    "id": "BG20_100", "dbf": 70143, "kind": "minion",
    "name": "Razorfen Geomancer", "name_zh": "剃刀沼泽地卜师",
    "tier": 1, "races": ["QUILBOAR"], "keywords": ["BATTLECRY"],
    "normal": "", "activatable": false, "activation_cost": 0
  } ],                                  // 3983 条；73 条法术额外有 "spellcraft_spell": true
  "skins": { "BG20_HERO_100_SKIN_A4": "BG20_HERO_100", ... }   // 653 条：皮肤 -> 本体英雄
}
```

- 字段：`id/dbf/kind/name/name_zh/tier/races/keywords/normal/activatable/activation_cost`
  （+ 可选 `spellcraft_spell`）；**没有** atk/health/cost/text/脚本参数。
- `kind` 分布：minion 2596、spell 297、trinket_greater 219、tavern_spell 208、
  trinket_lesser 201、hero_power 176、hero 143、quest_reward 73、dark_gift 47、quest 23。
- `tier` 分布：0:1156、1:369、2:323、3:599、4:517、5:655、6:305、7:59（非池内卡/法术/饰品为 0）。
- `name_zh` 覆盖率 **100%**（3983/3983 非空，含中文）；`normal` 非空 1234 条（金色变体指向本体）。
- 关键词 tag 为 `TRIGGER_VISUAL/DEATHRATTLE/BATTLECRY/...`，Top：`TRIGGER_VISUAL` 1378、
  `DEATHRATTLE` 428、`BATTLECRY` 359、`END_OF_TURN_TRIGGER` 234、`TAUNT` 193。
- `activatable=true` 50 条、`activation_cost>0` 40 条、`spellcraft_spell` 73 条。

`game_tags.json` 的结构：`{source, commit, enums}`，`enums` 含
`GameTag(1259 项)/CardType(22)/Race(47)/Zone(10)/ChoiceType(4)/PlayState(9)/State(4)/Step(21)`
的「数值 ↔ 名称」映射；来源为 python-hearthstone `b1819312...`。**它不是卡牌数值表**，
但可直接把 Power.log 的 `tag=` 名字与数值互查（本项目解析器保存字符串 tag，正因如此无需该表）。

### 1.2 静态分析手段（没有执行程序、没有联网）

1. **发行包结构**：目录清单 + `release-manifest.json`（`files` 哈希、`source_files`、`client_sources`、`bundled_project_modules`、`offline_smoke`）。
2. **PyInstaller 静态解析**：从 exe 尾部 CArchive cookie 读出 TOC → 定位 `PYZ.pyz` → 解析 PYZ 的 marshal TOC → 对每个模块 `zlib.decompress` 后 `marshal.loads` 得到 `code` 对象 → 递归提取 `co_names/co_consts` 与 docstring（**只读字节，不反编译执行**）。分析脚本放在临时目录，不进入仓库。
3. **catalog / game_tags 采样**：用 `python(encoding='utf-8')` 读取 JSON 并统计字段分布（不整文件塞进上下文）。
4. **差异统计**：`hsbg/bridge/catalog.py` 的 `compare_with_engine_data()`（见 §4/§8）。

> 为什么能这样判定"有没有本地模型/模拟器"：PyInstaller 会把所有被 import 的纯 Python 模块（含 C 扩展的包装）放进 PYZ/`_internal`；251 个模块的完整清单里没有 `torch/onnx/tensorflow/numpy`，也没有打包任何权重文件（manifest 1012 个文件全部可见，无 `.pt/.onnx/.bin/weights`）。同时 `release-manifest.offline_smoke.forbidden_imports = []` 说明打包者自己也跑过"禁止导入"检查。

### 1.3 本项目仓库内的关联资料

| 资料 | 用途 |
|------|------|
| `docs/reference_old/HDT_INTERFACE.md` | HDT（C# `GameStateExtractor`）暴露的 `game_state` 字段 ↔ GameTag 映射，是 Power.log/memory → 观测的对照表 |
| `docs/reference_old/POMDP_OBSERVABLE_FEATURES.md` | 真实对局中"哪些信息可见/不可见"（对手棋盘只有最近一次战斗快照等） |
| `docs/reference_old/S14_DIFF_REPORT.md` | 35.6.0 → 36.2.2 的自动 diff 报告，可作为下次升级的模板 |
| `\\wsl$\Ubuntu-22.04\home\glt\HrSRL\` | 旧项目：`Hearthstone-Deck-Tracker/` 源码、`hsrl/advisor/`（HDT 插件 + WebSocket 服务 + 采集器）、`data/real_games/*.jsonl`（原始逐帧 JSONL）、`data/trajectories_real/*.json`（按回合快照） |
| `data/backup_35.2.2/`、`data/backup_35.6.0/` | 以前升级留下的卡池快照，可作为回滚/对比样板 |

旧项目真实数据样例（可直接作为落盘格式参照）：

- `data/real_games/20260529/bg_20260529_214109_6269.jsonl`（15.1 MB）：每行 `{"type":"game_start|step|game_end", ...}`，`step.state` 是 HDT 的完整 `game_state`；旧 `hsrl/advisor/collector.py` 就是按这个格式落盘。
- `data/trajectories_real/bg_20260529_214109_6269.json`（35 KB 级）：按回合压缩的
  `TurnSnapshot`（board/tavern_tier/health/trinkets/placement），由
  `hsrl/advisor/trajectory_converter.py` 从上面 JSONL 提取。

---

## 2. AgenticAssistant 能力边界（结论 + 证据）

### 2.1 发行包结构

```
AgenticAssistant/
├── AgenticAssistant.exe            # 2.83 MB，PyInstaller 引导 + PYZ（全部业务代码）
├── AgenticUpdater.exe              # 13.2 MB，自动更新器（Ed25519 + SHA256 + zip）
├── release-manifest.json           # 0.5.3 / 1012 文件哈希 / 模块清单 / offline_smoke
├── 使用说明.txt                     # UTF-8 中文用户说明（59 行）
└── _internal/
    ├── bgassistant/data/catalog.json      # 3983 卡 + 653 皮肤（36.6.3.253932）
    ├── bgcontroller/data/game_tags.json   # GameTag/CardType/Race/Zone... 枚举
    ├── bgcontroller/data/BGTRACKER_LICENSE.txt  # MIT（Mono 布局遍历来源）
    ├── bgcontroller/data/PYTHON_HEARTHSTONE_LICENSE.txt
    ├── python313.dll / base_library.zip / tcl/tk / cryptography / _wmi ...
    └── （没有任何模型文件、没有 .py 源码）
```

`release-manifest.json` 的三个模块清单（打包者自述，已被 PYZ 实际清单验证）：

- `bundled_project_modules`（27 个）：`bgassistant.*`（15 个：`catalog/diagnostics/disconnect/network/protocol/reader/settings/telemetry/trajectory/ui/updates/update_key/...`）+ `bgcontroller.*`（12 个：`records/state/client.{choices,history,leaderboard,mapping,mechanics,memory,mono,powerlog,tags}`）。
- `client_sources`（15 个源文件）与 `source_files`（16 个，属于 `bgcontroller` 的 records/state/client.* 与两个 data 文件）——**注意没有 `liveclient`/`mouse`/`runner`/`model`**。
- `updater_project_modules`（10 个）：只包含更新所需模块。

### 2.2 能力结论表

| # | 能力 | 结论 | 证据（静态） |
|---|------|------|--------------|
| 1 | 读取 **Power.log** | ✅ 有 | 模块 `bgcontroller.client.powerlog`（docstring: *"Power.log: the server's messages as the client received them."*），含 `CREATE_GAME/FULL_ENTITY/TAG_CHANGE/SHOW_ENTITY/BLOCK_START/BLOCK_END/Player/option/ChoiceType` 解析与 `LogTail` 增量跟随；只读 `GameState.*`，跳过 `PowerTaskList.*` 重复行。 |
| 2 | 读取**游戏进程内存** | ✅ 有（**只读**） | 模块 `bgcontroller.client.mono`（docstring: *"Bounded read-only Mono metadata reader for Windows x64. ... Only QUERY_INFORMATION and VM_READ access are requested."*）与 `bgcontroller.client.memory`（*"Read-only game snapshots from a live Windows x64 Mono process. ... No injection or managed methods."*）；读取 `mono-2.0-bdwgc.dll`/`Assembly-CSharp` 的 `GameState`：`m_entityMap/m_entityRaces/m_local/m_choicesMap/m_gameEntity` 等；调用 `OpenProcess/ReadProcessMemory`（VM_READ）。**无 WriteProcessMemory、无注入、无 managed 方法调用**。 |
| 3 | 本地**战斗模拟器 / 搜索** | ❌ 没有 | 251 个模块中无任何模拟器模块；`bgassistant` docstring: *"Windows remote hints client. This package never loads a local model or simulator."*；`bgassistant.trajectory`: *"No simulator, encoder or model imports."*；`bgassistant.catalog`: *"Public card metadata only; no scripts, model indices, pools or rules."*；UI 文案："客户端只读取对局并显示建议。模型和战斗模拟器均运行于服务器。"；`bgcontroller.client.history` 只是**从日志 block 计数**（不是模拟）。 |
| 4 | 本地**模型权重 / 推理** | ❌ 没有 | 模块清单无 `torch/onnx/tensorflow/numpy/sklearn`；manifest 无权重文件；`bgassistant.protocol` docstring: *"Public DTO field fingerprint, independent of model tensors or weights."*；`offline_smoke.forbidden_imports = []`。 |
| 5 | **自动点击/输入注入** | ❌ 没有 | 无 `pyautogui/pynput/keyboard/mouse/pydirectinput`，无 `SendInput/keybd_event/mouse_event/PostMessage/SetCursorPos` 字符串；`bgassistant.reader` docstring: *"No LiveClient, mouse backend, runner or model imports."*；`bgassistant.disconnect` docstring: *"User-triggered, PID-verified disconnect. No input automation or clock plugin."*；`使用说明` 第 27 行"客户端不自动点击游戏"。 |
| 6 | **远程 AI 建议** | ✅ 有 | `bgassistant.network`/`protocol`/`ui`：`https://rizling.top/assistant`、访问码（`access_code`）、TLS 证书校验（`ssl`）、系统代理可选；上传 DTO 后接收 hint（`decode_hint`）。 |
| 7 | **内测数据采集/上传** | ✅ 有 | `bgassistant.trajectory`（语义动作记录，docstring: *"Small semantic action records. No simulator, encoder or model imports."*）；`bgassistant.telemetry`（DPAPI 密封的 SQLite 上传队列：`queue(id,key,kind,created,size,sealed)`，`PRAGMA secure_delete=ON`，带 `MAX_ROWS/MAX_BYTES/过期删除` 常量；《使用说明》称上限 4096 条 / 32 MiB / 7 天）；`protocol` 的 DTO 里有 `state/legal/hint/actions`；UI 文案："连接后默认保存局面、合法选项、AI 建议、观察到的操作与战斗结果……不上传完整日志、昵称或账号密码。仅本地记牌模式不上传。" |
| 8 | **自动更新** | ✅ 有 | `bgassistant.updates`: `Ed25519PublicKey` 验签 + SHA256 + zip 包校验 + 仅在 `%LOCALAPPDATA%\AgenticBattlegroundsAssistant\updates\versions` 侧装；更新源 `https://rizling.top/assistant/updates/`。 |
| 9 | **一键拔线** | ✅ 有（手动触发） | `bgassistant.disconnect`：`GetExtendedTcpTable` + `SetTcpEntry`（iphlpapi），按 PID 精确匹配炉石对局连接后断开；**不是**鼠标/键盘自动化。需要管理员权限时 UI 会提示。 |

### 2.3 与《使用说明》一致 / 矛盾清单

| 《使用说明》原文/含义 | 核对结果 | 证据 |
|----------------------|----------|------|
| L58 "本包不包含模型权重、模拟器或训练代码，全部 AI 与战斗计算均在运营者服务器上运行" | ✅ **一致** | 无模型/模拟器模块与文件；UI 文案同义；只有采集/协议/渲染代码 |
| L27 "客户端不自动点击游戏" | ✅ 一致 | 无输入库/输入 API 字符串；reader/disconnect docstring 自证 |
| L30–L38 内测记录局面/合法操作/AI 建议/实际操作/战斗结果/名次；不上传完整日志/原始内存/昵称/账号密码 | ✅ **代码意图一致** | `trajectory` 只记录语义动作与白名单字段；`reader`: *"Extract a narrow allowlist from parsed logs, never upload raw log rows."*；`GameAccountId` 只在 Player 行解析、未进入 DTO；`PlayerName` 仅在 `DebugPrintGame` 行被识别，**未发现**进入上传 DTO/轨迹字段的代码路径。服务端保留 30 天等策略**无法从客户端静态验证**。 |
| L39 "仅本地记牌模式不新增上传" | ✅ 一致 | UI 字符串 `本地记牌模式 · 未使用远程计算`；`telemetry` 只在连接远程时入队 |
| L19–L20 "开启 Power.log / 默认 Logs 路径 `C:\Program Files (x86)\Hearthstone\Logs`" | ✅ 一致（且更具体） | `bgassistant.settings.enable_power_log()` 反汇编显示：写 `%LOCALAPPDATA%\Blizzard\Hearthstone\log.config`，`[Power] LogLevel=1 / FilePrinting=true / Verbose=true`（保留原文件备份 `.bgassistant.bak`） |
| L57 "一键拔线…可能需要管理员权限，由游戏自行重连" | ✅ 一致 | `SetTcpEntry`（iphlpapi）需要管理员；文案："已断开当前炉石对局连接，等待游戏自行重连 / 可能需要以管理员身份运行客户端" |
| L15–L18 服务器/更新地址、签名校验、无管理员权限 | ✅ 一致 | `https://rizling.top/assistant`、`/updates/`；Ed25519/SHA256；写入当前用户 profile |
| **"客户端只读 Power.log"（任务背景/使用说明给人的印象）** | ⚠️ **需要修正** | 客户端**确实还读内存**（只读）。`bgcontroller.client.powerlog` docstring 原文更准确：*"The client's memory is the controller's source for the state of the game (it is what the screen shows; the log runs seconds ahead of it). The log supplies what memory has no record of: what the player did so far, how the combats went, the warbands met."* 结论：**只读 ✅ / 仅日志 ❌**；读取范围是进程查询 + VM_READ，无写内存/注入。 |
| L41 "服务器默认保留 30 天…" | ❓ 客户端不可验证 | 属于服务端行为，静态分析无法证实/证伪 |

### 2.4 关键证据原文（静态提取，保留英文原句）

```text
bgassistant
Windows remote hints client. This package never loads a local model or simulator.

bgassistant.reader
Read-only live adapter. No LiveClient, mouse backend, runner or model imports.

bgassistant.trajectory
Small semantic action records. No simulator, encoder or model imports.

bgassistant.catalog
Public card metadata only; no scripts, model indices, pools or rules.

bgcontroller.records
Transport-neutral game readings. No model, simulator or input dependency.

bgcontroller.client.mono
Bounded read-only Mono metadata reader for Windows x64.
Layout traversal adapted from BattlegroundsHelp/bgtracker (MIT).
Only QUERY_INFORMATION and VM_READ access are requested.

bgcontroller.client.memory
Read-only game snapshots from a live Windows x64 Mono process.
Only process query and VM_READ access are requested. No injection or managed methods.

bgcontroller.client.powerlog
Power.log: the server's messages as the client received them.
... Only `GameState.*` lines are read: the `PowerTaskList.*` lines repeat the
same messages when the client animates them.
The client's memory is the controller's source for the state of the game
(it is what the screen shows; the log runs seconds ahead of it). The log supplies
what memory has no record of: what the player did so far, how the combats went,
the warbands met.

bgassistant.disconnect
User-triggered, PID-verified disconnect. No input automation or clock plugin.

bgassistant.updates
Signed HTTPS updates installed side by side in the current user's profile.
```

> ⚠️ 一个容易误读的点：`bgcontroller` **包级 docstring** 仍保留旧项目（自动 bot）的描述
> *"Runs the trained model on the real Hearthstone Battlegrounds client. read the game → GameState → model input → model → operation → mouse gestures"*。
> 但该 bot 的 `LiveClient`/mouse backend/runner/model 模块**没有被打进发行包**
> （`bundled_project_modules` 与 PYZ 模块清单均可验证），`reader.py` 也明确说
> "No LiveClient, mouse backend, runner or model imports"。所以**不能**用它证明客户端有自动操作。
> `bgcontroller.client.mapping`/`mechanics` 里出现的 "simulator" 字样，是把客户端数据对齐到
> **服务端**模型输入字段的适配代码（例如 trinket 剩余回合的计数规则），不是本地模拟器。

### 2.5 对本项目的启示

1. "只读日志"可以作为**低风险基线**；AgenticAssistant 额外走的"只读内存"路线我们不跟进（理由见 §6）。
2. 它的 `catalog.json` 是一个现成的**线上 36.6.3 公共元数据快照**，可作为本项目的版本校验对照物（只读使用，见 §4）。
3. 它的采集器设计（语义动作 + 确认机制 + 缺口记录 + 不硬拼轨迹）值得直接借鉴到我们的 JSONL schema（见 §3.5）。

---

## 3. 真实对局数据链路设计

### 3.1 Power.log 获取

#### 3.1.1 打开日志（手动或自动）

`log.config` 位置（Windows，当前用户）：

```
%LOCALAPPDATA%\Blizzard\Hearthstone\log.config
```

本项目/手动写入的最小内容（与 AgenticAssistant `settings.enable_power_log()` 写入的值一致）：

```ini
[Power]
LogLevel=1
FilePrinting=true
ConsolePrinting=false
ScreenPrinting=false
Verbose=true
```

要点：

- 修改 `log.config` 后必须**完全退出并重启炉石**，从**新的一局**开始才会产生完整 `Power.log`（中途打开会缺 `CREATE_GAME`）。
- 文件编码 UTF-8（可能带 BOM）；读文件用 `encoding="utf-8", errors="replace"`。
- 日志目录默认 `C:\Program Files (x86)\Hearthstone\Logs`；不同安装方式也可能在
  `%LOCALAPPDATA%\Blizzard\Hearthstone\Logs` 或 `Documents\Hearthstone\Logs`。本项目的
  `tools/powerlog_probe.py` 会按顺序探测这些路径，**只读**打开。
- 本机现状：上述 `Logs` 目录**都不存在**（还没在开启日志后打过一局）；但
  `%LOCALAPPDATA%\Blizzard\Hearthstone\log.config` 已经包含 `[Power]` 段（疑似之前
  用 AgenticAssistant 的"开启 Power.log"写过）。因此现在运行探针会走内置样例。

#### 3.1.2 增量跟随（tail）语义

AgenticAssistant 的 `LogTail` 行为（docstring）：*"New complete lines of a growing file. A file that shrank or was replaced is read again from its start."*
我们照此实现，推荐算法：

1. 记录 `(st_dev, st_ino, st_size)` 与已读 `offset`；
2. 每 200–500 ms `stat` 一次：
   - 设备/ inode 变化或 `size < offset` → 判定"日志被替换/截断"，`reset()` 并从头读；
   - 否则从 `offset` 读到 `size`，只处理以 `\n` 结尾的**完整行**（半行留在缓冲）；
3. `CREATE_GAME` 出现在同一文件里可能是**断线重连**（`GAME_SEED` 相同）；原型默认每次
   `CREATE_GAME` 重置状态，并通过 `game_index` 区分（真实采集应把重连前的
   `CREATE_GAME` 快照并入同一 episode，见 AgenticAssistant `LogGame` 的
   *"Include preceding reconnect CREATE_GAME snapshots of the same seed."*）。

### 3.2 行格式与解析

#### 3.2.1 通用行结构

真实 Power.log 每一行形如（`[DIWE]` 级别 + 时间 + 命名空间 + 内容）：

```text
D 15:31:06.1234567 GameState.DebugPrintPower() - CREATE_GAME
```

解析正则（与 AgenticAssistant `bgcontroller.client.powerlog` 相同思路）：

```python
^[DIWE] (?P<ts>\d{2}:\d{2}:\d{2}\.\d+) (?P<source>[\w.]+)\(\) -\s*(?P<content>.*?)\s*$
```

- **只解析 `GameState.*`**：`PowerTaskList.*` 是动画回放时的重复消息，重复解析会
  把一条动作算两遍（本项目解析器默认跳过，`include_tasklist=False` 可打开）。
- 其他命名空间（如 `GameNetLogger`、`Achievements`）不属于 Power 消息，忽略并计数。

#### 3.2.2 关键行格式（来自 AgenticAssistant 解析器的正则，已核对）

| 行类型 | 格式 / 正则要点 | 说明 |
|--------|-----------------|------|
| 开局 | `CREATE_GAME` | 新一局（或重连快照）开始，重置实体表 |
| 游戏实体 | `GameEntity EntityID=1` | 后跟 `tag=GAME_SEED value=...` 等 |
| 玩家 | `Player EntityID=2 PlayerID=1 GameAccountId=[hi=.. lo=..]` | `hi/lo` 是账号标识，**本项目不保存** |
| 实体创建 | `FULL_ENTITY - Creating ID=64 CardID=` | 随后是若干 `tag=... value=...` 行 |
| 实体更新 | `FULL_ENTITY - Updating [entityName=... id=64 zone=... zonePos=.. cardId=.. player=..] CardID=...` | 揭示名称/区域/卡 id |
| 揭示 | `SHOW_ENTITY - Updating Entity=[...] CardID=BG_XXX` | 酒馆/发现等"亮牌" |
| 变形 | `CHANGE_ENTITY - Updating Entity=[...] CardID=...` | 同 SHOW |
| tag 变化 | `TAG_CHANGE Entity=[...] tag=ZONE value=PLAY` | 状态机的核心；`Entity=` 后跟 `[entityName=.. id=.. zone=..]` 或纯数字/`GameEntity` |
| 缩进 tag | `    tag=ATK value=2` | 紧跟在 FULL_ENTITY/Player 后，补全实体初始 tag |
| block 开始 | `BLOCK_START BlockType=PLAY Entity=[...] EffectCardId= EffectIndex=0 Target=0 SubOption=-1` | 服务端一次"原子操作"，动作/战斗都从这里解读 |
| block 结束 | `BLOCK_END` | 与 BLOCK_START 配对（可嵌套） |
| 选项 | `option 0 type=END_TURN mainEntity= error=INVALID` | `DebugPrintOptions` 段，合法操作列表 |
| 选择 | `id=1 Player=Bob TaskList= ChoiceType=GENERAL CountMin=0 CountMax=1` + `Entities[0]=...` | `DebugPrintEntityChoices` 段（发现/三选一） |

#### 3.2.3 本项目解析器原型 `hsbg/bridge/powerlog.py`

```python
from hsbg.bridge.powerlog import PowerLogParser

parser = PowerLogParser()                 # include_tasklist=False, capture_player_names=False
for line in open("Power.log", encoding="utf-8", errors="replace"):
    events = parser.feed(line)            # -> list[PowerLogEvent]，未知行也不抛异常
state = parser.game_state()               # 可 JSON 序列化的快照
```

能力：

- `feed(line) -> list[PowerLogEvent]`：逐行增量；事件类型
  `create_game/game_entity/player/full_entity/show_entity/change_entity/tag_change/
  entity_tag/block_start/block_end/option/choice/player_name/other/unknown`。
- 维护实体 tag 表（`parser.entities[eid].tags`）、玩家映射（`parser.players`）、
  block 栈（`parser.blocks`）、`turn/phase/game_seed/game_index`。
- 查询：`card_id(eid)`、`tag(eid, name)`、`int_tag(eid, name)`、
  `entities_in_zone("PLAY")`、`minions_in_play()`。
- 容错：未知/畸形行 → `unknown` 事件 + 计数；`parse_errors` 不抛出。
- 隐私：`GameAccountId` 解析后立即丢弃；`PlayerName` 默认**不保存**
  （`capture_player_names=True` 才保存，供本地调试）。
- `feed_file(path, tail_bytes=..., max_lines=...)`：一次性/尾部读取。

探针：

```powershell
python tools/powerlog_probe.py                 # 自动找真实 Power.log；找不到走样例
python tools/powerlog_probe.py --log "C:\Program Files (x86)\Hearthstone\Logs"
python tools/powerlog_probe.py --sample --max-lines 1000
```

本机当前没有真实日志，探针输出（样例自测）摘要为：33 行 / 5 实体 / 2 玩家 / turn 2 /
`BLOCK_START` 2 个（PLAY、TRIGGER）/ 未知行 0 / 解析异常 0。

### 3.3 从 Power.log 重建"酒馆战棋可观测状态"

#### 3.3.1 引擎观测契约（本项目 `hsbg/env/spec.py`）

`Observation` 的字段就是对齐目标：`turn/phase/hero(board,hand,tavern,trinkets,quest,
opponent_board,lobby,alive_count,rank,pending_choice,candidates)`；实体统一为
`EntityToken(card_id, card_type, zone, slot, atk, health, tier, cost, races,
keywords, golden, entity_id, name)`；英雄为 `HeroToken(...)`；对手为 `LobbyPlayer(...)`。

#### 3.3.2 tag → 观测字段映射表

| 观测字段 | 来源 tag / 日志行 | 备注 |
|----------|-------------------|------|
| `turn` | Player `TURN`（或 GameEntity `TURN`） | 招募回合数，`max(turn,1)` |
| `phase` | `BACON_IN_COMBAT_PHASE`（GameEntity）→ combat/recruit；或出现 `BLOCK_START BlockType=TRIGGER` 且 `TB_BaconShop_8P_PlayerE` | 战斗阶段（观战/结算） |
| `hero.health/armor/gold/tier` | Player 实体：`HEALTH/ARMOR/RESOURCES+TEMP_RESOURCES-RESOURCES_USED/PLAYER_TECH_LEVEL` | gold 公式与 HDT 一致 |
| `hero.hero_id` | Player `HERO_ENTITY` → 英雄实体的 `CardID` | 英雄实体在 PLAY zone |
| `hero.power_*` | 英雄技能实体（`CARDTYPE=HERO_POWER`，`CONTROLLER`=玩家）：`COST/EXHAUSTED` | |
| `board[*]` | `CONTROLLER=self` + `ZONE=PLAY` + `CARDTYPE=MINION`，按 `ZONE_POSITION` 排序 | 随从：`ATK/HEALTH/DAMAGE/PREMIUM/TAUNT/DIVINE_SHIELD/POISONOUS/VENOMOUS/REBORN/WINDFURY/EXHAUSTED` |
| `hand[*]` | `CONTROLLER=self` + `ZONE=HAND` | 手牌：`COST/ATK/HEALTH/PREMIUM/BATTLECRY/SPELLCRAFT/NUM_TURNS_IN_PLAY` |
| `tavern[*]` | `ZONE=PLAY` 且 `CREATOR` 指向 "Bob"（酒馆实体）的随从/法术 | AgenticAssistant 用 `TB_BaconShop_8P_PlayerE`/`CREATOR` 区分；HDT_INTERFACE §4 |
| `trinkets[*]` | `ZONE=SECRET` + `CONTROLLER=self`（饰品占 SECRET 区），`TECH_LEVEL/COST` | 最多 2 个 |
| `quest` | 任务卡（`kind=quest`）在 PLAY/SECRET 区 | 36.x 任务/奖励机制 |
| `opponent_board[*]` | 战斗开始瞬间 Bob 的随从（见 §3.4） | 招募期看不到对手当前棋盘 |
| `lobby[*]` | Player 实体的 `HEALTH/ARMOR/PLAYER_TECH_LEVEL/PLAYSTATE` + 存活判定 | 名次/存活人数由此推导 |
| `alive_count/rank` | 由各 Player `HEALTH>0` / `PLAYSTATE` 推导 | 真实名次只在终局日志/结算界面确认，不要提前推断 |
| `pending_choice` | `DebugPrintEntityChoices`（`ChoiceType/CountMin/CountMax/Entities[i]`）或 `DebugPrintOptions` | 发现/三选一/任务奖励 |
| `candidates` | `DebugPrintOptions` 的 option 列表 + block 中的动作 | 见 §3.4 语义化 |
| `anomaly` | `BG_ANOMALY` 类卡 id（GameEntity/Player tag 或实体扫描） | 36.x 异变 |
| `damage_cap` | `BACON_COMBAT_DAMAGE_CAP/_ENABLED` | 15（或异变调整后） |

> 字段级对照详见 `docs/reference_old/HDT_INTERFACE.md`（HDT 插件版 `game_state` 的
> 每个字段 ← 哪个 GameTag）；Power.log 与 HDT 用的是同一套 tag 名（`TAG_CHANGE` 的
> `tag=` 直接就是 GameTag 名），因此该表可直接复用。

#### 3.3.3 已知观测边界（必须写进 schema/训练过滤）

来自 `docs/reference_old/POMDP_OBSERVABLE_FEATURES.md` 与 AgenticAssistant 的说明：

- 招募期**看不到**对手当前棋盘/手牌/金币/英雄技能状态；
- 对手棋盘只有**最近一次战斗**的快照（HDT 的 `LastKnownBoardState`，键为 `PLAYER_ID`，带
  战斗回合数 → `staleness = 当前回合 - combat_turn`）；
- 对手饰品/任务通常**不可见**（除非战斗/效果揭示）；
- 匹配对手、隐藏信息、战斗随机结果不可观测；
- 因此训练时应把不完整观测与"上帝视角模拟器观测"分开：真实数据用于 BC/评价，
  不能直接当完全信息 RL 输入。

### 3.4 动作序列重建

AgenticAssistant `bgcontroller.client.history` 的规则（docstring 原文，来自"第一代控制器"
在真实客户端的经验），可以直接作为我们 `hsbg` 动作的判定逻辑：

1. **玩家动作 = 招募阶段的顶层 `BlockType=PLAY` block**。看该 block 的实体区分：
   - 拖拽购买：`TB_BaconShop_DragBuy` / `_DragBuy_Spell` / `_DragSell`，`Target` 是卡；
   - 按钮（刷新/升级/冻结/结束回合）；
   - 英雄技能实体；
   - 手牌里的卡；
   - 法术施放：block 内部出现同一张卡的 `POWER` block。
2. **战斗结果**：战斗以 `TRIGGER` block（`TB_BaconShop_8P_PlayerE`，`EffectIndex=14`）结束，
   内部是输家被英雄 `ATTACK`；本地英雄 Attack → win，Bob 英雄 → loss，无英雄 Attack → tie；
   伤害 = 攻击者 `ATK`。
3. **对手战团**：战斗开始时 Bob 控制的所有随从（`ZONE=PLAY`）的 tag 快照。
4. **实体替换**：战斗后随从被替换，`COPIED_FROM_ENTITY_ID` 能把复制体链回原体。

映射到 `hsbg/env/spec.py` 的 `ActionKind`：

| 真实动作 | 判定 | `ActionKind` |
|----------|------|--------------|
| 拖动购买随从/法术 | `BlockType=PLAY`，实体 `TB_BaconShop_DragBuy(_Spell)`，Target=卡 | `buy` |
| 出售 | `TB_BaconShop_DragSell`，Target=棋盘随从 | `sell` |
| 手牌打出随从 | PLAY block 实体=手牌卡，且 `CARDTYPE=MINION` | `play_minion` |
| 施放法术 | PLAY block 内出现同卡 `POWER` block（或手牌 `CARDTYPE=SPELL`） | `play_spell` |
| 刷新 | 按钮实体（Bob 的刷新按钮） | `reroll` |
| 升级 | 按钮实体 | `upgrade` |
| 冻结/解冻 | 按钮实体 | `freeze` |
| 英雄技能 | 实体 `CARDTYPE=HERO_POWER` | `hero_power` |
| 随从 Activate | 实体带 `activate`/`BACON_...ACTIVATE` 类 tag | `activate` |
| 黑暗赠礼 | `BlockType=PLAY` + dark gift 选项（`DebugPrintEntityChoices`） | `use_dark_gift` |
| 结束回合 | `option type=END_TURN` | `end_turn` |
| 发现/三选一 | `DebugPrintEntityChoices` 的 `option` 下标 | `choose` |

**动作确认（重要）**：AgenticAssistant 的规则是"有服务器 PLAY 回执或单步操作计数变化才确认生效"；
无法确认的操作与轨迹缺口**不硬拼**为训练序列（`trajectory` 模块的 `confirmed/unconfirmed/rejected/
server_play_block/gap` 字段）。我们的 JSONL 也要保留 `confirmed: true/false` 与 `gaps`。

### 3.5 建议的 JSONL 落盘格式

一行一个 JSON（UTF-8，无 BOM），文件按 episode 拆分；与旧项目 `data/real_games/*.jsonl`
（`game_start / step / game_end`）兼容，并新增语义动作/确认字段：

```jsonl
{"type":"episode","schema":"hsbg.real_episode.v1","episode_id":"sha256:9f2c...","patch":"36.6.3.253932","source":"powerlog","parser_version":"0.1.0","started_utc":"2026-10-18T15:31:06Z","hero_id":"BG20_HERO_100","players":8}
{"type":"turn","turn":5,"phase":"recruit","observation":{"hero":{"hero_id":"BG20_HERO_100","health":32,"armor":5,"tier":3,"gold":7,"upgrade_cost":8,"power_cost":2,"power_usable":true},"board":[{"card_id":"BG20_100","atk":2,"health":1,"tier":1,"races":["BEAST"],"keywords":["battlecry"],"golden":false,"entity_id":64}],"hand":[],"tavern":[],"trinkets":[],"lobby":[{"health":38,"armor":0,"tier":3,"alive":true}],"alive_count":7,"rank":4},"raw_tags":{"self_entity_id":2,"self_player_id":1}}
{"type":"step","turn":5,"phase":"recruit","observation":{},"legal_actions":[{"kind":"buy","option":1,"entity_id":64,"card_id":"BG20_100"},{"kind":"end_turn","option":0}],"observed_action":{"kind":"buy","entity_id":64,"target":0,"position":1},"confirmed":true,"confirmation":"server_play_block","elapsed_ms":812,"gap":false}
{"type":"step","turn":6,"phase":"combat","observation":{"opponent_board":[{"card_id":"BG23_000","atk":4,"health":5,"taunt":true}]},"combat_result":{"result":"win","damage_dealt":4,"damage_taken":0,"rounds":1},"confirmed":true}
{"type":"episode_end","episode_id":"sha256:9f2c...","placement":2,"turns":11,"ended_utc":"2026-10-18T15:58:00Z","end_reason":"eliminated","gaps":0}
```

字段约定：

| 字段 | 说明 |
|------|------|
| `episode_id` | `sha256(随机盐 + 匹配置信度)`，**不**写玩家/账号标识；同局不同片段可关联但不可反查 |
| `source` | `powerlog` / `memory`（不推荐）/ `manual` |
| `observation` | 与 `hsbg/env/spec.py` 字段同名（实体 token 的 `card_id/atk/health/tier/cost/races/keywords/golden/entity_id`），数值保持整数；不写入未知/隐藏字段（用缺省/掩码） |
| `legal_actions` | 从 `DebugPrintOptions`/`EntityChoices` 语义化；无法语义化时保留原始 option 文本 |
| `ai_action` | 若使用远程 AI/本地模型，记录建议及其 `hint_id`/`elapsed`；没有则省略 |
| `observed_action` | 真实玩家操作（来自 PLAY block/选项计数） |
| `confirmed` / `confirmation` | `server_play_block` / `option_counter` / `unconfirmed` / `rejected` |
| `combat_result` | `result ∈ {win,loss,tie}`、`damage_dealt/taken`、`rounds` |
| `placement` | 只在 `episode_end` 写；必须是**观察到**的终局名次，不提前推断 |
| `gaps` | 轨迹缺口计数/原因（掉线、日志重置、客户端重启、无法确认） |

隐私与合规：

- **不写** `GameAccountId`、`PlayerName`、BattleTag、账号/密码、完整 `Power.log`、原始内存；
- 对局内姓名统一替换为 `player_1..8`；
- 默认**只落本地磁盘**（建议 `data/real_games/<date>/`，已按旧项目惯例；若担心误提交，
  可放 `runs/real_games/`，`runs/` 已在仓库忽略）；
- 采集前需用户**明确知情同意**（内测/自用），提供"仅本地记牌模式"与"一键清空"；
- 若要上传，仅上传上面白名单字段的 DTO，并说明用途/保留期；不要二次分发原始日志；
- `powerlog.py` 的 `capture_player_names=False` 是默认隐私开关。

---

## 4. 线上 36.6.3 与本地 36.2.2 的数据差异量化

> **历史基线说明（2026-10-18 更新）**：本节数字是"线上 36.6.3 vs 本地 36.2.2
> 基线"的对照，生成命令为
> `python -m hsbg.bridge.catalog diff --data-dir data/backup_249896 --out runs/data_diff_36.6.3.json`。
> 项目 `data/` 现已升级到 **37.0.0.255130**；最新的"rizling 0.6.1（仍自报 36.6.3）
> ↔ 本项目 255130 数据"对齐、版本检测与同步流程见
> [`docs/VERSION_SYNC.md`](VERSION_SYNC.md)。本节仍可作为 36.6.3 差异的历史证据。

### 4.1 方法与口径

- 数据源：
  - 线上：`_internal\bgassistant\data\catalog.json`，`game_version = 36.6.3.253932`；
  - 本地：`data/bg_cards.json` + `bg_heroes.json` + `bg_hero_powers.json` +
    `bg_dark_gifts.json` + `bg_tavern_spells.json` + `bg_quest_rewards.json` +
    `bg_trinkets.json` + `bg_anomalies.json`，`bg_summary.patch = 36.2.2.249896`。
- **折叠金色变体**：catalog 用 `normal` 字段把 `_G/_Gt` 指向本体；引擎数据按 catalog 的
  `normal` 映射 + `_G` 后缀折叠。否则 catalog 里 1234 个金色变体会全部被误判成"新增卡"。
- **引擎侧是累积 CardDefs 导出**（含历史/轮换/令牌/异变），所以 `only_engine` 不等于
  "线上删除"；只有 `only_catalog` 里的 **BG36 前缀**才是线上新卡池。
- catalog **只有公共元数据**（id/dbf/kind/name/name_zh/tier/races/keywords/golden 关系），
  **没有 atk/health/cost/text/脚本参数**；所以本报告只能量化"卡是否存在、名称、酒馆等级、
  种族、关键词"，**数值平衡改动无法量化**（要以 36.6.3 的 `CardDefs.xml` 为准）。

### 4.2 总量

| 指标 | 值 |
|------|----|
| catalog 卡牌记录数（含金色变体） | **3983** |
| catalog 本体数（折叠金色后） | **2749** |
| catalog 金色变体数 | **1234** |
| catalog 英雄皮肤映射 | **653** |
| 引擎 raw id 并集 | **3683** |
| 引擎本体数（折叠金色后） | **2560** |
| id 交集（本体口径） | **2435** |
| 线上有、引擎缺（only_catalog） | **314** |
| 引擎有、线上目录无（only_engine） | **125** |
| catalog 覆盖率（交集/线上本体） | **88.58%** |

### 4.3 按 catalog `kind` 的缺口

| kind | catalog 记录 | 折叠后本体 | 引擎命中 | 引擎缺失 |
|------|-------------:|-----------:|---------:|---------:|
| minion | 2596 | 1362 | 1182 | **180** |
| spell | 297 | 297 | 257 | **40** |
| trinket_greater | 219 | 219 | 200 | **19** |
| trinket_lesser | 201 | 201 | 179 | **22** |
| tavern_spell | 208 | 208 | 202 | **6** |
| hero | 143 | 143 | 116 | **27** |
| hero_power | 176 | 176 | 162 | **14** |
| quest_reward | 73 | 73 | 73 | 0 |
| dark_gift | 47 | 47 | 43 | **4** |
| quest | 23 | 23 | 21 | **2** |

### 4.4 新增疑似（只统计线上有、引擎无）

| 分组 | 数量 | 说明 |
|------|-----:|------|
| `BG36_*` | **84** | 36.6.3 当前卡池新卡：minion 40、trinket_greater 15、trinket_lesser 15、hero_power 2、hero 2、tavern_spell 3、dark_gift 4、spell 3 |
| `BGDUO*` | 97 | 双人模式专用，单人引擎不迁移 |
| `TB_*` | 21 | 乱斗/英雄皮肤相关，多为非酒馆卡 |
| 旧扩展（RLK/EX1/ICC/CORE/GVG/VAN…） | 约 90 | 构造/冒险卡，仅作为名字/效果引用；不是当前卡池 |
| 其他 BG 前缀 | 约 22 | 历史 token/衍生物 |

`only_engine` 125 个主要是 `BG27_Anomaly_*`、轮换出卡池的 `BG27/BG31/...` 与 `TB_*`，
属于**引擎数据比线上目录更全**的方向，不影响"新卡缺失"结论。

### 4.5 同 id 的字段差异（catalog vs 引擎）

| 检查项 | 命中/覆盖 | 结论 |
|--------|-----------|------|
| 名称（忽略大小写） | 0 处不同 | 英文名完全一致（catalog 未出现改名） |
| `dbf` | 28 处不同 | 集中在 token：catalog 的 dbf 常比引擎 token dbf 大 1 或等于金色 token 的 dbf（例：`BG19_010t`: 70802 vs 70791；`BG23_353t`: 93101 vs 117712）。属导出/引用差异，不是玩法差异 |
| 酒馆等级（仅 minion 且双方 >0） | 9 处不同 | `BG25_009` 5→6、`BG30_123` 3→4、`BG31_327` 3→4、`BG33_828` 5→6、`BG36_210` 4→5、`BG36_508` 4→3、`BGS_008` 5→6、`BGS_018` 5→6、`BGS_034` 2→3（catalog→engine）。**这些是真正的平衡改动候选**，升级后需以 36.6.3 CardDefs 复核 |
| 种族 | 1 处不同 | `EX1_577`（Fiendish Servant）：catalog 双种族 `BEAST+ELEMENTAL`，引擎只有 `BEAST` |
| 关键词（仅可映射的 13 个，共 16586 对） | 10 处不同 | 例：`BG26_963`/`BG27_556`/`BG34_Giant_042` catalog 有 `START_OF_COMBAT` 而引擎无；`BG30_117` 等 6 张 catalog 无 `CHOOSE_ONE` 而引擎有。可能是 catalog 关键词标注口径/引擎导出差异，需逐卡复核 |
| 同 dbf 但 id 不同 | 1 处 | `107912`: catalog `BG29_100_G` vs 引擎 `BG29_100`（catalog 金色 id 未标 `normal` 的个例） |

`TRIGGER_VISUAL`（906 张）、`AURA`、`END_OF_TURN_TRIGGER` 等内部 tag 在引擎数据里没有
等价字段，未参与比较（`catalog_keyword_coverage.unmapped_keywords`）。

### 4.6 结论

1. **卡池规模差一个 patch**：线上 36.6.3 比本地 36.2.2 多出 **84 张 BG36 新卡**
   （40 随从、30 饰品、4 黑暗赠礼、3 酒馆法术、3 法术、4 英雄/英雄技能），另有 97 张
   双人卡不属于单人引擎范围。
2. **名称/种族几乎无变化**；**酒馆等级 9 处、关键词 10 处**需要复核，属于升级时要逐项处理的
   平衡/标注差异。
3. **无法从 catalog 得到 atk/health/cost/文本改动**；要量化数值必须拿 36.6.3 的
   `CardDefs.xml`（见 §5 第 1 步）。
4. 全部原始统计（含每个 id 列表）见 [`runs/data_diff_36.6.3.json`](../runs/data_diff_36.6.3.json)，
   可重复生成：

```powershell
python -m hsbg.bridge.catalog info
python -m hsbg.bridge.catalog diff --out runs/data_diff_36.6.3.json
```

---

## 5. 若要把引擎数据升级到 36.6.3：步骤清单

> 原则：`data/` 是生成产物，**不要手改**；权威是 `hsdata/CardDefs.xml`。升级要"先数
> 据后脚本、先测试后合入"。

| # | 步骤 | 命令 / 产物 | 验收 |
|---|------|-------------|------|
| 1 | 取得 36.6.3 的 `CardDefs.xml`（从 36.6.3 客户端 `Hearthstone_Data` 提取），替换 `hsdata/CardDefs.xml` 前先备份到 `hsdata/backup_36.2.2/CardDefs.xml` | 手动/提取脚本 | XML 内含 `36.6.3.253932` 的 dbf；大小/卡片数合理 |
| 2 | 备份当前数据快照：`data/backup_36.2.2/`（已有 `backup_35.2.2/`、`backup_35.6.0/` 先例） | 复制 `data/bg_*.json` | 快照可回滚 |
| 3 | 重新生成引擎卡牌数据：`python tools/generate_bg_data.py` | `data/bg_cards.json`、`bg_pool_minions.json`、`bg_pool_spells.json`、`bg_heroes.json`、`bg_hero_powers.json`、`bg_trinkets.json`、`bg_tavern_spells.json`、`bg_quest_rewards.json`、`bg_dark_gifts.json`、`bg_anomalies.json`、`bg_summary.json` | `bg_summary.patch == "36.6.3.253932"`；各文件计数与 §4.3 对得上 |
| 4 | 更新中文本地化（可选）：`python tools/extract_zhcn.py` | `data/card_zhcn.json` | 新卡有中文名 |
| 5 | 用 catalog 做交叉校验：`python -m hsbg.bridge.catalog diff --out runs/data_diff_36.6.3.json` | 差异 JSON | `only_catalog.BG36.engine_missing == 0`（或剩余项有解释）；`tier_mismatches` 归零/逐项确认 |
| 6 | 逐项处理数值/机制改动：`bg_cards.json` 的 atk/health/cost/text 由 CardDefs 自动带出；**新关键词/机制**（BG36 的饰品、黑暗赠礼、法术、随从效果）需要更新 `hsrl2/scripts/` 与 `REGISTRY` | 代码 + 新卡脚本 | 每条新卡有脚本或明确的 no-op 记录 |
| 7 | 更新池/概率/异变/饰品数据：`hsrl2/pools.py`、`bg_pool_*.json`、`bg_anomalies.json`、`bg_trinkets.json`；活动种族/奖池按 36.6.3 调整 | 数据 + 回归 | `tools/audit_card_registry*.py`、池子测试 |
| 8 | 跑引擎回归：`python -m pytest hsrl2/tests -q`、`python -m pytest tests -q`、`python tools/smoke_random_games.py --games 8 --seed 2000` | 全绿 | 4164+ passed、crashes=0 |
| 9 | 记录升级报告（模板：`docs/reference_old/S14_DIFF_REPORT.md`）与 `docs/ENGINE_NOTES.md`，更新 `AGENTS.md` 的基线 patch | `docs/UPGRADE_36.6.3.md`（建议） | 新增/删除/翻倍/数值改动逐类可查 |
| 10 | 环境层无需改契约：`hsbg/env/spec.py` 字段稳定；新卡通过 `card_id` 词表自然生效；如新增机制改变动作空间，才升 `spec.version` 并同步 `docs/ENV_SPEC.md` | — | 观测/动作契约测试仍全绿 |

风险提示：

- **不要**把 catalog 当作数值来源（它没有 atk/health/cost）；catalog 只适合做 id/名字/等级/
  种族/关键词的**交叉校验**。
- 36.6.3 的新机制（尤其饰品、黑暗赠礼、法术/任务）可能超出当前引擎 S14 的脚本覆盖；
  升级工作量的主体不是 JSON，而是 `hsrl2/scripts` 的新效果实现与测试。
- 每次升级保留 `data/backup_*` 快照和 diff 报告，便于回滚与对比。

---

## 6. 风险与边界

### 6.1 合规/封号风险

| 行为 | 风险级别 | 说明 / 本项目立场 |
|------|----------|------------------|
| 只读 `Power.log`（本地文件） | 低（灰色） | 客户端自身会写日志；HDT 等工具长期采用。仍需遵守暴雪 EULA/用户所在地区法规；建议只在本机、本人账号、明确同意下使用 |
| 只读进程内存（HDT/AgenticAssistant 路线） | **中高（灰色）** | 与第三方 overlay/HDT 同源；技术上无注入，但"读取客户端内部状态"可能被视为外挂辅助。**本项目默认不做**，仅记录参考项目有该能力 |
| 写内存 / DLL 注入 / 修改客户端 | 高（违规/封号） | 明确违反 ToS；本项目禁止 |
| 自动点击 / 输入注入 / 自动出牌 | **高（封号）** | 暴雪重点打击；本项目**不实现**，`AgenticAssistant` 也没有 |
| 断线工具（SetTcpEntry） | 中 | 破坏对局连接；只在用户手动触发、风险自负；本项目不实现 |
| 上传/分享对局数据 | 中 | 涉及账号/昵称/第三方隐私；本项目默认本地保存、匿名化、不二次分发 |

补充环境观察：本机游戏目录里已有第三方 mod 框架 **BepInEx + HsMod**（`doorstop_config.ini`
中 `enabled=false`，当前未启用）。这类插件会修改客户端行为，**风险高于只读日志**；
本项目不依赖、不修改、不建议开启。

### 6.2 本项目的明确边界（写进设计）

1. **默认离线**：训练/评估/模拟全部离线；不参与线上自动操作，不做实时建议上传。
2. **只读**：数据桥只读 `Power.log`；不读内存、不写游戏目录、不注入、不点击。
   游戏目录访问仅限读取（本报告分析时也未修改）。
3. **不采集隐私**：不采集昵称/账号/密码/BattleTag；对局 id 用哈希；原始日志/内存不上传。
4. **不复制参考项目资产**：`catalog.json` 仅作本地只读校验参考；不打包进本项目发行物、
   不再分发（其许可证/来源以发行包内声明为准）。
5. **数据只用于离线训练**：真实 episode 用于 BC/评估；模拟器仍是训练主环境。

### 6.3 对采集路线的建议

- **最小可行（推荐）**：Power.log only → 本解析器 → 本地 JSONL → 离线 BC/评估。
  证据：AgenticAssistant 用日志就能重建动作/战斗/对手战团；HDT 社区的 `HDT_INTERFACE`
  也证明这些字段足够做建议特征。
- **不进内存**：虽然 AgenticAssistant 用内存提高实时性，但封号/合规风险与本项目"离线训练"
  目标不匹配；日志的延迟（秒级）对离线采集无影响。
- **需要更强数据时**：优先增加"用户手动确认的操作标签"（例如回放时人工标注），而不是
  读内存或自动点击。

---

## 7. 最小可行采集路线（MVP）

```text
[炉石客户端] --只读--> Power.log
       |
       v
hsbg/bridge/powerlog.py  (feed 增量解析 / 实体 tag 表 / block 栈)
       |
       +--> game_state() 快照（对齐 hsbg/env/spec.py Observation 子集）
       +--> 语义动作（PLAY block / DebugPrintOptions / EntityChoices）
       +--> 战斗结果（TRIGGER block / 英雄 ATTACK）
       |
       v
data/real_games/<date>/<episode>.jsonl  (本报告 §3.5 schema，匿名化、本地)
       |
       v
离线过滤：只保留 confirmed=true 且 gaps 可解释的 step → BC / 评估
```

落地顺序：

1. **今天**：确认 `log.config`（已就绪）→ 打一局 → `python tools/powerlog_probe.py`
   能看到 `CREATE_GAME/Player/FULL_ENTITY/TAG_CHANGE/BLOCK_START` 与 turn 推进。
2. **下一步**：把 `game_state()` 的输出补成 §3.5 的 `observation` 字段（随从/手牌/酒馆/
   饰品/对手最近战团/选项），并保存 episode JSONL。
3. **再下一步**：用 `hsbg/env/spec.py` 的 `Observation` 做一次字段对齐测试（抽取 1 局，
   验证 `EntityToken` 字段齐全、缺省/掩码正确）。
4. **训练**：先 BC（只学 confirmed 动作），再评估；模拟器数据仍为主训练来源。

验收命令：

```powershell
python -m pytest tests/test_bridge_powerlog.py tests/test_bridge_catalog.py -q   # 全绿
python tools/powerlog_probe.py                                                  # 有日志解析；无日志走样例
python -m hsbg.bridge.catalog diff --out runs/data_diff_36.6.3.json              # 差异 JSON
```

---

## 8. 代码与交付索引

| 文件 | 作用 |
|------|------|
| `hsbg/bridge/powerlog.py` | Power.log 增量解析器原型：`PowerLogParser.feed()`、事件、实体 tag 表、block 栈、`game_state()`、文件 tail、隐私开关 |
| `hsbg/bridge/catalog.py` | AgenticAssistant `catalog.json` 只读适配器（`AACatalog`）+ `compare_with_engine_data()` + CLI（`info/get/diff`） |
| `tools/powerlog_probe.py` | 真实日志探针/样例自测：路径探测、摘要（行数/实体/turn/tag/block/棋盘/选项） |
| `tests/test_bridge_powerlog.py` | 解析、tag 更新、block、未知行容错、tasklist 过滤、隐私、JSON 可序列化等 |
| `tests/test_bridge_catalog.py` | catalog 加载/查询/金色折叠/皮肤、差异统计一致性、BG36 新卡检测、写盘 |
| `hsbg/bridge/rizling.py` | rizling 发行包版本跟踪/目录对齐（`read_product_db`、`detect_version_signals`、`compare_catalog_with_project` 等；详见 `docs/VERSION_SYNC.md`） |
| `hsbg/bridge/state_corpus.py` | 真实战斗边界状态语料导出（trace/XML → `runs/state_corpus/states.jsonl`） |
| `tests/test_state_corpus.py` | 语料结构/隐藏标注/池覆盖/抽样回溯一致性 |
| `hsbg/bridge/live_log.py` | Power.log 实时阶段监听器（会话/回合/阶段/选择窗口/我方状态事件） |
| `tests/test_bridge_live_log.py` | 增量 tail/轮转/截断/容错 + 两个真实 Power.log 回放 |
| `runs/data_diff_36.6.3.json` | 36.6.3 vs 36.2.2 的完整量化差异（本次生成） |

复现：

```powershell
cd C:\HSagent
python -m pytest tests/test_bridge_powerlog.py tests/test_bridge_catalog.py -q
python tools/powerlog_probe.py
python -m hsbg.bridge.catalog info
python -m hsbg.bridge.catalog diff --out runs/data_diff_36.6.3.json
```

本次实测结果：

- `tests/test_bridge_powerlog.py` + `tests/test_bridge_catalog.py`：**28 passed**；
- `python tools/powerlog_probe.py`：本机无真实日志 → 输出"未找到真实 Power.log + 已检查路径"
  并完成样例解析（33 行 / 5 实体 / 2 玩家 / turn 2 / PLAY+TRIGGER block），exit 0；
- `runs/data_diff_36.6.3.json`：已生成（UTF-8，`generated_by = hsbg.bridge.catalog.compare_with_engine_data`）。

---

## 9. 真实战斗边界状态语料（state_corpus）

> 目的：给离线批量差分（BobsBuddy oracle / diff-harness）提供**真实对局状态分布**，
> 而不是"基础卡面"。用法见 `hsbg/bridge/state_corpus.py` 与
> `runs/state_corpus/schema.json`。

### 9.1 输入与输出

| 输入（只读） | 内容 |
|--------------|------|
| `runs/official_traces_powerlog{,2,3}/` | 真实 Power.log 轨迹（去重后 24 场战斗，有 card_id/关键词/事件流） |
| `runs/official_traces_hdt/` | HDT BobsBuddy 会话抽取的 677 场真实战斗（双方战团 + 官方结果） |
| `runs/bg_last_games_20261018.xml` | HDT `BgsLastGames.xml` 45 局终局战团（仅本地玩家一侧，含数值 tag） |

输出：

| 文件 | 内容 |
|------|------|
| `runs/state_corpus/states.jsonl` | 一行一个状态对（746 行，10.6 MB） |
| `runs/state_corpus/schema.json` | 字段说明（JSON Schema 风格，含 `minion`/`warband` definitions） |
| `runs/state_corpus/index.json` | 生成元数据、来源、密度/覆盖/抽样校验汇总、`states.jsonl` sha256 |
| `reversed/rea/state_corpus_report.md` | 覆盖率报告（卡集合、关键词组合、stat 分位、visible/hidden、缺失字段原因） |

### 9.2 实测规模

| 指标 | 值 |
|------|----|
| 状态对 | **746**（powerlog 24 + HDT 677 + XML 45；powerlog 分批目录间 2 条重复 trace 已去重） |
| 随从记录 | **7128**（全部有 card_id/atk/health；`minions_with_hidden_fields=0`） |
| 唯一 card_id | **524**（当前池内随从覆盖 176/273；97 个池内卡未在语料出现） |
| 板面级 `hidden_state` | **45/746 = 6.03%**（全部来自 XML 源：只有本地玩家终局板，对手隐藏） |
| 上下文级 `hidden_context` | 746/746（HDT 缺英雄血量/护甲/等级；所有源都缺 trinket/anomaly/quest——已按字段列出） |
| 结果分布 | HDT：win 276 / loss 204 / tie 68（其余 154 条无官方 result）；XML 有 placement 1–8 |
| 关键词 | taunt 1248、divine_shield 823、reborn 575、windfury 93、venomous 87、cleave 75、stealth 14、poisonous 2 |
| ScriptData | num1 2652、num2 1688、num3 466、num4 131 个 minion 有值；附魔派生 589 |
| stat 分位（atk） | p10 2 / p50 11 / p90 194 / p99 1697 / max 20437（真实滚雪球分布，非卡面 1–7） |
| 抽样回溯 | 30 条语料 ↔ 原始 trace/XML：**30/30 通过**（card_id/atk/health/golden/keywords 完全一致） |

### 9.3 字段与"hidden"语义

每个状态对：

- `source`（`powerlog`/`hdt_bobsbuddy`/`bg_last_games_xml`）、`trace_id`、`episode_id`、
  `combat_index`、`turn`、`boundary`（`combat_start` / `game_end_final_board`）、
  `official_result`/`final_placement`；
- `player`/`opponent`：`hero_card_id`、`hero_power_id`、`hero_power_used/data`、
  `health/armor/tier`、`minions[]`、`hand[]`、`detected`、`hidden_fields/reasons`；
- **Deity（旧神）六字段**（每侧）：`deity_card_id`、`deity_atk`、`deity_health`、
  `deity_progress`、`deity_awakened`、`deity_sigil_card_id`，另带
  `deity_hidden`/`deity_source`/`deity_hidden_reason`/`deity_missing_fields`；
- 每个 minion：`slot`（=站位/ZONE_POSITION）、`card_id`、`atk`、`health`、
  `golden`、`tier`、`races`、`keywords` + `keyword_flags`（含 divine_shield/taunt/
  windfury/poisonous/venomous/reborn/cleave/stealth/elusive/immune）、
  `script_data_num_1..6`、`enchantment_derived`、`raw_tags`、`hidden_fields`。

关键口径：

1. **atk/health/golden/keywords/script_data 全部来自真实日志/trace 快照**，不插值；
2. 卡面只用于补 **静态身份**（`tier`/`races`/`name`），字段旁标 `*_source="carddb"`；
3. 不可见就标 `hidden_state`/`hidden_context` 并写原因，绝不猜测填充：
   - XML 对手整个隐藏、HDT 英雄血量/等级缺失、trace schema 不含 trinket/anomaly/quest；
   - XML 旧 tag（124 个里 41 个不在官方 255130 枚举）保留为 `tag_<id>` + `unmapped_tag_ids`；
4. 语料保留的是**该时间点的真实状态**（随对局历史滚雪球），不是基础卡面；
5. XML 的 `Player` 账号 id 只用于派生匿名 `trace_id`，**不写进语料**（测试守门）。

### 9.4 Deity（旧神）字段与 tag 映射

BobsBuddy 的 `Minion.IsDeity` / `Player.FriendlyDeitySigil` 需要显式输入；37.0
Deity 是**隐藏状态**，只能从 Power.log 的 `BG_OldGod` objective / `BGFYM_*`
token 重抽（HDT/XML 源没有 → 标 hidden，不猜）：

| 字段 | Power.log 证据 | 口径 |
|------|----------------|------|
| `deity_card_id` | `BG_OldGod.BACON_EVOLUTION_CARD_ID` / `TAG_SCRIPT_DATA_NUM_6`（dbf 130610/132532 → `BGFYM_000/011`），或 `BGFYM_*` token card id | 真实观测 |
| `deity_atk` | `BG_OldGod.TAG_SCRIPT_DATA_NUM_2`（对手 objective）；本地玩家 `BACON_OLD_GOD_ATTACK` | 战斗边界快照 |
| `deity_health` | `BG_OldGod.TAG_SCRIPT_DATA_NUM_3`；本地玩家 `BACON_OLD_GOD_HEALTH` | 同上 |
| `deity_progress` | 战斗开始按卡面 "each combat" 重置为 **0**；`QUEST_PROGRESS` 是战斗内进度 | 规则 + 边界口径 |
| `deity_awakened` | 战斗开始为 **False**（awaken 发生在战斗内） | 规则 + 边界口径 |
| `deity_sigil_card_id` | `BG_OldGod.BACON_DEITY_SIGIL=1` → `"BG_OldGod"` | 真实观测 |

- 覆盖：746 states 中 **7 个 powerlog 状态双方均有 Deity**（turn 14–18，均来自
  `runs/powerlog_2214/Power.log` 的 Aberration 局）；六字段侧覆盖率各 **14/1492=0.94%**。
  HDT/XML 源没有 Deity 实体：只有**卡面文本含 Deity / BGFYM token** 的侧才标
  `deity_hidden=true`（HDT 5 侧、XML 1 侧，原因 `deity_not_in_source` /
  `deity_not_in_final_board`）；其余侧无 Deity 信号 → `deity_source="not_applicable"`
  且 `deity_hidden=false`（不混入 unsupported:deity）。
- state23/268 基础状态（trace `ff75d9a57e3babce`, turn18）实测：
  player `BGFYM_000 33/33`、opponent `BGFYM_000 87/86`，双方 `BG_OldGod` sigil、
  progress=0、awakened=false——供 diff-harness 的 BB payload 使用。
- 不猜：`deity_progress`/`deity_awakened` 在边界固定 0/False；没有 objective/token
  的一侧写 null + hidden，不用卡面或上一场状态外推。

### 9.5 复现/验收

```powershell
python -m hsbg.bridge.state_corpus export
python -m hsbg.bridge.state_corpus validate
python -m pytest tests\test_state_corpus.py -q
```

本次实测：`export` → 746 states / 7128 minions / 抽样校验 30/30；测试 **7 passed**。
本模块只读 `runs/`、`reversed/` 与 `data/`，不修改引擎/环境/卡片数据。

---

## 10. Power.log 实时阶段监听器（live_log）

> 模块：`hsbg/bridge/live_log.py`；测试：`tests/test_bridge_live_log.py`。
> 用途：把"现在是什么阶段/第几回合/有没有选择窗口/对局结束没有/我方 gold·tier·
> 英雄血量变了没"以结构化事件喂给 bot runner，让 runner 决定**何时**操作。

### 10.1 数据源与增量读取

- 自动定位最新 `C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_*/Power.log`
  （也兼容 `Logs\Power.log`；按 `(mtime, 目录名)` 取最新）；
- 记录 byte offset，增量 tail；同一路径被截断/重写（size 变小、inode 变化）或出现
  更新的会话目录时：发 `game_over(reason="log_truncated"/"file_switched")` →
  重置解析器 → `session_start`，从新文件 offset 0 读；
- 半行留在 buffer，下次 poll 再拼；超过 4 MiB 的异常半行丢弃并记 `error`；
- 复用 `PowerLogParser` 口径（只解析 `GameState.*`，默认跳过 `PowerTaskList.*`）；
  对 HDT 提取片段缺 `D hh:mm:ss` 前缀的首行做容错补前缀。

### 10.2 API

```python
from hsbg.bridge.live_log import LiveLogWatcher

w = LiveLogWatcher(path=None, poll_interval=0.05)   # None=自动发现
w.on("turn_start", lambda ev: print("turn", ev.data["turn"]))
w.on("*", callback)                                 # 全部事件

# 方式 A：后台线程（runner 不需要自己轮询）
w.start()
...
w.stop()          # 会 flush 未完成的 choice_window；若对局未结束补 game_over(watch_end)

# 方式 B：手动轮询
for event in w.poll():        # 只返回本次新增事件；同时触发回调
    ...
state = w.snapshot()          # 当前 parser 快照 + local_player_id/gold/tier/hero_health
```

线程安全：内部 `RLock`；`poll()` 与后台线程二选一（同时用会把事件分到两边）。
异常不中断后台循环：文件暂时不可读/被删会发 `error` 事件并继续重试。

### 10.3 事件表

| type | data | 触发 |
|------|------|------|
| `session_start` | `path/session_id/session_index/reason` | 首次 attach / 换会话 / 截断重建 |
| `game_start` | `game_index/seed/local_player_id` | `CREATE_GAME` |
| `turn_start` | `turn/previous/phase` | GameEntity `tag=TURN`（忽略玩家/Bob 实体上的 TURN 副本） |
| `phase_change` | `phase="recruit"\|"combat"/previous/turn` | GameEntity `BACON_IN_COMBAT_PHASE` 0/1 |
| `game_over` | `reason/result/turn/placement/local_player_id` | GameEntity `STATE=COMPLETE`，或本地 Player `PLAYSTATE∈{LOST,WON,TIED,...}`，或日志结束 flush |
| `choice_window` | `kind="options"\|"choices"` + `options[]` 或 `choice.entities{}` + `local_player_id/turn/phase` | `DebugPrintOptions` 块 / `DebugPrintEntityChoices` 块（含可选实体 id/card_id/controller） |
| `player_state` | `player_id/gold/tier/hero_health/changed[]/sources` | 本地玩家 gold/tier/英雄血量变化 |
| `error` | `message/log_path` | 文件缺失/读取/超长行等；不中断 |

`choice_window` 里的 options **包含错误码/费用/主实体**（如
`TB_BaconShop_DragBuy` / 刷新按钮 / 英雄技能），runner 可据此决定操作；但
**Power.log 没有酒馆商店 offer 的具体卡牌**——要拿到 offer 必须用 rea-operator 的
内存读取（见 §9/工具索引），本模块不读内存。

### 10.4 本地玩家识别

默认自动推断（可传 `local_player_id=` 覆盖）：

1. `DebugPrintGame` 的 `PlayerID=.., PlayerName=..` → 名字表；
2. `DebugPrintEntityChoices` 的 `Player=<名字>`（选择只发给本地玩家）→ 映射到 PlayerID；
3. `DebugPrintOptions` 的本地控制实体（`DragBuy/DragSell/刷新/升级/冻结`按钮）
   上的 `player=`；
4. 2 人局（练习/Bob）：`GameAccountId` 非 0 的那一方；
5. 8 人局若以上都未出现，保持 `local_player_id=None`（不盲猜 `PlayerID=1`），
   等选择窗口/options 信号，或由 runner 显式传入。

我方状态来源按优先级：Player 实体 tag → `Bacon_TagTransferPlayerE` 标签转移实体
（练习/Bob 局）→ 本地英雄实体（`PLAYER_ID`+`CARDTYPE=HERO`，血量/等级）。

### 10.5 真实日志回放实测

| 文件 | local | 事件 |
|------|-------|------|
| `runs/powerlog_2214/Power.log`（31.3 MB） | 3 | session_start 1 / game_start 1 / **turn_start 1..20** / **phase_change 19**（combat→recruit 交替）/ player_state 91 / choice_window 162（151 options + 11 choices）/ **game_over 1（lost，placement=5）** |
| `runs/powerlog_2240/Power.log`（30.2 MB） | 4 | game_start 1（首行缺前缀也容错识别）/ turn_start 1..20 / phase_change 19 / player_state 81 / game_over 1（lost）/ choice_window 159 |

测试还覆盖：增量 append、日志截断重置、`Hearthstone_*` 目录轮转到新会话、
后台线程 + 回调、缺文件报错后恢复。`python -m pytest tests/test_bridge_live_log.py -q`
→ **10 passed**。

### 10.6 局限（给 runner 的明确边界）

1. **看不到酒馆商店 offer**：Power.log 只记录服务端已下发的 Power 消息（购买/刷新
   的选项与结果），不包含商店 7 个 slot 的卡牌状态；需要 rea-operator 内存读取补。
2. 日志有延迟/可能乱序：`choice_window` 表示"服务端已下发选项"，不保证立刻操作；
   等 `turn_start`/`phase_change`/`player_state` 稳定后再决策。
3. 不自动点击、不读内存、不写游戏目录：本模块只产生事件；真正操作由用户授权的
   runner 外部实现（风险与合规见 §6）。
4. HDT 提取片段可能缺首行前缀或缺少 `STATE=COMPLETE`；此时 `drain()/stop()` 的
   `flush` 会补 `game_over(reason="watch_end")`，字段 `result/placement` 可能为空。

---

## 附：快速事实核查表（写报告/汇报可直接引用）

| 事实 | 数值/结论 |
|------|-----------|
| AgenticAssistant 版本 | 0.5.3，built 20261018-001807 |
| 打包 Python | 3.13.16；OpenSSL 3.5.9 |
| 发行包文件数 | 1012（含哈希清单） |
| 业务代码 PYZ 模块数 | 251；其中 `bgassistant/bgcontroller` 27 个 |
| 有没有 `torch/onnx/tensorflow/numpy` | 没有 |
| 有没有输入注入库/API | 没有 |
| 有没有模型权重文件 | 没有 |
| 内存读取 | 有（只读，`QUERY_INFORMATION\|VM_READ`，无注入） |
| Power.log 解析 | 有（`bgcontroller.client.powerlog`，`GameState.*` only） |
| 远程服务 | `https://rizling.top/assistant`（访问码 + TLS + DPAPI 暂存） |
| 更新 | Ed25519 验签 + SHA256 + HTTPS，侧装到 `%LOCALAPPDATA%` |
| catalog 版本 | `36.6.3.253932`，3983 卡（2749 本体）+ 653 皮肤 |
| 引擎数据版本 | `36.2.2.249896`（S14），raw 3683 / 本体 2560 |
| 交集 / 线上缺 / 引擎多 | 2435 / 314 / 125 |
| BG36 新卡缺失 | 84（minion 40、饰品 30、dark_gift 4、spell 3、tavern_spell 3、hero/hero_power 4） |
| 本机 Power.log | 暂无（Logs 目录不存在；`log.config` 已启用 `[Power]`） |
