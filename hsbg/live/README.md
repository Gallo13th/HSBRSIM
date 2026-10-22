# `hsbg/live` —— 自动代打数据采集（Windows 输入 + 实时状态机）

> 用途：让脚本自动打炉石酒馆战棋，持续产生 `Power.log` / HDT 日志 / 对局记录。
> **默认 dry-run**：不发送任何真实鼠标/键盘事件；只有显式 `--live` 才真正操作。
> 自动化输入可能违反游戏服务条款，账号风险由使用者自行承担（本模块只在
> 用户明确要求、且仅本机单人使用的前提下提供）。

## 1. 快速开始

```powershell
cd C:\HSagent

# 1) 只验证计划/状态机（不需要游戏窗口，会自动用 SimulatedWatcher）
python scripts/livebot.py --games 5 --dry-run
python scripts/livebot.py --games 2 --dry-run --simulate

# 2) 查看/修改坐标（窗口内相对比例）
python scripts/livebot.py --list-coords
python scripts/livebot.py --set coords.points.end_turn=0.935,0.600 --show-config

# 3) 校准：截图 + 网格 + 标注（有游戏窗口时直接 --capture）
python tools/livebot_calibrate.py --image runs/live/game_screen.png
python tools/livebot_calibrate.py --capture --out runs/live/calibrated.png

# 4) 真实代打（先确保坐标已校准；F12 暂停/恢复，Ctrl+C 退出）
python scripts/livebot.py --games 20 --live
```

产物：`runs/live/<mode>_<时间戳>/` 下
- `records.jsonl`：每局一行（开始/结束时间、回合数、名次（若内存可读）、
  Power.log / HDT 日志路径、动作数、结束原因）
- `events.jsonl`：阶段/错误/对局开始结束事件
- `summary.json` / `config_snapshot.json`
- 错误截图：`runs/live/.../error_<时间戳>.png`（live 模式）

## 2. 组件

| 文件 | 作用 |
|------|------|
| `config.py` + `config.json` | 窗口/坐标比例/节奏/路径/安全项；支持 `--set key=value` 覆盖 |
| `wininput.py` | Win32 输入层（ctypes，无第三方硬依赖）：找窗口、DPI aware、相对坐标映射、点击/拖拽/按键、前台管理、F12 暂停、截图；`pyautogui` 可选 fallback；`DryRunBackend` 供 dry-run/测试 |
| `logwatch.py` | 实时状态：优先 `hsbg.bridge.live_log.LiveLogWatcher`，否则内置 Power.log+HDT tail；
- HDT 日志：`HandleGameStart/TurnStart`、`StartCombat/StartShopping`、`HandleGameEnd`
- Power.log：`CREATE_GAME`、`tag=TURN`、`DebugPrintOptions(type=END_TURN)`、`EntityChoices`、`STEP MAIN_END`、本地英雄死亡
- 输出 `LiveSnapshot(phase, turn, game_id, session_id, in_game, choice_active, ...)` |
| `memory_state.py` | 适配 rea-operator `tools/live_state_mem.read_live_state()`（`hsbg.live_state.v1`）：内存优先（shop/hand/board/choices/gold/tier/health），失败静默降级 |
| `planner.py` | 纯状态机：`LiveSnapshot (+memory) → [PlannedAction]`；每回合脚本、速率限制、结束回合重试、盲操作兜底 |
| `runner.py` | 主循环：poll watcher → memory → planner → 执行；归档 records/events；暂停/Ctrl+C/超时/错误截图；`SimulatedWatcher` 供无游戏环境演示 |
| `scripts/livebot.py` | CLI 入口 |
| `tools/livebot_calibrate.py` | 截图 + 比例网格 + 按钮/槽位标注，输出 `runs/live/calibrated*.png` 与坐标表 |

## 3. 实时状态来源与降级顺序

```
内存状态（tools.live_state_mem.read_live_state，最精确）
        ↓ 不可用
日志 watcher（hsbg.bridge.live_log → 内置 Power.log/HDT tail）
        ↓ 不可用 / 无日志
盲操作（固定时间脚本：菜单→大厅→英雄→每 blind_turn_s 一回合 → blind_game_duration_s 视为结算）
```

对局阶段：`menu` / `lobby` / `hero_select` / `recruit`（我方回合，可操作）/
`combat`（对手回合，等待）/ `choice`（发现·三选一·任务）/ `game_over`。

## 4. 坐标（窗口内 0–1 相对比例）——2026-10-19 实机 16:9 校准

