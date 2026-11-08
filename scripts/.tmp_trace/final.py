"""Final: 5 claims vs unique human replays. Writes runs/human_play/trace_check.json.

Sigma = sum over board of (atk+hp) in TRUE stat units (obs stores atk/hp * 0.1,
so multiply by 10 -- matches demo_index.json / ECONOMY_CEILING.md scale).
"""
import gzip, json, glob, os, sys, hashlib
from collections import Counter
import numpy as np

ROOT = '/home/data/users/gaoletian/projects/HSBRSIM'
for p in (ROOT, os.path.join(ROOT, 'rust', 'python')):
    if p not in sys.path:
        sys.path.insert(0, p)
import hsbg.env.obs_std as O
import hsbg_engine as E

PLAY = os.path.join(ROOT, 'runs/human_play')
NB, MF, B0 = 7, 31, O.SLICE_BOARD.start
SCALE = 10.0            # obs �?minion atk/hp 为真实�?/10
CHAIN = ('BG21_015', 'BG29_813', 'BG36_245', 'BG36_640')
CORE = ('BG29_813', 'BG36_245', 'BG36_640')   # t4/t5/t6 核心（塔�?= t2 起步卡）
C2I = {int(c['cid']): str(c['id']) for c in json.loads(E.catalog_json())}
norm = lambda c: c[:-2] if c.endswith('_G') else c


def parse(path):
    recs = [json.loads(l) for l in gzip.open(path, 'rt', encoding='utf-8')]
    dec = [r for r in recs if r.get('type') == 'decision' and r.get('phase') == 'recruit']
    summ = [r for r in recs if r.get('type') == 'summary']
    if not dec or not summ:
        return None
    T, bfirst, hfirst = {}, {}, {}
    for r in dec:
        t = int(r['turn']); fl = np.asarray(r['features'], dtype=np.float32)
        b = fl[B0:B0 + NB * MF].reshape(NB, MF)
        pres = b[:, 0] > 0.5
        sig = float(np.where(pres, b[:, 1] + b[:, 2], 0.0).sum()) * SCALE
        ca = np.asarray(r['cards'], dtype=np.int64)
        bid = [norm(C2I.get(int(x) - 1, '')) for x in ca[O.CARD_BLOCK_SLICES['card_board'].start:O.CARD_BLOCK_SLICES['card_board'].stop] if int(x) > 0]
        hid = [norm(C2I.get(int(x) - 1, '')) for x in ca[O.CARD_BLOCK_SLICES['card_hand'].start:O.CARD_BLOCK_SLICES['card_hand'].stop] if int(x) > 0]
        for c in bid:
            if c in CHAIN: bfirst.setdefault(c, t)
        for c in hid:
            if c in CHAIN: hfirst.setdefault(c, t)
        d = T.setdefault(t, {'t': t, 'tier0': int(r['tier']), 'tier_end': int(r['tier']),
                             'gold0': int(r.get('gold') or 0), 'sig': 0.0,
                             'buy': 0, 'sell': 0, 'refresh': 0, 'upg': 0, 'play': 0, 'golden': 0})
        d['sig'] = max(d['sig'], sig)
        d['tier_end'] = max(d['tier_end'], int(r['tier']))
        d['golden'] = max(d['golden'], int((b[:, 5] > 0.5).sum()))
        a = int(r.get('action') or 0)
        if 8 <= a < 16: d['buy'] += 1
        elif 16 <= a < 24: d['sell'] += 1
        elif a == 1: d['refresh'] += 1
        elif a == 3: d['upg'] += 1
        elif 46 <= a < 110: d['play'] += 1
    key = json.dumps([[t, d['tier_end'], d['buy'], d['sell'], d['refresh'], d['upg'], d['play']] for t, d in sorted(T.items())])
    h = hashlib.md5((str(recs[0].get('seed')) + key).encode()).hexdigest()[:10]
    tmax = max(T); per = {t: round(d['sig'], 1) for t, d in T.items()}
    tiers = {t: d['tier_end'] for t, d in T.items()}
    return {'file': os.path.basename(path), 'seed': int(recs[0].get('seed') or 0), 'hash': h,
            'placement': summ[0].get('placement'), 'turns': int(summ[0].get('turns') or tmax),
            'seconds': round(float(summ[0].get('seconds') or 0), 1), 'decisions': len(dec),
            'tmax': tmax, 'per': per, 'tiers': tiers,
            't15': per.get(15, per[tmax]), 't15_fallback': 15 not in per,
            'peak': max(per.values()), 'tier9': tiers.get(9), 'tier_final': tiers[tmax],
            'turn': T, 'chain_board_first': bfirst, 'chain_hand_first': hfirst,
            'total': {k: sum(d[k] for d in T.values()) for k in ('buy', 'sell', 'refresh', 'upg', 'play')}}


