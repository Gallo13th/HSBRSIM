# COMPOUND_TEACHER — 复利教师：CompoundPolicy → BC 标签数据集

> 一句话：把「会买放大器」的手写教师蒸馏成 BC 标签：`data/scaling/compound_bc/*.npz`
> （**432 局 / 196,840 决策 / 1.3GB**，3 组）。生成器 `scripts/gen_compound_bc.py`，
> 教师 `scripts/compound_script.py::CompoundPolicy`，单测 `tests/test_compound_script.py`（9 passed）。
> 2026-11-01 17:38–17:41，三组 **2m46s** / 12 workers / 纯 CPU。
> 上游：[COMPOUND_SCRIPT.md](COMPOUND_SCRIPT.md)（教师规则/环境上限）· [COMPOUND_INCOME.md](COMPOUND_INCOME.md)（收入机制）。

## 0. 结论先行

1. 教师 vs 模型（同沙盒口径）：放大器 **8.26–9.14 张/局、出现率 100%** vs **0.375 张/局、20.8%**
   （`runs/compound_script/amps_spell.json`，24 局）；t15 Σ（保留局）p50 **2330/2680/3027** vs 模型 1478。
2. 动作合法率 **1.000**（逐条在记录时刻 mask 上校验）；obs 3227+124、动作 245 与训练同编码
   → BC 可直接 masked CE，无需适配层。
3. 只保留 `sigma_t15 ≥ 1500` 的局（筛掉 29–48%）；`ep_split` 确定性留 10% 验证集。
4. **金色 1.4–1.5/局（<3 目标）**：教师局内 corr(goldens, Σ)=0.06–0.22，`triple_first` 只 +0.04
   且 Σ −6.5% → **金色不是当前瓶颈**（§6–§7）；`--gold-cap 0` 收入 +41% 但 Σ 不变（§6）。

## 1. 生成方法
```bash
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python; export PYTHONPATH=rust/python:.
$PY scripts/gen_compound_bc.py --games 240 --workers 12 --seed0 880000 \
    --keep-sigma 1500 --gold-cap 99 --out-dir data/scaling/compound_bc
```

- **沙盒** `hsbg.az.train.economy_sandbox`：无对手/战斗/血量/排名，15 回合只 recruit。
- **教师** `CompoundPolicy`：放大器出现即买 > 载体 > 酒馆 buff > 法术全打载体 > 三连
  （规则见 COMPOUND_SCRIPT.md §3）；每 worker 独立 policy/seed，每回合重置刷新计数。
- **3 组环境**：`s0_fixed30`（fixed 30 金/回合 + action_cap 40）/ `s1_growth_carrier`
  （growth 0.15 + 2 金/载体）/ `s3_growth_buff3`（S1 + action_cap_per_gold 3 + tavern_buff×3）。
- 每组**跑 240 局 → 筛后留 126/136/170 局**；种子 880000 起、worker 间不重叠。

## 2. npz 字段（SoA，三组同 schema；逐字段说明在 `meta_*.json`）

| 字段 | dtype | 含义 |
|---|---|---|
| `features` | float16[N,3227] | obs_std 编码（`--feature-dtype float32` 可换） |
| `cards` / `mask` | int16[N,124] / bool[N,245] | 卡牌块 / 记录时刻合法动作（含 action_cap 掩码） |
| `action` | uint8[N] | 教师动作 0..244（与训练逐位一致） |
| `turn` / `tier` / `gold` | uint8 / uint8 / int16 | 回合 1–15 / tier / 剩余金币 |
| `episode_id` | int32[N] | → 该局在 `ep_*` 数组的行号 |
| `action_kind` | uint8[N] | 0 other/1 buy_amp/2 buy_carrier/3 buy_spell/4 buy_minion/5 play_spell/6 play_minion/7 sell/8 upgrade/9 refresh/10 end_turn/11 pending |
| `is_amp_buy`/`is_carrier_buy`/`is_spell_action` | bool[N] | 该决策买放大器 / 买载体 / 买或打法术 |
| `ep_seed` | int64[E] | 沙盒 seed |
| `ep_sigma_t12` / `ep_sigma_t15` | int32[E] | t12/t15 战团 Σ=Σ(atk+hp) |
| `ep_r12_15` | float32[E] | `sigma_t15 / sigma_t12`（复利形状） |
| `ep_amp_total` / `ep_amp_any` | int16 / bool[E] | 整局放大器购买数 / ≥1 张 |
| `ep_goldens_t15` / `ep_carriers_t15` | int16[E] | t15 场上金色 / 载体数 |
| `ep_spells_t15` / `ep_tavern_buff_t15` | int32[E] | t15 累计施法 / 酒馆 buff 总量 |
| `ep_gold_total_income` / `ep_decisions` | int32[E] | 整局金币收入（Σ/金 分母）/ 该局样本数 |
| `ep_split` | uint8[E] | 0=train / 1=val（合并后每 10 局取 1 局） |

