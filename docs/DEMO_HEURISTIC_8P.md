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
  → Gold: 5→0 | Tier: 1→6

**Sneed**  HP=30 Armor=11 Gold=5 Tier=1

  Board: 2/3, 3/6
  Tavern: False Implicator 1/1 T1 $3 | Cord Puller 1/1 T1 $3 | Crackling Cyclone 2/1 T1 $3

  → Board after: 2/3, 3/6, 2/1 [DS,WF]
  → Gold: 5→0 | Tier: 1→6

**Overlord Saurfang**  HP=30 Armor=18 Gold=5 Tier=1

  Board: 4/3, 4/7
  Tavern: False Implicator 6/6 T1 $3 | Razorfen Geomancer 7/6 T1 $3 | Dune Dweller 9/8 T1 $3

  → Board after: 4/3, 4/7, 9/8
  → Gold: 5→0 | Tier: 1→6

**Ysera**  HP=30 Armor=10 Gold=5 Tier=1

  Board: 2/3, 4/4
  Tavern: Wrath Weaver 1/4 T1 $3 | Crackling Cyclone 2/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3

  → Board after: 2/3, 4/4, 3/6
  → Gold: 5→0 | Tier: 1→6 | Armor: 10→9

**Inge, the Iron Hymn**  HP=30 Armor=9 Gold=5 Tier=1

  Board: 2/1 [DS,WF], 2/3
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Picky Eater 1/1 T1 $3 | Sun-Bacon Relaxer 2/3 T1 $3

  → Board after: 2/1 [DS,WF], 2/3, 2/3
  → Gold: 5→0 | Tier: 1→6

**Professor Putricide**  HP=30 Armor=6 Gold=5 Tier=1

  Board: 2/1 [Taunt,Reborn], 2/3
  Tavern: False Implicator 1/1 T1 $3 | Sun-Bacon Relaxer 2/3 T1 $3 | Wrath Weaver 1/4 T1 $3

  → Board after: 2/1 [Taunt,Reborn], 2/3, 2/3
  → Gold: 5→0 | Tier: 1→6

**Sylvanas Windrunner**  HP=30 Armor=9 Gold=5 Tier=1

  Board: 4/4, 3/6
  Tavern: Cord Puller 1/1 T1 $3 | Windfall Tornado 4/4 T1 $3 | Annoy-o-Tron 1/2 T1 $3

  → Board after: 4/4, 3/6, 4/4
  → Gold: 5→0 | Tier: 1→6

**Drek'Thar**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 4/4, 4/4
  Tavern: Harmless Bonehead 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | False Implicator 1/1 T1 $3

  → Board after: 4/4, 4/4, 3/6
  → Gold: 5→0 | Tier: 1→6 | Armor: 12→11

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=11, Tier=6) | Sneed (HP=30, Armor=6, Tier=6) | Overlord Saurfang (HP=30, Armor=18, Tier=6) | Ysera (HP=30, Armor=9, Tier=6) | Inge, the Iron Hymn (HP=30, Armor=4, Tier=6) | Professor Putricide (HP=30, Armor=1, Tier=6) | Sylvanas Windrunner (HP=30, Armor=9, Tier=6) | Drek'Thar (HP=30, Armor=11, Tier=6)

### Turn 4

**Yogg-Saron, Hope's End**  HP=30 Armor=11 Gold=6 Tier=6

  Board: 4/4, 2/1, 3/2
  Tavern: Bristlemane Scrapsmith 4/4 T3 $3 | Fire Baller 5/4 T2 $3 | Waveling 7/2 T3 $3 | Air Revenant 4/7 T5 $3 | Ichoron the Protector 4/2 T4 $3 | Gem Smuggler 4/5 T5 $3

  → Board after: 4/4, 2/1, 3/2, 4/7, 5/4
  → Gold: 6→0

**Sneed**  HP=30 Armor=6 Gold=6 Tier=6

  Board: 2/3, 3/6, 2/1 [DS,WF]
  Tavern: Handless Forsaken 2/1 T3 $3 | Enchanted Sentinel 3/5 T4 $3 | Eternal Tycoon 4/8 T5 $3 | Prosthetic Hand 3/1 T4 $3 | Marquee Ticker 1/5 T4 $3 | Windfall Tornado 4/4 T1 $3

  → Board after: 2/3, 3/6, 2/1 [DS,WF], 4/8, 3/5
  → Gold: 6→0

**Overlord Saurfang**  HP=30 Armor=18 Gold=6 Tier=6

  Board: 4/3, 4/7, 9/8
  Tavern: Tavern Tempest 11/11 T4 $3 | Wintergrasp Ghoul 12/10 T5 $3 | Auto Assembler 9/9 T4 $3 | Handless Forsaken 9/8 T3 $3 | Consummate Conqueror 16/14 T6 $3 | Refreshing Anomaly 13/14 T4 $3

  → Board after: 4/3, 4/7, 9/8, 16/14, 13/14
  → Gold: 6→0

**Ysera**  HP=30 Armor=9 Gold=6 Tier=6

  Board: 2/3, 4/4, 3/6
  Tavern: Eternal Knight 4/2 T2 $3 | Earthsong Shaman 4/5 T6 $3 | One-Amalgam Tour Group 6/7 T6 $3 | Scarlet Skull 2/1 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3

  → Board after: 4/5, 6/6, 5/8, 8/9, 5/6 [WF]
  → Gold: 6→0

