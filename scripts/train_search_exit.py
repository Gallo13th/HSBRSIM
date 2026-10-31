#!/usr/bin/env python3
"""最小 ExIt 蒸馏实验驱动：learner-DAgger + 优势加权软 ExIt + KL 信赖域。

按 ``docs/SEARCH_DISTILL_THEORY.md`` §5 / ``docs/SEARCH_EXIT.md`` 跑一个**独立**闭环
（不碰 ``runs/az_entity_*`` 的 PPO 主循环，只读起点 checkpoint）：

1. 固定起点 checkpoint（默认 ``runs/infer_search_ab/ckpt_s16b_snapshot.pt``，其 sha256
   与 256 局 AB 面板记录的完全一致 ⇒ before/search 两臂的数字可以直接复用）；
2. 每轮：π_base 行为在**完整游戏**（人类战团注入，与 256 局面板同口径）跑 ``--games``
   局 → 关键决策查询 1 回合 top-8 搜索 → 软标签 + 优势权重 → 蒸馏 1–2 epoch；
3. 每轮结束用 ``scripts/human_panel_eval.py --infer-search 0`` 在固定 128 局子面板
   （seed 420000、seats 0–3 × 32 局，与 256 局主面板前 4 seat 逐局相同）上测**关闭
   搜索**的配对 Δ，并给出该轮的 capture ratio；
4. 收尾：256 局（8 seat × 32）关闭搜索 / 开启搜索两臂 + ``quality_monitor`` 的
   t12/t15 Σ 与载体率，输出 capture ratio、CI 与门禁结论。

用法::

  PYTHONPATH=rust/python:. python scripts/train_search_exit.py \
      --rounds 6 --games 128 --device cuda:7 --out runs/search_exit

所有产物写 ``--out``；主训练目录只读。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEFAULT_CKPT = "runs/infer_search_ab/ckpt_s16b_snapshot.pt"
DEFAULT_BEFORE_JSON = "runs/infer_search_ab/human_base0.json"
DEFAULT_BEFORE_SEARCH_JSON = "runs/infer_search_ab/human_t1.json"
HUMAN_BOARDS = "data/real_library/library_real_degraded.jsonl"


# ══════════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════════
def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _dump(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _append_jsonl(path: str, row: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _ranks_from_panel(panel: Dict[str, Any]) -> List[int]:
    """从 ``human_panel_eval`` 的 panel dict 里按 seat 顺序拼出 rank 序列。"""
    ps = (panel.get("details") or {}).get("per_seat") or {}
    out: List[int] = []
    for k in sorted(ps, key=lambda x: int(str(x).split("_")[1])):
        seq = ((ps[k].get("model") or {}).get("rank_sequence") or [])
        out.extend(int(r) for r in seq)
    return out


def paired_stats(after: Sequence[int], before: Sequence[int], *,
                 n_boot: int = 20000, seed: int = 0) -> Dict[str, Any]:
    """配对 Δ = mean(after) − mean(before) 的 bootstrap 95% CI。"""
    a = np.asarray(after, dtype=np.float64)
    b = np.asarray(before, dtype=np.float64)
    if a.size != b.size or a.size == 0:
        return {"n": int(min(a.size, b.size)), "mean": None, "ci_low": None,
                "ci_high": None}
    d = a - b
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, d.size, size=(int(n_boot), d.size))
    boots = d[idx].mean(axis=1)
    return {
        "n": int(d.size),
        "mean": float(d.mean()),
        "ci_low": float(np.percentile(boots, 2.5)),
        "ci_high": float(np.percentile(boots, 97.5)),
        "se": float(d.std(ddof=1) / np.sqrt(d.size)) if d.size > 1 else None,
        "frac_improved": float((d < 0).mean()),
        "frac_worse": float((d > 0).mean()),
        "after_mean": float(a.mean()), "before_mean": float(b.mean()),
    }


def _mean_or_none(v: Sequence[float]) -> Optional[float]:
    return float(np.mean(v)) if len(v) else None


def run_panel(*, checkpoint: str, games: int, seats: int, seed_base: int,
              device: str, out: str, infer_search: int = 0,
              turns: int = 1, topk: int = 8, max_per_turn: int = 3,
              when: str = "carrier_or_spell", action: str = "pi_argmax",
              bootstrap: int = 1000, log: str = "") -> Dict[str, Any]:
    """调用 ``scripts/human_panel_eval.py``（子进程；与 AB 面板同一脚本/口径）。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(ROOT, "rust", "python"), ROOT] +
        ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env.setdefault("OMP_NUM_THREADS", "8")
    env.setdefault("MKL_NUM_THREADS", "8")
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "human_panel_eval.py"),
           "--checkpoint", checkpoint, "--games", str(int(games)),
           "--seats", str(int(seats)), "--seed-base", str(int(seed_base)),
           "--device", device, "--smoke", "--bootstrap", str(int(bootstrap)),
           "--baseline-bot", "0",
           "--infer-search", str(int(infer_search)),
           "--infer-search-turns", str(int(turns)),
           "--infer-search-topk", str(int(topk)),
           "--infer-search-max-per-turn", str(int(max_per_turn)),
           "--infer-search-when", when,
           "--infer-search-action", action,
           "--out", out]
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if log:
        with open(log, "w", encoding="utf-8") as f:
            f.write(f"$ {' '.join(cmd)}\n[exit {proc.returncode}]\n")
            f.write(proc.stdout + "\n" + proc.stderr)
    if proc.returncode not in (0, 1) or not os.path.isfile(out):
        raise RuntimeError(f"panel 失败 exit={proc.returncode}: "
                           f"{(proc.stderr or proc.stdout)[-2000:]}")
    with open(out, encoding="utf-8") as f:
        payload = json.load(f)
    panel = (payload.get("panels") or [{}])[0]
    ranks = _ranks_from_panel(panel)
    return {"panel": panel, "ranks": ranks, "seconds": round(time.time() - t0, 1),
            "payload": payload, "cmd": cmd}


