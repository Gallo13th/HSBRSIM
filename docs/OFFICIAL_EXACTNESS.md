# OFFICIAL_EXACTNESS — 与官方实现完全一致：可执行技术路线

> 目标（用户最高优先级）：一个**可高并发搜集数据、与官方实现效果完全一致**的
> 酒馆战棋模拟环境。
>
> 本文把「官方一致性」拆成可验证的三层：**数据一致**（数值/卡池/枚举 = 官方
> build 255130）、**行为一致**（用官方可观测轨迹做差分回归）、**可直接运行官方
> 实现**（结论：不可行，见 §3）。每条结论都给出命令/文件/数据出处。
>
> 本文件由 `rea-analyst` 产出；产物全部在 `reversed/`，未修改 `data/`、`hsrl2/`、
> `hsbg/` 或游戏目录。

---

## 0. TL;DR（结论表）

| # | 问题 | 结论 | 关键证据 |
|---|------|------|----------|
| 1 | 能否拿到本机安装版本（37.0.0.**255130**.254477）的官方卡牌数据？ | **能，且已拿到并哈希固定**。255130 起官方数据拆成 `CardDefs.xml`（构筑）+ `CardDefs.Bacon.xml`（酒馆战棋，**本项目核心**）+ `CardDefs.Lettuce.xml`（佣兵）；旧的单文件布局已不存在 | `reversed/hsdata_255130/`（sha256 见 §1.2）；`python tools/rea_fetch_hsdata.py --tag 255130` |
| 2 | 官方数据与本地 36.2.2/249896 基线差多少？ | BG 实体 **5,612 → 5,787（+175）**；新增 **179** 张 BG 卡、删除 **4** 张；**384 处数值变化**（239 个 id：ATK 40 / HEALTH 60 / COST 98 / TECH_LEVEL 19 / ARMOR 27 / 模板参数 138 / SPELL_SCHOOL 2）；**新增 37 张池内随从**；**新增第 11 种族 ABERRATION(126)**（25 张池内随从） | `reversed/data_diff_255130_vs_249896.md` / `.json`；`python tools/rea_data_diff.py` |
| 3 | 现有生成器能否吃下 255130？ | **能，但必须先合并拆分布局**。`tools/generate_bg_data.py` 只读单个 `CardDefs.xml`；把 `CardDefs.Bacon.xml` 合并进一个 `<CardDefs>` 后**无需改生成器**即可产出 12 个 JSON，且 `hsrl2.db.CardDB.load()` 能加载（3817 张卡） | `reversed/data_255130_generator_report.md`；`python tools/rea_generate_probe.py` |
| 4 | 客户端里有没有可离线调用的**官方战斗模拟**？ | **没有**。14,390 个类型 / 113,222 个方法里，`Simulate*` 只有 6 个且全部与战斗无关；战斗由服务器下发 `PowerTaskList`，客户端只做播放/UI 预测 | `reversed/net/SUMMARY.md` §2.1；`reversed/net/Assembly-CSharp/methods.tsv` |
| 5 | 能否直接运行官方程序集做战斗模拟？ | **不可行**。Unity 运行时依赖 + 战网登录 + 服务器权威 Power 流 + ToS/授权风险；客户端根本不含裁决逻辑（§3） | `reversed/net/decompiled/{GameState,PowerTaskList,TB_BaconShop}.cs` |
| 6 | 能否与官方机制「完全一致」？ | **只能以「数据哈希一致 + 行为差分一致」逼近**。官方可观测轨迹（Power.log）是唯一权威裁判；本机 `log.config` 已开启 `[Power]`，但**尚无 BG 轨迹**（1,365 个 HDT 录像全是 2 人构筑局，不含 8 人 BG 局）→ 需先采集 ≥1 局 BG 才能启动差分 harness | §2；`reversed/powerlog_corpus.md` |
| 7 | 本机有没有 REA？ | **没有**。PATH/常见安装目录/游戏目录均无 `rea` 可执行或配置；`ilspycmd` + Mono.Cecil + hsdata 已覆盖「静态可提取」的全部关键部分（§4） | §4 的检索命令 |
| 8 | 高并发数据搜集怎么走？ | 官方轨迹侧：**只读 Power.log / HDT 录像**，禁止多开/输入注入（封号 + ToS 风险）；模拟侧：单进程 0.3–3 games/s，多进程按核数线性放大（§5） | §5；`python tools/smoke_random_games.py --games 8 --seed 2000` |

**一句话**：官方实现拿不到（服务端权威），但**官方数据（build 255130）现在就能拿到且已被哈希锁定**，官方行为只能通过 Power.log 轨迹做差分验证。战略应是：
**数据先升级到 255130 → 用轨迹差分把机制误差一条条压到 0 → 引擎多进程扩吞吐。**

---

## 1. 数据一致：build 255130 官方 CardDefs 为唯一数值来源

### 1.1 官方数据在客户端里的真实加载路径（逆向证据）

本机安装：`C:\Program Files (x86)\Hearthstone`（**只读**）。提取自
`Assembly-CSharp.dll`（23,114,752 B）的类型清单与反编译片段：

| 环节 | 官方符号（Namespace/Type.Method） | 文件/证据 |
|------|-----------------------------------|-----------|
| DBF 资源包 | `GameDbf.LoadDBFSharedAssetBundle` / `GameDbf.GetDOPAsset()` → `Assets/Game/DBF-Asset/DOPAsset.asset` | `reversed/net/SUMMARY.md` §2.2；`reversed/net/Assembly-CSharp/strings.tsv` |
| DBF 表加载 | `Dbf<CardDbfRecord>.CreateLoadAsyncJob("CARD", ...)`、`Dbf<CardTagDbfRecord>...("CARD_TAG", ...)`（共 **233** 张表） | `reversed/net/decompiled/GameDbf.cs`（`GetLoadDbfJobs`, line 1428+） |
| 卡牌记录 | `CardDbfRecord`（`NoteMiniGuid`/`Name`/`CardTextBuilderType` 等）与 `CardTagDbfRecord`（`TagId`/`TagValue`/`IsReferenceTag`） | `reversed/net/decompiled/CardDbfRecord.cs`、`CardTagDbfRecord.cs` |
| 实体构造 | `EntityDef.LoadBatchCardEntityDefs(List<string>)` → `EntityDef.LoadTagFromDBF(cardId, tags)` → `LoadTagFromDBF_SetTags()`（错误文案仍叫 `EntityDef.LoadDataFromCardXml()`） | `reversed/net/decompiled/EntityDef.cs` line 278/327 |
| 资源包路径（直接证据） | `DbfShared.GetSharedDBFAssetBundlePath()` → `Assets/Game/DBF-Asset/dbf.unity3d`；`Dbf<T>.GetAssetPath()` → `Assets/Game/DBF-Asset/{0}.asset` | `reversed/net/SUMMARY.md` §2.2（`strings.tsv`） |
| XML 退化路径 | `GameDbf.ShouldForceXmlLoading()`：`HearthstoneApplication.IsPublic()` 直接 `false`；仅编辑器/Standalone local data / `Option.DBF_XML_LOADING` 才读 XML | `reversed/net/decompiled/GameDbf.cs` line 1456 |

