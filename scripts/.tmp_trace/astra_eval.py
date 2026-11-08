#!/usr/bin/env python3
"""astra 只读：s61 首批 anchor_kl 精度地板 + summary evals + eval_panel 历史。"""
import glob
import json
import os

ROOT = "/home/data/users/gaoletian/projects/HSBRSIM"


def main():
    fp = os.path.join(ROOT, "runs/az_entity_s61/history.jsonl")
    first = []
    for line in open(fp, encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") == "header":
            continue
        e = (d.get("ppo") or {}).get("epochs") or []
        if e:
            first.append((d.get("iter"), e[-1].get("anchor_kl"),
                          e[-1].get("approx_kl"), e[-1].get("policy_loss"),
                          (d.get("ppo") or {}).get("pipeline")))
        if len(first) >= 8:
            break
    print("== s61 first updates (iter, anchor_kl, approx_kl, policy_loss)")
    for r in first:
        print("  ", r[0], r[1], r[2], r[3])

    sp = os.path.join(ROOT, "runs/az_entity_s61/summary.json")
    if os.path.isfile(sp):
        d = json.load(open(sp))
        ev = d.get("evals") or []
        print("== s61 summary evals n=", len(ev))
        for e in ev[:12]:
            print("  ", {k: e.get(k) for k in
                         ("panel", "decisions", "human_mean_rank", "human_top4",
                          "quantile", "games", "seed_base") if k in e})

    # eval_panel 冻结面板历史
    for fp in sorted(glob.glob(os.path.join(ROOT, "runs/eval_panel/*.json"))):
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        name = os.path.basename(fp)[:-5]
        if not any(k in name for k in ("s61", "s59", "s60")):
            continue
        print("[panel]", name, "rank", round(float(d.get("mean_rank") or 0), 3),
              "top4", round(float(d.get("top4") or 0), 3),
              "strength", d.get("death_strength_p50"),
              "tier4+", round(float(d.get("tier_ge4_ratio") or 0), 3),
              "surv12", round(float(d.get("survive_t12_ratio") or 0), 3),
              "games", d.get("games"), "seed", d.get("seed_base"))


if __name__ == "__main__":
    main()
