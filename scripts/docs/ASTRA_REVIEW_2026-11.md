# ASTRA_REVIEW_2026-11 · 数学/架构终审（comp_fit 决断 + 判定阈值）

> 终审对象：`hsbg/az/train/ppo.py`（PPO/GAE/rank critic/anchor KL）、`scripts/train_entity_sync.py`
> （奖励与 comp_fit，L738–813）、`scripts/eval_panel.sh`、`scripts/chain_300m.sh`（今晚配方真源）、
> `runs/az_entity_s61`、`runs/comp_scripts`（T1 既有实验）。**只读 + 短数值校验**：不训练、不占 GPU；
> "实测"值均给出处，无法复核的写进 §6。

## 0. 一屏结论（给 Lead 的决策）

| 问题 | 终审答案 |
|---|---|
| 今晚开不开 comp_fit | **不开。** 不是没证据，而是**已测过且无可测收益**（T1 四臂，§2.3），且当前实现**不是**势函数（§2.1）。 |
| 若坚持要开 | 只允许候选 B（真 PBRS：全程 `ΔΦ` + 终局 `−Φ`，`c≤0.05`、`t9_bonus=0`、`trinket=0`）；候选 A 已实测否决（§2.4 两套候选表）。 |
| 今晚怎么判改善 | 96 局口径：$|\Delta rank|<0.3$ **记噪声**、0.3–0.6 **不可判**、$>0.6$ **才叫信号**（§3.3）。改善声明留给下一次 512/2048 对新 exam（§3.4）。 |
| 今晚真正该盯 | `death_strength_p50`（强度）、`tier≥5@t15`、`survive12`、`anchor_kl`、`entropy`、`approx_kl`（§5）。 |
| 我推荐的单变量 | **零改动**（配方已在本轮历史最优点）。若要动，第一优先是 `anchor` 强度（成本 0、机制清楚），但**与"β 不衰减"的任务硬要求冲突，需你批准**（§4.1）。 |

**先纠一个事实**：主线 `adv_estimator=` **gae**（`runs/az_entity_s61/history.jsonl` header 逐字确认）。
`--power-alpha 0.25 --power-kappa 10` 只是被记进 config，**没有生效**。所以"当前用 power-law credit"
是误读；这也解释了 `adv_std` 与 GAE 口径一致（§1.3）。
## 1. 训练目标逐项复核（数学/量纲/梯度）

配方真源 = `scripts/chain_300m.sh:21-36`：`epochs 1 / minibatch 1024 / grad_accum 8`（有效 8192）、`lr 1.15e-6→0.5×`、
`clip 0.2 / target_kl 0.02 / lam 0.995 / gamma 1.0 / max_grad_norm 1.0 / entropy_coef 0.001 / pi_coef 0 / anchor β=0.1 恒不衰减 / rank-only / GAE`。
实测基线（s61 末 iter，285 iter ≈ 19.9M decisions）：`policy_loss 0.0015 / value_loss(rank CE) 1.55 / anchor_kl 0.009 /
entropy 0.753 / approx_kl 0.0033 / clip_frac 0.030 / adv_std 0.26 / value_pred_mean 0.253 / pre_ratio_mean 0.9971`。

### 1.1 奖励与 utility 量纲 ✅
`u(r)=1-2(r-1)/7`（`hsbg/az/train/common.py:50`），值域 $\{1,0.714,\dots,-1\}$，全距 2.0，单名次差 $2/7=0.286$；
`rank_utility_coef=1`、`terminal_strength_coef=0`（`ppo.py:1708`）→ 纯 rank 终局奖励，量纲自洽、有界。
每座位一个 episode（`done` 只在该 (game,seat) 末步为 1，`ppo.py:1697-1717`），GAE 分段正确。

