# 引擎 API 手册（ENGINE_API）

> 适用对象：`hsrl2/` vendored 引擎（S14 / patch **36.2.2** 数据基线，
> `data/` 共 3683 个 CardDef）。读者是 **RL 环境开发者**。
>
> **本文所有代码片段都实际运行过**：`python tools/probe_api.py`
> 覆盖 182 条断言（A1–A9 分组与本文小节一一对应），全部 PASS。
> 性能/内存数字见 `docs/ENGINE_RL_READINESS.md`（由
> `python tools/probe_speed.py --games 20` 生成）。
>
> 约定：代码注释用中文、标识符英文；所有文件 UTF-8。
> 引擎路径统一写 `C:\HSagent`。

---

## 0. 最小可运行对局（先跑起来）

```python
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.tags import CardType

DATA = Path("data")
db = CardDB.load(DATA)                      # 3683 定义，约 60 ms（见 §1.1）

hero_ids = [d.id for d in db._by_id.values()
            if d.card_type == CardType.HERO]          # 116 个英雄
heroes = [Hero(hero_ids[i], f"H{i}") for i in range(8)]

game = Game(heroes, db, seed=42)             # seed 决定全部引擎随机性
game.start_game()                            # 进入第 1 回合（金币/酒馆已备好）

# 开局可能产生 PendingChoice（英雄技能/异变绑定），必须先结算
while game.pending_choices:
    choice = game.pending_choices.pop(0)     # 契约：先 pop 再 choose
    choice.choose(0)

# 一个最简单动作：买第一个随从 → 进手牌（注意：不会自动上场）
hero = game.heroes[0]
minion = next(e for e in hero.tavern if isinstance(e, Minion))
game.buy_from_tavern(hero, minion)
game.play_minion(hero, minion)               # 手牌 → 棋盘

game.end_recruit_phase()                     # 结束全桌招募 → 战斗 → 下一回合
print(game.turn, len(game.heroes), game.finished)
```

### 0.1 本文片段使用的辅助函数

后面很多片段用下面几个小工具（定义同 `tools/probe_api.py`，可直接复制）：

```python
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import CardType, GameTag, Zone


def new_game(db, n=2, seed=42, hero_id_list=None, anomaly=None):
    """建一局并 start_game。"""
    ids = hero_id_list or [d.id for d in db._by_id.values()
                           if d.card_type == CardType.HERO]
    heroes = [Hero(ids[i % len(ids)], f"H{i}") for i in range(n)]
    game = Game(heroes, db, seed=seed, anomaly=anomaly)
    game.start_game()
    return game


def drain(game, pick=0):
    """FIFO 结算全部 PendingChoice（choose 只结算不出队——必须 pop）。"""
    kinds = []
    while game.pending_choices:
        choice = game.pending_choices.pop(0)
        kinds.append(choice.kind)
        choice.choose(min(pick, len(choice.options) - 1))
    return kinds


def make_hand_minion(game, hero, card_id=None, index=0):
    """白盒测试用：直接造一张随从放手牌（不经过买）。"""
    d = game.db.get(card_id) if card_id else game.db.pool_minions()[0]
    m = game.create_minion(d.id, controller=hero)
    hero.hand.append(m)
    m.zone = Zone.HAND
    return m


def summon_minion(game, hero, card_id=None, atk=1, health=20):
    """白盒测试用：直接召唤一只随从到棋盘。"""
    d = game.db.get(card_id) if card_id else game.db.pool_minions()[0]
    m = game.create_minion(d.id, controller=hero)
    m.set(GameTag.BASE_ATK, atk)
    m.set(GameTag.BASE_HEALTH, health)
    m.set(GameTag.HEALTH, health)
    game.summon(hero, m)
    return m
```

> 生产代码不要用 `create_minion + summon` 绕过池/费用——那只是测试/探查
> 手段；环境动作必须走 §3 的公开 API。

---

## 1. 初始化

### 1.1 加载 CardDB

```python
from pathlib import Path
from hsrl2.db import CardDB

db = CardDB.load("data")          # str 或 Path 均可；目录需含 bg_*.json
len(db)                           # 3683（S14/36.2.2；线上 36.6.3 见 AGENTS.md §5）
```

* `CardDB.load` 逐个读取下列文件（不存在则**静默跳过**）：
  `bg_cards.json`、`bg_pool_minions.json`、`bg_pool_spells.json`、
  `bg_heroes.json`、`bg_hero_powers.json`、`bg_trinkets.json`、
  `bg_anomalies.json`、`bg_quest_rewards.json`、`bg_dark_gifts.json`。
* 加载耗时约 **60 ms**，内存约 **12 MB**（`tracemalloc` 实测；见
  READINESS §3）。**每个进程加载一次并复用**——不要在每局 `reset()`
  里重新 load。
* 测试中常用 `DATA_DIR = Path(__file__).resolve().parent.parent / "data"`。

### 1.2 枚举英雄 id

`CardDB` **没有** `heroes()` / `all()` 这类公开迭代器，事实上的用法是
遍历私有的 `db._by_id`（README 级约定；见 READINESS D-8）：

```python
from hsrl2.tags import CardType

hero_defs = [d for d in db._by_id.values() if d.card_type == CardType.HERO]
hero_ids  = [d.id for d in hero_defs]
len(hero_ids)                       # 116

# 每个英雄都有主英雄技能 id（注意：是 card_id 字符串，不是 dbf_id）
with_power = [d.id for d in hero_defs if d.hero_power_id]
len(with_power)                     # 116
db.get(hero_defs[0].hero_power_id).card_type     # CardType.HERO_POWER
```

`tools/smoke_random_games.py` 使用的过滤条件是
`d.id.startswith(("TB_BaconShop_HERO", "BG"))`，但**全量 116 个英雄都满足
`card_type == HERO`**，直接按 card_type 过滤即可（不必按 id 前缀）。

### 1.3 创建 Hero / Game，调用 start_game

```python
from hsrl2.hero import Hero
from hsrl2.game import Game

heroes = [Hero(hero_ids[i], f"H{i}") for i in range(8)]

# 签名: Game(heroes: List[Hero], db: CardDB, *, seed: int|None = None,
#            anomaly: str|None = None)
game = Game(heroes, db, seed=42, anomaly=None)
game.start_game()
```

* `seed=None` → `random.Random(None)`，**不可复现**；训练/评测必须显式给 seed。
* `Game.__init__` 会把每个 `hero.game` 指向本局，并建立
  `game.rng = GameRNG(seed)`、`game.events`、两个池（`minion_pool` /
  `spell_pool`）、`pending_choices=[]`、`turn=0`。
* `Game` 只接受 `Hero` 列表；构造时**不校验** card_id 是否存在 DB。传入
  未知英雄 id 不会报错，但该英雄 `hero_power_def() is None`、没有技能
  （实测：`hero_power_ids == []`、`use_hero_power() is False`）。
  **环境层应从 §1.2 的合法 id 里选英雄**。
* `start_game()` 只应调用一次（重复调用会重跑 on_bind/首回合副作用）。

创建 Hero 的初始值（`probe_api` A1 断言）：

| 字段 | 初始值 | 说明 |
|------|--------|------|
| `health` | 30 | `GameTag.HEALTH2` |
| `armor` | 0 | `GameTag.ARMOR`，先扣护甲再扣血 |
| `gold` | 0 | `start_game` 后才是 3 |
| `tavern_tier` | 1 | |
| `upgrade_cost` | 5 (`BASE_UPGRADE_COSTS[2]`) | |
| `board/hand/tavern/trinkets` | `[]` | |
| `quest` | `None` | |
| `is_alive` | `health + armor > 0` | |

`start_game()` 之后（第 1 回合）：

```python
game.turn                 # 1
[x.gold for x in game.heroes]        # [3, 3, ...] = C.gold_base_income(1)
[len(x.tavern) for x in game.heroes] # [4, ...]  = 3 随从 + 1 酒馆法术
[x.upgrade_cost for x in game.heroes]# [5, ...]
```

### 1.4 start_game 的异常与开局选择

```python
from hsrl2.game import GameStateError

bad = Game([Hero(hero_ids[0], "X")], db, anomaly=hero_ids[0])
try:
    bad.start_game()
except GameStateError as e:
    print("anomaly 必须是 BACON_ANOMALY 卡：", e)
```

* `anomaly` 传错类型（例如把异变授予的**英雄技能** id 当异变）→
  `start_game()` 抛 `GameStateError`（fail-loud，见 `game.py:295-303`）。
* **开局可能挂起选择**：英雄技能 `on_bind` / 异变 / 饰品绑定都可能产生
  `PendingChoice`（例如 `discover_hero_power`）。环境在 `reset()` 里
  **必须** 像 smoke 脚本那样先 FIFO 结算一遍：

```python
while game.pending_choices:
    choice = game.pending_choices.pop(0)     # 契约：pop 后才能 choose
    choice.choose(0)                         # 引擎不会自动替你 pop
```

合法异变列表：

```python
from hsrl2.scripts import REGISTRY
from hsrl2.tags import CardType

anomalies = [k for k in REGISTRY
             if db.get(k) is not None
             and db.get(k).card_type == CardType.BACON_ANOMALY]
len(anomalies)      # 73（REGISTRY 中带脚本的可选异变；data 里共 108 张）
```

---

## 2. 回合流程

### 2.1 状态机与「现在是不是招募阶段」

引擎**没有** `phase` 字段。环境必须自己按下列顺序判定：

```python
def phase_of(game):
    if game.finished:
        return "game_over"
    if game.pending_choices:      # 有选择待结算 → 环境应返回 choice 步
        return "choice"
    return "recruit"

game.turn          # 当前回合，1 起；在 end_recruit_phase 内部 +1
game.in_combat     # 只在 run_combat 执行期间为 True（见 §6.2），
                   # 外部观察不到「战斗阶段」；不要用它判断招募阶段
game.finished      # 存活 ≤1 时由 end_recruit_phase 置 True
```

* `game.in_combat` 实测：招募阶段恒 `False`；`run_combat` 内监听
  `before_attack` 时恒 `True`；`run_combat` 返回后复位 `False`。
* `game.heroes` 是**可变列表**：淘汰时会被原地移除（§6.4），
  环境不要缓存它。

### 2.2 start_game 做了什么

顺序（`game.py:284-322`）：

1. `turn = 1`；
2. 为每个英雄接线主英雄技能 `on_bind`（被动/开局效果，如 Patchwerk 血量、
   The Curator 融合怪）；
3. 应用异变 `on_bind(game)`（可改英雄起始状态，如 10 金/5 甲）；
4. 补接线「第二技能槽」`on_bind`；
5. `_precompute_pairing()`：**开局即确定首回合对手**；
6. 对每个英雄执行 `_begin_recruit_for`（见 §2.3）。

### 2.3 每回合开始 `_begin_recruit_for` 的完整副作用（官方顺序）

`end_recruit_phase()` 在 turn+1 后会对**每个存活英雄**依次执行
（`game.py:324-413`）。这些副作用是「隐式动作」，环境不需要也不应该重复：

