import json, os
import numpy as np
ROOT = '/home/data/users/gaoletian/projects/HSBRSIM'
G = json.load(open(os.path.join(ROOT, '.tmp_trace/games.json')))['games']
seen, U = set(), []
for g in G:
    if g['hash'] in seen: continue
    seen.add(g['hash']); U.append(g)

# --- cross-validate against ingest_human_play output (demo_index.json) ---
idx = json.load(open(os.path.join(ROOT, 'runs/human_play/demo_index.json')))
rows = idx['games'] if isinstance(idx, dict) and 'games' in idx else idx
byfile = {r['file']: r for r in rows}
print('demo_index entries:', len(rows))
ok = 0; bad = []
for g in U:
    r = byfile.get(g['file'])
    if not r: continue
    # demo_index stores sig*10
    if abs(r['t15'] - g['t15']) <= 1 and int(r['final_tier'] or 0) == g['tier_final'] and (r['t9_tier'] in (None, g['tier9'])):
        ok += 1
    else:
        bad.append((g['file'], r['t15'], g['t15'], r['final_tier'], g['tier_final'], r['t9_tier'], g['tier9']))
print(f'cross-check demo_index: ok={ok}/{len(U)} bad={bad}')
print('sample demo t15 (demo / mine):', [(r['file'][11:23], r['t15'], g['t15']) for g in U[:4] for r in [byfile.get(g['file'])] if r])

def p50(xs):
    xs = sorted(xs); n=len(xs)
    return float('nan') if n==0 else (xs[n//2] if n%2 else .5*(xs[n//2-1]+xs[n//2]))
def rank(xs):
    o=sorted(range(len(xs)), key=lambda i: xs[i]); r=[0.]*len(xs); i=0
    while i<len(o):
        j=i
        while j+1<len(o) and xs[o[j+1]]==xs[o[i]]: j+=1
        for k in range(i,j+1): r[o[k]]=(i+j)/2.+1
        i=j+1
    return r
def sp(x,y):
    rx,ry=rank(x),rank(y); mx=sum(rx)/len(rx); my=sum(ry)/len(ry)
    return sum((a-mx)*(b-my) for a,b in zip(rx,ry))/((sum((a-mx)**2 for a in rx)*sum((b-my)**2 for b in ry))**.5)

print('\n=== C3 (games reaching t10; drop extreme 143644) ===')
U3=[g for g in U if g['per'].get('10') is not None]
for tag, S in (('all-with-t10', U3), ('no-143644', [g for g in U3 if '143644' not in g['file']])):
    for g in S:
        g['to'] = (g['total']['sell']+g['total']['refresh'])/len(g['per'])
        g['rr'] = g['total']['refresh']/len(g['per'])
    med=p50([g['to'] for g in S]); hi=[g for g in S if g['to']>med]; lo=[g for g in S if g['to']<=med]
    print(f'{tag}: n={len(S)} med_to={med:.2f} high p50_t15={p50([g["t15"] for g in hi]):.0f} (n={len(hi)}) '
          f'low p50_t15={p50([g["t15"] for g in lo]):.0f} (n={len(lo)}) '
          f'rho(t15)={sp([g["to"] for g in S],[g["t15"] for g in S]):+.2f} rho(t10)={sp([g["to"] for g in S],[g["per"]["10"] for g in S]):+.2f}')
    print(f'   refresh-rate: rho(t15)={sp([g["rr"] for g in S],[g["t15"] for g in S]):+.2f} rho(t10)={sp([g["rr"] for g in S],[g["per"]["10"] for g in S]):+.2f}')
wins=[g for g in U if g['placement']==1]
print('winners p50 t15 by turnover hi/lo:', )
to=[( (g['total']['sell']+g['total']['refresh'])/len(g['per']), g['t15']) for g in wins]
print('  ', [(round(a,1), round(b)) for a,b in sorted(to)])

print('\n=== C4 extras ===')
for ti in (4,5,6):
    gs=[g for g in U if g['tier9']==ti]
    print(f' t9tier={ti}: n={len(gs)} Sig@t9 p50={p50([g["per"]["9"] for g in gs]):.0f} '
          f'Sig@t10 p50={p50([g["per"]["10"] for g in gs if g["per"].get("10") is not None]):.0f} '
          f'wins={sum(1 for g in gs if g["placement"]==1)} t15_p50={p50([g["t15"] for g in gs]):.0f}')
print(' first turn reaching tier6:', sorted((next((int(t) for t,v in sorted(g["tiers"].items(), key=lambda kv:int(kv[0])) if v>=6), None), g['file'][11:23]) for g in U))
print(' first turn reaching tier5:', sorted((next((int(t) for t,v in sorted(g["tiers"].items(), key=lambda kv:int(kv[0])) if v>=5), None), g['file'][11:23]) for g in U))

print('\n=== C5 extras ===')
CORE=('BG29_813','BG36_245','BG36_640')
core=[g for g in U if any(c in g['chain_first'] for c in CORE)]
mn=[min(g['chain_first'][c] for c in CORE if c in g['chain_first']) for g in core]
print(' core min-turn per game:', sorted(mn), 'p50=', p50(mn))
print(' core games t15:', [(g['file'][11:23], round(g['t15']), min(g['chain_first'][c] for c in CORE if c in g['chain_first'])) for g in core])
hm=[]
for g in core:
    hf={}
    for c in CORE:
        if c in g['chain_hand']: hf[c]=g['chain_hand'][c]
    if hf: hm.append((g['file'][11:23], min(hf.values()), hf))
print(' core hand-first:', hm)
