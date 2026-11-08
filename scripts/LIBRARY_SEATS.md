# Library seats（镜像对手库）：原型与限制

> 目标：复现 AutoTavern 论文的「对手 = 7 个 library seat」结构；我们没有真人统计，先用
> **我们自己对局里冠军座位的牌面**做引导库（用户方案：镜像冠军对手的当前回合）。
> 状态：**采集 / 分档 / 抽样 / 注入 已实现并测试；尚未接进 collect（等 stage-1 结果）**。

## 1. 已实现

| 组件 | 位置 | 说明 |
|---|---|---|
| 牌面采集 | `hsbg/az/library.py::capture_turn` | 每回合「招募结束」抓一次，记 turn/seat/hero/tier/health/board（card/atk/hp/golden/keywords）/hand 张数/最终 placement |
| 库与抽样 | `BoardLibrary` | 按 `(turn, 强度档)` 索引；`sample(turn, rng, target_strength)` 按目标强度取，缺档时放宽相邻回合/强度；gzip-jsonl 存取；`filter_champions((1,))` 只留冠军 |
| 注入 | `inject_board` | `clear_zone` → 逐张 `add_minion` → `edit_minion`（atk/hp/golden/keywords）+ `set_player`(health/tier) |
| 采集脚本 | `scripts/build_bot_library.py` | 纯引擎 bot 对局建库（不需要 GPU）：10 局 0.6 s → 907 条 entry、其中冠军 143 条 |

实测规模（10 局的 bot 库）：每回合约 80 条（8 座），强度 p50=58 / p90=374；冠军库 p50=92 / p90=980。
按 1 万局外推 ≈ 90 万条、几百 MB（gzip），构建时间约 10 min。

## 2. 已知限制（必须先解决才能用于训练）

1. **注入的卡牌 id 保真度不足**：`add_minion(card, golden=…)` 会把 golden/token 变体重新规范化
   （实测一条 6 随从的牌面只有 2/6 的卡 id 与采集时一致：如 `BG36_344_G → BG36_343_G`、
   `BG34_170t → BG34_170_G`）。**张数、攻击、血量、关键词是精确的**，被改写的是卡 id。
   - 正确修法：给引擎加 `set_player_state` / `set_minion_state` 调试命令，直接吃 `state_json`
     的 minion 结构（含 eid/attached/pbonus/counter 等），做到逐字段还原；
   - 在修好之前，库可用于「牌面强度分布」类实验，但不适合当作严格对手复现。
2. **只还原牌面**：手牌内容、酒馆、任务、饰品、技能计数未还原（论文的 entry 含手牌与隐藏计数）。
3. **强度档**：现在用 `sum(atk+hp)`；论文是按回合的强度曲线（来自人类统计），我们只能用 bot/自我
   对局的分位数近似。
4. **自指风险**：库最终来自我们自己的对局，强度上限受自身策略限制；需要混入 bot 库、并为
   exam 库单独来源（论文的 "twins" 做法）。

## 3. 接入 collect 的下一步（stage-2）

1. 引擎加 `set_player_state`（Rust，`debug.rs`），注入改用完整 minion 结构 → 保真度修好；
2. `CollectConfig.opponent="library"`：每回合开始时为 7 个对手座位 `sample()` 并注入，然后
   对手直接 `EndTurn`（不跑 `bot_play` 招募）；
3. 训练库/exam 库分离；先做「bot 库 vs 现 7-bot」同预算消融，复现论文 Table 3 的方向；
4. 冠军库随 stage 更新（每 stage 用上一阶段冠军对局重建），并保留历史库做梯度难度。