### 1.2 GAE(γ=1, λ=0.995) 与 truncation ✅（"λ 很关键"是误解）
$A_t=\sum_{l}\lambda^{l}\delta_{t+l}$，$\delta_t=r_t+\gamma V_{t+1}-V_t$，末步不 bootstrap（`ppo.py:252-259`）。
- **truncation 正确**：`rank=0` 的整局在入口即丢弃（`ppo.py:1650`），不污染 done/GAE；实测每 iter `truncated_games=0`（384 局），eval 同为 0 → 无选择性偏差风险。
- **序列很短**：70812 decisions / 384 局 / 8 席 ≈ **23 decisions per seat-episode**，$\lambda^{23}=0.895$——λ=0.995 与 MC 只差 10%。
  **"后期信用分配不足"不是 GAE 衰减造成的**，这把 §4 从"改信用核"排除掉。
- **power/geom 近似等价 GAE**：`normalize=1` 时 $|A|$ 被压 $\sim1/N_{eff}$，而 loss 内又做 advantage 标准化（`ppo.py:2500-2506`），尺度被抹平，只剩 lag 相对权重差异（$l=22$：GAE $\lambda^{22}=0.896$ vs power $(1+2.2)^{-0.25}=0.748$，约 **16%**）。→ 开不开 power 不是高风险改动，但**没有证据**，今晚不值得动。

### 1.3 rank-only critic 与 advantage ✅（无偏，但有方差上限）
`value_loss="rank"` 用 `ranks-1` 做 8 类 CE（`ppo.py:2549`）；critic 的"价值"是 $V(s)=E_{p(r|s)}[u(r)]$（`ppo.py:2547`）。
CE 收敛时 $p(r|s)$ 一致、$E_p[u]\to E[u|s]$，故 $V$ 是合法 baseline（$a$-无关 → PG 无偏）。实测 CE $1.55<\ln8=2.079$；
若把 $A\approx u-V$ 粗算，$u$ 的 std 0.654、$adv\_std=0.26$，则 $V$ 解释了约 8 成方差（粗估，未扣 GAE 衰减）。**这一段健康**。
⚠️ 推论（决定 §2）：critic 回归目标**只有 rank 标签、不含 shaping**，故一旦加塑形，$A^F=(u+F)-V^{u}(s)$ 中 $F$ 是
**没有 baseline 的裸信号**，只能进方差、不能被 critic 吸收。

### 1.4 PPO clipped surrogate / 归一化 / clip ✅
`clipped_surrogate`（`ppo.py:264-283`）与 $-\min(rA,\mathrm{clip}(r)A)$ 一致；forced 样本用 `valid` 权重排除但保留 value 链
（`ppo.py:2499,2540`）；advantage 在 microbatch 内按 valid 子集标准化（`ppo.py:2500-2506`）。`ratio_mean 1.0001`、`clip_frac 0.030` → 健康。

### 1.5 anchor KL：**公式对、方向对，但它是真正的约束者** ⚠️
$\mathrm{KL}(\pi_\theta\|\pi_a)=\sum_a\pi_\theta(\log\pi_\theta-\log\pi_a)$（`ppo.py:2798-2806`）；masked softmax 下 $\sum_a\nabla\pi_\theta=0$，
故 autograd 多出的 $\sum\pi\nabla\log\pi$ 项恒零，**梯度解析正确**。问题在量级（实测）：
- `anchor_kl` p50 **0.0090**、max 0.0151；$\beta\cdot\mathrm{KL}$ p50 **0.00090** vs `policy_loss` p50 **0.00149**
  → **与策略项同量级（比值 0.58）**，约 1/3 的 actor 梯度预算被用来"别离开 s61"。
- 相对 KL 仅为 `target_kl=0.02` 的 45%；`approx_kl` p50=0.0033=target 的 17%；`1.5×target_kl=0.03` 的早停 **0/285 次触发**（`ppo.py:3087-3091`）
  → **实际信任域由 anchor 定，PPO 的 KL 护栏是摆设**。
