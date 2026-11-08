# 搜索蒸馏理论：把推理期改进训练回策略

> 状态：只读理论与实验设计；本文件不启动训练、不占用 GPU。
> 依据：`docs/INFERENCE_SEARCH.md`（搜索实现与 256 局 A/B）、`runs/infer_search_ab/AB_SUMMARY.json`（配对统计原始量）、`runs/search_labels_v2/REPORT.md`（300 局标签 / 96 局评测 / 48 局深度）、`docs/CARRIER_SCALING.md` 与 `docs/SCALING_SIGNAL.md`（200 局口径，仅作交叉参照）。
> 核心问题：推理期搜索已经有效，但如何把其**条件化的改进**而不是粗粒度动作偏好学回策略。

## 结论摘要

1. **推荐路线**：learner-DAgger 采状态 + 优势加权软 ExIt + KL 信赖域（目标平均 KL $0.02$、硬上限 $0.05$、每 20 个 PPO iter 一次）；PPO 作保留外壳，搜索只当**局部 surrogate 优势**，不当终局专家。
2. **第一轮最小实验**：固定 checkpoint 起，采集 2M（上限 5M）learner 决策；只在关键决策做 1 回合 top-$8$ 非 Move 候选搜索、每回合 $\le 3$ 次；20% holdout；蒸馏 batch 占 10%，标签不混 horizon。
3. **判据**：关闭搜索时 human 256 局配对 mean-rank $\Delta\le-0.10$ 且 95% CI 上界 $<0$；capture ratio $\ge50\%$ 是**阶段目标**，不是首次硬门槛。
4. **已测事实**：推理搜索 256 局同 seed A/B：off $6.375$ → $t1$ $5.953$（配对 $\Delta=-0.422$，95% CI $[-0.602,-0.242]$，`runs/infer_search_ab/AB_SUMMARY.json`）；离线 BC 学不进去（96 局 gold10 样本口径 $-3\%\sim-80\%$，`runs/search_labels_v2/REPORT.md` §4）。
5. **不可测边界**：256 局 human 面板内 0 局进入 t15 统计，叶值只含盘面 $\Sigma$，t15 rank 不能当验收指标；样本口径按 256 / 96 / 48 局分开标注、互不替代。

## 1. 事实、符号与问题边界

设完整游戏状态为 $s$，合法动作集合为 $A(s)$，策略为 $\pi_\theta(a\mid s)$，当前策略记为 $\pi=\pi_\theta$。训练是纯 PPO、rank-only 终局奖励，$\gamma=1$、$\lambda=0.995$。

评测口径（三套，**不可混用**）：

| 口径 | 样本 | 来源 |
|---|---|---|
| 推理搜索 A/B（完整游戏） | **256 局** = 8 seat × 32 局，seed_base 420000，两臂逐局同 seed/seat | `runs/infer_search_ab/AB_SUMMARY.json`；协议见 `docs/INFERENCE_SEARCH.md` §3 |
| 沙盒强度/存活 + 离线 BC | **96 局** gold10（seed 区 970000+/910000，固定采样 RNG） | `runs/search_labels_v2/REPORT.md` §3–§4 |
| 3 回合叶值（深度） | **48 局** gold10（同 seed 区） | `runs/search_labels_v2/REPORT.md` §5.1 |

**t15 在 256 局 human 面板上不可测**：0 局活到 t15（t14 仅 2 局），即“没有一局进入 t15 的统计”，不是“256/256 死亡”（`docs/INFERENCE_SEARCH.md` §4.2）。仓库另有一套 **200 局**口径（`docs/CARRIER_SCALING.md` §3.2、`docs/SCALING_SIGNAL.md` §2，s15 分布的沙盒观测），本文不与 256 / 96 局混用。

当前搜索只在关键决策调用：从 $\pi$ 的合法非 Move top-$k$（默认 $k=8$）候选中，以 rollout 到回合末（或更深）得到叶值。叶值是盘面 $\Sigma=\sum_i(\mathrm{atk}_i+\mathrm{hp}_i)$ 的

\[
 L(s')=\frac{\log(1+\Sigma(s'))}{\log(1+30000)}.
\]

它不是完整胜率，也不包含敌方未来、死亡风险或最终 rank 的显式估计。对候选 $a$ 的 rollout 估计记为 $\hat Q_\pi(s,a)$。

实测边界（256 局配对面板，`runs/infer_search_ab/AB_SUMMARY.json`）：关闭搜索 mean rank $6.375$，1 回合 $5.953$（配对 $\Delta=-0.422$，95% CI $[-0.602,-0.242]$，SE $0.093$，51.2% 局变好 / 23.8% 局变差），3 回合 $5.922$（$\Delta=-0.453$，CI $[-0.648,-0.258]$）；top4 $10.16\%\to14.84\%$（$+4.69$pp）；同一 (seat, 局序) 的局末盘面 $\Sigma$ 配对增量 $+197$（95% CI $[150.9,242.6]$，$n=256$）；无条件 $E[\Sigma_{t12}]$ 约 $\times2.03$（条件 p50 比 $\times0.96$ 受生存者偏差污染，不宜作主指标）。成本（solo 口径）：单次搜索 p50 $118$ ms（1 回合）/ $281$ ms（3 回合），搜索 $2.26/5.07$ s 每局，256 局墙钟 $843$ s（$3.8\times$）/ $1524$ s（$6.8\times$）（`docs/INFERENCE_SEARCH.md` §4.3、§5.4）。

