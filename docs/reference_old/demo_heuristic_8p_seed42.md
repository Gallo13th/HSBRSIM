# 8-Player Battlegrounds — All Heuristic Demo

**Seed**: 42  |  **Max Turns**: 8  |  **Agents**: 8× Greedy Q-Score Heuristic

> ⚠ **Audit note**: This demo uses a simplified auto-play strategy that does NOT use
> hero powers, spells, freezes, or positioning. It is an engine smoke test, not a
> faithful recreation of real player behavior. Combat logs show actual engine combat.
> No anomaly is active in this game. Trinkets are offered on Turns 6 and 9.


## Players

| # | Hero | HP | Armor | Tier |
|---|---|---|---|---|
| 1 | Yogg-Saron, Hope's End | 30 | 18 | 1 |
| 2 | Sneed | 30 | 12 | 1 |
| 3 | Overlord Saurfang | 30 | 18 | 1 |
| 4 | Ysera | 30 | 12 | 1 |
| 5 | Inge, the Iron Hymn | 30 | 12 | 1 |
| 6 | Professor Putricide | 30 | 10 | 1 |
| 7 | Sylvanas Windrunner | 30 | 10 | 1 |
| 8 | Drek'Thar | 30 | 12 | 1 |

---

## Game Log

### Turn 1

**Yogg-Saron, Hope's End**  HP=30 Armor=18 Gold=3 Tier=1

  Board: (empty)
  Tavern: Manasaber 4/1 T1 $3 | Risen Rider 2/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Evolving Strategy (spell) T1 $3

  → Board after: 4/1
  → Bought | Gold: 3→0

**Sneed**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Ominous Seer 2/1 T1 $3 | Picky Eater 1/1 T1 $3 | Picky Eater 1/1 T1 $3 | Rime or Reason (spell) T1 $3

  → Board after: 2/1
  → Bought | Gold: 3→0

**Overlord Saurfang**  HP=30 Armor=18 Gold=3 Tier=1

  Board: (empty)
  Tavern: Surf n' Surf 2/2 T1 $3 | Surf n' Surf 2/2 T1 $3 | Wrath Weaver 2/5 T1 $3 | Fortify (spell) T1 $1

  → Board after: 2/5
  → Bought | Gold: 3→0

**Ysera**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Picky Eater 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Slimy Shield (spell) T1 $3 | Scarlet Survivor 3/3 T1 $3

  → Board after: 3/3
  → Bought | Gold: 3→0

**Inge, the Iron Hymn**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Harmless Bonehead 1/1 T1 $3 | Picky Eater 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Tavern Dish Banana (spell) T1 $1

  → Board after: 4/1
  → Bought | Gold: 3→0

**Professor Putricide**  HP=30 Armor=10 Gold=3 Tier=1

  Board: (empty)
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Ominous Seer 2/1 T1 $3 | Cord Puller 1/1 T1 $3 | Sick Riffs (spell) T1 $3

  → Board after: 1/2 [Taunt,DS]
  → Bought | Gold: 3→0

**Sylvanas Windrunner**  HP=30 Armor=10 Gold=3 Tier=1

  Board: (empty)
  Tavern: Manasaber 4/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Ominous Seer 2/1 T1 $3 | Slumber Sorcerer's Spellcraft (spell) T1 $0

  → Board after: 4/1
  → Bought | Gold: 3→0

**Drek'Thar**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Risen Rider 2/1 T1 $3 | Picky Eater 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Undersea Mount (spell) T1 $3

  → Board after: 2/1 [Taunt,Reborn]
  → Bought | Gold: 3→0

**⚔ Combat Phase**

  ⚡ Ysera vs Sneed (first: Ysera)
     Ysera: [3/3]
     Sneed: [2/1]
     ⚔ Scarlet Survivor 3/3→3/1  🛡 Ominous Seer 2/1→2/0 💀
     🏁 survivors: 1 vs 0 — winner: Ysera
  ⚡ Yogg-Saron, Hope's End vs Drek'Thar (first: Yogg-Saron, Hope's End)
     Yogg-Saron, Hope's End: [4/1]
     Drek'Thar: [2/1]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Risen Rider 2/1→2/0 💀
     🏁 survivors: 0 vs 0 — winner: draw
  ⚡ Inge, the Iron Hymn vs Overlord Saurfang (first: Overlord Saurfang)
     Inge, the Iron Hymn: [4/1]
     Overlord Saurfang: [2/5]
     ⚔ Wrath Weaver 2/5→2/1  🛡 Manasaber 4/1→4/0 💀
     🏁 survivors: 0 vs 1 — winner: Overlord Saurfang
  ⚡ Sylvanas Windrunner vs Professor Putricide (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [4/1]
     Professor Putricide: [1/2]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Annoy-o-Tron 1/2→1/2
     🏁 survivors: 0 vs 1 — winner: Professor Putricide

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=18, Tier=1) | Sneed (HP=30, Armor=10, Tier=1) | Overlord Saurfang (HP=30, Armor=18, Tier=1) | Ysera (HP=30, Armor=12, Tier=1) | Inge, the Iron Hymn (HP=30, Armor=10, Tier=1) | Professor Putricide (HP=30, Armor=10, Tier=1) | Sylvanas Windrunner (HP=30, Armor=8, Tier=1) | Drek'Thar (HP=30, Armor=12, Tier=1)

### Turn 2

**Yogg-Saron, Hope's End**  HP=30 Armor=18 Gold=4 Tier=1

  Board: 4/1
  Tavern: Ominous Seer 2/1 T1 $3 | Manasaber 4/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Accelerator (spell) T1 $3

  → Board after: 4/1, 4/1
  → Gold: 4→0

**Sneed**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 2/1
  Tavern: Picky Eater 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Manasaber 4/1 T1 $3 | Meditation (spell) T1 $3

  → Board after: 2/1, 1/4
  → Bought | Gold: 4→0

**Overlord Saurfang**  HP=30 Armor=18 Gold=4 Tier=1

  Board: 2/5
  Tavern: Harmless Bonehead 4/4 T1 $3 | Surf n' Surf 4/4 T1 $3 | Harmless Bonehead 4/4 T1 $3 | The Goldenizer (spell) T1 $0

  → Board after: 2/5, 4/4
  → Bought | Gold: 4→0

**Ysera**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 3/3
  Tavern: Wrath Weaver 1/4 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Risen Rider 2/1 T1 $3 | Windfury + Divine Shield (spell) T1 $3 | Twilight Hatchling 1/1 T1 $3

  → Board after: 3/3, 1/4
  → Bought | Gold: 4→0

**Inge, the Iron Hymn**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 4/1
  Tavern: Manasaber 4/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Surf n' Surf 1/1 T1 $3 | Angler's Lure (spell) T1 $3

  → Board after: 4/1, 4/1
  → Gold: 4→0

**Professor Putricide**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 1/2 [Taunt,DS]
  Tavern: Ominous Seer 2/1 T1 $3 | Ominous Seer 2/1 T1 $3 | Risen Rider 2/1 T1 $3 | Banana (spell) T1 $0

  → Board after: 1/2 [Taunt,DS], 2/1
  → Bought | Gold: 4→0

**Sylvanas Windrunner**  HP=30 Armor=8 Gold=4 Tier=1

  Board: 4/1
  Tavern: Wrath Weaver 1/4 T1 $3 | Manasaber 4/1 T1 $3 | Risen Rider 2/1 T1 $3 | Tavern Coin (spell) T1 $1

  → Board after: 4/1, 1/4
  → Bought | Gold: 4→0

**Drek'Thar**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 2/1 [Taunt,Reborn]
  Tavern: Harmless Bonehead 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Spare Part (spell) T1 $3

  → Board after: 2/1 [Taunt,Reborn], 1/2 [Taunt,DS]
  → Bought | Gold: 4→0

**⚔ Combat Phase**

  ⚡ Ysera vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Ysera: [3/3, 1/4]
     Inge, the Iron Hymn: [4/1, 4/1]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Scarlet Survivor 3/3→3/0 💀
     ⚔ Wrath Weaver 1/4→1/0 💀  🛡 Manasaber 4/1→4/0 💀
     🏁 survivors: 0 vs 0 — winner: draw
  ⚡ Overlord Saurfang vs Drek'Thar (first: Drek'Thar)
     Overlord Saurfang: [2/5, 4/4]
     Drek'Thar: [2/1, 1/2]
     ⚔ Risen Rider 2/1→2/0 💀  🛡 Harmless Bonehead 4/4→4/2
     ⚔ Wrath Weaver 2/5→2/4  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Annoy-o-Tron 1/2→1/0 💀  🛡 Wrath Weaver 2/4→2/3
     🏁 survivors: 2 vs 0 — winner: Overlord Saurfang
  ⚡ Professor Putricide vs Yogg-Saron, Hope's End (first: Professor Putricide)
     Professor Putricide: [1/2, 2/1]
     Yogg-Saron, Hope's End: [4/1, 4/1]
     ⚔ Annoy-o-Tron 1/2→1/2  🛡 Manasaber 4/1→4/0 💀
     ⚔ Manasaber 4/1→4/0 💀  🛡 Annoy-o-Tron 1/2→1/0 💀
     🏁 survivors: 1 vs 0 — winner: Professor Putricide
  ⚡ Sylvanas Windrunner vs Sneed (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [4/1, 1/4]
     Sneed: [2/1, 1/4]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Wrath Weaver 1/4→1/0 💀
     ⚔ Ominous Seer 2/1→2/0 💀  🛡 Wrath Weaver 1/4→1/2
     🏁 survivors: 1 vs 0 — winner: Sylvanas Windrunner

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=16, Tier=1) | Sneed (HP=30, Armor=8, Tier=1) | Overlord Saurfang (HP=30, Armor=18, Tier=1) | Ysera (HP=30, Armor=12, Tier=1) | Inge, the Iron Hymn (HP=30, Armor=10, Tier=1) | Professor Putricide (HP=30, Armor=10, Tier=1) | Sylvanas Windrunner (HP=30, Armor=8, Tier=1) | Drek'Thar (HP=30, Armor=9, Tier=1)

