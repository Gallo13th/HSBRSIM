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

  → Actions: 

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

  [heur] Overlord Saurfang vs [heur] Drek'Thar (first: Drek'Thar)
     Overlord Saurfang: [2/5]
     Drek'Thar: [2/1]
     Risen Rider 2/1→2/0 DEAD  |  Wrath Weaver 2/5→2/3
     Result: 1 vs 0 — heur
  [heur] Sneed vs [heur] Professor Putricide (first: Sneed)
     Sneed: [2/1]
     Professor Putricide: [4/1]
     Ominous Seer 2/1→2/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: 0 vs 0 — draw
  [heur] Ysera vs [AGENT] Yogg-Saron, Hope's End (first: Ysera)
     Ysera: [3/3]
     Yogg-Saron, Hope's End: []
     Result: 1 vs 0 — heur
  [heur] Sylvanas Windrunner vs [heur] Inge, the Iron Hymn (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [2/1]
     Inge, the Iron Hymn: [4/1]
     Risen Rider 2/1→2/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: 0 vs 0 — draw

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=1) | Sneed (HP=30, Tier=1) | Overlord Saurfang (HP=30, Tier=1) | Ysera (HP=30, Tier=1) | Inge, the Iron Hymn (HP=30, Tier=1) | Professor Putricide (HP=30, Tier=1) | Sylvanas Windrunner (HP=30, Tier=1) | Drek'Thar (HP=30, Tier=1)

### Turn 2

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=16 Gold=4 Tier=1

  Board: (empty)
  Tavern (4 items): Annoy-o-Tron 1/2 T1 $3 | Manasaber 4/1 T1 $3 | Picky Eater 1/1 T1 $3 | Sick Riffs (spell) T1 $3
  Hand: 0 cards

  → Board (1/7): 4/1
  → Gold 4→1
  → Actions: buy_tavern_1, play_hand_0

**Sneed** [Heuristic]  HP=30 Armor=12 Gold=4 Tier=1

  Board (1/7): 2/1
  Tavern (4 items): Wrath Weaver 1/4 T1 $3 | Risen Rider 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Fortify (spell) T1 $1
  Hand: 0 cards

  → Board (2/7): 2/1, 1/4
  → Gold 4→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=18 Gold=4 Tier=1

  Board (1/7): 2/5
  Tavern (4 items): Harmless Bonehead 3/3 T1 $3 | Ominous Seer 4/3 T1 $3 | Wrath Weaver 3/6 T1 $3 | Enchanted Lasso (spell) T1 $2
  Hand: 0 cards

  → Board (2/7): 4/7, 3/6
  → Gold 4→0 | Armor 18→17
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=12 Gold=4 Tier=1

  Board (1/7): 3/3
  Tavern (5 items): Risen Rider 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Meditation (spell) T1 $3 | Scarlet Survivor 3/3 T1 $3
  Hand: 0 cards

  → Board (2/7): 3/3, 3/3
  → Gold 4→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=4 Tier=1

  Board (1/7): 4/1
  Tavern (4 items): Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Angler's Lure (spell) T1 $3
  Hand: 0 cards

  → Board (2/7): 4/1, 1/2 [Taunt,DS]
  → Gold 4→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=10 Gold=4 Tier=1

  Board (1/7): 4/1
  Tavern (4 items): Ominous Seer 2/1 T1 $3 | Ominous Seer 2/1 T1 $3 | Risen Rider 2/1 T1 $3 | Tavern Dish Banana (spell) T1 $1
  Hand: 0 cards

  → Board (2/7): 4/1, 2/1
  → Gold 4→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=10 Gold=4 Tier=1

  Board (1/7): 2/1 [Taunt,Reborn]
  Tavern (4 items): Wrath Weaver 1/4 T1 $3 | Manasaber 4/1 T1 $3 | Risen Rider 2/1 T1 $3 | Tavern Coin (spell) T1 $1
  Hand: 0 cards

  → Board (2/7): 2/1 [Taunt,Reborn], 1/4
  → Gold 4→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=4 Tier=1

  Board (1/7): 2/1 [Taunt,Reborn]
  Tavern (4 items): Harmless Bonehead 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | The Goldenizer (spell) T1 $0
  Hand: 0 cards

  → Board (2/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS]
  → Gold 4→0
  → Actions: (auto)

**Combat Phase**

  [heur] Inge, the Iron Hymn vs [heur] Drek'Thar (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2]
     Drek'Thar: [2/1, 1/2]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Result: 1 vs 1 — heur
  [AGENT] Yogg-Saron, Hope's End vs [heur] Professor Putricide (first: Professor Putricide)
     Yogg-Saron, Hope's End: [4/1]
     Professor Putricide: [4/1, 2/1]
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: 0 vs 1 — heur
  [heur] Ysera vs [heur] Sneed (first: Sneed)
     Ysera: [3/3, 3/3]
     Sneed: [2/1, 1/4]
     Ominous Seer 2/1→2/0 DEAD  |  Scarlet Survivor 3/3→3/1
     Scarlet Survivor 3/3→3/2  |  Wrath Weaver 1/4→1/1
     Wrath Weaver 1/1→1/0 DEAD  |  Scarlet Survivor 3/1→3/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Overlord Saurfang vs [heur] Sylvanas Windrunner (first: Overlord Saurfang)
     Overlord Saurfang: [4/7, 3/6]
     Sylvanas Windrunner: [2/1, 1/4]
     Wrath Weaver 4/7→4/5  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 1/4→1/1  |  Wrath Weaver 3/6→3/5
     Wrath Weaver 3/5→3/4  |  Wrath Weaver 1/1→1/0 DEAD
     Result: 2 vs 0 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=1) | Sneed (HP=30, Tier=1) | Overlord Saurfang (HP=30, Tier=1) | Ysera (HP=30, Tier=1) | Inge, the Iron Hymn (HP=30, Tier=1) | Professor Putricide (HP=30, Tier=1) | Sylvanas Windrunner (HP=30, Tier=1) | Drek'Thar (HP=30, Tier=1)

### Turn 3

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=14 Gold=5 Tier=1

  Board (1/7): 4/1
  Tavern (3 items): Risen Rider 2/1 T1 $3 | Cord Puller 1/1 T1 $3 | Ominous Seer 2/1 T1 $3
  Hand: 0 cards

  → Actions: 

**Sneed** [Heuristic]  HP=30 Armor=10 Gold=5 Tier=1

  Board (2/7): 2/1, 1/4
  Tavern (3 items): Manasaber 4/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Picky Eater 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1, 1/4, 4/1
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=5 Tier=1

  Board (2/7): 4/7, 3/6
  Tavern (3 items): Cord Puller 5/5 T1 $3 | Wrath Weaver 5/8 T1 $3 | Surf n' Surf 5/5 T1 $3
  Hand: 0 cards

  → Board (1/7): 11/17 [G]
  → Tier 1→2 | Gold 5→0 | Hand 0→1
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=12 Gold=5 Tier=1

  Board (2/7): 3/3, 3/3
  Tavern (4 items): Wrath Weaver 1/4 T1 $3 | Risen Rider 2/1 T1 $3 | Cord Puller 1/1 T1 $3 | Scarlet Survivor 3/3 T1 $3
  Hand: 0 cards

  → Board (1/7): 6/6 [G]
  → Tier 1→2 | Gold 5→0 | Hand 0→1
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=5 Tier=1

  Board (2/7): 4/1, 1/2 [Taunt,DS]
  Tavern (3 items): Cord Puller 1/1 T1 $3 | Cord Puller 1/1 T1 $3 | Cord Puller 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 4/1, 1/2 [Taunt,DS], 1/1 [DS]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=10 Gold=5 Tier=1

  Board (2/7): 4/1, 2/1
  Tavern (3 items): Risen Rider 2/1 T1 $3 | Risen Rider 2/1 T1 $3 | Surf n' Surf 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 4/1, 2/1, 2/1 [Taunt,Reborn]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=7 Gold=5 Tier=1

  Board (2/7): 2/1 [Taunt,Reborn], 1/4
  Tavern (3 items): Annoy-o-Tron 1/2 T1 $3 | Risen Rider 2/1 T1 $3 | Cord Puller 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1 [Taunt,Reborn], 1/4, 1/2 [Taunt,DS]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=5 Tier=1

  Board (2/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS]
  Tavern (3 items): Wrath Weaver 1/4 T1 $3 | Cord Puller 1/1 T1 $3 | Picky Eater 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 1/4
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Combat Phase**

  [heur] Sneed vs [heur] Overlord Saurfang (first: Sneed)
     Sneed: [2/1, 1/4, 4/1]
     Overlord Saurfang: [11/17]
     Ominous Seer 2/1→2/0 DEAD  |  Wrath Weaver 11/17→11/15
     Wrath Weaver 11/15→11/11  |  Manasaber 4/1→4/0 DEAD
     Wrath Weaver 1/4→1/0 DEAD  |  Wrath Weaver 11/11→11/10
     Result: 0 vs 1 — heur
  [heur] Sylvanas Windrunner vs [heur] Drek'Thar (first: Drek'Thar)
     Sylvanas Windrunner: [2/1, 1/4, 1/2]
     Drek'Thar: [2/1, 1/2, 1/4]
     Risen Rider 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Risen Rider 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/1→1/0 DEAD
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/1→1/0 DEAD
     Result: 1 vs 1 — heur
  [heur] Professor Putricide vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Professor Putricide: [4/1, 2/1, 2/1]
     Inge, the Iron Hymn: [4/1, 1/2, 1/1]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Ominous Seer 2/1→2/0 DEAD
     Result: 0 vs 1 — heur
  [AGENT] Yogg-Saron, Hope's End vs [heur] Ysera (first: Yogg-Saron, Hope's End)
     Yogg-Saron, Hope's End: [4/1]
     Ysera: [6/6]
     Manasaber 4/1→4/0 DEAD  |  Scarlet Survivor 6/6→6/2
     Result: 0 vs 1 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=1) | Sneed (HP=30, Tier=2) | Overlord Saurfang (HP=30, Tier=2) | Ysera (HP=30, Tier=2) | Inge, the Iron Hymn (HP=30, Tier=2) | Professor Putricide (HP=30, Tier=2) | Sylvanas Windrunner (HP=30, Tier=2) | Drek'Thar (HP=30, Tier=2)

### Turn 4

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=11 Gold=6 Tier=1

  Board (1/7): 4/1
  Tavern (3 items): Annoy-o-Tron 1/2 T1 $3 | Cord Puller 1/1 T1 $3 | Manasaber 4/1 T1 $3
  Hand: 0 cards

  → Board (0/7): 
  → Tier 1→2 | Gold 6→4
  → Actions: sell_board_0, refresh, refresh, upgrade

