"""Live bridge pilot：只读内存 + BepInEx TCP bridge（不点击 UI）。

默认 dry-run：读 live state（或 --state-file）→ bridge state（或 --mock-bridge）→
打印 state/option 映射，不发送任何 option/choices。
真实：--live --bridge 才发送；用于登录恢复后的 1 局 pilot。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.live.bridge_action import bridge_state_from_live_mock, find_option_for_action
from hsbg.live.bridge_client import BridgeClient, BridgeError
from hsbg.live.memory_state import read_memory_state
from hsbg.live.turn_search_live import search_live_turn


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class BridgePilot:
    def __init__(self, *, live: bool, dry_run: bool, out_dir: Path,
                 bridge: Optional[BridgeClient], state_file: Optional[str] = None,
                 mock_bridge: bool = False, max_runtime: float = 1500.0,
                 max_actions_per_turn: int = 10):
        self.live = bool(live and not dry_run)
        self.dry_run = bool(dry_run or not live)
        self.out = out_dir
        self.out.mkdir(parents=True, exist_ok=True)
        self.bridge = bridge or BridgeClient()
        self.state_file = state_file
        self.mock_bridge = bool(mock_bridge)
        self.max_runtime = float(max_runtime)
        self.max_actions_per_turn = int(max_actions_per_turn)
        self.t0 = time.time()
        self.records = open(self.out / "records.jsonl", "a", encoding="utf-8")
        self.actions = 0
        self.decisions = 0
        self.errors = 0
        self.invalid = 0
        self.last_turn = -1
        self.turn_actions = 0

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
        self.bridge.close()

    def _read_live(self) -> Dict[str, Any]:
        if self.state_file:
            try:
                return json.loads(Path(self.state_file).read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                self.log({"kind": "state_file_error", "error": str(exc)})
        return read_memory_state() or {}

    def _read_bridge(self) -> Dict[str, Any]:
        if self.mock_bridge or self.dry_run and not self.bridge.ping():
            live = self._read_live()
            return bridge_state_from_live_mock(live)
        try:
            return self.bridge.state()
        except BridgeError as exc:
            self.log({"kind": "bridge_error", "error": str(exc)})
            return {"ok": False, "error": str(exc), "options": [], "choice": None}

    def _send_action(self, bridge_state: Dict[str, Any],
                     live_state: Dict[str, Any], action) -> bool:
        opt = find_option_for_action(bridge_state, live_state, action)
        if opt is None:
            self.errors += 1
            self.invalid += 1
            self.log({"kind": "mapping_failed", "action": action.format(),
                      "bridge_options": len(bridge_state.get("options") or [])})
            return False
        main = int(opt.get("main") or 0)
        targets = list(opt.get("targets") or [])
        target = int(targets[0]) if targets else 0
        pos = 0
        if action.kind == "play":
            pos = min(len(live_state.get("board") or []), 6)
        self.log({"kind": "mapped", "action": action.format(),
                  "option_type": opt.get("type"), "main": main,
                  "target": target, "pos": pos,
                  "targets": targets[:6]})
        if self.dry_run:
            return True
        try:
            resp = self.bridge.option(
                options_id=int(bridge_state.get("options_id") or 0),
                main=main, target=target, sub=-1, pos=pos)
        except BridgeError as exc:
            self.errors += 1
            self.log({"kind": "send_error", "error": str(exc)})
            return False
        if not resp.get("ok"):
            self.errors += 1
            self.invalid += 1
            self.log({"kind": "send_invalid", "response": resp})
            return False
        self.actions += 1
        self.log({"kind": "sent", "action": action.format(), "response": resp})
        return True

    def _send_choice(self, bridge_state: Dict[str, Any]) -> bool:
        choice = bridge_state.get("choice")
        if not choice:
            return False
        entities = [int(x) for x in (choice.get("entities") or [])]
        count_min = max(1, int(choice.get("count_min") or 1))
        picks = entities[:count_min]
        self.log({"kind": "choice", "id": choice.get("id"),
                  "type": choice.get("type"), "picks": picks})
        if self.dry_run:
            return True
        try:
            resp = self.bridge.choices(choice_id=int(choice.get("id") or 0),
                                       picks=picks)
        except BridgeError as exc:
            self.errors += 1
            self.log({"kind": "choice_error", "error": str(exc)})
            return False
        if not resp.get("ok"):
            self.errors += 1
            self.invalid += 1
            self.log({"kind": "choice_invalid", "response": resp})
            return False
        self.log({"kind": "choice_sent", "picks": picks, "response": resp})
        return True

    def run(self) -> Dict[str, Any]:
        result = {"started_at": datetime.now().isoformat(timespec="seconds"),
                  "dry_run": self.dry_run, "live": self.live,
                  "out": str(self.out)}
        seen_closed = 0
        try:
            while time.time() - self.t0 < self.max_runtime:
                live = self._read_live()
                phase = str(live.get("phase") or "")
                bs = self._read_bridge()
                if not bs.get("ok"):
                    seen_closed += 1
                    self.log({"kind": "bridge_unavailable", "error": bs.get("error"),
                              "phase": phase})
                    if seen_closed >= 5:
                        result["bridge_unavailable"] = True
                        break
                    time.sleep(1.0)
                    continue
                seen_closed = 0
                self.log({"kind": "state", "phase": phase,
                          "turn": live.get("turn"), "gold": live.get("gold"),
                          "board": len(live.get("board") or []),
                          "hand": len(live.get("hand") or []),
                          "shop": len(live.get("shop") or []),
                          "options": len(bs.get("options") or []),
                          "choice": bool(bs.get("choice"))})
                if bs.get("choice"):
                    self._send_choice(bs)
                    time.sleep(1.0)
                    continue
                if phase != "recruit":
                    if phase in ("game_over", "no_active_game"):
                        result["game_over"] = True
                        break
                    time.sleep(1.0)
                    continue
                turn = int(live.get("turn") or 0)
                if turn != self.last_turn:
                    self.last_turn = turn
                    self.turn_actions = 0
                if self.turn_actions >= self.max_actions_per_turn:
                    time.sleep(1.5)
                    continue
                res = search_live_turn(live, states_budget=8,
                                       seed=turn * 31 + self.decisions)
                self.decisions += 1
                self.log({"kind": "decision", "turn": turn,
                          "n_states": res.n_states, "n_combats": res.n_combats,
                          "ms": round(res.elapsed_s * 1000, 1),
                          "action": res.action.format(),
                          "scores": res.candidate_scores})
                if res.action.kind != "end_turn":
                    if self._send_action(bs, live, res.action):
                        self.turn_actions += 1
                    time.sleep(1.2)
                else:
                    if self._send_action(bs, live, res.action):
                        self.turn_actions = self.max_actions_per_turn
                    time.sleep(1.5)
        except KeyboardInterrupt:
            result["interrupted"] = True
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            result["error"] = f"{type(exc).__name__}: {exc}"
            self.log({"kind": "fatal", "error": result["error"]})
        finally:
            result.update({"actions": self.actions, "decisions": self.decisions,
                           "errors": self.errors, "invalid": self.invalid,
                           "elapsed_s": round(time.time() - self.t0, 1)})
            try:
                src = Path("C:/Program Files (x86)/Hearthstone/Logs/Power.log")
                if src.exists():
                    dst = self.out / f"Power_{_stamp()}.log"
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
    p = argparse.ArgumentParser(description="live bridge pilot (no UI clicks)")
    p.add_argument("--live", action="store_true", help="发送 bridge option/choices")
    p.add_argument("--dry-run", action="store_true", help="只映射，不发送")
    p.add_argument("--state-file", default=None, help="dry-run 用 live state 文件")
    p.add_argument("--mock-bridge", action="store_true",
                   help="dry-run 用 live state 合成 bridge state 校验映射")
    p.add_argument("--max-runtime", type=float, default=1500.0)
    p.add_argument("--max-actions-per-turn", type=int, default=10)
    p.add_argument("--out-dir", default=None)
    args = p.parse_args(argv)
    if not args.live:
        args.dry_run = True
    out = Path(args.out_dir) if args.out_dir else (
        ROOT / "runs" / "live" / f"turn_search_bridge_{_stamp()}")
    bridge = BridgeClient()
    pilot = BridgePilot(live=args.live and not args.dry_run,
                        dry_run=args.dry_run or not args.live,
                        out_dir=out, bridge=bridge,
                        state_file=args.state_file,
                        mock_bridge=args.mock_bridge,
                        max_runtime=args.max_runtime,
                        max_actions_per_turn=args.max_actions_per_turn)
    summary = pilot.run()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not summary.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
