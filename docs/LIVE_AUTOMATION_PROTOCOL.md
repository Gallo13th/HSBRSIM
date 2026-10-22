# 实时对局自动化协议（Live Automation Protocol）

> 目标：把「真实客户端操作 → 截图/状态采集 → 问题定位 → 热修 → 反馈模拟器」
> 变成可持续、可并行、可复盘的协作流程，而不是一次性脚本。

## 1. 范围与目标

覆盖：

1. 启动/重连/多局循环；
2. 招募期操作（买、卖、打、刷、冻结、升本、英雄技能、选择/发现、目标）；
3. 战斗/结算/回大厅/下一局；
4. 操作验证、失效判定、截图与诊断；
5. 截图/日志反哺 `hsrl2` 引擎和 `hsbg` 环境缺失项。

非目标：绕过客户端安全、注入/改内存、自动登录/账号操作。

## 2. 组件

| 组件 | 路径 | 职责 |
|---|---|---|
| 主循环 | `hsbg/live/click_bot.py` | 状态机、动作选择、点击/拖拽、验证、多局循环 |
| 启动器 | `hsbg/live/launcher.py` | 战网 UI 启动、窗口查找、进入游戏 |
| 状态读取 | `tools/live_state_mem.py` | 只读内存，输出 `hsbg.live_state.v1` JSON |
| 动作驱动 | `hsbg/env/driver.py` | 模拟器动作原语（buy/sell/play/reroll/freeze/upgrade/hero_power/choose/end_turn） |
| 动作契约 | `hsbg/env/spec.py` | `ActionKind`、`CandidateAction`、观测版本 |
| 截图诊断 | `ClickBot.screenshot` / `_diagnostic_burst` | 每动作、失败、结算、密集 burst |

`click_bot.py` 内置 37.0 new UI 校准常量（2026-10-22 实测，见 §7.1）：启动链
（主菜单→酒馆战棋→开始）、英雄选择（点解锁英雄卡→确认）、对局内按钮
（刷新/升级/冻结/英雄技能/黑暗之赐）、卡牌行布局（shop/board/hand）
以及选择弹层布局（discover 三选一 / 饰品商店四选一）。常量更新必须附带
`runs/live/recon/*.png` 或新 run 的截图证据。

### 2.1 隔离原则

- 内存读取必须放在**独立子进程**：`bgcontroller` 偶发 access violation 时不能带崩主循环；
- 主循环对子进程失败返回 `{}`，记录 `state_reader_failed`，按 `game_unavailable` 处理；
- 不直接调用托管方法、不注入、不写内存。

## 3. Run 目录协议

每次运行必须使用独立目录：

```text
runs/live/<run_id>/
├── actions.jsonl           # 结构化动作/状态/决策/失败日志
├── summary.json            # 退出摘要（成功时）
├── settled/                # 每回合结算状态
│   └── turn_XX.json
├── screenshots/
│   ├── actions/            # 每次 click/drag 后截图
│   ├── <HHMMSS>_fail_*.png
│   ├── <HHMMSS>_turnXX_settled.png
│   └── <HHMMSS>_game_over.png
└── diagnostics/
    └── <HHMMSS>_turnXX_noeffectN/
        ├── meta.json        # 5 帧路径 + 5 份 state
        └── ...（帧在 screenshots/diag_*）
```

命名约束：

- `run_id`：`live_<UTC+8 时间>_<seed/agent>`；
- 截图文件名必须以 `HHMMSS` 开头；
- 任何需要人工复核的失败必须落 `diagnostics/` 或 `settled/`，不能只写 stdout。

## 4. 状态快照协议

状态读取统一使用 `hsbg.live_state.v1`。机器人只依赖以下稳定字段：

| 字段 | 类型 | 语义 |
|---|---|---|
| `schema` | string | 当前 `hsbg.live_state.v1` |
| `phase` | enum | `no_active_game/lobby/menu/hero_select/recruit/game_over` |
| `turn` | int | 回合；非对局为 0 |
| `gold` | int/null | 当前铸币 |
| `tier` | int | 酒馆等级 |
| `health` / `armor` | int | 英雄血量/护甲 |
| `board` | list | 己方随从：`card,eid,atk,hp,keywords` |
| `hand` | list | 手牌：`card,eid,kind,cost,locked` |
| `shop` | list | 酒馆：`card,eid,kind,cost,affordable` |
| `choices` | list | 待选卡（英雄/饰品/发现），可能滞后 |
| `legal` | object | `buy/play/sell/refresh/upgrade/powers/choose/end` |
| `pending` | string/null | 待处理选择类型 |
| `waiting` | string | 过渡态 |

