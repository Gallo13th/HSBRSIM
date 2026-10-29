# 动作序列辅助任务（turn 内动作 multi-hot + aux head + 权重 ramp）

> 状态：已实现，**默认关闭**（`--seq-coef 0`）。关闭时 records→batch→loss→日志与旧版本
> 逐字节等价（见 §7 的证据）。
>
> 代码：`hsbg/az/train/seq_aux.py`（标签/ramp/BCE 纯函数）、`hsbg/az/train/ppo.py`
> （批次字段 + 损失）、`hsbg/az/train/model.py` / `entity_model.py`（`seq_head`）、
> `scripts/train_entity_sync.py` / `scripts/train_az_ppo.py`（CLI 与 ramp 接线）、
> `tests/test_az_seq_aux.py`（单测）。

## 1. 动机

PPO 的主目标只有终局 rank/utility，梯度信号稀疏且回合内没有任何"过程监督"。动作序列
辅助任务让网络在学习主目标的同时，额外地预测**自己在当前回合内还会做哪些动作**：

- 结构上强迫 trunk 编码"本回合接下来可能采取的行动集合"，对未训练网络（容易在
  Play/Cancel 循环里打转）尤其有用；
- 只在 `seq_coef>0` 时生效，纯辅助正则，不改变行为分布与推理路径（推理不用 seq 头）。

注意：标签包含"当前步之后到回合结束"的动作，因此这是 **off-policy / 未来信息** 的
leaky 监督（§8.1），只能当辅助正则，不能当策略目标。

## 2. 标签定义与构造

对每个决策样本（seat `s`, turn `T`）：

```
seq_target[a] = 1  ⟺  seat s 在 turn T 内（含当前步，直到该回合结束）实际执行过动作 a
```

`seq_target` 是 `multi-hot(245) uint8`。

**构造方式（等价于"回合末回填"，但零热路径开销）**：每条 record 已经带
`(game_id, seat, turn, action)`，而"该 seat 在 turn T 内的动作集合"恰好等于
"`(game_id, seat, turn)` 相同的所有 record 的 action 集合"。因此标签在**打包阶段**
用 numpy 一次算完：

```python
key = (game_id, seat, turn)                 # 同回合 = 同组
bits[group, action] = 1                     # 组内动作并集
seq_target = bits[inverse_index]            # 回填给该组每条样本
```

向量化实现见 `seq_aux.seq_targets_from_records` / `seq_targets_from_packed`
（`np.unique(axis=0, return_inverse=True)` + 一次 `bits[...] = 1`）。

与"回合结束时回填"相比：

| | 回合末回填（逐决策维护 dict） | 打包期分组（本实现） |
|---|---|---|
| 语义 | 完全相同 | 完全相同（动作集合由 record 定义） |
| 采集热路径 | 每决策 1 次 dict 查找 + 置位 | **0 次** |
| 回填时机 | 需要每个游戏结束/回合切换点显式 flush（路径多、易漏） | 打包时一次，天然覆盖所有采集路径 |
| 复杂度 | O(1)/决策 | O(n log n)（`n` = 一批样本数） |

实测成本（CPU，单核，`pytest` 之外的 microbench）：**0.9–1.3 µs/样本**
（30k 样本 ≈ 27 ms，SoA 版本 ≈ 17 ms）；一次 iteration 的采集是几十秒量级，占比 <1%，
满足"不拖慢采集 >5%"。

`PPOBatch.validate()` 会检查两件事：值必须是 0/1；**本步实际执行的动作位必须是 1**
（防止标签构造与 action 错位）。

## 3. 模型

- `build_net(hidden, arch="tiny"|"entity"|"entity18m", seq_head=True)`：
  - tiny：`seq_head = nn.Linear(hidden, 245)`，输入 trunk 输出；
  - entity/entity18m：`seq_head = nn.Linear(d_model, 245)`，输入 global token；