| # | 副作用 | 细节 |
|---|--------|------|
| 1 | **金币覆盖式重置** | `hero.gold = min(3+turn-1, income_cap)`；回合内收入不储蓄 |
| 2 | 执行延迟动作 | 上回合 `defer_until_next_turn` 的 Action，在金币重置**之后**结算 |
| 3 | 重置本回合配额 | `spell_first` / `spellcraft_first` / `bc_first` 额外触发额度；清 `GOLD_SPENT_THIS_TURN`、`CARDS_PLAYED_THIS_TURN`、`TAVERN_SPELLS_CAST_THIS_TURN`、`MINIONS_SOLD_THIS_TURN` |
| 4 | **升级费衰减** | `turn>1` 时 `upgrade_cost = max(0, upgrade_cost - 1)`（下限 0） |
| 5 | 重置 Activate | 棋盘随从清 `ACTIVATE_USED_THIS_TURN` |
| 6 | 重置英雄技能 | 清 `HERO_POWER_USED_THIS_TURN`（每技能计数一并清零） |
| 7 | 重置 Dark Gift | `dark_gift_state[hero]["used_this_turn"] = False` |
| 8 | **SoT 钩子** | 饰品 → 任务奖励 → 棋盘随从（左→右）→ 手牌，逐个 `start_of_turn`；随后 fire `turn_start`；Lockbox 倒计时 -1 |
| 9 | Spellcraft 生成 | 棋盘/饰品/任务奖励上带 `SPELLCRAFT` 的实体各生成一张临时法术（满手进等待队列） |
| 10 | 等待队列补发 | `pending_hand_queue` 中属于本英雄的卡若手牌有空位则入手（随从触发三连检查） |
| 11 | **酒馆自动刷新** | `refresh_tavern(auto=True)`：不花金币；冻结内容保留（冻结只保留一轮） |
| 12 | **任务 offer** | 第 4 回合（`C.QUEST_OFFER_TURN`）每英雄一次：3 对 (任务, 奖励) 选一 → `PendingChoice(kind="quest_offer")` |
| 13 | **饰品 offer** | 第 6 回合 lesser / 第 9 回合 greater（`C.TRINKET_OFFER_TURNS`）：4 选 1 + 放弃（None）→ `PendingChoice(kind="trinket_offer")` |

验证片段（A2）：

```python
game = new_game(...)                 # 见 §1
hero = game.heroes[0]
hero.gold = 0
hero.set(GameTag.UPGRADE_COST, 5)
tavern_before = list(hero.tavern)

# 给棋盘随从挂一个 SoT 计数脚本（白盒探针）
calls = {"sot": 0}
class SoTProbe:
    @staticmethod
    def start_of_turn(source, g, ctx=None):
        calls["sot"] += 1
m = summon_minion(...)               # 任意随从召唤到棋盘
m.scripts = SoTProbe

game.end_recruit_phase()             # 推进整桌一个回合
assert game.turn == 2
assert hero.gold == 8                # C.gold_base_income(2)
assert hero.upgrade_cost == 4        # 5 - 1
assert hero.tavern != tavern_before  # 自动刷新
assert calls["sot"] >= 1             # SoT 钩子确实触发
```

### 2.4 关键时点表

| 事件 | 时点 | 常量 | 产生物 |
|------|------|------|--------|
| 金币收入 | 每回合开始 | `gold_base_income = min(3+turn-1, 10)` | — |
| 升级费衰减 | 每回合开始（turn>1） | `-1`，下限 0 | — |
| 酒馆刷新 | 每回合开始 + 手动 | `TAVERN_OFFERS[tier]` 随从 + 1 法术 | — |
| 任务三选一 | 第 4 回合 | `QUEST_OFFER_TURN=4` | `quest_offer` 选择 |
| Lesser 饰品 | 第 6 回合 | `TRINKET_OFFER_TURNS[6]` | `trinket_offer` 选择（5 项含 None） |
| Greater 饰品 | 第 9 回合 | `TRINKET_OFFER_TURNS[9]` | 同上 |
| Dark Gift | 第 3 回合起，每回合最多 1 次、每局 3 次、3 金 | `C.DARK_GIFT_*` | `dark_gift` 选择 |
| 战斗/淘汰 | `end_recruit_phase()` | — | 见 §6 |

> 实测：`pending_choices` 在 `end_recruit_phase` **内部**产生（下回合开始
> 副作用）。所以环境在 ERP 返回后必须先检查/结算选择，再构造观测。

### 2.5 结束招募阶段 → 下一回合

```python
ret = game.end_recruit_phase()   # 返回 None
# 内部顺序：EoT 效果 → 丢弃 Spellcraft → 战前快照 → 配对 → 逐对战斗
#          → 幽灵战 → 淘汰 → (存活≤1 ? finished : turn+1 + 新回合副作用)
```

详见 §6.1。

---

## 3. 动作 API

引擎把动作实现成 `Game` 上的方法（`hsrl2/game.py`）。**返回 `False`
表示「本次操作未发生」**；真正的非法状态才会抛
`hsrl2.game.GameStateError`。两者必须分别处理（§9）。

### 3.0 总表

| API | 返回 | 抛异常 | 扣金币 | 可能产生 PendingChoice |
|-----|------|--------|--------|------------------------|
| `buy_from_tavern(hero, entity)` | bool | 否 | 是（可 0/以生命代付） | 是（入手/战吼等监听） |
| `sell_minion(hero, minion)` | bool | 否（但传 Spell 会 **AttributeError**，§9.3） | 返还 +1 | 是（on_sell/监听） |
| `play_minion(hero, m, position=None, target=None, magnetic_target=None)` | bool | 否 | 否 | 是（battlecry_target / choose_one） |
| `play_spell(hero, spell, target=None)` | bool | 否 | 否（手牌法术免费） | 是（spell_target / choose_one） |
| `refresh_tavern(hero, ...)` | None | **是**（金币不足） | 是（1 金/覆盖价） | 是（刷新监听） |
| `upgrade_tavern(hero)` | bool | 否 | 是 | 是（升级监听） |
| `upgrade_tavern_free(hero)` | None | 否 | 否 | 是 |
| `freeze_tavern(hero)` | None | 否 | 否 | 否 |
| `use_hero_power(hero, target=None, power_id=None)` | bool | 否 | 是（定向技能在选择结算时扣） | 是（hero_power_target 等） |
| `use_activate(hero, minion)` | bool | 否 | 是 | 是（activate_target 等） |
| `use_dark_gift(hero)` | bool | 否 | 是（3 金） | 是（dark_gift） |
| `spend_gold(hero, amount)` | None | **是**（金币不足） | 是 | 否 |

### 3.1 `buy_from_tavern(hero, entity) -> bool`

```python
# 签名: hsrl2/game.py:737
ok = game.buy_from_tavern(hero, entity)
```

* **前置条件**：`entity in hero.tavern`、`not hero.hand_full()`、
  `not hero.get(GameTag.TURN_SKIPPED)`、支付得起（金币 / 免费额度 /
  健康购买）。
* **成功副作用**：从 `hero.tavern` 移除；`hero.add_to_hand(entity)`
  （`zone=HAND`，触发 `on_enter_hand` / `card_gained`）；随从 fire
  `minion_bought` 并做三连检查；若触发自动刷新配置则刷新。
* **失败返回 False 且不改状态**：不在酒馆 / 满手 / 金币不足 /
  `TURN_SKIPPED` / 健康不足。
* **坑 1（最重要）**：**买只进手牌，不会上场**。必须再 `play_minion`。
* **坑 2**：若购入过程中监听器占满手牌，卡会进 `game.pending_hand_queue`
  等待（函数仍返回 True，但卡不在 `hero.hand` 里——见 §9.2）。
* **坑 3**：酒馆法术也走这个 API（`isinstance(entity, Spell)`），买进手牌
  后用 `play_spell` 施放（施放不花钱）。

```python
hero.gold = 10
e = next(x for x in hero.tavern if isinstance(x, Minion))
cost = e.get(GameTag.COST, C.MINION_BUY_COST)      # 3（可被覆盖，见 §4.3）
assert game.buy_from_tavern(hero, e) is True
assert e in hero.hand and e.zone == Zone.HAND
assert len(hero.tavern) == before_tavern - 1
assert hero.gold == 10 - cost

assert game.buy_from_tavern(hero, other_minion_not_in_tavern) is False
assert game.buy_from_tavern(full_hand_hero, any_tavern_entity) is False
assert game.buy_from_tavern(poor_hero, any_tavern_entity) is False
```

### 3.2 `sell_minion(hero, minion) -> bool`

```python
# 签名: hsrl2/game.py:986
ok = game.sell_minion(hero, minion)
```

* **合法对象**：`minion in hero.board` 或 `minion in hero.hand`。
* **成功副作用**：先跑 `on_sell` 钩子；`hero.gold += sell_value`
  （默认 1；实体 `SELL_VALUE` tag / hero 级 `SELL_VALUE_OVERRIDE` 可改写）;
  `MINIONS_SOLD_THIS_TURN += 1`；fire `minion_sold`；移出区域；
  `zone = REMOVED`；按池规则回池（金色 3 份、非三连金 1 份）。
* 不在棋盘/手牌 → 返回 False。
* **坑**：签名写的是 `Minion`，但引擎**不校验类型**。传 `Spell` 会在
  `pools.release_minion_entity` 里 `AttributeError`，而此时金币已 +1、
  手牌已移除（状态被污染）。环境**必须只对 `isinstance(e, Minion)` 生成
  sell 候选**（READINESS D-9）。

```python
hero.gold = 0
m = summon(...);  assert game.sell_minion(hero, m) is True
assert hero.gold == 1 and m not in hero.board and m.zone == Zone.REMOVED

hand_m = ...  # hand 里的随从也能卖
assert game.sell_minion(hero, hand_m) is True

outsider = game.create_minion(db.pool_minions()[0].id, controller=hero)
assert game.sell_minion(hero, outsider) is False
```

### 3.3 `play_minion(hero, minion, position=None, target=None, magnetic_target=None) -> bool`

```python
# 签名: hsrl2/game.py:1015
ok = game.play_minion(hero, minion, position=None, target=None,
                      magnetic_target=None)
```

* **前置条件**：`minion in hero.hand`；`not CardDef.unplayable`；
  `not minion.has(GameTag.LOCKED_IN_HAND)`；`not TURN_SKIPPED`；
  棋盘未满（或有合法磁力吸附目标）。
* **`position`**：插入下标，`None` 或 `> len(board)` → 追加最右；
  合法枚举范围 `0..len(hero.board)`。传负数会走 Python 负索引语义
  （**引擎不报错**，环境不要生成）。
* **成功副作用**：手牌移除 → `summon()`（`zone=PLAY`、回满血、触发
  `summon`/`on_summon`）→ Choose One / 定向战吼分流 → `_run_play_effects`
  （战吼次数、`card_played`/`minion_played`、三连、金色奖励）。
