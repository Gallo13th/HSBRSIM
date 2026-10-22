# `hsbg/planning` —— 搜索（AlphaZero 类）的引擎 clone / forward 原语

> 状态：**v1（Phase 1 可用）**，2026-10-19。不修改 `hsrl2` 引擎语义。
> 基准：`runs/planning_bench.json`（由 `scripts/bench_planning.py` 生成）；
> 设计与数字说明见 `docs/ALGORITHM_RESEARCH.md` §4.2.4 / §6.3.1。

## 快速开始

```python
from hsbg.planning import model, checkpoint, rng, digest, hidden

# 1) 快速 clone（p50 ~1.1–1.6 ms / p90 ~1.8–2.0 ms，8p recruit；heap ~0.2 MB）
dup = model.clone(game)                       # strategy="fast"（默认）
dup2 = model.clone(game, strategy="deepcopy") # 正确性对照（慢，~3–4 ms）

# 2) checkpoint / push-pop（clone 快照 + 独立恢复；可重复恢复）
cp = checkpoint.push_checkpoint(dup)          # 或 CheckpointStack(dup).push()
game2 = checkpoint.pop_checkpoint(cp)         # 每次返回新的独立 Game

# 3) 合法动作 / 应用
acts = model.legal_actions(dup, hero)         # 招募期动作；有 PendingChoice 时为 choose 候选
res = model.apply(dup, hero, acts[0])         # int / ActionDescriptor / CandidateAction
model.drain_choices(dup, hero, choice_policy=None)   # 结算选择（英雄可选策略，其余默认）

# 4) RNG（chance node，~7/19/17 µs）
st = rng.get_state(game.rng)
rng.set_state(game.rng, st)
f = rng.fork(game.rng)                        # 同状态 → 同未来（独立推进）
f2 = rng.fork(game.rng, seed=7)               # 新随机流（decisions 清空）

# 5) 无副作用战斗 / 快速叶价值 forward
summary, dup_after = model.simulate_combat(dup, hero_a, hero_b,
                                           keep_state=True)   # ~1.2 ms（2v2，含 clone）
summary, _ = model.simulate_turn_combat(dup, hero)            # ~3.5 ms（8p，仅战斗裁决）
#   ↑ 替代 end_recruit_phase（~13 ms）做叶节点估值；不初始化下一回合

# 6) 摘要（去重/断言/日志）：fast ~0.2 ms，full ~2 ms
key = digest.digest(dup)

# 7) determinization v0：隐藏状态注入（实验性；建议在 clone 上做）
hidden.inject_hidden_state(dup, opponent_hero,
                           board=["BG25_001", {"card_id": "BGS_119",
                                               "atk": 5, "health": 7}],
                           hand=[], tavern=[], clear=True)
```

## 正确性/隔离保证

- `clone` 返回的副本可**独立推进**：任意动作/`end_recruit_phase` 不影响原
  `Game`；同 seed + 同动作序列 → `digest` 与 RNG 状态一致
  （`tests/test_planning.py::test_clone_*`、`test_fast_clone_matches_deepcopy`）。
- `game.db`（CardDB、CardDef frozen）**只读共享**，否则 clone 会复制 ~11 MB
  卡表（raw deepcopy ~140–160 ms）。调用方不得修改 CardDB。
- **闭包回调重绑**：引擎的 `PendingChoice.resolve_callback` / `EventListener`
  是闭包（捕获原 `hero/game/minion`）。`copy.deepcopy` 会复用同一函数 →
  副本结算任务会写回原对局。`model.clone` 已重绑（新函数对象，捕获值替换为
  副本）；**不要绕过 `model.clone` 自行 deepcopy**，也不要对会结算选择的
  分支使用 `rebind=False`。
- `pop_checkpoint` 返回的是快照的**新副本**（快照可重复恢复）；成本≈clone。
- `simulate_combat` / `simulate_turn_combat` 在 clone 上运行，原 game 的
  digest 不变、结果可复现。

## 性能（8p 招募期 T2/T4；`runs/planning_bench.json`）

| 操作 | p50 | p90 | 备注 |
|---|---:|---:|---|
| `clone`（T2/T4） | 1.14 / 1.63 ms | 1.25 / 1.75 ms | heap +202 KB；raw deepcopy ~141–159 ms |
| `legal_actions` | 0.04 ms | — | |
| `apply`（buy/upgrade/end_turn） | 0.003–0.07 ms | — | reroll 含刷新脚本 ~0.5–1.4 ms |
| `end_recruit_phase` | 12.96 ms | — | 全宏回合（含下一回合 offer 初始化） |
| **`simulate_turn_combat`** | **3.51 ms** | — | 叶价值快速 forward（不初始化下一回合） |
| `build_observation` | 0.16 ms | — | |
| `rng.get_state/set_state/fork` | 7/19/17 µs | — | |
| 搜索吞吐（clone+eval+1 动作） | N=8/16/32/64 → ~446/…/446/… sims/s | — | |

