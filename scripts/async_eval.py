#!/usr/bin/env python3
"""异步 C0 评测执行器：训练主循环提交 checkpoint，子进程跑 ``scripts/c0_gate.py``，不等待。

设计约束（见 ``docs/TRAINING_THROUGHPUT_NOTES.md``）：

- **并发上限 1**：同一时刻最多一个评测子进程；到点但上一个还没完成 -> 跳过，并往
  ``eval/history.json`` 追加一条 ``eval_skipped`` 记录（不阻塞训练）；
- **独立子进程**：评测不占 learner 进程（建议 ``--eval-device cuda:4``），主循环零等待；
- **轻量线程**：monitor 线程只做 ``proc.wait()`` + 读结果 JSON + 追加 history + 回调
  （镜像库 TRIGGER / 可选早停），**不碰 torch/CUDA**；
- **失败不崩溃**：非 0 退出或缺 JSON -> 打印 stderr 尾部，错误写进 history 的 ``error``，
  训练继续；
- **schema 兼容**：``history.json`` 仍是 ``{"evals": [rec, ...]}``，完成记录的字段与同步
  路径完全一致（``decisions/rc/seconds/mean_rank/bot_mean_rank/top4/win/...``）；跳过记录
  额外带 ``skipped/eval_skipped/reason``，没有 ``mean_rank``（绘图脚本会自动忽略）。

注意：``scripts/c0_gate.py --smoke`` 的退出码恒为 1（smoke 不产生 ``passed``），这是
**预期行为**；只要 JSON 里能解析出 ``panels[0]`` 就算成功，不记为失败。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional


def _default_log(msg: str) -> None:
    print(msg, flush=True)


def tail_lines(path: str, n: int = 20, max_bytes: int = 1 << 16) -> List[str]:
    """读文件末尾 n 行（最多读 max_bytes，避免把 11 分钟的大日志全读进内存）。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    try:
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            data = f.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    return [ln for ln in lines[-n:] if ln.strip()]