* **失败返回 False**：不在手牌 / unplayable / 锁定 / 棋盘满。
* **定向战吼**（脚本声明 `needs_target=True` + `battlecry`）：
  * `target=None` 且候选非空 → 随从**已上场**，返回 True，同时
    `game.pending_choices` 追加 `PendingChoice(kind="battlecry_target")`；
    选择结算后才跑战吼。
  * `target` 不在 `target_candidates` 中 → 随从仍上场，**战吼落空**，
    返回 True（不报错）。
  * 无候选 → 战吼落空，随从照常上场。
* **Choose One**（脚本声明 `choose_options`）→ 上场后追加
  `PendingChoice(kind="choose_one")`，`options` 是选项 key 字符串。
* **磁力**：`magnetic_target=host` 时走吸附分支——不占板位、不召唤；
  把磁力随从的攻击/生命/关键词并入宿主、亡语栈叠，磁力实体 `zone=REMOVED`。
  宿主必须满足：`host.controller is hero`、存活、`zone == PLAY`、
  `game._magnetic_valid(m, host)`（默认机械，个别卡例外，见 §4.7）。
  吸附失败（目标非法）→ 返回 False，卡留在手牌。

```python
# 普通打出 + 位置
m = make_hand_minion(...)
assert game.play_minion(hero, m, position=0) is True
assert hero.board[0] is m and m.zone == Zone.PLAY

# 棋盘满
while not hero.board_full():
    game.summon(hero, game.create_minion(db.pool_minions()[0].id,
                                         controller=hero))
assert game.play_minion(hero, another_hand_minion) is False

# 定向战吼：挂起选择
ok = game.play_minion(hero, targeted_minion)
assert ok is True and game.pending_choices[0].kind == "battlecry_target"
ch = game.pending_choices.pop(0)
ch.choose(0)                       # 结算战吼

# 磁力吸附
host = summon_mech(...)
mag = hand_magnetic(...)
before = host.atk
assert game.play_minion(hero, mag, magnetic_target=host) is True
assert host.atk == before + mag_def.atk and mag.zone == Zone.REMOVED
```

### 3.4 `play_spell(hero, spell, target=None) -> bool`

```python
# 签名: hsrl2/game.py:1432
ok = game.play_spell(hero, spell, target=None)
```

* **前置条件**：`spell in hero.hand`；`not unplayable`；
  `not LOCKED_IN_HAND`；`not TURN_SKIPPED`。
* **成功副作用**：手牌移除 → fire `spellcraft_cast`（若带 SPELLCRAFT）→
  逐次结算 `on_play`（含双施/额外施放配额）→ `spell_resolving` /
  `spell_resolved` 事件 → 酒馆法术计数与回池 → `card_played`。
  法术 `zone=REMOVED`。
* **施放不花金币**（金币在「买」时已付）。
* **定向法术**（`needs_target=True`）：`target=None` 且候选非空 →
  追加 `PendingChoice(kind="spell_target")`；**无候选 → 效果落空但法术
  照常消耗**（手牌移除）。显式传 `target` 时引擎不校验其是否在候选内
  （由脚本自行处理），环境只应传合法候选。
* 酒馆法术（`CardDef.is_pool_spell`）才计入
  `TAVERN_SPELLS_CAST_THIS_TURN/GAME` 并回法术池。

```python
s = game.create_spell(db.pool_spells()[0].id, controller=hero)
hero.hand.append(s); s.zone = Zone.HAND
assert game.play_spell(hero, s) is True
assert s not in hero.hand and s.zone == Zone.REMOVED

# 定向法术
ok = game.play_spell(hero, targeted_spell)
assert ok is True and game.pending_choices[0].kind == "spell_target"
game.pending_choices.pop(0).choose(0)
```

### 3.5 `refresh_tavern(hero, *, auto=False, free=False, spells_only=False, races=None, copies_of_warband=False, keywords=None, consume_free=True) -> None`

```python
# 签名: hsrl2/game.py:437
game.refresh_tavern(hero)             # 手动刷新，扣 1 金
game.refresh_tavern(hero, auto=True)  # 回合开始的自动刷新（不扣费）
```

* **费用顺序**：`FREE_REFRESH_REMAINING` → `HEALTH_REFRESHES_LEFT`（以生命
  代付）→ 金币（`REFRESH_COST_OVERRIDE` 可覆盖，默认 1）。
* **正常返回 None。金币不足 → 抛 `GameStateError`**（这是全引擎唯一一个
  「合法但付不起」会抛异常而不是返回 False 的常用动作，**必须捕获**）。
* `TURN_SKIPPED` 或 `game._block_manual_refresh` → 静默返回（不刷新、不扣费）。
* 冻结整馆（`hero.frozen_tavern`）→ 保留全部展示内容，且**本次刷新后清除
  FROZEN**（只保留一轮）。单卡冻结（实体级 `FROZEN` tag）同样保留一轮。
* 旧内容回池（不泄漏池）。
* 自动刷新 `auto=True` 绕过 `TURN_SKIPPED` 与 `_block_manual_refresh`，
  且不消耗免费刷新/金币。

```python
hero.gold = 10
game.refresh_tavern(hero)         # None
assert hero.gold == 9

hero.gold = 0
try:
    game.refresh_tavern(hero)
except GameStateError:
    pass                          # 金币不足必须走这里

# 冻结
game.freeze_tavern(hero)
frozen = list(hero.tavern)
game.refresh_tavern(hero)
assert all(e in hero.tavern for e in frozen) and not hero.frozen_tavern
```

### 3.6 `upgrade_tavern(hero) -> bool` / `upgrade_tavern_free(hero) -> None`

```python
# 签名: hsrl2/game.py:1773 / 1792
ok = game.upgrade_tavern(hero)
game.upgrade_tavern_free(hero)
```

* `upgrade_tavern`：
  * 费用 = `max(0, hero.upgrade_cost + UPGRADE_COST_MOD)`（升级费每回合
    自动衰减，下限 0；0 费 + 0 金也能升级——实测 True）。
  * 成功：扣费、`tavern_tier` → 下一个存在档位、更新下一升级费、fire
    `tavern_upgraded`，返回 True。
  * 失败返回 False：`TURN_SKIPPED`、`_upgrade_blocked`、已到本局最高档
    （含异变 101/102 的档位阶梯）、金币不足。
  * **异变 101/102**（"Only Tavern Tiers 1, 3, 5 exist"）下「下一档」不是
    `tier+1`，见 §4.6 的镜像实现。
* `upgrade_tavern_free`：不扣费、返回 **None**、不检查金币；脚本
  （异变 "upgrades itself"）使用。

```python
hero.gold = 10
cost = hero.upgrade_cost          # 5
assert game.upgrade_tavern(hero) is True
assert hero.gold == 10 - cost and hero.tavern_tier == 2
assert hero.upgrade_cost == C.BASE_UPGRADE_COSTS[3]   # 7

hero.gold = 0
assert game.upgrade_tavern(hero) is False

tier = hero.tavern_tier
assert game.upgrade_tavern_free(hero) is None
assert hero.tavern_tier == tier + 1
```

### 3.7 `freeze_tavern(hero) -> None`

```python
# 签名: hsrl2/game.py:1801
assert game.freeze_tavern(hero) is None
assert hero.frozen_tavern is True
```

* 只**设置** `hero` 级 `FROZEN` tag；下一次刷新（手动或自动）保留整馆内容
  后自动清除。
* **引擎没有 `unfreeze_tavern`**（全库无解冻 API）。真实游戏里可以点掉
  冻结，环境若要支持「解冻」只能 `hero.clear(GameTag.FROZEN)` 直接改
  tag（属于触碰引擎内部状态，见 READINESS D-2）。更简单的做法：冻结视为
  一次性、不可撤销。

### 3.8 `use_hero_power(hero, target=None, power_id=None) -> bool`

```python
# 签名: hsrl2/game.py:1990
ok = game.use_hero_power(hero)                # 默认主技能
ok = game.use_hero_power(hero, target=t)      # 定向技能
ok = game.use_hero_power(hero, power_id=pid)  # 第二技能槽
```

* 可用性由脚本协议决定：
  * `passive=True` → 被动技能，`use_hero_power` 恒 False（不可主动用）；
  * `available(hero, game)` → 门槛/冷却；
  * `uses_per_turn`（默认 1，`hp_uses` 额外次数）/ `uses_per_game`；
  * `cost_override(hero, game)` → 动态费用（默认 `CardDef.cost`，下限 0）；
  * `needs_target` + `target_candidates` + `target_count`（Vol'jin 类双目标）。
* **定向技能的费用/计数在「选择结算」时发生**：`target=None` 时
  `use_hero_power` 返回 True 但**不扣费**，只挂
  `PendingChoice(kind="hero_power_target")`；`choose()` 时才扣
  （期间金币可能被花光 → 该次使用作废，不扣费不计数）。
* 失败返回 False：技能未注册、被动、`available` 为假、次数用尽、金币不足、
  定向技能候选不足、传入的 target 已失效。
* 第二技能槽：`game.hero_power_ids(hero)` = 主技能 + `hero._second_power_id`
  （需 `CardType.HERO_POWER` 且已注册）；每个技能独立计次/计费。

```python
ids = game.hero_power_ids(hero)            # ['BG20_HERO_103p', ...]
pid = ids[0]
cost = game.hero_power_cost(hero, game.hero_power_def_for(hero, pid),
                            REGISTRY.get(pid))
hero.gold = 10
assert game.use_hero_power(hero) is True
assert hero.gold == 10 - cost
assert hero.get(GameTag.HERO_POWER_USED_THIS_TURN) == 1
assert game.use_hero_power(hero) is False  # 每回合 1 次（除非脚本另声明）

# 定向技能：挂起期不扣费
assert game.use_hero_power(targeted_hero) is True
assert game.pending_choices[0].kind == "hero_power_target"
game.pending_choices.pop(0).choose(0)
```

### 3.9 `use_activate(hero, minion) -> bool`

```python
# 签名: hsrl2/game.py:1819
ok = game.use_activate(hero, minion)
```

* 前置：`minion.has(GameTag.ACTIVATE)`、本回合未用、`controller is hero`、
  `minion in hero.board`、`hero.gold >= ACTIVATE_COST`（默认 1）。
* 成功：扣费、置 `ACTIVATE_USED_THIS_TURN`、跑脚本 `activate` 钩子、
  fire `activate_used`，返回 True。每回合开始重置已用标记。
* 失败返回 False（不抛异常）。
* 部分 Activate 脚本内部会再产生 `PendingChoice`（如 `activate_target`）。

```python
activate_defs = [d for d in db.pool_minions() if "activate" in d.keywords]
m = game.create_minion(activate_defs[0].id, controller=hero)
game.summon(hero, m)
hero.gold = 10
cost = m.get(GameTag.ACTIVATE_COST, 1)
assert game.use_activate(hero, m) is True
assert hero.gold == 10 - cost
assert m.has(GameTag.ACTIVATE_USED_THIS_TURN)
assert game.use_activate(hero, m) is False
```

### 3.10 `use_dark_gift(hero) -> bool`

