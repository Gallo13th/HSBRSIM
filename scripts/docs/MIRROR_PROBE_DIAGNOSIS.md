# 镜像快照探针 arm3 未终局诊断（2026-10-29）

- **状态**：已定位、已修（只改探针，未改引擎）、已重跑。
- **范围**：`scripts/probe_mirror_strength.py`（镜像快照难度探针）在 arm2/arm3 出现的
  「局未结束就退出」问题；引擎 `hsbg_engine` 未改动。
- **产物**：
  - 修复后：`runs/library/probe_mirror_fixed.json`（arm 0/2/3 各 40 局，seed 92001 起）
  - 修复前对照：`runs/library/probe_mirror_before_advance.json`（同一脚本 `--no-advance`）
  - 本文件：假设 → 证据 → 结论 → 修复 → 重跑数字。

## 0. 结论速览

| 项 | 结论 |
|---|---|
| arm3 只有 18/40 终局的根因 | **探针注入时没有推进回合**（`inject_turn(..., advance=None)`）。注入把镜像座位置 `ended_turn=true`；当场上只剩被注入的镜像座位（learner 与 bot 都已淘汰）时，8 个座位全部 `ended_turn=true` 却没有任何人调用 `fight_when_all_ended`，探针下一轮发现「无人 `needs_action`、局未结束」就 `break`，`rank=None`。 |
| 是否引擎 bug | **不是**。引擎只在显式 `advance=True` 时统一推进（`snapshot.rs:322-325`），而 `end_turn`/`end_turn_silent` 路径都会推进（`flow.rs:802`、`flow.rs:836`）。注入 API 把「是否推进」留给调用方是设计选择，探针用错了默认值。 |
| 修法 | `inject_turn(..., advance=True)`；若推进使 `game.turn` 变化，`continue` 回到循环顶部，先给新回合注入再让任何座位行动；另加防御路径 `apply_turn_snapshots([], True)`（实际 0 次触发）。 |
| 修后终局率 | **arm0 40/40、arm2 40/40、arm3 40/40（均 100%）**，超过 ≥95% 验收线。 |
| 附带结论 | `pending_choice` 拒绝（arm3 346 次）是**预期回退**（回合 0 选英雄、回合 6/9 饰品、其它回合起点待选），不是卡死原因；`not_alive` 拒绝是被注入座位已淘汰。二者都只让该座位本回合回退 bot。 |
| 旧 mean rank 3.5556 的解释 | 旧数字只统计了 18 个终局局，**排除了 22 个 learner 早已死亡（名次已定）的局**，是选择偏差；修后按 40 局统计 arm3 mean rank 3.95。 |

## 1. 环境与复现命令

- 远端：`bicourse-glt:/home/data/users/gaoletian/projects/HSBRSIM`
- Python：`~/.conda/envs/hiermolgen/bin/python`（3.10，torch 2.6.0+cu124）；`cuda:3` 单卡
- 引擎：`hsbg_engine 1.0.0` / game `37.0.0.255790`（`probe_mirror_fixed.json.engine`）
- learner：`runs/champion_c0_2279.pt`（md5 `78d92c5d46712631e380e8c0bd40f692`）
- 快照池：`runs/library/snaps_champ`（8 个文件，711 帧，126 个 `(turn,seat)` 键，turn 1..18）
- 修复后命令（验收跑）：

```bash
cd /home/data/users/gaoletian/projects/HSBRSIM
PYTHONPATH=rust/python:. ~/.conda/envs/hiermolgen/bin/python scripts/probe_mirror_strength.py \
  --checkpoint runs/champion_c0_2279.pt --device cuda:3 \
  --snap-dir runs/library/snaps_champ --games 40 --arms 0,2,3 \
  --seed 92001 --out runs/library/probe_mirror_fixed.json
```

- 修复前对照（同一个探针，只关掉推进）：

