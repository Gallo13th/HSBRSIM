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

  → Board (1/7): 4/1
  → Gold 3→0
  → Actions: buy_tavern_0, play_hand_0

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
     Yogg-Saron, Hope's End: [4/1]
     Scarlet Survivor 3/3→3/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: 0 vs 0 — draw
  [heur] Sylvanas Windrunner vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Sylvanas Windrunner: [2/1]
     Inge, the Iron Hymn: [4/1]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Result: 0 vs 0 — draw

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=1) | Sneed (HP=30, Tier=1) | Overlord Saurfang (HP=30, Tier=1) | Ysera (HP=30, Tier=1) | Inge, the Iron Hymn (HP=30, Tier=1) | Professor Putricide (HP=30, Tier=1) | Sylvanas Windrunner (HP=30, Tier=1) | Drek'Thar (HP=30, Tier=1)

### Turn 2

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=18 Gold=4 Tier=1

  Board (1/7): 4/1
  Tavern (4 items): Wrath Weaver 1/4 T1 $3 | Manasaber 4/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Angler's Lure (spell) T1 $3
  Hand: 0 cards

  → Board (2/7): 4/1, 4/1
  → Gold 4→1
  → Actions: buy_tavern_1, play_hand_0

**Sneed** [Heuristic]  HP=30 Armor=12 Gold=4 Tier=1

  Board (1/7): 2/1
  Tavern (4 items): Harmless Bonehead 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | The Goldenizer (spell) T1 $0
  Hand: 0 cards

  → Board (2/7): 2/1, 4/1
  → Gold 4→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=18 Gold=4 Tier=1

  Board (1/7): 2/5
  Tavern (4 items): Wrath Weaver 4/7 T1 $3 | Harmless Bonehead 4/4 T1 $3 | Risen Rider 5/4 T1 $3 | Recruit a Trainee (spell) T1 $2
  Hand: 0 cards

  → Board (2/7): 4/7, 4/7
  → Gold 4→0 | Armor 18→17
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=12 Gold=4 Tier=1

  Board (1/7): 3/3
  Tavern (5 items): Harmless Bonehead 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Ominous Seer 2/1 T1 $3 | Fortify (spell) T1 $1 | Scarlet Survivor 3/3 T1 $3
  Hand: 0 cards

  → Board (2/7): 3/3, 3/3
  → Gold 4→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=4 Tier=1

  Board (1/7): 4/1
  Tavern (4 items): Annoy-o-Tron 1/2 T1 $3 | Ominous Seer 2/1 T1 $3 | Picky Eater 1/1 T1 $3 | Sick Riffs (spell) T1 $3
  Hand: 0 cards

  → Board (2/7): 4/1, 1/2 [Taunt,DS]
  → Gold 4→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=10 Gold=4 Tier=1

  Board (1/7): 4/1
  Tavern (4 items): Cord Puller 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Manasaber 4/1 T1 $3 | Undersea Mount (spell) T1 $3
  Hand: 0 cards

  → Board (2/7): 4/1, 4/1
  → Gold 4→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=10 Gold=4 Tier=1

  Board (1/7): 2/1 [Taunt,Reborn]
  Tavern (4 items): Cord Puller 1/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Banana (spell) T1 $0
  Hand: 0 cards

  → Board (2/7): 2/1 [Taunt,Reborn], 1/1 [DS]
  → Gold 4→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=4 Tier=1

  Board (1/7): 2/1 [Taunt,Reborn]
  Tavern (4 items): Wrath Weaver 1/4 T1 $3 | Ominous Seer 2/1 T1 $3 | Manasaber 4/1 T1 $3 | Enchanted Lasso (spell) T1 $2
  Hand: 0 cards

  → Board (2/7): 2/1 [Taunt,Reborn], 1/4
  → Gold 4→0
  → Actions: (auto)

**Combat Phase**

  [heur] Drek'Thar vs [AGENT] Yogg-Saron, Hope's End (first: Drek'Thar)
     Drek'Thar: [2/1, 1/4]
     Yogg-Saron, Hope's End: [4/1, 4/1]
     Risen Rider 2/1→2/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 1/4→1/0 DEAD
     Result: 0 vs 0 — draw
  [heur] Overlord Saurfang vs [heur] Ysera (first: Ysera)
     Overlord Saurfang: [4/7, 4/7]
     Ysera: [3/3, 3/3]
     Scarlet Survivor 3/3→3/0 DEAD  |  Wrath Weaver 4/7→4/4
     Wrath Weaver 4/4→4/1  |  Scarlet Survivor 3/3→3/0 DEAD
     Result: 2 vs 0 — heur
  [heur] Inge, the Iron Hymn vs [heur] Sneed (first: Sneed)
     Inge, the Iron Hymn: [4/1, 1/2]
     Sneed: [2/1, 4/1]
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Sylvanas Windrunner vs [heur] Professor Putricide (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [2/1, 1/1]
     Professor Putricide: [4/1, 4/1]
     Risen Rider 2/1→2/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Cord Puller 1/1→1/1
     Result: 1 vs 0 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=1) | Sneed (HP=30, Tier=1) | Overlord Saurfang (HP=30, Tier=1) | Ysera (HP=30, Tier=1) | Inge, the Iron Hymn (HP=30, Tier=1) | Professor Putricide (HP=30, Tier=1) | Sylvanas Windrunner (HP=30, Tier=1) | Drek'Thar (HP=30, Tier=1)

### Turn 3

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=18 Gold=5 Tier=1

  Board (2/7): 4/1, 4/1
  Tavern (3 items): Cord Puller 1/1 T1 $3 | Risen Rider 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 4/1, 4/1, 2/1 [Taunt,Reborn]
  → Gold 5→2
  → Actions: buy_tavern_1, play_hand_0

**Sneed** [Heuristic]  HP=30 Armor=10 Gold=5 Tier=1

  Board (2/7): 2/1, 4/1
  Tavern (3 items): Ominous Seer 2/1 T1 $3 | Manasaber 4/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1, 4/1, 4/1
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=5 Tier=1

  Board (2/7): 4/7, 4/7
  Tavern (3 items): Picky Eater 6/6 T1 $3 | Harmless Bonehead 6/6 T1 $3 | Wrath Weaver 6/9 T1 $3
  Hand: 0 cards

  → Board (2/7): 13/19 [G], 2/4 [Taunt]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=9 Gold=5 Tier=1

  Board (2/7): 3/3, 3/3
  Tavern (4 items): Surf n' Surf 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Risen Rider 2/1 T1 $3 | Scarlet Survivor 3/3 T1 $3
  Hand: 0 cards

  → Board (2/7): 6/6 [G], 4/4
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=5 Tier=1

  Board (2/7): 4/1, 1/2 [Taunt,DS]
  Tavern (3 items): Cord Puller 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3
  Hand: 0 cards

  → Board (3/7): 4/1, 1/2 [Taunt,DS], 4/1
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=8 Gold=5 Tier=1

  Board (2/7): 4/1, 4/1
  Tavern (3 items): Cord Puller 1/1 T1 $3 | Cord Puller 1/1 T1 $3 | Cord Puller 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 4/1, 4/1, 1/1 [DS]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=10 Gold=5 Tier=1

  Board (2/7): 2/1 [Taunt,Reborn], 1/1 [DS]
  Tavern (3 items): Risen Rider 2/1 T1 $3 | Risen Rider 2/1 T1 $3 | Surf n' Surf 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1 [Taunt,Reborn], 1/1 [DS], 2/1 [Taunt,Reborn]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=5 Tier=1

  Board (2/7): 2/1 [Taunt,Reborn], 1/4
  Tavern (3 items): Annoy-o-Tron 1/2 T1 $3 | Risen Rider 2/1 T1 $3 | Cord Puller 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1 [Taunt,Reborn], 1/4, 1/2 [Taunt,DS]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Professor Putricide (first: Professor Putricide)
     Overlord Saurfang: [13/19, 2/4]
     Professor Putricide: [4/1, 4/1, 1/1]
     Manasaber 4/1→4/0 DEAD  |  Taunt Test Minion 2/4→2/0 DEAD
     Wrath Weaver 13/19→13/15  |  Manasaber 4/1→4/0 DEAD
     Cord Puller 1/1→1/1  |  Wrath Weaver 13/15→13/14
     Result: 1 vs 1 — heur
  [heur] Drek'Thar vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Drek'Thar: [2/1, 1/4, 1/2]
     Sylvanas Windrunner: [2/1, 1/1, 2/1]
     Risen Rider 2/1→2/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 1/4→1/2  |  Risen Rider 2/1→2/0 DEAD
     Cord Puller 1/1→1/1  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Cord Puller 1/1→1/0 DEAD
     Result: 2 vs 0 — heur
  [heur] Inge, the Iron Hymn vs [AGENT] Yogg-Saron, Hope's End (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 4/1]
     Yogg-Saron, Hope's End: [4/1, 4/1, 2/1]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Sneed vs [heur] Ysera (first: Sneed)
     Sneed: [2/1, 4/1, 4/1]
     Ysera: [6/6, 4/4]
     Ominous Seer 2/1→2/0 DEAD  |  Sklibb, Demon Hunter 4/4→4/2
     Scarlet Survivor 6/6→6/2  |  Manasaber 4/1→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Scarlet Survivor 6/2→6/0 DEAD
     Result: 0 vs 1 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=1) | Sneed (HP=30, Tier=2) | Overlord Saurfang (HP=30, Tier=2) | Ysera (HP=30, Tier=2) | Inge, the Iron Hymn (HP=30, Tier=2) | Professor Putricide (HP=30, Tier=2) | Sylvanas Windrunner (HP=30, Tier=2) | Drek'Thar (HP=30, Tier=2)

### Turn 4

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=15 Gold=6 Tier=1

  Board (3/7): 4/1, 4/1, 2/1 [Taunt,Reborn]
  Tavern (3 items): Cord Puller 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Surf n' Surf 1/1 T1 $3
  Hand: 0 cards

  → Actions: 

**Sneed** [Heuristic]  HP=30 Armor=7 Gold=6 Tier=2

  Board (3/7): 2/1, 4/1, 4/1
  Tavern (5 items): Alert Alarmist 2/2 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Shell Collector 4/3 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Might of Stormwind (spell) T2 $2
  Hand: 0 cards

  → Board (5/7): 2/1, 4/1, 4/1, 4/3, 3/4
  → Gold 6→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=6 Tier=2

  Board (2/7): 13/19 [G], 2/4 [Taunt]
  Tavern (5 items): Alert Alarmist 9/9 T2 $3 | Old Soul 10/11 T2 $3 | Eternal Knight 4/2 T2 $3 | Sewer Rat 10/9 T2 $3 | Chef's Choice (spell) T2 $2
  Hand: 0 cards

  → Board (4/7): 13/19 [G], 2/4 [Taunt], 10/11, 10/9
  → Gold 6→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=9 Gold=6 Tier=2

  Board (2/7): 6/6 [G], 4/4
  Tavern (6 items): Tide Raiser 2/1 T2 $3 | Metallic Hunter 4/2 T2 $3 | Tide Raiser 2/1 T2 $3 | Tide Raiser 2/1 T2 $3 | Search Through Time (spell) T2 $2 | Twilight Hatchling 1/1 T1 $3
  Hand: 0 cards

  → Board (4/7): 6/6 [G], 4/4, 4/2, 2/1 [Taunt]
  → Gold 6→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=6 Tier=2

  Board (3/7): 4/1, 1/2 [Taunt,DS], 4/1
  Tavern (5 items): Sewer Rat 3/2 T2 $3 | Ominous Seer 2/1 T1 $3 | Old Soul 3/4 T2 $3 | Humming Bird 1/4 T2 $3 | Hasty Excavation (spell) T2 $3
  Hand: 0 cards

  → Board (5/7): 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/2
  → Gold 6→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=8 Gold=6 Tier=2

  Board (3/7): 4/1, 4/1, 1/1 [DS]
  Tavern (5 items): Scarlet Skull 2/1 T2 $3 | Eternal Knight 4/2 T2 $3 | Eternal Knight 4/2 T2 $3 | Alert Alarmist 2/2 T2 $3 | Strike Oil (spell) T2 $3
  Hand: 0 cards

  → Board (5/7): 4/1, 4/1, 1/1 [DS], 4/2, 4/2
  → Gold 6→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=6 Gold=6 Tier=2

  Board (3/7): 2/1 [Taunt,Reborn], 1/1 [DS], 2/1 [Taunt,Reborn]
  Tavern (5 items): Nerubian Deathswarmer 1/4 T2 $3 | Wrath Weaver 1/4 T1 $3 | Shell Collector 4/3 T2 $3 | Scarlet Skull 2/1 T2 $3 | Leaf Through the Pages (spell) T2 $1
  Hand: 0 cards

  → Board (5/7): 3/1 [Taunt,Reborn], 1/1 [DS], 3/1 [Taunt,Reborn], 4/3, 2/4
  → Gold 6→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=6 Tier=2

  Board (3/7): 2/1 [Taunt,Reborn], 1/4, 1/2 [Taunt,DS]
  Tavern (4 items): Alert Alarmist 2/2 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Harmless Bonehead 1/1 T1 $3 | Scarlet Skull 2/1 T2 $3
  Hand: 0 cards

  → Board (5/7): 2/1 [Taunt,Reborn], 1/4, 1/2 [Taunt,DS], 3/4, 2/2 [Taunt]
  → Gold 6→0
  → Actions: (auto)