**结论**：正式客户端**不是**读 `CardDefs.xml`，而是读 `Data/Win/dbf.unity3d`
（本机 45,499,729 B）里的 Unity ScriptableObject；`CardDefs.xml` 是社区工具
（HearthSim `hsdata`）从 DBF 转出的等价转储。所以：

- `reversed/hsdata_255130/CardDefs*.xml` 是我们能拿到的**最接近官方**的数值源；
- 游戏目录里没有 CardDefs.xml 是正常现象（Lead 的观察得到解释）；
- HDT 自带的 `HearthDb.dll` 内嵌 `HearthDb.CardDefs.base.xml`，但本机版本是
  **build 244584**（`%USERPROFILE%\AppData\Roaming\HearthstoneDeckTracker\CardDefs\CardDefs.base.xml`，
  34,265,417 B），**过旧，不能当 255130 数据源**。

### 1.2 已获取的官方数据（sha256 固定，可复现）

命令：`python tools/rea_fetch_hsdata.py --tag 255130`（幂等；`--check` 只做本地校验）

| 文件 | 大小（B） | sha256 | 用途 |
|------|-----------|--------|------|
| `CardDefs.xml` | 70,509,381 | `c7863b8fc7dd109d3e67230bf2efda319b175f8bd9ddfa955b5f4cb5cb267f0f` | 构筑模式 23,452 实体（255130 起**不含** BG/佣兵） |
| `CardDefs.Bacon.xml` | 15,826,018 | `c60d62b350f2d0361cd88b12e4941bfe6a9f24125c1af003858adb7728b3f413` | **酒馆战棋 5,787 实体（本项目核心数据）** |
| `RaceTagMap.xml` | 1,443 | `3e3df0413390d8e47ce783812e8f56e3cd0f23c14bf9f67237659a55ebb5f0e9` | race 名 ↔ 布尔 tag 映射（含新种族 ABERRATION=tag 4756） |
| `README.md` | 291 | `36c8c8ed94d6a909cf5634d79e9883cd05c82c9f501cbb5673fd23aaf4e695e7` | `Version: 37.0.0.255130` |

记录文件：`reversed/hsdata_255130/source.json`（每个文件的 URL/size/sha256/抓取时间）、
`<file>.sha256` sidecar（幂等的依据）。校验测试：`tests/test_official_data.py`。

> **重要布局变化**（本轮最大坑）：`https://api.github.com/repos/HearthSim/hsdata/git/trees/255130`
> 显示 255130 只有 `CardDefs.Bacon.xml` / `CardDefs.Lettuce.xml` 拆分文件；249896 的
> tree 只有一个 `CardDefs.xml`。**任何还按「单个 CardDefs.xml 含 BG」写的工具在
> 255130 上都会静默得到 0 张 BG 卡**（本轮实测：只喂 CardDefs.xml →
> `Total BG entities: 0`）。`tools/rea_fetch_hsdata.py` 已自适应探测文件清单。

### 1.3 与本地 249896 基线的差分（可复现）

命令：`python tools/rea_data_diff.py`（旧 = `hsdata/CardDefs.xml`；
新 = `reversed/hsdata_255130/CardDefs.xml + CardDefs.Bacon.xml`，按 CardID 合并）

| 指标 | 249896（本地基线） | 255130（本机安装） | Δ |
|------|------------------|-------------------|---|
| 全量实体 | 35,713 | 29,239（23,452 + 5,787） | -6,474（重复：佣兵移出） |
| BG 集（CARD_SET=1453）实体 | 5,612 | 5,787 | **+175** |
| `IS_BACON_POOL_MINION` 实体 | 275 | 303 | +28 |
| BG 卡 id 新增 / 删除 | — | **+179 / -4** | 新增前缀 `BG` 169、`BGDUO` 6、`TB_Bacon` 4 |
| 同一 dbf 的 CardID 重编号 | — | 0 | 无 |
| 同一 CardID 卡名变化 | — | 0 | 无 |
| 数值变化（公共 id） | — | **384 处 / 239 个 id** | ATK 40、HEALTH 60、COST 98、TECH_LEVEL 19、ARMOR 27、NUM_1 70、NUM_2 49、NUM_3 14、NUM_4 4、NUM_5 1、SPELL_SCHOOL 2 |
| 新增 tag enumID（BG 卡使用） | — | 16 个 | 见 §1.5 |

- 删除的 4 张：`BG28_521t2`、`BG36_815e`、`BG36_MidGameEffect_000`、`BG36_MidGameEffect_000t6e2`
  （其中 2 张被 `hsrl2/tests` 引用：`test_batch_trinkets12.py`、`test_s14_mechanics.py`；
  另外 2 张被 `hsrl2/scripts/batches/batch_rally2.py`、`batch_trinkets30.py` 引用）。
- 完整新增卡列表、逐卡数值变化、按 tag 分类的变化明细见
  `reversed/data_diff_255130_vs_249896.md`（426 行）/ `.json`。

### 1.4 升级到 255130 会影响哪些测试（量化）

`reversed/engine_impact_255130.json`（由 `reversed/scratch/impact.py` 生成，
扫描 `hsrl2/**/*.py` 与 `tests/**/*.py`）：

| 变更类型 | id 数 | 命中引擎脚本/测试文件 | 命中 `hsrl2/tests` 文件 |
|----------|-------|----------------------|------------------------|
| 数值变化 | 239（194 本体 + 45 金色） | 146 个文件（`game.py` 16 个 id、`tags.py` 3、`registry.py` 2、`minions.py` 2…） | **71 个测试文件** |
| 新增卡 | 179（其中 37 张池内随从） | **0**（新机制尚未实现，符合预期） | 0 |
| 删除卡 | 4 | 4 个文件（2 测试 + 2 脚本） | 2 |

解读：
- **数值变化是主要回归面**（71 个测试文件直接引用这些 id，多为按卡 id 断言数值/机制）；
- **37 张新池内随从没有任何实现**——数据升级后它们会以「无脚本卡」形式进池，
  必须由引擎侧排期实现，不能假装一致；
- 4 张被删卡在脚本/测试里的引用需要清理或改为 37.0 的替代卡。

### 1.5 37.0 的新机制信号（数据层）

新增 tag enumID（BG 卡使用；名称取自官方 `GAME_TAG` 枚举）：

