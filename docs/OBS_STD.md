# 标准观测 profile（OBS_STD）：AutoTavern 3227 floats + 124 cards

> 状态：**P2 标准 profile（新增）**；旧 `hsbg.env.spec.Observation`（实体 token
> 动态观测）保留为 **legacy profile**。迁移见 §9/§10。
> 代码：`hsbg/env/obs_std.py`；测试：`tests/test_obs_std.py`（13 项，金标对照
> 上游 `taverngym`）。
> 上游参照：AutoTavern TavernGym 1.0.0 / 游戏数据 36.6.3.253932
> （`crates/taverngym/src/obs.rs` + AutoTavern 仓库 `docs/TAVERNGYM.md`）。
> 实测环境：macOS Apple Silicon / Python 3.12.2 / taverngym 1.0.0

---

## 1. 目标与可比性契约

HSBRSIM 标准观测 profile 直接采用 AT TavernGym 的**固定形状观测**：

* `features`：**3227** 个 `float32`（全局标量 + 己方/酒馆/选择/对手 + 对手
  上次战团）；
* `cards`：**124** 个 `int32`（卡牌 embedding 下标，`0 = 空槽`，
  `cards[i] = CardId + 1`）。

**可比性契约**

1. `hsbg.env.obs_std.layout()` 的 **32 项**（名称 + 数值）与
   `taverngym.layout()` **逐项相等**；
2. `OBS_FLOATS=3227`、`OBS_CARDS=124`、`N_ACTIONS=245` 与上游一致；
3. 各浮点块/卡牌块的**切片偏移与块内字段顺序**与上游 `obs.rs` 的
   `push_*` 顺序一致（本文件 §3–§7 是字段级明细）；
4. **卡牌 id 词表由数据版本决定**：同数据版本（同 `cards.json`）下
   `cards` 下标可逐位互认；跨数据版本必须按卡 id 重映射（§8）。

> 与"与 AT 逐位可比"的严格条件：**同引擎版本 + 同数据版本**。当前
> AT=36.6.3.253932、HSBRSIM 数据=37.0.0.255130 → 浮点块**位置语义**可比，
> 卡牌块**内容**不可直接比较（需数据管线映射）。策略不得直接迁移（重训）。

---

## 2. `layout()` 的 32 项（与上游逐项一致）

```python
from hsbg.env.obs_std import layout
layout()  # (('MINION_F', 31), ('ITEM_F', 40), ('GLOBAL_F', 53), ...)
```

| 项 | 值 | 项 | 值 |
|---|---:|---|---:|
| `MINION_F` | 31 | `A_END` | 0 |
| `ITEM_F` | 40 | `A_REFRESH` | 1 |
| `GLOBAL_F` | 53 | `A_FREEZE` | 2 |
| `N_QUESTS` | 3 | `A_UPGRADE` | 3 |
| `QUEST_F` | 2 | `A_HERO_POWER` | 4 |
| `N_SECRETS` | 5 | `A_DARK_GIFT` | 6 |
| `OPP_F` | 9 | `A_CANCEL` | 7 |
| `N_OPP` | 7 | `A_BUY` | 8 |
| `PENDING_KINDS` | 9 | `A_SELL` | 16 |
| `N_SHOP` | 8 | `A_ACTIVATE` | 23 |
| `N_BOARD` | 7 | `A_CHOOSE` | 30 |
| `N_HAND` | 10 | `A_PLAY` | 46 |
| `N_CHOICE` | 16 | `A_MAGNETIZE` | 126 |
| `N_POS` | 8 | `A_MOVE` | 196 |
| `N_POWERS` | 2 | `N_ACTIONS` | 245 |
| `OBS_FLOATS` | 3227 | `OBS_CARDS` | 124 |

