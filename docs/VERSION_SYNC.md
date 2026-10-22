# VERSION_SYNC — 游戏补丁 / rizling 发行包的版本跟踪与数据同步

> 目标：把"游戏什么时候更新了、本项目数据落后没有、rizling 参考包跟没跟上"
> 变成**可检测、可复现、可回归**的流程。
>
> 本文覆盖三件事：
> 1. **rizling 最新包 0.6.1 的静态分析结论**（下载/校验/与 0.5.3 对比/能力边界）；
> 2. **rizling catalog 与本项目 37.0.0.255130 数据的对齐量化**；
> 3. **版本检测 + 标准同步步骤**（`.product.db` → hsdata tag → CardDefs 合并 →
>    生成数据 → 差分 → 回归；复刻 `tmp_255130/deliver/tools/upgrade_engine_data.py` 模式）。
>
> 产物：`reversed/rizling_latest/`（只读分析物）、`hsbg/bridge/rizling.py`
> （检测/对比函数）、`tests/test_bridge_rizling.py`（17 项测试）。
> 全程**只读**：未运行下载的 exe、未登录、未联网认证、未修改游戏目录与 `data/`。

---

## 0. 一键流水线（推荐入口）— `tools/version_sync.py`

> 本页 §1–§10 是 rizling 专题分析与手工 playbook；**日常版本同步用下面这一条命令即可**，
> 它把 §4 的四信号检测、§5 的 S1–S6 数据面流程（取数/合并/生成/差分/应用）自动化。

```powershell
cd C:\HSagent

# 只检查：四信号 + 结论（写 runs/version_sync/<timestamp>.json）
python tools\version_sync.py --check

# 预演：取数 → 合并 CardDefs → 生成 → 差分；只写 tmp_version_sync/，不写 data/
python tools\version_sync.py --dry-run

# 应用（必须 --yes）：备份 data//hsdata/ → 复制新数据 → pytest + smoke；
# 任一步失败自动回滚
python tools\version_sync.py --apply --yes
```

**四信号**（与 §4.1 一致，工具内自动交叉核对）：

| # | 信号 | 来源 |
|---|------|------|
| 1 | 本机游戏 build | `C:\Program Files (x86)\Hearthstone\.product.db`（只读） |
| 2 | 项目数据 patch | `data/bg_summary.json.patch` |
| 3 | hsdata 最新 tag | GitHub `HearthSim/hsdata/tags`（失败→缓存→`reversed/hsdata_*`） |
| 4 | rizling 最新包 | `latest.zip` 的 `release-manifest.json`（HTTP Range 只读 ZIP 局部，约 0.3–0.4MB，不落 54MB 全包） |

**状态/动作**：`up-to-date`（无需动作）/ `update-available`（→ `--dry-run` →
`--apply --yes`）/ `waiting-for-hsdata`（客户端已更新但数据源未发 tag：等待，不要
手工造数据）/ `unknown`（网络失败且无缓存 → 联网重试或 `--offline`）。

**安全边界**：`--check`/`--dry-run` 绝不写 `data/`、`hsdata/`；`--apply` 必须
`--yes`，先备份到 `data/backup_<old_build>/`、`hsdata/backup_<old_build>/`，
pytest 或 smoke 失败自动回滚；build 未变化时 no-op；不运行下载的 exe、不改游戏目录。

**产物**：`runs/version_sync/<timestamp>.json`（检查）、`dryrun_<tag>.json`（预演）、
`apply_<tag>.json`（应用，含 `rolled_back`）、`tmp_version_sync/data_<tag>/`（新数据）、
`tmp_version_sync/report_<tag>.md|json`（差分）。

**模拟/离线**：`--build <b>` / `--project-patch <p>` / `--target-tag <tag>` 可覆盖
信号做演练；`--offline` 只用缓存与本地 `reversed/`。详见
`python tools\version_sync.py --help`。

> 需要**引擎结构改动**的版本（新种族/card_type/机制脚本），`--apply` 会因 fail-loud
> 测试失败自动回滚，此时回到下面 §5 的人工流程（或参考 `tmp_255130/deliver/
> UPGRADE_REPORT.md` 的迁移包模式）。

---

## 0. TL;DR（先看结论）