- `entropy` 全程 0.743–0.763（p10–p90）**几乎不动**；`anchor_kl` 20M 内只从 0.006 到 0.009–0.015 → 策略处于**准冻结平衡**（"再训 20M 期望位移很小"的直接证据）。
- ⚠️ **bf16 精度地板**：`anchor_amp=1` 时 anchor 参考前向走 bf16、policy logp 是 fp32（`ppo.py:2524-2525`）；iter0（同权重）实测 `anchor_kl=0.00061`，
  即 KL 有 ~6e-4 假底。读 `anchor_kl` 时不要把 $<6\times10^{-4}$ 当漂移；β 调大时该项线性放大。

### 1.6 其它小项
- `entropy_coef=0.001`：熵稳定 0.753，贡献 $7.5\times10^{-4}$ 与 policy 项同量级，但方向是保留探索，无害。
- `pi_coef=0`：无 MCTS 蒸馏目标，纯 PPO + 自对弈，与 DECISIONS 一致；`max_grad_norm=1.0` + Adam $1.15\times10^{-6}$：clip 极少激活。
- `pipeline lag=1`：`pre_ratio_mean=0.9971` → 旧策略 logprob 的系统偏置仅 ~0.3%（相对 clip 0.2 可忽略）；`value` 也是上一版本（GAE 用陈旧 $V$，二阶小量）。
- ⚠️ **被忽视的相关性**：8 席自对弈下同一局的 8 条 episode **共享同一个终局**（rank 1..8 全出现），彼此强相关 →
  "有效样本量"≈ 局数（384/iter）而非 70k decisions；microbatch 内标准化会混入相关样本。不是 bug，但解读方差要以局为单位。

**§1 小结**：PPO/GAE/utility/anchor 的**数学没错**（无符号/量纲错、无 NaN 路径）。削弱训练信号的是配方层面的三个量级：
① anchor 与 policy 同量级且早停永不触发（策略准冻结）；② rank-only critic 使任何奖励塑形都变成无 baseline 噪声（§2 的关键论据）；
③ 有效样本量 ~384 局/iter、episode 仅 ~23 步，λ/credit 类是无效杠杆。

## 2. comp_fit 奖励：势函数性质与"能不能开"

### 2.1 实现事实（`train_entity_sync.py:738-813`）
$\Phi(s)=\max_{26}\big[0.30\min(1,n_{core})+0.25\min(1,n_{en}/2)+0.20\min(1,n_{races}/type_{min})+0.25\cdot\mathbb 1[tier\ge tier_{exp}(t)]\big]$，
理论界 $\Phi_{\max}=1.00$（L766-769），实测 $\Phi\in[0.2,0.875]$、p50 0.325。奖励写入：`delta[_i] += c·(Φ_i−Φ_{i−1})` **但只对 `turn<=9`**（L779-784）；
另有 `delta += b·Φ@t9`（L785-786）与 trinket 一次性 `+w`（L790-809）。

### 2.2 性质判定：**它不是势函数**
令 $\Phi_{T9}$ 为最后一个 `turn≤9` 决策的势，则整局 $\sum_{i\le T9}F_i=c(\Phi_{T9}-\Phi_0)=c\,\Phi_{T9}$（$\Phi_0\equiv0$），
因为 $t>9$ 既不累加、**也不补离场项** $-c\Phi_{T9}$ —— **望远镜在 t9 断裂**。γ=1 时整局回报变为
$$G=u(\text{rank})+c\,\Phi_{T9}+b\,\Phi_{T9}$$
即 **t9 处的终局 bonus**：它改的是目标函数，最优策略一般会变。真 PBRS 要求 $F_t=c(\gamma\Phi_{t+1}-\Phi_t)$ 覆盖**全部**转移且
$\Phi(\text{terminal})=0$，于是 $\sum_t\gamma^tF_t=-c\Phi(s_0)=$ 常数（`docs/REWARD_SHAPING.md:63,84-89` 已有同一推导）。
→ `--comp-fit-coef` 与 `--comp-fit-t9-bonus` **是同一件事的两个倍率**，都不是塑形；`trinket` 是动作条件奖励，更不是。

