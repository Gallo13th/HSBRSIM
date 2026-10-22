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

  → Board (2/7): 8/2 [G], 6/2
  → Tier 1→2 | Gold 6→3
  → Actions: upgrade, buy_tavern_1, play_hand_0, play_hand_0, sell_board_0

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

  [heur] Sylvanas Windrunner vs [heur] Overlord Saurfang (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [3/1, 1/1, 3/1, 4/3, 2/4]
     Overlord Saurfang: [13/19, 2/4, 10/11, 10/9]
     Risen Rider 3/1→3/0 DEAD  |  Taunt Test Minion 2/4→2/1
     Wrath Weaver 13/19→13/16  |  Risen Rider 3/1→3/0 DEAD
     Cord Puller 1/1→1/1  |  Taunt Test Minion 2/1→2/0 DEAD
     Old Soul 10/11→10/10  |  Cord Puller 1/1→1/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Old Soul 10/10→10/6
     Sewer Rat 10/9→10/7  |  Nerubian Deathswarmer 2/4→2/0 DEAD
     Result: 0 vs 3 — heur
  [heur] Inge, the Iron Hymn vs [heur] Ysera (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4, 3/2]
     Ysera: [6/6, 4/4, 4/2, 2/1]
     Manasaber 4/1→4/0 DEAD  |  Tide Raiser 2/1→2/0 DEAD
     Scarlet Survivor 6/6→6/5  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Sklibb, Demon Hunter 4/4→4/3
     Sklibb, Demon Hunter 4/3→4/0 DEAD  |  Old Soul 3/4→3/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Metallic Hunter 5/4→5/0 DEAD
     Result: 1 vs 1 — heur
  [heur] Professor Putricide vs [heur] Sneed (first: Professor Putricide)
     Professor Putricide: [4/1, 4/1, 1/1, 4/2, 4/2]
     Sneed: [2/1, 4/1, 4/1, 4/3, 3/4]
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Eternal Knight 4/2→5/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Shell Collector 4/3→4/2  |  Cord Puller 1/1→1/1
     Cord Puller 1/1→1/0 DEAD  |  Shell Collector 4/2→4/1
     Laboratory Assistant 3/4→3/0 DEAD  |  Eternal Knight 5/2→6/0 DEAD
     Result: 0 vs 1 — heur
  [heur] Drek'Thar vs [AGENT] Yogg-Saron, Hope's End (first: Drek'Thar)
     Drek'Thar: [2/1, 1/4, 1/2, 3/4, 2/2]
     Yogg-Saron, Hope's End: [8/2, 6/2]
     Risen Rider 2/1→2/0 DEAD  |  Manasaber 8/2→8/0 DEAD
     Festergut 6/2→6/1  |  Annoy-o-Tron 1/2→1/2
     Wrath Weaver 1/4→1/0 DEAD  |  Festergut 6/1→6/0 DEAD
     Result: 3 vs 0 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=2) | Sneed (HP=30, Tier=2) | Overlord Saurfang (HP=30, Tier=2) | Ysera (HP=30, Tier=2) | Inge, the Iron Hymn (HP=30, Tier=2) | Professor Putricide (HP=30, Tier=2) | Drek'Thar (HP=30, Tier=2) | Sylvanas Windrunner (HP=29, Tier=2)

### Turn 5

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=8 Gold=7 Tier=2

  Board (2/7): 8/2 [G], 6/2
  Tavern (5 items): Soul Rewinder 4/1 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Tavern Coin (spell) T1 $3
  Hand: 0 cards

  → Board (3/7): 8/2 [G], 6/2, 3/4
  → Gold 7→3
  → Actions: buy_tavern_2, play_hand_0, refresh

**Sneed** [Heuristic]  HP=30 Armor=7 Gold=7 Tier=2

  Board (5/7): 2/1, 4/1, 4/1, 4/3, 3/4
  Tavern (4 items): Manasaber 4/1 T1 $3 | Soul Rewinder 4/1 T2 $3 | Harmless Bonehead 1/1 T1 $3 | Laboratory Assistant 3/4 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=7 Tier=2

  Board (4/7): 13/19 [G], 2/4 [Taunt], 10/11, 10/9
  Tavern (4 items): Surf n' Surf 11/11 T1 $3 | Humming Bird 11/14 T2 $3 | Metallic Hunter 14/12 T2 $3 | Alert Alarmist 12/12 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=9 Gold=7 Tier=2

  Board (4/7): 6/6 [G], 4/4, 4/2, 2/1 [Taunt]
  Tavern (5 items): Shell Collector 4/3 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Ominous Seer 2/1 T1 $3 | Ancestral Automaton 3/4 T2 $3 | Tarecgosa 4/4 T2 $3
  Hand: 1 cards

  → Tier 2→3 | Gold 7→0 | Hand 1→0
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

**Sylvanas Windrunner** [Heuristic]  HP=29 Armor=0 Gold=7 Tier=2

  Board (5/7): 3/1 [Taunt,Reborn], 1/1 [DS], 3/1 [Taunt,Reborn], 4/3, 2/4
  Tavern (4 items): Humming Bird 1/4 T2 $3 | Reef Riffer 3/2 T2 $3 | Eternal Knight 4/2 T2 $3 | Lava Lurker 2/5 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=7 Tier=2

  Board (5/7): 2/1 [Taunt,Reborn], 1/4, 1/2 [Taunt,DS], 3/4, 2/2 [Taunt]
  Tavern (4 items): Sewer Rat 3/2 T2 $3 | Old Soul 3/4 T2 $3 | Tide Raiser 2/1 T2 $3 | Eternal Knight 4/2 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Combat Phase**

  [heur] Professor Putricide vs [heur] Drek'Thar (first: Professor Putricide)
     Professor Putricide: [4/1, 4/1, 1/1, 6/2, 6/2]
     Drek'Thar: [2/1, 1/4, 1/2, 3/4, 2/2]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Risen Rider 2/1→2/0 DEAD  |  Eternal Knight 6/2→7/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 1/4→1/0 DEAD  |  Eternal Knight 7/2→7/1
     Cord Puller 1/1→1/1  |  Alert Alarmist 2/2→2/1
     Ancestral Automaton 3/4→3/3  |  Cord Puller 1/1→1/0 DEAD
     Eternal Knight 7/1→8/0 DEAD  |  Alert Alarmist 2/1→2/0 DEAD
     Result: 0 vs 1 — heur
  [heur] Ysera vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Ysera: [6/6, 4/4, 4/2, 2/1]
     Overlord Saurfang: [13/16, 2/4, 10/11, 10/9]
     Wrath Weaver 13/16→13/14  |  Tide Raiser 2/1→2/0 DEAD
     Scarlet Survivor 6/6→6/4  |  Taunt Test Minion 2/4→2/0 DEAD
     Old Soul 10/11→10/5  |  Scarlet Survivor 6/4→6/0 DEAD
     Sklibb, Demon Hunter 4/4→4/0 DEAD  |  Wrath Weaver 13/14→13/10
     Sewer Rat 10/9→10/4  |  Metallic Hunter 5/4→5/0 DEAD
     Result: 0 vs 3 — heur
  [heur] Sneed vs [heur] Inge, the Iron Hymn (first: Sneed)
     Sneed: [2/1, 4/1, 4/1, 4/3, 3/4]
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4, 3/2]
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Laboratory Assistant 3/4→3/1  |  Sewer Rat 3/2→3/0 DEAD
     Old Soul 3/4→3/1  |  Laboratory Assistant 3/1→3/0 DEAD
     Result: 0 vs 1 — heur
  [heur] Sylvanas Windrunner vs [AGENT] Yogg-Saron, Hope's End (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [3/1, 1/1, 3/1, 4/3, 2/4]
     Yogg-Saron, Hope's End: [8/2, 6/2, 3/4]
     Risen Rider 3/1→3/0 DEAD  |  Laboratory Assistant 3/4→3/1
     Manasaber 8/2→8/0 DEAD  |  Risen Rider 3/1→3/0 DEAD
     Cord Puller 1/1→1/1  |  Laboratory Assistant 3/1→3/0 DEAD
     Festergut 6/2→6/1  |  Cord Puller 1/1→1/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Festergut 6/1→6/0 DEAD
     Result: 1 vs 0 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=2) | Sneed (HP=30, Tier=3) | Overlord Saurfang (HP=30, Tier=3) | Ysera (HP=30, Tier=3) | Inge, the Iron Hymn (HP=30, Tier=3) | Drek'Thar (HP=30, Tier=3) | Professor Putricide (HP=29, Tier=3) | Sylvanas Windrunner (HP=29, Tier=3)

### Turn 6

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=3 Gold=8 Tier=2

  Board (3/7): 8/2 [G], 6/2, 3/4
  Tavern (4 items): Reef Riffer 3/2 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Metallic Hunter 4/2 T2 $3 | Wrath Weaver 1/4 T1 $3
  Hand: 0 cards

  → Gold 8→1 | Trinket: Stegodon Portrait
  → Actions: refresh, refresh

