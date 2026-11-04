#!/usr/bin/env python3
"""stage_monitor.py — 300M 大规模 PPO 训练守护器（10M 计点 + 监控 + 曲线）。

职责
----
1. 增量读 ``runs/<run>/history.jsonl``，按**本 run 累计 decisions** 每跨过
   ``--point-every``（默认 10M）记一个计点；在该 run 的 ``eval/`` 目录里找
   ``ckpt_<decisions>.pt``（取 decisions >= 点的最小者），调用既有唯一口径
   ``scripts/eval_panel.sh``（96 局 / seed 520000 / 5 席 p0.9 / full）打点，
   结果追加到 ``points.jsonl``。
2. 每 ``--system-every``（默认 60s）采系统指标（GPU 显存/利用率、训练进程 CPU/RSS、
   load、磁盘）到 ``system.jsonl``。
3. 异常写 ``alerts.log``：进程消失、summary.json 出现、illegal>0、truncated 突增、
   restarts>0、NaN/Inf 损失、dec/s<3000 连续 3 次、计点评测失败、评测卡显存不足。
4. 每次新增点或每 ``--redraw-every``（默认 300s）重绘 ``curves.png``（16 面板）与
   ``dashboard.md``（当前点表 + 异常摘要）。

本脚本**只读**训练进程与训练配置；唯一的对外动作是调用 ``scripts/eval_panel.sh``
（同一时间只跑 1 个评测进程）。不改训练代码，不动其它 run 目录。

常用命令
--------
常驻（真实 300M 训练，推荐）::

    cd /home/data/users/gaoletian/projects/HSBRSIM
    export PYTHONPATH=rust/python:.
    nohup /home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python \
      scripts/stage_monitor.py --run runs/az_stage300 \
      --until-decisions 300000000 --eval-gpu auto \
      >> runs/az_stage300/monitor.log 2>&1 &

一次性离线自测（不评测、不写 run 目录）::

    python scripts/stage_monitor.py --run runs/az_entity_s73 \
      --until-decisions 50000000 --no-eval --once \
      --out-prefix runs/_stage_monitor_selftest/s73

参数速查
--------
``--run/--until-decisions/--point-every``：run 目录与计点范围。
``--eval-gpu auto|cuda:N``：auto 时按 ``--gpu-priority``（默认 1,7,5,4,3,0,2,6）
选「不在训练 actors/learner 列表、free >= --min-free-mib」的卡。
``--once``：只跑一轮后退出（可用于补点/离线出图）；``--no-eval``：只监控出图不评测。
``--out-prefix P``：把 points/system/alerts/curves/dashboard 写到 ``P.*``（自测隔离用）。
``--points-file``：覆盖 points.jsonl 路径（离线补测/迁移用）。
``--keep-alive``：训练结束后仍常驻（默认训练结束且计点补齐后退出）。
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import shutil
import signal
import statistics as st
import subprocess
import sys
import time
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN_SCRIPT = "train_entity_sync.py"
DEFAULT_SEED = 520000
DPS_MIN = 3000.0
_CKPT_RE = re.compile(r"^ckpt_(\d+)\.pt$")

# ---------------------------------------------------------------- 基础工具


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _num(v, default=None):
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl(path):
    out = []
    if not os.path.isfile(path):
        return out
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def _append_jsonl(path, obj) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass


def _run(cmd, cwd=None, env=None, timeout=None):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, errors="replace")
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return -9, "", "timeout"
    except FileNotFoundError as exc:
        return -2, "", str(exc)
    except Exception as exc:  # noqa: BLE001
        return -1, "", repr(exc)


def _tail(text: str, n: int = 600) -> str:
    text = (text or "").strip().replace("\n", " | ")
    return text[-n:]


def _paths(run: str, prefix: str = ""):
    if prefix:
        base = os.path.abspath(prefix)
        return {
            "dir": os.path.dirname(base) or ".",
            "points": base + ".points.jsonl",
            "system": base + ".system.jsonl",
            "alerts": base + ".alerts.log",
            "png": base + ".curves.png",
            "dash": base + ".dashboard.md",
        }
    return {
        "dir": run,
        "points": os.path.join(run, "points.jsonl"),
        "system": os.path.join(run, "system.jsonl"),
        "alerts": os.path.join(run, "alerts.log"),
        "png": os.path.join(run, "curves.png"),
        "dash": os.path.join(run, "dashboard.md"),
    }


# ---------------------------------------------------------------- 进程 / GPU


def _ps_lines():
    rc, out, _ = _run(["ps", "-eo", "pid,etime,args", "--no-headers"])
    return out.splitlines() if rc == 0 else []


def find_trainers(run: str):
    """找出 --out 指向 run 的 train_entity_sync.py 进程。"""
    goal = os.path.normpath(run)
    goal_abs = os.path.abspath(run)
    found = []
    for line in _ps_lines():
        if TRAIN_SCRIPT not in line:
            continue
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(.*)$", line)
        if not m:
            continue
        pid, etime, args = int(m.group(1)), m.group(2), m.group(3)
        mout = re.search(r"--out[ =](\S+)", args)
        out_path = mout.group(1) if mout else ""
        out_norm = os.path.normpath(out_path) if out_path else ""
        if out_norm in (goal, goal_abs) or f"--out {goal}" in args:
            found.append({"pid": pid, "etime": etime, "args": args})
    return found


def _args_flag(args: str, flag: str):
    m = re.search(re.escape(flag) + r"\s+(\S+)", args or "")
    return m.group(1) if m else ""


def gpu_table():
    rc, out, _ = _run(["nvidia-smi",
                       "--query-gpu=index,memory.used,memory.total,utilization.gpu",
                       "--format=csv,noheader,nounits"])
    rows = []
    if rc != 0:
        return rows
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        rows.append({
            "index": int(parts[0]),
            "used": _int(_num(parts[1], 0)),
            "total": _int(_num(parts[2], 0)),
            "util": _int(_num(parts[3], 0)),
        })
    return rows


def training_gpu_exclusions(trainers, hist_last_row=None):
    """返回训练正在用的 GPU 列表（actor + learner）。"""
    excluded = set()
    for tr in trainers:
        gpus = _args_flag(tr["args"], "--gpus")
        for tok in gpus.split(","):
            if tok.strip().isdigit():
                excluded.add(int(tok.strip()))
        dev = _args_flag(tr["args"], "--device")
        m = re.search(r"cuda:(\d+)", dev)
        if m:
            excluded.add(int(m.group(1)))
    if hist_last_row:
        collect = hist_last_row.get("collect") or {}
        for g in collect.get("gpus") or []:
            if isinstance(g, int):
                excluded.add(g)
    return sorted(excluded)


def pick_eval_gpu(args, trainers, hist_last_row):
    """返回 (device|None, reason)。auto 优先 cuda:1/7/5，要求 free>=min_free_mib。"""
    table = gpu_table()
    free = {r["index"]: r["total"] - r["used"] for r in table}
    excluded = set(training_gpu_exclusions(trainers, hist_last_row))
    want = (args.eval_gpu or "auto").strip()
    if want != "auto":
        m = re.search(r"cuda:(\d+)", want)
        if not m:
            return None, f"非法 --eval-gpu: {want}"
        idx = int(m.group(1))
        if idx not in free:
            return None, f"GPU {idx} 不在 nvidia-smi 输出中"
        if free[idx] < args.min_free_mib and not args.allow_low_free:
            return None, f"GPU {idx} free={free[idx]}MiB < {args.min_free_mib}MiB"
        return f"cuda:{idx}", f"explicit free={free[idx]}MiB"
    prio = [int(x) for x in str(args.gpu_priority).replace(" ", "").split(",") if x.isdigit()]
    for idx in prio:
        if idx in excluded or idx not in free:
            continue
        if free[idx] >= args.min_free_mib:
            return f"cuda:{idx}", (f"auto free={free[idx]}MiB"
                                  f"（排除 actors/learner {sorted(excluded)}）")
    return None, (f"无可用卡：排除 {sorted(excluded)} 后均 free<{args.min_free_mib}MiB；"
                  f"free={free}")


# ---------------------------------------------------------------- history.jsonl


class JsonlTail:
    """按字节偏移增量读 JSONL，容忍半行与文件被截断。"""

    def __init__(self, path: str):
        self.path = path
        self.off = 0
        self.buf = b""

    def read(self):
        out = []
        if not os.path.isfile(self.path):
            return out
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return out
        if size < self.off:
            self.off = 0
            self.buf = b""
        try:
            with open(self.path, "rb") as f:
                f.seek(self.off)
                chunk = f.read()
        except OSError:
            return out
        self.off += len(chunk)
        self.buf += chunk
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            out.append(d)
        return out


class History:
    """history.jsonl 的增量解析 + 派生序列（X 轴=本 run 累计 decisions）。"""

    def __init__(self, path: str):
        self.path = path
        self.tail = JsonlTail(path)
        self.rows = []
        self.new = []
        self.cum = 0
        self.ser = {}
        self.iter = 0
        self.last = None

    def _add(self, r):
        if not isinstance(r, dict) or "iter" not in r:
            return
        c = r.get("collect") or {}
        p = r.get("profile") or {}
        ppo = r.get("ppo") or {}
        ep = (ppo.get("epochs") or [{}])[0] or {}
        dec = _int(c.get("decisions"))
        self.cum += dec
        vals = {
            "dec": float(dec),
            "cum_m": self.cum / 1e6,
            "dps": _num(c.get("decisions_per_s"), 0.0),
            "collect_s": _num(p.get("collect_s"), 0.0),
            "ppo_s": _num(p.get("ppo_s"), 0.0),
            "ent": _num(ep.get("entropy")),
            "kl": _num(ep.get("approx_kl")),
            "clip": _num(ep.get("clip_frac")),
            "pl": _num(ep.get("policy_loss")),
            "vl": _num(ep.get("value_loss")),
            "lr": _num(ppo.get("lr")),
            "anchor_kl": _num(ep.get("anchor_kl")),
            "illegal": float(_int(c.get("illegal_actions"))),
            "trunc": float(_int(c.get("truncated_games"))),
            "restarts": float(_int(c.get("restarts"))),
            "cuda_peak": _num(ppo.get("cuda_peak_mb")),
            "hb_applied": float(_int(c.get("human_board_applied"))),
            "hb_attempt": float(_int(c.get("human_board_attempt"))),
            "batch_fill": _num(c.get("batch_fill")),
            "batch_p50": _num(c.get("batch_p50")),
            "sec": _num(r.get("seconds")),
        }
        self.rows.append(r)
        self.last = r
        self.iter = _int(r.get("iter"))
        for k, v in vals.items():
            self.ser.setdefault(k, []).append(v)
        self.new.append(vals)

    def load_all(self):
        for r in self.tail.read():
            self._add(r)
        return self

    def poll(self):
        for r in self.tail.read():
            self._add(r)
        return self.new

    def take_new(self):
        out, self.new = self.new, []
        return out

    def series(self, key):
        return self.ser.get(key) or []

    def cum_m(self):
        return self.series("cum_m")


def load_dev_evals(run: str, offset: int = 0, offset_from_index: int = 0,
                   resume_epoch: float = 0.0):
    """训练内 dev 面板（seed 420000）的历次 eval 记录。

    断点续训后 eval/history.json 新条目用**进程内** decisions（从 0 开始），且文件按
    decisions 排序，续训前后的条目会交错（5M,10M,15M,20M...），不能用 index 区分。
    这里按 eval ckpt 的 mtime 判断：mtime >= resume_epoch 的条目是续训后产生的，
    加全局 offset。``offset_from_index`` 仅在没给 resume_epoch 时作为回退。
    """
    d = _read_json(os.path.join(run, "eval", "history.json")) or {}
    out = []
    for i, e in enumerate(d.get("evals") or []):
        if not isinstance(e, dict):
            continue
        dec = _num(e.get("decisions"))
        if dec is None:
            continue
        if offset:
            add = i >= int(offset_from_index)
            if resume_epoch:
                ck = os.path.join(run, "eval", f"ckpt_{int(dec):09d}.pt")
                try:
                    add = os.path.isfile(ck) and os.path.getmtime(ck) >= float(resume_epoch)
                except OSError:
                    add = False
            if add:
                dec = float(dec) + float(offset)
        out.append({
            "decisions": dec,
            "rank": _num(e.get("human_mean_rank")),
            "top4": _num(e.get("human_top4")),
            "win": _num(e.get("human_win")),
            "seconds": _num(e.get("seconds")),
            "rc": e.get("rc"),
        })
    out.sort(key=lambda x: x["decisions"])
    return out


# ---------------------------------------------------------------- 计点 / 评测


class Points:
    def __init__(self, path: str):
        self.path = path
        self.entries = _load_jsonl(path)
        self.keys = set()
        for e in self.entries:
            p = _num(e.get("point_decisions"))
            if p is not None:
                self.keys.add(int(p))

    def done(self, point: int) -> bool:
        return int(point) in self.keys

    def add(self, entry) -> None:
        entry.setdefault("ts", _iso())
        _append_jsonl(self.path, entry)
        self.entries.append(entry)
        p = _num(entry.get("point_decisions"))
        if p is not None:
            self.keys.add(int(p))


def list_ckpts(run: str):
    out = []
    for p in glob.glob(os.path.join(run, "eval", "ckpt_*.pt")):
        m = _CKPT_RE.match(os.path.basename(p))
        if m:
            out.append((int(m.group(1)), p))
    return sorted(out)


def pick_ckpt(run: str, point: int):
    """decisions >= 点的最小 ckpt；返回 (decisions, path) 或 None。"""
    cands = [(d, p) for d, p in list_ckpts(run) if d >= point]
    return min(cands) if cands else None


def _valid_panel(path):
    d = _read_json(path) or {}
    if isinstance(d, dict) and d.get("mean_rank") is not None:
        return d
    return None


def canonical_eval(run: str, point: int, ckpt_dec: int, ckpt: str,
                   gpu: str, args, points_dir_png=None):
    runbase = os.path.basename(os.path.normpath(run))
    tag = f"{runbase}_{int(round(point / 1e6))}M"
    out_json = os.path.join(REPO, "runs", "eval_panel", tag + ".json")
    t0 = time.time()
    reused = False
    d = _valid_panel(out_json)
    if d is not None:
        reused = True
        sec = 0.0
        rc = 0
        err = ""
    else:
        env = os.environ.copy()
        env["EVAL_DEVICE"] = gpu
        env["EVAL_SEED"] = str(args.eval_seed)
        env["PYTHONPATH"] = "rust/python:."
        cmd = ["bash", "scripts/eval_panel.sh", ckpt, tag, str(args.eval_games)]
        rc, _out, err = _run(cmd, cwd=REPO, env=env, timeout=args.eval_timeout)
        sec = time.time() - t0
        d = _valid_panel(out_json) or {}
    _w = d.get("weighted") or {}
    _wm = _w.get("weighted") if isinstance(_w.get("weighted"), dict) else _w
    entry = {
        "ts": _iso(),
        "point_decisions": int(point),
        "ckpt_decisions": int(ckpt_dec),
        "ckpt": ckpt,
        "tag": tag,
        "gpu": gpu,
        "seed": int(args.eval_seed),
        "games": _int(d.get("games"), args.eval_games),
        "status": "ok" if d.get("mean_rank") is not None else "failed",
        "reason": "" if d.get("mean_rank") is not None else _tail(err),
        "rank": _num(d.get("mean_rank")),
        "top4": _num(d.get("top4")),
        "win": _num(d.get("win")),
        "strength": _num(d.get("death_strength_p50")),
        "tier_ge4": _num(d.get("tier_ge4_ratio")),
        "tier_ge5_t15": _num(d.get("tier_ge5_t15")),
        "survive12": _num(d.get("survive_t12_ratio")),
        "tier_p50_t15": _num(d.get("tier_p50_t15")),
        "w_rank": _num(_wm.get("mean_rank")),
        "w_top4": _num(_wm.get("top4")),
        "w_win": _num(_wm.get("win")),
        "w_strength": _num(_wm.get("mean_strength")),
        "w_n_eff": _num(d.get("weight_n_eff")),
        "seconds": round(sec, 1),
        "reused": reused,
        "rc": int(rc),
    }
    return entry


# ---------------------------------------------------------------- 系统采样 / 告警


def _proc_ticks(pid: int):
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            parts = f.read().split()
        return int(parts[13]) + int(parts[14])
    except Exception:
        return None


def _proc_rss_mb(pid: int) -> float:
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


class SystemSampler:
    def __init__(self):
        self.prev = None

    def sample(self, run: str, cum: float):
        now = time.time()
        gpus = gpu_table()
        trainers = find_trainers(run)
        pids = [t["pid"] for t in trainers]
        ticks = 0
        rss = 0.0
        for pid in pids:
            t = _proc_ticks(pid)
            if t is not None:
                ticks += t
            rss += _proc_rss_mb(pid)
        cpu_pct = None
        if pids and self.prev and now > self.prev["t"] and self.prev["pids"] == pids:
            dt = now - self.prev["t"]
            try:
                clk = float(os.sysconf("SC_CLK_TCK") or 100)
            except Exception:
                clk = 100.0
            cpu_pct = max(0.0, 100.0 * (ticks - self.prev["ticks"]) / (dt * clk))
        load1 = load5 = load15 = None
        try:
            load1, load5, load15 = os.getloadavg()
        except Exception:
            pass
        disk_free_gb = disk_total_gb = None
        try:
            du = shutil.disk_usage(REPO)
            disk_free_gb = round(du.free / 1024 ** 3, 2)
            disk_total_gb = round(du.total / 1024 ** 3, 2)
        except Exception:
            pass
        self.prev = {"t": now, "pids": pids, "ticks": ticks}
        train_gpus = training_gpu_exclusions(trainers)
        train_rows = [r for r in gpus if r["index"] in train_gpus]
        row = {
            "ts": _iso(),
            "epoch": round(now, 1),
            "cum_decisions": int(cum),
            "trainer_pids": pids,
            "trainer_etime": trainers[0]["etime"] if trainers else None,
            "gpus": gpus,
            "gpu_free_mib": {str(r["index"]): r["total"] - r["used"] for r in gpus},
            "gpu_used_mib_total": sum(r["used"] for r in gpus) if gpus else None,
            "gpu_util_max": max((r["util"] for r in gpus), default=None),
            "train_gpus": train_gpus,
            "train_gpus_used_mib": sum(r["used"] for r in train_rows) if train_rows else None,
            "train_gpus_util_max": max((r["util"] for r in train_rows), default=None),
            "train_gpus_free_min_mib": (min(r["total"] - r["used"] for r in train_rows)
                                        if train_rows else None),
            "cpu_pct": round(cpu_pct, 1) if cpu_pct is not None else None,
            "rss_mb": round(rss, 1) if pids else None,
            "load1": round(load1, 2) if load1 is not None else None,
            "load5": round(load5, 2) if load5 is not None else None,
            "load15": round(load15, 2) if load15 is not None else None,
            "disk_free_gb": disk_free_gb,
            "disk_total_gb": disk_total_gb,
        }
        return row


class Alerts:
    def __init__(self, path: str):
        self.path = path
        self.active = {}
        self.events = []
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    def log(self, level: str, kind: str, msg: str, cooldown: float = 600.0) -> bool:
        now = time.time()
        if kind in self.active and now - self.active[kind] < cooldown:
            return False
        self.active[kind] = now
        line = f"[{_now()}] {level:<8} {kind:<20} {msg}"
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        self.events.append(line)
        return True

    def resolve(self, kind: str) -> None:
        if kind in self.active:
            del self.active[kind]
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(f"[{_now()}] RESOLVED {kind}\n")
            except OSError:
                pass

    def recent(self, n: int = 20):
        return _tail_lines(self.path, n)


def _tail_lines(path: str, n: int):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [ln.rstrip("\n") for ln in f.readlines()[-n:]]
    except OSError:
        return []


# ---------------------------------------------------------------- 绘图


def _setup_font():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: F401
    from matplotlib import font_manager as fm

    for p in glob.glob("/usr/share/fonts/google-noto-cjk/NotoSansCJK-*.ttc"):
        try:
            fm.fontManager.addfont(p)
        except Exception:
            pass
    for name in ("Noto Sans CJK JP", "Noto Sans CJK SC"):
        if any(f.name == name for f in fm.fontManager.ttflist):
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            break
    return plt


def _xy(xs, ys):
    px, py = [], []
    for x, y in zip(xs, ys):
        if x is None or y is None:
            continue
        try:
            if not (math.isfinite(float(x)) and math.isfinite(float(y))):
                continue
        except (TypeError, ValueError):
            continue
        px.append(float(x))
        py.append(float(y))
    return px, py


def _empty(ax, msg="无数据"):
    """没有数据序列时才提示；参考线（axhline，无 marker）不算数据。

    2026-11-04 修复：此前用「最后一个 series 为空」判断，canonical 有点但 dev 未出时
    会误显示「无数据」，并把提示文字压在第一个点上。
    """
    for line in ax.lines:
        try:
            marker = line.get_marker()
        except Exception:
            continue
        if marker not in (None, "", "None", " "):
            return
    if getattr(ax, "collections", None):
        return
    ax.text(0.5, 0.5, msg, ha="center", va="center", fontsize=10, color="gray",
            transform=ax.transAxes)


def _legend(ax, **kw):
    """只在有带标签图元时才画 legend（避免空 legend 警告）。"""
    try:
        handles, _labels = ax.get_legend_handles_labels()
    except Exception:
        return
    if handles:
        ax.legend(**kw)


def _finish(ax, title, xlabel="累计 decisions (M)", ylabel=""):
    ax.set_title(title, fontsize=10)
    ax.set_xlabel(xlabel, fontsize=8)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=8)
    ax.grid(alpha=0.3)
    ax.tick_params(labelsize=7)


def draw(run, paths, hist, dev, points, samples, alerts, args, status):
    plt = _setup_font()
    fig, axes = plt.subplots(4, 4, figsize=(22, 17))
    ax = axes.ravel()
    X = hist.cum_m()

    canon = sorted([p for p in points.entries if p.get("status") == "ok"],
                   key=lambda e: e.get("point_decisions") or 0)
    cx = [(e.get("point_decisions") or 0) / 1e6 for e in canon]

    def cser(key):
        return _xy(cx, [e.get(key) for e in canon])

    dx = [e["decisions"] / 1e6 for e in dev]

    # 1 rank：canonical + dev 对照 + 基线
    a = ax[0]
    xs, ys = cser("rank")
    if xs:
        a.plot(xs, ys, "o-", color="tab:blue", label="canonical rank (seed 520000)")
    xs, ys = _xy(cx, [e.get("w_rank") for e in canon])
    if xs:
        a.plot(xs, ys, "s--", color="tab:orange", alpha=0.85,
               label="canonical w_rank (len+str)")
    xs, ys = _xy(dx, [e["rank"] for e in dev])
    if xs:
        a.plot(xs, ys, "s--", color="tab:red", alpha=0.75, label="dev rank (seed 420000)")
    if args.baseline_rank:
        a.axhline(args.baseline_rank, color="gray", ls=":", lw=1,
                  label=f"s61 基线 {args.baseline_rank}")
    _finish(a, "1) 评测名次（越低越好）", ylabel="mean rank")
    if not xs:
        _empty(a)
    _legend(a, fontsize=6)

    # 2 top4 / win
    a = ax[1]
    xs, ys = cser("top4")
    if xs:
        a.plot(xs, [v * 100 for v in ys], "o-", color="tab:green", label="canonical top4%")
    xs, ys = _xy(cx, [e.get("w_top4") for e in canon])
    if xs:
        a.plot(xs, [v * 100 for v in ys], "s--", color="tab:orange", alpha=0.85,
               label="canonical w_top4%")
    xs, ys = _xy(dx, [e["top4"] for e in dev])
    if xs:
        a.plot(xs, [v * 100 for v in ys], "s--", color="tab:olive", alpha=0.75,
               label="dev top4%")
    xs, ys = cser("win")
    if xs:
        a.plot(xs, [v * 100 for v in ys], "^:", color="tab:purple", lw=1, label="canonical win%")
    _finish(a, "2) top4 / 吃鸡率", ylabel="%")
    if not xs and not dev:
        _empty(a)
    _legend(a, fontsize=6)

    # 3 death strength
    a = ax[2]
    xs, ys = cser("strength")
    if xs:
        a.plot(xs, ys, "o-", color="tab:orange", label="canonical strength")
    xs, ys = _xy(cx, [e.get("w_strength") for e in canon])
    if xs:
        a.plot(xs, ys, "s--", color="tab:olive", alpha=0.85, label="canonical w_strength")
    if args.baseline_strength:
        a.axhline(args.baseline_strength, color="gray", ls=":", lw=1,
                  label=f"s61 基线 {args.baseline_strength}")
    _legend(a, fontsize=6)
    _finish(a, "3) 出局战团强度 p50", ylabel="Σ(atk+hp)")
    if not xs:
        _empty(a)

    # 4 tier>=4
    a = ax[3]
    xs, ys = cser("tier_ge4")
    if xs:
        a.plot(xs, ys, "o-", color="tab:brown")
    _finish(a, "4) tier>=4 比例", ylabel="ratio")
    if not xs:
        _empty(a)

    # 5 tier>=5 @turn15
    a = ax[4]
    xs, ys = cser("tier_ge5_t15")
    if xs:
        a.plot(xs, ys, "o-", color="tab:cyan")
    _finish(a, "5) tier>=5 @ turn15", ylabel="ratio")
    if not xs:
        _empty(a)

    # 6 survive12
    a = ax[5]
    xs, ys = cser("survive12")
    if xs:
        a.plot(xs, ys, "o-", color="darkcyan")
    _finish(a, "6) 存活到 turn12 比例", ylabel="ratio")
    if not xs:
        _empty(a)

    # 7 entropy
    a = ax[6]
    xs, ys = _xy(X, hist.series("ent"))
    if xs:
        a.plot(xs, ys, lw=0.9, color="tab:green")
    _finish(a, "7) 策略熵 entropy", ylabel="entropy")
    if not xs:
        _empty(a)

    # 8 approx_kl + clip_frac + target_kl
    a = ax[7]
    xs, ys = _xy(X, hist.series("kl"))
    if xs:
        a.plot(xs, ys, lw=0.9, color="tab:olive", label="approx_kl")
        a.axhline(0.02, color="red", ls="--", lw=0.8, alpha=0.7, label="target_kl 0.02")
    xs2, ys2 = _xy(X, hist.series("clip"))
    if xs2:
        b = a.twinx()
        b.plot(xs2, ys2, lw=0.7, color="tab:cyan", alpha=0.6, label="clip_frac")
        b.set_ylabel("clip_frac", fontsize=8)
        b.tick_params(labelsize=7)
        _legend(b, fontsize=6, loc="upper right")
    _finish(a, "8) approx_kl / clip_frac", ylabel="KL")
    if not xs:
        _empty(a)
    _legend(a, fontsize=6, loc="upper left")

    # 9 policy / value loss
    a = ax[8]
    xs, ys = _xy(X, hist.series("pl"))
    if xs:
        a.plot(xs, ys, lw=0.9, color="tab:blue", label="policy_loss")
    xs2, ys2 = _xy(X, hist.series("vl"))
    if xs2:
        b = a.twinx()
        b.plot(xs2, ys2, lw=0.9, color="tab:red", alpha=0.7, label="value_loss")
        b.set_ylabel("value_loss", fontsize=8)
        b.tick_params(labelsize=7)
        _legend(b, fontsize=6, loc="upper right")
    _finish(a, "9) policy / value loss", ylabel="policy_loss")
    if not xs and not xs2:
        _empty(a)
    _legend(a, fontsize=6, loc="upper left")

    # 10 lr + anchor_kl
    a = ax[9]
    xs, ys = _xy(X, hist.series("lr"))
    if xs:
        a.plot(xs, ys, lw=0.9, color="tab:purple", label="lr")
    xs2, ys2 = _xy(X, hist.series("anchor_kl"))
    if xs2:
        b = a.twinx()
        b.plot(xs2, ys2, lw=0.8, color="tab:gray", alpha=0.8, label="anchor_kl")
        b.set_ylabel("anchor_kl", fontsize=8)
        b.tick_params(labelsize=7)
        _legend(b, fontsize=6, loc="upper right")
    _finish(a, "10) 学习率 lr / anchor_kl", ylabel="lr")
    if not xs:
        _empty(a)
    _legend(a, fontsize=6, loc="upper left")

    # 11 dec/s + collect_s/ppo_s
    a = ax[10]
    xs, ys = _xy(X, hist.series("dps"))
    if xs:
        a.plot(xs, ys, lw=0.8, color="tab:blue", label="dec/s")
        a.axhline(DPS_MIN, color="red", ls=":", lw=0.8, label=f"{DPS_MIN:.0f} 阈值")
    xs2, ys2 = _xy(X, hist.series("collect_s"))
    xs3, ys3 = _xy(X, hist.series("ppo_s"))
    if xs2 or xs3:
        b = a.twinx()
        if xs2:
            b.plot(xs2, ys2, lw=0.7, color="tab:orange", alpha=0.65, label="collect_s")
        if xs3:
            b.plot(xs3, ys3, lw=0.7, color="tab:green", alpha=0.65, label="ppo_s")
        b.set_ylabel("seconds / iter", fontsize=8)
        b.tick_params(labelsize=7)
        _legend(b, fontsize=6, loc="upper right")
    _finish(a, "11) 吞吐 dec/s 与 collect/ppo 耗时", ylabel="dec/s")
    if not xs:
        _empty(a)
    _legend(a, fontsize=6, loc="upper left")

    # 12 illegal / truncated / restarts + GPU mem/util
    a = ax[11]
    xs, illegal = _xy(X, hist.series("illegal"))
    xs, trunc = _xy(X, hist.series("trunc"))
    xs, restarts = _xy(X, hist.series("restarts"))
    if xs:
        a.plot(xs, [max(0.01, v) for v in illegal], lw=0.8, color="tab:red", label="illegal/iter")
        a.plot(xs, [max(0.01, v) for v in trunc], lw=0.8, color="tab:orange", label="truncated/iter")
        a.plot(xs, [max(0.01, v) for v in restarts], lw=0.8, color="tab:brown",
               label="restarts/iter")
        a.set_yscale("log")
        if max(illegal + trunc + restarts) <= 0:
            a.text(0.02, 0.05, "illegal/truncated/restarts 全程 0（对数轴下限 1e-2）",
                   transform=a.transAxes, fontsize=7, color="gray")
    if samples:
        sx = [s.get("cum_decisions", 0) / 1e6 for s in samples]
        mem = []
        util = []
        for s in samples:
            used = s.get("train_gpus_used_mib")
            if used is None:
                used = s.get("gpu_used_mib_total") or 0
            mem.append((used or 0) / 1024.0)
            u = s.get("train_gpus_util_max")
            util.append(u if u is not None else (s.get("gpu_util_max") or 0))
        b = a.twinx()
        b.plot(sx, mem, lw=0.8, color="tab:blue", alpha=0.6, label="训练卡已用 GB")
        b.plot(sx, util, lw=0.6, color="tab:cyan", alpha=0.5, label="训练卡 util max %")
        b.set_ylabel("GB / %", fontsize=8)
        b.tick_params(labelsize=7)
        _legend(b, fontsize=6, loc="lower right")
    _finish(a, "12) 非法/截断/重启 + GPU")
    if not xs and not samples:
        _empty(a)
    if xs:
        _legend(a, fontsize=6, loc="upper left")

    # 13 human_board applied ratio
    a = ax[12]
    ap = hist.series("hb_applied")
    at = hist.series("hb_attempt")
    ratio = [(x / y * 100.0) if y else None for x, y in zip(ap, at)]
    xs, ys = _xy(X, ratio)
    if xs:
        a.plot(xs, ys, lw=0.9, color="tab:green")
    _finish(a, "13) human board 注入成功率", ylabel="%")
    if not xs:
        _empty(a)

    # 14 batch_fill + batch_p50
    a = ax[13]
    xs, ys = _xy(X, hist.series("batch_fill"))
    if xs:
        a.plot(xs, ys, lw=0.8, color="tab:blue", label="batch_fill")
    xs2, ys2 = _xy(X, hist.series("batch_p50"))
    if xs2:
        b = a.twinx()
        b.plot(xs2, ys2, lw=0.8, color="tab:orange", alpha=0.7, label="batch_p50")
        b.set_ylabel("batch_p50", fontsize=8)
        b.tick_params(labelsize=7)
        _legend(b, fontsize=6, loc="upper right")
    _finish(a, "14) batch_fill / batch_p50", ylabel="fill")
    if not xs:
        _empty(a)
    _legend(a, fontsize=6, loc="upper left")

    # 15 cuda_peak + GPU used
    a = ax[14]
    xs, ys = _xy(X, hist.series("cuda_peak"))
    if xs:
        a.plot(xs, ys, lw=0.9, color="tab:purple", label="learner cuda_peak MB")
    if samples:
        sx = [s.get("cum_decisions", 0) / 1e6 for s in samples]
        used = []
        for s in samples:
            u = s.get("train_gpus_used_mib")
            if u is None:
                u = s.get("gpu_used_mib_total") or 0
            used.append((u or 0) / 1024.0)
        b = a.twinx()
        b.plot(sx, used, lw=0.8, color="tab:blue", alpha=0.55, label="训练卡已用 GB")
        b.set_ylabel("GB", fontsize=8)
        b.tick_params(labelsize=7)
        _legend(b, fontsize=6, loc="lower right")
    _finish(a, "15) 学习器显存峰值 / 训练卡占用", ylabel="MB")
    if not xs:
        _empty(a)
    _legend(a, fontsize=6, loc="upper left")

    # 16 状态文本
    a = ax[15]
    a.axis("off")
    lines = [
        f"run: {run}",
        f"状态: {status.get('state', '?')}",
        f"iter: {hist.iter}  累计: {hist.cum / 1e6:.2f} M / {args.until_decisions / 1e6:.0f} M",
        f"最后 dec/s: {hist.series('dps')[-1] if hist.series('dps') else '—'}",
        f"canonical 点: {len(canon)}/{len(point_targets(args.until_decisions, args.point_every))}",
        f"dev eval: {len(dev)} 次",
        f"draw: {_now()}",
        "",
        "最近告警:",
    ]
    for ln in alerts.recent(8):
        lines.append("  " + ln[:120])
    a.text(0.01, 0.98, "\n".join(lines), va="top", ha="left", fontsize=8,
           transform=a.transAxes)

    fig.suptitle(f"{run} — 300M 训练守护（{len(hist.rows)} iter, {hist.cum / 1e6:.1f}M decisions）",
                 fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    os.makedirs(os.path.dirname(os.path.abspath(paths["png"])) or ".", exist_ok=True)
    fig.savefig(paths["png"], dpi=110)
    plt.close(fig)
    return paths["png"]


def point_targets(until: int, every: int):
    if every <= 0:
        return []
    return [k * every for k in range(1, int(until // every) + 1)]


# ---------------------------------------------------------------- dashboard.md


def write_dashboard(run, paths, hist, dev, points, alerts, args, status):
    os.makedirs(os.path.dirname(os.path.abspath(paths["dash"])) or ".", exist_ok=True)
    targets = point_targets(args.until_decisions, args.point_every)
    crossed = [p for p in targets if p <= hist.cum]
    ok = [e for e in points.entries if e.get("status") == "ok"]
    skipped = [e for e in points.entries if e.get("status") == "skipped"]
    failed = [e for e in points.entries if e.get("status") == "failed"]
    lines = [
        f"# {run} 训练守护仪表盘",
        "",
        f"- 生成时间：{_now()}",
        f"- 状态：{status.get('state', '?')}"
        + (f"（PID {status.get('pids')}）" if status.get("pids") else ""),
        f"- iter：{hist.iter}；本 run 累计 decisions：{hist.cum:,}（{hist.cum / 1e6:.2f} M"
        f" / {args.until_decisions / 1e6:.0f} M）",
        f"- 计点：已跨过 {len(crossed)} 个 / 共 {len(targets)} 个；"
        f"canonical 成功 {len(ok)}、跳过 {len(skipped)}、失败 {len(failed)}",
        f"- 训练内 dev eval：{len(dev)} 次（seed 420000）",
        "",
        "## canonical 点表（96 局 / seed 520000 / 5 席 p0.9 / full）",
        "",
        "| 点(M) | ckpt | rank | top4 | strength | tier≥4 | tier≥5@t15 | survive12 | 秒 | GPU |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for e in ok[-16:]:
        lines.append("| {p} | {ck} | {r} | {t4} | {s} | {g4} | {g5} | {sv} | {sec} | {gpu} |".format(
            p=int((e.get("point_decisions") or 0) / 1e6),
            ck=os.path.basename(e.get("ckpt") or ""),
            r=_fmt(e.get("rank"), 3), t4=_fmt(e.get("top4"), 3),
            s=_fmt(e.get("strength"), 1), g4=_fmt(e.get("tier_ge4"), 3),
            g5=_fmt(e.get("tier_ge5_t15"), 3), sv=_fmt(e.get("survive12"), 3),
            sec=e.get("seconds"), gpu=e.get("gpu") or "-"))
    if not ok:
        lines.append("| — | 尚无 canonical 点 | | | | | | | | |")
    lines += [
        "",
        "## 加权点表（对局长度 + 终局强度；alpha=beta=0.5）",
        "",
        "| 点(M) | w_rank | w_top4 | w_strength | n_eff |",
        "|---|---|---|---|---|",
    ]
    any_w = False
    for e in ok[-16:]:
        if e.get("w_rank") is None:
            continue
        any_w = True
        lines.append(f"| {int((e.get('point_decisions') or 0) / 1e6)} | "
                     f"{_fmt(e.get('w_rank'), 3)} | {_fmt(e.get('w_top4'), 3)} | "
                     f"{_fmt(e.get('w_strength'), 1)} | {_fmt(e.get('w_n_eff'), 1)} |")
    if not any_w:
        lines.append("| — | 尚无加权点（从下一个 canonical 点开始） | | | |")
    lines += [
        "",
        "## dev 面板（训练内，seed 420000）",
        "",
        "| decisions(M) | rank | top4 | win | 秒 | rc |",
        "|---|---|---|---|---|---|",
    ]
    for e in dev[-10:]:
        lines.append(f"| {e['decisions'] / 1e6:.2f} | {_fmt(e.get('rank'), 3)} | "
                     f"{_fmt(e.get('top4'), 3)} | {_fmt(e.get('win'), 3)} | "
                     f"{_fmt(e.get('seconds'), 1)} | {e.get('rc')} |")
    if not dev:
        lines.append("| — | 尚无 dev eval | | | | |")
    lines += ["", "## 异常摘要（alerts.log 最近 12 条）", "", "```"]
    rec = alerts.recent(12)
    lines += rec if rec else ["（无告警）"]
    lines += ["```", "", "## 产物", "",
              f"- 曲线：{paths['png']}",
              f"- 点表：{paths['points']}",
              f"- 系统指标：{paths['system']}",
              f"- 告警：{paths['alerts']}", ""]
    with open(paths["dash"], "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return paths["dash"]


def _fmt(v, nd=3):
    if v is None:
        return "—"
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


# ---------------------------------------------------------------- 计点执行


def _wait_ckpt(run: str, point: int, args):
    deadline = time.time() + max(0, args.ckpt_wait)
    while True:
        ck = pick_ckpt(run, point)
        if ck is not None:
            return ck
        if time.time() >= deadline:
            return None
        time.sleep(min(max(args.poll, 3), 15))


def _wait_gpu(args, run: str, hist: History):
    deadline = time.time() + max(0, args.gpu_wait)
    while True:
        trainers = find_trainers(run)
        gpu, reason = pick_eval_gpu(args, trainers, hist.last)
        if gpu:
            return gpu, reason
        if time.time() >= deadline:
            return None, reason
        time.sleep(min(max(args.poll, 5), 30))


def process_points(run: str, hist: History, points: Points, alerts: Alerts, args) -> int:
    """为所有已跨过且未记录的点打 canonical 面板；返回新增点记录数。"""
    added = 0
    for point in point_targets(args.until_decisions, args.point_every):
        if point > hist.cum:
            break
        if points.done(point):
            continue
        ck = _wait_ckpt(run, point, args)
        if ck is None:
            points.add({
                "point_decisions": int(point),
                "status": "skipped",
                "reason": f"eval/ 下没有 decisions>={point} 的 ckpt（等待 {args.ckpt_wait}s）",
                "ckpt": None, "ckpt_decisions": None, "tag": None, "gpu": None,
                "games": 0, "rank": None, "top4": None, "win": None,
                "strength": None, "tier_ge4": None, "tier_ge5_t15": None,
                "survive12": None, "seconds": 0.0,
            })
            alerts.log("WARN", f"point_ckpt_missing_{int(point / 1e6)}M",
                       f"点 {point} 的 ckpt 缺失，已记 skipped")
            print(f"[{_now()}] point {int(point / 1e6)}M SKIP（ckpt 缺失）", flush=True)
            added += 1
            continue
        ckpt_dec, ckpt = ck
        gpu, reason = _wait_gpu(args, run, hist)
        if gpu is None:
            points.add({
                "point_decisions": int(point),
                "ckpt_decisions": int(ckpt_dec), "ckpt": ckpt,
                "status": "skipped", "tag": None, "gpu": None, "games": 0,
                "rank": None, "top4": None, "win": None, "strength": None,
                "tier_ge4": None, "tier_ge5_t15": None, "survive12": None,
                "seconds": 0.0, "reason": f"评测 GPU 不可用：{reason}",
            })
            alerts.log("WARN", f"point_gpu_unavailable_{int(point / 1e6)}M", reason)
            print(f"[{_now()}] point {int(point / 1e6)}M SKIP（{reason}）", flush=True)
            added += 1
            continue
        entry = canonical_eval(run, point, ckpt_dec, ckpt, gpu, args)
        points.add(entry)
        added += 1
        if entry.get("status") == "ok":
            print(f"[{_now()}] point {int(point / 1e6)}M OK rank={entry.get('rank')} "
                  f"top4={entry.get('top4')} strength={entry.get('strength')} "
                  f"gpu={gpu} sec={entry.get('seconds')}", flush=True)
        else:
            alerts.log("ERROR", f"point_eval_failed_{int(point / 1e6)}M",
                       f"点 {point} 评测失败 rc={entry.get('rc')}：{entry.get('reason')}")
            print(f"[{_now()}] point {int(point / 1e6)}M FAILED rc={entry.get('rc')}",
                  flush=True)
    return added


# ---------------------------------------------------------------- 告警巡检


def check_alerts(run: str, hist: History, dev, alerts: Alerts, state: dict, args):
    new = hist.take_new()
    for vals in new:
        if vals["illegal"] > 0:
            alerts.log("ERROR", "illegal_actions",
                       f"iter~{hist.iter} illegal_actions={int(vals['illegal'])}")
        if vals["restarts"] > 0:
            alerts.log("ERROR", "restarts",
                       f"iter~{hist.iter} restarts={int(vals['restarts'])}")
        for k in ("pl", "vl", "ent", "kl"):
            v = vals.get(k)
            if v is None:
                continue
            if not math.isfinite(v):
                alerts.log("ERROR", "nan_loss", f"iter~{hist.iter} {k}={v}")
    if new:
        cur = max(v["trunc"] for v in new)
        prev = hist.series("trunc")[:-len(new)] or []
        med = st.median(prev[-20:]) if prev else 0.0
        if cur > max(5.0, 3.0 * med + 2.0):
            alerts.log("WARN", "truncated_spike",
                       f"truncated 突增：本批 max={cur:.0f}，近 20 iter 中位 {med:.1f}")
    dps = [d for d in hist.series("dps") if d is not None]
    if len(dps) >= 3 and all(d < DPS_MIN for d in dps[-3:]):
        alerts.log("WARN", "low_dps", f"dec/s 连续 3 次 <{DPS_MIN:.0f}：{dps[-3:]}")
    else:
        alerts.resolve("low_dps")

    trainers = find_trainers(run)
    if trainers:
        state["trainer_seen"] = True
        if state.get("trainer_exit_alerted"):
            alerts.resolve("trainer_exited")
            state["trainer_exit_alerted"] = False
    elif state.get("trainer_seen") and not state.get("trainer_exit_alerted"):
        alerts.log("ERROR", "trainer_exited",
                   f"训练进程消失：最后 iter={hist.iter}，本 run 累计 {hist.cum / 1e6:.2f}M")
        state["trainer_exit_alerted"] = True

    summary_path = os.path.join(run, "summary.json")
    if os.path.isfile(summary_path) and not state.get("summary_seen"):
        state["summary_seen"] = True
        alerts.log("INFO", "summary_json",
                   f"summary.json 出现（{summary_path}）；训练内每个评测点也可能写出该文件")
    return trainers


def render(run, paths, hist, dev, points, samples, alerts, args, status):
    png = draw(run, paths, hist, dev, points, samples, alerts, args, status)
    dash = write_dashboard(run, paths, hist, dev, points, alerts, args, status)
    print(f"[{_now()}] draw iters={len(hist.rows)} cum={hist.cum / 1e6:.2f}M "
          f"dev={len(dev)} points={len(points.entries)} -> {png} | {dash}", flush=True)
    return png, dash


# ---------------------------------------------------------------- main


def build_args(argv=None):
    ap = argparse.ArgumentParser(
        description="300M 训练守护器：10M 计点 + 系统监控 + 告警 + 曲线")
    ap.add_argument("--run", required=True, help="run 目录，如 runs/az_stage300")
    ap.add_argument("--until-decisions", type=int, default=300_000_000,
                    help="本 run 累计 decisions 上限（默认 300M）")
    ap.add_argument("--point-every", type=int, default=10_000_000,
                    help="计点间隔（默认 10M）")
    ap.add_argument("--eval-gpu", default="auto", help="auto 或 cuda:N")
    ap.add_argument("--eval-games", type=int, default=96)
    ap.add_argument("--eval-seed", type=int, default=DEFAULT_SEED,
                    help="canonical 面板 seed（默认 520000）")
    ap.add_argument("--eval-timeout", type=int, default=2400, help="单次评测超时秒")
    ap.add_argument("--min-free-mib", type=int, default=2500,
                    help="评测卡最低空闲显存（默认 2500 MiB）")
    ap.add_argument("--allow-low-free", action="store_true",
                    help="显式 --eval-gpu 时也允许低于 min-free-mib")
    ap.add_argument("--gpu-priority", default="1,7,5,4,3,0,2,6",
                    help="auto 选卡优先级（默认 1,7,5,4,3,0,2,6）")
    ap.add_argument("--poll", type=int, default=30, help="主循环轮询秒")
    ap.add_argument("--system-every", type=int, default=60, help="系统采样间隔秒")
    ap.add_argument("--redraw-every", type=int, default=300, help="重绘间隔秒")
    ap.add_argument("--dev-offset", type=int, default=0,
                    help="断点续训后 dev eval 的全局 offset（0=不改）")
    ap.add_argument("--dev-offset-from-index", type=int, default=0,
                    help="从第几条 eval 记录开始加 offset（无 resume_epoch 时的回退）")
    ap.add_argument("--dev-resume-epoch", type=float, default=0.0,
                    help="续训开始时刻的 epoch；eval ckpt mtime>=它则视为续训后条目")
    ap.add_argument("--ckpt-wait", type=int, default=300, help="等 ckpt 最长秒数")
    ap.add_argument("--gpu-wait", type=int, default=600, help="等空闲评测卡最长秒数")
    ap.add_argument("--once", action="store_true", help="只跑一轮后退出")
    ap.add_argument("--no-eval", action="store_true", help="只监控出图，不跑 canonical 评测")
    ap.add_argument("--keep-alive", action="store_true",
                    help="训练结束且计点补齐后仍常驻")
    ap.add_argument("--out-prefix", default="",
                    help="产物前缀 P（写 P.points.jsonl / P.system.jsonl / P.alerts.log / "
                         "P.curves.png / P.dashboard.md）；默认写 run 目录")
    ap.add_argument("--points-file", default="", help="覆盖 points.jsonl 路径")
    ap.add_argument("--baseline-rank", type=float, default=6.083,
                    help="canonical rank 参考线（s61 96 局面板 6.083）")
    ap.add_argument("--baseline-strength", type=float, default=323.5,
                    help="strength 参考线（s61 96 局面板 323.5）")
    return ap.parse_args(argv)


def _status_text(hist, trainers, state, args, points):
    if trainers:
        st_text = "运行中"
    elif state.get("finished"):
        st_text = "已结束（计点已补齐）"
    elif state.get("trainer_seen"):
        st_text = "已停止（进程消失，守护器继续等待重启）"
    else:
        st_text = "未运行（仅离线出图）"
    return {"state": st_text, "pids": [t["pid"] for t in trainers],
            "workers": len(trainers)}


def main(argv=None) -> int:
    args = build_args(argv)
    run = os.path.normpath(args.run)
    if not os.path.isdir(run):
        print(f"[error] run 目录不存在: {run}", file=sys.stderr)
        return 2
    paths = _paths(run, args.out_prefix)
    if args.points_file:
        paths["points"] = args.points_file
    for key in ("points", "system", "alerts", "png", "dash"):
        os.makedirs(os.path.dirname(os.path.abspath(paths[key])) or ".", exist_ok=True)

    hist = History(os.path.join(run, "history.jsonl")).load_all()
    dev = load_dev_evals(run, args.dev_offset, args.dev_offset_from_index,
                     args.dev_resume_epoch)
    points = Points(paths["points"])
    alerts = Alerts(paths["alerts"])
    sampler = SystemSampler()
    samples = _load_jsonl(paths["system"])

    state = {"stop": False, "trainer_seen": False, "trainer_exit_alerted": False,
             "summary_seen": os.path.isfile(os.path.join(run, "summary.json")),
             "finished": False}

    def _sig(_signum, _frame):
        state["stop"] = True

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    print(f"[{_now()}] stage_monitor start run={run} until={args.until_decisions} "
          f"every={args.point_every} eval={'off' if args.no_eval else args.eval_gpu} "
          f"once={int(args.once)} out={paths['dir']}", flush=True)

    last_draw = 0.0
    last_sys = 0.0
    while True:
        hist.poll()
        # dev 面板是训练内异步评测写 eval/history.json；必须每轮重读，
        # 否则启动时还没有 eval 就会永远显示 0 次（2026-11-04 修复）。
        dev = load_dev_evals(run, args.dev_offset, args.dev_offset_from_index,
                     args.dev_resume_epoch)
        trainers = check_alerts(run, hist, dev, alerts, state, args)
        if not args.no_eval:
            process_points(run, hist, points, alerts, args)

        now = time.time()
        if now - last_sys >= args.system_every or last_sys == 0:
            row = sampler.sample(run, hist.cum)
            _append_jsonl(paths["system"], row)
            samples.append(row)
            last_sys = now

        targets = point_targets(args.until_decisions, args.point_every)
        crossed = [p for p in targets if p <= hist.cum]
        pending = [] if args.no_eval else [p for p in crossed if not points.done(p)]
        finished = (hist.cum >= args.until_decisions and not trainers and not pending)
        if finished:
            state["finished"] = True
        status = _status_text(hist, trainers, state, args, points)

        if (not last_draw) or finished or state["stop"] or (now - last_draw) >= args.redraw_every:
            render(run, paths, hist, dev, points, samples, alerts, args, status)
            last_draw = now

        if args.once or finished or state["stop"]:
            break
        time.sleep(max(1, args.poll))

    status = _status_text(hist, find_trainers(run), state, args, points)
    print(f"[{_now()}] stage_monitor stop state={status['state']} cum={hist.cum / 1e6:.2f}M "
          f"points={len(points.entries)} png={paths['png']} dash={paths['dash']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