### Turn 3

**Yogg-Saron, Hope's End**  HP=30 Armor=16 Gold=5 Tier=1

  Board: 4/1, 4/1
  Tavern: Manasaber 4/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Picky Eater 1/1 T1 $3 | Copy Non-Golden (spell) T1 $3

  → Board after: 8/2 [G], 6/5
  → ⬆ Upgrade T1→T2 | Bought | Gold: 5→0

**Sneed**  HP=30 Armor=8 Gold=5 Tier=1

  Board: 2/1, 1/4
  Tavern: Harmless Bonehead 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Surf n' Surf 1/1 T1 $3 | Temporary Golden Touch (spell) T1 $3

  → Board after: 2/1, 3/6, 1/4
  → ⬆ Upgrade T1→T2 | Gold: 5→0 | Armor: 8→7

**Overlord Saurfang**  HP=30 Armor=18 Gold=5 Tier=1

  Board: 2/5, 4/4
  Tavern: Risen Rider 7/6 T1 $3 | Cord Puller 6/6 T1 $3 | Wrath Weaver 6/9 T1 $3 | Enchanted Lasso (spell) T1 $2

  → Board after: 4/7, 4/4, 6/9
  → ⬆ Upgrade T1→T2 | Gold: 5→0 | Armor: 18→17

**Ysera**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 3/3, 1/4
  Tavern: Risen Rider 2/1 T1 $3 | Risen Rider 2/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Glowing Crown (spell) T1 $3 | Scarlet Survivor 3/3 T1 $3

  → Board after: 3/3, 1/4, 3/3
  → ⬆ Upgrade T1→T2 | Gold: 5→0

**Inge, the Iron Hymn**  HP=30 Armor=10 Gold=5 Tier=1

  Board: 4/1, 4/1
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Wrath Weaver 1/4 T1 $3 | Cord Puller 1/1 T1 $3 | Tavern Coin (spell) T1 $3

  → Board after: 4/1, 4/1, 1/4
  → ⬆ Upgrade T1→T2 | Bought | Gold: 5→0

**Professor Putricide**  HP=30 Armor=10 Gold=5 Tier=1

  Board: 1/2 [Taunt,DS], 2/1
  Tavern: Cord Puller 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Cord Puller 1/1 T1 $3 | Meditation (spell) T1 $3

  → Board after: 1/2 [Taunt,DS], 2/1, 1/1 [DS]
  → ⬆ Upgrade T1→T2 | Bought | Gold: 5→0

**Sylvanas Windrunner**  HP=30 Armor=8 Gold=5 Tier=1

  Board: 4/1, 1/4
  Tavern: Risen Rider 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Crab Mount (spell) T1 $3

  → Board after: 4/1, 3/6, 1/4
  → ⬆ Upgrade T1→T2 | Gold: 5→0 | Armor: 8→7

**Drek'Thar**  HP=30 Armor=9 Gold=5 Tier=1

  Board: 2/1 [Taunt,Reborn], 1/2 [Taunt,DS]
  Tavern: Manasaber 4/1 T1 $3 | Picky Eater 1/1 T1 $3 | Ominous Seer 2/1 T1 $3

  → Board after: 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 4/1
  → ⬆ Upgrade T1→T2 | Bought | Gold: 5→0

**⚔ Combat Phase**

  ⚡ Yogg-Saron, Hope's End vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Yogg-Saron, Hope's End: [8/2, 6/5]
     Inge, the Iron Hymn: [4/1, 4/1, 1/4]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Manasaber 8/2→8/0 💀
     ⚔ Lucifron 6/5→6/1  🛡 Manasaber 4/1→4/0 💀
     ⚔ Wrath Weaver 1/4→1/0 💀  🛡 Lucifron 6/1→6/0 💀
     🏁 survivors: 0 vs 0 — winner: draw
  ⚡ Drek'Thar vs Sylvanas Windrunner (first: Sylvanas Windrunner)
     Drek'Thar: [2/1, 1/2, 4/1]
     Sylvanas Windrunner: [4/1, 3/6, 1/4]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Risen Rider 2/1→2/0 💀  🛡 Wrath Weaver 1/4→1/2
     ⚔ Wrath Weaver 3/6→3/5  🛡 Annoy-o-Tron 1/2→1/0 💀
     ⚔ Manasaber 4/1→4/0 💀  🛡 Wrath Weaver 3/5→3/1
     🏁 survivors: 0 vs 2 — winner: Sylvanas Windrunner
  ⚡ Ysera vs Professor Putricide (first: Ysera)
     Ysera: [3/3, 1/4, 3/3]
     Professor Putricide: [1/2, 2/1, 1/1]
     ⚔ Scarlet Survivor 3/3→3/2  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Annoy-o-Tron 1/2→1/0 💀  🛡 Scarlet Survivor 3/2→3/1
     ⚔ Wrath Weaver 1/4→1/3  🛡 Cord Puller 1/1→1/1
     ⚔ Ominous Seer 2/1→2/0 💀  🛡 Scarlet Survivor 3/1→3/0 💀
     ⚔ Scarlet Survivor 3/3→3/2  🛡 Cord Puller 1/1→1/0 💀
     🏁 survivors: 2 vs 0 — winner: Ysera
  ⚡ Sneed vs Overlord Saurfang (first: Sneed)
     Sneed: [2/1, 3/6, 1/4]
     Overlord Saurfang: [4/7, 4/4, 6/9]
     ⚔ Ominous Seer 2/1→2/0 💀  🛡 Wrath Weaver 4/7→4/5
     ⚔ Wrath Weaver 4/5→4/2  🛡 Wrath Weaver 3/6→3/2
     ⚔ Wrath Weaver 3/2→3/0 💀  🛡 Wrath Weaver 6/9→6/6
     ⚔ Harmless Bonehead 4/4→4/3  🛡 Wrath Weaver 1/4→1/0 💀
     🏁 survivors: 0 vs 3 — winner: Overlord Saurfang

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=16, Tier=2) | Sneed (HP=30, Armor=2, Tier=2) | Overlord Saurfang (HP=30, Armor=17, Tier=2) | Ysera (HP=30, Armor=12, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=10, Tier=2) | Professor Putricide (HP=30, Armor=6, Tier=2) | Sylvanas Windrunner (HP=30, Armor=7, Tier=2) | Drek'Thar (HP=30, Armor=5, Tier=2)

### Turn 4

**Yogg-Saron, Hope's End**  HP=30 Armor=16 Gold=6 Tier=2

  Board: 8/2 [G], 6/5
  Tavern: Eternal Knight 4/2 T2 $3 | Sewer Rat 3/2 T2 $3 | Sewer Rat 3/2 T2 $3 | Tide Raiser 2/1 T2 $3 | Hasty Excavation (spell) T2 $3

  → Board after: 8/2 [G], 6/5, 4/2, 3/2
  → Bought | Gold: 6→0

