# AutoTavern 论文的训练方案（原文核对）

> 来源：Changlian Ma, Limin Wang，*Build, Don't Play: Self-Improving LLM Research Agents
> Develop a Hearthstone Battlegrounds AI That Rivals Top Players*，**arXiv:2610.33845v1**
>（2026-10-24，南京大学 / 上海人工智能实验室）。核对方式：抓取 arXiv HTML 全文
>（`https://arxiv.org/html/2610.33845v1`，352 KB）后按小节抽取原文；本文只记录**论文自己写的
> 内容**，第 9/10 节才是与 HSBRSIM 现状的差距与建议。
> 注意：TavernAgent 的**权重与训练代码不发布**，以下全部是论文文字与表格，不是从代码读出来的。

## 1. 一句话概括

TavernAgent = **18M entity transformer + 纯 PPO（没有 MCTS、没有自对弈）**；对手是
**7 个「library seat」**（按顶尖人类统计校准的对手牌面，逐回合按目标强度曲线取）；
每个 stage **300 iterations × ≈1.05M decisions ≈ 310M decisions（≈57 万局）**，
跨 stage 用 **KL anchor（β=0.1，前 100 个 iteration）**；23 个交付版本把「对校准对手的
吃鸡率」从 **1.9% 提到 41.5%**，平均名次 **3.40 → 2.33**，天梯 rating **6,000 → 14,007 →
约 15,000**。

> 原文：*"We use a standard learner, PPO … with a transformer"*（§2）；
> *"Rather than self-play, the learner faces seven library seats"*（§6）。

## 2. 训练配置（Table 7，原文照抄 TA-23 最终 stage）

| 配置项 | 值 |
|---|---|
| Games per member × steps | **512 × 256** |
| Iterations per stage | **300** |
| Decisions per iteration | **≈1.05 × 10⁶** |
| Minibatch / epochs | **8,192 / 1** |
| Learning rate | **6 × 10⁻⁶ → 5 × 10⁻⁶** |
| Clip / target KL | **0.2 / 0.05** |
| γ / λ | **1.0 / 0.995** |
| Gradient norm clip | **1.0** |
| Entropy / value / auxiliary coefficients | **0.002 / 0.5 / 0.1** |
| **KL anchor to the stage's start** | **0.1 for 100 iterations** |

即：奖励是终局名次效用（γ=1、λ=0.995）；一个 stage ≈ 310M decisions；KL anchor 只在前
1/3 的 iteration 生效（防止离开 stage 起点太远），之后放开。

## 3. 对手：reality-calibrated library seats（论文称「最大单项收益」）

原文（§6 *Reality-calibrated opponents*）：

> *"Rather than self-play, the learner faces seven library seats: each turn, a seat takes a board
> (with hand and hidden counters) from a library built from statistics of top human players and
> recalibrated, turn by turn, to the opponents the agent actually met in live games; exam libraries
> are never used for training."*

附录 C *Opponent libraries* 补充：

- **一个 library entry = 某个座位在某一回合的牌面**（board + hand + hidden counters）；
- 最初由**顶尖人类统计**（种族占比、升级曲线、购买率、分回合的 warband 强度）加录制对局构造；
- 每回合按**目标强度曲线**抽一个 entry；
- 之后**按天梯实际遇到的对手重新校准**（"strength is measured on the opponents the learner
  meets, not on entries drawn uniformly"）；
- 有**梯度难度**：从对齐的库到更硬的库（后期牌面带 venomous、留手牌、天花板构筑）；
- **exam library 永不参与训练**，训练用的是「同样的方法、不同来源」的 **twin** 库。

消融（Table 3，同起点同预算各 150 iterations）：

| 对手 | 主 exam 吃鸡率 | 更难 exam 吃鸡率 |
|---|---:|---:|
| 未校准 opponent libraries | 20.9% | 10.3% |
| **校准后的 libraries** | **27.2%** | **13.5%** |

更新节奏：20 天内 **14 次重校准**（附录 A：*"14 recalibrations of the opponent libraries and exams
to the opponents met in live games"*）。**论文未给出** library 条目数/池规模，也未给出每次重校准
的固定 cadence。

配套的考试库（exam）：每个评测点 **24,576 局 = 3 个未见 seed × 8,192 局**；训练库与 exam 库是
「同方法、不同来源」的 twin，exam 库不参与训练。

## 4. 课程：从零到 library（附录 C *Training stages*）