| enumID | 官方名 | 出现卡数 | 含义/风险 |
|--------|--------|----------|-----------|
| 4955 | （客户端未命名，内部） | 63 | 新机制计数器，未知 |
| 4757 | `BACON_SUBSET_ABERRATION` | 47 | **新种族 ABERRATION 的饰品关联标记** |
| 4953 | （未命名，内部） | 18 | 未知（疑为 discard/Deity 计数） |
| 1508 | `CAN_TARGET_CARDS_IN_HAND` | 11 | 手牌可被指向 |
| 3880 | `HAS_DARK_GIFT` | 10 | 黑暗赠礼新判定 |
| 4921/4922/4929/4933/4934/4935/4940/4946 | 部分命名：`BACON_DEITY_SIGIL`、`BACON_MYSTERY_ATTACK/HEALTH/TIER_IN_CARD_EXPORT` 等 | 1–8 | **S15「Deity」机制 + 卡导出隐藏信息** |
| 4744 | `BACON_OLD_GOD` | 4 | 新阵营/机制 |
| 230 | `CANT_DISCARD` | 1 | 弃牌 |
| 4916 | `USE_EVOLUITON_BIG_CARD_AS_PRIMARY` | 1 | 进化/大卡 |

**新种族 ABERRATION（`TAG_RACE`=126）** 是最硬的变化：
`RaceTagMap.xml` 255130 新增 `<Race race="ABERRATION" tag="4756"/>`；37.0 卡池内
**25 张**随从 `card_race=126`（`BG36_097`…`BG36_320`、`BGFYM_005`）。引擎
`hsrl2/tags.py` 的 `Race` 没有 126，`generate_bg_data.py` 会把它们记成
`card_race=126`，`CardDef.from_json` 映射为 `Race.NONE` → 种族相关效果全部错。
**数据升级必须与 `Race.ABERRATION=126` + `RACE_TAGS` 增补同批进行。**

### 1.6 现有生成器消费 255130 的实测

命令：`python tools/rea_generate_probe.py`
（importlib 加载 `tools/generate_bg_data.py`，猴补丁输入/输出路径，**不覆盖 `data/`**）

- 输入：合并后的 `reversed/data_255130_input/CardDefs.merged.xml`（87,887,292 B）；
- 结果：**返回码 0，生成器无需修改**；输出到 `reversed/data_255130/`；
- 引擎 `hsrl2.db.CardDB.load()` 加载生成数据：**成功**，3817 张卡、池内随从 273、
  池内法术 76、无法映射 card_type **14 个（与当前 `data/` 完全相同**——都是
  `TB_BaconShop*` 按钮/拖拽 token 等历史内部实体，不是回归）。

| 生成文件 | 255130 | 当前 `data/` | Δ |
|----------|--------|--------------|---|
| `bg_cards.json` | 3534 | 3405 | +129 |
| `bg_pool_minions.json` | **273** | 247 | **+26** |
| `bg_pool_spells.json` | 76 | 75 | +1 |
| `bg_heroes.json` | 118 | 116 | +2 |
| `bg_hero_powers.json` | 165 | 162 | +3 |
| `bg_trinkets.json` | 409 | 379 | +30 |
| `bg_anomalies.json` | 108 | 108 | 0 |
| `bg_quest_rewards.json` | 73 | 73 | 0 |
| `bg_tavern_spells.json` | 205 | 203 | +2 |
| `bg_dark_gifts.json` | 47 | 43 | +4 |

> 池内随从 273 vs 数据差分里的 303：后者是 `IS_BACON_POOL_MINION` 原始实体数
> （含金色/附魔），生成器会排除 enchantment/双打专属，口径不同已在报告中注明。
> 池内 `NONE` 种族从 24 张涨到 49 张——其中 25 张就是 ABERRATION 未映射，是
> 升级风险的最直观指标（`reversed/data_255130_generator_report.md` §2）。

### 1.7 数据升级执行步骤（建议，由 Lead 决策/执行）

> 写权限约束：`rea-analyst` 只产出脚本与报告；`data/` 的替换由 Lead 协调。
> 全程可回滚：先备份 `data/`。

| 步 | 动作 | 命令 | 验收 |
|----|------|------|------|
| S0 | 抓取并锁定官方数据 | `python tools/rea_fetch_hsdata.py --tag 255130 --deep` | 4 文件 sha256 与侧车一致；`pytest tests/test_official_data.py -q` 绿 |
| S1 | 差分评审 | `python tools/rea_data_diff.py` | 179/4/384 与本节一致；逐条过 ATK/HEALTH/COST/TECH_LEVEL/模板参数变化 |
| S2 | 生成器试跑 | `python tools/rea_generate_probe.py` | 生成成功；`CardDB.load` 通过；14 个 INVALID 不增加 |
| S3 | 引擎侧先补**结构**（独立 PR，Lead 批准） | 在 `hsrl2/tags.py` 增 `Race.ABERRATION=126`、`RACE_TAGS[4756]="ABERRATION"`；`generate_bg_data.py` 的 `RACE_TAGS` 增 4756；`DBF_RACE_NAMES` 增 126 | `pytest hsrl2/tests -q` 全绿（此步只加枚举，不改数据） |
| S4 | 备份 + 替换数据 | `copy data data\backup_36.2.2_249896`（Lead 执行）→ 将 `reversed/data_255130/*.json` 覆盖到 `data/` | `python -m pytest hsrl2/tests -q`，记录失败清单（预期集中在 §1.4 的 71 个测试文件 + 2 个删卡引用） |
| S5 | 回归分诊 | 逐失败判定：a) 官方数值变了 → 改**测试期望值**并注明 CardDefs 255130 证据；b) 机制变了 → 排期改脚本；c) 删卡引用 → 清理 | 4164 项回到 0 failed；或明确记录未实现清单（新 37 张随从机制） |
| S6 | 锁定与文档 | 更新 `hsdata/README.md` 版本（Lead）；把 `reversed/hsdata_255130/source.json` 哈希写进发布记录 | `python -m pytest tests -q` 全绿；`docs/OFFICIAL_EXACTNESS.md` 更新数据版本号 |

**风险表**

| 风险 | 影响 | 缓解 |
|------|------|------|
| 255130 拆分布局 | 任何只读单文件的工具静默得到 0 BG 卡 | 统一走 `rea_fetch_hsdata`/合并脚本；生成器侧后续加 `--bacon-xml`（最小改动：`parse_carddefs` 接受多路径） |
| 新种族 ABERRATION | 25 张池内随从种族身份错误，种族光环/发现/池权重全错 | S3 先加枚举与 tag 映射；`tests/test_official_data.py::test_255130_introduces_aberration_race` 守门 |
| 384 处数值/模板参数变化 | 71 个测试文件、146 个引擎文件受影响；脚本里硬编码数值过期 | 按 `reversed/engine_impact_255130.json` 分诊；模板参数变化（138 处）优先核对卡面文本 |
| 37 张新随从无实现 | 卡池「看起来对、打起来错」 | 数据升级与脚本实现分开验收；池子可先用「机制未实现」白名单过滤 |
| 删除 4 张卡 | 脚本/测试引用失效 | 清理或替换；在本报告记录 |
| 佣兵数据未抓 | 无影响（本项目不玩佣兵） | `CardDefs.Lettuce.xml` 默认不下载（`--with-lettuce` 可选） |

