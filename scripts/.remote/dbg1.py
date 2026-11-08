#!/usr/bin/env python3
import json, sys
sys.path.insert(0, '/home/data/users/gaoletian/projects/HSBRSIM')
sys.path.insert(0, '/home/data/users/gaoletian/projects/HSBRSIM/scripts')
import numpy as np
import hsbg_engine as E
from hsbg.az import env_api as EA
from hsbg.az.train.common import mask_from_bytes
from comp_scripts import CompPolicy, COMPS, _config_json

seed = 880001
game = E.Game(seed, _config_json(COMPS['A'], seed))
EA.finish_hero_select(game)
pol = CompPolicy(COMPS['A'], seed=1)
steps = 0
while not game.is_over() and steps < 400:
    for p in range(8):
        if game.is_over() or not game.needs_action(p):
            continue
        if p != 0:
            game.bot_play(p)
            continue
        mask = mask_from_bytes(game.legal_mask(0))
        v = json.loads(game.view(0))
        v['_mask'] = mask
        me = v['me']
        a = int(pol.act(v, mask))
        if steps < 60:
            print(f"t{v['turn']} ph={v['phase']} gold={me.get('gold')} tier={me.get('tier')} "
                  f"board={len(me.get('board') or [])} hand={len(me.get('hand') or [])} "
                  f"shop={len(me.get('shop') or [])} pend={bool(me.get('pending'))} "
                  f"act={a} legal={bool(mask[a])} nlegal={int(mask.sum())}")
        steps += 1
        game.step(0, a)
print('over', game.is_over(), 'turn', game.turn, 'steps', steps, 'illegal', pol.illegal)
pj = json.loads(game.player_json(0))
print('board:', [(m.get('id'), m.get('atk'), m.get('hp')) for m in pj.get('board') or []])
print('snaps:', [(s['turn'], s['strength'], s['tier']) for s in pol.snaps][:16])