**关键量级**：实测 $\Phi_{T9}$ p50 = **0.40**，故 T1 那组 $(c,b)=(0.5,1.0)$ 的平均终局 bonus $\approx1.5\times0.40=0.60$ =
**名次效用全距的 30% ≈ 2.1 个名次**，远超可接受剂量（单决策 $|F|$ 应 ≤ 效用全距 1–2%，`REWARD_SHAPING.md:136-149`）。
**"稠密信号"也不成立**：实测每回合 $|\Delta\Phi|$ p50 = **0.025**（势值全距 1.25%）、p90 = 0.25 → **多数回合 Φ 完全不变**，
只在少数事件跳变（核心卡 +0.30 / 升本 +0.25 / 种族 +0.20）。所以它是"稀疏事件奖励 + 终局 bonus"；其中 `0.25·1[tier≥curve(t)]`
与 D-20261030-03 否决的 tier-target 信号同构，`0.30·min(1,n_core)` 是"拿到核心卡"的事件奖励（与 D-20261030-04 的 upgrade/DPO 通路重叠）。

### 2.3 已有实验证据：T1 四臂（`runs/az_entity_t1*`，全部从 s27d 起）
| 臂 | c / t9bonus / trinket | 预算 | seed | human 面板（128 局, 420000, auto） |
|---|---|---:|---:|---:|
| t1p（对照） | 0 / 0 / 0 | 3M | 27008 | **6.5938** |
| t1 | 0.5 / 1.0 / 0.25 | 2M | 27005 | **6.5547**（Δ −0.039） |
| t1iso | 8.0 / 10.0 / 2.0 | 1M | 27006 | 6.4688（Δ −0.125） |
| t1iso2 | 8.0 / 10.0 / 2.0 | 1.5M | 27007 | 6.4766（Δ −0.117） |
- 所有臂都在 $n=128$ 的 $MDE_{80}\approx0.5$ 内；高剂量"看着更好"与臂间 seed/预算不同混杂，**不能读成剂量-收益**。
- `trinket` 实测只有 **6/188 次命中，且"comp 关键饰品被提供"=0 次**：命中全靠"恰好选中该套 trinket"，不是"正确响应选项"，只贡献 6 个样本的噪声梯度。
- 结论与 D-20261030-03（tier-target：通路通、收益无）**同构**；与 D-20261030-01（塑形：γ 对齐后仍无收益、λ 量级不可接受）方向一致。

### 2.4 与 D-20261030-01 对齐 + 终审裁决
D-01 的教训两条：**(a) 奖励即使"合法"，量级超过效用全距几 % 就会替换掉真目标；(b) 追加 credit 的前提是 critic 能吸收它**。
§1.3 已证明 rank-only critic **吸收不了任何塑形**——所以连"数学上干净"的 PBRS 在这里也只会**降低 SNR**（$F$ 全裸进 advantage）。
只剩两套候选，**都不在今晚开**：

| 候选 | 参数 | 数学性质 | 今晚判决 |
|---|---|---|---|
| **A（原样，即 T1 已测的那套）** | `c=0.5, t9_bonus=1.0, trinket=0.25` | 非势函数；平均终局 bonus 0.60 = 效用全距 30% | **否决**：T1 实测 Δ −0.039（n=128），功率不足到连 0.5 都分辨不了；量级 6 倍超上限 |
| **B（唯一可接受的修正版）** | 全程 `ΔΦ` + 终局 `−Φ`，`c=0.05, t9_bonus=0, trinket=0` | 真 PBRS，整局和 = $-c\Phi(s_0)$ = 常数，**策略不变** | **可留待以后**，但预期收益 0（critic 吸收不了）；要开必须配 ≥1024 对 exam（$\S3.4$），今天没有这个预算 |

