# 观测信息缺失与信用分配/价值头：B07 讨论

## Q1：注入输入，还是让网络学？

当前观测是固定的 3227 floats+124 card slots；它有当前商店、己方/上一场对手盘面和当前 tier，但没有池计数、历史序列或反事实收益。对一个确定引擎而言，“可由网络推导”不等于“在 300M decisions 内可学”：若状态统计量不是当前观测的充分统计量，问题是 POMDP；即使它是充分的，深度网络也要用样本估计长时分布。

|缺口|原则上能否由现有输入推导|对升本的因果相关性|学习代价/注入代价|结论|
|---|---|---|---|---|
|1. 商店分位、tier-race 出现率、池剩余|不能精确推导：当前 8 格是一次抽样，隐藏池状态不可辨识|直接决定升本后的期望战力，属于 `do(upgrade)` 后转移分布的关键变量|学习需跨局记忆、池状态和大量卡牌共现；注入约几十至数百标量，但依赖引擎池统计和版本|**先注入最小版**（各 tier 的抽样概率/剩余分位），再评估|
|2. tier5/6 未来可得卡集合|卡槽只表达当前可见卡，不能可靠“想象”未见卡|决定升本的 option value，尤其是核心卡存在概率|全表 token 约 50–100 张、显著增算且卡表版本耦合；低维 set encoder 或 tier histogram 约 10–30 维|**先学后注入**：先用 BC/离线卡表验证需求；若需求稳定，注入集合摘要而非全表|
|3. 自身成长斜率/潜力|可由 turn 间历史观测估计，但当前实现未提供显式 recurrent state|决定牺牲当前强度后能否在 2–3 回合回本，是升级时机的直接条件|网络须记忆、差分和处理删牌/战斗噪声；注入 4–8 个 robust EMA/斜率特征，兼容性好|**注入**（只注入因果可解释的过去差分，并用 warm-up mask）|
|4. 回合预算/死亡风险|health、对手 tier/盘面部分可推导，但“还能撑几回合”需战斗随机性模型|是升级成本是否可承受的约束；死亡风险是 upgrade 的负边际价值|学习需对手战斗模拟，样本量大；注入 2–6 个 calibration 后的 survival quantiles|**先学后注入**，先做辅助 survival head；校准有效再注入|
|5. 对手升本轨迹|当前输入无历史；单步网络不能辨别“刚升本”与“已停本”|影响全场 tempo 与下一场对手分布，但对个人升级是间接因果变量|每对手 6–10 个历史 tier/变化特征，维度低；需要 episode history|**注入**（历史序列/Δtier，避免只给结果标签）|
|6. 升本后期望收益/成本比|成本在 global 中，收益是隐藏转移和未来战斗，不能精确由当前网络瞬时推导|这是“何时 upgrade”的充分决策摘要，因果最直接|可由引擎 rollout/模型估计 2–4 个 value-of-upgrade 特征；但目标泄漏和版本耦合风险高|**先学后注入**：先训练 action-conditional value；只在校准后固定接口|
|7. 全场节奏/相对位置|现有 opponents 的 tier、placement、alive 可聚合，原则上可学|影响是否必须抢 tempo；信息量中等，通常不如 1/3/4/6|网络聚合只需学习，注入 5–10 个均值/分位会造成少量冗余|**先学**，只作诊断；若 attention 聚合失败再注入|

排序（对当前失败模式的边际价值）：**1≈3≈6 > 4 > 5 > 2 > 7**。但“注入全部信息一定更好”是错误的：池统计若口径错、未来集合含版本泄漏，策略会过拟合 simulator；高维 card list 还会稀释当前商店信号。新增特征必须记录数据版本，并先接一个 zero-init gate/adapter；旧 checkpoint 的旧路径保持严格等价。

## Q2：信用分配与价值头

### 命题1：终局单标量下 GAE 的视野不是“越大越好”

**假设。** Episodic MDP，终点在 T，唯一奖励为终点随机变量 R，γ=1；估计值为 \(V_t=V^\pi(s_t)+e_t\)。GAE 为
\[
\hat A_t^{(\lambda)}=\sum_{k=0}^{T-1-t}(\lambda)^k\delta_{t+k},\quad
\delta_i=r_i+V_{i+1}-V_i.
\]

