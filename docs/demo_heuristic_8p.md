# 8-Player Battlegrounds — All Heuristic Demo

**Seed**: 42  |  **Max Turns**: 15  |  **Agents**: 8× Greedy Q-Score Heuristic

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
  Tavern: False Implicator 1/1 T1 $3 | False Implicator 1/1 T1 $3 | Windfall Tornado 4/4 T1 $3 | Sick Riffs (spell) T1 $3

  → Board after: 4/4
  → Gold: 3→0

**Sneed**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Sun-Bacon Relaxer 2/3 T1 $3 | Cord Puller 1/1 T1 $3 | Dune Dweller 3/2 T1 $3 | Tavern Coin (spell) T1 $3

  → Board after: 2/3
  → Gold: 3→0

**Overlord Saurfang**  HP=30 Armor=18 Gold=3 Tier=1

  Board: (empty)
  Tavern: Dune Dweller 4/3 T1 $3 | Sun-Bacon Relaxer 3/4 T1 $3 | Wrath Weaver 2/5 T1 $3 | Windfury + Divine Shield (spell) T1 $3

  → Board after: 4/3
  → Gold: 3→0

**Ysera**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Harmless Bonehead 1/1 T1 $3 | Sun-Bacon Relaxer 2/3 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Pointy Arrow (spell) T1 $3

  → Board after: 2/3
  → Gold: 3→0

**Inge, the Iron Hymn**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: False Implicator 1/1 T1 $3 | Crackling Cyclone 2/1 T1 $3 | Razorfen Geomancer 2/1 T1 $3 | Spare Part (spell) T1 $3

  → Board after: 2/1 [DS,WF]
  → Gold: 3→0

**Professor Putricide**  HP=30 Armor=10 Gold=3 Tier=1

  Board: (empty)
  Tavern: Risen Rider 2/1 T1 $3 | Picky Eater 1/1 T1 $3 | Razorfen Geomancer 2/1 T1 $3 | Meditation (spell) T1 $3

  → Board after: 2/1 [Taunt,Reborn]
  → Gold: 3→0

**Sylvanas Windrunner**  HP=30 Armor=10 Gold=3 Tier=1

  Board: (empty)
  Tavern: Rot Hide Gnoll 1/4 T1 $3 | Windfall Tornado 4/4 T1 $3 | Windfall Tornado 4/4 T1 $3 | Slimy Shield (spell) T1 $3

  → Board after: 4/4
  → Gold: 3→0

**Drek'Thar**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Windfall Tornado 4/4 T1 $3 | Rot Hide Gnoll 1/4 T1 $3 | Rot Hide Gnoll 1/4 T1 $3 | Might of Stormwind (spell) T1 $3

  → Board after: 4/4
  → Gold: 3→0

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=18, Tier=1) | Sneed (HP=30, Armor=12, Tier=1) | Overlord Saurfang (HP=30, Armor=18, Tier=1) | Ysera (HP=30, Armor=10, Tier=1) | Inge, the Iron Hymn (HP=30, Armor=12, Tier=1) | Professor Putricide (HP=30, Armor=8, Tier=1) | Sylvanas Windrunner (HP=30, Armor=10, Tier=1) | Drek'Thar (HP=30, Armor=12, Tier=1)

### Turn 2

**Yogg-Saron, Hope's End**  HP=30 Armor=18 Gold=4 Tier=1

  Board: 4/4
  Tavern: Razorfen Geomancer 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Risen Rider 2/1 T1 $3 | Siren's Song (spell) T1 $3

  → Board after: 4/4, 2/1
  → Gold: 4→0

**Sneed**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 2/3
  Tavern: Wrath Weaver 1/4 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Sun-Bacon Relaxer 2/3 T1 $3 | Meditation (spell) T1 $3

  → Board after: 2/3, 3/6
  → Gold: 4→0 | Armor: 12→11

**Overlord Saurfang**  HP=30 Armor=18 Gold=4 Tier=1

  Board: 4/3
  Tavern: Rot Hide Gnoll 4/7 T1 $3 | Picky Eater 4/4 T1 $3 | Crackling Cyclone 6/5 T1 $3 | Undersea Mount (spell) T1 $3

  → Board after: 4/3, 4/7
  → Gold: 4→0

**Ysera**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 2/3
  Tavern: Crackling Cyclone 2/1 T1 $3 | Crackling Cyclone 2/1 T1 $3 | Windfall Tornado 4/4 T1 $3 | Lantern Light (spell) T1 $3

  → Board after: 2/3, 4/4
  → Gold: 4→0

**Inge, the Iron Hymn**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 2/1 [DS,WF]
  Tavern: Crackling Cyclone 2/1 T1 $3 | Sun-Bacon Relaxer 2/3 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Angler's Lure (spell) T1 $3

  → Board after: 2/1 [DS,WF], 2/3
  → Gold: 4→0

**Professor Putricide**  HP=30 Armor=8 Gold=4 Tier=1

  Board: 2/1 [Taunt,Reborn]
  Tavern: Sun-Bacon Relaxer 2/3 T1 $3 | Dune Dweller 3/2 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Portal in a Bottle (spell) T1 $3

  → Board after: 2/1 [Taunt,Reborn], 2/3
  → Gold: 4→0

**Sylvanas Windrunner**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 4/4
  Tavern: Crackling Cyclone 2/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Picky Eater 1/1 T1 $3 | Temporary Golden Touch (spell) T1 $3

  → Board after: 4/4, 3/6
  → Gold: 4→0 | Armor: 10→9

**Drek'Thar**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 4/4
  Tavern: Rot Hide Gnoll 1/4 T1 $3 | Windfall Tornado 4/4 T1 $3 | Picky Eater 1/1 T1 $3 | Glowing Crown (spell) T1 $3

  → Board after: 4/4, 4/4
  → Gold: 4→0

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=16, Tier=1) | Sneed (HP=30, Armor=11, Tier=1) | Overlord Saurfang (HP=30, Armor=18, Tier=1) | Ysera (HP=30, Armor=10, Tier=1) | Inge, the Iron Hymn (HP=30, Armor=9, Tier=1) | Professor Putricide (HP=30, Armor=6, Tier=1) | Sylvanas Windrunner (HP=30, Armor=9, Tier=1) | Drek'Thar (HP=30, Armor=12, Tier=1)

### Turn 3

**Yogg-Saron, Hope's End**  HP=30 Armor=16 Gold=5 Tier=1

  Board: 4/4, 2/1
  Tavern: Picky Eater 1/1 T1 $3 | Dune Dweller 3/2 T1 $3 | Picky Eater 1/1 T1 $3

  → Board after: 4/4, 2/1, 3/2
  → Gold: 5→0 | Tier: 1→2

**Sneed**  HP=30 Armor=11 Gold=5 Tier=1

  Board: 2/3, 3/6
  Tavern: False Implicator 1/1 T1 $3 | Cord Puller 1/1 T1 $3 | Crackling Cyclone 2/1 T1 $3

  → Board after: 2/3, 3/6, 2/1 [DS,WF]
  → Gold: 5→0 | Tier: 1→2

**Overlord Saurfang**  HP=30 Armor=18 Gold=5 Tier=1

  Board: 4/3, 4/7
  Tavern: False Implicator 6/6 T1 $3 | Razorfen Geomancer 7/6 T1 $3 | Dune Dweller 9/8 T1 $3

  → Board after: 4/3, 4/7, 9/8
  → Gold: 5→0 | Tier: 1→2