| 问题 | 结论 |
|------|------|
| rizling 最新包版本？ | **AgenticAssistant 0.6.1**，built `20261018-160659`，`public_release=true`，文件 2031 个 |
| 它自报的规则/数据版本？ | `game_version = 36.6.3.253932`（manifest + catalog 一致；新版《使用说明》不再写版本行） |
| 跟上了本机的 37.0.0.255130 吗？ | **没有**。manifest/catalog 仍是 36.6.3；客户端代码里**搜不到** `37.0.0/255130/249896/36.6.3` 任何版本常量；Power.log 解析器/GameTag 映射/内存读取/protocol 模块与 0.5.3 **字节级完全相同** |
| catalog 有什么新东西？ | 从"公共元数据"升级为**带数值/文本/卡池标记**：新增 `atk/hp/armor/cost/text/text_zh/golden/available_in_solo_pool/...` 等 20 个字段；**3983 个 id 与 0.5.3 完全相同**、共享字段 0 变化、`game_value` 仍 36.6.3 |
| 有没有本地模拟器/模型/自动点击？ | **仍然没有**。343 个 PYZ 模块里无 `torch/onnx/tensorflow/numpy`、无输入注入库；新增模块全是 UI/悬浮窗/卡图/本地展示；战斗模拟明确在服务器（`战斗预测说明.txt`）；热键用 `RegisterHotKey` 且不采集输入 |
| 和本项目 255130 数据吻合度？ | catalog 2749 本体 vs 项目 2649 本体；**交集 2526（覆盖 91.9%）**；catalog 的 **BG36 262 张全部命中（missing=0）**；数值差异 11 处**全部是 `is_reference_only` 构造/引用卡**（非 BG 池卡 0 差异）；卡池：随从 256→273、酒馆法术 70→76、英雄 116→118（项目 37.0.0 比 36.6.3 多出的池变化） |
| 版本检测怎么做？ | 三个信号：① 游戏 `.product.db` 的版本串；② HearthSim/hsdata 的 build tag；③ rizling manifest 的 `version/game_version`；再加 ④ 本项目 `data/bg_summary.json.patch` 交叉核对。**已封装**：`python tools\version_sync.py --check`（§0） |
| 同步流程怎么走？ | 抓 hsdata（tag=build）→ 合并 `CardDefs.xml + CardDefs.Bacon.xml`（255130 起拆分）→ `generate_bg_data.py` 试跑 → 差分评审 → 按迁移包模式备份/替换 `data/` → 回归 + 差分 harness → 文档/哈希锁定（§5）。**数据面已自动化**：`--dry-run` / `--apply --yes`（§0） |
| 触发频率？ | 游戏补丁（build 变化）立即；rizling 版本/`game_version` 变化后做一次"参考对齐"；每次 `data/` 变更后跑官方数据/枚举测试 + rizling 对齐；每周一次轻量漂移检查（§6） |

---

## 1. 为什么需要版本跟踪

本项目的"数据"来自两个方向：

- **官方权威**：游戏安装版本对应的 HearthSim/hsdata `CardDefs*.xml`（数值/卡池/枚举）；
- **第三方参考**：rizling 的 AgenticAssistant 发行包（公共卡牌目录 + 自报规则版本 +
  python-hearthstone 枚举）。

两者都可能**滞后**或**超前**：本项目数据已升级到 `37.0.0.255130`，而 rizling 0.6.1
仍写 `36.6.3.253932`。如果不做版本跟踪，就会出现：

1. 把"线上旧目录"当权威去"纠正"已经升级的数据（方向错误）；
2. 把"rizling 滞后"误判成本项目数据错误；
3. 游戏再次更新后，没人知道该抓哪个 build、该跑哪些脚本。

因此本流程把版本信号拆成**四个独立来源**并交叉核对（§4.1），把"是否要升级"变成
可判定的动作，而不是靠记忆。

---

## 2. rizling 0.6.1 专题（只读静态分析）

### 2.1 下载与完整性校验

| 项 | 值 |
|----|----|
| URL | `https://rizling.top/assistant/updates/latest.zip`（用户提供） |
| 大小 | **53,852,237 B** |
| sha256 | `B3C3FFEFCBD4A7B33E19B876A580844135C2AF120CE5E486290F4505EFA3BC1F` |
| zip 条目 | 2083（含目录） |
| 关键文件 vs manifest 哈希 | `AgenticAssistant.exe`、`AgenticUpdater.exe`、`使用说明.txt`、`启动离线预览.cmd`、`战斗预测说明.txt`、`catalog.json`、`game_tags.json`、`card-art.json` **全部一致** |
| 整包保留 | **否**（54MB，避免误提交；`PACKAGE_INFO.json` 记录了 URL/大小/sha256，需要时重下校验） |

> 边界说明：我们校验的是**包内 manifest 的文件内容哈希**；发行包的 Ed25519 发布签名
> 由 `AgenticUpdater.exe` 在执行时验证，本轮按任务要求**没有运行 exe**，因此未做
> 独立签名验证。若后续要以"可执行"方式使用该包，必须另行按官方更新流程验签。

分析产物全部在 `reversed/rizling_latest/`，索引见该目录的 `README.md`。

### 2.2 0.6.1 是什么

从 manifest 的模块清单 + PYZ 静态分析看，0.6.1 是**界面/悬浮窗大版本**：

| 变化 | 证据 |
|------|------|
| 客户端版本 0.5.3 → **0.6.1** | `release-manifest.version` |
| `built` 20261018-001807 → **20261018-160659** | manifest |
| 客户端源文件 15 → **24** | `client_sources` 新增 `desk.py / widgets.py / tracker.py / overlay_host.py / overlay_calibration.py / hotkeys.py / artwork.py / hud.py / demo.py` |
| 业务模块 27 → **36** | `bundled_project_modules` |
| 打包文件 1012 → **2031** | 新增 `_internal/bgassistant/data/artwork/web/*.webp`（942 张 webp 卡图 + 64 张 png 演示图）+ `PIL` 运行时 + `demo-combat.json` + `app.ico` |
| exe 2,833,498 → **3,518,316 B**；PYZ 251 → **343 模块** | 静态解析（见 `STATIC_ANALYSIS.json`） |
| UI 拆分/新增 | `bgassistant.ui` 反而缩小（29,135 → 24,015 pyc 字节），功能拆到 `desk/widgets/overlay_host/hud/tracker` |
| 采集/展示增强 | `reader` 新增首次攻击、存活数、HUD presentation 字段；`trajectory` 新增 `visible_ranks`；`history` 新增 `hud_upgrades/hud_triples` 观测时间线；`records` 小改 |
| 数据目录迁移 | `settings` 新增 `BGASSISTANT_DATA_DIR` 环境变量 + `L:/AgenticBattlegroundsAssistantClient` 默认逻辑 + ACL 加固 |
| 卡图 | 新增 `bgassistant.artwork`：固定 HTTPS 主机 `art.hearthstonejson.com`，只对 catalog 内卡 id 拉取 `{zhCN|enUS}-{256|512}-{card|portrait}-<id>.png`；有缓存上限、无重定向/无 cookie/无任意 URL |
| 热键 | 新增 `bgassistant.hotkeys`：`RegisterHotKey/WM_HOTKEY`，docstring 明确 *"Opt-in Windows shortcuts without keyboard hooks or input collection."* |
| 战斗预测 | 新增 `战斗预测说明.txt`：*"所有战斗模拟在服务器执行。客户端只显示概率和伤害统计，不接收内部模拟轨迹。"* |
| 离线预览 | 新增 `启动离线预览.cmd`，说明明确它"只展示合成界面，不读取游戏或连接后台" |

