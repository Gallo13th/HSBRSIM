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

  → Gold 3→1
  → Actions: buy_tavern_0, play_hand_0, sell_board_0

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

  → Gold 4→2
  → Actions: buy_tavern_1, play_hand_0, sell_board_0

**Sneed** [Heuristic]  HP=30 Armor=12 Gold=4 Tier=1

  Board (1/7): 2/1
  Tavern (4 items): Wrath Weaver 1/4 T1 $3 | Risen Rider 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Fortify (spell) T1 $1
  Hand: 0 cards

  → Board (2/7): 2/1, 1/4
  → Gold 4→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=18 Gold=4 Tier=1

  Board (1/7): 2/5
  Tavern (4 items): Harmless Bonehead 4/4 T1 $3 | Ominous Seer 5/4 T1 $3 | Wrath Weaver 4/7 T1 $3 | Enchanted Lasso (spell) T1 $2
  Hand: 0 cards

  → Board (2/7): 4/7, 4/7
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
     Yogg-Saron, Hope's End: []
     Professor Putricide: [4/1, 2/1]
     Result: 0 vs 2 — heur
  [heur] Ysera vs [heur] Sneed (first: Ysera)
     Ysera: [3/3, 3/3]
     Sneed: [2/1, 1/4]
     Scarlet Survivor 3/3→3/2  |  Wrath Weaver 1/4→1/1
     Ominous Seer 2/1→2/0 DEAD  |  Scarlet Survivor 3/3→3/1
     Scarlet Survivor 3/1→3/0 DEAD  |  Wrath Weaver 1/1→1/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Overlord Saurfang vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Overlord Saurfang: [4/7, 4/7]
     Sylvanas Windrunner: [2/1, 1/4]
     Risen Rider 2/1→2/0 DEAD  |  Wrath Weaver 4/7→4/5
     Wrath Weaver 4/5→4/4  |  Wrath Weaver 1/4→1/0 DEAD
     Result: 2 vs 0 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=1) | Sneed (HP=30, Tier=1) | Overlord Saurfang (HP=30, Tier=1) | Ysera (HP=30, Tier=1) | Inge, the Iron Hymn (HP=30, Tier=1) | Professor Putricide (HP=30, Tier=1) | Sylvanas Windrunner (HP=30, Tier=1) | Drek'Thar (HP=30, Tier=1)

### Turn 3

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=13 Gold=5 Tier=1

  Board: (empty)
  Tavern (3 items): Wrath Weaver 1/4 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Cord Puller 1/1 T1 $3
  Hand: 0 cards

  → Board (1/7): 1/1
  → Gold 5→0
  → Actions: buy_tavern_0, play_hand_0, sell_board_0, buy_tavern_0, play_hand_0

**Sneed** [Heuristic]  HP=30 Armor=10 Gold=5 Tier=1

  Board (2/7): 2/1, 1/4
  Tavern (3 items): Risen Rider 2/1 T1 $3 | Cord Puller 1/1 T1 $3 | Ominous Seer 2/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1, 1/4, 2/1 [Taunt,Reborn]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=5 Tier=1

  Board (2/7): 4/7, 4/7
  Tavern (3 items): Manasaber 9/6 T1 $3 | Annoy-o-Tron 6/7 T1 $3 | Picky Eater 6/6 T1 $3
  Hand: 0 cards

  → Board (3/7): 4/7, 4/7, 9/6
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=12 Gold=5 Tier=1

  Board (2/7): 3/3, 3/3
  Tavern (4 items): Cord Puller 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Surf n' Surf 1/1 T1 $3 | Scarlet Survivor 3/3 T1 $3
  Hand: 0 cards

  → Board (2/7): 6/6 [G], 2/4 [Taunt]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=5 Tier=1

  Board (2/7): 4/1, 1/2 [Taunt,DS]
  Tavern (3 items): Risen Rider 2/1 T1 $3 | Cord Puller 1/1 T1 $3 | Manasaber 4/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 4/1, 1/2 [Taunt,DS], 4/1
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=10 Gold=5 Tier=1

  Board (2/7): 4/1, 2/1
  Tavern (3 items): Cord Puller 1/1 T1 $3 | Risen Rider 2/1 T1 $3 | Risen Rider 2/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 4/1, 2/1, 2/1 [Taunt,Reborn]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=7 Gold=5 Tier=1

  Board (2/7): 2/1 [Taunt,Reborn], 1/4
  Tavern (3 items): Harmless Bonehead 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Risen Rider 2/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1 [Taunt,Reborn], 1/4, 1/2 [Taunt,DS]
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=10 Gold=5 Tier=1

  Board (2/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS]
  Tavern (3 items): Ominous Seer 2/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Cord Puller 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 1/4
  → Tier 1→2 | Gold 5→0
  → Actions: (auto)

**Combat Phase**

  [heur] Inge, the Iron Hymn vs [heur] Professor Putricide (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 4/1]
     Professor Putricide: [4/1, 2/1, 2/1]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Ominous Seer 2/1→2/0 DEAD
     Result: 1 vs 0 — heur
  [heur] Ysera vs [heur] Drek'Thar (first: Drek'Thar)
     Ysera: [6/6, 2/4]
     Drek'Thar: [2/1, 1/2, 1/4]
     Risen Rider 2/1→2/0 DEAD  |  Taunt Test Minion 2/4→2/2
     Scarlet Survivor 6/6→6/5  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Taunt Test Minion 2/2→2/1
     Taunt Test Minion 2/1→2/0 DEAD  |  Wrath Weaver 1/4→1/2
     Wrath Weaver 1/2→1/0 DEAD  |  Scarlet Survivor 6/5→6/4
     Result: 1 vs 0 — heur
  [AGENT] Yogg-Saron, Hope's End vs [heur] Sylvanas Windrunner (first: Sylvanas Windrunner)
     Yogg-Saron, Hope's End: [1/1]
     Sylvanas Windrunner: [2/1, 1/4, 1/2]
     Risen Rider 2/1→2/0 DEAD  |  Harmless Bonehead 1/1→1/0 DEAD
     Result: 0 vs 2 — heur
  [heur] Overlord Saurfang vs [heur] Sneed (first: Overlord Saurfang)
     Overlord Saurfang: [4/7, 4/7, 9/6]
     Sneed: [2/1, 1/4, 2/1]
     Wrath Weaver 4/7→4/5  |  Risen Rider 2/1→2/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Wrath Weaver 4/7→4/5
     Wrath Weaver 4/5→4/4  |  Wrath Weaver 1/4→1/0 DEAD
     Result: 3 vs 0 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=1) | Sneed (HP=30, Tier=2) | Overlord Saurfang (HP=30, Tier=2) | Ysera (HP=30, Tier=2) | Inge, the Iron Hymn (HP=30, Tier=2) | Professor Putricide (HP=30, Tier=2) | Sylvanas Windrunner (HP=30, Tier=2) | Drek'Thar (HP=30, Tier=2)

### Turn 4

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=9 Gold=6 Tier=1

  Board (1/7): 1/1
  Tavern (3 items): Picky Eater 1/1 T1 $3 | Picky Eater 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3
  Hand: 0 cards

  → Board (3/7): 2/2, 2/2, 1/1
  → Tier 1→2 | Gold 6→2
  → Actions: buy_tavern_0, play_hand_0, buy_tavern_0, play_hand_0, sell_board_0, buy_tavern_0, play_hand_0, upgrade

**Sneed** [Heuristic]  HP=30 Armor=5 Gold=6 Tier=2

  Board (3/7): 2/1, 1/4, 2/1 [Taunt,Reborn]
  Tavern (5 items): Ominous Seer 2/1 T1 $3 | Ancestral Automaton 3/4 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Search Through Time (spell) T2 $2
  Hand: 0 cards

  → Board (5/7): 2/1, 1/4, 3/1 [Taunt,Reborn], 3/4, 2/4
  → Gold 6→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=17 Gold=6 Tier=2

  Board (3/7): 4/7, 4/7, 9/6
  Tavern (5 items): Alert Alarmist 9/9 T2 $3 | Eternal Knight 4/2 T2 $3 | Shell Collector 11/10 T2 $3 | Laboratory Assistant 10/11 T2 $3 | Might of Stormwind (spell) T2 $2
  Hand: 0 cards

  → Board (5/7): 6/9, 6/9, 9/6, 11/10, 10/11
  → Gold 6→0 | Armor 17→15
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=12 Gold=6 Tier=2

  Board (2/7): 6/6 [G], 2/4 [Taunt]
  Tavern (6 items): Alert Alarmist 2/2 T2 $3 | Old Soul 3/4 T2 $3 | Eternal Knight 4/2 T2 $3 | Manasaber 4/1 T1 $3 | Chef's Choice (spell) T2 $2 | Blazing Skyfin 2/4 T2 $3
  Hand: 0 cards

  → Board (4/7): 6/6 [G], 2/4 [Taunt], 3/4, 4/2
  → Gold 6→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=6 Tier=2

  Board (3/7): 4/1, 1/2 [Taunt,DS], 4/1
  Tavern (5 items): Metallic Hunter 4/2 T2 $3 | Tide Raiser 2/1 T2 $3 | Tide Raiser 2/1 T2 $3 | Alert Alarmist 2/2 T2 $3 | Leaf Through the Pages (spell) T2 $1
  Hand: 0 cards

  → Board (5/7): 4/1, 1/2 [Taunt,DS], 4/1, 4/2, 2/2 [Taunt]
  → Gold 6→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=30 Armor=7 Gold=6 Tier=2

  Board (3/7): 4/1, 2/1, 2/1 [Taunt,Reborn]
  Tavern (5 items): Cord Puller 1/1 T1 $3 | Sewer Rat 3/2 T2 $3 | Ominous Seer 2/1 T1 $3 | Old Soul 3/4 T2 $3 | Strike Oil (spell) T2 $3
  Hand: 0 cards

  → Board (5/7): 4/1, 2/1, 2/1 [Taunt,Reborn], 3/4, 3/2
  → Gold 6→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=7 Gold=6 Tier=2

  Board (3/7): 2/1 [Taunt,Reborn], 1/4, 1/2 [Taunt,DS]
  Tavern (5 items): Sewer Rat 3/2 T2 $3 | Scarlet Skull 2/1 T2 $3 | Eternal Knight 4/2 T2 $3 | Eternal Knight 4/2 T2 $3 | Hasty Excavation (spell) T2 $3
  Hand: 0 cards

  → Board (5/7): 2/1 [Taunt,Reborn], 1/4, 1/2 [Taunt,DS], 4/2, 4/2
  → Gold 6→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=7 Gold=6 Tier=2

  Board (3/7): 2/1 [Taunt,Reborn], 1/2 [Taunt,DS], 1/4
  Tavern (4 items): Annoy-o-Tron 1/2 T1 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Wrath Weaver 1/4 T1 $3 | Shell Collector 4/3 T2 $3
  Hand: 0 cards

  → Board (5/7): 3/1 [Taunt,Reborn], 1/2 [Taunt,DS], 1/4, 4/3, 2/4
  → Gold 6→0
  → Actions: (auto)