def p50(xs):
    xs = sorted(xs); n = len(xs)
    return None if n == 0 else (xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2]))


def rank(xs):
    o = sorted(range(len(xs)), key=lambda i: xs[i]); r = [0.] * len(xs); i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and xs[o[j + 1]] == xs[o[i]]: j += 1
        for k in range(i, j + 1): r[o[k]] = (i + j) / 2. + 1
        i = j + 1
    return r


def sp(x, y):
    rx, ry = rank(x), rank(y); mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** .5
    return None if not den else num / den


files = sorted(glob.glob(os.path.join(PLAY, 'human_*.jsonl.gz')))
parsed = [g for g in (parse(p) for p in files) if g]
seen, U = set(), []
for g in parsed:
    if g['hash'] in seen: continue
    seen.add(g['hash']); U.append(g)
tmp = {}
for g in parsed: tmp.setdefault(g['hash'], []).append(g['file'])
dup = {h: v for h, v in tmp.items() if len(v) > 1}

for g in U:
    g['nturn'] = len(g['per'])
    g['turnover'] = (g['total']['sell'] + g['total']['refresh']) / g['nturn']
    g['sellrate'] = g['total']['sell'] / g['nturn']
    g['refrate'] = g['total']['refresh'] / g['nturn']
    g['upg_turns'] = [t for t, d in g['turn'].items() if d['upg'] > 0]

rows = []
for g in U:
    for t, d in g['turn'].items():
        if t < 2: continue
        f = g['per']
        rows.append({'f': g['file'], 't': t, 'upg': d['upg'] > 0, 'buy': d['buy'], 'gold': d['gold0'],
                     'sig': d['sig'], 'tier': d['tier_end'],
                     'd0': d['sig'] - f[t - 1] if (t - 1) in f else None,
                     'd1': f[t + 1] - d['sig'] if (t + 1) in f else None,
                     'd2': f[t + 2] - d['sig'] if (t + 2) in f else None})
up = [r for r in rows if r['upg']]; ct = [r for r in rows if not r['upg']]

out = {'source': 'runs/human_play/*.jsonl.gz', 'scale_note': 'Sigma = sum(atk+hp) true units (obs x0.1)',
       'n_files': len(files), 'n_parsed': len(parsed), 'n_unique': len(U),
       'n_wins_pl1': sum(1 for g in U if g['placement'] == 1),
       'duplicates': {k: {'n': len(v), 'files': v} for k, v in dup.items()},
       'defs': {'sigma': 'sum over board of (MINION_ATK+MINION_HP), max within turn, x10',
                't15': 'turn 15 Sigma; last turn if game ended earlier',
                'tier9': 'tier at END of turn 9', 'final_tier': 'tier at end of last recruit turn',
                'upgrade_turn': 'recruit turn containing action Upgrade(3)',
                'turnover': '(#Sell + #Refresh) / #recruit turns',
                'chain_board_first': 'first turn the card is on board (any decision in turn)'}}
print(f"files={len(files)} parsed={len(parsed)} unique={len(U)} wins={out['n_wins_pl1']}")
print('dup:', {k: len(v) for k, v in dup.items()},
      '| t15 fallback:', sum(1 for g in U if g['t15_fallback']), '/', len(U),
      '| reach t15:', sum(1 for g in U if g['tmax'] >= 15))

