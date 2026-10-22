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

  → Gold 8→1 | Trinket: Yu'lon Sticker
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
     Manasaber 8/2→8/0 DEAD  |  Tide Raiser 2/1→2/0 DEAD
     Sklibb, Demon Hunter 4/4→4/1  |  Laboratory Assistant 3/4→3/0 DEAD
     Result: 4 vs 0 — heur
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
  HP: Sneed (HP=30, Tier=3) | Overlord Saurfang (HP=30, Tier=3) | Ysera (HP=30, Tier=3) | Inge, the Iron Hymn (HP=30, Tier=3) | Drek'Thar (HP=30, Tier=3) | Yogg-Saron, Hope's End (HP=23, Tier=2) | Sylvanas Windrunner (HP=23, Tier=3) | Professor Putricide (HP=19, Tier=3)

### Turn 7

**Yogg-Saron, Hope's End** [RL AGENT]  HP=23 Armor=0 Gold=9 Tier=2

  Board (3/7): 8/2 [G], 6/2, 3/4
  Tavern (4 items): Shell Collector 4/3 T2 $3 | Eternal Knight 4/2 T2 $3 | Cord Puller 1/1 T1 $3 | Metallic Hunter 4/2 T2 $3
  Hand: 0 cards

  → Board (4/7): 8/2 [G], 6/2, 3/4, 4/3
  → Gold 9→5 | Hand 0→1
  → Actions: buy_tavern_0, play_hand_0, refresh

**Sneed** [Heuristic]  HP=30 Armor=2 Gold=9 Tier=3

  Board (7/7): 2/1, 4/1, 4/1, 4/3, 3/4, 5/6, 3/4
  Tavern (4 items): Sprightly Scarab 3/1 T3 $3 | Leeching Felhound 3/3 T3 $3 | Floating Watcher 4/4 T3 $5 | Technical Element 5/6 T3 $3
  Hand: 3 cards

  → Board (7/7): 4/1, 4/1, 8/7, 3/4, 5/6, 3/4, 5/6
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

  → Board (7/7): 6/6 [G], 6/6 [Taunt], 4/2, 2/1 [Taunt], 2/3, 3/2, 2/6
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
     Sneed: [4/1, 4/1, 8/7, 3/4, 5/6, 3/4, 5/6]
     Overlord Saurfang: [13/16, 2/4, 10/11, 10/9, 16/13, 16/13, 17/18]
     Manasaber 4/1→4/0 DEAD  |  Taunt Test Minion 2/4→2/0 DEAD
     Wrath Weaver 13/16→13/8  |  Shell Collector 8/7→8/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Mummifier 16/13→16/9
     Old Soul 10/11→10/8  |  Laboratory Assistant 3/4→3/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Mummifier 16/13→16/8
     Sewer Rat 10/9→10/6  |  Old Soul 3/4→3/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Mummifier 16/9→16/4
     Result: 0 vs 6 — heur
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
     Yogg-Saron, Hope's End: [8/2, 6/2, 3/4, 4/3]
     Manasaber 4/1→4/0 DEAD  |  Festergut 6/2→6/0 DEAD
     Manasaber 8/2→8/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Old Soul 3/4→3/1  |  Laboratory Assistant 3/4→3/1
     Laboratory Assistant 3/1→3/0 DEAD  |  Old Soul 3/1→3/0 DEAD
     Sewer Rat 3/2→3/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Result: 3 vs 0 — heur
  [heur] Professor Putricide vs [heur] Ysera (first: Professor Putricide)
     Professor Putricide: [4/1, 1/1, 10/2, 10/2, 5/2, 3/4, 5/6]
     Ysera: [6/6, 6/6, 4/2, 2/1, 2/3, 3/2, 2/6]
     Manasaber 4/1→4/0 DEAD  |  Sklibb, Demon Hunter 6/6→6/2
     Scarlet Survivor 6/6→6/0 DEAD  |  Eternal Knight 10/2→11/0 DEAD
     Cord Puller 1/1→1/1  |  Tide Raiser 2/1→2/0 DEAD
     Sklibb, Demon Hunter 6/2→6/1  |  Cord Puller 1/1→1/0 DEAD
     Eternal Knight 11/2→12/0 DEAD  |  Sklibb, Demon Hunter 6/1→6/0 DEAD
     Metallic Hunter 4/2→4/0 DEAD  |  Mummifier 5/2→5/0 DEAD
     Ancestral Automaton 3/4→3/1  |  Sewer Rat 3/2→3/0 DEAD
     Deep-Sea Angler 3/5→3/0 DEAD  |  Technical Element 5/6→5/3
     Technical Element 5/3→5/1  |  Dustbone Devastator 2/6→2/1
     Dustbone Devastator 2/1→3/0 DEAD  |  Technical Element 5/1→5/0 DEAD
     Result: 1 vs 0 — heur

  Alive: 8/8
  HP: Overlord Saurfang (HP=30, Tier=4) | Inge, the Iron Hymn (HP=30, Tier=4) | Drek'Thar (HP=30, Tier=4) | Ysera (HP=25, Tier=4) | Sneed (HP=22, Tier=4) | Professor Putricide (HP=19, Tier=4) | Yogg-Saron, Hope's End (HP=13, Tier=2) | Sylvanas Windrunner (HP=13, Tier=4)

### Turn 8

**Yogg-Saron, Hope's End** [RL AGENT]  HP=13 Armor=0 Gold=10 Tier=2

  Board (4/7): 8/2 [G], 6/2, 3/4, 4/3
  Tavern (5 items): Reef Riffer 3/2 T2 $3 | Alert Alarmist 2/2 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Sick Riffs (spell) T1 $3
  Hand: 1 cards

  → Board (5/7): 8/2 [G], 6/2, 3/4, 4/3, 3/4
  → Gold 10→6
  → Actions: buy_tavern_2, play_hand_1, refresh

**Sneed** [Heuristic]  HP=22 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/1, 4/1, 8/7, 3/4, 5/6, 3/4, 5/6
  Tavern (6 items): Hardy Orca 1/6 T3 $3 | Metallic Hunter 4/2 T2 $3 | Rimescale Priestess 3/3 T4 $3 | Zesty Shaker 6/7 T4 $3 | Holo Rover 4/4 T4 $3 | Arcane Absorption (spell) T4 $1
  Hand: 4 cards

  → Board (7/7): 8/7, 5/6 [DS], 5/6, 6/7, 4/4 [DS], 1/6 [Taunt], 3/3
  → Gold 10→0 | Hand 4→3
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=10 Tier=4

  Board (7/7): 13/16 [G], 2/4 [Taunt], 10/11, 10/9, 16/13, 16/13, 17/18
  Tavern (6 items): Trigore the Lasher 25/19 T4 $3 | Seafloor Recruiter 19/21 T4 $3 | Prosthetic Hand 19/17 T4 $3 | Malchezaar, Prince of Dance 21/20 T4 $3 | Hunting Tiger Shark 19/21 T4 $3 | Gem Confiscation (spell) T4 $1
  Hand: 0 cards

  → Board (7/7): 15/18 [G], 17/18, 25/19, 21/20, 19/21, 19/21, 19/17 [Reborn]
  → Gold 10→0 | Armor 17→16 | Hand 0→1
  → Actions: (auto)

