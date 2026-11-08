# 回合末场面快照镜像对手设计

- **状态**：设计稿；仅基于当前仓库只读核查，未改 Rust/Python、未训练、未占用 GPU。
- **范围**：HSBRSIM AutoTavern `hsbg_engine`，目标是以轨迹中的回合末场面增强对手，绝不重放对手动作。

## 1. 背景与目标

当前训练为 Rust `hsbg_engine` + PPO（sims=0、KL anchor、bf16、pipeline、lock-step 采集）；learner 在 seat 0，其余 7 席由引擎 bot 驱动。已知 C0 512 局 mean rank 2.279（top4 93.6%、吃鸡 31.4%），瓶颈是对手过弱。整 `Player` 移植会破坏 pool/eid/生命周期不变量；逐动作回放实测也不强（配对差 +0.03，CI [-0.93,+1.03]），所以本方案不重放动作。

**定义**：轨迹 seat `s` 在 turn `T` 的快照，是该座位所有动作已完成、EOT effects 已运行、pending 已解决、`ended_turn=true`，且 combat 尚未开始时的可观测 `Player` 状态。将其复制到目标对手座位，视作外生战团；默认达到该场面时牌库减少量等于其它玩家可选牌数。原始 seed 的逐位语义不再保留，但在固定轨迹、映射、分配 RNG 和动作序列下局面仍可复现。

代码依据：`flow.rs:751-803` 的 `end_turn` 先运行 end-of-turn hooks/deaths，随机解决 pending，随后才设置 `ended_turn`、`last_board` 并进入 `fight_when_all_ended`；`flow.rs:820-834` 的 `end_turn_silent` 对已 ended 直接 return，且不跑 EOT。因此只能采集 `end_turn` 完成之后、`combat_round` 之前的帧，不能把 silent 或 combat 后帧冒充 EOT 快照。

## 2. 语义、窗口和映射

### 2.1 注入窗口

建议在新回合的 `Game::start_turn` 中，`decide_pairs()` 后、每个 `start_turn_player(p)` 之前，完成本轮快照批量注入；严格的 pool 差量必须在任何逐座刷新/起始效果前完成。注入的镜像座位应被标记为本回合已完成（`ended_turn=true`），并禁止对其调用正常的 `start_turn_player`；否则该函数会将 `ended_turn=false`、刷新商店、过期临时效果（`flow.rs:379-483`），破坏快照。learner seat 仍走正常 start-turn。注入完成后，可选 `advance=true` 只让整局推进一次，不能每个快照分别推进。

推荐流程：

1. 进入 recruit、确认 phase/turn 和目标座位均有效；收集这一批所有快照。
2. 在临时副本/事务工作区验证帧、seat 映射、字段、EID、pending 和 pool 差量；任一失败整体拒绝。
3. 将目标旧 board/hand/queue/shop 的 minion pool parts 归还，再应用批量池变化和白名单字段；镜像座位 `ended_turn=true`。
4. 重建 `last_board`（如快照有该语义），保持对局级 pair/death bookkeeping 不被外部帧覆盖；必要时调用一次统一推进逻辑。
5. 任何 alive/health/placement 不一致、座位重复、帧缺失或映射冲突都按策略拒绝，不静默猜测。

### 2.2 seat 映射与缺帧

manifest 固化 `source_seat -> target_seat`，默认 `{0->0, 1->1, ...}` 仅当 source/target 相同语义；训练场建议 `{trajectory_s -> opponent_target}`，且 target 不得是 learner、不得重复。映射必须记录 source game/turn、target seat、是否镜像 board-only、pool 模式和 fallback 决策。

缺帧策略按 manifest 固化：`fail_closed`（推荐评测）直接拒绝整个 batch；`hold_last` 仅允许同一 source seat 的相邻回合、且显式标注 stale；`bot_fallback` 保留原 bot 状态并打点。不得用其它 seat 的帧替代。初始 hero-select/turn 0 无“回合末”定义：不能注入；只能在首个真实 `ended_turn=true` 的 recruit 回合之后注入；hero、powers、初始资源若由引擎产生，必须保持目标座位原值，除非 manifest 明确允许字段。

