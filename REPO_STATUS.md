# 仓库状态 / 同步说明（2026-10-22）

远程仓库：`git@github.com:Gallo13th/HSBRSIM.git`  
本地 `master` 与 `origin/master` 已同步：`0ba0a25`（干净快照，无历史大文件）。

## 1. 目录与可用性

| 部分 | 位置 | 状态 |
|---|---|---|
| 模拟引擎（vendored hsrl2） | `hsrl2/` | 引擎测试全绿；规则修复见 `docs/ENGINE_NOTES.md` |
| 卡牌/版本数据 | `data/`、`hsdata/CardDefs.xml` | 官方 build 37.0.0.255130；`hsdata/CardDefs.xml` 约 82MB（GitHub 提示建议 LFS） |
| RL 环境层 | `hsbg/env/` | 观测 v2、候选动作、奖励、VecEnv、Gymnasium wrapper |
| 行为/搜索 | `hsbg/search/` | turn-search（单回合自枚举 + 状态间 pairwise）、PUCT/MCTS、决策矩阵、评分器；测试 18 项通过 |
| 阵容价值网络 | `hsbg/value/` | warband Transformer + pairwise Bradley-Terry；pilot 见下 |
| 桥接/真实日志 | `hsbg/bridge/` | Power.log 解析、匿名化、轨迹差分 |
| Live 自动化（实验） | `hsbg/live/` | 1600×900 点击/拖拽 bot（购买=拖 shop→hand、上阵=拖 hand→board） |
| 文档 | `docs/` | 环境契约、算法研究、价值网络、验证报告 |

## 2. 本轮验证结果

```powershell
python -m pytest hsrl2/tests tests -q -o addopts='' -p no:cacheprovider
# 5286 passed, 5 skipped, 14 subtests passed

python scripts/verify_all.py
# 7/7 gates passed (engine/project/smoke/env validation/env bench/official consistency/version)

python -m pytest tests/test_turn_search.py tests/test_search_mcts.py tests/test_search_decision.py tests/test_warband_value.py -q
# 18 passed
```

价值网络（fresh eval，3,000 阵容 / 11,996 对）：

```json
{"pair_acc": 0.9129, "spearman_warband_meanwin": 0.8073}
```

复现：
```powershell
python scripts/build_warband_pairs.py --warbands 3000 --opponents 4 --seeds 2 --seed 123 --out runs/warband_value/pairs_eval.npz
python scripts/eval_warband_value.py --data runs/warband_value/pairs_eval.npz --checkpoint runs/warband_value/model_60k/checkpoint.pt
```

## 3. 隐私/清理

- 已把 tracked 文件中的本机用户名路径替换为 `%USERPROFILE%` / `<user>`；
- 已删除：旧 BepInEx 二进制包、构建产物（bin/obj）、反编译源码/大体积反汇编、旧数据备份（`hsdata/backup_249896`，约 100MB）、临时 scratch 文件；
- `.gitignore` 覆盖 `runs/`、`*.npz`、`*.pkl`、`*.log`、checkpoint 等；
- 没有 tracked 文件包含 BattleTag / 账号 / 玩家名 / 本机用户名（已用 `git grep` 全仓扫描）；
- 远程只同步了当前干净快照（orphan commit），未推送本地历史中的旧大文件；旧远端历史保存在分支 `archive-remote-2026-10-22`。

## 4. 数据重建（hsdata 不入库）

官方 `hsdata/CardDefs.xml` 不再入库（约 82MB）；运行所需的 `data/bg_*.json` 已入库。
需要升级/重建数据时按 [docs/DATA_REBUILD.md](docs/DATA_REBUILD.md)：

```powershell
# 1) 下载 HearthSim/hsdata tag 255130 的 CardDefs.xml 到 hsdata/
# 2) 生成
python tools/generate_bg_data.py --dry-run
python tools/generate_bg_data.py
# 3) 或走一键流水线
python tools/version_sync.py --dry-run
python tools/version_sync.py --apply --yes
```

## 5. 演示

- 阵容级展示：`scripts/demo_warband_4search_vs_4bc.py`
  - 4 个 PUCT/search 阵容 vs 4 个 BC checkpoint 阵容；
  - 产物 `runs/demo_warband_4search_vs_4bc/{showcase.json,README.md}`；
  - 结果：quarter 3:1 search 胜，final search-0 胜。