```bash
PYTHONPATH=rust/python:. ~/.conda/envs/hiermolgen/bin/python scripts/probe_mirror_strength.py \
  ... --games 40 --arms 0,2,3 --seed 92001 --no-advance \
  --out runs/library/probe_mirror_before_advance.json
```

**对照有效性**：`--no-advance` 输出与仓库上一轮 `runs/library/probe_mirror.json`（旧版脚本）
**逐局名次完全一致**（arm0 40、arm2 35、arm3 18 局的 `placements` 与 `mean_rank` 全部相等），
说明本次重写没有改变探针语义，二者差异只来自 `advance` 开关。

## 2. 假设逐条验证

所有数字来自：

- `BEFORE = runs/library/probe_mirror_before_advance.json`
- `AFTER = runs/library/probe_mirror_fixed.json`

### H1 超步数（`--max-steps` 20000 被触发）——**无**

- `BEFORE`/`AFTER` 六个（臂 × 对照）运行的 `diagnostics.max_steps_hit` 全为 **0**。
- 未终局局并没有跑满步数：arm3 平均 steps 226.6，全部在 turn 12–15 提前退出；arm0（终局）
  最长一局也只有 551 steps（slowest 列表）。离 20000 差两个数量级。
- 结论：不是步数上限。

### H2 引擎卡住（无 `needs_action` 但局未结束）——**有（表现层）**

- `BEFORE` 中 `diagnostics.no_action_stall`：arm0 = 0，arm2 = **5**，arm3 = **22**；
  与未终局局数完全对应（arm2 40−35=5，arm3 40−18=22）。
- 卡死现场由 `_stall_snapshot` 保存（arm3 seed 92003，turn 14）：

```text
phase = Recruit            # state_json()["phase"]，局未结束
needs_action = [False]*8   # 没有任何座位需要行动
health       = [-23, 30, 30, 7, -5, -4, -3, -7]
placements   = [4, 0, 0, 0, 7, 5, 8, 6]
seats        = 0 dead/ended, 1 alive+ended, 2 alive+ended, 3 alive+ended,
               4..7 dead/ended        # 存活座位 = 被注入的 seat 1..3
```

- arm2 的 5 个 stall 同型（seed 92004，turn 14，存活座位恰为 seat 1..2）。
- 注意：这 5/22 局里 learner（seat0）**已经死亡且名次已确定**（上例 placement=4），旧探针
  因为 `game.is_over()==False` 仍然返回 `rank=None`。
- 结论：这是「探针提前退出」，不是引擎死循环——turn 停在 14，`game.turn` 不再变化，
  没有任何等待外部输入的状态。

### H3 战斗异常（`pool_copies=0`、超大身材、多余单位拖慢/卡死 combat）——**无**

- 快照池静态统计（`probe_mirror_fixed.json.pool_stats`）：board 长度 2–7（引擎 board 上限 7，
  **无多余单位**），atk 最大 2137 / hp 最大 2160（**确有超大身材**），4164 个 board 单位中
  `pool_copies=0` 的有 65 个（注入时引擎会统一置 0，属 `pool_delta_unknown` 预期行为）。
- 运行期：arm0/2/3 的 `truncated_combats`（战斗被模拟器 guard 截断次数）全为 **0**，
  `turn_limit_end` 全为 **0**，`pool_unbalanced`、`pool_species_unbalanced` 全为 **0**。
- 单局耗时 Top5（`AFTER.arm3`）：seed 92036 / 92035 / 92007 / 92015 / 92016，分别
  1.97 / 1.68 / 1.59 / 1.53 / 1.38 s（整局，含 ~300 次网络决策）。每回合耗时 mean ≈ **5.3 ms**；
  排除每局第一个计时点（首局首回合含 CUDA 预热 ≈208–224 ms，不计入）后单回合最坏 **9.2 ms**
  （arm2 15.5 ms）。
- 若战斗死循环，单回合耗时会出现数秒级尖峰或 `truncated_combats>0`；两处都没有。
- 结论：镜像场面（含 `pool_copies=0` 与 2000+ 身材）不会让 `simulate_combat` 变慢或死循环。