- `seq_head=False`（**默认**）时属性为 `None`：不建参数、不参与前向、state_dict 不变；
- `forward()` 签名与返回值不变（tiny 仍是 2 元组、entity 仍是 3 元组），只有
  `forward_aux()` 会额外返回 seq logits：
  `(logits, rank_logits, value|None, seq_logits|None)`；
- `save_checkpoint` 写 `meta["seq_head"]`，`load_checkpoint` 据此重建；
  旧 checkpoint（无该键）-> `seq_head=False`，能照常加载。

参数量增量：tiny(hidden=256) `+62,965`（256×245 + 245）；entity(d=384) `+94,325`。

## 4. 损失

```
seq_loss = mean_{i ∈ valid & has_target} mean_{a=0..244} BCEWithLogits(seq_logits[i,a], seq_target[i,a])
total    = policy + value_coef*value + pi_coef*aux_pi - entropy_coef*entropy
         + seq_coef*seq_loss
```

- **只对 `valid & ~forced` 样本平均**：`valid = ~forced`（确定性守卫样本 `forced` 不参与
  策略/aux/seq，与既有口径一致）；另外 `has_target` 排除标签全 0 的样本（防御性，
  正常构造不会出现）；
- 先对 245 维取均值再对样本平均（多标签 BCE 的常规做法），因此**全 0 logits 时
  `seq_loss = ln2 ≈ 0.6931`**，可直接当"没学到东西"的基线看；
- 缺条件时（模型没 seq 头 / 批次没有 `seq_target`，例如 Rust 采集器路径）`seq_loss=0`
  且不制造假梯度，训练继续；
- 默认关闭时 `ppo_losses()` 的返回字典**不含** `seq_loss` 键，`total` 表达式与旧版一致。

## 5. 权重 ramp（按 decisions 比例）

规格：`coef@progress` 逗号分隔，`progress ∈ [0,1]`：

```bash
--seq-coef 0.02 --seq-coef-ramp "0.02@0,0.05@0.5"
# 进度 0 -> 0.02；0.25 -> 0.035；>=0.5 -> 0.05
```

- 纯函数：`parse_coef_ramp`（解析/校验/排序/去重）、`ramp_coef(points, progress)`
  （线性插值 + 两端 clamp + 非有限 progress 兜底 0）、`resolve_coef`（有 ramp 用 ramp，
  否则用常数系数）、`SeqCoefSchedule`（封装 `points + total_decisions`，`coef(cum)` 一行取值）；
- 进度 = `累计 decisions / --seq-ramp-total-decisions`（0 则退回 `--stop-at-decisions`，
  再缺省 **3e7**，≈ stage-3 一个 stage 的 decisions 量级）；
- `train_entity_sync.py` 每个 iteration 用**上一个 iteration 结束时的累计 decisions** 插值，
  写入 `trainer.config.seq_coef`，再走 `trainer.update(batch)`；
- `train_az_ppo.py` 是单轮入口，ramp 进度恒为 0（取第一个控制点）；
- 没有 ramp 时就是常数 `--seq-coef`。

边界语义（单测覆盖）：`progress<=首点` 取首点系数、`>=末点` 取末点系数、单点 spec
处处相等、`NaN` 进度按 0、非法 spec（缺 `@`、负数、`>1` 或 `NaN` 进度、无法解析）
直接 `ValueError`（`PPOConfig.__post_init__` 也会提前校验）。

## 6. 如何开启

```bash
# 主训练入口（写 history.jsonl）
PYTHONPATH=rust/python:. python scripts/train_entity_sync.py \
  --arch entity --device cuda:3 --games 4 --minutes 30 \
  --seq-coef 0.02 --seq-coef-ramp "0.02@0,0.05@0.5"

# 单轮入口（写 report.json）
PYTHONPATH=rust/python:. python scripts/train_az_ppo.py \
  --arch tiny --games 2 --epochs 1 --sims 0 --eval-games 0 --seq-coef 0.02
```

