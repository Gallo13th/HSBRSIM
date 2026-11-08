#!/usr/bin/env python3
import json, sys
d = json.load(open('data/scaling/comps_top.json', encoding='utf-8'))
print('TOP KEYS:', list(d.keys()))
for k, v in d.items():
    if isinstance(v, list):
        print(f'  {k}: list[{len(v)}]')
    elif isinstance(v, dict):
        print(f'  {k}: dict keys={list(v.keys())[:12]}')
c = d.get('comps') or d.get('items') or []
print('n comps', len(c))
if c:
    print(json.dumps(c[0], ensure_ascii=False, indent=1)[:4000])
