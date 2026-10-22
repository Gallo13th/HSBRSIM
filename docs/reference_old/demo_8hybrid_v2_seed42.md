# 8-Player Battlegrounds — All SearchAgent Self-Play Demo

**Seed**: 42  |  **Max Turns**: 15  |  **Agents**: 8× SearchAgent (greedy)

**Game Value**: `checkpoints/game_value_sp_iter1.pt`  |  **Board Eval**: `checkpoints/board_eval_v3_clean.pt`

> Each player uses the SearchAgent with GameValueNetwork to evaluate
> POMDP states and select the best action greedily. No beam search
> means one-step lookahead only. All 8 agents share the same model weights.


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

  → Board: 4/1
  → Actions (2): buy_tavern_0, play_hand_0

**Sneed**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Ominous Seer 2/1 T1 $3 | Picky Eater 1/1 T1 $3 | Picky Eater 1/1 T1 $3 | Rime or Reason (spell) T1 $3

  → Board: 2/1
  → Actions (2): buy_tavern_0, play_hand_0

**Overlord Saurfang**  HP=30 Armor=18 Gold=3 Tier=1

  Board: (empty)
  Tavern: Surf n' Surf 2/2 T1 $3 | Surf n' Surf 2/2 T1 $3 | Wrath Weaver 2/5 T1 $3 | Tavern Coin (spell) T1 $3

  → Board: 2/5
  → Actions (2): buy_tavern_2, play_hand_0

**Ysera**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Surf n' Surf 1/1 T1 $3 | A New Sprout (spell) T1 $3 | Scarlet Survivor 3/3 T1 $3

  → Board: 3/3
  → Actions (2): buy_tavern_4, play_hand_0

**Inge, the Iron Hymn**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Picky Eater 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Cloning Conch (spell) T1 $0

  → Board: 4/1
  → Actions (2): buy_tavern_1, play_hand_0

**Professor Putricide**  HP=30 Armor=10 Gold=3 Tier=1

  Board: (empty)
  Tavern: Cord Puller 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Them Apples (spell) T1 $1

  → Board: 4/1
  → Actions (2): buy_tavern_1, play_hand_0

**Sylvanas Windrunner**  HP=30 Armor=10 Gold=3 Tier=1

  Board: (empty)
  Tavern: Surf n' Surf 1/1 T1 $3 | Risen Rider 2/1 T1 $3 | Picky Eater 1/1 T1 $3 | Pointy Arrow (spell) T1 $1

  → Board: 2/1 [Taunt,Reborn]
  → Actions (2): buy_tavern_1, play_hand_0

**Drek'Thar**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Risen Rider 2/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Meditation (spell) T1 $3

  → Board: 2/1 [Taunt,Reborn]
  → Actions (2): buy_tavern_0, play_hand_0

**Combat Phase**

  Overlord Saurfang vs Drek'Thar (first: Drek'Thar)
     Overlord Saurfang: [2/5]
     Drek'Thar: [2/1]
     Risen Rider 2/1→2/0 DEAD  |  Wrath Weaver 2/5→2/3
     Result: survivors 1 vs 0 — winner: Overlord Saurfang
  Sneed vs Professor Putricide (first: Sneed)
     Sneed: [2/1]
     Professor Putricide: [4/1]
     Ominous Seer 2/1→2/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 0 vs 0 — winner: draw
  Ysera vs Yogg-Saron, Hope's End (first: Ysera)
     Ysera: [3/3]
     Yogg-Saron, Hope's End: [4/1]
     Scarlet Survivor 3/3→3/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 0 vs 0 — winner: draw
  Sylvanas Windrunner vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Sylvanas Windrunner: [2/1]
     Inge, the Iron Hymn: [4/1]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Result: survivors 0 vs 0 — winner: draw

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=18, Tier=1) | Sneed (HP=30, Armor=12, Tier=1) | Overlord Saurfang (HP=30, Armor=18, Tier=1) | Ysera (HP=30, Armor=12, Tier=1) | Inge, the Iron Hymn (HP=30, Armor=12, Tier=1) | Professor Putricide (HP=30, Armor=10, Tier=1) | Sylvanas Windrunner (HP=30, Armor=10, Tier=1) | Drek'Thar (HP=30, Armor=10, Tier=1)

### Turn 2

**Yogg-Saron, Hope's End**  HP=30 Armor=18 Gold=4 Tier=1

  Board: 4/1
  Tavern: Wrath Weaver 1/4 T1 $3 | Manasaber 4/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Angler's Lure (spell) T1 $3

  → Board: 4/1, 1/4
  → Actions (2): buy_tavern_0, play_hand_0

**Sneed**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 2/1
  Tavern: Harmless Bonehead 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | The Goldenizer (spell) T1 $0

  → Board: 2/1, 4/1
  → Gold: 1→0
  → Actions (3): buy_tavern_1, play_hand_0, refresh

**Overlord Saurfang**  HP=30 Armor=18 Gold=4 Tier=1

  Board: 2/5
  Tavern: Wrath Weaver 4/7 T1 $3 | Harmless Bonehead 4/4 T1 $3 | Risen Rider 5/4 T1 $3 | Recruit a Trainee (spell) T1 $2

  → Board: 4/7, 4/7
  → Armor: 18→17
  → Actions (2): buy_tavern_0, play_hand_0

**Ysera**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 3/3
  Tavern: Harmless Bonehead 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Ominous Seer 2/1 T1 $3 | Fortify (spell) T1 $1 | Scarlet Survivor 3/3 T1 $3

  → Board: 3/3, 3/3
  → Actions (2): buy_tavern_4, play_hand_0

**Inge, the Iron Hymn**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 4/1
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Ominous Seer 2/1 T1 $3 | Picky Eater 1/1 T1 $3 | Sick Riffs (spell) T1 $3

  → Board: 4/1, 1/2 [Taunt,DS]
  → Actions (2): buy_tavern_0, play_hand_0

**Professor Putricide**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 4/1
  Tavern: Cord Puller 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Manasaber 4/1 T1 $3 | Undersea Mount (spell) T1 $3

  → Board: 4/1, 4/1
  → Actions (2): buy_tavern_2, play_hand_0

**Sylvanas Windrunner**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 2/1 [Taunt,Reborn]
  Tavern: Cord Puller 1/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Banana (spell) T1 $0

  → Board: 2/1 [Taunt,Reborn], 1/1 [DS]
  → Gold: 1→0
  → Actions (3): buy_tavern_0, play_hand_0, refresh

**Drek'Thar**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 2/1 [Taunt,Reborn]
  Tavern: Wrath Weaver 1/4 T1 $3 | Ominous Seer 2/1 T1 $3 | Manasaber 4/1 T1 $3 | Enchanted Lasso (spell) T1 $2

  → Board: 2/1 [Taunt,Reborn], 1/4
  → Actions (2): buy_tavern_0, play_hand_0

**Combat Phase**

  Yogg-Saron, Hope's End vs Sylvanas Windrunner (first: Yogg-Saron, Hope's End)
     Yogg-Saron, Hope's End: [4/1, 1/4]
     Sylvanas Windrunner: [2/1, 1/1]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Cord Puller 1/1→1/1  |  Wrath Weaver 1/4→1/3
     Wrath Weaver 1/3→1/2  |  Cord Puller 1/1→1/0 DEAD
     Result: survivors 1 vs 0 — winner: Yogg-Saron, Hope's End
  Overlord Saurfang vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Overlord Saurfang: [4/7, 4/7]
     Inge, the Iron Hymn: [4/1, 1/2]
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 4/7→4/3
     Wrath Weaver 4/7→4/6  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Wrath Weaver 4/3→4/2
     Result: survivors 2 vs 0 — winner: Overlord Saurfang
  Ysera vs Drek'Thar (first: Ysera)
     Ysera: [3/3, 3/3]
     Drek'Thar: [2/1, 1/4]
     Scarlet Survivor 3/3→3/1  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 1/4→1/1  |  Scarlet Survivor 3/3→3/2
     Scarlet Survivor 3/2→3/1  |  Wrath Weaver 1/1→1/0 DEAD
     Result: survivors 2 vs 0 — winner: Ysera
  Sneed vs Professor Putricide (first: Sneed)
     Sneed: [2/1, 4/1]
     Professor Putricide: [4/1, 4/1]
     Ominous Seer 2/1→2/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 0 vs 0 — winner: draw

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=18, Tier=1) | Sneed (HP=30, Armor=12, Tier=1) | Overlord Saurfang (HP=30, Armor=17, Tier=1) | Ysera (HP=30, Armor=12, Tier=1) | Inge, the Iron Hymn (HP=30, Armor=9, Tier=1) | Professor Putricide (HP=30, Armor=10, Tier=1) | Sylvanas Windrunner (HP=30, Armor=8, Tier=1) | Drek'Thar (HP=30, Armor=7, Tier=1)

### Turn 3

**Yogg-Saron, Hope's End**  HP=30 Armor=18 Gold=5 Tier=1

  Board: 4/1, 1/4
  Tavern: Wrath Weaver 1/4 T1 $3 | Manasaber 4/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Tavern Dish Banana (spell) T1 $1

  → Board: 4/1, 3/6, 1/4
  → Gold: 1→0 | Armor: 18→17
  → Actions (4): buy_tavern_0, play_hand_0, refresh, refresh

**Sneed**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 2/1, 4/1
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Risen Rider 2/1 T1 $3 | Cord Puller 1/1 T1 $3 | Meditation (spell) T1 $3

  → Board: 2/1, 4/1, 1/2 [Taunt,DS]
  → Gold: 1→0
  → Actions (4): buy_tavern_0, play_hand_0, refresh, refresh

**Overlord Saurfang**  HP=30 Armor=17 Gold=5 Tier=1

  Board: 4/7, 4/7
  Tavern: Wrath Weaver 6/9 T1 $3 | Ominous Seer 7/6 T1 $3 | Annoy-o-Tron 6/7 T1 $3

  → Board: 13/19 [G]
  → Hand: 0→1
  → Actions (2): buy_tavern_0, play_hand_0

**Ysera**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 3/3, 3/3
  Tavern: Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Picky Eater 1/1 T1 $3 | Scarlet Survivor 3/3 T1 $3

  → Board: 6/6 [G], 2/4 [Taunt]
  → Actions (3): buy_tavern_3, play_hand_0, play_hand_0

**Inge, the Iron Hymn**  HP=30 Armor=9 Gold=5 Tier=1

  Board: 4/1, 1/2 [Taunt,DS]
  Tavern: Risen Rider 2/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Harmless Bonehead 1/1 T1 $3

  → Board: 4/1, 1/2 [Taunt,DS], 2/1 [Taunt,Reborn]
  → Upgrade T1→T2 | Gold: 2→0
  → Actions (3): buy_tavern_0, play_hand_0, upgrade

**Professor Putricide**  HP=30 Armor=10 Gold=5 Tier=1

  Board: 4/1, 4/1
  Tavern: Cord Puller 1/1 T1 $3 | Risen Rider 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3

  → Board: 4/1, 4/1, 2/1 [Taunt,Reborn]
  → Actions (2): buy_tavern_1, play_hand_0

**Sylvanas Windrunner**  HP=30 Armor=8 Gold=5 Tier=1

  Board: 2/1 [Taunt,Reborn], 1/1 [DS]
  Tavern: Ominous Seer 2/1 T1 $3 | Manasaber 4/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3

  → Board: 2/1 [Taunt,Reborn], 1/1 [DS], 4/1
  → Upgrade T1→T2 | Gold: 2→0
  → Actions (3): buy_tavern_1, play_hand_0, upgrade

**Drek'Thar**  HP=30 Armor=7 Gold=5 Tier=1

  Board: 2/1 [Taunt,Reborn], 1/4
  Tavern: Picky Eater 1/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3

  → Board: 2/1 [Taunt,Reborn], 3/6, 1/4
  → Upgrade T1→T2 | Gold: 2→0 | Armor: 7→6
  → Actions (3): buy_tavern_2, play_hand_0, upgrade

**Combat Phase**

  Inge, the Iron Hymn vs Professor Putricide (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 2/1]
     Professor Putricide: [4/1, 4/1, 2/1]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 1 vs 0 — winner: Inge, the Iron Hymn
  Ysera vs Sylvanas Windrunner (first: Sylvanas Windrunner)
     Ysera: [6/6, 2/4]
     Sylvanas Windrunner: [2/1, 1/1, 4/1]
     Risen Rider 2/1→2/0 DEAD  |  Taunt Test Minion 2/4→2/2
     Scarlet Survivor 6/6→6/2  |  Manasaber 4/1→4/0 DEAD
     Cord Puller 1/1→1/1  |  Taunt Test Minion 2/2→2/1
     Taunt Test Minion 2/1→2/0 DEAD  |  Cord Puller 1/1→1/0 DEAD
     Result: survivors 1 vs 0 — winner: Ysera
  Yogg-Saron, Hope's End vs Drek'Thar (first: Drek'Thar)
     Yogg-Saron, Hope's End: [4/1, 3/6, 1/4]
     Drek'Thar: [2/1, 3/6, 1/4]
     Risen Rider 2/1→2/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Wrath Weaver 3/6→3/3  |  Wrath Weaver 3/6→3/3
     Wrath Weaver 3/3→3/2  |  Wrath Weaver 1/4→1/1
     Wrath Weaver 1/1→1/0 DEAD  |  Wrath Weaver 1/4→1/3
     Wrath Weaver 1/3→1/0 DEAD  |  Wrath Weaver 3/3→3/2
     Result: survivors 1 vs 1 — winner: Yogg-Saron, Hope's End
  Overlord Saurfang vs Sneed (first: Sneed)
     Overlord Saurfang: [13/19]
     Sneed: [2/1, 4/1, 1/2]
     Ominous Seer 2/1→2/0 DEAD  |  Wrath Weaver 13/19→13/17
     Wrath Weaver 13/17→13/16  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 13/16→13/12
     Result: survivors 1 vs 1 — winner: Overlord Saurfang

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=17, Tier=1) | Sneed (HP=30, Armor=12, Tier=1) | Overlord Saurfang (HP=30, Armor=17, Tier=1) | Ysera (HP=30, Armor=12, Tier=1) | Inge, the Iron Hymn (HP=30, Armor=9, Tier=2) | Professor Putricide (HP=30, Armor=7, Tier=1) | Sylvanas Windrunner (HP=30, Armor=6, Tier=2) | Drek'Thar (HP=30, Armor=6, Tier=2)

### Turn 4

**Yogg-Saron, Hope's End**  HP=30 Armor=17 Gold=6 Tier=1

  Board: 4/1, 3/6, 1/4
  Tavern: Cord Puller 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Surf n' Surf 1/1 T1 $3

  → Board: 4/1, 3/6, 1/4, 4/1, 1/1 [DS]
  → Actions (4): buy_tavern_1, play_hand_0, buy_tavern_0, play_hand_0

