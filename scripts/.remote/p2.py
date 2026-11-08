#!/usr/bin/env python3
import json, sys
sys.path.insert(0, '/home/data/users/gaoletian/projects/HSBRSIM')
import hsbg_engine as E

car = json.load(open('data/scaling/carriers.json', encoding='utf-8'))
prim = set(car['primary_ids'])
print('== primary carriers (%d) ==' % len(prim))
for c in car['carriers']:
    if c['id'] in prim:
        print(f"  {c['id']:16s} {c['name'][:34]:36s} t{c['tier']} {','.join(c['races']):12s} {c['trigger']:14s} | {c['text'][:100]}")

cat = {c['id']: c for c in json.loads(E.catalog_json())}
comps = json.load(open('data/scaling/comps_top.json', encoding='utf-8'))['comps']
print('\n== core card engine status ==')
for c in comps:
    rows = []
    for x in c.get('core_cards') or []:
        cc = cat.get(x['id'])
        if not cc:
            rows.append(f"{x['id']} MISSING")
        else:
            rows.append(f"{x['id']} impl={cc.get('implemented')} pool={cc.get('in_pool')} reach={cc.get('reachable')} races={cc.get('races')}")
    print(f"{c['archetype']:26s} | " + ' ; '.join(rows))

print('\n== ALL-type cards ==')
for cid, c in cat.items():
    if 'ALL' in (c.get('races') or []) and c.get('kind') == 'minion':
        print(f"  {cid:16s} {c.get('name')[:34]:36s} t{c.get('tier')} in_pool={c.get('in_pool')} impl={c.get('implemented')} | {(c.get('text') or '')[:80]}")
