# 纯经济沙盒（Economy Sandbox）：先学会「金币→缩放」，再回完整游戏

> 问题：完整游戏里**终局名次对施法缩放没有梯度**（`docs/SCALING_SIGNAL.md`：控制存活后
> r≈0），而人类强度 99% 来自缩放（`runs/ceiling_probe/REPORT.md`：tier6 静态上界
> t12 Σ=294，真实 t12 p50=4458 = 6.6×上界）。所以先做一个**无对手、无战斗、无血量、
> 无排名**的简化 MDP，只练「用金币做缩放」，再测量它能把 t12/t15 战团推到多强。

| 文件 | 作用 |
|---|---|
| `hsbg/az/train/economy_sandbox.py` | 沙盒环境（单环境 + 向量化）、奖励口径、度量、基线策略、CLI |
| `scripts/train_economy_sandbox.py` | 沙盒 PPO（可选 teacher BC 热身）训练入口 |
| `tests/test_economy_sandbox.py` | 12 项契约测试（编码/终止/奖励/确定性/向量环境/观测解码） |
| `runs/economy_sandbox/` | 所有实验产物（`history.jsonl` / `train.log` / checkpoint / 迁移评测） |

**结论先行**（详见 §5）：

1. 沙盒**实现成功、且是忠实的测量代理**：s14 权重在沙盒里 t12 Σ p50=662，在完整游戏里
   566 —— 同一量级；引擎 step 只有 **~0.02 ms**，一局 15 回合 **~22 ms**，无战斗、无淘汰、
   无排名，编码与训练完全一致。
2. 沙盒自己的**上界测量**很有信息量：∞金币 + 专门的施法缩放脚本只能到 **t12 1170
   （26% 真实）**；s14 已经 662（15%）。**"缺金币"不是唯一瓶颈**——40 动作/回合、
   7 格酒馆、共享池、以及"没有免费 tier6"共同卡住了上限（ceiling_probe 的 1843
   依赖免费 tier6 + 120 动作）。
3. **训练（40 分钟 / 每条臂 25–73 万决策）没有超过 s14 起点**：最稳的一条
   （`board_delta` + lr 3e-6，727k 决策）在噪声内持平（最好点 250k：t12 606→638、
   greedy 684→748）；所有 lr ≥1.5e-5 的臂都**退化或崩溃**。
   ⇒ 沙盒**值得作为 s17 第一阶段的环境**，但**2–5M 决策 / 30–60 分钟这个预算不够**
   （见 §5.4 的量化依据与 §7 的替代路线）。
4. **迁移无增益**：直接放进完整游戏（5 席人类战团 p=0.9），t12 Σ p50 **471 vs s14 的 457**
   （+3%，噪声内），名次 5.73 vs 5.56；纯 bot 局 508 vs 624（-19%）。与"沙盒里也没提升"
   一致。

---

## 1. 沙盒定义

### 1.1 状态 / 动作（与正常训练**同一套编码**，便于策略迁移）

- 观测：`hsbg.az.env_api.observe(g, 0)` → `hsbg.env.obs_std` 的 **3227 floats + 124 cards**
  （`observe` 7 µs、`legal_mask` 1 µs，比 `view()` JSON 便宜 60×）；
- 动作：**245** 与 mask 完全一致；recruit 阶段全部合法动作（买 / 卖 / roll / 升级 /
  施法 / 冻结 / 换位 / 英雄技能 / 黑暗赠礼 / 饰品与发现的选择）；
- 每回合动作上限 `--action-cap`（默认 **40**，与 s16 训练的 `--max-actions-per-turn 40`
  同口径），由引擎 `RulesConfig::turn_action_caps` 强制（超限后只剩 `EndTurn` +
  pending 选择），**不是 Python 侧截断**；
- 单 learner 座位 seat 0；其余 7 席只占位（见 §1.3）。英雄选择用"第一个合法选项"
  （不做英雄决策，英雄差异进噪声）。

### 1.2 奖励（不是名次）

`L_t = log1p(Σ_t 战团 atk+hp) / log1p(strength_ref)`，`strength_ref=30000`
（真实 t15 p50=26516 → L=0.89；value 头 `tanh` 的量级刚好）。

| `--sandbox-reward` | 定义 | 说明 |
|---|---|---|
| `log_strength`（默认） | 回合结束 `r_t = L_t - L_{t-1}` | 望远镜求和 = `L_T`，期末强度口径 |
| `auc_strength` | `r_t = L_t` | 鼓励"早强" |
| `final_strength` | 只有 `t=T` 给 `r_T = L_T` | 纯终局，最难学 |
| `board_delta` | **逐决策** `r = L(Σ_i) - L(Σ_{i-1})` | 同一 potential 的密集版本（整局求和仍 = `L_T`），只改信用分配、不改最优策略 |

`--sandbox-reward-mix "tier:0.1,carrier:0.2,tavern:0.05,spells:0.05,gold:0.02"`
在每回合奖励上再加 tier / 载体数 / 酒馆永久 buff / 施法数 / 未花金币项（默认空）。
**实测这条混合项有害**（§5.3 `g10_mix`：策略去刷 tier 与载体，t12 掉到 214）。

### 1.3 如何跳过战斗与伤害（**不改 Rust**，只用 `RulesConfig` + 现有 API）

1. **伤害恒为 0**：`damage_caps=[[1,0]]` + `damage_cap_until_alive=0`。
   引擎 `apply_combat_result` 里 `dmg = out.damage.min(cap) = min(x,0) = 0`，
   所以**任何座位都不掉血**，永不淘汰、永无名次。
2. **回合推进走引擎原生路径**：其余 7 席在每回合开始被立刻 `EndTurn`（空战团，
   每席 1 次 `step`；遇到饰品/发现 pending 用第一个合法动作消化）。于是
   「所有活着的座位都已结束回合」→ 引擎 `combat_round()` → `start_turn()`，
   直接进入下一回合的 recruit。战斗仍会跑（空战团对空战团/我方战团，1 次攻击结束），
   但它**不改变任何状态**。
3. **终止**：`max_turns=turns`（默认 15）。第 15 回合战斗后引擎自己
   `finish_by_health()` → `Phase::GameOver`，不会跑到第 16 回合。
4. **每回合开始回满血**：一次 `debug({"cmd":"set_player","p":0,"gold":N,"health":30})`
   （`Game.debug` 是现成 API）。池里有以生命值支付的牌（`costs_health`），seat 0 一旦
   血到 0 会被淘汰；而其余 7 席此刻都已 EndTurn，引擎会认为"全员结束"→ 立刻打完
   本轮 → 跳到 GameOver（实测 25k 局偶发一次，表现为 `非法动作 ... game over`）。
   血量在沙盒里没有意义（伤害恒为 0），直接回满。

成本：一局 = **170–300 次 `step`**（其中 105 次是 7 席 × 15 回合的 `EndTurn`），
**~22 ms/局**（不含网络前向）。

### 1.4 每回合输出

`episode_summary()` / `_measure()`（一次 `view(0)`，0.45 ms/回合）：

