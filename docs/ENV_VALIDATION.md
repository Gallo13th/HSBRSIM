# 环境验收报告（ENV_VALIDATION）

> 日期：2026-10-18 ｜ 数据基线：官方 37.0.0.255130 ｜ 引擎：`hsrl2`（4,315 passed）
> 一键复现：`python scripts/validate_env.py --games 30 --json runs/env_validation.json`
> 全量门禁：`python scripts/verify_all.py`（7/7 gates，97s）

## 0. 观测契约 v2（2026-10-18）

`Observation.version = 2`，新增 **`extra: Dict[str, Any]`**（决策相关但非实体槽位）：
`frozen_tavern` / `power_uses_left` / `second_power_id` / `quest_progress` /
`dark_gift_uses_left` / `next_opponent` / `last_opponent` / `elimination_order` /
`last_combat` / `pending_hand_queue` / `minion_flags` 等。
纯数据（可 pickle、无引擎对象、每步独立），与 `info["obs_extra"]` **同源**。
`tests/test_env_coverage.py` 对 31 个契约键、pickle、跨进程、只读性做硬门禁。

## 1. 结论

**RL 环境接口验收通过**：单局闭环、info 契约、确定性、2/4/8 人多人数、
PendingChoice 选择步、非法动作防护、VecEnv 契约、奖励公式全部通过；
30 局 0 崩溃、0 超时、0 invalid。

| 检查 | 结果 |
|------|------|
| 单局闭环（30 局，8 人，启发式） | ✅ completed=30/30，truncated=0 |
| `info` 契约字段（turn/rank/health/armor/alive_count/combat/invalid/terminated_reason/seed/episode_steps） | ✅ 全齐 |
| 名次范围 | ✅ 1..N（30 局分布 1:2 / 2:3 / 3:4 / 4:4 / 5:3 / 6:8 / 7:4 / 8:2） |
| 确定性（同 seed + 同策略） | ✅ 观测/候选签名序列、步数、名次、总奖励逐位一致 |
| 2/4/8 人多人数 | ✅ 均正常完成，名次合法 |
| PendingChoice 选择步 | ✅ 30 局共 261 个 choice 步，phase/候选/结算契约正确 |
| 非法动作防护 | ✅ `invalid=True`、状态不推进、候选数不变 |
| 纯 placement 奖励公式 | ✅ 累计奖励 == `1 - 2*(rank-1)/(N-1)`（集成测试断言） |
| SyncVecEnv 自动 reset / dones / infos / terminal_observation | ✅ |
| Gymnasium 包装 | ✅ `check_env` 通过（mock+real）；`Discrete(64)` + `action_masks()` |

## 2. 性能（本机，30 局 × 8 人，启发式）

| 指标 | 数值 |
|------|------|
| 单局平均 | **349.6 ms**（validate_env 30 局；bench 20 局 396 ms，随负载 300–500 ms） |
| 单决策步 | **4.43 ms**（招募步 0.76–0.78 ms） |
| 单进程吞吐 | **2.86 局/s** |
| 8 进程采集 | **12.7 局/s（1,515 步/s）** |
| 平均回合 | 10.9 |
| 30 局平均名次 | 4.77（教师策略；100 局评测 4.24） |

（`scripts/bench_env.py --seeds 20` 另测：单局 242–694 ms，招募步 0.76 ms，
`end_recruit_phase` ~10 ms；4 进程采集 7.4 局/s。）

## 3. 已实现的环境契约（摘要）

- **观测**：`Observation`（39 实体槽容量：board 7 / hand 10 / tavern 7 /
  trinket 2 / quest 1 / opponent 7 / choice 5）+ 全局标量 + 实体 token
  （card_id/atk/health/tier/cost/races/keywords/golden/zone/slot）。
- **动作**：每步枚举合法 `CandidateAction`（buy/sell/play_minion/play_spell/
  reroll/upgrade/freeze/hero_power/activate/use_dark_gift/choose/end_turn），
  含目标组合与位置；候选即合法（非法动作有防御）。
- **选择步**：招募期 PendingChoice 暴露为 `phase="choice"`（候选仅 choose）；
  战斗内选择自动结算（引擎不可中断，已在 ENV_SPEC 记录边界）。