**如何保持 4164 测试绿**：不要为了让测试过而改断言；所有期望值改动必须能指向
255130 的 CardDefs 条目（卡 id + tag 名 + value）。S3 与 S4 拆成两步，先让
「结构/枚举」在旧数据上全绿，再做数据替换，失败即可二分定位。

---

## 2. 机制一致：用「官方可观测轨迹」做差分测试

### 2.1 为什么只能走轨迹差分

`Assembly-CSharp.dll` 里**没有**战斗裁决器（§0 #4，§3 展开）：客户端收到服务器
下发的 `PowerTaskList`（`GameState.DebugPrintPower()` 那一套），按序播放动画；
`ZoneMgr.PredictZone*` 只是 UI 区域预测。因此「官方实现」在客户端侧不存在，
唯一权威是**官方算出来的结果**——而它被完整记录在 Power.log 里。

### 2.2 本机已有的轨迹资产（格式已验证，BG 语料待采集）

| 资产 | 位置 | 规模/事实 |
|------|------|-----------|
| Power.log 开关 | `%LOCALAPPDATA%\Blizzard\Hearthstone\log.config` | `[Power] LogLevel=1 / FilePrinting=True / Verbose=True` **已开启**；但 `C:\Program Files (x86)\Hearthstone\Logs` 目前不存在（开启后还没打过一局） |
| HDT 录像 | `%APPDATA%\HearthstoneDeckTracker\Replays\*.hdtreplay` | **1,365** 个；zip 内含 `output_log.txt`（Power.log 的 GameState 行）。**玩家数分布 `{2: 1365}` → 全部是 2 人构筑/双人模式，没有 8 人 BG 局**；含 `tag=BACON_*` 的 103 个、含 `CardID=BG<数字>` 的 2 个都是构筑局里引用的 BG 实体，**不能当 BG 语料** |
| 现有解析器 | `hsbg/bridge/powerlog.py` + `tools/powerlog_probe.py` | 已能增量解析 `CREATE_GAME/FULL_ENTITY/TAG_CHANGE/BLOCK_START/option/choice` 等 15 类事件（bridge-analyst 已交付） |
| HDT BG 对局记录 | `%APPDATA%\HearthstoneDeckTracker\BgsLastGames.xml` | **60 场 BG 对局**：`Hero/Placement/Rating` + `FinalBoard` 随从 `CardId`/tag 快照（570,816 B，**无战斗事件**）。可用于真实终局战团分布采样/评测，**不能**当差分轨迹 |

> 采集 BG 语料的最低成本：`log.config` 已就绪 → 正常打一局 BG → `Logs\Power.log`
> 出现 → `hsbg.bridge.powerlog` tail 解析。**一局 BG 日志即可点亮整条 harness**
> （本机录像已证明 Power.log 的格式与 `GameState.*` 行结构稳定）。
>
> 隐私/合规：录像文件名含 BattleTag，`output_log.txt` 含 `PlayerName/GameAccountId`。
> **任何落盘/提交的轨迹必须先剥离**（`player_1..8` 匿名化；`GameAccountId` 直接丢弃）。
> `reversed/` 只保存统计摘要（`reversed/powerlog_corpus.md`），不保存原始日志。

### 2.3 记录什么：战斗轨迹 schema（`official_combat_trace.v1`）

一场 BG 对局 = 多个 combat。每场战斗记录「战斗前战团快照 + 事件序列 + 结果」：

```jsonl
{"type":"episode","schema":"official_combat_trace.v1","episode_id":"sha256:...","patch":"37.0.0.255130","source":"powerlog","parser":"hsbg.bridge.powerlog/0.1","started_utc":"...","players":8,"my_hero":"BG20_HERO_100"}
{"type":"combat_start","combat_id":3,"turn":8,"seed":null,"self":{"warband_id":"self","minions":[{"eid":64,"card_id":"BG20_100","slot":1,"atk":4,"health":5,"damage":0,"golden":false,"taunt":true,"divine_shield":false,"poisonous":false,"venomous":false,"reborn":false,"windfury":false,"cleave":false,"tags":{"PREMIUM":1,"CARDRACE":20}}]},"opponent":{"warband_id":"opp","minions":[...]},"anomaly":null}
{"type":"event","combat_id":3,"seq":0,"kind":"attack","actor":64,"target":129,"actor_card":"BG20_100","target_card":"BG23_000","damage":4,"tags_before":{"ATK":4},"tags_after":{}}
{"type":"event","combat_id":3,"seq":1,"kind":"damage","target":129,"amount":4,"health_after":1,"source":64}
{"type":"event","combat_id":3,"seq":2,"kind":"death","eid":129,"card_id":"BG23_000","slot":2}
{"type":"event","combat_id":3,"seq":3,"kind":"summon","eid":201,"card_id":"BG23_000t","slot":2,"by":64}
{"type":"event","combat_id":3,"seq":4,"kind":"trigger","source":77,"card_id":"BG20_200","trigger":"DEATHRATTLE","target":64}
{"type":"combat_end","combat_id":3,"result":"win","damage_dealt":4,"damage_taken":0,"survivors_self":[64,77],"first_divergence":null}
```

**必须记录的字段（来自 Power.log 的 tag 快照 + BLOCK 流）**