**Ysera**  HP=30 Armor=10 Gold=5 Tier=1

  Board: 2/3, 4/4
  Tavern: Wrath Weaver 1/4 T1 $3 | Crackling Cyclone 2/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3

  → Board after: 2/3, 4/4, 3/6
  → Gold: 5→0 | Tier: 1→2 | Armor: 10→9

**Inge, the Iron Hymn**  HP=30 Armor=9 Gold=5 Tier=1

  Board: 2/1 [DS,WF], 2/3
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Picky Eater 1/1 T1 $3 | Sun-Bacon Relaxer 2/3 T1 $3

  → Board after: 2/1 [DS,WF], 2/3, 2/3
  → Gold: 5→0 | Tier: 1→2

**Professor Putricide**  HP=30 Armor=6 Gold=5 Tier=1

  Board: 2/1 [Taunt,Reborn], 2/3
  Tavern: False Implicator 1/1 T1 $3 | Sun-Bacon Relaxer 2/3 T1 $3 | Wrath Weaver 1/4 T1 $3

  → Board after: 2/1 [Taunt,Reborn], 2/3, 2/3
  → Gold: 5→0 | Tier: 1→2

**Sylvanas Windrunner**  HP=30 Armor=9 Gold=5 Tier=1

  Board: 4/4, 3/6
  Tavern: Cord Puller 1/1 T1 $3 | Windfall Tornado 4/4 T1 $3 | Annoy-o-Tron 1/2 T1 $3

  → Board after: 4/4, 3/6, 4/4
  → Gold: 5→0 | Tier: 1→2

**Drek'Thar**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 4/4, 4/4
  Tavern: Harmless Bonehead 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | False Implicator 1/1 T1 $3

  → Board after: 4/4, 4/4, 3/6
  → Gold: 5→0 | Tier: 1→2 | Armor: 12→11

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=13, Tier=2) | Sneed (HP=30, Armor=6, Tier=2) | Overlord Saurfang (HP=30, Armor=18, Tier=2) | Ysera (HP=30, Armor=9, Tier=2) | Inge, the Iron Hymn (HP=30, Armor=4, Tier=2) | Professor Putricide (HP=30, Armor=3, Tier=2) | Sylvanas Windrunner (HP=30, Armor=9, Tier=2) | Drek'Thar (HP=30, Armor=11, Tier=2)

### Turn 4

**Yogg-Saron, Hope's End**  HP=30 Armor=13 Gold=6 Tier=2

  Board: 4/4, 2/1, 3/2
  Tavern: Ancestral Automaton 3/4 T2 $3 | Old Soul 3/4 T2 $3 | Eternal Knight 4/2 T2 $3 | Metallic Hunter 2/1 T2 $3 | Chef's Choice (spell) T2 $3

  → Board after: 4/4, 2/1, 3/2, 3/4, 3/4
  → Gold: 6→0

**Sneed**  HP=30 Armor=6 Gold=6 Tier=2

  Board: 2/3, 3/6, 2/1 [DS,WF]
  Tavern: Risen Rider 2/1 T1 $3 | Risen Rider 2/1 T1 $3 | Glowgullet Warlord 2/2 T2 $3 | Fire Baller 4/3 T2 $3

  → Board after: 2/3, 3/6, 2/1 [DS,WF], 4/3, 2/2
  → Gold: 6→0

**Overlord Saurfang**  HP=30 Armor=18 Gold=6 Tier=2

  Board: 4/3, 4/7, 9/8
  Tavern: Glowgullet Warlord 9/9 T2 $3 | Metallic Hunter 9/8 T2 $3 | Old Soul 10/11 T2 $3 | Sun-Bacon Relaxer 9/10 T1 $3

  → Board after: 4/3, 4/7, 9/8, 10/11, 9/10
  → Gold: 6→0

**Ysera**  HP=30 Armor=9 Gold=6 Tier=2

  Board: 2/3, 4/4, 3/6
  Tavern: Rot Hide Gnoll 1/4 T1 $3 | Picky Eater 1/1 T1 $3 | Metallic Hunter 2/1 T2 $3 | Fire Baller 4/3 T2 $3

  → Board after: 2/3, 4/4, 3/6, 4/3, 1/4
  → Gold: 6→0

**Inge, the Iron Hymn**  HP=30 Armor=4 Gold=6 Tier=2

  Board: 2/1 [DS,WF], 2/3, 2/3
  Tavern: Harmless Bonehead 1/1 T1 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Wrath Weaver 1/4 T1 $3 | Wrath Weaver 1/4 T1 $3

  → Board after: 2/1 [DS,WF], 2/3, 2/3, 2/4, 3/6
  → Gold: 6→0 | Armor: 4→3

**Professor Putricide**  HP=30 Armor=3 Gold=6 Tier=2

  Board: 2/1 [Taunt,Reborn], 2/3, 2/3
  Tavern: Ancestral Automaton 3/4 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Cord Puller 1/1 T1 $3 | Old Soul 3/4 T2 $3

  → Board after: 2/1 [Taunt,Reborn], 2/3, 2/3, 3/4, 3/4
  → Gold: 6→0

**Sylvanas Windrunner**  HP=30 Armor=9 Gold=6 Tier=2

  Board: 4/4, 3/6, 4/4
  Tavern: Wrath Weaver 1/4 T1 $3 | Scarlet Skull 2/1 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3

  → Board after: 4/4, 7/10, 4/4, 3/4, 3/6
  → Gold: 6→0 | Armor: 9→6

**Drek'Thar**  HP=30 Armor=11 Gold=6 Tier=2

  Board: 4/4, 4/4, 3/6
  Tavern: Risen Rider 2/1 T1 $3 | Laboratory Assistant 3/4 T2 $3 | Sellemental 3/3 T2 $3 | Rot Hide Gnoll 1/4 T1 $3

  → Board after: 4/4, 4/4, 5/8, 3/4, 3/3
  → Gold: 6→0 | Armor: 11→10

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=13, Tier=2) | Overlord Saurfang (HP=30, Armor=18, Tier=2) | Ysera (HP=30, Armor=9, Tier=2) | Sylvanas Windrunner (HP=30, Armor=6, Tier=2) | Drek'Thar (HP=30, Armor=10, Tier=2) | Sneed (HP=29, Armor=0, Tier=2) | Professor Putricide (HP=29, Armor=0, Tier=2) | Inge, the Iron Hymn (HP=27, Armor=0, Tier=2)

### Turn 5

**Yogg-Saron, Hope's End**  HP=30 Armor=13 Gold=7 Tier=2

  Board: 4/4, 2/1, 3/2, 3/4, 3/4
  Tavern: Picky Eater 1/1 T1 $3 | Picky Eater 1/1 T1 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Glowgullet Warlord 2/2 T2 $3

  → Gold: 7→0 | Tier: 2→3

**Sneed**  HP=29 Armor=0 Gold=7 Tier=2

  Board: 2/3, 3/6, 2/1 [DS,WF], 4/3, 2/2
  Tavern: Cord Puller 1/1 T1 $3 | Scarlet Skull 2/1 T2 $3 | Razorfen Geomancer 2/1 T1 $3 | Risen Rider 2/1 T1 $3

  → Gold: 7→0 | Tier: 2→3