**Ysera** [Heuristic]  HP=25 Armor=0 Gold=10 Tier=4

  Board (7/7): 6/6 [G], 6/6 [Taunt], 4/2, 2/1 [Taunt], 2/3, 3/2, 3/6
  Tavern (7 items): Deflect-o-Bot 3/2 T3 $3 | Annoy-o-Module 2/4 T3 $3 | Woodland Defiler 5/6 T4 $3 | Stomping Stegodon 4/4 T4 $3 | Banana Slamma 3/6 T4 $3 | Conflagration (spell) T4 $2 | Roaring Recruiter 2/8 T3 $3
  Hand: 2 cards

  → Board (7/7): 6/6 [G], 6/6 [Taunt], 3/6, 5/6, 4/10 [Taunt], 3/6, 2/4 [Taunt,DS]
  → Gold 10→0 | Hand 2→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=10 Tier=4

  Board (7/7): 4/1, 4/1, 3/4, 3/2, 3/4, 5/2, 5/2
  Tavern (6 items): Wyvern Outrider 2/8 T4 $3 | False Implicator 1/1 T3 $3 | Enchanted Sentinel 3/5 T4 $3 | Lava Lurker 2/5 T2 $3 | Handless Forsaken 2/1 T3 $3 | Temperature Shift (spell) T4 $4
  Hand: 0 cards

  → Board (7/7): 3/4, 5/2, 5/2, 2/8, 3/5, 2/5, 1/1
  → Gold 10→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=19 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/1, 1/1 [DS], 12/2, 12/2, 5/2, 3/1, 5/6
  Tavern (6 items): False Implicator 1/1 T3 $3 | Hunting Tiger Shark 3/5 T4 $3 | Deflect-o-Bot 3/2 T3 $3 | Rylak Metalhead 5/3 T4 $3 | Holo Rover 4/4 T4 $3 | Natural Blessing (spell) T4 $4
  Hand: 0 cards

  → Board (7/7): 12/2, 12/2, 5/6, 3/5, 5/3 [Taunt], 4/4 [DS], 1/1
  → Gold 10→0 | Hand 0→1
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=13 Armor=0 Gold=10 Tier=4

  Board (7/7): 3/1 [Taunt,Reborn], 1/1 [DS], 3/1 [Taunt,Reborn], 4/3, 2/4, 5/6, 2/4 [Taunt,DS]
  Tavern (6 items): Deep Blue Crooner 2/2 T3 $3 | Ominous Seer 2/1 T1 $3 | Zesty Shaker 6/7 T4 $3 | Abyssal Bruiser 1/1 T4 $3 | Accord-o-Tron 3/3 T3 $3 | Tomb Turning (spell) T4 $2
  Hand: 0 cards

  → Board (7/7): 4/3, 2/4, 5/6, 2/4 [Taunt,DS], 6/7, 3/3, 1/1 [DS]
  → Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=10 Tier=4

  Board (7/7): 1/4, 3/4, 6/6 [Taunt], 6/2, 3/2, 1/3, 1/6 [Taunt]
  Tavern (6 items): Zesty Shaker 6/7 T4 $3 | Alert Alarmist 2/2 T2 $3 | Mummifier 5/2 T3 $3 | Woodland Defiler 5/6 T4 $3 | Deep-Sea Angler 2/3 T3 $3 | Easterly Winds (spell) T4 $1
  Hand: 1 cards

  → Board (7/7): 6/6 [Taunt], 6/2, 1/6 [Taunt], 6/7, 5/6, 9/6, 2/2 [Taunt]
  → Gold 10→0 | Hand 1→0
  → Actions: (auto)

**Combat Phase**

  [heur] Sylvanas Windrunner vs [heur] Inge, the Iron Hymn (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [4/3, 2/4, 5/6, 2/4, 6/7, 3/3, 1/1]
     Inge, the Iron Hymn: [3/4, 5/2, 5/2, 2/8, 3/5, 2/5, 1/1]
     Shell Collector 4/3→4/0 DEAD  |  Mummifier 5/2→5/0 DEAD
     Ancestral Automaton 3/4→3/2  |  Annoy-o-Module 2/4→2/4
     Nerubian Deathswarmer 2/4→2/2  |  Lava Lurker 2/5→2/3
     Eternal Knight 5/2→6/0 DEAD  |  Annoy-o-Module 2/4→2/0 DEAD
     Technical Element 5/6→5/4  |  Lava Lurker 2/3→2/0 DEAD
     Wyvern Outrider 2/8→2/7  |  Abyssal Bruiser 1/1→1/1
     Zesty Shaker 6/7→6/4  |  Enchanted Sentinel 3/5→3/0 DEAD
     False Implicator 1/1→1/0 DEAD  |  Zesty Shaker 6/4→6/3
     Accord-o-Tron 3/3→3/1  |  Wyvern Outrider 2/7→2/4
     Result: 5 vs 2 — heur
  [heur] Sneed vs [heur] Professor Putricide (first: Professor Putricide)
     Sneed: [8/7, 5/6, 5/6, 6/7, 4/4, 1/6, 3/3]
     Professor Putricide: [12/2, 12/2, 5/6, 3/5, 5/3, 4/4, 1/1]
     Eternal Knight 12/2→12/1  |  Hardy Orca 1/6→1/0 DEAD
     Shell Collector 8/7→8/2  |  Rylak Metalhead 5/3→5/0 DEAD
     Eternal Knight 12/2→13/0 DEAD  |  Shell Collector 8/2→8/0 DEAD
     Technical Element 5/6→5/6  |  Technical Element 5/6→5/1
     Technical Element 5/1→5/0 DEAD  |  Technical Element 5/6→5/1
     Technical Element 5/1→5/0 DEAD  |  Hunting Tiger Shark 3/5→3/0 DEAD
     Holo Rover 4/4→4/4  |  Rimescale Priestess 3/3→3/0 DEAD
     Zesty Shaker 6/7→6/6  |  False Implicator 1/1→1/0 DEAD
     Result: 3 vs 2 — heur
  [heur] Overlord Saurfang vs [AGENT] Yogg-Saron, Hope's End (first: Overlord Saurfang)
     Overlord Saurfang: [15/18, 17/18, 25/19, 21/20, 19/21, 19/21, 19/17]
     Yogg-Saron, Hope's End: [8/2, 6/2, 3/4, 4/3, 3/4]
     Wrath Weaver 15/18→15/15  |  Laboratory Assistant 3/4→3/0 DEAD
     Manasaber 8/2→8/0 DEAD  |  Trigore the Lasher 25/19→25/11
     Old Soul 17/18→17/12  |  Festergut 6/2→6/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Prosthetic Hand 19/17→19/14
     Trigore the Lasher 25/11→25/7  |  Shell Collector 4/3→4/0 DEAD
     Result: 7 vs 0 — heur
  [heur] Ysera vs [heur] Drek'Thar (first: Drek'Thar)
     Ysera: [6/6, 6/6, 3/6, 5/6, 4/10, 3/6, 2/4]
     Drek'Thar: [6/6, 6/2, 1/6, 6/7, 5/6, 9/6, 2/2]
     Alert Alarmist 6/6→6/0 DEAD  |  Sklibb, Demon Hunter 6/6→6/0 DEAD
     Scarlet Survivor 6/6→7/5  |  Alert Alarmist 2/2→2/0 DEAD
     Eternal Knight 6/2→7/0 DEAD  |  Roaring Recruiter 4/10→4/4
     Dustbone Devastator 3/6→4/5  |  Hardy Orca 1/6→1/3
     Hardy Orca 1/3→1/0 DEAD  |  Roaring Recruiter 4/4→4/3
     Woodland Defiler 5/6→5/0 DEAD  |  Mummifier 9/6→9/1
     Zesty Shaker 6/7→6/3  |  Roaring Recruiter 4/3→4/0 DEAD
     Banana Slamma 3/6→3/1  |  Woodland Defiler 5/6→5/3
     Woodland Defiler 5/3→5/1  |  Annoy-o-Module 2/4→2/4
     Annoy-o-Module 2/4→2/0 DEAD  |  Zesty Shaker 6/3→6/1
     Mummifier 9/1→9/0 DEAD  |  Banana Slamma 3/1→3/0 DEAD
     Result: 2 vs 2 — heur

  **Yogg-Saron, Hope's End [AGENT] eliminated!** (Turn 8)
  Alive: 7/8
  HP: Overlord Saurfang (HP=30, Tier=4) | Inge, the Iron Hymn (HP=30, Tier=4) | Drek'Thar (HP=30, Tier=4) | Ysera (HP=25, Tier=4) | Sneed (HP=22, Tier=4) | Professor Putricide (HP=19, Tier=4) | Sylvanas Windrunner (HP=13, Tier=4)

