# 1 SearchAgent vs 7 Heuristic — Detailed Audit

**Seed**: 42  |  **Max Turns**: 15
**Agent**: Yogg-Saron, Hope's End (SearchAgent greedy)
**Opponents**: 7× Greedy Q-Score Heuristic

| # | Role | Hero | HP | Armor | Tier |
|---|---|---|---|---|---|
| 1 | **RL Agent** | Yogg-Saron, Hope's End | 30 | 18 | 1 |
| 2 | Heuristic #1 | Sneed | 30 | 12 | 1 |
| 3 | Heuristic #2 | Overlord Saurfang | 30 | 18 | 1 |
| 4 | Heuristic #3 | Ysera | 30 | 12 | 1 |
| 5 | Heuristic #4 | Inge, the Iron Hymn | 30 | 12 | 1 |
| 6 | Heuristic #5 | Professor Putricide | 30 | 10 | 1 |
| 7 | Heuristic #6 | Sylvanas Windrunner | 30 | 10 | 1 |
| 8 | Heuristic #7 | Drek'Thar | 30 | 12 | 1 |

---

## Game Log

### Turn 1

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=18 Gold=3 Tier=1

  Board: (empty)
  Tavern (4 items): Manasaber 4/1 T1 $3 | Risen Rider 2/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Evolving Strategy (spell) T1 $3
  Hand: 0 cards

  → Gold 3→0
  → Actions: buy_tavern_0, play_hand_0, sell_board_0, refresh

**Sneed** [Heuristic]  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern (4 items): Ominous Seer 2/1 T1 $3 | Picky Eater 1/1 T1 $3 | Picky Eater 1/1 T1 $3 | Rime or Reason (spell) T1 $3
  Hand: 0 cards

  → Board (1/7): 2/1
  → Gold 3→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=18 Gold=3 Tier=1

  Board: (empty)
  Tavern (4 items): Surf n' Surf 2/2 T1 $3 | Surf n' Surf 2/2 T1 $3 | Wrath Weaver 2/5 T1 $3 | Tavern Coin (spell) T1 $3
  Hand: 0 cards

  → Board (1/7): 2/5
  → Gold 3→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern (5 items): Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Surf n' Surf 1/1 T1 $3 | A New Sprout (spell) T1 $3 | Scarlet Survivor 3/3 T1 $3
  Hand: 0 cards

  → Board (1/7): 3/3
  → Gold 3→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern (4 items): Picky Eater 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Cloning Conch (spell) T1 $0
  Hand: 0 cards

  → Board (1/7): 4/1
  → Gold 3→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=10 Gold=3 Tier=1

  Board: (empty)
  Tavern (4 items): Cord Puller 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Them Apples (spell) T1 $1
  Hand: 0 cards

  → Board (1/7): 4/1
  → Gold 3→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=10 Gold=3 Tier=1

  Board: (empty)
  Tavern (4 items): Surf n' Surf 1/1 T1 $3 | Risen Rider 2/1 T1 $3 | Picky Eater 1/1 T1 $3 | Pointy Arrow (spell) T1 $1
  Hand: 0 cards

  → Board (1/7): 2/1 [Taunt,Reborn]
  → Gold 3→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern (4 items): Risen Rider 2/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Meditation (spell) T1 $3
  Hand: 0 cards

  → Board (1/7): 2/1 [Taunt,Reborn]
  → Gold 3→0
  → Actions: (auto)

**Combat Phase**

  [heur] Sylvanas Windrunner vs [heur] Sneed (first: Sneed)
     Sylvanas Windrunner: [2/1]
     Sneed: [2/1]
     Ominous Seer 2/1→2/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Result: 0 vs 0 — draw
  [heur] Overlord Saurfang vs [heur] Professor Putricide (first: Overlord Saurfang)
     Overlord Saurfang: [2/5]
     Professor Putricide: [4/1]
     Wrath Weaver 2/5→2/1  |  Manasaber 4/1→4/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Ysera vs [AGENT] Yogg-Saron, Hope's End (first: Ysera)
     Ysera: [3/3]
     Yogg-Saron, Hope's End: []
     Result: 1 vs 0 — heur
  [heur] Inge, the Iron Hymn vs [heur] Drek'Thar (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1]
     Drek'Thar: [2/1]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Result: 0 vs 0 — draw

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=1) | Sneed (HP=30, Tier=1) | Overlord Saurfang (HP=30, Tier=1) | Ysera (HP=30, Tier=1) | Inge, the Iron Hymn (HP=30, Tier=1) | Professor Putricide (HP=30, Tier=1) | Sylvanas Windrunner (HP=30, Tier=1) | Drek'Thar (HP=30, Tier=1)

### Turn 2

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=16 Gold=4 Tier=1

  Board: (empty)
  Tavern (4 items): Picky Eater 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Manasaber 4/1 T1 $3 | Undersea Mount (spell) T1 $3
  Hand: 0 cards

  → Board (1/7): 1/4
  → Gold 4→0
  → Actions: buy_tavern_1, play_hand_0, refresh

**Sneed** [Heuristic]  HP=30 Armor=12 Gold=4 Tier=1

  Board (1/7): 2/1
  Tavern (4 items): Harmless Bonehead 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Enchanted Lasso (spell) T1 $2
  Hand: 0 cards

  → Board (2/7): 2/1, 1/1
  → Gold 4→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=18 Gold=4 Tier=1

  Board (1/7): 2/5
  Tavern (4 items): Risen Rider 5/4 T1 $3 | Harmless Bonehead 4/4 T1 $3 | Harmless Bonehead 4/4 T1 $3 | Fortify (spell) T1 $1
  Hand: 0 cards

  → Board (2/7): 2/5, 5/4 [Taunt,Reborn]
  → Gold 4→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=12 Gold=4 Tier=1

  Board (1/7): 3/3
  Tavern (5 items): Annoy-o-Tron 1/2 T1 $3 | Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Sick Riffs (spell) T1 $3 | Scarlet Survivor 3/3 T1 $3
  Hand: 0 cards

  → Board (2/7): 3/3, 3/3
  → Gold 4→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=4 Tier=1

  Board (1/7): 4/1
  Tavern (4 items): Ominous Seer 2/1 T1 $3 | Risen Rider 2/1 T1 $3 | Ominous Seer 2/1 T1 $3 | Banana (spell) T1 $0
  Hand: 0 cards

  → Board (2/7): 4/1, 2/1
  → Gold 4→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=8 Gold=4 Tier=1

  Board (1/7): 4/1
  Tavern (4 items): Manasaber 4/1 T1 $3 | Risen Rider 2/1 T1 $3 | Cord Puller 1/1 T1 $3 | Tavern Coin (spell) T1 $1
  Hand: 0 cards

  → Board (2/7): 4/1, 4/1
  → Gold 4→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=10 Gold=4 Tier=1

  Board (1/7): 2/1 [Taunt,Reborn]
  Tavern (4 items): Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Wrath Weaver 1/4 T1 $3 | The Goldenizer (spell) T1 $0
  Hand: 0 cards

  → Board (2/7): 2/1 [Taunt,Reborn], 1/4
  → Gold 4→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=12 Gold=4 Tier=1

  Board (1/7): 2/1 [Taunt,Reborn]
  Tavern (4 items): Manasaber 4/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Angler's Lure (spell) T1 $3
  Hand: 0 cards

  → Board (2/7): 2/1 [Taunt,Reborn], 4/1
  → Gold 4→0
  → Actions: (auto)

**Combat Phase**

  [heur] Ysera vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Ysera: [3/3, 3/3]
     Inge, the Iron Hymn: [4/1, 2/1]
     Manasaber 4/1→4/0 DEAD  |  Scarlet Survivor 3/3→3/0 DEAD
     Scarlet Survivor 3/3→3/1  |  Ominous Seer 2/1→2/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Overlord Saurfang vs [heur] Sneed (first: Sneed)
     Overlord Saurfang: [2/5, 5/4]
     Sneed: [2/1, 1/1]
     Ominous Seer 2/1→2/0 DEAD  |  Risen Rider 5/4→5/2
     Wrath Weaver 2/5→2/4  |  Harmless Bonehead 1/1→1/0 DEAD
     Result: 2 vs 0 — heur
  [heur] Professor Putricide vs [heur] Sylvanas Windrunner (first: Professor Putricide)
     Professor Putricide: [4/1, 4/1]
     Sylvanas Windrunner: [2/1, 1/4]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 1/4→1/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: 0 vs 0 — draw
  [AGENT] Yogg-Saron, Hope's End vs [heur] Drek'Thar (first: Drek'Thar)
     Yogg-Saron, Hope's End: [1/4]
     Drek'Thar: [2/1, 4/1]
     Risen Rider 2/1→2/0 DEAD  |  Wrath Weaver 1/4→1/2
     Wrath Weaver 1/2→1/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: 0 vs 0 — draw

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=1) | Sneed (HP=30, Tier=1) | Overlord Saurfang (HP=30, Tier=1) | Ysera (HP=30, Tier=1) | Inge, the Iron Hymn (HP=30, Tier=1) | Professor Putricide (HP=30, Tier=1) | Sylvanas Windrunner (HP=30, Tier=1) | Drek'Thar (HP=30, Tier=1)

### Turn 3

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=16 Gold=5 Tier=1

  Board (1/7): 1/4
  Tavern (3 items): Cord Puller 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Manasaber 4/1 T1 $3
  Hand: 0 cards

  → Board (2/7): 1/4, 4/1
  → Gold 5→0
  → Actions: buy_tavern_2, play_hand_0, refresh, refresh

**Sneed** [Heuristic]  HP=30 Armor=9 Gold=5 Tier=1

  Board (2/7): 2/1, 1/1
  Tavern (3 items): Annoy-o-Tron 1/2 T1 $3 | Picky Eater 1/1 T1 $3 | Cord Puller 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1, 1/1, 1/2 [Taunt,DS]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=18 Gold=5 Tier=1

  Board (2/7): 2/5, 5/4 [Taunt,Reborn]
  Tavern (3 items): Surf n' Surf 6/6 T1 $3 | Risen Rider 7/6 T1 $3 | Cord Puller 6/6 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/5, 5/4 [Taunt,Reborn], 7/6 [Taunt,Reborn]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=12 Gold=5 Tier=1

  Board (2/7): 3/3, 3/3
  Tavern (4 items): Wrath Weaver 1/4 T1 $3 | Ominous Seer 2/1 T1 $3 | Cord Puller 1/1 T1 $3 | Scarlet Survivor 3/3 T1 $3
  Hand: 0 cards

  → Board (2/7): 6/6 [G], 3/5
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=10 Gold=5 Tier=1

  Board (2/7): 4/1, 2/1
  Tavern (3 items): Risen Rider 2/1 T1 $3 | Risen Rider 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 4/1, 2/1, 2/1 [Taunt,Reborn]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=8 Gold=5 Tier=1

  Board (2/7): 4/1, 4/1
  Tavern (3 items): Wrath Weaver 1/4 T1 $3 | Risen Rider 2/1 T1 $3 | Cord Puller 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 4/1, 4/1, 1/4
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=10 Gold=5 Tier=1

  Board (2/7): 2/1 [Taunt,Reborn], 1/4
  Tavern (3 items): Wrath Weaver 1/4 T1 $3 | Ominous Seer 2/1 T1 $3 | Picky Eater 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1 [Taunt,Reborn], 3/6, 1/4
  → Tier 1→2 | Gold 5→0 | Armor 10→9
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=12 Gold=5 Tier=1

  Board (2/7): 2/1 [Taunt,Reborn], 4/1
  Tavern (3 items): Ominous Seer 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Cord Puller 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1 [Taunt,Reborn], 4/1, 2/1
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Ysera (first: Overlord Saurfang)
     Overlord Saurfang: [2/5, 5/4, 7/6]
     Ysera: [6/6, 3/5]
     Wrath Weaver 2/5→2/0 DEAD  |  Scarlet Survivor 6/6→6/4
     Scarlet Survivor 6/4→6/0 DEAD  |  Risen Rider 7/6→7/0 DEAD
     Risen Rider 5/4→5/1  |  Street Magician 3/5→3/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Professor Putricide vs [heur] Sneed (first: Professor Putricide)
     Professor Putricide: [4/1, 4/1, 1/4]
     Sneed: [2/1, 1/1, 1/2]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Ominous Seer 2/1→2/0 DEAD  |  Wrath Weaver 1/4→1/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Harmless Bonehead 1/1→1/0 DEAD  |  Wrath Weaver 1/2→1/1
     Result: 1 vs 0 — heur
  [heur] Inge, the Iron Hymn vs [AGENT] Yogg-Saron, Hope's End (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 2/1, 2/1]
     Yogg-Saron, Hope's End: [1/4, 4/1]
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Wrath Weaver 1/4→1/2  |  Risen Rider 2/1→2/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Wrath Weaver 1/2→1/0 DEAD
     Result: 0 vs 0 — draw
  [heur] Sylvanas Windrunner vs [heur] Drek'Thar (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [2/1, 3/6, 1/4]
     Drek'Thar: [2/1, 4/1, 2/1]
     Risen Rider 2/1→2/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 3/6→3/2
     Wrath Weaver 3/2→3/0 DEAD  |  Ominous Seer 2/1→2/0 DEAD
     Result: 1 vs 0 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=1) | Sneed (HP=30, Tier=2) | Overlord Saurfang (HP=30, Tier=2) | Ysera (HP=30, Tier=2) | Inge, the Iron Hymn (HP=30, Tier=2) | Professor Putricide (HP=30, Tier=2) | Sylvanas Windrunner (HP=30, Tier=2) | Drek'Thar (HP=30, Tier=2)