**Sneed**  HP=30 Armor=2 Gold=6 Tier=2

  Board: 2/1, 3/6, 1/4
  Tavern: Tide Raiser 2/1 T2 $3 | Tide Raiser 2/1 T2 $3 | Alert Alarmist 2/2 T2 $3 | Cord Puller 1/1 T1 $3 | Chef's Choice (spell) T2 $2

  → Board after: 2/1, 3/6, 1/4, 2/2 [Taunt], 2/1 [Taunt]
  → Bought | Gold: 6→0

**Overlord Saurfang**  HP=30 Armor=17 Gold=6 Tier=2

  Board: 4/7, 4/4, 6/9
  Tavern: Ominous Seer 9/8 T1 $3 | Old Soul 10/11 T2 $3 | Humming Bird 8/11 T2 $3 | Sewer Rat 10/9 T2 $3 | Strike Oil (spell) T2 $3

  → Board after: 4/7, 4/4, 6/9, 10/11, 8/11
  → Bought | Gold: 6→0

**Ysera**  HP=30 Armor=12 Gold=6 Tier=2

  Board: 3/3, 1/4, 3/3
  Tavern: Eternal Knight 4/2 T2 $3 | Eternal Knight 4/2 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Shell Collector 4/3 T2 $3 | Leaf Through the Pages (spell) T2 $1 | Scarlet Survivor 3/3 T1 $3

  → Board after: 3/3, 3/6, 3/3, 3/4, 4/3
  → Bought | Gold: 6→0 | Armor: 12→11

**Inge, the Iron Hymn**  HP=30 Armor=10 Gold=6 Tier=2

  Board: 4/1, 4/1, 1/4
  Tavern: Soul Rewinder 4/1 T2 $3 | Alert Alarmist 2/2 T2 $3 | Scarlet Skull 2/1 T2 $3 | Annoy-o-Tron 1/2 T1 $3 | Search Through Time (spell) T2 $2

  → Board after: 4/1, 4/1, 3/6, 4/1, 2/2 [Taunt]
  → Bought | Gold: 6→0 | Armor: 10→9

**Professor Putricide**  HP=30 Armor=6 Gold=6 Tier=2

  Board: 1/2 [Taunt,DS], 2/1, 1/1 [DS]
  Tavern: Tide Raiser 2/1 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Might of Stormwind (spell) T2 $2

  → Board after: 1/2 [Taunt,DS], 2/1, 1/1 [DS], 3/4, 3/4
  → Bought | Gold: 6→0

**Sylvanas Windrunner**  HP=30 Armor=7 Gold=6 Tier=2

  Board: 4/1, 3/6, 1/4
  Tavern: Manasaber 4/1 T1 $3 | Humming Bird 1/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Laboratory Assistant 3/4 T2 $3

  → Board after: 4/1, 5/8, 3/6, 3/4, 4/1
  → Bought | Gold: 6→0 | Armor: 7→5

**Drek'Thar**  HP=30 Armor=5 Gold=6 Tier=2

  Board: 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 4/1
  Tavern: Picky Eater 1/1 T1 $3 | Cord Puller 1/1 T1 $3 | Ancestral Automaton 3/4 T2 $3 | Old Soul 3/4 T2 $3

  → Board after: 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 4/1, 3/4, 3/4
  → Bought | Gold: 6→0

**⚔ Combat Phase**

  ⚡ Overlord Saurfang vs Sylvanas Windrunner (first: Overlord Saurfang)
     Overlord Saurfang: [4/7, 4/4, 6/9, 10/11, 9/11]
     Sylvanas Windrunner: [4/1, 5/8, 3/6, 3/4, 4/1]
     ⚔ Wrath Weaver 4/7→4/2  🛡 Wrath Weaver 5/8→5/4
     ⚔ Manasaber 4/1→4/0 💀  🛡 Old Soul 10/11→10/7
     ⚔ Harmless Bonehead 4/4→4/0 💀  🛡 Wrath Weaver 5/4→5/0 💀
     ⚔ Wrath Weaver 3/6→3/0 💀  🛡 Humming Bird 9/11→9/8
     ⚔ Wrath Weaver 6/9→6/5  🛡 Manasaber 4/1→4/0 💀
     ⚔ Laboratory Assistant 3/4→3/0 💀  🛡 Humming Bird 9/8→9/5
     🏁 survivors: 4 vs 0 — winner: Overlord Saurfang
  ⚡ Yogg-Saron, Hope's End vs Drek'Thar (first: Drek'Thar)
     Yogg-Saron, Hope's End: [8/2, 6/5, 4/2, 3/2]
     Drek'Thar: [2/1, 1/2, 4/1, 3/4, 3/4]
     ⚔ Risen Rider 2/1→2/0 💀  🛡 Eternal Knight 4/2→5/0 💀
     ⚔ Manasaber 8/2→8/1  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Annoy-o-Tron 1/2→1/0 💀  🛡 Sewer Rat 3/2→3/1
     ⚔ Lucifron 6/5→6/2  🛡 Old Soul 3/4→3/0 💀
     ⚔ Manasaber 4/1→4/0 💀  🛡 Sewer Rat 3/1→3/0 💀
     🏁 survivors: 2 vs 1 — winner: Yogg-Saron, Hope's End
  ⚡ Inge, the Iron Hymn vs Professor Putricide (first: Professor Putricide)
     Inge, the Iron Hymn: [4/1, 4/1, 3/6, 4/1, 2/2]
     Professor Putricide: [1/2, 2/1, 1/1, 3/4, 3/4]
     ⚔ Annoy-o-Tron 1/2→1/2  🛡 Alert Alarmist 2/2→2/1
     ⚔ Manasaber 4/1→4/0 💀  🛡 Annoy-o-Tron 1/2→1/0 💀
     ⚔ Ominous Seer 2/1→2/0 💀  🛡 Alert Alarmist 2/1→2/0 💀
     ⚔ Manasaber 4/1→4/0 💀  🛡 Cord Puller 1/1→1/1
     ⚔ Cord Puller 1/1→1/0 💀  🛡 Wrath Weaver 3/6→3/5
     ⚔ Wrath Weaver 3/5→3/2  🛡 Laboratory Assistant 3/4→3/1
     ⚔ Laboratory Assistant 3/1→3/0 💀  🛡 Soul Rewinder 4/1→4/0 💀
     🏁 survivors: 1 vs 1 — winner: Inge, the Iron Hymn
  ⚡ Sneed vs Ysera (first: Sneed)
     Sneed: [2/1, 3/6, 1/4, 2/2, 2/1]
     Ysera: [3/3, 3/6, 3/3, 3/4, 4/3]
     ⚔ Ominous Seer 2/1→2/0 💀  🛡 Scarlet Survivor 3/3→3/1
     ⚔ Scarlet Survivor 3/1→3/0 💀  🛡 Tide Raiser 2/1→2/0 💀
     ⚔ Wrath Weaver 3/6→3/3  🛡 Wrath Weaver 3/6→3/3
     ⚔ Wrath Weaver 3/3→3/0 💀  🛡 Alert Alarmist 3/4→3/1
     ⚔ Wrath Weaver 1/4→1/1  🛡 Scarlet Survivor 3/3→3/2
     ⚔ Scarlet Survivor 3/2→3/0 💀  🛡 Alert Alarmist 3/1→3/0 💀
     🏁 survivors: 2 vs 2 — winner: Sneed

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=16, Tier=2) | Sneed (HP=30, Armor=2, Tier=2) | Overlord Saurfang (HP=30, Armor=17, Tier=2) | Ysera (HP=30, Armor=11, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=9, Tier=2) | Professor Putricide (HP=30, Armor=6, Tier=2) | Drek'Thar (HP=30, Armor=5, Tier=2) | Sylvanas Windrunner (HP=27, Armor=0, Tier=2)

### Turn 5