### 4.1 脏帧规则

以下状态不参与动作选择与坐标计算：

- `len(shop) > 7`；
- `len(board) > 7`；
- `len(hand) > 10`；
- `shop == [] and board == []`（战斗/回合过渡）；
- `board` 连续下降且 `shop == []`（战斗帧）→ 记录 `combat_wait`。

原因：内存映射在战斗/切回合时可能返回错位/滞后帧，按 `len` 算坐标会整体偏移。

## 5. 动作记录协议

`actions.jsonl` 每行一个 JSON 对象，至少包含：

```json
{
  "ts": "2026-10-22T21:58:24.406+08:00",
  "actions": 676,
  "kind": "drag",
  "a": [0.4245, 0.34],
  "b": [0.49, 0.9],
  "note": "buy:BG31_815"
}
```

通用字段：

| 字段 | 说明 |
|---|---|
| `ts` | ISO 时间 |
| `actions` | 本局动作序号 |
| `kind` | `state/decision/click/drag/no_effect/turn_settled/...` |
| `note` | 动作语义，必须可机器解析 |

### 5.1 动作 kind 枚举

- `state`：状态采样；
- `decision`：候选动作评分（`buy/play/sell/upgrade/refresh` 分值）；
- `click` / `drag`：实际输入；
- `no_effect`：验证失败；
- `repeat_failure_diag`：连续失败触发密集截图；
- `turn_settled`：本回合结算；
- `combat_wait`：战斗/过渡等待；
- `game_over`：对局结束；
- `foreground_failed` / `state_reader_failed`：环境异常；
- `game_unavailable`：窗口/进程不可用。

### 5.2 note 命名协议（与 `hsbg.env.spec.ActionKind` 对齐）

新动作的 note **前缀 = `ActionKind.value`**，冒号后为可机器解析的参数：

| note | ActionKind | 说明 |
|---|---|---|
| `buy:<card>` | `buy` | 酒馆→手牌（拖拽） |
| `sell:<card>` | `sell` | 随从拖到 Bob 卖出 |
| `play_minion:<card>` | `play_minion` | 手牌随从→棋盘 |
| `play_spell:<card>` | `play_spell` | 无目标法术 |
| `play_spell:<card>-><zone>[<index>]` | `play_spell` | 目标法术（拖/点到目标） |
| `reroll` | `reroll` | 刷新酒馆（顶部右侧「刷新」） |
| `upgrade` | `upgrade` | 升级酒馆（顶部左侧费用徽标） |
| `freeze` | `freeze` | 冻结/解冻（顶部最右雪花按钮） |
| `hero_power:<card>` | `hero_power` | 点底部英雄技能圆钮 |
| `hero_power_target:<zone>[<index>]` | `hero_power` | 技能目标（辅助 note） |
| `activate:<card>` | `activate` | 点随从发动 Activate |
| `activate_target:<zone>[<index>]` | `activate` | 发动目标（辅助 note） |
| `use_dark_gift` | `use_dark_gift` | 右侧「黑暗发现」按钮（3 费三选一） |
| `end_turn` | `end_turn` | 尝试结束回合（单人 BG 无按钮，见 §7） |
| `choose[<i>]:<card>` | `choose` | 选择弹层第 i 项 |
| `choice_confirm` | —（辅助） | 饰品商店「确认」 |

辅助/流程 note（不属于 ActionKind，只用于复盘）：`select:<card>`、
`target:<zone>[<index>]`、`overlay_click`、`choose_one`、`hero_option`、
`hero_confirm`、`menu_battlegrounds`、`start`、`start_combat`、
`result_continue`、`cancel_targeting`、`dismiss_popup`。

历史别名（旧 run 日志仍会出现）：`play:`=`play_minion:`、`cast:`/`dragcast:`=
`play_spell:`、`refresh`=`reroll`、`choice[<i>]`=`choose[<i>]`。

## 6. 截图协议

