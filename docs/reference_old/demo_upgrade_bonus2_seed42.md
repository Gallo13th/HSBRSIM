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

  → Gold 4→3
  → Actions: refresh

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

  [heur] Drek'Thar vs [AGENT] Yogg-Saron, Hope's End (first: Drek'Thar)
     Drek'Thar: [2/1, 1/2]
     Yogg-Saron, Hope's End: []
     Result: 2 vs 0 — heur
  [heur] Overlord Saurfang vs [heur] Ysera (first: Overlord Saurfang)
     Overlord Saurfang: [4/7, 3/6]
     Ysera: [3/3, 3/3]
     Wrath Weaver 4/7→4/4  |  Scarlet Survivor 3/3→3/0 DEAD
     Scarlet Survivor 3/3→3/0 DEAD  |  Wrath Weaver 4/4→4/1
     Result: 2 vs 0 — heur
  [heur] Inge, the Iron Hymn vs [heur] Sneed (first: Sneed)
     Inge, the Iron Hymn: [4/1, 1/2]
     Sneed: [2/1, 1/4]
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 1/4→1/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Sylvanas Windrunner vs [heur] Professor Putricide (first: Professor Putricide)
     Sylvanas Windrunner: [2/1, 1/4]
     Professor Putricide: [4/1, 2/1]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 1/4→1/2  |  Ominous Seer 2/1→2/0 DEAD
     Result: 1 vs 0 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=1) | Sneed (HP=30, Tier=1) | Overlord Saurfang (HP=30, Tier=1) | Ysera (HP=30, Tier=1) | Inge, the Iron Hymn (HP=30, Tier=1) | Professor Putricide (HP=30, Tier=1) | Sylvanas Windrunner (HP=30, Tier=1) | Drek'Thar (HP=30, Tier=1)

### Turn 3

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=13 Gold=5 Tier=1

  Board: (empty)
  Tavern (3 items): Wrath Weaver 1/4 T1 $3 | Picky Eater 1/1 T1 $3 | Risen Rider 2/1 T1 $3
  Hand: 0 cards

  → Tier 1→2 | Gold 5→3
  → Actions: upgrade

**Sneed** [Heuristic]  HP=30 Armor=10 Gold=5 Tier=1

  Board (2/7): 2/1, 1/4
  Tavern (3 items): Wrath Weaver 1/4 T1 $3 | Cord Puller 1/1 T1 $3 | Cord Puller 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1, 3/6, 1/4
  → Tier 1→2 | Gold 5→0 | Armor 10→9
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=5 Tier=1

  Board (2/7): 4/7, 3/6
  Tavern (3 items): Risen Rider 6/5 T1 $3 | Cord Puller 5/5 T1 $3 | Annoy-o-Tron 5/6 T1 $3
  Hand: 0 cards

  → Board (3/7): 4/7, 3/6, 6/5 [Taunt,Reborn]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=9 Gold=5 Tier=1

  Board (2/7): 3/3, 3/3
  Tavern (4 items): Risen Rider 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Picky Eater 1/1 T1 $3 | Scarlet Survivor 3/3 T1 $3
  Hand: 0 cards

  → Board (1/7): 6/6 [G]
  → Tier 1→2 | Gold 5→0 | Hand 0→1
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=5 Tier=1

  Board (2/7): 4/1, 1/2 [Taunt,DS]
  Tavern (3 items): Wrath Weaver 1/4 T1 $3 | Ominous Seer 2/1 T1 $3 | Manasaber 4/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 4/1, 1/2 [Taunt,DS], 1/4
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=8 Gold=5 Tier=1

  Board (2/7): 4/1, 2/1
  Tavern (3 items): Cord Puller 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Risen Rider 2/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 4/1, 2/1, 1/2 [Taunt,DS]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=10 Gold=5 Tier=1

  Board (2/7): 2/1 [Taunt,Reborn], 1/4
  Tavern (3 items): Cord Puller 1/1 T1 $3 | Picky Eater 1/1 T1 $3 | Ominous Seer 2/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1 [Taunt,Reborn], 1/4, 2/1
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=5 Tier=1

  Board (2/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS]
  Tavern (3 items): Surf n' Surf 1/1 T1 $3 | Ominous Seer 2/1 T1 $3 | Cord Puller 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 2/1
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Combat Phase**

  [heur] Professor Putricide vs [heur] Drek'Thar (first: Drek'Thar)
     Professor Putricide: [4/1, 2/1, 1/2]
     Drek'Thar: [2/1, 1/2, 2/1]
     Risen Rider 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 1/1→1/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 1/1→1/0 DEAD
     Result: 0 vs 0 — draw
  [heur] Sneed vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Sneed: [2/1, 3/6, 1/4]
     Sylvanas Windrunner: [2/1, 1/4, 2/1]
     Risen Rider 2/1→2/0 DEAD  |  Ominous Seer 2/1→2/0 DEAD
     Wrath Weaver 3/6→3/5  |  Wrath Weaver 1/4→1/1
     Wrath Weaver 1/1→1/0 DEAD  |  Wrath Weaver 3/5→3/4
     Wrath Weaver 1/4→1/2  |  Ominous Seer 2/1→2/0 DEAD
     Result: 2 vs 0 — heur
  [heur] Ysera vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Ysera: [6/6]
     Inge, the Iron Hymn: [4/1, 1/2, 1/4]
     Manasaber 4/1→4/0 DEAD  |  Scarlet Survivor 6/6→6/2
     Scarlet Survivor 6/2→6/1  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Scarlet Survivor 6/1→6/0 DEAD
     Result: 0 vs 1 — heur
  [heur] Overlord Saurfang vs [AGENT] Yogg-Saron, Hope's End (first: Overlord Saurfang)
     Overlord Saurfang: [4/7, 3/6, 6/5]
     Yogg-Saron, Hope's End: []
     Result: 3 vs 0 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=2) | Sneed (HP=30, Tier=2) | Overlord Saurfang (HP=30, Tier=2) | Ysera (HP=30, Tier=2) | Inge, the Iron Hymn (HP=30, Tier=2) | Professor Putricide (HP=30, Tier=2) | Sylvanas Windrunner (HP=30, Tier=2) | Drek'Thar (HP=30, Tier=2)

### Turn 4

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=8 Gold=6 Tier=2

  Board: (empty)
  Tavern (5 items): Nerubian Deathswarmer 1/4 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Picky Eater 1/1 T1 $3 | Ominous Seer 2/1 T1 $3 | Search Through Time (spell) T2 $2
  Hand: 0 cards

  → Actions: 