### 2.3 与 0.5.3 的核心代码差异（字节级）

对两个 exe 的 PYZ 逐模块解压后比 sha256（脚本见临时分析工具；结果固化在
`STATIC_ANALYSIS.json`）：

| 类别 | 模块 |
|------|------|
| **完全一致（未改一行）** | `bgcontroller.client.powerlog`（Power.log 解析）、`mapping`、`mechanics`、`tags`、`mono`、`memory`、`choices`、`leaderboard`、`state`、`bgassistant.protocol`（DTO 契约）、`network`、`telemetry`、`diagnostics`、`disconnect`、`updates`、`update_key` |
| 有改动 | `bgassistant`（包 docstring/版本行为）、`__main__`、`catalog`（新字段加载/检索）、`reader`（HUD 展示）、`settings`（数据目录）、`trajectory`（visible_ranks）、`ui`（拆分）、`bgcontroller.records`、`bgcontroller.client.history`（HUD 升级/三连时间线） |
| 新增（9 个客户端模块） | `artwork / demo / desk / hotkeys / hud / overlay_calibration / overlay_host / tracker / widgets` |
| 删除 | 无 |

**结论**：0.6.1 **没有**更新 Power.log 解析器、GameTag 映射、内存布局、协议 DTO；
它仍是 **36.6.3 的读法**。客户端代码里也没有任何 `37.0.0 / 255130 / 249896 / 36.6.3`
硬编码版本串（版本来自数据文件/manifest）。

### 2.4 能力边界：仍然没有本地模拟器/模型/自动操作

| 检查 | 结果 |
|------|------|
| PYZ 模块里 `torch/onnx/tensorflow/numpy/sklearn` | **无** |
| 输入注入库/API（`pyautogui/pynput/keyboard/mouse/SendInput/PostMessage/keybd_event`） | **无** |
| `liveclient/runner/model/simulator` 模块 | **无** |
| 模型权重文件（`.pt/.onnx/.bin/weights`） | **无**（manifest 2031 文件里也没有） |
| 战斗模拟 | 服务器侧；客户端只显示概率/伤害分布（`战斗预测说明.txt` 明说） |
| 自动出牌/自动点击 | 没有；`hotkeys` 只是 UI 快捷键，不安装键盘钩子、不采集输入；`使用说明`："助手不会自动执行 AI 操作" |
| `offline_smoke` | `catalog_cards: 3983`、`no_remote_or_reader: true`（demo 模式不联网/不读游戏）、`forbidden_imports: []` |
| 内存读取（旧能力） | 仍在（`bgcontroller.client.memory/mono`，只读 `QUERY_INFORMATION\|VM_READ`，无注入），与 0.5.3 字节级相同——这是参考项目的能力，**本项目不采用** |

> 新增的 `hud` 模块值得借鉴：docstring 说它是 *"Pure local HUD metadata from already
> observed, public game information. This module neither reads a process nor contacts a
> server."*，字段包括 `current_rank/own_placement_candidate/own_placement_final`、
> `hud_upgrades[{player_id,turn,from_tier,to_tier,confirmed}]`、
> `hud_triples`、`visible counters` 等——这些是"从可观测 tag 推导 UI 展示字段"的
> 好示例，可参考到本项目真实对局观测（但不要依赖其闭源实现）。

### 2.5 "官方实现/模拟器"线索核查

任务要求确认 rizling 包里是否有"官方实现/模拟器"线索。结论：**没有任何官方实现或
可离线运行的战斗模拟器线索**，与 rea-analyst 对官方客户端的结论一致：

- 官方客户端 `Assembly-CSharp.dll`（14,390 类型 / 113,222 方法）里 `Simulate*` 仅 6 个，
  且全部与战斗无关（网络断连模拟/Quest 进度模拟等）；**客户端不含战斗裁决器**，
  战斗由服务器下发 `PowerTaskList`——详见 `docs/OFFICIAL_EXACTNESS.md` §3 与
  `reversed/net/SUMMARY.md` §2.1；
- 本机 HDT 里的 **BobsBuddy** 是**社区插件**（第三方，非官方）的离线战斗模拟器，
  不属于 rizling 包；rizling 0.6.1 的 `战斗预测说明.txt` 也明确"所有战斗模拟在
  服务器执行，客户端只显示概率和伤害统计，不接收内部模拟轨迹"；
