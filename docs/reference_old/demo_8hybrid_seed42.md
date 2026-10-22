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
  → Gold: 1→0
  → Actions (3): buy_tavern_0, play_hand_0, refresh

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
  → Gold: 1→0 | Armor: 18→17
  → Actions (3): buy_tavern_0, play_hand_0, refresh

**Ysera**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 3/3
  Tavern: Harmless Bonehead 1/1 T1 $3 | Manasaber 4/1 T1 $3 | Ominous Seer 2/1 T1 $3 | Fortify (spell) T1 $1 | Scarlet Survivor 3/3 T1 $3

  → Board: 3/3, 3/3
  → Gold: 1→0
  → Actions (3): buy_tavern_4, play_hand_0, refresh

**Inge, the Iron Hymn**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 4/1
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Ominous Seer 2/1 T1 $3 | Picky Eater 1/1 T1 $3 | Sick Riffs (spell) T1 $3

  → Board: 4/1, 1/2 [Taunt,DS]
  → Gold: 1→0
  → Actions (3): buy_tavern_0, play_hand_0, refresh

**Professor Putricide**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 4/1
  Tavern: Cord Puller 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Manasaber 4/1 T1 $3 | Undersea Mount (spell) T1 $3

  → Board: 4/1, 4/1
  → Gold: 1→0
  → Actions (3): buy_tavern_2, play_hand_0, refresh

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
  → Gold: 1→0
  → Actions (3): buy_tavern_0, play_hand_0, refresh

**Combat Phase**

  Ysera vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Ysera: [3/3, 3/3]
     Inge, the Iron Hymn: [4/1, 1/2]
     Manasaber 4/1→4/0 DEAD  |  Scarlet Survivor 3/3→3/0 DEAD
     Scarlet Survivor 3/3→3/2  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Scarlet Survivor 3/2→3/1
     Result: survivors 1 vs 0 — winner: Ysera
  Overlord Saurfang vs Sneed (first: Sneed)
     Overlord Saurfang: [4/7, 4/7]
     Sneed: [2/1, 4/1]
     Ominous Seer 2/1→2/0 DEAD  |  Wrath Weaver 4/7→4/5
     Wrath Weaver 4/7→4/3  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 2 vs 0 — winner: Overlord Saurfang
  Professor Putricide vs Sylvanas Windrunner (first: Professor Putricide)
     Professor Putricide: [4/1, 4/1]
     Sylvanas Windrunner: [2/1, 1/1]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Cord Puller 1/1→1/1  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 0 vs 1 — winner: Sylvanas Windrunner
  Yogg-Saron, Hope's End vs Drek'Thar (first: Yogg-Saron, Hope's End)
     Yogg-Saron, Hope's End: [4/1, 1/4]
     Drek'Thar: [2/1, 1/4]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 1/4→1/3  |  Wrath Weaver 1/4→1/3
     Wrath Weaver 1/3→1/2  |  Wrath Weaver 1/3→1/2
     Result: survivors 1 vs 1 — winner: Yogg-Saron, Hope's End

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=18, Tier=1) | Sneed (HP=30, Armor=9, Tier=1) | Overlord Saurfang (HP=30, Armor=17, Tier=1) | Ysera (HP=30, Armor=12, Tier=1) | Inge, the Iron Hymn (HP=30, Armor=10, Tier=1) | Professor Putricide (HP=30, Armor=8, Tier=1) | Sylvanas Windrunner (HP=30, Armor=10, Tier=1) | Drek'Thar (HP=30, Armor=10, Tier=1)

### Turn 3

**Yogg-Saron, Hope's End**  HP=30 Armor=18 Gold=5 Tier=1

  Board: 4/1, 1/4
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Picky Eater 1/1 T1 $3 | Harmless Bonehead 1/1 T1 $3

  → Board: 4/1, 1/4, 1/2 [Taunt,DS]
  → Gold: 1→0
  → Actions (4): buy_tavern_0, play_hand_0, refresh, refresh

**Sneed**  HP=30 Armor=9 Gold=5 Tier=1

  Board: 2/1, 4/1
  Tavern: Wrath Weaver 1/4 T1 $3 | Manasaber 4/1 T1 $3 | Risen Rider 2/1 T1 $3

  → Board: 2/1, 4/1, 1/4
  → Gold: 1→0
  → Actions (4): buy_tavern_0, play_hand_0, refresh, refresh

**Overlord Saurfang**  HP=30 Armor=17 Gold=5 Tier=1

  Board: 4/7, 4/7
  Tavern: Cord Puller 6/6 T1 $3 | Wrath Weaver 6/9 T1 $3 | Surf n' Surf 6/6 T1 $3

  → Board: 13/19 [G]
  → Gold: 1→0 | Hand: 0→1
  → Actions (4): buy_tavern_1, play_hand_0, refresh, refresh

**Ysera**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 3/3, 3/3
  Tavern: Risen Rider 2/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Ominous Seer 2/1 T1 $3 | Twilight Hatchling 1/1 T1 $3

  → Board: 3/3, 3/3, 2/1 [Taunt,Reborn]
  → Gold: 1→0
  → Actions (4): buy_tavern_0, play_hand_0, refresh, refresh

**Inge, the Iron Hymn**  HP=30 Armor=10 Gold=5 Tier=1

  Board: 4/1, 1/2 [Taunt,DS]
  Tavern: Cord Puller 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Wrath Weaver 1/4 T1 $3

  → Board: 4/1, 1/2 [Taunt,DS], 1/4
  → Gold: 1→0
  → Actions (4): buy_tavern_2, play_hand_0, refresh, refresh

**Professor Putricide**  HP=30 Armor=8 Gold=5 Tier=1

  Board: 4/1, 4/1
  Tavern: Cord Puller 1/1 T1 $3 | Picky Eater 1/1 T1 $3 | Cord Puller 1/1 T1 $3

  → Board: 4/1, 4/1, 1/1 [DS]
  → Gold: 1→0
  → Actions (4): buy_tavern_0, play_hand_0, refresh, refresh

**Sylvanas Windrunner**  HP=30 Armor=10 Gold=5 Tier=1

  Board: 2/1 [Taunt,Reborn], 1/1 [DS]
  Tavern: Surf n' Surf 1/1 T1 $3 | Cord Puller 1/1 T1 $3 | Picky Eater 1/1 T1 $3

  → Board: 2/1 [Taunt,Reborn], 1/1 [DS], 1/1
  → Gold: 1→0
  → Actions (4): buy_tavern_0, play_hand_0, refresh, refresh

**Drek'Thar**  HP=30 Armor=10 Gold=5 Tier=1

  Board: 2/1 [Taunt,Reborn], 1/4
  Tavern: Risen Rider 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3

  → Board: 2/1 [Taunt,Reborn], 1/4, 2/1 [Taunt,Reborn]
  → Gold: 1→0
  → Actions (4): buy_tavern_0, play_hand_0, refresh, refresh

**Combat Phase**

  Professor Putricide vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Professor Putricide: [4/1, 4/1, 1/1]
     Inge, the Iron Hymn: [4/1, 1/2, 1/4]
     Manasaber 4/1→4/0 DEAD  |  Cord Puller 1/1→1/1
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Cord Puller 1/1→1/0 DEAD  |  Wrath Weaver 1/4→1/3
     Result: survivors 0 vs 1 — winner: Inge, the Iron Hymn
  Sneed vs Drek'Thar (first: Drek'Thar)
     Sneed: [2/1, 4/1, 1/4]
     Drek'Thar: [2/1, 1/4, 2/1]
     Risen Rider 2/1→2/0 DEAD  |  Wrath Weaver 1/4→1/2
     Ominous Seer 2/1→2/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 1/4→1/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Result: survivors 1 vs 0 — winner: Sneed
  Overlord Saurfang vs Sylvanas Windrunner (first: Sylvanas Windrunner)
     Overlord Saurfang: [13/19]
     Sylvanas Windrunner: [2/1, 1/1, 1/1]
     Risen Rider 2/1→2/0 DEAD  |  Wrath Weaver 13/19→13/17
     Wrath Weaver 13/17→13/16  |  Cord Puller 1/1→1/1
     Cord Puller 1/1→1/0 DEAD  |  Wrath Weaver 13/16→13/15
     Result: survivors 1 vs 1 — winner: Overlord Saurfang
  Yogg-Saron, Hope's End vs Ysera (first: Ysera)
     Yogg-Saron, Hope's End: [4/1, 1/4, 1/2]
     Ysera: [3/3, 3/3, 2/1]
     Scarlet Survivor 3/3→3/2  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Scarlet Survivor 3/3→3/2  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 1/4→1/1  |  Scarlet Survivor 3/2→3/1
     Result: survivors 1 vs 2 — winner: Yogg-Saron, Hope's End

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=18, Tier=1) | Sneed (HP=30, Armor=9, Tier=1) | Overlord Saurfang (HP=30, Armor=17, Tier=1) | Ysera (HP=30, Armor=12, Tier=1) | Inge, the Iron Hymn (HP=30, Armor=10, Tier=1) | Professor Putricide (HP=30, Armor=6, Tier=1) | Sylvanas Windrunner (HP=30, Armor=10, Tier=1) | Drek'Thar (HP=30, Armor=8, Tier=1)

### Turn 4

**Yogg-Saron, Hope's End**  HP=30 Armor=18 Gold=6 Tier=1

  Board: 4/1, 1/4, 1/2 [Taunt,DS]
  Tavern: 

  → Board: 4/1, 3/6, 1/2 [Taunt,DS], 4/1
  → Upgrade T1→T2 | Gold: 1→0 | Armor: 18→17
  → Actions (5): upgrade, refresh, buy_tavern_0, play_hand_0, refresh

**Sneed**  HP=30 Armor=9 Gold=6 Tier=1

  Board: 2/1, 4/1, 1/4
  Tavern: 

  → Board: 2/1, 4/1, 3/6, 3/4
  → Upgrade T1→T2 | Gold: 1→0 | Armor: 9→8
  → Actions (5): upgrade, refresh, buy_tavern_1, play_hand_0, refresh

**Overlord Saurfang**  HP=30 Armor=17 Gold=6 Tier=1

  Board: 13/19 [G]
  Tavern: 

  → Board: 13/19 [G], 11/10
  → Upgrade T1→T2 | Gold: 1→0 | Hand: 1→2
  → Actions (5): upgrade, refresh, buy_tavern_2, play_hand_1, refresh

**Ysera**  HP=30 Armor=12 Gold=6 Tier=1

  Board: 3/3, 3/3, 2/1 [Taunt,Reborn]
  Tavern: Twilight Hatchling 1/1 T1 $3

  → Board: 3/3, 3/3, 2/1 [Taunt,Reborn], 1/1
  → Upgrade T1→T2 | Gold: 1→0
  → Actions (5): buy_tavern_0, play_hand_0, upgrade, refresh, refresh

**Inge, the Iron Hymn**  HP=30 Armor=10 Gold=6 Tier=1

  Board: 4/1, 1/2 [Taunt,DS], 1/4
  Tavern: 

  → Board: 4/1, 1/2 [Taunt,DS], 3/6, 3/4
  → Upgrade T1→T2 | Gold: 1→0 | Armor: 10→9
  → Actions (5): upgrade, refresh, buy_tavern_0, play_hand_0, refresh

**Professor Putricide**  HP=30 Armor=6 Gold=6 Tier=1

  Board: 4/1, 4/1, 1/1 [DS]
  Tavern: 

  → Board: 4/1, 4/1, 1/1 [DS], 3/4
  → Upgrade T1→T2 | Gold: 1→0
  → Actions (5): upgrade, refresh, buy_tavern_1, play_hand_0, refresh

**Sylvanas Windrunner**  HP=30 Armor=10 Gold=6 Tier=1

  Board: 2/1 [Taunt,Reborn], 1/1 [DS], 1/1
  Tavern: 

  → Board: 2/1 [Taunt,Reborn], 1/1 [DS], 1/1, 3/4
  → Upgrade T1→T2 | Gold: 1→0
  → Actions (5): upgrade, refresh, buy_tavern_0, play_hand_1, refresh

**Drek'Thar**  HP=30 Armor=8 Gold=6 Tier=1

  Board: 2/1 [Taunt,Reborn], 1/4, 2/1 [Taunt,Reborn]
  Tavern: 

  → Board: 2/1 [Taunt,Reborn], 1/4, 2/1 [Taunt,Reborn], 3/4
  → Upgrade T1→T2 | Gold: 1→0
  → Actions (5): upgrade, refresh, buy_tavern_0, play_hand_0, refresh

**Combat Phase**

  Ysera vs Professor Putricide (first: Professor Putricide)
     Ysera: [3/3, 3/3, 2/1, 1/1]
     Professor Putricide: [4/1, 4/1, 1/1, 3/4]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Scarlet Survivor 3/3→3/0 DEAD  |  Ancestral Automaton 3/4→3/1
     Manasaber 4/1→4/0 DEAD  |  Scarlet Survivor 3/3→3/0 DEAD
     Twilight Hatchling 1/1→1/0 DEAD  |  Ancestral Automaton 3/1→3/0 DEAD
     Result: survivors 0 vs 1 — winner: Professor Putricide
  Inge, the Iron Hymn vs Sylvanas Windrunner (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [4/1, 1/2, 3/6, 3/4]
     Sylvanas Windrunner: [2/1, 1/1, 1/1, 3/4]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Cord Puller 1/1→1/1  |  Annoy-o-Tron 1/2→1/2
     Annoy-o-Tron 1/2→1/1  |  Cord Puller 1/1→1/0 DEAD
     Surf n' Surf 1/1→1/0 DEAD  |  Annoy-o-Tron 1/1→1/0 DEAD
     Wrath Weaver 3/6→3/3  |  Ancestral Automaton 3/4→3/1
     Ancestral Automaton 3/1→3/0 DEAD  |  Laboratory Assistant 3/4→3/1
     Result: survivors 2 vs 0 — winner: Inge, the Iron Hymn
  Sneed vs Yogg-Saron, Hope's End (first: Sneed)
     Sneed: [2/1, 4/1, 3/6, 3/4]
     Yogg-Saron, Hope's End: [4/1, 3/6, 1/2, 4/1]
     Ominous Seer 2/1→2/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Manasaber 4/1→4/0 DEAD
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 3/6→3/3  |  Laboratory Assistant 3/4→3/1
     Laboratory Assistant 3/1→3/0 DEAD  |  Soul Rewinder 4/1→4/0 DEAD
     Result: survivors 1 vs 1 — winner: Sneed
  Drek'Thar vs Overlord Saurfang (first: Drek'Thar)
     Drek'Thar: [2/1, 1/4, 2/1, 3/4]
     Overlord Saurfang: [13/19, 11/10]
     Risen Rider 2/1→2/0 DEAD  |  Wrath Weaver 13/19→13/17
     Wrath Weaver 13/17→13/15  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 1/4→1/0 DEAD  |  Shell Collector 11/10→11/9
     Shell Collector 11/9→11/6  |  Ancestral Automaton 3/4→3/0 DEAD
     Result: survivors 0 vs 2 — winner: Overlord Saurfang

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=17, Tier=2) | Sneed (HP=30, Armor=8, Tier=2) | Overlord Saurfang (HP=30, Armor=17, Tier=2) | Ysera (HP=30, Armor=9, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=9, Tier=2) | Professor Putricide (HP=30, Armor=6, Tier=2) | Sylvanas Windrunner (HP=30, Armor=5, Tier=2) | Drek'Thar (HP=30, Armor=3, Tier=2)