**Overlord Saurfang**  HP=30 Armor=18 Gold=7 Tier=2

  Board: 4/3, 4/7, 9/8, 10/11, 9/10
  Tavern: Laboratory Assistant 14/15 T2 $3 | Ancestral Automaton 3/15 T2 $3 | Fire Baller 17/16 T2 $3 | Scarlet Skull 13/12 T2 $3

  → Gold: 7→0 | Tier: 2→3

**Ysera**  HP=30 Armor=9 Gold=7 Tier=2

  Board: 2/3, 4/4, 3/6, 4/3, 1/4
  Tavern: Eternal Knight 4/2 T2 $3 | Snow Baller 3/4 T2 $3 | Scarlet Skull 2/1 T2 $3 | Soul Rewinder 4/1 T2 $3

  → Gold: 7→0 | Tier: 2→3

**Inge, the Iron Hymn**  HP=27 Armor=0 Gold=7 Tier=2

  Board: 2/1 [DS,WF], 2/3, 2/3, 2/4, 3/6
  Tavern: Old Soul 4/4 T2 $3 | Dune Dweller 3/2 T1 $3 | Fire Baller 4/3 T2 $3 | Bristleback Bully 3/2 T2 $3

  → Gold: 7→0 | Tier: 2→3

**Professor Putricide**  HP=29 Armor=0 Gold=7 Tier=2

  Board: 2/1 [Taunt,Reborn], 2/3, 2/3, 3/4, 3/4
  Tavern: Snow Baller 3/4 T2 $3 | Risen Rider 2/1 T1 $3 | False Implicator 1/1 T1 $3 | Bristleback Bully 3/2 T2 $3

  → Gold: 7→0 | Tier: 2→3

**Sylvanas Windrunner**  HP=30 Armor=6 Gold=7 Tier=2

  Board: 4/4, 7/10, 4/4, 3/4, 3/6
  Tavern: Risen Rider 2/1 T1 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Sellemental 3/3 T2 $3 | Soul Rewinder 4/1 T2 $3

  → Gold: 7→0 | Tier: 2→3

**Drek'Thar**  HP=30 Armor=10 Gold=7 Tier=2

  Board: 4/4, 4/4, 5/8, 3/4, 3/3
  Tavern: Glowgullet Warlord 2/2 T2 $3 | Risen Rider 2/1 T1 $3 | Scarlet Skull 2/1 T2 $3 | Old Soul 3/4 T2 $3

  → Gold: 7→0 | Tier: 2→3

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=5, Tier=3) | Overlord Saurfang (HP=30, Armor=18, Tier=3) | Ysera (HP=30, Armor=2, Tier=3) | Sylvanas Windrunner (HP=30, Armor=6, Tier=3) | Drek'Thar (HP=30, Armor=10, Tier=3) | Inge, the Iron Hymn (HP=27, Armor=0, Tier=3) | Professor Putricide (HP=25, Armor=0, Tier=3) | Sneed (HP=23, Armor=0, Tier=3)

### Turn 6

**Yogg-Saron, Hope's End**  HP=30 Armor=5 Gold=8 Tier=3

  Board: 4/4, 2/1, 3/2, 3/4, 3/4
  Tavern: Waveling 7/2 T3 $3 | Floating Watcher 4/4 T3 $5 | Old Soul 3/4 T2 $3 | Sellemental 4/4 T2 $3

  → Board after: 4/4, 2/1, 3/2, 3/4, 3/4, 7/2, 4/4
  → Gold: 8→0

**Sneed**  HP=23 Armor=0 Gold=8 Tier=3

  Board: 2/3, 3/6, 2/1 [DS,WF], 4/3, 2/2
  Tavern: Prickly Piper 5/1 T3 $3 | Felemental 3/3 T3 $3 | Annoy-o-Tron 1/2 T1 $3 | Bristleback Bully 3/2 T2 $3

  → Board after: 2/3, 3/6, 4/3, 2/2, 5/1, 3/3, 3/2 [Taunt]
  → Gold: 8→0

**Overlord Saurfang**  HP=30 Armor=18 Gold=8 Tier=3

  Board: 4/3, 14/7, 9/8, 20/11, 9/10
  Tavern: Moon-Bacon Jazzer 13/16 T3 $3 | Scarlet Skull 23/12 T2 $3 | Snow Baller 16/17 T2 $3 | Sun-Bacon Relaxer 13/14 T1 $3

  → Board after: 14/7, 9/8, 20/11, 9/10, 23/12 [Reborn], 16/17, 13/16
  → Gold: 8→0

**Ysera**  HP=30 Armor=2 Gold=8 Tier=3

  Board: 2/3, 4/4, 3/6, 4/3, 1/4
  Tavern: Waveling 6/1 T3 $3 | Bristlemane Scrapsmith 4/4 T3 $3 | False Implicator 1/1 T1 $3 | Leeching Felhound 3/3 T3 $3

  → Board after: 4/4, 5/8, 4/3, 1/4, 4/4, 6/1, 3/3
  → Gold: 8→0 | Armor: 2→1

**Inge, the Iron Hymn**  HP=27 Armor=0 Gold=8 Tier=3

  Board: 2/1 [DS,WF], 2/3, 2/3, 2/4, 3/6
  Tavern: Accord-o-Tron 3/3 T3 $3 | Dustbone Devastator 3/6 T3 $3 | Annoy-o-Module 2/4 T3 $3 | Annoy-o-Module 2/4 T3 $3

  → Board after: 2/3, 2/3, 2/4, 3/6, 3/6, 3/3, 2/4 [Taunt,DS]
  → Gold: 8→0

**Professor Putricide**  HP=25 Armor=0 Gold=8 Tier=3

  Board: 2/1 [Taunt,Reborn], 2/3, 2/3, 3/4, 3/4
  Tavern: Floating Watcher 4/4 T3 $5 | Skulking Bristlemane 5/2 T3 $3 | Scarlet Skull 2/1 T2 $3 | Alert Alarmist 1/1 T2 $3

  → Board after: 2/1 [Taunt,Reborn], 2/3, 2/3, 3/4, 3/4, 4/4, 5/2 [Taunt]
  → Gold: 8→0

**Sylvanas Windrunner**  HP=30 Armor=6 Gold=8 Tier=3

  Board: 4/4, 7/10, 4/4, 3/4, 3/6
  Tavern: Bristlemane Scrapsmith 4/4 T3 $3 | Rot Hide Gnoll 1/4 T1 $3 | Skulking Bristlemane 5/2 T3 $3 | Laboratory Assistant 3/4 T2 $3

  → Board after: 4/4, 9/12, 4/4, 5/8, 4/4, 5/2 [Taunt], 3/4
  → Gold: 8→0 | Armor: 6→4

**Drek'Thar**  HP=30 Armor=10 Gold=8 Tier=3

  Board: 4/4, 4/4, 5/8, 3/4, 3/3
  Tavern: Cadaver Caretaker 3/3 T3 $3 | Laboratory Assistant 3/4 T2 $3 | Skulking Bristlemane 5/2 T3 $3 | Wrath Weaver 1/4 T1 $3

  → Board after: 4/4, 4/4, 11/14, 3/4, 3/4, 5/2 [Taunt], 3/3
  → Gold: 8→0 | Armor: 10→9

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=5, Tier=3) | Overlord Saurfang (HP=30, Armor=18, Tier=3) | Sylvanas Windrunner (HP=30, Armor=4, Tier=3) | Drek'Thar (HP=30, Armor=9, Tier=3) | Inge, the Iron Hymn (HP=27, Armor=0, Tier=3) | Professor Putricide (HP=25, Armor=0, Tier=3) | Sneed (HP=23, Armor=0, Tier=3) | Ysera (HP=21, Armor=0, Tier=3)