**Yogg-Saron, Hope's End**  HP=30 Armor=16 Gold=7 Tier=2

  Board: 8/2 [G], 6/5, 5/2, 3/2
  Tavern: Humming Bird 1/4 T2 $3 | Harmless Bonehead 1/1 T1 $3 | Metallic Hunter 4/2 T2 $3 | Alert Alarmist 2/2 T2 $3 | Tavern Coin (spell) T1 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**Sneed**  HP=30 Armor=2 Gold=7 Tier=2

  Board: 2/1, 3/6, 1/4, 2/2 [Taunt], 2/1 [Taunt]
  Tavern: Nerubian Deathswarmer 1/4 T2 $3 | Ominous Seer 2/1 T1 $3 | Ancestral Automaton 3/4 T2 $3 | Reef Riffer 3/2 T2 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**Overlord Saurfang**  HP=30 Armor=17 Gold=7 Tier=2

  Board: 4/7, 4/4, 6/9, 10/11, 8/11
  Tavern: Shell Collector 15/14 T2 $3 | Humming Bird 12/15 T2 $3 | Humming Bird 12/15 T2 $3 | Manasaber 15/12 T1 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**Ysera**  HP=30 Armor=11 Gold=7 Tier=2

  Board: 3/3, 3/6, 3/3, 3/4, 4/3
  Tavern: Metallic Hunter 4/2 T2 $3 | Cord Puller 1/1 T1 $3 | Scarlet Skull 2/1 T2 $3 | Metallic Hunter 4/2 T2 $3 | Sleepy Supporter 4/3 T2 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**Inge, the Iron Hymn**  HP=30 Armor=9 Gold=7 Tier=2

  Board: 4/1, 4/1, 3/6, 4/1, 2/2 [Taunt]
  Tavern: Lava Lurker 2/5 T2 $3 | Shell Collector 4/3 T2 $3 | Old Soul 3/4 T2 $3 | Tide Raiser 2/1 T2 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**Professor Putricide**  HP=30 Armor=6 Gold=7 Tier=2

  Board: 1/2 [Taunt,DS], 2/1, 1/1 [DS], 3/4, 3/4
  Tavern: Eternal Knight 4/2 T2 $3 | Shell Collector 4/3 T2 $3 | Lava Lurker 2/5 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**Sylvanas Windrunner**  HP=27 Armor=0 Gold=7 Tier=2

  Board: 4/1, 5/8, 3/6, 3/4, 4/1
  Tavern: Soul Rewinder 4/1 T2 $3 | Eternal Knight 4/2 T2 $3 | Alert Alarmist 2/2 T2 $3 | Harmless Bonehead 1/1 T1 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**Drek'Thar**  HP=30 Armor=5 Gold=7 Tier=2

  Board: 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 4/1, 3/4, 3/4
  Tavern: Soul Rewinder 4/1 T2 $3 | Old Soul 3/4 T2 $3 | Metallic Hunter 4/2 T2 $3 | Ominous Seer 2/1 T1 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**⚔ Combat Phase**

  ⚡ Professor Putricide vs Drek'Thar (first: Drek'Thar)
     Professor Putricide: [1/2, 2/1, 1/1, 3/4, 3/4]
     Drek'Thar: [2/1, 1/2, 4/1, 3/4, 3/4]
     ⚔ Risen Rider 2/1→2/0 💀  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Annoy-o-Tron 1/2→1/1  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Annoy-o-Tron 1/2→1/1  🛡 Annoy-o-Tron 1/1→1/0 💀
     ⚔ Ominous Seer 2/1→2/0 💀  🛡 Annoy-o-Tron 1/1→1/0 💀
     ⚔ Manasaber 4/1→4/0 💀  🛡 Laboratory Assistant 3/4→3/0 💀
     ⚔ Cord Puller 1/1→1/1  🛡 Ancestral Automaton 3/4→3/3
     ⚔ Ancestral Automaton 3/3→3/2  🛡 Cord Puller 1/1→1/0 💀
     ⚔ Laboratory Assistant 3/4→3/1  🛡 Old Soul 3/4→3/1
     ⚔ Old Soul 3/1→3/0 💀  🛡 Laboratory Assistant 3/1→3/0 💀
     🏁 survivors: 0 vs 1 — winner: Drek'Thar
  ⚡ Inge, the Iron Hymn vs Ysera (first: Ysera)
     Inge, the Iron Hymn: [4/1, 4/1, 3/6, 4/1, 2/2]
     Ysera: [3/3, 3/6, 3/3, 3/4, 4/3]
     ⚔ Scarlet Survivor 3/3→3/1  🛡 Alert Alarmist 2/2→2/0 💀
     ⚔ Manasaber 4/1→4/0 💀  🛡 Wrath Weaver 3/6→3/2
     ⚔ Wrath Weaver 3/2→3/0 💀  🛡 Manasaber 4/1→4/0 💀
     ⚔ Wrath Weaver 3/6→3/3  🛡 Scarlet Survivor 3/3→3/0 💀
     ⚔ Laboratory Assistant 3/4→3/0 💀  🛡 Soul Rewinder 4/1→4/0 💀
     🏁 survivors: 1 vs 2 — winner: Inge, the Iron Hymn
  ⚡ Overlord Saurfang vs Yogg-Saron, Hope's End (first: Overlord Saurfang)
     Overlord Saurfang: [4/7, 4/4, 6/9, 10/11, 9/11]
     Yogg-Saron, Hope's End: [8/2, 6/5, 5/2, 3/2]
     ⚔ Wrath Weaver 4/7→4/2  🛡 Eternal Knight 5/2→6/0 💀
     ⚔ Manasaber 8/2→8/0 💀  🛡 Wrath Weaver 6/9→6/1
     ⚔ Harmless Bonehead 4/4→4/0 💀  🛡 Lucifron 6/5→6/1
     ⚔ Lucifron 6/1→6/0 💀  🛡 Old Soul 10/11→10/5
     ⚔ Wrath Weaver 6/1→6/0 💀  🛡 Sewer Rat 3/2→3/0 💀
     🏁 survivors: 3 vs 0 — winner: Overlord Saurfang
  ⚡ Sneed vs Sylvanas Windrunner (first: Sylvanas Windrunner)
     Sneed: [2/1, 3/6, 1/4, 2/2, 2/1]
     Sylvanas Windrunner: [4/1, 5/8, 3/6, 3/4, 4/1]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Tide Raiser 2/1→2/0 💀
     ⚔ Ominous Seer 2/1→2/0 💀  🛡 Wrath Weaver 5/8→5/6
     ⚔ Wrath Weaver 5/6→5/3  🛡 Alert Alarmist 3/4→3/0 💀
     ⚔ Wrath Weaver 3/6→3/3  🛡 Wrath Weaver 3/6→3/3
     ⚔ Wrath Weaver 3/3→3/2  🛡 Wrath Weaver 1/4→1/1
     ⚔ Wrath Weaver 1/1→1/0 💀  🛡 Wrath Weaver 5/3→5/2
     ⚔ Laboratory Assistant 3/4→3/1  🛡 Wrath Weaver 3/3→3/0 💀
     🏁 survivors: 0 vs 4 — winner: Sylvanas Windrunner

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=8, Tier=3) | Overlord Saurfang (HP=30, Armor=17, Tier=3) | Ysera (HP=30, Armor=11, Tier=3) | Inge, the Iron Hymn (HP=30, Armor=9, Tier=3) | Professor Putricide (HP=30, Armor=1, Tier=3) | Drek'Thar (HP=30, Armor=5, Tier=3) | Sylvanas Windrunner (HP=27, Armor=0, Tier=3) | Sneed (HP=24, Armor=0, Tier=3)

### Turn 6

**Yogg-Saron, Hope's End**  HP=30 Armor=8 Gold=8 Tier=3

  Board: 8/2 [G], 6/5, 6/2, 3/2
  Tavern: Leeching Felhound 3/3 T3 $3 | Deflect-o-Bot 3/2 T3 $3 | Handless Forsaken 2/1 T3 $3 | Deflect-o-Bot 3/2 T3 $3

  → Board after: 8/2 [G], 6/5, 6/2, 3/2, 3/3, 3/2 [DS], 3/2 [DS]
  → Bought | 💍 Got trinket: Beetle Band | Gold: 8→0 | Armor: 8→5

**Sneed**  HP=24 Armor=0 Gold=8 Tier=3

  Board: 2/1, 3/6, 1/4, 2/2 [Taunt], 2/1 [Taunt]
  Tavern: Soul Rewinder 4/1 T2 $3 | Annoy-o-Module 2/4 T3 $3 | Technical Element 5/6 T3 $3 | Alert Alarmist 2/2 T2 $3

  → Board after: 5/8, 3/6, 2/2 [Taunt], 2/1 [Taunt], 5/6, 2/4 [Taunt,DS], 4/1
  → Bought | Sold | 💍 Got trinket: Shadowy Elixir | Gold: 8→0 | Armor: 0→2