> *"Learning started from scratch on a simplified rule set, moved to the full content, then to the
> player's view, then to a first-place goal against opponents fitted to human statistics, and then
> to library opponents. Later versions are chains of 300-iteration stages (about 310 million decisions
> and 570 thousand games each), each starting from the previous stage under a KL anchor for its first
> 100 iterations."*

顺序：**简化规则 → 全内容 → 玩家视角（只用公开信息）→ 打「按人类统计拟合」的对手、目标是吃鸡 →
library 对手**；后期 stage 用梯度难度的训练库；**只有通过 unseen-seed 复查才交付**（gate G4）。

## 5. 网络与输入（附录 C *Architecture*）

- 每张己方随从/手牌/酒馆/待选/对手 = 一个 token（**至多 56**，另加 1 个 global token）；
- 卡牌表示 = **identity embedding + 静态特征投影 + 卡牌规则文本的 embedding 投影**
  （*"which gives rare cards a sensible start"*）；
- 磁力/Dark Gift 等附着**加到宿主随从 token 上**；饰品位、持续效果、计数器**池化进 global token**；
- 对手 token = 公开排行榜信息 + **上次见到的 warband 池化** + 那场战斗结果；
- 输入用**对称对数（symmetric logarithm）压缩**；
- 三个头：**pointer head（245 个 masked action logits）+ value head + placement 辅助头**；
- d=384、8 层、8 头、**18M 参数**（Table 8：3.5M/8M/18M 同配方对比，18M 名次最好：
  3.67 vs 3.77 vs 3.84）。

## 6. 推理与搜索：**不用树搜索**

- 模型前向本身极快：TavernBench 上 **0.03 s/任务**（Table 4），而 LLM 需要 1.4–26 s。
- TavernBench 的 0.03 s **不只是 argmax**：原文 §7 *TavernAgent's interface* 写的是——
  *"Combat questions and short-term decisions use TavernGym as the agent's model of the game: it
  applies each option and simulates 256 combats after it (one-step lookahead)."*
  即「一次前向 + 每题最多 256 次战斗模拟的**一步 lookahead**」，**没有 MCTS/树搜索/多步规划**。
- 在线天梯：*"the controller feeds the live game's state to the policy in the environment's own
  encoding, the policy decides every operation"*（§6 Live ladder）。**论文没有说明在线是否也做
  这个 lookahead，也没有说明用 argmax 还是采样。**
- §2 明确方法是标准 PPO + transformer：*"We use a standard learner, PPO … and focus on building and
  correcting the training world itself."*——全文没有 MCTS / 树搜索 / self-play 的训练用法。
- §8 反而记载了一次**搜索被骗**（唯一一次搜索尝试）：
  *"(i) Copied games leak the future. A search over game copies appeared to add 23.6 points of
  first-place rate; the copies carried the random-number state, so the search saw the real future
  shop and combat outcomes. Reseeded per sample, the gain vanished (−0.65 ± 1.14 points)."*
  —— 拷贝局面若不重播种 RNG，搜索会「看到未来」，重播种后增益消失。这条对我们的 PIMC
  直接构成风险提示。


## 7. 评测协议

- 每个评测点 **24,576 局 = 3 个未见 seed × 8,192 局**（Table 3/9 标注 "three unseen seeds,
  24,576 games per row"）；
- 交付门 G4：候选必须**在没被用于挑选的 seed 上复查**才交付（§4 Verification gates；§8(iii)
  "winner's curse" 记载：从多个 snapshot 里挑最好会高估 +1.2–2.1 分，unseen seed 上 −0.7）；
- 基线：random legal 7.97、scripted bot 7.54（Table 3）。

## 8. 算力（附录 F）

> *"Main-line training ran on eight H200 GPUs with 128 CPU cores. Training the 23 delivered
> TavernAgent stages took about 1,900 GPU-hours; all other training runs of the 20 days
> (explorations, ablations and abandoned lines) about 16,700 GPU-hours, and evaluations and analyses
> about 1,300 GPU-hours."*

即：**交付主线 1,900 GPU-h（23 个 stage，平均 ≈83 GPU-h/stage）**；试错/消融 16,700 GPU-h；
评测 1,300 GPU-h；研究 agent 本身消耗约 1 亿 output tokens 的前沿 LLM。

## 9. 与 HSBRSIM 现状的差距（同口径对照）