| 字段 | 含义 |
|---|---|
| `sigma` | 战团 Σ(atk+hp)（与真实库同口径：recruit 阶段结束） |
| `tier` | 酒馆等级（另给 `tier_hist`） |
| `carriers` | 场上**缩放载体**数（`data/scaling/carriers.json` 的 `primary_ids`，22 个 id） |
| `spells` | 已施放法术数（`stats.spells_cast`） |
| `tavern_buff` | **酒馆永久 buff 总量** = `stats.tavern_atk + stats.tavern_hp`（Devilish Distractor 那条"本局酒馆随从 +1/+2"的累计） |
| `gold` / `board_len` / `hand_len` | 经济与站位 |

CLI 直接打印逐回合表：

```bash
python -m hsbg.az.train.economy_sandbox --policy teacher --games 32 --gold-per-turn 10
# turn  Σ     tier carriers spells tavern_buff gold
#    1    12     1       0      0          0    1
#  ...
```

---

## 2. 沙盒基线（32 局，`--gold-per-turn 10`，40 动作上限，15 回合）

| 策略 | t12 Σ p50 | t12 p90 | t15 Σ p50 | tier p50 | 载体率 | 施法数 | 酒馆 buff |
|---|---:|---:|---:|---:|---:|---:|---:|
| `end`（什么都不做） | 0 | 0 | 0 | 1 | 0.00 | 0 | 0 |
| `random` | 36 | 112 | 52 | 4 | 0.06 | 12 | 0 |
| `carrier_teacher`（`scripts/carrier_teacher.py`） | 290 | 610 | 398 | 5 | **0.78** | 28 | 0 |
| `spell` 脚本（`scripts/engine_ceiling_probe.py`） | 328 | 602 | 517 | 6 | 0.12 | 45 | 4 |
| `spell` @15 金币/回合 | 554 | 1019 | 756 | 6 | 0.28 | 68 | 4 |
| `spell` @20 金币/回合 | 678 | 1480 | 758 | 6 | 0.34 | 67 | 4 |
| `spell` @99 金币/回合（∞经济） | **1170** | **2746** | **1212** | 6 | 0.28 | 74 | 8 |
| **s14 权重（训练起点，T=1 采样）** | **662** | – | **921** | 5 | 0.22 | 38 | 0 |

读法：

- 沙盒**复现了完整游戏里的策略排序**：只买身材 ≪ 载体教师 < s14 < ∞金币缩放脚本。
- s14 的沙盒 t12（662，32 局；24 局评测 562–606）与它**在完整游戏里的 566 同量级**
  —— 说明沙盒是"强度"的忠实代理，不是另一个游戏。
- **∞金币的施法脚本只有 1170（真实 4458 的 26%）**，而 ceiling_probe 里同样的脚本
  在完整游戏里能到 1843；差别是那个数字**同时**带了免费 tier6（`upgrade_cost=0`，
  开局 tier6）与 120 动作。动作上限本身不是全部原因（`--action-cap 40/80/120`
  在沙盒里给 998/1108/687，脚本自己也有 40 次刷新上限），**关键是拿不到 tier5/6 的
  载体与 6 格酒馆**。

---

## 3. 训练配置

```bash
# 主实验（最好的一条）
OUT=runs/economy_sandbox/g10_dd3 \
python scripts/train_economy_sandbox.py \
  --checkpoint runs/az_entity_s14/model.pt --device cuda:7 \
  --decisions 2000000 --envs 96 --batch-decisions 8192 \
  --minibatch 512 --epochs 1 --lr 3e-6 --entropy-coef 0.004 --target-kl 0.05 \
  --sandbox-reward board_delta --gold-per-turn 10 --turns 15 --action-cap 40 \
  --eval-every 250000 --eval-games 40 --save-every 250000
```

- **采样 + 学习同进程 lockstep**：96 局并行，每步把所有 active 局的观测叠成一个 batch
  做一次 GPU 前向（B=512 时 ~57 µs/决策），再逐局 `engine.step`。
  实测 **~2500 沙盒决策/秒**（单卡 cuda:7，含 PPO 更新）。
- 复用现有基础设施：`hsbg/az/train/ppo_trainer.PPOTrainer` + `PPOConfig` +
  `ppo.compute_gae`；`value_loss="mse"` + `value_head_coef=1.0`
  （默认 `value_loss="rank"` 是名次头，沙盒没有名次）。`pi_coef=0`、`bc_coef=0`、
  `dpo_coef=0`（不需要 MCTS π / 人类 BC / DPO）。
- `amp=off`（见 §6.2）。
- 更新粒度：`batch_decisions=8192` → 每次 update **2 个有效 minibatch**
  （`512×9`），第二个受 KL 早停保护。
- 可选的 teacher BC 热身：`--bc-decisions 20000 --bc-teacher teacher --bc-epochs 2`
  （实测没有采用：脚本教师在沙盒里只有 290，BC 它是**降级**，见 §5.4）。

---

## 4. 迁移验证（完整游戏）

```bash
PYTHONPATH=rust/python:. python scripts/quality_monitor.py \
  --checkpoint runs/economy_sandbox/g10_dd3/model.pt --device cuda:7 --games 48 \
  --human-boards data/real_library/library_real_quasi_full.jsonl \
  --human-board-p 0.9 --human-board-seats 5 --human-board-fidelity full \
  --out runs/economy_sandbox/migrate/quality_sb_5h.json
```

两种设置都跑（基线 s14 同样跑一遍，只比较**强度**是否迁移）：

| 设置 | 权重 | games | mean_rank | top4 | win | death_turn_p50 | survive@t12 | **t12 Σ p50** | tier@t12 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 席人类战团 p=0.9 | s14 | 48 | 5.56 | 0.21 | 0.00 | 11 | 0.25 | **457** | 3 |
| 5 席人类战团 p=0.9 | 沙盒 dd3 | 48 | 5.73 | 0.25 | 0.00 | 11 | 0.21 | **471** | 3 |
| 7 引擎 bot | s14 | 32 | 1.69 | 1.00 | 0.53 | 14 | 0.97 | **624** | 4 |
| 7 引擎 bot | 沙盒 dd3 | 32 | 2.19 | 0.94 | 0.34 | 14 | 0.97 | **508** | 4 |

- **强度基本没迁移**：难设置 +3%（471 vs 457，噪声内，名次略差）；纯 bot 局 −19%。
  与"沙盒里也没提升"完全一致 —— 沙盒是代理，不会凭空产生能力。
- 参考：`strength_ratio_t12`（对真实 p50=4458）= 0.103 / 0.106；5 席人类战团下
  学习者 **p50 在第 11 回合就死了**（survive@t12 只有 21–25%），所以 t12 强度是在
  "活着的人"里算的 —— 这也是为什么 t12 只有 457 而不是 600+。

---

## 5. 训练结果

### 5.1 六条臂（都在 s14 上微调；`--gold-per-turn 10`）

