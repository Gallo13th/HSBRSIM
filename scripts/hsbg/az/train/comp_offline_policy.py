"""固定阵容脚本席（comp script seats）：把 ``CompPolicy`` 包成训练用的对手 ``Policy``。

用途：lockstep 采集里 ``cfg.frozen_seats`` / ``cfg.frozen_opponent = "comp:..."`` 的
「脚本席」——座位 1..N 由固定阵容脚本（hybrid：阵容动作优先、其余引擎 bot 兜底）驱动，
其余座位仍是引擎 bot。**只改变对手分布，不改变奖励/PPO 数学**（见 docs/COMP_SCRIPT_SEATS.md）。

契约（T12 ``scripts/comp_scripts.py``）：
- ``comp_keys() -> list[str]``、``view_of(game, seat) -> dict``；
- ``CompPolicy(spec, auto=False, seed=...)`` 的 ``.reset()`` / ``.observe(v, mask)`` /
  ``.comp_action(v, mask) -> int|None`` / ``.act(v, mask) -> int``。

实现要点：
- 每个 seat 一个独立 ``CompPolicy``（固定 spec，不 auto），状态隔离；
- 每个 seat 自己跟踪 ``id(game)``：换局即 ``reset()``，避免核心/经济计数跨局漂移；
- 合法性双保险：脚本给的 action 先查 mask；非法 → ``game.bot_action(seat)`` → mask 首个合法位；
- ``stats`` 暴露 decisions / illegal / bot_fallback / comp_actions / errors。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .common import N_ACTIONS, mask_from_bytes
from .policies import Decision, Policy

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

#: 最多允许的脚本席数（seat 1..N；7 = 全部 bot 席位，但训练侧只开放 0..3）。
MAX_SCRIPT_SEATS = 7

_CS_MODULE: Any = None


def load_comp_module() -> Any:
    """按需 import ``scripts/comp_scripts.py``（同 train_entity_sync 的 T1 importlib 做法）。

    只加载一次并缓存；pool worker（fork）会继承该缓存。
    """
    global _CS_MODULE
    if _CS_MODULE is None:
        path = os.path.join(ROOT, "scripts", "comp_scripts.py")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"找不到阵容脚本: {path}")
        spec = importlib.util.spec_from_file_location("comp_scripts_seats", path)
        if spec is None or spec.loader is None:  # pragma: no cover - 环境异常
            raise ImportError(f"无法加载 {path}")
        mod = importlib.util.module_from_spec(spec)
        # dataclasses 在 exec 期会查 sys.modules[cls.__module__]；必须先注册再 exec。
        sys.modules["comp_scripts_seats"] = mod
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except BaseException:
            sys.modules.pop("comp_scripts_seats", None)
            raise
        _CS_MODULE = mod
    return _CS_MODULE


def comp_script_keys() -> List[str]:
    """全部可用阵容 key（稳定排序）。"""
    return list(load_comp_module().comp_keys())


def view_of(game: Any, seat: int) -> Dict[str, Any]:
    """``game.view(seat)`` 的 JSON 解码（T12 契约；缺失时本地等价实现）。"""
    cs = load_comp_module()
    fn = getattr(cs, "view_of", None)
    if fn is not None:
        return fn(game, int(seat))
    import json
    return json.loads(game.view(int(seat)))


def _canon_key(key: str, keys: Sequence[str]) -> Optional[str]:
    """把用户输入映射到注册表 key（先精确、再大小写不敏感；失败返回 None）。"""
    k = str(key).strip()
    if k in keys:
        return k
    low = {x.lower(): x for x in keys}
    return low.get(k.lower())


def resolve_comp_keys(spec: str, n_seats: int, seed: int) -> List[str]:
    """把 ``--script-comps`` 解析成 ``n_seats`` 个具体 key。

    - ``auto``：从 ``comp_keys()`` 按 ``seed % len(keys)`` 稳定轮转（不重复）；
    - ``A,C``：逗号分隔的 key，按顺序映射 seat 1..N；不足时循环、超出时截断。

    非法 key / 无可用 key 抛 ``ValueError``。
    """
    keys = comp_script_keys()
    if not keys:
        raise ValueError("comp_scripts.COMPS 为空，无法启用脚本席")
    n = max(0, min(int(n_seats), min(MAX_SCRIPT_SEATS, len(keys))))
    if n <= 0:
        return []
    text = str(spec or "auto").strip()
    if text.lower() in ("", "auto"):
        off = int(seed) % len(keys)
        return [keys[(off + i) % len(keys)] for i in range(n)]
    parts: List[str] = []
    for raw in text.split(","):
        raw = raw.strip()
        if not raw:
            continue
        hit = _canon_key(raw, keys)
        if hit is None:
            raise ValueError(
                f"未知阵容 key: {raw!r}；可选 {len(keys)} 套: {', '.join(keys)}")
        parts.append(hit)
    if not parts:
        raise ValueError("--script-comps 为空")
    return [parts[i % len(parts)] for i in range(n)]


class CompOpponentPolicy(Policy):
    """固定阵容脚本驱动的对手策略（每个 seat 一个独立 CompPolicy）。

    ``hybrid=True``（训练默认）：``comp_action`` 优先，返回 ``None`` 时用
    ``game.bot_action(seat)`` 兜底（经济/升本/站位仍由引擎 bot 负责）；
    ``hybrid=False``：纯脚本 ``act``（测试/对照用）。
    """

    name = "comp_script_seats"
    supports_pi = False

    def __init__(self, comp_keys: Sequence[str], *, seed: int = 0,
                 hybrid: bool = True) -> None:
        keys = [str(k) for k in comp_keys if str(k)]
        if not keys:
            raise ValueError("CompOpponentPolicy 需要至少 1 个 comp key")
        cs = load_comp_module()
        self.comp_keys: List[str] = keys
        self.seed = int(seed)
        self.hybrid = bool(hybrid)
        self.policies: List[Any] = []
        for i, k in enumerate(keys):
            spec = cs.COMPS.get(k)
            if spec is None:
                raise KeyError(f"未知阵容 key: {k!r}（见 scripts/comp_scripts.py --list）")
            self.policies.append(
                cs.CompPolicy(spec, auto=False, seed=self.seed + 1009 * i))
        self._last_game_id: Dict[int, int] = {}
        self._last_turn: Dict[int, int] = {}
        self.stats: Dict[str, Any] = {
            "decisions": 0, "illegal": 0, "bot_fallback": 0,
            "comp_actions": 0, "errors": 0, "seat_resets": 0}

    # -- 内部 ---------------------------------------------------------------
    def _seat_policy(self, seat: int) -> Any:
        return self.policies[(int(seat) - 1) % len(self.policies)]

    def _legalize(self, game: Any, seat: int, action: Any,
                  mask: np.ndarray) -> int:
        """保证返回 mask 内的合法动作：脚本动作 → bot_action → 首个合法位。"""
        a = int(action) if action is not None else -1
        if 0 <= a < N_ACTIONS and bool(mask[a]):
            return a
        self.stats["illegal"] += 1
        try:
            b = int(game.bot_action(int(seat)))
        except Exception:  # noqa: BLE001 - 引擎拒绝时退化到 mask 首合法位
            b = -1
        if 0 <= b < N_ACTIONS and bool(mask[b]):
            return b
        nz = np.flatnonzero(mask)
        return int(nz[0]) if nz.size else 0

    # -- Policy 接口 ---------------------------------------------------------
    def reset(self) -> None:
        for pol in self.policies:
            pol.reset()
        self._last_game_id.clear()
        self._last_turn.clear()

    def decide(self, game: Any, seat: int) -> Decision:
        seat = int(seat)
        pol = self._seat_policy(seat)
        mask = mask_from_bytes(game.legal_mask(seat))
        v = view_of(game, seat)
        gid = id(game)
        turn = int(v.get("turn") or 0)
        # 换局检测：同一 seat 的 CompPolicy 不跨局继承核心/经济计数。
        if self._last_game_id.get(seat) != gid or turn < self._last_turn.get(seat, -1):
            pol.reset()
            self._last_game_id[seat] = gid
            self.stats["seat_resets"] += 1
        self._last_turn[seat] = turn

        fallback = False
        action: Optional[int]
        try:
            pol.observe(v, mask)
            if self.hybrid:
                action = pol.comp_action(v, mask)
                if action is None:
                    fallback = True
                    action = int(game.bot_action(seat))
                else:
                    self.stats["comp_actions"] += 1
            else:
                action = int(pol.act(v, mask))
        except Exception as exc:  # noqa: BLE001 - 单席脚本异常不能中断整局采集
            self.stats["errors"] += 1
            self.stats["last_error"] = repr(exc)[:200]
            fallback = True
            try:
                action = int(game.bot_action(seat))
            except Exception:  # noqa: BLE001
                action = None

        if fallback:
            self.stats["bot_fallback"] += 1
        a = self._legalize(game, seat, action, mask)
        self.stats["decisions"] += 1
        info = {"policy": self.name, "seat": seat,
                "comp": self.comp_keys[(seat - 1) % len(self.comp_keys)],
                "hybrid": self.hybrid, "bot_fallback": bool(fallback)}
        return Decision(a, None, info)

    def act_batch(self, features: np.ndarray, cards: np.ndarray,
                  mask: np.ndarray, turn: int) -> int:  # pragma: no cover - 训练不用
        raise NotImplementedError(
            "CompOpponentPolicy 只实现 Game 级 decide()（lockstep 采集用）")


__all__ = ["CompOpponentPolicy", "comp_script_keys", "load_comp_module",
           "resolve_comp_keys", "view_of", "MAX_SCRIPT_SEATS"]
