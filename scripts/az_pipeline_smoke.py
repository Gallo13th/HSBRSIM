"""AZ-MCTS 训练管线 smoke（100 局级）：8 座自对弈 MCTS → 数据 → 训练 → 评测。

用途：在远程开发机验证“完整训练管线可运行”（不是强度/规模实验）。
- 搜索：`hsbg/search/engine_mcts.py`（Python 原型；搜索内对手用 bot，外层 8 座用搜索）；
- 网络：`hsbg/policy/std_net.py`（features 3227 → 245 policy + 8 rank value；cards 暂未编码）；
- 数据：每座位决策记录 (features, cards, mask, π, rank)；
- 训练：policy CE(π) + value CE(rank)，CPU/GPU 均可；
- 评测：seat0 vs 7 bot 的策略（不带搜索）平均名次。

运行（远程）：
  python3 scripts/az_pipeline_smoke.py --games 100 --sims 2 --epochs 2 --out runs/az_smoke
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch
import torch.nn.functional as F

import hsbg_engine as E
from hsbg.policy.std_net import AZNet, make_evaluator, save_checkpoint
from hsbg.search.engine_mcts import MCTSConfig, search


def collect(games: int, sims: int, seed: int, net: AZNet, device: str, temperature: float = 1.0):
    evaluator = make_evaluator(net, device)
    cfg = MCTSConfig(simulations=sims, temperature=temperature, seed=seed)
    feats, cards, masks, pis, ranks, seats = [], [], [], [], [], []
    t0 = time.time()
    decisions = 0
    for gi in range(games):
        game = E.Game(seed=seed + gi)
        game_samples = []
        guard = 0
        last_turn = game.turn
        steps_in_turn = 0
        while not game.is_over():
            acted = False
            for p in range(game.num_players):
                if not game.needs_action(p):
                    continue
                f_raw, c_raw = game.observe(p)
                f = np.frombuffer(f_raw, dtype="<f4").copy()
                c = np.frombuffer(c_raw, dtype="<i4").copy()
                mask = np.frombuffer(game.legal_mask(p), dtype=np.uint8).astype(bool)
                # smoke 防退化：随机初始化策略可能反复选 Freeze 等无进展动作；
                # 同一回合动作过多时强制 EndTurn（真实训练由搜索价值学习解决）。
                if steps_in_turn >= 8:
                    legal = np.nonzero(mask)[0]
                    action = 0 if mask[0] else int(legal[0])
                    pi = np.zeros(245, dtype=np.float32)
                    pi[action] = 1.0
                    stats = {"forced_end_turn": True}
                else:
                    pi, action, stats = search(game, p, evaluator, cfg)
                game_samples.append((p, f, c, mask, pi))
                game.step(p, action)
                decisions += 1
                acted = True
                guard += 1
                if steps_in_turn >= 8:
                    steps_in_turn = 0
                else:
                    steps_in_turn += 1
                if game.turn != last_turn:
                    last_turn = game.turn
                    steps_in_turn = 0
                if guard > 10000:
                    raise RuntimeError("game guard")
            if not acted:
                break
        placements = game.placements()
        for (p, f, c, mask, pi) in game_samples:
            feats.append(f.astype(np.float16))
            cards.append(np.asarray(c, dtype=np.int16))
            masks.append(np.asarray(mask, dtype=np.uint8))
            pis.append(np.asarray(pi, dtype=np.float16))
            ranks.append(int(placements[p]))
            seats.append(int(p))
        if (gi + 1) % 10 == 0:
            dt = time.time() - t0
            print(f"[collect] {gi+1}/{games} games, {decisions} decisions, {dt:.1f}s", flush=True)
    dt = time.time() - t0
    data = {
        "features": np.stack(feats),
        "cards": np.stack(cards),
        "masks": np.stack(masks),
        "pi": np.stack(pis),
        "rank": np.asarray(ranks, dtype=np.uint8),
        "seat": np.asarray(seats, dtype=np.uint8),
        "meta": np.asarray([{"games": games, "sims": sims, "seed": seed,
                             "decisions": decisions, "seconds": dt}], dtype=object),
    }
    return data, dt


def train(net: AZNet, data, epochs: int, batch: int, lr: float, device: str):
    features = data["features"]
    pi = data["pi"].astype(np.float32)
    rank = data["rank"].astype(np.int64)
    n = len(rank)
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    net.to(device).train()
    idx = np.arange(n)
    rng = np.random.default_rng(1234)
    logs = []
    for epoch in range(epochs):
        rng.shuffle(idx)
        total = 0.0
        nb = 0
        for start in range(0, n, batch):
            sel = idx[start:start + batch]
            x = torch.from_numpy(features[sel].astype(np.float32)).to(device)
            target_pi = torch.from_numpy(pi[sel]).to(device)
            target_rank = torch.from_numpy(rank[sel]).to(device)
            logits, vlog = net(x)
            loss_p = -(target_pi * F.log_softmax(logits, dim=-1)).sum(dim=-1).mean()
            loss_v = F.cross_entropy(vlog, target_rank - 1)
            loss = loss_p + loss_v
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0)
            opt.step()
            total += float(loss.item())
            nb += 1
        logs.append({"epoch": epoch + 1, "loss": total / max(nb, 1)})
        print(f"[train] epoch {epoch+1}: loss={logs[-1]['loss']:.4f}", flush=True)
    return logs


def evaluate(net: AZNet, games: int, seed: int, device: str):
    evaluator = make_evaluator(net, device)
    ranks = []
    t0 = time.time()
    for gi in range(games):
        game = E.Game(seed=seed + 10_000 + gi)
        guard = 0
        last_turn = game.turn
        steps_in_turn = 0
        while not game.is_over():
            acted = False
            for p in range(game.num_players):
                if not game.needs_action(p):
                    continue
                if p == 0:
                    f_raw, c_raw = game.observe(0)
                    f = np.frombuffer(f_raw, dtype="<f4").copy()
                    c = np.frombuffer(c_raw, dtype="<i4").copy()
                    mask = np.frombuffer(game.legal_mask(0), dtype=np.uint8).astype(bool)
                    if steps_in_turn >= 8:
                        legal = np.nonzero(mask)[0]
                        action = 0 if mask[0] else int(legal[0])
                    else:
                        policy, _ = evaluator(f, c, mask, 0)
                        action = int(np.argmax(policy))
                    game.step(0, action)
                else:
                    game.bot_play(p)
                acted = True
                guard += 1
                if game.turn != last_turn:
                    last_turn = game.turn
                    steps_in_turn = 0
                else:
                    steps_in_turn += 1
                if guard > 20000:
                    raise RuntimeError("eval guard")
            if not acted:
                break
        ranks.append(int(game.placements()[0]))
    dt = time.time() - t0
    arr = np.asarray(ranks, dtype=np.float32)
    return {"games": games, "mean_rank": float(arr.mean()), "top4_rate": float((arr <= 4).mean()),
            "win_rate": float((arr == 1).mean()), "seconds": dt,
            "rank_counts": {int(k): int(v) for k, v in Counter(ranks).items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--sims", type=int, default=2)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--eval-games", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=str, default="runs/az_smoke")
    ap.add_argument("--device", type=str, default="cpu")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    print("engine:", E.game_version(), E.db_info(), flush=True)

    net = AZNet().to(args.device)
    t_start = time.time()
    data, collect_s = collect(args.games, args.sims, args.seed, net, args.device)
    data_path = os.path.join(args.out, "data.npz")
    np.savez_compressed(data_path, **{k: v for k, v in data.items() if k != "meta"})
    print(f"[data] {data['features'].shape[0]} samples -> {data_path} ({collect_s:.1f}s)", flush=True)

    train_s = time.time()
    logs = train(net, data, args.epochs, args.batch, args.lr, args.device)
    train_s = time.time() - train_s
    ckpt = os.path.join(args.out, "model.pt")
    save_checkpoint(net, ckpt, meta={"games": args.games, "sims": args.sims,
                                     "epochs": args.epochs, "seed": args.seed})
    print(f"[ckpt] {ckpt}", flush=True)

    metrics = evaluate(net, args.eval_games, args.seed, args.device)
    report = {
        "engine": {"game_version": E.game_version(), "cards": E.db_info()[0]},
        "args": vars(args),
        "collect_seconds": collect_s,
        "train_seconds": train_s,
        "total_seconds": time.time() - t_start,
        "samples": int(data["features"].shape[0]),
        "decisions": int(data["meta"][0]["decisions"]),
        "train_log": logs,
        "eval": metrics,
    }
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("[done]", json.dumps({k: report[k] for k in ("samples", "decisions", "collect_seconds",
                                                       "train_seconds", "total_seconds")},
                               ensure_ascii=False), flush=True)
    print("[eval]", json.dumps(metrics, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
