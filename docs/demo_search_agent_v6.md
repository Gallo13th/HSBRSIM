======================================================================
  Hearthstone Battlegrounds — SearchAgent v2 Demo
======================================================================

  Seed: 42  |  Model: BoardEval v2 + GameValue v4
  Search: Greedy one-step lookahead with board embeddings
  Features: HDT-observable POMDP (397 dims, per-opponent combat memory)

  Agent Hero: Yogg-Saron, Hope's End
  Opponents (heuristic):
    1. Sneed
    2. Overlord Saurfang
    3. Ysera
    4. Inge, the Iron Hymn
    5. Professor Putricide
    6. Sylvanas Windrunner
    7. Drek'Thar

======================================================================
  GAME LOG
======================================================================

─── Turn 1 ───
  State: HP=30  Gold=3  Tier=1  Armor=18
  Board: (empty)
  Tavern: [0] False Implicator 1/1 T1 $3 | [1] False Implicator 1/1 T1 $3 | [2] Windfall Tornado 4/4 T1 $3 | [3] Sick Riffs (spell) T1 $3
  Initial V_game = 1.1132

  [0] buy_tavern_0  (V: 1.1132 → 1.1827, Δ=+0.0695)
       → buy 1/1 minion
  [1] play_hand_0  (V: 1.1827 → 1.3192, Δ=+0.1365)
       → play 1/1 from hand
  [2] END_TURN  (V=1.3192)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  (empty)
    Post-combat board: 1/1
    Teacher predicted placement: 1.000 (1.0th place)
    Alive players: 8/8

─── Turn 2 ───
  State: HP=30  Gold=4  Tier=1  Armor=16
  Board: 1/1
  Tavern: [0] False Implicator 3/2 T1 $3 | [1] Windfall Tornado 6/5 T1 $3 | [2] Sick Riffs (spell) T1 $3 | [3] Undersea Mount (spell) T1 $3
  Initial V_game = 1.1610

  [0] upgrade  (V: 1.1610 → 1.3118, Δ=+0.1508)
       → upgrade to tier 2 for stronger minions
  [1] refresh  (V: 1.3118 → 1.3595, Δ=+0.0477)
       → refresh for better minion options
  [2] END_TURN  (V=1.3595)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  1/1
    Post-combat board: 1/1
    Teacher predicted placement: 1.000 (1.0th place)
    Alive players: 8/8

─── Turn 3 ───
  State: HP=30  Gold=5  Tier=2  Armor=14
  Board: 1/1
  Tavern: [0] Soul Rewinder 6/2 T2 $3 | [1] Bristleback Bully 5/3 T2 $3 | [2] Metallic Hunter 4/2 T2 $3 | [3] Old Soul 5/5 T2 $3
  Initial V_game = 1.1212

  [0] buy_tavern_0  (V: 1.1212 → 1.2197, Δ=+0.0985)
       → buy 6/2 minion
  [1] play_hand_0  (V: 1.2197 → 1.3041, Δ=+0.0844)
       → play 6/2 from hand
  [2] refresh  (V: 1.3041 → 1.3482, Δ=+0.0441)
       → refresh for better minion options
  [3] refresh  (V: 1.3482 → 1.3870, Δ=+0.0388)
       → refresh for better minion options
  [4] END_TURN  (V=1.3870)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  1/1
    Post-combat board: 1/1, 6/2
    Teacher predicted placement: 1.000 (1.0th place)
    Alive players: 8/8

─── Turn 4 ───
  State: HP=30  Gold=6  Tier=2  Armor=11
  Board: 1/1, 6/2
  Tavern: [0] Harmless Bonehead 3/2 T1 $3 | [1] Eternal Knight 4/3 T2 $3 | [2] False Implicator 3/2 T1 $3 | [3] Picky Eater 3/2 T1 $3
  Initial V_game = 1.1199

  [0] upgrade  (V: 1.1199 → 1.3518, Δ=+0.2319)
       → upgrade to tier 3 for stronger minions
  [1] refresh  (V: 1.3518 → 1.3955, Δ=+0.0437)
       → refresh for better minion options
  [2] END_TURN  (V=1.3955)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  1/1, 6/2
    Post-combat board: 1/1, 6/2
    Teacher predicted placement: 1.000 (1.0th place)
    Alive players: 8/8

─── Turn 5 ───
  State: HP=30  Gold=7  Tier=3  Armor=3
  Board: 1/1, 6/2
  Tavern: [0] Annoy-o-Tron 3/3 T1 $3 | [1] False Implicator 3/2 T1 $3 | [2] Soul Rewinder 6/2 T2 $3 | [3] Eternal Knight 4/3 T2 $3
  Initial V_game = 0.9368

  [0] upgrade  (V: 0.9368 → 1.3018, Δ=+0.3650)
       → upgrade to tier 4 for stronger minions
  [1] END_TURN  (V=1.3018)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  1/1, 6/2
    Post-combat board: 1/1, 6/2
    Teacher predicted placement: 1.000 (1.0th place)
    Alive players: 8/8

