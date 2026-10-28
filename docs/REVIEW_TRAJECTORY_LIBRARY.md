# PPAI GPT-6 Astra 终审：对手场面轨迹镜像库 v2

> 评审模型 `ppai/gpt-6-astra`（只读，未占 GPU）。**结论：不通过 —— 正式训练保持 `p=0`**；
> 仅允许修复后的离线 CPU 验证与隔离研究。本轮已按其阻断项修复（见 §2），但未获准混入。

## 1. 评审结论与硬门（原文要点）

**阻断**
1. `capture_trajectory` 的状态/动作错位（保存的是**下一回合**的 state，却配上一回合的 actions）；
   `--every=2` 丢中间回合动作 —— **已修**（见 §2）；
2. v1 单座位注入仍在训练执行路径且未与轨迹开关互斥 —— **已修**（v1 在采集器与 CLI 双重禁用）；
3. `Game.from_json` 只做 `check_loaded`，不校验 `next_eid` 唯一性、players/eliminated/pairs/
   phase/ending_turn 一致性、pool 总量 —— **已补 property 测试**（见 §2）。

**重要**
- 回放动作「合法 ≠ 语义相同」：capture 与 lockstep 的决策时序/RNG/池时序不同，记录的原始动作可能
  指向不同的店面/目标；`illegal=0` 只说明 learner 没非法，不能证明对手强；
- `trajectory_games` 可能低于 `p·N`（恢复点 learner 已淘汰即跳过）——已加重采样与 `trajectory_skipped`；
- 从 turn≥6 恢复 ⇒ 只在中局训练：turn 分布/样本量偏移，`placements` 是重放后的新名次；
- 强度指标 `len(frames)+1` 与真实强度无关；`generation_decay` 之前未生效 —— 已改为 mtime 衰减评分。

## 2. 本轮已修（HEAD `5727050`）

| 项 | 修复 | 证据 |
|---|---|---|
| 状态/动作错位 | 帧 = **本回合开始时刻的 state** + 本回合 actions；不再丢弃中间回合 | 恢复 frame(turn=6) → `game.turn==6`，其 89 个动作回放 **0 illegal** |
| v1 互斥 | `collect_ppo_lockstep` 遇 `library_p>0` 直接 `RuntimeError`；`train_entity_sync --library-p>0` 直接退出（返回 2） | 全量 pytest 绿 |
| 恢复不变量 | 新增 `tests/test_state_restore.py`：恢复后 `state_json` 完全一致、同动作逐步无分叉、alive/placement/eliminated/next_eid 一致、**每个 turn 恢复后都能打到 1..8 合法终局** | 2 seeds × 多 turn 通过 |
| 重放统计 | meta 增 `trajectory_attempt/replayed/illegal/fallback/skipped` | 冒烟：attempt 1060 / replayed 920 / illegal 140 / fallback 167 |
| 采样 | strength 排序 + **mtime 世代衰减**；worker 缓存键改为「文件数 + 最大 mtime」 | 单测通过 |
| 体积 | 文档记录 105 KB/局（gzip），并接受评审的「每 worker 一份、需 manifest+LRU 分片」建议 | 文档 |

## 3. 评审给出的混入协议（**未执行，留给下一阶段**）

- 冻结 manifest + 历史 checkpoint 分层；**5 个训练种子同起点**；`p=0 / .05 / .10`（通过后最多 .20）；
- 三组对照：**A** 常规 turn1 bot、**B** 同入口状态 bot（无脚本）、**C** 同状态 replay
  —— 用于分离「中局课程」与「对手收益」；
- 训练外固定未见种子面板 ≥1000 局/种子；按**等 learner 决策数**而非等 episode/iter 预算；
  同时报「全局新局」与「中局 holdout」评估；
- 记录：requested/effective p、轨迹 ID/ckpt/turn/seed、重放动作分母/合法/语义匹配/各 fallback 原因、
  恢复失败、`truncated_combats`/`turn_limit_end`/`stopped_reason`、rank/top4/win、turn/decision 分布、
  adv std/returns/value 误差/explained variance/KL/clip/entropy、吞吐/RSS/IO；
- **硬门**：帧 `state.turn == frame.turn`；动作前后哈希可复现；CPU 多 seed 恢复不变量与终局一致率 100%；
  零结构错误/非法/guard 异常；真实脚本覆盖 ≥80% 且因非法 fallback ≤5%（研究门槛）；
  冻结评测对历史强对手显著优于 B，而完整新局对照 mean rank 退化 ≤0.10 / top4 下降 ≤2pp（95% CI）；
  任一硬门失败立即 `p=0`；连续两次评测退化 → 回到混入前 ckpt/manifest（不只是关开关）。

## 4. 路线判断

评审认为：**路线可行，但应定位为「中局课程 / 历史状态 + 混合脚本」，不是真实历史强策略**；
真正的「强对手自对弈」需要后期把整座位的决策换成冻结的对手模型联赛/分裂模型，
并配历史混合与防遗忘。

## 5. 当前状态

- 正式训练：`trajectory_p=0`（默认）、v1 已禁用，**训练行为不受影响**；
- 轨迹库代码与测试就绪，等待按 §3 协议做隔离研究后才能混入。
