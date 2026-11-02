# 复利 BC 蒸馏（CompoundPolicy → 学生策略）

> 教师 `scripts/compound_script.py::CompoundPolicy`；学生 `entity` d128×2（**0.667M**）/ d384×8（**14.81M**，与
> s14 主策略同构）。代码 `scripts/train_compound_bc.py`·`eval_compound_bc.py`·`tests/test_compound_bc.py`·
> `runs/compound_bc/dagger_gen.py`；产物 `runs/compound_bc/**`。

## 1. 一句话现状

**「模型不买放大器」（0.375 张/局）已解决**：加权后学生买到 **5.8–9.6 张/局**（教师 6.74，现实收入档），三档收入
全过「放大器」判据。**Σ 与 r12 二选一**（解码温度，§6.1）：greedy 下 Σ p50 **1,646**（教师 96%）但 r12 1.20；
T=1 下 r12 1.51–1.60 但 Σ 1,273。⇒ **可进候选池，四判据仍只过 2 条**。

## 2. 数据与加载契约

| 文件 | 规模 | 用途 |
|---|---|---|
| `s0_fixed30` / `s1_growth_carrier` / `s3_growth_buff3`（+ 3 个 S3 变体） | 126/136/170 局，54k/61k/81k 决策 | 正式配置 / 混采备选 |
| **`s3_mix_roll8`** | **255 局 / 133,709 决策**（amp 10.64、t15 Σ p50 3,390） | **主（base）训练集** |

字段：`features`[N,3227] **float16**、`cards`[N,124] int16、`mask`[N,245] bool、`action`[N] uint8、
`turn/tier/gold/episode_id/action_kind/is_amp_buy`、`ep_*`（每局标签）、**`ep_split`（官方 10% val）**；
只保留 σ_t15 ≥ 1500 的局，`legal_rate = 1.000`。加载器五条硬契约（单测覆盖）：① 合并 3351 与
`features`+`cards` 两种布局都认、**合并布局拒收 float16**；② `features` 保持 float16（省 1.3GB）；③ **`ep_split`
优先**、按局切（按行切会让同局动作跨 train/val 泄漏）；④ 非法动作丢弃并计数；⑤ `path@frac` **按局**确定性
抽样（控制 DAgger : base 混比，不切碎局）。

## 3. 配方

```bash
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python; export PYTHONPATH=rust/python:.
$PY scripts/train_compound_bc.py --data data/scaling/compound_bc/s3_mix_roll8.npz --arch entity \
  --d-model 384 --n-layers 8 --epochs 10 --lr 3e-5 --batch-size 256 --holdout 0.05 --diag 1 \
  --action-weight-mode manual --action-weight-kinds buy_amp:8,buy_carrier:8,play_spell:8,upgrade:8 \
  --size-name main_w8e10
```

- 损失 = masked CE（教师数据无 soft → 硬标签）。**动作级重加权**是核心：四类只占决策 **1.9/1.8/18.7/1.1%**，
  不加权时 CE 被高频动作主导 → 放大器召回 56%；`×8` 后 **98.4%**，整局放大器 3.25→8.1 张/局。逐类系数写作
  `buy_amp:8,sell:3`；`--sigma-weight`（终局 Σ 加权）实测有害，默认 0。
- 保存 `ckpt_<size>.pt` + `meta_<size>.json`（n_train/n_val、CE、top1、**holdout 分层诊断**、数据 sha08）。

## 4. 评测协议

自建 rollout（不 import 会被并行修改的 `train_economy_sandbox.py`），24–48 局/配置；每条决策：引擎 mask
校验 →`Ledger` 按 A_BUY→商店槽记账（放大器/法术）→ 载体审计（目标选择命中载体 eid）。**两条硬要求**：
① `torch.manual_seed(seed0)` 必须显式播（否则 `multinomial` 走全局 RNG，同配置 Σ p50 能差 ±20%，实测
1160 vs 1429）；② 报告必须写清解码方式（`--sample 0` / `--temperature`）。

| 档位 | 经济 | 判据（`GATE_PROFILES`） |
|---|---|---|
| `fixed20`（**现实收入**，主判据） | fixed 20 金/回合 | amp ≥ **5.5**、Σ p50 ≥ **1,500**、r12 ≥ **1.55**、goldens 均值 ≥ **1.45** |
| `fixed30`（旧口径，对照） | fixed 30 金 | amp ≥ 5、Σ ≥ 3,000、r12 ≥ 2、goldens ≥ 1.45 |
| `growth3` / `growth2` | growth 0.15 + 2/载体（+buff×3） | amp ≥ 10、Σ ≥ 2,400、r12 ≥ 1.4 |