**Sneed** [Heuristic]  HP=30 Armor=2 Gold=8 Tier=3

  Board (5/7): 2/1, 4/1, 4/1, 4/3, 3/4
  Tavern (5 items): Technical Element 5/6 T3 $3 | Soul Rewinder 4/1 T2 $3 | Old Soul 3/4 T2 $3 | Ominous Seer 2/1 T1 $3 | Robust Evolution (spell) T3 $1
  Hand: 1 cards

  → Board (7/7): 2/1, 4/1, 4/1, 4/3, 3/4, 5/6, 3/4
  → Gold 8→0 | Trinket: Rusty Trident
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=8 Tier=3

  Board (4/7): 13/16 [G], 2/4 [Taunt], 10/11, 10/9
  Tavern (5 items): Sly Raptor 12/14 T3 $3 | Picky Eater 12/12 T1 $3 | Mummifier 16/13 T3 $3 | Mummifier 16/13 T3 $3 | Hostile Bounty (spell) T3 $2
  Hand: 0 cards

  → Board (6/7): 13/16 [G], 2/4 [Taunt], 10/11, 10/9, 16/13, 16/13
  → Gold 8→0 | Trinket: Impulsive Portrait
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=1 Gold=8 Tier=3

  Board (4/7): 6/6 [G], 4/4, 4/2, 2/1 [Taunt]
  Tavern (6 items): Deep-Sea Angler 2/3 T3 $3 | Sly Raptor 1/3 T3 $3 | Sewer Rat 3/2 T2 $3 | Deflect-o-Bot 3/2 T3 $3 | Tricky Trousers (spell) T3 $1 | Amber Guardian 3/2 T3 $3
  Hand: 1 cards

  → Board (6/7): 6/6 [G], 4/4, 4/2, 2/1 [Taunt], 2/3, 3/2
  → Gold 8→0 | Trinket: Smuggler Portrait | Hand 1→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=8 Tier=3

  Board (5/7): 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/2
  Tavern (4 items): Ancestral Automaton 3/4 T2 $3 | Deflect-o-Bot 3/2 T3 $3 | Eternal Knight 4/2 T2 $3 | Alert Alarmist 2/2 T2 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/2, 3/4, 4/2
  → Gold 8→0 | Trinket: Beetle Band
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=29 Armor=0 Gold=8 Tier=3

  Board (6/7): 4/1, 1/1 [DS], 8/2, 8/2, 0/1 [Taunt], 0/1 [Taunt]
  Tavern (4 items): Mummifier 5/2 T3 $3 | Ancestral Automaton 3/4 T2 $3 | Deflect-o-Bot 3/2 T3 $3 | Leeching Felhound 3/3 T3 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 1/1 [DS], 8/2, 8/2, 0/1 [Taunt], 5/2, 3/4
  → Gold 8→0 | Trinket: Magician's Top Hat
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=29 Armor=0 Gold=8 Tier=3

  Board (5/7): 3/1 [Taunt,Reborn], 1/1 [DS], 3/1 [Taunt,Reborn], 4/3, 2/4
  Tavern (4 items): False Implicator 1/1 T3 $3 | Leeching Felhound 3/3 T3 $3 | Alert Alarmist 2/2 T2 $3 | Technical Element 5/6 T3 $3
  Hand: 0 cards

  → Board (6/7): 3/1 [Taunt,Reborn], 1/1 [DS], 3/1 [Taunt,Reborn], 4/3, 2/4, 5/6
  → Gold 8→0 | Trinket: Enigmatic Headstone
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=8 Tier=3

  Board (5/7): 2/1 [Taunt,Reborn], 1/4, 1/2 [Taunt,DS], 3/4, 2/2 [Taunt]
  Tavern (4 items): Eternal Knight 4/2 T2 $3 | Reef Riffer 3/2 T2 $3 | Sly Raptor 1/3 T3 $3 | Handless Forsaken 2/1 T3 $3
  Hand: 0 cards

  → Board (7/7): 1/4, 1/2 [Taunt,DS], 3/4, 2/2 [Taunt], 4/2, 3/2, 1/3
  → Gold 8→0 | Trinket: Kaboom Bot Portrait
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Professor Putricide (first: Professor Putricide)
     Overlord Saurfang: [13/16, 2/4, 10/11, 10/9, 16/13, 16/13]
     Professor Putricide: [4/1, 1/1, 8/2, 8/2, 0/1, 5/2, 3/4]
     Manasaber 4/1→4/0 DEAD  |  Taunt Test Minion 2/4→2/0 DEAD
     Wrath Weaver 13/16→13/16  |  Cubling 0/1→0/0 DEAD
     Cord Puller 1/1→1/1  |  Wrath Weaver 13/16→13/15
     Old Soul 10/11→10/8  |  Ancestral Automaton 3/4→3/0 DEAD
     Eternal Knight 8/2→9/0 DEAD  |  Old Soul 10/8→10/0 DEAD
     Sewer Rat 10/9→10/8  |  Cord Puller 1/1→1/0 DEAD
     Eternal Knight 9/2→10/0 DEAD  |  Mummifier 16/13→16/4
     Mummifier 16/13→16/8  |  Mummifier 5/2→5/0 DEAD
     Result: 4 vs 0 — heur
  [heur] Ysera vs [AGENT] Yogg-Saron, Hope's End (first: Ysera)
     Ysera: [6/6, 4/4, 4/2, 2/1, 2/3, 3/2]
     Yogg-Saron, Hope's End: [8/2, 6/2, 3/4]
     Scarlet Survivor 6/6→6/0 DEAD  |  Festergut 6/2→6/0 DEAD
     Manasaber 8/2→8/2  |  Tide Raiser 2/1→2/0 DEAD
     Sklibb, Demon Hunter 4/4→4/1  |  Laboratory Assistant 3/4→3/0 DEAD
     Result: 4 vs 1 — heur
  [heur] Inge, the Iron Hymn vs [heur] Drek'Thar (first: Drek'Thar)
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4, 3/2, 3/4, 4/2]
     Drek'Thar: [1/4, 1/2, 3/4, 2/2, 4/2, 3/2, 1/3]
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Alert Alarmist 2/2→2/0 DEAD
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/1
     Annoy-o-Tron 1/1→1/0 DEAD  |  Annoy-o-Tron 1/2→1/1
     Ancestral Automaton 3/4→3/1  |  Old Soul 3/4→3/1
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/1→1/0 DEAD
     Eternal Knight 4/2→5/0 DEAD  |  Eternal Knight 4/2→5/0 DEAD
     Old Soul 3/1→3/0 DEAD  |  Ancestral Automaton 3/1→3/0 DEAD
     Reef Riffer 3/2→3/0 DEAD  |  Ancestral Automaton 3/4→3/1
     Sewer Rat 3/2→3/1  |  Sly Raptor 1/3→1/0 DEAD
     Result: 2 vs 1 — heur
  [heur] Sneed vs [heur] Sylvanas Windrunner (first: Sneed)
     Sneed: [2/1, 4/1, 4/1, 4/3, 3/4, 5/6, 3/4]
     Sylvanas Windrunner: [3/1, 1/1, 3/1, 4/3, 2/4, 5/6]
     Ominous Seer 2/1→2/0 DEAD  |  Risen Rider 3/1→3/0 DEAD
     Risen Rider 3/1→3/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Nerubian Deathswarmer 2/4→2/0 DEAD
     Cord Puller 1/1→1/1  |  Manasaber 4/1→4/0 DEAD
     Laboratory Assistant 3/4→3/3  |  Cord Puller 1/1→1/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Laboratory Assistant 3/3→3/0 DEAD
     Technical Element 5/6→5/1  |  Technical Element 5/6→5/1
     Technical Element 5/1→5/0 DEAD  |  Old Soul 3/4→3/0 DEAD
     Result: 1 vs 0 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=2) | Sneed (HP=30, Tier=3) | Overlord Saurfang (HP=30, Tier=3) | Ysera (HP=30, Tier=3) | Inge, the Iron Hymn (HP=30, Tier=3) | Drek'Thar (HP=30, Tier=3) | Sylvanas Windrunner (HP=23, Tier=3) | Professor Putricide (HP=19, Tier=3)

### Turn 7

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=3 Gold=9 Tier=2

  Board (3/7): 8/2 [G], 6/2, 3/4
  Tavern (4 items): Shell Collector 4/3 T2 $3 | Eternal Knight 4/2 T2 $3 | Cord Puller 1/1 T1 $3 | Metallic Hunter 4/2 T2 $3
  Hand: 0 cards

  → Actions: 

**Sneed** [Heuristic]  HP=30 Armor=2 Gold=9 Tier=3

  Board (7/7): 2/1, 4/1, 4/1, 4/3, 3/4, 5/6, 3/4
  Tavern (4 items): Sprightly Scarab 3/1 T3 $3 | Leeching Felhound 3/3 T3 $3 | Floating Watcher 4/4 T3 $5 | Technical Element 5/6 T3 $3
  Hand: 3 cards

  → Board (7/7): 4/1, 8/5, 4/3, 3/4, 5/6, 3/4, 5/6
  → Tier 3→4 | Gold 9→0 | Hand 3→2
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=9 Tier=3

  Board (6/7): 13/16 [G], 2/4 [Taunt], 10/11, 10/9, 16/13, 16/13
  Tavern (4 items): Sprightly Scarab 17/15 T3 $3 | Sewer Rat 17/16 T2 $3 | Old Soul 17/18 T2 $3 | Mummifier 19/16 T3 $3
  Hand: 0 cards

  → Board (7/7): 13/16 [G], 2/4 [Taunt], 10/11, 10/9, 16/13, 16/13, 17/18
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=1 Gold=9 Tier=3

  Board (6/7): 6/6 [G], 4/4, 4/2, 2/1 [Taunt], 2/3, 3/2
  Tavern (5 items): Deep Blue Crooner 2/2 T3 $3 | Surf n' Surf 1/1 T1 $3 | Deep Blue Crooner 2/2 T3 $3 | Dustbone Devastator 2/6 T3 $3 | Twilight Hatchling 1/1 T1 $3
  Hand: 1 cards

  → Board (7/7): 8/8 [Taunt,G], 4/4, 4/2, 2/1 [Taunt], 2/3, 3/2, 2/6
  → Tier 3→4 | Gold 9→0 | Hand 1→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=9 Tier=3

  Board (7/7): 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/2, 3/4, 5/2
  Tavern (4 items): Sly Raptor 1/3 T3 $3 | Deep-Sea Angler 2/3 T3 $3 | Deep Blue Crooner 2/2 T3 $3 | Mummifier 5/2 T3 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 4/1, 3/4, 3/2, 3/4, 5/2, 5/2
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=19 Armor=0 Gold=9 Tier=3

  Board (7/7): 4/1, 1/1 [DS], 10/2, 10/2, 0/1 [Taunt], 5/2, 3/4
  Tavern (4 items): Tide Raiser 2/1 T2 $3 | Annoy-o-Module 2/4 T3 $3 | False Implicator 1/1 T3 $3 | Technical Element 5/6 T3 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 1/1 [DS], 10/2, 10/2, 5/2, 3/4, 5/6
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=23 Armor=0 Gold=9 Tier=3

  Board (6/7): 3/1 [Taunt,Reborn], 1/1 [DS], 3/1 [Taunt,Reborn], 4/3, 2/4, 5/6
  Tavern (4 items): Annoy-o-Module 2/4 T3 $3 | Cord Puller 1/1 T1 $3 | Sprightly Scarab 3/1 T3 $3 | Sly Raptor 1/3 T3 $3
  Hand: 0 cards

  → Board (7/7): 3/1 [Taunt,Reborn], 1/1 [DS], 3/1 [Taunt,Reborn], 4/3, 2/4, 5/6, 2/4 [Taunt,DS]
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=9 Tier=3

  Board (7/7): 1/4, 1/2 [Taunt,DS], 3/4, 2/2 [Taunt], 5/2, 3/2, 1/3
  Tavern (4 items): Cadaver Caretaker 3/3 T3 $3 | Reef Riffer 3/2 T2 $3 | Hardy Orca 1/6 T3 $3 | Scarlet Skull 2/1 T2 $3
  Hand: 1 cards

  → Board (7/7): 1/4, 3/4, 6/6 [Taunt], 5/2, 3/2, 1/3, 1/6 [Taunt]
  → Tier 3→4 | Gold 9→0 | Hand 1→0
  → Actions: (auto)