# ---------------- C1 ----------------
c1 = {'by_final_tier': {}, 'sigma_by_tier_at_turn': {}, 'group_t6_vs_le5': {}}
for tier in sorted({g['tier_final'] for g in U}):
    gs = [g for g in U if g['tier_final'] == tier]
    c1['by_final_tier'][tier] = {'n': len(gs), 'sigma15_p50': p50([g['t15'] for g in gs]),
                                 'sigma15_min': min(g['t15'] for g in gs), 'sigma15_max': max(g['t15'] for g in gs),
                                 'tmax': [g['tmax'] for g in gs]}
hi = [g for g in U if g['tier_final'] >= 6]; lo = [g for g in U if g['tier_final'] <= 5]
c1['group_t6_vs_le5'] = {'t6_n': len(hi), 't6_p50': p50([g['t15'] for g in hi]),
                         'le5_n': len(lo), 'le5_p50': p50([g['t15'] for g in lo]),
                         'le5_values': [round(g['t15']) for g in lo]}
for t in (8, 9, 10, 11, 12):
    bys = {}
    for g in U:
        s, ti = g['per'].get(t), g['tiers'].get(t)
        if s is None or ti is None: continue
        bys.setdefault(ti, []).append(s)
    c1['sigma_by_tier_at_turn'][t] = {ti: {'n': len(v), 'p50': p50(v)} for ti, v in bys.items()}
c1['spearman_final_tier_t15'] = sp([g['tier_final'] for g in U], [g['t15'] for g in U])
c1['sigma15_p50_all'] = p50([g['t15'] for g in U])
c1['sigma15_p50_reach15'] = p50([g['t15'] for g in U if g['tmax'] >= 15])
out['C1_upgrade_hurts_board'] = c1
print('\nC1 by final_tier:', {k: (v['n'], round(v['sigma15_p50'])) for k, v in c1['by_final_tier'].items()},
      'rho=', round(c1['spearman_final_tier_t15'], 2), '| T6 vs <=5:', c1['group_t6_vs_le5'])
print('C1 sigma by tier@turn:', {t: {k: (v['n'], round(v['p50'])) for k, v in d.items()} for t, d in c1['sigma_by_tier_at_turn'].items()})

# ---------------- C2 ----------------
c2 = {'upgrade': {'n_turns': len(up), 'n_games': len({r['f'] for r in up}),
                  'buy_mean': float(np.mean([r['buy'] for r in up])), 'buy_p50': p50([r['buy'] for r in up]),
                  'gold_mean': float(np.mean([r['gold'] for r in up]))},
      'control': {'n_turns': len(ct), 'buy_mean': float(np.mean([r['buy'] for r in ct])), 'buy_p50': p50([r['buy'] for r in ct]),
                  'gold_mean': float(np.mean([r['gold'] for r in ct]))},
      'paired_buy_diff': {}, 'buy_matched': {}, 'delta_matched': {}, 'delta_by_turn': {}, 'triple_overlap': {}}
