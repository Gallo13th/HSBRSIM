# 8-Player Battlegrounds — All Heuristic Demo

**Seed**: 123  |  **Max Turns**: 15  |  **Agents**: 8× Greedy Q-Score Heuristic

> ⚠ **Audit note**: This demo uses a simplified auto-play strategy that does NOT use
> hero powers, spells, freezes, or positioning. It is an engine smoke test, not a
> faithful recreation of real player behavior. Combat logs show actual engine combat.
> No anomaly is active in this game. Trinkets are offered on Turns 6 and 9.


## Players

| # | Hero | HP | Armor | Tier |
|---|---|---|---|---|
| 1 | Guff Runetotem | 30 | 18 | 1 |
| 2 | Cap'n Hoggarr | 30 | 10 | 1 |
| 3 | Cariel Roame | 30 | 12 | 1 |
| 4 | Malygos | 30 | 12 | 1 |
| 5 | Time Twister Chromie | 30 | 12 | 1 |
| 6 | Cookie the Cook | 30 | 12 | 1 |
| 7 | Jandice Barov | 30 | 12 | 1 |
| 8 | Y'Shaarj | 30 | 12 | 1 |

---

## Game Log

### Turn 1

**Guff Runetotem**  HP=30 Armor=18 Gold=3 Tier=1

  Board: (empty)
  Tavern: Ominous Seer 2/1 T1 $3 | Manasaber 4/1 T1 $3 | Picky Eater 1/1 T1 $3 | Enchanted Lasso (spell) T1 $2

  → Board after: 4/1
  → Bought | Gold: 3→0

**Cap'n Hoggarr**  HP=30 Armor=10 Gold=3 Tier=1

  Board: (empty)
  Tavern: Crackling Cyclone 2/1 T1 $3 | Dune Dweller 3/2 T1 $3 | Dune Dweller 3/2 T1 $3 | Glowing Crown (spell) T1 $3

  → Board after: 3/2
  → Bought | Gold: 3→0

**Cariel Roame**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Surf n' Surf 1/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Dune Dweller 3/2 T1 $3 | The Goldenizer (spell) T1 $0

  → Board after: 3/2
  → Bought | Gold: 3→0

**Malygos**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Dune Dweller 3/2 T1 $3 | Ominous Seer 2/1 T1 $3 | Surf n' Surf 1/1 T1 $3 | Tavern Coin (spell) T1 $3

  → Board after: 3/2
  → Bought | Gold: 3→0

**Time Twister Chromie**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Wrath Weaver 1/4 T1 $3 | Manasaber 4/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Angler's Lure (spell) T1 $3

  → Board after: 1/4
  → Bought | Gold: 3→0

**Cookie the Cook**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Picky Eater 1/1 T1 $3 | Dune Dweller 3/2 T1 $3 | Crackling Cyclone 2/1 T1 $3 | Rime or Reason (spell) T1 $3

  → Board after: 3/2
  → Bought | Gold: 3→0

**Jandice Barov**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Crackling Cyclone 2/1 T1 $3 | Picky Eater 1/1 T1 $3 | Picky Eater 1/1 T1 $3 | Tavern Dish Banana (spell) T1 $1

  → Board after: 2/1 [DS,WF]
  → Bought | Gold: 3→0

**Y'Shaarj**  HP=30 Armor=12 Gold=3 Tier=1

  Board: (empty)
  Tavern: Manasaber 4/1 T1 $3 | Manasaber 4/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Evolving Strategy (spell) T1 $3

  → Board after: 4/1
  → Bought | Gold: 3→0

**⚔ Combat Phase**

  ⚡ Cookie the Cook vs Guff Runetotem (first: Guff Runetotem)
     Cookie the Cook: [3/2]
     Guff Runetotem: [4/1]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Dune Dweller 3/2→3/0 💀
     🏁 survivors: 0 vs 0 — winner: draw
  ⚡ Cap'n Hoggarr vs Cariel Roame (first: Cariel Roame)
     Cap'n Hoggarr: [3/2]
     Cariel Roame: [3/2]
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Dune Dweller 3/2→3/0 💀
     🏁 survivors: 0 vs 0 — winner: draw
  ⚡ Jandice Barov vs Y'Shaarj (first: Y'Shaarj)
     Jandice Barov: [2/1]
     Y'Shaarj: [4/1]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Crackling Cyclone 2/1→2/1
     🏁 survivors: 1 vs 0 — winner: Jandice Barov
  ⚡ Malygos vs Time Twister Chromie (first: Time Twister Chromie)
     Malygos: [3/2]
     Time Twister Chromie: [1/4]
     ⚔ Wrath Weaver 1/4→1/1  🛡 Dune Dweller 3/2→3/1
     ⚔ Dune Dweller 3/1→3/0 💀  🛡 Wrath Weaver 1/1→1/0 💀
     🏁 survivors: 0 vs 0 — winner: draw

  Alive: 8/8
  HP standings: Guff Runetotem (HP=30, Armor=18, Tier=1) | Cap'n Hoggarr (HP=30, Armor=10, Tier=1) | Cariel Roame (HP=30, Armor=12, Tier=1) | Malygos (HP=30, Armor=12, Tier=1) | Time Twister Chromie (HP=30, Armor=12, Tier=1) | Cookie the Cook (HP=30, Armor=12, Tier=1) | Jandice Barov (HP=30, Armor=12, Tier=1) | Y'Shaarj (HP=30, Armor=10, Tier=1)

### Turn 2

**Guff Runetotem**  HP=30 Armor=18 Gold=4 Tier=1

  Board: 4/1
  Tavern: Ominous Seer 2/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Ominous Seer 2/1 T1 $3 | Fortify (spell) T1 $1

  → Board after: 4/1, 2/1
  → Bought | Gold: 4→0

**Cap'n Hoggarr**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 3/2
  Tavern: Dune Dweller 4/3 T1 $3 | Picky Eater 1/1 T1 $3 | Crackling Cyclone 3/2 T1 $3 | Banana (spell) T1 $0

  → Board after: 3/2, 4/3
  → Gold: 4→0

**Cariel Roame**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 3/2
  Tavern: Surf n' Surf 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Crackling Cyclone 3/2 T1 $3 | Sick Riffs (spell) T1 $3

  → Board after: 3/2, 1/4
  → Bought | Gold: 4→0

**Malygos**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 3/2
  Tavern: Ominous Seer 2/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Surf n' Surf 1/1 T1 $3 | Meditation (spell) T1 $3

  → Board after: 3/2, 2/1
  → Bought | Gold: 4→0

**Time Twister Chromie**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 1/4
  Tavern: Cord Puller 1/1 T1 $3 | Cord Puller 1/1 T1 $3 | Dune Dweller 3/2 T1 $3 | Them Apples (spell) T1 $1

  → Board after: 1/4, 3/2
  → Bought | Gold: 4→0

**Cookie the Cook**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 3/2
  Tavern: Picky Eater 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Ominous Seer 2/1 T1 $3 | Recruit a Trainee (spell) T1 $2

  → Board after: 3/2, 1/4
  → Bought | Gold: 4→0

**Jandice Barov**  HP=30 Armor=12 Gold=4 Tier=1

  Board: 2/1 [DS,WF]
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Crackling Cyclone 2/1 T1 $3 | Cord Puller 1/1 T1 $3 | Undersea Mount (spell) T1 $3

  → Board after: 2/1 [DS,WF], 1/2 [Taunt,DS]
  → Bought | Gold: 4→0

**Y'Shaarj**  HP=30 Armor=10 Gold=4 Tier=1

  Board: 4/1
  Tavern: Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Manasaber 4/1 T1 $3 | Cloning Conch (spell) T1 $0

  → Board after: 4/1, 4/1
  → Gold: 4→0

**⚔ Combat Phase**

  ⚡ Cap'n Hoggarr vs Y'Shaarj (first: Y'Shaarj)
     Cap'n Hoggarr: [3/2, 4/3]
     Y'Shaarj: [4/1, 4/1]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Dune Dweller 3/2→3/0 💀
     ⚔ Dune Dweller 4/3→4/0 💀  🛡 Manasaber 4/1→4/0 💀
     🏁 survivors: 0 vs 0 — winner: draw
  ⚡ Cariel Roame vs Guff Runetotem (first: Guff Runetotem)
     Cariel Roame: [3/2, 1/4]
     Guff Runetotem: [4/1, 2/1]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Dune Dweller 3/2→3/0 💀
     ⚔ Wrath Weaver 1/4→1/2  🛡 Ominous Seer 2/1→2/0 💀
     🏁 survivors: 1 vs 0 — winner: Cariel Roame
  ⚡ Jandice Barov vs Cookie the Cook (first: Jandice Barov)
     Jandice Barov: [2/1, 1/2]
     Cookie the Cook: [3/2, 1/4]
     ⚔ Crackling Cyclone 2/1→2/1  🛡 Wrath Weaver 1/4→1/2
     ⚔ Dune Dweller 3/2→3/1  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Crackling Cyclone 2/1→2/0 💀  🛡 Wrath Weaver 1/2→1/0 💀
     🏁 survivors: 1 vs 1 — winner: Jandice Barov
  ⚡ Malygos vs Time Twister Chromie (first: Time Twister Chromie)
     Malygos: [3/2, 2/1]
     Time Twister Chromie: [1/4, 3/2]
     ⚔ Wrath Weaver 1/4→1/2  🛡 Ominous Seer 2/1→2/0 💀
     ⚔ Dune Dweller 3/2→3/1  🛡 Wrath Weaver 1/2→1/0 💀
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Dune Dweller 3/1→3/0 💀
     🏁 survivors: 0 vs 0 — winner: draw

  Alive: 8/8
  HP standings: Guff Runetotem (HP=30, Armor=16, Tier=1) | Cap'n Hoggarr (HP=30, Armor=10, Tier=1) | Cariel Roame (HP=30, Armor=12, Tier=1) | Malygos (HP=30, Armor=12, Tier=1) | Time Twister Chromie (HP=30, Armor=12, Tier=1) | Cookie the Cook (HP=30, Armor=12, Tier=1) | Jandice Barov (HP=30, Armor=12, Tier=1) | Y'Shaarj (HP=30, Armor=10, Tier=1)

### Turn 3

**Guff Runetotem**  HP=30 Armor=16 Gold=5 Tier=1

  Board: 4/1, 2/1
  Tavern: Annoy-o-Tron 1/2 T1 $3 | Dune Dweller 3/2 T1 $3 | Picky Eater 1/1 T1 $3

  → Board after: 4/1, 2/1, 3/2
  → ⬆ Upgrade T1→T2 | Bought | Gold: 5→0

**Cap'n Hoggarr**  HP=30 Armor=10 Gold=5 Tier=1

  Board: 3/2, 4/3
  Tavern: Surf n' Surf 1/1 T1 $3 | Wrath Weaver 1/4 T1 $3 | Manasaber 4/1 T1 $3

  → Board after: 3/2, 4/3, 1/4
  → ⬆ Upgrade T1→T2 | Bought | Gold: 5→0

**Cariel Roame**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 3/2, 1/4
  Tavern: Surf n' Surf 1/1 T1 $3 | Annoy-o-Tron 1/2 T1 $3 | Cord Puller 1/1 T1 $3

  → Board after: 3/2, 1/4, 1/2 [Taunt,DS]
  → ⬆ Upgrade T1→T2 | Bought | Gold: 5→0

**Malygos**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 3/2, 2/1
  Tavern: Wrath Weaver 1/4 T1 $3 | Manasaber 4/1 T1 $3 | Wrath Weaver 1/4 T1 $3

  → Board after: 3/2, 2/1, 1/4
  → ⬆ Upgrade T1→T2 | Bought | Gold: 5→0

**Time Twister Chromie**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 1/4, 3/2
  Tavern: Crackling Cyclone 3/2 T1 $3 | Dune Dweller 4/3 T1 $3 | Picky Eater 1/1 T1 $3

  → Board after: 1/4, 3/2, 4/3
  → ⬆ Upgrade T1→T2 | Gold: 5→0

**Cookie the Cook**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 3/2, 1/4
  Tavern: Wrath Weaver 1/4 T1 $3 | Ominous Seer 2/1 T1 $3 | Cord Puller 1/1 T1 $3

  → Board after: 3/2, 3/6, 1/4
  → ⬆ Upgrade T1→T2 | Gold: 5→0 | Armor: 12→11

**Jandice Barov**  HP=30 Armor=12 Gold=5 Tier=1

  Board: 2/1 [DS,WF], 1/2 [Taunt,DS]
  Tavern: Dune Dweller 3/2 T1 $3 | Cord Puller 1/1 T1 $3 | Manasaber 4/1 T1 $3

  → Board after: 2/1 [DS,WF], 1/2 [Taunt,DS], 3/2
  → ⬆ Upgrade T1→T2 | Bought | Gold: 5→0

**Y'Shaarj**  HP=30 Armor=10 Gold=5 Tier=1

  Board: 4/1, 4/1
  Tavern: Wrath Weaver 1/4 T1 $3 | Crackling Cyclone 2/1 T1 $3 | Cord Puller 1/1 T1 $3

  → Board after: 4/1, 4/1, 1/4
  → ⬆ Upgrade T1→T2 | Bought | Gold: 5→0

**⚔ Combat Phase**

  ⚡ Cariel Roame vs Y'Shaarj (first: Cariel Roame)
     Cariel Roame: [3/2, 1/4, 1/2]
     Y'Shaarj: [4/1, 4/1, 1/4]
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Manasaber 4/1→4/0 💀
     ⚔ Manasaber 4/1→4/0 💀  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Wrath Weaver 1/4→1/3  🛡 Wrath Weaver 1/4→1/3
     ⚔ Wrath Weaver 1/3→1/2  🛡 Annoy-o-Tron 1/2→1/1
     ⚔ Annoy-o-Tron 1/1→1/0 💀  🛡 Wrath Weaver 1/2→1/1
     🏁 survivors: 1 vs 1 — winner: Cariel Roame
  ⚡ Jandice Barov vs Malygos (first: Malygos)
     Jandice Barov: [2/1, 1/2, 3/2]
     Malygos: [3/2, 2/1, 1/4]
     ⚔ Dune Dweller 3/2→3/1  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Crackling Cyclone 2/1→2/1  🛡 Dune Dweller 3/1→3/0 💀
     ⚔ Ominous Seer 2/1→2/0 💀  🛡 Annoy-o-Tron 1/2→1/0 💀
     ⚔ Crackling Cyclone 2/1→2/0 💀  🛡 Wrath Weaver 1/4→1/2
     ⚔ Wrath Weaver 1/2→1/0 💀  🛡 Dune Dweller 3/2→3/1
     🏁 survivors: 1 vs 0 — winner: Jandice Barov
  ⚡ Cap'n Hoggarr vs Guff Runetotem (first: Guff Runetotem)
     Cap'n Hoggarr: [3/2, 4/3, 1/4]
     Guff Runetotem: [4/1, 2/1, 3/2]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Wrath Weaver 1/4→1/0 💀
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Ominous Seer 2/1→2/0 💀
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Dune Dweller 4/3→4/0 💀
     🏁 survivors: 0 vs 0 — winner: draw
  ⚡ Time Twister Chromie vs Cookie the Cook (first: Time Twister Chromie)
     Time Twister Chromie: [1/4, 3/2, 4/3]
     Cookie the Cook: [3/2, 3/6, 1/4]
     ⚔ Wrath Weaver 1/4→1/3  🛡 Wrath Weaver 1/4→1/3
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Dune Dweller 3/2→3/0 💀
     ⚔ Dune Dweller 4/3→4/0 💀  🛡 Wrath Weaver 3/6→3/2
     ⚔ Wrath Weaver 3/2→3/1  🛡 Wrath Weaver 1/3→1/0 💀
     🏁 survivors: 0 vs 2 — winner: Cookie the Cook

  Alive: 8/8
  HP standings: Guff Runetotem (HP=30, Armor=16, Tier=2) | Cap'n Hoggarr (HP=30, Armor=10, Tier=2) | Cariel Roame (HP=30, Armor=12, Tier=2) | Malygos (HP=30, Armor=9, Tier=2) | Time Twister Chromie (HP=30, Armor=8, Tier=2) | Cookie the Cook (HP=30, Armor=11, Tier=2) | Jandice Barov (HP=30, Armor=12, Tier=2) | Y'Shaarj (HP=30, Armor=10, Tier=2)

### Turn 4

**Guff Runetotem**  HP=30 Armor=16 Gold=6 Tier=2

  Board: 4/1, 2/1, 3/2
  Tavern: Metallic Hunter 4/2 T2 $3 | Shell Collector 4/3 T2 $3 | Shell Collector 4/3 T2 $3 | Sellemental 4/4 T2 $3 | Strike Oil (spell) T2 $3

  → Board after: 4/1, 2/1, 3/2, 4/4, 4/3, 2/2
  → Bought | Gold: 6→0

**Cap'n Hoggarr**  HP=30 Armor=10 Gold=6 Tier=2

  Board: 3/2, 4/3, 1/4
  Tavern: Tide Raiser 2/1 T2 $3 | Soul Rewinder 4/1 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Manasaber 4/1 T1 $3 | Hasty Excavation (spell) T2 $3

  → Board after: 3/2, 4/3, 5/8, 3/4, 4/1
  → Bought | Gold: 6→0 | Armor: 10→8

**Cariel Roame**  HP=30 Armor=12 Gold=6 Tier=2

  Board: 3/2, 1/4, 1/2 [Taunt,DS]
  Tavern: Tide Raiser 2/1 T2 $3 | Alert Alarmist 2/2 T2 $3 | Alert Alarmist 2/2 T2 $3 | Fire Baller 5/4 T2 $3 | Search Through Time (spell) T2 $2

  → Board after: 3/2, 1/4, 1/2 [Taunt,DS], 5/4, 2/2 [Taunt]
  → Bought | Gold: 6→0

**Malygos**  HP=30 Armor=9 Gold=6 Tier=2

  Board: 3/2, 2/1, 1/4
  Tavern: Lava Lurker 2/5 T2 $3 | Soul Rewinder 4/1 T2 $3 | Sellemental 4/4 T2 $3 | Sewer Rat 3/2 T2 $3 | Leaf Through the Pages (spell) T2 $1

  → Board after: 3/2, 2/1, 1/4, 4/4, 2/5
  → Bought | Gold: 6→0

**Time Twister Chromie**  HP=30 Armor=8 Gold=6 Tier=2

  Board: 1/4, 3/2, 4/3
  Tavern: Sellemental 5/5 T2 $3 | Dune Dweller 5/4 T1 $3 | Snow Baller 5/6 T2 $3 | Metallic Hunter 4/2 T2 $3 | Chef's Choice (spell) T2 $2

  → Board after: 1/4, 3/2, 4/3, 5/6, 5/5
  → Bought | Gold: 6→0

**Cookie the Cook**  HP=30 Armor=11 Gold=6 Tier=2

  Board: 3/2, 3/6, 1/4
  Tavern: Sellemental 4/4 T2 $3 | Alert Alarmist 2/2 T2 $3 | Alert Alarmist 2/2 T2 $3 | Snow Baller 4/5 T2 $3 | Might of Stormwind (spell) T2 $2

  → Board after: 3/2, 3/6, 1/4, 4/5, 4/4
  → Bought | Gold: 6→0

**Jandice Barov**  HP=30 Armor=12 Gold=6 Tier=2

  Board: 2/1 [DS,WF], 1/2 [Taunt,DS], 3/2
  Tavern: Soul Rewinder 4/1 T2 $3 | Tide Raiser 2/1 T2 $3 | Snow Baller 4/5 T2 $3 | Dune Dweller 4/3 T1 $3

  → Board after: 2/1 [DS,WF], 1/2 [Taunt,DS], 3/2, 4/5, 4/3
  → Bought | Gold: 6→0

**Y'Shaarj**  HP=30 Armor=10 Gold=6 Tier=2

  Board: 4/1, 4/1, 1/4
  Tavern: Tide Raiser 2/1 T2 $3 | Surf n' Surf 1/1 T1 $3 | Soul Rewinder 4/1 T2 $3 | Sellemental 3/3 T2 $3

  → Board after: 4/1, 4/1, 3/6, 3/3, 4/1
  → Bought | Gold: 6→0 | Armor: 10→9

**⚔ Combat Phase**

  ⚡ Time Twister Chromie vs Y'Shaarj (first: Time Twister Chromie)
     Time Twister Chromie: [1/4, 3/2, 4/3, 5/6, 5/5]
     Y'Shaarj: [4/1, 4/1, 3/6, 3/3, 4/1]
     ⚔ Wrath Weaver 1/4→1/1  🛡 Sellemental 3/3→3/2
     ⚔ Manasaber 4/1→4/0 💀  🛡 Snow Baller 5/6→5/2
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Sellemental 3/2→3/0 💀
     ⚔ Manasaber 4/1→4/0 💀  🛡 Dune Dweller 4/3→4/0 💀
     ⚔ Snow Baller 5/2→5/0 💀  🛡 Soul Rewinder 4/1→4/0 💀
     ⚔ Wrath Weaver 3/6→3/1  🛡 Sellemental 5/5→5/2
     ⚔ Sellemental 5/2→5/0 💀  🛡 Wrath Weaver 3/1→3/0 💀
     🏁 survivors: 1 vs 0 — winner: Time Twister Chromie
  ⚡ Guff Runetotem vs Jandice Barov (first: Guff Runetotem)
     Guff Runetotem: [4/1, 2/1, 3/2, 4/4, 4/3, 2/2]
     Jandice Barov: [2/1, 1/2, 3/2, 4/5, 4/3]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Crackling Cyclone 2/1→2/1  🛡 Ominous Seer 2/1→2/0 💀
     ⚔ Dune Dweller 3/2→3/1  🛡 Annoy-o-Tron 1/2→1/0 💀
     ⚔ Crackling Cyclone 2/1→2/0 💀  🛡 Shell Collector 4/3→4/1
     ⚔ Sellemental 4/4→4/1  🛡 Dune Dweller 3/2→3/0 💀
     ⚔ Snow Baller 4/5→4/3  🛡 Mawsworn Soulkeeper 2/2→2/0 💀
     ⚔ Shell Collector 4/1→4/0 💀  🛡 Snow Baller 4/3→4/0 💀
     ⚔ Dune Dweller 4/3→4/0 💀  🛡 Sellemental 4/1→4/0 💀
     🏁 survivors: 1 vs 0 — winner: Guff Runetotem
  ⚡ Cariel Roame vs Malygos (first: Malygos)
     Cariel Roame: [3/2, 1/4, 1/2, 5/4, 2/2]
     Malygos: [3/2, 2/1, 1/4, 4/4, 2/5]
     ⚔ Dune Dweller 3/2→3/1  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Sellemental 4/4→4/1
     ⚔ Ominous Seer 2/1→2/0 💀  🛡 Alert Alarmist 2/2→2/0 💀
     ⚔ Wrath Weaver 1/4→1/3  🛡 Wrath Weaver 1/4→1/3
     ⚔ Wrath Weaver 1/3→1/2  🛡 Annoy-o-Tron 1/2→1/1
     ⚔ Annoy-o-Tron 1/1→1/0 💀  🛡 Sellemental 4/1→4/0 💀
     ⚔ Lava Lurker 2/5→2/0 💀  🛡 Fire Baller 5/4→5/2
     ⚔ Fire Baller 5/2→5/1  🛡 Wrath Weaver 1/2→1/0 💀
     🏁 survivors: 2 vs 1 — winner: Cariel Roame
  ⚡ Cap'n Hoggarr vs Cookie the Cook (first: Cap'n Hoggarr)
     Cap'n Hoggarr: [3/2, 4/3, 5/8, 3/4, 4/1]
     Cookie the Cook: [3/2, 3/6, 1/4, 4/5, 4/4]
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Snow Baller 4/5→4/2
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Laboratory Assistant 3/4→3/1
     ⚔ Dune Dweller 4/3→4/0 💀  🛡 Snow Baller 4/2→4/0 💀
     ⚔ Wrath Weaver 3/6→3/1  🛡 Wrath Weaver 5/8→5/5
     ⚔ Wrath Weaver 5/5→5/2  🛡 Wrath Weaver 3/1→3/0 💀
     ⚔ Wrath Weaver 1/4→1/0 💀  🛡 Wrath Weaver 5/2→5/1
     ⚔ Laboratory Assistant 3/1→3/0 💀  🛡 Sellemental 4/4→4/1
     ⚔ Sellemental 4/1→4/0 💀  🛡 Soul Rewinder 4/1→4/0 💀
     🏁 survivors: 1 vs 0 — winner: Cap'n Hoggarr

  Alive: 8/8
  HP standings: Guff Runetotem (HP=30, Armor=16, Tier=2) | Cap'n Hoggarr (HP=30, Armor=8, Tier=2) | Cariel Roame (HP=30, Armor=12, Tier=2) | Malygos (HP=30, Armor=9, Tier=2) | Time Twister Chromie (HP=30, Armor=8, Tier=2) | Cookie the Cook (HP=30, Armor=8, Tier=2) | Jandice Barov (HP=30, Armor=9, Tier=2) | Y'Shaarj (HP=30, Armor=6, Tier=2)

