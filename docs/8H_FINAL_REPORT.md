# 8 小时自主工作报告（2026-10-22 23:07 → 2026-10-23 07:00）

> 本文由 Lead 汇总，证据链接均可复现。07:00 前的最终数字以本文件为准。

## 0. 执行摘要

8 小时内完成：

1. **真实自动进入游戏**：Battle.net 点击「进入游戏」→ Hearthstone → 主菜单/任务弹窗 → 酒馆战棋 → 开始 → 英雄选择 → 对局，全自动；**已实机跑通自动开第二局**。
2. **live 动作扩展**：FREEZE、HERO_POWER（含目标）、ACTIVATE（代码/单测）、USE_DARK_GIFT（三选一）、END_TURN（单人局记录 `auto_timer`，不谎报）；buy/play/refresh/upgrade/sell/target 全部实机。
3. **审计 + 协议**：完成 Live/Env/Engine 三层审计、gap 台账、审计协议、多智能体协作规则、8h 报告模板。
4. **P0 修复**：
   - env：`MOVE_MINION`、Dark Gift `gift_id` 观测、EoT 自动结算留痕；Observation.version=3。
   - engine：饰品 offer 按 REGISTRY 过滤、Choose One+目标两阶段、法术实体 `CHOOSE_BOTH`。
   - cards：Choose One 36/36 脚本、10 base 抉择卡、6 个 37.0 英雄主技能、11 个 DEFERRED 台账。
5. **门禁**：`hsrl2/tests` 4800 passed / 6 skipped；`tests` 622 passed / 2 skipped；`verify_all --fast` 4/4；smoke 8 局 crashes=0；live run5 `no_effect=0`。

### 关键指标

| 指标 | 结果 | 证据 |
|---|---|---|
| 自动进入游戏 | **PASS** | `runs/live/live_20261022_2328_bot37_fix/actions.jsonl` → `start_game_ok phase=hero_select` |
| 自动开下一局 | **PASS** | `live_20261022_2330_bot37_final`：23:44:09 game_over → 23:45:20 `start_game_ok attempts=6` |
| 英雄选择 | **PASS** | 点解锁英雄卡 → 确认 `(0.500,0.789)`；run3/run5 实机 |
| Freeze/HP/Dark Gift | **PASS** | run3 summary `exercised={freeze:1, hero_power:1, use_dark_gift:1}` |
| Activate live | 代码+单测，5 局无样本 | `tests/test_live_clickbot.py` |
| PowerShell 门禁 | 4/4 | `scripts/verify_all.py --fast` |

## 1. 实时自动化

### 1.1 启动链

| 步骤 | 实现 | 实测 |
|---|---|---|
| Battle.net 窗口定位 | `launcher.py` 按进程路径含 `battle.net` | ✅ hwnd 264196 |
| 点击「进入游戏」 | `(0.08,0.895)` | ✅ 窗口出现 |
| 每日任务弹窗 | ESC×2（任务→菜单→主菜单） | ✅ |
| 酒馆战棋入口 | `(0.50,0.378)` | ✅ |
| 开始 | `(0.759,0.778)` | ✅ |
| 英雄选择 | 解锁卡 x≈0.24/0.41/0.57/0.74, y=0.478 → 确认 `(0.500,0.789)` | ✅ run3/run5 |
| 自动下一局 | game_over → 继续 → 大厅 → 开始 | ✅ run3 |

### 1.2 live 动作校准

| 动作 | 坐标/方式 | 状态 |
|---|---|---|
| buy | drag shop→hand | ✅ |
| play | click hand → click board | ✅ |
| freeze | `(0.6375,0.133)` | ✅ frozen 翻转 |
| hero power | `(0.5875,0.767)` + 目标 | ✅ gold -1/powers 清空 |
| dark gift | `(0.8375,0.264)` → 三选一 | ✅ 手牌+1/赐福生效 |
| target 法术 | 拖拽优先/三段式 | ✅ 交互验证；run5 无样本 |
| end turn | 单人局无按钮 | ✅ `end_turn:auto_timer`（不谎报） |
| activate | 代码+单测 | ⚠ 无实机样本 |

### 1.3 采集/诊断

- 每动作截图：`screenshots/actions/`
- 同回合 2 次 no-effect → 5 帧 burst + state
- 每回合 `settled/turn_XX.json` + 截图
- 读内存子进程隔离，避免 `bgcontroller` access violation 带崩主进程
- run3：298 actions / 1 局；run5：`no_effect=0`

