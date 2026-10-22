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
HERO_CONFIRM = (0.544, 0.622)
CHOICE_Y = 0.45
CHOICE_SPACING = 0.14
CHOICE_CONFIRM = (0.50, 0.66)
BOB_PORTRAIT = (0.50, 0.14)       # 拖随从到这里卖出
UPGRADE_BTN = (0.394, 0.145)      # 酒馆升级按钮（顶部左侧）
REFRESH_BTN = (0.60, 0.18)        # 刷新按钮（顶部右侧）
REFRESH_POINTS = [(0.60, 0.18)]
START_COMBAT = (0.81, 0.46)      # 战斗前“开始战斗”按钮
SHOP_Y = 0.34
SHOP_SPACING = 0.087
SHOP_CENTER = 0.555
BOARD_Y = 0.52
BOARD_SPACING = 0.087
BOARD_CENTER = 0.555
HAND_Y = 0.90
HAND_SPACING = 0.075
HAND_CENTER = 0.49
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
    safe_state: bool = True
    action_shots: bool = True
    _shot_seq: int = 0
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
    _refresh_count_turn: int = 0
    _turn_started_at: float = 0.0
    _diag_turn: int = -1
    _no_effect_turn: int = -1
    _no_effect_count: int = 0
    _last_board_count: int = -1
    _board_drop_count: int = 0
    _last_start_combat: float = 0.0

    def __post_init__(self):
        self.out_dir = Path(self.out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "screenshots").mkdir(exist_ok=True)
        (self.out_dir / "diagnostics").mkdir(exist_ok=True)
        self._rec = open(self.out_dir / "actions.jsonl", "a", encoding="utf-8")
        self.failed: Set[str] = set()
        self._fail_counts: Dict[str, int] = {}
        self._diag_keys: Set[str] = set()
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

    def screenshot(self, tag: str, subdir: Optional[str] = None) -> Optional[str]:
        try:
            from PIL import ImageGrab
            self._focus()
            w = self._window
            if w is None or not w.client_rect:
                return None
            l, t, r, b = w.client_rect
            base = self.out_dir / "screenshots"
            if subdir:
                base = base / subdir
                base.mkdir(parents=True, exist_ok=True)
            path = base / f"{datetime.now().strftime('%H%M%S')}_{tag}.png"
            ImageGrab.grab(bbox=(l, t, r, b)).save(path)
            return str(path)
        except Exception:
            return None

    def _action_shot(self, kind: str, note: str) -> None:
        if not self.action_shots:
            return
        self._shot_seq += 1
        safe = "".join(c if c.isalnum() or c in "_.-" else "_"
                       for c in note)[:50]
        tag = f"a{self._shot_seq:04d}_{kind}_{safe}"
        self.screenshot(tag, subdir="actions")

    def _focus(self) -> bool:
        try:
            h = getattr(self._window, "hwnd", None)
            if h:
                u = ctypes.windll.user32
                for _ in range(3):
                    u.ShowWindow(h, 9)
                    u.BringWindowToTop(h)
                    u.SetForegroundWindow(h)
                    try:
                        u.SwitchToThisWindow(h, True)
                    except Exception:
                        pass
                    time.sleep(0.12)
                    if u.GetForegroundWindow() == h:
                        return True
                self.log(kind="foreground_failed", hwnd=h,
                         foreground=u.GetForegroundWindow())
                return False
        except Exception:
            pass
        return True

    def click(self, fx: float, fy: float, note: str = "") -> None:
        if self.dry_run:
            self.log(kind="dry_click", fx=fx, fy=fy, note=note)
            return
        self._focus()
        self.backend.click(*self._pt(fx, fy))
        self.actions += 1
        self.log(kind="click", fx=fx, fy=fy, note=note)
        self._action_shot("click", note)

    def drag(self, a: Tuple[float, float], b: Tuple[float, float],
             duration: float = 0.40, note: str = "") -> None:
        if self.dry_run:
            self.log(kind="dry_drag", a=a, b=b, note=note)
            return
        self._focus()
        self.backend.drag([self._pt(*a), self._pt(*b)], duration=duration)
        self.actions += 1
        self.log(kind="drag", a=a, b=b, note=note)
        self._action_shot("drag", note)

    def state(self) -> Dict[str, Any]:
        if self.safe_state:
            import tempfile
            fd, path = tempfile.mkstemp(prefix="hs_state_", suffix=".json",
                                        dir=str(self.out_dir))
            import os
            os.close(fd)
            try:
                proc = subprocess.run(
                    [sys.executable, str(ROOT / "tools" / "live_state_mem.py"),
                     "--sample", path],
                    cwd=str(ROOT), capture_output=True, timeout=10)
                if proc.returncode == 0:
                    return json.loads(Path(path).read_text(encoding="utf-8"))
                self.log(kind="state_reader_failed", code=proc.returncode)
                return {}
            except Exception as exc:  # noqa: BLE001
                self.log(kind="state_reader_error", error=str(exc))
                return {}
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        try:
            return read_memory_state() or {}
        except Exception:
            return {}

    def _sig(self, st: Dict[str, Any]) -> Tuple:
        return (st.get("phase"), st.get("turn"), len(st.get("hand") or []),
                len(st.get("board") or []), len(st.get("shop") or []),
                tuple(c.get("eid") for c in (st.get("choices") or [])),
                int(st.get("gold") or 0),
                tuple((m.get("card"), int(m.get("atk") or 0),
                       int(m.get("hp") or 0)) for m in (st.get("board") or [])),
                tuple((m.get("card"), m.get("kind")) for m in (st.get("hand") or [])))

    def _changed(self, before: Tuple, timeout: float = 3.0) -> bool:
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

    def _diagnostic_burst(self, key: str, st: Dict[str, Any], note: str) -> None:
        """连续无变化时密集截图：前后帧 + 状态，便于异步复盘。"""
        import re
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", key)[:40]
        d = self.out_dir / "diagnostics" / (
            f"{datetime.now().strftime('%H%M%S')}_{safe}")
        d.mkdir(parents=True, exist_ok=True)
        frames = []
        states = []
        for i in range(5):
            frames.append(self.screenshot(f"diag_{safe}_{i}"))
            states.append(self.state())
            time.sleep(0.30)
        (d / "meta.json").write_text(json.dumps(
            {"key": key, "note": note, "frames": frames, "states": states},
            ensure_ascii=False, indent=1), encoding="utf-8")
        self.log(kind="repeat_failure_diag", key=key, note=note,
                 dir=str(d), frames=frames)

    def _fail(self, key: str, st: Dict[str, Any], note: str) -> None:
        turn = int(st.get("turn") or 0)
        if self._no_effect_turn != turn:
            self._no_effect_turn = turn
            self._no_effect_count = 0
        self._no_effect_count += 1
        if self._no_effect_count >= 2 and self._diag_turn != turn:
            self._diag_turn = turn
            self._diagnostic_burst(f"turn{turn}_noeffect{self._no_effect_count}",
                                   st, note)
        count = self._fail_counts.get(key, 0) + 1
        self._fail_counts[key] = count
        if count >= 2 and key not in self._diag_keys:
            self._diag_keys.add(key)
            self._diagnostic_burst(key, st, note)
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
        if not choices:
            return False
        pts = _center(len(choices), 0.20 if len(choices) <= 3 else 0.14, CHOICE_Y)
        for idx, pt in enumerate(pts):
            before = self._sig(st)
            self.click(*pt, note=f"choice[{idx}]:{choices[idx].get('card')}")
            time.sleep(0.45)
            now = self.state()
            if not (now.get("choices") or []):
                return True
            # 饰品商店等需要点“确认”
            self.click(*CHOICE_CONFIRM, note="choice_confirm")
            time.sleep(0.45)
            now = self.state()
            if not (now.get("choices") or []) or self._sig(now) != before:
                return True
        self._fail("choice", st, "choices 未消失")
        return False

    def do_hero(self, st: Dict[str, Any]) -> bool:
        # 已选英雄后：点底部“确认”（不是 start_combat）
        if len(st.get("choices") or []) < 4:
            before = self._sig(st)
            self.click(*HERO_CONFIRM, note="hero_confirm")
            time.sleep(0.6)
            return self._sig(self.state()) != before
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
        spacing = HAND_SPACING if n <= 5 else max(0.052, HAND_SPACING - 0.004 * (n - 5))
        return _center(n, spacing, HAND_Y, HAND_CENTER)

    def _board_pts(self, n: int):
        return _center(n, BOARD_SPACING, BOARD_Y, BOARD_CENTER)

    def _shop_pts(self, n: int):
        return _center(n, SHOP_SPACING, SHOP_Y, SHOP_CENTER)

    def _resolve_choose_one(self, before: Tuple) -> bool:
        """施放 Choose One 法术后的二选一弹层（内存 choices 可能为空）。"""
        for pt in ((0.44, 0.47), (0.56, 0.47)):
            self.click(*pt, note="choose_one")
            time.sleep(0.45)
            if self._sig(self.state()) != before:
                return True
        return False

    def sell_board(self, st: Dict[str, Any]) -> bool:
        """棋盘满且有手牌时，卖最弱随从腾格子（拖到 Bob 头像）。"""
        board = st.get("board") or []
        hand = st.get("hand") or []
        if not board or not hand or len(board) < 7:
            return False
        pts = self._board_pts(len(board))
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
        """legal.upgrade 时点顶部升级按钮并校验 tier。"""
        if not ((st.get("legal") or {}).get("upgrade")):
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
        hand_full = len(hand) >= 10
        sell = (100.0 if hand_full and len(board) >= 7
                else (30.0 if len(board) >= 7 and hand else 0.0))
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
            # 搜索预算：同一回合每多刷一次，期望收益递减
            refresh -= 30.0 * self._refresh_count_turn
        return {"buy": 0.0 if hand_full else 80.0 + best_buy, "play": 60.0 + best_play,
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
                self._refresh_count_turn += 1
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
        pts = self._shop_pts(len(shop))
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
        board_pts = self._board_pts(max(1, len(board) + 1))
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
            targets = []
            if isinstance(entry, dict):
                targets = ((entry.get("use") or {}).get("targets") or [])
            before = self._sig(st)
            target_dest = None
            if kind == "spell":
                if targets:
                    t = targets[0]
                    zone = str(t.get("zone") or "board")
                    ti = int(t.get("index") or 0)
                    if zone == "board" and board:
                        board_actual = self._board_pts(len(board))
                        dest = board_actual[min(ti, len(board_actual) - 1)]
                    elif zone == "shop":
                        shop_actual = self._shop_pts(max(1, len(st.get("shop") or [])))
                        dest = shop_actual[min(ti, len(shop_actual) - 1)]
                    else:
                        dest = (0.50, 0.52)
                    # 目标法术：先点手牌选中，再点目标随从
                    # 目标法术优先拖拽到目标（更接近正常操作）
                    self.drag(hand_pts[idx], dest, duration=0.50,
                              note=f"dragcast:{m.get('card')}->{zone}[{ti}]")
                    time.sleep(0.45)
                    if self._sig(self.state()) != before:
                        self.turn_actions += 1
                        return True
                    # 拖拽失败再尝试点选手牌 + 点目标
                    self.click(*hand_pts[idx], note=f"select:{m.get('card')}")
                    time.sleep(0.30)
                    # 先点目标，失败再依次尝试其它随从位置（坐标校准误差兜底）
                    cand_pts = [dest]
                    if zone == "board" and board:
                        for p in self._board_pts(len(board)):
                            if p != dest:
                                cand_pts.append(p)
                    for p in cand_pts:
                        self.click(*p, note=f"target:{zone}[{ti}]")
                        time.sleep(0.30)
                        if self._sig(self.state()) != before:
                            self.turn_actions += 1
                            return True
                    target_dest = dest
                else:
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
            if kind == "spell" and target_dest is not None:
                # 点选失败时退回拖拽到目标
                self.drag(hand_pts[idx], target_dest, duration=0.45,
                          note=f"cast:{m.get('card')}->target")
                if self._changed(before):
                    self.turn_actions += 1
                    return True
            if kind == "spell" and self._resolve_choose_one(before):
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
                    self._refresh_count_turn = 0
                    self._turn_started_at = time.time()
                    self._last_board_count = -1
                    self._board_drop_count = 0
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
                    bc = len(st.get("board") or [])
                    if not (st.get("shop") or []) and self._last_board_count > bc >= 0:
                        self._board_drop_count += 1
                    elif st.get("shop"):
                        self._board_drop_count = 0
                    self._last_board_count = bc
                    if self._board_drop_count >= 2:
                        self.log(kind="combat_wait", board=bc,
                                 shop=len(st.get("shop") or []))
                        time.sleep(1.5)
                        continue
                    # 过滤战斗/切回合脏帧，避免按错误长度算坐标
                    if (len(st.get("shop") or []) > 7 or len(st.get("board") or []) > 7
                            or len(st.get("hand") or []) > 10):
                        time.sleep(0.8)
                        continue
                    if not (st.get("shop") or []) and not (st.get("board") or []):
                        # 战斗/回合过渡帧：不按空棋盘乱点
                        time.sleep(1.0)
                        continue
                    if self.turn_actions >= self.max_actions_per_turn:
                        if time.time() - self._turn_started_at > 5:
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
                    if self.action_scores(st)["refresh"] > 40 and self.refresh_shop(st):
                        self.fail_streak = 0
                        continue
                    self.fail_streak += 1
                    if self.fail_streak >= 3 and self._diag_turn != turn:
                        self._diag_turn = turn
                        self._diagnostic_burst(f"turn{turn}_streak", st, "no_action_streak")
                    if self.fail_streak >= 3 and time.time() - self._turn_started_at > 5:
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
    import faulthandler
    faulthandler.enable()
    faulthandler.dump_traceback_later(30, repeat=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="runs/live/clickbot_auto")
    ap.add_argument("--games", type=int, default=0, help="0=无限")
    ap.add_argument("--max-seconds", type=float, default=0)
    ap.add_argument("--max-actions-per-turn", type=int, default=30)
    ap.add_argument("--auto-launch", action="store_true", default=True)
    ap.add_argument("--direct-state", action="store_true",
                    help="直接在进程内读内存（快但可能被 bgcontroller access violation 带崩）")
    ap.add_argument("--no-action-shots", action="store_true",
                    help="关闭每次操作的截图")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    bot = ClickBot(Path(args.out_dir), dry_run=args.dry_run,
                   max_actions_per_turn=args.max_actions_per_turn,
                   games=args.games, max_seconds=args.max_seconds,
                   auto_launch=args.auto_launch, safe_state=not args.direct_state,
                   action_shots=not args.no_action_shots)
    res = bot.run()
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