| 截图 | 触发 | 保存位置 | 用途 |
|---|---|---|---|
| 每动作 | 每次 click/drag 后 | `screenshots/actions/a%04d_<kind>_<note>.png` | 逐步复盘 |
| 失败 | `_fail()` | `screenshots/` | 定位单动作 |
| 结算 | 每回合操作结束 | `settled/turn_XX.json` + `screenshots/*_turnXX_settled.png` | 资源/场面判断 |
| 密集 burst | 同回合 2 次 no-effect 或同 key 重复失败 | `diagnostics/<...>/meta.json` + 5 帧 | 定位卡住/弹层/失焦 |
| 对局结束 | `game_over` | `screenshots/*_game_over.png` | 名次/结算 |
| 启动链 | `_enter_game` 尝试/成功/超时 | `screenshots/*_start_game_ok.png`、`*_start_wait.png`、`*_start_failed.png` | 证明“自动进入游戏” |
| 英雄选择 | 选中/确认成功或最终失败 | `screenshots/*_hero_selected.png`、`*_hero_confirm_no_effect.png`、`*_hero_select_failed.png` | 证明“点解锁卡→确认(0.50,0.789)” |
| 入局动画 | 每个新对局 turn1 首次 `recruit` | `screenshots/*_recruit_settle.png` | 记录 7s 无效点击窗口 |
| 黑暗之赐/三选一 | 按钮点击后 `choices` 出现 | 每动作截图 + `actions.jsonl` 的 `choices` | 证明三选一流程 |
| END_TURN | 状态变化或 `auto_timer` | `screenshots/*_end_turn_auto.png` | 记录单人局限制 |

规则：

- 截图前必须 `_focus()`，否则抓到的可能是覆盖层/终端；
- 每次截图同时保存对应 state（至少 settled/diagnostics 必须）；
- 保留原始全分辨率，不做 OCR 替代。

## 7. 动作实现矩阵（2026-10-22 实机验证）

| Live 操作 | bot 状态 | 模拟器 | 实测证据 |
|---|---|---|---|
| buy | 已实现（拖 shop→hand；**点击购买无效，必须拖拽**） | `BUY` | `runs/live/live_20261022_2336_bot37/actions.jsonl` |
| play minion | 已实现（拖 hand→board；点手牌选中→点棋盘也可） | `PLAY_MINION` | 同文件 `play_*` |
| play spell 无目标 | 已实现（拖到棋盘中央） | `PLAY_SPELL` | run1 `play_spell:BG28_810` 成功 |
| play spell 有目标 | 已实现：`legal.play[i].use.targets` 拖拽→点击兜底 | `PLAY_SPELL` | run2 `play_spell:*->board[*]` |
| play spell choose-one + 目标 | **已实现三段式**：`use.modes` 取合法目标 → 拖到目标弹出 Choose One → 点选项 (0.406/0.631,0.489) → 再点目标结算 | `PLAY_SPELL` | gap L06/L15；run4 截图确认交互，待 live 复验 |
| sell | 已实现（拖随从到 Bob） | `SELL` | 旧 run |
| reroll | 已实现（顶部右侧 0.572,0.156） | `REROLL` | run1 turn1 成功 |
| upgrade | 已实现（顶部左侧 0.406,0.144） | `UPGRADE` | 旧 run |
| freeze | **已实现**（0.6375,0.133；验证 `shop[*].frozen` 翻转） | `FREEZE` | run1 turn2 |
| hero power | **已实现**（0.5875,0.767 + `legal.powers[].targets`，可带目标） | `HERO_POWER` | run1 turn1（gold-1、powers 清空） |
| activate | **已实现代码**（`legal.activate` → 点随从 + 目标），本轮对局未遇到 Activate 随从，待真实用例 | `ACTIVATE` | `tests/test_live_clickbot.py` |
| dark gift/choose | **已实现**（0.8375,0.264 → 三选一 → 手牌获得带赐福随从） | `USE_DARK_GIFT` | run1 turn3 `choose[0]:BG36_116` |
| end turn | **已实现尝试**：按钮/`E` + 状态验证；单人局无手动按钮 → 记 `end_turn:auto_timer`，不谎报 | `END_TURN` | run1 |
| 三连奖励/发现确认 | 部分：discover 三选一直接点选；饰品商店四选一需「确认」 | `CHOOSE` | run1 |
| 饰品商店 | 已实现（点卡 + 确认 0.500,0.713） | `CHOOSE` | `runs/live/recon/231643_t6.png` |
| 随从换位/重排 | **未实现** | 引擎有 position | gap L05 |
| 战斗过渡 | 半自动：战斗自动推进；脏帧只等待，不再反复点 start_combat | 无（真实 UI） | run1 combat 自动推进 |

