# 轻量战斗沙盒（1 对手/回合）

> `docs/FULL_GAME_TRANSFER.md` §5 的定论：**无战斗的经济沙盒里最优解是「少买留钱」**，所以
> 复利策略不迁移（完整对局 t15 Σ 22.5）。本模块把**战斗这一层回报**补上，但只打 **1 场/回合**
> （不做 7 席），保持 ~1/6 的开销。
>
> 代码：`hsbg/az/train/combat_sandbox.py`（环境）、`scripts/train_combat_sandbox.py`（PPO 入口）、
> `tests/test_combat_sandbox.py`（6 项契约测试）。产物：`runs/combat_sandbox/**`。

## 1. 环境定义（与 `EconomySandbox` 的差别，全部是加法）

| 项 | `EconomySandbox` | `CombatSandbox` |
|---|---|---|
| 玩家数 | 8（其余 7 席空转） | **2**（learner + 1 个对手） |
| 伤害 | `damage_caps=[[1,0]]`（**恒 0**） | **去掉封印，引擎真实伤害** |
| 对手 | 空战团 + 每回合 EndTurn | 每回合从 `library_real_quasi_full.jsonl` 按分位采样一条**真实战团**注入 seat 1（`fidelity=full`），并把对手血量重置到 30 |
| learner 血量 | 每回合 `set_player health=30`（回满） | **不回满**：伤害跨回合累积，≤0 即终止（`--hp-start 30`） |
| 奖励 | `log_strength`（ΔL 望远镜） | 同上 **+** `win(+1)/lose(−1)` **+** 伤害差归一化 `(dealt−taken)/hp_start` |
| 观测/动作 | 3227+124 / 245（同一套） | **完全相同**（权重可直接互导） |

额外保留两个已证明有效的开关（来自 task-13）：
`gold_profile`（对齐完整对局收入 `3,4,5,6,7,8,9,10,10,10,10,10,11`）与
`tier_reward_coef`（`r += coef·Δtier`，推策略上 t5/t6 才摸得到 Titus/Gatekeeper）。

## 2. 契约（`tests/test_combat_sandbox.py`，6 项全绿）

1. `CombatConfig` 对 `SandboxConfig` 是**加法**（旧字段默认值逐一相等）；
2. 引擎配置**确实没有** `damage_caps` 且 `num_players=2`（父类仍有，证明没改旧语义）；
3. `_inject_gold` **不写 health**（否则每回合回满 → 伤害没有后果）；
4. 真跑 3 回合：每回合有 1 场战斗、`wins+losses+ties == combats`、血量单调不增、Σ/tier 口径仍在；
5. **确定性**：同 seed 同动作序列逐位一致；
6. `summarize_combat` 的字段齐备（win_rate / 伤害 / killed_rate / hp_end）。

## 3. 训练配方（`scripts/train_combat_sandbox.py`）

算法与 `scripts/train_compound_ppo.py` 完全一致（**value-warmup 只训 `value_head`** ——
entity 的 value 头与策略共享 trunk，整网回传会把策略推歪；**KL anchor β≡0.1**；GAE γ1/λ0.95；
**无熵奖励**；minibatch×grad_accum 梯度累积；退化早停）。

```bash
$PY scripts/train_combat_sandbox.py --checkpoint runs/compound_bc/ckpt_w8e4.pt \
  --out runs/combat_sandbox/cs1 --decisions 300000 --envs 16 --device cuda:7 \
  --gold-profile 3,4,5,6,7,8,9,10,10,10,10,10,11 --tier-reward-coef 0.1 \
  --opponent-quantile p75 --value-warmup 100 --anchor-beta 0.1 --eval-games 24
```

## 4. 首个冒烟结果（16k decisions，只为验证链路）

`tier_p50 6.0`、`ep_sigma_p50 107→147`、`damage_taken_mean 12.0`、`win_rate 0.0`
（对 p75 真实战团一场未赢——0.667M 的沙盒 BC 起点本来就打不过真实中位数战团）。
→ 说明**战斗与掉血确实在结算**，且 tier 奖励把 tier 推到了 6（放大器门槛已打开）。

## 5. 判据（task-14）

完整游戏 **t15 Σ p50 ≥300 且名次 ≤7.0**（现状 22.5 / 7.97）。
达成 → 做 A2 蒸馏进 14.9M；不达成 → 把「必须完整游戏 RL」写成定论，转 300M 直接训练。

（结果表见本文件末尾「§6 结果」，由 300k 训练 + 沙盒 24 局 + 完整游戏 100 局填定。）

## 6. 结果（300k decisions，p75 对手，0.667M 从 `ckpt_w8e4` 起）

| | 轻量战斗沙盒（24 局，greedy） | 完整对局（100 局） |
|---|---|---|
| t15 Σ p50 | 146（训练侧 ep_sigma_p50 107→**181**） | **46**（p90 99，max 218） |
| tier p50 | **6** | 4 |
| **胜率** | **0.0**（0 胜 / 每局约 10 场全败） | – |
| 承伤/局 | 10.2 | – |
| 名次均值 | – | **7.92** |
| 决策/局 | – | 50.9 |
| amp / goldens | – | 0.01 / 0.23 |

**判据（完整对局 Σ ≥300 且名次 ≤7.0）：Σ 46 ❌、名次 7.92 ❌ ⇒ 不达成。**
（对比：无战斗沙盒 22.5 / 7.97；s14 完整游戏 579 / 6.00。）

### 6.1 为什么补了战斗还是不行（这次的诊断很具体）

1. **胜率恒为 0 ⇒ 战斗奖励没有梯度**：`p75` 真实战团对 0.667M 的沙盒 BC 起点是**降维打击**，
   每回合都输，奖励恒为 `−1 + 伤害差`，策略学不到「怎么赢」，只能学到「少输一点」。
   要让它有用，必须**由易到难**（先 p25/p50，胜率 ≥30% 再升档），否则战斗信号 = 常数。
2. **tier 奖励在沙盒里有效、在完整对局里无效**：沙盒 tier p50 = **6**，完整对局仍是 **4**。
   说明「愿意升本」这个行为**没迁移**——因为完整对局里升本的钱要从战斗/利息里省出来，
   而决策/局只有 50.9（s14 是 155），它每回合几乎没有操作空间。
3. **沙盒 Σ 天花板太低**：即便 tier 6，沙盒 Σ 也只有 146–181（真实收入 3–11 金/回合下买不了几张牌），
   而完整对局要 500+ 需要「多回合滚雪球」——这不是 15 回合 1v1 能监督出来的。

## 7. 定论（写死）

> **沙盒（无论有没有战斗、经济对不对齐）都不是完整对局的可行监督信号。**
> 三次递进实验（无战斗 62 → 经济对齐 22.5 → 轻量战斗 46）都远低于判据 300；
> 根因是沙盒缺少「多名次/多回合滚雪球」这一层结构，而不是缺某一项奖励或某一条收入曲线。
>
> **下一步应当是直接在完整对局里做 RL（或 300M 规模的完整对局训练）**，沙盒最多只能用于
> 「动作分布预训练」（BC 起点），不能用于「能力达标」判定。

（保留资产：`CombatSandbox` 与 6 项契约测试仍有用——如果将来要做「由易到难的战斗课程」，
它是现成的、比 7 席便宜 6 倍的载体；唯一要改的是课程（p25→p50→p75），而不是环境。）