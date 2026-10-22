"""自动对局主循环：状态机 + 输入执行 + 记录归档。

职责
----
* 每 tick：``watcher.poll()`` → ``memory_reader()`` → ``Planner.plan()`` →
  :class:`hsbg.live.wininput.InputController` 执行（dry-run 只打印）；
* 对局生命周期归档：每局开始/结束写 ``records.jsonl``（含 Power.log/HDT 路径、
  起止时间、回合数、名次（若能从内存状态读到）、结束原因）；
* 阶段/错误事件写 ``events.jsonl``；异常时截图 ``runs/live/.../error_*.png``；
* F12 暂停/恢复（:class:`hsbg.live.wininput.PauseController`）、Ctrl+C 优雅退出、
  最大局数/最大时长保护。

默认安全策略
------------
* ``LiveBot(live=False)`` / CLI 不带 ``--live`` → **dry-run**：绝不点击真实鼠标，
  只打印 ``[DRY] ...`` 计划；
* 找不到窗口/日志时（且允许 simulate）→ 用 :class:`SimulatedWatcher` 跑通全流程，
  便于无游戏环境验证（``--simulate`` 可显式指定）。

备注
----
``hsbg.bridge.live_log.LiveLogWatcher``（rea-operator）就绪后由
:func:`hsbg.live.logwatch.create_watcher` 自动优先使用；``tools.live_state_mem``
就绪后由 :mod:`hsbg.live.memory_state` 自动接入（都可从外部注入，便于测试）。
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from hsbg.live.config import LiveConfig
from hsbg.live.logwatch import (
    LiveLogWatcher,
    LiveSnapshot,
    PHASE_CHOICE,
    PHASE_COMBAT,
    PHASE_GAME_OVER,
    PHASE_HERO_SELECT,
    PHASE_LOBBY,
    PHASE_MENU,
    PHASE_RECRUIT,
    create_watcher,
)
from hsbg.live.memory_state import MemoryReader, apply_memory, load_memory_reader
from hsbg.live.planner import PlannedAction, Planner
from hsbg.live.wininput import (
    InputController,
    WindowNotFoundError,
    find_hearthstone_window,
    process_running,
)

#: 每局记录 JSONL 字段（tests/分析用）
GAME_RECORD_KEYS = (
    "kind", "game_no", "game_id", "session_id", "started_at", "ended_at",
    "duration_s", "turns", "placement", "reason", "power_log", "hdt_log",
    "power_log_archive", "actions", "errors", "dry_run", "blind",
)


@dataclass
class RunSummary:
    """一次 ``LiveBot.run()`` 的汇总。"""

    games_requested: int = 0
    games_played: int = 0
    errors: int = 0
    wall_seconds: float = 0.0
    session_dir: str = ""
    records_path: str = ""
    events_path: str = ""
    reason: str = ""
    dry_run: bool = True
    blind: bool = False
    simulated: bool = False
    placements: List[Optional[int]] = field(default_factory=list)
    started_at: float = 0.0
    ended_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "games_requested": self.games_requested,
            "games_played": self.games_played,
            "errors": self.errors,
            "wall_seconds": round(self.wall_seconds, 3),
            "session_dir": self.session_dir,
            "records_path": self.records_path,
            "events_path": self.events_path,
            "reason": self.reason,
            "dry_run": self.dry_run,
            "blind": self.blind,
            "simulated": self.simulated,
            "placements": list(self.placements),
        }

    def format(self) -> str:
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        if self.blind:
            mode += "+blind"
        if self.simulated:
            mode += "+simulated"
        return (
            f"[live] done: {self.games_played}/{self.games_requested} games, "
            f"errors={self.errors}, wall={self.wall_seconds:.1f}s, mode={mode}, "
            f"reason={self.reason}\n"
            f"       records={self.records_path or '(none)'}"
        )


# ══════════════════════════════════════════════════════════════════════
# 模拟状态 watcher（无窗口/无日志时的 dry-run 演示 & 测试）
# ══════════════════════════════════════════════════════════════════════


class SimulatedWatcher:
    """按脚本推进的假 watcher：完整走一遍 菜单→大厅→英雄→招募→战斗→结算。

    用于 ``--dry-run --simulate`` 与测试；不读任何日志、不需要游戏窗口。
    ``poll()`` 返回当前阶段快照，``advance()`` 前进到下一个脚本阶段。
    """

    simulated = True

    def __init__(
        self,
        config: Optional[LiveConfig] = None,
        *,
        games: int = 1,
        start_phase: str = PHASE_MENU,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config or LiveConfig()
        self.clock = clock
        self._script = self._build_script(max(1, int(games)))
        self._idx = 0
        self._snapshot = self._script[0]
        self._advance_polls = 0

    @staticmethod
    def _build_script(games: int) -> List[LiveSnapshot]:
        script: List[LiveSnapshot] = [
            LiveSnapshot(phase=PHASE_MENU, in_game=False, mode="HUB",
                         source="simulated"),
            LiveSnapshot(phase=PHASE_LOBBY, in_game=False, mode="BACON",
                         source="simulated"),
        ]
        game_id = 0
        for game_no in range(1, games + 1):
            game_id += 1
            base = {"game_id": game_id, "in_game": True, "mode": "GAMEPLAY",
                    "source": "simulated",
                    "session_id": f"sim_{game_no}"}
            script.append(LiveSnapshot(phase=PHASE_HERO_SELECT, turn=0, **base))
            for turn in (1, 2, 3):
                script.append(LiveSnapshot(phase=PHASE_RECRUIT, turn=turn, **base))
                script.append(LiveSnapshot(phase=PHASE_COMBAT, turn=turn, **base))
            script.append(LiveSnapshot(phase=PHASE_CHOICE, turn=3,
                                       notes={"choice_serial": game_no,
                                              "choice_type": "DISCOVER"},
                                       **base))
            script.append(LiveSnapshot(phase=PHASE_GAME_OVER, turn=6,
                                       in_game=False, game_id=game_id,
                                       mode="BACON", source="simulated",
                                       session_id=f"sim_{game_no}",
                                       placement=(game_no % 8) + 1))
        script.append(LiveSnapshot(phase=PHASE_MENU, in_game=False, mode="HUB",
                                   source="simulated"))
        return script

    def poll(self) -> LiveSnapshot:
        return self._snapshot

    def snapshot(self) -> LiveSnapshot:
        return self._snapshot

    def advance(self) -> LiveSnapshot:
        self._idx = min(self._idx + 1, len(self._script) - 1)
        self._snapshot = self._script[self._idx]
        self._advance_polls = 0
        return self._snapshot

    @property
    def at_end(self) -> bool:
        return self._idx >= len(self._script) - 1

    def reset(self) -> None:
        self._idx = 0
        self._snapshot = self._script[0]
        self._advance_polls = 0


# ══════════════════════════════════════════════════════════════════════
# 主循环
# ══════════════════════════════════════════════════════════════════════


class LiveBot:
    """自动代打数据采集主循环（默认 dry-run）。

    参数
    ----
    config : LiveConfig
    live : bool
        ``True`` 才真正执行鼠标/键盘（需要找到炉石窗口）；
        默认 ``False`` = dry-run（只打印计划）。
    controller / watcher / memory_reader : 可注入（测试/替换实现）
    out_dir : 产物目录（默认 ``runs/live/session_<时间戳>``）
    clock / sleep_fn : 可注入（测试用假时钟）
    """

    def __init__(
        self,
        config: Optional[LiveConfig] = None,
        *,
        live: bool = False,
        controller: Optional[InputController] = None,
        watcher: Any = None,
        memory_reader: Optional[MemoryReader] = None,
        memory_reader_spec: Optional[str] = None,
        out_dir: Optional[Path | str] = None,
        clock: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
        logger: Optional[Callable[[str], None]] = None,
        verbose: bool = False,
        pause_controller: Any = None,
        auto_memory: bool = True,
        dry_run_max_actions: int = 0,
        dry_run_max_seconds: float = 0.0,
    ) -> None:
        self.config = config or LiveConfig.load()
        self.live = bool(live)
        self.dry_run = not self.live
        # 安全网：测试环境绝不允许真实输入（防止 CI/单测误操作正在运行的游戏）
        if (self.live and os.environ.get("PYTEST_CURRENT_TEST")
                and os.environ.get("HSBG_ALLOW_LIVE_IN_TESTS") != "1"):
            raise RuntimeError(
                "检测到 pytest 环境：禁止以 live=True 启动 LiveBot（防止测试发送真实输入）。"
                "如确需测试 live 路径，请设置 HSBG_ALLOW_LIVE_IN_TESTS=1 并自行保证无游戏窗口。"
            )
        self.clock = clock
        self.sleep_fn = sleep_fn or time.sleep
        self.logger = logger or (lambda msg: print(msg, flush=True))
        self.verbose = bool(verbose)
        self._stop_requested = False
        self._pause_controller = pause_controller
        self.dry_run_max_actions = int(dry_run_max_actions or 0)
        self.dry_run_max_seconds = float(dry_run_max_seconds or 0.0)
        self._executed_total = 0

        # 产物目录
        stamp = time.strftime("%Y%m%d_%H%M%S")
        mode = "live" if self.live else "dryrun"
        if out_dir is None:
            out_dir = self.config.runs_dir_resolved() / f"{mode}_{stamp}"
        self.session_dir = Path(out_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.records_path = self.session_dir / "records.jsonl"
        self.events_path = self.session_dir / "events.jsonl"
        self.summary_path = self.session_dir / "summary.json"
        self._config_path = self.session_dir / "config_snapshot.json"
        self._write_json(self._config_path, self.config.to_dict())
        self._records: List[Dict[str, Any]] = []
        self._events: List[Dict[str, Any]] = []

        # 输入控制器
        self.controller = controller
        if self.controller is None:
            try:
                self.controller = InputController(
                    self.config,
                    dry_run=self.dry_run,
                    logger=self._log_input,
                    sleep_fn=self.sleep_fn,
                )
            except WindowNotFoundError as exc:
                if not self.dry_run:
                    raise
                self.logger(f"[live] 未找到游戏窗口（dry-run 继续）: {exc}")

        # 暂停（F12）：优先使用注入的；否则复用 controller.pause
        if self._pause_controller is None and self.controller is not None:
            self._pause_controller = getattr(self.controller, "pause", None)

        # 状态来源
        self.watcher = watcher
        self.simulated = bool(getattr(watcher, "simulated", False))
        self.blind = bool(self.config.flow.blind)
        if self.watcher is None and not self.blind:
            try:
                self.watcher = create_watcher(
                    self.config, start_at_end=True, clock=self.clock,
                    logger=self.logger if self.verbose else None,
                )
            except Exception as exc:  # noqa: BLE001
                self.logger(f"[live] watcher 创建失败: {exc}")
                self.watcher = None
        if self.watcher is not None and not self.simulated:
            if not getattr(self.watcher, "has_sources", True):
                if self.dry_run and self.config.flow.simulate_when_unavailable:
                    self.logger(
                        "[live] 日志文件不存在（游戏/HDT 未运行）→ dry-run 使用"
                        " SimulatedWatcher 演示状态机"
                    )
                    self.watcher = SimulatedWatcher(self.config)
                    self.simulated = True
                else:
                    self.logger("[live] 日志文件不存在，将仅在状态可用时操作"
                                "（或使用 --blind）")
        if self.watcher is None and not self.blind:
            if not self.blind:
                self.blind = True
                self.logger("[live] 无 watcher/日志 → 进入盲操作模式（--blind）")
            if self.dry_run and self.config.flow.simulate_when_unavailable:
                self.watcher = SimulatedWatcher(self.config)
                self.simulated = True

        # 内存状态（rea-operator）；模拟状态下不自动接入（避免覆盖模拟阶段）
        self.memory_reader = memory_reader
        if self.memory_reader is None and not self.simulated and auto_memory:
            if memory_reader_spec:
                self.memory_reader = load_memory_reader(memory_reader_spec)
            if self.memory_reader is None:
                self.memory_reader = load_memory_reader()
        if self.memory_reader is not None:
            self.logger("[live] 已接入内存状态读取器（shop/hand/rank 将更精确）")
        self._memory_cache: Optional[Dict[str, Any]] = None
        self._memory_last_ts = 0.0

        self.planner = Planner(self.config, clock=self.clock)
        self.summary = RunSummary(
            games_requested=int(self.config.flow.max_games),
            dry_run=self.dry_run, blind=self.blind, simulated=self.simulated,
            session_dir=str(self.session_dir),
            records_path=str(self.records_path),
            events_path=str(self.events_path),
        )
        self._last_game_id: Optional[int] = None
        self._current_game: Optional[Dict[str, Any]] = None
        self._consecutive_errors = 0
        self._empty_polls = 0
        self._blind_games_recorded = 0
        self._last_snapshot: Optional[LiveSnapshot] = None
        self._started_at = 0.0
        # 客户端存活/重启
        self._client_missing_since = 0.0
        self._client_check_ts = 0.0
        self._client_check_ok = True
        self._client_restarts = 0
        # 结算页重试
        self._game_over_retries = 0
        self._game_over_last_nudge = 0.0
        # 本地递增 game_id（bridge 的 game_id 跨局可能一直是 0，planner 去重会失效）
        self._local_game_seq = 0
        self._current_local_game_id = 0

    # ── 日志工具 ──
    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    def _append_jsonl(self, path: Path, row: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _event(self, kind: str, **data: Any) -> None:
        row = {"ts": self.clock(), "event": kind, **data}
        self._events.append(row)
        self._append_jsonl(self.events_path, row)
        if self.verbose:
            self.logger(f"[event] {kind} {data}")

    def _log_input(self, msg: str) -> None:
        # InputController 的 dry-run 打印与 runner 的 [PLAN] 重复，默认静默；
        # 警告类（前台失败等）在 verbose 模式输出。
        if self.verbose and ("失败" in msg or "异常" in msg or "error" in msg.lower()):
            self.logger(msg)

    def _read_memory(self, now: float) -> Optional[Dict[str, Any]]:
        """按 ``flow.memory_poll_s`` 节流读取内存状态（失败静默降级）。"""
        reader = self.memory_reader
        if reader is None:
            return None
        interval = max(0.05, float(self.config.flow.memory_poll_s))
        if (self._memory_cache is not None
                and now - self._memory_last_ts < interval):
            return self._memory_cache
        self._memory_last_ts = now
        try:
            state = reader()
        except Exception as exc:  # noqa: BLE001 - 内存读取失败不影响主流程
            self._event("memory_error", error=f"{type(exc).__name__}: {exc}")
            state = None
        self._memory_cache = state if isinstance(state, dict) else None
        return self._memory_cache

    # ── 客户端存活 / 重启 / 结算页 ──
    def _client_alive(self, now: Optional[float] = None) -> bool:
        """炉石进程 + 窗口是否还在（缓存 1 秒，避免每 tick 枚举窗口）。"""
        if not self.live or self.simulated:
            return True
        now = self.clock() if now is None else now
        if now - self._client_check_ts < 1.0:
            return self._client_check_ok
        self._client_check_ts = now
        try:
            ok = process_running(self.config.window.process)
            if ok:
                ok = find_hearthstone_window(self.config) is not None
        except Exception:  # noqa: BLE001
            ok = True  # 检测失败时不误杀（交给 memory/watcher 降级）
        self._client_check_ok = bool(ok)
        return self._client_check_ok

    def _power_log_path_now(self, snap: Optional[LiveSnapshot]) -> str:
        """当前对局最新的 Power.log（优先快照路径，其次动态发现最新日志）。"""
        candidate = str(snap.power_log_path) if snap is not None else ""
        try:
            if candidate and Path(candidate).exists():
                age = time.time() - Path(candidate).stat().st_mtime
                if age < 6 * 3600:
                    return candidate
        except OSError:
            pass
        try:
            from hsbg.bridge.live_log import discover_power_log  # type: ignore

            found = discover_power_log()
            if found is not None:
                return str(found)
        except Exception:  # noqa: BLE001
            pass
        return candidate

    def _hdt_log_path_now(self, snap: Optional[LiveSnapshot]) -> str:
        candidate = str(snap.hdt_log_path) if snap is not None else ""
        try:
            if candidate and Path(candidate).exists():
                return candidate
        except OSError:
            pass
        try:
            from hsbg.live.logwatch import _HdtObserver

            path = _HdtObserver(self.config.hdt_log_dir_resolved())._resolve()
            if path is not None:
                return str(path)
        except Exception:  # noqa: BLE001
            pass
        return candidate

    def _archive_power_log(self, source: str, game_no: int) -> Optional[Path]:
        """把本局结束时的 Power.log 复制进会话目录（Power.log 下一局会被截断复用）。"""
        if not source or not bool(self.config.flow.archive_power_log):
            return None
        try:
            src = Path(source)
            if not src.exists():
                return None
            out_dir = self.session_dir / "logs"
            out_dir.mkdir(parents=True, exist_ok=True)
            dst = out_dir / f"game_{int(game_no):02d}_Power.log"
            shutil.copy2(src, dst)
            self._event("power_log_archived", game_no=int(game_no),
                        path=str(dst), size=dst.stat().st_size)
            return dst
        except Exception as exc:  # noqa: BLE001
            self._event("power_log_archive_error", error=str(exc))
            return None

    def _restart_client(self) -> bool:
        """用 Battle.net ``--exec=launch WTCG`` 重启炉石，等待窗口/内存就绪。"""
        cfg = self.config
        battle_net = Path(os.path.expandvars(cfg.paths.battle_net))
        if not battle_net.exists():
            self.logger(f"[live] 找不到 Battle.net: {battle_net}")
            return False
        self._client_restarts += 1
        self._event("client_restart_begin", attempt=self._client_restarts)
        self.logger(f"[live] 炉石进程不在，尝试重启客户端（第 {self._client_restarts} 次）…")
        try:
            subprocess.Popen([str(battle_net), "--exec=launch WTCG"],
                             close_fds=True)
        except Exception as exc:  # noqa: BLE001
            self.logger(f"[live] 启动 Battle.net 失败: {exc}")
            return False
        deadline = self.clock() + float(cfg.flow.restart_timeout_s)
        ready = False
        while self.clock() < deadline and not self._stop_requested:
            self.sleep_fn(2.0)
            try:
                if process_running(cfg.window.process) and \
                        find_hearthstone_window(cfg) is not None:
                    ready = True
                    break
            except Exception:  # noqa: BLE001
                continue
        if not ready:
            self.logger("[live] 客户端重启超时")
            self._event("client_restart_timeout")
            return False
        # 等加载/登录，重建 controller+watcher（窗口句柄会变）
        self.sleep_fn(6.0)
        try:
            self.controller = InputController(
                cfg, dry_run=self.dry_run, logger=self._log_input,
                sleep_fn=self.sleep_fn,
            )
        except WindowNotFoundError as exc:
            self.logger(f"[live] 重启后找不到窗口: {exc}")
            return False
        try:
            self.watcher = create_watcher(
                cfg, start_at_end=True, clock=self.clock, logger=self.logger,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger(f"[live] 重启后重建 watcher 失败: {exc}")
        self._last_snapshot = None
        self._current_game = None
        self._last_game_id = None
        self._memory_cache = None
        self._memory_last_ts = 0.0
        self._game_over_retries = 0
        try:
            self.planner.reset()
            # 点掉启动页「点击开始」（多点几次；之后由 planner 处理 主菜单→大厅→排队）
            for _ in range(3):
                self.controller.click(0.5, 0.5, note="splash_start")
                self.sleep_fn(2.5)
        except Exception as exc:  # noqa: BLE001
            self.logger(f"[live] 重启后点启动页失败: {exc}")
        self._event("client_restart_ok")
        self.logger("[live] 客户端已重启，继续采集")
        return True

    def _handle_game_over_stuck(self, now: float) -> None:
        """结算页连续点不动时有限次尝试（不盲点，超限即停）。"""
        if now - self._game_over_last_nudge < 2.5:
            return
        self._game_over_last_nudge = now
        self._game_over_retries += 1
        max_retries = max(1, int(self.config.flow.max_game_over_retries))
        if self._game_over_retries > max_retries:
            self._event("game_over_stuck", retries=self._game_over_retries)
            self.logger("[live] 结算页多次重试无效，停止（避免乱点）")
            self.summary.reason = "game_over_stuck"
            self._stop_requested = True
            return
        ctl = self.controller
        if ctl is None:
            return
        attempt = self._game_over_retries
        coords = self.config.coords
        try:
            if attempt <= 2:
                px, py = coords.point("result_continue")
                ctl.click(px, py, note="结算继续")
            elif attempt <= 4:
                ctl.key("ESC", note="结算页 ESC")
                self.sleep_fn(0.4)
                px, py = coords.point("result_center")
                ctl.click(px, py, note="结算页中心")
            else:
                px, py = coords.point("result_continue")
                ctl.click(px, py, note="结算继续")
        except Exception as exc:  # noqa: BLE001
            self._on_error(exc)
        self._event("game_over_nudge", attempt=attempt)

    # ── 记录 ──
    def _start_game(self, snap: LiveSnapshot) -> None:
        if self._current_game is not None:
            self._finish_game(snap, reason="new_game_detected")
        # bridge 的 game_id 跨局可能恒为 0 → 用本地递增序号给 planner 做每局去重键
        self._local_game_seq += 1
        self._current_local_game_id = self._local_game_seq
        self._current_game = {
            "kind": "game",
            "game_no": len(self._records) + 1,
            "game_id": self._current_local_game_id,
            "session_id": snap.session_id,
            "started_at": self.clock(),
            # 动态取本局最新 Power.log/HDT 路径，避免复用旧会话路径
            "power_log": self._power_log_path_now(snap),
            "hdt_log": self._hdt_log_path_now(snap),
            "actions": 0,
            "errors": 0,
            "max_turn": int(snap.turn),
        }
        self._event("game_start", game_no=self._current_game["game_no"],
                    game_id=self._current_local_game_id,
                    session_id=snap.session_id,
                    power_log=self._current_game["power_log"])
        self.logger(
            f"[live] game {self._current_game['game_no']} start "
            f"(game_id={self._current_local_game_id}, session={snap.session_id or '?'}, "
            f"power_log={Path(self._current_game['power_log']).name or '?'})"
        )

    def _finish_game(self, snap: Optional[LiveSnapshot], *, reason: str) -> Optional[Dict[str, Any]]:
        game = self._current_game
        if game is None:
            return None
        now = self.clock()
        placement = None
        if snap is not None:
            placement = snap.placement
        if placement is None and self.memory_reader is not None:
            try:
                mem = self._memory_cache
                if not isinstance(mem, dict):
                    mem = self.memory_reader() or {}
                value = mem.get("placement", mem.get("rank"))
                if value is not None:
                    placement = int(value)
                elif mem.get("alive") is False:
                    alive_count = mem.get("alive_count")
                    if isinstance(alive_count, int) and 1 <= alive_count <= 8:
                        placement = min(8, alive_count + 1)
            except Exception:  # noqa: BLE001
                pass
        turns = int(snap.turn) if snap is not None else 0
        turns = max(turns, int(game.get("max_turn", 0)))
        if snap is not None:
            turns = max(turns, int(snap.turns_played))
        # 结束时再刷新一次日志路径（会话轮转后取最新）
        try:
            refreshed = self._power_log_path_now(snap)
            if refreshed:
                game["power_log"] = refreshed
            refreshed_hdt = self._hdt_log_path_now(snap)
            if refreshed_hdt:
                game["hdt_log"] = refreshed_hdt
        except Exception:  # noqa: BLE001
            pass
        archive = self._archive_power_log(
            str(game.get("power_log", "")), int(game["game_no"]))
        record = {
            "kind": "game",
            "game_no": int(game["game_no"]),
            "game_id": int(game["game_id"]),
            "session_id": str(game.get("session_id", "")),
            "started_at": float(game["started_at"]),
            "ended_at": float(now),
            "duration_s": round(float(now) - float(game["started_at"]), 3),
            "turns": turns,
            "placement": placement,
            "reason": str(reason),
            "power_log": str(game.get("power_log", "")),
            "hdt_log": str(game.get("hdt_log", "")),
            "power_log_archive": str(archive) if archive else "",
            "actions": int(game.get("actions", 0)),
            "errors": int(game.get("errors", 0)),
            "dry_run": self.dry_run,
            "blind": self.blind,
        }
        self._records.append(record)
        self._append_jsonl(self.records_path, record)
        self.summary.games_played += 1
        self.summary.placements.append(placement)
        self.summary.errors += int(record["errors"])
        self._event("game_end", game_no=record["game_no"],
                    game_id=record["game_id"], placement=placement,
                    turns=turns, reason=reason,
                    duration_s=record["duration_s"])
        self.logger(
            f"[live] game {record['game_no']} end: placement={placement} "
            f"turns={turns} reason={reason} duration={record['duration_s']:.1f}s"
        )
        self._current_game = None
        self._last_game_id = record["game_id"]
        return record

    def _track_snapshot(self, snap: LiveSnapshot) -> None:
        # 客户端不在时，日志可能是旧会话的滞后状态，不能据此开新局
        if self.live and not self.simulated and not self._client_alive():
            return
        self._last_snapshot = snap
        if snap.in_game and snap.phase not in (PHASE_MENU, PHASE_LOBBY):
            if self._current_game is None:
                self._start_game(snap)
            elif int(snap.game_id) != int(self._current_game["game_id"]):
                self._finish_game(self._last_snapshot, reason="new_game_detected")
                self._start_game(snap)
            if self._current_game is not None:
                self._current_game["max_turn"] = max(
                    int(self._current_game.get("max_turn", 0)), int(snap.turn))
                if not self._current_game.get("hdt_log"):
                    self._current_game["hdt_log"] = snap.hdt_log_path
        if snap.phase == PHASE_GAME_OVER and self._current_game is not None:
            self._finish_game(snap, reason=str(snap.notes.get("reason", "game_over")))
        # 单局超时保护
        if self._current_game is not None:
            elapsed = self.clock() - float(self._current_game["started_at"])
            if elapsed > float(self.config.flow.game_timeout_s):
                self._event("game_timeout", game_id=self._current_game["game_id"],
                            elapsed=round(elapsed, 1))
                self.logger(f"[live] 单局超过 {elapsed:.0f}s，按超时结束并重新开始")
                self._finish_game(snap, reason="game_timeout")
                self._emergency_reset()

    def _track_blind_progress(self) -> None:
        completed = self.planner.blind_games_completed
        while self._blind_games_recorded < completed:
            self._blind_games_recorded += 1
            if self._current_game is None:
                self._current_game = {
                    "kind": "game", "game_no": len(self._records) + 1,
                    "game_id": self._blind_games_recorded,
                    "session_id": "", "started_at": self.clock(),
                    "power_log": "", "hdt_log": "", "actions": 0, "errors": 0,
                    "max_turn": 0,
                }
                self._event("game_start", game_no=self._current_game["game_no"],
                            game_id=self._blind_games_recorded, blind=True)
            self._finish_game(None, reason="blind_timer")

    def _emergency_reset(self) -> None:
        """异常/超时后点一下「再来一局/返回大厅」，避免卡在结算页。"""
        if self.controller is None:
            return
        try:
            px, py = self.config.coords.point("lobby_play_again")
            if self.dry_run:
                self.logger(f"[DRY] click lobby_play_again ({px:.3f},{py:.3f}) "
                            f"[emergency]")
            else:
                self.controller.click(px, py, note="emergency_reset")
        except Exception:  # noqa: BLE001
            pass

    # ── 动作执行 ──
    def _execute_actions(self, actions: Sequence[PlannedAction]) -> int:
        executed = 0
        for action in actions:
            if self._stop_requested:
                break
            pause = self._pause_controller
            if pause is not None and getattr(pause, "paused", False):
                self.logger("[live] 已暂停（F12 恢复）")
                break
            if self.dry_run:
                snapshot = self._last_snapshot
                where = ""
                if snapshot is not None:
                    where = (f"[{snapshot.phase} t{snapshot.turn} "
                             f"g{snapshot.game_id}] ")
                self.logger(f"[PLAN] {where}{action.format()}")
            try:
                self._dispatch(action)
                executed += 1
                if self._current_game is not None:
                    self._current_game["actions"] += 1
                if self.verbose and not self.dry_run:
                    snapshot = self._last_snapshot
                    where = ""
                    if snapshot is not None:
                        where = (f"[{snapshot.phase} t{snapshot.turn} "
                                 f"g{snapshot.game_id}] ")
                    self.logger(f"[act] {where}{action.format()}")
            except Exception as exc:  # noqa: BLE001 - 单个动作失败不拖垮整局
                self._on_error(exc, action)
        return executed

    def _dispatch(self, action: PlannedAction) -> None:
        ctl = self.controller
        if ctl is None:
            raise RuntimeError("没有 InputController（dry-run 也应初始化一个）")
        if action.kind == "click":
            ctl.click(float(action.x or 0.0), float(action.y or 0.0),
                      note=action.note or action.name)
        elif action.kind == "drag":
            ctl.drag((float(action.x or 0.0), float(action.y or 0.0)),
                     (float(action.x2 or 0.0), float(action.y2 or 0.0)),
                     duration=action.duration, note=action.note or action.name)
        elif action.kind == "key":
            ctl.key(action.key if action.key is not None else "E",
                    note=action.note or action.name)
        elif action.kind == "wait":
            ctl.wait(float(action.seconds or 0.0), note=action.note or action.name)
        elif action.kind == "screenshot":
            ctl.screenshot(action.name or None)
        elif action.kind == "record":
            self._event("record", name=action.name, note=action.note)
        else:
            raise ValueError(f"未知动作类型: {action.kind!r}")

    def _on_error(self, exc: Exception, action: Optional[PlannedAction] = None) -> None:
        self._consecutive_errors += 1
        self.summary.errors += 1
        if self._current_game is not None:
            self._current_game["errors"] += 1
        self._event("error", error=f"{type(exc).__name__}: {exc}",
                    action=action.to_dict() if action else None)
        self.logger(f"[live] 动作异常: {type(exc).__name__}: {exc}")
        # 截图便于事后定位
        if self.controller is not None and not self.dry_run:
            try:
                stamp = time.strftime("%Y%m%d_%H%M%S")
                self.controller.screenshot(f"error_{stamp}.png")
            except Exception:  # noqa: BLE001
                pass
        if self._consecutive_errors >= int(self.config.safety.max_consecutive_errors):
            self._stop_requested = True
            self.summary.reason = "too_many_errors"
            self.logger("[live] 连续错误过多，停止")

    # ── 主循环 ──
    def stop(self) -> None:
        self._stop_requested = True

    def run(self, max_games: Optional[int] = None) -> RunSummary:
        cfg = self.config
        games_limit = (int(max_games) if max_games is not None
                       else int(cfg.flow.max_games))
        self._started_at = self.clock()
        self.summary.games_requested = games_limit
        self.summary.started_at = self._started_at
        reason = "unknown"
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        self.logger(
            f"[live] start: mode={mode} blind={self.blind} "
            f"simulated={self.simulated} max_games={games_limit} "
            f"out={self.session_dir}"
        )
        self._event("start", mode=mode, blind=self.blind,
                    simulated=self.simulated, max_games=games_limit)
        try:
            while not self._stop_requested:
                now = self.clock()
                wall = now - self._started_at
                if games_limit > 0 and self.summary.games_played >= games_limit:
                    reason = "max_games"
                    break
                if wall >= float(cfg.flow.max_runtime_s):
                    reason = "max_runtime"
                    break
                # F12 暂停
                pause = self._pause_controller
                if pause is not None:
                    try:
                        pause.poll_once()
                    except Exception:  # noqa: BLE001
                        pass
                    if getattr(pause, "paused", False):
                        self.sleep_fn(max(0.05, float(cfg.flow.poll_interval_s)))
                        continue
                # 客户端存活检测（进程+窗口）；消失超过阈值 → 记录 client_gone 并尝试重启
                if self.live and not self.simulated:
                    if not self._client_alive(now):
                        if self._client_missing_since == 0.0:
                            self._client_missing_since = now
                            self._event("client_missing")
                            self.logger("[live] 检测不到炉石进程/窗口…")
                        elif (now - self._client_missing_since
                              >= float(cfg.flow.client_gone_s)):
                            self._event(
                                "client_gone",
                                missing_s=round(now - self._client_missing_since, 1),
                            )
                            self.logger("[live] 炉石进程消失，本局按 client_gone 结束")
                            if self._current_game is not None:
                                self._finish_game(self._last_snapshot,
                                                  reason="client_gone")
                            if cfg.flow.restart_client and self._restart_client():
                                self._client_missing_since = 0.0
                                self._game_over_retries = 0
                                continue
                            reason = "client_gone"
                            break
                        self.sleep_fn(max(0.5, float(cfg.flow.poll_interval_s)))
                        continue
                    self._client_missing_since = 0.0
                # 观测
                snap: Optional[LiveSnapshot] = None
                if self.watcher is not None:
                    try:
                        snap = self.watcher.poll()
                    except Exception as exc:  # noqa: BLE001 - watcher 失败降级
                        self._event("watcher_error", error=str(exc))
                        self.logger(f"[live] watcher 异常: {exc}")
                        snap = None
                # 决策（内存状态按 memory_poll_s 节流；内存优先于日志）
                memory = self._read_memory(now)
                merged = apply_memory(snap, memory) if memory else snap
                if merged is not None:
                    merged = copy.copy(merged)  # 防止改到 watcher 内部快照
                    # 当前局内：把 bridge 的 game_id 归一成本地 id，避免误判"新局"
                    if self._current_game is not None:
                        merged.game_id = self._current_local_game_id
                    self._track_snapshot(merged)
                    # bridge 的 game_id 跨局可能恒为 0：统一用本地递增 id 给 planner 去重
                    if self._current_game is not None:
                        merged.game_id = self._current_local_game_id
                    elif merged.phase == PHASE_GAME_OVER:
                        merged.game_id = self._current_local_game_id
                    if (self.live and not self.simulated
                            and merged.phase == PHASE_GAME_OVER):
                        self._handle_game_over_stuck(now)
                    else:
                        self._game_over_retries = 0
                # 盲模式进度
                if self.blind:
                    self._track_blind_progress()
                actions = self.planner.plan(
                    merged if merged is not None else snap, None, now=now)
                executed = self._execute_actions(actions)
                self._executed_total += executed
                if executed and executed == len(actions):
                    self._consecutive_errors = 0
                # dry-run 预览保护：动作数/秒数到上限自动退出，避免无游戏时一直跑
                if self.dry_run:
                    if (self.dry_run_max_actions > 0
                            and self._executed_total >= self.dry_run_max_actions):
                        reason = "dry_run_action_limit"
                        self.logger(
                            f"[live] dry-run 已执行 {self._executed_total} 个计划动作，"
                            f"预览结束（--dry-actions 0 可取消限制）"
                        )
                        break
                    if (self.dry_run_max_seconds > 0
                            and wall >= self.dry_run_max_seconds):
                        reason = "dry_run_time_limit"
                        self.logger(
                            f"[live] dry-run 已达到 {self.dry_run_max_seconds:.0f}s，预览结束"
                        )
                        break
                # 模拟状态推进：没有可执行动作时前进一步
                if not actions:
                    self._empty_polls += 1
                    if self.simulated and self._empty_polls >= 2:
                        self._empty_polls = 0
                        try:
                            advanced = self.watcher.advance()
                            self._event("sim_advance", phase=advanced.phase,
                                        turn=advanced.turn)
                        except Exception:  # noqa: BLE001
                            pass
                else:
                    self._empty_polls = 0
                self.sleep_fn(max(0.01, float(cfg.flow.poll_interval_s)))
        except KeyboardInterrupt:
            reason = "ctrl_c"
            self.logger("[live] 收到 Ctrl+C，退出")
        finally:
            if reason in ("unknown", ""):
                reason = (self.summary.reason
                          if self.summary.reason not in ("", "unknown")
                          else ("stopped" if self._stop_requested else "finished"))
            if self._current_game is not None:
                self._finish_game(self._last_snapshot, reason=f"run_stop:{reason}")
            self.summary.reason = reason
            self.summary.ended_at = self.clock()
            self.summary.wall_seconds = self.summary.ended_at - self._started_at
            self.summary.errors = max(self.summary.errors,
                                      sum(int(r.get("errors", 0)) for r in self._records))
            self._event("stop", reason=reason,
                        games_played=self.summary.games_played,
                        errors=self.summary.errors)
            self._write_json(self.summary_path, {
                **self.summary.to_dict(),
                "config": self.config.to_dict(),
                "records": self._records,
            })
            try:
                if self.controller is not None:
                    self.controller.close()
            except Exception:  # noqa: BLE001
                pass
            self.logger(self.summary.format())
        return self.summary


__all__ = ["GAME_RECORD_KEYS", "RunSummary", "SimulatedWatcher", "LiveBot"]