| 类别 | 字段 | Power.log 来源 |
|------|------|----------------|
| 战斗边界 | `combat_id/turn/phase` | 首选 `BACON_IN_COMBAT_PHASE`；历史文档记录的 `BLOCK_START BlockType=TRIGGER Entity=[TB_BaconShop_8P_PlayerE] EffectIndex=14`（REAL_GAME_BRIDGE §3.4）在本机 1,365 个录像里**从未出现**，需在首份真实 BG 日志上重新验证。**兜底**：`TURN` 推进 + 连续的 `BlockType=ATTACK/DEATHS/POWER` 簇 + `PREDAMAGE` 出现作为战斗段；战斗结束 = 攻击簇后随从 `ZONE=PLAY` 清空/英雄 `DAMAGE` 变化 |
| 战团快照 | 每个随从 `eid/card_id/zone_pos/ATK/HEALTH/DAMAGE/PREMIUM/taunt/divine/poison/venomous/reborn/windfury/cleave/IMMUNE` | 战斗开始瞬间 `ZONE=PLAY` 实体的 tag 集合 |
| 攻击 | `actor/target/seq` | `BLOCK_START BlockType=ATTACK Entity=[...] Target=[...]` + 内层 `TAG_CHANGE ATK/HEALTH` |
| 伤害 | `amount/health_after` | `TAG_CHANGE tag=DAMAGE` / `tag=HEALTH` |
| 死亡 | 死亡顺序、`eid/card_id/slot` | `TAG_CHANGE tag=ZONE value=GRAVEYARD`（按序） |
| 召唤 | `card_id/slot/来源` | `FULL_ENTITY - Creating` / `SHOW_ENTITY` |
| 亡语/触发 | 触发者、触发类型 | `BLOCK_START BlockType=TRIGGER` 的 `EffectCardId/EffectIndex` |
| 结果 | win/loss/tie + 英雄伤害 | 战斗结束 block 内英雄 `ATTACK`（本地英雄 Attack→win，Bob 英雄→loss，无→tie；REAL_GAME_BRIDGE §3.4） |

### 2.4 对齐（alignment）

| 维度 | 对齐方法 |
|------|----------|
| 战斗 | `(turn, combat_id)`；Power.log 的 `BACON_IN_COMBAT_PHASE` 上升沿切分 |
| 实体 id | 官方 `EntityID`（≥64）与引擎 `Entity.id` 不同 → 用 **战斗开始快照的槽位** 建 `official_eid ↔ engine_slot` 双射；槽位按 `ZONE_POSITION` 排序 |
| 卡身份 | `card_id`（CardID）+ `golden`（PREMIUM=1 或 `_G` 后缀）+ 战斗前 `atk/health` |
| 事件 | 归一化事件键 `(kind, actor_slot, target_slot, amount)`；不比较时间戳/动画、不比较 `PowerTaskList` 重复行（只取 `GameState.*`，`include_tasklist=False`） |
| 顺序 | 用事件 `seq` 做序列比对；同 tick 的伤害组（`DamageGroupScope`）允许组内顺序不敏感 |
| RNG | 官方随机结果不可观测其种子。**确定性事件（攻击/伤害/死亡）逐条比；随机分支**用两种口径：a) 枚举引擎 seed（N=64）看官方结果是否落在可达结果集；b) 只比「结果分布/集合」不比顺序。差异归入 `RNG_BRANCH` 而非 bug |

### 2.5 定位首个分歧（算法）

```text
diff(official_trace, engine_trace):
  align combat by (turn, combat_id)                 # 缺战斗 → MISSING_COMBAT
  build slot map from combat_start warbands         # 卡 id/金色/攻击力不匹配 → ROSTER_MISMATCH
  o = normalize(official.events); e = normalize(engine.events)
  for i in range(min(len(o), len(e))):
      if not equiv(o[i], e[i]):
          return FirstDivergence(
              seq=i,
              official=o[i], engine=e[i],
              context_o=o[max(0,i-5):i+5], context_e=e[...],
              class=classify(o[i], e[i]),          # 见下表
              suspects=cards_in(o[i], e[i]) ∩ unimplemented_cards,
          )
  if len(o) != len(e): return TAIL_DIVERGENCE(len(o), len(e), ...)
  return None                                        # 完全一致

equiv(a, b) = a.kind==b.kind and a.actor_slot==b.actor_slot
          and a.target_slot==b.target_slot and a.amount==b.amount
          and (a.kind != "death" or a.card_id==b.card_id)
```

分歧分类（直接映射到修复动作）：

| class | 判定 | 修复动作 |
|-------|------|----------|
| `MISSING_SCRIPT` | 分歧事件的卡在引擎 `REGISTRY` 无脚本 / 走简化脚本 | 写/补该卡脚本 |
| `KEYWORD_WRONG` | 分歧集中在 DIVINE_SHIELD/POISON/REBORN/WINDFURY/CLEAVE/TAUNT 处理 | 改 `combat.py`/`minion.py` 关键词规则 |
| `STAT_OR_BUFF_WRONG` | 数值差但事件类型一致 | 查数据数值（CardDefs 255130）或 buff 结算顺序 |
| `ORDERING` | 同一组事件顺序不同（亡语/召唤/Avenge 结算） | 改 `queue.py`/事件结算顺序 |
| `SUMMON_CAP` | 棋盘满/召唤失败判定不同 | 改召唤规则 |
| `RNG_BRANCH` | 仅随机结果不同且官方结果在引擎 N seed 可达集内 | 记录，不修 |
| `ROSTER_MISMATCH` | 战斗开始战团就不同 | 上游（招募期状态/数据）问题，先修数据 |

### 2.6 批量回归（最小 harness 设计）

**目标**：把「机制一致性」变成 CI 可量化的数字——每个卡/关键词一个通过率。

```
corpus/                          # 不在 git（含隐私），本地目录
  <episode_id>/
    official_combat_trace.jsonl  # §2.3 schema（已匿名化）
    meta.json                    # patch/hero/对手/来源

tools/rea_trace_diff.py          # 新增（bridge scope，本报告只给设计）
  --corpus corpus/ --replay-engine
  1) 读 trace → 重建 engine Game（复用 hsbg/bridge/powerlog 的实体/回合事件）
  2) 用 trace 的 combat_start 战团构造引擎 Minion 列表（CardDB 加载 255130 数据）
  3) engine.run_combat(self_warband, opp_warband, seed) 跑 N seeds
  4) 用 §2.5 对齐/定位；写 metrics.json
```

**metrics（每次 CI 输出）**

| 指标 | 定义 | 目标 |
|------|------|------|
| `combat_exact_match` | 事件流完全一致的战斗占比（确定性卡池） | 逐卡修复 → 100% |
| `first_divergence_by_card` | 首个分歧归因到卡的计数排行 | 用于排期修卡 |
| `event_precision/recall` | 事件级 precision/recall（允许尾部缺失时） | > 0.99 |
| `rng_unreachable` | 官方结果不在 N seed 可达集的战斗数 | 0（>0 说明引擎缺分支） |
| `roster_mismatch` | 战斗前战团就不一致 | 0 |

**首批验证用例（按修复难度排序，先跑通再扩）**

1. 无关键词白板互殴（验证轮转/攻击顺序/死亡结算）
2. 嘲讽 + 圣盾（目标选择 + 破盾顺序）
3. 剧毒 / 烈毒（伤害与消耗）
4. 风怒 / 超级风怒（多次攻击）
5. 顺劈（相邻伤害结算）
6. 复生（死亡后 1/1 复活位置与顺序）
7. 亡语召唤（棋盘满/召唤失败）
8. 金色随从数值（`_G`/PREMIUM 折叠）
9. Avenge（阈值与多次触发）
10. 战斗结果 + 英雄伤害（damage cap）