```python
# 签名: hsrl2/game.py:2172
ok = game.use_dark_gift(hero)
```

* 可用条件：`turn >= 3`、本回合未用、本局剩余次数 > 0、金币 ≥ 3。
* 成功：扣 3 金、记账、抽 3 个随从各配一个 gift →
  `PendingChoice(kind="dark_gift")`，`options` 是
  `(minion_card_id, gift_card_id)` 二元组；选择后随从（带 gift 效果）
  `pending_hand_add` 入手。
* **池耗尽/无法配对时仍返回 True 但没有 PendingChoice**（官方效果落空）。
* 失败返回 False。

```python
game.turn = 1
assert game.use_dark_gift(hero) is False     # 第 3 回合起才可用

game.turn = 3
hero.gold = 10
assert game.use_dark_gift(hero) is True
assert hero.gold == 7
assert game.pending_choices[0].kind == "dark_gift"
game.pending_choices.pop(0).choose(0)        # (card_id, gift_id) 选择
```

### 3.11 `spend_gold(hero, amount) -> None`

```python
# 签名: hsrl2/game.py:1807
game.spend_gold(hero, 3)
```

* `amount <= 0` → no-op；金币不足 → **抛 `GameStateError`**。
* 成功：扣金币、`GOLD_SPENT_THIS_TURN += amount`、fire `gold_spent`。
* 环境通常不直接调用（各动作内部已扣费），但可用于 `choose` 之后的自定义
  结算或测试。

### 3.12 没有直接 API 的动作

| 动作 | 实际实现 |
|------|----------|
| 买饰品 | 第 6/9 回合 `PendingChoice(kind="trinket_offer")`，`resolve` 里扣金币并 `grant_trinket` 语义（`_offer_trinkets`） |
| 选任务 | `PendingChoice(kind="quest_offer")`，选项 `(quest_id, reward_id)` |
| 发现三选一 | `PendingChoice(kind="discover_minion"/"discover_spell"/"discover_tavern_spell"/...)` |
| 英雄技能三选一 | `PendingChoice(kind="discover_hero_power")` |
| Choose One | `PendingChoice(kind="choose_one")`，选项为选项 key |
| 结束回合 | `game.end_recruit_phase()`（没有 per-player end turn） |

---

## 4. 候选动作枚举要点

> 目标：环境每一步输出**只含合法动作**的候选列表（`hsbg/env/spec.py`
> 的 `CandidateAction`）。引擎只提供**原语**，合法性判定需要环境镜像；
> 本节给出与引擎逐行对齐的镜像实现（`probe_api.py` 已验证）。

### 4.1 三个实体来源

```python
hero.tavern   # list[Entity]：Minion 与 酒馆法术(Spell) 混排；本回合展示
hero.hand     # list[Entity]：Minion / Spell / 酒馆法术 / 生成法术 / Lockbox
hero.board    # list[Minion]：左→右；下标即 ZONE_POSITION

# 区分类型（实体没有 .card_type 属性！）
from hsrl2.minion import Minion
from hsrl2.spell import Spell
isinstance(e, Minion); isinstance(e, Spell)
e.get(GameTag.CARDTYPE)          # CardType.MINION / SPELL / BACON_SPELL...

# 酒馆法术 vs 生成法术：看 CardDef.is_pool_spell（不是 card_type）
d = db.get(e.card_id)
d.is_pool_spell                  # True = 酒馆法术（可买/回法术池）
d.is_pool_minion                 # True = 池内随从（可三连/回随从池）
d.tech_level                     # 随从/法术的 tier（法术实体本身没有 tier 属性）
```

### 4.2 各动作合法条件（引擎判定顺序）

| 动作 | 条件（全部满足才生成候选） | 引擎位置 |
|------|---------------------------|----------|
| buy | `entity in hero.tavern`；`not hero.hand_full()`；`not TURN_SKIPPED`；`quote_buy_cost <= hero.gold` 或可健康购买 | `game.py:737` |
| sell | `m in hero.board or m in hero.hand`；`isinstance(m, Minion)`（引擎不校验，环境必须） | `game.py:986` |
| play_minion | `m in hero.hand`；`not CardDef.unplayable`；`not LOCKED_IN_HAND`；`not TURN_SKIPPED`；`not hero.board_full()`（磁力吸附路径除外） | `game.py:1015` |
| play_spell | `s in hero.hand`；`not unplayable`；`not LOCKED_IN_HAND`；`not TURN_SKIPPED` | `game.py:1432` |
| reroll | `not TURN_SKIPPED`；`not _block_manual_refresh`；有免费刷新 / 健康刷新 / `hero.gold >= refresh_cost` | `game.py:437` |
| upgrade | `not TURN_SKIPPED`；`not _upgrade_blocked`；存在下一档；`hero.gold >= upgrade_cost + UPGRADE_COST_MOD` | `game.py:1773` |
| freeze | 恒合法（0 费）；引擎无 unfreeze | `game.py:1801` |
| hero_power | 见 §4.5 镜像 | `game.py:1990` |
| activate | `has(ACTIVATE)`；`not ACTIVATE_USED_THIS_TURN`；`controller is hero`；`in hero.board`；`gold >= ACTIVATE_COST(默认1)` | `game.py:1819` |
| use_dark_gift | `turn >= 3`；本回合未用；`uses_left > 0`；`gold >= 3` | `game.py:2172` |
| end_turn | 招募阶段恒合法（`finished` / 有 agent 待选时除外） | — |

### 4.3 买价镜像（`quote_buy_cost`）

`buy_from_tavern` 的定价逻辑内联在函数里（约 100 行），没有公开的
「报价」API。环境必须镜像（否则候选与金币判定会漂移）。下列实现与引擎
一致，并已在 probe 中与真实扣款逐项比对（基础价/英雄覆盖/免费额度/
法术折扣）：

```python
from hsrl2 import constants as C
from hsrl2.minion import Minion
from hsrl2.tags import GameTag


def quote_buy_cost(game, hero, entity) -> int:
    """buy_from_tavern 的**只读**价格镜像（不消费任何配额/折扣）。"""
    cost = entity.get(GameTag.COST, C.MINION_BUY_COST)

    if isinstance(entity, Minion):
        # 1) 全局限价 / 英雄级覆盖
        if getattr(game, "_minion_cost_is_tier", False):
            cost = entity.tech_level
        override = hero.get(GameTag.TAVERN_MINION_COST_OVERRIDE, 0)
        if override:
            cost = override
        # 2) 条件化购买价（hero 级规则，取最低命中价；source 离场失效）
        for src, pred, c in list(getattr(hero, "_tavern_cost_rules", [])):
            if src is not None and not (
                    src in hero.trinkets
                    or src in getattr(hero, "quest_rewards", [])
                    or src in hero.board):
                continue
            try:
                if pred(entity):
                    cost = min(cost, int(c))
            except Exception:
                pass
        # 3) 免费随从配额（多来源独立记账；只读判定不消费）
        if _free_minion_buy_available(game, hero, entity):
            cost = 0

    d = game.db.get(entity.card_id)
    if d is not None and d.is_pool_spell:
        # 4) 酒馆法术：持久折扣 → 本回合免费 → 下一个法术折扣
        cost = max(0, cost - hero.get(GameTag.TAVERN_SPELL_COST_MOD, 0))
        if hero.get(GameTag.FREE_SPELL_BUYS_THIS_TURN, 0) > 0:
            cost = 0
        else:
            cost = max(0, cost - hero.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0))
    return cost


def _free_minion_buy_available(game, hero, entity) -> bool:
    """`Game._take_free_minion_buy` 的只读镜像（不消费额度）。"""
    for q in hero._free_minion_buy_quotas:
        if q["turn"] != game.turn or q["used"] >= q["count"]:
            continue
        if Game._free_buy_qualifiers_match(entity, q["race"], q["keyword"]):
            return True
    if hero._free_minion_buy_quotas:
        return False
    n = hero.get(GameTag.FREE_MINION_BUYS_THIS_TURN, 0)
    return n > 0 and Game._free_buy_qualifiers_match(
        entity,
        hero.get(GameTag.FREE_MINION_BUY_RACE, None),
        hero.get(GameTag.FREE_MINION_BUY_KEYWORD, None))
```

> 健康购买（`d.health_cost` / `HEALTH_BUY` / hero 配额）不影响金币报价，
> 但要求 `hero.health + hero.armor > cost`；平台期环境可先用
> `quote_buy_cost <= hero.gold` 做候选，再对不满足者检查健康支付条件。

### 4.4 目标需求识别（战吼/法术/技能/Activate）

引擎用脚本类的**约定属性**声明，而不是数据字段：

```python
from hsrl2.scripts import REGISTRY

script = entity.scripts                     # create_minion/create_spell 已绑定
                                            # （金色无脚本时回落基础卡脚本）
needs_target = bool(getattr(script, "needs_target", False))

# 目标候选：签名随实体类型而变
#   随从（战吼）: target_candidates(minion, game)
#   法术        : target_candidates(spell, game)
#   英雄技能    : target_candidates(hero, game)
cand_fn = getattr(script, "target_candidates", None)
targets = (list(cand_fn(entity, game)) if cand_fn is not None
           else [m for m in hero.board if not m.dead])

# 其它协议属性
getattr(script, "choose_options", None)     # [(key, label), ...] → Choose One
getattr(script, "target_count", 1)          # 英雄技能多目标
getattr(script, "activate", None)           # Activate 效果
```

* 战吼目标：**只有在脚本声明 `needs_target` 且该脚本有 `battlecry` 钩子时**
  才需要目标（`play_minion` 只对 `needs_target` 分流，标不标 `battlecry`
  都会分流；但枚举时把「无战吼的 needs_target 脚本」也当目标型更安全）。
* 法术目标：`needs_target`（`play_spell` 用 `target_candidates` 生成
  `spell_target` 选择，或环境显式传 target）。
* 无候选时：随从/法术仍可打出但效果落空（**不要因此丢弃候选**）。
* 目标集合可能是「酒馆/手牌/棋盘」混合（如 Xyrella/Maiev 指酒馆、Baz'hial
  指随从），一律以 `target_candidates` 为准，**不要**假设只在棋盘。

### 4.5 英雄技能可用性镜像（`hero_power_usable`）