### Turn 5

**Yogg-Saron, Hope's End**  HP=30 Armor=17 Gold=7 Tier=2

  Board: 4/1, 3/6, 1/2 [Taunt,DS], 4/1
  Tavern: Sewer Rat 3/2 T2 $3 | Sewer Rat 3/2 T2 $3 | Reef Riffer 3/2 T2 $3 | Eternal Knight 4/2 T2 $3

  → Board: 4/1, 3/6, 1/2 [Taunt,DS], 4/1, 4/2, 3/2
  → Gold: 1→0
  → Actions (5): buy_tavern_3, play_hand_0, buy_tavern_0, play_hand_0, refresh

**Sneed**  HP=30 Armor=8 Gold=7 Tier=2

  Board: 2/1, 4/1, 3/6, 3/4
  Tavern: Soul Rewinder 4/1 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Old Soul 3/4 T2 $3 | Alert Alarmist 2/2 T2 $3

  → Board: 2/1, 4/1, 5/8, 3/4, 3/4, 4/1
  → Gold: 1→0 | Armor: 8→7
  → Actions (5): buy_tavern_2, play_hand_0, buy_tavern_0, play_hand_0, refresh

**Overlord Saurfang**  HP=30 Armor=17 Gold=7 Tier=2

  Board: 13/19 [G], 11/10
  Tavern: Ancestral Automaton 3/4 T2 $3 | Sewer Rat 12/11 T2 $3 | Lava Lurker 11/14 T2 $3 | Lava Lurker 11/14 T2 $3

  → Board: 17/19 [G], 15/10, 15/14, 15/14
  → Gold: 1→0
  → Actions (5): buy_tavern_2, play_hand_2, buy_tavern_2, play_hand_2, refresh

**Ysera**  HP=30 Armor=9 Gold=7 Tier=2

  Board: 3/3, 3/3, 2/1 [Taunt,Reborn], 1/1
  Tavern: Nerubian Deathswarmer 1/4 T2 $3 | Alert Alarmist 2/2 T2 $3 | Shell Collector 4/3 T2 $3 | Metallic Hunter 4/2 T2 $3 | Scarlet Survivor 3/3 T1 $3

  → Board: 3/3, 3/3, 2/1 [Taunt,Reborn], 1/1, 4/3, 4/2
  → Gold: 1→0 | Hand: 0→1
  → Actions (5): buy_tavern_2, play_hand_0, buy_tavern_2, play_hand_1, refresh

**Inge, the Iron Hymn**  HP=30 Armor=9 Gold=7 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 3/6, 3/4
  Tavern: Tide Raiser 2/1 T2 $3 | Eternal Knight 4/2 T2 $3 | Shell Collector 4/3 T2 $3 | Humming Bird 1/4 T2 $3

  → Board: 4/1, 1/2 [Taunt,DS], 3/6, 3/4, 4/3, 4/2
  → Gold: 1→0 | Hand: 0→1
  → Actions (5): buy_tavern_2, play_hand_0, buy_tavern_1, play_hand_1, refresh

**Professor Putricide**  HP=30 Armor=6 Gold=7 Tier=2

  Board: 4/1, 4/1, 1/1 [DS], 3/4
  Tavern: Shell Collector 4/3 T2 $3 | Metallic Hunter 4/2 T2 $3 | Soul Rewinder 4/1 T2 $3 | Reef Riffer 3/2 T2 $3

  → Board: 4/1, 4/1, 1/1 [DS], 3/4, 4/3, 4/2
  → Gold: 1→0 | Hand: 0→1
  → Actions (5): buy_tavern_0, play_hand_0, buy_tavern_0, play_hand_1, refresh

**Sylvanas Windrunner**  HP=30 Armor=5 Gold=7 Tier=2

  Board: 2/1 [Taunt,Reborn], 1/1 [DS], 1/1, 3/4
  Tavern: Eternal Knight 4/2 T2 $3 | Old Soul 3/4 T2 $3 | Tide Raiser 2/1 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3

  → Board: 2/1 [Taunt,Reborn], 1/1 [DS], 1/1, 3/4, 3/4, 4/2
  → Gold: 1→0
  → Actions (5): buy_tavern_1, play_hand_1, buy_tavern_0, play_hand_1, refresh

**Drek'Thar**  HP=30 Armor=3 Gold=7 Tier=2

  Board: 2/1 [Taunt,Reborn], 1/4, 2/1 [Taunt,Reborn], 3/4
  Tavern: Reef Riffer 3/2 T2 $3 | Scarlet Skull 2/1 T2 $3 | Scarlet Skull 2/1 T2 $3 | Laboratory Assistant 3/4 T2 $3

  → Board: 2/1 [Taunt,Reborn], 3/6, 2/1 [Taunt,Reborn], 3/4, 3/4, 3/2
  → Gold: 1→0 | Armor: 3→2
  → Actions (5): buy_tavern_3, play_hand_0, buy_tavern_0, play_hand_0, refresh

**Combat Phase**

  Drek'Thar vs Ysera (first: Drek'Thar)
     Drek'Thar: [2/1, 3/6, 2/1, 3/4, 3/4, 3/2]
     Ysera: [3/3, 3/3, 2/1, 1/1, 4/3, 4/2]
     Risen Rider 2/1→2/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Scarlet Survivor 3/3→3/1  |  Risen Rider 2/1→2/0 DEAD
     Wrath Weaver 3/6→3/3  |  Scarlet Survivor 3/1→3/0 DEAD
     Scarlet Survivor 3/3→3/0 DEAD  |  Reef Riffer 3/2→3/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Twilight Hatchling 1/1→1/0 DEAD  |  Laboratory Assistant 3/4→3/3
     Laboratory Assistant 3/3→3/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Result: survivors 1 vs 0 — winner: Drek'Thar
  Sneed vs Overlord Saurfang (first: Sneed)
     Sneed: [2/1, 4/1, 5/8, 3/4, 3/4, 4/1]
     Overlord Saurfang: [17/19, 15/10, 15/14, 15/14]
     Ominous Seer 2/1→2/0 DEAD  |  Lava Lurker 15/14→15/12
     Wrath Weaver 17/19→17/15  |  Soul Rewinder 4/1→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Shell Collector 15/10→15/6
     Shell Collector 15/6→15/3  |  Laboratory Assistant 3/4→3/0 DEAD
     Wrath Weaver 5/8→5/0 DEAD  |  Wrath Weaver 17/15→17/10
     Lava Lurker 15/14→15/11  |  Old Soul 3/4→3/0 DEAD
     Result: survivors 0 vs 4 — winner: Overlord Saurfang
  Yogg-Saron, Hope's End vs Inge, the Iron Hymn (first: Yogg-Saron, Hope's End)
     Yogg-Saron, Hope's End: [4/1, 3/6, 1/2, 4/1, 4/2, 3/2]
     Inge, the Iron Hymn: [4/1, 1/2, 3/6, 3/4, 4/3, 4/2]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 3/6→3/5  |  Annoy-o-Tron 1/2→1/0 DEAD
     Soul Rewinder 4/1→4/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Laboratory Assistant 3/4→3/1  |  Sewer Rat 3/2→3/0 DEAD
     Eternal Knight 4/2→5/0 DEAD  |  Laboratory Assistant 3/1→3/0 DEAD
     Eternal Knight 4/2→5/0 DEAD  |  Wrath Weaver 3/5→3/1
     Result: survivors 1 vs 1 — winner: Yogg-Saron, Hope's End
  Professor Putricide vs Sylvanas Windrunner (first: Sylvanas Windrunner)
     Professor Putricide: [4/1, 4/1, 1/1, 3/4, 4/3, 4/2]
     Sylvanas Windrunner: [2/1, 1/1, 1/1, 3/4, 3/4, 4/2]
     Risen Rider 2/1→2/0 DEAD  |  Shell Collector 4/3→4/1
     Manasaber 4/1→4/0 DEAD  |  Ancestral Automaton 3/4→3/0 DEAD
     Cord Puller 1/1→1/1  |  Shell Collector 4/1→4/0 DEAD
     Manasaber 4/1→4/0 DEAD  |  Old Soul 3/4→3/0 DEAD
     Surf n' Surf 1/1→1/0 DEAD  |  Ancestral Automaton 3/4→3/3
     Cord Puller 1/1→1/1  |  Eternal Knight 4/2→4/1
     Eternal Knight 4/1→5/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Ancestral Automaton 3/3→3/2  |  Cord Puller 1/1→1/0 DEAD
     Result: survivors 2 vs 0 — winner: Professor Putricide

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=17, Tier=2) | Overlord Saurfang (HP=30, Armor=17, Tier=2) | Ysera (HP=30, Armor=6, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=9, Tier=2) | Professor Putricide (HP=30, Armor=6, Tier=2) | Sylvanas Windrunner (HP=30, Armor=0, Tier=2) | Drek'Thar (HP=30, Armor=2, Tier=2) | Sneed (HP=28, Armor=0, Tier=2)

### Turn 6

**Yogg-Saron, Hope's End**  HP=30 Armor=17 Gold=8 Tier=2

  Board: 4/1, 3/6, 1/2 [Taunt,DS], 4/1, 5/2, 3/2
  Tavern: Ancestral Automaton 3/4 T2 $3 | Scarlet Skull 2/1 T2 $3 | Alert Alarmist 2/2 T2 $3 | Reef Riffer 3/2 T2 $3

  → Board: 4/1, 3/6, 4/1, 5/2, 3/2, 3/4, 3/2
  → Gold: 1→0 | Trinket: Impulsive Portrait
  → Actions (7): buy_tavern_0, play_hand_0, sell_board_2, buy_tavern_2, play_hand_0, refresh, refresh

**Sneed**  HP=28 Armor=0 Gold=8 Tier=2

  Board: 2/1, 4/1, 5/8, 3/4, 3/4, 4/1
  Tavern: Scarlet Skull 2/1 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Eternal Knight 4/2 T2 $3 | Sewer Rat 3/2 T2 $3

  → Board: 4/1, 5/8, 3/4, 4/4, 4/1, 4/2, 2/4
  → Gold: 1→0 | Trinket: Impulsive Portrait
  → Actions (7): buy_tavern_2, play_hand_0, sell_board_0, buy_tavern_1, play_hand_0, refresh, refresh

**Overlord Saurfang**  HP=30 Armor=17 Gold=8 Tier=2

  Board: 17/19 [G], 15/10, 15/14, 15/14
  Tavern: Shell Collector 21/16 T2 $3 | Soul Rewinder 21/14 T2 $3 | Old Soul 20/17 T2 $3 | Alert Alarmist 19/15 T2 $3

  → Board: 17/19 [G], 15/10, 15/14, 15/14, 21/16, 20/17
  → Gold: 1→0 | Trinket: Spell-powered Wrench | Hand: 2→3
  → Actions (5): buy_tavern_0, play_hand_2, buy_tavern_1, play_hand_3, refresh

**Ysera**  HP=30 Armor=6 Gold=8 Tier=2

  Board: 3/3, 3/3, 2/1 [Taunt,Reborn], 1/1, 4/3, 4/2
  Tavern: Lava Lurker 2/5 T2 $3 | Old Soul 3/4 T2 $3 | Metallic Hunter 4/2 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Tarecgosa 4/4 T2 $3

  → Board: 3/3, 3/3, 2/1 [Taunt,Reborn], 1/1, 4/3, 4/2, 16/32
  → Upgrade T2→T3 | Gold: 1→0 | Trinket: Kaleidoscope
  → Actions (4): play_hand_2, upgrade, refresh, refresh

**Inge, the Iron Hymn**  HP=30 Armor=9 Gold=8 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 3/6, 3/4, 4/3, 5/2
  Tavern: Metallic Hunter 4/2 T2 $3 | Tide Raiser 2/1 T2 $3 | Metallic Hunter 4/2 T2 $3 | Reef Riffer 3/2 T2 $3

  → Board: 4/1, 1/2 [Taunt,DS], 3/6, 3/4, 4/3, 5/2, 4/2
  → Gold: 1→0 | Trinket: Demonic Tapestry
  → Actions (4): buy_tavern_0, play_hand_1, refresh, refresh

**Professor Putricide**  HP=30 Armor=6 Gold=8 Tier=2

  Board: 4/1, 4/1, 1/1 [DS], 3/4, 4/3, 4/2
  Tavern: Eternal Knight 4/2 T2 $3 | Sewer Rat 3/2 T2 $3 | Lava Lurker 2/5 T2 $3 | Old Soul 3/4 T2 $3

  → Board: 4/1, 4/1, 1/1 [DS], 3/4, 4/3, 4/2, 2/5
  → Upgrade T2→T3 | Trinket: Bartend-o-Tron's Oilcan
  → Actions (4): buy_tavern_2, play_hand_2, upgrade, refresh

**Sylvanas Windrunner**  HP=30 Armor=0 Gold=8 Tier=2

  Board: 2/1 [Taunt,Reborn], 1/1 [DS], 1/1, 3/4, 3/4, 5/2
  Tavern: Reef Riffer 3/2 T2 $3 | Scarlet Skull 2/1 T2 $3 | Alert Alarmist 2/2 T2 $3 | Laboratory Assistant 3/4 T2 $3

  → Board: 2/1 [Taunt,Reborn], 1/1, 3/4, 3/4, 5/2, 3/4, 3/2
  → Gold: 1→0 | Trinket: Putricide Sticker
  → Actions (6): buy_tavern_3, play_hand_1, sell_board_1, buy_tavern_0, play_hand_1, refresh

**Drek'Thar**  HP=30 Armor=2 Gold=8 Tier=2

  Board: 2/1 [Taunt,Reborn], 3/6, 2/1 [Taunt,Reborn], 3/4, 3/4, 3/2
  Tavern: Shell Collector 4/3 T2 $3 | Reef Riffer 3/2 T2 $3 | Eternal Knight 4/2 T2 $3 | Laboratory Assistant 9/10 T2 $3

  → Board: 2/1 [Taunt,Reborn], 5/8, 2/1 [Taunt,Reborn], 3/4, 3/4, 3/2, 9/10 [DS]
  → Upgrade T2→T3 | Gold: 5→0 | Armor: 2→5 | Trinket: Shadowy Elixir
  → Actions (3): buy_tavern_3, play_hand_1, upgrade