| run | 奖励 | lr | 决策 | 沙盒评测（同 run 内同 seed 序列） | 判定 |
|---|---|---|---:|---|---|
| `g10_lr5e5` | `log_strength` | 5e-5 | 300k | greedy t12 **630 → 39** | **崩**（argmax 退化成"一直 EndTurn"） |
| `g10_v2` | `log_strength` | 1.5e-5 | 300k | sample 562→478 / 868→646 | 略降（稳定不崩） |
| `g10_dd` | `board_delta` | 1.5e-5 | 300k | sample 672→524 / 954→742；greedy 630→640 / 856→**968** | 噪声内持平 |
| `g10_dd2` | `board_delta` | 3e-5 | 250k | sample 756→**340** / 1030→382 | **崩** |
| `g10_mix` | `log_strength` + tier/carrier/spell 混合 | 3e-5 | 250k | sample 552→**250** / 888→302（tier 冲到 6、载体 0.53） | **崩**（刷 shaping 项） |
| **`g10_dd3`** | `board_delta` | **3e-6** | **727k** | 0: 606/880 → 250k: **638**/866（greedy 684/860 → **748**/886）→ 500k: 592/718 | 稳定，最好点 +5%/+1%，整体噪声内持平 |

### 5.2 统一复评（同一 eval seed 910000，32 局，s14 vs 各 checkpoint）

| checkpoint | t12 sample | t15 sample | t12 greedy | t15 greedy |
|---|---:|---:|---:|---:|
| s14（起点） | **662** | **921** | **668** | **997** |
| `dd`/300k | 556 | 731 | 587 | 741 |
| `mix`/250k | 214 | 225 | 207 | 236 |
| `dd3`/250k | 614 | 901 | 531 | 734 |
| `dd3`/500k | 528 | 708 | 590 | 789 |
| `dd3`/680k | 614 | 851 | 590 | 789 |

**没有任何沙盒 checkpoint 超过 s14 起点**；`dd3` 是最接近的（低 lr + 密集奖励 → 不崩）。

### 5.3 训练曲线（每局回报 / 沙盒评测 vs 预算）

`dd3`（唯一稳定的臂）：

```
decisions   t12 Σ p50(sample)   t15 Σ p50(sample)   每局回报 L_T
0                 606                880             0.642
250k              638                866             0.676
500k              592                718             0.650
727k              –                  –               0.677   (greedy t12 590 / t15 789)
```

s14 起点在同一序列里是 606/880、`L_T≈0.64`。**曲线是平的**：`L_T` 在 0.64–0.70 之间
抖动，评测 p50 在 ±10% 内噪声。这与 §6 的原因分析一致。

### 5.4 为什么学不动（量化依据）

1. **lr 窗口极窄**：s14 自己的训练用 `lr=1.2e-6`（4241 次 update）。沙盒里
   lr ≥1.5e-5 时 25 万决策内就退化/崩溃（§5.1），lr 3e-6 稳定但 70 万决策仍是平的。
   → 要看到明确提升，粗估需要 **2–5×10⁷ 决策**量级（按 2500 决策/秒 ≈ 2–6 小时/臂），
   而不是任务设想的 2–5×10⁶（25–35 分钟）。
2. **信用分配**：奖励在时间上稀疏（`log_strength` 每回合只有一个非零），
   而一条 episode 有 ~200 个决策、15 个奖励；λ=0.95 只能跨一回合，跨回合完全靠
   value 头。`value_loss` 一直在 0.17–0.27（对 [0,1] 的回报 = 明显欠拟合）。
   改成逐决策 `board_delta` 后 value 头好一些（0.10–0.17）、KL 更小（0.002），
   但提升仍被 lr 上限卡住。
3. **探索**：要超过 s14 必须发现"多回合复利"链条（买载体 → 反复施法 → 买被永久
   buff 的酒馆随从）。单条 episode 的动作空间是 245²⁰⁰ 量级；PPO 的 on-policy
   梯度在没有好的 value 时几乎指不到这条链。**shaping 混合项不是解**：它让策略直接
   去刷 shaping（tier 6 / 载体 0.53）而强度掉到 214。
4. **教师不够强**：`carrier_teacher` 在沙盒里 290、`spell` 脚本 328，都远低于 s14
   的 662 → BC 这些教师是**降级**。要 BC 得先造一个 ∞金币 + 免费 tier6 档（~1843）
   的教师，而它在沙盒里（无免费 tier6）也只有 1170。

---

## 6. 调试记录（留档，避免重复踩坑）

1. **`amp=bf16` 会让 PPO 完全失效**：采集 fp32、训练 bf16 时同一个动作的
   `logprob` 差 **0.44 nats（max 2.2）** → `ratio` 起点就不是 1 → `approx_kl≈0.3`
   → KL 早停把**每次更新都跳过**，策略一动不动。实测对比脚本见提交说明。
2. **`minibatch=2048` 在 24 GB 卡上 OOM**：entity 8 层 × 49 token，
   2048 行时激活 ~10 GB。改 `512 × grad_accum`（峰值 ~3 GB）。
3. **`grad_accum` 与 `batch_decisions` 必须整除（或让有效 minibatch 覆盖整批）**：
   否则每个 update 只剩一个"残余组"，它在**一次 Adam step 之后**才评估 → KL 必超阈值
   → 早停 → 整次更新被丢弃。第一版 (`gen 2`) 就是这个原因。
4. **`lr` 是第一序参数**，比奖励形状、熵系数重要得多（§5.1）。
5. **指标陷阱**：逐决策平均回报 `ret_mean` 会被"回合内动作数变少"抬高
   （终止奖励摊到更少的步上），不能当进度看；必须看**每局**的 `L_T`
   （`ep_return_mean`）或评测 t12/t15 Σ。
6. **argmax 退化**：245 维策略天然接近确定性，greedy 评测会比 T=1 采样更早崩
   （`g10_lr5e5`：采样还能拿 ~600，greedy 掉到 39）。完整游戏的对手也是**采样**
   运行的（`PPOSelfPlayPolicy` + `CollectConfig.temperature`），所以迁移以
   `sample` 为主、`greedy` 只作诊断。

---

## 7. 局限

- **无对手 = 过度乐观**：不掉血、不淘汰，"活到 t15"免费。真实对局里 t12 之后能不能
  活下来是另一个问题（§4：5 席人类战团下 p50 第 11 回合就死）。
- **金币固定 = 与真实经济不同**：`--gold-per-turn 10` 把 3→10 的递增曲线换成每回合
  10，且 `set` 模式**抹平跨回合攒钱**（`--gold-mode add` 可保留曲线）。
- **7 席空转**：其余座位的酒馆照常刷新并占着共享池的牌（与真实 8 人局一样），
  但**永远不买** → 池子比真实对局更容易抽到好牌（偏乐观，但所有策略一致）。
- **英雄固定**为第一个合法选项，英雄差异进噪声。
- **15 回合硬上限**，学不到终局冲刺；**40 动作/回合**低于人类有效操作数上限。
- 沙盒只测"能滚多大"，**不含战斗**——关键词（圣盾/复生/风怒）与阵型的价值完全没进来，
  所以沙盒强的战团不一定打仗强（这也是为什么迁移只看强度、不看名次）。
- `board_delta` 的 Σ 从观测解码（atk/hp 已 /10），与 `view()` 的精确 Σ 差 ≤1（有测试）。

---

## 8. 下一步（沙盒 → 完整游戏的课程衔接）

1. **预算与 lr 先对齐**：s17 第一阶段若用这个沙盒，预算要 ≥ **2–5×10⁷ 决策**
   （≈2–6 小时/臂），lr ∈ [1e-6, 3e-6]；`--decisions 20000000 --lr 2e-6`。
