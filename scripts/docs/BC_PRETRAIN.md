# BC 预训练 warm-start（阶段 A）

> **TL;DR**：`scripts/bc_pretrain.py` 已实现"人类数据 -> 监督预训练 -> `model.pt` -> PPO + KL anchor"
> 的完整阶段 A 通道。20k 样本 / 200 步（cuda:7，25 s）能把 holdout 类型 CE 从
> **1.616 降到 1.516**、类型准确率 **33.7% -> 39.6%**，并把 t12 的 **tier p50 从 4 抬到 5**、
> **tier≥5 比例 25% -> 58%**（修复了"tier 锁 4"）；但**战团强度与胜率同时崩塌**
> （t12 强度比 **0.142 -> 0.031**，48 局 top4 **95.8% -> 29.2%**），根因是 **Move 动作族
> （196..244）完全不在分层 BC 的监督范围内**，其 logits 是棋盘 token 的双线性项，
> 随 trunk 漂移后抢占 argmax（moves/turn **2.4 -> 17.3**）。
> **结论：当前 loss 形态下不建议直接做更长的 BC-only 预训练**；先给 Move 族加监督
> （把 `reposition` 加进 BC 白名单）或做**定向** Move 正则，再用 KL 预算（≤0.2）放开预算。
> 详见 §5–§7。
>
> **2026-10 更新（§9）**：已把 `reposition` 做成第 10 类，并提供可选的 Move 段 MSE 锚定
> （均默认关闭、关闭时逐位等价）。Move 监督确实把 BC holdout 上的 Move 概率质量从
> **20.9% 压到 5.8%**，但 48 局面板仍不达标：B 组 top4 **20.8%** / 出局强度 **116** /
> tier≥5@t12 **50%**；C 组（anchor 0.1）虽把 moves/turn 压到 **5.3**，tier 与强度反而
> 更崩（**8.9% / 22**）；补充组 D/E/F 最好也只有 top4 **41.7%** / 强度 **118**。
> **没有任何配置通过质量门（top4≥85% & 强度≥600 & tier≥5@t12≥45%），本轮 BC 权重
> 不建议作 s11 起点**（§9.4）。

相关：`docs/BC_AUX.md`（BC 作为 PPO 辅助正则的原始设计）、
`scripts/bc_pretrain.py`、`tests/test_bc_pretrain.py`。

---

## 1. 为什么现有 BC 辅助正则不够

- 现有路径把真实人类对局当 **辅助正则**：`bc_coef=0.004`，每 `bc_every=4` 个 PPO 微批
  才做一次 BC，系数还要按 `m_total/n_bc` 折算，最终 BC 梯度相对 PPO 目标可以忽略。
- 诊断事实：主训练模型 t9 起 **tier p50 锁在 4**，战团强度只有真实 10k+ 同 turn p50 的
  **3–13%**。这说明"从引擎 bot 自对弈里学到的操作强度"与人类强度之间有一个**起点差距**：
  PPO 的价值/优势信号在 bot 对手下几乎不区分"像人类的高强度操作"，因为 bot 太弱，
  任何能赢 bot 的策略都拿满分。
- 因此阶段 A 需要一个**真正的主监督目标**：先让策略在人类动作分布上拟合到一定精度，
  得到一个"像人类"的起点，再由 PPO 在这个起点附近做价值优化，并用
  `--anchor-beta 0.1` 的 KL anchor 防止跑回 bot 式打法。

## 2. 方法

### 2.1 数据与过滤

数据：`data/firestone_bc/bc_samples.jsonl.gz`（308,944 条，1000 局，MMR 4009–15407）。

过滤（`hsbg.az.train.bc_aux.load_bc_samples`）：

1. `action_type` 在 9 类白名单：`sell / reroll / buy_minion / buy_spell / play_spell /
   play_minion / upgrade / hero_power / end_turn`（`reposition / freeze / dark_gift / triple`
   被排除）；
2. `action_index` 合法（0..244）；
3. `mmr >= --mmr-min`（默认 6000，缺失视为不可用）。
4. `--limit` 只保留前 N 条**通过过滤**的样本（默认 0 = 全部 183,245 条）。

### 2.2 编码与损失（复用 PPO 的 BC 实现）

- **观测**：`bc_obs_batch` 把回放可见字段编码成固定的 **3227 floats + 124 cards** 部分观测
  （商店 8 / 手牌 10 / 棋盘 7 / gold / tier / health / turn / hero；未知槽位补 0 并写 mask）；
  同时给出近似动作掩码（白名单动作族中可推断的候选 + 真实动作）。