### Turn 5

**Guff Runetotem**  HP=30 Armor=16 Gold=7 Tier=2

  Board: 4/1, 2/1, 3/2, 4/4, 4/3, 2/2
  Tavern: Tide Raiser 2/1 T2 $3 | Fire Baller 5/4 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Wrath Weaver 1/4 T1 $3 | Tavern Coin (spell) T1 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**Cap'n Hoggarr**  HP=30 Armor=8 Gold=7 Tier=2

  Board: 3/2, 4/3, 5/8, 3/4, 4/1
  Tavern: Fire Baller 6/5 T2 $3 | Surf n' Surf 1/1 T1 $3 | Humming Bird 1/4 T2 $3 | Snow Baller 5/6 T2 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**Cariel Roame**  HP=30 Armor=12 Gold=7 Tier=2

  Board: 3/2, 1/4, 1/2 [Taunt,DS], 5/4, 2/2 [Taunt]
  Tavern: Soul Rewinder 4/1 T2 $3 | Reef Riffer 3/2 T2 $3 | Shell Collector 4/3 T2 $3 | Metallic Hunter 4/2 T2 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**Malygos**  HP=30 Armor=9 Gold=7 Tier=2

  Board: 3/2, 2/1, 1/4, 4/4, 2/5
  Tavern: Manasaber 4/1 T1 $3 | Humming Bird 1/4 T2 $3 | Fire Baller 5/4 T2 $3 | Metallic Hunter 4/2 T2 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**Time Twister Chromie**  HP=30 Armor=8 Gold=7 Tier=2

  Board: 1/4, 3/2, 4/3, 5/6, 5/5
  Tavern: Ancestral Automaton 3/4 T2 $3 | Lava Lurker 2/5 T2 $3 | Alert Alarmist 2/2 T2 $3 | Metallic Hunter 4/2 T2 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**Cookie the Cook**  HP=30 Armor=8 Gold=7 Tier=2

  Board: 3/2, 3/6, 1/4, 4/5, 4/4
  Tavern: Picky Eater 1/1 T1 $3 | Soul Rewinder 4/1 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Reef Riffer 3/2 T2 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**Jandice Barov**  HP=30 Armor=9 Gold=7 Tier=2

  Board: 2/1 [DS,WF], 1/2 [Taunt,DS], 3/2, 4/5, 4/3
  Tavern: Shell Collector 4/3 T2 $3 | Alert Alarmist 2/2 T2 $3 | Cord Puller 1/1 T1 $3 | Shell Collector 4/3 T2 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**Y'Shaarj**  HP=30 Armor=6 Gold=7 Tier=2

  Board: 4/1, 4/1, 3/6, 3/3, 4/1
  Tavern: Lava Lurker 2/5 T2 $3 | Sewer Rat 3/2 T2 $3 | Humming Bird 1/4 T2 $3 | Reef Riffer 3/2 T2 $3

  → ⬆ Upgrade T2→T3 | Gold: 7→0

**⚔ Combat Phase**

  ⚡ Cariel Roame vs Cookie the Cook (first: Cookie the Cook)
     Cariel Roame: [3/2, 1/4, 1/2, 5/4, 2/2]
     Cookie the Cook: [3/2, 3/6, 1/4, 4/5, 4/4]
     ⚔ Dune Dweller 3/2→3/1  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Snow Baller 4/5→4/2
     ⚔ Wrath Weaver 3/6→3/5  🛡 Annoy-o-Tron 1/2→1/0 💀
     ⚔ Wrath Weaver 1/4→1/1  🛡 Wrath Weaver 3/5→3/4
     ⚔ Wrath Weaver 1/4→1/2  🛡 Alert Alarmist 2/2→2/1
     ⚔ Fire Baller 5/4→5/0 💀  🛡 Snow Baller 4/2→4/0 💀
     ⚔ Sellemental 4/4→4/2  🛡 Alert Alarmist 2/1→2/0 💀
     🏁 survivors: 1 vs 4 — winner: Cariel Roame
  ⚡ Y'Shaarj vs Guff Runetotem (first: Guff Runetotem)
     Y'Shaarj: [4/1, 4/1, 3/6, 3/3, 4/1]
     Guff Runetotem: [4/1, 2/1, 3/2, 4/4, 4/3, 2/2]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Soul Rewinder 4/1→4/0 💀
     ⚔ Manasaber 4/1→4/0 💀  🛡 Mawsworn Soulkeeper 2/2→2/0 💀
     ⚔ Ominous Seer 2/1→2/0 💀  🛡 Manasaber 4/1→4/0 💀
     ⚔ Wrath Weaver 3/6→3/2  🛡 Sellemental 4/4→4/1
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Sellemental 3/3→3/0 💀
     🏁 survivors: 1 vs 2 — winner: Y'Shaarj
  ⚡ Malygos vs Cap'n Hoggarr (first: Cap'n Hoggarr)
     Malygos: [3/2, 2/1, 1/4, 4/4, 2/5]
     Cap'n Hoggarr: [3/2, 4/3, 5/8, 3/4, 4/1]
     ⚔ Dune Dweller 3/2→3/1  🛡 Wrath Weaver 1/4→1/1
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Dune Dweller 4/3→4/0 💀
     ⚔ Wrath Weaver 5/8→5/6  🛡 Lava Lurker 2/5→2/0 💀
     ⚔ Ominous Seer 2/1→2/0 💀  🛡 Dune Dweller 3/1→3/0 💀
     ⚔ Laboratory Assistant 3/4→3/3  🛡 Wrath Weaver 1/1→1/0 💀
     ⚔ Sellemental 4/4→4/0 💀  🛡 Soul Rewinder 4/1→4/0 💀
     🏁 survivors: 0 vs 2 — winner: Cap'n Hoggarr
  ⚡ Time Twister Chromie vs Jandice Barov (first: Time Twister Chromie)
     Time Twister Chromie: [1/4, 3/2, 4/3, 5/6, 5/5]
     Jandice Barov: [2/1, 1/2, 3/2, 4/5, 4/3]
     ⚔ Wrath Weaver 1/4→1/3  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Crackling Cyclone 2/1→2/1  🛡 Wrath Weaver 1/3→1/1
     ⚔ Dune Dweller 3/2→3/1  🛡 Annoy-o-Tron 1/2→1/0 💀
     ⚔ Crackling Cyclone 2/1→2/0 💀  🛡 Snow Baller 5/6→5/4
     ⚔ Dune Dweller 4/3→4/0 💀  🛡 Dune Dweller 3/2→3/0 💀
     ⚔ Snow Baller 4/5→4/0 💀  🛡 Sellemental 5/5→5/1
     ⚔ Snow Baller 5/4→5/0 💀  🛡 Dune Dweller 4/3→4/0 💀
     🏁 survivors: 3 vs 0 — winner: Time Twister Chromie

  Alive: 8/8
  HP standings: Guff Runetotem (HP=30, Armor=16, Tier=3) | Cap'n Hoggarr (HP=30, Armor=8, Tier=3) | Cariel Roame (HP=30, Armor=12, Tier=3) | Malygos (HP=30, Armor=3, Tier=3) | Time Twister Chromie (HP=30, Armor=8, Tier=3) | Cookie the Cook (HP=30, Armor=8, Tier=3) | Jandice Barov (HP=30, Armor=2, Tier=3) | Y'Shaarj (HP=30, Armor=6, Tier=3)

### Turn 6

**Guff Runetotem**  HP=30 Armor=16 Gold=8 Tier=3

  Board: 4/1, 2/1, 3/2, 4/4, 4/3, 2/2
  Tavern: Manasaber 4/1 T1 $3 | Ancestral Automaton 3/4 T2 $3 | False Implicator 1/1 T3 $3 | Sly Raptor 1/3 T3 $3

  → Board after: 4/1, 3/2, 4/4, 4/3, 3/4, 4/1, 1/3
  → Bought | Sold | 💍 Got trinket: Fountain Pen | Gold: 8→0

