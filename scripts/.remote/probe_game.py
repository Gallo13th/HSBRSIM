#!/usr/bin/env python3
import json, sys, time
sys.path.insert(0, '/home/data/users/gaoletian/projects/HSBRSIM')
import hsbg_engine as E
from hsbg.az import env_api as EA

# cid -> id
cat = json.loads(E.catalog_json())
cid2id = {int(c['cid']): str(c['id']) for c in cat if c.get('cid') is not None}
print('catalog', len(cid2id))

g = E.Game(1001)
EA.finish_hero_select(g)
print('num players', EA.num_players(g), 'turn', g.turn)
t0 = time.time()
steps = 0
seen = set()
while not g.is_over() and steps < 20000:
    for p in range(8):
        if g.is_over():
            break
        if not g.needs_action(p):
            continue
        t = int(g.turn)
        if t in (3, 6, 10, 14) and t not in seen and p == 0:
            pj = json.loads(g.player_json(0))
            seen.add(t)
            print(f'--- turn {t} player_json keys:', list(pj.keys()))
            print('  board[0]:', json.dumps((pj.get('board') or [{}])[0], ensure_ascii=False)[:600])
            sh = pj.get('shop') or []
            print('  shop[0]:', json.dumps(sh[0] if sh else {}, ensure_ascii=False)[:600])
            hd = pj.get('hand') or []
            print('  hand[0]:', json.dumps(hd[0] if hd else {}, ensure_ascii=False)[:500])
            print('  stats keys:', list((pj.get('stats') or {}).keys())[:20])
            print('  tier', pj.get('tier'), 'gold', pj.get('gold'), 'hp', pj.get('health'))
        g.bot_play(p)
        steps += 1

print(f'game over={g.is_over()} steps={steps} elapsed={time.time()-t0:.2f}s placement={list(g.placements())}')