## 3. 最小引擎 API（建议，不声称当前已存在）

建议新增 PyO3 边界方法（签名为设计建议）：

```rust
#[pyclass]
pub struct Snapshot { /* version, source_seat, turn, player_payload,
                         pool_mode, pool_delta, frame_sha256 */ }

#[pymethods]
impl Game {
    pub fn apply_turn_snapshots(
        &mut self,
        snaps: &[Snapshot],
        advance: bool,
    ) -> PyResult<()>;
}
```

若 PyO3 不能直接接收 Rust slice，则使用 `&PyAny`/`Vec<Snapshot>` 的等价绑定；具体 crate/module 暴露位置当前未验证，实施时先查现有 Python API，不要复刻一个第二入口。错误必须包含 source/target/turn/reason，且事务失败后 `state_json` 字节完全不变。

实现要点：

- 锁定 `phase == Recruit`、目标存活、`pending.is_empty()`、快照 `ended_turn=true`；不接受 combat 中帧。
- 不做 `Player = snapshot_player`。使用显式 `SnapshotPlayer` 白名单，把 board/hand/shop/hand_queue、资源、英雄/能力等允许字段逐一复制；保留对局级 `id/alive/placement/pairing/last_opponent/recent_opponents/next_opponent/next_is_ghost` 等引擎拥有字段，除非契约另行允许。
- 事务前克隆/序列化工作态；先验证全部快照，最后一次性提交；pool、EID、所有 vectors 均在工作态处理。
- 对全部引用执行 typed EID 映射，不能全局字符串替换：`Minion.eid/killed_by`；`HandCard.hid/link/group/src`；queue marks；`ShopSlot.sid`；`scheduled.target`；`revert_golden`；`owed` 内嵌 Minion；`hats`；`mishmash_seen`。还需递归扫描 `Pending`、`effects`、`quests/rewards` 等类型中实际存在的 EntityId，未识别引用应 fail-closed。
- 新 EID 从引擎 allocator 取得或按 manifest 的确定性分配 RNG 生成；提交前验证全局唯一（`invariants.rs:10-72` 已有 EID 检查思路）。
- `advance=false` 只提交注入；`advance=true` 统一推进一次，禁止隐式调用多次 `start_turn`。

这比 v1 安全：所有生命周期仍由 Game 管理，目标座位只换受控字段；旧座位实体先按 pool parts 归还，引用可追踪重映射，pending/对局 pair/death 状态不会被外部 Player 覆盖。

## 4. 池算法与 fail-closed

### 4.1 计量

对一个场面 `P` 定义每物种池占用：

```text
H(P,c) = Σ_{m∈P.board∪P.hand∪P.shop∪P.hand_queue} parts(m,c)
parts(m,c) = m.pool_copies       (pool_parts 为空且 normal_card(m)=c)
              或 pool_parts 中 c 的数量
```

这是 `state.rs:34-63,209-220` 的语义，不是 golden×3。golden、异种三连、`pool_copies=0` 都必须以实际 `pool_parts` 计量。当前 `invariants.rs:100-143` 提供总量与逐物种守恒核查，`eliminate_dead`（`flow.rs:1114-1170`）明确会把 board、hand、hand_queue、shop 的 minion 逐项 `visit_pool_parts` 后归还。

替换旧场面 `P_old` 为新场面 `P_new` 时：

```text
Pool'(c) = Pool(c) + H(P_old,c) - H(P_new,c)
Δ(c)     = H(P_old,c) - H(P_new,c)
```

先用宽有符号整数（至少 `i64`，计算中不转 u8/u16）聚合整个 batch，检查每个 `Pool(c)+Δ(c)` 在 `[0, max]`；不足、未知 species、负结果、溢出一律拒绝，**不得 saturating**。验证通过才写回。批量先合并差量，避免中间顺序改变结果。