**Combat Phase**

  [heur] Sneed vs [heur] Overlord Saurfang (first: Sneed)
     Sneed: [4/1, 8/5, 4/3, 3/4, 5/6, 3/4, 5/6]
     Overlord Saurfang: [13/16, 2/4, 10/11, 10/9, 16/13, 16/13, 17/18]
     Manasaber 4/1→4/0 DEAD  |  Taunt Test Minion 2/4→2/0 DEAD
     Wrath Weaver 13/16→13/12  |  Shell Collector 4/3→4/0 DEAD
     Manasaber 8/5→8/0 DEAD  |  Mummifier 16/13→16/5
     Old Soul 10/11→10/8  |  Laboratory Assistant 3/4→3/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Mummifier 16/13→16/8
     Sewer Rat 10/9→10/6  |  Old Soul 3/4→3/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Mummifier 16/5→16/0 DEAD
     Result: 0 vs 5 — heur
  [heur] Drek'Thar vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Drek'Thar: [1/4, 3/4, 6/6, 5/2, 3/2, 1/3, 1/6]
     Sylvanas Windrunner: [3/1, 1/1, 3/1, 4/3, 2/4, 5/6, 2/4]
     Risen Rider 3/1→3/0 DEAD  |  Hardy Orca 1/6→1/3
     Wrath Weaver 1/4→1/1  |  Risen Rider 3/1→3/0 DEAD
     Cord Puller 1/1→1/1  |  Alert Alarmist 6/6→6/5
     Ancestral Automaton 3/4→3/2  |  Annoy-o-Module 2/4→2/4
     Shell Collector 4/3→4/2  |  Hardy Orca 1/3→1/0 DEAD
     Alert Alarmist 6/5→6/3  |  Annoy-o-Module 2/4→2/0 DEAD
     Nerubian Deathswarmer 2/4→2/0 DEAD  |  Alert Alarmist 6/3→6/1
     Eternal Knight 5/2→6/0 DEAD  |  Shell Collector 4/2→4/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Alert Alarmist 6/1→6/0 DEAD
     Reef Riffer 3/2→3/1  |  Cord Puller 1/1→1/0 DEAD
     Result: 4 vs 0 — heur
  [heur] Inge, the Iron Hymn vs [AGENT] Yogg-Saron, Hope's End (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 4/1, 3/4, 3/2, 3/4, 5/2, 5/2]
     Yogg-Saron, Hope's End: [8/2, 6/2, 3/4]
     Manasaber 4/1→4/0 DEAD  |  Laboratory Assistant 3/4→3/0 DEAD
     Manasaber 8/2→8/2  |  Old Soul 3/4→3/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Manasaber 8/2→8/0 DEAD
     Festergut 6/2→6/0 DEAD  |  Ancestral Automaton 3/4→3/0 DEAD
     Result: 3 vs 0 — heur
  [heur] Professor Putricide vs [heur] Ysera (first: Professor Putricide)
     Professor Putricide: [4/1, 1/1, 10/2, 10/2, 5/2, 3/4, 5/6]
     Ysera: [8/8, 4/4, 4/2, 2/1, 2/3, 3/2, 2/6]
     Manasaber 4/1→4/0 DEAD  |  Tide Raiser 2/1→2/0 DEAD
     Scarlet Survivor 8/8→8/5  |  Ancestral Automaton 3/4→3/0 DEAD
     Cord Puller 1/1→1/1  |  Scarlet Survivor 8/5→8/4
     Sklibb, Demon Hunter 4/4→4/0 DEAD  |  Eternal Knight 10/2→11/0 DEAD
     Eternal Knight 11/2→12/0 DEAD  |  Scarlet Survivor 8/4→8/0 DEAD
     Metallic Hunter 5/4→5/0 DEAD  |  Technical Element 5/6→5/1
     Mummifier 5/2→5/0 DEAD  |  Sewer Rat 3/2→3/0 DEAD
     Deep-Sea Angler 2/3→2/2  |  Cord Puller 1/1→1/0 DEAD
     Technical Element 5/1→5/0 DEAD  |  Dustbone Devastator 2/6→2/1
     Result: 0 vs 2 — heur

  Alive: 8/8
  HP: Overlord Saurfang (HP=30, Tier=4) | Ysera (HP=30, Tier=4) | Inge, the Iron Hymn (HP=30, Tier=4) | Drek'Thar (HP=30, Tier=4) | Yogg-Saron, Hope's End (HP=23, Tier=2) | Sneed (HP=22, Tier=4) | Sylvanas Windrunner (HP=13, Tier=4) | Professor Putricide (HP=9, Tier=4)

### Turn 8

**Yogg-Saron, Hope's End** [RL AGENT]  HP=23 Armor=0 Gold=10 Tier=2

  Board (3/7): 8/2 [G], 6/2, 3/4
  Tavern (5 items): Tide Raiser 2/1 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Sewer Rat 3/2 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Angler's Lure (spell) T1 $3
  Hand: 0 cards

  → Gold 10→8 | Hand 0→1
  → Actions: sell_board_2, buy_tavern_3, play_hand_0, buy_tavern_3

**Sneed** [Heuristic]  HP=22 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/1, 8/5, 4/3, 3/4, 5/6, 3/4, 5/6
  Tavern (6 items): Trigore the Lasher 9/3 T4 $3 | Wyvern Outrider 2/8 T4 $3 | Seafloor Recruiter 3/5 T4 $3 | Floating Watcher 4/4 T3 $5 | Friendly Geist 6/3 T4 $3 | Tomb Turning (spell) T4 $2
  Hand: 4 cards

  → Board (7/7): 8/5, 5/6, 5/6, 9/3, 2/8, 6/3 [DS], 6/4 [G]
  → Gold 10→0 | Hand 4→3
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=10 Tier=4

  Board (7/7): 13/16 [G], 2/4 [Taunt], 10/11, 10/9, 16/13, 16/13, 17/18
  Tavern (6 items): Hardy Orca 17/22 T3 $3 | Humming Bird 17/20 T2 $3 | Rimescale Priestess 19/19 T4 $3 | Zesty Shaker 22/23 T4 $3 | Holo Rover 20/20 T4 $3 | Conflagration (spell) T4 $2
  Hand: 0 cards

  → Board (7/7): 16/13, 17/18, 22/23, 20/20 [DS], 17/22 [Taunt], 19/19, 17/20
  → Gold 10→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=1 Gold=10 Tier=4

  Board (7/7): 8/8 [Taunt,G], 4/4, 4/2, 2/1 [Taunt], 2/3, 3/2, 2/6
  Tavern (7 items): Trigore the Lasher 9/3 T4 $3 | Seafloor Recruiter 3/5 T4 $3 | Prosthetic Hand 3/1 T4 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Hunting Tiger Shark 3/5 T4 $3 | Defender's Rites (spell) T4 $2 | Incubation Researcher 2/8 T4 $3
  Hand: 2 cards

  → Board (7/7): 8/8 [Taunt,G], 2/6, 11/5 [Taunt], 2/8, 5/4, 3/5, 3/5
  → Gold 10→0 | Hand 2→1
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=10 Tier=4

  Board (7/7): 4/1, 4/1, 3/4, 3/2, 3/4, 5/2, 5/2
  Tavern (6 items): Hardy Orca 1/6 T3 $3 | Woodland Defiler 5/6 T4 $3 | Stomping Stegodon 4/4 T4 $3 | Banana Slamma 3/6 T4 $3 | Deep-Sea Angler 2/3 T3 $3 | Boon of Beetles (spell) T4 $1
  Hand: 0 cards

  → Board (7/7): 5/2, 5/2, 5/6, 3/6, 4/4, 1/6 [Taunt], 2/3
  → Gold 10→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=9 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/1, 1/1 [DS], 12/2, 12/2, 5/2, 3/4, 5/6
  Tavern (6 items): Wyvern Outrider 2/8 T4 $3 | False Implicator 1/1 T3 $3 | Enchanted Sentinel 3/5 T4 $3 | Lava Lurker 2/5 T2 $3 | Handless Forsaken 2/1 T3 $3 | Shifting Tide (spell) T4 $1
  Hand: 0 cards

  → Board (7/7): 12/2, 12/2, 5/6, 2/8, 3/5, 2/5, 1/1
  → Gold 10→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=13 Armor=0 Gold=10 Tier=4

  Board (7/7): 3/1 [Taunt,Reborn], 1/1 [DS], 3/1 [Taunt,Reborn], 4/3, 2/4, 5/6, 2/4 [Taunt,DS]
  Tavern (6 items): False Implicator 1/1 T3 $3 | Hunting Tiger Shark 3/5 T4 $3 | Deflect-o-Bot 3/2 T3 $3 | Rylak Metalhead 5/3 T4 $3 | Trigore the Lasher 9/3 T4 $3 | Natural Blessing (spell) T4 $4
  Hand: 0 cards

  → Board (7/7): 4/3, 2/4, 5/6, 9/3, 3/5, 5/3 [Taunt], 1/1
  → Gold 10→0 | Hand 0→1
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=10 Tier=4

  Board (7/7): 1/4, 3/4, 6/6 [Taunt], 6/2, 3/2, 1/3, 1/6 [Taunt]
  Tavern (6 items): Deep Blue Crooner 2/2 T3 $3 | Ominous Seer 2/1 T1 $3 | Zesty Shaker 6/7 T4 $3 | Abyssal Bruiser 1/1 T4 $3 | Accord-o-Tron 3/3 T3 $3 | Deepwater Clan (spell) T4 $2
  Hand: 1 cards

  → Board (7/7): 3/4, 6/6 [Taunt], 6/6, 1/6 [Taunt], 6/7, 3/3, 1/1 [DS]
  → Gold 10→0 | Hand 1→0
  → Actions: (auto)

