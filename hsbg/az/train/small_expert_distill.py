"""小模型专家 → 大模型蒸馏（DAgger 标签，复用 ``search_exit`` 的损失/信赖域）。

路线的动机（见 ``docs/SMALL_EXPERT_CURRICULUM.md``）：搜索/专家蒸馏的**瓶颈是标签
与状态覆盖**，不是损失函数。这里用三阶段课程训出的 ≤5M 小专家当教师：

1. **行为 = 大模型 π_base（部署分布）**：在完整游戏里跑 200 局，对手档为
   ``1 席人类战团 p=0.3`` 与 ``3 席 p=0.7`` 各 100 局（与 s17 训练的 band 同口径）。
   DAgger 的关键是状态来自**要部署的大模型**，而不是小专家自己的轨迹；
2. **标签 = 小专家的策略**：在每个 learner 决策点把 ``(features, cards, legal_mask)``
   同时喂给大小两个网络；候选 = 两者 top-k 的并集（非 Move），教师分布 = 小专家在
   候选上的 masked softmax（温度可调），先验 = 大模型在同一候选上的分布；
3. **损失 = ``search_exit.ExitTrainer``**：优势加权软标签（本路线 ``weight_mode=none``，
   纯 KD） + ``KL(π_ref‖π_θ)`` 信赖域 + 熵地板/频率门禁；``train_scope=policy`` 只训
   策略头，trunk/value 冻结（与 ``runs/search_exit`` 同一安全口径）；
4. **验收**：大模型**关闭搜索**的 human 面板 256 局（seed 420000，8 seat × 32）配对
   ``Δ`` 与 20000 次 bootstrap CI；判据 ``Δ ≤ −0.10 且 CI 上界 < 0``。

边界：只读大/小 checkpoint 与人类战团库；所有产物写 ``--out``；设备默认 ``cuda:7``。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

HUMAN_BOARDS = "data/real_library/library_real_quasi_full.jsonl"
DEFAULT_BIG = "runs/stoch_search/ckpt_s17_step1001.pt"
DEFAULT_SMALL = "runs/small_expert/main/model.pt"


# ══════════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class DistillConfig:
    """采集 + 蒸馏 + 验收的旋钮。"""

    big_checkpoint: str = DEFAULT_BIG
    small_checkpoint: str = DEFAULT_SMALL
    out: str = "runs/small_expert_distill"
    device: str = "cuda:7"
    seed: int = 0
    #: 人类战团对手档：``(human_board_seats, human_board_p, games)``
    bands: Tuple[Tuple[int, float, int], ...] = ((1, 0.30, 100), (3, 0.70, 100))
    seed_base: int = 700000
    lockstep_games: int = 16
    max_steps: int = 30000
    max_actions_per_turn: int = 40
    human_board_sample: str = "p75"
    #: 候选集 = 大模型 top-k ∪ 小专家 top-k（非 Move）
    topk: int = 8
    #: 只保留关键决策（carrier_or_spell）；空 = 所有决策
    only_when: str = ""
    #: 教师软标签温度（1.0 = 原分布）
    distill_temp: float = 1.0
    #: 蒸馏（与 search_exit.ExitConfig 同语义）
    lr: float = 1e-5
    epochs: int = 60
    batch: int = 256
    train_scope: str = "policy"
    kl_anchor: float = 0.10
    kl_target: float = 0.05
    entropy_floor: float = 0.85
    freq_limit: float = 2.0
    min_weight: float = 0.0
    probe_n: int = 1024
    #: 验收面板
    eval_games: int = 256
    eval_seats: int = 8
    eval_seed_base: int = 420000
    bootstrap: int = 20000
    skip_panels: int = 0
    quality_games: int = 48

    def as_dict(self) -> Dict[str, Any]:
        return {k: (list(v) if isinstance(v, tuple) else v)
                for k, v in self.__dict__.items()}


# ══════════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════════
def _dump(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _sha256(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _script(name: str) -> Any:
    key = f"_hsbg_script_{name}"
    if key in sys.modules:
        return sys.modules[key]
    path = os.path.join(ROOT, "scripts", f"{name}.py")
    spec = importlib.util.spec_from_file_location(key, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _masked_softmax_rows(logits: Any, mask: Any) -> np.ndarray:
    lg = np.where(np.asarray(mask, dtype=bool),
                  np.asarray(logits, dtype=np.float64), -np.inf)
    mx = np.max(lg, axis=1, keepdims=True)
    e = np.exp(lg - mx)
    e = np.where(np.isfinite(e), e, 0.0)
    s = e.sum(axis=1, keepdims=True)
    return np.where(s > 0.0, e / np.maximum(s, 1e-12), 0.0)


def _topk_union(pi_big: np.ndarray, pi_small: np.ndarray, mask: np.ndarray,
                k: int) -> np.ndarray:
    """大/小模型各自 top-k（合法、非 Move）的并集，按大模型先验降序。"""
    from hsbg.az.train.sandbox_rollout import MOVE_HI, MOVE_LO

    def _tk(pi: np.ndarray) -> List[int]:
        p = np.where(mask, pi, -1.0)
        idx = np.argsort(-p)[:int(k)]
        return [int(i) for i in idx if p[i] > 0.0]

    cand = set(_tk(pi_big)) | set(_tk(pi_small))
    cand = [a for a in cand if not (MOVE_LO <= a < MOVE_HI)]
    if not cand:
        cand = [int(np.flatnonzero(mask)[0])] if mask.any() else [0]
    cand = np.asarray(cand, dtype=np.int64)
    order = np.argsort(-pi_big[cand], kind="stable")
    return cand[order]


# ══════════════════════════════════════════════════════════════════════════
# 1. 采集：大模型行为 + 人类战团对手
# ══════════════════════════════════════════════════════════════════════════
def collect_trajectories(big_model: Any, evaluator: Any, cfg: DistillConfig
                         ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from hsbg.az.train.human_board_pool import load_pool
    from hsbg.az.train.parallel_collect import collect_ppo_lockstep
    from hsbg.az.train.ppo import CollectConfig

    records: List[Dict[str, Any]] = []
    metas: List[Dict[str, Any]] = []
    t0 = time.time()
    gi = 0
    for bi, (seats, p, games) in enumerate(cfg.bands):
        pool = load_pool(HUMAN_BOARDS, sample=str(cfg.human_board_sample))
        if pool is None:
            raise RuntimeError(f"人类战团库为空: {HUMAN_BOARDS}")
        ccfg = CollectConfig(
            games=int(min(cfg.lockstep_games, games)), seed=int(cfg.seed_base) + gi,
            opponent="bot", behavior="net", lockstep=True, fast_act=True,
            max_actions_per_turn=int(cfg.max_actions_per_turn),
            max_steps=int(cfg.max_steps),
            human_boards=HUMAN_BOARDS, human_board_p=float(p),
            human_board_seats=int(seats), human_board_sample=str(cfg.human_board_sample),
            human_board_set_tier=True, human_board_fidelity="full",
            human_board_fast_inject=True)
        done = 0
        while done < int(games):
            n = int(min(cfg.lockstep_games, games - done))
            seed = int(cfg.seed_base) + gi + done
            recs, meta = collect_ppo_lockstep(
                big_model, ccfg, eval_fn=evaluator, device=cfg.device,
                seed=seed, games=n, gamemode="bot",
                human_board_pool=pool, human_board_p=float(p),
                human_board_seats=int(seats),
                human_board_sample=str(cfg.human_board_sample),
                human_board_set_tier=True,
                human_board_fidelity="full", human_board_fast_inject=True)
            records.extend(recs)
            metas.append({"band": bi, "seats": int(seats), "p": float(p),
                          "games": n, "seed": seed,
                          "records": len(recs),
                          "human_board_on": meta.get("human_board_on"),
                          "human_board_applied": meta.get("human_board_applied"),
                          "truncated_games": meta.get("truncated_games")})
            done += n
        gi += int(games)
    stats = {"records": len(records), "bands": metas,
             "seconds": round(time.time() - t0, 1),
             "games": int(sum(g for _s, _p, g in cfg.bands))}
    return records, stats


# ══════════════════════════════════════════════════════════════════════════
# 2. 打标签：小专家分布 → SearchSample（供 ExitTrainer 使用）
# ══════════════════════════════════════════════════════════════════════════
def make_samples(records: Sequence[Dict[str, Any]], big_eval: Any, small_eval: Any,
                 cfg: DistillConfig) -> Tuple[List[Any], Dict[str, Any]]:
    from hsbg.az.train.search_exit import SearchSample
    from hsbg.az.train.sandbox_rollout import search_when_names, tag_matches
    from hsbg.az.train.infer_search import InferSearcher

    when = (search_when_names(str(cfg.only_when)) if str(cfg.only_when) else None)
    # 关键决策过滤需要 tags；用一个不依赖 GPU 的 searcher 仅解码观测
    tagger = InferSearcher.__new__(InferSearcher)
    from hsbg.az.train.sandbox_rollout import card_tables
    tab = card_tables()
    tagger._cid2id = tab["cid2id"]
    tagger._id2kind = tab["id2kind"]
    from hsbg.az.train.economy_sandbox import carrier_ids
    tagger._carriers = set(carrier_ids())

    out: List[Any] = []
    n_filtered = 0
    n_bad = 0
    feats = np.stack([np.asarray(r["features"], dtype=np.float32) for r in records])
    cards = np.stack([np.asarray(r["cards"], dtype=np.int16) for r in records])
    masks = np.stack([np.asarray(r["mask"], dtype=bool) for r in records])
    n = len(records)
    chunk = 4096
    pi_big = np.zeros((n, 245), dtype=np.float32)
    pi_small = np.zeros((n, 245), dtype=np.float32)
    for s in range(0, n, chunk):
        e = min(n, s + chunk)
        pb, _ = big_eval.logits(feats[s:e], cards[s:e].astype(np.int64), masks[s:e])
        ps, _ = small_eval.logits(feats[s:e], cards[s:e].astype(np.int64), masks[s:e])
        pi_big[s:e] = _masked_softmax_rows(pb, masks[s:e]).astype(np.float32)
        pi_small[s:e] = _masked_softmax_rows(ps, masks[s:e]).astype(np.float32)
    for i, r in enumerate(records):
        mask = masks[i]
        if int(mask.sum()) < 2:
            n_bad += 1
            continue
        if when is not None:
            try:
                tags = tagger.tags(feats[i], cards[i])
                if not tag_matches(tags, when):
                    n_filtered += 1
                    continue
            except Exception:  # noqa: BLE001 - 过滤失败时保留样本
                pass
        cands = _topk_union(pi_big[i], pi_small[i], mask, int(cfg.topk))
        ps = np.asarray(pi_small[i][cands], dtype=np.float64)
        if float(ps.sum()) <= 0.0:
            n_bad += 1
            continue
        ps = ps / float(ps.sum())
        pb = np.asarray(pi_big[i][cands], dtype=np.float64)
        pb = pb / float(pb.sum()) if float(pb.sum()) > 0 else np.ones_like(pb) / len(pb)
        teacher = int(cands[int(np.argmax(ps))])
        base = int(cands[int(np.argmax(pb))])
        out.append(SearchSample(
            f=feats[i].astype(np.float16), c=cards[i].astype(np.int16),
            mask=mask.astype(bool), cands=cands.astype(np.int16),
            p_base=pb.astype(np.float32), p_s=ps.astype(np.float32),
            q=np.zeros(len(cands), dtype=np.float32),
            adv=np.zeros(len(cands), dtype=np.float32),
            q_std=1.0, tau=1.0, base=base, teacher=teacher,
            turn=int(r.get("turn", -1)), seat=int(r.get("seat", -1)),
            seed=int(r.get("seed", -1)) if "seed" in r else -1,
            game=int(r.get("game_id", -1)), sigma_root=0,
            switch=bool(base != teacher)))
    stats = {"n_states": len(out), "n_records": n,
             "filtered_non_key": int(n_filtered), "n_bad": int(n_bad),
             "teacher_base_agree": (float(np.mean([s.base == s.teacher for s in out]))
                                    if out else None),
             "mean_top1_mass": (float(np.mean([float(np.max(s.p_s)) for s in out]))
                                if out else None)}
    return out, stats


# ══════════════════════════════════════════════════════════════════════════
# 3. 蒸馏（复用 search_exit.ExitTrainer）
# ══════════════════════════════════════════════════════════════════════════
def train_distill(model: Any, ref_model: Any, samples: Sequence[Any],
                  cfg: DistillConfig) -> Dict[str, Any]:
    from hsbg.az.train.search_exit import ExitConfig, ExitTrainer

    ecfg = ExitConfig(
        lr=float(cfg.lr), epochs=int(cfg.epochs), batch=int(cfg.batch),
        train_scope=str(cfg.train_scope), weight_mode="none",
        min_weight=0.0, distill_temp=float(cfg.distill_temp),
        kl_anchor=float(cfg.kl_anchor), kl_target=float(cfg.kl_target),
        entropy_floor=float(cfg.entropy_floor), freq_limit=float(cfg.freq_limit),
        halt_on_gate=1, probe_n=int(cfg.probe_n), stall_epochs=4,
        seed=int(cfg.seed), device=str(cfg.device),
        games=((max(1, len(samples)) + 7) // 8) * 8).validate()
    trainer = ExitTrainer(model, ref_model, ecfg, device=str(cfg.device))
    fit = trainer.fit(samples, round_id=0, probe_samples=list(samples))
    fit["scope"] = str(cfg.train_scope)
    return fit


# ══════════════════════════════════════════════════════════════════════════
# 4. 验收面板
# ══════════════════════════════════════════════════════════════════════════
def run_panel(*, checkpoint: str, games: int, seats: int, seed_base: int,
              device: str, out: str, log: str = "") -> Dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(ROOT, "rust", "python"), ROOT] +
        ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env.setdefault("OMP_NUM_THREADS", "4")
    env.setdefault("MKL_NUM_THREADS", "4")
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "human_panel_eval.py"),
           "--checkpoint", checkpoint, "--games", str(int(games)),
           "--seats", str(int(seats)), "--seed-base", str(int(seed_base)),
           "--device", device, "--smoke", "--bootstrap", "1000",
           "--baseline-bot", "0", "--infer-search", "0",
           "--out", out]
    t0 = time.time()
    from hsbg.az.train.search_exit import _ranks_from_panel  # 同一解析口径
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if log:
        os.makedirs(os.path.dirname(os.path.abspath(log)) or ".", exist_ok=True)
        with open(log, "w", encoding="utf-8") as f:
            f.write(f"$ {' '.join(cmd)}\n[exit {proc.returncode}]\n")
            f.write(proc.stdout + "\n" + proc.stderr)
    if not os.path.isfile(out):
        raise RuntimeError(f"panel 失败 exit={proc.returncode}: "
                           f"{(proc.stderr or proc.stdout)[-2000:]}")
    with open(out, encoding="utf-8") as f:
        payload = json.load(f)
    panel = (payload.get("panels") or [{}])[0]
    ranks = _ranks_from_panel(panel)
    return {"panel": panel, "ranks": ranks,
            "seconds": round(time.time() - t0, 1), "path": out}


def paired_stats(after: Sequence[int], before: Sequence[int], *,
                 n_boot: int = 20000, seed: int = 0) -> Dict[str, Any]:
    """配对 Δ = mean(after − before) 的 bootstrap 95% CI。"""
    a = np.asarray(after, dtype=np.float64)
    b = np.asarray(before, dtype=np.float64)
    if a.size != b.size or a.size == 0:
        return {"n": int(min(a.size, b.size)), "mean": None}
    d = a - b
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, d.size, size=(int(n_boot), d.size))
    boots = d[idx].mean(axis=1)
    return {"n": int(d.size), "mean": float(d.mean()),
            "ci_low": float(np.percentile(boots, 2.5)),
            "ci_high": float(np.percentile(boots, 97.5)),
            "se": float(d.std(ddof=1) / np.sqrt(d.size)) if d.size > 1 else None,
            "frac_improved": float((d < 0).mean()),
            "after_mean": float(a.mean()), "before_mean": float(b.mean())}


def quality(checkpoint: str, cfg: DistillConfig, out: str) -> Dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(ROOT, "rust", "python"), ROOT] +
        ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "quality_monitor.py"),
           "--checkpoint", checkpoint, "--device", cfg.device,
           "--games", str(int(cfg.quality_games)),
           "--seed-base", "520000", "--carrier-audit", "1", "--out", out]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if not os.path.isfile(out):
        return {"error": (proc.stderr or "")[-1000:]}
    with open(out, encoding="utf-8") as f:
        q = json.load(f)
    by = {int(r["turn"]): r for r in (q.get("by_turn") or [])}
    return {"mean_rank": q.get("mean_rank"), "top4": q.get("top4"),
            "t12_sigma_p50": (by.get(12) or {}).get("ours_p50"),
            "t15_sigma_p50": (by.get(15) or {}).get("ours_p50"),
            "carrier_turns_mean": q.get("carrier_turns_mean"),
            "casts_on_carrier_mean": q.get("casts_on_carrier_mean")}


# ══════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════
def run(cfg: DistillConfig) -> Dict[str, Any]:
    from hsbg.az.train.model import load_checkpoint, save_checkpoint
    from hsbg.az.train.ppo import PPOEvaluator

    os.makedirs(cfg.out, exist_ok=True)
    t_start = time.time()
    report: Dict[str, Any] = {"config": cfg.as_dict(),
                              "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    print(f"[distill] big={cfg.big_checkpoint} small={cfg.small_checkpoint}", flush=True)
    big_model, meta = load_checkpoint(cfg.big_checkpoint, device=cfg.device)
    big_eval = PPOEvaluator(big_model, device=cfg.device)
    # KL 信赖域的 π_ref：起点权重的**独立副本**（不能与 π_θ 同一对象，否则 KL≡0）
    ref_model, _rref = load_checkpoint(cfg.big_checkpoint, device=cfg.device)
    small_model, _smeta = load_checkpoint(cfg.small_checkpoint, device=cfg.device)
    small_eval = PPOEvaluator(small_model, device=cfg.device)

    # 1) 采集（大模型行为 = 部署分布）
    records, coll = collect_trajectories(big_model, big_eval, cfg)
    report["collect"] = coll
    print(f"[distill] collect records={coll['records']} games={coll['games']} "
          f"{coll['seconds']}s", flush=True)

    # 2) 标签（小专家）
    samples, sstats = make_samples(records, big_eval, small_eval, cfg)
    report["samples"] = sstats
    print(f"[distill] samples={sstats['n_states']} filtered={sstats['filtered_non_key']} "
          f"agree={sstats['teacher_base_agree']}", flush=True)
    if not samples:
        raise RuntimeError("没有可用蒸馏样本")

    # 3) 蒸馏
    t0 = time.time()
    fit = train_distill(big_model, ref_model, samples, cfg)
    report["fit"] = fit
    report["fit_seconds"] = round(time.time() - t0, 1)
    print(f"[distill] fit n={fit['n_train']} kl_ref={fit['after'].get('kl_to_ref_mean')} "
          f"kl_max={fit['after'].get('kl_to_ref_max')} "
          f"ent_ratio={fit['after'].get('entropy_ratio')} "
          f"teacher_ag={fit['after'].get('teacher_top1_agree')} "
          f"gate={bool(fit.get('gate'))} {report['fit_seconds']}s", flush=True)

    ckpt_after = os.path.join(cfg.out, "ckpt_distilled.pt")
    meta_clean = {k: v for k, v in meta.items() if not isinstance(v, np.ndarray)}
    save_checkpoint(big_model, ckpt_after, meta=meta_clean)
    # 起点副本（KL ref 与 before 面板都用它）
    ckpt_before = os.path.join(cfg.out, "ckpt_before.pt")
    import shutil
    if not os.path.isfile(ckpt_before):
        shutil.copy2(cfg.big_checkpoint, ckpt_before)
    report["checkpoints"] = {"before": ckpt_before, "after": ckpt_after}

    if int(cfg.skip_panels):
        report["elapsed_s"] = round(time.time() - t_start, 1)
        _dump(os.path.join(cfg.out, "summary.json"), report)
        return report

    # 4) 验收：大模型关搜索 human 256 局配对 Δ
    p_before = os.path.join(cfg.out, "panel_before.json")
    p_after = os.path.join(cfg.out, "panel_after.json")
    sha_before = _sha256(ckpt_before)
    r_before = None
    if os.path.isfile(p_before):
        try:
            with open(p_before, encoding="utf-8") as f:
                _pb = json.load(f)
            if str(_pb.get("checkpoint_sha256", "")) == sha_before:
                from hsbg.az.train.search_exit import _ranks_from_panel
                r_before = {"panel": (_pb.get("panels") or [{}])[0],
                            "ranks": _ranks_from_panel((_pb.get("panels") or [{}])[0]),
                            "seconds": 0.0, "path": p_before, "reused": True}
        except Exception:  # noqa: BLE001 - 坏面板文件就当不存在
            r_before = None
    if r_before is None:
        r_before = run_panel(checkpoint=ckpt_before, games=int(cfg.eval_games),
                             seats=int(cfg.eval_seats), seed_base=int(cfg.eval_seed_base),
                             device=cfg.device, out=p_before,
                             log=os.path.join(cfg.out, "log_panel_before.log"))
    r_after = run_panel(checkpoint=ckpt_after, games=int(cfg.eval_games),
                        seats=int(cfg.eval_seats), seed_base=int(cfg.eval_seed_base),
                        device=cfg.device, out=p_after,
                        log=os.path.join(cfg.out, "log_panel_after.log"))
    st = paired_stats(r_after["ranks"], r_before["ranks"],
                      n_boot=int(cfg.bootstrap), seed=999)
    crit = bool(st.get("mean") is not None and st["mean"] <= -0.10
                and st.get("ci_high") is not None and st["ci_high"] < 0)
    report["panel"] = {
        "before": {"mean_rank": r_before["panel"].get("model_mean_rank"),
                   "top4": r_before["panel"].get("model_top4"),
                   "seconds": r_before["seconds"], "path": p_before},
        "after": {"mean_rank": r_after["panel"].get("model_mean_rank"),
                  "top4": r_after["panel"].get("model_top4"),
                  "seconds": r_after["seconds"], "path": p_after},
        "paired": st, "criterion_pass": crit,
        "quality_before": quality(ckpt_before, cfg,
                                  os.path.join(cfg.out, "quality_before.json")),
        "quality_after": quality(ckpt_after, cfg,
                                 os.path.join(cfg.out, "quality_after.json")),
    }
    print(f"[distill] panel before={report['panel']['before']['mean_rank']} "
          f"after={report['panel']['after']['mean_rank']} "
          f"Δ={st.get('mean')} CI=[{st.get('ci_low')},{st.get('ci_high')}] "
          f"pass={crit}", flush=True)
    report["elapsed_s"] = round(time.time() - t_start, 1)
    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _dump(os.path.join(cfg.out, "summary.json"), report)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="小模型专家 → 大模型 DAgger 蒸馏 + 256 局面板")
    ap.add_argument("--big-checkpoint", default=DEFAULT_BIG)
    ap.add_argument("--small-checkpoint", default=DEFAULT_SMALL)
    ap.add_argument("--out", default="runs/small_expert_distill")
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--games-per-band", type=int, default=100)
    ap.add_argument("--lockstep-games", type=int, default=16)
    ap.add_argument("--topk", type=int, default=8)
    ap.add_argument("--only-when", default="")
    ap.add_argument("--distill-temp", type=float, default=1.0)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--train-scope", default="policy", choices=["policy", "all"])
    ap.add_argument("--kl-anchor", type=float, default=0.10)
    ap.add_argument("--kl-target", type=float, default=0.05)
    ap.add_argument("--eval-games", type=int, default=256)
    ap.add_argument("--eval-seats", type=int, default=8)
    ap.add_argument("--bootstrap", type=int, default=20000)
    ap.add_argument("--quality-games", type=int, default=48)
    ap.add_argument("--skip-panels", type=int, default=0)
    args = ap.parse_args(argv)
    cfg = DistillConfig(
        big_checkpoint=str(args.big_checkpoint),
        small_checkpoint=str(args.small_checkpoint), out=str(args.out),
        device=str(args.device), seed=int(args.seed),
        bands=((1, 0.30, int(args.games_per_band)),
               (3, 0.70, int(args.games_per_band))),
        lockstep_games=int(args.lockstep_games), topk=int(args.topk),
        only_when=str(args.only_when), distill_temp=float(args.distill_temp),
        lr=float(args.lr), epochs=int(args.epochs), batch=int(args.batch),
        train_scope=str(args.train_scope), kl_anchor=float(args.kl_anchor),
        kl_target=float(args.kl_target), eval_games=int(args.eval_games),
        eval_seats=int(args.eval_seats), bootstrap=int(args.bootstrap),
        quality_games=int(args.quality_games),
        skip_panels=int(args.skip_panels))
    rep = run(cfg)
    print(json.dumps({k: rep.get(k) for k in
                      ("samples", "panel", "elapsed_s")}, ensure_ascii=False)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