酒馆法术不进上述 minion Pool：`engine.rs:197-215` 的 `spell_copies_left` 动态统计各玩家 Tavern/hand 数量；镜像法术只能按该动态规则或显式非池字段处理，不能把法术算进 `visit_pool_parts`。

### 4.2 外部真实库

若真实库没有 pool 差量，不能推断或伪造 `H`。使用 `pool_delta_unknown`：只替换战斗/可观测场面字段，不扣共享 pool，并把该 batch 标成“外生场面课程”，禁止用于声称严格池守恒的评测。训练和评测必须分开报表；可选后续用可审计的库存/库差数据升级为 `pool_delta_known`。

## 5. 可复现性契约

复现键（manifest hash 的规范化 JSON）至少包含：

```text
engine_version + cards/data/rules version
+ learner_seed
+ trajectory_file_sha256 and frame boundaries
+ source->target seat map
+ allocation_rng algorithm/seed and resulting EID map
+ every injection/fallback/rejection decision
+ learner action sequence (ordered, including choice indices)
+ pool mode and deltas
```

同 manifest、同动作序列，逐步比较 `state_json`、观测和 legal mask；分配 RNG 必须独立命名空间，不能偷偷消费主引擎 RNG。原始 seed 仍能决定未注入部分，但无法恢复真实对手原来的抽牌顺序、刷新顺序、动作因果链、原始 EID 生成、被替换实体的随机历史；因此这是固定轨迹下的确定性外生干预，不是原始游戏 seed 的语义复现。

## 6. 真实数据接入

当前仓库 `data/real_library/obs/observations/` 只读目录实测为 376 个 JSONL 文件（背景记录所称 383 需以实际清单/发布快照复核），样本约含 1.1 万条量级但精确行数未在本次核查统计；示例文件字段有 `build_number:250339`、`card_id` 字符串、`board[].entity_id/attack/health/position/tags`、`known_hand`、`library_ready:false`、`hidden_counters_complete:false`、`stage`、`perspective`。实际接入不得假设背景中的数字与当前目录永远一致。

导入器应：

1. 过滤 `build_number` 与官方 37.0.0.255790/当前 card DB 不相容的帧，记录 build 差异；禁止跨版本直接复用卡下标。
2. 用字符串 `card_id` 查官方卡表，映射到引擎 `CardId`/int；缺卡、golden/normal 无法归一、非 minion 卡误入 board 均拒绝或降级。
3. 质量门：`library_ready && hidden_counters_complete` 才可进入 strict；`board` 的 card_id、position、stats 完整、EID 在帧内唯一、无非法负值；`known_hand` 为空或 `unknown_hand_count>0` 时不得声称完整 Player。
4. 只有 `stage=recruitment_end_at_phase_switch` 或等价 EOT-before-combat 标记才可作为本方案帧；例如当前样本也有 `first_attack_after_start_effects`，必须排除，不能当 EOT。
5. 缺 pool 差量时使用 `pool_delta_unknown`（只换 board/明确可观测战斗字段，不扣池），并保留 `library_ready/hidden_counters_complete`、quality flags、build_number 到 manifest。

真实观察通常只有场面，不能填充隐藏的手牌/效果/pending；按字段白名单构造 board-only 快照，并让目标座位非观测字段保持引擎值。是否把 `known_hand` 视为完整手牌当前未验证，应默认不视为完整。

## 7. 实现清单（逐文件、验收标准）