**Combat Phase**

  [AGENT] Yogg-Saron, Hope's End vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Yogg-Saron, Hope's End: [8/2, 6/2, 3/4]
     Sylvanas Windrunner: [4/3, 2/4, 5/6, 9/3, 3/5, 5/3, 1/1]
     Shell Collector 4/3→4/0 DEAD  |  Festergut 6/2→6/0 DEAD
     Manasaber 8/2→8/2  |  Rylak Metalhead 5/3→5/0 DEAD
     Nerubian Deathswarmer 2/4→2/0 DEAD  |  Manasaber 8/2→8/0 DEAD
     Laboratory Assistant 3/4→3/1  |  Hunting Tiger Shark 3/5→3/2
     Technical Element 5/6→5/3  |  Laboratory Assistant 3/1→3/0 DEAD
     Result: 0 vs 4 — heur
  [heur] Sneed vs [heur] Drek'Thar (first: Sneed)
     Sneed: [8/5, 5/6, 5/3, 9/3, 2/8, 6/3, 6/4]
     Drek'Thar: [3/4, 6/6, 6/6, 1/6, 6/7, 3/3, 1/1]
     Manasaber 8/5→8/0 DEAD  |  Alert Alarmist 6/6→6/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Technical Element 5/3→5/0 DEAD
     Technical Element 5/6→5/5  |  Hardy Orca 1/6→1/1
     Eternal Knight 6/6→6/4  |  Wyvern Outrider 2/8→2/2
     Trigore the Lasher 9/3→9/2  |  Hardy Orca 1/1→1/0 DEAD
     Zesty Shaker 6/7→6/2  |  Technical Element 5/5→5/0 DEAD
     Wyvern Outrider 2/2→2/0 DEAD  |  Zesty Shaker 6/2→6/0 DEAD
     Accord-o-Tron 3/3→3/0 DEAD  |  Friendly Geist 6/3→6/3
     Friendly Geist 6/3→6/0 DEAD  |  Eternal Knight 6/4→7/0 DEAD
     Abyssal Bruiser 1/1→1/1  |  Old Soul 6/4→6/3
     Old Soul 6/3→6/2  |  Abyssal Bruiser 1/1→1/0 DEAD
     Result: 2 vs 0 — heur
  [heur] Overlord Saurfang vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Overlord Saurfang: [16/13, 17/18, 22/23, 20/20, 18/22, 19/19, 18/20]
     Inge, the Iron Hymn: [5/2, 5/2, 5/6, 3/6, 4/4, 1/6, 2/3]
     Eternal Knight 5/2→6/0 DEAD  |  Hardy Orca 18/22→18/17
     Mummifier 16/13→16/12  |  Hardy Orca 1/6→1/0 DEAD
     Mummifier 5/2→5/0 DEAD  |  Hardy Orca 18/17→18/12
     Old Soul 17/18→17/13  |  Woodland Defiler 5/6→5/0 DEAD
     Banana Slamma 3/6→3/0 DEAD  |  Hardy Orca 18/12→18/9
     Zesty Shaker 22/23→22/21  |  Deep-Sea Angler 2/3→2/0 DEAD
     Stomping Stegodon 4/4→4/0 DEAD  |  Hardy Orca 18/9→18/5
     Result: 7 vs 0 — heur
  [heur] Ysera vs [heur] Professor Putricide (first: Professor Putricide)
     Ysera: [8/8, 2/6, 11/5, 2/8, 5/4, 3/5, 3/5]
     Professor Putricide: [12/2, 12/2, 5/6, 2/8, 3/5, 2/5, 1/1]
     Eternal Knight 12/2→13/0 DEAD  |  Scarlet Survivor 8/8→8/0 DEAD
     Dustbone Devastator 2/6→3/0 DEAD  |  Eternal Knight 13/2→14/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Trigore the Lasher 11/5→11/0 DEAD
     Incubation Researcher 2/8→2/7  |  False Implicator 1/1→1/0 DEAD
     Wyvern Outrider 2/8→2/5  |  Hunting Tiger Shark 3/5→3/3
     Malchezaar, Prince of Dance 5/4→5/1  |  Enchanted Sentinel 3/5→3/0 DEAD
     Lava Lurker 2/5→2/0 DEAD  |  Malchezaar, Prince of Dance 5/1→5/0 DEAD
     Seafloor Recruiter 3/5→3/3  |  Wyvern Outrider 2/5→2/2
     Result: 3 vs 1 — heur

  Alive: 8/8
  HP: Overlord Saurfang (HP=30, Tier=4) | Ysera (HP=30, Tier=4) | Drek'Thar (HP=30, Tier=4) | Inge, the Iron Hymn (HP=27, Tier=4) | Sneed (HP=22, Tier=4) | Sylvanas Windrunner (HP=13, Tier=4) | Professor Putricide (HP=9, Tier=4) | Yogg-Saron, Hope's End (HP=8, Tier=2)

### Turn 9

**Yogg-Saron, Hope's End** [RL AGENT]  HP=8 Armor=0 Gold=10 Tier=2

  Board (3/7): 8/2 [G], 6/2, 3/4
  Tavern (5 items): Manasaber 4/1 T1 $3 | Lava Lurker 2/5 T2 $3 | Lava Lurker 2/5 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Sick Riffs (spell) T1 $3
  Hand: 0 cards

  → Board (4/7): 8/2 [G], 6/2, 3/4, 2/5
  → Gold 10→3 | Trinket: Wildfeather Duster
  → Actions: buy_tavern_1, play_hand_0, refresh

**Sneed** [Heuristic]  HP=22 Armor=0 Gold=10 Tier=4

  Board (7/7): 8/5, 5/6, 5/3, 9/7, 2/8, 6/3 [DS], 6/4 [G]
  Tavern (6 items): Ancestral Automaton 3/4 T2 $3 | Reef Riffer 3/2 T2 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Sewer Rat 3/2 T2 $3 | Soul Rewinder 4/1 T2 $3 | Glowing Crown (spell) T1 $3
  Hand: 3 cards

  → Tier 4→5 | Gold 10→0 | Trinket: Wildfeather Duster
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=10 Tier=4

  Board (7/7): 16/13, 17/18, 22/23, 20/20 [DS], 17/22 [Taunt], 19/19, 17/20
  Tavern (6 items): Technical Element 30/31 T3 $3 | Annoy-o-Module 27/29 T3 $3 | Friendly Geist 31/28 T4 $3 | Banana Slamma 28/31 T4 $3 | Floating Watcher 29/29 T3 $5 | Friendly Bounty (spell) T3 $2
  Hand: 1 cards

  → Board (7/7): 17/18, 22/23, 20/20 [DS], 17/22 [Taunt], 19/19, 17/20, 30/31
  → Tier 4→5 | Gold 10→0 | Trinket: Precious Pearl
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=1 Gold=10 Tier=4

  Board (7/7): 8/8 [Taunt,G], 3/6, 11/7 [Taunt], 2/8, 5/4, 3/5, 3/5
  Tavern (7 items): Annoy-o-Tron 1/2 T1 $3 | Ancestral Automaton 3/4 T2 $3 | Deep-Sea Angler 2/3 T3 $3 | Rimescale Priestess 3/3 T4 $3 | Deep-Sea Angler 2/3 T3 $3 | Forest's Bounty (spell) T4 $3 | Scarlet Survivor 3/3 T1 $3
  Hand: 2 cards

  → Board (7/7): 8/8 [Taunt,G], 3/6, 11/7 [Taunt], 2/8, 5/4, 3/5, 3/4
  → Tier 4→5 | Gold 10→0 | Trinket: Chromatic Tear | Hand 2→4
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=27 Armor=0 Gold=10 Tier=4

  Board (7/7): 6/2, 5/2, 5/6, 3/6, 4/4, 1/6 [Taunt], 2/3
  Tavern (6 items): Friendly Geist 6/3 T4 $3 | Laboratory Assistant 3/4 T2 $3 | False Implicator 1/1 T3 $3 | Seafloor Recruiter 3/5 T4 $3 | Woodland Defiler 5/6 T4 $3 | Angler's Lure (spell) T1 $3
  Hand: 1 cards

  → Board (7/7): 6/2, 5/2, 5/6, 5/8 [Taunt], 4/4, 1/6 [Taunt], 2/3
  → Tier 4→5 | Gold 10→0 | Trinket: Wildfeather Duster | Hand 1→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=9 Armor=0 Gold=10 Tier=4

  Board (7/7): 14/2, 14/2, 5/6, 2/8, 3/5, 2/5, 1/1
  Tavern (6 items): Nerubian Deathswarmer 1/4 T2 $3 | Imposing Percussionist 4/4 T4 $3 | Ancestral Automaton 3/4 T2 $3 | Auto Assembler 2/2 T4 $3 | Soul Rewinder 4/1 T2 $3 | Misplaced Tea Set (spell) T4 $2
  Hand: 0 cards

  → Board (7/7): 14/2, 14/2, 5/6, 2/8, 3/5, 2/5, 12/4
  → Tier 4→5 | Gold 10→0 | Trinket: Artisanal Urn
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=13 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/3, 2/4, 5/6, 9/5, 3/5, 5/3 [Taunt], 1/1
  Tavern (6 items): Abyssal Bruiser 1/1 T4 $3 | Soul Rewinder 4/1 T2 $3 | Sewer Rat 3/2 T2 $3 | Manasaber 4/1 T1 $3 | Reef Riffer 3/2 T2 $3 | Back to Back (spell) T4 $1
  Hand: 2 cards

  → Tier 4→5 | Gold 10→0 | Trinket: Wildfeather Duster
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=0 Gold=11 Tier=4

  Board (7/7): 3/4, 6/6 [Taunt], 7/6, 1/6 [Taunt], 6/7, 3/3, 1/1 [DS]
  Tavern (6 items): Holo Rover 4/4 T4 $3 | Plaguerunner 4/2 T4 $3 | Abyssal Bruiser 1/1 T4 $3 | Banana Slamma 3/6 T4 $3 | Leeching Felhound 3/3 T3 $3 | Pointy Arrow (spell) T1 $1
  Hand: 0 cards

  → Tier 4→5 | Gold 11→0 | Trinket: Fridge Magnet
  → Actions: (auto)

