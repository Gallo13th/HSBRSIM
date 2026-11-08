"""Human replay trace scan: per-game, per-turn board sum / tier / actions / chain."""
import gzip, json, glob, os, sys, hashlib
import numpy as np

ROOT = '/home/data/users/gaoletian/projects/HSBRSIM'
for p in (ROOT, os.path.join(ROOT, 'rust', 'python')):
    if p not in sys.path:
        sys.path.insert(0, p)
import hsbg.env.obs_std as O
import hsbg_engine as E

PLAY = os.path.join(ROOT, 'runs/human_play')
NB, MF = 7, 31
B0 = O.SLICE_BOARD.start

CHAIN = ('BG21_015', 'BG29_813', 'BG36_245', 'BG36_640')


def cid2id():
    return {int(c['cid']): str(c['id']) for c in json.loads(E.catalog_json())}


def norm(c):
    return c[:-2] if c.endswith('_G') else c


def analyze(path, cid2id_):
    recs = [json.loads(l) for l in gzip.open(path, 'rt', encoding='utf-8')]
    meta = recs[0]
    dec = [r for r in recs if r.get('type') == 'decision']
    summ = [r for r in recs if r.get('type') == 'summary']
    if not dec or not summ:
        return None
    rec = [r for r in dec if r.get('phase') == 'recruit']
    turns = {}
    for r in rec:
        t = int(r['turn']); fl = np.asarray(r['features'], dtype=np.float32)
        b = fl[B0:B0 + NB * MF].reshape(NB, MF)
        pres = b[:, 0] > 0.5
        sig = float(np.where(pres, b[:, 1] + b[:, 2], 0.0).sum())
        ca = np.asarray(r['cards'], dtype=np.int64)
        board_ids = [norm(cid2id_.get(int(x) - 1, '')) for x in
                     ca[O.CARD_BLOCK_SLICES['card_board'].start:O.CARD_BLOCK_SLICES['card_board'].stop]
                     if int(x) > 0]
        hand_ids = [norm(cid2id_.get(int(x) - 1, '')) for x in
                    ca[O.CARD_BLOCK_SLICES['card_hand'].start:O.CARD_BLOCK_SLICES['card_hand'].stop]
                    if int(x) > 0]
        d = turns.setdefault(t, {'t': t, 'tier0': int(r['tier']), 'gold0': int(r.get('gold') or 0),
                                 'sig': 0.0, 'n': 0, 'buy': 0, 'sell': 0, 'refresh': 0,
                                 'upg': 0, 'play': 0, 'acts': [], 'golden': 0,
                                 'board': [], 'hand': []})
        d['sig'] = max(d['sig'], sig)
        d['n'] += 1
        d['golden'] = max(d['golden'], int(pres.sum() and (b[:, 5] > 0.5).sum()))
        d['board'] = board_ids
        d['hand'] = hand_ids
        a = int(r.get('action') or 0)
        d['acts'].append((a, str(r.get('action_name') or '')))
        if 8 <= a < 16: d['buy'] += 1
        elif 16 <= a < 24: d['sell'] += 1
        elif a == 1: d['refresh'] += 1
        elif a == 3: d['upg'] += 1
        elif 46 <= a < 110: d['play'] += 1
    seq = tuple((t, d['buy'] + d['sell'] + d['refresh'] + d['upg'] + d['play'], d['tier0'])
                for t, d in sorted(turns.items()))
    h = hashlib.md5((meta.get('seed').__str__() + json.dumps(seq)).encode()).hexdigest()[:10]
    chain_first = {}
    for t, d in sorted(turns.items()):
        for c in d['board']:
            if c in CHAIN and c not in chain_first:
                chain_first[c] = t
    tiers = {t: d['tier0'] for t, d in turns.items()}
    per = {t: round(d['sig'], 0) for t, d in turns.items()}
    tmax = max(turns)
    t15 = per.get(15, per[tmax])
    return {
        'file': os.path.basename(path), 'seed': int(meta.get('seed') or 0),
        'hash': h, 'turns': int(summ[0].get('turns') or tmax),
        'placement': summ[0].get('placement'), 'decisions': len(rec),
        'seconds': summ[0].get('seconds'),
        'tmax': tmax, 't15': t15, 't15_fallback': 15 not in per,
        'tier9': tiers.get(9), 'tier_final': tiers[tmax], 'tier_max': max(tiers.values()),
        'peak': max(per.values()),
        'per': per, 'tiers': tiers,
        'turn': {str(t): {k: v for k, v in d.items() if k not in ('board', 'hand', 'acts')} | {
            'board': d['board'], 'hand': d['hand']}
                 for t, d in turns.items()},
        'chain_first': chain_first,
        'total': {'buy': sum(d['buy'] for d in turns.values()),
                  'sell': sum(d['sell'] for d in turns.values()),
                  'refresh': sum(d['refresh'] for d in turns.values()),
                  'upg': sum(d['upg'] for d in turns.values()),
                  'play': sum(d['play'] for d in turns.values())},
    }


def main():
    c2i = cid2id()
    games, skipped = [], []
    for p in sorted(glob.glob(os.path.join(PLAY, 'human_*.jsonl.gz'))):
        try:
            g = analyze(p, c2i)
        except Exception as e:
            skipped.append((os.path.basename(p), repr(e))); continue
        if g is None:
            skipped.append((os.path.basename(p), 'no decisions/summary')); continue
        games.append(g)
    print(f'files={len(glob.glob(os.path.join(PLAY, "human_*.jsonl.gz")))} parsed={len(games)} skipped={len(skipped)}')
    for s in skipped: print('  SKIP', s)
    seen = {}
    for g in games:
        seen.setdefault(g['hash'], []).append(g['file'])
    print(f'unique hashes={len(seen)}')
    for h, fs in seen.items():
        if len(fs) > 1: print('  DUP', h, len(fs), fs)
    for g in games:
        print(f"{g['file'][:46]:46s} seed={g['seed']:7d} pl={g['placement']} turns={g['turns']:2d} tmax={g['tmax']:2d} "
              f"tier9={g['tier9']} tierF={g['tier_final']} t15={g['t15']:7.0f} peak={g['peak']:7.0f} "
              f"buy={g['total']['buy']:3d} sell={g['total']['sell']:3d} ref={g['total']['refresh']:3d} upg={g['total']['upg']} "
              f"chain={g['chain_first']}")
    json.dump({'games': games}, open(os.path.join(ROOT, '.tmp_trace/games.json'), 'w'), indent=0)


if __name__ == '__main__':
    main()
