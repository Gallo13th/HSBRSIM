# 8-Player Battlegrounds — All Heuristic Demo

**Seed**: 99  |  **Max Turns**: 15  |  **Agents**: 8× Greedy Q-Score Heuristic

## Players

| # | Hero | HP | Armor | Tier |
|---|---|---|---|---|
| 1 | Murozond, Unbounded | 30 | 12 | 1 |
| 2 | Forest Lord Cenarius | 30 | 12 | 1 |
| 3 | Murloc Holmes | 30 | 15 | 1 |
| 4 | Sindragosa | 30 | 15 | 1 |
| 5 | Ambassador Faelin | 30 | 10 | 1 |
| 6 | Sire Denathrius | 30 | 15 | 1 |
| 7 | Professor Putricide | 30 | 10 | 1 |
| 8 | Drek'Thar | 30 | 12 | 1 |

---

## Game Log

### Turn 1

**Murozond, Unbounded**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Picky Eater 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Crackling Cyclone 2/1 T1 $3 | Siren's Song (spell) T1 $3

  → Board after: 2/1 [DS,WF]
  → Gold: 3→0

**Forest Lord Cenarius**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Dune Dweller 3/2 T1 $3 | Crackling Cyclone 2/1 T1 $3 | Crackling Cyclone 2/1 T1 $3 | Copy Non-Golden (spell) T1 $3

  → Board after: 3/2
  → Gold: 3→0

**Murloc Holmes**  HP=30 Armor=15 Gold=3 Tier=1

  Board: (empty)
  Tavern: Picky Eater 1/1 T1 $3 | Wrath Weaver 1/3 T1 $3 | Ominous Seer 4/2 T1 $3 | Sick Riffs (spell) T1 $3

  → Board after: 4/2
  → Gold: 3→0

**Sindragosa**  HP=30 Armor=15 Gold=3 Tier=1

  Board: (empty)
  Tavern: Cord Puller 1/1 T1 $3 | Wrath Weaver 1/3 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Meditation (spell) T1 $3

  → Board after: 1/3
  → Gold: 3→0

**Ambassador Faelin**  HP=30 Armor=10 Gold=3 Tier=1

  Board: (empty)
  Tavern: Cord Puller 1/1 T1 $3 | Cord Puller 1/1 T1 $3 | Crackling Cyclone 2/1 T1 $3 | Meditation (spell) T1 $3

  → Board after: 2/1 [DS,WF]
  → Gold: 3→0

**Sire Denathrius**  HP=30 Armor=15 Gold=3 Tier=1

  Board: (empty)
  Tavern: Risen Rider 2/1 T1 $3 | Ominous Seer 4/2 T1 $3 | Crackling Cyclone 2/1 T1 $3 | Undersea Mount (spell) T1 $3

  → Board after: 4/2
  → Gold: 3→0

**Professor Putricide**  HP=30 Armor=10 Gold=3 Tier=1

  Board: (empty)
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Picky Eater 1/1 T1 $3 | A New Sprout (spell) T1 $3

  → Board after: 1/2 [Taunt,DS]
  → Gold: 3→0

**Drek'Thar**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Picky Eater 1/1 T1 $3 | Dune Dweller 3/2 T1 $3 | Accelerator (spell) T1 $3

  → Board after: 3/2
  → Gold: 3→0

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Murozond, Unbounded (HP=30, Armor=12, Tier=1) | Forest Lord Cenarius (HP=30, Armor=12, Tier=1) | Murloc Holmes (HP=30, Armor=13, Tier=1) | Sindragosa (HP=30, Armor=13, Tier=1) | Ambassador Faelin (HP=30, Armor=10, Tier=1) | Sire Denathrius (HP=30, Armor=15, Tier=1) | Professor Putricide (HP=30, Armor=10, Tier=1) | Drek'Thar (HP=30, Armor=12, Tier=1)

### Turn 2

**Murozond, Unbounded**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 2/1 [DS,WF]
  Tavern: Risen Rider 2/1 T1 $3 | Ominous Seer 4/2 T1 $3 | Wrath Weaver 1/3 T1 $3 | Slimy Shield (spell) T1 $3

  → Board after: 2/1 [DS,WF], 4/2
  → Gold: 4→0

**Forest Lord Cenarius**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 3/2
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Rot Hide Gnoll 1/4 T1 $3 | Windfall Tornado 5/5 T1 $3 | Rime or Reason (spell) T1 $3

  → Board after: 3/2, 5/5
  → Gold: 4→0

**Murloc Holmes**  HP=30 Armor=13 Gold=4 Tier=1

  Board: 4/2
  Tavern: Windfall Tornado 4/4 T1 $3 | Rot Hide Gnoll 1/4 T1 $3 | Dune Dweller 3/2 T1 $3 | Recruit a Trainee (spell) T1 $2

  → Board after: 4/2, 4/4
  → Gold: 4→0

**Sindragosa**  HP=30 Armor=13 Gold=4 Tier=1

  Board: 1/3
  Tavern: Picky Eater 1/1 T1 $3 | Ominous Seer 4/2 T1 $3 | Picky Eater 1/1 T1 $3 | Pointy Arrow (spell) T1 $1

  → Board after: 1/3, 4/2
  → Gold: 4→0

**Ambassador Faelin**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 2/1 [DS,WF]
  Tavern: Harmless Bonehead 1/1 T1 $3 | Windfall Tornado 4/4 T1 $3 | Ominous Seer 4/2 T1 $3 | Lantern Light (spell) T1 $3

  → Board after: 2/1 [DS,WF], 4/4
  → Gold: 4→0

**Sire Denathrius**  HP=30 Armor=15 Gold=4 Tier=1

  Board: 4/2
  Tavern: Risen Rider 2/1 T1 $3 | Wrath Weaver 1/3 T1 $3 | Ominous Seer 4/2 T1 $3 | Slumber Sorcerer's Spellcraft (spell) T1 $0

  → Board after: 4/2, 4/2
  → Gold: 4→0

**Professor Putricide**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 1/2 [Taunt,DS]
  Tavern: Picky Eater 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Dune Dweller 3/2 T1 $3 | Windfury + Divine Shield (spell) T1 $3

  → Board after: 1/2 [Taunt,DS], 3/2
  → Gold: 4→0

**Drek'Thar**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 3/2
  Tavern: Crackling Cyclone 3/2 T1 $3 | Dune Dweller 4/3 T1 $3 | Risen Rider 2/1 T1 $3 | Tavern Coin (spell) T1 $1

  → Board after: 3/2, 4/3
  → Gold: 4→0

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Murozond, Unbounded (HP=30, Armor=12, Tier=1) | Forest Lord Cenarius (HP=30, Armor=12, Tier=1) | Murloc Holmes (HP=30, Armor=13, Tier=1) | Sindragosa (HP=30, Armor=11, Tier=1) | Ambassador Faelin (HP=30, Armor=10, Tier=1) | Sire Denathrius (HP=30, Armor=15, Tier=1) | Professor Putricide (HP=30, Armor=10, Tier=1) | Drek'Thar (HP=30, Armor=12, Tier=1)

### Turn 3

**Murozond, Unbounded**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 2/1 [DS,WF], 4/2
  Tavern: Harmless Bonehead 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Windfall Tornado 4/4 T1 $3 | Enchanted Lasso (spell) T1 $2

  → Board after: 2/1 [DS,WF], 4/2, 4/4
  → Gold: 5→0 | Tier: 1→2

**Forest Lord Cenarius**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 3/2, 5/5
  Tavern: Harmless Bonehead 1/1 T1 $3 | Crackling Cyclone 3/2 T1 $3 | Rot Hide Gnoll 1/4 T1 $3 | Crab Mount (spell) T1 $3

  → Board after: 3/2, 5/5, 3/2 [DS,WF]
  → Gold: 5→0 | Tier: 1→2

**Murloc Holmes**  HP=30 Armor=13 Gold=5 Tier=1

  Board: 4/2, 4/4
  Tavern: Cord Puller 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Cloning Conch (spell) T1 $0

  → Board after: 4/2, 4/4, 1/2 [Taunt,DS]
  → Gold: 5→0 | Tier: 1→2

