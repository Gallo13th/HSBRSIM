# 复利脚本（compound script）：放大器购买率 + 环境上限

> 脚本 `scripts/compound_script.py`；产物 `runs/compound_script/{amps_spell,groups}.json`。
> 沙盒：`hsbg.az.train.economy_sandbox`（无对手/无战斗/无血量）。卡表 37.0.0.255790。
> 运行：`--mode amps`（24 局放大器审计）/ `--mode groups`（4×28 局上限）。
> **动作合法率全程 1.000**（每一步用引擎 mask 校验，非法即回退并计数）。

## 1. 放大器清单（卡名匹配 → 实际 card id）

| 放大器 | card id（普通 / 金色） | 引擎实现 | 说明 |
|---|---|---|---|
| Brann 布莱恩 | `BG_LOE_077` / `TB_BaconUps_045`(+`_t`) | 战吼 ×2 / ×3 | 一次性法术 `BG28_509` Brann's Blessing、`BGS_Treasures_030` |
| Titus Rivendare 瑞文戴尔 | `BG25_354` / `BG25_354_G` | 亡语 ×2 / ×3 | 饰品 `BG30_MagicItem_310` Rivendare Portrait |
| Drakkari Enchanter | `BG26_ICC_901` / `BG26_ICC_901_G` | 回合结束 ×2 / ×3 | 饰品 `BG32_MagicItem_179` |
| Ashen Corruptor 邪吼咒龙 | `BG32_873` / `BG32_873_G` | 受伤后酒馆 +2/+2 | **沙盒无掉血 → 机制上是死牌** |
| Gatekeeper Amalgam 守门融合怪 | `BG36_640` / `BG36_640_G` | 施法即 Tea Set（=载体） | 同时是 `carriers.json` primary |
| **Barinda 巴琳达** | **卡表 0 张**（37.0 已无此卡） | — | 法术放大用 `income_probe.json` 的 `spell_amp` 28 张代理 |

> Titus/Drakkari/Brann 都是 tier5；Gatekeeper tier6；Ashen tier4。
> `Drakkari Embalmer`（`BG26_RLK_119`）是另一张牌，不算放大器。

## 2. 当前模型买不买放大器（24 局，spell 基线，CPU）

本机默认 Python **没有 torch**（`RuntimeError: torch 不可用`），s14-BC 权重
`runs/compound_prior/prep_bc/model_bc.pt` 无法加载；按任务允许的口径改用**现有脚本策略
（spell）**跑 24 局（`runs/compound_script/amps_spell.json`，5.5s）。

| 放大器 | 平均购买/局 | 出现率（≥1 张的局占比） | 总购买 |
|---|---|---|---|
| Brann | 0.083 | 0.08 | 2 |
| Titus/Rivendare | 0.000 | 0.00 | 0 |
| Drakkari | 0.000 | 0.00 | 0 |
| Ashen | 0.167 | 0.12 | 4 |
| Gatekeeper | 0.125 | 0.12 | 3 |
| Brann's Blessing / Titus' Tribute / Big Brann | 0.000 | 0.00 | 0 |
| Titus Portrait / Drakkari Portrait（饰品） | 0.000 | 0.00 | 0 |

**任意放大器 ≥1 张的局占比 = 20.8%（5/24），平均 0.375 张/局。**
结论：**当前模型基本不买放大器**（预期成立）。同口径下 `CompoundPolicy` 买
**8.8–15.4 张/局**（S0–S3），出现率 96–100% —— 差距在策略，不在可购买性。
Ashen 被买的 4 张是“身材顺带买的”，不是定向购买。

## 3. 脚本规则（`CompoundPolicy`，优先级显式）

1. **法术全打载体**：手牌法术优先 `A_PLAY` 到载体（`carriers.json` 22 个 id +
   “cast a spell on this / whenever you cast a (Tavern) spell” 全集）；无载体留 1 张，
   turn≥11 其余打出。
2. **放大器出现即买**（Brann/Titus/Drakkari/Ashen/Gatekeeper + 其法术/饰品），
   同名去重（三连除外）。
3. **载体 / 酒馆永久 buff farm**（`income_probe.json` 的 `tavern_buff` 15 个 id）优先买。
4. **三连**：持有对子时买第三张；刷新 ≤4 次/回合。
5. **t1–t5 curve**：升级后保留 4/6/8/10 金（`--upgrade-reserve`），tier5→6 不保留。
6. **t6/t9 饰品**：`gold_generation`(100) > `spell_generation`(80) > `spell_amplify`(60)
   > `tavern_buff`(40)；放大器饰品（Titus/Drakkari Portrait）额外 +95。
