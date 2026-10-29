# 牌面强度校准：真实 10k+ MMR 观测 vs 自采镜像库

> **状态**：只读校准，未训练、未用 GPU、未改引擎。
> **产物**：脚本 [`scripts/calibrate_strength.py`](../scripts/calibrate_strength.py)、
> 数据 [`data/real_library/strength_calibration.json`](../data/real_library/strength_calibration.json)、
> 本文件；单测 [`tests/test_calibrate_strength.py`](../tests/test_calibrate_strength.py)。
> **复现**：
>
> ```bash
> PYTHONPATH=rust/python:. python scripts/calibrate_strength.py --report
> pytest tests/test_calibrate_strength.py -q
> ```

## 0. 结论摘要（先看这里）

| 区间 | 结论（`ratio = real / ours`，>1 表示我们偏弱） |
|---|---|
| turn 1–2 | 我们**偏强**（p50 比值 0.38 / 0.40），但这是采集偏差：快照采集带 `min_board=2` 过滤，turn 1 只剩 4 帧；**不能当成真实低 turn 分布** |
| turn 3–7 | 基本同档：p50 比值 **0.76–1.05**，p90 比值 **0.94–1.32**；turn 5–6 几乎重合 |
| turn 8–9 | 开始偏弱：p50 **1.36× / 1.79×**，p90 **1.79× / 2.74×** |
| turn 10–12 | 明显偏弱：p50 **2.79× / 4.08× / 6.66×** |
| turn 13–15 | 数量级差距：p50 **12.9× / 21.3× / 25.4×**（p90 8.0×–14.1×） |
| turn 16–18 | 样本极少（真实 14/2/0 行，我们 9/6/2 帧），**不可下结论** |
| 可达性 | **turn 10 起我们库的最强帧也低于真实 p50**（t10 max 898 < 1128.5；t15 max 14,800 < 26,516），因此**仅靠分位重采样无法校准到真实中位数**，必须先补强快照来源 |

一句话：**自采库在 turn 3–7 已接近真实 10k+ 中位数；turn 8 起掉队，turn 10 后差距 3–25 倍，且已超出重采样能修的范围。**

> 采样实现：`MirrorSnapshotPool(sample=...)` 现支持 `p50 / p75 / p90 / max` 及任意 `pNN`；
> 每 turn 的推荐档位与用法见 §5.2。

## 1. 数据

| 项 | 真实观测 | 自采快照库 |
|---|---|---|
| 路径 | `data/real_library/obs/observations/*.jsonl` | `runs/library/snaps_champ/snap_*.json.gz` |
| 规模 | 376 文件 / 13,120 行 | 8 文件 / **711 帧**（126 个 `(turn, seat)` 键） |
| schema/版本 | Firestone `firestone-visible-v3` 可见牌面重建 | `hsbg.mirror_snapshots` v1（`mirror_snapshots.SCHEMA_VERSION=1`） |
| 阶段 | 只取 `recruitment_end_at_phase_switch`（4,498 行） | 全部为 `recruitment_end_before_combat`（EOT、战斗前） |
| turn 范围 | 1–17 | 1–18 |
| 元数据 | 4 个旧 build；`perspective=self`；`library_ready=false`、`hidden_counters_complete=false` 全量成立 | 8 局、`driver=model`、`checkpoint=champion_c0_2279.pt`、`temperature=0.7`、`min_board=2`、8 座全由同一模型驱动 |

自采库用 `hsbg/az/train/mirror_snapshots.py` 的 `MirrorSnapshotPool` 读取（不重复实现解析）：

```python
from hsbg.az.train.mirror_snapshots import MirrorSnapshotPool
pool = MirrorSnapshotPool("runs/library/snaps_champ")
frame.strength        # 由 board_strength(player) 预计算：Σ(atk+hp)
```

> `sample=` 只影响 `MirrorSnapshotPool.get(turn, seat)` 在**同键多来源**时的选择；本校准统计
> **全部帧**，因此 `sample` 模式不影响分布。

## 2. 方法

### 2.1 阶段过滤

真实 jsonl 一行是某个座位在某一时刻的可见牌面。只有
`stage == "recruitment_end_at_phase_switch"`（招募结束、战斗开始前）与自采 EOT 快照同义：

