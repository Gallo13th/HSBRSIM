# `hsbg/search` — 搜索与决策器（train-free 实验基础设施）

> 状态：turn-search 方向已收口（“有希望但未证实”）；本目录代码保留，作为后续价值网/搜索的
> 评估基础设施。**不训练、不更新权重、不改 env/engine。**

## 模块

| 文件 | 作用 |
|---|---|
| `forward.py` | 引擎 forward model 适配（planning v1 clone/apply/ERP/turn_combat） |
| `evaluator.py` | 冻结 BC checkpoint 推理（prior/rank value；仅作为 prior/对照，不用于训练） |
| `turn_search.py` | **当前正确的搜索形态**：单回合自枚举 + 状态间两两战斗胜率 + receding horizon；`state_scorer=value_prune_pairwise` 时 value head **只剪枝**，最终动作仍由 pairwise 分决定（`final_choice_by_pairwise=True`） |
| `mcts.py` / `micro_mcts.py` | 早期 macro PUCT / 动作级 PUCT（含 horizon3/full-game 叶；**结论作废/仅对照**） |
| `hard_search.py` / `wide_beam.py` / `decision.py` | 早期 macro 候选/大型 beam/决策器（结论作废/仅对照） |
| `rollout.py` / `determinize.py` / `types.py` | rollout、determinization v0（数据缺口）、共享类型 |
| `../scripts/eval_turn_search.py` | turn-search 评测脚本（BC/heuristic 对照、配对统计） |

## turn-search 最终结论

- 形态：**只搜当前回合**（到 `end_turn` 前），枚举可达状态，对状态集合做**两两战斗胜率**
  `score(s)=mean_{t≠s} winrate(s,t)`；每个当前动作的可达状态取 max/mean 分 → argmax；执行后
  在新状态重搜下一步。**不模拟下一回合、不做 full-game rollout、不用名次/价值网。**
- 结果（seeds 300–319，heuristic/teacher 交替，states_budget=12，20 局/cell）：
  - BC baseline 4.50 / top4 45% / win 10%
  - turn-search **3.65 / 70% / 15%**；动作改变率 **75%**
  - 配对差 **+0.85，CI [-0.45,+2.20]**，精确符号检验 p=0.63
- 预算敏感性：states8 +0.65、states12 +0.85、states16（7 局）+1.43；动作改变率稳定 71–76%。
- **states16 50 局确认（seeds 300–349，纯 pairwise）**：BC 4.22 / top4 58% / win 8% vs
  turn-search **2.90 / 86% / 30%**；配对差 **+1.32，CI [0.80,1.82]**，精确符号检验
  **p=4.26e-6**，动作改变率 74.9%、1132.7ms/决策、combats 64.2 → **强方向证据**。
- **跨对手 10 局（seeds 350–359，heuristic/teacher/random 循环；env 无 BC 对手）**：
  BC 4.20/50%/20% vs turn-search **1.70/90%/70%**；配对差 **+2.50，CI [1.30,3.70]**，
  精确符号检验 **p=0.0078**；动作改变率 77.8%、1035.7ms/决策 → 跨对手仍正收益。
- 决定：states8/12 的“有希望但未证实”已由 states16 20/50 局升级；跨对手验证通过，
  可进入 PPO/接口对接；旧 macro/horizon3 结果仅作对照。
- **value head 边界（用户澄清）**：value 只能用于枚举/候选的中间排序与**剪枝**；最终动作必须由
  finalists 的 pairwise 真实战斗胜率 argmax 决定，绝不能把 value 分直接当最终分。
  Phase1 训练的新 value head（`runs/value_net/turn_search_phase1/`）val MAE 1.28/CE 2.35、
  但 value 与 pairwise 状态分 Spearman 仅 **-0.064**；改用当前回合 pairwise 胜率标签训练的
  winrate head（`runs/value_net/turn_search_winrate/`）held-out Spearman **0.511**（旧头 0.361），
  但本地 pairwise Spearman **-0.007**；5 局剪枝速度提升（states12 620→345ms、combats 47→5），
  名次仍不稳定（K4 2.60 vs pairwise 2.20）→ 暂不做 states16/24/20 局，最终仍用 pairwise。
  B 路线本地 pairwise 标签（13,008 states）训练后 held-out Spearman val .304/test .224，
  5 局 states12 pairwise 2.20/100% vs K4/K6 3.40/60%，仍掉点 → 继续保留全 pairwise。
- 下一步：见 `docs/VALUE_NETWORK_PLAN.md`（value 网络用于加速/剪枝，最终动作仍 pairwise）。

## 复现

```powershell
python scripts\eval_turn_search.py --games 5 --seeds-start 300 \
  --states-budget 12 --samples-per-action 1 --combat-samples 1 \
  --completion-policy heuristic --out-prefix turn_search_pilot --max-wall-seconds 1500
python -m pytest tests\test_turn_search.py -q
```