- **分层损失**：直接复用 `bc_hier_loss`：
  - 类型级：245 动作 logits 按 9 类做 **log-sum-exp 聚合**后 CE（对槽位错位不敏感），
    默认 **类别平衡**（`--class-balance 1`，与 PPO 辅助 BC 同口径）；
  - 卡牌级：`card_head`（3983 类）在 buy/play 样本上 CE 卡牌身份；
  - `loss = 1.0 * type_ce + 0.5 * card_ce`（`--type-weight / --card-weight`）。
- **不做 value**：BC 样本无名次标签，`--value-coef` 只保留接口（>0 会告警并忽略）。
- **训练**：Adam `lr=1e-4`、`batch=256`、梯度裁剪 1.0、bf16 autocast；默认 1 epoch
  （19k 训练样本 ≈ 75 步/epoch）。

### 2.3 holdout 与 RL 保留（`--preserve-rl 1`）

- 以 `--seed` 随机切 `--holdout 0.05`（train/holdout 索引**不重叠**，见单测）。
- 每 `--eval-every` 步（默认自动 `total//10`）在 holdout 上算 `type_ce / card_ce / acc`。
- 训练前记录原策略在 holdout 上的 masked 分布，训练后报告
  `KL(pre‖post)` 的 mean/p50/p95/max 与 top-1 一致率；`mean KL > --max-kl`（默认 2.0）时告警。
- 保存的 checkpoint meta 带：`bc_pretrained=true`、`bc_steps`、`samples`、`bc_samples`、
  `bc_holdout`、`bc_loss`、`bc_holdout_type_ce/acc`、`bc_kl_pre_post`、`bc_anchor_beta` 等；
  init checkpoint 的其它 meta（如 `trainer_updates`、`seq_head`、`bc_card_head`）原样保留。
  卡表/标准化统计不进 state_dict 的部分（tiny 的 `hidden`）也写进 meta，保证
  `load_checkpoint` 能按原维度重建。

### 2.4 命令

```bash
# 正式短跑（20k 样本 / 200 步 / cuda:7；实测 25 s）
PYTHONPATH=rust/python:. python scripts/bc_pretrain.py \
    --init runs/az_entity_s8b/model.pt --limit 20000 \
    --epochs 4 --steps 200 --batch 256 --eval-batch 512 \
    --device cuda:7 --lr 1e-4 --log-every 20 --eval-every 25 \
    --out runs/bc_pretrain

# 全量（183k 样本，1 epoch ≈ 716 步）
PYTHONPATH=rust/python:. python scripts/bc_pretrain.py \
    --init runs/az_entity_s8b/model.pt --limit 0 --epochs 1 \
    --device cuda:7 --lr 1e-4 --out runs/bc_pretrain_full
```

输出：`<out>/model.pt` + `<out>/report.json`（args / 数据分布 / loss 曲线 / eval 曲线 / KL）。

## 3. 超参

| 参数 | 默认 | 说明 |
|---|---|---|
| `--init` | `runs/az_entity_s8b/model.pt` | 起始 checkpoint（缺省即"从 s8b 续训"） |
| `--from-scratch` / `--arch` | off / `entity` | 随机初始化；`tiny` 用于单测 |
| `--mmr-min` | 6000 | MMR 下限 |
| `--limit` | 0（全部） | 样本上限（短跑/正式预算） |
| `--holdout` | 0.05 | holdout 比例 |
| `--lr` | 1e-4 | BC 常用量级 |
| `--batch` | 256 | |
| `--epochs` | 1 | |
| `--steps` | 0（不限） | 总优化步上限（短跑 = 200） |
| `--grad-clip` | 1.0 | |
| `--amp` | bf16 | 仅 cuda 生效 |
| `--type-weight` / `--card-weight` | 1.0 / 0.5 | 分层损失权重 |
| `--class-balance` | 1 | 1 = 类别频率倒数加权（PPO 辅助 BC 口径）；0 = 自然频率 |
| `--value-coef` | 0 | 接口保留（BC 无 value 标签） |
| `--preserve-rl` / `--max-kl` | 1 / 2.0 | 前后 KL 与告警阈值 |
| `--anchor-beta` / `--anchor-scope` / `--anchor-temperature` | 0 / all / 1.0 | 可选 KL(π_θ‖π_init) 蒸馏锚定（见 §5.3，**实测不是可靠修复**） |

## 4. 真实短跑验证（20k 样本 / 200 步 / cuda:7）

