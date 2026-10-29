# Firestone 回放 → BC 样本可行性评估

> 数据：Firestone 回放 1000 局（HSReplay XML，客户端视角）
> 目标：判断能否把回放解析成 `hsbg/env/action_space_std.py`（245+29）可用的行为克隆样本
> 结论：**可以，但只对“招募阶段的可观测决策”成立**。1000 局全部解析，得到 **308,944** 个样本，
> 其中 **288,198（93.3%）** 在“卡表 + 动作槽位 + 基础状态”三项上同时可用；
> 上限约 **30.7 万（99.4%）**（补齐三连选项与手牌位后）。

产物：

| 文件 | 说明 |
|---|---|
| `data/firestone_bc/bc_samples.jsonl.gz` | 308,944 个决策样本（gzip JSONL，12.1 MB） |
| `data/firestone_bc/bc_parse_stats.json` | 解析统计 + 卡表/动作映射覆盖率 |
| `data/firestone_bc/SCHEMA.md` | 样本字段与语义说明 |
| `scripts/firestone_bc_parse.py` | 解析器（Python 标准库，12 进程约 4 分钟/1000 局） |
| `docs/BC_DATA_FEASIBILITY.md` | 本文 |

---

## 1. 数据来源与结构

- 本机分卷压缩包 `firestone-full-replays.7z.001…005`，4.9 GB，solid + 7zAES；
  解压后 18.0 GB（5126 文件）。**原始 `replay.xml`（约 11–13 MB/局）未上传**。
- 目录结构：`firestone-full-replays/players/player_<hash>/<game-uuid>/`，每局 4 个文件：
  - `events.jsonl.gz`：**解析主输入**，约 3.3–3.8 MB（压缩），单局约 43.9 万行；
  - `metadata.json`：约 12 KB，玩家/英雄/MMR/对局信息；
  - `replay.xml`、`replay.xml.zip`：完整 HSReplay XML（18 GB），本任务不使用。
- `metadata.json` 关键字段：
  - `reviewId`、`playerFolder`、`recordingPlayer{name, isMainPlayer}`；
  - `game{buildNumber, gameSeed, gameType, formatType}`；
  - `indexEntry{playerCardId(英雄), playerRank(MMR), bgsAvailableTribes, gameDurationTurns, finalComp, postMatchStats.boardHistory}`；
  - `eventRecords`（单局事件数）、`xmlElementCounts`（XML 元素计数）、`sha256` 等。
  - **没有最终名次字段**；只有 MMR、最终阵容（`finalComp`）和每回合棋盘快照（`boardHistory`）。

## 2. events 里到底有什么（schema 结论）

`events.jsonl.gz` **不是**“动作日志”，而是 HSReplay XML 的扁平元素流：每行一个 XML 元素的
`start`/`end` 记录，字段固定为 `seq / event / type / attributes`。单局 21 类元素、43.9 万条：

| 元素 | 单局量级 | 作用 |
|---|---|---|
| `TagChange` | 19.3 万 | 实体标签变化（zone/controller/资源/等级/站位…） |
| `Tag` | 14.9 万 | 实体创建时的初始标签（在 `FullEntity` 内） |
| `Target` / `Option` / `SubOption` | 4.1 万 / 2.1 万 / 1 千 | 目标与选项 |
| `Block` | 9,406 | **动作/效果块**（`type` ∈ 1 ATTACK, 3 POWER, 5 TRIGGER, 6 DEATHS, 7 PLAY, 12 MOVE_MINION） |
| `FullEntity` / `ShowEntity` / `HideEntity` | 7,906 / 4,280 / 3,814 | 实体创建/展示/隐藏 |
| `Choices` / `Choice` / `ChosenEntities` | 40 / 166 / 40 | 发现/三连选择 |
| `Player` / `Game` / `GameEntity` | 2 / 2 / 2 | 玩家与全局实体 |

**决策动作是可识别的**，编码在 `Block type=7 (PLAY)` 的 `entity` 卡牌上：