**Overlord Saurfang**  HP=30 Armor=17 Gold=8 Tier=3

  Board: 4/7, 4/4, 6/9, 10/11, 8/11
  Tavern: Leeching Felhound 14/14 T3 $3 | Cadaver Caretaker 14/14 T3 $3 | Picky Eater 12/12 T1 $3 | Alert Alarmist 13/13 T2 $3

  → Board after: 10/13, 13/11, 8/11, 17/14, 14/14, 13/13 [Taunt], 12/12
  → Bought | Sold | 💍 Got trinket: Artisanal Urn | Gold: 8→0 | Armor: 17→11

**Ysera**  HP=30 Armor=11 Gold=8 Tier=3

  Board: 3/3, 3/6, 3/3, 3/4, 4/3
  Tavern: Laboratory Assistant 3/4 T2 $3 | Humming Bird 1/4 T2 $3 | Sly Raptor 1/3 T3 $3 | Hardy Orca 1/6 T3 $3 | Amber Guardian 3/2 T3 $3

  → Board after: 5/8, 3/3, 3/4, 4/3, 3/4, 1/6 [Taunt], 1/4
  → Bought | 💍 Got trinket: Shadowy Elixir | Gold: 8→0 | Armor: 11→14

**Inge, the Iron Hymn**  HP=30 Armor=9 Gold=8 Tier=3

  Board: 4/1, 4/1, 3/6, 4/1, 2/2 [Taunt]
  Tavern: Deflect-o-Bot 3/2 T3 $3 | Ancestral Automaton 3/4 T2 $3 | Deep Blue Crooner 2/2 T3 $3 | Accord-o-Tron 3/3 T3 $3

  → Board after: 4/1, 4/1, 3/6, 4/1, 2/2 [Taunt], 3/4, 3/3
  → Bought | 💍 Got trinket: Implicator Portrait | Gold: 8→0

**Professor Putricide**  HP=30 Armor=1 Gold=8 Tier=3

  Board: 1/2 [Taunt,DS], 2/1, 1/1 [DS], 3/4, 3/4
  Tavern: Accord-o-Tron 3/3 T3 $3 | Humming Bird 1/4 T2 $3 | Cadaver Caretaker 3/3 T3 $3 | Sprightly Scarab 3/1 T3 $3

  → Board after: 1/2 [Taunt,DS], 2/1, 1/1 [DS], 7/8, 3/4, 3/3, 3/3
  → Bought | 💍 Got trinket: Rewinder Portrait | Gold: 8→0

**Sylvanas Windrunner**  HP=27 Armor=0 Gold=8 Tier=3

  Board: 4/1, 5/8, 3/6, 3/4, 4/1
  Tavern: Soul Rewinder 4/1 T2 $3 | Shell Collector 4/3 T2 $3 | Alert Alarmist 2/2 T2 $3 | Cadaver Caretaker 3/3 T3 $3

  → Board after: 4/1, 5/8, 3/6, 3/4, 4/1, 4/3, 3/3
  → Bought | 💍 Got trinket: Implicator Portrait | Gold: 8→0

**Drek'Thar**  HP=30 Armor=5 Gold=8 Tier=3

  Board: 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 4/1, 3/4, 3/4
  Tavern: Deflect-o-Bot 3/2 T3 $3 | Deflect-o-Bot 3/2 T3 $3 | Deep-Sea Angler 2/3 T3 $3 | Shell Collector 4/3 T2 $3

  → Board after: 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 4/1, 3/4, 3/4, 4/3, 3/2 [DS]
  → Bought | 💍 Got trinket: Deathly Phylactery | Gold: 8→0

**⚔ Combat Phase**

  ⚡ Overlord Saurfang vs Drek'Thar (first: Overlord Saurfang)
     Overlord Saurfang: [10/13, 13/11, 9/11, 17/14, 14/14, 13/13, 12/12]
     Drek'Thar: [2/1, 1/2, 4/1, 3/4, 3/4, 4/3, 3/2]
     ⚔ Wrath Weaver 10/13→10/12  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Risen Rider 2/1→2/0 💀  🛡 Alert Alarmist 13/13→13/11
     ⚔ Old Soul 13/11→13/10  🛡 Annoy-o-Tron 1/2→1/0 💀
     ⚔ Manasaber 4/1→4/0 💀  🛡 Alert Alarmist 13/11→13/7
     ⚔ Humming Bird 9/11→9/8  🛡 Deflect-o-Bot 3/2→3/2
     ⚔ Ancestral Automaton 3/4→3/0 💀  🛡 Alert Alarmist 13/7→13/4
     ⚔ Cadaver Caretaker 17/14→17/10  🛡 Shell Collector 4/3→4/0 💀
     ⚔ Old Soul 3/4→3/0 💀  🛡 Alert Alarmist 13/4→13/1
     ⚔ Leeching Felhound 14/14→14/11  🛡 Deflect-o-Bot 3/2→3/0 💀
     🏁 survivors: 7 vs 0 — winner: Overlord Saurfang
  ⚡ Sylvanas Windrunner vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Sylvanas Windrunner: [4/1, 5/8, 3/6, 3/4, 4/1, 4/3, 3/3]
     Inge, the Iron Hymn: [4/1, 4/1, 3/6, 4/1, 2/2, 3/4, 3/3]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Cadaver Caretaker 3/3→3/0 💀
     ⚔ Manasaber 4/1→4/0 💀  🛡 Alert Alarmist 2/2→2/0 💀
     ⚔ Manasaber 4/1→4/0 💀  🛡 Wrath Weaver 3/6→3/2
     ⚔ Wrath Weaver 5/8→5/5  🛡 Accord-o-Tron 3/3→3/0 💀
     ⚔ Wrath Weaver 3/6→3/2  🛡 Manasaber 4/1→4/0 💀
     ⚔ Wrath Weaver 3/2→3/0 💀  🛡 Soul Rewinder 4/1→4/0 💀
     ⚔ Ancestral Automaton 3/4→3/0 💀  🛡 Wrath Weaver 5/5→5/2
     ⚔ Laboratory Assistant 3/4→3/1  🛡 Wrath Weaver 3/2→3/0 💀
     🏁 survivors: 3 vs 0 — winner: Sylvanas Windrunner
  ⚡ Yogg-Saron, Hope's End vs Professor Putricide (first: Professor Putricide)
     Yogg-Saron, Hope's End: [8/2, 6/5, 6/2, 3/2, 3/3, 3/2, 3/2]
     Professor Putricide: [1/2, 2/1, 1/1, 7/8, 3/4, 3/3, 3/3]
     ⚔ Annoy-o-Tron 1/2→1/2  🛡 Deflect-o-Bot 3/2→3/2
     ⚔ Manasaber 8/2→8/1  🛡 Annoy-o-Tron 1/2→1/0 💀
     ⚔ Ominous Seer 2/1→2/0 💀  🛡 Eternal Knight 6/2→7/0 💀
     ⚔ Lucifron 6/5→6/2  🛡 Accord-o-Tron 3/3→3/0 💀
     ⚔ Cord Puller 1/1→1/1  🛡 Manasaber 8/1→8/0 💀
     ⚔ Sewer Rat 3/2→3/0 💀  🛡 Laboratory Assistant 3/4→3/1
     ⚔ Laboratory Assistant 7/8→7/5  🛡 Leeching Felhound 3/3→3/0 💀
     ⚔ Deflect-o-Bot 3/2→3/0 💀  🛡 Laboratory Assistant 3/1→3/0 💀
     ⚔ Cadaver Caretaker 3/3→3/0 💀  🛡 Deflect-o-Bot 3/2→3/2
     ⚔ Deflect-o-Bot 3/2→3/0 💀  🛡 Laboratory Assistant 7/5→7/2
     🏁 survivors: 1 vs 2 — winner: Yogg-Saron, Hope's End
  ⚡ Sneed vs Ysera (first: Sneed)
     Sneed: [5/8, 3/6, 2/2, 2/1, 5/6, 2/4, 4/1]
     Ysera: [5/8, 3/3, 3/4, 4/3, 3/4, 2/6, 2/4]
     ⚔ Wrath Weaver 5/8→5/6  🛡 Hardy Orca 2/6→2/1
     ⚔ Wrath Weaver 5/8→5/6  🛡 Alert Alarmist 2/2→2/0 💀
     ⚔ Wrath Weaver 3/6→3/4  🛡 Hardy Orca 2/1→2/0 💀
     ⚔ Scarlet Survivor 3/3→3/1  🛡 Annoy-o-Module 2/4→2/4
     ⚔ Tide Raiser 2/1→2/0 💀  🛡 Humming Bird 2/4→2/2
     ⚔ Laboratory Assistant 3/4→3/2  🛡 Annoy-o-Module 2/4→2/1
     ⚔ Technical Element 5/6→5/1  🛡 Wrath Weaver 5/6→5/1
     ⚔ Shell Collector 4/3→4/1  🛡 Annoy-o-Module 2/1→2/0 💀
     ⚔ Soul Rewinder 4/1→4/0 💀  🛡 Shell Collector 4/1→4/0 💀
     ⚔ Laboratory Assistant 3/4→3/0 💀  🛡 Wrath Weaver 4/6→4/3
     🏁 survivors: 3 vs 4 — winner: Sneed

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=5, Tier=3) | Overlord Saurfang (HP=30, Armor=11, Tier=3) | Ysera (HP=30, Armor=14, Tier=3) | Inge, the Iron Hymn (HP=30, Armor=1, Tier=3) | Professor Putricide (HP=30, Armor=1, Tier=3) | Sylvanas Windrunner (HP=27, Armor=0, Tier=3) | Drek'Thar (HP=25, Armor=0, Tier=3) | Sneed (HP=24, Armor=2, Tier=3)

