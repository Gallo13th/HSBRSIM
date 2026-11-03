# 人类对战界面（Human Arena）

`scripts/human_arena.py`：零 Web 依赖的本地 UI（标准库 `http.server` + 内嵌 HTML/JS）。
人类占一个座位，其余 7 个座位由引擎原生 `Game.bot_play` 驱动，跑到对局结束；
每个人类决策按训练同口径（`features` 3227 + `cards` 124 + `mask` 245 + `action`）
落盘到 `runs/human_play/*.jsonl.gz`，可直接转成 BC 数据。**CPU 即可，不训练、不占 GPU。**

![界面](human_arena_ui.png)

![发现/目标弹窗](human_arena_pending.png)

## 撤回（Undo）

每次人类动作前保存引擎 `Game.state_json()` 快照（默认栈深 50，至少 10 步），`POST /undo` 用 `Game.from_json` 精确恢复 RNG、bot 与 pending 状态。页面按钮支持 `Ctrl/Cmd+Z`，`/state` 暴露 `undo.enabled/reason/depth/limit`；对局结束、回合/战斗结算、Discover 已选或无快照时禁用并显示原因。

replay 会把被撤回的 decision 行标记 `undone: true`，并追加 undo 事件；`convert_replays` 过滤这些行，避免进入 BC。可通过 `/snapshot.txt` 对比撤回前后的状态。

战场右侧为独立出售区，拖拽槽位 `i` 映射 `Sell(16+i)`。卡面效果默认完整展示；buff/附件默认为 `+N 附件 ▸` 折叠摘要；英雄技能描述默认折叠，点击标题展开。


```bash
# 远端仓库根目录（默认只绑 127.0.0.1:8000）
python scripts/human_arena.py --port 8000 --seed 1234

# 本机浏览器：把远端 8000 端口转发到本地
ssh -L 8000:127.0.0.1:8000 bicourse-glt
# 打开 http://127.0.0.1:8000
```

参数：`--seat 0`（人类座位）、`--out runs/human_play`（replay 目录）、
`--host`（默认 127.0.0.1，**改成 0.0.0.0 等于对网络开放，风险自担**）、
`--aberration`（强制大厅含畸变怪，必有神明）、`--config-json '{...}'`（透传引擎 `RulesConfig`）。
`GET /health` 是存活探针。

## 界面能做什么

按 `docs/HUMAN_ARENA_UI_SPEC_V2.md` 做了官方酒馆战棋布局 V2（只改 UI 与 `/state` 白名单，**不改引擎、不占 GPU**）。

### 官方布局 V2（三行 + 侧栏）

- **第一行·鲍勃酒馆**：8 个固定槽位（空槽也保留 drop 区域）+ 金币/上限、等级、刷新/冻结/升本费用；
  按钮条含 `EndTurn/Refresh/Freeze/Upgrade/HeroPower/DarkGift`，按钮文案带价格与动作下标；
- **第二行·我方战场**：7 个固定槽位（横向可滚动），卡片可左右拖动排序；右侧/下方有出售区与发动区；
- **第三行·手牌**：10 个固定格，拖到战场空槽 = Play，拖到已有随从 = Magnetize；
- **侧栏/底栏**：对手公开信息、饰品/持续效果、黑暗之赐、神明、日志/战果、合法掩码、`/snapshot.txt`；
  移动端按「HUD→酒馆→战场→手牌→出售区→侧栏」纵向滚动（桌面 `@media` 保持三行 + 双栏）。
- 固定槽位由 `S.action_space.N_SHOP/N_BOARD` 派生，空槽保留宽高，不因商店/手牌数量变化抖动。

### 拖拽（HTML5 DnD + Pointer Events + 键盘）

| 源 | 目标 | 动作 |
|---|---|---|
| 商店槽 i | 战场/购买区 | `Buy 8+i`：**只购买**，卡进入手牌并提示“已购买”，需再拖手牌；不会自动打出（“买完自动打出”需要新端点，本版不做） |
| 手牌 h | 战场空槽 p | `Play 46+h*8+p` |
| 手牌 h（磁力） | 战场随从 b | `Magnetize 126+h*7+b` |
| 战场 from | 战场 to | `Move 196+from*7+to`（from≠to） |
| 战场 b | 出售区 | `Sell 16+b` |
| 战场 b | 发动区 | `Activate 23+b` |

