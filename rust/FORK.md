# FORK.md — hsbg_engine（AutoTavern TavernGym fork）

## 1. 来源与许可

| 项 | 值 |
|---|---|
| 上游 | `MCG-NJU/AutoTavern` |
| commit | `1c2086a997afde46d68c6c5992cab194ddcfce88`（AutoTavern 1.1.0 / TavernGym 1.1.0，Battlegrounds **37.0.2**） |
| 许可 | MIT（`LICENSE` / `NOTICE` / `CITATION.cff` 原样保留） |
| 引擎数据 | AutoTavern schema，官方 **37.0.2.256589**（3983 卡，ID 与顺序同 37.0.0） |
| fork 日期 | 2026-10-26；**2026-11-04 升级到 37.0.2** |

## 2. 重命名

| 上游 | 本 fork |
|---|---|
| `crates/taverngym/` | `crates/hsbg-engine/` |
| crate `taverngym` | `hsbg-engine`（lib `hsbg_engine`） |
| `crates/taverngym-py/` | `crates/hsbg-engine-py/` |
| Python 包 `taverngym` | `hsbg_engine` |
| maturin `module-name = taverngym._core` | `hsbg_engine._core` |

## 3. 相对上游的实质改动

1. **数据替换**：`crates/hsbg-engine/data/cards.json` = 上游 37.0.2.256589 数据（3983 卡，ID/顺序同 37.0.0；含上游 37.0.2 的随从/法术/饰品/池/暗赠规则）；编译期 `include_str!`，换数据后必须 `pip install -e .`。
2. **版本 meta 驱动**：`game_version()` / `server_rules_version()` 读 `cards.json.meta`；`db_info()` / `data_info()` 供一行核对。
3. **搜索**：新增 `src/search.rs`（逐步 MCTS，PyO3 `mcts_search`）与 `src/turn_search.rs`（回合内搜索；不进入 AZ 主路径）。
4. **Naga**：默认随机大厅不主动抽 NAGA；显式 `lobby_types` 含 `NAGA` 时按 37.0.2 允许
   （池内 2 张双种族卡：BG31_330 DEMON/NAGA、BG32_820 NAGA/DRAGON；不再用随机种族替换）。
5. **构建**：macOS `cargo build --release` 的 `-undefined dynamic_lookup` 链接参数；maturin 兼容。
6. **回合末场面快照镜像**（新增能力，默认不启用）：`src/snapshot.rs` 的 `Game::apply_turn_snapshots(snaps, advance)` +
   PyO3 `Game.apply_turn_snapshots`（同时暴露只读 `Game.pool_balance()` / `pool_species_violations()` /
   `invariant_violations()` 与 `snapshot_schema_version()`）。语义与白名单见 `docs/MIRROR_SNAPSHOT_DESIGN.md`
   「实现状态」：字段白名单替换 + typed EID 重映射 + `pool_delta_unknown`（旧持有物按 pool parts 归还、
   注入实体 `pool_copies=0`）。不改变任何既有机制/数值与默认行为（无调用时零影响）。
7. **人类战团（board-only）注入**（新增能力，默认不启用）：`src/snapshot.rs` 的
   `Game::inject_board(seat, minions, tier)` + PyO3 `Game.inject_board(seat, [[card, atk, hp], ...], tier=None)`。
   只替换 `board`（+ 可选 `tier`）与派生 `last_board`；hand/shop/资源/生命周期/配对全部保留；
   新随从 `alloc_eid()` 重分配且 `pool_copies=0`（`pool_delta_unknown`），旧 board 持有量归还共享池；
   指向被移除旧实体的 typed 引用（`link/group/src`、`hats`、`revert_golden`、`discover_targets`）就地清空；
   逐座位事务（非法输入不改状态/`next_eid`）；**不设置** `ended_turn`。语义与近似边界见
   `docs/HUMAN_BOARD_OPPONENT.md`。不改变任何既有机制/数值与默认行为（无调用时零影响）。