─── Turn 6 ───
  State: HP=24  Gold=8  Tier=4  Armor=0
  Board: 1/1, 6/2
  Tavern: [0] Annoy-o-Tron 5/4 T1 $3 | [1] False Implicator 5/3 T1 $3 | [2] Soul Rewinder 8/3 T2 $3 | [3] Eternal Knight 4/4 T2 $3 | [4] Leeching Felhound 3/3 T3 $3 | [5] Misplaced Tea Set (spell) T4 $3
  Initial V_game = 0.8522

  [0] upgrade  (V: 0.8522 → 1.2172, Δ=+0.3651)
       → upgrade to tier 5 for stronger minions
  [1] END_TURN  (V=1.2172)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  1/1, 6/2
    Post-combat board: 1/1, 6/2
    Teacher predicted placement: 0.000 (8.0th place)
    Alive players: 8/8

─── Turn 7 ───
  State: HP=14  Gold=9  Tier=5  Armor=0
  Board: 1/1, 6/2
  Tavern: [0] Annoy-o-Tron 7/5 T1 $3 | [1] False Implicator 7/4 T1 $3 | [2] Soul Rewinder 10/4 T2 $3 | [3] Eternal Knight 4/5 T2 $3 | [4] Leeching Felhound 5/4 T3 $3 | [5] Misplaced Tea Set (spell) T4 $3 | [6] Butchering (spell) T5 $3
  Initial V_game = 0.8196

  [0] upgrade  (V: 0.8196 → 1.0710, Δ=+0.2515)
       → upgrade to tier 6 for stronger minions
  [1] END_TURN  (V=1.0710)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  1/1, 6/2
    Post-combat board: 1/1, 6/2
    Teacher predicted placement: 0.000 (8.0th place)
    Alive players: 8/8

─── Turn 8 ───
  State: HP=4  Gold=10  Tier=6  Armor=0
  Board: 1/1, 6/2
  Tavern: [0] Annoy-o-Tron 9/6 T1 $3 | [1] False Implicator 9/5 T1 $3 | [2] Soul Rewinder 12/5 T2 $3 | [3] Eternal Knight 4/6 T2 $3 | [4] Leeching Felhound 7/5 T3 $3 | [5] Misplaced Tea Set (spell) T4 $3 | [6] Butchering (spell) T5 $3 | [7] Queen's Command (spell) T5 $3
  Initial V_game = 0.5809

  [0] sell_board_0  (V: 0.5809 → 0.6073, Δ=+0.0264)
       → sell 1/1 for +1 gold
  [1] sell_board_0  (V: 0.6073 → 0.6097, Δ=+0.0024)
       → sell 6/2 for +1 gold
  [2] refresh  (V: 0.6097 → 0.6113, Δ=+0.0015)
       → refresh for better minion options
  [3] END_TURN  (V=0.6113)
       → Ending recruit phase, proceeding to combat

  ⚔ Combat Phase:
    Pre-combat board:  1/1, 6/2
    Post-combat board: (empty)
    Teacher predicted placement: 0.000 (8.0th place)
    Alive players: 7/8

======================================================================
  FINAL STANDINGS
======================================================================

  1. Overlord Saurfang  (HP=30, alive=False)
  2. Yogg-Saron, Hope's End  (HP=0, alive=False)  ← AGENT
  3. Sneed  (HP=0, alive=False)
  4. Ysera  (HP=0, alive=False)
  5. Inge, the Iron Hymn  (HP=0, alive=False)
  6. Professor Putricide  (HP=0, alive=False)
  7. Sylvanas Windrunner  (HP=0, alive=False)
  8. Drek'Thar  (HP=0, alive=False)

  Agent final placement: 2
  Total agent actions: 16
  Total state evaluations: 189

======================================================================
  ARCHITECTURE SUMMARY
======================================================================

  Pipeline: Combat Simulator → BoardEval → GameValue → Search Policy

  BoardEvalNetwork v2 (embedding-based):
    - BoardEmbedder: (7,15) minion features → 32-dim embedding
    - Per-slot MLP + learned attention + mean/max pool
    - CombatPredictor: concat(emb_a, emb_b, diff, product) → P(A wins)
    - Trained on 44,958 combat pairs from 500 games
    - Pairwise accuracy: 99.1%

  GameValueNetwork v4 (HDT-observable POMDP):
    - Per-opponent: last_seen_board(32) + staleness + combat_history +
      hp + tier + armor + board_size + triples×6 + upgrades×5 = 51 dims
    - Shared opp_proj(51→32→16) + mean pool → 16
    - Total input: 32(board) + 6(own) + 7×51(opp) + 2(global) = 397 dims
    - Teacher: CombatPredictor pairwise ranking (full-information)
    - Model: 6,705 parameters

  SearchAgent v2:
    - Greedy one-step lookahead using GameValueNetwork
    - At each step: enumerate legal actions, simulate, evaluate V(s')
    - Chooses action with highest predicted state value
    - v6 greedy: avg_rank 2.00 (matches v2 teacher)