**Cap'n Hoggarr**  HP=30 Armor=8 Gold=8 Tier=3

  Board: 3/2, 4/3, 5/8, 3/4, 4/1
  Tavern: Deep-Sea Angler 2/3 T3 $3 | Tide Raiser 2/1 T2 $3 | Sewer Rat 3/2 T2 $3 | Sewer Rat 3/2 T2 $3

  → Board after: 3/2, 4/3, 5/8, 3/4, 4/1, 2/3, 3/2
  → Bought | 💍 Got trinket: Rewinder Portrait | Gold: 8→0

**Cariel Roame**  HP=30 Armor=12 Gold=8 Tier=3

  Board: 3/2, 1/4, 1/2 [Taunt,DS], 5/4, 2/2 [Taunt]
  Tavern: Annoy-o-Module 2/4 T3 $3 | Sewer Rat 3/2 T2 $3 | Lava Lurker 2/5 T2 $3 | Laboratory Assistant 3/4 T2 $3

  → Board after: 3/2, 3/6, 5/4, 2/2 [Taunt], 2/5, 3/4, 2/4 [Taunt,DS]
  → Bought | Sold | 💍 Got trinket: Fountain Pen | Gold: 8→0 | Armor: 12→11

**Malygos**  HP=30 Armor=3 Gold=8 Tier=3

  Board: 3/2, 2/1, 1/4, 4/4, 2/5
  Tavern: Sellemental 4/4 T2 $3 | Laboratory Assistant 3/4 T2 $3 | Reef Riffer 3/2 T2 $3 | Floating Watcher 4/4 T3 $5

  → Board after: 3/2, 2/1, 3/6, 4/4, 2/5, 4/4, 6/6
  → Bought | 💍 Got trinket: Fountain Pen | Gold: 8→0 | Armor: 3→2

**Time Twister Chromie**  HP=30 Armor=8 Gold=8 Tier=3

  Board: 1/4, 3/2, 4/3, 5/6, 5/5
  Tavern: Picky Eater 1/1 T1 $3 | Floating Watcher 4/4 T3 $5 | Ancestral Automaton 3/4 T2 $3 | Deep Blue Crooner 2/2 T3 $3

  → Board after: 3/6, 3/2, 4/3, 5/6, 5/5, 6/6, 3/4
  → Bought | 💍 Got trinket: Fountain Pen | Gold: 8→0 | Armor: 8→7

**Cookie the Cook**  HP=30 Armor=8 Gold=8 Tier=3

  Board: 3/2, 3/6, 1/4, 4/5, 4/4
  Tavern: Deflect-o-Bot 3/2 T3 $3 | Sly Raptor 1/3 T3 $3 | Sly Raptor 1/3 T3 $3 | Reef Riffer 3/2 T2 $3

  → Board after: 3/2, 3/6, 1/4, 4/5, 4/4, 3/2 [DS], 3/2
  → Bought | 💍 Got trinket: Lava Lamp | Gold: 8→0

**Jandice Barov**  HP=30 Armor=2 Gold=8 Tier=3

  Board: 2/1 [DS,WF], 1/2 [Taunt,DS], 3/2, 4/5, 4/3
  Tavern: Sprightly Scarab 3/1 T3 $3 | Annoy-o-Tron 1/2 T1 $3 | False Implicator 1/1 T3 $3 | Leeching Felhound 3/3 T3 $3

  → Board after: 3/2, 4/5, 4/3, 3/3, 5/1 [WF], 1/2 [Taunt,DS], 1/1
  → Bought | Sold | 💍 Got trinket: Lava Lamp | Gold: 8→0 | HP: 30→29 | Armor: 2→0

**Y'Shaarj**  HP=30 Armor=6 Gold=8 Tier=3

  Board: 4/1, 4/1, 3/6, 3/3, 4/1
  Tavern: Deep-Sea Angler 2/3 T3 $3 | Picky Eater 1/1 T1 $3 | Leeching Felhound 3/3 T3 $3 | Annoy-o-Module 2/4 T3 $3

  → Board after: 7/10, 3/3, 4/1, 3/3, 2/4 [Taunt,DS], 2/3, 1/1
  → Bought | Sold | 💍 Got trinket: Impulsive Portrait | Gold: 8→0 | Armor: 6→1

**⚔ Combat Phase**

  ⚡ Cookie the Cook vs Malygos (first: Cookie the Cook)
     Cookie the Cook: [3/2, 3/6, 1/4, 4/5, 4/4, 3/2, 3/2]
     Malygos: [3/2, 2/1, 3/6, 4/4, 2/5, 4/4, 6/6]
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Dune Dweller 3/2→3/0 💀
     ⚔ Ominous Seer 2/1→2/0 💀  🛡 Wrath Weaver 1/4→1/2
     ⚔ Wrath Weaver 3/6→3/0 💀  🛡 Floating Watcher 6/6→6/3
     ⚔ Wrath Weaver 3/6→3/5  🛡 Wrath Weaver 1/2→1/0 💀
     ⚔ Snow Baller 4/5→4/3  🛡 Lava Lurker 2/5→2/1
     ⚔ Sellemental 4/4→4/0 💀  🛡 Snow Baller 4/3→4/0 💀
     ⚔ Sellemental 4/4→4/1  🛡 Wrath Weaver 3/5→3/1
     ⚔ Lava Lurker 2/1→2/0 💀  🛡 Deflect-o-Bot 3/2→3/2
     ⚔ Deflect-o-Bot 3/2→3/0 💀  🛡 Wrath Weaver 3/1→3/0 💀
     ⚔ Sellemental 4/4→4/1  🛡 Reef Riffer 3/2→3/0 💀
     🏁 survivors: 1 vs 2 — winner: Cookie the Cook
  ⚡ Time Twister Chromie vs Cap'n Hoggarr (first: Cap'n Hoggarr)
     Time Twister Chromie: [3/6, 3/2, 4/3, 5/6, 5/5, 6/6, 3/4]
     Cap'n Hoggarr: [3/2, 4/3, 5/8, 3/4, 4/1, 2/3, 3/2]
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Dune Dweller 3/2→3/0 💀
     ⚔ Wrath Weaver 3/6→3/3  🛡 Laboratory Assistant 3/4→3/1
     ⚔ Dune Dweller 4/3→4/0 💀  🛡 Sellemental 5/5→5/1
     ⚔ Dune Dweller 4/3→4/0 💀  🛡 Wrath Weaver 5/8→5/4
     ⚔ Wrath Weaver 5/4→5/1  🛡 Ancestral Automaton 3/4→3/0 💀
     ⚔ Snow Baller 5/6→5/2  🛡 Soul Rewinder 4/1→4/0 💀
     ⚔ Laboratory Assistant 3/1→3/0 💀  🛡 Wrath Weaver 3/3→3/0 💀
     ⚔ Sellemental 5/1→5/0 💀  🛡 Sewer Rat 3/2→3/0 💀
     ⚔ Deep-Sea Angler 2/3→2/0 💀  🛡 Snow Baller 5/2→5/0 💀
     ⚔ Floating Watcher 6/6→6/1  🛡 Wrath Weaver 5/1→5/0 💀
     🏁 survivors: 1 vs 0 — winner: Time Twister Chromie
  ⚡ Y'Shaarj vs Cariel Roame (first: Cariel Roame)
     Y'Shaarj: [7/10, 3/3, 4/1, 3/3, 2/4, 2/3, 1/1]
     Cariel Roame: [3/2, 3/6, 5/4, 2/2, 2/5, 3/4, 2/4]
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Annoy-o-Module 2/4→2/4
     ⚔ Wrath Weaver 7/10→7/8  🛡 Annoy-o-Module 2/4→2/4
     ⚔ Wrath Weaver 3/6→3/4  🛡 Annoy-o-Module 2/4→2/1
     ⚔ Sellemental 3/3→3/1  🛡 Alert Alarmist 2/2→2/0 💀
     ⚔ Fire Baller 5/4→5/2  🛡 Annoy-o-Module 2/1→2/0 💀
     ⚔ Soul Rewinder 4/1→4/0 💀  🛡 Annoy-o-Module 2/4→2/0 💀
     ⚔ Lava Lurker 2/5→2/4  🛡 Picky Eater 1/1→1/0 💀
     ⚔ Leeching Felhound 3/3→3/0 💀  🛡 Wrath Weaver 3/4→3/1
     ⚔ Laboratory Assistant 3/4→3/1  🛡 Sellemental 3/1→3/0 💀
     ⚔ Deep-Sea Angler 2/3→2/0 💀  🛡 Laboratory Assistant 3/1→3/0 💀
     🏁 survivors: 1 vs 3 — winner: Y'Shaarj
  ⚡ Guff Runetotem vs Jandice Barov (first: Jandice Barov)
     Guff Runetotem: [4/1, 3/2, 4/4, 4/3, 3/4, 4/1, 1/3]
     Jandice Barov: [3/2, 4/5, 4/3, 3/3, 5/1, 1/2, 1/1]
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Manasaber 4/1→4/0 💀
     ⚔ Manasaber 4/1→4/0 💀  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Snow Baller 4/5→4/1  🛡 Sellemental 4/4→4/0 💀
     ⚔ Dune Dweller 3/2→3/1  🛡 Annoy-o-Tron 1/2→1/0 💀
     ⚔ Dune Dweller 4/3→4/0 💀  🛡 Dune Dweller 3/1→3/0 💀
     ⚔ Shell Collector 4/3→4/2  🛡 False Implicator 1/1→1/0 💀
     ⚔ Leeching Felhound 3/3→3/0 💀  🛡 Shell Collector 4/2→4/0 💀
     ⚔ Ancestral Automaton 3/4→3/0 💀  🛡 Snow Baller 4/1→4/0 💀
     ⚔ Sprightly Scarab 5/1→5/0 💀  🛡 Sly Raptor 1/3→1/0 💀
     🏁 survivors: 0 vs 0 — winner: draw

  Alive: 8/8
  HP standings: Guff Runetotem (HP=30, Armor=16, Tier=3) | Cap'n Hoggarr (HP=30, Armor=2, Tier=3) | Cariel Roame (HP=30, Armor=11, Tier=3) | Malygos (HP=30, Armor=2, Tier=3) | Time Twister Chromie (HP=30, Armor=7, Tier=3) | Cookie the Cook (HP=30, Armor=8, Tier=3) | Y'Shaarj (HP=30, Armor=1, Tier=3) | Jandice Barov (HP=29, Armor=0, Tier=3)

### Turn 7

**Guff Runetotem**  HP=30 Armor=16 Gold=9 Tier=3

  Board: 4/1, 3/2, 4/4, 4/3, 3/4, 4/1, 1/3
  Tavern: Sprightly Scarab 3/1 T3 $3 | Reef Riffer 3/2 T2 $3 | Shell Collector 4/3 T2 $3 | Fire Baller 5/4 T2 $3

  → Board after: 4/1, 3/2, 4/4, 4/3, 3/4, 4/1, 5/4
  → ⬆ Upgrade T3→T4 | Bought | Sold | Gold: 9→0

**Cap'n Hoggarr**  HP=30 Armor=2 Gold=9 Tier=3

  Board: 3/2, 4/3, 5/8, 3/4, 4/1, 2/3, 3/2
  Tavern: Deflect-o-Bot 3/2 T3 $3 | Sellemental 5/5 T2 $3 | Technical Element 5/6 T3 $3 | Fire Baller 6/5 T2 $3

  → Board after: 4/3, 5/8, 3/4, 6/3 [Taunt], 2/3, 3/2, 5/6
  → ⬆ Upgrade T3→T4 | Bought | Gold: 9→0

**Cariel Roame**  HP=30 Armor=11 Gold=9 Tier=3

  Board: 3/2, 3/6, 5/4, 2/2 [Taunt], 2/5, 3/4, 2/4 [Taunt,DS]
  Tavern: Deep Blue Crooner 2/2 T3 $3 | Deep-Sea Angler 2/3 T3 $3 | Sewer Rat 3/2 T2 $3 | Ominous Seer 2/1 T1 $3

  → Board after: 3/2, 3/6, 5/4, 2/5, 3/4, 2/4 [Taunt,DS], 2/3
  → ⬆ Upgrade T3→T4 | Bought | Sold | Gold: 9→0

**Malygos**  HP=30 Armor=2 Gold=9 Tier=3

  Board: 3/2, 2/1, 3/6, 4/4, 2/5, 4/4, 6/6
  Tavern: Sprightly Scarab 3/1 T3 $3 | Sellemental 4/4 T2 $3 | Crackling Cyclone 3/2 T1 $3 | Wildfire Elemental 7/4 T3 $3

  → Board after: 3/2, 3/6, 4/4, 2/5, 4/4, 6/6, 7/4
  → ⬆ Upgrade T3→T4 | Bought | Sold | Gold: 9→0

**Time Twister Chromie**  HP=30 Armor=7 Gold=9 Tier=3

  Board: 3/6, 3/2, 4/3, 5/6, 5/5, 6/6, 3/4
  Tavern: Metallic Hunter 4/2 T2 $3 | Felemental 5/5 T3 $3 | Felemental 5/5 T3 $3 | Sly Raptor 1/3 T3 $3

  → Board after: 3/6, 4/3, 5/6, 5/5, 6/6, 3/4, 5/5
  → ⬆ Upgrade T3→T4 | Bought | Gold: 9→0

**Cookie the Cook**  HP=30 Armor=8 Gold=9 Tier=3

  Board: 3/2, 3/6, 1/4, 4/5, 4/4, 3/2 [DS], 3/2
  Tavern: Ominous Seer 2/1 T1 $3 | Humming Bird 1/4 T2 $3 | Felemental 4/4 T3 $3 | Deep-Sea Angler 2/3 T3 $3

  → Board after: 3/6, 1/4, 8/9, 4/4, 3/2 [DS], 3/2, 4/4
  → ⬆ Upgrade T3→T4 | Bought | Sold | Gold: 9→0

**Jandice Barov**  HP=29 Armor=0 Gold=9 Tier=3

  Board: 3/2, 4/5, 4/3, 3/3, 5/1 [WF], 1/2 [Taunt,DS], 1/1
  Tavern: Laboratory Assistant 3/4 T2 $3 | Waveling 8/3 T3 $3 | Laboratory Assistant 3/4 T2 $3 | Deflect-o-Bot 3/2 T3 $3

  → Board after: 3/2, 4/5, 4/3, 3/3, 5/1 [WF], 1/2 [Taunt,DS], 8/3
  → ⬆ Upgrade T3→T4 | Bought | Sold | Gold: 9→0

**Y'Shaarj**  HP=30 Armor=1 Gold=9 Tier=3

  Board: 7/10, 3/3, 4/1, 3/3, 2/4 [Taunt,DS], 2/3, 1/1
  Tavern: Ominous Seer 2/1 T1 $3 | Waveling 6/1 T3 $3 | Sewer Rat 3/2 T2 $3 | Fire Baller 4/3 T2 $3

  → Board after: 7/10, 3/3, 6/3 [Taunt], 3/3, 2/4 [Taunt,DS], 2/3, 6/1
  → ⬆ Upgrade T3→T4 | Bought | Sold | Gold: 9→0

