import json, os
import numpy as np
ROOT = '/home/data/users/gaoletian/projects/HSBRSIM'
G = json.load(open(os.path.join(ROOT, '.tmp_trace/games.json')))['games']
seen, U = set(), []
for g in G:
    if g['hash'] in seen: continue
    seen.add(g['hash']); U.append(g)

def p50(xs):
    xs = sorted(xs); n = len(xs)
    return float('nan') if n == 0 else (xs[n//2] if n % 2 else .5*(xs[n//2-1]+xs[n//2]))

print('turn | n_upg  buy_mean_upg  gold_upg | n_ctrl buy_mean_ctrl gold_ctrl')
for t in range(2, 14):
    u = [g['turn'][str(t)] for g in U if str(t) in g['turn'] and g['turn'][str(t)]['upg'] > 0]
    c = [g['turn'][str(t)] for g in U if str(t) in g['turn'] and g['turn'][str(t)]['upg'] == 0]
    if not u and not c: continue
    print(f'{t:4d} | {len(u):5d}  {np.mean([d["buy"] for d in u]) if u else float("nan"):10.2f}  '
          f'{np.mean([d["gold0"] for d in u]) if u else float("nan"):7.1f} | '
          f'{len(c):6d} {np.mean([d["buy"] for d in c]) if c else float("nan"):12.2f} '
          f'{np.mean([d["gold0"] for d in c]) if c else float("nan"):8.1f}')

# matched t>=5 only, and t2 separately
for lo, hi in ((2, 2), (5, 8), (9, 12)):
    u = [g['turn'][str(t)] for g in U for t in range(lo, hi+1) if str(t) in g['turn'] and g['turn'][str(t)]['upg'] > 0]
    c = [g['turn'][str(t)] for g in U for t in range(lo, hi+1) if str(t) in g['turn'] and g['turn'][str(t)]['upg'] == 0]
    if u and c:
        print(f't{lo}-{hi}: upg n={len(u)} buy={np.mean([d["buy"] for d in u]):.2f} p50={p50([d["buy"] for d in u])} '
              f'| ctrl n={len(c)} buy={np.mean([d["buy"] for d in c]):.2f} p50={p50([d["buy"] for d in c])}')

# per game: buys on t5-8 upgrade turns vs t5-8 control turns
diffs = []
for g in U:
    a = [g['turn'][str(t)]['buy'] for t in range(5, 9) if str(t) in g['turn'] and g['turn'][str(t)]['upg'] > 0]
    b = [g['turn'][str(t)]['buy'] for t in range(5, 9) if str(t) in g['turn'] and g['turn'][str(t)]['upg'] == 0]
    if a and b: diffs.append(np.mean(a) - np.mean(b))
print(f'paired t5-8 buy diff: mean={np.mean(diffs):+.2f} n={len(diffs)} neg={sum(1 for d in diffs if d<0)}/{len(diffs)}')
