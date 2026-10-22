# HSbg Agent — 炉石传说·酒馆战棋智能体

把「酒馆战棋」做成**可训练、可评估、可复现**的强化学习智能体项目。

```
模拟引擎 (hsrl2)  →  RL 环境 (hsbg.env)  →  策略与训练 (hsbg.policy / hsbg.train)
```

数据基线：**官方 build 37.0.0.255130**（2026-10 补丁，池内随从 273）。
引擎回归 + 项目测试合计 **5,104 passed**（持续增长）；一键门禁 `python scripts/verify_all.py`（7/7，~3 分钟）。

## 组成与状态

| 层 | 目录 | 状态 |
|----|------|------|
| 战局模拟引擎 | `hsrl2/` | ✅ 移植自旧版 v2 引擎 + 官方 37.0.0 数据迁移；机制精度权威 |
| RL 环境 | `hsbg/env/` | ✅ 单智能体 8 人对局、实体 token 观测、候选动作、奖励、确定性、多进程向量化 |
| RL 接口层 | `hsbg/rl/` | ✅ Policy/EnvLike 协议、Gymnasium 包装（`check_env` 通过）、JSONL 采集器（4 进程 7.4 局/s）、多进程评测 |
| 智能体与教师 | `hsbg/agents/` | ✅ 随机 / 启发式（引擎感知贪心） |
| 策略网络 | `hsbg/policy/` | ✅ 实体 Transformer（候选打分 + 名次分布价值），1.24M 参数 |
| 训练管线 | `hsbg/train/` | ✅ BC（行为克隆）+ PPO（GAE/clip/KL 早停）+ 数据收集 |
| 评测 | `hsbg/eval/` | ✅ 固定种子集、bootstrap CI、名次分布、基线对比 |
| 真实对局桥 | `hsbg/bridge/` | ✅ Power.log 解析、HDT/BobsBuddy 轨迹抽取、rizling 版本跟踪 |
| 官方一致性工具 | `tools/` | ✅ 官方数据抓取/差分、客户端程序集分析、差分 harness、版本同步流水线 |

## 快速开始

```powershell
cd C:\HSagent

# 1) 引擎回归（约 50s）
python -m pytest hsrl2/tests -q

# 2) 项目测试（环境/策略/桥接）
python -m pytest tests -q

# 3) 跑一局 8 人对局（启发式智能体，打印每回合状态）
python scripts/demo_env.py --seed 42

# 3b) RL 接口：数据采集 / 评测 / Gym 包装
python -m hsbg.rl.collector --policy heuristic --envs 4 --episodes 100 --out runs/rl/heuristic_100.jsonl
python -m hsbg.rl.evaluate --policy random --episodes 20
python -c "from hsbg.rl.gym_wrapper import make_gym_env; env=make_gym_env(); print(env.observation_space, env.action_space)"

# 3c) 环境验收 / 全量门禁
python scripts/validate_env.py --games 30 --json runs/env_validation.json
python scripts/verify_all.py --fast

# 4) 环境基准（吞吐/耗时/崩溃）
python scripts/bench_env.py --seeds 20

# 5) 收集教师示范 → BC → 评测（CPU 即可，GPU 更快）
python scripts/collect_bc.py --episodes 320 --workers 4 --out runs/bc_data/heuristic_320_official.pkl
python scripts/train_bc_dataset.py --dataset runs/bc_data/heuristic_320_official.pkl `
    --epochs 30 --device cuda --out runs/bc/official_320
python scripts/evaluate.py --checkpoint runs/bc/official_320/policy_bc.pt --episodes 100 --seed 100

# 6) PPO 微调（需要 CUDA，约 8~20 分钟）
python scripts/train_ppo.py --total-steps 120000 --num-envs 6 --env real --device cuda `
    --init-from runs/bc/official_320/policy_bc.pt --out runs/ppo/official

# 7) 版本同步（游戏补丁后）
python tools/version_sync.py --check          # 四信号检测
python tools/version_sync.py --dry-run        # 取数/生成/差分（不覆盖 data/）
python tools/version_sync.py --apply --yes    # 备份→应用→回归（失败自动回滚）

# 8) 官方一致性差分（679 场真实 BG 战斗）
python tools/diff_extract_replays.py --limit 5
python tools/diff_replay_combat.py --traces runs/official_traces --limit 10
```

## 评测结果（100 局固定种子，8 人局，名次越小越好）

| 策略 | 平均名次 | 冠军率 | 前四率 |
|------|----------|--------|--------|
| 均匀随机 | 7.85 | 0% | 0% |
| 启发式教师 | 4.30 | 12% | 54% |
| **BC 策略（本仓库训练）** | **4.06** | 9% | 62% |
| PPO 微调 | 稀疏奖励下未稳定超过 BC（训练暂停） | — | — |

BC：320 局教师示范 / 30,300 样本；验证集动作准确率 **85.6%**（随机基线 11.5%）。
环境：单局约 **0.3–0.5 s**、~100 步、3–5 ms/步；单进程 2–3 局/s，4 进程 7 局/s。

## 设计要点

- **引擎是机制精度的唯一权威**：卡牌数值来自官方 CardDefs（build 255130）；效果由
  `hsrl2/scripts` 注册；环境层不重新实现规则。
- **实体中心观测**：棋盘/手牌/酒馆等按槽位序列化为实体 token；策略用 Transformer
  建模实体间关系（39 实体槽、候选动作 ≤64、8 名次分布价值头）。