动作段常量由 [`hsbg/env/action_space_std.py`](ACTION_SPACE_STD.md) 提供（同源，
避免两处硬编码漂移）。注意：`N_ACTIONS=245` 指**标准段**（与 AT 逐位一致）；
标准动作 profile 的**总数** `N_TOTAL_ACTIONS=274`（245 标准 + 29 扩展，其中
`FreezeSlot(0..7)`=266..273 为 P2-C OPS-02 新增、按槽位冻结/解冻），扩展段不
影响观测 profile 的 3227/124 布局，详见 [`ACTION_SPACE_STD.md`](ACTION_SPACE_STD.md) §4。

---

## 3. 浮点块总表（`features`，3227）

| 块名（`decode_blocks` key） | 切片 | 形状 | 内容 |
|---|---|---:|---|
| `global` | `[0, 53)` | (53,) | 42 个全局标量 + 11 个 lobby 种族位 |
| `quests` | `[53, 59)` | (3, 2) | 3 个任务槽：`present, progress/goal` |
| `pending_kinds` | `[59, 68)` | (9,) | pending 种类 one-hot |
| `board_minions` | `[68, 285)` | (7, 31) | 己方棋盘随从块 |
| `hand_items` | `[285, 685)` | (10, 40) | 手牌物品块（随从/法术） |
| `shop_items` | `[685, 1005)` | (8, 40) | 酒馆物品块（含当前价格） |
| `choice_items` | `[1005, 1645)` | (16, 40) | 选择选项物品块 |
| `opponents` | `[1645, 1708)` | (7, 9) | 对手公开摘要 |
| `opponent_boards` | `[1708, 3227)` | (7, 7, 31) | 各对手最近一次见到的战团 |

模块导出对应 slice 常量：`SLICE_GLOBAL`、`SLICE_QUESTS`、`SLICE_PENDING`、
`SLICE_BOARD`、`SLICE_HAND`、`SLICE_SHOP`、`SLICE_CHOICES`、`SLICE_OPPONENTS`、
`SLICE_OPP_BOARDS`，以及 `FLOAT_BLOCKS`/`FLOAT_BLOCK_SLICES`/`block_shapes()`。

### 3.1 `global` 42 标量（下标 = `GLOBAL_FIELD_INDEX[name]`）

| # | 字段 | 缩放 | 含义 |
|---:|---|---:|---|
| 0 | `turn` | 20 | 回合（英雄选择阶段 = 0） |
| 1 | `hero_select` | — | 阶段 = 英雄选择 |
| 2 | `game_over` | — | 阶段 = 游戏结束 |
| 3 | `alive` | 8 | 存活人数（`alive_count`） |
| 4 | `me_alive` | — | 本座是否存活 |
| 5 | `health` | 40 | 生命 |
| 6 | `armor` | 20 | 护甲 |
| 7 | `gold` | 10 | 当前金币 |
| 8 | `max_gold_bonus` | 5 | 最大金币加成 |
| 9 | `gold_next_turn` | 5 | 下回合金币 |
| 10 | `tier` | 6 | 酒馆等级 |
| 11 | `upgrade_price` | 10 | 升级费用 |
| 12 | `refresh_price` | 2 | 刷新费用 |
| 13 | `minion_price` | 3 | 随从基础价 |
| 14 | `free_refreshes` | 3 | 免费刷新次数 |
| 15 | `frozen` | — | 酒馆整馆冻结 |
| 16 | `power0_usable` | — | 主技能可用 |
| 17 | `power0_price` | 5 | 主技能费用 |
| 18 | `power0_uses_game` | 5 | 主技能本局使用次数 |
| 19 | `power1_usable` | — | 副技能可用 |
| 20 | `power1_price` | 5 | 副技能费用 |
| 21 | `power1_uses_game` | 5 | 副技能本局使用次数 |
| 22 | `can_dark_gift` | — | 黑暗赠礼可用 |
| 23 | `dark_gift_uses` | 3 | 黑暗赠礼已用次数 |
| 24 | `trinket_count` | 2 | 已获得饰品数 |
| 25 | `deity_atk` | 10 | 神祇攻击（若存在） |
| 26 | `deity_hp` | 10 | 神祇生命 |
| 27 | `won_last` | — | 上场战斗胜 |
| 28 | `lost_last` | — | 上场战斗负 |
| 29 | `spell_atk` | 5 | 法术攻击加成 |
| 30 | `spell_hp` | 5 | 法术生命加成 |
| 31 | `gem_atk` | 5 | 血宝石攻击加成 |
| 32 | `gem_hp` | 5 | 血宝石生命加成 |
| 33 | `board_len` | 7 | 棋盘随从数 |
| 34 | `hand_len` | 10 | 手牌数 |
| 35 | `deity_present` | — | 是否有神祇 |
| 36 | `hand_queue_len` | 5 | 满手待入场队列长度 |
| 37 | `next_is_ghost` | — | 下一场是否幽灵战 |
| 38 | `tavern_atk` | 10 | 酒馆法术攻击加成 |
| 39 | `tavern_hp` | 10 | 酒馆法术生命加成 |
| 40 | `effects_len` | 5 | 持续效果数 |
| 41 | `chronum` | 4 | Timewarp Chronum 余额 |
| 42..52 | `lobby_races` | bit | 11 个种族位（顺序见 §7.4） |