生效条件（三者缺一不可，否则退化为"无 seq 信号"）：

1. `--seq-coef > 0` 或 `--seq-coef-ramp` 中存在正系数；
2. 模型带 seq 头（新建模型自动带；**从旧 checkpoint 续训会打印 warn 并自动关闭**）；
3. 采集侧打开 `CollectConfig.seq_aux=True`（脚本按上面条件自动设置）。

日志/记录：

- `[ppo] epoch i/n ... seq=0.6970`（epoch 行末尾，仅启用时出现）；
- `[iter i] samples=... total=... seq=0.6970 seq_coef=0.02`；
- `history.jsonl` 的 `ppo` 记录新增 `seq_loss`（各 epoch 均值）、`seq_coef`（本 iteration
  实际系数）、`seq_coef_ramp`；每个 epoch 记录里也有 `seq_loss`；
- `summary.json` 在启用时额外写 `seq: {enabled, ramp, ramp_total_decisions, coef_final, cum_decisions}`；
- `PPOBatch.summary()` 在启用时额外写 `seq_target_rate` / `seq_target_density`。

判读：`seq_loss` 起点 ≈ 0.693，能稳定下降到 0.65 以下说明 trunk 学到了回合内动作结构；
若长期不动或主指标（mean rank）变差，把 `--seq-coef` 降回 0.005–0.01 或关掉。

## 7. 默认关闭 = 零影响（证据）

关闭（默认）时：

- `CollectConfig.seq_aux=False` -> 不构造标签，batch 无 `seq_target` 字段；
- `PPOConfig.seq_coef=0` -> 不走 `forward_aux`、不加 `seq_coef*seq_loss` 项、
  `ppo_losses()` 返回键与旧版完全相同；
- `train_ppo()` 的 stats 里**不出现** `seq_loss/seq_coef/seq_coef_ramp`，连 `config` 回显里的
  这两个键也会被剔除；`[ppo] epoch` 行不带 `seq=`；
- `PPOBatch.save()` 不写 `seq_target` 数组（npz 字段与旧版一致）；`BATCH_FIELDS` 未变，
  新增的是 `BATCH_OPTIONAL_FIELDS = ("seq_target",)`；
- `train_entity_sync.py` 关闭时不打印 `[seq]`、`summary.json` 无 `seq` 段。

回归证据（同机 CPU，`--arch tiny --games 2 --iterations 1 --sims 0 --opponent bot --seed 0`）：

| 对比 | 结果 |
|---|---|
| HEAD（`git archive HEAD` 的旧代码）vs 新代码 `--seq-coef 0`：`history.jsonl` 记录（剔除纯计时字段） | **完全相同** |
| 同上：`ppo.epochs` 指标（total/policy/value/aux_pi/entropy/kl/clip/ratio/...） | **逐位相同** |
| 同上：落盘 `model.pt` 全部权重 | **逐位相同**（`seq_head` 参数不存在） |
| 同上：`ppo.samples` / `collect.decisions` / `records` | 130 / 130 / 130，一致 |
| 新代码 `--seq-coef 0` vs `--seq-coef 0.02` | 仅启用侧多 `seq_*` 字段，训练按期望不同 |

单测另外锁定：带 `seq_target` 的批次在 `seq_coef=0` 下训练出的权重与不带标签的批次
**逐位相同**；`coef=0` 时 `seq_head` 参数梯度为 `None`（完全不动）。

## 8. 已知局限

1. **标签含未来动作（leaky / off-policy）**：`seq_target` 包含当前步之后到回合结束的动作，
   等价于给网络看了一点"未来"。它只通过 `seq_coef` 加权进辅助项，**不是**策略/价值目标；
   推理（`PPOEvaluator` / `PPOGreedyPolicy` / MCTS 叶评估）完全不使用 seq 头，所以不会
   在评测时泄漏信息。它仍会通过共享 trunk 间接影响策略表征，系数过大可能让策略变"过于
   确定"（倾向于预测自己过去的动作模式），建议 0.005–0.05。
