"""Evaluate warband value checkpoint on a fresh pairwise dataset."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import torch
from hsbg.value.warband_model import WarbandEncoder


def spearman(x, y):
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if len(x) < 3:
        return 0.0
    rx = np.argsort(np.argsort(x)).astype(np.float64)
    ry = np.argsort(np.argsort(y)).astype(np.float64)
    rx -= rx.mean()
    ry -= ry.mean()
    den = math.sqrt((rx * rx).sum() * (ry * ry).sum())
    return float((rx * ry).sum() / den) if den else 0.0


@torch.no_grad()
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--out", default="runs/warband_value/eval.json")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    d = np.load(args.data)
    meta = json.loads(Path(args.data).with_suffix(".json").read_text(encoding="utf-8"))
    ck = torch.load(args.checkpoint, map_location=args.device)
    a = ck["args"]
    model = WarbandEncoder(len(meta["card_ids"]), len(meta["keywords"]),
                           dim=a["dim"], layers=a["layers"]).to(args.device)
    model.load_state_dict(ck["model"])
    model.eval()

    device = torch.device(args.device)
    t = {
        "cards": torch.from_numpy(d["cards"].astype(np.int64)).to(device),
        "atk": torch.from_numpy(d["atk"].astype(np.float32)).to(device),
        "hp": torch.from_numpy(d["hp"].astype(np.float32)).to(device),
        "tier": torch.from_numpy(d["tier"].astype(np.float32)).to(device),
        "kw": torch.from_numpy(d["kw"].astype(np.float32)).to(device),
        "lengths": torch.from_numpy(d["lengths"].astype(np.int64)).to(device),
    }
    scores = []
    embs = []
    for k in range(0, len(t["cards"]), 2048):
        sl = {kk: vv[k:k + 2048] for kk, vv in t.items()}
        s, z = model(**sl)
        scores.append(s)
        embs.append(z)
    s = torch.cat(scores)
    pi = d["pair_i"].astype(np.int64)
    pj = d["pair_j"].astype(np.int64)
    pw = d["pair_win"].astype(np.float32)
    logit = (s[pi] - s[pj]).detach().cpu().numpy()
    acc = float((((logit > 0) & (pw > 0.5)) | ((logit < 0) & (pw < 0.5))).mean())
    # per-warband empirical mean win-rate vs predicted score
    mean_w = {}
    for i, w in zip(pi, pw):
        mean_w.setdefault(int(i), []).append(float(w))
    ids = list(mean_w)
    emp = np.array([np.mean(mean_w[i]) for i in ids])
    pred = s[ids].detach().cpu().numpy()
    sp = spearman(pred, emp)
    report = {
        "n_pairs": int(len(pi)), "n_warbands": int(meta["n_warbands"]),
        "pair_acc": acc, "spearman_warband_meanwin": sp,
        "pred_mean": float(s.mean()), "pred_std": float(s.std()),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    torch.save({"embeddings": torch.cat(embs).cpu(), "scores": s.cpu()},
               Path(args.out).with_suffix(".pt"))
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