**裁决**：今晚三开关保持 0（`--comp-fit-coef 0 --comp-fit-t9-bonus 0 --comp-trinket-coef 0`）。理由三条，缺一不可：
① 现行实现不是塑形、量级过界（§2.2）；② 已有 T1 四臂在 128 局上无收益且**功率只有 ~20%**（$n=128$ 的 $MDE_{80}\approx0.5$，
而 20M 的期望位移约 0.2 → 任何"有效/无效"的结论都不可判）；③ 唯一形式上干净的候选 B 需要 ≥1024 对面板才能判，今晚没有该预算。
**若仍要开**：只允许 B，且必须预先登记"今晚不做收益判定"，只记录 `reward_shaping_abs_*` 类诊断与 `Φ@t9` 分布。
**替代动作（零风险）**：跑 `scripts/comp_metrics_probe.py --games 96`（229 s，纯推理）看 `fit_max9` 与 `t15`/`placement` 的相关；
若 $\Phi$ 与结果无关（当前 `t15_with_match` 不可测、trinket 命中 3%），任何基于它的奖励都**没有可学方向**，直接结案。

## 3. 评测统计：SE / MDE / 两个面板的关系 / 可操作阈值

### 3.1 96 局面板的统计口径（数值校验）
per-game rank 的 sd 用 s61 实测面板（`t1_p09_quality.json` 的 96 个 placement）估得 $s=1.434$：

| n | 单模型 $SE=s/\sqrt n$ | 单模型 $MDE_{80}=2.80\,SE$ | 两 ckpt 未配对 $MDE_{80}$ | 两 ckpt **配对** $MDE_{80}$（$\rho\approx0.6$） |
|---:|---:|---:|---:|---:|
| 96 | 0.146 | 0.41 | **0.58** | **0.36** |
| 192 | 0.104 | 0.29 | 0.41 | 0.26 |
| 384 | 0.073 | 0.21 | 0.29 | 0.18 |
| 768 | 0.052 | 0.14 | 0.21 | 0.13 |
| 2048 | 0.032 | 0.089 | 0.126 | 0.078 |

配对列前提 $\rho\approx0.6$：由 exam 实测 $\Delta$ 的 CI 反推 $\sigma_\Delta=1.26$，而边际 $\sigma=1.43$ →
$\rho=1-\sigma_\Delta^2/(2\sigma^2)\approx0.61$。**exam 的 $MDE_{80}=0.0898$（D-20261031-04）与上表 $n=2048$ 单模型列 0.089 吻合** → 模型无误；
亦即 exam 的 2048 配对面板等效噪声 ≈ 2048 个独立样本。**96 局两 ckpt：未配对可分辨 0.58，配对 0.36。**

### 3.2 开发面板与 exam/主口径的关系（三个口径不能混用）
| 口径 | 库 | 席/概率 | 分位 | 保真度 | 用途 |
|---|---|---|---|---|---|
| 训练内 dev（`chain_300m.sh:34-35`） | 默认 `library_real_degraded.jsonl`（`train_entity_sync.py:3230`） | `eval_seats=8` | auto | board-only | 仅护栏/趋势 |
| `eval_panel.sh`（主口径） | `library_real_quasi_full.jsonl` | 5 席 p0.9 | **p75** | **full** | 历史可比曲线 |
| exam（`730001/513/025/537`） | 同上 | 同上 | 同上 | 同上 | 唯一能判 0.1 名次 |
| 训练库（s61 实际） | **`winner_library.jsonl`**（200 KB） | 3 席 p0.9 | auto | board | 训练分布 |

同一 ckpt 实测差：**dev 6.4375**（10.017M 唯一一次 dev eval）vs **冻结面板 6.292**（s61_10m）——**差 0.145 = 1 个 SE**。
故"dev 面板好转/恶化"只能当报警器，不能当结论；且 s61 整个 20M 只产出 **1 次** dev eval（`summary.json` 的 `evals` 长度=1），
本轮"dev 趋势"**根本不存在**。D-20261031-04 结论仍成立：冻结面板 5 点 6.396/6.458/6.406/6.292/6.083 极差 0.375≈2.6 SE，
其中 s61 的 10M→20M 位移 **0.209 = 1.4σ** —— "历史最优 s61@30M 比 20M 好 0.21"这个选点**本身就是噪声级**。

