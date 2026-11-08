#!/usr/bin/env python3
"""s22 杩愯鐘舵€侀€熻锛歞ecisions / collect_s / dec_s / ppo_s / kl / ent / value / eval 鏇茬嚎銆?""
import json, os, sys

run = sys.argv[1] if len(sys.argv) > 1 else "runs/az_entity_s22"
hist = os.path.join(run, "history.jsonl")
recs = []
with open(hist, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if "iter" in r:
            recs.append(r)
print(f"iters={len(recs)}")
if recs:
    last = recs[-1]
    print(f"iter={last['iter']} cum_dec={sum(r['collect'].get('decisions',0) for r in recs):,}")
    # 鏈€杩?5 涓?iteration 鐨勬椂寤?    for r in recs[-5:]:
        c, p = r["collect"], r.get("ppo", {})
        print(f"  it{r['iter']:>4} dec={c['decisions']:>6} collect_s={c['wall_s']:6.2f} "
              f"dec/s={c['decisions_per_s']:7.1f} kl={p.get('approx_kl', float('nan')):.5f} "
              f"ent={p.get('entropy', float('nan')):.3f} val={p.get('value_loss', float('nan')):.4f} "
              f"clip={p.get('clip_frac', float('nan')):.3f} "
              f"anchor={p.get('anchor_kl', float('nan')):.5f} "
              f"ppo_s={p.get('wall_s', float('nan')):.2f}")
# eval 缁撴灉
ev = os.path.join(run, "eval", "history.json")
if os.path.isfile(ev):
    with open(ev, encoding="utf-8") as f:
        e = json.load(f)
    for k in sorted(e, key=str):
        v = e[k]
        if isinstance(v, dict):
            print(f"[eval {k}] {json.dumps({kk: v.get(kk) for kk in ('human_mean_rank','mean_rank','top4','win','games','decisions','hard_errors','ts') if kk in v}, ensure_ascii=False)}")
else:
    print("[eval] (none yet)")