**陈述与证明思路。** 当 \(V=V^\pi\) 且 λ=1，残差望远镜为 \(R-V^\pi(s_t)\)，是无偏 Monte-Carlo advantage；λ<1 是 TD 残差的几何截断，若值函数有系统误差则一般有偏：
\[
E[\hat A_\lambda-A^\pi|s_t]
=E\sum_k\lambda^k(e_{t+k+1}-e_{t+k})
\]
（终点令 \(e_T=0\)）。若每个残差噪声近似独立、方差为 \(\sigma_\delta^2\)，长度 L 时
\[
Var(\hat A_\lambda)\simeq \sigma_\delta^2\frac{1-\lambda^{2L}}{1-\lambda^2},
\]
而 λ=1 为 \(L\sigma_\delta^2\)。这证明了 bias-variance trade-off，而非 λ=1 必然更好。

**数值。** 143 步局中，λ=.995：\(.995^{110}=0.576\)，\(.995^{143}=0.489\)；从 t=33 看终局约 110 步，信号仍保留 58%，不是消失。λ=1 则为 1，但把所有残差噪声累加。在独立残差近似下，L=110 时几何方差因子为 \((1-.995^{220})/(1-.995^2)\approx66.9\)，相对 λ=1 的 110 降约39%；L=143 时约 \((1-.995^{286})/(1-.995^2)\approx76.3\)，相对 143 降约47%。实际残差有时间相关性，故这些是量级估计；终点噪声仍会被所有早期动作共享。λ=.995 在当前值函数不成熟时通常更稳；应以 held-out TD residual、KL 和 rank 实测选择。若值头有严重欠估，λ=.995 的偏差可能压过方差收益；此时辅助头比盲目把 λ 拉到 1 更合理。

### 命题2：势函数塑形保策略不变，但不能写入“更早升本”偏好

**定理（Ng, Harada & Russell, 1999）。** 对同一 MDP、相同 γ，若
\[
F(s,a,s')=\gamma\Phi(s')-\Phi(s),
\]
且终端为吸收状态、终端 potential 统一（通常 \(\Phi(s_T)=0\)）、没有截断边界或边界也按同一规则 bootstrap，则任意轨迹累计 shaping 只差 \(-\Phi(s_0)\)（γ=1；折扣时为边界项），所有策略的回报排序不变，最优策略集合不变。

