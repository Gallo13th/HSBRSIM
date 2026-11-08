import json
p = '/home/data/users/gaoletian/projects/HSBRSIM/runs/human_play/trace_check.json'
d = json.load(open(p))
print('top keys:', list(d.keys()))
print('files/unique/wins:', d['n_files'], d['n_unique'], d['n_wins_pl1'])
g = d['games'][1]
print('game keys:', list(g.keys()))
print({k: g[k] for k in ('file', 'seed', 'placement', 'tmax', 't9_tier', 'final_tier', 'sigma15', 'turnover')})
print('sig_by_turn:', g['sig_by_turn'])
print('buy_by_turn:', g['buy_by_turn'])
print('C1:', json.dumps(d['C1_upgrade_hurts_board'], default=str)[:400])
print('C2 paired:', d['C2_trilemma']['paired_buy_diff'])
print('json ok, bytes:', len(open(p, 'rb').read()))
