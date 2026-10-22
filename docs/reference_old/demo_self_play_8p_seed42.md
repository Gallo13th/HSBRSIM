# 8-Player Battlegrounds — All SearchAgent Self-Play Demo

**Seed**: 42  |  **Max Turns**: 15  |  **Agents**: 8× SearchAgent (greedy)

**Game Value**: `checkpoints/game_value_v3_clean.pt`  |  **Board Eval**: `checkpoints/board_eval_v3_clean.pt`

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

  → Board: 1/2 [Taunt,DS]
  → Actions (2): buy_tavern_2, play_hand_0

**Combat Phase**

  Overlord Saurfang vs Drek'Thar (first: Drek'Thar)
     Overlord Saurfang: [2/5]
     Drek'Thar: [1/2]
     Annoy-o-Tron 1/2→1/2  |  Wrath Weaver 2/5→2/4
     Wrath Weaver 2/4→2/3  |  Annoy-o-Tron 1/2→1/0 DEAD
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
  Sylvanas Windrunner vs Inge, the Iron Hymn (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [2/1]
     Inge, the Iron Hymn: [4/1]
     Risen Rider 2/1→2/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 0 vs 0 — winner: draw

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=18, Tier=1) | Sneed (HP=30, Armor=12, Tier=1) | Overlord Saurfang (HP=30, Armor=18, Tier=1) | Ysera (HP=30, Armor=12, Tier=1) | Inge, the Iron Hymn (HP=30, Armor=12, Tier=1) | Professor Putricide (HP=30, Armor=10, Tier=1) | Sylvanas Windrunner (HP=30, Armor=10, Tier=1) | Drek'Thar (HP=30, Armor=10, Tier=1)

### Turn 2

**Yogg-Saron, Hope's End**  HP=30 Armor=18 Gold=4 Tier=1

  Board: 4/1
  Tavern: Wrath Weaver 1/4 T1 $3 | Risen Rider 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Meditation (spell) T1 $3

  → Board: 4/1, 1/4
  → Actions (2): buy_tavern_0, play_hand_0

**Sneed**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 2/1
  Tavern: Harmless Bonehead 1/1 T1 $3 | Ominous Seer 2/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Recruit a Trainee (spell) T1 $2

  → Board: 2/1, 1/4
  → Actions (2): buy_tavern_2, play_hand_0

**Overlord Saurfang**  HP=30 Armor=18 Gold=4 Tier=1

  Board: 2/5
  Tavern: Risen Rider 5/4 T1 $3 | Harmless Bonehead 4/4 T1 $3 | Surf n' Surf 4/4 T1 $3 | Sick Riffs (spell) T1 $3

  → Board: 2/5, 5/4 [Taunt,Reborn]
  → Actions (2): buy_tavern_0, play_hand_0

**Ysera**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 3/3
  Tavern: Ominous Seer 2/1 T1 $3 | Manasaber 4/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Angler's Lure (spell) T1 $3 | Scarlet Survivor 3/3 T1 $3

  → Board: 3/3, 1/2 [Taunt,DS]
  → Actions (2): buy_tavern_2, play_hand_0

**Inge, the Iron Hymn**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 4/1
  Tavern: Ominous Seer 2/1 T1 $3 | Risen Rider 2/1 T1 $3 | Cord Puller 1/1 T1 $3 | Enchanted Lasso (spell) T1 $2

  → Board: 4/1, 2/1
  → Actions (2): buy_tavern_0, play_hand_0

**Professor Putricide**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 4/1
  Tavern: Risen Rider 2/1 T1 $3 | Cord Puller 1/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Fortify (spell) T1 $1

  → Board: 4/1, 2/1 [Taunt,Reborn]
  → Actions (2): buy_tavern_0, play_hand_0

**Sylvanas Windrunner**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 2/1 [Taunt,Reborn]
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Ominous Seer 2/1 T1 $3 | Undersea Mount (spell) T1 $3

  → Board: 2/1 [Taunt,Reborn], 1/2 [Taunt,DS]
  → Actions (2): buy_tavern_0, play_hand_0

**Drek'Thar**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 1/2 [Taunt,DS]
  Tavern: Wrath Weaver 1/4 T1 $3 | Surf n' Surf 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Glowing Crown (spell) T1 $3

  → Board: 1/2 [Taunt,DS], 1/4
  → Actions (2): buy_tavern_0, play_hand_0

**Combat Phase**

  Inge, the Iron Hymn vs Professor Putricide (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 2/1]
     Professor Putricide: [4/1, 2/1]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Ominous Seer 2/1→2/0 DEAD
     Result: survivors 0 vs 0 — winner: draw
  Sneed vs Drek'Thar (first: Drek'Thar)
     Sneed: [2/1, 1/4]
     Drek'Thar: [1/2, 1/4]
     Annoy-o-Tron 1/2→1/2  |  Wrath Weaver 1/4→1/3
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 1/4→1/3  |  Wrath Weaver 1/3→1/2
     Wrath Weaver 1/2→1/1  |  Wrath Weaver 1/3→1/2
     Result: survivors 1 vs 1 — winner: Sneed
  Overlord Saurfang vs Yogg-Saron, Hope's End (first: Overlord Saurfang)
     Overlord Saurfang: [2/5, 5/4]
     Yogg-Saron, Hope's End: [4/1, 1/4]
     Wrath Weaver 2/5→2/1  |  Manasaber 4/1→4/0 DEAD
     Wrath Weaver 1/4→1/0 DEAD  |  Risen Rider 5/4→5/3
     Result: survivors 2 vs 0 — winner: Overlord Saurfang
  Sylvanas Windrunner vs Ysera (first: Ysera)
     Sylvanas Windrunner: [2/1, 1/2]
     Ysera: [3/3, 1/2]
     Scarlet Survivor 3/3→3/2  |  Annoy-o-Tron 1/2→1/2
     Risen Rider 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Annoy-o-Tron 1/1→1/0 DEAD  |  Annoy-o-Tron 1/1→1/0 DEAD
     Result: survivors 0 vs 1 — winner: Ysera

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=15, Tier=1) | Sneed (HP=30, Armor=12, Tier=1) | Overlord Saurfang (HP=30, Armor=18, Tier=1) | Ysera (HP=30, Armor=12, Tier=1) | Inge, the Iron Hymn (HP=30, Armor=12, Tier=1) | Professor Putricide (HP=30, Armor=10, Tier=1) | Sylvanas Windrunner (HP=30, Armor=8, Tier=1) | Drek'Thar (HP=30, Armor=10, Tier=1)

### Turn 3

**Yogg-Saron, Hope's End**  HP=30 Armor=15 Gold=5 Tier=1

  Board: 4/1, 1/4
  Tavern: Ominous Seer 2/1 T1 $3 | Cord Puller 1/1 T1 $3 | Picky Eater 1/1 T1 $3 | Tavern Coin (spell) T1 $1

  → Board: 4/1, 1/4, 2/1
  → Actions (2): buy_tavern_0, play_hand_0

**Sneed**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 2/1, 1/4
  Tavern: Risen Rider 2/1 T1 $3 | Risen Rider 2/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Tavern Dish Banana (spell) T1 $1

  → Board: 1/4, 1/2 [Taunt,DS]
  → Gold: 2→3
  → Actions (3): buy_tavern_2, play_hand_0, sell_board_0

**Overlord Saurfang**  HP=30 Armor=18 Gold=5 Tier=1

  Board: 2/5, 5/4 [Taunt,Reborn]
  Tavern: Wrath Weaver 6/9 T1 $3 | Cord Puller 6/6 T1 $3 | Annoy-o-Tron 6/7 T1 $3 | Banana (spell) T1 $0

  → Board: 4/7, 6/9
  → Gold: 2→3 | Armor: 18→17
  → Actions (3): buy_tavern_0, play_hand_0, sell_board_1

**Ysera**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 3/3, 1/2 [Taunt,DS]
  Tavern: Cord Puller 1/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | The Goldenizer (spell) T1 $0 | Scarlet Survivor 3/3 T1 $3

  → Board: 3/3, 1/2 [Taunt,DS], 3/3
  → Actions (2): buy_tavern_4, play_hand_0

**Inge, the Iron Hymn**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 4/1, 2/1
  Tavern: Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Picky Eater 1/1 T1 $3

  → Board: 4/1, 1/2 [Taunt,DS]
  → Gold: 2→3
  → Actions (3): buy_tavern_1, play_hand_0, sell_board_1

**Professor Putricide**  HP=30 Armor=10 Gold=5 Tier=1

  Board: 4/1, 2/1 [Taunt,Reborn]
  Tavern: Risen Rider 2/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Surf n' Surf 1/1 T1 $3

  → Board: 4/1, 1/2 [Taunt,DS]
  → Gold: 2→3
  → Actions (3): buy_tavern_1, play_hand_0, sell_board_1

**Sylvanas Windrunner**  HP=30 Armor=8 Gold=5 Tier=1

  Board: 2/1 [Taunt,Reborn], 1/2 [Taunt,DS]
  Tavern: Harmless Bonehead 1/1 T1 $3 | Risen Rider 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3

  → Board: 1/2 [Taunt,DS], 2/1 [Taunt,Reborn]
  → Gold: 2→3
  → Actions (3): buy_tavern_1, play_hand_0, sell_board_0

**Drek'Thar**  HP=30 Armor=10 Gold=5 Tier=1

  Board: 1/2 [Taunt,DS], 1/4
  Tavern: Ominous Seer 2/1 T1 $3 | Manasaber 4/1 T1 $3 | Ominous Seer 2/1 T1 $3

  → Board: 1/2 [Taunt,DS], 1/4, 4/1
  → Actions (2): buy_tavern_1, play_hand_0

**Combat Phase**

  Ysera vs Drek'Thar (first: Drek'Thar)
     Ysera: [3/3, 1/2, 3/3]
     Drek'Thar: [1/2, 1/4, 4/1]
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/2
     Scarlet Survivor 3/3→3/2  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/1
     Annoy-o-Tron 1/1→1/0 DEAD  |  Wrath Weaver 1/3→1/2
     Manasaber 4/1→4/0 DEAD  |  Scarlet Survivor 3/2→3/0 DEAD
     Scarlet Survivor 3/3→3/2  |  Wrath Weaver 1/2→1/0 DEAD
     Result: survivors 1 vs 0 — winner: Ysera
  Inge, the Iron Hymn vs Sneed (first: Sneed)
     Inge, the Iron Hymn: [4/1, 1/2]
     Sneed: [1/4, 1/2]
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Annoy-o-Tron 1/1→1/0 DEAD  |  Annoy-o-Tron 1/1→1/0 DEAD
     Result: survivors 0 vs 1 — winner: Sneed
  Overlord Saurfang vs Sylvanas Windrunner (first: Overlord Saurfang)
     Overlord Saurfang: [4/7, 6/9]
     Sylvanas Windrunner: [1/2, 2/1]
     Wrath Weaver 4/7→4/6  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Wrath Weaver 4/6→4/5
     Wrath Weaver 6/9→6/7  |  Risen Rider 2/1→2/0 DEAD
     Result: survivors 2 vs 0 — winner: Overlord Saurfang
  Professor Putricide vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Professor Putricide: [4/1, 1/2]
     Yogg-Saron, Hope's End: [4/1, 1/4, 2/1]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Ominous Seer 2/1→2/0 DEAD
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/1
     Annoy-o-Tron 1/1→1/0 DEAD  |  Wrath Weaver 1/3→1/2
     Result: survivors 0 vs 1 — winner: Yogg-Saron, Hope's End

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=15, Tier=1) | Sneed (HP=30, Armor=12, Tier=1) | Overlord Saurfang (HP=30, Armor=17, Tier=1) | Ysera (HP=30, Armor=12, Tier=1) | Inge, the Iron Hymn (HP=30, Armor=10, Tier=1) | Professor Putricide (HP=30, Armor=8, Tier=1) | Sylvanas Windrunner (HP=30, Armor=5, Tier=1) | Drek'Thar (HP=30, Armor=8, Tier=1)