**Sindragosa**  HP=30 Armor=11 Gold=5 Tier=1

  Board: 1/3, 4/2
  Tavern: Wrath Weaver 1/3 T1 $3 | Cord Puller 1/1 T1 $3 | Ominous Seer 4/2 T1 $3 | Fortify (spell) T1 $1

  → Board after: 1/3, 4/2, 4/2
  → Gold: 5→0 | Tier: 1→2

**Ambassador Faelin**  HP=30 Armor=10 Gold=5 Tier=1

  Board: 2/1 [DS,WF], 4/4
  Tavern: Rot Hide Gnoll 1/4 T1 $3 | Cord Puller 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Them Apples (spell) T1 $1

  → Board after: 2/1 [DS,WF], 4/4, 1/4
  → Gold: 5→0 | Tier: 1→2

**Sire Denathrius**  HP=30 Armor=15 Gold=5 Tier=1

  Board: 4/2, 4/2
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Risen Rider 2/1 T1 $3 | The Goldenizer (spell) T1 $0

  → Board after: 4/2, 4/2, 1/2 [Taunt,DS]
  → Gold: 5→0 | Tier: 1→2

**Professor Putricide**  HP=30 Armor=10 Gold=5 Tier=1

  Board: 1/2 [Taunt,DS], 3/2
  Tavern: Harmless Bonehead 1/1 T1 $3 | Wrath Weaver 1/3 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Spare Part (spell) T1 $3

  → Board after: 1/2 [Taunt,DS], 3/2, 1/3
  → Gold: 5→0 | Tier: 1→2

**Drek'Thar**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 3/2, 4/3
  Tavern: Risen Rider 2/1 T1 $3 | Harmless Bonehead 1/1 T1 $3 | Harmless Bonehead 1/1 T1 $3

  → Board after: 3/2, 4/3, 2/1 [Taunt,Reborn]
  → Gold: 5→0 | Tier: 1→2

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Murozond, Unbounded (HP=30, Armor=12, Tier=2) | Forest Lord Cenarius (HP=30, Armor=12, Tier=2) | Murloc Holmes (HP=30, Armor=13, Tier=2) | Sindragosa (HP=30, Armor=7, Tier=2) | Ambassador Faelin (HP=30, Armor=10, Tier=2) | Sire Denathrius (HP=30, Armor=11, Tier=2) | Professor Putricide (HP=30, Armor=10, Tier=2) | Drek'Thar (HP=30, Armor=12, Tier=2)

### Turn 4

**Murozond, Unbounded**  HP=30 Armor=12 Gold=6 Tier=2

  Board: 2/1 [DS,WF], 4/2, 4/4
  Tavern: Cord Puller 1/1 T1 $3 | Fire Baller 4/3 T2 $3 | Fire Baller 4/3 T2 $3 | Crackling Cyclone 2/1 T1 $3 | Hasty Excavation (spell) T2 $3

  → Board after: 2/1 [DS,WF], 4/2, 4/4, 4/3, 4/3
  → Gold: 6→0

**Forest Lord Cenarius**  HP=30 Armor=12 Gold=6 Tier=2

  Board: 3/2, 5/5, 3/2 [DS,WF]
  Tavern: Metallic Hunter 4/2 T2 $3 | Scarlet Skull 2/1 T2 $3 | Dune Dweller 4/3 T1 $3 | Dune Dweller 4/3 T1 $3 | Leaf Through the Pages (spell) T2 $1

  → Board after: 5/5, 3/2 [DS,WF], 8/6 [G], 2/2
  → Gold: 6→0

**Murloc Holmes**  HP=30 Armor=13 Gold=6 Tier=2

  Board: 4/2, 4/4, 1/2 [Taunt,DS]
  Tavern: Fire Baller 4/3 T2 $3 | Snow Baller 3/4 T2 $3 | Alert Alarmist 2/2 T2 $3 | Crackling Cyclone 2/1 T1 $3 | Strike Oil (spell) T2 $3

  → Board after: 4/2, 4/4, 1/2 [Taunt,DS], 4/3, 3/4
  → Gold: 6→0

**Sindragosa**  HP=30 Armor=7 Gold=6 Tier=2

  Board: 1/3, 4/2, 4/2
  Tavern: Eternal Knight 4/2 T2 $3 | Lava Lurker 2/5 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Old Soul 3/4 T2 $3 | Search Through Time (spell) T2 $2

  → Board after: 1/3, 4/2, 4/2, 2/5, 3/4
  → Gold: 6→0

**Ambassador Faelin**  HP=30 Armor=10 Gold=6 Tier=2

  Board: 2/1 [DS,WF], 4/4, 1/4
  Tavern: Fire Baller 4/3 T2 $3 | Shell Collector 4/3 T2 $3 | Old Soul 3/4 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Might of Stormwind (spell) T2 $2

  → Board after: 2/1 [DS,WF], 4/4, 1/4, 4/3, 4/3
  → Gold: 6→0

**Sire Denathrius**  HP=30 Armor=11 Gold=6 Tier=2

  Board: 4/2, 4/2, 1/2 [Taunt,DS]
  Tavern: Crackling Cyclone 2/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Laboratory Assistant 3/4 T2 $3 | Eternal Knight 4/2 T2 $3 | Chef's Choice (spell) T2 $2

  → Board after: 4/2, 4/2, 1/2 [Taunt,DS], 3/4, 4/2
  → Gold: 6→0

**Professor Putricide**  HP=30 Armor=10 Gold=6 Tier=2

  Board: 1/2 [Taunt,DS], 3/2, 1/3
  Tavern: Laboratory Assistant 3/4 T2 $3 | Windfall Tornado 5/5 T1 $3 | Ominous Seer 4/2 T1 $3 | Soul Rewinder 4/1 T2 $3

  → Board after: 1/2 [Taunt,DS], 3/2, 3/5, 5/5, 3/4
  → Gold: 6→0 | Armor: 10→9

**Drek'Thar**  HP=30 Armor=12 Gold=6 Tier=2

  Board: 3/2, 4/3, 2/1 [Taunt,Reborn]
  Tavern: Laboratory Assistant 3/4 T2 $3 | Surf n' Surf 1/1 T1 $3 | Reef Riffer 3/2 T2 $3 | Windfall Tornado 6/6 T1 $3

  → Board after: 3/2, 4/3, 2/1 [Taunt,Reborn], 6/6, 3/4
  → Gold: 6→0

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Murozond, Unbounded (HP=30, Armor=12, Tier=2) | Forest Lord Cenarius (HP=30, Armor=12, Tier=2) | Murloc Holmes (HP=30, Armor=13, Tier=2) | Sindragosa (HP=30, Armor=7, Tier=2) | Ambassador Faelin (HP=30, Armor=6, Tier=2) | Sire Denathrius (HP=30, Armor=7, Tier=2) | Professor Putricide (HP=30, Armor=9, Tier=2) | Drek'Thar (HP=30, Armor=12, Tier=2)

### Turn 5

**Murozond, Unbounded**  HP=30 Armor=12 Gold=7 Tier=2

  Board: 2/1 [DS,WF], 4/2, 4/4, 4/3, 4/3
  Tavern: Wrath Weaver 1/3 T1 $3 | Ancestral Automaton 3/4 T2 $3 | Cord Puller 1/1 T1 $3 | Picky Eater 1/1 T1 $3

  → Gold: 7→0 | Tier: 2→3

**Forest Lord Cenarius**  HP=30 Armor=12 Gold=7 Tier=2

  Board: 5/5, 3/2 [DS,WF], 8/6 [G], 2/2
  Tavern: Alert Alarmist 2/2 T2 $3 | Snow Baller 6/7 T2 $3 | Shell Collector 4/3 T2 $3 | Fire Baller 7/6 T2 $3

  → Gold: 7→0 | Tier: 2→3

