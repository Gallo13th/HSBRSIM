#!/usr/bin/env python3
"""升 5 本探针：每局记录 learner 首次到达 tier>=5 的回合数 + 最大 tier。"""
import sys, json, os, importlib.util
ROOT=os.environ.get("HSBRSIM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT,'rust/python'))
spec=importlib.util.spec_from_file_location('qm', os.path.join(ROOT,'scripts/quality_monitor.py'))
qm=importlib.util.module_from_spec(spec); spec.loader.exec_module(qm)
from hsbg.az.train.model import load_checkpoint
from hsbg.az.train.ppo import PPOEvaluator, PPOSelfPlayPolicy, CollectConfig

def run(ckpt, games, seed_base, device, human=None, seats=0, p=0.0, sample='auto', fidelity='full'):
    model, meta = load_checkpoint(ckpt, device=device)
    ev = PPOEvaluator(model, device=device, norm_mean=meta.get('norm_mean'), norm_std=meta.get('norm_std'))
    cfg = CollectConfig(games=1, seed=seed_base, opponent='bot', behavior='net', max_steps=20000,
                        move_guard=True, move_cap=3, move_repeat_limit=2)
    pol = PPOSelfPlayPolicy(model, device=device, config=cfg, eval_fn=ev, seed=seed_base, move_model=False)
    q = dict(cfg.__dict__)
    if human:
        hp = qm.load_human_pool(human, sample=sample)
        q.update({'human_board_pool': hp, 'human_board_p': p, 'human_board_seats': seats,
                  'human_board_set_tier': True, 'human_board_fidelity': fidelity,
                  'human_board_fast_inject': False})
    out=[]
    for g in range(games):
        r = qm._play(seed_base+g, pol, q)
        if not r: continue
        turns = r['turns']; t5=None; maxt=0
        for row in turns:
            t=int(row.get('turn',0)); tier=int(row.get('tier') or 0)
            maxt=max(maxt,tier)
            if t5 is None and tier>=5: t5=t
        out.append({'placement':int(r['placement']),'tier5_turn':t5,'max_tier':maxt,
                    'death_turn':r.get('death_turn'),
                    'final_turn':max(int(x['turn']) for x in turns) if turns else 0})
        if hasattr(pol,'flush'): pol.flush()
    return out

def summarize(name, rows):
    n=len(rows)
    t5=[r for r in rows if r['tier5_turn'] is not None]
    hist={}
    for r in t5: hist[r['tier5_turn']]=hist.get(r['tier5_turn'],0)+1
    maxt={}
    for r in rows: maxt[r['max_tier']]=maxt.get(r['max_tier'],0)+1
    print('[%s] n=%d  升5本 %d 局（%.1f%%）'%(name,n,len(t5),100*len(t5)/max(1,n)))
    print('  升5本回合分布 %s'%json.dumps({k:hist[k] for k in sorted(hist)},ensure_ascii=False))
    print('  最大 tier 分布 %s'%json.dumps({k:maxt[k] for k in sorted(maxt)},ensure_ascii=False))
    if t5:
        ts=sorted(r['tier5_turn'] for r in t5)
        print('  升5本回合 p10/p50/p90 = %d / %d / %d'%(ts[len(ts)//10], ts[len(ts)//2], ts[min(len(ts)-1,9*len(ts)//10)]))
    print('  平均名次 %.2f  平均终局回合 %.1f'%(sum(r['placement'] for r in rows)/max(1,n), sum(r['final_turn'] for r in rows)/max(1,n)))

if __name__=='__main__':
    dev='cuda:7'; games=int(sys.argv[1]) if len(sys.argv)>1 else 96
    res={}
    for name,ck in [('B03_300M_bot','runs/az_stage300m_b03/model.pt'),
                    ('B05_now_bot','runs/az_stage300m_b05/model.pt')]:
        rows=run(ck, games, 620000, dev); res[name]=rows; summarize(name, rows)
    rows=run('runs/az_stage300m_b05/model.pt', games, 520000, dev,
             human='data/real_library/library_real_quasi_full.jsonl', seats=5, p=0.9, sample='p75')
    res['B05_now_human5']=rows; summarize('B05_now_human5', rows)
    json.dump({k:v for k,v in res.items()}, open('/tmp/tier_probe_out.json','w'))
