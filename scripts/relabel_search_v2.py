#!/usr/bin/env python3
"""离线重算 v2 搜索标签的 π（改优势裁剪 / 温度 / π 口径，不重跑搜索）。

标签里的 ``search`` 记录已包含每个候选的 ``q``（回合末真实 Σ 的叶分）、
``sigma_end`` 与 ``pi_base_cands``（候选上的 π_base 先验），所以 π_search 可以**离线**
按不同 ``adv_clip`` / ``q_temp_scale`` 重新构造：

    π(a) ∝ p̃(a)·exp(clip((Q(a)−V)/τ, ±adv_clip)),  V = Σ p̃ Q,  τ = q_temp_scale·std(Q)

用途：一条 300 局 rollout 标签 → 多个 KL 预算下的 BC 目标（clip=30 原始口径、
clip=3–6 的 KL 信任域），不必重跑昂贵的 rollout。行为轨迹与 obs 完全不变。

用法::

  PYTHONPATH=rust/python:. python scripts/relabel_search_v2.py \
      --in data/search_labels_v2/sandbox_v2_g10.jsonl.gz \
      --out data/search_labels_v2/sandbox_v2_g10_clip6.jsonl.gz --adv-clip 6
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hsbg.az.train.sandbox_rollout import RolloutConfig, pi_from_q  # noqa: E402
from scripts.gen_sandbox_search_labels import kl_nats, topk_pi  # noqa: E402


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="离线重算 v2 标签的 π_search")
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--adv-clip", type=float, default=30.0)
    ap.add_argument("--q-temp", type=float, default=0.0)
    ap.add_argument("--q-temp-scale", type=float, default=1.0)
    ap.add_argument("--pi-mode", default="advantage", choices=["advantage", "softmax"])
    ap.add_argument("--label-topk", type=int, default=8)
    args = ap.parse_args(argv)
    cfg = RolloutConfig(q_temp=float(args.q_temp),
                        q_temp_scale=float(args.q_temp_scale),
                        adv_clip=float(args.adv_clip),
                        pi_mode=str(args.pi_mode))
    stats: Dict[str, Any] = {"adv_clip": float(args.adv_clip),
                             "q_temp": float(args.q_temp),
                             "q_temp_scale": float(args.q_temp_scale),
                             "pi_mode": str(args.pi_mode)}
    kls: List[float] = []
    agree: List[int] = []
    d_pi: List[int] = []
    mass: List[float] = []
    n_steps = 0
    n_searched = 0
    n_missing = 0
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with gzip.open(args.src, "rt", encoding="utf-8") as fi, \
            gzip.open(args.out, "wt", encoding="utf-8", compresslevel=6) as fo:
      try:
        for line in fi:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "step":
                fo.write(line)
                continue
            n_steps += 1
            s = rec.get("search") or {}
            if not int(rec.get("searched") or 0) or not s:
                fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue
            cands = np.asarray(s.get("cands") or [], dtype=np.int64)
            q = np.asarray(s.get("q") or [], dtype=np.float64)
            prior_c = s.get("pi_base_cands")
            if cands.size != q.size or prior_c is None or len(prior_c) != cands.size:
                n_missing += 1
                fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue
            prior = np.zeros(245, dtype=np.float32)
            prior[cands] = np.asarray(prior_c, dtype=np.float32)
            pi, tau, V = pi_from_q(prior, cands, q, cfg)
            n_searched += 1
            rec["pi"] = topk_pi(pi, int(args.label_topk))
            top1 = int(np.argmax(pi))
            s["pi_top1"] = top1
            s["pi_top1_mass"] = round(float(pi[top1]), 4)
            s["tau"] = round(float(tau), 6)
            # KL / 一致率 / 回合末 Σ 差（π top-1 vs π_base top-1）
            pb = np.zeros(245, dtype=np.float32)
            for a, p in (rec.get("pi_base") or []):
                pb[int(a)] = float(p)
            kls.append(kl_nats(pi, pb))
            agree.append(int(top1 == int(rec.get("pi_base_top1", -1))))
            mass.append(float(pi[top1]))
            base = int(s.get("base", -1))
            se = s.get("sigma_end") or []
            if se and se[0] >= 0 and base in cands.tolist():
                jb = cands.tolist().index(base)
                if top1 in cands.tolist():
                    jt = cands.tolist().index(top1)
                    d_pi.append(int(se[jt]) - int(se[jb]))
            fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
      except EOFError:      # 生成中断的半截 gzip：已读部分照用（诊断用）
        stats["truncated_gzip"] = True
    stats.update({"steps": int(n_steps), "searched": int(n_searched),
                  "missing_prior": int(n_missing),
                  "kl_pi_base_mean": (float(np.mean(kls)) if kls else None),
                  "kl_pi_base_p50": (float(np.median(kls)) if kls else None),
                  "kl_pi_base_p90": (float(np.percentile(kls, 90)) if kls else None),
                  "top1_agree_with_base": (float(np.mean(agree)) if agree else None),
                  "pi_top1_mass_mean": (float(np.mean(mass)) if mass else None),
                  "sigma_delta_pi_minus_base": {
                      "mean": (float(np.mean(d_pi)) if d_pi else None),
                      "p50": (float(np.median(d_pi)) if d_pi else None),
                      "frac_pos": (float(np.mean(np.asarray(d_pi) > 0))
                                   if d_pi else None)},
                  "out": os.path.abspath(args.out)})
    sm = args.out[:-len(".jsonl.gz")] + ".summary.json" \
        if args.out.endswith(".jsonl.gz") else os.path.splitext(args.out)[0] + ".summary.json"
    with open(sm, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    print(json.dumps(stats, ensure_ascii=False, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