### Turn 9

**Sneed** [Heuristic]  HP=22 Armor=0 Gold=10 Tier=4

  Board (7/7): 8/7, 5/6 [DS], 5/6, 6/7, 4/4 [DS], 1/6 [Taunt], 3/3
  Tavern (6 items): Flaming Enforcer 4/5 T4 $3 | Technical Element 5/6 T3 $3 | Banana Slamma 3/6 T4 $3 | Rylak Metalhead 5/3 T4 $3 | Hunting Tiger Shark 3/5 T4 $3 | Eonar's Favor (spell) T4 $2
  Hand: 5 cards

  → Board (7/7): 8/7, 6/7, 4/4 [DS], 1/6 [Taunt], 10/12 [G], 6/4 [G], 5/2
  → Tier 4→5 | Gold 10→0 | Trinket: Precious Pearl
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=16 Gold=10 Tier=4

  Board (7/7): 15/18 [G], 17/18, 25/21, 21/20, 19/21, 19/21, 19/17 [Reborn]
  Tavern (6 items): Alert Alarmist 27/27 T2 $3 | Hunting Tiger Shark 28/30 T4 $3 | Waverider 27/33 T4 $3 | Sprightly Scarab 28/26 T3 $3 | Hardy Orca 26/31 T3 $3 | Boon of Beetles (spell) T4 $1
  Hand: 1 cards

  → Board (7/7): 17/18, 25/21, 21/20, 19/21, 19/21, 19/17 [Reborn], 8/8 [G]
  → Tier 4→5 | Gold 10→0 | Trinket: Beetle Band
  → Actions: (auto)

**Ysera** [Heuristic]  HP=25 Armor=0 Gold=10 Tier=4

  Board (7/7): 6/6 [G], 6/6 [Taunt], 4/6, 5/6, 4/10 [Taunt], 3/6, 2/4 [Taunt,DS]
  Tavern (7 items): Handless Forsaken 4/1 T3 $3 | Wyvern Outrider 2/8 T4 $3 | Rylak Metalhead 5/3 T4 $3 | Dustbone Devastator 4/6 T3 $3 | Handless Forsaken 4/1 T3 $3 | Glowing Crown (spell) T1 $3 | Tarecgosa 4/4 T2 $3
  Hand: 0 cards

  → Board (7/7): 6/6 [G], 6/6 [Taunt], 4/6, 5/6, 4/10 [Taunt], 3/6, 4/6
  → Tier 4→5 | Gold 10→0 | Trinket: Chromatic Tear | Hand 0→2
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=10 Tier=4

  Board (7/7): 3/4, 6/2, 5/2, 2/8, 3/5, 2/5, 1/1
  Tavern (6 items): Holo Rover 4/4 T4 $3 | Tide Raiser 2/1 T2 $3 | Reef Riffer 3/2 T2 $3 | Marquee Ticker 3/7 T4 $3 | Sewer Rat 3/2 T2 $3 | Sick Riffs (spell) T1 $3
  Hand: 0 cards

  → Board (6/7): 3/4, 6/2, 5/2, 2/8, 3/5, 2/5
  → Tier 4→5 | Gold 10→0 | Trinket: Accord-o-Tron Portrait
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=19 Armor=0 Gold=10 Tier=4

  Board (7/7): 13/2, 13/2, 5/6, 3/5, 5/3 [Taunt], 4/4 [DS], 1/1
  Tavern (6 items): Old Soul 3/4 T2 $3 | Reef Riffer 3/2 T2 $3 | Imposing Percussionist 4/4 T4 $3 | Sewer Rat 3/2 T2 $3 | Soul Rewinder 4/1 T2 $3 | Pointy Arrow (spell) T1 $1
  Hand: 3 cards

  → Tier 4→5 | Gold 10→0 | Trinket: Unholy Sanctum
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=13 Armor=0 Gold=11 Tier=4

  Board (7/7): 4/3, 2/4, 5/6, 2/4 [Taunt,DS], 6/7, 3/3, 1/1 [DS]
  Tavern (6 items): Dustbone Devastator 3/6 T3 $3 | Floating Watcher 4/4 T3 $5 | Rimescale Priestess 3/3 T4 $3 | Trigore the Lasher 9/3 T4 $3 | Deep-Sea Angler 2/3 T3 $3 | Misplaced Tea Set (spell) T4 $2
  Hand: 0 cards

  → Tier 4→5 | Gold 11→0 | Trinket: Fridge Magnet
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=10 Tier=4

  Board (7/7): 6/6 [Taunt], 7/2, 1/6 [Taunt], 6/7, 5/6, 9/6, 2/2 [Taunt]
  Tavern (6 items): Annoy-o-Tron 1/2 T1 $3 | Old Soul 3/4 T2 $3 | Handless Forsaken 2/1 T3 $3 | Stomping Stegodon 4/4 T4 $3 | Handless Forsaken 2/1 T3 $3 | Spitescale Special (spell) T4 $2
  Hand: 0 cards

  → Board (7/7): 6/6 [Taunt], 7/2, 1/6 [Taunt], 6/7, 5/6, 19/6, 13/4
  → Tier 4→5 | Gold 10→0 | Trinket: Artisanal Urn
  → Actions: (auto)