def write_json_atomic(path: str, obj: Any) -> None:
    """原子写 JSON（tmp + os.replace），避免训练被杀时留下半截文件。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_eval_history(path: str) -> List[Dict[str, Any]]:
    """读 ``{"evals": [...]}``；文件不存在/损坏返回 []（损坏文件先备份）。"""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        evals = data.get("evals") if isinstance(data, dict) else None
        return list(evals or [])
    except Exception:  # noqa: BLE001
        try:
            os.replace(path, f"{path}.corrupt.{int(time.time())}")
        except OSError:
            pass
        return []


def parse_c0_result(decisions: int, rc: int, seconds: float,
                    out_json: str) -> Dict[str, Any]:
    """把 c0_gate 的结果 JSON 转成 history 记录（与同步路径逐字段一致）。"""
    rec: Dict[str, Any] = {"decisions": int(decisions), "rc": int(rc),
                           "seconds": round(float(seconds), 1)}
    try:
        with open(out_json, encoding="utf-8") as f:
            data = json.load(f)
        panels = data.get("panels") or []
        if not panels:
            rec["error"] = str(data.get("error") or f"c0_gate 未产出 panels (rc={rc})")
            return rec
        p = panels[0]
        rec.update({
            "mean_rank": float(p["model_mean_rank"]),
            "bot_mean_rank": float(p["bot_mean_rank"]),
            "top4": float(p["model_top4"]), "win": float(p["model_win"]),
            "mean_diff": float(p["mean_diff"]),
            "ci_low": float(p["ci_low"]), "ci_high": float(p["ci_high"]),
            "illegal": int(p["illegal"]), "truncated": int(p["truncated"]),
            "passed": bool(data.get("passed")),
        })
        if data.get("error"):
            rec["error"] = str(data["error"])
    except Exception as exc:  # noqa: BLE001
        rec["error"] = repr(exc)
    return rec


def build_c0_cmd(python: str, root: str, ckpt: str, *, arch: str, device: str,
                 games: int, seats: int, seed_base: int, out_json: str,
                 gate_script: str = "") -> List[str]:
    """与 ``train_entity_sync._run_eval`` 完全一致的 c0_gate 命令行。"""
    script = str(gate_script) if gate_script else os.path.join(str(root), "scripts",
                                                               "c0_gate.py")
    return [str(python), script,
            "--checkpoint", str(ckpt), "--arch", str(arch),
            "--device", str(device),
            "--games", str(int(games)), "--seats", str(int(seats)),
            "--seed-base", str(int(seed_base)), "--smoke",
            "--bootstrap", "1000", "--out", str(out_json)]


class AsyncEvalRunner:
    """并发上限 1 的异步 C0 评测执行器。

    用法::

        runner = AsyncEvalRunner(out_dir=args.out, root=ROOT, arch=arch,
                                 device="cuda:4", on_result=_post_eval)
        runner.submit(decisions, ckpt_path)   # 不等待
        ...
        runner.close(drain=False)             # 收尾：终止在跑的子进程
    """

    def __init__(self, *, out_dir: str, root: str, arch: str = "entity",
                 device: str = "cuda:4", games: int = 512, seats: int = 8,
                 seed_base: int = 420000, gate_script: str = "",
                 python: str = "", on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self.out_dir = os.path.abspath(out_dir)
        self.eval_dir = os.path.join(self.out_dir, "eval")
        self.history_path = os.path.join(self.eval_dir, "history.json")
        self.root = os.path.abspath(root)
        self.arch = str(arch)
        self.device = str(device)
        self.games = int(games)
        self.seats = int(seats)
        self.seed_base = int(seed_base)
        self.gate_script = os.path.abspath(
            gate_script or os.path.join(self.root, "scripts", "c0_gate.py"))
        self.python = str(python or sys.executable)
        self.on_result = on_result
        self.log = log or _default_log

        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stopping = False
        self._history: Optional[List[Dict[str, Any]]] = None

        self.submitted = 0
        self.completed = 0
        self.failed = 0
        #: 本次 run 完成的评测记录（不含 skipped），用于 summary
        self.results: List[Dict[str, Any]] = []
        #: 因并发上限跳过的记录
        self.skipped: List[Dict[str, Any]] = []
        self.stop_requested = False
        self.stop_reason = ""

    # -- 状态 ---------------------------------------------------------------
    def running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {"enabled": True, "device": self.device, "games": self.games,
                    "seats": self.seats, "submitted": self.submitted,
                    "completed": self.completed, "failed": self.failed,
                    "skipped": len(self.skipped), "running": self.running(),
                    "stop_requested": bool(self.stop_requested),
                    "history": self.history_path}

    def results_snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.results)

    # -- history ------------------------------------------------------------
    def _load_history(self) -> List[Dict[str, Any]]:
        if self._history is None:
            self._history = read_eval_history(self.history_path)
        return self._history

    def _append_history(self, rec: Dict[str, Any]) -> None:
        """追加一条记录并原子落盘（调用方需持有 self._lock）。

        按 decisions 排序：跳过记录可能比在跑的评测先完成，排序后 history 仍按时间轴排列
        （绘图脚本按顺序读；同 decisions 时完成记录在前）。
        """
        hist = self._load_history()
        hist.append(rec)
        hist.sort(key=lambda r: (int(r.get("decisions") or 0),
                                 bool(r.get("skipped"))))
        write_json_atomic(self.history_path, {"evals": hist})

    # -- 提交 ---------------------------------------------------------------
    def submit(self, decisions: int, ckpt_path: str) -> bool:
        """提交一次评测；已在跑则跳过并记 ``eval_skipped``，返回是否真正启动。"""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                rec = {"decisions": int(decisions), "rc": None, "seconds": 0.0,
                       "skipped": True, "eval_skipped": True,
                       "reason": "eval_in_flight"}
                self.skipped.append(rec)
                self._append_history(rec)
                self.log(f"[eval-async] skipped dec={int(decisions)}：上一个评测仍在运行"
                         f"（eval_skipped={len(self.skipped)}）")
                return False
            os.makedirs(self.eval_dir, exist_ok=True)
            tag = f"{int(decisions):09d}"
            out_json = os.path.join(self.eval_dir, f"c0_{tag}.json")
            log_path = os.path.join(self.eval_dir, f"c0_{tag}.log")
            err_path = os.path.join(self.eval_dir, f"c0_{tag}.err.log")
            # c0_gate 自己也会删旧 out；这里再删一次，避免"读到上一轮残留"
            try:
                os.unlink(out_json)
            except OSError:
                pass
            cmd = build_c0_cmd(
                self.python, self.root, ckpt_path, arch=self.arch, device=self.device,
                games=self.games, seats=self.seats, seed_base=self.seed_base,
                out_json=out_json, gate_script=self.gate_script)
            t0 = time.time()
            logf = errf = None
            try:
                logf = open(log_path, "w", encoding="utf-8")
                errf = open(err_path, "w", encoding="utf-8")
                proc = subprocess.Popen(cmd, cwd=self.root, stdout=logf, stderr=errf)
            except Exception as exc:  # noqa: BLE001
                for fh in (logf, errf):
                    try:
                        fh.close()
                    except Exception:  # noqa: BLE001
                        pass
                rec = {"decisions": int(decisions), "rc": -1, "seconds": 0.0,
                       "error": f"spawn failed: {exc!r}"}
                self.completed += 1
                self.failed += 1
                self.results.append(rec)
                self._append_history(rec)
                self.log(f"[eval-async] FAILED dec={int(decisions)} spawn: {exc!r}")
                return False
            self._proc = proc
            self.submitted += 1
            self._thread = threading.Thread(
                target=self._monitor, args=(proc, int(decisions), out_json, log_path,
                                            err_path, t0, logf, errf),
                name=f"eval-async-{tag}", daemon=True)
            self._thread.start()
            self.log(f"[eval-async] queued dec={int(decisions)} device={self.device} "
                     f"games={self.games} pid={proc.pid}")
            return True

    # -- monitor（子进程结束后在轻量线程里跑；不碰 torch/CUDA）----------------
    def _monitor(self, proc: subprocess.Popen, decisions: int, out_json: str,
                 log_path: str, err_path: str, t0: float,
                 logf: Any, errf: Any) -> None:
        try:
            rc = int(proc.wait())
        finally:
            for fh in (logf, errf):
                try:
                    fh.close()
                except Exception:  # noqa: BLE001
                    pass
        seconds = time.time() - t0
        rec = parse_c0_result(decisions, rc, seconds, out_json)
        failed = rec.get("mean_rank") is None or bool(rec.get("error"))
        with self._lock:
            # 只清自己：极端情况下"子进程已退出但 monitor 尚未回收"时主线程可能已提交
            # 下一个评测（新 _proc），不能把新进程的引用清掉（否则并发上限 1 失效）。
            if self._proc is proc:
                self._proc = None
            if self._stopping:
                # 训练收尾时主动终止：不入 history（避免污染评测曲线）
                self.log(f"[eval-async] aborted dec={int(decisions)} (trainer shutdown)")
                return
            self.completed += 1
            if failed:
                self.failed += 1
            self.results.append(rec)
            self._append_history(rec)
        if failed:
            tail = tail_lines(err_path) or tail_lines(log_path)
            self.log(f"[eval-async] FAILED dec={int(decisions)} rc={rc} "
                     f"error={rec.get('error')} ({seconds:.1f}s) log={log_path}")
            for line in tail:
                self.log(f"    {line}")
        else:
            self.log(f"[eval-async] dec={int(decisions)} "
                     f"mean_rank={rec['mean_rank']:.4f} top4={rec['top4']:.4f} "
                     f"win={rec['win']:.4f} ({seconds:.1f}s)")
        if self.on_result is not None:
            try:
                self.on_result(rec)
            except Exception as exc:  # noqa: BLE001
                self.log(f"[eval-async] on_result error: {exc!r}")

    # -- 收尾 ---------------------------------------------------------------
    def close(self, drain: bool = False) -> None:
        """收尾。``drain=1`` 等待在跑的评测完成；否则终止（不阻塞退出）。"""
        with self._lock:
            proc = self._proc
            th = self._thread
        if proc is not None and proc.poll() is None:
            if drain:
                self.log("[eval-async] drain=1：等待在跑的评测完成 ...")
            else:
                with self._lock:
                    self._stopping = True
                self.log("[eval-async] trainer 退出：终止在跑的评测"
                         "（--eval-drain 1 可等待）")
                try:
                    proc.terminate()
                except OSError:
                    pass
        if th is not None:
            th.join(timeout=None if drain else 10.0)
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass


__all__ = ["AsyncEvalRunner", "build_c0_cmd", "parse_c0_result",
           "read_eval_history", "tail_lines", "write_json_atomic"]