**Combat Phase**

  Professor Putricide vs Drek'Thar (first: Professor Putricide)
     Professor Putricide: [4/1, 4/1, 1/1, 3/4, 4/3, 4/2, 2/5]
     Drek'Thar: [2/1, 5/8, 2/1, 3/4, 3/4, 3/2, 9/10]
     Manasaber 4/1→4/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Risen Rider 2/1→2/0 DEAD  |  Cord Puller 1/1→1/1
     Manasaber 4/1→4/0 DEAD  |  Laboratory Assistant 3/4→3/0 DEAD
     Wrath Weaver 5/8→5/4  |  Metallic Hunter 4/2→4/0 DEAD
     Cord Puller 1/1→1/0 DEAD  |  Laboratory Assistant 9/10→9/10
     Ancestral Automaton 3/4→3/1  |  Ancestral Automaton 3/4→3/1
     Ancestral Automaton 3/1→3/0 DEAD  |  Laboratory Assistant 9/10→9/7
     Reef Riffer 3/2→3/0 DEAD  |  Lava Lurker 2/5→2/2
     Shell Collector 4/3→4/0 DEAD  |  Laboratory Assistant 9/7→9/3
     Laboratory Assistant 9/3→9/1  |  Lava Lurker 2/2→2/0 DEAD
     Result: survivors 0 vs 3 — winner: Drek'Thar
  Sneed vs Inge, the Iron Hymn (first: Sneed)
     Sneed: [4/1, 5/8, 3/4, 4/4, 4/1, 4/2, 2/4]
     Inge, the Iron Hymn: [4/1, 1/2, 3/6, 3/4, 4/3, 5/2, 4/2]
     Manasaber 4/1→4/0 DEAD  |  Annoy-o-Tron 1/2→1/2
     Manasaber 4/1→4/0 DEAD  |  Laboratory Assistant 3/4→3/0 DEAD
     Wrath Weaver 5/8→5/7  |  Annoy-o-Tron 1/2→1/0 DEAD
     Wrath Weaver 3/6→3/2  |  Eternal Knight 4/2→5/0 DEAD
     Old Soul 4/4→4/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Laboratory Assistant 3/4→3/2  |  Nerubian Deathswarmer 2/4→2/1
     Soul Rewinder 4/1→4/0 DEAD  |  Wrath Weaver 3/2→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Wrath Weaver 5/7→5/3
     Nerubian Deathswarmer 2/1→2/0 DEAD  |  Eternal Knight 5/2→6/0 DEAD
     Result: survivors 1 vs 1 — winner: Sneed
  Overlord Saurfang vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Overlord Saurfang: [17/19, 15/10, 15/14, 15/14, 21/16, 20/17]
     Yogg-Saron, Hope's End: [4/1, 3/6, 4/1, 5/2, 3/2, 3/4, 3/2]
     Manasaber 4/1→4/0 DEAD  |  Shell Collector 15/10→15/6
     Wrath Weaver 17/19→17/16  |  Sewer Rat 3/2→3/0 DEAD
     Wrath Weaver 3/6→3/0 DEAD  |  Shell Collector 15/6→15/3
     Shell Collector 15/3→15/0 DEAD  |  Soul Rewinder 4/1→4/0 DEAD
     Eternal Knight 5/2→6/0 DEAD  |  Lava Lurker 15/14→15/9
     Lava Lurker 15/14→15/11  |  Reef Riffer 3/2→3/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Lava Lurker 15/9→15/6
     Result: survivors 5 vs 0 — winner: Overlord Saurfang
  Ysera vs Sylvanas Windrunner (first: Ysera)
     Ysera: [3/3, 3/3, 2/1, 1/1, 4/3, 4/2, 16/32]
     Sylvanas Windrunner: [2/1, 1/1, 3/4, 3/4, 5/2, 3/4, 3/2]
     Scarlet Survivor 3/3→3/1  |  Risen Rider 2/1→2/0 DEAD
     Surf n' Surf 1/1→1/0 DEAD  |  Risen Rider 2/1→2/0 DEAD
     Scarlet Survivor 3/3→3/0 DEAD  |  Eternal Knight 5/2→6/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Twilight Hatchling 1/1→1/0 DEAD  |  Laboratory Assistant 3/4→3/3
     Old Soul 3/4→3/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Stalwart Kodo 16/32→16/29  |  Laboratory Assistant 3/3→3/0 DEAD
     Reef Riffer 3/2→3/0 DEAD  |  Stalwart Kodo 16/29→16/26
     Result: survivors 2 vs 0 — winner: Ysera

  Alive: 8/8
  HP: Yogg-Saron, Hope's End (HP=30, Armor=7, Tier=2) | Overlord Saurfang (HP=30, Armor=17, Tier=2) | Ysera (HP=30, Armor=6, Tier=3) | Inge, the Iron Hymn (HP=30, Armor=9, Tier=2) | Drek'Thar (HP=30, Armor=5, Tier=3) | Sneed (HP=28, Armor=0, Tier=2) | Professor Putricide (HP=28, Armor=0, Tier=3) | Sylvanas Windrunner (HP=20, Armor=0, Tier=2)

### Turn 7

**Yogg-Saron, Hope's End**  HP=30 Armor=7 Gold=9 Tier=2

  Board: 4/1, 3/6, 4/1, 6/2, 3/2, 3/4, 3/2
  Tavern: Ominous Seer 2/1 T1 $3 | Ancestral Automaton 3/4 T2 $3 | Sewer Rat 3/2 T2 $3 | Metallic Hunter 4/2 T2 $3

  → Board: 3/6, 6/2, 3/2, 6/4, 3/2, 6/4, 4/2
  → Upgrade T2→T3 | Gold: 1→0
  → Actions (8): upgrade, sell_board_0, buy_tavern_1, play_hand_1, sell_board_1, buy_tavern_2, play_hand_1, refresh

**Sneed**  HP=28 Armor=0 Gold=9 Tier=2

  Board: 4/1, 5/8, 3/4, 4/4, 4/1, 5/2, 2/4
  Tavern: Eternal Knight 5/2 T2 $3 | Metallic Hunter 4/2 T2 $3 | Sewer Rat 3/2 T2 $3 | Old Soul 4/4 T2 $3

  → Board: 5/8, 3/4, 4/4, 5/2, 2/4, 4/4, 5/2
  → Upgrade T2→T3 | Gold: 1→0
  → Actions (8): upgrade, sell_board_0, buy_tavern_3, play_hand_0, sell_board_3, buy_tavern_0, play_hand_0, refresh

**Overlord Saurfang**  HP=30 Armor=17 Gold=9 Tier=2

  Board: 17/19 [G], 15/10, 15/14, 15/14, 21/16, 20/17
  Tavern: Metallic Hunter 23/17 T2 $3 | Cord Puller 20/16 T1 $3 | Tide Raiser 21/16 T2 $3 | Annoy-o-Tron 20/17 T1 $3

  → Board: 17/19 [G], 15/10, 15/14, 15/14, 21/16, 20/17, 23/17
  → Upgrade T2→T3 | Gold: 1→0
  → Actions (5): buy_tavern_0, play_hand_3, upgrade, refresh, refresh

**Ysera**  HP=30 Armor=6 Gold=9 Tier=3

  Board: 3/3, 3/3, 2/1 [Taunt,Reborn], 1/1, 4/3, 4/2, 16/32
  Tavern: Leeching Felhound 3/3 T3 $3 | Handless Forsaken 2/1 T3 $3 | Deflect-o-Bot 3/2 T3 $3 | Scarlet Skull 2/1 T2 $3 | Robust Evolution (spell) T3 $1 | Scarlet Survivor 3/3 T1 $3

  → Board: 3/3, 3/3, 2/1 [Taunt,Reborn], 4/3, 4/2, 16/32
  → Armor: 6→3 | Hand: 3→4
  → Actions (2): sell_board_3, buy_tavern_0

**Inge, the Iron Hymn**  HP=30 Armor=9 Gold=9 Tier=2

  Board: 4/1, 1/2 [Taunt,DS], 3/6, 3/4, 4/3, 6/2, 4/2
  Tavern: Soul Rewinder 4/1 T2 $3 | Eternal Knight 6/2 T2 $3 | Metallic Hunter 4/2 T2 $3 | Alert Alarmist 2/2 T2 $3

  → Board: 3/6, 3/4, 4/3, 6/2, 4/2, 6/2, 4/2
  → Upgrade T2→T3 | Gold: 1→0
  → Actions (8): upgrade, sell_board_1, buy_tavern_1, play_hand_2, sell_board_0, buy_tavern_1, play_hand_2, refresh

**Professor Putricide**  HP=28 Armor=0 Gold=9 Tier=3

  Board: 4/1, 4/1, 1/1 [DS], 3/4, 4/3, 4/2, 2/5
  Tavern: False Implicator 1/1 T3 $3 | Technical Element 5/6 T3 $3 | Leeching Felhound 3/3 T3 $3 | Mummifier 5/2 T3 $3 | Mounting Avalanche (spell) T3 $2

  → Board: 3/4, 4/3, 4/2, 2/5, 5/6, 5/2
  → HP: 28→25 | Hand: 3→4
  → Actions (8): sell_board_2, buy_tavern_1, play_hand_3, sell_board_0, buy_tavern_2, play_hand_3, sell_board_0, buy_tavern_1

**Sylvanas Windrunner**  HP=20 Armor=0 Gold=9 Tier=2

  Board: 2/1 [Taunt,Reborn], 1/1, 3/4, 3/4, 6/2, 3/4, 3/2
  Tavern: Reef Riffer 3/2 T2 $3 | Humming Bird 1/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Humming Bird 1/4 T2 $3

  → Board: 3/4, 3/4, 6/2, 3/4, 3/2, 3/2, 1/4
  → Upgrade T2→T3 | Gold: 1→0
  → Actions (8): upgrade, sell_board_1, buy_tavern_0, play_hand_2, sell_board_0, buy_tavern_0, play_hand_2, refresh

**Drek'Thar**  HP=30 Armor=5 Gold=9 Tier=3

  Board: 2/1 [Taunt,Reborn], 5/8, 2/1 [Taunt,Reborn], 3/4, 3/4, 3/2, 9/10 [DS]
  Tavern: Deflect-o-Bot 3/2 T3 $3 | Handless Forsaken 2/1 T3 $3 | Accord-o-Tron 9/9 T3 $3 | Deep-Sea Angler 2/3 T3 $3 | Portal in a Fountain (spell) T3 $3

  → Board: 5/8, 3/4, 3/4, 9/10 [DS], 9/9 [DS], 3/2 [DS], 5/2
  → Gold: 1→0
  → Actions (12): sell_board_0, buy_tavern_2, play_hand_1, sell_board_1, buy_tavern_0, play_hand_1, refresh, sell_board_3, buy_tavern_2, play_hand_1, refresh, refresh

**Combat Phase**

  Professor Putricide vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Professor Putricide: [3/4, 4/3, 4/2, 2/5, 5/6, 5/2]
     Inge, the Iron Hymn: [3/6, 3/4, 4/3, 6/2, 4/2, 6/2, 4/2]
     Wrath Weaver 3/6→3/2  |  Metallic Hunter 4/2→4/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Shell Collector 4/3→4/0 DEAD
     Laboratory Assistant 3/4→3/0 DEAD  |  Technical Element 5/6→5/3
     Shell Collector 4/3→4/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Eternal Knight 6/2→7/0 DEAD  |  Mummifier 5/2→5/0 DEAD
     Lava Lurker 2/5→2/1  |  Metallic Hunter 4/2→4/0 DEAD
     Eternal Knight 7/2→8/0 DEAD  |  Lava Lurker 2/1→2/0 DEAD
     Technical Element 5/3→5/0 DEAD  |  Wrath Weaver 3/2→3/0 DEAD
     Result: survivors 0 vs 0 — winner: draw
  Drek'Thar vs Sylvanas Windrunner (first: Drek'Thar)
     Drek'Thar: [5/8, 3/4, 3/4, 9/10, 9/9, 3/2, 5/2]
     Sylvanas Windrunner: [3/4, 3/4, 6/2, 3/4, 3/2, 3/2, 2/4]
     Wrath Weaver 5/8→5/5  |  Old Soul 3/4→3/0 DEAD
     Ancestral Automaton 3/4→3/1  |  Deflect-o-Bot 3/2→3/2
     Ancestral Automaton 3/4→3/1  |  Reef Riffer 3/2→3/0 DEAD
     Eternal Knight 6/2→7/0 DEAD  |  Laboratory Assistant 9/10→9/10
     Laboratory Assistant 3/4→3/1  |  Laboratory Assistant 3/4→3/1
     Laboratory Assistant 3/1→3/0 DEAD  |  Deflect-o-Bot 3/2→3/0 DEAD
     Laboratory Assistant 9/10→9/7  |  Reef Riffer 3/2→3/0 DEAD
     Humming Bird 2/4→2/0 DEAD  |  Mummifier 5/2→5/0 DEAD
     Accord-o-Tron 9/9→9/9  |  Ancestral Automaton 3/1→3/0 DEAD
     Result: survivors 5 vs 0 — winner: Drek'Thar
  Sneed vs Ysera (first: Sneed)
     Sneed: [5/8, 3/4, 4/4, 5/2, 2/4, 4/4, 5/2]
     Ysera: [3/3, 3/3, 2/1, 4/3, 4/2, 16/32]
     Wrath Weaver 5/8→5/6  |  Risen Rider 2/1→2/0 DEAD
     Scarlet Survivor 3/3→3/0 DEAD  |  Eternal Knight 5/2→6/0 DEAD
     Laboratory Assistant 3/4→3/1  |  Scarlet Survivor 3/3→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Wrath Weaver 5/6→5/2
     Old Soul 4/4→4/0 DEAD  |  Stalwart Kodo 16/32→16/28
     Metallic Hunter 4/2→4/0 DEAD  |  Laboratory Assistant 3/1→3/0 DEAD
     Eternal Knight 6/2→7/0 DEAD  |  Stalwart Kodo 16/28→16/22
     Stalwart Kodo 16/22→16/18  |  Old Soul 4/4→4/0 DEAD
     Nerubian Deathswarmer 2/4→2/0 DEAD  |  Stalwart Kodo 16/18→16/16
     Result: survivors 1 vs 1 — winner: Sneed
  Overlord Saurfang vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Overlord Saurfang: [17/19, 15/10, 15/14, 15/14, 21/16, 20/17, 23/17]
     Yogg-Saron, Hope's End: [3/6, 6/2, 3/2, 6/4, 3/2, 6/4, 4/2]
     Wrath Weaver 3/6→3/0 DEAD  |  Old Soul 20/17→20/14
     Wrath Weaver 17/19→17/13  |  Ancestral Automaton 6/4→6/0 DEAD
     Eternal Knight 6/2→7/0 DEAD  |  Lava Lurker 15/14→15/8
     Shell Collector 15/10→15/6  |  Metallic Hunter 4/2→4/0 DEAD
     Sewer Rat 3/2→3/0 DEAD  |  Shell Collector 21/16→21/13
     Lava Lurker 15/8→15/5  |  Reef Riffer 3/2→3/0 DEAD
     Ancestral Automaton 6/4→6/0 DEAD  |  Lava Lurker 15/14→15/8
     Result: survivors 7 vs 0 — winner: Overlord Saurfang

  Alive: 8/8
  HP: Overlord Saurfang (HP=30, Armor=17, Tier=3) | Ysera (HP=30, Armor=3, Tier=3) | Inge, the Iron Hymn (HP=30, Armor=9, Tier=3) | Drek'Thar (HP=30, Armor=5, Tier=3) | Sneed (HP=28, Armor=0, Tier=3) | Yogg-Saron, Hope's End (HP=27, Armor=0, Tier=3) | Professor Putricide (HP=25, Armor=0, Tier=3) | Sylvanas Windrunner (HP=10, Armor=0, Tier=3)

### Turn 8

**Yogg-Saron, Hope's End**  HP=27 Armor=0 Gold=10 Tier=3

  Board: 3/6, 7/2, 3/2, 6/4, 3/2, 6/4, 4/2
  Tavern: Hardy Orca 1/6 T3 $3 | Deep Blue Crooner 2/2 T3 $3 | Deep Blue Crooner 2/2 T3 $3 | Cadaver Caretaker 3/3 T3 $3 | Hostile Bounty (spell) T3 $2

  → Board: 3/6, 7/2, 6/4, 3/2, 6/4, 4/2, 1/6 [Taunt]
  → Upgrade T3→T4 | Gold: 1→0
  → Actions (5): upgrade, sell_board_2, buy_tavern_0, play_hand_2, refresh