| 文件/函数 | 改动点 | 验收标准 |
|---|---|---|
| `rust/crates/hsbg-engine/src/flow.rs` `Game::start_turn` | 加批量注入窗口；在逐座 start 前验证/应用，镜像座位跳过普通 start | 7 席批量只推进一次；首店受 pool 差量影响 |
| `rust/crates/hsbg-engine/src/state.rs` | 新增 Snapshot payload/白名单转换所需辅助；不得改变 Player 全替换语义 | serde round-trip；未知字段拒绝或显式忽略并打点 |
| `rust/crates/hsbg-engine/src/engine.rs` | 复用 pool/allocator/state_json 入口；不把 spell 算入 minion pool | 事务失败 state_json 不变；法术计数保持动态 |
| `rust/crates/hsbg-engine/src/invariants.rs` | 暴露/复用逐物种、总 pool、EID 检查 | 每物种守恒、golden/异种/zero-copy 通过 |
| `rust/crates/hsbg-engine/src/lib.rs` 或现有 PyO3 暴露文件（具体位置未验证） | 增加 `apply_turn_snapshots(snaps, advance)` 绑定 | Python 可传 versioned payload，错误可读且原子 |
| `rust/crates/hsbg-engine/tests/`（建议新测试模块，具体文件未定） | 覆盖下节验收测试 | release Rust tests 全绿 |
| `hsbg/az/` 采集/环境入口（现有具体函数未验证） | 增加 `--mirror-snapshots`、manifest、source/target 映射、缺帧策略、pool mode | 默认关闭；lock-step 每帧记录决策和 SHA256 |
| `hsbg/az/` learner/bot 调度 | seat0 正常动作，其余注入 seat 按 ended 语义不重复执行 start | 同动作 manifest 逐步一致，记录 fallback |
| `tests/` Python engine adapter 测试文件（具体文件名未验证） | API、失败回滚、真实 JSONL card 映射/质量门 | 缺卡/build mismatch 不污染状态 |
| `data/real_library/` | 仅读输入与 manifest 清单，不改原始数据 | 文件数、行数、SHA256 可审计；背景 383 与当前实际差异显式报告 |

## 8. 验收测试清单

1. 注入后逐字段回读与规范化 snapshot 一致；`ended_turn=true`、phase/recruit 窗口正确。
2. 每物种 pool 守恒；总 pool 守恒；golden、异种三连、`pool_copies=0`。
3. 任意 pending 非空拒绝，且 `state_json` 字节完全不变。
4. 淘汰路径覆盖 board/hand/hand_queue/shop 归池，与 `eliminate_dead` 行为一致。
5. 7 个目标座位一次 batch 注入，检查无中间 start/refresh、无重复 advance。
6. 全局 EID 唯一，所有 typed 引用（含 killed_by、hid/link/group/src、marks、sid、scheduled、revert、owed、hats、mishmash）指向合法实体或允许的 None。
7. 事务中任一快照失败，所有 state_json、pool、RNG、turn 均不变。
8. 同 manifest + 同 learner 动作序列逐步 state_json/observation/legal mask 一致；不同 manifest hash 必须可区分。
9. 真实库质量门、build_number、字符串卡表映射测试；无 pool delta 只能进入 `pool_delta_unknown`。
10. 难度探针：bot 对真实战团 N 席至少 100 局，固定 seed，报告 mean rank/top4/吃鸡/置信区间，并与纯 bot、历史 checkpoint 对照；不能只看单局。

## 9. 风险、回退与监控

- **性能**：每回合复制多个完整 Player、EID 图重映射、pool 聚合和事务序列化会增加 lock-step latency；使用预计算 parts、批量差量和可选 debug-only 深检查，监控每 batch p50/p95。
- **分布偏移**：真实/轨迹战团可能含 learner 不会产生的 stats、隐藏效果或版本规则，训练可能学到不合法捷径；按来源/质量/strict-vs-unknown 分层采样，独立评测。
- **生态兼容**：真实 `build_number` 与官方 card DB/引擎规则不一致会导致 card 映射、golden、tags 语义错配；默认拒绝不兼容 build，manifest 固化版本，不能跨版本复用 int 卡表。
- **生命周期/EID 风险**：pending、scheduled、owed 等遗漏会在若干回合后才爆炸；typed remap + fuzz/invariants + 失败原子化是门禁。
- **可复现性风险**：外部帧丢失原 seed 因果，必须把 frame hash、分帧、分配 RNG、fallback 决策写入 manifest。
- **回退**：配置 `mirror_snapshots=false`（默认），或按 batch `pool_delta_unknown`/`bot_fallback`；检测 invariant、state hash、illegal action、异常胜率漂移时立即回纯 bot，不删除原轨迹。回退本身也写 manifest，确保结果可复现。

