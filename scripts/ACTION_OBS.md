# 动作 / 观测契约（AutoTavern 兼容）

## 动作：245（0..244）+ 扩展 29（245..273）

| 索引 | 动作 | 参数 |
|---|---|---|
| 0 / 1 / 2 / 3 | EndTurn / Refresh / Freeze / Upgrade | — |
| 4–5 | HeroPower | slot 0–1 |
| 6 / 7 | DarkGift / Cancel | — |
| 8–15 | Buy | 酒馆槽 0–7 |
| 16–22 | Sell | 棋盘槽 0–6 |
| 23–29 | Activate | 棋盘槽 0–6 |
| 30–45 | Choose | 选项 0–15 |
| 46–125 | Play | 手牌 0–9 × 位置 0–7 |
| 126–195 | Magnetize | 手牌 0–9 × 棋盘 0–6 |
| 196–244 | Move | from 0–6 → to 0–6 |
| 245 | Unfreeze | 整馆解冻 |
| 246–249 | HeroPower(2..5) | 预留 |
| 250–265 | Choose(16..31) | 预留 |
| 266–273 | FreezeSlot(0..7) | 按槽位冻结/解冻 |

- 0..244 与 AutoTavern `action_name` **逐位一致**；前 245 永远冻结。
- 扩展段只追加，不插入/重排；`N_TOTAL_ACTIONS=274`。
- 训练/搜索严格只用 245（`hsbg.az`）；扩展段用于环境完整性/未来内容。
- `legal_mask` 精确：mask 允许的动作 `step` 必然接受；非法动作不推进。

## 观测：3227 floats + 124 cards

浮点块（顺序 = 引擎 `obs.rs`）：

| 块 | 宽度 | 内容 |
|---|---:|---|
| global | 53 | 42 标量 + 11 种族位 |
| quests | 6 | 3 任务 × (present, progress/goal) |
| pending_kinds | 9 | 待选类型 one-hot |
| board_minions | 7×31 | 己方战团 |
| hand_items | 10×40 | 手牌 |
| shop_items | 8×40 | 酒馆（含价格） |
| choice_items | 16×40 | 待选项 |
| opponents | 7×9 | 公开对手摘要 |
| opponent_boards | 7×7×31 | 上次见到的对手战团 |
| **合计** | **3227** | |

卡牌块 124 = hero 1 + power 2 + deity 1 + pending_source 1 + quests 9 + secrets 5 + board 7 + hand 10 + shop 8 + choices 16 + trinkets 8 + opp_heroes 7 + opp_boards 49。

- 只含客户端可见信息：己方全状态、对手公开血量/等级/上次战团。
- `layout()` 32 项与 AutoTavern 一致；`decode_blocks` 返回只读块视图。
- 卡牌下标 = `CardId + 1`（0=空）；**跨数据版本不可复用**（需按 card id 重映射）。

## 确定性

- 同 seed + 同动作序列 ⇒ 同轨迹；`state_json` 精确 save/restore。
- 训练/评测固定 seed；自对弈 seed 与评测 seed 分离。
