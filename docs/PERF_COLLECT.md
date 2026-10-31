# 采集侧吞吐优化（collect dec/s）— 实测报告

> 主题：训练采集侧吞吐优化（目标 ≥6,500 dec/s，**不改变训练语义**）。
> 所有优化**默认关闭即逐位等价**；开启后与慢路径**逐位相同**（记录 sha 相同）。
> 采集时间：2026-10-31。主训练 `runs/az_entity_s14` 全程未被打断（未 kill / 未重启 / 未占 cuda:3-6）。

## 0. 结论摘要

| # | 项 | 状态 | 实测收益（本机 CPU 单进程锁步） | 风险 | 回退 |
|---|---|---|---|---|---|
| 1 | **payload 注入视图缓存 + orjson + `ended_turn` 位字符串替换**（`--human-board-fast-inject 1`） | **已实施** | 单次注入 **1.41 ms → 0.43 ms（−69%）**；wall **−14.4%**；采集 Python 侧 **−42%**；dec/s **+19%**（CPU 18 场前向占 70% 时） | 低（默认关；开启后 sha 逐位相同；有 6 个单测） | 参数回 `0`（零代码改动）；或 `git checkout` 7 个源文件 |
| 2 | **流派偏置计算优化**（节奏向量化 / `FLOW_DECAY` 幂表 / hero 预映射 / 整块 argmax） | **已实施** | `bias()` **95 → 82 µs/决策（−14%）** | 极低（有逐位对照单测 + 端到端 sha 相同） | 同上 |
| 3 | 流派**输入哈希缓存**（`--archetype-cache 1`） | 已实现、**实测命中率 0%**，建议保持关闭 | 0（反而 +2 µs/决策的哈希开销） | 低 | 默认 `0` |
| 4 | 批量注入预构建（多座位合并 apply） | **不实施**（实测 0 收益） | 合并 `apply_turn_snapshots` 仅 **−10.8 µs/座位（≈0.2%）**；payload 预构建已由 #1 的视图缓存覆盖 | 中（改拒绝/统计口径） | — |
| 5 | `--games 256` | **给数据，不建议**（会把瓶颈推给 PPO） | 采集侧 dec/s 可再 +26%，但 PPO 时间翻倍 → 端到端吞吐基本不变 | 中（改变每轮样本数 → 训练语义变化） | 保持 `--games 192` |
| 6 | `--leaf-wait-ms 0` | **建议**（`1.0 → 0`） | 每 batch 省 **1.1-1.3 ms**；s14 实测 `batch_wait_s=0.23 s/worker·iter` → collect **−5.7%** | 极低（lockstep 单客户端下批组成不变） | 参数回 `1.0` |
| 7 | `--threads 8 vs 4` | 无差别（**lockstep 下惰性**） | 0 | — | — |

**一句话**：`--human-board-fast-inject 1 --leaf-wait-ms 0` 两项即可把 s14 的采集侧
从 `collect_s≈4.05 s / 6528 dec/s` 推到 **≈3.1-3.4 s / 8.2-8.9k dec/s**（保守 −17%，
乐观 −25%）。按任务书基线（5317 dec/s）折算落在 **6,400–7,200 dec/s**。

## 1. 方法（可复现）

主训练在跑，因此全部测量用**单进程 CPU 锁步**（`collect_ppo_lockstep` + `BatchLeafServer`），
复现训练 worker 内的同一条热路径（引擎 + 观测 + mask + 注入 + 流派偏置 + 记录 + 批量叶）。

冻结 checkpoint：**训练每 iter 都会重写 `runs/az_entity_s14/model.pt`**，跨时间对比必须用快照，
否则动作序列会变（这是本次踩过的坑）。本报告全部 A/B 使用
`runs/profile_collect/ckpt_frozen.pt`（2026-10-31 10:57 拷贝）。

