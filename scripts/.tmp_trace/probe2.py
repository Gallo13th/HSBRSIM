import gzip, json, glob, os
from collections import Counter
ROOT = '/home/data/users/gaoletian/projects/HSBRSIM'
acc = Counter(); byid = {}
for p in glob.glob(os.path.join(ROOT, 'runs/human_play/human_*.jsonl.gz')):
    for l in gzip.open(p, 'rt', encoding='utf-8'):
        r = json.loads(l)
        if r.get('type') == 'decision' and r.get('phase') == 'recruit':
            a = int(r['action']); acc[a] += 1
            byid.setdefault(a, str(r.get('action_name')))
print('action id -> name (n>=10):')
for a, n in sorted(acc.items()):
    if n >= 10: print(f'  {a:3d} {byid[a]:>16s} n={n}')
print('ids with <10:', {a: (byid[a], n) for a, n in sorted(acc.items()) if n < 10})

# one game raw turn detail
p = os.path.join(ROOT, 'runs/human_play/human_20261103-094032_seed670032_02.jsonl.gz')
rec = [json.loads(l) for l in gzip.open(p, 'rt')]
cur = None
for r in rec:
    if r.get('type') != 'decision' or r.get('phase') != 'recruit': continue
    if r['turn'] != cur:
        cur = r['turn']
        print(f"\nT{cur} tier={r['tier']} gold={r['gold']}")
    print(f"   a={r['action']:3d} {r['action_name']:>16s} gold={r['gold']} tier={r['tier']}")