**⚔ Combat Phase**

  ⚡ Guff Runetotem vs Cap'n Hoggarr (first: Guff Runetotem)
     Guff Runetotem: [4/1, 3/2, 4/4, 4/3, 3/4, 4/1, 5/4]
     Cap'n Hoggarr: [4/3, 5/8, 3/4, 6/3, 2/3, 3/2, 5/6]
     ⚔ Manasaber 4/1→4/0 💀  🛡 Soul Rewinder 6/3→6/0 💀
     ⚔ Dune Dweller 4/3→4/0 💀  🛡 Dune Dweller 3/2→3/0 💀
     ⚔ Sellemental 4/4→4/2  🛡 Deep-Sea Angler 2/3→2/0 💀
     ⚔ Wrath Weaver 5/8→5/4  🛡 Sellemental 4/2→4/0 💀
     ⚔ Shell Collector 4/3→4/0 💀  🛡 Wrath Weaver 5/4→5/0 💀
     ⚔ Laboratory Assistant 3/4→3/0 💀  🛡 Manasaber 4/1→4/0 💀
     ⚔ Ancestral Automaton 3/4→3/0 💀  🛡 Technical Element 5/6→5/3
     ⚔ Sewer Rat 3/2→3/0 💀  🛡 Fire Baller 5/4→5/1
     ⚔ Fire Baller 5/1→5/0 💀  🛡 Technical Element 5/3→5/0 💀
     🏁 survivors: 0 vs 0 — winner: draw
  ⚡ Cookie the Cook vs Y'Shaarj (first: Cookie the Cook)
     Cookie the Cook: [3/6, 1/4, 8/9, 4/4, 3/2, 3/2, 4/4]
     Y'Shaarj: [7/10, 3/3, 6/3, 3/3, 2/4, 2/3, 6/1]
     ⚔ Wrath Weaver 3/6→3/0 💀  🛡 Soul Rewinder 6/3→6/0 💀
     ⚔ Wrath Weaver 7/10→7/2  🛡 Snow Baller 8/9→8/2
     ⚔ Wrath Weaver 1/4→1/2  🛡 Annoy-o-Module 2/4→2/4
     ⚔ Sellemental 3/3→3/0 💀  🛡 Snow Baller 8/2→8/0 💀
     ⚔ Sellemental 4/4→4/2  🛡 Annoy-o-Module 2/4→2/0 💀
     ⚔ Leeching Felhound 3/3→3/0 💀  🛡 Reef Riffer 3/2→3/0 💀
     ⚔ Deflect-o-Bot 3/2→3/2  🛡 Waveling 6/1→6/0 💀
     ⚔ Deep-Sea Angler 2/3→2/0 💀  🛡 Sellemental 4/2→4/0 💀
     ⚔ Felemental 4/4→4/0 💀  🛡 Wrath Weaver 7/2→7/0 💀
     🏁 survivors: 2 vs 0 — winner: Cookie the Cook
  ⚡ Cariel Roame vs Malygos (first: Malygos)
     Cariel Roame: [3/2, 3/6, 5/4, 2/5, 3/4, 2/4, 2/3]
     Malygos: [3/2, 3/6, 4/4, 2/5, 4/4, 6/6, 7/4]
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Annoy-o-Module 2/4→2/4
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Floating Watcher 6/6→6/3
     ⚔ Wrath Weaver 3/6→3/4  🛡 Annoy-o-Module 2/4→2/1
     ⚔ Wrath Weaver 3/6→3/0 💀  🛡 Wildfire Elemental 7/4→7/1
     ⚔ Sellemental 4/4→4/2  🛡 Annoy-o-Module 2/1→2/0 💀
     ⚔ Fire Baller 5/4→5/2  🛡 Lava Lurker 2/5→2/0 💀
     ⚔ Sellemental 4/4→4/2  🛡 Deep-Sea Angler 2/3→2/0 💀
     ⚔ Lava Lurker 2/5→2/1  🛡 Sellemental 4/2→4/0 💀
     ⚔ Floating Watcher 6/3→6/0 💀  🛡 Fire Baller 5/2→5/0 💀
     ⚔ Laboratory Assistant 3/4→3/1  🛡 Wrath Weaver 3/4→3/1
     ⚔ Wildfire Elemental 7/1→7/0 💀  🛡 Lava Lurker 2/1→2/0 💀
     🏁 survivors: 1 vs 2 — winner: Cariel Roame
  ⚡ Jandice Barov vs Time Twister Chromie (first: Jandice Barov)
     Jandice Barov: [3/2, 4/5, 4/3, 3/3, 5/1, 1/2, 8/3]
     Time Twister Chromie: [3/6, 4/3, 5/6, 5/5, 6/6, 3/4, 5/5]
     ⚔ Dune Dweller 3/2→3/0 💀  🛡 Snow Baller 5/6→5/3
     ⚔ Wrath Weaver 3/6→3/5  🛡 Annoy-o-Tron 1/2→1/2
     ⚔ Snow Baller 4/5→4/1  🛡 Dune Dweller 4/3→4/0 💀
     ⚔ Snow Baller 5/3→5/2  🛡 Annoy-o-Tron 1/2→1/0 💀
     ⚔ Dune Dweller 4/3→4/0 💀  🛡 Felemental 5/5→5/1
     ⚔ Sellemental 5/5→5/2  🛡 Leeching Felhound 3/3→3/0 💀
     ⚔ Sprightly Scarab 5/1→5/0 💀  🛡 Felemental 5/1→5/0 💀
     ⚔ Floating Watcher 6/6→6/0 💀  🛡 Waveling 8/3→8/0 💀
     🏁 survivors: 1 vs 4 — winner: Jandice Barov

  Alive: 8/8
  HP standings: Guff Runetotem (HP=30, Armor=16, Tier=4) | Cap'n Hoggarr (HP=30, Armor=2, Tier=4) | Cariel Roame (HP=30, Armor=11, Tier=4) | Malygos (HP=30, Armor=2, Tier=4) | Time Twister Chromie (HP=30, Armor=7, Tier=4) | Cookie the Cook (HP=30, Armor=8, Tier=4) | Jandice Barov (HP=29, Armor=0, Tier=4) | Y'Shaarj (HP=23, Armor=0, Tier=4)

### Turn 8

**Guff Runetotem**  HP=30 Armor=16 Gold=10 Tier=4

  Board: 4/1, 3/2, 4/4, 4/3, 3/4, 4/1, 5/4
  Tavern: Technical Element 5/6 T3 $3 | Zesty Shaker 6/7 T4 $3 | Technical Element 5/6 T3 $3 | Refreshing Anomaly 5/6 T4 $3 | Tavern Tempest 3/3 T4 $3 | Back to Back (spell) T4 $1

  → Board after: 4/4, 5/4, 6/7, 5/6, 5/6, 5/6, 3/3
  → Bought | Sold | Gold: 10→0

**Cap'n Hoggarr**  HP=30 Armor=2 Gold=10 Tier=4

  Board: 4/3, 5/8, 3/4, 6/3 [Taunt], 2/3, 3/2, 5/6
  Tavern: Surf n' Surf 1/1 T1 $3 | Sly Raptor 1/3 T3 $3 | Snow Baller 5/6 T2 $3 | Felemental 5/5 T3 $3 | Technical Element 5/6 T3 $3 | Temperature Shift (spell) T4 $4

  → Board after: 5/8, 8/5 [Taunt], 5/6, 5/6, 5/6, 5/5, 1/1
  → Bought | Sold | Gold: 10→0

**Cariel Roame**  HP=30 Armor=11 Gold=10 Tier=4

  Board: 3/2, 3/6, 5/4, 2/5, 3/4, 2/4 [Taunt,DS], 2/3
  Tavern: Marquee Ticker 3/7 T4 $3 | Deflect-o-Bot 3/2 T3 $3 | Sellemental 4/4 T2 $3 | Sewer Rat 3/2 T2 $3 | Deflect-o-Bot 3/2 T3 $3 | Defender's Rites (spell) T4 $2

  → Board after: 3/6, 5/4, 4/7 [Taunt], 3/4, 3/7, 4/4, 3/2 [DS]
  → Bought | Sold | Gold: 10→0

**Malygos**  HP=30 Armor=2 Gold=10 Tier=4

  Board: 3/2, 3/6, 4/4, 2/5, 4/4, 6/6, 7/4
  Tavern: Deep Blue Crooner 2/2 T3 $3 | Manasaber 4/1 T1 $3 | Ichoron the Protector 4/2 T4 $3 | Deflect-o-Bot 3/2 T3 $3 | Leyline Surfacer 5/7 T4 $3 | Gem Confiscation (spell) T4 $1

  → Board after: 3/6, 4/4, 4/4, 6/6, 7/4, 5/7, 2/2
  → Bought | Sold | Gold: 10→0

**Time Twister Chromie**  HP=30 Armor=7 Gold=10 Tier=4

  Board: 3/6, 4/3, 5/6, 5/5, 6/6, 3/4, 5/5
  Tavern: Stomping Stegodon 5/5 T4 $3 | Lava Lurker 3/6 T2 $3 | Sprightly Scarab 4/2 T3 $3 | Wildfire Elemental 9/6 T3 $3 | Waverider 3/9 T4 $3 | Angler's Lure (spell) T1 $3

  → Board after: 5/6, 6/6, 5/5, 9/6, 3/9, 5/5, 5/3 [Reborn]
  → Bought | Sold | Gold: 10→0

**Cookie the Cook**  HP=30 Armor=8 Gold=10 Tier=4

  Board: 3/6, 1/4, 8/9, 4/4, 3/2 [DS], 3/2, 4/4
  Tavern: Humming Bird 2/5 T2 $3 | Ominous Seer 3/2 T1 $3 | Flaming Enforcer 5/6 T4 $3 | Hardy Orca 2/7 T3 $3 | Waveling 8/3 T3 $3 | Deepwater Clan (spell) T4 $2

  → Board after: 5/8, 8/9, 4/4, 5/6, 12/7, 2/7 [Taunt], 3/2
  → Bought | Sold | Gold: 10→0 | Armor: 8→7

**Jandice Barov**  HP=29 Armor=0 Gold=10 Tier=4

  Board: 3/2, 4/5, 4/3, 3/3, 5/1 [WF], 1/2 [Taunt,DS], 8/3
  Tavern: Woodland Defiler 5/6 T4 $3 | Deep-Sea Angler 2/3 T3 $3 | Flaming Enforcer 4/5 T4 $3 | Banana Slamma 6/7 T4 $3 | Flaming Enforcer 4/5 T4 $3 | Easterly Winds (spell) T4 $1

  → Board after: 4/5, 8/3, 6/7, 5/6, 4/5, 4/5, 2/3
  → Bought | Sold | Gold: 10→0

**Y'Shaarj**  HP=23 Armor=0 Gold=10 Tier=4

  Board: 7/10, 3/3, 6/3 [Taunt], 3/3, 2/4 [Taunt,DS], 2/3, 6/1
  Tavern: En-Djinn Blazer 4/4 T4 $3 | Woodland Defiler 8/7 T4 $3 | Leyline Surfacer 4/6 T4 $3 | Holo Rover 4/4 T4 $3 | Flaming Enforcer 4/5 T4 $3 | Conflagration (spell) T4 $2

  → Board after: 13/16 [Taunt], 6/3 [Taunt], 8/7, 4/6, 4/5, 4/4, 4/4 [DS]
  → Bought | Sold | Gold: 10→0 | HP: 23→21

**⚔ Combat Phase**

  ⚡ Guff Runetotem vs Cookie the Cook (first: Guff Runetotem)
     Guff Runetotem: [4/4, 5/4, 6/7, 5/6, 5/6, 5/6, 3/3]
     Cookie the Cook: [5/8, 8/9, 4/4, 5/6, 12/7, 2/7, 3/2]
     ⚔ Sellemental 4/4→4/2  🛡 Hardy Orca 2/7→2/3
     ⚔ Wrath Weaver 5/8→5/4  🛡 Sellemental 4/2→4/0 💀
     ⚔ Fire Baller 5/4→5/2  🛡 Hardy Orca 2/3→2/0 💀
     ⚔ Snow Baller 8/9→8/4  🛡 Refreshing Anomaly 5/6→5/0 💀
     ⚔ Zesty Shaker 6/7→6/2  🛡 Flaming Enforcer 5/6→5/0 💀
     ⚔ Felemental 4/4→4/0 💀  🛡 Fire Baller 5/2→5/0 💀
     ⚔ Technical Element 5/6→5/0 💀  🛡 Snow Baller 8/4→8/0 💀
     ⚔ Waveling 12/7→12/2  🛡 Technical Element 5/6→5/0 💀
     ⚔ Tavern Tempest 3/3→3/0 💀  🛡 Wrath Weaver 5/4→5/1
     ⚔ Ominous Seer 3/2→3/0 💀  🛡 Zesty Shaker 6/2→6/0 💀
     🏁 survivors: 0 vs 2 — winner: Cookie the Cook
  ⚡ Time Twister Chromie vs Malygos (first: Malygos)
     Time Twister Chromie: [5/6, 6/6, 5/5, 9/6, 3/9, 5/5, 5/3]
     Malygos: [3/6, 4/4, 4/4, 6/6, 7/4, 5/7, 2/2]
     ⚔ Wrath Weaver 3/6→3/0 💀  🛡 Floating Watcher 6/6→6/3
     ⚔ Snow Baller 5/6→5/2  🛡 Sellemental 4/4→4/0 💀
     ⚔ Sellemental 4/4→4/0 💀  🛡 Snow Baller 5/2→5/0 💀
     ⚔ Floating Watcher 6/3→6/0 💀  🛡 Floating Watcher 6/6→6/0 💀
     ⚔ Wildfire Elemental 7/4→7/0 💀  🛡 Stomping Stegodon 5/5→5/0 💀
     ⚔ Felemental 5/5→5/3  🛡 Deep Blue Crooner 2/2→2/0 💀
     ⚔ Leyline Surfacer 5/7→5/2  🛡 Sprightly Scarab 5/3→5/0 💀
     ⚔ Wildfire Elemental 9/6→9/1  🛡 Leyline Surfacer 5/2→5/0 💀
     🏁 survivors: 3 vs 0 — winner: Time Twister Chromie
  ⚡ Jandice Barov vs Cap'n Hoggarr (first: Jandice Barov)
     Jandice Barov: [4/5, 8/3, 6/7, 5/6, 4/5, 4/5, 2/3]
     Cap'n Hoggarr: [5/8, 8/5, 5/6, 5/6, 5/6, 5/5, 1/1]
     ⚔ Snow Baller 4/5→4/0 💀  🛡 Soul Rewinder 8/5→8/1
     ⚔ Wrath Weaver 5/8→5/0 💀  🛡 Waveling 8/3→8/0 💀
     ⚔ Banana Slamma 6/7→6/0 💀  🛡 Soul Rewinder 8/1→8/0 💀
     ⚔ Technical Element 5/6→5/2  🛡 Flaming Enforcer 4/5→4/0 💀
     ⚔ Woodland Defiler 5/6→5/5  🛡 Surf n' Surf 1/1→1/0 💀
     ⚔ Snow Baller 5/6→5/2  🛡 Flaming Enforcer 4/5→4/0 💀
     ⚔ Deep-Sea Angler 2/3→2/0 💀  🛡 Felemental 5/5→5/3
     ⚔ Technical Element 5/6→5/1  🛡 Woodland Defiler 5/5→5/0 💀
     🏁 survivors: 0 vs 4 — winner: Cap'n Hoggarr
  ⚡ Y'Shaarj vs Cariel Roame (first: Cariel Roame)
     Y'Shaarj: [13/16, 6/3, 8/7, 4/6, 4/5, 4/4, 4/4]
     Cariel Roame: [3/6, 5/4, 4/7, 3/4, 3/7, 4/4, 3/2]
     ⚔ Wrath Weaver 3/6→3/0 💀  🛡 Soul Rewinder 6/3→6/0 💀
     ⚔ Wrath Weaver 13/16→13/12  🛡 Lava Lurker 4/7→4/0 💀
     ⚔ Fire Baller 5/4→5/0 💀  🛡 Wrath Weaver 13/12→13/7
     ⚔ Woodland Defiler 8/7→8/4  🛡 Marquee Ticker 3/7→3/0 💀
     ⚔ Laboratory Assistant 3/4→3/0 💀  🛡 Wrath Weaver 13/7→13/4
     ⚔ Leyline Surfacer 4/6→4/2  🛡 Sellemental 4/4→4/0 💀
     ⚔ Deflect-o-Bot 3/2→3/2  🛡 Wrath Weaver 13/4→13/1
     ⚔ Flaming Enforcer 4/5→4/2  🛡 Deflect-o-Bot 3/2→3/0 💀
     🏁 survivors: 6 vs 0 — winner: Y'Shaarj

  Alive: 8/8
  HP standings: Guff Runetotem (HP=30, Armor=8, Tier=4) | Cap'n Hoggarr (HP=30, Armor=2, Tier=4) | Time Twister Chromie (HP=30, Armor=7, Tier=4) | Cookie the Cook (HP=30, Armor=7, Tier=4) | Cariel Roame (HP=26, Armor=0, Tier=4) | Y'Shaarj (HP=21, Armor=0, Tier=4) | Malygos (HP=18, Armor=0, Tier=4) | Jandice Barov (HP=14, Armor=0, Tier=4)

### Turn 9