### Turn 7

**Yogg-Saron, Hope's End**  HP=30 Armor=5 Gold=9 Tier=3

  Board: 4/4, 2/1, 3/2, 3/4, 3/4, 7/2, 4/4
  Tavern: Cadaver Caretaker 3/3 T3 $3 | Wildfire Elemental 7/4 T3 $3 | Harmless Bonehead 1/1 T1 $3 | Handless Forsaken 2/1 T3 $3

  → Board after: 4/4, 3/2, 3/4, 3/4, 7/2, 4/4, 7/4
  → Gold: 9→0 | Tier: 3→4

**Sneed**  HP=23 Armor=0 Gold=9 Tier=3

  Board: 2/3, 3/6, 4/3, 2/2, 5/1, 3/3, 3/2 [Taunt]
  Tavern: Sellemental 4/4 T2 $3 | Technical Element 6/7 T3 $3 | Prickly Piper 6/2 T3 $3 | Scarlet Skull 9/8 T2 $3

  → Board after: 2/3, 3/6, 4/3, 5/1, 3/3, 3/2 [Taunt], 9/8 [DS,Reborn]
  → Gold: 9→0 | Tier: 3→4

**Overlord Saurfang**  HP=30 Armor=18 Gold=9 Tier=3

  Board: 14/7, 9/8, 20/11, 9/10, 23/12 [Reborn], 16/17, 13/16
  Tavern: Felemental 21/21 T3 $3 | Sellemental 21/21 T2 $3 | Snow Baller 21/22 T2 $3 | Eternal Knight 4/18 T2 $3

  → Board after: 14/7, 20/11, 9/10, 23/12 [Reborn], 16/17, 13/16, 21/22
  → Gold: 9→0 | Tier: 3→4

**Ysera**  HP=21 Armor=0 Gold=9 Tier=3

  Board: 4/4, 5/8, 4/3, 1/4, 4/4, 6/1, 3/3
  Tavern: Dustbone Devastator 5/7 T3 $3 | Annoy-o-Module 2/4 T3 $3 | False Implicator 1/1 T1 $3 | Wildfire Elemental 6/3 T3 $3

  → Board after: 4/4, 5/8, 4/3, 4/4, 6/1, 3/3, 5/7
  → Gold: 9→0 | Tier: 3→4

**Inge, the Iron Hymn**  HP=27 Armor=0 Gold=10 Tier=3

  Board: 2/3, 2/3, 3/4, 3/6, 4/6, 3/3, 2/4 [Taunt,DS]
  Tavern: Bristlemane Scrapsmith 4/4 T3 $3 | Soul Rewinder 4/1 T2 $3 | Nerubian Deathswarmer 3/4 T2 $3 | Annoy-o-Module 2/4 T3 $3

  → Board after: 4/4, 3/6, 5/6, 3/3, 2/4 [Taunt,DS], 4/4, 4/4
  → Gold: 10→0 | Tier: 3→4

**Professor Putricide**  HP=25 Armor=0 Gold=9 Tier=3

  Board: 2/1 [Taunt,Reborn], 2/3, 2/3, 3/4, 3/4, 4/4, 5/2 [Taunt]
  Tavern: Accord-o-Tron 3/3 T3 $3 | Pufferquil 2/6 T3 $3 | Picky Eater 1/1 T1 $3 | Prickly Piper 5/1 T3 $3

  → Board after: 2/3, 2/3, 3/4, 3/4, 4/4, 5/2 [Taunt], 2/6
  → Gold: 9→0 | Tier: 3→4

**Sylvanas Windrunner**  HP=30 Armor=4 Gold=9 Tier=3

  Board: 4/4, 9/12, 4/4, 5/8, 4/4, 5/2 [Taunt], 3/4
  Tavern: Metallic Hunter 2/1 T2 $3 | Crackling Cyclone 2/1 T1 $3 | Pufferquil 2/6 T3 $3 | Crackling Cyclone 2/1 T1 $3

  → Board after: 4/4, 9/12, 4/4, 5/8, 4/4, 3/4, 2/6
  → Gold: 9→0 | Tier: 3→4

**Drek'Thar**  HP=30 Armor=9 Gold=9 Tier=3

  Board: 4/4, 4/4, 11/14, 3/4, 3/4, 5/2 [Taunt], 3/3
  Tavern: Annoy-o-Module 2/4 T3 $3 | Prickly Piper 5/1 T3 $3 | Mummifier 5/2 T3 $3 | Technical Element 5/6 T3 $3

  → Board after: 4/4, 4/4, 11/14, 3/4, 3/4, 5/2 [Taunt], 5/6
  → Gold: 9→0 | Tier: 3→4

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Overlord Saurfang (HP=30, Armor=18, Tier=4) | Sylvanas Windrunner (HP=30, Armor=4, Tier=4) | Drek'Thar (HP=30, Armor=9, Tier=4) | Yogg-Saron, Hope's End (HP=25, Armor=0, Tier=4) | Ysera (HP=21, Armor=0, Tier=4) | Inge, the Iron Hymn (HP=17, Armor=0, Tier=4) | Professor Putricide (HP=17, Armor=0, Tier=4) | Sneed (HP=16, Armor=0, Tier=4)

### Turn 8

**Yogg-Saron, Hope's End**  HP=25 Armor=0 Gold=10 Tier=4

  Board: 4/4, 3/2, 3/4, 3/4, 7/2, 4/4, 7/4
  Tavern: Rot Hide Gnoll 1/4 T1 $3 | Cord Puller 1/1 T1 $3 | Rot Hide Gnoll 1/4 T1 $3 | Accord-o-Tron 3/3 T3 $3 | Sellemental 7/5 T2 $3 | Friendly Bounty (spell) T4 $3

  → Board after: 4/4, 3/4, 7/2, 4/4, 7/4, 7/5, 1/1 [DS]
  → Gold: 10→0

**Sneed**  HP=16 Armor=0 Gold=10 Tier=4

  Board: 2/3, 3/6, 4/3, 5/1, 3/3, 3/2 [Taunt], 9/8 [DS,Reborn]
  Tavern: Laboratory Assistant 4/5 T2 $3 | Leeching Felhound 10/10 T3 $3 | Metallic Hunter 3/2 T2 $3 | Enchanted Sentinel 4/6 T4 $3 | Snow Baller 4/5 T2 $3 | Forest's Bounty (spell) T4 $3

  → Board after: 7/10, 9/8 [DS,Reborn], 10/10 [DS], 4/6, 4/5, 4/5, 3/2
  → Gold: 10→0 | HP: 16→14

**Overlord Saurfang**  HP=30 Armor=18 Gold=10 Tier=4

  Board: 14/7, 20/11, 9/10, 23/12 [Reborn], 16/17, 13/16, 21/22
  Tavern: Enchanted Sentinel 21/23 T4 $3 | Prickly Piper 23/19 T3 $3 | Geomagus Roogug 22/24 T4 $3 | Bristleback Bully 21/20 T2 $3 | Snow Baller 23/24 T2 $3 | Hostile Bounty (spell) T4 $3

  → Board after: 14/7, 20/11, 23/12 [Reborn], 57/59 [G], 22/24 [DS], 21/23, 23/19
  → Gold: 10→0