| `entity` 卡牌 | 动作 | 单局约 |
|---|---|---|
| `TB_BaconShop_DragBuy` | 买入随从（`target` = 商店实体） | 23 |
| `TB_BaconShop_DragBuy_Spell` | 买入酒馆法术 | 11 |
| `TB_BaconShop_DragSell` | 出售随从（`target` = 棋盘实体） | 39 |
| `TB_BaconShop_8p_Reroll_Button` | 刷新酒馆 | 26 |
| `TB_BaconShopTechUp0N_Button` | 升级酒馆 | 5 |
| `TB_BaconShopLockAll_Button` | 冻结/锁定（toggle） | 7 |
| `TB_BaconShop_HP_*` / `kind=hero_power` | 英雄技能 | 6 |
| 普通随从/法术卡 | 从手牌打出 | 50+ |
| `BG36_Button_DarkGift` | 黑暗赠礼 | 3 |
| `TB_BaconShop_Triples_01` | 三连奖励选择 | 5 |
| `Block type=12` | 棋盘换位 | 5–10 |

**决策时刻的可观测状态**（均为 main player / 其英雄）：

| 状态 | 来源 |
|---|---|
| 金币 | 玩家实体 `TAG_RESOURCES=26` |
| 酒馆等级 | 玩家实体 `TAG_TECH_LEVEL=1377` |
| 生命/护甲 | 英雄实体 `HEALTH=45`、`DAMAGE=44`、`ARMOR=292` |
| 手牌 | `ZONE=3` + `CONTROLLER=main` + 卡表 kind ∈ {minion, spell, tavern_spell} |
| 棋盘 | `ZONE=1` + `CONTROLLER=main` + kind=minion |
| 酒馆 | **Bob（`TB_BaconShopBob*`）控制的 `ZONE=1/6` 卡牌**，按 `ZONE_POSITION` 取槽位 |
| 回合 | 玩家实体 `TAG_TURN=20` |

关键事实：**对手不可观测**。回放只有 2 个 `Player` 元素（记录者 + 酒馆/对手占位），
对手手牌、金币、酒馆全程不可见；只有战斗阶段通过 `ShowEntity` 暴露对手场面。
`metadata.json` 的 `postMatchStats.boardHistory` 可提供每回合结束时的己方棋盘（含 tag 快照），
可作为弱监督/校验，但不能替代动作时刻状态。

## 3. 解析方法

`scripts/firestone_bc_parse.py`（仅标准库）：

1. 单遍流式读取 `events.jsonl.gz`，维护实体表（card / tags / 最近更新 seq）与 zone 倒排索引；
2. `Block` 入栈/出栈，识别 `PLAY` 与 `MOVE_MINION`；动作状态在 **block start 时刻快照**
   （买入动作已验证：此时目标仍在商店中）；
3. 商店重建：按 `ZONE_POSITION` 分组，每个槽位取“最近更新”的实体（`zone=1` 可见优先），
   最多 8 槽（7 随从 + 1 酒馆法术）；买入目标命中率 **99.3%（随从）/ 96.3%（法术）**；
4. 回合切换（`TAG_TURN` 增加）额外产出一个 `end_turn` 样本（动作 0）；
5. 映射：`action_type + slot → action_space_std 下标`；卡 id 保留原始字符串，映射时允许 `_G` 归一化；
6. 多进程（`multiprocessing.Pool`，12 worker），1000 局约 **4 分钟**、峰值内存 < 1 GB。

单局样本重建的正确性证据：
- 买入目标在商店快照中：99.3% / 96.3%；
- 卖出目标在棋盘快照中：98.5%；
- 打出的法术在手牌快照中：99.98%；
- 打出的随从在手牌快照中：87.4%（其余为“已自动上场/召唤”，无手牌位）。

## 4. 样本统计

- 1000 局全部解析成功（0 失败），**308,944 样本**；每局 47–1078，均值 308.9。
- 时间跨度/MMR：MMR 4,009–15,407（中位 6,280），206 个不同英雄。
- 回合分布（样本数）：

| 回合 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 样本 | 3,852 | 2,962 | 6,674 | 7,224 | 8,543 | 12,714 | 17,270 | 27,038 | 37,126 | 38,143 | 38,592 | 36,914 | 35,655 | 22,421 | 9,815 | 3,547 |

