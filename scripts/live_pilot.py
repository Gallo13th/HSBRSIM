"""真机 pilot：live state → 回合内 turn-search → UI 动作（1 局）。

用法（默认 dry-run，不会点击）：
  python scripts/live_pilot.py --dry-run
真实执行（会点击/拖拽；仅 1 局）：
  python scripts/live_pilot.py --live --max-runtime 1500

安全：--live 才发送输入；异常截图并停止；单局/动作上限；F12 由人工干预。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.live.config import LiveConfig, load_config
from hsbg.live.memory_state import read_memory_state
from hsbg.live.planner import PlannedAction, Planner
from hsbg.live.turn_search_live import search_live_turn
from hsbg.live.wininput import InputController, WindowNotFoundError, find_hearthstone_window


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class Pilot:
    def __init__(self, config: LiveConfig, *, live: bool, out_dir: Path,
                 max_runtime: float = 1500.0, max_actions_per_turn: int = 12):
        self.config = config
        self.live = bool(live)
        self.out = out_dir
        self.out.mkdir(parents=True, exist_ok=True)
        self.max_runtime = float(max_runtime)
        self.max_actions_per_turn = int(max_actions_per_turn)
        self.window = find_hearthstone_window(config) if live else None
        if live and self.window is None:
            raise WindowNotFoundError("找不到 Hearthstone 窗口")
        self.controller = (InputController(config, dry_run=not live,
                                           window=self.window,
                                           logger=lambda m: print(m, flush=True))
                           if live else None)
        self.planner = Planner(config)
        self.t0 = time.time()
        self.actions_total = 0
        self.search_decisions = 0
        self.errors = 0
        self.last_turn = -1
        self.turn_actions = 0
        self.records = open(self.out / "records.jsonl", "a", encoding="utf-8")

    def log(self, row: Dict[str, Any]) -> None:
        row["ts"] = datetime.now().isoformat(timespec="seconds")
        row["elapsed_s"] = round(time.time() - self.t0, 2)
        self.records.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.records.flush()

    def close(self) -> None:
        try:
            self.records.close()
        except Exception:  # noqa: BLE001
            pass
        if self.controller is not None:
            try:
                self.controller.close()
            except Exception:  # noqa: BLE001
                pass

    def _exec_planned(self, actions: List[PlannedAction]) -> int:
        n = 0
        for a in actions:
            if time.time() - self.t0 > self.max_runtime:
                return n
            if self.controller is None:
                self.log({"kind": "dry_plan", "action": a.format()})
                n += 1
                continue
            try:
                if a.kind == "click":
                    self.controller.click(float(a.x), float(a.y), note=a.name)
                elif a.kind == "drag":
                    self.controller.drag((float(a.x), float(a.y)),
                                         (float(a.x2), float(a.y2)),
                                         duration=float(a.duration or 0.35),
                                         note=a.name)
                elif a.kind == "key":
                    self.controller.key(a.key if a.key is not None else "E",
                                        note=a.name)
                elif a.kind == "wait":
                    time.sleep(float(a.seconds or 0.2))
                elif a.kind == "screenshot":
                    self.controller.screenshot(a.name or None)
                n += 1
                self.actions_total += 1
            except Exception as exc:  # noqa: BLE001
                self.errors += 1
                self.log({"kind": "exec_error", "action": a.to_dict(),
                          "error": f"{type(exc).__name__}: {exc}"})
                try:
                    if self.controller is not None:
                        self.controller.screenshot(f"error_{self._stamp()}.png")
                except Exception:  # noqa: BLE001
                    pass
                break
        return n

    def _layout(self, group: str, count: int):
        """按当前数量居中布局（新版酒馆 UI：商店/棋盘/手牌均居中排布）。"""
        layout = getattr(self.config.coords, "layout", None) or {}
        try:
            n = max(1, int(count))
            if group == "shop":
                y = float(layout.get("shop_y", 0.19))
                sp = float(layout.get("shop_spacing", 0.068229))
                start = 0.5 - (n - 1) * sp / 2.0
                return [(start + i * sp, y) for i in range(n)]
            if group == "board":
                y = float(layout.get("board_y", 0.55))
                sp = float(layout.get("board_spacing", 0.068229))
                start = 0.5 - (n - 1) * sp / 2.0
                return [(start + i * sp, y) for i in range(n)]
            if group == "hand":
                y = float(layout.get("hand_y", 0.90))
                sp = float(layout.get("hand_spacing", 0.057292))
                cx = float(layout.get("hand_center_x", 0.48))
                start = cx - (n - 1) * sp / 2.0
                return [(start + i * sp, y) for i in range(n)]
            return self.planner._layout_positions(group, n)  # noqa: SLF001
        except Exception:  # noqa: BLE001
            return list(self.config.coords.group(group))

    def _live_action(self, state: Dict[str, Any], action) -> bool:
        """执行 search 选出的 UI 动作；返回是否成功派发。"""
        if self.controller is None:
            self.log({"kind": "dry_action", "action": action.format()})
            return True
        shop_n = max(1, len(state.get("shop") or []))
        hand_n = max(1, len(state.get("hand") or []))
        board_n = max(1, len(state.get("board") or []))
        shop_pts = self._layout("shop", shop_n)
        hand_pts = self._layout("hand", hand_n)
        board_pts = self._layout("board", max(1, board_n))
        try:
            # 点击/拖拽前确保游戏窗口前台；否则输入可能丢失。
            try:
                self.controller.ensure_foreground()
                time.sleep(0.35)
            except Exception:  # noqa: BLE001
                pass
            if action.kind == "buy" and 0 <= action.index < len(shop_pts):
                src = shop_pts[action.index]
                dst = hand_pts[min(len(state.get("hand") or []), len(hand_pts) - 1)]
                self.controller.drag(src, dst,
                                     duration=float(self.config.delays.drag_duration_s) + 0.15,
                                     note=f"turn_search_buy_{action.index}")
                time.sleep(float(self.config.delays.after_drag_s) + 0.8)
                return True
            if action.kind == "play" and 0 <= action.index < len(hand_pts):
                src = hand_pts[action.index]
                dst = board_pts[min(len(state.get("board") or []), len(board_pts) - 1)]
                self.controller.drag(src, dst,
                                     duration=float(self.config.delays.drag_duration_s),
                                     note=f"turn_search_play_{action.index}")
                time.sleep(float(self.config.delays.after_drag_s))
                return True
            if action.kind == "end_turn":
                return True
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            self.log({"kind": "ui_error", "action": action.format(),
                      "error": f"{type(exc).__name__}: {exc}"})
        return False

    def _handle_choice(self, state: Dict[str, Any]) -> bool:
        """处理英雄选择 / 饰品 / 黑暗之赐 / 发现等 choice 窗口。

        只读内存拿 choices，按选项点击后点确认；不依赖 UI 文本。
        """
        if self.controller is None:
            self.log({"kind": "dry_choice", "phase": state.get("phase"),
                      "choices": [c.get("card") for c in (state.get("choices") or [])]})
            return False
        phase = str(state.get("phase") or "")
        choices = list(state.get("choices") or [])
        if not choices:
            return False
        if phase == "hero_select":
            pts = list(self.config.coords.groups.get("hero_options") or [])
            confirm = self.config.coords.points.get("hero_confirm")
            idx = int(getattr(self.config.flow, "hero_option_index", 0) or 0)
        else:
            pts = list(self.config.coords.groups.get("choice_options") or [])
            confirm = self.config.coords.points.get("choice_confirm")
            idx = 0
        if not pts:
            return False
        idx = max(0, min(idx, len(pts) - 1, len(choices) - 1))
        try:
            self.controller.ensure_foreground()
            time.sleep(0.2)
            x, y = pts[idx]
            self.controller.click(float(x), float(y), note=f"{phase}_option_{idx}")
            time.sleep(0.4)
            if confirm is not None:
                self.controller.click(float(confirm[0]), float(confirm[1]),
                                      note=f"{phase}_confirm")
                time.sleep(0.5)
            self.actions_total += 1
            self.log({"kind": "choice", "phase": phase, "index": idx,
                      "card": choices[idx].get("card"),
                      "choices": [c.get("card") for c in choices],
                      "confirm": bool(confirm)})
            return True
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            self.log({"kind": "choice_error", "phase": phase,
                      "error": f"{type(exc).__name__}: {exc}"})
            return False

    def _snapshot_for_planner(self, state: Dict[str, Any]):
        from hsbg.live.memory_state import apply_memory
        return apply_memory(None, state)

    def run(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"started_at": datetime.now().isoformat(timespec="seconds"),
                                  "live": self.live, "out": str(self.out)}
        last_phase = ""
        wait_until = 0.0
        try:
            while time.time() - self.t0 < self.max_runtime:
                state = read_memory_state() or {}
                phase = str(state.get("phase") or "")
                if state.get("schema") != "hsbg.live_state.v1":
                    phase = phase or "unavailable"
                if phase == "unavailable":
                    # 内存不可用（游戏重启/退出/过渡）；不要空转。
                    if not hasattr(self, "_unavailable_since"):
                        self._unavailable_since = time.time()
                    elif time.time() - self._unavailable_since > 20.0:
                        self.log({"kind": "game_unavailable_exit"})
                        result["game_unavailable"] = True
                        break
                    time.sleep(1.0)
                    continue
                self._unavailable_since = 0.0
                self.log({"kind": "state", "phase": phase,
                          "turn": state.get("turn"), "gold": state.get("gold"),
                          "board": len(state.get("board") or []),
                          "hand": len(state.get("hand") or []),
                          "shop": len(state.get("shop") or []),
                          "choices": [c.get("card") for c in (state.get("choices") or [])],
                          "legal_keys": sorted((state.get("legal") or {}).keys())})
                if phase != last_phase:
                    self.log({"kind": "phase_change", "from": last_phase, "to": phase})
                    last_phase = phase
                if state.get("choices") and phase not in ("combat", "unavailable"):
                    if self._handle_choice(state):
                        time.sleep(1.0)
                        continue
                if phase in ("menu", "lobby", "hero_select", "choice",
                             "no_active_game", "game_over"):
                    snap = self._snapshot_for_planner(state)
                    planned = self.planner.plan(snap, state)
                    self._exec_planned(planned)
                    if phase == "game_over":
                        try:
                            if self.controller is not None:
                                self.controller.screenshot("game_over.png")
                        except Exception:  # noqa: BLE001
                            pass
                        result["game_over"] = True
                        break
                    time.sleep(0.8)
                    continue
                if phase == "combat":
                    time.sleep(1.0)
                    continue
                if phase != "recruit":
                    time.sleep(1.0)
                    continue
                turn = int(state.get("turn") or 0)
                if turn != self.last_turn:
                    self.last_turn = turn
                    self.turn_actions = 0
                if self.turn_actions >= self.max_actions_per_turn:
                    time.sleep(1.5)
                    continue
                # 防重复决策：同 turn 已记录动作后等待 UI 更新
                res = search_live_turn(state, states_budget=8,
                                       seed=int(state.get("turn") or 0) * 31 + self.search_decisions)
                self.search_decisions += 1
                self.log({"kind": "decision", "phase": phase, "turn": turn,
                          "gold": state.get("gold"), "tier": state.get("tier"),
                          "n_states": res.n_states, "n_combats": res.n_combats,
                          "ms": round(res.elapsed_s * 1000, 1),
                          "action": res.action.format(),
                          "candidate_scores": res.candidate_scores,
                          "board": [m.get("card") for m in (state.get("board") or [])],
                          "hand": [m.get("card") for m in (state.get("hand") or [])],
                          "shop": [m.get("card") for m in (state.get("shop") or [])]})
                if res.action.kind == "end_turn":
                    # 无结束按钮：等计时器；若配置有 end_turn 坐标/键则执行
                    if self.config.flow.send_end_turn:
                        acts = [PlannedAction(kind="key", name="end_turn",
                                              key=self.config.flow.end_turn_key)]
                        self._exec_planned(acts)
                    time.sleep(3.0)
                    continue
                before = state
                ok = self._live_action(state, res.action)
                if ok:
                    self.turn_actions += 1
                    time.sleep(1.2)
                    after = read_memory_state() or {}
                    changed = (len(after.get("board") or []) != len(before.get("board") or [])
                               or len(after.get("hand") or []) != len(before.get("hand") or []))
                    self.log({"kind": "action", "action": res.action.format(),
                              "changed": changed})
                    if not changed and self.live:
                        self.errors += 1
                        self.log({"kind": "no_change", "action": res.action.format()})
                else:
                    self.errors += 1
                    time.sleep(1.0)
            result["timed_out"] = time.time() - self.t0 >= self.max_runtime
        except KeyboardInterrupt:
            result["interrupted"] = True
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            result["error"] = f"{type(exc).__name__}: {exc}"
            try:
                if self.controller is not None:
                    self.controller.screenshot(f"fatal_{self._stamp()}.png")
            except Exception:  # noqa: BLE001
                pass
        finally:
            result.update({"actions": self.actions_total,
                           "search_decisions": self.search_decisions,
                           "errors": self.errors,
                           "elapsed_s": round(time.time() - self.t0, 1)})
            # Power.log 归档
            try:
                src = Path(self.config.power_log_path())
                if src.exists():
                    dst = self.out / f"Power_{self._stamp()}.log"
                    shutil.copy2(src, dst)
                    result["power_log"] = str(dst)
            except Exception:  # noqa: BLE001
                pass
            try:
                (self.out / "summary.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
            self.close()
        return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="live turn-search pilot")
    p.add_argument("--live", action="store_true", help="真实点击/拖拽（默认 dry-run）")
    p.add_argument("--dry-run", action="store_true", help="只读状态/计划，不点击")
    p.add_argument("--max-runtime", type=float, default=1500.0)
    p.add_argument("--max-actions-per-turn", type=int, default=12)
    p.add_argument("--out-dir", default=None)
    p.add_argument("--config", default=None)
    args = p.parse_args(argv)
    if not args.live:
        args.dry_run = True
    out = Path(args.out_dir) if args.out_dir else (
        ROOT / "runs" / "live" / f"turn_search_pilot_{_stamp()}")
    try:
        config = load_config(args.config)
        pilot = Pilot(config, live=bool(args.live and not args.dry_run),
                      out_dir=out, max_runtime=args.max_runtime,
                      max_actions_per_turn=args.max_actions_per_turn)
        summary = pilot.run()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if not summary.get("error") else 1
    except Exception as exc:  # noqa: BLE001
        print(f"[live_pilot] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