## 3. 加载示例（student-distill 直接用）
```python
import numpy as np
d = np.load('data/scaling/compound_bc/s3_growth_buff3.npz')   # N=80,999 E=170
f, c, m = d['features'], d['cards'], d['mask']        # [N,3227] [N,124] [N,245]
a = d['action'].astype(np.int64); ep = d['episode_id']
s15 = d['ep_sigma_t15'][ep]; is_val = d['ep_split'][ep] == 1
w = (s15 / 1500.0).clip(max=8.0)                      # 可选：按终局 Σ 加权采样
# loss = CE(logits, a)，非法动作先 masked_fill(~m, -inf)；features 喂模型前转 float32
```

## 4. 教师统计（保留局口径；全跑口径见 `meta_*.json` 的 `t15_sigma_all_run`）

| 组 | 跑/留 | 决策(决策/局) | 放大器/局(≥5 局数) | 金色/局 | t15 Σ p50/p90/max | r12_15 p50/p90 | Σ/金 p50 | 全跑 Σ p50 |
|---|---|---|---|---|---|---|---|---|
| s0_fixed30 | 240/126 | 54,457 (432) | **8.85** (116) | 1.46 | 2330 / 4579 / 8,495 | 1.37 / 2.20 | 5.18 | 1618 |
| s1_growth_carrier | 240/136 | 61,384 (451) | **8.26** (120) | 1.39 | 2680 / 5702 / 11,833 | 1.45 / 2.43 | 2.25 | 1795 |
| s3_growth_buff3 | 240/170 | 80,999 (476) | **9.14** (152) | 1.51 | 3027 / 9617 / **37,325** | 1.30 / 2.60 | 2.58 | 2520 |

- 放大器/局 p50/p90/max（S3）= 9/14/18，购买集中在 t8–t14（p50=8–9、p90=14，前 7 回合先铺载体）；
  t15 Σ≥10,000 的局：S0 0 / S1 1 / S3 **16**。
- 动作构成（S3）：play_spell 17.8%、play_minion 15.1%、buy_spell 13.8%、pending 12.9%、
  sell 12.4%、refresh 11.3%、buy_minion 7.2%、end_turn 3.1%、buy_amp 1.9%、buy_carrier 1.7%。

## 5. 与现有模型的差距（同沙盒、同卡表）

| 指标 | 模型/脚本（`amps_spell.json`，24 局） | 教师（S3，保留局） |
|---|---|---|
| 任意放大器 ≥1 的局 | **20.8%** | **100%** |
| 放大器/局 | **0.375** | **9.14** |
| Brann/Titus/Drakkari/Ashen/Gatekeeper（张/局） | 0.083 / 0 / 0 / 0.167 / 0.125 | 2.18 / 1.95 / 1.90 / 1.29 / 1.82 |
| t15 Σ p50 | 1478（spell 基线） | 3027（S0/S1：2330/2680） |
| 金色/局 p50 | 2.0 | 1（p90 3） |
| 施法/局 | 86.6 | 86.7 |

读法：差距不在可购买性/施法次数，而在「**买不买放大器、给不给载体腾格子**」；模型金色来自普通牌堆叠、**不含复利价值**。