- 动作分布（括号为可映射数）：

| action_type | 样本 | 可映射 | 映射 |
|---|---:|---:|---|
| play_minion | 76,584 | 63,423 (82.8%) | `46+hand*8+pos` |
| play_spell | 57,337 | 57,322 (99.97%) | `46+hand*8+pos`（pos=0） |
| sell | 51,357 | 51,357 (100%) | `16+slot` |
| reroll | 40,707 | 40,707 (100%) | `1` |
| buy_minion | 24,035 | 24,035 (100%) | `8+slot` |
| buy_spell | 13,709 | 13,709 (100%) | `8+7` |
| end_turn | 12,159 | 12,159 (100%) | `0` |
| reposition | 11,655 | 11,655 (100%) | `196+from*7+to` |
| triple | 5,734 | 0 (0%) | `30+option`（选项未知） |
| hero_power | 5,317 | 5,317 (100%) | `4+0` |
| upgrade | 4,819 | 4,819 (100%) | `3` |
| dark_gift | 2,862 | 2,862 (100%) | `6`（礼物卡未知） |
| freeze | 2,669 | 2,669 (100%) | `2` |

- 状态覆盖：
  - 商店快照非空 **97.78%**（全样本；仅看 6 类商店相关动作均 ≥99.85%）；
  - 商店规模（6 类商店相关动作，共 263,729 样本）：8 张 79,744、7 张 74,453、
    6 张 49,428、5 张 29,588、≤4 张 30,516；
  - `gold/tier/health` 缺失均 **0.15%**；棋盘为空 **0.91%**；手牌为空 **7.28%**。
- 每局样本数受“对局长度 + 操作频率”影响极大（47–1078），做 BC 时建议按局/按回合分层。

## 5. 卡表映射

对照 `rust/crates/hsbg-engine/data/cards.json`（3,983 张，37.0.0.255790）：

- 样本内卡牌提及 **6,012,268** 次（动作卡 + 商店 + 手牌 + 棋盘）；
- 精确命中 **6,009,406（99.95%）**，归一化（去 `_G`）后仍为 99.95%；
- 唯一未命中：`BG36_Button_DarkGift`（UI 按钮，不是游戏卡）；
- 去重后 878 个卡 id，**877 个命中卡表**；即**所有真实游戏卡 100% 可映射**，
  金色变体 `_G` 在卡表中也有独立条目，无需去后缀；
- 卡 id 原样保留（如 `BG31_803`、`BG31_803_G`）。

## 6. 动作空间映射

对照 `hsbg/env/action_space_std.py`（前 245 冻结 + 扩展 29 = 274）：

| 回放动作 | 标准动作 | 索引 | 可映射 |
|---|---|---|---|
| end_turn | EndTurn | 0 | ✅ |
| reroll | Refresh | 1 | ✅ |
| freeze | Freeze（整馆 toggle） | 2 | ✅（toggle 语义有歧义） |
| upgrade | Upgrade | 3 | ✅ |
| hero_power | HeroPower(slot) | 4+slot | ✅（slot 固定 0） |
| dark_gift | DarkGift | 6 | ✅（礼物卡未知） |
| buy_minion | Buy(shop 0..7) | 8+slot | ✅ |
| buy_spell | Buy(spell slot 7) | 8+7 | ✅ |
| sell | Sell(board 0..6) | 16+slot | ✅ |
| play_minion/spell | Play{hand 0..9, pos 0..7} | 46+hand*8+pos | ✅（随从 82.8%） |
| reposition | Move{from,to} | 196+from*7+to | ✅（噪声较大） |
| triple | Choose(option 0..15) | 30+option | ❌ 选项 id 未解析 |
| — (未提取) | Activate(board) | 23+slot | ❌ 回放无单独标记 |
| — | Magnetize | 126+… | ❌ BG 无磁力 |

**动作可映射 290,034 / 308,944 = 93.88%**；不可映射的 18,910 中有 5,734 是三连选择、
13,161 是“打出手牌位缺失”的随从（但动作本身仍可识别，只是槽位缺失）。

## 7. 可做 BC 的样本上限