diffs = []
for g in U:
    a = [g['turn'][[t]['buy'] for t in range(5, 9) if str(t) in g['turn'] and g['turn'][[t]['upg'] > 0]
    b = [g['turn'][[t]['buy'] for t in range(5, 9) if str(t) in g['turn'] and g['turn'][[t]['upg'] == 0]
    if a and b: diffs.append(float(np.mean(a) - np.mean(b)))
c2['paired_buy_diff'] = {'window': 't5-8, per game', 'mean': float(np.mean(diffs)), 'n_games': len(diffs),
                         'n_negative': sum(1 for d in diffs if d < 0), 'values': [round(d, 2) for d in diffs]}
for lo_, hi_ in ((2, 2), (5, 8), (9, 12)):
    u = [g['turn'][t] for g in U for t in range(lo_, hi_ + 1) if str(t) in g['turn'] and g['turn'][[t]['upg'] > 0]
    c = [g['turn'][t] for g in U for t in range(lo_, hi_ + 1) if str(t) in g['turn'] and g['turn'][[t]['upg'] == 0]
    if u and c:
        c2['buy_matched'][f't{lo_}-{hi_}'] = {
            'upg_n': len(u), 'upg_buy_mean': float(np.mean([d['buy'] for d in u])), 'upg_gold_mean': float(np.mean([d['gold0'] for d in u])),
            'ctrl_n': len(c), 'ctrl_buy_mean': float(np.mean([d['buy'] for d in c])), 'ctrl_gold_mean': float(np.mean([d['gold0'] for d in c]))}
for t in range(4, 13):
    u = [r['d0'] for r in up if r['t'] == t and r['d0'] is not None]
    c = [r['d0'] for r in ct if r['t'] == t and r['d0'] is not None]
    c2['delta_by_turn'][t] = {'upg_n': len(u), 'upg_p50_d0': p50(u), 'ctrl_n': len(c), 'ctrl_p50_d0': p50(c)}
for key, col, lo_, hi_ in (('d0', 'd0', 5, 8), ('d1', 'd1', 5, 8), ('d2', 'd2', 5, 7)):
    u = [r[col] for r in up if r[col] is not None and lo_ <= r['t'] <= hi_]
    c = [r[col] for r in ct if r[col] is not None and lo_ <= r['t'] <= hi_]
    c2['delta_matched'][f'{key}_t{lo_}-{hi_}'] = {'upg_n': len(u), 'upg_p50': p50(u), 'ctrl_n': len(c), 'ctrl_p50': p50(c)}
c2['delta_matched']['d0_unmatched_t>=5'] = {'upg_p50': p50([r['d0'] for r in up if r['d0'] is not None and r['t'] >= 5]),
                                            'ctrl_p50': p50([r['d0'] for r in ct if r['d0'] is not None and r['t'] >= 5])}
c2['delta_matched']['d1_unmatched_t>=5'] = {'upg_p50': p50([r['d1'] for r in up if r['d1'] is not None and r['t'] >= 5]),
                                            'ctrl_p50': p50([r['d1'] for r in ct if r['d1'] is not None and r['t'] >= 5])}
gev = []
for g in U:
    prev = 0
    for t, d in sorted(g['turn'].items()):
        if d['golden'] > prev: gev.append((g['file'], t, d['upg'] > 0))
        prev = d['golden']
c2['triple_overlap'] = {'n_gold_events': len(gev), 'on_upgrade_turn': sum(1 for e in gev if e[2]),
                        'upgrade_turn_share': len(up) / len(rows), 'events': [[e[0], e[1], e[2]] for e in gev]}
c2['upg_turns_by_t'] = {str(k): v for k, v in sorted(Counter(r['t'] for r in up).items())}
out['C2_trilemma'] = c2
print('\nC2 buy/turn upg', round(c2['upgrade']['buy_mean'], 2), 'vs ctrl', round(c2['control']['buy_mean'], 2),
      '| paired t5-8', round(float(np.mean(diffs)), 2), f'neg {sum(1 for d in diffs if d < 0)}/{len(diffs)}')
print('C2 buy matched:', {k: (round(v['upg_buy_mean'], 2), round(v['ctrl_buy_mean'], 2), round(v['upg_gold_mean'], 1), round(v['ctrl_gold_mean'], 1)) for k, v in c2['buy_matched'].items()})
print('C2 delta matched:', {k: (None if v['upg_p50'] is None else round(v['upg_p50']), None if v['ctrl_p50'] is None else round(v['ctrl_p50'])) for k, v in c2['delta_matched'].items()})
print('C2 triple events on upg turn', c2['triple_overlap']['on_upgrade_turn'], '/', len(gev), 'baseline', round(len(up) / len(rows), 2))
print('C2 upg turns by t', c2['upg_turns_by_t'])

# ---------------- C3 ----------------
c3 = {'median_split': {}, 'spearman': {}, 'per_game': []}
for key in ('turnover', 'sellrate', 'refrate'):
    med = p50([g[key] for g in U])
    hi_ = [g for g in U if g[key] > med]; lo_ = [g for g in U if g[key] <= med]
    c3['median_split'][key] = {'median': med, 'high_n': len(hi_), 'high_sigma15_p50': p50([g['t15'] for g in hi_]),
                               'low_n': len(lo_), 'low_sigma15_p50': p50([g['t15'] for g in lo_]),
                               'high_values': [round(g['t15']) for g in hi_], 'low_values': [round(g['t15']) for g in lo_]}
    c3['spearman'][key] = {'vs_t15': sp([g[key] for g in U], [g['t15'] for g in U]),
                           'vs_t10': sp([g[key] for g in U if g['per'].get(10) is not None],
                                        [g['per'][10] for g in U if g['per'].get(10) is not None])}
U2 = [g for g in U if '143644' not in g['file']]
med = p50([g['turnover'] for g in U2])
hi_ = [g for g in U2 if g['turnover'] > med]; lo_ = [g for g in U2 if g['turnover'] <= med]
c3['ex_extreme_143644'] = {'n': len(U2), 'median': med, 'high_n': len(hi_), 'high_sigma15_p50': p50([g['t15'] for g in hi_]),
                           'low_n': len(lo_), 'low_sigma15_p50': p50([g['t15'] for g in lo_]),
                           'spearman_t15': sp([g['turnover'] for g in U2], [g['t15'] for g in U2])}
c3['per_game'] = [{'file': g['file'], 'turnover': round(g['turnover'], 2), 'sell': g['total']['sell'],
                   'refresh': g['total']['refresh'], 'nturn': g['nturn'], 'sigma15': round(g['t15'], 1),
                   'placement': g['placement']} for g in sorted(U, key=lambda x: x['turnover'])]
out['C3_turnover'] = c3
print('\nC3 split:', {k: (round(v['high_sigma15_p50']), round(v['low_sigma15_p50']), round(v['median'], 2)) for k, v in c3['median_split'].items()})
print('C3 rho:', {k: (round(v['vs_t15'], 2), round(v['vs_t10'], 2)) for k, v in c3['spearman'].items()})
print('C3 no-extreme:', {k: (round(v) if isinstance(v, float) and v > 1 else v) for k, v in c3['ex_extreme_143644'].items()})
print('C3 per-game:', [(x['file'][11:23], x['turnover'], x['sigma15']) for x in c3['per_game']])

# ---------------- C4 ----------------
c4 = {'wins': {}, 'nonwins': {}, 'by_t9_tier': {}, 'low_tier_games': []}
w = [g for g in U if g['placement'] == 1]; l = [g for g in U if g['placement'] != 1]
c4['wins']['t9_tier_counts'] = {str(k): v for k, v in sorted(Counter(g['tier9'] for g in w if g['tier9']).items())}
c4['nonwins']['t9_tier_counts'] = {str(k): v for k, v in sorted(Counter(g['tier9'] for g in l if g['tier9']).items())}
c4['wins']['n_ge5'] = sum(1 for g in w if g['tier9'] and g['tier9'] >= 5)
for ti in (4, 5, 6):
    gs = [g for g in U if g['tier9'] == ti]
    if gs:
        c4['by_t9_tier'][ti] = {'n': len(gs), 'wins': sum(1 for g in gs if g['placement'] == 1),
                                'sigma9_p50': p50([g['per'][9] for g in gs]),
                                'sigma10_p50': p50([g['per'][10] for g in gs if g['per'].get(10) is not None]),
                                'sigma15_p50': p50([g['t15'] for g in gs]),
                                'placements': [g['placement'] for g in gs]}
c4['low_tier_games'] = [{'file': g['file'], 't9_tier': g['tier9'], 'placement': g['placement'],
                         'sigma15': round(g['t15']), 'final_tier': g['tier_final']}
                        for g in U if g['tier9'] and g['tier9'] <= 4]
out['C4_tier5_by_t9'] = c4
print('\nC4 wins t9 tiers:', c4['wins']['t9_tier_counts'], '| nonwins:', c4['nonwins']['t9_tier_counts'],
      '| wins>=5:', c4['wins']['n_ge5'], '/', len(w))
print('C4 by tier:', {k: (v['n'], v['wins'], round(v['sigma15_p50'])) for k, v in c4['by_t9_tier'].items()})
print('C4 low-tier:', c4['low_tier_games'])

# ---------------- C5 ----------------
c5 = {'games_with_any_chain': [], 'core_first_turns': [], 'groups': {}, 'tareg_turns': []}
withc = [g for g in U if g['chain_board_first']]
core = [g for g in U if any(c in g['chain_board_first'] for c in CORE)]
for g in withc:
    c5['games_with_any_chain'].append({'file': g['file'], 'placement': g['placement'],
                                       'board_first': g['chain_board_first'], 'hand_first': g['chain_hand_first'],
                                       'sigma15': round(g['t15'])})
c5['core_first_turns'] = sorted(g['chain_board_first'][c] for g in core for c in CORE if c in g['chain_board_first'])
c5['core_min_turn_per_game'] = sorted(min(g['chain_board_first'][c] for c in CORE if c in g['chain_board_first']) for g in core)
c5['core_hand_first'] = sorted(min(g['chain_hand_first'][c] for c in CORE if c in g['chain_hand_first']) for g in core if any(c in g['chain_hand_first'] for c in CORE))
c5['tareg_turns'] = sorted(g['chain_board_first']['BG21_015'] for g in U if 'BG21_015' in g['chain_board_first'])
c5['n_with_chain'] = len(withc); c5['n_with_core'] = len(core); c5['n_total'] = len(U)
for name, sel in (('core_chain', core), ('no_chain', [g for g in U if not g['chain_board_first']]),
                  ('tareg_only', [g for g in U if g['chain_board_first'] and not any(c in g['chain_board_first'] for c in CORE)])):
    if sel:
        c5['groups'][name] = {'n': len(sel), 'sigma15_p50': p50([g['t15'] for g in sel]),
                              'values': [round(g['t15']) for g in sel]}
c5['spearman_core_turn_sigma15'] = sp([min(g['chain_board_first'][c] for c in CORE if c in g['chain_board_first']) for g in core],
                                      [g['t15'] for g in core])
out['C5_chain_timing'] = c5
print('\nC5 chain games:', [(x['file'][11:23], x['board_first'], x['sigma15']) for x in c5['games_with_any_chain']])
print('C5 core first turns:', c5['core_first_turns'], '| min/game:', c5['core_min_turn_per_game'], '| hand:', c5['core_hand_first'])
print('C5 groups:', {k: (v['n'], round(v['sigma15_p50'])) for k, v in c5['groups'].items()})
print('C5 tareg turns:', c5['tareg_turns'], '| rho(core turn, sig15):', round(c5['spearman_core_turn_sigma15'], 3))

out['games'] = [{'file': g['file'], 'seed': g['seed'], 'placement': g['placement'], 'turns': g['turns'],
                 'tmax': g['tmax'], 'decisions': g['decisions'], 'seconds': g['seconds'],
                 't9_tier': g['tier9'], 'final_tier': g['tier_final'],
                 'sigma15': round(g['t15'], 1), 'sigma15_fallback': g['t15_fallback'],
                 'peak': round(g['peak'], 1), 'turnover': round(g['turnover'], 2),
                 'sell': g['total']['sell'], 'refresh': g['total']['refresh'], 'buy': g['total']['buy'],
                 'upgrade_turns': g['upg_turns'], 'chain_board_first': g['chain_board_first'],
                 'chain_hand_first': g['chain_hand_first'],
                 'sig_by_turn': {str(k): round(v, 1) for k, v in g['per'].items()},
                 'tier_by_turn': {str(k): v for k, v in g['tiers'].items()},
                 'buy_by_turn': {str(k): d['buy'] for k, d in g['turn'].items()}} for g in U]
json.dump(out, open(os.path.join(PLAY, 'trace_check.json'), 'w'), ensure_ascii=False, indent=1)
print('\nwrote', os.path.join(PLAY, 'trace_check.json'))

