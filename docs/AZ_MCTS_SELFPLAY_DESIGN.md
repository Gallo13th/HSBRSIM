# 逐步 MCTS + 自对弈训练设计（HSBRSIM / AZ-MCTS）

> 状态：**设计文档（v0.2）**，2026-10-26。本文先固化“完整流程 + 数学形式化 + 公式推导”，
> 开发计划在本文评审后另行讨论。
>
> **v0.2 增补（2026-10-26）**：用户确认 §0 的 D6–D11（8 座全搜索 / 历史对手回放 /
> 统一估计器接口 / 训练价值仅终局名次 / 动作严格对齐 AT 245 / 效率优先且可远程构建依赖）；
> 新增 §3.10“早期搜索的 rank-level 成对胜负矩阵评估”及附录 A.9。
>
> 范围：以 AutoTavern fork（`rust/` 内 `hsbg_engine`，数据 37.0.0.255130）为唯一主引擎，
> 用**逐步（move-level）MCTS** 生成训练数据，从零训练 245 动作策略 + 名次价值网络；
> `hsrl2` 仅作遗留 oracle/参考，不参与训练。
>
> 相关文档：[RUST_ENGINE.md](RUST_ENGINE.md)、[ACTION_SPACE_STD.md](ACTION_SPACE_STD.md)、
> [OBS_STD.md](OBS_STD.md)、[ALGORITHM_RESEARCH.md](ALGORITHM_RESEARCH.md)、
> [AUTOTAVERN_P3_KICKOFF.md](AUTOTAVERN_P3_KICKOFF.md)、[P3_VERIFICATION.md](P3_VERIFICATION.md)。

---

## 0. 决策记录（用户已确认）

| 编号 | 决策 | 说明 |
|---|---|---|
| **D1** | 采用**逐步 MCTS**（move-level），不做“回合级 macro MCTS”作为主方案 | 每个 245 动作决策都建树；macro 只作为可选加速/研究项 |
| **D2** | 搜索实现为 **Rust 搜索核** | 树、PUCT、chance、determinization、批量评估调度在 Rust；Python 只做 NN 推理/数据/训练 |
| **D3** | **隐藏信息不可见**；后续由用户设计“从部分可见信息预估对手某一回合状态”的模块 | 当前策略/价值/搜索输入只允许观测 `o`；不引入 oracle 特权特征 |
| **D4** | 自对弈**两阶段交替**：先 8 座全为我方模型对战；在“足够高质量数据”后，变为 **1 座我方模型 + 7 座历史数据中对应回合的历史对手**；如此反复 | 历史对手来自我们自己生成的高质量历史轨迹/快照，而非 AT（AT 未发布完整对局数据） |
| **D5** | 在远程开发机 **`biocourse-glt`** 上部署 HSBRSIM，用于快速性能测试 | 本 Mac 仅用于代码编写；训练/基准在远程机执行 |
| **D6** | **Phase A 全 8 座都跑搜索**（不是 1–2 座搜索） | 数据质量优先；效率通过 Rust 核/批量评估/预算控制（§6.2、§7） |
| **D7** | 历史对手默认 **回放动作序列**（replay） | 非法/状态偏移时 fallback：BC/脚本 bot；不把历史对手改成 BC 为主 |
| **D8** | 隐藏信息/对手状态估计使用**统一接口** | `BeliefSampler`（Rust trait）+ 估计器 `q_φ(h\|o)`；训练/推理共用（§3.7、§7.6） |
| **D9** | 训练价值目标**只用终局名次** | $z$ 为终局 rank（one-hot / 期望效用）；不使用 TD/中间奖励作为训练目标 |
| **D10** | 动作空间**严格对齐 AT：245** | 不引入 245+ 扩展（Unfreeze/额外技能槽等）；与 AT/TavernBench 逐位可比 |
| **D11** | **效率优先**：先测搜索/训练效率，再定数据规模；依赖可远程构建 | M0 基准先行（copy/step/obs、search sims/s、成对战斗吞吐）；远程机可 rustup/conda 构建 |

**非目标（本设计不覆盖）：** 异变系统、任务系统、饰品全量补完（P2/P3 内容项）；
AT 未公开训练代码的复刻；MuZero 式世界模型；在线搜索替代全部训练。

---

## 1. 接口基线（现有能力与硬约束）

### 1.1 引擎与训练接口

| 接口 | 定义（已实现） | 本设计中的用途 |
|---|---|---|
| `Game(seed, config)` | 8 人完整对局；`needs_action(p)`、`legal_mask(p)`、`observe(p)`、`step(p,a)`、`bot_action(p)`/`bot_play(p)`、`placements()`、`is_over()` | 逐步 MCTS 的前向模型（Rust 内部） |
| `Game.copy()` | Rust 深度拷贝（含 RNG） | 搜索树分支/回放；**成本是搜索预算第一决定因素** |
| `Game.state_json()` / `from_json()` | 精确存档/恢复（含卡表指纹校验） | 调试、断点、历史快照；不作为热路径 |
| `Game.debug(cmd_json)` | `set_player`、combat preview 等调试命令 | determinization 注入、对手状态估计器接口的临时实现 |
| `BatchEnv(n_games, controlled, threads)` | 批量观测/步进；`controlled=range(8)` 可全 self-play；`save/load` | 纯策略 rollout、评测、数据生成（非搜索部分） |
| `SoloEnv` | 单学习座 vs 7 脚本 bot | 快速回归/基线 |
| `observe(p)` | `features: f32[3227]` + `cards: i32[124]`（AT std 布局，逐位一致） | 策略/价值网络输入，**不需要再转换** |
| `legal_mask(p)` | `bool[245]` | 动作掩码；训练用 245 原生动作空间 |
| `action_name(i)`、`layout()` | 245 动作名/3227+124 布局 | 数据可读性、对齐 AT 基准 |

> **动作空间边界（D10）**：`hsbg_engine` 原生 `N_ACTIONS=245`（AT 定义：EndTurn/Refresh/Freeze/
> Upgrade/HeroPower/DarkGift/Cancel/Buy/Sell/Activate/Choose/Play/Magnetize/Move）。
> 本设计**训练/搜索只用 245**，245+ 扩展（Unfreeze/HeroPower 额外槽/FreezeSlot 等）
> 不纳入（与 AT/TavernBench 严格可比）；若未来需要，另行立项并同步动作语义/数据版本。

### 1.2 硬约束

1. **固定形状**：观测 3227 floats + 124 cards；动作 **245（严格对齐 AT，D10）**。网络/数据/搜索都按固定形状设计。
2. **EndTurn 是宏动作**：`step(p, 0)` 触发该玩家回合结束 → 其余 7 座行动（由对手策略决定）
   → 配对/战斗（RNG）/商店刷新（RNG）/淘汰 → 下一回合。它是**随机转移**，不是普通边。
3. **`Choose` 是独立动作**：245 中 `Choose(0..15)` 表示待选选项；搜索时作为节点边处理。
4. **无隐藏信息注入的正式 API**：`debug` 可临时 `set_player`，但 determinization 需要新增
   正式的“按观测重建/采样隐藏世界”的 Rust 接口（见 §7.6）。
5. **可复现性**：`Game` 含 RNG 状态，`copy()` 复制 RNG；同 seed + 同动作序列结果确定。
6. **评测/部署不使用特权信息**：策略/价值/搜索的**决策输入**只能是该座位观测（§2.7）。



### 1.3 符号表