**Ysera**  HP=21 Armor=0 Gold=10 Tier=4

  Board: 4/4, 5/8, 4/3, 4/4, 6/1, 3/3, 5/7
  Tavern: Annoy-o-Module 5/5 T3 $3 | Fire Baller 7/4 T2 $3 | Risen Rider 2/1 T1 $3 | Annoy-o-Module 2/4 T3 $3 | Fearless Foodie 2/4 T4 $3 | Selfish Bounty (spell) T4 $3

  → Board after: 4/4, 5/8, 4/4, 5/7, 7/4, 5/5 [Taunt,DS], 2/1 [Taunt,Reborn]
  → Gold: 10→0

**Inge, the Iron Hymn**  HP=17 Armor=0 Gold=11 Tier=4

  Board: 5/4, 3/6, 6/6, 3/3, 2/4 [Taunt,DS], 5/4, 4/4
  Tavern: Moon-Bacon Jazzer 2/5 T3 $3 | Soul Rewinder 4/1 T2 $3 | Waveling 6/1 T3 $3 | Metallic Hunter 2/1 T2 $3 | Dune Dweller 3/2 T1 $3

  → Board after: 5/4, 5/8, 6/6, 5/4, 4/4, 6/1, 2/1
  → Gold: 11→0 | HP: 17→16

**Professor Putricide**  HP=17 Armor=0 Gold=10 Tier=4

  Board: 2/3, 2/3, 3/4, 3/4, 4/4, 5/2 [Taunt], 2/6
  Tavern: Imposing Percussionist 4/4 T4 $3 | En-Djinn Blazer 4/4 T4 $3 | Fearless Foodie 2/4 T4 $3 | Eternal Knight 4/2 T2 $3 | Tavern Tempest 2/2 T4 $3

  → Board after: 3/4, 6/6, 5/2 [Taunt], 2/6, 4/4, 4/4, 2/2
  → Gold: 10→0 | HP: 17→15

**Sylvanas Windrunner**  HP=30 Armor=4 Gold=10 Tier=4

  Board: 4/4, 9/12, 4/4, 5/8, 4/4, 3/4, 2/6
  Tavern: Malchezaar, Prince of Dance 5/4 T4 $3 | Razorfen Geomancer 2/1 T1 $3 | Plaguerunner 4/2 T4 $3 | Prosthetic Hand 3/1 T4 $3 | Fire Baller 4/3 T2 $3

  → Board after: 11/14, 4/4, 7/10, 4/4, 2/6, 5/4, 2/1
  → Gold: 10→0 | Armor: 4→2

**Drek'Thar**  HP=30 Armor=9 Gold=10 Tier=4

  Board: 4/4, 4/4, 11/14, 3/4, 3/4, 5/2 [Taunt], 5/6
  Tavern: Fearless Foodie 2/4 T4 $3 | Hired Ritualist 5/7 T4 $3 | Alert Alarmist 1/1 T2 $3 | Woodland Defiler 5/6 T4 $3 | Sellemental 3/3 T2 $3

  → Board after: 4/4, 4/4, 13/16, 5/6, 5/7, 5/6, 1/1 [Taunt]
  → Gold: 10→0 | Armor: 9→8

**⚔ Combat Phase**

  💀 **Professor Putricide eliminated!** (HP=0, Turn 8)
  Alive: 7/8
  HP standings: Overlord Saurfang (HP=30, Armor=18, Tier=4) | Sylvanas Windrunner (HP=30, Armor=2, Tier=4) | Drek'Thar (HP=30, Armor=8, Tier=4) | Ysera (HP=21, Armor=0, Tier=4) | Sneed (HP=14, Armor=0, Tier=4) | Inge, the Iron Hymn (HP=11, Armor=0, Tier=4) | Yogg-Saron, Hope's End (HP=10, Armor=0, Tier=4)

### Turn 9

**Yogg-Saron, Hope's End**  HP=10 Armor=0 Gold=10 Tier=4

  Board: 4/4, 3/4, 7/2, 4/4, 7/4, 7/5, 1/1 [DS]
  Tavern: Tavern Tempest 3/3 T4 $3 | Technical Element 8/7 T3 $3 | Soul Rewinder 7/2 T2 $3 | Glowgullet Warlord 2/2 T2 $3 | Skulking Bristlemane 5/2 T3 $3

  → Board after: 4/4, 3/4, 7/2, 4/4, 7/4, 7/5, 8/7
  → Gold: 10→0 | Tier: 4→5

**Sneed**  HP=14 Armor=0 Gold=10 Tier=4

  Board: 7/10, 9/8 [DS,Reborn], 10/10 [DS], 4/6, 4/5, 4/5, 3/2
  Tavern: Ancestral Automaton 3/11 T2 $3 | Waveling 7/2 T3 $3 | Razorfen Geomancer 3/2 T1 $3 | Metallic Hunter 3/2 T2 $3 | Cadaver Caretaker 4/4 T3 $3

  → Board after: 7/10, 9/8 [DS,Reborn], 10/10 [DS], 4/6, 4/5, 4/5, 3/11 [DS]
  → Gold: 10→0 | Tier: 4→5

**Overlord Saurfang**  HP=30 Armor=18 Gold=10 Tier=4

  Board: 14/7, 20/11, 23/12 [Reborn], 57/59 [G], 22/24 [DS], 21/23, 23/19
  Tavern: Dustbone Devastator 40/34 T3 $3 | Glowgullet Warlord 30/30 T2 $3 | Leyline Surfacer 34/36 T4 $3 | Soul Rewinder 32/29 T2 $3 | Razorfen Geomancer 30/29 T1 $3

  → Board after: 20/11, 23/12 [Reborn], 57/59 [G], 22/24 [DS], 21/23, 23/19, 40/34
  → Gold: 10→0 | Tier: 4→5

**Ysera**  HP=21 Armor=0 Gold=10 Tier=4

  Board: 4/4, 5/8, 4/4, 6/7, 7/4, 5/5 [Taunt,DS], 3/1 [Taunt,Reborn]
  Tavern: Skulking Bristlemane 8/3 T3 $3 | Hired Ritualist 8/8 T4 $3 | Leyline Surfacer 4/6 T4 $3 | En-Djinn Blazer 4/4 T4 $3 | Accord-o-Tron 3/3 T3 $3

  → Board after: 4/4, 5/8, 4/4, 6/7, 7/4, 5/5 [Taunt,DS], 8/8
  → Gold: 10→0 | Tier: 4→5

**Inge, the Iron Hymn**  HP=11 Armor=0 Gold=10 Tier=4

  Board: 6/4, 5/8, 7/6, 6/4, 4/4, 6/1, 2/1
  Tavern: Prickly Piper 5/1 T3 $3 | Leyline Surfacer 5/7 T4 $3 | Snow Baller 4/5 T2 $3 | Dune Dweller 7/4 T1 $3 | Auto Assembler 2/2 T4 $3

  → Board after: 6/4, 5/8, 7/6, 6/4, 4/4, 6/1, 5/7
  → Gold: 10→0 | Tier: 4→5