- **候选动作打分**：不固定动作空间；每步枚举合法动作（含目标组合），策略对候选
  打分并做 masked argmax，天然支持动态棋盘与发现三选一。
- **确定性**：环境完全由 seed 决定；同 seed 轨迹逐位一致，训练可复现。
- **防死循环**：每回合动作预算（40）、freeze 单向、无进展保护。

## 官方一致性（本项目的核心要求）

| 工作 | 结果 |
|------|------|
| 官方数据 | 迁移到 build **255130**（37.0.0）：BG 实体 +175、新卡 +179、384 处数值变化、新种族 ABERRATION(126) |
| 引擎回归 | 数据迁移后 **4,175 → 4,187 passed**；补卡后引擎 4,588+ 项 + 项目 403+ 项（当前合计 **5,104 passed**（持续增长）） |
| 官方轨迹差分 | 679 场真实 BG 战斗：DATA_GAP=0，strict MATCH **72.3%**，确定性 **86.3%**（tolerant 94.4%），干净子集 **100%（33/33）**，behavior_mismatch=0；**真实 Power.log 事件级 26 场战斗 behavior_mismatch=0**（3 局：6+10+10，HDT 同局交叉 B/C 各 10/10，伤害上限 5/10/15 三档确认；C round6 经 F-14 修复）；有 CI 门禁 `scripts/audit_official_consistency.py` |
| 已修引擎 bug | 战斗快照 deepcopy 实体（性能 7×/内存 98×）、Ozumat SoC 召唤 6-7 只 Tentacle（官方 1 只） |
| 客户端逆向 | REA（rea-agents 6.7）+ ilspycmd：无官方战斗模拟器（服务器权威）；官方 GameTag 1214 项 vs 引擎 126 项差异报告；BobsBuddy 战斗算法逐条对照 |
| 已知缺口 | 37 张 37.x 新池随从无效果脚本（差分分歧主因）；4 个 DEFERRED Dark Gift；动态 SCRIPT_DATA_NUM tag 撞号待建模 |

详见 `docs/OFFICIAL_EXACTNESS.md`、`docs/DIFF_HARNESS.md`、`docs/REA_FINDINGS.md`、
`docs/VERSION_SYNC.md`。

## 文档

- `docs/ARCHITECTURE.md` — 分层架构与数据流
- `docs/ENV_SPEC.md` — 环境接口契约（观测/动作/奖励/step 顺序）
- `docs/ENGINE_API.md` — 引擎 API 速查
- `docs/ENGINE_RL_READINESS.md` — 引擎对 RL 的适配性评估（基准 + 缺陷清单）
- `docs/TRAINING.md` — 训练手册、超参、结果
- `docs/OFFICIAL_EXACTNESS.md` — 官方一致性技术路线（数据/行为/官方实现可行性）
- `docs/DIFF_HARNESS.md` — 官方轨迹差分方法与统计
- `docs/REA_FINDINGS.md` — REA/客户端/BobsBuddy 逆向结论
- `docs/VERSION_SYNC.md` — 版本跟踪与一键同步流水线
- `docs/ENV_VALIDATION.md` — 环境验收报告（确定性/多人数/选择步/奖励/性能/采集吞吐）
- `docs/EXACTNESS_STATUS.md` — 官方一致性状态快照（数据/脚本覆盖/差分/缺口/下一步）
- `docs/VERIFICATION.md` — 验收快照（每条命令的预期输出形态，交付/CI 对照）
- `docs/EVAL_REPORT.md` — 策略评测报告（100 局固定种子 + 名次分布图）
- `docs/RL_INTERFACE.md` — RL 接口层（Policy/EnvLike 协议、Gym 包装、JSONL 采集器、并发与确定性）
- `docs/REAL_GAME_BRIDGE.md` — 真实对局数据桥（Power.log / AgenticAssistant）
- `docs/LIVE_AUTOMATION_PROTOCOL.md` — 实时自动化/截图/采集/热修/协作协议
- `docs/LIVE_TO_SIM_GAP.md` — Live 操作 → 模拟器补全差距表
- `docs/schemas/live_action.schema.json` — 动作日志 JSON Schema
- `docs/ENGINE_NOTES.md` — 引擎修改记录（F-01…F-05）
- `AGENTS.md` — 协作与验收约定

## 目录

```
hsrl2/          模拟引擎（vendored；卡牌脚本在 scripts/batches/）
data/           官方 37.0.0 数据（backup_249896/ 为旧基线备份）
hsbg/env/       RL 环境（spec/driver/observation/game_env/vec_env）
hsbg/rl/        RL 接口层（api/policies/envs/gym_wrapper/collector/evaluate）
hsbg/agents/    对手与教师
hsbg/policy/    编码器 + 实体 Transformer + checkpoint
hsbg/train/     BC / PPO / buffer / vec env / 评测
hsbg/eval/      指标与评测运行器
hsbg/bridge/    Power.log / HDT 轨迹 / rizling 版本
tools/          数据生成/审计、官方数据抓取、差分 harness、版本同步
tests/          环境/策略/引擎契约/桥接测试
scripts/        demo/collect/train/evaluate 入口
reversed/       逆向分析产物（官方 XML/枚举/REA/BobsBuddy）
tmp_*/          隔离工作区（数据迁移/修复演练，可删）
```

## 运行环境

Windows 11，Python 3.13（`numpy`、`torch 2.9 + CUDA`、`pytest`）；
RTX 4060 Ti 16GB；训练与评测均可在 CUDA 或 CPU 上运行。