**证明思路。** 逐项求和：\(\sum_t\gamma^tF_t=-\Phi(s_0)+\gamma^T\Phi(s_T)\)，中间状态完全消失；Bellman 方程中 \(V'_\pi=V_\pi-\Phi\)，Q 的动作排序不变。若把 tier-target 直接奖励为 \(r+ c\,1\{tier\ge g(t)\}\)，它不是相邻 potential 的差，累计量依赖停留时长，故改变最优策略；这正是 `coef=10` 能把 t12 tier≥5 从 28% 推到 50% 而 human rank 不升的原因。

**保序版本。** 定义有界 \(\Phi(s)=c\,h(t,\tau)\)，例如 \(h=\mathrm{clip}(\tau-g(t),-G,G)\)，使用 \(F=\Phi(s')-\Phi(s)\)（γ=1），终点强制 \(\Phi(s_T)=0\)。越界 tier 必须 clip，且终端/死亡/时间截断都写入同一 terminal convention；否则 telescope 失败。该版本可改善学习密度，却不能合法地保证“t7 到4本、t9到5本”；若目标是注入该先验，必须承认它是 policy-changing reward，并以 rank 门禁。

### 命题3：辅助价值头可降方差，但共享主干并非自动无偏

设终局名次 Y 或终局强度 Z，在每个状态预测 \(q_\psi(Y|s)\)，
\[
L=L_{PPO}+c_vL_V+c_{aux}E_t[-\log q_\psi(Y|s_t)]
\]
（强度可用 Huber/MSE）。若辅助 loss 对 policy logits 的路径 stop-gradient，或辅助头有独立参数/独立 optimizer，则条件于当前 θ，PPO policy-gradient estimator 的期望仍为 \(\nabla J(\theta)\)：辅助项只改变表征的训练轨迹，不改变该次 estimator 的目标。若与 transformer 完全共享且不 stop-gradient，**不能声称不改变策略梯度**；它加入了 \(c_{aux}\nabla L_{aux}\)，可能有用也可能冲突。

对回报 R 和 baseline b(s)，
\[
Var(R-b)=Var(R)-2Cov(R,b)+Var(b).
\]
最优 baseline 是 \(b^*(s)=E[R|s]\)，此时 reduction 为 \(Var(E[R|s])\)，剩余为 \(E Var(R|s)\)。辅助名次头若把 MSE 降 \(\epsilon\)，可近似把同量的可解释方差转成 baseline，降低 \(Var(\hat A)\)；但 label leakage、校准差或强度与 rank 冲突时不保证下降。建议 auxiliary coef 0.02–0.1，并报告 held-out rank NLL、TD residual 和 PPO KL，而非只看 aux loss。

### 命题4：长强 episode 加权是改变目标，不是免费降噪

令轨迹权重 \(w(\tau)\ge0\)，归一化 PPO 梯度等价于优化
\[
J_w=\frac{E_{\tau\sim\pi}[w(\tau)R(\tau)]}{E[w]}.
\]
若 w 依赖终局强度/存活，它是 trajectory-level importance weighting；也可解释为风险敏感/选择性目标，已不再是原始平均 rank。若长强局本来是稀有且 value 误差大，\(E[w^2\|g\|^2] 增大，effective sample size 下降，且 critic 在加权分布上偏置；PPO 固定 KL 预算会把更新耗在少数长局。B06 的实测正是总体 bot rank 上升但长强 win、tier5@t15 下降，故不能使用“加权必然学到长局”的直觉。默认 `none`，如复测须 clipping、ESS 门禁和独立 long-strong 报告。

### 命题5：BC/ExIt 填的是探索支撑缺口

设当前策略支撑为 \(S_\pi(s)=\{a:\pi(a|s)>0\}\)，最优路线支撑为 \(S_*(s)\)。若存在一段关键状态使 \(S_\pi(s)\cap S_*(s)=\varnothing\)，且到该状态的概率在当前策略下为零（例如贪本后活过 t10 的路线从未被采样），任何纯 on-policy PPO 都无法从该状态得到反事实梯度；这就是 exploration gap。专家数据覆盖 \(S_*\) 后，行为克隆最小化 \(E_{d_E}[-\log\pi_\theta(a|s)]\)，可把概率质量搬入该支撑；ExIt 再用搜索/终局结果过滤错误示范。

前提是专家动作在任务版本中合法、状态分布有覆盖、示范质量优于随机且 BC 权重会退火；否则 covariate shift 会复制专家错误，或把不可达经济路线硬编码。应采用少量 BC warm-start/混合行为，不把 BC 当作 rank 证明。

## Q3：单变量实验矩阵（每项 200–300M decisions）

|实验|唯一变量/最小改动|主判据|无效/变差判定与回退|
|---|---|---|---|
|A 信用分配|tier miss 从回合首 decision 改为该回合 decision 均分或 EndTurn 前一次；不改总 episode reward|t7/t9/t12 tier、t14–18 Σ、768 局 human mean rank/top4|tier 不变或 rank 变差>0.1、top4 降>3pp：回退原 tracker；不把 coef 再无脑放大|
|B 辅助 value|新增终局 rank CE（可加 strength MSE 二选一），coef 0.05，policy 路径 stop-gradient|held-out rank NLL、TD residual/GAE 方差、768 局 rank；tier 只作次指标|GAE 方差不降、KL/entropy 异常或 rank 变差>0.1：coef=0；保留主 critic|
|C λ|只改 λ：.995→.999（另跑 .99 作为低方差对照；同一实验预算）|t≤7→t5 比例、long-strong win、rank、KL|KL 早停增加>20%、long-strong 降或 rank 超误差条：回到 .995；不能以单局 tier 胜出宣称成功|
|D 低维观测 adapter|只加 3–8 个已校准历史特征（scaling EMA、opponent Δtier、survival quantile），接 zero-init gate；不加全卡表|768 局 rank/top4、强度曲线，按版本/seed 分层|新特征消融无增益或跨版本退化：关 gate；不扩大观测。池/未来卡集合只有在 A–C 证实信息瓶颈后再做|

所有实验固定 B07 的 5 席、p0.90、full、无长强加权配方，禁止卡牌禁用；同时保留当前饰品限制作为固定配方，不把它当实验变量。每个 checkpoint 至少报告 384 局中期和 768 局终评、SE/置信区间、非法动作/截断、entropy/KL、t9 gold_end 与 t15 强度。若 A–D 均无效，结论应是“信用/表示不是唯一瓶颈”：`ECONOMY_CEILING.md` 的证据表明当前收入/升级费存在三选二上限，此时应另开、经项目批准的引擎规则对齐实验，而不是继续堆 reward。新增维度迁移必须旧特征路径逐位不变，adapter 的 gate 与新 projection zero-init，并先做短 pilot 验证吞吐和 state/卡表版本。

**出处与必须实测项。** Potential-based shaping：Ng, Harada & Russell (1999)；GAE：Schulman et al. (2016)；PPO：Schulman et al. (2017)；BC/DAgger 的分布偏移讨论：Ross, Gordon & Bagnell (2011)。上述无偏条件、方差公式依赖近似独立/正确终止；共享表征、池统计校准、实际 rank 与 survival 改善、λ 的最优点及所有阈值都必须在本项目实测，不能从定理外推。
