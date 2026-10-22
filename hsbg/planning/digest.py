"""轻量状态摘要 ``digest(game)``（可选接口，搜索去重/断言/日志用）。

两个模式：

- ``"fast"``（默认，目标 ≤0.5ms）：对**决策相关**状态做结构化哈希
  （回合/RNG/英雄经济与战团/待选队列/延迟队列/酒馆）；不保证覆盖全部
  战斗日志等调试字段，但 clone 与原局面摘要一致、动作推进后变化；
- ``"full"``：递归遍历 Game 属性图（跳过 CardDB 与实体 ``game`` 回环），
  对 dict 键值、list/tuple/set 做**顺序无关**规范化；成本 ~clone 量级，
  用于严格校验（如 clone 一致性测试）。

摘要对"同一逻辑状态的不同对象身份"稳定：clone 后 ``digest`` 相同；
不同状态（换牌/买随从/进入战斗）摘要不同。**不是密码学用途**。
"""

from __future__ import annotations

import functools
import hashlib
import types
from typing import Any, Dict, Optional

from hsrl2.game import Game

__all__ = ["digest", "digest_hex"]

_MAX_DEPTH_FALLBACK = 40


def _update_int(h, value: int) -> None:
    h.update(b"I")
    h.update(str(int(value)).encode("ascii", "replace"))


def _update_str(h, value: str) -> None:
    raw = value.encode("utf-8", "replace")
    h.update(b"S")
    h.update(len(raw).to_bytes(4, "little"))
    h.update(raw)


def _update_bool(h, value: bool) -> None:
    h.update(b"B1" if value else b"B0")


def _canon(value: Any) -> str:
    """身份无关的规范化表示（frozenset/set 顺序无关；Enum 用名字）。"""
    import enum
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return f"{type(value).__name__}:{value!r}"
    if isinstance(value, enum.Enum):
        return f"E:{type(value).__name__}:{value.name}"
    if isinstance(value, dict):
        return "D{" + ",".join(sorted(
            f"{_canon(k)}={_canon(v)}" for k, v in value.items())) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canon(v) for v in value) + "]"
    if isinstance(value, (set, frozenset)):
        return "{" + ",".join(sorted(_canon(v) for v in value)) + "}"
    if hasattr(value, "__dict__"):
        return "O:" + _entity_tag(value)
    return repr(value)


def _entity_tag(value: Any) -> str:
    """实体的身份无关标签（card_id + 基本位置/数值），用于 dict key 排序。"""
    card_id = str(getattr(value, "card_id", "") or "")
    zone = int(getattr(getattr(value, "zone", 0), "value", 0) or 0)
    atk = int(getattr(value, "atk", 0) or 0)
    health = int(getattr(value, "health", 0) or 0)
    return f"{type(value).__name__}:{card_id}:{zone}:{atk}:{health}"


def _feed_primitive(h, value: Any) -> bool:
    if value is None:
        h.update(b"N")
        return True
    if value is True or value is False:
        _update_bool(h, bool(value))
        return True
    if isinstance(value, int):
        _update_int(h, value)
        return True
    if isinstance(value, float):
        _update_str(h, repr(float(value)))
        return True
    if isinstance(value, str):
        _update_str(h, value)
        return True
    if isinstance(value, bytes):
        _update_str(h, value.hex())
        return True
    if isinstance(value, type) or isinstance(value, types.ModuleType):
        _update_str(h, f"T:{value.__name__}")
        return True
    try:
        import enum
        if isinstance(value, enum.Enum):
            _update_str(h, f"E:{type(value).__name__}:{value.name}")
            return True
    except Exception:                                     # noqa: BLE001
        pass
    return False