- rizling 的 `bgcontroller` 包 docstring 仍保留旧 bot 项目描述（"model input →
  operation → mouse gestures"），但该 bot 的 `LiveClient/mouse backend/runner/model`
  **没有打进 0.6.1 发行包**（36 个 bundled 模块与 PYZ 清单可验证），`reader` 明确
  "No LiveClient, mouse backend, runner or model imports"。

### 2.6 0.5.3 → 0.6.1 的数据文件差异

| 文件 | 0.5.3 | 0.6.1 | 结论 |
|------|-------|-------|------|
| `catalog.json` | 886,570 B；3983 卡（2749 本体）+653 皮肤；只有公共元数据 | 2,614,867 B；**同样 3983 卡/653 皮肤/同一 `game_version`**；新增 20 个字段（stats/text/pool/golden/hero_power/buddy…） | **纯增强，不改旧值**：3983 个 id 相同，`name/name_zh/tier/races/keywords/normal/activatable/activation_cost` 全部 0 差异 |
| `game_tags.json` | 49,104 B，sha256 `1da4d310…` | **完全相同**（sha256 一致） | 枚举没有更新 |
| `使用说明.txt` | 有"当前规则版本 36.6.3.253932"行 | 删除了该行；新增界面/数据目录/隐私说明 | 版本只写在 manifest/catalog |
| 战斗预测 | 无独立说明 | `战斗预测说明.txt`（服务器侧模拟） | 明确能力边界 |
| 卡图 | 无 | 942 webp + 64 png + `card-art.json` + PIL | 新增网络/资源面（固定 HearthSim 主机） |

catalog 新字段（20 个）：`armor / atk / hp / cost / text / text_zh / text_alt /
text_alt_zh / golden / hero_power / buddy / spellcraft / associated_races /
available_in_solo_pool / available_in_duos_pool / available_via_special_effect /
pool_access / is_reference_only / pool_identity_varies / lobby_races_required`；
顶层新增 `pool_scope = "solo_snapshot"`。

新 catalog 的卡池标记规模：`available_in_solo_pool=true` **678** 张、
`available_via_special_effect=true` **155** 张、`is_reference_only=true` **3305** 张
（双人池 `available_in_duos_pool` 全为 null，说明这是**单人快照**）。

### 2.7 game_tags 与官方 `GAME_TAG` 的差异

rizling 的 `game_tags.json` 来自 python-hearthstone（commit
`b181931242…`）。把它与 rea-analyst 从 `Assembly-CSharp.dll` 提取的官方枚举
（`reversed/net/Assembly-CSharp/enums.json`）对照（函数
`hsbg.bridge.rizling.compare_game_tags_with_official`）：

| 枚举 | 官方 | rizling | 同名 | 同名不同值 | 官方有/rizling 无 | rizling 有/官方无 |
|------|-----:|--------:|-----:|-----------:|------------------:|------------------:|
| `GAME_TAG` | 1214 | 1259 | 1167 | **0** | **47** | 92（多数是旧名/别名） |
| `CardType` | 22 | 22 | 22 | **0** | 0 | 0 |
| `Race` | 46 | 47 | 46 | **0** | 0 | 1（`PET` 别名，与 `BEAST=20` 同值） |
| `Zone` | 10 | 10 | 10 | **0** | 0 | 0 |
| `ChoiceType` | 4 | 4 | 4 | **0** | 0 | 0 |
| `PlayState` | 9 | 9 | 9 | **0** | 0 | 0 |
| `State` / `Step` | 4 / 21 | 4 / 21 | 全部 | **0** | 0 | 0 |

解读：

- **同名同值 0 错**（这与 `reversed/tag_diff.md` 里"引擎 126 个 tag 有 11 处数值错"
  形成对比——rizling 的枚举比本项目引擎的 `hsrl2/tags.py` 更贴近官方）；
- 官方多出的 47 个是 **37.0.0/255130 新增/新命名**的 tag（`ACTIVATABLE_MINION*`、
  `ASSEMBLE*`、`CRAFT*`、`CTHUN_ABILITY*`、`BACON_LINKED_CARD_IN_HAND_ID`、
  `OBJECTIVE_COUNTDOWN` 等），说明 **rizling 枚举停留在 36.6.3 时代**；
- 因为本项目 Power.log 解析器按 **tag 名字符串**存储（不按数值互转），
  rizling 少 47 个 tag 名**不会**直接破坏我们的解析；但如果我们想"用 rizling
  enum 做白名单"就会漏掉 37.0.0 新 tag——所以**不要**这样做。

---

## 3. rizling catalog ↔ 本项目 37.0.0.255130 数据对齐（量化）

命令：

```powershell
python -m hsbg.bridge.rizling summary   # 版本信号
python -m hsbg.bridge.rizling diff      # 写 reversed/rizling_latest/diff_vs_project.json
```

> 口径：catalog 用 `normal` 折叠金色；项目引擎数据用 `_G` 后缀 + catalog 的 `normal`
> 折叠；两边都取"本体"。catalog 是 36.6.3 快照，项目数据是 37.0.0——差异里既有
> **版本差**，也有 catalog 的 `is_reference_only` 构造/引用卡，不能一概算项目错误。

### 3.1 规模

| 指标 | 值 |
|------|----|
| catalog 记录 / 本体 / 皮肤 | 3983 / **2749** / 653 |
| 项目 `data/` 原始 id / 本体 | **3817** / **2649** |
| 交集 | **2526**（catalog 覆盖率 **91.89%**） |
| catalog 有、项目无 | **223**（BGDUO 双人 69+23+4、TB 20、旧构造卡 RLK/EX1/ICC/CORE/GVG/VAN 等） |
| 项目有、catalog 无 | **123**（BG27 异变历史 67、BG31 轮换 17、TB 12、BG34/BG35…） |
| **BG36（36.6.3 新卡池）** | catalog 262 张 → **262 张全部命中，missing=0** |