**重要：必须先保证游戏窗口是 16:9 client**（例如 1780x1001 / 1920x1080 / 1600x900）。
非 16:9 时（如 1920x1009 = 1.903）酒馆战棋 UI 底部/右下会被裁掉：手牌下缘被切、
布局错位。`wininput` 默认按 **client rect** 映射（`window.use_client_rect=true`）。

| 名称 | 当前默认（client 比例） | 校准状态 |
|------|--------------------------|----------|
| `menu_battlegrounds` | (0.4995, 0.3922) | ✅ 主菜单实机（「酒馆战棋」按钮） |
| `lobby_play` | (0.7172, 0.8028) | ✅ 大厅右侧蓝色「开始」圆钮 |
| `lobby_back` | (0.7810, 0.9230) | ✅ 大厅右下「返回」 |
| `lobby_play_again` | (0.7172, 0.8028) | ✅ 结算后回大厅再点「开始」 |
| `hero_options[0..3]` | y=0.436，x=0.25/0.4115/0.5766/0.7344 | ✅ 英雄选择 4 卡中心（锁住的点了无反应，planner 自动换下一个） |
| `hero_confirm` | (0.5000, 0.7582) | ✅ 英雄选择「确认」 |
| `choice_options[0..2]` | y=0.41，x=0.336/0.501/0.666 | ✅ 发现/三选一三张大卡中心 |
| `choice_confirm` | (0.5000, 0.7900) | ⚠️ 多数选择点卡即生效，确认点仅兜底 |
| `end_turn` | (0.7917, 0.4410) | ⚠️ **酒馆战棋单人模式没有结束回合按钮**（见下），仅特殊 UI 用 |
| `hero_power` | (0.5920, 0.7900) | ⚠️ 默认不点（`flow.use_hero_power=false`） |
| `shop[0..6]` / `board[0..6]` / `hand[0..9]` | 仅兜底；实际用 `coords.layout` 动态计算 | ✅ |

动态布局参数（`coords.layout`，按"当前格数"居中）：

```json
{"shop_y": 0.356, "shop_spacing": 0.068229, "board_y": 0.715,
 "board_spacing": 0.068229, "hand_y": 0.900, "hand_spacing": 0.057292,
 "hand_center_x": 0.480, "center_x": 0.5}
```

实测要点：
* 商店 4 个 offer 时卡中心约 image x=765/896/1027/1158（间距 131px），y≈0.356；
  planner 按 `memory.shop` 数量动态居中（4/5/6/7 个都能对上）。
* 购买：商店→手牌区 **拖拽到 (0.5, 0.90)**（y=0.90 落在手牌栏）→ 金币下降、手牌 +1；
  直接拖到棋盘 (0.5,0.715) 未见成功，因此默认 `flow.buy_to_hand=true`。
* 出牌：手牌源点 = `hand_center_x=0.48`、`hand_y=0.90`（抓手牌可见上半部；
  16:9 下手牌完整可见但贴底），落点 **(0.5, 0.715)** → 棋盘 +1。
* **结束回合**：酒馆战棋**单人模式没有结束回合按钮**（招募阶段由计时器自动结束；
  "开始战斗"按钮只在计时结束后出现，用于跳过等待）。因此默认
  `flow.send_end_turn=false`，planner 买/出牌后只等待 turn/phase 变化；
  如需 Duos/特殊 UI 可置 true 并用 `end_turn` 坐标。实测对计时框/右侧竖槽
  （hover 显示"第N回合"）/右下区域全部候选点均无效果，**不是输入被过滤**
  （同期购买/出牌/选英雄/开始按钮都有效）。

窗口：实机 16:9 例 `outer=(0,0,1796,1040)`、`client=(8,31,1788,1032)=1780x1001`；
`wininput` 自动读取 client rect，坐标比例与分辨率无关（换 1600x900 也可用）。
校准后请把新比例写回 `hsbg/live/config.json` 或用 `--set` 临时覆盖。

## 5. 记录 schema

`records.jsonl`（每局一行）：

```json
{"kind":"game","game_no":1,"game_id":1,"session_id":"ef8013ace8ae",
 "started_at":1792336112.6,"ended_at":1792336350.2,"duration_s":237.6,
 "turns":9,"placement":6,"reason":"game_over",
 "power_log":"C:/.../Power.log","hdt_log":"C:/.../hdt_log.txt",
 "power_log_archive":"./logs/game_01_Power.log",
 "actions":186,"errors":0,"dry_run":false,"blind":false}
```

