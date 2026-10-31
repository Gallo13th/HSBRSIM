#!/usr/bin/env python3
"""采集侧吞吐 profile / A/B 小规模跑（CPU，单进程锁步，不占训练 GPU）。

两个子命令：

- ``micro``：直接对热函数做微基准（``inject_quasi_state`` / ``archetype.bias`` /
  ``archetype.parse_obs``），给出 µs/次；
- ``lockstep``：用真实 checkpoint + ``BatchLeafServer`` 跑
  :func:`hsbg.az.train.parallel_collect.collect_ppo_lockstep`，可选 ``cProfile``
  输出 top-N 累计耗时（复现训练 worker 里的同一条热路径）。

用法：
  PY=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
  $PY scripts/bench_collect_profile.py lockstep --games 32 --iters 3 --device cpu
  $PY scripts/bench_collect_profile.py lockstep --games 32 --profile runs/profile_collect/
  $PY scripts/bench_collect_profile.py micro --n 200
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
import random
import sys
import time
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402


# ─────────────────────────── micro ───────────────────────────
def _micro(args: argparse.Namespace) -> int:
    import hsbg_engine as E
    from hsbg.az.train import human_obs_full as HOF
    from hsbg.az.train.human_board_pool import load_pool

    pool = load_pool(args.human_boards, sample="auto")
    assert pool is not None
    rows = [b for t in sorted(pool.index) for b in pool.index[t] if b.payload]
    rng = random.Random(7)
    picks = [rows[rng.randrange(len(rows))] for _ in range(64)]

    for fid in ("board", "hand", "full"):
        # 同一个 Game 反复注入同一座位（与训练循环一致：局内复用 game，注入后复位 ended）
        g = E.Game(seed=11)
        pays = [pool.sample_payload(int(p.turn), rng=random.Random(i)) or p.payload
                for i, p in enumerate(picks)]
        # 预热（模板缓存 / 卡表 / 池）
        for p in pays[:8]:
            HOF.inject_quasi_state(g, 2, p, fid, reset_ended=True)
        n = int(args.n)
        t0 = time.perf_counter()
        for i in range(n):
            HOF.inject_quasi_state(g, 2, pays[i % len(pays)], fid, reset_ended=True)
        dt = (time.perf_counter() - t0) / n
        print(f"inject_quasi_state fidelity={fid:5s}: {dt * 1e6:9.1f} us/seat")

    # payload 采样本身
    t0 = time.perf_counter()
    n = int(args.n) * 20
    for i in range(n):
        pool.sample_payload(int(rng.choice(pool.turns())), rng=rng)
    print(f"HumanBoardPool.sample_payload       : "
          f"{(time.perf_counter() - t0) / n * 1e6:9.1f} us/call")

    # ── archetype bias ──
    from hsbg.az.train.archetype_bias import (ArchetypeBias, bucket_of,  # noqa: PLC0415
                                             parse_obs)
    from hsbg.az.train.common import mask_from_bytes, obs_arrays  # noqa: PLC0415
    g = E.Game(seed=3)
    # 打几个 bot 动作，让场面有内容
    for _ in range(30):
        if g.is_over():
            break
        for s in range(8):
            if g.needs_action(s):
                g.bot_play(s)
                break
    ab = ArchetypeBias(coef=float(args.ab_coef), min_prob=0.6)
    f, c = obs_arrays(g.observe(0))
    m = mask_from_bytes(g.legal_mask(0))
    parse_obs(f, c)   # 预热
    t0 = time.perf_counter()
    n = int(args.n) * 20
    for i in range(n):
        parse_obs(f, c, hero_id_of=ab.card_id_of)
    print(f"archetype.parse_obs                 : "
          f"{(time.perf_counter() - t0) / n * 1e6:9.1f} us/call")
    t0 = time.perf_counter()
    for i in range(n // 20):
        ab.bias(f, c, m, game_id=f"g{i}", seat=0)
    print(f"archetype.bias (含 parse/vector/2×clf): "
          f"{(time.perf_counter() - t0) / (n // 20) * 1e6:9.1f} us/call")
    print(f"  mask_legal={int(m.sum())}")
    return 0


# ─────────────────────────── lockstep ───────────────────────────
def _patch_arch_ref() -> None:
    """把流派特征/偏好换回优化前的参考实现（端到端等价性验证用）。"""
    from tests import test_archetype_fast as T
    from hsbg.az.train import archetype_bias as AB

    def _parse(features, cards, *, hero_id_of=None):
        return T.parse_obs_ref(features, cards, hero_id_of=hero_id_of)

    def _vector(st, obs, *, hero_vocab=(), hero_index=None):
        return T.build_vector_ref(st, obs, hero_vocab=hero_vocab)

    def _pref(pref, base, obs, mask, *, coef, card_index_of=None, cards=None):
        return T.bias_from_pref_ref(pref, base, obs, mask, coef=coef,
                                    card_index_of=card_index_of, cards=cards)

    AB.parse_obs = _parse
    AB.build_vector = _vector
    AB.bias_from_pref = _pref
    print("[bench] archetype 已切到**优化前参考实现**（逐位对照用）", flush=True)


def _build(args: argparse.Namespace):
    import torch
    torch.set_num_threads(int(args.torch_threads))
    from hsbg.az.train.batch_eval import BatchLeafServer, BatchPPOEvaluator
    from hsbg.az.train.model import load_checkpoint

    dev = str(args.device)
    model, meta = load_checkpoint(args.checkpoint, device=dev)
    norm_mean, norm_std = meta.get("norm_mean"), meta.get("norm_std")
    server = BatchLeafServer(
        model, device=dev, batch_size=int(args.batch_size),
        max_wait_ms=float(args.leaf_wait_ms), queue_size=8192,
        norm_mean=norm_mean, norm_std=norm_std)
    evaluator = BatchPPOEvaluator(server)

    from hsbg.az.train.human_board_pool import load_pool as load_human
    from hsbg.az.train.mirror_snapshots import load_pool as load_mirror
    hpool = (load_human(args.human_boards, sample=args.human_board_sample)
             if args.human_p > 0 and args.human_boards else None)
    mpool = (load_mirror(args.mirror_snaps, sample=args.mirror_sample)
             if args.mirror_p > 0 and args.mirror_snaps else None)
    return model, meta, server, evaluator, hpool, mpool, norm_mean, norm_std


def _null_evaluator():
    """纯 Python 的确定性「假前向」：不跑模型，只按输入特征哈希选合法动作。

    用途：把 GPU/CPU 前向从 wall 里剔掉，得到**采集侧 Python/引擎**的真实成本，
    便于逐项归因（fast/慢路径输入相同时动作序列仍逐位相同）。
    """
    import hashlib

    class _Null:
        name = "null"
        accepts_game = False

        def act_batch(self, F, C, M, temperature=1.0, seed=None, bias=None):
            n = int(len(F))
            acts = np.zeros(n, dtype=np.int64)
            lps = np.zeros(n, dtype=np.float32)
            vals = np.zeros(n, dtype=np.float32)
            s = int(seed or 0)
            for i in range(n):
                legal = np.flatnonzero(M[i])
                if legal.size == 0:
                    continue
                fb = np.ascontiguousarray(F[i])
                h = int.from_bytes(hashlib.blake2b(fb.tobytes(), digest_size=8).digest(),
                                   "little")
                acts[i] = int(legal[(h ^ s) % legal.size])
                lps[i] = -1.0
            return acts, lps, vals

        def __call__(self, features, cards, mask, seat=0):
            raise RuntimeError("null evaluator 只支持 act/act_batch")

        def act(self, features, cards, mask, temperature=1.0, seed=None, bias=None):
            a, lp, v = self.act_batch(np.asarray([features]), np.asarray([cards]),
                                      np.asarray([mask]), temperature, seed, bias)
            return int(a[0]), float(lp[0]), float(v[0])

    return _Null()


def _run_once(args: argparse.Namespace, *, idx: int, model, evaluator, hpool, mpool,
              norm_mean, norm_std) -> Dict[str, Any]:
    from hsbg.az.train.parallel_collect import collect_ppo_lockstep
    from hsbg.az.train.ppo import CollectConfig

    cfg = CollectConfig(
        games=int(args.games), seed=int(args.seed) + idx * 1000,
        opponent="bot", behavior="net", lockstep=True,
        fast_act=True,
        move_guard=bool(int(args.move_guard)),
        move_cap=int(args.move_cap),
        move_repeat_limit=int(args.move_repeat_limit),
        archetype_bias_coef=float(args.ab_coef),
        archetype_min_prob=0.6,
        leaf_wait_ms=float(args.leaf_wait_ms),
        seq_aux=bool(int(args.seq_coef != 0)),
        shaping_coef=0.0,
        human_boards=str(args.human_boards),
        human_board_p=float(args.human_p),
        human_board_seats=int(args.human_seats),
        human_board_sample=str(args.human_board_sample),
        human_board_set_tier=True,
        human_board_fidelity=str(args.human_fidelity),
        human_board_fast_inject=bool(int(args.fast_inject)),
        mirror_snaps=str(args.mirror_snaps),
        mirror_seats=int(args.mirror_seats),
        mirror_p=float(args.mirror_p),
        mirror_sample=str(args.mirror_sample),
        mirror_seat_random=bool(int(args.mirror_seat_random)),
    )
    _srv = getattr(evaluator, "server", None)
    _f0 = float((_srv.stats or {}).get("forward_s", 0.0)) if _srv is not None else 0.0
    t0 = time.perf_counter()
    records, meta = collect_ppo_lockstep(
        model, cfg, eval_fn=evaluator, device=str(args.device),
        seed=int(args.seed) + idx * 1000, games=int(args.games), gamemode="bot",
        norm_mean=norm_mean, norm_std=norm_std,
        human_board_pool=hpool, human_board_p=float(args.human_p),
        human_board_seats=int(args.human_seats),
        human_board_sample=str(args.human_board_sample),
        human_board_set_tier=True,
        human_board_fidelity=str(args.human_fidelity),
        human_board_fast_inject=bool(int(args.fast_inject)),
        mirror_pool=mpool, mirror_seats_count=int(args.mirror_seats),
        mirror_p=float(args.mirror_p),
        mirror_seat_random=bool(int(args.mirror_seat_random)),
    )
    dt = time.perf_counter() - t0
    _f1 = float((_srv.stats or {}).get("forward_s", 0.0)) if _srv is not None else 0.0
    dec = int(meta.get("decisions", 0))
    # 记录指纹：同 seed 下 fast/慢路径必须**完全相同**（动作/特征/价值/名次逐位）
    import hashlib
    h = hashlib.sha256()
    for r in records:
        h.update(str(r.get("game_id")).encode())
        h.update(b"|")
        h.update(int(r.get("action", -1)).to_bytes(8, "little", signed=True))
        h.update(np.asarray(r.get("features")).tobytes())
        h.update(np.asarray([float(r.get("value", 0.0))], dtype=np.float64).tobytes())
        h.update(int(r.get("rank", 0)).to_bytes(4, "little", signed=True))
    out = {"seconds": dt, "decisions": dec,
           "dec_per_s": (dec / dt if dt > 0 else 0.0),
           "records": int(len(records)),
           "fwd_s": float(_f1 - _f0),
           "py_s": float(dt - (_f1 - _f0)),
           "records_sha": h.hexdigest()[:16]}
    for k in ("human_board_attempt", "human_board_applied", "human_board_rejected",
              "human_board_missing", "human_board_hand_applied",
              "human_board_counters_applied", "human_board_payload_rows",
              "mirror_attempt", "mirror_applied", "mirror_rejected",
              "archetype_detected", "archetype_bias_applied", "archetype_decisions"):
        if k in meta:
            out[k] = meta[k]
    return out


def _lockstep(args: argparse.Namespace) -> int:
    if bool(int(getattr(args, "arch_ref", 0))):
        _patch_arch_ref()
    model, meta, server, evaluator, hpool, mpool, nm, ns = _build(args)
    if bool(int(args.null_eval)):
        evaluator = _null_evaluator()
    print(f"[bench] ckpt={args.checkpoint} device={args.device} games={args.games} "
          f"human_p={args.human_p} fid={args.human_fidelity} ab={args.ab_coef} "
          f"mirror_p={args.mirror_p}", flush=True)
    # 预热一局，避免把首次模板/卡表加载计入
    _run_once(args, idx=-1, model=model, evaluator=evaluator, hpool=hpool,
              mpool=mpool, norm_mean=nm, norm_std=ns)
    rows: List[Dict[str, Any]] = []
    prof_path = str(args.profile or "")
    if prof_path:
        os.makedirs(prof_path, exist_ok=True)
        pr = cProfile.Profile()
        pr.enable()
        rows.append(_run_once(args, idx=0, model=model, evaluator=evaluator,
                              hpool=hpool, mpool=mpool, norm_mean=nm, norm_std=ns))
        pr.disable()
        s = io.StringIO()
        st = pstats.Stats(pr, stream=s).sort_stats("cumulative")
        st.print_stats(int(args.top))
        txt = s.getvalue()
        with open(os.path.join(prof_path, "profile.txt"), "w", encoding="utf-8") as f:
            f.write(txt)
        pr.dump_stats(os.path.join(prof_path, "profile.pstats"))
        print(txt[:200 + 200 * int(args.top)], flush=True)
        # 精确 top-N（按 cumtime）另存一份 JSON 便于写报告
        rows_sorted = []
        for (fn, _ln, name), (cc, nc, tt, ct, _callers) in st.stats.items():
            rows_sorted.append({"func": f"{name} ({os.path.basename(fn)}:{_ln})",
                                "ncalls": int(nc), "tottime_s": float(tt),
                                "cumtime_s": float(ct)})
        rows_sorted.sort(key=lambda r: -r["cumtime_s"])
        with open(os.path.join(prof_path, "top.json"), "w", encoding="utf-8") as f:
            json.dump(rows_sorted[: int(args.top)], f, indent=1, ensure_ascii=False)
    for i in range(int(args.iters)):
        rows.append(_run_once(args, idx=i, model=model, evaluator=evaluator,
                              hpool=hpool, mpool=mpool, norm_mean=nm, norm_std=ns))
    for i, r in enumerate(rows):
        print(f"[iter {i:2d}] wall={r['seconds']:7.3f}s dec={r['decisions']:6d} "
              f"dec/s={r['dec_per_s']:8.1f} rec={r['records']:6d} "
              f"fwd={r.get('fwd_s', 0):6.2f}s py={r.get('py_s', 0):6.2f}s "
              f"sha={r['records_sha']}", flush=True)
    good = [r for r in rows]
    if good:
        med = float(np.median([r["dec_per_s"] for r in good]))
        print(f"[summary] n={len(good)} median_dec_per_s={med:.1f} "
              f"mean_seconds={float(np.mean([r['seconds'] for r in good])):.3f}")
    out = {"args": vars(args), "iters": rows}
    if args.out:
        os.makedirs(os.path.dirname(str(args.out)) or ".", exist_ok=True)
        with open(str(args.out), "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("micro")
    m.add_argument("--n", type=int, default=200)
    m.add_argument("--human-boards",
                   default="data/real_library/library_real_quasi_full.jsonl")
    m.add_argument("--ab-coef", type=float, default=0.5)
    m.set_defaults(func=_micro)

    lk = sub.add_parser("lockstep")
    lk.add_argument("--games", type=int, default=32)
    lk.add_argument("--iters", type=int, default=3)
    lk.add_argument("--seed", type=int, default=20100)
    lk.add_argument("--device", default="cpu")
    lk.add_argument("--torch-threads", type=int, default=1)
    lk.add_argument("--checkpoint", default="runs/az_entity_s14/model.pt")
    lk.add_argument("--batch-size", type=int, default=64)
    lk.add_argument("--leaf-wait-ms", type=float, default=1.0)
    lk.add_argument("--human-boards",
                    default="data/real_library/library_real_quasi_full.jsonl")
    lk.add_argument("--human-p", type=float, default=0.9)
    lk.add_argument("--human-seats", type=int, default=5)
    lk.add_argument("--human-fidelity", default="full")
    lk.add_argument("--fast-inject", type=int, default=0)
    lk.add_argument("--arch-ref", type=int, default=0,
                    help="1=流派特征/偏好退回优化前参考实现（逐位等价对照）")
    lk.add_argument("--null-eval", type=int, default=0,
                    help="1=用确定性假前向（纯 Python），把前向从 wall 里剔除")
    lk.add_argument("--human-board-sample", default="auto")
    lk.add_argument("--mirror-snaps", default="runs/library/snaps_champ")
    lk.add_argument("--mirror-p", type=float, default=0.2)
    lk.add_argument("--mirror-seats", type=int, default=2)
    lk.add_argument("--mirror-sample", default="p75")
    lk.add_argument("--mirror-seat-random", type=int, default=1)
    lk.add_argument("--move-guard", type=int, default=1)
    lk.add_argument("--move-cap", type=int, default=3)
    lk.add_argument("--move-repeat-limit", type=int, default=2)
    lk.add_argument("--ab-coef", type=float, default=0.5)
    lk.add_argument("--seq-coef", type=float, default=0.05)
    lk.add_argument("--profile", default="")
    lk.add_argument("--top", type=int, default=20)
    lk.add_argument("--out", default="")
    lk.set_defaults(func=_lockstep)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