**Inge, the Iron Hymn**  HP=30 Armor=4 Gold=6 Tier=6

  Board: 2/1 [DS,WF], 2/3, 2/3
  Tavern: Deathly Striker 8/8 T6 $3 | Eternal Knight 4/2 T2 $3 | Hot-Air Surveyor 4/8 T5 $3 | Friendly Geist 6/3 T4 $3 | Fire Baller 4/3 T2 $3 | Sellemental 3/3 T2 $3

  → Board after: 2/1 [DS,WF], 2/3, 2/3, 8/8, 4/8
  → Gold: 6→0

**Professor Putricide**  HP=30 Armor=1 Gold=6 Tier=6

  Board: 2/1 [Taunt,Reborn], 2/3, 2/3
  Tavern: Bristlemane Scrapsmith 4/4 T3 $3 | Enchanted Sentinel 3/5 T4 $3 | Laboratory Assistant 3/4 T2 $3 | Living Azerite 6/5 T5 $3 | Moon-Bacon Jazzer 2/5 T3 $3 | Old Soul 3/4 T2 $3

  → Board after: 2/1 [Taunt,Reborn], 2/3, 2/3, 6/5, 4/4
  → Gold: 6→0

**Sylvanas Windrunner**  HP=30 Armor=9 Gold=6 Tier=6

  Board: 4/4, 3/6, 4/4
  Tavern: Scrap Scraper 6/5 T5 $3 | Prosthetic Hand 3/1 T4 $3 | Bristlebach 3/10 T6 $3 | Sellemental 3/3 T2 $3 | Fearless Foodie 2/4 T4 $3 | Imposing Percussionist 4/4 T4 $3

  → Board after: 4/4, 3/6, 4/4, 3/10, 6/5
  → Gold: 6→0

**Drek'Thar**  HP=30 Armor=11 Gold=6 Tier=6

  Board: 4/4, 4/4, 3/6
  Tavern: Ancestral Automaton 3/4 T2 $3 | Consummate Conqueror 9/7 T6 $3 | Consummate Conqueror 9/7 T6 $3 | Bristlebach 3/10 T6 $3 | Rot Hide Gnoll 1/4 T1 $3 | Wrath Weaver 1/4 T1 $3

  → Board after: 4/4, 4/4, 7/10, 9/7, 9/7
  → Gold: 6→0 | Armor: 11→9

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Yogg-Saron, Hope's End (HP=30, Armor=1, Tier=6) | Sneed (HP=30, Armor=6, Tier=6) | Overlord Saurfang (HP=30, Armor=18, Tier=6) | Ysera (HP=30, Armor=9, Tier=6) | Inge, the Iron Hymn (HP=30, Armor=4, Tier=6) | Drek'Thar (HP=30, Armor=9, Tier=6) | Sylvanas Windrunner (HP=29, Armor=0, Tier=6) | Professor Putricide (HP=21, Armor=0, Tier=6)

### Turn 5

**Yogg-Saron, Hope's End**  HP=30 Armor=1 Gold=7 Tier=6

  Board: 4/4, 2/1, 3/2, 4/7, 5/4
  Tavern: Glowgullet Warlord 2/2 T2 $3 | Nightmare Par-tea Guest 4/4 T5 $3 | Accord-o-Tron 3/3 T3 $3 | Wintergrasp Ghoul 5/3 T5 $3 | Dustbone Devastator 2/6 T3 $3 | Void Pup Trainer 7/7 T5 $3

  → Board after: 4/4, 2/1, 3/2, 4/7, 5/4, 7/7, 4/4
  → Gold: 7→0

**Sneed**  HP=30 Armor=6 Gold=7 Tier=6

  Board: 2/3, 3/6, 2/1 [DS,WF], 4/8, 3/5
  Tavern: Gem Smuggler 4/5 T5 $3 | Deathly Striker 8/8 T6 $3 | Nightmare Par-tea Guest 3/3 T5 $3 | Skeletal Strafer 6/6 T5 $3 | Ancestral Automaton 3/4 T2 $3 | Bristlemane Scrapsmith 4/4 T3 $3

  → Board after: 2/3, 3/6, 2/1 [DS,WF], 4/8, 3/5, 8/8, 6/6
  → Gold: 7→0

**Overlord Saurfang**  HP=30 Armor=18 Gold=7 Tier=6

  Board: 4/3, 4/7, 9/8, 16/14, 13/14
  Tavern: Snow Baller 16/17 T2 $3 | Air Revenant 16/19 T5 $3 | Charging Czarina 17/13 T5 $3 | Eternal Knight 4/13 T2 $3 | Technical Element 16/17 T3 $3 | P-0UL-TR-0N 19/19 T6 $3

  → Board after: 4/3, 4/7, 9/8, 16/14, 13/14, 19/19, 16/19
  → Gold: 7→0

**Ysera**  HP=30 Armor=9 Gold=7 Tier=6

  Board: 6/7, 8/8, 7/10, 10/11, 7/8 [WF]
  Tavern: Risen Rider 2/1 T1 $3 | Batty Terrorguard 6/2 T6 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Alert Alarmist 1/1 T2 $3 | Old Soul 3/4 T2 $3 | Famished Felbat 9/5 T6 $3

  → Board after: 8/9, 10/10, 13/16, 11/12, 8/9 [WF], 10/6, 6/5
  → Gold: 7→0 | Armor: 9→7