def run_quality(*, checkpoint: str, device: str, out: str, games: int = 256,
                seed_base: int = 520000, log: str = "") -> Dict[str, Any]:
    """``quality_monitor``：t12/t15 Σ、载体率（``--carrier-audit 1``）。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(ROOT, "rust", "python"), ROOT] +
        ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "quality_monitor.py"),
           "--checkpoint", checkpoint, "--device", device,
           "--games", str(int(games)), "--seed-base", str(int(seed_base)),
           "--carrier-audit", "1", "--out", out]
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if log:
        with open(log, "w", encoding="utf-8") as f:
            f.write(f"$ {' '.join(cmd)}\n[exit {proc.returncode}]\n")
            f.write(proc.stdout + "\n" + proc.stderr)
    if not os.path.isfile(out):
        raise RuntimeError(f"quality_monitor 失败: {(proc.stderr or '')[-2000:]}")
    with open(out, encoding="utf-8") as f:
        q = json.load(f)
    by = {int(r["turn"]): r for r in (q.get("by_turn") or [])}
    return {
        "seconds": round(time.time() - t0, 1),
        "mean_rank": q.get("mean_rank"), "top4": q.get("top4"),
        "t12_sigma_p50": (by.get(12) or {}).get("ours_p50"),
        "t12_sigma_mean": (by.get(12) or {}).get("ours_p50"),
        "t15_sigma_p50": (by.get(15) or {}).get("ours_p50"),
        "t12_n": (by.get(12) or {}).get("n"), "t15_n": (by.get(15) or {}).get("n"),
        "survive_t12_ratio": q.get("survive_t12_ratio"),
        "learner_turn_p50": q.get("learner_turn_p50"),
        "carrier_encounter_rate": q.get("carrier_encounter_rate"),
        "carrier_t9_rate": q.get("carrier_t9_rate"),
        "carrier_t12_rate": q.get("carrier_t12_rate"),
        "carrier_turns_mean": q.get("carrier_turns_mean"),
        "casts_on_carrier_mean": q.get("casts_on_carrier_mean"),
        "r_carrier_turns_str12": q.get("r_carrier_turns_str12"),
        "move_accept_ratio": q.get("move_accept_ratio"),
        "moves_per_turn_mean": q.get("moves_per_turn_mean"),
    }


# ══════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="最小 ExIt 蒸馏（DAgger + 优势加权软标签）")
    ap.add_argument("--checkpoint", default=DEFAULT_CKPT)
    ap.add_argument("--out", default="runs/search_exit")
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--rounds-done", type=int, default=0,
                    help=">0 时从第 N 轮继续（已存在的 samples/ckpt 会被复用）")
    # 采集
    ap.add_argument("--games", type=int, default=128)
    ap.add_argument("--seed-base", type=int, default=600000)
    ap.add_argument("--behavior", default="greedy", choices=["greedy", "sample"])
    ap.add_argument("--human-boards", default=HUMAN_BOARDS)
    ap.add_argument("--max-actions-per-turn", type=int, default=40)
    ap.add_argument("--max-steps", type=int, default=50000)
    # 搜索口径
    ap.add_argument("--turns", type=int, default=1)
    ap.add_argument("--topk", type=int, default=8)
    ap.add_argument("--max-per-turn", type=int, default=3)
    ap.add_argument("--search-when", default="carrier_or_spell")
    ap.add_argument("--adv-clip", type=float, default=30.0)
    # 蒸馏
    ap.add_argument("--weight-mode", default="adv", choices=["adv", "awr", "none"])
    ap.add_argument("--weight-stat", default="max", choices=["max", "expected"])
    ap.add_argument("--tau", type=float, default=0.0)
    ap.add_argument("--tau-scale", type=float, default=1.0)
    ap.add_argument("--min-weight", type=float, default=1e-3)
    ap.add_argument("--distill-temp", type=float, default=2.0)
    ap.add_argument("--awr-clip", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--epochs", type=int, default=60,
                    help="最多蒸馏 epoch 数（KL 预算/收敛会提前停）")
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--train-scope", default="policy", choices=["policy", "all"])
    ap.add_argument("--agg-rounds", type=int, default=0,
                    help="0 = 只用本轮标签；k>0 = 最近 k 轮聚合（DAgger 历史）")
    ap.add_argument("--kl-anchor", type=float, default=0.05)
    ap.add_argument("--kl-target", type=float, default=0.02,
                    help="每轮 KL(π_old‖π_θ) 预算（达到即停 epoch）")
    ap.add_argument("--stall-epochs", type=int, default=4)
    ap.add_argument("--entropy-floor", type=float, default=0.90)
    ap.add_argument("--freq-limit", type=float, default=1.5)
    ap.add_argument("--halt-on-gate", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    # 评测
    ap.add_argument("--eval-games", type=int, default=128)
    ap.add_argument("--eval-seats", type=int, default=4)
    ap.add_argument("--eval-seed-base", type=int, default=420000)
    ap.add_argument("--eval-every", type=int, default=1)
    ap.add_argument("--final-games", type=int, default=256)
    ap.add_argument("--final-seats", type=int, default=8)
    ap.add_argument("--bootstrap", type=int, default=20000)
    ap.add_argument("--before-json", default=DEFAULT_BEFORE_JSON,
                    help="起点 checkpoint 的 256 局 no-search 面板（复用 = 同一 sha256）")
    ap.add_argument("--before-search-json", default=DEFAULT_BEFORE_SEARCH_JSON,
                    help="起点 checkpoint 的 256 局 search 面板（capture 分母）")
    ap.add_argument("--skip-final", type=int, default=0)
    ap.add_argument("--skip-quality", type=int, default=0)
    ap.add_argument("--quality-games", type=int, default=256)
    ap.add_argument("--skip-before-eval", type=int, default=0)
    args = ap.parse_args(argv)

    from hsbg.az.train.model import load_checkpoint, save_checkpoint
    from hsbg.az.train.ppo import PPOEvaluator
    from hsbg.az.train.search_exit import (ExitConfig, ExitTrainer, collect_round,
                                          load_samples)

    cfg = ExitConfig(
        games=int(args.games), seed_base=int(args.seed_base), seats=8,
        max_steps=int(args.max_steps), max_actions_per_turn=int(args.max_actions_per_turn),
        behavior=str(args.behavior), human_boards=str(args.human_boards),
        turns=int(args.turns), topk=int(args.topk),
        max_searches_per_turn=int(args.max_per_turn),
        search_when=str(args.search_when), adv_clip=float(args.adv_clip),
        weight_mode=str(args.weight_mode), weight_stat=str(args.weight_stat),
        tau=float(args.tau), tau_scale=float(args.tau_scale),
        min_weight=float(args.min_weight), distill_temp=float(args.distill_temp),
        awr_clip=float(args.awr_clip), lr=float(args.lr), epochs=int(args.epochs),
        batch=int(args.batch), train_scope=str(args.train_scope),
        agg_rounds=int(args.agg_rounds), kl_anchor=float(args.kl_anchor),
        kl_target=float(args.kl_target), stall_epochs=int(args.stall_epochs),
        entropy_floor=float(args.entropy_floor), freq_limit=float(args.freq_limit),
        halt_on_gate=int(args.halt_on_gate), seed=int(args.seed),
        device=str(args.device)).validate()

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    ckpt_before = os.path.join(out, "ckpt_before.pt")
    if not os.path.isfile(ckpt_before):
        shutil.copy2(args.checkpoint, ckpt_before)
    sha_before = _sha256(ckpt_before)
    t_start = time.time()
    print(f"[exit] start ckpt={ckpt_before} sha256={sha_before[:16]}… "
          f"out={out}", flush=True)

    # ── 起点 / 参考权重 ──────────────────────────────────────────────────
    model, meta = load_checkpoint(ckpt_before, device=str(args.device))
    meta_clean = {k: v for k, v in meta.items() if not isinstance(v, np.ndarray)}
    norm_kw: Dict[str, Any] = {}
    if isinstance(meta.get("norm_mean"), np.ndarray):
        norm_kw = {"norm_mean": meta["norm_mean"], "norm_std": meta.get("norm_std")}
    evaluator = PPOEvaluator(model, device=str(args.device),
                            norm_mean=meta.get("norm_mean"),
                            norm_std=meta.get("norm_std"))
    ref_model, _ = load_checkpoint(ckpt_before, device=str(args.device))
    for p in ref_model.parameters():
        p.requires_grad_(False)

    # ── 复用 256 局 before/search 面板（sha256 必须一致）───────────────────
    before_ref = before_search_ref = None
    before_ranks_256: List[int] = []
    search_ranks_256: List[int] = []
    if str(args.before_json) and os.path.isfile(args.before_json):
        with open(args.before_json, encoding="utf-8") as f:
            before_ref = json.load(f)
        if str(before_ref.get("checkpoint_sha256", "")) == sha_before:
            before_ranks_256 = _ranks_from_panel(
                (before_ref.get("panels") or [{}])[0])
        else:
            print("[exit][warn] before_json 的 checkpoint_sha256 与起点不一致 ⇒ 不复用",
                  flush=True)
            before_ref = None
    if str(args.before_search_json) and os.path.isfile(args.before_search_json):
        with open(args.before_search_json, encoding="utf-8") as f:
            before_search_ref = json.load(f)
        if str(before_search_ref.get("checkpoint_sha256", "")) == sha_before:
            search_ranks_256 = _ranks_from_panel(
                (before_search_ref.get("panels") or [{}])[0])
        else:
            print("[exit][warn] before_search_json 的 sha256 与起点不一致 ⇒ 不复用",
                  flush=True)
            before_search_ref = None

    # ── 起点子面板（128 局，seats 0–3 × 32）──────────────────────────────
    eval_ckpt = os.path.join(out, "ckpt_r000.pt")
    if not os.path.isfile(eval_ckpt):
        save_checkpoint(model, eval_ckpt, meta=meta_clean, **norm_kw)
    before_sub_path = os.path.join(out, "eval_r000_nosearch.json")
    if int(args.skip_before_eval) and os.path.isfile(before_sub_path):
        with open(before_sub_path, encoding="utf-8") as f:
            before_sub = _ranks_from_panel((json.load(f).get("panels") or [{}])[0])
        before_sub_info = {"reused": True}
    else:
        r = run_panel(checkpoint=eval_ckpt, games=int(args.eval_games),
                      seats=int(args.eval_seats), seed_base=int(args.eval_seed_base),
                      device=str(args.device), out=before_sub_path,
                      infer_search=0, log=os.path.join(out, "log_r000_eval.log"))
        before_sub = r["ranks"]
        before_sub_info = {"seconds": r["seconds"], "reused": False}
    before_sub_mean = _mean_or_none(before_sub)
    # 与复用 256 面板前 4 seat 逐局核对（确定性自检）
    det_ok = None
    if before_ranks_256:
        n = len(before_sub)
        det_ok = bool(list(before_ranks_256[:n]) == list(before_sub))
    search_sub_mean = None
    if search_ranks_256:
        search_sub_mean = _mean_or_none(search_ranks_256[:len(before_sub)])
    print(f"[exit] before sub-panel n={len(before_sub)} mean={before_sub_mean} "
          f"determinism_vs_AB={det_ok} search_sub_mean={search_sub_mean}", flush=True)

    summary: Dict[str, Any] = {
        "protocol": "search_exit_v1",
        "checkpoint_start": ckpt_before, "checkpoint_sha256": sha_before,
        "config": cfg.as_dict(), "before_sub_mean_rank": before_sub_mean,
        "before_sub_n": len(before_sub),
        "before_256_mean_rank": _mean_or_none(before_ranks_256) if before_ranks_256 else None,
        "search_256_mean_rank": _mean_or_none(search_ranks_256) if search_ranks_256 else None,
        "before_256_reused": bool(before_ranks_256),
        "search_256_reused": bool(search_ranks_256),
        "determinism_vs_AB": det_ok, "rounds": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    _dump(os.path.join(out, "summary.json"), summary)

    # ── 逐轮 ─────────────────────────────────────────────────────────────
    gate_hit = False
    for rnd in range(int(args.rounds_done) + 1, int(args.rounds) + 1):
        row: Dict[str, Any] = {"round": int(rnd),
                              "t0": time.strftime("%Y-%m-%dT%H:%M:%S")}
        npz = os.path.join(out, f"samples_r{rnd:03d}.npz")
        tb = time.time()
        if os.path.isfile(npz):
            samples = load_samples(npz)
            coll = {"reused": True, "n_states": len(samples)}
        else:
            samples, coll = collect_round(
                model, evaluator, cfg,
                seed_base=int(args.seed_base) + (int(rnd) - 1) * 1000, out_npz=npz)
        row["collect"] = coll
        row["collect_seconds"] = round(time.time() - tb, 1)
        print(f"[exit][round {rnd}] collect n_states={coll.get('n_states')} "
              f"ratio={coll.get('searched_ratio')} kept={coll.get('kept_ratio')} "
              f"w_mean={coll.get('mean_weight')} {row['collect_seconds']}s", flush=True)

        # 聚合历史标签（DAgger）
        train_samples = samples
        if int(args.agg_rounds) > 0:
            lo = max(1, int(rnd) - int(args.agg_rounds) + 1)
            train_samples = []
            for k in range(lo, int(rnd) + 1):
                p = os.path.join(out, f"samples_r{k:03d}.npz")
                if os.path.isfile(p):
                    train_samples.extend(load_samples(p))
        # probe 固定用**本轮新状态**（DAgger 本轮访问分布）；聚合历史只用于训练
        probe_set = list(samples)

        trainer = ExitTrainer(model, ref_model, cfg, device=str(args.device))
        tt = time.time()
        fit = trainer.fit(train_samples, round_id=int(rnd), probe_samples=probe_set)
        fit["seconds"] = round(time.time() - tt, 1)
        row["fit"] = fit
        print(f"[exit][round {rnd}] fit n_train={fit['n_train']} "
              f"held={fit['n_held']} kl_ref={fit['after'].get('kl_to_ref_mean')} "
              f"kl_max={fit['after'].get('kl_to_ref_max')} "
              f"ent_ratio={fit['after'].get('entropy_ratio')} "
              f"kl_teacher={fit['after'].get('kl_to_teacher_mean')} "
              f"gate={bool(fit.get('gate'))} {fit['seconds']}s", flush=True)

        ck = os.path.join(out, f"ckpt_r{rnd:03d}.pt")
        save_checkpoint(model, ck, meta=meta_clean, **norm_kw)
        row["checkpoint"] = ck

        # ── 每轮：关闭搜索的 128 局配对 Δ + 该轮 capture ──────────────────
        if int(args.eval_every) > 0 and rnd % int(args.eval_every) == 0:
            p = os.path.join(out, f"eval_r{rnd:03d}_nosearch.json")
            r = run_panel(checkpoint=ck, games=int(args.eval_games),
                          seats=int(args.eval_seats),
                          seed_base=int(args.eval_seed_base),
                          device=str(args.device), out=p, infer_search=0,
                          log=os.path.join(out, f"log_r{rnd:03d}_eval.log"))
            ranks = r["ranks"]
            st = paired_stats(ranks, before_sub, n_boot=int(args.bootstrap),
                              seed=int(rnd))
            cap = None
            if search_sub_mean is not None and (search_sub_mean - before_sub_mean) != 0:
                cap = ((st["after_mean"] - before_sub_mean)
                       / (search_sub_mean - before_sub_mean))
            row["eval_nosearch"] = {**st, "seconds": r["seconds"],
                                    "capture": cap, "panel": p}
            print(f"[exit][round {rnd}] nosearch n={st['n']} "
                  f"mean={st['after_mean']:.3f} Δ={st['mean']:+.3f} "
                  f"CI=[{st['ci_low']:+.3f},{st['ci_high']:+.3f}] "
                  f"capture={cap if cap is None else round(cap, 3)}", flush=True)
        summary["rounds"].append(row)
        _dump(os.path.join(out, "summary.json"), summary)
        _append_jsonl(os.path.join(out, "curves.jsonl"), row)
        if fit.get("gate") and int(args.halt_on_gate):
            print(f"[exit] 门禁触发 ⇒ 停止后续轮：{fit['gate'].get('reasons')}",
                  flush=True)
            gate_hit = True
            break

    # ── 收尾评测 ─────────────────────────────────────────────────────────
    final_ckpt = os.path.join(out, f"ckpt_r{int(summary['rounds'][-1]['round']):03d}.pt")
    final: Dict[str, Any] = {"checkpoint": final_ckpt, "gate_hit": bool(gate_hit)}
    if not int(args.skip_final):
        p0 = os.path.join(out, "final_nosearch.json")
        r0 = run_panel(checkpoint=final_ckpt, games=int(args.final_games),
                       seats=int(args.final_seats),
                       seed_base=int(args.eval_seed_base),
                       device=str(args.device), out=p0, infer_search=0,
                       log=os.path.join(out, "log_final_nosearch.log"))
        after_ranks = r0["ranks"]
        st = paired_stats(after_ranks, before_ranks_256 or after_ranks,
                          n_boot=int(args.bootstrap), seed=999)
        p1 = os.path.join(out, "final_search.json")
        r1 = run_panel(checkpoint=final_ckpt, games=int(args.final_games),
                       seats=int(args.final_seats),
                       seed_base=int(args.eval_seed_base),
                       device=str(args.device), out=p1, infer_search=1,
                       turns=int(args.turns), topk=int(args.topk),
                       max_per_turn=int(args.max_per_turn),
                       when=str(args.search_when), action="pi_argmax",
                       log=os.path.join(out, "log_final_search.log"))
        after_search_ranks = r1["ranks"]
        st_s = paired_stats(after_ranks, after_search_ranks,
                            n_boot=int(args.bootstrap), seed=998)
        # capture ratio（配对 bootstrap）
        cap = None
        cap_ci = None
        if before_ranks_256 and search_ranks_256 and len(after_ranks) == len(before_ranks_256):
            num = np.asarray(after_ranks, float) - np.asarray(before_ranks_256, float)
            den = (np.asarray(search_ranks_256, float)
                   - np.asarray(before_ranks_256, float))
            if abs(float(den.mean())) > 1e-9:
                cap = float(num.mean() / den.mean())
                rng = np.random.default_rng(4242)
                idx = rng.integers(0, num.size, size=(int(args.bootstrap), num.size))
                boots = num[idx].mean(axis=1) / max(
                    float(den.mean()), 1e-9) if float(den.mean()) != 0 else None
                if boots is not None:
                    cap_ci = [float(np.percentile(boots, 2.5)),
                              float(np.percentile(boots, 97.5))]
        final.update({
            "nosearch": {**st, "seconds": r0["seconds"], "panel": p0},
            "search": {"mean_rank": _mean_or_none(after_search_ranks),
                       "seconds": r1["seconds"], "panel": p1,
                       "delta_vs_nosearch": st_s},
            "capture_ratio": cap, "capture_ci": cap_ci,
            "search_before_mean": _mean_or_none(search_ranks_256),
            "before_mean": _mean_or_none(before_ranks_256),
            "gate_pass": bool(st.get("mean") is not None and st["mean"] <= -0.10
                              and st.get("ci_high") is not None and st["ci_high"] < 0),
        })
        print(f"[exit][final] nosearch Δ={st.get('mean')} "
              f"CI=[{st.get('ci_low')},{st.get('ci_high')}] "
              f"search_mean={final['search']['mean_rank']} "
              f"capture={cap}", flush=True)
        if not int(args.skip_quality):
            try:
                qb = run_quality(checkpoint=ckpt_before, device=str(args.device),
                                 out=os.path.join(out, "quality_before.json"),
                                 games=int(args.quality_games),
                                 log=os.path.join(out, "log_quality_before.log"))
                qa = run_quality(checkpoint=final_ckpt, device=str(args.device),
                                 out=os.path.join(out, "quality_after.json"),
                                 games=int(args.quality_games),
                                 log=os.path.join(out, "log_quality_after.log"))
                final["quality"] = {"before": qb, "after": qa}
            except Exception as exc:      # noqa: BLE001 - 质量面板失败不阻断结论
                final["quality"] = {"error": repr(exc)}
    summary["final"] = final
    summary["elapsed_s"] = round(time.time() - t_start, 1)
    summary["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _dump(os.path.join(out, "summary.json"), summary)
    print(json.dumps({k: summary[k] for k in
                      ("before_256_mean_rank", "search_256_mean_rank",
                       "determinism_vs_AB", "elapsed_s")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
