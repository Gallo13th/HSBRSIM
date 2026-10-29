# Firestone BC 样本 schema

`bc_samples.jsonl.gz`：gzip 压缩的 JSONL，每行一个决策样本（UTF-8，紧凑 JSON）。
由 `scripts/firestone_bc_parse.py` 从 Firestone 回放（HSReplay XML 扁平事件流）生成。

## 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `game_id` | str | 回放 UUID（`metadata.json` 的 `reviewId`） |
| `player_folder` | str | 数据集内的玩家目录 `player_<hash>` |
| `player` | str | 记录玩家名（`recordingPlayer.name`） |
| `hero` | str | 记录玩家英雄卡 id（`indexEntry.playerCardId`，可能是皮肤 id） |
| `mmr` | str/int | 记录玩家 MMR（`indexEntry.playerRank`，字符串原样保留） |
| `turn` | int | 酒馆回合（`TAG_TURN=20`，1..15+） |
| `action_type` | str | 见下表 |
| `card_id` | str/null | 动作涉及的卡牌 id（保留原始字符串，如 `BG31_803`、`BG31_803_G`） |
| `entity_id` / `target_id` | str/null | 客户端实体 id（**跨局/跨阶段不可复用**） |
| `gold` | int/null | 决策时金币（`TAG_RESOURCES=26`） |
| `tier` | int/null | 决策时酒馆等级（`TAG_TECH_LEVEL=1377`） |
| `health` | int/null | 英雄 `TAG_HEALTH=45` |
| `damage` | int/null | 英雄 `TAG_DAMAGE=44`（通常缺失；BG 客户端用 HEALTH 直接扣血） |
| `armor` | int/null | 英雄 `TAG_ARMOR=292` |
| `board_cards` | list[str] | 决策前己方棋盘随从卡 id（按 `ZONE_POSITION` 排序） |
| `hand_cards` | list[str] | 决策前手牌卡 id（按手牌位置排序） |
| `shop_cards` | list[str] | 决策前酒馆卡 id（Bob 控制的 zone 1/6 卡，按槽位排序） |
| `shop_pos` | list[int] | 与 `shop_cards` 对应的 0-based 槽位（0..7） |
| `board_pos` / `hand_pos` | list[int] | 与棋盘/手牌列表对应的 0-based 位置 |
| `shop_slot` | int | 买入动作的槽位（0..7，`shop_pos` 中的下标） |
| `board_slot` | int | 卖出动作的棋盘槽位（0..6） |
| `hand_slot` | int | 打出动作的手牌位置（0..9） |
| `play_pos` | int | 打出动作的落位（0..7；法术固定 0） |
| `from_slot` / `to_slot` | int | 换位动作的起止棋盘位置（0..6） |
| `action_index` | int/null | 映射到 `hsbg/env/action_space_std.py` 的动作下标（null = 不可映射） |
| `ts` / `seq` | str/int | 客户端时间戳与事件序号（调试用） |

## action_type

| 值 | 含义 | 动作空间 |
|---|---|---|
| `end_turn` | 回合切换（结束招募） | `0 EndTurn` |
| `reroll` | 刷新酒馆 | `1 Refresh` |
| `freeze` | 冻结/锁定酒馆（toggle） | `2 Freeze` |
| `upgrade` | 升级酒馆 | `3 Upgrade` |
| `hero_power` | 英雄技能 | `4+slot` |
| `dark_gift` | 黑暗赠礼 | `6 DarkGift` |
| `buy_minion` | 买入酒馆随从 | `8+slot` |
| `buy_spell` | 买入酒馆法术 | `8+7` |
| `sell` | 出售棋盘随从 | `16+slot` |
| `play_minion` | 从手牌打出随从 | `46+hand*8+pos` |
| `play_spell` | 从手牌打出法术 | `46+hand*8+pos` |
| `reposition` | 棋盘换位 | `196+from*7+to` |
| `triple` | 三连奖励选择 | `30+option`（选项未知，`action_index=null`） |

未提取：`Activate`（23..29，回放中没有单独标记）、`Magnetize`（BG 无磁力）。

## 生成

```bash
python scripts/firestone_bc_parse.py \
  --root <解压后的 players 目录> \
  --cards rust/crates/hsbg-engine/data/cards.json \
  --out data/firestone_bc/bc_samples.jsonl.gz \
  --stats data/firestone_bc/bc_parse_stats.json \
  --workers 12
```

要求 Python 3.9+，仅标准库；单局约 2–3 秒（12 进程，1000 局约 4–6 分钟）。

## 已知限制

- 回放是**客户端视角**：对手手牌/金币/酒馆不可见，只有战斗阶段会 `ShowEntity` 对手场面。
- `shop_cards` 由“Bob（酒馆老板）控制的 zone 1/6 卡牌”重建；回放没有槽位 RNG 种子，
  同一商店在引擎里无法逐位复现。
- `entity_id` 在战斗复制/实体复用时会被重写，不能作为跨帧主键。
- 打出的法术没有有意义的棋盘落位，`play_pos` 固定 0。
- 冻结是 toggle，回放只能看到“锁定按钮被按下”，无法区分冻结/解冻语义。
- 三连奖励的选项 id 在 `Choices/Choice` 事件里，本版本未解析，因此 `triple` 不可映射。