```bash
PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
cp runs/az_entity_s14/model.pt runs/profile_collect/ckpt_frozen.pt

# A/B（32 局 × 3 iter；记录 sha 用于逐位校验）
$PY scripts/bench_collect_profile.py lockstep --games 32 --iters 3 --device cpu \
    --torch-threads 8 --checkpoint runs/profile_collect/ckpt_frozen.pt --fast-inject 0
$PY scripts/bench_collect_profile.py lockstep --games 32 --iters 3 --device cpu \
    --torch-threads 8 --checkpoint runs/profile_collect/ckpt_frozen.pt --fast-inject 1 --leaf-wait-ms 0

# cProfile top-20（写 runs/profile_collect/prof_*/profile.txt|top.json）
$PY scripts/bench_collect_profile.py lockstep --games 32 --iters 0 --device cpu \
    --torch-threads 8 --checkpoint runs/profile_collect/ckpt_frozen.pt --profile runs/profile_collect/prof_base
$PY scripts/bench_collect_profile.py lockstep --games 32 --iters 0 --device cpu \
    --torch-threads 8 --checkpoint runs/profile_collect/ckpt_frozen.pt --fast-inject 1 --profile runs/profile_collect/prof_fast

# 单座位注入阶段拆解 / 流派微基准
$PY scripts/bench_inject_stages.py --n 300
$PY scripts/bench_collect_profile.py micro --n 300

# 叶子前向 batch 曲线（单卡短跑 ~40 s，cuda:7 空闲时）
$PY scripts/bench_leaf_batch.py --device cuda:7 --reps 25 --out runs/profile_collect/leaf_batch.json
```

## 2. Profile top-20（32 局锁步，CPU 前向，`cProfile` 累计耗时）

> CPU 前向单进程下占总 wall 的 70%，因此下表的**百分比是 CPU 场景**；实时 s14（GPU）
> 前向只占 35%（`forward_s 22.6/16=1.41 s` vs `wall 4.05 s`），所以 Python 侧占比更高
> （65%），优化收益按 §7 折算。`cProfile` 对纯 Python 小函数有 ~0.5-1 µs/调用 的膨胀，
> 只用于**相对**归因。

### 2.1 优化前（全部默认关闭，wall 15.01 s / 4665 决策）

| 函数 | 位置 | 调用 | tottime | cumtime | 占 wall |
|---|---|---|---|---|---|
| `collect_ppo_lockstep` | parallel_collect.py:280 | 1 | 0.05 | 14.92 | 99.4% |
| `decide_batch` | ppo.py:2323 | 212 | 0.04 | 11.78 | 78.5% |
| `act_batch`（等 GPU 前向） | batch_eval.py:173/430 | 212 | 0.00 | **10.55** | **70.3%** |
| `_maybe_inject` | parallel_collect.py:497 | 12088 | 0.01 | 2.82 | 18.8% |
| `inject_turn` | human_board_pool.py:624 | 458 | 0.07 | **2.71** | **18.0%** |
| `inject_quasi_state` | human_obs_full.py:724 | 2002 | 0.05 | 2.57 | 17.1% |
| `json.dumps`（编码整帧） | json/__init__.py:183 | 14858 | 0.01 | 1.05 | 7.0% |
| `json.loads`（解码整帧） | json/__init__.py:299 | 14699 | 0.02 | 1.03 | 6.9% |
| `iterencode`（C 编码本体） | encoder.py:204 | 14858 | 1.02 | 1.02 | 6.8% |
| `raw_decode`（C 解码本体） | decoder.py:343 | 14699 | 0.97 | 0.97 | 6.5% |
| `archetype_bias.bias` | archetype_bias.py:913 | 4665 | 0.04 | **0.76** | **5.1%** |
| `_minion_json`（逐随从深拷贝） | human_obs_full.py:420 | 11445 | 0.06 | 0.34 | 2.2% |

