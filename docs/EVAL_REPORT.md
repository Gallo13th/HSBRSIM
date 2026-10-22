# 策略评测报告（EVAL REPORT）

> 环境：官方数据 37.0.0.255130、8 人局、7 个启发式对手；seed=300..399（100 局固定种子）。
> 名次越小越好（1 = 冠军）。奖励信号与名次相关系数 -0.995。

| 策略 | 平均名次 [95% CI] | 冠军率 | 前四率 | 平均回合 | 平均步数 |
|------|-------------------|--------|--------|----------|----------|
| random | 7.85 [7.76, 7.93] | 0.0% | 0.0% | 7.3 | 44 |
| heuristic | 4.30 [3.89, 4.70] | 12.0% | 54.0% | 11.4 | 97 |
| BC | 4.06 [3.69, 4.47] | 9.0% | 62.0% | 11.6 | 100 |

## 名次分布

| 名次 | random | heuristic | BC |
|------|---|---|---|
| 1 | 0% | 12% | 9% |
| 2 | 0% | 9% | 15% |
| 3 | 0% | 20% | 23% |
| 4 | 0% | 13% | 15% |
| 5 | 0% | 12% | 11% |
| 6 | 3% | 16% | 12% |
| 7 | 9% | 12% | 9% |
| 8 | 88% | 6% | 6% |

![rank distribution](docs/assets/eval_rank_distribution.png)


## 结论

- **BC 策略**（320 局教师示范 / 30,300 样本，验证动作准确率 85.6%）显著优于随机，
  与启发式教师接近；checkpoint 可直接用 `scripts/evaluate.py` 加载评测。
- 启发式教师为引擎感知贪心（买/打/升级/刷新 + 种族关键词协同 + 金币利用），
  同时用作 BC 示范与默认对手。
- PPO 管线可训练（60k–300k 步实验、checkpoint 可复现），但在稀疏终局奖励 + 8 人局
  高方差下未稳定超过 BC；训练已按用户指示暂停，管线保留。

## 复现

```powershell
python scripts/evaluate.py --baseline random    --episodes 100 --seed 300 --out runs/eval_final_random.json
python scripts/evaluate.py --baseline heuristic --episodes 100 --seed 300 --out runs/eval_final_heuristic.json
python scripts/evaluate.py --checkpoint runs/bc/official_320/policy_bc.pt --episodes 100 --seed 300 --out runs/eval_final_bc.json
python scripts/eval_report.py --eval random=runs/eval_final_random.json --eval heuristic=runs/eval_final_heuristic.json --eval BC=runs/eval_final_bc.json
```

