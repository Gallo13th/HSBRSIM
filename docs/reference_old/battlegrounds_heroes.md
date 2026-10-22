# 酒馆战棋 — 英雄技能详细描述文档

> 本文档基于 Hearthstone Wiki (hearthstone.wiki.gg/wiki/Battlegrounds) 最新内容撰写。
> 
> 版本基准：**Patch 34.6.0.235290 (2026-02-09)**
> 
> 当前英雄数：**114**（含轮换英雄）

---

## 1. 英雄基础机制

### 1.1 英雄选择

- 每局游戏开始时，每位玩家从 **2 个（无赛季通行证）或 4 个（有赛季通行证）** 随机英雄中选择 1 个
- 新英雄发布后通常在所有对局中可用 **2 周**
- 英雄会定期轮换（退休/回归）
- 当前退休英雄可能在未来补丁中重新引入

### 1.2 基础属性

| 属性 | 默认值 | 例外 |
|------|--------|------|
| 生命值 | 30     | Patchwerk = 60 |
| 护甲 | 0-20   | 根据英雄强度动态调整 |
| 种族 | 中立   | 所有英雄均为中立 |

### 1.3 护甲系统（Armor Tier）

护甲值是 Blizzard 用于平衡英雄强度的动态系统：

| 护甲等级 | 护甲值 | 说明 |
|---------|--------|------|
| Tier 0  | 0      | 最强英雄 |
| Tier 1  | 2-5    | 较强英雄 |
| Tier 2  | 5-10   | 中等英雄 |
| Tier 3  | 10-15  | 较弱英雄 |
| Tier 4  | 15-20  | 最弱英雄 |

> **项目当前问题**：`hero.py` 中完全没有护甲系统的实现。所有英雄都使用默认的 30 血，没有护甲差异。

---

## 2. 英雄技能类型

### 2.1 技能分类

| 类型 | 说明 | 消耗 | 典型示例 |
|------|------|------|---------|
| **被动（Passive）** | 持续生效，无需激活 | 0 | Deathwing +3攻、Millhouse 随从2金 |
| **主动（Active）** | 酒馆阶段手动使用 | 通常 1-2 金 | Rafaam 偷随从、Reno 镀金 |
| **战斗（Battle）** | 战斗开始时触发 | 0 | Al'Akir 风怒/圣盾、Nefarian 喷火 |
| **触发（Triggered）** | 条件满足时自动触发 | 0 | Sylvanas 亡语偷、Vashj 升级后发现 |

### 2.2 技能使用限制

- **每回合使用次数**：大部分主动技能每回合限 1 次
- **每局使用次数**：部分技能有全局限制（如 Reno 只能使用 1 次）
- **冷却回合**：部分技能有冷却（如 Zephrys 每 3 回合）

---

## 3. 当前可用英雄列表（按类型）

### 3.1 被动技能英雄