拖拽先按当前 `state.mask`/子字段做本地预校验：合法才调用 `/act`，非法**不提交**、源卡抖动、
toast 显示原因（如“金币不足/手牌已满/该位置不能移动/当前不能出售”）；pending 期间暂停普通拖拽。
桌面用 `dragstart/dragover/drop`，触屏用 `pointerdown` 长按约 150ms 生成拖影、`pointermove` +
`elementFromPoint` 找目标、`pointerup` 复用同一 `dispatchDrop`；`dragend`/取消清理高亮。
卡片也可用 Enter/Space 打开动作菜单（与拖拽等价），`aria-grabbed` 标记拖拽状态。

### 折叠（默认收起）

`attached` 折叠为一行 `+N 附件 ▸`（展开才显示每项名称/类型/效果/来源）；卡面效果、金卡效果、
`breakdown`（`属性来源 ▸`）、Discover/抉择说明（`发现：三选一 ▸` / `抉择：选项1/2 ▸`）、
神明触发（`神明触发：N 条 ▸`）、对手所见战团、战斗帧、日志（最新一条 + `更多日志 ▸`）默认折叠。
点击 `summary` 只切换自身内容，`stopPropagation` 保证不触发购买/打出；重渲染时用
`data-key` 保留已展开项。

操作入口：点商店卡 = `Buy(slot)`（`8+slot`）；手牌「打出/磁力→随从j」chip = `Play{hand,pos}`
（`46+hand*8+pos`）/ `Magnetize`；战场 chip = 出售 `[16+slot]` / 发动 `[23+slot]` / 移到位置 j
`Move{from,to}`；技能 `[4+slot]`、黑暗之赐 `[6]`、刷新 `[1]`、冻结 `[2]`、升级 `[3]`、结束回合 `[0]`；
选择弹窗全部映射到 `Choose(i)`（`30+i`），可取消时给 `Cancel [7]`。

### 卡牌信息（商店 / 手牌 / 战场 / 选择弹窗共用）

- 中文名、种族（双种族全列，无种族写“无”）、`★N` tier 徽标、金卡“金色”文字 + 金边；
- 当前 `atk/hp` 与 `max_hp`（受伤/临时上限），动态关键词（嘲讽/圣盾/风怒/复生/烈毒/…）
  与**卡面**关键词（战吼/亡语/抉择/复仇/回合结束/战斗开始时/…，静态表只补卡面，
  不会把已经失去的动态圣盾“补回来”）；
- 卡面效果全文（标 `[卡面]`；引擎 `live_text` 时数字是当前值），实际价格：
  商店 `price/costs_health`、手牌 `play_cost`（当前引擎恒 0，不伪造）、饰品/选项 `cost/base_cost`；
- 磁力/宝石/赐福等附件（`attached`：名称+类型+效果）与数值拆解 `breakdown`
  （基础 / 已记录来源 / 本局 / 临时 / 其他 / 已受伤）；
- 卡图 `https://art.hearthstonejson.com/v1/orig/{card_id}.png`；加载失败 `onerror` 回退为
  文字占位，不阻塞任何操作、不把图当权威信息；
- 不可购买 / 不可打出 / 不可出售会写原因（金币不足、手牌已满、阶段不符、没有磁力目标）。

### 饰品 / 黑暗之赐

- 已获得小/大饰品常驻（名称 + 类型 + 效果）；第 6/9 回合 pending 四选一带完整效果与价格
  （`weight` 只是出价权重，不是胜率；回合数 ≠ 酒馆星级）；
- 黑暗之赐：费用、已用/上限、本回合是否已用、本回合/下回合可选星级、使用按钮与不可用原因
  （未解锁 / 本回合已用 / 已达上限 / 金币不足 / 阶段不符）。

### 对手 / 战果 / 操作

- 对手栏：英雄、生命与护甲分列、等级、存活/淘汰名次、下位对手与幽灵标记、公开饰品；
  上轮阵容标“第 X 回合交战时所见”，从未交战写“未知”，**不**转发 debug view 的实时棋盘；
- 自己的上轮战果：从完整 `combats` 过滤 `a==seat || b==seat` 后取最近一场，显示胜/负/平 + 伤害
  （可展开战斗帧 `frames`；引擎未记录时明确写“无战斗帧”；对局后期引擎滚掉旧记录时用本局缓存并标注）；
