# 真实人类对局 BC 辅助正则（形态 A）

> 状态：**已接入 PPO，默认关闭**。`bc_coef=0` 时不会加载数据、不编码、不采样、不算 loss，
> 训练路径与旧版本逐位等价。本文记录数据来源、过滤/编码假设、权重策略、启用/回退方法与
> 失败判据。实现：`hsbg/az/train/bc_aux.py`、`hsbg/az/train/ppo.py`、
> `hsbg/az/train/ppo_trainer.py`、`scripts/train_entity_sync.py`；单测：
> `tests/test_bc_aux.py`。

---

## 1. 目标与形态

主目标是 PPO clipped surrogate（+ 可选 MCTS π 辅助 CE / 动作序列辅助 BCE）。
BC 只作为**小权重辅助交叉熵**加入**同一次 backward**：

```text
total = ppo_policy + value_coef * value + pi_coef * aux_pi
        + seq_coef * seq_bce
        + bc_coef * bc_ce        # ← 本模块；默认 bc_coef=0
```

它**不改变**主目标、不替换自对弈数据、不单独 step；只提供“人类在相似状态下更常选
哪些动作”的先验，缓解冷启动/策略坍缩。形态 A 的硬约束：

- 默认 `bc_coef=0` 时零影响（权重逐位相同，stats/日志不出现 `bc_*`）；
- BC 系数可 ramp（与 `seq_coef_ramp` 同一实现/语法）；
- 加载失败/池为空只 warn 一次并自动 `bc_coef=0`，不崩训练；
- 数据/编码/损失均为纯函数，可单测（不依赖引擎）。

---

## 2. 数据来源与质量

| 项 | 值 |
|---|---|
| 文件 | `data/firestone_bc/bc_samples.jsonl.gz`（gzip JSONL，12 MB） |
| 样本 | 308,944 条真实决策（1000 局 Firestone 回放，客户端视角） |
| 字段 | 见 `data/firestone_bc/SCHEMA.md`；实际抽样确认 `action_index` 已映射到 245 动作空间 |
| 动作可映射 | 290,034 / 308,944 = **93.88%** |
| 卡表命中 | 6,009,406 / 6,012,268 = **99.95%**（唯一未命中是 UI 按钮 `BG36_Button_DarkGift`） |
| MMR | 4,009–15,407，中位 6,280 |
| 解析器 | `scripts/firestone_bc_parse.py`（仅标准库） |
| 统计/可行性 | `docs/BC_DATA_FEASIBILITY.md` |

本实现的实际池（默认白名单 + `mmr>=6000`）：

```text
samples = 183,245（过滤前 308,944）
load    ≈ 7–8 s（单进程，含 cards.json 解析）
mmr     6,000–15,407，mean ≈ 7,022
```

类别分布（`load_bc_samples(mmr_min=6000)`，同时是启动日志内容）：

| action_type | 样本 | 占比 |
|---|---:|---:|
| play_minion | 43,081 | 23.51% |
| play_spell | 38,124 | 20.80% |
| sell | 35,228 | 19.22% |
| reroll | 27,662 | 15.10% |
| buy_minion | 15,821 | 8.63% |
| buy_spell | 9,169 | 5.00% |
| end_turn | 7,638 | 4.17% |
| hero_power | 3,472 | 1.89% |
| upgrade | 3,050 | 1.66% |

高频 `play_*` / `sell` 与低频 `upgrade` / `hero_power` 相差 14 倍，因此损失必须做
class-balanced（见 §5），不能直接按样本均匀平均。

数据质量风险（来自解析器与可行性文档，BC 侧仍成立）：

- 客户端事件不是引擎 `state_json`，实体 id/触发顺序不可逐位复现；
- 商店由 Bob 控制的 zone 1/6 卡重建，买入目标命中 99.3%/96.3%，仍有 1–4% 槽位错位；
- 17.2% 的 `play_minion` 在 block start 时卡已不在手牌（hand slot 缺失）→ 这类
  `action_index=null` 已被过滤；
- 换位（`reposition`）、冻结（toggle 语义）、黑暗赠礼（礼物卡未知）、三连（option 未解析）
  标签噪声大，**不纳入白名单**；
- 回放没有最终名次，只有 MMR；不能按 placement 加权（本实现用 MMR 权重）。

---

## 3. 白名单与排除原因

默认白名单（`DEFAULT_BC_ACTION_TYPES`，顺序即类别 id）：

```text
sell, reroll, buy_minion, buy_spell, play_spell,
play_minion, upgrade, hero_power, end_turn
```