| 英雄（中文） | 英雄（英文） | 技能名 | 效果 | 护甲 |
|------------|------------|--------|------|------|
| 帕奇维克 | Patchwerk | All Patched Up | 开局 60 血 | 0 |
| 馆长 | The Curator | Menagerist | 开局 2/2 全种族融合怪 | 0 |
| 死亡之翼 | Deathwing | ALL Will Burn! | 所有随从 +3 攻击力 | 0 |
| 挂机的阿凯 | AF Kay | Procrastinate | 跳过前 2 回合，T3 发现 2 个 T3 随从 | 0 |
| 米尔豪斯 | Millhouse Manastorm | Manastorm | 随从 2 金，刷新 2 金，开局 2 金 | 0 |
| 诺兹多姆 | Nozdormu | Clairvoyance | 每回合首次刷新免费，酒馆 +1 展示位 | 0 |
| 伊瑟拉 | Ysera | Dream Portal | 回合开始，酒馆中加入一条龙 | 0 |
| 恩佐斯 | N'Zoth | Avatar of N'Zoth | 开局 1/1 鱼，获得所有亡语 | 0 |
| 格雷伯 | Greybough | Sprout it Out! | 召唤的随从 +1/+2 和嘲讽 | 0 |
| 阿莱克丝塔萨 | Alexstrasza | Queen of Dragons | 升到 T5 后，发现 2 条龙 | 0 |
| 恐龙大师布莱恩 | Dinotamer Brann | Battle Brand | 战吼触发两次 | 0 |
| 伊利丹 | Illidan Stormrage | Wingmen | 最左和最右随从率先攻击 | 0 |
| 奥妮克希亚 | Onyxia | Broodmother | 复仇(4)：召唤 3/1 雏龙 | 0 |
| 米尔菲丝 | Millificent Manastorm | Tinker | 酒馆中机械 +1/+1 | 0 |
| 阿兰娜 | Aranna Starseeker | Demon Hunter Training | 刷新 16 次后，酒馆永远 7 个随从 | 0 |
| 鼠王 | The Rat King | A Tale of Kings | 每回合切换种族，该种族随从 +2/+2 | 0 |
| 瓦格托格女王 | Queen Wagtoggle | Wax Warband | 回合结束，每个不同种族友方 +2/+1 | 0 |
| 伊妮·风暴线圈 | Ini Stormcoil | MechGyver | 打出机械后，获得随机磁力 | 0 |
| 艾德温 | Edwin VanCleef | Sharpen Blades | 购买随从后，使其 +1/+1 | 0 |
| 范达尔 | Vanndar Stormpike | Lead the Stormpikes | 复仇(2)：友方 +1 生命值 | 0 |
| 德雷克塔尔 | Drek'Thar | Lead the Frostwolves | 复仇(2)：友方 +1 攻击力 | 0 |
| 布鲁坎 | Bru'kan | Embrace the Elements | 每回合选择元素祈咒 | 0 |
| 晨拥 | Chenvaala | Avalanche | 打出 3 个元素后，升级费用 -3 | 0 |
| 库尔特鲁斯 | Kurtrus Ashfallen | Final Showdown | 三阶被动：买3→买4→全体+2/+2 | 0 |
| 艾萨拉 | Queen Azshara | Azshara's Ambition | 场上 30+ 属性值时变身 | 0 |
| 厄祖玛特 | Ozumat | Tentacular | 战斗开始，召唤 2/2 触手（每回合升级）| 0 |
| 大使费林 | Ambassador Faelin | Expedition Plans | 开局发现 2 个高等级随从 | 0 |
| 比格沃斯 | Mr. Bigglesworth | Kel'Thuzad's Kitty | 对手淘汰时，从其战队发现随从 | 0 |
| 卡莉尔 | Cariel Roame | Conviction | T2/T4/T6 升级圣契 +1/+1→+2/+2→+3/+3 | 0 |
| 布莱克松 | Death Speaker Blackthorn | Bloodbound | 升级酒馆后获得 2 血宝石 | 0 |
| 欧穆 | Forest Warden Omu | Everbloom | 开局 +1 金，升级费用 -1 | 0 |
| 加里维克斯 | Trade Prince Gallywix | Smart Savings | 未用完金币保留到下一回合 | 0 |
| 德纳修斯 | Sire Denathrius | Whodunit? | 开局选择 2 个任务 | 0 |
| 凯尔萨斯 | Kael'thas Sunstrider | Verdant Spheres | 每购买第三个随从 +2/+2 | 0 |
| 托瓦格尔 | Heistbaron Togwaggle | The Perfect Crime | 开局选择暗月宝藏 | 0 |
| 提克特斯 | Tickatus | Prize Wall | 开局发现暗月奖品 | 0 |
| 吉恩 | Genn Greymane | King of Duality | T4 发现两个英雄技能 | 0 |
| 发条先生 | Clocksworth | Double Time | 仅需 2 张合成金色，三连奖励变铸币 | 0 |
| 拉格纳罗斯 | Ragnaros the Firelord | DIE, INSECTS! | 消灭 25 个敌方随从后，每回合 +3/+3 | 0 |
| 赛弗瑞斯 | Zephrys the Great | Three Wishes | 每 3 回合许愿完美随从 | 0 |
| 玛维 | Maiev Shadowsong | Imprison | 使酒馆随从休眠 3 回合，+1/+1 | 0 |
| 尤朵拉 | Captain Eudora | Buried Treasure | 挖掘 5 次获得金色随从 | 0 |
| 苔丝 | Tess Greymane | Bob's Burgles | 刷新复制上一轮对手随从 | 0 |
| 盖尔 | Galewing | Dungar's Gryphon | 选择飞行路线获得奖励 | 0 |
| 沙德沃克 | Shudderwock | Snicker-snack | 每回合下一个战吼触发两次 | 0 |
| 塞纳留斯 | Forest Lord Cenarius | Wisdom of the Ancients | 给友方 +1/+1，连击三次 | 0 |
| 巴顿斯 | Buttons | Growing Collection | 回合开始，获得等于酒馆等级的随从 | 0 |
| 凯瑞甘 | Kerrigan, Queen of Blades | Spawning Pool | 星际联动英雄 | 0 |
| 雷诺·杰克逊 | Reno Jackson | — | 被动/主动混合 | 0 |