**结论**：本项目 255130 数据已经完整吸收了 rizling catalog 里的 36.6.3 BG36 卡池；
`only_catalog` 的主体是双人模式/构造引用，不是"漏卡"。

### 3.2 按 kind 的覆盖（catalog 本体 vs 项目命中）

| kind | catalog 本体 | 命中 | 项目缺 |
|------|-------------:|-----:|-------:|
| minion | 1362 | 1227 | 135 |
| spell | 297 | 261 | 36 |
| trinket_greater | 219 | 215 | 4 |
| trinket_lesser | 201 | 194 | 7 |
| tavern_spell | 208 | 205 | 3 |
| hero | 143 | 118 | 25 |
| hero_power | 176 | 165 | 11 |
| quest_reward | 73 | 73 | 0 |
| dark_gift | 47 | 47 | 0 |
| quest | 23 | 21 | 2 |

缺失项绝大多数是 BGDUO/TB/构造引用（单人引擎不迁移）；`hero` 的 25 张主要是双人英雄。

### 3.3 数值/文本/金色/卡池

| 检查 | 结果 |
|------|------|
| 数值（minion atk/hp、hero hp/armor、法术/饰品 cost） | **11 处差异，全部 `is_reference_only=true`**（BOT_218、BOT_445、BOT_537、EX1_577、YOD_026 等构造卡）；**非 BG 池卡 0 差异** |
| 文本（规范化后） | 1405 条相同 / 967 条不同；差异来自"展示替换值 vs CardDefs 模板"（`+1/+1` vs `+{0}/+{1}`、`@` 计数、`[x]` 标记）——**文本不能作一致性判据** |
| 金色变体指向 | catalog 1234 个 golden 链接；63 个在项目 raw id 里找不到，集中在 **BGDUO（38）/TB（20）/BG（5）**，属单人数据不含双人卡 |
| 卡池(solo) | 随从：catalog **256** vs 项目 **273**（交集 251；catalog 多 5 个 `BG36_360t*` token 口径差异，项目多 22 个 37.0.0 池内/回归随从）；酒馆法术：**70 vs 76**（交集 70，项目多 6）；英雄：**116 vs 118**（交集 116，项目多 2） |
| 饰品 | catalog 的"可被饰品选择"子集 236 vs 项目 `bg_trinkets.json` 409（口径不同，不做法判） |
| 同名/等级/种族/关键词（复用 `compare_with_engine_data`） | 名称 0、酒馆等级 **0**（升级到 255130 后已消掉 36.2.2 时代的 9 处差异）、种族 1（EX1_577 双种族）、dbf 6、可映射关键词 9/17213 |

### 3.4 版本信号（本机实测）

```json
{
  "product_db": {"version": "37.0.0.255130", "build": 255130, "revision": 254477},
  "project": {"patch": "37.0.0.255130", "build": 255130},
  "rizling": {"version": "0.6.1", "game_version": "36.6.3.253932"},
  "hsdata": {"tag": "255130", "files": {"CardDefs.xml": ..., "CardDefs.Bacon.xml": ...}},
  "checks": {
    "product_matches_project": true,
    "rizling_matches_project": false,
    "hsdata_matches_project": true
  }
}
```

**一句话**：项目数据 = 游戏补丁 = hsdata = 255130（三对齐），rizling 落后一个规则版本；
rizling 0.6.1 **不能**用来验证 37.0.0 数据，只能作 36.6.3 快照的交叉参考。

---

## 4. 版本检测方法

### 4.1 四个信号

| # | 信号 | 位置 | 读取方式 |
|---|------|------|----------|
| 1 | **游戏补丁 build** | `C:\Program Files (x86)\Hearthstone\.product.db` | 只读字节 + 正则：`hsbg.bridge.rizling.read_product_db()`。本机内嵌 ASCII `37.0.0.255130.254477` → `version=37.0.0.255130, build=255130, revision=254477` |
| 2 | **HearthSim/hsdata tag** | `reversed/hsdata_<build>/source.json`（`python tools/rea_fetch_hsdata.py --tag <build>`） | `tag` + 每文件 sha256；`--check` 只校验不下载 |
| 3 | **rizling 自报版本** | `reversed/rizling_latest/release-manifest.json` 的 `version/game_version` + catalog 的 `game_version` | `python -m hsbg.bridge.rizling summary` |
| 4 | **本项目数据版本** | `data/bg_summary.json` 的 `patch` | `hsbg.bridge.catalog.read_engine_patch()` |

交叉判定（`hsbg.bridge.rizling.detect_version_signals()`）：

```text
product_matches_project = product_db.build == project.patch.build
hsdata_matches_project  = hsdata.tag        == project.patch.build
rizling_matches_project = rizling.game_version == project.patch
```

### 4.2 `.product.db` 的格式说明

`.product.db`（767 B）是 protobuf 风格二进制，含产品名（`hs_beta`）、安装路径、
locale、**版本串**、hash、包设置等。我们不做完整 protobuf 解析，只做只读字节扫描：

```python
from hsbg.bridge.rizling import read_product_db
read_product_db()   # -> {'version': '37.0.0.255130', 'build': 255130,
                    #     'revision': 254477, 'raw': '37.0.0.255130.254477'}
```

