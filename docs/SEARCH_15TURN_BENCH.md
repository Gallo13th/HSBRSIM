# 15 回合搜索宽度/深度/跨回合预期基准

## 1. 目标与边界

- **只做单英雄、单座招募模拟**：`Game([Hero])` 从 turn 1 到 turn 15，手动推进 `_begin_recruit_for`；
  **不跑 8 人对局、不跑战斗、不跑淘汰**。每回合只执行招募动作，终局阵容为第 15 回合招募结束后的棋盘。
- 搜索动作来自 `EngineForwardModel`（driver 候选），按 `width` 做 beam 截断、按 `depth` 做动作 ply
  递归；leaf 用 warband value network 评分。
- `horizon` 为跨回合预期：leaf 后手动进入下 N 个回合，用 heuristic 做 **2 个动作** 再评分
  （廉价代理；不是完整 future rollout）。

## 2. 搜索变量

| 变量 | 取值 | 含义 |
|---|---|---|
| `width` | 1, 2 | 每层保留的 top-W 动作（beam width） |
| `depth` | 1, 2 | 动作 ply 深度；depth=2 会先看一步后续动作 |
| `horizon` | 0, 1 | 跨回合预期：0=只看本回合 leaf；1=leaf 后进入下一回合并走 2 个 heuristic 动作 |
| seeds | 1,2,3 | 引擎随机种子（商店/发现/战斗公共随机） |
| turns | 15 | 固定 15 回合 |

## 3. 终局强度评估

1. **value 网分数**：`runs/warband_value/model_60k/checkpoint.pt`，输入终局 7 个随从的
   card/atk/hp/tier/keywords；越高越强（不同 seed 间有系统方差）。
2. **引擎 pairwise 战斗**：所有 **唯一终局阵容** 两两用 `simulate_combat_warbands` 打 9 个 seed，
   每个阵容对其它唯一阵容的平均胜率；避免相同阵容重复行互相“刷分”。
3. 同时记录 final board stats、tier、搜索耗时。

## 4. 结果（5 seeds/config，单座 15 回合）

数据：[`15turn_results_5seed.json`](search_bench/15turn_results_5seed.json)  
分析：[`15turn_analysis_5seed.md`](search_bench/15turn_analysis_5seed.md)

| config | n | value mean±sd | Δ vs baseline [95% CI] | pairwise winrate | stats | tier | s/run |
|---|---:|---:|---:|---:|---:|---:|---:|
| w1_d1_h0（baseline） | 5 | 7.05±4.95 | +0.00 | 0.516 | 107 | 6.0 | 34.3 |
| w1_d1_h1 | 5 | 7.05±4.95 | +0.00 [0,0] | 0.516 | 107 | 6.0 | 36.7 |
| w1_d2_h0 | 5 | 7.05±4.95 | +0.00 [0,0] | 0.516 | 107 | 6.0 | 66.5 |
| w1_d2_h1 | 5 | 7.05±4.95 | +0.00 [0,0] | 0.516 | 107 | 6.0 | 68.6 |
| w2_d1_h0 | 5 | 7.05±4.95 | +0.00 [0,0] | 0.516 | 107 | 6.0 | 36.9 |
| w2_d1_h1 | 5 | 6.26±5.26 | -0.79 [-6.81,+5.24] | 0.488 | 114 | 6.0 | 41.9 |
| w2_d2_h0 | 5 | 7.72±3.02 | +0.67 [-5.78,+7.12] | 0.556 | 104 | 5.2 | 112.1 |
| w2_d2_h1 | 5 | 5.71±4.86 | -1.33 [-6.73,+4.06] | 0.441 | 88 | 6.0 | 115.8 |

### 关键观察

1. **width=1 时 depth/horizon 完全不改变结果**：所有 w1 配置的 5 个 seed/board 都相同；
   只增加搜索耗时（34.3s → 68.6s）。原因是 beam=1 时 root 只保留立即 value 最高的动作，
   后续递归/horizon 无法改变第一步，最终沿同一轨迹。
2. **width=2 且 depth=1/horizon=0 与 baseline 相同**：探索第二名动作没有改变最终阵容；
   耗时 36.9s（几乎与 baseline 同）。
3. **w2+d1+h1 与 w2+d2+h1 平均略差**：value -0.79/-1.33，pairwise 0.488/0.441；
   宽+跨回合代理倾向牺牲经济/节奏，稳定性没有提升。