### Turn 4

**Yogg-Saron, Hope's End**  HP=30 Armor=15 Gold=6 Tier=1

  Board: 4/1, 1/4, 2/1
  Tavern: Picky Eater 1/1 T1 $3 | Cord Puller 1/1 T1 $3 | Picky Eater 1/1 T1 $3


**Sneed**  HP=30 Armor=12 Gold=6 Tier=1

  Board: 1/4, 1/2 [Taunt,DS]
  Tavern: Risen Rider 2/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3

  → Board: 1/4, 1/2 [Taunt,DS], 4/1
  → Upgrade T1→T2 | Gold: 1→0
  → Actions (5): refresh, refresh, buy_tavern_1, play_hand_0, upgrade

**Overlord Saurfang**  HP=30 Armor=17 Gold=6 Tier=1

  Board: 4/7, 6/9
  Tavern: Picky Eater 8/8 T1 $3 | Risen Rider 9/8 T1 $3 | Picky Eater 8/8 T1 $3

  → Board: 6/9, 9/8 [Taunt,Reborn]
  → Gold: 3→4
  → Actions (3): buy_tavern_1, play_hand_0, sell_board_0

**Ysera**  HP=30 Armor=12 Gold=6 Tier=1

  Board: 3/3, 1/2 [Taunt,DS], 3/3
  Tavern: Harmless Bonehead 1/1 T1 $3 | Risen Rider 2/1 T1 $3 | Picky Eater 1/1 T1 $3 | Scarlet Survivor 3/3 T1 $3


**Inge, the Iron Hymn**  HP=30 Armor=10 Gold=6 Tier=1

  Board: 4/1, 1/2 [Taunt,DS]
  Tavern: Ominous Seer 2/1 T1 $3 | Manasaber 4/1 T1 $3 | Cord Puller 1/1 T1 $3

  → Board: 4/1, 1/2 [Taunt,DS], 4/1
  → Upgrade T1→T2 | Gold: 3→2
  → Actions (3): buy_tavern_1, play_hand_0, upgrade

**Professor Putricide**  HP=30 Armor=8 Gold=6 Tier=1

  Board: 4/1, 1/2 [Taunt,DS]
  Tavern: Surf n' Surf 1/1 T1 $3 | Ominous Seer 2/1 T1 $3 | Cord Puller 1/1 T1 $3

  → Board: 4/1, 1/2 [Taunt,DS], 2/1
  → Actions (2): buy_tavern_1, play_hand_0

**Sylvanas Windrunner**  HP=30 Armor=5 Gold=6 Tier=1

  Board: 1/2 [Taunt,DS], 2/1 [Taunt,Reborn]
  Tavern: Manasaber 4/1 T1 $3 | Ominous Seer 2/1 T1 $3 | Manasaber 4/1 T1 $3

  → Board: 1/2 [Taunt,DS], 2/1 [Taunt,Reborn], 4/1
  → Actions (2): buy_tavern_0, play_hand_0

**Drek'Thar**  HP=30 Armor=8 Gold=6 Tier=1

  Board: 1/2 [Taunt,DS], 1/4, 4/1
  Tavern: Wrath Weaver 1/4 T1 $3 | Ominous Seer 2/1 T1 $3 | Cord Puller 1/1 T1 $3

  → Board: 1/2 [Taunt,DS], 1/4, 4/1
  → Gold: 6→5
  → Actions (1): refresh

**Combat Phase**

  Sneed vs Overlord Saurfang (first: Sneed)
     Sneed: [1/4, 1/2, 4/1]
     Overlord Saurfang: [6/9, 9/8]
     Wrath Weaver 1/4→1/0 DEAD  |  Risen Rider 9/8→9/7
     Wrath Weaver 6/9→6/8  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Risen Rider 9/7→9/6
     Risen Rider 9/6→9/2  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 0 vs 2 — winner: Overlord Saurfang
  Inge, the Iron Hymn vs Yogg-Saron, Hope's End (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 4/1]
     Yogg-Saron, Hope's End: [4/1, 1/4, 2/1]
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Ominous Seer 2/1→2/0 DEAD
     Result: survivors 1 vs 1 — winner: Inge, the Iron Hymn
  Drek'Thar vs Sylvanas Windrunner (first: Drek'Thar)
     Drek'Thar: [1/2, 1/4, 4/1]
     Sylvanas Windrunner: [1/2, 2/1, 4/1]
     Annoy-o-Tron 1/2→1/2  |  Risen Rider 2/1→2/0 DEAD
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/1
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/1
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/1→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/1→1/0 DEAD
     Result: survivors 1 vs 0 — winner: Drek'Thar
  Ysera vs Professor Putricide (first: Ysera)
     Ysera: [3/3, 1/2, 3/3]
     Professor Putricide: [4/1, 1/2, 2/1]
     Scarlet Survivor 3/3→3/2  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Annoy-o-Tron 1/1→1/0 DEAD  |  Annoy-o-Tron 1/1→1/0 DEAD
     Scarlet Survivor 3/3→3/1  |  Ominous Seer 2/1→2/0 DEAD
     Result: survivors 2 vs 0 — winner: Ysera

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=15, Tier=1) | Sneed (HP=30, Armor=9, Tier=2) | Overlord Saurfang (HP=30, Armor=17, Tier=1) | Ysera (HP=30, Armor=12, Tier=1) | Inge, the Iron Hymn (HP=30, Armor=10, Tier=2) | Professor Putricide (HP=30, Armor=5, Tier=1) | Sylvanas Windrunner (HP=30, Armor=3, Tier=1) | Drek'Thar (HP=30, Armor=8, Tier=1)

### Turn 5

**Yogg-Saron, Hope's End**  HP=30 Armor=15 Gold=7 Tier=1

  Board: 4/1, 1/4, 2/1
  Tavern: Harmless Bonehead 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3

  → Board: 4/1, 1/4, 1/2 [Taunt,DS]
  → Gold: 4→5
  → Actions (3): buy_tavern_2, play_hand_0, sell_board_2

**Sneed**  HP=30 Armor=9 Gold=7 Tier=2

  Board: 1/4, 1/2 [Taunt,DS], 4/1
  Tavern: Alert Alarmist 2/2 T2 $3 | Alert Alarmist 2/2 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Old Soul 3/4 T2 $3 | Chef's Choice (spell) T2 $2

  → Board: 1/4, 1/2 [Taunt,DS], 4/1, 3/4
  → Actions (2): buy_tavern_3, play_hand_0

**Overlord Saurfang**  HP=30 Armor=17 Gold=7 Tier=1

  Board: 6/9, 9/8 [Taunt,Reborn]
  Tavern: Manasaber 12/9 T1 $3 | Annoy-o-Tron 9/10 T1 $3 | Picky Eater 9/9 T1 $3

  → Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS]
  → Gold: 4→5
  → Actions (3): buy_tavern_1, play_hand_0, sell_board_0

**Ysera**  HP=30 Armor=12 Gold=7 Tier=1

  Board: 3/3, 1/2 [Taunt,DS], 3/3
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Twilight Hatchling 1/1 T1 $3

  → Board: 3/3, 1/2 [Taunt,DS], 3/3, 1/4
  → Upgrade T1→T2 | Gold: 4→3
  → Actions (3): buy_tavern_2, play_hand_0, upgrade

**Inge, the Iron Hymn**  HP=30 Armor=10 Gold=7 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 4/1
  Tavern: Laboratory Assistant 3/4 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Lava Lurker 2/5 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Strike Oil (spell) T2 $3

  → Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4
  → Actions (2): buy_tavern_0, play_hand_0

**Professor Putricide**  HP=30 Armor=5 Gold=7 Tier=1

  Board: 4/1, 1/2 [Taunt,DS], 2/1
  Tavern: Harmless Bonehead 1/1 T1 $3 | Picky Eater 1/1 T1 $3 | Risen Rider 2/1 T1 $3

  → Board: 4/1, 1/2 [Taunt,DS], 2/1
  → Gold: 6→5
  → Actions (2): refresh, refresh

**Sylvanas Windrunner**  HP=30 Armor=3 Gold=7 Tier=1

  Board: 1/2 [Taunt,DS], 2/1 [Taunt,Reborn], 4/1
  Tavern: Manasaber 4/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Risen Rider 2/1 T1 $3

  → Board: 1/2 [Taunt,DS], 4/1, 4/1
  → Gold: 4→5
  → Actions (3): buy_tavern_0, play_hand_0, sell_board_1

**Drek'Thar**  HP=30 Armor=8 Gold=7 Tier=1

  Board: 1/2 [Taunt,DS], 1/4, 4/1
  Tavern: Ominous Seer 2/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Risen Rider 2/1 T1 $3

  → Board: 1/2 [Taunt,DS], 3/6, 4/1
  → Gold: 4→5 | Armor: 8→7
  → Actions (3): buy_tavern_1, play_hand_0, sell_board_3