### Turn 4

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=16 Gold=6 Tier=1

  Board (2/7): 1/4, 4/1
  Tavern (3 items): Annoy-o-Tron 1/2 T1 $3 | Manasaber 4/1 T1 $3 | Wrath Weaver 1/4 T1 $3
  Hand: 0 cards

  → Board (3/7): 3/6, 4/1, 4/1
  → Tier 1→2 | Gold 6→0 | Armor 16→15
  → Actions: buy_tavern_1, play_hand_0, buy_tavern_1, play_hand_0, sell_board_3, upgrade

**Sneed** [Heuristic]  HP=30 Armor=6 Gold=6 Tier=2

  Board (3/7): 2/1, 1/1, 1/2 [Taunt,DS]
  Tavern (5 items): Alert Alarmist 2/2 T2 $3 | Scarlet Skull 2/1 T2 $3 | Tide Raiser 2/1 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Chef's Choice (spell) T2 $2
  Hand: 0 cards

  → Board (5/7): 2/1, 2/1, 1/2 [Taunt,DS], 2/4, 3/1 [Reborn]
  → Gold 6→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=18 Gold=6 Tier=2

  Board (3/7): 2/5, 5/4 [Taunt,Reborn], 7/6 [Taunt,Reborn]
  Tavern (5 items): Sewer Rat 10/9 T2 $3 | Laboratory Assistant 10/11 T2 $3 | Metallic Hunter 11/9 T2 $3 | Laboratory Assistant 10/11 T2 $3 | Leaf Through the Pages (spell) T2 $1
  Hand: 0 cards

  → Board (5/7): 6/9, 5/4 [Taunt,Reborn], 7/6 [Taunt,Reborn], 10/11, 10/11
  → Gold 6→0 | Armor 18→16
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=9 Gold=6 Tier=2

  Board (2/7): 6/6 [G], 3/5
  Tavern (6 items): Scarlet Skull 2/1 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Old Soul 3/4 T2 $3 | Surf n' Surf 1/1 T1 $3 | Might of Stormwind (spell) T2 $2 | Twilight Hatchling 1/1 T1 $3
  Hand: 0 cards

  → Board (4/7): 6/6 [G], 3/5, 3/4, 3/4
  → Gold 6→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=10 Gold=6 Tier=2

  Board (3/7): 4/1, 2/1, 2/1 [Taunt,Reborn]
  Tavern (5 items): Nerubian Deathswarmer 1/4 T2 $3 | Old Soul 3/4 T2 $3 | Eternal Knight 4/2 T2 $3 | Tide Raiser 2/1 T2 $3 | Hasty Excavation (spell) T2 $3
  Hand: 0 cards

  → Board (5/7): 4/1, 2/1, 2/1 [Taunt,Reborn], 3/4, 4/2
  → Gold 6→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=8 Gold=6 Tier=2

  Board (3/7): 4/1, 4/1, 1/4
  Tavern (5 items): Shell Collector 4/3 T2 $3 | Sewer Rat 3/2 T2 $3 | Sewer Rat 3/2 T2 $3 | Reef Riffer 3/2 T2 $3 | Search Through Time (spell) T2 $2
  Hand: 0 cards

  → Board (5/7): 4/1, 4/1, 1/4, 4/3, 3/2
  → Gold 6→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=9 Gold=6 Tier=2

  Board (3/7): 2/1 [Taunt,Reborn], 3/6, 1/4
  Tavern (5 items): Manasaber 4/1 T1 $3 | Scarlet Skull 2/1 T2 $3 | Sewer Rat 3/2 T2 $3 | Lava Lurker 2/5 T2 $3 | Strike Oil (spell) T2 $3
  Hand: 0 cards

  → Board (5/7): 2/1 [Taunt,Reborn], 3/6, 1/4, 2/5, 4/1
  → Gold 6→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=9 Gold=6 Tier=2

  Board (3/7): 2/1 [Taunt,Reborn], 4/1, 2/1
  Tavern (4 items): Lava Lurker 2/5 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Cord Puller 1/1 T1 $3
  Hand: 0 cards

  → Board (5/7): 2/1 [Taunt,Reborn], 4/1, 2/1, 2/5, 3/4
  → Gold 6→0
  → Actions: (auto)

**Combat Phase**

  [heur] Sneed vs [heur] Ysera (first: Sneed)
     Sneed: [2/1, 2/1, 1/2, 2/4, 3/1]
     Ysera: [6/6, 3/5, 3/4, 3/4]
     Ominous Seer 2/1→2/0 DEAD  |  Scarlet Survivor 6/6→6/4
     Scarlet Survivor 6/4→6/3  |  Annoy-o-Tron 1/2→1/2
     Harmless Bonehead 2/1→2/0 DEAD  |  Street Magician 3/5→3/3
     Street Magician 3/3→3/2  |  Annoy-o-Tron 1/2→1/0 DEAD
     Nerubian Deathswarmer 2/4→2/1  |  Old Soul 3/4→3/2
     Laboratory Assistant 3/4→3/1  |  Scarlet Skull 3/1→3/0 DEAD
     Result: 1 vs 4 — heur
  [heur] Overlord Saurfang vs [heur] Professor Putricide (first: Professor Putricide)
     Overlord Saurfang: [6/9, 5/4, 7/6, 10/11, 10/11]
     Professor Putricide: [4/1, 4/1, 1/4, 4/3, 3/2]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 5/4→5/0 DEAD
     Wrath Weaver 6/9→6/8  |  Wrath Weaver 1/4→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 7/6→7/2
     Risen Rider 7/2→7/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Sewer Rat 3/2→3/0 DEAD  |  Laboratory Assistant 10/11→10/8
     Result: 3 vs 0 — heur
  [AGENT] Yogg-Saron, Hope's End vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Yogg-Saron, Hope's End: [3/6, 4/1, 4/1]
     Sylvanas Windrunner: [2/1, 3/6, 1/4, 2/5, 4/1]
     Risen Rider 2/1→2/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Wrath Weaver 3/6→3/2  |  Manasaber 4/1→4/0 DEAD
     Wrath Weaver 3/6→3/2  |  Manasaber 4/1→4/0 DEAD
     Result: 1 vs 3 — AGENT
  [heur] Inge, the Iron Hymn vs [heur] Drek'Thar (first: Drek'Thar)
     Inge, the Iron Hymn: [4/1, 2/1, 2/1, 3/4, 4/2]
     Drek'Thar: [2/1, 4/1, 2/1, 2/5, 3/4]
     Risen Rider 2/1→2/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Ominous Seer 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Ominous Seer 2/1→2/0 DEAD
     Old Soul 3/4→3/1  |  Ancestral Automaton 3/4→3/1
     Lava Lurker 2/5→2/2  |  Old Soul 3/1→3/0 DEAD
     Eternal Knight 4/2→5/0 DEAD  |  Lava Lurker 2/2→2/0 DEAD
     Result: 0 vs 1 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=2) | Sneed (HP=30, Tier=2) | Overlord Saurfang (HP=30, Tier=2) | Ysera (HP=30, Tier=2) | Inge, the Iron Hymn (HP=30, Tier=2) | Professor Putricide (HP=30, Tier=2) | Sylvanas Windrunner (HP=30, Tier=2) | Drek'Thar (HP=30, Tier=2)

### Turn 5

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=15 Gold=7 Tier=2

  Board (3/7): 3/6, 4/1, 4/1
  Tavern (5 items): Humming Bird 1/4 T2 $3 | Tide Raiser 2/1 T2 $3 | Reef Riffer 3/2 T2 $3 | Cord Puller 1/1 T1 $3 | Tavern Coin (spell) T1 $3
  Hand: 0 cards

  → Board (5/7): 3/6, 4/1, 4/1, 1/4, 3/2
  → Gold 7→0
  → Actions: buy_tavern_0, play_hand_0, buy_tavern_1, play_hand_0, refresh

**Sneed** [Heuristic]  HP=30 Armor=6 Gold=7 Tier=2

  Board (5/7): 2/1, 2/1, 1/2 [Taunt,DS], 2/4, 3/1 [Reborn]
  Tavern (4 items): Harmless Bonehead 2/1 T1 $3 | Harmless Bonehead 2/1 T1 $3 | Humming Bird 1/4 T2 $3 | Soul Rewinder 4/1 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=16 Gold=7 Tier=2

  Board (5/7): 6/9, 5/4 [Taunt,Reborn], 7/6 [Taunt,Reborn], 10/11, 10/11
  Tavern (4 items): Reef Riffer 14/13 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Reef Riffer 14/13 T2 $3 | Sewer Rat 14/13 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=9 Gold=7 Tier=2

  Board (4/7): 6/6 [G], 3/5, 3/4, 3/4
  Tavern (5 items): Ancestral Automaton 3/4 T2 $3 | Shell Collector 4/3 T2 $3 | Ominous Seer 2/1 T1 $3 | Metallic Hunter 4/2 T2 $3 | Twilight Hatchling 1/1 T1 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=6 Gold=7 Tier=2

  Board (5/7): 4/1, 2/1, 2/1 [Taunt,Reborn], 3/4, 5/2
  Tavern (4 items): Scarlet Skull 2/1 T2 $3 | Wrath Weaver 1/4 T1 $3 | Metallic Hunter 4/2 T2 $3 | Lava Lurker 2/5 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=1 Gold=7 Tier=2

  Board (5/7): 4/1, 4/1, 1/4, 4/3, 3/2
  Tavern (4 items): Metallic Hunter 4/2 T2 $3 | Metallic Hunter 4/2 T2 $3 | Manasaber 4/1 T1 $3 | Old Soul 3/4 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=9 Gold=7 Tier=2

  Board (5/7): 2/1 [Taunt,Reborn], 3/6, 1/4, 2/5, 4/1
  Tavern (4 items): Ominous Seer 2/1 T1 $3 | Soul Rewinder 4/1 T2 $3 | Tide Raiser 2/1 T2 $3 | Metallic Hunter 4/2 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=9 Gold=7 Tier=2

  Board (5/7): 2/1 [Taunt,Reborn], 4/1, 2/1, 2/5, 3/4
  Tavern (4 items): Metallic Hunter 4/2 T2 $3 | Humming Bird 1/4 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Eternal Knight 4/2 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Combat Phase**

  [heur] Professor Putricide vs [heur] Drek'Thar (first: Professor Putricide)
     Professor Putricide: [4/1, 4/1, 1/4, 4/3, 3/2]
     Drek'Thar: [2/1, 4/1, 2/1, 2/5, 3/4]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Ominous Seer 2/1→2/0 DEAD
     Lava Lurker 2/5→2/2  |  Sewer Rat 3/2→3/0 DEAD
     Wrath Weaver 1/4→1/2  |  Lava Lurker 2/2→2/1
     Ancestral Automaton 3/4→3/3  |  Wrath Weaver 1/2→1/0 DEAD
     Result: 0 vs 2 — heur
  [heur] Ysera vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Ysera: [6/6, 3/5, 3/4, 3/4]
     Inge, the Iron Hymn: [4/1, 2/1, 2/1, 3/4, 5/2]
     Manasaber 4/1→4/0 DEAD  |  Scarlet Survivor 6/6→6/2
     Scarlet Survivor 6/2→6/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Old Soul 3/4→3/2
     Street Magician 3/5→3/0 DEAD  |  Eternal Knight 5/2→6/0 DEAD
     Old Soul 3/4→3/1  |  Laboratory Assistant 3/4→3/1
     Laboratory Assistant 3/1→3/0 DEAD  |  Old Soul 3/1→3/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Sneed vs [heur] Overlord Saurfang (first: Sneed)
     Sneed: [2/1, 2/1, 1/2, 2/4, 3/1]
     Overlord Saurfang: [6/9, 5/4, 7/6, 10/11, 10/11]
     Ominous Seer 2/1→2/0 DEAD  |  Risen Rider 5/4→5/2
     Wrath Weaver 6/9→6/8  |  Annoy-o-Tron 1/2→1/2
     Harmless Bonehead 2/1→2/0 DEAD  |  Risen Rider 5/2→5/0 DEAD
     Risen Rider 7/6→7/5  |  Annoy-o-Tron 1/2→1/0 DEAD
     Nerubian Deathswarmer 2/4→2/0 DEAD  |  Risen Rider 7/5→7/3
     Laboratory Assistant 10/11→10/8  |  Scarlet Skull 3/1→3/0 DEAD
     Result: 0 vs 4 — heur
  [heur] Sylvanas Windrunner vs [AGENT] Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Sylvanas Windrunner: [2/1, 3/6, 1/4, 2/5, 4/1]
     Yogg-Saron, Hope's End: [3/6, 5/1, 5/1, 2/4, 3/2]
     Wrath Weaver 3/6→3/4  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 3/6→3/3  |  Wrath Weaver 3/4→3/1
     Manasaber 5/1→5/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Wrath Weaver 1/4→1/1  |  Wrath Weaver 3/1→3/0 DEAD
     Manasaber 5/1→5/0 DEAD  |  Wrath Weaver 1/1→1/0 DEAD
     Lava Lurker 2/5→2/3  |  Humming Bird 2/4→2/2
     Humming Bird 2/2→2/0 DEAD  |  Wrath Weaver 3/3→3/1
     Result: 2 vs 1 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=2) | Overlord Saurfang (HP=30, Tier=3) | Ysera (HP=30, Tier=3) | Inge, the Iron Hymn (HP=30, Tier=3) | Sylvanas Windrunner (HP=30, Tier=3) | Drek'Thar (HP=30, Tier=3) | Sneed (HP=27, Tier=3) | Professor Putricide (HP=24, Tier=3)