**Combat Phase**

  [heur] Professor Putricide vs [heur] Sneed (first: Sneed)
     Professor Putricide: [14/2, 14/2, 5/6, 2/8, 3/5, 2/5, 12/4]
     Sneed: [8/5, 5/6, 5/3, 9/7, 2/8, 6/3, 6/4]
     Manasaber 8/5→8/0 DEAD  |  Eternal Knight 14/2→15/0 DEAD
     Eternal Knight 15/2→16/0 DEAD  |  Wyvern Outrider 2/8→2/0 DEAD
     Technical Element 5/6→5/3  |  Enchanted Sentinel 3/5→3/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Friendly Geist 6/3→6/3
     Technical Element 5/3→5/1  |  Lava Lurker 2/5→2/0 DEAD
     Wyvern Outrider 2/8→2/0 DEAD  |  Trigore the Lasher 9/7→9/5
     Trigore the Lasher 9/5→9/0 DEAD  |  Nerubian Deathswarmer 12/4→12/0 DEAD
     Result: 0 vs 4 — heur
  [AGENT] Yogg-Saron, Hope's End vs [heur] Drek'Thar (first: Drek'Thar)
     Yogg-Saron, Hope's End: [8/2, 6/2, 3/4, 2/5]
     Drek'Thar: [3/4, 6/6, 7/6, 1/6, 6/7, 3/3, 1/1]
     Ancestral Automaton 3/4→3/0 DEAD  |  Festergut 6/2→6/0 DEAD
     Manasaber 8/2→8/2  |  Hardy Orca 1/6→1/0 DEAD
     Alert Alarmist 6/6→6/3  |  Laboratory Assistant 3/4→3/0 DEAD
     Lava Lurker 2/5→2/0 DEAD  |  Alert Alarmist 6/3→6/1
     Eternal Knight 7/6→8/0 DEAD  |  Manasaber 8/2→8/0 DEAD
     Result: 0 vs 4 — heur
  [heur] Sylvanas Windrunner vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Sylvanas Windrunner: [4/3, 2/4, 5/6, 9/5, 3/5, 5/3, 1/1]
     Inge, the Iron Hymn: [6/2, 5/2, 5/6, 5/8, 4/4, 1/6, 2/3]
     Eternal Knight 6/2→7/0 DEAD  |  Rylak Metalhead 5/3→5/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Banana Slamma 5/8→5/4
     Mummifier 5/2→5/0 DEAD  |  Hunting Tiger Shark 3/5→3/0 DEAD
     Nerubian Deathswarmer 2/4→2/0 DEAD  |  Banana Slamma 5/4→5/2
     Woodland Defiler 5/6→5/5  |  False Implicator 1/1→1/0 DEAD
     Technical Element 5/6→5/5  |  Hardy Orca 1/6→1/1
     Banana Slamma 5/2→5/0 DEAD  |  Trigore the Lasher 9/5→9/0 DEAD
     Result: 1 vs 4 — heur
  [heur] Ysera vs [heur] Overlord Saurfang (first: Ysera)
     Ysera: [8/8, 3/6, 11/7, 2/8, 5/4, 3/5, 3/4]
     Overlord Saurfang: [17/18, 22/23, 20/20, 18/22, 19/19, 18/20, 30/31]
     Scarlet Survivor 8/8→8/0 DEAD  |  Hardy Orca 18/22→18/14
     Old Soul 17/18→17/7  |  Trigore the Lasher 11/7→11/0 DEAD
     Dustbone Devastator 3/6→4/0 DEAD  |  Hardy Orca 18/14→18/11
     Zesty Shaker 22/23→22/21  |  Incubation Researcher 2/8→2/0 DEAD
     Malchezaar, Prince of Dance 5/4→5/0 DEAD  |  Hardy Orca 18/11→18/6
     Holo Rover 20/20→20/20  |  Ancestral Automaton 3/4→3/0 DEAD
     Hunting Tiger Shark 3/5→3/0 DEAD  |  Hardy Orca 18/6→18/3
     Result: 0 vs 7 — heur

  **Yogg-Saron, Hope's End [AGENT] eliminated!** (Turn 9)
  **Professor Putricide [Heuristic] eliminated!** (Turn 9)
  Alive: 6/8
  HP: Overlord Saurfang (HP=30, Tier=5) | Drek'Thar (HP=30, Tier=5) | Inge, the Iron Hymn (HP=27, Tier=5) | Sneed (HP=22, Tier=5) | Ysera (HP=16, Tier=5) | Sylvanas Windrunner (HP=13, Tier=5)

### Turn 10

**Sneed** [Heuristic]  HP=22 Armor=0 Gold=10 Tier=5

  Board (7/7): 8/5, 5/6, 5/3, 9/11, 2/8, 6/3 [DS], 6/4 [G]
  Tavern (6 items): Holo Rover 4/4 T4 $3 | Glowscale 4/6 T5 $3 | Iridescent Skyblazer 3/8 T5 $3 | Deep-Sea Angler 2/3 T3 $3 | Risen Rider 2/1 T1 $3 | Portal in a Crystal (spell) T5 $2
  Hand: 3 cards

  → Board (7/7): 8/5, 5/6, 9/11, 6/4 [G], 3/8, 4/6 [Taunt], 2/1 [Taunt,Reborn]
  → Gold 10→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=10 Tier=5

  Board (7/7): 17/18, 22/23, 20/20 [DS], 17/22 [Taunt], 19/19, 17/20, 30/31
  Tavern (6 items): Lurking Leviathan 29/34 T5 $3 | Zesty Shaker 32/33 T4 $3 | Sprightly Scarab 29/27 T3 $3 | Friendly Geist 32/29 T4 $3 | Shadowdancer 31/29 T5 $3 | Rime or Reason (spell) T1 $3
  Hand: 3 cards

  → Board (6/7): 22/23, 30/31, 32/33, 29/34, 32/29, 31/29 [Taunt]
  → Gold 10→0 | Hand 3→2
  → Actions: (auto)

**Ysera** [Heuristic]  HP=16 Armor=0 Gold=10 Tier=5

  Board (7/7): 8/8 [Taunt,G], 4/6, 11/9 [Taunt], 2/8, 5/4, 3/5, 3/4
  Tavern (7 items): Divine Sparkbot 4/2 T5 $3 | Monstrous Macaw 5/4 T4 $3 | Alert Alarmist 2/2 T2 $3 | False Implicator 1/1 T3 $3 | Reef Riffer 3/2 T2 $3 | Hired Headhunter (spell) T5 $3 | Tarecgosa 4/4 T2 $3
  Hand: 7 cards

  → Board (7/7): 8/8 [Taunt,G], 4/6, 11/9 [Taunt], 2/8, 5/4, 5/4, 2/2 [Taunt]
  → Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=27 Armor=0 Gold=10 Tier=5

  Board (7/7): 7/2, 5/2, 5/6, 5/8 [Taunt], 4/4, 1/6 [Taunt], 2/3
  Tavern (6 items): Deep Blue Crooner 2/2 T3 $3 | Darkcrest Strategist 4/5 T5 $3 | Marquee Ticker 3/7 T4 $3 | Nightmare Par-tea Guest 3/3 T5 $3 | Trigore the Lasher 9/3 T4 $3 | Contracted Corpse (spell) T5 $3
  Hand: 1 cards

  → Board (7/7): 7/2, 5/6, 5/8 [Taunt], 9/3, 5/9 [Taunt], 4/5, 2/2
  → Gold 10→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=13 Armor=0 Gold=10 Tier=5

  Board (7/7): 4/3, 2/4, 5/6, 9/8, 3/5, 5/3 [Taunt], 1/1
  Tavern (6 items): Malchezaar, Prince of Dance 5/4 T4 $3 | Charging Czarina 4/1 T5 $3 | Eternal Tycoon 5/8 T5 $3 | Accord-o-Tron 3/3 T3 $3 | Abyssal Bruiser 1/1 T4 $3 | Upper Hand (spell) T5 $3
  Hand: 3 cards

  → Board (7/7): 5/6, 9/8, 3/5, 5/3 [Taunt], 5/8, 5/4, 1/1 [DS]
  → Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=0 Gold=11 Tier=5

  Board (7/7): 3/4, 6/6 [Taunt], 8/6, 1/6 [Taunt], 6/7, 3/3, 1/1 [DS]
  Tavern (6 items): Sewer Lord 4/6 T5 $3 | Drustfallen Butcher 2/7 T5 $3 | Sly Raptor 1/3 T3 $3 | Reef Riffer 3/2 T2 $3 | Holo Rover 4/4 T4 $3 | Brood of Nozdormu (spell) T5 $2
  Hand: 0 cards

  → Board (7/7): 6/6 [Taunt], 8/6, 6/7, 4/6, 2/7, 4/4 [DS], 1/3
  → Gold 11→0
  → Actions: (auto)

**Combat Phase**

  [heur] Sneed vs [heur] Ysera (first: Sneed)
     Sneed: [8/5, 5/6, 9/11, 6/4, 3/8, 4/6, 2/1]
     Ysera: [8/8, 4/6, 11/9, 2/8, 5/4, 5/4, 2/2]
     Manasaber 8/5→8/3  |  Alert Alarmist 2/2→2/0 DEAD
     Scarlet Survivor 8/8→8/6  |  Risen Rider 2/1→2/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Scarlet Survivor 8/6→8/1
     Dustbone Devastator 4/6→5/2  |  Glowscale 4/6→4/2
     Trigore the Lasher 10/12→10/4  |  Scarlet Survivor 8/1→8/0 DEAD
     Trigore the Lasher 11/9→11/5  |  Glowscale 4/2→4/0 DEAD
     Old Soul 6/4→6/0 DEAD  |  Trigore the Lasher 11/5→11/0 DEAD
     Incubation Researcher 2/8→2/0 DEAD  |  Trigore the Lasher 10/4→10/2
     Iridescent Skyblazer 4/9→4/4  |  Dustbone Devastator 5/2→5/0 DEAD
     Malchezaar, Prince of Dance 5/4→5/0 DEAD  |  Manasaber 9/4→9/0 DEAD
     Result: 2 vs 1 — heur
  [heur] Overlord Saurfang vs [heur] Drek'Thar (first: Drek'Thar)
     Overlord Saurfang: [22/23, 30/31, 32/33, 29/34, 32/29, 31/29]
     Drek'Thar: [6/6, 8/6, 6/7, 4/6, 2/7, 4/4, 1/3]
     Alert Alarmist 6/6→6/0 DEAD  |  Shadowdancer 31/29→31/23
     Zesty Shaker 22/23→22/19  |  Holo Rover 4/4→4/4
     Eternal Knight 8/6→9/0 DEAD  |  Shadowdancer 31/23→31/15
     Technical Element 30/31→30/25  |  Zesty Shaker 6/7→6/0 DEAD
     Sewer Lord 4/6→4/0 DEAD  |  Shadowdancer 31/15→31/11
     Zesty Shaker 32/33→32/29  |  Holo Rover 4/4→4/0 DEAD
     Drustfallen Butcher 2/7→2/0 DEAD  |  Shadowdancer 31/11→31/9
     Lurking Leviathan 29/34→29/33  |  Sly Raptor 1/3→1/0 DEAD
     Result: 6 vs 0 — heur
  [heur] Inge, the Iron Hymn vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Inge, the Iron Hymn: [7/2, 5/6, 5/8, 9/3, 5/9, 4/5, 2/2]
     Sylvanas Windrunner: [5/6, 9/8, 3/5, 5/3, 5/8, 5/4, 1/1]
     Technical Element 5/6→5/1  |  Marquee Ticker 5/9→5/4
     Eternal Knight 7/2→8/0 DEAD  |  Rylak Metalhead 5/3→5/0 DEAD
     Trigore the Lasher 9/8→9/3  |  Marquee Ticker 5/4→5/0 DEAD
     Woodland Defiler 5/6→5/3  |  Hunting Tiger Shark 3/5→3/0 DEAD
     Eternal Tycoon 5/8→5/3  |  Banana Slamma 5/8→5/3
     Banana Slamma 5/3→5/2  |  Abyssal Bruiser 1/1→1/1
     Malchezaar, Prince of Dance 5/4→5/0 DEAD  |  Banana Slamma 5/2→5/0 DEAD
     Trigore the Lasher 9/3→9/0 DEAD  |  Trigore the Lasher 9/3→9/0 DEAD
     Abyssal Bruiser 1/1→1/0 DEAD  |  Deep Blue Crooner 2/2→2/1
     Deep Blue Crooner 2/1→2/0 DEAD  |  Technical Element 5/1→5/0 DEAD
     Result: 0 vs 1 — heur

  Alive: 6/8
  HP: Overlord Saurfang (HP=30, Tier=5) | Sneed (HP=22, Tier=5) | Inge, the Iron Hymn (HP=17, Tier=5) | Ysera (HP=16, Tier=5) | Drek'Thar (HP=15, Tier=5) | Sylvanas Windrunner (HP=13, Tier=5)

