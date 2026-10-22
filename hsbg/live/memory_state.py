"""可选内存状态读取（rea-operator 的 ``tools/live_state_mem.read_live_state()``）。

接口约定（弱契约，缺失时自动降级）
--------------------------------
``read_live_state() -> dict | None``，建议包含（有则用、无则忽略）::

    {"phase": "recruit"|"combat"|"choice"|"hero_select"|"game_over",
     "in_game": true, "turn": 5, "placement": 3,
     "gold": 7, "tier": 4, "health": 21,
     "shop": [{"card_id": ..., "atk":..}], "hand": [...], "board": [...],
     "hero_options": [...], "choice_options": [...]}

* 内存状态比日志**更实时/更精确**，但模块不存在或读取失败时必须静默降级为
  ``None``（此时运行器回退到 ``LiveLogWatcher`` 的日志状态，再回退到盲操作）。
* 本模块不修改任何内存/游戏状态，只调用只读接口。

命令行/配置可通过 ``--memory-reader module:function`` 或
``LiveBot(memory_reader=...)`` 注入自定义读取函数（测试用）。
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, Dict, Optional

from hsbg.live.logwatch import LiveSnapshot, PHASES

MemoryReader = Callable[[], Optional[Dict[str, Any]]]

#: 已知的内存状态读取入口（按优先级）
_CANDIDATE_MODULES = ("tools.live_state_mem", "hsbg.live.live_state_mem")
_DEFAULT_FUNCTION = "read_live_state"


def _import_reader(path: str) -> Optional[MemoryReader]:
    """``module:function`` → callable；失败返回 None。"""
    if ":" not in path:
        path = f"{path}:{_DEFAULT_FUNCTION}"
    module_name, func_name = path.split(":", 1)
    try:
        module = importlib.import_module(module_name)
    except Exception:  # noqa: BLE001
        return None
    fn = getattr(module, func_name, None)
    if not callable(fn):
        return None
    return fn  # type: ignore[return-value]


def load_memory_reader(spec: Optional[str] = None) -> Optional[MemoryReader]:
    """加载内存状态读取器；未就绪返回 ``None``（调用方降级）。"""
    if spec:
        return _import_reader(spec)
    for module_name in _CANDIDATE_MODULES:
        reader = _import_reader(f"{module_name}:{_DEFAULT_FUNCTION}")
        if reader is not None:
            return reader
    return None


def read_memory_state(spec: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """读取一次内存状态（失败返回 None，不抛异常）。"""
    reader = load_memory_reader(spec)
    if reader is None:
        return None
    try:
        state = reader()
    except Exception:  # noqa: BLE001
        return None
    return state if isinstance(state, dict) else None


# ── 把内存状态融合进 LiveSnapshot ──

def _norm_phase(value: Any) -> Optional[str]:
    if value is None:
        return None
    phase = str(value).strip().lower()
    aliases = {
        "player_turn": "recruit",
        "shopping": "recruit",
        "shop": "recruit",
        "opponent_turn": "combat",
        "battle": "combat",
        "combat": "combat",
        "combat_phase": "combat",
        "hero": "hero_select",
        "hero_pick": "hero_select",
        "hero_select": "hero_select",
        "hero_confirm": "hero_select",
        "hero_choose": "hero_select",
        "choice": "choice",
        "discover": "choice",
        "gameover": "game_over",
        "game_over": "game_over",
        "menu": "menu",
        "hub": "menu",
        "no_active_game": "menu",
        "lobby": "lobby",
        "bacon": "lobby",
        "unavailable": "",
        "unbound": "",
        "unknown": "",
    }
    phase = aliases.get(phase, phase)
    return phase if phase in PHASES else None


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


#: 内存 schema（``hsbg.live_state.v1``）中可直接存进 notes 的字段
_MEMORY_NOTE_KEYS = (
    "shop", "hand", "board", "choices", "hero", "gold", "tier", "health",
    "armor", "alive_count", "opponents", "legal", "quests", "trinkets",
    "powers", "phase_raw", "attached", "schema", "source",
)


def apply_memory(
    snapshot: Optional[LiveSnapshot], memory: Optional[Dict[str, Any]]
) -> Optional[LiveSnapshot]:
    """用内存状态覆盖/补充日志快照（内存优先，但不破坏已有字段）。

    兼容 rea-operator 的 ``hsbg.live_state.v1``：``phase`` 取值
    recruit/combat/hero_select/game_over/no_active_game/unavailable；
    ``no_active_game`` 视为不在对局（menu），``unavailable``/``unbound``
    表示内存不可用 → 不覆盖日志状态。
    """
    if not memory:
        return snapshot
    base = snapshot or LiveSnapshot()
    phase_raw = memory.get("phase", memory.get("state"))
    phase = _norm_phase(phase_raw)
    attached = bool(memory.get("attached", True))
    schema = str(memory.get("schema", ""))
    # 内存不可用：不覆盖（保留日志/盲操作状态）
    unavailable = (not attached) or str(phase_raw).lower() in (
        "unavailable", "unbound", "",
    )
    if unavailable and not memory.get("shop") and not memory.get("board"):
        return base

    in_game = base.in_game
    if attached and phase is not None:
        if phase in ("menu", "lobby"):
            in_game = False
        elif phase == "game_over":
            in_game = False
        else:
            in_game = True
    elif phase is None and memory.get("in_game") is not None:
        in_game = bool(memory["in_game"])

    turn = _as_int(memory.get("turn"))
    if turn is None or turn < 0:
        turn = base.turn
    placement = None
    for key in ("placement", "rank", "place", "placement_rank"):
        if memory.get(key) is not None:
            placement = _as_int(memory[key])
            break
    if placement is None and phase == "game_over":
        # 内存 schema 没有直接名次：用 alive/alive_count 推（死亡时仍有 N 人存活 → 第 N+1 名）
        alive = memory.get("alive")
        alive_count = _as_int(memory.get("alive_count"))
        if alive_count is not None and 1 <= alive_count <= 8:
            if alive is False:
                placement = min(8, alive_count + 1)
            elif alive is True and alive_count == 1:
                placement = 1
    if placement is None:
        placement = base.placement

    choices = memory.get("choices")
    choice_active = bool(base.choice_active)
    if isinstance(choices, (list, tuple)):
        choice_active = len(choices) > 0
    if choice_active and phase == "recruit" and in_game:
        phase = "choice"
    if phase is None:
        phase = base.phase
    if phase in ("no_active_game",):
        phase = "menu"
    # 内存只知道"不在对局"；若日志/HDT 已判定在酒馆大厅，保留 lobby 以便点「开始」
    if phase == "menu" and base.phase == "lobby":
        phase = "lobby"

    notes = dict(base.notes)
    for key in _MEMORY_NOTE_KEYS:
        if key in memory:
            notes[key] = memory[key]
    notes["memory"] = memory

    session = memory.get("session_id") or memory.get("session")
    if session is None:
        identity = memory.get("game_identity")
        if isinstance(identity, dict):
            session = identity.get("session_id") or identity.get("game_id")
    return LiveSnapshot(
        phase=phase,
        turn=turn,
        game_id=_as_int(memory.get("game_id")) or base.game_id,
        session_id=str(session) if session is not None else base.session_id,
        in_game=in_game,
        choice_active=choice_active,
        mode=str(memory.get("mode") or base.mode),
        placement=placement,
        turns_played=_as_int(memory.get("turns_played")) or base.turns_played,
        power_log_path=base.power_log_path,
        power_log_offset=base.power_log_offset,
        hdt_log_path=base.hdt_log_path,
        hdt_log_offset=base.hdt_log_offset,
        last_event=str(memory.get("last_event", base.last_event)),
        last_event_age_s=base.last_event_age_s,
        game_started_at=base.game_started_at,
        game_ended_at=base.game_ended_at,
        source=("memory" if base.source in ("unknown", "") else "memory+logwatch"),
        updated_at=base.updated_at,
        notes=notes,
    )


__all__ = [
    "MemoryReader",
    "load_memory_reader",
    "read_memory_state",
    "apply_memory",
]
