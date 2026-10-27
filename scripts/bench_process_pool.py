#!/usr/bin/env python3
"""进程级 actor pool 资源扫描（持久 worker 版）。

与 2026-10-27 旧版（每轮新建 Pool -> BrokenPipe、30min 跑不完）的区别见
`hsbg/az/train/process_pool.py` 顶部说明。

本脚本产出（每轮 + 汇总）：

- decisions/s、leaf/s、batch fill（batches/leafs 来自各 worker 的 BatchLeafServer）；
- queue wait p50/p95（submit -> 开始聚批的等待），batch size p50/p95；
- 持续采样的 GPU util / 显存（空闲判定 + 均值/p95/峰值）；
- illegal / truncated / worker 重启次数；
- 每轮中间结果写盘，崩溃也保留数据。

用法（不设 CUDA_VISIBLE_DEVICES：--gpus 用**物理** GPU 序号）：

  P=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
  $P scripts/bench_process_pool.py \
    --checkpoint runs/az_entity_1m_s0/model.pt --arch entity \
    --processes 4 --gpus 0,5,6,7 --threads 16 --games 64 --sims 4 \
    --minutes 30 --out runs/bench/process_4gpu_30min_clean.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.ppo import CollectConfig  # noqa: E402
from hsbg.az.train.process_pool import ProcessActorPool  # noqa: E402


# ---------------------------------------------------------------------------
# GPU 采样
# ---------------------------------------------------------------------------
def _gpu_snapshot() -> List[Dict[str, int]]:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"], text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return []
    rows = []
    for line in out.strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            rows.append({"index": int(parts[0]), "util": int(parts[1]),
                         "mem_mb": int(parts[2])})
        except ValueError:
            continue
    return rows


class GpuSampler(threading.Thread):
    """后台持续采样；线程只做 nvidia-smi，不影响 actor。"""

    def __init__(self, interval: float = 0.5) -> None:
        super().__init__(name="gpu-sampler", daemon=True)
        self.interval = float(interval)
        self.samples: List[Dict[str, Any]] = []
        self._stop_evt = threading.Event()

    def run(self) -> None:
        while not self._stop_evt.is_set():
            snap = _gpu_snapshot()
            if snap:
                self.samples.append({"t": time.time(), "gpus": snap})
            self._stop_evt.wait(self.interval)

    def stop(self) -> None:
        self._stop_evt.set()
        self.join(timeout=5.0)

    def window(self, t0: float, t1: float, gpus: List[int]) -> Dict[str, Any]:
        want = set(int(g) for g in gpus)
        per: Dict[int, Dict[str, List[int]]] = {g: {"util": [], "mem": []} for g in want}
        for s in self.samples:
            if not (t0 <= s["t"] <= t1):
                continue
            for row in s["gpus"]:
                if row["index"] in want:
                    per[row["index"]]["util"].append(int(row["util"]))
                    per[row["index"]]["mem"].append(int(row["mem_mb"]))

        def _pct(xs: List[int], q: float) -> float:
            if not xs:
                return 0.0
            ys = sorted(float(x) for x in xs)
            i = min(len(ys) - 1, max(0, int(round(q * (len(ys) - 1)))))
            return float(ys[i])

        rows = {}
        for g, d in per.items():
            u = d["util"]
            rows[str(g)] = {
                "n": len(u),
                "util_mean": float(np.mean(u)) if u else 0.0,
                "util_p50": _pct(u, 0.5), "util_p95": _pct(u, 0.95),
                "util_max": float(max(u)) if u else 0.0,
                "mem_mb_max": float(max(d["mem"])) if d["mem"] else 0.0,
            }
        allu = [v for d in per.values() for v in d["util"]]
        return {"per_gpu": rows,
                "util_mean_all": float(np.mean(allu)) if allu else 0.0,
                "util_p50_all": _pct(allu, 0.5),
                "util_p95_all": _pct(allu, 0.95)}


def _pct(xs: List[float], q: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(float(x) for x in xs)
    i = min(len(ys) - 1, max(0, int(round(q * (len(ys) - 1)))))
    return float(ys[i])


def _check_gpus_idle(gpus: List[int], allow_busy: bool) -> Dict[str, Any]:
    snap = _gpu_snapshot()
    busy = []
    for row in snap:
        if row["index"] in gpus and (row["mem_mb"] > 2048 or row["util"] > 20):
            busy.append(row)
    info = {"snapshot": snap, "busy": busy}
    if busy and not allow_busy:
        msg = ", ".join(f"gpu{r['index']} util={r['util']}% mem={r['mem_mb']}MiB"
                        for r in busy)
        raise SystemExit(
            f"[error] 指定 GPU 上有其他任务，拒绝污染扫描: {msg}\n"
            f"        换空闲卡，或显式加 --allow-busy 承担污染风险")
    return info


def main() -> int:
    ap = argparse.ArgumentParser(description="进程级 actor pool 扫描（持久 worker）")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--arch", default="entity")
    ap.add_argument("--processes", type=int, default=4)
    ap.add_argument("--gpus", default="0,5,6,7")
    ap.add_argument("--threads", type=int, default=16,
                    help="每个进程内的采集线程数（多局并发 + 共享 batch leaf）")
    ap.add_argument("--games", type=int, default=64, help="每轮总 games")
    ap.add_argument("--sims", type=int, default=4)
    ap.add_argument("--determinizations", type=int, default=1)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--max-wait-ms", type=float, default=2.0)
    ap.add_argument("--max-steps", type=int, default=10000)
    ap.add_argument("--warmup-rounds", type=int, default=1)
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--allow-busy", action="store_true")
    ap.add_argument("--no-records", action="store_true",
                    help="扫描不需要轨迹（默认就不回传 records）")
    ap.add_argument("--out", default="runs/bench/process_pool_scan.json")
    args = ap.parse_args()

    if os.environ.get("CUDA_VISIBLE_DEVICES"):
        raise SystemExit("[error] 请 unset CUDA_VISIBLE_DEVICES：--gpus 使用物理 GPU 序号")
    gpus = [int(x) for x in str(args.gpus).split(",") if x.strip()]
    idle = _check_gpus_idle(gpus, bool(args.allow_busy))
    print(f"[gpu] use={gpus} idle_check={'busy_allowed' if idle['busy'] else 'clean'}",
          flush=True)
    if idle["busy"]:
        print(f"[gpu][warn] 以下 GPU 仍被占用: {idle['busy']}", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    pool = ProcessActorPool(
        int(args.processes), gpus, args.checkpoint, arch=str(args.arch),
        sims=int(args.sims), determinizations=int(args.determinizations),
        seed=int(args.seed), threads=int(args.threads),
        batch_size=int(args.batch_size), max_wait_ms=float(args.max_wait_ms),
        tmpdir=os.path.join(os.path.dirname(os.path.abspath(args.out)), "_proc_tmp"))
    print(f"[pool] {json.dumps(pool.describe(), ensure_ascii=False)}", flush=True)

    sampler = GpuSampler(interval=0.5)
    sampler.start()

    rounds: List[Dict[str, Any]] = []
    t_all0 = time.time()
    deadline = t_all0 + float(args.minutes) * 60.0
    rnd = 0

    def _write(final: bool) -> None:
        measured = [r for r in rounds if r.get("measured")]
        decs = sum(int(r["decisions"]) for r in measured)
        secs = sum(float(r["seconds"]) for r in measured)
        dps = [float(r["decisions_per_s"]) for r in measured]
        q95 = [float(r["queue_wait_ms_p95"]) for r in measured]
        q50 = [float(r["queue_wait_ms_p50"]) for r in measured]
        fills = [float(r["batch_fill"]) for r in measured]
        leafs = [float(r["leaf_per_s"]) for r in measured]
        summary = {
            "measured_rounds": len(measured),
            "decisions": decs,
            "seconds_sum": secs,
            "decisions_per_s": (decs / secs) if secs > 0 else 0.0,
            "decisions_per_s_p50": _pct(dps, 0.5),
            "decisions_per_s_p95": _pct(dps, 0.95),
            "leaf_per_s_median": _pct(leafs, 0.5),
            "queue_wait_ms_p50_median": _pct(q50, 0.5),
            "queue_wait_ms_p95_median": _pct(q95, 0.5),
            "queue_wait_ms_p95_worst": max(q95) if q95 else 0.0,
            "batch_fill_median": _pct(fills, 0.5),
            "illegal": sum(int(r["illegal"]) for r in measured),
            "truncated": sum(int(r["truncated"]) for r in measured),
            "restarts": pool.restarts,
            "elapsed_s": time.time() - t_all0,
            "gpu_window": sampler.window(
                measured[0]["t0"], measured[-1]["t1"], gpus) if measured else {},
        }
        payload = {
            "args": vars(args),
            "pool": pool.describe(),
            "gpu_idle_check": idle,
            "rounds": rounds,
            "summary": summary,
            "finished": bool(final),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        tmp = args.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, args.out)

    try:
        while time.time() < deadline:
            rnd += 1
            measured = rnd > int(args.warmup_rounds)
            games = int(args.games)
            if not measured:
                games = max(2, games // 4)
            t0 = time.time()
            cfg = CollectConfig(games=games, seed=int(args.seed) + rnd * 1000,
                                opponent="bot", behavior="net",
                                max_steps=int(args.max_steps))
            try:
                _batch, meta = pool.collect(
                    cfg, games, return_records=not bool(args.no_records),
                    progress=False, seed=int(cfg.seed),
                    timeout=max(600.0, float(args.minutes) * 60.0))
            except BaseException as exc:  # noqa: BLE001
                rounds.append({"round": rnd, "measured": measured, "error": repr(exc),
                               "seconds": time.time() - t0})
                print(f"[round {rnd}] ERROR {exc!r}", flush=True)
                _write(False)
                time.sleep(3.0)
                continue
            t1 = time.time()
            dt = max(t1 - t0, 1e-9)
            gpu_win = sampler.window(t0, t1, gpus)
            rec = {
                "round": rnd, "measured": measured, "games": games,
                "t0": t0, "t1": t1, "seconds": dt,
                "decisions": int(meta["decisions"]),
                "decisions_per_s": int(meta["decisions"]) / dt,
                "records": int(meta["records"]),
                "leafs": int(meta["leafs"]),
                "leaf_per_s": float(meta["leaf_per_s"]),
                "batches": int(meta["batches"]),
                "batch_fill": float(meta["batch_fill"]),
                "batch_p50": float(meta["batch_p50"]),
                "batch_p95": float(meta["batch_p95"]),
                "queue_wait_ms_p50": float(meta["queue_wait_ms_p50"]),
                "queue_wait_ms_p95": float(meta["queue_wait_ms_p95"]),
                "illegal": int(meta["illegal_actions"]),
                "truncated": int(meta["truncated_games"]),
                "restarts": int(meta["restarts"]),
                "gpu": gpu_win,
                "workers": meta["workers"],
            }
            rounds.append(rec)
            _write(False)
            print(f"[round {rnd}{'' if measured else ' warmup'}] "
                  f"{rec['decisions']} dec / {dt:.1f}s = {rec['decisions_per_s']:.1f} dec/s "
                  f"leaf/s={rec['leaf_per_s']:.0f} fill={rec['batch_fill']:.2f} "
                  f"q50={rec['queue_wait_ms_p50']:.2f}ms q95={rec['queue_wait_ms_p95']:.2f}ms "
                  f"gpu_util={gpu_win.get('util_mean_all', 0):.1f}%", flush=True)
    except KeyboardInterrupt:
        print("[scan] interrupted", flush=True)
    finally:
        sampler.stop()
        _write(True)
        pool.close()

    payload = json.load(open(args.out, encoding="utf-8"))
    print("[done] " + json.dumps(payload["summary"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
