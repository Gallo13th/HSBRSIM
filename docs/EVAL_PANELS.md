# 评测面板：bot 面板（已饱和）→ human 面板（新主指标）

> 一句话：**bot 面板已饱和，不能再当主指标**；新的主指标是「人类战团对手面板」
> （`scripts/human_panel_eval.py`），对手 = 真实 10k+ MMR 玩家在对应 turn 的战团分位。
> bot 面板继续保留，用于和历史 checkpoint 可比；human 面板用于暴露真实强度缺陷。

相关实现：`scripts/human_panel_eval.py`、`hsbg/az/train/evaluate.py`（注入驱动）、
`hsbg/az/train/human_board_pool.py`（分位池）、`scripts/async_eval.py`（训练侧双面板排队）、
`scripts/plot_quality_curves.py`（曲线）、`tests/test_human_panel_eval.py`。
人类战团数据本身的细节见 `docs/HUMAN_BOARD_OPPONENT.md`。

## 1. 为什么 bot 面板饱和

C0 gate（`scripts/c0_gate.py`）的口径是 **512 局 = 8 seat × 64 局，learner 轮换 seat 0..7，
7 个对手全部是引擎内置 bot**。该口径在早期有效，但现在已经失效：

- **分数被压缩**：历史最好 checkpoint 在 bot 面板上 mean rank 1.768、top4 97.1%、
  win 48.8%（`docs/STAGE6_REPORT.md`），64 局实测 mean rank 1.69 / top4 100%；
  再提升 1% 都要多打几百万 decisions，指标却几乎不动；
- **bot 的强度天花板太低**：从 t9 起 bot 的战团强度基本锁死在 **tier 4** 左右的水平，
  真实 10k+ 玩家 t9+ 的战团强度是它的 **3–13 倍**（见 `docs/STRENGTH_CALIBRATION.md`、
  `docs/HUMAN_BOARD_OPPONENT.md`）；
- **饱和掩盖缺陷**：模型只要「比 bot 强」就能在 bot 面板接近满分，无法回答
  「离真实 10k+ 玩家还差多少」，也无法指导 t9+ 的课程/强度训练。

所以 bot 面板从「主指标」降级为「**回归基线**」：新 checkpoint 不应比历史差，但**不应**
再用它判断是否变强。主指标换成 human 面板。

## 2. human 面板口径

### 2.1 对手强度 = 真实 10k+ 战团分位

- 数据：`data/real_library/library_real_degraded.jsonl`（4,284 行真实 10k+ 观测帧）；
- 每条观测按 `turn` 分桶，桶内按 `strength = Σ(atk+hp)` 取**最近秩分位**；
- `--quantile`：
  - `p50` / `p75` / `p90`：固定分位；
  - `auto`（默认）：按回合走难度曲线 **t≤8 → p50，9–12 → p75，t≥13 → p90**
    （理由：早期快照库并不弱，t10 之后真实值远高于 p50）；
- 每个对手座位每回合独立抽一条（同强度多条随机抽，避免总取上限）。

### 2.2 与 c0_gate 相同的协议

| 项 | bot 面板 | human 面板 |
|---|---|---|
| 局数 / seat | 512 = 8 × 64 | 512 = 8 × 64（smoke 可 64） |
| learner | seat 0..7 轮换 | seat 0..7 轮换 |
| seed | `--seed-base`（默认 100000 / 训练 420000） | 同左，参数化 |
| 封存面板 | 至少 2 个不重叠 seed 面板 | 同左 |
| 配对 | 同 seed/seat 再跑 bot 基线，Δ=rank_model−rank_bot | 同左（`--baseline-bot 1`，训练默认 0） |
| 主统计 | Δ 的 95% bootstrap CI | 同左（有 bot 基线时） |
| 硬约束 | 0 illegal / 0 truncated / 0 truncated_combats | 同左 |

human 面板的 `passed` 语义：

- 有 bot 基线（`--baseline-bot 1`）：沿用 `hsbg.eval.c0.evaluate_gate`，即
  「95% CI 上界 < 0（在该人类战团强度下仍显著优于 bot）」且硬约束全 0；
- 无 bot 基线（训练默认 `--baseline-bot 0`）：只表示**协议干净**（0 illegal/0 truncation），
  这也是训练里用它做监控的语义；
- 无论哪种，human 面板都是**测量工具**，不是晋级 gate；不要拿 bot 面板的 3.0 目标套用。

### 2.3 注入时机与 board-only 近似边界