纳入理由：动作类型/槽位在回放中可重建，且状态覆盖高（商店 97.78%、gold/tier/health
缺失 0.15%、手牌位 99.98% 对法术、82.8% 对随从）。`play_minion` 只保留
`action_index` 存在的 82.8% 子集。

排除：

| 动作 | 样本 | 排除原因 |
|---|---:|---|
| reposition | 11,655 | `MOVE_MINION` 混入卡牌效果移动；槽位/语义噪声大 |
| dark_gift | 2,862 | 礼物卡未知，只能监督“按按钮” |
| freeze | 2,669 | 回放只看到 toggle，无法区分 Freeze/Unfreeze |
| triple | 5,734 | `action_index=null`（选项未解析） |
| activate | — | 回放没有单独标记 |
| magnetize | — | BG 无磁力 |

另外过滤：`action_index` 非整数/越界/`null`、`mmr` 缺失或 `< bc_mmr_min`、白名单外类型。

---

## 4. 部分观测编码（3227 floats + 124 cards）

`bc_obs_batch(samples, layout=BC_OBS_LAYOUT)` 把每条 BC 样本编码成我们固定观测的
**部分观测**。布局偏移全部来自 `hsbg/env/obs_std.py`（不硬编码偏移）；`BC_OBS_LAYOUT`
明确列出实际用到的切片，单测检查 features 叶子切片与 card 块均不重叠、不越界。

已知槽位（mask True）：

| 块 | 填充 |
|---|---|
| global | turn/20、health/40、armor/20、gold/10、tier/6、board_len/7、hand_len/10、alive=1、me_alive=1（缺失字段填 0 + mask False） |
| board | 7 × `MINION_F`：present、atk/hp/max_hp（卡表基础值 /10）、tier/6、golden、keywords/races 位 |
| hand | 10 × `ITEM_F`：present、is_minion、cost=0（引擎手牌语义）、随从/法术子块 |
| shop | 8 × `ITEM_F`：present、is_minion、cost/5（卡表基础价）、随从/法术子块；第 7 槽是酒馆法术槽 |
| cards | hero(1)、board(7)、hand(10)、shop(8) 的卡表下标+1 |

未知槽位/字段（mask False，值 0）：

- 对手 7×9 摘要、对手 7×7×31 上局战团、pending/choices/quests/secrets/trinkets、
  hero power 卡、法术 `data`、大多数 global 标量（upgrade/refresh price、deity、
  trinket 等）；
- 未观测到的 board/hand/shop 槽；
- 英雄皮肤归一失败时的 hero（约 0.6% 样本，3 个基础英雄不在卡表）。

**近似动作掩码**：`bc_obs_batch` 同时返回 `action_mask[n,245]`，由部分观测推断：

- EndTurn 恒合法；HeroPower(slot0) 恒合法；Upgrade 在 tier<6 时；Refresh 在 gold>=1 时；
- Buy(8+slot)：商店该槽有卡，且 gold 已知时不排除买不起的槽（基础价近似）；
- Sell(16+slot)：棋盘该槽有随从；
- Play{hand,pos}：手牌该槽有卡；法术仅 pos 0；随从按 `board_len+1` 个插入位；
- 最后**强制把真实动作加入 mask**（保证 CE 可算）。

这**不是**引擎 `legal_mask` 的精确重建，而是“白名单动作族内的条件候选集”。它避免
BC 梯度去压低 freeze/dark_gift 等未标注动作，但也使 CE 的分母小于真实合法动作数
（实测平均约 34 个候选，均匀参考 CE ≈ ln(34) ≈ 3.5）。

### 部分观测假设与风险

1. **对手不可见**：回放只有记录者视角，对手手牌/金币/酒馆全程隐藏；BC 只学单边策略。
   模型看到的是“对手块全 0 + mask False”，与引擎自对弈的完整观测分布不同，因此只能
   作为小权重正则，不能当主数据。
2. **商店 RNG 不可复现**：回放没有刷新序列/随机种子，同一商店在引擎里不能逐位复现；
   BC 只提供“看到这类商店时人类怎么选”的先验。
3. **tag 噪声**：客户端 tag 与引擎不完全一致；商店槽位 1–4% 错位、买入目标 0.7%/3.7%
   未命中、手牌位 17% 缺失（已过滤）。
4. **静态卡表近似**：回放没有每个随从的实时 atk/hp/关键词，本实现用卡表基础值填充；
   实际 buff 后的数值不可见，模型可能学到“基础身材”偏差。