| 维度 | AutoTavern 论文 | HSBRSIM 现状 | 差距性质 |
|---|---|---|---|
| 算法 | 纯 PPO，无搜索、无自对弈 | PIMC MCTS + PPO（`behavior=net`，π 作辅助 CE） | 我们多了一条论文没有、且经验上无增益的线 |
| **每 stage 预算** | **300 iter × 1.05M ≈ 310M decisions / 57 万局** | 1M decisions（≈论文的 **1/300**，等于他们 1 个 iteration） | **两个数量级** |
| 对手 | 7 个 library seat（人类统计校准、逐回合强度匹配、梯度难度、exam 库隔离） | 7 个**同一个引擎脚本 bot** | 论文称这是最大单项收益；我们等于零课程 |
| KL anchor | 每个 stage 前 100 iter，β=0.1 | **未实现**（只有 batch KL 早停） | 我们观察到的单调退化正对应缺失项 |
| minibatch / epochs | 8192 / 1 | 1024 / 1（本次跑） | 每 iter 17 次更新 vs 他们 128 次 |
| lr | 6e-6 → 5e-6 | 1e-5（本次跑） | 偏高 |
| λ / entropy / grad-clip | 0.995 / 0.002 / 1.0 | 0.95 / 0.005 / **0.5** | 三处不一致 |
| value / aux | value head + **placement 辅助头**（0.1） | rank 分布 CE（`E[u]`），无 placement 头 | 少一个辅助信号 |
| 输入编码 | 56 entity + 1 global；卡牌含**规则文本 embedding**；对称对数 | entity 49（18m 版本 57，其中 8 个是**结构补位**）；无卡牌文本 embedding | 表征口径不同 |
| 评测点数 | 24,576 局/点（3 unseen seeds × 8192） | 512 局（8 seat × 64）；曾用 64 局选 checkpoint | 我们样本量小 48 倍，且犯过 winner's curse |
| 算力 | 8×H200 / 128C，主线 1,900 GPU-h | 4×4090（且有别的项目共用），累计 <10 GPU-h | 规模差 2–3 个数量级 |

## 10. 对我们的直接含义

1. **我们 1.08M PPO 退化，与论文并不矛盾**：1.08M 只等于论文**一个 iteration**；论文的
   「一个 stage」是 310M。用 1/300 的预算去跑，看到的自然是噪声/漂移，而不是强度趋势。
2. **最该补的不是步数而是对手分布**：论文实测「校准库」把吃鸡率 20.9%→27.2%（同起点同预算），
   是所有实验里最大的单项收益；我们现在 7 个座位是**同一个 bot**，advantage 近乎零均值噪声。
3. **KL anchor 是论文的显式设计**（β=0.1、前 100/300 iter），我们完全没有——这正是「越训越差」
   的直接嫌疑。
4. **MCTS/自对弈在论文里不存在**，且论文记录了「拷贝局面搜索看到未来」的假增益（reseed 后消失）。
   我们的 PIMC 若复用带 RNG 的 `Game` 拷贝，存在同一类泄漏风险，值得按论文方式复测。
5. **评测协议要改**：至少 8,192 局/点 + unseen seed 复查；64 局选 checkpoint 正是论文 §8(iii)
   记录的 winner's curse。

### 建议的实施顺序（按「性价比 / 与论文对齐度」）

- **P0（当天）**：① 实现 KL anchor（冻结 stage 起点，β=0.1，前 1/3 iteration，之后放开）；
  ② 超参对齐：λ=0.995、entropy=0.002、grad-clip=1.0、minibatch 8192（用梯度累积）、lr 6e-6；
  ③ 评测改成 ≥8,192 局 + unseen seed。
- **P1（1–2 天）**：用现有引擎做 **library seats 原型**——从 bot 对局按回合/强度分档取样牌面，
  7 个座位全部来自库（训练库与 exam 库分离），先做「对齐 vs 未对齐」的同预算消融复现论文 Table 3。
- **P2**：把「一个 stage」拉到 30–100M decisions（我们的 684.9 dec/s ⇒ 30M ≈ 12 h、100M ≈ 40 h，
  4 GPU 独占时），按 stage 交付；搜索只保留为评估/重搜消融，不进训练主环。

> 结论：论文的训练方案是**「PPO + 校准对手库 + KL anchor + 大 stage 预算」**，不是
> 「AlphaZero + MCTS + 自对弈」。我们之前的 PPO 结论（1M 退化）应当重新解释为
> **预算差 300 倍 + 对手错配 + 缺 KL anchor**，而不是「PPO 不适合这个游戏」。
