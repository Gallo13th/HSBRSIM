# 阵容嵌入 / 价值网络（pairwise 战斗标签）

> 方向（用户提出）：不需要用模拟环境打完整对局来获得阵容；可以近乎暴力地枚举
> 随从组合与排序，用 pairwise 战斗胜率训练阵容嵌入和价值网络。
> 本文件记录实现、pilot 结果与下一步。

## 1. 方法

### 1.1 数据生成（不做完整对局）
- 从 `data/` 的 BG 随从池（273 张）采样阵容：
  - 规模 1–7；
  - 按回合决定最大 tier（1–6），从该 tier 以下随机取随从；
  - 允许重复（真实对局中重复会三连，pilot 先按独立随从处理）；
  - 随机顺序（站位）；
  - atk/hp 在卡面值上随机加 buff（模拟真实状态差异），并按概率附加战斗关键词
    （taunt / divine_shield / poisonous / windfury / reborn）。
- 每套阵容与随机对手做 pairwise 战斗（`hsbg.planning.live_warband.simulate_combat_warbands`），
  记录胜/平/负（draw=0.5）与伤害；1–2 个 seed 平均。
- 输出 `runs/warband_value/pairs_*.npz`：padded 特征 + pair 标签 + 词表 meta。

生成器：`scripts/build_warband_pairs.py`  
实测：800 套/1600 对 3.1s；20,000 套/59,996 对 177s；3,000 套/11,996 对 49s。

### 1.2 模型
`hsbg/value/warband_model.py`：
- 每个随从特征：卡牌 embedding + log(atk/hp) MLP + tier embedding + 关键词多热 + 位置 embedding；
- 7 个 token + CLS，Transformer encoder（dim 128 / 3 层 / 4 头）；
- 输出 scalar strength `s` 与 CLS embedding（阵容嵌入）；
- pairwise Bradley-Terry：`P(A beats B)=sigmoid(s_A - s_B)`，BCE 训练（支持软胜率标签）。

训练：`scripts/train_warband_value.py`；评估：`scripts/eval_warband_value.py`。

## 2. Pilot 结果（20k → 60k 阵容）

训练：dim128/3 层，15 epochs，GPU **39.8s**。

| split | pair accuracy | Spearman（预测分 vs 阵容平均胜率） |
|---|---:|---:|
| val | 0.907–0.911 | 0.769–0.770 |
| test | **0.9117** | **0.7576** |

**独立 fresh 数据**（3,000 新阵容 / 11,996 对，不同 seed）：
- 20k 模型：pair accuracy **0.9112**、Spearman **0.8054**
- 60k 模型（60,000 阵容 / 179,996 对，训练 103.5s）：pair accuracy **0.9129**、Spearman **0.8073**
- 60k 相比 20k 提升很小 → 当前数据分布下已接近饱和，下一步应提升分布真实性/特征，而不是只加随机样本
- 分数范围：mean 0.24，std 5.91（未校准，仅用于排序）

结论：**用 pairwise 战斗标签训练阵容价值网络是可行的**；即使只给随机组合+随机 buff，
模型也能在未见阵容上达到 ~91% 成对准确率、rank 相关 ~0.8。

## 3. 与之前价值头的区别

- 之前：用 BC/教师轨迹的终局名次训练 value head，目标噪声大、与搜索 pairwise 目标不一致；
- 现在：直接以**战斗胜负/pairwise 胜率**为监督，目标与战斗裁决器一致、标签成本低、
  可以近乎无限生成数据；模型学到的是"阵容强度"而不是"终局名次"。

## 4. 下一步（建议）

1. **扩大规模**：200k–1M 阵容 / 0.5–2M 对（生成约 15–60min，训练几分钟）；
2. **特征/分布对齐**：
   - 用真实 live/BC 状态里的 atk/hp/keywords 分布采样，而不是均匀随机；
   - 加入 tier/race 组成、英雄技能、饰品/黑暗之赐（后续）；
   - 处理三连/金色、磁力、复生等真实状态；
3. **阵容嵌入目标**：除 pairwise 头外，加对比学习/排序损失，使 embedding 可用于最近邻检索；
4. **下游使用**：
   - 作为 turn-search 候选状态的**廉价评分/剪枝**（最终仍可 pairwise 复核）；
   - 或用价值网络给搜索排序、减少 pairwise 战斗次数；
5. **评估**：与真实参考阵容的 win-rate 相关性、pair accuracy、校准、以及搜索增益。

## 5. 限制（如实）

- pilot 的随从属性是卡面值 + 随机 buff，尚未对齐真实对局状态分布；
- 未含英雄技能、饰品、黑暗之赐、三连/金色、磁力合并等；
- 战斗模拟使用引擎（含已知脚本 gap），与真实客户端仍有差异；
- 当前分数未校准，只适合排序；作为概率使用需温度/isotonic 校准。
