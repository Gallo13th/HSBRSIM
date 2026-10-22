# Missing Engine Features

Engine capabilities not yet implemented, ordered by impact (number of cards affected).

## P0 — High Impact (> 4 cards)

### 1. ~~TargetedAction: Tavern Domain~~ ✅ (2 cards)

~~`TargetedAction` currently only supports board (friendly) targets. Needs extension to support tavern minions as valid targets.~~

| Card ID | Card | Effect |
|---------|------|--------|
| TB_BaconShop_HP_011 | Galakrond's Greed | Choose a minion in Bob's Tavern |
| TB_BaconShop_HP_014 | Stay Frosty | Freeze a minion in Bob's Tavern |

**Done**: `TargetedAction` now takes `target_domain: str = "board"` parameter. Galakrond's Greed and Stay Frosty pass `target_domain="tavern"`. RL env exposes `target_domain` in info dict and action mask.

### 2. ~~Sequential Multi-Target Selection~~ ✅ (2 cards)

~~Some hero powers require selecting a first target, then selecting a second target based on the first.~~

| Card ID | Card | Effect |
|---------|------|--------|
| BG23_HERO_306p | Reclaimed Souls | Remove a friendly minion. Give its stats to another. |
| TB_BaconShop_HP_702t | Rune of Damnation | Give a friendly Undead +1/+1. Give another minion +1 Atk. |

**Done**: Game uses `_pending_targeted_queue` (list) instead of scalar. `action_factory` can return another `TargetedAction`, creating a chain. RL env loops through multi-target resolution.

### 3. ~~After-Play Race-Filtered Listeners~~ ✅ (4 cards)

~~Several cards trigger "After you play a {tribe}" but current engine only has generic `MINION_PLAYED` event.~~

| Card ID | Card | Trigger |
|---------|------|---------|
| BGS_004 | Wrath Weaver | After you play a Demon |
| BG20_203 | Prophet of the Boar | After you play a Quilboar |
| BG30_122 | Mrglin' Burglar | After you play a Murloc |
| BG34_321 | Rabid Panther | After you play a Beast |

**Done**: Implemented using `on_summon` → register `MINION_PLAYED` EventListener with race condition (same pattern as BreamCounterScript).

### 4. ~~Start of Game Choice (Choice Action)~~ ✅ (2 heroes × 4 variants)

~~Several hero powers require a choice at game start (not during recruit).~~

| Card ID | Card | Choice |
|---------|------|--------|
| BG22_HERO_000p | Deadeye | Choose aim direction (Left/Low/High/Right) |
| BG22_HERO_001p | Embrace Elements | Choose element (Earth/Fire/Water/Lightning) |

**Done**: Fixed `DeadeyeScript` and `EmbraceTheElementsScript` to read `HERO_POWER` tag instead of missing `card_id` attribute. Added `hero_power_overrides` to `Game.create_game()` and env-level start-of-game choice phase. Dungar's Gryphon, Azshara's Ambition, and Murloc Holmes remain as future work (more complex choice mechanics).

## P1 — Medium Impact (2-4 cards)

### 5. ~~Start of Combat Spell System~~ ✅ (2 cards)

~~Some anomalies cast spells at Start of Combat.~~

| Card ID | Card | Effect |
|---------|------|--------|
| BG27_Anomaly_301 | Sharing is Caring | SoC: Cast a tavern spell on all minions |
| BG27_Anomaly_302 | Brood of Nozdormu | SoC: Cast a tavern spell on Dragons |

**Done**: Added `CastSpellOnTarget` and `CastSpellOnAll` actions. Created `SharingIsCaringScript` and `BroodOfNozdormuScript` with SoC trigger. Added `_soc_triggered` guard to prevent double-firing.

### 6. ~~Health-as-Cost Purchase~~ ✅ (2 cards)

~~Some minions cost Health instead of Gold.~~

| Card ID | Card | Effect |
|---------|------|--------|
| BG26_352 | Leeching Felhound | Costs Health instead of Gold (Demons) |
| BG26_353 | Bazaar Dealer | Costs Health instead of Gold |

**Already implemented** (previous audit): `HEALTH_COST_DEMON` and `HEALTH_COST_SPELL` tags with Eleventh Hour damage prevention.

### 7. ~~Avenge System~~ ✅ (3+ cards)