2. **`turn` 缺失时退化为整局**：record 的 `turn` 来自引擎 `game.turn`；如果换成没有 `turn`
   属性的假对象（部分单测/玩具环境）则记 `-1`，同座位整局的 action 会被并成一组，
   标签变宽。真实引擎路径不会触发。
3. **Rust 全采集器（`--rust-collector 1`）暂不产出标签**：SoA 由 Rust 侧直接打包，没有
   `seq_target`。训练脚本会打印一次 warn，该批次 `seq_loss=0`（不崩、不制造假梯度）。
4. **只有 learner 座位的动作被记录**：`opponent=bot/weak` 时标签只描述 learner 自己的
   回合动作（其余座位的动作没有 record），这与"只监督学习者"的意图一致；自对弈
   （8 座）则每座位各有标签。
5. **标签密度极低**（每样本 245 位里通常只有几位为 1，典型密度 ~4e-3）：普通 BCE 会被
   "全 0 维"主导，损失数值天然贴近 0.693。若希望更强调正例，可以后续加
   `pos_weight`（本实现未加，保持与论文口径无关的简单形式）。
6. **ramp 预算的分母是显式参数**：`--seq-ramp-total-decisions` 缺省 3e7 只是经验值；
   按分钟跑的训练请显式给出（或用 `--stop-at-decisions`）。进度用"上一 iteration 结束
   时的累计 decisions"，因此第一个 iteration 的系数是 ramp 在 0 处的值。
7. **续训旧 checkpoint 会静默放弃 seq**（有 warn）：旧 checkpoint 没有 `seq_head` 参数，
   当前实现选择"打印 warn + 本轮关闭"，而不是随机初始化一个新头。
8. **`seq_target` 占内存/传输**：`uint8[n,245]` ≈ 245 B/样本（30k 样本 ≈ 7.3 MB，
   相比 3227 float32 特征的 12.9 KB/样本可忽略）；npz/进程间只在启用时多这一个数组。

## 9. 测试清单（`tests/test_az_seq_aux.py`，24 项）

| 用例 | 覆盖 |
|---|---|
| `test_seq_targets_multi_hot_same_turn` | 同回合多动作并集、跨回合/座位/局隔离、uint8、本步位必为 1 |
| `test_seq_targets_missing_turn_degrades_to_game_scope` | 局限 2 的显式行为 |
| `test_seq_targets_empty_and_invalid_action` | 空输入 / 越界动作报错 |
| `test_seq_targets_from_packed_matches_records` | SoA 路径与 records 路径一致 |
| `test_seq_bce_loss_matches_manual` | BCE 数值与手算一致（含权重、全 0 权重不 NaN） |
| `test_parse_coef_ramp_and_interpolation` / `test_parse_coef_ramp_rejects_bad_specs` / `test_resolve_coef_and_schedule_bounds` | ramp 解析、插值、两端 clamp、单点、空 spec、非法 spec、按 decisions 进度 |
| `test_ppo_config_validates_seq_fields` | `seq_coef>=0`、ramp 提前校验 |
| `test_collect_config_default_seq_off` / `test_batch_fields_unchanged_and_optional_only` | 默认关闭、`BATCH_FIELDS` 未变 |
| `test_build_batch_from_records_seq_off_has_no_labels` | 关闭时无字段、npz 无 `seq_target`、summary 无 seq 键 |
| `test_build_batch_from_records_seq_on_labels_and_validation` | 开启时标签正确、validate、npz 往返 |
| `test_batch_validate_catches_bad_seq_target` | 0/1 校验 + "本步动作未标"校验 |
| `test_build_batch_from_arrays_tolerates_missing_seq_target` | **batch builder 处理缺字段**、形状不符忽略 |
| `test_seq_coef_zero_adds_no_field_and_no_gradient` | coef=0：无 seq 键、seq 头无梯度、训练 stats/权重与无标签完全一致 |
| `test_seq_loss_ignores_forced_samples` | **forced 样本不参与 seq loss**（改标签不影响）、空标签行被排除、手工核对 |
| `test_train_ppo_seq_coef_reports_and_trains_head` | stats/epoch 日志字段、seq 头被更新、total 里确含 `coef*seq_loss` |
| `test_seq_bce_loss_is_minimizable` | 梯度下降能把 BCE 压到 ~0（目标可达） |
| `test_seq_loss_zero_when_batch_has_no_labels` | 缺标签 -> 0，且 total 有限 |
| `test_model_forward_aux_shapes_and_checkpoint_roundtrip` | `forward_aux` 形状、`forward` 不变、checkpoint 保留/不保留 seq 头 |
| `test_entity_forward_aux` | entity 版本（需要 `hsbg_engine` 建卡表） |
| `test_entry_scripts_expose_seq_flags` | 两个入口都暴露 `--seq-coef` / `--seq-coef-ramp` |
| `test_json_roundtrip_of_stats_with_seq` | stats 可 JSON 序列化（history.jsonl 直接写） |

