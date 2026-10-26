# Rust TurnSearch（回合内 pairwise 搜索）

对应旧 Python `hsbg/search/turn_search.py` 的 Rust 重实现，代码：

- `rust/crates/hsbg-engine/src/turn_search.rs`
- PyO3：`hsbg_engine.turn_search(...)`
- 基线脚本：`scripts/az_turn_search_test.py`

## 算法（按旧版复原）

不做完整 bot rollout，也不预测下一回合：

```text
当前合法动作 a（按旧 driver 顺序：buy → play → sell → move → power
  → activate → upgrade → reroll → freeze → dark gift → end）
  → 应用 a（不推进回合）
  → 用 heuristic completion 补完本回合（在 EndTurn 前停住）
  → 枚举最多 states_budget 个回合末状态
  → 状态两两 simulate_combat，score(s)=mean winrate(s vs others)
  → 每个动作取可达状态的 max/mean 分数
  → argmax 执行一步；新状态重新搜索
```

对齐旧版的点：

- **动作顺序**对齐 `hsbg/env/driver.enumerate_actions`（buy head → plays → tail），
  不是 Rust 245 动作空间的下标顺序；
- completion 使用 Rust 移植的 `hsbg.agents.heuristic.HeuristicPolicy`
  （`heuristic_action`），不是引擎 bot；
- `Cancel` 不参与搜索；`Freeze` 只在未冻结时生成（对齐旧 driver 单向 Freeze）；
- EndTurn 直接返回当前状态作为回合末状态；
- pairwise 用 `Game::simulate_combat`，双方取两个 state 的 seat0 战团。

仍未完全等价：

- Python `HeuristicPolicy` 的买牌/卖牌评分只做了精简移植，不是逐行等价；
- 旧版 `run_combat` 与 Rust `simulate_combat` 的英雄/饰品持久效果口径不同；
- 当前对手是 Rust engine bot，旧实验对手是 legacy `heuristic/teacher`；
- 旧版 50 局/BC 对照实验的 checkpoint 已清理，当前按用户要求**不依赖 BC**。

## Python API

```python
import numpy as np
import hsbg_engine as E

r = E.turn_search(
    game, seat=0,
    states_budget=16,
    samples_per_action=1,
    combat_samples=1,
    max_steps_per_turn=40,
    seed=0,
    aggregate="max",        # max / mean
)
scores = np.frombuffer(r[0], dtype="<f4")  # f32[N_ACTIONS]
action, score, n_states, n_combats = r[1], r[2], r[3], r[4]
```

返回：

- `r[0]`：`f32[N_ACTIONS]` action scores（未评估动作 0）；
- `r[1]`：选中的 action index；
- `r[2]`：best score；
- `r[3]/r[4]`：枚举状态数 / pairwise 战斗数。

## 运行基线

```bash
cd ~/projects/HSBRSIM
PYTHONPATH=$HOME/projects/HSBRSIM/rust/python \
  $HOME/.conda/envs/hiermolgen/bin/python \
  scripts/az_turn_search_test.py \
  --games 20 --states-budget 16 --seed 70000 \
  --out runs/turn_search_rust
```

脚本在 pending choice/targeting 时自动选合法项；并对连续重复的 Move/Freeze/Refresh
做回合推进守卫。

## 测试

```bash
cd rust
RUSTUP_TOOLCHAIN=1.98.1 cargo test -p hsbg-engine --lib turn_search
```

已验证：2 个 Rust 单元测试通过（合法动作/状态预算/确定性）。

## 测试结果（2026-10-26，新 Rust 引擎）

### Rust TurnSearch，3 局，states16，seed 70000

```text
mean_rank = 8.00
top4 = 0%
win = 0%
decisions/game ≈ 30
states/search ≈ 8.2
combats/search ≈ 36.4
```

### 旧 Python TurnSearch 对照（单局，legacy，seed 300，无 BC）

```text
rank = 5
turns = 11
steps = 344
elapsed ≈ 374s
```

结论：**旧版 mean rank 2.90（50 局）目前没有在 Rust 引擎/新对手上复现。**
单局旧版 seed300 也只有 rank5，说明旧 2.90 是 50 局配对结果，不是任意单局保证；
同时 Rust 版仍存在以下差异，需要继续对齐后才能直接比较：

1. completion heuristic 是精简移植，买/卖/刷新细节与旧 Python 不完全一致；
2. 旧实验对手是 legacy heuristic/teacher，新 baseline 对手是 Rust engine bot；
3. 旧实验用 legacy `hsrl2` 8 人环境，新实验是 37 数据/Rust 245 动作；
4. pairwise 战斗的持久效果/RNG 口径不同；
5. 旧 50 局有 BC 对照实验，当前按要求不依赖 BC，只有脚本对手。

## 下一步

1. 用旧 Python TurnSearch 在 seeds 300–349 重跑 50 局（无 BC pairwise 模式），
   与当前 Rust 结果做同一 seed 的逐局对照；
2. 逐项对齐 `HeuristicPolicy` 的 `_best_play/_best_buy/_sell_decision/_simple_spell`
   与 reroll 上限；
3. 对齐旧 `run_combat` 与 `simulate_combat` 的 board/hero 状态；
4. 对齐对手策略后再判定 Rust TurnSearch 是否达到旧 rank 2.9；
5. 若要提高强度，优先增加 `combat_samples`（64–256）或对 finalists 做高采样，
   而不是把全矩阵做成 20k 战斗。