def _digest_fast(game: Game) -> str:
    h = hashlib.blake2b(digest_size=16)
    _update_int(h, int(getattr(game, "turn", 0)))
    _update_bool(h, bool(getattr(game, "finished", False)))
    _update_bool(h, bool(getattr(game, "in_combat", False)))
    rng = getattr(game, "rng", None)
    if rng is not None:
        try:
            seed = int(getattr(rng, "seed_value", 0))
            _update_int(h, seed)
            for part in rng._rng.getstate():
                _update_str(h, repr(part))
        except Exception:                                 # noqa: BLE001
            _update_str(h, "rng?")
    # pending choices（kind/owner/options 身份无关标签）
    for choice in list(getattr(game, "pending_choices", []) or []):
        _update_str(h, f"C:{getattr(choice, 'kind', '')}")
        owner = getattr(choice, "owner", None)
        _update_str(h, _entity_tag(owner) if owner is not None else "")
        for opt in list(getattr(choice, "options", []) or []):
            _update_str(h, _entity_tag(opt) if hasattr(opt, "__dict__")
                        else repr(opt)[:64])
    # 英雄状态
    for hero in list(getattr(game, "heroes", []) or []):
        _update_str(h, _entity_tag(hero))
        _update_int(h, int(getattr(hero, "health", 0) or 0))
        _update_int(h, int(getattr(hero, "armor", 0) or 0))
        _update_int(h, int(getattr(hero, "gold", 0) or 0))
        _update_int(h, int(getattr(hero, "tavern_tier", 0) or 0))
        _update_bool(h, bool(getattr(hero, "frozen_tavern", False)))
        for m in list(getattr(hero, "board", []) or []):
            _update_str(h, _entity_tag(m))
            for tag, val in sorted(getattr(m, "tags", {}).items(),
                                   key=lambda kv: kv[0].name):
                _update_str(h, tag.name)
                _update_str(h, _canon(val))
        for e in list(getattr(hero, "hand", []) or []):
            _update_str(h, _entity_tag(e))
        for e in list(getattr(hero, "tavern", []) or []):
            _update_str(h, _entity_tag(e))
        for t in list(getattr(hero, "trinkets", []) or []):
            _update_str(h, _entity_tag(t))
        quest = getattr(hero, "quest", None)
        _update_str(h, _entity_tag(quest) if quest is not None else "")
    _update_int(h, len(getattr(game, "pending_hand_queue", []) or []))
    _update_int(h, len(getattr(game, "deferred_actions", []) or []))
    _update_int(h, len(getattr(game, "combat_death_log", []) or []))
    return h.hexdigest()


def _digest_full(game: Game) -> str:
    h = hashlib.blake2b(digest_size=16)
    memo: Dict[int, int] = {}
    skip_types = (types.ModuleType, type)

    def feed(value: Any, depth: int = 0) -> None:
        if _feed_primitive(h, value):
            return
        # 回调/闭包属于"代码"而非状态：用 qualname 归一，避免 clone 重绑后
        # 新函数对象导致摘要漂移（rebind 保留 __qualname__）
        if isinstance(value, (types.FunctionType, types.MethodType,
                              types.BuiltinFunctionType,
                              types.BuiltinMethodType)) \
                or isinstance(value, functools.partial):
            name = getattr(value, "__qualname__", None) \
                or getattr(value, "__name__", None) \
                or type(value).__name__
            _update_str(h, f"F:{name}")
            return
        if depth > _MAX_DEPTH_FALLBACK:
            _update_str(h, "DEEP")
            return
        oid = id(value)
        if oid in memo:
            _update_int(h, -memo[oid] - 1)
            return
        memo[oid] = len(memo)

        if isinstance(value, dict):
            h.update(b"D")

            def _key(item):
                k = item[0]
                if isinstance(k, (str, int, float, bool, bytes)) or k is None:
                    return ("p", type(k).__name__, repr(k))
                return ("o", type(k).__name__, _entity_tag(k))

            for k, v in sorted(value.items(), key=_key):
                feed(k, depth + 1)
                feed(v, depth + 1)
            return
        if isinstance(value, (list, tuple)):
            h.update(b"L" if isinstance(value, list) else b"U")
            _update_int(h, len(value))
            for item in value:
                feed(item, depth + 1)
            return
        if isinstance(value, (set, frozenset)):
            h.update(b"X")
            # set 顺序不稳定 → 按身份无关标签排序后逐个 feed
            elements = sorted(
                value,
                key=lambda x: _entity_tag(x) if hasattr(x, "__dict__")
                else repr(x))
            _update_int(h, len(elements))
            for item in elements:
                feed(item, depth + 1)
            return
        if skip_types and isinstance(value, skip_types):
            _update_str(h, f"T:{type(value).__name__}")
            return
        attrs = getattr(value, "__dict__", None)
        if attrs is None:
            _update_str(h, f"O:{type(value).__name__}")
            return
        h.update(b"O")
        _update_str(h, f"{type(value).__module__}.{type(value).__name__}")
        for key in sorted(attrs.keys()):
            if key in ("db", "game"):
                continue
            _update_str(h, str(key))
            feed(attrs[key], depth + 1)

    feed(game)
    return h.hexdigest()


def digest(game: Game, mode: str = "fast") -> str:
    """返回状态摘要（hex）。``mode="fast"``（默认）或 ``"full"``。"""
    if game is None:
        raise ValueError("digest(None)")
    if mode == "fast":
        return _digest_fast(game)
    if mode == "full":
        return _digest_full(game)
    raise ValueError(f"unknown digest mode: {mode!r}")


def digest_hex(game: Game, mode: str = "fast") -> str:
    """语义同 :func:`digest`（显式名字，便于调用方区分）。"""
    return digest(game, mode=mode)
