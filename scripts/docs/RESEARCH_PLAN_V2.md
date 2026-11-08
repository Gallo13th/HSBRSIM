# HSBRSIM 场面强度 V2：研究方案与开发要求

> 状态：研究设计/开发规格；本文件只读分析，不包含训练授权，不占用 GPU。日期：2026-10-31。
> 目标：解决「名次接近、场面强度显著偏弱」而不是继续在旧 512 局面板上挑低点。

## 0. 执行摘要与事实基线

### 0.1 问题定义

主指标仍是 7 席注入真实 10k+ 战团的 human 面板：256 局、seed 420000、auto 分位（评测约 194 秒）。已知结果为 s9d 6.445、s10 最佳 6.402、s12 6.344；用户最新快照显示 s13（准完整库 + 5 席×p0.9 + rank-only + move-guard + DPO 0.02 + 120M）稳定 6.26–6.32，最新以 s13 120M 的 6.307 @110M 为准；s14 加 archetype 软偏置 0.5、10M 为 6.328。任何新方法均须同时改善主指标和强度过程终点，不能用弱对手饱和替代人类改进。

### 0.1a 证据表

| 指标 | 数值 | 来源（文件路径或 run 名） | 时点 |
|---|---:|---|---|
| baseline human mean rank | 6.445 | `runs/exam/SUMMARY.md` §2 开发标注（exam 绝对值 6.4756）；`docs/PROJECT_MEMORY.md` §1.3 | 20M 开发面板（256 局） |
| s10 human mean rank | 6.402 | `runs/exam/SUMMARY.md` §2 开发标注（exam s10_40M 6.4390）；`docs/PROJECT_MEMORY.md` §1.3 | 40M 开发面板（点估计最佳；终值 6.471） |
| s12 human mean rank | 6.344 | `runs/exam/SUMMARY.md` §2 开发标注（exam s12_20M 6.3862）；`docs/PROJECT_MEMORY.md` §1.3 | 20M 开发面板（单点；后续 6.402/6.441） |
| s13 human mean rank | 6.26–6.32（6.260 @70M；6.307 @110M） | `docs/PROJECT_MEMORY.md` §1.3；`runs/az_entity_s13/eval/history.json` | 120M 预算，70M/110M 快照 |
| s14 human mean rank | 6.328（6.328125） | `runs/az_entity_s14/eval/history.json`（human, 256 局, 193.8 s, 10,027,241 decisions） | 10M eval（2026-10-31） |
| 强度比 t9 / t12 / t13 / t15 | 约 0.38 / 0.14 / 0.07 / 0.03–0.04（A：0.383/0.133/0.069/0.031；B：0.388/0.144/0.073/0.036） | [REWARD_SHAPING](<REWARD_SHAPING.md>) §10.2 | 2026-10-30，s9d 起点 A/B 各 60 iter；质量面板 64 局 |
| tier p50 t9 / t12 / t15 | 4 / 4 / 5（DPO 有效臂；对照臂 4 / 4 / 4） | [DPO_UPGRADE](<DPO_UPGRADE.md>) §6.5；[REWARD_SHAPING](<REWARD_SHAPING.md>) §10.2 | 64–96 局质量面板；t15 4→5 来自 DPO 有效系数臂 |
| 出局强度 p50 | 约 800–860（报告值，`reported_not_verified`） | 用户委托基线快照；[REVIEW_PLATEAU](<REVIEW_PLATEAU.md>) §5 仅引述约 800；未定位 860 的原始 artifact | 历史质量快照，非本次实测 |
| 暴露剂量 | 4.6% → 约 60% | [PRESSURE_AUDIT](<PRESSURE_AUDIT.md>) §2.3；[REVIEW_PLATEAU](<REVIEW_PLATEAU.md>) §1 | 旧 s10 实测 → 当前报告值；约 60% 尚须实际命中日志核验 |
| 保真度 counters | +2.62pp（combat；95% CI [1.75,3.53]）；pipeline +1.36pp | [FIDELITY_INJECTION](<FIDELITY_INJECTION.md>) §4 | B2r−B0，自有可信快照消融；不是 human rank 收益 |

> 状态标注：`docs/REVIEW_PLATEAU.md` 中 s13=6.430 是 **20M 旧快照**；最新状态以 s13 120M（6.307 @110M）为准。未有原始 artifact 的用户委托数字保留为快照/报告值，不冒充重新测得。

最直观缺口是战团强度比（我方 p50/真实 10k+ p50）：t9 约 0.38、t12 约 0.14、t13 约 0.07、t15 约 0.03–0.04；t15 才勉强 tier 5，而真人 t9+ 已 tier 5–6。出局强度 p50 约 800–860，真实 t15 约 26,500。训练是 14.9M entity transformer、PPO/rank-only、γ=1、λ=0.995、KL anchor 0.1×200 iter、seq 辅助 0.05、分层 BC 0.004、DPO(upgrade) 0.02、move-guard、archetype 软偏置 0.5、准完整 board+hand+counters 注入；真实数据没有 gold/shop/player-level effects。

### 0.2 已知因果边界

- 注入命中时压力很大：败率增加约 63.7–72.5pp（[PRESSURE_AUDIT](PRESSURE_AUDIT.md)）；所以不是「人类战团不够强」。
- 旧审计曾测得训练暴露仅 4.6%/learner-turn；当前已约 60%且保真度提高，必须把实际对位命中率、投递成功率和版本分层写入日志，不把配置概率当暴露。
- λ=0.995 下 t≤8 GAE 权重中位约 0.319，终端分量占早期 |A| 约 14.6%；不能未经实验宣称 λ 把信用完全压没。日志曾有 PPOConfig.lam=0.95 与 CLI 0.995 不一致，先修配置可观测性。
- 准完整库为 13,120 条观测、1,961 帧；可获得 board/golden/部分关键词/hand/tier，不可得 gold、script counter/gems、attachments、玩家级效果、shop/共享池差量（[FIDELITY_INJECTION](FIDELITY_INJECTION.md)）。
- 308,944 条 BC 样本；BC-only 曾令 moves/turn 从 2.4 到 17.3，强度与胜率崩塌；加 Move 监督/anchor 仍未过质量门（[BC_PRETRAIN](BC_PRETRAIN.md)）。DPO upgrade 纯 30 步即趋于 99.9%，因此只能小系数（[DPO_UPGRADE](DPO_UPGRADE.md)）。archetype 线上前缀 top1/top3 为种族 64.5/83.3%、流派 45.3/73.5%，低置信时必须不偏置（[ARCHETYPE_BIAS](ARCHETYPE_BIAS.md)）。
- 势函数塑形和 tier-target 已证伪为当前主解：前者在 γ 一致时望远镜，后者未改变核心行为（[REWARD_SHAPING](REWARD_SHAPING.md)、[TIER_TARGET](TIER_TARGET.md)）。Move-guard 只能去抖，不等于强度目标（[MOVE_GUARD](MOVE_GUARD.md)）。

### 0.3 总原则

1. **先可证伪、后大训练**：每个方向先做离线或冻结轨迹 40–60 iter 试验；不得因旧面板单点低而扩大预算。
2. **逐位等价默认关闭**：任何新字段在 `coef=0`/`enabled=false` 时不加载、不采样、不改变 RNG、records、stats、checkpoint bytes、动作序列；至少有同 seed bitwise 测试。
3. **human 主指标不可被过程指标替代**：固定主面板协议，报告配对逐局差值和 CI；仅使用人类面板 + 质量面板门禁，不再进行 bot 评测。
4. **强度必须按 turn、存活口径、版本分层报告**：同时报告条件/无条件强度比、tier≥5、存活率、动作族和实际人类命中。
5. **只在现有 `hsbg/az` PPO/不完全信息栈内实现**：不重新引擎、不重新引入自对弈路线；新方法先在 tiny/toy env 与冻结回放验证。

## 1. 四个方向调研与落地方案

### A. 克隆人类高手操作 / 场面题标准解