### 3.3 今晚的判定协议（Lead 口径：0.3 / 0.6 三档）
**主指标 = `mean_rank`（96 局, seed 520000, 5 席 p0.9, full, p75）**，$\Delta=\text{rank}(s73)-\text{rank}(s61@30M)$（负=更好）：

| $\lvert\Delta\rvert$（96 局） | 结论写法 |
|---|---|
| $<0.3$ | **噪声**。只能写"未见退化"，不得写改善/恶化（对应 $SE=0.146$，约 0.7–2σ） |
| $0.3\sim0.6$ | **不可判**。只能写"方向性提示，需更大样本"（≈2–4σ，且未配对 $MDE_{80}=0.58$ 覆盖此区间） |
| $>0.6$ | **信号**。可写"改善/恶化（单面板）"，但仍必须交 §3.4 exam 复核后才能作为决策依据 |

口径对应（`eval_panel.sh` 输出字段 ↔ 主指标含义）：
- `mean_rank` = learner 平均名次（1 最好）→ 主指标；
- `strength` = **`death_strength_p50`**（出局瞬间盘面 Σ 的 p50）——注意它**不是** t15 强度；
  真正的 t15 强度在 `quality_monitor` 输出的 `by_turn[15].ours_p50` 里（冻结面板曲线口径的同一字段）；
- `tier4+` = `tier_ge4_ratio`；**`tier≥5@t15` 不打印**，须读 JSON 的 `by_turn[15].tier_ge5_ratio`（建议在 `eval_panel.sh:19-27` 的打印里补一行）；
- `survive12` = `survive_t12_ratio`；`top4` = 前四率。

**辅助判定（信息量更大，但只作描述）**：`death_strength_p50`（本轮历史块间 259↔323.5，±25%）、`by_turn[15].tier_ge5_ratio`、
`survive_t12_ratio`、`death_turn_p50`。判"后期强度改善"要求 **≥+20% 且 96 局与 4×512 同向**；只 +10% 一律当噪声。
**配对加成**：把起点 s61@30M 在同一 96 seed 上补跑一次（≈3 min，实测 96 局 171 s），
可将 96 局的可分辨效应从 0.58 压到 0.36（$\rho\approx0.61$）——但**这不改变上表三档的结论**，只让 0.3–0.4 区间从"不可判"变成"弱信号"。

### 3.4 下一次更大样本 exam：s61 vs s73 的可执行协议
**目的**：把"20M 续训的期望位移 0.2 名次"变成可检出（而不是今晚的不可判）。用**新 seed 区块**（`74xxxx`，与 730xxx/420000/520000 均不重叠），
同 seed 全模型配对（对手注入按 `(seed,game,turn,seat)` 派生 → 对手部分是 CRN）。**必须沿用 `eval_panel.sh` 口径**（不能用 `exam_paired_eval.py` 的旧默认：
它默认 `--seats 8 --quantile auto` 且不传 fidelity，与 s61 的 6.083 不同尺）。

```bash
# 每面板 512 局；面板 seed = 740000/740512/741024/741536（4 块 = 2048 对）；两臂同 seed
for arm in s61_30m s73_final; do for k in 0 1 2 3; do
  EVAL_SEED=$((740000 + k*512)) bash scripts/eval_panel.sh <ckpt_of_$arm> ${arm}_p${k} 512
done; done   # 配对分析：读 runs/eval_panel/*_p*.json，按 game seed 做 seed 级配对 bootstrap（簇=panel）
```
成本（实测 **1.79 s/局**，96 局 = 171 s）：512 局 ≈ **15 min/模型**；4×512=2048 局 ≈ **61 min/模型**；
两模型串行 2048 对 ≈ **2 h**（2 张卡并行 ≈1 h）。判据（$\Delta=\text{rank}(s73)-\text{rank}(s61)$）：