### Turn 11

**Sneed** [Heuristic]  HP=22 Armor=0 Gold=10 Tier=5

  Board (7/7): 8/5, 5/6, 9/16, 6/4 [G], 3/8, 4/6 [Taunt], 2/1 [Taunt,Reborn]
  Tavern (6 items): Laboratory Assistant 3/4 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Glowscale 4/6 T5 $3 | Mummifier 5/2 T3 $3 | Marquee Ticker 3/7 T4 $3 | Rime or Reason (spell) T1 $3
  Hand: 5 cards

  → Board (7/7): 8/5, 5/6, 9/16, 6/4 [G], 3/8 [DS], 4/6 [Taunt], 4/6 [Taunt]
  → Tier 5→6 | Gold 10→0 | Hand 5→4
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=10 Tier=5

  Board (6/7): 22/23, 30/31, 32/33, 29/34, 32/29, 31/29 [Taunt]
  Tavern (6 items): Eternal Knight 4/2 T2 $3 | Stomping Stegodon 37/37 T4 $3 | Scarlet Skull 35/34 T2 $3 | Marquee Ticker 36/40 T4 $3 | Seafloor Recruiter 36/38 T4 $3 | Corrupted Cupcakes (spell) T5 $4
  Hand: 2 cards

  → Board (7/7): 22/23, 30/31, 32/33, 29/34, 32/29, 31/29 [Taunt], 3/1 [Reborn]
  → Tier 5→6 | Gold 10→0 | Hand 2→1
  → Actions: (auto)

**Ysera** [Heuristic]  HP=16 Armor=0 Gold=10 Tier=5

  Board (7/7): 8/8 [Taunt,G], 5/6, 11/11 [Taunt], 2/8, 5/4, 5/4, 2/2 [Taunt]
  Tavern (7 items): Glowscale 4/6 T5 $3 | Accord-o-Tron 3/3 T3 $3 | Zesty Shaker 6/7 T4 $3 | Ashen Corruptor 6/6 T5 $3 | Seafloor Recruiter 3/5 T4 $3 | Unmasked Identity (spell) T5 $3 | Blazing Skyfin 2/4 T2 $3
  Hand: 8 cards

  → Board (7/7): 8/8 [Taunt,G], 5/6, 11/11 [Taunt], 2/8, 5/4, 5/4, 6/7
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=17 Armor=0 Gold=10 Tier=5

  Board (7/7): 8/2, 5/6, 5/8 [Taunt], 9/7, 5/9 [Taunt], 4/5, 2/2
  Tavern (6 items): Technical Element 5/6 T3 $3 | Dustbone Devastator 2/6 T3 $3 | Old Soul 3/4 T2 $3 | Wyvern Outrider 2/8 T4 $3 | Zesty Shaker 6/7 T4 $3 | Wave of Gold (spell) T5 $2
  Hand: 4 cards

  → Board (7/7): 8/2, 5/6, 5/8 [Taunt], 9/7, 5/9 [Taunt], 4/5, 6/7
  → Tier 5→6 | Gold 10→0 | Hand 4→3
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=13 Armor=0 Gold=10 Tier=5

  Board (7/7): 5/6, 9/12, 3/5, 5/3 [Taunt], 5/8, 5/4, 1/1 [DS]
  Tavern (6 items): Bazaar Dealer 4/6 T5 $3 | Imposing Percussionist 4/4 T4 $3 | Charging Czarina 4/1 T5 $3 | Imposing Percussionist 4/4 T4 $3 | Ominous Seer 2/1 T1 $3 | Channel the Devourer (spell) T5 $4
  Hand: 4 cards

  → Board (7/7): 5/6, 9/12, 3/5, 5/3 [Taunt], 5/8, 5/4, 4/6
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=15 Armor=0 Gold=10 Tier=5

  Board (7/7): 6/6 [Taunt], 9/6, 6/7, 4/6, 2/7, 4/4 [DS], 1/3
  Tavern (6 items): Marquee Ticker 3/7 T4 $3 | Wintergrasp Ghoul 5/3 T5 $3 | Mummifier 5/2 T3 $3 | Metallic Hunter 4/2 T2 $3 | Tichondrius 3/6 T5 $3 | Misplaced Tea Set (spell) T4 $2
  Hand: 1 cards

  → Board (6/7): 6/6 [Taunt], 9/6, 6/7, 4/6, 4/4 [DS], 3/7
  → Tier 5→6 | Gold 10→0 | Hand 1→0
  → Actions: (auto)

**Combat Phase**

  [heur] Ysera vs [heur] Drek'Thar (first: Ysera)
     Ysera: [8/8, 5/6, 11/11, 2/8, 5/4, 5/4, 6/7]
     Drek'Thar: [6/6, 9/6, 6/7, 4/6, 4/4, 3/7]
     Scarlet Survivor 8/8→8/2  |  Alert Alarmist 6/6→6/0 DEAD
     Eternal Knight 9/6→10/0 DEAD  |  Scarlet Survivor 8/2→8/0 DEAD
     Dustbone Devastator 5/6→6/2  |  Sewer Lord 4/6→4/1
     Zesty Shaker 6/7→6/0 DEAD  |  Trigore the Lasher 11/11→11/5
     Trigore the Lasher 11/5→11/2  |  Marquee Ticker 3/7→3/0 DEAD
     Sewer Lord 4/1→4/0 DEAD  |  Trigore the Lasher 11/2→11/0 DEAD
     Incubation Researcher 2/8→2/4  |  Holo Rover 4/4→4/4
     Holo Rover 4/4→4/0 DEAD  |  Dustbone Devastator 6/2→6/0 DEAD
     Result: 4 vs 0 — heur
  [heur] Overlord Saurfang vs [heur] Inge, the Iron Hymn (first: Overlord Saurfang)
     Overlord Saurfang: [22/23, 30/31, 32/33, 29/34, 32/29, 31/29, 3/1]
     Inge, the Iron Hymn: [8/2, 5/6, 5/8, 9/7, 5/9, 4/5, 6/7]
     Zesty Shaker 22/23→22/18  |  Marquee Ticker 5/9→5/0 DEAD
     Eternal Knight 8/2→9/0 DEAD  |  Shadowdancer 31/29→31/21
     Technical Element 30/31→30/26  |  Banana Slamma 5/8→5/0 DEAD
     Woodland Defiler 5/6→5/0 DEAD  |  Shadowdancer 31/21→31/16
     Zesty Shaker 32/33→32/29  |  Darkcrest Strategist 4/5→4/0 DEAD
     Trigore the Lasher 9/7→9/0 DEAD  |  Shadowdancer 31/16→31/7
     Lurking Leviathan 29/34→29/28  |  Zesty Shaker 6/7→6/0 DEAD
     Result: 7 vs 0 — heur
  [heur] Sneed vs [heur] Sylvanas Windrunner (first: Sneed)
     Sneed: [8/5, 5/6, 9/16, 6/4, 3/8, 4/6, 4/6]
     Sylvanas Windrunner: [5/6, 9/12, 3/5, 5/3, 5/8, 5/4, 4/6]
     Manasaber 8/5→8/0 DEAD  |  Rylak Metalhead 5/3→5/0 DEAD
     Technical Element 5/6→5/2  |  Glowscale 4/6→4/1
     Technical Element 5/6→5/1  |  Technical Element 5/2→5/0 DEAD
     Trigore the Lasher 9/12→9/8  |  Glowscale 4/1→4/0 DEAD
     Trigore the Lasher 9/16→9/13  |  Hunting Tiger Shark 3/5→3/0 DEAD
     Eternal Tycoon 5/8→5/4  |  Glowscale 4/6→4/1
     Old Soul 6/4→6/0 DEAD  |  Bazaar Dealer 4/6→4/0 DEAD
     Malchezaar, Prince of Dance 5/4→5/0 DEAD  |  Glowscale 4/1→4/0 DEAD
     Iridescent Skyblazer 6/11→6/11  |  Trigore the Lasher 9/8→9/2
     Result: 3 vs 2 — heur

  **Drek'Thar [Heuristic] eliminated!** (Turn 11)
  Alive: 5/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Sneed (HP=22, Tier=6) | Ysera (HP=16, Tier=6) | Sylvanas Windrunner (HP=13, Tier=6) | Inge, the Iron Hymn (HP=2, Tier=6)

### Turn 12