**Sneed**  HP=28 Armor=0 Gold=10 Tier=3

  Board: 5/8, 3/4, 4/4, 7/2, 2/4, 4/4, 7/2
  Tavern: Accord-o-Tron 3/3 T3 $3 | Sly Raptor 1/3 T3 $3 | Leeching Felhound 3/3 T3 $3 | False Implicator 1/1 T3 $3

  → Board: 5/8, 3/4, 4/4, 7/2, 2/4, 4/4, 7/2
  → Upgrade T3→T4 | Gold: 1→0
  → Actions (4): upgrade, refresh, refresh, refresh

**Overlord Saurfang**  HP=30 Armor=17 Gold=10 Tier=3

  Board: 17/19 [G], 15/10, 15/14, 15/14, 21/16, 20/17, 23/17
  Tavern: Handless Forsaken 25/20 T3 $3 | Deep Blue Crooner 25/21 T3 $3 | False Implicator 24/20 T3 $3 | Hardy Orca 24/25 T3 $3

  → Board: 17/19 [G], 15/14, 15/14, 21/16, 20/17, 23/17, 24/25 [Taunt]
  → Upgrade T3→T4 | Gold: 1→0
  → Actions (5): upgrade, sell_board_1, buy_tavern_3, play_hand_3, refresh

**Ysera**  HP=30 Armor=3 Gold=10 Tier=3

  Board: 3/3, 3/3, 2/1 [Taunt,Reborn], 4/3, 4/2, 16/32
  Tavern: Handless Forsaken 2/1 T3 $3 | Handless Forsaken 2/1 T3 $3 | Leeching Felhound 3/3 T3 $3 | Dustbone Devastator 2/6 T3 $3 | Blazing Skyfin 2/4 T2 $3

  → Board: 3/3, 3/3, 4/3, 4/2, 16/32, 3/3, 2/6
  → Upgrade T3→T4 | Gold: 1→0 | Hand: 5→4
  → Actions (7): play_hand_3, upgrade, sell_board_2, buy_tavern_3, play_hand_4, refresh, refresh

**Inge, the Iron Hymn**  HP=30 Armor=9 Gold=10 Tier=3

  Board: 3/6, 3/4, 4/3, 8/2, 4/2, 8/2, 4/2
  Tavern: Floating Watcher 4/4 T3 $5 | Annoy-o-Module 2/4 T3 $3 | Deflect-o-Bot 3/2 T3 $3 | Deep Blue Crooner 2/2 T3 $3

  → Board: 3/6, 3/4, 4/3, 8/2, 4/2, 8/2, 4/2
  → Upgrade T3→T4 | Gold: 1→0
  → Actions (4): upgrade, refresh, refresh, refresh

**Professor Putricide**  HP=25 Armor=0 Gold=10 Tier=3

  Board: 3/4, 4/3, 4/2, 2/5, 5/6, 5/2
  Tavern: Soul Rewinder 4/1 T2 $3 | Leeching Felhound 3/3 T3 $3 | Deep Blue Crooner 2/2 T3 $3 | Sly Raptor 1/3 T3 $3

  → Board: 3/4, 4/3, 4/2, 2/5, 5/6, 5/2, 3/3
  → Upgrade T3→T4 | Hand: 5→4
  → Actions (3): play_hand_3, upgrade, refresh

**Sylvanas Windrunner**  HP=10 Armor=0 Gold=10 Tier=3

  Board: 3/4, 3/4, 7/2, 3/4, 3/2, 3/2, 1/4
  Tavern: Cadaver Caretaker 3/3 T3 $3 | Handless Forsaken 2/1 T3 $3 | Sprightly Scarab 3/1 T3 $3 | Manasaber 4/1 T1 $3

  → Board: 3/4, 3/4, 7/2, 3/4, 3/2, 1/4, 3/3
  → Upgrade T3→T4 | Gold: 1→0
  → Actions (5): upgrade, sell_board_4, buy_tavern_0, play_hand_2, refresh

**Drek'Thar**  HP=30 Armor=5 Gold=11 Tier=3

  Board: 5/8, 3/4, 3/4, 9/10 [DS], 9/9 [DS], 3/2 [DS], 5/2
  Tavern: Floating Watcher 10/10 T3 $5 | Deep-Sea Angler 2/3 T3 $3 | Deep Blue Crooner 2/2 T3 $3 | Shell Collector 4/3 T2 $3

  → Board: 7/10, 3/4, 3/4, 9/10 [DS], 9/9 [DS], 5/2, 14/14 [DS]
  → Upgrade T3→T4 | Gold: 1→0 | Armor: 5→3
  → Actions (5): upgrade, sell_board_5, buy_tavern_0, play_hand_0, refresh

**Combat Phase**

  Sylvanas Windrunner vs Yogg-Saron, Hope's End (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [3/4, 3/4, 7/2, 3/4, 3/2, 2/4, 3/3]
     Yogg-Saron, Hope's End: [3/6, 7/2, 6/4, 3/2, 6/4, 4/2, 1/6]
     Ancestral Automaton 3/4→3/3  |  Hardy Orca 1/6→1/3
     Wrath Weaver 3/6→3/3  |  Cadaver Caretaker 3/3→3/0 DEAD
     Old Soul 3/4→3/3  |  Hardy Orca 1/3→1/0 DEAD
     Eternal Knight 7/2→8/0 DEAD  |  Reef Riffer 3/2→3/0 DEAD
     Eternal Knight 7/2→8/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Ancestral Automaton 6/4→6/1  |  Laboratory Assistant 3/4→3/0 DEAD
     Humming Bird 2/4→2/0 DEAD  |  Ancestral Automaton 6/4→6/2
     Reef Riffer 3/2→3/0 DEAD  |  Ancestral Automaton 3/3→3/0 DEAD
     Result: survivors 1 vs 3 — winner: Sylvanas Windrunner
  Ysera vs Overlord Saurfang (first: Overlord Saurfang)
     Ysera: [3/3, 3/3, 4/3, 4/2, 16/32, 3/3, 2/6]
     Overlord Saurfang: [17/19, 15/14, 15/14, 21/16, 20/17, 23/17, 24/25]
     Wrath Weaver 17/19→17/16  |  Leeching Felhound 3/3→3/0 DEAD
     Scarlet Survivor 3/3→3/0 DEAD  |  Hardy Orca 24/25→24/22
     Lava Lurker 15/14→15/0 DEAD  |  Stalwart Kodo 16/32→16/17
     Scarlet Survivor 3/3→3/0 DEAD  |  Hardy Orca 24/22→24/19
     Lava Lurker 15/14→15/12  |  Dustbone Devastator 2/6→2/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Hardy Orca 24/19→24/15
     Shell Collector 21/16→21/12  |  Metallic Hunter 4/2→4/0 DEAD
     Stalwart Kodo 16/17→16/0 DEAD  |  Hardy Orca 24/15→24/0 DEAD
     Result: survivors 0 vs 5 — winner: Overlord Saurfang
  Professor Putricide vs Sneed (first: Sneed)
     Professor Putricide: [3/4, 4/3, 4/2, 2/5, 5/6, 5/2, 3/3]
     Sneed: [5/8, 3/4, 4/4, 7/2, 2/4, 4/4, 7/2]
     Wrath Weaver 5/8→5/3  |  Mummifier 5/2→5/0 DEAD
     Ancestral Automaton 3/4→3/0 DEAD  |  Old Soul 4/4→4/1
     Laboratory Assistant 3/4→3/1  |  Leeching Felhound 3/3→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Old Soul 4/1→4/0 DEAD
     Eternal Knight 7/2→8/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Lava Lurker 2/5→2/0 DEAD  |  Wrath Weaver 5/3→5/1
     Nerubian Deathswarmer 2/4→2/0 DEAD  |  Technical Element 5/6→5/4
     Technical Element 5/4→5/0 DEAD  |  Wrath Weaver 5/1→5/0 DEAD
     Result: survivors 0 vs 3 — winner: Sneed
  Drek'Thar vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Drek'Thar: [7/10, 3/4, 3/4, 9/10, 9/9, 5/2, 14/14]
     Inge, the Iron Hymn: [3/6, 3/4, 4/3, 8/2, 4/2, 8/2, 4/2]
     Wrath Weaver 3/6→3/0 DEAD  |  Accord-o-Tron 9/9→9/9
     Wrath Weaver 7/10→7/7  |  Laboratory Assistant 3/4→3/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Floating Watcher 14/14→14/14
     Ancestral Automaton 3/4→3/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Eternal Knight 8/2→9/0 DEAD  |  Accord-o-Tron 9/9→9/1
     Laboratory Assistant 3/4→3/0 DEAD  |  Metallic Hunter 4/2→4/0 DEAD
     Eternal Knight 9/2→10/0 DEAD  |  Accord-o-Tron 9/1→9/0 DEAD
     Result: survivors 4 vs 0 — winner: Drek'Thar

  Alive: 8/8
  HP: Overlord Saurfang (HP=30, Armor=17, Tier=4) | Drek'Thar (HP=30, Armor=3, Tier=4) | Sneed (HP=28, Armor=0, Tier=4) | Yogg-Saron, Hope's End (HP=27, Armor=0, Tier=4) | Inge, the Iron Hymn (HP=26, Armor=0, Tier=4) | Ysera (HP=20, Armor=0, Tier=4) | Professor Putricide (HP=15, Armor=0, Tier=4) | Sylvanas Windrunner (HP=10, Armor=0, Tier=4)

### Turn 9

**Yogg-Saron, Hope's End**  HP=27 Armor=0 Gold=10 Tier=4

  Board: 3/6, 8/2, 6/4, 3/2, 6/4, 4/2, 1/6 [Taunt]
  Tavern: Hardy Orca 1/6 T3 $3 | Plaguerunner 4/2 T4 $3 | Trigore the Lasher 9/3 T4 $3 | Prosthetic Hand 3/1 T4 $3 | Hunting Tiger Shark 3/5 T4 $3 | Shifting Tide (spell) T4 $1

  → Board: 3/6, 8/2, 6/4, 6/4, 1/6 [Taunt], 9/3, 3/5
  → Gold: 1→0 | Trinket: Fridge Magnet | Hand: 3→4
  → Actions (9): sell_board_3, buy_tavern_2, play_hand_3, sell_board_4, buy_tavern_3, play_hand_3, refresh, refresh, refresh

**Sneed**  HP=28 Armor=0 Gold=10 Tier=4

  Board: 5/8, 3/4, 4/4, 8/2, 2/4, 4/4, 8/2
  Tavern: Rimescale Priestess 3/3 T4 $3 | False Implicator 1/1 T3 $3 | Annoy-o-Module 2/4 T3 $3 | Zesty Shaker 6/7 T4 $3 | Woodland Defiler 5/6 T4 $3 | Deepwater Clan (spell) T4 $2

  → Board: 7/10, 4/4, 8/2, 4/4, 8/2, 6/7, 5/6
  → Gold: 1→0 | HP: 28→27 | Trinket: Jarred Frostling
  → Actions (9): sell_board_4, buy_tavern_3, play_hand_0, sell_board_1, buy_tavern_3, play_hand_0, refresh, refresh, refresh

**Overlord Saurfang**  HP=30 Armor=17 Gold=10 Tier=4

  Board: 17/19 [G], 15/14, 15/14, 21/16, 20/17, 23/17, 24/25 [Taunt]
  Tavern: Imposing Percussionist 29/25 T4 $3 | Rimescale Priestess 28/24 T4 $3 | Hunting Tiger Shark 28/26 T4 $3 | Sprightly Scarab 28/22 T3 $3 | Humming Bird 26/25 T2 $3 | Boon of Beetles (spell) T4 $1

  → Board: 21/23 [G], 20/17, 23/17, 24/25 [Taunt], 29/25, 11/33, 28/26
  → Gold: 1→0 | Armor: 17→12 | Trinket: Wizard's Pipe
  → Actions (10): sell_board_1, buy_tavern_0, play_hand_3, sell_board_1, play_hand_3, sell_board_1, buy_tavern_1, play_hand_2, refresh, refresh

**Ysera**  HP=20 Armor=0 Gold=10 Tier=4

  Board: 3/3, 3/3, 4/3, 4/2, 16/32, 3/3, 2/6
  Tavern: Technical Element 5/6 T3 $3 | Rylak Metalhead 5/3 T4 $3 | Enchanted Sentinel 3/5 T4 $3 | Risen Rider 2/1 T1 $3 | Auto Assembler 2/2 T4 $3 | Tarecgosa 4/4 T2 $3

  → Board: 4/3, 4/2, 16/32, 3/3, 2/6, 5/6, 5/3 [Taunt]
  → Gold: 1→0 | Trinket: Faerie Dragon Scale
  → Actions (8): sell_board_0, buy_tavern_0, play_hand_5, sell_board_0, buy_tavern_0, play_hand_5, refresh, refresh

**Inge, the Iron Hymn**  HP=26 Armor=0 Gold=10 Tier=4

  Board: 3/6, 3/4, 4/3, 10/2, 4/2, 10/2, 4/2
  Tavern: Waverider 2/8 T4 $3 | Sprightly Scarab 3/1 T3 $3 | Flaming Enforcer 4/5 T4 $3 | Sprightly Scarab 3/1 T3 $3 | Technical Element 5/6 T3 $3

  → Board: 3/6, 4/3, 10/2, 10/2, 5/6, 2/8
  → HP: 26→23 | Trinket: Unholy Sanctum | Hand: 6→7
  → Actions (8): sell_board_4, buy_tavern_4, play_hand_6, sell_board_5, buy_tavern_0, play_hand_6, sell_board_1, buy_tavern_1

**Professor Putricide**  HP=15 Armor=0 Gold=10 Tier=4

  Board: 3/4, 4/3, 4/2, 2/5, 5/6, 5/2, 3/3
  Tavern: Seafloor Recruiter 3/5 T4 $3 | Rylak Metalhead 5/3 T4 $3 | Woodland Defiler 5/6 T4 $3 | Imposing Percussionist 4/4 T4 $3 | Rimescale Priestess 3/3 T4 $3

  → Board: 4/3, 2/5, 5/6, 5/2, 5/6, 3/5, 5/3 [Taunt]
  → Trinket: Electrode Attractor
  → Actions (10): sell_board_2, buy_tavern_2, play_hand_5, sell_board_5, buy_tavern_0, play_hand_5, sell_board_0, buy_tavern_0, play_hand_5, refresh

**Sylvanas Windrunner**  HP=10 Armor=0 Gold=10 Tier=4

  Board: 3/4, 3/4, 8/2, 3/4, 3/2, 1/4, 3/3
  Tavern: Plaguerunner 4/2 T4 $3 | Plaguerunner 4/2 T4 $3 | Zesty Shaker 6/7 T4 $3 | Hunting Tiger Shark 3/5 T4 $3 | Abyssal Bruiser 1/1 T4 $3

  → Board: 3/4, 3/4, 8/2, 3/4, 3/3, 6/7, 3/5
  → Gold: 1→0 | Trinket: Kel'Thuzad Portrait | Hand: 1→2
  → Actions (8): sell_board_4, buy_tavern_2, play_hand_1, sell_board_4, buy_tavern_2, play_hand_1, refresh, refresh