## 2. 审计与协议

- [LIVE_AUTOMATION_PROTOCOL.md](LIVE_AUTOMATION_PROTOCOL.md)（含协作章节合并）
- [AUDIT_PROTOCOL.md](AUDIT_PROTOCOL.md)
- [MULTI_AGENT_RULES.md](MULTI_AGENT_RULES.md)
- [AUDIT_LIVE_TO_SIM.md](AUDIT_LIVE_TO_SIM.md)
- [AUDIT_ENV_ACTIONS.md](AUDIT_ENV_ACTIONS.md)
- [AUDIT_ENGINE_MECHANICS.md](AUDIT_ENGINE_MECHANICS.md)
- [LIVE_TO_SIM_GAP.md](LIVE_TO_SIM_GAP.md)
- [AUDIT_CONSISTENCY.md](AUDIT_CONSISTENCY.md)
- [ENGINE_SUBSYSTEM_GAPS.md](ENGINE_SUBSYSTEM_GAPS.md)

多智能体协作：任务板 claim/complete CAS；写范围隔离；完成后四段消息；Lead 统一 commit/merge/最终报告；live 客户端只有一个操作者。

## 3. 已修复/已落地

| 层 | 改动 | 测试 | 证据 |
|---|---|---|---|
| env | move_minion、Dark Gift gift_id、EoT auto-resolve 留痕 | 24 新测试；tests 全绿 | `b4a12db` / `AUDIT_ENV_ACTIONS` §8 |
| engine | 饰品 REGISTRY 闸、choose+target 两阶段、法术 CHOOSE_BOTH | `test_engine_choose_target` 18；engine 全绿 | `7372b6f` / `ENGINE_NOTES` F-20 |
| cards | choose_one 36/36、10 base 抉择、6 英雄技能、11 DEFERRED | 4800 passed | `ed765c3` / `ENGINE_SUBSYSTEM_GAPS` |
| live | 自动进入/英雄选择/5 新动作/每动作截图 | 27 passed | `runs/live/live_20261022_2359_bot37_v3/` |

## 4. 未完成/阻塞

- 11 个英雄主技能保持未注册（缺子系统）：Nguyen/Raynor/Kerrigan/Murozond/Morchie/Akazamzarak/Silas/Tickatus/Cariel/Galewing/Putricide；见 `ENGINE_SUBSYSTEM_GAPS.md`。
- ACTIVATE 无实机样本；END_TURN 单人无按钮；choose-one+target 未 live 成功结算；launcher 自动拉起游戏未在“游戏关闭”状态实机复验（启动函数本机曾成功）。
- PendingChoice 幂等/回滚、EoT 选择可决策化、`grant_random_trinket` 随机授予过滤仍在 P1。
- 旧 policy checkpoint 与 obs v3/新增 MOVE_MINION 不兼容；需重训/迁移（policy 适配进行中）。

## 5. 回归结果

```text
python -m pytest hsrl2/tests -q  -> 4800 passed, 6 skipped (35.7s)
python -m pytest tests -q        -> 622 passed, 2 skipped (88.6s)
python scripts/verify_all.py --fast -> 4/4 gates PASS (134.9s)
python tools/smoke_random_games.py --games 8 --seed 2000 -> 8/8, crashes=0
python -m pytest tests/test_live_clickbot.py -q -> 27 passed
```

## 6. 风险与后续

- live 战斗/切回合内存状态滞后仍是主要 no-effect 来源；已用子进程读状态 + 脏帧过滤 + burst 截图缓解。
- 饰品 offer 过滤是“有脚本子集”，非官方权重；RNG 保持 seed 确定性。
- 英雄技能 11 个需子系统实现后再补，不能伪造。
- 下一步：P1 引擎健壮性、policy obs v3 适配、更多 live 多局样本（Activate/choose+target）、最终把所有 P0 gap 标 verified。

## 7. 证据清单

- 审计/协议：`docs/` 上述文件 + `docs/audit/choose_one_matrix.json`。
- 复现审计：`python scripts/audit_mechanism_coverage.py --out runs/audit/mechanism_coverage.json`
- live 证据：`runs/live/LIVE_AUTOMATION_EVIDENCE_20261022.md`、`runs/live/live_20261022_*`。
- 8h 日志：`docs/8H_WORK_LOG.md`；提交：`git log --oneline`。