## 6. 已知局限（变体已实测，见 §7）

1. **金币不是瓶颈**：`--gold-cap 0` 同种子 120 局把收入 p50 1192→**1684（+41%）**，但 t15 Σ
   全跑 p50 **不变（2358）**、mean −3.5%，Σ/金 2.62→**1.80** → 正式数据保持 gold-cap 99，
   真正的闸门是**动作额度 / 手牌 10 张 / 7 个站位**（同 COMPOUND_INCOME.md §0.3）。
2. **金色上不去**：`triple_first` 同种子只把金色 1.50→**1.54**、t15 Σ 全跑 p50 −6.5%
   （2358→2205）⇒ 简单三连优先级无效，金色复利需要单独机制设计（允许载体攒对子/换位）。
3. Ashen Corruptor 在无战斗沙盒是**死牌**（受伤触发不可达），教师 1.3 张/局是「身材顺带」；
   `pending`（饰品/发现/目标）占 13% 决策，是合法且被 mask 的强制选择，蒸馏建议保留但不作
   「策略偏好」单独分析。
4. 教师只在无对战沙盒成立；回到完整游戏（战斗/血量/排名）动作分布会漂移，这是 student-distill
   要处理的分布迁移。

## 7. 变体（triple-first / gold-cap 0；同种子 120 局，均不影响正式三组）

- `triple_first`：金色 1.50→**1.54**（噪声）、t15 Σ 全跑 p50 2358→**2205（−6.5%）** → 金色不是瓶颈。
- `gold-cap 0`：收入 1192→**1684（+41%）**、t15 Σ 全跑 p50 **不变（2358）**、Σ/金 2.62→**1.80** → 金币不是瓶颈。
- 文件：`s3_growth_buff3_{base120,cap0,triple_first}.npz`；动作效率变体见 §9（roll≤8 是目前最强）。

## 8. 交付给 student-distill 的接口约定

- 起点推荐 `s3_growth_buff3`（复利最强），`s0` 作对照；三组同 schema 可混采，但先按 Σ 归一化。
- `mask` 是权威：`logits.masked_fill(~mask, -inf)`；`action` 在记录时刻全部合法（legal 1.000）。
- `ep_split==1`（10%）只用于评测动作一致率/Σ，不参与训练。
- 建议两条正则：① 按 `ep_sigma_t15` 加权采样（尾部局更重要）；② 单独报 `is_amp_buy` 召回
  （这是本数据集要修的第一指标，模型基线 0.375 张/局）。
- 重生成：改 `gen_compound_bc.py` 的 `DEC_FIELDS/EP_FIELDS` 后三组 240 局 ≈3 分钟（12 workers），`--feature-dtype float32` 可换逐位精度。

## 9. 动作效率审计（40 局 + 6 个变体；`scripts/audit_compound_actions.py`）

逐决策记 `ΔΣ`（动作前后战团 Σ）、金币花费、`fwd3`（未来 3 回合 Σ 增量，启发式非因果）；
按回合内第 N 个动作统计边际价值。**预算**：600 动作/局（40×15），实际自主动作 **381.7（64%）**
+ pending 61.3（13.4%）。**金币**：收入 p50 1194/局，只花 **388（33%）**，**回合末余金 58.1/回合
（86.5% 的回合 ≥5 金）**。

| 动作 | 次数/局 | 占比 | 花费/局 | ΔΣ 均值 | fwd3 倍数 |
|---|---|---|---|---|---|
| play_spell | 83.1 | 18.1% | 0 | **+18.4** | ×2.19 |
| play_minion | 66.8 | 14.6% | 0 | **+136.3** | ×3.76 |
| buy_spell | 65.3 | 14.3% | 143 | +0.4 | ×2.69 |
| pending | 61.3 | 13.4% | 2 | +25.1 | ×2.31 |
| sell | 53.5 | 11.7% | 0（+53 收） | **−139.5** | ×2.50 |
| refresh | 53.3 | 11.6% | 52 | +1.8 | ×2.49 |
| buy_minion | 30.9 | 6.7% | 91 | −3.8 | ×5.15 |
| end_turn | 15.0 | 3.3% | 0 | 0 | ×4.36 |
| buy_amp | 8.9 | 2.0% | 26 | −12.8 | ×2.45 |
| buy_carrier | 8.2 | 1.8% | 24 | −29.0 | ×2.66 |
| upgrade | 5.0 | 1.1% | 41 | 0 | ×16.9 |
| hero_power | 6.7 | 1.5% | 7 | +1.1 | ×3.74 |