**Drek'Thar**  HP=30 Armor=3 Gold=11 Tier=4

  Board: 7/10, 3/4, 3/4, 9/10 [DS], 9/9 [DS], 5/2, 14/14 [DS]
  Tavern: Technical Element 11/12 T3 $3 | Auto Assembler 2/2 T4 $3 | Annoy-o-Module 2/4 T3 $3 | Enchanted Sentinel 3/5 T4 $3 | Cadaver Caretaker 3/3 T3 $3

  → Board: 7/10, 9/10 [DS], 9/9 [DS], 14/14 [DS], 11/12 [DS], 8/14 [DS], 9/3
  → Gold: 1→0 | Trinket: Ur'zul Sticker
  → Actions (15): sell_board_1, buy_tavern_0, play_hand_0, sell_board_1, buy_tavern_2, play_hand_0, refresh, sell_board_3, buy_tavern_1, play_hand_0, sell_board_5, buy_tavern_1, play_hand_0, refresh, refresh

**Combat Phase**

  Inge, the Iron Hymn vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Inge, the Iron Hymn: [3/6, 4/3, 10/2, 10/2, 5/6, 2/8]
     Yogg-Saron, Hope's End: [3/6, 8/2, 6/4, 6/4, 1/6, 9/3, 3/5]
     Wrath Weaver 3/6→3/0 DEAD  |  Eternal Knight 10/2→11/0 DEAD
     Wrath Weaver 3/6→3/5  |  Hardy Orca 1/6→1/3
     Eternal Knight 8/2→9/0 DEAD  |  Waverider 2/8→2/0 DEAD
     Shell Collector 4/3→4/2  |  Hardy Orca 1/3→1/0 DEAD
     Ancestral Automaton 6/4→6/1  |  Wrath Weaver 3/5→3/0 DEAD
     Eternal Knight 11/2→12/0 DEAD  |  Hunting Tiger Shark 3/5→3/0 DEAD
     Ancestral Automaton 6/4→6/0 DEAD  |  Technical Element 5/6→5/0 DEAD
     Result: survivors 1 vs 2 — winner: Inge, the Iron Hymn
  Sylvanas Windrunner vs Professor Putricide (first: Professor Putricide)
     Sylvanas Windrunner: [3/4, 3/4, 8/2, 3/4, 3/3, 6/7, 3/5]
     Professor Putricide: [4/3, 2/5, 5/6, 5/2, 5/6, 3/5, 5/3]
     Shell Collector 4/3→4/0 DEAD  |  Zesty Shaker 6/7→6/3
     Ancestral Automaton 3/4→3/0 DEAD  |  Rylak Metalhead 5/3→5/0 DEAD
     Lava Lurker 2/5→2/2  |  Hunting Tiger Shark 3/5→3/3
     Old Soul 3/4→3/0 DEAD  |  Mummifier 5/2→5/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Zesty Shaker 6/3→6/0 DEAD
     Eternal Knight 8/2→9/0 DEAD  |  Woodland Defiler 5/6→5/0 DEAD
     Seafloor Recruiter 3/5→3/2  |  Laboratory Assistant 3/4→3/1
     Laboratory Assistant 3/1→3/0 DEAD  |  Seafloor Recruiter 3/2→3/0 DEAD
     Result: survivors 2 vs 1 — winner: Sylvanas Windrunner
  Drek'Thar vs Ysera (first: Ysera)
     Drek'Thar: [7/10, 9/10, 9/9, 14/14, 11/12, 8/14, 9/3]
     Ysera: [4/3, 4/2, 16/32, 3/3, 2/6, 5/6, 5/3]
     Shell Collector 4/3→4/0 DEAD  |  Wrath Weaver 7/10→7/6
     Wrath Weaver 7/6→7/1  |  Rylak Metalhead 5/3→5/0 DEAD
     Metallic Hunter 4/2→4/0 DEAD  |  Floating Watcher 14/14→14/14
     Laboratory Assistant 9/10→9/10  |  Dustbone Devastator 2/6→2/0 DEAD
     Stalwart Kodo 16/32→16/21  |  Technical Element 11/12→11/12
     Accord-o-Tron 9/9→9/9  |  Leeching Felhound 3/3→3/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Waverider 8/14→8/14
     Floating Watcher 14/14→14/0 DEAD  |  Stalwart Kodo 16/21→16/7
     Result: survivors 6 vs 1 — winner: Drek'Thar
  Sneed vs Overlord Saurfang (first: Sneed)
     Sneed: [7/10, 4/4, 8/2, 4/4, 8/2, 6/7, 5/6]
     Overlord Saurfang: [21/23, 20/17, 23/17, 24/25, 29/25, 11/33, 28/26]
     Wrath Weaver 7/10→7/0 DEAD  |  Hardy Orca 24/25→24/18
     Wrath Weaver 21/23→21/19  |  Old Soul 4/4→4/0 DEAD
     Old Soul 4/4→4/0 DEAD  |  Hardy Orca 24/18→24/14
     Old Soul 20/17→20/9  |  Eternal Knight 8/2→9/0 DEAD
     Eternal Knight 9/2→10/0 DEAD  |  Hardy Orca 24/14→24/5
     Metallic Hunter 23/17→23/12  |  Woodland Defiler 5/6→5/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Hardy Orca 24/5→24/0 DEAD
     Result: survivors 0 vs 6 — winner: Overlord Saurfang

  Alive: 8/8
  HP: Overlord Saurfang (HP=30, Armor=12, Tier=4) | Drek'Thar (HP=30, Armor=3, Tier=4) | Yogg-Saron, Hope's End (HP=27, Armor=0, Tier=4) | Inge, the Iron Hymn (HP=23, Armor=0, Tier=4) | Ysera (HP=20, Armor=0, Tier=4) | Professor Putricide (HP=15, Armor=0, Tier=4) | Sneed (HP=12, Armor=0, Tier=4) | Sylvanas Windrunner (HP=10, Armor=0, Tier=4)

### Turn 10

**Yogg-Saron, Hope's End**  HP=27 Armor=0 Gold=10 Tier=4

  Board: 3/6, 9/2, 6/4, 6/4, 1/6 [Taunt], 9/6, 3/5
  Tavern: Auto Assembler 2/2 T4 $3 | Enchanted Sentinel 3/5 T4 $3 | Floating Watcher 4/4 T3 $5 | Sprightly Scarab 3/1 T3 $3 | Friendly Geist 6/3 T4 $3

  → Board: 3/6, 9/2, 6/4, 6/4, 9/6, 16/32, 6/3
  → Upgrade T4→T5 | Gold: 1→0 | Hand: 3→2
  → Actions (8): upgrade, sell_board_4, play_hand_2, sell_board_5, buy_tavern_4, play_hand_2, refresh, refresh

**Sneed**  HP=12 Armor=0 Gold=10 Tier=4

  Board: 7/10, 4/4, 10/2, 4/4, 10/2, 6/7, 5/6
  Tavern: Accord-o-Tron 3/3 T3 $3 | Friendly Geist 7/3 T4 $3 | Cadaver Caretaker 4/3 T3 $3 | Stomping Stegodon 4/4 T4 $3 | Seafloor Recruiter 3/5 T4 $3

  → Board: 7/10, 10/2, 4/4, 10/2, 6/7, 5/6, 7/3
  → Upgrade T4→T5 | Gold: 1→0
  → Actions (5): upgrade, sell_board_1, buy_tavern_1, play_hand_0, refresh

**Overlord Saurfang**  HP=30 Armor=12 Gold=10 Tier=4

  Board: 21/23 [G], 20/17, 23/17, 24/25 [Taunt], 29/25, 11/33, 28/26
  Tavern: Rimescale Priestess 33/29 T4 $3 | Laboratory Assistant 33/30 T2 $3 | Stomping Stegodon 34/30 T4 $3 | Tide Raiser 32/27 T2 $3 | Hardy Orca 31/32 T3 $3

  → Board: 21/23 [G], 23/17, 24/25 [Taunt], 29/25, 11/33, 28/26, 34/30
  → Upgrade T4→T5 | Gold: 1→0 | Hand: 3→2
  → Actions (8): upgrade, sell_board_1, play_hand_2, sell_board_6, buy_tavern_2, play_hand_2, refresh, refresh

**Ysera**  HP=20 Armor=0 Gold=10 Tier=4

  Board: 4/3, 4/2, 16/32, 3/3, 2/6, 5/6, 5/3 [Taunt]
  Tavern: Abyssal Bruiser 1/1 T4 $3 | Imposing Percussionist 4/4 T4 $3 | Humming Bird 1/4 T2 $3 | Auto Assembler 2/2 T4 $3 | Waverider 2/8 T4 $3 | Tarecgosa 4/4 T2 $3

  → Board: 4/3, 16/32, 3/3, 2/6, 5/6, 5/3 [Taunt], 2/8
  → Upgrade T4→T5 | Gold: 1→0
  → Actions (5): upgrade, sell_board_1, buy_tavern_4, play_hand_6, refresh

**Inge, the Iron Hymn**  HP=23 Armor=0 Gold=10 Tier=4

  Board: 3/6, 4/3, 12/2, 12/2, 5/6, 2/8
  Tavern: Ancestral Automaton 3/4 T2 $3 | Hardy Orca 1/6 T3 $3 | Deflect-o-Bot 3/2 T3 $3 | Wyvern Outrider 2/8 T4 $3 | Malchezaar, Prince of Dance 5/4 T4 $3

  → Board: 5/8, 12/2, 12/2, 5/6, 2/8, 4/5, 2/8
  → Upgrade T4→T5 | Gold: 1→0 | HP: 23→22 | Hand: 8→7
  → Actions (6): play_hand_6, upgrade, sell_board_1, buy_tavern_3, play_hand_7, refresh

**Professor Putricide**  HP=15 Armor=0 Gold=10 Tier=4

  Board: 4/3, 2/5, 5/6, 5/2, 5/6, 3/5, 5/3 [Taunt]
  Tavern: Deep Blue Crooner 2/2 T3 $3 | Sprightly Scarab 3/1 T3 $3 | Deep-Sea Angler 2/3 T3 $3 | Prosthetic Hand 3/1 T4 $3 | Marquee Ticker 3/7 T4 $3

  → Board: 2/5, 5/6, 5/2, 5/6, 3/5, 5/3 [Taunt], 3/7
  → Upgrade T4→T5
  → Actions (5): upgrade, sell_board_0, buy_tavern_4, play_hand_5, refresh

**Sylvanas Windrunner**  HP=10 Armor=0 Gold=10 Tier=4

  Board: 3/4, 3/4, 9/2, 3/4, 3/3, 6/7, 3/5
  Tavern: Marquee Ticker 3/7 T4 $3 | Holo Rover 4/4 T4 $3 | Hardy Orca 1/6 T3 $3 | Accord-o-Tron 3/3 T3 $3 | Dustbone Devastator 2/6 T3 $3

  → Board: 3/4, 9/2, 3/4, 6/7, 3/5, 3/6, 3/7
  → Upgrade T4→T5 | Gold: 1→0 | Hand: 1→0
  → Actions (8): upgrade, sell_board_4, play_hand_0, sell_board_0, buy_tavern_0, play_hand_0, refresh, refresh

**Drek'Thar**  HP=30 Armor=3 Gold=11 Tier=4

  Board: 7/10, 9/10 [DS], 9/9 [DS], 14/14 [DS], 11/12 [DS], 8/14 [DS], 9/3
  Tavern: Trigore the Lasher 9/3 T4 $3 | Deflect-o-Bot 3/2 T3 $3 | Prosthetic Hand 3/1 T4 $3 | Waverider 8/14 T4 $3 | False Implicator 1/1 T3 $3

  → Board: 7/10, 9/10 [DS], 9/9 [DS], 14/14 [DS], 11/12 [DS], 8/14 [DS], 8/14 [DS]
  → Upgrade T4→T5 | Gold: 1→0
  → Actions (6): upgrade, sell_board_6, buy_tavern_3, play_hand_1, refresh, refresh

**Combat Phase**

  Professor Putricide vs Inge, the Iron Hymn (first: Professor Putricide)
     Professor Putricide: [2/5, 5/6, 5/2, 5/6, 3/5, 5/3, 3/7]
     Inge, the Iron Hymn: [5/8, 12/2, 12/2, 5/6, 2/8, 8/13, 2/8]
     Lava Lurker 2/5→2/0 DEAD  |  Flaming Enforcer 8/13→8/11
     Wrath Weaver 5/8→5/3  |  Rylak Metalhead 5/3→5/0 DEAD
     Technical Element 5/6→5/1  |  Wrath Weaver 5/3→5/0 DEAD
     Eternal Knight 12/2→13/0 DEAD  |  Woodland Defiler 5/6→5/0 DEAD
     Mummifier 5/2→5/0 DEAD  |  Technical Element 5/6→5/1
     Eternal Knight 13/2→14/0 DEAD  |  Technical Element 5/1→5/0 DEAD
     Seafloor Recruiter 3/5→3/3  |  Waverider 2/8→2/5
     Technical Element 5/1→5/0 DEAD  |  Seafloor Recruiter 3/3→3/0 DEAD
     Marquee Ticker 8/12→8/10  |  Wyvern Outrider 2/8→2/0 DEAD
     Waverider 2/5→2/0 DEAD  |  Marquee Ticker 8/10→8/8
     Result: survivors 1 vs 1 — winner: Professor Putricide
  Sylvanas Windrunner vs Drek'Thar (first: Sylvanas Windrunner)
     Sylvanas Windrunner: [3/4, 9/2, 3/4, 6/7, 3/5, 3/6, 3/7]
     Drek'Thar: [7/10, 9/10, 9/9, 14/14, 11/12, 8/14, 8/14]
     Old Soul 3/4→3/0 DEAD  |  Waverider 8/14→8/14
     Wrath Weaver 7/10→7/7  |  Laboratory Assistant 3/4→3/0 DEAD
     Eternal Knight 9/2→10/0 DEAD  |  Accord-o-Tron 9/9→9/9
     Laboratory Assistant 9/10→9/10  |  Hunting Tiger Shark 3/5→3/0 DEAD
     Zesty Shaker 6/7→6/0 DEAD  |  Waverider 8/14→8/8
     Accord-o-Tron 9/9→9/6  |  Baby Kodo 3/6→3/0 DEAD
     Marquee Ticker 3/7→3/0 DEAD  |  Accord-o-Tron 9/6→9/3
     Result: survivors 0 vs 7 — winner: Drek'Thar
  Sneed vs Ysera (first: Sneed)
     Sneed: [7/10, 10/2, 4/4, 10/2, 6/7, 5/6, 7/3]
     Ysera: [4/3, 16/32, 3/3, 2/6, 5/6, 5/3, 2/8]
     Wrath Weaver 7/10→7/5  |  Rylak Metalhead 5/3→5/0 DEAD
     Shell Collector 4/3→4/0 DEAD  |  Zesty Shaker 6/7→6/3
     Eternal Knight 10/2→11/0 DEAD  |  Dustbone Devastator 2/6→2/0 DEAD
     Stalwart Kodo 16/32→16/28  |  Old Soul 4/4→4/0 DEAD
     Eternal Knight 11/2→12/0 DEAD  |  Stalwart Kodo 16/28→16/17
     Leeching Felhound 3/3→3/0 DEAD  |  Wrath Weaver 7/5→7/2
     Zesty Shaker 6/3→6/0 DEAD  |  Stalwart Kodo 16/17→16/11
     Technical Element 5/6→5/0 DEAD  |  Wrath Weaver 7/2→7/0 DEAD
     Woodland Defiler 5/6→5/4  |  Waverider 2/8→2/3
     Waverider 2/3→2/0 DEAD  |  Woodland Defiler 5/4→5/2
     Friendly Geist 7/3→7/0 DEAD  |  Stalwart Kodo 16/11→16/4
     Result: survivors 1 vs 1 — winner: Sneed
  Overlord Saurfang vs Yogg-Saron, Hope's End (first: Overlord Saurfang)
     Overlord Saurfang: [21/23, 23/17, 24/25, 29/25, 11/33, 28/26, 34/30]
     Yogg-Saron, Hope's End: [3/6, 9/2, 6/4, 6/4, 9/6, 16/32, 6/3]
     Wrath Weaver 21/23→21/14  |  Eternal Knight 9/2→10/0 DEAD
     Wrath Weaver 3/6→3/0 DEAD  |  Hardy Orca 24/25→24/22
     Metallic Hunter 23/17→23/11  |  Ancestral Automaton 6/4→6/0 DEAD
     Ancestral Automaton 6/4→6/0 DEAD  |  Hardy Orca 24/22→24/16
     Hardy Orca 24/16→24/10  |  Friendly Geist 6/3→6/0 DEAD
     Trigore the Lasher 9/6→9/0 DEAD  |  Hardy Orca 24/10→24/1
     Imposing Percussionist 29/25→29/9  |  Stalwart Kodo 16/32→16/3
     Stalwart Kodo 16/3→16/0 DEAD  |  Hardy Orca 24/1→24/0 DEAD
     Result: survivors 6 vs 0 — winner: Overlord Saurfang

  **Sylvanas Windrunner eliminated!** (HP=0, Turn 10)
  Alive: 7/8
  HP: Overlord Saurfang (HP=30, Armor=12, Tier=5) | Drek'Thar (HP=30, Armor=3, Tier=5) | Inge, the Iron Hymn (HP=22, Armor=0, Tier=5) | Ysera (HP=20, Armor=0, Tier=5) | Professor Putricide (HP=15, Armor=0, Tier=5) | Yogg-Saron, Hope's End (HP=12, Armor=0, Tier=5) | Sneed (HP=12, Armor=0, Tier=5)

