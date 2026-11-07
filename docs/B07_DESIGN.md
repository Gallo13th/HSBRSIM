# B07 设计：训练/评测分布对齐（+ 同配方恢复 lr）

> 起点：B06 300M 权重（`runs/az_stage300m_b06/model.pt`）。
> 优化器与 B05/B06 完全一致（lr 3e-6 恢复、mb 1024 / accum 2 / max_updates 4300、epochs 1）。
> **唯一新增变量**：人类盘面注入从「3 席 p0.90 + board 保真」对齐到「**5 席 p0.90 + full 保真**」，
> 即与 canonical 评测 `scripts/eval_panel.sh`（5 席 / p0.90 / full / p75）同构。

## 1. 为什么是这条（杠杆账本）

| 轮 | 唯一变量 | bot 768 局 | 长强 win | human | 结论 |
|---|---|---|---|---|---|
| B01 | 300M 连续 PPO（lr 1.17e-6） | 1.853 / 41.8% | 20.0% | 6.385 / 328 | 基线 |
| B02 | （lr 触底空转） | — | — | — | 停 |
| B03 | human-board 课程 p50→p90 | 1.810 / 45.3% | 15.7% | 6.125 / 377 | 小幅 |
| B04 | 2 席冻结克隆 | 150M 384g 2.003 | 10.3% | — | 负 |
| B05 | **优化器强度 ×10 位移** | **1.646 / 51.8%** | 23.3%（250M 40%） | **6.021 / 434** | **显著有效** |
| B06 | 长强 advantage 加权 | 待 150M | 待 | 待 | 进行中 |

规律：**能改变行为的是"位移 / 分布"类杠杆**；改奖励/对手的收益小或负。
B07 属于"分布"类：训练场地与主评测口径不一致，这是唯一还没对齐过的结构性因素。

## 2. 重要更正：B05/B06 实际没有应用课程 ramp

编写 B05/B06 时以为它们沿用了 B03 的 `--human-board-ramp` / `--human-board-quantile-ramp`，
但核对其 `BLOCK_INFO.txt` 的完整命令行后确认：**这两个参数都没有被传进去**（`train_block_clean.sh`
里对应的 env 接线在某次覆盖中丢失，直到 B07 准备期才补回）。

- B03 实际场地：seats ramp（1→2→3）+ **flat quantile ramp**（p50→p75→p90，按累计决策切档）
- **B05/B06 实际场地**：固定 3 席 p0.90 + `sample=auto`（`human_board_pool` 内置的**按回合难度曲线**：
  turn≤8 → p50、9–12 → p75、≥13 → p90）+ `fidelity=board`
- ⇒ B05 相对 B03 的提升同时包含"优化器强度"和"课程口径变化"两个因素（不是严格单变量）。
  这一点必须写进后续报告，不能把 B05 的收益全部归给 lr。

B07 因此**不使用 ramp**（`sample=auto` 的按回合曲线本身就是合理的课程），把变更压缩到
"席数 3→5、保真度 board→full"这两项同源改动（都属于"把对手变得与评测同构"）。

## 3. 为什么 5 席 + full 应该有用

1. 评测口径是 `5 席 / p0.90 / full / p75`；训练只有 `3 席 / board`：
   - `board` 档只替换战团，**不带手牌、关键词位、金身/圣盾层数、tavern tier**；
   - 文档 `FIDELITY_INJECTION.md` 的配对反事实审计显示 full 档能把压力下界抬高 1–2pp，
     且注入后才"继续按 bot 策略打"，board 档的对手在注入后会明显变弱。
2. human 面板是唯一还没饱和的轴（B05 6.021，最好单点 5.708 @B06 40M），也是唯一"对手像人"的评测。
3. 与 `docs/ECONOMY_CEILING.md` 不冲突：那份文档证明的是"人类级强度在当前引擎规则下不可达"，
   而不是"不能继续靠近"；B05→B06 的 human 面仍在缓慢改善。

## 4. 成本与风险

| 项 | 评估 |
|---|---|
| 注入开销 | full 档 ≈ +0.62ms/座位（文档口径），5 席 vs 3 席再 +2 次调用/回合；**必须 pilot 验吞吐** |
| 库依赖 | `data/real_library/library_real_quasi_full.jsonl`（3.2MB，存在） |
| 风险 1 | 5 席 p0.90 full 让训练场显著变硬 → 早期 bot 面板可能先降后升（B03 课程加档时也这样） |
| 风险 2 | 若 human 面不再改善，说明瓶颈不在"对手保真度"而在策略表达能力 → 转搜索路线（候选 B） |
| 止损 | 150M 时若 bot 384g ≥1.75 且 human ≥6.25 ⇒ 停止，回滚 B06 权重，改跑候选 C（余弦退火到底 + 200M） |