**Sylvanas Windrunner**  HP=30 Armor=2 Gold=10 Tier=4

  Board: 11/14, 4/4, 7/10, 4/4, 2/6, 5/4, 2/1
  Tavern: Eternal Knight 4/2 T2 $3 | Crackling Cyclone 2/1 T1 $3 | Alert Alarmist 1/1 T2 $3 | Alert Alarmist 1/1 T2 $3 | Floating Watcher 4/4 T3 $5

  → Board after: 11/14, 4/4, 7/10, 4/4, 2/6, 5/4, 4/2
  → Gold: 10→0 | Tier: 4→5

**Drek'Thar**  HP=30 Armor=8 Gold=10 Tier=4

  Board: 4/4, 4/4, 13/16, 5/6, 5/7, 5/6, 1/1 [Taunt]
  Tavern: Nerubian Deathswarmer 1/4 T2 $3 | Prickly Piper 5/1 T3 $3 | Metallic Hunter 2/1 T2 $3 | Plaguerunner 4/2 T4 $3 | Felemental 3/3 T3 $3

  → Board after: 4/4, 4/4, 13/16, 5/6, 5/7, 5/6, 5/1
  → Gold: 10→0 | Tier: 4→5

**⚔ Combat Phase**

  Alive: 7/8
  HP standings: Overlord Saurfang (HP=30, Armor=18, Tier=5) | Sylvanas Windrunner (HP=30, Armor=2, Tier=5) | Drek'Thar (HP=30, Armor=8, Tier=5) | Ysera (HP=21, Armor=0, Tier=5) | Sneed (HP=14, Armor=0, Tier=5) | Yogg-Saron, Hope's End (HP=10, Armor=0, Tier=5) | Inge, the Iron Hymn (HP=2, Armor=0, Tier=5)

### Turn 10

**Yogg-Saron, Hope's End**  HP=10 Armor=0 Gold=10 Tier=5

  Board: 4/4, 3/4, 7/2, 4/4, 7/4, 7/5, 8/7
  Tavern: Nightmare Par-tea Guest 4/4 T5 $3 | Annoy-o-Tron 4/3 T1 $3 | Ancestral Automaton 3/5 T2 $3 | Tavern Tempest 6/4 T4 $3 | Tichondrius 3/6 T5 $3

  → Board after: 7/2, 7/4, 7/5, 8/7, 6/4, 3/6, 4/3 [Taunt,DS]
  → Gold: 10→0

**Sneed**  HP=14 Armor=0 Gold=10 Tier=5

  Board: 7/10, 9/8 [DS,Reborn], 10/10 [DS], 4/6, 4/5, 4/5, 3/11 [DS]
  Tavern: Ashen Corruptor 7/7 T5 $3 | Hired Ritualist 6/8 T4 $3 | Void Pup Trainer 8/8 T5 $3 | Sinrunner Blanchy 15/15 T5 $3 | Soul Rewinder 5/2 T2 $3

  → Board after: 17/22, 9/8 [DS,Reborn], 10/10 [DS], 15/15 [DS,Reborn], 13/10, 7/7, 10/10 [DS]
  → Gold: 10→0 | HP: 14→12

**Overlord Saurfang**  HP=30 Armor=18 Gold=10 Tier=5

  Board: 20/11, 23/12 [Reborn], 57/59 [G], 22/24 [DS], 21/23, 23/19, 40/34
  Tavern: En-Djinn Blazer 36/36 T4 $3 | Imposing Percussionist 34/34 T4 $3 | Malchezaar, Prince of Dance 35/34 T4 $3 | Snow Baller 35/36 T2 $3 | Ancestral Automaton 3/34 T2 $3

  → Board after: 57/59 [G], 40/34, 36/36, 35/36, 35/34, 34/34, 3/34
  → Gold: 10→0 | Armor: 18→11

**Ysera**  HP=21 Armor=0 Gold=10 Tier=5

  Board: 4/4, 5/8, 4/4, 6/7, 7/4, 5/5 [Taunt,DS], 8/8
  Tavern: Imposing Percussionist 7/5 T4 $3 | Woodland Defiler 5/6 T4 $3 | Gem Smuggler 4/5 T5 $3 | Deflect-o-Bot 3/2 T3 $3 | En-Djinn Blazer 7/5 T4 $3

  → Board after: 12/14, 9/9, 11/10, 10/7, 10/7, 8/8, 3/2 [DS]
  → Gold: 10→0 | HP: 21→17

**Inge, the Iron Hymn**  HP=2 Armor=0 Gold=10 Tier=5

  Board: 7/4, 5/8, 8/6, 7/4, 4/4, 6/1, 5/7
  Tavern: Refreshing Anomaly 8/7 T4 $3 | Scarlet Skull 8/1 T2 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Technical Element 8/7 T3 $3 | Imposing Percussionist 4/4 T4 $3

  → Board after: 7/4, 8/6, 7/4, 8/7, 8/1 [Reborn], 8/7, 4/4
  → Gold: 10→0 | HP: 2→0

**Sylvanas Windrunner**  HP=30 Armor=2 Gold=10 Tier=5

  Board: 11/14, 4/4, 7/10, 4/4, 2/6, 5/4, 5/2
  Tavern: Living Azerite 6/5 T5 $3 | False Implicator 1/1 T1 $3 | Hot-Air Surveyor 4/8 T5 $3 | Darkgaze Elder 6/8 T5 $3 | Redtusk Thornraiser 3/7 T4 $3

  → Board after: 13/16, 9/12, 6/8, 4/8, 6/5, 3/7, 2/2 [G]
  → Gold: 10→0 | Armor: 2→0

**Drek'Thar**  HP=30 Armor=8 Gold=10 Tier=5

  Board: 4/4, 4/4, 13/16, 5/6, 5/7, 5/6, 5/1
  Tavern: Rot Hide Gnoll 1/4 T1 $3 | Bristlemane Scrapsmith 4/4 T3 $3 | Charging Czarina 6/2 T5 $3 | Auto Assembler 2/2 T4 $3 | Twisted Wrathguard 4/4 T5 $3

  → Board after: 15/18, 5/6, 5/7, 5/6, 6/2 [DS], 4/4, 2/2
  → Gold: 10→0 | Armor: 8→7

**⚔ Combat Phase**

  💀 **Inge, the Iron Hymn eliminated!** (HP=0, Turn 10)
  Alive: 6/8
  HP standings: Overlord Saurfang (HP=30, Armor=11, Tier=5) | Sylvanas Windrunner (HP=30, Armor=0, Tier=5) | Drek'Thar (HP=24, Armor=0, Tier=5) | Ysera (HP=17, Armor=0, Tier=5) | Sneed (HP=12, Armor=0, Tier=5) | Yogg-Saron, Hope's End (HP=10, Armor=0, Tier=5)

### Turn 11

**Yogg-Saron, Hope's End**  HP=10 Armor=0 Gold=10 Tier=5

  Board: 7/2, 7/4, 7/5, 8/7, 6/4, 3/6, 4/3 [Taunt,DS]
  Tavern: Drustfallen Butcher 2/9 T5 $3 | Friendly Geist 6/3 T4 $3 | Moon-Bacon Jazzer 5/6 T3 $3 | Woodland Defiler 14/9 T4 $3 | Crackling Cyclone 3/2 T1 $3

  → Board after: 7/2, 7/4, 7/5, 8/7, 6/4, 3/6, 14/9
  → Gold: 10→0 | Tier: 5→6

