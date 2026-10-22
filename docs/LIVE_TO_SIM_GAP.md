# Live → Simulator 差距表（Gap Ledger）

> 目的：把 live bot 截图/日志里暴露的“真实客户端需要、但 bot 或模拟器缺失”的操作，
> 变成可跟踪、可验收的补全项。每条 gap 必须能指到截图/动作/状态证据。

## 1. 最近一轮观测摘要

数据来源：`runs/live/clickbot_every/actions.jsonl`（约 678 个动作，26 个 settled，
95 次 no-effect，42 次密集诊断；截至 2026-10-22 21:58）。

动作分布（note 前缀）：

| 操作 | 次数 | 备注 |
|---|---:|---|
| buy | 129 | 已实现；0 费卡曾因 `cost or 3` 被跳过，已修 |
| start_combat | 90 | 兜底触发过多：英雄页/战斗页状态不一致时反复点 |
| choice[0]/choice_confirm | 62/59 | 饰品/发现选择；需卡+确认 |
| play | 47 | 随从 |
| cast | 41 | 法术（含无目标/目标） |
| choose_one | 38 | 法术二选一；部分仍失败 |
| target | 34 | 目标法术点选 |
| dragcast | 31 | 目标法术拖拽 |
| refresh | 24 | 顶部刷新 |
| select | 22 | 目标法术选手牌 |
| start | 20 | 开始按钮 |
| sell | 17 | 卖随从 |
| hero_option/confirm | 8/8 | 英雄选择 |
| upgrade | 6 | 升本 |
| freeze | 0 | **未实现** |
| hero_power | 0 | **未实现** |
| end_turn | 0 | **未实现**（靠计时器） |
| reorder/move | 0 | **未实现** |
| triple_reward | 0 | 未单独处理 |

结论：bot 已覆盖“买卖打刷升 + 基本选择”，但**冻结、英雄技能、主动结束回合、
三连奖励、随从换位、目标选择稳定性**仍是空白或弱项。

### 1.1 本轮截图直接证据

- `runs/live/clickbot_every/screenshots/actions/220022_a0692_drag_play_BG36_345.png`
  - 画面：第 4 回合、gold=0、board 6、顶部雪花冻结按钮可见、右下英雄技能按钮可见；
  - 但动作日志只有 buy/play/refresh，没有 `freeze`/`hero_power`；
- `runs/live/clickbot_every/actions.jsonl`：
  - `start_combat` 90 次，说明英雄/战斗页状态识别兜底被反复触发；
  - `freeze` / `hero_power` / `end_turn` / `reorder` 均为 0 次；
- `runs/live/clickbot_every/screenshots/215824_turn02_settled.png`：
  - 金币 0、商店 2、手牌 0，只能等待；说明“资源用尽”判定与 active end turn 缺失。

## 2. Gap 表