`GLOBAL_FIELD_SCALE` 只列出需要反归一化的字段（`raw = round(float * scale)`）；
布尔/枚举字段不在表中（原值即 0/1 或已经缩放后取整）。

### 3.2 `quests`（3×2）

每个任务槽 `[present, progress/goal]`：`present∈{0,1}`，第二项是
`progress/goal` 的归一化值（0~1）。任务卡 id / 奖励 id 在卡牌块
`card_quests`（§7.2）。

### 3.3 `pending_kinds`（9，one-hot）

顺序（与 `obs.rs` 的 `PENDING_KINDS` 一致，模块常量 `PENDING_KIND_NAMES`）：

```
none, hero, discover, choose_one, target, hero_power, trinket, quest, timewarp
```

### 3.4 `board_minions`（7×31，`MINION_F=31`）

| 偏移 | 字段 | 缩放 | 含义 |
|---:|---|---:|---|
| 0 | `present` | — | 槽位有随从 |
| 1 | `atk` | 10 | 当前攻击 |
| 2 | `hp` | 10 | 当前生命 |
| 3 | `max_hp` | 10 | 最大生命 |
| 4 | `tier` | 6 | 随从等级 |
| 5 | `golden` | — | 金色 |
| 6 | `attached` | 3 | 磁力/附件数量 |
| 7 | `shield_hits` | 3 | 圣盾剩余次数 |
| 8..19 | `keywords` | bit | 12 个关键词位（顺序见 §7.4） |
| 20..30 | `races` | bit | 11 个种族位 |

### 3.5 `hand_items` / `shop_items` / `choice_items`（10/8/16 × 40，`ITEM_F=40`）

物品块 = 9 个头字段 + 内嵌一个 `MINION_F=31` 子块：

| 偏移 | 字段 | 含义 |
|---:|---|---|
| 0 | `present` | 有物品 |
| 1 | `is_minion` | 1=随从 / 0=法术 |
| 2 | `cost` | 价格（缩放 5）：手牌恒 0；酒馆=当前价；选择=选项费用 |
| 3 | `locked` | 手牌锁定 |
| 4 | `temporary` | 临时 |
| 5 | `combined` | Choose One 合并 |
| 6 | `frozen` | 酒馆冻结 / 手牌"本回合打出即死亡" |
| 7 | `kept` | 上回合保留（酒馆） |
| 8 | `marked` | 酒馆票券 / 手牌组标记 |
| 9..39 | 随从子块 | 同 §3.4（法术块布局见下） |

**法术块**（`is_minion=0`）：偏移 9 恒 1.0（`SPELL_PRESENT`），10 = `data/6`
（`SPELL_DATA`），11/12 保留 0，13 = `tier/6`（`SPELL_TIER`），其余 0。