| stage | 行数 | 处理 |
|---|---:|---|
| `recruitment_end_at_phase_switch` | **4,498** | 保留（其中 54 行数值缺失被跳过，见下） |
| `first_attack_after_start_effects` | 8,622 | **丢弃并计数**（已含战斗开始效果，与 EOT 不同时点；混入会重复计强度） |

明细（脚本 `--report` 会打印）：

- 13,120 行 → 4,498 行目标 stage → **4,444 行进入分位统计**；
- 跳过 `invalid_minion_stats=54`（`attack`/`health` 为 `null`，质量标记 `incomplete_minion_state`）；
- `bad_json=0`、`missing_turn=0`；
- 空牌面 226 行**保留**（strength=0，它们在真实分布里是真实的空场）；
- `board > 7` 12 行**保留但计数**（质量标记 `invalid_board_positions`，会抬高 p99/max，见 §3）；
- **不做去重**。`import_real_library.py` 会按 `(turn, signature)` 去重；本校准要回答「真实每个
  turn 的强度分布」，保留原始重复行更贴近出现频率，也让 p50 更稳。

### 2.2 strength 定义

与 [`hsbg/az/train/mirror_snapshots.py`](../hsbg/az/train/mirror_snapshots.py) 的
`board_strength` **同一定义**：

- 真实行：`strength = Σ(attack + health)`（字段名 `attack`/`health`）；
- 自采帧：`strength = Σ(atk + hp)`（引擎 Player JSON 字段名 `atk`/`hp`，`SnapshotFrame.strength` 已预计算）。

两者都是「当前攻击 + 当前生命」，**不减 `damage`**。这个代理**忽略**关键词（圣盾/剧毒/风怒/
嘲讽/复生）、光环、亡语和站位，因此**同 strength ≠ 同战力**。

### 2.3 分桶与分位数

- 按 `turn` 分桶（整数 turn 1–18，不做相邻 turn 平滑/插值）；只在一侧出现的 turn 也输出，缺失侧
  `count=0`、其余为 `null`；
- 每个桶输出 `count / p50 / p75 / p90 / p99 / max`；
- 分位数用**线性插值**（与 numpy 默认一致）：`k=(n-1)q`，在相邻 order statistic 间插值；
  单点返回该值，空桶返回 `null`。

### 2.4 输出 schema

```json
{
  "_meta": {"schema": "hsbg.strength_calibration", "version": 1,
            "stage_real": "...", "strength_definition": "...",
            "real": {...}, "ours": {...}},
  "1": {"real": {"count": 362, "p50": 3.0, "p75": 6.0, "p90": 7.0, "p99": 10.4, "max": 13},
        "ours": {"count": 4, "p50": 8.0, "p75": 8.5, "p90": 9.4, "p99": 9.9, "max": 10},
        "ratio_p50": 0.375, "ratio_p90": 0.7447,
        "ours_quantile_for_real": {"p50": 0.0, "p75": 0.0, "p90": 0.0},
        "reachable": {"p50": true, "p75": true, "p90": true}},
  "10": {"real": {...}, "ours": {...}, "ratio_p50": 2.7864, "ratio_p90": 4.7198,
         "ours_quantile_for_real": {"p50": 100.0, "p75": 100.0, "p90": 100.0},
         "reachable": {"p50": false, "p75": false, "p90": false}}
}
```

- 顶层数字键 = turn（字符串），`_meta` 带来源/计数；消费方跳过 `_` 前缀键即可；
- `ratio_p50 / ratio_p90 = real / ours`；任一侧缺失或我们为 0 时为 `null`；
- `ours_quantile_for_real`：把真实 `p50/p75/p90` 的**绝对强度**映射到我们库的经验分位
  （0–100）；`reachable=false` 表示该目标高于我们库最大值（重采样不可达）。

## 3. 已知局限（解读数字前必须知道）

1. **hidden counters 不全**：真实 4,498 行 `hidden_counters_complete=false` 全量成立，
   `library_ready=false` 全量成立。观测是可见信息重建：亡语/复仇/回合计数、饰品/任务内部状态、
   酒馆池消耗等隐藏计数缺失；`enchantments` 也只是可见重建。strength 只统计牌面，不受这些
   字段直接影响，但它们决定「同样牌面的真实战力」，所以本校准只能校准**身材总量**。
