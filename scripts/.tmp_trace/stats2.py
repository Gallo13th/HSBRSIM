import json, os
import numpy as np
ROOT = '/home/data/users/gaoletian/projects/HSBRSIM'
G = json.load(open(os.path.join(ROOT, '.tmp_trace/games.json')))['games']

# duplicate seconds check
for g in G:
    if '1234' in g['file']:
        print('seed1234 file', g['file'][11:35], 'seconds', g['seconds'], 'decisions', g['decisions'], 'hash', g['hash'])
seen, U = set(), []
for g in G:
    if g['hash'] in seen: continue
    seen.add(g['hash']); U.append(g)

def p50(xs):
    xs = sorted(xs); n = len(xs)
    if n == 0: return float('nan')
    return xs[n//2] if n % 2 else 0.5*(xs[n//2-1]+xs[n//2])

print('\n=== Sigma by tier at fixed turns (pooled over games) ===')
for t in (6, 7, 8, 9, 10, 11, 12):
    bys = {}
    for g in U:
        s = g['per'].get(str(t)); ti = g['tiers'].get(str(t))
        if s is None or ti is None: continue
        bys.setdefault(ti, []).append(s)
    print(f't={t}: ' + '  '.join(f'n{tier}={len(v)} p50={p50(v):.0f}' for tier, v in sorted(bys.items())))

print('\n=== d0: Sigma(t)-Sigma(t-1) during turn (upgrade turn vs control) ===')
rows = []
for g in U:
    ts = sorted(int(t) for t in g['per'])
    for t in ts:
        if t < 3: continue
        d = g['turn'][str(t)]
        pm = g['per'].get(str(t-1)); nx = g['per'].get(str(t+1)); n2 = g['per'].get(str(t+2))
        rows.append({'f': g['file'][11:23], 't': t, 'upg': d['upg'] > 0, 'buy': d['buy'],
                     'sig': d['sig'], 'd0': (d['sig']-pm) if pm is not None else None,
                     'd1': (nx-d['sig']) if nx is not None else None,
                     'd01': (nx-pm) if (nx is not None and pm is not None) else None})
for t in range(4, 13):
    u = [r['d0'] for r in rows if r['t'] == t and r['upg'] and r['d0'] is not None]
    c = [r['d0'] for r in rows if r['t'] == t and not r['upg'] and r['d0'] is not None]
    if u or c:
        print(f'  t={t:2d} d0 upg n={len(u)} med={p50(u) if u else float("nan"):7.0f} | ctrl n={len(c)} med={p50(c) if c else float("nan"):7.0f}')
ut = [r for r in rows if r['upg'] and r['d01'] is not None]
ct = [r for r in rows if not r['upg'] and r['d01'] is not None]
print(f'  d0 (upg turn itself) t>=5: upg p50={p50([r["d0"] for r in rows if r["upg"] and r["d0"] is not None and r["t"]>=5]):.0f} '
      f'ctrl p50={p50([r["d0"] for r in rows if not r["upg"] and r["d0"] is not None and r["t"]>=5]):.0f}')
print(f'  d0+d1 = Sig(t+1)-Sig(t-1) (2-turn window) t>=5: upg p50={p50([r["d01"] for r in ut if r["t"]>=5]):.0f} '
      f'ctrl p50={p50([r["d01"] for r in ct if r["t"]>=5]):.0f}')
# matched: upgrades happen at t5-8 mostly -> compare only t in 5..8
for lo, hi in ((5, 8),):
    u = [r['d01'] for r in ut if lo <= r['t'] <= hi]; c = [r['d01'] for r in ct if lo <= r['t'] <= hi]
    print(f'  matched t{lo}-{hi}: upg n={len(u)} p50={p50(u):.0f} | ctrl n={len(c)} p50={p50(c):.0f}')

print('\n=== per-turn upgrade rate ===')
print('games: ', [(g['file'][11:23], g['tier_final'], g['tier9']) for g in U])

print('\n=== C3 without extreme game ===')
U2 = [g for g in U if '143644' not in g['file']]
def rank(xs):
    o = sorted(range(len(xs)), key=lambda i: xs[i]); r=[0.]*len(xs); i=0
    while i < len(o):
        j=i
        while j+1 < len(o) and xs[o[j+1]]==xs[o[i]]: j+=1
        for k in range(i,j+1): r[o[k]] = (i+j)/2.+1
        i=j+1
    return r
def sp(x,y):
    rx,ry=rank(x),rank(y); mx=sum(rx)/len(rx); my=sum(ry)/len(ry)
    num=sum((a-mx)*(b-my) for a,b in zip(rx,ry))
    den=(sum((a-mx)**2 for a in rx)*sum((b-my)**2 for b in ry))**.5
    return num/den if den else float('nan')
for g in U2:
    g['turnover'] = (g['total']['sell']+g['total']['refresh'])/len(g['per'])
    g['refrate'] = g['total']['refresh']/len(g['per'])
med = p50([g['turnover'] for g in U2])
hi=[g for g in U2 if g['turnover']>med]; lo=[g for g in U2 if g['turnover']<=med]
print(f'turnover(no 143644) med={med:.2f} high n={len(hi)} p50={p50([g["t15"] for g in hi]):.0f} | low n={len(lo)} p50={p50([g["t15"] for g in lo]):.0f}')
print('spearman turnover vs t15:', round(sp([g['turnover'] for g in U2],[g['t15'] for g in U2]),3),
      'vs t10:', round(sp([g['turnover'] for g in U2],[g['per']['10'] for g in U2]),3))
wins=[g for g in U if g['placement']==1]
print('winners only: turnover', [(g['file'][11:23], round((g['total']['sell']+g['total']['refresh'])/len(g['per']),1), round(g['t15'])) for g in sorted(wins,key=lambda x:(x['total']['sell']+x['total']['refresh'])/len(x['per']))])
print('spearman turnover vs t15 (winners):', round(sp([(g['total']['sell']+g['total']['refresh'])/len(g['per']) for g in wins],[g['t15'] for g in wins]),3))
print('spearman sellcount vs t15 (all):', round(sp([g['total']['sell'] for g in U],[g['t15'] for g in U]),3))
print('spearman refresh vs t15 (all):', round(sp([g['total']['refresh'] for g in U],[g['t15'] for g in U]),3))
print('\n=== C4 extras: Sigma at t9 by tier9, wins ===')
for ti in (4,5,6):
    gs=[g for g in U if g['tier9']==ti]
    print(f' t9tier={ti}: n={len(gs)} Sig@t9 p50={p50([g["per"]["9"] for g in gs]):.0f} '
          f'Sig@t10 p50={p50([g["per"]["10"] for g in gs if g["per"].get("10") is not None]):.0f} '
          f'wins={sum(1 for g in gs if g["placement"]==1)}')
print(' tier reach t6 by turn:', {g['file'][11:23]: [t for t,v in sorted(g['tiers'].items(), key=lambda kv:int(kv[0])) if v>=6][:1] for g in U})