> 与 legacy `hsbg.env.spec.EntityToken` 的差异：这里没有实体 uuid/名称，只有
> 卡牌 embedding 下标（`cards` 块）+ 数值；`cost` 在酒馆里是"当前价格"
> （折扣后），不是卡面费用。

### 3.6 `opponents`（7×9，`OPP_F=9`）

| 偏移 | 字段 | 缩放 | 含义 |
|---:|---|---:|---|
| 0 | `present` | — | 该对手槽存在 |
| 1 | `alive` | — | 存活 |
| 2 | `health` | 40 | 生命 |
| 3 | `armor` | 20 | 护甲 |
| 4 | `tier` | 6 | 酒馆等级 |
| 5 | `seen_board_len` | 7 | 最近见到的战团规模 |
| 6 | `placement` | 8 | 最终名次（0=存活中） |
| 7 | `is_last` | — | 上一场对手 |
| 8 | `is_next` | — | 下一场对手 |

英雄卡在 `card_opp_heroes`；见到的战团在 `opponent_boards`。

### 3.7 `opponent_boards`（7×7×31）

每个对手 × 7 个随从槽 × `MINION_F=31`，内容 = 该玩家**最近一次战斗见到**
的战团（公开信息；不含实时隐藏棋盘）。

---

## 4. 卡牌块总表（`cards`，124）

| 块名（`decode_blocks` key） | 切片 | 形状 | 内容 |
|---|---|---:|---|
| `card_hero` | `[0, 1)` | (1,) | 己方英雄卡 id |
| `card_powers` | `[1, 3)` | (2,) | 英雄技能槽 0/1（0=无） |
| `card_deity` | `[3, 4)` | (1,) | 神祇 |
| `card_pending_source` | `[4, 5)` | (1,) | 触发当前 pending 的卡（发现源/法术/技能） |
| `card_quests` | `[5, 14)` | (3, 3) | 每任务槽 `[quest, reward, owned_reward]` |
| `card_secrets` | `[14, 19)` | (5,) | 已打出奥秘（上限 5） |
| `card_board` | `[19, 26)` | (7,) | 棋盘随从卡 id |
| `card_hand` | `[26, 36)` | (10,) | 手牌卡 id |
| `card_shop` | `[36, 44)` | (8,) | 酒馆卡 id |
| `card_choices` | `[44, 60)` | (16,) | 选择选项卡 id |
| `card_trinkets` | `[60, 68)` | (8,) | 已获得饰品 |
| `card_opp_heroes` | `[68, 75)` | (7,) | 对手英雄卡 id |
| `card_opp_boards` | `[75, 124)` | (7, 7) | 对手最近战团随从卡 id |

卡牌下标含义：`0 = 空槽`；`cards[i] = CardId + 1`（`CardId` 是上游卡表的
稠密下标）。卡 id 字符串/中文名可通过 `taverngym.card_info(idx)` 取得
（上游 API：`(id, enUS name, zhCN name, tier)`）。

---

## 5. 使用方式

```python
from hsbg.env import obs_std

# 上游 Game.observe(seat) 返回原始 bytes（little-endian f32 + i32）
features_bytes, cards_bytes = game.observe(0)

blocks = obs_std.decode_blocks(features_bytes, cards_bytes)
blocks["global"].shape            # (53,)   float32，只读
blocks["board_minions"].shape     # (7, 31)
blocks["card_shop"].shape         # (8,)    int32
blocks["global"][obs_std.GLOBAL_FIELD_INDEX["turn"]] * 20   # 回合数
blocks["pending_kinds"]           # one-hot（顺序见 PENDING_KIND_NAMES）

# 也接受 ndarray / list（float32 / int32 校验）
obs_std.decode_blocks(np.frombuffer(features_bytes, dtype="<f4"),
                      np.frombuffer(cards_bytes, dtype="<i4"))
# copy=True：返回独立只读副本（默认 False = 与输入共享内存的只读视图）
```

**只读语义**：所有返回数组 `writeable=False`（bytes 输入天然只读；
ndarray/list 输入也不会被修改）。需要长期缓存时用 `copy=True`。