**Combat Phase**

  Sylvanas Windrunner vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Sylvanas Windrunner: [1/2, 4/1, 4/1]
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/1→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/1→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 0 vs 1 — winner: Inge, the Iron Hymn
  Overlord Saurfang vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Overlord Saurfang: [9/8, 9/10]
     Yogg-Saron, Hope's End: [4/1, 1/4, 1/2]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 9/8→9/4
     Risen Rider 9/4→9/3  |  Annoy-o-Tron 1/2→1/2
     Wrath Weaver 1/4→1/0 DEAD  |  Risen Rider 9/3→9/2
     Annoy-o-Tron 9/10→9/10  |  Annoy-o-Tron 1/2→1/0 DEAD
     Result: survivors 2 vs 0 — winner: Overlord Saurfang
  Ysera vs Sneed (first: Sneed)
     Ysera: [3/3, 1/2, 3/3, 1/4]
     Sneed: [1/4, 1/2, 4/1, 3/4]
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/2
     Scarlet Survivor 3/3→3/2  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Annoy-o-Tron 1/1→1/0 DEAD  |  Annoy-o-Tron 1/1→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Scarlet Survivor 3/2→3/0 DEAD
     Scarlet Survivor 3/3→3/2  |  Wrath Weaver 1/3→1/0 DEAD
     Old Soul 3/4→3/3  |  Wrath Weaver 1/4→1/1
     Wrath Weaver 1/1→1/0 DEAD  |  Old Soul 3/3→3/2
     Result: survivors 1 vs 1 — winner: Ysera
  Drek'Thar vs Professor Putricide (first: Drek'Thar)
     Drek'Thar: [1/2, 3/6, 4/1]
     Professor Putricide: [4/1, 1/2, 2/1]
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/2→1/0 DEAD
     Ominous Seer 2/1→2/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 1 vs 0 — winner: Drek'Thar

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=12, Tier=1) | Sneed (HP=30, Armor=9, Tier=2) | Overlord Saurfang (HP=30, Armor=17, Tier=1) | Ysera (HP=30, Armor=12, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=10, Tier=2) | Professor Putricide (HP=30, Armor=3, Tier=1) | Drek'Thar (HP=30, Armor=7, Tier=1) | Sylvanas Windrunner (HP=29, Armor=0, Tier=1)

### Turn 6

**Yogg-Saron, Hope's End**  HP=30 Armor=12 Gold=8 Tier=1

  Board: 4/1, 1/4, 1/2 [Taunt,DS]
  Tavern: Picky Eater 1/1 T1 $3 | Picky Eater 1/1 T1 $3 | Cord Puller 1/1 T1 $3

  → Gold: 8→5 | Trinket: Lucky Tabby
  → Actions (1): buy_trinket_0

**Sneed**  HP=30 Armor=9 Gold=8 Tier=2

  Board: 1/4, 1/2 [Taunt,DS], 4/1, 3/4
  Tavern: Tide Raiser 2/1 T2 $3 | Sewer Rat 3/2 T2 $3 | Metallic Hunter 4/2 T2 $3 | Eternal Knight 4/2 T2 $3 | Hasty Excavation (spell) T2 $3

  → Gold: 8→5 | Trinket: Bleeding Heart
  → Actions (1): buy_trinket_0

**Overlord Saurfang**  HP=30 Armor=17 Gold=8 Tier=1

  Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS]
  Tavern: Ominous Seer 12/11 T1 $3 | Wrath Weaver 11/14 T1 $3 | Wrath Weaver 11/14 T1 $3

  → Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 5/6
  → Trinket: Defiler Portrait
  → Actions (2): buy_trinket_3, play_hand_0

**Ysera**  HP=30 Armor=12 Gold=8 Tier=2

  Board: 3/3, 1/2 [Taunt,DS], 3/3, 1/4
  Tavern: Humming Bird 1/4 T2 $3 | Harmless Bonehead 1/1 T1 $3 | Sewer Rat 3/2 T2 $3 | Sewer Rat 3/2 T2 $3 | Search Through Time (spell) T2 $2 | Scarlet Survivor 3/3 T1 $3

  → Board: 1/2 [Taunt,DS], 1/4, 10/10 [DS,G]
  → Gold: 4→3 | Trinket: Dragonwing Glider | Hand: 0→1
  → Actions (4): buy_trinket_0, buy_tavern_5, play_hand_0, refresh

**Inge, the Iron Hymn**  HP=30 Armor=10 Gold=8 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4
  Tavern: Humming Bird 1/4 T2 $3 | Wrath Weaver 1/4 T1 $3 | Alert Alarmist 2/2 T2 $3 | Scarlet Skull 2/1 T2 $3 | Might of Stormwind (spell) T2 $2

  → Gold: 8→5 | Trinket: Lucky Tabby
  → Actions (1): buy_trinket_0

**Professor Putricide**  HP=30 Armor=3 Gold=8 Tier=1

  Board: 4/1, 1/2 [Taunt,DS], 2/1
  Tavern: Harmless Bonehead 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3

  → Board: 4/1, 1/2 [Taunt,DS], 1/4, 1/1
  → Trinket: Beetle Band
  → Actions (6): buy_trinket_0, buy_tavern_2, play_hand_0, sell_board_2, buy_tavern_0, play_hand_0

**Sylvanas Windrunner**  HP=29 Armor=0 Gold=8 Tier=1

  Board: 1/2 [Taunt,DS], 4/1, 4/1
  Tavern: Cord Puller 3/2 T1 $3 | Risen Rider 2/1 T1 $3 | Manasaber 4/1 T1 $3

  → Board: 1/2 [Taunt,DS], 4/1, 4/1, 3/2 [DS]
  → Trinket: Beetle Band
  → Actions (3): buy_trinket_1, buy_tavern_0, play_hand_0

**Drek'Thar**  HP=30 Armor=7 Gold=8 Tier=1

  Board: 1/2 [Taunt,DS], 3/6, 4/1
  Tavern: Ominous Seer 2/1 T1 $3 | Cord Puller 1/1 T1 $3 | Risen Rider 2/1 T1 $3

  → Gold: 8→5 | Trinket: Demonic Tapestry
  → Actions (1): buy_trinket_1

**Combat Phase**

  Sylvanas Windrunner vs Yogg-Saron, Hope's End (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [1/2, 4/1, 4/1, 3/2]
     Yogg-Saron, Hope's End: [4/1, 1/4, 1/2]
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 1/4→1/1  |  Cord Puller 3/2→3/2
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 1/1→1/0 DEAD
     Result: survivors 1 vs 0 — winner: Sylvanas Windrunner
  Inge, the Iron Hymn vs Sneed (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4]
     Sneed: [1/4, 1/2, 4/1, 3/4]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Annoy-o-Tron 1/1→1/0 DEAD  |  Annoy-o-Tron 1/1→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 1/3→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Laboratory Assistant 3/4→3/0 DEAD
     Result: survivors 0 vs 1 — winner: Sneed
  Ysera vs Drek'Thar (first: Ysera)
     Ysera: [1/2, 1/4, 10/10]
     Drek'Thar: [1/2, 3/6, 4/1]
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/1→1/0 DEAD
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/1→1/0 DEAD
     Scarlet Survivor 10/10→10/10  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 2 vs 1 — winner: Ysera
  Professor Putricide vs Overlord Saurfang (first: Professor Putricide)
     Professor Putricide: [4/1, 1/2, 1/4, 1/1]
     Overlord Saurfang: [9/8, 9/10, 5/6]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 9/10→9/10
     Risen Rider 9/8→9/7  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Annoy-o-Tron 9/10→9/9
     Annoy-o-Tron 9/9→9/8  |  Wrath Weaver 1/4→1/0 DEAD
     Harmless Bonehead 1/1→1/0 DEAD  |  Risen Rider 9/7→9/6
     Result: survivors 0 vs 3 — winner: Overlord Saurfang

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=10, Tier=1) | Sneed (HP=30, Armor=9, Tier=2) | Overlord Saurfang (HP=30, Armor=17, Tier=1) | Ysera (HP=30, Armor=12, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=6, Tier=2) | Drek'Thar (HP=30, Armor=7, Tier=1) | Sylvanas Windrunner (HP=29, Armor=0, Tier=1) | Professor Putricide (HP=26, Armor=0, Tier=1)

### Turn 7

**Yogg-Saron, Hope's End**  HP=30 Armor=10 Gold=9 Tier=1

  Board: 4/1, 1/4, 1/2 [Taunt,DS]
  Tavern: Wrath Weaver 1/4 T1 $3 | Cord Puller 1/1 T1 $3 | Ominous Seer 2/1 T1 $3

  → Board: 4/1, 3/6, 1/2 [Taunt,DS], 1/4
  → Armor: 10→9
  → Actions (2): buy_tavern_0, play_hand_0

**Sneed**  HP=30 Armor=9 Gold=9 Tier=2

  Board: 1/4, 1/2 [Taunt,DS], 4/1, 3/4
  Tavern: Nerubian Deathswarmer 1/4 T2 $3 | Sewer Rat 3/2 T2 $3 | Shell Collector 4/3 T2 $3 | Old Soul 3/4 T2 $3

  → Board: 1/4, 1/2 [Taunt,DS], 4/1, 3/4, 4/3
  → Hand: 0→1
  → Actions (2): buy_tavern_2, play_hand_0

**Overlord Saurfang**  HP=30 Armor=17 Gold=9 Tier=1

  Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 5/6
  Tavern: Wrath Weaver 12/15 T1 $3 | Annoy-o-Tron 12/13 T1 $3 | Wrath Weaver 12/15 T1 $3

  → Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 5/6, 5/6
  → Hand: 1→0
  → Actions (1): play_hand_0

**Ysera**  HP=30 Armor=12 Gold=9 Tier=2

  Board: 1/2 [Taunt,DS], 1/4, 10/10 [DS,G]
  Tavern: Tide Raiser 2/1 T2 $3 | Metallic Hunter 4/2 T2 $3 | Lava Lurker 2/5 T2 $3 | Reef Riffer 3/2 T2 $3 | Scarlet Survivor 3/3 T1 $3

  → Board: 1/2 [Taunt,DS], 1/4, 14/14 [DS,G], 2/5
  → Actions (2): buy_tavern_2, play_hand_1

**Inge, the Iron Hymn**  HP=30 Armor=6 Gold=9 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4
  Tavern: Scarlet Skull 2/1 T2 $3 | Sewer Rat 3/2 T2 $3 | Alert Alarmist 2/2 T2 $3 | Humming Bird 1/4 T2 $3

  → Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 1/4
  → Actions (2): buy_tavern_3, play_hand_0

**Professor Putricide**  HP=26 Armor=0 Gold=9 Tier=1

  Board: 4/1, 1/2 [Taunt,DS], 1/4, 1/1
  Tavern: Ominous Seer 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Harmless Bonehead 1/1 T1 $3

  → Board: 4/1, 1/2 [Taunt,DS], 1/4, 1/1
  → Gold: 9→8
  → Actions (1): refresh

**Sylvanas Windrunner**  HP=29 Armor=0 Gold=9 Tier=1

  Board: 1/2 [Taunt,DS], 4/1, 4/1, 3/2 [DS]
  Tavern: 

  → Board: 1/2 [Taunt,DS], 4/1, 4/1, 3/2 [DS]
  → Gold: 9→8
  → Actions (1): refresh

**Drek'Thar**  HP=30 Armor=7 Gold=9 Tier=1

  Board: 1/2 [Taunt,DS], 3/6, 4/1
  Tavern: 

  → Board: 1/2 [Taunt,DS], 3/6, 4/1
  → Gold: 6→5
  → Actions (4): refresh, refresh, refresh, refresh

