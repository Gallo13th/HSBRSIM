# Rust TurnSearch（回合内 pairwise 搜索）

对应旧 Python `hsbg/search/turn_search.py` 的 Rust 重实现，代码：

- `rust/crates/hsbg-engine/src/turn_search.rs`
- PyO3：`hsbg_engine.turn_search(...)`
- 基线脚本：`scripts/az_turn_search_test.py`

## 算法

不做完整 bot rollout，也不预测下一回合：

```text
当前合法动作 a
  → 应用 a（不推进回合）
  → 用引擎 bot 补完本回合（在 EndTurn 前停住）
  → 枚举最多 states_budget 个回合末状态
  → 状态两两 simulate_combat，score(s)=mean winrate(s vs others)
  → 每个动作取可达状态的 max/mean 分数
  → argmax 执行一步；新状态重新搜索
```

与旧版的关键差别：

- completion 用 **Rust 引擎 bot**（`bot::choose_action`），不是 Python HeuristicPolicy；
- pairwise 用 `Game::simulate_combat`；
- `Freeze` / `Refresh` 不做 completion（它们不消耗回合；否则 completion 里的 bot
  买牌会被错误算成这两个动作的价值）；
- 与根状态无变化（no-op）的动作跳过；
- `Freeze/Refresh`、`EndTurn` 有轻量负先验，避免纯界面动作排在 Buy/Play 前。

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

## 测试

```bash
cd rust
RUSTUP_TOOLCHAIN=1.98.1 cargo test -p hsbg-engine --lib turn_search
```

已验证：2 个 Rust 单元测试通过（合法动作/状态预算/确定性）。

## 初始 smoke 结果

3 局 / states_budget=16 / seed 70000：

```text
mean_rank = 7.67
top4 = 0%
win = 0%
decisions/game ≈ 35
states/search ≈ 9.0
combats/search ≈ 43.2
```

这个数字**不是强度结论**：当前 Rust 版仍是对当前回合的 pairwise 搜索，且 seat0 的
动作执行/结束回合守卫较保守；它主要用于验证 Rust 搜索核/接口，以及作为后续
action-value、completion policy 和状态预算调参的基线。

## 后续

1. 用 20–50 局、states_budget 8/12/16 做预算曲线；
2. 加入 `samples_per_action` 的独立 RNG / completion policy 选项；
3. 若要对齐旧 Python TurnSearch，先用旧 harness 在相同 seeds 跑一次对照，
   再统一 completion policy 与动作排序；
4. 若要更强基线，优先把 leaf 改为“当前回合结束后的实际战团”而不是
   completion-bot 状态，并加入跨回合截断（A/B'' 方案）。