读法：买牌进手牌 ΔΣ≈0、上场 +136、卖出 −139、施法 +18 → **Σ 净额 ≈ 上场 − 卖出 + 施法**；
卖牌是「升级换代」的成本，不是纯浪费。**浪费读数**：roll 53.3/局、**85.2% 的回合打满 4 次**、
空刷新 21.9%；freeze/move=0（教师不用）；hero power 6.7/局；upgrade 集中在 t≈1.4。
**边际价值曲线**：第 N=1..20 个动作的 ΔΣ 在 ±20 振荡、第 21+ 个仍 **+13.5**，**没有递减** →
roll4 下动作额度没打满（64%），真正的堵点是「钱花不出去」（手牌 10 格 / 7 站位 / 商店 7 张）。

**变体（同种子 120 局，S3；`gen_compound_bc.py --max-refresh/--efficient`）**

| 变体 | 动作/局(占 600) | roll/回合 | 放大器/局 | 施法/局 | t15 Σ p50 全跑/保留 | r12_15 p50 |
|---|---|---|---|---|---|---|
| base120（roll≤4，正式） | 407 (68%) | 3.6 | 9.15 | 92 | 2358 / 3088 | 1.49 |
| roll≤2 | 285 (47%) | 1.9 | 6.17 | 67 | **1390 / 2346（−41%）** | 1.42 |
| roll≤6 | 462 (77%) | 5.2 | 11.13 | 102 | 2458 / 3638 | 1.13 |
| **roll≤8** | **520 (87%)** | 6.7 | **13.39 (+46%)** | 116 | **3046 / 3683（+29%）** | 1.02 |
| efficient 施法（roll4） | 398 (66%) | 3.6 | 9.70 | 92 | 2438 / 2962 | 1.25 |
| roll≤2 + efficient | 307 (51%) | 1.9 | 6.74 | 72 | 1646 / 2205 | **1.55** |

判据：**roll≤8 的 t15 Σ p50 +29%（≥10% 达标）**、放大器 +46%；但 r12_15 1.49→1.02（水平抬升、
形状不改善），roll≤2+efficient 的 r12=1.55 但 Σ −30%。「少刷新」方向相反：**刷新不是浪费**，
它是教师唯一的「找牌」动作；真正浪费是**回合末 58 金花不掉**（收入只花 33%）。roll8 已用掉
87% 动作预算 → **600 动作上限已成为下一道闸门**，再提升需环境侧放宽 `action_cap`。

产物：`s3_growth_buff3_eff_roll8.npz`（94 局 / 57,764 决策 / amp 13.39，动作效率教师，可与正式 S3
混采）、`s3_growth_buff3_eff_roll6.npz`（中间对照）、`action_audit_{s3,roll2,roll6,roll8}.json`。

## 10. 混采版 + 现实收入臂（2026-11-01）

**混采**：`s3_mix_roll8.npz` = 正式 S3 : roll8 = **2:1**（170 : 85 局，`ep_source` 0/1 标记），
255 局 / **133,709 决策** / 931MB；amp **10.64**、t15 Σ p50 **3,390**、r12 1.20、val 26 局。
脚本 `scripts/mix_compound_bc.py`（按局确定性抽样、重编号、重算 val、复用合法自检）。

**现实收入臂**（同 S3 其余配置，只把收入换成 fixed 15/20 金/回合；各 120 局）：