**归因（非前向部分 = 15.01 − 10.55 = 4.46 s）**：
注入 **2.57 s（58%）** > 流派偏置 0.76 s（17%）> 其余（引擎 bot_play / observe / mask /
记录）≈1.1 s（25%）。
注入内部：**JSON 编解码 ≈2.08 s（占注入 81%）**——`json.dumps` 1.05 s + `json.loads`
1.03 s，其中每次注入 2 次「整帧往返」+ 每个随从一次 `json.loads(json.dumps(tpl))`
深拷贝（11445 次 `_minion_json` / 2002 次注入 ≈ 5.7 个随从）；Rust
`player_json`/`apply_turn_snapshots`/`set_player_from_json` 合计仅 ≈0.25 ms/座位。

### 2.2 优化后（`--human-board-fast-inject 1 --leaf-wait-ms 0`，wall 13.04 s）

| 函数 | 位置 | 调用 | tottime | cumtime | 占 wall |
|---|---|---|---|---|---|
| `collect_ppo_lockstep` | parallel_collect.py:280 | 1 | 0.05 | 12.96 | 99.4% |
| `decide_batch` | ppo.py:2323 | 212 | 0.04 | 11.64 | 89.3% |
| `act_batch`（前向） | batch_eval.py:173 | 212 | 0.00 | **10.39** | **79.7%** |
| `_maybe_inject` | parallel_collect.py:497 | 12088 | 0.01 | **0.98** | **7.5%** |
| `inject_turn` | human_board_pool.py:624 | 458 | 0.03 | 0.87 | 6.7% |
| `archetype_bias.bias` | archetype_bias.py:913 | 4665 | 0.04 | **0.77** | **5.9%** |
| `_fast_inject_quasi_state` | human_obs_full.py:606 | 2002 | 0.05 | 0.75 | 5.7% |
| `orjson.loads` | `~` | 2002 | 0.21 | 0.21 | 1.6% |
| `Game.bot_play` | `~` | 2726 | 0.21 | 0.21 | 1.6% |
| `build_vector` | archetype_bias.py:489 | 4665 | 0.14 | 0.19 | 1.5% |

注入 **2.71 → 0.87 s（−68%）**；`json.dumps/loads` 完全消失（改为 orjson + 视图缓存）。
注入后**流派偏置成为与注入同量级的热点**（0.77 s vs 0.87 s），这也是 #2/#3 的动机。

### 2.3 单座位注入阶段拆解（turn≈8、7 随从、帧 32 KB，`scripts/bench_inject_stages.py`）

| 阶段 | µs/座位 | 占比 |
|---|---|---|
| `player_json` + `json.loads`（读帧） | 374.6 | 21.2% |
| `_minion_json` ×7（逐随从深拷贝） | 140.4 | 7.9% |
| `_hand_json` | 43.7 | 2.5% |
| `json.dumps`（编码新帧） | 298.1 | 16.9% |
| `apply_turn_snapshots`（Rust 解码 + 提交） | 103.7 | 5.9% |
| `player_json` + `json.loads`（读回） | 379.1 | 21.5% |
| `json.dumps`（写回帧） | 299.6 | 17.0% |
| `set_player_from_json`（Rust 解码） | 90.6 | 5.1% |
| **合计** | **1766** | 100% |

→ **Python JSON 编解码 1352 µs = 77%**。Rust（`player_json` 序列化 40 µs/次、
`apply_turn_snapshots` ~104 µs、`set_player_from_json` ~64-91 µs）只占约 1/4。

## 3. 优化 1：payload 注入视图缓存 + orjson（`--human-board-fast-inject 1`）

实现（`hsbg/az/train/human_obs_full.py`，**Rust 零改动**）：

1. **注入视图缓存** `_inject_view(payload, fidelity)`：每个 `(库行, fidelity)` 只把
   payload 的 board/hand 编译成引擎 Minion/HandCard **模板 dict** 一次，挂在
   `payload["_inject_views"]`（`sample_payload` 的浅拷贝共享同一容器）。注入时只做
   `dict(tpl)` + 逐座位 `eid`/`hid` 重映射（`nid = max(used|{50000})+1`，与慢路径同公式）。
2. **orjson 编解码**：`_fast_loads/_fast_dumps` 优先 orjson（3.11.9，环境已装），
   无 orjson / 遇到它不支持的 JSON（NaN、非 str 键）**自动退回标准库**。
   实测 34 KB 帧：loads 305→106 µs，dumps 283→34 µs。