配置：`--init runs/az_entity_s8b/model.pt --limit 20000 --epochs 4 --steps 200
--batch 256 --lr 1e-4 --log-every 20 --eval-every 25`，19,000 train / 1,000 holdout，
共 200 步（≈2.69 epoch，51,200 样本更新），**25.1 s / 2043 samples/s**。

### 4.1 loss 曲线（每 20 步）

| step | loss | type | card | type acc | action acc |
|---:|---:|---:|---:|---:|---:|
| 20 | 4.2875 | 1.5314 | 5.5122 | 0.352 | 0.227 |
| 40 | 4.0843 | 1.4160 | 5.3366 | 0.379 | 0.191 |
| 60 | 4.1180 | 1.4562 | 5.3238 | 0.316 | 0.156 |
| 80 | 3.9667 | 1.3128 | 5.3078 | 0.379 | 0.145 |
| 100 | 3.8457 | 1.2896 | 5.1122 | 0.449 | 0.219 |
| 120 | 3.9439 | 1.3462 | 5.1954 | 0.457 | 0.281 |
| 140 | 3.9394 | 1.3171 | 5.2446 | 0.453 | 0.207 |
| 160 | 3.7393 | 1.3130 | 4.8526 | 0.473 | 0.242 |
| 180 | 3.7949 | 1.3355 | 4.9189 | 0.398 | 0.215 |
| 200 | 3.5360 | 1.0869 | 4.8981 | 0.504 | 0.266 |

holdout（1000 条，随机切分）：

| 指标 | step 0 | step 200 |
|---|---:|---:|
| type CE | 1.6158 | **1.5160** |
| card CE | 5.2970 | **4.9273** |
| type acc | 0.3370 | **0.3960** |
| action acc | 0.1710 | **0.2260** |

原策略 KL（holdout，masked）：**mean 1.0039 / p50 0.9133 / p95 1.9802 / max 4.8490**，
top-1 一致率 0.385。mean KL 未超过默认 `--max-kl 2.0`，但 **1 nat 已经非常大**
（PPO 的 target_kl 是 0.02），下文 §5 会看到它对应的行为代价。

同配置 `--lr 0`（1 步）对照：KL 严格为 0、holdout CE 完全不变，说明 checkpoint
保存/加载/评测链路与 s8b **逐位一致**（48 局质量面板 JSON 也完全相同）。

### 4.2 质量面板（`scripts/quality_monitor.py --games 48 --seed-base 520000`）

同一批 seed、纯模型（`move_guard=0`）、对手为引擎 bot。下表所有行都用同一面板，
便于横向比较（"lr0" 行 = s8b 原权重经本脚本存盘）。

| 模型 | KL | mean_rank | top4 | win | death_turn p50 | death_strength p50 | moves/turn | tier p50 t9/t12/t15 | tier≥5 t12 | 强度比 t12 / t15 |
|---|---|---:|---:|---:|---:|---:|---:|---|---:|---|
| **s8b 原权重**（lr0 行完全相同） | 0 | 1.69 | **95.8%** | 60.4% | 14 | **809** | **2.41** | 4 / 4 / 5 | 25.0% | **0.142 / 0.0344** |
| BC 200 步 @ lr 1e-4 | 1.004 | 5.75 | 29.2% | 8.3% | 10 | 93 | 17.28 | 4 / **5** / 5 | **57.8%** | 0.0307 / 0.0047 |
| BC 200 步 @ lr 2e-5 | 0.520 | 3.23 | 72.9% | 33.3% | 13 | 417 | 4.71 | 4 / 4 / 5 | 46.8% | 0.1117 / 0.0256 |
| BC 200 步 @ lr 1e-4 + anchor β=1 (T=2) | 0.777 | 7.04 | 8.3% | 2.1% | 8 | 47 | 13.41 | 3 / 3 / 3 | 0% | 0.0112 / 0.0020 |
| BC 200 步 @ lr 1e-4 + 自然频率（class-balance 0） | 1.494 | 7.23 | 6.3% | 4.2% | 8 | 34 | 16.51 | 2 / 2 / 2 | 0% | 0.0099 / 0.0022 |
| 对照：s8b + 1e-3 相对权重噪声（未训练） | — | 1.83 | 93.8% | 39.6% | 16 | 794 | 4.10 | 4 / 4 / 4 | 22.9% | 0.143 / 0.0335 |

读法：