> 注意：`Hearthstone.exe` 的 FileVersion（6000.3.11…）是 **Unity 引擎版本**，不是
> 炉石补丁号；不要拿它判断游戏版本。`OFFICIAL_EXACTNESS.md` 附录 A 也记录了这一点。

### 4.3 rizling 信号怎么用

1. **只在它自报的 `game_version` 上做比较**：它的 catalog 是"那个版本的快照"；
   拿 36.6.3 的 catalog 去判 37.0.0 数据"缺卡"会得到错误结论（本项目实测：BG36
   全命中，缺的只有双人/构造引用）。
2. **版本号变化（`version` 或 `game_version`）时**才需要重新跑 `summary/diff`；
   它只是"运营方认为线上规则是什么版本"的旁证。
3. **不要依赖它的闭源服务/逻辑**：本项目的数值/规则权威永远是官方 CardDefs +
   轨迹差分（`docs/OFFICIAL_EXACTNESS.md` / `docs/DIFF_HARNESS.md`）。

---

## 5. 标准同步流程（游戏补丁 → 本项目数据）

> 255130 的完整执行记录见 `docs/OFFICIAL_EXACTNESS.md` §1.7；本节把它整理成
> **可重复的 playbook**，并复用 `tmp_255130/deliver/tools/upgrade_engine_data.py`
> 的"迁移包 + 备份 + 一键应用 + 回归"模式。
>
> **自动化**：S1–S6 的数据面（取数→合并→生成→差分→备份/替换→回归/压测→回滚）
> 已封装为 `tools/version_sync.py --dry-run` / `--apply --yes`（见 §0）；
> 下列手工步骤仍适用于需要**引擎结构改动**（新种族/card_type/机制脚本）的版本。

### S0 — 检测到新补丁（触发条件）

```powershell
cd C:\HSagent
python -m hsbg.bridge.rizling summary        # 打印 .product.db / hsdata / rizling / 项目 patch
```

判据：`product_matches_project == false`（游戏 build 变了）或人工确认游戏更新。
记录：旧 build、新 build、`.product.db` raw 版本串。

### S1 — 抓取/锁定官方数据（tag = build）

```powershell
python tools\rea_fetch_hsdata.py --tag <build> --deep   # 幂等；先探测文件清单
python tools\rea_fetch_hsdata.py --check                # 只校验本地 sha256
python -m pytest tests\test_official_data.py -q         # 哈希/布局守门测试
```

- 产物：`reversed/hsdata_<build>/{CardDefs.xml, CardDefs.Bacon.xml, RaceTagMap.xml,
  README.md, source.json, *.sha256}`；
- **255130 起拆分布局**：BG 数据在 **`CardDefs.Bacon.xml`**（本项目核心）；
  只读 `CardDefs.xml` 会静默得到 0 张 BG 卡（`OFFICIAL_EXACTNESS.md` §1.2）；
- `KNOWN_HASHES` 会强断言已知 build 的哈希；上游重新打包会报警。

### S2 — 差分评审（先看变化，再改数据）

```powershell
python tools\rea_data_diff.py        # 生成 reversed/data_diff_<new>_vs_<old>.{md,json}
python tools\rea_tag_compare.py      # 官方枚举 vs hsrl2/tags.py（exit 0）
```

- 255130 实测基线：BG 实体 5,612 → 5,787（+175）；新增 179 卡、删除 4 卡、
  **384 处数值变化 / 239 个 id**、16 个新 tag、新增种族 **ABERRATION(126)**；
- 必须逐项过：ATK/HEALTH/COST/TECH_LEVEL/ARMOR/模板参数/SPELL_SCHOOL/新 tag；
- 这一步的结论决定 S3 的"结构补丁"清单。

### S3 — 引擎结构先补（独立、可在旧数据上全绿）

典型改动（255130 实例）：

- `hsrl2/tags.py`：`Race.ABERRATION = 126`、`RACE_TAGS[4756] = "ABERRATION"`；
- `tools/generate_bg_data.py`：`RACE_TAGS`/`DBF_RACE_NAMES` 增补新种族；
- 新 CardType/新 tag 的白名单（仅当生成器需要）。

验收：**旧 `data/` + 新枚举** 下 `pytest hsrl2/tests -q` 全绿。这一步不动数据文件，
失败可以二分定位。

### S4 — 生成器试跑（不覆盖 `data/`）

```powershell
python tools\rea_generate_probe.py
```

- 自动合并 `CardDefs.xml + CardDefs.Bacon.xml` → 
  `reversed/data_255130_input/CardDefs.merged.xml`（单 `<CardDefs>` 根，现有生成器
  只接受单文件）；
- 猴补丁输入/输出路径，生成到 `reversed/data_255130/`（**不碰 `data/`**）；
- 用 `hsrl2.db.CardDB.load()` 实际加载新数据，报告条目数/INVALID card_type/池规模；
- 255130 实测：生成器返回 0，3817 卡、池内随从 273、法术 76、INVALID 14（与旧数据相同）。

### S5 — 按迁移包模式应用（复用 `upgrade_engine_data.py`）

> 模式（255130 已用）：`tmp_<build>/deliver/{data,hsdata,patches,tools}` +
> `MANIFEST.json`；`upgrade_engine_data.py` 负责备份/复制/回归。