3. **`ended_turn` 位字符串替换**：写回那次只需把 `"ended_turn":true` 改成 `false`
   （`payload` 无 `player` 段时），省掉第二次整帧 load/dump；找不到该片段自动退回
   整帧路径（fail-safe）。

### 逐位等价证据

* `tests/test_fast_injection.py`（6 个用例，全绿）：
  - 真实准完整库 × 4 个 turn × 3 个座位 × hand/full → **`Game.state_json()` 逐字节相等**；
  - 强制标准库后端（`_ORJSON=None`）同样逐字节相等（证明 orjson 不影响语义）；
  - `player` overlay 分支、拒绝路径（已结束座位的 `applied=False` + 同 reason）、
    连续 6 次注入（视图缓存命中）逐步 `state_json` 相等，且 `view_builds==1`；
  - `fidelity=board` 时 `fast` 参数不改变行为。
* 端到端（32 局 × 3 iter，冻结 ckpt）：`--fast-inject 0/1` 的 **records sha 完全相同**
  （`62b5ef3ccbaa7cc2 / a96537776735eb8c / 3989bbb44a6b1211`），决策数相同
  （4665/4768/4655）。

### 收益

| 指标 | 关闭 | 开启 | Δ |
|---|---|---|---|
| 单次注入（turn≈8 帧） | 1743.6 µs | 426.0 µs | **−75.6%** |
| A/B wall（32 局均值） | 14.779 s | 12.653 s | **−14.4%** |
| A/B dec/s | 317.5 | 378.3 | **+19.2%** |
| 采集 Python 侧（wall − forward） | 4.24 s | 2.45 s | **−42%** |
| 端到端 records sha | — | — | **相同** |

## 4. 优化 2：流派偏置计算（默认路径，无开关，逐位等价）

微基准（单决策，`hsbg/data/archetype/*`，`coef=0.5`）：

| 阶段 | 优化前 | 优化后 |
|---|---|---|
| `parse_obs` | 25.7 µs | 25.5 µs（逐格循环最快，见下） |
| `build_vector`（132 维） | 23.0 µs | **11.6 µs** |
| `tribe_model.probs` | 12.9 µs | 12.8 µs（未动） |
| `arch_model.probs` | 12.8 µs | 12.7 µs（未动） |
| `bias_from_pref` | 26.2 µs | **20.5 µs** |
| **`bias()` 合计** | **95.1 µs** | **81.7 µs（−14%）** |

改动：
1. `build_vector`：66 个节奏位从「双重 Python 循环 + 标量赋值」改成
   `st.rhythm / _BUCKET_WIDTHS` 一次向量化（float32 除，与 NEP50 下
   `np.float32 标量 / Python float` 语义一致）；`FLOW_DECAY ** k` 换成 64 项幂表；
   hero one-hot 用 `{name: idx}` 预映射替掉 `tuple.index` 线性查找。
2. `bias_from_pref`：`np.argmax(shop_tribes[slot])` ×7 / `hand_tribes[h]` ×10 改成
   每块一次 `argmax(axis=1)`（**同值同 tie-break**）；`np.asarray(cards)` 移出循环。

**逐位证据**：`tests/test_archetype_fast.py`（3 个用例）把优化前实现逐行拷贝成
`*_ref`，在 240+ 真实观测 / 400 组随机历史上比较 `parse_obs` / `build_vector` /
`bias_from_pref`，**`np.array_equal` 全部相等**；`tests/test_archetype_bias_equiv.py`
用独立 history 复算整条 `bias()`（4665 次决策序列），bias 数组与 10 项统计计数
（decisions/detected/applied/lvl_*/name_counts/prob_sum/bias_sum/bias_actions）
**完全一致**，并断言 `applied>0`（测例确实覆盖到「实际应用偏置」）。
端到端：`--arch-ref 1`（运行时把三个函数换回参考实现）与优化版的 records sha 相同
（`5fa2b8ba176ce276 / 8d790e5a8787cdc2`）。