**核心思想。** 不把「赢弱 bot」当作唯一监督，而从高 MMR 人类行为学习状态→动作及状态→场面强度的条件分布。除行为克隆外，构造场面题：给定 turn、hero、board、hand、shop、gold 与战团，要求模型在购买、升本、刷新、站位序列上选择能最大化短期/多回合战团强度的标准解。目标应为排序/相对偏好（expert action 优于弱动作）和强度预测，而不是不可信的单一 oracle。

**代表工作/启发。** 行为克隆与 DAgger（Ross et al.）；Decision Transformer/trajectory-conditioned imitation；T-REX/advantage-weighted regression；AlphaStar/Offline RL 的 ranked demonstrations；AlphaZero policy/value targets。这里采用「分层动作 CE + action ranking + 强度 head + 短后续 replay label」的保守组合，不采用 BC-only。

**在本任务落地。**
- 从 `data/firestone_bc`、`data/real_library` 建专家等级、版本和 game-group split；对同一场景产生人类动作候选、相邻动作反事实和短 horizon（1/3/8 turn）强度标签。
- 训练辅助 head：`V_strength(s)` 预测同 turn 人类战团强度分位/对数比；`Q_strength(s,a)` 或 pairwise margin 预测动作后强度改善；policy 仍由 PPO 主导。
- 使用 action-conditioned target 时，必须只用可见信息；gold/shop/player effect 缺失标 mask，不用默认 0 伪造标签。
- 与 BC/DPO 的关系：BC 提供初始化/低权重先验，DPO 只继续处理 upgrade 子集；A 不复活 BC-only，也不把人类动作当绝对最优。优先使用 `BC auxiliary` 和 `DPO` 的独立 RNG/周期。

**数据/改动。** 现有 308,944 BC 样本足够做 policy imitation 原型，不能独立提供强度真值；需要 ≥200 个独立源局的版本隔离快照、动作后 1/3/8 turn 状态和标准解标注。标准题先做 200–500 题人工/程序双审，覆盖 t6–12、升本/购买/站位/经济；每题保存 `problem_id/source_group/visibility_mask/candidate_actions/expert_set/strength_label/label_version`。

**收益与风险。** 预期最直接抬高 t9–t12 tier/战团；风险是 dataset bias、动作模仿过拟合、Move 再次爆发、强度标签把版本变化/存活幸存者偏差带入策略。若只优化 CE，可能重复 BC 的 0.031 强度比崩塌。

**最小验证。** 固定 s13/s14 checkpoint，200 题×每题 64 CPU replay；40–60 PPO iter，policy 辅助系数从 0.001 起，另做无 policy 更新的 label 可学性。判据：人类面板配对 `Δhuman≤−0.10` 且 CI 上界 `<+0.05`（rank 越低越好），人类 top4 ≥ 基线−2pp；质量面板 t12/t15 强度比相对基线提升 ≥10%，tier≥5@t12/t15 与出局强度 p50 不低于基线；collect 增幅<15%，illegal/truncation/注入错误=0。任一不达标即回退该单因素并记录进 `EXPERIMENTS`。

### B. 重构信用分配

**核心思想。** 让 critic 评价 `Q(s,a)` 或 advantage 的动作条件，而非只用 `V(s)`；以分数阶/可调资格迹处理回合内长依赖，用幂率记忆代替单一指数 GAE，使 t7 升本对 t12–15 强度和终局 rank 的信用可见。关键是把幂率记忆实现为 **advantage 估计器的时间核**；动作条件 Q 只作为 critic 结构，不直接当 actor baseline（见 B.3）。

**B.1 幂率资格迹：定义、两个极限、替换边界。**

任务给的写法是 `e_t = Σ_{k≤t}(1+(t−k)/κ)^{−α} γ^k ∇log π`。为避免 `γ^k` 的**时间原点歧义**，下文把 `k` 定义为 lag（`k=0` 是当前决策），写成等价式：

```text
e_t = Σ_{k=0}^{t} (1 + k/κ)^(−α) γ^k ∇_θ log π_θ(a_{t−k} | s_{t−k}),   κ>0, α≥0
```

若 `k` 是绝对步，折扣必须写 `γ^{t−k}`；否则 `γ^k` 会随绝对时间改变尺度。`e_t` 是**后向资格迹**（把信用分配给过去动作），对应 actor-critic 更新 `Δθ ∝ δ_t e_t`；它不是 PPO 的 forward advantage。若要把同一核作为 PPO 的 drop-in advantage（替换 GAE），必须**前向**作用在未来的 TD 残差上：

```text
δ_t = r_t + γ V(s_{t+1}) − V(s_t)
A_t = Σ_{l=0}^{T−t} w_l γ^l δ_{t+l},   w_l = (1 + l/κ)^(−α)
w̃_l = w_l / Σ_{j=0}^{T−t} w_j        (normalization over future horizon)
```

`e_t` 单独拿来做 REINFORCE 型更新时必须乘回报/优势；`A_t` 才是 PPO 里替换 GAE 的对象。后向 trace 与前向 advantage 不要混用：trace 只进 `δ_t e_t` 的更新，不得当 advantage 传入 PPO。terminal/truncated 的 mask、bootstrap 与旧 GAE 一致；`credit_timebase=turn` 时 `l` 是未来 elapsed turn，`γ^l` 是 SMDP 折扣，禁止与 action-step 混用。

**它替换的是 GAE 的 λ 还是整个 advantage？** 这里指前向 `A_t`：替换 GAE 内部的**时间核 `λ^d`**，也就是整个 advantage 估计的权重；保留 `V(s)` critic、`γ`、reward、TD 残差和 bootstrap/mask。后向 `e_t` 是另一条 trace 实现路径，不是 advantage 的替代品。`kernel_mode=gae|powerlaw` 互斥，powerlaw 不是叠加在 GAE 上；若要做凸组合，另设 `kernel_mix_beta` 消融（默认 0），并同时报告两种核的 ESS。动作条件 Q 只在 critic 侧（B.3），不改变这条替换边界。

**两个极限（可检验命题）。**

1. **α→0（均匀/长记忆）**：`w_l=1`。`γ=1` 时 `A_t` 是未来 horizon 内 TD 误差的均匀平均，`N_eff=L`（`L=T−t+1`）；`γ<1` 时只剩折扣，不再有幂率长尾。
2. **α→∞（短记忆/局部几何）**：对固定 `l≥1`，`w_l→0`、`w_0=1`，归一化核→`δ_{l0}`，`A_t→δ_t`（one-step），`N_eff→1`。它**不**收敛到 GAE(0.995)；局部几何率为 `λ_eff≈e^{−α/κ}`，有效视野 `O(κ/α)`。要匹配 GAE 的**局部**衰减率 `λ=0.995` 需 `α≈−κ ln 0.995≈0.005κ`（此时核近均匀，并不是 GAE(0.995) 的精确等价），不是“α 大”。证明直觉：`log w_l=−α log(1+l/κ)`，在 `l≪κ` 时 `≈−(α/κ)l+O(αl²/κ²)`，局部是几何核；α 越大，下述 Gamma 混合越集中在 `u≈α`（相对宽度 `1/√α`），支撑收缩到 `l≲κ/α`。
3. **严格表示（α>0）**：
```text
(1+x)^(−α) = 1/Γ(α) ∫_0^∞ u^{α−1} e^{−u(1+x)} du,   x=k/κ
```
即幂率核是**指数迹的 Gamma 混合**。这给出可实现路径（Q 点求积/指数和）与“α 大→局部指数”的严格含义；不要把“混合”误写成“等于某个单一 GAE λ”。

**有效记忆长度。**

```text
N_eff(t;α,κ) = (Σ_{l=0}^{L−1} w_l)² / Σ_{l=0}^{L−1} w_l² = 1 / Σ_{l=0}^{L−1} w̃_l²
```

`α=0` 时 `N_eff=L`；`α→∞` 时→1；固定 horizon 下随 α 单调不增（Gamma 混合的随机序；单测数值断言）。报告 t=8/12/15 的 `N_eff` 作为信用视野/方差诊断；只报 α 不够。horizon 归一化让不同 α 的 advantage 尺度可比，否则 PPO 的 advantage normalization/LR 会被核的绝对尺度混淆。