### 3.2 主动技能英雄

| 英雄（中文） | 英雄（英文） | 技能名 | 效果 | 消耗 | 限制 |
|------------|------------|--------|------|------|------|
| 拉法姆 | Arch-Villain Rafaam | I'll Take That! | 下回合战斗后，获得对手第一个死亡随从的复制 | 1 | 每回合 |
| 雷诺 | Reno Jackson | Gonna Be Rich! | 使一个随从变为金色（每局1次）| 0 | 每局1次 |
| 尤格-萨隆 | Yogg-Saron | Pray to Yogg! | 随机施放一个酒馆法术 | 2 | 每回合 |
| 乔治 | George the Fallen | Boon of Light | 给一个随从圣盾 | 2 | 每回合 |
| 舞王 | Dancin' Deryl | Derrick Step | 出售随从后，给一个酒馆随从 +2/+2 | 1 | 被动触发 |
| 穆坦努斯 | Mutanus | Devour | 吃掉一个友方随从，获得其属性 | 0 | 每回合 |
| 詹迪斯 | Jandice Barov | Arcane Alteration | 将一个非金色随从替换为同等级随机随从 | 0 | 每回合 |
| 巴罗夫 | Lord Barov | Friendly Wager | 下注预测下一场战斗胜负，猜对获得 3 金 | 1 | 每回合 |
| 钩牙 | Captain Hooktusk | Trash for Treasure | 移除一个随从，获得更低等级的随机随从 | 0 | 每回合 |
| 巫妖巴兹亚尔 | Lich Baz'hial | Graveyard Shift | 受到 3 伤害，获得 1 金 | 0 | 每回合 |
| 迦拉克隆 | Galakrond | Galakrond's Greed | 替换一个随从为更高等级的随从 | 1 | 每回合 |
| 沃金 | Vol'jin | Spirit Swap | 交换两个随从的属性值 | 0 | 每回合 |
| 古夫 | Guff Runetotem | Natural Balance | 使一个随从获得 +2/+2，或升级酒馆费用 -1 | 2 | 每回合 |
| 泽瑞拉 | Xyrella | Desperate Prayer | 恢复 4 生命值 | 2 | 每回合 |
| 克苏恩 | C'Thun | Saturday C'Thuns! | 回合结束，随机友方 +1/+1，每回合重复 | 2 | 每回合 |
| 玛里苟斯 | Malygos | Dragonflight | 将一个随从替换为同等级龙 | 0 | 每回合 |
| 帕奇斯 | Patches the Pirate | Fire the Cannons! | 造成 3 伤害 | 3 | 每回合 |
| 金字塔 | Pyramad | Brick by Brick | 获得一个 1/1 嘲讽 Brick | 2 | 每回合 |
| 拉卡尼休 | Rakanishu | Tip the Scales | 给一个随从 +1/+1，重复等于酒馆等级 | 1 | 每回合 |
| 天空上尉 | Skycap'n Kragg | Piggy Bank | 获得 1 金，本回合每花 1 金多 1 金 | 0 | 每回合 |
| 托奇 | Infinite Toki | Temporal Taverns | 刷新酒馆，包含一个更高等级的随从 | 1 | 每回合 |
| 亚煞极 | Y'Shaarj | Embrace Your Rage | 战斗后，获得你第一个死亡的随从 | 2 | 每回合 |
| 辛达苟萨 | Sindragosa | Stay Frosty | 冻结的酒馆随从每回合 +2/+2 | 0 | 被动冻结 |
| 穆克拉 | King Mukla | Bananarama | 获得 2 根香蕉 | 1 | 每回合 |
| 曲奇 | Cookiemonster | Stir the Pot | 消灭一个友方随从，获得 2 个其种族随从 | 0 | 每回合 |
| 加拉克苏斯 | Lord Jaraxxus | Bloodfury | 装备血怒（3攻武器）| 2 | 每回合 |
| 塔维什 | Beaststalker Tavish | Deadeye | 发现并装备一个奥术射击 | 2 | 每回合 |
| 斯卡布斯 | Scabbs Cutterbutter | Rogue's Gallery | 发现上一个对手的随从 | 0 | 每回合 |
| 普崔塞德 | Professor Putricide | Rage Potion | 给友方 +10/+10，回合结束死亡 | 0 | 每回合 |
| 塔隆 | Teron Gorefiend | Death's Defilement | 标记一个友方，其死亡时复活为全属性 | 0 | 每回合 |
| 斯尼德 | Sneed | Sneed's Replicator | 出售一个随从，其亡语触发 | 1 | 每回合 |
| 瓦尔登 | Varden Dawngrasp | Freezing Touch | 冻结 2 个酒馆随从 | 0 | 每回合 |
| 塔姆辛 | Tamsin Roame | Fragrant Phylactery | 给一个友方亡语：召唤其复制 | 0 | 每回合 |
| 阮大师 | Master Nguyen | Chi-Ji the Red Crane | 每回合随机获得一个英雄技能 | 0 | 每回合 |
| 巫妖王 | The Lich King | Reborn Rites | 给友方复生 | 1 | 每回合 |
| 伊莉斯 | Elise Starseeker | Recruitment Map | 升级后获得一张"人才地图" | 0 | 被动 |
| 芬利 | Sir Finley Mrrgglton | Adventure! | 发现一个新的英雄技能 | 0 | 每局 |
| 洛卡拉 | Loh | Grace of the Loa | 给一个随从 +1/+1，如果击杀则保留 | 0 | 每回合 |

