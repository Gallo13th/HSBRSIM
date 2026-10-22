# POMDP Observable Features — HDT-Verified Design

## Motivation

GameValueNetwork v2 (teacher-trained) achieves avg_rank 2.00. v3 (self-play actual placements)
regresses to 2.20. The root cause is the **POMDP bottleneck**: the value network sees only
opponent HP/tier (21 dims), losing all compositional information about opponent boards.

This document defines what additional features are observable through Hearthstone Deck Tracker
(HDT) — verified against the HDT source code at `../Hearthstone-Deck-Tracker/` — and designs
the new POMDP encoding to exploit them.

## HDT Source Verification

All claims below are verified against HDT C# source (HearthSim/Hearthstone-Deck-Tracker).

### 1. Opponent Board Snapshots (Last Known Board)

**Source**: `Hearthstone Deck Tracker/Hearthstone/BattlegroundsBoardState.cs:33`
```csharp
LastKnownBoardState[playerId] = new BoardSnapshot(entities, _game.GetTurnNumber());
```

**How it works**:
- During combat, HDT reads `Power.log` which contains full entity data for ALL minions on
  both sides, including the opponent's board.
- `SnapshotCurrentBoard()` captures every minion the opponent controls (via `CONTROLLER` tag)
  with all tags: ATK, HEALTH, DIVINE_SHIELD, TAUNT, POISONOUS, REBORN, WINDFURY, VENOMOUS,
  CARD_ID, TECH_LEVEL, etc.
- The snapshot is keyed by `PLAYER_ID` and persisted across turns.
- When the player hovers over an opponent on the leaderboard, `GetBattlegroundsBoardStateFor(id)`
  retrieves the last snapshot.

**Conclusion**: Our engine can capture the opponent's full `(7, 15)` board encoding during combat,
run it through the frozen BoardEmbedder, and use the resulting 32-dim embedding as a feature.

### 2. Staleness (Turns Since Last Combat)

**Source**: `Hearthstone Deck Tracker/Controls/Overlay/Battlegrounds/BattlegroundsOpponentInfo.xaml.cs:73`
```csharp
var age = turnNumber - state.Turn;
BattlegroundsAge.Text = string.Format(LocUtil.Get("Overlay_Battlegrounds_Turns"), age);
```

**How it works**: HDT displays "X turns ago" next to each opponent's last known board.
`BoardSnapshot.Turn` records the turn when the snapshot was taken. The overlay subtracts
this from the current turn to show staleness.

**Conclusion**: We track `combat_turn` for each record and compute `staleness = current_turn - combat_turn`.

### 3. Combat Results (Win/Loss/Draw, Damage)

**Source**: `Hearthstone Deck Tracker/BobsBuddy/BobsBuddyInvoker.cs:1124-1153`
```csharp
private int GetLastCombatDamageDealt() { ... }
private CombatResult GetLastCombatResult() { ... } // Win, Loss, Tie
```

**How it works**: Bob's Buddy tracks the last attacking hero and uses its attack value as
damage dealt. Win/loss is determined by checking whether the attacking hero belongs to the
player or opponent.

**Conclusion**: We track `damage_dealt`, `damage_taken`, and `result ∈ {win, loss, draw}` for
each combat.

### 4. Opponent Leaderboard Info (Always Visible)

**Source**: Entity tags tracked by HDT's GameV2 entity system.

| Information | GameTag | Source |
|-------------|---------|--------|
| HP + Armor | HEALTH, ARMOR | Always visible on leaderboard |
| Tavern Tier | PLAYER_TECH_LEVEL | Leaderboard |
| Board size | Derived from minion count | `OpponentBoardCount` (GameV2.cs:122) |
| Triples by tier | Tracked per hero | `GetBattlegroundsHeroTriplesByTier()` (GameV2.cs:524) |
| Tavern upgrade turns | Tracked per hero | `GetBattlegroundsHeroLatestTavernUpTurn()` (GameV2.cs:504) |