**Sneed** [Heuristic]  HP=22 Armor=0 Gold=10 Tier=6

  Board (7/7): 8/5, 5/6, 9/19, 6/4 [G], 3/8 [DS], 4/6 [Taunt], 4/6 [Taunt]
  Tavern (7 items): Wyvern Outrider 2/8 T4 $3 | Ruthless Queensguard 3/3 T6 $3 | Banana Slamma 3/6 T4 $3 | Divine Sparkbot 4/2 T5 $3 | Prosthetic Hand 3/1 T4 $3 | P-0UL-TR-0N 10/10 T6 $3 | Shiny Ring (spell) T3 $2
  Hand: 9 cards

  → Board (7/7): 8/5, 5/6, 9/19, 3/8 [DS], 10/10 [DS], 10/16 [DS], 4/2 [Taunt,DS]
  → Gold 10→0 | Hand 9→6
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=10 Tier=6

  Board (7/7): 22/23, 30/31, 32/33, 29/34, 32/29, 31/29 [Taunt], 3/1 [Reborn]
  Tavern (7 items): Reef Riffer 37/36 T2 $3 | Consummate Conqueror 43/41 T6 $3 | Waverider 36/42 T4 $3 | Catacomb Crasher 38/44 T5 $3 | Cord Puller 35/35 T1 $3 | Deathly Striker 42/42 T6 $3 | Bargain Bundle (spell) T5 $5
  Hand: 1 cards

  → Board (7/7): 32/33, 29/34, 43/41, 48/48, 38/44, 36/42, 37/36
  → Gold 10→0 | Hand 1→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=16 Armor=0 Gold=10 Tier=6

  Board (7/7): 8/8 [Taunt,G], 6/6, 11/14 [Taunt], 2/8, 5/4, 5/4, 6/7
  Tavern (8 items): Hunting Tiger Shark 3/5 T4 $3 | Moonsteel Juggernaut 8/8 T6 $3 | Hardy Orca 1/6 T3 $3 | Forsaken Weaver 7/10 T6 $3 | Soul Rewinder 4/1 T2 $3 | Junk Jouster 8/7 T6 $3 | Saloon's Finest (spell) T5 $2 | Nightbane, Ignited 16/8 T6 $3
  Hand: 9 cards

  → Board (7/7): 8/8 [Taunt,G], 6/6, 11/14 [Taunt], 16/8 [Taunt], 7/10, 8/8, 3/5
  → Gold 10→0 | Hand 9→10
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=2 Armor=0 Gold=10 Tier=6

  Board (7/7): 9/2, 5/6, 5/8 [Taunt], 9/9, 5/9 [Taunt], 4/5, 6/7
  Tavern (7 items): Stomping Stegodon 5/5 T4 $3 | Ring Bearer 6/11 T6 $3 | Glowscale 5/7 T5 $3 | Deep-Sea Angler 3/4 T3 $3 | Accord-o-Tron 4/4 T3 $3 | Eternal Knight 9/7 T2 $3 | Angler's Lure (spell) T1 $3
  Hand: 4 cards

  → Board (7/7): 5/8 [Taunt], 9/9, 5/9 [Taunt], 6/7, 6/11, 9/7, 4/4
  → Gold 10→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=13 Armor=0 Gold=10 Tier=6

  Board (7/7): 5/6, 9/16, 3/5, 5/3 [Taunt], 5/8, 5/4, 4/6
  Tavern (7 items): Old Soul 4/4 T2 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Void Pup Trainer 7/7 T5 $3 | Accord-o-Tron 3/3 T3 $3 | Holo Rover 4/4 T4 $3 | Spiked Savior 8/2 T5 $3 | Sanctify (spell) T5 $1
  Hand: 5 cards

  → Board (7/7): 5/6, 9/16, 5/8, 4/6, 7/7, 8/2 [Taunt,Reborn], 4/4 [DS]
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Ysera vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Ysera: [8/8, 6/6, 11/14, 16/8, 7/10, 8/8, 3/5]
     Overlord Saurfang: [32/33, 29/34, 43/41, 48/48, 38/44, 36/42, 37/36]
     Zesty Shaker 32/33→32/25  |  Scarlet Survivor 8/8→8/0 DEAD
     Dustbone Devastator 6/6→7/0 DEAD  |  Deathly Striker 48/48→48/42
     Lurking Leviathan 29/34→29/18  |  Nightbane, Ignited 16/8→16/0 DEAD
     Trigore the Lasher 11/14→11/0 DEAD  |  Zesty Shaker 32/25→32/14
     Consummate Conqueror 43/41→43/22  |  Hunting Tiger Shark 19/5→19/0 DEAD
     Forsaken Weaver 24/10→24/0 DEAD  |  Consummate Conqueror 43/22→43/0 DEAD
     Deathly Striker 48/42→48/34  |  Moonsteel Juggernaut 8/8→8/0 DEAD
     Result: 0 vs 6 — heur
  [heur] Sneed vs [heur] Inge, the Iron Hymn (first: Sneed)
     Sneed: [8/5, 5/6, 9/19, 3/8, 10/10, 10/16, 4/2]
     Inge, the Iron Hymn: [5/8, 9/9, 5/9, 6/7, 6/11, 9/7, 4/4]
     Manasaber 8/5→8/0 DEAD  |  Marquee Ticker 5/9→5/1
     Banana Slamma 5/8→5/4  |  Divine Sparkbot 4/2→4/2
     Technical Element 5/6→5/1  |  Banana Slamma 5/4→5/0 DEAD
     Trigore the Lasher 9/9→9/5  |  Divine Sparkbot 4/2→4/0 DEAD
     Trigore the Lasher 9/19→9/14  |  Marquee Ticker 5/1→5/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Trigore the Lasher 9/14→9/8
     Iridescent Skyblazer 4/9→4/9  |  Trigore the Lasher 9/5→9/1
     Ring Bearer 6/11→6/6  |  Technical Element 5/1→5/0 DEAD
     P-0UL-TR-0N 10/10→10/10  |  Eternal Knight 9/7→10/0 DEAD
     Accord-o-Tron 4/4→4/0 DEAD  |  Iridescent Skyblazer 4/9→4/5
     Wyvern Outrider 10/16→10/16  |  Trigore the Lasher 9/1→9/0 DEAD
     Result: 4 vs 1 — heur

  Alive: 5/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Sneed (HP=22, Tier=6) | Sylvanas Windrunner (HP=13, Tier=6) | Inge, the Iron Hymn (HP=2, Tier=6) | Ysera (HP=1, Tier=6)

### Turn 13

