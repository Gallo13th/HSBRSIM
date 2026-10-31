#!/usr/bin/env python3
"""在**纯经济沙盒**里生成搜索标签 ``obs → π_search``（PUCT/MCTS），供离线 BC 用。

流程
----
1. （可选，强烈建议）``--fit-value-games N``：先用当前策略在沙盒里跑 N 局，把
   entity 的 **scalar value 头**拟合到 ``L_T - L(s)``（trunk 冻结，只训头）。
   完整游戏 checkpoint（s14/s16）在训练里 ``value_head_coef=0``（只训 rank 头），
   标量头≈随机初始化，直接当叶评估等于噪声。拟合后的头写回 checkpoint
   （``--value-out``），后续搜索与 BC 都用它。
2. 跑 ``--games`` 局（gold 10 / 30 各一半），每步：
   - 策略头给先验 π_base；``should_search`` 判定是否关键决策；
   - 关键决策跑 PUCT（``--search-sims`` / ``--search-topk`` / ``--search-depth``），
     根访问分布 = π_search；其余步 π_search = π_base；
   - 按 π_search 采样动作（``--action-mode sample``）继续这一局。
3. 每步写一条记录（obs float16 / cards int16 / mask packbits + 稀疏 π + 搜索统计），
   整局结束写一条 episode 汇总；最后写 summary（延迟 / KL / top-1 一致率）。

用法::

  PYTHONPATH=rust/python:. python scripts/gen_sandbox_search_labels.py \
      --checkpoint runs/az_entity_s14/model.pt --device cuda:7 \
      --games 500 --envs 16 --search-sims 128 --search-topk 8 --search-depth 1 \
      --fit-value-games 96 --out data/search_labels/sandbox_labels.jsonl.gz
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import math
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hsbg.az.train.economy_sandbox import (END_TURN, N_ACTIONS, OBS_CARDS,  # noqa: E402
                                           OBS_FLOATS, SEAT, EconomySandbox,
                                           SandboxConfig, SandboxObs, carrier_ids,
                                           stack_obs)
from hsbg.az.train.sandbox_search import (SearchConfig, SearchResult,  # noqa: E402
                                          SearchRunner, action_kind,
                                          should_search)

STRENGTH_REF = 30000.0


def _torch():
    import torch
    return torch


def _L(sigma: float) -> float:
    return math.log1p(max(0.0, float(sigma))) / math.log1p(STRENGTH_REF)


def sigmas_from_features(feats: np.ndarray) -> np.ndarray:
    """批量从 3227 观测解码战团 Σ（与 ``EconomySandbox.sigma_from_features`` 同口径）。"""
    b = np.asarray(feats, dtype=np.float32)[:, 68:285].reshape(len(feats), 7, 31)
    present = b[:, :, 0] > 0.5
    sig = (b[:, :, 1] + b[:, :, 2]) * present
    return np.rint(sig.sum(axis=1) * 10.0).astype(np.int32)


#: obs_std 冻结契约：board 卡牌块 = cards[19:26]，tier = features[10] * 6（见 hsbg/env/obs_std.py）
_CARD_BOARD_SLICE = (19, 26)
_G_TIER = 10
_G_TIER_SCALE = 6.0


def build_card_id_map() -> Dict[int, str]:
    """cid -> 卡 id（载体识别用）；引擎不可用时返回空表。"""
    try:
        import hsbg_engine as E
        return {int(c["cid"]): str(c["id"]) for c in json.loads(E.catalog_json())}
    except Exception:  # noqa: BLE001 - 无引擎时标签里 carriers 恒 0（不阻断）
        return {}


def obs_meta(feats: np.ndarray, cards: np.ndarray, cid2id: Dict[int, str],
             carrier_ids: set) -> Tuple[int, int]:
    """从观测解出 ``(tier, 载体在场数)``（与 ``economy_sandbox.measure`` 同口径，纯解码）。"""
    tier = int(round(float(np.asarray(feats)[_G_TIER]) * _G_TIER_SCALE))
    board = np.asarray(cards, dtype=np.int64)[_CARD_BOARD_SLICE[0]:_CARD_BOARD_SLICE[1]]
    carriers = sum(1 for cid in board if int(cid) > 0 and cid2id.get(int(cid)) in carrier_ids)
    return max(0, int(tier)), int(carriers)


# ── obs 编解码（标签文件用；float16 省一半空间）──────────────────────────────


def encode_obs(obs: SandboxObs) -> Dict[str, str]:
    f16 = np.ascontiguousarray(obs.features, dtype=np.float16)
    c16 = np.ascontiguousarray(obs.cards, dtype=np.int16)
    packed = np.packbits(np.ascontiguousarray(obs.mask, dtype=np.uint8))
    return {"f16": base64.b64encode(f16.tobytes()).decode("ascii"),
            "cards": base64.b64encode(c16.tobytes()).decode("ascii"),
            "mask": base64.b64encode(packed.tobytes()).decode("ascii")}


def decode_obs(rec: Dict[str, str]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """标签记录 -> ``(features f32[3227], cards i32[124], mask bool[245])``。"""
    f = np.frombuffer(base64.b64decode(rec["f16"]), dtype=np.float16).astype(np.float32)
    c = np.frombuffer(base64.b64decode(rec["cards"]), dtype=np.int16).astype(np.int32)
    m = np.unpackbits(np.frombuffer(base64.b64decode(rec["mask"]), dtype=np.uint8),
                      count=N_ACTIONS).astype(bool)
    return f, c, m


def topk_pi(pi: np.ndarray, k: int = 8) -> List[List[float]]:
    p = np.asarray(pi, dtype=np.float64)
    nz = np.flatnonzero(p > 0)
    if nz.size == 0:
        return []
    order = nz[np.argsort(-p[nz])][:int(k)]
    return [[int(a), round(float(p[a]), 6)] for a in order]


def kl_nats(p: np.ndarray, q: np.ndarray) -> float:
    """KL(p‖q)（只在 p>0 的动作上求和；两者都按各自合法支撑归一）。"""
    p = np.asarray(p, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    sp, sq = float(p.sum()), float(q.sum())
    if sp <= 0 or sq <= 0:
        return 0.0
    p = p / sp
    q = q / sq
    mask = p > 0
    return float(np.sum(p[mask] * (np.log(p[mask]) - np.log(np.maximum(q[mask], 1e-12)))))


# ── 价值头拟合 ──────────────────────────────────────────────────────────────


def _forward_global(model, device: str, feats: np.ndarray, cards: np.ndarray,
                    masks: np.ndarray, chunk: int = 128) -> np.ndarray:
    """批量取 entity trunk 的 global token ``g``（value 头的输入）。"""
    torch = _torch()
    n = len(masks)
    d = int(getattr(model, "d_model", 0) or 0)
    out = None
    with torch.no_grad():
        for s in range(0, n, chunk):
            e = min(n, s + chunk)
            f = torch.from_numpy(np.ascontiguousarray(feats[s:e], dtype=np.float32)).to(device)
            c = torch.from_numpy(np.ascontiguousarray(cards[s:e], dtype=np.int64)).to(device)
            m = torch.from_numpy(np.ascontiguousarray(masks[s:e], dtype=bool)).to(device)
            g = model.forward_global(f, c, m)
            g = g.float().cpu().numpy()
            if out is None:
                d = int(g.shape[1])
                out = np.empty((n, d), dtype=np.float32)
            out[s:e] = g
    return out if out is not None else np.zeros((0, d), dtype=np.float32)


def collect_value_data(model, runner: SearchRunner, device: str, games: int,
                       golds: Sequence[int], seed0: int, n_envs: int,
                       dtype: str = "fp32") -> Dict[str, np.ndarray]:
    """跑 ``games`` 局（按 π_base 采样），收集 ``(g, L, L_T, gold)``。"""
    gs: List[np.ndarray] = []
    Ls: List[np.ndarray] = []
    LTs: List[np.ndarray] = []
    gold_list: List[np.ndarray] = []
    t0 = time.time()
    done_games = 0
    while done_games < games:
        batch = min(int(n_envs), games - done_games)
        envs: List[EconomySandbox] = []
        obs: List[SandboxObs] = []
        rngs: Dict[int, np.random.Generator] = {}
        for j in range(batch):
            gold = int(golds[(done_games + j) % len(golds)])
            env = EconomySandbox(SandboxConfig(gold_per_turn=gold))
            obs.append(env.reset(seed=seed0 + done_games + j))
            envs.append(env)
            rngs[j] = np.random.default_rng(seed0 + done_games + j)
        active = list(range(batch))
        per_game: Dict[int, List[Tuple[np.ndarray, int]]] = {j: [] for j in active}
        while active:
            f, c, m = stack_obs([obs[j] for j in active])
            priors, _v = runner.evaluate(f, c, m)
            g = _forward_global(model, device, f, c, m)
            sig = sigmas_from_features(f)
            acts = np.empty(len(active), dtype=np.int64)
            for idx, j in enumerate(active):
                p = priors[idx].astype(np.float64)
                p = p / max(float(p.sum()), 1e-12)
                acts[idx] = int(rngs[j].choice(N_ACTIONS, p=p))
                per_game[j].append((g[idx], int(sig[idx])))
            still = []
            for idx, j in enumerate(active):
                o, _r, d, info = envs[j].step(int(acts[idx]))
                obs[j] = o
                if d:
                    ep = info.get("episode") or envs[j].episode_summary()
                    LT = _L(ep.get("sigma_t15") or 0)
                    seq = per_game[j]
                    gs.append(np.stack([x[0] for x in seq]).astype(np.float32))
                    Ls.append(np.asarray([_L(x[1]) for x in seq], dtype=np.float32))
                    LTs.append(np.full(len(seq), LT, dtype=np.float32))
                    gold_list.append(np.full(len(seq), int(envs[j].gold_per_turn),
                                             np.int32))
                    done_games += 1
                else:
                    still.append(j)
            active = still
        print(f"[value] {done_games}/{games} games ({time.time() - t0:.1f}s)", flush=True)
    return {"g": np.concatenate(gs), "L": np.concatenate(Ls),
            "L_T": np.concatenate(LTs), "gold": np.concatenate(gold_list)}


def fit_value_head(model, data: Dict[str, np.ndarray], device: str, *,
                   epochs: int = 30, lr: float = 1e-3, batch: int = 4096,
                   val_frac: float = 0.15, seed: int = 0,
                   out: str = "", meta: Optional[Dict[str, Any]] = None
                   ) -> Dict[str, Any]:
    """在冻结 trunk 的 ``g`` 上拟合 ``tanh(head(g)) ≈ L_T - L(s)``。"""
    torch = _torch()
    g = np.asarray(data["g"], dtype=np.float32)
    y = np.asarray(data["L_T"] - data["L"], dtype=np.float32)
    n = len(g)
    rng = np.random.default_rng(seed)
    order = rng.permutation(n)
    n_val = max(1, int(round(n * float(val_frac)))) if n >= 20 else 0
    val = order[:n_val]
    tr = order[n_val:]
    d = int(g.shape[1])
    head = torch.nn.Sequential(torch.nn.Linear(d, 128), torch.nn.ReLU(),
                               torch.nn.Linear(128, 1)).to(device)
    opt = torch.optim.Adam(head.parameters(), lr=float(lr))
    gt = torch.from_numpy(g).to(device)
    yt = torch.from_numpy(y).to(device)
    hist = []
    for ep in range(int(epochs)):
        head.train()
        perm = torch.from_numpy(rng.permutation(len(tr))).to(device)
        tot, cnt = 0.0, 0
        for s in range(0, len(tr), int(batch)):
            idx = perm[s:s + int(batch)]
            pred = torch.tanh(head(gt[idx]).squeeze(1))
            loss = torch.nn.functional.mse_loss(pred, yt[idx])
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            tot += float(loss.detach().cpu()) * len(idx)
            cnt += len(idx)
        hist.append({"epoch": ep + 1, "mse": tot / max(1, cnt)})
    head.eval()
    with torch.no_grad():
        pred_all = torch.tanh(head(gt).squeeze(1)).cpu().numpy()
    stats: Dict[str, Any] = {
        "samples": int(n), "d": int(d),
        "train_mse": float(np.mean((pred_all[tr] - y[tr]) ** 2)),
        "val_mse": (float(np.mean((pred_all[val] - y[val]) ** 2)) if n_val else None),
        "corr": float(np.corrcoef(pred_all[tr], y[tr])[0, 1]) if len(tr) > 2 else None,
        "val_corr": (float(np.corrcoef(pred_all[val], y[val])[0, 1])
                     if n_val > 2 else None),
        "y_mean": float(y.mean()), "pred_mean": float(pred_all.mean()),
        "mse": float(np.mean((pred_all - y) ** 2)), "history": hist}
    # 写回模型（entity 的 forward 里是 tanh(value_head(g))）——**单独存**，
    # 不改标准 checkpoint 的 state_dict 结构（load_checkpoint 不认识 Sequential 头）。
    model.value_head = head
    model.eval()
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        torch.save({"state_dict": head.state_dict(), "d": int(d),
                    "hidden": 128, "fit": {k: v for k, v in stats.items()
                                           if k != "history"}}, out)
        stats["out"] = out
    return stats


def load_fitted_value_head(model, path: str, device: str = "cuda") -> Dict[str, Any]:
    """把拟合好的 value 头挂到模型上（``tanh(head(g))`` 与 entity forward 一致）。"""
    torch = _torch()
    payload = torch.load(path, map_location=device, weights_only=True)
    d = int(payload.get("d") or getattr(model, "d_model", 0))
    hidden = int(payload.get("hidden") or 128)
    head = torch.nn.Sequential(torch.nn.Linear(d, hidden), torch.nn.ReLU(),
                               torch.nn.Linear(hidden, 1))
    head.load_state_dict(payload["state_dict"])
    head.to(device)
    head.eval()
    model.value_head = head
    model.eval()
    return dict(payload.get("fit") or {})


# ── 主循环：生成标签 ────────────────────────────────────────────────────────


def _sample(pi: np.ndarray, rng: np.random.Generator) -> int:
    p = np.asarray(pi, dtype=np.float64)
    p = np.where(np.isfinite(p) & (p > 0), p, 0.0)
    s = float(p.sum())
    if s <= 0:
        return END_TURN
    return int(rng.choice(N_ACTIONS, p=p / s))


def generate(model, runner: SearchRunner, device: str, args,
             cfg_search: SearchConfig) -> Dict[str, Any]:
    torch = _torch()  # noqa: F841
    golds = [int(x) for x in str(args.golds).split(",") if str(x).strip()]
    out_path = str(args.out)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    summary: Dict[str, Any] = {"games_target": int(args.games), "golds": golds,
                               "search": {"sims": int(cfg_search.sims),
                                          "topk": int(cfg_search.topk),
                                          "depth": int(cfg_search.depth_turns),
                                          "max_per_turn": int(cfg_search.max_searches_per_turn),
                                          "value_mode": str(cfg_search.value_mode)},
                               "value_fit": args.value_fit_stats}
    n_done = 0
    n_steps = 0
    carrier_set = set(carrier_ids())
    cid2id = build_card_id_map()
    n_searched = 0
    t_start = time.time()
    kl_vals: List[float] = []
    agree: List[int] = []
    search_times: List[float] = []
    search_sims: List[int] = []
    fh = gzip.open(out_path, "wt", encoding="utf-8", compresslevel=6)

    def emit(rec: Dict[str, Any]) -> None:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    try:
        envs_n = int(args.envs)
        total = int(args.games)
        started = 0
        slots: List[Dict[str, Any]] = []

        def new_slot() -> Dict[str, Any]:
            nonlocal started
            gold = golds[started % len(golds)]
            seed = int(args.seed0) + started
            env = EconomySandbox(SandboxConfig(gold_per_turn=gold))
            obs0 = env.reset(seed=seed)
            started += 1
            return {"env": env, "obs": obs0, "seed": seed, "step": 0,
                    "searched_turn": 0, "last_turn": int(env.g.turn)}

        while len(slots) < envs_n and started < total:
            slots.append(new_slot())
        last_print = time.time()
        while slots:
            f, c, m = stack_obs([s["obs"] for s in slots])
            priors, values = runner.evaluate(f, c, m)
            # 1) 关键决策：只对这些槽跑搜索
            search_idx: List[int] = []
            for idx, slot in enumerate(slots):
                turn = int(slot["obs"].turn)
                if turn != slot["last_turn"]:
                    slot["last_turn"] = turn
                    slot["searched_turn"] = 0
                if should_search(slot["obs"], cfg_search,
                                 searched_this_turn=slot["searched_turn"],
                                 prior=priors[idx]):
                    search_idx.append(idx)
            results: Dict[int, SearchResult] = {}
            if search_idx:
                sub_envs = [slots[i]["env"] for i in search_idx]
                res = runner.run(sub_envs, f[search_idx], c[search_idx], m[search_idx],
                                 priors[search_idx], values[search_idx],
                                 seeds=[slots[i]["seed"] for i in search_idx])
                for k, i in enumerate(search_idx):
                    results[i] = res[k]
                    slots[i]["searched_turn"] += 1
            # 2) 选动作 + 写标签（obs 是动作前的状态）
            acts = np.empty(len(slots), dtype=np.int64)
            for idx, slot in enumerate(slots):
                rng = np.random.default_rng(
                    int(slot["seed"]) * 1000003 + slot["step"] * 7919)
                res = results.get(idx)
                if res is not None:
                    pi = res.pi
                    n_searched += 1
                    kl_vals.append(kl_nats(res.pi, priors[idx]))
                    agree.append(int(res.top1() == int(np.argmax(priors[idx]))))
                    search_times.append(float(res.elapsed_s))
                    search_sims.append(int(res.sims))
                else:
                    pi = priors[idx]
                acts[idx] = _sample(pi, rng)
                mt_tier, mt_car = obs_meta(f[idx], c[idx], cid2id, carrier_set)
                rec = {"type": "step", "seed": int(slot["seed"]),
                       "gold": int(slot["env"].gold_per_turn),
                       "turn": int(slot["obs"].turn), "step": int(slot["step"]),
                       "tier": int(mt_tier), "carriers": int(mt_car),
                       "action": int(acts[idx]),
                       "kind": action_kind(int(acts[idx])),
                       "searched": int(res is not None),
                       "pi": topk_pi(pi, int(args.label_topk)),
                       "pi_base": topk_pi(priors[idx], int(args.label_topk)),
                       "sigma": int(sigmas_from_features(f[idx:idx + 1])[0]),
                       "value": round(float(values[idx]), 4),
                       "obs": encode_obs(slot["obs"])}
                if res is not None:
                    rec["search"] = {"sims": int(res.sims),
                                     "seconds": round(float(res.elapsed_s), 5),
                                     "nodes": int(res.expanded_nodes),
                                     "leaf_calls": int(res.leaf_value_calls),
                                     "root_value": round(float(res.root_value), 4),
                                     "top1": int(res.top1())}
                emit(rec)
                n_steps += 1
            # 3) 推进 + 补位（保持 --envs 个活跃局；否则批尾只剩 1–2 局 → 搜索被串行化）
            keep: List[Dict[str, Any]] = []
            for idx, slot in enumerate(slots):
                env = slot["env"]
                o, _r, d, info = env.step(int(acts[idx]))
                slot["obs"] = o
                slot["step"] += 1
                if d:
                    ep = info.get("episode") or env.episode_summary()
                    emit({"type": "episode", "seed": int(slot["seed"]),
                          "gold": int(env.gold_per_turn),
                          "sigma_t12": int(ep.get("sigma_t12") or 0),
                          "sigma_t15": int(ep.get("sigma_t15") or 0),
                          "tier_final": int(ep.get("tier_final") or 0),
                          "carriers_max": int(ep.get("carriers_max") or 0),
                          "spells_t15": int(ep.get("spells_t15") or 0),
                          "tavern_buff_t15": int(ep.get("tavern_buff_t15") or 0),
                          "decisions": int(slot["step"])})
                    n_done += 1
                else:
                    keep.append(slot)
            slots = keep
            while len(slots) < envs_n and started < total:
                slots.append(new_slot())
            if time.time() - last_print > 30:
                last_print = time.time()
                print(f"[gen] games {n_done}/{total} steps={n_steps} searched={n_searched} "
                      f"active={len(slots)} elapsed={time.time() - t_start:.0f}s", flush=True)
    finally:
        fh.close()

    elapsed = time.time() - t_start
    summary.update({
        "games": int(n_done), "steps": int(n_steps), "searched_steps": int(n_searched),
        "search_ratio": (float(n_searched) / n_steps if n_steps else 0.0),
        "elapsed_s": round(float(elapsed), 1),
        "seconds_per_game": round(float(elapsed) / max(1, n_done), 3),
        "kl_pi_base_mean": (float(np.mean(kl_vals)) if kl_vals else None),
        "kl_pi_base_p50": (float(np.percentile(kl_vals, 50)) if kl_vals else None),
        "top1_agree_with_base": (float(np.mean(agree)) if agree else None),
        "search_seconds_per_decision_p50": (float(np.percentile(search_times, 50))
                                            if search_times else None),
        "search_sims_mean": (float(np.mean(search_sims)) if search_sims else None),
        "out": out_path})
    with open(os.path.splitext(out_path)[0] + ".summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="沙盒搜索标签（PUCT + BC 数据）")
    ap.add_argument("--checkpoint", default="runs/az_entity_s14/model.pt")
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--games", type=int, default=500)
    ap.add_argument("--golds", default="10,30", help="金币档位（按局轮转；默认 10,30 各半）")
    ap.add_argument("--seed0", type=int, default=960000)
    ap.add_argument("--envs", type=int, default=16, help="并行局数（lockstep 批）")
    ap.add_argument("--dtype", default="fp32", choices=["fp32", "bf16"])
    ap.add_argument("--label-topk", type=int, default=8,
                    help="标签里 π / π_base 的稀疏 top-k")
    # 搜索预算（任务口径）
    ap.add_argument("--search-sims", type=int, default=128)
    ap.add_argument("--search-topk", type=int, default=8)
    ap.add_argument("--search-depth", type=int, default=1, help="向前看几个回合")
    ap.add_argument("--search-max-plies", type=int, default=64)
    ap.add_argument("--search-c-puct", type=float, default=1.5)
    ap.add_argument("--search-max-per-turn", type=int, default=8)
    ap.add_argument("--search-value-mode", default="total", choices=["total", "raw"])
    ap.add_argument("--search-temperature", type=float, default=1.0)
    ap.add_argument("--search-no-skip-move", dest="search_skip_move", action="store_false",
                    default=True)
    # 价值头拟合
    ap.add_argument("--fit-value-games", type=int, default=0,
                    help=">0 时先跑 N 局拟合 scalar value 头（推荐 96）")
    ap.add_argument("--fit-value-epochs", type=int, default=30)
    ap.add_argument("--fit-value-envs", type=int, default=64)
    ap.add_argument("--value-out", default="runs/economy_sandbox/search_value/s14_vfit.pt")
    ap.add_argument("--value-head", default="",
                    help="直接加载已拟合好 value 头的 checkpoint（与 --checkpoint 同架构）")
    ap.add_argument("--out", default="data/search_labels/sandbox_labels.jsonl.gz")
    ap.add_argument("--limit-games", type=int, default=0, help="冒烟：只跑 N 局")
    args = ap.parse_args(argv)
    if int(args.limit_games) > 0:
        args.games = int(args.limit_games)

    from hsbg.az.train.model import load_checkpoint
    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    model.eval()
    print(f"[gen] ckpt={args.checkpoint} arch={meta.get('arch')} "
          f"d_model={meta.get('d_model')} layers={meta.get('n_layers')}", flush=True)
    cfg = SearchConfig(sims=int(args.search_sims), topk=int(args.search_topk),
                       depth_turns=int(args.search_depth),
                       max_plies=int(args.search_max_plies),
                       c_puct=float(args.search_c_puct),
                       max_searches_per_turn=int(args.search_max_per_turn),
                       value_mode=str(args.search_value_mode),
                       temperature=float(args.search_temperature),
                       skip_move=bool(args.search_skip_move))
    cfg.validate()
    runner = SearchRunner(model, device=args.device, cfg=cfg, dtype=str(args.dtype))

    args.value_fit_stats = None
    if str(args.value_head):
        args.value_fit_stats = load_fitted_value_head(model, str(args.value_head),
                                                      args.device)
        print(f"[gen] 载入拟合 value 头: {args.value_head}", flush=True)
    elif int(args.fit_value_games) > 0:
        t0 = time.time()
        data = collect_value_data(model, runner, args.device, int(args.fit_value_games),
                                  [int(x) for x in str(args.golds).split(",")],
                                  seed0=int(args.seed0) - 100000,
                                  n_envs=int(args.fit_value_envs), dtype=str(args.dtype))
        stats = fit_value_head(model, data, args.device,
                               epochs=int(args.fit_value_epochs),
                               out=str(args.value_out), meta=meta)
        stats["elapsed_s"] = round(time.time() - t0, 1)
        args.value_fit_stats = stats
        print(f"[gen] value 头拟合: val_mse={stats.get('val_mse')} "
              f"corr={stats.get('corr')} val_corr={stats.get('val_corr')} "
              f"-> {stats.get('out')}", flush=True)
    summary = generate(model, runner, args.device, args, cfg)
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