**Inge, the Iron Hymn**  HP=30 Armor=4 Gold=7 Tier=6

  Board: 2/1 [DS,WF], 2/3, 2/3, 8/8, 4/8
  Tavern: Malchezaar, Prince of Dance 5/4 T4 $3 | Mummifier 5/2 T3 $3 | Leeching Felhound 3/3 T3 $3 | Bristlebach 3/10 T6 $3 | Skeletal Strafer 6/6 T5 $3 | Forsaken Weaver 3/10 T6 $3

  → Board after: 2/1 [DS,WF], 2/3, 2/3, 8/8, 4/8, 3/10, 3/10
  → Gold: 7→0

**Professor Putricide**  HP=21 Armor=0 Gold=7 Tier=6

  Board: 2/1 [Taunt,Reborn], 2/3, 2/3, 6/5, 4/4
  Tavern: Bristleback Bully 3/2 T2 $3 | Alert Alarmist 1/1 T2 $3 | Sun-Bacon Relaxer 2/3 T1 $3 | Gem Smuggler 4/5 T5 $3 | Old Soul 3/4 T2 $3 | Dustbone Devastator 2/6 T3 $3

  → Board after: 4/3 [Taunt,Reborn], 4/5, 4/5, 8/7, 6/6, 4/5, 3/7
  → Gold: 7→0

**Sylvanas Windrunner**  HP=29 Armor=0 Gold=7 Tier=6

  Board: 4/4, 3/6, 4/4, 3/10, 6/5
  Tavern: Moon-Bacon Jazzer 2/5 T3 $3 | Pufferquil 2/6 T3 $3 | Consummate Conqueror 9/7 T6 $3 | Dune Dweller 3/2 T1 $3 | Void Pup Trainer 7/7 T5 $3 | Mummifier 5/2 T3 $3

  → Board after: 4/4, 7/10, 4/4, 3/10, 6/5, 11/9, 10/10
  → Gold: 7→0 | HP: 29→27

**Drek'Thar**  HP=30 Armor=9 Gold=7 Tier=6

  Board: 4/4, 4/4, 7/10, 9/7, 9/7
  Tavern: Sinrunner Blanchy 8/8 T5 $3 | Auto Assembler 2/2 T4 $3 | Waveling 6/1 T3 $3 | Living Azerite 6/5 T5 $3 | P-0UL-TR-0N 8/8 T6 $3 | Plaguerunner 4/2 T4 $3

  → Board after: 4/4, 4/4, 7/10, 9/7, 9/7, 12/12 [Reborn], 13/13
  → Gold: 7→0

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Overlord Saurfang (HP=30, Armor=18, Tier=6) | Ysera (HP=30, Armor=7, Tier=6) | Inge, the Iron Hymn (HP=30, Armor=4, Tier=7) | Drek'Thar (HP=29, Armor=0, Tier=6) | Sylvanas Windrunner (HP=27, Armor=0, Tier=6) | Sneed (HP=26, Armor=0, Tier=6) | Yogg-Saron, Hope's End (HP=21, Armor=0, Tier=6) | Professor Putricide (HP=11, Armor=0, Tier=6)

### Turn 6

**Yogg-Saron, Hope's End**  HP=21 Armor=0 Gold=8 Tier=6

  Board: 2/1, 4/7, 7/7, 4/4
  Tavern: Ichoron the Protector 4/2 T4 $3 | Geomagus Roogug 4/6 T4 $3 | Handless Forsaken 4/3 T3 $3 | Famished Felbat 9/5 T6 $3 | Bristlemane Scrapsmith 6/6 T3 $3 | Three Lil' Quilboar 3/3 T5 $3

  → Board after: 2/1, 4/7, 7/7, 4/4, 15/11, 13/13
  → Gold: 8→0

**Sneed**  HP=26 Armor=0 Gold=8 Tier=6

  Board: 4/5, 5/8, 4/3 [DS,WF], 6/10, 5/7, 10/10, 8/8
  Tavern: Felemental 3/3 T3 $3 | One-Amalgam Tour Group 6/7 T6 $3 | Ultraviolet Ascendant 6/3 T6 $3 | En-Djinn Blazer 4/4 T4 $3 | Auto Assembler 2/2 T4 $3 | Tichondrius 3/6 T5 $3

  → Board after: 11/14, 12/12, 11/11, 16/17, 16/13, 14/17, 16/16
  → Gold: 8→0 | HP: 26→25

**Overlord Saurfang**  HP=30 Armor=18 Gold=8 Tier=6

  Board: 4/3, 4/7, 9/8, 16/14, 13/14, 19/19, 16/19
  Tavern: Sellemental 20/20 T2 $3 | Felemental 20/20 T3 $3 | Geomagus Roogug 19/21 T4 $3 | Wrath Weaver 16/19 T1 $3 | Air Revenant 20/23 T5 $3 | Leeching Felhound 18/18 T3 $3

  → Board after: 16/14, 19/19, 16/19, 32/35, 33/33, 34/34, 34/36 [DS]
  → Gold: 8→0

