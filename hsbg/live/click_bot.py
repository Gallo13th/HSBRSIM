"""Fully automatic click/drag Battlegrounds bot (1600x900).

Design:
- calibrated SendInput clicks/drags (buy = drag shop->hand, play = drag hand->board);
- every action is verified against the memory state;
- a no-effect action is blacklisted for the current turn and a screenshot is
  written to `screenshots/` so the failure can be inspected;
- the loop is fully automatic across games: result screen -> next lobby -> start
  next match; optional auto-launch of Hearthstone via Battle.net.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.live.config import LiveConfig
from hsbg.live.launcher import launch_hearthstone_via_battlenet
from hsbg.live.memory_state import read_memory_state
from hsbg.live.wininput import Win32Backend, find_hearthstone_window

# ---------------------------------------------------------------- 1600x900 calibration
START = (0.759, 0.778)
HERO_OPTIONS = [(0.22, 0.44), (0.36, 0.44), (0.50, 0.44), (0.64, 0.44)]
HERO_CONFIRM = (0.50, 0.71)
CHOICE_Y = 0.45
CHOICE_SPACING = 0.14
CHOICE_CONFIRM = (0.50, 0.70)
BOB_PORTRAIT = (0.50, 0.14)       # 拖随从到这里卖出
UPGRADE_BTN = (0.394, 0.145)      # 酒馆升级按钮（顶部左侧）
REFRESH_BTN = (0.60, 0.18)        # 刷新按钮（顶部右侧）
REFRESH_POINTS = [(0.60, 0.18)]
SHOP_Y = 0.34
SHOP_SPACING = 0.077
BOARD_Y = 0.52
BOARD_SPACING = 0.077
HAND_Y = 0.90
HAND_SPACING = 0.040
HAND_CENTER = 0.475
RESULT_POINTS = [(0.5393, 0.8492), (0.50, 0.86), (0.50, 0.50), (0.78, 0.92)]


def _center(n: int, spacing: float, y: float, cx: float = 0.5) -> List[Tuple[float, float]]:
    if n <= 0:
        return []
    start = cx - (n - 1) * spacing / 2.0
    return [(start + i * spacing, y) for i in range(n)]


@dataclass
class ClickBot:
    out_dir: Path
    dry_run: bool = False
    max_actions_per_turn: int = 30
    games: int = 0                 # 0 = infinite
    max_seconds: float = 0.0       # 0 = infinite
    auto_launch: bool = True
    actions: int = 0
    errors: int = 0
    turn_actions: int = 0
    last_turn: int = -1
    fail_streak: int = 0
    games_done: int = 0
    _rec: Any = None
    _window: Any = None
    _seen_game_over: bool = False
    _unavailable: int = 0
    _last_lobby_click: float = 0.0
    _overlay_turn: int = -1
    _settled_turn: int = -1
    _upgrade_turn: int = -1
    _refresh_turn: int = -1
    _refresh_failed_turn: int = -1

    def __post_init__(self):
        self.out_dir = Path(self.out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "screenshots").mkdir(exist_ok=True)
        self._rec = open(self.out_dir / "actions.jsonl", "a", encoding="utf-8")
        self.failed: Set[str] = set()
        self._connect()

    # ------------------------------------------------------------ window/input
    def _connect(self) -> bool:
        try:
            self._window = find_hearthstone_window()
        except Exception:
            self._window = None
        if self._window is not None and str(getattr(self._window, "process", "")).lower() != "hearthstone.exe":
            self._window = None
        if self._window is None and self.auto_launch:
            launch_hearthstone_via_battlenet(
                log=lambda m: self.log(kind="launcher", msg=str(m)))
            try:
                self._window = find_hearthstone_window()
            except Exception:
                self._window = None
        if self._window is None:
            return False
        self.backend = Win32Backend()
        self.l, self.t, self.r, self.b = self._window.client_rect
        return True

    def _launch(self) -> None:
        cfg = LiveConfig()
        battle_net = Path(getattr(cfg.paths, "battle_net", ""))
        if not battle_net.exists():
            return
        subprocess.Popen([str(battle_net), "--exec=launch WTCG"])
        deadline = time.time() + 120
        while time.time() < deadline:
            time.sleep(3)
            try:
                self._window = find_hearthstone_window()
            except Exception:
                self._window = None
            if self._window is not None:
                return

    def close(self) -> None:
        try:
            self._rec.close()
        except Exception:
            pass

    def _pt(self, fx: float, fy: float) -> Tuple[int, int]:
        return (self.l + int(fx * (self.r - self.l)),
                self.t + int(fy * (self.b - self.t)))

    def log(self, **kw) -> None:
        kw["ts"] = datetime.now().isoformat(timespec="milliseconds")
        kw["actions"] = self.actions
        self._rec.write(json.dumps(kw, ensure_ascii=False) + "\n")
        self._rec.flush()

    def screenshot(self, tag: str) -> Optional[str]:
        try:
            from PIL import ImageGrab
            w = self._window
            if w is None or not w.client_rect:
                return None
            l, t, r, b = w.client_rect
            path = self.out_dir / "screenshots" / (
                f"{datetime.now().strftime('%H%M%S')}_{tag}.png")
            ImageGrab.grab(bbox=(l, t, r, b)).save(path)
            return str(path)
        except Exception:
            return None

    def _focus(self) -> None:
        try:
            h = getattr(self._window, "hwnd", None)
            if h:
                u = ctypes.windll.user32
                u.ShowWindow(h, 9)
                u.SetForegroundWindow(h)
                time.sleep(0.08)
        except Exception:
            pass

    def click(self, fx: float, fy: float, note: str = "") -> None:
        if self.dry_run:
            self.log(kind="dry_click", fx=fx, fy=fy, note=note)
            return
        self._focus()
        self.backend.click(*self._pt(fx, fy))
        self.actions += 1
        self.log(kind="click", fx=fx, fy=fy, note=note)

    def drag(self, a: Tuple[float, float], b: Tuple[float, float],
             duration: float = 0.40, note: str = "") -> None:
        if self.dry_run:
            self.log(kind="dry_drag", a=a, b=b, note=note)
            return
        self._focus()
        self.backend.drag([self._pt(*a), self._pt(*b)], duration=duration)
        self.actions += 1
        self.log(kind="drag", a=a, b=b, note=note)

    def state(self) -> Dict[str, Any]:
        try:
            return read_memory_state() or {}
        except Exception:
            return {}

    def _sig(self, st: Dict[str, Any]) -> Tuple:
        return (st.get("phase"), st.get("turn"), len(st.get("hand") or []),
                len(st.get("board") or []), len(st.get("shop") or []),
                tuple(c.get("eid") for c in (st.get("choices") or [])),
                int(st.get("gold") or 0))

    def _changed(self, before: Tuple, timeout: float = 1.2) -> bool:
        """Poll state until it changes or timeout (UI animations are async)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.18)
            if self._sig(self.state()) != before:
                return True
        return False

    def _click_overlay(self, st: Dict[str, Any]) -> bool:
        """Fallback for visible non-memory overlays (Choose One / spell pages)."""
        before = self._sig(st)
        for pt in ((0.44, 0.47), (0.56, 0.47), (0.50, 0.55)):
            self.click(*pt, note="overlay_click")
            time.sleep(0.45)
            now = self.state()
            if self._sig(now) != before:
                return True
        return False

    def _fail(self, key: str, st: Dict[str, Any], note: str) -> None:
        if key in self.failed:
            return
        self.failed.add(key)
        shot = self.screenshot(f"fail_{abs(hash(key)) % 100000:05d}")
        self.errors += 1
        self.log(kind="no_effect", key=key, note=note, phase=st.get("phase"),
                 turn=st.get("turn"), gold=st.get("gold"),
                 hand=[m.get("card") for m in (st.get("hand") or [])],
                 board=[m.get("card") for m in (st.get("board") or [])],
                 shop=[m.get("card") for m in (st.get("shop") or [])],
                 screenshot=shot)

    # ------------------------------------------------------------ actions
    def do_choice(self, st: Dict[str, Any]) -> bool:
        choices = st.get("choices") or []
        if not choices or "choice" in self.failed:
            return False
        pts = _center(len(choices), 0.20 if len(choices) <= 3 else 0.14, CHOICE_Y)
        for idx, pt in enumerate(pts):
            before = self._sig(st)
            self.click(*pt, note=f"choice[{idx}]:{choices[idx].get('card')}")
            time.sleep(0.45)
            now = self.state()
            if not (now.get("choices") or []):
                return True
            if self._sig(now) != before:
                return True
        self._fail("choice", st, "choices 未消失")
        return False

    def do_hero(self, st: Dict[str, Any]) -> bool:
        # 可能弹出“英雄栏位锁定”确认框，先点取消
        self.click(0.56, 0.58, note="hero_locked_cancel")
        time.sleep(0.25)
        before = self._sig(st)
        for pt in (HERO_OPTIONS[1], HERO_OPTIONS[2]):
            self.click(*pt, note="hero_option")
            time.sleep(0.35)
            self.click(*HERO_CONFIRM, note="hero_confirm")
            time.sleep(0.45)
            now = self.state()
            if str(now.get("phase")) != "hero_select":
                return True
            if self._sig(now) != before:
                before = self._sig(now)
        self._fail("hero_select", st, "英雄选择未推进")
        return False

    def _hand_pts(self, n: int):
        return _center(n, HAND_SPACING, HAND_Y, HAND_CENTER)

    def sell_board(self, st: Dict[str, Any]) -> bool:
        """棋盘满且有手牌时，卖最弱随从腾格子（拖到 Bob 头像）。"""
        board = st.get("board") or []
        hand = st.get("hand") or []
        if not board or not hand or len(board) < 7:
            return False
        pts = _center(len(board), BOARD_SPACING, BOARD_Y)
        idx = min(range(len(board)),
                  key=lambda i: int(board[i].get("atk") or 0) + int(board[i].get("hp") or 0))
        key = f"sell:{board[idx].get('eid')}:{board[idx].get('card')}"
        if key in self.failed:
            return False
        before = self._sig(st)
        self.drag(pts[idx], BOB_PORTRAIT, duration=0.45,
                  note=f"sell:{board[idx].get('card')}")
        if self._changed(before):
            self.turn_actions += 1
            return True
        self._fail(key, st, "卖出后状态未变化")
        return False

    def upgrade_tavern(self, st: Dict[str, Any]) -> bool:
        """尝试升级；0 费升级/legal.upgrade 缺失时也点一次验证。"""
        legal = bool((st.get("legal") or {}).get("upgrade"))
        if not legal and int(st.get("gold") or 0) > 0:
            return False
        tier_before = st.get("tier")
        before = self._sig(st)
        self.click(*UPGRADE_BTN, note="upgrade")
        time.sleep(0.6)
        now = self.state()
        if now.get("tier") != tier_before:
            self.turn_actions += 1
            return True
        if self._sig(now) != before and int(now.get("gold") or 0) < int(st.get("gold") or 0):
            self.turn_actions += 1
            return True
        return False

    def _minion_score(self, m: Dict[str, Any]) -> float:
        try:
            return float(int(m.get("atk") or 0) + int(m.get("hp") or 0)
                         + 2 * int(m.get("tier") or 1))
        except Exception:
            return 0.0

    def action_scores(self, st: Dict[str, Any]) -> Dict[str, float]:
        """把买/打/卖/升级/刷新都当成候选动作打分，而不是固定优先级。"""
        gold = int(st.get("gold") or 0)
        shop = st.get("shop") or []
        board = st.get("board") or []
        hand = st.get("hand") or []
        legal = st.get("legal") or {}
        affordable = [m for m in shop
                      if (3 if m.get("cost") is None else int(m.get("cost") or 0)) <= gold]
        best_buy = max((self._minion_score(m) for m in affordable), default=0.0)
        legal_play = legal.get("play") or {}
        play_vals = []
        for idx, m in enumerate(hand):
            if str(idx) not in legal_play:
                continue
            if m.get("kind") == "minion" and len(board) >= 7:
                continue
            play_vals.append(self._minion_score(m) if m.get("kind") == "minion" else 30.0)
        best_play = max(play_vals, default=0.0)
        sell = 30.0 if len(board) >= 7 and hand else 0.0
        upgrade = 130.0 if legal.get("upgrade") and gold == 0 else (70.0 if legal.get("upgrade") else 0.0)
        refresh = 0.0
        if legal.get("refresh") and gold >= 1:
            refresh = 50.0
            if not shop:
                refresh += 60.0
            if not affordable:
                refresh += 25.0
            if len(board) >= 7:
                refresh += 10.0
        return {"buy": 80.0 + best_buy, "play": 60.0 + best_play,
                "sell": sell, "upgrade": upgrade, "refresh": refresh}

    def refresh_shop(self, st: Dict[str, Any]) -> bool:
        """刷新是候选动作；成功可连续刷新，失败则本回合不再点。"""
        if self._refresh_failed_turn == int(st.get("turn") or 0):
            return False
        if not ((st.get("legal") or {}).get("refresh")):
            return False
        gold0 = int(st.get("gold") or 0)
        shop0 = tuple(m.get("card") for m in (st.get("shop") or []))
        before = self._sig(st)
        for pt in REFRESH_POINTS:
            self.click(*pt, note="refresh")
            time.sleep(0.5)
            now = self.state()
            shop1 = tuple(m.get("card") for m in (now.get("shop") or []))
            if (int(now.get("gold") or 0) != gold0 or shop1 != shop0
                    or self._sig(now) != before):
                self.turn_actions += 1
                return True
        self._refresh_failed_turn = int(st.get("turn") or 0)
        return False

    def settle_screenshot(self, st: Dict[str, Any], turn: int) -> None:
        """每回合操作做完后截图 + 落盘状态，供异步复盘。"""
        if turn <= 0 or self._settled_turn == turn:
            return
        self._settled_turn = turn
        shot = self.screenshot(f"turn{turn:02d}_settled")
        path = self.out_dir / "settled" / f"turn_{turn:02d}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"state": st, "screenshot": shot},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        self.log(kind="turn_settled", turn=turn, screenshot=shot,
                 gold=st.get("gold"), board=[m.get("card") for m in (st.get("board") or [])],
                 hand=[m.get("card") for m in (st.get("hand") or [])])

    def buy_shop(self, st: Dict[str, Any]) -> bool:
        shop = st.get("shop") or []
        gold = int(st.get("gold") or 0)
        hand = st.get("hand") or []
        if not shop or len(hand) >= 9:
            return False
        pts = _center(len(shop), SHOP_SPACING, SHOP_Y)
        order = sorted(range(len(shop)),
                       key=lambda i: self._minion_score(shop[i]), reverse=True)
        for i in order:
            item = shop[i]
            key = f"buy:{item.get('eid')}:{item.get('card')}"
            if key in self.failed:
                continue
            cost = item.get("cost")
            cost = 3 if cost is None else int(cost)
            if cost > gold or i >= len(pts):
                continue
            before = self._sig(st)
            self.drag(pts[i], (HAND_CENTER, HAND_Y), duration=0.42,
                      note=f"buy:{item.get('card')}")
            if self._changed(before):
                self.turn_actions += 1
                return True
            self._fail(key, st, "购买后状态未变化")
        return False

    def play_hand(self, st: Dict[str, Any]) -> bool:
        hand = st.get("hand") or []
        board = st.get("board") or []
        legal_play = (st.get("legal") or {}).get("play") or {}
        if not hand:
            return False
        hand_pts = self._hand_pts(len(hand))
        board_pts = _center(max(1, len(board) + 1), BOARD_SPACING, BOARD_Y)
        for idx, m in enumerate(hand):
            kind = str(m.get("kind") or "")
            if kind not in ("minion", "spell"):
                continue
            if kind == "minion" and len(board) >= 7:
                continue
            key = f"play:{m.get('eid')}:{m.get('card')}"
            if key in self.failed:
                continue
            entry = legal_play.get(str(idx))
            if legal_play and entry is None:
                continue
            # targeted spells/minions are skipped for now (need target click)
            if isinstance(entry, dict):
                use = entry.get("use") or {}
                if use.get("targets"):
                    continue
            before = self._sig(st)
            if kind == "spell":
                # 无目标法术：拖到棋盘中央施放
                self.drag(hand_pts[idx], (0.50, 0.52), duration=0.42,
                          note=f"cast:{m.get('card')}")
            else:
                self.drag(hand_pts[idx],
                          board_pts[min(len(board), len(board_pts) - 1)],
                          duration=0.42, note=f"play:{m.get('card')}")
            if self._changed(before):
                self.turn_actions += 1
                return True
            self._fail(key, st, "打出后状态未变化")
        return False

    # ------------------------------------------------------------ main loop
    def _start_game(self) -> None:
        for pt in RESULT_POINTS:
            self.click(*pt, note="result_continue")
            time.sleep(0.7)
            st = self.state()
            if str(st.get("phase")) in ("no_active_game", "lobby", "menu",
                                        "hero_select", "recruit"):
                break
        self.click(*START, note="start")
        time.sleep(1.0)

    def run(self) -> Dict[str, Any]:
        t0 = time.time()
        result: Dict[str, Any] = {"started": datetime.now().isoformat(timespec="seconds")}
        try:
            if not self._connect():
                result["error"] = "no Hearthstone window"
                return result
            while True:
                if self.max_seconds and time.time() - t0 > self.max_seconds:
                    result["timed_out"] = True
                    break
                if self.games and self.games_done >= self.games:
                    break
                st = self.state()
                phase = str(st.get("phase") or "")
                turn = int(st.get("turn") or 0)
                if not phase:
                    self._unavailable += 1
                    if self._unavailable >= 5:
                        self.log(kind="game_unavailable", n=self._unavailable)
                        self._connect()
                        self._unavailable = 0
                    time.sleep(1.0)
                    continue
                self._unavailable = 0
                if turn != self.last_turn:
                    self.last_turn = turn
                    self.turn_actions = 0
                    self.failed.clear()
                    time.sleep(0.8)
                self.log(kind="state", phase=phase, turn=turn,
                         gold=st.get("gold"), board=len(st.get("board") or []),
                         hand=len(st.get("hand") or []),
                         shop=len(st.get("shop") or []),
                         choices=[c.get("card") for c in (st.get("choices") or [])])
                if phase in ("game_over", "result", "spectating"):
                    if not self._seen_game_over:
                        self._seen_game_over = True
                        self.games_done += 1
                        self.log(kind="game_over", rank=st.get("rank"),
                                 screenshot=self.screenshot("game_over"))
                    self._start_game()
                    time.sleep(2.0)
                    self._seen_game_over = False
                    continue
                if phase in ("no_active_game", "lobby", "menu"):
                    # 主菜单 → 酒馆战棋；BG 大厅 → 开始；排队中不要反复点
                    if time.time() - self._last_lobby_click > 10.0:
                        self._last_lobby_click = time.time()
                        self.click(0.50, 0.378, note="menu_battlegrounds")
                        time.sleep(0.8)
                        self.click(*START, note="start")
                    time.sleep(1.0)
                    continue
                if phase == "hero_select":
                    self.do_hero(st)
                    time.sleep(0.4)
                    continue
                if st.get("choices"):
                    self.do_choice(st)
                    time.sleep(0.3)
                    continue
                if phase == "recruit":
                    if self._settled_turn == turn:
                        time.sleep(1.0)
                        continue
                    if self.turn_actions >= self.max_actions_per_turn:
                        self.settle_screenshot(st, turn)
                        time.sleep(0.5)
                        continue
                    scores = self.action_scores(st)
                    self.log(kind="decision", turn=turn, **scores)
                    if (self._upgrade_turn != turn
                            and scores["upgrade"] >= max(scores["buy"], scores["play"],
                                                         scores["sell"], scores["refresh"])
                            and self.upgrade_tavern(st)):
                        self._upgrade_turn = turn
                        self.fail_streak = 0
                        continue
                    if (scores["refresh"] >= max(scores["buy"], scores["play"],
                                                 scores["sell"], scores["upgrade"])
                            and self.refresh_shop(st)):
                        self.fail_streak = 0
                        continue
                    if self.buy_shop(st):
                        self.fail_streak = 0
                        continue
                    if self.play_hand(st):
                        self.fail_streak = 0
                        continue
                    if self.sell_board(st):
                        self.fail_streak = 0
                        continue
                    if self._upgrade_turn != turn and self.upgrade_tavern(st):
                        self._upgrade_turn = turn
                        self.fail_streak = 0
                        continue
                    if self.refresh_shop(st):
                        self.fail_streak = 0
                        continue
                    self.fail_streak += 1
                    if self.fail_streak >= 3:
                        self.settle_screenshot(st, turn)
                    time.sleep(min(2.0, 0.4 + 0.3 * self.fail_streak))
                    continue
                time.sleep(0.5)
        except KeyboardInterrupt:
            result["interrupted"] = True
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            result["error"] = f"{type(exc).__name__}: {exc}"
            self.screenshot("fatal")
        finally:
            result.update({"actions": self.actions, "errors": self.errors,
                           "games_done": self.games_done,
                           "elapsed_s": round(time.time() - t0, 1)})
            (self.out_dir / "summary.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            self.close()
        return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="runs/live/clickbot_auto")
    ap.add_argument("--games", type=int, default=0, help="0=无限")
    ap.add_argument("--max-seconds", type=float, default=0)
    ap.add_argument("--max-actions-per-turn", type=int, default=30)
    ap.add_argument("--auto-launch", action="store_true", default=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    bot = ClickBot(Path(args.out_dir), dry_run=args.dry_run,
                   max_actions_per_turn=args.max_actions_per_turn,
                   games=args.games, max_seconds=args.max_seconds,
                   auto_launch=args.auto_launch)
    res = bot.run()
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