2. **换小模型做沙盒阶段**：沙盒的观测/动作与完整游戏一致，但**不需要 16M 参数的
   实体 transformer**。用 `--arch tiny --d-model 256`（~1M 参数，前向快 10×）先把
   "金币→载体→施法→复利"学出来，再**蒸馏**回 entity（`scripts/bc_pretrain.py` 路径）。
3. **金币课程**：`--gold-per-turn 99 → 20 → 10`（或 `--gold-mode add`）分阶段收紧，
   让策略在宽经济下先学会链条，再压到真实节奏。
4. **奖励衔接**：完整游戏里把 `L_t` 当**过程奖励**（`--shaping-coef` 或
   `--process-value-coef`），名次奖励保留但降权；否则终局名次会把策略拉回
   "买身材"的吸收态。
5. **对手课程**：`--human-board-seats 0 → 1 → 3 → 5`、`--human-board-p 0 → 0.3 → 0.9`，
   让"活到 t15"逐步变难（沙盒本身始终 0 席）。
6. **教师**：先造 1843 档（∞金币 + 免费 tier6 + 120 动作）的沙盒教师，用它做 BC/DAgger
   冷启动——但要**把免费 tier6 一起带进沙盒**（加一个 `--tier6-start` 选项），
   否则教师在被评估的环境里也只有 1170。
7. **判据**：以"沙盒 t12 Σ p50 ≥ 2000（真实 4458 的 45%）"作为进入完整游戏阶段的门槛，
   因为沙盒与完整游戏的 s14 读数已经对齐（662 vs 566）。

---

## 9. 规模化训练（2026-10-31 夜）：配方修正 + 金币课程 + 小模型

§6 把「学不动」归到四条原因上。这一节是**按这四条把配方修好、再把预算放大到 10⁷** 的
实验记录。结论先行：

1. **配方四条全部修好并验证**（§9.1）：采集/训练同一 dtype + 启动 logprob 自检
   （`max|Δlogp|=0`）、`batch_decisions` 必须是 `minibatch×grad_accum` 的整数倍（启动断言
   + 余数结转，**0 次 update 被丢弃**）、默认 lr 3e-6 / minibatch 1024 / grad_accum 8、
   按每局 `L_T` 记进度。吞吐达标：**小模型 3988–4216 决策/秒**（目标 ≥2000）。
2. **仍然没学上去，而且在部署金币下是负的**：主臂（s14 起点 + 12M 预算 + 金币课程）在
   gold 30 上 +7%（噪声内），在 gold 15 上 −33%、gold 10 上 **−60%**（635→542→308）。
   控制臂（无课程、gold=10、lr 1e-5）同样从 626 掉到 485。**gate 2000 / 1200 / 800
   全部未达**（训练后最好 542）。
3. **失败原因不再是管道**（§9.6）：KL 0.0002–0.003（远低于 0.05）、value_loss 0.02–0.03、
   策略确实在动（`KL(s14‖step2M)=0.47 nat`、top1 一致 66%）——但熵在升、`L_T` 在降。
   它学会了「对载体施法」（0.8→2.4 次/局），却丢了 tier/载体在场率（0.38→0.16），Σ 净降。
   **金币课程每下台阶塌 ~50%**（30→15：1158→614；15→10：601→222），lr 3e-6 的恢复只有
   ~+20 Σ/1M ⇒ 这套课程要成立每档需要 5–10M 决策。
4. **沙盒仍然是忠实的代理**（§9.7）：沙盒 −15% 的退化在完整游戏里是 −10%（t12 Σ
   457→412；1 席 p0.3：608→571），方向与量级都对得上。
⇒ **不建议**把沙盒 PPO 作为 s17 第一阶段（§9.8）；下一步优先「搜索标签」，而不是继续
堆 PPO 预算。

### 9.1 配方修正（已落地，`scripts/train_economy_sandbox.py`）

| # | 问题（§6） | 修正 | 验证 |
|---|---|---|---|
| 1 | 采集 fp32 / 训练 bf16 → logprob 不一致 → KL 早停 | `--dtype fp32\|bf16`：**采集也开同一 autocast**；启动时用真实观测跑一次「采集路径 vs 训练路径」logprob 自检，超容差直接 `AssertionError` | `max|Δlogp|=0.000e+00`（fp32 与 bf16 各自） |
| 2 | `grad_accum` 与 batch 不整除 → 残余组 → 整次更新被丢弃 | `--batch-decisions` 必须是 `minibatch×grad_accum` 的整数倍（**启动断言**并给出建议值）；采样侧把已完成轨迹**裁到整数倍、余数结转**到下一次更新（不丢样本、无残余组） | 断言实测（3000 对 1024 → 报错建议 3072）；主臂跑到 6.6M（**400 次 update**），**0 次 `update_failed`** |
| 3 | lr 过高退化 | 默认 `--lr 3e-6`、`--minibatch 1024`、`--grad-accum 8`（有效 8192）、`--batch-decisions 16384`、`--epochs 1` | `approx_kl` 0.0002–0.003（target 0.05），**无 KL 早停** |
| 4 | 用逐决策均值当进度 | 每局 `L_T`（奖励望远镜求和 = 终局强度）：`ep_LT_mean/p50/p90/max/last10` | 与评测 Σ₁₅ 的 L 口径一致（§9.4 曲线） |
| 5 | 金币固定 | `--sandbox-gold-ramp "0:99,1M:30,3M:15,5M:10"`（按累计决策数切档，逐局生效） | §9.4 |
| 6 | 免费 tier6 开不了 | `--sandbox-free-tier6 1`（`upgrade_costs=[0]*6` + 每回合 `debug tier=6`），**默认 0** | 脚本复评：∞金币 1169.5 → **959.5**（免费 tier6 反而更低——手写脚本不靠它） |
| 7 | （附加）小模型冷启动 | `--bc-teacher-from <ckpt>`：用**另一个 checkpoint** 在沙盒里 T=1 采样做 BC | 300k 决策从 s14 蒸馏：CE 2.53→1.45，top1 33%→49% |
| 8 | （附加）缺「对载体施法数」 | `evaluate(carrier_audit=1)` + `runs/economy_sandbox/audit_ckpt.py`（与完整游戏同口径：目标选择命中载体 eid 的次数） | §9.4 / §9.7 |

**小模型**：`--arch tiny` **不可行**（已核实，不是没试）：
- `TinyAZNet` 只返回 `(policy_logits, 8-rank logits)`，**没有标量 value 头**，而沙盒 PPO 用
  GAE + `value_loss=mse` 必须有 scalar value；
- 它的观测编码是 `3227 → MLP`，与完整游戏的 entity token 编码不一致，**权重无法回迁**。
- 折中：**同一架构的小 entity** `--arch entity --d-model 256 --n-layers 4`（**3.57M**
  参数，观测/动作/value 头与 14.81M 的 s14 逐项一致，checkpoint 可直接回完整游戏）。

### 9.2 吞吐

| 模型 | 参数量 | 环境数 | 决策/秒（含 PPO 更新） | 2M 决策耗时 |
|---|---:|---:|---:|---:|
| s14 entity 384×8 | 14.81M | 96 | 2333–2520 | ~14 min |
| 小 entity 256×4 | 3.57M | 96 | **3988–4216** | 8.4 min |

