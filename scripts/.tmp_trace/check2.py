import json
d = json.load(open('/home/data/users/gaoletian/projects/HSBRSIM/runs/human_play/trace_check.json'))
for g in d['games']:
    if any(k in g['file'] for k in ('100337', '103400', '101823', '134142')):
        print(g['file'][11:23], 'pl', g['placement'], 'tiers', g['tier_by_turn'])
print()
print('tier>=5 at end of t9:', sum(1 for g in d['games'] if g['t9_tier'] and g['t9_tier'] >= 5), '/15')
print('C2 buy_matched:', json.dumps(d['C2_trilemma']['buy_matched'], indent=0))
print('C3 split turnover:', json.dumps(d['C3_turnover']['median_split']['turnover'], indent=0))
print('C3 ex-extreme:', json.dumps(d['C3_turnover']['ex_extreme_143644'], indent=0))
print('C4:', json.dumps(d['C4_tier5_by_t9']['by_t9_tier'], indent=0))