- **tier 轴被修好了**：class-balanced BC 把 t12 的 tier p50 从 4 抬到 5、tier≥5 从 25% 抬到 58%
  （`upgrade` 在人类数据里只占 1.7%，类别平衡把它放大了 ~6 倍，模型因此学会升级）。
- **强度/胜率轴反而崩了**：t12 强度比 0.142 -> 0.031（4.6 倍差距），top4 96% -> 29%，
  出局强度 809 -> 93；**moves/turn 2.4 -> 17.3**（每回合 40 个动作上限被换位刷满）。
- 自然频率（不做类别平衡）把**模仿指标**做得更好（holdout type acc 50.6%，远超 class-balanced
  的 39.6%），但游戏表现更差（tier 锁 2、强度比 1%）。**"更像人类"与"更强"在这一步是背离的。**
- 1e-3 相对噪声对照只掉 2 pt top4、moves 仅升到 4.1，说明面板不是"任何扰动都会崩"；
  BC 造成的崩塌是**定向漂移**。

## 5. 结论、根因与风险

### 5.1 根因：Move 族不受监督 + 双线性头放大漂移

1. 分层 BC 的 `type_ids` 只覆盖 9 类白名单动作；**Move（196..244）、Freeze、DarkGift 等
   动作的 logit 完全不参与损失**。
2. entity 的 Move logits 是 `hb_i · hb_j`（棋盘 token 的**双线性**项，加上 `move_bias`）：
   trunk/board token 的**幅度**一变，Move logits 按平方放大。而类型级 CE 只约束白名单
   logits 的**相对形状**（log-sum-exp 后 CE），对"白名单整体相对 Move 的尺度"没有约束。
3. 于是 BC 只要更新共享 trunk，Move logits 就可能相对白名单抬升，推理时（合法 Move 不受
   BC 掩码限制）抢占 argmax -> **换位刷满动作预算** -> 没动作/金币去买/打随从 ->
   战团强度崩。实测 moves/turn 随 KL 单调上升：KL 0 -> 2.4、0.52 -> 4.7、1.0 -> 17.3。
4. 旁证：在 BC 的 holdout 输入上，s8b 的**无掩码 argmax 已有 95.9% 是 Move**（Move logits
   对 BC 部分观测是 OOD 的极端值，mean|logit|≈35，max≈237）；所以 Move 头是这套模型里
   最脆弱的"未校准自由度"。

### 5.2 全 245 分布 KL 锚定不是可靠修复

`--anchor-beta`（KL(π_θ‖π_init)，全 245 动作，T=2）实测：

| 配置 | holdout type CE | KL(pre‖post) | 质量面板 |
|---|---|---|---|
| β=0（基线） | 1.616 -> 1.516 | 1.004 | top4 29.2% |
| β=1 | 1.616 -> 1.512 | 0.777 | top4 8.3%，tier 锁 3 |
| β=5 | 1.616 -> **1.789**（变差） | 1.199 | 未跑（CE 已更差，KL 更大） |

原因：Move 的 49 个 logits 在 BC 状态上既极端又近似简并（top-1 由大数相减决定），
全分布 KL 的梯度主要在追教师模型的 Move argmax —— β 小则拉不住，β 大则把 trunk 往
"复制教师退化 Move 分布"的方向拽，反而更糟。**锚定必须作用在 Move logits 本身
（MSE/margin）或直接给 Move 族监督，而不是整条分布。**

### 5.3 其它风险

- **KL 巨大**：200 步 @1e-4 就有 1 nat；默认告警阈值 2.0 对"是否可接 PPO"太松。
  实测 **KL≈0.5 已经掉 23 pt top4**，安全预算应在 **≤0.2**。
- **遗忘**：BC 起点接 PPO 时必须用 `--anchor-beta 0.1` 锚住（见 §6），否则 PPO 会迅速
  冲掉人类先验。
- **holdout 偏乐观**：随机按样本切分，同一 replay 的样本可能同时落在 train/holdout
  （数据按局分组），所以 holdout CE 是 in-distribution 指标，不能当"新对局泛化"。
- **近似动作掩码**：`bc_obs_batch` 的 action_mask 不是引擎 legal_mask 的重建；
  类型 CE 的分母因此偏小，Move/Freeze 等族不在掩码里（同 §5.1）。
- **tier 与强度是跷跷板**：类别平衡 = 抬 tier、压强度；自然频率 = 更像人类、tier 锁死。
  需要 move 监督修好后重新做一次 2x2（class-balance × KL 预算）。

## 6. 如何接 PPO（阶段 B）