按“卡表命中 × 动作槽位合法 × 基础状态齐全（gold/tier/health + 对应商店/棋盘非空）”：

| 口径 | 样本数 | 占比 |
|---|---:|---:|
| 全部样本 | 308,944 | 100% |
| 动作可映射 | 290,034 | 93.88% |
| 卡表 + 动作 | 290,034 | 93.88% |
| **严格可用（推荐上限）** | **288,198** | **93.28%** |

补齐两个缺口后可到 **约 30.7 万（99.4%）**：

1. 解析 `Choices/Choice/ChosenEntities` 得到三连奖励 option → `Choose(option)`：+5,734；
2. 通过“上一步手牌快照”恢复打出随从的 hand slot：+13,161。

对 BC 的含义：约 **29 万条 (s, a)** transition，按 8 卡手牌/8 槽动作的离散策略头足够；
建议按动作类型做类平衡（`play_minion` 占 24.8%，`freeze` 仅 0.86%），并按 MMR 分层（4k–15k）。

## 8. 已知局限与标签噪声

1. **客户端事件 ≠ 引擎状态**：回放是客户端 XML，不是 `hsbg_engine` 的 `state_json`；
   实体 id、tag 语义、触发顺序与引擎不完全一致，不能逐位回放。
2. **对手不可观测**：对手手牌/金币/酒馆/英雄技能全程隐藏，BC 只能学“单边策略”，
   不适合直接做完整信息博弈的监督。
3. **无商店 RNG 种子**：`gameSeed` 只有对局种子，没有酒馆刷新序列；同一商店无法在引擎复现，
   因此这些样本更适合做“策略先验/辅助正则”，而不是精确的 world model 数据。
4. **实体 id 复用**：战斗阶段会 `ShowEntity` 复制实体并复用 id，跨帧不可作主键；
   本解析只采信招募阶段的动作块。
5. **商店重建是启发式**：Bob 控制的 zone 1/6 卡 + 按槽位取最近更新；买入目标命中 99.3%/96.3%，
   仍有约 1–4% 的槽位/卡牌错位；8 槽含 1 个酒馆法术槽。
6. **手牌位缺失**：17.2% 的 `play_minion` 在 block start 时卡已不在手牌（自动上场/召唤），
   hand slot 无法恢复。
7. **换位噪声**：`MOVE_MINION` 既包含玩家拖拽，也包含卡牌效果移动；本版本只保留
   “同一实体 from≠to 且 controller=main”，仍可能混入效果移动（11,655 条，建议降权）。
8. **三连/黑暗赠礼**：`triple` 的 option、`dark_gift` 的礼物卡都未解析；
   `triple` 完全不可映射，`dark_gift` 只能映射到动作 6。
9. **冻结是 toggle**：回放只看到“锁定按钮被按下”，无法区分冻结/解冻；
   动作空间里 `Freeze(2)` 与 `Unfreeze(245)` 的标签会互相污染。
10. **自动/触发动作混入**：`BGS_Treasures_*`、`BG20_GEM` 等“打出”可能是奖励/衍生自动施放，
    不一定是玩家决策；本版本未区分。
11. **回合切换快照**：`end_turn` 在 `TAG_TURN` 增加时取状态，此时商店已被清空；
    若要更好的 end_turn 状态，应缓存“上一个非空商店快照”。
12. **无名次**：`metadata.json` 没有 placement；只有 MMR 与最终阵容，无法按名次加权。
13. **英雄皮肤 id**：`hero` 字段是皮肤 id（如 `TB_BaconShop_HERO_93_SKIN_D`），
    需要卡表/英雄表归一化到基础英雄。

## 9. BC 辅助正则：建议纳入的动作与权重

**第一优先级（标签干净、状态完整）**