> 未实现项必须进入 `docs/LIVE_TO_SIM_GAP.md` 的 gap 表，而不是只留在 issue 里。

### 7.1 37.0 new UI 校准表（1600x900 client，2026-10-22 实测）

客户端 window client rect = `(160,101,1760,1001)`；所有点击使用窗口内相对坐标。

| 元素 | 坐标 | 验证方式 | 证据 |
|---|---|---|---|
| 主菜单「酒馆战棋」 | (0.500, 0.378) | 点击后进入 BG 大厅/排队（state 仍 `no_active_game`） | `runs/live/current_screen.png` |
| 大厅「开始」 | (0.759, 0.778) 主 / (0.7172, 0.803) 备 | 进入英雄选择 | run `*_start_game_ok.png` |
| 英雄卡 4 张 | x=0.2406/0.4094/0.5719/0.7406, y=0.478 | 点卡后「确认」可用 | `runs/live/hero_after_confirm.png` |
| 英雄「确认」 | (0.500, 0.789) | 点选英雄后推进；**旧 (0.544,0.622) 落在卡上不是确认** | 同上 |
| 升级酒馆 | (0.406, 0.144) | tier/gold 变化 | `runs/live/recon/hover_batch1_top_hex1.png` |
| 刷新 | (0.572, 0.156) | tooltip「刷新」+ shop 变化 | `hover_batch1_top_hex2.png` |
| 冻结 | (0.6375, 0.133) | tooltip「冻结」+ `shop[*].frozen` 翻转 | `hover_batch1_top_hex3.png` / run1 |
| 英雄技能 | (0.5875, 0.767) | tooltip 技能名 + gold/powers 变化 | `hover_batch1_bottom_heropower.png` |
| 黑暗发现 | (0.8375, 0.264) | tooltip「黑暗发现…(还剩N次)」+ `choices=3` | `hover3_lower_red.png` / `dg_choice.png` |
| 开始战斗（过渡） | (0.8125, 0.461) | 战斗过渡按钮；通常自动推进，不主动点 | `runs/live/recon/231607_neutral.png` |
| shop 行 | y=0.372；中心 0.500；间距 0.0775(≤4 格)/0.0688(≥5 格) | 拖拽买入成功 | 布局截图 |
| board 行 | y=0.545；中心 0.500；间距 0.0775 | 拖/点出牌成功 | 布局截图 |
| hand 行 | y=0.930；中心 0.465；间距 0.0625 | 点手牌选中成功 | run1 |
| discover 三选一 | y=0.444；x 中心 0.5±0.19 | 点卡直接选中 | `runs/live/recon/dg_choice.png` |
| 饰品四选一 | y=0.400；间距 0.148；中心 0.51；确认 (0.500,0.713) | 点卡→确认 | `231643_t6.png` |
| 入局动画 | 新对局 turn1 约 7s 内点击无效（对手 VS/英雄弧） | 期间只等待、不点击 | `232237_fail_50258.png` |

已知 UI 陷阱（实测）：

1. **手牌 hover 放大预览**：鼠标停在手牌上时，客户端把卡放大到屏幕中央
   （约 y=0.33–0.87），会挡住商店行；买入拖到手后必须 `park_mouse()`。
2. **targeting 残留**：目标法术拖到空处失败后，客户端停在选目标模式；
   必须右键取消（`cancel_targeting()`），否则后续买/打全部失效。
3. **商店行重排动画**：买入成功后卡牌行会重排居中，动画期间按旧坐标会点空；
   每个成功动作后等 0.45s。
4. **choose-one + 需要目标** 的法术（如 BG31_880 Alliance Flag）是三段式交互：
   ① 把法术从手牌拖到合法随从目标上 → 弹出 Choose One 两张选项卡
   （实测中心 (0.406,0.489) / (0.631,0.489)）；
   ② 点选项 → 进入选择目标状态；
   ③ 再点目标随从 → 结算。
   `legal.play[i].use.modes` 给出每个模式的合法目标列表。
   证据：`runs/live/live_20261022_2352_bot37_v2/screenshots/actions/235336_a0021_drag_play_spell_BG31_880-_board_0_.png`、
   `235340_a0023_click_choose_one.png`。代码已按此实现，待 live 复验（L06/L15）。