**Combat Phase**

  [heur] Drek'Thar vs [heur] Overlord Saurfang (first: Drek'Thar)
     Drek'Thar: [2/1, 1/4, 1/2, 3/4, 2/2]
     Overlord Saurfang: [13/19, 2/4, 10/11, 10/9]
     Risen Rider 2/1→2/0 DEAD  |  Taunt Test Minion 2/4→2/2
     Wrath Weaver 13/19→13/17  |  Alert Alarmist 2/2→2/0 DEAD
     Wrath Weaver 1/4→1/2  |  Taunt Test Minion 2/2→2/1
     Taunt Test Minion 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Wrath Weaver 13/17→13/16
     Old Soul 10/11→10/8  |  Ancestral Automaton 3/4→3/0 DEAD
     Result: 1 vs 3 — heur
  [heur] Ysera vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Ysera: [6/6, 4/4, 4/2, 2/1]
     Sylvanas Windrunner: [3/1, 1/1, 3/1, 4/3, 2/4]
     Risen Rider 3/1→3/0 DEAD  |  Tide Raiser 2/1→2/0 DEAD
     Scarlet Survivor 6/6→6/3  |  Risen Rider 3/1→3/0 DEAD
     Cord Puller 1/1→1/1  |  Scarlet Survivor 6/3→6/2
     Sklibb, Demon Hunter 4/4→4/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Nerubian Deathswarmer 2/4→2/0 DEAD  |  Metallic Hunter 5/4→5/2
     Metallic Hunter 5/2→5/1  |  Cord Puller 1/1→1/0 DEAD
     Result: 2 vs 0 — heur
  [heur] Inge, the Iron Hymn vs [heur] Professor Putricide (first: Professor Putricide)
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4, 3/2]
     Professor Putricide: [4/1, 4/1, 1/1, 4/2, 4/2]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Eternal Knight 4/2→5/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Cord Puller 1/1→1/1
     Cord Puller 1/1→1/0 DEAD  |  Sewer Rat 3/2→3/1
     Old Soul 3/4→3/0 DEAD  |  Eternal Knight 5/2→6/0 DEAD
     Result: 1 vs 0 — heur
  [AGENT] Yogg-Saron, Hope's End vs [heur] Sneed (first: Sneed)
     Yogg-Saron, Hope's End: [4/1, 4/1, 2/1]
     Sneed: [2/1, 4/1, 4/1, 4/3, 3/4]
     Ominous Seer 2/1→2/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: 0 vs 2 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=1) | Sneed (HP=30, Tier=2) | Overlord Saurfang (HP=30, Tier=2) | Ysera (HP=30, Tier=2) | Inge, the Iron Hymn (HP=30, Tier=2) | Professor Putricide (HP=30, Tier=2) | Sylvanas Windrunner (HP=30, Tier=2) | Drek'Thar (HP=30, Tier=2)

### Turn 5

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=9 Gold=7 Tier=1

  Board (3/7): 4/1, 4/1, 2/1 [Taunt,Reborn]
  Tavern (4 items): Picky Eater 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Ominous Seer 2/1 T1 $3 | Tavern Coin (spell) T1 $3
  Hand: 0 cards

  → Board (3/7): 4/1, 4/1, 1/2 [Taunt,DS]
  → Gold 7→5
  → Actions: buy_tavern_1, play_hand_0, sell_board_2

**Sneed** [Heuristic]  HP=30 Armor=7 Gold=7 Tier=2

  Board (5/7): 2/1, 4/1, 4/1, 4/3, 3/4
  Tavern (4 items): Manasaber 4/1 T1 $3 | Soul Rewinder 4/1 T2 $3 | Harmless Bonehead 1/1 T1 $3 | Alert Alarmist 2/2 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=7 Tier=2

  Board (4/7): 13/19 [G], 2/4 [Taunt], 10/11, 10/9
  Tavern (4 items): Harmless Bonehead 11/11 T1 $3 | Humming Bird 11/14 T2 $3 | Metallic Hunter 14/12 T2 $3 | Alert Alarmist 12/12 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=9 Gold=7 Tier=2

  Board (4/7): 6/6 [G], 4/4, 4/2, 2/1 [Taunt]
  Tavern (5 items): Shell Collector 4/3 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Ominous Seer 2/1 T1 $3 | Ancestral Automaton 3/4 T2 $3 | Tarecgosa 4/4 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=7 Tier=2

  Board (5/7): 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/2
  Tavern (4 items): Humming Bird 1/4 T2 $3 | Humming Bird 1/4 T2 $3 | Risen Rider 2/1 T1 $3 | Metallic Hunter 4/2 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=4 Gold=7 Tier=2

  Board (5/7): 4/1, 4/1, 1/1 [DS], 6/2, 6/2
  Tavern (4 items): Cord Puller 1/1 T1 $3 | Scarlet Skull 2/1 T2 $3 | Old Soul 3/4 T2 $3 | Humming Bird 1/4 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=1 Gold=7 Tier=2

  Board (5/7): 3/1 [Taunt,Reborn], 1/1 [DS], 3/1 [Taunt,Reborn], 4/3, 2/4
  Tavern (4 items): Humming Bird 1/4 T2 $3 | Reef Riffer 3/2 T2 $3 | Eternal Knight 4/2 T2 $3 | Lava Lurker 2/5 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=7 Tier=2

  Board (5/7): 2/1 [Taunt,Reborn], 1/4, 1/2 [Taunt,DS], 3/4, 2/2 [Taunt]
  Tavern (4 items): Shell Collector 4/3 T2 $3 | Tide Raiser 2/1 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Eternal Knight 4/2 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Ysera (first: Ysera)
     Overlord Saurfang: [13/19, 2/4, 10/11, 10/9]
     Ysera: [6/6, 4/4, 4/2, 2/1]
     Scarlet Survivor 6/6→6/4  |  Taunt Test Minion 2/4→2/0 DEAD
     Wrath Weaver 13/19→13/17  |  Tide Raiser 2/1→2/0 DEAD
     Sklibb, Demon Hunter 4/4→4/0 DEAD  |  Old Soul 10/11→10/7
     Old Soul 10/7→10/1  |  Scarlet Survivor 6/4→6/0 DEAD
     Metallic Hunter 5/4→5/0 DEAD  |  Old Soul 10/1→10/0 DEAD
     Result: 2 vs 0 — heur
  [heur] Inge, the Iron Hymn vs [heur] Sylvanas Windrunner (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4, 3/2]
     Sylvanas Windrunner: [3/1, 1/1, 3/1, 4/3, 2/4]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 3/1→3/0 DEAD
     Cord Puller 1/1→1/1  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Risen Rider 3/1→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Sewer Rat 3/2→3/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Nerubian Deathswarmer 2/4→2/0 DEAD
     Result: 1 vs 1 — heur
  [heur] Drek'Thar vs [heur] Professor Putricide (first: Drek'Thar)
     Drek'Thar: [2/1, 1/4, 1/2, 3/4, 2/2]
     Professor Putricide: [4/1, 4/1, 1/1, 6/2, 6/2]
     Risen Rider 2/1→2/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Wrath Weaver 1/4→1/3  |  Cord Puller 1/1→1/1
     Cord Puller 1/1→1/0 DEAD  |  Alert Alarmist 2/2→2/1
     Annoy-o-Tron 1/2→1/0 DEAD  |  Eternal Knight 6/2→6/1
     Eternal Knight 6/1→7/0 DEAD  |  Alert Alarmist 2/1→2/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Eternal Knight 7/2→8/0 DEAD
     Result: 1 vs 0 — heur
  [AGENT] Yogg-Saron, Hope's End vs [heur] Sneed (first: Sneed)
     Yogg-Saron, Hope's End: [4/1, 4/1, 1/2]
     Sneed: [2/1, 4/1, 4/1, 4/3, 3/4]
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Result: 0 vs 1 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=1) | Sneed (HP=30, Tier=3) | Overlord Saurfang (HP=30, Tier=3) | Ysera (HP=30, Tier=3) | Inge, the Iron Hymn (HP=30, Tier=3) | Professor Putricide (HP=30, Tier=3) | Sylvanas Windrunner (HP=30, Tier=3) | Drek'Thar (HP=30, Tier=3)

### Turn 6

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=4 Gold=8 Tier=1

  Board (3/7): 4/1, 4/1, 1/2 [Taunt,DS]
  Tavern (3 items): Ominous Seer 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3
  Hand: 0 cards

  → Gold 8→5 | Trinket: Ophidian Staff
  → Actions: refresh