**Combat Phase**

  [heur] Drek'Thar vs [heur] Sylvanas Windrunner (first: Drek'Thar)
     Drek'Thar: [3/1, 1/2, 1/4, 4/3, 2/4]
     Sylvanas Windrunner: [2/1, 1/4, 1/2, 4/2, 4/2]
     Risen Rider 3/1→3/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/1→1/0 DEAD
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/1→1/0 DEAD
     Eternal Knight 4/2→4/1  |  Wrath Weaver 1/3→1/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Eternal Knight 4/1→5/0 DEAD
     Eternal Knight 5/2→6/0 DEAD  |  Nerubian Deathswarmer 2/4→2/0 DEAD
     Result: 0 vs 1 — heur
  [heur] Overlord Saurfang vs [heur] Professor Putricide (first: Overlord Saurfang)
     Overlord Saurfang: [6/9, 6/9, 9/6, 11/10, 10/11]
     Professor Putricide: [4/1, 2/1, 2/1, 3/4, 3/2]
     Wrath Weaver 6/9→6/7  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 6/7→6/3
     Wrath Weaver 6/9→6/6  |  Old Soul 3/4→3/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Manasaber 9/6→9/4
     Manasaber 9/4→9/1  |  Sewer Rat 3/2→3/0 DEAD
     Result: 5 vs 0 — heur
  [AGENT] Yogg-Saron, Hope's End vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Yogg-Saron, Hope's End: [2/2, 2/2, 1/1]
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 4/2, 2/2]
     Manasaber 4/1→4/0 DEAD  |  Picky Eater 2/2→2/0 DEAD
     Picky Eater 2/2→2/0 DEAD  |  Alert Alarmist 2/2→2/0 DEAD
     Annoy-o-Tron 1/2→1/2  |  Surf n' Surf 1/1→1/0 DEAD
     Result: 0 vs 3 — heur
  [heur] Ysera vs [heur] Sneed (first: Sneed)
     Ysera: [6/6, 2/4, 3/4, 4/2]
     Sneed: [2/1, 1/4, 3/1, 3/4, 2/4]
     Ominous Seer 2/1→2/0 DEAD  |  Taunt Test Minion 2/4→2/2
     Scarlet Survivor 6/6→6/3  |  Risen Rider 3/1→3/0 DEAD
     Wrath Weaver 1/4→1/2  |  Taunt Test Minion 2/2→2/1
     Taunt Test Minion 2/1→2/0 DEAD  |  Wrath Weaver 1/2→1/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Scarlet Survivor 6/3→6/0 DEAD
     Old Soul 3/4→3/2  |  Nerubian Deathswarmer 2/4→2/1
     Nerubian Deathswarmer 2/1→2/0 DEAD  |  Eternal Knight 4/2→5/0 DEAD
     Result: 1 vs 0 — heur

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Tier=2) | Sneed (HP=30, Tier=2) | Overlord Saurfang (HP=30, Tier=2) | Ysera (HP=30, Tier=2) | Inge, the Iron Hymn (HP=30, Tier=2) | Sylvanas Windrunner (HP=30, Tier=2) | Drek'Thar (HP=30, Tier=2) | Professor Putricide (HP=28, Tier=2)

### Turn 5

**Yogg-Saron, Hope's End** [RL AGENT]  HP=30 Armor=3 Gold=7 Tier=2

  Board (3/7): 2/2, 2/2, 1/1
  Tavern (5 items): Surf n' Surf 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Reef Riffer 3/2 T2 $3 | Scarlet Skull 2/1 T2 $3 | Tavern Coin (spell) T1 $3
  Hand: 1 cards

  → Board (5/7): 2/2, 2/2, 1/1, 4/1, 3/2
  → Gold 7→1
  → Actions: buy_tavern_1, play_hand_1, buy_tavern_1, play_hand_1

