"""Train warband value network on pairwise combat win-rate labels."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.value.warband_model import WarbandEncoder, pairwise_loss


def load_npz(path: str):
    d = np.load(path)
    meta = json.loads(Path(path).with_suffix(".json").read_text(encoding="utf-8"))
    return d, meta


def tensors(d, idx):
    return {
        "cards": torch.from_numpy(d["cards"][idx].astype(np.int64)),
        "atk": torch.from_numpy(d["atk"][idx].astype(np.float32)),
        "hp": torch.from_numpy(d["hp"][idx].astype(np.float32)),
        "tier": torch.from_numpy(d["tier"][idx].astype(np.float32)),
        "kw": torch.from_numpy(d["kw"][idx].astype(np.float32)),
        "lengths": torch.from_numpy(d["lengths"][idx].astype(np.int64)),
    }


def to_device(t, device):
    return {k: v.to(device) for k, v in t.items()}


def spearman(x, y):
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if len(x) < 3:
        return 0.0
    rx = np.argsort(np.argsort(x))
    ry = np.argsort(np.argsort(y))
    rx = rx - rx.mean()
    ry = ry - ry.mean()
    den = math.sqrt((rx * rx).sum() * (ry * ry).sum())
    return float((rx * ry).sum() / den) if den else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="runs/warband_value/pairs_pilot.npz")
    ap.add_argument("--out-dir", default="runs/warband_value/model_pilot")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--dim", type=int, default=128)
    ap.add_argument("--layers", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--max-seconds", type=float, default=900.0)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    d, meta = load_npz(args.data)
    n_wb = int(meta["n_warbands"])
    n_kw = len(meta["keywords"])
    n_cards = len(meta["card_ids"])
    perm = np.random.permutation(n_wb)
    n_val = max(1, int(n_wb * 0.1))
    n_test = max(1, int(n_wb * 0.1))
    val_idx = perm[:n_val]
    test_idx = perm[n_val:n_val + n_test]
    train_idx = perm[n_val + n_test:]

    pi = d["pair_i"].astype(np.int64)
    pj = d["pair_j"].astype(np.int64)
    pw = d["pair_win"].astype(np.float32)
    val_set = set(val_idx.tolist())
    test_set = set(test_idx.tolist())
    train_set = set(train_idx.tolist())
    tr = np.array([k for k in range(len(pi)) if pi[k] in train_set], dtype=np.int64)
    va = np.array([k for k in range(len(pi)) if pi[k] in val_set], dtype=np.int64)
    te = np.array([k for k in range(len(pi)) if pi[k] in test_set], dtype=np.int64)
    print(f"warbands={n_wb} pairs={len(pi)} train/val/test pairs={len(tr)}/{len(va)}/{len(te)}")

    device = torch.device(args.device)
    model = WarbandEncoder(n_cards, n_kw, dim=args.dim, layers=args.layers).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    print(f"params={sum(p.numel() for p in model.parameters())/1e6:.2f}M device={device}")

    # cache all warband tensors on device (small)
    all_t = to_device(tensors(d, np.arange(n_wb)), device)

    def score_all():
        model.eval()
        out = []
        with torch.no_grad():
            for k in range(0, n_wb, 1024):
                idx = torch.arange(k, min(n_wb, k + 1024), device=device)
                s, _ = model(**{kk: vv[idx] for kk, vv in all_t.items()})
                out.append(s)
        return torch.cat(out)

    def metrics(split_idx):
        if len(split_idx) == 0:
            return {}
        model.eval()
        s = score_all()
        a = s[pi[split_idx]]
        b = s[pj[split_idx]]
        w = torch.from_numpy(pw[split_idx]).to(device)
        logit = a - b
        acc = float((((logit > 0) & (w > 0.5)) | ((logit < 0) & (w < 0.5))).float().mean())
        # empirical mean win per warband (only noise-free for eval pairs)
        mean_w = {}
        for k in split_idx:
            mean_w.setdefault(int(pi[k]), []).append(float(pw[k]))
        idxs = list(mean_w.keys())
        emp = [float(np.mean(mean_w[i])) for i in idxs]
        pred = [float(s[i]) for i in idxs]
        return {"n_pairs": int(len(split_idx)), "pair_acc": acc,
                "spearman_meanwin": spearman(pred, emp)}

    hist = []
    t0 = time.time()
    for ep in range(args.epochs):
        model.train()
        np.random.shuffle(tr)
        total = 0.0
        for k in range(0, len(tr), args.batch):
            ids = tr[k:k + args.batch]
            i = pi[ids]
            j = pj[ids]
            w = torch.from_numpy(pw[ids]).to(device)
            uniq, inv = torch.unique(torch.cat([torch.from_numpy(i).to(device),
                                                torch.from_numpy(j).to(device)]),
                                     return_inverse=True)
            sub = {kk: vv[uniq] for kk, vv in all_t.items()}
            s_sub, _ = model(**sub)
            n_i = len(i)
            loss = pairwise_loss(s_sub[inv[:n_i]], s_sub[inv[n_i:]], w)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss) * len(ids)
            if time.time() - t0 > args.max_seconds:
                break
        val = metrics(va)
        hist.append({"epoch": ep + 1, "loss": total / max(1, len(tr)), "val": val})
        print(f"ep{ep+1} loss={total/max(1,len(tr)):.4f} val={val}")
        if time.time() - t0 > args.max_seconds:
            break

    test = metrics(te)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    torch.save({"model": model.state_dict(), "args": vars(args),
                "meta": {"n_cards": n_cards, "n_keywords": n_kw}}, out / "checkpoint.pt")
    report = {"args": vars(args), "history": hist, "test": test,
              "wall_s": time.time() - t0}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"test={test} wall={report['wall_s']:.1f}s out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