**输入约定**：`features` 必须是 exactly 3227 个 f32；`cards` 必须是 exactly
124 个 i32；bytes 输入必须是 4 字节对齐的小端流（= 上游 `observe()` 原样）。
长度/dtype 不符抛 `ValueError`。

**辅助常量**：`GLOBAL_FIELD_NAMES`（42 项）、`GLOBAL_FIELD_INDEX`、
`GLOBAL_FIELD_SCALE`、`MINION_*`/`ITEM_*`/`SPELL_*`/`OPP_*` 偏移、
`RACE_NAMES`/`KEYWORD_NAMES`/`PENDING_KIND_NAMES`、`FLOAT_BLOCKS`/
`CARD_BLOCKS`/`block_shapes()`、`SLICE_*`。

---

## 6. 与 AT 的逐位可比性（验收）

`tests/test_obs_std.py` 的金标断言（13 项，全绿）：

1. `[list(x) for x in layout()] == [list(x) for x in taverngym.layout()]`
   （32/32 项）；
2. `OBS_FLOATS/OBS_CARDS/N_ACTIONS/N_CARDS` 与上游一致；
3. 浮点块/卡牌块切片连续覆盖整个向量、无空洞/重叠，形状与 `FLOAT_BLOCKS`/
   `CARD_BLOCKS` 一致；
4. 块内字段偏移（`MINION_*`/`ITEM_*`/`SPELL_*`/`OPP_*`）与 `obs.rs` 的
   `push_*` 顺序一致；
5. 直接解码上游 `Game.observe(seat)` 的原始 bytes；块形状/dtype 正确；
   `turn`/英雄卡/pending one-hot 等抽样值正确；
6. bytes / ndarray / list 三种输入解码结果一致；非法长度/dtype 抛
   `ValueError`；返回数组只读；
7. 与 `hsbg/backends/taverngym_env.py` 的内部布局推导（`_tg_layout()`）逐项
   一致（浮点块偏移 + 卡牌块偏移）。

复现命令：

```bash
cd /Users/letiangao/HSAgent/HSBRSIM
python3 -m pytest tests/test_obs_std.py -q     # 13 passed（需 taverngym）
python3 -m pytest tests/test_action_space_std.py tests/test_obs_std.py -q
# 本机实测：57 passed（44 + 13，约 1.2s；含 P2-D2 FREEZE_SLOT 增量）
```

---

## 7. 顺序表（bit / one-hot）

### 7.1 关键词位（12，`KEYWORD_NAMES`）

```
TAUNT, DIVINE_SHIELD, WINDFURY, REBORN, VENOMOUS, POISONOUS,
STEALTH, MAGNETIC, MEGA_WINDFURY, CLEAVE, IMMUNE, IMMUNE_ATTACKING
```

### 7.2 种族位（11，`RACE_NAMES`）

```
BEAST, DEMON, DRAGON, ELEMENTAL, MECHANICAL, MURLOC,
PIRATE, QUILBOAR, UNDEAD, ABERRATION, NAGA
```

（注意 AT 的 `MECHANICAL` 对应 `hsbg.env.spec.RACES` 的 `mech`；
`ABERRATION` 不在 legacy spec 标准种族里，转换时映射为 `none` 位。）

### 7.3 pending 种类（9，`PENDING_KIND_NAMES`）

```
none, hero, discover, choose_one, target, hero_power, trinket, quest, timewarp
```

### 7.4 其他

* `quests`：`progress/goal` 归一化值，0~1；
* `card_quests`：每槽 `[quest, reward, owned_reward]` 三个卡牌下标；
* `opponents` 顺序：其他 7 座按"相对座位序"（`(seat + k) % 8`），不是绝对座位号
  （与上游 `obs.rs` 一致）。

---

## 8. 数据版本 / 卡牌词表契约（重要）

1. **布局稳定、词表不稳定**：3227/124 的块布局由**引擎实现**决定（同 taverngym
   版本稳定）；`cards` 下标 → 卡 id 的映射由**数据包**决定；