**接入现有 CI**：`pytest tests/test_official_trace.py`（corpus 缺失则 skip）→ 先以
`--subset smoke` 跑前 10 类；数值门槛从「记录」开始，逐卡修复后收紧。**注意**：
harness 依赖 `hsbg/bridge/`（bridge-analyst scope），本报告不越权实现。

### 2.7 采集侧（为 harness 供料）

- **当前状态**：本机 1,365 个 HDT 录像全是 2 人构筑局，**0 个 BG 轨迹**（§2.2）；
- 第一步（阻塞项）：开启 `[Power]` 后**正常打一局 BG** → 产出一份真实 `Power.log`
  → 用 `hsbg.bridge.powerlog` 解析并确认：战斗边界标志、8 人 Player 结构、
  战团快照 tag 是否齐全（若 `TB_BaconShop_8P_PlayerE` 不存在，按 §2.3 兜底规则切分）；
- 第二步：把该日志匿名化为 `official_combat_trace.v1`，跑通 §2.5 的 diff；
- 第三步：正常对局积累 + 手动录制高价值战斗（特定卡组合），roll 成回归 corpus；
- 采集与合规边界见 §5。

---

## 3. 能否直接运行官方实现（离线调用官方客户端程序集）？

**结论：不可行（不是「难」，是客户端里没有这个能力），仅有部分替代。**

| 障碍 | 证据 | 影响 |
|------|------|------|
| 客户端不含战斗裁决代码 | 14,390 类型/113,222 方法中 `Simulate*` 仅 6 个（`Network.SimulateReceivedPacketFromServer`、`Network.SimulateUncleanDisconnectFromGameServer`、`SelectorWheel.SimulateWheel`、`QuestManager.SimulateQuestProgress/NotificationPopup` 等），**无 combat simulator / resolve combat / predict combat** | 即使能加载程序集，也无函数可调 |
| 战斗由服务器权威下发 | `TB_BaconShop.OnCombatPhase()` 协程按 `PowerTaskList` 播放；`GetRemainingCombatEvents` 统计服务器下发的 task list；`PowerProcessor` 顺序执行服务器任务；`GameState` 状态机由 `CREATE_GAME/FULL_ENTITY/TAG_CHANGE` 驱动 | 离线没有服务器就没有战斗 |
| Unity 运行时依赖 | `Assembly-CSharp` 全部逻辑挂在 `MonoBehaviour`/Unity 引擎（`Actor`、`ZoneMgr`、`GameObject`、`AssetBundle`）；`GameDbf.Load()` 依赖 `WaitForDbfBundleReady` + `Data/Win/dbf.unity3d` 资源包 | 不能像普通 .NET DLL 那样 `new Game()`；需要完整 Unity 场景/资源 |
| 网络/登录/校验 | 需要战网登录（`Network/BattleNet`）、服务器连接（`PegasusGame` 协议），客户端会校验服务器下发的 power 流 | 无合法离线会话 |
| 授权/ToS | 修改/自动化客户端违反暴雪 ToS；分发反编译产物有版权风险 | 只做本地静态分析；不运行、不注入、不改游戏目录 |

**可用的「部分」**（按价值排序）：

1. **官方数据**（已达成）：CardDefs 255130，hash 锁定；
2. **官方枚举/协议常量**（已达成）：`GAME_TAG` 1214 项等（§4.2）；
3. **官方轨迹**（可达成）：Power.log → 差分裁判（§2）；
4. **社区参考实现**：本机 HDT 自带 **BobsBuddy 1.34.11**（1,282,560 B，`BobsBuddy.Simulation.*`
   1,817 类型/5,991 方法，完整战斗模拟器）与 **HearthDb**（卡库+枚举）。
   它们不是官方、不能当权威，但可以作为「第二实现」交叉验证引擎：
   若引擎与 BobsBuddy 在确定性战斗上也不一致，至少说明有一方错。
   BobsBuddy 是 HDT 插件，独立调用需要宿主进程 + HearthDb 卡数据 + HDT 注入的
   game state，**不作为本轮路线**（合规与耦合成本高），只在需要时做离线校验参考。

**一句话**：官方一致性只能靠「官方的数据（拿到）+ 官方的结果（轨迹）+ 我们自己的
裁决器（引擎）」三者对齐，而不是「跑官方代码」。

---

## 4. REA 工具：本机现状与替代覆盖

### 4.1 检索结论：本机没有 REA

已执行的检索（均无结果）：

```powershell
where.exe rea                      # 无
Get-ChildItem C:\ -Filter "rea*"   # 无相关目录（用户目录/游戏目录/工作区均无 REA 安装）
```

游戏目录只有 BepInEx（doorstop `enabled=false`）与 HsMod，没有 REA；HDT 目录只有
HearthDb/HearthMirror/HearthWatcher/BobsBuddy 等。**结论：本机不存在可调用的 REA
工具/服务。**

### 4.2 若 REA 是外部工具/服务，接入需要什么信息

| 需要 | 说明 |
|------|------|
| 入口 | 可执行路径或 HTTP endpoint + 认证方式（API key/OAuth） |
| 输入格式 | 期望的是「.NET 程序集路径」？「游戏目录」？「进程 PID」？ |
| 输出格式 | 类型/方法/IL/字符串/资源？JSON schema 是什么？ |
| 能力边界 | 是否包含**服务端**二进制？若只反编译本机客户端，其能力 ≤ ilspycmd/Cecil（本报告已覆盖） |
| 授权 | 使用范围/许可，是否允许把产物用于本项目 |

### 4.3 没有 REA 也已完成的部分（覆盖表）

| 能力 | 工具 | 产物 | 覆盖率 |
|------|------|------|--------|
| 全部类型/方法/枚举/字段名 | Mono.Cecil（`reversed/net_extractor`） | `reversed/net/{Assembly-CSharp,blizzard.bgssdk,blizzard.bgsclient,HearthDb,BobsBuddy,HearthWatcher}/`（types.tsv/methods.tsv/enums.json/strings.tsv/refs.json） | 100% 元数据 |
| 关键类型反编译源码 | `ilspycmd 9.1.0.7988` | `reversed/net/decompiled/*.cs`（EntityDef/GameDbf/CardDbfRecord/CardTagDbfRecord/GameState/PowerTaskList/TB_BaconShop） | 目标类型 100% |
| 全量类型清单（C# 视角） | `ilspycmd -l c/i/s/d/e` | `reversed/net_lists/Assembly-CSharp.*.txt`（12,638 class / 107 interface / 320 struct / 440 delegate / 895 enum） | 100% |
| 内嵌资源 | Cecil `--dump-embedded` | HearthDb 的 `CardDefs.base.xml`（build 244584，过旧，仅证明 HDT 数据链） | 100% 资源 |
| 官方卡牌数据 | hsdata 255130 | `reversed/hsdata_255130/` | BG 卡 100% |
| 枚举差异 | `tools/rea_tag_compare.py` | `reversed/tag_diff.{md,json}` | GameTag 1214 项全量对比 |
| Power.log 解析 | `hsbg/bridge/powerlog.py`（bridge-analyst） | 15 类事件 | 已覆盖 harness 输入侧 |