**Combat Phase**

  [heur] Professor Putricide vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Professor Putricide: [13/2, 13/2, 5/6, 3/5, 5/3, 4/4, 1/1]
     Overlord Saurfang: [17/18, 25/21, 21/20, 19/21, 19/21, 19/17, 8/8]
     Old Soul 17/18→17/13  |  Rylak Metalhead 5/3→5/0 DEAD
     Eternal Knight 13/2→14/0 DEAD  |  Old Soul 17/13→17/0 DEAD
     Trigore the Lasher 25/21→25/17  |  Holo Rover 4/4→4/4
     Eternal Knight 14/2→15/0 DEAD  |  Seafloor Recruiter 19/21→19/7
     Malchezaar, Prince of Dance 21/20→21/13  |  False Implicator 7/5→7/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Seafloor Recruiter 19/7→19/2
     Seafloor Recruiter 19/2→19/0 DEAD  |  Holo Rover 4/4→4/0 DEAD
     Hunting Tiger Shark 3/5→3/0 DEAD  |  Trigore the Lasher 25/17→25/14
     Result: 0 vs 5 — heur
  [heur] Inge, the Iron Hymn vs [heur] Sneed (first: Sneed)
     Inge, the Iron Hymn: [3/7, 6/2, 5/2, 2/8, 6/8, 2/5]
     Sneed: [8/7, 6/7, 4/4, 1/6, 10/12, 6/4, 5/2]
     Shell Collector 8/7→8/1  |  Eternal Knight 6/2→7/0 DEAD
     Ancestral Automaton 3/7→3/6  |  Hardy Orca 1/6→1/3
     Zesty Shaker 6/7→6/1  |  Enchanted Sentinel 6/8→6/2
     Mummifier 5/2→5/1  |  Hardy Orca 1/3→1/0 DEAD
     Holo Rover 4/4→4/4  |  Wyvern Outrider 2/8→2/4
     Wyvern Outrider 2/4→2/0 DEAD  |  Old Soul 6/4→6/2
     Technical Element 10/12→10/9  |  Ancestral Automaton 3/6→3/0 DEAD
     Enchanted Sentinel 6/2→6/0 DEAD  |  Technical Element 10/9→10/3
     Old Soul 6/2→6/0 DEAD  |  Mummifier 5/1→5/0 DEAD
     Lava Lurker 2/5→2/1  |  Holo Rover 4/4→4/2
     Mummifier 5/2→5/0 DEAD  |  Lava Lurker 2/1→2/0 DEAD
     Result: 0 vs 4 — heur
  [heur] Ysera vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Ysera: [6/6, 6/6, 4/6, 5/6, 4/10, 3/6, 4/6]
     Sylvanas Windrunner: [4/3, 2/4, 5/6, 2/4, 6/7, 3/3, 1/1]
     Shell Collector 4/3→4/0 DEAD  |  Sklibb, Demon Hunter 6/6→6/2
     Scarlet Survivor 6/6→7/5  |  Annoy-o-Module 2/4→2/4
     Nerubian Deathswarmer 2/4→2/0 DEAD  |  Sklibb, Demon Hunter 6/2→6/0 DEAD
     Dustbone Devastator 4/6→5/4  |  Annoy-o-Module 2/4→2/0 DEAD
     Technical Element 5/6→5/2  |  Roaring Recruiter 4/10→4/5
     Woodland Defiler 5/6→5/1  |  Technical Element 5/2→5/0 DEAD
     Zesty Shaker 6/7→6/3  |  Roaring Recruiter 4/5→4/0 DEAD
     Banana Slamma 3/6→3/5  |  Abyssal Bruiser 1/1→1/1
     Accord-o-Tron 3/3→3/0 DEAD  |  Woodland Defiler 5/1→5/0 DEAD
     Dustbone Devastator 5/6→6/5  |  Abyssal Bruiser 1/1→1/0 DEAD
     Result: 4 vs 1 — heur

  Alive: 7/8
  HP: Overlord Saurfang (HP=30, Tier=5) | Drek'Thar (HP=30, Tier=5) | Inge, the Iron Hymn (HP=27, Tier=5) | Ysera (HP=25, Tier=5) | Sneed (HP=22, Tier=5) | Sylvanas Windrunner (HP=13, Tier=5) | Professor Putricide (HP=4, Tier=5)

### Turn 10

**Sneed** [Heuristic]  HP=22 Armor=0 Gold=10 Tier=5

  Board (7/7): 8/7, 6/7, 4/4 [DS], 1/6 [Taunt], 10/12 [G], 6/4 [G], 5/2
  Tavern (6 items): Charging Czarina 4/1 T5 $3 | Reef Riffer 3/2 T2 $3 | Risen Rider 2/1 T1 $3 | Lurking Leviathan 3/8 T5 $3 | Void Pup Trainer 7/7 T5 $3 | Queen's Command (spell) T5 $2
  Hand: 6 cards

  → Board (7/7): 8/7, 6/7, 10/12 [G], 6/4 [G], 7/7, 3/8, 2/1 [Taunt]
  → Gold 10→0 | Hand 6→5
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=16 Gold=10 Tier=5

  Board (7/7): 17/18, 25/23, 21/20, 19/21, 19/21, 19/17 [Reborn], 8/8 [G]
  Tavern (6 items): Accord-o-Tron 29/29 T3 $3 | Auto Assembler 28/28 T4 $3 | Tranquil Meditative 29/34 T5 $3 | Annoy-o-Tron 27/28 T1 $3 | Ashen Corruptor 32/32 T5 $3 | Bargain Bundle (spell) T5 $5
  Hand: 1 cards

  → Board (7/7): 25/23, 21/20, 32/32, 29/34, 29/29, 28/28, 27/28 [Taunt,DS]
  → Gold 10→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=25 Armor=0 Gold=10 Tier=5

  Board (7/7): 6/6 [G], 6/6 [Taunt], 6/6, 5/6, 4/10 [Taunt], 3/6, 6/6
  Tavern (7 items): Laboratory Assistant 3/4 T2 $3 | Sly Raptor 1/3 T3 $3 | Sewer Rat 3/2 T2 $3 | Scrap Scraper 6/5 T5 $3 | Ancestral Automaton 3/4 T2 $3 | Deepwater Clan (spell) T4 $2 | Twilight Broodmother 5/3 T4 $3
  Hand: 2 cards

  → Board (7/7): 6/6 [G], 6/6 [Taunt], 6/6, 4/10 [Taunt], 6/6, 6/5, 3/2
  → Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=27 Armor=0 Gold=10 Tier=5

  Board (6/7): 3/7, 7/2, 5/2, 2/8, 6/8, 2/5
  Tavern (6 items): Catacomb Crasher 4/10 T5 $3 | Banana Slamma 3/6 T4 $3 | Monstrous Macaw 5/4 T4 $3 | Bazaar Dealer 4/6 T5 $3 | Charging Czarina 4/1 T5 $3 | Friendly Bounty (spell) T3 $2
  Hand: 0 cards

  → Board (7/7): 3/7, 2/8, 6/8, 4/10, 4/6, 3/6, 5/4
  → Gold 10→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=4 Armor=0 Gold=10 Tier=5

  Board (7/7): 15/2, 15/2, 5/6, 3/5, 5/3 [Taunt], 4/4 [DS], 1/1
  Tavern (6 items): Scrap Scraper 6/5 T5 $3 | Shadowdancer 5/3 T5 $3 | Sly Raptor 1/3 T3 $3 | Enchanted Sentinel 3/5 T4 $3 | Hardy Orca 1/6 T3 $3 | Saloon's Finest (spell) T5 $2
  Hand: 4 cards

  → Board (7/7): 15/2, 15/2, 5/6, 6/5, 5/3 [Taunt], 3/5, 1/3
  → Gold 10→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=13 Armor=0 Gold=11 Tier=5

  Board (7/7): 4/3, 2/4, 5/6, 2/4 [Taunt,DS], 6/7, 3/3, 1/1 [DS]
  Tavern (6 items): Darkcrest Strategist 4/5 T5 $3 | Handless Forsaken 3/1 T3 $3 | Soul Rewinder 4/1 T2 $3 | Trigore the Lasher 9/3 T4 $3 | Monstrous Macaw 5/4 T4 $3 | Armor Stash (spell) T5 $3
  Hand: 0 cards

  → Board (7/7): 2/4, 5/6, 6/7, 9/3, 4/5, 5/4, 4/1
  → Gold 11→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=10 Tier=5

  Board (7/7): 6/6 [Taunt], 8/2, 1/6 [Taunt], 6/7, 5/6, 19/6, 13/4
  Tavern (6 items): Nightmare Par-tea Guest 13/3 T5 $3 | Banana Slamma 3/6 T4 $3 | Picky Eater 1/1 T1 $3 | Holo Rover 4/4 T4 $3 | Auto Assembler 2/2 T4 $3 | Portal in a Crystal (spell) T5 $2
  Hand: 0 cards

  → Board (7/7): 6/6 [Taunt], 8/2, 6/7, 19/6, 13/4, 13/3, 1/1
  → Gold 10→0 | Hand 0→1
  → Actions: (auto)

