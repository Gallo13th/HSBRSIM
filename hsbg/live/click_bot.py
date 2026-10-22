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
# 2026-10-22 实测：炉石 37.0 new UI（1600x900 client，窗口 160,101,1760,1001）。
# 证据：runs/live/recon/*.png + runs/live/hero_after_confirm.png。
# 启动链
MENU_BATTLEGROUNDS = (0.500, 0.378)   # 主菜单「酒馆战棋」（实测截图 current_screen.png）
LOBBY_START_POINTS = [(0.759, 0.778), (0.7172, 0.803)]  # 酒馆大厅「开始」
RESULT_POINTS = [(0.5393, 0.8492), (0.50, 0.86), (0.50, 0.50), (0.78, 0.92)]
# 英雄选择：实测 4 张卡中心 + 底部「确认」（未选英雄时灰显，点击无效）
HERO_OPTIONS = [(0.2406, 0.478), (0.4094, 0.478),
                (0.5719, 0.478), (0.7406, 0.478)]
HERO_CONFIRM = (0.500, 0.789)         # 旧坐标 (0.544,0.622) 不是确认按钮
# 对局内按钮（hover tooltip / 状态验证，见 runs/live/recon/hover_batch1_*.png）
UPGRADE_BTN = (0.406, 0.144)          # 顶部左：升级酒馆（费用徽标）
REROLL_BTN = (0.572, 0.156)           # 顶部右：刷新（tooltip=刷新）
FREEZE_BTN = (0.6375, 0.133)          # 顶部最右：冻结/解冻（tooltip=冻结）
HERO_POWER_BTN = (0.5875, 0.767)      # 底部英雄技能圆钮（tooltip=技能名）
DARK_GIFT_BTN = (0.8375, 0.264)       # 右侧「黑暗发现」按钮（T3 起可用，3 费）
START_COMBAT_BTN = (0.8125, 0.461)    # 右侧「开始战斗」（战斗过渡，通常自动推进）
BOB_PORTRAIT = (0.50, 0.145)          # 拖随从到这里卖出
# 卡牌行布局（1600x900；new UI 卡片居中排布，按格数自适应间距）
SHOP_Y = 0.372
SHOP_CENTER = 0.500
SHOP_SPACING = 0.0775                 # <=4 格实测 ~123px/1600
SHOP_SPACING_TIGHT = 0.0688           # >=5 格 ~110px
BOARD_Y = 0.545
BOARD_CENTER = 0.500
BOARD_SPACING = 0.0775
BOARD_SPACING_TIGHT = 0.0688
HAND_Y = 0.930
HAND_CENTER = 0.465
HAND_SPACING = 0.0625
HAND_SPACING_TIGHT = 0.048
# 选择/确认（discover 三选一 vs 饰品商店四选一）
CHOICE_Y = 0.444
CHOICE_SPACING = 0.19
TRINKET_Y = 0.400
TRINKET_CENTER = 0.510
TRINKET_SPACING = 0.148
CHOICE_CONFIRM = (0.500, 0.713)
CHOICE_HIDE = (0.275, 0.790)
# Choose One 法术弹层：两张选项卡中心（实测 runs/live/live_20261022_2352_bot37_v2/
# screenshots/actions/235336_a0021_drag_play_spell_BG31_880-_board_0_.png）
CHOOSE_ONE_OPTIONS = [(0.406, 0.489), (0.631, 0.489)]


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
    exercise_actions: bool = False   # 前几回合各演练一次新动作（证据用）
    start_timeout: float = 240.0     # 自动进入对局的最长等待（秒）
    recruit_settle_s: float = 7.0    # 入局动画（对手 VS/英雄弧）等待，期间点击无效
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
    _end_turn_turn: int = -1
    _hero_attempts: int = 0
    _started_game: bool = False
    _recruit_ready_at: float = 0.0

    def __post_init__(self):
        self.out_dir = Path(self.out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "screenshots").mkdir(exist_ok=True)
        (self.out_dir / "diagnostics").mkdir(exist_ok=True)
        self._rec = open(self.out_dir / "actions.jsonl", "a", encoding="utf-8")
        self.failed: Set[str] = set()
        self._fail_counts: Dict[str, int] = {}
        self._diag_keys: Set[str] = set()
        #: --exercise-actions 演练记录 action -> 成功次数
        self._exercised: Dict[str, int] = {}
        #: 本回合每张手牌打出尝试次数（防止脏帧误判成功导致同卡重复点击）
        self._played_this_turn: Dict[str, int] = {}
        #: 选择弹层失败标记（同一回合不再重复尝试）
        self._choice_fail_turn: int = -1
        self._t_start = 0.0
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

    def press_escape(self) -> None:
        if self.dry_run:
            return
        self._focus()
        try:
            self.backend.key(0x1B)
            self.actions += 1
            self.log(kind="key", key="ESC", note="dismiss_popup")
        except Exception:
            pass

    def cancel_targeting(self) -> None:
        """右键取消“正在选择目标/已选中卡牌”的 UI 状态（HS 标准取消键）。

        目标法术拖到空处失败后，客户端会停在 targeting 模式；不取消的话后续
        买/打/点按钮都会被解释成“选目标”，整回合动作全部失效。
        """
        if self.dry_run:
            return
        self._focus()
        try:
            x, y = self._pt(0.5, 0.06)   # 顶部空白处（避免点到按钮/卡牌）
            self.backend.click(x, y, button="right")
            self.log(kind="cancel_targeting", note="right_click")
        except Exception:
            pass

    def park_mouse(self) -> None:
        """把鼠标移回顶部空白处。

        买牌拖到手上后鼠标会停在手牌上，客户端会弹出手牌放大预览（约覆盖屏幕
        中央 y≈0.33-0.87）；下一次点击商店会被预览层挡住 → 购买/点击失效。
        每个动作成功后 park 一次即可避免。
        """
        if self.dry_run:
            return
        try:
            x, y = self._pt(0.5, 0.06)
            self.backend.move(x, y)
        except Exception:
            pass

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

    @staticmethod
    def _frozen_flags(st: Dict[str, Any]) -> Tuple[bool, ...]:
        return tuple(bool(m.get("frozen")) for m in (st.get("shop") or []))

    @staticmethod
    def _frozen_count(st: Dict[str, Any]) -> int:
        return sum(1 for flag in ClickBot._frozen_flags(st) if flag)

    @staticmethod
    def _legal_flags(st: Dict[str, Any]) -> Dict[str, Any]:
        """把 legal 压成统计用的短标记（多局长跑复盘：动作可得性统计）。"""
        legal = st.get("legal") or {}
        play = legal.get("play") or {}
        modes = 0
        try:
            for entry in play.values():
                modes += len(((entry or {}).get("use") or {}).get("modes") or [])
        except Exception:
            modes = -1
        return {
            "end": bool(legal.get("end")),
            "refresh": bool(legal.get("refresh")),
            "freeze": bool(legal.get("freeze")),
            "upgrade": bool(legal.get("upgrade")),
            "dark_gift": bool(legal.get("dark_gift")),
            "powers": len(legal.get("powers") or {}),
            "activate": len(legal.get("activate") or {}),
            "play": len(play or {}),
            "play_modes": modes,
            "choose": len(legal.get("choose") or ()),
        }

    def _sig(self, st: Dict[str, Any]) -> Tuple:
        return (st.get("phase"), st.get("turn"), len(st.get("hand") or []),
                len(st.get("board") or []), len(st.get("shop") or []),
                tuple(c.get("eid") for c in (st.get("choices") or [])),
                int(st.get("gold") or 0),
                tuple((m.get("card"), int(m.get("atk") or 0),
                       int(m.get("hp") or 0)) for m in (st.get("board") or [])),
                tuple((m.get("card"), m.get("kind")) for m in (st.get("hand") or [])),
                self._frozen_flags(st))

    def _changed(self, before: Tuple, timeout: float = 3.0) -> bool:
        """状态变化必须连续两帧一致才确认（过滤战斗/切回合脏帧的瞬态抖动）。

        实测：内存状态在战斗过渡/切回合时会出现 1 帧的 hand/board 抖动；
        旧实现只比较一次，会把脏帧当成“动作成功”，导致同一张不可用法术
        每轮重复点击（run live_20261023_0029_games3_fix 的 BG36_520t 循环）。
        """
        deadline = time.time() + timeout
        prev = None
        while time.time() < deadline:
            time.sleep(0.18)
            sig = self._sig(self.state())
            if sig == before:
                prev = None
                continue
            if prev is not None and sig == prev:
                return True
            prev = sig
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
    def _choice_layouts(self, n: int, pending: str) -> List[List[Tuple[float, float]]]:
        """选择弹层候选布局（37.0 new UI 实测 + 未校准布局兜底）。

        - discover / 黑暗之赐三选一：3 张大卡 y≈0.444，间距 0.19，直接点击即选中；
        - 饰品商店：4 张饰品卡 y≈0.40，间距 0.148，点卡后还需点「确认」；
        - 5+ 选（三连奖励/巨型发现）：先按 discover 紧凑行试，再按饰品双行试，
          都不行就点「隐藏」并且本回合不再重试（避免像 run 0034 turn8 那样卡住）。
        """
        outs: List[List[Tuple[float, float]]] = []
        if n <= 3:
            outs.append(_center(n, CHOICE_SPACING, CHOICE_Y))
        elif n == 4:
            outs.append(_center(n, TRINKET_SPACING, TRINKET_Y, TRINKET_CENTER))
        else:
            outs.append(_center(n, 0.155, CHOICE_Y, 0.5))
            outs.append(_center(n, 0.135, TRINKET_Y, 0.51))
        return [pts for pts in outs if pts]

    @staticmethod
    def _choice_is_stale(st: Dict[str, Any]) -> bool:
        """choices 非空但 legal.choose 为空 = 战斗/切回合滞后帧，禁止盲点。"""
        if not (st.get("choices") or []):
            return False
        legal = st.get("legal") or {}
        return not (legal.get("choose") or ())

    def do_choice(self, st: Dict[str, Any]) -> bool:
        choices = st.get("choices") or []
        if not choices:
            return False
        if self._choice_is_stale(st):
            self.log(kind="stale_choice_ignored", n=len(choices),
                     turn=st.get("turn"), phase=st.get("phase"))
            return False
        pending = str(st.get("pending") or "")
        clicks = 0
        for pts in self._choice_layouts(len(choices), pending):
            for idx, pt in enumerate(pts):
                key = f"choose:{idx}"
                card = (choices[idx] or {}).get("card") if idx < len(choices) else ""
                if key in self.failed and len(self._choice_layouts(len(choices), pending)) == 1:
                    continue
                before = self._sig(st)
                self.click(*pt, note=f"choose[{idx}]:{card}")
                clicks += 1
                time.sleep(0.6)
                now = self.state()
                if not (now.get("choices") or []):
                    self.turn_actions += 1
                    return True
                # 饰品商店/部分发现需要点「确认」
                self.click(*CHOICE_CONFIRM, note="choice_confirm")
                clicks += 1
                time.sleep(0.6)
                now = self.state()
                if not (now.get("choices") or []):
                    self.turn_actions += 1
                    return True
                if self._sig(now) != before:
                    # 选中态变化（如高亮/价格刷新）仍算推进，继续尝试下一个布局
                    break
                if clicks >= 10:
                    break
            if clicks >= 10:
                break
        # 兜底：点「隐藏」把弹层收掉（选择保留为 pending，避免阻塞招募）
        self.click(*CHOICE_HIDE, note="choice_hide")
        time.sleep(0.5)
        now = self.state()
        if not (now.get("choices") or []):
            self.turn_actions += 1
            return True
        self._choice_fail_turn = int(st.get("turn") or 0)
        self.log(kind="choice_layout_unknown", n=len(choices), pending=pending,
                 choices=[c.get("card") for c in choices[:6]],
                 screenshot=self.screenshot("choice_layout_unknown"))
        self._fail("choice", st, "choices 未消失")
        return False

    def do_hero(self, st: Dict[str, Any]) -> bool:
        """英雄选择：先点一张解锁的英雄卡，再点底部「确认」。

        1600x900 实测（runs/live/hero_after_confirm.png）：
        - 4 张英雄卡中心 x=0.2406/0.4094/0.5719/0.7406, y=0.478；
        - 「确认」在 (0.500,0.789)：未选英雄时按钮灰显，点击无效；
        - 旧坐标 (0.544,0.622) 落在英雄卡上而不是确认按钮。
        """
        if str(st.get("phase") or "") != "hero_select":
            return False
        self._hero_attempts += 1
        order = [1, 2, 0, 3]  # 实测解锁位多在中间两张，先点中间
        for idx in order:
            key = f"hero_option:{idx}"
            if key in self.failed:
                continue
            self.click(*HERO_OPTIONS[idx], note="hero_option")
            time.sleep(0.45)
            st1 = self.state()
            if str(st1.get("phase") or "") != "hero_select":
                self.log(kind="hero_selected", option=idx, phase=st1.get("phase"),
                         screenshot=self.screenshot("hero_selected"))
                return True
            self.click(*HERO_CONFIRM, note="hero_confirm")
            time.sleep(0.9)
            st2 = self.state()
            if str(st2.get("phase") or "") != "hero_select":
                self.log(kind="hero_selected", option=idx, phase=st2.get("phase"),
                         screenshot=self.screenshot("hero_selected"))
                return True
            # 选中但确认无效（未选中/灰显）→ 记录后换下一张
            self.log(kind="hero_confirm_no_effect", option=idx,
                     n_choices=len(st2.get("choices") or []),
                     screenshot=self.screenshot("hero_confirm_no_effect"))
        self._fail("hero_select", st, "英雄选择未推进")
        self.screenshot("hero_select_failed")
        return False

    def _hand_pts(self, n: int):
        # 实测：1-2 张间距约 100px(0.0625)，5 张起 fan 收紧，7 张约 72px(0.045)
        spacing = HAND_SPACING if n <= 5 else max(
            HAND_SPACING_TIGHT, HAND_SPACING - 0.0055 * (n - 5))
        return _center(n, spacing, HAND_Y, HAND_CENTER)

    def _board_pts(self, n: int):
        spacing = BOARD_SPACING if n <= 6 else BOARD_SPACING_TIGHT
        return _center(n, spacing, BOARD_Y, BOARD_CENTER)

    def _shop_pts(self, n: int):
        spacing = SHOP_SPACING if n <= 4 else SHOP_SPACING_TIGHT
        return _center(n, spacing, SHOP_Y, SHOP_CENTER)

    def _point_for(self, zone: str, index: int,
                   st: Dict[str, Any]) -> Optional[Tuple[float, float]]:
        """zone+index → 点坐标（用于目标选择/激活）。"""
        zone = str(zone or "board")
        if zone == "shop":
            pts = self._shop_pts(len(st.get("shop") or []))
        elif zone == "hand":
            pts = self._hand_pts(len(st.get("hand") or []))
        elif zone == "board":
            pts = self._board_pts(len(st.get("board") or []))
        else:
            pts = []
        if not pts:
            return None
        return pts[min(max(int(index), 0), len(pts) - 1)]

    def _click_targets(self, st: Dict[str, Any], targets: List[Dict[str, Any]],
                       note_prefix: str) -> bool:
        """按 legal target（zone+index）点击；只要观测到状态变化即成功。"""
        before = self._sig(st)
        for t in (targets or [])[:4]:
            zone = str(t.get("zone") or "board")
            idx = int(t.get("index") or 0)
            pt = self._point_for(zone, idx, st)
            if pt is None:
                continue
            self.click(*pt, note=f"{note_prefix}:{zone}[{idx}]")
            time.sleep(0.45)
            if self._sig(self.state()) != before:
                return True
        return False

    def _resolve_choose_one(self, before: Tuple) -> bool:
        """Choose One 弹层：点左/右选项，稳定状态变化才算成功。"""
        for pt in CHOOSE_ONE_OPTIONS:
            self.click(*pt, note="choose_one")
            time.sleep(0.45)
            if self._changed_stable(before, timeout=1.6):
                return True
        return False

    def _changed_stable(self, before: Tuple, timeout: float = 1.6) -> bool:
        """轻量版 _changed：稳定两帧才返回 True。"""
        return self._changed(before, timeout=timeout)

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
        """把买/打/卖/升级/刷新/技能/黑暗之赐都当成候选动作打分。

        键名与 :class:`hsbg.env.spec.ActionKind` 的 value 对齐
        （buy/play/sell/upgrade/reroll/hero_power/activate/use_dark_gift/freeze），
        日志 note 使用同一词表。
        """
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
        reroll = 0.0
        if legal.get("refresh") and gold >= 1:
            reroll = 50.0
            if not shop:
                reroll += 60.0
            if not affordable:
                reroll += 25.0
            if len(board) >= 7:
                reroll += 10.0
            # 搜索预算：同一回合每多刷一次，期望收益递减
            reroll -= 30.0 * self._refresh_count_turn
        # 黑暗之赐：S14 新机制，3 费换一个带赐福的随从，通常强于刷新
        dark_gift = 0.0
        if legal.get("dark_gift") and self._exercised.get("use_dark_gift", 0) == 0:
            dark_gift = 145.0 if gold >= 3 else 0.0
        # 英雄技能：有合法目标且付得起时是正收益动作
        hero_power = 0.0
        powers = legal.get("powers") or {}
        if powers and gold >= 1:
            hero_power = 72.0
            if self.exercise_actions and not self._exercised.get("hero_power"):
                hero_power += 60.0
        # 随从 Activate（发动）技能：1 费换 +3/+3 等，强于刷新/买普通随从
        activate = 95.0 if (legal.get("activate") or {}) else 0.0
        # 冻结：只在 --exercise-actions 时主动演练（自然策略下容易误冻好店）
        freeze = 0.0
        if legal.get("freeze") and self.exercise_actions and not self._exercised.get("freeze"):
            freeze = 135.0
        return {"buy": 0.0 if hand_full else 80.0 + best_buy,
                "play": 60.0 + best_play, "sell": sell, "upgrade": upgrade,
                "reroll": reroll, "use_dark_gift": dark_gift,
                "hero_power": hero_power, "activate": activate, "freeze": freeze}

    def refresh_shop(self, st: Dict[str, Any]) -> bool:
        """刷新（env ActionKind.REROLL）；成功可连续刷新，失败则本回合不再点。"""
        if self._refresh_failed_turn == int(st.get("turn") or 0):
            return False
        if not ((st.get("legal") or {}).get("refresh")):
            return False
        gold0 = int(st.get("gold") or 0)
        shop0 = tuple(m.get("card") for m in (st.get("shop") or []))
        before = self._sig(st)
        for pt in (REROLL_BTN,):
            self.click(*pt, note="reroll")
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
        """打出手牌（env ActionKind.PLAY_MINION / PLAY_SPELL）。

        note 词表与 ActionKind 对齐：``play_minion:<card>`` / ``play_spell:<card>``；
        带目标时写成 ``play_spell:<card>-><zone>[<index>]``。
        """
        hand = st.get("hand") or []
        board = st.get("board") or []
        legal_play = (st.get("legal") or {}).get("play") or {}
        if not hand:
            return False
        hand_pts = self._hand_pts(len(hand))
        board_pts = self._board_pts(max(1, len(board) + 1))
        drop_pt = (0.50, 0.560)  # 棋盘中央落点（实测出牌成功）
        for idx, m in enumerate(hand):
            kind = str(m.get("kind") or "")
            if kind not in ("minion", "spell"):
                continue
            if kind == "minion" and len(board) >= 7:
                continue
            key = f"play:{m.get('eid')}:{m.get('card')}"
            attempts = self._played_this_turn.get(key, 0)
            if key in self.failed or attempts >= 2:
                continue
            # 主拖占 1 次预算；minion 允许 1 次 ±0.03 兜底 = 每牌每回合最多 2 次拖拽
            budget = 2 - attempts
            self._played_this_turn[key] = attempts + budget
            entry = legal_play.get(str(idx))
            if legal_play and entry is None:
                continue
            targets = []
            modes: List[Any] = []
            if isinstance(entry, dict):
                use = entry.get("use") or {}
                targets = (use.get("targets") or [])
                modes = (use.get("modes") or [])
            before = self._sig(st)
            target_dest = None
            if kind == "spell":
                if targets:
                    t = targets[0]
                    zone = str(t.get("zone") or "board")
                    ti = int(t.get("index") or 0)
                    target_dest = self._point_for(zone, ti, st) or drop_pt
                    # 目标法术：优先拖拽到目标（更接近正常操作）
                    self.drag(hand_pts[idx], target_dest, duration=0.50,
                              note=f"play_spell:{m.get('card')}->{zone}[{ti}]")
                    time.sleep(0.45)
                    if self._sig(self.state()) != before:
                        self.turn_actions += 1
                        return True
                    # 拖拽失败再尝试点选手牌 + 点目标（目标坐标全部兜底）
                    self.click(*hand_pts[idx], note=f"select:{m.get('card')}")
                    time.sleep(0.30)
                    cand_pts = [target_dest]
                    if zone == "board" and board:
                        for p in self._board_pts(len(board)):
                            if p != target_dest:
                                cand_pts.append(p)
                    for p in cand_pts:
                        self.click(*p, note=f"target:{zone}[{ti}]")
                        time.sleep(0.30)
                        if self._sig(self.state()) != before:
                            self.turn_actions += 1
                            return True
                elif modes:
                    # Choose One + 需要目标：直接走后面的两段式（拖到目标→选模式）
                    pass
                else:
                    # 无目标法术：拖到棋盘中央施放
                    self.drag(hand_pts[idx], drop_pt, duration=0.42,
                              note=f"play_spell:{m.get('card')}")
            else:
                self.drag(hand_pts[idx],
                          board_pts[min(len(board), len(board_pts) - 1)],
                          duration=0.42, note=f"play_minion:{m.get('card')}")
            if not (kind == "spell" and modes):
                if self._changed(before):
                    self.turn_actions += 1
                    return True
            if kind == "minion":
                # 手牌 >5 张时 fan 布局间距收紧，按理论点可能落在卡缝里：
                # 换 ±0.03 的手牌落点重试（预算内仅 1 次；每次失败约 3s，仅失败时触发）。
                board_dest = board_pts[min(len(board), len(board_pts) - 1)]
                alt_offsets = (0.03, -0.03) if budget >= 2 else ()
                for dx in alt_offsets:
                    alt_x = min(0.94, max(0.06, hand_pts[idx][0] + dx))
                    self.drag((alt_x, hand_pts[idx][1]), board_dest,
                              duration=0.42, note=f"play_minion:{m.get('card')}")
                    if self._changed(before):
                        self.turn_actions += 1
                        return True
            if kind == "spell" and target_dest is not None:
                # 点选失败时退回拖拽到目标
                self.drag(hand_pts[idx], target_dest, duration=0.45,
                          note=f"play_spell:{m.get('card')}->target")
                if self._changed(before):
                    self.turn_actions += 1
                    return True
            if kind == "spell" and modes:
                # Choose One + 需要目标（例如 BG31_880 Alliance Flag）。
                # 实测交互（run4 截图 235336/235340）：
                #   1) 把法术拖到合法随从目标上 → 弹出 Choose One 两张选项卡；
                #   2) 点左/右选项 → 进入选择目标状态；
                #   3) 再点目标随从 → 结算。
                mode_targets = []
                for mi, mode in enumerate(modes[:2]):
                    for t in list(mode or []):
                        mode_targets.append((mi, t))
                for mi, t in mode_targets[:3]:
                    zone = str(t.get("zone") or "board")
                    ti = int(t.get("index") or 0)
                    pt = self._point_for(zone, ti, st)
                    if pt is None:
                        continue
                    self.drag(hand_pts[idx], pt, duration=0.50,
                              note=f"play_spell:{m.get('card')}->{zone}[{ti}]")
                    time.sleep(0.5)
                    if self._changed_stable(before, timeout=1.6):
                        self.turn_actions += 1
                        return True
                    for opt_pt in CHOOSE_ONE_OPTIONS:
                        self.click(*opt_pt, note="choose_one")
                        time.sleep(0.4)
                        # 选项后进入选目标：点回目标随从结算
                        self.click(*pt, note=f"target:{zone}[{ti}]")
                        time.sleep(0.4)
                        if self._changed_stable(before, timeout=1.6):
                            self.turn_actions += 1
                            return True
                    self.cancel_targeting()
            if kind == "spell" and self._resolve_choose_one(before):
                self.turn_actions += 1
                return True
            if kind == "spell":
                # 目标法术失败后客户端会停在 targeting 模式：右键取消，
                # 否则同一回合后续买/打/点按钮都会被解释成“选目标”。
                self.cancel_targeting()
            self._fail(key, st, "打出后状态未变化")
        return False

    # ------------------------------------------------------------ live-only actions
    def freeze_shop(self, st: Dict[str, Any]) -> bool:
        """冻结/解冻酒馆（env ActionKind.FREEZE）。

        客户端顶部雪花按钮 (0.6375,0.133)；验证 ``shop[*].frozen`` 翻转。
        客户端是同键 toggle，服务端 legal.freeze 为当前是否可点。
        """
        legal = st.get("legal") or {}
        if not legal.get("freeze"):
            return False
        key = "freeze"
        if key in self.failed:
            return False
        before_flags = self._frozen_flags(st)
        before = self._sig(st)
        self.click(*FREEZE_BTN, note="freeze")
        time.sleep(0.8)
        now = self.state()
        if self._frozen_flags(now) != before_flags or self._sig(now) != before:
            self.turn_actions += 1
            self._exercised["freeze"] = self._exercised.get("freeze", 0) + 1
            return True
        self._fail(key, st, "冻结后 shop[*].frozen 未变化")
        return False

    def use_hero_power(self, st: Dict[str, Any]) -> bool:
        """使用英雄技能（env ActionKind.HERO_POWER，可带目标）。

        底部圆钮 (0.5875,0.767)；目标来自 ``legal.powers[<idx>].targets``
        （zone=shop/board/hand + index），逐个尝试并做状态验证。
        """
        legal = st.get("legal") or {}
        powers = legal.get("powers") or {}
        if not powers:
            return False
        powers_list = st.get("powers") or []
        for key in sorted(powers, key=lambda k: int(k) if str(k).isdigit() else 0):
            info = powers.get(key) or {}
            if info.get("valid") is False:
                continue
            idx = int(key) if str(key).isdigit() else 0
            card = ""
            if idx < len(powers_list):
                card = str(powers_list[idx].get("card")
                           or powers_list[idx].get("name") or idx)
            note_key = f"hero_power:{card}"
            if note_key in self.failed:
                continue
            before = self._sig(st)
            self.click(*HERO_POWER_BTN, note=f"hero_power:{card}")
            time.sleep(0.7)
            st1 = self.state()
            targets = info.get("targets") or []
            new_powers = (st1.get("legal") or {}).get("powers") or {}
            if new_powers:
                info2 = new_powers.get(key) or {}
                if info2.get("targets"):
                    targets = info2["targets"]
            if targets and self._click_targets(st1, targets,
                                              note_prefix="hero_power_target"):
                self.turn_actions += 1
                self._exercised["hero_power"] = self._exercised.get("hero_power", 0) + 1
                return True
            if self._sig(self.state()) != before:
                self.turn_actions += 1
                self._exercised["hero_power"] = self._exercised.get("hero_power", 0) + 1
                return True
            self._fail(note_key, st, "英雄技能后状态未变化")
        return False

    def activate_minion(self, st: Dict[str, Any]) -> bool:
        """发动随从 Activate 技能（env ActionKind.ACTIVATE）。

        ``legal.activate`` 的 key 可能是棋盘下标或 eid；值可能是
        ``{"targets": [{"zone","index"}]}``。点随从后按目标点击，做状态验证。
        """
        legal = st.get("legal") or {}
        activate = legal.get("activate") or {}
        if not activate:
            return False
        board = st.get("board") or []
        pts = self._board_pts(len(board))
        if not pts:
            return False
        for key, val in list(activate.items())[:4]:
            idx: Optional[int] = None
            try:
                k = int(key)
            except (TypeError, ValueError):
                k = None
            if k is not None and 0 <= k < len(board):
                idx = k
            elif k is not None:
                for i, m in enumerate(board):
                    if int(m.get("eid") or -1) == k:
                        idx = i
                        break
            if idx is None:
                continue
            card = str(board[idx].get("card") or "")
            note_key = f"activate:{card}"
            if note_key in self.failed:
                continue
            before = self._sig(st)
            self.click(*pts[idx], note=f"activate:{card}")
            time.sleep(0.7)
            st1 = self.state()
            targets: List[Dict[str, Any]] = []
            if isinstance(val, dict):
                targets = val.get("targets") or []
            if not targets:
                for p in ((st1.get("legal") or {}).get("activate") or {}).values():
                    if isinstance(p, dict) and p.get("targets"):
                        targets = p["targets"]
                        break
            if targets and self._click_targets(st1, targets,
                                              note_prefix="activate_target"):
                self.turn_actions += 1
                self._exercised["activate"] = self._exercised.get("activate", 0) + 1
                return True
            if self._sig(self.state()) != before:
                self.turn_actions += 1
                self._exercised["activate"] = self._exercised.get("activate", 0) + 1
                return True
            self._fail(note_key, st, "发动技能后状态未变化")
        return False

    def use_dark_gift(self, st: Dict[str, Any]) -> bool:
        """购买/触发黑暗之赐（env ActionKind.USE_DARK_GIFT）。

        右侧按钮 (0.8375,0.264)（T3 起 legal.dark_gift=true，3 费）；
        点击后应出现 ``choices`` 三选一（pending=discover），由 :meth:`do_choice` 结算。
        验证：choices 出现 / 金币下降 / 状态签名变化。
        """
        legal = st.get("legal") or {}
        if not legal.get("dark_gift"):
            return False
        key = "use_dark_gift"
        if key in self.failed:
            return False
        gold0 = int(st.get("gold") or 0)
        before = self._sig(st)
        self.click(*DARK_GIFT_BTN, note="use_dark_gift")
        time.sleep(1.0)
        now = self.state()
        if ((now.get("choices") or []) or int(now.get("gold") or 0) < gold0
                or self._sig(now) != before):
            self.turn_actions += 1
            self._exercised["use_dark_gift"] = self._exercised.get("use_dark_gift", 0) + 1
            return True
        self._fail(key, st, "黑暗之赐按钮未打开三选一")
        return False

    def end_turn(self, st: Dict[str, Any]) -> bool:
        """主动结束招募回合（env ActionKind.END_TURN）。

        酒馆战棋单人模式的客户端**没有**手动“结束回合”按钮（计时器自动结束）。
        因此这里只做“有按钮/快捷键才点 + 状态验证”：
        1) 尝试右侧「开始战斗/结束回合」按钮；
        2) 尝试快捷键 E；
        3) 都无效则只记一次 ``end_turn_unavailable``（note=end_turn:auto_timer），
           **不谎报成功**，等待计时器自动进入战斗。
        """
        legal = st.get("legal") or {}
        turn = int(st.get("turn") or 0)
        if not legal.get("end"):
            return False
        if self._end_turn_turn == turn:
            return False
        self._end_turn_turn = turn
        phase0 = str(st.get("phase") or "")
        self.click(*START_COMBAT_BTN, note="end_turn")
        time.sleep(0.8)
        now = self.state()
        if (str(now.get("phase") or "") != phase0
                or int(now.get("turn") or 0) != turn):
            self.turn_actions += 1
            self._exercised["end_turn"] = self._exercised.get("end_turn", 0) + 1
            return True
        try:
            self._focus()
            self.backend.key(0x45)  # E：标准“结束回合”快捷键（BG 单人无效）
            self.log(kind="key", key="E", note="end_turn")
        except Exception:
            pass
        time.sleep(0.8)
        now = self.state()
        if (str(now.get("phase") or "") != phase0
                or int(now.get("turn") or 0) != turn):
            self.turn_actions += 1
            self._exercised["end_turn"] = self._exercised.get("end_turn", 0) + 1
            return True
        self.log(kind="end_turn_unavailable", note="end_turn:auto_timer",
                 turn=turn, phase=phase0,
                 screenshot=self.screenshot("end_turn_auto"))
        return False

    # ------------------------------------------------------------ main loop
    def _enter_game(self, *, timeout_s: Optional[float] = None) -> bool:
        """全自动进入对局：结算/大厅/主菜单 → 酒馆战棋 → 开始 → 英雄选择。

        只在状态明确时点击（game_over / no_active_game / lobby / menu）；
        登录页/启动页（phase 为空）只截图等待，不点击，避免旧版在登录页乱点。
        返回 True = 已进入 hero_select/recruit。
        """
        timeout = float(self.start_timeout if timeout_s is None else timeout_s)
        deadline = time.time() + timeout
        last_click = 0.0
        last_shot = 0.0
        attempts = 0
        while time.time() < deadline:
            if (self.max_seconds and self._t_start
                    and time.time() - self._t_start > self.max_seconds):
                return False
            try:
                if self._window is None or not getattr(self._window, "client_rect", None):
                    self._connect()
            except Exception:
                pass
            st = self.state()
            phase = str(st.get("phase") or "")
            if phase in ("hero_select", "recruit"):
                self._started_game = True
                self._recruit_ready_at = 0.0
                self.log(kind="start_game_ok", phase=phase, turn=st.get("turn"),
                         attempts=attempts,
                         screenshot=self.screenshot("start_game_ok"))
                return True
            if phase == "game_over":
                for pt in RESULT_POINTS:
                    self.click(*pt, note="result_continue")
                    time.sleep(0.8)
                    if str(self.state().get("phase") or "") != "game_over":
                        break
                continue
            if phase in ("no_active_game", "lobby", "menu"):
                now = time.time()
                if now - last_click > 8.0:
                    last_click = now
                    attempts += 1
                    # 任务弹窗/游戏菜单可能挡住主菜单：ESC 两次收回
                    self.press_escape()
                    time.sleep(0.25)
                    self.press_escape()
                    time.sleep(0.4)
                    self.click(*MENU_BATTLEGROUNDS, note="menu_battlegrounds")
                    time.sleep(1.2)
                    if str(self.state().get("phase") or "") in ("hero_select", "recruit"):
                        continue
                    for pt in LOBBY_START_POINTS:
                        self.click(*pt, note="start")
                        time.sleep(1.2)
                        if str(self.state().get("phase") or "") not in (
                                "no_active_game", "lobby", "menu"):
                            break
                time.sleep(1.0)
                continue
            # phase 未知（登录页/启动页/内存未就绪）：只截图等待，不点击
            if time.time() - last_shot > 5.0:
                last_shot = time.time()
                self.log(kind="start_wait", phase=phase or "unknown",
                         screenshot=self.screenshot("start_wait"))
            time.sleep(1.5)
        self.log(kind="start_failed", timeout_s=timeout, attempts=attempts)
        self.screenshot("start_failed")
        return False

    def _decision_actions(self, st: Dict[str, Any]):
        """候选动作列表：(name, score, bound method)，按 ActionKind 语义命名。"""
        scores = self.action_scores(st)
        turn = int(st.get("turn") or 0)
        actions = [
            ("use_dark_gift", scores.get("use_dark_gift", 0.0), self.use_dark_gift),
            ("upgrade", scores.get("upgrade", 0.0) if self._upgrade_turn != turn else 0.0,
             self.upgrade_tavern),
            ("reroll", scores.get("reroll", 0.0), self.refresh_shop),
            ("buy", scores.get("buy", 0.0), self.buy_shop),
            ("play", scores.get("play", 0.0), self.play_hand),
            ("sell", scores.get("sell", 0.0), self.sell_board),
            ("hero_power", scores.get("hero_power", 0.0), self.use_hero_power),
            ("activate", scores.get("activate", 0.0), self.activate_minion),
            ("freeze", scores.get("freeze", 0.0), self.freeze_shop),
        ]
        return actions

    def run(self) -> Dict[str, Any]:
        t0 = time.time()
        self._t_start = t0
        result: Dict[str, Any] = {"started": datetime.now().isoformat(timespec="seconds")}
        try:
            if not self._connect():
                result["error"] = "no Hearthstone window"
                return result
            # 启动链：自动进入游戏（必要时自动拉起战网/客户端）
            if not self._enter_game():
                result["error"] = "could not enter game"
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
                        if self._window is None:
                            launch_hearthstone_via_battlenet(
                                log=lambda m: self.log(kind="launcher", msg=str(m)))
                    time.sleep(1.0)
                    continue
                self._unavailable = 0
                if phase == "recruit" and turn <= 1 and self._recruit_ready_at <= 0:
                    # 英雄选择后还有 6-8s 的对手 VS / 英雄弧入场动画，
                    # 这段时间内存已是 recruit 但点击全部无效。
                    self._recruit_ready_at = time.time() + self.recruit_settle_s
                    self.log(kind="recruit_settle", wait_s=self.recruit_settle_s,
                             screenshot=self.screenshot("recruit_settle"))
                if phase == "recruit" and time.time() < self._recruit_ready_at:
                    time.sleep(1.0)
                    continue
                if turn != self.last_turn:
                    self.last_turn = turn
                    self.turn_actions = 0
                    self.failed.clear()
                    self._refresh_count_turn = 0
                    self._turn_started_at = time.time()
                    self._last_board_count = -1
                    self._board_drop_count = 0
                    self._played_this_turn.clear()
                    time.sleep(0.8)
                self.log(kind="state", phase=phase, turn=turn,
                         gold=st.get("gold"), board=len(st.get("board") or []),
                         hand=len(st.get("hand") or []),
                         shop=len(st.get("shop") or []),
                         choices=[c.get("card") for c in (st.get("choices") or [])],
                         frozen=self._frozen_count(st),
                         legal=self._legal_flags(st))
                if phase in ("game_over", "result", "spectating"):
                    if not self._seen_game_over:
                        self._seen_game_over = True
                        self._recruit_ready_at = 0.0
                        self.games_done += 1
                        self.log(kind="game_over", rank=st.get("rank"),
                                 screenshot=self.screenshot("game_over"))
                    if self.games and self.games_done >= self.games:
                        break
                    # 自动开下一局：结算 → 大厅 → 酒馆战棋 → 开始
                    if not self._enter_game():
                        result["error"] = "could not start next game"
                        break
                    self._seen_game_over = False
                    self.last_turn = -1
                    continue
                if phase in ("no_active_game", "lobby", "menu"):
                    if not self._enter_game():
                        result["error"] = "could not start next game"
                        break
                    continue
                if phase == "hero_select":
                    self.do_hero(st)
                    time.sleep(0.4)
                    continue
                if st.get("choices"):
                    if self._choice_is_stale(st):
                        # 战斗/切回合滞后帧：choices 还在但 legal.choose 为空 → 不点
                        self.log(kind="stale_choice_ignored", n=len(st.get("choices") or []),
                                 turn=turn, phase=phase)
                        time.sleep(0.8)
                        continue
                    if self._choice_fail_turn == turn:
                        # 本回合已确认处理不了该弹层：不要每 2s 重复点
                        time.sleep(0.8)
                        continue
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
                    done = False
                    for name, score, fn in sorted(self._decision_actions(st),
                                                  key=lambda x: x[1], reverse=True):
                        if score <= 0:
                            continue
                        try:
                            ok = fn(st)
                        except Exception as exc:  # noqa: BLE001
                            self.log(kind="action_error", action=name,
                                     error=f"{type(exc).__name__}: {exc}")
                            ok = False
                        if ok:
                            if name == "upgrade":
                                self._upgrade_turn = turn
                            self.fail_streak = 0
                            done = True
                            break
                    if done:
                        # 动作后 UI 动画/行重排未完成时立刻下一步动作容易点空；
                        # 同时把手牌 hover 放大预览收掉，避免遮挡后续点击。
                        time.sleep(0.45)
                        self.park_mouse()
                        continue
                    # 动作耗尽：尝试主动结束回合（BG 单人无按钮 → 记 auto_timer）
                    self.end_turn(st)
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
                           "exercised": dict(self._exercised),
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
    ap.add_argument("--exercise-actions", action="store_true",
                    help="前几回合各演练一次 freeze/hero_power/activate/use_dark_gift/end_turn（证据用）")
    ap.add_argument("--start-timeout", type=float, default=240.0,
                    help="自动进入对局（含启动/登录/排队）最长等待秒数")
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
                   action_shots=not args.no_action_shots,
                   exercise_actions=args.exercise_actions,
                   start_timeout=args.start_timeout)
    res = bot.run()
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