**Sneed** [Heuristic]  HP=30 Armor=1 Gold=7 Tier=2

  Board (5/7): 2/1, 1/4, 3/1 [Taunt,Reborn], 3/4, 2/4
  Tavern (4 items): Surf n' Surf 1/1 T1 $3 | Soul Rewinder 4/1 T2 $3 | Cord Puller 1/1 T1 $3 | Laboratory Assistant 3/4 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=7 Tier=2

  Board (5/7): 6/9, 6/9, 9/6, 11/10, 10/11
  Tavern (4 items): Sewer Rat 14/13 T2 $3 | Harmless Bonehead 12/12 T1 $3 | Humming Bird 12/15 T2 $3 | Metallic Hunter 15/13 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=12 Gold=7 Tier=2

  Board (4/7): 6/6 [G], 2/4 [Taunt], 3/4, 5/2
  Tavern (5 items): Nerubian Deathswarmer 1/4 T2 $3 | Annoy-o-Tron 1/2 T1 $3 | Ancestral Automaton 3/4 T2 $3 | Humming Bird 1/4 T2 $3 | Tarecgosa 4/4 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=7 Tier=2

  Board (5/7): 4/1, 1/2 [Taunt,DS], 4/1, 4/2, 2/2 [Taunt]
  Tavern (4 items): Humming Bird 1/4 T2 $3 | Humming Bird 1/4 T2 $3 | Manasaber 4/1 T1 $3 | Metallic Hunter 4/2 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=28 Armor=0 Gold=7 Tier=2

  Board (5/7): 4/1, 2/1, 2/1 [Taunt,Reborn], 3/4, 3/2
  Tavern (4 items): Cord Puller 1/1 T1 $3 | Scarlet Skull 2/1 T2 $3 | Old Soul 3/4 T2 $3 | Humming Bird 1/4 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=7 Gold=7 Tier=2

  Board (5/7): 2/1 [Taunt,Reborn], 1/4, 1/2 [Taunt,DS], 6/2, 6/2
  Tavern (4 items): Humming Bird 1/4 T2 $3 | Reef Riffer 3/2 T2 $3 | Eternal Knight 6/2 T2 $3 | Lava Lurker 2/5 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=4 Gold=7 Tier=2

  Board (5/7): 3/1 [Taunt,Reborn], 1/2 [Taunt,DS], 1/4, 4/3, 2/4
  Tavern (4 items): Shell Collector 4/3 T2 $3 | Tide Raiser 2/1 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Eternal Knight 4/2 T2 $3
  Hand: 0 cards

  → Tier 2→3 | Gold 7→0
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Ysera (first: Overlord Saurfang)
     Overlord Saurfang: [6/9, 6/9, 9/6, 11/10, 10/11]
     Ysera: [6/6, 2/4, 3/4, 5/2]
     Wrath Weaver 6/9→6/7  |  Taunt Test Minion 2/4→2/0 DEAD
     Scarlet Survivor 6/6→6/0 DEAD  |  Wrath Weaver 6/9→6/3
     Wrath Weaver 6/3→6/0 DEAD  |  Old Soul 3/4→3/0 DEAD
     Eternal Knight 5/2→6/0 DEAD  |  Shell Collector 11/10→11/5
     Result: 4 vs 0 — heur
  [heur] Inge, the Iron Hymn vs [heur] Sneed (first: Sneed)
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 4/2, 2/2]
     Sneed: [2/1, 1/4, 3/1, 3/4, 2/4]
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 3/1→3/0 DEAD
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/1
     Annoy-o-Tron 1/1→1/0 DEAD  |  Nerubian Deathswarmer 2/4→2/3
     Ancestral Automaton 3/4→3/2  |  Alert Alarmist 2/2→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Nerubian Deathswarmer 2/3→2/0 DEAD
     Result: 1 vs 2 — heur
  [heur] Professor Putricide vs [heur] Sylvanas Windrunner (first: Professor Putricide)
     Professor Putricide: [4/1, 2/1, 2/1, 3/4, 3/2]
     Sylvanas Windrunner: [2/1, 1/4, 1/2, 6/2, 6/2]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Risen Rider 2/1→2/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 1/4→1/1  |  Old Soul 3/4→3/3
     Old Soul 3/3→3/2  |  Wrath Weaver 1/1→1/0 DEAD
     Eternal Knight 6/2→7/0 DEAD  |  Old Soul 3/2→3/0 DEAD
     Sewer Rat 3/2→3/0 DEAD  |  Eternal Knight 7/2→8/0 DEAD
     Result: 0 vs 0 — draw
  [heur] Drek'Thar vs [AGENT] Yogg-Saron, Hope's End (first: Drek'Thar)
     Drek'Thar: [3/1, 1/2, 1/4, 4/3, 2/4]
     Yogg-Saron, Hope's End: [2/2, 2/2, 1/1, 4/1, 3/2]
     Risen Rider 3/1→3/0 DEAD  |  Picky Eater 2/2→2/0 DEAD
     Picky Eater 2/2→2/1  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Reef Riffer 3/2→3/1
     Surf n' Surf 1/1→1/0 DEAD  |  Nerubian Deathswarmer 2/4→2/3
     Wrath Weaver 1/4→1/1  |  Reef Riffer 3/1→3/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 1/1→1/0 DEAD
     Shell Collector 4/3→4/1  |  Picky Eater 2/1→2/0 DEAD
     Result: 2 vs 0 — heur

  Alive: 8/8
  HP: Sneed (HP=30, Tier=3) | Overlord Saurfang (HP=30, Tier=3) | Ysera (HP=30, Tier=3) | Inge, the Iron Hymn (HP=30, Tier=3) | Sylvanas Windrunner (HP=30, Tier=3) | Drek'Thar (HP=30, Tier=3) | Professor Putricide (HP=28, Tier=3) | Yogg-Saron, Hope's End (HP=26, Tier=2)

### Turn 6

**Yogg-Saron, Hope's End** [RL AGENT]  HP=26 Armor=0 Gold=8 Tier=2

  Board (5/7): 2/2, 2/2, 1/1, 4/1, 3/2
  Tavern (4 items): Annoy-o-Tron 1/2 T1 $3 | Tide Raiser 2/1 T2 $3 | Reef Riffer 3/2 T2 $3 | Scarlet Skull 2/1 T2 $3
  Hand: 2 cards

  → Board (7/7): 2/2, 2/2, 1/1, 4/1, 3/2, 3/2, 1/2 [Taunt,DS]
  → Gold 8→1 | Trinket: Impulsive Portrait
  → Actions: buy_tavern_2, play_hand_2, buy_tavern_0, play_hand_2

**Sneed** [Heuristic]  HP=30 Armor=1 Gold=8 Tier=3

  Board (5/7): 2/1, 1/4, 3/1 [Taunt,Reborn], 3/4, 2/4
  Tavern (5 items): Alert Alarmist 2/2 T2 $3 | Leeching Felhound 3/3 T3 $3 | Dustbone Devastator 3/6 T3 $3 | Sprightly Scarab 3/1 T3 $3 | Fleeting Vigor (spell) T3 $1
  Hand: 0 cards

  → Board (7/7): 3/6, 3/4, 2/4, 3/6, 3/3, 6/3 [Reborn], 2/2 [Taunt]
  → Gold 8→0 | HP 30→27 | Armor 1→0 | Trinket: Deathly Phylactery
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=8 Tier=3

  Board (5/7): 6/9, 6/9, 9/6, 11/10, 10/11
  Tavern (5 items): Deep-Sea Angler 14/15 T3 $3 | Technical Element 17/18 T3 $3 | Soul Rewinder 16/13 T2 $3 | Metallic Hunter 16/14 T2 $3 | Time Management (spell) T3 $4
  Hand: 0 cards

  → Board (7/7): 6/9, 6/9, 9/6, 11/10, 10/11, 17/18, 16/14
  → Gold 8→0 | Trinket: Impulsive Portrait
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=3 Gold=8 Tier=3

  Board (4/7): 6/6 [G], 2/4 [Taunt], 3/4, 6/2
  Tavern (5 items): Sly Raptor 1/3 T3 $3 | Picky Eater 1/1 T1 $3 | Sprightly Scarab 3/1 T3 $3 | Mummifier 5/2 T3 $3 | Roaring Recruiter 2/8 T3 $3
  Hand: 0 cards

  → Board (6/7): 6/6 [G], 2/4 [Taunt], 3/4, 6/2, 2/8, 5/2
  → Gold 8→0 | Trinket: Putricide Sticker
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=12 Gold=8 Tier=3

  Board (5/7): 4/1, 1/2 [Taunt,DS], 4/1, 4/2, 2/2 [Taunt]
  Tavern (4 items): Deflect-o-Bot 3/2 T3 $3 | Soul Rewinder 4/1 T2 $3 | False Implicator 1/1 T3 $3 | Leeching Felhound 3/3 T3 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 4/1, 4/2, 3/3, 3/2 [DS], 4/1, 1/1
  → Gold 8→0 | Armor 12→9 | Trinket: Kaboom Bot Portrait
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=28 Armor=0 Gold=8 Tier=3

  Board (5/7): 4/1, 2/1, 2/1 [Taunt,Reborn], 3/4, 3/2
  Tavern (4 items): Sewer Rat 3/2 T2 $3 | Deflect-o-Bot 3/2 T3 $3 | Ancestral Automaton 3/4 T2 $3 | Annoy-o-Module 2/4 T3 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 2/1, 2/1 [Taunt,Reborn], 3/4, 3/2, 3/4, 2/4 [Taunt,DS]
  → Gold 8→0 | Trinket: Beetle Band
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=30 Armor=7 Gold=8 Tier=3

  Board (5/7): 2/1 [Taunt,Reborn], 1/4, 1/2 [Taunt,DS], 8/2, 8/2
  Tavern (4 items): Alert Alarmist 2/2 T2 $3 | Deflect-o-Bot 3/2 T3 $3 | Eternal Knight 8/2 T2 $3 | Laboratory Assistant 3/4 T2 $3
  Hand: 0 cards

  → Board (5/7): 2/1 [Taunt,Reborn], 3/6, 1/2 [Taunt,DS], 8/6 [G], 3/4
  → Gold 8→0 | Armor 7→6 | Trinket: Putricide Sticker | Hand 0→1
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=30 Armor=4 Gold=8 Tier=3

  Board (5/7): 3/1 [Taunt,Reborn], 1/2 [Taunt,DS], 1/4, 4/3, 2/4
  Tavern (4 items): Mummifier 6/2 T3 $3 | Alert Alarmist 2/2 T2 $3 | Leeching Felhound 3/3 T3 $3 | Ancestral Automaton 3/4 T2 $3
  Hand: 0 cards

  → Board (6/7): 3/1 [Taunt,Reborn], 1/2 [Taunt,DS], 1/4, 4/3, 2/4, 6/2
  → Gold 8→0 | Trinket: Bleeding Heart
  → Actions: (auto)

**Combat Phase**

  [heur] Ysera vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Ysera: [6/6, 2/4, 3/4, 6/2, 2/8, 5/2]
     Inge, the Iron Hymn: [4/1, 4/1, 4/2, 3/3, 3/2, 4/1, 1/1]
     Manasaber 4/1→4/0 DEAD  |  Taunt Test Minion 2/4→2/0 DEAD
     Scarlet Survivor 6/6→7/3  |  Manasaber 4/1→4/0 DEAD
     Metallic Hunter 4/2→4/0 DEAD  |  Old Soul 3/4→3/0 DEAD
     Eternal Knight 6/2→6/1  |  False Implicator 1/1→1/0 DEAD
     Leeching Felhound 3/3→3/0 DEAD  |  Scarlet Survivor 7/3→7/0 DEAD
     Roaring Recruiter 2/8→3/5  |  Soul Rewinder 4/1→4/0 DEAD
     Deflect-o-Bot 3/2→3/2  |  Roaring Recruiter 3/5→3/2
     Mummifier 5/2→5/0 DEAD  |  Deflect-o-Bot 3/2→3/0 DEAD
     Result: 2 vs 0 — heur
  [heur] Sylvanas Windrunner vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Sylvanas Windrunner: [2/1, 3/6, 1/2, 8/6, 3/4]
     Overlord Saurfang: [6/9, 6/9, 9/6, 11/10, 10/11, 17/18, 16/14]
     Wrath Weaver 6/9→6/8  |  Annoy-o-Tron 1/2→1/2
     Risen Rider 2/1→2/0 DEAD  |  Shell Collector 11/10→11/8
     Wrath Weaver 6/9→6/8  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 3/6→3/0 DEAD  |  Wrath Weaver 6/8→6/5
     Manasaber 9/6→9/0 DEAD  |  Eternal Knight 8/6→9/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Wrath Weaver 6/8→6/5
     Result: 0 vs 6 — heur
  [heur] Drek'Thar vs [heur] Sneed (first: Sneed)
     Drek'Thar: [3/1, 1/2, 1/4, 4/3, 2/4, 6/2]
     Sneed: [3/6, 3/4, 2/4, 3/6, 3/3, 6/3, 2/2]
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/2→1/2
     Risen Rider 3/1→3/0 DEAD  |  Alert Alarmist 2/2→2/0 DEAD
     Ancestral Automaton 3/4→3/3  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 1/4→1/0 DEAD  |  Sprightly Scarab 6/3→6/2
     Nerubian Deathswarmer 2/4→2/0 DEAD  |  Mummifier 6/2→6/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Wrath Weaver 3/5→3/1
     Dustbone Devastator 3/6→4/4  |  Nerubian Deathswarmer 2/4→2/1
     Nerubian Deathswarmer 2/1→2/0 DEAD  |  Wrath Weaver 3/1→3/0 DEAD
     Result: 0 vs 4 — heur
  [AGENT] Yogg-Saron, Hope's End vs [heur] Professor Putricide (first: Professor Putricide)
     Yogg-Saron, Hope's End: [2/2, 2/2, 1/1, 4/1, 3/2, 3/2, 1/2]
     Professor Putricide: [4/1, 2/1, 2/1, 3/4, 3/2, 3/4, 2/4]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Picky Eater 2/2→2/0 DEAD  |  Annoy-o-Module 2/4→2/4
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Picky Eater 2/2→2/0 DEAD  |  Annoy-o-Module 2/4→2/2
     Risen Rider 2/1→2/0 DEAD  |  Reef Riffer 3/2→3/0 DEAD
     Surf n' Surf 1/1→1/0 DEAD  |  Annoy-o-Module 2/2→2/1
     Old Soul 3/4→3/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Reef Riffer 3/2→3/0 DEAD  |  Annoy-o-Module 2/1→2/0 DEAD
     Result: 0 vs 2 — heur

  Alive: 8/8
  HP: Overlord Saurfang (HP=30, Tier=3) | Ysera (HP=30, Tier=3) | Inge, the Iron Hymn (HP=30, Tier=3) | Professor Putricide (HP=28, Tier=3) | Sneed (HP=27, Tier=3) | Sylvanas Windrunner (HP=26, Tier=3) | Drek'Thar (HP=24, Tier=3) | Yogg-Saron, Hope's End (HP=19, Tier=2)

### Turn 7

**Yogg-Saron, Hope's End** [RL AGENT]  HP=19 Armor=0 Gold=9 Tier=2

  Board (7/7): 2/2, 2/2, 1/1, 4/1, 3/2, 3/2, 1/2 [Taunt,DS]
  Tavern (4 items): Metallic Hunter 4/2 T2 $3 | Eternal Knight 4/2 T2 $3 | Lava Lurker 2/5 T2 $3 | Alert Alarmist 2/2 T2 $3
  Hand: 3 cards

  → Board (6/7): 2/2, 4/1, 3/2, 3/2, 2/5, 4/2
  → Tier 2→3 | Gold 9→2
  → Actions: upgrade, sell_board_2, buy_tavern_2, play_hand_3, sell_board_5, buy_tavern_0, play_hand_3, sell_board_0

**Sneed** [Heuristic]  HP=27 Armor=0 Gold=9 Tier=3

  Board (7/7): 3/6, 3/4, 3/4, 4/6, 3/3, 6/3 [Reborn], 2/2 [Taunt]
  Tavern (4 items): Laboratory Assistant 4/6 T2 $3 | Technical Element 5/6 T3 $3 | Mummifier 7/2 T3 $3 | Old Soul 8/7 T2 $3
  Hand: 0 cards

  → Board (7/7): 3/6, 3/4, 3/4, 4/6, 3/3, 6/3 [Reborn], 10/9
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=15 Gold=9 Tier=3

  Board (7/7): 6/9, 6/9, 9/6, 11/10, 10/11, 17/18, 16/14
  Tavern (4 items): Laboratory Assistant 19/20 T2 $3 | Deep Blue Crooner 18/18 T3 $3 | Sewer Rat 19/18 T2 $3 | Ancestral Automaton 3/4 T2 $3
  Hand: 0 cards

  → Board (7/7): 8/11, 9/6, 11/10, 10/11, 17/18, 16/14, 19/20
  → Tier 3→4 | Gold 9→0 | Armor 15→14
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=3 Gold=9 Tier=3

  Board (6/7): 6/6 [G], 2/4 [Taunt], 3/4, 6/2, 2/8, 5/2
  Tavern (5 items): Old Soul 3/4 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Deep-Sea Angler 2/3 T3 $3 | False Implicator 1/1 T3 $3 | Sleepy Supporter 4/3 T2 $3
  Hand: 0 cards

  → Board (7/7): 6/6 [G], 2/4 [Taunt], 3/4, 6/2, 2/8, 5/2, 3/4
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=30 Armor=1 Gold=9 Tier=3

  Board (7/7): 4/1, 4/1, 4/2, 3/3, 3/2 [DS], 4/1, 1/1
  Tavern (4 items): Sewer Rat 3/2 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Old Soul 3/4 T2 $3
  Hand: 1 cards

  → Board (7/7): 4/1, 4/1, 4/2, 3/3, 3/2 [DS], 4/1, 3/4
  → Tier 3→4 | Gold 9→0 | Hand 1→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=28 Armor=0 Gold=9 Tier=3

  Board (7/7): 4/1, 2/1, 2/1 [Taunt,Reborn], 3/4, 3/2, 3/4, 2/4 [Taunt,DS]
  Tavern (4 items): Sly Raptor 1/3 T3 $3 | Scarlet Skull 2/1 T2 $3 | Metallic Hunter 4/2 T2 $3 | Harmless Bonehead 1/1 T1 $3
  Hand: 0 cards

  → Board (7/7): 4/1, 2/1 [Taunt,Reborn], 3/4, 3/2, 3/4, 2/4 [Taunt,DS], 4/2
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=26 Armor=0 Gold=9 Tier=3

  Board (5/7): 2/1 [Taunt,Reborn], 3/6, 1/2 [Taunt,DS], 9/3 [G], 3/4
  Tavern (4 items): Deep Blue Crooner 2/2 T3 $3 | Deep Blue Crooner 2/2 T3 $3 | Handless Forsaken 2/1 T3 $3 | Annoy-o-Module 2/4 T3 $3
  Hand: 1 cards

  → Board (6/7): 2/1 [Taunt,Reborn], 3/6, 1/2 [Taunt,DS], 9/3 [G], 3/4, 2/4 [Taunt,DS]
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=24 Armor=0 Gold=9 Tier=3

  Board (6/7): 3/1 [Taunt,Reborn], 1/2 [Taunt,DS], 1/4, 4/3, 2/4, 6/2
  Tavern (4 items): Sprightly Scarab 3/1 T3 $3 | Harmless Bonehead 2/1 T1 $3 | Humming Bird 1/4 T2 $3 | Sprightly Scarab 3/1 T3 $3
  Hand: 0 cards

  → Board (7/7): 3/1 [Taunt,Reborn], 1/2 [Taunt,DS], 1/4, 4/3, 2/4, 6/2, 1/4
  → Tier 3→4 | Gold 9→0
  → Actions: (auto)

**Combat Phase**

  [heur] Drek'Thar vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Drek'Thar: [3/1, 1/2, 1/4, 4/3, 2/4, 6/2, 2/4]
     Inge, the Iron Hymn: [4/1, 4/1, 4/2, 3/3, 3/2, 4/1, 3/4]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Risen Rider 3/1→3/0 DEAD  |  Leeching Felhound 3/3→3/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 1/4→1/0 DEAD  |  Soul Rewinder 4/1→4/0 DEAD
     Metallic Hunter 4/2→4/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Nerubian Deathswarmer 2/4→2/1  |  Old Soul 3/4→3/2
     Deflect-o-Bot 3/2→3/2  |  Nerubian Deathswarmer 2/1→2/0 DEAD
     Mummifier 6/2→6/0 DEAD  |  Deflect-o-Bot 3/2→3/0 DEAD
     Old Soul 3/2→3/0 DEAD  |  Humming Bird 2/4→2/1
     Result: 1 vs 0 — heur
  [heur] Professor Putricide vs [heur] Sneed (first: Professor Putricide)
     Professor Putricide: [4/1, 2/1, 3/4, 3/2, 3/4, 2/4, 4/2]
     Sneed: [3/6, 3/4, 3/4, 4/6, 3/3, 6/3, 10/9]
     Manasaber 4/1→4/0 DEAD  |  Old Soul 10/9→10/5
     Wrath Weaver 3/6→3/4  |  Risen Rider 2/1→2/0 DEAD
     Old Soul 3/4→3/0 DEAD  |  Old Soul 10/5→10/2
     Ancestral Automaton 3/4→3/2  |  Annoy-o-Module 2/4→2/4
     Sewer Rat 3/2→3/0 DEAD  |  Ancestral Automaton 3/2→3/0 DEAD
     Nerubian Deathswarmer 3/4→3/2  |  Annoy-o-Module 2/4→2/1
     Ancestral Automaton 3/4→3/1  |  Wrath Weaver 3/4→3/1
     Dustbone Devastator 4/6→5/4  |  Annoy-o-Module 2/1→2/0 DEAD
     Metallic Hunter 4/2→4/0 DEAD  |  Nerubian Deathswarmer 4/2→4/0 DEAD
     Leeching Felhound 3/3→3/0 DEAD  |  Ancestral Automaton 3/1→3/0 DEAD
     Result: 0 vs 4 — heur
  [heur] Sylvanas Windrunner vs [heur] Ysera (first: Ysera)
     Sylvanas Windrunner: [2/1, 3/6, 1/2, 9/3, 3/4, 2/4]
     Ysera: [6/6, 2/4, 3/4, 6/2, 2/8, 5/2, 3/4]
     Scarlet Survivor 6/6→7/6  |  Annoy-o-Tron 1/2→1/2
     Risen Rider 2/1→2/0 DEAD  |  Taunt Test Minion 2/4→2/2
     Taunt Test Minion 2/2→2/1  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 3/6→3/4  |  Taunt Test Minion 2/1→2/0 DEAD
     Old Soul 3/4→3/2  |  Annoy-o-Module 2/4→2/4
     Eternal Knight 9/3→10/0 DEAD  |  Eternal Knight 6/2→7/0 DEAD
     Roaring Recruiter 2/8→3/7  |  Annoy-o-Module 2/4→2/2
     Laboratory Assistant 3/4→3/1  |  Old Soul 3/4→3/1
     Mummifier 5/2→5/0 DEAD  |  Annoy-o-Module 2/2→2/0 DEAD
     Result: 2 vs 4 — heur
  [heur] Overlord Saurfang vs [AGENT] Yogg-Saron, Hope's End (first: Overlord Saurfang)
     Overlord Saurfang: [8/11, 9/6, 11/10, 10/11, 17/18, 16/14, 19/20]
     Yogg-Saron, Hope's End: [2/2, 4/1, 3/2, 3/2, 2/5, 4/2]
     Wrath Weaver 8/11→8/8  |  Reef Riffer 3/2→3/0 DEAD
     Picky Eater 2/2→2/0 DEAD  |  Wrath Weaver 8/8→8/6
     Manasaber 9/6→9/2  |  Manasaber 4/1→4/0 DEAD
     Reef Riffer 3/2→3/0 DEAD  |  Shell Collector 11/10→11/7
     Shell Collector 11/7→11/3  |  Metallic Hunter 4/2→4/0 DEAD
     Lava Lurker 2/5→2/0 DEAD  |  Laboratory Assistant 10/11→10/9
     Result: 7 vs 0 — heur

  Alive: 8/8
  HP: Overlord Saurfang (HP=30, Tier=4) | Ysera (HP=30, Tier=4) | Sneed (HP=27, Tier=4) | Sylvanas Windrunner (HP=26, Tier=4) | Inge, the Iron Hymn (HP=25, Tier=4) | Drek'Thar (HP=24, Tier=4) | Professor Putricide (HP=18, Tier=4) | Yogg-Saron, Hope's End (HP=9, Tier=3)

### Turn 8

**Yogg-Saron, Hope's End** [RL AGENT]  HP=9 Armor=0 Gold=10 Tier=3

  Board (6/7): 2/2, 4/1, 3/2, 3/2, 2/5, 4/2
  Tavern (5 items): Sewer Rat 3/2 T2 $3 | Tide Raiser 2/1 T2 $3 | Lava Lurker 2/5 T2 $3 | Deep-Sea Angler 2/3 T3 $3 | Pointy Arrow (spell) T1 $1
  Hand: 3 cards

  → Board (7/7): 2/2, 4/1, 3/2, 3/2, 2/5, 4/2, 2/5
  → Tier 3→4 | Gold 10→0
  → Actions: buy_tavern_2, play_hand_3, upgrade

**Sneed** [Heuristic]  HP=27 Armor=0 Gold=10 Tier=4

  Board (7/7): 3/6, 3/4, 4/4, 5/6, 3/3, 6/3 [Reborn], 11/9
  Tavern (6 items): Shell Collector 4/3 T2 $3 | Trigore the Lasher 9/3 T4 $3 | Hunting Tiger Shark 3/5 T4 $3 | Auto Assembler 2/2 T4 $3 | Nerubian Deathswarmer 4/4 T2 $3 | Shifting Tide (spell) T4 $1
  Hand: 0 cards

  → Board (7/7): 5/4, 6/6, 12/9, 6/8, 8/10, 11/9, 4/3
  → Gold 10→0 | Hand 0→1
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=14 Gold=10 Tier=4

  Board (7/7): 8/11, 9/6, 11/10, 10/11, 17/18, 16/14, 19/20
  Tavern (6 items): Trigore the Lasher 28/22 T4 $3 | Cord Puller 20/20 T1 $3 | Hunting Tiger Shark 22/24 T4 $3 | Prosthetic Hand 22/20 T4 $3 | Old Soul 22/23 T2 $3 | Natural Blessing (spell) T4 $4
  Hand: 0 cards

  → Board (7/7): 17/18, 19/20, 28/22, 22/24, 22/23, 22/20 [Reborn], 20/20 [DS]
  → Gold 10→0 | Hand 0→1
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=3 Gold=10 Tier=4

  Board (7/7): 6/6 [G], 2/4 [Taunt], 3/4, 7/2, 2/8, 5/2, 3/4
  Tavern (7 items): Enchanted Sentinel 3/5 T4 $3 | Handless Forsaken 2/1 T3 $3 | Seafloor Recruiter 3/5 T4 $3 | Accord-o-Tron 3/3 T3 $3 | Deflect-o-Bot 3/2 T3 $3 | Back to Back (spell) T4 $1 | Incubation Researcher 2/8 T4 $3
  Hand: 1 cards

  → Board (7/7): 6/6 [G], 7/2, 2/8, 2/8, 3/5, 3/5, 3/2 [DS]
  → Gold 10→0
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=25 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/1, 4/1, 4/2, 3/3, 3/2 [DS], 4/1, 3/4
  Tavern (6 items): Hardy Orca 1/6 T3 $3 | Technical Element 5/6 T3 $3 | Hunting Tiger Shark 3/5 T4 $3 | Auto Assembler 2/2 T4 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Forest's Bounty (spell) T4 $3
  Hand: 1 cards

  → Board (7/7): 3/3, 3/4, 5/6, 5/4, 3/5, 1/6 [Taunt], 2/2
  → Gold 10→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=18 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/1, 2/1 [Taunt,Reborn], 3/4, 3/2, 3/4, 2/4 [Taunt,DS], 4/2
  Tavern (6 items): Leeching Felhound 3/3 T3 $3 | Seafloor Recruiter 3/5 T4 $3 | Ancestral Automaton 3/4 T2 $3 | Plaguerunner 4/2 T4 $3 | Abyssal Bruiser 1/1 T4 $3 | Deepwater Clan (spell) T4 $2
  Hand: 1 cards

  → Board (7/7): 3/4, 6/4, 3/5, 6/4, 3/3, 4/2, 5/6
  → Gold 10→0 | HP 18→15 | Hand 1→0
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=26 Armor=0 Gold=10 Tier=4

  Board (6/7): 2/1 [Taunt,Reborn], 3/6, 1/2 [Taunt,DS], 10/3 [G], 3/4, 2/4 [Taunt,DS]
  Tavern (6 items): False Implicator 1/1 T3 $3 | Enchanted Sentinel 3/5 T4 $3 | Dustbone Devastator 2/6 T3 $3 | Alert Alarmist 2/2 T2 $3 | Rimescale Priestess 3/3 T4 $3 | Defender's Rites (spell) T4 $2
  Hand: 1 cards

  → Board (7/7): 3/6, 10/3 [G], 3/4, 3/5, 2/6, 3/3, 2/2 [Taunt]
  → Gold 10→0
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=4

  Board (7/7): 3/1 [Taunt,Reborn], 1/2 [Taunt,DS], 1/4, 4/3, 2/4, 6/2, 1/4
  Tavern (6 items): Rylak Metalhead 5/3 T4 $3 | Holo Rover 4/4 T4 $3 | Sprightly Scarab 3/1 T3 $3 | Sly Raptor 1/3 T3 $3 | Ominous Seer 2/1 T1 $3 | Temperature Shift (spell) T4 $4
  Hand: 0 cards

  → Board (7/7): 4/3, 2/4, 6/2, 1/4, 6/4 [Taunt,Reborn], 4/4 [DS], 2/1
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Sylvanas Windrunner vs [heur] Professor Putricide (first: Professor Putricide)
     Sylvanas Windrunner: [3/6, 10/3, 3/4, 3/5, 2/6, 3/3, 2/2]
     Professor Putricide: [3/4, 6/4, 3/5, 6/4, 3/3, 4/2, 5/6]
     Old Soul 3/4→3/2  |  Alert Alarmist 2/2→2/0 DEAD
     Wrath Weaver 3/6→3/0 DEAD  |  Ancestral Automaton 6/4→6/1
     Ancestral Automaton 6/4→6/2  |  Dustbone Devastator 2/6→2/0 DEAD
     Eternal Knight 10/3→11/0 DEAD  |  Seafloor Recruiter 3/5→3/0 DEAD
     Ancestral Automaton 6/1→6/0 DEAD  |  Laboratory Assistant 3/4→3/0 DEAD
     Enchanted Sentinel 3/5→3/2  |  Old Soul 3/2→3/0 DEAD
     Leeching Felhound 3/3→3/0 DEAD  |  Rimescale Priestess 3/3→3/0 DEAD
     Result: 1 vs 3 — heur
  [heur] Drek'Thar vs [heur] Ysera (first: Ysera)
     Drek'Thar: [4/3, 2/4, 6/2, 2/4, 7/4, 4/4, 2/1]
     Ysera: [6/6, 7/2, 2/8, 2/8, 3/5, 3/5, 3/2]
     Scarlet Survivor 6/6→7/0 DEAD  |  Rylak Metalhead 7/4→7/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Eternal Knight 7/2→8/0 DEAD
     Roaring Recruiter 2/8→3/5  |  Holo Rover 4/4→4/4
     Nerubian Deathswarmer 2/4→2/1  |  Seafloor Recruiter 3/5→3/3
     Incubation Researcher 2/8→3/7  |  Nerubian Deathswarmer 2/1→2/0 DEAD
     Mummifier 6/2→6/0 DEAD  |  Deflect-o-Bot 3/2→3/0 DEAD
     Enchanted Sentinel 3/5→3/3  |  Humming Bird 2/4→2/1
     Humming Bird 2/1→2/0 DEAD  |  Incubation Researcher 3/7→3/5
     Seafloor Recruiter 3/3→3/1  |  Ominous Seer 2/1→2/0 DEAD
     Holo Rover 4/4→4/1  |  Roaring Recruiter 3/5→3/1
     Result: 1 vs 4 — heur
  [heur] Sneed vs [heur] Overlord Saurfang (first: Sneed)
     Sneed: [5/4, 6/6, 12/9, 6/8, 8/10, 11/9, 4/3]
     Overlord Saurfang: [17/18, 19/20, 28/22, 22/24, 22/23, 22/20, 20/20]
     Nerubian Deathswarmer 5/4→5/0 DEAD  |  Old Soul 22/23→22/18
     Technical Element 17/18→17/10  |  Nerubian Deathswarmer 8/10→8/0 DEAD
     Dustbone Devastator 6/6→7/0 DEAD  |  Old Soul 22/18→22/12
     Laboratory Assistant 19/20→19/14  |  Hunting Tiger Shark 6/8→6/0 DEAD
     Old Soul 13/9→13/0 DEAD  |  Cord Puller 20/20→20/20
     Trigore the Lasher 28/22→28/18  |  Shell Collector 4/3→4/0 DEAD
     Auto Assembler 11/9→11/0 DEAD  |  Hunting Tiger Shark 22/24→22/13
     Result: 0 vs 7 — heur
  [heur] Inge, the Iron Hymn vs [AGENT] Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Inge, the Iron Hymn: [3/3, 3/4, 5/6, 5/4, 3/5, 1/6, 3/4]
     Yogg-Saron, Hope's End: [2/2, 4/1, 3/2, 3/2, 2/5, 4/2, 2/5]
     Picky Eater 2/2→2/1  |  Hardy Orca 1/6→1/4
     Leeching Felhound 3/3→3/1  |  Lava Lurker 2/5→2/2
     Manasaber 4/1→4/0 DEAD  |  Hardy Orca 1/4→1/0 DEAD
     Old Soul 3/4→3/1  |  Reef Riffer 3/2→3/0 DEAD
     Reef Riffer 3/2→3/0 DEAD  |  Hunting Tiger Shark 3/5→3/2
     Technical Element 5/6→5/4  |  Picky Eater 2/1→2/0 DEAD
     Lava Lurker 2/5→2/2  |  Hunting Tiger Shark 3/2→3/0 DEAD
     Malchezaar, Prince of Dance 5/4→5/2  |  Lava Lurker 2/2→2/0 DEAD
     Metallic Hunter 4/2→4/0 DEAD  |  Leeching Felhound 3/1→3/0 DEAD
     Ancestral Automaton 3/4→3/2  |  Lava Lurker 2/2→2/0 DEAD
     Result: 4 vs 0 — heur

  **Yogg-Saron, Hope's End [AGENT] eliminated!** (Turn 8)
  Alive: 7/8
  HP: Overlord Saurfang (HP=30, Tier=4) | Ysera (HP=30, Tier=4) | Sylvanas Windrunner (HP=26, Tier=4) | Inge, the Iron Hymn (HP=25, Tier=4) | Drek'Thar (HP=24, Tier=4) | Professor Putricide (HP=15, Tier=4) | Sneed (HP=12, Tier=4)

### Turn 9

**Sneed** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=4

  Board (7/7): 6/4, 7/6, 13/9, 6/8, 9/10, 11/9, 4/3
  Tavern (6 items): Technical Element 5/6 T3 $3 | False Implicator 1/1 T3 $3 | Deflect-o-Bot 3/2 T3 $3 | Metallic Hunter 4/2 T2 $3 | Nerubian Deathswarmer 6/4 T2 $3 | Tavern Coin (spell) T1 $3
  Hand: 1 cards

  → Tier 4→5 | Gold 10→0 | Trinket: Unholy Sanctum
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=14 Gold=10 Tier=4

  Board (7/7): 17/18, 19/20, 28/24, 22/24, 22/23, 22/20 [Reborn], 20/20 [DS]
  Tavern (6 items): Scarlet Skull 30/29 T2 $3 | Stomping Stegodon 32/32 T4 $3 | False Implicator 29/29 T3 $3 | Malchezaar, Prince of Dance 33/32 T4 $3 | Friendly Geist 34/31 T4 $3 | Conflagration (spell) T4 $2
  Hand: 1 cards

  → Tier 4→5 | Gold 10→0 | Trinket: Fridge Magnet
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=3 Gold=10 Tier=4

  Board (7/7): 6/6 [G], 8/2, 2/8, 2/8, 3/5, 3/5, 3/2
  Tavern (7 items): Lava Lurker 2/5 T2 $3 | Hardy Orca 1/6 T3 $3 | Holo Rover 4/4 T4 $3 | False Implicator 1/1 T3 $3 | Holo Rover 4/4 T4 $3 | Arcane Absorption (spell) T4 $1 | Sleepy Supporter 4/3 T2 $3
  Hand: 3 cards

  → Board (7/7): 6/6 [G], 8/2, 2/8, 2/8, 3/5, 3/5, 4/4 [DS]
  → Tier 4→5 | Gold 10→0 | Trinket: Chromatic Tear | Hand 3→5
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=25 Armor=0 Gold=10 Tier=4

  Board (7/7): 3/3, 3/4, 5/6, 5/4, 3/5, 1/6 [Taunt], 3/4
  Tavern (6 items): Floating Watcher 4/4 T3 $5 | Annoy-o-Module 2/4 T3 $3 | Annoy-o-Module 2/4 T3 $3 | Technical Element 5/6 T3 $3 | Annoy-o-Tron 1/2 T1 $3 | Pointy Arrow (spell) T1 $1
  Hand: 1 cards

  → Tier 4→5 | Gold 10→0 | Trinket: Electrode Attractor
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=15 Armor=0 Gold=10 Tier=4

  Board (7/7): 3/4, 6/4, 3/5, 6/4, 3/3, 4/2, 5/6
  Tavern (6 items): Wyvern Outrider 2/8 T4 $3 | Technical Element 5/6 T3 $3 | Friendly Geist 6/3 T4 $3 | Handless Forsaken 2/1 T3 $3 | Imposing Percussionist 4/4 T4 $3 | Eonar's Favor (spell) T4 $2
  Hand: 0 cards

  → Board (6/7): 3/4, 6/4, 3/5, 6/4, 4/2, 5/6
  → Tier 4→5 | Gold 10→0 | Trinket: Mechagon Adapter
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=26 Armor=0 Gold=10 Tier=4

  Board (7/7): 3/6, 11/3 [G], 3/4, 3/5, 2/6, 3/3, 2/2 [Taunt]
  Tavern (5 items): Ominous Seer 2/1 T1 $3 | Sewer Rat 3/2 T2 $3 | Tide Raiser 2/1 T2 $3 | Holo Rover 4/4 T4 $3 | Seafloor Recruiter 3/5 T4 $3
  Hand: 2 cards

  → Board (7/7): 3/6, 11/3 [G], 3/4, 3/5, 12/6, 3/3, 4/4 [DS]
  → Tier 4→5 | Gold 10→0 | Trinket: Artisanal Urn
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=4

  Board (7/7): 4/3, 2/4, 6/2, 1/4, 6/4 [Taunt,Reborn], 4/4 [DS], 2/1
  Tavern (5 items): Enchanted Sentinel 3/5 T4 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Imposing Percussionist 4/4 T4 $3 | Cord Puller 1/1 T1 $3 | Flaming Enforcer 4/5 T4 $3
  Hand: 1 cards

  → Tier 4→5 | Gold 10→0 | Trinket: Wildfeather Duster
  → Actions: (auto)

**Combat Phase**

  [heur] Sneed vs [heur] Sylvanas Windrunner (first: Sneed)
     Sneed: [6/4, 7/6, 13/9, 6/8, 9/10, 11/9, 4/3]
     Sylvanas Windrunner: [3/6, 11/3, 3/4, 3/5, 12/6, 3/3, 4/4]
     Nerubian Deathswarmer 6/4→6/1  |  Enchanted Sentinel 3/5→3/0 DEAD
     Wrath Weaver 3/6→3/0 DEAD  |  Nerubian Deathswarmer 6/1→6/0 DEAD
     Dustbone Devastator 7/6→8/0 DEAD  |  Dustbone Devastator 12/6→12/0 DEAD
     Eternal Knight 11/3→12/0 DEAD  |  Nerubian Deathswarmer 10/10→10/0 DEAD
     Old Soul 14/9→14/6  |  Rimescale Priestess 3/3→3/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Old Soul 14/6→14/3
     Hunting Tiger Shark 6/8→6/4  |  Holo Rover 4/4→4/4
     Holo Rover 4/4→4/0 DEAD  |  Old Soul 14/3→14/0 DEAD
     Result: 3 vs 0 — heur
  [heur] Drek'Thar vs [heur] Professor Putricide (first: Drek'Thar)
     Drek'Thar: [4/3, 2/4, 6/2, 2/4, 7/4, 4/4, 2/1]
     Professor Putricide: [3/4, 6/4, 3/5, 6/4, 4/2, 5/6]
     Shell Collector 4/3→4/0 DEAD  |  Ancestral Automaton 6/4→6/0 DEAD
     Old Soul 3/4→3/0 DEAD  |  Rylak Metalhead 7/4→7/1
     Nerubian Deathswarmer 2/4→2/0 DEAD  |  Ancestral Automaton 6/4→6/2
     Ancestral Automaton 6/2→6/0 DEAD  |  Rylak Metalhead 7/1→7/0 DEAD
     Mummifier 6/2→6/0 DEAD  |  Technical Element 5/6→5/0 DEAD
     Seafloor Recruiter 3/5→3/1  |  Holo Rover 4/4→4/4
     Humming Bird 2/4→2/0 DEAD  |  Plaguerunner 9/7→9/5
     Plaguerunner 9/5→9/3  |  Ominous Seer 2/1→2/0 DEAD
     Holo Rover 4/4→4/1  |  Seafloor Recruiter 3/1→3/0 DEAD
     Result: 1 vs 1 — heur
  [heur] Inge, the Iron Hymn vs [heur] Ysera (first: Ysera)
     Inge, the Iron Hymn: [3/3, 3/4, 5/6, 5/4, 3/5, 1/6, 3/4]
     Ysera: [6/6, 8/2, 2/8, 2/8, 3/5, 3/5, 4/4]
     Scarlet Survivor 6/6→7/6  |  Hardy Orca 1/6→1/0 DEAD
     Leeching Felhound 3/3→3/1  |  Roaring Recruiter 2/8→2/5
     Eternal Knight 8/2→9/0 DEAD  |  Malchezaar, Prince of Dance 5/4→5/0 DEAD
     Old Soul 3/4→3/0 DEAD  |  Holo Rover 4/4→4/4
     Roaring Recruiter 2/5→3/3  |  Ancestral Automaton 3/4→3/2
     Technical Element 5/6→5/0 DEAD  |  Scarlet Survivor 7/6→7/1
     Incubation Researcher 2/8→3/6  |  Leeching Felhound 3/1→3/0 DEAD
     Hunting Tiger Shark 3/5→3/1  |  Holo Rover 4/4→4/1
     Enchanted Sentinel 3/5→3/2  |  Hunting Tiger Shark 3/1→3/0 DEAD
     Ancestral Automaton 3/2→3/0 DEAD  |  Holo Rover 4/1→4/0 DEAD
     Result: 0 vs 5 — heur

  Alive: 7/8
  HP: Overlord Saurfang (HP=30, Tier=5) | Ysera (HP=30, Tier=5) | Drek'Thar (HP=24, Tier=5) | Professor Putricide (HP=15, Tier=5) | Sneed (HP=12, Tier=5) | Sylvanas Windrunner (HP=11, Tier=5) | Inge, the Iron Hymn (HP=10, Tier=5)

