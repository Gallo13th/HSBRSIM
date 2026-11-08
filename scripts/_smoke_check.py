import json, os
os.chdir('/home/data/users/gaoletian/projects/HSBRSIM')
d = 'runs/_smoke_scriptseats'
lines = open(d + '/history.jsonl').read().splitlines()
hdr = json.loads(lines[0])['args']
recs = [json.loads(x) for x in lines[1:] if x.strip()]
print('header: script_seats=%s script_comps=%s frozen_seats=%s frozen_opponent=%r' % (
    hdr.get('script_seats'), hdr.get('script_comps'),
    hdr.get('frozen_seats'), hdr.get('frozen_opponent')))
print('lockstep=%s opponent=%s trainer_state=%s' % (
    hdr.get('lockstep'), hdr.get('opponent'), hdr.get('trainer_state')))
dec = sum(int((r.get('collect') or {}).get('decisions') or 0) for r in recs)
illegal = sum(int((r.get('collect') or {}).get('illegal_actions') or 0) for r in recs)
fd = sum(int((r.get('collect') or {}).get('frozen_decisions') or 0) for r in recs)
rec_n = sum(int((r.get('collect') or {}).get('records') or 0) for r in recs)
hb = sum(int((r.get('collect') or {}).get('human_board_applied') or 0) for r in recs)
print('records=%d decisions=%d illegal_actions=%d frozen_decisions=%d human_board_applied=%d' % (
    len(recs), dec, illegal, fd, hb))
print('keys in collect:', sorted((recs[0].get('collect') or {}).keys()))
print('first record iter=%s last iter=%s' % (recs[0].get('iter'), recs[-1].get('iter')))
print('summary:', json.load(open(d + '/summary.json')).get('updates'),
      json.load(open(d + '/summary.json')).get('iterations'))
