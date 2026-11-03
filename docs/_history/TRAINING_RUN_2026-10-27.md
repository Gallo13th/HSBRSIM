# 1h PPO 试训结果（2026-10-27）

> 目标：按当前流程（不完全信息 MCTS + 自对弈 + PPO）跑 1h，先看有没有明显改进。
> 引擎/数据：`hsbg_engine` 1.0.0 / **37.0.0.255790**；网络：tiny MLP 0.96M。
> 代码：`scripts/train_az_ppo_loop.py` + `scripts/train_az_ppo.py` + `hsbg/az/train/ppo.py`。

## 1. 运行配置

```bash
python scripts/train_az_ppo_loop.py \
  --minutes 48 --games 8 --epochs 2 --arch tiny --device cuda \
  --sims 4 --determinizations 1 --opponent self --behavior net \
  --lr 1e-4 --clip 0.2 --minibatch 256 --target-kl 0.02 \
  --pi-coef 0.1 --entropy-coef 0.005 \
  --eval-every 10 --eval-games 16 --final-games 16 --seed 12000 \
  --out runs/az_ppo_1h_tiny_self
```

说明：
- 自对弈 8 局/轮，MCTS sims=4、W=1；网络行为采样（on-policy PPO）。
- 每轮约 80–270s（随对局变长而变慢），共 **20 轮**。
- 训练 wall-clock **3168s ≈ 52.8min**；最终逐 seat 评测后总 **3222s ≈ 53.7min**。
- 实际 **502,826 decisions**（`meta.decisions` 全座累计），≈ **157 decisions/s**；
  按此速率 1M decisions 约需 **106min**，1h 只完成约一半预算。

## 2. 评测协议

- 初始模型（未训练 tiny）与最终模型，均：
  - **8 个 seat 轮换**，每 seat 16 局，共 **128 局**；
  - 同 seed 集 `90000..90015`（同一 seat/seed 对比）；
  - seat0=被评策略，其余 7 座引擎 bot；greedy（search-off）。
- 基线：random 与 engine bot 各 16 局（seat0）。
- 指标：mean rank（越小越好）、top4、win、legal、逐局 rank。
- 配对 bootstrap 5000 次（按局重采样）。

## 3. 结果

| 策略 | 局数 | mean rank | top4 | win | legal | 说明 |
|---|---:|---:|---:|---:|---:|---|
| random vs bot | 16 | 8.000 | 0.0% | 0.0% | 100% | 基线 |
| engine bot vs bot | 16 | 4.8125 | 43.75% | — | 100% | 强参照 |
| **initial tiny**（未训练） | 128 | **7.9766** | 0.0% | 0.0% | 100% | 初始 |
| **final tiny**（53.7min） | 128 | **7.6328** | **0.78%** | 0.0% | 100% | 同 seed/seat |
| final（loop seed 91000） | 128 | 7.5625 | — | — | 100% | 不同 seed，仅参考 |

**配对差（final − initial）**：
- 平均名次差 **−0.3438**；95% bootstrap CI **[-0.4609, -0.2266]**。
- top4：0% → **0.78%**；胜场 0。
- 结论：**有统计上可检测的改进，但幅度很小**（0.34 名），远未达到“明显变强”；
  对 bot 仍是稳定第 8，top4 几乎为 0。

## 4. 诊断

- **对 bot 全 rank8**：bot 作为固定强对手，1h tiny + 稀疏终局奖励不足以学会击败它；
  selfplay 的 rank 信号（rank_mean≈3.7）与“对 bot 名次”不是同一分布。
- **吞吐不足**：随策略变强，单局决策数从 ~1.8k 增到 ~5k，单轮从 80s 增到 270s；
  1h 只完成 ~0.5M decisions，距 1M 目标约 2×。
- **PPO 更新被 KL 早停压住**：target_kl=0.02 时多数轮只更新 3–12 个 minibatch；
  价值预测接近 rank8，policy loss 很小；不是“跑满 2 epochs”。
- **search-on 未改善**：最终模型 20 局 `net` vs `search_az`（sims=8/W=2）
  均 mean rank 8.0；当前 MCTS 不是强度增益来源。
- **强制 EndTurn**：每轮 8–1000 次（随 policy 变强而增），已从 policy/aux loss 排除，
  但会缩短回合、影响数据分布。

## 5. 判断

**有改进，但不算“明显改进”**：
- 统计显著（CI 不含 0），但平均名次只从 7.98 降到 7.63；
- top4 0.78%、0 胜，离可用智能体很远；
- 1h 预算不足以跑完 1M decisions；当前瓶颈是数据量/对手信号，不是模型容量。

## 6. 下一步（按优先级）

1. **更多数据**：至少 1M decisions（约 2h 当前吞吐）；或先用 sims=0/更小 games 提高吞吐。
2. **对手课程**：bot 全 rank8 无信号，需要 random/弱 checkpoint/历史池产生可学习胜负；
   真实对局 library 暂无（bridge 已删）。
3. **KL anchor + 更强 critic**：当前 rank CE 与 GAE 目标需校准；加入 scalar utility/更稳 target。
4. **批量叶评估**：把当前 ~157 decisions/s 提升到可支撑 1M/iter 的量级。
5. **模型**：tiny 只适合 smoke；entity 14.8M 需在吞吐/质量上先做 ablation。

## 7. 产物

- `runs/az_ppo_1h_tiny_self/current/model.pt`（最终 checkpoint）
- `runs/az_ppo_1h_tiny_self/history.json`、`summary.json`
- `runs/az_ppo_1h_tiny_self/eval_initial/`、`eval_final_same/`、`eval_search_20.json`
- 训练日志：`runs/az_ppo_1h_tiny_self/train.log`

> `runs/` 被 gitignore，不入库；以上数字来自本次运行报告。