**Murloc Holmes**  HP=30 Armor=13 Gold=7 Tier=2

  Board: 4/2, 4/4, 1/2 [Taunt,DS], 4/3, 3/4
  Tavern: Eternal Knight 4/2 T2 $3 | Shell Collector 4/3 T2 $3 | Reef Riffer 3/2 T2 $3 | Rot Hide Gnoll 1/4 T1 $3

  → Gold: 7→0 | Tier: 2→3

**Sindragosa**  HP=30 Armor=7 Gold=7 Tier=2

  Board: 1/3, 4/2, 4/2, 2/5, 3/4
  Tavern: Fire Baller 4/3 T2 $3 | Old Soul 3/4 T2 $3 | Lava Lurker 2/5 T2 $3 | Soul Rewinder 4/1 T2 $3

  → Gold: 7→0 | Tier: 2→3

**Ambassador Faelin**  HP=30 Armor=6 Gold=7 Tier=2

  Board: 2/1 [DS,WF], 4/4, 1/4, 4/3, 4/3
  Tavern: Shell Collector 4/3 T2 $3 | Dune Dweller 3/2 T1 $3 | Wrath Weaver 1/3 T1 $3 | Alert Alarmist 2/2 T2 $3

  → Gold: 7→0 | Tier: 2→3

**Sire Denathrius**  HP=30 Armor=7 Gold=7 Tier=2

  Board: 4/2, 4/2, 1/2 [Taunt,DS], 3/4, 5/2
  Tavern: Ancestral Automaton 3/4 T2 $3 | Windfall Tornado 4/4 T1 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Metallic Hunter 4/2 T2 $3

  → Gold: 7→0 | Tier: 2→3

**Professor Putricide**  HP=30 Armor=9 Gold=7 Tier=2

  Board: 1/2 [Taunt,DS], 3/2, 3/5, 5/5, 3/4
  Tavern: Nerubian Deathswarmer 1/4 T2 $3 | Tide Raiser 2/1 T2 $3 | Cord Puller 1/1 T1 $3 | Shell Collector 4/3 T2 $3

  → Gold: 7→0 | Tier: 2→3

**Drek'Thar**  HP=30 Armor=12 Gold=7 Tier=2

  Board: 3/2, 4/3, 2/1 [Taunt,Reborn], 6/6, 3/4
  Tavern: Laboratory Assistant 3/4 T2 $3 | Metallic Hunter 4/2 T2 $3 | Scarlet Skull 2/1 T2 $3 | Reef Riffer 3/2 T2 $3

  → Gold: 7→0 | Tier: 2→3

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Murozond, Unbounded (HP=30, Armor=12, Tier=3) | Forest Lord Cenarius (HP=30, Armor=12, Tier=3) | Murloc Holmes (HP=30, Armor=13, Tier=3) | Sindragosa (HP=30, Armor=7, Tier=3) | Ambassador Faelin (HP=30, Armor=1, Tier=3) | Sire Denathrius (HP=30, Armor=7, Tier=3) | Professor Putricide (HP=30, Armor=5, Tier=3) | Drek'Thar (HP=30, Armor=12, Tier=3)

### Turn 6

**Murozond, Unbounded**  HP=30 Armor=12 Gold=8 Tier=3

  Board: 2/1 [DS,WF], 4/2, 4/4, 4/3, 4/3
  Tavern: Shell Collector 4/3 T2 $3 | Deep Blue Crooner 2/2 T3 $3 | Ominous Seer 4/2 T1 $3 | Laboratory Assistant 3/4 T2 $3

  → Board after: 2/1 [DS,WF], 4/2, 4/4, 4/3, 4/3, 4/3, 3/4
  → Gold: 8→0

**Forest Lord Cenarius**  HP=30 Armor=12 Gold=8 Tier=3

  Board: 5/5, 3/2 [DS,WF], 8/6 [G], 2/2
  Tavern: Picky Eater 1/1 T1 $3 | Tide Raiser 2/1 T2 $3 | Metallic Hunter 4/2 T2 $3 | Laboratory Assistant 3/4 T2 $3

  → Board after: 5/5, 3/2 [DS,WF], 8/6 [G], 2/2, 3/4, 4/2
  → Gold: 8→0

**Murloc Holmes**  HP=30 Armor=13 Gold=8 Tier=3

  Board: 4/2, 4/4, 1/2 [Taunt,DS], 4/3, 3/4
  Tavern: Reef Riffer 3/2 T2 $3 | Leeching Felhound 3/3 T3 $3 | Lava Lurker 2/5 T2 $3 | Ominous Seer 4/2 T1 $3

  → Board after: 4/4, 4/3, 3/4, 2/5, 3/3, 4/2, 3/2
  → Gold: 8→0 | Armor: 13→10

**Sindragosa**  HP=30 Armor=7 Gold=8 Tier=3

  Board: 1/3, 4/2, 4/2, 2/5, 3/4
  Tavern: Risen Rider 2/1 T1 $3 | Risen Rider 2/1 T1 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Scarlet Skull 2/1 T2 $3

  → Board after: 1/3, 4/2, 4/2, 2/5, 4/4, 2/4, 3/1 [Taunt,Reborn]
  → Gold: 8→0

**Ambassador Faelin**  HP=30 Armor=1 Gold=8 Tier=3

  Board: 2/1 [DS,WF], 4/4, 1/4, 4/3, 4/3
  Tavern: Soul Rewinder 4/1 T2 $3 | Tide Raiser 2/1 T2 $3 | Cadaver Caretaker 3/3 T3 $3 | Fire Baller 4/3 T2 $3

  → Board after: 2/1 [DS,WF], 4/4, 1/4, 4/3, 4/3, 4/3, 3/3
  → Gold: 8→0

**Sire Denathrius**  HP=30 Armor=7 Gold=8 Tier=3

  Board: 4/2, 4/2, 1/2 [Taunt,DS], 3/4, 6/2
  Tavern: Ominous Seer 4/2 T1 $3 | Dustbone Devastator 2/6 T3 $3 | Windfall Tornado 4/4 T1 $3 | False Implicator 1/1 T3 $3

  → Board after: 4/2, 4/2, 5/6 [Taunt,DS], 3/4, 6/2, 2/6, 4/4
  → Gold: 8→0

**Professor Putricide**  HP=30 Armor=5 Gold=8 Tier=3

  Board: 1/2 [Taunt,DS], 3/2, 3/5, 5/5, 3/4
  Tavern: Shell Collector 4/3 T2 $3 | Waveling 7/2 T3 $3 | False Implicator 1/1 T3 $3 | Dune Dweller 4/3 T1 $3

  → Board after: 1/2 [Taunt,DS], 3/2, 3/5, 5/5, 14/9, 7/2, 4/3
  → Gold: 8→0

**Drek'Thar**  HP=30 Armor=12 Gold=8 Tier=3

  Board: 3/2, 4/3, 2/1 [Taunt,Reborn], 6/6, 3/4
  Tavern: Deflect-o-Bot 3/2 T3 $3 | Wildfire Elemental 8/5 T3 $3 | Ancestral Automaton 3/4 T2 $3 | Felemental 5/5 T3 $3

  → Board after: 3/2, 17/13, 2/1 [Taunt,Reborn], 6/6, 3/4, 8/5, 5/5
  → Gold: 8→0

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Murozond, Unbounded (HP=30, Armor=8, Tier=3) | Forest Lord Cenarius (HP=30, Armor=12, Tier=3) | Murloc Holmes (HP=30, Armor=2, Tier=3) | Sindragosa (HP=30, Armor=7, Tier=3) | Sire Denathrius (HP=30, Armor=7, Tier=3) | Professor Putricide (HP=30, Armor=5, Tier=3) | Drek'Thar (HP=30, Armor=12, Tier=3) | Ambassador Faelin (HP=21, Armor=0, Tier=3)

### Turn 7

