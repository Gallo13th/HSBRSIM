# FORK.md — hsbg_engine（AutoTavern TavernGym fork）

## 1. 来源与许可

| 项 | 值 |
|---|---|
| 上游 | `MCG-NJU/AutoTavern` |
| commit | `fb61201a557ddd36a411cf44aac51ce4d9b606ce`（TavernGym + TavernBench v1.0.0） |
| 许可 | MIT（`LICENSE` / `NOTICE` / `CITATION.cff` 原样保留） |
| 引擎数据 | AutoTavern schema，官方 **37.0.0.255790**（3983 卡） |
| fork 日期 | 2026-10-26 |

## 2. 重命名

| 上游 | 本 fork |
|---|---|
| `crates/taverngym/` | `crates/hsbg-engine/` |
| crate `taverngym` | `hsbg-engine`（lib `hsbg_engine`） |
| `crates/taverngym-py/` | `crates/hsbg-engine-py/` |
| Python 包 `taverngym` | `hsbg_engine` |
| maturin `module-name = taverngym._core` | `hsbg_engine._core` |

## 3. 相对上游的实质改动

1. **数据替换**：`crates/hsbg-engine/data/cards.json` = 37.0.0.255790 AutoTavern schema（3983 卡 = 3695 映射 + 288 compat）；编译期 `include_str!`，换数据后必须 `pip install -e .`。
2. **版本 meta 驱动**：`game_version()` / `server_rules_version()` 读 `cards.json.meta`；`db_info()` / `data_info()` 供一行核对。
3. **搜索**：新增 `src/search.rs`（逐步 MCTS，PyO3 `mcts_search`）与 `src/turn_search.rs`（回合内搜索；不进入 AZ 主路径）。
4. **Naga**：移除 HSBRSIM 早期的 Naga 全局过滤；37.0.0.255790 池内保留 1 张 DRAGON/NAGA 双种族卡 `BG32_820`，NAGA 仍不作为大厅种族开放。
5. **构建**：macOS `cargo build --release` 的 `-undefined dynamic_lookup` 链接参数；maturin 兼容。
6. **回合末场面快照镜像**（新增能力，默认不启用）：`src/snapshot.rs` 的 `Game::apply_turn_snapshots(snaps, advance)` +
   PyO3 `Game.apply_turn_snapshots`（同时暴露只读 `Game.pool_balance()` / `pool_species_violations()` /
   `invariant_violations()` 与 `snapshot_schema_version()`）。语义与白名单见 `docs/MIRROR_SNAPSHOT_DESIGN.md`
   「实现状态」：字段白名单替换 + typed EID 重映射 + `pool_delta_unknown`（旧持有物按 pool parts 归还、
   注入实体 `pool_copies=0`）。不改变任何既有机制/数值与默认行为（无调用时零影响）。

除此之外，公开 API/行为、245 动作、3227+124 观测、`state_json`、seed 确定性、BatchEnv 语义与上游一致。

## 4. 数据

- `data/cards.json` 只允许由 `tools/p2_data/gen_carddb_37.py` 生成；禁止手改。
- 当前数据版本：`37.0.0.255790`；`game_version()` 实测返回该值。
- 换数据：替换 JSON → `cd rust && python -m pip install -e .` → `cargo test --release -p hsbg-engine`。

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