| 符号 | 含义 |
|---|---|
| $s\in\mathcal{S}$ | 8 人完整状态（含隐藏信息） |
| $o=Z(s)\in\mathcal{O}$ | 座位观测（3227 floats + 124 cards），**唯一允许的决策输入** |
| $h$ | 观测历史（信息集）；$h_t=(o_0,a_0,\dots,o_t)$ |
| $a\in\mathcal{A}$ | 动作，$\mathcal{A}=\{0,\dots,244\}$；$m(a\mid s)$ 合法掩码 |
| $T(s'\mid s,a)$ | 转移；`EndTurn` 含对手策略与 chance |
| $\mu$ | 对手联合策略（自对弈/历史/bot） |
| $r\in\{1,\dots,8\}$ | 终局名次；$u(r)=1-2(r-1)/7$ 名次效用 |
| $\pi_\theta(a\mid o)$ | 策略网络；$\pi_{\text{target}}$ 为 MCTS visit 目标 |
| $q_\theta(r\mid o)$ | 名次分布头；$V_\theta=\sum_r q_\theta(r)u(r)$ |
| $b(s)$ / $q_\phi(h\mid o)$ | 信念 / 对手状态估计器（后续） |
| $N(n,a),W(n,a),Q(n,a),P(n,a)$ | MCTS 边统计：访问/累计价值/均值/先验 |
| $S$ | 每次决策的模拟次数 |
| $K$ | `EndTurn` chance 采样数（世界线） |
| $W_{\text{det}}$ | determinization 世界数（与边统计 $W(n,a)$ 区分） |
| $\tau$ | 策略温度；$\varepsilon,\alpha$ Dirichlet 噪声参数 |
| $c_{\text{puct}},c_{\text{vl}}$ | PUCT/虚拟损失系数 |

---

## 2. 问题形式化

### 2.1 8 人酒馆战棋 = 部分可观测随机博弈（POMDP/MPOMDP）

将单座位视角建模为 **POMDP**：

$$
\mathcal{M}=\bigl(\mathcal{S},\ \mathcal{A},\ \mathcal{O},\ T,\ Z,\ R,\ \gamma\bigr),
\qquad \gamma=1\ (\text{episodic}),
$$

- **状态** $s\in\mathcal{S}$：8 座完整状态（英雄、血量、金币、等级、手牌、战团、酒馆、
  饰品、任务、卡池、RNG 状态、回合/阶段、配对/幽灵等）；
- **动作** $a\in\mathcal{A}=\{0,\dots,244\}$（§2.3）；合法掩码 $m(a\mid s)$；
- **观测** $o=Z(s)\in\mathcal{O}$：该座位可见的 3227+124 特征（含上局对手战团公开信息），
  完整状态中的隐藏部分记为 $h=s\setminus o$；
- **转移** $T(s'\mid s,a)$：普通招募动作大多确定；`EndTurn` 包含对手策略、战斗与商店 RNG；
- **奖励**：仅终局有名次奖励（§2.5）。

> 8 人之间是常和（constant-sum）名次效用，不是 2 人零和；因此**不使用 negamax**，
> 单座位视角把其余 7 座视为“带策略的随机环境”（与 `docs/ALGORITHM_RESEARCH.md` 一致）。

### 2.2 观测、信息集与信念

观测函数 $Z:\mathcal{S}\to\mathcal{O}$。一个观测历史
$h_t=(o_0,a_0,o_1,a_1,\dots,o_t)$ 对应一个**信息集**
$$
I(h_t)=\{s\in\mathcal{S}: Z(s_j)=o_j\ \text{沿同一动作历史}\}.
$$
信念 $b_t(s)$ 为在信息集上的后验。贝叶斯更新：
$$
b_{t+1}(s')\ \propto\ Z(o_{t+1}\mid s')\sum_{s\in\mathcal{S}}T(s'\mid s,a_t)\,b_t(s).
$$
策略 $\pi(a\mid h)$、价值 $V^\pi(h)=\mathbb{E}_{s\sim b(h)}\bigl[V^\pi(s)\bigr]$，
其中 $V^\pi(s)=\mathbb{E}_\pi[u(r)\mid s]$。

**本设计的搜索对象是信息集/观测历史，而不是隐藏状态**：MCTS 节点对应 $h$；
$Q(h,a)$ 是对 $s\sim b(h)$ 的期望；价值网络输入只有 $o$。

### 2.3 动作

$$
\mathcal{A}=\{0,\dots,244\},\qquad
\text{EndTurn}=0,\ \text{Refresh}=1,\ \text{Freeze}=2,\ \text{Upgrade}=3,
$$
$$
\text{HeroPower}\in[4,5],\ \text{DarkGift}=6,\ \text{Cancel}=7,\ 
\text{Buy}\in[8,15],\ \text{Sell}\in[16,22],
$$
$$
\text{Activate}\in[23,29],\ \text{Choose}\in[30,45],\ \text{Play}\in[46,125],
\ \text{Magnetize}\in[126,195],\ \text{Move}\in[196,244].
$$

合法动作集合 $\mathcal{A}_{\text{legal}}(s)=\{a: m(a\mid s)=1\}$；策略只在合法动作上归一化。
动作语义与 AT 逐位一致（金标测试 `tests/test_action_space_std.py`）。

### 2.4 转移、chance 与对手混合策略

把转移拆成两层：

$$
T(s'\mid s,a)=\sum_{a_{\text{opp}}\in\mathcal{A}^7}\mu(a_{\text{opp}}\mid s)\,
P_{\text{chance}}\bigl(s'\mid s,a,a_{\text{opp}}\bigr),
$$

- $\mu$：7 个对手的联合策略（自对弈时为我方模型；Phase B 为历史对手；评估时为 bot/联赛）；
- $P_{\text{chance}}$：战斗攻击顺序/随机目标、商店/发现/刷新、任务/饰品随机等。

**普通动作**（买/卖/打/移/技能/选择等）：确定性转移 $s'=f(s,a)$（除随机效果外）。
**`EndTurn`**：宏动作，$\mu$ 与 $P_{\text{chance}}$ 都参与；搜索中按 chance 节点处理（§3.4）。

### 2.5 终局与奖励

终局名次 $r\in\{1,\dots,8\}$（1=冠军）。名次效用：
$$
u(r)=1-2\,\frac{r-1}{N-1},\qquad N=8,
$$
即 $u(1)=+1,\ u(8)=-1$，线性、常和：$\sum_{p=1}^{8}u(r_p)=0$。

对座位 $p$，第 $t$ 步的回报 $G_t=u(r)$（$\gamma=1$，仅终局给 reward）。
**训练/评测主指标**：平均名次 $\bar r$（越小越好）、前四率、冠军率、期望效用
$\mathbb{E}[u]$；搜索价值函数用 $u$ 的期望，网络同时输出名次分布（§4）。

### 2.6 目标函数

$$
J(\pi)=\mathbb{E}_{s_0\sim p_0,\ a_t\sim\pi(\cdot\mid h_t),\ s_{t+1}\sim T}\bigl[u(r)\bigr],
\qquad
\pi^\star=\arg\max_{\pi}J(\pi).
$$

在信息集上，$J$ 等价于 belief-MDP 的目标；由于对手策略也在变（自对弈/历史对手），
严格说是**非平稳多智能体目标**；本设计用“每轮固定对手池 + 周期性更新”的近似（§6）。

### 2.7 隐藏信息约束（D3）

**当前阶段（本设计）**：策略、价值、搜索的**决策输入只允许** $o$（及公开历史）。
- 搜索树节点保存观测历史 $h$ 与一个**采样世界**（determinization）$s\sim q(\cdot\mid h)$，
  用于推进转移；**网络前向只看到 $o$**，不把 $s$ 的隐藏字段喂给网络。
- 世界采样 $q$ 与真实隐藏状态 $h$ 独立（不使用 oracle）；$q$ 初始可为“按公开信息的经验先验”，
  后续由用户设计的**对手状态估计器**替换（§6.7）。
- 评估时必须报告 **oracle gap**：用特权搜索（能看到 $s$）与观测搜索的强度差，作为
  表征/估计器改进的目标（只用于诊断，不作为训练输入）。

**后续阶段（用户将设计）**：从部分可见信息预测对手某一回合状态，得到
$q_\phi(h\mid o)$；它作为 determinization 的 proposal/后验，并训练辅助损失（§6.7）。

### 2.8 自对弈两阶段的分布定义

- **Phase A（全 8 座自对弈）**：联合策略
  $$
  \Pi_A(s)=\prod_{p=1}^{8}\pi_\theta(a_p\mid o_p(s)),
  $$
  所有座位由同一网络（可带搜索）控制；数据分布 $\mathcal{D}_A=\mathcal{D}(\Pi_A)$。
- **Phase B（1 座学习 + 7 座历史对手）**：学习座位策略 $\pi_\theta$，对手联合策略
  $$
  \mu_{\text{hist}}(a_{\text{opp}}\mid s)=\prod_{j\in\text{opp}}\pi_j^{\text{hist}}(a_j\mid o_j(s)),
  \qquad \pi_j^{\text{hist}}\sim\mathcal{P}_{\text{hist}},
  $$
  $\mathcal{P}_{\text{hist}}$ 为历史对手库上的分布（§6.3）；数据分布 $\mathcal{D}_B$。

两阶段交替（§6.4）。

---

## 3. 逐步 MCTS 的形式化

### 3.1 搜索树

对一次决策（固定座位 $p$、根观测历史 $h_0$），MCTS 树：

- 节点 $n$ 对应信息集历史 $h_n$（观测+动作序列）；
- 边 $(n,a)$：$a\in\mathcal{A}_{\text{legal}}(h_n)$，子节点 $n'=n\cdot a$；
- 每条边统计：访问次数 $N(n,a)$、累计价值 $W(n,a)$、先验 $P(n,a)$；
  $$
  Q(n,a)=\frac{W(n,a)}{N(n,a)}\quad(N>0),\qquad P(n,a)=\pi_\theta(a\mid o(h_n)).
  $$
- 根节点先验加 Dirichlet 噪声（§3.5）；
- 终端节点：对局结束（$u(r)$ 已知）或达到单次搜索深度上限（用价值网/rollout 评估）。

> 搜索深度：普通动作是“步”；`EndTurn` 是宏动作，一步跨一个完整回合（含对手行动/战斗）。
> 树的每条根到叶路径 = 若干招募动作 + 若干 `EndTurn` 宏动作。深度上限按“回合数”截断。

### 3.2 选择：PUCT

在节点 $n$ 选择
$$
a^\star=\arg\max_{a\in\mathcal{A}_{\text{legal}}(h_n)}
\left[
Q(n,a)+c_{\text{puct}}\,P(n,a)\,
\frac{\sqrt{\sum_{b}N(n,b)}}{1+N(n,a)}
\right],
$$
其中 $c_{\text{puct}}>0$（建议初值 1.5–2.5，按 8 人/245 动作调）。

**推导（从 UCB1 到 PUCT）**：多臂老虎机的 UCB1 为
$$
\text{UCB}(a)=\hat\mu_a+\sqrt{\frac{2\ln N}{N_a}}.
$$
在树搜索中，$N=\sum_b N_b$，用先验 $P(a)$ 代替均匀探索，得到 PUCT（Rosin 1970s /
AlphaZero 形式）：
$$
\text{PUCT}(a)=Q(a)+c_{\text{puct}}P(a)\frac{\sqrt{N}}{1+N_a},
$$
其含义：先验高的动作在访问少时获得更大探索加成；$N_a\to\infty$ 时探索项 $\to 0$，
趋于利用 $Q$。$c_{\text{puct}}$ 控制“先验/价值”的相对信任。

**虚拟损失（并行搜索）**：为避免多个线程/批量评估重复走同一路径，对正在评估的边加
虚拟损失。设边 $a$ 有 $v_a$ 个 in-flight 评估，定义
$$
\tilde Q(a)=\frac{W(a)-c_{\text{vl}}\,v_a}{N(a)+v_a},
\qquad
\text{select}(a)=\tilde Q(a)+c_{\text{puct}}P(a)\frac{\sqrt{\sum_b N_b}}{1+N(a)+v_a}.
$$
评估完成后用真实价值回填、撤销虚拟损失；$c_{\text{vl}}$ 建议 0.5–1.0。

### 3.3 扩展与叶评估

叶节点（首次访问/未扩展）：
1. 取观测 $o=Z(s)$（只含可见信息），合法掩码 $m$；
2. 网络输出 $(p,v)=f_\theta(o)$，$p$ 为 245 维 masked softmax 先验，$v$ 为**期望名次效用**
   $$
   V_\theta(o)=\sum_{r=1}^{8}q_\theta(r\mid o)\,u(r)
   $$
   （$q_\theta$ 为名次分布头，§4）；
3. 生成子边并初始化 $N=W=0$、$P=p$；
4. 用 $v$ 备份（§3.4）。

可选 **rollout 价值**（冷启动/消融）：
$$
v_{\text{rollout}}=\mathbb{E}_{\text{rollout}}\bigl[u(r)\bigr],
$$
rollout 策略可用引擎 bot（`bot_action`）或随机策略。α 混合：
$v=(1-\alpha)v_{\text{net}}+\alpha v_{\text{rollout}}$；训练稳定后 $\alpha\to0$。

### 3.4 备份

设一次模拟从根到叶 $n_L$，叶价值为 $v$（或终局 $z=u(r)$）。对路径上每条边
$(n,a)$：
$$
N(n,a)\leftarrow N(n,a)+1,\qquad
W(n,a)\leftarrow W(n,a)+v,\qquad
Q(n,a)\leftarrow \frac{W(n,a)}{N(n,a)}.
$$
**注意**：8 人常和但非两方零和，**不做符号翻转**；所有座位共享同一个 $u$ 标度，
搜索的是单座位期望效用。

**chance 节点（`EndTurn`）**：其转移含对手策略与 RNG，严格应做期望
$$
Q(h,\text{EndTurn})=\mathbb{E}_{a_{\text{opp}},c\sim P}
\left[V_\theta(h')\right],
$$
Monte Carlo 估计：对同一 `EndTurn` 边采样 $K$ 次（$K=1$ 为默认；可配 $K>1$ 降方差），
每次采样对手动作（来自对手池）与 RNG，取平均：
$$
\hat Q=\frac{1}{K}\sum_{k=1}^{K}V_\theta(h'_k).
$$
若 $K>1$，边的统计要区分“节点访问”和“转移样本”，实现上作为 chance 节点展开
（§7.5）。

### 3.5 Dirichlet 噪声、温度与动作选择

**根先验噪声**（仅根，训练自对弈时）：
$$
\tilde P_{\text{root}}(a)=(1-\varepsilon)P(a)+\varepsilon\,\mathrm{Dir}(\alpha),
\qquad \varepsilon=0.25,\ \alpha\approx0.3\ (\text{按 245 动作调}).
$$
**策略目标**（visit 分布，带温度 $\tau$）：
$$
\pi_{\text{target}}(a)=\frac{N(\text{root},a)^{1/\tau}}{\sum_b N(\text{root},b)^{1/\tau}}.
$$
训练数据生成：自对弈前若干步 $\tau=1$（探索），后段 $\tau\to0.25$；
评估/部署：$\tau\to0$（取 argmax）或小温度采样。

**动作选择**：训练自对弈按 $\pi_{\text{target}}$ 采样；评测/对局按 argmax 或温度采样。
树复用：执行动作 $a$ 后，新根 = 该子节点（同一回合内状态确定，保留子树）；`EndTurn`
后进入新回合，重新建根（可保留价值估计做 warm start，但通常重建）。

### 3.6 算法伪代码（单次决策）

```text
function SEARCH(root_game, seat, net, cfg):
    root = Node(history=(), game=root_game.copy(), expanded=false)
    root.prior = dirichlet_noise(net.prior(root), cfg)
    for s in 1..S:
        n, game, path = root, root.game.copy(), []
        # SELECT
        while n.expanded and not game.is_over():
            a, n = PUCT_select(n)          # 仅 legal_mask
            game.step(seat, a)             # 普通动作
            if a == END_TURN: drive_opponents(game, seat)   # bot/historical/self-play
            path.append((n.parent, a, n))
            if cfg.worlds > 1: resample_world(game, seat)   # 可选：chance/determinization
        # EXPAND / EVAL
        if game.is_over():
            v = u(game.placements()[seat])
        else:
            o = game.observe(seat); m = game.legal_mask(seat)
            p, val = net(o, m)             # 批量推理时收集 leaf 后一次前向
            n.expand(m, p); v = val
        # BACKUP
        for (parent, a, child) in reverse(path):
            parent.N[a] += 1; parent.W[a] += v; parent.Q[a] = parent.W[a]/parent.N[a]
        root.N_visits += 1
    return normalize_visits(root, cfg.temperature)
```

> 实现上：**树在 Rust**；每个模拟不复制整棵树，只复制根 `Game` + 沿路径 step；
> leaf 评估按批收集（§7.5）。Python 只提供 `net(o,m)` 批量推理与数据落盘。

### 3.7 部分可观测下的搜索（determinization）

严格 POMDP 搜索需要对信念求期望：
$$
Q(h,a)=\mathbb{E}_{s\sim b(h)}\Bigl[\sum_{s'}T(s'\mid s,a)\,V(h')\Bigr].
$$
实现为 **determinization + 多世界线**：

1. 根节点：从 $q(s\mid h)$ 采样 $W_{\text{det}}$ 个世界 $s_1,\dots,s_{W_{\text{det}}}$（$W_{\text{det}}=1$ 默认，训练后期可 2–4）；
2. 每次模拟随机选一个世界（或轮流），沿动作路径推进；叶价值用网络 $V_\theta(o)$；
3. 根统计聚合所有世界线；策略目标用聚合 visit；
4. **$q$ 不使用真实隐藏状态**：初始 $q$ 为公开信息先验（按回合/等级/种族/英雄的历史分布）；
   后续由对手状态估计器 $q_\phi$ 替换（§6.7）。

**初始化 $q$（无估计器时）**：优先从历史 replay 中按 `(turn, tier, lobby races, hero)`
匹配采样对手战团/经济摘要；只能使用公开字段与训练集统计，不能用当前对局真实隐藏值。

**oracle gap 诊断**：另跑一版“特权搜索”（用真实 $s$ 推进、网络仍只看 $o$）只用于测量：
$$
\Delta_{\text{oracle}}=\bar r_{\text{obs-search}}-\bar r_{\text{privileged-search}},
$$
作为估计器/表征改进的指标；**不进入训练数据/部署**。

### 3.8 复杂度与成本模型

一次决策的搜索成本近似：
$$
C_{\text{dec}}\approx S\cdot\bigl(c_{\text{copy}}+L_{\text{path}}\,c_{\text{step}}
+c_{\text{eval}}\bigr),
$$
其中 $S$ 模拟数、$c_{\text{copy}}$ 为 `Game.copy()`、$L_{\text{path}}$ 为根到叶平均步数、
$c_{\text{step}}$ 为 `step`（含对手 bot/chance）、$c_{\text{eval}}$ 摊到每次模拟的网络评估成本。
**批量评估**把 $c_{\text{eval}}$ 从“每模拟一次小前向”降到“每批一次大前向”，是吞吐关键。
总自对弈成本（每局）：
$$
C_{\text{game}}\approx D_{\text{seat}}\cdot C_{\text{dec}}
+D_{\text{opp}}\cdot C_{\text{opp}},
$$
$D_{\text{seat}}\approx 60$–$100$ 决策/局，$D_{\text{opp}}$ 为对手决策数（Phase B 用历史回放/BC，成本近似 0）。
数值预算在开发机基准后回填（§7.8）。

### 3.9 与标准 AlphaZero 假设的对照

| 假设 | BG 实际 | 本设计处理 |
|---|---|---|
| 2 人零和 | 8 人常和 | 单座位 POMDP，backup 用 utility 标量，不取负 |
| 完美信息 | 部分可观测 | 信息集搜索 + determinization；网络只读 obs |
| 确定性 | 商店/战斗/对手随机 | chance 节点/采样；`EndTurn` 宏动作 |
| 固定动作空间 | 245 固定（本设计） | 固定 masked policy；AT 对齐 |
| 可反复访问同一状态 | 需要 clone | Rust `Game.copy()`/状态缓存；树复用 |
| 同一价值函数评估所有状态 | 名次价值随座位/大厅变 | 价值头带座位/大厅上下文（obs 已含） |

结论：本设计是 **“AlphaZero 式学习+搜索”在 8 人 POMDP 上的变体**，不是标准 AlphaZero。

---

### 3.10 早期搜索的 rank-level 价值：成对胜负矩阵（用户明确允许）

> **适用范围**：训练早期（价值网络尚未可靠时）的搜索价值评估；也可作为诊断/数据过滤。
> **不是**训练价值目标（D9 仍只用终局名次），而是搜索时的**相对排名评估器**。

**动机**：从零开始时 $V_\theta$ 近似随机，直接用它做叶评估会让 MCTS 几乎无信号。
用户允许：对某座位，把搜索找到的**多种可能世界线**（候选状态/战团）**彼此对战**，
构造胜负矩阵，用其行分数作为候选策略好坏的参考，并识别“离群”候选。

**定义（候选集）**：在一次决策/一个回合末，收集 $K$ 个候选状态
$\mathcal{B}=\{B_1,\dots,B_K\}$（来源可为：不同 determinization 世界线的回合末战团、
不同动作序列的终局状态、MCTS 叶节点集合）。对每对 $(i,j)$ 用引擎精确战斗模拟 $M$ 次
（固定公共种子集），定义
$$
p_{ij}=\frac{1}{M}\sum_{m=1}^{M}\Bigl(
\mathbb{1}[\text{combat}(B_i,B_j;\xi_m)=\text{win}]
+\tfrac12\mathbb{1}[\text{tie}]\Bigr),\qquad
p_{ji}=1-p_{ij}.
$$
矩阵 $P=(p_{ij})\in[0,1]^{K\times K}$ 为**成对胜负矩阵**。行分数与相对名次：
$$
s_i=\frac{1}{K-1}\sum_{j\ne i}p_{ij},\qquad
\rho_i=1+\sum_{j\ne i}\mathbb{1}[s_j>s_i],\qquad
u_i=1-\frac{2(\rho_i-1)}{K-1}.
$$
$u_i$ 是候选 $B_i$ 的**相对名次效用**（在 $K$ 个候选内，不是最终 8 人名次）。

**性质（完美传递时，推导见附录 A.9）**：若存在强弱全序且无平局，$p_{ij}=\mathbb{1}[i\ \text{强于}\ j]$，
则 $s_i=\frac{K-i}{K-1}$（按强弱排序），且
$$
u_i=1-\frac{2(i-1)}{K-1}=2s_i-1.
$$
即行分数与相对名次效用是仿射等价的；有平局/非传递时用 $\rho_i$ 更稳健。

**不确定性与离群判定**：
- 每个 $p_{ij}$ 的 MC 标准误 $\hat\sigma_{ij}=\sqrt{\hat p(1-\hat p)/M}$；
  行分数标准误 $\hat\sigma_i=\frac{1}{K-1}\sqrt{\sum_{j\ne i}\hat\sigma_{ij}^2}$；
- 稳健离群分数：令 $\mathrm{med}(s)$、$\mathrm{MAD}=\mathrm{median}(|s_i-\mathrm{med}(s)|)$，
  $$
  z_i=\frac{s_i-\mathrm{med}(s)}{1.4826\,\mathrm{MAD}},
  $$
  $|z_i|>\tau_z$ 的候选标记为离群（过强/过弱/非传递），可用于：
  1. **剪枝/降权**（离群候选不作为动作依据或降低其 MCTS 先验）；
  2. **数据过滤**（若根候选整体离群/矩阵不稳定，则该决策样本降权或丢弃）；
  3. **诊断**（世界线采样质量、估计器/对手模型是否异常）。

**在 MCTS 中的接入（早期）**：
1. **叶值替代**：在回合边界（`EndTurn` 之后）取叶状态 $B_0$ 与搜索前沿中 $K-1$ 个
   兄弟/世界线状态组成 $\mathcal B$，算 $P$，用 $v(B_0)=u_0$ 备份；
2. **根动作排序**（可选）：对根动作 $a$ 各采样 $K_a$ 个回合末状态，用矩阵分数作为
   $Q_{\text{pair}}(a)$ 的先验/辅助项；
3. **混合调度**：$v=(1-\alpha)v_{\text{net}}+\alpha v_{\text{pair}}$，$\alpha$ 从 1
   逐步降到 0（价值网络可靠后）；成对矩阵保留为诊断/数据过滤；
4. **成本**：$C_{\text{pair}}=\binom{K}{2}M\,c_{\text{combat}}$；例 $K=16,M=4$
   → 480 场战斗/次评估；Rust 引擎批量战斗可承受，但只在回合边界/关键节点用。

**注意**：成对矩阵是**相对/自指**的评估（只看候选集合内部；推导/方差/离群公式见附录 A.9），不能当作最终 8 人名次
的无偏估计；因此仅用于搜索期 bootstrap/诊断，训练价值目标仍为终局名次（D9）。


## 4. 网络与学习目标

### 4.1 输入

- `features`: f32[3227]（AT 布局：global/quests/pending/board/hand/shop/choices/opponents/opp_boards）；
- `cards`: i32[124]（卡牌 embedding 下标，0=空）；
- 可选：座位/回合/大厅的显式标量（obs 已含大部分；如需要可从 obs 块取，不引入隐藏信息）。
- **禁止**：任何隐藏状态字段（对手手牌/金币/未公开战团）进入输入；审计用“隐藏信息探测分类器”
  验证（§9）。

### 4.2 架构（建议）

- **编码器**：卡牌 embedding + 分块特征嵌入（棋盘/手牌/酒馆/选择/对手）→ 小型 Transformer
  或 MLP-Mixer；输出 token 序列 + 全局向量。
- **策略头**：245 logits（可分解为 `动作类型 + 参数` 两头，降低稀疏性）：
  - 类型头：EndTurn/Refresh/.../Move（16 类）；
  - 参数头：按类型选择 slot/target/pos（条件 softmax）；
  - 训练时用完整 245 的 masked CE；推理用分解头再合成 245 概率（或直接用 245 头，二选一）。
- **价值头**：8 类名次分布 logits $q_\theta(r\mid o)$；同时输出期望效用
  $V_\theta(o)=\sum_r q_\theta(r)u(r)$（搜索叶价值）。
- **可选辅助头**：战斗结果/伤害、目标/顺序、经济等（用模拟器标签；可选，不阻塞主线）。

### 4.3 训练目标

对一条样本 $(o,\pi_{\text{target}},r)$：
$$
\mathcal{L}(\theta)=\underbrace{-\sum_{a}\pi_{\text{target}}(a)\log \pi_\theta(a\mid o)}_{\mathcal{L}_p}
+\lambda_v\underbrace{\Bigl(-\sum_{r'}z_{r'}\log q_\theta(r'\mid o)\Bigr)}_{\mathcal{L}_v}
+\lambda_{\text{aux}}\mathcal{L}_{\text{aux}}
+c\|\theta\|_2^2,
$$
其中 $z$ 为终局名次 one-hot（或软目标，§4.4），$\pi_{\text{target}}$ 为 MCTS visit 分布。

**为什么用名次分布而非只回归标量**：8 人高方差；名次分布保留完整不确定性，
$\mathcal{L}_v$ 的梯度更稳；期望效用 $V=\sum q_ru_r$ 供搜索使用。

### 4.4 目标构造细节

- **策略目标**：$\pi_{\text{target}}(a)=N(a)^{1/\tau}/\sum_b N(b)^{1/\tau}$，
  仅保留 $N(a)>0$ 的动作；可选 **visit 截断**（top-k，k=8–16）减小标签噪声；
- **价值目标**：
  - 硬目标：$z=\mathrm{onehot}(r)$；或 soft target 用历史/多次模拟的名次经验分布；
  - 期望效用目标：$u=u(r)$ 与 $V_\theta$ 的 MSE（辅助）；
- **数据过滤**（§6.5）：低访问数/高熵/低 margin 的决策降低权重或丢弃；
- **对称性**：座位身份不应影响策略（除先手/血量/英雄差异）；可通过随机座位重标/大厅增强
  提升泛化（注意不改变规则语义）；
- **温度**：训练数据 $\tau$ 随回合递减（前 10 回合 1.0，后段 0.5→0.25）。

### 4.5 损失梯度推导

**(a) 策略 masked softmax CE**
设 $z_a$ 为 logits，$p_a=\frac{e^{z_a}m_a}{\sum_b e^{z_b}m_b}$，$m$ 为合法掩码。
$$
\mathcal{L}_p=-\sum_a \pi_a\log p_a
\quad\Longrightarrow\quad
\frac{\partial\mathcal{L}_p}{\partial z_a}=p_a-\pi_a\ \ (\text{合法 }a),
$$
非法动作梯度为 0（masked）。梯度下降更新 $\theta\leftarrow\theta-\eta\nabla_\theta\mathcal{L}_p$。

**(b) 名次分布 CE**
$q_r=\mathrm{softmax}(z_r)$，
$$
\mathcal{L}_v=-\sum_r z_r\log q_r
\quad\Longrightarrow\quad
\frac{\partial\mathcal{L}_v}{\partial z_r}=q_r-z_r.
$$

**(c) 期望效用与 MSE**
$V=\sum_r q_ru_r$，$\mathcal{L}_{\text{MSE}}=\tfrac12(V-u^\star)^2$：
$$
\frac{\partial V}{\partial z_r}=q_r\bigl(u_r-V\bigr),
\qquad
\frac{\partial\mathcal{L}_{\text{MSE}}}{\partial z_r}
=(V-u^\star)\,q_r\bigl(u_r-V\bigr).
$$
（若同时用 CE+MSE，$\lambda$ 调节两者。）

**(d) 正则**：$c\|\theta\|_2^2$ 梯度 $2c\theta$；可加 entropy bonus
$-\beta\sum_a p_a\log p_a$（梯度 $-\beta p_a(\log p_a+1)$）或 KL anchor 到旧策略。

### 4.6 训练稳定性

- 学习率 warmup + cosine；梯度裁剪；
- 每轮数据只来自最近 $M$ 局/迭代（避免 off-policy 过旧）；
- 定期评估（固定 seed）与晋升门禁（§6.8）；
- 价值目标 clip 到 $[-1,1]$；策略目标温度不宜过低（避免过早坍缩）；
- 大 batch（8 人方差）+ 多 seed 平均。

---

## 5. 推理流程

### 5.1 单次决策（部署/自对弈）

1. 取当前座位观测 $o$、掩码 $m$、根 `Game.copy()`；
2. 根先验 $P=\pi_\theta(\cdot\mid o)$（可加噪声，训练时）；
3. 运行 §3.6 的搜索 $S$ 次（Rust 核）；
4. 得到 visit 分布 $\pi_{\text{target}}$，按温度选择动作（训练采样/评测 argmax）；
5. `game.step(seat,a)`；若 `EndTurn` 则推进对手/战斗；重复直到终局。

### 5.2 搜索预算与模式

| 模式 | S（模拟/决策） | 用途 |
|---|---:|---|
| 数据生成（训练） | 16–64（随迭代升） | 高质量 $\pi$ 目标 |
| 评估/对局（强） | 64–256 | 评测上限/teacher |
| 部署（快） | 1（纯策略）或 8–16 | 实时/大规模评测 |
| 蒸馏 | 大 S 生成 → 小模型 | Search→Policy 蒸馏 |

> Phase A 为 **8 座全搜索**（D6）：总成本 ≈ 8×单座搜索；S 建议先 8–16，
> 效率基准（§7.9）后再定；批量/多机扩展优先于减座位。

### 5.3 批量推理与树复用

- 多局/多树并行：Rust 收集 leaf，批量送 GPU；虚拟损失避免重复；
- 同一回合内：执行动作后下移根、保留子树（状态确定，只需更新 mask/obs）；
- `EndTurn` 后重开根；跨回合不重用（或只用价值估计做 warm start）。

### 5.4 确定性

- 每局种子 `seed`；搜索随机源（Dirichlet、chance 采样）用独立 RNG；
- 相同 seed + 相同模型 + 相同 S ⇒ 相同轨迹（虚拟损失/线程调度需固定顺序或记录）；
- 数据样本记录 `seed, S, temperature, model_version` 以便复现。

---

## 6. 训练流程（两阶段交替）

### 6.1 总循环（Expert Iteration）

```text
θ ← 随机初始化
for iteration k = 1..K:
    D_k ← GENERATE(θ, phase_schedule(k))      # Phase A 或 B
    buffer.add(D_k); buffer.prune(recent=M)
    θ ← TRAIN(buffer, θ, epochs=E)             # policy CE + value CE + aux
    metrics ← EVALUATE(θ, fixed_seeds, baselines, search_on/off)
    if PROMOTE(metrics): champion ← θ
    if SWITCH_CONDITION(k): phase ← other_phase
```

数据只保留最近 $M$ 局（滑动窗口）+ 可选优先采样；每轮开始用当前 champion 生成新数据。

### 6.2 Phase A：全 8 座自对弈

- **D6：8 个座位全部由当前模型 + MCTS 搜索控制**（成本 ×8，必须用 Rust 核/批量评估/
  S 预算控制；效率基准见 §7.9）。
- 对手即自己的历史/当前策略；为增加多样性可混合：
  - 当前 champion + 历史 checkpoint 池（league），
  - 小概率脚本 bot/随机策略（防退化）。
- 数据：每个座位的决策都记录 $(o,\pi_{\text{target}},r)$；价值目标同名次。
- 目标：产生**高质量、分布广**的数据（探索通过 Dirichlet/温度/多 seed）。
- 成本控制：初期 8 座全搜索 S=8–16；数据质量达标后**仍保持 8 座全搜索**（D6），
  通过提高批量/多机扩展吞吐，而不是减少搜索座位；如需降本，只降 S/缩短局，不改座位搜索。

**Phase A 数据分布**：
$$
\mathcal{D}_A=\Bigl\{(o_t,\pi_t,r)\ \Bigm|\ 
s\sim\text{SelfPlay}(\pi_\theta^{\otimes 8}),\ 
\pi_t=\mathrm{MCTS}_\theta(h_t)\Bigr\}.
$$

### 6.3 Phase B：1 座学习 + 7 座历史对手

**触发条件**：Phase A 产生“足够高质量数据”（§6.4 定义），进入 Phase B 以**降低生成成本、
增加对手多样性、逼近真实分布**。

**历史对手库** $\mathcal{H}$：来自我们自己的历史数据（replay），每条记录包含：
- 对局 id、轮次 $t$、大厅（种族/英雄/饰品/异变配置）、座位 $j$ 的**完整状态快照**；
- 该座位从 $t$ 起的**动作序列**（用于回放/BC）；
- 该对局的终局名次（质量标签）、模型版本、搜索 $S$、时间戳。

**采样**：给定学习座位当前回合 $t$ 与公开上下文 $c$（大厅/回合/等级/血量区间），
$$
(g,j)\sim p(g,j\mid t,c)\ \propto\ \mathrm{qual}(g)\cdot\mathrm{div}(g,j)\cdot
\mathbb{1}[\text{match}(g,j,t,c)],
$$
从 $\mathcal{H}$ 取该座位在 $t$ 的状态快照，实例化为对手。

**对手策略** $\pi^{\text{hist}}_j$（**D7：默认回放**）：
1. **回放模式（默认）**：动作序列逐条重放；若动作在当前状态非法（因学习座位改变了战斗结果），
   从该点切换到脚本 bot fallback（不默认改 BC）；
2. **行为克隆模式（可选/研究）**：用历史数据训练 $\pi^{\text{BC}}_j(a\mid o)$，
   作为 fallback 或消融，不作为默认对手。

**对手分布**：
$$
\mu_{\text{hist}}(a_{\text{opp}}\mid s)=\sum_{(g,j)\in\mathcal{H}}w_{g,j}\,
\pi^{\text{hist}}_{g,j}(a_{\text{opp}}\mid o_{\text{opp}}(s)).
$$

**学习目标**（单座位）：
$$
J_B(\theta)=\mathbb{E}_{(g,j)\sim p,\ \pi_\theta,\ \mu_{\text{hist}}}
\bigl[u(r)\bigr].
$$

**数据分布**：
$$
\mathcal{D}_B=\Bigl\{(o_t,\pi_t,r)\ \Bigm|\ 
\text{learner seat in }(\pi_\theta\text{ vs }\mu_{\text{hist}}),\ 
\pi_t=\mathrm{MCTS}_\theta(h_t)\Bigr\}.
$$

**隐藏信息**：学习座位只看到 $o$；历史对手的隐藏状态（手牌/金币/未公开战团）不进入
学习座位的输入；搜索用 $q(\cdot\mid o)$ determinization（§3.7），不使用对手真实隐藏值。

### 6.4 交替调度与切换条件

**Phase A → Phase B（“足够高质量数据”）**，建议判据（全部满足）：
1. buffer 中高质量对局数 $N_{\text{hq}}\ge N_{\min}$（如 50k–200k 局）；
2. 数据质量：$\mathbb{E}[\text{visits at root}]\ge S_{\min}$，top-1 visit margin
   $\ge m_{\min}$，根价值与结果相关性 $\ge\rho_{\min}$；
3. 竞技指标：champion 对 heuristic/上一代胜率 $\ge w_{\min}$，且 oracle gap 在可接受范围；
4. 多样性：对手/大厅/英雄覆盖度 $\ge d_{\min}$。

**Phase B → Phase A**（回到全自对弈以刷新对手池），建议判据：
1. Phase B 新数据量 $\ge N'_{\min}$；
2. 学习座位对历史对手池胜率 $\ge w'_{\min}$ 且对当前 champion 不退化；
3. 历史对手库已刷新（新快照占比 $\ge$ 阈值），避免过拟合旧对手；
4. 数据质量指标仍达标。

**调度形式化**：设 phase $k\in\{A,B\}$、阶段长度（迭代数/局数）$L_A,L_B$、
数据混合权重 $\alpha_k$；每轮训练数据
$$
\mathcal{D}_k=\alpha_k\mathcal{D}_{A}+(1-\alpha_k)\mathcal{D}_{B}
$$
（或只用当前阶段数据 + 少量旧数据）。切换是**状态机**：
$$
\text{state}_{k+1}=\begin{cases}
B,&\text{state}_k=A\ \land\ \text{Cond}_{A\to B}\\
A,&\text{state}_k=B\ \land\ \text{Cond}_{B\to A}\\
\text{state}_k,&\text{otherwise}
\end{cases}
$$
初期只跑 A（冷启动），达到条件后按上述交替；长期可用“A 生成新对手 → B 学多样对手”
的循环（类似 league/curriculum）。

### 6.5 数据质量过滤与优先采样

**样本级**：
- 访问数 $N_{\text{root}}\ge S_{\min}$；
- 根 visit 熵 $H(\pi_{\text{root}})\in[H_{\min},H_{\max}]$（过低=无探索，过高=无信号）；
- top-1 margin $N_1-N_2 \ge \Delta_{\min}$；
- 根价值 $V_{\text{root}}$ 与最终 $u$ 的偏差（同局/同回合）在阈值内。

**对局级**：
- 对局完整、无 `truncated_combats/contexts` 异常、无非法动作回退；
- 与当前策略的 KL 不过大（避免过时数据）；
- 去重：同 seed/同轨迹哈希只保留一次。

**优先采样**：按“TD/价值误差、margin、稀有对手/大厅”加权；维护 replay 容量 $M$，
只训练最近 $M$ 局（或重要性采样）。

### 6.6 从零冷启动（无 BC、无人类数据）

1. $\theta_0$ 随机；前 $K_0$ 轮用 **成对胜负矩阵（§3.10）或 rollout 价值**作为叶评估，
   $\alpha$ 逐步降到 0（D11 效率优先：先测 $K,M,S$ 的吞吐/质量曲线）；
2. 搜索预算 $S$ 从 8→16→32→64 递增；
3. 先用短局（`max_turns` 较小）降低方差/成本，再放开到完整局；
4. 价值头先只用终局名次训练（数据量大、便宜），策略头随后；
5. 若初期数据几乎全随机：保留高熵样本、增大温度/探索，直到出现非平凡策略；
6. 可选“先学价值、后学策略”的两段式（价值可用随机自对弈终局标签预训练）。

### 6.7 隐藏信息与对手状态估计（后续，用户设计）

**接口预留**：Rust 搜索核的 determinization 模块接受一个 `BeliefSampler`：
$$
q_\phi(h\mid o)\quad\Rightarrow\quad \text{采样世界 } s\sim q_\phi.
$$
接上估计器后：
- 搜索：用 $q_\phi$ 采样/加权世界线，改善部分可观测搜索；
- 训练：估计器可用历史 replay 做辅助监督（预测对手战团/经济/手牌规模等），
  或与策略联合训练（辅助损失）；
- 评估：对比 $q_\phi$ 前后 $\bar r$ 与 oracle gap；不得把真实隐藏值作为输入。

**当前实现（无估计器）**：$q_0$ 为按公开信息（回合/等级/大厅/英雄）的经验分布
（从历史 replay 统计），并对每个对手座位独立采样。

### 6.8 评估、晋升与停止

- 固定 seed 集（如 seed=0..499，500 局）评测：
  - vs 脚本 bot（heuristic）、上一代 champion、search-off 版本、历史对手池；
  - 指标：平均名次、前四率、冠军率、期望效用、对局时长、invalid/truncated；
- **搜索增益**：同一模型 search-on vs search-off 的胜率差；
  若长期无增益，降低搜索预算或检查价值/目标；
- 晋升：champion 只在显著优于当前 champion（如 +2% 名次/胜率，配对检验）时替换；
- 停止：预算耗尽 / 指标收敛 / 数据质量饱和。

### 6.9 数据与对手库格式（摘要，详见 §8）

- 样本：`features[3227] f32, cards[124] i32, mask[245] u8, pi: sparse[(a,N)], rank r, seat, turn, game_id, model_version, S, temperature, seed`。
- 对手库：`game_id, turn, seat, lobby, hero, snapshot(state_json), actions[], rank, quality, model_version`。
- 所有数据带 `data_version`（37.0.0.255130）与 `engine_version`，跨版本不可混用。

---

## 7. Rust 搜索核设计

### 7.1 目标与非功能要求

- **吞吐**：搜索不成为训练瓶颈；单核 ≥500–1000 sims/s（待基准），批量 NN 评估；
- **确定性**：同 seed/S/模型 ⇒ 同搜索轨迹（可复现数据）；
- **低开销**：`Game.copy`、`step`、`observe` 的 p50/p99 可测；树内存可控；
- **可扩展**：chance/determinization/自定义对手/BeliefSampler 可插拔；
- **无需 GIL**：搜索在 Rust 线程中运行（`py.allow_threads`），仅批量评估回 Python。

### 7.2 Crate / 模块结构

建议在 fork 内新增 crate `crates/hsbg-search`（依赖 `hsbg-engine`），或
`crates/hsbg-engine/src/search/` 模块：

```
crates/hsbg-search/
  Cargo.toml
  src/
    lib.rs          // 公开 API
    config.rs       // SearchConfig
    node.rs         // Node/Edge 紧凑结构
    tree.rs         // arena/树复用/路径
    puct.rs         // 选择（PUCT + 虚拟损失）
    backup.rs       // 价值备份/chance
    eval.rs         // Evaluator trait + 批量队列
    determinize.rs  // BeliefSampler trait + 默认先验
    opponent.rs     // 对手策略（bot/历史/自对弈/回放）
    pairwise.rs     // §3.10 成对胜负矩阵评估（早期价值/离群诊断）
    stats.rs        // 诊断/日志
  tests/
```

### 7.3 数据结构（建议）

```rust
struct Edge { action: u16, n: u32, w: f32, p: f32, child: NodeId }
struct Node {
    parent: NodeId, action: u16, depth: u16,
    terminal: bool, expanded: bool,
    sum_n: u32, children: Vec<Edge>,   // 小数组可内联
}
struct Tree { nodes: Vec<Node>, root: NodeId, rng: SmallRng }
```

内存：节点数 $\approx$ 搜索模拟数 × 平均分支；单节几百字节量级；按需用 arena/SoA 优化。

### 7.4 状态复制、回放与 RNG

两种策略，基准后二选一：
1. **节点存 Game**：每个节点持有 `Game`（或 `Box<Game>`）；简单但内存大；适合小 S；
2. **路径回放**：树只存动作路径；每次模拟从根 `Game.copy()` 出发逐步 `step`；
   内存小，代价是重复 step；适合深树/大 S。
建议：**默认路径回放**（内存可控），对高频子树缓存 `Game`（LRU）；基准后定。
- `Game.copy` 含 RNG；chance 采样用树级 RNG（独立 seed），`EndTurn` 边记录采样种子；
- `state_json/from_json` 仅用于快照/调试（JSON 慢，不做热路径）。

### 7.5 评估器与批量推理

```rust
pub struct EvalRequest { pub obs: Observation }        // 3227+124
pub struct EvalResult { pub policy: Vec<f32>,          // 245
                        pub value: f32,                // E[u]
                        pub ranks: [f32; 8] }          // 可选
pub trait Evaluator: Send + Sync {
    fn evaluate(&self, requests: &[EvalRequest]) -> Vec<EvalResult>;
}
```

- **Rust 侧**：多个搜索线程把 leaf 请求放入 `crossbeam` 队列；一个 evaluator 线程批量
  取请求 → 调 Python 回调（`Python::with_gil`，一次批量）→ 回填；
- **Python 侧**：`hsbg/search/engine_mcts_rs.py` 封装 `search(...)`，传入可调用对象
  `eval_fn(features, cards, masks) -> (logits, value, ranks)`；内部用 Torch 批量前向；
- 虚拟损失在等待评估期间生效；
- 备选（更简单、先做）：单树批量——收集当前树的所有 leaf，一次前向，回填；
  多局并行在进程级（每进程一局），适合 M0/M1。

### 7.6 Determinization / BeliefSampler

```rust
pub trait BeliefSampler: Send + Sync {
    /// 从与观测 o 一致的分布中采样隐藏世界，返回可推进的 Game 状态。
    fn sample_world(&self, game: &Game, seat: usize, rng: &mut Rng) -> Game;
}
```
- 默认实现：按公开信息经验先验采样（§3.7）；不读真实隐藏值；
- 后续：用户设计的对手状态估计器实现该 trait（或提供 `q(h|o)` 的采样/似然）；
- 需要引擎侧正式 API 来**注入/重建隐藏状态**（`debug set_player` 可先接入，
  正式版在引擎加 `Game::resample_hidden(...)` 或 `DeterminizeConfig`）。

### 7.7 对手策略

```rust
pub trait OpponentPolicy: Send + Sync {
    fn act(&self, game: &Game, seat: usize, rng: &mut Rng) -> u16;
}
```
- `BotOpponent`：`Game::bot_action`；
- `ReplayOpponent`：按历史动作序列重放（失败 fallback bot）；
- `LeagueOpponent`：历史 checkpoint 的 policy（纯策略，不搜索）；
- `SelfPlayOpponent`：当前网络纯策略（Phase A 中其它座位）。
- 统一通过 `drive_opponents(game, learner_seat, &dyn OpponentPolicy)` 推进 `EndTurn` 后的
  7 座行动。

### 7.8 API 草案（Python 视角）

```python
import hsbg_engine as E
from hsbg.search.engine_mcts import MCTSConfig, search

cfg = MCTSConfig(simulations=32, c_puct=2.0,
                 dirichlet_alpha=0.3, epsilon=0.25,
                 temperature=1.0, max_turns=20,
                 worlds=1, virtual_loss=1.0)
g = E.Game(seed=0)
res = search(g, seat=0, cfg=cfg, eval_fn=net.eval_batch,
             opponents="selfplay", belief=None)
# res.pi: np.ndarray[245] 访问分布；res.action: int；res.stats: dict
```

### 7.9 效率优先的 M0 基准计划（远程机，D11）

> **先测效率，再定实现与数据规模**：M0 不追求强度，只回答“逐步 MCTS + Rust 核 +
> 8 座全搜索能否在可接受成本内产出数据”。

**必须测（按顺序）**：
1. **状态原语**：`Game.copy()`、`step`（普通/`EndTurn`）、`observe`、`legal_mask`
   的 p50/p95/p99；`Game.copy` 决定“节点存 Game vs 路径回放”（§7.4）。
2. **单树搜索**：S=8/16/32/64 的 sims/s（单核/多核）；批量 NN 评估的 batch/延迟；
   虚拟损失开/关对比；树内存。
3. **8 座全搜索端到端**：1 局 8 座搜索的耗时、games/h、每局节点数/内存；
   与“8 座纯策略”对比（仅参考）；
4. **成对矩阵（§3.10）**：$K=8/16/32$、$M=2/4/8$ 的组合战斗吞吐、单次评估耗时；
   离群检测（MAD）与排序稳定性；
5. **数据生成吞吐**：在给定 S/K/M 下，每小时可产生多少高质量样本；
   据此反推 100k/1M 局所需机时与节点成本。

**目标（初版，待实测修正）**：单核 ≥500 sims/s；copy p99 <200µs；
8 座全搜索 ≥2–5 局/h/进程组（逐步搜索很重，需实测）；成对矩阵不成为主要瓶颈。
**决策点**：若 8 座全搜索成本过高，优先用 S 预算/批量/多机扩展，而不是减座位（D6）；
若 copy 成本过高，走“路径回放 + 缓存”或 Rust 侧树状态共享。

---

## 8. 数据与回放

### 8.1 样本 schema

```text
sample = {
  features: float32[3227], cards: int32[124], mask: uint8[245],
  pi: [(action:int, visits:int)],          # 稀疏；或 float16[245]
  rank: uint8,                              # 1..8
  seat: uint8, turn: uint8,
  game_id: int64, model_version: str, S: int, temperature: float,
  seed: int64, data_version: "37.0.0.255130", engine_version: "hsbg_engine-1.0.0",
  stats: { root_value: f32, visits: int, entropy: f32, top1_margin: int }
}
```

### 8.2 存储与索引

- 分片 HDF5/Parquet：每 shard 固定样本数；按 `game_id/turn` 索引；
- replay：内存环形缓冲 + 磁盘归档；最近 $M$ 局参与训练；
- 数据版本/引擎版本/模型版本必须记录，跨版本不可混训（卡牌下标/动作语义可能变）。

### 8.3 对手库（Phase B）

```text
opponent_record = {
  game_id, turn, seat, lobby_races, hero, tier, health,
  snapshot: state_json,      # 该座位在 turn 起点的完整状态
  actions: [u16...],         # 该座位 turn 起的动作序列（回放/BC）
  rank, quality, model_version, S, data_version
}
```

按 `(turn, lobby, tier, hero)` 建索引；refresh 频率与 Phase 切换绑定（§6.4）。

### 8.4 可复现性

- 每局 seed、搜索 seed、Dirichlet RNG seed、chance 采样种子全部记录；
- 同数据版本 + 同引擎版本 + 同模型 + 同 seed ⇒ 同轨迹；
- 训练脚本固定 Python/NumPy/Torch 种子；数据管线支持 dry-run/校验。

---

## 9. 评测与验收

### 9.1 指标

- **强度**：平均名次（主）、前四率、冠军率、期望效用；对固定基线的配对胜率；
- **搜索**：search-on/off 差、不同 S 的收益曲线、oracle gap；
- **数据质量**：root visits、margin、熵、价值-结果相关性、非法动作率；
- **效率**：games/h、sims/s、GPU 利用率、数据生成/训练占比；
- **泛化**：未见大厅/英雄/饰品的表现；历史对手池胜率。

### 9.2 固定 seed 与统计

- 评测 seed 集与训练/自对弈 seed 分离（防泄漏）；
- 500–2000 局/配置；报告 95% bootstrap CI；配对比较（同 seed 对手）；
- 显著性阈值：名次差 ≥0.1 或胜率差 ≥2%（CI 不跨 0）才晋升。

### 9.3 阶段门禁（建议）

| 阶段 | 门禁 |
|---|---|
| M0 接口/基准 | copy/step/obs 基准有数；BatchEnv/search smoke；同 seed 复现 |
| M1 Python MCTS | 1k 局无崩溃；搜索 π 比 raw policy A/B 显著更好；数据 schema 校验 |
| M2 Rust 核 | 吞吐目标；1 万局数据训练；vs heuristic 胜率提升；oracle gap 记录 |
| M3 Phase A/B | Phase A 数据质量达标 → Phase B 不退化；历史对手池胜率≥阈值 |
| M4 规模化 | 全量训练后名次 < heuristic/BC；搜索增益可复现；TavernBench 对照 |

### 9.4 与 AT/TavernBench 的可比性

- 动作/观测与 AT 逐位一致（245/3227/124），但数据版本不同（我们 37.0.0.255130，
  AT 36.6.3）；对比时注明并按 card id 重映射；
- 可选 adapter：把 obs 转成 TavernBench prompt/答案格式，评 decision accuracy；
  TavernAgent 答案可作对照（不参与训练）。

---

## 10. 远程开发机部署（`biocourse-glt`）

### 10.1 机器事实（实测，2026-10-26）

- SSH 别名：`biocourse-glt`（`~/.ssh/config`），HostName `166.111.155.157`，Port 822，
  User `gaoletian`；`hostname` = `oulab-cs9`；
- CPU 128 核；内存 ~503 GiB；至少 4× RTX 4090（`nvidia-smi -L` 前 4 张确认，可能更多）；
- `/home/data` 44T（可用 ~7.9T）；base conda Python 3.14，**无 torch、无 cargo**；
- 本 Mac 仅代码编写，**所有训练/性能测试在远程机执行**；
- **D11/D7 补充**：远程机允许构建依赖（rustup/conda/torch 均可装）；第一件事是
  §7.9 的 M0 效率基准，用实测决定搜索实现与数据规模。

### 10.2 目录与环境（建议）

```
~/projects/HSBRSIM            # git clone（与 ~/rna2smol 分开，勿覆盖）
~/envs/hsbrsim                # conda env（python 3.11 + torch cu121）
```

### 10.3 部署步骤（开发计划阶段执行）

```bash
ssh biocourse-glt
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/Gallo13th/HSBRSIM.git   # 公开仓库，HTTPS 即可
cd HSBRSIM

# Rust（rustup；当前 PATH 无 cargo）
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source ~/.cargo/env
rustc --version && cargo --version

# Python（不要用 base 3.14；建独立 env）
conda create -n hsbrsim python=3.11 -y
conda activate hsbrsim
pip install -U pip numpy pytest
pip install torch --index-url https://download.pytorch.org/whl/cu121
cd rust && pip install -e . && cd ..
python3 -c "import hsbg_engine as E; print(E.game_version(), E.db_info())"

# 冒烟/基准（远程机执行，结果用于性能预算）
cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine
python3 rust/bench_engine.py --games 2000 --e2e-games 20
```

### 10.4 性能基准命令（M0 用）

```bash
# 单测/基准（需在远程机）
python3 -m tools.p3_verify.run_all --skip-rebuild   # 内容回归
cargo test --release -p hsbg-engine
# 新增搜索基准（待实现）：copy/step/obs 延迟、S 扫描、8 座 vs 1 座吞吐
python3 scripts/bench_search_engine.py --games 20 --sims 8,16,32,64 --threads 8
```

---

## 11. 公式推导附录

### A.1 PUCT 的探索项

UCB1 的探索项 $\sqrt{2\ln N/N_a}$ 在树中把 $N$ 换成父访问、并乘以先验 $P(a)$ 缩放：
$$
\text{explore}(a)=c_{\text{puct}}P(a)\frac{\sqrt{\sum_b N_b}}{1+N_a}.
$$
先验 $P(a)=\pi_\theta(a\mid o)$ 提供“人类先验/策略先验”，在 $N_a$ 小时主导；
$N_a$ 大时 $Q$ 主导。$1+N_a$ 避免除零；$\sqrt{\cdot}$ 控制探索随总访问增长（对数级）。

### A.2 策略 CE 的梯度

$p_a=\mathrm{softmax}(z)_a$，$m$ 掩码。$\mathcal{L}_p=-\sum_a\pi_a\log p_a$：
$$
\frac{\partial\mathcal{L}_p}{\partial z_a}
=-\frac{\pi_a}{p_a}\frac{\partial p_a}{\partial z_a}
=-\frac{\pi_a}{p_a}p_a(1-p_a)+\sum_{b\ne a}\frac{\pi_b}{p_b}p_b p_a
=p_a-\pi_a.
$$
（掩码下只对合法动作求和；非法动作 $p=0,\pi=0$，梯度 0。）

### A.3 名次分布 CE / 期望效用

$q_r=\mathrm{softmax}(z)_r$，$\mathcal{L}_v=-\sum_r z_r\log q_r$：
$$
\frac{\partial\mathcal{L}_v}{\partial z_r}=q_r-z_r.
$$
$V=\sum_r q_ru_r$：
$$
\frac{\partial V}{\partial z_r}=q_r u_r-q_r\sum_s q_su_s=q_r(u_r-V).
$$
若 $\mathcal{L}_{\text{MSE}}=\frac12(V-u^\star)^2$：
$$
\frac{\partial\mathcal{L}_{\text{MSE}}}{\partial z_r}
=(V-u^\star)q_r(u_r-V).
$$
两者组合 $\mathcal{L}_v=\text{CE}+\lambda_{\text{MSE}}\text{MSE}$。

### A.4 chance 节点与方差

`EndTurn` 的 $Q$ 是随机变量 $\hat Q_K=\frac1K\sum_{k=1}^K V(h'_k)$；
$\mathbb{E}[\hat Q_K]=Q$，$\mathrm{Var}(\hat Q_K)=\mathrm{Var}(V(h'))/K$。
$K$ 增大降方差但成本线性增；建议先 $K=1$（大 S/多局平均），
对高方差局面（末期/多对手）用 $K=2$–4。

### A.5 虚拟损失

设边 $a$ 有 $v_a$ 个 in-flight 评估，若直接按 $Q=W/N$ 选择，多个线程会重复走同一路径。
虚拟损失把每条 in-flight 视为“暂时失败”：
$$
\tilde Q=\frac{W-c_{\text{vl}}v_a}{N+v_a},
$$
选择后 $v_a\leftarrow v_a+1$；评估完成回填 $W,N$ 并 $v_a\leftarrow v_a-1$。
$c_{\text{vl}}$ 控制并行去重强度；过大会过度惩罚高价值路径。

### A.6 数据质量指标

- 根 visit 熵 $H(\pi_{\text{root}})=-\sum_a\pi_a\log\pi_a$；
- top-1 margin $\Delta=N_1-N_2$；
- 价值一致性：$\rho=\mathrm{corr}(V_{\text{root}},u)$（同回合/同局分桶）；
- 有效样本数 $\mathrm{ESS}=(\sum_i w_i)^2/\sum_iw_i^2$（优先采样权重）。
过滤阈值用验证集/分位数确定，写入数据管线配置。


### A.8 为什么 MCTS 能提升数据质量（策略改进）

**有限 MDP 的策略改进定理**：给定策略 $\pi$，定义
$Q^\pi(s,a)=\mathbb{E}_\pi[G_t\mid s,a]$，
$$
\pi'(a\mid s)=\mathbb{1}\bigl[a=\arg\max_b Q^\pi(s,b)\bigr].
$$
则对任意 $s$：$V^{\pi'}(s)\ge V^\pi(s)$（策略改进定理）。AlphaZero 用 MCTS 的访问分布
$$
\pi_{\text{MCTS}}(a\mid s)\approx \frac{\exp(\beta Q(s,a))}{\sum_b\exp(\beta Q(s,b))}
$$
（$\beta$ 随访问数增大）去逼近贪心策略，因此**搜索产生的 π 目标优于当前策略**；
反复“搜索生成 π → 蒸馏回策略”是近似策略迭代。

**MCTS 的收敛性**：对有限 MDP，PUCT/UCT 的 regret 有
$O(\sqrt{N})$ 界（Kocsis–Szepesvári 2006），访问次数趋于最优动作；
有限模拟下存在近似误差，误差随 $S$ 下降但受先验/价值网络误差影响。

**本任务的两个偏离**：
1. **部分可观测**：上述定理在 belief-MDP 上成立（信念为状态）；我们用 determinization
   采样信念，收敛性变为“在采样世界上的期望”，误差来自 $q(\cdot\mid o)$ 与真实信念的差
   （这也是后续对手状态估计器的动机）；
2. **8 人非平稳**：对手策略随训练变化，$Q$ 非平稳；策略改进是“针对当前对手池”的局部改进，
   不是全局最优保证。因此需要 **league/历史对手池 + 定期重新评估**，不能只信单轮数据。

**数据质量的三条保证**：
1. π 来自搜索（访问分布），而非策略网络的 argmax——搜索提供“改进方向”；
2. 价值目标来自真实终局名次（MC，无偏）——价值学习提供“方向正确性”；
3. 过滤（§6.5）剔除低置信/低访问/异常样本——控制标签噪声。

### A.7 阶段切换判据（形式化）

$$
\text{Cond}_{A\to B}=\mathbb{1}\Bigl[
N_{\text{hq}}\ge N_{\min}\ \land\ 
\mathbb{E}[N_{\text{root}}]\ge S_{\min}\ \land\
\mathbb{E}[\Delta]\ge\Delta_{\min}\ \land\
\rho\ge\rho_{\min}\ \land\
w_{\text{champ}}\ge w_{\min}\ \land\
\text{cov}\ge d_{\min}
\Bigr],
$$
$$
\text{Cond}_{B\to A}=\mathbb{1}\Bigl[
N'_B\ge N'_{\min}\ \land\
w_{\text{hist}}\ge w'_{\min}\ \land\
\text{fresh}(\mathcal{H})\ge f_{\min}
\Bigr].
$$
阈值在 M1–M2 用实测分布校准；未达标不切换，避免“数据不够就换阶段”的抖动。

### A.9 成对胜负矩阵的推导与性质

**定义**（同 §3.10）：
$$
p_{ij}=\frac1M\sum_{m=1}^M\Bigl(\mathbb 1[\text{win}]+\tfrac12\mathbb 1[\text{tie}]\Bigr),
\quad s_i=\frac{1}{K-1}\sum_{j\ne i}p_{ij},
\quad \rho_i=1+\sum_{j\ne i}\mathbb 1[s_j>s_i],
\quad u_i=1-\frac{2(\rho_i-1)}{K-1}.
$$

**完美传递情形**：若候选可按强度全序排列，且 $p_{ij}=1$ 当且仅当 $i$ 强于 $j$
（无平局），则对第 $i$ 强（$i=1$ 最强）：
$$
s_i=\frac{1}{K-1}\sum_{j\ne i}\mathbb 1[i\ \text{强于}\ j]
=\frac{K-i}{K-1},
$$
$$
u_i=1-\frac{2(i-1)}{K-1}
=1-\frac{2\bigl((K-1)-(K-i)\bigr)}{K-1}
=1-2+2s_i=2s_i-1.
$$
即**行分数与相对名次效用仿射等价**；因此用 $s_i$ 排序与用 $u_i$ 排序一致。

**平局/非传递**：平局按 0.5 计；若存在循环克制（$p_{ij}>0.5,p_{jk}>0.5,p_{ki}>0.5$），
$s_i$ 仍是“平均胜率”的合理度量，但 $\rho_i$ 可能出现并列/非传递；此时
$u_i$ 用 $\rho_i$ 计算并保留平局处理（并列取平均名次）。

**MC 误差**：$p_{ij}$ 的估计方差
$$
\widehat{\mathrm{Var}}(p_{ij})=\frac{\hat p_{ij}(1-\hat p_{ij})}{M},
\qquad
\widehat{\mathrm{Var}}(s_i)=\frac{1}{(K-1)^2}\sum_{j\ne i}\widehat{\mathrm{Var}}(p_{ij}),
$$
（$p_{ij}$ 与 $p_{ik}$ 因共享 $B_i$ 而相关，上式忽略协方差，作为保守近似）。
名次 $\rho_i$ 的不确定性可用 bootstrap（重采样 $M$ 场战斗）估计；若 bootstrap 名次
区间过宽，则候选/矩阵不可靠，降权。

**离群分数**：$\mathrm{MAD}=\mathrm{median}_i|s_i-\mathrm{med}(s)|$，
$$
z_i=\frac{s_i-\mathrm{med}(s)}{1.4826\,\mathrm{MAD}},
$$
1.4826 使 MAD 在正态下近似标准差。$|z_i|>\tau_z$ 视为离群；也可用
leave-one-out 检查 $s_i$ 是否由单一对手造成。

**偏差说明（重要）**：$u_i$ 是**候选集合内**的相对效用，候选集合的构造
（世界线/动作/回合）会改变其含义；它不是最终 8 人名次的无偏估计。用于：
(1) 早期叶值 bootstrap；(2) 动作/候选排序的先验；(3) 离群/异常诊断；
(4) 数据过滤。训练价值目标仍为终局名次（D9），不把 $u_i$ 当训练标签。


---

## 12. 风险、开放问题与待拍板

### 12.1 风险

1. **`Game.copy` 成本**未知（Mac 未测；远程机 M0 先 benchmark）——决定用“节点存 Game”
   还是“路径回放”，也是搜索吞吐上限。
2. **从零 MCTS 早期信号弱**：随机价值/策略下搜索增益小；需 rollout 冷启动/短局/大 S。
3. **隐藏信息处理**：determinization 先验不准会拖累搜索；估计器接入前需评估 oracle gap。
4. **8 人高方差/非平稳**：价值目标噪声大；需要名次分布、大样本、固定对手池。
5. **Phase B 历史对手语义**：回放动作在状态偏移时非法；BC 对手可能太弱/太强；
   需定义 fallback 与质量筛选。
6. **搜索与训练吞吐**：Rust 核 + 批量评估是硬工程；Python 侧每步往返必须消除。
7. **数据规模/算力**：从零需要大量自对弈；128 核 + 4×4090 可支撑，但需预算管理。
8. **规则/数据版本**：37.0.0 与 AT 36.6.3 不同；评测对比需注明，不可混用卡牌下标。
9. **成对矩阵成本**：$K^2M$ 战斗在深树/多座搜索下可能成为瓶颈；只在回合边界/关键节点用，
   并做批量/缓存；离群阈值需校准，避免误剪。

### 12.2 已确认决策（v0.2）与剩余问题

**已确认（用户 2026-10-26）**：
1. Phase A **8 座全搜索**（D6）；
2. 历史对手**回放**（D7）；
3. 隐藏信息/对手状态估计用**统一接口**（D8，`BeliefSampler`）；
4. 训练价值**只用终局名次**（D9，不做 TD/中间目标）；
5. 动作空间**严格 245 对齐 AT**（D10，不用 245+ 扩展）；
6. **先测效率**再定数据规模（D11）；
7. 远程机**允许构建依赖**（D11）。

**仍需在开发计划阶段细化（不阻塞设计）**：
1. 历史对手匹配粒度：`(turn, lobby, hero, tier)` 之外是否加血量/经济带；回放 fallback
   的具体触发条件（动作非法/状态哈希不匹配）。
2. 成对矩阵参数：$K$、$M$、离群阈值 $\tau_z$、使用节点范围（仅回合边界 vs 关键决策）；
   以及它与价值网络的混合调度 $\alpha$。
3. M0 效率基准后的具体指标：8 座全搜索可接受的 games/h、单局成本、内存上限；
   据此定第一版数据规模（10 万/100 万局）与远程机并行方案。
4. `BeliefSampler` 的最小接口签名（输入观测/输出世界采样）、估计器何时接入（训练到
   何水平）、oracle gap 的可接受阈值。
5. 网络规模/训练超参（在 M0/M1 后按吞吐与样本效率定）。
6. 远程机环境细节：conda/CUDA/torch 版本由远程构建决定（D11），磁盘/配额按实际。

### 12.3 下一步（待评审后）

1. 评审本文档（v0.2，已固化 D6–D11 与 §3.10）；
2. 在 `biocourse-glt` 上完成环境构建 + **M0 效率基准**（§7.9：copy/step/obs、
   8 座全搜索吞吐、成对矩阵成本、批量评估）；
3. 依据 M0 实测结果写开发计划（M1 Python 原型 → M2 Rust 搜索核 → M3 两阶段自对弈）；
4. 先跑 1k 局小规模验证“搜索确实提升策略”，再按效率曲线扩到 100k+。
