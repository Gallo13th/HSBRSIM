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
5. **门禁**：`hsrl2/tests` 4816 passed / 6 skipped；`tests` 663 passed / 2 skipped；`verify_all --fast` 4/4；smoke 8 局 crashes=0；live task-8 多局 no_effect 9/1767（4 次战斗过渡帧）。

### 关键指标

| 指标 | 结果 | 证据 |
|---|---|---|
| 自动进入游戏 | **PASS** | `runs/live/live_20261022_2328_bot37_fix/actions.jsonl` → `start_game_ok phase=hero_select` |
| 自动开下一局 | **PASS** | `live_20261022_2330_bot37_final`：23:44:09 game_over → 23:45:20 `start_game_ok attempts=6` |
| 英雄选择 | **PASS** | 点解锁英雄卡 → 确认 `(0.500,0.789)`；run3/run5 实机 |
| Freeze/HP/Dark Gift | **PASS** | run3 summary `exercised={freeze:1, hero_power:1, use_dark_gift:1}` |
| Activate live | **PASS**（39 点击≈19 成功） | `runs/live/LIVE_AUTOMATION_EVIDENCE_2.md`；0018/0029/0034 |
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
| cards | choose_one 36/36、10 base 抉择、6 英雄技能、11 DEFERRED | 4816 passed | `ed765c3` / `ENGINE_SUBSYSTEM_GAPS` |
| live | 自动进入/英雄选择/5 新动作/每动作截图 | 33 passed | `runs/live/LIVE_AUTOMATION_EVIDENCE_2.md` |

## 4. 未完成/阻塞

- 11 个英雄主技能保持未注册（缺子系统）：Nguyen/Raynor/Kerrigan/Murozond/Morchie/Akazamzarak/Silas/Tickatus/Cariel/Galewing/Putricide；见 `ENGINE_SUBSYSTEM_GAPS.md`。
- LIVE：ACTIVATE 已实机验证（39 点击≈19 成功）；choose-one+target 已实机成功；END_TURN 单人无按钮只能 auto_timer；launcher 自动拉起游戏未在“游戏关闭”状态实机复验（启动函数本机曾成功）。
- P1 已完成：PendingChoice 幂等/失败终态、grant_random_trinket 过滤、policy obs v3 迁移、env take_choice；EoT 选择仍只能 auto-resolve + 留痕（不可暂停，P2 状态机）。
- 旧 policy checkpoint 与 obs v3/MOVE_MINION 通过迁移兼容，但 MOVE_MINION 需继续训练。

## 5. 回归结果

```text
python -m pytest hsrl2/tests -q  -> 4816 passed, 6 skipped (32.5s)
python -m pytest tests -q        -> 663 passed, 2 skipped (87.2s)
python scripts/verify_all.py --fast -> 4/4 gates PASS (140.2s)
python tools/smoke_random_games.py --games 8 --seed 2000 -> 8/8, crashes=0
python -m pytest tests/test_live_clickbot.py -q -> 33 passed
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

## 8. P1 追加（00:00–01:00）

### 8.1 Engine P1（commit 09095da）

- `grant_random_trinket` 随机授予路径按 REGISTRY 过滤；测试 4 例。
- `PendingChoice` 一次性：重复 choose 抛 `GameStateError`；resolve 抛错进入 `failed` 终态；
  新增 `Game.take_choice()` 原子 API；测试 +12，`test_engine_choose_target` +4。
- 修复 test_engine_gaps 的 REGISTRY 删除污染。
- 门禁：hsrl2/tests 4816 passed / 6 skipped；tests 663 passed / 2 skipped；verify_all 4/4；smoke 8/8。

### 8.2 Policy P1（commit 8bf8c5a）

- encoder：action kind 动态 13、`entity_secondary`（Dark Gift gift_id/任务 reward_id）进编码；
- checkpoint format 2，旧 obs v2 默认迁移+警告，`allow_legacy=False` 严格报错；
- `docs/POLICY_OBS_V3.md` + 19 测试；PPO mock 64 步 smoke 通过；旧 BC/PPO ckpt 迁移权重断言通过。
- 影响：旧 checkpoint 不再静默错位；MOVE_MINION 需继续训练。

### 8.3 Live P1（完成）

- ACTIVATE 实机样本已抓到（`live_20261023_0018_games3`）；
- choose-one+target 首次实机成功（`live_20261023_0029_games3_fix`）；
- 自动下一局/英雄选择实机；每动作截图/失败诊断；
- task-8 三 run 完成：2 个完整 game_over + 2 个进行中局；live 测试 33 passed。

## 9. 最终门禁（2026-10-23 01:05）

| 命令 | 结果 | 耗时 |
|---|---|---|
| `python -m pytest hsrl2/tests -q` | **4816 passed, 6 skipped** | 32.5s |
| `python -m pytest tests -q` | **663 passed, 2 skipped** | 87.2s |
| `python scripts/verify_all.py --fast` | **4/4 gates PASS** | 140.2s |
| `python tools/smoke_random_games.py --games 8 --seed 2000` | **8/8, crashes=0** | — |
| `python -m pytest tests/test_live_clickbot.py -q` | 33 passed | 6.9s |
| `python -m pytest tests/test_policy_obs_v3.py -q` | 19 passed | 2.6s |
| `python -m pytest tests/test_env_choice_contract.py -q` | 15 passed | 0.5s |

### task-8 live 多局证据

- `runs/live/LIVE_AUTOMATION_EVIDENCE_2.md`；
- `0018_games3`：完整 game1 → 自动 game2 → 英雄选择；**ACTIVATE 首个样本**；
- `0029_games3_fix`：**choose-one+target 首次实机成功**（BG31_880 → choose_one → target board[0]）；
- `0034_games3_fix2`：完整 game1 → 自动 game2；freeze1/buy11/play_minion20/play_spell11/activate4/choose3/sell18/reroll6/dark_gift1；game2 5 选弹层未标定，人工终止；
- ACTIVATE：39 次点击约 19 次成功；freeze/DG 各 3 次成功；no_effect 合计 9 / 1767 行（4 次战斗过渡帧）；
- live 修复：稳定帧验证、每牌每回合最多 2 次拖拽、stale choices guard、5+ 选隐藏兜底、activate 优先级 95、手牌 6+ fan 间距。

### env P1（task-9）

- `Game.take_choice` 接入 driver/choice 全链路；owner/空队列/越界不消费；
- 结算回调失败 → failed 终态 + `info.choice_failed/resolution_error` + 刷新观测；
- EoT/淘汰/对手期 auto-resolve 失败全部留痕；暂停能力探测：EoT/淘汰/战斗不可暂停（同步方法），对手招募期 P2 设计债；
- 15 项新测试；ENV_SPEC v3.1。