**Murozond, Unbounded**  HP=30 Armor=8 Gold=9 Tier=3

  Board: 2/1 [DS,WF], 4/2, 4/4, 4/3, 4/3, 4/3, 3/4
  Tavern: Picky Eater 1/1 T1 $3 | Deep-Sea Angler 2/3 T3 $3 | Old Soul 3/4 T2 $3 | Scarlet Skull 2/1 T2 $3

  → Board after: 4/2, 4/4, 7/7, 4/3, 4/3, 3/4, 3/4
  → Gold: 9→0 | Tier: 3→4

**Forest Lord Cenarius**  HP=30 Armor=12 Gold=9 Tier=3

  Board: 5/5, 3/2 [DS,WF], 8/6 [G], 2/2, 3/4, 4/2
  Tavern: Old Soul 3/4 T2 $3 | Scarlet Skull 2/1 T2 $3 | Deep-Sea Angler 2/3 T3 $3 | Annoy-o-Tron 1/2 T1 $3

  → Board after: 5/5, 6/6 [DS,WF], 8/6 [G], 2/2, 3/4, 4/2, 3/4
  → Gold: 9→0 | Tier: 3→4

**Murloc Holmes**  HP=30 Armor=2 Gold=9 Tier=3

  Board: 4/4, 4/3, 3/4, 2/5, 3/3, 4/2, 3/2
  Tavern: Scarlet Skull 2/1 T2 $3 | Deep-Sea Angler 2/3 T3 $3 | Sellemental 3/3 T2 $3 | Floating Watcher 4/4 T3 $5

  → Board after: 4/4, 7/6, 3/4, 2/5, 3/3, 4/2, 3/3
  → Gold: 9→0 | Tier: 3→4

**Sindragosa**  HP=30 Armor=7 Gold=9 Tier=3

  Board: 1/3, 4/2, 4/2, 2/5, 4/4, 2/4, 3/1 [Taunt,Reborn]
  Tavern: Crackling Cyclone 2/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Metallic Hunter 4/2 T2 $3 | Mummifier 6/2 T3 $3

  → Board after: 4/2, 4/2, 8/7, 4/4, 2/4, 3/1 [Taunt,Reborn], 6/2
  → Gold: 9→0 | Tier: 3→4

**Ambassador Faelin**  HP=21 Armor=0 Gold=9 Tier=3

  Board: 2/1 [DS,WF], 4/4, 1/4, 4/3, 4/3, 4/3, 3/3
  Tavern: Laboratory Assistant 9/10 T2 $3 | Metallic Hunter 4/2 T2 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Old Soul 3/4 T2 $3

  → Board after: 13/14, 1/4, 4/3, 4/3, 4/3, 3/3, 9/10 [DS]
  → Gold: 9→0 | Tier: 3→4

**Sire Denathrius**  HP=30 Armor=7 Gold=9 Tier=3

  Board: 4/2, 4/2, 5/6 [Taunt,DS], 3/4, 7/2, 3/6, 4/4
  Tavern: Surf n' Surf 1/1 T1 $3 | Floating Watcher 4/4 T3 $5 | Dune Dweller 3/2 T1 $3 | Metallic Hunter 4/2 T2 $3

  → Board after: 8/4, 5/6 [Taunt,DS], 3/4, 7/2, 3/6, 4/4, 4/2
  → Gold: 9→0 | Tier: 3→4

**Professor Putricide**  HP=30 Armor=5 Gold=9 Tier=3

  Board: 1/2 [Taunt,DS], 3/2, 3/5, 5/5, 14/9, 7/2, 4/3
  Tavern: Accord-o-Tron 3/3 T3 $3 | Deep-Sea Angler 2/3 T3 $3 | Eternal Knight 4/2 T2 $3 | Laboratory Assistant 3/4 T2 $3

  → Board after: 3/2, 8/11, 5/5, 14/9, 7/2, 4/3, 3/4
  → Gold: 9→0 | Tier: 3→4 | Armor: 5→4

**Drek'Thar**  HP=30 Armor=12 Gold=9 Tier=3

  Board: 3/2, 17/13, 2/1 [Taunt,Reborn], 6/6, 3/4, 8/5, 5/5
  Tavern: Deflect-o-Bot 18/17 T3 $3 | Mummifier 20/17 T3 $3 | Fire Baller 25/24 T2 $3 | Cadaver Caretaker 18/18 T3 $3

  → Board after: 28/26, 17/13, 6/6, 3/4, 8/5, 5/5, 25/24
  → Gold: 9→0 | Tier: 3→4

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Murozond, Unbounded (HP=30, Armor=8, Tier=4) | Forest Lord Cenarius (HP=30, Armor=12, Tier=4) | Sire Denathrius (HP=30, Armor=1, Tier=4) | Drek'Thar (HP=30, Armor=12, Tier=4) | Sindragosa (HP=29, Armor=0, Tier=4) | Professor Putricide (HP=26, Armor=0, Tier=4) | Murloc Holmes (HP=24, Armor=0, Tier=4) | Ambassador Faelin (HP=21, Armor=0, Tier=4)

### Turn 8

**Murozond, Unbounded**  HP=30 Armor=8 Gold=10 Tier=4

  Board: 4/2, 4/4, 7/7, 4/3, 4/3, 3/4, 3/4
  Tavern: Wrath Weaver 1/3 T1 $3 | False Implicator 1/1 T3 $3 | Soul Rewinder 4/1 T2 $3 | Abyssal Bruiser 1/1 T4 $3 | Rimescale Priestess 3/3 T4 $3 | Temperature Shift (spell) T4 $4

  → Board after: 5/5, 10/10, 4/3, 9/5, 3/4, 4/7, 1/1 [DS]
  → Gold: 10→0

**Forest Lord Cenarius**  HP=30 Armor=12 Gold=10 Tier=4

  Board: 5/5, 6/6 [DS,WF], 8/6 [G], 2/2, 3/4, 4/2, 3/4
  Tavern: Friendly Geist 6/3 T4 $3 | Auto Assembler 2/2 T4 $3 | Friendly Geist 6/3 T4 $3 | Dustbone Devastator 2/6 T3 $3 | Fire Baller 7/6 T2 $3 | Conflagration (spell) T4 $2

  → Board after: 7/11, 14/11 [DS,WF], 15/12 [G], 13/9, 6/3, 6/3, 2/2
  → Gold: 10→0

**Murloc Holmes**  HP=24 Armor=0 Gold=10 Tier=4

  Board: 4/4, 7/6, 3/4, 2/5, 3/3, 4/2, 3/3
  Tavern: Marquee Ticker 3/7 T4 $3 | Tide Raiser 2/1 T2 $3 | Lava Lurker 2/5 T2 $3 | Waveling 8/3 T3 $3 | Reef Riffer 3/2 T2 $3 | Misplaced Tea Set (spell) T4 $2

  → Board after: 7/11, 9/7, 5/9, 10/8, 11/5, 3/7, 2/1 [Taunt]
  → Gold: 10→0

**Sindragosa**  HP=29 Armor=0 Gold=10 Tier=4

  Board: 4/2, 4/2, 8/7, 4/4, 2/4, 3/1 [Taunt,Reborn], 6/2
  Tavern: Auto Assembler 2/2 T4 $3 | Flaming Enforcer 4/5 T4 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Technical Element 5/6 T3 $3 | Tide Raiser 2/1 T2 $3 | Easterly Winds (spell) T4 $1

  → Board after: 10/8, 8/9, 11/8, 5/6, 11/11, 5/4, 2/1 [Taunt]
  → Gold: 10→0

**Ambassador Faelin**  HP=21 Armor=0 Gold=10 Tier=4

  Board: 13/14, 1/4, 4/3, 4/3, 4/3, 3/3, 9/10 [DS]
  Tavern: Waverider 2/8 T4 $3 | Deflect-o-Bot 3/2 T3 $3 | En-Djinn Blazer 10/10 T4 $3 | Tide Raiser 2/1 T2 $3 | Alert Alarmist 2/2 T2 $3 | Arcane Absorption (spell) T4 $1

  → Board after: 25/25, 6/11, 4/3, 9/10 [DS], 10/10 [DS], 7/12, 2/1 [Taunt]
  → Gold: 10→0

