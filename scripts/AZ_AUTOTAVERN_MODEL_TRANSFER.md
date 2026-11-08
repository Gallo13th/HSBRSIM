# AutoTavern 模型/训练方案迁移记录（arXiv:2610.33845）

> 来源：*Build, Don't Play: Self-Improving LLM Research Agents Develop a Hearthstone
> Battlegrounds AI That Rivals Top Players*（Ma & Wang, 2026）
> 本文记录**精读 paper 后**从 TavernAgent 迁移到 HSBRSIM AZ 训练的部分、未迁移部分、
> 初步对照结果与下一步。代码：`hsbg/az/train/entity_model.py`。

---

## 1. 论文模型设计（原文要点）

- **Entity transformer**：己方随从(7)/手牌(10)/酒馆(8)/待选(pending)/对手(7) 各为 token，
  最多 **56 token + 1 global**；
- 卡牌表示 = **identity embedding + 静态特征投影 + 规则文本 embedding**（rule text 让稀有卡
  有好起点）；磁力/黑暗赠礼等附件加到所属随从 token；全局状态（饰品/持久效果/计数器）
  汇入 global token；对手 token 含公开信息 + 上一次见到的战团 + 战斗结果；
- 输入做 **symmetric log** 压缩；
- **Pointer head** 产出 245 个 masked action logits；value head + auxiliary placement head
  共享 trunk；
- 规模：**d=384, 8 layers, 8 heads, 18M 参数**；早期 size 对比 3.5M(d192/4)/8M(d256/6)/
  18M(d384/8)，18M 最好（Table 8）。

## 2. 论文训练方案（原文要点）

- **PPO**（不是 search-based self-play）：
  - 每 iteration ~**1M decisions**；每 stage 300 iterations ≈ **310M decisions / 570k games**；
  - 每个 stage 从上一 stage 初始化，**KL anchor 0.1 前 100 iterations**；
  - 配置（Table 7）：games/member×steps 512×256；minibatch 8192；lr 6e-6→5e-6；
    clip 0.2 / target KL 0.05；γ=1.0, λ=0.995；entropy 0.002；value 0.5；aux 0.1；
- **Reality-calibrated opponent libraries**（不是 self-play）：7 个 library seats，每 turn 从
  “顶尖人类统计 + 录制对局”构建的 library 取一个 board（含 hand/hidden counters），并按
  天梯实际遇到的对手逐 turn 校准；**exam libraries 从不用于训练**；这是单点最大增益：
  同 checkpoint/预算，first-place 20.9%→27.2%（main）、10.3%→13.5%（harder）；
- **课程**：简化规则 → 全内容 → 玩家视角 → first-place 目标 → library 对手；
- **iterative delivery**：23 版 TavernAgent，20 天；每版在 unseen seeds 上重测；
- **live ladder 闭环**：策略直接经客户端控制器打天梯，人工只按键；392 局 6000→14,007，
  最终 top 100，最近 20 局 1.60 平均名次（server top10 为 2.34）。

## 3. 我们迁移了什么

| 论文设计 | 我们的实现（`entity_model.py`） | 状态 |
|---|---|---|
| Entity tokens ≤56 | 全局 + 随从7 + 手牌10 + 酒馆8 + 待选16 + 对手7 = **49 token** | ✅ |
| 卡牌 identity + 静态 + 规则文本 | identity embedding + `card_static()` 投影 + **字符 3-gram 哈希文本 embedding**（TEXT_DIM=64，非学习文本编码器） | ✅ 近似 |
| 附件/全局状态 | 随从/物品特征已含 attached 等位；饰品/英雄/技能/秘密卡牌表示汇入 global；未做独立 attachment token | ◐ 部分 |
| 对手 token | 公开 9 特征 + 上次战团 mean/max + 对手英雄卡牌 | ✅ |
| symmetric log | 输入 `sign(x)*log1p(abs(x))` | ✅ |
| Pointer head 245 | Buy/Sell/Activate/Choose/Play(手牌×位置)/Magnetize(手牌×随从)/Move(随从×随从) 点积 + 类型/位置 + 偏置；标量动作来自 global | ✅ |
| Transformer d384/8/8 | d=384, 8 layers, 8 heads；FF=4d；**14.8M 参数**（与 18M 的差异主要来自 head/FF 配置） | ✅ |
| value + placement head | rank(8) + value scalar（MSE 辅助） | ✅ |
| PPO | **已实现**：`hsbg/az/train/ppo.py`（masked PPO + GAE + clip + KL 早停；π 辅助 CE 可配；`--sims 0` 退化为纯网络 PPO，`--behavior net/mcts/mixed`） | ✅ 代码就绪；未规模训练 |
| 1M decisions/iter、300 iter/stage、KL anchor | 未实现；当前 stage 只有 4 局/5k decisions | ❌ |
| reality-calibrated opponent libraries | 未实现；当前 self-play 8 座同策略，没有 library/联赛 | ❌ |
| 课程/23 版迭代/天梯闭环 | 未实现；只有单机小规模 | ❌ |