**Sneed** [Heuristic]  HP=30 Armor=7 Gold=8 Tier=3

  Board (5/7): 2/1, 4/1, 4/1, 4/3, 3/4
  Tavern (5 items): Alert Alarmist 2/2 T2 $3 | Leeching Felhound 3/3 T3 $3 | Dustbone Devastator 2/6 T3 $3 | Sprightly Scarab 3/1 T3 $3 | Friendly Bounty (spell) T3 $2
  Hand: 0 cards

  → Board (7/7): 4/1, 4/1, 4/3, 3/4, 2/6, 3/3, 4/2 [Reborn]
  → Gold 8→0 | Armor 7→4 | Trinket: Vash'jir Anemone
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=8 Tier=3

  Board (4/7): 13/19 [G], 2/4 [Taunt], 10/11, 10/9
  Tavern (5 items): Deep-Sea Angler 12/13 T3 $3 | Technical Element 15/16 T3 $3 | Soul Rewinder 14/11 T2 $3 | Old Soul 13/14 T2 $3 | Tricky Trousers (spell) T3 $1
  Hand: 0 cards

  → Board (6/7): 13/19 [G], 2/4 [Taunt], 10/11, 10/9, 15/16, 13/14
  → Gold 8→0 | Trinket: Impulsive Portrait
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=3 Gold=8 Tier=3

  Board (4/7): 6/6 [G], 4/4, 4/2, 2/1 [Taunt]
  Tavern (5 items): Sly Raptor 1/3 T3 $3 | Picky Eater 1/1 T1 $3 | Mummifier 5/2 T3 $3 | Mummifier 5/2 T3 $3 | Roaring Recruiter 2/8 T3 $3
  Hand: 1 cards

  → Board (6/7): 6/6 [G], 4/4, 4/2, 2/1 [Taunt], 2/8, 5/2
  → Gold 8→0 | Trinket: Smuggler Portrait | Hand 1→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=8 Tier=3

  Board (5/7): 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 2/3 [Taunt]
  Tavern (4 items): Deflect-o-Bot 3/2 T3 $3 | Reef Riffer 3/2 T2 $3 | Deep-Sea Angler 2/3 T3 $3 | Sly Raptor 1/3 T3 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 2/3 [Taunt], 3/2 [DS], 3/2
  → Gold 8→0 | Trinket: Beetle Band
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=0 Gold=8 Tier=3

  Board (5/7): 4/1, 4/1, 1/1 [DS], 8/2, 8/2
  Tavern (4 items): Sewer Rat 3/2 T2 $3 | Deflect-o-Bot 3/2 T3 $3 | Ancestral Automaton 3/4 T2 $3 | Annoy-o-Module 2/4 T3 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 4/1, 1/1 [DS], 8/2, 8/2, 3/4, 2/4 [Taunt,DS]
  → Gold 8→0 | Trinket: Putricide Sticker
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=1 Gold=8 Tier=3

  Board (5/7): 3/1 [Taunt,Reborn], 1/1 [DS], 3/1 [Taunt,Reborn], 4/3, 2/4
  Tavern (4 items): Ancestral Automaton 3/4 T2 $3 | Deflect-o-Bot 3/2 T3 $3 | Eternal Knight 4/2 T2 $3 | Alert Alarmist 2/2 T2 $3
  Hand: 0 cards

  → Board (6/7): 3/1 [Taunt,Reborn], 1/1 [DS], 3/1 [Taunt,Reborn], 4/3, 2/4, 3/4
  → Gold 8→0 | Trinket: Unholy Sanctum
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=8 Tier=3

  Board (5/7): 2/1 [Taunt,Reborn], 1/4, 1/2 [Taunt,DS], 3/4, 2/2 [Taunt]
  Tavern (4 items): Mummifier 5/2 T3 $3 | Ancestral Automaton 3/4 T2 $3 | Leeching Felhound 3/3 T3 $3 | False Implicator 1/1 T3 $3
  Hand: 0 cards

  → Board (7/7): 5/8, 6/4, 2/2 [Taunt], 5/2, 6/4, 3/3, 1/1
  → Gold 8→0 | Armor 10→5 | Trinket: Stormcoil Sticker
  → Actions: (auto)

**Combat Phase**

  [heur] Professor Putricide vs [heur] Overlord Saurfang (first: Professor Putricide)
     Professor Putricide: [4/1, 4/1, 1/1, 8/2, 8/2, 3/4, 2/4]
     Overlord Saurfang: [13/19, 2/4, 10/11, 10/9, 15/16, 13/14]
     Manasaber 4/1→4/0 DEAD  |  Taunt Test Minion 2/4→2/0 DEAD
     Wrath Weaver 13/19→13/17  |  Annoy-o-Module 2/4→2/4
     Manasaber 4/1→4/0 DEAD  |  Technical Element 15/16→15/12
     Old Soul 10/11→10/9  |  Annoy-o-Module 2/4→2/0 DEAD
     Cord Puller 1/1→1/1  |  Old Soul 10/9→10/8
     Sewer Rat 10/9→10/1  |  Eternal Knight 8/2→9/0 DEAD
     Eternal Knight 9/2→10/0 DEAD  |  Wrath Weaver 13/17→13/8
     Technical Element 15/12→15/11  |  Cord Puller 1/1→1/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Technical Element 15/11→15/8
     Result: 0 vs 5 — heur
  [heur] Sylvanas Windrunner vs [heur] Drek'Thar (first: Drek'Thar)
     Sylvanas Windrunner: [3/1, 1/1, 3/1, 4/3, 2/4, 3/4]
     Drek'Thar: [5/8, 6/4, 2/2, 5/2, 6/4, 3/3, 1/1]
     Wrath Weaver 5/8→5/5  |  Risen Rider 3/1→3/0 DEAD
     Cord Puller 1/1→1/1  |  Alert Alarmist 2/2→2/1
     Ancestral Automaton 6/4→6/1  |  Risen Rider 3/1→3/0 DEAD
     Shell Collector 4/3→4/1  |  Alert Alarmist 2/1→2/0 DEAD
     Mummifier 5/2→5/0 DEAD  |  Shell Collector 4/1→4/0 DEAD
     Nerubian Deathswarmer 2/4→2/0 DEAD  |  Wrath Weaver 5/5→5/3
     Ancestral Automaton 6/4→6/1  |  Ancestral Automaton 3/4→3/0 DEAD
     Result: 1 vs 5 — heur
  [heur] Inge, the Iron Hymn vs [heur] Ysera (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4, 2/3, 3/2, 3/2]
     Ysera: [6/6, 4/4, 4/2, 2/1, 2/8, 5/2]
     Manasaber 4/1→4/0 DEAD  |  Tide Raiser 2/1→2/0 DEAD
     Scarlet Survivor 6/6→7/5  |  Half-Shell 2/3→2/0 DEAD
     Annoy-o-Tron 1/2→1/2  |  Roaring Recruiter 3/10→3/9
     Sklibb, Demon Hunter 4/4→4/3  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Mummifier 5/2→5/0 DEAD
     Metallic Hunter 4/2→4/0 DEAD  |  Deflect-o-Bot 3/2→3/2
     Old Soul 3/4→3/0 DEAD  |  Scarlet Survivor 7/5→7/2
     Roaring Recruiter 3/9→4/7  |  Reef Riffer 3/2→3/0 DEAD
     Deflect-o-Bot 3/2→3/0 DEAD  |  Sklibb, Demon Hunter 4/3→4/0 DEAD
     Result: 0 vs 2 — heur
  [heur] Sneed vs [AGENT] Yogg-Saron, Hope's End (first: Sneed)
     Sneed: [4/1, 4/1, 4/4, 3/4, 2/6, 3/3, 4/2]
     Yogg-Saron, Hope's End: [4/1, 4/1, 1/2]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Shell Collector 4/4→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Sprightly Scarab 4/2→4/0 DEAD
     Result: 3 vs 0 — heur

  Alive: 8/8
  HP: Sneed (HP=30, Tier=3) | Overlord Saurfang (HP=30, Tier=3) | Ysera (HP=30, Tier=3) | Inge, the Iron Hymn (HP=30, Tier=3) | Sylvanas Windrunner (HP=30, Tier=3) | Drek'Thar (HP=30, Tier=3) | Yogg-Saron, Hope's End (HP=24, Tier=1) | Professor Putricide (HP=20, Tier=3)

### Turn 7

**Yogg-Saron, Hope's End** [RL AGENT]  HP=24 Armor=0 Gold=9 Tier=1

  Board (3/7): 4/1, 4/1, 1/2 [Taunt,DS]
  Tavern (3 items): Wrath Weaver 1/4 T1 $3 | Surf n' Surf 1/1 T1 $3 | Harmless Bonehead 1/1 T1 $3
  Hand: 0 cards

  → Board (4/7): 4/1, 4/1, 1/2 [Taunt,DS], 1/4
  → Gold 9→6
  → Actions: buy_tavern_0, play_hand_0