**Sire Denathrius**  HP=30 Armor=1 Gold=10 Tier=4

  Board: 8/4, 5/6 [Taunt,DS], 3/4, 8/2, 4/6, 4/4, 4/2
  Tavern: Deflect-o-Bot 3/2 T3 $3 | Waveling 6/1 T3 $3 | Floating Watcher 4/4 T3 $5 | Laboratory Assistant 3/4 T2 $3 | Eternal Knight 8/2 T2 $3 | Boon of Beetles (spell) T4 $1

  → Board after: 8/4, 9/10 [Taunt,DS], 8/8, 4/6, 8/6, 10/5, 3/4
  → Gold: 10→0

**Professor Putricide**  HP=26 Armor=0 Gold=10 Tier=4

  Board: 3/2, 8/11, 5/5, 14/9, 7/2, 4/3, 3/4
  Tavern: Accord-o-Tron 3/3 T3 $3 | Floating Watcher 4/4 T3 $5 | Wildfire Elemental 7/4 T3 $3 | Lava Lurker 5/6 T2 $3 | Alert Alarmist 2/2 T2 $3 | Spitescale Special (spell) T4 $2

  → Board after: 10/13, 14/9, 19/12, 7/4, 9/10, 9/9, 3/3
  → Gold: 10→0 | HP: 26→25

**Drek'Thar**  HP=30 Armor=12 Gold=10 Tier=4

  Board: 28/26, 17/13, 6/6, 3/4, 8/5, 5/5, 25/24
  Tavern: Wrath Weaver 23/25 T1 $3 | Enchanted Sentinel 11/13 T4 $3 | Tavern Tempest 18/18 T4 $3 | Deep-Sea Angler 17/18 T3 $3 | Surf n' Surf 23/23 T1 $3 | Back to Back (spell) T4 $1

  → Board after: 51/51, 51/49, 25/24, 23/25, 58/59, 18/18, 11/13
  → Gold: 10→0

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Murozond, Unbounded (HP=30, Armor=8, Tier=4) | Forest Lord Cenarius (HP=30, Armor=12, Tier=4) | Sire Denathrius (HP=30, Armor=1, Tier=4) | Drek'Thar (HP=30, Armor=12, Tier=4) | Sindragosa (HP=29, Armor=0, Tier=4) | Murloc Holmes (HP=24, Armor=0, Tier=4) | Ambassador Faelin (HP=21, Armor=0, Tier=4) | Professor Putricide (HP=10, Armor=0, Tier=4)

### Turn 9

**Murozond, Unbounded**  HP=30 Armor=8 Gold=10 Tier=4

  Board: 5/5, 10/10, 4/3, 9/5, 3/4, 4/7, 1/1 [DS]
  Tavern: Rimescale Priestess 3/3 T4 $3 | Ancestral Automaton 3/4 T2 $3 | Leyline Surfacer 4/6 T4 $3 | Felemental 3/3 T3 $3 | Refreshing Anomaly 4/5 T4 $3 | Deepwater Clan (spell) T4 $2

  → Board after: 5/5, 10/10, 4/3, 9/5, 7/10, 4/7, 4/6
  → Gold: 10→0 | Tier: 4→5

**Forest Lord Cenarius**  HP=30 Armor=12 Gold=10 Tier=4

  Board: 7/11, 14/11 [DS,WF], 15/12 [G], 13/9, 6/3, 6/3, 2/2
  Tavern: Rimescale Priestess 3/3 T4 $3 | Imposing Percussionist 4/4 T4 $3 | En-Djinn Blazer 7/7 T4 $3 | Zesty Shaker 6/7 T4 $3 | Malchezaar, Prince of Dance 5/4 T4 $3

  → Board after: 7/11, 21/18 [DS,WF], 15/12 [G], 13/9, 6/3, 6/3, 7/7
  → Gold: 10→0 | Tier: 4→5

**Murloc Holmes**  HP=24 Armor=0 Gold=10 Tier=4

  Board: 7/11, 9/7, 5/9, 10/8, 11/5, 3/7, 2/1 [Taunt]
  Tavern: Leeching Felhound 3/3 T3 $3 | Shell Collector 4/3 T2 $3 | Scarlet Skull 2/1 T2 $3 | Accord-o-Tron 6/4 T3 $3 | Cadaver Caretaker 3/3 T3 $3

  → Gold: 10→0 | Tier: 4→5

**Sindragosa**  HP=29 Armor=0 Gold=10 Tier=4

  Board: 10/8, 8/9, 11/8, 5/6, 11/11, 5/4, 2/1 [Taunt]
  Tavern: Sellemental 3/3 T2 $3 | Technical Element 5/6 T3 $3 | En-Djinn Blazer 4/4 T4 $3 | Deep Blue Crooner 2/2 T3 $3 | Holo Rover 4/4 T4 $3

  → Board after: 10/8, 23/15, 21/8, 5/6, 11/11, 5/4, 5/6
  → Gold: 10→0 | Tier: 4→5

**Ambassador Faelin**  HP=21 Armor=0 Gold=10 Tier=4

  Board: 25/25, 6/11, 4/3, 9/10 [DS], 10/10 [DS], 7/12, 2/1 [Taunt]
  Tavern: Nerubian Deathswarmer 1/4 T2 $3 | False Implicator 4/4 T3 $3 | Windfall Tornado 4/4 T1 $3 | Windfall Tornado 10/10 T1 $3 | Scarlet Skull 2/1 T2 $3

  → Gold: 10→0 | Tier: 4→5

**Sire Denathrius**  HP=30 Armor=1 Gold=10 Tier=4

  Board: 8/4, 9/10 [Taunt,DS], 9/8, 5/6, 9/6, 10/5, 3/4
  Tavern: Friendly Geist 9/3 T4 $3 | Tavern Tempest 2/2 T4 $3 | Laboratory Assistant 3/4 T2 $3 | Deep Blue Crooner 2/2 T3 $3 | Nerubian Deathswarmer 4/4 T2 $3

  → Board after: 8/4, 28/13 [Taunt,DS], 9/8, 15/6, 9/6, 10/5, 19/3
  → Gold: 10→0 | Tier: 4→5

**Professor Putricide**  HP=10 Armor=0 Gold=11 Tier=4

  Board: 10/13, 14/9, 19/12, 7/4, 9/10, 9/9, 3/3
  Tavern: Picky Eater 1/1 T1 $3 | Refreshing Anomaly 5/6 T4 $3 | Soul Rewinder 4/1 T2 $3 | Holo Rover 7/5 T4 $3 | Wildfire Elemental 10/5 T3 $3

  → Board after: 20/18, 14/9, 19/12, 9/10, 9/9, 17/10, 7/5 [DS]
  → Gold: 11→0 | Tier: 4→5

**Drek'Thar**  HP=30 Armor=12 Gold=10 Tier=4

  Board: 51/51, 51/49, 25/24, 23/25, 58/59, 18/18, 11/13
  Tavern: Metallic Hunter 19/17 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Rimescale Priestess 11/11 T4 $3 | Tavern Tempest 20/20 T4 $3 | Soul Rewinder 19/16 T2 $3

  → Board after: 51/51, 71/69, 25/24, 23/25, 58/59, 18/18, 20/20
  → Gold: 10→0 | Tier: 4→5

**⚔ Combat Phase**

  Alive: 8/8
  HP standings: Forest Lord Cenarius (HP=30, Armor=12, Tier=5) | Sire Denathrius (HP=30, Armor=1, Tier=5) | Drek'Thar (HP=30, Armor=12, Tier=5) | Murozond, Unbounded (HP=24, Armor=0, Tier=5) | Ambassador Faelin (HP=21, Armor=0, Tier=5) | Sindragosa (HP=14, Armor=0, Tier=5) | Professor Putricide (HP=10, Armor=0, Tier=5) | Murloc Holmes (HP=9, Armor=0, Tier=5)

### Turn 10