4. **w2+d2+h0（无跨回合）是唯一均值略高的配置**：value +0.67，pairwise 0.556，
   但 tier 从 6.0 降到 5.2、stats 107→104，而且 95% CI 跨 0、5 seeds 不足以显著；
   逐 seed 看：它把 seed3 3.44→10.27、seed4 0.66→8.50 抬高，但把 seed1 13.05→2.61 压低，
   seed2/5 小幅变化，属于“方差重分配”而不是稳定增益。
5. **seed 方差远大于 config 差异**：baseline value 0.66–13.05（极差 12.4）；
   任何配置的 Δ CI 都宽（约 ±7），不能声称宽度/深度有显著正收益。
6. **代价**：w2d2 约 112–116s/run，是 baseline 的 3.3 倍；没有稳定收益。

### 逐 seed 终局 value（关键配置）

| seed | w1_d1_h0 | w2_d1_h1 | w2_d2_h0 | w2_d2_h1 |
|---:|---:|---:|---:|---:|
| 1 | 13.05 | 0.34 | 2.61 | 2.32 |
| 2 | 8.92 | 13.55 | 7.69 | 8.26 |
| 3 | 3.44 | 5.84 | 10.27 | 9.89 |
| 4 | 0.66 | 2.50 | 8.50 | -1.12 |
| 5 | 9.17 | 9.08 | 9.52 | 9.23 |
| mean | 7.05 | 6.26 | 7.72 | 5.71 |

（完整 40 行见 `docs/search_bench/15turn_results_5seed.json`。）

## 5. 解释

- 当前 value scorer 只看 **终局棋盘**，而搜索在招募早期面对空/小棋盘，绝大多数候选的 leaf value
  非常接近；width=1 时搜索退化为“立即 value 贪心”。
- `horizon=1` 只是 leaf 后多走 **2 个 heuristic 动作**，没有真正建模下回合商店/经济/三连；
  这会让宽搜索偶尔选择“牺牲当前经济换未来”的线，但代理不够准，平均反而更差。
- w2d2 的某些 seed 出现 tier 2 终局（seed1），说明宽+深搜索可能为了短期 value 放弃升级节奏；
  这是“搜索目标/代理错位”，不是算力不足。
- 结论：在这个 15 回合、无战斗、单座的测试里，**增加 beam 宽度/深度/廉价跨回合项不能稳定提升终局阵容强度**；
  当前唯一均值略高的 w2d2h0 也伴随 tier 下降与宽 CI，不能作为“更强”结论。

## 6. 复现

```powershell
# 完整矩阵（8 config × 5 seeds，约 20–25 分钟）
python -u scripts\search_15turn_bench.py `
  --widths 1,2 --depths 1,2 --horizons 0,1 --seeds 1,2,3,4,5 `
  --turns 15 --out runs\search_15turn_bench_full

# 分析 + 唯一阵容 pairwise（支持多个 results 合并）
python scripts\analyze_search_15turn.py `
  --results runs\search_15turn_bench_full\results.json
```

注意：

- `runs/warband_value/model_60k/checkpoint.pt` 是本地训练产物（`.gitignore`），
  需要先按 `docs/WARBAND_VALUE_NETWORK.md` 训练或放置；
  **2026-10-24 清理后该目录已删除**，见 [CLEANUP_20261024.md](CLEANUP_20261024.md)。
- `runs/search_15turn_bench_full/` 也在 `.gitignore`；仓库内保留
  `docs/search_bench/15turn_results_5seed.json` 与 `15turn_analysis_5seed.md` 作为 5-seed 快照。
- 这只是 **搜索策略基准**，不代表线上/8 人对局强度；8 人对局另有 `scripts/eval_turn_search.py`。

## 7. 后续建议

1. 增加 seeds 到 ≥10，按 seed 配对做 Wilcoxon/CI；当前 5 seeds 仍偏少。
2. leaf value 加入 **tier/经济/三连进度/下回合商店期望**，否则宽搜索会牺牲节奏。
3. 若要做真正跨回合预期，应使用 **turn-level rollout**（至少完整下回合招募，而非 2 个动作），
   并控制额外计算预算。
4. 对 width=1 的 depth/horizon 做短路：搜索前检测 beam=1 的等价性，避免无意义算力。