**Ysera**  HP=30 Armor=7 Gold=8 Tier=6

  Board: 12/13, 14/14, 28/28, 15/16, 12/13 [WF], 19/18, 15/14
  Tavern: Sellemental 3/3 T2 $3 | Felemental 3/3 T3 $3 | Cadaver Caretaker 3/3 T3 $3 | Mummifier 5/2 T3 $3 | Redtusk Thornraiser 3/7 T4 $3 | Wrath Weaver 1/4 T1 $3

  → Board after: 18/18, 32/32, 19/18, 20/24, 24/21, 23/23, 23/23
  → Gold: 8→0

**Inge, the Iron Hymn**  HP=30 Armor=4 Gold=8 Tier=7

  Board: 2/1 [DS,WF], 2/3, 2/3, 8/8, 4/8, 3/10, 3/10
  Tavern: Fire Baller 4/3 T2 $3 | Snow Baller 3/4 T2 $3 | Sellemental 3/3 T2 $3 | Floating Watcher 4/4 T3 $5 | Wintergrasp Ghoul 5/3 T5 $3 | Snow Baller 3/4 T2 $3

  → Board after: 8/8, 4/8, 3/10, 3/10, 24/24, 26/24, 26/25
  → Gold: 8→0

**Professor Putricide**  HP=11 Armor=0 Gold=8 Tier=6

  Board: 4/3 [Taunt,Reborn], 4/5, 4/5, 8/7, 6/6, 4/5, 3/7
  Tavern: Twisted Wrathguard 4/4 T5 $3 | Bristleback Bully 3/2 T2 $3 | Dune Dweller 3/2 T1 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Wildfire Elemental 6/3 T3 $3 | Technical Element 5/6 T3 $3

  → Board after: 8/7, 6/6, 3/7, 28/29, 29/28, 31/28, 30/30
  → Gold: 8→0

**Sylvanas Windrunner**  HP=27 Armor=0 Gold=8 Tier=6

  Board: 4/4, 7/10, 4/4, 3/10, 6/5, 11/9, 10/10
  Tavern: Leyline Surfacer 4/6 T4 $3 | Friendly Geist 6/3 T4 $3 | Imposing Percussionist 4/4 T4 $3 | Dune Dweller 5/4 T1 $3 | Bristleback Bully 5/4 T2 $3 | Imposing Percussionist 4/4 T4 $3

  → Board after: 7/10, 11/9, 10/10, 31/33, 34/31, 34/33, 35/34 [Taunt]
  → Gold: 8→0

**Drek'Thar**  HP=29 Armor=0 Gold=8 Tier=6

  Board: 4/4, 4/4, 7/10, 9/7, 9/7, 12/12 [Reborn], 13/13
  Tavern: Deflect-o-Bot 3/2 T3 $3 | Forsaken Weaver 3/10 T6 $3 | Gem Smuggler 4/5 T5 $3 | Twisted Wrathguard 4/4 T5 $3 | Razorfen Geomancer 2/1 T1 $3 | Junk Jouster 8/7 T6 $3

  → Board after: 13/16, 16/16 [Reborn], 17/17, 43/42, 39/46, 37/38, 38/38
  → Gold: 8→0 | HP: 29→28

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Overlord Saurfang (HP=30, Armor=18, Tier=6) | Drek'Thar (HP=28, Armor=0, Tier=6) | Ysera (HP=27, Armor=0, Tier=6) | Sylvanas Windrunner (HP=27, Armor=0, Tier=6) | Sneed (HP=25, Armor=0, Tier=6) | Inge, the Iron Hymn (HP=24, Armor=0, Tier=7) | Yogg-Saron, Hope's End (HP=11, Armor=0, Tier=6) | Professor Putricide (HP=1, Armor=0, Tier=6)

### Turn 7

**Yogg-Saron, Hope's End**  HP=11 Armor=0 Gold=9 Tier=6

  Board: 2/1, 4/7, 15/15, 4/4, 22/15, 13/13
  Tavern: Charging Czarina 6/2 T5 $3 | Fire Baller 7/6 T2 $3 | Sellemental 6/6 T2 $3 | Scarlet Skull 4/3 T2 $3 | Friendly Geist 6/3 T4 $3 | Shadowdancer 5/3 T5 $3

  → Board after: 15/15, 22/15, 13/13, 42/41, 42/42, 43/40, 44/40 [DS]
  → Gold: 9→0

**Sneed**  HP=25 Armor=0 Gold=9 Tier=6

  Board: 13/16, 14/14, 13/13, 18/19, 18/15, 16/19, 18/18
  Tavern: Tavern Tempest 2/2 T4 $3 | Bristleback Bully 6/5 T2 $3 | Auto Assembler 5/5 T4 $3 | Twisted Wrathguard 7/7 T5 $3 | Handless Forsaken 5/4 T3 $3 | Junk Jouster 17/16 T6 $3

  → Board after: 19/20, 18/21, 21/21, 57/56, 48/48, 49/48 [Taunt], 48/48
  → Gold: 9→0 | HP: 25→24

