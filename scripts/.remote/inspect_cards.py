#!/usr/bin/env python3
import json, sys
sys.path.insert(0, '/home/data/users/gaoletian/projects/HSBRSIM')
import hsbg_engine as E
cat = {c['id']: c for c in json.loads(E.catalog_json())}
ids = ['BG35_883','BG36_640','BG_LOE_077','BG28_633','BG28_707','BG35_881','BG36_245',
       'BG29_813','BG36_364','BG25_354','BG26_ICC_901','BG32_821','BG36_202','BG36_204',
       'BG36_208','BG36_209','BG31_809','BG26_802','BG35_602','BG25_008','BG25_009',
       'BGS_004','BG32_873','BG26_174','BG36_733','BG36_762','BG36_731','BG33_823','BG33_825',
       'BG34_692','BG36_515','BG36_367','BG36_851','BG36_366','BG26_152','BG36_853','BG30_121',
       'BG28_583','BG36_331','BG31_323','BGS_041','BG36_241','BG36_344','BG36_523','BG36_700',
       'BG33_318','BG26_354','BG36_703','BG22_403','BG33_891','BG31_835','BG36_318','BG36_101']
for i in ids:
    c = cat.get(i)
    if not c:
        print(f'{i}: MISSING'); continue
    print(f"{i} | {c.get('name')} | t{c.get('tier')} | kind={c.get('kind')} | race={c.get('race') or c.get('tribe')} | atk={c.get('atk')} hp={c.get('hp')} | {c.get('text')}")
print('--- catalog size', len(cat))
import collections
print('kinds', collections.Counter(c.get('kind') for c in cat.values()))
races = collections.Counter(str(c.get('race') or c.get('tribe')) for c in cat.values() if str(c.get('kind'))=='minion')
print('races', races)
print('sample card keys', list(next(iter(cat.values())).keys()))
