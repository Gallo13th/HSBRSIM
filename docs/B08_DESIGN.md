# B08：强制升本（单变量）

## 动机（为什么不用"信用分配"方案）

astra 的 A（把 tier-miss 惩罚均分到整回合）只解决"惩罚落在哪个动作上"，不解决两个更根本的问题：

1. **数据稀缺**：高本样本极少（B07@250M 的 8-bot 768 局面板里 `tier5@t15 = 7.7%`，终局 T6 只 1.5%）。
   信用分配再好，也没有足够的"高本成功轨迹"可学。
2. **高本的期望收益没有被表示**：升本价值是 13+ 回合后才兑现的 option value；在终局单标量 +
   GAE(λ=.995, ~110 步视野) 下，它既不在观测里（无商店分位/池计数），也不在奖励里（只有终局名次）。
   不注入观测时，最直接的办法是**改变行为分布本身**。

## 方案：强制升本规则（`--forced-upgrade 1`）

> 本回合任一决策点，若 `gold > upgrade_price + 商店里当下最便宜的商品价格`
> 且「升级」为合法动作 ⇒ **只允许升级**（其余动作位清零）。

- 这是**行为策略的硬约束**（policy-changing），不是奖励塑形；训练/评测同源生效
  （`HSBRSIM_FORCE_UPGRADE=1` 对所有入口生效）。
- 与"禁卡"无关（不动卡池/运营自由度），只把"是否升本"这一维从策略里拿掉一部分。
- 实现：`hsbg/az/train/forced_upgrade.py`，在 `PPOSelfPlayPolicy._observe` 改写 mask
  （`decide` 与 lockstep `decide_batch` 共用路径）；默认关闭时恒等。
- 只用观测（gold / upgrade_price / shop ITEM_COST），**不读 player_json**，零额外开销。
- 单测：`tests/test_forced_upgrade.py`（5 个用例，含 float32 归一化误差与 env 开关）。

## 预期与风险

| 预期 | 说明 |
|---|---|
| 高本样本大增 | 买得起就升本 ⇒ `tier5@t15` 应从 7.7% 显著上移，T6 终局比例上升 |
| 前中期掉血 | 牺牲买怪/roll 节奏，可能拉低 bot 面板 rank（尤其前 20M） |
| 关键判据 | ①tier 时点 ②96 局强度曲线 t14–18 ③**双模型对战**（与合作者 ckpt 同口径）④768 局 bot rank |

## 判据与回退（预注册）

- 成功：`tier5@t15 ≥ 25%`、终局 T5+T6 ≥ 40%、96 局 t16–18 强度 ≥ 1400、768 局 rank ≤ 1.55；
- 部分成功（tier 上移但 rank 掉 >0.15）：保留规则但加 `margin`（如 2 金）只在小康时强制；
- 失败（tier 不动）：说明"买得起"的时刻太晚（收入曲线本就低），转去查经济（ECONOMY_CEILING）；
- 最终对照：与合作者 ckpt 的 128 局 H2H（`scripts/h2h_eval.py`）。

## 运行

```bash
bash scripts/run_stage300m_b08.sh                 # 正式
MINUTES=5 STOP=200000000 OUT=runs/az_stage300m_b08_pilot TAG=az_stage300m_b08_pilot \
  bash scripts/run_stage300m_b08.sh               # pilot
```