BC checkpoint 就是普通 `model.pt`（`load_checkpoint` 可直接加载，`seq_head` / `card_head` /
tiny `hidden` 都会按 meta 重建），因此直接当 `--checkpoint` 用，并用
`--anchor-beta 0.1` 把 PPO 锚在 BC 起点：

```bash
python scripts/train_entity_sync.py \
    --checkpoint runs/bc_pretrain/model.pt \
    --anchor-beta 0.1 --anchor-iterations 200 \
    --bc-coef 0.004 --bc-type-weight 1.0 --bc-card-weight 0.5 \
    ...（其余参数同 runs/az_entity_s10 的命令行）
```

要点：

- `--anchor-beta 0.1`：PPO 的 `KL(π_θ‖π_anchor)`，anchor 在 **BC 起点**；
  `--anchor-iterations 200` + `--anchor-beta-tail 0.02` 让锚定随训练退火。
- 建议先跑 `scripts/quality_monitor.py --checkpoint runs/bc_pretrain/model.pt --games 48`
  过一遍质量门（tier / 强度比 / moves/turn / top4），**再**放 PPO。
- 当前短跑 checkpoint（尤其 lr 1e-4 / 自然频率两版）**不建议直接进主线**：moves/turn 与
  强度比都显著劣于 s8b，PPO 从这种起点出发等于先把 Move 调回来。

## 7. 建议：是否值得用更长预算做正式 BC 预训练？

**当前 loss 形态下：不值得直接加预算。** 200 步已经把 KL 推到 1 nat 并把 gameplay 打崩；
同样的 loss 再跑 200k 样本 / 更长步数只会让 KL 更大、Move 漂移更严重 —— 除非先解决
Move 监督。建议按以下顺序做：

1. **给 Move 族监督（最高优先级）**：把 `reposition` 加入 BC 白名单。数据里已有
   **11,655 条 `reposition`**（`action_index = 196 + from*7 + to` 已映射），当前被白名单排除；
   扩成 10 类 type CE（或给 Move 段单独一个 move CE）就能让 196..244 参与训练，
   从根上消除"未监督自由度"。改动点在 `hsbg/az/train/bc_aux.py` 的
   `DEFAULT_BC_ACTION_TYPES / BC_TYPE_CLASSES / bc_type_ids` 与对应测试。
2. **或者（补丁式）对 Move logits 做定向正则**：`MSE(move_logits_θ, move_logits_init)`
   或对"Move 概率 > 白名单概率"加 margin；不要用全 245 KL（§5.2 已证伪）。
3. **KL 预算写进门限**：把 `--max-kl` 用 0.2，超过就停；每 100 步跑 16–48 局
   `quality_monitor` 小面板（tier / strength_ratio / moves_per_turn / top4）。
4. **正式预算（在 1/2 修好后）**：200k 样本 × 1 epoch（≈780 步 @ batch 256）、
   `lr 3e-5 ~ 1e-4`、`batch 256`、clip 1.0、bf16、`--preserve-rl 1`；
   class-balance 先用 0（忠实模仿）并对照 1（tier 优先），两者都看质量面板而不是只看 CE。
5. **通过质量门后再接 PPO**：`--checkpoint runs/bc_pretrain/model.pt --anchor-beta 0.1`；
   若 BC 起点仍有 Move 漂移，先用 100–200 步 PPO（`--anchor-beta 0.3`）修回来再放开。

一句话：**BC 能修 tier 锁，但修不了强度，而且是在当前 loss 下用 Move 漂移换来的；
先把 Move 纳入监督，再谈"200k 正式预算"。**

> **§9 已按本节第 1/2 条做了 A/B/C（+D/E/F）实验**：`reposition` 第 10 类能显著降低
> BC holdout 上的 Move 概率质量（20.9% -> 5.8%），但自对弈强度/胜率仍崩，且 10 类损失
> 本身会让其它头变差；锚定系数 0.1 过强。**结论仍是不建议用本轮 BC 权重做 s11 起点**，
> 详见 §9。

## 8. 复现与文件