≥2000 达标（小模型约 2×）。瓶颈在 CPU 侧 `engine.step`（96 环境 lockstep，~110 µs/决策），
不是网络前向。

### 9.3 小模型臂（`runs/economy_sandbox/sb_small`）

`--from-scratch --d-model 256 --n-layers 4` → BC 300k（s14 教师，gold=10）→ PPO 2M，
金币课程 `0:99,2M:30`（99 阶段跑满 2M）：

| decisions | gold | t12 Σ p50 | t15 Σ p50 | tier | 载体率 | 施法数 | L_T |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0（BC 后） | 99 | 1114 | 1243 | 6 | 0.50 | 36 | — |
| 500k | 99 | 993 | 1123 | 6 | 0.41 | 28 | — |
| 1000k | 99 | 1185 | 1277 | 6 | 0.56 | 31 | — |
| 1500k | 99 | **1194** | **1394** | 6 | 0.53 | 30 | 0.725 |
| 2000k | 30 | 864 | 1206 | 6 | 0.25 | 34 | — |
| final（64 局） | 30 | 1041 | 1420 | 6 | 0.41 | 30 | — |

- ∞金币下 2M 决策就把 t12 从 1114 推到 **1194（> ∞金币脚本的 1170）**、t15 1394
  （脚本 1212）——**「缩放可学」在小模型上成立**（宽经济下）。
- **放到部署金币 10 就崩：t12 p50 = 0、t15 = 10**（`audit_ckpt --gold 10`，32 局；同协议
  s14 = 635/910）。逐回合表显示它把每回合 10 金币全砸在**升级 tier**（t1 tier2 → t5 tier5），
  场上 0 随从、金币 0 —— 富经济习惯，不是另一个游戏。

### 9.4 主臂（`runs/economy_sandbox/sb_main`，s14 起点，12M 预算）

```bash
OUT=runs/economy_sandbox/sb_main bash runs/economy_sandbox/launch.sh \
  --checkpoint runs/az_entity_s14/model.pt --device cuda:7 \
  --decisions 12000000 --envs 96 --batch-decisions 16384 \
  --minibatch 1024 --grad-accum 8 --epochs 1 --lr 3e-6 \
  --entropy-coef 0.004 --target-kl 0.05 --sandbox-reward board_delta \
  --sandbox-gold-ramp "0:99,1M:30,3M:15,5M:10" \
  --eval-every 1000000 --eval-games 32 --save-every 1000000
```

> **与任务给的 ramp 串的差别**：任务给的是 `0:99,2M:30,6M:15,10M:10`，最后一段正好落在
> 10M 预算**边界上** ⇒ 策略**从未在 gold 10 上训练过**却要在 gold 10 上评测。按原串先跑了
> 236k 决策确认这一点（gold 切到 10 的瞬间 t12=222），随后把阈值前移成 `1M/3M/5M`
> 并把预算加到 12M：99/30/15/10 四段都在预算内，5M–12M 是 **7M 决策的部署金币阶段**。

评测（同 run 内 32 局，seed 900000，gold = 当时档位）：

| decisions | gold | t12 sample | t15 sample | t12 greedy | tier | 载体率 | 施法 | 酒馆 buff |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0（s14） | 99 | 1136 | 1158 | 1273 | 6 | 0.41 | 34 | 2 |
| 1000k | 30 | 1124 | 1174 | 1170 | 6 | 0.47 | 41 | 4 |
| 2000k | 30 | **1158** | 1314 | 1102 | 6 | 0.56 | 50 | 4 |
| 3000k | 15 | 614 | 892 | 653 | 6 | 0.47 | 44 | 4 |
| 4000k | 15 | 601 | 894 | 654 | 6 | 0.53 | 50 | 4 |
| 5000k | 10 | 222 | 356 | 186 | 3 | 0.22 | 29 | 0 |
| 6000k | 10 | 244 | 356 | 122 | 2 | 0.16 | 30 | 0 |
| 6.6M（停） | 10 | — | — | — | — | — | — | `L_T` 0.557 ↓ |

**停的原因**：`ep_LT`（训练返回 = 终局强度）在 gold 10 阶段 0.606 → 0.597 → 0.557 单调下降，
继续跑只会更差；原计划 12M，6.6M 处停（`model_step_6000000.pt` 保留）。

**同 seed 校准（s14 自己，seed 900000 / 32 局）**：gold 99 = 1136、30 = **1079**、
15 = **902.5**、10 = **626**。于是同档位对比是：

| gold | s14（未训练） | 训练后最好 | 结论 |
|---:|---:|---:|---|
| 99 | 1136 | 1136（0）/ 1124（1M） | 持平 |
| 30 | 1079 | **1158**（2M） | **+7%（噪声内）** |
| 15 | 902 | 601（4M） | **−33%** |
| 10 | 626 | 244（6M，3e-6）/ 485（1M，1e-5） | **−60%** |

> ⚠️ **32 局 p50 的 seed 噪声很大**：同一个 s14 在 seed 910000 下 gold 30 = 1355 / 15 = 774，
> 在 seed 900000 下是 1079 / 902。**跨 seed 比较没有意义**，本表一律同 seed。

**部署金币 10 的损伤曲线**（s14 与各 step，seed 910000，32 局；括号内 greedy t12）：

| ckpt | t12 | t15 | tier | 载体率 | 施法 | **对载体施法/局** |
|---|---:|---:|---:|---:|---:|---:|
| s14（0） | **635** (668) | 910 | 5 | 0.38 | 36 | 0.8 |
| 1M | 542 (554) | 755 | 6 | 0.59 | 32 | 0.4 |
| 2M | 503 (484) | 746 | 6 | 0.44 | 34 | 1.0 |
| 3M | 422 (542) | 662 | 6 | 0.47 | 37 | 2.1 |
| 4M | 382 (422) | 530 | 5 | 0.31 | 36 | 2.4 |
| 5M | 288 (149) | 406 | 3 | 0.16 | 31 | 1.1 |
| 6M | 308 (102) | 432 | 2 | 0.16 | 34 | 1.5 |

单调下降：**每一个 checkpoint 在部署金币下都不如起点 s14**。「对载体施法」从 0.8 升到 2.4
（策略确实学到了这条局部动作），但 tier/载体在场率崩了 → Σ 净降。

### 9.5 控制臂：无课程、gold=10、lr 1e-5（`runs/economy_sandbox/sb_lr1e5_g10`）

排除「课程本身害的」：直接从 s14 在 gold 10 上训、不切档（lr 1e-5）：

| decisions | t12 sample | t15 sample | t12 greedy | `L_T` |
|---:|---:|---:|---:|---:|
| 0（s14） | 626 | 904 | 645 | 0.665 |
| 1000k | 485 | 662 | 543 | 0.653 |
| 1330k（停） | — | — | — | 0.627 ↓ |

1M 内 −23%，退化方向与 lr 3e-6 完全相同 ⇒ **lr 和课程都不是根因**（此臂在 `L_T` 继续下滑处停）。

### 9.6 诊断：修好管道之后为什么还是学不动