```powershell
python tmp_255130\deliver\tools\upgrade_engine_data.py --dry-run    # 预演
python tmp_255130\deliver\tools\upgrade_engine_data.py --smoke      # 备份+应用+pytest+压测
```

脚本行为（幂等、可回滚）：

1. 备份 `data/` 的 12 个生成 JSON → `data/backup_<old_build>/`；
   备份 `hsdata/{CardDefs.xml,RaceTagMap.xml,README.md}` → `hsdata/backup_<old_build>/`；
2. 复制迁移包 `deliver/data/*` → `data/`、`deliver/hsdata/*` → `hsdata/`；
3. 复制 `deliver/patches/**` 的代码补丁（引擎 tags/defs/卡脚本/测试/生成器）；
4. 默认跑 `python -m pytest hsrl2/tests tests -q`（可选 `--smoke`）。

回滚：把 `backup_<old_build>/` 复制回 + `git checkout -- hsrl2 tests tools`。
**`data/` 是生成产物，禁止手改**；所有改动以迁移包/生成器为准。

### S6 — 回归 + 差分 harness

```powershell
python -m pytest hsrl2/tests -q
python -m pytest tests -q
python tools\smoke_random_games.py --games 8 --seed 2000
python tools\diff_extract_replays.py              # 真实 BG 轨迹（679 条，BobsBuddy 日志）
python tools\diff_replay_combat.py                # 引擎复现 + 差分
```

255130 当前基线（`docs/DIFF_HARNESS.md`）：

- 679 场真实 BG 战斗，**DATA_GAP = 0**（所有卡名都在引擎 `data/` 里解析成功）；
- 总体 MATCH 382/679 = 59.9%，确定性战斗 75.5%，干净子集 82.9%；
- **当前瓶颈不是数据，而是 37.x 新卡效果脚本缺失**：246/256 条分歧轨迹涉及
  "有卡面文本但 `REGISTRY` 无脚本"的卡。
- 因此本流程的验收标准是：**数据升级后 DATA_GAP 保持 0**；机制一致率由脚本
  实现推进（`DIFF_HARNESS.md` 的 TOP 卡清单）。

### S7 — 锁定与文档

- 更新 `hsdata/README.md` / `VERSION_NOTE.md` 的版本号；
- 把 `reversed/hsdata_<build>/source.json` 的哈希写进发布记录/`OFFICIAL_EXACTNESS.md`；
- 更新 `AGENTS.md` 的数据基线（S14/36.2.2 → 37.0.0/255130 …）；
- 跑一遍 rizling 对齐（§4）：

```powershell
python -m hsbg.bridge.rizling diff
python -m pytest tests -q -k "official or bridge"
```

---

## 6. 触发频率建议

| 触发事件 | 检测方式 | 动作 | 频率 |
|----------|----------|------|------|
| **游戏客户端补丁** | `python tools\version_sync.py --check`（`.product.db` build 变化） | 状态 `waiting-for-hsdata` 时等待；`update-available` 时 `--dry-run` → `--apply --yes` | 每次补丁 |
| HearthSim/hsdata 新 tag | `--check` 的 hsdata 最新 tag（或 `rea_fetch_hsdata.py --check`） | 抓取 + 哈希锁定 + 差分评审（`--dry-run` 已含） | 补丁后 / tag 发布时 |
| **rizling 发行包更新** | `--check` 的 rizling 信号（或 `python -m hsbg.bridge.rizling summary`） | 相对项目数据"落后/一致/超前"记录；**不驱动数据升级** | 每次 rizling 更新（可选） |
| **本项目 `data/` 变更后** | `bg_summary.patch` 变化 / 迁移包应用后 | 跑 `pytest tests -q -k "official or bridge"` + `rizling diff` + 差分 harness 冒烟 | 每次数据变更 |
| 轻量漂移检查 | 同上的 summary（只读、秒级） | 记录 product/build/rizling/项目 patch 四元组；异常才升级 | 每周或每次大版本前 |
| 官方枚举变化 | `rea_tag_compare.py`（任一 build） | 更新 `hsrl2/tags.py` 缺失/同名错值（按 tag 名映射，不按数值） | 随数据升级 |

原则：**数据升级只由官方 CardDefs（build tag）驱动；rizling 只是旁证**。rizling 的
版本滞后不应触发"降级"或"回退"。

---

## 7. rizling 与本项目的关系（明确边界）

| 允许 | 禁止 |
|------|------|
| 用它的 `release-manifest`/catalog 做**版本信号与公共元数据交叉校验**（只在它自报的 `game_version` 上） | 依赖它的闭源服务/协议/模型输出；把它当权威数据源 |
| 用它的 `game_tags.json` 与官方枚举对照，辅助发现"官方新增 tag" | 把它的枚举当白名单（会漏 37.0.0 的 47 个官方 tag） |
| 借鉴它的 `hud`/`trajectory` 的**字段设计**（rank/placement/upgrades/triples/visible_ranks） | 复制它的卡图/webp、闭源代码、或再分发发行包 |
| 记录它的包版本/哈希作为"参考基线" | 运行它的 exe、上传容器数据、把包提交进仓库（54MB） |

它与本项目的关系链：

```text
官方游戏 build ──(.product.db)──┐
                                 ├──> 官方 CardDefs (hsdata tag) ──> data/*.json ──> 引擎/RL
rizling manifest/catalog ────────┘            （权威）                 （生成产物）
        └── 仅"线上规则版本"旁证：落后/一致/超前，不驱动升级
```

---

## 8. 自动化命令与代码索引

