#!/usr/bin/env python3
"""astra 只读：从 s61/s62.. 的 history.jsonl 提取 PPO 量级与 KL anchor 占比。"""
import glob
import json
import math
import os

ROOT = "/home/data/users/gaoletian/projects/HSBRSIM"


def pct(a, q):
    a = sorted(a)
    if not a:
        return None
    i = min(len(a) - 1, max(0, int(round(q * (len(a) - 1)))))
    return round(a[i], 6)


def main():
    for run in ("az_entity_s61", "az_entity_s62"):
        fp = os.path.join(ROOT, "runs", run, "history.jsonl")
        if not os.path.isfile(fp):
            continue
        rows = []
        header = None
        for line in open(fp, encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") == "header":
                header = d.get("args") or {}
                continue
            rows.append(d)
        if not rows:
            continue
        print(f"== {run}: iters={len(rows)} adv={header.get('adv_estimator')} "
              f"beta={header.get('anchor_beta')} lam={header.get('lam')} "
              f"ent={header.get('entropy_coef')} lr={header.get('lr')} "
              f"games={header.get('games')} minibatch={header.get('minibatch')} "
              f"accum={header.get('grad_accum')}")
        pl, akl, vl, ent, kl, clip, advs, beta_kl, stopped = ([] for _ in range(9))
        rank, top4, tier4, surv = [], [], [], []
        for r in rows:
            pp = r.get("ppo") or {}
            if pp.get("epochs"):
                e = pp["epochs"][-1]
                pl.append(float(e.get("policy_loss", 0)))
                akl.append(float(e.get("anchor_kl", 0)))
                vl.append(float(e.get("value_loss", 0)))
                ent.append(float(e.get("entropy", 0)))
                kl.append(float(e.get("approx_kl", 0)))
                clip.append(float(e.get("clip_frac", 0)))
                beta_kl.append(0.1 * float(e.get("anchor_kl", 0)))
                stopped.append(1 if e.get("kl_early_stopped") else 0)
            if "adv_std" in pp:
                advs.append(float(pp["adv_std"]))
            ev = r.get("eval") or {}
            if ev.get("human_mean_rank") is not None:
                rank.append(float(ev["human_mean_rank"]))
                top4.append(float(ev.get("human_top4") or 0))
        print("  n_upd_rec", len(pl),
              "| policy_loss p50", pct(pl, .5), "p10", pct(pl, .1), "p90", pct(pl, .9),
              "| beta*anchor_kl p50", pct(beta_kl, .5),
              "| ratio betaKL/policy p50",
              pct([b / max(p, 1e-12) for b, p in zip(beta_kl, pl)], .5))
        print("  anchor_kl p50/max", pct(akl, .5), pct(akl, 1.0),
              "| value_loss p50", pct(vl, .5), "p90", pct(vl, .9),
              "| entropy p10/p50/p90", pct(ent, .1), pct(ent, .5), pct(ent, .9))
        print("  approx_kl p50/p90/max", pct(kl, .5), pct(kl, .9), pct(kl, 1.0),
              "| clip_frac p50/p90", pct(clip, .5), pct(clip, .9),
              "| early_stop_frac", round(sum(stopped) / max(len(stopped), 1), 3),
              "| adv_std p50", pct(advs, .5))
        if rank:
            print("  human dev rank n_eval", len(rank), "min", round(min(rank), 3),
                  "max", round(max(rank), 3), "p50", pct(rank, .5),
                  "| top4 p50", pct(top4, .5))
            print("  ranks:", " ".join(f"{x:.2f}" for x in rank))


if __name__ == "__main__":
    main()