**Sneed** [Heuristic]  HP=30 Armor=7 Gold=6 Tier=2

  Board (3/7): 2/1, 1/4, 4/1
  Tavern (5 items): Shell Collector 4/3 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Scarlet Skull 2/1 T2 $3 | Old Soul 3/4 T2 $3 | Might of Stormwind (spell) T2 $2
  Hand: 0 cards

  → Board (5/7): 2/1, 3/6, 4/1, 4/3, 3/4
  → Gold 6→0 | Armor 7→6
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=6 Tier=2

  Board (1/7): 11/17 [G]
  Tavern (5 items): Sewer Rat 9/8 T2 $3 | Sewer Rat 9/8 T2 $3 | Tide Raiser 8/7 T2 $3 | Metallic Hunter 10/8 T2 $3 | Leaf Through the Pages (spell) T2 $1
  Hand: 1 cards

  → Board (3/7): 11/17 [G], 10/8, 9/8
  → Gold 6→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=12 Gold=6 Tier=2

  Board (1/7): 6/6 [G]
  Tavern (6 items): Tide Raiser 2/1 T2 $3 | Alert Alarmist 2/2 T2 $3 | Cord Puller 1/1 T1 $3 | Sewer Rat 3/2 T2 $3 | Chef's Choice (spell) T2 $2 | Blazing Skyfin 2/4 T2 $3
  Hand: 1 cards

  → Board (3/7): 6/6 [G], 2/4, 3/2
  → Gold 6→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=6 Tier=2

  Board (3/7): 4/1, 1/2 [Taunt,DS], 1/1 [DS]
  Tavern (5 items): Humming Bird 1/4 T2 $3 | Sewer Rat 3/2 T2 $3 | Scarlet Skull 2/1 T2 $3 | Eternal Knight 4/2 T2 $3 | Hasty Excavation (spell) T2 $3
  Hand: 0 cards

  → Board (5/7): 4/1, 1/2 [Taunt,DS], 1/1 [DS], 4/2, 1/4
  → Gold 6→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=7 Gold=6 Tier=2

  Board (3/7): 4/1, 2/1, 2/1 [Taunt,Reborn]
  Tavern (5 items): Alert Alarmist 2/2 T2 $3 | Shell Collector 4/3 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Eternal Knight 4/2 T2 $3 | Search Through Time (spell) T2 $2
  Hand: 0 cards

  → Board (5/7): 4/1, 2/1, 2/1 [Taunt,Reborn], 4/3, 3/4
  → Gold 6→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=7 Gold=6 Tier=2

  Board (3/7): 2/1 [Taunt,Reborn], 1/4, 1/2 [Taunt,DS]
  Tavern (5 items): Scarlet Skull 2/1 T2 $3 | Shell Collector 4/3 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Alert Alarmist 2/2 T2 $3 | Strike Oil (spell) T2 $3
  Hand: 0 cards

  → Board (5/7): 2/1 [Taunt,Reborn], 3/6, 1/2 [Taunt,DS], 4/3, 3/4
  → Gold 6→0 | Armor 7→6
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=6 Tier=2

  Board (3/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 1/4
  Tavern (4 items): Scarlet Skull 2/1 T2 $3 | Tide Raiser 2/1 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Laboratory Assistant 3/4 T2 $3
  Hand: 0 cards

  → Board (5/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 5/8, 3/4, 3/4
  → Gold 6→0 | Armor 10→8
  → Actions: (auto)

**Combat Phase**

  [AGENT] Yogg-Saron, Hope's End vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Yogg-Saron, Hope's End: []
     Overlord Saurfang: [11/17, 10/8, 9/8]
     Result: 0 vs 3 — heur
  [heur] Inge, the Iron Hymn vs [heur] Ysera (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [5/1, 1/2, 1/1, 4/2, 2/4]
     Ysera: [6/6, 2/4, 3/2]
     Manasaber 5/1→5/0 DEAD  |  Scarlet Survivor 6/6→6/1
     Scarlet Survivor 6/1→6/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Blazing Skyfin 2/4→2/3
     Blazing Skyfin 2/3→2/2  |  Cord Puller 1/1→1/1
     Cord Puller 1/1→1/0 DEAD  |  Sewer Rat 3/2→3/1
     Sewer Rat 3/1→3/0 DEAD  |  Eternal Knight 4/2→5/0 DEAD
     Humming Bird 2/4→2/2  |  Blazing Skyfin 2/2→2/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Professor Putricide vs [heur] Drek'Thar (first: Drek'Thar)
     Professor Putricide: [4/1, 2/1, 2/1, 4/3, 3/4]
     Drek'Thar: [2/1, 1/2, 5/8, 3/4, 3/4]
     Risen Rider 2/1→2/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Shell Collector 4/3→4/2
     Ominous Seer 2/1→2/0 DEAD  |  Laboratory Assistant 3/4→3/2
     Wrath Weaver 5/8→5/5  |  Laboratory Assistant 3/4→3/0 DEAD
     Shell Collector 4/2→4/0 DEAD  |  Wrath Weaver 5/5→5/1
     Result: 0 vs 3 — heur
  [heur] Sylvanas Windrunner vs [heur] Sneed (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [2/1, 3/6, 1/2, 4/3, 3/4]
     Sneed: [2/1, 3/6, 4/1, 4/3, 3/4]
     Risen Rider 2/1→2/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Wrath Weaver 3/6→3/3  |  Wrath Weaver 3/6→3/3
     Wrath Weaver 3/3→3/2  |  Annoy-o-Tron 1/2→1/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Laboratory Assistant 3/4→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Laboratory Assistant 3/4→3/0 DEAD
     Result: 1 vs 1 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=2) | Sneed (HP=30, Tier=2) | Overlord Saurfang (HP=30, Tier=2) | Ysera (HP=30, Tier=2) | Inge, the Iron Hymn (HP=30, Tier=2) | Professor Putricide (HP=30, Tier=2) | Sylvanas Windrunner (HP=30, Tier=2) | Drek'Thar (HP=30, Tier=2)

### Turn 5

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=4 Gold=7 Tier=2

  Board: (empty)
  Tavern (5 items): Surf n' Surf 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Humming Bird 1/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Tavern Coin (spell) T1 $3
  Hand: 0 cards

  → Board (2/7): 4/1, 1/4
  → Gold 7→0
  → Actions: buy_tavern_3, play_hand_0, buy_tavern_2, play_hand_0, refresh

**Sneed** [Heuristic]  HP=30 Armor=6 Gold=7 Tier=2

  Board (5/7): 2/1, 3/6, 4/1, 4/3, 3/4
  Tavern (4 items): Surf n' Surf 1/1 T1 $3 | Soul Rewinder 4/1 T2 $3 | Cord Puller 1/1 T1 $3 | Alert Alarmist 2/2 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=7 Tier=2

  Board (3/7): 11/17 [G], 10/8, 9/8
  Tavern (4 items): Harmless Bonehead 11/11 T1 $3 | Humming Bird 11/14 T2 $3 | Old Soul 13/14 T2 $3 | Ancestral Automaton 3/4 T2 $3
  Hand: 1 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=8 Gold=7 Tier=2

  Board (3/7): 6/6 [G], 2/4, 3/2
  Tavern (5 items): Lava Lurker 2/5 T2 $3 | Scarlet Skull 2/1 T2 $3 | Annoy-o-Tron 1/2 T1 $3 | Ancestral Automaton 3/4 T2 $3 | Tarecgosa 4/4 T2 $3
  Hand: 1 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=7 Tier=2

  Board (5/7): 4/1, 1/2 [Taunt,DS], 1/1 [DS], 5/2, 1/4
  Tavern (4 items): Humming Bird 1/4 T2 $3 | Metallic Hunter 4/2 T2 $3 | Manasaber 4/1 T1 $3 | Metallic Hunter 4/2 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=0 Gold=7 Tier=2

  Board (5/7): 4/1, 2/1, 2/1 [Taunt,Reborn], 4/3, 3/4
  Tavern (4 items): Ominous Seer 2/1 T1 $3 | Scarlet Skull 2/1 T2 $3 | Old Soul 3/4 T2 $3 | Metallic Hunter 4/2 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=6 Gold=7 Tier=2

  Board (5/7): 2/1 [Taunt,Reborn], 3/6, 1/2 [Taunt,DS], 4/3, 3/4
  Tavern (4 items): Lava Lurker 2/5 T2 $3 | Shell Collector 4/3 T2 $3 | Tide Raiser 2/1 T2 $3 | Laboratory Assistant 3/4 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=8 Gold=7 Tier=2

  Board (5/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 5/8, 3/4, 3/4
  Tavern (4 items): Lava Lurker 2/5 T2 $3 | Lava Lurker 2/5 T2 $3 | Scarlet Skull 2/1 T2 $3 | Manasaber 4/1 T1 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Combat Phase**

  [heur] Inge, the Iron Hymn vs [heur] Sylvanas Windrunner (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [5/1, 1/2, 1/1, 5/2, 2/4]
     Sylvanas Windrunner: [2/1, 3/6, 1/2, 4/3, 3/4]
     Manasaber 5/1→5/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/1→1/0 DEAD
     Cord Puller 1/1→1/1  |  Annoy-o-Tron 1/1→1/0 DEAD
     Shell Collector 4/3→4/2  |  Cord Puller 1/1→1/0 DEAD
     Eternal Knight 5/2→6/0 DEAD  |  Laboratory Assistant 3/4→3/0 DEAD
     Result: 1 vs 2 — heur
  [heur] Drek'Thar vs [heur] Overlord Saurfang (first: Drek'Thar)
     Drek'Thar: [2/1, 1/2, 5/8, 3/4, 3/4]
     Overlord Saurfang: [11/17, 10/8, 9/8]
     Risen Rider 2/1→2/0 DEAD  |  Metallic Hunter 10/8→10/6
     Wrath Weaver 11/17→11/16  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Sewer Rat 9/8→9/7
     Metallic Hunter 10/6→10/3  |  Laboratory Assistant 3/4→3/0 DEAD
     Wrath Weaver 5/8→5/0 DEAD  |  Wrath Weaver 11/16→11/11
     Sewer Rat 9/7→9/4  |  Laboratory Assistant 3/4→3/0 DEAD
     Result: 0 vs 3 — heur
  [AGENT] Yogg-Saron, Hope's End vs [heur] Sneed (first: Sneed)
     Yogg-Saron, Hope's End: [4/1, 2/4]
     Sneed: [2/1, 3/6, 4/1, 4/3, 3/4]
     Ominous Seer 2/1→2/0 DEAD  |  Soul Rewinder 4/1→4/0 DEAD
     Humming Bird 2/4→2/1  |  Wrath Weaver 3/6→3/4
     Wrath Weaver 3/4→3/2  |  Humming Bird 2/1→2/0 DEAD
     Result: 0 vs 4 — heur
  [heur] Professor Putricide vs [heur] Ysera (first: Professor Putricide)
     Professor Putricide: [4/1, 2/1, 2/1, 4/3, 3/4]
     Ysera: [6/6, 2/4, 3/2]
     Manasaber 4/1→4/0 DEAD  |  Scarlet Survivor 6/6→6/2
     Scarlet Survivor 6/2→6/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Blazing Skyfin 2/4→2/2
     Blazing Skyfin 2/2→2/0 DEAD  |  Shell Collector 4/3→4/1
     Shell Collector 4/1→4/0 DEAD  |  Sewer Rat 3/2→3/0 DEAD
     Result: 1 vs 0 — heur

  Alive: 8/8
  HP: Sneed (HP=30, Tier=3) | Overlord Saurfang (HP=30, Tier=3) | Ysera (HP=30, Tier=3) | Inge, the Iron Hymn (HP=30, Tier=3) | Professor Putricide (HP=30, Tier=3) | Sylvanas Windrunner (HP=30, Tier=3) | Drek'Thar (HP=30, Tier=3) | Yogg-Saron, Hope's End (HP=25, Tier=2)

### Turn 6

**Yogg-Saron, Hope's End** [RL AGENT]  HP=25 Armor=0 Gold=8 Tier=2

  Board (2/7): 4/1, 1/4
  Tavern (4 items): Humming Bird 1/4 T2 $3 | Picky Eater 1/1 T1 $3 | Old Soul 3/4 T2 $3 | Tide Raiser 2/1 T2 $3
  Hand: 1 cards

  → Board (3/7): 4/1, 1/4, 4/3
  → Gold 8→5 | HP 25→22 | Trinket: Pilgrimp Sticker | Hand 1→2
  → Actions: play_hand_0, buy_tavern_1

**Sneed** [Heuristic]  HP=30 Armor=6 Gold=8 Tier=3

  Board (5/7): 2/1, 3/6, 4/1, 4/3, 3/4
  Tavern (5 items): Deflect-o-Bot 3/2 T3 $3 | Deflect-o-Bot 3/2 T3 $3 | Reef Riffer 3/2 T2 $3 | Deep-Sea Angler 2/3 T3 $3 | Planar Telescope (spell) T3 $4
  Hand: 0 cards

  → Board (7/7): 2/1, 3/6, 4/1, 4/3, 3/4, 3/2 [DS], 3/2 [DS]
  → Gold 8→0 | Trinket: Impulsive Portrait
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=8 Tier=3

  Board (3/7): 11/17 [G], 10/8, 9/8
  Tavern (5 items): Sewer Rat 13/12 T2 $3 | Deflect-o-Bot 13/12 T3 $3 | False Implicator 11/11 T3 $3 | Annoy-o-Module 12/14 T3 $3 | Hostile Bounty (spell) T3 $2
  Hand: 1 cards

  → Board (7/7): 15/21 [G], 10/8, 9/8, 12/14 [Taunt,DS], 13/12, 4/1, 1/4
  → Gold 8→0 | Armor 17→15 | Trinket: Rewinder Portrait
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=3 Gold=8 Tier=3

  Board (3/7): 6/6 [G], 2/4, 3/2
  Tavern (5 items): Deflect-o-Bot 3/2 T3 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Alert Alarmist 2/2 T2 $3 | Mummifier 5/2 T3 $3 | Tarecgosa 4/4 T2 $3
  Hand: 1 cards

  → Board (5/7): 6/6 [G], 2/4, 3/2, 4/4, 5/2
  → Gold 8→0 | Trinket: Smuggler Portrait
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=8 Tier=3

  Board (5/7): 4/1, 1/2 [Taunt,DS], 1/1 [DS], 6/2, 1/4
  Tavern (4 items): Leeching Felhound 3/3 T3 $3 | False Implicator 1/1 T3 $3 | Leeching Felhound 3/3 T3 $3 | Alert Alarmist 2/2 T2 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 6/2, 1/4, 3/3, 3/3, 2/2 [Taunt], 5/6
  → Gold 8→0 | Armor 12→6 | Trinket: Beetle Band
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=0 Gold=8 Tier=3

  Board (5/7): 4/1, 2/1, 2/1 [Taunt,Reborn], 4/3, 3/4
  Tavern (4 items): Technical Element 5/6 T3 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Reef Riffer 3/2 T2 $3 | Sly Raptor 1/3 T3 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 3/1 [Taunt,Reborn], 4/3, 3/4, 5/6, 2/4, 3/2
  → Gold 8→0 | Trinket: Demonblood Gourd
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=6 Gold=8 Tier=3

  Board (5/7): 2/1 [Taunt,Reborn], 3/6, 1/2 [Taunt,DS], 4/3, 3/4
  Tavern (4 items): Handless Forsaken 2/1 T3 $3 | Soul Rewinder 4/1 T2 $3 | Floating Watcher 4/4 T3 $5 | Hardy Orca 1/6 T3 $3
  Hand: 0 cards

  → Board (7/7): 2/1 [Taunt,Reborn], 5/8, 1/2 [Taunt,DS], 4/3, 3/4, 8/8, 1/6 [Taunt]
  → Gold 8→0 | Armor 6→9 | Trinket: Shadowy Elixir
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=0 Gold=8 Tier=3

  Board (5/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 5/8, 3/4, 3/4
  Tavern (4 items): Ancestral Automaton 3/4 T2 $3 | Sly Raptor 1/3 T3 $3 | Technical Element 5/6 T3 $3 | Picky Eater 1/1 T1 $3
  Hand: 0 cards

  → Board (7/7): 1/2 [Taunt,DS], 5/8, 3/4, 3/4, 5/6, 3/4, 1/3
  → Gold 8→0 | Armor 0→5 | Trinket: Shadowy Elixir
  → Actions: (auto)

**Combat Phase**

  [heur] Ysera vs [AGENT] Yogg-Saron, Hope's End (first: Ysera)
     Ysera: [6/6, 2/4, 3/2, 4/4, 5/2]
     Yogg-Saron, Hope's End: [4/1, 2/4, 4/3]
     Scarlet Survivor 6/6→6/2  |  Soul Rewinder 4/1→4/0 DEAD
     Humming Bird 2/4→2/0 DEAD  |  Scarlet Survivor 6/2→6/0 DEAD
     Blazing Skyfin 2/4→2/0 DEAD  |  Shell Collector 4/3→4/1
     Shell Collector 4/1→4/0 DEAD  |  Tarecgosa 4/4→4/0 DEAD
     Result: 2 vs 0 — heur
  [heur] Inge, the Iron Hymn vs [heur] Professor Putricide (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [5/1, 6/2, 2/4, 3/3, 3/3, 2/2, 5/6]
     Professor Putricide: [4/1, 3/1, 4/3, 3/4, 5/6, 2/4, 3/2]
     Manasaber 5/1→5/0 DEAD  |  Risen Rider 3/1→3/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Alert Alarmist 2/2→2/0 DEAD
     Eternal Knight 6/2→7/0 DEAD  |  Reef Riffer 3/2→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Leeching Felhound 3/3→3/0 DEAD
     Humming Bird 2/4→2/2  |  Nerubian Deathswarmer 2/4→2/2
     Laboratory Assistant 3/4→3/0 DEAD  |  Technical Element 5/6→5/3
     Leeching Felhound 3/3→3/1  |  Nerubian Deathswarmer 2/2→2/0 DEAD
     Technical Element 5/6→5/3  |  Leeching Felhound 3/1→3/0 DEAD
     Technical Element 5/3→5/0 DEAD  |  Technical Element 5/3→5/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Overlord Saurfang vs [heur] Sylvanas Windrunner (first: Overlord Saurfang)
     Overlord Saurfang: [15/21, 10/8, 9/8, 12/14, 13/12, 4/1, 1/4]
     Sylvanas Windrunner: [2/1, 5/8, 1/2, 4/3, 3/4, 8/8, 1/6]
     Wrath Weaver 15/21→15/19  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 5/8→5/0 DEAD  |  Annoy-o-Module 12/14→12/14
     Metallic Hunter 10/8→10/7  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Annoy-o-Module 12/14→12/13
     Sewer Rat 9/8→9/7  |  Hardy Orca 1/6→1/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Annoy-o-Module 12/13→12/9
     Annoy-o-Module 12/9→12/1  |  Floating Watcher 8/8→8/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Annoy-o-Module 12/1→12/0 DEAD
     Result: 6 vs 0 — heur
  [heur] Drek'Thar vs [heur] Sneed (first: Drek'Thar)
     Drek'Thar: [1/2, 5/8, 3/4, 3/4, 5/6, 3/4, 1/3]
     Sneed: [2/1, 3/6, 4/1, 4/3, 3/4, 3/2, 3/2]
     Annoy-o-Tron 1/2→1/2  |  Deflect-o-Bot 3/2→3/2
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 5/8→5/5  |  Laboratory Assistant 3/4→3/0 DEAD
     Wrath Weaver 3/6→3/3  |  Laboratory Assistant 3/4→3/1
     Laboratory Assistant 3/1→3/0 DEAD  |  Deflect-o-Bot 3/2→3/2
     Manasaber 4/1→4/0 DEAD  |  Sly Raptor 1/3→1/0 DEAD
     Laboratory Assistant 3/4→3/1  |  Deflect-o-Bot 3/2→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Ancestral Automaton 3/4→3/0 DEAD
     Technical Element 5/6→5/3  |  Deflect-o-Bot 3/2→3/0 DEAD
     Result: 3 vs 1 — heur

  Alive: 8/8
  HP: Sneed (HP=30, Tier=3) | Overlord Saurfang (HP=30, Tier=3) | Ysera (HP=30, Tier=3) | Inge, the Iron Hymn (HP=30, Tier=3) | Drek'Thar (HP=30, Tier=3) | Sylvanas Windrunner (HP=29, Tier=3) | Professor Putricide (HP=25, Tier=3) | Yogg-Saron, Hope's End (HP=14, Tier=2)

### Turn 7

**Yogg-Saron, Hope's End** [RL AGENT]  HP=14 Armor=0 Gold=9 Tier=2

  Board (3/7): 4/1, 1/4, 4/3
  Tavern (4 items): Shell Collector 4/3 T2 $3 | Old Soul 3/4 T2 $3 | Metallic Hunter 4/2 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3
  Hand: 3 cards

  → Board (4/7): 1/4, 4/3, 4/5, 5/2
  → Tier 2→3 | Gold 9→6 | Hand 3→1
  → Actions: play_hand_1, play_hand_1, upgrade, sell_board_0

**Sneed** [Heuristic]  HP=30 Armor=6 Gold=9 Tier=3

  Board (7/7): 2/1, 3/6, 4/1, 4/3, 3/4, 3/2 [DS], 3/2 [DS]
  Tavern (4 items): Tide Raiser 2/1 T2 $3 | Alert Alarmist 2/2 T2 $3 | Dustbone Devastator 2/6 T3 $3 | Cadaver Caretaker 3/3 T3 $3
  Hand: 0 cards

  → Board (7/7): 3/6, 4/1, 4/3, 3/4, 3/2 [DS], 3/2 [DS], 2/6
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=9 Tier=3

  Board (7/7): 15/21 [G], 10/8, 9/8, 12/14 [Taunt,DS], 13/12, 4/1, 1/4
  Tavern (4 items): Tide Raiser 17/16 T2 $3 | Alert Alarmist 17/17 T2 $3 | Sprightly Scarab 18/16 T3 $3 | Shell Collector 19/18 T2 $3
  Hand: 1 cards

  → Board (7/7): 15/21 [G], 10/8, 9/8, 12/14 [Taunt,DS], 13/12, 1/4, 19/18
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=3 Gold=9 Tier=3

  Board (5/7): 6/6 [G], 2/4, 3/2, 4/4, 5/2
  Tavern (5 items): Ancestral Automaton 3/4 T2 $3 | Old Soul 3/4 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Handless Forsaken 2/1 T3 $3 | Blazing Skyfin 2/4 T2 $3
  Hand: 1 cards

  → Board (6/7): 6/6 [G], 2/4, 3/2, 4/4, 5/2, 3/4
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=6 Gold=9 Tier=3

  Board (7/7): 4/1, 7/2, 1/4, 3/3, 3/3, 2/2 [Taunt], 5/6
  Tavern (4 items): Annoy-o-Module 2/4 T3 $3 | Shell Collector 4/3 T2 $3 | Scarlet Skull 2/1 T2 $3 | Soul Rewinder 4/1 T2 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 7/2, 1/4, 3/3, 3/3, 5/6, 4/3
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=25 Armor=0 Gold=9 Tier=3

  Board (7/7): 4/1, 3/1 [Taunt,Reborn], 4/3, 3/4, 5/6, 2/4, 3/2
  Tavern (4 items): Tide Raiser 2/1 T2 $3 | Accord-o-Tron 3/3 T3 $3 | Soul Rewinder 4/1 T2 $3 | Metallic Hunter 4/2 T2 $3
  Hand: 1 cards

  → Board (7/7): 3/1 [Taunt,Reborn], 4/3, 3/4, 5/6, 6/8, 3/2, 3/3
  → Tier 3→4 | Gold 9→0 | Hand 1→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=29 Armor=0 Gold=9 Tier=3

  Board (7/7): 2/1 [Taunt,Reborn], 5/8, 1/2 [Taunt,DS], 4/3, 3/4, 8/8, 1/6 [Taunt]
  Tavern (4 items): Sewer Rat 3/2 T2 $3 | Sprightly Scarab 3/1 T3 $3 | Sprightly Scarab 3/1 T3 $3 | Leeching Felhound 3/3 T3 $3
  Hand: 0 cards

  → Board (7/7): 7/10, 4/3, 3/4, 14/14, 3/6 [Taunt,WF], 3/3, 3/1
  → Tier 3→4 | Gold 9→0 | HP 29→24
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=5 Gold=9 Tier=3

  Board (7/7): 1/2 [Taunt,DS], 5/8, 3/4, 3/4, 5/6, 3/4, 1/3
  Tavern (4 items): Floating Watcher 4/4 T3 $5 | Technical Element 5/6 T3 $3 | Sprightly Scarab 3/1 T3 $3 | Sewer Rat 3/2 T2 $3
  Hand: 0 cards

  → Board (7/7): 5/8, 3/4, 3/4, 5/6, 3/4, 1/3, 5/6
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Combat Phase**

  [heur] Drek'Thar vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Drek'Thar: [5/8, 3/4, 3/4, 5/6, 3/4, 1/3, 5/6]
     Inge, the Iron Hymn: [5/1, 7/2, 2/4, 3/3, 3/3, 5/6, 4/3]
     Manasaber 5/1→5/0 DEAD  |  Technical Element 5/6→5/1
     Wrath Weaver 5/8→5/5  |  Leeching Felhound 3/3→3/0 DEAD
     Eternal Knight 7/2→8/0 DEAD  |  Laboratory Assistant 3/4→3/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Humming Bird 2/4→2/1  |  Ancestral Automaton 3/4→3/2
     Technical Element 5/6→5/4  |  Humming Bird 2/1→2/0 DEAD
     Leeching Felhound 3/3→3/2  |  Sly Raptor 1/3→1/0 DEAD
     Ancestral Automaton 3/2→3/0 DEAD  |  Leeching Felhound 3/2→3/0 DEAD
     Technical Element 5/6→5/1  |  Technical Element 5/4→5/0 DEAD
     Technical Element 5/1→5/0 DEAD  |  Technical Element 5/1→5/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Professor Putricide vs [heur] Sneed (first: Professor Putricide)
     Professor Putricide: [3/1, 4/3, 3/4, 5/6, 6/8, 3/2, 3/3]
     Sneed: [3/6, 4/1, 4/3, 3/4, 3/2, 3/2, 2/6]
     Risen Rider 3/1→3/0 DEAD  |  Dustbone Devastator 2/6→2/3
     Wrath Weaver 3/6→3/3  |  Accord-o-Tron 3/3→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Wrath Weaver 3/3→3/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Laboratory Assistant 3/4→3/0 DEAD
     Technical Element 5/6→5/3  |  Laboratory Assistant 3/4→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Technical Element 5/3→5/0 DEAD
     Nerubian Deathswarmer 6/8→6/5  |  Deflect-o-Bot 3/2→3/2
     Deflect-o-Bot 3/2→3/0 DEAD  |  Nerubian Deathswarmer 6/5→6/2
     Reef Riffer 3/2→3/0 DEAD  |  Deflect-o-Bot 3/2→3/2
     Deflect-o-Bot 3/2→3/0 DEAD  |  Nerubian Deathswarmer 6/2→6/0 DEAD
     Result: 0 vs 1 — heur
  [heur] Sylvanas Windrunner vs [heur] Ysera (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [7/10, 4/3, 3/4, 14/14, 3/6, 3/3, 3/1]
     Ysera: [6/6, 2/4, 3/2, 4/4, 5/2, 3/4]
     Wrath Weaver 7/10→7/6  |  Tarecgosa 4/4→4/0 DEAD
     Scarlet Survivor 6/6→6/3  |  Hardy Orca 3/6→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Ancestral Automaton 3/4→3/0 DEAD
     Blazing Skyfin 2/4→2/1  |  Laboratory Assistant 3/4→3/2
     Laboratory Assistant 3/2→3/0 DEAD  |  Mummifier 5/2→5/0 DEAD
     Sewer Rat 3/2→3/0 DEAD  |  Leeching Felhound 3/3→3/0 DEAD
     Floating Watcher 14/14→14/12  |  Blazing Skyfin 2/1→2/0 DEAD
     Result: 3 vs 1 — heur
  [heur] Overlord Saurfang vs [AGENT] Yogg-Saron, Hope's End (first: Overlord Saurfang)
     Overlord Saurfang: [15/21, 10/8, 9/8, 12/14, 13/12, 1/4, 19/18]
     Yogg-Saron, Hope's End: [2/4, 4/3, 4/5, 5/2]
     Wrath Weaver 15/21→15/17  |  Shell Collector 4/3→4/0 DEAD
     Humming Bird 2/4→2/0 DEAD  |  Annoy-o-Module 12/14→12/14
     Metallic Hunter 10/8→10/4  |  Picky Eater 4/5→4/0 DEAD
     Mummifier 5/2→5/0 DEAD  |  Annoy-o-Module 12/14→12/9
     Result: 7 vs 0 — heur

  Alive: 8/8
  HP: Sneed (HP=30, Tier=4) | Overlord Saurfang (HP=30, Tier=4) | Ysera (HP=30, Tier=4) | Inge, the Iron Hymn (HP=30, Tier=4) | Drek'Thar (HP=30, Tier=4) | Sylvanas Windrunner (HP=24, Tier=4) | Professor Putricide (HP=18, Tier=4) | Yogg-Saron, Hope's End (HP=4, Tier=3)

### Turn 8

**Yogg-Saron, Hope's End** [RL AGENT]  HP=4 Armor=0 Gold=10 Tier=3

  Board (4/7): 1/4, 4/3, 4/5, 5/2
  Tavern (5 items): Ominous Seer 2/1 T1 $3 | Deep-Sea Angler 2/3 T3 $3 | Accord-o-Tron 3/3 T3 $3 | Deep Blue Crooner 2/2 T3 $3 | Tavern Coin (spell) T1 $3
  Hand: 2 cards

  → Board (5/7): 1/4, 4/3, 4/5, 5/2, 4/2
  → Hand 2→1
  → Actions: play_hand_1

**Sneed** [Heuristic]  HP=30 Armor=6 Gold=10 Tier=4

  Board (7/7): 3/6, 4/1, 4/3, 3/4, 3/2 [DS], 3/2 [DS], 2/6
  Tavern (6 items): Soul Rewinder 4/1 T2 $3 | Hardy Orca 1/6 T3 $3 | Metallic Hunter 4/2 T2 $3 | Imposing Percussionist 4/4 T4 $3 | Laboratory Assistant 3/4 T2 $3 | Easterly Winds (spell) T4 $1
  Hand: 0 cards

  → Board (7/7): 9/12, 3/4, 2/6, 4/4, 1/6 [Taunt], 3/4, 4/1
  → Gold 10→0 | HP 30→28 | Armor 6→0 | Hand 0→1
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=10 Tier=4

  Board (7/7): 15/21 [G], 10/8, 9/8, 12/14 [Taunt,DS], 13/12, 1/4, 19/18
  Tavern (6 items): Stomping Stegodon 21/21 T4 $3 | Cord Puller 18/18 T1 $3 | Sly Raptor 18/20 T3 $3 | Waverider 19/25 T4 $3 | Cadaver Caretaker 20/20 T3 $3 | Back to Back (spell) T4 $1
  Hand: 1 cards

  → Board (7/7): 15/21 [G], 19/18, 19/25, 21/21, 20/20, 18/20, 18/18 [DS]
  → Gold 10→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=3 Gold=10 Tier=4

  Board (6/7): 6/6 [G], 2/4, 3/2, 4/4, 5/2, 3/4
  Tavern (7 items): Deep Blue Crooner 2/2 T3 $3 | Sewer Rat 3/2 T2 $3 | Floating Watcher 4/4 T3 $5 | Trigore the Lasher 9/3 T4 $3 | Sly Raptor 1/3 T3 $3 | Sick Riffs (spell) T1 $3 | Persistent Poet 2/3 T4 $3
  Hand: 1 cards

  → Board (7/7): 6/6 [G], 4/4, 5/2, 3/4, 9/3, 4/4, 3/2
  → Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=1 Gold=10 Tier=4

  Board (7/7): 4/1, 8/2, 1/4, 3/3, 3/3, 5/6, 4/3
  Tavern (6 items): Plaguerunner 4/2 T4 $3 | Annoy-o-Module 2/4 T3 $3 | Eternal Knight 8/2 T2 $3 | Technical Element 5/6 T3 $3 | Monstrous Macaw 5/4 T4 $3 | Defender's Rites (spell) T4 $2
  Hand: 0 cards

  → Board (7/7): 8/2, 5/6, 4/3, 5/6, 8/2, 5/4, 2/4 [Taunt,DS]
  → Gold 10→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=18 Armor=0 Gold=11 Tier=4

  Board (7/7): 3/1 [Taunt,Reborn], 4/3, 3/4, 5/6, 6/8, 3/2, 3/3
  Tavern (6 items): Trigore the Lasher 9/3 T4 $3 | Wyvern Outrider 2/8 T4 $3 | Seafloor Recruiter 3/5 T4 $3 | Hardy Orca 1/6 T3 $3 | Auto Assembler 2/2 T4 $3 | Conflagration (spell) T4 $2
  Hand: 1 cards

  → Board (7/7): 5/6, 10/12, 9/3, 2/8, 3/5, 1/6 [Taunt], 2/2
  → Gold 11→0 | Hand 1→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=4

  Board (7/7): 7/10, 4/3, 3/4, 14/14, 3/6 [Taunt,WF], 3/3, 3/1
  Tavern (6 items): Technical Element 5/6 T3 $3 | Humming Bird 1/4 T2 $3 | Rimescale Priestess 3/3 T4 $3 | Waverider 2/8 T4 $3 | Holo Rover 4/4 T4 $3 | Forest's Bounty (spell) T4 $3
  Hand: 0 cards

  → Board (7/7): 7/10, 14/14, 3/6 [Taunt,WF], 5/6, 2/8, 4/4 [DS], 1/4
  → Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=5 Gold=10 Tier=4

  Board (7/7): 5/8, 3/4, 3/4, 5/6, 3/4, 1/3, 5/6
  Tavern (6 items): Banana Slamma 3/6 T4 $3 | Plaguerunner 4/2 T4 $3 | Prosthetic Hand 3/1 T4 $3 | Zesty Shaker 6/7 T4 $3 | Hunting Tiger Shark 3/5 T4 $3 | Natural Blessing (spell) T4 $4
  Hand: 0 cards

  → Board (7/7): 5/8, 5/6, 5/6, 6/7, 3/6, 3/5, 3/1 [Reborn]
  → Gold 10→0 | Hand 0→1
  → Actions: (auto)

**Combat Phase**

  [heur] Inge, the Iron Hymn vs [heur] Sneed (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [8/2, 5/6, 4/3, 5/6, 8/2, 5/4, 2/4]
     Sneed: [9/12, 3/4, 2/6, 4/4, 1/6, 3/4, 4/1]
     Eternal Knight 8/2→8/1  |  Hardy Orca 1/6→1/0 DEAD
     Wrath Weaver 9/12→9/10  |  Annoy-o-Module 2/4→2/4
     Technical Element 5/6→5/4  |  Dustbone Devastator 2/6→2/1
     Laboratory Assistant 3/4→3/2  |  Annoy-o-Module 2/4→2/1
     Shell Collector 4/3→4/0 DEAD  |  Laboratory Assistant 3/4→3/0 DEAD
     Dustbone Devastator 2/1→3/0 DEAD  |  Annoy-o-Module 2/1→2/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Wrath Weaver 9/10→9/5
     Imposing Percussionist 4/4→4/0 DEAD  |  Technical Element 5/4→5/0 DEAD
     Eternal Knight 8/2→9/0 DEAD  |  Wrath Weaver 9/5→9/0 DEAD
     Soul Rewinder 4/1→4/0 DEAD  |  Eternal Knight 9/1→10/0 DEAD
     Monstrous Macaw 5/4→5/1  |  Laboratory Assistant 3/2→3/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Professor Putricide vs [heur] Drek'Thar (first: Drek'Thar)
     Professor Putricide: [5/6, 10/12, 9/3, 2/8, 3/5, 1/6, 2/2]
     Drek'Thar: [5/8, 5/6, 5/6, 6/7, 3/6, 3/5, 3/1]
     Wrath Weaver 5/8→5/7  |  Hardy Orca 1/6→1/1
     Technical Element 5/6→5/3  |  Hunting Tiger Shark 3/5→3/0 DEAD
     Technical Element 5/6→5/5  |  Hardy Orca 1/1→1/0 DEAD
     Nerubian Deathswarmer 10/12→10/9  |  Prosthetic Hand 3/1→3/0 DEAD
     Technical Element 5/6→5/4  |  Auto Assembler 2/2→2/0 DEAD
     Trigore the Lasher 9/3→9/0 DEAD  |  Zesty Shaker 6/7→6/0 DEAD
     Banana Slamma 3/6→3/3  |  Seafloor Recruiter 3/5→3/2
     Wyvern Outrider 2/8→2/3  |  Wrath Weaver 5/7→5/5
     Result: 4 vs 4 — heur
  [heur] Ysera vs [heur] Overlord Saurfang (first: Ysera)
     Ysera: [6/6, 4/4, 5/2, 3/4, 9/3, 4/4, 3/2]
     Overlord Saurfang: [15/21, 19/18, 19/25, 21/21, 20/20, 18/20, 18/18]
     Scarlet Survivor 6/6→6/0 DEAD  |  Waverider 19/25→19/19
     Wrath Weaver 15/21→15/16  |  Mummifier 5/2→5/0 DEAD
     Tarecgosa 4/4→4/0 DEAD  |  Stomping Stegodon 21/21→21/17
     Shell Collector 19/18→19/9  |  Trigore the Lasher 9/3→9/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Waverider 19/19→19/16
     Waverider 19/16→19/13  |  Sewer Rat 3/2→3/0 DEAD
     Floating Watcher 4/4→4/0 DEAD  |  Stomping Stegodon 21/17→21/13
     Result: 0 vs 7 — heur
  [AGENT] Yogg-Saron, Hope's End vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Yogg-Saron, Hope's End: [2/4, 4/3, 4/5, 5/2, 4/2]
     Sylvanas Windrunner: [7/10, 14/14, 4/6, 5/6, 2/8, 4/4, 2/4]
     Wrath Weaver 7/10→7/6  |  Metallic Hunter 4/2→4/0 DEAD
     Humming Bird 2/4→2/0 DEAD  |  Hardy Orca 4/6→4/4
     Floating Watcher 14/14→14/10  |  Picky Eater 4/5→4/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Hardy Orca 4/4→4/0 DEAD
     Technical Element 5/6→5/1  |  Mummifier 5/2→5/0 DEAD
     Result: 0 vs 6 — heur

  **Yogg-Saron, Hope's End [AGENT] eliminated!** (Turn 8)
  Alive: 7/8
  HP: Overlord Saurfang (HP=30, Tier=4) | Inge, the Iron Hymn (HP=30, Tier=4) | Drek'Thar (HP=30, Tier=4) | Sylvanas Windrunner (HP=24, Tier=4) | Sneed (HP=20, Tier=4) | Ysera (HP=18, Tier=4) | Professor Putricide (HP=18, Tier=4)

### Turn 9

**Sneed** [Heuristic]  HP=20 Armor=0 Gold=10 Tier=4

  Board (7/7): 9/12, 3/4, 3/6, 4/4, 1/6 [Taunt], 3/4, 4/1
  Tavern (6 items): Rimescale Priestess 3/3 T4 $3 | Annoy-o-Tron 1/2 T1 $3 | Waverider 2/8 T4 $3 | False Implicator 1/1 T3 $3 | Holo Rover 4/4 T4 $3 | Deepwater Clan (spell) T4 $2
  Hand: 1 cards

  → Board (7/7): 9/12, 3/4, 3/6, 4/4, 1/6 [Taunt], 3/4, 2/8
  → Tier 4→5 | Gold 10→0 | Trinket: S'Thara Sticker
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=10 Tier=4

  Board (7/7): 15/21 [G], 19/18, 19/25, 21/21, 20/20, 18/20, 18/18 [DS]
  Tavern (6 items): Eternal Knight 4/2 T2 $3 | Enchanted Sentinel 29/31 T4 $3 | Surf n' Surf 27/27 T1 $3 | Zesty Shaker 32/33 T4 $3 | Laboratory Assistant 29/30 T2 $3 | Arcane Absorption (spell) T4 $1
  Hand: 2 cards

  → Board (6/7): 19/18, 19/25, 21/21, 22/22, 18/20, 18/18 [DS]
  → Tier 4→5 | Gold 10→0 | Trinket: Nazjatar Postcard | Hand 2→1
  → Actions: (auto)

**Ysera** [Heuristic]  HP=18 Armor=0 Gold=10 Tier=4

  Board (7/7): 6/6 [G], 4/4, 5/2, 3/4, 9/5, 4/4, 3/2
  Tavern (7 items): Hardy Orca 1/6 T3 $3 | Cadaver Caretaker 3/3 T3 $3 | Leeching Felhound 3/3 T3 $3 | Humming Bird 1/4 T2 $3 | Annoy-o-Tron 1/2 T1 $3 | Shifting Tide (spell) T4 $1 | Incubation Researcher 2/8 T4 $3
  Hand: 1 cards

  → Board (7/7): 6/6 [G], 4/4, 5/2, 3/4, 9/5, 4/4, 2/8
  → Tier 4→5 | Gold 10→0 | Trinket: Chromatic Tear | Hand 1→3
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=1 Gold=10 Tier=4

  Board (7/7): 10/2, 5/6, 4/3, 5/6, 10/2, 5/4, 2/4 [Taunt,DS]
  Tavern (6 items): Nerubian Deathswarmer 1/4 T2 $3 | Seafloor Recruiter 3/5 T4 $3 | Sewer Rat 3/2 T2 $3 | Sprightly Scarab 3/1 T3 $3 | Floating Watcher 4/4 T3 $5 | Sick Riffs (spell) T1 $3
  Hand: 0 cards

  → Board (7/7): 10/2, 5/6, 4/3, 5/6, 10/2, 5/4, 3/5
  → Tier 4→5 | Gold 10→0 | Trinket: Drakkari Portrait | Hand 0→1
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=18 Armor=0 Gold=10 Tier=4

  Board (7/7): 5/6, 10/12, 9/7, 2/8, 3/5, 1/6 [Taunt], 2/2
  Tavern (5 items): Malchezaar, Prince of Dance 5/4 T4 $3 | Banana Slamma 3/6 T4 $3 | Marquee Ticker 3/7 T4 $3 | Wrath Weaver 1/4 T1 $3 | Reef Riffer 3/2 T2 $3
  Hand: 0 cards

  → Board (6/7): 5/6, 10/12, 9/7, 2/8, 3/5, 1/6 [Taunt]
  → Tier 4→5 | Gold 10→0 | Trinket: Beetle Band
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=4

  Board (7/7): 7/10, 14/14, 3/6 [Taunt,WF], 5/6, 2/8, 4/4 [DS], 1/4
  Tavern (5 items): Reef Riffer 3/2 T2 $3 | Seafloor Recruiter 3/5 T4 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Deep-Sea Angler 2/3 T3 $3 | Lava Lurker 2/5 T2 $3
  Hand: 1 cards

  → Board (7/7): 9/12, 20/20, 3/6 [Taunt,WF], 5/6, 2/8, 4/4 [DS], 5/4
  → Tier 4→5 | Gold 10→0 | HP 24→22 | Trinket: S'Thara Sticker | Hand 1→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=5 Gold=10 Tier=4

  Board (7/7): 5/8, 5/6, 5/6, 6/7, 3/6, 3/5, 3/1 [Reborn]
  Tavern (5 items): Humming Bird 1/4 T2 $3 | Scarlet Skull 2/1 T2 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Hunting Tiger Shark 3/5 T4 $3 | Cadaver Caretaker 3/3 T3 $3
  Hand: 1 cards

  → Board (7/7): 5/8, 5/6, 5/6, 6/7, 3/6, 3/5, 3/2
  → Tier 4→5 | Gold 10→0 | Trinket: Ironforge Anvil | Hand 1→0
  → Actions: (auto)

**Combat Phase**

  [heur] Sylvanas Windrunner vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Sylvanas Windrunner: [9/12, 20/20, 3/6, 5/6, 2/8, 4/4, 5/4]
     Inge, the Iron Hymn: [10/2, 5/6, 4/3, 5/6, 10/2, 5/4, 3/5]
     Eternal Knight 10/2→11/0 DEAD  |  Hardy Orca 3/6→3/0 DEAD
     Wrath Weaver 9/12→9/9  |  Seafloor Recruiter 3/5→3/0 DEAD
     Technical Element 5/6→5/2  |  Holo Rover 4/4→4/4
     Floating Watcher 20/20→20/9  |  Eternal Knight 11/2→12/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Technical Element 5/6→5/2
     Technical Element 5/2→5/0 DEAD  |  Technical Element 5/2→5/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Floating Watcher 20/9→20/4
     Waverider 2/8→2/3  |  Monstrous Macaw 5/4→5/2
     Monstrous Macaw 5/2→5/0 DEAD  |  Waverider 2/3→2/0 DEAD
     Result: 4 vs 0 — heur
  [heur] Ysera vs [heur] Sneed (first: Sneed)
     Ysera: [6/6, 4/4, 5/2, 3/4, 9/5, 4/4, 2/8]
     Sneed: [9/12, 3/4, 3/6, 4/4, 1/6, 3/4, 2/8]
     Wrath Weaver 9/12→9/6  |  Scarlet Survivor 6/6→6/0 DEAD
     Tarecgosa 4/4→4/3  |  Hardy Orca 1/6→1/2
     Laboratory Assistant 3/4→3/1  |  Ancestral Automaton 3/4→3/1
     Mummifier 5/2→5/1  |  Hardy Orca 1/2→1/0 DEAD
     Dustbone Devastator 3/6→4/0 DEAD  |  Trigore the Lasher 9/5→9/2
     Ancestral Automaton 3/1→3/0 DEAD  |  Wrath Weaver 9/6→9/3
     Imposing Percussionist 4/4→4/2  |  Incubation Researcher 2/8→2/4
     Trigore the Lasher 9/2→9/0 DEAD  |  Laboratory Assistant 3/1→3/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Floating Watcher 4/4→4/1
     Floating Watcher 4/1→4/0 DEAD  |  Wrath Weaver 9/3→9/0 DEAD
     Waverider 2/8→2/4  |  Tarecgosa 4/3→4/1
     Incubation Researcher 2/4→2/0 DEAD  |  Imposing Percussionist 4/2→4/0 DEAD
     Result: 2 vs 1 — heur
  [heur] Professor Putricide vs [heur] Overlord Saurfang (first: Professor Putricide)
     Professor Putricide: [5/6, 10/12, 9/7, 2/8, 3/5, 1/6]
     Overlord Saurfang: [19/18, 19/25, 21/21, 22/22, 18/20, 18/18]
     Technical Element 5/6→5/0 DEAD  |  Stomping Stegodon 21/21→21/16
     Shell Collector 19/18→19/17  |  Hardy Orca 1/6→1/0 DEAD
     Nerubian Deathswarmer 10/12→10/0 DEAD  |  Cadaver Caretaker 22/22→22/12
     Waverider 19/25→19/16  |  Trigore the Lasher 9/7→9/0 DEAD
     Wyvern Outrider 2/8→2/0 DEAD  |  Cadaver Caretaker 22/12→22/10
     Stomping Stegodon 21/16→21/13  |  Seafloor Recruiter 3/5→3/0 DEAD
     Result: 0 vs 6 — heur

  Alive: 7/8
  HP: Overlord Saurfang (HP=30, Tier=5) | Drek'Thar (HP=30, Tier=5) | Sylvanas Windrunner (HP=22, Tier=5) | Sneed (HP=20, Tier=5) | Ysera (HP=18, Tier=5) | Inge, the Iron Hymn (HP=16, Tier=5) | Professor Putricide (HP=3, Tier=5)

### Turn 10

**Sneed** [Heuristic]  HP=20 Armor=0 Gold=10 Tier=5

  Board (7/7): 9/12, 3/4, 4/6, 4/4, 1/6 [Taunt], 3/4, 2/8
  Tavern (6 items): Reef Riffer 3/2 T2 $3 | Divine Sparkbot 4/2 T5 $3 | Shell Collector 4/3 T2 $3 | Abyssal Bruiser 1/1 T4 $3 | Holo Rover 4/4 T4 $3 | Bargain Bundle (spell) T5 $5
  Hand: 2 cards

  → Board (7/7): 9/12, 4/6, 6/6, 2/8, 4/4 [DS], 4/3, 1/1 [DS]
  → Gold 10→0 | Hand 2→1
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=10 Tier=5

  Board (6/7): 19/18, 19/25, 21/21, 22/22, 18/20, 18/18 [DS]
  Tavern (6 items): Wrath Weaver 28/31 T1 $3 | Old Soul 30/31 T2 $3 | Annoy-o-Module 29/31 T3 $3 | Ashen Corruptor 33/33 T5 $3 | Shadowdancer 32/30 T5 $3 | Undersea Mount (spell) T1 $3
  Hand: 2 cards

  → Board (7/7): 19/25, 21/21, 22/22, 33/33, 32/30 [Taunt], 32/33, 29/31 [Taunt,DS]
  → Gold 10→0 | Hand 2→1
  → Actions: (auto)

**Ysera** [Heuristic]  HP=18 Armor=0 Gold=10 Tier=5

  Board (7/7): 6/6 [G], 4/4, 5/2, 3/4, 9/7, 4/4, 2/8
  Tavern (7 items): Malchezaar, Prince of Dance 5/4 T4 $3 | Ashen Corruptor 6/6 T5 $3 | Lava Lurker 2/5 T2 $3 | Accord-o-Tron 3/3 T3 $3 | Sinrunner Blanchy 8/8 T5 $3 | Portal in a Crystal (spell) T5 $2 | Kalecgos, Arcane Aspect 4/12 T5 $3
  Hand: 4 cards

  → Board (7/7): 6/6 [G], 9/7, 2/8, 8/8 [Reborn], 4/12, 6/6, 2/5
  → Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=16 Armor=0 Gold=10 Tier=5

  Board (7/7): 12/2, 5/6, 4/3, 5/6, 12/2, 5/4, 3/5
  Tavern (6 items): Plaguerunner 4/2 T4 $3 | Imposing Percussionist 4/4 T4 $3 | Deep Blue Crooner 2/2 T3 $3 | Divine Sparkbot 4/2 T5 $3 | Monstrous Macaw 5/4 T4 $3 | Unmasked Identity (spell) T5 $3
  Hand: 1 cards

  → Board (7/7): 12/2, 5/6, 5/6, 12/2, 5/4, 5/4, 2/2
  → Gold 10→0 | HP 16→11 | Hand 1→2
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=3 Armor=0 Gold=10 Tier=5

  Board (6/7): 5/6, 10/12, 9/10, 2/8, 3/5, 1/6 [Taunt]
  Tavern (6 items): Charging Czarina 4/1 T5 $3 | Tide Raiser 2/1 T2 $3 | Scrap Scraper 6/5 T5 $3 | Stomping Stegodon 4/4 T4 $3 | Wyvern Outrider 2/8 T4 $3 | Saloon's Finest (spell) T5 $2
  Hand: 0 cards

  → Board (7/7): 5/6, 10/12, 9/10, 2/8, 6/5, 2/8, 4/1 [DS]
  → Gold 10→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=22 Armor=0 Gold=10 Tier=5

  Board (7/7): 9/12, 20/20, 3/6 [Taunt,WF], 5/6, 2/8, 4/4 [DS], 5/4
  Tavern (6 items): Marquee Ticker 3/7 T4 $3 | Ancestral Automaton 3/4 T2 $3 | Leeching Felhound 3/3 T3 $3 | Auto Assembler 2/2 T4 $3 | Abyssal Bruiser 1/1 T4 $3 | Wave of Gold (spell) T5 $2
  Hand: 1 cards

  → Board (7/7): 11/14, 26/26, 7/8, 2/8, 5/4, 3/7, 3/8
  → Gold 10→0 | HP 22→17 | Hand 1→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=5 Gold=10 Tier=5

  Board (7/7): 5/8, 5/6, 5/6, 6/7, 3/6, 3/5, 3/2
  Tavern (6 items): Banana Slamma 3/6 T4 $3 | Wyvern Outrider 2/8 T4 $3 | Tranquil Meditative 3/8 T5 $3 | Shell Collector 4/3 T2 $3 | Sinrunner Blanchy 8/8 T5 $3 | Armor Stash (spell) T5 $3
  Hand: 0 cards

  → Board (7/7): 5/8, 5/6, 5/6, 6/7, 8/8 [Reborn], 3/8, 4/3
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Sneed (first: Overlord Saurfang)
     Overlord Saurfang: [19/25, 21/21, 22/22, 33/33, 32/30, 32/33, 29/31]
     Sneed: [9/12, 4/6, 6/6, 2/8, 4/4, 4/3, 1/1]
     Waverider 19/25→19/19  |  Imposing Percussionist 6/6→6/0 DEAD
     Wrath Weaver 9/12→9/0 DEAD  |  Shadowdancer 32/30→32/21
     Stomping Stegodon 21/21→21/20  |  Abyssal Bruiser 1/1→1/1
     Dustbone Devastator 4/6→5/0 DEAD  |  Annoy-o-Module 29/31→29/31
     Cadaver Caretaker 22/22→22/20  |  Waverider 2/8→2/0 DEAD
     Holo Rover 4/4→4/4  |  Shadowdancer 32/21→32/17
     Ashen Corruptor 33/33→33/29  |  Shell Collector 4/3→4/0 DEAD
     Abyssal Bruiser 1/1→1/0 DEAD  |  Shadowdancer 32/17→32/16
     Shadowdancer 32/16→32/12  |  Holo Rover 4/4→4/0 DEAD
     Result: 7 vs 0 — heur
  [heur] Ysera vs [heur] Professor Putricide (first: Professor Putricide)
     Ysera: [6/6, 9/7, 2/8, 8/8, 4/12, 6/6, 2/5]
     Professor Putricide: [5/6, 10/12, 9/10, 2/8, 6/5, 2/8, 4/1]
     Technical Element 5/6→5/0 DEAD  |  Ashen Corruptor 6/6→6/1
     Scarlet Survivor 6/6→6/4  |  Wyvern Outrider 2/8→2/2
     Nerubian Deathswarmer 10/12→10/8  |  Kalecgos, Arcane Aspect 4/12→4/2
     Trigore the Lasher 9/7→9/3  |  Charging Czarina 4/1→4/1
     Trigore the Lasher 9/10→9/8  |  Incubation Researcher 2/8→2/0 DEAD
     Sinrunner Blanchy 8/8→8/2  |  Scrap Scraper 6/5→6/0 DEAD
     Wyvern Outrider 2/2→2/0 DEAD  |  Kalecgos, Arcane Aspect 4/2→4/0 DEAD
     Ashen Corruptor 6/1→6/0 DEAD  |  Trigore the Lasher 9/8→9/2
     Wyvern Outrider 2/8→2/6  |  Lava Lurker 2/5→2/3
     Lava Lurker 2/3→2/0 DEAD  |  Trigore the Lasher 9/2→9/0 DEAD
     Charging Czarina 4/1→4/0 DEAD  |  Trigore the Lasher 9/3→9/0 DEAD
     Result: 2 vs 2 — heur
  [heur] Drek'Thar vs [heur] Sylvanas Windrunner (first: Drek'Thar)
     Drek'Thar: [5/8, 5/6, 5/6, 6/7, 8/8, 3/8, 4/3]
     Sylvanas Windrunner: [11/14, 26/26, 7/8, 2/8, 5/4, 3/7, 3/8]
     Wrath Weaver 5/8→5/3  |  Malchezaar, Prince of Dance 5/4→5/0 DEAD
     Wrath Weaver 11/14→11/6  |  Sinrunner Blanchy 8/8→8/0 DEAD
     Technical Element 5/6→5/3  |  Lurking Leviathan 3/8→3/3
     Floating Watcher 26/26→26/21  |  Technical Element 5/3→5/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Wrath Weaver 11/6→11/1
     Technical Element 7/8→7/5  |  Tranquil Meditative 3/8→3/1
     Zesty Shaker 6/7→6/5  |  Waverider 2/8→2/2
     Waverider 2/2→2/0 DEAD  |  Tranquil Meditative 3/1→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Lurking Leviathan 3/3→3/0 DEAD
     Marquee Ticker 3/7→3/1  |  Zesty Shaker 6/5→6/2
     Result: 2 vs 4 — heur

  **Sneed [Heuristic] eliminated!** (Turn 10)
  Alive: 6/8
  HP: Overlord Saurfang (HP=30, Tier=5) | Drek'Thar (HP=30, Tier=5) | Ysera (HP=18, Tier=5) | Sylvanas Windrunner (HP=17, Tier=5) | Inge, the Iron Hymn (HP=11, Tier=5) | Professor Putricide (HP=3, Tier=5)

### Turn 11

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=10 Tier=5

  Board (7/7): 19/25, 21/21, 22/22, 33/33, 32/30 [Taunt], 32/33, 29/31 [Taunt,DS]
  Tavern (6 items): Abyssal Bruiser 1/1 T4 $3 | Darkcrest Strategist 39/40 T5 $3 | Tichondrius 38/41 T5 $3 | Rimescale Priestess 38/38 T4 $3 | Auto Assembler 37/37 T4 $3 | Contracted Corpse (spell) T5 $3
  Hand: 2 cards

  → Board (7/7): 19/25, 24/24, 33/33, 32/30 [Taunt], 32/33, 29/31 [Taunt,DS], 39/40
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=18 Armor=0 Gold=10 Tier=5

  Board (7/7): 6/6 [G], 9/9, 2/8, 8/8 [Reborn], 4/12, 6/6, 2/5
  Tavern (7 items): Drustfallen Butcher 2/7 T5 $3 | Plaguerunner 4/2 T4 $3 | Famished Felbat 6/3 T5 $3 | Marquee Ticker 3/7 T4 $3 | Sprightly Scarab 3/1 T3 $3 | Channel the Devourer (spell) T5 $4 | Sleepy Supporter 4/3 T2 $3
  Hand: 6 cards

  → Board (7/7): 6/6 [G], 9/9, 2/8, 8/8 [Reborn], 4/12, 6/6, 3/7
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=11 Armor=0 Gold=10 Tier=5

  Board (7/7): 13/2, 5/6, 5/6, 13/2, 5/4, 5/4, 2/2
  Tavern (6 items): Divine Sparkbot 4/2 T5 $3 | Woodland Defiler 5/6 T4 $3 | Deflect-o-Bot 3/2 T3 $3 | Prosthetic Hand 3/1 T4 $3 | Lava Lurker 2/5 T2 $3 | Butchering (spell) T5 $2
  Hand: 2 cards

  → Board (7/7): 13/2, 5/6, 5/6, 13/2, 5/4, 5/4, 5/6
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=3 Armor=0 Gold=10 Tier=5

  Board (7/7): 5/6, 10/12, 9/16, 2/8, 6/5, 2/8, 4/1 [DS]
  Tavern (6 items): Tichondrius 3/6 T5 $3 | Woodland Defiler 5/6 T4 $3 | Woodland Defiler 5/6 T4 $3 | Handless Forsaken 3/1 T3 $3 | Iridescent Skyblazer 3/8 T5 $3 | Tavern Coin (spell) T1 $3
  Hand: 1 cards

  → Board (7/7): 5/6, 10/12, 9/16, 2/8, 6/5, 2/8, 5/6
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=17 Armor=0 Gold=10 Tier=5

  Board (7/7): 11/14, 26/26, 7/8, 2/8, 5/4, 3/7, 3/8
  Tavern (6 items): Laboratory Assistant 3/4 T2 $3 | Spiked Savior 8/2 T5 $3 | Void Pup Trainer 7/7 T5 $3 | Friendly Geist 6/3 T4 $3 | Ancestral Automaton 3/4 T2 $3 | Corrupted Cupcakes (spell) T5 $4
  Hand: 1 cards

  → Board (7/7): 15/18, 30/30, 7/8, 2/8, 3/7, 3/8, 7/7
  → Tier 5→6 | Gold 10→0 | HP 17→15 | Hand 1→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=5 Gold=10 Tier=5

  Board (7/7): 5/8, 5/6, 5/6, 6/7, 8/8 [Reborn], 3/8, 4/3
  Tavern (6 items): Ancestral Automaton 3/4 T2 $3 | Nightmare Par-tea Guest 3/3 T5 $3 | Sinrunner Blanchy 8/8 T5 $3 | Manasaber 4/1 T1 $3 | Deep-Sea Angler 2/3 T3 $3 | Hired Headhunter (spell) T5 $3
  Hand: 1 cards

  → Board (7/7): 5/8, 5/6, 5/6, 6/7, 8/8 [Reborn], 3/8, 8/8 [Reborn]
  → Tier 5→6 | Gold 10→0 | Hand 1→0
  → Actions: (auto)

**Combat Phase**

  [heur] Ysera vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Ysera: [6/6, 9/9, 2/8, 8/8, 4/12, 6/6, 3/7]
     Overlord Saurfang: [19/25, 24/24, 33/33, 32/30, 32/33, 29/31, 39/40]
     Waverider 19/25→19/22  |  Marquee Ticker 3/7→3/0 DEAD
     Scarlet Survivor 6/6→6/0 DEAD  |  Annoy-o-Module 29/31→29/31
     Cadaver Caretaker 24/24→24/16  |  Sinrunner Blanchy 8/8→8/0 DEAD
     Trigore the Lasher 9/9→9/0 DEAD  |  Shadowdancer 32/30→32/21
     Ashen Corruptor 33/33→33/27  |  Ashen Corruptor 6/6→6/0 DEAD
     Incubation Researcher 2/8→2/0 DEAD  |  Shadowdancer 32/21→32/19
     Shadowdancer 32/19→32/15  |  Kalecgos, Arcane Aspect 4/12→4/0 DEAD
     Result: 0 vs 7 — heur
  [heur] Drek'Thar vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Drek'Thar: [5/8, 5/6, 5/6, 6/7, 8/8, 3/8, 8/8]
     Inge, the Iron Hymn: [13/2, 5/6, 5/6, 13/2, 5/4, 5/4, 5/6]
     Eternal Knight 13/2→14/0 DEAD  |  Technical Element 5/6→5/0 DEAD
     Wrath Weaver 5/8→5/3  |  Woodland Defiler 5/6→5/1
     Technical Element 5/6→5/1  |  Wrath Weaver 5/3→5/0 DEAD
     Technical Element 5/6→5/1  |  Monstrous Macaw 5/4→5/0 DEAD
     Technical Element 5/6→5/1  |  Technical Element 5/1→5/0 DEAD
     Zesty Shaker 6/7→6/2  |  Technical Element 5/1→5/0 DEAD
     Eternal Knight 14/2→15/0 DEAD  |  Sinrunner Blanchy 8/8→8/0 DEAD
     Sinrunner Blanchy 8/8→8/3  |  Technical Element 5/1→5/0 DEAD
     Monstrous Macaw 5/4→5/1  |  Tranquil Meditative 3/8→3/3
     Tranquil Meditative 3/3→3/0 DEAD  |  Woodland Defiler 5/1→5/0 DEAD
     Result: 2 vs 1 — heur
  [heur] Professor Putricide vs [heur] Sylvanas Windrunner (first: Professor Putricide)
     Professor Putricide: [5/6, 10/12, 9/16, 2/8, 6/5, 2/8, 5/6]
     Sylvanas Windrunner: [15/18, 30/30, 7/8, 2/8, 3/7, 3/8, 7/7]
     Technical Element 5/6→5/0 DEAD  |  Wrath Weaver 15/18→15/13
     Wrath Weaver 15/13→15/11  |  Wyvern Outrider 2/8→2/0 DEAD
     Nerubian Deathswarmer 10/12→10/5  |  Void Pup Trainer 7/7→7/0 DEAD
     Floating Watcher 30/30→30/20  |  Nerubian Deathswarmer 10/5→10/0 DEAD
     Trigore the Lasher 9/16→9/9  |  Technical Element 7/8→7/0 DEAD
     Waverider 2/8→2/6  |  Wyvern Outrider 2/8→2/6
     Scrap Scraper 6/5→6/3  |  Waverider 2/6→2/0 DEAD
     Marquee Ticker 3/7→3/2  |  Woodland Defiler 5/6→5/3
     Wyvern Outrider 2/6→2/0 DEAD  |  Floating Watcher 30/20→30/18
     Lurking Leviathan 3/8→3/0 DEAD  |  Trigore the Lasher 9/9→9/6
     Woodland Defiler 5/3→5/0 DEAD  |  Marquee Ticker 3/2→3/0 DEAD
     Result: 2 vs 2 — heur

  Alive: 6/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Drek'Thar (HP=30, Tier=6) | Sylvanas Windrunner (HP=15, Tier=6) | Inge, the Iron Hymn (HP=11, Tier=6) | Ysera (HP=3, Tier=6) | Professor Putricide (HP=3, Tier=6)

### Turn 12

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=10 Tier=6

  Board (7/7): 19/25, 24/24, 33/33, 32/30 [Taunt], 32/33, 29/31 [Taunt,DS], 39/40
  Tavern (7 items): Eternal Tycoon 41/45 T5 $3 | Rabid Panther 41/45 T6 $3 | Deep Blue Crooner 39/39 T3 $3 | Accord-o-Tron 40/40 T3 $3 | Deep Blue Crooner 39/39 T3 $3 | Metallic Hunter 41/39 T2 $3 | Knockoff Wisdomball (spell) T6 $4
  Hand: 3 cards

  → Board (7/7): 33/33, 39/40, 43/47, 41/45, 40/40, 41/39, 39/39
  → Gold 10→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=3 Armor=0 Gold=10 Tier=6

  Board (7/7): 6/6 [G], 9/10, 2/8, 8/8 [Reborn], 4/12, 6/6, 3/7
  Tavern (8 items): Enchanted Sentinel 3/5 T4 $3 | Eternal Summoner 8/1 T6 $3 | Forsaken Weaver 3/10 T6 $3 | Sly Raptor 1/3 T3 $3 | Spiked Savior 8/2 T5 $3 | Void Pup Trainer 7/7 T5 $3 | Meditation (spell) T1 $3 | Sleepy Supporter 4/3 T2 $3
  Hand: 9 cards

  → Board (7/7): 7/7 [G], 9/10, 10/8 [Reborn], 10/26 [G], 7/7, 5/10, 6/10 [G]
  → Gold 10→0 | Hand 9→7
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=11 Armor=0 Gold=10 Tier=6

  Board (7/7): 15/2, 5/6, 5/6, 15/2, 5/4, 5/4, 5/6
  Tavern (7 items): Tichondrius 3/6 T5 $3 | Moonsteel Juggernaut 8/8 T6 $3 | Zesty Shaker 6/7 T4 $3 | Scrap Scraper 6/5 T5 $3 | Zesty Shaker 6/7 T4 $3 | Junk Jouster 8/7 T6 $3 | Undersea Mount (spell) T1 $3
  Hand: 2 cards

  → Board (7/7): 15/2, 15/2, 8/8, 8/7, 6/7, 6/7, 6/5
  → Gold 10→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=3 Armor=0 Gold=10 Tier=6

  Board (7/7): 5/6, 10/12, 9/21, 2/8, 6/5, 2/8, 5/6
  Tavern (7 items): Banana Slamma 3/6 T4 $3 | Ring Bearer 5/10 T6 $3 | Divine Sparkbot 4/2 T5 $3 | Leeching Felhound 3/3 T3 $3 | Humming Bird 1/4 T2 $3 | Glowscale 4/6 T5 $3 | Eyes of the Earth Mother (spell) T6 $4
  Hand: 1 cards

  → Board (7/7): 5/6, 10/12, 9/21, 6/5, 5/6, 5/10, 3/3
  → Gold 10→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=15 Armor=0 Gold=10 Tier=6

  Board (7/7): 15/18, 30/30, 7/8, 2/8, 3/7, 3/8, 7/7
  Tavern (7 items): Holo Rover 4/4 T4 $3 | Batty Terrorguard 6/2 T6 $3 | Banana Slamma 3/6 T4 $3 | Twisted Wrathguard 8/8 T6 $3 | Waverider 2/8 T4 $3 | Tichondrius 3/6 T5 $3 | Perfect Vision (spell) T6 $2
  Hand: 3 cards

  → Board (7/7): 26/29 [Taunt], 40/40, 7/8, 9/9, 10/10, 7/10, 9/9 [Taunt,DS]
  → Gold 10→0 | HP 15→11 | Hand 3→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=5 Gold=10 Tier=6

  Board (7/7): 5/8, 5/6, 5/6, 6/7, 8/8 [Reborn], 3/8, 8/8 [Reborn]
  Tavern (7 items): Dustbone Devastator 2/6 T3 $3 | Abyssal Bruiser 1/1 T4 $3 | Spiked Savior 8/2 T5 $3 | Sewer Rat 3/2 T2 $3 | Hardy Orca 1/6 T3 $3 | Wyvern Outrider 2/8 T4 $3 | Lost Staff of Hamuul (spell) T6 $2
  Hand: 1 cards

  → Board (7/7): 5/8, 5/6, 6/7, 8/8 [Reborn], 3/8, 8/8 [Reborn], 3/2
  → Gold 10→0 | Hand 1→0
  → Actions: (auto)

**Combat Phase**

  [heur] Ysera vs [heur] Drek'Thar (first: Drek'Thar)
     Ysera: [7/7, 9/10, 10/8, 10/26, 7/7, 5/10, 6/10]
     Drek'Thar: [5/8, 5/6, 6/7, 8/8, 3/8, 8/8, 3/2]
     Wrath Weaver 5/8→5/2  |  Enchanted Sentinel 6/10→6/5
     Scarlet Survivor 7/7→7/1  |  Zesty Shaker 6/7→6/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Enchanted Sentinel 6/5→6/0 DEAD
     Trigore the Lasher 9/10→9/2  |  Sinrunner Blanchy 8/8→8/0 DEAD
     Tranquil Meditative 3/8→3/1  |  Void Pup Trainer 7/7→7/4
     Sinrunner Blanchy 10/8→10/0 DEAD  |  Sinrunner Blanchy 8/8→8/0 DEAD
     Sewer Rat 3/2→3/0 DEAD  |  Trigore the Lasher 9/2→9/0 DEAD
     Kalecgos, Arcane Aspect 10/26→10/21  |  Wrath Weaver 5/2→5/0 DEAD
     Result: 4 vs 1 — heur
  [heur] Sylvanas Windrunner vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Sylvanas Windrunner: [26/29, 40/40, 7/8, 9/9, 10/10, 7/10, 9/9]
     Overlord Saurfang: [33/33, 39/40, 43/47, 41/45, 40/40, 41/39, 39/39]
     Ashen Corruptor 33/33→33/7  |  Wrath Weaver 26/29→26/0 DEAD
     Floating Watcher 40/40→40/0 DEAD  |  Metallic Hunter 41/39→41/0 DEAD
     Darkcrest Strategist 39/40→39/31  |  Holo Rover 9/9→9/9
     Technical Element 7/8→7/0 DEAD  |  Deep Blue Crooner 39/39→39/32
     Eternal Tycoon 43/47→43/38  |  Holo Rover 9/9→9/0 DEAD
     Void Pup Trainer 9/9→9/0 DEAD  |  Eternal Tycoon 43/38→43/29
     Rabid Panther 41/45→41/38  |  Tichondrius 7/10→7/0 DEAD
     Twisted Wrathguard 10/10→10/0 DEAD  |  Ashen Corruptor 33/7→33/0 DEAD
     Result: 0 vs 5 — heur
  [heur] Inge, the Iron Hymn vs [heur] Professor Putricide (first: Professor Putricide)
     Inge, the Iron Hymn: [15/2, 15/2, 8/8, 8/7, 6/7, 6/7, 6/5]
     Professor Putricide: [5/6, 10/12, 9/21, 6/5, 5/6, 5/10, 3/3]
     Technical Element 5/6→5/0 DEAD  |  Zesty Shaker 6/7→6/2
     Eternal Knight 15/2→16/0 DEAD  |  Trigore the Lasher 9/21→9/6
     Nerubian Deathswarmer 10/12→10/0 DEAD  |  Eternal Knight 16/2→17/0 DEAD
     Moonsteel Juggernaut 8/8→8/3  |  Woodland Defiler 5/6→5/0 DEAD
     Trigore the Lasher 9/6→9/0 DEAD  |  Zesty Shaker 6/7→6/0 DEAD
     Junk Jouster 8/7→8/4  |  Leeching Felhound 3/3→3/0 DEAD
     Scrap Scraper 6/5→6/0 DEAD  |  Scrap Scraper 6/5→6/0 DEAD
     Zesty Shaker 6/2→6/0 DEAD  |  Ring Bearer 5/10→5/4
     Ring Bearer 5/4→5/0 DEAD  |  Junk Jouster 8/4→8/0 DEAD
     Result: 1 vs 0 — heur

  **Professor Putricide [Heuristic] eliminated!** (Turn 12)
  **Sylvanas Windrunner [Heuristic] eliminated!** (Turn 12)
  Alive: 4/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Drek'Thar (HP=30, Tier=6) | Inge, the Iron Hymn (HP=11, Tier=6) | Ysera (HP=3, Tier=6)

### Turn 13

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=11 Tier=6

  Board (7/7): 33/33, 39/40, 43/47, 41/45, 40/40, 41/39, 39/39
  Tavern (7 items): Catacomb Crasher 48/54 T5 $3 | Imposing Percussionist 48/48 T4 $3 | Accord-o-Tron 47/47 T3 $3 | Zesty Shaker 50/51 T4 $3 | Bazaar Dealer 48/50 T5 $3 | Trigore the Lasher 53/47 T4 $3 | Meditation (spell) T1 $3
  Hand: 4 cards

  → Board (7/7): 43/47, 42/46, 48/54, 50/51, 54/48, 48/50, 50/50 [Taunt]
  → Gold 11→0 | Armor 15→9
  → Actions: (auto)

**Ysera** [Heuristic]  HP=3 Armor=0 Gold=10 Tier=6

  Board (7/7): 7/7 [G], 9/12, 10/8 [Reborn], 10/26 [G], 7/7, 5/10, 6/10 [G]
  Tavern (8 items): Ancestral Automaton 3/4 T2 $3 | Charging Czarina 4/1 T5 $3 | Metallic Hunter 6/4 T2 $3 | Deep-Sea Angler 4/5 T3 $3 | Annoy-o-Module 4/6 T3 $3 | Forsaken Weaver 5/10 T6 $3 | Azerite Empowerment (spell) T6 $4 | Felfire Conjurer 6/5 T5 $3
  Hand: 9 cards

  → Board (7/7): 9/12, 10/8 [Reborn], 10/26 [G], 5/10, 6/10 [G], 5/10, 4/5
  → Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=11 Armor=0 Gold=10 Tier=6

  Board (7/7): 17/2, 17/2, 8/8, 8/7, 6/7, 6/7, 6/5
  Tavern (7 items): Woodland Defiler 5/6 T4 $3 | Laboratory Assistant 3/4 T2 $3 | Monstrous Macaw 5/4 T4 $3 | Manasaber 4/1 T1 $3 | Imposing Percussionist 4/4 T4 $3 | Shadowdancer 5/3 T5 $3 | Undersea Mount (spell) T1 $3
  Hand: 5 cards

  → Board (7/7): 17/2, 17/2, 8/8, 8/7, 6/7, 6/7, 3/4
  → Gold 10→0 | HP 11→6 | Hand 5→6
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=5 Gold=10 Tier=6

  Board (7/7): 5/8, 5/6, 6/7, 8/8 [Reborn], 3/8, 8/8 [Reborn], 2/3 [Taunt]
  Tavern (7 items): Enchanted Sentinel 3/5 T4 $3 | Ring Bearer 5/10 T6 $3 | Imposing Percussionist 4/4 T4 $3 | Sewer Lord 4/6 T5 $3 | Prosthetic Hand 3/1 T4 $3 | Deathly Striker 8/8 T6 $3 | Golden Touch (spell) T5 $5
  Hand: 1 cards

  → Board (7/7): 7/10, 6/7, 8/8 [Reborn], 8/8 [Reborn], 8/8, 5/10, 4/4
  → Gold 10→0 | HP 30→27 | Armor 5→0
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Drek'Thar (first: Overlord Saurfang)
     Overlord Saurfang: [43/47, 42/46, 48/54, 50/51, 54/48, 48/50, 50/50]
     Drek'Thar: [7/10, 6/7, 8/8, 8/8, 8/8, 5/10, 4/4]
     Eternal Tycoon 43/47→43/41  |  Zesty Shaker 6/7→6/0 DEAD
     Wrath Weaver 7/10→7/0 DEAD  |  Imposing Percussionist 50/50→50/43
     Rabid Panther 42/46→42/38  |  Sinrunner Blanchy 8/8→8/0 DEAD
     Sinrunner Blanchy 8/8→8/0 DEAD  |  Imposing Percussionist 50/43→50/35
     Catacomb Crasher 48/54→48/46  |  Deathly Striker 8/8→8/0 DEAD
     Ring Bearer 5/10→5/0 DEAD  |  Imposing Percussionist 50/35→50/30
     Zesty Shaker 50/51→50/47  |  Imposing Percussionist 4/4→4/0 DEAD
     Result: 7 vs 0 — heur
  [heur] Ysera vs [heur] Inge, the Iron Hymn (first: Ysera)
     Ysera: [9/12, 10/8, 10/26, 5/10, 6/10, 5/10, 4/5]
     Inge, the Iron Hymn: [17/2, 17/2, 8/8, 8/7, 6/7, 6/7, 3/4]
     Trigore the Lasher 9/12→9/4  |  Junk Jouster 8/7→8/0 DEAD
     Eternal Knight 17/2→18/0 DEAD  |  Forsaken Weaver 5/10→5/0 DEAD
     Sinrunner Blanchy 10/8→10/2  |  Zesty Shaker 6/7→6/0 DEAD
     Eternal Knight 18/2→19/0 DEAD  |  Deep-Sea Angler 4/5→4/0 DEAD
     Kalecgos, Arcane Aspect 10/26→10/23  |  Laboratory Assistant 3/4→3/0 DEAD
     Moonsteel Juggernaut 8/8→8/3  |  Forsaken Weaver 5/10→5/2
     Enchanted Sentinel 6/10→6/4  |  Zesty Shaker 6/7→6/1
     Zesty Shaker 6/1→6/0 DEAD  |  Forsaken Weaver 5/2→5/0 DEAD
     Result: 4 vs 1 — heur

  **Drek'Thar [Heuristic] eliminated!** (Turn 13)
  Alive: 3/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Inge, the Iron Hymn (HP=6, Tier=6) | Ysera (HP=3, Tier=6)

### Turn 14

**Overlord Saurfang** [Heuristic]  HP=30 Armor=9 Gold=10 Tier=6

  Board (7/7): 43/47, 42/46, 48/54, 50/51, 54/49, 48/50, 50/50 [Taunt]
  Tavern (7 items): Sly Raptor 50/52 T3 $3 | Waverider 51/57 T4 $3 | P-0UL-TR-0N 59/59 T6 $3 | Metallic Hunter 53/51 T2 $3 | Catacomb Crasher 53/59 T5 $3 | Tidemistress Athissa 55/56 T6 $3 | Meditation (spell) T1 $3
  Hand: 4 cards

  → Board (7/7): 48/54 [DS], 54/49, 59/59, 53/59, 57/58, 53/59, 55/53
  → Gold 10→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=3 Armor=0 Gold=10 Tier=6

  Board (7/7): 9/13, 10/8 [Reborn], 10/26 [G], 5/10, 6/10 [G], 5/10, 4/5
  Tavern (8 items): Trigore the Lasher 9/3 T4 $3 | Shell Collector 6/5 T2 $3 | Twisted Wrathguard 8/8 T6 $3 | Wyvern Outrider 2/8 T4 $3 | Deflect-o-Bot 5/4 T3 $3 | Sinrunner Blanchy 10/8 T5 $3 | Evolving Strategy (spell) T1 $3 | Sleepy Supporter 4/3 T2 $3
  Hand: 10 cards

  → Board (7/7): 9/13, 12/8 [Reborn], 12/28 [G], 7/10, 6/10 [G], 9/12 [Taunt], 4/6
  → Gold 10→0 | Hand 10→8
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=6 Armor=0 Gold=10 Tier=6

  Board (7/7): 19/2, 19/2, 8/8, 8/7, 6/7, 6/7, 3/4
  Tavern (7 items): Enchanted Sentinel 3/5 T4 $3 | Sewer Rat 3/2 T2 $3 | Twisted Wrathguard 8/8 T6 $3 | Wyvern Outrider 2/8 T4 $3 | Wintergrasp Ghoul 5/3 T5 $3 | P-0UL-TR-0N 10/10 T6 $3 | Angler's Lure (spell) T1 $3
  Hand: 8 cards

  → Board (7/7): 19/2, 19/2, 8/8, 8/7, 10/10, 8/8, 5/3
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Overlord Saurfang: [48/54, 54/49, 59/59, 53/59, 57/58, 53/59, 55/53]
     Inge, the Iron Hymn: [19/2, 19/2, 8/8, 8/7, 10/10, 8/8, 5/3]
     Eternal Knight 19/2→20/0 DEAD  |  Catacomb Crasher 53/59→53/40
     Catacomb Crasher 48/54→48/54  |  Twisted Wrathguard 8/8→8/0 DEAD
     Eternal Knight 20/2→21/0 DEAD  |  Tidemistress Athissa 57/58→57/38
     Trigore the Lasher 54/49→54/44  |  Wintergrasp Ghoul 5/3→5/0 DEAD
     Moonsteel Juggernaut 8/8→8/0 DEAD  |  Catacomb Crasher 48/54→48/46
     P-0UL-TR-0N 59/59→59/51  |  Junk Jouster 8/7→8/0 DEAD
     Result: 7 vs 1 — heur

  Alive: 3/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Inge, the Iron Hymn (HP=6, Tier=6) | Ysera (HP=3, Tier=6)

### Turn 15

**Overlord Saurfang** [Heuristic]  HP=30 Armor=9 Gold=10 Tier=6

  Board (7/7): 48/54 [DS], 54/50, 59/59, 53/59, 57/58, 53/59, 55/53
  Tavern (7 items): Monstrous Macaw 57/56 T4 $3 | Nightmare Par-tea Guest 55/55 T5 $3 | Glowscale 56/58 T5 $3 | Charging Czarina 56/53 T5 $3 | Laboratory Assistant 55/56 T2 $3 | Seafloor Recruiter 55/57 T4 $3 | Angler's Lure (spell) T1 $3
  Hand: 5 cards

  → Board (7/7): 59/59, 61/62, 57/63, 60/62 [Taunt], 61/60 [Taunt], 59/61, 55/55
  → Gold 10→0 | Hand 5→6
  → Actions: (auto)

**Ysera** [Heuristic]  HP=3 Armor=0 Gold=10 Tier=6

  Board (7/7): 9/14, 12/8 [Reborn], 12/28 [G], 7/10, 6/10 [G], 9/12 [Taunt], 4/6
  Tavern (7 items): Woodland Defiler 5/6 T4 $3 | Marquee Ticker 3/7 T4 $3 | Woodland Defiler 5/6 T4 $3 | Cadaver Caretaker 9/5 T3 $3 | Shadowdancer 5/3 T5 $3 | Tide Raiser 4/3 T2 $3 | Scarlet Survivor 3/3 T1 $3
  Hand: 8 cards

  → Board (7/7): 9/14, 12/8 [Reborn], 12/28 [G], 7/10, 9/12 [Taunt], 9/5, 5/3 [Taunt]
  → Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=6 Armor=0 Gold=10 Tier=6

  Board (7/7): 21/2, 21/2, 8/8, 8/7, 10/10, 8/8, 5/3
  Tavern (6 items): Shell Collector 4/3 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Darkcrest Strategist 4/5 T5 $3 | Shell Collector 4/3 T2 $3 | Enchanted Sentinel 3/5 T4 $3 | Accord-o-Tron 3/3 T3 $3
  Hand: 10 cards

  → Board (7/7): 21/2, 21/2, 8/8, 8/7, 10/10, 8/8, 1/5
  → Gold 10→0 | Hand 10→9
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Ysera (first: Overlord Saurfang)
     Overlord Saurfang: [59/59, 61/62, 57/63, 60/62, 61/60, 59/61, 55/55]
     Ysera: [9/14, 12/8, 12/28, 7/10, 9/12, 9/5, 5/3]
     P-0UL-TR-0N 59/59→59/54  |  Shadowdancer 5/3→5/0 DEAD
     Trigore the Lasher 9/14→9/0 DEAD  |  Monstrous Macaw 61/60→61/51
     Tidemistress Athissa 61/62→61/53  |  Forsaken Weaver 9/12→9/0 DEAD
     Sinrunner Blanchy 12/8→12/0 DEAD  |  Glowscale 60/62→60/50
     Waverider 57/63→57/51  |  Kalecgos, Arcane Aspect 12/28→12/0 DEAD
     Forsaken Weaver 7/10→7/0 DEAD  |  Monstrous Macaw 61/51→61/44
     Glowscale 60/50→60/41  |  Cadaver Caretaker 9/5→9/0 DEAD
     Result: 7 vs 0 — heur

  **Ysera [Heuristic] eliminated!** (Turn 15)
  Alive: 2/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Inge, the Iron Hymn (HP=6, Tier=6)

---

## Final Standings

| # | Hero | Role | HP | Tier | Eliminated |
|---|---|---|---|---|---|
| 1 | Overlord Saurfang | Heuristic | 30 | 6 | — |
| 2 | Inge, the Iron Hymn | Heuristic | 6 | 6 | — |
| 3 | Ysera | Heuristic | 0 | 6 | 15 |
| 4 | Drek'Thar | Heuristic | 0 | 6 | 13 |
| 5 | Professor Putricide | Heuristic | 0 | 6 | 12 |
| 6 | Sylvanas Windrunner | Heuristic | 0 | 6 | 12 |
| 7 | Sneed | Heuristic | 0 | 5 | 10 |
| 8 | Yogg-Saron, Hope's End | AGENT | 0 | 3 | 8 |