**Combat Phase**

  [heur] Drek'Thar vs [heur] Sneed (first: Sneed)
     Drek'Thar: [6/6, 8/2, 6/7, 19/6, 13/4, 13/3, 1/1]
     Sneed: [8/7, 6/7, 10/12, 6/4, 7/7, 3/8, 2/1]
     Shell Collector 8/7→8/1  |  Alert Alarmist 6/6→6/0 DEAD
     Eternal Knight 8/2→9/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Zesty Shaker 6/7→6/6  |  Picky Eater 1/1→1/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Void Pup Trainer 7/7→7/1
     Technical Element 10/12→10/0 DEAD  |  Old Soul 13/4→13/0 DEAD
     Mummifier 19/6→19/0 DEAD  |  Shell Collector 8/1→8/0 DEAD
     Old Soul 6/4→6/0 DEAD  |  Nightmare Par-tea Guest 13/3→13/0 DEAD
     Result: 0 vs 3 — heur
  [heur] Overlord Saurfang vs [heur] Inge, the Iron Hymn (first: Overlord Saurfang)
     Overlord Saurfang: [25/23, 21/20, 32/32, 29/34, 29/29, 28/28, 27/28]
     Inge, the Iron Hymn: [3/10, 2/8, 9/11, 4/10, 4/6, 3/6, 5/4]
     Trigore the Lasher 25/23→25/20  |  Banana Slamma 3/6→3/0 DEAD
     Ancestral Automaton 3/10→3/0 DEAD  |  Annoy-o-Tron 27/28→27/28
     Malchezaar, Prince of Dance 21/20→21/16  |  Bazaar Dealer 4/6→4/0 DEAD
     Wyvern Outrider 2/8→2/0 DEAD  |  Annoy-o-Tron 27/28→27/26
     Ashen Corruptor 32/32→32/23  |  Enchanted Sentinel 9/11→9/0 DEAD
     Catacomb Crasher 4/10→4/0 DEAD  |  Annoy-o-Tron 27/26→27/22
     Tranquil Meditative 29/34→29/29  |  Monstrous Macaw 5/4→5/0 DEAD
     Result: 7 vs 0 — heur
  [heur] Professor Putricide vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Professor Putricide: [15/2, 15/2, 5/6, 6/5, 5/3, 3/5, 1/3]
     Sylvanas Windrunner: [2/4, 5/6, 6/7, 9/3, 4/5, 5/4, 4/1]
     Nerubian Deathswarmer 2/4→2/0 DEAD  |  Shadowdancer 5/3→5/1
     Eternal Knight 15/2→16/0 DEAD  |  Soul Rewinder 4/1→4/0 DEAD
     Technical Element 5/6→5/1  |  Shadowdancer 5/1→5/0 DEAD
     Eternal Knight 16/2→17/0 DEAD  |  Trigore the Lasher 9/3→9/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Sly Raptor 7/7→7/1
     Technical Element 5/6→5/2  |  Darkcrest Strategist 4/5→4/0 DEAD
     Monstrous Macaw 5/4→5/0 DEAD  |  Sly Raptor 7/1→7/0 DEAD
     Scrap Scraper 6/5→6/0 DEAD  |  Technical Element 5/1→5/0 DEAD
     Result: 2 vs 0 — heur

  Alive: 7/8
  HP: Overlord Saurfang (HP=30, Tier=5) | Ysera (HP=25, Tier=5) | Drek'Thar (HP=25, Tier=5) | Sneed (HP=22, Tier=5) | Inge, the Iron Hymn (HP=12, Tier=5) | Professor Putricide (HP=4, Tier=5) | Sylvanas Windrunner (HP=1, Tier=5)

### Turn 11

**Sneed** [Heuristic]  HP=22 Armor=0 Gold=10 Tier=5

  Board (7/7): 8/7, 6/7, 10/12 [G], 6/4 [G], 7/7, 3/8, 2/1 [Taunt]
  Tavern (6 items): Laboratory Assistant 5/6 T2 $3 | Hunting Tiger Shark 3/5 T4 $3 | Ancestral Automaton 3/4 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Famished Felbat 6/3 T5 $3 | A New Sprout (spell) T1 $3
  Hand: 5 cards

  → Board (7/7): 8/7, 6/7, 10/12 [G], 6/4 [G], 7/7, 3/8, 5/6
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=16 Gold=11 Tier=5

  Board (7/7): 25/24, 21/20, 32/32, 29/34, 29/29, 28/28, 27/28 [Taunt,DS]
  Tavern (6 items): Marquee Ticker 37/41 T4 $3 | Wrath Weaver 35/38 T1 $3 | Lava Lurker 36/39 T2 $3 | Friendly Geist 40/37 T4 $3 | Nerubian Deathswarmer 35/38 T2 $3 | Upper Hand (spell) T5 $3
  Hand: 2 cards

  → Board (7/7): 25/24, 32/32, 29/34, 29/29, 28/28, 27/28 [Taunt,DS], 37/41
  → Tier 5→6 | Gold 11→0 | Hand 2→1
  → Actions: (auto)

