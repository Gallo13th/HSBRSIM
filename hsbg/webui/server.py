"""HSBRSIM 本地 Web 控制台（标准库，无第三方 Web 依赖）。

设计目标：给训练/评测/基准结果一个可点击的页面，而不是替代训练器。
- 状态：引擎版本、RL backend、checkpoint、runs 产物
- 评测：调用 `python -m hsbg.rl.evaluate`，展示名次分布/均值/吞吐
- runs：扫描 `runs/` 下 JSON 结果
- TavernBench：展示 vendored 评分快照 / 跑 --check

用法：
    python scripts/webui.py --port 8765
    python -m hsbg.webui.server --port 8765
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).with_name("static")
RUNS = ROOT / "runs"
WEB_RUNS = RUNS / "webui"


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except Exception:
        return str(path)


def status() -> Dict[str, Any]:
    engine: Dict[str, Any]
    try:
        import hsbg_engine as E  # type: ignore
        engine = {
            "kind": "hsbg_engine",
            "game_version": str(E.game_version()),
            "server_rules_version": str(E.server_rules_version()),
            "db_info": list(E.db_info()) if hasattr(E, "db_info") else None,
            "rust_mcts": bool(hasattr(E, "mcts_search")),
        }
    except Exception as exc:  # noqa: BLE001
        try:
            from hsrl2.db import CardDB
            db = CardDB.load(str(ROOT / "data"))
            engine = {
                "kind": "hsrl2-legacy",
                "reason": str(exc),
                "cards": len(getattr(db, "cards", {}) or {}),
            }
        except Exception as exc2:  # noqa: BLE001
            engine = {"kind": "unknown", "reason": f"{exc}; {exc2}"}
    try:
        from hsbg.rl.envs import BACKENDS
        backends = list(BACKENDS)
    except Exception:
        backends = []
    return {
        "ok": True,
        "cwd": str(ROOT),
        "python": sys.version.split()[0],
        "engine": engine,
        "backends": backends,
        "checkpoints": len(_checkpoint_files()),
        "runs_json": len(_run_files(limit=500)),
        "tavernbench_expected": (ROOT / "benchmarks/tavernbench/expected/eval_report.json").is_file(),
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _checkpoint_files() -> List[Path]:
    out: List[Path] = []
    if not RUNS.is_dir():
        return out
    for ext in ("*.pt", "*.pth", "*.ckpt", "*.npz"):
        out.extend(RUNS.rglob(ext))
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def _run_files(limit: int = 100) -> List[Path]:
    if not RUNS.is_dir():
        return []
    files = [p for p in RUNS.rglob("*.json") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def runs_payload(limit: int = 40) -> Dict[str, Any]:
    rows = []
    for p in _run_files(limit=limit):
        data = _read_json(p)
        if data is None:
            continue
        summary = None
        if isinstance(data, dict):
            if isinstance(data.get("summary"), dict):
                summary = data["summary"]
            elif isinstance(data.get("results"), list) and data["results"]:
                r0 = data["results"][0]
                if isinstance(r0, dict):
                    summary = r0.get("summary") or {
                        "mean_rank": r0.get("mean_rank"),
                        "top4_rate": r0.get("top4_rate"),
                        "win_rate": r0.get("win_rate"),
                    }
        rows.append({
            "path": _rel(p),
            "mtime": time.strftime("%Y-%m-%d %H:%M",
                                   time.localtime(p.stat().st_mtime)),
            "size": p.stat().st_size,
            "summary": _jsonable(summary),
        })
    return {"ok": True, "rows": rows}


def replay_payload() -> Dict[str, Any]:
    """Load the latest search+BotPrior demo replay saved under runs/webui/."""
    path = WEB_RUNS / "search_botprior_demo.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return {"ok": False, "error": f"missing replay: {_rel(path)}",
                "hint": "先运行 scripts/az_webui_match.py，再复制到 runs/webui/"}
    trace = []
    for row in data.get("trace") or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        for key in ("state", "after"):
            state = item.get(key)
            if isinstance(state, dict):
                state = dict(state)
                state.pop("combats", None)
                item[key] = state
        trace.append(item)
    return {
        "ok": True,
        "path": _rel(path),
        "seed": data.get("seed"),
        "config": data.get("config"),
        "result": data.get("result"),
        "trace": trace,
    }


def evaluate(payload: Dict[str, Any]) -> Dict[str, Any]:
    policy = str(payload.get("policy") or "heuristic").strip()
    if not policy or len(policy) > 500:
        raise ValueError("invalid policy")
    episodes = max(1, min(200, int(payload.get("episodes") or 5)))
    seed = int(payload.get("seed") or 0)
    workers = max(1, min(16, int(payload.get("workers") or 1)))
    backend = str(payload.get("backend") or "auto")
    opponent = str(payload.get("opponent") or "heuristic")
    WEB_RUNS.mkdir(parents=True, exist_ok=True)
    out = WEB_RUNS / f"eval_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.json"
    cmd = [
        sys.executable, "-m", "hsbg.rl.evaluate",
        "--policy", policy,
        "--episodes", str(episodes),
        "--seed", str(seed),
        "--workers", str(workers),
        "--backend", backend,
        "--opponent", opponent,
        "--json", "--out", str(out),
    ]
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd, cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900,
    )
    elapsed = round(time.perf_counter() - t0, 2)
    if proc.returncode != 0:
        raise RuntimeError(
            f"evaluate rc={proc.returncode}\n{(proc.stderr or proc.stdout or '')[-4000:]}")
    data = _read_json(out)
    if not isinstance(data, dict):
        raise RuntimeError("evaluate did not produce JSON")
    results = data.get("results") or []
    return {
        "ok": True,
        "elapsed_s": elapsed,
        "out": _rel(out),
        "command": cmd,
        "config": data.get("config"),
        "results": [_jsonable(r) for r in results],
        "stdout_tail": (proc.stdout or "")[-2000:],
    }


def tavernbench_payload() -> Dict[str, Any]:
    path = ROOT / "benchmarks/tavernbench/expected/eval_report.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return {"ok": False, "error": "expected/eval_report.json missing"}
    keys = ["play", "rule_score", "rules", "combat", "positioning",
            "ordering", "targets", "selection", "strategy", "economy",
            "real_time_play"]
    systems = {}
    for name, row in data.items():
        if not isinstance(row, dict):
            continue
        systems[name] = {k: row.get(k) for k in keys if k in row}
    return {"ok": True, "systems": systems,
            "source": _rel(path)}


def tavernbench_check() -> Dict[str, Any]:
    cmd = [sys.executable, "scripts/run_tavernbench.py", "--check"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=900)
    return {"ok": proc.returncode == 0, "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-8000:],
            "stderr": (proc.stderr or "")[-4000:]}


class Handler(BaseHTTPRequestHandler):
    server_version = "HSBRSIMWebUI/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _read_body(self) -> Dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(min(n, 1_000_000))
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        try:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                html = (STATIC / "index.html").read_bytes()
                self._send(200, html, "text/html; charset=utf-8")
            elif path == "/api/status":
                self._json(200, status())
            elif path == "/api/runs":
                self._json(200, runs_payload())
            elif path == "/api/replay":
                self._json(200, replay_payload())
            elif path == "/api/checkpoints":
                self._json(200, {"ok": True, "rows": [
                    {"path": _rel(p), "mtime": time.strftime(
                        "%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime)),
                     "size": p.stat().st_size}
                    for p in _checkpoint_files()[:200]
                ]})
            elif path == "/api/tavernbench":
                self._json(200, tavernbench_payload())
            elif path == "/api/health":
                self._json(200, {"ok": True, "time": time.time()})
            else:
                self._json(404, {"ok": False, "error": "not found"})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            path = urlparse(self.path).path
            body = self._read_body()
            if path == "/api/evaluate":
                self._json(200, evaluate(body))
            elif path == "/api/tavernbench-check":
                self._json(200, tavernbench_check())
            else:
                self._json(404, {"ok": False, "error": "not found"})
        except subprocess.TimeoutExpired:
            self._json(504, {"ok": False, "error": "timeout"})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"ok": False, "error": str(exc)})


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    httpd = ThreadingHTTPServer((host, int(port)), Handler)
    httpd.daemon_threads = True
    url = f"http://{host}:{int(port)}"
    print(f"[webui] HSBRSIM web console: {url}", flush=True)
    print(f"[webui] cwd={ROOT}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