### Turn 11

**Yogg-Saron, Hope's End**  HP=12 Armor=0 Gold=10 Tier=5

  Board: 3/6, 10/2, 6/4, 6/4, 9/9, 16/32, 6/3
  Tavern: Spiked Savior 8/2 T5 $3 | Bazaar Dealer 4/6 T5 $3 | Famished Felbat 6/3 T5 $3 | Darkcrest Strategist 4/5 T5 $3 | Divine Sparkbot 4/2 T5 $3 | Armor Stash (spell) T5 $3

  → Board: 10/2, 9/9, 16/32, 8/2 [Taunt,Reborn], 4/6, 4/8, 5/6
  → Gold: 1→0
  → Actions (14): sell_board_0, buy_tavern_0, play_hand_2, sell_board_5, buy_tavern_0, play_hand_2, refresh, sell_board_1, buy_tavern_2, play_hand_2, sell_board_1, buy_tavern_0, play_hand_2, refresh

**Sneed**  HP=12 Armor=0 Gold=10 Tier=5

  Board: 7/10, 12/2, 4/4, 12/2, 6/7, 5/6, 7/3
  Tavern: Iridescent Skyblazer 3/8 T5 $3 | Darkcrest Strategist 4/5 T5 $3 | Holo Rover 4/4 T4 $3 | Wintergrasp Ghoul 6/3 T5 $3 | Ancestral Automaton 3/4 T2 $3 | Contracted Corpse (spell) T5 $3

  → Board: 7/10, 12/2, 12/2, 6/7, 3/8, 3/8, 5/10
  → Gold: 1→0
  → Actions (13): sell_board_2, buy_tavern_0, play_hand_0, refresh, sell_board_5, buy_tavern_4, play_hand_0, refresh, refresh, sell_board_4, buy_tavern_3, play_hand_0, refresh

**Overlord Saurfang**  HP=30 Armor=12 Gold=10 Tier=5

  Board: 21/23 [G], 23/17, 24/25 [Taunt], 29/25, 11/33, 28/26, 34/30
  Tavern: Iridescent Skyblazer 35/36 T5 $3 | Void Pup Trainer 39/35 T5 $3 | Nerubian Deathswarmer 33/32 T2 $3 | False Implicator 33/29 T3 $3 | Catacomb Crasher 36/38 T5 $3 | Saloon's Finest (spell) T5 $2

  → Board: 29/25, 28/26, 34/30, 39/35, 37/38, 35/36, 34/32
  → Gold: 1→0 | Armor: 12→11
  → Actions (14): sell_board_1, buy_tavern_1, play_hand_2, sell_board_3, buy_tavern_3, play_hand_2, sell_board_0, buy_tavern_0, play_hand_2, sell_board_0, buy_tavern_0, play_hand_2, refresh, refresh

**Ysera**  HP=20 Armor=0 Gold=10 Tier=5

  Board: 4/3, 16/32, 3/3, 2/6, 5/6, 5/3 [Taunt], 2/8
  Tavern: Bazaar Dealer 4/6 T5 $3 | Dustbone Devastator 2/6 T3 $3 | Darkcrest Strategist 4/5 T5 $3 | Iridescent Skyblazer 3/8 T5 $3 | Sly Raptor 1/3 T3 $3 | Upper Hand (spell) T5 $3 | Roaring Recruiter 2/8 T3 $3

  → Board: 16/32, 5/6, 2/8, 3/8, 4/6, 2/8, 4/5
  → Gold: 1→0
  → Actions (14): sell_board_2, buy_tavern_3, play_hand_7, sell_board_0, buy_tavern_0, play_hand_7, sell_board_1, buy_tavern_4, play_hand_7, sell_board_2, buy_tavern_1, play_hand_7, refresh, refresh

**Inge, the Iron Hymn**  HP=22 Armor=0 Gold=10 Tier=5

  Board: 5/8, 14/2, 14/2, 5/6, 2/8, 8/13, 2/8
  Tavern: Maelstrom Emergent 2/7 T5 $3 | Zesty Shaker 6/7 T4 $3 | Handless Forsaken 2/1 T3 $3 | Deflect-o-Bot 3/2 T3 $3 | Seafloor Recruiter 3/5 T4 $3

  → Board: 5/8, 14/2, 14/2, 5/6, 8/13, 6/7, 3/8
  → Gold: 1→0
  → Actions (12): sell_board_4, buy_tavern_1, play_hand_7, refresh, sell_board_5, buy_tavern_4, play_hand_7, refresh, refresh, refresh, refresh, refresh

**Professor Putricide**  HP=15 Armor=0 Gold=10 Tier=5

  Board: 2/5, 5/6, 5/2, 5/6, 3/5, 5/3 [Taunt], 3/7
  Tavern: Skeletal Strafer 6/6 T5 $3 | Lurking Leviathan 3/8 T5 $3 | Wintergrasp Ghoul 5/3 T5 $3 | Shadowdancer 5/3 T5 $3 | Monstrous Macaw 5/4 T4 $3

  → Board: 5/6, 5/6, 5/3 [Taunt], 3/7, 6/6, 3/8, 6/4
  → Actions (10): sell_board_0, buy_tavern_0, play_hand_6, sell_board_1, buy_tavern_0, play_hand_6, sell_board_2, buy_tavern_2, play_hand_6, refresh

**Drek'Thar**  HP=30 Armor=3 Gold=11 Tier=5

  Board: 7/10, 9/10 [DS], 9/9 [DS], 14/14 [DS], 11/12 [DS], 8/14 [DS], 8/14 [DS]
  Tavern: Ashen Corruptor 6/6 T5 $3 | Wyvern Outrider 2/8 T4 $3 | Catacomb Crasher 4/10 T5 $3 | Tranquil Meditative 9/14 T5 $3 | Void Pup Trainer 7/7 T5 $3

  → Board: 14/14 [DS], 11/12 [DS], 8/14 [DS], 8/14 [DS], 9/14 [DS], 12/9 [DS], 10/14 [DS]
  → Gold: 1→0
  → Actions (14): sell_board_0, buy_tavern_3, play_hand_2, refresh, refresh, sell_board_1, buy_tavern_2, play_hand_2, refresh, sell_board_0, buy_tavern_0, play_hand_2, refresh, refresh

**Combat Phase**

  Ysera vs Professor Putricide (first: Ysera)
     Ysera: [16/32, 5/6, 2/8, 3/8, 4/6, 2/8, 4/5]
     Professor Putricide: [6/7, 6/7, 6/4, 4/8, 7/7, 4/9, 7/5]
     Stalwart Kodo 16/32→16/26  |  Rylak Metalhead 6/4→6/0 DEAD
     Technical Element 6/7→6/3  |  Bazaar Dealer 4/6→4/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Monstrous Macaw 7/5→7/0 DEAD
     Woodland Defiler 6/7→6/5  |  Waverider 2/8→2/2
     Waverider 2/2→2/0 DEAD  |  Lurking Leviathan 4/9→4/7
     Marquee Ticker 4/8→4/6  |  Roaring Recruiter 2/8→2/4
     Iridescent Skyblazer 4/9→4/3  |  Technical Element 6/3→6/0 DEAD
     Skeletal Strafer 7/7→7/0 DEAD  |  Stalwart Kodo 17/27→17/20
     Roaring Recruiter 2/4→3/5  |  Woodland Defiler 6/5→6/3
     Lurking Leviathan 4/7→4/3  |  Darkcrest Strategist 4/5→4/1
     Darkcrest Strategist 4/1→4/0 DEAD  |  Woodland Defiler 6/3→6/0 DEAD
     Result: survivors 3 vs 2 — winner: Ysera
  Sneed vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Sneed: [7/10, 12/2, 12/2, 6/7, 3/8, 3/8, 5/10]
     Inge, the Iron Hymn: [5/8, 14/2, 14/2, 5/6, 12/23, 6/7, 3/8]
     Wrath Weaver 5/8→5/5  |  Iridescent Skyblazer 3/8→3/3
     Wrath Weaver 7/10→7/4  |  Zesty Shaker 6/7→6/0 DEAD
     Eternal Knight 14/2→15/0 DEAD  |  Iridescent Skyblazer 5/10→5/0 DEAD
     Eternal Knight 12/2→13/0 DEAD  |  Wrath Weaver 5/5→5/0 DEAD
     Eternal Knight 15/2→16/0 DEAD  |  Iridescent Skyblazer 5/5→5/0 DEAD
     Eternal Knight 13/2→14/0 DEAD  |  Technical Element 5/6→5/0 DEAD
     Flaming Enforcer 12/23→12/17  |  Zesty Shaker 6/7→6/0 DEAD
     Catacomb Crasher 5/10→5/0 DEAD  |  Flaming Enforcer 12/17→12/12
     Lurking Leviathan 3/8→3/1  |  Wrath Weaver 7/4→7/1
     Result: survivors 1 vs 2 — winner: Sneed
  Yogg-Saron, Hope's End vs Drek'Thar (first: Drek'Thar)
     Yogg-Saron, Hope's End: [10/2, 9/9, 16/32, 8/2, 4/6, 4/8, 5/6]
     Drek'Thar: [14/14, 11/12, 8/14, 8/14, 9/14, 12/9, 10/14]
     Floating Watcher 14/14→14/14  |  Spiked Savior 8/2→8/0 DEAD
     Eternal Knight 10/2→11/0 DEAD  |  Waverider 8/14→8/14
     Technical Element 11/12→11/1  |  Trigore the Lasher 9/9→9/0 DEAD
     Stalwart Kodo 16/32→16/24  |  Waverider 8/14→8/0 DEAD
     Waverider 8/14→8/14  |  Technical Element 5/6→5/0 DEAD
     Bazaar Dealer 4/6→4/0 DEAD  |  Friendly Geist 12/9→12/9
     Tranquil Meditative 9/14→9/14  |  Eternal Tycoon 4/8→4/0 DEAD
     Result: survivors 1 vs 6 — winner: Yogg-Saron, Hope's End

  Alive: 7/8
  HP: Overlord Saurfang (HP=30, Armor=11, Tier=5) | Drek'Thar (HP=30, Armor=3, Tier=5) | Inge, the Iron Hymn (HP=22, Armor=0, Tier=5) | Ysera (HP=20, Armor=0, Tier=5) | Professor Putricide (HP=15, Armor=0, Tier=5) | Yogg-Saron, Hope's End (HP=12, Armor=0, Tier=5) | Sneed (HP=12, Armor=0, Tier=5)

### Turn 12

**Yogg-Saron, Hope's End**  HP=12 Armor=0 Gold=10 Tier=5

  Board: 13/2, 9/14, 16/32, 8/2 [Taunt,Reborn], 4/6, 4/8, 5/6
  Tavern: Zesty Shaker 6/7 T4 $3 | Old Soul 3/4 T2 $3 | Deep Blue Crooner 2/2 T3 $3 | Imposing Percussionist 4/4 T4 $3 | Hardy Orca 1/6 T3 $3

  → Board: 13/2, 9/14, 16/32, 8/2 [Taunt,Reborn], 4/6, 4/8, 5/6
  → Upgrade T5→T6 | Gold: 1→0
  → Actions (3): upgrade, refresh, refresh

**Sneed**  HP=12 Armor=0 Gold=10 Tier=5

  Board: 7/10, 14/2, 14/2, 6/7, 3/8, 3/8, 5/10
  Tavern: Deflect-o-Bot 3/2 T3 $3 | Charging Czarina 4/1 T5 $3 | Dustbone Devastator 3/6 T3 $3 | Ashen Corruptor 6/6 T5 $3 | Catacomb Crasher 5/10 T5 $3

  → Board: 7/10, 14/2, 14/2, 6/7, 3/8, 3/8, 5/10
  → Upgrade T5→T6 | Gold: 1→0
  → Actions (3): upgrade, refresh, refresh

**Overlord Saurfang**  HP=30 Armor=11 Gold=10 Tier=5

  Board: 29/25, 28/26, 34/30, 39/35, 37/38, 35/36, 34/32
  Tavern: Laboratory Assistant 42/39 T2 $3 | Hardy Orca 40/41 T3 $3 | Shadowdancer 42/36 T5 $3 | Spiked Savior 45/35 T5 $3 | Rylak Metalhead 42/36 T4 $3

  → Board: 29/25, 28/26, 34/30, 39/35, 37/38, 35/36, 34/32
  → Upgrade T5→T6 | Gold: 1→0
  → Actions (3): upgrade, refresh, refresh

**Ysera**  HP=20 Armor=0 Gold=10 Tier=5

  Board: 16/32, 5/6, 2/8, 3/8, 4/6, 2/8, 4/5
  Tavern: Hunting Tiger Shark 3/5 T4 $3 | Divine Sparkbot 4/2 T5 $3 | Tichondrius 3/6 T5 $3 | Eternal Tycoon 4/8 T5 $3 | Charging Czarina 4/1 T5 $3 | Twilight Broodmother 5/3 T4 $3

  → Board: 16/32, 5/6, 2/8, 3/8, 4/6, 2/8, 4/5
  → Upgrade T5→T6 | Gold: 1→0
  → Actions (3): upgrade, refresh, refresh

**Inge, the Iron Hymn**  HP=22 Armor=0 Gold=10 Tier=5

  Board: 5/8, 16/2, 16/2, 5/6, 12/23, 6/7, 3/8
  Tavern: Drustfallen Butcher 2/7 T5 $3 | Charging Czarina 4/1 T5 $3 | Nightmare Par-tea Guest 3/3 T5 $3 | Darkcrest Strategist 4/5 T5 $3 | Darkcrest Strategist 4/5 T5 $3

  → Board: 5/8, 16/2, 16/2, 5/6, 12/23, 6/7, 3/8
  → Upgrade T5→T6 | Gold: 1→0
  → Actions (3): upgrade, refresh, refresh

**Professor Putricide**  HP=15 Armor=0 Gold=10 Tier=5

  Board: 6/7, 6/7, 6/4 [Taunt], 4/8, 7/7, 4/9, 7/5
  Tavern: Stomping Stegodon 4/4 T4 $3 | Nightmare Par-tea Guest 3/3 T5 $3 | Rimescale Priestess 3/3 T4 $3 | Annoy-o-Module 2/4 T3 $3 | Monstrous Macaw 5/4 T4 $3

  → Board: 6/7, 6/7, 6/4 [Taunt], 4/8, 7/7, 4/9, 7/5
  → Upgrade T5→T6
  → Actions (2): upgrade, refresh

**Drek'Thar**  HP=30 Armor=3 Gold=10 Tier=5

  Board: 14/14 [DS], 11/12 [DS], 8/14 [DS], 8/14 [DS], 9/14 [DS], 12/9 [DS], 10/14 [DS]
  Tavern: Drustfallen Butcher 8/13 T5 $3 | Friendly Geist 6/3 T4 $3 | Skeletal Strafer 6/6 T5 $3 | Holo Rover 4/4 T4 $3 | Spiked Savior 8/2 T5 $3

  → Board: 14/14 [DS], 11/12 [DS], 8/14 [DS], 8/14 [DS], 9/14 [DS], 12/9 [DS], 10/14 [DS]
  → Upgrade T5→T6 | Gold: 1→0
  → Actions (3): upgrade, refresh, refresh

**Combat Phase**

  Ysera vs Overlord Saurfang (first: Ysera)
     Ysera: [16/32, 5/6, 2/8, 3/8, 4/6, 2/8, 4/5]
     Overlord Saurfang: [29/25, 28/26, 34/30, 39/35, 37/38, 35/36, 34/32]
     Stalwart Kodo 16/32→16/0 DEAD  |  Catacomb Crasher 37/38→37/22
     Imposing Percussionist 29/25→29/23  |  Waverider 2/8→2/0 DEAD
     Technical Element 5/6→5/0 DEAD  |  Hunting Tiger Shark 28/26→28/21
     Hunting Tiger Shark 28/21→28/17  |  Bazaar Dealer 4/6→4/0 DEAD
     Iridescent Skyblazer 4/9→4/0 DEAD  |  Imposing Percussionist 29/23→29/19
     Stomping Stegodon 35/31→35/27  |  Darkcrest Strategist 4/5→4/0 DEAD
     Roaring Recruiter 2/8→3/9  |  Iridescent Skyblazer 40/38→40/36
     Void Pup Trainer 39/35→39/32  |  Roaring Recruiter 3/9→3/0 DEAD
     Result: survivors 0 vs 7 — winner: Overlord Saurfang
  Sneed vs Yogg-Saron, Hope's End (first: Yogg-Saron, Hope's End)
     Sneed: [7/10, 14/2, 14/2, 6/7, 3/8, 3/8, 5/10]
     Yogg-Saron, Hope's End: [13/2, 9/14, 16/32, 8/2, 4/6, 4/8, 5/6]
     Eternal Knight 13/2→14/0 DEAD  |  Catacomb Crasher 5/10→5/0 DEAD
     Wrath Weaver 7/10→7/2  |  Spiked Savior 8/2→8/0 DEAD
     Trigore the Lasher 9/14→9/0 DEAD  |  Eternal Knight 14/2→15/0 DEAD
     Eternal Knight 15/2→16/0 DEAD  |  Technical Element 5/6→5/0 DEAD
     Stalwart Kodo 16/32→16/25  |  Wrath Weaver 7/2→7/0 DEAD
     Zesty Shaker 6/7→6/3  |  Bazaar Dealer 4/6→4/0 DEAD
     Eternal Tycoon 4/8→4/2  |  Zesty Shaker 6/3→6/0 DEAD
     Result: survivors 0 vs 2 — winner: Yogg-Saron, Hope's End
  Inge, the Iron Hymn vs Drek'Thar (first: Drek'Thar)
     Inge, the Iron Hymn: [5/8, 16/2, 16/2, 5/6, 20/31, 6/7, 3/8]
     Drek'Thar: [14/14, 11/12, 8/14, 8/14, 9/14, 12/9, 10/14]
     Floating Watcher 14/14→14/14  |  Lurking Leviathan 3/8→3/0 DEAD
     Wrath Weaver 5/8→5/0 DEAD  |  Waverider 8/14→8/14
     Technical Element 11/12→11/12  |  Zesty Shaker 6/7→6/0 DEAD
     Eternal Knight 16/2→17/0 DEAD  |  Tranquil Meditative 9/14→9/14
     Waverider 8/14→8/14  |  Technical Element 5/6→5/0 DEAD
     Eternal Knight 17/2→18/0 DEAD  |  Technical Element 11/12→11/0 DEAD
     Waverider 8/14→8/0 DEAD  |  Flaming Enforcer 20/31→20/23
     Flaming Enforcer 20/23→20/13  |  Eternal Tycoon 10/14→10/14
     Tranquil Meditative 9/14→9/0 DEAD  |  Flaming Enforcer 20/13→20/0 DEAD
     Result: survivors 0 vs 4 — winner: Drek'Thar

  **Sneed eliminated!** (HP=0, Turn 12)
  Alive: 6/8
  HP: Overlord Saurfang (HP=30, Armor=11, Tier=6) | Drek'Thar (HP=30, Armor=3, Tier=6) | Professor Putricide (HP=15, Armor=0, Tier=6) | Yogg-Saron, Hope's End (HP=12, Armor=0, Tier=6) | Inge, the Iron Hymn (HP=7, Armor=0, Tier=6) | Ysera (HP=5, Armor=0, Tier=6)