### Turn 7

**Yogg-Saron, Hope's End**  HP=30 Armor=5 Gold=9 Tier=3

  Board: 8/2 [G], 6/5, 7/2, 3/2, 3/3, 3/2 [DS], 3/2 [DS]
  Tavern: Hardy Orca 1/6 T3 $3 | Mummifier 5/2 T3 $3 | Deep Blue Crooner 2/2 T3 $3 | Sewer Rat 3/2 T2 $3 | Tavern Coin (spell) T1 $3

  → Board after: 8/2 [G], 6/5, 7/2, 3/3, 3/2 [DS], 3/2 [DS], 1/6 [Taunt]
  → ⬆ Upgrade T3→T4 | Bought | Sold | Gold: 9→0

**Sneed**  HP=24 Armor=2 Gold=9 Tier=3

  Board: 5/8, 3/6, 2/2 [Taunt], 2/1 [Taunt], 5/6, 2/4 [Taunt,DS], 4/1
  Tavern: Deep Blue Crooner 2/2 T3 $3 | Sly Raptor 1/3 T3 $3 | Deflect-o-Bot 3/2 T3 $3 | Surf n' Surf 1/1 T1 $3

  → Board after: 5/8, 3/6, 2/2 [Taunt], 5/6, 2/4 [Taunt,DS], 4/1, 3/2 [DS]
  → ⬆ Upgrade T3→T4 | Bought | Sold | Gold: 9→0

**Overlord Saurfang**  HP=30 Armor=11 Gold=9 Tier=3

  Board: 10/13, 13/11, 8/11, 17/14, 14/14, 13/13 [Taunt], 12/12
  Tavern: Deflect-o-Bot 19/18 T3 $3 | Sly Raptor 17/19 T3 $3 | Cadaver Caretaker 22/19 T3 $3 | Risen Rider 21/17 T1 $3

  → Board after: 10/13, 13/11, 17/14, 14/14, 13/13 [Taunt], 12/12, 22/19
  → ⬆ Upgrade T3→T4 | Sold | Gold: 9→0

**Ysera**  HP=30 Armor=14 Gold=9 Tier=3

  Board: 5/8, 3/3, 3/4, 4/3, 3/4, 1/6 [Taunt], 1/4
  Tavern: Handless Forsaken 2/1 T3 $3 | False Implicator 1/1 T3 $3 | Accord-o-Tron 3/3 T3 $3 | Deep Blue Crooner 2/2 T3 $3 | Sleepy Supporter 4/3 T2 $3

  → Board after: 5/8, 3/3, 3/4, 4/3, 3/4, 1/6 [Taunt], 4/3
  → ⬆ Upgrade T3→T4 | Bought | Sold | Gold: 9→0

**Inge, the Iron Hymn**  HP=30 Armor=1 Gold=10 Tier=3

  Board: 4/1, 4/1, 3/6, 4/1, 2/2 [Taunt], 3/4, 3/3
  Tavern: Old Soul 3/4 T2 $3 | Dustbone Devastator 2/6 T3 $3 | Ancestral Automaton 3/4 T2 $3 | Mummifier 5/2 T3 $3

  → Board after: 4/1, 3/6, 4/1, 3/4, 3/3, 2/6, 3/4
  → ⬆ Upgrade T3→T4 | Bought | Sold | Gold: 10→0

**Professor Putricide**  HP=30 Armor=1 Gold=10 Tier=3

  Board: 1/2 [Taunt,DS], 2/1, 1/1 [DS], 7/8, 3/4, 3/3, 3/3
  Tavern: Dustbone Devastator 2/6 T3 $3 | Cord Puller 1/1 T1 $3 | Accord-o-Tron 3/3 T3 $3 | Handless Forsaken 2/1 T3 $3

  → Board after: 2/1, 7/8, 3/4, 3/3, 3/3, 2/6, 3/3
  → ⬆ Upgrade T3→T4 | Bought | Sold | Gold: 10→0

**Sylvanas Windrunner**  HP=27 Armor=0 Gold=9 Tier=3

  Board: 4/1, 5/8, 3/6, 3/4, 4/1, 4/3, 3/3
  Tavern: Sprightly Scarab 3/1 T3 $3 | Reef Riffer 3/2 T2 $3 | Technical Element 5/6 T3 $3 | Nerubian Deathswarmer 1/4 T2 $3

  → Board after: 5/8, 3/6, 3/4, 4/1, 4/3, 3/3, 5/6
  → ⬆ Upgrade T3→T4 | Bought | Gold: 9→0

**Drek'Thar**  HP=25 Armor=0 Gold=9 Tier=3

  Board: 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 4/1, 3/4, 3/4, 4/3, 3/2 [DS]
  Tavern: Floating Watcher 4/4 T3 $5 | Cord Puller 1/1 T1 $3 | Deep Blue Crooner 2/2 T3 $3 | Shell Collector 4/3 T2 $3

  → Board after: 1/2 [Taunt,DS], 4/1, 3/4, 3/4, 4/3, 3/2 [DS], 4/3
  → ⬆ Upgrade T3→T4 | Sold | Gold: 9→0

