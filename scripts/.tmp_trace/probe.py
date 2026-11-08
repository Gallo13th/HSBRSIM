import gzip, json, glob, sys

p = 'runs/human_play/human_20261103-143644_seed687804_05.jsonl.gz'
print('FILE', p)
lines = gzip.open(p, 'rt').read().splitlines()
print('N lines', len(lines))
for i, ln in enumerate(lines[:3] + lines[-3:]):
    d = json.loads(ln)
    print('--- idx', i, 'keys:', list(d.keys()))
    for k, v in d.items():
        if isinstance(v, list):
            n = len(v)
            head = v[:8] if n and not isinstance(v[0], (list, dict)) else v[:2]
            print('   ', k, 'list', n, str(head)[:200])
        elif isinstance(v, dict):
            print('   ', k, 'dict', list(v.keys())[:25])
        else:
            print('   ', k, '=', repr(v)[:150])