**Sneed**  HP=30 Armor=12 Gold=6 Tier=1

  Board: 2/1, 4/1, 1/2 [Taunt,DS]
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Cord Puller 1/1 T1 $3 | Manasaber 4/1 T1 $3

  → Board: 2/1, 4/1, 1/2 [Taunt,DS], 4/1, 1/2 [Taunt,DS]
  → Actions (4): buy_tavern_2, play_hand_0, buy_tavern_0, play_hand_0

**Overlord Saurfang**  HP=30 Armor=17 Gold=6 Tier=1

  Board: 13/19 [G]
  Tavern: Ominous Seer 9/8 T1 $3 | Risen Rider 9/8 T1 $3 | Wrath Weaver 8/11 T1 $3

  → Board: 15/21 [G], 8/11, 9/8
  → Armor: 17→16
  → Actions (4): buy_tavern_2, play_hand_1, buy_tavern_0, play_hand_1

**Ysera**  HP=30 Armor=12 Gold=6 Tier=1

  Board: 6/6 [G], 2/4 [Taunt]
  Tavern: Ominous Seer 2/1 T1 $3 | Ominous Seer 2/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Scarlet Survivor 3/3 T1 $3

  → Board: 6/6 [G], 2/4 [Taunt], 3/3, 2/1
  → Actions (4): buy_tavern_3, play_hand_0, buy_tavern_0, play_hand_0

**Inge, the Iron Hymn**  HP=30 Armor=9 Gold=6 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 2/1 [Taunt,Reborn]
  Tavern: Alert Alarmist 2/2 T2 $3 | Tide Raiser 2/1 T2 $3 | Eternal Knight 4/2 T2 $3 | Sewer Rat 3/2 T2 $3 | Chef's Choice (spell) T2 $2

  → Board: 4/1, 1/2 [Taunt,DS], 2/1 [Taunt,Reborn], 4/2, 3/2
  → Actions (4): buy_tavern_2, play_hand_0, buy_tavern_2, play_hand_0

**Professor Putricide**  HP=30 Armor=7 Gold=6 Tier=1

  Board: 4/1, 4/1, 2/1 [Taunt,Reborn]
  Tavern: Cord Puller 1/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Cord Puller 1/1 T1 $3

  → Board: 4/1, 4/1, 2/1 [Taunt,Reborn], 1/1 [DS], 1/1
  → Actions (4): buy_tavern_0, play_hand_0, buy_tavern_0, play_hand_0

**Sylvanas Windrunner**  HP=30 Armor=6 Gold=6 Tier=2

  Board: 2/1 [Taunt,Reborn], 1/1 [DS], 4/1
  Tavern: Alert Alarmist 2/2 T2 $3 | Ominous Seer 2/1 T1 $3 | Sewer Rat 3/2 T2 $3 | Ominous Seer 2/1 T1 $3 | Leaf Through the Pages (spell) T2 $1

  → Board: 2/1 [Taunt,Reborn], 1/1 [DS], 4/1, 3/2, 2/2 [Taunt]
  → Actions (4): buy_tavern_2, play_hand_0, buy_tavern_0, play_hand_0

**Drek'Thar**  HP=30 Armor=6 Gold=6 Tier=2

  Board: 2/1 [Taunt,Reborn], 3/6, 1/4
  Tavern: Metallic Hunter 4/2 T2 $3 | Shell Collector 4/3 T2 $3 | Soul Rewinder 4/1 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Hasty Excavation (spell) T2 $3

  → Board: 2/1 [Taunt,Reborn], 3/6, 1/4, 4/3, 4/2
  → Hand: 0→1
  → Actions (4): buy_tavern_1, play_hand_0, buy_tavern_0, play_hand_1

**Combat Phase**

  Professor Putricide vs Yogg-Saron, Hope's End (first: Professor Putricide)
     Professor Putricide: [4/1, 4/1, 2/1, 1/1, 1/1]
     Yogg-Saron, Hope's End: [4/1, 3/6, 1/4, 4/1, 1/1]
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 3/6→3/2
     Wrath Weaver 3/2→3/1  |  Cord Puller 1/1→1/1
     Cord Puller 1/1→1/0 DEAD  |  Wrath Weaver 3/1→3/0 DEAD
     Wrath Weaver 1/4→1/3  |  Harmless Bonehead 1/1→1/0 DEAD
     Result: survivors 0 vs 2 — winner: Yogg-Saron, Hope's End
  Inge, the Iron Hymn vs Sylvanas Windrunner (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 2/1, 4/2, 3/2]
     Sylvanas Windrunner: [2/1, 1/1, 4/1, 3/2, 2/2]
     Manasaber 4/1→4/0 DEAD  |  Alert Alarmist 2/2→2/0 DEAD
     Risen Rider 2/1→2/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Annoy-o-Tron 1/2→1/2  |  Manasaber 4/1→4/0 DEAD
     Cord Puller 1/1→1/1  |  Annoy-o-Tron 1/2→1/1
     Eternal Knight 4/2→5/0 DEAD  |  Sewer Rat 3/2→3/0 DEAD
     Result: survivors 2 vs 1 — winner: Inge, the Iron Hymn
  Overlord Saurfang vs Ysera (first: Ysera)
     Overlord Saurfang: [15/21, 8/11, 9/8]
     Ysera: [6/6, 2/4, 3/3, 2/1]
     Scarlet Survivor 6/6→6/0 DEAD  |  Wrath Weaver 15/21→15/15
     Wrath Weaver 15/15→15/13  |  Taunt Test Minion 2/4→2/0 DEAD
     Scarlet Survivor 3/3→3/0 DEAD  |  Wrath Weaver 8/11→8/8
     Wrath Weaver 8/8→8/6  |  Ominous Seer 2/1→2/0 DEAD
     Result: survivors 3 vs 0 — winner: Overlord Saurfang
  Sneed vs Drek'Thar (first: Drek'Thar)
     Sneed: [2/1, 4/1, 1/2, 4/1, 1/2]
     Drek'Thar: [2/1, 3/6, 1/4, 4/3, 4/2]
     Risen Rider 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Ominous Seer 2/1→2/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 1/4→1/0 DEAD
     Shell Collector 4/3→4/2  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Wrath Weaver 3/5→3/4
     Result: survivors 1 vs 2 — winner: Sneed

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=17, Tier=1) | Sneed (HP=30, Armor=12, Tier=1) | Overlord Saurfang (HP=30, Armor=16, Tier=1) | Ysera (HP=30, Armor=8, Tier=1) | Inge, the Iron Hymn (HP=30, Armor=9, Tier=2) | Professor Putricide (HP=30, Armor=4, Tier=1) | Sylvanas Windrunner (HP=30, Armor=6, Tier=2) | Drek'Thar (HP=30, Armor=6, Tier=2)

### Turn 5

**Yogg-Saron, Hope's End**  HP=30 Armor=17 Gold=7 Tier=1

  Board: 4/1, 3/6, 1/4, 4/1, 1/1 [DS]
  Tavern: Manasaber 4/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Manasaber 4/1 T1 $3

  → Board: 3/6, 1/4, 1/1 [DS], 8/2 [G], 4/1
  → Upgrade T1→T2 | Gold: 1→0 | Hand: 0→1
  → Actions (5): buy_tavern_0, play_hand_0, buy_tavern_1, play_hand_1, upgrade

**Sneed**  HP=30 Armor=12 Gold=7 Tier=1

  Board: 2/1, 4/1, 1/2 [Taunt,DS], 4/1, 1/2 [Taunt,DS]
  Tavern: Picky Eater 1/1 T1 $3 | Cord Puller 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3

  → Board: 2/1, 4/1, 1/2 [Taunt,DS], 4/1, 1/2 [Taunt,DS], 3/6, 2/2
  → Upgrade T1→T2 | Gold: 1→0 | Armor: 12→11
  → Actions (5): buy_tavern_2, play_hand_0, buy_tavern_0, play_hand_0, upgrade

**Overlord Saurfang**  HP=30 Armor=16 Gold=7 Tier=1

  Board: 15/21 [G], 8/11, 9/8
  Tavern: Harmless Bonehead 12/12 T1 $3 | Wrath Weaver 12/15 T1 $3 | Annoy-o-Tron 12/13 T1 $3

  → Board: 17/23 [G], 10/13, 9/8, 12/15, 12/13 [Taunt,DS]
  → Upgrade T1→T2 | Gold: 1→0 | Armor: 16→14
  → Actions (5): buy_tavern_1, play_hand_1, buy_tavern_1, play_hand_1, upgrade

**Ysera**  HP=30 Armor=8 Gold=7 Tier=1

  Board: 6/6 [G], 2/4 [Taunt], 3/3, 2/1
  Tavern: Harmless Bonehead 1/1 T1 $3 | Risen Rider 2/1 T1 $3 | Picky Eater 1/1 T1 $3 | Scarlet Survivor 3/3 T1 $3

  → Board: 6/6 [G], 2/4 [Taunt], 3/3, 2/1, 3/3, 2/1 [Taunt,Reborn]
  → Upgrade T1→T2 | Gold: 1→0
  → Actions (5): buy_tavern_3, play_hand_0, buy_tavern_1, play_hand_0, upgrade

**Inge, the Iron Hymn**  HP=30 Armor=9 Gold=7 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 2/1 [Taunt,Reborn], 5/2, 3/2
  Tavern: Ominous Seer 2/1 T1 $3 | Alert Alarmist 2/2 T2 $3 | Shell Collector 4/3 T2 $3 | Ominous Seer 2/1 T1 $3 | Search Through Time (spell) T2 $2

  → Board: 4/1, 1/2 [Taunt,DS], 2/1 [Taunt,Reborn], 5/2, 3/2, 4/3, 2/2 [Taunt]
  → Hand: 0→1
  → Actions (4): buy_tavern_2, play_hand_0, buy_tavern_1, play_hand_1

**Professor Putricide**  HP=30 Armor=4 Gold=7 Tier=1

  Board: 4/1, 4/1, 2/1 [Taunt,Reborn], 1/1 [DS], 1/1
  Tavern: Picky Eater 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Risen Rider 2/1 T1 $3

  → Board: 4/1, 4/1, 2/1 [Taunt,Reborn], 1/1 [DS], 1/1, 1/4, 2/1 [Taunt,Reborn]
  → Upgrade T1→T2 | Gold: 1→0
  → Actions (5): buy_tavern_1, play_hand_0, buy_tavern_1, play_hand_0, upgrade

**Sylvanas Windrunner**  HP=30 Armor=6 Gold=7 Tier=2

  Board: 2/1 [Taunt,Reborn], 1/1 [DS], 4/1, 3/2, 2/2 [Taunt]
  Tavern: Scarlet Skull 2/1 T2 $3 | Sewer Rat 3/2 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Humming Bird 1/4 T2 $3 | Might of Stormwind (spell) T2 $2

  → Board: 2/1 [Taunt,Reborn], 1/1 [DS], 4/1, 3/2, 2/2 [Taunt], 3/4, 3/2
  → Actions (4): buy_tavern_2, play_hand_0, buy_tavern_1, play_hand_0

**Drek'Thar**  HP=30 Armor=6 Gold=7 Tier=2

  Board: 2/1 [Taunt,Reborn], 3/6, 1/4, 4/3, 4/2
  Tavern: Metallic Hunter 4/2 T2 $3 | Metallic Hunter 4/2 T2 $3 | Harmless Bonehead 1/1 T1 $3 | Metallic Hunter 4/2 T2 $3 | Strike Oil (spell) T2 $3

  → Board: 2/1 [Taunt,Reborn], 3/6, 1/4, 4/3, 8/4 [G]
  → Hand: 2→3
  → Actions (4): buy_tavern_0, play_hand_2, buy_tavern_0, play_hand_2

**Combat Phase**

  Inge, the Iron Hymn vs Yogg-Saron, Hope's End (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 2/1, 5/2, 3/2, 4/3, 2/2]
     Yogg-Saron, Hope's End: [3/6, 1/4, 1/1, 8/2, 4/1]
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 3/6→3/2
     Wrath Weaver 3/2→3/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Annoy-o-Tron 1/2→1/2  |  Wrath Weaver 1/4→1/3
     Wrath Weaver 1/3→1/2  |  Annoy-o-Tron 1/2→1/1
     Eternal Knight 5/2→5/1  |  Cord Puller 1/1→1/1
     Cord Puller 1/1→1/0 DEAD  |  Alert Alarmist 2/2→2/1
     Sewer Rat 3/2→3/1  |  Wrath Weaver 1/2→1/0 DEAD
     Manasaber 8/2→8/0 DEAD  |  Alert Alarmist 2/1→2/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 3 vs 0 — winner: Inge, the Iron Hymn
  Sneed vs Ysera (first: Sneed)
     Sneed: [2/1, 4/1, 1/2, 4/1, 1/2, 3/6, 2/2]
     Ysera: [6/6, 2/4, 3/3, 2/1, 3/3, 2/1]
     Ominous Seer 2/1→2/0 DEAD  |  Taunt Test Minion 2/4→2/2
     Scarlet Survivor 6/6→6/5  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Taunt Test Minion 2/2→2/1  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Taunt Test Minion 2/1→2/0 DEAD
     Scarlet Survivor 3/3→3/2  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Scarlet Survivor 6/5→6/1
     Ominous Seer 2/1→2/0 DEAD  |  Picky Eater 2/2→2/0 DEAD
     Wrath Weaver 3/6→3/3  |  Scarlet Survivor 3/3→3/0 DEAD
     Result: survivors 1 vs 2 — winner: Sneed
  Drek'Thar vs Sylvanas Windrunner (first: Sylvanas Windrunner)
     Drek'Thar: [2/1, 3/6, 1/4, 4/3, 8/4]
     Sylvanas Windrunner: [2/1, 1/1, 4/1, 3/2, 2/2, 3/4, 3/2]
     Risen Rider 2/1→2/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 3/6→3/4  |  Alert Alarmist 2/2→2/0 DEAD
     Cord Puller 1/1→1/1  |  Shell Collector 4/3→4/2
     Wrath Weaver 1/4→1/3  |  Cord Puller 1/1→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 3/4→3/0 DEAD
     Shell Collector 4/2→4/0 DEAD  |  Sewer Rat 3/2→3/0 DEAD
     Sewer Rat 3/2→3/1  |  Wrath Weaver 1/3→1/0 DEAD
     Metallic Hunter 8/4→8/1  |  Ancestral Automaton 3/4→3/0 DEAD
     Result: survivors 1 vs 1 — winner: Drek'Thar
  Professor Putricide vs Overlord Saurfang (first: Professor Putricide)
     Professor Putricide: [4/1, 4/1, 2/1, 1/1, 1/1, 1/4, 2/1]
     Overlord Saurfang: [17/23, 10/13, 9/8, 12/15, 12/13]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 12/13→12/13
     Wrath Weaver 17/23→17/21  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 12/13→12/9
     Wrath Weaver 10/13→10/11  |  Risen Rider 2/1→2/0 DEAD
     Cord Puller 1/1→1/1  |  Annoy-o-Tron 12/9→12/8
     Ominous Seer 9/8→9/7  |  Wrath Weaver 1/4→1/0 DEAD
     Harmless Bonehead 1/1→1/0 DEAD  |  Annoy-o-Tron 12/8→12/7
     Wrath Weaver 12/15→12/14  |  Cord Puller 1/1→1/0 DEAD
     Result: survivors 0 vs 5 — winner: Overlord Saurfang

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=10, Tier=2) | Sneed (HP=30, Armor=11, Tier=2) | Overlord Saurfang (HP=30, Armor=14, Tier=2) | Ysera (HP=30, Armor=8, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=9, Tier=2) | Sylvanas Windrunner (HP=30, Armor=6, Tier=2) | Drek'Thar (HP=30, Armor=6, Tier=2) | Professor Putricide (HP=27, Armor=0, Tier=2)