| 规模 | SE | $MDE_{80}$ | 对 0.2 的检出力 | 用途 |
|---:|---:|---:|---:|---|
| 512 对 | 0.056 | 0.156 | **95%** | 最小可执行；能判"是否改善 ≥0.2" |
| 1024 对 | 0.039 | 0.110 | ≈100% | 推荐；可同时测非劣界 +0.10 |
| 2048 对 | 0.028 | 0.078 | ≈100% | 与 D-20261031-04 同量级，可支持"≥0.1 改善"表述 |

- **改善**：95% CI 上界 $<0$（即 $\Delta<0$ 显著）；
- **不退化（非劣）**：95% CI 上界 $<+0.10$（需 ≥1024 对）；
- **强度门**：`death_strength_p50` 与 `by_turn[15].ours_p50` 均不下降，且至少一项 ≥+20%；
- 预注册：先定面板与判据再跑，禁止跑完再挑面板；多终点（rank 主 + 3 个辅助）按主终点单侧 0.05 判，辅助只作描述。

## 4. 「后期盘面强度不足」的 3 条低风险改动（按成本/风险排序）

**下一实验候选（本轮不改，Lead 已同意先不动）**：§1.5 的「anchor-KL 支配 + entropy 冻结」是本轮之后**最值得 A/B 的假设**——
它同时解释了"policy_loss 近乎 0""KL 只有 target 的 17%""早停 0 次""20M 位移仅 0.2"。**最小预算**：
2 臂（β 恒 0.1 vs 5M 后 0.03）从 s61@30M 各训 10M decisions（≈3.5 h/臂，可 2 组卡并行）+ 1024 对（≈1 h）；
**判据**：先把"信任域是否被打开"当机制门（`kl_early_stopped` 频率 >0、`entropy` 明显下降、`approx_kl` 上升到 0.01 附近），
再看 rank CI 上界 <0 与强度门；**止损**：entropy<0.65 或 `value_loss`>1.75 连续 10 iter 即停。与 `docs/SMALL_FULLGAME_RL.md:89`「β 不衰减」冲突，需任务侧批准。

诊断基线（`runs/comp_scripts/s42_t9.json`）：t9 时 tier p50 **3** vs 真实 **5**；`core_rate` 0.50 vs 0.94；`races_p50` 4 vs 2；
death_turn p50 10–11；t15 Σ p50 ~200 vs 真实 546。即：**模型活不到后期、也没在攒，而不是"后期不会打"**。三条改动都指向"进得去 + 学到后期状态"，不再加奖励。

### 4.1（成本 0，风险中）放开 anchor：`--anchor-iterations 1500 --anchor-beta-tail 0.03`
即上文"下一实验候选"的具体命令：β 恒 0.1 → 5M 后 0.03。**预算/判据/止损见上段**；与 `SMALL_FULLGAME_RL.md:89`「β 不衰减」冲突，列为"需批准"，不作默认。

### 4.2（成本 ~50 行，风险中低）在自对弈轨迹上加 **t+5 后期状态辅助头**
在 `_apply_custom_rewards` 已有 batch 上（L746-760 已有 `_turns/_board/_tier`），对每个决策取"同 episode 内 t+5 状态"作自监督标签：
预测 `1[tier≥5]`（BCE）与 `log1p Σ`（z-score MSE），权重各 0.01–0.02，加在 **trunk**。
为什么低风险：**不改奖励、不改 critic 目标、不改策略目标**，只给共享表征稠密监督；策略不变性完整保留（与 §2 路线正交），且标签来自 on-policy 分布
（不像 `problem_pool` 是离线状态）。**验证预算**：2 臂 × 5M（约 2.5 h）+ 96×4 面板（$MDE=0.29$）+ exam 复核；`strength_head` 在 `ppo.py:1152-1160` 已有同构实现，可复用 80% 代码。

### 4.3（成本 0，风险中）后期压力课程：`--human-board-quantile-ramp 0:p75,12M:p90`
ramp 机制已实现且默认关（`ppo.py:477-509`、`BoardRampController`）。当前训练库是 winner 库 3 席 p0.9 auto；把 t≥12 分位推到 p90 才能让模型**活着时**见到真实后期强度。
**验证预算**：2 臂 × 10M + exam；**风险**：改对手分布 → 归因困难（D-20261031-01 已声明剂量未被单变量检验），故排最后。

