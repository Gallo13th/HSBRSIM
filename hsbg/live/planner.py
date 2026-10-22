"""纯状态机：``LiveSnapshot (+ memory)`` → ``List[PlannedAction]``。

* 不碰 Win32 / 网络 / 日志 I/O，只做确定性决策，便于单元测试与 dry-run；
* 由 :class:`hsbg.live.runner.LiveBot` 负责把 ``PlannedAction`` 交给
  :class:`hsbg.live.wininput.InputController` 执行（dry-run 只打印）；
* 状态来源优先级：内存状态（memory，若有）> 日志 watcher（``LiveSnapshot``）
  > 盲操作（固定时间脚本，最后手段）。

阶段脚本
--------
* ``menu``/``lobby``：点「酒馆战棋」/「开始」（有限速率重试）
* ``hero_select``：点第 1 个英雄候选 → 等待 → 点确认（每局一次；失败重试换候选）
* ``recruit``：每回合一次脚本：商店 i 格 → 手牌（或棋盘）、手牌 i → 棋盘、
  （可选）英雄技能、结束回合（E 键或按钮）；分 tick 分片执行
* ``combat``：只等待
* ``choice``：点第一个选项 + 确认（每个选择事件一次）
* ``game_over``：截图 → 点「再来一局/返回大厅」→ 等下一局
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from hsbg.live.config import LiveConfig
from hsbg.live.logwatch import (
    LiveSnapshot,
    PHASE_CHOICE,
    PHASE_COMBAT,
    PHASE_GAME_OVER,
    PHASE_HERO_SELECT,
    PHASE_LOBBY,
    PHASE_MENU,
    PHASE_RECRUIT,
    PHASE_UNKNOWN,
)
from hsbg.live.memory_state import apply_memory


@dataclass
class PlannedAction:
    """一个待执行的 UI 动作（相对坐标；也支持 wait/key/screenshot）。"""

    kind: str  # click | drag | key | wait | screenshot | record
    name: str = ""
    x: Optional[float] = None
    y: Optional[float] = None
    x2: Optional[float] = None
    y2: Optional[float] = None
    duration: Optional[float] = None
    key: Optional[Union[int, str]] = None
    seconds: Optional[float] = None
    note: str = ""

    def format(self) -> str:
        if self.kind == "click":
            return f"click {self.name} ({self.x:.3f},{self.y:.3f})"
        if self.kind == "drag":
            dur = 0.0 if self.duration is None else float(self.duration)
            return (f"drag {self.name} ({self.x:.3f},{self.y:.3f})"
                    f"->({self.x2:.3f},{self.y2:.3f}) {dur:.2f}s")
        if self.kind == "key":
            return f"key {self.key} ({self.name})" if self.name else f"key {self.key}"
        if self.kind == "wait":
            sec = 0.0 if self.seconds is None else float(self.seconds)
            return f"wait {sec:.2f}s {self.name}".rstrip()
        if self.kind == "screenshot":
            return f"screenshot {self.name}".rstrip()
        return f"{self.kind} {self.name} {self.note}".rstrip()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "x2": self.x2,
            "y2": self.y2,
            "duration": self.duration,
            "key": self.key,
            "seconds": self.seconds,
            "note": self.note,
        }


class Planner:
    """把状态快照转换为有界、可重放的 UI 动作序列。

    关键设计
    --------
    * **每回合脚本只生成一次**（key = ``(game_id, turn)``），分 tick 执行；
      阶段变化（combat/choice/game_over）会丢弃未执行完的脚本，避免串台；
    * **有界动作数**（``safety.max_actions_per_turn``），并始终保证脚本里
      含有「结束回合」动作；
    * 所有速率限制（菜单重试、英雄重试、game over 处理一次）都在内部状态里，
      因此 ``plan()`` 可以每 0.25s 调用一次而不会疯狂点击。
    """

    def __init__(
        self,
        config: LiveConfig,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self._clock = clock
        self.reset()

    # ── 生命周期 ──
    def reset(self) -> None:
        self._turn_seq: List[PlannedAction] = []
        self._turn_seq_key: Optional[tuple] = None
        self._turn_drained_ts: float = 0.0
        self._end_turn_retries: int = 0
        self._hero_game: int = -1
        self._hero_attempt: int = 0
        self._hero_last_ts: float = 0.0
        self._choice_key: Optional[tuple] = None
        self._game_over_game: int = -1
        self._menu_ts: float = 0.0
        self._lobby_ts: float = 0.0
        self._last_phase: str = ""
        # 盲操作状态
        self._blind_game_started: float = 0.0
        self._blind_menu_clicked = False
        self._blind_lobby_clicked = False
        self._blind_hero_done = False
        self._blind_last_turn_ts = 0.0
        self._blind_games_completed = 0
        self._blind_turn = 0
        # 账本（调试/测试）
        self.actions_planned = 0
        self.phase_history: List[tuple] = []

    # ── 主入口 ──
    def plan(
        self,
        snapshot: Optional[LiveSnapshot],
        memory: Optional[Dict[str, Any]] = None,
        *,
        now: Optional[float] = None,
    ) -> List[PlannedAction]:
        """根据快照生成**下一步**要执行的动作列表（可能为空）。"""
        now = self._clock() if now is None else float(now)
        snap = apply_memory(snapshot, memory)
        if snap is None or (snap.phase == PHASE_UNKNOWN and not snap.in_game):
            return self._plan_blind(now)
        phase = snap.phase
        if phase != self._last_phase:
            self.phase_history.append((now, phase, int(snap.turn), int(snap.game_id)))
            self._last_phase = phase
        if phase not in (PHASE_RECRUIT,):
            self._turn_seq = []
            self._turn_seq_key = None
        if not snap.in_game and phase not in (PHASE_MENU, PHASE_LOBBY, PHASE_GAME_OVER):
            return self._plan_lobby_or_menu(phase, now)
        if phase in (PHASE_MENU, PHASE_LOBBY):
            return self._plan_lobby_or_menu(phase, now)
        if phase == PHASE_HERO_SELECT:
            return self._plan_hero(snap, now)
        if phase == PHASE_CHOICE:
            return self._plan_choice(snap, now)
        if phase == PHASE_RECRUIT:
            return self._plan_recruit(snap, now)
        if phase == PHASE_COMBAT:
            return []
        if phase == PHASE_GAME_OVER:
            return self._plan_game_over(snap, now)
        return []

    # ── 菜单 / 大厅 ──
    def _plan_lobby_or_menu(self, phase: str, now: float) -> List[PlannedAction]:
        retry = max(1.0, float(self.config.delays.menu_retry_s))
        if phase == PHASE_LOBBY:
            if now - self._lobby_ts < retry:
                return []
            self._lobby_ts = now
            x, y = self.config.coords.point("lobby_play")
            return [PlannedAction(kind="click", name="lobby_play", x=x, y=y,
                                  note="酒馆大厅开始按钮")]
        if now - self._menu_ts < retry:
            return []
        self._menu_ts = now
        x, y = self.config.coords.point("menu_battlegrounds")
        return [PlannedAction(kind="click", name="menu_battlegrounds", x=x, y=y,
                              note="主菜单→酒馆战棋")]

    # ── 英雄选择 ──
    def _plan_hero(self, snap: LiveSnapshot, now: float) -> List[PlannedAction]:
        options = self.config.coords.group("hero_options")
        if not options:
            return []
        retry = 8.0
        if snap.game_id == self._hero_game:
            if self._hero_attempt >= 3 or now - self._hero_last_ts < retry:
                return []
        else:
            self._hero_game = int(snap.game_id)
            self._hero_attempt = 0
        idx = min(
            int(self.config.flow.hero_option_index) + self._hero_attempt,
            len(options) - 1,
        )
        self._hero_attempt += 1
        self._hero_last_ts = now
        x, y = options[idx]
        cx, cy = self.config.coords.point("hero_confirm")
        wait_s = float(self.config.delays.hero_select_wait_s)
        return [
            PlannedAction(kind="click", name=f"hero_option_{idx}", x=x, y=y,
                          note="选择英雄"),
            PlannedAction(kind="wait", name="hero_wait", seconds=wait_s),
            PlannedAction(kind="click", name="hero_confirm", x=cx, y=cy,
                          note="确认英雄"),
            PlannedAction(kind="wait", name="hero_confirm_wait",
                          seconds=float(self.config.delays.after_click_s)),
        ]

    # ── 选择窗口（发现/三选一/任务）──
    def _plan_choice(self, snap: LiveSnapshot, now: float) -> List[PlannedAction]:
        options = self.config.coords.group("choice_options")
        if not options:
            return []
        key = (int(snap.game_id), int(snap.turn), int(snap.notes.get("choice_serial", 0) or 0))
        if key == self._choice_key:
            return []
        self._choice_key = key
        x, y = options[0]
        cx, cy = self.config.coords.point("choice_confirm")
        wait_s = float(self.config.delays.choice_wait_s)
        self._last_phase = PHASE_CHOICE
        return [
            PlannedAction(kind="click", name="choice_option_0", x=x, y=y,
                          note="选择第一个选项"),
            PlannedAction(kind="wait", name="choice_wait", seconds=wait_s),
            PlannedAction(kind="click", name="choice_confirm", x=cx, y=cy,
                          note="确认选择"),
            PlannedAction(kind="wait", name="choice_confirm_wait",
                          seconds=float(self.config.delays.after_click_s)),
        ]

    # ── 招募（每回合脚本，分 tick 执行）──
    def _plan_recruit(self, snap: LiveSnapshot, now: float) -> List[PlannedAction]:
        key = (int(snap.game_id), int(snap.turn))
        if key != self._turn_seq_key:
            self._turn_seq = self._build_recruit_sequence(snap)
            self._turn_seq_key = key
            self._turn_drained_ts = 0.0
            self._end_turn_retries = 0
        if not self._turn_seq:
            # 脚本执行完但回合没有推进：仅当配置为主动结束回合时才限量重试；
            # 酒馆战棋单人模式交给计时器自动结束（等待 turn/phase 变化）。
            if self._turn_drained_ts == 0.0:
                self._turn_drained_ts = now
            if (self.config.flow.send_end_turn
                    and now - self._turn_drained_ts > 30.0
                    and self._end_turn_retries < 5):
                self._end_turn_retries += 1
                self._turn_drained_ts = now
                return self._end_turn_retry_actions()
            return []
        cap = max(1, int(self.config.flow.max_actions_per_tick))
        chunk = self._turn_seq[:cap]
        self._turn_seq = self._turn_seq[cap:]
        self.actions_planned += len(chunk)
        return chunk

    def _end_turn_retry_actions(self) -> List[PlannedAction]:
        flow = self.config.flow
        delays = self.config.delays
        if flow.end_turn_use_key:
            act = PlannedAction(kind="key", name="end_turn_retry",
                                key=flow.end_turn_key, note="重试结束回合")
        else:
            ex, ey = self.config.coords.point("end_turn")
            act = PlannedAction(kind="click", name="end_turn_retry",
                                x=ex, y=ey, note="重试结束回合")
        return [act, PlannedAction(kind="wait", name="end_turn_retry_wait",
                                   seconds=float(delays.end_turn_wait_s))]

    def _memory_count(self, snap: LiveSnapshot, key: str, default: int) -> int:
        value = snap.notes.get(key)
        if isinstance(value, (list, tuple)):
            return len(value)
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def _layout_positions(self, group: str, count: Optional[int] = None) -> List[Tuple[float, float]]:
        """按实机校准的动态布局生成卡牌行坐标（BG 卡牌按"当前格数"居中排布）。"""
        layout = getattr(self.config.coords, "layout", {}) or {}
        center = float(layout.get("center_x", 0.5))
        if group == "shop":
            y = float(layout.get("shop_y", 0.356))
            spacing = float(layout.get("shop_spacing", 0.068229))
            default_n = len(self.config.coords.group("shop"))
            max_n = 7
        elif group == "board":
            y = float(layout.get("board_y", 0.715))
            spacing = float(layout.get("board_spacing", 0.068229))
            default_n = len(self.config.coords.group("board"))
            max_n = 7
        elif group == "hand":
            y = float(layout.get("hand_y", 0.900))
            spacing = float(layout.get("hand_spacing", 0.057292))
            center = float(layout.get("hand_center_x", center))
            default_n = len(self.config.coords.group("hand"))
            max_n = 10
        else:  # pragma: no cover - 仅内部使用
            return list(self.config.coords.group(group))
        n = default_n if count is None else int(count)
        n = max(1, min(n, max_n))
        return [
            (round(center + (i - (n - 1) / 2.0) * spacing, 4), y)
            for i in range(n)
        ]

    def _build_recruit_sequence(self, snap: LiveSnapshot) -> List[PlannedAction]:
        cfg = self.config
        coords = cfg.coords
        delays = cfg.delays
        flow = cfg.flow
        actions: List[PlannedAction] = []

        shop_n = max(1, self._memory_count(snap, "shop", int(flow.buy_count)))
        hand_n = self._memory_count(snap, "hand", 0)
        buy_n = min(shop_n, int(flow.buy_count), 7)
        expected_hand_n = hand_n + (buy_n if flow.buy_to_hand else 0)
        play_n = (min(expected_hand_n, int(flow.play_count), 10)
                  if expected_hand_n else 0)

        shop_pts = self._layout_positions("shop", shop_n)
        board_pts = self._layout_positions("board", 7)
        hand_pts = (self._layout_positions("hand", max(1, expected_hand_n))
                    if expected_hand_n else [])
        buy_hand_pts = self._layout_positions("hand", max(1, buy_n))

        if flow.buy_all_shop and buy_n > 0:
            for i in range(buy_n):
                if flow.buy_to_hand:
                    dst = buy_hand_pts[min(i, len(buy_hand_pts) - 1)]
                else:
                    dst = board_pts[i % len(board_pts)]
                src = shop_pts[min(i, len(shop_pts) - 1)]
                actions.append(PlannedAction(
                    kind="drag", name=f"buy_shop_{i}",
                    x=src[0], y=src[1], x2=dst[0], y2=dst[1],
                    duration=float(delays.drag_duration_s),
                    note=f"商店{i}→{'手牌' if flow.buy_to_hand else '棋盘'}",
                ))
                actions.append(PlannedAction(
                    kind="wait", name="between_buys",
                    seconds=float(delays.between_buys_s),
                ))
        if flow.play_hand_minions and play_n > 0 and hand_pts:
            for j in range(play_n):
                src = hand_pts[min(j, len(hand_pts) - 1)]
                dst = board_pts[j % len(board_pts)]
                actions.append(PlannedAction(
                    kind="drag", name=f"play_hand_{j}",
                    x=src[0], y=src[1], x2=dst[0], y2=dst[1],
                    duration=float(delays.drag_duration_s),
                    note=f"手牌{j}→棋盘",
                ))
                actions.append(PlannedAction(
                    kind="wait", name="between_plays",
                    seconds=float(delays.between_buys_s),
                ))
        if flow.use_hero_power:
            hx, hy = coords.point("hero_power")
            actions.append(PlannedAction(kind="click", name="hero_power",
                                         x=hx, y=hy, note="英雄技能"))
            actions.append(PlannedAction(kind="wait", name="after_power",
                                         seconds=float(delays.after_click_s)))
        if flow.send_end_turn:
            if flow.end_turn_use_key:
                actions.append(PlannedAction(
                    kind="key", name="end_turn", key=flow.end_turn_key,
                    note="结束回合（快捷键）",
                ))
            else:
                ex, ey = coords.point("end_turn")
                actions.append(PlannedAction(kind="click", name="end_turn",
                                             x=ex, y=ey, note="结束回合按钮"))
            actions.append(PlannedAction(
                kind="wait", name="end_turn_wait",
                seconds=float(delays.end_turn_wait_s),
            ))
        else:
            # 酒馆战棋单人模式没有"结束回合"按钮：买/出牌后等待计时器自动结束，
            # turn/phase 变化后 planner 会重新生成本回合动作（见 _plan_recruit）。
            actions.append(PlannedAction(
                kind="wait", name="wait_turn_timer",
                seconds=float(flow.recruit_min_s),
                note="等待招募计时器自动结束回合",
            ))
        return self._cap_turn_actions(actions)

    def _cap_turn_actions(self, actions: List[PlannedAction]) -> List[PlannedAction]:
        """限制每回合动作数，但必须保留末尾的「结束回合 + 等待」。"""
        cap = max(3, int(self.config.safety.max_actions_per_turn))
        if len(actions) <= cap:
            return actions
        tail = actions[-2:]
        head = actions[: cap - len(tail)]
        return head + tail

    # ── game over ──
    def _plan_game_over(self, snap: LiveSnapshot, now: float) -> List[PlannedAction]:
        if int(snap.game_id) == self._game_over_game:
            return []
        self._game_over_game = int(snap.game_id)
        # 结算页：先点"继续/返回"回大厅（不要盲点大厅坐标，避免误触退出客户端）
        px, py = self.config.coords.point("result_continue")
        return [
            PlannedAction(kind="screenshot",
                          name=f"game_over_{int(snap.game_id)}.png",
                          note="对局结算截图"),
            PlannedAction(kind="click", name="result_continue", x=px, y=py,
                          note="结算页→继续/返回大厅"),
            PlannedAction(kind="wait", name="after_result",
                          seconds=float(self.config.delays.after_game_wait_s)),
        ]

    # ── 盲操作（无日志/无内存时的兜底）──
    def _plan_blind(self, now: float) -> List[PlannedAction]:
        cfg = self.config
        flow = cfg.flow
        delays = cfg.delays
        if self._blind_game_started == 0.0:
            self._blind_game_started = now
        elapsed = now - self._blind_game_started
        if not self._blind_menu_clicked:
            self._blind_menu_clicked = True
            x, y = cfg.coords.point("menu_battlegrounds")
            return [PlannedAction(kind="click", name="menu_battlegrounds",
                                  x=x, y=y, note="[blind] 主菜单→酒馆战棋"),
                    PlannedAction(kind="wait", name="blind_load", seconds=2.0)]
        if not self._blind_lobby_clicked:
            self._blind_lobby_clicked = True
            x, y = cfg.coords.point("lobby_play")
            return [PlannedAction(kind="click", name="lobby_play", x=x, y=y,
                                  note="[blind] 大厅开始"),
                    PlannedAction(kind="wait", name="blind_lobby", seconds=2.0)]
        if not self._blind_hero_done:
            self._blind_hero_done = True
            options = cfg.coords.group("hero_options")
            if not options:
                return []
            x, y = options[0]
            cx, cy = cfg.coords.point("hero_confirm")
            return [
                PlannedAction(kind="click", name="hero_option_0", x=x, y=y,
                              note="[blind] 选择英雄"),
                PlannedAction(kind="wait", name="blind_hero_wait",
                              seconds=float(delays.hero_select_wait_s)),
                PlannedAction(kind="click", name="hero_confirm", x=cx, y=cy,
                              note="[blind] 确认英雄"),
                PlannedAction(kind="wait", name="blind_hero_confirm",
                              seconds=float(delays.after_click_s)),
            ]
        if elapsed >= float(flow.blind_game_duration_s):
            # 一局"盲玩"到时间 → 视为结束，回大厅/再来一局
            self._blind_games_completed += 1
            self._blind_game_started = now
            self._blind_menu_clicked = False
            self._blind_lobby_clicked = False
            self._blind_hero_done = False
            self._blind_turn = 0
            self._blind_last_turn_ts = 0.0
            px, py = cfg.coords.point("lobby_play_again")
            return [
                PlannedAction(kind="screenshot",
                              name=f"blind_game_{self._blind_games_completed}.png",
                              note="[blind] 对局结算截图"),
                PlannedAction(kind="click", name="lobby_play_again",
                              x=px, y=py, note="[blind] 再来一局"),
                PlannedAction(kind="wait", name="blind_after_game",
                              seconds=float(delays.after_game_wait_s)),
            ]
        gap = max(3.0, float(flow.blind_turn_s))
        if now - self._blind_last_turn_ts < gap:
            return []
        self._blind_last_turn_ts = now
        self._blind_turn += 1
        snap = LiveSnapshot(phase=PHASE_RECRUIT, turn=self._blind_turn,
                            in_game=True, source="blind")
        return self._build_recruit_sequence(snap)

    # ── 属性 ──
    @property
    def blind_games_completed(self) -> int:
        """盲操作模式下已完成（按时长推算）的局数。"""
        return self._blind_games_completed

    @property
    def turn_sequence_remaining(self) -> int:
        return len(self._turn_seq)


def plan_once(
    config: LiveConfig,
    snapshot: Optional[LiveSnapshot] = None,
    memory: Optional[Dict[str, Any]] = None,
    *,
    planner: Optional[Planner] = None,
    now: Optional[float] = None,
) -> List[PlannedAction]:
    """一次性调用（脚本/调试用），内部可复用同一 Planner 状态。"""
    planner = planner or Planner(config)
    return planner.plan(snapshot, memory, now=now)


__all__ = ["PlannedAction", "Planner", "plan_once"]
