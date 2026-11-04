# 固定阵容脚本席（comp script seats）

> 把 `scripts/comp_scripts.py` 的固定阵容脚本作为自对弈大厅的 1–3 个「脚本席」对手
> （seat 1..N），其余座位仍是引擎 bot。**只改变对手分布，不改变奖励/PPO 数学。**
> 代码：`hsbg/az/train/comp_offline_policy.py`、`process_pool.py`、`parallel_collect.py`、`scripts/train_entity_sync.py`；测试：`tests/test_comp_script_seats.py`。

## 0. TL;DR
- CLI：`--script-seats 2 --script-comps auto`（需 `--lockstep 1`、`--opponent bot|weak`）。
- 语义：脚本席 = **hybrid**（阵容动作由 CompPolicy 接管，其余交给引擎 bot）；smoke 证据：
  header `frozen_opponent="comp:auto"`/`frozen_seats=2`，collect `frozen_decisions=32,975`、
  `illegal_actions=0`。不做奖励 shaping（comp_fit 类已被 ASTRA/comp-audit 否决，见
  DECISIONS D-20261030-01、docs/COMP_SCRIPTS_TRAINING.md），只是对手分布改动。

## 1. 设计
- `CompOpponentPolicy(Policy)`：每 seat 一个独立 `CompPolicy`（固定 spec、`auto=False`），状态隔离。
- `decide()`：`mask_from_bytes(game.legal_mask(seat))` → `view_of(game,seat)` → `observe` →
  `comp_action`；`None` 则 `game.bot_action(seat)`；合法性双保险（非法 → bot_action →
  mask 首个合法位），非法计数进 `stats["illegal"]`。
- 换局检测（`id(game)` 变化或 turn 回退）→ 该 seat `reset()`；核心/经济计数不跨局。
- `stats`：`decisions / illegal / bot_fallback / comp_actions / errors / seat_resets`；
  `hybrid=False`（纯 `act`）只用于测试/对照，训练默认 hybrid。
- `process_pool` 在 `cfg.frozen_opponent` 以 `comp:` 开头时走脚本分支（不加载 checkpoint）并缓存；
  `comp:auto` 按 task seed 稳定轮转取 `min(frozen_seats, len(keys))` 套，`comp:A,C` 显式指定。

## 2. CLI / 校验（`scripts/train_entity_sync.py`）
`--script-seats 0..3`（默认 0）；`--script-comps auto|A,C`（28 套 key，`scripts/comp_scripts.py --list`）。
启动校验（不过 → rc=2 不训练）：`--lockstep 1`、`--opponent bot|weak`、不得与 `--frozen-opponent`
同给、key 必须存在于 `comp_keys()`。通过后写 `args.frozen_seats=N`、
`args.frozen_opponent="comp:"+script_comps`（history header 自动记录）。

## 3. 运行时链路
`train_entity_sync → CollectConfig.frozen_* → process_pool worker（comp 分支构造/缓存
CompOpponentPolicy）→ collect_ppo_lockstep：frozen_set=1..N → bot 座位动作前 decide →
成功 step 后 st["frozen_decisions"]+=1`。父进程汇总 `frozen_opponent/frozen_seats/
frozen_decisions` 到 collect 顶层（仅确有脚本席时新增键，不改其它 run schema）。
脚本席不被其它注入源覆盖：人类战团显式排座排除、镜像目标过滤 `frozen_set`（含随机模式）、
轨迹回放跳过、v1 `--library-pool` 本就禁用（raise）。

## 4. 指标（history.jsonl）：`header.args` 记 `script_seats`/`script_comps`/`frozen_seats`/`frozen_opponent`；`record.collect`
记 `frozen_decisions`（脚本席成功决策数，>0 才证明真上场）与 `illegal_actions`（脚本席要求 0）。

## 5. 限制
- 脚本强度 ≈ 引擎 bot 量级（comp 探针 t15 Σ p50≈249 vs 模型 323.5）→ 本实验测**对手多样性**，
  不是更强对手；hybrid 只接管阵容动作，经济/升本/站位仍由 bot 决定。
- `auto` 轮转偏移来自每次 collect 的 task seed，**逐 iteration 可能换阵容**；
  严格固定对手 A/B 请显式 `--script-comps key1,key2`。
- 96 局 canonical 面板 rank SE≈0.2，`|Δrank|<0.3` 不可分辨；正式判定需 ≥288–384 局。
- 不改网络、不改奖励、不改 PPO 数学。

## 6. A/B 预注册（2026-11-04 实际执行版）
- 起点 `runs/az_entity_s73/model.pt` + `trainer.pt`（精确续训）；其余沿用 clean recipe。
- 唯一变量 `--script-seats`：control `0` vs treat `2 --script-comps D,H`
  （D=Elemental Azerite、H=Murloc End of Turn；探针 hybrid t15 Σ 314/313，是脚本里最强的两套）。
