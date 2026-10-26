# AutoTavern Rust 环境与 RL 训练（hsrl2 已停用）

> 决策（2026-10-26）：**放弃 `hsrl2` 作为运行时模拟器**。项目只使用 AutoTavern
> fork 的 Rust 引擎 `hsbg_engine`（`rust/`，TavernGym 系）作为模拟与训练环境。
> `hsrl2/` 仅保留为历史/差分参考，不进入默认训练、采集、评测路径。

## 1. 运行时接口

主环境适配器：

- `hsbg.backends.taverngym_env.TavernGymEnv`
- 别名：`hsbg.backends.RustEngineEnv` / `AutoTavernEnv`
- 实际加载顺序：`hsbg_engine` →（可选）外部 `taverngym`

```python
from hsbg.rl.envs import make_env

env = make_env(backend="rust", seed=0)  # 默认后端
obs = env.reset(seed=0)
obs, reward, terminated, truncated, info = env.step(0)  # 候选下标
env.close()
```

`TavernGymEnv` 把 Rust `hsbg_engine.Game` 包装成 `hsbg.rl.api.EnvLike`：

- `reset(seed) -> Observation`；
- `step(candidate_index | CandidateAction) -> (obs, reward, terminated, truncated, info)`；
- `save_state()/load_state()` 精确存档；
- `extra["taverngym"]["flat_action_indices"]`：候选下标 ↔ 245 维 AutoTavern 动作；
- `info["backend"] = "hsbg_engine"`。

`make_env` 后端：

| backend | 说明 |
|---|---|
| `rust` / `hsbg_engine` / `real`（兼容别名） | AutoTavern Rust 环境（默认） |
| `auto` | Rust 可用则用 Rust，否则 `mock` |
| `mock` | 纯 Python 合成环境，仅接口/训练管线自测 |

## 2. 训练/采集/评测

```bash
# PPO：默认 --env rust
python scripts/train_ppo.py --env rust --total-steps 3000 --num-envs 2 --out runs/ppo_rust

# 采集轨迹（观测级策略）
python -m hsbg.rl.collector --policy heuristic --envs 2 --episodes 10 \
  --backend rust --out runs/rl/heuristic.jsonl

# 评测
python -m hsbg.rl.evaluate --policy heuristic --episodes 20 --backend rust

# BC 示范数据（观测级 heuristic，Rust 环境）
python scripts/collect_bc.py --episodes 100 --workers 4 \
  --out runs/bc_data/heuristic_rust.pkl

# 策略评测
python scripts/evaluate_policy.py --policy runs/ppo_rust/policy_final.pt \
  --env rust --episodes 20
```

训练侧 `hsbg.train.vec_env.make_vec_env` 的 `mode` 现在为：

```text
rust / hsbg_engine / real → Rust 单环境 + SyncVecEnv
auto                       → Rust 可用则用，否则 mock
mock                       → 合成环境
```

## 3. 已验证

在开发机（Rust 1.98.1 + HierMolGen Python 3.10）实测：

```text
TavernGymEnv.reset/step：通过（phase=choice，step 返回 backend=hsbg_engine）
run_episode(random)：rank=8，43 steps，terminated=True
make_vec_env(2, mode="rust")：reset/step 通过
train_ppo.py --env rust --total-steps 64：训练完成，checkpoint 已保存
collect_bc.py --episodes 1：242 samples，rank=1
collector/evaluate --backend rust：1 局通过
tests/test_rl_api.py + test_rl_collector.py + test_rl_evaluate.py + test_rl_gym.py：通过（teacher 旧引擎用例 skip）
```

## 4. 与旧 hsrl2 的差异/注意

1. **动作空间**：AutoTavern 是 245 维固定动作 + mask；适配器把它展开成
   `Observation.candidates`，候选数可能超过 `hsbg.env.spec.CANDIDATE_MAX=64`。
   现有策略编码器会在 64 处截断；大规模训练前应决定：
   - 提高 `CANDIDATE_MAX`，或
   - 只保留合法 mask 的固定 245 维动作接口训练。
2. **对手**：Rust 环境的其他座位固定使用引擎内置 bot；旧 `opponent=heuristic/teacher`
   参数不再生效。
3. **teacher 策略**：`hsbg.rl.policies.TeacherPolicy` 依赖 legacy `env.game/env.agent_hero`，
   在 Rust 后端不可用；请使用 `heuristic/random/checkpoint`（观测级策略）。
4. **数据**：Rust 引擎使用 `rust/crates/hsbg-engine/data/cards.json`
   （37.0.0.255130，当前版本无 Naga 随从池）。
5. **存档**：Rust `Game` 是 PyO3 对象，不能跨进程 pickle；多进程采集必须在 worker
   内 `make_env`，`hsbg.rl` 已按此设计。
6. **单局速度**：Rust 引擎单步比 hsrl2 快，但适配器观测构建（尤其 `view`）有额外开销；
   训练优先 `obs_source="features"`。

## 5. 迁移清单

- [x] `hsbg.rl.envs.make_env` 默认 `rust`
- [x] 适配器优先 `hsbg_engine`
- [x] `hsbg.train.vec_env` 使用 Rust env
- [x] `train_ppo` / `evaluate_policy` 默认 `rust`
- [x] `collect_bc` 改用观测级 heuristic + Rust env
- [x] `collector/evaluate` 默认/支持 `rust`
- [x] RL 测试迁移；teacher 旧引擎用例按 Rust 后端 skip
- [ ] 固定 245 维动作训练接口（如需要，另立任务）
- [ ] 训练吞吐/收敛对比（Rust vs 旧 hsrl2）归入性能报告