| ID | 真实操作 | 证据 | bot | 模拟器/环境 | 建议 | 优先级 |
|---|---|---|---|---|---|---|
| L01 | 冻结/解冻酒馆 | 截图顶部雪花按钮；日志无 `freeze` | 未实现 | `ActionKind.FREEZE` 已支持 | 加 `freeze_shop`：点顶部雪花，校验 shop.frozen | P1 |
| L02 | 英雄技能（含目标） | 英雄技能按钮；`legal.powers` 未用 | 未实现 | `HERO_POWER` 已支持 | 读 `powers`，按技能目标点击；无目标直接点 | P0 |
| L03 | 主动结束回合 | 目前等计时器；`legal.end` 未用 | 未实现 | `END_TURN` 已支持 | 无买/打/刷/升时点“结束回合”按钮 | P1 |
| L04 | 三连奖励/发现确认 | 三连后 `choices`/弹层 | 部分 | `CHOOSE` / `USE_DARK_GIFT` | 统一 `choice` 处理：卡+确认+重试 | P0 |
| L05 | 随从换位/重排 | 棋盘位置影响战斗 | 未实现 | 引擎 `position` 参数存在，env 候选少 | 增加 move 动作/拖拽重排；先记录 gap | P2 |
| L06 | 目标法术稳定命中 | `select/target/dragcast` 多次 no_effect | 弱 | `PLAY_SPELL` 支持 target | 目标坐标/高亮检测；失败时截 burst | P0 |
| L07 | 饰品商店确认 | 选卡后需“确认” | 已实现 | `CHOOSE` | 保持；补自动化回归 | P1 |
| L08 | 英雄选择后“开始战斗”页 | `start_combat` 90 次 | 兜底过多 | 无（UI 流程） | 只在截图/状态明确时点；加冷却 | P0 |
| L09 | 战斗阶段识别 | `phase=recruit` 但画面“当前战斗” | 启发式 | 环境有 phase；live 没有 | 截图特征/board 连续下降/等待 | P0 |
| L10 | 锁定/不可打手牌 | `locked=1` 跨回合占手牌 | 跳过 | 环境有 locked | 记录 locked 语义，确认是否可弃/不可用 | P2 |
| L11 | 0 费/免费升本 | 顶部升级按钮 0 费 | 已实现 `legal.upgrade` | `UPGRADE` | 验证 gold=0 且 legal=true 样本 | P1 |
| L12 | 空店刷新 | gold 4–7 + shop=[] | 已修顶部坐标 | `REROLL` | 回归：空店刷新成功 | P0 |
| L13 | 买后手牌满 | 截图“手牌已满” | 已加 hand-full 卖优先 | 环境有 hand cap | 加 buy 前 hand cap 校验 | P1 |
| L14 | 操作后延迟生效 | 3–4s 才变状态 | 验证窗口 3s | 环境即时 | live 增加“连续两帧稳定”再动作 | P1 |

## 3. 反哺模拟器/引擎的具体方式

### 3.1 截图 → 规则缺失

当截图显示某个交互（例如“选择一项并购买”饰品、二选一法术、三连奖励），
而 `hsrl2` 没有对应脚本/`PendingChoice`：

1. 在 gap 表新增行，附截图路径和动作 note；
2. 在 `docs/ENGINE_NOTES.md` 写规则依据（官方文本/build）；
3. 在 `hsrl2/scripts/` 补卡牌脚本或 `hsbg/env` 补动作；
4. 加回归测试：`tests/test_engine_fixes.py` 或 `tests/test_env_*.py`；
5. live 复跑同一局面，确认动作不再 no_effect。

### 3.2 截图 → 环境动作缺失

例如 live 能“冻结”，但 env 的 `CandidateAction` 未暴露/策略从未选：

- `hsbg/env/spec.py` 增加/确认 `ActionKind`；
- `hsbg/env/driver.py` 枚举与 apply；
- `docs/ENV_SPEC.md` 升 version；
- `tests/test_env_driver.py` 覆盖。

### 3.3 截图 → 观测字段缺失

例如 live 有 `frozen`、`locked`、`can_activate`，观测没暴露：

- 在 `Observation`/`extra` 增加字段；
- 保持旧字段兼容，升 `version`；
- live 与 env 双端回归。

## 4. Gap 记录模板

```json
{
  "id": "L06",
  "operation": "targeted_spell",
  "observed_at": "2026-10-22T21:58:24+08:00",
  "screenshot": "runs/live/.../screenshots/actions/a0123_cast_....png",
  "action_note": "dragcast:BG36_624->board[0]",
  "state": {"phase": "recruit", "turn": 11, "gold": 1},
  "expected": "目标随从获得 buff/法术结算",
  "actual": "state 无变化，随后 blacklist",
  "category": "live_ui|env_action|engine_rule|observation",
  "priority": "P0",
  "owner": "lead|env-builder|engine-analyst",
  "status": "open|fixed|verified"
}
```

## 5. 验收

- gap 表每一行有截图或 `actions.jsonl` 证据；
- 标为 `fixed` 的条目有对应测试/复跑记录；
- 同一 gap 不允许连续两轮 live 复现；
- 每次 live run 结束更新本表统计。

---

相关：[LIVE_AUTOMATION_PROTOCOL.md](LIVE_AUTOMATION_PROTOCOL.md)