5. **法术槽/价格**：shop 第 7 槽是酒馆法术；cost 用卡表基础价，实际折扣/动态价格不可见。
6. **英雄皮肤**：`hero` 是皮肤 id，按 `_SKIN_[A-Z0-9]+` 去后缀映射到基础英雄；
   3 个基础英雄缺失（约 1,803/308,944 样本）时 hero=0、mask False。
7. **动作掩码不是 legal_mask**：见上；BC 是条件辅助目标，不用于评测/搜索。

---

## 5. 权重策略

`bc_ce_loss(logits, target_action, weights, mask, class_ids, class_counts)`：

```text
per_i   = CE(logits_i, target_i)                  # 245 类，非法位已填 -1e30
w_i     = mmr_weight_i * class_weight[class_i]    # 样本权重
loss    = Σ_{mask_i=True} w_i * per_i / Σ_{mask_i=True} w_i
```

### 5.1 class-balanced

按**动作类别频率倒数**并归一：

```text
inv_c      = 1 / count_c
class_w_c  = inv_c / mean_{c: count_c>0}(inv_c)
```

归一化到“每个类别总权重相同、类别权重均值=1”，保持损失量级与未加权 CE 可比。
例如 `count=[9,1]` -> `class_w=[0.2,1.8]`。`count` 默认用**全池**计数（`class_counts`），
不是每个 minibatch 的计数，避免小 batch 抖动。

### 5.2 MMR 权重

- 默认：`mmr >= bc_mmr_min(6000)` -> **1.0**；低于下限直接丢弃；
- 可选线性增强（`bc_mmr_boost > 1`）：在 `[6000, 8000]` 上从 1.0 线性升到
  `bc_mmr_boost`，`>=8000` 保持该值。CLI：`--bc-mmr-boost 1.5`。
- 没有 placement 字段，不能按名次加权；MMR 是唯一可用的质量代理。

### 5.3 样本 mask

`load_bc_samples` 已过滤非法/缺失；`bc_ce_loss` 的 `mask` 参数用于额外屏蔽（本路径
传 None/全 True）。全 mask 掉或权重全 0 时返回 0（保留计算图，不产生 NaN）。

---

## 6. PPO 接入细节

### 6.1 配置（`PPOConfig`）

| 字段 | 默认 | 说明 |
|---|---|---|
| `bc_coef` | 0.0 | BC CE 权重；0=关闭 |
| `bc_coef_ramp` | `""` | 与 `seq_coef_ramp` 同语法，如 `0.005@0,0.02@0.3` |
| `bc_mmr_min` | 6000 | MMR 下限 |
| `bc_mmr_boost` | 1.0 | 6000–8000 线性增强上限（1=关闭） |
| `bc_samples_path` | `""` | 空=仓库默认 `data/firestone_bc/bc_samples.jsonl.gz` |
| `bc_batch` | 256 | 每个 PPO minibatch 抽取/编码的 BC 条数 |

### 6.2 训练流程

1. `PPOTrainer.__init__`：`bc_enabled`（常数系数>0 或 ramp 有正系数）时预加载一次
   `BCSamples`（CLI 预加载后通过 `bc_pool=` 注入，避免重复读 12 MB）；失败/空池
   **warn 一次**，自动 `bc_coef=0, bc_coef_ramp=""`；
2. `train_ppo` 每个 minibatch：`rng.choice(池, min(bc_batch, n_pool))` -> `bc_obs_batch`
   -> 额外一次 `forward_model` -> `bc_ce_loss` -> `total += bc_coef * bc_ce`；
3. 与 PPO/seq 共用同一次 `backward()`，不单独 `optimizer.step()`；
4. stats 增加 `bc_loss` / `bc_coef` / `bc_samples` / `bc_pool_samples` / `bc_pool`
   （仅 bc 真正启用时）；`[ppo] step/epoch` 与 `[iter i]` 日志追加
   `bc=... bc_coef=... bc_samples=...`；
5. `bc_coef=0`：不加载、不采样、不 forward、不出 stats 字段；`history.jsonl` 的
   `config` 回显也去掉 6 个 bc 键，保持旧结构。

### 6.3 ramp

`parse_bc_coef_ramp(spec)` 直接复用 `seq_aux.parse_coef_ramp`（同一语法/校验/排序）。
CLI 按**累计 decisions** 的进度求值后写回 `config.bc_coef`（与 seq ramp 同一进度口径）：

```text
progress = min(1, cum_decisions / total_decisions)
bc_coef  = linear_interp(points, progress)
```

`total_decisions` 取 `--stop-at-decisions`（>0），否则 30M（与 seq 的缺省一致）。

---