**Overlord Saurfang**  HP=30 Armor=18 Gold=9 Tier=6

  Board: 16/14, 19/19, 16/19, 32/35, 33/33, 34/34, 34/36 [DS]
  Tavern: Metallic Hunter 25/24 T2 $3 | Three Lil' Quilboar 26/26 T5 $3 | Living Azerite 31/30 T5 $3 | Deathly Striker 31/31 T6 $3 | Eternal Summoner 31/24 T6 $3 | Nerubian Deathswarmer 24/27 T2 $3

  → Board after: 32/35, 34/34, 34/36 [DS], 74/74, 75/74, 76/69 [Reborn], 72/72
  → Gold: 9→0

**Ysera**  HP=27 Armor=0 Gold=9 Tier=6

  Board: 18/18, 35/35, 20/22, 20/24, 24/21, 23/23, 23/23
  Tavern: Prickly Piper 6/2 T3 $3 | Eternal Knight 4/3 T2 $3 | Sinrunner Blanchy 9/9 T5 $3 | Picky Eater 2/2 T1 $3 | Prickly Piper 6/2 T3 $3 | Sinrunner Blanchy 9/9 T5 $3

  → Board after: 39/39, 27/27, 27/27, 58/58 [Reborn], 58/58 [Reborn], 57/53, 57/53
  → Gold: 9→0

**Inge, the Iron Hymn**  HP=24 Armor=0 Gold=9 Tier=7

  Board: 8/8, 4/8, 3/10, 3/10, 24/24, 26/24, 26/25
  Tavern: Floating Watcher 4/4 T3 $5 | Wildfire Elemental 6/3 T3 $3 | Elemental of Surprise 8/8 T6 $3 | Laboratory Assistant 3/4 T2 $3 | Wrath Weaver 1/4 T1 $3 | Three Lil' Quilboar 3/3 T5 $3

  → Board after: 8/8, 24/24, 26/24, 26/25, 59/59 [DS], 58/55, 57/57
  → Gold: 9→0

**Professor Putricide**  HP=1 Armor=0 Gold=9 Tier=6

  Board: 8/7, 6/6, 4/7, 28/29, 29/28, 31/28, 30/30
  Tavern: Nightmare Par-tea Guest 4/3 T5 $3 | Bristlemane Scrapsmith 4/4 T3 $3 | Eternal Knight 4/2 T2 $3 | Gem Smuggler 4/5 T5 $3 | Prickly Piper 5/1 T3 $3 | Skeletal Strafer 7/6 T5 $3

  → Board after: 31/30, 33/30, 32/32, 63/62, 59/60, 60/59, 61/61
  → Gold: 9→0

**Sylvanas Windrunner**  HP=27 Armor=0 Gold=9 Tier=6

  Board: 7/10, 11/9, 10/10, 31/33, 34/31, 34/33, 35/34 [Taunt]
  Tavern: Scarlet Skull 4/3 T2 $3 | Sinrunner Blanchy 8/8 T5 $3 | Rot Hide Gnoll 3/6 T1 $3 | Dustbone Devastator 4/8 T3 $3 | Prosthetic Hand 3/1 T4 $3 | Marquee Ticker 1/5 T4 $3

  → Board after: 34/31, 34/33, 35/34 [Taunt], 66/66 [Reborn], 63/67, 63/66, 65/64 [Reborn]
  → Gold: 9→0

**Drek'Thar**  HP=28 Armor=0 Gold=9 Tier=6

  Board: 13/16, 16/16 [Reborn], 17/17, 43/42, 39/46, 37/38, 38/38
  Tavern: Floating Watcher 4/4 T3 $5 | Annoy-o-Tron 1/2 T1 $3 | Redtusk Thornraiser 3/7 T4 $3 | Eternal Tycoon 4/8 T5 $3 | Dustbone Devastator 2/6 T3 $3 | Razorfen Geomancer 2/1 T1 $3

  → Board after: 43/42, 39/46, 37/38, 38/38, 66/70, 66/70, 68/68
  → Gold: 9→0

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Overlord Saurfang (HP=30, Armor=18, Tier=6) | Drek'Thar (HP=28, Armor=0, Tier=6) | Sylvanas Windrunner (HP=27, Armor=0, Tier=6) | Ysera (HP=17, Armor=0, Tier=6) | Sneed (HP=15, Armor=0, Tier=6) | Inge, the Iron Hymn (HP=14, Armor=0, Tier=7) | Yogg-Saron, Hope's End (HP=1, Armor=0, Tier=6) | Professor Putricide (HP=1, Armor=0, Tier=6)

### Turn 8

**Yogg-Saron, Hope's End**  HP=1 Armor=0 Gold=10 Tier=6

  Board: 19/18, 27/18, 13/9, 42/41, 42/42, 43/40, 44/40 [DS]
  Tavern: Leeching Felhound 5/5 T3 $3 | Harmless Bonehead 3/3 T1 $3 | Cord Puller 3/3 T1 $3 | Tichondrius 3/6 T5 $3 | Prickly Piper 7/3 T3 $3 | Batty Terrorguard 6/2 T6 $3

  → Board after: 42/42, 44/40 [DS], 70/70, 73/69, 70/73, 74/70, 72/72
  → Gold: 10→0

**Sneed**  HP=15 Armor=0 Gold=10 Tier=6

  Board: 19/20, 18/21, 21/21, 57/56, 48/48, 49/48 [Taunt], 48/48
  Tavern: Skeletal Strafer 9/9 T5 $3 | Leyline Surfacer 4/6 T4 $3 | Eternal Knight 5/2 T2 $3 | Razorfen Geomancer 8/7 T1 $3 | Bazaar Dealer 10/12 T5 $3 | Moon-Bacon Jazzer 8/11 T3 $3

  → Board after: 57/56, 53/52 [Taunt], 82/84, 82/85, 82/82, 83/82, 79/81
  → Gold: 10→0