**Combat Phase**

  Sneed vs Drek'Thar (first: Sneed)
     Sneed: [1/4, 1/2, 4/1, 3/4, 4/3]
     Drek'Thar: [1/2, 3/6, 4/1]
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/1→1/0 DEAD
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/1→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 3 vs 1 — winner: Sneed
  Ysera vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Ysera: [1/2, 1/4, 14/14, 2/5]
     Inge, the Iron Hymn: [5/1, 1/2, 5/1, 3/4, 2/4]
     Manasaber 5/1→5/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/1→1/0 DEAD
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/1→1/0 DEAD
     Manasaber 5/1→5/0 DEAD  |  Lava Lurker 2/5→2/0 DEAD
     Scarlet Survivor 14/14→14/14  |  Humming Bird 2/4→2/0 DEAD
     Laboratory Assistant 3/4→3/3  |  Wrath Weaver 1/3→1/0 DEAD
     Result: survivors 1 vs 1 — winner: Ysera
  Overlord Saurfang vs Sylvanas Windrunner (first: Sylvanas Windrunner)
     Overlord Saurfang: [9/8, 9/10, 5/6, 5/6]
     Sylvanas Windrunner: [1/2, 4/1, 4/1, 3/2]
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 9/10→9/10
     Risen Rider 9/8→9/7  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 9/10→9/6
     Annoy-o-Tron 9/6→9/3  |  Cord Puller 3/2→3/2
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 9/7→9/3
     Woodland Defiler 5/6→5/3  |  Cord Puller 3/2→3/0 DEAD
     Result: survivors 4 vs 0 — winner: Overlord Saurfang
  Professor Putricide vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Professor Putricide: [4/1, 1/2, 1/4, 1/1]
     Yogg-Saron, Hope's End: [4/1, 3/6, 1/2, 1/4, 50/50, 50/50]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/1
     Annoy-o-Tron 1/1→1/0 DEAD  |  Wrath Weaver 1/3→1/2
     Harmless Bonehead 1/1→1/0 DEAD  |  Amalgam 50/50→50/49
     Wrath Weaver 1/4→1/3  |  Wrath Weaver 1/2→1/1
     Result: survivors 1 vs 4 — winner: Professor Putricide

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=9, Tier=1) | Sneed (HP=30, Armor=9, Tier=2) | Overlord Saurfang (HP=30, Armor=17, Tier=1) | Ysera (HP=30, Armor=12, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=6, Tier=2) | Drek'Thar (HP=30, Armor=7, Tier=1) | Professor Putricide (HP=26, Armor=0, Tier=1) | Sylvanas Windrunner (HP=19, Armor=0, Tier=1)

### Turn 8

**Yogg-Saron, Hope's End**  HP=30 Armor=9 Gold=10 Tier=1

  Board: 4/1, 3/6, 1/2 [Taunt,DS], 1/4, 50/50, 50/50
  Tavern: 

  → Board: 3/6, 1/2 [Taunt,DS], 1/4, 50/50, 50/50
  → Gold: 10→11
  → Actions (1): sell_board_0

**Sneed**  HP=30 Armor=9 Gold=10 Tier=2

  Board: 1/4, 1/2 [Taunt,DS], 4/1, 3/4, 4/3
  Tavern: Alert Alarmist 2/2 T2 $3 | Shell Collector 4/3 T2 $3 | Scarlet Skull 2/1 T2 $3 | Old Soul 3/4 T2 $3

  → Board: 1/4, 1/2 [Taunt,DS], 4/1, 3/4, 4/3, 4/3
  → Hand: 1→2
  → Actions (2): buy_tavern_1, play_hand_1

**Overlord Saurfang**  HP=30 Armor=17 Gold=10 Tier=1

  Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS]
  Tavern: 

  → Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13
  → Actions (4): play_hand_0, refresh, buy_tavern_0, play_hand_1

**Ysera**  HP=30 Armor=12 Gold=10 Tier=2

  Board: 1/2 [Taunt,DS], 1/4, 14/14 [DS,G], 2/5
  Tavern: Alert Alarmist 2/2 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Twilight Hatchling 1/1 T1 $3

  → Board: 1/2 [Taunt,DS], 3/6, 18/18 [DS,G], 2/5, 3/4
  → Armor: 12→11
  → Actions (2): buy_tavern_1, play_hand_1

**Inge, the Iron Hymn**  HP=30 Armor=6 Gold=10 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 1/4
  Tavern: Scarlet Skull 2/1 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3

  → Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/4
  → Gold: 7→8
  → Actions (3): buy_tavern_1, play_hand_0, sell_board_4

**Professor Putricide**  HP=26 Armor=0 Gold=10 Tier=1

  Board: 4/1, 1/2 [Taunt,DS], 1/4, 1/1
  Tavern: 


**Sylvanas Windrunner**  HP=19 Armor=0 Gold=10 Tier=1

  Board: 1/2 [Taunt,DS], 4/1, 4/1, 3/2 [DS]
  Tavern: 

  → Board: 1/2 [Taunt,DS], 4/1, 4/1, 3/2 [DS]
  → Gold: 10→9
  → Actions (1): refresh

**Drek'Thar**  HP=30 Armor=7 Gold=10 Tier=1

  Board: 1/2 [Taunt,DS], 3/6, 4/1
  Tavern: 

  → Board: 1/2 [Taunt,DS], 3/6, 4/1
  → Gold: 6→5
  → Actions (5): refresh, refresh, refresh, refresh, refresh

**Combat Phase**

  Yogg-Saron, Hope's End vs Overlord Saurfang (first: Yogg-Saron, Hope's End)
     Yogg-Saron, Hope's End: [3/6, 1/2, 1/4, 50/50, 50/50]
     Overlord Saurfang: [9/8, 9/10, 10/12, 16/13]
     Wrath Weaver 3/6→3/0 DEAD  |  Risen Rider 9/8→9/5
     Risen Rider 9/5→9/4  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Risen Rider 9/4→9/3
     Annoy-o-Tron 9/10→9/10  |  Wrath Weaver 1/4→1/0 DEAD
     Amalgam 50/50→50/41  |  Annoy-o-Tron 9/10→9/0 DEAD
     Woodland Defiler 10/12→10/0 DEAD  |  Amalgam 50/41→50/31
     Amalgam 50/50→50/41  |  Risen Rider 9/3→9/0 DEAD
     Manasaber 16/13→16/0 DEAD  |  Amalgam 50/41→50/25
     Result: survivors 2 vs 0 — winner: Yogg-Saron, Hope's End
  Drek'Thar vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Drek'Thar: [1/2, 3/6, 4/1]
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4, 3/4]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/1→1/0 DEAD
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/1→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 3/5→3/1
     Manasaber 4/1→4/0 DEAD  |  Ancestral Automaton 3/4→3/0 DEAD
     Laboratory Assistant 3/4→3/1  |  Wrath Weaver 3/1→3/0 DEAD
     Result: survivors 0 vs 1 — winner: Inge, the Iron Hymn
  Ysera vs Sneed (first: Sneed)
     Ysera: [1/2, 3/6, 18/18, 2/5, 3/4]
     Sneed: [1/4, 1/2, 4/1, 3/4, 4/3, 4/3]
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/1→1/0 DEAD
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/1→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Laboratory Assistant 3/4→3/0 DEAD
     Scarlet Survivor 18/18→18/18  |  Shell Collector 4/3→4/0 DEAD
     Old Soul 3/4→3/0 DEAD  |  Scarlet Survivor 18/18→18/15
     Lava Lurker 2/5→2/4  |  Wrath Weaver 1/3→1/1
     Shell Collector 4/3→4/1  |  Lava Lurker 2/4→2/0 DEAD
     Result: survivors 2 vs 2 — winner: Ysera
  Professor Putricide vs Sylvanas Windrunner (first: Sylvanas Windrunner)
     Professor Putricide: [4/1, 1/2, 1/4, 1/1]
     Sylvanas Windrunner: [1/2, 4/1, 4/1, 3/2]
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 1/4→1/1  |  Cord Puller 3/2→3/2
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 1/1→1/0 DEAD
     Harmless Bonehead 1/1→1/0 DEAD  |  Cord Puller 3/2→3/1
     Result: survivors 0 vs 1 — winner: Sylvanas Windrunner

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=9, Tier=1) | Sneed (HP=30, Armor=9, Tier=2) | Overlord Saurfang (HP=30, Armor=16, Tier=1) | Ysera (HP=30, Armor=11, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=6, Tier=2) | Drek'Thar (HP=30, Armor=3, Tier=1) | Professor Putricide (HP=24, Armor=0, Tier=1) | Sylvanas Windrunner (HP=19, Armor=0, Tier=1)

### Turn 9

**Yogg-Saron, Hope's End**  HP=30 Armor=9 Gold=10 Tier=1

  Board: 3/6, 1/2 [Taunt,DS], 1/4, 50/50, 50/50, 50/50, 50/50
  Tavern: 

  → Board: 1/2 [Taunt,DS], 50/50, 50/50, 50/50
  → Gold: 9→10 | Trinket: Mecha-Jaraxxus Sticker
  → Actions (4): buy_trinket_0, sell_board_3, sell_board_0, sell_board_1

**Sneed**  HP=30 Armor=9 Gold=10 Tier=2

  Board: 1/4, 1/2 [Taunt,DS], 4/1, 3/4, 4/3, 4/3
  Tavern: Humming Bird 1/4 T2 $3 | Humming Bird 1/4 T2 $3 | Tide Raiser 2/1 T2 $3 | Tide Raiser 2/1 T2 $3

  → Board: 1/4, 4/1, 3/4, 4/3, 4/3
  → Gold: 4→5 | Trinket: Comfy Coffin
  → Actions (2): buy_trinket_1, sell_board_1

**Overlord Saurfang**  HP=30 Armor=16 Gold=10 Tier=1

  Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13
  Tavern: 

  → Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13, 5/6
  → Trinket: Manipulator Portrait | Hand: 2→1
  → Actions (2): buy_trinket_3, play_hand_1

**Ysera**  HP=30 Armor=11 Gold=10 Tier=2

  Board: 1/2 [Taunt,DS], 3/6, 18/18 [DS,G], 2/5, 3/4
  Tavern: Alert Alarmist 2/2 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Old Soul 3/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Sleepy Supporter 4/3 T2 $3

  → Gold: 10→7 | Trinket: Mecha-Jaraxxus Sticker
  → Actions (1): buy_trinket_1

**Inge, the Iron Hymn**  HP=30 Armor=6 Gold=10 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/4
  Tavern: Sewer Rat 3/2 T2 $3 | Humming Bird 1/4 T2 $3 | Reef Riffer 3/2 T2 $3 | Humming Bird 1/4 T2 $3

  → Gold: 10→8 | Trinket: Bird Feeder
  → Actions (1): buy_trinket_3