### 3.3 战斗技能英雄

| 英雄（中文） | 英雄（英文） | 技能名 | 效果 |
|------------|------------|--------|------|
| 奥拉基尔 | Al'Akir the Windlord | SWAT, INSECTS! | 战斗开始：最左和最右随从获得风怒/圣盾/嘲讽 |
| 奈法利安 | Nefarian | Nefarious Fire | 战斗开始：对所有敌方随从造成 1 点伤害 |

### 3.4 触发技能英雄

| 英雄（中文） | 英雄（英文） | 技能名 | 效果 |
|------------|------------|--------|------|
| 希尔瓦娜斯 | Sylvanas Windrunner | Banshee's Blessing | 友方死亡时，偷取一个敌方随从的属性 |
| 瓦丝琪 | Lady Vashj | Evolving Electricity | 升级酒馆后，获得 3 张"进化"法术 |
| 鱼尔摩斯 | Murloc Holmes | Detective for Hire | 发现上一个对手战队中的一个随从 |

---

## 4. 最新英雄（Patch 34.x）

### 4.1 Patch 34.2 新增英雄

| 英雄 | 技能 | 说明 |
|------|------|------|
| Archaedas | 战吼：获得一个随机 T5 随从 | T6 中立 |
| Worgen Executive | 进击：刷新后给最右随从 +1/+1 | T2 中立 |
| Heroic Underdog | 潜行。进击：获得目标的攻击力 | T4 中立 |
| Flaming Enforcer | 回合结束，吞噬酒馆最高生命随从 | T4 恶魔/元素 |
| Spirit Drake | 复仇(3)：获得随机酒馆法术 | T4 亡灵/龙 |
| Plankwalker | 施放酒馆法术后，3个随机友方 +2/+1 | T4 亡灵/海盗 |
| Hardy Orca | 嘲讽。受伤时给其他友方 +1/+1 | T3 野兽 |
| Hunting Tiger Shark | 战吼：发现一只野兽 | T4 野兽 |
| Rabid Panther | 打出野兽后，你的野兽 +3/+3 并受1伤 | T6 野兽 |
| Aranasi Alchemist | 嘲讽，复生。亡语：酒馆随从 +1 生命 | T3 恶魔 |
| Twilight Hatchling | 亡语：召唤 3/3 雏龙并立即攻击 | T1 龙 |
| Whelp Watcher | — | T2 龙 |