2. **4 个旧 build**：真实数据只有 build `250339 / 251952 / 253216 / 254477`（按目标 stage 行数
   分别为 1,630 / 424 / 1,106 / 1,338），而我们的引擎基线是 **37.0.0.255790**。跨 build 的卡牌
   数值/机制/新随从会改变同等经济下的身材曲线；尤其后期 scaling 卡差异会放大 turn 13+ 的差距。
   另外其中 **144 行是 duo 模式**（`game_type=37`，占 3.2%），与单人 BG 的强度曲线不完全同分布。
3. **无 pool 差量**：真实观测只有某一时刻的牌面，没有「哪些随从已被买走/刷新掉」的共享池计数；
   自采帧虽有 `held_pool_parts`，但注入走 `pool_delta_unknown`（不扣池）。两边都无法还原真实
   池状态。因此本校准只对齐**入口强度**，不代表注入后的完整局面等价。
4. **可见牌面重建**：真实行是 Firestone 可见信息重建，存在解析噪声——`max` 可达 370,510
   （turn 15）、`board > 7` 12 行、`attack/health=null` 54 行。我们用 p50/p75/p90 作主结论、
   p99/max 只作上界参考；p99 以上可能被少量异常缩放随从拉高。
5. **自采侧采集偏差**：8 局、`min_board=2`（低 turn 只保留 ≥2 随从的座位）、同一 checkpoint、
   温度 0.7、8 座全部由模型驱动（没有人类/异构对手）。这会造成：
   - turn 1 只有 4 帧（p50=8），turn 2 有 40 帧，低 turn 分布**不可信**；
   - turn 11+ 每 turn 只剩 47→2 帧（对局结束），p99/max 抖动大，不能当稳定分位；
   - 库的强度上限受自身策略限制（自指风险）。
6. **无 MMR 分层**：「10k+ MMR」是上游来源描述，payload 里**没有 MMR 字段**，无法过滤/分层。
7. **turn 对齐**：真实 `turn_source=owner_player_tag20`，按目标 stage 统计时每个 turn 有约 2 行
   `combat_index` 与 `turn` 差 1；自采 `turn` 是引擎 `game.turn`。绝大多数行对齐，但存在少量
   边界错位。
8. **只统计到 18 turn**：双方 turn > 18 的样本为零；真实 turn 17 只有 2 行，我们 turn 18 只有
   2 帧，任何「终局强度」结论都不成立。

## 4. 分 turn 对照

数据来自 `--report` / JSON（`count` 为有效样本数；`—` 表示无样本）。