7. **满场卖非核心**：留场优先级 载体 3 > 放大器 2 > tavern-buff 1 > 普通 0；
   载体绝不卖，核心只在“明显更优”时换（普通牌 +20 身材门槛）。
8. 剩余金币买最强身材；仍花不掉则刷新（≤4）/英雄技能/EndTurn。

**实现坑（已修）**：手牌上限 10。早期版本把放大器/载体买进手牌却不给上场位，
手牌卡死 → 所有购买被 mask → t15 Σ 只有 ~780、金币剩 90+。修法：购买前算
`slots_left = 7 − 棋盘 − 手牌随从`，并允许“核心换非核心”。

## 4. 四组结果（每组 28 局，12 进程，合计 50s）

| 组 | 配置 | t12 p50/p90/max | t15 p50/p90/max | **r12_15 p50/p90/max** | Σ/金 p50 | goldens p50 | tav_buff p50 | 放大器/局 | 施法 p50 | 饰品命中/局 |
|---|---|---|---|---|---|---|---|---|---|---|
| S0 | fixed 30 金，action cap 40 | 1448 / 3182 / 6718 | 1820 / 4450 / 7118 | **1.14 / 1.95 / 2.63** | 4.05 | 1 | 18 | 8.8 | 80 | 1.14 |
| S1 | growth 0.15 + 2/载体，cap 40 | 1495 / 2698 / 3421 | 1652 / 2942 / 3430 | **1.02 / 1.86 / 4.65** | 1.39 | 1 | 8.5 | 9.3 | 82 | 1.14 |
| S2 | S1 + action-cap-per-gold 3 | 1915 / 5030 / 9128 | 2094 / 9012 / 13253 | **1.00 / 2.88 / 4.25** | 1.76 | 2 | 12 | 12.8 | 100 | 1.07 |
| S3 | S2 + tavern-buff-scale 3 | 3401 / 6864 / 14840 | 4207 / 14088 / **35513** | **1.19 / 3.94 / 8.33** | 3.60 | 2 | 32 | 15.4 | 131 | 1.21 |

（Σ/金 分母 = t15 `gold_total_income`：S0 450，S1–S3 ≈1190。）

## 5. 判据结论

- **S0（现状）28 局没有任何一局 r12_15 ≥ 3**（max 2.63）→ 现状环境 + 人类脚本 = 线性。
- **S1 起出现 r12_15 ≥ 3**（S1 max 4.65；S2 max 4.25；S3 p90 3.94 / max 8.33，
  t15 max 35513）。**按任务判据（任一 ≥3）= 环境能表达复利**，只是中位数仍 ~1.1
  → 复利是**尾部事件**，不是稳定策略。
- 瓶颈不在引擎，在两处：
  1. **金币上限 99**：growth 0.15 时 t8 就顶到 99（S1–S3 的 Σ/金 只有 1.4–3.6，
     vs S0 4.05）。要真正跑出指数段，下一轮应加 `--gold-cap 0`（闸门文档里已有开关）。
  2. **动作额度 / 手牌 10 张**：S3 施法 131 次已是 4 组最高，但塔尖局仍在 35k 以下
     （真实 10k+ t15 p50 26516 的同口径下我们 p90 14088）。

## 6. 下一步建议

1. 用 `CompoundPolicy` 当 **BC 教师**（s14 起点）：先 24 局 → 蒸馏，再测放大器购买率
   是否从 0.375 抬到 ≥5/局；这是“模型不买放大器”的直接修复。
2. 环境侧开 `--gold-cap 0` + `--sandbox-income-scale 1.2` 重跑 S3，验证 r12_15 p50
   ≥3；若仍 <2，再加 `--action-cap 60`（手牌 10 张是硬顶）。
3. **Ashen Corruptor 在无战斗沙盒里是死牌**：上限测试应把它换成
   `BG28_509` Brann's Blessing 之类可即时生效的放大器，或给沙盒加“假掉血”触发器。
4. 饰品命中 1.07–1.21/局、命中率 82–86%，说明 t6/t9 优先表生效；但 `gold_generation`
   饰品的实际收益被金币上限 99 截断，与第 2 条同因。