**Guff Runetotem**  HP=30 Armor=8 Gold=10 Tier=4

  Board: 4/4, 5/4, 6/7, 5/6, 5/6, 5/6, 3/3
  Tavern: Leyline Surfacer 5/7 T4 $3 | Prosthetic Hand 3/1 T4 $3 | Zesty Shaker 6/7 T4 $3 | Wyvern Outrider 2/8 T4 $3 | Imposing Percussionist 4/4 T4 $3 | Sick Riffs (spell) T1 $3

  → Board after: 4/4, 5/4, 6/7, 5/6, 5/6, 5/6, 2/2
  → ⬆ Upgrade T4→T5 | Bought | Sold | 💍 Got trinket: Drakkari Portrait | Gold: 10→0

**Cap'n Hoggarr**  HP=30 Armor=2 Gold=10 Tier=4

  Board: 5/8, 8/5 [Taunt], 5/6, 5/6, 5/6, 5/5, 1/1
  Tavern: Holo Rover 5/5 T4 $3 | Hardy Orca 2/7 T3 $3 | Wyvern Outrider 3/9 T4 $3 | Wildfire Elemental 9/6 T3 $3 | Tavern Tempest 5/5 T4 $3 | Angler's Lure (spell) T1 $3

  → Board after: 5/8, 8/5 [Taunt], 5/6, 5/6, 5/6, 5/5, 9/6
  → ⬆ Upgrade T4→T5 | Bought | Sold | 💍 Got trinket: S'Thara Sticker | Gold: 10→0

**Cariel Roame**  HP=26 Armor=0 Gold=10 Tier=4

  Board: 3/6, 5/4, 4/7 [Taunt], 3/4, 3/7, 4/4, 3/2 [DS]
  Tavern: Prosthetic Hand 3/1 T4 $3 | Wyvern Outrider 2/8 T4 $3 | Banana Slamma 3/6 T4 $3 | Enchanted Sentinel 3/5 T4 $3 | Sly Raptor 1/3 T3 $3 | Spitescale Special (spell) T4 $2

  → Board after: 9/12, 5/4, 4/7 [Taunt], 3/4, 3/7, 4/4, 2/8
  → ⬆ Upgrade T4→T5 | Bought | Sold | 💍 Got trinket: Drakkari Portrait | Gold: 10→0

**Malygos**  HP=18 Armor=0 Gold=10 Tier=4

  Board: 3/6, 4/4, 4/4, 6/6, 7/4, 5/7, 2/2
  Tavern: Imposing Percussionist 4/4 T4 $3 | Imposing Percussionist 4/4 T4 $3 | Banana Slamma 3/6 T4 $3 | Zesty Shaker 6/7 T4 $3 | Reef Riffer 3/2 T2 $3 | Misplaced Tea Set (spell) T4 $2

  → Board after: 3/6, 4/4, 4/4, 6/6, 7/4, 5/7, 6/7
  → ⬆ Upgrade T4→T5 | Bought | Sold | 💍 Got trinket: Drakkari Portrait | Gold: 10→0

**Time Twister Chromie**  HP=30 Armor=7 Gold=10 Tier=4

  Board: 5/6, 6/6, 5/5, 9/6, 3/9, 5/5, 5/3 [Reborn]
  Tavern: En-Djinn Blazer 7/7 T4 $3 | Manasaber 5/2 T1 $3 | Snow Baller 6/7 T2 $3 | Auto Assembler 3/3 T4 $3 | Annoy-o-Module 3/5 T3 $3 | Arcane Absorption (spell) T4 $1

  → Board after: 5/6, 6/6, 7/7, 9/6, 3/9, 5/5, 7/7
  → ⬆ Upgrade T4→T5 | Bought | Sold | 💍 Got trinket: Elementium Chest | Gold: 10→0

**Cookie the Cook**  HP=30 Armor=7 Gold=10 Tier=4

  Board: 5/8, 8/9, 4/4, 5/6, 12/7, 2/7 [Taunt], 3/2
  Tavern: Auto Assembler 3/3 T4 $3 | Trigore the Lasher 10/4 T4 $3 | False Implicator 2/2 T3 $3 | Trigore the Lasher 10/4 T4 $3 | Sellemental 5/5 T2 $3

  → Board after: 5/8, 8/9, 4/4, 5/6, 12/7, 2/7 [Taunt], 10/4
  → ⬆ Upgrade T4→T5 | Bought | Sold | 💍 Got trinket: Fountain Pen | Gold: 10→0

**Jandice Barov**  HP=14 Armor=0 Gold=10 Tier=4

  Board: 4/5, 8/3, 6/7, 5/6, 4/5, 4/5, 2/3
  Tavern: Seafloor Recruiter 6/6 T4 $3 | Felemental 8/6 T3 $3 | Metallic Hunter 4/2 T2 $3 | Refreshing Anomaly 6/7 T4 $3 | Zesty Shaker 6/7 T4 $3

  → Board after: 4/5, 10/5 [Taunt], 6/7, 5/6, 4/5, 4/5, 8/6
  → ⬆ Upgrade T4→T5 | Bought | Sold | 💍 Got trinket: S'Thara Sticker | Gold: 10→0

**Y'Shaarj**  HP=21 Armor=0 Gold=10 Tier=4

  Board: 13/16 [Taunt], 6/3 [Taunt], 8/7, 4/6, 4/5, 4/4, 4/4 [DS]
  Tavern: Banana Slamma 3/6 T4 $3 | Waveling 9/4 T3 $3 | Imposing Percussionist 4/4 T4 $3 | Dune Dweller 6/3 T1 $3 | Technical Element 5/6 T3 $3

  → Board after: 13/16 [Taunt], 6/3 [Taunt], 8/7, 4/6, 4/5, 4/4 [Taunt,DS], 9/4
  → ⬆ Upgrade T4→T5 | Bought | Sold | 💍 Got trinket: S'Thara Sticker | Gold: 10→0

**⚔ Combat Phase**

  ⚡ Cariel Roame vs Guff Runetotem (first: Cariel Roame)
     Cariel Roame: [9/12, 5/4, 4/7, 3/4, 3/7, 4/4, 2/8]
     Guff Runetotem: [4/4, 5/4, 6/7, 5/6, 5/6, 5/6, 2/2]
     ⚔ Wrath Weaver 9/12→9/6  🛡 Zesty Shaker 6/7→6/0 💀
     ⚔ Sellemental 4/4→4/0 💀  🛡 Lava Lurker 4/7→4/3
     ⚔ Fire Baller 5/4→5/0 💀  🛡 Fire Baller 5/4→5/0 💀
     ⚔ Technical Element 5/6→5/2  🛡 Lava Lurker 4/3→4/0 💀
     ⚔ Laboratory Assistant 3/4→3/2  🛡 Mawsworn Soulkeeper 2/2→2/0 💀
     ⚔ Technical Element 5/6→5/3  🛡 Laboratory Assistant 3/2→3/0 💀
     ⚔ Marquee Ticker 3/7→3/2  🛡 Refreshing Anomaly 5/6→5/3
     ⚔ Refreshing Anomaly 5/3→5/0 💀  🛡 Marquee Ticker 3/2→3/0 💀
     ⚔ Sellemental 4/4→4/0 💀  🛡 Technical Element 5/3→5/0 💀
     🏁 survivors: 2 vs 1 — winner: Cariel Roame
  ⚡ Y'Shaarj vs Jandice Barov (first: Y'Shaarj)
     Y'Shaarj: [13/16, 6/3, 8/7, 4/6, 10/15, 4/4, 9/4]
     Jandice Barov: [4/5, 10/5, 6/7, 5/6, 15/16, 10/12, 8/6]
     ⚔ Wrath Weaver 13/16→13/6  🛡 Waveling 10/5→10/0 💀
     ⚔ Snow Baller 4/5→4/0 💀  🛡 Soul Rewinder 6/3→6/0 💀
     ⚔ Woodland Defiler 8/7→8/0 💀  🛡 Felemental 8/6→8/0 💀
     ⚔ Banana Slamma 6/7→6/3  🛡 Holo Rover 4/4→4/4
     ⚔ Leyline Surfacer 4/6→4/0 💀  🛡 Flaming Enforcer 15/16→15/12
     ⚔ Woodland Defiler 5/6→5/0 💀  🛡 Wrath Weaver 13/6→13/1
     ⚔ Flaming Enforcer 10/15→10/9  🛡 Banana Slamma 6/3→6/0 💀
     ⚔ Flaming Enforcer 15/12→15/0 💀  🛡 Wrath Weaver 13/1→13/0 💀
     ⚔ Holo Rover 4/4→4/0 💀  🛡 Flaming Enforcer 10/12→10/8
     ⚔ Flaming Enforcer 10/8→10/0 💀  🛡 Flaming Enforcer 10/9→10/0 💀
     🏁 survivors: 1 vs 0 — winner: Y'Shaarj
  ⚡ Cookie the Cook vs Time Twister Chromie (first: Time Twister Chromie)
     Cookie the Cook: [5/8, 8/9, 4/4, 10/11, 12/7, 2/7, 10/4]
     Time Twister Chromie: [5/6, 6/6, 7/7, 9/6, 3/9, 5/5, 7/7]
     ⚔ Snow Baller 5/6→5/4  🛡 Hardy Orca 2/7→2/2
     ⚔ Wrath Weaver 5/8→5/0 💀  🛡 Wildfire Elemental 9/6→9/1
     ⚔ Floating Watcher 6/6→6/4  🛡 Hardy Orca 2/2→2/0 💀
     ⚔ Snow Baller 8/9→8/3  🛡 Floating Watcher 6/4→6/0 💀
     ⚔ Felemental 7/7→7/0 💀  🛡 Waveling 12/7→12/0 💀
     ⚔ Felemental 4/4→4/1  🛡 Waverider 3/9→3/5
     ⚔ Wildfire Elemental 9/1→9/0 💀  🛡 Snow Baller 8/3→8/0 💀
     ⚔ Flaming Enforcer 10/11→10/4  🛡 En-Djinn Blazer 7/7→7/0 💀
     ⚔ Waverider 3/5→3/0 💀  🛡 Trigore the Lasher 10/4→10/1
     ⚔ Trigore the Lasher 10/1→10/0 💀  🛡 Stomping Stegodon 5/5→5/0 💀
     🏁 survivors: 2 vs 1 — winner: Cookie the Cook
  ⚡ Cap'n Hoggarr vs Malygos (first: Cap'n Hoggarr)
     Cap'n Hoggarr: [5/8, 8/5, 5/6, 5/6, 5/6, 5/5, 9/6]
     Malygos: [3/6, 4/4, 4/4, 6/6, 7/4, 5/7, 6/7]
     ⚔ Wrath Weaver 5/8→5/2  🛡 Zesty Shaker 6/7→6/2
     ⚔ Wrath Weaver 3/6→3/0 💀  🛡 Soul Rewinder 8/5→8/2
     ⚔ Soul Rewinder 8/2→8/0 💀  🛡 Zesty Shaker 6/2→6/0 💀
     ⚔ Sellemental 4/4→4/0 💀  🛡 Wrath Weaver 5/2→5/0 💀
     ⚔ Technical Element 5/6→5/0 💀  🛡 Floating Watcher 6/6→6/1
     ⚔ Sellemental 4/4→4/0 💀  🛡 Felemental 5/5→5/1
     ⚔ Snow Baller 5/6→5/0 💀  🛡 Wildfire Elemental 7/4→7/0 💀
     ⚔ Floating Watcher 6/1→6/0 💀  🛡 Technical Element 5/6→5/0 💀
     ⚔ Felemental 5/1→5/0 💀  🛡 Leyline Surfacer 5/7→5/2
     ⚔ Leyline Surfacer 5/2→5/0 💀  🛡 Wildfire Elemental 9/6→9/1
     🏁 survivors: 1 vs 0 — winner: Cap'n Hoggarr

  Alive: 8/8
  HP standings: Guff Runetotem (HP=30, Armor=8, Tier=5) | Cap'n Hoggarr (HP=30, Armor=2, Tier=5) | Time Twister Chromie (HP=30, Armor=7, Tier=5) | Cookie the Cook (HP=30, Armor=7, Tier=5) | Cariel Roame (HP=26, Armor=0, Tier=5) | Y'Shaarj (HP=21, Armor=0, Tier=5) | Malygos (HP=10, Armor=0, Tier=5) | Jandice Barov (HP=6, Armor=0, Tier=5)

### Turn 10

**Guff Runetotem**  HP=30 Armor=8 Gold=10 Tier=5

  Board: 4/4, 5/4, 6/7, 5/6, 5/6, 5/6, 2/2
  Tavern: Ichoron the Protector 4/2 T4 $3 | Sewer Rat 3/2 T2 $3 | Bazaar Dealer 4/6 T5 $3 | Living Azerite 7/6 T5 $3 | En-Djinn Blazer 5/5 T4 $3 | Butchering (spell) T5 $2

  → Board after: 4/4, 5/4, 6/7, 5/6, 5/6, 5/6, 3/4
  → ⬆ Upgrade T5→T6 | Bought | Sold | Gold: 10→0

**Cap'n Hoggarr**  HP=30 Armor=2 Gold=10 Tier=5

  Board: 5/8, 8/5 [Taunt], 5/6, 5/6, 5/6, 5/5, 9/6
  Tavern: Sellemental 6/6 T2 $3 | Waverider 3/9 T4 $3 | Seafloor Recruiter 4/6 T4 $3 | Imposing Percussionist 5/5 T4 $3 | Rylak Metalhead 6/4 T4 $3 | Portal in a Crystal (spell) T5 $2

  → Board after: 7/10, 8/5 [Taunt], 5/6, 9/6, 6/6, 3/9, 6/4 [Taunt]
  → Bought | Sold | Gold: 10→0 | HP: 30→26 | Armor: 2→0

**Cariel Roame**  HP=26 Armor=0 Gold=10 Tier=5

  Board: 9/12, 5/4, 4/7 [Taunt], 3/4, 3/7, 4/4, 2/8
  Tavern: Tranquil Meditative 3/8 T5 $3 | Laboratory Assistant 3/4 T2 $3 | Ancestral Automaton 3/4 T2 $3 | Wrath Weaver 1/4 T1 $3 | En-Djinn Blazer 5/5 T4 $3 | Corrupted Cupcakes (spell) T5 $4

  → Board after: 13/16, 4/7 [Taunt], 3/7, 2/8, 3/8, 5/5, 1/4
  → Bought | Sold | Gold: 10→0 | HP: 26→24

**Malygos**  HP=10 Armor=0 Gold=10 Tier=5

  Board: 3/6, 4/4, 4/4, 6/6, 7/4, 5/7, 6/7
  Tavern: Scrap Scraper 6/5 T5 $3 | Scrap Scraper 6/5 T5 $3 | Abyssal Bruiser 1/1 T4 $3 | Accord-o-Tron 3/3 T3 $3 | Annoy-o-Module 2/4 T3 $3 | Arcane Absorption (spell) T4 $1

  → Board after: 12/12, 7/4, 5/7, 6/7, 6/5, 6/5, 1/1 [DS]
  → Bought | Sold | Gold: 10→0

**Time Twister Chromie**  HP=30 Armor=7 Gold=11 Tier=5

  Board: 5/6, 6/6, 7/7, 9/6, 3/9, 5/5, 7/7
  Tavern: Annoy-o-Module 3/5 T3 $3 | Hunting Tiger Shark 4/6 T4 $3 | Deep-Sea Angler 3/4 T3 $3 | Tichondrius 7/10 T5 $3 | Accord-o-Tron 4/4 T3 $3 | Boon of Beetles (spell) T4 $1

  → Board after: 6/6, 7/7, 11/8, 3/9, 7/7, 7/10, 3/4
  → Bought | Sold | Gold: 11→0

**Cookie the Cook**  HP=30 Armor=7 Gold=10 Tier=5

  Board: 5/8, 8/9, 4/4, 10/11, 12/7, 2/7 [Taunt], 10/8
  Tavern: Leyline Surfacer 6/8 T4 $3 | Abyssal Bruiser 1/1 T4 $3 | Sprightly Scarab 4/2 T3 $3 | Banana Slamma 7/8 T4 $3 | Lurking Leviathan 4/9 T5 $3 | Selfish Bounty (spell) T3 $2

  → Board after: 8/9, 10/11, 12/7, 11/9 [Reborn], 7/8, 6/8, 1/1 [DS]
  → Bought | Sold | Gold: 10→0