**B.2 可执行单测（`tests/test_credit.py`，CPU，固定向量）。**

```python
import torch
L, kappa = 64, 3.0
k = torch.arange(L, dtype=torch.float64)
def kernel(alpha):
    w = (1 + k / kappa) ** (-alpha)
    return w / w.sum()
```

1. `alpha=0` → 权重全等于 `1/L`（`allclose`），`N_eff=L`。
2. α∈`[0,0.25,0.5,1,2,4,8,16,64,1e3]` → `N_eff` 非增（tol 1e-9）；α=1e3 时 `N_eff<1.01`、`argmax=0`、`w[0]>0.999`。
3. **几何极限**：α=8, κ=1, L=128（此时 `N_eff≈1.01`，非平凡 one-step）；在 λ∈[1e-4,0.999] 网格上取 `argmin KL(w || (1−λ)λ^k)`，断言 `λ*<0.01`、`KL<1e-3`、`cosine≥0.999`；同一 w 对 GAE(0.995) 的 `KL>1` 且 `cosine<0.2`。这条直接检验“α 大≈指数”到底指哪个 λ。
4. **与指数迹对比**：α 网格 × λ 网格输出 cosine/KL 矩阵；断言 α=0 与 uniform 的 cosine=1、α 大与 λ→0 的 cosine→1；非单调情形只记录、不断言。
5. **估计器等价**：`compute_credit(mode="gae")` 与旧 `compute_gae` 在 3–5 步手算轨迹上 `allclose`（γ=1, λ=.995）；覆盖 terminal/truncated/empty batch/all-masked；归一化权重和=1；α=0、κ>0、L=0 无 NaN。
6. **方差/ESS**：`diagnostics["ess"] == 1/(w̃²).sum()`；ESS 随 α 下降；给所有 δ 加常数 c 时，归一化 A 只平移 c。
7. **timebase**：同一 turn 3 个 action，turn 模式用 γ³，decision 模式用 γ¹，断言不混用。
8. **baseline 偏差 toy test**（与 B.3 共用）：3 动作 softmax、固定 `b(a)`，枚举算 `E[∇logπ b]` 非零；双采样与加权修正估计 1e6 次均值≈0；中心化版本**不**≈0。

**B.3 动作条件 baseline / critic：actor 无偏性。**

设 `s~d^π, a~π_θ(·|s)`，回报 `G_t`。score-function 估计为

```text
g = E[ ∇_θ log π_θ(a|s) (G_t − b(s,a)) ]
```

对任意 baseline `b`（critic 参数 stop-grad）：

```text
E[∇logπ b(s,a)] = Σ_a ∇π(a|s) b(s,a)
                 = ∇_θ E_{a~π}[b(s,a)] − E_{a~π}[∇_θ b(s,a)]
                 = ∇_θ E_{a~π}[b(s,a)]        (stop-grad)
```

- `b=b(s)` 与动作无关 ⇒ `E[b]` 不依赖 θ ⇒ 偏差为 0，无偏。
- `b=b(s,a)` 依赖动作 ⇒ `∇_θ E_{a~π}[b]` 一般 ≠0 ⇒ **有偏**。反例：softmax 下 `b(a)=1[a=0]`，偏差为 `∇π(0|s)≠0`。
- **中心化不是修正**：`b̄(s)=Σ_{a'}π(a'|s)b(s,a')` 只依赖 s，`E[∇logπ b̄]=0`，所以 `E[∇logπ(b−b̄)] = E[∇logπ b]`，偏差原样保留。把“减掉策略均值”当成无偏修正，是常见错误。
- **双采样修正**：独立抽 `a'~π(·|s)`（与 a 独立），用
```text
ĝ = ∇logπ(a|s) (G_t − b(s,a'))
E[ĝ] = ∇J − E_{a'}[b] · E_a[∇logπ(a|s)] = ∇J
```
  无偏；代价是两次采样/更高方差。
- **加权修正（显式偏差项）**：对离散动作可精确求和
```text
ĝ_w = ∇logπ(a|s)(G_t − b(s,a)) + Σ_{a'} π(a'|s) ∇logπ(a'|s) b(s,a')
E[ĝ_w] = ∇J − E[∇logπ b] + E[∇logπ b] = ∇J
```
  代价是每个 state 一次全动作求和（本任务 274 个动作，mask 后可行），且 b 必须 stop-grad；若第二项用采样估计，就退化为双采样/更高方差。其他加权/DR 版本只有在显式写出并证明其 score 加权期望为 0 时才可用，不能默认。
- **`Q−V` 是 advantage，不是 baseline**：若 `A(s,a)=Q(s,a)−V(s)`，则 `E[∇logπ A]=∇J`（`V(s)` 项因 `E[∇logπ V(s)]=0` 消失），这是合法的；有偏的是把 `Q(s,a)` 当作 `G_t` 的 baseline 去减（`G−Q`）。两者不要混为一谈。

**工程上如何安全使用（一句话）**：把动作条件评价严格放在 critic——`Q(s,a)` 只进 value/TD loss 与 `A=Q−V` 的 advantage 计算；actor 的 baseline 保持 `b(s)`，若要用 `b(s,a)` 必须走独立动作双采样或显式加权修正，并在 `tests/test_credit.py` 里用枚举验证 `E[∇logπ b]=0`；开关 `baseline_action_dependent` 默认 0，置 1 时强制该测试与日志。

**落地与冲突（在 B.1–B.3 约束下）。**

- `γ=1` 且 episode 约 200 个 learner decision，现有 `λ=0.995` 的 action-step 时间尺度；`Q(s,a)` target 必须以行为策略下实际 next state 计算，并记录 behavior logp、合法 mask 和 target action。
- 如在 turn 边界聚合，明确 SMDP duration `k`：`γ^k`、trace `(γλ)^k`，不能把一个 turn 的动作优势重复计权。先离线输出 action-conditioned TD error、turn-boundary value error、`N_eff`。
- Power-law memory 只作为 advantage estimator 的**互斥** plugin：`kernel_mode=gae|fractional|powerlaw`，固定 horizon 核归一化，terminal/bootstrap 的定义和 mask 明确；不要同时改 reward、γ、λ、critic architecture。
- 先做 dual critic `V(s)` + lightweight `A_action(s,a)`（仅合法动作 logits 或 sampled action），再考虑完整 Q head；Q 误差过大时回退 V GAE。
- **动作条件 critic 不直接替换 actor baseline**：离线诊断若显示 `E[∇logπ b]` 显著非零，只允许进 critic，不允许进 actor；除非双采样/加权修正通过单测。

**数据/改动。** 现有冻结轨迹足以做 estimator replay 和 40–60 iter；缺少稳定的 rollout-level value loss/action TD diagnostics，需要 records 落 `turn_id/action_idx/decision_in_turn/duration/done/old_logp/value/next_value/baseline_action_dependent`，以及独立评测的短后续回报。不得把 s10 无注入重采轨迹称为训练分布。

**收益与风险。** 可能改善升本/前期经济的 credit assignment；风险是 off-policy Q 偏差、长尾高方差、动作头与 PPO ratio 双重不一致、按动作数过度加权、`γ=1` 下未终止轨迹的泄漏，以及误把动作条件 baseline 当无偏控制变量。当前证据只支持“待验证”，不支持先做它。

**最小验证。** 不先改 reward；固定轨迹计算三 estimator 的 action/turn advantage 相关性、`N_eff`、ESS、terminal fraction，以及 baseline 偏差 toy test。通过离线门后，以同 checkpoint、同 RNG 跑 40–60 iter，仅替换 estimator；同时 A/B `lambda=0.995` 与默认旧 GAE。判据同 A 与 §2.3（人类面板 + 质量面板门禁）；另要求 `N_eff@t15` 不超过预注册上限、ESS 下降<50%、baseline 诊断通过。若 value loss/ratio/NaN 或早期强度无改善，恢复旧 GAE。

### C. 显式信念状态

**核心思想。** 不完全信息下策略不应把当前可见 observation 当作完整状态；维护对对手隐藏 board/hand、英雄效果、资源/流派的 belief，并以 belief embedding 作为 value/policy 输入或辅助预测目标。belief 必须是“根据历史和观测的后验”，不是偷看真实注入状态。