```python
from hsrl2.scripts import REGISTRY


def hero_power_usable(game, hero, power_id):
    """use_hero_power 的只读合法性镜像。返回 dict。"""
    out = {"usable": False, "cost": 0, "needs_target": False,
           "targets": [], "reason": ""}
    if power_id not in game.hero_power_ids(hero):
        out["reason"] = "not_owned"; return out
    power_def = game.hero_power_def_for(hero, power_id)
    script = REGISTRY.get(power_id) if power_def is not None else None
    if power_def is None or script is None:
        out["reason"] = "no_script"; return out
    if getattr(script, "passive", False):
        out["reason"] = "passive"; return out
    avail = getattr(script, "available", None)
    if avail is not None and not avail(hero, game):
        out["reason"] = "unavailable"; return out
    max_uses = (getattr(script, "uses_per_turn", 1)
                + hero.extra_trigger("hp_uses"))
    if hero._power_uses_this_turn.get(power_id, 0) >= max_uses:
        out["reason"] = "used_this_turn"; return out
    per_game = getattr(script, "uses_per_game", None)
    if per_game is not None and \
            hero._power_uses_this_game.get(power_id, 0) >= per_game:
        out["reason"] = "used_this_game"; return out
    cost = game.hero_power_cost(hero, power_def, script)
    if cost and hero.gold < cost:
        out["reason"] = "no_gold"; return out
    n_targets = (getattr(script, "target_count", 1)
                 if getattr(script, "needs_target", False) else 0)
    if n_targets > 0:
        cand_fn = getattr(script, "target_candidates", None)
        targets = (list(cand_fn(hero, game)) if cand_fn is not None
                   else [m for m in hero.board if not m.dead])
        if len(targets) < n_targets:
            out["reason"] = "no_target"; return out
        out["needs_target"] = True
        out["targets"] = targets
    out.update(usable=True, cost=cost)
    return out
```

> 引擎没有公开的 `can_use_hero_power`；这是必须镜像的私有判定之一
> （READINESS D-3）。

### 4.6 升级落点镜像（异变档位阶梯）

```python
def next_existing_tier(game, hero):
    """升级落点：标准局 = tier+1（封顶 max_tavern_tier）；
    异变 101/102 = 阶梯中严格大于当前档的最小档。"""
    ladder = getattr(game, "_tavern_tier_ladder", None)   # 通常是 None
    if ladder is None:
        nxt = hero.tavern_tier + 1
        return nxt if nxt <= game.max_tavern_tier else None
    for t in ladder:
        if t > hero.tavern_tier:
            return t
    return None


def upgrade_cost_now(game, hero):
    return max(0, hero.upgrade_cost + hero.get(GameTag.UPGRADE_COST_MOD, 0))
```

### 4.7 磁力目标

```python
# 候选：手牌中 has(GameTag.MAGNETIC) 的随从 × 棋盘合法宿主
if m.has(GameTag.MAGNETIC):
    for host in hero.board:
        if host.dead or host.controller is not hero or host.zone != Zone.PLAY:
            continue
        if game._magnetic_valid(m, host):       # 私有 API，见 §4.8
            candidates.append(dict(kind="play_minion", src=m,
                                   magnetic_target=host))
```

* 默认宿主种族 = 机械；数据例外（源码硬编码）：
  `BG_DEEP_015` → 也吸亡灵；`BG31_859` → 也吸元素；
  `BG25_807t/t2/t3/t4` → 也吸恶魔。
* 磁力吸附**不占板位**，所以棋盘 7/7 时仍有磁力候选。

### 4.8 参考实现 `enumerate_actions`

完整可运行版本在 `tools/probe_api.py::enumerate_actions`（已跑通 6 项
健全性断言）。核心结构：

```python
def enumerate_actions(game, hero):
    acts = []
    if game.finished or game.pending_choices:
        return acts                                   # choice/game_over 由上层处理
    if hero.get(GameTag.TURN_SKIPPED, False):
        return [{"kind": "end_turn"}]

    # 1) buy
    if not hero.hand_full():
        for slot, e in enumerate(hero.tavern):
            cost = quote_buy_cost(game, hero, e)
            if cost <= hero.gold:
                acts.append({"kind": "buy", "src_slot": slot, "cost": cost})

    # 2) sell（仅 Minion）
    for slot, m in enumerate(hero.board):
        acts.append({"kind": "sell", "src_slot": slot})

    # 3) play_minion / play_spell
    for slot, e in enumerate(hero.hand):
        if e.has(GameTag.LOCKED_IN_HAND):
            continue
        d = game.db.get(e.card_id)
        if d is not None and d.unplayable:
            continue
        if isinstance(e, Minion):
            if e.has(GameTag.MAGNETIC):                # 吸附候选（不占板位）
                for host in hero.board:
                    if not host.dead and game._magnetic_valid(e, host):
                        acts.append({"kind": "play_minion", "src_slot": slot,
                                     "magnetic_target": host})
            if hero.board_full():
                continue
            if getattr(e.scripts, "needs_target", False) \
                    and getattr(e.scripts, "battlecry", None) is not None:
                fn = getattr(e.scripts, "target_candidates", None)
                tgts = (list(fn(e, game)) if fn is not None
                        else [x for x in hero.board if not x.dead])
                for t in (tgts or [None]):
                    acts.append({"kind": "play_minion", "src_slot": slot,
                                 "target": t})
            else:
                for pos in range(len(hero.board) + 1):
                    acts.append({"kind": "play_minion", "src_slot": slot,
                                 "position": pos})
        elif isinstance(e, Spell):
            if getattr(e.scripts, "needs_target", False):
                fn = getattr(e.scripts, "target_candidates", None)
                tgts = (list(fn(e, game)) if fn is not None
                        else [x for x in hero.board if not x.dead])
                for t in (tgts or [None]):
                    acts.append({"kind": "play_spell", "src_slot": slot,
                                 "target": t})
            else:
                acts.append({"kind": "play_spell", "src_slot": slot})

    # 4) reroll（金币不足会抛异常，必须先过滤）
    rc = hero.get(GameTag.REFRESH_COST_OVERRIDE, C.REFRESH_COST)
    if (hero.get(GameTag.FREE_REFRESH_REMAINING, 0) > 0
            or hero.get(GameTag.HEALTH_REFRESHES_LEFT, 0) > 0
            or hero.gold >= rc):
        acts.append({"kind": "reroll", "cost": rc})

    # 5) upgrade
    nxt = next_existing_tier(game, hero)
    if nxt is not None and hero.gold >= upgrade_cost_now(game, hero):
        acts.append({"kind": "upgrade", "cost": upgrade_cost_now(game, hero)})

    # 6) freeze（无 unfreeze）
    acts.append({"kind": "freeze"})

    # 7) hero power（含目标）
    for pid in game.hero_power_ids(hero):
        info = hero_power_usable(game, hero, pid)
        if not info["usable"]:
            continue
        for t in (info["targets"] if info["needs_target"] else [None]):
            acts.append({"kind": "hero_power", "power_id": pid,
                         "target": t, "cost": info["cost"]})

    # 8) activate
    for slot, m in enumerate(hero.board):
        if m.has(GameTag.ACTIVATE) and not m.has(GameTag.ACTIVATE_USED_THIS_TURN):
            if hero.gold >= m.get(GameTag.ACTIVATE_COST, 1):
                acts.append({"kind": "activate", "src_slot": slot})

    # 9) dark gift
    state = game.dark_gift_state.get(hero)
    uses_left = state["uses_left"] if state else C.DARK_GIFT_USES_PER_GAME
    used = state["used_this_turn"] if state else False
    if (game.turn >= C.DARK_GIFT_START_TURN and uses_left > 0 and not used
            and hero.gold >= C.DARK_GIFT_COST):
        acts.append({"kind": "use_dark_gift", "cost": C.DARK_GIFT_COST})

    # 10) end_turn（注意：这是「本智能体结束招募」，对手由环境驱动）
    acts.append({"kind": "end_turn"})
    return acts
```

### 4.9 环境不得不依赖的私有/无公开 API 清单

| 需求 | 引擎现状 | 建议 |
|------|----------|------|
| 下一升级档位 | `Game._next_existing_tier`（私有） | 镜像（§4.6） |
| 买价报价 | 内联在 `buy_from_tavern` | 镜像（§4.3） |
| 免费随从额度判定 | `Game._take_free_minion_buy`（会消费！） | 镜像只读版（§4.3） |
| 英雄技能可用性 | 内联在 `use_hero_power` | 镜像（§4.5） |
| 磁力目标合法性 | `Game._magnetic_valid`（私有） | 直接调用或镜像 |
| 刷新是否会抛异常 | `refresh_tavern` 内部判断 | 前置过滤（§4.2） |
| 卡池枚举 | `db._by_id`（私有）；`db.pool_minions()` 公开 | 直接用 `pool_minions()` |
| 英雄枚举 | 无公开枚举 | `db._by_id` 过滤 `CardType.HERO` |

---

## 5. PendingChoice（发现/三选一/任务/饰品/目标选择）

### 5.1 结构

```python
# hsrl2/game.py:135
class PendingChoice:
    owner: Hero                     # 谁做选择
    options: list                   # 候选；类型见 §5.3
    kind: str                       # 选择类型，见 §5.4
    resolve_callback: callable|None # 选择后的结算回调
    discover_golden: bool           # 仅 Discover 金色选项时存在

    def choose(self, index: int) -> None:
        ...
```

`game.pending_choices` 是**列表队列**，可能同时包含多个英雄的多个选择
（8 人局第 4 回合会一次积压 8 个 `quest_offer`）。

### 5.2 契约：`choose()` 只结算，**不出队**

```python
game.pending_choices.append(PendingChoice(hero, ["a", "b"], "demo",
                                          resolve_callback=cb))
n = len(game.pending_choices)
game.pending_choices[0].choose(1)      # 只调用回调，队列长度不变
assert len(game.pending_choices) == n # 必须由环境 pop(0) 才能出队
game.pending_choices[0].choose(0)      # 再次 choose 会**重复结算**！

choice = game.pending_choices.pop(0)   # 正确用法：先 pop 再 choose
choice.choose(0)
```

* `choose(index)` 越界 → `GameStateError`。
* 回调里的 `pick` 不在选项内（如 Discover）→ `GameStateError`。
* 不 pop 就继续 choose = 同一效果重复施加（smoke 脚本注释记载过 18k
  队列假死的教训）。

### 5.3 `options` 类型

| 类型 | 出现在 | 处理建议 |
|------|--------|----------|
| `str`（card_id） | `discover_*`、`choose_one`（key）、`triple_reward` | `db.get(card_id)` → 卡定义 → 观测 token |
| `Minion` 实体 | `battlecry_target`、`spell_target`、`hero_power_target`、`activate_target` | 直接读实体；映射回 obs 槽位 |
| `tuple` | `dark_gift` = `(minion_card_id, gift_card_id)`；`quest_offer` = `(quest_id, reward_id)` | 两个 id 都转 token（或拼 label） |
| `CardDef` | `trinket_offer`（候选饰品） | 用 CardDef 字段构 token；**最后一项可能是 `None`（放弃）** |
| `None` | `trinket_offer` 的放弃项 | 映射成 `skip` 动作 |

### 5.4 `kind` 清单（实测出现过的）