| 文件 | 作用 |
|---|---|
| `scripts/bc_pretrain.py` | 阶段 A 主脚本（本文件所有数字的来源） |
| `tests/test_bc_pretrain.py` | ① 3 步 loss 下降 ② checkpoint -> `load_checkpoint` + `PPOEvaluator` ③ `--from-scratch` ④ holdout 不重叠 ⑤ KL 上报 |
| `runs/bc_pretrain/` | 短跑 checkpoint + `report.json`（loss/eval 曲线、KL） |
| `runs/bc_pretrain_lr0/` | lr=0 对照（验证存盘链路逐位一致） |
| `runs/bc_pretrain_lr2e5/`、`runs/bc_pretrain_nat/`、`runs/bc_pretrain_anchor/` | §4.2 的各组消融 checkpoint |
| `runs/quality/{s8b,bc_pretrain,bc_lr2e5,bc_nat,bc_anchor_b1,noise1e3}_g48.json` | §4.2 的 48 局质量面板原始 JSON |
| `tests/test_bc_move_supervision.py` | §9 Move 监督单测（reposition 纳入 / 关闭逐位等价 / Move 锚定 / 10 类兼容） |
| `runs/bc_move{A..F}/` | §9 的 A/B/C（+D/E/F）checkpoint + `report.json` |
| `runs/quality/move_{s8b,A,B,C,D,E,F}_g48.json` | §9 的 48 局质量面板（`--seed-base 520000`） |
| `runs/quality/move_holdout_diag.json` | §9 的 BC holdout Move 概率质量诊断 |

```bash
# 单测
python -m pytest tests/test_bc_pretrain.py tests/test_bc_move_supervision.py -q

# 质量面板（每个 checkpoint 一次）
PYTHONPATH=rust/python:. python scripts/quality_monitor.py \
    --checkpoint runs/bc_pretrain/model.pt --device cuda:7 \
    --games 48 --seed-base 520000 --out runs/quality/bc_pretrain_g48.json
```

## 9. Move 监督修复实验（`reposition` 第 10 类 + Move 锚定，A/B/C/D/E/F）

§7 的第 1/2 条建议已实现并做了完整 A/B 对照。**结论先行：Move 监督在 BC holdout 上
有效（Move 概率质量 20.9% -> 5.8%，logits 量级 36 -> 13），但在自对弈状态里压不住
Move 选择，强度仍崩；A/B/C 三组全部不通过质量门，补充的 D/E/F 也不通过。本轮 BC
权重不建议作为 s11 起点。**

### 9.1 实现（两个开关都默认关闭；关闭时与历史 9 类实现逐位等价）

`hsbg/az/train/bc_aux.py`：

- 新增第 10 类 `reposition`：`BC_REPOSITION_TYPE` / `BC_ACTION_TYPES_WITH_REPOSITION` /
  `N_BC_TYPES_WITH_REPOSITION` / `BC_MOVE_SLICE` / `bc_action_types()`（L123–L147）。
  默认 `DEFAULT_BC_ACTION_TYPES` 仍是 9 类，`BC_STATIC_TYPE_IDS` / `N_BC_TYPES` 未动。
- `bc_type_ids`（L958）：样本的 `action_types` 含 `reposition` 时，Move 段 196..244
  整体映射为第 10 类；否则保持历史 `-1`。
- `bc_obs_batch`（L1113–L1125）：启用时按 `board_len` 重建**近似合法换位**
  （from/to 都在棋盘内且 `from != to`，与引擎 `legal_mask` 的 move 段一致）写入
  `action_mask`；关闭时不写（Move 位全 False，除真实动作）。
- `bc_type_logits` / `bc_hier_loss` 新增 `n_types`（默认 9；启用时 10），
  log-sum-exp 聚合 CE（L1256、L1348）。
- `--bc-class-weight` 机制沿用 `parse_bc_class_weights(spec, action_types)`：
  开关打开后可写 `"reposition=2"`；默认 9 类时仍拒绝该名字。

`scripts/bc_pretrain.py`：

- 新增 `--bc-include-reposition {0,1}`（默认 0）、`--bc-class-weight`（默认空）、
  `--bc-move-anchor-coef`（默认 0，L503–L512）。
- Move 锚定 `_move_anchor_mse`（L231）：`coef * MSE(move_logits_θ, move_logits_init)`，
  只取 196..244，只在 `action_mask` 的 Move 候选位上求均值（避免 `-1e9` 掩码值）；
  teacher = 加载时冻结的权重副本。**`MSE(θ,θ_init)` 在 init 处梯度为 0，所以训练第 1 步
  更新与关闭锚定时逐位相同，从第 2 步开始生效**（单测覆盖）。
- 训练循环加入锚定项与 `move_anchor` 曲线（L746–L750）；checkpoint meta / report 记录
  `bc_include_reposition / bc_n_types / bc_class_weight / bc_move_anchor_coef /
  bc_move_anchor_last`（L843–L901）。

