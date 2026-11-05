# B04 设计：冻结对手席（联赛/自对弈的廉价版）

> 目标：把 B03 留下的**长局后期强度**短板当成对手分布问题来解 —— 让「对手不再被早期打死」，
> 逼出后期滚雪球能力。唯一变量 = 2 个 bot 席由冻结 checkpoint 驱动。
> 起始权重：`runs/az_stage300m_b03/model.pt`（B03 完整 300M，human 面最好、bot 面无回归）。

## 1. 动机（B03 的实证）

| 口径（768 局，seed 620000，37.0.2） | B01 起点 | B03 300M |
|---|---:|---:|
| bot rank / win | 1.853 / 41.8% | 1.810 / 45.3% |
| **长且强子集 win**（turns≥17 且 bot 强度 top25%） | 20.0%（n=50） | **15.7%（n=51）** |
| 输局时我方死亡盘面 Σ p50 | 783 | 757 |
| 同期死局 bot 最强盘面 Σ 均值 | 3439 | 3139 |
| human 96 局 rank / survive12 | 6.385 / 8.3% | **6.125 / 15.6%** |

- bot 面板已近饱和（top4 97–98%），唯一还有空间的判别轴是**长局**：我方在长局里的盘面只有
  bot 赢家终盘的约 1/4，长强子集胜率 15.7–20.0%，与非长强局 45–50% 断层。
- `docs/ECONOMY_CEILING.md` 证明「人类级强度」在当前引擎不可达，但**引擎 bot 自己能到 3000+**
  ⇒ 「bot 级后期强度」是可达的，缺的是**训练分布里逼出后期强度的对手**：引擎 bot 太容易被早期打死，
  8 席里又只有 1 个 learner，长局样本占比低。

## 2. 方案（唯一变量）

```
FROZEN_SEATS=2
FROZEN_OPPONENT=runs/az_stage300m_b03/model.pt   # 起跑时与 learner 同代的权重
```

- 8 席构成：1 learner + **2 冻结 net 席** + 5 引擎 bot 席（其中 3 席仍按 B03 课程注入 human-board）。
- 其余配方逐字沿用 B03：`lr 1.17e-6→5.85e-7`、`max_updates 4500`、课程 ramp
  （`0:1:0.30 → 15M:2:0.50 → 40M:3:0.70 → 80M:3:0.90`；`p50→p75→p90`）、anchor/KL/奖励全不变。
- 起点 `CK=runs/az_stage300m_b03/model.pt`，`TS=""`（fresh optimizer，沿用 B03 的教训）。

### 为什么不用 `--opponent self`（8 席全自对弈）

`--frozen-seats` 的帮助文本已经量化过：**7 席全冻结 ≈ 慢 25×**（每个席位每次决策都要一次 net forward），
300M 会从 ~15h 变成数天。`--frozen-seats 2` 的代价实测约 **−30% 吞吐**（3 卡 5288 dec/s → 4 卡 6366 dec/s，
见 [THROUGHPUT_300M.md](THROUGHPUT_300M.md) §5），是当前唯一可行的「对手升级」形态。
B04 默认使用 **actor 卡 3,4,5,6（4 张）**；`--leaf-wait-ms` 与 `--processes 48` 实测均为负收益。

### 联赛阶梯（下一步，不在本 run 内）

冻结对手在 run 内不会刷新，learner 大约 50–100M 后会超过它。真正的联赛需要**分块成阶梯**：
每 75M 一个 block，下一 block 的 `FROZEN_OPPONENT` 用上一 block 的 `model.pt`
（4 block × 75M，各带 fresh optimizer）。本次先跑单块，验证「冻结席是否带来长局改善」，
再决定要不要上阶梯。

## 3. 判据（≥768 局，单变量）

- 主判据：**长且强子集 win ≥ 26.7%**（B01 20.0% + 10pp 口径；B03 15.7%）且 n≥24
- 次判据：bot rank ≤ 1.75（768 局，B03 1.810）、win ≥ 48%
- 副作用检查：human 96 局面板不劣化 >0.10（B03 6.125）、entropy 不塌（>0.65）、
  吞吐 ≥ 5k dec/s
- 中途点（150M / 250M / 300M）各跑一次 384 局；终评 768 局（`scripts/eval_bot_panel.sh`）

## 4. 复现

```bash
# 正式跑（300M，约 15h）
bash scripts/run_stage300m_b04.sh
# 吞吐 pilot（8 分钟）
MINUTES=8 STOP=200000000 OUT=runs/az_stage300m_b04_pilot bash scripts/run_stage300m_b04.sh
# 监视
python scripts/stage_monitor.py --run runs/az_stage300m_b04 --until-decisions 300000000 \
  --eval-gpu auto --gpu-priority 7,1,6 --bot-panel-games 96 --bot-panel-seed 620000
# 终评（768 局）
bash scripts/eval_bot_panel.sh runs/az_stage300m_b04/model.pt b04_300M_bot768 768 620000
```

## 5. 风险

1. **冻结对手被超越**：run 后半段 2 个冻结席≈普通强对手，收益可能只在 0–100M 出现 ⇒ 需要阶梯化。
2. **吞吐**：−35% 使 ETA 从 9.5h 变 ~15h；宿主 load 高时更慢（B03 曾低到 0.35M/min）。
3. **长局样本仍然少**：冻结席只有 2/7，长局占比提升有限；若 200M 仍无长强改善，下一步加 `FROZEN_SEATS=3`
   或直接上阶梯。