| 文件/命令 | 作用 |
|-----------|------|
| `hsbg/bridge/rizling.py` | `read_product_db()` / `package_summary()` / `detect_version_signals()` / `compare_packages()` / `compare_catalogs()` / `compare_game_tags()` / `compare_game_tags_with_official()` / `compare_catalog_with_project()` / `pool_alignment()` |
| `python -m hsbg.bridge.rizling summary` | 打印版本信号（product.db / hsdata / rizling / 项目 patch） |
| `python -m hsbg.bridge.rizling diff` | 写 `reversed/rizling_latest/diff_061_vs_053.json` 与 `diff_vs_project.json` |
| `tests/test_bridge_rizling.py` | 合成包/版本解析/枚举/对齐测试（真实包缺失自动 skip） |
| `tools/rea_fetch_hsdata.py` | 按 build tag 抓取官方 CardDefs（幂等、sha256 锁定、自适应拆分布局） |
| `tools/rea_data_diff.py` / `rea_tag_compare.py` | 官方数据/枚举差分 |
| `tools/rea_generate_probe.py` | 合并 CardDefs 并**不覆盖地**试跑 `generate_bg_data.py` |
| **`tools/version_sync.py`** | **一键版本同步流水线**：四信号检测（`--check`）、取数/合并/生成/差分预演（`--dry-run`）、备份+应用+回归+自动回滚（`--apply --yes`）；产物 `runs/version_sync/`、`tmp_version_sync/` |
| **`tests/test_version_sync.py`** | 流水线单元测试（`.product.db` 解析、信号决策、网络注入/mock、ZIP Range、回滚辅助；**不联网**）|
| `tmp_255130/deliver/tools/upgrade_engine_data.py` | 迁移包一键应用（备份/复制/回归）——下一 build 的模板 |
| `reversed/rizling_latest/` | 0.6.1 关键文件 + `PACKAGE_INFO.json` + `STATIC_ANALYSIS.json` + 两个 diff JSON + `README.md` |

验收命令：

```powershell
python -m pytest tests\test_bridge_powerlog.py tests\test_bridge_catalog.py tests\test_bridge_rizling.py -q
python -m hsbg.bridge.rizling summary
python -m hsbg.bridge.rizling diff
python -m pytest tests\test_official_data.py tests\test_official_tags.py -q
```

本次实测：bridge 三组测试 **45 passed**（powerlog 18 + catalog 10 + rizling 17）。

---

## 9. 风险与合规边界

1. **不运行下载的 exe**：0.6.1 只做 PyInstaller 静态解析与 JSON 分析；未联网登录、
   未触发远程服务、未读取游戏进程内存。
2. **不修改游戏目录**：`.product.db`/Logs/log.config 均只读；本流程不写游戏目录。
3. **包完整性**：只做了"zip 内容 vs manifest 内容哈希"的校验；**Ed25519 发布签名
   未独立验证**（由 updater 在运行时做）。后续若要以可执行方式使用该包，必须另走
   官方更新流程验签。
4. **不提交整包/不二次分发**：54MB zip 已删除，仅保留关键文件与哈希；卡图/webp
   是 Blizzard 游戏素材（HearthstoneJSON 托管），不进入本项目仓库/发行物。
5. **隐私**：分析不涉及账号/昵称；rizling catalog 是公共卡牌元数据；若未来要采集
   对局，仍按 `docs/REAL_GAME_BRIDGE.md` §3.5 的匿名化/本地化约定。
6. **依赖边界**：本项目数据/训练/评估不依赖 rizling 服务；它的版本信号仅作旁证，
   失效/下线不影响本项目。
7. **ToS/封号**：参考项目的"只读日志 + 只读内存"是灰区；本项目只采用其中的
   **只读日志**路线，不做内存读取/自动点击（见 `REAL_GAME_BRIDGE.md` §6）。

---

## 10. 附：本次 0.6.1 分析产物与关键数字速查

| 事实 | 数值 |
|------|------|
| rizling 版本 / built | 0.6.1 / 20261018-160659 |
| rizling 自报 game_version | **36.6.3.253932** |
| 包大小 / sha256 | 53,852,237 B / `B3C3FFEF…BC1F` |
| 文件数 | 2031 |
| PYZ 模块 / 客户端模块 | 343 / 36（0.5.3：251 / 27） |
| 新增客户端模块 | 9（artwork/demo/desk/hotkeys/hud/overlay_calibration/overlay_host/tracker/widgets） |
| 字节级不变的核心模块 | powerlog/mapping/mechanics/tags/mono/memory/choices/leaderboard/state/protocol/network/telemetry 等 |
| catalog | 3983 卡 / 2749 本体 / 653 皮肤 / 新增 20 字段 / 共享字段 0 变化 |
| game_tags 与 0.5.3 | **完全相同**（sha256 一致） |
| game_tags vs 官方 GAME_TAG | 同名同值 **0 错**；官方多 47 个（37.0.0 新 tag）；rizling 多 92 个旧名/别名 |
| 本地模拟器/模型/自动点击 | **仍然没有** |
| 项目数据 patch | **37.0.0.255130**（raw 3817 / 本体 2649） |
| catalog ↔ 项目 | 交集 2526 / only_catalog 223 / only_engine 123；BG36 262/262 命中；数值差异 11 全为 reference-only；卡池 256→273、70→76、116→118 |
| 版本一致性 | product.db = project = hsdata = 255130；**rizling = 36.6.3（落后）** |