**Ysera** [Heuristic]  HP=25 Armor=0 Gold=10 Tier=5

  Board (7/7): 6/6 [G], 6/6 [Taunt], 7/6, 4/10 [Taunt], 7/6, 6/5, 3/2
  Tavern (7 items): Plaguerunner 9/2 T4 $3 | Woodland Defiler 5/6 T4 $3 | Holo Rover 4/4 T4 $3 | Accord-o-Tron 3/3 T3 $3 | Zesty Shaker 6/7 T4 $3 | Wave of Gold (spell) T5 $2 | Persistent Poet 2/3 T4 $3
  Hand: 4 cards

  → Board (7/7): 6/6 [G], 6/6 [Taunt], 7/6, 4/10 [Taunt], 7/6, 6/5, 9/2
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=5

  Board (7/7): 3/10, 2/8, 9/11, 4/10, 4/6, 3/6, 5/4
  Tavern (6 items): Dustbone Devastator 2/6 T3 $3 | Cadaver Caretaker 3/3 T3 $3 | Technical Element 5/6 T3 $3 | Humming Bird 1/4 T2 $3 | Sewer Lord 4/6 T5 $3 | Contracted Corpse (spell) T5 $3
  Hand: 0 cards

  → Board (7/7): 3/10, 2/8, 9/11, 4/10, 4/6, 5/4, 5/6
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=4 Armor=0 Gold=10 Tier=5

  Board (7/7): 17/2, 17/2, 5/6, 6/5, 5/3 [Taunt], 3/5, 1/3
  Tavern (6 items): Zesty Shaker 6/7 T4 $3 | Catacomb Crasher 4/10 T5 $3 | Void Pup Trainer 7/7 T5 $3 | Sly Raptor 1/3 T3 $3 | Waverider 2/8 T4 $3 | Misplaced Tea Set (spell) T4 $2
  Hand: 6 cards

  → Board (7/7): 17/2, 17/2, 5/6, 6/5, 5/3 [Taunt], 3/5, 4/10
  → Tier 5→6 | Gold 10→2 | Hand 6→5
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=1 Armor=0 Gold=10 Tier=5

  Board (7/7): 2/4, 5/6, 6/7, 9/5, 4/5, 5/4, 4/1
  Tavern (6 items): Imposing Percussionist 4/4 T4 $3 | Tichondrius 3/6 T5 $3 | Imposing Percussionist 4/4 T4 $3 | Cord Puller 1/1 T1 $3 | Charging Czarina 4/1 T5 $3 | Back to Back (spell) T4 $1
  Hand: 1 cards

  → Board (7/7): 2/4, 5/6, 6/7, 9/5, 4/5, 5/4, 3/6
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=25 Armor=0 Gold=10 Tier=5

  Board (7/7): 6/6 [Taunt], 9/2, 6/7, 19/6, 13/4, 13/3, 1/1
  Tavern (6 items): Eternal Tycoon 14/8 T5 $3 | Sprightly Scarab 3/1 T3 $3 | Humming Bird 1/4 T2 $3 | Scrap Scraper 6/5 T5 $3 | Plaguerunner 14/2 T4 $3 | Brood of Nozdormu (spell) T5 $2
  Hand: 2 cards

  → Board (7/7): 6/6 [Taunt], 9/2, 6/7, 19/6, 13/4, 13/3, 14/8
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Inge, the Iron Hymn vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Inge, the Iron Hymn: [3/13, 2/8, 9/11, 4/10, 4/6, 5/4, 8/9]
     Sylvanas Windrunner: [2/4, 5/6, 6/7, 9/5, 4/5, 5/4, 3/6]
     Nerubian Deathswarmer 2/4→2/1  |  Ancestral Automaton 3/13→3/11
     Ancestral Automaton 3/11→3/7  |  Darkcrest Strategist 4/5→4/2
     Technical Element 5/6→5/0 DEAD  |  Technical Element 8/9→8/4
     Wyvern Outrider 2/8→2/5  |  Tichondrius 3/6→3/4
     Zesty Shaker 6/7→6/0 DEAD  |  Technical Element 8/4→8/0 DEAD
     Enchanted Sentinel 9/11→9/9  |  Nerubian Deathswarmer 2/1→2/0 DEAD
     Trigore the Lasher 9/5→9/1  |  Bazaar Dealer 4/6→4/0 DEAD
     Catacomb Crasher 4/10→4/7  |  Tichondrius 3/4→3/0 DEAD
     Darkcrest Strategist 4/2→4/0 DEAD  |  Enchanted Sentinel 9/9→9/5
     Monstrous Macaw 5/4→5/0 DEAD  |  Trigore the Lasher 9/1→9/0 DEAD
     Monstrous Macaw 5/4→5/0 DEAD  |  Enchanted Sentinel 9/5→9/0 DEAD
     Result: 3 vs 0 — heur
  [heur] Overlord Saurfang vs [heur] Sneed (first: Overlord Saurfang)
     Overlord Saurfang: [25/24, 32/32, 29/34, 29/29, 28/28, 27/28, 37/41]
     Sneed: [8/7, 6/7, 10/12, 6/4, 7/7, 3/8, 5/6]
     Trigore the Lasher 25/24→25/21  |  Lurking Leviathan 3/8→3/0 DEAD
     Shell Collector 8/7→8/0 DEAD  |  Annoy-o-Tron 27/28→27/28
     Ashen Corruptor 32/32→32/26  |  Old Soul 6/4→6/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Annoy-o-Tron 27/28→27/22
     Tranquil Meditative 29/34→29/24  |  Technical Element 10/12→10/0 DEAD
     Void Pup Trainer 7/7→7/0 DEAD  |  Annoy-o-Tron 27/22→27/15
     Accord-o-Tron 29/29→29/24  |  Laboratory Assistant 5/6→5/0 DEAD
     Result: 7 vs 0 — heur
  [heur] Drek'Thar vs [heur] Professor Putricide (first: Professor Putricide)
     Drek'Thar: [6/6, 9/2, 6/7, 19/6, 13/4, 13/3, 14/8]
     Professor Putricide: [17/2, 17/2, 5/6, 6/5, 5/3, 3/5, 4/10]
     Eternal Knight 17/2→18/0 DEAD  |  Alert Alarmist 6/6→6/0 DEAD
     Eternal Knight 9/2→10/0 DEAD  |  Shadowdancer 5/3→5/0 DEAD
     Eternal Knight 18/2→19/0 DEAD  |  Mummifier 19/6→19/0 DEAD
     Zesty Shaker 6/7→6/1  |  Scrap Scraper 6/5→6/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Old Soul 13/4→13/0 DEAD
     Nightmare Par-tea Guest 13/3→13/0 DEAD  |  Catacomb Crasher 16/18→16/0 DEAD
     Result: 2 vs 0 — heur

  **Professor Putricide [Heuristic] eliminated!** (Turn 11)
  **Sylvanas Windrunner [Heuristic] eliminated!** (Turn 11)
  Alive: 5/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Ysera (HP=25, Tier=6) | Drek'Thar (HP=25, Tier=6) | Inge, the Iron Hymn (HP=12, Tier=6) | Sneed (HP=7, Tier=6)

### Turn 12