| turn | 真实 n | 真实 p50 | p75 | p90 | p99 | max | 我们 n | 我们 p50 | p75 | p90 | p99 | max | ratio p50 | ratio p90 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 362 | 3.0 | 6.0 | 7.0 | 10.4 | 13 | 4 | 8.0 | 8.5 | 9.4 | 9.9 | 10 | 0.38 | 0.74 |
| 2 | 364 | 5.0 | 7.0 | 11.0 | 23.1 | 25 | 40 | 12.5 | 15.2 | 18.1 | 20.6 | 21 | 0.40 | 0.61 |
| 3 | 362 | 15.0 | 21.0 | 27.0 | 39.0 | 42 | 62 | 18.5 | 24.0 | 28.8 | 39.0 | 39 | 0.81 | 0.94 |
| 4 | 356 | 26.0 | 36.0 | 46.0 | 58.5 | 63 | 64 | 34.0 | 40.0 | 46.4 | 57.2 | 66 | 0.76 | 0.99 |
| 5 | 364 | 48.0 | 60.0 | 73.0 | 122.9 | 144 | 64 | 53.0 | 60.8 | 71.4 | 94.2 | 103 | 0.91 | 1.02 |
| 6 | 364 | 77.0 | 99.0 | 129.0 | 250.1 | 323 | 64 | 85.0 | 99.8 | 121.1 | 142.5 | 145 | 0.91 | 1.07 |
| 7 | 362 | 131.0 | 171.0 | 238.0 | 427.5 | 705 | 64 | 124.5 | 150.5 | 180.6 | 234.2 | 243 | 1.05 | 1.32 |
| 8 | 362 | 266.0 | 361.0 | 465.0 | 997.3 | 1173 | 64 | 195.0 | 225.5 | 259.7 | 375.2 | 396 | 1.36 | 1.79 |
| 9 | 364 | 546.5 | 837.0 | 1268.0 | 2609.9 | 2700 | 63 | 305.0 | 388.0 | 463.4 | 516.3 | 564 | 1.79 | 2.74 |
| 10 | 344 | 1128.5 | 1778.0 | 2948.0 | 5601.1 | 8603 | 55 | 405.0 | 533.5 | 624.6 | 855.3 | 898 | 2.79 | 4.72 |
| 11 | 310 | 2203.0 | 4125.0 | 6644.0 | 27123.1 | 29648 | 47 | 540.0 | 644.0 | 1065.6 | 1472.5 | 1582 | 4.08 | 6.24 |
| 12 | 230 | 4458.0 | 8460.5 | 13288.0 | 43133.0 | 82221 | 38 | 669.0 | 818.8 | 2115.0 | 2544.4 | 2698 | 6.66 | 6.28 |
| 13 | 160 | 9666.5 | 18515.8 | 31366.4 | 127729.7 | 143137 | 29 | 751.0 | 1043.0 | 3901.6 | 4525.7 | 4694 | 12.87 | 8.04 |
| 14 | 84 | 21136.0 | 37736.0 | 74435.0 | 249407.0 | 249407 | 23 | 993.0 | 1528.5 | 7596.2 | 8314.3 | 8494 | 21.29 | 9.80 |
| 15 | 40 | 26516.0 | 60310.0 | 170585.2 | 370510.0 | 370510 | 13 | 1045.0 | 1285.0 | 12063.4 | 14760.6 | 14800 | 25.37 | 14.14 |
| 16 | 14 | 19296.0 | 34865.0 | 50130.2 | 55016.0 | 55016 | 9 | 1152.0 | 4231.0 | 28873.8 | 29110.7 | 29137 | 16.75 | 1.74 |
| 17 | 2 | 22653.0 | 22653.0 | 22653.0 | 22653.0 | 22653 | 6 | 1245.0 | 1461.2 | 4674.0 | 7500.9 | 7815 | 18.20 | 4.85 |
| 18 | 0 | — | — | — | — | — | 2 | 1261.0 | 1325.0 | 1363.4 | 1386.4 | 1389 | — | — |

**读法**：

- turn 3–6：我们 p50 反而略高（18.5 vs 15、34 vs 26、53 vs 48、85 vs 77），p90 与真实几乎重合
  （28.8 vs 27、46.4 vs 46、71.4 vs 73、121.1 vs 129）——中前期**不弱**；
- turn 7 起真实 p90 开始拉开（238 vs 180.6），turn 8 后 p50 也拉开；
- turn 10–13 真实 p50 以约 2×/turn 增长，我们约 1.3×/turn，差距逐 turn 放大；
- turn 14–15 真实 p50 的绝对值主要来自高 scaling 构筑（p99 249k/370k），我们库最高只有
  8.5k/14.8k，量级差距明确；
- turn 16 的 p90 比值 1.74 是**假象**：我们只有 9 帧，其中 1 帧 29,137 把 p90 拉高；真实只有
  14 行。turn 16–18 一律不作结论。

## 5. 镜像库采样建议

### 5.1 目标：每 turn 的「真实分位 → 我们库分位」

镜像库的目标强度曲线应取**真实 p50（训练）/ p75（更难课程或 exam）**。下表给出真实目标强度
落在我们库的哪个经验分位（数值越小，说明我们越容易在低分位就达到该目标；`不可达` 表示目标
高于我们库最大值）：

