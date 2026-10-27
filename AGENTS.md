# AGENTS.md — HSBRSIM 协作指南（AutoTavern-only）

> 目标：在 AutoTavern 的 Rust 引擎 `hsbg_engine` 上训练 AlphaZero 风格智能体：
> **不完全信息 MCTS + 8 座自对弈 + PPO**。
> 唯一数据基线：官方 **37.0.0.255790**（`data/` + `data/p2/` + `rust/.../data/cards.json`）。
> 唯一搜索/训练栈：`hsbg/az`。不要重新引入其它引擎、其它搜索或其它训练路线。

## 1. 目录

```text
rust/                    # 唯一主引擎：hsbg_engine（AutoTavern TavernGym fork，MIT）
data/                    # 37.0.0.255790 官方派生数据
data/p2/                 # AutoTavern schema cards_37.json / MANIFEST
hsbg/env/                # action_space_std（245+29）/ obs_std（3227+124）
hsbg/az/                 # 唯一搜索/自对弈/训练栈（search/belief/puct/env_api + train/）
hsbg/eval/metrics.py     # 纯函数指标
benchmarks/tavernbench/  # vendored TavernBench
tests/                   # AZ / 标准 profile / 数据 / Rust 适配
scripts/                 # verify_all / az_eval_search / az_selfplay_smoke / train_az_ppo
tools/                   # 数据更新（generate_bg_data / rea_fetch_hsdata / p2_data）
docs/                    # 当前设计（无历史报告）
```

## 2. 核心契约

- **引擎是机制/数值唯一权威**：Rust `hsbg_engine` + `rust/crates/hsbg-engine/data/cards.json`。
  改机制/数据必须登记 `rust/FORK.md`，并跑 `cargo test --release -p hsbg-engine`。
- **动作**：0..244 与 AutoTavern 逐位一致；245..273 是扩展段（Unfreeze / 备用技能槽 /
  备用选择槽 / FreezeSlot），总宽 274。前 245 永远冻结；**扩展 29 维目前仅 Python 侧声明，
  引擎未实现**（`legal_mask` 固定 245 位，`apply_index ≥ 245` 直接拒绝）。
- **观测**：3227 floats + 124 cards；`layout()` 32 项与 AutoTavern 一致；卡牌下标
  跨数据版本不可复用。
- **确定性**：同 seed + 同动作序列逐位一致；`state_json` 精确 save/restore。
- **搜索**：只允许 `hsbg/az` 的不完全信息 MCTS（PIMC/ISMCTS + PUCT）与自对弈。
- **训练**：MCTS 自对弈 → 策略/价值监督 → PPO（masked、clip、GAE）。新增方法先写测试。
- **语言**：代码注释/文档中文；标识符英文；UTF-8。

## 3. 命令

```bash
# 依赖
python -m pip install -e .
cd rust && python -m pip install -e . && cd ..

# 门禁
python scripts/verify_all.py --fast       # Rust/Python 测试 + smoke + TavernBench
python scripts/verify_all.py              # 再加 AZ smoke
python -m pytest tests -q
cargo test --release --manifest-path rust/Cargo.toml -p hsbg-engine
python scripts/run_tavernbench.py --check

# 数据（255790）
python tools/p2_data/gen_carddb_37.py --check   # 需 HSBRSIM_AT_ROOT 或 ../AutoTavern
```

## 4. 写范围（并行 agent）

| 角色 | 写范围 |
|---|---|
| Lead | `README.md`、`AGENTS.md`、`docs/`、`pyproject.toml`、`scripts/verify_all.py`、最终提交 |
| engine | `rust/**`（机制/数据）、`rust/FORK.md`、`tests/test_rust_engine.py` |
| az-search | `hsbg/az/{search,belief,puct,env_api,policy,toy_env}.py`、`tests/test_az_search.py` |
| az-train | `hsbg/az/train/**`、`scripts/az_*.py`、`scripts/train_az_ppo.py`、`tests/test_az_*.py` |
| env-profile | `hsbg/env/action_space_std.py`、`hsbg/env/obs_std.py`、对应测试 |
| data | `data/**`、`data/p2/**`、`tools/p2_data/**` |

规则：一个文件同一时间只允许一个 writer；写前 30 秒内重读；冲突时先告知 Lead。
禁止 `git reset --hard` / `git checkout -- .` / `git clean` / 全仓格式化。
任务板：`team_task_*` claim/complete，带 revision 与证据。

## 5. 验收

- `python scripts/verify_all.py` 全绿（0 failed / 0 crash / 0 invalid）。
- 改算法：固定 seed 对比 random / engine bot / 历史 checkpoint，报告 mean rank / top4 / win / legal rate。
- 改数据：`gen_carddb_37.py --check` 幂等、Rust 测试全绿、`data_info()` 版本正确。
- 纯文档：只做链接/路径自检，不跑长测试。
- 不把历史文档/旧 checkpoint/旧引擎当作现状；旧实现已删除。