**代表工作/启发。** ReBeL（Brown et al.，belief-state search + self-play）；Deep CFR/PSRO 的不完全信息策略；Bayes-adaptive MDP、POMCP/ISMCTS；Deep Recurrent Q-Network 与 predictive-state representations。当前项目已有 `hsbg/az/belief.py`/search 栈，优先做可校准的监督 belief encoder，不直接上昂贵 MCTS。

**落地。**
- `BeliefEncoder(history, visible_board, action/event history)` 输出 opponent archetype、tier、board strength quantiles、hidden effects 的分布与 uncertainty；使用 set/sequence encoder，历史长度按 turn 截断。
- 训练时只能从观测构造输入；完整真实帧仅作 label，按字段可见性隔离，禁止把 hidden counters/gold 注入 policy features。
- 辅助 loss：对隐藏 tier/strength bucket/是否持有关键 tribe 做 masked CE/quantile loss；用 temperature calibration、Brier/ECE 报告；高 entropy 时降低 belief gate 或不 bias。
- policy/value 的新增 concatenation 接口默认 0；checkpoint meta 写 belief schema/hash，旧 checkpoint 能加载。

**数据/改动。** 现有 1,961 准完整帧和 Firestone 500 局可做 prototype，但标签覆盖不完整、build 混杂；需要按 source game 隔离 train/dev/exam，额外收集 ≥200 独立源局或明确只做同库泛化。不能声称真实完整隐藏状态校准。

**收益与风险。** 对中后期站位和针对性购买有潜力，减少“看到强敌仍按弱 bot 规划”；风险是 belief 泄漏、分类器错误导致策略误导、非平稳对手与分布外版本。belief 预测准确不保证 rank 改善，需动作后效应评估。

**最小验证。** 先冻结策略做 belief probe：与均匀/last-observation baseline 比较 NLL、Brier、ECE 和 hidden strength bucket；再 40–60 iter 只开 belief auxiliary，最后开小门控（≤0.1）。判据同 A；额外要求高 entropy 样本不劣于关闭 gate，collect<15%；失败即只保留离线探针，不接 policy。

### D. 分层强化学习

**核心思想。** 约 200 步 episode 有明显阶段：前期经济/稳血，中期升本/发现，后期构筑/站位。manager 选择短期 option/skill，worker 在合法动作内执行；option termination 必须受回合边界、死亡、升本/构筑事件约束，不能让高层目标稀释可学习的密集 action。

**代表工作/启发。** Options framework（Sutton, Precup, Singh）；MAXQ；FeUdal Networks manager-worker；HIRO/HAC；option-critic。此任务优先“受监督的阶段/skill discovery + PPO worker”而不是完全无监督 option-critic，避免 200 步样本不足。

**落地。**
- 三层初始 skills：`economy`、`level_up/discover`、`board_build/position`；阶段只作 proposal，不硬屏蔽动作。
- `manager` 每 1–4 个 learner turn 选 option，worker policy 输入 option embedding；option termination 在 planned turn、关键事件或异常时触发。
- manager advantage 使用 option duration 的 SMDP return；worker 保持旧 PPO/G​AE，分开 entropy/KL budget。若 manager 与 worker 同一 logits 共享 trunk，必须防止 option ID 泄漏造成旧 checkpoint 不兼容。
- skill labels 从人类前缀动作序列启发式生成（turn、tier、动作族、board delta），再允许 soft discovery；不要把三阶段当真实硬边界。

**数据/改动。** 现有 BC/Firestone 数据够做 skill segmentation 原型；缺少跨 game 稳定的 option label 和 manager target，需要 ≥200 独立 game-group、每 option 至少 5000 transition（或退回两个 option）。

**收益与风险。** 可能将升本/经济决策从每动作噪声中分离，提升长程一致性；风险是 options collapse、manager reward hacking、短 episode 中高层更新不足、worker 分布漂移、与 move-guard/动作 mask 冲突。

**最小验证。** 先离线测 segmentation purity/coverage/平均 option 长度；以固定 worker + rule manager 跑 40–60 iter，再学习 manager。判据同 A，另加 option coverage（每个 option ≥5% 且不单一占比>90%）、termination 合法率、episode length 不异常；失败删除 manager，回退 flat PPO。

## 2. 优先级、依赖与并行计划

### 2.1 排序

**P0：A（受约束的人类监督/场面题） → P1：C（belief auxiliary） → P2：D（受监督分层） → P3：B（信用重构）。**

理由：A 最直接对准强度缺口，已有 BC 数据、DPO 接口和人类库，能够先做“强度可学性”判定；C 依赖稳定的可见性 schema 和 A 的场面标签，但可先并行做离线 probe；D 需要确认强度目标/skill 标签且改变 rollout 分布；B 会触碰 PPO advantage、γ=1、λ/SMDP，最容易造成不可解释回归，必须在独立 exam 可分辨且确有 credit bottleneck 后再做。

### 2.2 可并行/必须串行

可并行：A 的标签审计、C 的 belief probe、D 的离线 segmentation、B 的 estimator replay 分析；它们不得共享未冻结的 checkpoint 或 exam 数据。必须串行：先完成独立冻结 exam/固定评测协议；A 先过离线可学性和 Move 安全门，才能进入训练；C 只有防泄漏/校准通过才接 policy；D 在 A/C 的状态 schema 稳定后再做；B 的真正 PPO A/B 最后做，且不可与其它方向同时改 estimator、reward、模型容量或数据剂量。

### 2.3 共同晋级门

每个方向的 40–60 iter 最小实验都须：

**人类面板 + 质量面板门禁**（所有方向统一执行）：

| 门禁项 | 阈值 |
|---|---|
| human 面板 Δ（配对，同 seed/seat） | ≤ −0.10 且 95% CI 上界 < +0.05 |
| human top4 | ≥ 基线 −2pp |
| **强度比 t12 / t15**（质量面板） | 各自相对基线 **+10%** 以上（核心靶点） |
| tier≥5 @ t12 / t15 | 不低于基线 |
| 出局强度 p50 | 不低于基线 |
| collect 增幅 | < +15%（只统计训练采集；评测耗时不计入，见 §5.4） |
| 评测成本 | human 256 局 ≈194 s、quality 64 局 ≈92 s；单列预算，不参与 collect 门 |
| 硬错 | illegal / truncation / 注入错误 = 0 |
| 回退 | 任一不达标 → 回退该单因素，记录进 `EXPERIMENTS` |

- 两本预算：评测（human 256 + quality 64）与训练采集分开记账；评测成本不计入 collect 增幅（§5.4）。
- 不以单次最佳 checkpoint 晋级，预先固定 checkpoint/seed；显存/CPU 峰值、NaN 同时记录。
- t9/t12/t13/t15 强度比、tier≥5、存活率按有条件/无条件口径报告；核心强度门按预注册的无条件口径计算，相对提升为 `(candidate/baseline−1)×100%`，t12/t15 各自须 ≥10%，同时报告 CI；这些是工程门，而非真实人类阈值。
- 旧 human panel 仅 development；不得在同一 panel 反复挑低点。遵守 [REVIEW_PLATEAU](REVIEW_PLATEAU.md) 的独立源组、配对差值和 exam 隔离原则。

## 3. 通用接口、目录和默认关闭规格

### 3.1 建议文件边界

不得直接把四方向逻辑塞进 `ppo.py` 巨型函数；建议新增：

- `hsbg/az/train/human_targets.py`：样面题 schema、标签/版本/可见性 mask、strength quantile、pairwise target。
- `hsbg/az/train/credit.py`：GAE、fractional、power-law kernel、SMDP duration；纯函数。
- `hsbg/az/train/belief_encoder.py`：belief model、calibration、masked auxiliary loss。
- `hsbg/az/train/options.py`：option/manager/worker 状态机、termination、SMDP returns。
- `hsbg/az/train/experiment_manifest.py`：seed、source-group split、config/hash、exam manifest。
- 接线仅改 `ppo.py`、`ppo_trainer.py`、`parallel_collect.py`、`process_pool.py`、`scripts/train_entity_sync.py`；现有 `bc_aux.py`、`dpo_upgrade.py`、`human_obs_full.py`、`archetype_bias.py` 复用，不复制编码器。
- 测试：`tests/test_human_targets.py`、`test_credit.py`、`test_belief_encoder.py`、`test_options.py`，另补 PPO legacy/serialization tests。

