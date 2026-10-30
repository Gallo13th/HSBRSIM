"""势函数奖励塑形（potential-based reward shaping，P0-8）。

动机见 ``docs/REWARD_SHAPING.md``：现有奖励只看终局名次，弱 bot 局里「苟活不升级」
也能进前四，形成保守局部最优。这里给 learner 每个决策加一项**势函数差**奖励，
直接激励把战团做大、酒馆升级，同时（在 γ 一致的条件下）不改变最优策略。

公式（learner seat 专用）::

    Φ(s) = w_str * Σ(atk + hp) + w_tier * TIER_BONUS[tier]
    F_t  = λ * (γ_s * Φ(s_{t+1}) - Φ(s_t))
    reward_t = F_t + (旧奖励：-step_penalty，末步再加 u(rank))

**γ_s 必须与训练 γ（``PPOConfig.gamma``，当前 1.0）一致**才满足势函数塑形的
策略不变性；默认 ``shaping_gamma=None`` = 跟随训练 γ。历史实现硬编码 0.995 与
训练 γ=1.0 不一致，会引入与策略相关的累积惩罚，见 docs/REWARD_SHAPING.md §3。

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
import warnings
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

#: 与训练默认 γ=1.0 对齐的塑形折扣（``shaping_reward`` 的兼容默认值）。
#: **不要**把它当成「任务约定的 0.995」：历史实现的 0.995 与训练 γ=1.0 不一致，
#: 会破坏望远镜求和（见 docs/REWARD_SHAPING.md §3）。:class:`RewardShaper` 的
#: 默认值是 ``shaping_gamma=None`` = 跟随 ``cfg.gamma``，本常量只用于纯函数默认。
SHAPING_GAMMA = 1.0

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
    """``F = λ * (γΦ(s') - Φ(s))``（γ 需与训练折扣一致）。"""
    return float(coef) * (float(gamma) * float(phi_after) - float(phi_before))


#: 启动期偏差估算的参考轨迹（只用于把解析式变成可读数字；真实值见
#: collect meta 的 ``reward_shaping_bias_sum``）：一局 learner 决策数 / 平均 Φ。
BIAS_REF_DECISIONS = 45
BIAS_REF_MEAN_PHI = 5000.0


def shaping_bias_per_episode(coef: float, gamma_shaping: float,
                             gamma_train: float, *,
                             decisions: int = BIAS_REF_DECISIONS,
                             mean_phi: float = BIAS_REF_MEAN_PHI) -> float:
    """γ_s ≠ γ_t 时，一局回报里多出的**与策略相关**的塑形项（解析式）。

    令 ``F_t = c(γ_s Φ(s_{t+1}) − Φ(s_t))``、``Φ(s_T)=0``，按训练折扣 γ_t 求和：

    ``Σ_t γ_t^t F_t = −c Φ(s_0) + c(γ_s−γ_t) Σ_{t=0}^{T−1} γ_t^t Φ(s_{t+1})``

    γ_s == γ_t 时第二项严格为 0（望远镜求和，与策略无关）。本函数用
    ``mean_phi`` 近似 ``Φ(s_{t+1})``、``decisions`` 近似 T，返回**第二项**。
    """
    c = float(coef)
    gs = float(gamma_shaping)
    gt = float(gamma_train)
    if c == 0.0 or gs == gt:
        return 0.0
    t = max(0, int(decisions))
    if abs(gt - 1.0) < 1e-12:
        weight = float(t)
    else:
        weight = (1.0 - gt ** t) / (1.0 - gt)
    return c * (gs - gt) * float(mean_phi) * weight


def shaping_gamma_warning(coef: float, gamma_shaping: float, gamma_train: float, *,
                          decisions: int = BIAS_REF_DECISIONS,
                          mean_phi: float = BIAS_REF_MEAN_PHI) -> str:
    """不一致折扣的人类可读警告（启动期打印；含参考量级的偏差估算）。"""
    bias = shaping_bias_per_episode(
        coef, gamma_shaping, gamma_train,
        decisions=decisions, mean_phi=mean_phi)
    frac = abs(bias) / 2.0            # 名次效用全距 = 2（+1 … −1）
    return (
        f"塑形折扣 shaping_gamma={float(gamma_shaping):g} 与训练 γ="
        f"{float(gamma_train):g} 不一致：F 不再逐决策望远镜，整局回报会多出 "
        f"c·(γ_s−γ)·Σγ^tΦ 的与策略相关项，破坏策略不变性。"
        f"参考估算（T={int(decisions)} 决策/局、Φ̄={float(mean_phi):g}）："
        f"每局额外 ≈ {bias:+.3f}（名次效用全距 2 的 {frac:.0%}）；"
        f"实际累计值见 collect meta 的 reward_shaping_bias_sum。"
        f"建议 shaping_gamma=None（跟随训练 γ）。")


class RewardShaper:
    """一个采集任务内的塑形器：配置、Φ 读取、record 回填与开销统计。

    ``shaping_coef=0`` 时 ``enabled=False``：:meth:`potential` / :meth:`attach`
    都是空操作，:meth:`stats` 返回空 dict（不污染采集 meta）。
    """

    def __init__(self, cfg: Any, *, gamma: Optional[float] = None) -> None:
        """``gamma`` = **训练折扣**（PPOConfig.gamma）；None 时读 ``cfg.gamma``。

        ``cfg.shaping_gamma``：None（默认）= 跟随训练 γ；显式值原样使用。
        两者不一致时 enabled 状态下发 UserWarning（启动期不静默）。
        """
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
        self.gamma_train = float(
            gamma if gamma is not None else getattr(cfg, "gamma", 1.0))
        spec = getattr(cfg, "shaping_gamma", None)
        self.gamma_explicit = spec is not None
        if self.enabled:
            self.gamma = self.gamma_train if spec is None else float(spec)
            for name, value in (("shaping_gamma", self.gamma),
                                ("训练 gamma", self.gamma_train)):
                if not np.isfinite(value) or not (0.0 <= value <= 1.0):
                    raise ValueError(f"{name} 必须在 [0, 1] 内，得到 {value!r}")
        else:
            # coef=0：不解析显式 shaping_gamma（typo 不得改变关闭路径的行为）
            self.gamma = self.gamma_train
        self.gamma_aligned = (self.gamma == self.gamma_train)
        # 与训练折扣不一致时的「额外项」累计（诊断用；对齐时恒为 0）
        self.bias_sum = 0.0
        self._bias_steps: Dict[int, int] = {}
        if self.enabled and not self.gamma_aligned:
            warnings.warn(
                shaping_gamma_warning(self.coef, self.gamma, self.gamma_train),
                UserWarning, stacklevel=2)
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
        self._track_bias(int(game_id), phi_after)
        rec["reward"] = self.shaping(phi_before, phi_after)
        return True

    def _track_bias(self, game_id: int, phi_after: float) -> None:
        """累计 γ_s≠γ_t 时的额外项（仅诊断；对齐时零开销）。

        第 t 个决策的额外项 = ``c(γ_s−γ_t) γ_t^t Φ(s_{t+1})``；按 game_id 维护
        决策序号，因此 lockstep 多局交错也正确。
        """
        if self.gamma_aligned or self.coef == 0.0:
            return
        t = int(self._bias_steps.get(int(game_id), 0))
        self._bias_steps[int(game_id)] = t + 1
        self.bias_sum += (self.coef * (self.gamma - self.gamma_train)
                          * (self.gamma_train ** t) * float(phi_after))

    def stats(self, *, elapsed_s: Optional[float] = None) -> Dict[str, Any]:
        """采集 meta 里的塑形字段；禁用时返回 ``{}``（旧路径零键增量）。"""
        if not self.enabled:
            return {}
        n = int(self.count)
        out: Dict[str, Any] = {
            "shaping_coef": float(self.coef),
            "shaping_gamma": float(self.gamma),
            "shaping_gamma_train": float(self.gamma_train),
            "shaping_gamma_aligned": bool(self.gamma_aligned),
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
            # γ_s≠γ_t 时与策略相关的额外回报项（对齐时恒 0）；跨局累计
            "reward_shaping_bias_sum": float(self.bias_sum),
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
    bias_total = sum(float(m.get("reward_shaping_bias_sum", 0.0)) for m in rows)
    out: Dict[str, Any] = {
        "shaping_coef": float(first.get("shaping_coef", 0.0)),
        "shaping_gamma": float(first.get("shaping_gamma", SHAPING_GAMMA)),
        "shaping_gamma_train": float(first.get(
            "shaping_gamma_train", first.get("shaping_gamma", SHAPING_GAMMA))),
        "shaping_gamma_aligned": bool(first.get("shaping_gamma_aligned", True)),
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
        "reward_shaping_bias_sum": float(bias_total),
    }
    if elapsed_s is not None and float(elapsed_s) > 0.0:
        out["shaping_overhead_pct"] = 100.0 * float(seconds) / float(elapsed_s)
    return out


__all__ = [
    "SHAPING_GAMMA",
    "DEFAULT_TIER_BONUS",
    "BIAS_REF_DECISIONS",
    "BIAS_REF_MEAN_PHI",
    "parse_tier_bonus",
    "format_tier_bonus",
    "tier_bonus_value",
    "potential_from_player",
    "potential_from_player_json",
    "potential_from_obs",
    "potential",
    "shaping_reward",
    "shaping_bias_per_episode",
    "shaping_gamma_warning",
    "RewardShaper",
    "aggregate_shaping",
]