## 5. 判据（≥384 局，终评 768 局）

| 指标 | B06 起点（待 B06 300M 定） | B07 目标 |
|---|---|---|
| bot rank | B06 300M | ≤ B06 − 0.05 |
| 长强 win（n≥24） | B06 300M | 不降（B05 768 局 23.3%、B05@250M 384 局 40.0%） |
| **human rank** | B06 300M | **≤ B06 − 0.10**（主要目标轴） |
| human 强度 p50 | B06 300M | ≥ B06 |
| 吞吐 | ~8.2k dec/s | ≥7.0k dec/s |

## 6. 执行步骤

1. `MINUTES=5 STOP=200000000 OUT=runs/az_stage300m_b07_pilot TAG=az_stage300m_b07_pilot bash scripts/run_stage300m_b07.sh`
   —— 检查吞吐（≥7k）、`illegal/truncated` 不变、`human_board.fidelity=full`、`payload_missing` 计数为 0
2. 正式跑 300M；监护沿用 B06 三件套（`tools/relabel_b06.sh` 改 run 名后复用 / watchdog 泛化）
3. 判读：150/250/300M 各 384 局 + 300M 768 局 + human 96 局 + `scripts/tier_probe.py`

## 7. 复现

```bash
bash scripts/run_stage300m_b07.sh          # 正式
DRY_RUN=1 OUT=/tmp/dry bash scripts/run_stage300m_b07.sh   # 只打印命令
```

## 2b. 决策记录：关闭长强加权（2026-11-07 07:50）

B06（`--game-weight-mode adv`, α=β=0.5）跑完后，三个独立面板点的方向一致：

| 指标 | B06@150M | B06@250M | B06@300M | B05 对照 |
|---|---:|---:|---:|---:|
| 长强 win（n） | 25.0%（24） | 15.6%（32） | **12.5%（24）** | 40.0%（25，250M）/ 23.3%（43，768 局） |
| tier5@t15 | 24.6% | 21.3% | **19.3%** | 28.0%（250M）/ 37.6%（B03） |
| bot rank（384 局） | 1.555 | 1.576 | **1.503** | 1.669（300M）/ 1.578（250M） |

结论：加权把总体 rank/win 推高了（1.503 / 63.5%，历史最好），但**长强子集与经济侧单调变差**，
与设计目标相反（机制猜测：长局多为输局，放大其 advantage 抬高了方差并拉偏价值估计）。

⇒ **B07 默认 `GAME_WEIGHT_MODE=none`**，把变量压回"分布对齐（5 席 + full）"这一项。
B06 的 `--game-weight-mode adv` 实现与测试保留（`tests/test_game_weight_adv.py`），供后续需要时复测。

## 8. 事故与修复：看门狗续训丢配置（2026-11-07 10:50）

**现象**：B07 在 10:50 因引擎空 mask 崩溃，watchdog 自动续训，但续训模板里**没有带
`HB_LIB/HB_FIDELITY/HB_SEATS`**，于是续训进程退回 `3 席 + board` 并**重新打开了长强加权**
（模板里 `GAME_WEIGHT_MODE` 常量仍是 `adv`）。从 78.5M 到 89M 的约 25 分钟、≈10M 决策
是在错误配方上跑的（熵、每 iter 决策数立刻从 0.48/54k 跳回 0.58/77k，这才被发现）。

**修复**（`tools/watchdog_b07.py`）：
1. 常量改为 B07 的真实配方：`GAME_WEIGHT_MODE="none"`、`HB_LIB=library_real_quasi_full.jsonl`、
   `HB_FIDELITY=full`、`HB_SEATS=5`，并把这些 env 导出/透传到 `run_stage300m.sh`；
2. 续训后 **45 秒主动核对**运行进程命令行里的 `--human-board-seats/-fidelity/库名/--game-weight-mode`，
   不一致直接打 ERROR（日志 `/tmp/watchdog_b07.log`）；
3. 11:15:42 从 `snap=1501 / DONE=86,417,075` 重新以正确配方续训，已确认
   `seats 5 / fidelity full / 无 --game-weight-mode`。

**教训（写进后续 run）**：续训模板必须与 launcher 的配方**同源**，最稳的做法是让 watchdog
直接调用该 run 的 launcher（`scripts/run_stage300m_bNN.sh`）并把 CK/TS/STOP/RAMP_START/EVAL_FIRST
作为覆盖项传进去，而不是各自维护一份模板。此项列为 B08 之前的技术债。