**Sneed**  HP=12 Armor=0 Gold=10 Tier=5

  Board: 17/22, 9/8 [DS,Reborn], 10/10 [DS], 15/15 [DS,Reborn], 13/10, 7/7, 10/10 [DS]
  Tavern: Firelands Fugitive 6/8 T5 $3 | Ancestral Automaton 3/7 T2 $3 | Gem Smuggler 5/6 T5 $3 | Annoy-o-Tron 4/5 T1 $3 | Laboratory Assistant 12/13 T2 $3

  → Board after: 19/24, 9/8 [DS,Reborn], 10/10 [DS], 15/15 [DS,Reborn], 18/16, 10/10 [DS], 12/13 [DS]
  → Gold: 10→0 | Tier: 5→6 | HP: 12→11

**Overlord Saurfang**  HP=30 Armor=11 Gold=10 Tier=5

  Board: 57/59 [G], 41/34, 36/36, 35/36, 35/34, 34/34, 3/34
  Tavern: Divine Sparkbot 42/40 T5 $3 | Imposing Percussionist 42/42 T4 $3 | Fire Baller 44/43 T2 $3 | Prosthetic Hand 44/42 T4 $3 | Charging Czarina 44/40 T5 $3

  → Board after: 57/59 [G], 41/34, 36/36, 35/36, 35/34, 34/34, 44/43
  → Gold: 10→0 | Tier: 5→6

**Ysera**  HP=17 Armor=0 Gold=10 Tier=5

  Board: 12/14, 10/9, 11/10, 10/7, 10/7, 8/8, 3/2 [DS]
  Tavern: Picky Eater 1/1 T1 $3 | Bristleback Bully 3/2 T2 $3 | Enchanted Sentinel 9/9 T4 $3 | Sellemental 6/4 T2 $3 | Eternal Knight 4/2 T2 $3

  → Board after: 12/14, 10/9, 11/10, 10/7, 10/7, 8/8, 9/9
  → Gold: 10→0 | Tier: 5→6

**Sylvanas Windrunner**  HP=30 Armor=0 Gold=10 Tier=5

  Board: 13/16, 9/12, 6/8, 4/8, 6/5, 3/7, 2/2 [G]
  Tavern: Woodland Defiler 5/6 T4 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Imposing Percussionist 4/4 T4 $3 | Hot-Air Surveyor 4/8 T5 $3 | Flaming Enforcer 4/5 T4 $3

  → Board after: 13/16, 9/12, 6/8, 4/8, 6/5, 3/7, 4/8
  → Gold: 10→0 | Tier: 5→6

**Drek'Thar**  HP=24 Armor=0 Gold=10 Tier=5

  Board: 15/18, 5/6, 5/7, 5/6, 6/2 [DS], 4/4, 2/2
  Tavern: Malchezaar, Prince of Dance 5/4 T4 $3 | Firelands Fugitive 5/7 T5 $3 | Scrap Scraper 6/5 T5 $3 | Catacomb Crasher 4/10 T5 $3 | Annoy-o-Tron 1/2 T1 $3

  → Board after: 15/18, 5/6, 5/7, 5/6, 6/2 [DS], 4/4, 4/10
  → Gold: 10→0 | Tier: 5→6

**⚔ Combat Phase**

  💀 **Yogg-Saron, Hope's End eliminated!** (HP=0, Turn 11)
  Alive: 5/8
  HP standings: Overlord Saurfang (HP=30, Armor=11, Tier=6) | Sylvanas Windrunner (HP=19, Armor=0, Tier=6) | Ysera (HP=17, Armor=0, Tier=6) | Sneed (HP=11, Armor=0, Tier=6) | Drek'Thar (HP=9, Armor=0, Tier=6)

### Turn 12

**Sneed**  HP=11 Armor=0 Gold=10 Tier=6

  Board: 19/24, 9/8 [DS,Reborn], 10/10 [DS], 15/15 [DS,Reborn], 18/16, 10/10 [DS], 12/13 [DS]
  Tavern: Eternal Tycoon 5/9 T5 $3 | Bristleback Bully 6/5 T2 $3 | Prickly Piper 8/4 T3 $3 | Leyline Surfacer 11/13 T4 $3 | Gem Smuggler 5/6 T5 $3 | Skulking Bristlemane 8/5 T3 $3

  → Board after: 19/24, 15/15 [DS,Reborn], 18/16, 10/10 [DS], 12/13 [DS], 11/13 [DS], 6/5 [Taunt]
  → Gold: 10→0

**Overlord Saurfang**  HP=30 Armor=11 Gold=10 Tier=6

  Board: 57/59 [G], 42/34, 36/36, 35/36, 35/34, 34/34, 44/43
  Tavern: One-Amalgam Tour Group 60/49 T6 $3 | Windfall Tornado 49/49 T1 $3 | Darkgaze Elder 46/48 T5 $3 | Wildfire Elemental 48/45 T3 $3 | Ultraviolet Ascendant 48/45 T6 $3 | Drustfallen Butcher 54/49 T5 $3

  → Board after: 61/63 [G], 46/38, 61/50, 56/51, 52/52, 47/49, 49/46
  → Gold: 10→0

**Ysera**  HP=17 Armor=0 Gold=10 Tier=6

  Board: 12/14, 11/9, 11/10, 10/7, 10/7, 8/8, 9/9
  Tavern: Eternal Knight 4/2 T2 $3 | Tavern Tempest 2/2 T4 $3 | Marquee Ticker 4/8 T4 $3 | Air Revenant 6/7 T5 $3 | Annoy-o-Module 2/4 T3 $3 | Eternal Summoner 14/2 T6 $3

  → Board after: 12/14, 11/9, 11/10, 10/7, 9/9, 14/2 [Reborn], 2/4 [Taunt,DS]
  → Gold: 10→0

**Sylvanas Windrunner**  HP=19 Armor=0 Gold=10 Tier=6

  Board: 13/16, 9/12, 6/8, 4/8, 6/5, 3/7, 4/8
  Tavern: Pufferquil 2/6 T3 $3 | Plaguerunner 4/2 T4 $3 | Tichondrius 3/6 T5 $3 | Metallic Hunter 2/1 T2 $3 | Cadaver Caretaker 3/3 T3 $3 | Plaguerunner 4/2 T4 $3

  → Board after: 19/20, 11/14, 6/8, 4/8, 6/5, 4/8, 2/1
  → Gold: 10→0 | HP: 19→17

**Drek'Thar**  HP=9 Armor=0 Gold=10 Tier=6

  Board: 15/18, 5/6, 5/7, 5/6, 6/2 [DS], 4/4, 4/10
  Tavern: Wintergrasp Ghoul 5/3 T5 $3 | Auto Assembler 2/2 T4 $3 | Wintergrasp Ghoul 5/3 T5 $3 | Accord-o-Tron 3/3 T3 $3 | Consummate Conqueror 9/7 T6 $3 | Harmless Bonehead 1/1 T1 $3

  → Board after: 17/20, 5/6, 5/7, 5/6, 4/10, 9/7, 2/2
  → Gold: 10→0 | HP: 9→8

**⚔ Combat Phase**

  💀 **Sylvanas Windrunner eliminated!** (HP=0, Turn 12)
  💀 **Drek'Thar eliminated!** (HP=0, Turn 12)
  Alive: 3/8
  HP standings: Overlord Saurfang (HP=30, Armor=11, Tier=6) | Ysera (HP=17, Armor=0, Tier=6) | Sneed (HP=11, Armor=0, Tier=6)

### Turn 13