### H4 探针循环问题（注入 `advance=None` 不推进）——**有（根因）**

- 旧探针在回合起点：

```python
inject_turn(game, pool, last_turn, seats=seats, p=1.0, rng=rng, stats=stats)
# advance 缺省 None -> game.apply_turn_snapshots(snaps, None)
```

- 引擎侧只有 `advance=True` 才在整批注入后调用一次统一推进：

```rust
// rust/crates/hsbg-engine/src/snapshot.rs:322-325
if advance.unwrap_or(false) {
    self.fight_when_all_ended();
    rep.advanced = true;
}
```

- `fight_when_all_ended`（`flow.rs:812-817`）只在「所有存活座位都 `ended_turn`」时开打；
  正常 `end_turn`/`end_turn_silent` 在最后一个座位结束时都会调用它（`flow.rs:802`、`flow.rs:836`）。
  注入把座位置为 `ended_turn=true` 却不推进，于是**只剩镜像座位存活**时，最后一步推进就丢了。
- 数据对应关系（决定性证据）：

| 臂 | 未终局 | `no_action_stall` | 存活座位是否为被注入座位 |
|---|---|---|---|
| arm0（不注入） | 0 | 0 | — |
| arm2 | 5 | 5 | 是（seat 1..2） |
| arm3 | 22 | 22 | 是（seat 1..3） |

- 开 `advance=True` 后：arm3 有 **28 次**注入直接触发推进（`inject_advances`，arm2 为 3），
  终局 40/40；`forced_advance`（防御路径）= 0，说明修的就是这一条路径。
- 结论：**探针 bug**，不是引擎 bug。

### H5 `pending` 拒绝是否导致无人行动/卡死——**有拒绝，但不是卡死原因**

- `BEFORE`/`AFTER` 的拒绝原因分类（`mirror.rejected_reasons`）：

| 臂 / 运行 | attempt | applied | rejected | rejected 分类 | missing |
|---|---|---|---|---|---|
| arm2 BEFORE | 1208 | 775 | 260 | not_alive 39, pending_choice 221 | 173 |
| arm2 AFTER | 1214 | 780 | 260 | not_alive 39, pending_choice 221 | 174 |
| arm3 BEFORE | 1767 | 1111 | 438 | not_alive 94, pending_choice 344 | 218 |
| arm3 AFTER | 1857 | 1175 | 458 | not_alive 112, pending_choice 346 | 224 |

- 恒等式 `attempt = applied + rejected + missing` 在四组里都成立；`errors=0`，没有其它拒绝类。
- `pending_choice` 的来源（已逐座核实）：回合 0 是 `HeroSelect` 待选（每局固定 3 次）；
  回合 6/9 是饰品三选一（`config.rs:263-264` 的 `lesser_trinket_turn=6` /
  `greater_trinket_turn=9`，`flow.rs:487-500` 在 `start_turn_player` 里产生 pending）；
  其余是回合起点的零散待选。探针在 `start_turn` 返回后注入，此时 pending 已存在，
  引擎 fail-closed 拒绝（`snapshot.rs:357-359`），该座位本回合按 bot 行动（fallback）。
- 关键反证：修复后 `pending_choice` 计数与修复前同量级（346 vs 344），但终局率从 45% 变成
  **100%**；arm2 的 pending 计数完全不变（221）而终局率 87.5% → 100%。所以 pending 拒绝
  只会造成「该回合少注入一个座位」，不会让整局无人行动。
- `not_alive`：`mirror_seats(arm)` 固定返回 seat 1..N，已淘汰座位每回合仍会被尝试注入；
  引擎拒绝并计数。属正常噪声，不影响推进。
- `missing`：turn 0（池里没有 turn 0 帧）与 turn>18（池覆盖 1..18）的缺帧，按设计跳过。

## 3. 最小复现（修复前）

不依赖 GPU 也可复现（seat0 用 bot 也能触发；下面命令保留 learner 以便与报告数字一致）：