- 全 8 座回合制对局：`scripts/demo_full_8seat.py`（`MultiSeatEnv` 子类，8 座位独立策略）
  - 4 个 **纯 PUCT-search** 座位（无启发式兜底）+ 4 个冻结 BC 座位；seed=42、14 回合、108 步、14.4s；
  - 产物 `runs/demo_full_puct_final/{episode.json,README.md}`，README 含**每回合 8 座位场面 + 最终名次**；
  - 结果：search 拿到第 1/2/3 名（P3 冠军、P0 亚军、P2 季军），BC 最好第 4。零 invalid / engine error。

## 6. Live 自动化

- 协议：[docs/LIVE_AUTOMATION_PROTOCOL.md](docs/LIVE_AUTOMATION_PROTOCOL.md)
- 差距表：[docs/LIVE_TO_SIM_GAP.md](docs/LIVE_TO_SIM_GAP.md)
- 审计：[docs/AUDIT_LIVE_TO_SIM.md](docs/AUDIT_LIVE_TO_SIM.md)
  - 环境层：[docs/AUDIT_ENV_ACTIONS.md](docs/AUDIT_ENV_ACTIONS.md)
  - 引擎/卡牌：[docs/AUDIT_ENGINE_MECHANICS.md](docs/AUDIT_ENGINE_MECHANICS.md)
- 动作 schema：[docs/schemas/live_action.schema.json](docs/schemas/live_action.schema.json)
- 采集：`python hsbg/live/click_bot.py --games 0 --max-seconds 0`
  - 每次 click/drag 后截图到 `runs/live/<run>/screenshots/actions/`
  - 同回合 2 次 no-effect → `diagnostics/` 5 帧 + state
  - 每回合 settled 截图/JSON；内存读取走子进程防崩
- live 证据（2026-10-24 清理前）：`runs/live/LIVE_AUTOMATION_EVIDENCE_2.md`（task-8 三 run 合并）：
  - 自动 game_over→下一局、英雄选择、ACTIVATE 19 次成功发动、freeze/DG 各 3 次、
    choose-one+target 成功、no_effect 9/1767（4 次战斗过渡帧）；
  - 单次 run 3 个完整 game_over 未达成（跨 run 2 完整 + 2 进行中）。
  - 说明：`runs/` 已于 2026-10-24 清理，证据需按 `docs/CLEANUP_20261024.md` 重新采集。
- 8h 审计/修复（2026-10-22 23:07 →）：
  - env：move_minion、Dark Gift gift_id 观测、take_choice/失败诊断（b4a12db/c9cb58d）；
  - engine：饰品 REGISTRY 闸、choose+target 两阶段、CHOOSE_BOTH、PendingChoice 一次性（7372b6f/09095da）；
  - cards：choose_one 36/36、10 base 抉择、6 英雄技能、11 DEFERRED（ed765c3）；
  - policy：obs v3/MOVE_MINION/旧 ckpt 迁移（8bf8c5a）；
  - live：自动进入/英雄选择/5 新动作/稳定帧/尝试预算/5选兜底（8535264）；
  - 回归：hsrl2/tests **4816 passed/6 skipped**；tests **663 passed/2 skipped**；
    verify_all --fast **4/4**；smoke 8 局 **crashes=0**；live 33 passed；policy 19 passed。
- 仍 open：5+ 选弹层布局标定（L04）、EoT 选择可决策化（L26/P2）、11 个英雄技能子系统、
  launcher 从“游戏关闭”状态自动拉起未实机复验。

## 7. 已知限制

- `runs/` 下的模型 checkpoint / 数据集 / 评测结果不入库，需要按上面命令重新生成；
- live 自动化仍是实验性、仅 1600×900 校准；5+ 选弹层、战斗期内存滞后仍需样本；
- 价值网络目前用随机阵容+随机 buff 训练，尚未对齐真实对局分布（见 `docs/WARBAND_VALUE_NETWORK.md`）。
- 原始 `hsdata/CardDefs.xml` 不入库，重建流程见 `docs/DATA_REBUILD.md`。
