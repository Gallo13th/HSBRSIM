# 8 小时自主工作报告（2026-10-22 23:07 → 2026-10-23 07:00）

> 状态：进行中；07:00 前填写最终数据。本文由 Lead 汇总，证据链接必须可复现。

## 0. 执行摘要

- 目标：
  1. Battle.net → 进入游戏 → 酒馆战棋 → 开始/英雄选择 → 对局，自动完成；
  2. 真实对局采集 + 截图分析 + 实时热修；
  3. 按审计补 env/engine/card P0；
  4. 审计协议 + 多智能体协作规则；
  5. 07:00 停止并交付。
- 结论（待填）：
- 关键指标（待填）：
  - 自动进入游戏：PASS/FAIL，证据：
  - 自动开始下一局：PASS/FAIL，证据：
  - 修复的 P0 数：
  - 回归：hsrl2/tests、tests、verify_all、smoke。
  - live 采集：run_id / 截图数 / actions 数。

## 1. 实时自动化

### 1.1 启动链

| 步骤 | 实现 | 实测 |
|---|---|---|
| Battle.net 窗口定位 | `hsbg/live/launcher.py`：按进程路径含 `battle.net` | ✅ hwnd 264196 |
| 点击「进入游戏」 | client-relative `(0.08,0.895)` | ✅ Hearthstone 窗口出现 |
| 每日任务弹窗 | ESC ×2（任务→菜单→主菜单） | ✅ 到达主菜单 |
| 酒馆战棋入口 | `(0.50,0.378)` | ✅ |
| 开始 | `(0.759,0.778)` | ✅ 排队/英雄选择 |
| 英雄选择 | 点解锁英雄卡 → 确认 `(0.50,0.789)` | 待 live-automator 最终验证 |
| 自动下一局 | game_over → 继续 → 大厅 → 开始 | 待验证 |

### 1.2 live 动作校准（来自 recon）

| 动作 | 坐标/方式 | 状态 |
|---|---|---|
| buy | drag shop→hand | ✅ |
| play | click hand → click board | ✅ |
| freeze | `(0.6375,0.133)` | ✅ frozen=true |
| hero power | `(0.5875,0.767)` + 目标 | ✅ 金币 -1/powers 清空 |
| dark gift | `(0.8375,0.264)` → 三选一卡片 | ✅ 手牌 +1 |
| end turn | 单人局无按钮，靠计时器 | 记录 `auto_timer` |
| target 法术 | 拖拽优先 + 点击回退 | 待稳定 |

### 1.3 截图/诊断

- 每动作截图：`runs/live/<run>/screenshots/actions/`
- 失败截图 + 同回合 2 次 no-effect → 5 帧 burst
- 每回合 settled：`settled/turn_XX.json`
- 读内存子进程隔离，防 `bgcontroller` access violation

## 2. 审计与协议

### 2.1 审计

- [LIVE_AUTOMATION_PROTOCOL.md](LIVE_AUTOMATION_PROTOCOL.md)
- [AUDIT_PROTOCOL.md](AUDIT_PROTOCOL.md)
- [MULTI_AGENT_RULES.md](MULTI_AGENT_RULES.md)
- [AUDIT_LIVE_TO_SIM.md](AUDIT_LIVE_TO_SIM.md)
- [AUDIT_ENV_ACTIONS.md](AUDIT_ENV_ACTIONS.md)
- [AUDIT_ENGINE_MECHANICS.md](AUDIT_ENGINE_MECHANICS.md)
- [LIVE_TO_SIM_GAP.md](LIVE_TO_SIM_GAP.md)
- [AUDIT_CONSISTENCY.md](AUDIT_CONSISTENCY.md)

### 2.2 多智能体协作

- 任务板 claim/complete CAS
- 写范围隔离（见 AGENTS §4 / MULTI_AGENT_RULES）
- 每个 agent 完成后四段消息
- Lead 统一 commit/merge/最终报告

## 3. 已修复/已落地（待填）

| 层 | 改动 | 测试 | 证据 |
|---|---|---|---|
| env | move/reorder、Dark Gift gift_id、EoT 选择 | 待填 | 待填 |
| engine | 饰品 offer 过滤、choose+target、CHOOSE_BOTH | 待填 | 待填 |
| card | 英雄技能/Choose One/数据权威化 | 待填 | 待填 |
| live | 自动进入、英雄选择、freeze/HP/DG/buy/play | 待填 | 待填 |

## 4. 未完成/阻塞

- 待填（英雄技能子系统、Choose One 组合、真实对局等）

## 5. 回归结果

```text
# 07:00 前填入实际命令输出（命令+时间+passed/failed/耗时）
```

## 6. 风险与后续

- 待填

## 7. 证据清单

- `runs/live/...`
- `runs/audit/...`
- `git log --oneline`
- `docs/AUDIT_CONSISTENCY.md` 基线