**⚔ Combat Phase**

  ⚡ Drek'Thar vs Ysera (first: Drek'Thar)
     Drek'Thar: [1/2, 4/1, 3/4, 3/4, 4/3, 3/2, 4/3]
     Ysera: [5/8, 3/3, 3/4, 4/3, 3/4, 1/6, 4/3]
     ⚔ Annoy-o-Tron 1/2→1/2  🛡 Hardy Orca 1/6→1/5
     ⚔ Wrath Weaver 5/8→5/7  🛡 Annoy-o-Tron 1/2→1/0 💀
     ⚔ Manasaber 4/1→4/0 💀  🛡 Hardy Orca 1/5→1/1
     ⚔ Scarlet Survivor 3/3→3/0 💀  🛡 Old Soul 3/4→3/1
     ⚔ Ancestral Automaton 3/4→3/3  🛡 Hardy Orca 1/1→1/0 💀
     ⚔ Laboratory Assistant 3/4→3/0 💀  🛡 Shell Collector 4/3→4/0 💀
     ⚔ Old Soul 3/1→3/0 💀  🛡 Shell Collector 4/3→4/0 💀
     ⚔ Laboratory Assistant 3/4→3/1  🛡 Ancestral Automaton 3/3→3/0 💀
     ⚔ Shell Collector 4/3→4/0 💀  🛡 Sleepy Supporter 4/3→4/0 💀
     🏁 survivors: 1 vs 2 — winner: Drek'Thar
  ⚡ Professor Putricide vs Sneed (first: Sneed)
     Professor Putricide: [2/1, 7/8, 3/4, 3/3, 3/3, 2/6, 3/3]
     Sneed: [5/8, 3/6, 2/2, 5/6, 2/4, 4/1, 3/2]
     ⚔ Wrath Weaver 5/8→5/5  🛡 Accord-o-Tron 3/3→3/0 💀
     ⚔ Ominous Seer 2/1→2/0 💀  🛡 Alert Alarmist 2/2→2/0 💀
     ⚔ Wrath Weaver 3/6→3/4  🛡 Dustbone Devastator 2/6→2/3
     ⚔ Laboratory Assistant 7/8→7/6  🛡 Annoy-o-Module 2/4→2/4
     ⚔ Technical Element 5/6→5/3  🛡 Accord-o-Tron 3/3→3/0 💀
     ⚔ Laboratory Assistant 3/4→3/2  🛡 Annoy-o-Module 2/4→2/1
     ⚔ Annoy-o-Module 2/1→2/0 💀  🛡 Cadaver Caretaker 3/3→3/1
     ⚔ Cadaver Caretaker 3/1→3/0 💀  🛡 Wrath Weaver 5/5→5/2
     ⚔ Soul Rewinder 4/1→4/0 💀  🛡 Dustbone Devastator 2/3→2/0 💀
     🏁 survivors: 2 vs 4 — winner: Professor Putricide
  ⚡ Yogg-Saron, Hope's End vs Sylvanas Windrunner (first: Sylvanas Windrunner)
     Yogg-Saron, Hope's End: [8/2, 6/5, 7/2, 3/3, 3/2, 3/2, 1/6]
     Sylvanas Windrunner: [5/8, 3/6, 3/4, 4/1, 4/3, 3/3, 5/6]
     ⚔ Wrath Weaver 5/8→5/7  🛡 Hardy Orca 1/6→1/1
     ⚔ Manasaber 8/2→8/0 💀  🛡 Technical Element 5/6→5/0 💀
     ⚔ Wrath Weaver 3/6→3/5  🛡 Hardy Orca 1/1→1/0 💀
     ⚔ Lucifron 6/5→6/1  🛡 Manasaber 4/1→4/0 💀
     ⚔ Laboratory Assistant 3/4→3/0 💀  🛡 Lucifron 6/1→6/0 💀
     ⚔ Eternal Knight 7/2→8/0 💀  🛡 Cadaver Caretaker 3/3→3/0 💀
     ⚔ Shell Collector 4/3→4/0 💀  🛡 Deflect-o-Bot 3/2→3/2
     ⚔ Leeching Felhound 3/3→3/0 💀  🛡 Wrath Weaver 3/5→3/2
     🏁 survivors: 2 vs 2 — winner: Yogg-Saron, Hope's End
  ⚡ Inge, the Iron Hymn vs Overlord Saurfang (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 3/6, 4/1, 3/4, 3/3, 2/6, 3/4]
     Overlord Saurfang: [10/13, 13/11, 17/14, 14/14, 13/13, 12/12, 22/19]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Alert Alarmist 13/13→13/9
     ⚔ Wrath Weaver 10/13→10/9  🛡 Soul Rewinder 4/1→4/0 💀
     ⚔ Wrath Weaver 3/6→3/0 💀  🛡 Alert Alarmist 13/9→13/6
     ⚔ Old Soul 13/11→13/8  🛡 Old Soul 3/4→3/0 💀
     ⚔ Ancestral Automaton 3/4→3/0 💀  🛡 Alert Alarmist 13/6→13/3
     ⚔ Cadaver Caretaker 17/14→17/12  🛡 Dustbone Devastator 2/6→2/0 💀
     ⚔ Accord-o-Tron 3/3→3/0 💀  🛡 Alert Alarmist 13/3→13/0 💀
     🏁 survivors: 0 vs 6 — winner: Overlord Saurfang

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=5, Tier=4) | Overlord Saurfang (HP=30, Armor=11, Tier=4) | Ysera (HP=30, Armor=14, Tier=4) | Professor Putricide (HP=30, Armor=1, Tier=4) | Sylvanas Windrunner (HP=27, Armor=0, Tier=4) | Drek'Thar (HP=25, Armor=0, Tier=4) | Sneed (HP=24, Armor=2, Tier=4) | Inge, the Iron Hymn (HP=21, Armor=0, Tier=4)

### Turn 8

**Yogg-Saron, Hope's End**  HP=30 Armor=5 Gold=10 Tier=4

  Board: 8/2 [G], 6/5, 8/2, 3/3, 3/2 [DS], 3/2 [DS], 1/6 [Taunt]
  Tavern: Handless Forsaken 2/1 T3 $3 | Seafloor Recruiter 3/5 T4 $3 | Alert Alarmist 2/2 T2 $3 | Plaguerunner 4/2 T4 $3 | Abyssal Bruiser 1/1 T4 $3 | Misplaced Tea Set (spell) T4 $2

  → Board after: 8/2 [G], 6/5, 8/2, 1/6 [Taunt], 3/5, 4/2, 1/1 [DS]
  → Bought | Sold | Gold: 10→0

**Sneed**  HP=24 Armor=2 Gold=10 Tier=4

  Board: 5/8, 3/6, 2/2 [Taunt], 5/6, 2/4 [Taunt,DS], 4/1, 3/2 [DS]
  Tavern: Humming Bird 1/4 T2 $3 | Woodland Defiler 5/6 T4 $3 | Dustbone Devastator 2/6 T3 $3 | Laboratory Assistant 3/4 T2 $3 | Rimescale Priestess 3/3 T4 $3 | Shifting Tide (spell) T4 $1

  → Board after: 9/12, 7/10, 5/6, 5/6, 2/6, 3/4, 1/4
  → Bought | Sold | Gold: 10→0 | HP: 24→20 | Armor: 2→0

**Overlord Saurfang**  HP=30 Armor=11 Gold=10 Tier=4

  Board: 10/13, 13/11, 17/14, 14/14, 13/13 [Taunt], 12/12, 22/19
  Tavern: Malchezaar, Prince of Dance 23/22 T4 $3 | Rylak Metalhead 23/21 T4 $3 | Holo Rover 22/22 T4 $3 | Deep Blue Crooner 20/20 T3 $3 | Leeching Felhound 21/21 T3 $3 | Tavern Coin (spell) T1 $3

  → Board after: 22/19, 23/22, 23/21 [Taunt], 22/22 [DS], 21/21, 20/20, 25/27
  → Bought | Sold | Gold: 10→0 | Armor: 11→8

**Ysera**  HP=30 Armor=14 Gold=10 Tier=4

  Board: 5/8, 3/3, 3/4, 4/3, 3/4, 1/6 [Taunt], 4/3
  Tavern: Floating Watcher 4/4 T3 $5 | Woodland Defiler 5/6 T4 $3 | Handless Forsaken 2/1 T3 $3 | Humming Bird 1/4 T2 $3 | Floating Watcher 4/4 T3 $5 | Boon of Beetles (spell) T4 $1 | Roaring Recruiter 2/8 T3 $3

  → Board after: 9/12, 1/6 [Taunt], 4/3, 5/6, 2/8, 8/8, 1/4
  → Bought | Sold | Gold: 10→0 | Armor: 14→10

**Inge, the Iron Hymn**  HP=21 Armor=0 Gold=11 Tier=4

  Board: 4/1, 3/6, 4/1, 3/4, 3/3, 2/6, 3/4
  Tavern: Sly Raptor 1/3 T3 $3 | False Implicator 1/1 T3 $3 | Wyvern Outrider 2/8 T4 $3 | Rylak Metalhead 5/3 T4 $3 | Auto Assembler 2/2 T4 $3 | Conflagration (spell) T4 $2

  → Board after: 5/8, 3/4, 2/6, 3/4, 2/8, 5/3 [Taunt], 2/2 [G]
  → Bought | Sold | Gold: 11→0 | HP: 21→20

**Professor Putricide**  HP=30 Armor=1 Gold=12 Tier=4

  Board: 2/1, 7/8, 3/4, 3/3, 3/3, 2/6, 3/3
  Tavern: Malchezaar, Prince of Dance 5/4 T4 $3 | Risen Rider 2/1 T1 $3 | Waverider 2/8 T4 $3 | Metallic Hunter 4/2 T2 $3 | Shell Collector 4/3 T2 $3 | Arcane Absorption (spell) T4 $1

  → Board after: 7/8, 3/4, 2/6, 2/8, 5/4, 4/3, 4/1
  → Bought | Sold | Gold: 12→0

**Sylvanas Windrunner**  HP=27 Armor=0 Gold=10 Tier=4

  Board: 5/8, 3/6, 3/4, 4/1, 4/3, 3/3, 5/6
  Tavern: Rimescale Priestess 3/3 T4 $3 | Cadaver Caretaker 3/3 T3 $3 | Deflect-o-Bot 3/2 T3 $3 | Imposing Percussionist 4/4 T4 $3 | Flaming Enforcer 4/5 T4 $3 | Natural Blessing (spell) T4 $4

  → Board after: 9/12, 7/10, 4/3, 5/6, 4/5, 4/4, 3/2 [DS]
  → Bought | Sold | Gold: 10→0 | HP: 27→20