### Turn 6

**Yogg-Saron, Hope's End**  HP=30 Armor=10 Gold=8 Tier=2

  Board: 3/6, 1/4, 1/1 [DS], 8/2 [G], 4/1
  Tavern: Alert Alarmist 2/2 T2 $3 | Humming Bird 1/4 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Soul Rewinder 4/1 T2 $3

  → Board: 3/6, 1/4, 1/1 [DS], 8/2 [G], 4/1, 3/4
  → Trinket: Lucky Tabby
  → Actions (2): buy_tavern_2, play_hand_1

**Sneed**  HP=30 Armor=11 Gold=8 Tier=2

  Board: 2/1, 4/1, 1/2 [Taunt,DS], 4/1, 1/2 [Taunt,DS], 3/6, 2/2
  Tavern: Old Soul 3/4 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Shell Collector 4/3 T2 $3 | Eternal Knight 4/2 T2 $3

  → Board: 4/1, 1/2 [Taunt,DS], 4/1, 1/2 [Taunt,DS], 3/6, 2/2, 3/3
  → Upgrade T2→T3 | Gold: 6→0 | Trinket: Pilgrimp Sticker | Hand: 1→0
  → Actions (3): sell_board_0, play_hand_0, upgrade

**Overlord Saurfang**  HP=30 Armor=14 Gold=8 Tier=2

  Board: 17/23 [G], 10/13, 9/8, 12/15, 12/13 [Taunt,DS]
  Tavern: Shell Collector 19/18 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Lava Lurker 17/20 T2 $3

  → Board: 21/27 [G], 14/17, 9/8, 16/19, 12/13 [Taunt,DS], 1/1, 1/1
  → Upgrade T2→T3 | Gold: 7→1 | Armor: 14→8 | Trinket: Implicator Portrait
  → Actions (3): play_hand_1, play_hand_1, upgrade

**Ysera**  HP=30 Armor=8 Gold=8 Tier=2

  Board: 6/6 [G], 2/4 [Taunt], 3/3, 2/1, 3/3, 2/1 [Taunt,Reborn]
  Tavern: Soul Rewinder 4/1 T2 $3 | Manasaber 4/1 T1 $3 | Lava Lurker 2/5 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Blazing Skyfin 2/4 T2 $3

  → Board: 6/6 [G], 2/4 [Taunt], 3/3, 3/3, 2/1 [Taunt,Reborn], 2/5, 3/4
  → Trinket: Goldenizer Supply
  → Actions (5): buy_tavern_2, play_hand_0, sell_board_3, buy_tavern_2, play_hand_0

**Inge, the Iron Hymn**  HP=30 Armor=9 Gold=8 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 2/1 [Taunt,Reborn], 5/2, 3/2, 4/3, 2/2 [Taunt]
  Tavern: Ancestral Automaton 3/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Tide Raiser 2/1 T2 $3

  → Board: 4/1, 1/2 [Taunt,DS], 2/1 [Taunt,Reborn], 5/2, 3/2, 4/3, 2/2 [Taunt]
  → Upgrade T2→T3 | Gold: 6→2 | Trinket: Ophidian Staff
  → Actions (1): upgrade

**Professor Putricide**  HP=27 Armor=0 Gold=8 Tier=2

  Board: 4/1, 4/1, 2/1 [Taunt,Reborn], 1/1 [DS], 1/1, 1/4, 2/1 [Taunt,Reborn]
  Tavern: Alert Alarmist 2/2 T2 $3 | Eternal Knight 4/2 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Shell Collector 4/3 T2 $3

  → Board: 4/1, 4/1, 5/1 [Taunt,Reborn], 1/1 [DS], 4/1, 1/4, 5/1 [Taunt,Reborn]
  → Upgrade T2→T3 | Gold: 7→1 | Trinket: Artisanal Urn
  → Actions (1): upgrade

**Sylvanas Windrunner**  HP=30 Armor=6 Gold=8 Tier=2

  Board: 2/1 [Taunt,Reborn], 1/1 [DS], 4/1, 3/2, 2/2 [Taunt], 3/4, 3/2
  Tavern: Laboratory Assistant 3/4 T2 $3 | Sewer Rat 3/2 T2 $3 | Soul Rewinder 4/1 T2 $3 | Harmless Bonehead 1/1 T1 $3

  → Board: 2/1 [Taunt,Reborn], 1/1 [DS], 4/1, 3/2, 2/2 [Taunt], 3/4, 3/2
  → Upgrade T2→T3 | Gold: 6→2 | Trinket: Ophidian Staff
  → Actions (1): upgrade

**Drek'Thar**  HP=30 Armor=6 Gold=8 Tier=2

  Board: 2/1 [Taunt,Reborn], 3/6, 1/4, 4/3, 8/4 [G]
  Tavern: Humming Bird 1/4 T2 $3 | Eternal Knight 4/2 T2 $3 | Eternal Knight 4/2 T2 $3 | Humming Bird 1/4 T2 $3

  → Board: 2/1 [Taunt,Reborn], 3/6, 1/4, 4/3, 8/4 [G], 4/2, 4/2
  → Trinket: Impulsive Portrait
  → Actions (4): buy_tavern_1, play_hand_3, buy_tavern_1, play_hand_3

**Combat Phase**

  Inge, the Iron Hymn vs Ysera (first: Ysera)
     Inge, the Iron Hymn: [4/1, 1/2, 2/1, 5/2, 3/2, 4/3, 2/2]
     Ysera: [6/6, 2/4, 3/3, 3/3, 2/1, 2/5, 3/4]
     Scarlet Survivor 6/6→6/4  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Taunt Test Minion 2/4→2/3  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Taunt Test Minion 2/3→2/2
     Scarlet Survivor 3/3→3/1  |  Alert Alarmist 2/2→2/0 DEAD
     Eternal Knight 5/2→6/0 DEAD  |  Taunt Test Minion 2/2→2/0 DEAD
     Scarlet Survivor 3/3→3/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Sewer Rat 3/2→3/0 DEAD  |  Scarlet Survivor 6/4→6/1
     Result: survivors 0 vs 4 — winner: Ysera
  Sylvanas Windrunner vs Yogg-Saron, Hope's End (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [2/1, 1/1, 4/1, 3/2, 2/2, 3/4, 3/2]
     Yogg-Saron, Hope's End: [3/6, 1/4, 1/1, 8/2, 4/1, 3/4]
     Risen Rider 2/1→2/0 DEAD  |  Wrath Weaver 3/6→3/4
     Wrath Weaver 3/4→3/2  |  Alert Alarmist 2/2→2/0 DEAD
     Cord Puller 1/1→1/1  |  Wrath Weaver 1/4→1/3
     Wrath Weaver 1/3→1/0 DEAD  |  Sewer Rat 3/2→3/1
     Manasaber 4/1→4/0 DEAD  |  Manasaber 8/2→8/0 DEAD
     Cord Puller 1/1→1/1  |  Cord Puller 1/1→1/0 DEAD
     Sewer Rat 3/2→3/0 DEAD  |  Wrath Weaver 3/2→3/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Sewer Rat 3/1→3/0 DEAD
     Ancestral Automaton 3/4→3/1  |  Ancestral Automaton 3/4→3/1
     Ancestral Automaton 3/1→3/0 DEAD  |  Ancestral Automaton 3/1→3/0 DEAD
     Result: survivors 0 vs 1 — winner: Yogg-Saron, Hope's End
  Drek'Thar vs Overlord Saurfang (first: Overlord Saurfang)
     Drek'Thar: [2/1, 3/6, 1/4, 4/3, 8/4, 4/2, 4/2]
     Overlord Saurfang: [21/27, 14/17, 9/8, 16/19, 12/13, 1/1, 1/1]
     Wrath Weaver 21/27→21/25  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 3/6→3/0 DEAD  |  Annoy-o-Tron 12/13→12/13
     Wrath Weaver 14/17→14/13  |  Eternal Knight 4/2→5/0 DEAD
     Wrath Weaver 1/4→1/0 DEAD  |  Annoy-o-Tron 12/13→12/12
     Ominous Seer 9/8→9/0 DEAD  |  Metallic Hunter 8/4→8/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Annoy-o-Tron 12/12→12/8
     Wrath Weaver 16/19→16/14  |  Eternal Knight 5/2→6/0 DEAD
     Result: survivors 0 vs 6 — winner: Overlord Saurfang
  Sneed vs Professor Putricide (first: Sneed)
     Sneed: [4/1, 1/2, 4/1, 1/2, 3/6, 2/2, 3/3]
     Professor Putricide: [4/1, 4/1, 5/1, 1/1, 4/1, 1/4, 5/1]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 5/1→5/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/2  |  Risen Rider 5/1→5/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 1/4→1/0 DEAD
     Cord Puller 1/1→1/1  |  Annoy-o-Tron 1/2→1/1
     Annoy-o-Tron 1/1→1/0 DEAD  |  Harmless Bonehead 4/1→4/0 DEAD
     Result: survivors 3 vs 1 — winner: Sneed

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=10, Tier=2) | Sneed (HP=30, Armor=11, Tier=3) | Overlord Saurfang (HP=30, Armor=8, Tier=3) | Ysera (HP=30, Armor=8, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=1, Tier=3) | Sylvanas Windrunner (HP=30, Armor=3, Tier=3) | Professor Putricide (HP=27, Armor=0, Tier=3) | Drek'Thar (HP=26, Armor=0, Tier=2)

### Turn 7

**Yogg-Saron, Hope's End**  HP=30 Armor=10 Gold=9 Tier=2

  Board: 3/6, 1/4, 1/1 [DS], 8/2 [G], 4/1, 3/4
  Tavern: Alert Alarmist 2/2 T2 $3 | Scarlet Skull 2/1 T2 $3 | Metallic Hunter 4/2 T2 $3 | Scarlet Skull 2/1 T2 $3

  → Board: 3/6, 1/4, 1/1 [DS], 8/2 [G], 4/1, 3/4, 4/2
  → Upgrade T2→T3 | Gold: 6→1
  → Actions (3): buy_tavern_2, play_hand_1, upgrade

**Sneed**  HP=30 Armor=11 Gold=9 Tier=3

  Board: 4/1, 1/2 [Taunt,DS], 4/1, 1/2 [Taunt,DS], 3/6, 2/2, 3/3
  Tavern: Dustbone Devastator 2/6 T3 $3 | Deep-Sea Angler 2/3 T3 $3 | Laboratory Assistant 3/4 T2 $3 | Deep-Sea Angler 2/3 T3 $3 | Planar Telescope (spell) T3 $4

  → Board: 4/1, 4/1, 1/2 [Taunt,DS], 3/6, 2/2, 3/3, 1/1 [DS]
  → Gold: 10→9 | Hand: 1→0
  → Actions (3): sell_board_1, play_hand_0, refresh

**Overlord Saurfang**  HP=30 Armor=8 Gold=9 Tier=3

  Board: 21/27 [G], 14/17, 9/8, 16/19, 12/13 [Taunt,DS], 1/1, 1/1
  Tavern: Sprightly Scarab 19/17 T3 $3 | Nerubian Deathswarmer 17/20 T2 $3 | Reef Riffer 19/18 T2 $3 | Handless Forsaken 18/17 T3 $3 | Overconfidence (spell) T3 $1

  → Board: 21/27 [G], 14/17, 9/8, 16/19, 12/13 [Taunt,DS], 1/1, 18/20
  → Actions (3): sell_board_5, buy_tavern_1, play_hand_1

**Ysera**  HP=30 Armor=8 Gold=9 Tier=2

  Board: 6/6 [G], 2/4 [Taunt], 3/3, 3/3, 2/1 [Taunt,Reborn], 2/5, 3/4
  Tavern: Reef Riffer 3/2 T2 $3 | Alert Alarmist 2/2 T2 $3 | Lava Lurker 2/5 T2 $3 | Tide Raiser 2/1 T2 $3 | Tarecgosa 4/4 T2 $3

  → Board: 6/6 [G], 2/4 [Taunt], 3/3, 3/3, 2/5, 3/4, 4/4
  → Upgrade T2→T3
  → Actions (4): upgrade, sell_board_4, buy_tavern_4, play_hand_1

**Inge, the Iron Hymn**  HP=30 Armor=1 Gold=9 Tier=3

  Board: 4/1, 1/2 [Taunt,DS], 2/1 [Taunt,Reborn], 6/2, 3/2, 4/3, 2/2 [Taunt]
  Tavern: Sprightly Scarab 3/1 T3 $3 | Picky Eater 1/1 T1 $3 | Tide Raiser 2/1 T2 $3 | Tide Raiser 2/1 T2 $3 | Hostile Bounty (spell) T3 $2

  → Board: 4/1, 2/1 [Taunt,Reborn], 6/2, 4/3 [Reborn], 4/3, 2/2 [Taunt], 3/1
  → Actions (3): sell_board_1, buy_tavern_0, play_hand_1

**Professor Putricide**  HP=27 Armor=0 Gold=9 Tier=3

  Board: 4/1, 4/1, 5/1 [Taunt,Reborn], 1/1 [DS], 4/1, 1/4, 5/1 [Taunt,Reborn]
  Tavern: Leeching Felhound 3/3 T3 $3 | Cadaver Caretaker 6/3 T3 $3 | Technical Element 5/6 T3 $3 | Hardy Orca 1/6 T3 $3 | Shiny Ring (spell) T3 $2

  → Board: 4/1, 4/1, 5/1 [Taunt,Reborn], 4/1, 1/4, 5/1 [Taunt,Reborn], 5/6
  → Actions (3): sell_board_3, buy_tavern_2, play_hand_0

**Sylvanas Windrunner**  HP=30 Armor=3 Gold=9 Tier=3

  Board: 2/1 [Taunt,Reborn], 1/1 [DS], 4/1, 3/2, 2/2 [Taunt], 3/4, 3/2
  Tavern: Sly Raptor 1/3 T3 $3 | Leeching Felhound 3/3 T3 $3 | Annoy-o-Module 2/4 T3 $3 | Humming Bird 1/4 T2 $3 | Robust Evolution (spell) T3 $1

  → Board: 2/1 [Taunt,Reborn], 4/1, 3/2, 2/2 [Taunt], 3/4, 3/2
  → Armor: 3→0 | Hand: 0→1
  → Actions (2): sell_board_1, buy_tavern_1