- 按钮文案 = 动作名 + 实际价格 + `[引擎动作下标]`；禁用按钮直接显示原因；
  请求处理中锁定提交（防双击重复购买）；非法动作的 HTTP 400 回包带 `action` 与可读原因，
  前端提示后刷新状态。

### 神明（Deity）

神明（`me.deity`）只在含畸变怪（ABERRATION）的大厅出现，和“赐福/持续效果”是两套机制，
单独一块面板显示（没有神明时写“本局无神明”），字段：

- **名字**、当前 **atk/hp**、`★tier`、种族、卡 id、卡图；金卡/复生分别打“金色/复生”标识；
- **效果全文**：优先 view 的卡面文本（金卡用 `_G` 卡面），标来源 `[卡面]`；
- **触发要求（结构化）**：每条 `阶段（招募/战斗/回合结束）｜条件｜效果｜来源`。
  唤醒条件卡面**没有写**，由引擎脚本推导并标 `[脚本]`：
  `engine.rs::check_deity`（本场战斗中你的畸变怪累计死亡 ≥ `RulesConfig.deity_threshold`，默认 4）
  → `content/mod.rs::deity_awakened`（克苏恩：把自身属性均分给其他随从；金卡 ×2）/
  `content/minions.rs::yshaarj`（亚煞极亡语：复活本场死亡的前 2 个畸变怪，金卡 4 个）。
  卡表未收录的神明 id 只展示卡面并标 `[推断]`，不编造条件；
- **数值**：面板 atk/hp、卡面初始属性（含金卡值）、唤醒门槛、金卡倍率/复活数量、
  卡表中可提升神明的卡数（静态卡表按“神明/Deity”文本检索，含金卡/衍生）。

数据来源：卡 id 来自 `Game.view` 的 `me.deity.card`；名字/文本/种族/星级/类型用
`rust/crates/hsbg-engine/data/cards.json` 补全；唤醒/亡语触发条件从畸变怪机制
（`content/aberrations.rs` 同源）与引擎脚本（`engine.rs::check_deity`、`content/mod.rs::deity_awakened`、
`content/minions.rs::yshaarj`）推导，逐条标 `卡面/脚本/推断`。
`/state` 的 `hud.deity`、`/snapshot`、`/snapshot.txt` 三处同源。

### 快照

`GET /snapshot` 返回注入状态 JSON + `<pre id="statetext">` 纯文本的静态 HTML；
`GET /snapshot.txt` 直接返回同一段中局状态文本（回合/种族/星级/商店/手牌/战场/饰品/黑暗之赐/
神明/对手/上轮战果/按钮原因），便于截图与复盘，例如：

```text
=== 第 6 回合 · 招募 · 种子 1234 · 座位 0 ===
英雄：时光扭曲者克罗米  生命 30  护甲 6  金币 6/8  等级 T2  存活 8/8
本局种族：野兽/机械/野猪人/亡灵/畸变怪
  1 号位 獠牙露营者  ★1  野猪人  2/3  卡面关键词：集结
饰品（已获得 1）：
  [小饰品] 腐蚀的节杖
黑暗之赐：3 金 · 已用 0/3 · 本回合未用 · 可选星级 3/4（下回合 4）· 可用 [6]
神明（deity，不等于赐福）：亚煞极 1/1 · ★1 · 畸变怪（BGFYM_011）
  [卡面] 神明。亡语：召唤你在本场战斗中死亡的前2个畸变怪，且其具有其最大属性值（神明除外）。
  触发要求（阶段｜条件｜效果｜来源）：
    1) 阶段=战斗｜条件=本场战斗中你的畸变怪累计死亡 ≥ 4 只｜效果=唤醒亚煞极：把它召唤到己方战场最右侧（属性 = 面板 atk/hp；金卡使用金色卡）｜来源=脚本
    2) 阶段=战斗｜条件=神明死亡（亡语结算）｜效果=召唤你在本场战斗中死亡的前 2 个畸变怪（金卡 4 个），并使其具有其最大属性值（神明除外）｜来源=卡面
    3) 阶段=招募｜条件=打出/触发卡面提到「神明」的卡（34 张，含金卡/衍生）｜效果=你的神明获得对应属性值（面板 atk/hp 随之变化，本面板实时同步）｜来源=卡面
  数值：面板属性=1/1[引擎 view] · 初始属性（卡面）=1/1（金卡 2/2）[卡面] · 唤醒门槛（本场畸变怪死亡）=4[引擎 config.deity_threshold] · 亡语复活数量=2 只（金卡 4 只）[卡面+脚本] · 可提升神明的卡=34 张[卡面（卡表检索）]
  提示：唤醒门槛：本场战斗畸变怪死亡 ≥ 4 只
```