## 4. 初步对照（远程 hiermolgen，CUDA torch 2.6）

命令：
```bash
PYTHONPATH=$PWD/rust/python:. ~/.conda/envs/hiermolgen/bin/python scripts/az_selfplay_smoke.py \
  --policy search_rust --search-sims 4 --search-backend rust --evaluator net \
  --bootstrap-games 100 --max-train-samples 60000 --epochs 3 --arch {tiny,entity} \
  --device cuda --games 4 --eval-games 50 --out runs/az_arch_{tiny,entity2}
```

| 指标 | Tiny MLP | Entity（初版） | Entity（pointer 缩放后） |
|---|---:|---:|---:|
| 参数量 | ~0.96M | 14.8M | 14.8M |
| 训练 loss（bootstrap 3 epoch） | 1.02 | 143→2.96 | 8.90→1.06 |
| value-rank corr（监督） | 0.953 | 0.991 | **0.9938** |
| policy top1 vs π | 0.745 | 0.723 | **0.7811** |
| eval mean rank（search-off, 50 局） | 7.92 | 6.90 | **5.28** |
| 同 eval bot 基线 | 4.96 | 4.96 | 4.96 |
| 4 局 self-play 耗时 / 吞吐 | 9.9s / 0.406 games/s | 118s / 0.034 | 134s / 0.030 |

从 entity2 checkpoint 继续训练（`--net-checkpoint`）：
| 续训配置 | 样本 | value corr | policy top1 | eval mean rank | bot |
|---|---:|---:|---:|---:|---:|
| +4 局（stage3） | 4,566 | 0.996 | 0.751 | 7.28 | 4.96 |
| +16 局（stage4） | 16,964 | 0.995 | 0.727 | 6.16 | 4.78 |

4 局 stage 因样本少/无 KL anchor 出现退化；16 局明显缓解但仍未超过单 stage entity2
（5.28，评估 seed/数据不同，差异在噪声范围）。说明 **每 stage 数据量与 KL/league 比
单次模型容量更关键**。

**结论**：entity/pointer 架构在 **value 拟合、policy top1、单 stage 评测名次** 上均优于
Tiny MLP；但**搜索叶评估（14.8M 网络逐叶前向）使 self-play 慢 ~12×**；且单 stage 4 局
数据下仍远弱于 bot，说明 **数据/对手库/迭代次数** 仍是主瓶颈。

续训结果说明：**小样本 stage + 无 KL anchor/无联赛会导致漂移**（4 局 stage 退化到 7.28）；
16 局 stage 回到 6.16，但仍未稳定超过单 stage 的 5.28。这不是架构问题，而是训练方案
不完整（paper 每 stage 570k 局 + KL anchor + library 对手）。

## 5. 下一步（按论文可迁移性）

1. **PPO/actor-learner 或混合 AZ**：PPO 已实现（`hsbg/az/train/ppo.py`）；论文用纯 PPO，
   我们默认 MCTS-guided PPO。下一步先做 **批量叶评估**，再决定 MCTS 比例与规模；
2. **Reality-calibrated opponent library**：需要真实/录制对局数据（我们已有 Power.log/bridge
   资产可接）；先做 bot/历史 checkpoint library，再做人类统计校准；
3. **KL anchor + 多 stage 迭代**：每个 stage 从上一 checkpoint 初始化，前 N iter KL 约束；
4. **课程**：简化→全内容→玩家视角→first-place→library；
5. **模型 size sweep**：3.5M/8M/18M 同数据对比（论文 Table 8 方法），决定我们的容量；
6. **评估**：500–1000 局 + unseen seeds + TavernBench Tier2；不要用 4 局 stage 判断强弱。

## 6. 限制（诚实边界）

- 文本 embedding 是字符哈希，不是论文的学习式 rule-text encoder；
- 未实现 attachment/global 的全部细节，token 数 49 vs 56；
- 我们的评测是 seat0 vs bot，不是 7 座 library；与论文的完整对局不可直接横比；
- PPO 代码已就绪（2026-10-27），但只做过 1 局 smoke，未做论文规模的 actor-learner/库/课程/迭代；
- `hsbg/bridge`/`live` 与旧轨迹已在重构中删除；reality-calibrated library 需重新引入只读数据适配层；
- 当前评测仍是 seat0 vs bot，不是 7 座 library；不要用 4 局 stage 判断强弱。