1. **策略确实在动**：`KL(s14 ‖ step_2M) = 0.473 nat`、top1 一致率 **66%**
   （`runs/economy_sandbox/policy_kl.py`，4096 条固定观测）——不是「lr 太小动不了」。
2. **动的是熵，不是强度**：策略熵 0.75→0.89（`entropy_coef=0.004`），`L_T` 0.665→0.557。
3. **奖励学到的是局部势，不是复利链**：`board_delta` 立刻奖励「抬 Σ」的动作
   （施法打载体 0.8→2.4），而「买/留载体」的收益要 3–5 回合后才兑现，被 λ=0.95 的 GAE
   抹平（跨回合只剩 value 头）。于是它用「卖载体换施法目标」的局部最优换掉了复利
   ——与 §5.3 的 shaping 崩塌是同一机制的两面。
4. **value 头不是瓶颈**：`value_loss` 0.02–0.03（§5.4 时 0.17–0.27），10M 预算下价值学习
   已收敛；瓶颈在**策略梯度上的信用分配**。
5. **课程在这个预算下有害**：每档下台阶塌 ~50%，lr 3e-6 恢复 ~+20 Σ/1M。「先富后穷」要成立，
   每档至少 5–10M 决策、总预算 **2–5×10⁷**（与 §5.4 的粗估一致），不是 12M。

### 9.7 迁移（失败臂也验代理）

判据要求「成功才迁移」，但**退化臂也必须验代理**，否则分不清「沙盒学不动」与
「沙盒不可迁移」。取退化最轻的训练 checkpoint（主臂 1M：沙盒 gold-10 t12 542 vs s14 635，
−15%），完整游戏 `quality_monitor --games 48`：

| 设置 | 权重 | mean_rank | top4 | win | survive@t12 | **t12 Σ p50** | t15 Σ p50 |
|---|---|---:|---:|---:|---:|---:|---:|
| 5 席人类战团 p=0.9 | s14 | 5.56 | 0.21 | 0.00 | 0.25 | **457** | 547 |
| 5 席人类战团 p=0.9 | 沙盒 1M | 6.15 | 0.17 | 0.00 | 0.13 | **412** | 422 |
| 1 席人类战团 p=0.3 | s14 | 2.27 | 0.96 | 0.21 | 0.96 | **608** | 942 |
| 1 席人类战团 p=0.3 | 沙盒 1M | 2.52 | 0.94 | 0.25 | 0.92 | **571** | 1008 |

- **代理仍然忠实**：沙盒 −15% → 完整游戏 −10%（难设置）/ −6%（易设置），名次与存活同步变差。
  沙盒既没伪造进步，也没把退化藏起来。
- 顺带发现**完整游戏侧的 bug**：`scripts/quality_monitor.py` 读 `pending["options"]`，而引擎
  `Pending::Target` 序列化的键是 **`targets`**（`rust/crates/hsbg-engine/src/debug.rs`）
  ⇒ `casts_on_carrier_mean` **恒为 0**（§4/§5 的历史数字同样失真）。
  沙盒侧 `evaluate(carrier_audit=1)` 已按 `targets` 实现，得到非零值（§9.4 表）。
  **已修复（2026-11-01）**：脚本改为先读 `targets`、回退 `options`（旧数据），单测
  `tests/test_quality_monitor.py` 构造两种 pending 结构锁住。修复后 s16 当前权重在
  **band0（1 席 p=0.30 / p50 / full）+ `--games 48`** 的真实值：
  `casts_on_carrier_mean = 1.52`（有载体局 2.92）、`carrier_turns_mean = 2.90`、
  `r_carrier_turns_str12 = +0.021 [−0.323, +0.157]`（n₁₂=48）、t12 Σ p50 = 542。
  ⇒ 之前「对载体施法 ≈ 0 / 几乎不打在载体上」的结论是**测量 bug**，不是策略行为；
  但「载体回合数与 t12 强度正相关」仍未成立（CI 含 0）。
  产物：`runs/az_entity_s16/eval/quality_band0_carrier_fix.json`。

### 9.8 结论：是否作为 s17 第一阶段

**不作为。** 按判据（2000 成功 / 1200 部分 / <800 失败）这是**失败**：部署金币下训练后最好
**542** < s14 起点 635/662；同 seed 同档位对照也只有 gold 30 的 +7%（噪声内），15/10 都显著
更差。12M 决策的沙盒 PPO **没有产生可迁移的增益**；配方修好后，失败原因已从「管道 bug」
收敛到「信用分配 / 样本效率」。

可用的正面结论（写进 s17 设计）：
1. **管道是健康的**：§6 的四条坑都有回归护栏（dtype 自检、batch 断言、`L_T` 记账），主臂
   400 次更新 0 次被丢弃、KL 常年 1e-3；吞吐 4k 决策/秒（小模型）。
2. **∞ 金币下缩放确实可学**：小模型 3.57M + BC(300k) + 2M PPO → t12 1194 / t15 1394，超过
   手写 ∞金币脚本（1170/1212）。**不是学不会，是富经济学到的东西不能直接迁移到穷经济**。
3. **金币档位是第一序变量**（同权重 626/902/1079/1136 → 10/15/30/99）；任何「沙盒 t12」
   报告必须写明金币档位与 seed，否则不可比。

**下一步（按优先级）**：
1. **搜索标签**（最优先）：沙盒一局 22 ms，MCTS 完全跑得动。用现有 value 头 + PUCT 对
   关键决策（买 / 施法目标）做 64–256 次模拟，把 `(obs → 搜索改进后的 π)` 当监督标签做
   离线 BC / DAgger，而不是让 PPO 从 ±1e-3 的 advantage 里自己找。22 ms/局是这条路线
   成立的核心资产。
2. **奖励改口径**：不要 `Σ_t` 的势函数；改成「t≥8 的载体在场回合数 × 对载体施法数」这类
   **链条指标**的终局奖励（或 `final_strength` + 只对 carrier 相关动作给过程奖励），
   避免 §9.6-3 的「卖载体换局部势」。
3. **金币课程要么别用、要么每档 5–10M**：12M 下四档课程是纯损伤（每档塌 50%、恢复 20 Σ/1M）。
4. **免费 tier6 不是捷径**：脚本在免费 tier6 下 959.5 < 1169.5；它只改变「省下的升级钱」，
   沙盒的真上限由动作上限（40）与格子数决定。
5. 修 `quality_monitor.py` 的 `targets` 键（§9.7），否则所有「对载体施法」数字都是 0。
   **（2026-11-01 已修：先读 `targets` 回退 `options`，单测 `tests/test_quality_monitor.py`；
   s16 band0/48 局复测 `casts_on_carrier_mean = 1.52`、`r_carrier_turns_str12 = +0.021`，
   见 §9.7。）**

---

## 10. 搜索标签（PUCT/MCTS）+ 离线 BC（2026-11-01）

§9.8 把「搜索标签」列为下一步最优先项（沙盒 22 ms/局 ⇒ MCTS 跑得动）。这一节是
**第一版实现 + 500 局标签 + 离线 BC** 的完整记录。结论先行：

1. **管道建好、可复现、指标可测**：`hsbg/az/train/sandbox_search.py`（PUCT，64–256 sims，
   策略头先验 + scalar value 头叶评估）、`scripts/gen_sandbox_search_labels.py`
   （500 局 / gold 10+30 各半 / 逐步 `obs → π_search`）、`scripts/train_search_bc.py`
   （soft-label CE + 沙盒评测）。