| 收入 | 策略 | t15 Σ p50(全跑) | mean | 放大器/局 | 施法/局 | r12 p50 | Σ/金 |
|---|---|---|---|---|---|---|---|
| growth（S3≈1200 金/局） | roll4 | 2358 | 3507 | 9.15 | 92 | 1.49 | 2.0 |
| growth | roll8 | 3046 | 4521 | 13.39 | 116 | 1.02 | 2.5 |
| **fixed 20**（300 金/局） | roll4 | 1524 | 2398 | 6.06 | 66 | 1.68 | 5.1 |
| **fixed 20** | roll8 | **1716** | 2838 | **6.74** | 71 | 1.55 | 5.7 |
| fixed 15（225 金/局） | roll4 | 1088 | 1253 | 2.94 | 54 | 1.64 | 4.8 |
| fixed 15 | roll8 | 1052 | 1271 | 2.80 | 58 | 1.47 | 4.7 |

判据：现实收入（20 金/回合）下 **t15 Σ p50 1716 < 2,300、amp 6.74 < 10 → 两条都不达标**；
roll8 相对 roll4 的优势在现实收入下仍 **+12.6% p50 / +18.3% mean**（方向成立、幅度减半），但
**绝对水平主要由金币总量决定**（S3 growth 收入 ≈1,200 vs 现实 300/225，4–5 倍）——高收入臂的
Σ 水平大半来自不现实收入；15 金/回合时连放大器都买不起（amp 2.8）。
**形状**：r12 随收入下降而回升（1.02@growth → 1.55@20 → 1.47@15）→ **水平抬升≠形状改善**；
要形状只能在「收入→动作转化」或「放大器触发次数」上做，教师侧不再继续动。

产物：`s3_mix_roll8.npz` + `s3_mix_roll8_meta.json`（混采，推荐蒸馏起点）；
`s3_growth_buff3_real20_roll8.npz`（现实收入教师证据）、`meta_*_real*.json`（15/20 与 roll4 对照读数）。

## 11. spell_spam 教师（sandbox-econ `SpellSpamPolicy`；fixed20 主臂，2026-11-01）

教师 = `scripts/spell_spam_probe.py::SpellSpamPolicy`（`CompoundPolicy` 子类：**金币优先买法术 →
立刻施放、优先对载体**；无东西可买才刷新）。入口：`gen_compound_bc.py --spell-spam 1 --env base`。
三组各 120 局（同种子；fixed20/fixed30 用 base 环境＝15 回合/action_cap 40/无闸门，
growth 用 S1 组配置）；**只保留 fixed20 口径 t15 Σ ≥ 1,400**。

| 臂 | 局(留) | t15 Σ p50 全跑/保留 | Σ/金(保留) | buff 实例(施法)/局 | golden/局 | amp/局 | r12_15 | 金币/局 |
|---|---|---|---|---|---|---|---|---|
| **fixed20（主）** | 120/73 | 1614 / **1980** | **6.60** | **81.7** | 1.48 | 5.62 | **1.65** | 300 |
| fixed30（对照） | 120/81 | 1662 / 2301 | 5.11 | 89.0 | 1.31 | 8.21 | 1.43 | 450 |
| growth 0.15（对照） | 120/81 | 1738 / 2339 | 1.97 | 93.4 | 1.51 | 8.16 | 1.58 | 1188 |

- 输出 `s20_spellspam.npz`（28,879 决策 / 201MB，`teacher_kind=spell_spam`、
  `meta_s20_spellspam.json`；`--out-name` 区分旧数据）。
- 读法：spell_spam 用**现实收入（300 金/局）**换来 **Σ/金 6.60**（旧 growth 教师 2.58、现实 roll8 5.7），
  r12_15 **1.65**（比高收入臂的 1.02 好）；代价是 **amp 5.62**（旧教师 9.14，且低于学生基线 5.96）
  与 Σ 水平（1,980 < 3,027）。⇒ 它是「省着花 + 形状好」的对照教师，建议与 `s3_mix_roll8`
  **按 1:1~1:2 混采**使用，而不是单独替换。
- 口径提示：Σ/金 是保留局口径（Σ≥1,400 筛选会抬高分子，全跑口径的完整 buff 实例
  = 法术+战吼+亡语+EOT 见 sandbox-econ 的 111/局）。