**Murozond, Unbounded**  HP=24 Armor=0 Gold=10 Tier=5

  Board: 5/5, 10/10, 4/3, 9/5, 7/10, 4/7, 4/6
  Tavern: Skeletal Strafer 6/6 T5 $3 | Famished Felbat 6/3 T5 $3 | Skeletal Strafer 6/6 T5 $3 | Sinrunner Blanchy 8/8 T5 $3 | Harmless Bonehead 1/1 T1 $3 | Bargain Bundle (spell) T5 $5

  → Board after: 10/10, 21/14, 15/18, 14/14 [Reborn], 6/6, 7/7, 1/1
  → Gold: 10→0

**Forest Lord Cenarius**  HP=30 Armor=12 Gold=10 Tier=5

  Board: 7/11, 21/18 [DS,WF], 15/12 [G], 13/9, 6/3, 6/3, 7/7
  Tavern: Annoy-o-Tron 4/5 T1 $3 | Floating Watcher 4/4 T3 $5 | Bazaar Dealer 4/6 T5 $3 | Divine Sparkbot 4/2 T5 $3 | Reef Riffer 3/2 T2 $3 | Golden Touch (spell) T5 $5

  → Board after: 11/15, 21/18 [DS,WF], 15/12 [G], 13/9, 10/9, 15/14, 4/2 [Taunt,DS]
  → Gold: 10→0

**Murloc Holmes**  HP=9 Armor=0 Gold=10 Tier=5

  Board: 7/11, 9/7, 5/9, 10/8, 11/5, 3/7, 2/1 [Taunt]
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Leyline Surfacer 8/10 T4 $3 | Plaguerunner 10/4 T4 $3 | Picky Eater 1/1 T1 $3 | Deep-Sea Angler 2/3 T3 $3 | Hired Headhunter (spell) T5 $3

  → Board after: 17/24, 19/11, 12/11, 11/5, 8/10, 10/4, 1/1
  → Gold: 10→0

**Sindragosa**  HP=14 Armor=0 Gold=10 Tier=5

  Board: 10/8, 23/15, 21/8, 5/6, 20/23, 5/4, 5/6
  Tavern: Divine Sparkbot 4/2 T5 $3 | Auto Assembler 2/2 T4 $3 | Waveling 6/1 T3 $3 | Marquee Ticker 3/7 T4 $3 | False Implicator 1/1 T3 $3 | Brood of Nozdormu (spell) T5 $2

  → Board after: 14/10, 31/18, 22/9, 8/13, 20/23, 5/6, 1/1
  → Gold: 10→0

**Ambassador Faelin**  HP=21 Armor=0 Gold=10 Tier=5

  Board: 25/25, 6/11, 4/3, 9/10 [DS], 10/10 [DS], 7/12, 2/1 [Taunt]
  Tavern: False Implicator 7/7 T3 $3 | Air Revenant 3/6 T5 $3 | Dustbone Devastator 2/6 T3 $3 | Holo Rover 7/7 T4 $3 | Darkcrest Strategist 4/5 T5 $3 | Butchering (spell) T5 $2

  → Board after: 25/25, 10/16, 18/23 [DS], 10/10 [DS], 17/25, 7/7 [DS], 2/6
  → Gold: 10→0

**Sire Denathrius**  HP=30 Armor=1 Gold=10 Tier=5

  Board: 8/4, 28/13 [Taunt,DS], 10/8, 16/6, 10/6, 10/5, 20/3
  Tavern: Nerubian Deathswarmer 15/4 T2 $3 | Soul Rewinder 4/1 T2 $3 | Deep Blue Crooner 2/2 T3 $3 | Old Soul 17/4 T2 $3 | Friendly Geist 20/3 T4 $3 | Corrupted Cupcakes (spell) T5 $4

  → Board after: 45/17 [Taunt,DS], 10/15, 21/7, 23/5, 21/3, 18/4, 2/2
  → Gold: 10→0

**Professor Putricide**  HP=10 Armor=0 Gold=10 Tier=5

  Board: 20/18, 14/9, 19/12, 9/10, 9/9, 17/10, 7/5 [DS]
  Tavern: Technical Element 5/6 T3 $3 | Deflect-o-Bot 6/3 T3 $3 | Shell Collector 4/3 T2 $3 | Sellemental 7/5 T2 $3 | Tranquil Meditative 6/9 T5 $3 | Armor Stash (spell) T5 $3

  → Board after: 31/33, 18/12, 19/12, 9/10, 22/17, 17/10, 4/3
  → Gold: 10→0

**Drek'Thar**  HP=30 Armor=12 Gold=10 Tier=5

  Board: 51/51, 71/69, 25/24, 23/25, 58/59, 18/18, 20/20
  Tavern: Rot Hide Gnoll 23/26 T1 $3 | Rimescale Priestess 11/11 T4 $3 | Marquee Ticker 11/15 T4 $3 | Leeching Felhound 18/18 T3 $3 | Seafloor Recruiter 11/13 T4 $3 | Portal in a Crystal (spell) T5 $2

  → Board after: 74/77, 112/110, 25/24, 25/27, 69/74, 52/57, 30/30
  → Gold: 10→0 | Armor: 12→8

**⚔ Combat Phase**

  💀 **Murloc Holmes eliminated!** (HP=0, Turn 10)
  💀 **Sindragosa eliminated!** (HP=0, Turn 10)
  💀 **Professor Putricide eliminated!** (HP=0, Turn 10)
  Alive: 5/8
  HP standings: Forest Lord Cenarius (HP=30, Armor=2, Tier=5) | Sire Denathrius (HP=30, Armor=1, Tier=5) | Drek'Thar (HP=30, Armor=8, Tier=5) | Murozond, Unbounded (HP=24, Armor=0, Tier=5) | Ambassador Faelin (HP=21, Armor=0, Tier=5)

### Turn 11

**Murozond, Unbounded**  HP=24 Armor=0 Gold=10 Tier=5

  Board: 12/12, 23/16, 17/20, 16/16 [Reborn], 8/8, 9/9, 3/3
  Tavern: Leeching Felhound 3/3 T3 $3 | Tichondrius 3/6 T5 $3 | Auto Assembler 2/2 T4 $3 | Holo Rover 4/4 T4 $3 | Nerubian Deathswarmer 1/4 T2 $3 | Wave of Gold (spell) T5 $2

  → Board after: 12/12, 26/22, 17/20, 16/16 [Reborn], 8/8, 9/9, 3/6
  → Gold: 10→0 | Tier: 5→6

**Forest Lord Cenarius**  HP=30 Armor=2 Gold=10 Tier=5

  Board: 11/15, 21/18 [DS,WF], 15/12 [G], 13/9, 10/9, 15/14, 4/2 [Taunt,DS]
  Tavern: Deep-Sea Angler 2/3 T3 $3 | Imposing Percussionist 7/7 T4 $3 | Imposing Percussionist 4/4 T4 $3 | Eternal Tycoon 4/8 T5 $3 | Ominous Seer 4/2 T1 $3 | Sanctify (spell) T5 $1

  → Board after: 11/15, 28/25 [DS,WF], 15/12 [G], 13/9, 10/9, 15/14, 7/7
  → Gold: 10→0 | Tier: 5→6 | HP: 30→28 | Armor: 2→0

**Ambassador Faelin**  HP=21 Armor=0 Gold=10 Tier=5

  Board: 25/25, 10/16, 18/23 [DS], 10/10 [DS], 17/25, 7/7 [DS], 2/6
  Tavern: Ominous Seer 10/8 T1 $3 | Charging Czarina 4/1 T5 $3 | Nightmare Par-tea Guest 6/6 T5 $3 | Holo Rover 4/4 T4 $3 | Dustbone Devastator 2/6 T3 $3 | Unmasked Identity (spell) T5 $3

  → Board after: 25/25, 10/16, 18/23 [DS], 20/18 [DS], 17/25, 7/7 [DS], 10/8 [DS]
  → Gold: 10→0 | Tier: 5→6