```bash
cd /home/data/users/gaoletian/projects/HSBRSIM
PYTHONPATH=rust/python:. ~/.conda/envs/hiermolgen/bin/python scripts/probe_mirror_strength.py \
  --checkpoint runs/champion_c0_2279.pt --device cuda:3 \
  --snap-dir runs/library/snaps_champ --games 40 --arms 3 --seed 92001 --no-advance \
  --out /tmp/probe_repro.json
# 预期：arm3 约 18–19/40 终局；任取一个未终局局，其 stall 快照为
# phase=Recruit、needs_action 全 false、全部 ended_turn=true、存活座位 = 被注入座位。
```

相关代码位置：

- 探针修复前：回合起点 `inject_turn(...)` 未传 `advance`（本次修复后为
  `scripts/probe_mirror_strength.py:105-106` 的 `advance=inject_advance`）。
- 引擎推进门槛：`rust/crates/hsbg-engine/src/snapshot.rs:302-327`（`advance` 默认不推进）。
- 统一推进：`rust/crates/hsbg-engine/src/flow.rs:812-817`（`fight_when_all_ended`）。

**判定：不是引擎 bug，未改引擎。** 引擎的三条结束路径（`end_turn` / `end_turn_silent` /
`apply_turn_snapshots(advance=true)`）都会走 `fight_when_all_ended`；注入 API 把推进显式化是
为了支持「采集端 clone 阻止推进」等用法（见 `docs/MIRROR_SNAPSHOT_DESIGN.md` §2.1）。

## 4. 修复内容（仅 `scripts/probe_mirror_strength.py`）

1. **注入带推进**（`:105-106`）：`inject_turn(..., advance=True)`（默认；`--no-advance` 仅供诊断对照）。
2. **推进后先重注入**（`:112-117`）：若注入导致 `game.turn` 变化（所有存活座位都被注入 → 开打 →
   下一回合），`continue` 回循环顶部，保证新回合在任何座位行动前完成注入；否则新回合会变成
   「未注入的 bot 回合」，污染镜像强度。
3. **防御性推进**（`:131-142`）：若出现「无人 `needs_action` 且局未结束」，调用一次
   `game.apply_turn_snapshots([], True)` 只走 `fight_when_all_ended`（不注入任何座位）。
   本次重跑 `forced_advance=0`，说明第 1 条已覆盖全部情况；保留它是为了以后引擎/池变化时不静默退出。
4. **诊断与证据固化**：新增逐局/逐臂计数 `inject_advances`、`forced_advance`、`no_action_stall`、
   `max_steps_hit`、`truncated_combats`、`turn_limit_end`；未终局时保存
   `_stall_snapshot`（含 `phase`、每座 `needs_action/ended_turn/health/pending/board`）；
   拒绝原因分类 `rejected_reasons`（`_reject_kind`，`:47-51`）；每回合耗时与单局耗时 Top5；
   输出 `source_hashes` + `engine` 便于复现审计。
5. **输出结构**：每臂新增 `games_played` / `terminal` / `terminal_rate` / `mean_turn` /
   `rejected_reasons` / `diagnostics`，保留旧字段 `games` / `mean_rank` / `top4` / `win` /
   `mean_steps` / `mirror`，不破坏下游读取。

引擎与 `hsbg/az/train/**` 未由本任务改动。

## 5. 修后重跑数字（arm 0/2/3，各 40 局，seed 92001–92040，cuda:3）

