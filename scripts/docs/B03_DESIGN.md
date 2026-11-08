# B03 详细设计：对手强度课程（human-board ladder）

> 状态：**设计稿**，等 B02（37.0.2 固定配方基线）跑完后启动。
> 目标：在**相同起点/预算/数据/算法**下，只改「训练对手难度的时间分布」，检验
> 「先弱后强」的对手课程能否比 B02 的固定强度更快/更好地把 bot 局 rank 与
> 「长且强 bot 局 win」拉起来，同时 human 面板不退。

## 1. 假设与可证伪点

- H1（机制）：B02 从第 1 个 iteration 就是 3 席 p0.9 / p75 的硬对手，模型长期停在
  tier 2–4、`survive_t12` 只有 12–19%；先把对手降到「能稳定活到 t10–12」的水平，
  能让 tier≥4 回合占比升起来，学到缩放/后期决策。
- H2（效果）：在 300M 处，B03 的 8-bot 面板 `mean_rank` 至少比 B02 低 0.15，
  或「长且强 bot 局 win」高 10pp，且 human 面板不退化。
- H3（可证伪）：若 100M 时 B03 的 bot rank 已落后 B02 >0.25，或 `entropy<0.65`、
  human 退化 >0.3 → 课程假设不成立，停止并回退。

## 2. 唯一变量

**只改训练内 human-board 注入的难度日程**；其它与 B02 逐字相同：

| 项 | B02（基线） | B03（课程） |
|---|---|---|
| 起点 | B01 final `model.pt`+`trainer.pt` | **同 B01 final**（同一起点） |
| seed | 27503 | **27503**（同 seed，减少差异） |
| 引擎/数据 | 37.0.2.256589 | 同 |
| 预算 | 300M decisions | 300M |
| 采集 | 32 procs / threads 2 / mb 2048 / accum 4 | 同 |
| 奖励/算法 | clean recipe（anchor 0.1 常数等） | 同 |
| 对手（固定） | 3 席 / p0.9 / p75 / board fidelity | **改为下面的日程** |
| 评测 | 每 10M：human 96 + 8-bot 96 | 同（不参与训练） |

## 3. 难度日程（主方案 B03-A：固定 step 档位）

按**累计 learner decisions**求值（引擎/控制器原生口径，不是 wall time），
`step` 模式（到点整档切换；`linear` 只作为敏感性对照，不混入主实验）。

**席数 / 注入概率**（`--human-board-ramp`）：

```
0:1:0.30, 15M:2:0.50, 40M:3:0.70, 80M:3:0.90
```

**分位**（`--human-board-quantile-ramp`，独立）：

```
0:p50, 40M:p75, 150M:p90
```

时间线：

| decisions | 席数 | p | 分位 | 意图 |
|---|---:|---:|---|---|
| 0–15M | 1 | 0.30 | p50 | 极简：先学会活过 t8–10、升本/经济 |
| 15–40M | 2 | 0.50 | p50 | 中等：开始面对真实战团 |
| 40–80M | 3 | 0.70 | p75 | 接近 B02 强度（席数=3） |
| 80–150M | 3 | 0.90 | p75 | **等于 B02 固定强度** |
| 150–300M | 3 | 0.90 | p90 | 比 B02 更硬，冲后期上限 |

> 为什么 80M 才回到 B02 强度：B02 的前 80M 一直在硬对手下停在 tier 2–4；
> 课程需要足够长的「能活到后期」窗口来产生 tier≥4/缩放决策，否则只是把 B02 的
> 困难期重复一遍。150M 后升 p90 是为了避免课程结束得太软、浪费后半程。

保真度：与 B02 一致 `--human-board-fidelity board`（不做 full，避免与引擎 37.0.2
的高保真 payload 差异混淆）；`--human-board-set-tier 1` 保持。

## 4. 自适应门控（B03-B，主实验不启用）

主实验用固定日程（可复现、无反馈噪声）。若 B03-A 有效但升档点偏保守，再做
B03-B 作为消融：

- `--ramp-adaptive 1 --ramp-window 5 --ramp-survive-threshold 0.25
   --ramp-tier4-threshold 0.30 --ramp-delay-decisions 2M --ramp-max-forced-per-game 12`
  （默认门控含义见 `docs/BOARD_RAMP.md` §3）。
- 需要真实 tier 观测时接 `--ramp-quality-json`（每 10M 的 quality 面板），
  否则用轨迹代理（会把「活到 t12 但停在 tier3」高估）。