### Turn 13

**Yogg-Saron, Hope's End**  HP=12 Armor=0 Gold=10 Tier=6

  Board: 16/2, 9/19, 16/32, 8/2 [Taunt,Reborn], 4/6, 4/8, 5/6
  Tavern: Twisted Wrathguard 8/8 T6 $3 | Wrath Weaver 1/4 T1 $3 | Tichondrius 3/6 T5 $3 | Metallic Hunter 4/2 T2 $3 | Sinrunner Blanchy 8/8 T5 $3 | Tranquil Meditative 3/8 T5 $3

  → Board: 16/2, 9/19, 16/32, 8/8, 8/8 [Reborn], 6/7, 3/10
  → Gold: 1→0
  → Actions (14): sell_board_3, buy_tavern_0, play_hand_2, sell_board_3, buy_tavern_3, play_hand_2, refresh, sell_board_4, buy_tavern_0, play_hand_2, sell_board_3, buy_tavern_0, play_hand_2, refresh

**Overlord Saurfang**  HP=30 Armor=11 Gold=10 Tier=6

  Board: 29/25, 28/26, 34/30, 39/35, 37/38, 35/36, 34/32
  Tavern: Glowscale 41/39 T5 $3 | Flaming Enforcer 41/38 T4 $3 | Glowscale 41/39 T5 $3 | Old Soul 43/39 T2 $3 | Rimescale Priestess 40/36 T4 $3 | Wrath Weaver 40/39 T1 $3

  → Board: 39/35, 37/38, 35/36, 43/39, 41/39 [Taunt], 41/39 [Taunt], 41/38
  → Gold: 1→0
  → Actions (14): sell_board_0, buy_tavern_3, play_hand_2, sell_board_0, buy_tavern_0, play_hand_2, sell_board_0, buy_tavern_1, play_hand_2, sell_board_3, buy_tavern_0, play_hand_2, refresh, refresh

**Ysera**  HP=5 Armor=0 Gold=10 Tier=6

  Board: 16/32, 5/6, 2/8, 3/8, 4/6, 2/8, 4/5
  Tavern: Friendly Geist 6/3 T4 $3 | Goldrinn, the Great Wolf 8/8 T6 $3 | Sly Raptor 1/3 T3 $3 | Ruthless Queensguard 3/3 T6 $3 | Batty Terrorguard 6/2 T6 $3 | Groundbreaker 5/4 T6 $3 | Prized Promo-Drake 1/1 T4 $3

  → Board: 16/32, 5/6, 3/8, 8/8, 8/8, 8/7, 6/7
  → Gold: 1→0
  → Actions (14): sell_board_6, buy_tavern_1, play_hand_8, refresh, sell_board_2, buy_tavern_2, play_hand_8, sell_board_3, buy_tavern_0, play_hand_8, sell_board_3, buy_tavern_0, play_hand_8, refresh

**Inge, the Iron Hymn**  HP=7 Armor=0 Gold=10 Tier=6

  Board: 5/8, 18/2, 18/2, 5/6, 20/31, 6/7, 3/8
  Tavern: Forsaken Weaver 3/10 T6 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Zesty Shaker 6/7 T4 $3 | Tide Raiser 2/1 T2 $3 | Monstrous Macaw 5/4 T4 $3 | Ruthless Queensguard 3/3 T6 $3

  → Board: 18/2, 18/2, 20/31, 3/10, 6/7, 5/10, 5/10
  → Gold: 1→0
  → Actions (14): sell_board_3, buy_tavern_0, play_hand_6, sell_board_5, buy_tavern_1, play_hand_6, refresh, sell_board_0, buy_tavern_1, play_hand_6, sell_board_3, buy_tavern_1, play_hand_6, refresh

**Professor Putricide**  HP=15 Armor=0 Gold=10 Tier=6

  Board: 7/8, 7/8, 7/5 [Taunt], 5/9, 8/8, 5/10, 8/6
  Tavern: Shadowdancer 5/3 T5 $3 | P-0UL-TR-0N 10/10 T6 $3 | Consummate Conqueror 9/7 T6 $3 | Imposing Percussionist 4/4 T4 $3 | Forsaken Weaver 3/10 T6 $3 | P-0UL-TR-0N 10/10 T6 $3

  → Board: 7/8, 7/8, 8/8, 5/10, 10/10, 10/10, 9/7
  → Actions (10): sell_board_2, buy_tavern_1, play_hand_8, sell_board_2, buy_tavern_4, play_hand_8, sell_board_4, buy_tavern_1, play_hand_8, refresh

**Drek'Thar**  HP=30 Armor=3 Gold=10 Tier=6

  Board: 14/14 [DS], 11/12 [DS], 8/14 [DS], 8/14 [DS], 9/14 [DS], 12/9 [DS], 10/14 [DS]
  Tavern: Manasaber 4/1 T1 $3 | Laboratory Assistant 9/10 T2 $3 | Risen Rider 2/1 T1 $3 | Prosthetic Hand 3/1 T4 $3 | Seafloor Recruiter 3/5 T4 $3 | Falling Sky Golem 4/2 T6 $3

  → Board: 20/20 [DS], 11/12 [DS], 8/14 [DS], 9/14 [DS], 10/14 [DS], 14/14 [DS], 9/14 [DS]
  → Gold: 1→0 | Armor: 3→2
  → Actions (12): refresh, sell_board_5, buy_tavern_5, play_hand_3, refresh, refresh, refresh, refresh, sell_board_2, buy_tavern_0, play_hand_3, refresh

**Combat Phase**

  Yogg-Saron, Hope's End vs Overlord Saurfang (first: Overlord Saurfang)
     Yogg-Saron, Hope's End: [16/2, 9/19, 16/32, 8/8, 8/8, 6/7, 3/10]
     Overlord Saurfang: [39/35, 37/38, 35/36, 43/39, 41/39, 41/39, 88/81]
     Void Pup Trainer 39/35→39/19  |  Stalwart Kodo 16/32→16/0 DEAD
     Eternal Knight 16/2→17/0 DEAD  |  Glowscale 41/39→41/23
     Catacomb Crasher 37/38→37/32  |  Tidemistress Athissa 6/7→6/0 DEAD
     Trigore the Lasher 9/19→9/0 DEAD  |  Glowscale 41/39→41/30
     Iridescent Skyblazer 35/36→35/28  |  Sinrunner Blanchy 8/8→8/0 DEAD
     Twisted Wrathguard 8/8→8/0 DEAD  |  Glowscale 41/30→41/22
     Old Soul 43/39→43/36  |  Forsaken Weaver 3/10→3/0 DEAD
     Result: survivors 0 vs 7 — winner: Overlord Saurfang
  Drek'Thar vs Professor Putricide (first: Professor Putricide)
     Drek'Thar: [20/20, 11/12, 8/14, 9/14, 10/14, 14/14, 9/14]
     Professor Putricide: [8/9, 8/9, 9/9, 6/11, 11/11, 11/11, 10/8]
     Technical Element 8/9→8/0 DEAD  |  Floating Watcher 20/20→20/20
     Floating Watcher 20/20→20/9  |  P-0UL-TR-0N 11/11→11/0 DEAD
     Woodland Defiler 8/9→8/0 DEAD  |  Eternal Tycoon 10/14→10/14
     Technical Element 11/12→11/12  |  Lurking Leviathan 6/11→6/0 DEAD
     Skeletal Strafer 9/9→9/0 DEAD  |  Eternal Tycoon 10/14→10/5
     Waverider 8/14→8/4  |  Consummate Conqueror 10/8→10/0 DEAD
     Result: survivors 7 vs 1 — winner: Drek'Thar
  Inge, the Iron Hymn vs Ysera (first: Inge, the Iron Hymn)
     Inge, the Iron Hymn: [18/2, 18/2, 28/39, 3/10, 6/7, 5/10, 5/10]
     Ysera: [16/32, 5/6, 3/8, 8/8, 8/8, 8/7, 6/7]
     Eternal Knight 18/2→19/0 DEAD  |  Stalwart Kodo 16/32→16/14
     Stalwart Kodo 16/14→16/9  |  Ring Bearer 5/10→5/0 DEAD
     Eternal Knight 19/2→20/0 DEAD  |  Iridescent Skyblazer 3/8→3/0 DEAD
     Technical Element 5/6→5/1  |  Ring Bearer 5/10→5/5
     Flaming Enforcer 28/39→28/34  |  Technical Element 5/1→5/0 DEAD
     Goldrinn, the Great Wolf 11/11→11/6  |  Ring Bearer 5/5→5/0 DEAD
     Forsaken Weaver 3/10→3/2  |  Junk Jouster 8/7→8/4
     Moonsteel Juggernaut 8/8→8/0 DEAD  |  Flaming Enforcer 28/34→28/26
     Zesty Shaker 6/7→6/0 DEAD  |  Junk Jouster 8/4→8/0 DEAD
     Tidemistress Athissa 6/7→6/4  |  Forsaken Weaver 3/2→3/0 DEAD
     Result: survivors 1 vs 3 — winner: Inge, the Iron Hymn

  **Yogg-Saron, Hope's End eliminated!** (HP=0, Turn 13)
  Alive: 5/8
  HP: Overlord Saurfang (HP=30, Armor=11, Tier=6) | Drek'Thar (HP=30, Armor=2, Tier=6) | Professor Putricide (HP=15, Armor=0, Tier=6) | Inge, the Iron Hymn (HP=7, Armor=0, Tier=6) | Ysera (HP=5, Armor=0, Tier=6)

### Turn 14