2. 上游 36.6.3.253932 构建：`N_CARDS=3984`（3983 张卡 + 空位 0；
   `hsbg.env.obs_std.N_CARDS_REFERENCE` 记录该基线，运行时以
   `taverngym.N_CARDS` 为准）；
3. HSBRSIM 数据基线 **37.0.0.255130** 的卡表不同（卡池 273 随从 / 76 酒馆法术
   / 118 英雄 / 409 饰品，见 `data/bg_summary.json`）→ **跨数据版本时
   `cards` 下标不可直接比较/复用**：必须按卡 id 建立映射
   （`cards[i] -> card_id -> 新卡表下标`），映射表由数据管线（37 数据管线任务）
   提供；
4. 因此"与 AT 逐位可比"的严格条件是**同引擎版本 + 同数据版本**；动作/浮点块
   的位置语义可比，卡牌块内容不可比（策略/数据迁移见 §10）。

---

## 9. 迁移指南：旧 Observation profile → 标准观测

旧 checkpoint / 旧 JSONL 一律视为 **legacy**（用户已确认接受重训）。

| 旧（legacy `hsbg.env.spec.Observation`） | 新（std profile） |
|---|---|
| 实体 token：`board/hand/tavern/trinkets/quest/opponent_board/lobby` | 固定块：`board_minions/hand_items/shop_items/...` + `card_*` |
| `HeroToken`（health/armor/tier/gold/...） | `global` 42 标量（§3.1） |
| `EntityToken.keywords/races`（字符串元组） | 关键词/种族 **bit 位**（§7.1/7.2） |
| `pending_choice.options`（实体列表） | `pending_kinds` one-hot + `choice_items` + `card_choices` |
| `extra`（决策状态袋，v2/v3） | 部分标量已进 `global`（frozen/power 可用/任务进度等）；**未覆盖的 extra 字段需另行扩展 profile**（本 profile 与 AT 逐位一致，不擅自加字段） |
| 动态候选（≤64） | 245 维固定动作 + mask（见 [`ACTION_SPACE_STD.md`](ACTION_SPACE_STD.md)） |

**策略/训练侧**：

1. 编码器输入从"实体 token 序列"换成 `features(3227) + cards(124)`
   （MLP/Transformer 两种都可；卡牌 embedding 表大小 `N_CARDS` 随数据版本）；
2. 旧 checkpoint 与新观测不兼容 → legacy，不再用于评测/训练（重训）；
3. 数据采集：新轨迹应直接保存 `features/cards` 原始向量（或按 §5 解码后的
   块），避免再做一次实体 token 序列化；
4. 跨引擎数据：同数据版本下可直接对比/混合；跨数据版本需卡 id 重映射
   （§8），且状态分布不同（不可直接迁移策略）。

---

## 10. 已知限制 / 契约边界

1. **AT 版本固定**：本 profile 对应 taverngym 1.0.0 / 36.6.3.253932 的
   3227/124 布局；上游升版本改观测编码时必须同步本模块 + 文档 + 金标测试
   （`_validate_layout()` 只能拦截本地常量漂移）；
2. **卡牌词表随数据版本**：`N_CARDS_REFERENCE=3984` 只是 36.6.3 基线；
   HSBRSIM 37.0.0 数据需重映射（§8）；
3. **不含隐藏信息**：`opponent_boards` 是"最近一次见到的战团"（公开），
   不是对手实时棋盘；手牌/金币等隐藏量不在观测中（与 AT POMDP 一致）；
4. **不含战斗回放/事件流**：该 profile 是决策点快照；战斗过程/回放属于 AT 的
   `Game.view()` 调试视图（见 `docs/TAVERNGYM_BACKEND.md` §4.2），不在本 profile；
5. **额外决策状态**：legacy `Observation.extra` 的部分键（如 elimination 顺序、
   last_combat、pending_hand_queue 明细）在 AT 固定观测中没有对应槽位——
   需要时作为 profile 扩展另行设计（不得改动 3227/124 前段语义）。