**Sneed** [Heuristic]  HP=22 Armor=0 Gold=10 Tier=6

  Board (7/7): 8/5, 5/6, 9/23, 3/8 [DS], 10/10 [DS], 10/16 [DS], 4/2 [Taunt,DS]
  Tavern (7 items): Sprightly Scarab 3/1 T3 $3 | Eternal Summoner 8/1 T6 $3 | Picky Eater 1/1 T1 $3 | Marquee Ticker 3/7 T4 $3 | Deep Blue Crooner 2/2 T3 $3 | Leeching Felhound 3/3 T3 $3 | Perfect Vision (spell) T6 $2
  Hand: 8 cards

  → Board (7/7): 9/6 [Reborn], 5/6, 9/23, 9/8 [DS], 16/10 [DS], 16/16 [DS], 1/1
  → Gold 10→0 | HP 22→19 | Hand 8→7
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=10 Tier=6

  Board (7/7): 32/33, 29/34, 43/41, 48/48, 38/44, 36/42, 37/36
  Tavern (7 items): Rylak Metalhead 46/44 T4 $3 | Hardy Orca 42/47 T3 $3 | Old Soul 44/45 T2 $3 | Ruthless Queensguard 44/44 T6 $3 | Wrath Weaver 42/45 T1 $3 | Leeching Felhound 44/44 T3 $3 | Glowing Crown (spell) T1 $3
  Hand: 2 cards

  → Board (7/7): 48/48, 54/52 [Taunt], 44/49 [Taunt], 44/45, 50/50, 44/44, 42/45
  → Gold 10→0 | Armor 17→14 | Hand 2→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=1 Armor=0 Gold=10 Tier=6

  Board (7/7): 8/8 [Taunt,G], 7/6, 11/16 [Taunt], 16/8 [Taunt], 8/10, 8/8, 3/5
  Tavern (8 items): Abyssal Bruiser 1/1 T4 $3 | Imposing Percussionist 4/4 T4 $3 | Eternal Summoner 13/1 T6 $3 | Seafloor Recruiter 3/5 T4 $3 | Wrath Weaver 1/4 T1 $3 | Hardy Orca 1/6 T3 $3 | Arcane Absorption (spell) T4 $1 | Scarlet Survivor 3/3 T1 $3
  Hand: 12 cards

  → Board (7/7): 8/8 [Taunt,G], 7/6, 11/16 [Taunt], 16/8 [Taunt], 8/10, 8/8, 8/2 [Taunt,Reborn]
  → Gold 10→0 | Hand 12→11
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=2 Armor=0 Gold=11 Tier=6

  Board (7/7): 5/8 [Taunt], 9/14, 5/9 [Taunt], 6/7, 6/11, 10/7, 4/4
  Tavern (7 items): Leeching Felhound 9/9 T3 $3 | Tichondrius 9/12 T5 $3 | Wintergrasp Ghoul 11/9 T5 $3 | Deep-Sea Angler 8/9 T3 $3 | Humming Bird 7/10 T2 $3 | Nightmare Par-tea Guest 9/9 T5 $3 | Lost Staff of Hamuul (spell) T6 $2
  Hand: 6 cards

  → Board (7/7): 9/14, 10/7, 9/12, 11/9, 9/9 [Reborn], 9/9 [Taunt], 8/9
  → Gold 11→0 | Hand 6→5
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=13 Armor=0 Gold=10 Tier=6

  Board (7/7): 5/6, 9/19, 5/8, 4/6, 7/7, 8/2 [Taunt,Reborn], 4/4 [DS]
  Tavern (7 items): Monstrous Macaw 5/4 T4 $3 | Eternal Tycoon 5/8 T5 $3 | Groundbreaker 5/4 T6 $3 | False Implicator 3/3 T3 $3 | Catacomb Crasher 5/10 T5 $3 | Divine Sparkbot 4/2 T5 $3 | Evolving Strategy (spell) T1 $3
  Hand: 5 cards

  → Board (7/7): 5/6, 9/19, 5/8, 7/7, 5/10, 5/8, 3/3
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Sylvanas Windrunner vs [heur] Ysera (first: Ysera)
     Sylvanas Windrunner: [5/6, 9/19, 5/8, 7/7, 5/10, 5/8, 3/3]
     Ysera: [8/8, 7/6, 11/16, 16/8, 8/10, 8/8, 8/2]
     Scarlet Survivor 8/8→8/3  |  Eternal Tycoon 5/8→5/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Trigore the Lasher 11/16→11/11
     Dustbone Devastator 7/6→8/1  |  Catacomb Crasher 5/10→5/3
     Trigore the Lasher 9/19→9/3  |  Nightbane, Ignited 16/8→16/0 DEAD
     Trigore the Lasher 27/11→27/8  |  False Implicator 3/3→3/0 DEAD
     Void Pup Trainer 7/7→7/0 DEAD  |  Scarlet Survivor 8/3→8/0 DEAD
     Forsaken Weaver 9/10→9/1  |  Trigore the Lasher 9/3→9/0 DEAD
     Catacomb Crasher 5/3→5/0 DEAD  |  Trigore the Lasher 27/1→27/0 DEAD
     Moonsteel Juggernaut 8/8→8/3  |  Eternal Tycoon 5/8→5/0 DEAD
     Result: 0 vs 3 — heur
  [heur] Inge, the Iron Hymn vs [heur] Overlord Saurfang (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [9/14, 10/7, 9/12, 11/9, 9/9, 9/9, 8/9]
     Overlord Saurfang: [48/48, 54/52, 44/49, 44/45, 50/50, 44/44, 42/45]
     Trigore the Lasher 9/14→9/0 DEAD  |  Hardy Orca 44/49→44/40
     Deathly Striker 48/48→48/39  |  Nightmare Par-tea Guest 9/9→9/0 DEAD
     Eternal Knight 10/7→11/0 DEAD  |  Hardy Orca 44/40→44/30
     Rylak Metalhead 54/52→54/44  |  Deep-Sea Angler 8/9→8/0 DEAD
     Tichondrius 9/12→9/0 DEAD  |  Hardy Orca 44/30→44/21
     Hardy Orca 44/21→44/12  |  Leeching Felhound 9/9→9/0 DEAD
     Wintergrasp Ghoul 11/9→11/0 DEAD  |  Hardy Orca 44/12→44/1
     Result: 0 vs 7 — heur

  **Inge, the Iron Hymn [Heuristic] eliminated!** (Turn 13)
  **Sylvanas Windrunner [Heuristic] eliminated!** (Turn 13)
  Alive: 3/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Sneed (HP=19, Tier=6) | Ysera (HP=1, Tier=6)

### Turn 14

**Sneed** [Heuristic]  HP=19 Armor=0 Gold=10 Tier=6

  Board (7/7): 9/6 [Reborn], 5/6, 9/26, 9/8 [DS], 16/10 [DS], 16/16 [DS], 1/1
  Tavern (7 items): One-Amalgam Tour Group 6/7 T6 $3 | Abyssal Bruiser 1/1 T4 $3 | Scarlet Skull 2/1 T2 $3 | Banana Slamma 3/6 T4 $3 | Bazaar Dealer 4/6 T5 $3 | Goldrinn, the Great Wolf 8/8 T6 $3 | Natural Blessing (spell) T4 $4
  Hand: 8 cards

  → Board (7/7): 12/9 [Reborn], 11/28, 10/9 [DS], 16/10 [DS], 18/18 [DS], 8/8, 3/2 [Reborn]
  → Gold 10→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=14 Gold=10 Tier=6

  Board (7/7): 48/48, 54/52 [Taunt], 44/49 [Taunt], 44/45, 50/50, 44/44, 42/45
  Tavern (7 items): Annoy-o-Tron 47/48 T1 $3 | Malchezaar, Prince of Dance 51/50 T4 $3 | Wyvern Outrider 48/54 T4 $3 | Imposing Percussionist 50/50 T4 $3 | Dustbone Devastator 48/52 T3 $3 | Stomping Stegodon 50/50 T4 $3 | Misplaced Tea Set (spell) T4 $2
  Hand: 0 cards

  → Board (7/7): 54/52 [Taunt], 50/50, 48/54, 51/50, 50/50, 48/52, 50/50
  → Gold 10→0 | Armor 14→10 | Hand 0→1
  → Actions: (auto)

**Ysera** [Heuristic]  HP=1 Armor=0 Gold=10 Tier=6

  Board (7/7): 8/8 [Taunt,G], 8/6, 11/22 [Taunt], 16/8 [Taunt], 9/10, 8/8, 8/2 [Taunt,Reborn]
  Tavern (7 items): Prosthetic Hand 3/1 T4 $3 | Sprightly Scarab 3/1 T3 $3 | Risen Rider 8/1 T1 $3 | Glowscale 4/6 T5 $3 | Ashen Corruptor 6/6 T5 $3 | Deep-Sea Angler 2/3 T3 $3 | Blazing Skyfin 2/4 T2 $3
  Hand: 13 cards

  → Board (7/7): 8/8 [Taunt,G], 8/6, 11/22 [Taunt], 16/8 [Taunt], 9/10, 8/8, 6/4
  → Gold 10→0 | Hand 13→12
  → Actions: (auto)

**Combat Phase**

  [heur] Sneed vs [heur] Ysera (first: Sneed)
     Sneed: [12/9, 11/28, 10/9, 16/10, 18/18, 8/8, 3/2]
     Ysera: [8/8, 8/6, 11/22, 16/8, 9/10, 8/8, 6/4]
     Manasaber 12/9→12/1  |  Scarlet Survivor 8/8→8/0 DEAD
     Dustbone Devastator 8/6→9/3  |  Scarlet Skull 3/2→3/0 DEAD
     Trigore the Lasher 11/28→11/12  |  Nightbane, Ignited 16/8→16/0 DEAD
     Trigore the Lasher 11/22→11/6  |  P-0UL-TR-0N 16/10→16/10
     Iridescent Skyblazer 10/9→10/9  |  Trigore the Lasher 11/6→11/0 DEAD
     Forsaken Weaver 10/10→10/0 DEAD  |  P-0UL-TR-0N 16/10→16/0 DEAD
     Wyvern Outrider 19/19→19/19  |  Red Chromadrake 22/4→22/0 DEAD
     Moonsteel Juggernaut 8/8→8/0 DEAD  |  Trigore the Lasher 11/12→11/4
     Goldrinn, the Great Wolf 9/9→9/0 DEAD  |  Dustbone Devastator 25/3→25/0 DEAD
     Result: 4 vs 0 — heur

  **Ysera [Heuristic] eliminated!** (Turn 14)
  Alive: 2/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Sneed (HP=19, Tier=6)

### Turn 15

**Sneed** [Heuristic]  HP=19 Armor=0 Gold=10 Tier=6

  Board (7/7): 12/9 [Reborn], 11/32, 10/9 [DS], 16/10 [DS], 18/18 [DS], 8/8, 3/2 [Reborn]
  Tavern (6 items): False Implicator 1/1 T3 $3 | Ruthless Queensguard 3/3 T6 $3 | Waverider 2/8 T4 $3 | Scarlet Skull 2/1 T2 $3 | Seafloor Recruiter 3/5 T4 $3 | Sewer Lord 4/6 T5 $3
  Hand: 8 cards

  → Board (7/7): 17/14 [Reborn], 15/36, 18/17 [DS], 17/11 [DS], 22/22 [DS], 9/9, 3/2 [Reborn]
  → Gold 10→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=10 Gold=10 Tier=6

  Board (7/7): 54/52 [Taunt], 50/50, 48/54, 51/50, 50/50, 48/52, 50/50
  Tavern (6 items): Shadowdancer 54/52 T5 $3 | Junk Jouster 57/56 T6 $3 | Ruthless Queensguard 52/52 T6 $3 | Deep Blue Crooner 51/51 T3 $3 | Drustfallen Butcher 51/56 T5 $3 | Tranquil Meditative 52/57 T5 $3
  Hand: 1 cards

  → Board (7/7): 54/52 [Taunt], 48/54, 57/56, 52/57, 51/56, 54/52 [Taunt], 62/62
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Sneed vs [heur] Overlord Saurfang (first: Sneed)
     Sneed: [17/14, 15/36, 18/17, 17/11, 22/22, 9/9, 3/2]
     Overlord Saurfang: [54/52, 48/54, 57/56, 52/57, 51/56, 54/52, 62/62]
     Manasaber 17/14→17/0 DEAD  |  Shadowdancer 54/52→54/35
     Rylak Metalhead 54/52→54/35  |  P-0UL-TR-0N 17/11→17/11
     Trigore the Lasher 16/37→16/0 DEAD  |  Rylak Metalhead 54/35→54/19
     Wyvern Outrider 48/54→48/32  |  Wyvern Outrider 22/22→22/22
     Iridescent Skyblazer 18/17→18/17  |  Shadowdancer 54/35→54/17
     Junk Jouster 57/56→57/53  |  Scarlet Skull 3/2→3/0 DEAD
     P-0UL-TR-0N 17/11→17/0 DEAD  |  Rylak Metalhead 54/19→54/2
     Tranquil Meditative 52/57→52/35  |  Wyvern Outrider 22/22→22/0 DEAD
     Goldrinn, the Great Wolf 10/10→10/0 DEAD  |  Rylak Metalhead 54/2→54/0 DEAD
     Drustfallen Butcher 51/56→51/33  |  Iridescent Skyblazer 23/22→23/0 DEAD
     Result: 0 vs 6 — heur

  **Sneed [Heuristic] eliminated!** (Turn 15)
  **Overlord Saurfang [Heuristic] eliminated!** (Turn 15)

---

## Final Standings

| # | Hero | Role | HP | Tier | Eliminated |
|---|---|---|---|---|---|
| 1 | Overlord Saurfang | Heuristic | 30 | 6 | 15 |
| 2 | Sneed | Heuristic | 0 | 6 | 15 |
| 3 | Ysera | Heuristic | 0 | 6 | 14 |
| 4 | Inge, the Iron Hymn | Heuristic | 0 | 6 | 13 |
| 5 | Sylvanas Windrunner | Heuristic | 0 | 6 | 13 |
| 6 | Drek'Thar | Heuristic | 0 | 6 | 11 |
| 7 | Yogg-Saron, Hope's End | AGENT | 0 | 2 | 9 |
| 8 | Professor Putricide | Heuristic | 0 | 5 | 9 |