| 臂 | 终局率 | mean rank | top4 | win | mean steps | mean turn | attempt | applied | rejected（分类） | missing |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 修复前 | 40/40 (100%) | 2.00 | 0.975 | 0.375 | 328.9 | 15.9 | 0 | 0 | 0 | 0 |
| 0 修复后 | 40/40 (100%) | 2.00 | 0.975 | 0.375 | 328.9 | 15.9 | 0 | 0 | 0 | 0 |
| 2 修复前 | **35/40 (87.5%)** | 3.8286¹ | 0.6286¹ | 0.0286¹ | 239.0 | 14.1 | 1208 | 775 | 260（not_alive 39 / pending 221） | 173 |
| 2 修复后 | **40/40 (100%)** | 4.00 | 0.575 | 0.025 | 239.1 | 14.2 | 1214 | 780 | 260（39 / 221） | 174 |
| 3 修复前 | **18/40 (45.0%)** | 3.5556¹ | 0.7222¹ | 0.1111¹ | 226.6 | 13.7 | 1767 | 1111 | 438（not_alive 94 / pending 344） | 218 |
| 3 修复后 | **40/40 (100%)** | 3.95 | 0.675 | 0.05 | 226.8 | 14.5 | 1857 | 1175 | 458（112 / 346） | 224 |

¹ 修复前只对「终局局」求均值（35/40、18/40），排除了 learner 已死、名次已定的局，是**有偏**
统计，不能与修复后的 40 局均值直接比较。修复前 delta vs arm0：arm2 +1.8286、arm3 +1.5556；
修复后：arm2 **+2.00**、arm3 **+1.95**。

补充（`probe_mirror_fixed.json`）：

- `advance=true`，`inject_advances`：arm2 = 3，arm3 = 28；`forced_advance = 0`；
  `no_action_stall = 0`；`max_steps_hit = 0`；`truncated_combats = 0`；`turn_limit_end = 0`。
- 计时：arm0/2/3 mean game 1.31 / 0.93 / 0.92 s；mean 5.4 / 5.35 / 5.31 ms per turn；
  排除每局第一个计时点后单回合最坏 15.4 / 15.5 / 9.2 ms（首局首回合含 CUDA 预热 ≈208 ms，不计入）。
- 两次独立重跑（同一 `--arms 0,2,3 --seed 92001`）逐局 `placements` 与全部 mirror 计数完全一致；
  产物 `source_hashes`：probe `d5357d9b`、mirror_snapshots `614f7034`、model `3c8ca85f`、
  entity_model `e13824e6`；固定产物记录时 ppo 为 `4b828755`（另一份重跑在 ppo `a50973ca`
  下得到逐局一致结果；ppo 仍在并行开发，探针结论不依赖其内部改动）。

## 6. 复现注意

- **必须固定 `--arms` 列表与顺序**：`PPOSelfPlayPolicy.reset()` 只清本局记录，不重置采样 RNG
  （`ppo.py:1275-1283`，需要 `reseed()` 才重建）。因此同一 `--arms 0,2,3` 顺序可逐局复现；
  单独跑 `--arms 3` 会从不同的 RNG 流开始（实测同一 `--no-advance` 下 19/40，而
  `--arms 0,2,3` 为 18/40，差 1 局）。若希望臂间完全独立，可在每局开始调用
  `learner.reseed(seed+g)`，但会改变与历史数字的可比性，本次未改。
- 勿用旧版脚本/旧 JSON 与新数字混比：旧 JSON 的 `mean_rank` 只覆盖终局子集。
- 当前工作区有其它并行开发改动（`hsbg/az/train/**`、`ppo.py` 等）；本报告数字对应的
  `source_hashes` 已写进输出 JSON，重跑前请先核对。

## 7. 给 Lead 的结论

1. 未终局根因是探针注入未推进回合，**引擎无需修改**；无最小引擎复现需要上报。
2. 修复只在探针：`advance=True` + 推进后重注入 + 防御推进 + 诊断字段。
3. 重跑 arm 0/2/3 各 40 局全部终局（100% ≥ 95% 验收线），产物
   `runs/library/probe_mirror_fixed.json`。
4. arm 难度结论按修正后的全 40 局统计：arm0 mean rank 2.00 → arm2 4.00 → arm3 3.95
   （top4：97.5% → 57.5% → 67.5%；win：37.5% → 2.5% → 5.0%）。
   arm3 与 arm2 接近、没有随镜像座位数单调变难，可作为下一步难度曲线/课程采样的输入。