**时机**：每回合开始、**任何座位行动前**，给除 learner 外的全部存活座位各注入一条
该 turn 的人类战团。注入不是「替换 bot 策略」，而是「把对手战团换成人类该回合的强度模板」；
被注入的座位**本回合照常行动**（买牌/上怪/技能都保留），所以只会比模板更强，不会更弱。

实现上按 `(seed, game, turn, seat)` 独立派生注入 RNG（`hsbg/az/train/evaluate.py`
的 `_mix_seed`），因此同一 seed 的 model 与 bot 基线面对**同一批战团**；某个座位是否死亡、
注入成功与否都不会改变其它座位的抽样 —— 配对差分才可靠。

**近似边界（必须如实标注）**：人类数据只有 `board`（recruit 末、combat 前），没有：

- hand / shop / 金币 / 酒馆等级（tier 按 turn 派生，`t≤10` 用常规升级节奏，上限 6）；
- 共享池差量（注入随从 `pool_copies=0`，旧 board 的持有量归还池，注入前后 `pool_balance` 守恒）；
- 隐藏计数（英雄技能次数、任务/饰品进度、pending choice、侦察/配对状态）。

因此它是 **`source=human_board_approx` 的 board-only 近似**，只能读作「该回合强度分位的
战团模板」，不能声称是忠实对手状态。已知窗口限制：

- 引擎 `turn=0` 是开局准备帧（人类数据从 turn=1 起），面板**从 turn=1 开始注入**；
- 饰品选择回合（如 t6/t9）开局时座位带着 `pending choice`，引擎会拒绝注入
  （`pending_choice`），该回合沿用上一回合注入的战团继续成长 —— 计数如实写进
  `injection.rejected_by_reason`；
- 没有镜像快照参与，`skipped_by_mirror` 恒为 0。

### 2.4 注入计数（证明真的生效）

结果里 `injection` / 每 seat 的 `human_board` 字段：

| 字段 | 含义 |
|---|---|
| `human_board_attempt` | 尝试注入的座位·回合数 |
| `human_board_applied` | 引擎成功替换 board 的次数 |
| `human_board_rejected` | 引擎拒绝次数（`not_recruit` / `already_ended` / `pending_choice` / `not_alive`） |
| `human_board_missing` | 该回合池里没有可用战团 |
| `human_board_errors` | Python 侧异常（应为 0） |
| `human_board_pool_unbalanced` | 注入后共享池不守恒（应为 0） |
| `human_board_nearest_bucket` | 该 turn 无数据、退化到最近回合的次数 |
| `human_board_tier_set` | 同时写入派生 tier 的次数 |
| `human_board_rejected_by_reason` | 拒绝原因分类计数 |
| `human_board_source` | 固定 `human_board_approx` |

## 3. 如何对比历史

- **bot 面板仍可比**：协议没变（512 局 / 8 seat / 同 seed），历史数字可直接对；
  但请把它当「回归检查」，不要再当主指标。
- **human 面板是新主指标**：2026-10 之前的历史 run 没有 human 面板数据，不能反推；
  从本版本起 `--eval-panel both`（默认）会同时记录。
- **human 面板内部只在同分位下可比**：`p50 / p75 / p90 / auto` 的难度完全不同，
  不要把 p50 的 4.0 和 p90 的 6.5 放在同一张表里比；跨 checkpoint 对比请固定
  `--eval-human-quantile` 与数据版本（`data/real_library/*.jsonl`）。
- **不要跨面板比较绝对值**：bot 面板 1.7 与 human 面板 6.8 不是同一把尺子；
  有意义的对比是「同一面板内的趋势」和「human 面板相对 bot 基线的 Δ」。

用 64 局 champion（`runs/champion_c0_1746.pt`，seed_base=100000）实测：

| 面板 | mean rank | top4 | win | 注入 applied/attempt |
|---|---|---|---|---|
| bot 面板（c0_gate，64 局） | **1.69** | 100% | 45.3% | — |
| human `auto`（64 局） | **6.81** | 4.7% | 0% | 9,049 / 11,272 |
| human `p90`（64 局） | **7.64** | 0% | 0% | 9,899 / 12,141 |

同一模型从 bot 面板的「接近满分」掉到 human 面板的「后 1–2 名」，正好量化了
bot 面板掩盖的真实强度缺口（t9+ 只到真实 10k+ 的 3–13%）。

## 4. 用法

### 4.1 单模型评测

```bash
# 正式 512 局 × 2 封存面板（auto 难度曲线）
python scripts/human_panel_eval.py --checkpoint runs/champion_c0_1746.pt \
    --games 512 --device cuda:7 --quantile auto \
    --out runs/eval/human_panel_champion.json

# 开发 smoke：64 局、单面板、同时跑 bot 基线做配对 CI
python scripts/human_panel_eval.py --checkpoint runs/champion_c0_1746.pt \
    --games 64 --smoke --device cuda:7 --quantile p90 --baseline-bot 1 \
    --out runs/eval/human_p90_smoke.json
```