**Overlord Saurfang**  HP=30 Armor=18 Gold=10 Tier=6

  Board: 32/35, 34/34, 34/36 [DS], 74/74, 75/74, 76/69 [Reborn], 72/72
  Tavern: Redtusk Thornraiser 33/37 T4 $3 | Flaming Enforcer 34/35 T4 $3 | Annoy-o-Module 32/34 T3 $3 | Laboratory Assistant 33/34 T2 $3 | Cord Puller 31/31 T1 $3 | Pufferquil 32/36 T3 $3

  → Board after: 74/74, 75/74, 108/112, 110/111, 109/113, 111/112, 111/113 [Taunt,DS]
  → Gold: 10→0

**Ysera**  HP=17 Armor=0 Gold=10 Tier=6

  Board: 39/39, 27/27, 27/27, 58/58 [Reborn], 58/58 [Reborn], 57/53, 57/53
  Tavern: Scarlet Skull 3/2 T2 $3 | Wrath Weaver 2/5 T1 $3 | Fearless Foodie 3/5 T4 $3 | Prosthetic Hand 4/2 T4 $3 | Rot Hide Gnoll 2/5 T1 $3 | Nightmare Par-tea Guest 4/4 T5 $3

  → Board after: 59/59 [Reborn], 59/59 [Reborn], 86/88, 86/86, 89/92, 87/90, 89/87 [Reborn]
  → Gold: 10→0 | HP: 17→16

**Inge, the Iron Hymn**  HP=14 Armor=0 Gold=10 Tier=7

  Board: 8/8, 24/24, 26/24, 26/25, 59/59 [DS], 58/55, 57/57
  Tavern: Junk Jouster 8/7 T6 $3 | Dune Dweller 3/2 T1 $3 | Metallic Hunter 2/1 T2 $3 | Metallic Hunter 2/1 T2 $3 | Catacomb Crasher 4/10 T5 $3 | Technical Element 5/6 T3 $3

  → Board after: 59/59 [DS], 57/57, 93/92, 90/96, 92/93, 91/90, 91/90
  → Gold: 10→0

**Professor Putricide**  HP=1 Armor=0 Gold=10 Tier=6

  Board: 32/31, 34/31, 33/33, 64/63, 60/61, 61/60, 62/62
  Tavern: Felemental 3/3 T3 $3 | Soul Rewinder 4/1 T2 $3 | Hot-Air Surveyor 4/8 T5 $3 | Friendly Geist 7/3 T4 $3 | Void Pup Trainer 7/7 T5 $3 | Wintergrasp Ghoul 6/3 T5 $3

  → Board after: 64/63, 62/62, 97/97, 95/99, 99/95, 99/96, 97/97
  → Gold: 10→0

**Sylvanas Windrunner**  HP=27 Armor=0 Gold=10 Tier=6

  Board: 35/31, 34/33, 35/34 [Taunt], 67/66 [Reborn], 64/67, 64/66, 66/64 [Reborn]
  Tavern: Bristlemane Scrapsmith 6/6 T3 $3 | Scrap Scraper 6/5 T5 $3 | Geomagus Roogug 4/6 T4 $3 | Enchanted Sentinel 3/5 T4 $3 | Woodland Defiler 5/6 T4 $3 | Technical Element 7/8 T3 $3

  → Board after: 67/66 [Reborn], 64/67, 102/103, 102/102, 103/102, 103/104, 103/105 [DS]
  → Gold: 10→0

**Drek'Thar**  HP=28 Armor=0 Gold=10 Tier=6

  Board: 43/42, 39/46, 37/38, 38/38, 66/70, 66/70, 68/68
  Tavern: Plaguerunner 4/2 T4 $3 | Skulking Bristlemane 5/2 T3 $3 | Ashen Corruptor 6/6 T5 $3 | Air Revenant 3/6 T5 $3 | Annoy-o-Tron 1/2 T1 $3 | Firelands Fugitive 5/7 T5 $3

  → Board after: 66/70, 68/68, 106/106, 106/108, 105/108, 108/105 [Taunt], 108/106
  → Gold: 10→0

**⚔ Combat Phase**

  💀 **Yogg-Saron, Hope's End eliminated!** (HP=0, Turn 8)
  💀 **Sneed eliminated!** (HP=0, Turn 8)
  💀 **Inge, the Iron Hymn eliminated!** (HP=0, Turn 8)
  Alive: 5/8
  HP standings: Overlord Saurfang (HP=30, Armor=18, Tier=6) | Drek'Thar (HP=28, Armor=0, Tier=6) | Sylvanas Windrunner (HP=27, Armor=0, Tier=6) | Ysera (HP=1, Armor=0, Tier=6) | Professor Putricide (HP=1, Armor=0, Tier=6)

### Turn 9