## 10. 未验证项

本次只读核查未发现现成 `apply_turn_snapshots`/PyO3 方法，具体绑定文件、Python 采集器函数名、轨迹格式和现有 EID allocator 暴露点均待实现前定位；文中对应位置用“建议/具体未验证”标明，不能当作当前 API。真实目录精确“约 1.1 万条”和 383 文件的背景数字也未在本次执行全量行数统计，当前目录清单显示 376 文件。

## 11. 实现状态（2026-10-29）

范围：**无池差量 / 外部快照安全版本**（`pool_delta_unknown`）。GPU 训练未跑；只做 CPU
单测与 2 局 CPU 注入冒烟。数据版本未动（`data/real_library/` 未读写）。

### 11.1 已完成

| 层 | 文件 | 内容 |
|---|---|---|
| 引擎 | `rust/crates/hsbg-engine/src/snapshot.rs`（新增，472 行） | `Game::apply_turn_snapshots(&[(seat, player_json)], advance: Option<bool>) -> SnapshotReport`；白名单替换 / typed EID 重映射 / pool parts 归还 / 逐座位事务 |
| 引擎 | `rust/crates/hsbg-engine/src/flow.rs:812` | `fight_when_all_ended` 改 `pub(crate)`，供整批注入后**统一推进一次** |
| 引擎 | `rust/crates/hsbg-engine/src/lib.rs:46-56` | `pub mod snapshot;` + `pub use snapshot::{SNAPSHOT_SCHEMA_VERSION, SnapshotReport}` |
| PyO3 | `rust/crates/hsbg-engine-py/src/lib.rs:200-276,484` | `Game.apply_turn_snapshots(snaps, advance=None)`、只读 `pool_balance()` / `pool_species_violations()` / `invariant_violations()`、`snapshot_schema_version()` |
| PyO3 包 | `rust/python/hsbg_engine/__init__.py:39,132` | 导出 `snapshot_schema_version` |
| 采集 | `scripts/capture_trajectory.py`（重写） | `--emit-snapshots/--snap-dir/--snap-from-turn/--snap-min-board`；新增 `--driver bot`（CPU、无 torch） |
| 采集/注入 | `hsbg/az/train/mirror_snapshots.py`（新增，494 行） | 帧采集（clone + 阻止推进）、`snap_*.json.gz` schema、`MirrorSnapshotPool`、`MirrorStats`、`inject_turn` |
| 训练 | `hsbg/az/train/parallel_collect.py:34,235-236,270-272,313-330,349-355,486-498` | `collect_ppo_lockstep(..., mirror_pool, mirror_seats_count, mirror_p)`；`_maybe_mirror` 在**每个新 turn、任何座位行动前**注入 |
| 训练 | `hsbg/az/train/ppo.py:283-285` | `CollectConfig.mirror_snaps / mirror_seats / mirror_p`（默认空/0/0） |
| 训练 | `hsbg/az/train/process_pool.py:58,267-283,311-313,320-322` | 快照库热加载缓存 + 传给 lockstep；非 lockstep 路径打 warn |
| 训练入口 | `scripts/train_entity_sync.py:109-116,171-179,421-422` | `--mirror-snaps/--mirror-seats/--mirror-p`（默认关；`--mirror-p 0` 零影响） |
| 测试 | `rust/crates/hsbg-engine/tests/mirror_snapshot.rs`（新增，301 行，5 个用例） | 白名单 / 逐物种池守恒（含异种三连 2+1 与 `pool_copies=0`）/ 拒绝路径 `state_json` 不变 / `advance` 只推进一次 / `hand_queue`+`link` 同一实体映射到同一新 EID |
| 测试 | `tests/test_mirror_snapshot.py`（新增，492 行，8 个用例） | 同上 + EID 唯一 + 采集 schema 冒烟 + 训练侧注入驱动 CPU 冒烟 + `--mirror-p 0` 零影响 + lockstep 接线 |
| 文档 | 本文件 §11、`rust/FORK.md` §3.6 | 实现登记 |