### 3.2 配置与逐位等价

所有开关默认：`human_target_coef=0`、`credit_mode=gae`、`belief_aux_coef=0`、`belief_policy_coef=0`、`options_enabled=0`。配置还需：`target_horizon={1,3,8}`、`target_strength_log=1`、`credit_alpha/cutoff/normalize`、`credit_timebase=decision|turn`、`belief_history_turns`、`belief_temperature`、`belief_min_confidence`、`option_max_duration`、`option_entropy_coef`。

关闭时：不加载数据、不消耗 RNG、不增加 records 字段（或写完全相同的旧 schema）、不改变 action mask/old_logprob/GAE、无新 meta/stats 键；旧 checkpoint 可加载并产生相同动作序列。启用时 checkpoint 必须记录 schema version、source manifest hash、git revision、model/head shapes、effective coefficients、actual exposure、data build/version。

### 3.3 数据结构

```text
SceneTarget {
  problem_id, source_group, build_id, turn, seat, visibility_mask,
  obs_hash, candidate_actions[], expert_action_set[],
  strength_before, strength_after[horizon], tier_after, survival_after,
  label_quality, target_version
}
BeliefTarget { source_group, turn, opponent_seat, visible_mask,
  hidden_bucket, probability_target, confidence, label_version }
TransitionRecord { game_id, seat, turn, decision_idx, action, old_logp,
  reward, done, value, next_value, duration, option_id, visible_hash }
```

所有数值定义写入 JSON schema；source_group 按玩家/对局/整局 turn 连通分组，禁止逐帧随机切分造成泄漏。

## 4. 各方向实现规格

### 4.1 A 开发清单

**接口。** `build_scene_targets(records, visibility_policy, horizon)`、`human_target_loss(model,batch)`、`strength_value_loss`、`pairwise_action_loss`；PPO `PPOConfig.human_target_coef=0`，训练器 lazy load target pool，独立 `target_rng`，按 iteration 采样一次。

**训练/评测。** `total=ppo+seq+bc+dpo+[target]`；target 只进同一 backward，不改 ratio。报告 CE、pairwise accuracy、strength calibration、Move 概率质量、moves/turn。A 与已有 BC 共用 `bc_obs_batch`，DPO 仍只 upgrade；禁止重复加载/重复前向。场面题标准解必须保留多解集合和“未知”标签。

**单测/文档。** 覆盖 schema round-trip、mask 不泄漏、同 seed 采样、空池/重复样本、horizon terminal、Move mask、coef=0 bitwise、旧 checkpoint；更新 `docs/BC_PRETRAIN.md` 或新增 `docs/HUMAN_TARGETS.md`，记录数据版本与失败实验。

**失败/回退。** human 不过门、strength head 校准差、moves/turn>+15%、或 §2.3 任一门禁不达标即 `coef=0`/删除 head；不得用更长 BC-only 代替。

### 4.2 B 开发清单

**接口。** `compute_gae` 保持旧签名；新增 `compute_credit(records, mode, gamma, lam, duration, alpha, cutoff)` 返回同 shape advantage、diagnostics。`mode=gae` 必须字节/浮点等价；power-law kernel 在 d=0、terminal、truncation、empty batch 有明确单测。

**关键约束。** 若 turn base，`duration` 是 learner action 数或明确 elapsed turn，不能混用；SMDP return 使用 duration 折扣；action-conditioned critic 必须记录 behavior policy、合法 mask、target action，不能把 chosen action 以外 logits 当 Q 标签。critic 更新先独立 loss，再接 actor。actor 的 baseline 默认只用 `V(s)`；动作条件 `Q(s,a)` 只进 critic/TD loss 与 `A=Q−V`，若无双采样修正禁止直接进 actor（§B.3）。

**单测/文档。** 手算 3–5 步轨迹、γ=1、λ=0.995、terminal/truncated、option duration、all-masked、normalization；幂率核按 §B.1–B.2 测 α→0/α→∞、`N_eff` 单调、与几何核的 KL/cosine、horizon 归一化；动作条件 baseline 按 §B.3 测双采样无偏与中心化无效；文档写“估计器不是策略改进证明”。

**失败/回退。** NaN、effective sample size 下降、早期 value error 上升、ratio/clip 异常、旧主指标不达门即回到 GAE；不能仅因为离线 terminal weight 变大就晋级。

### 4.3 C 开发清单

**接口。** `BeliefEncoder.forward(obs_history, masks)`、`belief_aux_loss(pred,target,mask)`、`calibrate_belief`；策略侧 `belief_policy_coef=0` 时输入零向量或完全不传 kwargs，保证旧模型 shape 兼容。新增 head 维度写 meta，无法加载时显式报错而非静默随机初始化。

**不完全信息约束。** 输入仅用 learner 视角已见字段、过去 action/event 和合法公共信息；禁止 opponent `player_json`、hidden counters、future board、注入 payload。标签可来自完整帧但只在 loss 使用，严格 source/time split；对每字段标 `available/unknown`。

**单测/文档。** 泄漏测试（改 hidden label 不改输入）、mask permutation、历史截断、温度校准、entropy gate、batch padding、旧 checkpoint；新增 `docs/BELIEF_STATE.md`，列可见性矩阵与 exam 限制。

**失败/回退。** hidden probe 好但 action/human 不改善，停止 policy gate；高熵样本劣化、ECE 恶化或按版本迁移失败时仅保留离线报告。任何高置信错误偏置均触发紧急关闭。

### 4.4 D 开发清单

**接口。** `OptionState`（option_id/start_turn/start_decision/elapsed/termination_reason）、`ManagerPolicy`、`WorkerPolicy`、`should_terminate`、`compute_smdp_option_return`。默认 flat worker 与旧 policy 完全相同；manager 不改合法动作 mask。

**边界。** option 最短/最长 duration 明确；新 turn、death、upgrade、discover、forced end-turn 可 termination；不跨 game/seat 混状态。manager logprob 与 worker logprob 分开记录；PPO ratio 不交叉。option 不得把 move-guard 的每 turn 状态跨边界。

**单测/文档。** termination 优先级、episode 200-step 截断、option duration 折扣、worker action mask、manager/worker RNG 独立、collapse/coverage、旧 checkpoint；新增 `docs/OPTIONS_HRL.md`。

**失败/回退。** option coverage<5% 或任一 option>90%、duration 异常、worker legal rate/强度退化、collect>15% 即关闭 manager；保留 skill segmentation 供后续分析。

## 5. 评测与 A/B 协议

### 5.1 固定考试

只与人类面板测：human 面板固定 **256 局（评测约 194 秒）**，另配 **质量面板 64–96 局**；不再安排 bot 评测。质量面板用于强度/tier/出局强度诊断，不作为额外的弱对手名次门。评测耗时为既有参考，不是本次运行结果；本次仅修改文档，不启动训练或评测、不占 GPU。候选与基线同 seed/seat 配对，统一执行 §2.3 门禁；任一不达标回退该单因素并记录进 `EXPERIMENTS`。

先按 [REVIEW_PLATEAU](REVIEW_PLATEAU.md) 冻结 checkpoint hash、seed、引擎/卡表版本、温度、move-guard、注入语义和 source-group manifest。用户主面板可做 development，但不能把其最佳点当独立证据。正式 exam 按整局 source group 隔离；缺独立源组就明确“同库泛化”，不声称人类泛化。

### 5.2 必报表

主终点 human mean rank；次终点 top4/win。过程固定 t=9/12/13/15：学习者存活率、全大厅存活玩家人数、战斗后随从数、无条件/存活条件强度比、tier≥5、真实战团实际命中/拒绝/缺字段、每 turn action/move。report `learner p50 / median human same-turn,stratum`，不得用出局 800 直接除 t15 26,500。