| kind | 产生点 | 选项 | 结算后果 |
|------|--------|------|----------|
| `discover_minion` | 发现随从（三连奖励/卡牌效果） | `str` | 选中随从入手（占池） |
| `discover_spell` | 发现法术 | `str` | 法术入手 |
| `discover_tavern_spell` | 发现酒馆法术 | `str` | 法术入手 |
| `discover_hero_power` | 英雄技能三选一 / Cosmic Reward | `str` | 替换/附加技能 |
| `triple_reward` | 三连奖励 | `str` | 随从入手 |
| `battlecry_target` | 定向战吼 | `Minion` | 继续结算战吼 |
| `spell_target` | 定向法术 | `Minion` | 继续结算法术 |
| `hero_power_target` | 定向英雄技能（可多目标链） | `Minion` | 结算技能 |
| `activate_target` | 定向 Activate | `Minion` | 结算 Activate 效果 |
| `choose_one` | Choose One（随从/法术） | `str` key | 按 key 结算 |
| `dark_gift` | Dark Gift | `(minion_id, gift_id)` | 随从+gift 入手 |
| `quest_offer` | 第 4 回合任务三选一 | `(quest_id, reward_id)` | 绑定任务/奖励 |
| `trinket_offer` | 第 6/9 回合饰品商店 | `CardDef` ×4 + `None` | 扣金币并绑定饰品 |
| `trinket_replace` / `reward_replace` / `holmes_guess` / `friendly_wager` / `galakrond_tavern` / `tavern_pick` / `choose_protoss` … | 各卡脚本自定义 | 混合 | 见脚本 |

> 引擎**不维护 kind 白名单**（脚本可自定义 kind）。环境应把未知 kind
> 统一按「选项 → obs token；choose 动作」处理，不要枚举穷举。

### 5.5 FIFO 循环（环境层模板）

```python
def settle_choices(game, is_agent_hero, agent_choice_fn, auto_pick=lambda c: 0):
    """FIFO 结算；遇到智能体的选择就停下来交给策略。

    返回 None（队列清空）或 PendingChoice（智能体需要决策）。
    契约：只有 pop(0) 拿到的那一项才能 choose；不要跳过队首。
    """
    while game.pending_choices:
        choice = game.pending_choices[0]        # 只看不 pop
        if choice.owner is is_agent_hero:
            return choice                       # 暴露给策略（phase="choice"）
        game.pending_choices.pop(0)
        choice.choose(auto_pick(choice))        # 对手选择自动结算
    return None


def agent_choose(game, choice, option_index):
    assert game.pending_choices[0] is choice
    game.pending_choices.pop(0)
    choice.choose(option_index)
```

要点：

1. **只处理队首**（FIFO）。若队首是对手选择，替它选并 pop，继续。
2. 智能体的选择暴露给策略时，队列**保持原状**（还没 pop），把
   `options` 序列化成观测；策略返回下标后再 pop+choose。
3. `reset()` / 每次动作 / `end_recruit_phase` 之后都要跑一遍
   `settle_choices`（对手 + 开局 + 战斗后下回合 offer 都可能有选择）。
4. 未知 kind 的自动策略：保守选 0；或按 kind 定制（如 `trinket_offer`
   选 `None` 表示放弃，需要时选 0）。

### 5.6 未结算选择的后果

* 引擎**不会**自动结算；选择对应效果不生效（例如任务没绑定、饰品没买、
  发现没入手）。
* 选择会一直留在 `game.pending_choices`，跨 `end_recruit_phase` 继续存在
  （下一回合会继续积压），最终导致观测/训练数据错位。
* 环境必须在把控制权交回策略前保证：**队列里只剩智能体的选择**。

---

## 6. 战斗与回合推进

### 6.1 `end_recruit_phase()` 的完整副作用（`game.py:2594-2693`）

返回 `None`。顺序：

1. 清 `TURN_SKIPPED`（跳回合只锁一个招募期）；
2. fire `turn_end`；
3. **EoT 效果**：饰品 → 任务奖励 → 棋盘随从（左→右），每个 hook 后
   `check_deaths()`；`END_OF_TURN_DOUBLER`（Drakkari）与 `eot_extra`
   会让本轮 EoT 重复 N 次；
4. **丢弃手牌里未用的 Spellcraft 法术**（永久化豁免除外）；
5. 存活英雄 `hero.last_combat_board = list(hero.board)`（战前快照）；
6. 取用本招募期开始时预生成的配对（`_take_pairing`），逐对 `run_combat`，
   fire `combat_end`；同时记录 `combat_memory` 与
   `_last_opponent_board`；
7. 奇数存活 → leftover 打**幽灵**（`run_ghost_combat`）；
8. `_process_eliminations()`：health≤0 的英雄回池、生成 ghost 记录、
   fire `hero_eliminated`、**从 `game.heroes` 移除**；
9. 存活 ≤1 → `game.finished = True` 并返回（**turn 不再 +1**）；
10. `turn += 1` → `_precompute_pairing()` → 对每个存活英雄执行
    `_begin_recruit_for`（§2.3，含下回合酒馆刷新与任务/饰品 offer）。

验证（A6）：

```python
game = new_game(...)
assert game.end_recruit_phase() is None
assert game.turn == before + 1              # 存活 >1 时
assert loser.health < C.HERO_BASE_HEALTH    # 战败掉血
```

### 6.2 `run_combat(hero_a, hero_b, alive_count=None) -> CombatResult`

```python
# 签名: hsrl2/game.py:3084；CombatResult 定义在 hsrl2/combat.py:31
res = game.run_combat(hero_a, hero_b, alive_count=8)
res.winner          # Hero | None（None=平局）
res.loser           # Hero | None
res.damage_dealt    # 胜方应造成的原始伤害（tier + Σ存活随从 tier）
res.capped_damage   # 应用伤害上限后的实际伤害
res.attacker_first  # 先攻方 Hero
res.rounds          # 攻击轮数
```

* `alive_count`：伤害上限判定用「本阶段开始时的存活人数」；不传则实时统计
  （`_alive_count()`）。上限规则：存活 ≤4 无上限；turn≤3 封顶 5；
  turn 4-7 封顶 10；turn≥8 封顶 15（`C.damage_cap`）。
* 战斗内部同步执行（`game.in_combat=True`）；战后棋盘/监听器/磁力栈/属性
  全部按快照复原（`run_combat` 的 `finally`），只有 PERSIST/Poet/伤害窗口
  增量等例外保留。
* 战斗期间可能产生 `PendingChoice`（少数 SoC/Rally 脚本），必须等
  `run_combat` 返回后统一结算。
* 直接调用 `run_combat` 只打一场，不触发淘汰/换回合；环境正常流程应调用
  `end_recruit_phase()`。

### 6.3 幽灵战

* 奇数存活者：`run_ghost_combat(hero)` 用 `game.ghost_records[-1]`
  （最近被淘汰者的**冻结战团**）；无记录（尚无人被淘汰）→ 本回合不战。
* 幽灵 Hero 是临时对象：临时 `append` 进 `game.heroes`，`finally` 移除；
  幽灵 `health=0` 不计入存活人数（伤害上限按真实人数）。
* 幽灵战结果同样是 `CombatResult`；并 fire `combat_end`；对手记忆记 `None`。
* 幽灵不成长、不变化；幽灵随从是冻结克隆（`_frozen_clone`）。

```python
game = new_game(db, 4, seed=125)
game.heroes[3].health = 0
game._process_eliminations()      # 仅演示；正常由 ERP 调用
assert len(game.heroes) == 3 and len(game.ghost_records) == 1

ends = []
game.events.register(Listener(event="combat_end", owner=game.heroes[0],
                              callback=lambda g, **kw: ends.append(kw["result"])))
game.end_recruit_phase()
# 此时应有 1 场正常战斗 + 1 场幽灵战
```

### 6.4 淘汰：`game.heroes` 会被原地修改

```python
elims = []
game.events.register(Listener(
    event="hero_eliminated", owner=agent_hero,
    callback=lambda g, **kw: elims.append(kw["hero"].name)))

dead.health = 0
game.end_recruit_phase()          # 内部 _process_eliminations
assert dead not in game.heroes    # 淘汰者被移除！
assert dead.name in elims         # 事件顺序 = 名次数据源
```

`_process_eliminations`（`game.py:3028-3082`）对每个 health≤0 的英雄：

1. 棋盘/手牌/酒馆回池（金卡 3 份、非三连金 1 份；酒馆法术回法术池）；
2. `game.ghost_records.append({name, board: [冻结克隆], tavern_tier})`；
3. fire `hero_eliminated`；
4. `game.heroes.remove(hero)`；
5. 清空区域、注销其全部监听器。

注意：

* 淘汰者的 `hero` 对象仍存在（外部引用可读），但已不在 `game.heroes`；
* 同一回合多人同时 ≤0：`eliminated` 顺序 = `game.heroes` 当前顺序
  （引擎按列表顺序逐个处理），环境记录该顺序即可；
* `game.combat_memory` / `_opponent_history` / `_last_opponent_board`
  以 Hero 为键，**淘汰者的键不会清理**（长局小内存增长，无正确性影响）。

### 6.5 `finished` 判定

* `end_recruit_phase` 末尾：`alive = [h for h in game.heroes if h.is_alive]`；
  `len(alive) <= 1` → `game.finished = True`，**turn 不再自增**，不做下一
  回合副作用。
* `finished` 后再次调用 `end_recruit_phase()` 不会崩，但也不推进 turn
  （环境必须在 `finished` 时终止 episode）。
* 注意 `is_alive` = `health + armor > 0`。

### 6.6 名次计算（**环境层职责**，引擎不提供）

引擎没有 rank/placement 字段，只有 `hero_eliminated` 事件与 `game.heroes`
列表变化。标准做法：

```python
class RankTracker:
    def __init__(self, total_players: int):
        self.total = total_players
        self.eliminated = []            # 按淘汰先后

    def on_hero_eliminated(self, hero):
        self.eliminated.append(hero)

    def final_ranks(self, survivors) -> dict:
        ranks = {}
        for i, hero in enumerate(self.eliminated):
            ranks[id(hero)] = self.total - i      # 第一个死的 = 第 N 名
        for hero in survivors:
            ranks[id(hero)] = 1
        return ranks
```

* 第一个被淘汰 = 第 `num_players` 名；最后存活 = 第 1 名。
* 同一回合多人淘汰：按 `hero_eliminated` 事件顺序（引擎按列表顺序发）。
* 智能体被杀时 `hero not in game.heroes` 但仍可调用 `hero.health` 等读取
  最终状态。

### 6.7 事件与日志

可注册 `game.events.register(Listener(event=..., owner=..., callback=...))`
监听。常用事件：`combat_end`、`hero_eliminated`、`death`、`minion_bought`、
`card_played`、`tavern_refresh_complete`、`turn_start`/`turn_end`、
`hero_power_used`、`trinket_bought`、`gold_spent`、`stats_gained`。
`Listener.owner` 离场自动注销；不要持有已淘汰英雄的监听器。

战斗日志：`game.combat_summon_log` / `game.combat_death_log`（每场重置）、
`hero._last_combat_result`（"win"/"loss"/"draw"）。

---

## 7. 状态读取

### 7.1 Hero（`hsrl2/hero.py`）