**Overlord Saurfang**  HP=30 Armor=18 Gold=10 Tier=6

  Board: 74/74, 75/74, 108/112, 141/142, 109/113, 111/112, 111/113 [Taunt,DS]
  Tavern: Nightmare Par-tea Guest 45/45 T5 $3 | Ashen Corruptor 46/46 T5 $3 | Sun-Bacon Relaxer 42/43 T1 $3 | One-Amalgam Tour Group 48/49 T6 $3 | Accord-o-Tron 43/43 T3 $3 | Drustfallen Butcher 42/49 T5 $3

  → Board after: 145/146, 116/118 [Taunt,DS], 154/155, 155/155, 151/158, 154/154, 153/153
  → Gold: 10→0

**Ysera**  HP=1 Armor=0 Gold=10 Tier=6

  Board: 59/59 [Reborn], 59/59 [Reborn], 86/88, 86/86, 89/92, 87/90, 89/87 [Reborn]
  Tavern: Darkgaze Elder 7/9 T5 $3 | Famished Felbat 10/6 T6 $3 | En-Djinn Blazer 5/5 T4 $3 | Prickly Piper 6/2 T3 $3 | Laboratory Assistant 4/5 T2 $3 | Shadowdancer 6/4 T5 $3

  → Board after: 100/103, 92/95, 120/122, 122/118, 119/119, 120/118 [Taunt], 119/120
  → Gold: 10→0 | HP: 1→0

**Professor Putricide**  HP=1 Armor=0 Gold=10 Tier=6

  Board: 65/64, 63/63, 98/98, 96/100, 100/96, 100/97, 98/98
  Tavern: Wrath Weaver 4/7 T1 $3 | Hired Ritualist 6/8 T4 $3 | Deflect-o-Bot 6/5 T3 $3 | Marquee Ticker 2/6 T4 $3 | Annoy-o-Module 5/7 T3 $3 | Waveling 9/4 T3 $3

  → Board after: 100/96, 100/97, 121/123, 125/120, 122/124 [Taunt,DS], 124/127, 125/124 [DS]
  → Gold: 10→0 | HP: 1→0

**Sylvanas Windrunner**  HP=27 Armor=0 Gold=10 Tier=6

  Board: 68/66 [Reborn], 65/67, 102/103, 102/102, 103/102, 103/104, 103/105 [DS]
  Tavern: Auto Assembler 2/2 T4 $3 | Earthsong Shaman 4/5 T6 $3 | Hired Ritualist 5/7 T4 $3 | Cadaver Caretaker 7/5 T3 $3 | Moonsteel Juggernaut 6/6 T6 $3 | Marquee Ticker 1/5 T4 $3

  → Board after: 103/104, 103/105 [DS], 127/125, 126/128, 128/128, 127/128 [WF], 125/129
  → Gold: 10→0

**Drek'Thar**  HP=28 Armor=0 Gold=10 Tier=6

  Board: 66/70, 68/68, 106/106, 106/108, 105/108, 108/105 [Taunt], 108/106
  Tavern: Redtusk Thornraiser 3/7 T4 $3 | Wrath Weaver 1/4 T1 $3 | Dustbone Devastator 2/6 T3 $3 | Felemental 3/3 T3 $3 | Annoy-o-Module 2/4 T3 $3 | Soul Rewinder 4/1 T2 $3

  → Board after: 106/108, 108/106, 128/132, 128/132, 130/130, 130/132 [Taunt,DS], 132/135
  → Gold: 10→0 | HP: 28→27

**⚔ Combat Phase**

  💀 **Ysera eliminated!** (HP=0, Turn 9)
  💀 **Professor Putricide eliminated!** (HP=0, Turn 9)
  Alive: 3/8
  HP standings: Overlord Saurfang (HP=30, Armor=18, Tier=6) | Drek'Thar (HP=27, Armor=0, Tier=6) | Sylvanas Windrunner (HP=2, Armor=0, Tier=6)

### Turn 10

**Overlord Saurfang**  HP=30 Armor=18 Gold=11 Tier=6

  Board: 187/189, 116/118 [Taunt,DS], 154/155, 155/155, 151/158, 154/154, 153/153
  Tavern: Charging Czarina 53/49 T5 $3 | Fire Baller 53/52 T2 $3 | Cadaver Caretaker 50/50 T3 $3 | En-Djinn Blazer 53/53 T4 $3 | Falling Sky Golem 4/49 T6 $3 | Refreshing Anomaly 53/54 T4 $3

  → Board after: 190/192, 157/157, 186/187, 186/186, 188/187, 187/183 [DS], 185/185
  → Gold: 11→0

**Sylvanas Windrunner**  HP=2 Armor=0 Gold=10 Tier=6

  Board: 115/116, 111/113 [DS], 135/133, 134/136, 136/136, 135/136 [WF], 133/137
  Tavern: Bazaar Dealer 4/6 T5 $3 | Razorfen Geomancer 4/3 T1 $3 | Bazaar Dealer 4/6 T5 $3 | Ichoron the Protector 4/2 T4 $3 | Sun-Bacon Relaxer 4/5 T1 $3 | Laboratory Assistant 5/6 T2 $3

  → Board after: 136/136, 135/136 [WF], 144/144, 140/142, 141/142, 142/140 [DS], 3/3
  → Gold: 10→0