**Sire Denathrius**  HP=30 Armor=1 Gold=10 Tier=5

  Board: 45/17 [Taunt,DS], 10/15, 22/7, 24/5, 22/3, 19/4, 2/2
  Tavern: Drustfallen Butcher 18/7 T5 $3 | Annoy-o-Module 2/4 T4 $3 | Mummifier 21/2 T3 $3 | Alert Alarmist 2/2 T2 $3 | Wrath Weaver 1/3 T1 $3

  → Board after: 63/24 [Taunt,DS], 10/15, 22/7, 24/5, 22/3, 19/4, 18/7
  → Gold: 10→0 | Tier: 5→6

**Drek'Thar**  HP=30 Armor=8 Gold=10 Tier=5

  Board: 74/77, 112/110, 25/24, 25/27, 69/74, 52/57, 30/30
  Tavern: Soul Rewinder 19/16 T2 $3 | Sinrunner Blanchy 16/16 T5 $3 | Alert Alarmist 17/17 T2 $3 | Felemental 32/32 T3 $3 | Deep Blue Crooner 17/17 T3 $3

  → Board after: 74/77, 112/110, 25/27, 69/74, 84/89, 30/30, 32/32
  → Gold: 10→0 | Tier: 5→6

**⚔ Combat Phase**

  Alive: 5/8
  HP standings: Drek'Thar (HP=30, Armor=8, Tier=6) | Murozond, Unbounded (HP=24, Armor=0, Tier=6) | Ambassador Faelin (HP=21, Armor=0, Tier=6) | Sire Denathrius (HP=21, Armor=0, Tier=6) | Forest Lord Cenarius (HP=13, Armor=0, Tier=6)

### Turn 12

**Murozond, Unbounded**  HP=24 Armor=0 Gold=10 Tier=6

  Board: 14/14, 28/24, 19/22, 18/18 [Reborn], 10/10, 11/11, 5/8
  Tavern: Falling Sky Golem 5/2 T6 $3 | One-Amalgam Tour Group 6/7 T6 $3 | Malchezaar, Prince of Dance 5/4 T4 $3 | Cord Puller 1/1 T1 $3 | Waverider 2/8 T4 $3 | Woodland Defiler 5/6 T4 $3 | Perfect Vision (spell) T6 $2

  → Board after: 18/18, 37/31, 23/26, 24/25 [Reborn], 16/15, 20/27, 5/3 [DS]
  → Gold: 10→0

**Forest Lord Cenarius**  HP=13 Armor=0 Gold=10 Tier=6

  Board: 11/15, 28/25 [DS,WF], 15/12 [G], 13/9, 10/9, 15/14, 7/7
  Tavern: Moonsteel Juggernaut 8/8 T6 $3 | En-Djinn Blazer 7/7 T4 $3 | Maelstrom Emergent 2/7 T5 $3 | Shell Collector 4/3 T2 $3 | Nerubian Deathswarmer 4/7 T2 $3 | Maelstrom Emergent 2/7 T5 $3 | Knockoff Wisdomball (spell) T6 $4

  → Board after: 11/15, 28/25 [DS,WF], 24/26 [G], 23/24, 11/9, 19/21, 2/7
  → Gold: 10→0

**Ambassador Faelin**  HP=21 Armor=0 Gold=10 Tier=6

  Board: 25/25, 10/16, 18/23 [DS], 20/18 [DS], 17/25, 7/7 [DS], 10/8 [DS]
  Tavern: Falling Sky Golem 8/2 T6 $3 | Leeching Felhound 3/3 T3 $3 | En-Djinn Blazer 10/10 T4 $3 | Sellemental 3/3 T2 $3 | Snow Baller 6/7 T2 $3 | Tidemistress Athissa 6/6 T6 $3 | Eyes of the Earth Mother (spell) T6 $4

  → Board after: 31/31, 20/26, 21/26 [DS], 23/21 [DS], 31/38, 10/10 [DS], 3/3
  → Gold: 10→0 | HP: 21→18

**Sire Denathrius**  HP=21 Armor=0 Gold=10 Tier=6

  Board: 63/24 [Taunt,DS], 11/15, 23/7, 25/5, 23/3, 20/4, 19/7
  Tavern: Glowscale 4/6 T5 $3 | Handless Forsaken 19/1 T3 $3 | Flaming Enforcer 4/5 T4 $3 | Woodland Defiler 5/6 T4 $3 | Deathly Striker 25/8 T6 $3 | Wildfire Elemental 6/3 T3 $3 | Azerite Empowerment (spell) T6 $4

  → Board after: 63/24 [Taunt,DS], 11/23, 23/7, 44/6, 32/24, 25/8, 4/5
  → Gold: 10→0

**Drek'Thar**  HP=30 Armor=8 Gold=10 Tier=6

  Board: 74/77, 112/110, 25/27, 69/74, 84/89, 30/30, 32/32
  Tavern: Deathly Striker 10/10 T6 $3 | Zesty Shaker 15/16 T4 $3 | Dustbone Devastator 18/22 T3 $3 | Firelands Fugitive 30/32 T5 $3 | Catacomb Crasher 13/19 T5 $3 | Void Pup Trainer 16/16 T5 $3 | Lost Staff of Hamuul (spell) T6 $2

  → Board after: 74/77, 173/174, 82/93, 84/89, 50/54, 30/32, 15/16
  → Gold: 10→0

**⚔ Combat Phase**

  💀 **Forest Lord Cenarius eliminated!** (HP=0, Turn 12)
  Alive: 4/8
  HP standings: Drek'Thar (HP=30, Armor=8, Tier=6) | Murozond, Unbounded (HP=24, Armor=0, Tier=6) | Ambassador Faelin (HP=18, Armor=0, Tier=6) | Sire Denathrius (HP=1, Armor=0, Tier=6)

### Turn 13

**Murozond, Unbounded**  HP=24 Armor=0 Gold=10 Tier=6

  Board: 20/20, 39/33, 25/28, 26/27 [Reborn], 18/17, 22/29, 5/5 [DS]
  Tavern: Wildfire Elemental 6/3 T3 $3 | Ring Bearer 5/10 T6 $3 | Lava Lurker 2/5 T2 $3 | Handless Forsaken 2/1 T3 $3 | Cadaver Caretaker 3/3 T3 $3 | Air Revenant 3/6 T5 $3

  → Board after: 36/38, 46/43, 30/33, 31/35 [Reborn], 23/22, 24/31, 4/4
  → Gold: 10→0

**Ambassador Faelin**  HP=18 Armor=0 Gold=10 Tier=6

  Board: 31/31, 20/26, 21/26 [DS], 23/21 [DS], 31/38, 10/10 [DS], 3/3
  Tavern: Snow Baller 3/4 T2 $3 | Fire Baller 7/6 T2 $3 | Enchanted Sentinel 3/5 T4 $3 | Felemental 3/3 T3 $3 | Nightmare Par-tea Guest 6/6 T5 $3 | Friendly Geist 12/9 T4 $3

  → Board after: 32/31, 21/26, 34/35 [DS], 31/27 [DS], 32/38, 13/9 [DS], 3/3
  → Gold: 10→0

**Sire Denathrius**  HP=1 Armor=0 Gold=10 Tier=6

  Board: 63/24 [Taunt,DS], 12/23, 23/7, 44/6, 32/24, 25/8, 10/8
  Tavern: Technical Element 5/6 T3 $3 | Eternal Tycoon 21/8 T5 $3 | Auto Assembler 2/2 T4 $3 | Holo Rover 4/4 T4 $3 | Tide Raiser 2/1 T2 $3 | Fire Baller 4/3 T2 $3

  → Board after: 65/26 [Taunt,DS], 12/23, 23/7, 48/9, 58/38, 29/12, 2/2
  → Gold: 10→0

