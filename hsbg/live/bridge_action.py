"""Bridge state/option ↔ live/search action 映射（不发送；便于 dry-run/测试）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _upper(value: Any) -> str:
    return str(value or "").upper()


def _live_entity(live_state: Dict[str, Any], zone: str, index: int) -> Optional[Dict[str, Any]]:
    items = live_state.get(zone) or []
    if 0 <= index < len(items):
        return items[index]
    return None


def _eid(item: Optional[Dict[str, Any]]) -> Optional[int]:
    if not item:
        return None
    for key in ("eid", "entity_id", "entityId"):
        value = item.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return None


def _option_contains_type(opt: Dict[str, Any], *needles: str) -> bool:
    t = _upper(opt.get("type"))
    return any(n in t for n in needles)


def find_option_for_action(bridge_state: Dict[str, Any],
                           live_state: Dict[str, Any],
                           action: Any) -> Optional[Dict[str, Any]]:
    """按 action(kind/index) 在 bridge state.options 中找匹配 option。

    返回 option dict（含 main/targets/subs）；找不到返回 None。
    bridge state 不可用时调用方应记录 mapping_failed，不发送。
    """
    options = bridge_state.get("options") or []
    kind = str(getattr(action, "kind", "") or "")
    idx_raw = getattr(action, "index", -1)
    idx = int(idx_raw) if idx_raw is not None else -1
    if kind == "end_turn":
        for opt in options:
            if _option_contains_type(opt, "END", "ENDTURN", "END_TURN"):
                return opt
        return None
    zone = "shop" if kind == "buy" else "hand" if kind == "play" else "board" if kind == "sell" else ""
    item = _live_entity(live_state, zone, idx) if zone else None
    eid = _eid(item)
    needles = {"buy": ("BUY",), "play": ("PLAY",), "sell": ("SELL",)}.get(kind, ())
    # 1) entity 精确匹配
    if eid is not None:
        for opt in options:
            if _option_contains_type(opt, *needles) and int(opt.get("main") or 0) == eid:
                return opt
    # 2) 同类型按 zone 顺序回退（bridge/live entity id 不一致时）
    typed = [o for o in options if _option_contains_type(o, *needles)]
    if 0 <= idx < len(typed):
        return typed[idx]
    return None


def bridge_state_from_live_mock(live_state: Dict[str, Any]) -> Dict[str, Any]:
    """诊断用：由 live state 合成一个“理想 bridge state.options”（不用于真实发送）。"""
    options: List[Dict[str, Any]] = []
    for i, item in enumerate(live_state.get("shop") or []):
        eid = _eid(item)
        if eid is not None:
            options.append({"type": "BUY", "main": eid, "targets": [],
                            "subs": [], "pos": i})
    for i, item in enumerate(live_state.get("hand") or []):
        eid = _eid(item)
        if eid is not None:
            options.append({"type": "PLAY", "main": eid, "targets": [],
                            "subs": [], "pos": 0})
    for i, item in enumerate(live_state.get("board") or []):
        eid = _eid(item)
        if eid is not None:
            options.append({"type": "SELL", "main": eid, "targets": [],
                            "subs": [], "pos": i})
    options.append({"type": "END_TURN", "main": 0, "targets": [], "subs": [],
                    "pos": 0})
    return {"ok": True, "options_id": 1, "options": options, "choice": None}


__all__ = ["find_option_for_action", "bridge_state_from_live_mock"]