无神明时同一位置输出 `神明（deity，不等于赐福）：本局无神明`（并说明大厅没有畸变怪）。

`GET /replay` 下载本局 replay；「新开一局」按钮调 `POST /new {seed}`。

## 动作空间

前 245 项与 AutoTavern 逐位一致（`hsbg/env/action_space_std.py`，单一真源）：
`EndTurn 0 / Refresh 1 / Freeze 2 / Upgrade 3 / HeroPower 4-5 / DarkGift 6 / Cancel 7 /
Buy 8-15 / Sell 16-22 / Activate 23-29 / Choose 30-45 / Play 46-125 /
Magnetize 126-195 / Move 196-244`。扩展段 245+ 不参与掩码与本 UI。
非法动作（越界或 `mask[action]=0`）返回 HTTP 400 且不改变对局。

## replay 格式（`runs/human_play/human_<时间>_seed<seed>_<序号>.jsonl.gz`）

gzip JSONL，多 gzip member 拼接（`gzip.open` 正常读），每行一个对象：

- 首行 `{"type":"meta", game_version, seed, seat, n_actions:245, obs_floats:3227, obs_cards:124}`；
- 每个决策一行 `{"type":"decision", features:[3227], cards:[124], mask:[245],
  action, turn, tier, gold, phase, decision, action_name, seed, seat}`，`mask[action]=1` 恒成立；
- 结束行 `{"type":"summary", placement, placements, decisions, steps, turns}`（人类被淘汰后，
  bot 继续打完到 `Game.is_over()`，因此 summary 的 turns 可能大于人类最后一个决策回合）。

## 转成 BC 数据

```bash
python scripts/human_arena.py --to-npz runs/human_play --npz-out data/human_bc/human_play.npz
# 可选 --skip-hero-select：过滤英雄选择阶段
```

输出 npz 的字段与 `scripts/train_compound_bc.py::load_npz` 对齐：`obs (n,3351)` float32
（前 3227 观测 + 后 124 卡牌 id）、`cards int16`、`mask (n,245) bool`、`action int64`、
`turn/tier/gold/episode_id`；另存 `features float16` 便于复用现有工具。
训练时按 `--data <npz>` 直接读，`episode_id` 用于按局切 holdout。

## 自测 / 测试

```bash
# 脚本化人类跑完整一局 + 校验 replay + 转 npz（默认写 runs/human_play/）
python scripts/human_arena.py --selftest --seed 1234
# 强制畸变怪大厅，验证神明面板（任意 seed 必有神明；seed 1 = 亚煞极，seed 3 = 克苏恩）
python scripts/human_arena.py --selftest --aberration --seed 1
# 8 项：动作映射/状态序列化/replay/完整局/BC 转换/HTTP
python -m pytest tests/test_human_arena.py -q
# 8 项：卡片字段/卡图回退/价格与原因/饰品/黑暗之赐/对手与战果/snapshot 文本/400 原因
python -m pytest tests/test_human_arena_ui.py -q
# 神明面板：有/无神明、结构化触发要求、snapshot 与 HTML 一致、金卡与复生标识
python -m pytest tests/test_human_arena_deity.py -q
# 7 项：三行顺序/拖拽映射 id/商店拖 Buy/非法回滚/折叠默认收起/DnD+Pointer/snapshot 字段
python -m pytest tests/test_human_arena_v2.py -q
```

`--selftest` 会额外打印“中局状态文本”（与 `/snapshot.txt` 同款，含种族/关键词/饰品/神明）。

限制：单用户、单进程；bot 在人类请求内推进（无动画）；UI 只展示公开对手信息；
卡图是在线增强，离线/加载失败时自动回退文字占位。