## 10. 改动清单（实现导航）

| 文件 | 位置 | 内容 |
|---|---|---|
| `hsbg/az/train/seq_aux.py` | 新文件 | `seq_targets_from_records/_packed`、`parse_coef_ramp`、`ramp_coef`、`resolve_coef`、`SeqCoefSchedule`、`seq_bce_loss`、`SEQ_TARGET_KEY` |
| `hsbg/az/train/ppo.py` | `CollectConfig.seq_aux` | 采集侧是否产出标签（默认 False） |
| | `PPOConfig.seq_coef` / `seq_coef_ramp` | 损失权重与 ramp 规格（含提前校验） |
| | `BATCH_OPTIONAL_FIELDS` / `PPOBatch.seq_target` | 可选批次字段（save/load 只在存在时写读） |
| | `PPOBatch.validate/summary` | 0/1 + 本步动作校验、标签密度摘要 |
| | `forward_model_aux` | 统一取 seq logits（无 `forward_aux` 时返回 None） |
| | `ppo_losses` | `seq_coef*BCE(valid & ~forced)`，关闭时无键 |
| | `train_ppo` | epoch 日志 `seq=`、stats 的 `seq_*` 字段（关闭时剔除） |
| | `build_batch_from_records/pack_records_arrays/build_batch_from_arrays` | `seq_aux` 开关与透传 |
| `hsbg/az/train/model.py` | `build_net(..., seq_head=)`、`TinyAZNet.forward_aux`、checkpoint | tiny seq 头 |
| `hsbg/az/train/entity_model.py` | `build_entity_net(..., seq_head=)`、`forward/_forward_impl/forward_aux` | entity seq 头（global token） |
| `hsbg/az/train/parallel_collect.py` | `collect_ppo_batch_parallel` | 透传 `cfg.seq_aux` |
| `hsbg/az/train/process_pool.py` | worker `pack_records_arrays`、`_save_built_batch`、父进程合并 | 多 shard 的 `seq_target` 拼接 |
| `scripts/train_entity_sync.py` | `--seq-coef/--seq-coef-ramp/--seq-ramp-total-decisions`、ramp 逐 iter 生效、`[iter] seq=`、`summary.seq` | 主训练入口 |
| `scripts/train_az_ppo.py` | 同上（单轮，ramp 进度 0）+ report/ckpt 记录 | 单轮入口 |
| `tests/test_az_seq_aux.py` | 新文件 | 24 项单测 |
| `docs/ACTION_SEQUENCE_AUX.md` | 本文 | 设计/实现/开启/局限 |

顺带修掉一个既有 bug：`scripts/train_entity_sync.py` 的 `--leaf-amp` help 里有裸 `%`
（`约 -5%`），会让 `argparse` 打印帮助时抛 `ValueError: unsupported format character`；
已改为 `-5%%`。