**Drek'Thar**  HP=25 Armor=0 Gold=10 Tier=4

  Board: 1/2 [Taunt,DS], 4/1, 3/4, 3/4, 4/3, 3/2 [DS], 4/3
  Tavern: Friendly Geist 6/3 T4 $3 | Floating Watcher 4/4 T3 $5 | Marquee Ticker 3/7 T4 $3 | Rimescale Priestess 3/3 T4 $3 | Waverider 2/8 T4 $3 | Eonar's Favor (spell) T4 $2

  → Board after: 3/4, 4/3, 4/3, 3/7, 2/8, 6/3, 4/4
  → Bought | Sold | Gold: 10→0

**⚔ Combat Phase**

  ⚡ Sneed vs Sylvanas Windrunner (first: Sylvanas Windrunner)
     Sneed: [9/12, 7/10, 5/6, 5/6, 2/6, 3/4, 2/4]
     Sylvanas Windrunner: [9/12, 7/10, 4/3, 5/6, 4/5, 4/4, 3/2]
     ⚔ Wrath Weaver 9/12→9/5  🛡 Wrath Weaver 7/10→7/1
     ⚔ Wrath Weaver 9/12→9/8  🛡 Shell Collector 4/3→4/0 💀
     ⚔ Wrath Weaver 7/10→7/3  🛡 Wrath Weaver 7/1→7/0 💀
     ⚔ Technical Element 5/6→5/1  🛡 Technical Element 5/6→5/1
     ⚔ Technical Element 5/1→5/0 💀  🛡 Wrath Weaver 9/8→9/3
     ⚔ Woodland Defiler 5/6→5/3  🛡 Deflect-o-Bot 3/2→3/2
     ⚔ Flaming Enforcer 4/5→4/0 💀  🛡 Technical Element 5/1→5/0 💀
     ⚔ Dustbone Devastator 2/6→3/2  🛡 Imposing Percussionist 4/4→4/2
     ⚔ Imposing Percussionist 4/2→4/0 💀  🛡 Wrath Weaver 9/3→9/0 💀
     ⚔ Laboratory Assistant 3/4→3/0 💀  🛡 Wrath Weaver 9/5→9/2
     ⚔ Deflect-o-Bot 3/2→3/0 💀  🛡 Humming Bird 2/4→2/1
     ⚔ Humming Bird 2/1→2/0 💀  🛡 Wrath Weaver 7/3→7/1
     🏁 survivors: 2 vs 2 — winner: Sneed
  ⚡ Yogg-Saron, Hope's End vs Inge, the Iron Hymn (first: Yogg-Saron, Hope's End)
     Yogg-Saron, Hope's End: [8/2, 6/5, 8/2, 1/6, 3/5, 4/2, 1/1]
     Inge, the Iron Hymn: [5/8, 3/4, 2/6, 3/4, 2/8, 5/3, 2/2]
     ⚔ Manasaber 8/2→8/0 💀  🛡 Rylak Metalhead 5/3→5/0 💀
     ⚔ Wrath Weaver 5/8→5/7  🛡 Hardy Orca 1/6→1/1
     ⚔ Lucifron 6/5→6/0 💀  🛡 Wrath Weaver 5/7→5/1
     ⚔ Ancestral Automaton 3/4→3/3  🛡 Hardy Orca 1/1→1/0 💀
     ⚔ Eternal Knight 8/2→9/0 💀  🛡 Old Soul 3/4→3/0 💀
     ⚔ Dustbone Devastator 2/6→3/2  🛡 Plaguerunner 4/2→7/0 💀
     ⚔ Seafloor Recruiter 3/5→3/3  🛡 Wyvern Outrider 2/8→2/5
     ⚔ Wyvern Outrider 2/5→2/4  🛡 Abyssal Bruiser 1/5→1/5
     ⚔ Abyssal Bruiser 1/5→1/2  🛡 Ancestral Automaton 3/3→3/2
     ⚔ False Implicator 2/2→2/0 💀  🛡 Seafloor Recruiter 3/3→3/1
     🏁 survivors: 2 vs 4 — winner: Yogg-Saron, Hope's End
  ⚡ Overlord Saurfang vs Professor Putricide (first: Professor Putricide)
     Overlord Saurfang: [22/19, 23/22, 23/21, 22/22, 21/21, 20/20, 25/27]
     Professor Putricide: [7/8, 3/4, 2/6, 2/8, 5/4, 4/3, 4/1]
     ⚔ Laboratory Assistant 7/8→7/0 💀  🛡 Rylak Metalhead 23/21→23/14
     ⚔ Cadaver Caretaker 22/19→22/16  🛡 Laboratory Assistant 3/4→3/0 💀
     ⚔ Dustbone Devastator 2/6→3/0 💀  🛡 Rylak Metalhead 23/14→23/12
     ⚔ Malchezaar, Prince of Dance 23/22→23/18  🛡 Soul Rewinder 4/1→4/0 💀
     ⚔ Waverider 2/8→2/0 💀  🛡 Rylak Metalhead 23/12→23/10
     ⚔ Rylak Metalhead 23/10→23/5  🛡 Malchezaar, Prince of Dance 5/4→5/0 💀
     ⚔ Shell Collector 4/3→4/0 💀  🛡 Rylak Metalhead 23/5→23/1
     🏁 survivors: 7 vs 0 — winner: Overlord Saurfang
  ⚡ Drek'Thar vs Ysera (first: Drek'Thar)
     Drek'Thar: [3/4, 4/3, 4/3, 3/7, 2/8, 6/3, 4/4]
     Ysera: [9/12, 2/6, 4/3, 5/6, 2/8, 8/8, 2/4]
     ⚔ Old Soul 3/4→3/2  🛡 Hardy Orca 2/6→2/3
     ⚔ Wrath Weaver 9/12→9/8  🛡 Floating Watcher 4/4→4/0 💀
     ⚔ Shell Collector 4/3→4/1  🛡 Hardy Orca 2/3→2/0 💀
     ⚔ Sleepy Supporter 4/3→5/1  🛡 Old Soul 3/2→3/0 💀
     ⚔ Shell Collector 4/3→4/0 💀  🛡 Sleepy Supporter 5/1→5/0 💀
     ⚔ Woodland Defiler 6/7→6/3  🛡 Shell Collector 4/1→4/0 💀
     ⚔ Marquee Ticker 3/7→3/5  🛡 Humming Bird 2/4→2/1
     ⚔ Roaring Recruiter 2/8→3/7  🛡 Waverider 2/8→2/6
     ⚔ Waverider 2/6→2/4  🛡 Humming Bird 2/1→2/0 💀
     ⚔ Floating Watcher 8/8→8/2  🛡 Friendly Geist 6/3→6/0 💀
     🏁 survivors: 2 vs 4 — winner: Drek'Thar

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=5, Tier=4) | Overlord Saurfang (HP=30, Armor=8, Tier=4) | Ysera (HP=30, Armor=10, Tier=4) | Drek'Thar (HP=25, Armor=0, Tier=4) | Sneed (HP=20, Armor=0, Tier=4) | Inge, the Iron Hymn (HP=20, Armor=0, Tier=4) | Sylvanas Windrunner (HP=20, Armor=0, Tier=4) | Professor Putricide (HP=16, Armor=0, Tier=4)

---

## Final Standings

| # | Hero | HP | Armor | Alive | Eliminated Turn |
|---|---|---|---|---|
| 1 | Yogg-Saron, Hope's End | 30 | 5 | Yes | — |
| 2 | Overlord Saurfang | 30 | 8 | Yes | — |
| 3 | Ysera | 30 | 10 | Yes | — |
| 4 | Drek'Thar | 25 | 0 | Yes | — |
| 5 | Sneed | 20 | 0 | Yes | — |
| 6 | Inge, the Iron Hymn | 20 | 0 | Yes | — |
| 7 | Sylvanas Windrunner | 20 | 0 | Yes | — |
| 8 | Professor Putricide | 16 | 0 | Yes | — |

---

## Heuristic Strategy

The Q-score heuristic evaluates each affordable tavern minion by:

1. **Buy & Play**: Score = current_board_score + minion.atk + minion.health + aura_bonus
2. **Sell & Replace**: If board full, replace weakest minion if net score change > 0
3. **Upgrade**: If no beneficial buy is available and gold ≥ upgrade_cost, upgrade tavern tier
4. **Refresh**: If no other action is possible, refresh the tavern for 1 gold

This is a greedy one-step heuristic — no lookahead, no opponent modeling, no combat simulation.
Average rank in self-play: ~4.5 (random among identical strategies)