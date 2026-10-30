"""势函数奖励塑形（potential-based reward shaping，P0-8）。

动机见 ``docs/REWARD_SHAPING.md``：现有奖励只看终局名次，弱 bot 局里「苟活不升级」
也能进前四，形成保守局部最优。这里给 learner 每个决策加一项**势函数差**奖励，
直接激励把战团做大、酒馆升级，同时（在 γ 一致的条件下）不改变最优策略。

公式（learner seat 专用）::

    Φ(s) = w_str * Σ(atk + hp) + w_tier * TIER_BONUS[tier]
    F_t  = λ * (γ * Φ(s_{t+1}) - Φ(s_t))
    reward_t = F_t + (旧奖励：-step_penalty，末步再加 u(rank))

几个实现约定：

- **Σ(atk+hp) 与 mirror_snapshots.board_strength 同定义**（见
  :func:`potential_from_player`），只是从标准观测 ``observe(seat)`` 的 board 块读取，
  比 ``player_json`` + ``json.loads`` 便宜一个数量级（见下）。
- **s_{t+1} = 同一局下一次 learner 决策前的状态**（learner MDP 的一步包含对手行动）。
  因此每个决策只读一次 Φ：上一次决策的 Φ(s') 就是本次决策的 Φ(s)，末步用
  Φ(terminal)=0。这既节省一半序列化，又保证 F 在整局上严格望远镜求和。
- 默认 ``shaping_coef=0``：:class:`RewardShaper` 立即禁用，不读状态、不写 record，
  采集/打包/GAE 与旧路径逐位一致。
- tier 表按 **tier 直接索引**（索引 0 为占位）；越界/非法 tier 一律按 0 处理。

开销（CPU 实测，单次 Φ 读取）：

- ``game.observe(seat)`` + 解析 board 块：约 1.5–2 µs；
- 对照 ``game.player_json(seat)``：6–50 µs；再 ``json.loads`` 全量解析：40–350 µs。

所以这里默认走观测路径，``player_json`` 只作为兜底。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from hsbg.env.obs_std import (
    GLOBAL_FIELD_INDEX,
    GLOBAL_FIELD_SCALE,
    MINION_ATK,
    MINION_F,
    MINION_HP,
    MINION_PRESENT,
    N_BOARD,
    OBS_FLOATS,
    SLICE_BOARD,
)

from .mirror_snapshots import board_strength

#: 塑形折扣（任务约定 0.995）。注意：严格不改变最优策略要求它与 PPO/GAE 的 γ 一致；
#: 当前训练入口 GAE γ=1.0，因此 0.995 只是「轻微前视」，见 docs/REWARD_SHAPING.md。
SHAPING_GAMMA = 0.995

#: 默认 tier 奖励表：**按 tier 直接索引**，索引 0 是占位（tier=1 → 0，tier=6 → 900）。
DEFAULT_TIER_BONUS: Tuple[float, ...] = (0.0, 0.0, 20.0, 60.0, 150.0, 400.0, 900.0)

#: 观测里 minion 的 atk/hp 归一化除数（``raw = round(float * 10)``）。
_MINION_STAT_SCALE = 10.0

#: board 块在 features 里的起始 float 下标（``SLICE_BOARD`` 是 slice）。
_BOARD_START = int(SLICE_BOARD.start)

#: global 块里 tier 的归一化除数（``raw = round(float * 6)``）。
_TIER_SCALE = float(GLOBAL_FIELD_SCALE["tier"])


def parse_tier_bonus(spec: Any) -> Tuple[float, ...]:
    """解析 ``--shaping-tier-bonus``：``"0,0,20,60,150,400,900"`` → tuple。

    ``None``/空串 → :data:`DEFAULT_TIER_BONUS`；也接受 list/tuple。非数字抛
    ``ValueError``（启动期 fail-fast，避免训练中静默按 0 处理）。
    """
    if spec is None:
        return DEFAULT_TIER_BONUS
    if isinstance(spec, (list, tuple, np.ndarray)):
        return tuple(float(x) for x in spec)
    text = str(spec).strip()
    if not text:
        return DEFAULT_TIER_BONUS
    parts = [p.strip() for p in text.replace(";", ",").split(",")]
    out: List[float] = []
    for p in parts:
        if not p:
            continue
        try:
            out.append(float(p))
        except ValueError as exc:
            raise ValueError(f"非法的 tier bonus 元素 {p!r}（{spec!r}）") from exc
    return tuple(out) if out else DEFAULT_TIER_BONUS


def format_tier_bonus(table: Sequence[float]) -> str:
    """把 tier 表格式化回 CLI 字符串（history/meta 记录用）。"""
    return ",".join(f"{float(x):g}" for x in table)


def tier_bonus_value(tier: Any, table: Sequence[float]) -> float:
    """``TIER_BONUS[tier]``；越界/非法 tier 或缺省位置返回 0.0。"""
    try:
        t = int(tier)
    except (TypeError, ValueError):
        return 0.0
    if 0 <= t < len(table):
        return float(table[t])
    return 0.0


def potential_from_player(player: Any, *, w_str: float = 1.0,
                          w_tier: float = 0.5,
                          tier_bonus: Sequence[float] = DEFAULT_TIER_BONUS) -> float:
    """由 ``player_json`` 解析出的 dict 计算 Φ。

    ``Σ(atk+hp)`` 直接复用 :func:`mirror_snapshots.board_strength`（同一套定义：
    非负整数 atk/hp 逐 minion 相加，空 board → 0）。字段缺失/空 board 都安全。
    """
    if not isinstance(player, dict):
        return 0.0
    strength = float(board_strength(player))
    tier = tier_bonus_value(player.get("tier", 0), tier_bonus)
    return float(w_str) * strength + float(w_tier) * tier


def potential_from_player_json(player_json: Any, *, w_str: float = 1.0,
                               w_tier: float = 0.5,
                               tier_bonus: Sequence[float] = DEFAULT_TIER_BONUS) -> float:
    """``game.player_json(seat)`` 字符串 → Φ（兜底路径，慢）。"""
    try:
        player = json.loads(player_json)
    except (TypeError, ValueError):
        return 0.0
    return potential_from_player(player, w_str=w_str, w_tier=w_tier,
                                 tier_bonus=tier_bonus)


def _features_float_view(features: Any) -> memoryview:
    """把观测 features（bytes / f32 ndarray）转成可按 float32 下标读取的视图。"""
    if isinstance(features, np.ndarray):
        arr = np.ascontiguousarray(features, dtype=np.float32).reshape(-1)
        view = memoryview(arr)
    else:
        view = memoryview(features)
    if view.format != "f" or view.itemsize != 4:
        view = view.cast("f")
    if view.nbytes // 4 < OBS_FLOATS:
        raise ValueError(f"obs features 太短: {view.nbytes // 4} < {OBS_FLOATS}")
    return view


def potential_from_obs(features: Any, *, w_str: float = 1.0,
                       w_tier: float = 0.5,
                       tier_bonus: Sequence[float] = DEFAULT_TIER_BONUS) -> float:
    """标准观测 features（3227 f32）→ Φ（快路径，约 2–4 µs）。

    观测编码：board 块 7×31，``MINION_PRESENT/ATK/HP``；atk/hp 是 ``raw/10``；
    global 的 ``tier`` 是 ``raw/6``。用 ``round`` 还原整数（float32 误差 < 0.5）。
    这里用 ``memoryview.cast("f")`` 直接读少量槽位，避免 numpy 小数组开销
    （实测 numpy 版 ~12 µs → memoryview 版 ~2 µs）。
    """
    view = _features_float_view(features)
    strength = 0
    for i in range(N_BOARD):
        base = _BOARD_START + i * MINION_F
        if view[base + MINION_PRESENT] > 0.5:
            strength += int(round(view[base + MINION_ATK] * _MINION_STAT_SCALE))
            strength += int(round(view[base + MINION_HP] * _MINION_STAT_SCALE))
    tier = int(round(view[GLOBAL_FIELD_INDEX["tier"]] * _TIER_SCALE))
    return (float(w_str) * float(strength)
            + float(w_tier) * tier_bonus_value(tier, tier_bonus))


def potential(game: Any, seat: int, *, w_str: float = 1.0, w_tier: float = 0.5,
              tier_bonus: Sequence[float] = DEFAULT_TIER_BONUS) -> float:
    """读 ``game`` 的 learner ``seat`` 当前 Φ（观测快路径，失败时退回 player_json）。"""
    try:
        out = game.observe(int(seat))
        feats = out[0] if isinstance(out, (tuple, list)) else out
        return potential_from_obs(feats, w_str=w_str, w_tier=w_tier,
                                  tier_bonus=tier_bonus)
    except Exception:  # noqa: BLE001 - 引擎版本差异/测试 mock：退回 JSON
        pass
    try:
        return potential_from_player_json(game.player_json(int(seat)),
                                          w_str=w_str, w_tier=w_tier,
                                          tier_bonus=tier_bonus)
    except Exception:  # noqa: BLE001 - 状态不可读时按 0（不阻断采集）
        return 0.0


def shaping_reward(phi_before: float, phi_after: float, coef: float,
                   gamma: float = SHAPING_GAMMA) -> float:
    """``F = λ * (γΦ(s') - Φ(s))``。"""
    return float(coef) * (float(gamma) * float(phi_after) - float(phi_before))


class RewardShaper:
    """一个采集任务内的塑形器：配置、Φ 读取、record 回填与开销统计。

    ``shaping_coef=0`` 时 ``enabled=False``：:meth:`potential` / :meth:`attach`
    都是空操作，:meth:`stats` 返回空 dict（不污染采集 meta）。
    """

    def __init__(self, cfg: Any, *, gamma: float = SHAPING_GAMMA) -> None:
        self.coef = float(getattr(cfg, "shaping_coef", 0.0) or 0.0)
        self.enabled = self.coef != 0.0
        self.w_str = float(getattr(cfg, "shaping_w_str", 1.0))
        self.w_tier = float(getattr(cfg, "shaping_w_tier", 0.5))
        if self.enabled:
            table = parse_tier_bonus(getattr(cfg, "shaping_tier_bonus",
                                             DEFAULT_TIER_BONUS))
        else:
            # coef=0：不解析、不校验（避免关闭状态下因 typo 改变旧路径行为）
            table = DEFAULT_TIER_BONUS
        self.tier_bonus: Tuple[float, ...] = table
        self.tier_bonus_spec = format_tier_bonus(table)
        self.gamma = float(gamma)
        # 统计（只在 enabled 时累加）
        self.calls = 0
        self.seconds = 0.0
        self.count = 0
        self.total = 0.0
        self.abs_total = 0.0
        self.abs_max = 0.0

    # ── Φ / F ──────────────────────────────────────────────────────────
    def potential(self, game: Any, seat: int) -> float:
        """读一次 Φ（计时；禁用时返回 0.0）。"""
        if not self.enabled:
            return 0.0
        t0 = time.perf_counter()
        value = potential(game, int(seat), w_str=self.w_str,
                          w_tier=self.w_tier, tier_bonus=self.tier_bonus)
        self.seconds += time.perf_counter() - t0
        self.calls += 1
        return value

    def shaping(self, phi_before: float, phi_after: float) -> float:
        """计算并累计一条 F。"""
        value = shaping_reward(phi_before, phi_after, self.coef, self.gamma)
        self.count += 1
        self.total += value
        self.abs_total += abs(value)
        self.abs_max = max(self.abs_max, abs(value))
        return value

    def attach(self, records: Sequence[Dict[str, Any]], index: int, game_id: int,
               phi_before: float, phi_after: float) -> bool:
        """把 F 写到 ``records[index]["reward"]``（校验 game_id，防串局）。"""
        if not self.enabled:
            return False
        idx = int(index)
        if not (0 <= idx < len(records)):
            return False
        rec = records[idx]
        if int(rec.get("game_id", -1)) != int(game_id):
            return False
        rec["reward"] = self.shaping(phi_before, phi_after)
        return True

    def stats(self, *, elapsed_s: Optional[float] = None) -> Dict[str, Any]:
        """采集 meta 里的塑形字段；禁用时返回 ``{}``（旧路径零键增量）。"""
        if not self.enabled:
            return {}
        n = int(self.count)
        out: Dict[str, Any] = {
            "shaping_coef": float(self.coef),
            "shaping_gamma": float(self.gamma),
            "shaping_w_str": float(self.w_str),
            "shaping_w_tier": float(self.w_tier),
            "shaping_tier_bonus": self.tier_bonus_spec,
            "shaping_calls": int(self.calls),
            "shaping_decisions": n,
            "shaping_seconds": float(self.seconds),
            "reward_shaping_sum": float(self.total),
            "reward_shaping_mean": (float(self.total) / n) if n else 0.0,
            "reward_shaping_abs_mean": (float(self.abs_total) / n) if n else 0.0,
            "reward_shaping_abs_sum": float(self.abs_total),
            "reward_shaping_abs_max": float(self.abs_max),
        }
        if elapsed_s is not None and float(elapsed_s) > 0.0:
            out["shaping_overhead_pct"] = 100.0 * float(self.seconds) / float(elapsed_s)
        return out


def aggregate_shaping(metas: Iterable[Any], *,
                      elapsed_s: Optional[float] = None) -> Dict[str, Any]:
    """把多个 worker/game 的塑形统计汇总成 collect 段顶层字段。

    规则：sum 计数/时间/奖励和，``reward_shaping_mean = sum / decisions``；
    没有任一条带 ``shaping_coef`` 的 meta（= 默认关闭）返回 ``{}``。
    """
    rows = [m for m in metas if isinstance(m, dict) and "shaping_coef" in m]
    if not rows:
        return {}
    first = rows[0]
    calls = sum(int(m.get("shaping_calls", 0)) for m in rows)
    decisions = sum(int(m.get("shaping_decisions", 0)) for m in rows)
    seconds = sum(float(m.get("shaping_seconds", 0.0)) for m in rows)
    total = sum(float(m.get("reward_shaping_sum", 0.0)) for m in rows)
    abs_total = sum(float(m.get("reward_shaping_abs_sum", 0.0)) for m in rows)
    abs_max = max(float(m.get("reward_shaping_abs_max", 0.0)) for m in rows)
    out: Dict[str, Any] = {
        "shaping_coef": float(first.get("shaping_coef", 0.0)),
        "shaping_gamma": float(first.get("shaping_gamma", SHAPING_GAMMA)),
        "shaping_w_str": float(first.get("shaping_w_str", 1.0)),
        "shaping_w_tier": float(first.get("shaping_w_tier", 0.5)),
        "shaping_tier_bonus": str(first.get("shaping_tier_bonus", "")),
        "shaping_calls": int(calls),
        "shaping_decisions": int(decisions),
        "shaping_seconds": float(seconds),
        "reward_shaping_sum": float(total),
        "reward_shaping_mean": (float(total) / decisions) if decisions else 0.0,
        "reward_shaping_abs_mean": (float(abs_total) / decisions) if decisions else 0.0,
        "reward_shaping_abs_sum": float(abs_total),
        "reward_shaping_abs_max": float(abs_max),
    }
    if elapsed_s is not None and float(elapsed_s) > 0.0:
        out["shaping_overhead_pct"] = 100.0 * float(seconds) / float(elapsed_s)
    return out


__all__ = [
    "SHAPING_GAMMA",
    "DEFAULT_TIER_BONUS",
    "parse_tier_bonus",
    "format_tier_bonus",
    "tier_bonus_value",
    "potential_from_player",
    "potential_from_player_json",
    "potential_from_obs",
    "potential",
    "shaping_reward",
    "RewardShaper",
    "aggregate_shaping",
]
