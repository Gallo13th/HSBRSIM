# 专家轨迹注入的可识别性、不可采样极端条件与解法

> 本文是**只读理论分析**，不训练、不占用 GPU。目标是先回答“模型根本采样不到专家路线时，奖励是否有意义”，再给出可验证、可实现的注入方案。

## 1. 事实与形式化设定

### 1.1 环境：MDP 与 POMDP

把单局 AutoTavern 视为有限时域 MDP
\[
\mathcal M=(\mathcal S,\mathcal A,P,\rho_0,r,T),
\]
其中状态 \(s_t\in\mathcal S\) 包含棋盘、手牌、商店、金币、等级、玩家级计数器及随机数状态；动作是 AutoTavern 245 维离散动作（实际训练栈另有 245..273 的扩展段，但本文“245 维动作”指核心动作空间），合法动作掩码记为 \(m(s)\)。转移 \(P(s'\mid s,a)\) 包含招募、战斗和随机事件。一个 episode 最多至终局，令 \(T\) 为终止时间（8 座对局中对某一 learner 而言通常是有限的，但不假设固定长度）。

真实环境有隐藏商店池、脚本 counter、其他玩家信息等，因此更准确是 POMDP
\[
\mathcal P=(\mathcal S,\mathcal A,P,O,\Omega,r,T),
\quad o_t\sim\Omega(\cdot\mid s_t).
\]
策略应写成历史策略 \(\pi(a_t\mid h_t)\)，或以信念 \(b_t=P(s_t\mid h_t)\) 为输入的 \(\pi(a_t\mid b_t)\)。实现中的观测网络把历史/信念编码为特征；以下为简洁仍写 \(s_t\)，所有结论对 \(h_t\) 或 \(b_t\) 逐点成立。

奖励只有终局名次效用：
\[
r_t=0\;(t<T),\qquad r_T=U(\operatorname{rank}),
\qquad \gamma=1.
\]
策略为 \(\pi_\theta(a\mid s)\)，并严格满足合法掩码。轨迹
\(\tau=(s_0,a_0,\ldots,s_T)\) 的概率为
\[
P_\pi(\tau)=\rho_0(s_0)\prod_{t=0}^{T-1}
\pi(a_t\mid s_t)P(s_{t+1}\mid s_t,a_t).
\]
占用测度（有限时域版本）为
\[
d^\pi_t(s)=P_\pi(s_t=s),\qquad
\bar d^\pi(s)=\frac1{\mathbb E_\pi[T]}
\mathbb E_\pi\left[\sum_{t<T}\mathbf1\{s_t=s\}\right].
\]
优化目标是
\[
J(\theta)=\mathbb E_{\tau\sim P_{\pi_\theta}}[U(\operatorname{rank}(\tau))]
=\mathbb E\left[\sum_{t=0}^{T}\gamma^t r_t\right].
\]
在可交换微分、支持不随参数突变且概率为正的条件下，策略梯度为
\[
\nabla_\theta J=\mathbb E_\pi\left[\sum_{t<T}
G_t\nabla_\theta\log\pi_\theta(a_t\mid s_t)\right],\quad G_t=r_T.
\]
\(\lambda=0.995\) 仅是 GAE/trace 的估计参数，不改变上述真实目标。

### 1.2 与仓库事实对齐

[阶段强度表](../runs/plots/strength_stages.md) 显示，真实 10k+ 的强度 p50 在 t12/t13/t14/t15 为 **4,458/9,666/21,136/26,516**，而 s14@70M 为 **566/664/749/821**，强度比为 **0.127/0.069/0.035/0.031**；s8--s14 在 t12 后均停留在约 0.13--0.15、0.07--0.09、0.035--0.044、0.031--0.038。s14 配置中 5 席人类战团（\(p=0.9\)）加 2 席镜像下，实测 **64/64 局 learner 在 t13 前出局**，因此该批经验占用测度在 t14/t15 为零；总体概率不一定为零，统计上界见§7.1。

已有数据规模为 13,120 行 10k+ 观测、5,000+ 局 Firestone 回放（10,811 帧、149,166 动作）及 308,944 条 BC 样本；直接以人类轨迹 BC 曾失败，说明问题不是“没有标签”，而是 \(d^{\rm human}\) 与 \(d^\pi\) 错配。[状态保真度审计](FIDELITY_INJECTION.md) 还明确记录了真实观测缺 gold/shop/隐藏量，不能把完整人类轨迹无损搬入引擎。

## 2. 极端条件的精确定义

### 2.1 支持与专家轨迹

策略支持集定义为
\[
\operatorname{supp}(\pi_\theta)=\{(s,a):d_t^{\pi_\theta}(s)>0,\ \pi_\theta(a\mid s)>0\text{ for some }t\}.
\]
对固定专家路径 \(\tau^*=(s_0^*,a_0^*,\ldots,s_H^*)\)，其可采样概率为
\[
P_\pi(\tau^*)=\rho_0(s_0^*)\prod_{t=0}^{H-1}
\pi(a_t^*\mid s_t^*)P(s_{t+1}^*\mid s_t^*,a_t^*).
\]
若环境转移含连续随机量，应将“精确路径”替换为半径 \(\delta\) 的 tube \(B_\delta(\tau^*)\)，以下概率均指该 tube 概率。

称存在**采样极端条件**，若存在专家轨迹 \(\tau^*\) 及 \(\Delta>0,\epsilon\ll1\)，使
\[
J(\tau^*)-J(\pi)\ge\Delta,\qquad P_\pi(\tau^*)\le\epsilon.
\tag{E}
\]
若 \(\tau^*\notin\operatorname{supp}(P_\pi)\)，则称为**严格不可采样**。若每一步专家动作至少被压到 \(q<1\)，则
\[
P_\pi(\tau^*)\le \rho_0(s_0^*)P_{\rm env}(\tau^*)q^H,
\]
即随关键决策步数指数衰减。达到一次置信度 \(1-\alpha\) 的成功观测所需样本数满足
\[
N\ge\frac{\log\alpha}{\log(1-P_\pi(\tau^*))}
\approx\frac{\log(1/\alpha)}{P_\pi(\tau^*)};
\]
若 \(P_\pi\le q^H\)，样本复杂度至少为 \(\Omega(q^{-H}\log(1/\alpha))\)。这就是“奖励再好也等不到该回报”的可计算含义。

### 2.2 为什么奖励不能修复支持缺口

对 on-policy Monte Carlo，估计量为
\[
\hat g=\frac1N\sum_i\sum_tG_t^{(i)}\nabla\log\pi(a_t^{(i)}\mid s_t^{(i)}).
\]
若专家路径在当前策略支持之外，则其事件概率为零，样本中永不出现；即使该路径回报最大，\(\hat g\) 对该路径的贡献恒为 0。若把动作硬 mask 为概率 0 且 mask 在参数邻域内不变，则 \(\nabla_\theta\pi(a^*\mid s^*)=0\)，严格地说该方向梯度不可识别；若不是硬零而只是概率 \(p\) 极小，重要性权重含 \(1/p\)，二阶矩通常按 \(1/p\) 爆炸，方差在 \(p\to0\) 时无穷。

势函数 reward shaping
\[
r'_t=r_t+\gamma\Phi(s_{t+1})-\Phi(s_t)
\]
在终端势为 0、\(\gamma=1\) 时沿每条已访问轨迹望远镜为 \(R'=R-\Phi(s_0)\)，故不改变最优策略排序。它只能改变**已经采到的状态**的方差/信用分配，不能改变 \(P_\pi(\tau^*)\)，也不能把零概率动作变为正概率。若手工 shaping 依赖“专家相似度”并改变排序，那已经是新增行为监督/任务目标，不再是势函数不变性保证下的 reward-only 修复。

## 3. 在本数据上的可操作判定

设专家数据按回放切成 t 到 t+3 的窗口 \(W_e\)，并用同一观测编码器/合法动作掩码。所有估计应按**对局或帧 cluster** bootstrap，不能把同一局帧当独立样本。

1. **专家状态密度覆盖**：训练 \(d^\pi_t\) 的状态密度模型（或 kNN 半径质量）\(\hat p_\pi(s)\)，在专家状态求
\[
C_{\rm state}=\frac1n\sum_i\mathbf1[\hat p_\pi(s_i^e)\ge\eta],\quad
\mathrm{OOD}_\eta=1-C_{\rm state}.
\]
离散/哈希状态用计数平滑 \((n_s+\alpha)/(N+\alpha|S|)\)；连续特征用 kNN 距离阈值，阈值在 learner holdout 的 95% 分位预先固定。报告 cluster-bootstrap 95% CI。

2. **专家动作 KL/交叉熵**：在可比状态计算
\[
D_{KL}(\pi_E\|\pi_\theta)(s)=\sum_{a\in A(s)}\pi_E(a|s)\log\frac{\pi_E(a|s)}{\pi_\theta(a|s)},
\quad
\mathrm{NLL}_E=-\frac1n\sum_i\log\pi_\theta(a_i^e|s_i^e).
\]
单一专家动作定义 point-mass 经验分布，但不是对真实多模态专家 KL 的无偏估计；对不合法动作先剔除并记录。动作支持覆盖率
\[
C_{\rm act}=\frac{\sum_i\mathbf1[\pi_\theta(a_i^e|s_i^e)>\eta]}n
\]
直接给出“标签能否被当前策略产生”的比例。

3. **三回合成长路径可行性**：对每个 t→t+3 专家窗口，以 learner 策略独立 rollout K 次，从可比注入状态开始，定义
\[
\hat p_3=\frac1K\sum_{k=1}^K\mathbf1[\text{存活至 }t+3\land
S_{t+3}\ge S^e_{t+3}\text{（或达到目标比率）}].
\]
其二项 Wilson 95% CI（若成功数为 0，Clopper--Pearson 上界约为 \(1-\alpha^{1/K}\)）比单步动作概率更接近问题本质。

4. **轨迹支持覆盖率**：三回合不是三动作。令窗口内全部微决策数为 \(H_i\)，计算 \(\ell_i=\sum_{j=0}^{H_i-1}\log\pi_\theta(a^e_{i,j}|h^e_{i,j})\)、\(q_i=e^{\ell_i}\)、几何平均 \(e^{\ell_i/H_i}\)。这是**固定外生状态序列上的动作似然乘积**，不是包含转移概率的完整路径概率；只有用引擎恢复并 rollout 才能估计真实 \(p_3\)。报告 \(\Pr(q_i>\eta)\)、全体可审计窗口分母、合法/非法/语义不可对齐/缺观测各类别及其整局 bootstrap CI；单一步非法不能自动证明策略缺陷，可能只是错误重演。严格零概率须由 mask/守卫/图不可达证明，浮点下溢须用 log-softmax 排除；软阈值覆盖只叫“预算意义有效支持”。低覆盖与低 p3 只支持稀有性，仍需独立验证 Δ。

## 4. 解法族及保证

### (a) 专家轨迹注入与 DAgger

在 learner 访问的 \(s\sim d^{\pi_i}\) 上查询专家标签 \(a_E\)，以混合策略
\[
\pi_i^{\rm roll}=(1-\beta_i)\pi_i+\beta_i\pi_E
\]
采集聚合数据并用 no-regret 学习器拟合。令 \(C\) 为代价，\(\varepsilon=\mathbb E_{\bar d^{\hat\pi}}\mathbf1[\hat\pi(s)\ne\pi_E(s)]\)，假设一次错误动作相对专家的 **cost-to-go disadvantage** 至多 \(u\)，则 performance-difference 展开给出
\[
C(\hat\pi)-C(\pi_E)\le uT(\varepsilon_{\rm class}+\varepsilon_{\rm regret}+\varepsilon_{\rm query})+2c_{\max}T^2\bar\beta.
\]
这里以固定最大决策时域 T 表示，\(\bar\beta\) 是训练混合占比，分布 TV 耦合给出保守混合项；随聚合轮数增大需退火使其消失。**O(Tε) 要求 u=O(1)**；只有每步代价有界时 u 可为 O(T)，不能无条件宣称线性界。本任务终局效用范围 \(R_U=U_{max}-U_{min}\) 有界，因此 u≤R_U。最近邻标签的查询误差还需加 \(\varepsilon_{\rm query}\le\varepsilon_E+L\mathbb E\|z-z_{NN}\|+\varepsilon_{hidden}\)，前提是动作语义可对齐且 oracle 在所选表示中满足局部正则性，否则没有此界。足够条件是 learner 真正进入待修复状态、查询错误小、可执行标签合法、策略类可拟合且后续能回到正常起始分布；离线人类 BC 不满足这些条件，不能套 DAgger 保证。

### (b) 轨迹级 IS、V-trace、Retrace、DICE

行为策略 \(\mu\) 采到轨迹、目标策略 \(\pi\) 校正时
\[
\rho_{0:H-1}=\prod_t\frac{\pi(a_t|s_t)}{\mu(a_t|s_t)},\qquad
\hat J_{IS}=\frac1N\sum_i\rho_iR_i.
\]
无偏需要绝对连续性 \(P_\pi\ll P_\mu\)、同一转移核及初始分布（不同则需连同它们校正）；有限方差还需 \(\mathbb E_\mu[\rho^2R^2]<\infty\)。若每步比值≤c，\(|R|≤R_{max}\)，则方差上界为 \(R_{max}^2c^{2H}/N\)，**是可能指数增长的上界，不是必然的下界**。直接截断整轨迹权重时偏差≤\(R_{max}\mathbb E_\mu[(\rho-C)_+]\)。V-trace 的 TD 系数 \(\bar\rho_t=\min(\rho_t,\rho_{max})\)、trace 系数 \(c_t=\min(\rho_t,c_{max})\)，有限截断通常改变其评价策略；Retrace 的 \(c_t=\lambda\min(1,\rho_t)\) 配合目标策略 Bellman TD，在表格、覆盖和精确期望条件下仍以 \(Q^\pi\) 为不动点，**并非一切 trace 截断都导致渐近偏差**。DICE 用 \(w_t=d_t^\pi/d_t^\mu\) 满足有限时域流守恒约束以避免长轨迹权重，仍要求覆盖、可识别性和函数类充分；γ=1 应用有限时域/吸收终止版本，不能直接套折扣平稳公式。专家策略自身提供新数据可扩大行为支持，但 IS 校正本身不会造出未采到的轨迹；准重演改变转移核时，仅动作比值不再足够。

### (c) 搜索引导的 policy improvement

在可恢复状态以 PUCT 进行有限预算搜索，得到访问分布
\[
q_N(a|s)\propto N_N(s,a)^{1/\tau},
\]
以 \(L_{search}=\mathrm{CE}(q_N,\pi_\theta)\) 蒸馏（价值头同时回归搜索/终局值）。若搜索在一个状态找到专家质量路径的概率为 \(p_{find}(B)\)，预算为 B，则 K 个独立根搜索漏检概率为 \((1-p_{find}(B))^K\)，达到 \(1-\alpha\) 发现概率需 \(K\ge\log\alpha/\log(1-p_{find})\)。蒸馏只能保证“搜索标签被学到”而不能保证真实专家存在：搜索模型错误、隐藏状态错误、动作分支爆炸或路径仍被硬 mask 时均失败。AlphaZero 式方法因此适合作为注入后的局部 improvement，不适合作为缺少可执行状态的第一步。

### (d) 奖励无关探索与自动课程

PAIRED/ADR 通过生成器选择能区分 learner 与参考的任务，Go-Explore 维护 archive 并从稀有 cell 返回、恢复后探索；形式上改变行为分布，使某个 cell \(C\) 的访问概率从 \(p_C\) 提升为 \(q_C\)。覆盖一次的期望代价从 \(1/p_C\) 降至 \(1/q_C\)，但需支付 archive、reset/checkpoint、环境随机性控制和生成器偏差成本。它能覆盖稀有状态的条件是：状态可复位、cell 可识别、探索动作仍有正概率；对缺 gold/shop/隐藏量的不可忠实重演，探索只会覆盖“近似环境”而非真实专家状态。

### (e) LLM 作为专家

令文本化观测为 \(x=f(o,h)\)，LLM 输出动作分布 \(\pi_L(a|x)\)。可把它当 noisy oracle：\(P(a_L\ne a^*|x)=\epsilon_L(x)\)，并加入非法率 \(\epsilon_{illegal}\)、幻觉/缺字段率 \(\epsilon_{hall}\)。LLM 错误可能相关，也可能被去噪学习超越，不能把 oracle 错误当 learner 必然下界；有 H 次查询时至少一次错误的概率由 union bound 上界为 \(\sum_{j<H}\epsilon_{L,j}\)，不是把三回合误当三次动作后相乘。因此必须先做 schema 约束、合法动作投影、拒答与置信度校准；LLM 不会凭文本制造缺失的商店/隐藏状态，也不应被称为 ground-truth expert。

## 5. 针对 HSBRSIM 的具体推荐

### 5.1 构造 t→t+3 可执行重演

第一版不要声称“完整重演”。从每局人类回放选取有 board 的 t→t+3 战团增长窗口，保存 `board_problems` 同风格的题目行：`schema/version`、`state/obs`、`cards`、`legal_mask`、`turn`、`actions`、`seed`、`target_strength_before/after`、`source_game/frame` 和 `availability`。起点先用现有 `inject_quasi_state`：board + hand + tier，gold/shop 保持当前引擎局面；若 payload 有可信近似 gold/shop 才覆盖，否则显式标 `unavailable`，绝不填零冒充真值。按窗口验证三回合内每个实体 eid、pool、pending_choice、ended_turn 和合法动作掩码；失败窗口丢弃并计数。

[状态保真度审计](FIDELITY_INJECTION.md) 已证明：13,120 行中 4,498 为 EOT，去重后 1,961 准完整行；gold、shop、每随从 script counter、共享池差量不可得。故推荐 `fidelity=full` 仅用于字段真实可得的准完整帧，实际训练默认保守 `board`/`hand`，并报告不可得率。

### 5.2 BC + DAgger + 搜索标签组合

推荐三阶段而非一次混合：

1. **离线筛选/BC warm start**：只在支持不足开关为真时监督，
\[
L_{BC}=\frac{\sum_i w_i\,\mathbf1[\hat p_i<\eta]
[-\log\pi_\theta(a_i^E|s_i)]}{\sum_iw_i},
\quad w_i=\operatorname{clip}(\exp(-\text{OOD}_i),w_{min},w_{max}).
\]
与 PPO 损失组合 \(L=L_{PPO}+\alpha_{BC}L_{BC}\)，\(\alpha_{BC}\) 从小值线性退火到 0；这样不对已充分覆盖的普通状态重复拟合。

2. **DAgger 注入**：每个 learner 访问且 \(\hat p_3<\eta_3\) 的状态，注入可执行的当前状态的搜索或人工 oracle（人类近邻只提供候选），混合 \(\beta_i\) 从较大值退火；近邻必须通过 3 回合可行性审计，否则只作 OOD 负例，不作动作标签。

3. **搜索标签**：对注入后状态运行 PUCT，只有搜索达到目标改善且访问质量置信度超过阈值才用 \(L_{search}=\mathrm{CE}(q_N,\pi)\)；与 BC 二选一冲突时优先搜索标签，因它在当前状态而不是离线人类状态上产生。

建议配置接口（默认全部关闭、逐位等价现状）：

```text
--expert-injection-enabled false
--expert-injection-data <jsonl>
--expert-injection-prob 0.0
--expert-injection-fidelity board|hand|full
--expert-injection-mode bc|dagger|search|hybrid
--expert-injection-bc-coef 0.0
--expert-injection-dagger-beta 0.0
--expert-injection-support-threshold <eta>
--expert-injection-path-threshold <eta3>
--expert-injection-search-budget 0
--expert-injection-focus-turns 12-15
--expert-injection-max-per-game 1
```

schema 可复用 `board_problems`：新增 `expert_window_id`、`source`、`availability`、`expert_action`、`expert_action_prob`、`support_metrics`，旧 reader 遇未知字段忽略。单测必须包括：默认关闭时同 seed 的 `state_json`/RNG/动作逐位相等；合法 mask 与动作维度；注入失败原子性；三回合 reset 可复现；支持阈值开关；BC mask 后梯度只来自选中样本；搜索标签不含非法动作；数据泄漏按 `source_game` 分组切分。

### 5.3 成功判据与最小实验

强度比目标以 s14 当前 t14/t15 **0.035/0.031** 为基线，分阶段设为：相对提升 **+10%**（0.0385/0.0341）、**+50%**（0.0525/0.0465），长期门槛为两回合均达到 **0.15**、再均达到 **0.30**；所有阶段还必须满足 human panel 不劣化（预先规定置信区间下界或非劣检验，不能只看 learner）。

最小验证必须先**离线、不训练**：在固定留出人类窗口上计算 OOD、\(C_{act}\)、\(\hat p_3\)、轨迹支持率及 cluster-bootstrap/二项 CI；回答“专家路径在 learner 支持集外的比例”后再决定注入。只有确认缺口且状态可执行，才另行批准做 40--60 iter 的既有训练栈 A/B：A 为默认 PPO，B 为使用前缀到后期 reset 课程、只在 support 不足时监督的低系数 hybrid；固定 seed、相同人类注入 RNG、同评估集，比较 t13 生存率、t14/t15 强度比、panel、合法率和注入拒绝率。

## 6. 风险、反例与停止条件

* **状态重演不可行**：缺隐藏量时 board 相同不等于 MDP 状态相同；若三回合可行性/一致性审计失败，应退回搜索或只做 board 题目，不能把伪轨迹当专家。
* **专家偏差**：curated perfect games 不是随机天梯分布；必须按来源、版本、tier、turn 分层留出，并监控 panel 不劣化。
* **固定解过拟合**：固定 t12--15 或近邻会学到 replay fingerprint；随机 seed、动作扰动、多个来源和 held-out game 是必要条件。
* **LLM 幻觉**：文本缺字段、非法动作和理由看似合理；动作必须 schema/合法 mask 投影，拒绝高不确定输出。
* **评估泄漏**：同一 Firestone game 或其近邻不可同时进注入训练和评估；按整局分组切分，搜索也不能读取评估终局标签。
* **IS 误用**：任何行为策略未覆盖的动作不能用无限权重“校正”；应显式报告 support violation。
* **面板退化**：专家监督可能提升极端局面却破坏早期经济策略；任何 A/B 以 panel 非劣化为硬约束，必要时只开启 OOD gate。

## 7. 必须限定的推导与可执行协议

### 7.1 概率、效用与证据强度

上述轨迹记号中的 \(J(\tau^*)\) 应理解为专家续行方案在同一初始状态分布和同一随机环境下的**期望终局效用**，不是从一条幸运回放推断期望值。所有理论在固定对手策略/人类注入规则下成立；对手随训练更新时逐轮冻结讨论。有限长度证明可取实现的最大微决策数 \(T_{max}\)，或对终止时间尾部单独给界，不能把“回合 t15”当成 15 次动作。

\(\epsilon\) 与 \(\Delta\) **没有无需假设的函数关系**。给出一个可操作联合条件：若奖励范围为 \(R_U\)，预算 N、漏检容忍概率 α、目标增益分辨率 Δ，则要求
\[
P_\pi(E)\le\epsilon\le\min\{\alpha/N,\Delta/(2R_U)\},\qquad J(\pi_E)-J(\pi)\ge\Delta.
\]
由 union bound，N 次 rollout 命中 E 的概率≤Nε≤α；两个仅在 E 内相差至多 \(R_U\) 的奖励机制，在当前策略期望上差≤εR_U≤Δ/2，而离线 oracle 改变行为后可获得 Δ。H 个必要瓶颈每步条件成功率≤q 时，\(\epsilon\le q^H\)；若有 M 条候选路线，上界应为 \(Mq^H\)，**一条精确序列罕见不代表所有好路线罕见**。检验应使用增长目标事件 E，而非只盯单条动作字符串。

64/64 在 t13 前出局对应 \(\hat P(\mathrm{alive}_{13})=0\)。若独立同分布局，单侧 95% Clopper--Pearson 上界为 \(1-0.05^{1/64}\approx4.57\%\)（由实测样本数推导），不等于真概率零；t14/t15 存活是其子事件。名次面板 6.223（基线 6.445）、γ=1、λ=0.995、64 局和 BC 失败取自本次用户实测事实；面板变化不推出增长路径有 Δ 的名次增益。场面强度 S 与 U 不是同一目标，强度高却输掉对局是直接反例。强度图评估分布不必等于这 64 局训练分布，不能把二者当同一采样池。

### 7.2 “梯度为零”的准确版本与 shaping 的边界

设 \(g_E=\mathbf1_E R\sum_t\nabla\log\pi(a_t|h_t)\)。若 Pπ(E)=0，则 \(g_E=0\) 几乎处处；**整个 \(\nabla J\) 不必为零**，其他有奖路径、共享参数仍会更新。例：三个动作概率为 (p,1−p,0)，奖励为 (1,0,2)，第三动作不可达但 J=p 的梯度不为零。若所有访问路径回报相同且采用精确 baseline，则期望优势梯度为零；硬零在参数邻域保持时支持缺口不能被这种更新修复。有限 logit softmax 对合法动作通常严格为正，不能把数值小当硬零。

重要性采样目标对 E 的质量为 q、行为质量为 p 时，指示收益估计量 \(q\mathbf1_E/p\) 的方差为 \(q^2(1/p-1)\)；p→0 才发散，p=0 时根本没有合法的 RN 导数，不能声称存在无偏有限方差估计。原生 on-policy 梯度对固定有限参数和有界 score 可有有限方差，只是稀有信号的相对误差很大。

势函数不变性**没有数学失效**：正确终端势为零时定理仍成立，失效的是把“保持最优策略”推成“必然发现最优策略”。原有文字“不能改变路径概率”仅指固定 θ 的采样分布；近似 critic/GAE 下 shaping 可改变优化进程并提高以后有限概率路径的访问率，但不能改变引擎不可达或固定硬 mask。截断 episode 的终端势不消去、状态混叠、非势型奖励均需另论。

### 7.3 估计细节与审计类别

状态占用报告必须分为 \(a_t=P(\mathrm{alive}_t)\) 与 \(d_t(s|\mathrm{alive})\)，否则只统计幸存者会掩盖早死。精确状态几乎不会重复，kNN 指标是表示空间的**近邻质量**而非全状态密度；预先冻结 turn/tier/board/hand 特征和尺度，bootstrap 连同阈值拟合一起重采样。动作 KL/NLL 按整局 bootstrap；把非法/未知标签从条件 KL 分母剔除后，另报全样本缺失率，禁止隐藏失败。合法动作的真零给 KL=∞，另报零质量率，不能靠加 epsilon 宣称有限 KL。重复独立 rollout 的二项 CI 需使用实际独立随机 seed，恢复同一个 RNG 反复执行不是重复试验；跨窗口同源时用整局 bootstrap。零次成功的单侧上界为精确 \(1-\alpha^{1/K}\)，若想认证 \(p_3≤p_0\)，预先选 \(K≥\log\alpha/\log(1-p_0)\)；多窗口检验做 Bonferroni 或报告整体 bootstrap 区间。

离线审计输出五类比例及区间：可执行且被证明硬零；可执行但低有效支持；可执行且覆盖；状态不可构造；缺动作/历史无法判断。分母同时报全部窗口与可判定子集。有限样本不能直接估计数学 support 的全部外部比例，后三类不得算作“已证明 support 外”。

### 7.4 搜索与蒸馏的条件复杂度

搜索找到可执行策略不等于蒸馏成功。若在冻结根分布上有 n 个独立标签、有限假设类 \(\mathcal H\)、可实现无噪声分类，则一致学习器达到错误率≤ε所需
\[
n\ge\frac{\log|\mathcal H|+\log(1/\delta)}{\varepsilon}.
\]
推导：错误率>ε的模型避开 n 个错误点概率≤exp(−nε)，再 union bound。有噪声的 bounded-loss 泛化一般为 \(O((\log|\mathcal H|+\log(1/\delta))/\varepsilon^2)\)，CE 需截断/限制概率使损失有界；神经网络需相应容量复杂度，不能把该公式当现网预算承诺。H 步闭环 rollout 在其自身状态分布错误≤ε时，路线失效概率≤Hε；若仅在老师状态上拟合，分布错配仍会回来。完整代价为搜索调用 \(BK\) 加标签样本 n；PUCT 在此不完全信息大树上没有无条件多项式发现保证。合法动作先验可混入均匀探索但不可绕过非法 mask。信念采样不得读取隐藏真值，避免 PIMC 的策略融合与先知标签。

### 7.5 可执行状态构造、schema 与训练语义补充

**不是复制人类完整局面，而是受约束场景集合。** 对同一 game 的 t→t+3 同阶段窗口，先检查卡牌版本、EOT/recruitment 标记、英雄/机制兼容性；来自混合旧 build 的卡必须映射到当前官方数据并记录拒绝原因。选择当前引擎合法运行至相同 turn 的完整 donor `state_json`，保留 donor 的隐藏字段和共享池上下文，调用现有注入封装搬 board/hand/tier。若窗口起点为 EOT，先完成该回合战斗再进入下一回合，不能在相同金币周期额外行动。gold/shop 不以目标后验挑选：来自 donor 当前合法状态，并按冻结的 donor/seed 分布抽取多个补全版本，明确其为假设；若 tier 改变导致商店不匹配，则用引擎正规刷新/推进接口并记账，无法一致化就拒绝。检查 save/restore、无重复 EID、无 pending 冲突、金币非负、合法 mask、引擎 invariants；`pool_delta_unknown` 必须保留，不能宣传全局历史守恒。只让引擎生成后续动作与随机商店，不从人类 t+3 目标反推出作弊商店。

记补全分布为 \(\nu(s|o)\)，目标是 \(\mathbb E_{s\sim\nu}P_\pi(E|s)\)，另报补全之间最差/最好范围；这不是未知真实后验。LLM 仅看到 learner 可见字段与合法动作表，输出 action_id/target/abstain；它只能建议，搜索/引擎验证才能形成标签。原先 `(1−ε_L)^3` 仅在三个独立错误机会且每次错误必失败的玩具模型成立；实际有 H 个决策，应使用 union bound \(P(\text{至少一次 oracle 错误})≤\sum_{j<H}\epsilon_{L,j}\)，错误相关时不能乘积，也不存在普遍的 learner 错误≥oracle 错误定理（可去噪/超越老师）。

接口落点为现有 [题目与软标签模块](../hsbg/az/train/board_problems.py)、[PPO 损失与配置](../hsbg/az/train/ppo.py)、[训练器](../hsbg/az/train/ppo_trainer.py)、[准状态注入](../hsbg/az/train/human_obs_full.py)；搜索仅复用 `hsbg/az`，不另建训练路线。CLI 与新增字段全是**提案、未实现**。旧 schema 不应静默当作新 schema：加版本化适配器，已有 features/cards/legal、reference 与 label 字段原样保留，新字段置于 expert 子对象：

```json
{
  "expert": {
    "schema": "expert_window_v1",
    "source_game": "source-id", "window_id": "window-id",
    "phase": "recruitment_start", "turn_start": 12, "horizon_turns": 3,
    "completion_seed": 0, "state_json_ref": "snapshot-ref",
    "engine_version": "version", "card_map_hash": "hash",
    "availability": {"gold": "donor_assumption", "shop": "donor_assumption"},
    "support": {"status": "unmeasured", "log_action_likelihood": null},
    "teacher": {"kind": "search", "legal_action_distribution": null},
    "behavior": {"policy_id": null, "action_probabilities": null},
    "split": "train", "audit_status": "pending"
  }
}
```

以上数值只是 schema 示例，不是新增测量。必须保留 state/动作精确可恢复引用、完整行为 logprob、合法 mask、观测 hash、模型 hash；未知数据为 null 而非伪造。新增 `--expert-injection-reset-prob` 与 action/query 混合概率分开；关闭时不读题库、不构建头、不额外取 RNG、不改变 optimizer 参数顺序。增加缺 shop/版本错配、EOT 双重招募、补全抽样、split 泄漏和独立 RNG 单测。

### 7.6 具体损失、开关及 A/B 预注册

推荐优先级是 **当前 learner/准重演状态 → 现有 PUCT 搜索验证 → DAgger 聚合 → 软 BC 蒸馏**，不是再次对未经验证人类轨迹 warm start。DAgger 的动作查询不应替换 learner 状态；reset 注入改变初始分布，是单独课程操作。为进入后期需要从合成晚期状态短程训练，再把 reset 边界逐步前移，最终在正常起始对局关闭 reset 评估；只对从未访问到的 t14 开监督 gate 是无效的。

定义冻结审计 gate
\[
g_i=\mathbf1[\mathrm{valid}_i\land \mathrm{quality}_i\land
(\log q_i<\log\eta_i\lor p^U_{3,i}<p_0\lor\mathrm{OOD}_i)]
\]
并对 gate/权重 stop-gradient；OOD 但不可执行/未知 oracle 时只请求标签不直接产生监督。\(\eta_i\) 按计划采样预算取 \(\alpha/N_i\)，需区分动作似然与真实路径概率；\(p_0\) 由离线预算预注册。令可靠性权重 w 来自补全稳定性与搜索改进下置信界，而非自动认为“越 OOD 越应该降权”。最终
\[
L=L_{PPO}^{native}+\alpha_k\frac{\sum_i g_iw_i\mathrm{CE}(q_i^{search},\pi_\theta)}{\max(1,\sum_i g_iw_i)}
+\zeta_k\mathbb E_{native}\mathrm{KL}(\pi_{ref}\|\pi_\theta).
\]
原有 BC 公式的分母和 OOD 权重以本式为准；无有效样本时辅助损失精确为零。PPO 只使用原生 on-policy rollout，专家替换动作/合成 reset 样本默认进监督 buffer，不冒用 learner old_logprob；后续若要让 PPO 学混合策略需另做正确概率和分布校正。冻结 ref 是 A/B 起点，保护正常策略。

以下均为**待验证超参数提案，不是事实或理论保证**：50 iter（允许预注册40–60），reset 占比上限0.1并线性降至0；标签系数 \(\alpha_k=0.1\max(0,1-k/K)\)，DAgger 执行混合 \(\beta_k=0.1\max(0,1-k/K)\)，监督 buffer 占比上限0.1，\(\zeta=0.01\)。若辅助梯度范数超过 native PPO 的0.1倍则缩放；零 native 梯度时禁止辅助更新或另行批准 warm start。初始窗口可从 t10–12 的可达前缀开始逐步接 t14/t15，不能仅配置 t12–15 等待自然死亡策略进入。搜索预算 B 由离线 CPU 延迟/发现率确定，A/B 前冻结，不承诺特定节点数足够。

A/B 由另行批准后执行，本任务不执行训练，不能保证40–60 iter 可在合理 CPU 时间完成。A 保持原流程，B 加上述 gate/课程；同源基线 checkpoint、等 native 环境步数、固定独立 seed 流，同时报告 B 额外 CPU 搜索成本。训练样本与评估人类 game 全局互斥；若现有 checkpoint 已接触全部人类源，须另取未见来源，不能声称新切分自动消除历史泄漏。

成功评估三套口径分开：正常起点严格 s14 压力下存活率及“死亡记零”的全体强度；原 strength_stages 同协议强度比；准重演条件下增长成功率。报告幸存条件强度但不单独用于胜利声明。+10%、+50%按相对改善算；长期**两回合均≥0.15，再两回合均≥0.30**，避免把0.15与0.30误作t14/t15不同标准。human panel 按平均名次越小越好，\(D=\bar r_B-\bar r_A\)，非劣约束为单侧95%上界≤预注册容忍 δ_rank；严格不劣可取 δ_rank=0，6.223作当前冻结参照、6.445仅历史上下文。对局配对/整局 bootstrap，同时报告多 seed 区间、合法率、拒绝率，不能用注入评估的提升替代真实面板。

### 7.7 引用与数值口径

仓库依据：[阶段强度实测](../runs/plots/strength_stages.md)、[状态保真度审计](FIDELITY_INJECTION.md)、[题目收集与3回合标签](../hsbg/az/train/board_problems.py)。64/64、面板6.223/6.445、Firestone总量、308,944 BC样本及其失败归因由本次用户提供，本文未重新运行验证。所有置信界计算、提升目标和超参数提案均已与实测分开。理论名称用于界定方法族，并非宣称仓库已实现 DAgger/V-trace/Retrace/DICE/PAIRED/ADR/Go-Explore；课程只借用其思想，仍在唯一 AZ 栈实现。

## 8. 一句话结论

**当前有强证据处于有限预算的后期覆盖极端区，但尚未证明严格 support 外或名次增益 Δ；应先做可执行准重演上的 DAgger 式当前状态搜索标签，第一步是 CPU 离线审计严格零/有效低支持/不可判定比例及三回合可达概率置信区间，而不是先调奖励。**

## 9. 本仓库离线审计结果（2026-10-31，`scripts/support_coverage_audit.py`）

§8 要求的「第一步」已执行；产物：`runs/support_audit/report.json` + `report.md`。
数据：376 个真实观测文件 / 13,120 帧 → 4,404 个 game-turn（EOT 优先，每局每回合一个
状态）；t≥10 的 t→t+3 后期窗口 286 个，取**同 turn Δ top 50%** 作成长窗口（146 个，
t10 78 / t11 40 / t12 20 / t13 8）。learner 侧用 s15 当前权重的弱对手后期题池
（96 局 / 672 个状态；`runs/support_audit/problems_s15_late.jsonl`，由
`build_board_problems.py --late-ref-policy fixed` 生成）。

**结果（全部按整局 cluster bootstrap，1,000 次）**

| 指标 | 值 |
|---|---:|
| 专家状态覆盖率 `C_state`（kNN k=5，η=learner holdout p95） | **0.000** [0.000, 0.000] |
| OOD（=1−C_state） | **1.000** |
| 专家 kNN 距离 / learner holdout 中位距离 | 2.92× |
| 同 turn 对照（同 turn 内定 η；t10–13） | 0.000 / 0.000 / 0.000 / 0.000（最小距离 5.0–8.5 > η 3.0–3.7） |
| η 放宽到 holdout p99.9 | 覆盖率仍 0.000 |
| 全部 286 个后期窗口（不按成长筛） | 覆盖率 0.000 |
| 强度比（专家 p50 / learner p50，t10–13） | 3.7× / 6.9× / 13.4× / 4.0× |
| `KL(ref_fixed‖π)` 中位 / p90（可比状态 n=282） | 4.73 / 15.02 |
| `NLL`(ref top-1) 中位 | 4.25（t14 7.63、t15 7.11） |
| 动作支持覆盖 `C_act`（π>1e-3 的参考质量） | 0.442（t14 0.346、t15 0.324） |
| 三回合可行性 `p3`(fixed) log10 中位（n=43 窗口） | **−6.29**（p10 −13.05；51.2% <1e-6） |
| 同口径 `p3`(current) / `p3`(buy∪play) | −4.62 / −3.02 |

**判据**（预注册：C_state < 0.90 或 p3 < 1e-6 → 极端条件）：两条同时触发 ⇒
**extreme_condition**。这里的极端不是「某一条专家路线罕见」，而是**同 turn 的成长状态
整体落在 learner 近邻之外**（最小距离就 > η，即使阈值放到 p99.9），且人类路径的
3 回合动作似然中位在 1e-7 量级。

**解释与限制**：专家状态与 learner 的差异集中在 tier（+3.5σ）、卡 tier 构成
（mean_card_tier +3.9σ、tier≥5 数量 +5.2σ）、关键词数（+3.3σ）与强度（+2.0σ）——
即 learner 的后期「没有升本/没有成型的 5–6 本战团」，这正是 §1.2 的覆盖缺口；但专家帧
缺 gold/shop，kNN 只是**可见子空间**的近邻质量（§7.3），动作 KL 只能在可比状态上算，
`p3` 是固定状态序列上的动作似然连乘（§3.4），不是含转移概率的真实路径概率。

**下一步**：按 §5.2/§7.6 的优先级进入 **DAgger / 当前状态搜索标签**（离线人类近邻只作
候选，不作动作标签）；在支持缺口被证明之前，继续只调参考解权重属于 §7.6 所说的
「无效 gate」。参考解本身的可复现修正见 `docs/BOARD_PROBLEMS.md` §14。