**Sneed** [Heuristic]  HP=30 Armor=4 Gold=9 Tier=3

  Board (7/7): 4/1, 4/1, 4/3, 3/4, 2/6, 3/3, 4/2 [Reborn]
  Tavern (4 items): Sprightly Scarab 3/1 T3 $3 | Shell Collector 4/3 T2 $3 | Alert Alarmist 2/2 T2 $3 | Tide Raiser 2/1 T2 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 4/3, 3/4, 2/6, 3/3, 4/2 [Reborn], 4/3
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=9 Tier=3

  Board (6/7): 13/19 [G], 2/4 [Taunt], 10/11, 10/9, 15/16, 13/14
  Tavern (4 items): Ancestral Automaton 3/4 T2 $3 | Handless Forsaken 17/16 T3 $3 | Deep-Sea Angler 17/18 T3 $3 | Annoy-o-Module 17/19 T3 $3
  Hand: 0 cards

  → Board (7/7): 13/19 [G], 2/4 [Taunt], 10/11, 10/9, 15/16, 13/14, 17/19 [Taunt,DS]
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=3 Gold=9 Tier=3

  Board (6/7): 6/6 [G], 4/4, 4/2, 2/1 [Taunt], 2/8, 5/2
  Tavern (5 items): Lava Lurker 2/5 T2 $3 | Scarlet Skull 2/1 T2 $3 | Soul Rewinder 4/1 T2 $3 | Tide Raiser 2/1 T2 $3 | Blazing Skyfin 2/4 T2 $3
  Hand: 1 cards

  → Board (7/7): 6/6 [G], 4/4, 4/2, 2/1 [Taunt], 2/8, 5/2, 2/5
  → Tier 3→4 | Gold 9→0 | Hand 1→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=5 Gold=9 Tier=3

  Board (7/7): 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 2/3 [Taunt], 3/2 [DS], 3/2
  Tavern (4 items): Soul Rewinder 4/1 T2 $3 | Tide Raiser 2/1 T2 $3 | Shell Collector 4/3 T2 $3 | Sprightly Scarab 3/1 T3 $3
  Hand: 1 cards

  → Board (7/7): 4/1, 4/1, 7/8, 2/3 [Taunt], 3/2 [DS], 3/2, 4/3
  → Tier 3→4 | Gold 9→0 | Hand 1→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=20 Armor=0 Gold=9 Tier=3

  Board (7/7): 4/1, 4/1, 1/1 [DS], 10/2, 10/2, 3/4, 2/4 [Taunt]
  Tavern (4 items): Sprightly Scarab 3/1 T3 $3 | Leeching Felhound 3/3 T3 $3 | Floating Watcher 4/4 T3 $5 | Technical Element 5/6 T3 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 4/1, 10/2, 10/2, 3/4, 2/4 [Taunt], 5/6
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=1 Gold=9 Tier=3

  Board (6/7): 3/1 [Taunt,Reborn], 1/1 [DS], 3/1 [Taunt,Reborn], 4/3, 2/4, 3/4
  Tavern (4 items): Mummifier 6/2 T3 $3 | Sewer Rat 3/2 T2 $3 | Old Soul 4/4 T2 $3 | Mummifier 6/2 T3 $3
  Hand: 0 cards

  → Board (7/7): 3/1 [Taunt,Reborn], 1/1 [DS], 3/1 [Taunt,Reborn], 4/3, 2/4, 3/4, 6/2
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=5 Gold=9 Tier=3

  Board (7/7): 5/8, 6/4, 2/2 [Taunt], 5/2, 6/4, 3/3, 1/1
  Tavern (4 items): Deep Blue Crooner 2/2 T3 $3 | Ominous Seer 2/1 T1 $3 | Deep Blue Crooner 2/2 T3 $3 | Hardy Orca 1/6 T3 $3
  Hand: 0 cards

  → Board (7/7): 5/8, 6/4, 2/2 [Taunt], 5/2, 6/4, 3/3, 1/6 [Taunt]
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Combat Phase**

  [heur] Drek'Thar vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Drek'Thar: [5/8, 6/4, 2/2, 5/2, 6/4, 3/3, 1/6]
     Inge, the Iron Hymn: [4/1, 4/1, 7/8, 2/3, 3/2, 3/2, 4/3]
     Manasaber 4/1→4/0 DEAD  |  Hardy Orca 1/6→1/2
     Wrath Weaver 5/8→5/6  |  Half-Shell 2/3→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Hardy Orca 1/2→1/0 DEAD
     Ancestral Automaton 6/4→6/1  |  Reef Riffer 3/2→3/0 DEAD
     Old Soul 7/8→7/6  |  Alert Alarmist 2/2→2/0 DEAD
     Mummifier 5/2→5/0 DEAD  |  Deflect-o-Bot 3/2→3/2
     Deflect-o-Bot 3/2→3/0 DEAD  |  Wrath Weaver 5/6→5/3
     Ancestral Automaton 6/4→6/0 DEAD  |  Old Soul 7/6→7/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Ancestral Automaton 6/1→6/0 DEAD
     Result: 2 vs 0 — heur
  [heur] Professor Putricide vs [heur] Sneed (first: Professor Putricide)
     Professor Putricide: [4/1, 4/1, 10/2, 10/2, 3/4, 2/4, 5/6]
     Sneed: [4/1, 4/4, 3/4, 2/6, 3/3, 4/2, 4/4]
     Manasaber 4/1→4/0 DEAD  |  Sprightly Scarab 4/2→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Module 2/4→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Shell Collector 4/4→4/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Eternal Knight 10/2→11/0 DEAD
     Eternal Knight 11/2→12/0 DEAD  |  Dustbone Devastator 2/6→2/0 DEAD
     Leeching Felhound 3/3→3/0 DEAD  |  Ancestral Automaton 3/4→3/1
     Ancestral Automaton 3/1→3/0 DEAD  |  Shell Collector 4/4→4/1
     Shell Collector 4/1→4/0 DEAD  |  Technical Element 5/6→5/2
     Result: 1 vs 0 — heur
  [heur] Sylvanas Windrunner vs [heur] Ysera (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [3/1, 1/1, 3/1, 4/3, 2/4, 3/4, 6/2]
     Ysera: [6/6, 4/4, 4/2, 2/1, 2/8, 5/2, 2/5]
     Risen Rider 3/1→3/0 DEAD  |  Tide Raiser 2/1→2/0 DEAD
     Scarlet Survivor 6/6→7/4  |  Risen Rider 3/1→3/0 DEAD
     Cord Puller 1/1→1/1  |  Mummifier 5/2→5/1
     Sklibb, Demon Hunter 4/4→4/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Nerubian Deathswarmer 2/4→2/0 DEAD  |  Mummifier 5/1→5/0 DEAD
     Metallic Hunter 4/2→4/0 DEAD  |  Mummifier 6/2→6/0 DEAD
     Ancestral Automaton 3/6→3/3  |  Roaring Recruiter 3/10→3/7
     Roaring Recruiter 3/7→4/7  |  Cord Puller 1/1→1/0 DEAD
     Result: 1 vs 3 — heur
  [heur] Overlord Saurfang vs [AGENT] Yogg-Saron, Hope's End (first: Overlord Saurfang)
     Overlord Saurfang: [13/19, 2/4, 10/11, 10/9, 15/16, 13/14, 17/19]
     Yogg-Saron, Hope's End: [4/1, 4/1, 1/2, 1/4]
     Wrath Weaver 13/19→13/18  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Taunt Test Minion 2/4→2/0 DEAD
     Old Soul 10/11→10/10  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Module 17/19→17/19
     Sewer Rat 10/9→10/8  |  Wrath Weaver 1/4→1/0 DEAD
     Result: 6 vs 0 — heur

  Alive: 8/8
  HP: Overlord Saurfang (HP=30, Tier=4) | Ysera (HP=30, Tier=4) | Sylvanas Windrunner (HP=30, Tier=4) | Drek'Thar (HP=30, Tier=4) | Sneed (HP=27, Tier=4) | Inge, the Iron Hymn (HP=27, Tier=4) | Professor Putricide (HP=20, Tier=4) | Yogg-Saron, Hope's End (HP=14, Tier=1)

### Turn 8

**Yogg-Saron, Hope's End** [RL AGENT]  HP=14 Armor=0 Gold=10 Tier=1

  Board (4/7): 4/1, 4/1, 1/2 [Taunt,DS], 1/4
  Tavern (4 items): Risen Rider 2/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Pointy Arrow (spell) T1 $1
  Hand: 0 cards

  → Board (5/7): 4/1, 4/1, 1/2 [Taunt,DS], 1/4, 1/2 [Taunt,DS]
  → Tier 1→2 | Gold 10→6
  → Actions: buy_tavern_1, play_hand_0, upgrade

**Sneed** [Heuristic]  HP=27 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/1, 4/3, 3/4, 2/6, 3/3, 4/2 [Reborn], 4/3
  Tavern (6 items): Cadaver Caretaker 3/3 T3 $3 | Reef Riffer 3/2 T2 $3 | Annoy-o-Module 2/4 T3 $3 | Tide Raiser 2/1 T2 $3 | Imposing Percussionist 4/4 T4 $3 | Back to Back (spell) T4 $1
  Hand: 1 cards

  → Board (7/7): 4/3, 3/4, 2/6, 4/3, 4/4, 2/4 [Taunt,DS], 2/1 [Taunt]
  → Gold 10→0 | HP 27→25 | Hand 1→2
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=10 Tier=4

  Board (7/7): 13/19 [G], 2/4 [Taunt], 10/11, 10/9, 15/16, 13/14, 17/19 [Taunt,DS]
  Tavern (6 items): Marquee Ticker 20/24 T4 $3 | Rylak Metalhead 22/20 T4 $3 | Flaming Enforcer 21/22 T4 $3 | Scarlet Skull 19/18 T2 $3 | Flaming Enforcer 21/22 T4 $3 | Defender's Rites (spell) T4 $2
  Hand: 0 cards

  → Board (7/7): 17/23 [G], 17/19 [Taunt,DS], 20/24, 21/22, 21/22, 22/20 [Taunt], 19/18 [Reborn]
  → Gold 10→0 | Armor 17→15
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=3 Gold=10 Tier=4

  Board (7/7): 6/6 [G], 4/4, 4/2, 2/1 [Taunt], 2/8, 5/2, 2/5
  Tavern (7 items): Flaming Enforcer 4/5 T4 $3 | Sewer Rat 3/2 T2 $3 | Accord-o-Tron 3/3 T3 $3 | Waverider 2/8 T4 $3 | Dustbone Devastator 2/6 T3 $3 | Easterly Winds (spell) T4 $1 | Prized Promo-Drake 1/1 T4 $3
  Hand: 1 cards

  → Board (7/7): 6/6 [G], 4/4, 2/8, 2/8, 4/5, 2/6, 3/2
  → Gold 10→0 | Hand 1→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=27 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/1, 4/1, 7/8, 2/3 [Taunt], 3/2 [DS], 3/2, 4/3
  Tavern (6 items): Lava Lurker 2/5 T2 $3 | Deflect-o-Bot 3/2 T3 $3 | Trigore the Lasher 9/3 T4 $3 | Accord-o-Tron 3/3 T3 $3 | Cord Puller 1/1 T1 $3 | Forest's Bounty (spell) T4 $3
  Hand: 1 cards

  → Board (7/7): 7/8, 4/3, 9/3, 2/5, 3/3, 3/2 [DS], 5/5 [DS]
  → Gold 10→0 | Hand 1→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=20 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/1, 4/1, 12/2, 12/2, 3/4, 2/4 [Taunt], 5/6
  Tavern (6 items): Seafloor Recruiter 3/5 T4 $3 | Deflect-o-Bot 3/2 T3 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Hardy Orca 1/6 T3 $3 | Monstrous Macaw 5/4 T4 $3 | Conflagration (spell) T4 $2
  Hand: 0 cards

  → Board (7/7): 12/2, 12/2, 5/6, 5/4, 3/5, 1/6 [Taunt], 2/4
  → Gold 10→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=1 Gold=10 Tier=4

  Board (7/7): 3/1 [Taunt,Reborn], 1/1, 3/1 [Taunt,Reborn], 4/3, 2/4, 3/4, 6/2
  Tavern (6 items): Trigore the Lasher 9/3 T4 $3 | Abyssal Bruiser 1/1 T4 $3 | Seafloor Recruiter 3/5 T4 $3 | Annoy-o-Module 2/4 T3 $3 | Friendly Geist 7/3 T4 $3 | Misplaced Tea Set (spell) T4 $2
  Hand: 0 cards

  → Board (7/7): 2/4, 3/4, 6/2, 9/3, 7/3, 3/5, 1/1 [DS]
  → Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=5 Gold=10 Tier=4

  Board (7/7): 5/8, 6/4, 2/2 [Taunt], 5/2, 6/4, 3/3, 1/6 [Taunt]
  Tavern (6 items): Hardy Orca 1/6 T3 $3 | Old Soul 3/4 T2 $3 | Stomping Stegodon 4/4 T4 $3 | Zesty Shaker 6/7 T4 $3 | Holo Rover 4/4 T4 $3 | Boon of Beetles (spell) T4 $1
  Hand: 0 cards

  → Board (7/7): 5/8, 6/4, 6/4, 6/7, 4/4, 4/4 [DS], 3/4
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Sylvanas Windrunner vs [AGENT] Yogg-Saron, Hope's End (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [2/4, 3/4, 6/2, 9/3, 7/3, 3/5, 1/1]
     Yogg-Saron, Hope's End: [4/1, 4/1, 1/2, 1/4, 1/2]
     Nerubian Deathswarmer 2/4→2/3  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Mummifier 6/2→6/0 DEAD
     Ancestral Automaton 3/4→3/3  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Friendly Geist 7/3→7/0 DEAD
     Trigore the Lasher 9/3→9/2  |  Annoy-o-Tron 1/2→1/2
     Wrath Weaver 1/4→1/0 DEAD  |  Trigore the Lasher 9/2→9/1
     Seafloor Recruiter 3/5→3/4  |  Annoy-o-Tron 1/2→1/0 DEAD
     Result: 5 vs 0 — heur
  [heur] Sneed vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Sneed: [4/4, 3/4, 2/6, 4/4, 4/4, 2/4, 2/2]
     Overlord Saurfang: [17/23, 17/19, 20/24, 21/22, 21/22, 22/20, 19/18]
     Wrath Weaver 17/23→17/21  |  Tide Raiser 2/2→2/0 DEAD
     Shell Collector 4/4→4/0 DEAD  |  Rylak Metalhead 22/20→22/16
     Annoy-o-Module 17/19→17/19  |  Annoy-o-Module 3/6→3/6
     Laboratory Assistant 3/4→3/0 DEAD  |  Rylak Metalhead 22/16→22/13
     Marquee Ticker 20/24→20/21  |  Annoy-o-Module 3/6→3/0 DEAD
     Dustbone Devastator 2/6→3/0 DEAD  |  Rylak Metalhead 22/13→22/11
     Flaming Enforcer 21/22→21/18  |  Imposing Percussionist 4/4→4/0 DEAD
     Shell Collector 4/4→4/0 DEAD  |  Rylak Metalhead 22/11→22/7
     Result: 0 vs 7 — heur
  [heur] Inge, the Iron Hymn vs [heur] Professor Putricide (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [7/8, 4/3, 9/3, 2/5, 3/3, 3/2, 5/5]
     Professor Putricide: [12/2, 12/2, 5/6, 5/4, 3/5, 1/6, 2/4]
     Old Soul 7/8→7/7  |  Hardy Orca 1/6→1/0 DEAD
     Eternal Knight 12/2→13/0 DEAD  |  Old Soul 7/7→7/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Technical Element 5/6→5/2
     Eternal Knight 13/2→14/0 DEAD  |  Deflect-o-Bot 3/2→3/2
     Trigore the Lasher 9/3→9/1  |  Nerubian Deathswarmer 2/4→2/0 DEAD
     Technical Element 5/2→5/0 DEAD  |  Cord Puller 5/5→5/5
     Lava Lurker 2/5→2/0 DEAD  |  Monstrous Macaw 5/4→5/2
     Monstrous Macaw 5/2→5/0 DEAD  |  Cord Puller 5/5→5/0 DEAD
     Accord-o-Tron 3/3→3/0 DEAD  |  Seafloor Recruiter 3/5→3/2
     Seafloor Recruiter 3/2→3/0 DEAD  |  Deflect-o-Bot 3/2→3/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Ysera vs [heur] Drek'Thar (first: Ysera)
     Ysera: [6/6, 4/4, 2/8, 2/8, 5/6, 2/6, 3/2]
     Drek'Thar: [5/8, 6/4, 6/4, 6/7, 4/4, 4/4, 3/4]
     Scarlet Survivor 6/6→7/2  |  Wrath Weaver 5/8→5/2
     Wrath Weaver 5/2→5/0 DEAD  |  Roaring Recruiter 2/8→2/3
     Sklibb, Demon Hunter 4/4→4/0 DEAD  |  Ancestral Automaton 6/4→6/0 DEAD
     Ancestral Automaton 6/4→6/0 DEAD  |  Flaming Enforcer 5/6→5/0 DEAD
     Roaring Recruiter 2/3→3/0 DEAD  |  Stomping Stegodon 4/4→4/2
     Zesty Shaker 6/7→6/5  |  Dustbone Devastator 2/6→2/0 DEAD
     Waverider 2/8→2/4  |  Holo Rover 4/4→4/4
     Stomping Stegodon 4/2→4/0 DEAD  |  Waverider 2/4→2/0 DEAD
     Sewer Rat 3/2→3/0 DEAD  |  Old Soul 3/4→3/1
     Holo Rover 4/4→4/0 DEAD  |  Scarlet Survivor 7/2→7/0 DEAD
     Result: 0 vs 2 — heur

  **Yogg-Saron, Hope's End [AGENT] eliminated!** (Turn 8)
  Alive: 7/8
  HP: Overlord Saurfang (HP=30, Tier=4) | Sylvanas Windrunner (HP=30, Tier=4) | Drek'Thar (HP=30, Tier=4) | Inge, the Iron Hymn (HP=27, Tier=4) | Ysera (HP=23, Tier=4) | Professor Putricide (HP=12, Tier=4) | Sneed (HP=10, Tier=4)

### Turn 9

**Sneed** [Heuristic]  HP=10 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/3, 3/4, 3/6, 4/3, 4/4, 2/4 [Taunt,DS], 2/1 [Taunt]
  Tavern (6 items): Ominous Seer 2/1 T1 $3 | Holo Rover 4/4 T4 $3 | Cadaver Caretaker 4/3 T3 $3 | Scarlet Skull 3/1 T2 $3 | False Implicator 1/1 T3 $3 | Tavern Coin (spell) T1 $3
  Hand: 3 cards

  → Board (7/7): 4/3, 3/4, 3/6, 4/3, 4/4, 2/4 [Taunt,DS], 5/6
  → Tier 4→5 | Gold 10→0 | Trinket: Charming Panpipes | Hand 3→2
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=10 Tier=4

  Board (7/7): 17/23 [G], 17/19 [Taunt,DS], 20/24, 21/22, 21/22, 22/20 [Taunt], 19/18 [Reborn]
  Tavern (6 items): Monstrous Macaw 31/30 T4 $3 | Sewer Rat 29/28 T2 $3 | Waverider 28/34 T4 $3 | Deep-Sea Angler 28/29 T3 $3 | Holo Rover 30/30 T4 $3 | Pointy Arrow (spell) T1 $1
  Hand: 1 cards

  → Board (7/7): 17/23 [G], 20/24, 21/22, 21/22, 22/20 [Taunt], 19/18 [Reborn], 28/34
  → Tier 4→5 | Gold 10→0 | Trinket: S'Thara Sticker
  → Actions: (auto)

**Ysera** [Heuristic]  HP=23 Armor=0 Gold=10 Tier=4

  Board (7/7): 6/6 [G], 4/4, 2/8, 2/8, 5/6, 2/6, 3/2
  Tavern (7 items): Rylak Metalhead 5/3 T4 $3 | Woodland Defiler 5/6 T4 $3 | Rimescale Priestess 3/3 T4 $3 | Floating Watcher 4/4 T3 $5 | Nerubian Deathswarmer 1/4 T2 $3 | Sick Riffs (spell) T1 $3 | Amber Guardian 3/2 T3 $3
  Hand: 1 cards

  → Board (7/7): 6/6 [G], 4/4, 2/8, 4/10 [WF], 5/6, 2/6, 5/6
  → Tier 4→5 | Gold 10→0 | Trinket: Chromatic Tear | Hand 1→2
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=27 Armor=0 Gold=11 Tier=4

  Board (7/7): 7/8, 4/3, 9/4, 2/5, 3/3, 3/2 [DS], 5/5 [DS]
  Tavern (6 items): Annoy-o-Module 2/4 T3 $3 | Annoy-o-Module 2/4 T3 $3 | Dustbone Devastator 2/6 T3 $3 | Sly Raptor 1/3 T3 $3 | Old Soul 3/4 T2 $3 | Tomb Turning (spell) T4 $2
  Hand: 0 cards

  → Board (7/7): 7/8, 4/3, 9/4, 2/5, 3/3, 5/5 [DS], 2/6
  → Tier 4→5 | Gold 11→0 | Trinket: Electrode Attractor
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=4

  Board (7/7): 14/2, 14/2, 5/6, 5/4, 3/5, 1/6 [Taunt], 2/4
  Tavern (6 items): Reef Riffer 3/2 T2 $3 | Monstrous Macaw 5/4 T4 $3 | Enchanted Sentinel 3/5 T4 $3 | Floating Watcher 4/4 T3 $5 | Nerubian Deathswarmer 2/4 T2 $3 | Arcane Absorption (spell) T4 $1
  Hand: 0 cards

  → Tier 4→5 | Gold 10→0 | Trinket: Unholy Sanctum
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=1 Gold=10 Tier=4

  Board (7/7): 2/4, 3/4, 6/2, 9/5, 7/3, 3/5, 1/1 [DS]
  Tavern (6 items): Cadaver Caretaker 4/3 T3 $3 | Deflect-o-Bot 3/2 T3 $3 | Lava Lurker 2/5 T2 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Banana Slamma 3/6 T4 $3 | Eonar's Favor (spell) T4 $2
  Hand: 0 cards

  → Tier 4→5 | Gold 10→0 | Trinket: Jarred Frostling
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=5 Gold=10 Tier=4

  Board (7/7): 5/8, 6/4, 6/4, 6/7, 4/4, 4/4 [DS], 3/4
  Tavern (6 items): Sewer Rat 3/2 T2 $3 | Humming Bird 1/4 T2 $3 | Humming Bird 1/4 T2 $3 | Seafloor Recruiter 3/5 T4 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Shifting Tide (spell) T4 $1
  Hand: 1 cards

  → Board (7/7): 7/10, 6/4, 6/4, 6/7, 4/4, 4/4 [DS], 5/4
  → Tier 4→5 | Gold 10→0 | Armor 5→4 | Trinket: Drakkari Portrait | Hand 1→2
  → Actions: (auto)

**Combat Phase**

  [heur] Sylvanas Windrunner vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Sylvanas Windrunner: [2/4, 3/4, 6/2, 9/5, 7/3, 3/5, 1/1]
     Inge, the Iron Hymn: [7/8, 4/3, 9/4, 2/5, 3/3, 5/5, 2/6]
     Old Soul 7/8→7/0 DEAD  |  Trigore the Lasher 9/5→9/0 DEAD
     Nerubian Deathswarmer 2/4→2/2  |  Dustbone Devastator 2/6→2/4
     Shell Collector 4/3→4/0 DEAD  |  Seafloor Recruiter 3/5→3/1
     Ancestral Automaton 3/4→3/0 DEAD  |  Cord Puller 5/5→5/5
     Trigore the Lasher 9/4→9/0 DEAD  |  Friendly Geist 7/3→7/0 DEAD
     Mummifier 6/2→6/0 DEAD  |  Lava Lurker 2/5→2/0 DEAD
     Accord-o-Tron 3/3→3/0 DEAD  |  Seafloor Recruiter 3/1→3/0 DEAD
     Abyssal Bruiser 1/5→1/5  |  Dustbone Devastator 2/4→2/3
     Cord Puller 5/5→5/4  |  Abyssal Bruiser 1/5→1/0 DEAD
     Result: 1 vs 2 — heur
  [heur] Ysera vs [heur] Sneed (first: Ysera)
     Ysera: [6/6, 4/4, 2/8, 4/10, 9/10, 2/6, 5/6]
     Sneed: [7/7, 3/4, 3/6, 4/4, 4/4, 2/4, 5/6]
     Scarlet Survivor 6/6→7/5  |  Annoy-o-Module 2/4→2/4
     Shell Collector 7/7→7/5  |  Roaring Recruiter 2/8→2/1
     Sklibb, Demon Hunter 4/4→4/2  |  Annoy-o-Module 2/4→2/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Waverider 4/10→4/7
     Roaring Recruiter 2/1→3/0 DEAD  |  Shell Collector 7/5→7/3
     Dustbone Devastator 3/6→4/4  |  Dustbone Devastator 2/6→2/3
     Waverider 4/7→4/3  |  Dustbone Devastator 4/4→4/0 DEAD
     Shell Collector 4/4→4/0 DEAD  |  Woodland Defiler 5/6→5/2
     Waverider 4/3→4/0 DEAD  |  Shell Collector 7/3→7/0 DEAD
     Imposing Percussionist 4/4→4/0 DEAD  |  Flaming Enforcer 9/10→9/6
     Flaming Enforcer 9/6→9/1  |  Technical Element 5/6→5/0 DEAD
     Result: 5 vs 0 — heur
  [heur] Professor Putricide vs [heur] Drek'Thar (first: Professor Putricide)
     Professor Putricide: [14/2, 14/2, 5/6, 5/4, 3/5, 1/6, 2/4]
     Drek'Thar: [7/10, 6/4, 6/4, 6/7, 4/4, 4/4, 5/4]
     Eternal Knight 14/2→15/0 DEAD  |  Wrath Weaver 7/10→7/0 DEAD
     Ancestral Automaton 6/4→6/3  |  Hardy Orca 1/6→1/0 DEAD
     Eternal Knight 15/2→16/0 DEAD  |  Zesty Shaker 6/7→6/0 DEAD
     Ancestral Automaton 6/4→6/1  |  Seafloor Recruiter 3/5→3/0 DEAD
     Technical Element 5/6→5/2  |  Holo Rover 4/4→4/4
     Stomping Stegodon 4/4→4/0 DEAD  |  Technical Element 5/2→5/0 DEAD
     Monstrous Macaw 5/4→5/0 DEAD  |  Malchezaar, Prince of Dance 5/4→5/0 DEAD
     Holo Rover 4/4→4/2  |  Nerubian Deathswarmer 2/4→2/0 DEAD
     Result: 0 vs 3 — heur

  **Sneed [Heuristic] eliminated!** (Turn 9)
  **Professor Putricide [Heuristic] eliminated!** (Turn 9)
  Alive: 5/8
  HP: Overlord Saurfang (HP=30, Tier=5) | Sylvanas Windrunner (HP=30, Tier=5) | Drek'Thar (HP=30, Tier=5) | Inge, the Iron Hymn (HP=27, Tier=5) | Ysera (HP=23, Tier=5)

### Turn 10

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=10 Tier=5

  Board (7/7): 17/23 [G], 20/24, 52/54, 51/53, 22/20 [Taunt], 19/18 [Reborn], 28/34
  Tavern (6 items): Sewer Rat 30/29 T2 $3 | Laboratory Assistant 30/31 T2 $3 | Floating Watcher 31/31 T3 $5 | Tranquil Meditative 30/35 T5 $3 | Ashen Corruptor 33/33 T5 $3 | Undersea Mount (spell) T1 $3
  Hand: 3 cards

  → Board (7/7): 52/54, 51/53, 28/34, 33/33, 30/35, 33/33, 30/31
  → Gold 10→0 | Armor 15→14 | Hand 3→1
  → Actions: (auto)

**Ysera** [Heuristic]  HP=23 Armor=0 Gold=10 Tier=5

  Board (7/7): 6/6 [G], 4/4, 2/8, 4/10 [WF], 9/10, 2/6, 5/6
  Tavern (7 items): Zesty Shaker 6/7 T4 $3 | Tranquil Meditative 3/8 T5 $3 | Eternal Knight 4/2 T2 $3 | Deep Blue Crooner 2/2 T3 $3 | Glowscale 4/6 T5 $3 | Bargain Bundle (spell) T5 $5 | Kalecgos, Arcane Aspect 4/12 T5 $3
  Hand: 3 cards

  → Board (7/7): 6/6 [G], 4/10 [WF], 9/10, 6/14, 6/7, 3/8, 4/2
  → Gold 10→0 | Hand 3→2
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=27 Armor=0 Gold=11 Tier=5

  Board (7/7): 7/8, 4/3, 9/5, 2/5, 3/3, 5/5 [DS], 2/6
  Tavern (6 items): Imposing Percussionist 4/4 T4 $3 | Sprightly Scarab 3/1 T3 $3 | Shadowdancer 5/3 T5 $3 | Abyssal Bruiser 1/1 T4 $3 | Skeletal Strafer 6/6 T5 $3 | Hired Headhunter (spell) T5 $3
  Hand: 0 cards

  → Board (7/7): 7/8, 10/6 [Reborn], 5/5 [DS], 6/6, 4/4, 5/3 [Taunt], 1/1 [DS]
  → Gold 11→0 | HP 27→24 | Hand 0→1
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=1 Gold=10 Tier=5

  Board (7/7): 2/4, 3/4, 6/2, 9/6, 7/3, 3/5, 1/1 [DS]
  Tavern (6 items): Laboratory Assistant 3/4 T2 $3 | Sinrunner Blanchy 9/8 T5 $3 | Rimescale Priestess 3/3 T4 $3 | Enchanted Sentinel 3/5 T4 $3 | Auto Assembler 2/2 T4 $3 | Saloon's Finest (spell) T5 $2
  Hand: 0 cards

  → Board (7/7): 6/2, 9/6, 7/3, 3/5, 9/8 [Reborn], 3/5, 2/2
  → Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=4 Gold=10 Tier=5

  Board (7/7): 7/10, 6/4, 6/4, 6/7, 4/4, 4/4 [DS], 5/4
  Tavern (6 items): Ancestral Automaton 6/4 T2 $3 | Accord-o-Tron 3/3 T3 $3 | Auto Assembler 2/2 T4 $3 | Wyvern Outrider 2/8 T4 $3 | Charging Czarina 4/1 T5 $3 | Corrupted Cupcakes (spell) T5 $4
  Hand: 3 cards

  → Board (7/7): 7/10, 6/7, 4/4 [DS], 5/4, 9/6 [G], 2/8, 4/1 [DS]
  → Gold 10→0 | Hand 3→4
  → Actions: (auto)

**Combat Phase**

  [heur] Inge, the Iron Hymn vs [heur] Overlord Saurfang (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [9/10, 12/8, 7/7, 8/8, 6/6, 7/5, 1/3]
     Overlord Saurfang: [82/83, 51/53, 28/34, 33/33, 30/35, 33/33, 30/31]
     Old Soul 9/10→9/0 DEAD  |  Tranquil Meditative 30/35→30/26
     Flaming Enforcer 82/83→82/76  |  Shadowdancer 7/5→7/0 DEAD
     Trigore the Lasher 12/8→12/0 DEAD  |  Tranquil Meditative 30/26→30/14
     Flaming Enforcer 51/53→51/52  |  Abyssal Bruiser 1/3→1/3
     Cord Puller 7/7→7/7  |  Floating Watcher 33/33→33/26
     Waverider 28/34→28/33  |  Abyssal Bruiser 1/3→1/0 DEAD
     Skeletal Strafer 8/8→8/0 DEAD  |  Laboratory Assistant 30/31→30/23
     Ashen Corruptor 33/33→33/26  |  Cord Puller 7/7→7/0 DEAD
     Imposing Percussionist 6/6→6/0 DEAD  |  Flaming Enforcer 51/52→51/46
     Result: 0 vs 7 — heur
  [heur] Ysera vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Ysera: [6/6, 4/10, 11/12, 6/14, 6/7, 3/8, 4/2]
     Sylvanas Windrunner: [6/2, 9/6, 7/3, 3/5, 9/8, 3/5, 2/2]
     Mummifier 6/2→6/0 DEAD  |  Zesty Shaker 6/7→6/1
     Scarlet Survivor 6/6→7/4  |  Seafloor Recruiter 3/5→3/0 DEAD
     Trigore the Lasher 9/6→9/0 DEAD  |  Kalecgos, Arcane Aspect 6/14→6/5
     Waverider 4/10→4/6  |  Auto Assembler 4/4→4/0 DEAD
     Friendly Geist 7/3→7/0 DEAD  |  Scarlet Survivor 7/4→7/0 DEAD
     Waverider 4/6→4/0 DEAD  |  Sinrunner Blanchy 9/8→9/4
     Sinrunner Blanchy 9/4→9/0 DEAD  |  Eternal Knight 4/2→5/0 DEAD
     Flaming Enforcer 11/12→11/7  |  Enchanted Sentinel 5/7→5/0 DEAD
     Result: 4 vs 0 — heur

  Alive: 5/8
  HP: Overlord Saurfang (HP=30, Tier=5) | Drek'Thar (HP=30, Tier=5) | Ysera (HP=23, Tier=5) | Sylvanas Windrunner (HP=16, Tier=5) | Inge, the Iron Hymn (HP=9, Tier=5)

### Turn 11

**Overlord Saurfang** [Heuristic]  HP=30 Armor=14 Gold=10 Tier=5

  Board (7/7): 82/83, 51/53, 28/34, 33/33, 30/35, 33/33, 30/31
  Tavern (6 items): Tide Raiser 36/33 T2 $3 | Lurking Leviathan 37/40 T5 $3 | Leeching Felhound 37/35 T3 $3 | Tichondrius 37/38 T5 $3 | Imposing Percussionist 38/36 T4 $3 | Wave of Gold (spell) T5 $2
  Hand: 3 cards

  → Board (7/7): 82/83, 51/53, 28/34, 35/35, 30/35, 33/33, 37/40
  → Tier 5→6 | Gold 10→0 | Hand 3→1
  → Actions: (auto)

**Ysera** [Heuristic]  HP=23 Armor=0 Gold=10 Tier=5

  Board (7/7): 6/6 [G], 4/10 [WF], 11/12, 6/14, 6/7, 3/8, 5/2
  Tavern (7 items): Enchanted Sentinel 3/5 T4 $3 | Sinrunner Blanchy 8/8 T5 $3 | Glowscale 4/6 T5 $3 | Deflect-o-Bot 3/2 T3 $3 | Woodland Defiler 5/6 T4 $3 | Channel the Devourer (spell) T5 $4 | Tarecgosa 4/4 T2 $3
  Hand: 4 cards

  → Board (7/7): 6/6 [G], 4/10 [WF], 13/14, 6/14, 6/7, 3/8, 8/8 [Reborn]
  → Tier 5→6 | Gold 10→0 | Hand 4→2
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=9 Armor=0 Gold=10 Tier=5

  Board (7/7): 9/10, 12/9 [Reborn], 7/7 [DS], 8/8, 6/6, 7/5 [Taunt], 1/3 [DS]
  Tavern (6 items): Cadaver Caretaker 3/3 T3 $3 | Eternal Tycoon 4/8 T5 $3 | Bazaar Dealer 4/6 T5 $3 | Deep-Sea Angler 2/3 T3 $3 | Reef Riffer 3/2 T2 $3 | Upper Hand (spell) T5 $3
  Hand: 2 cards

  → Board (7/7): 9/10, 12/9 [Reborn], 7/7 [DS], 8/8, 6/6, 7/5 [Taunt], 4/8
  → Tier 5→6 | Gold 10→2 | Hand 2→1
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=16 Armor=0 Gold=10 Tier=5

  Board (7/7): 6/2, 9/7, 7/3, 3/5, 9/8 [Reborn], 3/5, 2/2
  Tavern (6 items): Wyvern Outrider 2/8 T4 $3 | Friendly Geist 7/3 T4 $3 | Bazaar Dealer 4/6 T5 $3 | Zesty Shaker 6/7 T4 $3 | Risen Rider 3/1 T1 $3 | Contracted Corpse (spell) T5 $3
  Hand: 0 cards

  → Board (7/7): 6/2, 9/7, 7/3, 3/5, 9/8 [Reborn], 3/5, 6/7
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=4 Gold=10 Tier=5

  Board (7/7): 7/10, 6/7, 4/4 [DS], 5/4, 9/6 [G], 2/8, 4/1 [DS]
  Tavern (6 items): Eternal Tycoon 4/8 T5 $3 | Divine Sparkbot 4/2 T5 $3 | Charging Czarina 4/1 T5 $3 | Leeching Felhound 3/3 T3 $3 | Woodland Defiler 5/6 T4 $3 | Portal in a Crystal (spell) T5 $2
  Hand: 5 cards

  → Board (7/7): 7/10, 6/7, 4/4 [DS], 5/4, 9/6 [G], 2/8, 4/8
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Drek'Thar (first: Overlord Saurfang)
     Overlord Saurfang: [119/121, 89/89, 28/34, 35/35, 30/35, 33/33, 37/40]
     Drek'Thar: [7/10, 6/7, 4/4, 5/4, 9/6, 2/8, 4/8]
     Flaming Enforcer 119/121→119/119  |  Wyvern Outrider 2/8→2/0 DEAD
     Wrath Weaver 7/10→7/0 DEAD  |  Flaming Enforcer 89/89→89/82
     Flaming Enforcer 89/82→89/78  |  Eternal Tycoon 4/8→4/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Ashen Corruptor 35/35→35/29
     Waverider 28/34→28/30  |  Holo Rover 4/4→4/4
     Holo Rover 4/4→4/0 DEAD  |  Lurking Leviathan 37/40→37/36
     Ashen Corruptor 35/29→35/24  |  Malchezaar, Prince of Dance 5/4→5/0 DEAD
     Ancestral Automaton 9/6→9/0 DEAD  |  Waverider 28/30→28/21
     Result: 7 vs 0 — heur
  [heur] Ysera vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Ysera: [6/6, 4/10, 17/20, 6/14, 6/7, 3/8, 8/8]
     Inge, the Iron Hymn: [11/12, 14/11, 9/9, 10/10, 8/8, 9/7, 6/10]
     Old Soul 11/12→11/9  |  Tranquil Meditative 3/8→3/0 DEAD
     Scarlet Survivor 6/6→7/0 DEAD  |  Shadowdancer 9/7→9/1
     Trigore the Lasher 14/11→14/5  |  Zesty Shaker 6/7→6/0 DEAD
     Waverider 4/10→4/1  |  Shadowdancer 9/1→9/0 DEAD
     Cord Puller 9/9→9/9  |  Sinrunner Blanchy 8/8→8/0 DEAD
     Waverider 4/1→4/0 DEAD  |  Old Soul 11/9→11/5
     Skeletal Strafer 10/10→10/0 DEAD  |  Flaming Enforcer 17/20→17/10
     Flaming Enforcer 17/10→17/4  |  Eternal Tycoon 6/10→6/0 DEAD
     Imposing Percussionist 8/8→8/2  |  Kalecgos, Arcane Aspect 6/14→6/6
     Kalecgos, Arcane Aspect 6/6→7/0 DEAD  |  Old Soul 11/5→11/0 DEAD
     Result: 1 vs 3 — heur

  Alive: 5/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Ysera (HP=23, Tier=6) | Drek'Thar (HP=19, Tier=6) | Sylvanas Windrunner (HP=16, Tier=6) | Inge, the Iron Hymn (HP=9, Tier=6)

### Turn 12

**Overlord Saurfang** [Heuristic]  HP=30 Armor=14 Gold=10 Tier=6

  Board (7/7): 119/121, 89/89, 28/34, 35/35, 30/35, 33/33, 37/40
  Tavern (7 items): Sinrunner Blanchy 44/42 T5 $3 | Zesty Shaker 42/41 T4 $3 | Friendly Geist 42/37 T4 $3 | Skeletal Strafer 42/40 T5 $3 | P-0UL-TR-0N 46/44 T6 $3 | Woodland Defiler 41/40 T4 $3 | Knockoff Wisdomball (spell) T6 $4
  Hand: 3 cards

  → Board (7/7): 119/121, 89/89, 48/46, 44/42 [Reborn], 42/41, 42/40, 41/40
  → Gold 10→0 | Hand 3→1
  → Actions: (auto)

**Ysera** [Heuristic]  HP=23 Armor=0 Gold=10 Tier=6

  Board (7/7): 6/6 [G], 4/10 [WF], 17/20, 6/14, 6/7, 3/8, 8/8 [Reborn]
  Tavern (8 items): Auto Assembler 2/2 T4 $3 | Deathly Striker 8/8 T6 $3 | Darkcrest Strategist 4/5 T5 $3 | Plaguerunner 4/2 T4 $3 | Holo Rover 4/4 T4 $3 | Sewer Lord 4/6 T5 $3 | Lost Staff of Hamuul (spell) T6 $2 | Fire-forged Evoker 8/5 T6 $3
  Hand: 4 cards

  → Board (7/7): 4/10 [WF], 17/20, 8/16, 8/8 [Reborn], 8/8, 8/5, 4/4 [DS]
  → Gold 10→0 | Hand 4→2
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=9 Armor=0 Gold=10 Tier=6

  Board (7/7): 11/12, 14/12 [Reborn], 9/9 [DS], 10/10, 8/8, 9/7 [Taunt], 6/10
  Tavern (7 items): Drustfallen Butcher 2/7 T5 $3 | Lava Lurker 2/5 T2 $3 | Lurking Leviathan 3/8 T5 $3 | Reef Riffer 3/2 T2 $3 | Sprightly Scarab 3/1 T3 $3 | Glowscale 4/6 T5 $3 | Eyes of the Earth Mother (spell) T6 $4
  Hand: 2 cards

  → Board (7/7): 11/12, 14/12 [Reborn], 9/9 [DS], 10/10, 9/7 [Taunt], 6/10, 3/2
  → Gold 10→2 | Hand 2→1
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=16 Armor=0 Gold=10 Tier=6

  Board (7/7): 6/2, 9/8, 7/3, 3/5, 9/8 [Reborn], 3/5, 6/7
  Tavern (7 items): Rylak Metalhead 5/3 T4 $3 | Deflect-o-Bot 3/2 T3 $3 | Laboratory Assistant 3/4 T2 $3 | Monstrous Macaw 5/4 T4 $3 | Ancestral Automaton 6/4 T2 $3 | Tidemistress Athissa 6/7 T6 $3 | Meditation (spell) T1 $3
  Hand: 0 cards

  → Board (7/7): 9/8, 7/3, 9/8 [Reborn], 6/7, 6/7, 9/4, 3/4
  → Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=19 Armor=0 Gold=10 Tier=6

  Board (7/7): 7/10, 6/7, 4/4 [DS], 5/4, 9/6 [G], 2/8, 4/8
  Tavern (7 items): Deep Blue Crooner 2/2 T3 $3 | Forsaken Weaver 3/10 T6 $3 | Trigore the Lasher 9/3 T4 $3 | Sewer Rat 3/2 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Auto Assembler 2/2 T4 $3 | Undersea Mount (spell) T1 $3
  Hand: 4 cards

  → Board (7/7): 7/10, 6/7, 9/6 [G], 5/8, 4/10, 9/3, 2/2
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Sylvanas Windrunner (first: Overlord Saurfang)
     Overlord Saurfang: [162/159, 90/90, 49/47, 45/43, 43/42, 43/41, 42/41]
     Sylvanas Windrunner: [9/8, 7/3, 9/8, 6/7, 6/7, 9/4, 3/4]
     Flaming Enforcer 162/159→162/152  |  Friendly Geist 7/3→7/0 DEAD
     Trigore the Lasher 9/8→9/0 DEAD  |  Flaming Enforcer 90/90→90/81
     Flaming Enforcer 90/81→90/72  |  Sinrunner Blanchy 9/8→9/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Zesty Shaker 43/42→43/36
     P-0UL-TR-0N 49/47→49/38  |  Ancestral Automaton 9/4→9/0 DEAD
     Tidemistress Athissa 6/7→6/0 DEAD  |  Zesty Shaker 43/36→43/30
     Sinrunner Blanchy 45/43→45/38  |  Laboratory Assistant 5/6→5/0 DEAD
     Result: 7 vs 0 — heur
  [heur] Inge, the Iron Hymn vs [heur] Drek'Thar (first: Drek'Thar)
     Inge, the Iron Hymn: [13/14, 16/14, 11/11, 12/12, 11/9, 8/12, 5/4]
     Drek'Thar: [7/10, 6/7, 9/6, 5/8, 4/10, 9/3, 2/2]
     Wrath Weaver 7/10→7/0 DEAD  |  Shadowdancer 11/9→11/2
     Old Soul 13/14→13/5  |  Ancestral Automaton 9/6→9/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Shadowdancer 11/2→11/0 DEAD
     Trigore the Lasher 16/14→16/5  |  Trigore the Lasher 9/3→9/0 DEAD
     Eternal Tycoon 5/8→5/0 DEAD  |  Skeletal Strafer 12/12→12/7
     Cord Puller 11/11→11/11  |  Deep Blue Crooner 2/2→2/0 DEAD
     Forsaken Weaver 4/10→4/0 DEAD  |  Old Soul 13/5→13/1
     Result: 5 vs 0 — heur

  Alive: 5/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Ysera (HP=23, Tier=6) | Inge, the Iron Hymn (HP=9, Tier=6) | Drek'Thar (HP=4, Tier=6) | Sylvanas Windrunner (HP=1, Tier=6)

### Turn 13

**Overlord Saurfang** [Heuristic]  HP=30 Armor=14 Gold=10 Tier=6

  Board (7/7): 162/159, 90/90, 49/47, 45/43 [Reborn], 43/42, 43/41, 42/41
  Tavern (7 items): Batty Terrorguard 48/42 T6 $3 | Floating Watcher 46/44 T3 $5 | Famished Felbat 48/43 T5 $3 | Trigore the Lasher 51/43 T4 $3 | Dustbone Devastator 44/46 T3 $3 | Seafloor Recruiter 45/45 T4 $3 | Unmasked Identity (spell) T5 $3
  Hand: 1 cards

  → Board (7/7): 162/159, 90/90, 49/47, 51/43, 48/43, 48/42, 46/44
  → Gold 10→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=23 Armor=0 Gold=10 Tier=6

  Board (7/7): 4/10 [WF], 19/22, 8/16, 8/8 [Reborn], 8/8, 8/5, 4/4 [DS]
  Tavern (8 items): Woodland Defiler 5/6 T4 $3 | Divine Sparkbot 4/2 T5 $3 | Hunting Tiger Shark 3/5 T4 $3 | Eternal Tycoon 4/8 T5 $3 | Banana Slamma 3/6 T4 $3 | Rabid Panther 4/8 T6 $3 | Conflagration (spell) T4 $2 | Twilight Hatchling 1/1 T1 $3
  Hand: 5 cards

  → Board (7/7): 4/10 [WF], 19/22, 11/19, 8/8 [Reborn], 8/8, 9/6, 3/5
  → Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=9 Armor=0 Gold=10 Tier=6

  Board (7/7): 13/14, 16/15 [Reborn], 11/11 [DS], 12/12, 11/9 [Taunt], 8/12, 5/4
  Tavern (7 items): Groundbreaker 5/4 T6 $3 | Wyvern Outrider 2/8 T4 $3 | Imposing Percussionist 4/4 T4 $3 | Wrath Weaver 1/4 T1 $3 | Divine Sparkbot 4/2 T5 $3 | Junk Jouster 8/7 T6 $3 | Undersea Mount (spell) T1 $3
  Hand: 3 cards

  → Board (7/7): 13/14, 16/15 [Reborn], 11/11 [DS], 18/18, 11/9 [Taunt], 8/12, 4/2 [Taunt,DS]
  → Gold 10→2 | HP 9→8 | Hand 3→2
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=1 Armor=0 Gold=10 Tier=6

  Board (7/7): 9/9, 7/3, 9/8 [Reborn], 6/7, 6/7, 9/4, 3/4
  Tavern (7 items): Lurking Leviathan 3/8 T5 $3 | Iridescent Skyblazer 3/8 T5 $3 | Banana Slamma 3/6 T4 $3 | Accord-o-Tron 3/3 T3 $3 | Lurking Leviathan 3/8 T5 $3 | Flaming Enforcer 4/5 T4 $3 | Staff of Enrichment (spell) T3 $2
  Hand: 0 cards

  → Board (7/7): 9/9, 9/8 [Reborn], 6/7, 6/7, 9/4, 4/8, 4/5
  → Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=4 Armor=0 Gold=10 Tier=6

  Board (7/7): 7/10, 6/7, 9/6 [G], 5/8, 4/10, 9/4, 2/2
  Tavern (7 items): Sewer Lord 4/6 T5 $3 | Waverider 2/8 T4 $3 | Junk Jouster 8/7 T6 $3 | Falling Sky Golem 8/2 T6 $3 | Deathly Striker 9/8 T6 $3 | Rabid Panther 4/8 T6 $3 | Gem Confiscation (spell) T4 $1
  Hand: 4 cards

  → Board (7/7): 7/10, 9/6 [G], 5/8, 4/10, 9/8, 8/7, 2/8
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Ysera vs [heur] Drek'Thar (first: Ysera)
     Ysera: [4/10, 23/24, 18/33, 8/8, 8/8, 16/20, 3/5]
     Drek'Thar: [7/10, 9/6, 5/8, 4/10, 9/8, 8/7, 2/8]
     Waverider 4/10→4/5  |  Eternal Tycoon 5/8→5/4
     Wrath Weaver 7/10→7/0 DEAD  |  Kalecgos, Arcane Aspect 18/33→18/26
     Waverider 4/5→4/3  |  Waverider 2/8→2/4
     Ancestral Automaton 9/6→9/0 DEAD  |  Sinrunner Blanchy 8/8→8/0 DEAD
     Flaming Enforcer 23/24→23/15  |  Forsaken Weaver 4/10→4/0 DEAD
     Eternal Tycoon 5/4→5/0 DEAD  |  Fire-forged Evoker 16/20→16/15
     Kalecgos, Arcane Aspect 18/26→19/19  |  Junk Jouster 8/7→8/0 DEAD
     Deathly Striker 9/8→9/0 DEAD  |  Fire-forged Evoker 16/15→16/6
     Deathly Striker 8/8→8/6  |  Waverider 2/4→2/0 DEAD
     Result: 6 vs 0 — heur
  [heur] Sylvanas Windrunner vs [heur] Inge, the Iron Hymn (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [9/9, 9/8, 6/7, 6/7, 9/4, 4/8, 7/8]
     Inge, the Iron Hymn: [15/16, 18/17, 13/13, 20/20, 13/11, 10/14, 6/4]
     Trigore the Lasher 9/9→9/3  |  Divine Sparkbot 6/4→6/4
     Old Soul 15/16→15/9  |  Flaming Enforcer 7/8→7/0 DEAD
     Sinrunner Blanchy 9/8→9/2  |  Divine Sparkbot 6/4→6/0 DEAD
     Trigore the Lasher 18/17→18/12  |  Iridescent Skyblazer 5/9→5/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Shadowdancer 13/11→13/5
     Cord Puller 13/13→13/13  |  Ancestral Automaton 9/4→9/0 DEAD
     Tidemistress Athissa 6/7→6/0 DEAD  |  Shadowdancer 13/5→13/0 DEAD
     Skeletal Strafer 20/20→20/10  |  Trigore the Lasher 10/4→10/0 DEAD
     Result: 1 vs 5 — heur

  **Drek'Thar [Heuristic] eliminated!** (Turn 13)
  Alive: 4/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Ysera (HP=23, Tier=6) | Inge, the Iron Hymn (HP=8, Tier=6) | Sylvanas Windrunner (HP=1, Tier=6)

### Turn 14

**Overlord Saurfang** [Heuristic]  HP=30 Armor=14 Gold=10 Tier=6

  Board (7/7): 206/205, 135/135, 49/47, 51/44, 48/43, 48/42, 46/44
  Tavern (7 items): Zesty Shaker 54/53 T4 $3 | Nightmare Par-tea Guest 51/49 T5 $3 | Laboratory Assistant 51/50 T2 $3 | Famished Felbat 54/49 T5 $3 | Plaguerunner 52/48 T4 $3 | Moonsteel Juggernaut 56/54 T6 $3 | Queen's Command (spell) T5 $2
  Hand: 1 cards

  → Board (7/7): 258/253, 135/135, 56/54, 54/53, 54/49, 51/50, 51/49
  → Gold 10→0 | Hand 1→2
  → Actions: (auto)

**Ysera** [Heuristic]  HP=23 Armor=0 Gold=10 Tier=6

  Board (7/7): 4/10 [WF], 23/24, 11/19, 8/8 [Reborn], 8/8, 9/6, 3/5
  Tavern (8 items): Enchanted Sentinel 3/5 T4 $3 | Lurking Leviathan 3/8 T5 $3 | Seafloor Recruiter 3/5 T4 $3 | Sewer Rat 3/2 T2 $3 | Deathly Striker 8/8 T6 $3 | Annoy-o-Module 2/4 T3 $3 | Staff of Enrichment (spell) T3 $2 | Twilight Hatchling 1/1 T1 $3
  Hand: 8 cards

  → Board (7/7): 23/24, 13/21, 8/8 [Reborn], 8/8, 9/6, 8/8, 2/4 [Taunt,DS]
  → Gold 10→0 | Hand 8→7
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=8 Armor=0 Gold=10 Tier=6

  Board (7/7): 15/16, 18/18 [Reborn], 13/13 [DS], 20/20, 13/11 [Taunt], 10/14, 6/4 [Taunt,DS]
  Tavern (7 items): Tichondrius 3/6 T5 $3 | Shadowdancer 5/3 T5 $3 | Rimescale Priestess 3/3 T4 $3 | Sewer Lord 4/6 T5 $3 | Deflect-o-Bot 3/2 T3 $3 | Eternal Summoner 8/1 T6 $3 | Meditation (spell) T1 $3
  Hand: 4 cards

  → Board (7/7): 15/16, 18/18 [Reborn], 19/13 [DS], 20/20, 13/11 [Taunt], 10/14, 3/3
  → Gold 10→2 | Hand 4→2
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=1 Armor=0 Gold=10 Tier=6

  Board (7/7): 9/12, 9/8 [Reborn], 6/7, 6/7, 9/4, 4/8, 7/8
  Tavern (7 items): Tidemistress Athissa 6/7 T6 $3 | Scrap Scraper 6/5 T5 $3 | Ruthless Queensguard 3/3 T6 $3 | Marquee Ticker 3/7 T4 $3 | One-Amalgam Tour Group 7/7 T6 $3 | Monstrous Macaw 5/4 T4 $3 | Undersea Mount (spell) T1 $3
  Hand: 0 cards

  → Board (7/7): 13/16, 11/10 [Reborn], 7/8, 11/12, 8/8, 7/8, 6/5
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Overlord Saurfang: [258/253, 135/135, 56/54, 54/53, 54/49, 51/50, 51/49]
     Inge, the Iron Hymn: [17/18, 20/20, 21/15, 22/22, 15/13, 12/16, 5/5]
     Old Soul 17/18→17/0 DEAD  |  Famished Felbat 54/49→54/32
     Flaming Enforcer 258/253→258/238  |  Shadowdancer 15/13→15/0 DEAD
     Trigore the Lasher 20/20→20/0 DEAD  |  Zesty Shaker 54/53→54/33
     Flaming Enforcer 135/135→135/114  |  Cord Puller 21/15→21/15
     Cord Puller 21/15→21/0 DEAD  |  Nightmare Par-tea Guest 51/49→51/28
     Moonsteel Juggernaut 56/54→56/42  |  Eternal Tycoon 12/16→12/0 DEAD
     Skeletal Strafer 22/22→22/0 DEAD  |  Famished Felbat 54/32→54/10
     Zesty Shaker 54/33→54/28  |  Rimescale Priestess 5/5→5/0 DEAD
     Result: 7 vs 0 — heur
  [heur] Ysera vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Ysera: [26/26, 24/43, 8/8, 8/8, 20/28, 8/8, 2/4]
     Sylvanas Windrunner: [13/16, 11/10, 7/8, 14/15, 8/8, 7/8, 6/5]
     Trigore the Lasher 13/16→13/14  |  Annoy-o-Module 2/4→2/4
     Flaming Enforcer 26/26→26/15  |  Sinrunner Blanchy 11/10→11/0 DEAD
     Tidemistress Athissa 7/8→7/6  |  Annoy-o-Module 2/4→2/0 DEAD
     Kalecgos, Arcane Aspect 24/43→25/36  |  One-Amalgam Tour Group 8/8→8/0 DEAD
     Flaming Enforcer 15/16→15/0 DEAD  |  Kalecgos, Arcane Aspect 25/36→25/21
     Sinrunner Blanchy 8/8→8/1  |  Tidemistress Athissa 7/8→7/0 DEAD
     Monstrous Macaw 8/7→8/0 DEAD  |  Flaming Enforcer 26/15→26/7
     Deathly Striker 8/8→8/1  |  Tidemistress Athissa 7/6→7/0 DEAD
     Result: 6 vs 1 — heur

  **Inge, the Iron Hymn [Heuristic] eliminated!** (Turn 14)
  Alive: 3/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Ysera (HP=23, Tier=6) | Sylvanas Windrunner (HP=1, Tier=6)

### Turn 15

**Overlord Saurfang** [Heuristic]  HP=30 Armor=14 Gold=10 Tier=6

  Board (7/7): 258/253, 135/135, 56/54, 54/53, 54/49, 51/50, 51/49
  Tavern (7 items): Prosthetic Hand 56/52 T4 $3 | Imposing Percussionist 57/55 T4 $3 | Cadaver Caretaker 56/54 T3 $3 | Ancestral Automaton 3/4 T2 $3 | Famished Felbat 59/54 T5 $3 | Ancestral Automaton 3/4 T2 $3 | Misplaced Tea Set (spell) T4 $2
  Hand: 4 cards

  → Board (7/7): 258/253, 138/139, 56/54, 59/54, 57/55, 3/4, 1/1
  → Gold 10→0 | Armor 14→11
  → Actions: (auto)

**Ysera** [Heuristic]  HP=23 Armor=0 Gold=10 Tier=6

  Board (7/7): 26/26, 13/21, 8/8 [Reborn], 8/8, 9/6, 8/8, 2/4 [Taunt,DS]
  Tavern (8 items): Void Pup Trainer 7/7 T5 $3 | Cord Puller 1/1 T1 $3 | Scarlet Skull 2/1 T2 $3 | Stomping Stegodon 4/4 T4 $3 | Floating Watcher 4/4 T3 $5 | False Implicator 1/1 T3 $3 | Perfect Vision (spell) T6 $2 | Felfire Conjurer 6/5 T5 $3
  Hand: 7 cards

  → Board (7/7): 26/26, 14/22, 8/8 [Reborn], 8/8, 10/7, 8/8, 4/4
  → Gold 10→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=1 Armor=0 Gold=10 Tier=6

  Board (7/7): 13/18, 11/10 [Reborn], 7/8, 14/15, 8/8, 7/8, 6/5
  Tavern (7 items): Annoy-o-Module 2/4 T3 $3 | Metallic Hunter 4/2 T2 $3 | Shadowdancer 5/3 T5 $3 | Annoy-o-Module 2/4 T3 $3 | Void Pup Trainer 7/7 T5 $3 | False Implicator 1/1 T3 $3 | Undersea Mount (spell) T1 $3
  Hand: 0 cards

  → Board (7/7): 15/20, 13/12 [Reborn], 16/17, 8/8, 7/8, 9/9, 3/5 [Taunt,DS]
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Ysera (first: Overlord Saurfang)
     Overlord Saurfang: [258/253, 138/139, 56/54, 59/54, 57/55, 3/4, 1/1]
     Ysera: [27/27, 26/46, 8/8, 8/8, 22/31, 8/8, 4/4]
     Flaming Enforcer 258/253→258/226  |  Flaming Enforcer 27/27→27/0 DEAD
     Kalecgos, Arcane Aspect 26/46→27/44  |  Ancestral Automaton 3/4→3/0 DEAD
     Flaming Enforcer 138/139→138/112  |  Kalecgos, Arcane Aspect 27/44→27/0 DEAD
     Sinrunner Blanchy 8/8→8/0 DEAD  |  Flaming Enforcer 138/112→138/104
     Moonsteel Juggernaut 56/54→56/46  |  Deathly Striker 8/8→8/0 DEAD
     Deathly Striker 8/8→8/0 DEAD  |  Flaming Enforcer 138/104→138/96
     Famished Felbat 59/54→59/50  |  Floating Watcher 4/4→4/0 DEAD
     Fire-forged Evoker 22/31→23/0 DEAD  |  Flaming Enforcer 258/226→258/204
     Result: 6 vs 0 — heur

  **Overlord Saurfang [Heuristic] eliminated!** (Turn 15)
  **Ysera [Heuristic] eliminated!** (Turn 15)
  **Sylvanas Windrunner [Heuristic] eliminated!** (Turn 15)

---

## Final Standings

| # | Hero | Role | HP | Tier | Eliminated |
|---|---|---|---|---|---|
| 1 | Overlord Saurfang | Heuristic | 30 | 6 | 15 |
| 2 | Ysera | Heuristic | 0 | 6 | 15 |
| 3 | Sylvanas Windrunner | Heuristic | 0 | 6 | 15 |
| 4 | Inge, the Iron Hymn | Heuristic | 0 | 6 | 14 |
| 5 | Drek'Thar | Heuristic | 0 | 6 | 13 |
| 6 | Sneed | Heuristic | 0 | 5 | 9 |
| 7 | Professor Putricide | Heuristic | 0 | 5 | 9 |
| 8 | Yogg-Saron, Hope's End | AGENT | 0 | 2 | 8 |