教师参考（`--teacher-ref` 逗号分隔、后者覆盖）：`runs/compound_script/groups.json`（28 局/组，未过滤）
+ `data/scaling/compound_bc/meta.json`（240 局/组 all_run）；现实档教师 roll8 基线 **Σ 1,716 / amp 6.74 /
r12 1.55** 写在 `TEACHER_STATIC["fixed20"]`。

## 5. 结果（**24 局/配置，seed 910000，已播 torch seed → 逐位复现**）

| ckpt（14.81M 除注明） | 数据 / 加权 | 解码 | fixed20 Σ | amp | r12 | goldens | fixed30 Σ | amp |
|---|---|---|---|---|---|---|---|---|
| **`main_w8e10`** | base / amp·carrier·spell·upgrade ×8 | T=1 | 1,273 | 5.79 | **1.51** | 1.33 | 1,271 | 5.67 |
| **`main_w8e10`** | 同上 | **greedy** | **1,646** | **8.33** | 1.20 | 1.17 | **1,782** | **9.62** |
| `mix_w8e10`（0.667M） | base / ×8 | T=1 | 1,416 | 5.67 | **1.60** | 0.67 | 1,186 | 7.25 |
| `nar_base_384x8` | base / **窄 amp×4,carrier×2** | T=1 | 991 | 5.04 | **1.63** | 1.17 | 1,236 | 5.29 |
| `nar_dagger13_384x8` | DAgger@0.33 + base / 窄 | T=1 | 1,017 | 5.71 | 1.33 | 0.88 | 1,638 | 7.00 |
| `dg1_384x8` | DAgger@1.0 + base / 宽+sell×3 | T=1 | 818 | 3.21 | 1.44 | 1.00 | 922 | 4.54 |

**结构性动作召回（holdout，判断「分布是否被稀释」的唯一依据）**：

| ckpt | amp | refresh | buy_minion | buy_spell | sell | end_turn | play_minion | val CE / top1 |
|---|---|---|---|---|---|---|---|---|
| `main_w8e10`（宽×8, base） | 98.4% | 86% | 54% | 87% | 54% | 16% | 77% | 0.647 / 79.0% |
| `nar_base_384x8`（窄, base） | 96.5% | 92% | 64% | 90% | 55% | 19% | 92% | **0.566 / 82.1%** |
| `nar_dagger13_384x8`（窄, DAgger 1:3） | **98.4%** | **93%** | **70%** | **91%** | 53% | 25% | 90% | **0.564 / 82.0%** |
| `dg1_384x8`（宽+sell/end×3, DAgger 1:1） | 98.5% | **61%** | 47% | 81% | **62%** | **46%** | 71% | 0.762 / 74.5% |

**判据（realistic = fixed20，教师 1716/6.74/1.55）**：`main_w8e10` greedy → amp ✅ Σ ✅ r12 ❌ goldens ❌（2/4）；`mix_w8e10` T=1 → amp ✅ Σ ❌ r12 ✅ goldens ❌（2/4）；`main_w8e10` T=1 → 1/4 —— **没有单一配置同时过四条**。## 6. 诊断：保真度、Σ、r12 三者不同向

1. **DAgger 是负结果**（两种混比都试了）：1:1 + 宽加权 → fixed20 Σ **818**（base 1,273，−36%）；1:3 + 窄加权 → **1,017**（−20%）。它唯一确定的好处是 `sell` 53–62% / `end_turn` 25–46%（base 16%，即收尾动作覆盖），代价是 `refresh` 86→61%；两个尺寸（0.667M/14.81M）都退。
2. **保真度最高 ≠ Σ 最高**：`nar_dagger13` 单步指标全面最好（CE 0.564、top1 82.0%、refresh 93%、buy_minion
   70%）fixed20 Σ 只有 **1,017**；`main_w8e10`（CE 0.647、refresh 86%）却有 **1,273**。⇒ CE 只度量「在已到达的
   状态上抄得像不像」，不度量「到达什么状态」；长程状态分布才是 Σ 的瓶颈。
3. **宽加权优于窄加权**（Σ 1,273 vs 991）：放大器+载体+法术+升级一起抬，复利链才在整局尺度兑现。

## 6.1 解码温度是一阶开关（部署口径必须写清）

同 `ckpt_main_w8e10`：**T=1** → Σ 1,273 / r12 1.51 / amp 5.79；**T=0.5** → 1,208 / 1.34 / 6.58；**greedy** →
**1,646 / 1.20 / 8.33**（fixed30 更明显：1,271 → **1,782**）。规律：**降温 → Σ/amp 升、r12 降**（greedy 把 t12
也抬高）。BC 策略熵高于教师（CE 不压熵），T=1 的采样噪声每步累积 ⇒ **部署建议 greedy 或 T≤0.5**，别沿用 PPO
时代的 T=1 口径。