`tests/test_bc_move_supervision.py`（6 个测试）：① reposition 样本纳入 + class-weight；
② 关闭开关逐位等价（数组字段 + `bc_obs_batch` + 9 类 loss + CLI 存盘 checkpoint）；
③ Move 锚定在 1 步 / 50 步短训后 Move logits 漂移更小；④ 10 类路径与 9 类数据兼容。

**逐位等价证据**：A 组（不加任何新开关）的 200 步 loss 曲线、holdout CE、KL 与历史
`runs/bc_pretrain` **完全相同**（`runs/bc_moveA/report.json` vs `runs/bc_pretrain/report.json`），
48 局面板也与 `runs/quality/s8b_g48.json` 相同（top4 95.8% / 809 / 2.41）。

### 9.2 配置与训练数字

统一：`--init runs/az_entity_s8b/model.pt --limit 20000 --epochs 4 --steps 200
--batch 256 --eval-batch 512 --device cuda:7`；A/B/C 用 `--lr 1e-4`（与 §4 同口径），
D/E 用 `--lr 2e-5`（§4 里最好的 BC 预算）。

| 组 | 额外参数 |
|---|---|
| A（现状） | 无（9 类，无 Move 监督） |
| B | `--bc-include-reposition 1` |
| C | B + `--bc-move-anchor-coef 0.1` |
| D（补充） | B + `--lr 2e-5` |
| E（补充） | B + `--lr 2e-5 --bc-move-anchor-coef 0.01` |
| F（补充） | B + `--bc-move-anchor-coef 0.01` |

| 组 | n_types | holdout type CE | type acc | KL(pre‖post) | Move 概率质量¹ | Move argmax¹ | 末步 move_mse |
|---|---:|---:|---:|---:|---:|---:|---:|
| s8b（起点） | 9 | 1.6158 | 33.7% | 0 | 3.2% | 3.4% | — |
| A | 9 | 1.5160 | 39.6% | 1.004 | **20.9%** | 20.5% | — |
| B | 10 | 1.5344² | 31.9% | 1.537 | **5.8%** | 2.6% | — |
| C | 10 | 1.6123² | 36.0% | 0.907 | 9.0% | 6.6% | 5.03 |
| D | 10 | 1.7547² | 28.9% | 0.658 | **1.8%** | 0.6% | — |
| E | 10 | 1.7225² | 29.8% | 0.593 | 3.4% | 1.8% | 15.10 |
| F | 10 | 1.5130² | 38.6% | 1.006 | 4.8% | 2.7% | 16.37 |

¹ 在 BC holdout（1000 条）上，用“BC 候选动作 + 重建的合法换位”做 masked softmax，
统计 196..244 的概率和 / argmax 落在 Move 的比例（`runs/quality/move_holdout_diag.json`）。
该指标是**回放状态**上的 in-distribution 指标，不等于自对弈状态里的 Move 率（见 §9.4）。

² 10 类 CE 与 9 类 CE 的类别数不同，**不同 n_types 之间的 CE 不可直接比较**；同 n_types
的 B/C/D/E/F 可比。

### 9.3 质量面板（`scripts/quality_monitor.py --games 48 --seed-base 520000`，`move_guard=0`）

| 组 | mean_rank | top4 | win | 出局强度 p50 | moves/turn | tier p50 t9/t12/t15 | tier≥5 t12 | 强度比 t12 / t15 | 门 |
|---|---:|---:|---:|---:|---:|---|---:|---:|---|
| **s8b 原权重** | 1.69 | **95.8%** | 60.4% | **809** | **2.41** | 4 / 4 / 5 | 25.0% | **0.142 / 0.034** | — |
| **A**（9 类，现状） | 5.75 | 29.2% | 8.3% | 93 | 17.28 | 4 / **5** / 5 | **57.8%** | 0.031 / 0.005 | ✗ |
| **B**（+reposition） | 6.25 | 20.8% | 0.0% | 115.5 | 14.93 | 4 / 4.5 / 4 | 50.0% | 0.029 / 0.005 | ✗ |
| **C**（B+anchor 0.1） | 6.85 | 14.6% | 2.1% | 22 | **5.28** | 4 / 4 / 4 | 8.9% | 0.0045 / 0.0008 | ✗ |
| D（B+lr 2e-5） | 5.81 | 33.3% | 2.1% | 115 | 21.09 | 3 / 2.5 / 2 | 11.4% | 0.028 / 0.005 | ✗ |
| E（D+anchor 0.01） | 4.90 | 47.9% | 6.3% | 220 | 21.37 | 3 / 3 / 4 | 11.4% | 0.052 / 0.010 | ✗ |
| F（B+anchor 0.01） | 4.79 | 41.7% | 18.8% | 118 | 13.26 | 4 / 5 / 5 | **56.5%** | 0.053 / 0.008 | ✗ |
| 参考：9 类 BC @ lr 2e-5（§4.2） | 3.23 | 72.9% | 33.3% | 417 | 4.71 | 4 / 4 / 5 | 46.8% | 0.112 / 0.026 | ✗ |