2. **判据未达**：gold 10 下 BC 后 t12 Σ p50 = **478.5**（s14 同协议同 RNG 552.5，
   96 局；32 局时 RNG 敏感，见 §10.6），离 **900** 差得远；t15 771 vs 811。
   ⇒ **这一版搜索标签不构成 s17 路线**。
3. **但标签确实改变了行为**：BC 后 `carrier_turns_mean` 3.45→**4.45**、
   `casts_on_carrier_mean` 0.90→**1.23**、`carrier_rate` 34.4%→**45.8%**（96 局）——
   搜索标签**成功教会了「买载体 + 对载体施法」**，与 §9.6 的 PPO 同一个病：
   行为对了、强度没涨（tier/节奏/整体 Σ 没跟上）。
4. **失败机理是可定位的**（§10.5）：s14/s16 的 scalar value 头在完整游戏训练里
   `value_head_coef=0`（只训 rank 头），**直接拿来做叶评估等于随机头**——必须先补拟合；
   拟合后（val_corr **0.956**）它也只对「单步动作」给出弱排序（Spearman 0.25、
   argmax 一致 67%），而 PUCT 默认 `c_puct=1.5` 的探索项是 Q 跨动作差（0.034）的 3 倍
   ⇒ 访问分布退化成先验本身（KL **0.011**、top1 一致 99.2%）。把 c_puct 压到 0.25 后
   π 真的偏离（KL **0.43**、top1 一致 95.2%），**行为更强地偏向载体**，但整局更弱
   （同 seed 配对 gold10 t12 **534 vs 601.5**）。

### 10.1 文件

| 文件 | 作用 |
|---|---|
| `hsbg/az/train/sandbox_search.py` | PUCT/MCTS（`SearchConfig` / `SandboxTree` / 跨局批量叶评估 `SearchRunner`）、`should_search`、`action_kind` |
| `scripts/gen_sandbox_search_labels.py` | 生成标签：value 头拟合、关键决策搜索、逐步记录、summary（延迟 / KL / top-1 一致率） |
| `scripts/train_search_bc.py` | 标签 → soft-label CE → 沙盒评测（t12/t15 / 载体指标 / 判据） |
| `scripts/annotate_search_labels.py` | 合并分片 + 补 `tier` / `carriers`（纯 obs 解码，容忍半截 gzip） |
| `tests/test_sandbox_search.py` | 4 项契约：`clone+search_step` 与 `step` 逐位一致、π 合法稀疏可复现、`should_search`、动作段 |
| `data/search_labels/sandbox_labels.jsonl.gz` | **500 局 / 202,385 步 / 36,953 个搜索标签**（gold 10: 252 局；gold 30: 248 局） |
| `runs/economy_sandbox/search_value/s14_vfit.pt` | 拟合后的 scalar value 头（trunk 冻结，`tanh(head(g))`） |
| `runs/search_bc/` | BC checkpoint + `eval.json`（判据）+ `paired_base_g10.json`（配对基线） |

标签记录（每步一条 JSONL）：
`{seed, gold, turn, step, tier, carriers, action, kind, searched, pi(top-k), pi_base(top-k),
sigma, value, obs{f16→3227 f16, cards→124 i16, mask→245 bits}, search{sims, seconds, nodes,
leaf_calls, root_value, top1}}`；整局结束再写一条 `{"type":"episode", sigma_t12, sigma_t15,
tier_final, carriers_max, spells_t15, ...}`。

### 10.2 搜索设计（与任务口径的对应）

| 任务要求 | 实现 |
|---|---|
| 每步 64–256 次模拟 | `--search-sims`（本轮 64；生成器默认 128），`SearchConfig.sims` |
| 用 value 头做叶评估、策略头做先验 | `SearchRunner.evaluate` 一次前向拿 `(masked softmax, scalar value)`；叶子值 = `L(Σ)+V`（`--search-value-mode total`） |
| 只搜关键决策（`--search-topk 8`） | 根候选 = 合法动作里策略概率 top-8（剔除 Move：沙盒无战斗）；且只在「策略 top-1 是 buy/play/choose/upgrade/...」时搜（`should_search`），每回合上限 `--search-max-per-turn` |
| `--search-depth`（到回合末 / 3 回合） | `depth_turns=1`（默认）= 本回合末；`depth_turns=3` 可跨 3 回合；`max_plies` 硬上限 |
| 预算控制 | 跨局 lockstep 批量叶评估（一次前向 B 条），4 进程 × 32 局并行 |
| 输出访问分布 π | `SearchResult.pi`（稀疏，和=1）+ `visits` / `q` |

**状态转移**用引擎 `Game.copy()`（~8 µs）+ 新方法 `EconomySandbox.search_step`
（与 `step` 同一状态机：新回合注入金币/回血、其余座位立刻 EndTurn，但**不取 view**）。
`tests/test_sandbox_search.py` 锁住「逐位 state_json 一致」。

### 10.3 value 头：必须先拟合，否则叶评估是随机头

完整游戏训练（s14/s16）**没有** `value_head_coef`（默认 0），scalar 头只被 rank 头
间接初始化 ⇒ 直接当叶评估 ≈ 噪声（实测 s14 原始头 `corr(V, L_T−L) = 0.35`，且量级不对）。

做法：冻结 trunk，在 `g`（global token，384 维）上拟合 `tanh(head(g)) ≈ L_T − L(s)`：

| 项 | 值 |
|---|---|
| 训练数据 | 128 局（gold 10/30 各半，π_base 采样），53,292 个决策 |
| 结构 | `Linear(384→128) → ReLU → Linear(128→1)` + `tanh` |
| **val MSE / val corr** | **0.00142 / 0.956**（`y_mean 0.105` vs `pred_mean 0.104`，无偏） |
| 产物 | `runs/economy_sandbox/search_value/s14_vfit.pt`（单独存，不改标准 checkpoint 结构） |

### 10.4 500 局标签：延迟 / KL / 一致率

生成配置：s14 + 拟合 value 头，`--golds 10,30`，`--search-sims 64 --search-topk 8
--search-depth 1 --search-c-puct 0.25 --search-max-per-turn 6`，4 进程 × 32 并行局。

| 指标 | 值 |
|---|---|
| 局数 / 步数 / 搜索步 | 500 / 202,385 / **36,953（18.3%）** |
| **延迟** | **7.1 s/局**（4 进程 × 32 局并行；单进程≈28 s/局，500 局总墙钟 ~11.5 分钟） |
| 单次搜索延迟 | p50 **76 ms**（128/64 sims、top-8、本回合末深度，跨局批量） |
| **KL(π_search‖π_base)** | mean **0.43** nat（在线全分布口径；稀疏 top-8 复算 p50≈0.21） |
| **π top-1 vs 策略 top-1 一致率** | **95.2%** |
| π 的 top-1 概率质量 | 0.71（先验通常 0.3–0.5 ⇒ 搜索更尖锐） |
| 标签轨迹强度（gold 10，252 局） | t12 Σ p50 **534** / t15 **781** |
| 同上（gold 30，248 局） | t12 **1205** / t15 **1348** |
| 配对 s14 基线（gold 10，64 局，同 seed 区，sample） | t12 **601.5** / t15 **819** |

