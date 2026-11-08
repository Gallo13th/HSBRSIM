#!/usr/bin/env python3
import json
d = json.load(open('data/scaling/carriers.json', encoding='utf-8'))
print(type(d), list(d.keys())[:10] if isinstance(d, dict) else len(d))
def show(x, n=0):
    if isinstance(x, dict):
        print(' ' * n, {k: (type(v).__name__) for k, v in x.items()})
    return
show(d)
import sys
if isinstance(d, dict):
    for k, v in d.items():
        if isinstance(v, list):
            print(k, 'list', len(v), 'first:', json.dumps(v[0], ensure_ascii=False)[:400] if v else '')
        elif isinstance(v, dict):
            print(k, 'dict', list(v.keys())[:15])
