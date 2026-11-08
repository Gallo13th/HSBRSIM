#!/usr/bin/env python3
"""astra 只读探针：T1(comp_fit) 已跑过的实验读数 + 96 局面板统计量。不训练、不写 runs。"""
import gzip
import json
import math
import os
import sys

ROOT = "/home/data/users/gaoletian/projects/HSBRSIM"
OUT = []


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    OUT.append(s)


def boot_ci(x, n=4000, seed=7):
    import numpy as np
    rng = np.random.default_rng(seed)
    x = np.asarray(x, float)
    idx = rng.integers(0, x.size, size=(n, x.size))
    m = x[idx].mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    import numpy as np
    # ── 1. T1 各臂 config ────────────────────────────────────────────────
    for d in ("t1", "t1iso", "t1iso2", "t1p"):
        fp = os.path.join(ROOT, "runs", "az_entity_" + d, "summary.json")
        if not os.path.isfile(fp):
            continue
        c = json.load(open(fp))["config"]
        keys = [k for k in sorted(c) if ("comp" in k or "trinket" in k)]
        keys += [k for k in ("checkpoint", "seed", "games", "human_board_seats",
                             "human_board_p", "entropy_coef", "lam", "adv_estimator",
                             "power_alpha", "power_kappa", "power_normalize",
                             "anchor_coef", "value_loss", "stop_at_decisions")
                 if k in c]
        p("== config", d, json.dumps({k: c[k] for k in keys}, ensure_ascii=False))

    # ── 2. T1 各臂 96 局 p0.9 quality（placements 配对）──────────────────
    pl = {}
    for tag in ("t1", "t1p"):
        fp = os.path.join(ROOT, "runs", "comp_scripts", tag + "_p09_quality.json")
        if os.path.isfile(fp):
            q = json.load(open(fp))
            pl[tag] = np.asarray(q["placements"], float)
            p("[q]", tag, "n", len(pl[tag]), "mean_rank", round(float(pl[tag].mean()), 4),
              "top4", round(float((pl[tag] <= 4).mean()), 4),
              "death_strength_p50", q.get("death_strength_p50"))
    if "t1" in pl and "t1p" in pl:
        n = min(len(pl["t1"]), len(pl["t1p"]))
        dlt = pl["t1p"][:n] - pl["t1"][:n]
        lo, hi = boot_ci(dlt)
        se = float(dlt.std(ddof=1) / math.sqrt(n))
        p("[q] t1p-t1 paired dRank", round(float(dlt.mean()), 4),
          "CI", [round(lo, 4), round(hi, 4)], "SE", round(se, 4),
          "sd_diff", round(float(dlt.std(ddof=1)), 4))
    # ── 3. human128 面板（seed 420000，非主口径，仅作方向）───────────────
    hu = {}
    for tag in ("t1", "t1iso", "t1iso2", "t1p"):
        fp = os.path.join(ROOT, "runs", "comp_scripts", tag + "_human128.json")
        if not os.path.isfile(fp):
            continue
        d = json.load(open(fp))
        pa = d["panels"][0]
        hu[tag] = pa
        p("[h]", tag, "n", pa.get("n"), "model_rank", round(pa.get("model_mean_rank") or 0, 4),
          "top4", round(pa.get("model_top4") or 0, 4),
          "ci", pa.get("ci_low"), pa.get("ci_high"))

    # ── 4. comp_fit 势函数经验分布（baseline_p09 探针的 per-turn fit）─────
    fp = os.path.join(ROOT, "runs", "comp_scripts", "baseline_p09.jsonl.gz")
    if os.path.isfile(fp):
        fits, d_fit, t9, last, trink = [], [], [], [], []
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                fv = {int(k): float(v) for k, v in (r.get("fit") or {}).items()}
                if not fv:
                    continue
                ts = sorted(fv)
                t9.append(fv.get(9))
                last.append(fv[ts[-1]])
                fits.extend(fv.values())
                for a, b in zip(ts, ts[1:]):
                    d_fit.append(fv[b] - fv[a])
                trink.extend(r.get("trinkets") or [])
        fits = np.asarray([x for x in fits if x is not None], float)
        d_fit = np.asarray([x for x in d_fit if x is not None], float)
        q = lambda a, x: round(float(np.percentile(a, x)), 4) if len(a) else None
        p("[fit] per-turn Phi n", fits.size, "p10/p50/p90", q(fits, 10), q(fits, 50), q(fits, 90),
          "max", round(float(fits.max()), 4) if fits.size else None)
        p("[fit] dPhi per-turn p50/p90/max", q(np.abs(d_fit), 50), q(np.abs(d_fit), 90),
          round(float(np.abs(d_fit).max()), 4) if d_fit.size else None)
        t9a = np.asarray([x for x in t9 if x is not None], float)
        p("[fit] Phi@t9 p10/p50/p90", q(t9a, 10), q(t9a, 50), q(t9a, 90),
          "mean", round(float(t9a.mean()), 4))
        p("[trinket] n", len(trink), "matched", sum(1 for x in trink if x.get("matched")),
          "offered", sum(1 for x in trink if x.get("offered")))

    # ── 5. 96 局面板的 SE / MDE（rank 分布按 s61@30M 的 6.083 附近建模）───
    # rank~1..8，用 t1_p09_quality 的 96 局经验分布当 sd 估计
    if "t1" in pl:
        a = pl["t1"]
        sd = float(a.std(ddof=1))
        for n in (96, 192, 384, 768, 2048):
            se = sd / math.sqrt(n)
            p(f"[stat] single-model n={n} sd={sd:.3f} SE={se:.4f} "
              f"MDE80={2.802*se:.4f} MDE95={3.92*se:.4f}")
        for n in (96, 192, 384, 768, 2048):
            se_d = math.sqrt(2.0) * sd / math.sqrt(n)
            p(f"[stat] unpaired 2-model n={n} SE_diff={se_d:.4f} MDE80={2.802*se_d:.4f}")
        # 比例指标 SE
        for name, pp in (("top4", float((a <= 4).mean())), ("win", float((a <= 1).mean()))):
            for n in (96, 384, 2048):
                s = math.sqrt(max(pp * (1 - pp), 1e-9) / n)
                p(f"[stat] {name} n={n} p={pp:.3f} SE={s:.4f} MDE80(2prop)="
                  f"{2.802*math.sqrt(2)*s:.4f}")
    p("[done]")
    open(os.path.join(ROOT, ".tmp_trace", "astra_probe_out.txt"), "w",
         encoding="utf-8").write("\n".join(OUT) + "\n")


if __name__ == "__main__":
    sys.exit(main())
