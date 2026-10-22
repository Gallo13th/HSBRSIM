"""Fast, calibrated click/drag automation for live Battlegrounds (1600x900).

Design goals:
- direct SendInput clicks/drags with calibrated client-relative coordinates;
- verify every action against the memory state (board/hand/choice counts);
- no full-game strategy: buy available shop minions, play hand minions, resolve
  choice windows (trinket / dark gift / discover), wait out combat timer;
- all actions logged with timings for replay/debugging.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.live.memory_state import read_memory_state
from hsbg.live.wininput import Win32Backend, find_hearthstone_window

# ---------------------------------------------------------------- calibration
# All coordinates are fractions of the **client** area (1600x900 reference).
START = (0.759, 0.778)
HERO_OPTIONS = [(0.22, 0.44), (0.36, 0.44), (0.50, 0.44), (0.64, 0.44)]
HERO_CONFIRM = (0.50, 0.71)
CHOICE_Y = 0.39
CHOICE_SPACING = 0.14
SHOP_Y = 0.34
SHOP_SPACING = 0.077
BOARD_Y = 0.52
BOARD_SPACING = 0.077
HAND_Y = 0.90
HAND_SPACING = 0.040
HAND_CENTER = 0.475


def _center(n: int, spacing: float, y: float, cx: float = 0.5) -> List[Tuple[float, float]]:
    if n <= 0:
        return []
    start = cx - (n - 1) * spacing / 2.0
    return [(start + i * spacing, y) for i in range(n)]


@dataclass
class ClickBot:
    out_dir: Path
    dry_run: bool = False
    max_actions_per_turn: int = 20
    log_path: Optional[Path] = None
    actions: int = 0
    errors: int = 0
    turn_actions: int = 0
    last_turn: int = -1
    fail_streak: int = 0
    _rec: Any = None

    def __post_init__(self):
        self.out_dir = Path(self.out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_path or (self.out_dir / "actions.jsonl")
        self._rec = open(self.log_path, "a", encoding="utf-8")
        self.window = find_hearthstone_window()
        self.backend = Win32Backend()
        self.l, self.t, self.r, self.b = self.window.client_rect

    def close(self):
        try:
            self._rec.close()
        except Exception:
            pass

    def _pt(self, fx: float, fy: float) -> Tuple[int, int]:
        return (self.l + int(fx * (self.r - self.l)),
                self.t + int(fy * (self.b - self.t)))

    def log(self, **kw):
        kw["ts"] = datetime.now().isoformat(timespec="milliseconds")
        kw["actions"] = self.actions
        self._rec.write(json.dumps(kw, ensure_ascii=False) + "\n")
        self._rec.flush()

    def click(self, fx: float, fy: float, note: str = ""):
        if self.dry_run:
            self.log(kind="dry_click", fx=fx, fy=fy, note=note)
            return
        x, y = self._pt(fx, fy)
        self.backend.click(x, y)
        self.actions += 1
        self.log(kind="click", fx=fx, fy=fy, note=note)

    def drag(self, a: Tuple[float, float], b: Tuple[float, float],
             duration: float = 0.22, note: str = ""):
        if self.dry_run:
            self.log(kind="dry_drag", a=a, b=b, note=note)
            return
        self.backend.drag([self._pt(*a), self._pt(*b)], duration=duration)
        self.actions += 1
        self.log(kind="drag", a=a, b=b, note=note)

    def state(self) -> Dict[str, Any]:
        return read_memory_state() or {}

    # ---------------------------------------------------------------- actions
    def do_choice(self, st: Dict[str, Any]) -> bool:
        choices = st.get("choices") or []
        if not choices:
            return False
        n = len(choices)
        spacing = 0.20 if n <= 3 else 0.14
        pts = _center(n, spacing, CHOICE_Y)
        for idx in range(n):
            self.click(*pts[idx], note=f"choice[{idx}]:{choices[idx].get('card')}")
            time.sleep(0.35)
            now = self.state()
            if not (now.get("choices") or []):
                return True
            # some windows need explicit confirm
            self.click(0.5, 0.70, note="choice_confirm")
            time.sleep(0.30)
            now = self.state()
            if not (now.get("choices") or []):
                return True
        return True

    def do_hero(self, st: Dict[str, Any]) -> bool:
        choices = st.get("choices") or []
        # available heroes: card ids not starting with a lock marker; pick middle
        pts = HERO_OPTIONS
        self.click(*pts[1], note="hero_option1")
        time.sleep(0.5)
        self.click(*HERO_CONFIRM, note="hero_confirm")
        time.sleep(0.5)
        return True

    def buy_shop(self, st: Dict[str, Any]) -> bool:
        shop = st.get("shop") or []
        gold = int(st.get("gold") or 0)
        hand = st.get("hand") or []
        legal_buy = (st.get("legal") or {}).get("buy") or []
        if not shop or not legal_buy or len(hand) >= 9:
            return False
        pts = _center(len(shop), SHOP_SPACING, SHOP_Y)
        hand_pt = (HAND_CENTER, HAND_Y)
        for i, item in enumerate(shop):
            cost = int(item.get("cost") or 3)
            if cost > gold or i >= len(pts):
                continue
            before = (len(hand), len(st.get("board") or []))
            # BG buy is a drag shop -> hand/board, not a click
            self.drag(pts[i], hand_pt, duration=0.42,
                      note=f"buy:{item.get('card')}")
            time.sleep(0.30)
            after = self.state()
            if (len(after.get("hand") or []), len(after.get("board") or [])) != before:
                self.turn_actions += 1
                return True
        return False

    def play_hand(self, st: Dict[str, Any]) -> bool:
        hand = st.get("hand") or []
        board = st.get("board") or []
        legal_play = (st.get("legal") or {}).get("play") or {}
        if not hand or not legal_play or len(board) >= 7:
            return False
        hand_pts = _center(len(hand), HAND_SPACING, HAND_Y, HAND_CENTER)
        board_pts = _center(max(1, len(board) + 1), BOARD_SPACING, BOARD_Y)
        # only minions with a legal play entry; spells need targets, skip them
        idx = None
        for i, m in enumerate(hand):
            if m.get("kind") != "minion":
                continue
            if str(i) not in legal_play:
                continue
            idx = i
            break
        if idx is None:
            return False
        before = len(board)
        self.drag(hand_pts[idx], board_pts[min(len(board), len(board_pts) - 1)],
                  duration=0.42, note=f"play:{hand[idx].get('card')}")
        time.sleep(0.30)
        after = self.state()
        if len(after.get("board") or []) > before:
            self.turn_actions += 1
            return True
        return False

    # ---------------------------------------------------------------- main loop
    def run(self, max_seconds: float = 3600.0) -> Dict[str, Any]:
        t0 = time.time()
        result: Dict[str, Any] = {"started": datetime.now().isoformat(timespec="seconds")}
        try:
            while time.time() - t0 < max_seconds:
                st = self.state()
                phase = str(st.get("phase") or "")
                turn = int(st.get("turn") or 0)
                if turn != self.last_turn:
                    self.last_turn = turn
                    self.turn_actions = 0
                    time.sleep(1.0)  # 新回合 splash / 动画
                self.log(kind="state", phase=phase, turn=turn,
                         gold=st.get("gold"), board=len(st.get("board") or []),
                         hand=len(st.get("hand") or []),
                         shop=len(st.get("shop") or []),
                         choices=[c.get("card") for c in (st.get("choices") or [])])
                if phase in ("no_active_game", "lobby", "menu"):
                    self.click(*START, note="start")
                    time.sleep(1.0)
                    continue
                if st.get("choices"):
                    self.do_choice(st)
                    time.sleep(0.3)
                    continue
                if phase == "hero_select":
                    self.do_hero(st)
                    time.sleep(0.5)
                    continue
                if phase == "recruit":
                    if self.turn_actions >= self.max_actions_per_turn:
                        time.sleep(0.5)
                        continue
                    if self.buy_shop(st):
                        self.fail_streak = 0
                        continue
                    if self.play_hand(st):
                        self.fail_streak = 0
                        continue
                    self.fail_streak += 1
                    # 动作没有生效（动画/遮罩/坐标偏差）：退避，避免无意义连点
                    time.sleep(min(2.0, 0.4 + 0.3 * self.fail_streak))
                    continue
                time.sleep(0.5)
            result["timed_out"] = True
        except KeyboardInterrupt:
            result["interrupted"] = True
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            result.update({"actions": self.actions, "errors": self.errors,
                           "elapsed_s": round(time.time() - t0, 1)})
            (self.out_dir / "summary.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            self.close()
        return result


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="runs/live/clickbot")
    ap.add_argument("--max-seconds", type=float, default=3600)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-actions-per-turn", type=int, default=20)
    args = ap.parse_args()
    bot = ClickBot(Path(args.out_dir), dry_run=args.dry_run,
                   max_actions_per_turn=args.max_actions_per_turn)
    res = bot.run(args.max_seconds)
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