| 读取 | 类型 | 说明 |
|------|------|------|
| `hero.health` | int | `HEALTH2`；受伤先扣护甲 |
| `hero.armor` | int | |
| `hero.gold` | int | 0..99（`GOLD_HOLD_CAP`） |
| `hero.tavern_tier` | int | 1..`game.max_tavern_tier` |
| `hero.upgrade_cost` | int | 当前升级费 |
| `hero.is_alive` | bool | `health + armor > 0` |
| `hero.frozen_tavern` | bool | `FROZEN` tag |
| `hero.board` | list[Minion] | 左→右 |
| `hero.hand` | list[Entity] | ≤10 |
| `hero.tavern` | list[Entity] | 随从+法术混排 |
| `hero.trinkets` | list[Entity] | 已获得饰品 |
| `hero.trinkets_granted` | set[str] | 已获得饰品 id |
| `hero.quest` | Entity\|None | 当前任务 |
| `hero.quest_rewards` | list[Entity] | 已获得任务奖励 |
| `hero.last_combat_board` | list[Minion] | **自己**上一场战前战团 |
| `hero.board_full()` / `hand_full()` | bool | 7 / 10 |
| `hero.living_minions()` | list[Minion] | 未死亡随从 |
| `hero.income_cap` | int | 默认 10（可被效果提高） |
| `hero.extra_triggers` | dict | 额外触发额度（脚本用） |

### 7.2 Minion（`hsrl2/minion.py`）

| 读取 | 类型 | 说明 |
|------|------|------|
| `m.card_id` | str | |
| `m.get(GameTag.CARDTYPE)` | CardType | **没有 `.card_type` 属性** |
| `m.zone` | Zone | `PLAY=1 / HAND=2 / TAVERN=3 / REMOVED=6` |
| `m.uuid` | str(12) | 局内稳定 id |
| `m.atk` | int | base+buff+光环+动态脚本 |
| `m.health` | int | 当前血；`m.max_health` 上限 |
| `m.tech_level` | int | 随从 tier（token=1） |
| `m.races` | frozenset[Race] | 类型身份集合（含 ALL 展开/家族改写） |
| `m.race` | Race | 主类型单值视图 |
| `m.has_race(Race.X)` | bool | 集合语义 |
| `m.taunt/divine_shield/poisonous/venomous_active/reborn/windfury/cleave/is_golden/exhausted` | bool | 关键词视图 |
| `m.buffs` | list[Buff] | 附魔 |
| `m.stats_without_aura()` | (atk, health) | base+buff（不含光环/动态） |
| `m.snapshot_state()` | dict | 战斗快照（**慎用**：会 deepcopy tags，见 READINESS D-1） |

### 7.3 Spell / Entity

* `Spell` 是 `Entity` 子类：`card_id / uuid / zone / tags / controller`；
  `spell.get(GameTag.COST)`。
* **法术没有 `tech_level` 属性**——tier 读 `db.get(spell.card_id).tech_level`。
* 通用 `Entity`：`get(tag, default) / set(tag, value) / has(tag) / clear(tag)`，
  以及 `call_script(hook, ctx)`。
* 卡牌类型：`CardType.MINION=4, SPELL=5, HERO=3, HERO_POWER=10,
  BACON_TRINKET=44, BACON_ANOMALY=43, BACON_SPELL=42,
  BACON_QUEST_REWARD=40`。观测映射见 `hsbg/env/spec.py` 的
  `CARD_TYPE_*`。

### 7.4 CardDef（`hsrl2/defs.py`，不可变）

主要字段：`id, dbf_id, name, text, card_type, race, races, race_tags,
tech_level, atk, health, cost, rarity, armor, script_data_num_1..5,
triple_upgrade_id, spell_school, keywords(frozenset[str]),
avenge_target, activate_cost, spellcraft_id, hero_power_id, sell_value,
unplayable, dark_gift, health_cost, is_pool_minion, is_pool_spell,
quest, quest_progress_total, subsets, raw(dict)`。

* `d.num(i)` 取模板参数 `{i}`（0..4），缺失返回 default/None。
* `d.races` = `CARDRACE ∪ per-race tag`；`Race.ALL` 展开为 10 族。
* `d.keywords` 是**卡面关键词字符串集合**（如 `{"taunt","battlecry"}`），
  不是 `GameTag`；实体上的关键词用属性/`has(GameTag.X)` 读取。

### 7.5 CardDB 查询

```python
db.get(card_id)                # CardDef | None
db.by_dbf(dbf_id)              # CardDef | None
db.golden_version(def)         # 金色本体 CardDef | None
db.pool_minions()              # 247 张池内随从（非金）
db.pool_spells()               # 75 张池内酒馆法术
db.dark_gifts()                # 43 个 Dark Gift
db.trinket_offer_pool()        # 331 个可被商店提供的饰品
len(db)                        # 3683
```

### 7.6 池（`hsrl2/pools.py`）

```python
game.minion_pool.available(card_id)      # 剩余副本数
game.minion_pool.total_remaining()       # 全池剩余
game.minion_pool.candidates(max_tier)    # 可抽 id 列表（剩余>0）
game.spell_pool.available(id) / total_remaining()
```

* 池是**共享**的（8 人共享 247 张随从池）；Discover/随机获取受池限制。
* 金色出售/淘汰回池 3 份；非三连金回 1 份。

### 7.7 对手与大厅

```python
game.next_opponent(hero)             # 本回合对手 Hero | None（幽灵/未配对=None）
game.next_opponent_warband(hero)     # 对手**当前**战团（隐藏信息！慎用）
game.last_opponent(hero)             # 上一场对手 Hero | None（幽灵战=None）
game.last_opponent_warband(hero)     # 上一场对手**战前**战团（官方可见信息）
hero.last_combat_board               # 自己上一场战前战团

# 大厅统计由环境自己算（引擎无 API）
alive = [h for h in game.heroes if h.is_alive]
len(alive)                            # alive_count
8 - len(alive)                        # 已淘汰人数
```

* **POMDP 边界**：`next_opponent_warband` 暴露的是对手**当前**棋盘（真实
  游戏不可见），`last_opponent_warband` 才是官方可见的「上一场战前战团」。
  观测只应使用后者（ENV_SPEC §7）。
* **坑**：`last_opponent_warband` 在「对手战团为空」时返回 **None**
  （不是 `[]`）——引擎实现是 `list(snap) if snap else None`。首回合/无战斗
  记录时同样 None。环境要归一化为 `()`。

### 7.8 实体 → 观测字段建议

| obs 字段 | 来源 |
|----------|------|
| `card_id` | `e.card_id` |
| `card_type` | `e.get(GameTag.CARDTYPE)` 映射字符串 |
| `zone` / `slot` | 所在列表 + 下标 |
| `atk/health` | `Minion.atk/max_health`（手牌/酒馆也用卡面值或实体值） |
| `tier` | `Minion.tech_level`；法术/饰品用 `db.get(id).tech_level` |
| `cost` | `e.get(GameTag.COST, 0)`；酒馆实体用 `quote_buy_cost` |
| `races` | `Minion.races` → 字符串集合 |
| `keywords` | 实体关键词属性 → 字符串集合（或 `CardDef.keywords`） |
| `golden` | `Minion.is_golden` |
| `entity_id` | `e.uuid`（调试用） |

---

## 8. 确定性

### 8.1 GameRNG

```python
from hsrl2.rng import GameRNG

rng = GameRNG(42)
rng.choice([1, 2, 3], label="demo")   # 带 label 时写审计日志
rng.sample([1, 2, 3], 2, label="demo")
rng.shuffle(lst, label="demo")
rng.random()
rng.randint(1, 6)
rng.seed_value                        # 构造时的 seed
rng.decisions                         # [(label, repr(choice)), ...] 审计日志
```

* 引擎**全部**随机性走 `game.rng`（`hsrl2/` 内只有 `rng.py` `import random`）。
* `GameRNG` 不含 `randrange`；环境驱动层的随机（如随机对手）请**另用**
  `random.Random(seed)`，不要污染 `game.rng`。
* `rng.decisions` 每局约 1300-1800 条（实测 20 局 mean≈1367），长期训练
  若不释放 Game 对象会累积（每局 < 1 MB 量级，见 READINESS D-6）。

### 8.2 seed 传播

```python
game = Game(heroes, db, seed=42)      # game.rng = GameRNG(42)
game.start_game()                     # 首回合酒馆/配对/offer 全部由该 RNG 决定
```

`seed=None` → 不可复现（`random.Random(None)`）。英雄选择、对手策略等
**环境侧**随机也必须由环境自己的 seed 派生（建议
`env_seed → (game_seed, driver_seed)`），否则回放断裂。

### 8.3 同一 seed 重放的条件

**全部满足**时轨迹逐位一致（probe A8 已验证：同一 seed 两次轨迹完全相同、
不同 seed 不同）：

1. 同一 Python/引擎版本、同一 `data/` 数据（CardDB 内容一致）；
2. 同一 `Game(heroes, db, seed=..., anomaly=...)` 参数；
3. **同一 heroes 列表**（英雄 id 与顺序）；
4. **同一动作序列**（包括顺序、目标、position、以及每个 `PendingChoice`
   的 `choose` 下标与 pop 时机）；
5. 不使用 `random` 模块或任何真实时间/哈希顺序影响决策；
6. 不在同一进程内用线程并发跑两局（见 §8.4）；
7. 若开启 `Game(anomaly=...)`，seed 与 anomaly 都要一致。

### 8.4 确定性注意事项

* `entity.py` 有**模块级** `_stats_gained_suppress_depth`（战斗快照复原时
  抑制 `stats_gained` 广播）。它是进程全局计数，**不是线程安全**：
  同进程多线程并行跑两局会互相干扰（一局的复原窗口会静默另一局的广播）。
  → 并行请用**多进程**（`hsbg/env/vec_env.py` 的 multiprocessing 方案），
  不要用线程。
* 事件回调的注册顺序影响同一事件的结算顺序（脚本 on_bind 顺序确定，但
  环境若自行注册监听器要注意顺序）。
* `game.heroes` 顺序影响配对（`matchmaking.pair_players` 对 `alive` 列表
  洗牌，但初始顺序来自 `game.heroes`）→ 不要重排 `game.heroes`。

---

## 9. 常见错误与规避

### 9.1 `GameStateError` 触发点

| 触发点 | 条件 | 规避 |
|--------|------|------|
| `game.spend_gold(hero, n)` | `hero.gold < n` | 先检查金币 |
| `game.refresh_tavern(hero)` | 金币不足且无免费/健康刷新 | 先算刷新费（§4.2） |
| `PendingChoice.choose(i)` | 下标越界 | 按 `len(options)` 校验 |
| Discover 回调 | pick 不在选项内 | 只能传 options 里的对象 |
| `Game.start_game()` | `anomaly` 非 `BACON_ANOMALY` | 从合法异变池选 |
| `Game.set_second_hero_power()` | 第二槽已占用 / 技能不存在 | 只调用一次 |
| `Game.replace_hero_power()` | 技能 id 不存在 | 用 DB 中存在的 id |
| `Game.apply_dark_gift()` | gift id 未知 | 只对已知 gift 调用 |
| `CombatLoopError` | 战斗轮数>2000 / 死亡波次>100 / 队列动作>20000 | 引擎 bug 兜底；训练进程必须 try/except 并丢弃该局 |