**Drek'Thar**  HP=26 Armor=0 Gold=9 Tier=2

  Board: 2/1 [Taunt,Reborn], 3/6, 1/4, 4/3, 8/4 [G], 6/2, 6/2
  Tavern: Metallic Hunter 4/2 T2 $3 | Lava Lurker 2/5 T2 $3 | Alert Alarmist 2/2 T2 $3 | Sewer Rat 3/2 T2 $3

  → Board: 3/6, 1/4, 4/3, 8/4 [G], 6/2, 6/2, 2/5
  → Upgrade T2→T3
  → Actions (4): upgrade, sell_board_0, buy_tavern_1, play_hand_4

**Combat Phase**

  Drek'Thar vs Yogg-Saron, Hope's End (first: Drek'Thar)
     Drek'Thar: [3/6, 1/4, 4/3, 8/4, 6/2, 6/2, 2/5]
     Yogg-Saron, Hope's End: [3/6, 1/4, 1/1, 8/2, 4/1, 3/4, 4/2]
     Wrath Weaver 3/6→3/5  |  Wrath Weaver 1/4→1/1
     Wrath Weaver 3/6→3/0 DEAD  |  Metallic Hunter 8/4→8/1
     Wrath Weaver 1/4→1/1  |  Ancestral Automaton 3/4→3/3
     Wrath Weaver 1/1→1/0 DEAD  |  Lava Lurker 2/5→2/4
     Shell Collector 4/3→4/2  |  Cord Puller 1/1→1/1
     Cord Puller 1/1→1/0 DEAD  |  Metallic Hunter 8/1→8/0 DEAD
     Eternal Knight 6/2→7/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Manasaber 8/2→8/0 DEAD  |  Lava Lurker 2/4→2/0 DEAD
     Eternal Knight 7/2→8/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Ancestral Automaton 3/3→3/0 DEAD  |  Shell Collector 4/2→4/0 DEAD
     Result: survivors 2 vs 0 — winner: Drek'Thar
  Sylvanas Windrunner vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Sylvanas Windrunner: [2/1, 4/1, 3/2, 2/2, 3/4, 3/2]
     Inge, the Iron Hymn: [4/1, 2/1, 6/2, 4/3, 4/3, 2/2, 3/1]
     Manasaber 4/1→4/0 DEAD  |  Alert Alarmist 2/2→2/0 DEAD
     Risen Rider 2/1→2/0 DEAD  |  Alert Alarmist 2/2→2/0 DEAD
     Risen Rider 2/1→2/0 DEAD  |  Sewer Rat 3/2→3/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Sewer Rat 4/3→4/0 DEAD
     Eternal Knight 6/2→7/0 DEAD  |  Sewer Rat 3/2→3/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Result: survivors 0 vs 1 — winner: Inge, the Iron Hymn
  Sneed vs Overlord Saurfang (first: Sneed)
     Sneed: [4/1, 4/1, 1/2, 3/6, 2/2, 3/3, 1/1]
     Overlord Saurfang: [21/27, 14/17, 9/8, 16/19, 12/13, 1/1, 18/20]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 12/13→12/13
     Wrath Weaver 21/27→21/26  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 12/13→12/9
     Wrath Weaver 14/17→14/16  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 3/6→3/0 DEAD  |  Annoy-o-Tron 12/9→12/6
     Ominous Seer 9/8→9/7  |  Cord Puller 1/1→1/1
     Picky Eater 2/2→2/0 DEAD  |  Annoy-o-Tron 12/6→12/4
     Wrath Weaver 16/19→16/16  |  Scarlet Survivor 3/3→3/0 DEAD
     Cord Puller 1/1→1/0 DEAD  |  Annoy-o-Tron 12/4→12/3
     Result: survivors 0 vs 7 — winner: Overlord Saurfang
  Professor Putricide vs Ysera (first: Professor Putricide)
     Professor Putricide: [4/1, 4/1, 5/1, 4/1, 1/4, 5/1, 5/6]
     Ysera: [6/6, 2/4, 3/3, 3/3, 2/5, 3/4, 4/4]
     Manasaber 4/1→4/0 DEAD  |  Taunt Test Minion 2/4→2/0 DEAD
     Scarlet Survivor 6/6→6/1  |  Risen Rider 5/1→5/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Lava Lurker 2/5→2/1
     Scarlet Survivor 3/3→3/0 DEAD  |  Risen Rider 5/1→5/0 DEAD
     Harmless Bonehead 4/1→4/0 DEAD  |  Tarecgosa 4/4→4/0 DEAD
     Scarlet Survivor 3/3→3/0 DEAD  |  Technical Element 5/6→5/3
     Wrath Weaver 1/4→1/0 DEAD  |  Scarlet Survivor 6/1→6/0 DEAD
     Lava Lurker 2/1→2/0 DEAD  |  Technical Element 5/3→5/1
     Technical Element 5/1→5/0 DEAD  |  Laboratory Assistant 3/4→3/0 DEAD
     Result: survivors 0 vs 0 — winner: draw

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=5, Tier=3) | Sneed (HP=30, Armor=1, Tier=3) | Overlord Saurfang (HP=30, Armor=8, Tier=3) | Ysera (HP=30, Armor=8, Tier=3) | Inge, the Iron Hymn (HP=30, Armor=1, Tier=3) | Professor Putricide (HP=27, Armor=0, Tier=3) | Drek'Thar (HP=26, Armor=0, Tier=3) | Sylvanas Windrunner (HP=24, Armor=0, Tier=3)

### Turn 8

**Yogg-Saron, Hope's End**  HP=30 Armor=5 Gold=10 Tier=3

  Board: 3/6, 1/4, 1/1 [DS], 8/2 [G], 4/1, 3/4, 4/2
  Tavern: Metallic Hunter 4/2 T2 $3 | Hardy Orca 1/6 T3 $3 | Old Soul 3/4 T2 $3 | Sprightly Scarab 3/1 T3 $3 | Careful Investment (spell) T3 $1

  → Board: 3/6, 1/4, 8/2 [G], 4/1, 3/4, 4/2, 1/6 [Taunt]
  → Upgrade T3→T4
  → Actions (4): upgrade, sell_board_2, buy_tavern_1, play_hand_2

**Sneed**  HP=30 Armor=1 Gold=10 Tier=3

  Board: 4/1, 4/1, 1/2 [Taunt,DS], 3/6, 2/2, 3/3, 1/1 [DS]
  Tavern: Dustbone Devastator 2/6 T3 $3 | Metallic Hunter 4/2 T2 $3 | Old Soul 3/4 T2 $3 | Leeching Felhound 3/3 T3 $3 | Friendly Bounty (spell) T3 $2

  → Board: 4/1, 4/1, 1/2 [Taunt,DS], 5/8, 2/2, 3/3, 1/4
  → Upgrade T3→T4 | Armor: 1→0 | Hand: 1→0
  → Actions (3): upgrade, sell_board_6, play_hand_0

**Overlord Saurfang**  HP=30 Armor=8 Gold=10 Tier=3

  Board: 21/27 [G], 14/17, 9/8, 16/19, 12/13 [Taunt,DS], 1/1, 18/20
  Tavern: Tide Raiser 20/19 T2 $3 | Humming Bird 19/22 T2 $3 | Old Soul 22/22 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Tricky Trousers (spell) T3 $1

  → Board: 21/27 [G], 14/17, 9/8, 16/19, 12/13 [Taunt,DS], 18/20, 22/22
  → Upgrade T3→T4
  → Actions (4): upgrade, sell_board_5, buy_tavern_2, play_hand_1

**Ysera**  HP=30 Armor=8 Gold=10 Tier=3

  Board: 6/6 [G], 2/4 [Taunt], 3/3, 3/3, 2/5, 3/4, 4/4
  Tavern: Mummifier 5/2 T3 $3 | Shell Collector 4/3 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Scarlet Skull 2/1 T2 $3 | Healthy Bounty (spell) T3 $2 | Blazing Skyfin 2/4 T2 $3

  → Board: 6/6 [G], 3/3, 3/3, 2/5, 3/4, 4/4, 5/2
  → Upgrade T3→T4
  → Actions (4): upgrade, sell_board_1, buy_tavern_0, play_hand_2

**Inge, the Iron Hymn**  HP=30 Armor=1 Gold=10 Tier=3

  Board: 4/1, 2/1 [Taunt,Reborn], 7/2, 4/3 [Reborn], 4/3, 2/2 [Taunt], 3/1
  Tavern: Humming Bird 1/4 T2 $3 | Sewer Rat 3/2 T2 $3 | Leeching Felhound 3/3 T3 $3 | Leeching Felhound 3/3 T3 $3 | Wealthy Bounty (spell) T3 $2

  → Board: 4/1, 7/2, 4/3 [Reborn], 4/3, 2/2 [Taunt], 3/1
  → Upgrade T3→T4 | HP: 30→28 | Armor: 1→0 | Hand: 1→2
  → Actions (3): upgrade, sell_board_1, buy_tavern_2

**Professor Putricide**  HP=27 Armor=0 Gold=10 Tier=3

  Board: 4/1, 4/1, 5/1 [Taunt,Reborn], 4/1, 1/4, 5/1 [Taunt,Reborn], 5/6
  Tavern: Cadaver Caretaker 6/3 T3 $3 | Deep Blue Crooner 2/2 T3 $3 | Sly Raptor 1/3 T3 $3 | Sewer Rat 3/2 T2 $3 | Selfish Bounty (spell) T3 $2

  → Board: 4/1, 5/1 [Taunt,Reborn], 4/1, 1/4, 5/1 [Taunt,Reborn], 5/6, 6/3
  → Upgrade T3→T4
  → Actions (4): upgrade, sell_board_0, buy_tavern_0, play_hand_0

**Sylvanas Windrunner**  HP=24 Armor=0 Gold=10 Tier=3

  Board: 2/1 [Taunt,Reborn], 4/1, 3/2, 2/2 [Taunt], 3/4, 3/2
  Tavern: Sly Raptor 1/3 T3 $3 | Handless Forsaken 2/1 T3 $3 | Dustbone Devastator 2/6 T3 $3 | Cord Puller 1/1 T1 $3 | Mounting Avalanche (spell) T3 $2

  → Board: 4/1, 3/2, 2/2 [Taunt], 3/4, 3/2, 3/3, 2/6
  → Upgrade T3→T4
  → Actions (6): play_hand_0, upgrade, sell_board_0, buy_tavern_2, play_hand_0, buy_tavern_3

**Drek'Thar**  HP=26 Armor=0 Gold=10 Tier=3

  Board: 3/6, 1/4, 4/3, 8/4 [G], 8/2, 8/2, 2/5
  Tavern: Sprightly Scarab 3/1 T3 $3 | Risen Rider 2/1 T1 $3 | Deep-Sea Angler 2/3 T3 $3 | Alert Alarmist 2/2 T2 $3 | Fleeting Vigor (spell) T3 $1

  → Board: 3/6, 1/4, 4/3, 8/4 [G], 8/2, 8/2, 2/5
  → Upgrade T3→T4 | Gold: 1→0 | Hand: 5→6
  → Actions (4): upgrade, buy_tavern_4, refresh, refresh

**Combat Phase**

  Inge, the Iron Hymn vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Inge, the Iron Hymn: [4/1, 7/2, 4/3, 4/3, 2/2, 3/1]
     Yogg-Saron, Hope's End: [3/6, 1/4, 8/2, 4/1, 3/4, 4/2, 1/6]
     Wrath Weaver 3/6→3/4  |  Alert Alarmist 2/2→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Hardy Orca 1/6→1/2
     Wrath Weaver 1/4→1/0 DEAD  |  Eternal Knight 7/2→7/1
     Eternal Knight 7/1→8/0 DEAD  |  Hardy Orca 1/2→1/0 DEAD
     Manasaber 8/2→8/0 DEAD  |  Sewer Rat 4/3→4/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Sprightly Scarab 3/1→3/0 DEAD
     Result: survivors 0 vs 2 — winner: Yogg-Saron, Hope's End
  Overlord Saurfang vs Ysera (first: Overlord Saurfang)
     Overlord Saurfang: [21/27, 14/17, 9/8, 16/19, 12/13, 18/20, 22/22]
     Ysera: [6/6, 3/3, 3/3, 2/5, 3/4, 4/4, 5/2]
     Wrath Weaver 21/27→21/24  |  Scarlet Survivor 3/3→3/0 DEAD
     Scarlet Survivor 6/6→6/0 DEAD  |  Annoy-o-Tron 12/13→12/13
     Wrath Weaver 14/17→14/14  |  Laboratory Assistant 3/4→3/0 DEAD
     Scarlet Survivor 3/3→3/0 DEAD  |  Annoy-o-Tron 12/13→12/10
     Ominous Seer 9/8→9/4  |  Tarecgosa 4/4→4/0 DEAD
     Lava Lurker 2/5→2/0 DEAD  |  Annoy-o-Tron 12/10→12/8
     Wrath Weaver 16/19→16/14  |  Mummifier 5/2→5/0 DEAD
     Result: survivors 7 vs 0 — winner: Overlord Saurfang
  Drek'Thar vs Sneed (first: Sneed)
     Drek'Thar: [3/6, 1/4, 4/3, 8/4, 8/2, 8/2, 2/5]
     Sneed: [4/1, 4/1, 1/2, 5/8, 2/2, 3/3, 1/4]
     Manasaber 4/1→4/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Metallic Hunter 8/4→8/0 DEAD
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/1
     Annoy-o-Tron 1/1→1/0 DEAD  |  Eternal Knight 8/2→8/1
     Eternal Knight 8/2→9/0 DEAD  |  Wrath Weaver 5/8→5/0 DEAD
     Picky Eater 2/2→2/0 DEAD  |  Wrath Weaver 3/5→3/3
     Eternal Knight 9/1→10/0 DEAD  |  Wrath Weaver 1/4→1/0 DEAD
     Scarlet Survivor 3/3→3/0 DEAD  |  Wrath Weaver 3/3→3/0 DEAD
     Result: survivors 2 vs 0 — winner: Drek'Thar
  Professor Putricide vs Sylvanas Windrunner (first: Professor Putricide)
     Professor Putricide: [4/1, 5/1, 4/1, 1/4, 5/1, 5/6, 6/3]
     Sylvanas Windrunner: [4/1, 3/2, 2/2, 3/4, 3/2, 3/3, 2/6]
     Manasaber 4/1→4/0 DEAD  |  Alert Alarmist 2/2→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 5/1→5/0 DEAD
     Harmless Bonehead 4/1→4/0 DEAD  |  Ancestral Automaton 3/4→3/0 DEAD
     Sewer Rat 3/2→3/0 DEAD  |  Risen Rider 5/1→5/0 DEAD
     Wrath Weaver 1/4→1/1  |  Sewer Rat 3/2→3/1
     Sewer Rat 3/1→3/0 DEAD  |  Cadaver Caretaker 6/3→6/0 DEAD
     Technical Element 5/6→5/3  |  Leeching Felhound 3/3→3/0 DEAD
     Dustbone Devastator 2/6→3/5  |  Wrath Weaver 1/1→1/0 DEAD
     Result: survivors 1 vs 1 — winner: Professor Putricide

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=5, Tier=4) | Overlord Saurfang (HP=30, Armor=8, Tier=4) | Professor Putricide (HP=27, Armor=0, Tier=4) | Drek'Thar (HP=26, Armor=0, Tier=4) | Ysera (HP=25, Armor=0, Tier=4) | Sylvanas Windrunner (HP=24, Armor=0, Tier=4) | Sneed (HP=23, Armor=0, Tier=4) | Inge, the Iron Hymn (HP=21, Armor=0, Tier=4)