**Sneed** [Heuristic]  HP=7 Armor=0 Gold=10 Tier=6

  Board (7/7): 8/7, 6/7, 10/12 [G], 6/4 [G], 7/7, 3/8, 5/6
  Tavern (7 items): Spiked Savior 8/2 T5 $3 | Auto Assembler 2/2 T4 $3 | Hunting Tiger Shark 3/5 T4 $3 | Eternal Knight 4/2 T2 $3 | Iridescent Skyblazer 3/8 T5 $3 | Humming Bird 3/6 T2 $3 | Meditation (spell) T1 $3
  Hand: 6 cards

  → Board (7/7): 8/7, 6/7, 10/12 [G], 7/7, 5/6, 4/8, 4/2
  → Gold 10→0 | Hand 6→7
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=16 Gold=11 Tier=6

  Board (7/7): 25/25, 32/32, 29/34, 29/29, 28/28, 27/28 [Taunt,DS], 37/41
  Tavern (7 items): Ruthless Queensguard 39/39 T6 $3 | Ruthless Queensguard 39/39 T6 $3 | Monstrous Macaw 41/40 T4 $3 | Maelstrom Emergent 38/43 T5 $3 | Enchanted Sentinel 39/41 T4 $3 | Ancestral Automaton 3/4 T2 $3 | Upper Hand (spell) T5 $3
  Hand: 3 cards

  → Board (7/7): 32/32, 37/41, 49/48, 38/43, 47/49, 39/39, 39/39
  → Gold 11→0 | Hand 3→2
  → Actions: (auto)

**Ysera** [Heuristic]  HP=25 Armor=0 Gold=10 Tier=6

  Board (7/7): 6/6 [G], 6/6 [Taunt], 8/6, 4/10 [Taunt], 8/6, 6/5, 10/2
  Tavern (8 items): Ominous Seer 2/1 T1 $3 | Banana Slamma 3/6 T4 $3 | Eternal Tycoon 10/8 T5 $3 | Deep-Sea Angler 2/3 T3 $3 | Bazaar Dealer 4/6 T5 $3 | Wyvern Outrider 2/8 T4 $3 | Lost Staff of Hamuul (spell) T6 $2 | Fire-forged Evoker 8/5 T6 $3
  Hand: 6 cards

  → Board (7/7): 8/6, 4/10 [Taunt], 8/6, 10/2, 10/8, 8/5, 3/6
  → Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=6

  Board (7/7): 3/13, 2/8, 9/11, 4/10, 4/6, 5/4, 8/9
  Tavern (7 items): Banana Slamma 3/6 T4 $3 | Tidemistress Athissa 6/7 T6 $3 | Prosthetic Hand 3/1 T4 $3 | Junk Jouster 8/7 T6 $3 | Abyssal Bruiser 1/1 T4 $3 | Laboratory Assistant 3/4 T2 $3 | Staff of Enrichment (spell) T3 $2
  Hand: 0 cards

  → Board (7/7): 3/13, 9/11, 4/10, 8/9, 8/7, 6/7, 3/1 [Reborn]
  → Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=25 Armor=0 Gold=10 Tier=6

  Board (7/7): 6/6 [Taunt], 12/2, 6/7, 19/6, 13/4, 13/3, 14/8
  Tavern (7 items): Catacomb Crasher 14/10 T5 $3 | Ominous Seer 2/1 T1 $3 | Batty Terrorguard 6/2 T6 $3 | Skeletal Strafer 16/6 T5 $3 | Hunting Tiger Shark 3/5 T4 $3 | Moonsteel Juggernaut 8/8 T6 $3 | Misplaced Tea Set (spell) T4 $2
  Hand: 3 cards

  → Board (7/7): 19/6, 13/4, 13/3, 19/13, 14/10, 16/6, 3/5
  → Gold 10→0 | Hand 3→2
  → Actions: (auto)

**Combat Phase**

  [heur] Drek'Thar vs [heur] Ysera (first: Ysera)
     Drek'Thar: [21/8, 15/6, 15/5, 21/15, 16/12, 18/8, 5/7]
     Ysera: [8/6, 8/18, 8/6, 10/2, 10/8, 12/13, 3/6]
     Dustbone Devastator 8/6→9/0 DEAD  |  Catacomb Crasher 16/12→16/4
     Mummifier 21/8→21/0 DEAD  |  Roaring Recruiter 8/18→8/0 DEAD
     Dustbone Devastator 9/6→10/0 DEAD  |  Old Soul 15/6→15/0 DEAD
     Nightmare Par-tea Guest 15/5→15/0 DEAD  |  Fire-forged Evoker 12/13→12/0 DEAD
     Plaguerunner 12/2→15/0 DEAD  |  Skeletal Strafer 18/8→18/0 DEAD
     Result: 2 vs 0 — heur
  [heur] Sneed vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Sneed: [8/7, 6/7, 10/12, 7/7, 5/6, 4/8, 4/2]
     Inge, the Iron Hymn: [3/18, 11/13, 6/12, 10/11, 10/9, 8/9, 8/6]
     Ancestral Automaton 3/18→3/10  |  Shell Collector 8/7→8/4
     Shell Collector 8/4→8/0 DEAD  |  Tidemistress Athissa 8/9→8/1
     Enchanted Sentinel 11/13→11/9  |  Iridescent Skyblazer 4/8→4/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Tidemistress Athissa 8/1→8/0 DEAD
     Catacomb Crasher 6/12→6/2  |  Technical Element 10/12→10/6
     Technical Element 10/6→10/0 DEAD  |  Technical Element 10/11→10/1
     Technical Element 10/1→10/0 DEAD  |  Laboratory Assistant 5/6→5/0 DEAD
     Void Pup Trainer 7/7→7/0 DEAD  |  Enchanted Sentinel 11/9→11/2
     Junk Jouster 10/9→10/5  |  Eternal Knight 4/2→5/0 DEAD
     Result: 0 vs 5 — heur

  **Sneed [Heuristic] eliminated!** (Turn 12)
  Alive: 4/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Drek'Thar (HP=25, Tier=6) | Inge, the Iron Hymn (HP=12, Tier=6) | Ysera (HP=10, Tier=6)

### Turn 13

**Overlord Saurfang** [Heuristic]  HP=30 Armor=16 Gold=10 Tier=6

  Board (7/7): 32/32, 37/41, 49/48, 38/43, 47/49, 39/39, 39/39
  Tavern (7 items): Malchezaar, Prince of Dance 47/46 T4 $3 | Deep-Sea Angler 44/45 T3 $3 | Skeletal Strafer 48/48 T5 $3 | Mummifier 47/44 T3 $3 | Reef Riffer 45/44 T2 $3 | Void Pup Trainer 49/49 T5 $3 | Misplaced Tea Set (spell) T4 $2
  Hand: 3 cards

  → Board (7/7): 49/48, 47/49, 49/49, 48/48, 47/46, 47/44, 44/45
  → Gold 10→0 | Hand 3→2
  → Actions: (auto)