复现：

```powershell
python scripts/bench_planning.py --players-list 8,6,4,2 --turns 4 --endgame \
    --json runs/planning_bench.json
python -m pytest tests/test_planning.py -q
```

## 文件

- `model.py` —— clone / legal_actions / apply / random_rollout / evaluate /
  simulate_combat / simulate_turn_combat；
- `checkpoint.py` —— push/pop checkpoint、CheckpointStack；
- `rng.py` —— GameRNG get_state/set_state/fork；
- `digest.py` —— fast/full 状态摘要；
- `hidden.py` —— determinization v0 隐藏状态注入（实验性）。

## Hard search：rollout 到终局 / 有限 horizon

```python
from hsbg.planning.rollout_throughput import (rollout_to_end, rollout_batch,
    benchmark_rollout, HeuristicEnginePolicy, RandomEnginePolicy)

res, final_game = rollout_to_end(game, HeuristicEnginePolicy(),
                                  max_turns=None,          # None=到终局；N=截断
                                  fast_opponents=False)    # True=对手不买牌（~2x）
res.rank / res.champion / res.turns / res.steps / res.value
stats = benchmark_rollout(game, policy=..., max_turns=3, repeats=3)
```

实测（8p T2，heuristic 驱动、正常对手买牌；`runs/planning_rollout_bench.json`）：

| horizon | p50 | throughput |
|---|---:|---:|
| 到终局 | **443.5 ms** | **2.2 rollouts/s** |
| 3 回合 | 62.7 ms | 16.2/s |
| 1 回合 | 14.4 ms | 68.3/s |
| fast_opponents 到终局 | 234.1 ms | 4.36/s |

**结论**：full-to-end rollout 对 hard-search 太慢（10 候选×1 rollout≈4.5s/决策）；
建议 horizon 1–3 先筛候选，再对 top 2–3 做一次 full-to-end 复核；并行需按
"seed+动作日志 replay 重建快照"（Game 含闭包不可 pickle）。不要用
`fast_opponents` 的输出当无偏冠军率（它会高估目标英雄）。

## Live 对局辅助（live_warband）

从 `tools/live_state_mem.read_live_state()` 的 board/hand/shop 构造引擎战团，
供 live turn-search 做候选评估（不需要完整 Game/对局）：

```python
from hsbg.planning import live_warband as lw

wb = lw.build_warband(live_state, "board")          # live dict → 引擎 Minion
r = lw.simulate_combat_warbands(wb, other_wb, seed=7)   # 单场（公共 seed）
pw = lw.pairwise_winrate([wb, wb2, wb3], seed=3)        # 两两胜率矩阵
pred = lw.predict_after_action(live_state, {"kind": "buy", "shop_index": 0})
```

- **输入**：`card_id/card/id`、`atk`、`hp/health/max_hp`、`golden`、`keywords`、
  `races`、`tier`、`position`、`attached`（磁力模块近似合并）；
- **属性以 live 为准**：atk/hp/keywords 覆盖 CardDef；战斗可见关键词按 live
  精确设置（清掉 CardDef 原生但 live 列表没有的圣盾/嘲讽等）；
- **战斗**复用引擎 `run_combat`（亡语/圣盾/风怒/剧毒等脚本完整执行）；
  每次调用新建独立最小 Game/战团，输入 state 不被修改，同 seed 可复现；
- **近似**：battlecry/目标/发现/光环不结算；`predict_after_action` 只做
  buy/shop→hand、play hand→board、sell board 移除（附 `approximations`）；
  磁力 attached 合并为数值/关键词；多类型 race 只取主种族（会 warnings）。
- 性能（本机）：build 7 随从 ~0.6–0.9ms；7v7 单场 ~1.7–2.4ms；
  pairwise 8 个战团 28 场 ~57ms（约 2ms/场）。

## 边界 / 后续

- 引擎未提供 in-place restore：checkpoint 用 clone 快照实现（成本≈clone）。
- `end_recruit_phase(skip_offers=True)` **未获批准**（会改变经济/状态分布）：
  跨回合搜索的性能优先用 `simulate_turn_combat` 做叶节点；ERP 本身保持引擎语义。
- `CandidateAction` 无 `flags/power_id` 字段：候选同签名歧义按 index 消歧
  （见 `docs/ENV_INTERFACE_GAPS.md` §A7）。
- `hidden.inject_hidden_state` 为 v0（直接落位、不触发 on_summon）；与 bridge
  对齐可见信息采样后可扩展。