**Jandice Barov**  HP=6 Armor=0 Gold=10 Tier=5

  Board: 4/5, 10/5 [Taunt], 6/7, 5/6, 15/16, 10/12, 8/6
  Tavern: Divine Sparkbot 5/3 T5 $3 | Glowscale 8/8 T5 $3 | Cord Puller 5/3 T1 $3 | Malchezaar, Prince of Dance 6/5 T4 $3 | Iridescent Skyblazer 7/10 T5 $3 | Angler's Lure (spell) T1 $3

  → Board after: 10/5 [Taunt], 15/16, 10/12, 8/6, 7/10, 8/8 [Taunt], 5/3 [DS]
  → Bought | Sold | Gold: 10→0

**Y'Shaarj**  HP=21 Armor=0 Gold=10 Tier=5

  Board: 13/16 [Taunt], 6/3 [Taunt], 8/7, 4/6, 10/15, 4/4 [Taunt,DS], 9/4
  Tavern: Living Azerite 9/6 T5 $3 | Hunting Tiger Shark 6/8 T4 $3 | Cord Puller 1/1 T1 $3 | Bazaar Dealer 4/6 T5 $3 | Seafloor Recruiter 3/5 T4 $3 | Hired Headhunter (spell) T5 $3

  → Board after: 15/18 [Taunt], 8/7, 10/15, 9/4, 9/6, 6/8, 1/1 [DS]
  → Bought | Sold | Gold: 10→0 | HP: 21→20