| turn | 真实 p50 | 我们分位 @真实p50 | 真实 p75 | 我们分位 @真实p75 | 真实 p90 | 我们分位 @真实p90 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 3.0 | 0.0 | 6.0 | 0.0 | 7.0 | 0.0 |
| 2 | 5.0 | 0.9 | 7.0 | 2.6 | 11.0 | 35.9 |
| 3 | 15.0 | 31.1 | 21.0 | 62.3 | 27.0 | 88.5 |
| 4 | 26.0 | 15.9 | 36.0 | 63.5 | 46.0 | 89.7 |
| 5 | 48.0 | 34.9 | 60.0 | 74.6 | 73.0 | 91.3 |
| 6 | 77.0 | 40.5 | 99.0 | 74.6 | 129.0 | 94.1 |
| 7 | 131.0 | 57.1 | 171.0 | 87.8 | 238.0 | 99.4 |
| 8 | 266.0 | 90.7 | 361.0 | 98.3 | 465.0 | 不可达 |
| 9 | 546.5 | 99.6 | 837.0 | 不可达 | 1268.0 | 不可达 |
| 10 | 1128.5 | 不可达 | 1778.0 | 不可达 | 2948.0 | 不可达 |
| 11 | 2203.0 | 不可达 | 4125.0 | 不可达 | 6644.0 | 不可达 |
| 12 | 4458.0 | 不可达 | 8460.5 | 不可达 | 13288.0 | 不可达 |
| 13 | 9666.5 | 不可达 | 18515.8 | 不可达 | 31366.4 | 不可达 |
| 14 | 21136.0 | 不可达 | 37736.0 | 不可达 | 74435.0 | 不可达 |
| 15 | 26516.0 | 不可达 | 60310.0 | 不可达 | 170585.2 | 不可达 |
| 16 | 19296.0 | 82.7 | 34865.0 | 不可达 | 50130.2 | 不可达 |
| 17 | 22653.0 | 不可达 | 22653.0 | 不可达 | 22653.0 | 不可达 |

**采信边界**：

- **turn 3–7**：真实 p50 对应我们 q16–q57，真实 p75 对应 q62–q88 → 用「我们库同 turn 的
  q16–q60」即可对齐真实中位；这是当前唯一可以直接校准的区间；
- **turn 8–9**：要达真实 p50 必须取我们 q91–q100（接近本 turn 最强帧），只能算「勉强可达」；
- **turn 10+**：真实 p50 已超过我们库最大值，**无论取哪个分位都达不到**。此时建议：
  - 仍按真实 p50 作为目标强度，注入时取「本 turn 最强帧」（或 q99）作为**下界近似**，
    并在训练 meta 中显式标记 `strength_under_calibrated=true`；
  - 同时把差距作为**数据补强优先级**：提升 checkpoint/搜索预算、增加局数与 seed 多样性，
    或引入真实人类完整 `player_json` 库。**不要**用「把 atk/hp 按比例放大」来伪造——那会改变
    随从相对构成、关键词/亡语结算，且当前注入 API 只接受真实 Player JSON，不做数值缩放；
- **turn 1–2**：真实 p50 低于我们库最小值（q0），说明采集过滤掉了低强度帧。若要做低 turn 课程，
  需用 `min_board=0/1` 重新采集；否则这 2 个 turn 的「偏强」只是采样偏差。

### 5.2 实现方式：`MirrorSnapshotPool(sample=...)` 的 `p50/p75/p90/max` 模式

当前 `hsbg/az/train/mirror_snapshots.py` 已支持按桶内 strength 分位采样（`SAMPLE_MODES`）：

| `sample=` | 行为 |
|---|---|
| `p50` / `p75` / `p90`（或任意 `pNN`，如 `p37`） | 对同一个 `(turn, seat)` 的候选帧按 strength 升序取最近秩分位；同强度用 `rng` 随机 |
| `max`（旧名 `strong`） | 同键取最大 |
| `weak` | 同键取最小 |
| `random` / 未知 | 同键均匀随机 |

训练入口 [`scripts/train_entity_sync.py`](../scripts/train_entity_sync.py) 的
`--mirror-sample {p50,p75,p90,max,strong,weak,random}` 只暴露固定列表；类本身还接受任意
`pNN`，要按 turn 精确切换时直接改 `pool.sample_mode`。

**关键粒度**：分位是在**每个 `(turn, seat)` 桶**（中位 6 帧，`frames_per_key_p50=6`）内选，
不是在整个 turn 的约 64 帧里选。§5.1 的映射是**全 turn 全局分位**；每座样本量接近时二者近似相等，
但不严格相同。需要精确命中某个绝对强度时，用本节的「直接选帧」法。

**按 turn 的目标 `sample=`**（训练对齐真实 p50，取 §5.1 `@p50` 分位四舍五入；exam 对齐 p75）：