### 11.2 Python API 语义（实现后）

```python
rep = game.apply_turn_snapshots([[seat, player_json], ...], advance=None)
# -> {"applied": int,
#     "rejected": [(seat, reason), ...],
#     "pool_balance_ok": bool, "pool_species_ok": bool,
#     "pool_held": int, "pool_initial": int,
#     "advanced": bool, "summary": str}
```

- `player_json` 与 `player_json(seat)` / `state_json()["players"][seat]` 同构；
- **逐座位**校验+提交：被拒绝的座位不改任何状态（pool / `next_eid` / turn / `state_json` 字节），
  也不抛异常（结构性错误如 `snaps` 不是 `[seat, player_json]` 才抛 `ValueError`）；
- 前置条件（否则拒绝，reason 见括号）：`phase==Recruit`（`not_recruit`）、座位存在
  （`seat_out_of_range`）、同批不重复（`duplicate_seat`）、目标存活（`not_alive`）、
  目标未 `ended_turn`（`already_ended`）、目标血量 > 0（`dying`）、目标无 pending
  （`pending_choice`）、帧本身无 pending（`snapshot_pending`）、JSON 可解析（`bad_json`）、
  卡牌/数值/牌面上限合法（`board_too_large`/`hand_too_large`/`shop_too_large`/`bad_tier`/
  `bad_gold`/未知卡/非 minion/负攻击/血上限异常/`destroyed` 尸体）、帧内 EID 非 0 且唯一
  （`zero_entity_id`/`duplicate_eid`）、`hand.hid == minion.eid` 等引擎约定
  （`hand_hid_mismatch`）、所有 typed 引用都在帧内（`unknown_ref:<field>=<eid>`）、
  归还后池计数不溢出（`pool_overflow`）；
- `advance=None/false` 只提交；`true` 在**整批**提交后统一调用一次 `fight_when_all_ended`
  （若此时所有存活座位都 `ended_turn` 则战斗并进入下一回合；返回值 `advanced=true`）；
- 注入后目标座位 `ended_turn=true`（`needs_action` 变 false，本回合不再行动），因此训练循环
  不会再把 bot 动作浪费在镜像座位上。

### 11.3 字段白名单（实现）

| 处理 | 字段 |
|---|---|
| **替换** | `board`、`hand`、`hand_queue`(+`hand_queue_marks`)、`shop`、`tier`、`gold`、`max_gold_bonus`、`upgrade_cost`、`free_refreshes` |
| **派生** | `last_board = board.clone()`（EOT 语义）、`ended_turn = true`、`chronum_balance = 0`（与 `end_turn` 一致） |
| **清空** | `hats`、`mishmash_seen`、`revert_golden`、`discover_targets`（都指向已被整体替换的旧实体，留着就是悬垂引用） |
| **保留当前局** | `id`、`alive`、`placement`、`health`、`armor`、`hero`、`powers`、`stats`、`pending`、`scheduled`、`effects`、`quests`、`rewards`、`trinkets`、`secrets`、`counters`、`levels`、`owed`、`scouted`、`seen_board`、`last_opponent`、`recent_opponents`、`next_opponent`、`next_is_ghost`、`sees_all_boards` 等 |

（`hand` 视为完整手牌：轨迹/自对弈帧由引擎自身产生，`HandCard` 的 `hid/link/group/src`
都能在帧内解析；真实库的 `known_hand` **不**满足这个前提，见 §11.5。）