### 5.3 统计规则

逐局配对 `D=rank_candidate-rank_baseline`，报告均值、95% CI、source-group cluster bootstrap；不能以多次重播同一源组冒充独立样本。checkpoint 选择规则预注册；不允许看 exam 后调参。CI 上界、门禁阈值、失败原因全部写 experiment ledger；bot 面板不再作为非劣/晋级门（已停用）。

### 5.4 两本预算：评测成本与训练采集增幅分开

**结论：评测耗时与训练采集开销是两本账、两个门禁；评测成本不计入 `collect` 增幅。**

| 预算 | 基线实测 | 门禁 | 记账字段 |
|---|---:|---|---|
| human 面板 256 局（auto，seed 420000） | **193.8 s**（s14 @10,027,241 decisions，`runs/az_entity_s14/eval/history.json`） | ≤240 s/次；不得阻塞训练 iter | `eval_wall_s.human` |
| 质量面板 64 局（tier/强度/出局） | **92.4 s**（64 局 bot 面板实测，`runs/ab_move_guard/eval/A_bot64.json` 的 `details.seconds`；`quality_monitor --games 64` 同量级） | ≤120 s/次 | `eval_wall_s.quality` |
| 训练采集 collect（192 games/iter） | s14 约 **3.9–4.1 s/iter、6.6–7.8k dec/s**（`runs/az_entity_s14/history.jsonl` 的 p50） | 相对基线 **<+15%**（wall 或 dec/s 任一不退化超过 15%） | `collect_s`、`decisions_per_s` |

规则：

1. 评测异步（`--eval-async 1 --eval-device cuda:7`），同一时间只跑一个 panel；到点未完成记 `eval_skipped`，不阻塞训练。`eval_wall_s` 单独入账，**从 `collect_s` 和 <15% 采集门中排除**。
2. 若新方法使单次评测 >240 s（human）或 >120 s（quality），或单 checkpoint 评测总时长 >360 s，这属于**评测预算回归**：报告并做面板/分片优化，但不消耗 collect 预算，也不能拿它当训练变慢的借口。
3. 采集门只用相同 `games=192`、`processes=16`、`gpus=3,4,5` 的 **≥20 个连续 iter 的 p50**；排除 eval、checkpoint save/reload 的 wall；单 iter 尖峰不判过/不过。显存峰值、NaN、illegal/truncation 另列硬错。
4. 两本账都写入 manifest/ledger：`eval_wall_s`、`collect_s`、`decisions_per_s`、`cuda_peak_mb`。评测便宜但采集贵的方法仍失败；采集免费但评测贵的方法仍需评测预算批准。
5. human 256 局是主测量；质量 64 局只做过程诊断（tier/强度/出局强度），不能替代 human 主面板，也不单独构成晋级证据。

## 6. 2–3 阶段路线图（每阶段 60–120M decisions）

### Stage V2-A：监督强度可学性（60–80M）

先完成独立 exam/manifest 和 A 离线 scene target；训练只开小 `human_target_coef`，保留准完整 fidelity、move-guard、DPO 现有经审计配置，冻结容量与暴露策略。验证：t9–12 tier/strength 是否随 human target 上升，Move 不爆，rank 是否达到共同门禁。晋级：§2.3 人类面板 + 质量面板门禁全部通过（含 t12/t15 强度比各自相对基线 ≥+10%）；否则回退并停止 A 预算。

### Stage V2-B：belief 或受监督 options 单因素（80–100M）

只选 A 通过后的一个方向：优先 C auxiliary→小 policy gate；若 C 离线不可学，改 D 的 rule-manager→learned-manager。只改一个因素，固定 V2-A 的数据/暴露/评测。晋级要求在独立 seed/固定 checkpoint 规则下复制 A 的 rank 与强度收益，不得只改善单项过程指标；belief 需校准/无泄漏，options 需 coverage/duration 门。

### Stage V2-C：信用分配候选（80–120M）

仅在独立 exam 已可分辨且 V2-A/B 显示早期 action/value error 仍是瓶颈后，做 B 的 GAE vs power-law/fractional 单因素对照；先回放 estimator 再训练。固定 γ=1、旧 reward、同模型容量和暴露；报告 turn/SMDP 与 action-conditioned critic 的独立贡献。晋级条件除共同门外，必须 t7 升本/早期经济的 action value calibration 和 t12/t15 强度同步改善；否则回退 GAE，不继续堆长程记忆。

每阶段都保存 `manifest.json`、完整 args、数据 hash、git revision、checkpoint hash、逐局结果、CI、失败/回退原因；60–120M 是预算上限，不是保证训练到末尾或可挑最佳。

## 7. 团队协作与记忆机制（可直接作为 `docs/AGENT_TEAM.md` 骨架）

### 7.1 角色

- **Lead/裁决者**：维护本计划、门禁、最终 merge；不同时写算法实现。
- **Evidence auditor**：只读审计数据、版本/泄漏/统计，维护 `docs/EXPERIMENT_LEDGER.md`。
- **Human-target owner**：`human_targets.py`、BC/DPO 对接及题目 manifest。
- **Credit owner**：`credit.py`、GAE/SMDP/power kernel；不得改 reward/模型容量。
- **Belief owner**：`belief_encoder.py` 与可见性矩阵；负责 leakage tests。
- **HRL owner**：`options.py` 与 segmentation；负责 option coverage/termination。
- **Eval/repro owner**：固定 exam、seed、配对统计、人类面板 + 质量面板门禁。
- **Infra/test owner**：序列化、bitwise legacy、CPU smoke、verify_all；不改变实验假设。

每个任务 claim 前写 `owner/scope/input revision/output/acceptance/expiry`；一个文件同一时间只有一个 writer。遵循 [AGENTS.md](../AGENTS.md) 的现有目录写范围，算法 owner 不越界写 Rust/数据/评测。

### 7.2 决策记录模板

```markdown
## DEC-YYYYMMDD-NN: 标题
- 状态: proposed|accepted|rejected|superseded
- 问题/假说:
- 证据: 文档/commit/manifest/checkpoint hash
- 选择与未选项:
- 影响范围: 文件、配置、数据、评测
- 回滚: 开关/旧 checkpoint/commit
- 责任人与复核人:
- 生效日期与失效条件:
```

每次改变系数、数据过滤、评测口径、checkpoint 选择规则必须新增 DEC；禁止在聊天中只留不可检索决定。

### 7.3 实验台账模板

```markdown
## EXP-YYYYMMDD-NN
- 假说/方向: A|B|C|D
- parent checkpoint/hash、代码 revision、数据 build/hash:
- train seed / eval seed / decisions / checkpoint rule:
- 完整 config（含所有默认值）:
- 变更单因素、关闭对照、实际 exposure/applied/attempt:
- human rank mean/95% CI、top4、illegal/truncation/注入错误、collect 增幅:
- t9/t12/t13/t15 strength ratio（条件/无条件）、tier≥5、survival、出局强度 p50:
- 失败/异常/NaN/回退:
- 结论: advance|hold|revert|invalid
```

### 7.4 间断开发规则

1. 开始工作先读本文件、最新 ledger、最近 DEC 和 `git status`；结束前写“已完成/未完成/下一步/风险”。
2. 每个实验都生成可复制命令、环境版本、seed、manifest hash；不使用“最佳历史点”而不登记选择规则。
3. 任何事实冲突以最新可追溯原始 artifact 为准；用户委托数字若尚未落仓库，标为 `reported_not_verified`，不得伪造为文档实测。当前 `docs/TRAINING_PLAN_AUTOTAVERN.md` 不存在；引用论文训练背景时使用 [AUTOTAVERN_PAPER_TRAINING](AUTOTAVERN_PAPER_TRAINING.md)，并记录该缺失。
4. 先查 ledger/DEC/grep 再提新实验，重复失败方向必须链接旧结论（BC-only、MCTS、自对弈、势函数、tier-target、Firestone 混池已证伪）。
5. 只读分析不启动训练；GPU/长评测必须由 Lead 明确批准并登记资源预算。
6. 合并前执行文档链接/JSON schema/纯 CPU tiny tests；算法改动再由对应 owner 执行完整门禁。失败实验也必须入账，不得删除 runs 或覆盖旧结果。