**无法用 REA/反编译解决的部分**（必须承认的边界）：服务端战斗裁决代码不在本机、
运行期随机数/隐藏信息不可静态获得、卡牌脚本（`PowerTaskList` 效果）依赖服务端
`EntityDef` 组装逻辑——这些只能靠轨迹差分（§2）。

> 附：ilspycmd 安装备注（可复现）：
> `dotnet tool install -g ilspycmd --version 9.1.0.7988`（最新的 11.x 在本机
> .NET 9 上安装失败，9.1.0.7988 可用；Mono.Cecil 直接用 BepInEx 自带的
> `C:\Program Files (x86)\Hearthstone\BepInEx\core\Mono.Cecil.dll`，无需 NuGet）。

---

## 5. 高并发数据搜集与模拟环境吞吐

### 5.1 官方轨迹采集路线（唯一合规的高质量来源）

| 路线 | 做法 | 吞吐 | 风险 |
|------|------|------|------|
| HDT 录像批量解析 | 只读 `%APPDATA%\HearthstoneDeckTracker\Replays\*.hdtreplay`（zip 内 `output_log.txt` = Power.log），N 进程并发解析/匿名化 | 1,365 个文件分钟级，但**本机全是构筑局（0 BG）**，暂无 BG 供料 | 低（本地只读文件；不含账号操作） |
| Power.log tail（实时，**当前唯一 BG 来源**） | `log.config` 已开启；正常对局时 `Logs\Power.log` 增长 → 增量解析 | 每局 1 文件（~200KB-2MB） | 低（只读日志；HDT/日志解析是社区常规行为） |
| AgenticAssistant 类工具 | 已有项目内分析：只读日志+只读内存快照，无输入注入 | — | 中（内存读取违反 ToS 灰区，本项目不采用） |
| 多开/多账号/输入脚本 | —— | —— | **高：封号 + ToS 明确禁止，禁止采用** |

**采集字段**：§2.3 的 trace（战斗边界、战团快照、事件流、结果）。**不采集**：
账号 id/昵称/BattleTag/原始日志全文。

**数据量估算**：一场 BG 对局 ≈ 8 名玩家 × ~10-15 场战斗；本机目前 **0 个 BG 轨迹**
（1,365 个录像全是 2 人构筑局）。要做「逐卡机制验收」至少需要每张卡 ≥ 5 次出现——按
37.0 池内 273 张随从 + 76 法术 + 饰品的量级，需要 **≥ 3,000-5,000 场战斗轨迹**，正常
对局途径不现实；
**结论：轨迹主要用于「抽检 + 回归」，不能替代模拟器自博弈做覆盖率。** 覆盖率靠
引擎多进程自博弈（§5.2），一致性靠轨迹差分（§2）。

### 5.2 模拟环境高并发（引擎侧，本项目可控）

| 维度 | 现状/建议 | 数据 |
|------|-----------|------|
| 单进程吞吐 | `smoke_random_games`：8 局 ≈ 2.37s（含启动），≈ 3.4 局/s；单局 < 500ms 目标成立 | `docs/ROADMAP.md` M0 验收；`python tools/smoke_random_games.py --games 8 --seed 2000` |
| 多进程 | `hsbg/env/vec_env.py` 已按 `multiprocessing` 设计；每核一个 worker，8-16 进程接近线性 | `docs/ENV_SPEC.md` §8 |
| 状态快照 | 不要 pickle 整个 `Game`（大对象）；用 **seed + 动作序列** 作为可重放快照（KB 级），需要时 `reset(seed)` + 重放 | `AGENTS.md` 确定性约定（`game.rng`） |
| 批量评估 | 固定 seed 集（如 0-999）+ 对手池快照；结果写 parquet/jsonl；用进程池跑 config 矩阵 | `hsbg/eval/`（policy-builder scope） |
| 建议规模 | 16 核（本机 RTX 4060 Ti 机器）估算 ≈ 40-50 局/s 空跑；瓶颈是战斗 Python 循环，后续可 numba/Cython 或把 `combat.py` 热路径向量化 | 实测后更新本节 |

### 5.3 合规红线（写进设计）

1. 只读：游戏目录、日志、录像、进程内存（内存读取本项目不采用）；
2. 不注入、不改客户端、不自动输入、不多开/多账号；
3. 轨迹匿名化后只本地使用；不上传原始日志；
4. 反编译产物仅供本项目内部规则核对，不二次分发。

---

## 6. 产物索引与复现命令

| 产物 | 生成命令 | 内容 |
|------|----------|------|
| `reversed/hsdata_255130/` | `python tools/rea_fetch_hsdata.py --tag 255130` | 官方 CardDefs + Bacon + RaceTagMap + source.json（sha256 锁定） |
| `reversed/data_diff_255130_vs_249896.{md,json}` | `python tools/rea_data_diff.py` | 179/4/384 差异全量（含新 tag 名） |
| `reversed/data_255130/` | `python tools/rea_generate_probe.py` | 255130 生成数据（12 个 JSON，不覆盖 `data/`） |
| `reversed/data_255130_generator_report.{md,json}` | 同上 | 生成器消费性 + CardDB 加载验证 |
| `reversed/net/` | `python tools/rea_net_extract.py` | 6 个程序集类型/方法/枚举/字符串/资源 + `SUMMARY.md` + `key_enums.json` |
| `reversed/net/decompiled/*.cs` | `ilspycmd -t <Type> Assembly-CSharp.dll` | 关键类型官方实现源码（只读分析用） |
| `reversed/tag_diff.{md,json}` | `python tools/rea_tag_compare.py` | 官方枚举 vs `hsrl2/tags.py`（11 处同名数值错、1181 缺失、93 多余、36 撞号） |
| `reversed/engine_impact_255130.json` | `python reversed/scratch/impact.py` | 数据升级命中 146 个引擎文件 / 71 个测试文件 |
| `reversed/powerlog_corpus.md` | `python reversed/scratch/replays.py` | 本机 HDT 录像统计（1,365 个，全部 2 人构筑局，0 个 BG） |
| `tests/test_official_data.py` / `tests/test_official_tags.py` | `python -m pytest tests/test_official_*.py -q` | 数据/枚举一致性回归（缺产物则 skip） |