### Turn 6

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=15 Gold=8 Tier=2

  Board (5/7): 3/6, 4/1, 4/1, 1/4, 3/2
  Tavern (4 items): Alert Alarmist 2/2 T2 $3 | Tide Raiser 2/1 T2 $3 | Sewer Rat 3/2 T2 $3 | Reef Riffer 3/2 T2 $3
  Hand: 1 cards

  → Board (6/7): 3/6, 4/1, 4/1, 1/4, 3/2, 3/2
  → Gold 8→0 | Trinket: Stegodon Portrait
  → Actions: buy_tavern_2, play_hand_1

**Sneed** [Heuristic]  HP=27 Armor=0 Gold=8 Tier=3

  Board (5/7): 2/1, 2/1, 1/2 [Taunt,DS], 2/4, 3/1 [Reborn]
  Tavern (5 items): Dustbone Devastator 3/6 T3 $3 | Reef Riffer 3/2 T2 $3 | Tide Raiser 2/1 T2 $3 | Wrath Weaver 1/4 T1 $3 | Overconfidence (spell) T3 $1
  Hand: 0 cards

  → Board (7/7): 2/1, 5/1, 1/2 [Taunt,DS], 5/4, 6/1 [Reborn], 6/6, 3/2
  → Gold 8→0 | Trinket: Artisanal Urn
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=16 Gold=8 Tier=3

  Board (5/7): 6/9, 5/4 [Taunt,Reborn], 7/6 [Taunt,Reborn], 10/11, 10/11
  Tavern (5 items): Picky Eater 12/12 T1 $3 | Cadaver Caretaker 14/14 T3 $3 | Cadaver Caretaker 14/14 T3 $3 | Reef Riffer 14/13 T2 $3 | Careful Investment (spell) T3 $1
  Hand: 0 cards

  → Board (7/7): 6/9, 7/6 [Taunt,Reborn], 10/11, 10/11, 14/14, 14/14, 14/13
  → Gold 8→0 | Armor 16→21 | Trinket: Shadowy Elixir
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=9 Gold=8 Tier=3

  Board (4/7): 6/6 [G], 3/5, 3/4, 3/4
  Tavern (5 items): Accord-o-Tron 3/3 T3 $3 | Shell Collector 4/3 T2 $3 | False Implicator 1/1 T3 $3 | Floating Watcher 4/4 T3 $5 | Blazing Skyfin 2/4 T2 $3
  Hand: 0 cards

  → Board (6/7): 6/6 [G], 3/5, 3/4, 3/4, 4/4, 4/3
  → Gold 8→0 | Trinket: Smuggler Portrait
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=1 Gold=8 Tier=3

  Board (5/7): 4/1, 2/1, 2/1 [Taunt,Reborn], 3/4, 6/2
  Tavern (4 items): Nerubian Deathswarmer 1/4 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Mummifier 5/2 T3 $3 | False Implicator 1/1 T3 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 2/1, 2/1 [Taunt,Reborn], 3/4, 6/2, 3/4, 5/2
  → Gold 8→0 | Trinket: Putricide Sticker
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=24 Armor=0 Gold=8 Tier=3

  Board (5/7): 4/1, 4/1, 1/4, 4/3, 3/2
  Tavern (4 items): Sly Raptor 1/3 T3 $3 | Deep-Sea Angler 2/3 T3 $3 | Sly Raptor 1/3 T3 $3 | Ancestral Automaton 3/4 T2 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 4/1, 1/4, 4/3, 3/2, 3/4, 2/3
  → Gold 8→0 | Trinket: Ophidian Staff
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=9 Gold=8 Tier=3

  Board (5/7): 2/1 [Taunt,Reborn], 3/6, 1/4, 2/5, 4/1
  Tavern (4 items): Dustbone Devastator 2/6 T3 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Humming Bird 1/4 T2 $3 | Accord-o-Tron 3/3 T3 $3
  Hand: 0 cards

  → Board (7/7): 3/6, 1/4, 2/5, 4/1, 3/6, 3/3, 2/4
  → Gold 8→0 | Armor 9→14 | Trinket: Shadowy Elixir
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=9 Gold=8 Tier=3

  Board (5/7): 2/1 [Taunt,Reborn], 4/1, 2/1, 2/5, 3/4
  Tavern (4 items): Leeching Felhound 3/3 T3 $3 | Reef Riffer 3/2 T2 $3 | Deflect-o-Bot 3/2 T3 $3 | Annoy-o-Module 2/4 T3 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 2/1, 2/5, 3/4, 3/3, 2/4 [Taunt,DS], 3/2
  → Gold 8→0 | Armor 9→6 | Trinket: Archaic Scroll
  → Actions: (auto)

**Combat Phase**

  [heur] Inge, the Iron Hymn vs [AGENT] Yogg-Saron, Hope's End (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 2/1, 2/1, 3/4, 6/2, 3/4, 5/2]
     Yogg-Saron, Hope's End: [3/6, 5/1, 5/1, 2/4, 3/2, 4/2]
     Manasaber 4/1→4/0 DEAD  |  Sewer Rat 4/2→4/0 DEAD
     Wrath Weaver 3/6→3/4  |  Risen Rider 2/1→2/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Manasaber 5/1→5/1
     Manasaber 5/1→5/1  |  Ancestral Automaton 3/4→3/0 DEAD
     Old Soul 3/4→3/1  |  Wrath Weaver 3/4→3/1
     Manasaber 5/1→5/0 DEAD  |  Old Soul 3/1→3/0 DEAD
     Eternal Knight 6/2→7/0 DEAD  |  Humming Bird 2/4→2/0 DEAD
     Reef Riffer 3/2→3/0 DEAD  |  Mummifier 5/2→5/0 DEAD
     Result: 0 vs 2 — AGENT
  [heur] Overlord Saurfang vs [heur] Sylvanas Windrunner (first: Overlord Saurfang)
     Overlord Saurfang: [6/9, 7/6, 10/11, 10/11, 14/14, 14/14, 14/13]
     Sylvanas Windrunner: [3/6, 1/4, 2/5, 4/1, 3/6, 3/3, 2/4]
     Wrath Weaver 6/9→6/6  |  Wrath Weaver 3/6→3/0 DEAD
     Wrath Weaver 1/4→1/0 DEAD  |  Risen Rider 7/6→7/5
     Risen Rider 7/5→7/1  |  Manasaber 4/1→4/0 DEAD
     Lava Lurker 2/5→2/0 DEAD  |  Risen Rider 7/1→7/0 DEAD
     Laboratory Assistant 10/11→10/9  |  Nerubian Deathswarmer 2/4→2/0 DEAD
     Dustbone Devastator 3/6→4/0 DEAD  |  Wrath Weaver 6/6→6/3
     Laboratory Assistant 10/11→10/8  |  Accord-o-Tron 3/3→3/0 DEAD
     Result: 6 vs 0 — heur
  [heur] Professor Putricide vs [heur] Sneed (first: Sneed)
     Professor Putricide: [4/1, 4/1, 1/4, 4/3, 3/2, 3/4, 2/3]
     Sneed: [2/1, 5/1, 1/2, 5/4, 6/1, 6/6, 3/2]
     Ominous Seer 2/1→2/0 DEAD  |  Ancestral Automaton 3/4→3/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Harmless Bonehead 5/1→5/0 DEAD  |  Deep-Sea Angler 2/3→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Nerubian Deathswarmer 5/4→5/1  |  Ancestral Automaton 3/2→3/0 DEAD
     Wrath Weaver 1/4→1/1  |  Reef Riffer 3/2→3/1
     Scarlet Skull 6/1→6/0 DEAD  |  Wrath Weaver 1/1→1/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Reef Riffer 3/1→3/0 DEAD
     Dustbone Devastator 7/8→8/5  |  Sewer Rat 3/2→3/0 DEAD
     Result: 0 vs 2 — heur
  [heur] Ysera vs [heur] Drek'Thar (first: Drek'Thar)
     Ysera: [6/6, 3/5, 3/4, 3/4, 4/4, 4/3]
     Drek'Thar: [4/1, 2/1, 2/5, 3/4, 3/3, 2/4, 3/2]
     Manasaber 4/1→4/0 DEAD  |  Scarlet Survivor 6/6→6/2
     Scarlet Survivor 6/2→6/0 DEAD  |  Annoy-o-Module 2/4→2/4
     Ominous Seer 2/1→2/0 DEAD  |  Laboratory Assistant 3/4→3/2
     Street Magician 3/5→3/3  |  Annoy-o-Module 2/4→2/1
     Lava Lurker 2/5→2/1  |  Shell Collector 4/3→4/1
     Laboratory Assistant 3/2→3/0 DEAD  |  Annoy-o-Module 2/1→2/0 DEAD
     Ancestral Automaton 3/4→3/1  |  Street Magician 3/3→3/0 DEAD
     Old Soul 3/4→3/1  |  Ancestral Automaton 3/1→3/0 DEAD
     Leeching Felhound 3/3→3/0 DEAD  |  Old Soul 3/1→3/0 DEAD
     Floating Watcher 4/4→4/1  |  Reef Riffer 3/2→3/0 DEAD
     Result: 2 vs 1 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=2) | Overlord Saurfang (HP=30, Tier=3) | Ysera (HP=30, Tier=3) | Sylvanas Windrunner (HP=30, Tier=3) | Drek'Thar (HP=30, Tier=3) | Sneed (HP=27, Tier=3) | Inge, the Iron Hymn (HP=27, Tier=3) | Professor Putricide (HP=16, Tier=3)

### Turn 7

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=15 Gold=9 Tier=2

  Board (6/7): 3/6, 4/1, 4/1, 1/4, 3/2, 3/2
  Tavern (4 items): Shell Collector 4/3 T2 $3 | Old Soul 3/4 T2 $3 | Alert Alarmist 2/2 T2 $3 | Alert Alarmist 2/2 T2 $3
  Hand: 1 cards

  → Board (6/7): 3/6, 4/1, 4/1, 1/4, 3/2, 4/3
  → Tier 2→3 | Gold 9→0 | Hand 1→2
  → Actions: buy_tavern_0, play_hand_1, upgrade, refresh, refresh, sell_board_5, refresh

**Sneed** [Heuristic]  HP=27 Armor=0 Gold=9 Tier=3

  Board (7/7): 2/1, 6/1, 1/2 [Taunt,DS], 6/4, 7/1 [Reborn], 7/6, 3/2
  Tavern (4 items): Deflect-o-Bot 3/2 T3 $3 | Deep-Sea Angler 2/3 T3 $3 | Sprightly Scarab 3/1 T3 $3 | Technical Element 5/6 T3 $3
  Hand: 1 cards

  → Board (7/7): 6/1, 1/2 [Taunt,DS], 10/8, 7/1 [Reborn], 7/6, 3/2, 5/6
  → Tier 3→4 | Gold 9→0 | Hand 1→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=21 Gold=9 Tier=3

  Board (7/7): 6/9, 7/6 [Taunt,Reborn], 10/11, 10/11, 14/14, 14/14, 14/13
  Tavern (4 items): Sprightly Scarab 19/17 T3 $3 | Annoy-o-Module 18/20 T3 $3 | Mummifier 21/18 T3 $3 | Soul Rewinder 20/17 T2 $3
  Hand: 1 cards

  → Board (7/7): 6/9, 10/11, 14/15, 14/14, 14/14, 14/13, 21/18
  → Tier 3→4 | Gold 9→0 | Hand 1→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=9 Gold=9 Tier=3

  Board (6/7): 6/6 [G], 3/5, 3/4, 3/4, 4/4, 4/3
  Tavern (5 items): Technical Element 5/6 T3 $3 | Mummifier 5/2 T3 $3 | Alert Alarmist 2/2 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Roaring Recruiter 2/8 T3 $3
  Hand: 0 cards

  → Board (7/7): 6/6 [G], 3/5, 3/4, 3/4, 4/4, 4/3, 5/6
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=27 Armor=0 Gold=9 Tier=3

  Board (7/7): 4/1, 2/1, 2/1 [Taunt,Reborn], 3/4, 7/2, 3/4, 5/2
  Tavern (4 items): Ancestral Automaton 3/4 T2 $3 | Hardy Orca 1/6 T3 $3 | Technical Element 5/6 T3 $3 | Laboratory Assistant 3/4 T2 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 2/1 [Taunt,Reborn], 3/4, 7/2, 3/4, 5/2, 5/6
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=16 Armor=0 Gold=9 Tier=3

  Board (7/7): 4/1, 4/1, 1/4, 4/3, 3/2, 3/4, 2/3
  Tavern (4 items): Ancestral Automaton 3/4 T2 $3 | Mummifier 5/2 T3 $3 | Shell Collector 4/3 T2 $3 | False Implicator 1/1 T3 $3
  Hand: 1 cards

  → Board (7/7): 4/1, 1/4, 4/3, 3/2, 6/6 [Taunt], 2/3, 6/4
  → Tier 3→4 | Gold 9→0 | Hand 1→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=4 Gold=10 Tier=3

  Board (7/7): 3/6, 1/4, 2/5, 4/1, 4/6, 3/3, 3/4
  Tavern (4 items): Tide Raiser 2/1 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Leeching Felhound 3/3 T3 $3 | Handless Forsaken 4/1 T3 $3
  Hand: 0 cards

  → Board (7/7): 3/6, 2/5, 4/6, 3/3, 3/4, 3/4, 4/1
  → Tier 3→4 | Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=6 Gold=9 Tier=3

  Board (7/7): 4/1, 2/1, 2/5, 3/4, 3/3, 2/4 [Taunt,DS], 3/2
  Tavern (4 items): Floating Watcher 4/4 T3 $5 | Lava Lurker 2/5 T2 $3 | Scarlet Skull 2/1 T2 $3 | Soul Rewinder 4/1 T2 $3
  Hand: 1 cards

  → Board (7/7): 4/1, 6/9, 3/4, 3/3, 2/4 [Taunt,DS], 3/2, 2/5
  → Tier 3→4 | Gold 9→0 | Hand 1→0
  → Actions: (auto)