**Ysera** [Heuristic]  HP=10 Armor=0 Gold=10 Tier=6

  Board (7/7): 13/6, 4/10 [Taunt], 13/6, 15/2, 15/8, 8/5, 3/6
  Tavern (8 items): Tidemistress Athissa 6/7 T6 $3 | Annoy-o-Module 2/4 T3 $3 | Zesty Shaker 6/7 T4 $3 | Plaguerunner 15/2 T4 $3 | Deep Blue Crooner 2/2 T3 $3 | Eternal Summoner 19/1 T6 $3 | Angler's Lure (spell) T1 $3 | Amber Guardian 3/2 T3 $3
  Hand: 6 cards

  → Board (7/7): 13/6, 13/6, 15/2, 15/8, 19/1 [Reborn], 15/2, 2/4 [Taunt,DS]
  → Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=6

  Board (7/7): 3/18, 11/13, 6/12, 10/11, 10/9, 8/9, 8/6 [Reborn]
  Tavern (7 items): Accord-o-Tron 3/3 T3 $3 | Handless Forsaken 2/1 T3 $3 | Maelstrom Emergent 2/7 T5 $3 | Rylak Metalhead 5/3 T4 $3 | Hardy Orca 1/6 T3 $3 | Old Soul 3/4 T2 $3 | Evolving Strategy (spell) T1 $3
  Hand: 0 cards

  → Board (7/7): 3/18, 11/13, 6/12, 10/11, 10/9, 8/9, 3/3
  → Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=25 Armor=0 Gold=10 Tier=6

  Board (7/7): 21/8, 15/6, 15/5, 21/15, 16/12, 18/8, 5/7
  Tavern (7 items): Manasaber 4/1 T1 $3 | Abyssal Bruiser 1/1 T4 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | One-Amalgam Tour Group 16/7 T6 $3 | Plaguerunner 14/2 T4 $3 | Manasaber 4/1 T1 $3 | Portal in a Crystal (spell) T5 $2
  Hand: 3 cards

  → Board (6/7): 23/10, 17/8, 21/15, 18/8, 32/19, 5/2
  → Gold 10→0 | Hand 3→2
  → Actions: (auto)

**Combat Phase**

  [heur] Ysera vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Ysera: [13/6, 13/6, 15/2, 15/8, 19/1, 15/2, 2/4]
     Inge, the Iron Hymn: [3/23, 13/15, 8/14, 12/13, 12/11, 10/11, 8/8]
     Ancestral Automaton 3/23→3/21  |  Annoy-o-Module 2/4→2/4
     Dustbone Devastator 13/6→14/0 DEAD  |  Accord-o-Tron 8/8→8/0 DEAD
     Enchanted Sentinel 13/15→13/13  |  Annoy-o-Module 2/4→2/0 DEAD
     Dustbone Devastator 14/6→15/0 DEAD  |  Junk Jouster 12/11→12/0 DEAD
     Catacomb Crasher 8/14→8/0 DEAD  |  Plaguerunner 17/2→21/0 DEAD
     Eternal Tycoon 21/8→21/0 DEAD  |  Tidemistress Athissa 10/6→10/0 DEAD
     Technical Element 12/13→12/0 DEAD  |  Eternal Summoner 25/1→25/0 DEAD
     Plaguerunner 21/2→26/0 DEAD  |  Ancestral Automaton 3/21→3/0 DEAD
     Result: 0 vs 1 — heur
  [heur] Drek'Thar vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Drek'Thar: [25/12, 19/10, 23/17, 20/10, 34/21, 7/4]
     Overlord Saurfang: [50/49, 48/50, 50/50, 49/49, 48/47, 48/45, 45/46]
     Monstrous Macaw 50/49→50/42  |  Manasaber 7/4→7/0 DEAD
     Mummifier 25/12→25/0 DEAD  |  Skeletal Strafer 49/49→49/24
     Enchanted Sentinel 48/50→48/16  |  One-Amalgam Tour Group 34/21→34/0 DEAD
     Old Soul 20/11→20/0 DEAD  |  Deep-Sea Angler 45/46→45/26
     Void Pup Trainer 50/50→50/30  |  Skeletal Strafer 20/10→20/0 DEAD
     Eternal Tycoon 23/17→23/0 DEAD  |  Mummifier 48/45→48/22
     Result: 0 vs 7 — heur

  **Ysera [Heuristic] eliminated!** (Turn 13)
  **Drek'Thar [Heuristic] eliminated!** (Turn 13)
  Alive: 2/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Inge, the Iron Hymn (HP=12, Tier=6)

### Turn 14

**Overlord Saurfang** [Heuristic]  HP=30 Armor=16 Gold=10 Tier=6

  Board (7/7): 50/49, 48/50, 50/50, 49/49, 48/47, 48/45, 45/46
  Tavern (7 items): Drustfallen Butcher 50/55 T5 $3 | Tichondrius 51/54 T5 $3 | Tide Raiser 52/51 T2 $3 | Laboratory Assistant 53/54 T2 $3 | Plaguerunner 52/50 T4 $3 | Groundbreaker 53/52 T6 $3 | Misplaced Tea Set (spell) T4 $2
  Hand: 3 cards

  → Board (7/7): 50/49, 50/50, 55/56 [Taunt], 50/55, 51/54, 54/53, 52/51 [Taunt]
  → Gold 10→0 | Hand 3→2
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=12 Armor=0 Gold=11 Tier=6

  Board (7/7): 3/23, 13/15, 8/14, 12/13, 12/11, 10/11, 8/8
  Tavern (7 items): Soul Rewinder 4/1 T2 $3 | Handless Forsaken 2/1 T3 $3 | Marquee Ticker 3/7 T4 $3 | P-0UL-TR-0N 10/10 T6 $3 | Junk Jouster 8/7 T6 $3 | Tidemistress Athissa 6/7 T6 $3 | Eyes of the Earth Mother (spell) T6 $4
  Hand: 0 cards

  → Board (7/7): 3/23, 13/15, 8/14, 12/13, 12/11, 10/11, 4/1
  → Gold 11→0
  → Actions: (auto)

**Combat Phase**

  [heur] Inge, the Iron Hymn vs [heur] Overlord Saurfang (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [3/30, 17/19, 12/18, 16/17, 19/18, 14/15, 8/5]
     Overlord Saurfang: [50/49, 50/50, 55/56, 50/55, 51/54, 54/53, 52/51]
     Ancestral Automaton 3/30→3/0 DEAD  |  Tide Raiser 52/51→52/48
     Monstrous Macaw 50/49→50/30  |  Junk Jouster 19/18→19/0 DEAD
     Enchanted Sentinel 17/19→17/0 DEAD  |  Tide Raiser 52/48→52/31
     Void Pup Trainer 50/50→50/36  |  Tidemistress Athissa 14/15→14/0 DEAD
     Catacomb Crasher 12/18→12/0 DEAD  |  Tide Raiser 52/31→52/19
     Laboratory Assistant 55/56→55/48  |  Soul Rewinder 8/5→8/0 DEAD
     Technical Element 16/17→16/0 DEAD  |  Tide Raiser 52/19→52/3
     Result: 0 vs 7 — heur

  **Overlord Saurfang [Heuristic] eliminated!** (Turn 14)
  **Inge, the Iron Hymn [Heuristic] eliminated!** (Turn 14)

---

## Final Standings

| # | Hero | Role | HP | Tier | Eliminated |
|---|---|---|---|---|---|
| 1 | Overlord Saurfang | Heuristic | 30 | 6 | 14 |
| 2 | Inge, the Iron Hymn | Heuristic | 0 | 6 | 14 |
| 3 | Ysera | Heuristic | 0 | 6 | 13 |
| 4 | Drek'Thar | Heuristic | 0 | 6 | 13 |
| 5 | Sneed | Heuristic | 0 | 6 | 12 |
| 6 | Professor Putricide | Heuristic | 0 | 6 | 11 |
| 7 | Sylvanas Windrunner | Heuristic | 0 | 6 | 11 |
| 8 | Yogg-Saron, Hope's End | AGENT | 0 | 2 | 8 |