| 动作 | 样本 | 建议 |
|---|---:|---|
| sell | 51,357 | 权重 1.0；棋盘槽位可靠（98.5%） |
| reroll | 40,707 | 权重 1.0；商店快照可靠（99.85%） |
| buy_minion | 24,035 | 权重 1.0；槽位可靠（99.3%） |
| buy_spell | 13,709 | 权重 1.0（槽位固定 7） |
| play_spell | 57,337 | 权重 1.0（手牌位 99.98%，pos 固定 0） |
| play_minion | 63,423 | 权重 0.8（17% 手牌位缺失，建议只保留 hand slot 存在的） |
| upgrade / hero_power / end_turn | 4,819 / 5,317 / 12,159 | 权重 0.5–1.0；end_turn 建议用缓存商店 |

**第二优先级（有噪声，建议低权重或先清洗）**

| 动作 | 样本 | 噪声 |
|---|---:|---|
| reposition | 11,655 | 效果移动混入；建议只保留“同一实体、from≠to、且前后 1 秒内无其它动作”的子集 |
| dark_gift | 2,862 | 礼物卡未知；只能监督“按下按钮” |
| freeze | 2,669 | toggle 语义不明；可只监督“是否点击”，不区分冻结/解冻 |
| triple | 5,734 | option 未知；建议先解析 `Choices` 再纳入 |

**不建议直接纳入**：`Activate`（未提取）、`Magnetize`（BG 无）、对手动作（不可见）。

### 标签噪声在哪里

- **状态侧**：商店槽位（1–4% 错位）、手牌位（17% 缺失）、end_turn 商店为空、9 槽溢出已修；
- **动作侧**：freeze toggle、triple/dark_gift 选项缺失、自动打出的奖励/衍生牌；
- **策略侧**：玩家是 4k–15k MMR 的人类，不是最优策略；同一状态下不同玩家选择不同，
  这是 BC 的“人类噪声”，不是解析错误；
- **分布侧**：`play_minion` 占 24.8%，`freeze` 占 0.86%，直接训练会被高频动作支配。

### 建议的训练用法（不训练，仅建议）

1. 先用 `action_type + slot` 做离散 BC（29 万条，单卡 3090 级别即可 1–2 epoch）；
2. 动作类型做 class-balanced sampling，MMR ≥ 6,000 的局权重 ×1.5；
3. 把回放样本当 **auxiliary regularizer**（辅助 CE/KL），与自对弈/引擎数据混采，
   而不是唯一数据源；
4. 用 `metadata.postMatchStats.boardHistory` 做回合级一致性校验（棋盘卡 id 集合）；
5. 对 `buy/sell/play` 额外监督“槽位选择”，对 `reroll/upgrade/freeze` 只监督动作类型。

## 10. 复现

```bash
# 1) 解压（密码以数据分享页为准；本次实测为 hidrse）
7z x firestone-full-replays.7z.001 -phidrse -o<tmp> \
  "firestone-full-replays/players/*/*/events.jsonl.gz" \
  "firestone-full-replays/players/*/*/metadata.json"

# 2) 解析
python scripts/firestone_bc_parse.py \
  --root <tmp>/firestone-full-replays/players \
  --cards rust/crates/hsbg-engine/data/cards.json \
  --out data/firestone_bc/bc_samples.jsonl.gz \
  --stats data/firestone_bc/bc_parse_stats.json \
  --workers 12
```

- 环境：Python 3.13（仅标准库），Windows 本机；1000 局约 4 分钟，输出 12.1 MB；
- 未上传任何 `replay.xml`（原始 18 GB）。

## 11. 结论

- **schema 结论**：events 是 HSReplay XML 的元素流，决策动作由 `Block type=7/12` 的
  `entity` 卡牌显式编码；金币/等级/血量/手牌/棋盘/商店均可从 tag + zone 重建；
  对手不可见，商店无 RNG 种子。
- **样本**：1000 局、308,944 条；严格可用 288,198 条（93.3%）。
- **卡表**：真实游戏卡 100% 命中（6.0M 次提及，唯一未命中是 UI 按钮）。
- **动作**：93.88% 可映射到 245/274；缺口是三连选项与 17% 的打出随从手牌位。
- **BC 上限**：约 29 万条可用 transition；补齐缺口后约 30.7 万。
- **建议**：优先 buy/sell/play/reroll；freeze/dark_gift 低权重；reposition/triple 先清洗；
  作为 auxiliary regularizer 与引擎/自对弈数据混用，而不是唯一数据源。