判据：`top4 ≥ 85%` **且** `出局强度 p50 ≥ 600` **且** `tier≥5@t12 ≥ 45%`。
**8 行里没有一行同时满足**；最好的补充组 F 也只有 top4 41.7% / 强度 118。

### 9.4 结论与下一步

1. **reposition 监督确实修好了“Move 族完全不受监督”**：BC holdout 上 Move 概率质量
   20.9% -> 5.8%（B）、Move logits 平均幅度 36 -> 13；且 B/F 在“人类确实换位”的
   样本上 Move 概率（19.8% / 20.1%）明显高于非换位样本（5.2% / 4.2%），说明类型语义学到了。
2. **但它不能把强度修回来**：B 的 moves/turn 只从 17.3 降到 14.9、强度 93 -> 116、top4
   29.2% -> 20.8%；C 把 moves 压到 5.3，却把 tier≥5@t12 打到 8.9%、强度 22。原因是
   BC 的**部分观测状态分布 ≠ 自对弈输入分布**：Move logits 是棋盘 token 的双线性
   `hb_i·hb_j`，在回放状态（大量 0/静态卡面字段）上被压小，不代表自对弈状态（真实
   属性、buff、满场 7 张）上的量级也被压小。D 组最能说明这一点：holdout Move 概率
   只有 1.8%，实际却 **21.1 moves/turn**。
3. **10 类损失本身有副作用**：把 36 量级的 Move logits 拉进共享 trunk 的 CE 梯度后，
   即使 lr 2e-5 也把其它头带坏（D type acc 28.9%、tier 锁 2；同预算的 9 类参考是
   72.9% top4 / tier≥5 46.8%）。`anchor 0.1` 过强（C）；`0.01`（E/F）能缓解，
   但强度仍只有 118–220。
4. **是否可用于 s11 起点：不建议。** 本轮任何 BC 权重（A–F）都不满足质量门；s11 应
   继续从 s10/主线 checkpoint 出发，BC 只保留现有 `bc_coef=0.004` 辅助正则，并保持
   `--move-guard 1 --move-cap 3` 的防刷机制。
5. 如果还要继续 BC warm-start，应优先解决**状态分布**而不是再调 loss 权重，候选顺序：
   a. 在**自对弈状态**上做 Move 概率质量/margin 正则（在线，和 PPO 同分布）；
   b. 用**参数空间**约束（冻结或低 lr 的 board-token / move 相关参数），而不是在回放
      状态上做 logit MSE；
   c. 对 Move logits 做尺度归一化（RMS/温度）后再进 type CE，避免 36 量级 logits
      主导共享 trunk 梯度；
   d. 更小预算（KL≤0.2，约 40–60 步 @2e-5）+ 48 局质量门禁；但按 §4.2 的跷跷板关系，
      tier 收益会很小，预期仍过不了 `top4≥85% & 强度≥600`。

复现：

```bash
# B 组
PYTHONPATH=rust/python:. python scripts/bc_pretrain.py \
    --init runs/az_entity_s8b/model.pt --limit 20000 --epochs 4 --steps 200 \
    --batch 256 --eval-batch 512 --device cuda:7 --lr 1e-4 \
    --bc-include-reposition 1 --out runs/bc_moveB

# C 组（B + Move 段 MSE 锚定）
PYTHONPATH=rust/python:. python scripts/bc_pretrain.py \
    --init runs/az_entity_s8b/model.pt --limit 20000 --epochs 4 --steps 200 \
    --batch 256 --eval-batch 512 --device cuda:7 --lr 1e-4 \
    --bc-include-reposition 1 --bc-move-anchor-coef 0.1 --out runs/bc_moveC

# 质量面板
PYTHONPATH=rust/python:. python scripts/quality_monitor.py \
    --checkpoint runs/bc_moveB/model.pt --device cuda:7 \
    --games 48 --seed-base 520000 --out runs/quality/move_B_g48.json
```