## 8. 引用清单与研究参考

### 8.1 仓库事实

- [PRESSURE_AUDIT](PRESSURE_AUDIT.md)：压力、暴露、GAE 和配对审计。
- [FIDELITY_INJECTION](FIDELITY_INJECTION.md)：准完整库字段覆盖和注入语义。
- [BC_PRETRAIN](BC_PRETRAIN.md)、[DPO_UPGRADE](DPO_UPGRADE.md)：已有人类监督与 upgrade DPO 的结果/接口。
- [ARCHETYPE_BIAS](ARCHETYPE_BIAS.md)：流派分类、线上置信度和软偏置。
- [REWARD_SHAPING](REWARD_SHAPING.md)、[TIER_TARGET](TIER_TARGET.md)、[MOVE_GUARD](MOVE_GUARD.md)：已证伪/应复用的现有开关。
- [REVIEW_PLATEAU](REVIEW_PLATEAU.md)：旧面板选点、独立 exam 和统计规则。
- [PROJECT_MEMORY](PROJECT_MEMORY.md) §1.3/§5：开发面板逐点、s14 命令行、强度比/tier 口径与证据边界。
- [EVAL_PANELS](EVAL_PANELS.md)：human 面板协议、注入计数与“bot 面板降级为回归线”的说明。
- [AUTOTAVERN_PAPER_TRAINING](AUTOTAVERN_PAPER_TRAINING.md)：论文训练背景；论文记录 18M + 纯 PPO + 7 library seats + γ=1/λ=.995 + 300 iter、约 310M decisions/stage、exam 24,576 局/点、平均名次 3.40→2.33，且搜索未来泄漏在重播种后消失。用户指定的 `TRAINING_PLAN_AUTOTAVERN.md` 当前不存在。

### 8.2 外部方法参考（链接与核验状态）

> 核验方式：2026-10-31 用 `web_fetch` 读取 arXiv abs 页、书目页或 Crossref DOI 记录，核对**标题、作者、venue**；ScienceDirect 对自动抓取返回 403，改用 UT Austin 课程书目页交叉核对（标题/作者/卷期/页码）。未读取到原文正文的，只算“题录核验”，不算“方法复现核验”。核验不了的明确标 `未核实`。

**已核验题录（arXiv/官方页）**

