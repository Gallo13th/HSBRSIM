#!/usr/bin/env python3
import json, sys, collections
sys.path.insert(0, '/home/data/users/gaoletian/projects/HSBRSIM')
import hsbg_engine as E
cat = {c['id']: c for c in json.loads(E.catalog_json())}
print('flags', collections.Counter((c.get('implemented'), c.get('scripted'), c.get('in_pool')) for c in cat.values()).most_common(8))
print('races sample', [c.get('races') for c in cat.values() if c.get('kind')=='minion'][:10])
# minions with races
mr = collections.Counter()
for c in cat.values():
    if c.get('kind') == 'minion':
        for r in (c.get('races') or []):
            mr[r] += 1
print('race counts', mr.most_common(20))
# text search for "different type" / "types"
for c in cat.values():
    t = (c.get('text') or '').lower()
    if 'different type' in t or 'of each type' in t or 'all types' in t:
        print('TYPE-CARD', c['id'], c.get('name'), 't', c.get('tier'), '|', c.get('text'))
