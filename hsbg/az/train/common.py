"""AZ 训练脚手架公共常量与工具。

约束（与任务板 task-3 一致）：
- 只复用 `hsbg_engine`（Rust 主引擎）的公开 API；**不修改** `hsbg/env`、`hsbg/rl`、
  `hsbg/train` 等既有模块；
- 固定形状：245 动作 / 3227 features / 124 cards / 8 座；
- 本模块在**没有 hsbg_engine** 的开发机上也能 import（引擎相关入口惰性加载），
  这样数据/模型/报告相关的单测不依赖引擎。

动作分段与 docs/ACTION_SPACE_STD.md、docs/AZ_MCTS_SELFPLAY_DESIGN.md §2.3 一致，
与 AutoTavern 245 动作逐位对齐。
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional

import numpy as np

# ── 固定形状 ──────────────────────────────────────────────────────────────
N_ACTIONS = 245
OBS_FLOATS = 3227
OBS_CARDS = 124
N_PLAYERS = 8
N_RANKS = 8
DATA_VERSION = "37.0.0.255130"

# ── 245 动作分段（闭区间，含端点）────────────────────────────────────────
# EndTurn=0, Refresh=1, Freeze=2, Upgrade=3, HeroPower=4..5, DarkGift=6,
# Cancel=7, Buy=8..15, Sell=16..22, Activate=23..29, Choose=30..45,
# Play=46..125, Magnetize=126..195, Move=196..244
ACTION_SEGMENTS: Dict[str, tuple[int, int]] = {
    "end_turn": (0, 0),
    "refresh": (1, 1),
    "freeze": (2, 2),
    "upgrade": (3, 3),
    "hero_power": (4, 5),
    "dark_gift": (6, 6),
    "cancel": (7, 7),
    "buy": (8, 15),
    "sell": (16, 22),
    "activate": (23, 29),
    "choose": (30, 45),
    "play": (46, 125),
    "magnetize": (126, 195),
    "move": (196, 244),
}

#: 名次效用 u(r)=1-2*(r-1)/(N-1)，u(1)=+1 … u(8)=-1（设计 §2.5）。
RANK_UTILITY = np.array(
    [1.0 - 2.0 * (r - 1) / (N_PLAYERS - 1) for r in range(1, N_RANKS + 1)],
    dtype=np.float32,
)


def segment_indices(name: str) -> np.ndarray:
    """某动作分组在 245 维动作空间中的下标数组。"""
    lo, hi = ACTION_SEGMENTS[name]
    return np.arange(lo, hi + 1, dtype=np.int64)


def group_of(action: int) -> str:
    """动作下标 -> 分组名（越界返回 ``"unknown"``）。"""
    a = int(action)
    for name, (lo, hi) in ACTION_SEGMENTS.items():
        if lo <= a <= hi:
            return name
    return "unknown"


def utility_from_rank(rank: Any) -> np.ndarray:
    """名次 1..8 -> 效用 [-1,1]；rank<=0（未知/被守卫截断）-> 0.0。"""
    r = np.asarray(rank, dtype=np.int32)
    out = np.zeros(r.shape, dtype=np.float32)
    ok = (r >= 1) & (r <= N_RANKS)
    out[ok] = RANK_UTILITY[r[ok] - 1]
    return out


# ── 引擎惰性加载（引擎缺失时给出可读错误，而不是 import 期崩溃）──────────
_ENGINE: Optional[Any] = None


def engine_available() -> bool:
    """当前环境是否可 import ``hsbg_engine``（Rust 主引擎已构建安装）。"""
    try:
        import hsbg_engine  # noqa: F401
    except Exception:  # noqa: BLE001 - 缺构建/缺包都视为不可用
        return False
    return True


def load_engine():
    """返回 ``hsbg_engine`` 模块；不可用时抛 RuntimeError（附构建提示）。"""
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    try:
        import hsbg_engine as E
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "hsbg_engine 不可用：需要 Rust 主引擎构建安装 "
            "(`cd rust && python -m pip install -e .`, 见 docs/RUST_ENGINE.md)"
        ) from exc
    _ENGINE = E
    return E


def engine_info() -> Dict[str, Any]:
    """引擎/数据版本摘要（写进报告，保证可复现与跨版本可比性）。"""
    E = load_engine()
    try:
        data = E.data_info()
    except Exception:  # noqa: BLE001
        data = {}
    try:
        binfo = E.build_info()
        profile = str(binfo.get("profile"))
        source_hash = str(binfo.get("source_hash"))
    except Exception:  # noqa: BLE001
        profile, source_hash = None, None
    return {
        "engine_version": str(E.version()),
        "game_version": str(E.game_version()),
        "server_rules_version": str(E.server_rules_version()),
        "cards": int(data.get("cards", -1)),
        "build_profile": profile,
        "source_hash": source_hash,
        "n_actions": int(E.N_ACTIONS),
        "obs_floats": int(E.OBS_FLOATS),
        "obs_cards": int(E.OBS_CARDS),
        "data_version": DATA_VERSION,
    }


# ── 观测/动作数组工具 ─────────────────────────────────────────────────────
def obs_arrays(pair: Iterable[Any]) -> tuple[np.ndarray, np.ndarray]:
    """``Game.observe(seat) -> (features_bytes, cards_bytes)`` -> ndarray 拷贝。"""
    f_raw, c_raw = pair
    f = np.frombuffer(f_raw, dtype="<f4").copy().astype(np.float32, copy=False)
    c = np.frombuffer(c_raw, dtype="<i4").copy().astype(np.int32, copy=False)
    return f, c


def mask_from_bytes(raw: Any) -> np.ndarray:
    """``Game.legal_mask(seat)`` 的 u8[245] 字节 -> bool[245]。"""
    return np.frombuffer(raw, dtype=np.uint8).astype(bool)


def masked_normalize(policy: Any, mask: Any, eps: float = 1e-8) -> np.ndarray:
    """按合法掩码清零并归一；全 0 时退化为合法动作上的均匀分布。"""
    p = np.asarray(policy, dtype=np.float32).copy()
    m = np.asarray(mask, dtype=bool)
    p[~m] = 0.0
    s = float(p.sum())
    if s > eps:
        return p / s
    legal = m.astype(np.float32)
    n = float(legal.sum())
    if n <= 0:
        return np.zeros(N_ACTIONS, dtype=np.float32)
    return legal / n


def uniform_mask_policy(mask: Any) -> np.ndarray:
    """合法动作上的均匀分布（非法动作 0）。"""
    m = np.asarray(mask, dtype=bool)
    legal = m.astype(np.float32)
    n = float(legal.sum())
    if n <= 0:
        return np.zeros(N_ACTIONS, dtype=np.float32)
    return legal / n


def one_hot_policy(action: int, mask: Optional[Any] = None) -> np.ndarray:
    """动作下标 -> 245 维 one-hot（可选按 mask 校验，非法则退化为均匀合法）。"""
    pi = np.zeros(N_ACTIONS, dtype=np.float32)
    a = int(action)
    if mask is None:
        if 0 <= a < N_ACTIONS:
            pi[a] = 1.0
        return pi
    m = np.asarray(mask, dtype=bool)
    if 0 <= a < N_ACTIONS and bool(m[a]):
        pi[a] = 1.0
        return pi
    return uniform_mask_policy(m)


def masked_argmax(logits: Any, mask: Any) -> int:
    """在合法动作上取 argmax（非法位视为 -inf）；无合法动作返回 0。"""
    x = np.asarray(logits, dtype=np.float32).reshape(-1)
    m = np.asarray(mask, dtype=bool).reshape(-1)
    if not bool(m.any()):
        return 0
    x = np.where(m, x, -np.inf)
    return int(np.argmax(x))


def masked_softmax(logits: Any, mask: Any, eps: float = 0.0) -> np.ndarray:
    """数值稳定的 masked softmax（NaN/Inf 兜底为均匀合法分布）。"""
    x = np.asarray(logits, dtype=np.float32).reshape(-1).copy()
    m = np.asarray(mask, dtype=bool).reshape(-1)
    if not bool(m.any()):
        return np.zeros(N_ACTIONS, dtype=np.float32)
    x[~m] = -np.inf
    x = x - np.max(x[m])
    e = np.exp(x)
    s = float(e.sum())
    if not math.isfinite(s) or s <= 0:
        return uniform_mask_policy(m)
    p = (e / s).astype(np.float32)
    if eps > 0.0:
        p = (1.0 - eps) * p + eps * uniform_mask_policy(m)
    return p


def policy_entropy(policy: Any, mask: Optional[Any] = None) -> float:
    """策略熵（nats）；全 0 策略返回 0。"""
    p = np.asarray(policy, dtype=np.float64).reshape(-1)
    if mask is not None:
        p = p * np.asarray(mask, dtype=bool)
    s = float(p.sum())
    if s <= 0:
        return 0.0
    p = p / s
    nz = p[p > 0]
    return float(-(nz * np.log(nz)).sum())


# ── JSON 友好 ─────────────────────────────────────────────────────────────
def to_jsonable(obj: Any) -> Any:
    """递归把 numpy 类型/数组转换为可 ``json.dump`` 的原生类型。"""
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return to_jsonable(obj.tolist())
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return obj


__all__ = [
    "N_ACTIONS",
    "OBS_FLOATS",
    "OBS_CARDS",
    "N_PLAYERS",
    "N_RANKS",
    "DATA_VERSION",
    "ACTION_SEGMENTS",
    "RANK_UTILITY",
    "segment_indices",
    "group_of",
    "utility_from_rank",
    "engine_available",
    "load_engine",
    "engine_info",
    "obs_arrays",
    "mask_from_bytes",
    "masked_normalize",
    "uniform_mask_policy",
    "one_hot_policy",
    "masked_argmax",
    "masked_softmax",
    "policy_entropy",
    "to_jsonable",
]