### Turn 10

**Sneed** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=5

  Board (7/7): 7/4, 8/6, 14/9, 6/8, 10/10, 11/9, 4/3
  Tavern (6 items): Laboratory Assistant 3/4 T2 $3 | Famished Felbat 6/3 T5 $3 | Alert Alarmist 2/2 T2 $3 | Skeletal Strafer 12/6 T5 $3 | Handless Forsaken 8/1 T3 $3 | Saloon's Finest (spell) T5 $2
  Hand: 1 cards

  → Board (7/7): 14/9, 10/10, 11/9, 12/6, 12/11, 13/9 [Taunt], 3/4
  → Gold 10→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=14 Gold=10 Tier=5

  Board (7/7): 17/18, 19/20, 28/26, 22/24, 22/23, 22/20 [Reborn], 20/20 [DS]
  Tavern (6 items): Imposing Percussionist 32/32 T4 $3 | Bazaar Dealer 32/34 T5 $3 | Zesty Shaker 34/35 T4 $3 | Enchanted Sentinel 31/33 T4 $3 | Sinrunner Blanchy 36/36 T5 $3 | Contracted Corpse (spell) T5 $3
  Hand: 1 cards

  → Board (7/7): 28/26, 22/24, 36/36 [Reborn], 34/35, 32/34, 32/32, 31/33
  → Gold 10→0 | Armor 14→8 | Hand 1→2
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=3 Gold=10 Tier=5

  Board (7/7): 6/6 [G], 9/2, 2/8, 2/8, 3/5, 3/5, 4/4 [DS]
  Tavern (7 items): Deflect-o-Bot 3/2 T3 $3 | Famished Felbat 6/3 T5 $3 | Nightmare Par-tea Guest 3/3 T5 $3 | Deep-Sea Angler 2/3 T3 $3 | Hunting Tiger Shark 3/5 T4 $3 | Armor Stash (spell) T5 $3 | Draconic Warden 7/4 T5 $3
  Hand: 5 cards

  → Board (7/7): 6/6 [G], 9/2, 2/8, 2/8, 7/4, 6/3, 1/4
  → Gold 10→0 | Hand 5→9
  → Actions: (auto)