除此之外，公开 API/行为、245 动作、3227+124 观测、`state_json`、seed 确定性、BatchEnv 语义与上游一致。

## 4. 数据

- `data/cards.json` 由上游 AutoTavern 37.0.2 发布物提供（3983 卡，ID 与顺序与 37.0.0 相同）；
  不再由 `tools/p2_data/gen_carddb_37.py` 生成，禁止手改。
- 当前数据版本：`37.0.2.256589`；`game_version()` 实测返回该值。
- 换数据：替换 JSON → `cd rust && python -m pip install -e .` → `cargo test --release -p hsbg-engine`。
- **37.0.2 升级**（2026-11-04）：公开接口不变（245 动作 / 3227+124 观测 / state_json / seed 确定性）；
  变化集中在随从/法术/饰品数值、池成员、大厅 t7–9 类型保底、Dark Gift 规则与 Kiri's Eclipse/Minion Bait。
  旧 37.0.0 checkpoint 可直接加载（卡表顺序不变）。

## 5. 测试/构建

```bash
cd rust
python -m pip install -e .
cargo build --release -p hsbg-engine
cargo test --release -p hsbg-engine
python -m pytest ../tests/test_rust_engine.py -q
```

当前：Rust 39 套件全绿；Python 适配测试全绿；`N_ACTIONS=245`、`OBS_FLOATS=3227`、`OBS_CARDS=124`。

## 6. 规则权威

- 机制/数值以 `hsbg_engine` + 官方 37.0.0.255790 数据为准；AutoTavern 是第三方重建，不是官方服务端。
- 任何机制修正必须：写失败测试 → 改 Rust → 跑全量 Rust 测试 → 记录到本文件（动机/证据/影响）。
- 不保留其它引擎作为 fallback。

## 2026-11-03 `tier_upgrade_discount`（A/B 关卡，默认 0 = 逐位等价）

- `RulesConfig::tier_upgrade_discount: i32`（默认 0，`#[serde(default)]`）：`upgrade_price()` 返回
  `(upgrade_cost + power_extra − discount).max(0)`。**只改升本费用计算**，收入/商店/其他规则一律不变。
- **默认 0 逐位等价**：`tier_upgrade_discount_zero_is_default` 断言默认配置下 `upgrade_price(0) == 5`；
  `tier_upgrade_discount_two` 断言折扣 2 下回合 1 升级价 5 → 3。
- 传播路径：训练入口 `--tier-upgrade-discount N` → 环境变量 `HSBG_TIER_UPGRADE_DISCOUNT` →
  `hsbg/az/train/game_rules.py::game_config_json()` → `E.Game(seed, config_json=...)`
  （采集 worker / 评估 / collector 的全部创建点）。
- 依据与 A/B 判据：`docs/ECONOMY_CEILING.md` §5①（s28 系列：升本与盘子零和；A2 判据 t9 tier p50≥5、
  t9 Σ≥280、death≥11、human≤6.30）。

## 2026-11-05 `sell_minion` 越界防御 + 目标侧校验（B03 采集崩溃修复）

- 现象：B03（`runs/az_stage300m_b03`）在 77.69M decisions 时 `worker16` panic：
  `crates/hsbg-engine/src/recruit.rs:634:35: removal index (is 6) should be < len (is 5)`，
  发生在 `bot_play` 的招募阶段；训练进程 rc=1 退出。
- 修复（`Ctx::sell_minion` 与三个脚本调用方）：
  - `sell_minion` 在 `Vec::remove` 前检查 `idx < boards[side].len()`；越界时向 stderr 打印
    不变量违例 + 调用点回溯（`std::backtrace::Backtrace::force_capture`）并**跳过**该次 sell，
    不再 panic 打死采集 worker。
  - `EBG_Spell_032`（Channel the Devourer）、`BG20_HERO_301p`（Nightmare Ectoplasm）改用
    `locate` 返回的 `side`（原实现用 `me.side`），并校验 `i < boards[side].len()`；
    `BG23_HERO_306_Buddy` 增加同样的界检查。
