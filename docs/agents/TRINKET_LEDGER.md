# 饰品迁移台账 — 基线 36.2.2 (S14)

来源: `CardDB.trinket_offer_pool()`（商店可提供集，排除 BG30_Trinket_* 内部 token
与有同名本体的 t/t2 升级变体）∩/∖ `hsrl2.scripts.REGISTRY`。
（自动生成: `python tools/generate_trinket_ledger.py`）

商店可提供: 331；已注册: **316**；未注册: **15**；商店池覆盖率 95%

全域（含 token/升级变体）: 饰品类 379 张，已注册 324 张

档位: spell_school 11 = Lesser (T6 档)，12 = Greater (T9 档)。
数值一律 `CardDef.num(i)`；金色 = `db.golden_version(def)`；随机走 `game.rng`；
二态铁律: CORRECT 或 DEFERRED 撤注册（SOP §6b）。

## 未注册明细（派发源；每 20 张一片）

### 片 1: BG30_MagicItem_402 … BG36_MagicItem_373（15 张）

| id | 档 | 关联卡 | 名称 | 文本 |
|----|----|--------|------|------|
| `BG30_MagicItem_402` | 12 | Snarling Conductor | Conductor Portrait | [x]Get a Snarling Conductor. Whenever you discard a card, this plays a <b>Blood Gem</b> on all your minions. |
| `BG30_MagicItem_416` | 11 | — | Token of the Old Gods | [x]<b>Spellcraft:</b> Choose a minion. Then choose a minion from a Tier higher to transform it into. |
| `BG30_MagicItem_431` | 12 | Living Azerite | Azerite Portrait | [x]Get a Living Azerite. Your Living Azerites also give stats to friendly Elementals. |
| `BG30_MagicItem_707` | 11 | — | Tickatus Sticker | [x]<b>Discover</b> a Tier 3 Darkmoon Prize. At the start of every three turns, repeat this. <i>({0} \|4(turn, turns) left!)</i> |
| `BG30_MagicItem_711` | 11 | — | Marine Signet | [x]After you play 4 minions, get a random Tier {1} Tavern spell and improve this. <i>({0} left!)</i>@[x]After you play 4 minions, get a random Tier {1} Tavern spell. |
| `BG30_MagicItem_994` | 11 | — | Yogg-Tastic Pastry | Spin the Wheel of Yogg-Saron. At the start of each turn, spin it again. |
| `BG32_MagicItem_300` | 11 | — | Putricide Sticker | [x]Craft a custom Undead. At the start of every 2 turns, repeat this. <i>({0} \|4(turn, turns) left!)</i> |
| `BG32_MagicItem_806` | 11 | Battlecruiser | Battlecruiser Portrait | [x]Get an 12/12 Battlecruiser. Whenever the Tavern is <b>Refreshed</b>, add a Battlecruiser Upgrade to it. |
| `BG32_MagicItem_809` | 11 | — | Gem Donation | [x]The first minion you sell each turn plays its <b>Blood Gems</b> on the 3 highest-Tier minions in the Tavern. |
| `BG32_MagicItem_823` | 11 | — | Wax Imprinter | [x]Gain 2 Gold and take 2 damage. At the start of each turn, repeat this <i>(if possible)</i>. |
| `BG35_MagicItem_812` | 12 | Triple Prize | Corrupted Tome | Get a Triple Prize. Whenever you would get a Triple Reward, get a Triple Prize instead. |
| `BG35_MagicItem_820` | 12 | Ice Block | Safety Patch | Cast Ice Block. Gain {0} Gold. |
| `BG35_MagicItem_823` | 11 | — | Timeworn Candelabra | <b>Discover</b> a 2-Cost minion from the Minor <b>Timewarp</b>. |
| `BG35_MagicItem_921` | 11 | — | Cowrie Necklace | Tavern spells that give stats cost (2) less. |
| `BG36_MagicItem_373` | 12 | — | Multilayered Shield | [x]Your Tavern spells give an extra +{0}/+{1}. <i>(Improved by each different friendly minion type!)</i> |