**Combat Phase**

  [heur] Inge, the Iron Hymn vs [heur] Professor Putricide (first: Professor Putricide)
     Inge, the Iron Hymn: [4/1, 2/1, 3/4, 7/2, 3/4, 5/2, 5/6]
     Professor Putricide: [4/1, 1/4, 4/3, 3/2, 6/6, 2/3, 6/4]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Ancestral Automaton 6/6→6/2
     Wrath Weaver 1/4→1/0 DEAD  |  Mummifier 5/2→5/1
     Old Soul 3/4→3/0 DEAD  |  Ancestral Automaton 6/2→6/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Technical Element 5/6→5/2
     Eternal Knight 7/2→8/0 DEAD  |  Deep-Sea Angler 2/3→2/0 DEAD
     Sewer Rat 3/2→3/0 DEAD  |  Ancestral Automaton 3/4→3/1
     Ancestral Automaton 3/1→3/0 DEAD  |  Ancestral Automaton 6/4→6/1
     Ancestral Automaton 6/1→6/0 DEAD  |  Mummifier 5/1→5/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Sylvanas Windrunner vs [heur] Ysera (first: Ysera)
     Sylvanas Windrunner: [3/6, 2/5, 4/6, 3/3, 3/4, 3/4, 4/1]
     Ysera: [6/6, 3/5, 3/4, 3/4, 4/4, 4/3, 5/6]
     Scarlet Survivor 6/6→6/4  |  Lava Lurker 2/5→2/0 DEAD
     Wrath Weaver 3/6→3/2  |  Shell Collector 4/3→4/0 DEAD
     Street Magician 3/5→3/2  |  Wrath Weaver 3/2→3/0 DEAD
     Dustbone Devastator 4/6→5/1  |  Technical Element 5/6→5/2
     Laboratory Assistant 3/4→3/0 DEAD  |  Dustbone Devastator 5/1→5/0 DEAD
     Accord-o-Tron 3/3→3/0 DEAD  |  Scarlet Survivor 6/4→6/1
     Old Soul 3/4→3/0 DEAD  |  Nerubian Deathswarmer 4/4→4/1
     Nerubian Deathswarmer 4/1→4/0 DEAD  |  Street Magician 3/2→3/0 DEAD
     Floating Watcher 4/4→4/1  |  Ancestral Automaton 3/4→3/0 DEAD
     Handless Forsaken 5/1→5/0 DEAD  |  Technical Element 5/2→5/0 DEAD
     Result: 0 vs 2 — heur
  [heur] Overlord Saurfang vs [AGENT] Yogg-Saron, Hope's End (first: Overlord Saurfang)
     Overlord Saurfang: [6/9, 10/11, 14/15, 14/14, 14/14, 14/13, 21/18]
     Yogg-Saron, Hope's End: [3/6, 5/1, 5/1, 2/4, 3/2, 4/3]
     Wrath Weaver 6/9→6/4  |  Manasaber 5/1→5/1
     Wrath Weaver 3/6→3/0 DEAD  |  Laboratory Assistant 10/11→10/8
     Laboratory Assistant 10/8→10/3  |  Manasaber 5/1→5/1
     Manasaber 5/1→5/0 DEAD  |  Cadaver Caretaker 14/14→14/9
     Laboratory Assistant 14/15→14/10  |  Manasaber 5/1→5/0 DEAD
     Humming Bird 2/4→2/0 DEAD  |  Cadaver Caretaker 14/14→14/12
     Cadaver Caretaker 14/9→14/6  |  Reef Riffer 3/2→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Cadaver Caretaker 14/6→14/2
     Result: 7 vs 0 — heur
  [heur] Sneed vs [heur] Drek'Thar (first: Drek'Thar)
     Sneed: [6/1, 1/2, 10/8, 7/1, 7/6, 3/2, 5/6]
     Drek'Thar: [4/1, 6/9, 3/4, 3/3, 2/4, 3/2, 2/5]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Harmless Bonehead 6/1→6/0 DEAD  |  Annoy-o-Module 2/4→2/4
     Lava Lurker 6/9→6/8  |  Annoy-o-Tron 1/2→1/0 DEAD
     Nerubian Deathswarmer 10/8→10/6  |  Annoy-o-Module 2/4→2/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Dustbone Devastator 7/6→7/3
     Scarlet Skull 7/1→7/0 DEAD  |  Lava Lurker 6/8→6/1
     Leeching Felhound 3/3→3/0 DEAD  |  Nerubian Deathswarmer 10/6→10/3
     Dustbone Devastator 7/3→8/0 DEAD  |  Reef Riffer 3/2→3/0 DEAD
     Lava Lurker 2/5→2/0 DEAD  |  Technical Element 5/6→5/4
     Reef Riffer 3/2→3/0 DEAD  |  Lava Lurker 6/1→6/0 DEAD
     Result: 2 vs 0 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=3) | Overlord Saurfang (HP=30, Tier=4) | Ysera (HP=30, Tier=4) | Sneed (HP=27, Tier=4) | Inge, the Iron Hymn (HP=27, Tier=4) | Drek'Thar (HP=27, Tier=4) | Sylvanas Windrunner (HP=26, Tier=4) | Professor Putricide (HP=9, Tier=4)

### Turn 8

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=5 Gold=10 Tier=3

  Board (6/7): 3/6, 4/1, 4/1, 1/4, 3/2, 4/3
  Tavern (5 items): Mummifier 5/2 T3 $3 | Metallic Hunter 4/2 T2 $3 | Shell Collector 4/3 T2 $3 | Alert Alarmist 2/2 T2 $3 | Sick Riffs (spell) T1 $3
  Hand: 2 cards

  → Board (4/7): 3/6, 4/1, 4/3, 5/2
  → Tier 3→4 | Gold 10→0
  → Actions: buy_tavern_0, play_hand_2, upgrade, sell_board_4, refresh, sell_board_3, refresh, sell_board_1, refresh

**Sneed** [Heuristic]  HP=27 Armor=0 Gold=10 Tier=4

  Board (7/7): 7/1, 1/2 [Taunt,DS], 11/8, 8/1 [Reborn], 8/6, 3/2, 5/6
  Tavern (6 items): Marquee Ticker 3/7 T4 $3 | Stomping Stegodon 4/4 T4 $3 | Handless Forsaken 8/1 T3 $3 | Seafloor Recruiter 3/5 T4 $3 | Marquee Ticker 3/7 T4 $3 | Easterly Winds (spell) T4 $1
  Hand: 1 cards

  → Board (7/7): 7/1, 11/8, 8/1 [Reborn], 8/6, 9/10, 8/1, 3/5
  → Gold 10→0 | Hand 1→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=21 Gold=10 Tier=4

  Board (7/7): 6/9, 10/11, 14/15, 14/14, 14/14, 14/13, 21/18
  Tavern (6 items): Hunting Tiger Shark 21/23 T4 $3 | Nerubian Deathswarmer 19/22 T2 $3 | Hunting Tiger Shark 21/23 T4 $3 | Malchezaar, Prince of Dance 23/22 T4 $3 | Flaming Enforcer 22/23 T4 $3 | Angler's Lure (spell) T1 $3
  Hand: 1 cards

  → Board (7/7): 14/15, 26/22, 23/22, 22/23, 21/23, 21/23, 20/22
  → Gold 10→0 | Armor 21→19 | Hand 1→2
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=9 Gold=10 Tier=4

  Board (7/7): 6/6 [G], 3/5, 3/4, 3/4, 4/4, 4/3, 5/6
  Tavern (7 items): Accord-o-Tron 3/3 T3 $3 | Waverider 2/8 T4 $3 | Dustbone Devastator 2/6 T3 $3 | Holo Rover 4/4 T4 $3 | Deep Blue Crooner 2/2 T3 $3 | Deepwater Clan (spell) T4 $2 | Twilight Broodmother 5/3 T4 $3
  Hand: 0 cards

  → Board (7/7): 6/6 [G], 5/6, 2/8, 2/6, 4/4 [DS], 5/3, 3/3
  → Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=27 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/1, 2/1 [Taunt,Reborn], 3/4, 8/2, 3/4, 5/2, 5/6
  Tavern (6 items): Holo Rover 4/4 T4 $3 | Accord-o-Tron 3/3 T3 $3 | Harmless Bonehead 1/1 T1 $3 | Woodland Defiler 5/6 T4 $3 | Technical Element 5/6 T3 $3 | Eonar's Favor (spell) T4 $2
  Hand: 0 cards

  → Board (7/7): 8/2, 5/2, 5/6, 5/6, 5/6, 4/4 [DS], 1/1
  → Gold 10→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=9 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/1, 1/4, 4/3, 3/2, 6/6 [Taunt], 2/3, 6/4
  Tavern (6 items): Eternal Knight 4/2 T2 $3 | Dustbone Devastator 2/6 T3 $3 | Deep Blue Crooner 2/2 T3 $3 | Trigore the Lasher 9/3 T4 $3 | Abyssal Bruiser 1/1 T4 $3 | Back to Back (spell) T4 $1
  Hand: 1 cards

  → Board (7/7): 4/3, 6/6 [Taunt], 6/4, 11/5 [Taunt], 2/6, 4/2, 1/1 [DS]
  → Gold 10→0 | Hand 1→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=26 Armor=0 Gold=11 Tier=4

  Board (7/7): 3/6, 2/5, 5/6, 3/3, 4/4, 3/4, 5/1
  Tavern (6 items): Friendly Geist 9/3 T4 $3 | Soul Rewinder 4/1 T2 $3 | Hardy Orca 1/6 T3 $3 | Humming Bird 1/4 T2 $3 | Stomping Stegodon 4/4 T4 $3 | Defender's Rites (spell) T4 $2
  Hand: 0 cards

  → Board (7/7): 5/8, 5/6, 4/4, 5/1, 9/3, 4/4, 1/4
  → Gold 11→0 | HP 26→24
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=27 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/1, 6/9, 3/4, 3/3, 2/4 [Taunt,DS], 3/2, 2/5
  Tavern (6 items): Marquee Ticker 3/7 T4 $3 | Deep-Sea Angler 2/3 T3 $3 | Trigore the Lasher 9/3 T4 $3 | Woodland Defiler 5/6 T4 $3 | Monstrous Macaw 5/4 T4 $3 | Natural Blessing (spell) T4 $4
  Hand: 1 cards

  → Board (7/7): 6/9, 2/5, 9/3, 5/6, 7/11, 5/4, 2/3
  → Gold 10→0 | Hand 1→0
  → Actions: (auto)

