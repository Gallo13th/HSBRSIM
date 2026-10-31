#!/usr/bin/env python3
"""离线 BC：用沙盒搜索标签（``obs → π_search``）训练 entity 的策略头。

标签来自 ``scripts/gen_sandbox_search_labels.py``（PUCT/MCTS，64–256 sims，
稀疏 top-k 的 π）。训练目标 = **soft-label CE**：``-Σ_i π_i · log_softmax(logits)_i``
（masked，只在标签的 top-k 支撑上求和、按支撑重新归一）。默认只训 ``searched=1``
的关键决策步（其余步 π_search = π_base，训它们等于自蒸馏，会稀释搜索信号）。

训练后评测（沙盒，gold 10，与 s14 同 seed 成对）：
- t12 / t15 Σ p50（判据：**t12 ≥ 900** 才算搜索标签有效）；
- 载体在场回合数 ``carrier_turns_mean``、对载体施法 ``casts_on_carrier_mean``。

用法::

  PYTHONPATH=rust/python:. python scripts/train_search_bc.py \
      --labels data/search_labels/sandbox_labels.jsonl.gz \
      --checkpoint runs/az_entity_s14/model.pt --device cuda:7 \
      --epochs 2 --lr 3e-5 --batch 256 --only-searched 1 \
      --out runs/search_bc/bc_search.pt --eval-games 32 --eval-gold 10
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hsbg.az.train.economy_sandbox import (N_ACTIONS, OBS_CARDS, OBS_FLOATS,  # noqa: E402
                                           SandboxConfig)
from hsbg.az.train.model import load_checkpoint, save_checkpoint  # noqa: E402


def _torch():
    import torch
    return torch


def decode_obs(rec: Dict[str, str]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """标签记录 -> ``(features f32[3227], cards i32[124], mask bool[245])``。"""
    import base64
    f = np.frombuffer(base64.b64decode(rec["f16"]), dtype=np.float16).astype(np.float32)
    c = np.frombuffer(base64.b64decode(rec["cards"]), dtype=np.int16).astype(np.int32)
    m = np.unpackbits(np.frombuffer(base64.b64decode(rec["mask"]), dtype=np.uint8),
                      count=N_ACTIONS).astype(bool)
    if f.size != OBS_FLOATS or c.size != OBS_CARDS or m.size != N_ACTIONS:
        raise ValueError(f"标签维度异常: {f.size}/{c.size}/{m.size}")
    return f, c, m


def load_labels(path: str, *, only_searched: bool = True, topk: int = 0,
                max_samples: int = 0, verbose: bool = True,
                base_fallback: bool = False
                ) -> Dict[str, Any]:
    """读 ``.jsonl.gz``：返回 ``features/cards/masks/target/actions`` 与统计。"""
    feats: List[np.ndarray] = []
    cards: List[np.ndarray] = []
    masks: List[np.ndarray] = []
    targets: List[np.ndarray] = []
    acts: List[int] = []
    steps = 0
    searched = 0
    episodes: List[Dict[str, Any]] = []
    t0 = time.time()
    truncated = False
    fh = gzip.open(path, "rt", encoding="utf-8")
    try:
        for line in fh:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "episode":
                episodes.append(rec)
                continue
            if rec.get("type") != "step":
                continue
            steps += 1
            is_s = bool(int(rec.get("searched") or 0))
            if is_s:
                searched += 1
            if only_searched and not is_s:
                continue
            pi = rec.get("pi") or []
            if not pi and base_fallback:
                # DAgger 锚点：未搜索步用 π_base 当目标（自蒸馏正则，防止策略整体漂移）
                pi = rec.get("pi_base") or []
            if not pi:
                continue
            f, c, m = decode_obs(rec["obs"])
            tgt = np.zeros(N_ACTIONS, dtype=np.float32)
            for a, p in pi:
                a = int(a)
                if 0 <= a < N_ACTIONS and bool(m[a]):
                    tgt[a] += float(p)
            s = float(tgt.sum())
            if s <= 0:
                continue
            tgt /= s
            feats.append(f)
            cards.append(c)
            masks.append(m)
            targets.append(tgt)
            acts.append(int(np.argmax(tgt)))
            if int(max_samples) > 0 and len(targets) >= int(max_samples):
                break
    except EOFError:          # 生成中断的半截 gzip：用已读部分（诊断/冒烟用）
        truncated = True
    finally:
        fh.close()
    data = {"features": np.stack(feats) if feats else np.zeros((0, OBS_FLOATS), np.float32),
            "cards": np.stack(cards) if cards else np.zeros((0, OBS_CARDS), np.int32),
            "masks": np.stack(masks) if masks else np.zeros((0, N_ACTIONS), bool),
            "targets": np.stack(targets) if targets else np.zeros((0, N_ACTIONS), np.float32),
            "actions": np.asarray(acts, dtype=np.int64),
            "episodes": episodes,
            "stats": {"steps": steps, "searched_steps": searched,
                      "samples": len(targets),
                      "search_ratio": (searched / steps if steps else 0.0),
                      "load_s": round(time.time() - t0, 2)}}
    if verbose:
        print(f"[bc] labels {path}: steps={steps} searched={searched} "
              f"samples={len(targets)} ({data['stats']['load_s']}s)", flush=True)
    return data


def bc_fit(model, data: Dict[str, Any], device: str, *, epochs: int = 2,
           lr: float = 3e-5, batch: int = 256, seed: int = 0) -> Dict[str, Any]:
    """soft-label CE（masked），只在标签 π 的支撑上归一。"""
    torch = _torch()
    t = torch
    from hsbg.az.train.ppo import masked_log_softmax_torch
    f = data["features"]
    c = data["cards"]
    m = data["masks"]
    tgt = data["targets"]
    n = len(tgt)
    model.to(t.device(device))
    model.train()
    opt = t.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=float(lr))
    rng = np.random.default_rng(seed)
    hist: List[Dict[str, Any]] = []
    t0 = time.time()
    for ep in range(int(epochs)):
        order = rng.permutation(n)
        tot, cnt, hit = 0.0, 0, 0
        for s in range(0, n, int(batch)):
            idx = order[s:s + int(batch)]
            ft = t.from_numpy(np.ascontiguousarray(f[idx])).to(device)
            ct = t.from_numpy(np.ascontiguousarray(c[idx])).to(device)
            mt = t.from_numpy(np.ascontiguousarray(m[idx])).to(device)
            tt = t.from_numpy(np.ascontiguousarray(tgt[idx])).to(device)
            out = model(ft, ct, mt)
            logits = out[0]
            logp = masked_log_softmax_torch(logits.float(), mt)
            loss = -(tt * logp).sum(dim=-1).mean()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            t.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += float(loss.detach().cpu()) * len(idx)
            cnt += len(idx)
            hit += int((logp.argmax(-1) == tt.argmax(-1)).sum().detach().cpu())
        rec = {"epoch": ep + 1, "ce": tot / max(1, cnt),
               "top1": hit / max(1, cnt), "samples": n}
        hist.append(rec)
        print(f"[bc] epoch {ep + 1}/{epochs} ce={rec['ce']:.4f} "
              f"top1={rec['top1']:.3f} n={n} ({time.time() - t0:.0f}s)", flush=True)
    model.eval()
    return {"history": hist, "samples": n, "elapsed_s": round(time.time() - t0, 1)}


# ── 沙盒评测（与 s14 成对、同 seed）────────────────────────────────────────


def eval_sandbox(model, device: str, games: int, gold: int, seed0: int,
                 *, sample: bool, carrier_audit: int = 1) -> Dict[str, Any]:
    sys.path.insert(0, ROOT)
    import scripts.train_economy_sandbox as T
    # 采样 RNG 固定：BC 与基线用**同一条**采样流，配对比较才干净
    torch = _torch()
    torch.manual_seed(int(seed0))
    np.random.seed(int(seed0) % (2 ** 32 - 1))
    cfg = SandboxConfig(gold_per_turn=int(gold))
    rep = T.evaluate(model, cfg, int(games), device, seed0=int(seed0),
                     sample=bool(sample), carrier_audit=int(carrier_audit))
    keys = ("mode", "gold", "games", "sigma_t12_p50", "sigma_t12_p90", "sigma_t12_max",
            "sigma_t15_p50", "sigma_t15_p90", "tier_p50", "carrier_rate",
            "carrier_turns_mean", "carriers_p50", "spells_p50", "spells_max",
            "casts_on_carrier_mean", "casts_on_carrier_mean_given_carrier",
            "tavern_buff_p50", "decisions_mean")
    return {k: rep.get(k) for k in keys}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="沙盒搜索标签 -> 离线 BC + 评测")
    ap.add_argument("--labels", default="data/search_labels/sandbox_labels.jsonl.gz")
    ap.add_argument("--checkpoint", default="runs/az_entity_s14/model.pt")
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--only-searched", type=int, default=1, choices=[0, 1])
    ap.add_argument("--base-fallback", type=int, default=0, choices=[0, 1],
                    help="1=未搜索步用 π_base 当 soft 目标（DAgger 锚点，配合 --only-searched 0）")
    ap.add_argument("--max-samples", type=int, default=0)
    ap.add_argument("--out", default="runs/search_bc/bc_search.pt")
    ap.add_argument("--eval-games", type=int, default=32)
    ap.add_argument("--eval-gold", type=int, default=10)
    ap.add_argument("--eval-seed", type=int, default=910000)
    ap.add_argument("--baseline", default="runs/az_entity_s14/model.pt",
                    help="对照 checkpoint（同 seed 成对评测；空 = 不跑）")
    ap.add_argument("--no-eval", action="store_true")
    ap.add_argument("--json-out", default="runs/search_bc/eval.json")
    args = ap.parse_args(argv)

    data = load_labels(args.labels, only_searched=bool(int(args.only_searched)),
                       max_samples=int(args.max_samples),
                       base_fallback=bool(int(args.base_fallback)))
    if len(data["actions"]) == 0:
        print("[bc] 没有可用样本", file=sys.stderr)
        return 2
    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    print(f"[bc] ckpt={args.checkpoint} arch={meta.get('arch')}", flush=True)
    fit = bc_fit(model, data, args.device, epochs=int(args.epochs), lr=float(args.lr),
                 batch=int(args.batch), seed=int(args.seed))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    meta_out = dict(meta)
    meta_out.update({"search_bc": True, "search_bc_fit": fit,
                     "search_bc_labels": os.path.abspath(args.labels),
                     "search_bc_stats": data["stats"]})
    save_checkpoint(model, args.out, meta=meta_out)
    print(f"[bc] saved {args.out}", flush=True)
    result: Dict[str, Any] = {"checkpoint": args.checkpoint, "out": args.out,
                              "labels": args.labels, "data": data["stats"],
                              "fit": fit}
    if not args.no_eval:
        # 评测：BC 权重与基线 s14 在同 seed 上成对（sample 主口径 + greedy 诊断）
        result["eval"] = {}
        t0 = time.time()
        pairs = [("bc", args.out)]
        if args.baseline:
            pairs.append(("baseline", str(args.baseline)))
        for tag, ckpt in pairs:
            if not ckpt:
                continue
            m2, _meta2 = load_checkpoint(ckpt, device=args.device)
            for mode in ("sample", "greedy"):
                rep = eval_sandbox(m2, args.device, int(args.eval_games),
                                   int(args.eval_gold), int(args.eval_seed),
                                   sample=(mode == "sample"))
                result["eval"][f"{tag}_{mode}"] = rep
                print(json.dumps({f"{tag}_{mode}": rep}, ensure_ascii=False), flush=True)
            del m2
        result["eval_elapsed_s"] = round(time.time() - t0, 1)
        # 判据
        t12 = (result["eval"].get("bc_sample") or {}).get("sigma_t12_p50")
        t12_base = (result["eval"].get("baseline_sample") or {}).get("sigma_t12_p50")
        result["criterion"] = {
            "gold": int(args.eval_gold), "t12_bc": t12, "t12_baseline": t12_base,
            "target": 900.0, "passed": bool(t12 is not None and float(t12) >= 900.0)}
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: result.get(k) for k in ("criterion", "fit")},
                     ensure_ascii=False, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
