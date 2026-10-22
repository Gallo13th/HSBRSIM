# 训练手册（TRAINING）

本手册覆盖「从零到可评测策略」的完整流程：环境 → 教师示范 → BC → PPO → 评测。
所有命令在 `C:\HSagent` 下执行，Python 3.13，训练可用 CUDA（RTX 4060 Ti）。

## 0. 前置检查

```powershell
python -m pytest hsrl2/tests -q          # 引擎回归（4187 项，含官方数据迁移后新增）
python -m pytest tests -q                # 环境/策略/桥接测试
python tools/smoke_random_games.py --games 8 --seed 2000
python scripts/demo_env.py --seed 42     # 单局演示（启发式智能体）
```

数据基线：**官方 build 37.0.0.255130**（`data/bg_summary.json`，
池内随从 273 / 法术 76 / 卡 3817）。旧基线备份在 `data/backup_249896/`。

## 1. 环境与向量化

```python
from hsbg.env import BattlegroundsEnv
env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=42)
obs = env.reset(seed=42)
obs, reward, terminated, truncated, info = env.step(obs.candidates[0])
```

- 单局约 **300–500 ms**（8 人、13 回合、~100 步），单动作 3–5 ms；
- 8 人局吞吐：单进程约 **2–3 局/s**；4 进程约 **7 局/s**（数据收集/评测）；
- 向量化：`hsbg.env.vec_env.VecEnv`（多进程，Windows spawn，需 `__main__` 保护）
  或 `SyncVecEnv`（单进程多环境，接口等价）；
- 结果 `info` 含 `rank`（1..8）、`health`、`combat`、`terminated_reason`。

## 2. 教师示范数据（BC 数据集）

教师 = `hsbg.agents.heuristic.HeuristicPolicy`（引擎感知贪心：买/打/升级/刷新/
卖弱换强 + 种族/关键词协同 + 金币利用）。收集器逐动作记录
`(Observation, 候选下标)`，对局结束回填名次。

```powershell
python scripts/collect_bc.py --episodes 320 --workers 4 `
    --out runs/bc_data/heuristic_320_official.pkl
```

实测：320 局 / **30,300 样本** / 43 s（4 进程，7.4 局/s）；教师平均名次 **4.28**、胜率 13.1%。
产物 `BCDataset`（pickle）可直接被 `BCTrainer.fit` 消费。

## 3. BC 训练

```powershell
python scripts/train_bc_dataset.py --dataset runs/bc_data/heuristic_320_official.pkl `
    --epochs 30 --batch-size 512 --lr 3e-4 --device cuda --out runs/bc/official_320
```

实测（1.24M 参数实体 Transformer，GPU）：30 epoch 约 **30 s**；
train acc 0.984 / **val acc 0.856**（随机基线 0.115）。
产物：`policy_bc.pt`（自包含词表/配置）、`report.json`。

## 4. PPO 微调

```powershell
python scripts/train_ppo.py --total-steps 60000 --num-envs 4 --env real --device cuda `
    --init-from runs/bc/official_320/policy_bc.pt --out runs/ppo/official_bcinit_60k `
    --n-steps 256 --epochs 4 --minibatch-size 512 `
    --eval-every 20000 --eval-games 8 --save-every 20000
```

- PPO：GAE(λ=0.95)、clip=0.2、entropy=0.01、value_coef=0.5、名次分布 CE=0.5、
  target_kl=0.02；8 人局 + 7 个启发式对手；
- 实测吞吐：60k steps / **310 s（~194 steps/s）**；
- 训练中 eval（8 局）mean_rank：5.0 → 3.875 → 4.625（噪声大，最终以 100 局评测为准）；
- 产物：`policy_final.pt`、`train_log.csv`、`summary.json`、`eval_log.csv`。

## 5. 评测

```powershell
python scripts/evaluate.py --baseline random    --episodes 100 --seed 100
python scripts/evaluate.py --baseline heuristic --episodes 100 --seed 100
python scripts/evaluate.py --checkpoint runs/bc/official_320/policy_bc.pt `
    --episodes 100 --seed 100 --out runs/eval100_bc.json
python scripts/evaluate.py --checkpoint runs/ppo/official_bcinit_60k/policy_final.pt `
    --episodes 100 --seed 100 --out runs/eval100_ppo60k.json
```

固定种子集（同 seed 同轨迹），输出平均名次、95% bootstrap CI、冠军率、前四率、
名次分布、平均回合/步数、invalid/truncated 计数。

## 6. 结果表（官方数据 37.0.0）

> 由 100 局固定种子（seed=100..199）评测；名次越小越好。

| 策略 | 平均名次 | 冠军率 | 前四率 | 说明 |
|------|----------|--------|--------|------|
| random | **7.80** [7.69, 7.90] | 0% | 0% | 均匀随机候选 |
| heuristic（教师） | **4.24** [3.85, 4.63] | 8% | 52% | 引擎感知贪心 |
| BC（320 局 / 30k 样本） | **4.34** [3.94, 4.75] | 6% | 54% | 监督拟合教师 |
| PPO 60k（BC 初始化） | **4.72** [4.38, 5.07] | 4% | 44% | 早期版本，退化（熵坍缩） |
| PPO 200k（调参版） | 运行中 | — | — | 熵 0.03 / lr 1e-4 / 6 环境 |

*(100 局固定种子 seed=100..199；原始数据 `runs/eval100_*.json`。PPO 200k 完成后回填。)*

## 7. 复现性

- `hsbg.train.setup`/训练脚本固定 python/numpy/torch 种子；同 seed 训练日志逐行一致
  （仅耗时列不同）。
- 环境由 `seed` 完全决定；评测对同一 seed 集复现。
- checkpoint 自包含（模型配置、卡牌词表、编码维度），`load_policy_and_encoder`
  可直接加载推理。

## 8. 已知限制

- 官方 37.0.0 新增的 37 张池内随从**尚无效果脚本**（白板进池），会拉低模拟精度；
  差分 harness 显示 246/256 条分歧与缺脚本卡相关。补脚本是后续最大工作量。
- 战斗内核有 6 条已知行为分歧（圣盾+风怒第二击 / 复生双向反伤），修复进行中
  （见 `docs/DIFF_HARNESS.md`、`docs/REA_FINDINGS.md`）。
- 对手为脚本启发式（非自我对弈池）；PPO 仅 60k 步，尚未饱和。
