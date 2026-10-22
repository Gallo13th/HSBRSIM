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

### 5.2 note 命名协议

```text
buy:<card>
play:<card>
cast:<card>
cast:<card>-><zone>[<index>]
dragcast:<card>-><zone>[<index>]
select:<card>
target:<zone>[<index>]
sell:<card>
refresh
upgrade
choice[<i>]:<card>
choice_confirm
choose_one
hero_option / hero_confirm / hero_locked_cancel
start / menu_battlegrounds / start_combat / result_continue
```

## 6. 截图协议

| 截图 | 触发 | 保存位置 | 用途 |
|---|---|---|---|
| 每动作 | 每次 click/drag 后 | `screenshots/actions/a%04d_<kind>_<note>.png` | 逐步复盘 |
| 失败 | `_fail()` | `screenshots/` | 定位单动作 |
| 结算 | 每回合操作结束 | `settled/turn_XX.json` + `screenshots/*_turnXX_settled.png` | 资源/场面判断 |
| 密集 burst | 同回合 2 次 no-effect 或同 key 重复失败 | `diagnostics/<...>/meta.json` + 5 帧 | 定位卡住/弹层/失焦 |
| 对局结束 | `game_over` | `screenshots/*_game_over.png` | 名次/结算 |

规则：

- 截图前必须 `_focus()`，否则抓到的可能是覆盖层/终端；
- 每次截图同时保存对应 state（至少 settled/diagnostics 必须）；
- 保留原始全分辨率，不做 OCR 替代。

## 7. 动作实现矩阵（当前）

| Live 操作 | bot 状态 | 模拟器 |
|---|---|---|
| buy | 已实现（拖 shop→hand，0 费修复） | `BUY` |
| play minion | 已实现（拖 hand→board） | `PLAY_MINION` |
| play spell 无目标 | 已实现 | `PLAY_SPELL` |
| play spell 有目标 | 已实现拖拽优先 + 点击回退，仍待稳定验证 | `PLAY_SPELL` |
| sell | 已实现（拖到 Bob） | `SELL` |
| reroll | 已实现（顶部右侧） | `REROLL` |
| upgrade | 已实现（顶部左侧，`legal.upgrade` 前置） | `UPGRADE` |
| freeze | **未实现** | `FREEZE` |
| hero power | **未实现** | `HERO_POWER` |
| activate | **未实现** | `ACTIVATE` |
| dark gift/choose | 部分（choice/choose_one） | `USE_DARK_GIFT` / `CHOOSE` |
| end turn | **未实现**（靠计时器） | `END_TURN` |
| 三连奖励/发现确认 | 部分 | `CHOOSE` |
| 饰品商店 | card + 确认已实现 | `CHOOSE`/`USE_DARK_GIFT` |
| 随从换位/重排 | **未实现** | 引擎有位置参数，环境动作未暴露 |
| 战斗开始确认 | 已加兜底 `start_combat`，但触发过多 | 无（真实 UI） |

> 未实现项必须进入 `docs/LIVE_TO_SIM_GAP.md` 的 gap 表，而不是只留在 issue 里。

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
→ 英雄选择/开始战斗 → 招募循环（N 回合）
→ 战斗等待 → 结算 → 回大厅 → 下一局
```

异常路径：

- 无窗口/进程退出 → `launcher` 重开战网 + 进入游戏；
- 内存读取崩溃 → 子进程失败，主循环继续，重试；
- 状态长期为空 → `game_unavailable`，重新连接；
- 游戏结束 → 点击结果页 → 大厅 → 开始下一局。

## 10. 协作协议（持续开发）

### 10.1 角色与写入范围

| 角色 | 写入范围 |
|---|---|
| Lead | `hsbg/live/**`、`docs/live*`、`tests/test_live*`、`scripts/demo*` |
| live-gap-analyst | `runs/live/analysis/**`（只读代码/截图） |
| env-builder | `hsbg/env/**`、`tests/test_env*` |
| engine-analyst | `hsrl2/**` 只读；规则问题写 `docs/ENGINE_NOTES.md` |

跨范围修改必须先读文件、最小 diff，并在回复中说明。

### 10.2 问题闭环

1. 采集：`actions.jsonl` + 截图 + state；
2. 归类：代码层 / UI 坐标 / 状态滞后 / 引擎缺失 / 规则缺失；
3. 记录 gap：`docs/LIVE_TO_SIM_GAP.md` 新增一行（含截图、动作、期望）；
4. 热修：`hsbg/live` 内改；涉及 env/引擎则另开任务；
5. 验证：同 seed/同局面复跑，至少 1 局无同类 no-effect；
6. 回归：`pytest tests` + `pytest hsrl2/tests` + live smoke；
7. 文档：更新本协议/gap 表/提交号。

### 10.3 每局验收

- 无 `state_reader` 崩溃（或已恢复）；
- 无连续 3 次相同 no-effect；
- 金币/手牌/商店可用时至少尝试一次；
- 英雄选择、饰品选择、结算、下一局自动推进；
- 产出 `settled/turn_*.json` 与 `screenshots/actions/`。

## 11. 安全与隐私

- 只读内存、只发送鼠标输入，不注入、不改游戏文件、不自动登录；
- 运行目录不提交 `runs/`，截图/日志不含账号密码；
- 不将原始 `hsdata` 大文件入库，重建走 `docs/DATA_REBUILD.md`。

## 12. 快速命令

```powershell
# 正常采集（默认每动作截图）
python hsbg/live/click_bot.py --games 0 --max-seconds 0 \
  --out-dir runs/live/live_$(Get-Date -Format yyyyMMdd_HHmmss)

# 关闭每动作截图
python hsbg/live/click_bot.py --no-action-shots ...

# 直接读内存（快但可能崩，仅调试）
python hsbg/live/click_bot.py --direct-state ...
```

---

相关文档：

- 动作/状态差距：[LIVE_TO_SIM_GAP.md](LIVE_TO_SIM_GAP.md)
- 动作记录 schema：[schemas/live_action.schema.json](schemas/live_action.schema.json)
- 环境契约：[ENV_SPEC.md](ENV_SPEC.md)
- 数据重建：[DATA_REBUILD.md](DATA_REBUILD.md)