**⚔ Combat Phase**

  ⚡ Malygos vs Cariel Roame (first: Malygos)
     Malygos: [12/12, 7/4, 5/7, 6/7, 6/5, 6/5, 1/1]
     Cariel Roame: [13/16, 4/7, 3/7, 2/8, 3/8, 5/5, 1/4]
     ⚔ Floating Watcher 12/12→12/8  🛡 Lava Lurker 4/7→4/0 💀
     ⚔ Wrath Weaver 13/16→13/10  🛡 Scrap Scraper 6/5→6/0 💀
     ⚔ Wildfire Elemental 7/4→7/1  🛡 Tranquil Meditative 3/8→3/1
     ⚔ Marquee Ticker 3/7→3/2  🛡 Leyline Surfacer 5/7→5/4
     ⚔ Leyline Surfacer 5/4→5/3  🛡 Wrath Weaver 1/4→1/0 💀
     ⚔ Wyvern Outrider 2/8→2/1  🛡 Wildfire Elemental 7/1→7/0 💀
     ⚔ Zesty Shaker 6/7→6/5  🛡 Wyvern Outrider 2/1→2/0 💀
     ⚔ Tranquil Meditative 3/1→3/0 💀  🛡 Scrap Scraper 6/5→6/2
     ⚔ Scrap Scraper 6/2→6/0 💀  🛡 En-Djinn Blazer 5/5→5/0 💀
     🏁 survivors: 4 vs 2 — winner: Malygos
  ⚡ Guff Runetotem vs Time Twister Chromie (first: Guff Runetotem)
     Guff Runetotem: [4/4, 5/4, 6/7, 5/6, 5/6, 5/6, 3/4]
     Time Twister Chromie: [6/6, 7/7, 11/8, 3/9, 7/7, 7/10, 3/4]
     ⚔ Sellemental 4/4→4/0 💀  🛡 En-Djinn Blazer 7/7→7/3
     ⚔ Floating Watcher 6/6→6/1  🛡 Refreshing Anomaly 5/6→5/0 💀
     ⚔ Fire Baller 5/4→5/0 💀  🛡 Felemental 7/7→7/2
     ⚔ Felemental 7/2→7/0 💀  🛡 Technical Element 5/6→5/0 💀
     ⚔ Zesty Shaker 6/7→6/1  🛡 Floating Watcher 6/1→6/0 💀
     ⚔ Wildfire Elemental 11/8→11/5  🛡 Snow Baller 3/4→3/0 💀
     ⚔ Technical Element 5/6→5/3  🛡 Deep-Sea Angler 3/4→3/0 💀
     ⚔ Waverider 3/9→3/3  🛡 Zesty Shaker 6/1→6/0 💀
     🏁 survivors: 1 vs 4 — winner: Guff Runetotem
  ⚡ Y'Shaarj vs Cap'n Hoggarr (first: Cap'n Hoggarr)
     Y'Shaarj: [15/18, 8/7, 10/15, 9/4, 9/6, 6/8, 1/1]
     Cap'n Hoggarr: [7/10, 8/5, 5/6, 9/6, 6/6, 3/9, 6/4]
     ⚔ Wrath Weaver 7/10→7/0 💀  🛡 Wrath Weaver 15/18→15/11
     ⚔ Wrath Weaver 15/11→15/5  🛡 Rylak Metalhead 6/4→6/0 💀
     ⚔ Soul Rewinder 8/5→8/0 💀  🛡 Wrath Weaver 15/5→15/0 💀
     ⚔ Woodland Defiler 8/7→8/0 💀  🛡 Wildfire Elemental 9/6→9/0 💀
     ⚔ Technical Element 5/6→5/5  🛡 Cord Puller 1/1→1/1
     ⚔ Flaming Enforcer 10/15→10/9  🛡 Sellemental 6/6→6/0 💀
     ⚔ Waverider 3/9→3/0 💀  🛡 Living Azerite 9/6→9/3
     ⚔ Waveling 9/4→9/0 💀  🛡 Technical Element 5/5→5/0 💀
     🏁 survivors: 4 vs 0 — winner: Y'Shaarj
  ⚡ Jandice Barov vs Cookie the Cook (first: Jandice Barov)
     Jandice Barov: [10/5, 15/16, 10/12, 8/6, 7/10, 8/8, 5/3]
     Cookie the Cook: [8/9, 10/11, 12/7, 11/9, 7/8, 6/8, 1/1]
     ⚔ Waveling 10/5→10/0 💀  🛡 Flaming Enforcer 10/11→10/1
     ⚔ Snow Baller 8/9→8/1  🛡 Glowscale 8/8→8/0 💀
     ⚔ Flaming Enforcer 15/16→15/4  🛡 Waveling 12/7→12/0 💀
     ⚔ Flaming Enforcer 10/1→10/0 💀  🛡 Flaming Enforcer 10/12→10/2
     ⚔ Flaming Enforcer 10/2→10/0 💀  🛡 Banana Slamma 7/8→7/0 💀
     ⚔ Trigore the Lasher 11/9→11/0 💀  🛡 Flaming Enforcer 15/4→15/0 💀
     ⚔ Felemental 8/6→8/5  🛡 Abyssal Bruiser 1/1→1/1
     ⚔ Leyline Surfacer 6/8→6/1  🛡 Iridescent Skyblazer 7/10→7/4
     ⚔ Iridescent Skyblazer 7/4→7/0 💀  🛡 Snow Baller 8/1→8/0 💀
     ⚔ Abyssal Bruiser 1/1→1/0 💀  🛡 Felemental 8/5→8/4
     ⚔ Cord Puller 5/3→5/3  🛡 Leyline Surfacer 6/1→6/0 💀
     🏁 survivors: 2 vs 0 — winner: Jandice Barov

  💀 **Cap'n Hoggarr eliminated!** (HP=0, Turn 10)
  Alive: 7/8
  HP standings: Guff Runetotem (HP=30, Armor=8, Tier=6) | Time Twister Chromie (HP=30, Armor=7, Tier=5) | Cookie the Cook (HP=28, Armor=0, Tier=5) | Cariel Roame (HP=24, Armor=0, Tier=5) | Y'Shaarj (HP=20, Armor=0, Tier=5) | Malygos (HP=10, Armor=0, Tier=5) | Jandice Barov (HP=6, Armor=0, Tier=5)

### Turn 11

**Guff Runetotem**  HP=30 Armor=8 Gold=10 Tier=6

  Board: 4/4, 5/4, 6/7, 5/6, 5/6, 5/6, 3/4
  Tavern: One-Amalgam Tour Group 7/8 T6 $3 | Void Pup Trainer 7/7 T5 $3 | Shell Collector 4/3 T2 $3 | P-0UL-TR-0N 10/10 T6 $3 | Moonsteel Juggernaut 8/8 T6 $3 | Prosthetic Hand 3/1 T4 $3 | Brood of Nozdormu (spell) T5 $2

  → Board after: 4/4, 5/4, 6/7, 5/6, 5/6, 5/6, 12/10 [G]
  → Bought | Sold | Gold: 10→0

**Cariel Roame**  HP=24 Armor=0 Gold=10 Tier=5

  Board: 13/16, 4/7 [Taunt], 3/7, 2/8, 3/8, 5/5, 1/4
  Tavern: Shell Collector 5/4 T2 $3 | Hardy Orca 2/7 T3 $3 | Deflect-o-Bot 4/3 T3 $3 | Auto Assembler 6/6 T4 $3 | Tavern Tempest 4/4 T4 $3 | Time Management (spell) T3 $4

  → Board after: 13/16, 4/7 [Taunt], 3/7, 2/8, 3/8, 5/5, 6/6
  → ⬆ Upgrade T5→T6 | Bought | Gold: 10→0

**Malygos**  HP=10 Armor=0 Gold=10 Tier=5

  Board: 12/12, 7/4, 5/7, 6/7, 6/5, 6/5, 1/1 [DS]
  Tavern: Rimescale Priestess 5/4 T4 $3 | Deep-Sea Angler 4/4 T3 $3 | Hunting Tiger Shark 5/6 T4 $3 | Marquee Ticker 5/8 T4 $3 | Iridescent Skyblazer 5/9 T5 $3 | Golden Touch (spell) T5 $5

  → Board after: 12/12, 14/8 [G], 5/7, 6/7, 6/5, 6/5, 5/9
  → ⬆ Upgrade T5→T6 | Bought | Sold | Gold: 10→0

**Time Twister Chromie**  HP=30 Armor=7 Gold=10 Tier=5

  Board: 6/6, 7/7, 11/8, 3/9, 7/7, 7/10, 3/4
  Tavern: Spiked Savior 9/3 T5 $3 | Leyline Surfacer 7/9 T4 $3 | Tranquil Meditative 4/9 T5 $3 | Leyline Surfacer 10/12 T4 $3 | Sprightly Scarab 4/2 T3 $3 | Arcane Absorption (spell) T4 $1

  → Board after: 6/6, 9/9, 11/8, 3/9, 7/7, 7/10, 12/14 [Taunt]
  → ⬆ Upgrade T5→T6 | Bought | Sold | Gold: 10→0

**Cookie the Cook**  HP=28 Armor=0 Gold=10 Tier=5

  Board: 8/9, 10/11, 12/7, 11/11 [Reborn], 7/8, 6/8, 1/1 [DS]
  Tavern: Shadowdancer 6/4 T5 $3 | Humming Bird 2/5 T2 $3 | False Implicator 5/3 T3 $3 | Leeching Felhound 7/5 T3 $3 | Scrap Scraper 7/6 T5 $3 | Undersea Mount (spell) T1 $3

  → Board after: 8/9, 10/11, 12/7, 11/11 [Reborn], 7/8, 6/8, 7/6
  → ⬆ Upgrade T5→T6 | Bought | Sold | Gold: 10→0

**Jandice Barov**  HP=6 Armor=0 Gold=10 Tier=5

  Board: 10/5 [Taunt], 15/16, 10/12, 8/6, 7/10, 8/8 [Taunt], 5/3 [DS]
  Tavern: Nightmare Par-tea Guest 6/6 T5 $3 | Deep Blue Crooner 9/5 T3 $3 | Waveling 12/5 T3 $3 | En-Djinn Blazer 7/7 T4 $3 | Manasaber 8/3 T1 $3 | Channel the Devourer (spell) T5 $4

  → Board after: 10/5 [Taunt], 15/16, 10/12 [DS], 8/6, 7/10, 8/8 [Taunt], 12/5
  → ⬆ Upgrade T5→T6 | Sold | Gold: 10→0

**Y'Shaarj**  HP=20 Armor=0 Gold=10 Tier=5

  Board: 15/18 [Taunt], 8/7, 10/15, 9/4, 9/6, 6/8, 1/1 [DS]
  Tavern: Rylak Metalhead 5/3 T4 $3 | Tichondrius 6/9 T5 $3 | Felemental 4/4 T3 $3 | Shadowdancer 8/4 T5 $3 | Monstrous Macaw 8/5 T4 $3

  → Board after: 18/21 [Taunt], 9/8, 11/16, 9/4, 9/6, 6/8, 7/10
  → ⬆ Upgrade T5→T6 | Bought | Sold | Gold: 10→0 | HP: 20→19

**⚔ Combat Phase**

  ⚡ Jandice Barov vs Time Twister Chromie (first: Time Twister Chromie)
     Jandice Barov: [10/5, 22/23, 16/18, 8/6, 7/10, 8/8, 12/5]
     Time Twister Chromie: [6/6, 9/9, 11/8, 3/9, 7/7, 7/10, 12/14]
     ⚔ Floating Watcher 6/6→6/0 💀  🛡 Waveling 10/5→10/0 💀
     ⚔ Flaming Enforcer 22/23→22/11  🛡 Leyline Surfacer 12/14→12/0 💀
     ⚔ Felemental 9/9→9/1  🛡 Glowscale 8/8→8/0 💀
     ⚔ Flaming Enforcer 16/18→16/18  🛡 Waverider 3/9→3/0 💀
     ⚔ Wildfire Elemental 11/8→11/0 💀  🛡 Felemental 8/6→8/0 💀
     ⚔ Iridescent Skyblazer 7/10→7/3  🛡 En-Djinn Blazer 7/7→7/0 💀
     ⚔ Tichondrius 7/10→7/0 💀  🛡 Flaming Enforcer 16/18→16/11
     ⚔ Waveling 12/5→12/0 💀  🛡 Felemental 9/1→9/0 💀
     🏁 survivors: 3 vs 0 — winner: Jandice Barov
  ⚡ Y'Shaarj vs Malygos (first: Malygos)
     Y'Shaarj: [18/21, 9/8, 19/21, 9/4, 9/6, 6/8, 7/10]
     Malygos: [12/12, 14/8, 5/7, 6/7, 6/5, 6/5, 5/9]
     ⚔ Floating Watcher 12/12→12/0 💀  🛡 Wrath Weaver 18/21→18/9
     ⚔ Wrath Weaver 18/9→18/0 💀  🛡 Wildfire Elemental 14/8→14/0 💀
     ⚔ Leyline Surfacer 5/7→5/0 💀  🛡 Woodland Defiler 9/8→9/3
     ⚔ Woodland Defiler 9/3→9/0 💀  🛡 Zesty Shaker 6/7→6/0 💀
     ⚔ Scrap Scraper 6/5→6/0 💀  🛡 Flaming Enforcer 19/21→19/15
     ⚔ Flaming Enforcer 19/15→19/10  🛡 Iridescent Skyblazer 5/9→5/0 💀
     ⚔ Scrap Scraper 6/5→6/0 💀  🛡 Waveling 9/4→9/0 💀
     🏁 survivors: 4 vs 0 — winner: Y'Shaarj
  ⚡ Cookie the Cook vs Cariel Roame (first: Cookie the Cook)
     Cookie the Cook: [8/9, 12/16, 12/7, 11/11, 7/8, 6/8, 7/6]
     Cariel Roame: [13/16, 4/7, 3/7, 2/8, 3/8, 5/5, 6/6]
     ⚔ Snow Baller 8/9→8/5  🛡 Lava Lurker 4/7→4/0 💀
     ⚔ Wrath Weaver 13/16→13/4  🛡 Waveling 12/7→12/0 💀
     ⚔ Flaming Enforcer 12/16→12/10  🛡 Auto Assembler 6/6→6/0 💀
     ⚔ Marquee Ticker 3/7→3/0 💀  🛡 Flaming Enforcer 12/10→12/7
     ⚔ Trigore the Lasher 11/11→11/9  🛡 Wyvern Outrider 2/8→2/0 💀
     ⚔ Tranquil Meditative 3/8→3/1  🛡 Scrap Scraper 7/6→7/3
     ⚔ Banana Slamma 7/8→7/3  🛡 En-Djinn Blazer 5/5→5/0 💀
     🏁 survivors: 6 vs 2 — winner: Cookie the Cook

  💀 **Malygos eliminated!** (HP=0, Turn 11)
  Alive: 6/8
  HP standings: Guff Runetotem (HP=30, Armor=0, Tier=6) | Cookie the Cook (HP=28, Armor=0, Tier=6) | Cariel Roame (HP=24, Armor=0, Tier=6) | Time Twister Chromie (HP=22, Armor=0, Tier=6) | Y'Shaarj (HP=19, Armor=0, Tier=6) | Jandice Barov (HP=6, Armor=0, Tier=6)

### Turn 12

**Guff Runetotem**  HP=30 Armor=0 Gold=10 Tier=6

  Board: 4/4, 5/4, 6/7, 5/6, 5/6, 5/6, 12/10 [G]
  Tavern: Auto Assembler 2/2 T4 $3 | Charging Czarina 4/1 T5 $3 | Ashen Corruptor 6/6 T5 $3 | Monstrous Macaw 5/4 T4 $3 | False Implicator 1/1 T3 $3 | Leeching Felhound 3/3 T3 $3 | Perfect Vision (spell) T6 $2

  → Board after: 5/4, 6/7, 5/6, 5/6, 5/6, 12/10 [G], 8/14 [G]
  → Bought | Sold | Gold: 10→0

**Cariel Roame**  HP=24 Armor=0 Gold=10 Tier=6

  Board: 13/16, 4/7 [Taunt], 3/7, 2/8, 3/8, 5/5, 6/6
  Tavern: Sprightly Scarab 4/2 T3 $3 | Moonsteel Juggernaut 9/9 T6 $3 | Twisted Wrathguard 9/9 T6 $3 | Enchanted Sentinel 7/9 T4 $3 | Groundbreaker 6/5 T6 $3 | Junk Jouster 9/8 T6 $3 | Angler's Lure (spell) T1 $3

  → Board after: 15/18, 6/6, 9/9 [DS], 9/9, 9/8, 7/9, 6/5
  → Bought | Sold | Gold: 10→0 | HP: 24→23

**Time Twister Chromie**  HP=22 Armor=0 Gold=10 Tier=6

  Board: 6/6, 9/9, 11/8, 3/9, 7/7, 7/10, 12/14 [Taunt]
  Tavern: Ruthless Queensguard 7/7 T6 $3 | En-Djinn Blazer 7/7 T4 $3 | Deep-Sea Angler 3/4 T3 $3 | Waverider 3/9 T4 $3 | Rylak Metalhead 6/4 T4 $3 | Ashen Corruptor 7/7 T5 $3 | Glowing Crown (spell) T1 $3

  → Board after: 9/9, 11/8, 7/10, 18/20 [Taunt], 9/9, 7/7, 6/4 [Taunt]
  → Bought | Sold | Gold: 10→0

**Cookie the Cook**  HP=28 Armor=0 Gold=10 Tier=6

  Board: 8/9, 12/16, 12/7, 11/13 [Reborn], 7/8, 6/8, 7/6
  Tavern: Laboratory Assistant 4/5 T2 $3 | Maelstrom Emergent 3/8 T5 $3 | Ichoron the Protector 11/5 T4 $3 | Ashen Corruptor 7/7 T5 $3 | Living Azerite 11/8 T5 $3 | Holo Rover 5/5 T4 $3 | Sanctify (spell) T5 $1

  → Board after: 8/9, 12/16, 12/7, 11/13 [Reborn], 11/8, 11/5 [DS], 5/5 [DS]
  → Bought | Sold | Gold: 10→0

**Jandice Barov**  HP=6 Armor=0 Gold=10 Tier=6

  Board: 10/5 [Taunt], 22/23, 16/18 [DS], 8/6, 7/10, 8/8 [Taunt], 12/5
  Tavern: Batty Terrorguard 7/3 T6 $3 | Hunting Tiger Shark 10/8 T4 $3 | Junk Jouster 9/8 T6 $3 | Junk Jouster 18/11 T6 $3 | Dune Dweller 6/5 T1 $3 | Ultraviolet Ascendant 12/7 T6 $3 | Meditation (spell) T1 $3

  → Board after: 22/23, 16/18 [DS], 18/11, 12/7, 10/8 [DS], 9/8, 6/5
  → Bought | Sold | Gold: 10→0

**Y'Shaarj**  HP=19 Armor=0 Gold=10 Tier=6

  Board: 18/21 [Taunt], 9/8, 19/21, 9/4, 9/6, 6/8, 7/10
  Tavern: Sprightly Scarab 6/2 T3 $3 | Maelstrom Emergent 5/8 T5 $3 | Felemental 8/6 T3 $3 | Hunting Tiger Shark 3/5 T4 $3 | Technical Element 8/9 T3 $3 | Ichoron the Protector 5/3 T4 $3 | Undersea Mount (spell) T1 $3

  → Board after: 18/21 [Taunt], 9/8, 19/21, 9/6, 7/10, 8/9, 4/6 [Reborn]
  → Bought | Sold | Gold: 10→0

**⚔ Combat Phase**

  ⚡ Cookie the Cook vs Guff Runetotem (first: Cookie the Cook)
     Cookie the Cook: [8/9, 16/21, 12/7, 11/13, 11/8, 11/5, 5/5]
     Guff Runetotem: [5/4, 6/7, 5/6, 5/6, 5/6, 12/10, 8/14]
     ⚔ Snow Baller 8/9→8/4  🛡 Technical Element 5/6→5/0 💀
     ⚔ Fire Baller 5/4→5/0 💀  🛡 Holo Rover 5/5→5/5
     ⚔ Flaming Enforcer 16/21→16/16  🛡 Technical Element 5/6→5/0 💀
     ⚔ Zesty Shaker 6/7→6/0 💀  🛡 Waveling 12/7→12/1
     ⚔ Waveling 12/1→12/0 💀  🛡 Stormpike Lieutenant 8/14→8/2
     ⚔ Refreshing Anomaly 5/6→5/0 💀  🛡 Living Azerite 11/8→11/3
     ⚔ Trigore the Lasher 11/13→11/5  🛡 Stormpike Lieutenant 8/2→8/0 💀
     ⚔ Raging Contender 12/10→12/5  🛡 Holo Rover 5/5→5/0 💀
     ⚔ Living Azerite 11/3→11/0 💀  🛡 Raging Contender 12/5→12/0 💀
     🏁 survivors: 4 vs 0 — winner: Cookie the Cook
  ⚡ Jandice Barov vs Y'Shaarj (first: Jandice Barov)
     Jandice Barov: [29/26, 16/18, 18/11, 12/7, 10/8, 9/8, 9/11]
     Y'Shaarj: [18/21, 9/8, 24/24, 9/6, 7/10, 8/9, 4/6]
     ⚔ Flaming Enforcer 29/26→29/8  🛡 Wrath Weaver 18/21→18/0 💀
     ⚔ Woodland Defiler 9/8→9/0 💀  🛡 Dune Dweller 9/11→9/2
     ⚔ Flaming Enforcer 16/18→16/18  🛡 Living Azerite 9/6→9/0 💀
     ⚔ Flaming Enforcer 24/24→24/15  🛡 Dune Dweller 9/2→9/0 💀
     ⚔ Junk Jouster 18/11→18/7  🛡 Hunting Tiger Shark 4/6→4/0 💀
     ⚔ Tichondrius 7/10→7/1  🛡 Junk Jouster 9/8→9/1
     ⚔ Ultraviolet Ascendant 12/7→12/0 💀  🛡 Tichondrius 7/1→7/0 💀
     ⚔ Technical Element 8/9→8/0 💀  🛡 Flaming Enforcer 29/8→29/0 💀
     ⚔ Hunting Tiger Shark 10/8→10/8  🛡 Flaming Enforcer 24/15→24/5
     🏁 survivors: 4 vs 1 — winner: Jandice Barov
  ⚡ Time Twister Chromie vs Cariel Roame (first: Cariel Roame)
     Time Twister Chromie: [9/9, 11/8, 7/10, 18/20, 9/9, 7/7, 6/4]
     Cariel Roame: [15/18, 6/6, 9/9, 9/9, 9/8, 7/9, 6/5]
     ⚔ Wrath Weaver 15/18→15/0 💀  🛡 Leyline Surfacer 18/20→18/5
     ⚔ Felemental 9/9→9/0 💀  🛡 Moonsteel Juggernaut 9/9→9/9
     ⚔ Auto Assembler 6/6→6/0 💀  🛡 Rylak Metalhead 6/4→6/0 💀
     ⚔ Wildfire Elemental 11/8→11/1  🛡 Enchanted Sentinel 7/9→7/0 💀
     ⚔ Moonsteel Juggernaut 9/9→9/0 💀  🛡 Leyline Surfacer 18/5→18/0 💀
     ⚔ Tichondrius 7/10→7/1  🛡 Twisted Wrathguard 9/9→9/2
     ⚔ Twisted Wrathguard 9/2→9/0 💀  🛡 Ashen Corruptor 7/7→7/0 💀
     ⚔ En-Djinn Blazer 9/9→9/3  🛡 Groundbreaker 6/5→6/0 💀
     ⚔ Junk Jouster 9/8→9/0 💀  🛡 Wildfire Elemental 11/1→11/0 💀
     🏁 survivors: 2 vs 0 — winner: Time Twister Chromie

  Alive: 6/8
  HP standings: Cookie the Cook (HP=28, Armor=0, Tier=6) | Time Twister Chromie (HP=22, Armor=0, Tier=6) | Y'Shaarj (HP=19, Armor=0, Tier=6) | Guff Runetotem (HP=15, Armor=0, Tier=6) | Cariel Roame (HP=8, Armor=0, Tier=6) | Jandice Barov (HP=6, Armor=0, Tier=6)

### Turn 13

**Guff Runetotem**  HP=15 Armor=0 Gold=10 Tier=6

  Board: 5/4, 6/7, 5/6, 5/6, 5/6, 12/10 [G], 8/14 [G]
  Tavern: Trigore the Lasher 9/3 T4 $3 | Spiked Savior 8/2 T5 $3 | Deep Blue Crooner 2/2 T3 $3 | Iridescent Skyblazer 3/8 T5 $3 | Scrap Scraper 6/5 T5 $3 | False Implicator 1/1 T3 $3 | Arcane Absorption (spell) T4 $1

  → Board after: 6/7, 5/6, 5/6, 5/6, 12/10 [G], 8/14 [G], 5/4
  → Bought | Sold | Gold: 10→0

**Cariel Roame**  HP=8 Armor=0 Gold=10 Tier=6

  Board: 15/18, 6/6, 9/9 [DS], 9/9, 9/8, 7/9, 6/5
  Tavern: Malchezaar, Prince of Dance 6/5 T4 $3 | Rylak Metalhead 9/7 T4 $3 | Reef Riffer 4/3 T2 $3 | Ichoron the Protector 5/3 T4 $3 | Falling Sky Golem 9/7 T6 $3 | Goldrinn, the Great Wolf 9/9 T6 $3 | Undersea Mount (spell) T1 $3

  → Board after: 17/20, 9/9 [DS], 9/9, 9/8, 9/9, 9/7 [DS], 5/3 [DS]
  → Bought | Sold | Gold: 10→0 | HP: 8→7

**Time Twister Chromie**  HP=22 Armor=0 Gold=10 Tier=6

  Board: 9/9, 11/8, 7/10, 18/20 [Taunt], 9/9, 7/7, 6/4 [Taunt]
  Tavern: Maelstrom Emergent 3/8 T5 $3 | Refreshing Anomaly 7/8 T4 $3 | Malchezaar, Prince of Dance 6/5 T4 $3 | False Implicator 5/5 T3 $3 | Crackling Cyclone 5/4 T1 $3 | Monstrous Macaw 9/8 T4 $3 | Glowing Crown (spell) T1 $3

  → Board after: 9/9, 11/8, 7/10, 18/20 [Taunt], 9/9, 9/8, 5/5
  → Bought | Sold | Gold: 10→0

**Cookie the Cook**  HP=28 Armor=0 Gold=10 Tier=6

  Board: 8/9, 16/21, 12/7, 11/14 [Reborn], 11/8, 11/5 [DS], 5/5 [DS]
  Tavern: Reef Riffer 4/3 T2 $3 | Dune Dweller 6/5 T1 $3 | Glowscale 8/8 T5 $3 | Shadowdancer 15/7 T5 $3 | Air Revenant 6/9 T5 $3 | Charging Czarina 5/2 T5 $3 | Tricky Trousers (spell) T3 $1

  → Board after: 8/9, 16/21, 12/7, 11/14 [Reborn], 11/8, 15/7 [Taunt], 4/3
  → Bought | Sold | Gold: 10→0

**Jandice Barov**  HP=6 Armor=0 Gold=10 Tier=6

  Board: 29/26, 16/18 [DS], 18/11, 12/7, 10/8 [DS], 9/8, 6/5
  Tavern: Felemental 13/9 T3 $3 | Malchezaar, Prince of Dance 9/6 T4 $3 | Snow Baller 7/8 T2 $3 | Scrap Scraper 10/7 T5 $3 | Fire Baller 8/7 T2 $3 | Spiked Savior 15/5 T5 $3 | Meditation (spell) T1 $3

  → Board after: 29/26, 16/18 [DS], 18/11, 12/7, 13/9, 15/5 [Taunt,Reborn], 7/8
  → Bought | Sold | Gold: 10→0

**Y'Shaarj**  HP=19 Armor=0 Gold=10 Tier=6

  Board: 18/21 [Taunt], 9/8, 24/24, 9/6, 7/10, 8/9, 4/6 [Reborn]
  Tavern: False Implicator 5/3 T3 $3 | Stomping Stegodon 8/8 T4 $3 | Hunting Tiger Shark 7/7 T4 $3 | Darkcrest Strategist 5/6 T5 $3 | Prosthetic Hand 7/3 T4 $3 | Waveling 9/4 T3 $3 | Tavern Coin (spell) T1 $3

  → Board after: 18/21 [Taunt], 9/8, 24/24, 7/10, 8/9, 8/8, 7/3 [Reborn]
  → Bought | Sold | Gold: 10→0

**⚔ Combat Phase**

  ⚡ Jandice Barov vs Guff Runetotem (first: Guff Runetotem)
     Jandice Barov: [37/33, 16/18, 18/11, 12/7, 23/29, 15/5, 17/28]
     Guff Runetotem: [6/7, 5/6, 5/6, 5/6, 12/10, 8/14, 5/4]
     ⚔ Zesty Shaker 6/7→6/0 💀  🛡 Spiked Savior 15/5→15/0 💀
     ⚔ Flaming Enforcer 37/33→37/28  🛡 Lil' K.T. 5/4→5/0 💀
     ⚔ Technical Element 5/6→5/0 💀  🛡 Felemental 23/29→23/24
     ⚔ Flaming Enforcer 16/19→16/14  🛡 Refreshing Anomaly 5/6→5/0 💀
     ⚔ Technical Element 5/6→5/0 💀  🛡 Junk Jouster 18/11→18/6
     ⚔ Junk Jouster 18/6→18/0 💀  🛡 Stormpike Lieutenant 8/14→8/0 💀
     ⚔ Raging Contender 12/10→12/0 💀  🛡 Snow Baller 17/28→17/16
     🏁 survivors: 5 vs 0 — winner: Jandice Barov
  ⚡ Cookie the Cook vs Y'Shaarj (first: Y'Shaarj)
     Cookie the Cook: [8/9, 21/23, 12/7, 11/14, 11/8, 15/7, 4/3]
     Y'Shaarj: [18/21, 9/8, 29/27, 7/10, 8/9, 8/8, 7/3]
     ⚔ Wrath Weaver 18/21→18/6  🛡 Shadowdancer 15/7→15/0 💀
     ⚔ Snow Baller 8/9→8/0 💀  🛡 Wrath Weaver 18/6→18/0 💀
     ⚔ Woodland Defiler 9/8→9/0 💀  🛡 Living Azerite 11/8→11/0 💀
     ⚔ Flaming Enforcer 21/23→21/15  🛡 Stomping Stegodon 8/8→8/0 💀
     ⚔ Flaming Enforcer 29/27→29/6  🛡 Flaming Enforcer 21/15→21/0 💀
     ⚔ Waveling 12/7→12/0 💀  🛡 Flaming Enforcer 29/6→29/0 💀
     ⚔ Tichondrius 7/10→7/6  🛡 Reef Riffer 4/3→4/0 💀
     ⚔ Trigore the Lasher 11/14→11/7  🛡 Prosthetic Hand 7/3→7/0 💀
     ⚔ Technical Element 8/9→8/0 💀  🛡 Trigore the Lasher 11/7→11/0 💀
     🏁 survivors: 0 vs 1 — winner: Y'Shaarj
  ⚡ Cariel Roame vs Time Twister Chromie (first: Time Twister Chromie)
     Cariel Roame: [17/20, 9/9, 9/9, 9/8, 9/9, 9/7, 5/3]
     Time Twister Chromie: [9/9, 11/8, 7/10, 18/20, 9/9, 9/8, 5/5]
     ⚔ Felemental 9/9→9/0 💀  🛡 Junk Jouster 9/8→9/0 💀
     ⚔ Wrath Weaver 17/20→17/2  🛡 Leyline Surfacer 18/20→18/3
     ⚔ Wildfire Elemental 11/8→11/0 💀  🛡 Twisted Wrathguard 9/9→9/0 💀
     ⚔ Moonsteel Juggernaut 9/9→9/9  🛡 Leyline Surfacer 18/3→18/0 💀
     ⚔ Tichondrius 7/10→7/0 💀  🛡 Wrath Weaver 17/2→17/0 💀
     ⚔ Goldrinn, the Great Wolf 9/9→9/0 💀  🛡 En-Djinn Blazer 9/9→9/0 💀
     ⚔ Monstrous Macaw 9/8→9/0 💀  🛡 Moonsteel Juggernaut 9/9→9/0 💀
     ⚔ Falling Sky Golem 9/7→9/7  🛡 False Implicator 5/5→5/0 💀
     🏁 survivors: 2 vs 0 — winner: Cariel Roame

  💀 **Guff Runetotem eliminated!** (HP=0, Turn 13)
  Alive: 5/8
  HP standings: Y'Shaarj (HP=19, Armor=0, Tier=6) | Cookie the Cook (HP=17, Armor=0, Tier=6) | Cariel Roame (HP=7, Armor=0, Tier=6) | Time Twister Chromie (HP=7, Armor=0, Tier=6) | Jandice Barov (HP=6, Armor=0, Tier=6)