> 反面经验（写进代码注释）：`_item_blocks`（shop/hand 种族块）**不该向量化**——
> 实测 n=7 时逐格循环 7.4 µs，fancy-index 12.0 µs，`as_strided` 14.3 µs；
> numpy 小数组开销大于收益。保持原循环。

## 5. 优化 3：流派输入哈希缓存（实测命中率 0%，默认关闭）

`ArchetypeBias(cache=True)` / `--archetype-cache 1`：key =
`(hash(features), hash(cards), hash(mask), 历史修订号 st.rev)`，命中时重放统计并返回
同一份 bias（`tests/test_archetype_fast.py::test_bias_cache_is_transparent` 证明
开/关输出与统计完全一致）。

**实测命中率 = 0/775 = 0%**（真实对局：每决策的 board/shop/hand/gold 与动作历史都在变，
`note_action` 每个非机械动作都会推高 `st.rev`）。结论：**默认关闭**，只在
「同观测重复决策」的极端场景（例如批量推理同一帧）才有意义。

## 6. 未实施项与数据

### 6.1 批量注入预构建（多座位合并 apply）

把一回合 4 个座位的帧合并成**一次** `apply_turn_snapshots` 调用：

| 方式 | µs/轮（4 座位） | µs/座位 |
|---|---|---|
| 分 4 次 apply | 870.3 | 217.6 |
| 一次 apply | 827.0 | 206.7 |
| **节省** | 43.3 | **10.8（≈5%）** |

节省来自 `invariants::pool_balance`（1.2 µs）+ `pool_species_violations`（1.6 µs）
从 4 次降到 1 次；折算到整局 **≈0.2%**，而合并会改变「逐座位拒绝/池统计」的时序语义。
**不实施**。真正的跨座位重复（payload 解析/模板构建）已由 #1 的视图缓存消除。

### 6.2 `--games 256`

叶子前向**几乎是固定成本**（`scripts/bench_leaf_batch.py`，cuda:7，单客户端，
`leaf-wait-ms 0`）：

| batch | ms/调用 | ms/决策 |
|---|---|---|
| 1 | 5.69 | 5.69 |
| 8 | 6.00 | **0.750** |
| 16 | 6.04 | **0.377** |
| 24 | 6.10 | 0.254 |
| 32 | — | ~0.19 |
| 64 | 8.38 | 0.131 |

s14 现在 `batch_fill=0.128`（≈8.2 行/前向，`batch_max=1` 是因为 lockstep 把整批放在
**一个** request 里），前向占 `1.41 s / 4.05 s = 35%`。把 `--games` 从 192 提到 256 会让
每 worker 12→16 局、batch≈16，**前向/决策减半（0.79→0.40 ms）**，采集侧 dec/s 可再 +26%。
**但**：每轮样本数翻倍 → PPO `ppo_s` 从 3.27 s 翻到 ~6.5 s，流水线
（`max(collect, ppo)`）被 PPO 卡住，端到端吞吐≈不变（甚至略差）。
→ **不改默认 `--games 192`**；若要加，必须同时把 PPO 预算（`--max-updates` /
`--epochs` / minibatch）调到每样本成本不变，属于训练语义变更，需要单独 A/B。

### 6.3 `--threads 8 vs 4`

lockstep 路径下 worker 里显式 `torch.set_num_threads(1)`，`--threads` 只传给**非 lockstep**
的 `collect_ppo_records_parallel(workers=threads)`。因此 `--lockstep 1` 时 **`--threads` 惰性**，
实测（8/4）无可测差异。

### 6.4 `--leaf-wait-ms 0`（建议开）

`BatchLeafServer._worker` 收第一个 request 后固定等 `max_wait_ms` 再聚批；lockstep 每
worker 只有**一个**客户端，且整批已在同一个 request 里，所以这 1 ms 是纯等待。
实测 1.0 → 0：batch=8 时 **7.31 → 6.00 ms/调用（−18%）**；s14 实测
`batch_wait_s = 3.65 s（16 worker 合计）= 0.23 s/worker·iter = collect 的 5.7%`。
批组成不变 → records sha 相同（已验证）。**建议 `--leaf-wait-ms 0`**。