- **Ng, Harada & Russell (1999)**，*Policy Invariance Under Reward Transformations: Theory and Application to Reward Shaping*，ICML 1999, pp. 278–287。作者页 [PDF/PS](http://robotics.stanford.edu/~ang/papers/shaping-icml99.ps)；书目交叉核对 [UT Austin](https://www.cs.utexas.edu/~shivaram/readings/b2hd-NgHR1999.html)。状态：题录已核验。
- **Sutton, Precup & Singh (1999)**，*Between MDPs and Semi-MDPs: A Framework for Temporal Abstraction in Reinforcement Learning*，Artificial Intelligence 112(1–2):181–211。DOI [10.1016/S0004-3702(99)00052-1](https://doi.org/10.1016/S0004-3702(99)00052-1)；书目/PDF 入口 [UT Austin](https://www.cs.utexas.edu/~shivaram/readings/b2hd-SuttonPS1999.html)。状态：题录已核验（Crossref DOI 记录：Artificial Intelligence 112(1–2):181–211, 1999）；ScienceDirect 直连 403，未读正文。
- **GAE** — Schulman, Moritz, Levine, Jordan & Abbeel (2015/2016)，*High-Dimensional Continuous Control Using Generalized Advantage Estimation*。[arXiv:1506.02438](https://arxiv.org/abs/1506.02438)。状态：题录已核验。
- **PPO** — Schulman, Wolski, Dhariwal, Radford & Klimov (2017)，*Proximal Policy Optimization Algorithms*。[arXiv:1707.06347](https://arxiv.org/abs/1707.06347)。状态：题录已核验。
- **Retrace(λ)** — Munos, Stepleton, Harutyunyan & Bellemare (2016)，*Safe and Efficient Off-Policy Reinforcement Learning*。[arXiv:1606.02647](https://arxiv.org/abs/1606.02647)。状态：题录已核验。**注意**：`arXiv:1512.04455` 是 Heess et al. 的 *Memory-based control with recurrent neural networks*，不是 Retrace；不要混用。
- **V-trace / IMPALA** — Espeholt et al. (2018)，*IMPALA: Scalable Distributed Deep-RL with Importance Weighted Actor-Learner Architectures*。[arXiv:1802.01561](https://arxiv.org/abs/1802.01561)。状态：题录已核验。
- **DAgger** — Ross, Gordon & Bagnell (2011)，*A Reduction of Imitation Learning and Structured Prediction to No-Regret Online Learning*。[arXiv:1011.0686](https://arxiv.org/abs/1011.0686)。状态：题录已核验。
- **Decision Transformer** — Chen et al. (2021)，*Decision Transformer: Reinforcement Learning via Sequence Modeling*。[arXiv:2106.01345](https://arxiv.org/abs/2106.01345)。状态：题录已核验。
- **T-REX** — Daniel S. Brown, Goo, Nagarajan & Niekum (2019)，*Extrapolating Beyond Suboptimal Demonstrations via Inverse Reinforcement Learning from Observations*。[arXiv:1904.06387](https://arxiv.org/abs/1904.06387)。状态：题录已核验；这是 Daniel S. Brown，不是 Noam Brown。
- **ReBeL** — Noam Brown, Bakhtin, Lerer & Gong (2020)，*Combining Deep Reinforcement Learning and Search for Imperfect-Information Games*。[arXiv:2007.13544](https://arxiv.org/abs/2007.13544)。状态：题录已核验；标题本身不含“ReBeL”，摘要给出该名称。若计划中的 `ReBel` 指另一篇论文，则 `未核实`。
- **Deep CFR** — Noam Brown, Lerer, Gross & Sandholm (2019)，*Deep Counterfactual Regret Minimization*。[arXiv:1811.00164](https://arxiv.org/abs/1811.00164)。状态：题录已核验。
- **HIRO** — Nachum, Gu, Lee & Levine (2018)，*Data-Efficient Hierarchical Reinforcement Learning*，NeurIPS 2018。[arXiv:1805.08296](https://arxiv.org/abs/1805.08296)。状态：题录已核验。
- **HAC** — Levy, Konidaris, Platt & Saenko (2019)，*Learning Multi-Level Hierarchies with Hindsight*，ICLR 2019。[arXiv:1712.00948](https://arxiv.org/abs/1712.00948)。状态：题录已核验；HAC 不是 Nachum 的 HIRO，二者不要并称同一作者。
- **FeUdal Networks** — Vezhnevets, Osindero, Schaul, Heess, Jaderberg, Silver & Kavukcuoglu (2017)，*FeUdal Networks for Hierarchical Reinforcement Learning*。[arXiv:1703.01161](https://arxiv.org/abs/1703.01161)。状态：题录已核验。
- **Option-Critic** — Bacon, Harb & Precup (2017)，*The Option-Critic Architecture*，AAAI 2017。[arXiv:1609.05140](https://arxiv.org/abs/1609.05140)。状态：题录已核验。
- **AlphaZero** — Silver et al. (2017)，*Mastering Chess and Shogi by Self-Play with a General Reinforcement Learning Algorithm*。[arXiv:1712.01815](https://arxiv.org/abs/1712.01815)。状态：题录已核验。
- **SAC** — Haarnoja, Zhou, Abbeel & Levine (2018)，*Soft Actor-Critic: Off-Policy Maximum Entropy Deep Reinforcement Learning with a Stochastic Actor*。[arXiv:1801.01290](https://arxiv.org/abs/1801.01290)。状态：题录已核验。
- **PSRO** — Lanctot et al. (2017)，*A Unified Game-Theoretic Approach to Multiagent Reinforcement Learning*，NeurIPS 2017。[arXiv:1711.00832](https://arxiv.org/abs/1711.00832)。状态：题录已核验。
- **Transformer-XL** — Dai et al. (2019)，*Transformer-XL: Attentive Language Models Beyond a Fixed-Length Context*。[arXiv:1901.02860](https://arxiv.org/abs/1901.02860)。状态：题录已核验。
- **Compressive Transformer** — Rae, Potapenko, Jayakumar & Lillicrap (2019)，*Compressive Transformers for Long-Range Sequence Modelling*。[arXiv:1911.05507](https://arxiv.org/abs/1911.05507)。状态：题录已核验。
- **RWKV** — Peng et al. (2023)，*RWKV: Reinventing RNNs for the Transformer Era*。[arXiv:2305.13048](https://arxiv.org/abs/2305.13048)。状态：题录已核验。

**未核实 / 无 arXiv 的条目（实现前补原文，不得当已核验引用）**

- **AlphaStar** — Vinyals et al. (2019)，*Grandmaster level in StarCraft II using multi-agent reinforcement learning*，Nature 575:350–354。DOI [10.1038/s41586-019-1724-z](https://doi.org/10.1038/s41586-019-1724-z)。状态：题录已核验（Crossref DOI 记录：Nature 575(7782):350–354, 2019）；Nature 页面反爬，未读正文。
- **POMCP** — Silver & Veness (2010)，*Monte-Carlo Planning in Large POMDPs*，NeurIPS 2010。状态：`未核实`（无 arXiv；需补 NeurIPS 官方页）。
- **ISMCTS** — Cowling, Powley & Whitehouse (2012)，*Information Set Monte Carlo Tree Search*，IEEE TCIAIG。状态：`未核实`。
- **Watkins Q(λ)** — Watkins (1989) 博士论文 / Watkins & Dayan (1992)。状态：`未核实`（无 arXiv）。
- **Peng's Q(λ)** — Peng & Williams (1996)。状态：`未核实`。
- **MAXQ** — Dietterich (2000)，*Hierarchical Reinforcement Learning with the MAXQ Value Function Decomposition*。状态：`未核实`（无 arXiv）。
- **Deep Recurrent Q-Network** — Hausknecht & Stone (2015)，[arXiv:1507.06527](https://arxiv.org/abs/1507.06527)。状态：`未核实`（本轮未抓取；ID 为常见引用，使用前请复核）。
- **fractional calculus / 长记忆核** — 无单一 canonical 论文；如需引用，补 Oldham & Spanier (1974) 或 Podlubny (1999) 的出版社页。状态：`未核实`；当前只作为设计启发，不作为已证收益。
- **advantage-weighted regression / Bayes-adaptive MDP / predictive-state representations** — 计划中作为关键词使用，未指定具体论文；状态：`未核实`，实现前必须补确切文献。

## 9. 一句话结论

**先做 A：在独立 exam 和 Move 安全约束下验证“高 MMR 人类动作/场面题强度监督是否可学”，下一个 60–120M 阶段只改这一因素并以配对 human rank + t12/t15 无条件强度门禁决定是否进入 belief/options，信用重构最后做。** B 的幂率核必须先过 §B.1–B.2 的 α 极限/`N_eff`/与几何核 KL 单测；动作条件 `Q(s,a)` 只进 critic，若作 baseline 必须双采样修正（§B.3）；评测与采集按 §5.4 分账。

## 10. 可复现命令（与 s14 一致；本文件不授权执行）

> 以下命令逐字对齐 `runs/az_entity_s14/history.jsonl` 的 header（2026-10-31 11:15 启动）。训练/评测会占用 GPU，需 Lead 明确批准并登记资源；纯 CPU 自检不需要 GPU。`--eval-panel human` 与 s14 一致（不再跑 bot 评测）；`--eval-games 256` 是主面板，质量面板另跑。

```bash
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
cd /home/data/users/gaoletian/projects/HSBRSIM
export PYTHONPATH=rust/python:.

# s14 公共参数（与 header 一致；新增实验只允许在此之外加单因素开关）
S14_COMMON="
  --arch entity --device cuda:6 --processes 16 --gpus 3,4,5 --threads 8
  --games 192 --sims 0 --epochs 1 --minibatch 1024 --grad-accum 8 --amp bf16
  --lr 1.2e-6 --lr-min-ratio 0.5 --max-updates 3000 --clip 0.2 --target-kl 0.02
  --lam 0.995 --max-grad-norm 1.0 --entropy-coef 0.001 --pi-coef 0.0
  --anchor-beta 0.1 --anchor-iterations 200 --anchor-beta-tail 0.02
  --compile-train 1 --anchor-amp 1 --pipeline 1 --lockstep 1
  --leaf-wait-ms 0 --human-board-fast-inject 1 --archetype-cache 0
  --shaping-coef 0 --move-guard 1 --move-cap 3 --move-repeat-limit 2
  --archetype-bias-coef 0.5 --archetype-min-prob 0.6
  --mirror-snaps runs/library/snaps_champ --mirror-seats 2 --mirror-p 0.2
  --mirror-sample p75 --mirror-seat-random 1
  --human-boards data/real_library/library_real_quasi_full.jsonl
  --human-board-fidelity full --human-board-p 0.9 --human-board-seats 5
  --human-board-sample auto --human-board-set-tier 1
  --seq-coef 0.05 --bc-coef 0.004 --bc-type-weight 1.0 --bc-card-weight 0.5
  --bc-batch 128 --bc-every 4 --bc-compile 1
  --dpo-coef 0.02 --dpo-every 1 --dpo-beta 0.1 --dpo-batch 128
  --gpu-free-check 0 --seed 20100
  --eval-every-decisions 10000000 --eval-games 256 --eval-seats 8
  --eval-seed-base 420000 --eval-panel human --eval-human-quantile auto
  --eval-async 1 --eval-device cuda:7
  --snapshot-every 100 --keep-snapshots 4
"

# 1) 起训练（从 s13 110M 续训；out 换成新目录，避免覆盖 s14）
$PY scripts/train_entity_sync.py \
  --checkpoint runs/az_entity_s13/model.pt $S14_COMMON \
  --iterations 12000 --stop-at-decisions 120000000 --minutes 1800 \
  --out runs/az_entity_s14_repro

# 2) human 主面板 256 局（auto/seed 420000；默认库是 degraded，与 s14 评测一致）
$PY scripts/human_panel_eval.py \
  --checkpoint runs/az_entity_s14/model.pt --arch entity --device cuda:7 \
  --games 256 --seats 8 --seed-base 420000 --quantile auto \
  --human-boards data/real_library/library_real_degraded.jsonl \
  --set-tier 1 --baseline-bot 0 \
  --out runs/eval/human_s14_420000.json

# 3) 质量面板 64 局（tier p50 / tier≥5 / 强度比 / 出局强度；只做过程诊断）
$PY scripts/quality_monitor.py \
  --checkpoint runs/az_entity_s14/model.pt --arch entity --device cuda:7 \
  --games 64 --seed-base 740000 --move-guard 1 \
  --move-cap 3 --move-repeat-limit 2 \
  --out runs/eval/quality_s14_64.json

# 4) A/B 独立 exam（同 panel/seed/seat 配对；base vs 单因素候选）
$PY scripts/exam_paired_eval.py \
  --ckpt base=runs/az_entity_s14/model.pt \
  --ckpt cand=runs/az_entity_s14_ab/model.pt \
  --panel-seed-bases 730001,730513 --games 256 --seats 8 \
  --quantile auto --human-boards data/real_library/library_real_degraded.jsonl \
  --arch entity --device cuda:7 --nshards 1 \
  --out-dir runs/eval/exam_s14_ab

# 5) 纯 CPU 门禁（改算法后先跑；不占 GPU）
$PY -m pytest tests/test_credit.py -q
$PY scripts/verify_all.py --fast
```

**预算对照**：训练采集只按 §5.4 的 `collect_s`/`decisions_per_s` 记 <15%；human 256 局（约 194 s）与 quality 64 局（约 92 s）走评测预算，**不计入** collect 增幅。每次实验把 `manifest.json`、完整 args、数据 hash、git revision、checkpoint hash、逐局结果与 CI 一并入账（§7.3）。