## 7. 如何开启 / 回退

### 7.1 默认（关闭，零影响）

```bash
python scripts/train_entity_sync.py ...   # 不传任何 --bc-*
```

或显式：

```bash
python scripts/train_entity_sync.py ... --bc-coef 0
```

两者模型权重/PPO 指标应逐位一致（见 §8 冒烟）。

### 7.2 从 s5 最佳 ckpt 起的新阶段（建议）

**不要中断正在跑的 s5**。等 s5 结束/到阶段边界后，从最佳 ckpt 起新阶段：

```bash
python scripts/train_entity_sync.py \
  --checkpoint runs/az_entity_s5/model.pt \
  --arch entity --device cuda:7 \
  --processes 1 --gpus "" --workers 1 --sims 0 \
  --bc-coef 0.01 \
  --bc-coef-ramp 0.005@0,0.01@0.2 \
  --bc-mmr-min 6000 --bc-mmr-boost 1.0 \
  --bc-samples data/firestone_bc/bc_samples.jsonl.gz \
  --bc-batch 256 \
  ...（其余沿用 stage 的超参）
```

建议初值：**从零/tiny 冷启动 `bc_coef=0.01`；从 s5 等已训练 ckpt 起用
`bc_coef=5e-4–1e-3`**，`bc_batch=256`，`bc_mmr_min=6000`。已训练 ckpt 的
`bc_loss` 初始可达 14–18（部分观测 OOD + 人类与当前策略差异），0.01 可能压过 PPO；
先从 `5e-4` 观察 `bc_loss` 与 C0 eval，若稳定再升到 `0.005–0.01`。ramp 让 BC 在阶段
早期略强、后期让位给 PPO：

```text
--bc-coef-ramp 0.01@0,0.01@0.3,0.005@1.0
```

### 7.3 回退

- 运行时：`--bc-coef 0`（不加载、零影响）；
- 已启动的训练：不要热改；下一个阶段用 `bc_coef=0` 从 ckpt 重启；
- 数据缺失：保持 `bc_coef=0`；若误开，加载失败会自动关闭并 warn。

---

## 8. 冒烟数字（本机）

> 环境：`/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python`（torch 2.6 / cu124）。
> 未触碰 s5（`/tmp/s5c_train.log`，out=`runs/az_entity_s5`）。

### 8.1 CPU tiny（`--bc-coef 0.01`，2 iter，`bc_batch=64`）

```text
[bc] 真实人类 BC 池: samples=183245 mmr>=6000 load=7.2s
[bc] class_counts={"sell":35228,...}
[ppo] epoch 1/1 ... bc=3.2246 bc_coef=0.01 bc_samples=64
[iter 0] ... bc=3.2246 bc_coef=0.01 bc_samples=64
[ppo] epoch 1/1 ... bc=3.4528 bc_coef=0.01 bc_samples=64
[iter 1] ... bc=3.4528 bc_coef=0.01 bc_samples=64
```

12 iter（`bc_batch=128`）的 `bc_loss` 从 **3.345** 降到 **3.10–3.29**（单步/小 batch
有抖动；趋势向下）。作为参考：动作掩码平均约 34 个候选，均匀策略 CE ≈ ln(34) ≈ 3.53；
模型初始 CE 3.35 已低于该参考。任务描述中的 `ln(9)` 对应“9 个动作类别”，实际 CE 是
245 动作 + 槽位掩码，参考值应以候选槽位数为准。

### 8.2 等价性（`bc_coef=0`）

两次 CPU tiny 运行：A 显式 `--bc-coef 0`，B 不传 BC 参数；同 `--seed 0`、同 batch：

- `model.pt` SHA256 完全相同：
  `2cd378e27c8bdcc9c9cc7e483f743f902726903c9b2f26ef6290c1a14c48881f`
- `history.jsonl` 去掉墙钟字段（`seconds`/`profile`/`collect.elapsed_s`）与
  `args.out` 后逐项相同；PPO `total/policy/value/entropy/kl` 输出行逐字相同。

### 8.3 GPU（cuda:7）

tiny（1 iter）：

```text
[bc] 真实人类 BC 池: samples=183245 mmr>=6000 load=7.5s
[ppo] step 0 total=1.0336 ... bc=3.1946 bc_coef=0.01
[ppo] epoch 1/2 ... bc=3.1720 bc_coef=0.01 bc_samples=64
[ppo] epoch 2/2 ... bc=3.3803 bc_coef=0.01 bc_samples=64
[iter 0] ... bc=3.2761 bc_coef=0.01 bc_samples=64
```