| turn | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10–18 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 训练（→ 真实 p50） | p31 | p16 | p35 | p40 | p57 | p91 | p99 | `max` |
| exam / 难课程（→ 真实 p75） | p62 | p64 | p75 | p75 | p88 | p98 | `max` | `max` |

turn 1–2 真实 p50 低于我们库最小值，保持 `weak`/`p0` 即可，但更该按 `min_board=0/1` 重采。

用法（单进程 actor；在每次 `inject_turn` 前切模式）：

```python
TRAIN_Q = {3: 31, 4: 16, 5: 35, 6: 40, 7: 57, 8: 91, 9: 99}   # 10+ 用 max

def sample_mode_for(turn: int) -> str:
    q = TRAIN_Q.get(int(turn), 100)
    return "max" if q >= 100 else f"p{q}"

pool.sample_mode = sample_mode_for(turn)      # 只影响随后 pool.get()
inject_turn(game, pool, turn, seats=seats, p=1.0, rng=rng, stats=stats)
```

- lock-step / `process_pool` 一个 worker 内多局并行时，不要在局间随意切 `sample_mode`（会串档）；
  在「同一批所有局都处于同一 turn 区间」的批次边界切换，或用固定模式做阶段课程（见下）；
- `--mirror-sample` 是**整轮固定**模式，只能做阶段课程：例如早段 `p50`、后段 `max`。要逐 turn
  精确对齐，就在采集循环里切 `pool.sample_mode`（上面的写法）。

**若需要精确的绝对强度**（而非桶内分位）：按全 turn 分位列直接选帧：

```python
frames = [f for fs in pool.index.values() for f in fs]
by_turn = {}
for f in frames:
    by_turn.setdefault(f.turn, []).append(f)
for fs in by_turn.values():
    fs.sort(key=lambda f: f.strength)

def frame_at(turn: int, q: float):           # q ∈ [0, 1]
    fs = by_turn.get(turn) or []
    if not fs:
        return None
    return fs[min(len(fs) - 1, max(0, round(q * (len(fs) - 1))))]

chosen = frame_at(10, 1.0)   # turn 10 最强帧 = 真实 p50 不可达时的下界近似
# 再 game.apply_turn_snapshots([[seat, chosen.player_json]], advance=...) 显式注入
```

**落库建议**（把校准变成对手强度曲线）：

| 用途 | 目标 | 采样档位 |
|---|---|---|
| 训练（对齐真实中位） | 真实 p50 | turn 3–9 用上表训练行；turn 10+ 用 `max`，并在训练 meta 标记 `strength_under_calibrated` |
| 梯度/更难课程（twin exam） | 真实 p75–p90 | turn 3–8 用上表 exam 行；turn 9+ 用 `max` |
| exam 库隔离 | — | exam 用不同来源（不同 checkpoint/seed），不参与训练（论文的 twin 库做法） |

> 说明：当前自采库只有 8 局 / 711 帧，单 turn 分位分辨率很粗（turn ≥ 11 每 turn 仅 47→2 帧），
> 而 `pNN` 又在每座约 6 帧内选，粒度更粗。上表应理解为「该 turn 的目标档位」；扩充局数后重新跑
> `scripts/calibrate_strength.py` 更新 `strength_calibration.json`，不要把分位长期写死。

## 6. 复现与验收

```bash
# 对照表（同时写 data/real_library/strength_calibration.json）
PYTHONPATH=rust/python:. python scripts/calibrate_strength.py --report

# 单测（合成 3 行 jsonl + 2 个假快照帧，不依赖大文件/引擎/GPU）
PYTHONPATH=rust/python:. pytest tests/test_calibrate_strength.py -q
```

验收点：

- `--report` 打印 `turn / 真实 p50/p75/p90/p99/max / 我们 p50/p75/p90/p99/max / ratio p50/p90 /
  建议分位`，并输出 §4 的完整表；
- JSON 顶层每个 turn 都有 `real`、`ours`、`ratio_p50`、`ratio_p90`（另有 `ours_quantile_for_real`
  与 `reachable` 供采样侧直接使用）；
- 单测覆盖：非法 stage 丢弃、strength 定义、分位插值、按 turn 分桶、2 帧 pool 读取、
  ratio/分位映射、`main --report` 端到端。
