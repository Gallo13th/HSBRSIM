# 小模型专家课程（SmallExpertCurriculum）：宽经济 → 硬限制 → 加对手

> 状态：实现 + 单测 + 三阶段实跑（结果见 §5）。代码
> `hsbg/az/train/small_expert.py`、沙盒奖励/动作上限课程在
> `hsbg/az/train/economy_sandbox.py` + `scripts/train_economy_sandbox.py`，
> 完整游戏 `scripts/train_entity_sync.py` 新增 `--shaping-mode log_strength`、
> `--rank-utility-coef`、`--terminal-strength-coef`。

## 0. 结论摘要

（待三阶段跑完后填写。）

## 1. 动机与设计

目标：训练一个 **≤5M** 的小 entity（`--d-model 256 --n-layers 4`，**3.57M**，
与 s14/s17 **同一套观测/动作/value 头**，checkpoint 可回完整游戏；实测沙盒
~4k 决策/秒），按「先让场面达到真实强度，再逐步加硬限制，最后当专家」的顺序：

| 阶段 | 环境 | 约束 | 奖励 | 判据 |
|---|---|---|---|---|
| **S1 无约束缩放** | 纯经济沙盒（无对手/无战斗） | gold=99，cap=120 | `L(Σ12) + 0.5·L(Σ15)` | t12 Σ ≥ 1200 |
| **S2 两维硬限制** | 沙盒 | gold 99→30→15→10，cap 120→40→20→10 | 同上 | 每档 t12 掉幅 <10% 才进档 |
| **S3 加对手** | 完整游戏 | 1→3→5 席人类战团（p=0.3/0.7/0.9） | `0.7·L(Σ_T) + 0.3·u(rank)` | 报告 t12/t15、载体率、对载体施法、tier |

预算：`--max-total-decisions`（默认 8M，按沙盒/完整游戏 PPO 实际决策数 + BC 采样
累计）。本机 cuda:7 与其他实验共享，实际预算见 §5（**未用满 8M**，按吞吐截断）。

### 1.1 S1/S2 的奖励：`t12_t15`

任务要求 `log1p(t12 Σ) + 0.5·log1p(t15 Σ)`。实现用**归一化 L 口径**
（`L(Σ)=log1p(Σ)/log1p(30000)`，与 value 头 tanh / 推理期叶值同一曲线），
最优策略不变；逐回合密集分解（精确望远镜）：

```
t ≤ 12:  r_t = 1.5·(L_t − L_{t−1})
t > 12:  r_t = 0.5·(L_t − L_{t−1})
Σ_t r_t = 1.0·L(Σ12) + 0.5·L(Σ15)
```

单测 `tests/test_small_expert.py::test_t12_t15_reward_telescopes` 锁住该等式（1e-9）。

### 1.2 S2 的两维课程与「掉幅 <10%」门控

- 金币档位由 `--sandbox-gold-ramp` 控制（既有）；
- **每回合动作上限**新增 `--sandbox-action-cap-ramp "0:120,2M:40,..."`：切档时**重建**
  `VectorEconomySandbox`（引擎 `RulesConfig.turn_action_caps` 固定，不能热改），
  已完成轨迹保留、在飞轨迹丢弃并记日志；
- 驱动 `SmallExpertCurriculum._run_s2` 在**每个档位的起点**先用新约束评测一次
  （entry），再按 `--s2-chunk` 训练并评测；`drop = 1 − t12/上一档 t12`，
  `drop ≤ 10%` 才算 `gate_pass` 并进下一档，否则继续训练到 `--s2-max-steps`。
  预算耗尽仍未达标时 `gate_pass=False` 后继续（如实记录，不伪造）。

### 1.3 S3 的 0.7 强度 + 0.3 名次

- **名次**：`--rank-utility-coef 0.3`，终局奖励 `0.3·u(rank)`（`u∈[-1,1]`，
  `u(1)=1`、`u(8)=-1`）；
- **强度**：`--terminal-strength-coef 0.7`，末步额外加
  `0.7·L(Σ_末决策)`（从标准观测 board 块解码，与沙盒同一口径）；
- **信用分配**：另开 `--shaping-coef 0.7 --shaping-mode log_strength`（势函数
  `Φ=L(Σ)`，γ=训练 γ）。势函数塑形整局望远镜和是常数（`-Φ(start)`），**不改变**
  上两条目标奖励，只把终局强度信号摊到每个决策，缓解稀疏信用。

## 2. 接口

```bash
python -m hsbg.az.train.small_expert \
  --out runs/small_expert/main --device cuda:7 \
  --init-checkpoint runs/economy_sandbox/sb_small/model.pt \
  --s1-steps 250000 --s2-chunk 200000 --s2-max-steps 200000 \
  --s3-games 24 --s3-processes 4 --s3-threads 4 \
  --eval-games 64 --quality-games 48
```

产物：`runs/small_expert/main/curriculum.jsonl`（逐档一行）、`summary.json`、
`eval_all.json`（单 checkpoint 全约束扫）、每个子段的 `train.log`。

## 3. 单测（`tests/test_small_expert.py`）

1. `t12_t15` 奖励整局和 = `L12 + 0.5·L15`；
2. 动作上限 ramp 的解析/取值 + `engine_config.turn_action_caps` 真的随档位变；
3. S2 门控：掉幅 >10% 继续、≤10% 才 `gate_pass`；预算超限拒绝训练；
4. 终局强度项：`build_batch_from_arrays` 末步奖励 = `0.3·u(rank) + 0.7·L(Σ)`。

## 4. 复现

```bash
bash runs/small_expert/launch.sh
# 或单点全约束扫：
python -m hsbg.az.train.small_expert --out runs/small_expert/main \
    --eval-only runs/small_expert/main/model.pt
```

## 5. 结果

（待填。）

## 6. 结论

（待填。）