这证明的是“搜索时动作更好”，不是“一个固定动作标签可被无风险地平均进策略”。

## 2. 搜索是何种改进算子

### 2.1 定义

令候选截断算子

\[
 C_k(\pi,s)=\operatorname{TopK}_{a\in A(s)\setminus A_{Move}}\pi(a\mid s),
\]

若基线 top-$k$ 漏掉全局好动作，则搜索不可能恢复它。令 rollout 叶值估计

\[
 \hat Q(s,a)=Q^{H}_{\pi}(s,a)+b(s,a)+\epsilon(s,a),
\]

其中 $H$ 是 rollout horizon，$b$ 是系统性叶值偏差，$\epsilon$ 是随机/数值误差。若只观察最后盘面，则真实目标应区分为 $Q^\Sigma_H$ 与 rank 目标 $Q^{rank}$；一般不存在 $Q^\Sigma_H=Q^{rank}$。

先验重加权形式为（$\tilde p$ 是 $\pi$ 在候选集上的归一化先验，与实现一致）

\[
 \tilde p(a\mid s)=\frac{\pi(a\mid s)}{\sum_{a'\in C_k}\pi(a'\mid s)},\qquad
 \hat A(s,a)=\hat Q(s,a)-\sum_{a'\in C_k}\tilde p(a'\mid s)\hat Q(s,a'),
\]

\[
 \tilde \pi_S(a\mid s)=
 \frac{\pi(a\mid s)\exp(g(\hat A(s,a)))}
 {\sum_{a'\in C_k}\pi(a'\mid s)\exp(g(\hat A(s,a')))},
\]

并在 $C_k$ 外置零；当前实现为 $g(x)=\operatorname{clip}(x/\tau,[-c,c])$，$\tau=q_{temp}\cdot\operatorname{std}_{\tilde p}(\hat Q)$（`hsbg/az/train/sandbox_rollout.py::pi_from_q`）。动作规则可为 $\arg\max_a\tilde\pi_S(a\mid s)$、$\arg\max_a\hat Q(s,a)$ 或按 $\tilde\pi_S$ 采样。

定义搜索改进算子

\[
 S_H^k(\pi)(\cdot\mid s)=\tilde \pi_S(\cdot\mid s),\qquad \pi'=S_H^k(\pi).
\]

它是**局部、截断、以盘面 surrogate 为目标**的算子，不是无条件的全局最优算子。

### 2.2 可用的策略改进定理（本设定的版本）

设真实有限 horizon 平均回报为 $J(\pi)=\frac1H E_\pi[\sum_{t=0}^{H-1}r_t]$（episodic、终止状态吸收；$\gamma=1$ 时不存在有限的 $1/(1-\gamma)$ 常数，不能直接套无限 horizon 界）。性能差异引理在有限 horizon 下写为

\[
 J(\pi')-J(\pi)=\frac1H\sum_{t=0}^{H-1}E_{s_t\sim d_t^{\pi'}}\big[E_{a\sim\pi'(\cdot\mid s_t)}A_\pi(s_t,a)\big],
\]

其中 $d_t^{\pi'}$ 是 $\pi'$ 在第 $t$ 步的状态分布。若在所有将被访问的状态上 $E_{a\sim\pi'}A_\pi(s,\cdot)\ge0$，且状态占用改变带来的项可控，则 $\pi'$ 不劣于 $\pi$；若再有正测度状态上严格为正，得到严格改进。

在有限 horizon $T$ 的 episodic 写法，若 $\sup_{s,a}|A_\pi(s,a)|\le A_{max}$，搜索目标 $\hat Q$ 与真实 $Q_\pi$ 的均匀误差不超过 $\epsilon_Q$，候选截断遗漏的真实改进行动损失不超过 $\epsilon_C$，搜索分布相对理想贪心/信赖域分布的误差不超过 $\epsilon_S$，则对同一状态（或对 $d_{\pi'}$ 取期望）有保守的 surrogate 界：

\[
 E_{\pi'}A_\pi\ge E_{\pi'}\hat A-2\epsilon_Q-\epsilon_C-\epsilon_S A_{max}.
\]

因此只要搜索产生的估计优势余量大于右侧误差，才可声称改进；否则“搜索是改进算子”不成立。

需要的前提：

1. **叶值无严重系统偏差**：$|b|$ 小，且目标与真实 rank/存活相关；只含当前盘面 $\Sigma$ 在 t15 不可测时不能代表终局。
2. **候选覆盖**：$a^\star$ 或至少一个正优势动作在 $C_k$ 中；$k=8$ 是工程预算而非理论保证（沙盒实测 topk $8\to16$ 无收益，`docs/INFERENCE_SEARCH.md` §7.3）。
3. **可行动作数有限**：$|A(s)|\le 274$（实际合法动作更少），mask 正确；Move 被移除只有在其确实不改变目标时才合法。
4. **分布漂移受限**：$\pi'$ 不得把系统性错误集中到 learner 未验证区域；必要时设 KL 信赖域（§4.4）。
5. **终止/存活可见**：若叶值忽略“这一动作让 agent 在未来死亡”，盘面上升也可能降低 rank。

沙盒证据：1 回合在线搜索把 gold10 t12 $\Sigma$ p50 从 $605.5$ 拉到 $668$（$+10.3\%$，96 局，`runs/search_labels_v2/REPORT.md` §3）；3 回合主要改善 t15（$896\to1139$，$+27\%$，48 局，同报告 §5.1），说明 $H=1$ 的目标错过跨回合复利。但 256 局 human 面板内无人活到 t15，所以 t15 rank 不可验证，只能用存活率、无条件 $E[\Sigma_t]$ 和局末配对指标（`docs/INFERENCE_SEARCH.md` §4.2）。

## 3. 既往蒸馏为何失败

### 3.1 支持/分布失配

行为数据来自 $d_{\pi_{base}}$，标签来自 $\pi_S=S(\pi_{base})$（300 局 / 81,039 步 / 8,989 个搜索决策，`runs/search_labels_v2/REPORT.md` §2）。若某状态的标签动作在行为策略下概率近零，重要性比

\[
 w(s,a)=\frac{\pi_S(a\mid s)}{\pi_{base}(a\mid s)}
\]

重尾或无定义；离线 CE 实际最小化的是 $d_{base}$ 上的条件拟合，而部署访问分布是 $d_{\pi_S}$。DAgger 让行为按 base 采样，能防分布崩溃，却不覆盖“改动作后才到达”的状态，故既保守又抓不到复利。

### 3.2 尖标签和 CE 的先验污染

对 one-hot/高峰标签 $y$，softmax CE 对 logit 的梯度是

\[
 \frac{\partial \ell_{CE}}{\partial z_a}=p_\theta(a\mid s)-y_a.
\]

在大量 $\pi_{base}$ 已近 1 的状态中，少数标签翻 top-1 会对新动作产生同方向的大梯度；如果状态特征无法区分这些例外，梯度在共享动作 head 上聚合成全局先验。v2 标签统计（`runs/search_labels_v2/REPORT.md` §2.2–§2.3，8,989 个关键决策）：$\pi_{search}$ 的 top-1 质量 $0.83$，与 $\pi_{base}$ top-1 的**一致率仅 $45.3\%$**（即 54.7% 的关键决策 top-1 不同）；KL$(\pi_S\|\pi_{base})$ 在候选支撑上 p50 $1.07$、均值 $3.59$；被换动作集中为 sell 1589、refresh 999，而 base top-1 主要 play 4475、choose 1832。于是只搜步 BC 抬高 sell/refresh，样本 t12 崩至 $117.5$（clip30，96 局，同报告 §4），不是学到了“何时 sell”。

> **口径提醒**：$45.3\%$ 是 top-1 **一致率**，不是翻转率。按“翻转率/被改变决策比例”的定义，`runs/search_labels_v2/REPORT.md` 只统计了 top-1 一致率与“被换掉的 top-1 动作类型分布”（上面 54.7% 仅对 8,989 个被搜索的关键决策有意义，且是标签层面），**没有单独测量部署口径的翻转率 ⇒ 该量标记为“未测量”**。可对照的另一个量是推理搜索的 `switch_rate`（搜索动作实际覆盖 $\pi_{base}$ 动作的比例）：$t1$ 臂 $32.6\%$（256 局，`runs/infer_search_ab/AB_SUMMARY.json` 的 `cost.switch_rate`；分母是完整游戏的被搜索决策），与 54.7% 不是同一统计量，不可互换。

### 3.3 无优势加权与系统性叶值偏差

CE 把每个标签等权处理；但 v2 的搜索 top-1 相对 base 的 $\Delta\Sigma$ 均值 $+25.5$、p50 仅 $+2$、正比例 $51.5\%$（$n=8{,}989$，`runs/search_labels_v2/REPORT.md` §2.3），长尾贡献很大。把几乎零优势的随机偏好和大优势翻盘同权，等于放大噪声。若 $\hat Q=Q+b$，且 $b$ 对 sell/refresh、载体、某类商店状态恒正，argmax 选择概率会系统性偏向该类；CE 会固化 $b$，这不是零均值噪声，增加样本不能消除。

### 3.4 容量、熵坍缩和采样放大

245+29 动作、实体条件与序列历史需要大量条件容量；只搜 11.1% 决策（8,989/81,039，沙盒口径，`runs/search_labels_v2/REPORT.md` §2.1）时，普通 CE 的最容易拟合路径是动作频率而不是状态条件。尖目标同时降低策略熵。greedy 评估可能变好而 sample 变差正是证据：v2 各臂 96 局 sample 均不超过 baseline $578.5$（最好 clip6+锚点 $562$，约 $-3\%$）；greedy 可有 $+9\%\sim+19\%$（`clip30+锚点` $677$，$+19\%$），但不可信为部署收益（同报告 §4）。v1 叶值头搜索 KL 仅 $0.011$、$\pi\approx$ base（top-1 一致 $99.2\%$，同报告 §2.2），说明“太软无信号”；v2 过尖又污染先验，存在中间信赖域而非“越像搜索越好”。

可检验判据：记录 entropy$(\pi_S)$、top-1 mass、KL 分位（p50/p90/p99）、top-1 一致率（及其补数“top-1 不一致比例”，**不称翻转率**）、$\hat Q$ 校准误差（按 Q 分位比较 rollout 后真实 $\Sigma$）、候选覆盖率、重要性权重 ESS，以及按动作类型/回合的行为频率。接受标准应包括：搜索标签 advantage 与实际回报相关；校准误差不随动作类型有符号偏差；蒸馏后 sample 与 greedy 同向；熵下降不超过预设阈值。

## 4. 可选正确算法族

### 4.1 Expert Iteration（ExIt）

在 learner 访问状态查询搜索专家，以软分布拟合：

\[
 \theta_{k+1}=\arg\min_\theta E_{s\sim d_{\pi_k}}
 \operatorname{KL}\big(\pi_S^{\pi_k}(\cdot\mid s)\,\|\,\pi_\theta(\cdot\mid s)\big)
 +\beta\,\operatorname{KL}\big(\pi_k\,\|\,\pi_\theta\big).
\]

前提是专家在同一状态分布上有正 surrogate 改进、候选覆盖且标签误差 $\epsilon_{distill}$ 小。若拟合误差每轮不超过 $\epsilon$、搜索改进余量为 $\alpha$，则有限 horizon 的**启发式**记账是“每轮净增至少 $\alpha-\epsilon$，并承受后续分布偏移项”（不是严格界，严格每轮界需 §2.2 的前提）；误差传播可粗略写为 $E_{k+1}\le L E_k+\epsilon$，$L$ 是搜索/环境对策略误差的 Lipschitz 常数。ExIt 适合本项目，但必须软标签、优势门控、KL 约束，不能把 top-1 当真值。

样本复杂度：若每状态动作分类误差方差为 $\sigma^2$，要把均方误差压到 $\epsilon^2$，约需 $O(\sigma^2/\epsilon^2)$ 个查询状态（再乘动作/实体覆盖）；2–5M decisions 足以做小轮验证，不足以宣称全局收敛。

### 4.2 DAgger 式聚合

第 $k$ 轮让当前 learner $\pi_k$ 实际走，按其访问分布 $d_{\pi_k}$ 查询 $\pi_S^{\pi_k}$，聚合历史 $(s,\pi_S)$，训练

\[
 \min_\theta E_{s\sim d_{mix}}\operatorname{KL}(\pi_S^{\pi_k}\|\pi_\theta).
\]

它修复 base 行为和 target 状态的分布失配；需要防止搜索错误随策略自噬，故混合 $\rho d_{\pi_k}+(1-\rho)d_{\pi_0}$、保存旧标签并做 holdout。样本成本为每个访问状态一次搜索，工程成本约每局 $2.3$ s（搜索 $2.26$ s/局；关键决策覆盖沙盒 $11.1\%$、完整面板 $11.5\%$，`docs/INFERENCE_SEARCH.md` §4.3）；可先每 N 个状态查询而非全量。

### 4.3 AWR/IQL/搜索 Q 的优势加权

对搜索 Q 形成

\[
 A_S(s,a)=\hat Q(s,a)-\sum_b \pi_{old}(b\mid s)\hat Q(s,b),\qquad
 w=\min\big(w_{max},\exp(A_S/\tau_A)\big),
\]

优化

\[
 L_{AWR}=-E\big[w(s,a)\log \pi_\theta(a\mid s)\big].
\]

只给正优势且按大小加权，能排除“搜索随机偏好”；IQL 形式可先拟合保守 $V$，再对 $Q-V$ 加权，适合离线数据但仍受叶值偏差/支持限制。样本复杂度通常比 hard BC 高，要求 Q 校准和 ESS 监控；本项目可行，rank-only 使它只能作为局部 shaping，不应冒充终局 rank。

### 4.4 KL 信赖域蒸馏

\[
 \max_\theta\; E_{s\sim d}\Big[E_{a\sim \pi_\theta(\cdot\mid s)}\hat A_S(s,a)\Big]
 \quad\text{s.t.}\quad
 E_{s\sim d}\operatorname{KL}\big(\pi_{old}(\cdot\mid s)\,\|\,\pi_\theta(\cdot\mid s)\big)\le\delta .
\]

**适用条件（用之前必须写明的四条）**

1. **有限 horizon / 吸收终止**：episodic、horizon $H$、终止状态吸收；$\gamma=1$ 时用平均回报 $J=\frac1H E[\sum_{t=0}^{H-1}r_t]$。无限 horizon 的 $1/(1-\gamma)$ 界在 $\gamma=1$ 发散，不能搬用。
2. **同支集（分类分布）**：$\pi_{old}$ 与 $\pi_\theta$ 在同一 masked 合法集 $A(s)$ 上都有正概率，$|A(s)|\le 274$（分类分布支集有限，故单状态 KL $\le\log|A(s)|$ 有界）。若某状态 $\pi_{old}(a\mid s)=0$ 而 $\pi_\theta(a\mid s)>0$，该状态 KL 为 $+\infty$，所有界失效；实现上只在 masked 支撑上算 KL，并对 $\pi_{old}$ 加平滑下限 $\epsilon_{smooth}$。
3. **区分 $\operatorname{KL}_{max}$ 与 $E[\operatorname{KL}]$**：
   - **逐状态一致界** $\operatorname{KL}_{max}:=\max_{s\in\mathcal S_{reach}}\operatorname{KL}(\pi_{old}(\cdot\mid s)\|\pi_\theta(\cdot\mid s))\le\delta$ 给**最坏情况**保证：对每个 $s$，Pinsker 给 $\operatorname{TV}(\pi_\theta,\pi_{old})\le\sqrt{\delta/2}$，有界优势下每步动作选择损失 $\le 2A_{max}\operatorname{TV}\le A_{max}\sqrt{2\delta}$，$H$ 步合计 $\le H A_{max}\sqrt{2\delta}$。
   - **期望界** $E_{s\sim d}\operatorname{KL}\le\delta$ 只给**平均情形**：由 $\sqrt{\cdot}$ 的凹性与 Jensen，$E_s[\operatorname{TV}]\le E_s\sqrt{\operatorname{KL}_s/2}\le\sqrt{E_s[\operatorname{KL}_s]/2}=\sqrt{\delta/2}$，动作选择项同样 $\le H A_{max}\sqrt{2\delta}$ —— 但允许个别状态 KL 很大。训练时必须同时报 p50/p90/p99 与 $\operatorname{KL}_{max}$，单状态超限直接拒绝该 minibatch。
4. **状态占用漂移不由 per-state KL 控制**：$J(\pi')-J(\pi)=\frac1H\sum_t E_{s_t\sim d_t^{\pi'}}[A_\pi(s_t,\cdot)]$ 里状态分布取 $d^{\pi'}$，而 per-state KL 只约束“同一个 $s$ 上的动作分布”，不约束“哪些 $s$ 会被访问”。要拿到全程界，需额外的均匀界（所有可达状态同一个 $\delta$）与占用测度漂移假设，或对 rollout 做 off-policy 校正；否则只能声称“局部动作选择损失受控”。

另注：$\hat A_S$ 是搜索 Q 的估计（含叶值偏差 $b$ 与 rollout 噪声），上述界只对 $\hat A_S$ 成立；接到真实 $J$ 还要加 §2.2 的 $2\epsilon_Q+\epsilon_C+\epsilon_S A_{max}$。KL 约束也不直接压 PPO/IS 的权重方差（$\pi_{old}$ 近 one-hot 时 $1/\pi_{old}$ 仍重尾），需另看 ESS 与权重分位（§4.5）。它正对“sell/refresh 先验抬升”和熵坍缩，是推荐的外壳。

### 4.5 搜索行为策略 + PPO（把行为策略 $\mu$ 写对）

“部分决策用搜索动作”要写成**决策级混合行为策略**：在关键决策以概率 $\varepsilon$ 用 $\pi_S$、以 $1-\varepsilon$ 用 $\pi_\theta$（非关键决策恒用 $\pi_\theta$）。实际采样分布是

\[
 \mu_{\theta_{old}}(a\mid s)=(1-\varepsilon)\,\pi_{\theta_{old}}(a\mid s)+\varepsilon\,\pi_S(a\mid s),
\]

即 $\mu=(1-\varepsilon)\pi+\varepsilon\,\pi_{search}$。

**$\mu$ 才是 behavior policy；$\pi$ 不是 on-policy 分布**，轨迹是从 $\mu$ 采出来的（搜索分支的概率质量必须显式记进 logprob）。

PPO 的重要性比必须用 $\mu$ 的 logprob 做分母：

\[
 r_t(\theta)=\frac{\pi_\theta(a_t\mid s_t)}{\mu_{\theta_{old}}(a_t\mid s_t)},\qquad
 L^{clip}(\theta)=E_{t\sim\mu}\Big[\min\big(r_t(\theta)\hat A_t,\ \operatorname{clip}(r_t(\theta),1-c,1+c)\hat A_t\big)\Big].
\]

- **不能用 $\pi$ 当 on-policy 分母**：若写成 $r_t=\pi_\theta/\pi_{old}$，梯度是 $E_{a\sim\mu}[(\pi_\theta/\pi_{old})\hat A]\ne E_{a\sim\pi_\theta}[\hat A]$，偏差随 $\varepsilon$ 与 $\operatorname{KL}(\pi_S\|\pi)$ 增大；只有 $\varepsilon=0$ 时才退化为普通 PPO。
- **方差**：$\mu\ge\varepsilon\pi_S$ ⇒ $r_t\le\pi_\theta/(\varepsilon\pi_S)$。$\pi_S$ 近 one-hot（`pi_argmax`）时搜索分支权重约 $1/\varepsilon$，IS 估计的二阶矩按 $1/\varepsilon^2$ 放大，有效样本量 $\mathrm{ESS}=(\sum_t w_t)^2/\sum_t w_t^2$ 随 $\varepsilon$ 下降。因此 $\varepsilon$ 不能太小（建议 $0.1$–$0.3$，且只放在关键决策上），逐 minibatch 报 ESS、权重分位与 $\max_t r_t$；要对 $w$ 截断时须同时报截断引入的偏差。
- **稀疏回报**：rank-only 终局奖励、$\gamma=1$、$H\lesssim16$，回报稀疏且高方差；用 GAE($\lambda=0.995$)、同 seed 配对（CRN）与大 batch 降方差，搜索分支 RNG 由 seed 派生以保可复现。
- **与其他路线的关系**：ExIt 直接拟合 $\pi_S$ 的分布（监督、低方差，但有分布失配与容量上限）；混合 PPO 直接优化 $\mu$ 产生的环境回报（无偏但高方差，自动包含状态分布改变与存活信号）。本轮先 ExIt/DAgger，第二阶段再开这条，不要同一轮同时改两个旋钮。

优点：自动包含状态分布改变与存活信号。缺点：每局成本高（搜索约 $2.3$ s/局 + PPO 采样）、rank-only 回报稀疏、搜索动作随机性使方差大、$\varepsilon$ 与 KL 两个超参耦合；可用更大的搜索覆盖比例与 CRN 配对降低方差，并把 $\pi_S$ 作为 $\mu$ 的**混合成分**（而不是“旧策略”或离线标签）写进轨迹记录。

### 4.6 联合价值学习

用 rollout return/盘面轨迹训练辅助 $V_\phi(s)$ 或 Q head，再以 PPO value loss + 搜索回报 loss 联合训练。必须将 $\Sigma$ 目标标为 shaping/auxiliary，禁止把它当 rank 真值；生存 mask、calibration 和 separate head 是必要条件。

## 5. 针对 HSBRSIM 的推荐方案

### 5.1 选择

推荐“**DAgger 状态覆盖 + 优势加权 ExIt + KL 信赖域**”，而不是先做全量 hard BC；第二阶段才尝试搜索行为 PPO。理由：标签尖（top-1 质量 $0.83$）且与 base top-1 只有 $45.3\%$ 一致（54.7% 的关键决策 top-1 不同；标签层面的“不一致比例”，部署翻转率未测量），必须软化；base 行为与搜索状态失配，必须让 learner 访问状态；t15 不可测且叶值仅盘面 $\Sigma$，必须只把搜索当局部 advantage，不可将标签当终局专家；rank-only 且高方差，KL 可防样本崩溃。

### 5.2 第一轮最小实验（2–5M decisions）

1. 从固定 checkpoint 启动，先采集 2M（上限 5M）learner 实际轨迹；其余决策按 base，关键决策查询 1 回合 rollout 搜索，保持 top-$k=8$、每回合最多 3 次、非 Move 候选。为验证跨回合信号，附加一个小 3 回合臂（48 局口径，`runs/search_labels_v2/REPORT.md` §5.1），但不混合两个 horizon 的标签。
2. 每个查询保存：完整 masked logits/合法集、$\pi_{old}$、$\pi_S$、所有候选 $\hat Q$、rollout $\Sigma_{end}$、回合/存活/最终 rank（可得时）、动作类型、搜索耗时。查询状态来自 $\pi_{old}$ 轨迹，另保留 20% holdout。
3. 目标分布先做温度软化（建议 $\tau_{distill}=2$）并裁剪优势 $c=3$ 或 6；只对 $\hat A>0$ 的候选做 $w=\exp(\operatorname{clip}(\hat A/\tau_A,-2,2))$，$\tau_A$ 取候选 Q std 的 1–2 倍；不以 argmax one-hot 训练。
4. 损失：

\[
 L=L_{PPO}+0.25L_{AW\text{-}ExIt}+0.10\operatorname{KL}(\pi_{old}\|\pi_\theta)
 +0.01L_{entropy}+0.05L_{value/\Sigma},
\]

其中 $L_{AW\text{-}ExIt}=-E[w\log\pi_\theta]$，系数以梯度范数归一化后再生效；KL 是显式 per-state trust region，目标平均 KL $0.02$、硬上限 $0.05$（越界回退该 minibatch；同时记录 $\operatorname{KL}_{max}$，见 §4.4）。entropy 系数以不低于 base entropy 的 90% 为监控下限，而不是固定追求高熵。
5. 每 $K=20$ 个 PPO iter 做一次蒸馏更新；每次只用 1–2 个 epoch、lr $1\times10^{-5}$（不超过现 PPO lr 的同量级），PPO 正常更新继续保留 90% 数据，蒸馏 batch 占 10%，并以 80% base/on-policy + 20% 搜索查询混合，逐轮将搜索占比最多升至 30%。
6. 搜索标签只在 advantage 置信度高时启用：候选 $\Sigma$ 差的 bootstrap/重复 rollout CI 不跨 0，或 $\hat A>q_{0.6}$；否则只作 base anchor。动作频率变化按类型设上限（sell/refresh 相对 base 不得单轮增幅超过 1.5 倍）。

### 5.3 “学回来了多少”

固定同一 checkpoint seed/seat 配对面板（256 局，与 §1 的 A/B 面板同口径），分别测无搜索 base（before）、训练后关闭搜索（after）和推理期搜索上界（search）。定义

\[
 \text{capture ratio}=\frac{\text{rank}_{after}-\text{rank}_{before}}
 {\text{rank}_{search}-\text{rank}_{before}}.
\]

由于 rank 越小越好，分子分母均通常为负，比例仍表示捕获的改善；报告每局配对 bootstrap 95% CI，并同时报告无条件 $E[\Sigma_t]$、生存率、top4、动作类型/熵/KL。第一阶段目标是 capture ratio $\ge50\%$（**阶段目标**，非首次硬门槛），且不能以 greedy 代替采样评测。

### 5.4 最小成功/失败判据

2–5M decisions 后，**关闭搜索**的训练后策略在同一 256 局配对面板相对 before 的 human mean-rank $\Delta\le-0.10$ 且 95% CI 上界 $<0$；capture ratio $\ge0.5$（阶段目标）；sample 与 greedy 同向；存活率和无条件 $E[\Sigma_{t12}]$ 不下降。若 rank 改善但 CI 跨 0、capture $<0.5$，延长 DAgger/提高覆盖而不加大标签尖度；若 sample 下降、KL p99 爆炸、sell/refresh 超限或存活率下降，立即回退到 old checkpoint/base anchor，减小 $c$、蒸馏系数和查询比例。若搜索本身的配对收益消失，则先修叶值/候选覆盖，不训练。

## 6. 风险与反例

- **搜索—策略共适应/自噬**：策略学到错误后，top-$k$ 和 rollout 都围绕错误候选；保留 frozen expert/base、历史 replay、固定 holdout，周期性重算搜索。
- **叶值偏差固化**：$\Sigma$ 高但存活/排名差时，训练会强化自杀式成长；分离 $\Sigma$ auxiliary head，加入存活 gate，按最终 rank 可得样本校准。
- **熵坍缩**：尖标签和大 KL 会让 sample 崩；监控 entropy、ESS、top-1 mass，trust region 超限即拒绝更新。
- **评测泄漏**：用搜索评测后宣称“策略变强”会混淆；所有 capture ratio 的 after 必须关闭搜索，另报 search 上界。
- **算力成本**：搜索约 $2.26$ s/局（另加基线推理，256 局墙钟 $843$ s $\approx3.3$ s/局），故只查询关键决策、每回合最多 3 次，先做 2M；不能为了蒸馏无限调用搜索。
- **t15 反例**：256 局 human 面板 0 局进入 t15 统计（t14 仅 2 局），任何 t15 结论都只能来自沙盒或新生存分布，不能当当前主验收指标。

## 7. 路线图

**阶段 1（2–5M decisions）**：DAgger learner 状态、1 回合搜索、优势加权 ExIt + KL；目标 capture $\ge50\%$（阶段目标），关闭搜索配对 CI 过零门槛。
**阶段 2**：对高潜力/跨回合动作增加 3 回合叶值，只在候选 Q 校准通过的状态查询；混合搜索行为 PPO 小比例 on-policy（§4.5 的 $\mu$ 口径），目标减少 value/rank mismatch，并将 capture 推向 70%。
**阶段 3**：按“关键决策价值”学习 search gate；蒸馏后从每个关键点搜索降到只在高不确定性、carrier/spell、跨回合复利点搜索，验证降预算后仍保持至少 50% capture，再考虑部署默认降到 t1。

降低预算的条件不是训练 loss 下降，而是关闭搜索策略在固定配对面板达到目标、search/no-search 差距稳定、且无条件存活/$\Sigma$ 指标不退化；否则保留推理期搜索。

## 一句话结论

先做 **2–5M decisions 的 learner-DAgger + 优势加权软 ExIt + 平均 KL 0.02（硬上限 0.05、每 20 个 PPO iter 一次）**，用 1 回合 top-8 搜索标签并严格关闭搜索验收，要求 mean-rank $\Delta\le-0.10$、95% CI 上界 $<0$ 且 capture ratio $\ge50\%$（阶段目标），失败即回退并减小标签尖度/覆盖比例。

## 审校记录

本次终审（2026-11-01）只改本文件，未跑训练、未占 GPU。修正 5 项（行号均为本版最终行号）：

| # | 修正 | 位置（本版行号） |
|---|---|---|
| 1 | 公式残留清理：原文**没有**控制字符前缀（0x1B，检索 0 处），也**没有**两个连续的反斜杠（检索 0 处）；实际残留是无效控制序列与裸符号 —— 反斜杠 + α（2 处）、反斜杠 + O、反斜杠 + TV、反斜杠 + 0.02/0.05（2 处），共 6 处；另有裸 β 1 处、裸 δ 3 处。已改为 `\alpha`、`O`/`\operatorname{TV}`、`0.02`/`0.05`、`\beta`/`\delta`，并补 `\arg\max_a` 的下标、`\mathrm{atk}` 与 `\Sigma_{\mathrm{end}}` 的运算符写法。 | L29、L72、L153、L156、L197–L204、L254 |
| 2 | “搜索行为 PPO”改写：行为策略写成 $\mu=(1-\varepsilon)\pi+\varepsilon\,\pi_{search}$；ratio $r_t(\theta)=\pi_\theta/\mu$ 与 clipped 目标显式用 $\mu$ 作分母；补“用 $\pi$ 作分母有偏”的推导、$1/\varepsilon$ 权重上界、$1/\varepsilon^2$ 方差放大与 ESS 监控；删除“把 $\pi_S$ 当旧策略/离线标签”的错误表述。 | L206–L230 |
| 3 | KL 界条件显式化：有限 horizon/吸收终止、$\gamma=1$ 不能用 $1/(1-\gamma)$、分类分布同支集（$\lvert A(s)\rvert\le274$，$\pi_{old}$ 需平滑）、逐状态 $\operatorname{KL}_{max}$ 与期望 $E[\operatorname{KL}]$ 分开（Pinsker 给 $\operatorname{TV}\le\sqrt{\delta/2}$，每步损失 $\le2A_{max}\operatorname{TV}\le A_{max}\sqrt{2\delta}$，$H$ 步合计 $\le HA_{max}\sqrt{2\delta}$）、状态占用漂移不受 per-state KL 控制。 | L187–L204 |
| 4 | 数字引用更正：$45.3\%$ 是 $\pi_{search}$ 与 $\pi_{base}$ 的 **top-1 一致率**（8,989 个关键决策，`runs/search_labels_v2/REPORT.md` §2.2），不是翻转率；报告没有按“翻转率/被改变决策比例”的定义统计该量 ⇒ 标注**未测量**（只给出“54.7% 关键决策 top-1 不同”与被换动作类型分布）。另注推理搜索 `switch_rate` $32.6\%$（256 局，`runs/infer_search_ab/AB_SUMMARY.json`）分母不同、不可互换。 | L130–L132、L240 |
| 5 | 样本口径统一：**256 局** = 推理搜索 A/B（同 seed 面板，seed_base 420000）；**96 局** = 沙盒强度/存活 + 离线 BC（gold10，seed 区 970000+/910000）；**48 局** = 3 回合深度；t15 改为“256 局面板 0 局进入 t15 统计（t14 仅 2 局）”，不再写“200 局有 256/256 死亡”。正文逐处标注来源文件/小节。 | L20–L25、L27、L37、L108、L130、L140、L271、L280 |

**发现的其他不一致（已一并修正或标注）**

1. **$\hat A$ 的基线口径与实现不符**：原文用重加权后的 $\tilde\pi$ 做基线；`hsbg/az/train/sandbox_rollout.py::pi_from_q` 实际用 $\tilde p$（$\pi$ 在候选上的归一化，$V=\sum\tilde p\,Q$）。已改为 $\hat A=\hat Q-\sum\tilde p\,\hat Q$ 并显式定义 $\tilde p$（L59–L64）。
2. **“关键决策覆盖率 11.1%”与完整面板 11.5% 是两套口径**：11.1% 是沙盒 8,989/81,039（`runs/search_labels_v2/REPORT.md` §2.1），11.5% 是完整游戏 18.96 次/局（`docs/INFERENCE_SEARCH.md` §4.3）；原文只写 11.1% 却用于完整游戏成本论证，已分开标注（L140、L168）。
3. **“约 2.3 s/局”只是搜索耗时**：256 局墙钟 $843$ s $\approx3.3$ s/局（含基线推理）；原文把它当整局成本，已改为“搜索约 2.26 s/局 + 基线推理”（L168、L279）。
4. **任务书“96 局（`docs/CARRIER_SCALING.md`、`docs/SCALING_SIGNAL.md` 口径）”与仓库事实不符**：这两份文档的强度/存活观测是 **200 局**（`docs/CARRIER_SCALING.md` §3.2 教师/基线各 200 局；`docs/SCALING_SIGNAL.md` §2 主 arm 200 局，1x 下 61/200 活到 t12、t15 仅 3 局）；96 局来自 `runs/search_labels_v2/REPORT.md` §3–§4 与 `docs/ECONOMY_SANDBOX.md`。本版把 96 局标注为 REPORT/ECONOMY 口径，200 局单独列为交叉参照并注明不与 256/96 混用（L20–L32）。若后续要以 200 局为主口径，需另起一节并重跑对齐。
5. **`switch_rate` 与 top-1 一致率易混**：前者是完整游戏搜索实际覆盖 $\pi_{base}$ 动作的比例（分母 = 被搜索决策），后者是沙盒标签 top-1 一致率（分母 = 8,989 个关键决策）；已在 §3.2 加注说明不可互换（L132）。