- 预算：每臂 10M decisions，`--seed 27401`（两臂同 seed）；actors 3,4,5 / learner cuda:0 /
  eval cuda:1；`GPU_FREE_CHECK=0`。两臂顺序执行（同一资源条件），代码冻结于 commit `31d61bf`。
- 主判据：**新 seed 741024、512 局**的 `mean_rank`（起点 s73 也同 seed 复评）；
  次判据：`top4` / `death_strength_p50` / `tier_ge4_ratio` / `survive_t12_ratio` / `tier_ge5_t15`；
  另报 canonical 96 局（seed 520000）。
- 判定：`Δrank ≤ -0.3` 且 top4 不降 → 可能有改善（再 384 局复评）；`|Δrank|<0.3` → 噪声；
  `Δrank ≥ +0.3` → 回退（`--script-seats 0`，零影响）。10M 是 pilot，不宣称显著性。

## 6.1 执行结果（2026-11-04，详见 [COMP_SCRIPT_AB.md](COMP_SCRIPT_AB.md)）

| 指标 | s73 起点 | control(10M) | treatment(10M) | treat−ctl |
|---|---:|---:|---:|---:|
| 512 局 seed741024 rank | 6.232 | 6.324 | 6.258 | **−0.066** |
| 512 局 strength | 322.0 | 315.5 | 322.0 | +6.5 |
| 512 局 top4 | 12.70% | 12.89% | 10.74% | −2.15pp |
| 96 局 seed520000 rank | 6.208 | 6.375 | 6.135 | **−0.240** |
| 96 局 strength | 347.5 | 300.5 | 362.0 | +61.5 |
| 采集 dec/s | — | 10,260 | 3,090 | **−3.3×** |
| illegal / frozen decisions | — | 0 / 0 | 0 / 8.23M | — |

**裁决**：接入正确、无退化；rank 方向偏好但两面板均 |Δ|<0.3（噪声），且 512 局 top4 反向
⇒ **不宣称改善**。脚本席采集慢 3.3×（逐决策 `view_of`），默认保持 `--script-seats 0`；
下一轮先优化决策路径再做 ≥1024 对配对 A/B。

## 6.2 对手强度复核（8 席全脚本，2026-11-04）

`docs/EIGHT_SCRIPT_BOTS.md`：8 席全部脚本、50 局，冠军终局 Σ(atk+hp)：

| 模式 | p50 | p90 | max |
|---|---:|---:|---:|
| 8 scripts（默认） | 1268 | 1960 | 2558 |
| 8 scripts（no-exit） | 1230 | 1832 | 3042 |
| 8 engine bots | 1311 | 3876 | 14576 |

→ **脚本与引擎 bot 中位强度相当，尾部更紧**（没有 10k+ 滚雪球），作为对手可靠。
用户据此批准脚本作为 PPO 对手（DECISIONS D-20261104-09）：**下一 stage 默认 2 席**，
当前 300M stage 保持 clean；启用前需把 3.3× 采集开销压下来（快速 view / 每回合前 k 决策）。




## 7. Smoke 证据（2026-11-04）
`train_block_clean.sh --dry-run` 派生命令，只改 `--processes 2 --games 8 --gpus 3,4
--device cuda:5 --threads 2 --minutes 10 --stop-at-decisions 40000
--eval-every-decisions 100000000 --out runs/_smoke_scriptseats`，追加
`--script-seats 2 --script-comps auto`。结果：`rc=0`，`[done] iters=312 updates=312
elapsed=142s`；27 条 record、`decisions=41,316`；`frozen_decisions=32,975`、
`illegal_actions=0`、`human_board_applied=5,857`；失败路径（seats=4/未知 key/lockstep=0/
与 frozen-opponent 同给）均 rc=2。

## 8. 用法（一条完整命令）
```bash
cd /home/data/users/gaoletian/projects/HSBRSIM
PYTHONPATH=rust/python:. /home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python \
  scripts/train_entity_sync.py --checkpoint runs/az_entity_s61/eval/ckpt_020026719.pt \
  --trainer-state runs/az_entity_s61/trainer.pt --device cuda:6 --gpus 3,4,5 \
  --processes 24 --threads 3 --lockstep 1 --games 384 --minutes 400 --iterations 8000 \
  --stop-at-decisions 10000000 --script-seats 2 --script-comps auto \
  --eval-every-decisions 10000000 --eval-games 96 --eval-seats 8 --eval-seed-base 420000 \
  --eval-async 1 --eval-device cuda:1 --eval-drain 1 --out runs/az_entity_s74_scriptseats
```
（正式 run 用 `scripts/train_block_clean.sh` 完整开关集合 + 追加本两参数。）