### Turn 9

**Yogg-Saron, Hope's End**  HP=30 Armor=5 Gold=10 Tier=4

  Board: 3/6, 1/4, 8/2 [G], 4/1, 3/4, 4/2, 1/6 [Taunt]
  Tavern: Nerubian Deathswarmer 1/4 T2 $3 | Seafloor Recruiter 3/5 T4 $3 | Waverider 2/8 T4 $3 | Annoy-o-Tron 1/2 T1 $3 | Marquee Ticker 3/7 T4 $3 | Back to Back (spell) T4 $1

  → Board: 3/6, 8/2 [G], 4/1, 3/4, 4/2, 1/6 [Taunt], 2/8
  → Trinket: Wildfeather Duster
  → Actions (3): sell_board_1, buy_tavern_2, play_hand_3

**Sneed**  HP=23 Armor=0 Gold=10 Tier=4

  Board: 4/1, 4/1, 1/2 [Taunt,DS], 2/2, 3/3
  Tavern: Humming Bird 1/4 T2 $3 | Auto Assembler 2/2 T4 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Stomping Stegodon 4/4 T4 $3 | Alert Alarmist 2/2 T2 $3 | Conflagration (spell) T4 $2

  → Board: 4/1, 4/1, 2/2, 3/3, 6/12 [G], 2/2
  → HP: 23→20 | Trinket: Beetle Band
  → Actions (4): play_hand_0, play_hand_0, sell_board_2, buy_tavern_2

**Overlord Saurfang**  HP=30 Armor=8 Gold=10 Tier=4

  Board: 21/27 [G], 14/17, 9/8, 16/19, 12/13 [Taunt,DS], 18/20, 22/22
  Tavern: Deep-Sea Angler 21/22 T3 $3 | Enchanted Sentinel 22/24 T4 $3 | Technical Element 24/25 T3 $3 | Abyssal Bruiser 1/1 T4 $3 | Plaguerunner 24/21 T4 $3 | Spitescale Special (spell) T4 $2

  → Board: 21/27 [G], 14/17, 16/19, 12/13 [Taunt,DS], 18/20, 22/22, 24/25
  → Trinket: Mecha-Jaraxxus Sticker
  → Actions (3): sell_board_2, buy_tavern_2, play_hand_1

**Ysera**  HP=25 Armor=0 Gold=10 Tier=4

  Board: 6/6 [G], 3/3, 3/3, 2/5, 3/4, 4/4, 5/2
  Tavern: Friendly Geist 6/3 T4 $3 | Technical Element 5/6 T3 $3 | Deflect-o-Bot 3/2 T3 $3 | Mummifier 5/2 T3 $3 | Soul Rewinder 4/1 T2 $3 | Deepwater Clan (spell) T4 $2 | Persistent Poet 2/3 T4 $3

  → Board: 6/6 [G], 3/3, 2/5, 3/4, 4/4, 5/2, 4/6
  → Trinket: Chromatic Tear | Hand: 2→3
  → Actions (2): sell_board_1, play_hand_2

**Inge, the Iron Hymn**  HP=21 Armor=0 Gold=10 Tier=4

  Board: 4/1, 8/2, 4/3 [Reborn], 4/3, 2/2 [Taunt], 3/1
  Tavern: Flaming Enforcer 4/5 T4 $3 | Banana Slamma 3/6 T4 $3 | Zesty Shaker 6/7 T4 $3 | Sewer Rat 3/2 T2 $3 | Seafloor Recruiter 3/5 T4 $3 | Boon of Beetles (spell) T4 $1

  → Board: 4/1, 8/2, 4/3 [Reborn], 4/3, 3/1, 3/3, 6/7
  → Trinket: Fang Anklet
  → Actions (5): play_hand_1, sell_board_4, buy_tavern_2, play_hand_1, buy_tavern_4

**Professor Putricide**  HP=27 Armor=0 Gold=10 Tier=4

  Board: 4/1, 5/1 [Taunt,Reborn], 4/1, 1/4, 5/1 [Taunt,Reborn], 5/6, 6/3
  Tavern: Handless Forsaken 5/1 T3 $3 | Seafloor Recruiter 3/5 T4 $3 | Accord-o-Tron 3/3 T3 $3 | Imposing Percussionist 4/4 T4 $3 | Cadaver Caretaker 6/3 T3 $3 | Gem Confiscation (spell) T4 $1

  → Board: 5/1 [Taunt,Reborn], 4/1, 1/4, 5/1 [Taunt,Reborn], 5/6, 6/3, 6/3
  → Gold: 5→2 | Trinket: Jarred Frostling | Hand: 0→1
  → Actions (4): sell_board_0, buy_tavern_4, play_hand_0, buy_tavern_3

**Sylvanas Windrunner**  HP=24 Armor=0 Gold=10 Tier=4

  Board: 4/1, 3/2, 2/2 [Taunt], 3/4, 3/2, 3/3, 3/6
  Tavern: Hardy Orca 1/6 T3 $3 | Dustbone Devastator 3/6 T3 $3 | Ominous Seer 2/1 T1 $3 | Abyssal Bruiser 1/1 T4 $3 | Leeching Felhound 3/3 T3 $3 | Portal in a Fountain (spell) T3 $3

  → Board: 4/1, 3/2, 3/4, 3/2, 3/3, 3/6, 3/6
  → Gold: 1→0 | Trinket: Fang Anklet
  → Actions (5): sell_board_2, buy_tavern_1, play_hand_1, refresh, refresh

**Drek'Thar**  HP=26 Armor=0 Gold=10 Tier=4

  Board: 3/6, 1/4, 4/3, 8/4 [G], 10/2, 10/2, 2/5
  Tavern: Mummifier 5/2 T3 $3 | Auto Assembler 2/2 T4 $3 | Woodland Defiler 5/6 T4 $3 | Mummifier 5/2 T3 $3 | Seafloor Recruiter 3/5 T4 $3 | Easterly Winds (spell) T4 $1

  → Board: 5/8, 4/3, 8/4 [G], 10/2, 10/2, 2/5, 5/6
  → Gold: 3→0 | HP: 26→25 | Trinket: Thornspike Pauldron | Hand: 7→8
  → Actions (4): sell_board_1, buy_tavern_2, play_hand_7, buy_tavern_1

**Combat Phase**

  Drek'Thar vs Ysera (first: Drek'Thar)
     Drek'Thar: [5/8, 4/3, 8/4, 10/2, 10/2, 2/5, 5/6]
     Ysera: [6/6, 3/3, 2/5, 3/4, 4/4, 5/2, 4/6]
     Wrath Weaver 5/8→5/5  |  Scarlet Survivor 3/3→3/0 DEAD
     Scarlet Survivor 6/6→6/4  |  Lava Lurker 2/5→2/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Tarecgosa 4/4→4/0 DEAD
     Lava Lurker 2/5→2/0 DEAD  |  Eternal Knight 10/2→11/0 DEAD
     Metallic Hunter 8/4→8/0 DEAD  |  Mummifier 5/2→5/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Wrath Weaver 5/5→5/2
     Eternal Knight 11/2→12/0 DEAD  |  Scarlet Survivor 6/4→6/0 DEAD
     Black Chromadrake 4/6→4/1  |  Woodland Defiler 5/6→5/2
     Woodland Defiler 5/2→5/0 DEAD  |  Black Chromadrake 4/1→4/0 DEAD
     Result: survivors 1 vs 0 — winner: Drek'Thar
  Professor Putricide vs Overlord Saurfang (first: Overlord Saurfang)
     Professor Putricide: [5/1, 4/1, 1/4, 5/1, 5/6, 6/3, 6/3]
     Overlord Saurfang: [21/27, 14/17, 16/19, 12/13, 18/20, 22/22, 24/25]
     Wrath Weaver 21/27→21/22  |  Risen Rider 5/1→5/0 DEAD
     Harmless Bonehead 4/1→4/0 DEAD  |  Annoy-o-Tron 12/13→12/13
     Wrath Weaver 14/17→14/12  |  Risen Rider 5/1→5/0 DEAD
     Wrath Weaver 1/4→1/0 DEAD  |  Annoy-o-Tron 12/13→12/12
     Wrath Weaver 16/19→16/13  |  Cadaver Caretaker 6/3→6/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Annoy-o-Tron 12/12→12/7
     Annoy-o-Tron 12/7→12/1  |  Cadaver Caretaker 6/3→6/0 DEAD
     Result: survivors 0 vs 7 — winner: Overlord Saurfang
  Sylvanas Windrunner vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Sylvanas Windrunner: [5/2, 4/3, 3/4, 4/3, 3/3, 3/6, 3/6]
     Yogg-Saron, Hope's End: [3/6, 8/2, 4/1, 3/4, 4/2, 1/6, 2/8]
     Wrath Weaver 3/6→3/3  |  Dustbone Devastator 3/6→3/3
     Manasaber 5/2→5/1  |  Hardy Orca 1/6→1/1
     Manasaber 8/2→8/0 DEAD  |  Dustbone Devastator 3/3→3/0 DEAD
     Sewer Rat 4/3→4/2  |  Hardy Orca 1/1→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Manasaber 5/1→5/0 DEAD
     Ancestral Automaton 3/4→3/1  |  Wrath Weaver 3/3→3/0 DEAD
     Ancestral Automaton 3/4→3/1  |  Dustbone Devastator 3/6→3/3
     Sewer Rat 4/3→4/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Waverider 2/8→2/5  |  Dustbone Devastator 3/3→3/1
     Leeching Felhound 3/3→3/1  |  Waverider 2/5→2/2
     Result: survivors 4 vs 2 — winner: Sylvanas Windrunner
  Sneed vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Sneed: [4/1, 4/1, 2/2, 3/3, 6/12, 2/2]
     Inge, the Iron Hymn: [5/2, 8/2, 5/4, 4/3, 4/2, 3/3, 6/7]
     Manasaber 5/2→5/0 DEAD  |  Scarlet Survivor 3/3→3/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Eternal Knight 8/2→9/0 DEAD  |  Picky Eater 2/2→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Sewer Rat 5/4→5/0 DEAD
     Sprightly Scarab 4/2→4/0 DEAD  |  Tavern Spell Modifier (Test) 2/2→2/0 DEAD
     Wrath Weaver 6/12→6/6  |  Zesty Shaker 6/7→6/1
     Leeching Felhound 3/3→3/0 DEAD  |  Wrath Weaver 6/6→6/3
     Result: survivors 1 vs 1 — winner: Sneed

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=5, Tier=4) | Overlord Saurfang (HP=30, Armor=8, Tier=4) | Drek'Thar (HP=25, Armor=0, Tier=4) | Sylvanas Windrunner (HP=24, Armor=0, Tier=4) | Inge, the Iron Hymn (HP=21, Armor=0, Tier=4) | Sneed (HP=20, Armor=0, Tier=4) | Ysera (HP=20, Armor=0, Tier=4) | Professor Putricide (HP=12, Armor=0, Tier=4)

### Turn 10

**Yogg-Saron, Hope's End**  HP=30 Armor=5 Gold=10 Tier=4

  Board: 3/6, 8/2 [G], 4/1, 3/4, 4/2, 1/6 [Taunt], 2/8
  Tavern: Marquee Ticker 3/7 T4 $3 | Enchanted Sentinel 3/5 T4 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Lava Lurker 2/5 T2 $3 | Alert Alarmist 2/2 T2 $3 | Misplaced Tea Set (spell) T4 $2

  → Board: 3/6, 8/2 [G], 3/4, 4/2, 1/6 [Taunt], 2/8, 3/7
  → Upgrade T4→T5 | Gold: 1→0
  → Actions (5): upgrade, sell_board_2, buy_tavern_0, play_hand_5, refresh

**Sneed**  HP=20 Armor=0 Gold=10 Tier=4

  Board: 4/1, 4/1, 2/2, 3/3, 6/12 [G], 2/2
  Tavern: Floating Watcher 4/4 T3 $5 | Soul Rewinder 4/1 T2 $3 | Cadaver Caretaker 3/3 T3 $3 | Old Soul 3/4 T2 $3 | Friendly Geist 6/3 T4 $3 | Eonar's Favor (spell) T4 $2

  → Board: 4/1, 4/1, 3/3, 8/14 [G], 2/2, 5/4, 6/7
  → Upgrade T4→T5 | Gold: 1→0 | HP: 20→19 | Hand: 2→1
  → Actions (6): play_hand_0, upgrade, sell_board_2, play_hand_0, buy_tavern_4, refresh

**Overlord Saurfang**  HP=30 Armor=8 Gold=10 Tier=4

  Board: 21/27 [G], 14/17, 16/19, 12/13 [Taunt,DS], 18/20, 22/22, 24/25
  Tavern: Deep Blue Crooner 23/23 T3 $3 | Monstrous Macaw 26/25 T4 $3 | Holo Rover 25/25 T4 $3 | Hunting Tiger Shark 24/26 T4 $3 | Hunting Tiger Shark 24/26 T4 $3 | Natural Blessing (spell) T4 $4

  → Board: 21/27 [G], 14/17, 16/19, 18/20, 22/22, 24/25, 26/25
  → Upgrade T4→T5 | Gold: 1→0
  → Actions (5): upgrade, sell_board_3, buy_tavern_1, play_hand_1, refresh

**Ysera**  HP=20 Armor=0 Gold=10 Tier=4

  Board: 6/6 [G], 3/3, 2/5, 3/4, 4/4, 5/2, 4/6
  Tavern: Stomping Stegodon 4/4 T4 $3 | Deflect-o-Bot 3/2 T3 $3 | Eternal Knight 4/2 T2 $3 | Reef Riffer 3/2 T2 $3 | Accord-o-Tron 3/3 T3 $3 | Shifting Tide (spell) T4 $1 | Blazing Skyfin 2/4 T2 $3

  → Board: 7/7 [G], 2/5, 3/4, 5/5, 5/2, 5/7, 5/3
  → Upgrade T4→T5 | Hand: 4→5
  → Actions (5): upgrade, sell_board_1, play_hand_2, buy_tavern_0, buy_tavern_4

