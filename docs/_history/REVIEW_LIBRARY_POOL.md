# PPAI GPT-6 Astra 终审：镜像对手库（2026-10-28）

> 评审模型 `ppai/gpt-6-astra`（只读，未占 GPU）。快照 `4284a2b`。**结论：不通过 —— 暂不允许混入正式训练**；
> 本轮据此修复了可修部分（见 §3），仍未闭环（§4），因此混入保持关闭（`--library-p 0` 默认）。

## 1. 评审结论（原文要点）

1. **Rust 注入不碰全局 pool 计数**：`Player` 含 shop/hand/board，注入后买卖/刷新按 game.pool 记账，
   可能重复卡 / 负计数 / 破坏经济；另覆盖 `alive/placement/ended_turn/actions_this_turn/pending/
   recent/next_opponent/last_board/scouted` 等跨局与调度字段。
2. **Python 注入层**：异常静默；签名不匹配时已覆盖却只 `pass` 不恢复；只回读 board signature，
   验证不到 hand/shop/quests/hero；meta 只统计成功次数，没有 attempt/failure。
3. **时机**：注入在外层 `g.turn` 变化时做一次，而内层 `bot_play` 可能跨 turn，**不是严格回合起点**。
4. **缓存**：worker 按路径永久缓存，滚动追加 JSONL 后不热加载。
5. **采集来源**：`capture_library.py` 的 checkpoint 只驱动 learner 座位，7 个对手仍是引擎 bot ⇒
   「用当前权重采集对手」的说法不成立（采到的是**打败了我们的 bot 牌面**）。
6. **质量门**：只用最终 placement≤2 + board≥4 + Σ(atk+hp)，未按 turn/英雄/阵容归一，可能把偶然样本固化。
7. **采样**：±1 桶 + top8 随机 ≠ 文档说的「最强」；signature 只含 board 且顺序敏感。
8. 浮点 `library_p` 无 [0,1] 校验；失败静默降级掩盖坏库。

## 2. 评审给出的处置

> 「不允许正式训练；最多隔离 CPU / A-B 前置修复。」

## 2b. 措辞校正（评审第二轮）

- 「pool 不重算」是**代码确定事实**（守恒关系无人维护），但**负计数/崩溃未被运行证实**；
  `next_eid`/eid 冲突同属风险，需 CPU 验证，不写成「必然」。
- 采集来源：当前 checkpoint **只驱动 learner**，7 个对手仍是引擎 bot ⇒ 采到的是「当前 learner
  对局里打败它的 bot 牌面」（条件选择偏差），不是 learner 策略，也不是历史 policy。
- 单测现状：`tests/test_library_pool.py` 只有 4 个 **Python 假 player** 用例（质量门/去重/
  ±1 桶/JSONL），**缺**真实 Rust 注入、不变量、跨 turn、死亡座位、故障回退、热更新集成用例。
- 体积：完整 Player JSON（含 shop/hand/quests/effects/scouted）单条 p50/p95 需实测；按
  14,336 条（512 局×4 turn×7 席）、5–20 KB/条估算约 **72–286 MB**，且每个 worker 各持一份
  → 建议 zstd 分片 + 按 turn/世代分片，避免单 JSONL 全量入内存。

## 2c. M5（滚动更新）已补

- `capture_library.py` 默认**载入已有库再追加**（`--fresh 1` 才覆盖），`--created-iter` 用训练
  iteration 而非游戏序号；
- `LibraryPool.sample` 实现**世代衰减**（`generation_decay` 默认 1%/代，越旧等效强度越低）。

## 2d. 混入判据（评审给定，写入协议）

- 固定同一 commit/checkpoint/card db/seed/游戏数/worker，`--lockstep 1`；
- **p=0 基线 vs p=0.1/0.3/0.5**，各 ≥3 seeds、≥1k 局或足够 CI；先短跑 10–20 iter 再长跑；
- 记录：mean rank/top4/placement 分布、learner win、对手伤害、回合长度、legal/illegal、
  truncated/forced、library attempt/success/fail/mismatch、吞吐、approx_kl/clipfrac/entropy/
  value loss/adv std/return、各 turn 的库覆盖与强度 p50/p90；