**Combat Phase**

  [heur] Ysera vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Ysera: [6/6, 5/6, 2/8, 2/6, 4/4, 5/3, 3/3]
     Overlord Saurfang: [14/15, 26/22, 23/22, 22/23, 21/23, 21/23, 20/22]
     Laboratory Assistant 14/15→14/13  |  Dustbone Devastator 2/6→2/0 DEAD
     Scarlet Survivor 6/6→6/0 DEAD  |  Hunting Tiger Shark 21/23→21/17
     Mummifier 26/22→26/20  |  Waverider 2/8→2/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Hunting Tiger Shark 21/23→21/18
     Malchezaar, Prince of Dance 23/22→23/17  |  Twilight Broodmother 5/3→5/0 DEAD
     Holo Rover 4/4→4/4  |  Hunting Tiger Shark 21/18→21/14
     Flaming Enforcer 22/23→22/20  |  Accord-o-Tron 3/3→3/0 DEAD
     Result: 1 vs 7 — heur
  [heur] Professor Putricide vs [heur] Sylvanas Windrunner (first: Professor Putricide)
     Professor Putricide: [4/3, 6/6, 6/4, 11/5, 2/6, 4/2, 1/1]
     Sylvanas Windrunner: [5/8, 5/6, 4/4, 5/1, 9/3, 5/4, 2/4]
     Shell Collector 4/3→4/0 DEAD  |  Wrath Weaver 5/8→5/4
     Wrath Weaver 5/4→5/0 DEAD  |  Trigore the Lasher 11/5→11/0 DEAD
     Ancestral Automaton 6/6→6/2  |  Nerubian Deathswarmer 4/4→4/0 DEAD
     Dustbone Devastator 5/6→6/0 DEAD  |  Ancestral Automaton 6/2→6/0 DEAD
     Ancestral Automaton 6/4→6/0 DEAD  |  Friendly Geist 10/3→10/0 DEAD
     Handless Forsaken 6/1→6/0 DEAD  |  Eternal Knight 4/2→5/0 DEAD
     Dustbone Devastator 2/6→3/4  |  Humming Bird 2/4→2/2
     Stomping Stegodon 5/4→5/3  |  Abyssal Bruiser 1/1→1/1
     Abyssal Bruiser 1/1→1/0 DEAD  |  Humming Bird 5/2→5/1
     Humming Bird 5/1→5/0 DEAD  |  Dustbone Devastator 3/4→3/0 DEAD
     Result: 0 vs 1 — heur
  [heur] Sneed vs [AGENT] Yogg-Saron, Hope's End (first: Sneed)
     Sneed: [7/1, 11/8, 8/1, 8/6, 9/10, 8/1, 3/5]
     Yogg-Saron, Hope's End: [3/6, 4/1, 4/3, 5/2]
     Harmless Bonehead 7/1→7/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Wrath Weaver 3/6→3/0 DEAD  |  Dustbone Devastator 8/6→8/3
     Nerubian Deathswarmer 11/8→11/3  |  Mummifier 5/2→5/0 DEAD
     Manasaber 4/1→4/1  |  Dustbone Devastator 8/3→8/0 DEAD
     Scarlet Skull 8/1→8/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: 4 vs 0 — heur
  [heur] Drek'Thar vs [heur] Inge, the Iron Hymn (first: Drek'Thar)
     Drek'Thar: [6/9, 2/5, 9/3, 5/6, 7/11, 5/4, 2/3]
     Inge, the Iron Hymn: [8/2, 5/2, 5/6, 5/6, 5/6, 4/4, 1/1]
     Lava Lurker 6/9→6/1  |  Eternal Knight 8/2→9/0 DEAD
     Mummifier 5/2→5/0 DEAD  |  Monstrous Macaw 5/4→5/0 DEAD
     Lava Lurker 2/5→2/0 DEAD  |  Technical Element 5/6→5/4
     Technical Element 5/6→5/0 DEAD  |  Lava Lurker 6/1→6/0 DEAD
     Trigore the Lasher 9/3→9/0 DEAD  |  Technical Element 5/4→5/0 DEAD
     Woodland Defiler 5/6→5/1  |  Woodland Defiler 5/6→5/1
     Woodland Defiler 5/1→5/0 DEAD  |  Woodland Defiler 5/1→5/0 DEAD
     Holo Rover 4/4→4/4  |  Deep-Sea Angler 2/3→2/0 DEAD
     Marquee Ticker 7/11→7/10  |  Harmless Bonehead 1/1→1/0 DEAD
     Result: 1 vs 1 — heur

  Alive: 8/8
  HP: Overlord Saurfang (HP=30, Tier=4) | Ysera (HP=30, Tier=4) | Sneed (HP=27, Tier=4) | Inge, the Iron Hymn (HP=27, Tier=4) | Drek'Thar (HP=27, Tier=4) | Sylvanas Windrunner (HP=24, Tier=4) | Yogg-Saron, Hope's End (HP=20, Tier=4) | Professor Putricide (HP=1, Tier=4)

### Turn 9

**Yogg-Saron, Hope's End** [RL AGENT]  HP=20 Armor=0 Gold=10 Tier=4

  Board (4/7): 3/6, 4/1, 4/3, 5/2
  Tavern (6 items): Sewer Rat 3/2 T2 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Rylak Metalhead 5/3 T4 $3 | Marquee Ticker 3/7 T4 $3 | Ominous Seer 2/1 T1 $3 | Sick Riffs (spell) T1 $3
  Hand: 1 cards

  → Board (5/7): 5/8, 4/3, 5/2, 3/7, 5/4
  → Gold 10→0 | HP 20→19 | Trinket: Mecha-Jaraxxus Sticker
  → Actions: buy_tavern_3, play_hand_1, buy_tavern_1, play_hand_1, refresh, sell_board_1, refresh

**Sneed** [Heuristic]  HP=27 Armor=0 Gold=10 Tier=4

  Board (7/7): 7/1, 11/8, 8/1 [Reborn], 8/6, 9/10, 8/1, 3/5
  Tavern (6 items): Soul Rewinder 4/1 T2 $3 | Seafloor Recruiter 3/5 T4 $3 | Zesty Shaker 6/7 T4 $3 | Deep-Sea Angler 2/3 T3 $3 | Shell Collector 4/3 T2 $3 | Angler's Lure (spell) T1 $3
  Hand: 0 cards

  → Board (7/7): 17/1, 21/8, 18/1 [Reborn], 18/6, 9/10, 18/1, 6/7
  → Tier 4→5 | Gold 10→0 | Trinket: Artisanal Urn
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=19 Gold=10 Tier=4

  Board (7/7): 14/15, 26/22, 23/22, 22/23, 21/23, 21/23, 20/22
  Tavern (6 items): Nerubian Deathswarmer 29/31 T2 $3 | Zesty Shaker 33/34 T4 $3 | Flaming Enforcer 31/32 T4 $3 | Technical Element 32/33 T3 $3 | Rylak Metalhead 32/30 T4 $3 | Gem Confiscation (spell) T4 $1
  Hand: 2 cards

  → Board (7/7): 26/22, 23/22, 22/23, 21/23, 21/23, 20/22, 33/34
  → Tier 4→5 | Gold 10→0 | Trinket: Ur'zul Sticker
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=9 Gold=11 Tier=4

  Board (7/7): 6/6 [G], 5/6, 2/8, 2/6, 4/4 [DS], 5/3, 3/3
  Tavern (6 items): Plaguerunner 4/2 T4 $3 | Waverider 2/8 T4 $3 | Sprightly Scarab 3/1 T3 $3 | Hardy Orca 1/6 T3 $3 | Monstrous Macaw 5/4 T4 $3 | Persistent Poet 2/3 T4 $3
  Hand: 2 cards

  → Board (7/7): 6/6 [G], 5/6, 2/8, 4/4 [DS], 7/5, 2/8, 5/4
  → Tier 4→5 | Gold 11→0 | Trinket: Drakkari Portrait
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=27 Armor=0 Gold=10 Tier=4

  Board (7/7): 9/2, 5/2, 5/6, 5/6, 5/6, 4/4 [DS], 1/1
  Tavern (5 items): Deep-Sea Angler 2/3 T3 $3 | Abyssal Bruiser 1/1 T4 $3 | Rylak Metalhead 5/3 T4 $3 | Dustbone Devastator 2/6 T3 $3 | Handless Forsaken 2/1 T3 $3
  Hand: 1 cards

  → Board (4/7): 9/2, 5/2, 5/6, 4/4 [DS]
  → Tier 4→5 | Gold 10→0 | Trinket: Accord-o-Tron Portrait
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=1 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/3, 6/6 [Taunt], 6/4, 11/6 [Taunt], 3/6, 5/2, 1/1 [DS]
  Tavern (5 items): Trigore the Lasher 9/3 T4 $3 | Risen Rider 3/1 T1 $3 | Banana Slamma 3/6 T4 $3 | Flaming Enforcer 4/5 T4 $3 | Lava Lurker 2/5 T2 $3
  Hand: 0 cards

  → Board (6/7): 4/3, 6/6 [Taunt], 6/4, 11/6 [Taunt], 3/6, 5/2
  → Tier 4→5 | Gold 10→0 | Trinket: Mechagon Adapter
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=4

  Board (7/7): 5/8, 6/6, 5/4, 6/1, 10/3, 4/4, 1/4
  Tavern (5 items): Plaguerunner 8/2 T4 $3 | Laboratory Assistant 3/4 T2 $3 | Holo Rover 4/4 T4 $3 | Laboratory Assistant 3/4 T2 $3 | Reef Riffer 3/2 T2 $3
  Hand: 0 cards

  → Board (7/7): 5/8, 16/6, 15/4, 16/1, 20/3, 4/4, 18/2
  → Tier 4→5 | Gold 10→0 | Trinket: Artisanal Urn
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=27 Armor=0 Gold=10 Tier=4

  Board (7/7): 6/9, 2/5, 9/5, 5/6, 7/11, 5/4, 2/3
  Tavern (5 items): Auto Assembler 2/2 T4 $3 | Shell Collector 4/3 T2 $3 | Reef Riffer 3/2 T2 $3 | Reef Riffer 3/2 T2 $3 | Humming Bird 1/4 T2 $3
  Hand: 2 cards

  → Board (6/7): 6/9, 2/5, 14/11, 7/11, 7/6 [Taunt], 4/3
  → Tier 4→5 | Gold 10→0 | Trinket: Lavish Cape | Hand 2→0
  → Actions: (auto)

