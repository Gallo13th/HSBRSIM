import json, sys
sys.path.insert(0, '/home/data/users/gaoletian/projects/HSBRSIM/.tmp_trace')
d = json.load(open('/home/data/users/gaoletian/projects/HSBRSIM/.tmp_trace/games.json'))
g = [x for x in d['games'] if '671417_06' in x['file']][0]
for t in ('13', '14', '15'):
    print(t, 'sig', g['per'].get(t), 'tier', g['tiers'].get(t), 'board', g['turn'][t]['board'])
    print('   turn rec', {k: v for k, v in g['turn'][t].items() if k not in ('board', 'hand')})
print('--- normal game seed1')
g2 = [x for x in d['games'] if 'seed1_02' in x['file']][0]
for t in ('7', '8', '9', '13', '14'):
    print(t, 'sig', g2['per'].get(t), 'board', g2['turn'][t]['board'], 'hand', g2['turn'][t]['hand'][:4])