**不推荐**（已证伪或不解决该问题）：奖励塑形（D-01）、tier-target（D-03）、BC warm-start（D-05）、换库（D-03）、move-head-split（D-02）、
把 credit 核换 power（§1.2，23 步下等价）、沙盒教师/comp 脚本当教师（`docs/COMP_SCRIPTS.md` §0：最强阵容终局 Σ 292 ≈ bot）。

## 5. 今晚训练的护栏清单（必须监控 + 停机条件）
每 iteration 看 `history.jsonl` 的 `ppo` 段（括号内为 s61 基线）：
| 量 | 基线 / 正常带 | 触发动作 |
|---|---|---|
| `illegal_actions` / `truncated_games` / `invalid_games` | 0 / 0 / 0 | **任一非 0：立即停** |
| `pipeline.pre_ratio_mean` / `guard_tripped` | 0.997 / false | <0.99 或 true：**停**（旧策略/批次错配） |
| `approx_kl` p50 | 0.0033（p90 0.0073） | >0.010 连续 3 iter 或触发 1.5×target_kl：**停** |
| `kl_early_stopped` 频率 | 0/285 | >5%：**停**（信任域被打破） |
| `anchor_kl` | 0.009（地板 6.1e-4） | >0.05：anchor 失效；<6e-4：读作"没动" |
| `entropy` | 0.743–0.763 | <0.65（塌缩）或 >0.85（变随机）连续 10 iter：**停** |
| `value_loss`(rank CE) | 1.49–1.56 | >1.75 连续 10 iter 或 <1.2（头崩/泄漏）：**停** |
| `clip_frac` / `adv_std` | 0.030 / 0.26–0.28 | clip>0.15：**停**；adv_std>0.6 或 <0.10：查 reward/GAE 接线 |
| `human_board_rejected/attempt` | 0.39（多为 `pending_choice`） | >0.60：注入失效，分布漂移 |
| `forced_end_turns` / 局 | 111/384 ≈ 0.29 | >2/局：采样在打转（假存活） |

**评测护栏（每 10M）**：同口径 96 局 + **起点 ckpt 配对重跑**（同 seed，≈8 min）。
硬门：配对 $\Delta rank>+0.30$ **且** `death_strength_p50`（或 `by_turn[15].ours_p50`）下降 >15% → **停**，回滚 s61@30M；软门：配对 $\Delta rank>+0.60$ → 判恶化、停。
不许用 dev 面板绝对值与 `eval_panel.sh` 数字互比（§3.2）。

**明确禁止今晚动**：任何奖励项（shaping/comp_fit/tier-target/trinket/win-only/strength-reward）、对手库与剂量、`move-guard` 参数、`adv-estimator`、`pi_coef`、eval 口径/seed/席数。唯一例外是 §4.1（需批准）。

## 6. 复核边界（没做/做不到的，如实标注）
1. **没做真实 minibatch 的梯度范数比**：§1.5 的"β·KL 占 1/3 梯度预算"由 loss 量级 + KL/早停事实推断，严格证明需一次 backward 抓 $\lVert\nabla L_{policy}\rVert$ 与 $\lVert\beta\nabla KL\rVert$，涉及 GPU（不归我）；建议持 GPU 成员用 `dpo_grad_probe.py` 同款手法补一次。
2. **没跑 comp_fit 修正版 A/B**（不可开训练），只复核代码路径与既有 T1 结果。
3. **trinket 的 6/188 命中**来自 `baseline_p09` 探针（96 局、s27d 时代），不是 s61；但 `offered=0` 是结构性的，换 ckpt 不会变。
4. 数值脚本已删（`.tmp_trace/astra_*.py`，只读、<60 s）；未写 `runs/`、未改任何训练语义。