**Inge, the Iron Hymn**  HP=21 Armor=0 Gold=10 Tier=4

  Board: 4/1, 9/2, 4/3 [Reborn], 4/3, 3/1, 3/3, 6/7
  Tavern: Dustbone Devastator 2/6 T3 $3 | Scarlet Skull 2/1 T2 $3 | Alert Alarmist 2/2 T2 $3 | Mummifier 5/2 T3 $3 | Deep-Sea Angler 2/3 T3 $3 | Staff of Enrichment (spell) T3 $2

  → Board: 4/1, 9/2, 4/3 [Reborn], 4/3, 3/3, 6/7, 2/6
  → Upgrade T4→T5 | Gold: 1→0
  → Actions (5): upgrade, sell_board_4, buy_tavern_0, play_hand_2, refresh

**Professor Putricide**  HP=12 Armor=0 Gold=10 Tier=4

  Board: 5/1 [Taunt,Reborn], 4/1, 1/4, 5/1 [Taunt,Reborn], 5/6, 6/3, 6/3
  Tavern: False Implicator 1/1 T3 $3 | Risen Rider 5/1 T1 $3 | Rimescale Priestess 3/3 T4 $3 | Seafloor Recruiter 3/5 T4 $3 | Enchanted Sentinel 3/5 T4 $3 | Arcane Absorption (spell) T4 $1

  → Board: 5/1 [Taunt,Reborn], 3/6, 5/1 [Taunt,Reborn], 5/6, 6/3, 6/3, 4/4
  → Upgrade T4→T5 | Gold: 4→1 | HP: 12→6 | Hand: 1→2
  → Actions (4): upgrade, sell_board_1, play_hand_0, buy_tavern_4

**Sylvanas Windrunner**  HP=24 Armor=0 Gold=10 Tier=4

  Board: 4/1, 3/2, 3/4, 3/2, 3/3, 3/6, 3/6
  Tavern: Sewer Rat 3/2 T2 $3 | Mummifier 6/2 T3 $3 | Floating Watcher 4/4 T3 $5 | Floating Watcher 4/4 T3 $5 | Woodland Defiler 5/6 T4 $3

  → Board: 3/2, 3/4, 3/2, 3/3, 3/6, 3/6, 5/6
  → Upgrade T4→T5
  → Actions (4): upgrade, sell_board_0, buy_tavern_4, play_hand_1

**Drek'Thar**  HP=25 Armor=0 Gold=10 Tier=4

  Board: 5/8, 4/3, 8/4 [G], 12/2, 12/2, 2/5, 5/6
  Tavern: Shell Collector 4/3 T2 $3 | Banana Slamma 3/6 T4 $3 | Old Soul 3/4 T2 $3 | Wyvern Outrider 2/8 T4 $3 | Laboratory Assistant 3/4 T2 $3

  → Board: 5/8, 8/4 [G], 12/2, 12/2, 2/5, 5/6, 2/2
  → Upgrade T4→T5 | Gold: 1→0
  → Actions (5): upgrade, sell_board_1, play_hand_7, buy_tavern_0, refresh

**Combat Phase**

  Ysera vs Professor Putricide (first: Ysera)
     Ysera: [7/7, 2/5, 3/4, 5/5, 5/2, 5/7, 5/3]
     Professor Putricide: [5/1, 3/6, 5/1, 5/6, 6/3, 6/3, 4/4]
     Scarlet Survivor 7/7→7/2  |  Risen Rider 5/1→5/0 DEAD
     Wrath Weaver 3/6→3/1  |  Tarecgosa 5/5→5/2
     Lava Lurker 2/5→2/0 DEAD  |  Risen Rider 5/1→5/0 DEAD
     Technical Element 5/6→5/1  |  Tarecgosa 5/2→5/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Technical Element 5/1→5/0 DEAD
     Cadaver Caretaker 6/3→6/0 DEAD  |  Bronze Chromadrake 5/3→5/0 DEAD
     Mummifier 5/2→5/0 DEAD  |  Imposing Percussionist 4/4→4/0 DEAD
     Cadaver Caretaker 6/3→6/0 DEAD  |  Black Chromadrake 5/7→5/1
     Black Chromadrake 5/1→5/0 DEAD  |  Wrath Weaver 3/1→3/0 DEAD
     Result: survivors 1 vs 0 — winner: Ysera
  Drek'Thar vs Overlord Saurfang (first: Overlord Saurfang)
     Drek'Thar: [5/8, 8/4, 12/2, 12/2, 2/5, 5/6, 2/2]
     Overlord Saurfang: [21/27, 14/17, 16/19, 18/20, 22/22, 24/25, 26/25]
     Wrath Weaver 21/27→21/15  |  Eternal Knight 12/2→13/0 DEAD
     Wrath Weaver 5/8→5/0 DEAD  |  Nerubian Deathswarmer 18/20→18/15
     Wrath Weaver 14/17→14/15  |  Lava Lurker 2/5→2/0 DEAD
     Metallic Hunter 8/4→8/0 DEAD  |  Wrath Weaver 16/19→16/11
     Wrath Weaver 16/11→16/9  |  Auto Assembler 2/2→2/0 DEAD
     Eternal Knight 13/2→14/0 DEAD  |  Wrath Weaver 21/15→21/2
     Nerubian Deathswarmer 18/15→18/10  |  Woodland Defiler 5/6→5/0 DEAD
     Result: survivors 0 vs 7 — winner: Overlord Saurfang
  Sneed vs Sylvanas Windrunner (first: Sylvanas Windrunner)
     Sneed: [4/1, 4/1, 3/3, 8/14, 2/2, 5/4, 6/7]
     Sylvanas Windrunner: [4/3, 3/4, 4/3, 3/3, 3/6, 3/6, 5/6]
     Sewer Rat 4/3→4/0 DEAD  |  Wrath Weaver 8/14→8/10
     Manasaber 4/1→4/0 DEAD  |  Woodland Defiler 5/6→5/2
     Ancestral Automaton 3/4→3/2  |  Tavern Spell Modifier (Test) 2/2→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Leeching Felhound 3/3→3/0 DEAD
     Sewer Rat 4/3→4/0 DEAD  |  Zesty Shaker 6/7→6/3
     Scarlet Survivor 3/3→3/0 DEAD  |  Ancestral Automaton 3/2→3/0 DEAD
     Dustbone Devastator 3/6→4/1  |  Malchezaar, Prince of Dance 5/4→5/1
     Wrath Weaver 8/10→8/6  |  Dustbone Devastator 4/1→4/0 DEAD
     Dustbone Devastator 4/6→5/1  |  Malchezaar, Prince of Dance 5/1→5/0 DEAD
     Zesty Shaker 6/3→6/0 DEAD  |  Woodland Defiler 5/2→5/0 DEAD
     Result: survivors 1 vs 1 — winner: Sneed
  Yogg-Saron, Hope's End vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Yogg-Saron, Hope's End: [3/6, 8/2, 3/4, 4/2, 1/6, 2/8, 3/7]
     Inge, the Iron Hymn: [5/2, 9/2, 5/4, 4/3, 3/3, 6/7, 2/6]
     Manasaber 5/2→5/1  |  Hardy Orca 1/6→1/1
     Wrath Weaver 3/6→3/4  |  Dustbone Devastator 2/6→2/3
     Eternal Knight 9/2→9/1  |  Hardy Orca 1/1→1/0 DEAD
     Manasaber 8/2→8/0 DEAD  |  Dustbone Devastator 2/3→2/0 DEAD
     Sewer Rat 5/4→5/1  |  Marquee Ticker 3/7→3/2
     Ancestral Automaton 3/4→3/0 DEAD  |  Manasaber 5/1→5/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Marquee Ticker 3/2→3/0 DEAD
     Metallic Hunter 4/2→4/0 DEAD  |  Zesty Shaker 6/7→6/3
     Leeching Felhound 3/3→3/0 DEAD  |  Wrath Weaver 3/4→3/1
     Waverider 2/8→2/0 DEAD  |  Eternal Knight 9/1→10/0 DEAD
     Zesty Shaker 6/3→6/0 DEAD  |  Wrath Weaver 3/1→3/0 DEAD
     Result: survivors 0 vs 1 — winner: Inge, the Iron Hymn

  **Professor Putricide eliminated!** (HP=0, Turn 10)
  Alive: 7/8
  HP: Overlord Saurfang (HP=30, Armor=8, Tier=5) | Yogg-Saron, Hope's End (HP=28, Armor=0, Tier=5) | Sylvanas Windrunner (HP=24, Armor=0, Tier=5) | Inge, the Iron Hymn (HP=21, Armor=0, Tier=5) | Ysera (HP=20, Armor=0, Tier=5) | Sneed (HP=19, Armor=0, Tier=5) | Drek'Thar (HP=10, Armor=0, Tier=5)

### Turn 11

**Yogg-Saron, Hope's End**  HP=28 Armor=0 Gold=10 Tier=5

  Board: 3/6, 8/2 [G], 3/4, 4/2, 1/6 [Taunt], 2/8, 3/7
  Tavern: Divine Sparkbot 4/2 T5 $3 | Enchanted Sentinel 3/5 T4 $3 | Lava Lurker 2/5 T2 $3 | Deep Blue Crooner 2/2 T3 $3 | Annoy-o-Module 2/4 T3 $3 | Brood of Nozdormu (spell) T5 $2

  → Board: 3/6, 8/2 [G], 3/4, 1/6 [Taunt], 2/8, 3/7, 3/5
  → Actions (3): sell_board_3, buy_tavern_1, play_hand_7

**Sneed**  HP=19 Armor=0 Gold=10 Tier=5

  Board: 4/1, 4/1, 3/3, 8/14 [G], 2/2, 5/4, 6/7
  Tavern: Laboratory Assistant 3/4 T2 $3 | Waverider 2/8 T4 $3 | Enchanted Sentinel 3/5 T4 $3 | Famished Felbat 6/3 T5 $3 | Tide Raiser 2/1 T2 $3 | Butchering (spell) T5 $2

  → Board: 4/1, 4/1, 3/3, 8/14 [G], 5/4, 6/7, 6/3
  → Upgrade T5→T6 | Gold: 11→2 | Hand: 2→1
  → Actions (3): sell_board_4, play_hand_0, upgrade

**Overlord Saurfang**  HP=30 Armor=8 Gold=10 Tier=5

  Board: 21/27 [G], 14/17, 16/19, 18/20, 22/22, 24/25, 26/25
  Tavern: Wintergrasp Ghoul 29/26 T5 $3 | Shadowdancer 28/26 T5 $3 | Technical Element 28/29 T3 $3 | Deep-Sea Angler 25/26 T3 $3 | Imposing Percussionist 27/27 T4 $3 | Channel the Devourer (spell) T5 $4

  → Board: 21/27 [G], 16/19, 18/20, 22/22, 24/25, 26/25, 28/29
  → Actions (3): sell_board_1, buy_tavern_2, play_hand_1

**Ysera**  HP=20 Armor=0 Gold=10 Tier=5

  Board: 7/7 [G], 2/5, 3/4, 6/6, 5/2, 5/7, 5/3
  Tavern: Risen Rider 2/1 T1 $3 | Catacomb Crasher 4/10 T5 $3 | Hunting Tiger Shark 3/5 T4 $3 | Reef Riffer 3/2 T2 $3 | Cadaver Caretaker 3/3 T3 $3 | Armor Stash (spell) T5 $3 | Incubation Researcher 2/8 T4 $3

  → Board: 7/7 [G], 3/4, 6/6, 5/2, 5/7, 5/3, 4/4
  → Gold: 11→8
  → Actions (3): sell_board_1, play_hand_3, buy_tavern_6

**Inge, the Iron Hymn**  HP=21 Armor=0 Gold=10 Tier=5

  Board: 4/1, 10/2, 4/3 [Reborn], 4/3, 3/3, 6/7, 2/6
  Tavern: Old Soul 3/4 T2 $3 | Skeletal Strafer 6/6 T5 $3 | False Implicator 1/1 T3 $3 | Scrap Scraper 6/5 T5 $3 | Zesty Shaker 6/7 T4 $3 | Bargain Bundle (spell) T5 $5

  → Board: 10/2, 4/3 [Reborn], 4/3, 3/3, 6/7, 2/6, 6/7
  → Gold: 5→0 | Hand: 2→4
  → Actions (5): sell_board_0, buy_tavern_4, play_hand_2, buy_tavern_0, buy_tavern_3

**Sylvanas Windrunner**  HP=24 Armor=0 Gold=10 Tier=5

  Board: 3/2, 3/4, 3/2, 3/3, 5/6, 5/6, 5/6
  Tavern: Deflect-o-Bot 3/2 T3 $3 | Seafloor Recruiter 3/5 T4 $3 | Sinrunner Blanchy 11/8 T5 $3 | Famished Felbat 6/3 T5 $3 | Hardy Orca 1/6 T3 $3 | Contracted Corpse (spell) T5 $3

  → Board: 3/4, 3/2, 3/3, 5/6, 5/6, 5/6, 11/8 [Reborn]
  → Actions (3): sell_board_0, buy_tavern_2, play_hand_1

**Drek'Thar**  HP=10 Armor=0 Gold=10 Tier=5

  Board: 5/8, 8/4 [G], 14/2, 14/2, 2/5, 5/6, 2/2
  Tavern: False Implicator 1/1 T3 $3 | Stomping Stegodon 4/4 T4 $3 | Accord-o-Tron 3/3 T3 $3 | Divine Sparkbot 4/2 T5 $3 | Charging Czarina 4/1 T5 $3 | Upper Hand (spell) T5 $3

  → Board: 5/8, 8/4 [G], 14/2, 14/2, 2/5, 5/6, 4/3
  → Actions (2): sell_board_6, play_hand_8