**Combat Phase**

  [heur] Sneed vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Sneed: [17/1, 21/8, 18/1, 18/6, 9/10, 18/1, 6/7]
     Overlord Saurfang: [26/22, 23/22, 84/92, 21/23, 21/23, 20/22, 33/34]
     Mummifier 26/22→26/4  |  Handless Forsaken 18/1→18/0 DEAD
     Harmless Bonehead 17/1→17/0 DEAD  |  Flaming Enforcer 84/92→84/75
     Malchezaar, Prince of Dance 23/22→23/16  |  Zesty Shaker 6/7→6/0 DEAD
     Nerubian Deathswarmer 21/8→21/0 DEAD  |  Flaming Enforcer 84/75→84/54
     Flaming Enforcer 84/54→84/36  |  Scarlet Skull 18/1→18/0 DEAD
     Dustbone Devastator 19/8→20/0 DEAD  |  Malchezaar, Prince of Dance 23/16→23/0 DEAD
     Hunting Tiger Shark 21/23→21/14  |  Technical Element 9/10→9/0 DEAD
     Result: 0 vs 6 — heur
  [AGENT] Yogg-Saron, Hope's End vs [heur] Professor Putricide (first: Professor Putricide)
     Yogg-Saron, Hope's End: [5/8, 4/3, 5/2, 3/7, 5/4]
     Professor Putricide: [4/3, 6/6, 6/4, 11/6, 3/6, 5/2]
     Shell Collector 4/3→4/0 DEAD  |  Mummifier 5/2→5/0 DEAD
     Wrath Weaver 5/8→5/2  |  Ancestral Automaton 6/6→6/1
     Ancestral Automaton 6/1→6/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Marquee Ticker 3/7→3/0 DEAD  |  Trigore the Lasher 11/6→11/3
     Ancestral Automaton 6/4→6/0 DEAD  |  Malchezaar, Prince of Dance 5/4→5/0 DEAD
     Result: 1 vs 3 — AGENT
  [heur] Ysera vs [heur] Drek'Thar (first: Ysera)
     Ysera: [6/6, 5/6, 2/8, 4/4, 7/5, 2/8, 5/4]
     Drek'Thar: [6/9, 2/5, 14/11, 7/11, 7/6, 4/3]
     Scarlet Survivor 6/6→6/0 DEAD  |  Monstrous Macaw 7/6→7/0 DEAD
     Lava Lurker 6/9→6/7  |  Waverider 2/8→2/2
     Technical Element 5/6→5/2  |  Shell Collector 4/3→4/0 DEAD
     Lava Lurker 2/5→2/0 DEAD  |  Twilight Broodmother 7/5→7/3
     Waverider 2/2→2/0 DEAD  |  Marquee Ticker 7/11→7/9
     Trigore the Lasher 14/11→14/9  |  Waverider 2/8→2/0 DEAD
     Holo Rover 4/4→4/4  |  Lava Lurker 6/7→6/3
     Marquee Ticker 7/9→7/2  |  Twilight Broodmother 7/3→7/0 DEAD
     Monstrous Macaw 5/4→5/0 DEAD  |  Trigore the Lasher 14/9→14/1
     Result: 2 vs 3 — heur
  [heur] Sylvanas Windrunner vs [heur] Inge, the Iron Hymn (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [5/8, 16/6, 15/4, 16/1, 20/3, 4/4, 18/2]
     Inge, the Iron Hymn: [9/2, 5/2, 5/6, 7/7]
     Wrath Weaver 5/8→5/3  |  Woodland Defiler 5/6→5/1
     Eternal Knight 9/2→10/0 DEAD  |  Stomping Stegodon 4/4→4/0 DEAD
     Dustbone Devastator 16/6→17/1  |  Mummifier 5/2→5/0 DEAD
     Woodland Defiler 5/1→5/0 DEAD  |  Dustbone Devastator 17/1→17/0 DEAD
     Nerubian Deathswarmer 16/4→16/0 DEAD  |  Holo Rover 7/7→7/7
     Holo Rover 7/7→7/0 DEAD  |  Plaguerunner 19/2→22/0 DEAD
     Result: 3 vs 0 — heur

  Alive: 8/8
  HP: Overlord Saurfang (HP=30, Tier=5) | Ysera (HP=30, Tier=5) | Drek'Thar (HP=27, Tier=5) | Sylvanas Windrunner (HP=24, Tier=5) | Yogg-Saron, Hope's End (HP=19, Tier=4) | Inge, the Iron Hymn (HP=14, Tier=5) | Sneed (HP=12, Tier=5) | Professor Putricide (HP=1, Tier=5)

### Turn 10

**Yogg-Saron, Hope's End** [RL AGENT]  HP=19 Armor=0 Gold=10 Tier=4

  Board (5/7): 5/8, 4/3, 5/2, 3/7, 5/4
  Tavern (6 items): Handless Forsaken 2/1 T3 $3 | Stomping Stegodon 4/4 T4 $3 | Hardy Orca 1/6 T3 $3 | Prosthetic Hand 3/1 T4 $3 | Enchanted Sentinel 3/5 T4 $3 | Angler's Lure (spell) T1 $3
  Hand: 2 cards

  → Board (7/7): 5/8, 5/2, 3/7, 5/4, 4/4, 3/5, 6/7
  → Gold 10→0
  → Actions: buy_tavern_1, play_hand_2, buy_tavern_3, play_hand_2, refresh, sell_board_1, buy_tavern_1, play_hand_2, refresh

**Sneed** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=5

  Board (7/7): 18/1, 22/8, 19/1 [Reborn], 19/6, 9/10, 19/1, 6/7
  Tavern (6 items): Tichondrius 3/6 T5 $3 | Old Soul 20/4 T2 $3 | Friendly Geist 23/3 T4 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Rimescale Priestess 3/3 T4 $3 | Sanctify (spell) T5 $1
  Hand: 0 cards

  → Board (7/7): 22/8, 19/1 [Reborn], 19/6, 19/1, 23/3, 20/4, 3/3
  → Gold 10→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=19 Gold=10 Tier=5

  Board (7/7): 26/22, 23/22, 84/92, 21/23, 21/23, 20/22, 33/34
  Tavern (6 items): Monstrous Macaw 34/33 T4 $3 | Drustfallen Butcher 32/36 T5 $3 | Risen Rider 32/30 T1 $3 | Shadowdancer 34/32 T5 $3 | Bazaar Dealer 33/35 T5 $3 | Contracted Corpse (spell) T5 $3
  Hand: 2 cards

  → Board (7/7): 57/55, 116/122, 33/34, 32/36, 68/70, 34/32 [Taunt], 38/38
  → Gold 10→0 | Armor 19→16
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=9 Gold=10 Tier=5

  Board (7/7): 6/6 [G], 5/6, 2/8, 4/4 [DS], 7/5, 2/8, 5/4
  Tavern (7 items): Nerubian Deathswarmer 1/4 T2 $3 | Technical Element 5/6 T3 $3 | Drustfallen Butcher 2/7 T5 $3 | Woodland Defiler 5/6 T4 $3 | Darkcrest Strategist 4/5 T5 $3 | Channel the Devourer (spell) T5 $4 | Persistent Poet 2/3 T4 $3
  Hand: 5 cards

  → Board (7/7): 6/6 [G], 5/6, 9/7, 2/8, 7/8, 5/6, 2/4
  → Gold 10→0 | Hand 5→3
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=14 Armor=0 Gold=10 Tier=5

  Board (4/7): 10/2, 5/2, 5/6, 7/7 [DS]
  Tavern (6 items): Eternal Knight 10/2 T2 $3 | Annoy-o-Module 2/4 T3 $3 | Rylak Metalhead 5/3 T4 $3 | Eternal Tycoon 4/8 T5 $3 | Deep-Sea Angler 2/3 T3 $3 | Corrupted Cupcakes (spell) T5 $4
  Hand: 2 cards

  → Board (7/7): 10/2, 5/2, 5/6, 7/7 [DS], 10/2, 4/8, 5/3 [Taunt]
  → Gold 10→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=1 Armor=0 Gold=10 Tier=5

  Board (6/7): 4/3, 6/6 [Taunt], 6/4, 11/7 [Taunt], 3/6, 5/2
  Tavern (6 items): False Implicator 1/1 T3 $3 | Wrath Weaver 1/4 T1 $3 | Zesty Shaker 6/7 T4 $3 | Deep Blue Crooner 2/2 T3 $3 | Rimescale Priestess 3/3 T4 $3 | Wave of Gold (spell) T5 $2
  Hand: 0 cards

  → Board (7/7): 6/6 [Taunt], 6/4, 11/7 [Taunt], 3/6, 5/2, 6/7, 2/2
  → Gold 10→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=5

  Board (7/7): 5/8, 20/6, 19/4, 20/1, 24/3, 4/4, 22/2
  Tavern (6 items): Risen Rider 20/1 T1 $3 | Wintergrasp Ghoul 23/3 T5 $3 | Glowscale 4/6 T5 $3 | Alert Alarmist 2/2 T2 $3 | Accord-o-Tron 3/3 T3 $3 | Queen's Command (spell) T5 $2
  Hand: 0 cards

  → Board (7/7): 20/6, 19/4, 24/3, 22/2, 23/3, 20/1 [Taunt,Reborn], 2/2 [Taunt]
  → Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=27 Armor=0 Gold=10 Tier=5

  Board (6/7): 6/9, 2/5, 14/15, 7/11, 7/6 [Taunt], 4/3
  Tavern (6 items): Spiked Savior 8/2 T5 $3 | Humming Bird 1/4 T2 $3 | Deep Blue Crooner 2/2 T3 $3 | Drustfallen Butcher 2/7 T5 $3 | Auto Assembler 2/2 T4 $3 | Bargain Bundle (spell) T5 $5
  Hand: 1 cards

  → Board (7/7): 6/9, 14/15, 7/11, 7/6 [Taunt], 8/2 [Taunt,Reborn], 2/7, 2/2
  → Gold 10→0 | Hand 1→0
  → Actions: (auto)

**Combat Phase**

  [heur] Drek'Thar vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Drek'Thar: [6/9, 14/15, 7/11, 7/6, 8/2, 2/7, 2/2]
     Overlord Saurfang: [57/55, 186/201, 33/34, 32/36, 68/70, 34/32, 38/38]
     Malchezaar, Prince of Dance 57/55→57/48  |  Monstrous Macaw 7/6→7/0 DEAD
     Lava Lurker 6/9→6/0 DEAD  |  Shadowdancer 34/32→34/26
     Flaming Enforcer 186/201→186/193  |  Spiked Savior 8/2→8/0 DEAD
     Trigore the Lasher 14/15→14/0 DEAD  |  Shadowdancer 34/26→34/12
     Zesty Shaker 33/34→33/32  |  Drustfallen Butcher 2/7→2/0 DEAD
     Marquee Ticker 7/11→7/0 DEAD  |  Shadowdancer 34/12→34/5
     Drustfallen Butcher 32/36→32/34  |  Deep Blue Crooner 2/2→2/0 DEAD
     Result: 0 vs 7 — heur
  [heur] Inge, the Iron Hymn vs [heur] Professor Putricide (first: Professor Putricide)
     Inge, the Iron Hymn: [10/2, 5/2, 5/6, 10/10, 10/2, 4/8, 5/3]
     Professor Putricide: [6/6, 6/4, 11/7, 3/6, 5/2, 6/7, 2/2]
     Ancestral Automaton 6/6→6/1  |  Rylak Metalhead 5/3→5/0 DEAD
     Eternal Knight 10/2→11/0 DEAD  |  Trigore the Lasher 11/7→11/0 DEAD
     Ancestral Automaton 6/4→6/0 DEAD  |  Eternal Knight 11/2→13/0 DEAD
     Mummifier 5/2→5/0 DEAD  |  Dustbone Devastator 3/6→3/1
     Dustbone Devastator 3/1→4/0 DEAD  |  Eternal Tycoon 4/8→4/5
     Woodland Defiler 5/6→5/4  |  Deep Blue Crooner 2/2→2/0 DEAD
     Eternal Knight 5/2→6/0 DEAD  |  Holo Rover 10/10→10/10
     Holo Rover 10/10→10/4  |  Zesty Shaker 6/7→6/0 DEAD
     Result: 3 vs 0 — heur
  [AGENT] Yogg-Saron, Hope's End vs [heur] Ysera (first: Ysera)
     Yogg-Saron, Hope's End: [5/8, 5/2, 3/7, 5/4, 4/4, 3/5, 6/7]
     Ysera: [6/6, 5/6, 9/7, 2/8, 7/8, 5/6, 2/4]
     Scarlet Survivor 6/6→6/1  |  Wrath Weaver 5/8→5/2
     Wrath Weaver 5/2→5/0 DEAD  |  Nerubian Deathswarmer 2/4→2/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Zesty Shaker 6/7→6/2
     Mummifier 5/2→5/0 DEAD  |  Scarlet Survivor 6/1→6/0 DEAD
     Twilight Broodmother 9/7→9/4  |  Enchanted Sentinel 3/5→3/0 DEAD
     Marquee Ticker 3/7→3/5  |  Waverider 2/8→2/5
     Waverider 2/5→2/1  |  Stomping Stegodon 4/4→4/4
     Malchezaar, Prince of Dance 5/4→5/0 DEAD  |  Twilight Broodmother 9/4→9/0 DEAD
     Technical Element 7/8→7/5  |  Marquee Ticker 3/5→3/0 DEAD
     Stomping Stegodon 4/4→4/0 DEAD  |  Technical Element 7/5→7/1
     Woodland Defiler 5/6→5/0 DEAD  |  Zesty Shaker 6/2→6/0 DEAD
     Result: 0 vs 2 — heur
  [heur] Sylvanas Windrunner vs [heur] Sneed (first: Sneed)
     Sylvanas Windrunner: [20/6, 19/4, 24/3, 22/2, 23/3, 20/1, 2/2]
     Sneed: [22/8, 19/1, 19/6, 19/1, 23/3, 20/4, 3/3]
     Nerubian Deathswarmer 22/8→22/6  |  Alert Alarmist 2/2→2/0 DEAD
     Dustbone Devastator 20/6→21/0 DEAD  |  Dustbone Devastator 19/6→19/0 DEAD
     Scarlet Skull 19/1→19/0 DEAD  |  Risen Rider 21/1→21/0 DEAD
     Nerubian Deathswarmer 20/4→20/0 DEAD  |  Handless Forsaken 20/3→20/0 DEAD
     Friendly Geist 23/3→23/0 DEAD  |  Wintergrasp Ghoul 24/3→24/0 DEAD
     Friendly Geist 25/3→25/0 DEAD  |  Old Soul 20/4→20/0 DEAD
     Rimescale Priestess 3/3→3/0 DEAD  |  Plaguerunner 23/2→27/0 DEAD
     Result: 0 vs 1 — heur

  **Professor Putricide [Heuristic] eliminated!** (Turn 10)
  Alive: 7/8
  HP: Overlord Saurfang (HP=30, Tier=5) | Ysera (HP=30, Tier=5) | Sylvanas Windrunner (HP=17, Tier=5) | Inge, the Iron Hymn (HP=14, Tier=5) | Sneed (HP=12, Tier=5) | Drek'Thar (HP=12, Tier=5) | Yogg-Saron, Hope's End (HP=7, Tier=4)

### Turn 11

**Yogg-Saron, Hope's End** [RL AGENT]  HP=7 Armor=0 Gold=10 Tier=4

  Board (7/7): 5/8, 5/2, 3/7, 5/4, 4/4, 3/5, 6/7
  Tavern (6 items): Tide Raiser 2/1 T2 $3 | Tide Raiser 2/1 T2 $3 | Lava Lurker 2/5 T2 $3 | Stomping Stegodon 4/4 T4 $3 | Annoy-o-Module 2/4 T3 $3 | Boon of Beetles (spell) T4 $1
  Hand: 3 cards

  → Board (5/7): 3/7, 5/4, 4/4, 6/7, 4/4
  → Tier 4→5 | Gold 10→0
  → Actions: upgrade, sell_board_1, buy_tavern_3, play_hand_3, refresh, refresh, sell_board_0, refresh, sell_board_3, refresh

**Sneed** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=5

  Board (7/7): 22/8, 19/1 [Reborn], 19/6, 19/1, 23/3, 20/4, 3/3
  Tavern (6 items): Ashen Corruptor 6/6 T5 $3 | Sly Raptor 1/3 T3 $3 | Zesty Shaker 6/7 T4 $3 | Catacomb Crasher 21/10 T5 $3 | Rylak Metalhead 5/3 T4 $3 | Golden Touch (spell) T5 $5
  Hand: 1 cards

  → Board (7/7): 22/8, 19/1 [Reborn], 19/6, 19/1, 23/3, 20/4, 21/10
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=16 Gold=10 Tier=5

  Board (7/7): 57/55, 186/201, 33/34, 32/36, 68/70, 34/32 [Taunt], 38/38
  Tavern (6 items): Banana Slamma 40/43 T4 $3 | Annoy-o-Tron 38/39 T1 $3 | Darkcrest Strategist 41/42 T5 $3 | Friendly Geist 44/40 T4 $3 | Skeletal Strafer 44/43 T5 $3 | Upper Hand (spell) T5 $3
  Hand: 2 cards

  → Board (7/7): 57/55, 186/201, 33/34, 32/36, 68/70, 38/38, 44/43
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=9 Gold=10 Tier=5

  Board (7/7): 6/6 [G], 5/6, 9/7, 2/8, 7/8, 5/6, 2/4
  Tavern (6 items): Humming Bird 1/4 T2 $3 | Iridescent Skyblazer 3/8 T5 $3 | Wyvern Outrider 2/8 T4 $3 | Flaming Enforcer 4/5 T4 $3 | Charging Czarina 4/1 T5 $3 | Sleepy Supporter 4/3 T2 $3
  Hand: 4 cards

  → Board (7/7): 6/6 [G], 5/6, 9/7, 2/8, 9/10, 5/6, 3/8
  → Tier 5→6 | Gold 10→0 | Hand 4→3
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=14 Armor=0 Gold=10 Tier=5

  Board (7/7): 13/2, 5/2, 5/6, 10/10 [DS], 13/2, 4/8, 5/3 [Taunt]
  Tavern (5 items): Hunting Tiger Shark 3/5 T4 $3 | Deflect-o-Bot 3/2 T3 $3 | Famished Felbat 6/3 T5 $3 | Ashen Corruptor 6/6 T5 $3 | Ancestral Automaton 3/4 T2 $3
  Hand: 3 cards

  → Board (7/7): 13/2, 5/6, 10/10 [DS], 13/2, 4/8, 5/3 [Taunt], 6/6
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=17 Armor=0 Gold=10 Tier=5

  Board (7/7): 25/6, 24/4, 29/3, 27/2, 28/3, 25/1 [Taunt,Reborn], 2/2 [Taunt]
  Tavern (5 items): Monstrous Macaw 5/4 T4 $3 | Flaming Enforcer 4/5 T4 $3 | Risen Rider 25/1 T1 $3 | Sinrunner Blanchy 31/8 T5 $3 | Auto Assembler 2/2 T4 $3
  Hand: 1 cards

  → Board (7/7): 25/6, 24/4, 29/3, 27/2, 28/3, 25/1 [Taunt,Reborn], 31/8 [Reborn]
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=5

  Board (7/7): 6/9, 14/19, 7/11, 7/6 [Taunt], 8/2 [Taunt,Reborn], 2/7, 2/2
  Tavern (5 items): Annoy-o-Tron 1/2 T1 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Eternal Tycoon 4/8 T5 $3 | Stomping Stegodon 4/4 T4 $3 | Malchezaar, Prince of Dance 5/4 T4 $3
  Hand: 2 cards

  → Board (6/7): 6/9, 14/19, 7/11, 7/6 [Taunt], 8/2 [Taunt,Reborn], 6/7
  → Tier 5→6 | Gold 10→0 | Hand 2→1
  → Actions: (auto)

**Combat Phase**

  [heur] Sylvanas Windrunner vs [heur] Drek'Thar (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [25/6, 24/4, 29/3, 27/2, 28/3, 25/1, 31/8]
     Drek'Thar: [6/9, 14/19, 7/11, 7/6, 8/2, 6/7]
     Dustbone Devastator 25/6→26/0 DEAD  |  Spiked Savior 8/2→8/0 DEAD
     Lava Lurker 6/9→6/0 DEAD  |  Risen Rider 26/1→26/0 DEAD
     Nerubian Deathswarmer 25/4→25/0 DEAD  |  Monstrous Macaw 7/6→7/0 DEAD
     Trigore the Lasher 14/19→14/0 DEAD  |  Friendly Geist 30/3→30/0 DEAD
     Plaguerunner 28/2→33/0 DEAD  |  Drustfallen Butcher 6/7→6/0 DEAD
     Marquee Ticker 7/11→7/0 DEAD  |  Wintergrasp Ghoul 34/3→34/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Overlord Saurfang vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Overlord Saurfang: [59/57, 269/288, 35/36, 34/38, 70/72, 40/40, 46/45]
     Inge, the Iron Hymn: [13/2, 5/6, 13/13, 13/2, 4/8, 5/3, 6/6]
     Eternal Knight 13/2→14/0 DEAD  |  Zesty Shaker 35/36→35/23
     Malchezaar, Prince of Dance 59/57→59/52  |  Rylak Metalhead 5/3→5/0 DEAD
     Woodland Defiler 5/6→5/0 DEAD  |  Bazaar Dealer 70/72→70/67
     Flaming Enforcer 269/288→269/284  |  Eternal Tycoon 4/8→4/0 DEAD
     Holo Rover 13/13→13/13  |  Malchezaar, Prince of Dance 59/52→59/39
     Zesty Shaker 35/23→35/8  |  Eternal Knight 15/2→16/0 DEAD
     Ashen Corruptor 6/6→6/0 DEAD  |  Malchezaar, Prince of Dance 59/39→59/33
     Drustfallen Butcher 34/24→34/11  |  Holo Rover 13/13→13/0 DEAD
     Result: 7 vs 0 — heur
  [heur] Sneed vs [AGENT] Yogg-Saron, Hope's End (first: Sneed)
     Sneed: [22/8, 19/1, 19/6, 19/1, 23/3, 20/4, 21/10]
     Yogg-Saron, Hope's End: [3/7, 5/4, 4/4, 6/7, 4/4]
     Nerubian Deathswarmer 22/8→22/4  |  Stomping Stegodon 4/4→4/4
     Marquee Ticker 3/7→3/0 DEAD  |  Scarlet Skull 19/1→19/0 DEAD
     Dustbone Devastator 19/6→20/1  |  Malchezaar, Prince of Dance 5/4→5/0 DEAD
     Stomping Stegodon 4/4→4/4  |  Catacomb Crasher 23/12→23/8
     Handless Forsaken 20/1→20/0 DEAD  |  Zesty Shaker 6/7→6/0 DEAD
     Stomping Stegodon 7/4→7/0 DEAD  |  Friendly Geist 24/3→24/0 DEAD
     Old Soul 21/4→21/0 DEAD  |  Stomping Stegodon 7/4→7/0 DEAD
     Result: 3 vs 0 — heur

  **Yogg-Saron, Hope's End [AGENT] eliminated!** (Turn 11)
  **Inge, the Iron Hymn [Heuristic] eliminated!** (Turn 11)
  Alive: 5/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Ysera (HP=30, Tier=6) | Sylvanas Windrunner (HP=17, Tier=6) | Sneed (HP=12, Tier=6) | Drek'Thar (HP=1, Tier=6)

### Turn 12

**Sneed** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=6

  Board (7/7): 23/8, 20/1 [Reborn], 20/6, 20/1, 24/3, 21/4, 22/10
  Tavern (7 items): Ancestral Automaton 3/4 T2 $3 | Imposing Percussionist 4/4 T4 $3 | Darkcrest Strategist 4/5 T5 $3 | Sly Raptor 1/3 T3 $3 | Scrap Scraper 6/5 T5 $3 | Tranquil Meditative 3/8 T5 $3 | Azerite Empowerment (spell) T6 $4
  Hand: 1 cards

  → Board (7/7): 23/8, 20/6, 20/1, 24/3, 21/4, 22/10, 3/4
  → Gold 10→0 | HP 12→8 | Hand 1→2
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=16 Gold=10 Tier=6

  Board (7/7): 59/57, 269/288, 35/36, 34/38, 70/72, 40/40, 46/45
  Tavern (7 items): Tidemistress Athissa 45/46 T6 $3 | Spiked Savior 47/41 T5 $3 | P-0UL-TR-0N 49/49 T6 $3 | Cadaver Caretaker 43/42 T3 $3 | Spiked Savior 47/41 T5 $3 | Ancestral Automaton 3/4 T2 $3 | Eyes of the Earth Mother (spell) T6 $4
  Hand: 2 cards

  → Board (7/7): 59/57, 269/288, 70/72, 46/45, 49/49, 45/46, 43/42
  → Gold 10→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=9 Gold=10 Tier=6

  Board (7/7): 6/6 [G], 5/6, 9/7, 2/8, 9/10, 5/6, 3/8
  Tavern (8 items): Ruthless Queensguard 3/3 T6 $3 | Iridescent Skyblazer 3/8 T5 $3 | Flaming Enforcer 4/5 T4 $3 | Sewer Rat 3/2 T2 $3 | Sinrunner Blanchy 9/8 T5 $3 | Zesty Shaker 6/7 T4 $3 | Lost Staff of Hamuul (spell) T6 $2 | Incubation Researcher 2/8 T4 $3
  Hand: 4 cards

  → Board (7/7): 8/8 [G], 9/7, 9/10, 9/8 [Reborn], 6/7, 3/8, 4/5
  → Gold 10→0 | Hand 4→3
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=17 Armor=0 Gold=10 Tier=6

  Board (7/7): 31/6, 30/4, 35/3, 33/2, 34/3, 31/1 [Taunt,Reborn], 37/8 [Reborn]
  Tavern (7 items): Glowscale 4/6 T5 $3 | Reef Riffer 3/2 T2 $3 | Sinrunner Blanchy 37/8 T5 $3 | One-Amalgam Tour Group 35/7 T6 $3 | Famished Felbat 6/3 T5 $3 | Soul Rewinder 4/1 T2 $3 | Tomb Turning (spell) T4 $2
  Hand: 2 cards

  → Board (7/7): 33/8, 37/5, 36/5, 39/10 [Reborn], 39/10 [Reborn], 35/7, 4/3
  → Gold 10→0 | HP 17→16
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=1 Armor=0 Gold=10 Tier=6

  Board (6/7): 6/9, 14/24, 7/11, 7/6 [Taunt], 8/2 [Taunt,Reborn], 6/7
  Tavern (7 items): Flaming Enforcer 4/5 T4 $3 | Hardy Orca 1/6 T3 $3 | Handless Forsaken 2/1 T3 $3 | Divine Sparkbot 4/2 T5 $3 | Old Soul 3/4 T2 $3 | Waverider 2/8 T4 $3 | Knockoff Wisdomball (spell) T6 $4
  Hand: 3 cards

  → Board (5/7): 6/9, 14/24, 7/11, 7/6 [Taunt], 2/8
  → Gold 10→0 | Hand 3→1
  → Actions: (auto)

**Combat Phase**

  [heur] Ysera vs [heur] Sylvanas Windrunner (first: Ysera)
     Ysera: [8/8, 9/7, 9/10, 9/8, 6/7, 3/8, 7/8]
     Sylvanas Windrunner: [33/8, 37/5, 36/5, 39/10, 39/10, 35/7, 4/3]
     Scarlet Survivor 8/8→8/0 DEAD  |  Sinrunner Blanchy 39/10→39/2
     Dustbone Devastator 33/8→34/0 DEAD  |  Sinrunner Blanchy 9/8→9/0 DEAD
     Twilight Broodmother 9/7→9/0 DEAD  |  Wintergrasp Ghoul 37/5→37/0 DEAD
     Friendly Geist 38/5→38/0 DEAD  |  Technical Element 9/10→9/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Sinrunner Blanchy 40/10→40/4
     Sinrunner Blanchy 40/4→40/1  |  Iridescent Skyblazer 3/8→3/0 DEAD
     Flaming Enforcer 7/8→7/0 DEAD  |  Sinrunner Blanchy 40/1→40/0 DEAD
     Result: 0 vs 3 — heur
  [heur] Overlord Saurfang vs [heur] Sneed (first: Sneed)
     Overlord Saurfang: [61/59, 274/294, 72/74, 48/47, 51/51, 47/48, 45/44]
     Sneed: [23/8, 20/6, 20/1, 24/3, 21/4, 22/10, 3/4]
     Nerubian Deathswarmer 23/8→23/0 DEAD  |  Cadaver Caretaker 45/44→45/21
     Malchezaar, Prince of Dance 61/59→61/39  |  Handless Forsaken 20/1→20/0 DEAD
     Dustbone Devastator 20/6→21/0 DEAD  |  P-0UL-TR-0N 51/51→51/31
     Flaming Enforcer 274/294→274/271  |  Catacomb Crasher 23/10→23/0 DEAD
     Friendly Geist 25/3→25/0 DEAD  |  Malchezaar, Prince of Dance 61/39→61/14
     Bazaar Dealer 72/74→72/52  |  Old Soul 22/4→22/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Bazaar Dealer 72/52→72/49
     Result: 7 vs 0 — heur

  **Sneed [Heuristic] eliminated!** (Turn 12)
  Alive: 4/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Ysera (HP=24, Tier=6) | Sylvanas Windrunner (HP=16, Tier=6) | Drek'Thar (HP=1, Tier=6)

### Turn 13

**Overlord Saurfang** [Heuristic]  HP=30 Armor=16 Gold=10 Tier=6

  Board (7/7): 61/59, 274/294, 72/74, 48/47, 51/51, 47/48, 45/44
  Tavern (7 items): Wintergrasp Ghoul 51/48 T5 $3 | Ashen Corruptor 51/51 T5 $3 | Glowscale 49/51 T5 $3 | Sewer Lord 49/51 T5 $3 | Rabid Panther 49/53 T6 $3 | Nerubian Deathswarmer 47/49 T2 $3 | Tomb Turning (spell) T4 $2
  Hand: 2 cards

  → Board (7/7): 61/59, 321/343, 72/74, 51/51, 51/51, 50/54, 50/52
  → Gold 10→0 | Armor 16→14
  → Actions: (auto)

**Ysera** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=6

  Board (7/7): 8/8 [G], 9/7, 9/10, 9/8 [Reborn], 6/7, 3/8, 7/8
  Tavern (8 items): Lurking Leviathan 3/8 T5 $3 | Imposing Percussionist 4/4 T4 $3 | Consummate Conqueror 9/7 T6 $3 | Eternal Knight 4/2 T2 $3 | Darkcrest Strategist 4/5 T5 $3 | Enchanted Sentinel 3/5 T4 $3 | Butchering (spell) T5 $2 | Kalecgos, Arcane Aspect 4/12 T5 $3
  Hand: 3 cards

  → Board (7/7): 9/9 [G], 10/8, 9/10, 9/8 [Reborn], 9/7, 5/13, 4/4
  → Gold 10→0 | HP 24→20 | Hand 3→4
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=16 Armor=0 Gold=10 Tier=6

  Board (7/7): 34/8, 38/5, 37/5, 40/10 [Reborn], 40/10 [Reborn], 36/7, 4/3
  Tavern (7 items): Soul Rewinder 4/1 T2 $3 | Void Pup Trainer 7/7 T5 $3 | Spiked Savior 8/2 T5 $3 | Nightmare Par-tea Guest 33/3 T5 $3 | Ancestral Automaton 3/4 T2 $3 | Skeletal Strafer 36/6 T5 $3 | Perfect Vision (spell) T6 $2
  Hand: 4 cards

  → Board (7/7): 38/12, 42/9, 41/9, 50/20 [Reborn], 44/14 [Reborn], 40/10, 6/5
  → Gold 10→0 | HP 16→15
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=1 Armor=0 Gold=10 Tier=6

  Board (5/7): 6/9, 14/27, 7/11, 7/6 [Taunt], 2/8
  Tavern (7 items): Laboratory Assistant 3/4 T2 $3 | Humming Bird 1/4 T2 $3 | Prosthetic Hand 3/1 T4 $3 | Consummate Conqueror 9/7 T6 $3 | Cadaver Caretaker 3/3 T3 $3 | Metallic Hunter 4/2 T2 $3 | Rime or Reason (spell) T1 $3
  Hand: 3 cards

  → Board (7/7): 6/9, 14/27, 7/11, 7/6 [Taunt], 6/12 [WF], 9/7, 4/2
  → Gold 10→0 | Hand 3→1
  → Actions: (auto)

**Combat Phase**

  [heur] Ysera vs [heur] Drek'Thar (first: Ysera)
     Ysera: [9/9, 10/8, 9/10, 9/8, 9/7, 5/13, 4/4]
     Drek'Thar: [6/9, 14/27, 7/11, 7/6, 6/12, 9/7, 4/2]
     Scarlet Survivor 9/9→9/2  |  Monstrous Macaw 7/6→7/0 DEAD
     Lava Lurker 6/9→6/0 DEAD  |  Sinrunner Blanchy 9/8→9/2
     Twilight Broodmother 10/8→10/1  |  Marquee Ticker 7/11→7/1
     Trigore the Lasher 14/27→14/18  |  Sinrunner Blanchy 9/2→9/0 DEAD
     Technical Element 9/10→9/4  |  Waverider 6/12→6/3
     Marquee Ticker 7/1→7/0 DEAD  |  Consummate Conqueror 9/7→9/0 DEAD
     Kalecgos, Arcane Aspect 5/13→5/9  |  Metallic Hunter 4/2→4/0 DEAD
     Waverider 6/3→6/0 DEAD  |  Kalecgos, Arcane Aspect 5/9→5/3
     Imposing Percussionist 4/4→4/0 DEAD  |  Trigore the Lasher 14/18→14/14
     Consummate Conqueror 9/7→9/0 DEAD  |  Technical Element 9/4→9/0 DEAD
     Result: 3 vs 1 — heur
  [heur] Sylvanas Windrunner vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Sylvanas Windrunner: [39/13, 43/10, 42/10, 51/21, 45/15, 41/11, 6/6]
     Overlord Saurfang: [61/59, 321/343, 72/74, 51/51, 51/51, 50/54, 50/52]
     Malchezaar, Prince of Dance 61/59→61/17  |  Wintergrasp Ghoul 42/10→42/0 DEAD
     Dustbone Devastator 39/13→40/0 DEAD  |  Rabid Panther 50/54→50/15
     Flaming Enforcer 321/343→321/297  |  Sinrunner Blanchy 46/15→46/0 DEAD
     Friendly Geist 45/11→45/0 DEAD  |  Bazaar Dealer 72/74→72/29
     Bazaar Dealer 72/29→72/0 DEAD  |  Sinrunner Blanchy 53/22→53/0 DEAD
     Skeletal Strafer 44/13→44/0 DEAD  |  Sewer Lord 50/52→50/8
     P-0UL-TR-0N 51/51→51/45  |  Ancestral Automaton 6/8→6/0 DEAD
     Result: 0 vs 6 — heur

  **Sylvanas Windrunner [Heuristic] eliminated!** (Turn 13)
  Alive: 3/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Ysera (HP=20, Tier=6) | Drek'Thar (HP=1, Tier=6)

### Turn 14

**Overlord Saurfang** [Heuristic]  HP=30 Armor=14 Gold=10 Tier=6

  Board (7/7): 61/59, 321/343, 72/74, 51/51, 51/51, 50/54, 50/52
  Tavern (7 items): Old Soul 54/54 T2 $3 | Laboratory Assistant 53/54 T2 $3 | Sewer Rat 53/52 T2 $3 | Shell Collector 54/53 T2 $3 | Tranquil Meditative 53/58 T5 $3 | Lava Lurker 52/55 T2 $3 | Misplaced Tea Set (spell) T4 $2
  Hand: 2 cards

  → Board (7/7): 61/59, 374/395, 72/74, 54/59, 54/54, 55/54, 53/56
  → Gold 10→0 | Armor 14→13
  → Actions: (auto)

**Ysera** [Heuristic]  HP=20 Armor=0 Gold=10 Tier=6

  Board (7/7): 9/9 [G], 10/8, 9/10, 9/8 [Reborn], 9/7, 5/13, 4/4
  Tavern (8 items): Tichondrius 3/6 T5 $3 | Sprightly Scarab 3/1 T3 $3 | Moonsteel Juggernaut 8/8 T6 $3 | Metallic Hunter 4/2 T2 $3 | Rabid Panther 4/8 T6 $3 | Deathly Striker 9/8 T6 $3 | Tomb Turning (spell) T4 $2 | Roaring Recruiter 2/8 T3 $3
  Hand: 4 cards

  → Board (7/7): 9/9 [G], 10/8, 9/10, 9/8 [Reborn], 5/13, 9/8, 3/6
  → Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=1 Armor=0 Gold=10 Tier=6

  Board (7/7): 6/9, 14/30, 7/11, 7/6 [Taunt], 6/12 [WF], 9/7, 4/2
  Tavern (7 items): Deep Blue Crooner 2/2 T3 $3 | Nightmare Par-tea Guest 3/3 T5 $3 | Glowscale 4/6 T5 $3 | Tranquil Meditative 3/8 T5 $3 | Scarlet Skull 2/1 T2 $3 | Woodland Defiler 5/6 T4 $3 | Deepwater Clan (spell) T4 $2
  Hand: 4 cards

  → Board (7/7): 6/9, 14/30, 7/11, 9/8 [Taunt], 6/12 [WF], 9/7, 2/2
  → Gold 10→2 | Hand 4→2
  → Actions: (auto)

**Combat Phase**

  [heur] Drek'Thar vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Drek'Thar: [6/9, 14/30, 7/11, 9/8, 6/12, 9/7, 2/2]
     Overlord Saurfang: [61/59, 374/395, 72/74, 54/59, 54/54, 55/54, 53/56]
     Malchezaar, Prince of Dance 61/59→61/50  |  Monstrous Macaw 9/8→9/0 DEAD
     Lava Lurker 6/9→6/0 DEAD  |  Lava Lurker 53/56→53/50
     Flaming Enforcer 374/395→374/389  |  Waverider 6/12→6/0 DEAD
     Trigore the Lasher 14/30→14/0 DEAD  |  Old Soul 54/54→54/40
     Bazaar Dealer 72/74→72/67  |  Marquee Ticker 7/11→7/0 DEAD
     Consummate Conqueror 9/7→9/0 DEAD  |  Lava Lurker 53/50→53/41
     Tranquil Meditative 54/59→54/57  |  Deep Blue Crooner 2/2→2/0 DEAD
     Result: 0 vs 7 — heur

  **Drek'Thar [Heuristic] eliminated!** (Turn 14)
  Alive: 2/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Ysera (HP=20, Tier=6)

### Turn 15

**Overlord Saurfang** [Heuristic]  HP=30 Armor=13 Gold=10 Tier=6

  Board (7/7): 61/59, 374/395, 72/74, 54/59, 54/54, 55/54, 53/56
  Tavern (7 items): Hunting Tiger Shark 56/58 T4 $3 | Wrath Weaver 54/57 T1 $3 | Accord-o-Tron 56/56 T3 $3 | Plaguerunner 58/55 T4 $3 | Abyssal Bruiser 1/1 T4 $3 | Waverider 55/61 T4 $3 | Friendly Bounty (spell) T3 $2
  Hand: 3 cards

  → Board (7/7): 62/60, 374/395, 72/74, 56/62, 56/58, 58/55, 54/57
  → Gold 10→0 | Armor 13→12
  → Actions: (auto)

**Ysera** [Heuristic]  HP=20 Armor=0 Gold=10 Tier=6

  Board (7/7): 9/9 [G], 10/8, 9/7, 9/8 [Reborn], 5/13, 9/8, 3/6
  Tavern (8 items): Accord-o-Tron 3/3 T3 $3 | Technical Element 5/6 T3 $3 | P-0UL-TR-0N 10/10 T6 $3 | Darkcrest Strategist 4/5 T5 $3 | Humming Bird 1/4 T2 $3 | Cadaver Caretaker 4/3 T3 $3 | Careful Investment (spell) T3 $1 | Kalecgos, Arcane Aspect 4/12 T5 $3
  Hand: 4 cards

  → Board (7/7): 9/9 [G], 10/8, 9/8 [Reborn], 5/13, 9/8, 10/10, 4/3
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Ysera (first: Ysera)
     Overlord Saurfang: [62/60, 374/395, 72/74, 56/62, 56/58, 58/55, 54/57]
     Ysera: [9/9, 10/8, 9/8, 5/13, 9/8, 10/10, 4/3]
     Scarlet Survivor 9/9→10/0 DEAD  |  Bazaar Dealer 72/74→72/65
     Malchezaar, Prince of Dance 62/60→62/51  |  Sinrunner Blanchy 9/8→9/0 DEAD
     Twilight Broodmother 10/8→11/0 DEAD  |  Bazaar Dealer 72/65→72/55
     Flaming Enforcer 374/395→374/385  |  P-0UL-TR-0N 10/10→10/0 DEAD
     Kalecgos, Arcane Aspect 5/13→6/0 DEAD  |  Wrath Weaver 54/57→54/52
     Bazaar Dealer 72/55→72/46  |  Deathly Striker 9/8→9/0 DEAD
     Cadaver Caretaker 4/3→4/0 DEAD  |  Malchezaar, Prince of Dance 62/51→62/47
     Result: 7 vs 0 — heur

  **Overlord Saurfang [Heuristic] eliminated!** (Turn 15)
  **Ysera [Heuristic] eliminated!** (Turn 15)

---

## Final Standings

| # | Hero | Role | HP | Tier | Eliminated |
|---|---|---|---|---|---|
| 1 | Overlord Saurfang | Heuristic | 30 | 6 | 15 |
| 2 | Ysera | Heuristic | 0 | 6 | 15 |
| 3 | Drek'Thar | Heuristic | 0 | 6 | 14 |
| 4 | Sylvanas Windrunner | Heuristic | 0 | 6 | 13 |
| 5 | Sneed | Heuristic | 0 | 6 | 12 |
| 6 | Yogg-Saron, Hope's End | AGENT | 0 | 5 | 11 |
| 7 | Inge, the Iron Hymn | Heuristic | 0 | 6 | 11 |
| 8 | Professor Putricide | Heuristic | 0 | 5 | 10 |