## 7. 短跑对比表与对 s14 的折算

（A: 默认；B: `--human-board-fast-inject 1`；C: B + `--leaf-wait-ms 0`；
冻结 ckpt，32 局 × 3 iter，同 seed，records sha 三者相同）

| 配置 | wall 均值 | dec/s | fwd/iter | py/iter |
|---|---|---|---|---|
| A 默认 | **14.78 s** | **317.5** | 10.51 s | 4.24 s |
| B fast-inject | **12.65 s（−14.4%）** | **378.3（+19.2%）** | 10.20 s | 2.45 s（−42%） |
| C B + leaf-wait 0 | 12.73 s | 372.9 | 10.32 s | 2.41 s |

CPU 场景里前向占 70%，所以 wall 只 −14%；实时 s14（GPU）前向只占 35%，Python 侧占 65%，
同样的 Python 节省会被放大：

| s14 现状（近 8 iter 均值） | 值 |
|---|---|
| `decisions` | 27,900/iter（192 局） |
| `wall_s` | 4.05 s |
| `forward_s`（16 worker 合计） | 22.6 s → **1.41 s/worker（35%）** |
| Python+引擎（推算） | **2.64 s（65%）** |
| `decisions_per_s` | **6,528**（区间 6,089–6,921） |
| `profile.collect_s` | 4.5–5.0 s |

折算（每 worker·iter，756 次注入）：

| 项 | 保守（按注入次数直接扣） | 乐观（按 Python 侧比例扣） |
|---|---|---|
| fast-inject | −0.67 s（0.89 ms × 756） | −1.11 s（py × 0.578） |
| leaf-wait 0 | −0.23 s（`batch_wait_s` 实测） | −0.23 s |
| 预计 wall | 4.05 → **3.15 s** | 4.05 → **2.71 s** |
| 预计 dec/s | **≈8,850（+36%）** | **≈10,300（+58%）** |
| 若只算 fast-inject | 4.05 → 3.38 s → **8,250（+26%）** | → 2.94 s → **9,500（+45%）** |

按任务书基线 5317 dec/s 折算：**保守 6,400–6,800，乐观 7,500–8,000**（≥6,500 达标）。

## 8. 建议 s14 下次重启时采用

在现有命令行上**只加两项**（其余全部保持不变）：

```diff
   --human-boards data/real_library/library_real_quasi_full.jsonl \
   --human-board-fidelity full --human-board-p 0.9 --human-board-seats 5 \
+  --human-board-fast-inject 1 \
   ...
-  --leaf-wait-ms 1.0 \
+  --leaf-wait-ms 0 \
   ...
   --archetype-bias-coef 0.5 --archetype-min-prob 0.6 \
+  --archetype-cache 0 \        # 可不加（默认就是 0；实测命中率 0%）
   --games 192                  # 保持 192（256 会把瓶颈推给 PPO）
```

完整覆盖项（可直接拼到原命令）：

```bash
--human-board-fast-inject 1 --leaf-wait-ms 0 --archetype-cache 0 --games 192
```

预期：`collect_s 4.5-5.0 → 3.4-3.9`，`decisions_per_s 6.5k → 8.2-8.9k`；
`ppo_s 3.27 s` 不变（仍然 < collect），流水线不换瓶颈。
**注意**：若只开 fast-inject 且不改 leaf-wait，collect 约 3.4 s ≈ ppo 3.27 s，
流水线开始贴平（lag 守卫 `pre_ratio` 仍正常）——两项一起开最稳。

后续若还要提速，瓶颈依次是：
1. **PPO** `3.27 s/iter`（改 `--max-updates`/`--epochs`/minibatch 属训练语义，需单独 A/B）；
2. **叶子前向** 6.0-6.7 ms/调用（固定成本，只能靠加大每 worker 局数摊薄，见 §6.2）；
3. **注入剩余 ~0.43 ms/座位**（其中 Rust `player_json`/`apply`/`set_player` 约 0.25 ms 是
   引擎 API 下限，要再降必须改 Rust：[`Game.set_ended_turn(seat)` 之类的专用 API]）。