**Combat Phase**

  Ysera vs Sylvanas Windrunner (first: Sylvanas Windrunner)
     Ysera: [7/7, 3/4, 6/6, 5/2, 5/7, 5/3, 4/4]
     Sylvanas Windrunner: [3/4, 4/3, 3/3, 5/6, 5/6, 5/6, 11/8]
     Ancestral Automaton 3/4→3/0 DEAD  |  Stomping Stegodon 4/4→4/1
     Scarlet Survivor 7/7→7/4  |  Leeching Felhound 3/3→3/0 DEAD
     Sewer Rat 4/3→4/0 DEAD  |  Mummifier 5/2→5/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Sinrunner Blanchy 11/8→11/5
     Dustbone Devastator 5/6→6/1  |  Black Chromadrake 5/7→5/2
     Tarecgosa 6/6→6/1  |  Woodland Defiler 5/6→5/0 DEAD
     Dustbone Devastator 6/6→7/2  |  Stomping Stegodon 4/1→4/0 DEAD
     Black Chromadrake 5/2→5/0 DEAD  |  Sinrunner Blanchy 13/5→13/0 DEAD
     Result: survivors 3 vs 2 — winner: Ysera
  Sneed vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Sneed: [4/1, 4/1, 3/3, 8/14, 5/4, 6/7, 6/3]
     Yogg-Saron, Hope's End: [3/6, 8/2, 3/4, 1/6, 2/8, 3/7, 3/5]
     Wrath Weaver 3/6→3/0 DEAD  |  Wrath Weaver 8/14→8/11
     Manasaber 4/1→4/0 DEAD  |  Hardy Orca 1/6→1/2
     Manasaber 8/2→8/0 DEAD  |  Scarlet Survivor 3/3→3/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Hardy Orca 1/2→1/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Friendly Geist 6/3→6/0 DEAD
     Wrath Weaver 8/11→8/9  |  Waverider 2/8→2/0 DEAD
     Marquee Ticker 3/7→3/2  |  Malchezaar, Prince of Dance 5/4→5/1
     Malchezaar, Prince of Dance 5/1→5/0 DEAD  |  Marquee Ticker 3/2→3/0 DEAD
     Enchanted Sentinel 3/5→3/0 DEAD  |  Zesty Shaker 6/7→6/4
     Result: survivors 2 vs 0 — winner: Sneed
  Drek'Thar vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Drek'Thar: [5/8, 8/4, 14/2, 14/2, 2/5, 5/6, 4/3]
     Inge, the Iron Hymn: [10/2, 5/4, 4/3, 3/3, 6/7, 2/6, 6/7]
     Eternal Knight 10/2→11/0 DEAD  |  Woodland Defiler 5/6→5/0 DEAD
     Wrath Weaver 5/8→5/2  |  Zesty Shaker 6/7→6/2
     Sewer Rat 5/4→5/0 DEAD  |  Eternal Knight 14/2→15/0 DEAD
     Metallic Hunter 8/4→8/1  |  Leeching Felhound 3/3→3/0 DEAD
     Shell Collector 4/3→4/1  |  Lava Lurker 2/5→2/1
     Eternal Knight 15/2→16/0 DEAD  |  Shell Collector 4/1→4/0 DEAD
     Zesty Shaker 6/2→6/0 DEAD  |  Metallic Hunter 8/1→8/0 DEAD
     Lava Lurker 2/1→2/0 DEAD  |  Zesty Shaker 6/7→6/5
     Dustbone Devastator 2/6→3/1  |  Wrath Weaver 5/2→5/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Zesty Shaker 6/5→6/1
     Result: survivors 0 vs 2 — winner: Inge, the Iron Hymn

  **Drek'Thar eliminated!** (HP=0, Turn 11)
  Alive: 6/8
  HP: Overlord Saurfang (HP=30, Armor=8, Tier=5) | Sylvanas Windrunner (HP=24, Armor=0, Tier=5) | Inge, the Iron Hymn (HP=21, Armor=0, Tier=5) | Ysera (HP=20, Armor=0, Tier=5) | Sneed (HP=19, Armor=0, Tier=6) | Yogg-Saron, Hope's End (HP=17, Armor=0, Tier=5)

### Turn 12

**Yogg-Saron, Hope's End**  HP=17 Armor=0 Gold=10 Tier=5

  Board: 3/6, 8/2 [G], 3/4, 1/6 [Taunt], 2/8, 3/7, 3/5
  Tavern: Famished Felbat 6/3 T5 $3 | Floating Watcher 4/4 T3 $5 | Trigore the Lasher 9/3 T4 $3 | Maelstrom Emergent 2/7 T5 $3 | Hunting Tiger Shark 3/5 T4 $3 | Queen's Command (spell) T5 $2

  → Board: 3/6, 8/2 [G], 3/4, 1/6 [Taunt], 2/8, 3/7, 3/5
  → Upgrade T5→T6 | Gold: 2→0 | Hand: 8→9
  → Actions (2): upgrade, buy_tavern_5

**Sneed**  HP=19 Armor=0 Gold=10 Tier=6

  Board: 4/1, 4/1, 3/3, 8/14 [G], 5/4, 6/7, 6/3
  Tavern: Trigore the Lasher 9/3 T4 $3 | One-Amalgam Tour Group 6/7 T6 $3 | Spiked Savior 8/2 T5 $3 | Rimescale Priestess 3/3 T4 $3 | Rylak Metalhead 5/3 T4 $3 | Void Pup Trainer 7/7 T5 $3 | Lost Staff of Hamuul (spell) T6 $2

  → Board: 4/1, 3/3, 8/14 [G], 5/4, 6/7, 6/3, 2/6
  → Gold: 5→2 | Hand: 1→3
  → Actions (5): sell_board_0, play_hand_0, buy_tavern_4, buy_tavern_3, buy_tavern_2

**Overlord Saurfang**  HP=30 Armor=8 Gold=10 Tier=5

  Board: 21/27 [G], 16/19, 18/20, 22/22, 24/25, 26/25, 28/29
  Tavern: Darkcrest Strategist 29/30 T5 $3 | Sewer Rat 28/27 T2 $3 | Void Pup Trainer 32/32 T5 $3 | Nerubian Deathswarmer 27/29 T2 $3 | Technical Element 30/31 T3 $3 | Wave of Gold (spell) T5 $2

  → Board: 21/27 [G], 16/19, 18/20, 22/22, 24/25, 26/25, 28/29
  → Upgrade T5→T6 | Gold: 1→0 | Hand: 1→2
  → Actions (3): upgrade, buy_tavern_5, refresh

**Ysera**  HP=20 Armor=0 Gold=10 Tier=5

  Board: 7/7 [G], 3/4, 8/8, 5/2, 5/7, 5/3, 4/4
  Tavern: Zesty Shaker 6/7 T4 $3 | Cadaver Caretaker 3/3 T3 $3 | Reef Riffer 3/2 T2 $3 | Abyssal Bruiser 1/1 T4 $3 | Humming Bird 1/4 T2 $3 | Golden Touch (spell) T5 $5 | Persistent Poet 2/3 T4 $3

  → Board: 7/7 [G], 3/4, 8/8, 5/2, 5/7, 5/3, 4/4
  → Upgrade T5→T6 | Gold: 10→2
  → Actions (1): upgrade

**Inge, the Iron Hymn**  HP=21 Armor=0 Gold=10 Tier=5

  Board: 11/2, 4/3 [Reborn], 4/3, 3/3, 6/7, 3/6, 6/7
  Tavern: Handless Forsaken 3/1 T3 $3 | Imposing Percussionist 4/4 T4 $3 | Picky Eater 1/1 T1 $3 | Lava Lurker 2/5 T2 $3 | Trigore the Lasher 9/3 T4 $3 | Portal in a Crystal (spell) T5 $2

  → Board: 11/2, 4/3 [Reborn], 4/3, 3/3, 6/7, 3/6, 6/7
  → Upgrade T5→T6 | Gold: 2→0 | Hand: 4→5
  → Actions (2): upgrade, buy_tavern_5

**Sylvanas Windrunner**  HP=24 Armor=0 Gold=10 Tier=5

  Board: 3/4, 3/2, 3/3, 7/6, 7/6, 5/6, 13/8 [Reborn]
  Tavern: Imposing Percussionist 4/4 T4 $3 | Rimescale Priestess 3/3 T4 $3 | Flaming Enforcer 4/5 T4 $3 | Prosthetic Hand 3/1 T4 $3 | False Implicator 1/1 T3 $3

  → Board: 3/4, 3/2, 3/3, 7/6, 7/6, 5/6, 13/8 [Reborn]
  → Upgrade T5→T6 | Gold: 1→0
  → Actions (3): upgrade, refresh, refresh

**Combat Phase**

  Sylvanas Windrunner vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Sylvanas Windrunner: [3/4, 4/3, 3/3, 7/6, 7/6, 5/6, 13/8]
     Yogg-Saron, Hope's End: [3/6, 8/2, 3/4, 1/6, 2/8, 3/7, 3/5]
     Wrath Weaver 3/6→3/0 DEAD  |  Dustbone Devastator 7/6→7/3
     Ancestral Automaton 3/4→3/3  |  Hardy Orca 1/6→1/3
     Manasaber 8/2→8/0 DEAD  |  Woodland Defiler 5/6→5/0 DEAD
     Sewer Rat 4/3→4/2  |  Hardy Orca 1/3→1/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Sinrunner Blanchy 13/8→13/5
     Leeching Felhound 3/3→3/0 DEAD  |  Marquee Ticker 3/7→3/4
     Waverider 2/8→2/1  |  Dustbone Devastator 7/3→7/1
     Dustbone Devastator 7/6→8/3  |  Marquee Ticker 3/4→3/0 DEAD
     Enchanted Sentinel 3/5→3/1  |  Sewer Rat 4/2→4/0 DEAD
     Dustbone Devastator 8/1→9/0 DEAD  |  Enchanted Sentinel 3/1→3/0 DEAD
     Result: survivors 3 vs 1 — winner: Sylvanas Windrunner
  Ysera vs Sneed (first: Sneed)
     Ysera: [7/7, 3/4, 8/8, 5/2, 5/7, 5/3, 4/4]
     Sneed: [4/1, 3/3, 8/14, 5/4, 6/7, 6/3, 2/6]
     Manasaber 4/1→4/0 DEAD  |  Scarlet Survivor 7/7→7/3
     Scarlet Survivor 7/3→7/0 DEAD  |  Wrath Weaver 8/14→8/7
     Scarlet Survivor 3/3→3/0 DEAD  |  Black Chromadrake 5/7→5/4
     Laboratory Assistant 3/4→3/2  |  Dustbone Devastator 2/6→2/3
     Wrath Weaver 8/7→8/2  |  Mummifier 5/2→5/0 DEAD
     Tarecgosa 8/8→8/6  |  Dustbone Devastator 2/3→2/0 DEAD
     Malchezaar, Prince of Dance 5/4→5/0 DEAD  |  Black Chromadrake 5/4→5/0 DEAD
     Bronze Chromadrake 5/3→5/0 DEAD  |  Friendly Geist 6/3→6/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Tarecgosa 8/6→8/0 DEAD
     Stomping Stegodon 4/4→4/0 DEAD  |  Wrath Weaver 8/2→8/0 DEAD
     Result: survivors 1 vs 0 — winner: Ysera
  Inge, the Iron Hymn vs Overlord Saurfang (first: Overlord Saurfang)
     Inge, the Iron Hymn: [11/2, 5/4, 4/3, 3/3, 6/7, 3/6, 6/7]
     Overlord Saurfang: [21/27, 16/19, 18/20, 22/22, 24/25, 26/25, 28/29]
     Wrath Weaver 21/27→21/23  |  Shell Collector 4/3→4/0 DEAD
     Eternal Knight 11/2→12/0 DEAD  |  Wrath Weaver 21/23→21/12
     Wrath Weaver 16/19→16/13  |  Zesty Shaker 6/7→6/0 DEAD
     Sewer Rat 5/4→5/0 DEAD  |  Technical Element 28/29→28/24
     Nerubian Deathswarmer 18/20→18/17  |  Dustbone Devastator 3/6→3/0 DEAD
     Leeching Felhound 3/3→3/0 DEAD  |  Technical Element 28/24→28/21
     Old Soul 22/22→22/16  |  Zesty Shaker 6/7→6/0 DEAD
     Result: survivors 0 vs 7 — winner: Overlord Saurfang

  Alive: 6/8
  HP: Overlord Saurfang (HP=30, Armor=8, Tier=6) | Sylvanas Windrunner (HP=24, Armor=0, Tier=6) | Ysera (HP=20, Armor=0, Tier=6) | Yogg-Saron, Hope's End (HP=17, Armor=0, Tier=6) | Sneed (HP=11, Armor=0, Tier=6) | Inge, the Iron Hymn (HP=6, Armor=0, Tier=6)

### Turn 13

**Yogg-Saron, Hope's End**  HP=17 Armor=0 Gold=10 Tier=6

  Board: 3/6, 8/2 [G], 3/4, 1/6 [Taunt], 2/8, 3/7, 3/5
  Tavern: Imposing Percussionist 4/4 T4 $3 | Dustbone Devastator 2/6 T3 $3 | Lurking Leviathan 3/8 T5 $3 | Rimescale Priestess 3/3 T4 $3 | Technical Element 5/6 T3 $3 | Groundbreaker 5/4 T6 $3 | Knockoff Wisdomball (spell) T6 $4

  → Board: 3/6, 8/2 [G], 1/6 [Taunt], 2/8, 3/7, 3/5
  → Actions (2): sell_board_2, buy_tavern_2

**Sneed**  HP=11 Armor=0 Gold=10 Tier=6

  Board: 4/1, 3/3, 8/14 [G], 5/4, 6/7, 6/3, 2/6
  Tavern: Eternal Summoner 8/1 T6 $3 | Floating Watcher 4/4 T3 $5 | Forsaken Weaver 3/10 T6 $3 | Goldrinn, the Great Wolf 8/8 T6 $3 | P-0UL-TR-0N 10/10 T6 $3 | Forsaken Weaver 3/10 T6 $3

  → Board: 3/3, 8/14 [G], 5/4, 6/7, 6/3, 2/6, 5/3 [Taunt]
  → Gold: 3→0 | Hand: 4→6
  → Actions (5): sell_board_0, play_hand_0, buy_tavern_1, buy_tavern_1, buy_tavern_3

**Overlord Saurfang**  HP=30 Armor=8 Gold=10 Tier=6

  Board: 21/27 [G], 16/19, 18/20, 22/22, 24/25, 26/25, 28/29
  Tavern: Ancestral Automaton 3/4 T2 $3 | Groundbreaker 31/30 T6 $3 | Humming Bird 27/30 T2 $3 | One-Amalgam Tour Group 33/33 T6 $3 | Deathly Striker 35/34 T6 $3 | Shell Collector 30/29 T2 $3

  → Board: 21/27 [G], 18/20, 22/22, 24/25, 26/25, 28/29, 35/34
  → Actions (3): sell_board_1, buy_tavern_4, play_hand_2

**Ysera**  HP=20 Armor=0 Gold=10 Tier=6

  Board: 7/7 [G], 3/4, 12/12, 5/2, 5/7, 5/3, 4/4
  Tavern: Trigore the Lasher 9/3 T4 $3 | Glowscale 4/6 T5 $3 | Manasaber 4/1 T1 $3 | Void Pup Trainer 7/7 T5 $3 | Hunting Tiger Shark 3/5 T4 $3 | Ancestral Automaton 3/4 T2 $3 | Scarlet Survivor 3/3 T1 $3

  → Board: 7/7 [G], 12/12, 5/2, 5/7, 5/3, 4/4, 6/4
  → Hand: 9→10
  → Actions (5): sell_board_1, play_hand_4, buy_tavern_5, buy_tavern_4, buy_tavern_1