## 7. 结论

1. **放大器：达标**（T=1 5.79 / greedy 8.33，教师 6.74；相对现状 0.375 → **15–22×**）。
2. **Σ：greedy 达标**（1,646 ≥ 1,500，教师 96%），T=1 只有 1,273（85%）。**r12：T=1 接近**（1.51–1.60 vs 判据
   1.55、教师 1.55），greedy 掉到 1.20。**goldens 未达标**（1.17–1.42 vs 1.45，教师自己 1.4–1.5）。
3. **DAgger 关闭**：「状态分布漂移」假设**未被验证**——单步保真度提升后 Σ 反而下降（§6.2），瓶颈不在数据
   分布而在目标函数（CE 不优化 Σ）。部署一律记录解码方式，否则同一 ckpt 的 Σ 能差 29%。

## 8. 下一步（进主策略的条件）

1. **换目标函数，不是换数据**：BC 权重当 **PPO 初始化 + KL 锚**（s14 配方里 `--anchor-beta` 的角色），用
   1–2M decisions 在沙盒里把 Σ 推上去；BC 只负责「别退回 0.375 张放大器」。
2. **goldens**：判据改「≥ 教师水平 1.45」，并单独统计三连（买第三张）召回——本次没测。继续 BC 线的前提是
   **先证明 r12 与 Σ 可以同向**（当前证据反向，§6.1）；进主策略硬条件仍是四判据 + human 面板 Δ ≤ −0.10。

## 9. BC→PPO 微调（task-10）：**负结果，已停**
实现 `scripts/train_compound_ppo.py`（自建，不改别人的训练脚本）：冻结 BC 当参考策略 + **精确 full-KL
anchor**（`β=0.1` 前 200 次更新 → `0.02`）、梯度累积（`minibatch 1024 × grad_accum 8`）、GAE(γ1/λ0.95)、
**无熵奖励**（BC 熵已偏高，§6.1）、`lr 3e-6`、`target_kl 0.02` 早停。起点 `ckpt_main_w8e10`，fixed20。

**实现踩坑（重要）**：实体模型有 `dropout=0.1`，采集与更新必须**同一 eval 模式**——否则同一批观测的
logits 会变，`approx_kl` 假性 0.1–0.3，每批都被 KL 早停打成「只做 1 个 minibatch」。修好后 KL ≈ 1e-5。

| 起点 / 快照 | greedy：Σ / amp / r12 / goldens | T=1：Σ / amp / r12 |
|---|---|---|
| BC 起点 `main_w8e10`（24 局） | **1,646 / 8.33 / 1.20 / 1.17** | **1,273 / 5.79 / 1.51** |
| PPO 261k（16 局） | 1,025 / 6.88 / 1.30 / 1.06 | 1,250 / 5.12 / 1.54 |
| PPO 505k（16 局） | **273** / 4.75 / 1.74 / 0.31 | **276** / 2.38 / 1.35 |

`anchor_kl` 从 2e-4 涨到 **0.77**（β=0.02 挡不住漂移），entropy 1.03→0.87，`ep_sigma_p50` 训练侧从 1,131
跌到 280。**Σ 单调退化 → 按停止规则在 669k 杀掉并回退 BC 权重**；0.667M 臂未跑（同配方、更小容量、
无信息增益）。混合 BC 臂（`s20_spellspam : s3_mix_roll8 = 1:1` + 窄加权）三温度 amp 3.62–5.21 < 5，
按规则回退纯 `s3_mix_roll8` 版。⇒ **在无对战沙盒里，PPO 即使从 BC 起点 + KL anchor 也会退化**，
与 `docs/ECONOMY_SANDBOX.md` §9 的六条臂一致：瓶颈是**信用分配**，不是初始化或数据。

## 9.1 奖励设计 + 退化诊断（task-11）：**元凶是 value 头没训过，不是奖励尺度**

**诊断（`runs/compound_bc/ppo/diag_reward_scale.json`，BC 起点 24 局，fixed20，T=1）**：
整局 return ∈ **[0.574, 0.762]**（p50 0.693，望远镜校验通过）；tanh value 头范围 ±1 ⇒ **没有溢出/饱和**。
但 BC 训练没训 value ⇒ V ∈ **[-0.985, +0.976]**、|V| 均值 0.49（真实 ≈0.69），于是 GAE 的 advantage
**std 0.31（真实跨局差异只有 0.05）、符号一致率 52.8%、与真实优势相关 0.555** ⇒ 策略梯度≈随机游走。