**Drek'Thar**  HP=27 Armor=0 Gold=10 Tier=6

  Board: 106/108, 108/106, 128/132, 128/132, 130/130, 130/132 [Taunt,DS], 132/135
  Tavern: Friendly Geist 7/4 T4 $3 | One-Amalgam Tour Group 9/9 T6 $3 | Technical Element 6/7 T3 $3 | Sinrunner Blanchy 9/9 T5 $3 | Ultraviolet Ascendant 9/5 T6 $3 | Prickly Piper 6/2 T3 $3

  → Board after: 135/137 [Taunt,DS], 137/140, 150/150, 151/151 [Reborn], 151/147, 150/151, 151/148
  → Gold: 10→0

**⚔ Combat Phase**

  💀 **Sylvanas Windrunner eliminated!** (HP=0, Turn 10)
  Alive: 2/8
  HP standings: Overlord Saurfang (HP=30, Armor=18, Tier=6) | Drek'Thar (HP=27, Armor=0, Tier=6)

### Turn 11

**Overlord Saurfang**  HP=30 Armor=18 Gold=11 Tier=6

  Board: 245/253, 157/157, 186/187, 186/186, 188/187, 187/183 [DS], 185/185
  Tavern: Razorfen Geomancer 52/51 T1 $3 | Metallic Hunter 52/51 T2 $3 | Flaming Enforcer 57/58 T4 $3 | Ultraviolet Ascendant 58/55 T6 $3 | Glowgullet Warlord 52/52 T2 $3 | Sun-Bacon Relaxer 55/56 T1 $3

  → Board after: 247/255, 191/190, 203/204, 204/201, 204/205, 200/200, 201/200
  → Gold: 11→0

**Drek'Thar**  HP=27 Armor=0 Gold=10 Tier=6

  Board: 135/137 [Taunt,DS], 137/137, 150/150, 151/151 [Reborn], 151/147, 150/151, 151/148
  Tavern: Drustfallen Butcher 3/10 T5 $3 | Bristlebach 4/11 T6 $3 | Auto Assembler 3/3 T4 $3 | Ultraviolet Ascendant 11/6 T6 $3 | Wrath Weaver 2/5 T1 $3 | Wildfire Elemental 11/6 T3 $3

  → Board after: 154/154 [Reborn], 154/155, 162/157, 164/159, 156/163, 156/163, 158/161
  → Gold: 10→0 | HP: 27→26

**⚔ Combat Phase**

  Alive: 2/8
  HP standings: Overlord Saurfang (HP=30, Armor=18, Tier=6) | Drek'Thar (HP=6, Armor=0, Tier=6)

### Turn 12

**Overlord Saurfang**  HP=30 Armor=18 Gold=10 Tier=6

  Board: 300/315, 191/190, 259/264, 204/201, 204/205, 200/200, 201/200
  Tavern: Rot Hide Gnoll 57/60 T1 $3 | Dune Dweller 61/60 T1 $3 | Wildfire Elemental 61/58 T3 $3 | Crackling Cyclone 57/56 T1 $3 | Dustbone Devastator 55/59 T3 $3 | Malchezaar, Prince of Dance 58/57 T4 $3

  → Board after: 301/316, 260/265, 220/219, 218/215, 216/219, 216/215, 4/4
  → Gold: 10→0

**Drek'Thar**  HP=6 Armor=0 Gold=10 Tier=6

  Board: 154/154 [Reborn], 154/155, 162/157, 164/159, 156/163, 156/163, 158/161
  Tavern: Accord-o-Tron 4/4 T3 $3 | Catacomb Crasher 5/11 T5 $3 | En-Djinn Blazer 13/9 T4 $3 | Twisted Wrathguard 5/5 T5 $3 | Consummate Conqueror 10/8 T6 $3 | Bristleback Bully 4/3 T2 $3

  → Board after: 169/164, 167/170, 175/171, 170/168, 167/173, 167/167, 167/167
  → Gold: 10→0 | HP: 6→4

**⚔ Combat Phase**

  💀 **Overlord Saurfang eliminated!** (HP=0, Turn 12)
  💀 **Drek'Thar eliminated!** (HP=0, Turn 12)

---

## Final Standings

| # | Hero | HP | Armor | Alive | Eliminated Turn |
|---|---|---|---|---|
| 1 | Overlord Saurfang | 30 | 18 | No | 12 |
| 2 | Drek'Thar | 0 | 0 | No | 12 |
| 3 | Sylvanas Windrunner | 0 | 0 | No | 10 |
| 4 | Ysera | 0 | 0 | No | 9 |
| 5 | Professor Putricide | 0 | 0 | No | 9 |
| 6 | Yogg-Saron, Hope's End | 0 | 0 | No | 8 |
| 7 | Sneed | 0 | 0 | No | 8 |
| 8 | Inge, the Iron Hymn | 0 | 0 | No | 8 |

---

## Heuristic Strategy

The Q-score heuristic evaluates each affordable tavern minion by:

1. **Buy & Play**: Score = current_board_score + minion.atk + minion.health + aura_bonus
2. **Sell & Replace**: If board full, replace weakest minion if net score change > 0
3. **Upgrade**: If no beneficial buy is available and gold ≥ upgrade_cost, upgrade tavern tier
4. **Refresh**: If no other action is possible, refresh the tavern for 1 gold

This is a greedy one-step heuristic — no lookahead, no opponent modeling, no combat simulation.
Average rank in self-play: ~4.5 (random among identical strategies)