**Inge, the Iron Hymn**  HP=6 Armor=0 Gold=10 Tier=6

  Board: 12/2, 4/3 [Reborn], 4/3, 3/3, 6/7, 3/6, 6/7
  Tavern: Banana Slamma 3/6 T4 $3 | Auto Assembler 2/2 T4 $3 | Monstrous Macaw 5/4 T4 $3 | Sly Raptor 1/3 T3 $3 | Sprightly Scarab 3/1 T3 $3 | Ancestral Automaton 3/4 T2 $3

  → Board: 12/2, 4/3 [Reborn], 4/3, 6/7, 3/6, 6/7, 4/4
  → Hand: 5→4
  → Actions (3): sell_board_3, play_hand_2, upgrade

**Sylvanas Windrunner**  HP=24 Armor=0 Gold=10 Tier=6

  Board: 3/4, 3/2, 3/3, 9/6, 9/6, 5/6, 15/8 [Reborn]
  Tavern: Divine Sparkbot 4/2 T5 $3 | Plaguerunner 11/2 T4 $3 | Ashen Corruptor 6/6 T5 $3 | Nightmare Par-tea Guest 10/3 T5 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Leeching Felhound 3/3 T3 $3

  → Board: 3/4, 3/3, 9/6, 9/6, 5/6, 15/8 [Reborn], 11/2
  → Actions (3): sell_board_1, buy_tavern_1, play_hand_1

**Combat Phase**

  Sneed vs Overlord Saurfang (first: Overlord Saurfang)
     Sneed: [3/3, 8/14, 5/4, 6/7, 6/3, 2/6, 5/3]
     Overlord Saurfang: [21/27, 18/20, 22/22, 24/25, 26/25, 28/29, 35/34]
     Wrath Weaver 21/27→21/22  |  Rylak Metalhead 5/3→5/0 DEAD
     Scarlet Survivor 3/3→3/0 DEAD  |  Wrath Weaver 21/22→21/19
     Nerubian Deathswarmer 18/20→18/14  |  Friendly Geist 6/3→6/0 DEAD
     Wrath Weaver 8/14→8/0 DEAD  |  Wrath Weaver 21/19→21/11
     Old Soul 22/22→22/16  |  Zesty Shaker 6/7→6/0 DEAD
     Malchezaar, Prince of Dance 5/4→5/0 DEAD  |  Monstrous Macaw 26/25→26/20
     Technical Element 24/25→24/23  |  Dustbone Devastator 2/6→2/0 DEAD
     Result: survivors 0 vs 7 — winner: Overlord Saurfang
  Inge, the Iron Hymn vs Sylvanas Windrunner (first: Sylvanas Windrunner)
     Inge, the Iron Hymn: [12/2, 5/4, 4/3, 6/7, 3/6, 6/7, 4/4]
     Sylvanas Windrunner: [3/4, 3/3, 9/6, 9/6, 5/6, 15/8, 11/2]
     Ancestral Automaton 3/4→3/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Eternal Knight 12/2→13/0 DEAD  |  Plaguerunner 11/2→14/0 DEAD
     Leeching Felhound 3/3→3/0 DEAD  |  Dustbone Devastator 3/6→3/3
     Sewer Rat 5/4→5/0 DEAD  |  Sinrunner Blanchy 18/8→18/3
     Dustbone Devastator 12/6→13/0 DEAD  |  Zesty Shaker 6/7→6/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Dustbone Devastator 13/6→13/0 DEAD
     Woodland Defiler 5/6→5/3  |  Dustbone Devastator 3/3→3/0 DEAD
     Old Soul 4/4→4/0 DEAD  |  Sinrunner Blanchy 19/3→19/0 DEAD
     Result: survivors 0 vs 1 — winner: Sylvanas Windrunner
  Ysera vs Yogg-Saron, Hope's End (first: Ysera)
     Ysera: [7/7, 12/12, 5/2, 5/7, 5/3, 4/4, 6/4]
     Yogg-Saron, Hope's End: [3/6, 8/2, 1/6, 2/8, 3/7, 3/5]
     Scarlet Survivor 7/7→7/6  |  Hardy Orca 1/6→1/0 DEAD
     Wrath Weaver 3/6→3/1  |  Bronze Chromadrake 5/3→5/0 DEAD
     Tarecgosa 12/12→12/9  |  Enchanted Sentinel 3/5→3/0 DEAD
     Manasaber 8/2→8/0 DEAD  |  Mummifier 5/2→5/0 DEAD
     Black Chromadrake 5/7→5/4  |  Marquee Ticker 3/7→3/2
     Waverider 2/8→2/0 DEAD  |  Tarecgosa 12/9→12/7
     Stomping Stegodon 4/4→4/1  |  Wrath Weaver 3/1→3/0 DEAD
     Marquee Ticker 3/2→3/0 DEAD  |  Stomping Stegodon 4/1→4/0 DEAD
     Result: survivors 4 vs 0 — winner: Ysera

  **Sneed eliminated!** (HP=0, Turn 13)
  **Inge, the Iron Hymn eliminated!** (HP=0, Turn 13)
  Alive: 4/8
  HP: Overlord Saurfang (HP=30, Armor=8, Tier=6) | Sylvanas Windrunner (HP=24, Armor=0, Tier=6) | Ysera (HP=20, Armor=0, Tier=6) | Yogg-Saron, Hope's End (HP=2, Armor=0, Tier=6)

### Turn 14

**Yogg-Saron, Hope's End**  HP=2 Armor=0 Gold=10 Tier=6

  Board: 3/6, 8/2 [G], 1/6 [Taunt], 2/8, 3/7, 3/5
  Tavern: Trigore the Lasher 9/3 T4 $3 | Rabid Panther 4/8 T6 $3 | Prosthetic Hand 3/1 T4 $3 | Tide Raiser 2/1 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Lava Lurker 2/5 T2 $3

  → Board: 3/6, 8/2 [G], 1/6 [Taunt], 2/8, 3/7, 3/5
  → Actions (1): buy_tavern_0

**Overlord Saurfang**  HP=30 Armor=8 Gold=10 Tier=6

  Board: 21/27 [G], 18/20, 22/22, 24/25, 26/25, 28/29, 35/34
  Tavern: Sewer Rat 30/29 T2 $3 | Holo Rover 31/31 T4 $3 | Darkcrest Strategist 31/32 T5 $3 | Tide Raiser 29/28 T2 $3 | Humming Bird 28/31 T2 $3 | Annoy-o-Module 29/31 T3 $3

  → Board: 21/27 [G], 22/22, 24/25, 26/25, 28/29, 35/34, 31/32
  → Actions (3): sell_board_1, buy_tavern_2, play_hand_2

**Ysera**  HP=20 Armor=0 Gold=10 Tier=6

  Board: 7/7 [G], 20/20, 5/2, 5/7, 5/3, 4/4, 6/4
  Tavern: Eternal Tycoon 4/8 T5 $3 | Laboratory Assistant 3/4 T2 $3 | Abyssal Bruiser 1/1 T4 $3 | Bazaar Dealer 4/6 T5 $3 | Woodland Defiler 5/6 T4 $3 | Twisted Wrathguard 8/8 T6 $3 | Fire-forged Evoker 8/5 T6 $3

  → Board: 8/8 [G], 21/21, 6/8, 4/4, 7/5, 2/8, 3/4
  → Actions (7): sell_board_2, play_hand_4, play_hand_5, play_hand_6, buy_tavern_2, buy_tavern_1, buy_tavern_2

**Sylvanas Windrunner**  HP=24 Armor=0 Gold=10 Tier=6

  Board: 3/4, 3/3, 13/6, 13/6, 5/6, 19/8 [Reborn], 15/2
  Tavern: Wintergrasp Ghoul 16/3 T5 $3 | Glowscale 4/6 T5 $3 | Eternal Summoner 19/1 T6 $3 | Handless Forsaken 13/1 T3 $3 | Glowscale 4/6 T5 $3 | Ruthless Queensguard 3/3 T6 $3

  → Board: 3/4, 13/6, 13/6, 5/6, 19/8 [Reborn], 15/2, 19/1 [Reborn]
  → Gold: 5→2 | Hand: 1→3
  → Actions (5): sell_board_1, buy_tavern_2, play_hand_1, buy_tavern_0, buy_tavern_1

**Combat Phase**

  Sylvanas Windrunner vs Overlord Saurfang (first: Overlord Saurfang)
     Sylvanas Windrunner: [3/4, 13/6, 13/6, 5/6, 19/8, 15/2, 19/1]
     Overlord Saurfang: [21/27, 22/22, 24/25, 26/25, 28/29, 35/34, 31/32]
     Wrath Weaver 21/27→21/14  |  Dustbone Devastator 13/6→13/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Darkcrest Strategist 31/32→31/29
     Old Soul 22/22→22/3  |  Sinrunner Blanchy 19/8→19/0 DEAD
     Dustbone Devastator 13/6→14/0 DEAD  |  Wrath Weaver 21/14→21/1
     Technical Element 24/25→24/5  |  Eternal Summoner 20/1→20/0 DEAD
     Woodland Defiler 5/6→5/0 DEAD  |  Technical Element 24/5→24/0 DEAD
     Monstrous Macaw 26/25→26/9  |  Plaguerunner 16/2→20/0 DEAD
     Result: survivors 0 vs 6 — winner: Overlord Saurfang
  Yogg-Saron, Hope's End vs Ysera (first: Ysera)
     Yogg-Saron, Hope's End: [3/6, 8/2, 1/6, 2/8, 3/7, 3/5]
     Ysera: [8/8, 21/21, 6/8, 4/4, 7/5, 2/8, 3/4]
     Scarlet Survivor 8/8→8/7  |  Hardy Orca 1/6→1/0 DEAD
     Wrath Weaver 3/6→3/2  |  Stomping Stegodon 4/4→4/1
     Tarecgosa 21/21→21/19  |  Waverider 2/8→2/0 DEAD
     Manasaber 8/2→8/0 DEAD  |  Tarecgosa 21/19→21/11
     Black Chromadrake 6/8→6/5  |  Wrath Weaver 3/2→3/0 DEAD
     Marquee Ticker 3/7→3/4  |  Ancestral Automaton 3/4→3/1
     Stomping Stegodon 4/1→4/0 DEAD  |  Enchanted Sentinel 3/5→3/1
     Enchanted Sentinel 3/1→3/0 DEAD  |  Scarlet Survivor 8/7→8/4
     Red Chromadrake 7/5→7/2  |  Marquee Ticker 3/4→3/0 DEAD
     Result: survivors 0 vs 6 — winner: Ysera

  **Yogg-Saron, Hope's End eliminated!** (HP=0, Turn 14)
  **Sylvanas Windrunner eliminated!** (HP=0, Turn 14)
  Alive: 2/8
  HP: Overlord Saurfang (HP=30, Armor=8, Tier=6) | Ysera (HP=20, Armor=0, Tier=6)

### Turn 15

**Overlord Saurfang**  HP=30 Armor=8 Gold=10 Tier=6

  Board: 21/27 [G], 22/22, 24/25, 26/25, 28/29, 35/34, 31/32
  Tavern: Forsaken Weaver 33/39 T6 $3 | Groundbreaker 34/33 T6 $3 | Wrath Weaver 30/33 T1 $3 | Lava Lurker 31/34 T2 $3 | Rimescale Priestess 32/32 T4 $3 | Deflect-o-Bot 32/31 T3 $3

  → Board: 21/27 [G], 24/25, 26/25, 28/29, 35/34, 31/32, 33/39
  → Actions (3): sell_board_1, buy_tavern_0, play_hand_3

**Ysera**  HP=20 Armor=0 Gold=10 Tier=6

  Board: 8/8 [G], 38/38, 6/8, 4/4, 7/5, 2/8, 3/4
  Tavern: Alert Alarmist 2/2 T2 $3 | Lurking Leviathan 3/8 T5 $3 | Cadaver Caretaker 3/3 T3 $3 | Scarlet Skull 2/1 T2 $3 | Skeletal Strafer 6/6 T5 $3 | Technical Element 5/6 T3 $3 | Felfire Conjurer 6/5 T5 $3

  → Board: 8/8 [G], 38/38, 6/8, 4/4, 7/5, 2/8, 3/5
  → Actions (3): sell_board_6, play_hand_6, buy_tavern_2

**Combat Phase**

  Overlord Saurfang vs Ysera (first: Overlord Saurfang)
     Overlord Saurfang: [21/27, 24/25, 26/25, 28/29, 35/34, 31/32, 33/39]
     Ysera: [8/8, 38/38, 6/8, 4/4, 7/5, 2/8, 3/5]
     Wrath Weaver 21/27→21/24  |  Hunting Tiger Shark 3/5→3/0 DEAD
     Scarlet Survivor 8/8→8/0 DEAD  |  Deathly Striker 35/34→35/26
     Technical Element 24/25→24/0 DEAD  |  Tarecgosa 38/38→38/14
     Tarecgosa 38/14→38/0 DEAD  |  Technical Element 28/29→28/0 DEAD
     Monstrous Macaw 26/25→26/21  |  Stomping Stegodon 4/4→4/0 DEAD
     Black Chromadrake 6/8→6/0 DEAD  |  Forsaken Weaver 33/39→33/33
     Deathly Striker 35/26→35/24  |  Incubation Researcher 2/8→2/0 DEAD
     Red Chromadrake 7/5→7/0 DEAD  |  Monstrous Macaw 26/21→26/14
     Result: survivors 5 vs 0 — winner: Overlord Saurfang

  **Overlord Saurfang eliminated!** (HP=0, Turn 15)
  **Ysera eliminated!** (HP=0, Turn 15)

---

## Final Standings

| # | Hero | HP | Armor | Alive | Eliminated Turn |
|---|---|---|---|---|
| 1 | Overlord Saurfang | 30 | 8 | No | 15 |
| 2 | Ysera | 0 | 0 | No | 15 |
| 3 | Yogg-Saron, Hope's End | 0 | 0 | No | 14 |
| 4 | Sylvanas Windrunner | 0 | 0 | No | 14 |
| 5 | Sneed | 0 | 0 | No | 13 |
| 6 | Inge, the Iron Hymn | 0 | 0 | No | 13 |
| 7 | Drek'Thar | 0 | 0 | No | 11 |
| 8 | Professor Putricide | 0 | 0 | No | 10 |

---

## Agent Strategy

**SearchAgent (greedy)** with GameValueNetwork evaluates each legal action by:

1. Simulate action forward (buy, sell, play, upgrade, refresh, freeze, hero power)
2. Encode resulting POMDP state (61-dim: board embedding + own stats + opponent stats)
3. Evaluate V(s') with GameValueNetwork (MSE-trained to predict expected placement)
4. Choose action with highest V(s'); end turn if no action improves baseline

This is a one-step greedy lookahead using learned value function —
no multi-step planning, no opponent modeling, no combat simulation at decision time.