**Inge, the Iron Hymn** [Heuristic]  HP=10 Armor=0 Gold=10 Tier=5

  Board (7/7): 3/3, 3/4, 5/6, 5/4, 3/5, 1/6 [Taunt], 3/4
  Tavern (6 items): Bazaar Dealer 4/6 T5 $3 | Alert Alarmist 2/2 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Wyvern Outrider 2/8 T4 $3 | Golden Touch (spell) T5 $5
  Hand: 1 cards

  → Board (7/7): 5/6, 5/4, 3/5, 4/6, 2/8, 5/4, 2/2 [Taunt]
  → Gold 10→0
  → Actions: (auto)

**Professor Putricide** [Heuristic]  HP=15 Armor=0 Gold=10 Tier=5

  Board (6/7): 3/4, 6/4, 3/5, 6/4, 4/2, 5/6
  Tavern (6 items): Iridescent Skyblazer 3/8 T5 $3 | Zesty Shaker 6/7 T4 $3 | Picky Eater 1/1 T1 $3 | Imposing Percussionist 4/4 T4 $3 | Banana Slamma 3/6 T4 $3 | Wave of Gold (spell) T5 $2
  Hand: 0 cards

  → Board (7/7): 6/4, 6/4, 5/6, 6/7, 3/8, 3/6, 4/4
  → Gold 10→0 | HP 15→9 | Hand 0→1
  → Actions: (auto)

