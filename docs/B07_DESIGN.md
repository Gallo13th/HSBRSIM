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
