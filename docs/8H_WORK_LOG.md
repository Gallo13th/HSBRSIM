# 8 小时自主工作日志（2026-10-22 23:07 → 2026-10-23 07:00）

> Lead 维护。每 30–60 分钟更新一次：任务、证据、测试、阻塞、下一步。

## 0. 目标

1. Battle.net「进入游戏」→ Hearthstone → 酒馆战棋 → 开始 → 英雄选择/对局，全自动；
2. 真实对局截图/状态采集、实时分析/热修；
3. 按审计补 env/engine/card P0；
4. 审计协议 + 多智能体协作规则；
5. 07:00 停止并提交完整报告。

## 1. 角色/任务

| 任务 | owner | 内容 | 状态 |
|---|---|---|---|
| task-1 | env-auditor | move/reorder、Dark Gift gift_id 观测、EoT 选择 | in_progress |
| task-2 | engine-mech-auditor | 饰品 offer 过滤、choose+target、法术 CHOOSE_BOTH | in_progress |
| task-3 | card-script-builder | 17 英雄技能、10 base Choose One、数据权威化 | in_progress |
| task-4 | live-automator | 战网自动进入游戏、英雄选择、freeze/技能/发动/黑暗之赐/结束回合 | in_progress |
| task-5 | protocol-writer | 审计协议、多智能体规则、报告模板 | in_progress |
| task-6 | Lead | 集成、真实验证、最终报告 | in_progress |

## 2. 时间线

### 23:07–23:15 启动/侦察

- Battle.net 已在运行、登录；Hearthstone 未运行；
- `launcher.launch_hearthstone_via_battlenet()` 实测成功：
  - click Battle.net `进入游戏` at `(0.08,0.895)` → 窗口 ready；
- 游戏启动后卡在**每日任务弹窗**，用 ESC 两次可关闭（任务弹窗→游戏菜单→主菜单）；
- 自动进入酒馆战棋/排队/英雄选择已到达；
- 英雄选择页实测：4 卡（2 解锁）+ 底部确认；`HERO_CONFIRM` 旧坐标未推进，
  待 live-automator 校准；截图：`runs/live/hero_after_confirm.png`。

### 23:15+ 并行任务

- 5 个 teammate 已领取 task；
- 写范围隔离：engine 只改 game/actions/tests；card 只改 scripts/tests；
  env 只改 hsbg/env+test_env；live 只改 hsbg/live+test_live；协议只写 docs。
- Lead 暂停真实点击，把鼠标交给 live-automator。

### 23:08 自动进入游戏（Lead 验证）

- Battle.net 已登录且运行；Hearthstone 未运行。
- `hsbg.live.launcher.launch_hearthstone_via_battlenet()` 实测：
  - `find_battlenet_window` 找到主窗口（进程路径含 battle.net）；
  - 点击 `进入游戏` client `(0.08,0.895)`；
  - Hearthstone 窗口 ready，函数返回 True。
- 进入后卡每日任务弹窗：`ESC` 两次可关闭（任务→菜单→主菜单），
  再点 `酒馆战棋 (0.50,0.378)` + `开始 (0.759,0.778)` 到达英雄选择。
- 证据：`runs/live/autostart_real/actions.jsonl`、`runs/live/hero_auto_now.png`。
- 英雄选择页实测：4 卡（2 解锁）+ 底部“确认”；旧 `HERO_CONFIRM` 未推进，
  待 live-automator 继续校准；`runs/live/recon` 已有 freeze/hero power/
  黑暗之赐/结束回合的密集截图探测。

### 23:30 协议/审计

- protocol-writer 完成：`docs/AUDIT_PROTOCOL.md`、`docs/MULTI_AGENT_RULES.md`、
  `docs/LIVE_COLLAB_SECTION.md`、`docs/AUDIT_CONSISTENCY.md`；AGENTS 更新。
- 发现 C01 换位优先级冲突 → L05/L20 升 P0（已写入 gap 表）。
- C02 Dark Gift 43→47、C03 Choose One 对账、C08 ENV_SPEC 版本冲突已派单。

### 23:40–23:55 里程碑

- **env task-1 完成并提交**（`b4a12db`）：
  - `ActionKind.MOVE_MINION`、Observation.version=3；
  - Dark Gift `pending_choice_options`（gift_id/secondary_id 可观测）；
  - EoT/淘汰/对手期 auto-resolve 留痕（info/stats/errors）；
  - 24 条新测试通过；`pytest tests` 全绿。