**How triples tracking works** (GameV2.cs:509-521):
When a player plays a triple, HDT captures the `PLAYER_TECH_LEVEL` at that moment
and increments the counter for that tier. This tells you: "this opponent has discovered
X triples at tier N."

**How upgrade timing works** (GameV2.cs:496-501):
When an opponent's `PLAYER_TECH_LEVEL` changes, HDT records `turn → new_tier`.
This tells you: "this opponent leveled to tier 4 on turn 6" — an aggressive timing signal.

### 5. What is NOT Observable

- Opponent current board during recruit (only last-seen from combat)
- Opponent hand contents, gold, hero power status
- Opponent trinkets/quests (unless revealed through combat effects)
- Future matchmaking (who you'll fight next)

## Feature Design

### Per-Opponent Feature Vector (51 dims, shared projection → 32 → 16)

```
Group A: Combat Memory (from last fight against this opponent)
├── last_seen_board_emb (32)   BoardEmbedder(last_seen_board) — or zeros if never fought
├── staleness (1)              current_turn - combat_turn, capped at 10, /10
├── combat_result (1)          1.0 = win, 0.0 = loss, 0.5 = draw/never fought
├── damage_dealt (1)           Damage dealt to opponent, /40
├── damage_taken (1)           Damage taken from opponent, /40

Group B: Leaderboard (always visible, updated every turn)
├── hp (1)                     opponent.health / 40
├── tavern_tier (1)            opponent.tavern_tier / 7
├── armor (1)                  opponent.armor / 20
├── board_size (1)             len(living board) / 7

Group C: Power Trajectory (leaderboard hover info)
├── triples_t1..t6 (6)         Triples discovered at each tier, /3
├── upgrade_t2..t6 (5)         Turn when upgraded to tier 2-6, /30 (0 = not yet)
                               (upgrade_t1 is always turn 1, excluded)

Total: 32 + 5 + 4 + 6 + 5 = 51 dims per opponent
```

### Architecture

```
Per opponent (51 dims):
  [last_seen_emb(32) | staleness | result | dmg_dealt | dmg_taken |
   hp | tier | armor | board_size | triples×6 | upgrades×5]

    ↓ shared opp_proj: 51 → 32 → 16 (ReLU)

7 opponents → 7 × 16 → mean pool → 16 dims

Own features:
  own_board_emb (32) + own_stats (6) → own_proj → 16 + 16 = 32 dims

Global:
  turn (1) + alive_count (1) = 2 dims

Final combined: 16 (opp_pooled) + 32 (own) + 2 (global) = 50 dims → combiner MLP → 1
```

### Cold Start (Never Fought)

For opponents you haven't fought yet:
- `last_seen_board_emb` = zeros(32)
- `staleness` = 1.0 (max staleness)
- `combat_result` = 0.5 (unknown)
- `damage_dealt` = 0.0
- `damage_taken` = 0.0
- Leaderboard info is always available

### Staleness Semantics

Staleness matters because boards evolve:
- staleness = 0: just fought this turn (board is current)
- staleness = 1-3: moderately stale (some changes likely)
- staleness ≥ 5: effectively unknown (board likely entirely different)

The network learns to weight last_seen_board_emb inversely with staleness.

## Implementation Plan

1. **`hsrl/core/game.py`** — Add `combat_memory` dict to Game:
   - `self.combat_memory: dict[int, dict[int, CombatRecord]]` — player_id → opponent_id → record
   - `CombatRecord = namedtuple('CombatRecord', ['board', 'turn', 'damage_dealt', 'damage_taken', 'result'])`
   - Save records in `_run_combat()` after damage resolution
   - Track `_triples_by_tier` and `_tavern_upgrade_turns` per player

2. **`hsrl/train/game_value_sp.py`** — New POMDP encoder:
   - `encode_pomdp_state_v2()` with all new features
   - Updated `GameValueNetwork` architecture
   - Backward-compatible checkpoint format

3. **Train v4**: collect self-play data with new features → train → benchmark