说明：
* `game_id` 用**本地递增序号**（bridge 的 game_id 跨局可能恒为 0，不能做每局去重键）；
* `power_log` 是**本局**动态发现的 Power.log 路径（会话内换局时同一路径会截断复用，
  因此 `power_log_archive` 在每局结束时把当时内容复制到 `<session>/logs/game_NN_Power.log`，
  离线解析请优先用 archive）；
* `placement` 由内存 `alive/alive_count` 推导（死亡时仍有 N 人存活 → 第 N+1 名）。

## 6. 安全 / 运维

* 默认 `dry-run`（`safety.dry_run_default=true`），`--live` 必须显式；
* `--live` 前会检查 Hearthstone 窗口，找不到直接退出（乱点桌面风险为 0）；
* **客户端存活检测**：每 tick 检查进程+窗口，连续 `flow.client_gone_s`（默认20s）
  检测不到 → 本局记 `client_gone`；`flow.restart_client=true` 时自动用
  `Battle.net.exe --exec=launch WTCG` 重启、等窗口/内存就绪、点掉启动页后继续；
* **结算页**：先点 `result_continue` 回大厅，连续点不动会有限次 nudge
  （ESC/中心/继续），超过 `flow.max_game_over_retries` 记 `game_over_stuck` 并停止，
  不再盲点（之前盲点大厅坐标可能误触退出客户端）；
* F12 暂停/恢复；每回合动作上限、单局超时、连续错误上限、错误截图；
* Ctrl+C 会归档当前局并写 summary；所有输入只在游戏窗口前台时发送。

## 7. 与其它模块的接口

* `hsbg.bridge.live_log.LiveLogWatcher`：已就绪时自动使用
  （`snapshot()` 的 `phase/game_active/turn/pending_choice_window/...` 被映射为
  `LiveSnapshot`）；未就绪则回退内置 Power.log+HDT tail。
* `tools/live_state_mem.read_live_state()`：已就绪时自动接入（`hsbg.live_state.v1`），
  按 `flow.memory_poll_s` 节流；内存不可用/无对局时自动回退日志状态。
* 后续接训练：records 里的 Power.log 路径 + `hdt_log` 可直接给
  `hsbg.bridge.live_log` / `hsbg.bridge.powerlog` 离线解析；内存状态若落盘
  （`--memory-reader` 自定义）可给 BC 数据集补充 shop/hand/board 标签。

## 8. 已知限制

* 盲操作模式只按固定时长推演，无法感知真实战况，只作为日志/内存都不可用时的兜底；
* **酒馆战棋单人模式没有结束回合按钮**：招募阶段靠计时器自动结束（"开始战斗"只在
  计时结束后出现，用于跳过等待）。`flow.send_end_turn=false` 是正确默认；开启后
  `end_turn` 坐标仅供 Duos/特殊 UI 使用；
* 窗口必须是 **16:9 client**（否则 UI 底部/右下被裁：手牌下缘切掉、按钮不可见）；
  换分辨率后由于按 client 比例映射，通常无需重校；换 DPI/超宽屏需重新校准；
* 名次依赖内存读取（`alive/alive_count` 推导）或 bridge watcher 的 placement；
  HDT 日志本身通常不含 BG 名次；
* 日志有延迟（Power.log 批量 flush、HDT 事件延迟），`choice` 窗口可能滞后 1–2 个 tick，
  因此 planner 对 choice 有一次性处理 + 不快进保护；
* 手牌/商店随从数量由内存状态决定（内存不可用时退化为固定 7 张）；内存读取失败会
  自动降级为日志状态（事件里记录 memory_error）。

## 9. 实机验证记录（2026-10-19）

* 窗口：`outer=(0,0,1796,1040)`、`client=(8,31,1788,1032)=1780x1001`（16:9）；
* **连续 2 局验证（重启流程修复后）**：`runs/live/collect_fix3/records.jsonl`
  - game 1：placement=8、9 turns、207 actions、780.8s、errors=0
  - game 2：placement=6、9 turns、161 actions、723.0s、errors=0
  - 流程：game_over → result_continue/nudge(1-4 次) → 回大厅 → 排队 → 选英雄 → 第 2 局正常开打；
    无 `client_gone`、无 `game_over_stuck`，Power.log/HDT 路径正常记录；
* 更早：`runs/live/live_final/`（placement=7、16 turns、217 actions、920s）与
  `runs/live/live_16x9_full/`（8 turns）为单局/校准记录；
  `live_first*/`、`collect_1/` 为旧的非 16:9/重开流程未修版本（含失败/掉线记录，可忽略）。