- 回归：`tests/mechanics.rs::sell_minion_out_of_range_is_skipped`（越界 no-op、合法 sell
  仍生效）；`cargo test --release -p hsbg-engine` 全绿（2026-11-05）。
- 说明：触发该越界的唯一路径未定位（纯 bot fuzz 约 10 万局未复现），防御 + 回溯日志用于
  下一次复现时定位；三种改法都不改变合法路径的行为。

## 2026-11-03 `gold_bonus_by_turn`（A/B 关卡，默认空 = 逐位等价）

- `RulesConfig::gold_bonus_by_turn: Vec<(u32, i32)>`（默认空）：`start_turn_player` 时
  `gold = min(base + max_gold_bonus, 99) + gold_bonus_at(turn) + gold_next_turn`；
  **只加指定回合的额外金币**，其余规则不变。依据：Firestone 真实成功组 p90 收入差额 t5 +1 / t7 +1 / t9 +3。
- **默认空逐位等价**：`gold_bonus_by_turn_zero_is_default` 断言默认无加成；`_applies` 断言 t2 base 4 + 1 = 5。
- 传播：训练入口 `--gold-bonus-turn "5:1,7:1,9:3"` → `HSBG_GOLD_BONUS_TURNS` → `game_config_json()` → 全部 `E.Game(config_json=...)`。
- **2026-11-07 `RulesConfig::banned_trinkets: Vec<String>`（默认空）**：生成饰品报价时
  `flow.rs::trinket_offer` 的候选集里直接剔除这些 card id（按 `CardDef.id` 字符串比对）。
  用途：`docs/B07_DESIGN.md §9` 的「加重护手（`BG36_MagicItem_414`）禁用」对照实验——
  该饰品回合结束 +1/+1 且每回合翻倍，会让低本阵容把属性滚到 5 倍以上，干扰"升本换核心"的评估。
- 传播：环境变量 `HSBRSIM_BAN_TRINKETS="id1,id2"` → `hsbg/az/train/game_rules.banned_trinkets()`
  → `game_config_json()` → 全部 `E.Game(config_json=...)`；训练/评测同时生效。
- 测试：`tests/trinket_ban.rs`（禁用它后 24 个种子 × lesser/greater 报价均不含该 id；
  禁掉全部 lesser 饰品时报价退化为空且不 panic）。
- **2026-11-08 空 mask 死锁修复（付费饰品单买不起时无合法动作）**：
  现象：训练采集持续报 `存在无合法动作的行（mask 全 False）`（今天 194 个现场 dump）。
  根因：`Pending::Trinket { free: false }` 的报价单挂起后金币被花掉，四个选项
  `trinket_price(p, t) > gold` 全部不可选，而 `Pending::cancellable()` 对饰品单恒为
  false —— `legal_mask` 的 pending 分支只置 `A_CHOOSE*`/`A_CANCEL`，于是整座 mask 全
  false，`needs_action` 又为 true，整局卡死。
  修复：①`actions.rs::legal_mask` 在 pending 分支统计"有没有任何合法选项"，若一个都
  没有则**强制放行 `A_CANCEL`**（逃生口）；②`recruit.rs::cancel` 识别"付费饰品单一个
  都买不起"的情形，走已有的 `drop_unaffordable_trinket_offers` 放弃该单（而不是报
  `nothing to cancel`）。
  验证：`tests/empty_mask.rs` 用现场 dump（`tests/fixtures/empty_mask_trinket.json`）
  断言修复后 mask 含 `A_CANCEL`、`apply` 成功；离线重放 **194/194** 个历史 dump 全部
  恢复出合法动作（修复前 18/194 复现空 mask）。