### 9.2 静默失败（返回 False / None，不抛异常）

* `buy_from_tavern` / `play_minion` / `play_spell` / `sell_minion` /
  `upgrade_tavern` / `use_hero_power` / `use_activate` / `use_dark_gift`
  → `False`；
* `refresh_tavern`（`TURN_SKIPPED`）→ `None` 且不刷新；
* `used_dark_gift` 池耗尽 → `True` 但**无 PendingChoice**；
* `play_minion`/`play_spell` 目标非法/无候选 → `True` 但效果落空；
* `buy_from_tavern` 时手牌被监听器占满 → `True` 但卡进
  `game.pending_hand_queue`。

**环境层动作应用模板**：

```python
def apply_action(game, hero, action):
    """返回 (ok, note)。GameStateError 由上层转成 invalid。"""
    try:
        kind = action["kind"]
        if kind == "buy":
            return game.buy_from_tavern(hero, action["entity"]), ""
        if kind == "sell":
            return game.sell_minion(hero, action["entity"]), ""
        if kind == "play_minion":
            return game.play_minion(
                hero, action["entity"],
                position=action.get("position"),
                target=action.get("target"),
                magnetic_target=action.get("magnetic_target")), ""
        if kind == "play_spell":
            return game.play_spell(hero, action["entity"],
                                   target=action.get("target")), ""
        if kind == "reroll":
            game.refresh_tavern(hero)
            return True, ""
        if kind == "upgrade":
            return game.upgrade_tavern(hero), ""
        if kind == "freeze":
            game.freeze_tavern(hero)
            return True, ""
        if kind == "hero_power":
            return game.use_hero_power(hero, target=action.get("target"),
                                       power_id=action.get("power_id")), ""
        if kind == "activate":
            return game.use_activate(hero, action["entity"]), ""
        if kind == "use_dark_gift":
            return game.use_dark_gift(hero), ""
        if kind == "end_turn":
            return True, "end_turn"
        return False, f"unknown kind {kind}"
    except GameStateError as e:
        return False, f"invalid: {e}"
```

### 9.3 状态污染坑（比异常更危险）

| 坑 | 现象 | 规避 |
|----|------|------|
| `sell_minion(hero, spell)` | `AttributeError`；金币已 +1、卡已离手、zone 未更新 | 只对 Minion 生成 sell 候选 |
| `play_minion(position=-1)` | 按 Python 负索引插入（不报错） | 只生成 `0..len(board)` |
| `play_minion(position=99)` | 自动夹到最右 | 同上 |
| 满手牌时生成卡 | 进 `pending_hand_queue`（不在 hand 里） | 观测可忽略；注意跨回合补发 |
| 淘汰英雄仍被引用 | `hero not in game.heroes` 但对象可用 | 每步从 `game.heroes` 重新取 |
| 未 pop 就 choose | 效果重复结算 | 严格 pop(0)→choose |
| `finished` 后继续 end_recruit_phase | 不推进 turn（但仍跑流程） | episode 终止 |
| 未知英雄 id | 静默无技能 | 从合法英雄池选 |

### 9.4 `pending_hand_queue` 的语义

* `game.pending_hand_queue: list[(Hero, Entity)]`：满手牌时「等待入场」的
  生成卡（购买/发现/Dark Gift/三连奖励/Spellcraft 等）。
* 下一次回合开始（`_begin_recruit_for`）若手牌有空位则自动补入；
  手牌一直满则持续排队（实测长局终局最多残留 ~55 张）。
* 环境观测默认只暴露 `hero.hand`（≤10）；队列中的卡是「未来手牌」，
  不进入观测（也不会丢失）。

---

## 10. 环境驱动伪代码（reset / 枚举 / step / 结束回合 / 对手）

```python
# hsbg/env/driver.py 级别的最小骨架（不含观测/奖励实现）

def reset(env, seed):
    game_seed, driver_seed = split_seed(seed)
    db = SHARED_DB                                  # 进程级加载一次（§1.1）
    hero_ids = pick_heroes(db, n=env.num_players, rng=random.Random(driver_seed))
    heroes = [Hero(hid, f"P{i}") for i, hid in enumerate(hero_ids)]
    game = Game(heroes, db, seed=game_seed, anomaly=env.anomaly)
    game.start_game()

    env.rank_tracker = RankTracker(env.num_players)
    game.events.register(Listener(
        event="hero_eliminated", owner=heroes[0],
        callback=lambda g, **kw: env.rank_tracker.on_hero_eliminated(kw["hero"])))
    env.agent = heroes[env.agent_index]             # 固定 0 号

    settle_choices(game, env.agent, ...)            # §5.5：开局选择
    drive_opponents(game, env)                      # 若 reset 落在招募期
    return build_observation(game, env)


def step(env, action):
    game, agent = env.game, env.agent
    if game.finished:
        return terminated_observation(env)

    if env.phase == "choice":
        choice = game.pending_choices[0]
        ok, note = apply_choice(game, choice, action["option"])
    else:
        ok, note = apply_action(game, agent, action)          # §9.2 模板
        settle_choices(game, agent, ...)                       # 动作可能触发选择

    # 同步对手的待结算选择（对手的招募动作由 env 的对手策略按需驱动）
    settle_choices(game, agent, ...)

    if not ok:
        return same_observation(env), env.reward.invalid_action, False, False, {
            "invalid": True, "note": note, ...}

    if action["kind"] == "end_turn":
        drive_opponents(game, env)                  # 所有对手做完招募（公开 API）
        game.end_recruit_phase()                    # 战斗+淘汰+下一回合
        settle_choices(game, agent, ...)            # 下回合 offer / 战斗内选择
        env.turn += 1
        if env.agent not in game.heroes or game.finished:
            rank = env.rank_tracker.final_rank(env.agent)
            return terminal_observation(env, rank)

    env.phase = "choice" if game.pending_choices else "recruit"
    obs = build_observation(game, env)
    return obs, reward_from_transition(env), False, False, info


def drive_opponents(game, env):
    """对手招募：只使用引擎公开 API，逐动作 + 每次动作后结算其选择。"""
    for hero in list(game.heroes):                  # 注意：淘汰会改列表
        if hero is env.agent or not hero.is_alive:
            continue
        settle_choices(game, env.agent, ...)        # 先把非智能体选择清掉
        n = 0
        while n < env.max_opponent_actions:
            n += 1
            action = env.opponent_policy.choose(game, hero, env)
            if action is None:                      # None = 结束招募
                break
            ok, _ = apply_action(game, hero, action)
            settle_choices(game, env.agent, ...)
            if not ok:
                break                               # 对手策略 bug 保护
        # 对手没有 per-player end turn：全部对手做完后由 ERP 统一推进
```

### 10.1 一次 episode 的时序（环境视角）

```
reset():
  CardDB.load(一次/进程) → Hero×8 → Game(seed) → start_game()
  → settle_choices()（开局技能/异变）
  → 构造 obs(phase=recruit)

loop:
  obs(phase=recruit) → 策略选候选
    → apply_action → settle_choices
    → 若 agent 还有选择 → obs(phase=choice)
    → 若 action == end_turn:
        drive_opponents() → end_recruit_phase() → settle_choices()
        → agent 淘汰?/finished? → terminated + 名次
        → 否则 obs(phase=recruit)，turn+1

terminated:
  rank = RankTracker.final_rank(agent)      # 第 1 名 = 1
```

### 10.2 动作 ↔ 引擎调用对照（环境层要实现的唯一映射）

| 候选 kind | 引擎调用 |
|-----------|----------|
| `buy` | `game.buy_from_tavern(hero, tavern[slot])` |
| `sell` | `game.sell_minion(hero, board[slot])` |
| `play_minion` | `game.play_minion(hero, hand[slot], position, target, magnetic_target)` |
| `play_spell` | `game.play_spell(hero, hand[slot], target)` |
| `reroll` | `game.refresh_tavern(hero)` |
| `upgrade` | `game.upgrade_tavern(hero)` |
| `freeze` | `game.freeze_tavern(hero)` |
| `hero_power` | `game.use_hero_power(hero, target, power_id)` |
| `activate` | `game.use_activate(hero, board[slot])` |
| `use_dark_gift` | `game.use_dark_gift(hero)` |
| `end_turn` | `game.end_recruit_phase()`（先驱动全部对手） |
| `choose` | `game.pending_choices.pop(0).choose(i)` |

---

## 附录 A：关键常量与数值（`hsrl2/constants.py`）

| 常量 | 值 |
|------|-----|
| 金币 | `GOLD_START=3`，`GOLD_INCOME_CAP=10`，`GOLD_HOLD_CAP=99` |
| 购买/出售/刷新/冻结 | 3 / 1 / 1 / 0 |
| 棋盘/手牌 | 7 / 10 |
| 酒馆展示数 | `{1:3, 2:4, 3:4, 4:5, 5:5, 6:6}`（另固定 1 张酒馆法术） |
| 升级费基数 | `{2:5, 3:7, 4:8, 5:9, 6:10, 7:11}`，每回合 -1、下限 0 |
| 随从池副本 | `{1:16, 2:15, 3:13, 4:11, 5:9, 6:7, 7:5}` |
| 伤害上限 | turn≤3: 5；4-7: 10；≥8: 15；存活≤4 无上限 |
| 任务 offer | 第 4 回合，三对 (任务, 奖励) 选一 |
| 饰品 offer | 第 6 回合 Lesser / 第 9 回合 Greater，4 选 1 + 放弃 |
| Dark Gift | 第 3 回合起，3 金/次，每回合 1 次、每局 3 次 |
| 战斗保护 | 攻击轮数 ≤2000；死亡波次 ≤100；队列动作 ≤20000（超限抛 `CombatLoopError`） |

## 附录 B：本文验证清单（`tools/probe_api.py`）

| 分组 | 覆盖内容 |
|------|----------|
| A1 | CardDB 加载/查询、英雄枚举、Hero 初始值、Game/start_game、anomaly 异常 |
| A2 | 回合开始副作用（金币/升级费/刷新/SoT）、冻结、任务/饰品 offer 时点 |
| A3 | 12 个动作 API 的返回/异常/前置/副作用/坑（buy/sell/play×2/refresh/upgrade/freeze/hero_power/activate/dark_gift/spend_gold） |
| A4 | 候选枚举：价格镜像、技能可用性镜像、目标集合、磁力、满手/满板、`enumerate_actions` 健全性 |
| A5 | PendingChoice 结构、choose 契约、越界异常、FIFO、选项类型 |
| A6 | CombatResult、伤害上限、ERP 副作用、in_combat、幽灵战、淘汰、finished、名次算法 |
| A7 | Hero/Minion/Spell/Entity/CardDef/CardDB/池/对手 API 读取 |
| A8 | 同 seed 重放一致、不同 seed 不同、GameRNG 方法 |
| A9 | GameStateError 各触发点、静默失败、满手排队、淘汰列表变化、已知状态污染坑 |

运行：

```powershell
cd C:\HSagent
python tools\probe_api.py --verbose     # 逐条 PASS
```