**Professor Putricide**  HP=24 Armor=0 Gold=10 Tier=1

  Board: 4/1, 1/2 [Taunt,DS], 1/4, 1/1
  Tavern: 

  → Board: 4/1, 1/2 [Taunt,DS], 1/4, 1/1
  → Upgrade T1→T2 | Gold: 5→4 | Trinket: Slamma Sticker
  → Actions (2): buy_trinket_2, upgrade

**Sylvanas Windrunner**  HP=19 Armor=0 Gold=10 Tier=1

  Board: 1/2 [Taunt,DS], 4/1, 4/1, 3/2 [DS]
  Tavern: 

  → Board: 1/2 [Taunt,DS], 4/1, 4/1, 3/2 [DS]
  → Upgrade T1→T2 | Gold: 4→3 | Trinket: Fang Anklet
  → Actions (2): buy_trinket_0, upgrade

**Drek'Thar**  HP=30 Armor=3 Gold=10 Tier=1

  Board: 1/2 [Taunt,DS], 3/6, 4/1
  Tavern: 

  → Board: 1/2 [Taunt,DS], 3/6, 4/1
  → Gold: 6→5 | Trinket: Mecha-Jaraxxus Sticker
  → Actions (3): buy_trinket_1, refresh, refresh

**Combat Phase**

  Overlord Saurfang vs Ysera (first: Overlord Saurfang)
     Overlord Saurfang: [9/8, 9/10, 10/12, 16/13, 5/6]
     Ysera: [1/2, 3/6, 18/18, 2/5, 3/4]
     Risen Rider 9/8→9/7  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Risen Rider 9/7→9/6
     Annoy-o-Tron 9/10→9/10  |  Laboratory Assistant 3/4→3/0 DEAD
     Wrath Weaver 3/6→3/0 DEAD  |  Risen Rider 9/6→9/3
     Woodland Defiler 10/12→10/0 DEAD  |  Scarlet Survivor 18/18→18/18
     Scarlet Survivor 18/18→18/9  |  Annoy-o-Tron 9/10→9/0 DEAD
     Manasaber 16/13→16/11  |  Lava Lurker 2/5→2/0 DEAD
     Result: survivors 3 vs 1 — winner: Overlord Saurfang
  Sylvanas Windrunner vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Sylvanas Windrunner: [1/2, 5/2, 5/2, 3/2]
     Yogg-Saron, Hope's End: [1/2, 50/50, 50/50, 50/50, 50/50]
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Amalgam 50/50→50/49  |  Annoy-o-Tron 1/1→1/0 DEAD
     Manasaber 5/2→5/1  |  Annoy-o-Tron 1/1→1/0 DEAD
     Amalgam 50/50→50/45  |  Manasaber 5/2→5/0 DEAD
     Cord Puller 3/2→3/2  |  Amalgam 50/50→50/47
     Amalgam 50/50→50/47  |  Cord Puller 3/2→3/0 DEAD
     Result: survivors 1 vs 4 — winner: Sylvanas Windrunner
  Professor Putricide vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Professor Putricide: [4/1, 1/2, 1/4, 1/1]
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4, 3/4]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 5/6→5/6
     Annoy-o-Tron 5/6→5/5  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 1/4→1/0 DEAD  |  Annoy-o-Tron 5/5→5/4
     Manasaber 8/5→8/4  |  Harmless Bonehead 1/1→1/0 DEAD
     Result: survivors 0 vs 4 — winner: Inge, the Iron Hymn
  Sneed vs Drek'Thar (first: Sneed)
     Sneed: [1/4, 4/1, 3/4, 4/3, 4/3]
     Drek'Thar: [1/2, 3/6, 4/1]
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Old Soul 3/4→3/3
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 3/6→3/2
     Wrath Weaver 3/2→3/1  |  Wrath Weaver 1/3→1/0 DEAD
     Old Soul 3/3→3/0 DEAD  |  Wrath Weaver 3/1→3/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Result: survivors 1 vs 0 — winner: Sneed

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=9, Tier=1) | Sneed (HP=30, Armor=9, Tier=2) | Overlord Saurfang (HP=30, Armor=16, Tier=1) | Ysera (HP=30, Armor=11, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=6, Tier=2) | Drek'Thar (HP=29, Armor=0, Tier=1) | Sylvanas Windrunner (HP=19, Armor=0, Tier=2) | Professor Putricide (HP=16, Armor=0, Tier=2)

### Turn 10

**Yogg-Saron, Hope's End**  HP=30 Armor=9 Gold=10 Tier=1

  Board: 1/2 [Taunt,DS], 50/50, 50/50, 50/50, 50/50, 50/50, 50/50
  Tavern: 

  → Board: 1/2 [Taunt,DS], 50/50, 50/50, 50/50
  → Gold: 13→12
  → Actions (4): sell_board_1, sell_board_1, sell_board_1, refresh

**Sneed**  HP=30 Armor=9 Gold=10 Tier=2

  Board: 1/4, 4/1, 3/4, 4/3, 4/3
  Tavern: Scarlet Skull 2/1 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Sewer Rat 3/2 T2 $3 | Ancestral Automaton 3/4 T2 $3

  → Board: 1/4, 4/1, 3/4, 4/3, 4/3, 3/4
  → Actions (2): buy_tavern_3, play_hand_2

**Overlord Saurfang**  HP=30 Armor=16 Gold=10 Tier=1

  Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13, 5/6
  Tavern: 

  → Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13, 5/6
  → Gold: 10→11 | Hand: 2→1
  → Actions (2): play_hand_1, sell_board_4

**Ysera**  HP=30 Armor=11 Gold=10 Tier=2

  Board: 1/2 [Taunt,DS], 3/6, 18/18 [DS,G], 2/5, 3/4
  Tavern: Eternal Knight 4/2 T2 $3 | Scarlet Skull 2/1 T2 $3 | Eternal Knight 4/2 T2 $3 | Tide Raiser 2/1 T2 $3 | Scarlet Survivor 3/3 T1 $3

  → Board: 1/2 [Taunt,DS], 3/6, 18/18 [DS,G], 2/5, 3/4
  → Gold: 9→8
  → Actions (2): refresh, refresh

**Inge, the Iron Hymn**  HP=30 Armor=6 Gold=10 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/4
  Tavern: Scarlet Skull 2/1 T2 $3 | Tide Raiser 2/1 T2 $3 | Soul Rewinder 4/1 T2 $3 | Metallic Hunter 4/2 T2 $3

  → Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/4, 4/2
  → Actions (2): buy_tavern_3, play_hand_0

**Professor Putricide**  HP=16 Armor=0 Gold=10 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 1/4, 1/1
  Tavern: Eternal Knight 4/2 T2 $3 | Humming Bird 1/4 T2 $3 | Lava Lurker 2/5 T2 $3 | Eternal Knight 4/2 T2 $3

  → Board: 4/1, 1/2 [Taunt,DS], 1/4, 1/1, 2/5
  → Actions (2): buy_tavern_2, play_hand_0

**Sylvanas Windrunner**  HP=19 Armor=0 Gold=10 Tier=2

  Board: 1/2 [Taunt,DS], 4/1, 4/1, 3/2 [DS]
  Tavern: Reef Riffer 3/2 T2 $3 | Lava Lurker 7/11 T2 $3 | Ancestral Automaton 3/54 T2 $3 | Sewer Rat 103/102 T2 $3

  → Board: 1/2 [Taunt,DS], 4/1, 4/1, 3/2 [DS], 103/102
  → Actions (2): buy_tavern_3, play_hand_0

**Drek'Thar**  HP=29 Armor=0 Gold=10 Tier=1

  Board: 1/2 [Taunt,DS], 3/6, 4/1
  Tavern: 


**Combat Phase**

  Ysera vs Sylvanas Windrunner (first: Ysera)
     Ysera: [1/2, 3/6, 18/18, 2/5, 3/4]
     Sylvanas Windrunner: [1/2, 5/2, 5/2, 3/2, 104/103]
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/1→1/0 DEAD
     Manasaber 5/2→5/1  |  Annoy-o-Tron 1/1→1/0 DEAD
     Scarlet Survivor 18/18→18/18  |  Sewer Rat 104/103→104/85
     Manasaber 5/2→5/0 DEAD  |  Scarlet Survivor 18/18→18/13
     Lava Lurker 2/5→2/0 DEAD  |  Sewer Rat 104/85→104/83
     Cord Puller 3/2→3/2  |  Laboratory Assistant 3/4→3/1
     Laboratory Assistant 3/1→3/0 DEAD  |  Sewer Rat 104/83→104/80
     Sewer Rat 104/80→104/62  |  Scarlet Survivor 18/13→18/0 DEAD
     Result: survivors 1 vs 3 — winner: Ysera
  Drek'Thar vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Drek'Thar: [1/2, 3/6, 4/1]
     Yogg-Saron, Hope's End: [1/2, 50/50, 50/50, 50/50]
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Amalgam 50/50→50/49  |  Annoy-o-Tron 1/1→1/0 DEAD
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/1→1/0 DEAD
     Amalgam 50/50→50/46  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 1 vs 3 — winner: Drek'Thar
  Overlord Saurfang vs Professor Putricide (first: Overlord Saurfang)
     Overlord Saurfang: [9/8, 9/10, 10/12, 16/13, 5/6]
     Professor Putricide: [4/1, 1/2, 1/4, 1/1, 2/5]
     Risen Rider 9/8→9/7  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 9/10→9/10
     Annoy-o-Tron 9/10→9/9  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 1/4→1/0 DEAD  |  Risen Rider 9/7→9/6
     Woodland Defiler 10/12→10/10  |  Lava Lurker 2/5→2/0 DEAD
     Harmless Bonehead 1/1→1/0 DEAD  |  Annoy-o-Tron 9/9→9/8
     Result: survivors 5 vs 0 — winner: Overlord Saurfang
  Inge, the Iron Hymn vs Sneed (first: Sneed)
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4, 3/4, 4/2]
     Sneed: [1/4, 4/1, 3/4, 4/3, 4/3, 3/4]
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 5/6→5/2
     Annoy-o-Tron 5/2→5/0 DEAD  |  Old Soul 3/4→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Metallic Hunter 12/10→12/6
     Manasaber 12/9→12/8  |  Wrath Weaver 1/3→1/0 DEAD
     Ancestral Automaton 3/4→3/1  |  Ancestral Automaton 3/12→3/9
     Laboratory Assistant 11/12→11/9  |  Ancestral Automaton 3/1→3/0 DEAD
     Result: survivors 4 vs 0 — winner: Inge, the Iron Hymn

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=9, Tier=1) | Sneed (HP=30, Armor=0, Tier=2) | Overlord Saurfang (HP=30, Armor=16, Tier=1) | Ysera (HP=30, Armor=11, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=6, Tier=2) | Drek'Thar (HP=29, Armor=0, Tier=1) | Sylvanas Windrunner (HP=19, Armor=0, Tier=2) | Professor Putricide (HP=4, Armor=0, Tier=2)

### Turn 11