### 4.2 训练脚本集成

```bash
python scripts/train_entity_sync.py ... \
    --eval-every-decisions 1000000 \
    --eval-panel both                    # bot + human（默认）
    --eval-human-quantile auto           # p50|p75|p90|auto（默认 auto）
    --eval-async 1 --eval-device cuda:7
```

- `--eval-async 1` 时**每个 panel 各起一个子进程**，但**并发上限仍为 1**：bot 跑完才跑
  human（顺序固定 bot → human）；到点但队列/子进程还在跑 -> 记一条 `eval_skipped`；
- `--eval-human-baseline-bot 1` 可让 human 面板同 seed 再跑 bot 基线（配对 CI），
  默认 0 省一半 wall；TRIGGER 库 / `--eval-stop-mean-rank` 仍只看 bot 面板；
- 结果都写进同一个 `runs/<run>/eval/history.json`，用 `panel` 字段区分：
  - bot 记录：`mean_rank / bot_mean_rank / top4 / win / mean_diff / ci_low / ci_high`；
  - human 记录：`human_mean_rank / human_top4 / human_win / human_bot_mean_rank /
    human_mean_diff / human_ci_low / human_ci_high / quantile / injection`，
    且 `mean_rank = null`（避免绘图脚本误当 bot 面板）；
- `history.jsonl` 每个 iteration 记录的 `eval` 段（从评测返回后的下一个 iteration 开始，
  最多滞后一次评测）同时保留：
  `mean_rank`（bot 面板）+ `human_mean_rank`（human 面板）+ `top4/win/human_top4/human_win`；
  训练结束的 `summary.json` 里 `evals` 是完整逐面板记录。

### 4.3 曲线

```bash
python scripts/plot_quality_curves.py --run runs/az_entity_s3 \
    --out quality_curves.png        # -> runs/plots/quality_curves.png
```

一张图三联：

1. mean rank：bot 面板（蓝实线）vs human 面板（红虚线）；
2. top4 / win：两个面板各自两条线；
3. 训练吞吐：`history.jsonl` 每 iteration 的 `collect_s` / `ppo_s`（对数轴），
   横轴=累计 decisions。

## 5. 结果字段（`scripts/human_panel_eval.py` 输出）

顶层：`protocol`（`human_panel_v1` / `human_panel_smoke`）、`panel="human_board"`、
`quantile`、`passed`、`smoke_result`、`checkpoint`、`checkpoint_sha256`、`engine`、
`config`、`panels`、`human_board_pool_stats`、`generated_at`。

`panels[i]`（与 c0_gate 相同的 panels 结构，另加 human 字段）：

| 字段 | 含义 |
|---|---|
| `passed` / `n` | 判定 / 有效配对局数 |
| `model_mean_rank` | learner 平均名次（主指标） |
| `bot_mean_rank` | 同 seed/seat bot 基线平均名次（无基线为 `null`） |
| `model_top4` / `model_win` | 前四率 / 冠军率 |
| `model_decisions` / `model_decisions_per_game` | learner 总决策数 / 每局决策数 |
| `mean_diff` / `ci_low` / `ci_high` | 配对 Δ 与 95% bootstrap CI |
| `illegal` / `truncated` / `truncated_combats` | 协议硬约束计数 |
| `reasons` | 未通过原因 |
| `panel` / `quantile` / `opponent` | `human_board` / 分位 / `human_board_approx` |
| `human_board_pool_stats` | 池摘要（rows/kept/filtered/每 turn 的 p50/p75/p90/max） |
| `injection` | §2.4 的注入计数 |
| `details.per_seat.seat_k` | 每 seat 的 `model` / `bot` 指标、`decisions_per_game`、注入计数 |

## 6. 已知限制与后续

- board-only 近似：没有 hand/shop/资源/池差量，t6/t9 饰品回合注入会被 pending 拒绝；
- tier 是派生值（t≤10 常规节奏，上限 6），不是真实玩家 tier；
- 对手每回合被「重置」为分位模板，无法反映真人同一局的资源滚动；
- 下一个增强方向：把 human hand/shop 也入库（当前数据没有），或把注入改成
  「只覆盖更强战团」的保守模式，减少低分位回退。

在增强之前，human 面板的数字应理解为**相对强度**（同分位、同数据版本的趋势），
而不是对真实 10k+ 玩家胜率的无偏估计。