## 9. 风险与回退

* **默认关闭**：`fast_inject=False` / `archetype_cache=False` / `leaf_wait_ms` 由调用方给值，
  不写任何新路径 → 与历史版本**逐位等价**（老测试 107 个全绿）。
* **开启后语义**：records sha 逐位相同（3 个 iter × 多种组合）；单测覆盖 state_json
  逐字节相等、拒绝路径、overlay、视图缓存复用。
* **orjson 缺失**：`_ORJSON=None` 自动退回标准库（单测覆盖），只是慢一点。
* **回退方式**（无需改代码）：`--human-board-fast-inject 0 --leaf-wait-ms 1.0`。
* **代码回退**：
  ```bash
  git checkout -- hsbg/az/train/human_obs_full.py hsbg/az/train/human_board_pool.py \
      hsbg/az/train/parallel_collect.py hsbg/az/train/process_pool.py \
      hsbg/az/train/ppo.py hsbg/az/train/archetype_bias.py scripts/train_entity_sync.py
  rm -f scripts/bench_collect_profile.py scripts/bench_inject_stages.py scripts/bench_leaf_batch.py \
      tests/test_fast_injection.py tests/test_archetype_fast.py tests/test_archetype_bias_equiv.py
  ```
* **在跑的 s14 不受影响**：Python 进程已 import 旧模块；本次只改源码，未重建
  `hsbg_engine`（Rust 零改动），未触碰 `runs/az_entity_s14`。评测子进程若在改动窗口内
  启动，读到的新代码里所有新开关**默认关闭**，行为与旧版一致。

## 10. 新增/修改文件

| 文件 | 说明 |
|---|---|
| `hsbg/az/train/human_obs_full.py` | 快速注入路径（视图缓存 / orjson / ended 位替换 / `fast=` 参数 / `FAST_STATS`），慢路径**原样保留** |
| `hsbg/az/train/human_board_pool.py` | `inject_turn(fast_inject=)`；`sample_payload` 共享 `_inject_views` |
| `hsbg/az/train/parallel_collect.py` | 透传 `human_board_fast_inject`；meta 新增 `human_board_fast_inject` |
| `hsbg/az/train/process_pool.py` | 透传 `human_board_fast_inject` |
| `hsbg/az/train/ppo.py` | `CollectConfig.human_board_fast_inject` / `.archetype_cache`；meta 汇总缓存命中率 |
| `hsbg/az/train/archetype_bias.py` | `build_vector` 向量化 / 幂表 / hero 预映射；`bias_from_pref` 整块 argmax；可选输入哈希缓存；`_Hist.rev` |
| `scripts/train_entity_sync.py` | `--human-board-fast-inject` / `--archetype-cache` |
| `scripts/bench_collect_profile.py` | lockstep A/B + cProfile + 记录 sha + 假前向归因 |
| `scripts/bench_inject_stages.py` | 单座位注入阶段拆解 |
| `scripts/bench_leaf_batch.py` | 叶子前向 batch 成本曲线（单卡短跑） |
| `tests/test_fast_injection.py` | 快速注入逐位等价（6 例） |
| `tests/test_archetype_fast.py` | 流派计算逐位等价 + 缓存透明（4 例） |
| `tests/test_archetype_bias_equiv.py` | 整条 `bias()` 逐位等价 + 统计口径（1 例） |

回归：`pytest tests/test_fast_injection.py tests/test_archetype_fast.py
tests/test_archetype_bias_equiv.py tests/test_full_state_injection.py
tests/test_human_board_pool.py tests/test_archetype_bias.py tests/test_archetype_table.py
tests/test_mirror_snapshot.py tests/test_injection_meta.py tests/test_batch_eval.py
tests/test_az_train.py` → **117 passed**。