**Sylvanas Windrunner** [Heuristic]  HP=11 Armor=0 Gold=10 Tier=5

  Board (7/7): 3/6, 12/3 [G], 3/4, 3/5, 12/6, 3/3, 4/4 [DS]
  Tavern (6 items): Divine Sparkbot 4/2 T5 $3 | Charging Czarina 4/1 T5 $3 | Handless Forsaken 12/1 T3 $3 | Famished Felbat 6/3 T5 $3 | Nightmare Par-tea Guest 13/3 T5 $3 | Portal in a Crystal (spell) T5 $2
  Hand: 4 cards

  → Board (7/7): 5/8, 12/3 [G], 12/6, 13/3, 12/1, 6/3, 16/1 [DS]
  → Gold 10→0 | HP 11→10 | Hand 4→5
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=5

  Board (7/7): 4/3, 2/4, 6/2, 1/4, 6/4 [Taunt,Reborn], 4/4 [DS], 2/1
  Tavern (6 items): Rimescale Priestess 3/3 T4 $3 | Friendly Geist 7/3 T4 $3 | Tranquil Meditative 3/8 T5 $3 | Drustfallen Butcher 3/7 T5 $3 | Plaguerunner 5/2 T4 $3 | Brood of Nozdormu (spell) T5 $2
  Hand: 2 cards

  → Board (7/7): 6/2, 6/4 [Taunt,Reborn], 7/3, 3/8, 3/7, 5/2, 3/3
  → Gold 10→0
  → Actions: (auto)

