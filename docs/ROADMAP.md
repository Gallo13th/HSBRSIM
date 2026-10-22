# 路线图与验收（ROADMAP）

> 状态图例：✅ 完成 / 🚧 进行中 / ⏳ 待启动

## M0 引擎移植与校验 ✅

- [x] 从 WSL `/home/glt/HrSRL` 移植 `hsrl2`（v2 引擎，413 个 Python 文件）
- [x] Windows + Python 3.13 下全量回归：**4,164 passed**（初始基线）
- [x] 8 人随机全对局压测、引擎契约测试（回合/淘汰/名次/确定性/PendingChoice）
- [x] 修复 F-01：战斗快照 deepcopy 实体引用（整局 7.2× → 正常、内存 98× 回落）

**验收**：`pytest hsrl2/tests`；`tools/smoke_random_games.py --games 8`

## M0.5 官方一致性 ✅（持续维护）

- [x] 官方数据获取：build **255130 / 37.0.0**（`CardDefs.Bacon.xml` 5,787 BG 实体，sha256 锁定）
- [x] 数据迁移：BG +175、新卡 +179/-4、384 数值变化、新种族 ABERRATION(126)
- [x] 数据迁移后全量回归 **4,187 passed**（含 11 条 ABERRATION 专项）
- [x] 客户端逆向（REA + ilspycmd）：无官方战斗模拟器（服务器权威）；GameTag/枚举差异报告
- [x] 官方轨迹差分：679 场真实 BG 战斗；DATA_GAP=0，确定性匹配 76.9%，干净子集 100%
- [x] 修复 F-02：Ozumat SoC 召唤 6-7 只 → 1 只（官方轨迹由 diverged 转 MATCH）
- [x] REA/BobsBuddy 战斗算法逐条对照（`docs/REA_FINDINGS.md`）
- [x] 版本同步一键流水线（`tools/version_sync.py`，四信号检测/预演/应用/回滚）

**验收**：`python tools/diff_replay_combat.py --traces runs/official_traces --limit 10`

## M1 环境契约 ✅

- [x] `hsbg/env/spec.py` + `docs/ENV_SPEC.md`（观测/动作/奖励/step 顺序/POMDP 边界）

## M2 RL 环境实现 ✅

- [x] driver（合法动作枚举/应用/PendingChoice）、observation（实体 token）、game_env、vec_env
- [x] 随机/启发式对手与教师；freeze/no-op 三层防护
- [x] 确定性、20 seeds 0 崩、单局 ~0.3–0.5 s、4 进程 7 局/s
- [x] `scripts/demo_env.py`、`scripts/bench_env.py`

**验收**：`pytest tests`；`scripts/bench_env.py --seeds 20`

## M3 策略与训练实现 ✅

- [x] 编码器（39 实体槽 / 64 候选 / 8 名次分布）+ 1.24M 参数实体 Transformer
- [x] BC：30,300 教师样本，验证准确率 85.6%（随机 11.5%）
- [x] PPO：GAE + clip + KL 早停 + checkpoint；真环境 60k/120k/200k/300k 步实验
- [x] `scripts/collect_bc.py` / `train_bc_dataset.py` / `train_ppo.py` / `evaluate.py`

**验收**：`pytest tests`；训练脚本短跑通过、checkpoint 可加载复现

## M4 端到端集成 ✅

- [x] 真环境 + 策略 + PPO 冒烟（60k 步 310 s）
- [x] BC 100 局评测：**4.34** 平均名次（random 7.80 / 教师 4.24）
- [x] 评测固定种子集 + bootstrap CI + 名次分布

## M5 训练与结果 ⏸（用户指示暂停训练，管线已就绪）

- [x] BC 显著优于随机（4.34 vs 7.80），接近教师
- [x] PPO 管线可训练、可复现（60k/120k/200k/300k 步实验）
- [x] BC 策略 4.34 平均名次；PPO 稀疏奖励下未稳定超过 BC（暂停训练后保留管线）
- [ ] PPO 稳定超过 BC（当前稀疏终局奖励 + 高方差下未达成；需要更长训练/课程学习/自对弈）
- [ ] 更大规模 BC（1000+ 局）与搜索教师蒸馏

## M6 真实对局桥 ✅

- [x] AgenticAssistant 能力边界核实（无本地模拟器/无自动点击；内存只读 + Power.log）
- [x] Power.log 解析器、HDT BobsBuddy 轨迹抽取（679 场）、rizling 版本跟踪
- [x] 数据差异量化与版本同步流水线

## M7 文档与交付 ✅

- [x] README、ARCHITECTURE、ENV_SPEC、ENGINE_API、ENGINE_RL_READINESS、
      TRAINING、OFFICIAL_EXACTNESS、DIFF_HARNESS、REA_FINDINGS、VERSION_SYNC、
      REAL_GAME_BRIDGE、ENGINE_NOTES、AGENTS
- [x] 全部测试 + demo + 基准 + 评测可一键复现

## 后续（按优先级）

1. **补 37.x 缺失效果脚本**（37 张池内随从 + 94 条非池；差分分歧主因）
2. **PPO 提升**：课程学习（2/4/8 人）、更长训练、自对弈对手池、BC 辅助损失
3. **动态 `SCRIPT_DATA_NUM_1..5`** 建模（官方 tag 与引擎内部 tag 撞号的根治）
4. **真实 BG Power.log 采集**（用户可提供一局开启日志的对战）→ 事件级差分
5. 大规模数据搜集（高并发 rollout + 真实轨迹混合训练）