**Yogg-Saron, Hope's End**  HP=30 Armor=9 Gold=10 Tier=1

  Board: 1/2 [Taunt,DS], 50/50, 50/50, 50/50, 50/50, 50/50
  Tavern: 

  → Board: 1/2 [Taunt,DS], 50/50, 50/50, 50/50
  → Gold: 11→12
  → Actions (2): sell_board_1, sell_board_1

**Sneed**  HP=30 Armor=0 Gold=10 Tier=2

  Board: 1/4, 4/1, 3/4, 4/3, 4/3, 3/4
  Tavern: Metallic Hunter 4/2 T2 $3 | Reef Riffer 3/2 T2 $3 | Reef Riffer 3/2 T2 $3 | Sewer Rat 3/2 T2 $3


**Overlord Saurfang**  HP=30 Armor=16 Gold=10 Tier=1

  Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13, 5/6
  Tavern: 

  → Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13, 5/6
  → Gold: 10→11 | Hand: 2→1
  → Actions (2): play_hand_1, sell_board_4

**Ysera**  HP=30 Armor=11 Gold=10 Tier=2

  Board: 1/2 [Taunt,DS], 3/6, 18/18 [DS,G], 2/5, 3/4
  Tavern: Ancestral Automaton 3/4 T2 $3 | Scarlet Skull 2/1 T2 $3 | Lava Lurker 2/5 T2 $3 | Reef Riffer 3/2 T2 $3 | Sleepy Supporter 4/3 T2 $3

  → Board: 1/2 [Taunt,DS], 3/6, 18/18 [DS,G], 2/5, 3/4
  → Gold: 9→8
  → Actions (2): refresh, refresh

**Inge, the Iron Hymn**  HP=30 Armor=6 Gold=10 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/4, 4/2
  Tavern: Ancestral Automaton 3/4 T2 $3 | Reef Riffer 3/2 T2 $3 | Alert Alarmist 2/2 T2 $3 | Laboratory Assistant 3/4 T2 $3


**Professor Putricide**  HP=4 Armor=0 Gold=10 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 1/4, 1/1, 2/5
  Tavern: Sewer Rat 3/2 T2 $3 | Lava Lurker 2/5 T2 $3 | Metallic Hunter 4/2 T2 $3 | Soul Rewinder 4/1 T2 $3

  → Board: 4/1, 1/2 [Taunt,DS], 1/4, 1/1, 2/5, 2/5, 4/2
  → Gold: 4→1 | Hand: 0→1
  → Actions (5): buy_tavern_1, play_hand_0, buy_tavern_1, play_hand_0, buy_tavern_0

**Sylvanas Windrunner**  HP=19 Armor=0 Gold=10 Tier=2

  Board: 1/2 [Taunt,DS], 4/1, 4/1, 3/2 [DS], 103/102
  Tavern: Soul Rewinder 4/1 T2 $3 | Old Soul 3/4 T2 $3 | Nerubian Deathswarmer 56/60 T2 $3 | Nerubian Deathswarmer 51/54 T2 $3


**Drek'Thar**  HP=29 Armor=0 Gold=10 Tier=1

  Board: 1/2 [Taunt,DS], 3/6, 4/1
  Tavern: 


**Combat Phase**

  Inge, the Iron Hymn vs Drek'Thar (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4, 3/4, 4/2]
     Drek'Thar: [1/2, 3/6, 4/1]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Annoy-o-Tron 5/6→5/6
     Annoy-o-Tron 5/6→5/2  |  Manasaber 4/1→4/0 DEAD
     Wrath Weaver 3/6→3/1  |  Annoy-o-Tron 5/2→5/0 DEAD
     Manasaber 12/9→12/6  |  Wrath Weaver 3/1→3/0 DEAD
     Result: survivors 4 vs 0 — winner: Inge, the Iron Hymn
  Sylvanas Windrunner vs Overlord Saurfang (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [1/2, 5/2, 5/2, 3/2, 104/103]
     Overlord Saurfang: [9/8, 9/10, 10/12, 16/13, 5/6]
     Annoy-o-Tron 1/2→1/2  |  Risen Rider 9/8→9/7
     Risen Rider 9/7→9/6  |  Annoy-o-Tron 1/2→1/0 DEAD
     Manasaber 5/2→5/0 DEAD  |  Risen Rider 9/6→9/1
     Annoy-o-Tron 9/10→9/10  |  Cord Puller 3/2→3/2
     Manasaber 5/2→5/0 DEAD  |  Risen Rider 9/1→9/0 DEAD
     Woodland Defiler 10/12→10/0 DEAD  |  Sewer Rat 104/103→104/93
     Cord Puller 3/2→3/0 DEAD  |  Annoy-o-Tron 9/10→9/7
     Manasaber 16/13→16/0 DEAD  |  Sewer Rat 104/93→104/77
     Sewer Rat 104/77→104/68  |  Annoy-o-Tron 9/7→9/0 DEAD
     Woodland Defiler 5/6→5/0 DEAD  |  Sewer Rat 104/68→104/63
     Result: survivors 1 vs 0 — winner: Sylvanas Windrunner
  Sneed vs Professor Putricide (first: Professor Putricide)
     Sneed: [1/4, 4/1, 3/4, 4/3, 4/3, 3/4]
     Professor Putricide: [4/1, 1/2, 1/4, 1/1, 2/5, 2/5, 4/2]
     Manasaber 4/1→4/0 DEAD  |  Wrath Weaver 1/4→1/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Shell Collector 4/3→4/2
     Old Soul 3/4→3/2  |  Lava Lurker 2/5→2/2
     Wrath Weaver 1/4→1/1  |  Old Soul 3/2→3/1
     Shell Collector 4/2→4/1  |  Wrath Weaver 1/1→1/0 DEAD
     Harmless Bonehead 1/1→1/0 DEAD  |  Shell Collector 4/3→4/2
     Shell Collector 4/2→4/0 DEAD  |  Lava Lurker 2/2→2/0 DEAD
     Lava Lurker 2/5→2/1  |  Shell Collector 4/1→4/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Result: survivors 1 vs 1 — winner: Sneed
  Yogg-Saron, Hope's End vs Ysera (first: Yogg-Saron, Hope's End)
     Yogg-Saron, Hope's End: [1/2, 50/50, 50/50, 50/50, 50/50, 50/50, 50/50]
     Ysera: [1/2, 3/6, 18/18, 2/5, 3/4]
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Amalgam 50/50→50/49  |  Annoy-o-Tron 1/1→1/0 DEAD
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/1→1/0 DEAD
     Amalgam 50/50→50/47  |  Laboratory Assistant 3/4→3/0 DEAD
     Scarlet Survivor 18/18→18/18  |  Amalgam 50/49→50/31
     Amalgam 50/50→50/47  |  Wrath Weaver 3/5→3/0 DEAD
     Lava Lurker 2/5→2/0 DEAD  |  Amalgam 50/50→50/48
     Amalgam 50/48→50/30  |  Scarlet Survivor 18/18→18/0 DEAD
     Result: survivors 6 vs 0 — winner: Yogg-Saron, Hope's End

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=9, Tier=1) | Sneed (HP=30, Armor=0, Tier=2) | Overlord Saurfang (HP=30, Armor=12, Tier=1) | Ysera (HP=30, Armor=10, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=6, Tier=2) | Drek'Thar (HP=20, Armor=0, Tier=1) | Sylvanas Windrunner (HP=19, Armor=0, Tier=2) | Professor Putricide (HP=4, Armor=0, Tier=2)

### Turn 12

**Yogg-Saron, Hope's End**  HP=30 Armor=9 Gold=10 Tier=1

  Board: 1/2 [Taunt,DS], 50/50, 50/50, 50/50, 50/50, 50/50, 50/50
  Tavern: 

  → Board: 1/2 [Taunt,DS], 50/50, 50/50, 50/50
  → Gold: 13→12
  → Actions (4): sell_board_1, sell_board_1, sell_board_1, refresh

**Sneed**  HP=30 Armor=0 Gold=10 Tier=2

  Board: 1/4, 4/1, 3/4, 4/3, 4/3, 3/4
  Tavern: Shell Collector 4/3 T2 $3 | Old Soul 3/4 T2 $3 | Tide Raiser 2/1 T2 $3 | Laboratory Assistant 3/4 T2 $3


**Overlord Saurfang**  HP=30 Armor=12 Gold=10 Tier=1

  Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13, 5/6
  Tavern: 

  → Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13, 5/6
  → Gold: 10→11 | Hand: 2→1
  → Actions (2): play_hand_1, sell_board_4

**Ysera**  HP=30 Armor=10 Gold=10 Tier=2

  Board: 1/2 [Taunt,DS], 3/6, 18/18 [DS,G], 2/5, 3/4
  Tavern: Shell Collector 4/3 T2 $3 | Lava Lurker 2/5 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Old Soul 3/4 T2 $3 | Sleepy Supporter 4/3 T2 $3

  → Board: 1/2 [Taunt,DS], 3/6, 18/18 [DS,G], 2/5, 3/4
  → Gold: 9→8
  → Actions (2): refresh, refresh

**Inge, the Iron Hymn**  HP=30 Armor=6 Gold=10 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/4, 4/2
  Tavern: Scarlet Skull 2/1 T2 $3 | Shell Collector 4/3 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Lava Lurker 2/5 T2 $3


**Professor Putricide**  HP=4 Armor=0 Gold=10 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 1/4, 1/1, 2/5, 2/5, 4/2
  Tavern: Tide Raiser 2/1 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Humming Bird 1/4 T2 $3 | Laboratory Assistant 3/4 T2 $3

  → Board: 4/1, 1/2 [Taunt,DS], 1/4, 1/1, 2/5, 2/5, 4/2
  → Gold: 1→0 | Hand: 2→5
  → Actions (4): buy_tavern_3, buy_tavern_1, buy_tavern_1, refresh

**Sylvanas Windrunner**  HP=19 Armor=0 Gold=10 Tier=2

  Board: 1/2 [Taunt,DS], 4/1, 4/1, 3/2 [DS], 103/102
  Tavern: Laboratory Assistant 3/4 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Nerubian Deathswarmer 6/10 T2 $3 | Old Soul 153/154 T2 $3


**Drek'Thar**  HP=20 Armor=0 Gold=10 Tier=1

  Board: 1/2 [Taunt,DS], 3/6, 4/1
  Tavern: 

  → Board: 1/2 [Taunt,DS], 3/6, 4/1
  → Upgrade T1→T3 | Gold: 2→1
  → Actions (3): upgrade, upgrade, refresh