### Turn 14

**Cariel Roame**  HP=7 Armor=0 Gold=10 Tier=6

  Board: 17/20, 9/9 [DS], 9/9, 9/8, 9/9, 9/7 [DS], 5/3 [DS]
  Tavern: Marquee Ticker 4/8 T4 $3 | Laboratory Assistant 4/5 T2 $3 | Tranquil Meditative 4/9 T5 $3 | Iridescent Skyblazer 4/9 T5 $3 | Ichoron the Protector 5/3 T4 $3 | Air Revenant 8/11 T5 $3 | Arcane Absorption (spell) T4 $1

  → Board after: 19/22, 9/9 [DS], 9/9, 9/8, 9/9, 8/11 [DS], 4/5
  → Bought | Sold | Gold: 10→0 | HP: 7→6

**Time Twister Chromie**  HP=7 Armor=0 Gold=10 Tier=6

  Board: 9/9, 11/8, 7/10, 18/20 [Taunt], 9/9, 9/8, 5/5
  Tavern: Elemental of Surprise 14/14 T6 $3 | Tranquil Meditative 4/9 T5 $3 | P-0UL-TR-0N 11/11 T6 $3 | Floating Watcher 8/8 T3 $5 | Ichoron the Protector 6/4 T4 $3 | Humming Bird 2/5 T2 $3

  → Board after: 18/18, 20/17, 27/29 [Taunt], 18/18, 23/23 [DS], 20/20, 13/18
  → Bought | Sold | Gold: 10→0

**Cookie the Cook**  HP=17 Armor=0 Gold=10 Tier=6

  Board: 8/9, 21/23, 12/7, 11/16 [Reborn], 11/8, 15/7 [Taunt], 4/3
  Tavern: Shadowdancer 9/5 T5 $3 | Tranquil Meditative 10/11 T5 $3 | Leyline Surfacer 8/10 T4 $3 | Dune Dweller 7/6 T1 $3 | Lurking Leviathan 7/10 T5 $3 | Abyssal Bruiser 1/2 T4 $3

  → Board after: 21/23, 12/7, 11/16 [Reborn], 11/8, 21/13 [Taunt], 10/11, 7/6 [DS]
  → Bought | Sold | Gold: 10→2

**Jandice Barov**  HP=6 Armor=0 Gold=10 Tier=6

  Board: 37/33, 16/18 [DS], 18/11, 12/7, 13/9, 15/5 [Taunt,Reborn], 7/8
  Tavern: Deflect-o-Bot 11/6 T3 $3 | Rylak Metalhead 13/7 T4 $3 | Humming Bird 3/6 T2 $3 | Sly Raptor 3/5 T3 $3 | Cord Puller 6/4 T1 $3 | Nightmare Par-tea Guest 11/9 T5 $3

  → Board after: 37/34, 16/19 [DS], 18/12, 13/10, 15/6 [Taunt,Reborn], 11/9, 3/6
  → Bought | Sold | Gold: 10→0

**Y'Shaarj**  HP=19 Armor=0 Gold=10 Tier=6

  Board: 18/21 [Taunt], 9/8, 29/27, 7/10, 8/9, 8/8, 7/3 [Reborn]
  Tavern: Marquee Ticker 7/9 T4 $3 | Surf n' Surf 5/3 T1 $3 | Famished Felbat 7/4 T5 $3 | Glowscale 11/11 T5 $3 | P-0UL-TR-0N 11/11 T6 $3 | Annoy-o-Module 3/5 T3 $3

  → Board after: 21/24 [Taunt], 30/28, 8/11, 8/9, 11/11 [Taunt], 11/11, 5/3
  → Bought | Sold | Gold: 10→0 | HP: 19→18

**⚔ Combat Phase**

  ⚡ Cookie the Cook vs Jandice Barov (first: Jandice Barov)
     Cookie the Cook: [22/24, 12/7, 11/16, 11/8, 21/13, 10/11, 7/6]
     Jandice Barov: [40/39, 16/19, 18/12, 13/10, 16/6, 12/9, 4/6]
     ⚔ Flaming Enforcer 40/39→40/18  🛡 Shadowdancer 21/13→21/0 💀
     ⚔ Flaming Enforcer 22/24→22/8  🛡 Spiked Savior 16/6→16/0 💀
     ⚔ Flaming Enforcer 16/20→16/8  🛡 Waveling 12/7→12/0 💀
     ⚔ Trigore the Lasher 11/16→11/0 💀  🛡 Flaming Enforcer 40/18→40/7
     ⚔ Junk Jouster 18/12→18/1  🛡 Living Azerite 11/8→11/0 💀
     ⚔ Tranquil Meditative 10/11→10/0 💀  🛡 Flaming Enforcer 40/7→40/0 💀
     ⚔ Felemental 13/10→13/3  🛡 Dune Dweller 7/6→7/6
     ⚔ Dune Dweller 7/6→7/0 💀  🛡 Junk Jouster 18/1→18/0 💀
     ⚔ Nightmare Par-tea Guest 12/9→12/0 💀  🛡 Flaming Enforcer 22/8→22/0 💀
     🏁 survivors: 0 vs 3 — winner: Jandice Barov
  ⚡ Time Twister Chromie vs Y'Shaarj (first: Time Twister Chromie)
     Time Twister Chromie: [18/18, 20/17, 27/29, 18/18, 23/23, 20/20, 13/18]
     Y'Shaarj: [21/24, 33/33, 8/11, 8/9, 11/11, 11/11, 5/3]
     ⚔ Felemental 18/18→18/7  🛡 Glowscale 11/11→11/0 💀
     ⚔ Wrath Weaver 21/24→21/0 💀  🛡 Leyline Surfacer 27/29→27/8
     ⚔ Wildfire Elemental 20/17→20/6  🛡 P-0UL-TR-0N 11/11→11/0 💀
     ⚔ Flaming Enforcer 33/33→33/6  🛡 Leyline Surfacer 27/8→27/0 💀
     ⚔ En-Djinn Blazer 18/18→18/13  🛡 Surf n' Surf 5/3→5/0 💀
     ⚔ Tichondrius 8/11→8/0 💀  🛡 Elemental of Surprise 23/23→23/23
     ⚔ Elemental of Surprise 23/23→23/15  🛡 Technical Element 8/9→8/0 💀
     🏁 survivors: 6 vs 1 — winner: Time Twister Chromie

  Alive: 5/8
  HP standings: Y'Shaarj (HP=18, Armor=0, Tier=6) | Time Twister Chromie (HP=7, Armor=0, Tier=6) | Cariel Roame (HP=6, Armor=0, Tier=6) | Jandice Barov (HP=6, Armor=0, Tier=6) | Cookie the Cook (HP=2, Armor=0, Tier=6)

### Turn 15

**Cariel Roame**  HP=6 Armor=0 Gold=10 Tier=6

  Board: 19/22, 9/9 [DS], 9/9, 9/8, 9/9, 8/11 [DS], 4/5
  Tavern: Marquee Ticker 7/11 T4 $3 | Floating Watcher 5/5 T3 $5 | Flaming Enforcer 5/6 T4 $3 | Rylak Metalhead 6/4 T4 $3 | Ichoron the Protector 5/3 T4 $3 | Laboratory Assistant 4/5 T2 $3 | Arcane Absorption (spell) T4 $1

  → Board after: 23/26, 9/9 [DS], 9/9, 9/9, 8/11 [DS], 7/11, 6/4 [Taunt]
  → Bought | Sold | Gold: 10→0 | HP: 6→4

**Time Twister Chromie**  HP=7 Armor=0 Gold=10 Tier=6

  Board: 18/18, 20/17, 27/29 [Taunt], 18/18, 23/23 [DS], 20/20, 13/18
  Tavern: Soul Rewinder 8/5 T2 $3 | Maelstrom Emergent 3/8 T5 $3 | Lurking Leviathan 4/9 T5 $3 | Moonsteel Juggernaut 12/12 T6 $3 | Groundbreaker 6/5 T6 $3 | Seafloor Recruiter 4/6 T4 $3 | Misplaced Tea Set (spell) T4 $2

  → Board after: 18/18, 20/17, 27/29 [Taunt], 18/18, 25/25 [DS], 20/20, 6/5
  → Bought | Sold | Gold: 10→0

**Cookie the Cook**  HP=2 Armor=0 Gold=10 Tier=6

  Board: 22/24, 12/7, 11/17 [Reborn], 11/8, 21/13 [Taunt], 10/11, 7/6 [DS]
  Tavern: Holo Rover 11/7 T4 $3 | Sprightly Scarab 7/3 T3 $3 | Rylak Metalhead 9/5 T4 $3 | Hunting Tiger Shark 4/6 T4 $3 | Imposing Percussionist 11/7 T4 $3 | Firelands Fugitive 13/15 T5 $3 | Staff of Enrichment (spell) T3 $2

  → Board after: 22/24, 11/17 [Reborn], 11/8, 21/13 [Taunt], 10/11, 13/15 [DS], 8/4 [Reborn]
  → Bought | Sold | Gold: 10→2 | HP: 2→0

**Jandice Barov**  HP=6 Armor=0 Gold=10 Tier=6

  Board: 40/39, 16/19 [DS], 18/12, 13/10, 15/6 [Taunt,Reborn], 11/9, 3/6
  Tavern: Prosthetic Hand 5/3 T4 $3 | Abyssal Bruiser 1/1 T4 $3 | Scrap Scraper 17/10 T5 $3 | Ashen Corruptor 11/9 T5 $3 | Woodland Defiler 13/10 T4 $3 | Ashen Corruptor 8/8 T5 $3 | Sick Riffs (spell) T1 $3

  → Board after: 38/38, 16/19 [DS], 18/12, 13/10, 17/10, 13/10, 5/3 [Reborn]
  → Bought | Sold | Gold: 10→0

**Y'Shaarj**  HP=18 Armor=0 Gold=10 Tier=6

  Board: 21/24 [Taunt], 33/33, 8/11, 8/9, 11/11 [Taunt], 11/11, 5/3
  Tavern: Leeching Felhound 7/5 T3 $3 | Charging Czarina 8/3 T5 $3 | Marquee Ticker 10/12 T4 $3 | Auto Assembler 3/3 T4 $3 | Air Revenant 6/9 T5 $3 | Woodland Defiler 6/7 T4 $3

  → Board after: 28/31 [Taunt], 36/36 [DS], 11/14, 11/11 [Taunt], 11/11, 10/12, 3/3
  → Bought | Sold | Gold: 10→0 | HP: 18→13

**⚔ Combat Phase**

  ⚡ Y'Shaarj vs Jandice Barov (first: Y'Shaarj)
     Y'Shaarj: [28/31, 45/47, 11/14, 11/11, 11/11, 10/12, 3/3]
     Jandice Barov: [38/38, 17/20, 18/12, 13/10, 17/10, 13/10, 5/3]
     ⚔ Wrath Weaver 28/31→28/14  🛡 Scrap Scraper 17/10→17/0 💀
     ⚔ Brann Bronzebeard 38/38→38/27  🛡 Glowscale 11/11→11/0 💀
     ⚔ Flaming Enforcer 45/47→45/47  🛡 Felemental 13/10→13/0 💀
     ⚔ Flaming Enforcer 17/20→17/20  🛡 Wrath Weaver 28/14→28/0 💀
     ⚔ Tichondrius 11/14→11/0 💀  🛡 Flaming Enforcer 17/20→17/9
     ⚔ Junk Jouster 18/12→18/0 💀  🛡 Flaming Enforcer 45/47→45/29
     ⚔ P-0UL-TR-0N 11/11→11/0 💀  🛡 Woodland Defiler 13/10→13/0 💀
     ⚔ Prosthetic Hand 5/3→5/0 💀  🛡 Marquee Ticker 10/12→10/7
     ⚔ Marquee Ticker 10/7→10/0 💀  🛡 Brann Bronzebeard 38/27→38/17
     🏁 survivors: 2 vs 2 — winner: Y'Shaarj
  ⚡ Time Twister Chromie vs Cariel Roame (first: Cariel Roame)
     Time Twister Chromie: [18/18, 20/17, 27/29, 18/18, 25/25, 20/20, 6/5]
     Cariel Roame: [23/26, 9/9, 9/9, 9/9, 8/11, 7/11, 6/4]
     ⚔ Wrath Weaver 23/26→23/0 💀  🛡 Leyline Surfacer 27/29→27/6
     ⚔ Felemental 18/18→18/12  🛡 Rylak Metalhead 6/4→6/0 💀
     ⚔ Moonsteel Juggernaut 9/9→9/9  🛡 Leyline Surfacer 27/6→27/0 💀
     ⚔ Wildfire Elemental 20/17→20/8  🛡 Twisted Wrathguard 9/9→9/0 💀
     ⚔ Goldrinn, the Great Wolf 10/10→10/0 💀  🛡 P-0UL-TR-0N 20/20→20/10
     ⚔ En-Djinn Blazer 18/18→18/10  🛡 Air Revenant 8/11→8/11
     ⚔ Air Revenant 8/11→8/0 💀  🛡 Felemental 18/12→18/4
     ⚔ Elemental of Surprise 25/25→25/25  🛡 Moonsteel Juggernaut 9/9→9/0 💀
     ⚔ Marquee Ticker 7/11→7/0 💀  🛡 Wildfire Elemental 20/8→20/1
     🏁 survivors: 6 vs 0 — winner: Time Twister Chromie

  💀 **Cariel Roame eliminated!** (HP=0, Turn 15)
  💀 **Cookie the Cook eliminated!** (HP=0, Turn 15)
  Alive: 3/8
  HP standings: Y'Shaarj (HP=13, Armor=0, Tier=6) | Time Twister Chromie (HP=7, Armor=0, Tier=6) | Jandice Barov (HP=6, Armor=0, Tier=6)

---

## Final Standings

| # | Hero | HP | Armor | Alive | Eliminated Turn |
|---|---|---|---|---|
| 1 | Y'Shaarj | 13 | 0 | Yes | — |
| 2 | Time Twister Chromie | 7 | 0 | Yes | — |
| 3 | Jandice Barov | 6 | 0 | Yes | — |
| 4 | Cariel Roame | 0 | 0 | No | 15 |
| 5 | Cookie the Cook | 0 | 0 | No | 15 |
| 6 | Guff Runetotem | 0 | 0 | No | 13 |
| 7 | Malygos | 0 | 0 | No | 11 |
| 8 | Cap'n Hoggarr | 0 | 0 | No | 10 |

---

## Heuristic Strategy

The Q-score heuristic evaluates each affordable tavern minion by:

1. **Buy & Play**: Score = current_board_score + minion.atk + minion.health + aura_bonus
2. **Sell & Replace**: If board full, replace weakest minion if net score change > 0
3. **Upgrade**: If no beneficial buy is available and gold ≥ upgrade_cost, upgrade tavern tier
4. **Refresh**: If no other action is possible, refresh the tavern for 1 gold

This is a greedy one-step heuristic — no lookahead, no opponent modeling, no combat simulation.
Average rank in self-play: ~4.5 (random among identical strategies)