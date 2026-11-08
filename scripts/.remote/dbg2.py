#!/usr/bin/env python3
import json, sys
sys.path.insert(0, '/home/data/users/gaoletian/projects/HSBRSIM')
sys.path.insert(0, '/home/data/users/gaoletian/projects/HSBRSIM/scripts')
import numpy as np
import hsbg_engine as E
from hsbg.az import env_api as EA
from hsbg.az.train.common import mask_from_bytes
from comp_scripts import CompPolicy, COMPS, _config_json, strength_of

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 880001
key = sys.argv[2] if len(sys.argv) > 2 else 'A'
game = E.Game(seed, _config_json(COMPS[key], seed))
EA.finish_hero_select(game)
pol = CompPolicy(COMPS[key], seed=1)
NAME = {}
NAME = {}
log = []
while not game.is_over() and len(log) < 600:
    for p in range(8):
        if game.is_over() or not game.needs_action(p):
            continue
        if p != 0:
            game.bot_play(p)
            continue
        mask = mask_from_bytes(game.legal_mask(0))
        v = json.loads(game.view(0))
        me = v['me']
        a = int(pol.act(v, mask))
        tag = f"a{a}"
        if a == 0: tag = 'END'
        elif a == 1: tag = 'REF'
        elif a == 2: tag = 'FRZ'
        elif a == 3: tag = 'UP'
        elif a == 4: tag = 'HP'
        elif 8 <= a < 16: tag = f"BUY{a-8}"
        elif 16 <= a < 23: tag = f"SELL{a-16}"
        elif 30 <= a < 46: tag = f"CH{a-30}"
        elif 46 <= a < 126: tag = f"PLAY{(a-46)//8}"
        log.append((v['turn'], me.get('gold'), me.get('tier'),
                    sum(strength_of(m) for m in me.get('board') or []),
                    len(me.get('board') or []), len(me.get('hand') or []), tag))
        game.step(0, a)
print('turn gold tier sig board hand act')
prev = None
for row in log:
    if row[6] != 'END' or (prev and prev[0] != row[0]):
        print(row)
    prev = row
print('over', game.is_over(), 'turn', game.turn, 'illegal', pol.illegal,
      'place', list(game.placements()))

