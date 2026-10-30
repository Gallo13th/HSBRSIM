#!/usr/bin/env python3
"""异步评测执行器：训练主循环提交 checkpoint，子进程跑评测，不等待。

设计约束（见 ``docs/TRAINING_THROUGHPUT_NOTES.md`` / ``docs/EVAL_PANELS.md``）：

- **并发上限 1**：同一时刻最多一个评测子进程；到点但上一个还没完成 -> 跳过，并往
  ``eval/history.json`` 追加一条 ``eval_skipped`` 记录（不阻塞训练）；
- **多面板排队**：``panels=("bot","human")`` 时每个 panel 各起一个子进程（``c0_gate.py`` /
  ``human_panel_eval.py``），**串行排队**执行（并发上限仍为 1）；结果用 ``panel`` 字段区分；
- **独立子进程**：评测不占 learner 进程（建议 ``--eval-device cuda:4``），主循环零等待；
- **轻量线程**：monitor 线程只做 ``proc.wait()`` + 读结果 JSON + 追加 history + 回调
  （镜像库 TRIGGER / 可选早停），**不碰 torch/CUDA**；
- **失败不崩溃**：非 0 退出或缺 JSON -> 打印 stderr 尾部，错误写进 history 的 ``error``，
  训练继续；
- **schema 兼容**：``history.json`` 仍是 ``{"evals": [rec, ...]}``；bot 面板记录保留旧字段
  （``mean_rank/bot_mean_rank/top4/win/...``），human 面板记录额外带 ``human_mean_rank`` /
  ``human_top4`` / ``human_win``，两者都有 ``panel`` 字段；跳过记录额外带
  ``skipped/eval_skipped/reason``，没有评测指标（绘图脚本会自动忽略）。

注意：``scripts/c0_gate.py --smoke`` / ``scripts/human_panel_eval.py --smoke`` 的退出码恒为
1（smoke 不产生 ``passed``），这是**预期行为**；只要 JSON 里能解析出 ``panels[0]`` 就算成功，
不记为失败。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence


def _default_log(msg: str) -> None:
    print(msg, flush=True)


#: 合法 panel 名；``both`` 展开为 bot -> human（串行排队）。
PANEL_NAMES = ("bot", "human")


def panels_from_spec(spec: Any) -> List[str]:
    """``bot|human|both`` -> 实际要跑的 panel 列表（顺序固定，便于 history 排序）。"""
    s = str(spec or "both").strip().lower()
    if s == "both":
        return ["bot", "human"]
    if s in PANEL_NAMES:
        return [s]
    return ["bot"]


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


def _panel_rec_common(rec: Dict[str, Any], p: Dict[str, Any],
                      data: Dict[str, Any], panel: str) -> None:
    """把 c0_gate / human_panel_eval 的 panels[0] 转成 history 公共字段。"""
    rec["panel"] = str(panel)
    rec["illegal"] = int(p.get("illegal") or 0)
    rec["truncated"] = int(p.get("truncated") or 0)
    rec["passed"] = bool(data.get("passed"))
    if panel == "human":
        # 主指标：human_mean_rank；同时保留 mean_rank=None（避免绘图脚本误当 bot 面板）。
        rec["human_mean_rank"] = (None if p.get("model_mean_rank") is None
                                  else float(p["model_mean_rank"]))
        rec["mean_rank"] = None
        rec["human_top4"] = (None if p.get("model_top4") is None
                             else float(p["model_top4"]))
        rec["human_win"] = (None if p.get("model_win") is None
                            else float(p["model_win"]))
        rec["human_bot_mean_rank"] = (None if p.get("bot_mean_rank") is None
                                      else float(p["bot_mean_rank"]))
        rec["human_top4_bot"] = (None if p.get("bot_top4") is None
                                 else float(p["bot_top4"]))
        rec["human_mean_diff"] = (None if p.get("mean_diff") is None
                                  else float(p["mean_diff"]))
        rec["human_ci_low"] = (None if p.get("ci_low") is None
                               else float(p["ci_low"]))
        rec["human_ci_high"] = (None if p.get("ci_high") is None
                                else float(p["ci_high"]))
        rec["quantile"] = str(data.get("quantile") or p.get("quantile") or "")
        rec["injection"] = (p.get("injection")
                            or (p.get("details") or {}).get("injection"))
    else:
        rec["mean_rank"] = (None if p.get("model_mean_rank") is None
                            else float(p["model_mean_rank"]))
        rec["bot_mean_rank"] = (None if p.get("bot_mean_rank") is None
                                else float(p["bot_mean_rank"]))
        rec["top4"] = (None if p.get("model_top4") is None else float(p["model_top4"]))
        rec["win"] = (None if p.get("model_win") is None else float(p["model_win"]))
        rec["mean_diff"] = (None if p.get("mean_diff") is None
                            else float(p["mean_diff"]))
        rec["ci_low"] = (None if p.get("ci_low") is None else float(p["ci_low"]))
        rec["ci_high"] = (None if p.get("ci_high") is None else float(p["ci_high"]))


def parse_panel_result(decisions: int, rc: int, seconds: float,
                       out_json: str, panel: str = "bot") -> Dict[str, Any]:
    """把一次评测的结果 JSON 转成 history 记录（带 ``panel`` 字段）。"""
    rec: Dict[str, Any] = {"decisions": int(decisions), "rc": int(rc),
                           "seconds": round(float(seconds), 1),
                           "panel": str(panel)}
    try:
        with open(out_json, encoding="utf-8") as f:
            data = json.load(f)
        panels = data.get("panels") or []
        if not panels:
            rec["error"] = str(data.get("error") or f"评测未产出 panels (rc={rc})")
            return rec
        _panel_rec_common(rec, panels[0], data, panel)
        if data.get("error"):
            rec["error"] = str(data["error"])
    except Exception as exc:  # noqa: BLE001
        rec["error"] = repr(exc)
    return rec


def parse_c0_result(decisions: int, rc: int, seconds: float,
                    out_json: str) -> Dict[str, Any]:
    """``parse_panel_result(panel="bot")`` 的兼容别名（旧调用点/旧测试）。"""
    return parse_panel_result(decisions, rc, seconds, out_json, panel="bot")


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


def build_human_cmd(python: str, root: str, ckpt: str, *, arch: str, device: str,
                    games: int, seats: int, seed_base: int, out_json: str,
                    quantile: str = "auto", human_boards: str = "",
                    baseline_bot: bool = False,
                    script: str = "") -> List[str]:
    """人类战团面板命令行（``scripts/human_panel_eval.py``）。"""
    path = str(script) if script else os.path.join(str(root), "scripts",
                                                   "human_panel_eval.py")
    cmd = [str(python), path,
           "--checkpoint", str(ckpt), "--arch", str(arch),
           "--device", str(device),
           "--games", str(int(games)), "--seats", str(int(seats)),
           "--seed-base", str(int(seed_base)), "--smoke",
           "--quantile", str(quantile),
           "--bootstrap", "1000",
           "--baseline-bot", ("1" if baseline_bot else "0"),
           "--out", str(out_json)]
    if str(human_boards):
        cmd += ["--human-boards", str(human_boards)]
    return cmd


class AsyncEvalRunner:
    """并发上限 1 的异步评测执行器（支持 bot/human 多面板串行排队）。

    用法::

        runner = AsyncEvalRunner(out_dir=args.out, root=ROOT, arch=arch,
                                 device="cuda:4", panels=("bot", "human"),
                                 human_quantile="auto", on_result=_post_eval)
        runner.submit(decisions, ckpt_path)   # 不等待（两个面板依次排队）
        ...
        runner.close(drain=False)             # 收尾：终止在跑的子进程
    """

    def __init__(self, *, out_dir: str, root: str, arch: str = "entity",
                 device: str = "cuda:4", games: int = 512, seats: int = 8,
                 seed_base: int = 420000, gate_script: str = "",
                 panels: Optional[Sequence[str]] = None,
                 human_quantile: str = "auto", human_boards: str = "",
                 baseline_bot: bool = False, human_script: str = "",
                 python: str = "",
                 on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
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
        self.human_script = os.path.abspath(
            human_script or os.path.join(self.root, "scripts", "human_panel_eval.py"))
        self.human_quantile = str(human_quantile or "auto")
        self.human_boards = str(human_boards or "")
        self.baseline_bot = bool(baseline_bot)
        self.panels = tuple(panels if panels is not None else ("bot",))
        self.python = str(python or sys.executable)
        self.on_result = on_result
        self.log = log or _default_log

        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stopping = False
        self._history: Optional[List[Dict[str, Any]]] = None
        #: 待跑的 panel job（每个 job 一个子进程；并发上限 1 = 队列串行）
        self._queue: List[Dict[str, Any]] = []

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
            if self._queue:
                return True
            return self._proc is not None and self._proc.poll() is None

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {"enabled": True, "device": self.device, "games": self.games,
                    "seats": self.seats, "panels": list(self.panels),
                    "human_quantile": self.human_quantile,
                    "submitted": self.submitted,
                    "completed": self.completed, "failed": self.failed,
                    "skipped": len(self.skipped), "running": self.running(),
                    "queued": len(self._queue),
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
        （绘图脚本按顺序读；同 decisions 时完成记录在前，panel 顺序 bot -> human）。
        """
        order = {"bot": 0, "human": 1}
        hist = self._load_history()
        hist.append(rec)
        hist.sort(key=lambda r: (int(r.get("decisions") or 0),
                                 bool(r.get("skipped")),
                                 order.get(str(r.get("panel")), 2)))
        write_json_atomic(self.history_path, {"evals": hist})

    # -- 提交 ---------------------------------------------------------------
    def _make_job(self, panel: str, decisions: int, ckpt_path: str) -> Dict[str, Any]:
        tag = f"{int(decisions):09d}"
        prefix = "c0" if panel == "bot" else "human"
        job: Dict[str, Any] = {
            "panel": str(panel), "decisions": int(decisions), "tag": tag,
            "out_json": os.path.join(self.eval_dir, f"{prefix}_{tag}.json"),
            "log_path": os.path.join(self.eval_dir, f"{prefix}_{tag}.log"),
            "err_path": os.path.join(self.eval_dir, f"{prefix}_{tag}.err.log"),
        }
        if panel == "bot":
            job["cmd"] = build_c0_cmd(
                self.python, self.root, ckpt_path, arch=self.arch, device=self.device,
                games=self.games, seats=self.seats, seed_base=self.seed_base,
                out_json=job["out_json"], gate_script=self.gate_script)
        else:
            job["cmd"] = build_human_cmd(
                self.python, self.root, ckpt_path, arch=self.arch, device=self.device,
                games=self.games, seats=self.seats, seed_base=self.seed_base,
                out_json=job["out_json"], quantile=self.human_quantile,
                human_boards=self.human_boards, baseline_bot=self.baseline_bot,
                script=self.human_script)
        # 评测脚本自己也会删旧 out；这里再删一次，避免"读到上一轮残留"
        try:
            os.unlink(job["out_json"])
        except OSError:
            pass
        return job

    def _advance_locked(self) -> bool:
        """启动队列里的下一个 panel（调用方需持有 self._lock）。返回是否启动了进程。"""
        if self._stopping:
            self._queue.clear()
            self._proc = None
            return False
        while self._queue:
            job = self._queue.pop(0)
            logf = errf = None
            try:
                logf = open(job["log_path"], "w", encoding="utf-8")
                errf = open(job["err_path"], "w", encoding="utf-8")
                proc = subprocess.Popen(job["cmd"], cwd=self.root,
                                        stdout=logf, stderr=errf)
            except Exception as exc:  # noqa: BLE001
                for fh in (logf, errf):
                    try:
                        fh.close()
                    except Exception:  # noqa: BLE001
                        pass
                rec = {"decisions": int(job["decisions"]), "rc": -1, "seconds": 0.0,
                       "panel": str(job["panel"]),
                       "error": f"spawn failed: {exc!r}"}
                self.completed += 1
                self.failed += 1
                self.results.append(rec)
                self._append_history(rec)
                self.log(f"[eval-async] FAILED dec={int(job['decisions'])} "
                         f"panel={job['panel']} spawn: {exc!r}")
                continue
            self._proc = proc
            self._thread = threading.Thread(
                target=self._monitor, args=(proc, job, time.time(), logf, errf),
                name=f"eval-async-{job['panel']}-{job['tag']}", daemon=True)
            self._thread.start()
            self.log(f"[eval-async] queued dec={int(job['decisions'])} "
                     f"panel={job['panel']} device={self.device} games={self.games} "
                     f"pid={proc.pid}")
            return True
        self._proc = None
        return False

    def submit(self, decisions: int, ckpt_path: str) -> bool:
        """提交一次评测（按 panel 展开为多个排队子进程）；已在跑则跳过。

        已有一个评测/队列在跑时返回 False，并记一条 ``eval_skipped``。
        """
        with self._lock:
            if self.running():
                rec = {"decisions": int(decisions), "rc": None, "seconds": 0.0,
                       "skipped": True, "eval_skipped": True,
                       "reason": "eval_in_flight"}
                self.skipped.append(rec)
                self._append_history(rec)
                self.log(f"[eval-async] skipped dec={int(decisions)}：上一个评测仍在运行"
                         f"（eval_skipped={len(self.skipped)}）")
                return False
            os.makedirs(self.eval_dir, exist_ok=True)
            self._queue = [self._make_job(p, decisions, ckpt_path)
                           for p in self.panels]
            self.submitted += 1
            return self._advance_locked()

    # -- monitor（子进程结束后在轻量线程里跑；不碰 torch/CUDA）----------------
    def _monitor(self, proc: subprocess.Popen, job: Dict[str, Any], t0: float,
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
        rec = parse_panel_result(int(job["decisions"]), rc, seconds,
                                 str(job["out_json"]), panel=str(job["panel"]))
        failed = bool(rec.get("error")) or (
            rec.get("mean_rank") is None and rec.get("human_mean_rank") is None)
        with self._lock:
            # 只清自己：极端情况下"子进程已退出但 monitor 尚未回收"时主线程可能已提交
            # 下一个评测（新 _proc），不能把新进程的引用清掉（否则并发上限 1 失效）。
            if self._proc is proc:
                self._proc = None
            if self._stopping:
                # 训练收尾时主动终止：不入 history（避免污染评测曲线）
                self.log(f"[eval-async] aborted dec={int(job['decisions'])} "
                         f"panel={job['panel']} (trainer shutdown)")
                return
            self.completed += 1
            if failed:
                self.failed += 1
            self.results.append(rec)
            self._append_history(rec)
            # 队列里还有 panel（bot -> human）：立刻串行启动下一个
            self._advance_locked()
        if failed:
            tail = tail_lines(job["err_path"]) or tail_lines(job["log_path"])
            self.log(f"[eval-async] FAILED dec={int(job['decisions'])} "
                     f"panel={job['panel']} rc={rc} error={rec.get('error')} "
                     f"({seconds:.1f}s) log={job['log_path']}")
            for line in tail:
                self.log(f"    {line}")
        elif str(job["panel"]) == "human":
            self.log(f"[eval-async] dec={int(job['decisions'])} panel=human "
                     f"human_mean_rank={rec['human_mean_rank']:.4f} "
                     f"top4={rec['human_top4']:.4f} win={rec['human_win']:.4f} "
                     f"({seconds:.1f}s)")
        else:
            self.log(f"[eval-async] dec={int(job['decisions'])} panel=bot "
                     f"mean_rank={rec['mean_rank']:.4f} top4={rec['top4']:.4f} "
                     f"win={rec['win']:.4f} ({seconds:.1f}s)")
        if self.on_result is not None:
            try:
                self.on_result(rec)
            except Exception as exc:  # noqa: BLE001
                self.log(f"[eval-async] on_result error: {exc!r}")

    # -- 收尾 ---------------------------------------------------------------
    def close(self, drain: bool = False) -> None:
        """收尾。``drain=1`` 等待**全部排队 panel** 完成；否则终止（不阻塞退出）。"""
        if drain:
            # 多面板场景：bot 跑完后 monitor 线程会串行启动 human；必须循环等待，
            # 只 join 当前线程会漏掉排队中的 panel（训练退出即被杀）。
            while True:
                with self._lock:
                    proc = self._proc
                    th = self._thread
                    queued = bool(self._queue)
                if proc is None and not queued:
                    break
                if proc is not None and (th is None or not th.is_alive()):
                    try:
                        proc.wait(timeout=120)
                    except Exception:  # noqa: BLE001 - 超时后继续轮询
                        pass
                elif th is not None:
                    th.join(timeout=120)
            with self._lock:
                th = self._thread
            if th is not None:
                th.join(timeout=5.0)
            self.log("[eval-async] drain=1：全部 panel 已完成")
            return
        with self._lock:
            proc = self._proc
            th = self._thread
            self._queue.clear()
        if proc is not None and proc.poll() is None:
            with self._lock:
                self._stopping = True
            self.log("[eval-async] trainer 退出：终止在跑的评测"
                     "（--eval-drain 1 可等待）")
            try:
                proc.terminate()
            except OSError:
                pass
        if th is not None:
            th.join(timeout=10.0)
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass


__all__ = ["AsyncEvalRunner", "PANEL_NAMES", "build_c0_cmd", "build_human_cmd",
           "panels_from_spec", "parse_c0_result", "parse_panel_result",
           "read_eval_history", "tail_lines", "write_json_atomic"]
