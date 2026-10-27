# 引擎 hsbg_engine（AutoTavern TavernGym fork）

## 来源与许可

| 项 | 值 |
|---|---|
| 上游 | `MCG-NJU/AutoTavern` commit `fb61201a557ddd36a411cf44aac51ce4d9b606ce` |
| 上游版本 | TavernGym v1.0.0 |
| 许可 | MIT（保留 `LICENSE/NOTICE/CITATION.cff`） |
| fork 日期 | 2026-10-26 |
| 数据 | **官方 37.0.0.255790**（AutoTavern schema，3983 卡） |

## 与上游的关系

- 目录/包名重命名：`crates/taverngym → crates/hsbg-engine`，`python/taverngym → python/hsbg_engine`，PyO3 模块仍为 `_core`。
- 相对上游的实质增量：`search.rs`（逐步 MCTS）、`turn_search.rs`（回合内搜索，当前不进入 AZ 主路径）、`db_info/data_info`、数据 meta 版本驱动、macOS 链接参数。
- 公开 API/行为与上游逐位一致；删除了 HSBRSIM 特有的 Naga 全局过滤（37.0.0.255790 池内有 1 张 DRAGON/NAGA 双种族卡 `BG32_820`，NAGA 仍不作为大厅种族开放）。
- 详细台账：`rust/FORK.md`。

## 构建

```bash
cd rust
python -m pip install -e .     # 需要 Rust 1.98.1 + maturin>=1.15
python -c "import hsbg_engine as E; print(E.game_version(), E.data_info())"
# 37.0.0.255790 {'cards': 3983, ...}
```

## 公开 API（Python）

- `Game`：`turn/num_players/is_over/needs_action/legal_mask/step/observe/bot_action/bot_play/placements/truncated_combats/health/state_json/from_json/copy/view/debug`
- `SoloEnv`：1 学习座 vs 7 脚本 bot
- `BatchEnv`：多局并行、任意 controlled 座位、save/load
- 函数：`version/game_version/server_rules_version/db_info/build_info/action_name/card_info/card_static/catalog_json/default_config_json/layout/run_bot_games`
- 常量：`N_ACTIONS=245`、`OBS_FLOATS=3227`、`OBS_CARDS=124`、`N_CARDS=3984`

## 数据

`crates/hsbg-engine/data/cards.json` 编译期 `include_str!`；由 `tools/p2_data/gen_carddb_37.py` 生成，**禁止手改**。换数据后必须 `pip install -e .` 重建。

## 确定性与性能

- 单一 xoshiro256**（SplitMix64 播种）；seed + 动作序列逐位复现；`state_json` 精确存档。
- 单核 8 人 bot：约 190–280 局/s；后期战斗 52–76k 场/s（论文口径）。
- 精确 legal mask：`legal_mask` 允许的动作一定被 `step` 接受。

## 测试

```bash
cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine
python -m pytest tests/test_rust_engine.py -q
```
