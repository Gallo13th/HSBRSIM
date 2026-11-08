"""Detailed stats for the 5 claims."""
import json, os, sys, glob, gzip, hashlib
import numpy as np

ROOT = '/home/data/users/gaoletian/projects/HSBRSIM'
G = json.load(open(os.path.join(ROOT, '.tmp_trace/games.json')))['games']

# --- exact duplicate check on full decision stream ---
def dec_hash(path):
    h = hashlib.md5()
    for l in gzip.open(path, 'rt', encoding='utf-8'):
        r = json.loads(l)
        if r.get('type') == 'decision':
            h.update(f"{r['turn']}|{r['action']}|{r['action_name']}|{r['tier']}|{r['gold']}|{r['phase']};".encode())
    return h.hexdigest()[:12]

for g in G:
    g['dhash'] = dec_hash(os.path.join(ROOT, 'runs/human_play', g['file']))
groups = {}
for g in G:
    groups.setdefault(g['dhash'], []).append(g['file'])
print('decision-stream dup groups:', {k: len(v) for k, v in groups.items() if len(v) > 1})

# dedupe: keep first file per decision hash
seen, U = set(), []
for g in G:
    if g['dhash'] in seen:
        continue
    seen.add(g['dhash']); U.append(g)
print(f'games: files={len(G)} unique={len(U)}  wins={sum(1 for g in U if g["placement"] == 1)}')
print('tmax:', sorted(g['tmax'] for g in U))
print('t15 fallback games:', sum(1 for g in U if g['t15_fallback']), '/', len(U))


def p50(xs):
    xs = sorted(xs); n = len(xs)
    if n == 0: return float('nan')
    return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])


def stat(xs):
    return f'n={len(xs)} p50={p50(xs):.0f} [{min(xs):.0f},{max(xs):.0f}]'


def rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs); i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(x, y):
    rx, ry = rank(x), rank(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** .5
    return num / den if den else float('nan')


print('\n================ C1: final_tier vs t15 Sigma ================')
for tier in sorted({g['tier_final'] for g in U}):
    gs = [g for g in U if g['tier_final'] == tier]
    print(f'tier={tier}: {stat([g["t15"] for g in gs])}  tmax={[g["tmax"] for g in gs]}  '
          f't9tier={[g["tier9"] for g in gs]}')
    s10 = [g['per'].get('10') for g in gs if g['per'].get('10') is not None]
    if s10: print(f'    Sigma@t10: {stat(s10)}')
print('all:', stat([g['t15'] for g in U]))
print('only tmax>=15:', stat([g['t15'] for g in U if g['tmax'] >= 15]))
print('spearman(final_tier, t15)=', round(spearman([g['tier_final'] for g in U], [g['t15'] for g in U]), 3))

print('\n================ C2: upgrade turn vs not ================')
rows = []
for g in U:
    ts = sorted(int(t) for t in g['per'])
    for t in ts:
        if t < 2: continue
        d = g['turn'][str(t)]
        nxt = g['per'].get(str(t + 1)); nxt2 = g['per'].get(str(t + 2))
        rows.append({'g': g['file'][11:23], 't': t, 'upg': d['upg'] > 0, 'buy': d['buy'],
                     'gold': d['gold0'], 'tier': d['tier0'], 'sig': d['sig'], 'sell': d['sell'],
                     'refresh': d['refresh'], 'golden': d['golden'],
                     'd1': (nxt - d['sig']) if nxt is not None else None,
                     'd2': ((nxt2 - d['sig']) / 2) if nxt2 is not None else None})
up = [r for r in rows if r['upg']]; ct = [r for r in rows if not r['upg']]
print(f'upgrade turns n={len(up)} games_with_upg={len({r["g"] for r in up})}/{len(U)}  '
      f'control turns n={len(ct)}')
for nm, sel in (('buy/turn', 'buy'), ('gold@start', 'gold')):
    print(f'  {nm}: upg mean={np.mean([r[sel] for r in up]):.2f} p50={p50([r[sel] for r in up]):.1f} | '
          f'ctrl mean={np.mean([r[sel] for r in ct]):.2f} p50={p50([r[sel] for r in ct]):.1f}')
# paired within game
diffs = []
for g in U:
    a = [r['buy'] for r in rows if r['g'] == g['file'][11:23] and r['upg']]
    b = [r['buy'] for r in rows if r['g'] == g['file'][11:23] and not r['upg'] and r['t'] >= 4]
    if a and b: diffs.append(np.mean(a) - np.mean(b))
print(f'  paired per-game buy diff (upg - ctrl, t>=4): mean={np.mean(diffs):+.2f} n={len(diffs)} '
      f'negative_games={sum(1 for d in diffs if d < 0)}/{len(diffs)}')
print('  upgrade turns by t:', {t: sum(1 for r in up if r['t'] == t) for t in sorted({r['t'] for r in up})})
print('\n  delta1 (Sigma(t+1)-Sigma(t)) by turn index & upg:')
for t in range(4, 13):
    u = [r['d1'] for r in up if r['t'] == t and r['d1'] is not None]
    c = [r['d1'] for r in ct if r['t'] == t and r['d1'] is not None]
    if u or c:
        print(f'   t={t:2d} upg n={len(u)} med={p50(u) if u else float("nan"):8.0f} | ctrl n={len(c)} med={p50(c) if c else float("nan"):8.0f}')
u1 = [r['d1'] for r in up if r['d1'] is not None and r['t'] >= 5]
c1 = [r['d1'] for r in ct if r['d1'] is not None and r['t'] >= 5]
print(f'  d1 t>=5: upg {stat(u1)} | ctrl {stat(c1)}')
u2 = [r['d2'] for r in up if r['d2'] is not None and r['t'] >= 5]
c2 = [r['d2'] for r in ct if r['d2'] is not None and r['t'] >= 5]
print(f'  d2=(Sig(t+2)-Sig(t))/2 t>=5: upg {stat(u2)} | ctrl {stat(c2)}')
# golden (triple) overlap
gold_ev = []
for g in U:
    ts = sorted(int(t) for t in g['per'])
    prev = 0
    for t in ts:
        gd = g['turn'][str(t)]['golden']
        if gd > prev: gold_ev.append((g['file'][11:23], t, g['turn'][str(t)]['upg']))
        prev = gd
print(f'  triple-completion events (golden count increments) n={len(gold_ev)}; same-turn upgrade '
      f'{sum(1 for e in gold_ev if e[2])}/{len(gold_ev)}')
print('   golden events:', gold_ev)

print('\n================ C3: turnover ================')
for g in U:
    nt = len(g['per'])
    g['turnover'] = (g['total']['sell'] + g['total']['refresh']) / nt
    g['sellrate'] = g['total']['sell'] / nt
    g['refrate'] = g['total']['refresh'] / nt
for key in ('turnover', 'sellrate', 'refrate'):
    med = p50([g[key] for g in U])
    hi = [g for g in U if g[key] > med]; lo = [g for g in U if g[key] <= med]
    print(f'{key}: med={med:.2f} high(n={len(hi)}) t15 {stat([g["t15"] for g in hi])} | '
          f'low(n={len(lo)}) t15 {stat([g["t15"] for g in lo])}')
    print(f'   spearman({key},t15)={spearman([g[key] for g in U],[g["t15"] for g in U]):+.3f} '
          f'spearman({key},t10)={spearman([g[key] for g in U if g["per"].get("10") is not None],[g["per"]["10"] for g in U if g["per"].get("10") is not None]):+.3f}')
print('  per game turnover/Sigma15:', [(g['file'][11:23], round(g['turnover'], 1), round(g['t15'])) for g in sorted(U, key=lambda x: x['turnover'])])

print('\n================ C4: t9 tier ================')
w = [g for g in U if g['placement'] == 1]; l = [g for g in U if g['placement'] != 1]
print('wins t9 tier:', sorted(g['tier9'] for g in w if g['tier9']))
print('non-wins t9 tier:', sorted(g['tier9'] for g in l if g['tier9']))
for tier in (4, 5, 6):
    gs = [g for g in U if g['tier9'] == tier]
    if gs:
        print(f'  t9 tier={tier}: n={len(gs)} wins={sum(1 for g in gs if g["placement"]==1)} '
              f't15 {stat([g["t15"] for g in gs])} placements={[g["placement"] for g in gs]}')
print('  t9 tier<=4:', [(g['file'][11:23], g['placement'], round(g['t15'])) for g in U if g['tier9'] and g['tier9'] <= 4])

print('\n================ C5: chain ================')
CHAIN = ('BG21_015', 'BG29_813', 'BG36_245', 'BG36_640')
CORE = ('BG29_813', 'BG36_245', 'BG36_640')
for g in U:
    hand_first = {}
    for t in sorted(g['per'], key=int):
        for c in g['turn'][t]['hand']:
            hand_first.setdefault(c, int(t))
    g['chain_hand'] = {c: hand_first[c] for c in CHAIN if c in hand_first}
for g in U:
    cf = g['chain_first']
    print(f"{g['file'][11:23]}: pl={g['placement']} t15={g['t15']:7.0f} tmax={g['tmax']:2d} "
          f"board_first={cf} hand_first={g['chain_hand']}")
withc = [g for g in U if g['chain_first']]
core = [g for g in U if any(c in g['chain_first'] for c in CORE)]
print(f'games with any chain card on board: {len(withc)}/{len(U)}; with core(T5/T6): {len(core)}/{len(U)}')
print('  core first-turn values:', sorted(g['chain_first'][c] for g in core for c in CORE if c in g['chain_first']))
print('  chain vs no-chain t15:', stat([g['t15'] for g in withc]), '|', stat([g['t15'] for g in U if not g['chain_first']]))
tareg = [g for g in U if 'BG21_015' in g['chain_first']]
print('  Tareg first turns:', sorted(g['chain_first']['BG21_015'] for g in tareg), 'n=', len(tareg))