- **奖励**：名次为主 + 生命/战斗净伤/场面战力塑形 + 非法/超时惩罚；可配置。
- **回合**：每回合动作预算 40、freeze 单向、无进展保护（防 no-op 死循环）。
- **名次**：监听 `hero_eliminated` 记录淘汰顺序，`rank = 淘汰时存活数 + 1`，
  冠军 = 1。
- **确定性**：`seed` 决定英雄抽取与引擎 RNG（独立 RNG 流不污染 `game.rng`）。
- **向量化**：`VecEnv`（Windows spawn，多进程）/`SyncVecEnv`（单进程多环境），
  auto-reset、`dones`、`infos["terminal_observation"]` 契约；同 seed 与单环境一致。
- **只读观测**：连续构建 3 次观测前后引擎状态与 `game.rng.decisions` 不变
  （env 测试覆盖）。

## 4. 已知接口缺口（正在处理）

| 缺口 | 影响 | 计划 |
|------|------|------|
| 部分需要目标的法术/双目标英雄技能候选枚举保守 | 策略可能无法选择某些目标动作 | env-builder 目标枚举补全 |
| 观测缺 `frozen`、技能剩余次数、任务进度、combat 阶段等字段 | 策略信息不完整 | 评估后改 `spec.py`（升 version） |
| `CANDIDATE_MAX=64` 裁剪 | 极端局面少数变体不可选 | 覆盖率审计 + 必要时提高上限 |
| Gymnasium spaces / action mask 标准封装 | 接入通用 RL 库 | ✅ `hsbg/rl/gym_wrapper.py`（`check_env` 通过） |
| 高并发轨迹采集器 | 数据搜集 | ✅ `hsbg/rl/collector.py`（8 进程 12.7 局/s，JSONL） |

## 5. 验收命令

```powershell
cd C:\HSagent
python scripts/validate_env.py --games 30 --json runs/env_validation.json
python -m pytest tests/test_integration.py -q
python -m pytest tests -q
python scripts/bench_env.py --seeds 20
python scripts/demo_env.py --seed 42
```

## 6. 高并发数据采集吞吐（`scripts/bench_collect.py`，teacher 策略，真环境）

| workers | 局数 | games/s | 加速比 | steps/s | mean_rank |
|--------:|-----:|--------:|-------:|--------:|----------:|
| 1  | 8  | 2.65  | 1.00x | 264  | 3.875 |
| 2  | 16 | 4.61  | 1.74x | 452  | 4.00  |
| 4  | 32 | 6.98  | 2.63x | 663  | 4.281 |
| 8  | 64 | 10.73 | 4.05x | 1044 | 4.25  |
| 12 | 96 | 12.57 | 4.74x | 1181 | 4.417 |

- 12 workers 时单局摊薄 **80 ms**（实际每局 CPU ~370ms，并行摊薄）；invalid=0 / errors=0 / truncated=0。
- 加速比亚线性来自本机同时运行其他 agent/负载；空闲时可更高。
- 复现：`python scripts/bench_collect.py --worker-list 1,2,4,8,12 --episodes-per-worker 8 --policy teacher`
- 采集产物：`runs/bench_collect.json`；JSONL schema 见 `docs/RL_INTERFACE.md`。

## 7. 奖励信号校验（RL 接口正确性）

40 局采集数据（`runs/rl/lead_heur_40.jsonl`）按终局名次统计累计奖励：

| 名次 | 1 | 3 | 4 | 5 | 6 | 7 | 8 |
|------|---|---|---|---|---|---|---|
| 平均累计奖励 | +0.865 | -0.066 | -0.318 | -0.555 | -1.013 | -1.306 | -1.610 |

名次与累计奖励的相关系数 **-0.995**（越靠前奖励越高），奖励信号方向正确、区分度充分。

## 8. 模型策略采集（checkpoint 路径）

```powershell
python -m hsbg.rl.collector --policy runs/bc/official_320/policy_bc.pt `
    --envs 4 --episodes 16 --out runs/rl/bc_ckpt_16.jsonl
# 实测：7.35s / 1,569 步 → 2.18 局/s；mean_rank 4.25（与 100 局评测 4.34 一致）
# invalid=0 / errors=0 / truncated=0
```

说明 RL 接口可直接用训练好的 checkpoint 做离线采集/评测（多进程、确定性、JSONL）。
