import gzip, json, os, sys
import numpy as np
ROOT = '/home/data/users/gaoletian/projects/HSBRSIM'
for p in (ROOT, os.path.join(ROOT, 'rust', 'python')):
    if p not in sys.path: sys.path.insert(0, p)
import hsbg.env.obs_std as O
import hsbg_engine as E

C2I = {int(c['cid']): str(c['id']) for c in json.loads(E.catalog_json())}
cards = json.load(open(os.path.join(ROOT, 'data/p2/cards_37.json')))
cards = cards if isinstance(cards, list) else (cards.get('cards') or cards.get('data'))
db = {c['id']: c for c in cards if isinstance(c, dict) and c.get('id')}
for cid in ('BG21_015', 'BG29_813', 'BG36_245', 'BG36_640', 'BG21_015_G', 'BG36_640_G'):
    c = db.get(cid)
    print(cid, '->', (c or {}).get('name'), 'tier', (c or {}).get('tier'), 'atk/hp', (c or {}).get('attack'), (c or {}).get('health'),
          '| races', (c or {}).get('races'))
print('N_CARDS', E.N_CARDS)

p = os.path.join(ROOT, 'runs/human_play/human_20261103-100337_seed671417_04.jsonl.gz')
rec = [json.loads(l) for l in gzip.open(p, 'rt')]
B0 = O.SLICE_BOARD.start
cur = None
for r in rec:
    if r.get('type') != 'decision' or r.get('phase') != 'recruit': continue
    if r['turn'] != cur:
        cur = r['turn']; fl = np.asarray(r['features'], dtype=np.float32)
        b = fl[B0:B0+7*31].reshape(7, 31)
        ca = np.asarray(r['cards'], dtype=np.int64)
        bs = ca[O.CARD_BLOCK_SLICES['card_board'].start:O.CARD_BLOCK_SLICES['card_board'].stop]
        ids = [(C2I.get(int(x)-1, '?'), round(float(b[i][1]),1), round(float(b[i][2]),1), round(float(b[i][4]),1))
               for i, x in enumerate(bs) if int(x) > 0]
        print(f"T{cur} tier={r['tier']} gold={r['gold']} board={ids}")
PY