### 11.4 EID 与池（实现）

- 新实体（board minion、hand `hid`、shop `sid`、hand_queue minion 与其 `QueueMark.hid`
  预留 id）**全部**由 `Game::alloc_eid()` 重新分配，与旧局的 id 空间无关；
- typed 引用重映射：`Minion.eid/killed_by`、`HandCard.hid/link/group/src`、`ShopSlot.sid`、
  `QueueMark.hid/link/src`；集合外引用 fail-closed 拒绝整个座位；
- `pool_delta_unknown`：被替换四区（board/hand/shop/hand_queue）里旧 minion 按
  `visit_pool_parts` 归还共享池（异种三连按 `pool_parts` 逐项，不按 golden×3），
  注入实体一律 `pool_copies=0`、`pool_parts` 清空；提交前用 i64 聚合检查 `pool.counts`
  写回不越界/不溢出（拒绝而不是 saturating）；
- 注入后立即跑 `invariants::pool_balance` 与 `invariants::pool_species_violations`，
  结果写进返回值的 `pool_balance_ok` / `pool_species_ok`；
- 酒馆法术不进 minion 池（`spell_copies_left` 仍按引擎动态统计）。

### 11.5 采集与训练接线

- `scripts/capture_trajectory.py --emit-snapshots 1`：每个座位 `EndTurn` 之后、combat 之前
  记录一帧（实现方式：clone 整局 → 把一个已结束座位的 `ended_turn` 标记回 false 以阻止
  `fight_when_all_ended` → 在 clone 上执行同一个 EndTurn → 读该座位 `player_json`；
  clone 若仍推进了回合则该帧丢弃并计入 `snap_skipped`）；
- 文件：`<snap-dir>/snap_<seed:08d>.json.gz`，`schema="hsbg.mirror_snapshots"`、
  `schema_version=1`（= 引擎 `snapshot_schema_version()`），头里有 engine/data 版本，
  帧字段 `turn/seat/player/held_pool_parts/stage/pool_mode/frame_sha256/source_game_seed`；
  `stage="recruitment_end_before_combat"`、`pool_mode="unknown"`；
  `held_pool_parts` 是设计 §4.1 的 `H(P,c)`（留给将来的 `pool_delta_known`）；
- 训练：`--lockstep 1 --mirror-snaps <dir> --mirror-seats N --mirror-p p`。窗口 = `g.turn`
  变化后、任何座位行动前（outer/inner 两处检查，每 turn 只尝试一次）；按概率给 seat
  `1..N` 抽 `(turn, seat)` 帧注入；缺帧 `missing`、引擎拒绝 `rejected`；被拒绝/缺帧的座位
  本回合仍由 bot 行为兜底（`fallback = missing + rejected + errors`）。meta 记录
  `mirror_attempt/applied/rejected/missing/fallback/errors/pool_unbalanced/
  pool_species_unbalanced/last_rejected` + `mirror_p/mirror_seats/mirror_targets/mirror_frames`；
- 默认关闭：`--mirror-p 0` 时 `inject_turn` 直接返回（不掷骰、不调引擎）；既有
  `--trajectory-pool/--trajectory-p`（整局轨迹回放）行为未改。

### 11.6 验证结果（本机，CPU）

- `cd rust && cargo build --release -p hsbg-engine-py && cp target/release/lib_core.so python/hsbg_engine/_core.abi3.so`：通过；
- `cargo test --release -p hsbg-engine`：**904 passed / 0 failed**（41 个套件，含新增
  `tests/mirror_snapshot.rs` 5 个用例）；
- `python -m pytest tests/test_mirror_snapshot.py -q`：**8 passed**；
- `python -m pytest tests -q`（忽略 `tests/test_az_entity_model.py`，见下）：**149 passed /
  29 failed / 9 skipped**，29 个失败**全部**是本机 `torch` 装的是 CUDA 版但缺
  `libcublasLt`（`ValueError: libcublasLt.so.*[0-9] not found`）导致 `pytest.importorskip("torch")`
  在 import 阶段就抛错，与本改动无关（涉及 `test_az_ppo/test_batch_eval/test_entity18m/
  test_parallel_collect/test_process_pool/test_replay_policy`）；`tests/test_az_entity_model.py`
  收集阶段同样因此报错；