**Overlord Saurfang**  HP=30 Armor=11 Gold=10 Tier=6

  Board: 39/35, 37/38, 35/36, 43/39, 41/39 [Taunt], 41/39 [Taunt], 88/81
  Tavern: Spiked Savior 51/41 T5 $3 | Mummifier 51/43 T3 $3 | Rylak Metalhead 48/42 T4 $3 | Eternal Summoner 52/40 T6 $3 | Eternal Tycoon 48/47 T5 $3 | Ruthless Queensguard 46/42 T6 $3

  → Board: 43/39, 41/39 [Taunt], 88/81, 48/47, 51/43, 51/41 [Taunt,Reborn], 52/40 [Reborn]
  → Gold: 1→0
  → Actions (14): sell_board_2, buy_tavern_4, play_hand_4, sell_board_0, buy_tavern_1, play_hand_4, sell_board_0, buy_tavern_0, play_hand_4, sell_board_1, buy_tavern_1, play_hand_4, refresh, refresh

**Ysera**  HP=5 Armor=0 Gold=10 Tier=6

  Board: 16/32, 5/6, 3/8, 8/8, 8/8, 8/7, 6/7
  Tavern: Friendly Geist 6/3 T4 $3 | Metallic Hunter 4/2 T2 $3 | Prosthetic Hand 3/1 T4 $3 | Junk Jouster 8/7 T6 $3 | Metallic Hunter 4/2 T2 $3 | Enchanted Sentinel 3/5 T4 $3 | Scarlet Survivor 3/3 T1 $3

  → Board: 16/32, 8/8, 8/8, 6/7, 16/14 [G], 7/7, 3/8
  → Gold: 1→0 | Hand: 8→6
  → Actions (19): sell_board_1, play_hand_6, sell_board_1, play_hand_6, sell_board_5, buy_tavern_3, play_hand_6, refresh, sell_board_5, buy_tavern_3, play_hand_6, play_hand_6, buy_tavern_3, play_hand_6, sell_board_5, buy_tavern_1, play_hand_6, refresh, refresh

**Inge, the Iron Hymn**  HP=7 Armor=0 Gold=10 Tier=6

  Board: 20/2, 20/2, 28/39, 3/10, 6/7, 5/10, 5/10
  Tavern: Bazaar Dealer 14/16 T5 $3 | Eternal Summoner 18/11 T6 $3 | Tidemistress Athissa 16/17 T6 $3 | Deathly Striker 18/18 T6 $3 | Sly Raptor 11/13 T3 $3 | Wyvern Outrider 12/18 T4 $3

  → Board: 20/2, 20/2, 28/39, 5/10, 18/18, 16/17
  → HP: 7→4 | Hand: 6→7
  → Actions (8): sell_board_3, buy_tavern_3, play_hand_6, sell_board_3, buy_tavern_2, play_hand_6, sell_board_3, buy_tavern_0

**Professor Putricide**  HP=15 Armor=0 Gold=10 Tier=6

  Board: 8/9, 8/9, 9/9, 6/11, 11/11, 11/11, 10/8
  Tavern: Consummate Conqueror 9/7 T6 $3 | Deathly Striker 8/8 T6 $3 | Batty Terrorguard 6/2 T6 $3 | Ruthless Queensguard 3/3 T6 $3 | Holo Rover 4/4 T4 $3 | Rylak Metalhead 5/3 T4 $3

  → Board: 8/9, 8/9, 9/9, 6/11, 11/11, 11/11, 10/8
  → Actions (1): refresh

**Drek'Thar**  HP=30 Armor=2 Gold=10 Tier=6

  Board: 20/20 [DS], 11/12 [DS], 8/14 [DS], 9/14 [DS], 10/14 [DS], 14/14 [DS], 9/14 [DS]
  Tavern: Rylak Metalhead 11/9 T4 $3 | Darkcrest Strategist 4/5 T5 $3 | Wyvern Outrider 2/8 T4 $3 | Trigore the Lasher 9/3 T4 $3 | Moonsteel Juggernaut 8/8 T6 $3 | Rylak Metalhead 5/3 T4 $3

  → Board: 20/20 [DS], 9/14 [DS], 10/14 [DS], 14/14 [DS], 9/14 [DS], 12/12 [DS], 12/13 [DS]
  → Gold: 1→0
  → Actions (12): refresh, refresh, sell_board_2, buy_tavern_4, play_hand_3, refresh, refresh, sell_board_1, buy_tavern_2, play_hand_3, refresh, refresh

**Combat Phase**

  Inge, the Iron Hymn vs Professor Putricide (first: Professor Putricide)
     Inge, the Iron Hymn: [20/2, 20/2, 40/57, 5/10, 18/18, 16/17]
     Professor Putricide: [9/10, 9/10, 10/10, 7/12, 12/12, 12/12, 11/9]
     Technical Element 9/10→9/0 DEAD  |  Eternal Knight 20/2→21/0 DEAD
     Eternal Knight 21/2→22/0 DEAD  |  Lurking Leviathan 7/12→7/0 DEAD
     Woodland Defiler 9/10→9/5  |  Ring Bearer 5/10→5/1
     Flaming Enforcer 40/57→40/45  |  P-0UL-TR-0N 12/12→12/0 DEAD
     Skeletal Strafer 10/10→10/0 DEAD  |  Deathly Striker 18/18→18/8
     Ring Bearer 5/1→5/0 DEAD  |  Woodland Defiler 9/5→9/0 DEAD
     Consummate Conqueror 11/9→11/0 DEAD  |  Tidemistress Athissa 16/17→16/6
     Tidemistress Athissa 16/6→16/0 DEAD  |  P-0UL-TR-0N 12/12→12/0 DEAD
     Result: survivors 1 vs 0 — winner: Inge, the Iron Hymn
  Drek'Thar vs Ysera (first: Ysera)
     Drek'Thar: [21/21, 10/15, 11/15, 15/15, 10/15, 13/13, 13/14]
     Ysera: [16/32, 8/8, 8/8, 6/7, 16/14, 7/7, 3/8]
     Stalwart Kodo 16/32→16/22  |  Tranquil Meditative 10/15→10/15
     Floating Watcher 21/21→21/21  |  Junk Jouster 16/14→16/0 DEAD
     Goldrinn, the Great Wolf 10/10→10/0 DEAD  |  Tranquil Meditative 10/15→10/5
     Tranquil Meditative 10/15→10/15  |  Iridescent Skyblazer 7/12→7/2
     Moonsteel Juggernaut 8/8→8/0 DEAD  |  One-Amalgam Tour Group 13/14→13/14
     Eternal Tycoon 11/15→11/15  |  Stalwart Kodo 24/30→24/19
     Tidemistress Athissa 6/7→6/0 DEAD  |  Skeletal Strafer 13/13→13/13
     Twisted Wrathguard 15/15→15/15  |  Iridescent Skyblazer 9/4→9/0 DEAD
     Void Pup Trainer 7/7→7/0 DEAD  |  One-Amalgam Tour Group 13/14→13/7
     Tranquil Meditative 10/5→10/0 DEAD  |  Stalwart Kodo 26/21→26/11
     Result: survivors 6 vs 1 — winner: Drek'Thar

  Alive: 5/8
  HP: Overlord Saurfang (HP=30, Armor=11, Tier=6) | Drek'Thar (HP=30, Armor=2, Tier=6) | Ysera (HP=5, Armor=0, Tier=6) | Professor Putricide (HP=5, Armor=0, Tier=6) | Inge, the Iron Hymn (HP=4, Armor=0, Tier=6)

### Turn 15

**Overlord Saurfang**  HP=30 Armor=11 Gold=10 Tier=6

  Board: 43/39, 41/39 [Taunt], 136/131, 48/47, 51/43, 51/41 [Taunt,Reborn], 52/40 [Reborn]
  Tavern: Nightmare Par-tea Guest 50/45 T5 $3 | Reef Riffer 51/46 T2 $3 | Catacomb Crasher 51/52 T5 $3 | Reef Riffer 51/46 T2 $3 | Auto Assembler 48/44 T4 $3 | Bazaar Dealer 50/48 T5 $3

  → Board: 136/131, 48/47, 51/43, 51/52, 50/48, 51/46, 51/46
  → Gold: 1→0
  → Actions (14): sell_board_1, buy_tavern_2, play_hand_3, sell_board_0, buy_tavern_4, play_hand_3, sell_board_3, buy_tavern_1, play_hand_3, sell_board_3, buy_tavern_1, play_hand_3, refresh, refresh

**Ysera**  HP=5 Armor=0 Gold=10 Tier=6

  Board: 16/32, 8/8, 8/8, 6/7, 16/14 [G], 7/7, 3/8
  Tavern: Shadowdancer 5/3 T5 $3 | Maelstrom Emergent 2/7 T5 $3 | Wintergrasp Ghoul 5/3 T5 $3 | Rylak Metalhead 5/3 T4 $3 | Sinrunner Blanchy 8/8 T5 $3 | Void Pup Trainer 7/7 T5 $3 | Blazing Skyfin 2/4 T2 $3

  → Board: 16/32, 8/8, 8/8, 16/14 [G], 8/8, 8/8, 8/8 [Reborn]
  → Gold: 1→0 | Hand: 8→6
  → Actions (17): sell_board_6, play_hand_6, sell_board_3, play_hand_6, sell_board_4, buy_tavern_4, play_hand_6, refresh, refresh, refresh, refresh, refresh, refresh, refresh, refresh, refresh, refresh

**Inge, the Iron Hymn**  HP=4 Armor=0 Gold=10 Tier=6

  Board: 22/2, 22/2, 40/57, 5/10, 18/18, 16/17
  Tavern: Scrap Scraper 24/23 T5 $3 | Forsaken Weaver 21/28 T6 $3 | Forsaken Weaver 21/28 T6 $3 | Bazaar Dealer 22/24 T5 $3 | Shadowdancer 23/21 T5 $3 | Flaming Enforcer 22/23 T4 $3

  → Board: 40/57, 18/18, 21/28, 21/28, 24/23, 22/24, 22/23
  → Gold: 1→0 | Hand: 8→6
  → Actions (19): play_hand_6, sell_board_3, play_hand_6, sell_board_6, buy_tavern_1, play_hand_6, sell_board_0, buy_tavern_1, play_hand_6, sell_board_0, buy_tavern_0, play_hand_6, sell_board_3, buy_tavern_0, play_hand_6, sell_board_2, buy_tavern_1, play_hand_6, refresh

**Professor Putricide**  HP=5 Armor=0 Gold=10 Tier=6

  Board: 9/10, 9/10, 10/10, 7/12, 12/12, 12/12, 11/9
  Tavern: Skeletal Strafer 6/6 T5 $3 | Batty Terrorguard 6/2 T6 $3 | Rabid Panther 4/8 T6 $3 | Banana Slamma 3/6 T4 $3 | Ashen Corruptor 6/6 T5 $3 | Zesty Shaker 6/7 T4 $3

  → Board: 9/10, 9/10, 10/10, 7/12, 12/12, 12/12, 11/9
  → Actions (1): refresh

**Drek'Thar**  HP=30 Armor=2 Gold=10 Tier=6

  Board: 21/21 [DS], 10/15 [DS], 11/15 [DS], 15/15 [DS], 10/15 [DS], 13/13 [DS], 13/14 [DS]
  Tavern: Batty Terrorguard 6/2 T6 $3 | Wyvern Outrider 2/8 T4 $3 | Hunting Tiger Shark 3/5 T4 $3 | Holo Rover 10/10 T4 $3 | Metallic Hunter 4/2 T2 $3 | Twisted Wrathguard 8/8 T6 $3

  → Board: 21/21 [DS], 10/15 [DS], 11/15 [DS], 15/15 [DS], 10/15 [DS], 13/13 [DS], 13/14 [DS]
  → Gold: 1→0
  → Actions (10): refresh, refresh, refresh, refresh, refresh, refresh, refresh, refresh, refresh, refresh

**Combat Phase**

  Ysera vs Overlord Saurfang (first: Ysera)
     Ysera: [16/32, 8/8, 8/8, 16/14, 8/8, 8/8, 8/8]
     Overlord Saurfang: [188/184, 48/47, 51/43, 51/52, 50/48, 51/46, 51/46]
     Stalwart Kodo 16/32→16/0 DEAD  |  Flaming Enforcer 188/184→188/168
     Flaming Enforcer 188/168→188/152  |  Junk Jouster 16/14→16/0 DEAD
     Goldrinn, the Great Wolf 10/10→10/0 DEAD  |  Bazaar Dealer 50/48→50/38
     Eternal Tycoon 48/47→48/39  |  Satellite 8/8→8/0 DEAD
     Moonsteel Juggernaut 8/8→8/0 DEAD  |  Reef Riffer 51/46→51/38
     Mummifier 51/43→51/35  |  Satellite 8/8→8/0 DEAD
     Sinrunner Blanchy 8/8→8/0 DEAD  |  Eternal Tycoon 48/39→48/31
     Result: survivors 0 vs 7 — winner: Overlord Saurfang
  Professor Putricide vs Inge, the Iron Hymn (first: Inge, the Iron Hymn)
     Professor Putricide: [10/11, 10/11, 11/11, 8/13, 13/13, 13/13, 12/10]
     Inge, the Iron Hymn: [63/85, 18/18, 21/28, 21/28, 24/23, 22/24, 46/48]
     Flaming Enforcer 63/85→63/72  |  P-0UL-TR-0N 13/13→13/0 DEAD
     Technical Element 10/11→10/0 DEAD  |  Flaming Enforcer 63/72→63/62
     Deathly Striker 18/18→18/8  |  Woodland Defiler 10/11→10/0 DEAD
     Skeletal Strafer 11/11→11/0 DEAD  |  Flaming Enforcer 63/62→63/51
     Forsaken Weaver 21/28→21/20  |  Lurking Leviathan 8/13→8/0 DEAD
     Consummate Conqueror 12/10→12/0 DEAD  |  Forsaken Weaver 21/20→21/8
     Forsaken Weaver 21/28→21/15  |  P-0UL-TR-0N 13/13→13/0 DEAD
     Result: survivors 0 vs 7 — winner: Inge, the Iron Hymn

  **Ysera eliminated!** (HP=0, Turn 15)
  **Professor Putricide eliminated!** (HP=0, Turn 15)
  Alive: 3/8
  HP: Overlord Saurfang (HP=30, Armor=11, Tier=6) | Drek'Thar (HP=30, Armor=2, Tier=6) | Inge, the Iron Hymn (HP=4, Armor=0, Tier=6)

---

## Final Standings

| # | Hero | HP | Armor | Alive | Eliminated Turn |
|---|---|---|---|---|
| 1 | Overlord Saurfang | 30 | 11 | Yes | — |
| 2 | Drek'Thar | 30 | 2 | Yes | — |
| 3 | Inge, the Iron Hymn | 4 | 0 | Yes | — |
| 4 | Ysera | 0 | 0 | No | 15 |
| 5 | Professor Putricide | 0 | 0 | No | 15 |
| 6 | Yogg-Saron, Hope's End | 0 | 0 | No | 13 |
| 7 | Sneed | 0 | 0 | No | 12 |
| 8 | Sylvanas Windrunner | 0 | 0 | No | 10 |

---

## Agent Strategy

**SearchAgent (greedy)** with GameValueNetwork evaluates each legal action by:

1. Simulate action forward (buy, sell, play, upgrade, refresh, freeze, hero power)
2. Encode resulting POMDP state (61-dim: board embedding + own stats + opponent stats)
3. Evaluate V(s') with GameValueNetwork (MSE-trained to predict expected placement)
4. Choose action with highest V(s'); end turn if no action improves baseline

This is a one-step greedy lookahead using learned value function —
no multi-step planning, no opponent modeling, no combat simulation at decision time.