读法：**搜索确实把 π 推离了先验**（KL 0.43、5% 的步换了 top-1），但用 π 采样出的
**轨迹反而略弱**（534 vs 601.5，−11%；t15 781 vs 819，−5%）：搜索偏好的动作（更多 buy / play / sell-on-carrier）
没有转成终局强度。

### 10.5 为什么「行为对了、强度没涨」：三层证据

1. **价值头对单步动作只有弱排序**。抽 12 个真实决策点，把 8 个候选各执行一步后
   用策略 argmax 打到本回合末（真值 = 回合末 L + 下一回合 V）：
   - `Spearman(Q_head, true_L)` = **0.246**，`argmax Q == argmax true` = **67%**，
     而**策略 top-1 命中真值 = 0%**；
   - Q 的跨动作标准差 **0.034**，与 value 头残差同量级（叶值 RMSE≈0.037），
     而单个动作在 `L` 上的即时收益只有 **1e-4–1e-3**（`L=log1p(Σ)/log1p(30000)` 的尺度）。
2. **PUCT 的探索项吃掉了这点信号**。`c_puct=1.5` 时 `U(P=0.3,N=16)≈0.1`，是 Q 跨动作差
   的 3 倍 ⇒ 访问次数 ∝ 先验 ⇒ π≈π_base。实测（`--search-c-puct 1.5`，92 局存档）：
   **KL 0.011 nat、top1 一致 99.2%** —— 标签是自蒸馏，没有信息量。
3. **强行让 Q 说话会更差**。加「未访问候选先各访问一次」+ `c_puct=0.25`：KL 0.43、
   top1 一致 95.2%，但搜索后的策略在 gold 10 上 **t12 534 < 601.5**。把 BC 学到的行为
   摊开看：载体行为显著变强（§10.6），但 tier/节奏/总 Σ 没变 —— 与 §9.6 的 PPO 完全同构：
   value 头把「即时 Σ / 载体动作」当成目标，学不到「多回合复利」。

### 10.6 离线 BC（`scripts/train_search_bc.py`）

配置：`--only-searched 1`（只用 36,953 个关键决策标签）、soft-label CE（masked，按 π 的
支撑重新归一）、lr **3e-5**、batch **256**、**2 epoch**、从 s14 初始化。

| 项 | 值 |
|---|---|
| CE / top-1（epoch 1→2） | 1.373 → **1.246**；75.2% → **78.2%** |
| 训练耗时 | 17 s（36,953 样本 × 2 epoch） |

评测（沙盒 gold 10，**96 局**，seed 910000，BC 与 s14 用**同一条采样 RNG**）：

| 指标 | s14（sample） | **BC（sample）** | s14（greedy） | BC（greedy） |
|---|---:|---:|---:|---:|
| t12 Σ p50 | 552.5 | **478.5（−13%）** | 606 | **697.5（+15%）** |
| t15 Σ p50 | 811 | **771** | 909.5 | **1004** |
| tier p50 | 5 | 5 | 4 | 4 |
| `carrier_rate` | 34.4% | **45.8%** | 32.3% | 32.3% |
| `carrier_turns_mean` | 3.45 | **4.45** | 3.28 | 3.68 |
| `casts_on_carrier_mean` | 0.90 | **1.23** | 0.75 | 0.83 |
| spells p50 | 33.0 | 32.5 | 33.5 | 41.5 |

**判据**：gold 10 下 **t12 ≥ 900** ⇒ **未达（478.5）**。搜索标签的正面效果是
**载体行为被写进来了**（载体回合数 +29%、对载体施法 +37%）；负面是**采样部署口径下
强度 −13%**。注意 BC 的**贪婪**评测反而 +15% —— 标签把 π 变尖（top-1 质量 0.71），
argmax 更接近搜索意图，但 T=1 采样时探索变少、更容易掉进「刷载体动作」的局部最优。

> **32 局的 RNG 噪声很大**：同一对权重在 32 局（固定 torch seed）下是
> BC 629.5 vs s14 536（+17%），96 局才收敛到 478.5 vs 552.5（−13%）。
> 任何「BC 是否比 s14 强」的结论都必须 ≥96 局 + 固定采样 RNG（本轮两次 32 局
> 结论方向相反，就是这个原因）。

### 10.7 结论与下一步

**结论：这一版（value 头叶评估 + 1 回合 PUCT + soft-label BC）不作为 s17 路线。**
搜索标签能改变行为（载体回合数 +29%、对载体施法 +37%），但改变不了强度；
判据 900 未达（样本口径 478.5，差 47%；贪婪 697.5，也差 22%）。

要让它成立，至少要改三处（按优先级）：

1. **叶评估换成「回合末真实 Σ」**：不要用 value 头预测单步价值（噪声 0.037 >> 动作效应
   1e-3）。用「执行候选动作后，策略 rollout 到本回合末」的真值做 Q —— 批量跨候选/跨局
   后成本可接受（8 候选 × 约 20 步，batch 64 时 ~20 次前向/决策）。
2. **DAgger，而不是纯 BC**：行为仍走 π_base（保持 586 的水平），只把 π_search 当标签；
   纯 BC 会把采样噪声与「搜索偏好的载体动作」一起学进来（本轮 t12 −14%）。
3. **只搜「载体/施法」决策并单独给价值**：把搜索预算集中在 `§9.8-2` 的链条指标上
   （t≥8 载体在场回合 × 对载体施法），而不是全动作空间的 top-8。

复现命令：

```bash
# 0) 拟合 value 头（128 局，~25 s）
PYTHONPATH=rust/python:. python scripts/gen_sandbox_search_labels.py \
  --checkpoint runs/az_entity_s14/model.pt --device cuda:7 --games 1 \
  --fit-value-games 128 --fit-value-envs 64 --out /tmp/x.jsonl.gz

# 1) 500 局标签（4 分片 × 125 局；~12 min）
for k in 0 1 2 3; do s=$((960000+k*125)); \
  PYTHONPATH=rust/python:. python scripts/gen_sandbox_search_labels.py \
    --checkpoint runs/az_entity_s14/model.pt \
    --value-head runs/economy_sandbox/search_value/s14_vfit.pt --device cuda:7 \
    --games 125 --envs 32 --seed0 $s --search-sims 64 --search-c-puct 0.25 \
    --search-max-per-turn 6 --out data/search_labels/shards/shard${k}.jsonl.gz; done

# 2) 合并 + 补 tier/carriers
PYTHONPATH=rust/python:. python scripts/annotate_search_labels.py \
  --in data/search_labels/shards/shard{0,1,2,3}.jsonl.gz \
  --out data/search_labels/sandbox_labels.jsonl.gz

# 3) BC + 评测（判据 900）
PYTHONPATH=rust/python:. python scripts/train_search_bc.py \
  --labels data/search_labels/sandbox_labels.jsonl.gz \
  --checkpoint runs/az_entity_s14/model.pt --device cuda:7 \
  --epochs 2 --lr 3e-5 --batch 256 --only-searched 1 \
  --out runs/search_bc/bc_search.pt --eval-games 32 --eval-gold 10
```