**Drek'Thar**  HP=30 Armor=8 Gold=10 Tier=6

  Board: 74/77, 173/174, 82/93, 84/89, 50/54, 30/32, 15/16
  Tavern: Nerubian Deathswarmer 19/22 T2 $3 | Flaming Enforcer 13/14 T4 $3 | Living Azerite 33/32 T5 $3 | Laboratory Assistant 21/22 T2 $3 | Deflect-o-Bot 21/20 T3 $3 | Catacomb Crasher 13/19 T5 $3

  → Board after: 74/77, 206/206, 82/93, 127/131, 69/76, 47/51, 14/19
  → Gold: 10→0

**⚔ Combat Phase**

  Alive: 4/8
  HP standings: Drek'Thar (HP=30, Armor=8, Tier=6) | Murozond, Unbounded (HP=24, Armor=0, Tier=6) | Ambassador Faelin (HP=18, Armor=0, Tier=6) | Sire Denathrius (HP=1, Armor=0, Tier=6)

### Turn 14

**Murozond, Unbounded**  HP=24 Armor=0 Gold=10 Tier=6

  Board: 38/40, 48/45, 32/35, 33/37 [Reborn], 25/24, 26/33, 6/6
  Tavern: Living Azerite 11/10 T5 $3 | Risen Rider 7/6 T1 $3 | Annoy-o-Tron 6/7 T1 $3 | Charging Czarina 9/6 T5 $3 | Deep Blue Crooner 7/7 T3 $3 | False Implicator 6/6 T3 $3

  → Board after: 47/50, 62/58, 42/44, 42/46 [Reborn], 27/26, 37/41, 7/8 [Taunt,DS]
  → Gold: 10→0

**Ambassador Faelin**  HP=18 Armor=0 Gold=10 Tier=6

  Board: 32/31, 21/26, 34/35 [DS], 31/27 [DS], 32/38, 13/9 [DS], 3/3
  Tavern: Marquee Ticker 3/7 T4 $3 | Deathly Striker 8/8 T6 $3 | Prosthetic Hand 6/4 T4 $3 | En-Djinn Blazer 4/4 T4 $3 | Ominous Seer 7/5 T1 $3 | Cadaver Caretaker 9/9 T3 $3

  → Board after: 32/31, 21/26, 34/35 [DS], 31/27 [DS], 32/38, 13/9 [DS]
  → Gold: 10→0

**Sire Denathrius**  HP=1 Armor=0 Gold=10 Tier=6

  Board: 65/26 [Taunt,DS], 13/23, 24/7, 49/9, 59/38, 30/12, 2/2
  Tavern: Catacomb Crasher 22/10 T5 $3 | Divine Sparkbot 4/2 T5 $3 | Eternal Tycoon 22/8 T5 $3 | Eternal Summoner 26/1 T6 $3 | Abyssal Bruiser 1/1 T4 $3 | Risen Rider 20/1 T1 $3

  → Board after: 69/28 [Taunt,DS], 13/23, 71/17, 107/49, 30/12, 42/11, 4/2 [Taunt,DS]
  → Gold: 10→0

**Drek'Thar**  HP=30 Armor=8 Gold=10 Tier=6

  Board: 74/77, 206/206, 82/93, 127/131, 69/76, 47/51, 14/19
  Tavern: Dustbone Devastator 21/24 T3 $3 | One-Amalgam Tour Group 29/29 T6 $3 | Old Soul 22/22 T2 $3 | Tranquil Meditative 12/17 T5 $3 | Air Revenant 32/35 T5 $3 | Deep-Sea Angler 20/21 T3 $3

  → Board after: 126/130, 230/233, 85/96, 130/134, 125/135, 47/51, 21/22
  → Gold: 10→0

**⚔ Combat Phase**

  Alive: 4/8
  HP standings: Drek'Thar (HP=30, Armor=8, Tier=6) | Ambassador Faelin (HP=18, Armor=0, Tier=6) | Murozond, Unbounded (HP=7, Armor=0, Tier=6) | Sire Denathrius (HP=1, Armor=0, Tier=6)

### Turn 15

**Murozond, Unbounded**  HP=7 Armor=0 Gold=10 Tier=6

  Board: 49/52, 64/60, 44/46, 44/48 [Reborn], 29/28, 39/43, 9/10 [Taunt,DS]
  Tavern: Malchezaar, Prince of Dance 15/14 T4 $3 | Seafloor Recruiter 13/15 T4 $3 | Woodland Defiler 15/16 T4 $3 | Ancestral Automaton 3/4 T2 $3 | Lava Lurker 12/15 T2 $3 | P-0UL-TR-0N 20/20 T6 $3

  → Board after: 54/57, 97/96, 69/71, 57/64 [Reborn], 45/43, 40/44, 13/16
  → Gold: 10→0

**Ambassador Faelin**  HP=18 Armor=0 Gold=10 Tier=6

  Board: 32/31, 21/26, 34/35 [DS], 31/27 [DS], 32/38, 13/9 [DS]
  Tavern: Lava Lurker 2/5 T2 $3 | Snow Baller 15/16 T2 $3 | Annoy-o-Module 2/4 T4 $3 | P-0UL-TR-0N 10/10 T6 $3 | Refreshing Anomaly 4/5 T4 $3 | Junk Jouster 8/7 T6 $3

  → Gold: 10→0

**Sire Denathrius**  HP=1 Armor=0 Gold=10 Tier=6

  Board: 69/28 [Taunt,DS], 13/23, 71/17, 107/49, 30/12, 42/11, 4/2 [Taunt,DS]
  Tavern: Nightmare Par-tea Guest 21/3 T5 $3 | Technical Element 5/6 T3 $3 | Handless Forsaken 20/1 T3 $3 | Shell Collector 4/3 T2 $3 | Wintergrasp Ghoul 23/3 T6 $3 | Shell Collector 4/3 T2 $3

  → Board after: 69/28 [Taunt,DS], 13/23, 71/17, 107/49, 30/12, 42/11, 20/7
  → Gold: 10→0

**Drek'Thar**  HP=30 Armor=8 Gold=10 Tier=6

  Board: 126/130, 230/233, 85/96, 130/134, 125/135, 47/51, 21/22
  Tavern: Rot Hide Gnoll 27/29 T1 $3 | Prosthetic Hand 12/10 T4 $3 | Risen Rider 28/26 T1 $3 | Drustfallen Butcher 12/16 T5 $3 | Shadowdancer 14/12 T5 $3 | Auto Assembler 11/11 T4 $3

  → Board after: 131/135, 247/254, 102/111, 149/151, 155/167, 77/79, 13/11 [Reborn]
  → Gold: 10→0

**⚔ Combat Phase**

  💀 **Ambassador Faelin eliminated!** (HP=0, Turn 15)
  💀 **Sire Denathrius eliminated!** (HP=0, Turn 15)
  Alive: 2/8
  HP standings: Drek'Thar (HP=30, Armor=8, Tier=6) | Murozond, Unbounded (HP=7, Armor=0, Tier=6)

---

## Final Standings

| # | Hero | HP | Armor | Alive | Eliminated Turn |
|---|---|---|---|---|
| 1 | Drek'Thar | 30 | 8 | Yes | — |
| 2 | Murozond, Unbounded | 7 | 0 | Yes | — |
| 3 | Ambassador Faelin | 0 | 0 | No | 15 |
| 4 | Sire Denathrius | 0 | 0 | No | 15 |
| 5 | Forest Lord Cenarius | 0 | 0 | No | 12 |
| 6 | Murloc Holmes | 0 | 0 | No | 10 |
| 7 | Sindragosa | 0 | 0 | No | 10 |
| 8 | Professor Putricide | 0 | 0 | No | 10 |

---

## Heuristic Strategy

The Q-score heuristic evaluates each affordable tavern minion by:

1. **Buy & Play**: Score = current_board_score + minion.atk + minion.health + aura_bonus
2. **Sell & Replace**: If board full, replace weakest minion if net score change > 0
3. **Upgrade**: If no beneficial buy is available and gold ≥ upgrade_cost, upgrade tavern tier
4. **Refresh**: If no other action is possible, refresh the tavern for 1 gold

This is a greedy one-step heuristic — no lookahead, no opponent modeling, no combat simulation.
Average rank in self-play: ~4.5 (random among identical strategies)