**验收命令**（本文件所有结论的最小复现集）：

```powershell
cd C:\HSagent
python tools\rea_fetch_hsdata.py --tag 255130     # 幂等，第二次走缓存
python tools\rea_data_diff.py                     # 差分报告
python tools\rea_generate_probe.py                # 生成器消费性
python tools\rea_net_extract.py                   # 官方程序集提取（需 dotnet SDK 9）
python tools\rea_tag_compare.py                   # 枚举差分，退出码 0
python -m pytest tests\test_official_*.py -q      # 全绿（缺产物则 skip）
```

**官方一致性验收定义（建议写进里程碑）**

1. 数据：`CardDefs.Bacon.xml` sha256 == 官方 build 对应值（本报告 §1.2），且引擎数据由它生成；
2. 枚举：`reversed/tag_diff.md` 的「同名数值不一致」逐项有处理结论（引擎内部 tag 可豁免，但必须按**名字**映射）；
3. 行为：轨迹差分 corpus 上 `combat_exact_match ≥ 目标`（分关键词/分卡统计）；
4. 吞吐：多进程评估 ≥ 目标局/s（§5.2）。

---

## 附录 A：255130 与 249896 的关键事实速查

- 本机版本：`.product.db`/`Data\Win` → `37.0.0.255130.254477`；`Hearthstone.exe` FileVersion=6000.3.11 是 Unity 版本，不是炉石版本；
- 官方 `GAME_TAG` 1214 项；引擎 `GameTag` 126 项，同名 33，其中 **11 项数值错**：
  `ENTITY_ID`(官方 53/引擎 12)、`STEALTH`(191/19)、`SILENCED`(188/3309)、
  `MEGA_WINDFURY`(1207/826)、`FROZEN`(260/1035)、`EXHAUSTED`(43/1026)、
  `IMMUNE_WHILE_ATTACKING`(373/1044)、`DARK_GIFT`(3627/4855)、
  `BONUS_KEYWORDS`(3423/1097)、`CHOOSE_ONE`(443/1050)、`CHOOSE_BOTH`(419/1058)；
- 引擎 `Zone` 与官方不兼容：官方 `PLAY=1/HAND=3/DECK=2/SETASIDE=6/REMOVEDFROMGAME=5`，
  引擎 `PLAY=1/HAND=2/TAVERN=3/SETASIDE=5/REMOVED=6` → **真实日志桥必须按 tag 名映射**；
- `CardType` 值全对（引擎用 `BACON_*` 命名对应官方 `BATTLEGROUND_*`）；`Race` 值全对；
- 官方 `TAG_STEP` 21 项、`TAG_PLAYSTATE` 9 项、`TAG_SPELL_SCHOOL` 14 项
  （含 `LESSER_TRINKET=11` / `GREATER_TRINKET=12`，引擎数据层用裸 int）；
- 官方客户端字符串 `GameDbf.LoadDBFSharedAssetBundle`、`Assets/Game/DBF-Asset/DOPAsset.asset`、
  `EntityDef.LoadDataFromCardXml()`（遗留文案）是数据加载路径的静态证据；
- 本机 HDT：HearthDb.dll 引用版本 35.6.2.0（内嵌 CardDefs build **244584**，过旧）；
  BobsBuddy 1.34.11（社区离线战斗模拟器，仅参考）；HearthWatcher 2.x（Power.log 解析）。

## 附录 B：外部/社区资料来源

- HearthSim/hsdata（官方 build tag 数据）：<https://github.com/HearthSim/hsdata/tree/255130>
  （本轮下载源：`https://raw.githubusercontent.com/HearthSim/hsdata/255130/CardDefs.xml` 等）
- HearthDb（社区卡库/枚举）：<https://github.com/HearthSim/HearthDb>
- BobsBuddy（社区 BG 战斗模拟器）：<https://github.com/jleclanche/BobsBuddy>
- HearthWatcher（Power.log 解析）：<https://github.com/HearthSim/HearthWatcher>

---

## 7. 2026-10-18 追加：官方完整实现可否从游戏本体迁移？——结论：不能

> 详细取证：`reversed/rea/official_implementation_audit.md` + `.json`（15/15 证据自动定位），
> 复现：`python reversed/rea/scripts/audit_official_impl.py`。

**用户决策指令**：若能从游戏本体直接获取官方完整实现，则直接迁移官方实现。

**结论（高置信度）**：官方战斗裁决/回合流程**不在本机游戏本体**，客户端只是服务器
`PowerHistory` 的「状态应用器 + 播放器 + UI」：

1. `Gameplay.cs:243-245` 注册 `OnPowerHistory`；`Network.cs:10578-10668`
   把服务器 protobuf `PowerHistory` 转成 `HistFullEntity/TagChange/BlockStart/...`；
   `PowerProcessor.cs:329,696` → `BuildTaskList`；`PowerTaskList.cs:496-504` 纯包装；
   `GameState.cs:4631-4653` / `GameUtils.cs:1722-1744` 用服务器值 `SetTag`。
2. 断线重连（`ReconnectMgr.cs:338/453/693/704`）与回放/观战同样消费服务器 history，
   **无本地重算**。
3. `BaconCombat` / `BattlegroundsCombat` / `DamageCap` 符号均为表现层
   （`BaconCombatStep` 播放步骤、`IsInBattlegroundsCombatPhase` 阶段标志、
   `DamageCapPanel` 显示 tag 2089）。
4. 全量扫描 126 个托管 DLL + 原生 DLL + 13GB 资源：
   `CombatSimulator/SimulateCombat/ResolveCombat/CalculateCombat/PredictCombat/
   CombatResolver/BattleSimulator/CombatEngine/CombatLogic` **0 命中**；
   `Simulate*` 仅 5 个且与战斗无关。

**能拿到 vs 拿不到**：
- 能：官方 CardDefs/DBF、GAME_TAG 等 893 枚举、官方规则文本（伤害公式/上限解除/
  亡语先于复生/毒烈毒定义）、Power 协议 schema、伤害上限 tag 2089/3403 与显示逻辑。
- 拿不到：服务端裁决器（攻击轮转/目标随机/死亡/亡语/复生/Avenge 顺序）、随机数、
  服务端卡牌脚本、逐回合 cap 值、匹配/淘汰/隐藏信息。

**因此**：`客户端 C#→Python 迁移`无意义（引擎里没有裁决）。最高一致性路线 =
**官方 Power.log 事件级轨迹（服务器 history = 官方裁决可观测真值）+ 官方数据/文本 +
差分校准 + BobsBuddy 第二实现参照**；唯一 blocker 是真实 Power.log 采集。
可选：BobsBuddy .NET 桥接（本机 dotnet 9 可调用；第三方、非官方、需确认许可证），
只作为交叉参照，不作为官方替代。