~~"Avenge (X):" triggers after X friendly minions die.~~

| Card ID | Card | Avenge |
|---------|------|--------|
| BG21_HERO_030p | Broodmother | Avenge (3): Get a minion |
| BG24_HERO_100p | Avatar of N'Zoth | Avenge (3): Get a random Deathrattle minion |
| BG31_HERO_802pt1 | Carrier | Avenge (1): Get an Interceptor |

**Already implemented** (previous audit): Avenge counter tracking with per-entity death-count-then-reset pattern. Event listener with counter + reset on trigger.

### 8. ~~Overflow / Board-Full Mechanic~~ ✅ (1 card)

~~When a minion can't be summoned because the board is full.~~

| Card ID | Card | Effect |
|---------|------|--------|
| BG30_MagicItem_438t | Mug of the Sire | Overflow → +5 Atk to all |

**Done**: `MINION_OVERFLOW` event broadcast in both `summon()` and `play_minion()`. MugOfTheSireScript listener handles the buff.

## P2 — Low Impact (1-2 cards)

### 9. ~~Spell-Target on-Minion Triggers~~ ✅

~~When a spell targets a specific minion (not board-wide), trigger effects on that minion.~~

| Card ID | Card | Trigger |
|---------|------|---------|
| BG26_528 | Pufferquil | When targeted by a spell |
| BG34_926 | Batty Terrorguard | When a tavern spell is cast on this |

**Done**: `TargetedAction.do()` broadcasts `SPELL_CAST_ON_MINION` when source is a spell and target is a minion. Trinket listeners (`OnSpellCastOnMinionBuffScript`, `LorewalkerScrollLesserScript`, `LorewalkerScrollGreaterScript`) receive the event.

### 10. ~~Consume/Fodder System~~ ✅ (1 card)

~~"Consume" (Fodder) mechanic: minion in tavern is consumed to buff another.~~

| Card ID | Card | Effect |
|---------|------|--------|
| BG35_333 | Consummate Conqueror | Battlecry: Consume a minion in the Tavern |

**Already implemented** (previous audit): `FodderConsume` action with tavern-targeted consumption.

## To Be Verified (Future Work)

Features that may need engine support but haven't been verified:

| Feature | Cards | Notes |
|---------|-------|-------|
| Dungar's Gryphon choice | BG20_HERO_283p | Quest choice at game start (needs quest pool selection) |
| Azshara's Ambition choice | BG22_HERO_007p | Spell school choice (needs spell school tags) |
| Murloc Holmes choice | BG24_HERO_100p | Guess opponent minion (complex UI/strategy) |
| Golden Discover at turn X | BG27_Anomaly_559 etc. | Needs golden discover variant of DiscoverMinion |

## Implemented During Audit

| Feature | Cards Fixed | Description |
|---------|-------------|-------------|
| TargetedAction (friendly board) | 13 HP | Hero powers now use TargetedAction for board minion targeting |
| TargetedAction (tavern domain) | 2 HP | Galakrond's Greed, Stay Frosty support tavern targeting |
| Sequential multi-target | 2 HP | Reclaimed Souls, Rune of Damnation two-stage selection |
| Race-filtered MINION_PLAYED | 4 minions | Wrath Weaver, Prophet of Boar, Mrglin' Burglar, Rabid Panther |
| SoC spell casting | 2 anomalies | Sharing is Caring, Brood of Nozdormu with CastSpellOnAll |
| SPELL_CAST_ON_MINION broadcast | 3 trinkets | Broadcast in TargetedAction.do() for spell-on-minion listeners |
| MINION_OVERFLOW in play_minion | 1 trinket | Mug of the Sire overflow fix |
| Start-of-game choice (env) | 2 heroes | Deadeye, Embrace Elements variant selection |
| HERO_POWER tag fix | 2 heroes | DeadeyeScript, EmbraceTheElementsScript now read HERO_POWER tag |
| Token spell scripts | 2 | Spare Part, Windfury+DS get proper TargetedAction scripts |
| Protoss minions registered | 5 | Warp Gate now correctly filters Protoss minions |
| Mama/Papa Mrrglton counters | 2 | Split MRRGLTON_COUNT into MAMA_MRRGLTON_COUNT and PAPA_MRRGLTON_COUNT |
| Temporal Tavern higher tier | 1 | Added missing higher-tier minion to Temporal Tavern hero power |