**Combat Phase**

  [heur] Sylvanas Windrunner vs [heur] Overlord Saurfang (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [5/8, 12/3, 12/6, 13/3, 12/1, 6/3, 16/1]
     Overlord Saurfang: [28/26, 22/24, 36/36, 34/35, 32/34, 32/32, 31/33]
     Wrath Weaver 5/8→5/0 DEAD  |  Zesty Shaker 34/35→34/30
     Trigore the Lasher 28/26→28/13  |  Nightmare Par-tea Guest 13/3→13/0 DEAD
     Eternal Knight 12/3→13/0 DEAD  |  Bazaar Dealer 32/34→32/22
     Hunting Tiger Shark 22/24→22/18  |  Famished Felbat 6/3→6/0 DEAD
     Dustbone Devastator 12/6→13/0 DEAD  |  Imposing Percussionist 32/32→32/20
     Sinrunner Blanchy 36/36→36/20  |  Charging Czarina 16/1→16/1
     Handless Forsaken 13/1→13/0 DEAD  |  Imposing Percussionist 32/20→32/7
     Zesty Shaker 34/30→34/14  |  Charging Czarina 16/1→16/0 DEAD
     Result: 0 vs 7 — heur
  [heur] Professor Putricide vs [heur] Sneed (first: Sneed)
     Professor Putricide: [6/4, 6/4, 5/6, 6/7, 3/8, 3/6, 4/4]
     Sneed: [15/10, 11/11, 12/10, 13/7, 13/12, 14/10, 4/5]
     Old Soul 15/10→15/6  |  Imposing Percussionist 4/4→4/0 DEAD
     Ancestral Automaton 6/4→6/0 DEAD  |  Alert Alarmist 14/10→14/4
     Nerubian Deathswarmer 11/11→11/6  |  Technical Element 5/6→5/0 DEAD
     Ancestral Automaton 6/4→6/0 DEAD  |  Alert Alarmist 14/4→14/0 DEAD
     Auto Assembler 12/10→12/7  |  Iridescent Skyblazer 3/8→3/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Nerubian Deathswarmer 11/6→11/0 DEAD
     Skeletal Strafer 13/7→13/3  |  Banana Slamma 4/7→4/0 DEAD
     Result: 0 vs 5 — heur
  [heur] Drek'Thar vs [heur] Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Drek'Thar: [6/2, 6/4, 7/3, 3/8, 3/7, 5/2, 3/3]
     Inge, the Iron Hymn: [5/6, 5/4, 3/5, 4/6, 2/8, 5/4, 2/2]
     Technical Element 5/6→5/0 DEAD  |  Rylak Metalhead 6/4→6/0 DEAD
     Mummifier 6/2→6/0 DEAD  |  Alert Alarmist 2/2→2/0 DEAD
     Malchezaar, Prince of Dance 5/4→5/0 DEAD  |  Plaguerunner 5/2→8/0 DEAD
     Friendly Geist 10/3→10/1  |  Wyvern Outrider 2/8→2/0 DEAD
     Hunting Tiger Shark 3/5→3/0 DEAD  |  Friendly Geist 10/1→10/0 DEAD
     Tranquil Meditative 3/8→3/4  |  Bazaar Dealer 4/6→4/3
     Bazaar Dealer 4/3→4/0 DEAD  |  Rimescale Priestess 3/3→3/0 DEAD
     Drustfallen Butcher 6/7→6/2  |  Malchezaar, Prince of Dance 5/4→5/0 DEAD
     Result: 2 vs 0 — heur

  **Inge, the Iron Hymn [Heuristic] eliminated!** (Turn 10)
  **Professor Putricide [Heuristic] eliminated!** (Turn 10)
  **Sylvanas Windrunner [Heuristic] eliminated!** (Turn 10)
  Alive: 4/8
  HP: Overlord Saurfang (HP=30, Tier=5) | Ysera (HP=30, Tier=5) | Drek'Thar (HP=24, Tier=5) | Sneed (HP=12, Tier=5)

### Turn 11

**Sneed** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=5

  Board (7/7): 15/10, 11/11, 12/10, 13/7, 13/12, 14/10 [Taunt], 4/5
  Tavern (6 items): Monstrous Macaw 5/4 T4 $3 | Risen Rider 8/1 T1 $3 | Divine Sparkbot 4/2 T5 $3 | Flaming Enforcer 4/5 T4 $3 | Shell Collector 4/3 T2 $3 | Rime or Reason (spell) T1 $3
  Hand: 1 cards

  → Board (7/7): 15/10, 11/11, 12/10, 13/7, 13/12, 14/10 [Taunt], 8/1 [Taunt,Reborn]
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=8 Gold=10 Tier=5

  Board (7/7): 28/28, 22/24, 36/36 [Reborn], 34/35, 32/34, 32/32, 31/33
  Tavern (6 items): Marquee Ticker 39/43 T4 $3 | Abyssal Bruiser 1/1 T4 $3 | Accord-o-Tron 39/39 T3 $3 | Cadaver Caretaker 39/39 T3 $3 | Old Soul 39/40 T2 $3 | Queen's Command (spell) T5 $2
  Hand: 2 cards

  → Board (7/7): 28/28, 36/36 [Reborn], 34/35, 32/34, 32/32, 31/33, 39/43
  → Tier 5→6 | Gold 10→0
  → Actions: (auto)

**Ysera** [Heuristic]  HP=30 Armor=3 Gold=10 Tier=5

  Board (7/7): 6/6 [G], 10/2, 2/8, 2/8, 7/4, 9/6, 4/7
  Tavern (7 items): Darkcrest Strategist 4/5 T5 $3 | Iridescent Skyblazer 3/8 T5 $3 | Zesty Shaker 6/7 T4 $3 | Sly Raptor 1/3 T3 $3 | Leeching Felhound 3/3 T3 $3 | Misplaced Tea Set (spell) T4 $2 | Amber Guardian 3/2 T3 $3
  Hand: 10 cards

  → Board (7/7): 6/6 [G], 10/2, 2/8, 7/4, 9/6, 4/7, 6/6
  → Tier 5→6 | Gold 10→0 | Hand 10→9
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=5

  Board (7/7): 9/2, 6/4 [Taunt,Reborn], 10/3, 3/8, 6/7, 8/2, 3/3
  Tavern (6 items): Rimescale Priestess 3/3 T4 $3 | Ancestral Automaton 3/4 T2 $3 | Scrap Scraper 6/5 T5 $3 | Soul Rewinder 4/1 T2 $3 | False Implicator 1/1 T3 $3 | Friendly Bounty (spell) T3 $2
  Hand: 5 cards

  → Board (6/7): 6/4 [Taunt,Reborn], 19/3, 3/8, 15/7, 17/2 [Reborn], 6/5
  → Tier 5→6 | Gold 10→0 | Hand 5→3
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Ysera (first: Overlord Saurfang)
     Overlord Saurfang: [28/28, 36/36, 34/35, 32/34, 32/32, 31/33, 39/43]
     Ysera: [6/6, 10/2, 2/8, 7/4, 13/14, 5/11, 6/6]
     Trigore the Lasher 28/28→28/26  |  Incubation Researcher 2/8→2/0 DEAD
     Scarlet Survivor 6/6→7/0 DEAD  |  Bazaar Dealer 32/34→32/28
     Sinrunner Blanchy 36/36→36/26  |  Eternal Knight 10/2→11/0 DEAD
     Draconic Warden 7/4→8/0 DEAD  |  Trigore the Lasher 28/26→28/19
     Zesty Shaker 34/35→34/29  |  Blue Chromadrake 6/6→6/0 DEAD
     Famished Felbat 13/14→13/0 DEAD  |  Sinrunner Blanchy 36/26→36/13
     Bazaar Dealer 32/28→32/23  |  Wrath Weaver 5/11→5/0 DEAD
     Result: 7 vs 0 — heur
  [heur] Drek'Thar vs [heur] Sneed (first: Sneed)
     Drek'Thar: [6/4, 19/3, 3/8, 15/7, 17/2, 6/5]
     Sneed: [16/11, 12/12, 13/11, 14/8, 18/18, 15/11, 9/2]
     Old Soul 16/11→16/5  |  Rylak Metalhead 6/4→6/0 DEAD
     Friendly Geist 19/3→19/0 DEAD  |  Risen Rider 9/2→9/0 DEAD
     Nerubian Deathswarmer 12/12→12/6  |  Scrap Scraper 6/5→6/0 DEAD
     Tranquil Meditative 3/8→3/0 DEAD  |  Alert Alarmist 15/11→15/8
     Auto Assembler 13/11→13/0 DEAD  |  Plaguerunner 17/2→21/0 DEAD
     Drustfallen Butcher 19/7→19/0 DEAD  |  Alert Alarmist 15/8→15/0 DEAD
     Result: 0 vs 4 — heur

  **Ysera [Heuristic] eliminated!** (Turn 11)
  Alive: 3/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Sneed (HP=12, Tier=6) | Drek'Thar (HP=4, Tier=6)

### Turn 12

**Sneed** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=6

  Board (7/7): 16/11, 12/12, 13/11, 14/8, 18/18, 15/11 [Taunt], 9/2 [Taunt,Reborn]
  Tavern (7 items): Iridescent Skyblazer 3/8 T5 $3 | Nightmare Par-tea Guest 9/3 T5 $3 | Prosthetic Hand 3/1 T4 $3 | Rylak Metalhead 5/3 T4 $3 | Annoy-o-Tron 1/2 T1 $3 | Ring Bearer 5/10 T6 $3 | Butchering (spell) T5 $2
  Hand: 1 cards

  → Board (7/7): 16/11, 12/12, 14/8, 18/18, 22/14, 18/15 [Taunt], 5/10
  → Gold 10→0 | Hand 1→2
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=8 Gold=10 Tier=6

  Board (7/7): 28/30, 36/36 [Reborn], 34/35, 32/34, 32/32, 31/33, 39/43
  Tavern (7 items): Glowscale 41/43 T5 $3 | Glowscale 41/43 T5 $3 | Leeching Felhound 40/40 T3 $3 | Plaguerunner 41/39 T4 $3 | Tide Raiser 39/38 T2 $3 | Ring Bearer 42/47 T6 $3 | Azerite Empowerment (spell) T6 $4
  Hand: 3 cards

  → Board (7/7): 39/43, 42/47, 41/43 [Taunt], 41/43 [Taunt], 40/40, 41/39, 39/38 [Taunt]
  → Gold 10→0 | Armor 8→5
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=4 Armor=0 Gold=10 Tier=6

  Board (6/7): 6/4 [Taunt,Reborn], 23/3, 3/8, 19/7, 21/2 [Reborn], 6/5
  Tavern (7 items): Divine Sparkbot 4/2 T5 $3 | Deathly Striker 16/8 T6 $3 | Plaguerunner 12/2 T4 $3 | Nerubian Deathswarmer 9/4 T2 $3 | Prosthetic Hand 3/1 T4 $3 | Rylak Metalhead 5/3 T4 $3 | Rime or Reason (spell) T1 $3
  Hand: 7 cards

  → Board (5/7): 55/3, 51/7, 53/2 [Reborn], 41/4, 5/3 [Taunt]
  → Gold 10→0 | Hand 7→5
  → Actions: (auto)

**Combat Phase**

  [heur] Sneed vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Sneed: [17/12, 13/13, 15/9, 196/203, 23/15, 19/16, 6/11]
     Overlord Saurfang: [39/43, 42/47, 41/43, 41/43, 40/40, 41/39, 39/38]
     Marquee Ticker 39/43→39/24  |  Rylak Metalhead 19/16→19/0 DEAD
     Old Soul 17/12→17/0 DEAD  |  Tide Raiser 39/38→39/21
     Ring Bearer 42/47→42/32  |  Skeletal Strafer 15/9→15/0 DEAD
     Nerubian Deathswarmer 13/13→13/0 DEAD  |  Tide Raiser 39/21→39/8
     Glowscale 41/43→41/0 DEAD  |  Famished Felbat 196/203→196/162
     Famished Felbat 196/162→196/123  |  Tide Raiser 39/8→39/0 DEAD
     Glowscale 41/43→41/31  |  Ring Bearer 12/15→12/0 DEAD
     Nightmare Par-tea Guest 23/15→23/0 DEAD  |  Glowscale 41/31→41/8
     Leeching Felhound 40/40→40/0 DEAD  |  Famished Felbat 202/127→202/87
     Result: 1 vs 4 — heur

  Alive: 3/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Sneed (HP=12, Tier=6) | Drek'Thar (HP=4, Tier=6)

### Turn 13

**Sneed** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=6

  Board (7/7): 17/12, 13/13, 15/9, 196/203, 23/15, 19/16 [Taunt], 6/11
  Tavern (7 items): Tidemistress Athissa 10/11 T6 $3 | Handless Forsaken 12/5 T3 $3 | Scarlet Skull 12/5 T2 $3 | Ancestral Automaton 9/8 T2 $3 | Rylak Metalhead 9/7 T4 $3 | One-Amalgam Tour Group 16/11 T6 $3 | Lost Staff of Hamuul (spell) T6 $2
  Hand: 4 cards

  → Board (7/7): 33/28, 29/29, 208/215, 35/27, 12/44, 42/30, 35/26 [Taunt]
  → Gold 10→0 | Hand 4→3
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=5 Gold=10 Tier=6

  Board (7/7): 39/43, 42/47, 41/43 [Taunt], 41/43 [Taunt], 40/40, 41/39, 39/38 [Taunt]
  Tavern (7 items): Wintergrasp Ghoul 51/49 T5 $3 | Stomping Stegodon 50/50 T4 $3 | Abyssal Bruiser 1/1 T4 $3 | Eternal Tycoon 50/54 T5 $3 | Shadowdancer 51/49 T5 $3 | Holo Rover 50/50 T4 $3 | Butchering (spell) T5 $2
  Hand: 5 cards

  → Board (6/7): 42/47 [DS], 41/43 [Taunt], 101/49, 50/50, 51/49 [Taunt], 50/50 [DS]
  → Gold 10→0 | Hand 5→2
  → Actions: (auto)

**Drek'Thar** [Heuristic]  HP=4 Armor=0 Gold=10 Tier=6

  Board (5/7): 61/3, 57/7, 59/2 [Reborn], 47/4, 5/3 [Taunt]
  Tavern (7 items): Drustfallen Butcher 18/7 T5 $3 | Eternal Summoner 24/1 T6 $3 | Glowscale 4/6 T5 $3 | Laboratory Assistant 3/4 T2 $3 | Goldrinn, the Great Wolf 8/8 T6 $3 | Soul Rewinder 4/1 T2 $3 | Leaf Through the Pages (spell) T2 $1
  Hand: 6 cards

  → Board (5/7): 136/7, 138/2 [Reborn], 126/4, 103/1 [Reborn], 4/6 [Taunt]
  → Gold 10→0 | Hand 6→4
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Drek'Thar (first: Overlord Saurfang)
     Overlord Saurfang: [42/47, 41/43, 101/49, 50/50, 51/49, 50/50]
     Drek'Thar: [136/7, 138/2, 126/4, 103/1, 4/6]
     Ring Bearer 42/47→42/47  |  Glowscale 4/6→4/0 DEAD
     Drustfallen Butcher 136/7→136/0 DEAD  |  Shadowdancer 51/49→51/0 DEAD
     Glowscale 41/43→41/0 DEAD  |  Eternal Summoner 103/1→103/0 DEAD
     Plaguerunner 138/2→144/0 DEAD  |  Holo Rover 50/50→50/50
     Wintergrasp Ghoul 101/49→101/0 DEAD  |  Nerubian Deathswarmer 132/4→132/0 DEAD
     Result: 3 vs 0 — heur

  **Drek'Thar [Heuristic] eliminated!** (Turn 13)
  Alive: 2/8
  HP: Overlord Saurfang (HP=30, Tier=6) | Sneed (HP=12, Tier=6)

### Turn 14

**Sneed** [Heuristic]  HP=12 Armor=0 Gold=10 Tier=6

  Board (7/7): 33/28, 29/29, 305/311, 35/27, 12/44, 42/30, 35/26 [Taunt]
  Tavern (7 items): Shell Collector 11/10 T2 $3 | Seafloor Recruiter 10/12 T4 $3 | Maelstrom Emergent 9/14 T5 $3 | Wyvern Outrider 9/15 T4 $3 | Sewer Rat 10/9 T2 $3 | Banana Slamma 10/13 T4 $3 | Misplaced Tea Set (spell) T4 $2
  Hand: 3 cards

  → Board (7/7): 38/33, 34/34, 305/311, 45/33, 48/41, 49/46, 48/47
  → Gold 10→0 | Armor 0→5 | Hand 3→1
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=30 Armor=5 Gold=10 Tier=6

  Board (6/7): 42/47 [DS], 41/43 [Taunt], 101/49, 50/50, 51/49 [Taunt], 50/50 [DS]
  Tavern (7 items): Sprightly Scarab 55/53 T3 $3 | Glowscale 56/58 T5 $3 | Void Pup Trainer 59/59 T5 $3 | Moonsteel Juggernaut 60/60 T6 $3 | Groundbreaker 57/56 T6 $3 | Consummate Conqueror 61/59 T6 $3 | Perfect Vision (spell) T6 $2
  Hand: 5 cards

  → Board (7/7): 101/49 [DS], 51/49 [Taunt], 50/50 [DS], 60/60, 61/59, 59/59, 56/58 [Taunt]
  → Gold 10→2 | Hand 5→3
  → Actions: (auto)

**Combat Phase**

  [heur] Sneed vs [heur] Overlord Saurfang (first: Overlord Saurfang)
     Sneed: [38/33, 34/34, 314/325, 45/33, 48/41, 49/46, 48/47]
     Overlord Saurfang: [101/49, 51/49, 50/50, 60/60, 61/59, 59/59, 56/58]
     Wintergrasp Ghoul 101/49→101/49  |  Handless Forsaken 45/33→45/0 DEAD
     Old Soul 38/33→38/0 DEAD  |  Glowscale 56/58→56/20
     Shadowdancer 51/49→51/0 DEAD  |  Famished Felbat 314/325→314/274
     Nerubian Deathswarmer 34/34→34/0 DEAD  |  Glowscale 56/20→56/0 DEAD
     Holo Rover 50/50→50/50  |  Wyvern Outrider 49/46→49/0 DEAD
     Famished Felbat 314/274→314/173  |  Wintergrasp Ghoul 101/49→101/0 DEAD
     Moonsteel Juggernaut 60/60→60/0 DEAD  |  Famished Felbat 314/173→314/113
     Seafloor Recruiter 48/41→48/0 DEAD  |  Holo Rover 50/50→50/2
     Consummate Conqueror 61/59→61/0 DEAD  |  Famished Felbat 314/113→314/52
     Banana Slamma 61/58→61/8  |  Holo Rover 50/2→50/0 DEAD
     Void Pup Trainer 59/59→59/0 DEAD  |  Banana Slamma 61/8→61/0 DEAD
     Result: 1 vs 0 — heur

  Alive: 2/8
  HP: Overlord Saurfang (HP=24, Tier=6) | Sneed (HP=12, Tier=6)

### Turn 15

**Sneed** [Heuristic]  HP=12 Armor=5 Gold=10 Tier=6

  Board (7/7): 38/33, 34/34, 314/325, 45/33, 48/41, 49/46, 48/47
  Tavern (7 items): Ring Bearer 17/22 T6 $3 | Glowscale 16/18 T5 $3 | Catacomb Crasher 22/22 T5 $3 | One-Amalgam Tour Group 24/19 T6 $3 | Scrap Scraper 18/17 T5 $3 | Plaguerunner 22/14 T4 $3 | Staff of Enrichment (spell) T3 $2
  Hand: 1 cards

  → Board (7/7): 320/331, 52/40, 55/48, 56/53, 55/54, 63/55, 20/19
  → Gold 10→0
  → Actions: (auto)

**Overlord Saurfang** [Heuristic]  HP=24 Armor=0 Gold=10 Tier=6

  Board (7/7): 101/49 [DS], 51/49 [Taunt], 50/50 [DS], 60/60, 61/59, 59/59, 56/58 [Taunt]
  Tavern (7 items): Floating Watcher 67/67 T3 $5 | Ashen Corruptor 67/67 T5 $3 | Alert Alarmist 65/65 T2 $3 | Seafloor Recruiter 64/66 T4 $3 | Sinrunner Blanchy 69/69 T5 $3 | Metallic Hunter 67/65 T2 $3 | Arcane Absorption (spell) T4 $1
  Hand: 9 cards

  → Board (7/7): 101/49 [DS], 60/60, 61/59 [DS], 69/69 [Reborn], 67/67, 67/67, 67/65
  → Gold 10→2 | Hand 9→7
  → Actions: (auto)

**Combat Phase**

  [heur] Overlord Saurfang vs [heur] Sneed (first: Sneed)
     Overlord Saurfang: [101/49, 60/60, 61/59, 69/69, 67/67, 67/67, 67/65]
     Sneed: [442/457, 52/40, 55/48, 56/53, 55/54, 63/55, 20/19]
     Famished Felbat 442/457→442/396  |  Consummate Conqueror 61/59→61/59
     Wintergrasp Ghoul 101/49→101/49  |  Seafloor Recruiter 55/48→55/0 DEAD
     Handless Forsaken 52/40→52/0 DEAD  |  Wintergrasp Ghoul 101/49→101/0 DEAD
     Moonsteel Juggernaut 60/60→60/0 DEAD  |  Famished Felbat 442/396→442/336
     Wyvern Outrider 56/53→56/0 DEAD  |  Ashen Corruptor 67/67→67/11
     Consummate Conqueror 61/59→61/3  |  Banana Slamma 56/55→56/0 DEAD
     Plaguerunner 63/55→66/0 DEAD  |  Sinrunner Blanchy 69/69→69/6
     Sinrunner Blanchy 69/6→69/0 DEAD  |  Scrap Scraper 26/23→26/0 DEAD
     Result: 4 vs 1 — heur

  Alive: 2/8
  HP: Overlord Saurfang (HP=24, Tier=6) | Sneed (HP=12, Tier=6)

---

## Final Standings

| # | Hero | Role | HP | Tier | Eliminated |
|---|---|---|---|---|---|
| 1 | Overlord Saurfang | Heuristic | 24 | 6 | — |
| 2 | Sneed | Heuristic | 12 | 6 | — |
| 3 | Drek'Thar | Heuristic | 0 | 6 | 13 |
| 4 | Ysera | Heuristic | 0 | 6 | 11 |
| 5 | Inge, the Iron Hymn | Heuristic | 0 | 5 | 10 |
| 6 | Professor Putricide | Heuristic | 0 | 5 | 10 |
| 7 | Sylvanas Windrunner | Heuristic | 0 | 5 | 10 |
| 8 | Yogg-Saron, Hope's End | AGENT | 0 | 4 | 8 |