- CPU 冒烟（`test_lockstep_mirror_driver_smoke`）：2 局、seat `[1,2,3]`、`p=0.6`；
  每回合注入前后池检查 29 次全部 `held == initial` 且逐物种无违规；
  `attempt=47 applied=30 rejected=7 missing=10 fallback=17 errors=0`，两局都打到终局，
  终局 `pool_balance` 仍平衡；`rejected>0` 来自饰品回合（t6/t9 全座位 pending，
  按设计 fail-closed 拒绝）；
- 采集冒烟：`capture_trajectory.py --driver bot --games 1 --emit-snapshots 1` 产出
  1 个 `snap_*.json.gz` / 94 帧（turn 1..14 × seat 0..7），帧可被引擎再次接受并打完终局。

### 11.7 TODO / 降级（明确未做）

1. **严格池差量（`pool_delta_known`）**：引擎只在接口层留位；当前一律
   `pool_delta_unknown`（新场面不占池）。采集端已经把 `held_pool_parts` 写进帧，将来可
   按设计 §4.1 计算 `Δ(c)=H(P_old,c)-H(P_new,c)` 并写回 `pool.counts`。
2. **pending 非空一律拒绝**：饰品回合（`lesser_trinket_turn=6`、`greater_trinket_turn=9`）
   开局每个座位都有 `Pending::Trinket`，因此这两个回合**不会**发生注入。要放开需给
   `Pending::Trinket/HeroPowerChoice/Quest/ChooseOne` 这类自包含选择做引用审计（它们不含
   EntityId 引用时可保留），并按设计 §2.1 保留目标座位自己的选择而不是快照的。
3. **未导入的字段**：`scheduled`（含 `target`）、`hats`、`revert_golden`、`discover_targets`、
   `owed`、`pending`、`stats`、英雄与能力一律保持目标座位原值。要导入 `scheduled` 需要
   其 `target` 的 typed 重映射（引擎已具备该能力，只是当前不在白名单里）。
4. **`last_board`/`seen_board`**：`last_board` 由新 board 重建；`seen_board` 与
   `scouted`（别的座位看过这个座位的战团）保持旧值，镜像对手在别人眼里仍是「上一轮看过的
   战团」，直到本轮 combat 结束。
5. **seat 映射**：固定 `target seat == source seat`（1..N）；manifest 里的
   `source_seat -> target_seat` 任意映射、缺帧 `fail_closed`/`hold_last` 策略、复现 manifest
   hash 尚未实现（当前按缺帧跳过 + 每局 `random.Random` 固定种子可复现）。
6. **`--driver bot` 只是冒烟/冷启动用**：它用 `Game.bot_action()`（不推进引擎 RNG），决策
   确定性；训练质量的库仍应来自 checkpoint 驱动（本机 `torch` 不可用，未跑）。
7. **真实库接入**（`data/real_library/obs/observations/`）：未写导入器；质量门、`build_number`
   过滤、字符串 `card_id` → `CardId` 映射、`stage` 过滤、`known_hand` 不完整等按设计 §6 仍待做。
8. **性能**：每帧 `json.dumps` + 引擎 `serde_json` 反序列化 + EID 图重映射，未做预计算/批量
   优化；注入只在每个新 turn 发生一次（≤N 次/局），未测 p50/p95 延迟。
9. **难度探针**（设计 §8.10）：未跑 100 局 bot-vs-真实战团的 mean rank/top4/吃鸡对照。
10. **`BattleEnv`/`SoloEnv`/Rust 采集器**（`collect_ppo_rust`）路径未接镜像；只在
    `collect_ppo_lockstep` 生效。