**从 s5 ckpt 起（entity，cuda:7，1 iter）**：`bc_loss` 初始约 **14–18**（不是 2–4）。
原因：s5 策略在“部分观测（对手全 0、商店/手牌只填可见槽）”上高度自信，且人类动作与
当前策略差异大；动作掩码已把 CE 从全 245 掩码时的 ~217 降到 ~14。
**结论：从已训练 ckpt 启用时不要直接用 0.01**；建议 `bc_coef=5e-4…1e-3` 起步，
或先跑 20–50 iter 观察，确认 C0 eval 不退化后再升到 0.005–0.01。
从零/tiny 冷启动则 0.01 可用（§8.1）。

### 8.4 测试

```text
# 默认环境（/tmp/hsbrsim_clone/rust/python 的旧 _core，缺 RustCollector）
# 会先失败在 8 个既有 rust-collector/mirror 测试；与本改动无关。
# 用仓库自身引擎跑全量：
PYTHONPATH=$PWD/rust/python python -m pytest tests -q -p no:warnings
# => 全部通过（lastfailed={}；仅 skip 既有引擎相关用例）
```

`tests/test_bc_aux.py` 覆盖：加载/白名单/缺失字段、MMR 权重、class-balanced、
切片不重叠、CE 手算、`bc_coef=0` 逐位等价、`bc_coef>0` stats。

---

## 9. 期望收益与失败判据

### 期望收益

- **冷启动/坍缩**：PPO 在对手强/奖励稀疏时策略熵坍缩到少数动作；BC 提供人类动作先验，
  提升动作多样性/合法率；
- **槽位选择**：buy/sell/play 的槽位由 BC 监督（真正的人类偏好），比纯 PPO 随机探索更快；
- **低频动作**：class-balanced 让 upgrade/hero_power 不被高频 play/sell 淹没；
- **与搜索互补**：BC 不替代 MCTS/自对弈，只在小权重下稳定早期策略。

### 失败判据（任一出现即回退 `bc_coef=0`）

1. `bc_loss` 长期不降（例如 5 个 iteration 内没有下降趋势）或 NaN；
2. `illegal_prob_max > 0`（BC 动作掩码/target 不一致会直接暴露）；
3. C0 eval 的 `mean_rank` 相对 baseline 变差超过 ~0.1，或 `top4/win` 显著下降；
4. `approx_kl` / `clip_frac` 异常升高（BC 与 PPO 梯度冲突）；
5. entropy 异常塌缩到低于 baseline 的一半；
6. 训练吞吐下降超过可接受范围（BC 编码/前向额外开销；CPU 实测 encode 256≈0.05s，
   额外 forward 约 +15–25% PPO 时间，GPU 上占比更低）。

### 建议启用时机

- **不要在 s5 运行中热改**；等 s5 结束，从最佳 ckpt（按 C0 mean_rank/top4）起**新阶段**；
- 从已训练 ckpt 起：`bc_coef=5e-4–1e-3` + `bc_batch=256` 跑 20–50 iter，观察 `bc_loss` 与 eval；
- 从零/tiny：`bc_coef=0.01` 起步；
- 若有效，再按 ramp 提到 0.005–0.01；若无效，直接回退，不影响已有 ckpt。

---

## 10. 复现命令

```bash
# 单测
python -m pytest tests/test_bc_aux.py -q -p no:warnings

# CPU tiny 冒烟（1–2 iter）
python scripts/train_entity_sync.py --arch tiny --device cpu \
  --games 1 --sims 0 --iterations 2 --minutes 5 \
  --max-steps 2000 --max-actions-per-turn 10 \
  --batch-size 8 --minibatch 16 --epochs 1 \
  --workers 1 --processes 1 \
  --bc-coef 0.01 --bc-batch 64 \
  --out /tmp/bc_smoke_cpu

# 等价性（bc_coef=0）
python scripts/train_entity_sync.py ... --bc-coef 0 --out /tmp/bc_eq_a
python scripts/train_entity_sync.py ...              --out /tmp/bc_eq_b
sha256sum /tmp/bc_eq_a/model.pt /tmp/bc_eq_b/model.pt

# cuda:7 1 iter（空闲卡）
python scripts/train_entity_sync.py --arch tiny --device cuda:7 \
  --games 1 --sims 0 --iterations 1 --minutes 5 \
  --max-steps 2000 --max-actions-per-turn 10 \
  --batch-size 8 --minibatch 16 --epochs 1 \
  --workers 1 --processes 1 \
  --bc-coef 0.01 --bc-batch 64 --out /tmp/bc_smoke_cuda7
```