### 4.2 星际联动英雄（StarCraft Crossover, Patch 34.0）

| 英雄 | 技能名 | 类型 | 效果 |
|------|--------|------|------|
| Kerrigan, Queen of Blades | Spawning Pool | 被动 | 星际虫族主题 |
| Artanis | Warp Gate | 被动 | 星际神族主题 |
| Jim Raynor | Lift Off | 被动 | 星际人族主题 |
| Exarch Othaar | Arcane Knowledge | 被动 | 星际主题 |

---

## 5. 项目当前问题与修复建议

### 5.1 当前问题

| 问题 | 严重程度 | 说明 |
|------|---------|------|
| 无护甲系统 | 🔴 严重 | 所有英雄均为 30 血，无护甲差异 |
| 英雄选择机制缺失 | 🟡 中等 | 没有每局随机提供 2/4 个英雄选择的逻辑 |
| 部分英雄仅为框架 | 🟡 中等 | 许多英雄的回调函数为空（`pass`） |
| 缺少最新英雄 | 🟡 中等 | 未包含 Patch 34.x 新增的英雄 |
| 英雄强度无分级 | 🟡 中等 | 未实现根据护甲值分级的平衡系统 |
| 英雄皮肤未过滤 | 🟢 轻微 | `cache/cards.json` 中包含大量皮肤版本 |

### 5.2 修复建议

**步骤1：实现护甲系统**
```python
@dataclass
class HeroDefinition:
    hero_id: str
    name: str
    health: int = 30
    armor: int = 0  # 新增
    power: HeroPower = None
```

**步骤2：建立英雄轮换池**
```python
class HeroRotationPool:
    """管理可用英雄和退休英雄。"""
    
    AVAILABLE_HEROES: list[str] = [
        # 当前可用的 ~70 个英雄
    ]
    
    RETIRED_HEROES: list[str] = [
        # 暂时退休的英雄
    ]
    
    def get_random_heroes(self, count: int = 2) -> list[HeroDefinition]:
        """为玩家随机选择 count 个英雄。"""
        ...
```

**步骤3：补全英雄技能实现**
- 优先实现 T0/T1 级别（高使用率）英雄的完整逻辑
- 对于复杂英雄（如阮大师、苔丝），可先标记为 `partially_implemented`

**步骤4：更新英雄数据**
- 从 `cache/cards.json` 中提取最新的英雄列表
- 过滤掉 `_SKIN_` 版本，只保留基础英雄
- 新增 Patch 34.x 的英雄

---

## 6. 相关文件

- `hsrhl/engine/hero.py` — 英雄技能系统实现
- `hsrhl/engine/tavern.py` — 酒馆阶段（英雄技能使用时机）
- `cache/cards.json` — 英雄原始数据（需过滤皮肤）
- `tests/test_hero.py` — 英雄技能测试