- **允许条件**：注入成功率≈attempt 且失败 <1e-3、0 异常/非法/复活/跨卡表、legal 不劣于基线
  （CI）、truncated/forced 不升、吞吐影响 <5%、KL/entropy/adv 方差无持续恶化、held-out 固定
  评测 top4/mean rank 显著或不劣；
- **回退条件**：引擎 panic/不变量破坏/illegal 显著/性能 >5%/KL 或 entropy 越界/收益不显著 → p=0；
- **p 建议从 0.1 起**；不要按 7 席独立 p=0.3（至少一次注入概率 ≈0.92，扰动过强），
  建议 game-level 或每 turn 固定注入数。

## 3. 本轮已修（提交见 git log）

| 评审项 | 修复 |
|---|---|
| 1 alive/簿记字段 | `set_player_from_json(..., preserve_lobby=True)`：`alive/placement/next_opponent/last_opponent/recent_opponents/next_is_ghost/sees_all_boards/scouted/ended_turn/actions_this_turn/skipping` 一律用**当前局**的值，杜绝「复活已淘汰座位」 |
| 2 静默/不恢复/指标 | 注入前保存 `player_json`；校验 `board/hand/tier/health/gold/trinkets/quests/hero` 全等，不等则**整体回滚**；异常计数；meta 增加 `library_attempt/injected/mismatch/error/library_p` |
| 3 时机 | 注入点移到「该 bot 座位**本回合第一次行动之前**」，按 `(seat, turn)` 去重 |
| 4 缓存 | 按 `mtime` 热加载；库为空/路径无效时显式告警并退回纯 bot |
| 6 质量门 | `capture_library.py` 新增 `--min-learner-placement`（只收 learner 名次 ≥N、即「赢了我们」的对局） |
| 7 采样 | 桶内直接取**最强**（去掉 top8 随机） |
| 8 p 值 | 采集入口 `clamp(0,1)`；非 lockstep 路径显式告警「库只在 --lockstep 1 生效」 |

冒烟（CPU tiny，6 局，p=1.0）：`attempt=697 / injected=294 / mismatch=0 / error=0 / illegal=0`。

## 4. 仍未闭环（**因此不混入正式训练**）

1. **全局 pool 计数**：注入不重算 `game.pool`，可能出现「同卡超过池上限」。需要引擎侧
   `recount_pool()` 或在注入时按 `pool_copies` 扣减（并加不变量测试）；
2. **采集来源**：要真做到「模型 vs 模型」，必须让 7 个对手座位也由某 checkpoint 驱动
   （自对弈采集），当前只驱动 learner；
3. **质量门强度归一**：需要按 turn/英雄/阵容归一后再比较，且加「随机对照」防止偶然样本固化；
4. **signature** 应包含 hand/trinkets/hero，且对 board 顺序不敏感；
5. 需要一次**隔离 A/B**（p=0 vs p=0.3）证明：合法率不降、C0 不降、entropy/KL 不变差、吞吐影响 <5%。

## 5. 结论

镜像库实现完成度：**M1–M4 代码就绪、测试通过，但按终审不能混入正式训练**。
下一步（按优先级）：① 引擎 `recount_pool` + 不变量测试 → ② 自对弈采集（模型驱动 7 席） →
③ 隔离 A/B → ④ 再送终审；全部通过后才打开 `--library-p`。


## 6. 「越来越强」目前不成立（评审结论）

- top-2 是**幸存者选择**（selection bias），且当前局 bot 不是 checkpoint 策略；
- 强度 Σ(atk+hp) 未按 turn/英雄/种族/血量校准；
- 已补的世代衰减/追加只是必要条件，**不构成「库会变强」的证明**；
- 要真正建立「越来越强」：固定旧代保留 + 按世代/时间衰减 + 采集**历史 checkpoint 混合**（避免自举）
  + held-out 上做 Elo/胜率评估。