**Combat Phase**

  Overlord Saurfang vs Drek'Thar (first: Overlord Saurfang)
     Overlord Saurfang: [9/8, 9/10, 10/12, 16/13, 5/6]
     Drek'Thar: [1/2, 3/6, 4/1]
     Risen Rider 9/8→9/7  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Annoy-o-Tron 9/10→9/10
     Annoy-o-Tron 9/10→9/6  |  Manasaber 4/1→4/0 DEAD
     Wrath Weaver 3/6→3/0 DEAD  |  Annoy-o-Tron 9/6→9/3
     Result: survivors 5 vs 0 — winner: Overlord Saurfang
  Sneed vs Sylvanas Windrunner (first: Sneed)
     Sneed: [1/4, 4/1, 3/4, 4/3, 4/3, 3/4]
     Sylvanas Windrunner: [1/2, 5/2, 5/2, 3/2, 104/103]
     Wrath Weaver 1/4→1/3  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Ancestral Automaton 3/4→3/3
     Manasaber 4/1→4/0 DEAD  |  Manasaber 5/2→5/0 DEAD
     Manasaber 5/2→5/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Old Soul 3/4→3/1  |  Cord Puller 3/2→3/2
     Cord Puller 3/2→3/0 DEAD  |  Ancestral Automaton 3/3→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Sewer Rat 104/103→104/99
     Sewer Rat 104/99→104/98  |  Wrath Weaver 1/3→1/0 DEAD
     Result: survivors 1 vs 1 — winner: Sneed
  Professor Putricide vs Inge, the Iron Hymn (first: Professor Putricide)
     Professor Putricide: [4/1, 1/2, 1/4, 1/1, 2/5, 2/5, 4/2]
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4, 3/4, 4/2]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Annoy-o-Tron 5/6→5/5
     Annoy-o-Tron 5/5→5/4  |  Wrath Weaver 1/4→1/0 DEAD
     Harmless Bonehead 1/1→1/0 DEAD  |  Annoy-o-Tron 5/4→5/3
     Manasaber 8/5→8/3  |  Lava Lurker 2/5→2/0 DEAD
     Lava Lurker 2/5→2/0 DEAD  |  Annoy-o-Tron 5/3→5/1
     Laboratory Assistant 7/8→7/4  |  Metallic Hunter 4/2→4/0 DEAD
     Result: survivors 0 vs 5 — winner: Inge, the Iron Hymn
  Ysera vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Ysera: [1/2, 3/6, 18/18, 2/5, 3/4]
     Yogg-Saron, Hope's End: [1/2, 50/50, 50/50, 50/50, 50/50, 50/50, 50/50]
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Amalgam 50/50→50/49  |  Annoy-o-Tron 1/1→1/0 DEAD
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/1→1/0 DEAD
     Amalgam 50/50→50/47  |  Laboratory Assistant 3/4→3/0 DEAD
     Scarlet Survivor 18/18→18/18  |  Amalgam 50/50→50/32
     Amalgam 50/32→50/30  |  Lava Lurker 2/5→2/0 DEAD
     Result: survivors 2 vs 6 — winner: Ysera

  **Professor Putricide eliminated!** (HP=0, Turn 12)
  Alive: 7/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=9, Tier=1) | Sneed (HP=30, Armor=0, Tier=2) | Overlord Saurfang (HP=30, Armor=12, Tier=1) | Ysera (HP=30, Armor=10, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=6, Tier=2) | Sylvanas Windrunner (HP=19, Armor=0, Tier=2) | Drek'Thar (HP=8, Armor=0, Tier=3)

### Turn 13

**Yogg-Saron, Hope's End**  HP=30 Armor=9 Gold=10 Tier=1

  Board: 1/2 [Taunt,DS], 50/50, 50/50, 50/50, 50/50, 50/50, 50/50
  Tavern: 

  → Board: 1/2 [Taunt,DS], 50/50, 50/50, 50/50
  → Gold: 13→12
  → Actions (4): sell_board_1, sell_board_1, sell_board_1, refresh

**Sneed**  HP=30 Armor=0 Gold=10 Tier=2

  Board: 1/4, 4/1, 3/4, 4/3, 4/3, 3/4
  Tavern: Alert Alarmist 2/2 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Old Soul 3/4 T2 $3 | Lava Lurker 2/5 T2 $3


**Overlord Saurfang**  HP=30 Armor=12 Gold=10 Tier=1

  Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13, 5/6
  Tavern: 

  → Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13, 5/6
  → Gold: 10→11 | Hand: 2→1
  → Actions (2): play_hand_1, sell_board_4

**Ysera**  HP=30 Armor=10 Gold=10 Tier=2

  Board: 1/2 [Taunt,DS], 3/6, 18/18 [DS,G], 2/5, 3/4
  Tavern: Shell Collector 4/3 T2 $3 | Old Soul 3/4 T2 $3 | Humming Bird 1/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Twilight Hatchling 1/1 T1 $3

  → Board: 1/2 [Taunt,DS], 3/6, 18/18 [DS,G], 2/5, 3/4
  → Gold: 9→8
  → Actions (2): refresh, refresh

**Inge, the Iron Hymn**  HP=30 Armor=6 Gold=10 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/4, 4/2
  Tavern: Lava Lurker 2/5 T2 $3 | Soul Rewinder 4/1 T2 $3 | Sewer Rat 3/2 T2 $3 | Reef Riffer 3/2 T2 $3


**Sylvanas Windrunner**  HP=19 Armor=0 Gold=10 Tier=2

  Board: 1/2 [Taunt,DS], 4/1, 4/1, 3/2 [DS], 103/102
  Tavern: Shell Collector 54/53 T2 $3 | Scarlet Skull 2/1 T2 $3 | Ancestral Automaton 3/10 T2 $3 | Humming Bird 101/104 T2 $3


**Drek'Thar**  HP=8 Armor=0 Gold=10 Tier=3

  Board: 1/2 [Taunt,DS], 3/6, 4/1
  Tavern: Hardy Orca 1/6 T3 $3 | Deep Blue Crooner 2/2 T3 $3 | Handless Forsaken 2/1 T3 $3 | Hardy Orca 1/6 T3 $3 | Overconfidence (spell) T3 $1

  → Board: 3/6, 1/6 [Taunt]
  → Upgrade T3→T4
  → Actions (5): upgrade, sell_board_2, sell_board_0, buy_tavern_0, play_hand_0

**Combat Phase**

  Overlord Saurfang vs Sneed (first: Sneed)
     Overlord Saurfang: [9/8, 9/10, 10/12, 16/13, 5/6]
     Sneed: [1/4, 4/1, 3/4, 4/3, 4/3, 3/4]
     Wrath Weaver 1/4→1/0 DEAD  |  Annoy-o-Tron 9/10→9/10
     Risen Rider 9/8→9/4  |  Shell Collector 4/3→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 9/10→9/6
     Annoy-o-Tron 9/6→9/3  |  Old Soul 3/4→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Annoy-o-Tron 9/3→9/0 DEAD
     Woodland Defiler 10/12→10/9  |  Ancestral Automaton 3/4→3/0 DEAD
     Result: survivors 4 vs 0 — winner: Overlord Saurfang
  Drek'Thar vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Drek'Thar: [3/6, 1/6]
     Yogg-Saron, Hope's End: [1/2, 50/50, 50/50, 50/50, 50/50]
     Annoy-o-Tron 1/2→1/2  |  Hardy Orca 1/6→1/5
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/2→1/0 DEAD
     Amalgam 50/50→50/49  |  Hardy Orca 1/5→1/0 DEAD
     Result: survivors 1 vs 4 — winner: Drek'Thar
  Inge, the Iron Hymn vs Ysera (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4, 3/4, 4/2]
     Ysera: [1/2, 3/6, 18/18, 2/5, 3/4]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Annoy-o-Tron 5/6→5/6
     Annoy-o-Tron 5/6→5/3  |  Laboratory Assistant 3/4→3/0 DEAD
     Wrath Weaver 3/6→3/1  |  Annoy-o-Tron 5/3→5/0 DEAD
     Manasaber 12/9→12/6  |  Wrath Weaver 3/1→3/0 DEAD
     Scarlet Survivor 18/18→18/18  |  Laboratory Assistant 11/12→11/0 DEAD
     Ancestral Automaton 3/16→3/14  |  Lava Lurker 2/5→2/2
     Lava Lurker 2/2→2/0 DEAD  |  Metallic Hunter 16/14→16/12
     Metallic Hunter 16/12→16/0 DEAD  |  Scarlet Survivor 18/18→18/2
     Result: survivors 2 vs 1 — winner: Inge, the Iron Hymn

  Alive: 7/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=9, Tier=1) | Overlord Saurfang (HP=30, Armor=12, Tier=1) | Ysera (HP=30, Armor=10, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=6, Tier=2) | Sneed (HP=19, Armor=0, Tier=2) | Sylvanas Windrunner (HP=19, Armor=0, Tier=2) | Drek'Thar (HP=8, Armor=0, Tier=4)

### Turn 14

**Yogg-Saron, Hope's End**  HP=30 Armor=9 Gold=10 Tier=1

  Board: 1/2 [Taunt,DS], 50/50, 50/50, 50/50, 50/50, 50/50, 50/50
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Manasaber 4/1 T1 $3

  → Board: 1/2 [Taunt,DS], 50/50, 50/50, 50/50
  → Gold: 13→12
  → Actions (4): sell_board_1, sell_board_1, sell_board_1, refresh

**Sneed**  HP=19 Armor=0 Gold=10 Tier=2

  Board: 1/4, 4/1, 3/4, 4/3, 4/3, 3/4
  Tavern: Eternal Knight 4/2 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Lava Lurker 2/5 T2 $3 | Metallic Hunter 4/2 T2 $3

  → Board: 1/4, 4/1, 3/4, 4/3, 4/3, 6/4, 6/4
  → Upgrade T2→T3 | Gold: 7→6
  → Actions (3): buy_tavern_1, play_hand_2, upgrade

**Overlord Saurfang**  HP=30 Armor=12 Gold=10 Tier=1

  Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13, 5/6
  Tavern: 

  → Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13, 5/6
  → Gold: 10→11 | Hand: 2→1
  → Actions (2): play_hand_1, sell_board_4

**Ysera**  HP=30 Armor=10 Gold=10 Tier=2

  Board: 1/2 [Taunt,DS], 3/6, 18/18 [DS,G], 2/5, 3/4
  Tavern: Lava Lurker 2/5 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Eternal Knight 4/2 T2 $3 | Old Soul 3/4 T2 $3 | Sleepy Supporter 4/3 T2 $3

  → Board: 1/2 [Taunt,DS], 3/6, 18/18 [DS,G], 2/5, 3/4
  → Gold: 9→8
  → Actions (2): refresh, refresh

**Inge, the Iron Hymn**  HP=30 Armor=6 Gold=10 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/4, 4/2
  Tavern: Reef Riffer 3/2 T2 $3 | Tide Raiser 2/1 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Soul Rewinder 4/1 T2 $3


**Sylvanas Windrunner**  HP=19 Armor=0 Gold=10 Tier=2

  Board: 1/2 [Taunt,DS], 4/1, 4/1, 3/2 [DS], 103/102
  Tavern: Metallic Hunter 54/52 T2 $3 | Tide Raiser 52/51 T2 $3 | Soul Rewinder 54/51 T2 $3 | Old Soul 8/10 T2 $3