更新坐标必须：① 附新截图证据；② 同步 `tests/test_live_clickbot.py` 的布局断言。


## 8. 验证与失效处理

- 动作前后比较 `state` 签名：`phase/turn/gold/board stats/hand/choices`;
- 成功：任一签名变化；
- 失败：加入本回合黑名单 key（`buy:.../play:.../...`）；
- 同回合 2 次 no-effect → 密集截图；
- 每回合最多 30 个动作，避免死循环；
- 刷新/升级等候选动作带**搜索预算**，不是固定次数；
- 金币/商店/手牌变化后必须清空黑名单，重新决策。

## 9. 生命周期

```text
启动 Battle.net UI → 进入游戏 → 主菜单/酒馆战棋 → 排队
→ 英雄选择（点解锁英雄卡 → 确认）→ 入局动画（约 7s 只等待）
→ 招募循环（N 回合）→ 战斗自动推进 → 结算
→ 结果页 → 大厅 → 主菜单 → 下一局
```

自动进入对局（`ClickBot._enter_game`）规则：

- 只在状态明确时点击：`no_active_game` / `lobby` / `menu`（点「酒馆战棋」→「开始」）、
  `game_over`（点结果页「继续」）；
- `phase` 为空（登录页/启动页/内存未就绪）**只截图等待，不点击**；
- 每次点击前先 `press_escape()` ×2 收回任务/游戏弹窗；
- 成功进入 `hero_select`/`recruit` 后写 `start_game_ok` 日志 + 截图；
- 超时（默认 240s，`--start-timeout`）写 `start_failed` + 截图，不无限点。

异常路径：

- 无窗口/进程退出 → `launcher` 重开战网 + 进入游戏；
- 内存读取崩溃 → 子进程失败，主循环继续，重试；
- 状态长期为空 → `game_unavailable`，重新连接（无窗口时再次拉起客户端）；
- 游戏结束 → 点击结果页 → 大厅 → 开始下一局；
- 目标法术失败 → **右键取消 targeting**（否则整回合后续动作都会被吃掉）；
- 拖拽买入后 → **鼠标 park 到顶部空白**（否则手牌 hover 放大预览覆盖屏幕中部，
  下一次点商店会被预览层挡住，表现为“买入 no_effect”）；
- 每个成功动作后等 0.45s 再决策（商店行重排动画期间点击会落空）；
- 入局动画期（新对局 turn1）→ 7s 内只等待，避免动作无效和黑名单污染。


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

## 11. 安全与隐私

- 只读内存、只发送鼠标输入，不注入、不改游戏文件、不自动登录；
- 运行目录不提交 `runs/`，截图/日志不含账号密码；
- 不将原始 `hsdata` 大文件入库，重建走 `docs/DATA_REBUILD.md`。

## 12. 快速命令

```powershell
# 正常采集（默认每动作截图）：自动进入游戏 + 新动作
python hsbg/live/click_bot.py --games 0 --max-seconds 0 `
  --out-dir runs/live/live_$(Get-Date -Format yyyyMMdd_HHmmss)

# 证据/验收 run：前几回合各演练一次 freeze/hero_power/use_dark_gift/end_turn，
# 跑 1 局后退出（自动进入游戏 + 英雄选择 + 动作全覆盖）
python hsbg/live/click_bot.py --games 1 --max-seconds 900 --exercise-actions `
  --out-dir runs/live/live_$(Get-Date -Format yyyyMMdd_HHmmss)_fix

# 关闭每动作截图
python hsbg/live/click_bot.py --no-action-shots ...

# 直接读内存（快但可能崩，仅调试）
python hsbg/live/click_bot.py --direct-state ...

# 自动进入对局的最长等待（登录/排队慢时调大）
python hsbg/live/click_bot.py --start-timeout 300 ...
```

单测（不接触真实游戏）：

```powershell
python -m pytest tests/test_live_clickbot.py -q
```


---

相关文档：

- 动作/状态差距：[LIVE_TO_SIM_GAP.md](LIVE_TO_SIM_GAP.md)
- 动作记录 schema：[schemas/live_action.schema.json](schemas/live_action.schema.json)
- 环境契约：[ENV_SPEC.md](ENV_SPEC.md)
- 数据重建：[DATA_REBUILD.md](DATA_REBUILD.md)
