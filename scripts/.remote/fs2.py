import json
import numpy as np
ROOT = '/home/data/users/gaoletian/projects/HSBRSIM'


def pct(v, q):
    return float(np.percentile(np.asarray(v, float), q)) if len(v) else 0.0


def score(eps):
    f = [e['final'] for e in eps]
    return pct(f, 50), pct(f, 90), max(f) if f else 0


for cfg, fn in (('bot', 'bot30.json'), ('human', 'human30.json')):
    d = json.load(open(f'{ROOT}/runs/comp_scripts/{fn}'))['configs'][cfg]
    base = json.load(open(f'{ROOT}/runs/comp_scripts/bot_baseline.json'))['configs'][cfg]['BOT']
    print('--- %s 终局 Σ (p50/p90/max) ---  BOT %.0f / %.0f / %.0f'
          % ((cfg,) + score(base['episodes'])))
    rows = [(*score(v['episodes']), k) for k, v in d.items()]
    for p50, p90, mx, k in sorted(rows, reverse=True):
        print('%-6s %6.0f / %6.0f / %6.0f' % (k, p50, p90, mx))