**Drek'Thar**  HP=8 Armor=0 Gold=10 Tier=4

  Board: 3/6, 1/6 [Taunt]
  Tavern: Imposing Percussionist 4/4 T4 $3 | Handless Forsaken 2/1 T3 $3 | Hardy Orca 1/6 T3 $3 | Sly Raptor 1/3 T3 $3 | Prosthetic Hand 3/1 T4 $3 | Forest's Bounty (spell) T4 $3

  → Board: 3/6, 1/6 [Taunt]
  → Upgrade T4→T5 | Gold: 10→2
  → Actions (1): upgrade

**Combat Phase**

  Yogg-Saron, Hope's End vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Yogg-Saron, Hope's End: [1/2, 50/50, 50/50, 50/50]
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4, 3/4, 4/2]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Annoy-o-Tron 5/6→5/6
     Annoy-o-Tron 5/6→5/0 DEAD  |  Amalgam 50/50→50/45
     Amalgam 50/50→50/38  |  Metallic Hunter 12/10→12/0 DEAD
     Manasaber 16/13→16/0 DEAD  |  Amalgam 50/38→50/22
     Amalgam 50/50→50/47  |  Ancestral Automaton 3/20→3/0 DEAD
     Laboratory Assistant 23/24→23/0 DEAD  |  Amalgam 50/22→50/0 DEAD
     Result: survivors 2 vs 0 — winner: Yogg-Saron, Hope's End
  Sneed vs Drek'Thar (first: Sneed)
     Sneed: [1/4, 4/1, 3/4, 4/3, 4/3, 6/4, 6/4]
     Drek'Thar: [3/6, 1/6]
     Wrath Weaver 1/4→1/3  |  Hardy Orca 1/6→1/5
     Wrath Weaver 3/6→3/0 DEAD  |  Ancestral Automaton 6/4→6/1
     Manasaber 4/1→4/0 DEAD  |  Hardy Orca 1/5→1/1
     Hardy Orca 1/1→1/0 DEAD  |  Ancestral Automaton 6/4→6/3
     Result: survivors 6 vs 0 — winner: Sneed
  Sylvanas Windrunner vs Ysera (first: Ysera)
     Sylvanas Windrunner: [1/2, 5/2, 5/2, 3/2, 104/103]
     Ysera: [1/2, 3/6, 18/18, 2/5, 3/4]
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/1→1/0 DEAD
     Manasaber 5/2→5/1  |  Annoy-o-Tron 1/1→1/0 DEAD
     Scarlet Survivor 18/18→18/18  |  Manasaber 5/2→5/0 DEAD
     Cord Puller 3/2→3/2  |  Lava Lurker 2/5→2/2
     Lava Lurker 2/2→2/0 DEAD  |  Manasaber 5/1→5/0 DEAD
     Sewer Rat 104/103→104/85  |  Scarlet Survivor 18/18→18/0 DEAD
     Laboratory Assistant 3/4→3/1  |  Cord Puller 3/2→3/0 DEAD
     Result: survivors 1 vs 2 — winner: Sylvanas Windrunner

  **Drek'Thar eliminated!** (HP=0, Turn 14)
  Alive: 6/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=9, Tier=1) | Overlord Saurfang (HP=30, Armor=12, Tier=1) | Ysera (HP=30, Armor=10, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=5, Tier=2) | Sneed (HP=19, Armor=0, Tier=3) | Sylvanas Windrunner (HP=19, Armor=0, Tier=2)

### Turn 15

**Yogg-Saron, Hope's End**  HP=30 Armor=9 Gold=10 Tier=1

  Board: 1/2 [Taunt,DS], 50/50, 50/50, 50/50, 50/50
  Tavern: 

  → Board: 1/2 [Taunt,DS], 50/50, 50/50, 50/50
  → Gold: 10→11
  → Actions (1): sell_board_1

**Sneed**  HP=19 Armor=0 Gold=10 Tier=3

  Board: 1/4, 4/1, 3/4, 4/3, 4/3, 6/4, 6/4
  Tavern: Sly Raptor 1/3 T3 $3 | Technical Element 5/6 T3 $3 | Dustbone Devastator 2/6 T3 $3 | Accord-o-Tron 3/3 T3 $3 | Robust Evolution (spell) T3 $1

  → Board: 1/4, 4/1, 3/4, 4/3, 4/3, 6/4, 6/4
  → Gold: 7→4 | Hand: 2→4
  → Actions (2): buy_tavern_1, buy_tavern_1

**Overlord Saurfang**  HP=30 Armor=12 Gold=10 Tier=1

  Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13, 5/6
  Tavern: 

  → Board: 9/8 [Taunt,Reborn], 9/10 [Taunt,DS], 10/12 [G], 16/13, 5/6
  → Gold: 10→11 | Hand: 2→1
  → Actions (2): play_hand_1, sell_board_4

**Ysera**  HP=30 Armor=10 Gold=10 Tier=2

  Board: 1/2 [Taunt,DS], 3/6, 18/18 [DS,G], 2/5, 3/4
  Tavern: Sewer Rat 3/2 T2 $3 | Alert Alarmist 2/2 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Old Soul 3/4 T2 $3 | Blazing Skyfin 2/4 T2 $3

  → Board: 1/2 [Taunt,DS], 3/6, 18/18 [DS,G], 2/5, 3/4
  → Gold: 9→8
  → Actions (2): refresh, refresh

**Inge, the Iron Hymn**  HP=30 Armor=5 Gold=10 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/4, 4/2
  Tavern: Reef Riffer 3/2 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Tide Raiser 2/1 T2 $3 | Laboratory Assistant 3/4 T2 $3

  → Board: 4/1, 1/2 [Taunt,DS], 4/1, 3/4, 3/4, 4/2, 3/4
  → Upgrade T2→T3 | Gold: 7→6
  → Actions (3): buy_tavern_3, play_hand_2, upgrade

**Sylvanas Windrunner**  HP=19 Armor=0 Gold=10 Tier=2

  Board: 1/2 [Taunt,DS], 4/1, 4/1, 3/2 [DS], 103/102
  Tavern: Metallic Hunter 54/52 T2 $3 | Tide Raiser 7/7 T2 $3 | Sewer Rat 3/2 T2 $3 | Alert Alarmist 2/2 T2 $3


**Combat Phase**

  Inge, the Iron Hymn vs Sylvanas Windrunner (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 4/1, 3/4, 3/4, 4/2, 3/4]
     Sylvanas Windrunner: [1/2, 5/2, 5/2, 3/2, 104/103]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Annoy-o-Tron 5/6→5/6
     Annoy-o-Tron 5/6→5/3  |  Cord Puller 3/2→3/2
     Manasaber 5/2→5/0 DEAD  |  Annoy-o-Tron 5/3→5/0 DEAD
     Manasaber 12/9→12/6  |  Cord Puller 3/2→3/0 DEAD
     Manasaber 5/2→5/0 DEAD  |  Laboratory Assistant 11/12→11/7
     Laboratory Assistant 11/7→11/0 DEAD  |  Sewer Rat 104/103→104/92
     Sewer Rat 104/92→104/77  |  Laboratory Assistant 15/16→15/0 DEAD
     Ancestral Automaton 3/20→3/0 DEAD  |  Sewer Rat 104/77→104/74
     Result: survivors 2 vs 1 — winner: Inge, the Iron Hymn
  Ysera vs Yogg-Saron, Hope's End (first: Ysera)
     Ysera: [1/2, 3/6, 18/18, 2/5, 3/4]
     Yogg-Saron, Hope's End: [1/2, 50/50, 50/50, 50/50, 50/50]
     Annoy-o-Tron 1/2→1/2  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Annoy-o-Tron 1/2→1/1
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/1→1/0 DEAD
     Amalgam 50/50→50/49  |  Annoy-o-Tron 1/1→1/0 DEAD
     Scarlet Survivor 18/18→18/18  |  Amalgam 50/50→50/32
     Amalgam 50/50→50/32  |  Scarlet Survivor 18/18→18/0 DEAD
     Lava Lurker 2/5→2/0 DEAD  |  Amalgam 50/32→50/30
     Amalgam 50/50→50/47  |  Laboratory Assistant 3/4→3/0 DEAD
     Result: survivors 1 vs 4 — winner: Ysera
  Overlord Saurfang vs Sneed (first: Sneed)
     Overlord Saurfang: [9/8, 9/10, 10/12, 16/13, 5/6]
     Sneed: [1/4, 4/1, 3/4, 4/3, 4/3, 6/4, 6/4]
     Wrath Weaver 1/4→1/0 DEAD  |  Annoy-o-Tron 9/10→9/10
     Risen Rider 9/8→9/4  |  Shell Collector 4/3→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 9/10→9/6
     Annoy-o-Tron 9/6→9/3  |  Old Soul 3/4→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Annoy-o-Tron 9/3→9/0 DEAD
     Woodland Defiler 10/12→10/6  |  Ancestral Automaton 6/4→6/0 DEAD
     Ancestral Automaton 6/4→6/0 DEAD  |  Risen Rider 9/4→9/0 DEAD
     Result: survivors 3 vs 0 — winner: Overlord Saurfang

  Alive: 6/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=9, Tier=1) | Overlord Saurfang (HP=30, Armor=12, Tier=1) | Ysera (HP=30, Armor=10, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=5, Tier=3) | Sylvanas Windrunner (HP=19, Armor=0, Tier=2) | Sneed (HP=9, Armor=0, Tier=3)

---

## Final Standings

| # | Hero | HP | Armor | Alive | Eliminated Turn |
|---|---|---|---|---|
| 1 | Yogg-Saron, Hope's End | 30 | 9 | Yes | — |
| 2 | Overlord Saurfang | 30 | 12 | Yes | — |
| 3 | Ysera | 30 | 10 | Yes | — |
| 4 | Inge, the Iron Hymn | 30 | 5 | Yes | — |
| 5 | Sylvanas Windrunner | 19 | 0 | Yes | — |
| 6 | Sneed | 9 | 0 | Yes | — |
| 7 | Drek'Thar | 0 | 0 | No | 14 |
| 8 | Professor Putricide | 0 | 0 | No | 12 |

---

## Agent Strategy

**SearchAgent (greedy)** with GameValueNetwork evaluates each legal action by:

1. Simulate action forward (buy, sell, play, upgrade, refresh, freeze, hero power)
2. Encode resulting POMDP state (61-dim: board embedding + own stats + opponent stats)
3. Evaluate V(s') with GameValueNetwork (MSE-trained to predict expected placement)
4. Choose action with highest V(s'); end turn if no action improves baseline

This is a one-step greedy lookahead using learned value function —
no multi-step planning, no opponent modeling, no combat simulation at decision time.