- **不把 bot 面板 rank 作为在线门控**：bot 面板每 10M 才有一个点，延迟太大，
  且会让课程和评测互相污染；bot 指标只做**离线判定**。

## 5. 评测与判定（预注册）

### 5.1 主判据（300M 处）

1. **8-bot 面板 128 局**（训练配置 `--move-guard 1`，seed 620000）：
   `mean_rank`、`top4`、`win`；加权（长度+bot强度）同口径。
2. **长且强 bot 局**（`bot_strength_curves` 64–128 局，seed 830000/620000）：
   turns 与 bot 终局强度都 top 25% 的子集，win / mean_rank。
3. **human canonical 96 局**（seed 520000）：rank/top4/strength/tier≥4。

### 5.2 判定规则

- **有效**：以下同时成立
  - bot `mean_rank` ≤ B02 − **0.15**（或 `top4` +3pp）**且** 最近 5 个 10M 点中至少
    3 个方向一致；
  - 长且强 bot 局 win ≥ B02 + **10pp**（样本 ≥24 局）；
  - human `mean_rank` ≤ B02 + **0.10**（非劣），tier≥4 不低于 B02 −3pp。
- **无效**：bot rank 与 B02 的差 |Δ|<0.15，或长且强 win 无改善 → 课程不采纳，
  下一阶段转 B04（长度+强度加权）。
- **有害/早停**：100M 时 bot rank 落后 B02 >0.25，或 entropy<0.65 连续 10 iter，
  或 human 退化 >0.3 → 停跑、保留 checkpoint、记录失败。

### 5.3 噪声与样本量

- 128 局 8-bot 的 `mean_rank` SE≈0.09（SD≈1.0）；96 局 human SE≈0.15。
  因此「Δrank=0.15」只是 ~1.5 SE，必须叠加「最近 5 点方向一致 + 长且强 win +10pp」
  才判定有效，避免把噪声当收益。
- 训练内 10M bot 面板每点 96 局（SE≈0.10），只用于看趋势与早停，不做最终判定。

## 6. 实现改动（都是可选/加法，不动训练数学）

1. `scripts/train_block_clean.sh` 增加 env 透传（默认空 = 逐位不变）：
   `HB_RAMP` → `--human-board-ramp`、`HB_QUANTILE_RAMP` → `--human-board-quantile-ramp`、
   `RAMP_MODE` → `--ramp-mode`。
2. 新增 `scripts/run_stage300m_b03.sh`：CK/TS=B01 final，OUT=`runs/az_stage300m_b03`，
   SEED=27503，STOP=300M，MINUTES=1500，传入上面 schedule。
3. `quality_monitor.py` 的 bot 面板增加 **长且强子集** 字段（复用
   `game_weights` 的 turns/bot-strength 百分位；输出 `longstrong_n/win/rank`），
   stage monitor 每 10M 记录，避免只在终局才知道。
4. 单测：`tests/test_bot_longstrong.py`（纯函数）+ board-ramp 解析已有测试。

## 7. 运行与成本

- 启动条件：B02 完成（或确认停止）后，GPU 3,4,5 + learner 0 空闲。
- 预计 300M ≈ 9–10h（9k dec/s）+ 每 10M 的 human/bot 评测（后台卡）→ **~11h**。
- 若 100M 早停，成本 ≈ 3.5h。

## 8. 回退与后续

- 回退：B03 任何时点都可从最近 snapshot 停；不覆盖 B02 目录。
- 若 B03 无效：B04 = 对局长度+强度加权（per-episode PPO loss，α=β=0.5，
  `--game-weight-mode loss`），目标仍是「长且强 bot 局 win」。
- 若 B03 有效：把日程固化进下一 stage 默认，并做 B03-B（自适应门控）消融。
- 引擎/数据升级与课程参数**分开提交**；B03 的 schedule 写进 `meta.txt`/`summary.json`。

## 9. 风险

| 风险 | 缓解 |
|---|---|
| 早期太软，模型「躺赢」学不到东西 | 80M 回到 B02 强度；100M 早停对比 |
| 从 B01 final（已硬训 287M）开始，easy 段收益小 | 100M 判据；无效就转 B04 |
| 37.0.2 人类战团库仍是旧 stats | 只影响注入数值，不影响课程机制；记录版本 |
| 自适应门控把课程卡死 | 主实验不用自适应；B03-B 单独做 |