**Sneed** [Heuristic]  HP=30 Armor=9 Gold=6 Tier=2

  Board (3/7): 2/1, 3/6, 1/4
  Tavern (5 items): Cord Puller 1/1 T1 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Ominous Seer 2/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Hasty Excavation (spell) T2 $3
  Hand: 0 cards

  → Board (5/7): 2/1, 3/6, 1/4, 2/4, 2/1
  → Gold 6→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=6 Tier=2

  Board (3/7): 4/7, 3/6, 6/5 [Taunt,Reborn]
  Tavern (5 items): Annoy-o-Tron 7/8 T1 $3 | Ancestral Automaton 3/4 T2 $3 | Scarlet Skull 8/7 T2 $3 | Soul Rewinder 10/7 T2 $3 | Leaf Through the Pages (spell) T2 $1
  Hand: 0 cards

  → Board (5/7): 6/9, 5/8, 6/5 [Taunt,Reborn], 10/7, 7/8 [Taunt,DS]
  → Gold 6→0 | Armor 17→15
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=6 Gold=6 Tier=2

  Board (1/7): 6/6 [G]
  Tavern (6 items): Nerubian Deathswarmer 1/4 T2 $3 | Shell Collector 4/3 T2 $3 | Alert Alarmist 2/2 T2 $3 | Scarlet Skull 2/1 T2 $3 | Might of Stormwind (spell) T2 $2 | Blazing Skyfin 2/4 T2 $3
  Hand: 1 cards

  → Board (3/7): 6/6 [G], 4/3, 2/4
  → Gold 6→5
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=6 Tier=2

  Board (3/7): 4/1, 1/2 [Taunt,DS], 1/4
  Tavern (5 items): Eternal Knight 4/2 T2 $3 | Sewer Rat 3/2 T2 $3 | Sewer Rat 3/2 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Strike Oil (spell) T2 $3
  Hand: 0 cards

  → Board (5/7): 4/1, 1/2 [Taunt,DS], 3/6, 3/4, 4/2
  → Gold 6→0 | Armor 12→11
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=8 Gold=6 Tier=2

  Board (3/7): 4/1, 2/1, 1/2 [Taunt,DS]
  Tavern (5 items): Nerubian Deathswarmer 1/4 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Scarlet Skull 2/1 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Chef's Choice (spell) T2 $2
  Hand: 0 cards

  → Board (5/7): 4/1, 2/1, 1/2 [Taunt,DS], 3/4, 2/4
  → Gold 6→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=6 Gold=6 Tier=2

  Board (3/7): 2/1 [Taunt,Reborn], 1/4, 2/1
  Tavern (4 items): Metallic Hunter 4/2 T2 $3 | Metallic Hunter 4/2 T2 $3 | Metallic Hunter 4/2 T2 $3 | Cord Puller 1/1 T1 $3
  Hand: 0 cards

  → Board (5/7): 2/1 [Taunt,Reborn], 1/4, 2/1, 4/2, 4/2
  → Gold 6→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=6 Tier=2

  Board (3/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 2/1
  Tavern (4 items): Surf n' Surf 1/1 T1 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Old Soul 3/4 T2 $3 | Eternal Knight 4/2 T2 $3
  Hand: 0 cards

  → Board (5/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 2/1, 3/4, 4/2
  → Gold 6→0
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Inge, the Iron Hymn (first: Overlord Saurfang)
     Overlord Saurfang: [6/9, 5/8, 6/5, 10/7, 7/8]
     Inge, the Iron Hymn: [4/1, 1/2, 3/6, 3/4, 4/2]
     Wrath Weaver 6/9→6/8  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 7/8→7/8
     Wrath Weaver 5/8→5/7  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 3/6→3/0 DEAD  |  Risen Rider 6/5→6/2
     Risen Rider 6/2→6/0 DEAD  |  Eternal Knight 4/2→5/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Annoy-o-Tron 7/8→7/5
     Result: 4 vs 0 — heur
  [AGENT] Yogg-Saron, Hope's End vs [heur] Ysera (first: Ysera)
     Yogg-Saron, Hope's End: []
     Ysera: [6/6, 4/3, 2/4]
     Result: 0 vs 3 — heur
  [heur] Professor Putricide vs [heur] Sneed (first: Professor Putricide)
     Professor Putricide: [4/1, 2/1, 1/2, 3/4, 2/4]
     Sneed: [2/1, 3/6, 1/4, 2/4, 2/1]
     Manasaber 4/1→4/0 DEAD  |  Ominous Seer 2/1→2/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Ominous Seer 2/1→2/0 DEAD  |  Wrath Weaver 3/6→3/4
     Wrath Weaver 3/4→3/3  |  Annoy-o-Tron 1/2→1/0 DEAD
     Laboratory Assistant 3/4→3/1  |  Wrath Weaver 3/3→3/0 DEAD
     Wrath Weaver 1/4→1/2  |  Nerubian Deathswarmer 2/4→2/3
     Nerubian Deathswarmer 2/3→2/1  |  Nerubian Deathswarmer 2/4→2/2
     Nerubian Deathswarmer 2/2→2/0 DEAD  |  Nerubian Deathswarmer 2/1→2/0 DEAD
     Result: 1 vs 1 — heur
  [heur] Sylvanas Windrunner vs [heur] Drek'Thar (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [2/1, 1/4, 2/1, 4/2, 4/2]
     Drek'Thar: [2/1, 1/2, 2/1, 3/4, 4/2]
     Risen Rider 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Risen Rider 2/1→2/0 DEAD  |  Wrath Weaver 1/4→1/2
     Wrath Weaver 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Annoy-o-Tron 1/1→1/0 DEAD  |  Metallic Hunter 4/2→4/1
     Ominous Seer 2/1→2/0 DEAD  |  Ominous Seer 2/1→2/0 DEAD
     Old Soul 3/4→3/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Metallic Hunter 4/1→4/0 DEAD  |  Eternal Knight 4/2→5/0 DEAD
     Result: 1 vs 0 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=2) | Sneed (HP=30, Tier=2) | Overlord Saurfang (HP=30, Tier=2) | Ysera (HP=30, Tier=2) | Inge, the Iron Hymn (HP=30, Tier=2) | Professor Putricide (HP=30, Tier=2) | Sylvanas Windrunner (HP=30, Tier=2) | Drek'Thar (HP=30, Tier=2)

### Turn 5

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=1 Gold=7 Tier=2

  Board: (empty)
  Tavern (5 items): Ancestral Automaton 3/4 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Lava Lurker 2/5 T2 $3 | Tavern Coin (spell) T1 $3
  Hand: 0 cards

  → Board (1/7): 3/4
  → Gold 7→4
  → Actions: buy_tavern_1, play_hand_0

**Sneed** [Heuristic]  HP=30 Armor=9 Gold=7 Tier=2

  Board (5/7): 2/1, 3/6, 1/4, 2/4, 2/1
  Tavern (4 items): Old Soul 4/4 T2 $3 | Tide Raiser 2/1 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Humming Bird 1/4 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=7 Tier=2

  Board (5/7): 6/9, 5/8, 6/5 [Taunt,Reborn], 10/7, 7/8 [Taunt,DS]
  Tavern (4 items): Old Soul 12/13 T2 $3 | Tide Raiser 11/10 T2 $3 | Soul Rewinder 13/10 T2 $3 | Wrath Weaver 10/13 T1 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=6 Gold=7 Tier=2

  Board (3/7): 6/6 [G], 4/3, 2/4
  Tavern (5 items): Sewer Rat 3/2 T2 $3 | Lava Lurker 2/5 T2 $3 | Shell Collector 4/3 T2 $3 | Manasaber 4/1 T1 $3 | Sleepy Supporter 4/3 T2 $3
  Hand: 1 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=4 Gold=7 Tier=2

  Board (5/7): 4/1, 1/2 [Taunt,DS], 3/6, 3/4, 5/2
  Tavern (4 items): Surf n' Surf 1/1 T1 $3 | Laboratory Assistant 3/4 T2 $3 | Eternal Knight 5/2 T2 $3 | Surf n' Surf 1/1 T1 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=8 Gold=7 Tier=2

  Board (5/7): 4/1, 2/1, 1/2 [Taunt,DS], 3/4, 2/4
  Tavern (4 items): Metallic Hunter 4/2 T2 $3 | Reef Riffer 3/2 T2 $3 | Reef Riffer 3/2 T2 $3 | Ancestral Automaton 3/4 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=6 Gold=7 Tier=2

  Board (5/7): 2/1 [Taunt,Reborn], 1/4, 2/1, 4/2, 4/2
  Tavern (4 items): Surf n' Surf 1/1 T1 $3 | Reef Riffer 3/2 T2 $3 | Cord Puller 1/1 T1 $3 | Sewer Rat 3/2 T2 $3
  Hand: 2 cards

  → Tier 2→3 | Gold 7→0 | Hand 2→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=7 Gold=7 Tier=2

  Board (5/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 2/1, 3/4, 5/2
  Tavern (4 items): Harmless Bonehead 1/1 T1 $3 | Old Soul 3/4 T2 $3 | Tide Raiser 2/1 T2 $3 | Lava Lurker 2/5 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Combat Phase**

  [heur] Ysera vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Ysera: [6/6, 4/3, 2/4]
     Sylvanas Windrunner: [2/1, 1/4, 2/1, 4/2, 4/2]
     Risen Rider 2/1→2/0 DEAD  |  Blazing Skyfin 2/4→2/2
     Scarlet Survivor 6/6→6/2  |  Metallic Hunter 4/2→4/0 DEAD
     Wrath Weaver 1/4→1/2  |  Blazing Skyfin 2/2→2/1
     Shell Collector 4/3→4/2  |  Wrath Weaver 1/2→1/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Scarlet Survivor 6/2→6/0 DEAD
     Blazing Skyfin 2/1→2/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Inge, the Iron Hymn vs [heur] Professor Putricide (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 3/6, 3/4, 5/2]
     Professor Putricide: [4/1, 2/1, 1/2, 3/4, 2/4]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Nerubian Deathswarmer 2/4→2/3
     Ominous Seer 2/1→2/0 DEAD  |  Eternal Knight 5/2→6/0 DEAD
     Wrath Weaver 3/6→3/3  |  Laboratory Assistant 3/4→3/1
     Laboratory Assistant 3/1→3/0 DEAD  |  Laboratory Assistant 3/4→3/1
     Laboratory Assistant 3/1→3/0 DEAD  |  Nerubian Deathswarmer 2/3→2/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Sneed vs [heur] Overlord Saurfang (first: Sneed)
     Sneed: [2/1, 3/6, 1/4, 2/4, 2/1]
     Overlord Saurfang: [6/6, 5/8, 6/5, 10/7, 7/8]
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 7/8→7/8
     Wrath Weaver 6/6→6/4  |  Nerubian Deathswarmer 2/4→2/0 DEAD
     Wrath Weaver 3/6→3/0 DEAD  |  Risen Rider 6/5→6/2
     Wrath Weaver 5/8→5/6  |  Ominous Seer 2/1→2/0 DEAD
     Wrath Weaver 1/4→1/0 DEAD  |  Risen Rider 6/2→6/1
     Result: 0 vs 5 — heur
  [heur] Drek'Thar vs [AGENT] Yogg-Saron, Hope's End (first: Drek'Thar)
     Drek'Thar: [2/1, 1/2, 2/1, 3/4, 5/2]
     Yogg-Saron, Hope's End: [3/4]
     Risen Rider 2/1→2/0 DEAD  |  Laboratory Assistant 3/4→3/2
     Laboratory Assistant 3/2→3/1  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Laboratory Assistant 3/1→3/0 DEAD
     Result: 3 vs 0 — heur

  Alive: 8/8
  HP: Sneed (HP=30, Tier=3) | Overlord Saurfang (HP=30, Tier=3) | Ysera (HP=30, Tier=3) | Inge, the Iron Hymn (HP=30, Tier=3) | Professor Putricide (HP=30, Tier=3) | Sylvanas Windrunner (HP=30, Tier=3) | Drek'Thar (HP=30, Tier=3) | Yogg-Saron, Hope's End (HP=23, Tier=2)

### Turn 6

**Yogg-Saron, Hope's End** [RL AGENT]  HP=23 Armor=0 Gold=8 Tier=2

  Board (1/7): 3/4
  Tavern (5 items): Cord Puller 1/1 T1 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Alert Alarmist 2/2 T2 $3 | Pointy Arrow (spell) T1 $1
  Hand: 0 cards

  → Board (2/7): 3/4, 4/1
  → Gold 8→3 | Armor 0→4 | Trinket: Shadowy Elixir | Hand 0→1
  → Actions: buy_tavern_4, refresh, buy_tavern_3, play_hand_1

**Sneed** [Heuristic]  HP=30 Armor=0 Gold=8 Tier=3

  Board (5/7): 2/1, 3/6, 1/4, 2/4, 2/1
  Tavern (5 items): Harmless Bonehead 2/1 T1 $3 | Eternal Knight 4/2 T2 $3 | Old Soul 4/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Mounting Avalanche (spell) T3 $2
  Hand: 0 cards

  → Board (7/7): 2/1, 3/6, 1/4, 2/4, 2/1, 4/4, 4/2
  → Gold 8→0 | Trinket: Impulsive Portrait
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=8 Tier=3

  Board (5/7): 6/6, 5/8, 6/5 [Taunt,Reborn], 10/7, 7/8 [Taunt,DS]
  Tavern (5 items): Cord Puller 11/11 T1 $3 | Lava Lurker 12/15 T2 $3 | Dustbone Devastator 12/16 T3 $3 | Sly Raptor 11/13 T3 $3 | Healthy Bounty (spell) T3 $2
  Hand: 0 cards

  → Board (7/7): 6/6, 5/8, 6/5 [Taunt,Reborn], 10/7, 7/8 [Taunt,DS], 12/16, 12/15
  → Gold 8→0 | Trinket: Implicator Portrait | Hand 0→2
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=6 Gold=8 Tier=3

  Board (3/7): 6/6 [G], 4/3, 2/4
  Tavern (5 items): Ancestral Automaton 3/4 T2 $3 | Sly Raptor 1/3 T3 $3 | Hardy Orca 1/6 T3 $3 | Mummifier 5/2 T3 $3 | Twilight Hatchling 1/1 T1 $3
  Hand: 1 cards

  → Board (5/7): 6/6 [G], 4/3, 2/4, 3/4, 1/6 [Taunt]
  → Gold 8→0 | Trinket: Smuggler Portrait
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=4 Gold=8 Tier=3

  Board (5/7): 4/1, 1/2 [Taunt,DS], 3/6, 3/4, 6/2
  Tavern (4 items): Handless Forsaken 2/1 T3 $3 | Dustbone Devastator 2/6 T3 $3 | Reef Riffer 3/2 T2 $3 | Tide Raiser 2/1 T2 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 1/2 [Taunt,DS], 3/6, 3/4, 6/2, 2/6, 3/2
  → Gold 8→0 | Trinket: Implicator Portrait | Hand 0→2
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=4 Gold=8 Tier=3

  Board (5/7): 4/1, 2/1, 1/2 [Taunt], 3/4, 2/4
  Tavern (4 items): Annoy-o-Tron 1/2 T1 $3 | Sly Raptor 1/3 T3 $3 | Picky Eater 1/1 T1 $3 | Cadaver Caretaker 4/3 T3 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 2/1, 1/2 [Taunt], 3/4, 2/4, 4/3, 1/3
  → Gold 8→0 | Trinket: Impulsive Portrait
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=1 Gold=8 Tier=3

  Board (5/7): 2/1 [Taunt,Reborn], 1/4, 2/1, 4/2, 4/2
  Tavern (4 items): Technical Element 5/6 T3 $3 | Humming Bird 1/4 T2 $3 | Deep-Sea Angler 2/3 T3 $3 | Sly Raptor 1/3 T3 $3
  Hand: 3 cards

  → Board (7/7): 1/4, 2/1, 4/2, 4/2, 5/6, 1/4, 2/3
  → Gold 8→0 | Trinket: Stormcoil Sticker | Hand 3→1
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=7 Gold=8 Tier=3

  Board (5/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 2/1, 3/4, 5/2
  Tavern (4 items): Shell Collector 4/3 T2 $3 | False Implicator 1/1 T3 $3 | Floating Watcher 4/4 T3 $5 | Ancestral Automaton 3/4 T2 $3
  Hand: 0 cards

  → Board (6/7): 5/1 [Taunt,Reborn], 1/2 [Taunt,DS], 2/1, 6/4, 5/2, 4/4
  → Gold 8→0 | Trinket: Artisanal Urn
  → Actions: (auto)

**Combat Phase**

  [heur] Professor Putricide vs [heur] Overlord Saurfang (first: Professor Putricide)
     Professor Putricide: [4/1, 2/1, 1/2, 3/4, 2/4, 4/3, 1/3]
     Overlord Saurfang: [6/6, 5/8, 6/5, 10/7, 7/8, 12/16, 12/15]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 7/8→7/8
     Wrath Weaver 6/6→6/5  |  Annoy-o-Tron 1/2→1/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 7/8→7/6
     Wrath Weaver 5/8→5/6  |  Nerubian Deathswarmer 2/4→2/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Risen Rider 6/5→6/2
     Risen Rider 6/2→6/0 DEAD  |  Cadaver Caretaker 4/3→4/0 DEAD
     Sly Raptor 1/3→1/0 DEAD  |  Annoy-o-Tron 7/6→7/5
     Result: 0 vs 6 — heur
  [heur] Sylvanas Windrunner vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Sylvanas Windrunner: [1/4, 2/1, 4/2, 4/2, 5/6, 2/4, 2/3]
     Inge, the Iron Hymn: [4/1, 1/2, 3/6, 3/4, 6/2, 2/6, 3/2]
     Manasaber 4/1→4/0 DEAD  |  Ominous Seer 2/1→2/0 DEAD
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Deep-Sea Angler 2/3→2/2
     Metallic Hunter 4/2→4/0 DEAD  |  Reef Riffer 3/2→3/0 DEAD
     Wrath Weaver 3/6→3/4  |  Humming Bird 2/4→2/1
     Metallic Hunter 4/2→4/0 DEAD  |  Wrath Weaver 3/4→3/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Technical Element 5/6→5/3
     Technical Element 5/3→5/0 DEAD  |  Eternal Knight 6/2→7/0 DEAD
     Dustbone Devastator 2/6→3/4  |  Humming Bird 2/1→2/0 DEAD
     Deep-Sea Angler 2/2→2/0 DEAD  |  Dustbone Devastator 3/4→3/2
     Result: 1 vs 1 — heur
  [heur] Drek'Thar vs [heur] Ysera (first: Drek'Thar)
     Drek'Thar: [5/1, 1/2, 2/1, 6/4, 5/2, 4/4]
     Ysera: [6/6, 4/3, 2/1, 3/4, 1/6]
     Risen Rider 5/1→5/0 DEAD  |  Hardy Orca 1/6→1/1
     Scarlet Survivor 6/6→6/5  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Hardy Orca 1/1→1/0 DEAD
     Shell Collector 4/3→4/2  |  Annoy-o-Tron 1/1→1/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Ancestral Automaton 3/4→3/2
     Blazing Skyfin 2/1→2/0 DEAD  |  Old Soul 6/4→6/2
     Old Soul 6/2→6/0 DEAD  |  Ancestral Automaton 3/2→3/0 DEAD
     Result: 2 vs 2 — heur
  [heur] Sneed vs [AGENT] Yogg-Saron, Hope's End (first: Sneed)
     Sneed: [2/1, 3/6, 1/4, 2/1, 2/1, 4/4, 4/2]
     Yogg-Saron, Hope's End: [3/4, 4/1]
     Ominous Seer 2/1→2/0 DEAD  |  Soul Rewinder 4/1→4/0 DEAD
     Laboratory Assistant 3/4→3/2  |  Ominous Seer 2/1→2/0 DEAD
     Wrath Weaver 3/6→3/3  |  Laboratory Assistant 3/2→3/0 DEAD
     Result: 5 vs 0 — heur

  Alive: 8/8
  HP: Sneed (HP=30, Tier=3) | Overlord Saurfang (HP=30, Tier=3) | Ysera (HP=30, Tier=3) | Inge, the Iron Hymn (HP=30, Tier=3) | Sylvanas Windrunner (HP=30, Tier=3) | Drek'Thar (HP=30, Tier=3) | Professor Putricide (HP=24, Tier=3) | Yogg-Saron, Hope's End (HP=17, Tier=2)

### Turn 7

**Yogg-Saron, Hope's End** [RL AGENT]  HP=17 Armor=0 Gold=9 Tier=2

  Board (2/7): 3/4, 4/1
  Tavern (4 items): Scarlet Skull 2/1 T2 $3 | Alert Alarmist 2/2 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3
  Hand: 1 cards

  → Tier 2→3 | Gold 9→6
  → Actions: upgrade

**Sneed** [Heuristic]  HP=30 Armor=0 Gold=9 Tier=3

  Board (7/7): 2/1, 3/6, 1/4, 2/1, 2/1, 4/4, 4/2
  Tavern (4 items): Cadaver Caretaker 4/3 T3 $3 | Shell Collector 4/3 T2 $3 | False Implicator 1/1 T3 $3 | Laboratory Assistant 3/4 T2 $3
  Hand: 0 cards

  → Board (7/7): 3/6, 1/4, 2/1, 2/1, 4/4, 4/2, 4/3
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=9 Tier=3

  Board (7/7): 6/6, 5/8, 6/5 [Taunt,Reborn], 10/7, 7/8 [Taunt,DS], 12/16, 12/15
  Tavern (4 items): False Implicator 14/14 T3 $3 | Leeching Felhound 16/16 T3 $3 | Handless Forsaken 15/14 T3 $3 | Deflect-o-Bot 16/15 T3 $3
  Hand: 2 cards

  → Board (7/7): 7/10, 10/7, 12/16, 12/15, 16/16, 16/15 [DS], 15/14
  → Tier 3→4 | Gold 9→0 | Armor 15→10
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=6 Gold=9 Tier=3

  Board (5/7): 6/6 [G], 4/3, 2/1, 3/4, 1/6 [Taunt]
  Tavern (5 items): Lava Lurker 2/5 T2 $3 | Soul Rewinder 4/1 T2 $3 | Soul Rewinder 4/1 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Blazing Skyfin 2/4 T2 $3
  Hand: 1 cards

  → Board (6/7): 6/6 [G], 4/3, 2/1, 3/4, 1/6 [Taunt], 2/5
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=4 Gold=9 Tier=3

  Board (7/7): 4/1, 1/2 [Taunt,DS], 3/6, 3/4, 7/2, 3/6, 3/2
  Tavern (4 items): Reef Riffer 3/2 T2 $3 | Tide Raiser 2/1 T2 $3 | Shell Collector 12/9 T2 $3 | Mummifier 21/21 T3 $3
  Hand: 3 cards

  → Board (7/7): 4/1, 7/10, 3/4, 7/2, 3/6, 3/2, 21/21
  → Tier 3→4 | Gold 9→0 | Hand 3→2
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=24 Armor=0 Gold=9 Tier=3

  Board (7/7): 4/1, 2/1, 1/2 [Taunt], 3/4, 2/4, 4/3, 1/3
  Tavern (4 items): Mummifier 6/2 T3 $3 | Sly Raptor 1/3 T3 $3 | Hardy Orca 1/6 T3 $3 | Cadaver Caretaker 4/3 T3 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 1/2 [Taunt], 3/4, 2/4, 4/3, 1/3, 6/2
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=1 Gold=9 Tier=3

  Board (7/7): 1/4, 2/1, 4/2, 4/2, 5/6, 1/4, 2/3
  Tavern (4 items): Shell Collector 4/3 T2 $3 | Tide Raiser 2/1 T2 $3 | Cadaver Caretaker 3/3 T3 $3 | Sprightly Scarab 3/1 T3 $3
  Hand: 5 cards

  → Board (7/7): 3/6 [Taunt], 4/2, 4/2, 5/6, 1/4, 2/3, 4/3
  → Tier 3→4 | Gold 9→0 | Hand 5→2
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=7 Gold=9 Tier=3

  Board (6/7): 5/1 [Taunt,Reborn], 1/2 [Taunt,DS], 2/1, 6/4, 5/2, 4/4
  Tavern (4 items): Manasaber 4/1 T1 $3 | Sprightly Scarab 3/1 T3 $3 | Annoy-o-Module 2/4 T3 $3 | Risen Rider 5/1 T1 $3
  Hand: 0 cards

  → Board (7/7): 5/1 [Taunt,Reborn], 1/2 [Taunt,DS], 2/1, 6/4, 5/2, 4/4, 5/1 [Taunt,Reborn]
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Combat Phase**

  [AGENT] Yogg-Saron, Hope's End vs [heur] Professor Putricide (first: Professor Putricide)
     Yogg-Saron, Hope's End: [3/4, 4/1]
     Professor Putricide: [1/2, 3/4, 2/4, 4/3, 1/3, 6/2, 0/1]
     Annoy-o-Tron 1/2→1/0 DEAD  |  Soul Rewinder 4/1→4/0 DEAD
     Laboratory Assistant 3/4→3/4  |  Cubling 0/1→0/0 DEAD
     Laboratory Assistant 3/4→3/1  |  Laboratory Assistant 3/4→3/1
     Result: 1 vs 5 — AGENT
  [heur] Drek'Thar vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Drek'Thar: [5/1, 1/2, 2/1, 6/4, 5/2, 4/4, 5/1]
     Sylvanas Windrunner: [3/6, 4/2, 4/2, 5/6, 2/4, 2/3, 4/3]
     Wrath Weaver 3/6→3/1  |  Risen Rider 5/1→5/0 DEAD
     Annoy-o-Tron 1/2→1/2  |  Wrath Weaver 3/1→3/0 DEAD
     Metallic Hunter 4/2→4/1  |  Annoy-o-Tron 1/2→1/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Shell Collector 4/3→4/1
     Metallic Hunter 4/2→4/0 DEAD  |  Risen Rider 5/1→5/0 DEAD
     Old Soul 6/4→6/2  |  Humming Bird 2/4→2/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Old Soul 6/2→6/0 DEAD
     Eternal Knight 5/2→6/0 DEAD  |  Shell Collector 4/1→4/0 DEAD
     Deep-Sea Angler 2/3→2/0 DEAD  |  Floating Watcher 4/4→4/2
     Floating Watcher 4/2→4/0 DEAD  |  Metallic Hunter 4/1→4/0 DEAD
     Result: 0 vs 0 — draw
  [heur] Sneed vs [heur] Ysera (first: Sneed)
     Sneed: [3/6, 1/4, 2/1, 2/1, 4/4, 4/2, 4/3]
     Ysera: [6/6, 4/3, 2/1, 3/4, 1/6, 2/5]
     Wrath Weaver 3/6→3/5  |  Hardy Orca 1/6→1/3
     Scarlet Survivor 6/6→6/5  |  Wrath Weaver 1/4→1/0 DEAD
     Nerubian Deathswarmer 2/1→2/0 DEAD  |  Hardy Orca 1/3→1/1
     Shell Collector 4/3→4/0 DEAD  |  Wrath Weaver 3/5→3/1
     Ominous Seer 2/1→2/0 DEAD  |  Hardy Orca 1/1→1/0 DEAD
     Blazing Skyfin 2/1→2/0 DEAD  |  Old Soul 4/4→4/2
     Old Soul 4/2→4/0 DEAD  |  Scarlet Survivor 6/5→6/1
     Ancestral Automaton 3/4→3/0 DEAD  |  Eternal Knight 4/2→5/0 DEAD
     Cadaver Caretaker 4/3→4/0 DEAD  |  Scarlet Survivor 6/1→6/0 DEAD
     Lava Lurker 2/5→2/2  |  Wrath Weaver 3/1→3/0 DEAD
     Result: 0 vs 1 — heur
  [heur] Overlord Saurfang vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Overlord Saurfang: [7/10, 10/7, 12/13, 12/15, 16/16, 16/15, 15/14]
     Inge, the Iron Hymn: [4/1, 7/10, 3/4, 7/2, 3/6, 3/2, 21/21]
     Manasaber 4/1→4/0 DEAD  |  Deflect-o-Bot 16/15→16/15
     Wrath Weaver 7/10→7/3  |  Eternal Knight 7/2→8/0 DEAD
     Wrath Weaver 7/10→7/0 DEAD  |  Handless Forsaken 15/14→15/7
     Soul Rewinder 10/7→10/4  |  Reef Riffer 3/2→3/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Soul Rewinder 10/4→10/1
     Dustbone Devastator 12/13→13/10  |  Dustbone Devastator 3/6→3/0 DEAD
     Mummifier 21/21→21/5  |  Handless Forsaken 16/7→16/0 DEAD
     Lava Lurker 12/15→12/0 DEAD  |  Mummifier 21/5→21/0 DEAD
     Result: 5 vs 0 — heur

  Alive: 8/8
  HP: Overlord Saurfang (HP=30, Tier=4) | Ysera (HP=30, Tier=4) | Sylvanas Windrunner (HP=30, Tier=4) | Drek'Thar (HP=30, Tier=4) | Sneed (HP=24, Tier=4) | Inge, the Iron Hymn (HP=24, Tier=4) | Professor Putricide (HP=24, Tier=4) | Yogg-Saron, Hope's End (HP=17, Tier=3)

### Turn 8

**Yogg-Saron, Hope's End** [RL AGENT]  HP=17 Armor=0 Gold=10 Tier=3

  Board (2/7): 3/4, 4/1
  Tavern (5 items): Leeching Felhound 3/3 T3 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Ominous Seer 2/1 T1 $3 | Sprightly Scarab 3/1 T3 $3 | Tavern Coin (spell) T1 $3
  Hand: 1 cards

  → Actions: 

**Sneed** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=4

  Board (7/7): 3/6, 1/4, 2/1, 2/1, 4/4, 5/2, 4/3
  Tavern (6 items): Prosthetic Hand 3/1 T4 $3 | Friendly Geist 7/3 T4 $3 | Old Soul 4/4 T2 $3 | Shell Collector 4/3 T2 $3 | Rylak Metalhead 5/3 T4 $3 | Natural Blessing (spell) T4 $4
  Hand: 0 cards

  → Board (7/7): 3/6, 4/4, 4/3, 7/3, 4/4, 5/3 [Taunt], 3/1 [Reborn]
  → Gold 10→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=10 Gold=10 Tier=4

  Board (7/7): 7/10, 10/7, 13/13, 12/15, 16/16, 16/15 [DS], 16/14
  Tavern (6 items): Seafloor Recruiter 19/21 T4 $3 | Trigore the Lasher 25/19 T4 $3 | Ancestral Automaton 3/4 T2 $3 | Eternal Knight 4/2 T2 $3 | Auto Assembler 18/18 T4 $3 | Shifting Tide (spell) T4 $1
  Hand: 2 cards

  → Board (7/7): 16/16, 16/15 [DS], 16/14, 25/19, 19/21, 18/18, 4/2
  → Gold 10→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=6 Gold=10 Tier=4

  Board (6/7): 6/6 [G], 4/3, 2/1, 3/4, 1/6 [Taunt], 2/5
  Tavern (7 items): Leeching Felhound 3/3 T3 $3 | Woodland Defiler 5/6 T4 $3 | Auto Assembler 2/2 T4 $3 | Banana Slamma 3/6 T4 $3 | Plaguerunner 4/2 T4 $3 | Pointy Arrow (spell) T1 $1 | Twilight Hatchling 1/1 T1 $3
  Hand: 1 cards

  → Board (7/7): 6/6 [G], 3/4, 1/6 [Taunt], 2/5, 5/6, 3/6, 1/1
  → Gold 10→0 | Armor 6→3
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/1, 7/10, 3/4, 8/2, 3/6, 3/2, 21/21
  Tavern (6 items): Deep Blue Crooner 5/5 T3 $3 | Zesty Shaker 10/10 T4 $3 | Hardy Orca 12/20 T3 $3 | Marquee Ticker 26/29 T4 $3 | Mummifier 24/24 T3 $3 | Angler's Lure (spell) T1 $3
  Hand: 3 cards

  → Board (7/7): 7/10, 21/21, 26/29, 31/30, 12/20 [Taunt], 17/17, 13/11
  → Gold 10→0 | Hand 3→2
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=4

  Board (7/7): 1/2 [Taunt], 3/4, 2/4, 4/3, 1/3, 6/2, 0/1 [Taunt]
  Tavern (6 items): Zesty Shaker 6/7 T4 $3 | Marquee Ticker 3/7 T4 $3 | Accord-o-Tron 3/3 T3 $3 | Manasaber 4/1 T1 $3 | Enchanted Sentinel 3/5 T4 $3 | Forest's Bounty (spell) T4 $3
  Hand: 0 cards

  → Board (7/7): 2/4, 4/3, 6/2, 6/7, 3/7, 3/5, 4/1
  → Gold 10→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=1 Gold=10 Tier=4

  Board (7/7): 3/6 [Taunt], 4/2, 4/2, 5/6, 1/4, 2/3, 4/3
  Tavern (6 items): Woodland Defiler 5/6 T4 $3 | Waverider 2/8 T4 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Annoy-o-Module 2/4 T3 $3 | Sprightly Scarab 3/1 T3 $3 | Gem Confiscation (spell) T4 $1
  Hand: 5 cards

  → Board (7/7): 5/8 [Taunt], 7/8 [Taunt], 4/3, 5/6, 2/8, 2/4, 5/1 [WF]
  → Gold 10→0 | Armor 1→0 | Hand 5→2
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=7 Gold=10 Tier=4

  Board (7/7): 5/1 [Taunt,Reborn], 1/2 [Taunt,DS], 2/1, 6/4, 6/2, 4/4, 5/1 [Taunt,Reborn]
  Tavern (6 items): Stomping Stegodon 4/4 T4 $3 | Humming Bird 1/4 T2 $3 | Annoy-o-Module 2/4 T3 $3 | Metallic Hunter 4/2 T2 $3 | Flaming Enforcer 4/5 T4 $3 | Easterly Winds (spell) T4 $1
  Hand: 0 cards

  → Board (7/7): 5/1 [Taunt,Reborn], 6/4, 6/2, 5/1 [Taunt,Reborn], 4/5, 4/4, 1/4
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [AGENT] Yogg-Saron, Hope's End vs [heur] Drek'Thar (first: Drek'Thar)
     Yogg-Saron, Hope's End: [3/4, 4/1]
     Drek'Thar: [5/1, 6/4, 6/2, 5/1, 4/5, 5/4, 2/4]
     Risen Rider 5/1→5/0 DEAD  |  Soul Rewinder 4/1→4/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Risen Rider 5/1→5/0 DEAD
     Result: 0 vs 5 — heur
  [heur] Professor Putricide vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Professor Putricide: [2/4, 4/3, 6/2, 6/4, 3/7, 3/5, 4/1]
     Sylvanas Windrunner: [5/8, 7/8, 4/3, 5/6, 2/8, 2/4, 5/1]
     Wrath Weaver 5/8→5/5  |  Enchanted Sentinel 3/5→3/0 DEAD
     Nerubian Deathswarmer 2/4→2/0 DEAD  |  Technical Element 7/8→7/6
     Technical Element 7/6→7/0 DEAD  |  Zesty Shaker 6/4→6/0 DEAD
     Cadaver Caretaker 4/3→4/0 DEAD  |  Wrath Weaver 5/5→5/1
     Shell Collector 4/3→4/0 DEAD  |  Marquee Ticker 3/7→3/3
     Mummifier 6/2→6/0 DEAD  |  Wrath Weaver 5/1→5/0 DEAD
     Woodland Defiler 5/6→5/3  |  Marquee Ticker 3/3→3/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Woodland Defiler 5/3→5/0 DEAD
     Result: 0 vs 3 — heur
  [heur] Overlord Saurfang vs [heur] Ysera (first: Overlord Saurfang)
     Overlord Saurfang: [16/16, 16/15, 16/14, 25/16, 19/21, 18/18, 4/2]
     Ysera: [6/6, 3/4, 1/6, 2/5, 5/6, 3/6, 1/1]
     Leeching Felhound 16/16→16/15  |  Hardy Orca 1/6→1/0 DEAD
     Scarlet Survivor 6/6→6/0 DEAD  |  Leeching Felhound 16/15→16/9
     Deflect-o-Bot 16/15→16/15  |  Twilight Hatchling 1/1→1/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Auto Assembler 18/18→18/15
     Handless Forsaken 16/14→16/12  |  Lava Lurker 2/5→2/0 DEAD
     Woodland Defiler 5/6→5/0 DEAD  |  Deflect-o-Bot 16/15→16/10
     Trigore the Lasher 25/16→25/13  |  Banana Slamma 3/6→3/0 DEAD
     Result: 6 vs 0 — heur
  [heur] Sneed vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Sneed: [3/6, 4/4, 4/3, 7/3, 4/4, 5/3, 3/1]
     Inge, the Iron Hymn: [7/10, 21/21, 26/29, 31/30, 12/20, 17/17, 13/11]
     Wrath Weaver 7/10→7/5  |  Rylak Metalhead 5/3→5/0 DEAD
     Wrath Weaver 3/6→3/0 DEAD  |  Hardy Orca 12/20→12/17
     Mummifier 21/21→21/17  |  Old Soul 4/4→4/0 DEAD
     Cadaver Caretaker 4/3→4/0 DEAD  |  Hardy Orca 12/17→12/13
     Marquee Ticker 26/29→26/25  |  Old Soul 4/4→4/0 DEAD
     Friendly Geist 7/3→7/0 DEAD  |  Hardy Orca 12/13→12/6
     Mummifier 31/30→31/27  |  Prosthetic Hand 3/1→3/0 DEAD
     Result: 0 vs 7 — heur

  Alive: 8/8
  HP: Overlord Saurfang (HP=30, Tier=4) | Sylvanas Windrunner (HP=30, Tier=4) | Drek'Thar (HP=30, Tier=4) | Inge, the Iron Hymn (HP=24, Tier=4) | Ysera (HP=18, Tier=4) | Professor Putricide (HP=11, Tier=4) | Sneed (HP=9, Tier=4) | Yogg-Saron, Hope's End (HP=2, Tier=3)

### Turn 9

**Yogg-Saron, Hope's End** [RL AGENT]  HP=2 Armor=0 Gold=10 Tier=3

  Board (2/7): 3/4, 4/1
  Tavern (5 items): Deep-Sea Angler 2/3 T3 $3 | Shell Collector 4/3 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Angler's Lure (spell) T1 $3
  Hand: 1 cards

  → Tier 3→4 | Gold 10→0 | Trinket: Mecha-Jaraxxus Sticker
  → Actions: upgrade, refresh

**Sneed** [Heuristic]  HP=9 Armor=0 Gold=10 Tier=4

  Board (7/7): 3/6, 4/4, 4/3, 7/3, 4/4, 5/3 [Taunt], 3/1 [Reborn]
  Tavern (6 items): Rylak Metalhead 5/3 T4 $3 | Imposing Percussionist 4/4 T4 $3 | Hunting Tiger Shark 3/5 T4 $3 | Banana Slamma 3/6 T4 $3 | Alert Alarmist 2/2 T2 $3 | Boon of Beetles (spell) T4 $1
  Hand: 0 cards

  → Board (7/7): 3/6, 14/4, 14/3, 17/3, 14/4, 5/3 [Taunt], 3/6
  → Tier 4→5 | Gold 10→0 | Trinket: Artisanal Urn
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=10 Gold=10 Tier=4

  Board (7/7): 16/16, 16/15 [DS], 16/14, 25/17, 19/21, 18/18, 5/2
  Tavern (6 items): Deep Blue Crooner 27/27 T3 $3 | Hardy Orca 26/31 T3 $3 | Prosthetic Hand 28/26 T4 $3 | Hardy Orca 26/31 T3 $3 | Deep-Sea Angler 27/28 T3 $3 | Arcane Absorption (spell) T4 $1
  Hand: 2 cards

  → Board (7/7): 16/16, 16/15 [DS], 16/14, 25/17, 19/21, 18/18, 26/31 [Taunt]
  → Tier 4→5 | Gold 10→0 | Trinket: Drakkari Portrait | Hand 2→3
  → Actions: (auto)

**Ysera** [Heuristic]  HP=18 Armor=0 Gold=10 Tier=4

  Board (7/7): 6/6 [G], 3/4, 1/6 [Taunt], 2/5, 5/6, 3/6, 1/1
  Tavern (7 items): Handless Forsaken 2/1 T3 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Banana Slamma 3/6 T4 $3 | Annoy-o-Tron 1/2 T1 $3 | Banana Slamma 3/6 T4 $3 | Tavern Coin (spell) T1 $3 | Sleepy Supporter 4/3 T2 $3
  Hand: 1 cards

  → Tier 4→5 | Gold 10→0 | Trinket: Wildfeather Duster
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=4

  Board (7/7): 7/10, 21/21, 26/29, 31/30, 12/20 [Taunt], 17/17, 13/11
  Tavern (6 items): Laboratory Assistant 3/4 T2 $3 | Metallic Hunter 4/2 T2 $3 | Marquee Ticker 8/10 T4 $3 | Shell Collector 4/3 T2 $3 | Humming Bird 4/5 T2 $3 | Pointy Arrow (spell) T1 $1
  Hand: 2 cards

  → Board (7/7): 31/21, 26/29, 41/30, 12/20 [Taunt], 17/17, 13/11, 11/13
  → Tier 4→5 | Gold 10→0 | Trinket: Artisanal Urn
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=11 Armor=0 Gold=10 Tier=4

  Board (7/7): 2/4, 4/3, 6/2, 6/4, 3/7, 3/5, 4/1
  Tavern (6 items): Metallic Hunter 4/2 T2 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Shell Collector 4/3 T2 $3 | Humming Bird 1/4 T2 $3 | Picky Eater 1/1 T1 $3 | Deepwater Clan (spell) T4 $2
  Hand: 1 cards

  → Board (7/7): 12/4, 14/3, 16/2, 6/4, 3/7, 3/5, 5/4
  → Tier 4→5 | Gold 10→2 | Trinket: Artisanal Urn | Hand 1→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=0 Gold=10 Tier=4

  Board (7/7): 5/8 [Taunt], 7/8 [Taunt], 4/3, 5/6, 2/8, 2/4, 5/1 [WF]
  Tavern (6 items): Floating Watcher 4/4 T3 $5 | Rimescale Priestess 3/3 T4 $3 | Trigore the Lasher 9/3 T4 $3 | Deflect-o-Bot 3/2 T3 $3 | Handless Forsaken 3/1 T3 $3 | Sick Riffs (spell) T1 $3
  Hand: 3 cards

  → Board (7/7): 7/10 [Taunt], 7/8 [Taunt], 4/3, 5/6, 2/8, 2/4, 9/3
  → Tier 4→5 | Gold 10→0 | Trinket: Ur'zul Sticker | Hand 3→2
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=7 Gold=10 Tier=4

  Board (7/7): 5/1 [Taunt,Reborn], 6/4, 6/2, 5/1 [Taunt,Reborn], 4/5, 4/4, 1/4
  Tavern (6 items): Handless Forsaken 5/1 T3 $3 | Stomping Stegodon 4/4 T4 $3 | Deep-Sea Angler 2/3 T3 $3 | Stomping Stegodon 4/4 T4 $3 | Abyssal Bruiser 1/1 T4 $3 | Temperature Shift (spell) T4 $4
  Hand: 0 cards

  → Tier 4→5 | Gold 10→0 | Trinket: Unholy Sanctum
  → Actions: (auto)

**Combat Phase**

  [heur] Sylvanas Windrunner vs [heur] Inge, the Iron Hymn (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [7/10, 7/8, 4/3, 5/6, 2/8, 2/4, 9/3]
     Inge, the Iron Hymn: [31/21, 26/29, 41/30, 12/20, 17/17, 13/11, 11/13]
     Wrath Weaver 7/10→7/0 DEAD  |  Hardy Orca 12/20→12/13
     Mummifier 31/21→31/14  |  Technical Element 7/8→7/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Hardy Orca 12/13→12/9
     Marquee Ticker 26/29→26/20  |  Trigore the Lasher 9/3→9/0 DEAD
     Woodland Defiler 5/6→5/0 DEAD  |  Hardy Orca 12/9→12/4
     Mummifier 41/30→41/28  |  Nerubian Deathswarmer 2/4→2/0 DEAD
     Waverider 2/8→2/0 DEAD  |  Hardy Orca 12/4→12/2
     Result: 0 vs 7 — heur
  [heur] Sneed vs [heur] Professor Putricide (first: Professor Putricide)
     Sneed: [3/6, 14/4, 14/3, 17/3, 14/4, 5/3, 3/6]
     Professor Putricide: [12/4, 14/3, 16/2, 6/4, 3/7, 3/5, 5/4]
     Nerubian Deathswarmer 12/4→12/0 DEAD  |  Rylak Metalhead 5/3→5/0 DEAD
     Wrath Weaver 3/6→3/0 DEAD  |  Zesty Shaker 6/4→6/1
     Cadaver Caretaker 14/3→14/0 DEAD  |  Friendly Geist 17/3→17/0 DEAD
     Old Soul 14/4→14/1  |  Marquee Ticker 3/7→3/0 DEAD
     Mummifier 16/2→16/0 DEAD  |  Old Soul 14/1→14/0 DEAD
     Cadaver Caretaker 14/3→14/0 DEAD  |  Malchezaar, Prince of Dance 5/4→5/0 DEAD
     Zesty Shaker 6/1→6/0 DEAD  |  Old Soul 14/4→14/0 DEAD
     Banana Slamma 3/6→3/3  |  Enchanted Sentinel 3/5→3/2
     Enchanted Sentinel 3/2→3/0 DEAD  |  Banana Slamma 3/3→3/0 DEAD
     Result: 0 vs 0 — draw
  [heur] Overlord Saurfang vs [AGENT] Yogg-Saron, Hope's End (first: Overlord Saurfang)
     Overlord Saurfang: [16/16, 16/15, 16/14, 25/17, 19/21, 18/18, 26/31]
     Yogg-Saron, Hope's End: [3/4, 4/1]
     Leeching Felhound 16/16→16/13  |  Laboratory Assistant 3/4→3/0 DEAD
     Soul Rewinder 4/1→4/0 DEAD  |  Hardy Orca 26/31→26/27
     Result: 7 vs 0 — heur
  [heur] Ysera vs [heur] Drek'Thar (first: Drek'Thar)
     Ysera: [6/6, 3/4, 1/6, 2/5, 5/6, 3/6, 1/1]
     Drek'Thar: [5/1, 6/4, 6/2, 5/1, 8/11, 5/4, 2/4]
     Risen Rider 5/1→5/0 DEAD  |  Hardy Orca 1/6→1/1
     Scarlet Survivor 6/6→6/1  |  Risen Rider 5/1→5/0 DEAD
     Old Soul 6/4→6/3  |  Hardy Orca 1/1→1/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Eternal Knight 6/2→7/0 DEAD
     Flaming Enforcer 8/11→8/6  |  Woodland Defiler 5/6→5/0 DEAD
     Lava Lurker 2/5→2/0 DEAD  |  Flaming Enforcer 8/6→8/4
     Stomping Stegodon 5/4→5/1  |  Banana Slamma 3/6→3/1
     Banana Slamma 3/1→3/0 DEAD  |  Humming Bird 5/4→5/1
     Humming Bird 5/1→5/0 DEAD  |  Twilight Hatchling 1/1→1/0 DEAD
     Result: 1 vs 3 — heur

  **Yogg-Saron, Hope's End [AGENT] eliminated!** (Turn 9)
  Alive: 7/8
  HP: Overlord Saurfang (HP=30, Tier=5) | Drek'Thar (HP=30, Tier=5) | Inge, the Iron Hymn (HP=24, Tier=5) | Ysera (HP=18, Tier=5) | Sylvanas Windrunner (HP=15, Tier=5) | Professor Putricide (HP=11, Tier=5) | Sneed (HP=9, Tier=5)

### Turn 10

**Sneed** [Heuristic]  HP=9 Armor=0 Gold=10 Tier=5

  Board (7/7): 3/6, 14/4, 14/3, 17/3, 14/4, 5/3 [Taunt], 3/6
  Tavern (6 items): Skeletal Strafer 17/6 T5 $3 | Zesty Shaker 6/7 T4 $3 | Deep Blue Crooner 2/2 T3 $3 | Friendly Geist 17/3 T4 $3 | Ashen Corruptor 6/6 T5 $3 | Tavern Coin (spell) T1 $3
  Hand: 0 cards

  → Board (7/7): 14/4, 14/3, 17/3, 14/4, 17/6, 17/3, 2/2
  → Gold 10→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=10 Gold=10 Tier=5

  Board (7/7): 16/16, 16/15 [DS], 16/14, 25/18, 19/21, 18/18, 26/31 [Taunt]
  Tavern (6 items): Shadowdancer 31/29 T5 $3 | Prosthetic Hand 29/27 T4 $3 | Alert Alarmist 28/28 T2 $3 | Annoy-o-Module 28/30 T3 $3 | Laboratory Assistant 29/30 T2 $3 | Saloon's Finest (spell) T5 $2
  Hand: 3 cards

  → Board (7/7): 25/18, 26/31 [Taunt], 31/29 [Taunt], 29/30, 28/30 [Taunt,DS], 29/27 [Reborn], 28/28 [Taunt]
  → Gold 10→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=18 Armor=0 Gold=10 Tier=5

  Board (7/7): 6/6 [G], 3/4, 1/6 [Taunt], 2/5, 5/6, 3/6, 1/1
  Tavern (7 items): Metallic Hunter 4/2 T2 $3 | Accord-o-Tron 3/3 T3 $3 | Catacomb Crasher 4/10 T5 $3 | Marquee Ticker 3/7 T4 $3 | Darkcrest Strategist 4/5 T5 $3 | Wave of Gold (spell) T5 $2 | Amber Guardian 3/2 T3 $3
  Hand: 1 cards

  → Board (7/7): 6/6 [G], 5/6, 3/6, 4/10, 3/7, 4/5, 3/3
  → Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=5

  Board (7/7): 31/21, 26/29, 41/30, 12/20 [Taunt], 17/17, 13/11, 11/13
  Tavern (6 items): Bazaar Dealer 8/8 T5 $3 | Malchezaar, Prince of Dance 41/47 T4 $3 | Tichondrius 27/29 T5 $3 | Divine Sparkbot 31/32 T5 $3 | Sly Raptor 11/17 T3 $3 | Upper Hand (spell) T5 $3
  Hand: 3 cards

  → Board (7/7): 31/21, 41/30, 41/47, 40/40, 31/32 [Taunt,DS], 39/47, 34/37
  → Gold 10→0 | Hand 3→4
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=11 Armor=0 Gold=10 Tier=5

  Board (7/7): 12/4, 14/3, 16/2, 6/4, 3/7, 3/5, 5/4
  Tavern (6 items): Annoy-o-Module 2/4 T3 $3 | Lurking Leviathan 3/8 T5 $3 | Nightmare Par-tea Guest 14/3 T5 $3 | Leeching Felhound 3/3 T3 $3 | Reef Riffer 3/2 T2 $3 | Butchering (spell) T5 $2
  Hand: 1 cards

  → Board (7/7): 12/4, 14/3, 16/2, 3/7, 14/3, 3/8, 13/7
  → Gold 10→2 | HP 11→8
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=15 Armor=0 Gold=10 Tier=5

  Board (7/7): 7/10 [Taunt], 7/8 [Taunt], 4/3, 5/6, 2/8, 2/4, 9/4
  Tavern (6 items): Famished Felbat 6/3 T5 $3 | Plaguerunner 5/2 T4 $3 | Drustfallen Butcher 3/7 T5 $3 | Trigore the Lasher 9/3 T4 $3 | Risen Rider 3/1 T1 $3 | Armor Stash (spell) T5 $3
  Hand: 4 cards

  → Board (7/7): 14/15 [Taunt], 7/8 [Taunt], 5/6, 9/4, 9/3, 3/7, 4/3
  → Gold 10→0 | HP 15→14 | Hand 4→2
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=7 Gold=10 Tier=5

  Board (7/7): 5/1 [Taunt,Reborn], 6/4, 7/2, 5/1 [Taunt,Reborn], 8/11, 4/4, 1/4
  Tavern (6 items): Skeletal Strafer 9/6 T5 $3 | Darkcrest Strategist 4/5 T5 $3 | Accord-o-Tron 3/3 T3 $3 | Tichondrius 3/6 T5 $3 | Divine Sparkbot 4/2 T5 $3 | Brood of Nozdormu (spell) T5 $2
  Hand: 0 cards

  → Board (7/7): 6/4, 7/2, 8/11, 9/6, 4/5, 3/6, 4/2 [Taunt,DS]
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Drek'Thar vs [heur] Sneed (first: Sneed)
     Drek'Thar: [7/5, 7/3, 9/12, 10/7, 5/6, 4/7, 5/3]
     Sneed: [15/5, 15/4, 18/4, 15/5, 18/7, 18/4, 3/3]
     Old Soul 15/5→15/0 DEAD  |  Divine Sparkbot 5/3→5/3
     Old Soul 7/5→7/0 DEAD  |  Skeletal Strafer 18/7→18/0 DEAD
     Cadaver Caretaker 15/4→15/0 DEAD  |  Divine Sparkbot 5/3→5/0 DEAD
     Eternal Knight 7/3→8/0 DEAD  |  Old Soul 15/5→15/0 DEAD
     Friendly Geist 18/4→18/0 DEAD  |  Tichondrius 10/11→10/0 DEAD
     Flaming Enforcer 9/12→9/9  |  Deep Blue Crooner 3/3→3/0 DEAD
     Friendly Geist 18/4→18/0 DEAD  |  Skeletal Strafer 10/7→10/0 DEAD
     Result: 2 vs 0 — heur
  [heur] Ysera vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Ysera: [6/6, 5/6, 3/6, 4/10, 3/7, 4/5, 3/3]
     Sylvanas Windrunner: [14/15, 7/8, 5/6, 9/4, 9/3, 3/7, 4/3]
     Wrath Weaver 14/15→14/11  |  Darkcrest Strategist 4/5→4/0 DEAD
     Scarlet Survivor 6/6→6/0 DEAD  |  Wrath Weaver 14/11→14/5
     Technical Element 7/8→7/5  |  Marquee Ticker 3/7→3/0 DEAD
     Woodland Defiler 5/6→5/0 DEAD  |  Technical Element 7/5→7/0 DEAD
     Woodland Defiler 5/6→5/3  |  Accord-o-Tron 3/3→3/0 DEAD
     Banana Slamma 3/6→3/0 DEAD  |  Wrath Weaver 14/5→14/2
     Trigore the Lasher 9/4→9/0 DEAD  |  Catacomb Crasher 4/10→4/1
     Catacomb Crasher 4/1→4/0 DEAD  |  Wrath Weaver 14/2→14/0 DEAD
     Result: 0 vs 4 — heur
  [heur] Overlord Saurfang vs [heur] Professor Putricide (first: Professor Putricide)
     Overlord Saurfang: [25/18, 26/31, 31/29, 29/30, 28/30, 29/27, 28/28]
     Professor Putricide: [12/4, 14/3, 16/2, 3/7, 14/3, 3/8, 13/7]
     Nerubian Deathswarmer 12/4→12/0 DEAD  |  Annoy-o-Module 28/30→28/30
     Trigore the Lasher 25/18→25/5  |  Drustfallen Butcher 13/7→13/0 DEAD
     Cadaver Caretaker 14/3→14/0 DEAD  |  Alert Alarmist 28/28→28/14
     Hardy Orca 26/31→26/17  |  Nightmare Par-tea Guest 14/3→14/0 DEAD
     Mummifier 16/2→16/0 DEAD  |  Alert Alarmist 28/14→28/0 DEAD
     Shadowdancer 31/29→31/26  |  Marquee Ticker 3/7→3/0 DEAD
     Lurking Leviathan 3/8→3/0 DEAD  |  Shadowdancer 31/26→31/23
     Result: 6 vs 0 — heur

  **Sneed [Heuristic] eliminated!** (Turn 10)
  **Professor Putricide [Heuristic] eliminated!** (Turn 10)
  Alive: 5/8
  HP: Overlord Saurfang (HP=30, Tier=5) | Drek'Thar (HP=30, Tier=5) | Inge, the Iron Hymn (HP=24, Tier=5) | Sylvanas Windrunner (HP=14, Tier=5) | Ysera (HP=3, Tier=5)

### Turn 11

**Overlord Saurfang** [Heuristic]  HP=30 Armor=10 Gold=10 Tier=5

  Board (7/7): 25/20, 26/31 [Taunt], 31/29 [Taunt], 29/30, 28/30 [Taunt,DS], 29/27 [Reborn], 28/28 [Taunt]
  Tavern (6 items): Zesty Shaker 41/42 T4 $3 | Wyvern Outrider 37/43 T4 $3 | Maelstrom Emergent 37/42 T5 $3 | Seafloor Recruiter 38/40 T4 $3 | Maelstrom Emergent 37/42 T5 $3 | Staff of Enrichment (spell) T3 $2
  Hand: 3 cards

  → Board (7/7): 26/31 [Taunt], 31/29 [Taunt], 29/30, 28/30 [Taunt,DS], 29/27 [Reborn], 28/28 [Taunt], 41/42
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=3 Armor=0 Gold=11 Tier=5

  Board (7/7): 6/6 [G], 5/6, 3/6, 4/10, 3/7, 4/5, 3/3
  Tavern (7 items): Wrath Weaver 1/4 T1 $3 | Prosthetic Hand 3/1 T4 $3 | Trigore the Lasher 9/3 T4 $3 | Cord Puller 1/1 T1 $3 | Maelstrom Emergent 2/7 T5 $3 | Hired Headhunter (spell) T5 $3 | Twilight Hatchling 1/1 T1 $3
  Hand: 2 cards

  → Board (7/7): 6/6 [G], 5/6, 3/6, 4/10, 3/7, 4/5, 9/3
  → Tier 5→6 | Gold 11→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=5

  Board (7/7): 31/21, 41/30, 41/47, 40/40, 31/32 [Taunt,DS], 39/47, 34/37
  Tavern (6 items): Marquee Ticker 3/7 T4 $3 | Waverider 30/34 T4 $3 | Seafloor Recruiter 3/5 T4 $3 | Hardy Orca 1/6 T3 $3 | Floating Watcher 4/4 T3 $5 | Temperature Shift (spell) T4 $4
  Hand: 4 cards

  → Board (7/7): 41/30, 41/47, 40/40, 31/32 [Taunt,DS], 39/47, 34/37, 30/34
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=14 Armor=0 Gold=10 Tier=5

  Board (7/7): 14/15 [Taunt], 7/8 [Taunt], 5/6, 9/5, 9/4, 3/7, 4/3
  Tavern (6 items): Imposing Percussionist 4/4 T4 $3 | Leeching Felhound 3/3 T3 $3 | Soul Rewinder 4/1 T2 $3 | Eternal Knight 4/2 T2 $3 | Rimescale Priestess 3/3 T4 $3 | Tomb Turning (spell) T4 $2
  Hand: 3 cards

  → Board (6/7): 19/20 [Taunt], 7/8 [Taunt], 5/6, 9/5, 9/4, 4/4
  → Tier 5→6 | Gold 10→0 | HP 14→12
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=7 Gold=10 Tier=5

  Board (7/7): 7/5, 8/3, 9/12, 10/7, 5/6, 4/7, 5/3 [Taunt,DS]
  Tavern (6 items): Leeching Felhound 3/3 T3 $3 | Ancestral Automaton 3/4 T2 $3 | Friendly Geist 9/3 T4 $3 | Hunting Tiger Shark 3/5 T4 $3 | Famished Felbat 6/3 T5 $3 | Undersea Mount (spell) T1 $3
  Hand: 2 cards

  → Board (7/7): 7/5, 8/3, 9/12, 10/7, 5/6, 4/7, 9/3
  → Tier 5→6 | Gold 10→0 | Hand 2→1
  → Actions: (auto)

**Combat Phase**

  [heur] Drek'Thar vs [heur] Overlord Saurfang (first: Drek'Thar)
     Drek'Thar: [8/6, 8/4, 13/18, 11/8, 6/7, 5/8, 10/4]
     Overlord Saurfang: [26/31, 31/29, 29/30, 28/30, 29/27, 28/28, 41/42]
     Old Soul 8/6→8/0 DEAD  |  Annoy-o-Module 28/30→28/30
     Hardy Orca 26/31→26/26  |  Tichondrius 5/8→5/0 DEAD
     Eternal Knight 8/4→9/0 DEAD  |  Hardy Orca 26/26→26/18
     Shadowdancer 31/29→31/19  |  Friendly Geist 10/4→10/0 DEAD
     Flaming Enforcer 13/18→13/0 DEAD  |  Annoy-o-Module 28/30→28/17
     Laboratory Assistant 29/30→29/18  |  Darkcrest Strategist 12/11→12/0 DEAD
     Skeletal Strafer 11/8→11/0 DEAD  |  Alert Alarmist 28/28→28/17
     Result: 0 vs 7 — heur
  [heur] Ysera vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Ysera: [6/6, 5/6, 3/6, 4/10, 3/7, 4/5, 9/3]
     Inge, the Iron Hymn: [41/30, 41/47, 40/40, 31/32, 39/47, 34/37, 30/34]
     Mummifier 41/30→41/24  |  Scarlet Survivor 6/6→6/0 DEAD
     Woodland Defiler 5/6→5/0 DEAD  |  Divine Sparkbot 31/32→31/32
     Malchezaar, Prince of Dance 41/47→41/43  |  Darkcrest Strategist 4/5→4/0 DEAD
     Banana Slamma 3/6→3/0 DEAD  |  Divine Sparkbot 31/32→31/29
     Tichondrius 40/40→40/31  |  Trigore the Lasher 9/3→9/0 DEAD
     Catacomb Crasher 4/10→4/0 DEAD  |  Divine Sparkbot 31/29→31/25
     Divine Sparkbot 31/25→31/22  |  Marquee Ticker 3/7→3/0 DEAD
     Result: 0 vs 7 — heur

  **Ysera [Heuristic] eliminated!** (Turn 11)
  Alive: 4/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Inge, the Iron Hymn (HP=24, Tier=6) | Drek'Thar (HP=22, Tier=6) | Sylvanas Windrunner (HP=12, Tier=6)

### Turn 12

**Overlord Saurfang** [Heuristic]  HP=30 Armor=10 Gold=10 Tier=6

  Board (7/7): 26/31 [Taunt], 31/29 [Taunt], 29/30, 28/30 [Taunt,DS], 29/27 [Reborn], 28/28 [Taunt], 41/42
  Tavern (7 items): Goldrinn, the Great Wolf 44/44 T6 $3 | Rimescale Priestess 39/39 T4 $3 | Rabid Panther 40/44 T6 $3 | Famished Felbat 42/39 T5 $3 | False Implicator 37/37 T3 $3 | Accord-o-Tron 39/39 T3 $3 | Tavern Coin (spell) T1 $3
  Hand: 3 cards

  → Board (7/7): 31/29 [Taunt], 41/42, 44/44, 40/44, 42/39, 39/39, 39/39
  → Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=6

  Board (7/7): 41/30, 41/47, 40/40, 31/32 [Taunt,DS], 39/47, 34/37, 30/34
  Tavern (7 items): Stomping Stegodon 33/31 T4 $3 | Drustfallen Butcher 41/37 T5 $3 | False Implicator 27/32 T3 $3 | Shell Collector 33/33 T2 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Wintergrasp Ghoul 44/31 T5 $3 | Butchering (spell) T5 $2
  Hand: 5 cards

  → Board (7/7): 41/47, 39/47, 66/67 [WF], 71/71, 44/31, 73/71, 39/41
  → Gold 10→0 | Hand 5→4
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=6

  Board (6/7): 19/20 [Taunt], 7/8 [Taunt], 5/6, 9/5, 9/4, 4/4
  Tavern (7 items): Zesty Shaker 6/7 T4 $3 | Iridescent Skyblazer 3/8 T5 $3 | Prosthetic Hand 3/1 T4 $3 | Consummate Conqueror 9/7 T6 $3 | Maelstrom Emergent 2/7 T5 $3 | Sinrunner Blanchy 9/8 T5 $3 | Knockoff Wisdomball (spell) T6 $4
  Hand: 3 cards

  → Board (7/7): 24/23 [Taunt], 7/8 [Taunt], 9/5, 9/8 [Reborn], 9/7, 7/8, 4/9
  → Gold 10→0 | HP 12→11
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=22 Armor=0 Gold=10 Tier=6

  Board (7/7): 8/6, 9/4, 13/18, 11/8, 6/7, 5/8, 10/4
  Tavern (7 items): Sinrunner Blanchy 11/8 T5 $3 | Ruthless Queensguard 3/3 T6 $3 | Eternal Knight 9/2 T2 $3 | Tranquil Meditative 3/8 T5 $3 | Batty Terrorguard 6/2 T6 $3 | Glowscale 4/6 T5 $3 | Sanctify (spell) T5 $1
  Hand: 2 cards

  → Board (7/7): 8/6, 9/4, 16/21, 11/8, 10/4, 11/8 [Reborn], 6/2
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Drek'Thar vs [heur] Sylvanas Windrunner (first: Drek'Thar)
     Drek'Thar: [9/7, 9/5, 17/22, 12/9, 11/5, 12/9, 7/3]
     Sylvanas Windrunner: [24/23, 7/8, 9/5, 9/8, 9/7, 7/8, 4/9]
     Old Soul 9/7→9/0 DEAD  |  Technical Element 7/8→7/0 DEAD
     Wrath Weaver 24/23→24/6  |  Flaming Enforcer 17/22→17/0 DEAD
     Eternal Knight 9/5→10/0 DEAD  |  Wrath Weaver 24/6→24/0 DEAD
     Trigore the Lasher 9/5→9/0 DEAD  |  Sinrunner Blanchy 12/9→12/0 DEAD
     Skeletal Strafer 12/9→12/0 DEAD  |  Consummate Conqueror 9/7→9/0 DEAD
     Sinrunner Blanchy 9/8→9/1  |  Batty Terrorguard 7/3→7/0 DEAD
     Friendly Geist 11/5→11/0 DEAD  |  Sinrunner Blanchy 9/1→9/0 DEAD
     Result: 0 vs 2 — heur
  [heur] Overlord Saurfang vs [heur] Inge, the Iron Hymn (first: Overlord Saurfang)
     Overlord Saurfang: [68/66, 41/42, 44/44, 40/44, 42/39, 39/39, 39/39]
     Inge, the Iron Hymn: [41/47, 39/47, 66/67, 71/71, 44/31, 73/71, 39/41]
     Shadowdancer 68/66→68/0 DEAD  |  Stomping Stegodon 73/71→73/3
     Malchezaar, Prince of Dance 41/47→41/6  |  Zesty Shaker 41/42→41/1
     Zesty Shaker 41/1→41/0 DEAD  |  Sly Raptor 39/47→39/6
     Sly Raptor 39/6→39/0 DEAD  |  Goldrinn, the Great Wolf 44/44→44/5
     Goldrinn, the Great Wolf 44/5→44/0 DEAD  |  Shell Collector 66/67→66/23
     Shell Collector 66/23→66/0 DEAD  |  Rimescale Priestess 39/39→39/0 DEAD
     Rabid Panther 44/48→44/7  |  Malchezaar, Prince of Dance 41/6→41/0 DEAD
     Drustfallen Butcher 71/71→71/27  |  Rabid Panther 44/7→44/0 DEAD
     Famished Felbat 42/39→42/0 DEAD  |  Stomping Stegodon 73/3→73/0 DEAD
     Wintergrasp Ghoul 44/31→44/0 DEAD  |  Accord-o-Tron 39/39→39/0 DEAD
     Result: 0 vs 2 — heur

  Alive: 4/8
  HP: Overlord Saurfang (HP=25, Tier=6) | Inge, the Iron Hymn (HP=24, Tier=6) | Sylvanas Windrunner (HP=11, Tier=6) | Drek'Thar (HP=7, Tier=6)

### Turn 13

**Overlord Saurfang** [Heuristic]  HP=25 Armor=0 Gold=11 Tier=6

  Board (7/7): 68/66 [Taunt], 41/42, 44/44, 40/44, 42/39, 39/39, 39/39
  Tavern (7 items): Handless Forsaken 44/42 T3 $3 | Sinrunner Blanchy 50/49 T5 $3 | Eternal Tycoon 46/49 T5 $3 | Laboratory Assistant 44/45 T2 $3 | Humming Bird 42/45 T2 $3 | Catacomb Crasher 46/51 T5 $3 | Careful Investment (spell) T3 $1
  Hand: 5 cards

  → Board (7/7): 68/66 [Taunt], 44/44, 50/49 [Reborn], 46/51, 46/49, 44/45, 44/42
  → Gold 11→2 | Hand 5→4
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=6

  Board (7/7): 41/47, 39/47, 66/67 [WF], 71/71, 44/31, 73/71, 39/41
  Tavern (7 items): Divine Sparkbot 85/80 T5 $3 | One-Amalgam Tour Group 17/7 T6 $3 | Humming Bird 42/46 T2 $3 | Iridescent Skyblazer 42/47 T5 $3 | Ashen Corruptor 46/50 T5 $3 | Waverider 2/8 T4 $3 | Lost Staff of Hamuul (spell) T6 $2
  Hand: 6 cards

  → Board (6/7): 66/67 [WF], 73/71, 85/91, 85/80 [Taunt,DS], 86/78, 42/46
  → Gold 10→0 | Hand 6→5
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=11 Armor=0 Gold=10 Tier=6

  Board (7/7): 24/23 [Taunt], 7/8 [Taunt], 9/6, 9/8 [Reborn], 9/7, 7/8, 4/9
  Tavern (7 items): Scarlet Skull 3/1 T2 $3 | Consummate Conqueror 9/7 T6 $3 | Wintergrasp Ghoul 6/3 T5 $3 | Flaming Enforcer 4/5 T4 $3 | Spiked Savior 8/2 T5 $3 | Forsaken Weaver 4/10 T6 $3 | Evolving Strategy (spell) T1 $3
  Hand: 3 cards

  → Board (7/7): 28/27 [Taunt], 9/8 [Reborn], 20/13, 7/8, 9/7, 6/12, 3/6
  → Gold 10→0 | HP 11→9 | Hand 3→2
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=7 Armor=0 Gold=10 Tier=6

  Board (7/7): 9/7, 10/5, 17/22, 12/9, 11/5, 12/9 [Reborn], 7/3
  Tavern (7 items): Humming Bird 1/4 T2 $3 | Nightmare Par-tea Guest 6/3 T5 $3 | Famished Felbat 6/3 T5 $3 | Tichondrius 3/6 T5 $3 | Shell Collector 4/3 T2 $3 | Tranquil Meditative 3/8 T5 $3 | Perfect Vision (spell) T6 $2
  Hand: 2 cards

  → Board (7/7): 9/7, 10/5, 18/26, 12/9, 11/5, 12/9 [Reborn], 4/3
  → Gold 10→0 | Hand 2→3
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Sylvanas Windrunner (first: Overlord Saurfang)
     Overlord Saurfang: [68/66, 44/44, 50/49, 46/51, 46/49, 44/45, 44/42]
     Sylvanas Windrunner: [28/27, 9/8, 20/13, 7/8, 9/7, 6/12, 3/6]
     Shadowdancer 68/66→68/38  |  Wrath Weaver 28/27→28/0 DEAD
     Sinrunner Blanchy 9/8→9/0 DEAD  |  Shadowdancer 68/38→68/29
     Goldrinn, the Great Wolf 44/44→44/41  |  Dustbone Devastator 3/6→3/0 DEAD
     Consummate Conqueror 20/13→20/0 DEAD  |  Shadowdancer 68/29→68/9
     Sinrunner Blanchy 50/49→50/42  |  Zesty Shaker 7/8→7/0 DEAD
     Consummate Conqueror 9/7→9/0 DEAD  |  Shadowdancer 68/9→68/0 DEAD
     Catacomb Crasher 46/51→46/45  |  Forsaken Weaver 6/12→6/0 DEAD
     Result: 6 vs 0 — heur
  [heur] Drek'Thar vs [heur] Inge, the Iron Hymn (first: Drek'Thar)
     Drek'Thar: [10/8, 10/6, 19/27, 13/10, 12/6, 13/10, 5/4]
     Inge, the Iron Hymn: [66/67, 74/71, 85/91, 85/80, 87/78, 43/46]
     Old Soul 10/8→10/0 DEAD  |  Divine Sparkbot 85/80→85/80
     Shell Collector 66/67→66/54  |  Sinrunner Blanchy 13/10→13/0 DEAD
     Eternal Knight 10/6→11/0 DEAD  |  Divine Sparkbot 85/80→85/70
     Shell Collector 66/54→66/42  |  Friendly Geist 12/6→12/0 DEAD
     Flaming Enforcer 19/27→19/0 DEAD  |  Divine Sparkbot 85/70→85/51
     Stomping Stegodon 74/71→74/58  |  Skeletal Strafer 13/10→13/0 DEAD
     Shell Collector 11/8→11/0 DEAD  |  Divine Sparkbot 85/51→85/40
     Result: 0 vs 6 — heur

  **Sylvanas Windrunner [Heuristic] eliminated!** (Turn 13)
  **Drek'Thar [Heuristic] eliminated!** (Turn 13)
  Alive: 2/8
  HP: Overlord Saurfang (HP=25, Tier=6) | Inge, the Iron Hymn (HP=24, Tier=6)

### Turn 14

**Overlord Saurfang** [Heuristic]  HP=25 Armor=0 Gold=10 Tier=6

  Board (7/7): 68/66 [Taunt], 44/44, 50/49 [Reborn], 46/51, 46/49, 44/45, 44/42
  Tavern (7 items): Abyssal Bruiser 1/1 T4 $3 | Cord Puller 46/46 T1 $3 | Leeching Felhound 48/48 T3 $3 | Cadaver Caretaker 49/48 T3 $3 | Tidemistress Athissa 51/52 T6 $3 | Falling Sky Golem 9/7 T6 $3 | Misplaced Tea Set (spell) T4 $2
  Hand: 5 cards

  → Board (6/7): 50/49 [Reborn], 46/51, 53/54, 49/48, 48/48, 1/3 [DS]
  → Gold 10→2 | HP 25→22 | Hand 5→4
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=6

  Board (6/7): 66/67 [WF], 73/71, 85/91, 85/80 [Taunt,DS], 86/78, 42/46
  Tavern (7 items): Cadaver Caretaker 14/3 T3 $3 | Ring Bearer 51/59 T6 $3 | Sewer Rat 102/100 T2 $3 | Lava Lurker 90/91 T2 $3 | Lurking Leviathan 3/8 T5 $3 | Zesty Shaker 6/7 T4 $3 | Staff of Enrichment (spell) T3 $2
  Hand: 5 cards

  → Board (7/7): 85/91, 85/80 [Taunt,DS], 86/78, 102/100, 90/91, 80/70, 79/78
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Inge, the Iron Hymn vs [heur] Overlord Saurfang (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [85/91, 85/80, 86/78, 102/100, 90/91, 80/70, 79/78]
     Overlord Saurfang: [50/49, 46/51, 53/54, 49/48, 48/48, 1/3]
     Ashen Corruptor 85/91→85/43  |  Leeching Felhound 48/48→48/0 DEAD
     Sinrunner Blanchy 50/49→50/0 DEAD  |  Divine Sparkbot 85/80→85/80
     Divine Sparkbot 85/80→85/31  |  Cadaver Caretaker 49/48→49/0 DEAD
     Catacomb Crasher 46/51→46/0 DEAD  |  Divine Sparkbot 85/31→85/0 DEAD
     Iridescent Skyblazer 86/78→86/25  |  Tidemistress Athissa 53/54→53/0 DEAD
     Abyssal Bruiser 1/3→1/3  |  Zesty Shaker 79/78→79/77
     Sewer Rat 103/101→103/100  |  Abyssal Bruiser 1/3→1/0 DEAD
     Result: 6 vs 0 — heur

  **Overlord Saurfang [Heuristic] eliminated!** (Turn 14)
  **Inge, the Iron Hymn [Heuristic] eliminated!** (Turn 14)

---

## Final Standings

| # | Hero | Role | HP | Tier | Eliminated |
|---|---|---|---|---|---|
| 1 | Inge, the Iron Hymn | Heuristic | 24 | 6 | 14 |
| 2 | Overlord Saurfang | Heuristic | 0 | 6 | 14 |
| 3 | Sylvanas Windrunner | Heuristic | 0 | 6 | 13 |
| 4 | Drek'Thar | Heuristic | 0 | 6 | 13 |
| 5 | Ysera | Heuristic | 0 | 6 | 11 |
| 6 | Sneed | Heuristic | 0 | 5 | 10 |
| 7 | Professor Putricide | Heuristic | 0 | 5 | 10 |
| 8 | Yogg-Saron, Hope's End | AGENT | 0 | 4 | 9 |