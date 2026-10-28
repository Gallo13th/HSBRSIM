#!/usr/bin/env python3
"""Entity 同步 PPO 基线（单进程、持久 Adam/LR/RNG）。

与 `train_az_ppo.py` 的区别：
- 默认 `arch=entity`（14.8M）；
- 同一个进程跨 iteration 保留 model / Adam / LambdaLR / numpy RNG；
- 同时原子保存 `model.pt`（给评测）与 `trainer.pt`（优化器/调度器/RNG）；
- 支持 `--trainer-state` 精确续训；不再每轮重建 Adam。

仍使用当前串行采集（P0 第 2 轮）；批量叶/并发 actor 在 P0 第 3 轮。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import engine_available, engine_info, to_jsonable  # noqa: E402
from hsbg.az.train.model import build_net, load_checkpoint, save_checkpoint  # noqa: E402
from hsbg.az.train.ppo import (  # noqa: E402
    CollectConfig,
    PPOConfig,
    PPOEvaluator,
    collect_ppo_batch,
    torch_available,
)
from hsbg.az.train.ppo_trainer import PPOTrainer  # noqa: E402
from hsbg.az.train.batch_eval import BatchLeafServer, BatchPPOEvaluator  # noqa: E402
from hsbg.az.train.parallel_collect import collect_ppo_batch_parallel  # noqa: E402
from hsbg.az.train.process_pool import ProcessActorPool  # noqa: E402


def _atomic_torch_save(obj: Any, path: str) -> None:
    import torch
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    torch.save(obj, tmp)
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Entity 同步 PPO 基线（持久 trainer）")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--iterations", type=int, default=0)
    ap.add_argument("--games", type=int, default=4)
    ap.add_argument("--arch", default="entity", choices=["tiny", "entity", "entity18m"])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--sims", type=int, default=4)
    ap.add_argument("--determinizations", type=int, default=1)
    ap.add_argument("--opponent", default="bot", choices=["bot", "self", "weak"])
    ap.add_argument("--behavior", default="net", choices=["net", "mcts", "mixed"])
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--minibatch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--lr-min-ratio", type=float, default=0.1)
    ap.add_argument("--max-updates", type=int, default=100000)
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--target-kl", type=float, default=0.05)
    ap.add_argument("--lam", type=float, default=0.95, help="GAE λ（论文 0.995）")
    ap.add_argument("--max-grad-norm", type=float, default=0.5,
                    help="梯度裁剪范数（论文 1.0）")
    ap.add_argument("--grad-accum", type=int, default=1,
                    help="梯度累积步数：有效 minibatch = minibatch * grad_accum（论文 8192）")
    ap.add_argument("--pi-coef", type=float, default=0.1)
    ap.add_argument("--entropy-coef", type=float, default=0.005)
    ap.add_argument("--max-actions-per-turn", type=int, default=40)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--log-every", type=int, default=10)
    ap.add_argument("--workers", type=int, default=1,
                    help=">1 时使用并行采集 + 共享批量叶 server")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--processes", type=int, default=1,
                    help=">1 时用进程级 actor pool（每进程绑定一张 GPU，同步模式）")
    ap.add_argument("--gpus", default="",
                    help="actor pool 使用的物理 GPU 序号，如 0,5,6,7（不要设 CUDA_VISIBLE_DEVICES）")
    ap.add_argument("--threads", type=int, default=16,
                    help="每个 actor 进程内的采集线程数（每轮 games 应 >= processes*threads）")
    ap.add_argument("--snapshot-every", type=int, default=1,
                    help="每 N 个 iteration 落一次快照（进程 actor 下建议 5）")
    ap.add_argument("--keep-snapshots", type=int, default=3,
                    help="只保留最近 K 个 snapshot 目录（0=不清理）")
    ap.add_argument("--anchor-beta", type=float, default=0.0,
                    help="KL anchor 系数 β（论文 Table 7 = 0.1；0=关闭）")
    ap.add_argument("--anchor-iterations", type=int, default=100,
                    help="β 生效的前 N 个 iteration（论文 300 个中的前 100）")
    ap.add_argument("--eval-every-decisions", type=int, default=0,
                    help="每累计 N decisions 做一次 C0 评测（0=关闭）")
    ap.add_argument("--eval-games", type=int, default=512)
    ap.add_argument("--eval-seats", type=int, default=8)
    ap.add_argument("--eval-seed-base", type=int, default=420000)
    ap.add_argument("--eval-device", default="",
                    help="评测用的 GPU（默认跟随 --device；建议用没跑 actor 的卡）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--checkpoint", default="")
    ap.add_argument("--trainer-state", default="")
    ap.add_argument("--out", default="runs/az_entity_sync")
    args = ap.parse_args()
    args.out = os.path.abspath(args.out)

    if not engine_available():
        print("[error] hsbg_engine 不可用", file=sys.stderr)
        return 2
    if not torch_available():
        print("[error] torch 不可用", file=sys.stderr)
        return 2
    import torch
    if args.minutes <= 0 or args.games <= 0 or args.iterations < 0:
        print("[error] minutes/games 必须 >0，iterations 必须 >=0", file=sys.stderr)
        return 2
    if args.workers <= 0 or args.batch_size <= 0:
        print("[error] workers/batch-size 必须 >0", file=sys.stderr)
        return 2
    if args.trainer_state and not os.path.isfile(args.trainer_state):
        print(f"[error] trainer-state 不存在: {args.trainer_state}", file=sys.stderr)
        return 2
    torch.manual_seed(int(args.seed))
    np.random.seed(int(args.seed) % (2 ** 32))
    os.makedirs(args.out, exist_ok=True)
    eng = engine_info()
    print(f"[engine] {json.dumps(eng, ensure_ascii=False)}", flush=True)

    norm_mean = norm_std = None
    if args.checkpoint:
        model, meta = load_checkpoint(args.checkpoint, device=args.device)
        arch = str(meta.get("arch", args.arch))
        norm_mean, norm_std = meta.get("norm_mean"), meta.get("norm_std")
        print(f"[net] checkpoint={args.checkpoint} arch={arch}", flush=True)
    elif args.trainer_state and os.path.isfile(args.trainer_state):
        # 只能先有同结构模型再 load_state；trainer state 内含 model state
        model = build_net(arch=args.arch)
        meta = {"arch": args.arch}
        arch = args.arch
        print(f"[net] empty model for trainer-state={args.trainer_state}", flush=True)
    else:
        model = build_net(arch=args.arch)
        meta = {"arch": args.arch}
        arch = args.arch
    model.to(torch.device(args.device))
    print(f"[net] arch={arch} params={sum(p.numel() for p in model.parameters()):,}",
          flush=True)

    p_cfg = PPOConfig(
        epochs=int(args.epochs), minibatch=int(args.minibatch), lr=float(args.lr),
        clip=float(args.clip), target_kl=float(args.target_kl),
        entropy_coef=float(args.entropy_coef), pi_coef=float(args.pi_coef),
        max_grad_norm=float(args.max_grad_norm),
        grad_accum=int(args.grad_accum),
        device=str(args.device), seed=int(args.seed),
        log_every=int(args.log_every))
    trainer: Optional[PPOTrainer] = None
    if args.trainer_state and os.path.isfile(args.trainer_state):
        trainer = PPOTrainer.load(model, args.trainer_state, config=p_cfg,
                                  device=args.device)
        print(f"[trainer] loaded updates={trainer.updates} "
              f"lr={trainer.optimizer.param_groups[0]['lr']:.3g}", flush=True)
    else:
        trainer = PPOTrainer(model, p_cfg, lr_min_ratio=float(args.lr_min_ratio),
                             max_updates=int(args.max_updates))

    history = []
    history_path = os.path.join(args.out, "history.json")
    if args.trainer_state and os.path.isfile(history_path):
        try:
            history = json.load(open(history_path, encoding="utf-8")).get("history", [])
        except Exception:
            history = []
    if trainer.extra.get("norm_mean") is not None:
        norm_mean = np.asarray(trainer.extra["norm_mean"], dtype=np.float32)
    if trainer.extra.get("norm_std") is not None:
        norm_std = np.asarray(trainer.extra["norm_std"], dtype=np.float32)
    trainer.extra["norm_mean"] = (None if norm_mean is None else norm_mean.tolist())
    trainer.extra["norm_std"] = (None if norm_std is None else norm_std.tolist())
    start_i = int(trainer.updates)
    print(f"[resume] start_iter={start_i} updates={trainer.updates}", flush=True)

    # ---- KL anchor（AutoTavern Table 7：β=0.1，仅前 100 个 iteration）----
    if float(args.anchor_beta) > 0.0:
        trainer.set_anchor()
        print(f"[anchor] beta={args.anchor_beta} for first "
              f"{int(args.anchor_iterations)} iters (stage-start policy frozen)",
              flush=True)

    # ---- 周期 C0 评测（监控曲线；avg rank<=3.0 触发镜像库）----
    evals: list = []
    eval_dir = os.path.join(args.out, "eval")

    def _run_eval(decisions_done: int) -> None:
        os.makedirs(eval_dir, exist_ok=True)
        tag = f"{int(decisions_done):09d}"
        ckpt = os.path.join(eval_dir, f"ckpt_{tag}.pt")
        save_checkpoint(model, ckpt, meta={**meta, "arch": arch},
                        norm_mean=norm_mean, norm_std=norm_std)
        out_json = os.path.join(eval_dir, f"c0_{tag}.json")
        log_path = os.path.join(eval_dir, f"c0_{tag}.log")
        cmd = [sys.executable, os.path.join(ROOT, "scripts", "c0_gate.py"),
               "--checkpoint", ckpt, "--arch", str(arch),
               "--device", str(args.eval_device or args.device),
               "--games", str(int(args.eval_games)), "--seats", str(int(args.eval_seats)),
               "--seed-base", str(int(args.eval_seed_base)), "--smoke",
               "--bootstrap", "1000", "--out", out_json]
        t_eval = time.time()
        print(f"[eval] dec={int(decisions_done)} start games={args.eval_games}", flush=True)
        with open(log_path, "w", encoding="utf-8") as lf:
            rc = subprocess.call(cmd, cwd=ROOT, stdout=lf, stderr=lf)
        rec: Dict[str, Any] = {"decisions": int(decisions_done), "rc": int(rc),
                               "seconds": round(time.time() - t_eval, 1)}
        try:
            with open(out_json, encoding="utf-8") as f:
                d = json.load(f)
            p = d["panels"][0]
            rec.update({
                "mean_rank": float(p["model_mean_rank"]),
                "bot_mean_rank": float(p["bot_mean_rank"]),
                "top4": float(p["model_top4"]), "win": float(p["model_win"]),
                "mean_diff": float(p["mean_diff"]),
                "ci_low": float(p["ci_low"]), "ci_high": float(p["ci_high"]),
                "illegal": int(p["illegal"]), "truncated": int(p["truncated"]),
                "passed": bool(d.get("passed")),
            })
        except Exception as exc:  # noqa: BLE001
            rec["error"] = repr(exc)
        evals.append(rec)
        with open(os.path.join(eval_dir, "history.json"), "w", encoding="utf-8") as f:
            json.dump({"evals": evals}, f, ensure_ascii=False, indent=2)
        if rec.get("mean_rank") is not None:
            print(f"[eval] dec={int(decisions_done)} mean_rank={rec['mean_rank']:.3f} "
                  f"bot={rec['bot_mean_rank']:.3f} top4={rec['top4']:.3f} "
                  f"win={rec['win']:.3f} ({rec['seconds']}s)", flush=True)
            if rec["mean_rank"] <= 3.0:
                trig = os.path.join(args.out, "TRIGGER_library.json")
                with open(trig, "w", encoding="utf-8") as f:
                    json.dump({"decisions": int(decisions_done),
                               "mean_rank": rec["mean_rank"],
                               "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, f,
                              ensure_ascii=False, indent=2)
                print(f"[TRIGGER] avg rank {rec['mean_rank']:.3f} <= 3.0 -> "
                      f"构建高质量对局镜像库 ({trig})", flush=True)
        else:
            print(f"[eval] dec={int(decisions_done)} FAILED rc={rc} "
                  f"error={rec.get('error')} log={log_path}", flush=True)

    search_fn = search_cfg = None
    if int(args.sims) > 0:
        try:
            from hsbg.az import SearchConfig, search as az_search
        except Exception as exc:  # noqa: BLE001
            print(f"[error] search unavailable: {exc!r}", file=sys.stderr)
            return 2
        search_cfg = SearchConfig(simulations=int(args.sims),
                                  determinizations=int(args.determinizations),
                                  seed=int(args.seed))
        search_fn = az_search

    pool: Optional[ProcessActorPool] = None
    pool_ckpt = os.path.join(args.out, "_pool_weights.pt")
    if int(args.processes) > 1:
        if not str(args.gpus).strip():
            print("[error] --processes>1 需要 --gpus（物理 GPU 序号）", file=sys.stderr)
            return 2
        if os.environ.get("CUDA_VISIBLE_DEVICES"):
            print("[error] 请 unset CUDA_VISIBLE_DEVICES：--gpus 用物理序号", file=sys.stderr)
            return 2
        gpus = [int(x) for x in str(args.gpus).split(",") if x.strip()]
        save_checkpoint(model, pool_ckpt, meta={**meta, "arch": arch},
                        norm_mean=norm_mean, norm_std=norm_std)
        pool = ProcessActorPool(
            int(args.processes), gpus, pool_ckpt, arch=arch,
            sims=int(args.sims), determinizations=int(args.determinizations),
            seed=int(args.seed), threads=int(args.threads),
            batch_size=int(args.batch_size),
            tmpdir=os.path.join(args.out, "_proc_tmp"))
        print(f"[pool] {json.dumps(pool.describe(), ensure_ascii=False)}", flush=True)
    batch_server = None
    evaluator = None
    if pool is None and args.workers > 1:
        batch_server = BatchLeafServer(model, device=args.device,
                                       batch_size=int(args.batch_size),
                                       max_wait_ms=2.0, queue_size=8192,
                                       norm_mean=norm_mean, norm_std=norm_std)
        evaluator = BatchPPOEvaluator(batch_server)
    elif pool is None:
        evaluator = PPOEvaluator(model, device=args.device,
                                 norm_mean=norm_mean, norm_std=norm_std)
    t0 = time.time()
    deadline = t0 + float(args.minutes) * 60.0
    cum_decisions = 0
    next_eval = (int(args.eval_every_decisions)
                 if int(args.eval_every_decisions) > 0 else 10 ** 18)
    i = int(start_i)
    end_i = (int(start_i) + int(args.iterations)) if int(args.iterations) > 0 else 0
    last_len = 0.0
    while time.time() < deadline:
        if end_i > 0 and i >= end_i:
            break
        if last_len > 0 and (deadline - time.time()) < max(60.0, last_len):
            print("[loop] remaining time < last iteration; stop", flush=True)
            break
        _reload_s = 0.0
        _collect_s = 0.0
        _history_s_prev = locals().get("_history_s", 0.0)
        c_cfg = CollectConfig(
            games=int(args.games), seed=int(args.seed) + i * 1000,
            opponent=str(args.opponent), behavior=str(args.behavior),
            max_actions_per_turn=int(args.max_actions_per_turn),
            max_steps=int(args.max_steps))
        iter_start = time.time()
        if pool is not None:
            # 同步模式：先把最新权重推到每个 actor 进程（不重建进程）
            _t0 = time.time()
            save_checkpoint(model, pool_ckpt, meta={**meta, "arch": arch},
                            norm_mean=norm_mean, norm_std=norm_std)
            pool.reload_weights(pool_ckpt, updates=int(trainer.updates))
            _reload_s = time.time() - _t0
            _t1 = time.time()
            batch, collect_meta = pool.collect(
                c_cfg, int(args.games), return_records=True, progress=True,
                seed=int(c_cfg.seed), gamma=1.0, lam=float(args.lam))
            _collect_s = time.time() - _t1
        elif args.workers > 1:
            batch, collect_meta = collect_ppo_batch_parallel(
                model, c_cfg, workers=int(args.workers),
                search_fn=search_fn, search_config=search_cfg,
                eval_fn=evaluator, device=str(args.device),
                seed=int(args.seed) + i * 1000, gamma=1.0, lam=float(args.lam),
                norm_mean=norm_mean, norm_std=norm_std, progress=True)
        else:
            batch, collect_meta = collect_ppo_batch(
                model, c_cfg, search_fn=search_fn, search_config=search_cfg,
                eval_fn=evaluator, device=str(args.device),
                seed=int(args.seed) + i * 1000, gamma=1.0, lam=float(args.lam),
                norm_mean=norm_mean, norm_std=norm_std, progress=True)
        errs = batch.validate()
        if errs:
            print(f"[error] batch invalid: {errs}", file=sys.stderr)
            return 3
        # KL anchor 只在前 --anchor-iterations 个 iteration 生效（论文：前 100/300）
        trainer.config.anchor_coef = (float(args.anchor_beta)
                                      if i < int(args.anchor_iterations) else 0.0)
        _t_ppo = time.time()
        stats = trainer.update(batch)
        _ppo_s = time.time() - _t_ppo
        rec = {"iter": i, "collect": collect_meta, "ppo": stats,
               "profile": {"reload_s": round(_reload_s, 3),
                           "collect_s": round(_collect_s, 3),
                           "ppo_s": round(_ppo_s, 3),
                           "build_batch_s": round(float(collect_meta.get("build_batch_s", 0.0)), 3),
                           "parent_read_s": round(float(collect_meta.get("parent_read_s", 0.0)), 3),
                           "records_mb": round(float(collect_meta.get("records_bytes", 0)) / 1e6, 1),
                           "history_prev_s": round(float(_history_s_prev), 3)},
               "batch_server": (dict(batch_server.stats) if batch_server is not None else None),
               "seconds": time.time() - t0}
        history.append(rec)
        print(f"[iter {i}] samples={len(batch)} updates={stats['trainer_updates']} "
              f"lr={stats['lr']:.3g} total={stats['epochs'][-1]['total']:.4f}",
              flush=True)
        # 版本化快照：trainer 为权威，model 为导出；manifest 最后原子发布
        ver = int(trainer.updates)
        do_snap = (int(args.snapshot_every) <= 1) or ((i % int(args.snapshot_every)) == 0)
        if do_snap:
            snap = os.path.join(args.out, "snapshots", f"step_{ver:06d}")
            os.makedirs(snap, exist_ok=True)
            trainer.save(os.path.join(snap, "trainer.pt"))
            ckpt = os.path.join(snap, "model.pt")
            tmp_ckpt = ckpt + ".tmp"
            save_checkpoint(model, tmp_ckpt,
                            meta={**meta, "arch": arch, "trainer_updates": ver},
                            norm_mean=norm_mean, norm_std=norm_std)
            os.replace(tmp_ckpt, ckpt)
            # 兼容旧路径
            trainer.save(os.path.join(args.out, "trainer.pt"))
            ckpt_flat = os.path.join(args.out, "model.pt")
            save_checkpoint(model, ckpt_flat + ".tmp",
                            meta={**meta, "arch": arch, "trainer_updates": ver},
                            norm_mean=norm_mean, norm_std=norm_std)
            os.replace(ckpt_flat + ".tmp", ckpt_flat)
            manifest = {"version": ver, "trainer": os.path.join(snap, "trainer.pt"),
                        "model": os.path.join(snap, "model.pt"),
                        "arch": arch, "seed": int(args.seed),
                        "elapsed_s": time.time() - t0,
                        "history_len": len(history)}
            with open(os.path.join(args.out, "latest.json.tmp"), "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            os.replace(os.path.join(args.out, "latest.json.tmp"),
                       os.path.join(args.out, "latest.json"))
            keep = int(args.keep_snapshots)
            if keep > 0:
                snap_root = os.path.join(args.out, "snapshots")
                olds = sorted(d for d in os.listdir(snap_root)
                              if d.startswith("step_") and os.path.isdir(os.path.join(snap_root, d)))
                for d in olds[:-keep]:
                    shutil.rmtree(os.path.join(snap_root, d), ignore_errors=True)
        _th0 = time.time()
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump({"args": vars(args), "history": history,
                       "elapsed_s": time.time() - t0}, f, ensure_ascii=False, indent=2)
        _history_s = time.time() - _th0
        # 累计 decisions + 周期评测（512 局 C0，暂停采集）
        cum_decisions += int(collect_meta.get("decisions", 0))
        if cum_decisions >= next_eval:
            _run_eval(cum_decisions)
            while next_eval <= cum_decisions:
                next_eval += int(args.eval_every_decisions)
        last_len = time.time() - iter_start
        i += 1

    if batch_server is not None:
        batch_server.close()
    if pool is not None:
        pool.close()
    # 收尾：最后一个 iteration 若不在快照点，也导出最终模型（评测/续训都要用）
    try:
        save_checkpoint(model, os.path.join(args.out, "model.pt"),
                        meta={**meta, "arch": arch,
                              "trainer_updates": int(trainer.updates)},
                        norm_mean=norm_mean, norm_std=norm_std)
        trainer.save(os.path.join(args.out, "trainer.pt"))
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] final save failed: {exc!r}", flush=True)
    summary = {"iterations": i, "updates": trainer.updates,
               "elapsed_s": time.time() - t0, "config": vars(args),
               "history": history}
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(to_jsonable(summary), f, ensure_ascii=False, indent=2)
    print(f"[done] iters={i} updates={trainer.updates} "
          f"elapsed={time.time()-t0:.0f}s -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