- **engine task-2 完成并提交**（`7372b6f`）：
  - 饰品 offer REGISTRY 闸；choose+target 两阶段；法术实体 CHOOSE_BOTH；
  - `test_engine_choose_target.py` 18 passed；F-20 已写入 ENGINE_NOTES。
- **card task-3 完成并提交**（`ed765c3`）：
  - `choose_one_authority.py`；36 卡/36 脚本 missing=[]；
  - 10 base Choose One（17 def）；6 个 37.0 英雄技能落地，11 个 DEFERRED 有台账；
  - `hsrl2/tests 4800 passed / 6 skipped`；`tests 622 passed / 2 skipped`；
  - `verify_all --fast 4/4`；smoke 8 局 crashes=0。
- **protocol/AGENTS** 已更新，待合并 LIVE_COLLAB_SECTION。
- **live task-4**：
  - 自动进入游戏实机跑通：`runs/live/live_20261022_2328_bot37_fix/`，
    `start_game_ok phase=hero_select`；
  - 英雄选择：点解锁卡→确认 (0.500,0.789) 实机跑通；
  - FREEZE/HERO_POWER/USE_DARK_GIFT 实机验证；ACTIVATE 单测就绪无实机样本；
  - END_TURN 单人局无按钮，记录 auto_timer；
  - `tests/test_live_clickbot.py` 27 passed；
  - 最终两局验证 `runs/live/live_20261022_2330_bot37_final/` 运行中。



## 3. 关键产物

- 审计：
  - `docs/AUDIT_LIVE_TO_SIM.md`
  - `docs/AUDIT_ENV_ACTIONS.md`
  - `docs/AUDIT_ENGINE_MECHANICS.md`
- 协议：
  - `docs/LIVE_AUTOMATION_PROTOCOL.md`
  - `docs/LIVE_TO_SIM_GAP.md`
  - `docs/schemas/live_*.json`
- 复现：
  - `python scripts/audit_mechanism_coverage.py --out runs/audit/mechanism_coverage.json`
- live：
  - `runs/live/autostart_real/`
  - `runs/live/hero_after_confirm.png`

## 4. 风险/阻塞

- 游戏 UI 每日任务弹窗/游戏菜单需要 ESC 序列；
- 英雄选择确认坐标未稳定；
- 多 agent 共享工作树，需避免同文件写冲突（已做范围隔离）；
- `bgcontroller` 偶发 access violation，live 状态读取已子进程隔离；
- 8h 内不可能补完所有 17 英雄技能/全部 Choose One，按 P0/实际池优先。

## 5. 下一步

- [ ] live-automator：完成自动进入 + 英雄选择 + 开局截图；
- [ ] env-auditor：move 动作 + gift_id 观测测试通过；
- [ ] engine-mech-auditor：饰品过滤 + choose/target 组合测试通过；
- [ ] card-script-builder：至少 37.0 新英雄技能 + 数据字段；
- [ ] protocol-writer：审计协议/多智能体规则；
- [ ] Lead：集成 diff、跑 pytest hsrl2/tests + tests + smoke、真实局验证、写最终报告。

### 00:00–01:10 P1/收尾

- engine P1（09095da）：grant_random_trinket 过滤、PendingChoice 一次性/failed 终态、take_choice；
- policy P1（8bf8c5a）：obs v3/MOVE_MINION/entity_secondary 编码、checkpoint format 2 + 旧 ckpt 迁移；
- env P1（c9cb58d）：take_choice 全链路、choice 失败诊断、EoT 不可暂停结论；
- live task-8（8535264）：稳定帧验证、每牌尝试预算、stale choices、5+ 选兜底、ACTIVATE 多局样本；
- 最终门禁：engine 4816/6 skip、project 663/2 skip、verify_all 4/4、smoke 8/8、live 33 passed。

### 01:20 checkpoint（提前完成）

- 所有任务板任务 completed；无 in_progress；所有 bot 已停止。
- 最终门禁：engine 4816/6 skip、project 663/2 skip、verify_all 4/4、smoke 8/8、live 33。
- 最终报告：docs/8H_FINAL_REPORT.md；协议：docs/LIVE_AUTOMATION_PROTOCOL.md。
- 后续 07:00 提醒已删除；工作树干净（HEAD 7ca245f + 最终文档提交）。
