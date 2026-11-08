# 缩放策略课程：金币课程 + 缩放教师 + 过程价值

> 依据：`runs/ceiling_probe/REPORT.md`。机制完备、真实经济下「只买身材」的上限只有真实
> t12 的 4–13%，而同一套施法缩放脚本在 ∞ 金币下 t12 p50 = 1843（41%）、p90 = 1.35×。
> 本文件描述三个默认关闭、开启后叠加的组件，以及四臂 A/B。

## 1. 经济（金币）课程

**开关**（`scripts/train_entity_sync.py`）：

| flag | 默认 | 语义 |
|---|---|---|
| `--gold-curriculum` | 0 | 兼容总开关；=1 且 stage=none 时按 warmup |
| `--curriculum-stage` | none | none / warmup / anneal |
| `--curriculum-gold-mult` | 1.0 | 金币**收入**倍数（warmup 建议 3.0） |
| `--curriculum-anneal-decisions` | 10M | 线性退火窗口（累计 decisions） |

schedule（`hsbg/az/train/curriculum.py`）：

- `warmup`：`mult` → 1.0 在窗口内线性下降（题面口径）；
- `anneal`：先保持 `mult` 半个窗口，再用半个窗口线性降到 1.0；
- `none` 或 `mult=1.0`：恒等。

**实现**：只在采集侧、learner 每个新回合第一次决策前，设
`gold = carry + round((gold_now - carry) * mult)`，其中 `carry` 是上一回合 learner
最后一次行动后的结余（放大的是本回合收入，不是结余，避免指数膨胀）。引擎通过
`Game.player_json` 读、`Game.debug({"cmd":"set_player",...})` 写；**不改 Rust**。
`mult=1.0` 时不读 JSON、不调 debug，逐位等价。

history 每行写 `curriculum_stage` / `curriculum_gold_mult` /
`curriculum_anneal_progress`（同时保留嵌套 `curriculum` 对象）。

## 2. 缩放教师（DAgger）

`hsbg/az/train/scaling_teacher.py` 把 `scripts/engine_ceiling_probe.py` 的 spell
脚本改造成纯函数教师：输入 `Game.view(seat)`，输出**确定性、必合法**动作。
规则优先级：手牌法术 → 买法术（酒馆永久 buff / 吞食）→ 买「cast a spell on this」
缩放随从 → 手牌随从/换身材 → 三连 → 买随从 → 升 tier → 刷新 → 英雄技能 → 结束。
`pending`（target/discover/choose_one/trinket）单独处理，target 优先缩放随从。

两种标注：

- **离线**：`python scripts/scaling_teacher.py --checkpoint ... --games 24 \
  --device cuda:7` → `data/scaling_teacher/labels.jsonl`（每行含宽松状态 +
  `teacher_action` / `action_name` / `legal` / `window`）与 `.meta.json`（合法率）。
- **在线**：`--teacher-bc-coef > 0` 时，采集侧在 `gold>=10 and tier>=4` 的决策上写
  `record["teacher_action"]`；PPO 在 `~forced` 且有标签的样本上加
  `coef * CE(π_θ, a_teacher)`。默认 0 = 不查教师、不写字段、不加损失。

## 3. 过程价值

`--process-value-coef`（默认 0）在 entity trunk 上追加 `Linear(d, 3)` 辅助头
（`attach_process_head`），预测三个过程量的 `log1p`：

1. 酒馆随从永久 buff 总和（`shop[].breakdown.this_game_bonus` 逐张累加）；
2. 本局施法次数（`stats.spells_cast`）；
3. 本局 consume 事件数（采集侧临时 `Game.set_record_log(True)` 后数日志里的
   `" consumes "`；只在开关打开时启用）。

只有目标可得的样本（NaN 掩码）参与 MSE；该头只被 `forward_process()` 读取，
`forward()` / `forward_aux()` / `forward_bc()` / `forward_problem()` 输出逐位不变
（单测覆盖）。与已证明无用的 `strength_head`（t+3 终局强度代理）是**两个独立头**。

## 4. 默认关闭 / 逐位等价

- 采集：`none+1.0` 不碰金币、不查教师、不读日志 → 同 seed 2 iteration 的 packed
  数组 sha256 完全相同（`tests/test_curriculum_scaling.py`）。
- 损失：`teacher_bc_coef=0` 时带/不带教师标签的 PPO 更新 weights 与统计完全一致；
  `process_value_coef=0` 时 head 参数不动、无 `process_*` stats 键。
- checkpoint：无新头时 meta/state_dict 与旧版逐位一致；需要时由 attach 追加。

## 5. A/B（40–60 iter，从 s15 权重起）

`scripts/run_scaling_ab.py`（cuda:7，每臂 50 iter，公共参数与 s15 一致）：

- A：现状；
- B：`--curriculum-stage warmup --curriculum-gold-mult 3.0`；
- C：B + `--teacher-bc-coef 0.02`；
- D：C + `--process-value-coef 0.05`。

评测：`quality_monitor --games 192`（t12/t13/t14/t15 强度比）与
`human_panel_eval --games 256`（`--smoke`、auto 分位）。判据：t12 强度比 ≥ +10%
（现 ~0.13）、human Δ ≤ +0.05、出局强度不降、零硬错。