**Sneed**  HP=11 Armor=0 Gold=10 Tier=6

  Board: 19/24, 15/15 [DS,Reborn], 18/16, 10/10 [DS], 12/13 [DS], 11/13 [DS], 6/5 [Taunt]
  Tavern: Ancestral Automaton 3/7 T2 $3 | Pufferquil 5/9 T3 $3 | Alert Alarmist 4/4 T2 $3 | Catacomb Crasher 5/11 T5 $3 | Auto Assembler 9/9 T4 $3 | Hot-Air Surveyor 5/9 T5 $3

  → Board after: 19/24, 15/15 [DS,Reborn], 18/16, 10/10 [DS], 12/13 [DS], 11/13 [DS], 3/7
  → Gold: 10→0

**Overlord Saurfang**  HP=30 Armor=11 Gold=10 Tier=6

  Board: 61/63 [G], 47/38, 62/50, 57/51, 52/52, 47/49, 49/46
  Tavern: Laboratory Assistant 49/50 T2 $3 | Waveling 54/49 T3 $3 | Scrap Scraper 52/51 T5 $3 | Annoy-o-Module 51/53 T3 $3 | Fearless Foodie 48/50 T4 $3 | Old Soul 62/50 T2 $3

  → Board after: 66/68 [G], 62/50, 58/52, 57/57, 67/55, 54/56 [Taunt,DS], 50/51
  → Gold: 10→0

**Ysera**  HP=17 Armor=0 Gold=10 Tier=6

  Board: 12/14, 12/9, 11/10, 10/7, 9/9, 15/2 [Reborn], 2/4 [Taunt,DS]
  Tavern: Eternal Knight 4/2 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Mummifier 12/5 T3 $3 | Deathly Striker 15/9 T6 $3 | Earthsong Shaman 7/6 T6 $3 | Deathly Striker 12/8 T6 $3

  → Board after: 12/14, 12/9, 15/2 [Reborn], 15/9, 12/8, 12/5, 4/2
  → Gold: 10→0

**⚔ Combat Phase**

  Alive: 3/8
  HP standings: Overlord Saurfang (HP=30, Armor=11, Tier=6) | Ysera (HP=17, Armor=0, Tier=6) | Sneed (HP=11, Armor=0, Tier=6)

### Turn 14

**Sneed**  HP=11 Armor=0 Gold=10 Tier=6

  Board: 19/24, 15/15 [DS,Reborn], 18/16, 10/10 [DS], 12/13 [DS], 11/13 [DS], 3/7
  Tavern: Glowgullet Warlord 5/5 T2 $3 | Moonsteel Juggernaut 7/7 T6 $3 | Cadaver Caretaker 6/6 T3 $3 | Sinrunner Blanchy 9/9 T5 $3 | Cord Puller 10/10 T1 $3 | Firelands Fugitive 6/8 T5 $3

  → Board after: 19/24, 15/15 [DS,Reborn], 18/16, 12/13 [DS], 11/13 [DS], 10/10 [DS], 6/6
  → Gold: 10→0

**Overlord Saurfang**  HP=30 Armor=11 Gold=10 Tier=6

  Board: 66/68 [G], 62/50, 58/52, 57/57, 67/55, 54/56 [Taunt,DS], 50/51
  Tavern: Skeletal Strafer 69/56 T5 $3 | Mummifier 68/52 T3 $3 | Bristlebach 53/60 T6 $3 | Wrath Weaver 51/54 T1 $3 | Famished Felbat 59/55 T6 $3 | Darkgaze Elder 59/61 T5 $3

  → Board after: 71/73 [G], 64/52, 62/56, 72/60, 73/60, 72/56, 54/61
  → Gold: 10→0

**Ysera**  HP=17 Armor=0 Gold=10 Tier=6

  Board: 12/14, 13/9, 16/2 [Reborn], 16/9, 13/8, 13/5, 5/2
  Tavern: Elemental of Surprise 11/11 T6 $3 | Leyline Surfacer 4/6 T4 $3 | Laboratory Assistant 6/5 T2 $3 | Sellemental 6/4 T2 $3 | Sun-Bacon Relaxer 2/3 T1 $3 | Crackling Cyclone 2/1 T1 $3

  → Board after: 14/16, 13/9, 16/2 [Reborn], 16/9, 13/8, 13/5, 9/14
  → Gold: 10→0 | HP: 17→16

**⚔ Combat Phase**

  💀 **Ysera eliminated!** (HP=0, Turn 14)
  Alive: 2/8
  HP standings: Overlord Saurfang (HP=30, Armor=11, Tier=6) | Sneed (HP=11, Armor=0, Tier=6)

### Turn 15

**Sneed**  HP=11 Armor=0 Gold=10 Tier=6

  Board: 19/24, 15/15 [DS,Reborn], 18/16, 12/13 [DS], 11/13 [DS], 10/10 [DS], 6/6
  Tavern: Tichondrius 10/13 T5 $3 | Scarlet Skull 5/4 T2 $3 | Soul Rewinder 7/4 T2 $3 | Auto Assembler 3/3 T4 $3 | Moonsteel Juggernaut 7/7 T6 $3 | Old Soul 6/7 T2 $3

  → Board after: 23/28, 15/15 [DS,Reborn], 24/23, 15/16 [DS], 11/13 [DS], 10/13 [DS]
  → Gold: 10→0 | HP: 11→9

**Overlord Saurfang**  HP=30 Armor=11 Gold=10 Tier=6

  Board: 72/74 [G], 65/53, 63/57, 73/61, 74/61, 73/57, 55/62
  Tavern: Fire Baller 58/57 T2 $3 | Waveling 60/55 T3 $3 | P-0UL-TR-0N 60/60 T6 $3 | Forsaken Weaver 68/62 T6 $3 | Bristlebach 55/62 T6 $3 | Skeletal Strafer 74/61 T5 $3

  → Board after: 77/79 [G], 78/66, 78/65, 77/61, 78/65, 71/65, 59/58
  → Gold: 10→0

**⚔ Combat Phase**

  Alive: 2/8
  HP standings: Overlord Saurfang (HP=30, Armor=11, Tier=6) | Sneed (HP=9, Armor=0, Tier=6)

---

## Final Standings

| # | Hero | HP | Armor | Alive | Eliminated Turn |
|---|---|---|---|---|
| 1 | Overlord Saurfang | 30 | 11 | Yes | — |
| 2 | Sneed | 9 | 0 | Yes | — |
| 3 | Ysera | 0 | 0 | No | 14 |
| 4 | Sylvanas Windrunner | 0 | 0 | No | 12 |
| 5 | Drek'Thar | 0 | 0 | No | 12 |
| 6 | Yogg-Saron, Hope's End | 0 | 0 | No | 11 |
| 7 | Inge, the Iron Hymn | 0 | 0 | No | 10 |
| 8 | Professor Putricide | 0 | 0 | No | 8 |

---

## Heuristic Strategy

The Q-score heuristic evaluates each affordable tavern minion by:

1. **Buy & Play**: Score = current_board_score + minion.atk + minion.health + aura_bonus
2. **Sell & Replace**: If board full, replace weakest minion if net score change > 0
3. **Upgrade**: If no beneficial buy is available and gold ≥ upgrade_cost, upgrade tavern tier
4. **Refresh**: If no other action is possible, refresh the tavern for 1 gold

This is a greedy one-step heuristic — no lookahead, no opponent modeling, no combat simulation.
Average rank in self-play: ~4.5 (random among identical strategies)