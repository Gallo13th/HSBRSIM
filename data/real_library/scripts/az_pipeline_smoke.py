"""AZ-MCTS 训练管线 smoke（100 局级）：8 座自对弈 MCTS → 数据 → 训练 → 评测。

用途：在远程开发机验证“完整训练管线可运行”（不是强度/规模实验）。
- 搜索：`hsbg/search/engine_mcts.py`（Python 原型；搜索内对手用 bot，外层 8 座用搜索）；
- 网络：torch `AZNet`（可用时）或 numpy `NumpyAZNet`（无 torch 时自动回退）；
- 数据：每座位决策记录 (features, cards, mask, π, rank)；
- 训练：policy CE(π) + value CE(rank)，CPU/GPU；
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

import hsbg_engine as E
from hsbg.search.engine_mcts import MCTSConfig, search as py_search

try:
    import torch
    import torch.nn.functional as F
    TORCH = True
except Exception:  # noqa: BLE001
    torch = None
    F = None
    TORCH = False


RUST_SEARCH = hasattr(E, "mcts_search")


def rust_eval_adapter(evaluator):
    def eval_fn(features_bytes, cards_bytes, mask_bytes, seat):
        f = np.frombuffer(features_bytes, dtype="<f4")
        c = np.frombuffer(cards_bytes, dtype="<i4")
        m = np.frombuffer(mask_bytes, dtype=np.uint8).astype(bool)
        policy, value = evaluator(f, c, m, seat)
        return policy.astype(np.float32).tobytes(), float(value)
    return eval_fn


def decide(game, seat, evaluator, cfg, search_backend: str):
    if search_backend == "rust":
        pi_b, action, root_value, visits = E.mcts_search(
            game, seat, simulations=cfg.simulations, c_puct=cfg.c_puct,
            temperature=cfg.temperature, eval_fn=rust_eval_adapter(evaluator),
            seed=cfg.seed, dirichlet_alpha=cfg.dirichlet_alpha,
            dirichlet_epsilon=cfg.dirichlet_epsilon)
        pi = np.frombuffer(pi_b, dtype="<f4").copy()
        return pi, int(action), {"root_value": float(root_value), "visits": int(visits),
                                 "search": "rust"}
    pi, action, stats = py_search(game, seat, evaluator, cfg)
    stats["search"] = "python"
    return pi, action, stats


def make_backend(name: str) -> str:
    if name == "auto":
        return "torch" if TORCH else "numpy"
    if name == "torch" and not TORCH:
        raise RuntimeError("torch not available")
    return name


def make_net(backend: str, device: str):
    if backend == "torch":
        from hsbg.policy.std_net import AZNet
        return AZNet().to(device)
    from hsbg.policy.numpy_net import NumpyAZNet
    return NumpyAZNet(seed=0)


def net_evaluator(net, backend: str, device: str):
    if backend == "torch":
        from hsbg.policy.std_net import make_evaluator
        return make_evaluator(net, device)
    from hsbg.policy.numpy_net import make_evaluator
    return make_evaluator(net)


def save_net(net, backend: str, path: str, meta: dict):
    if backend == "torch":
        from hsbg.policy.std_net import save_checkpoint
        save_checkpoint(net, path, meta=meta)
    else:
        np.savez(path, **{k: getattr(net, k) for k in net.params})
        with open(path + ".json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)


def collect(games: int, sims: int, seed: int, net, backend: str, device: str,
            temperature: float = 1.0, search_backend: str = "auto", sample_stride: int = 1):
    evaluator = net_evaluator(net, backend, device)
    if search_backend == "auto":
        search_backend = "rust" if RUST_SEARCH else "python"
    if search_backend == "rust" and not RUST_SEARCH:
        raise RuntimeError("Rust mcts_search not available; rebuild hsbg_engine")
    cfg = MCTSConfig(simulations=sims, temperature=temperature, seed=seed)
    total_visits = 0
    decisions_by_seat = {}
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
                # 同一回合动作过多时强制 EndTurn（正式训练由搜索价值学习解决）。
                if steps_in_turn >= 8:
                    legal = np.nonzero(mask)[0]
                    action = 0 if mask[0] else int(legal[0])
                    pi = np.zeros(245, dtype=np.float32)
                    pi[action] = 1.0
                    stats = {"visits": 0}
                else:
                    pi, action, stats = decide(game, p, evaluator, cfg, search_backend)
                total_visits += int(stats.get("visits", 0))
                di = decisions_by_seat.get(p, 0)
                decisions_by_seat[p] = di + 1
                if sample_stride <= 1 or (di % sample_stride) == 0:
                    game_samples.append((p, f, c, mask, pi))
                game.step(p, action)
                decisions += 1
                acted = True
                guard += 1
                if game.turn != last_turn:
                    last_turn = game.turn
                    steps_in_turn = 0
                else:
                    steps_in_turn += 1
                if guard > 10000:
                    raise RuntimeError("game guard")
            if not acted:
                break
        placements = game.placements()
        for (p, f, c, mask, pi) in game_samples:
            feats.append(f.astype(np.float32))
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
    }
    meta = {"search": search_backend, "games_per_s": games / max(dt, 1e-9),
            "decisions": decisions, "samples": int(data["features"].shape[0]),
            "total_visits": total_visits}
    return data, dt, meta


def train(net, backend: str, data, epochs: int, batch: int, lr: float, device: str):
    features = data["features"]
    pi = data["pi"].astype(np.float32)
    rank = data["rank"].astype(np.int64)
    n = len(rank)
    rng = np.random.default_rng(1234)
    logs = []
    if backend == "torch":
        opt = torch.optim.Adam(net.parameters(), lr=lr)
        net.train()
        for epoch in range(epochs):
            idx = rng.permutation(n)
            total, nb = 0.0, 0
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
    else:
        net.fit_norm(features[::max(1, n // 5000)].astype(np.float32))
        opt = net.init_opt()
        t = 0
        for epoch in range(epochs):
            idx = rng.permutation(n)
            total, nb = 0.0, 0
            for start in range(0, n, batch):
                sel = idx[start:start + batch]
                t += 1
                loss = net.train_step(features[sel].astype(np.float32), pi[sel],
                                      rank[sel], opt, lr=lr, t=t)
                total += float(loss)
                nb += 1
            logs.append({"epoch": epoch + 1, "loss": total / max(nb, 1)})
            print(f"[train] epoch {epoch+1}: loss={logs[-1]['loss']:.4f}", flush=True)
    return logs


def evaluate(net, backend: str, games: int, seed: int, device: str):
    evaluator = net_evaluator(net, backend, device)
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


def evaluate_heuristic(games: int, seed: int):
    """seat0 = 引擎 heuristic bot；其余 bot；平均名次基线。"""
    ranks = []
    for gi in range(games):
        game = E.Game(seed=seed + 20_000 + gi)
        guard = 0
        while not game.is_over():
            acted = False
            for p in range(game.num_players):
                if not game.needs_action(p):
                    continue
                if p == 0:
                    game.step(0, int(game.bot_action(0)))
                else:
                    game.bot_play(p)
                acted = True
                guard += 1
                if guard > 20000:
                    raise RuntimeError("heuristic eval guard")
            if not acted:
                break
        ranks.append(int(game.placements()[0]))
    arr = np.asarray(ranks, dtype=np.float32)
    return {"games": games, "mean_rank": float(arr.mean()),
            "top4_rate": float((arr <= 4).mean()), "win_rate": float((arr == 1).mean())}


def data_quality(net, backend: str, data, device: str, limit: int = 2000):
    """在训练数据上评估 value 相关性 / policy top-1 与搜索 π 一致率。"""
    evaluator = net_evaluator(net, backend, device)
    n = len(data["rank"])
    idx = np.linspace(0, n - 1, min(limit, n)).astype(np.int64)
    values, utils, top1_ok, top1_n = [], [], 0, 0
    for i in idx:
        f = data["features"][i].astype(np.float32)
        c = data["cards"][i]
        m = data["masks"][i].astype(bool)
        pi = data["pi"][i].astype(np.float32)
        policy, value = evaluator(f, c, m, int(data["seat"][i]))
        values.append(value)
        utils.append(1.0 - 2.0 * (int(data["rank"][i]) - 1) / 7.0)
        if pi.argmax() == policy.argmax():
            top1_ok += 1
        top1_n += 1
    corr = float(np.corrcoef(values, utils)[0, 1]) if len(values) > 2 else 0.0
    return {"samples": int(top1_n), "value_rank_corr": corr,
            "policy_top1_agreement": top1_ok / max(top1_n, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--sims", type=int, default=2)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--eval-games", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=str, default="runs/az_smoke")
    ap.add_argument("--device", type=str, default="cpu")
    ap.add_argument("--backend", type=str, default="auto", choices=["auto", "torch", "numpy"])
    ap.add_argument("--search", type=str, default="auto", choices=["auto", "rust", "python"])
    ap.add_argument("--sample-stride", type=int, default=1,
                    help="每座位决策采样间隔（1=全采；>1 降低数据量）")
    args = ap.parse_args()
    backend = make_backend(args.backend)

    os.makedirs(args.out, exist_ok=True)
    if TORCH:
        torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    print("engine:", E.game_version(), E.db_info(), "backend:", backend, flush=True)

    net = make_net(backend, args.device)
    t_start = time.time()
    data, collect_s, collect_meta = collect(args.games, args.sims, args.seed, net, backend,
                                            args.device, search_backend=args.search,
                                            sample_stride=args.sample_stride)
    data_path = os.path.join(args.out, "data.npz")
    np.savez_compressed(data_path, **data)
    print(f"[data] {data['features'].shape[0]} samples -> {data_path} ({collect_s:.1f}s)",
          flush=True)

    train_t = time.time()
    logs = train(net, backend, data, args.epochs, args.batch, args.lr, args.device)
    train_s = time.time() - train_t
    ckpt = os.path.join(args.out, "model" + (".pt" if backend == "torch" else ".npz"))
    save_net(net, backend, ckpt,
             {"games": args.games, "sims": args.sims, "epochs": args.epochs,
              "seed": args.seed, "backend": backend})
    print(f"[ckpt] {ckpt}", flush=True)

    metrics = evaluate(net, backend, args.eval_games, args.seed, args.device)
    heur = evaluate_heuristic(args.eval_games, args.seed)
    quality = data_quality(net, backend, data, args.device)
    report = {
        "engine": {"game_version": E.game_version(), "cards": E.db_info()[0]},
        "backend": backend,
        "args": vars(args),
        "collect_seconds": collect_s,
        "train_seconds": train_s,
        "total_seconds": time.time() - t_start,
        "samples": int(data["features"].shape[0]),
        "decisions": int(collect_meta["decisions"]),
        "search": collect_meta["search"],
        "games_per_s": collect_meta["games_per_s"],
        "total_visits": collect_meta["total_visits"],
        "train_log": logs,
        "eval": metrics,
        "baseline_heuristic": heur,
        "data_quality": quality,
    }
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("[done]", json.dumps({k: report[k] for k in ("backend", "samples", "decisions",
                                                       "collect_seconds", "train_seconds",
                                                       "total_seconds")}, ensure_ascii=False),
          flush=True)
    print("[eval]", json.dumps(metrics, ensure_ascii=False), flush=True)
    print("[baseline]", json.dumps(heur, ensure_ascii=False), flush=True)
    print("[quality]", json.dumps(quality, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