**两处修复（`scripts/train_compound_ppo.py`）**：① `--value-warmup 100` **只训 `value_head`**（entity 的
value 头与策略共享 trunk，整网回传会把策略推歪——踩过 anchor_kl 首行 0.205、130k 后 Σ 1646→524；
修好后自检 `Δlogp=0.000000`、|V−return| 0.5→**0.061**）；② **β 固定 0.1 不衰减** + `--stop-if-sigma-below`。

| telescope（dense_dlog ≡ γ1 pbrs） | greedy：Σ / amp / r12 / goldens | T=0.5 | T=1 |
|---|---|---|---|
| BC 起点 | 1,646 / 8.33 / 1.20 / 1.17 | 1,208 / 6.58 / 1.34 | 1,273 / 5.79 / 1.51 |
| **PPO 163k** | 1,618 / **8.62** / 1.25 / **1.54** | – | – |
| **PPO 310k（最佳）** | **1,676** / 6.21 / **1.63** / 1.33 | 1,293 / 5.04 / 1.56 | 812 / 4.33 / 1.51 |
| PPO 再续 212k | 950 / 4.00 / 1.56 / 0.75 | – | 564 / 3.62 / 1.66 |

**训练曲线**（310k 那次）：`ep_sigma_p50` 996→1120→1044（**不再崩**，旧配方同预算是 1131→305）；
entropy **1.03（BC）→0.757（16k）→0.62–0.76**（策略被锐化）；`anchor_kl` 2e-4→0.117（缓漂）。
**amp 随迭代下降**（163k 8.62 → 310k 6.21，−28%）而 **r12 上升**（1.25→1.63，+30%）⇒ 这不是「丢掉放大器」，
而是**用「买得少一点、形状更好」换了 Σ/形状**（goldens 1.54→1.33 同步回落）。锐化的副作用是 **T=1 掉到
812**（greedy 反而更强）：**部署必须用 greedy/低温**。再往后加预算会退化（+212k → Σ 950），已早停。
判据：Σ 1,676 < 1,800（差 7%）、r12 1.63 ✅、amp 6.21 ✅ = **2/3**，是本路线最接近达标的一次。

**四个奖励变体**（都从 `ckpt_main_w8e10`、fixed20、lr 3e-6、value-warmup 100、β≡0.1；greedy / T=1）：

| 变体（预算） | greedy：Σ / amp / r12 / goldens | T=1：Σ / amp / r12 |
|---|---|---|
| **telescope（dense_dlog，310k）** | **1,676 / 6.21 / 1.63 / 1.33** | 812 / 4.33 / 1.51 |
| pbrs99（γ=0.99，310k） | 1,568 / 6.88 / 1.33 / 1.38 | 942 / 4.29 / 1.22 |
| convexity（212k） | 1,410 / 6.17 / 1.26 / 1.12 | 911 / 4.00 / 1.45 |
| mix（212k） | 1,116 / **7.00** / 1.03 / 1.04 | 982 / 4.50 / 1.43 |
| （BC 起点，对照） | 1,646 / 8.33 / 1.20 / 1.17 | 1,273 / 5.79 / 1.51 |

⇒ **最密的奖励（telescope = 每回合 ΔlogΣ）最好**：它唯一把 r12 从 1.20 抬到 **1.63**；`convexity`/`mix`
的终局凸性项只奖励「已经复利」的局，稀疏且与 Σ 冲突（mix 虽然 amp 7.00 最高，但 r12 掉到 1.03）。

## 10. 复现

```bash
$PY -m pytest tests/test_compound_bc.py -q     # 35 passed / 1 skipped（smoke 需 COMPOUND_BC_SLOW=1）
bash runs/compound_bc/run_narrow.sh base 1 384 8 10      # 窄加权对照
bash runs/compound_bc/scan_temp.sh runs/compound_bc/ckpt_main_w8e10.pt 24   # 温度扫描
bash runs/compound_bc/run_eval_final.sh 24               # 定稿表（已播 seed，逐位复现）
bash runs/compound_bc/run_eval3.sh runs/compound_bc/ckpt_main_w8e10.pt 24  # 三温度（task-10 口径）
```

产物：`ckpt_{main_w8e10,mix_w8e10,nar_base_384x8,nar_dagger13_384x8,dg1_384x8,...}.pt`、`meta_*.json`、
`eval_*.json/.md`、`dagger/r1.npz`(+meta)、`data_manifest.txt`、`compare.py`（对照表）。
