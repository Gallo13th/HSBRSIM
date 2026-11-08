"""等级进度奖励（tier-target reward）：按回合设定「应该达到的酒馆等级」并直接改 reward。

动机见 ``docs/TIER_TARGET.md``：``scripts/quality_monitor.py`` 的实测显示，champion 与
s8b@10M 的 learner tier 从 **turn 9 起恒为 4**，而真实 10k+ MMR 在 t9+ 会到 5–6 级；
战团强度只有真实 p50 的 0.03–0.37。现有势函数塑形（``reward_shaping.py``）**没有改变**
tier 行为：升一级要花 9–11 金币、瞬间 Φ 可能下降，长期收益不在 Φ 里。所以这里改用
**定向目标曲线**（不是势函数）：

    TARGET_TIER = {7: 4, 9: 5, 12: 6}          # 默认目标曲线（turn -> tier）

在 learner 的**每个新回合开始**（该回合第一条 learner decision 之前）读一次 tier：

- 若该 turn 有目标且 ``tier < target`` → 该回合第一条 decision 的 reward 加
  ``-coef * tier_penalty``（默认 penalty=0.02，coef=1），记一次 miss；
- 若该 turn 有目标且 ``tier >= target`` 且此前**从未领取过该 turn 档位** → 该回合一
  次性加 ``+coef * tier_bonus``（默认 bonus=0.15），记一次 hit；用 ``set`` 记录已领取
  的 turn，每个档位只发一次，越过目标后不重复发；
- 该 turn 没有目标 → 不做任何事（不惩罚也不奖励）。

为什么直接改 reward 而不是势函数：这是**有意的策略偏置**（我们就是要它更早升级），
不满足 potential-based shaping 的最优策略不变性。因此默认关闭；``tier_target_coef=0``
时 :class:`TierTargetTracker` 立即禁用：不读状态、不写 record、不新增 meta 键，
采集/打包/GAE 与旧路径**逐位一致**。

实现约定：

- 每个采集任务里**每局一个** :class:`TierTargetTracker`（状态隔离：``claimed`` /
  ``evaluated`` 互不共享；多进程/多线程采集天然按局隔离）；
- 奖励不直接写 ``record["reward"]``，而是先 :meth:`TierTargetTracker.queue` 到待应用
  列表，采集结束（势函数塑形的终局 Φ=0 回填之后）再 :meth:`TierTargetTracker.flush`
  一次性加上。这样与 ``RewardShaper.attach`` 的「覆盖写」不会互相踩；
- tier 读取走 ``game.observe(seat)`` 快路径（``global.tier = raw/6``），失败退回
  ``player_json``，再失败按 0（不阻断采集）；
- 越界/非法 tier 归一为 0；目标表在启动期 fail-fast 解析（非法格式直接 ``ValueError``）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np

from hsbg.env.obs_std import GLOBAL_FIELD_INDEX, GLOBAL_FIELD_SCALE

#: 默认目标曲线：turn -> 期望 tier（见 docs/TIER_TARGET.md 的诊断依据）。
DEFAULT_TIER_TARGET_TABLE: Dict[int, int] = {7: 4, 9: 5, 12: 6}

#: 默认目标曲线字符串（CLI/记录用）。
DEFAULT_TIER_TARGET_TABLE_SPEC = "7:4,9:5,12:6"

#: 未达标时该回合第一条 decision 的惩罚（乘 coef；默认 0.02）。
DEFAULT_TIER_PENALTY = 0.02

#: 达标时一次性奖励（乘 coef；默认 0.15）。
DEFAULT_TIER_BONUS = 0.15

#: tier 在观测 global 块里的归一化除数（``raw = round(float * 6)``）。
_TIER_SCALE = float(GLOBAL_FIELD_SCALE["tier"])

#: tier 合法范围（引擎 tier 1..6；7 是特殊等级，允许作为目标/观测值）。
_TIER_MIN = 1
_TIER_MAX = 7


# ══════════════════════════════════════════════════════════════════════════
# 1. 目标表解析 / 格式化
# ══════════════════════════════════════════════════════════════════════════
def _add_target(table: Dict[int, int], turn: Any, tier: Any) -> None:
    """解析并写入一条 ``turn:tier``；非法值抛 ``ValueError``（启动期 fail-fast）。"""
    try:
        t = int(turn)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"非法 turn {turn!r}（应为正整数）") from exc
    try:
        v = int(tier)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"非法 tier {tier!r}（应为 {_TIER_MIN}..{_TIER_MAX} 整数）") from exc
    if t < 1:
        raise ValueError(f"turn 必须 >= 1，得到 {t}")
    if not (_TIER_MIN <= v <= _TIER_MAX):
        raise ValueError(f"tier 必须在 {_TIER_MIN}..{_TIER_MAX}，得到 {v}")
    if t in table:
        raise ValueError(f"目标表 turn 重复：{t}")
    table[t] = v


def parse_tier_target_table(spec: Any) -> Dict[int, int]:
    """解析 ``--tier-target-table``：``"7:4,9:5,12:6"`` → ``{7:4, 9:5, 12:6}``。

    - ``None`` / 空串 → :data:`DEFAULT_TIER_TARGET_TABLE` 的副本；
    - 也接受 ``dict``（键值直接校验）与 ``[(turn, tier), ...]``；
    - 分隔符：逗号或分号；条目内允许空格；turn 重复 / 非法 turn / tier 越界
      一律 ``ValueError``（启动期报错，避免训练中静默按 0 处理）。
    """
    if spec is None:
        return dict(DEFAULT_TIER_TARGET_TABLE)
    if isinstance(spec, dict):
        out: Dict[int, int] = {}
        for t, v in spec.items():
            _add_target(out, t, v)
        return out
    if isinstance(spec, (list, tuple)) and spec and not isinstance(spec[0], str):
        out = {}
        for item in spec:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError(f"非法目标表条目 {item!r}（应为 (turn, tier)）")
            _add_target(out, item[0], item[1])
        return out
    text = str(spec).strip()
    if not text:
        return dict(DEFAULT_TIER_TARGET_TABLE)
    out = {}
    for raw in text.replace(";", ",").split(","):
        item = raw.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"非法目标表条目 {item!r}（应为 turn:tier）")
        turn_s, tier_s = item.split(":", 1)
        _add_target(out, turn_s.strip(), tier_s.strip())
    if not out:
        return dict(DEFAULT_TIER_TARGET_TABLE)
    return out


def format_tier_target_table(table: Any) -> str:
    """把目标表格式化回 CLI 字符串（history/meta 记录用），按 turn 升序。"""
    if isinstance(table, (list, tuple)):
        pairs = [(int(t), int(v)) for t, v in table]
    elif isinstance(table, dict):
        pairs = sorted((int(t), int(v)) for t, v in table.items())
    else:
        return str(table)
    return ",".join(f"{t}:{v}" for t, v in sorted(pairs))


def tier_target_for_turn(turn: Any, table: Dict[int, int]) -> Optional[int]:
    """该 turn 的目标 tier；没有目标返回 ``None``。"""
    try:
        return table.get(int(turn))
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════════
# 2. tier 读取（观测快路径 + player_json 兜底）
# ══════════════════════════════════════════════════════════════════════════
def _features_float_view(features: Any) -> memoryview:
    """观测 features（bytes / f32 ndarray）→ 可按 float32 下标读取的 memoryview。"""
    if isinstance(features, np.ndarray):
        arr = np.ascontiguousarray(features, dtype=np.float32).reshape(-1)
        view = memoryview(arr)
    else:
        view = memoryview(features)
    if view.format != "f" or view.itemsize != 4:
        view = view.cast("f")
    idx = int(GLOBAL_FIELD_INDEX["tier"])
    if view.nbytes // 4 <= idx:
        raise ValueError(f"obs features 太短: {view.nbytes // 4} <= tier 下标 {idx}")
    return view


def tier_from_obs(features: Any) -> int:
    """标准观测 features → tier（``global.tier`` 是 ``raw/6``，用 round 还原整数）。"""
    view = _features_float_view(features)
    return int(round(view[int(GLOBAL_FIELD_INDEX["tier"])] * _TIER_SCALE))


def tier_from_player_json(player_json: Any) -> int:
    """``game.player_json(seat)`` 字符串 → tier（慢路径，兜底）。"""
    try:
        player = json.loads(player_json)
    except (TypeError, ValueError):
        return 0
    if not isinstance(player, dict):
        return 0
    try:
        return int(player.get("tier") or 0)
    except (TypeError, ValueError):
        return 0


def tier_of(game: Any, seat: int) -> int:
    """读 ``game`` 的 learner ``seat`` 当前 tier（观测快路径，失败退回 player_json）。"""
    try:
        out = game.observe(int(seat))
        feats = out[0] if isinstance(out, (tuple, list)) else out
        return tier_from_obs(feats)
    except Exception:  # noqa: BLE001 - 引擎版本差异/测试 mock：退回 JSON
        pass
    try:
        return tier_from_player_json(game.player_json(int(seat)))
    except Exception:  # noqa: BLE001 - 状态不可读时按 0（不阻断采集）
        return 0


# ══════════════════════════════════════════════════════════════════════════
# 3. 状态机
# ══════════════════════════════════════════════════════════════════════════
def _cfg_value(cfg: Any, name: str, explicit: Any, default: Any) -> Any:
    if explicit is not None:
        return explicit
    if cfg is not None:
        return getattr(cfg, name, default)
    return default


class TierTargetTracker:
    """一局一个的目标曲线状态机：检查点、一次性奖励与待应用 reward 增量。

    ``coef=0``（默认）时 ``enabled=False``：:meth:`observe` / :meth:`queue` /
    :meth:`flush` 全是空操作，:meth:`stats` 返回 ``{}``（不污染采集 meta）。

    状态：

    - ``evaluated``：已检查过的 turn（同一 turn 只查一次，防止重复扣分/发奖）；
    - ``claimed``：已领取过「达标奖励」的 turn 档位（每档只发一次）；
    - ``pending``：``(record_index, game_id, delta)``，采集结束时统一加到 record。
    """

    def __init__(self, cfg: Any = None, *, coef: Optional[float] = None,
                 penalty: Optional[float] = None, bonus: Optional[float] = None,
                 table: Any = None) -> None:
        self.coef = float(_cfg_value(cfg, "tier_target_coef", coef, 0.0) or 0.0)
        self.enabled = self.coef != 0.0
        self.penalty = float(_cfg_value(cfg, "tier_penalty", penalty,
                                        DEFAULT_TIER_PENALTY))
        self.bonus = float(_cfg_value(cfg, "tier_bonus", bonus, DEFAULT_TIER_BONUS))
        if self.enabled:
            if self.penalty < 0.0:
                raise ValueError(f"tier_penalty 必须 >= 0，得到 {self.penalty}")
            if self.bonus < 0.0:
                raise ValueError(f"tier_bonus 必须 >= 0，得到 {self.bonus}")
            spec = (_cfg_value(cfg, "tier_target_table", table,
                               DEFAULT_TIER_TARGET_TABLE_SPEC))
            self.table: Dict[int, int] = parse_tier_target_table(spec)
        else:
            # coef=0：不解析、不校验（避免关闭状态下因 typo 改变旧路径行为）
            self.table = dict(DEFAULT_TIER_TARGET_TABLE)
        self.table_spec = format_tier_target_table(self.table)

        self.evaluated: Set[int] = set()
        self.claimed: Set[int] = set()
        self.pending: List[Tuple[int, int, float]] = []

        # 统计（只在 enabled 时累加）
        self.checks = 0
        self.hits = 0
        self.misses = 0
        self.bonus_sum = 0.0
        self.penalty_sum = 0.0
        self.reward_sum = 0.0
        self.applied = 0
        self.dropped = 0

    # ── 检查点 ──────────────────────────────────────────────────────────
    def check(self, turn: Any, tier: Any) -> float:
        """在 turn 起点检查一次 tier，返回**该回合第一条 decision** 的 reward 增量。

        同一 turn 重复调用返回 0；没有目标 / 已领取过该档位 / 已达标不再发奖。
        """
        if not self.enabled:
            return 0.0
        try:
            t = int(turn)
        except (TypeError, ValueError):
            return 0.0
        if t in self.evaluated:
            return 0.0
        self.evaluated.add(t)
        target = self.table.get(t)
        if target is None:
            return 0.0
        try:
            current = int(tier)
        except (TypeError, ValueError):
            current = 0
        self.checks += 1
        if current >= int(target):
            if t in self.claimed:
                return 0.0
            self.claimed.add(t)
            self.hits += 1
            delta = self.coef * self.bonus
            self.bonus_sum += delta
            self.reward_sum += delta
            return delta
        self.misses += 1
        delta = -self.coef * self.penalty
        self.penalty_sum += -delta
        self.reward_sum += delta
        return delta

    def observe(self, game: Any, seat: int, turn: Optional[int] = None) -> float:
        """读当前 tier 并检查该 turn；已检查过的 turn 直接返回 0（不读状态）。"""
        if not self.enabled:
            return 0.0
        try:
            t = int(game.turn if turn is None else turn)
        except (TypeError, ValueError):
            return 0.0
        if t in self.evaluated:
            return 0.0
        return self.check(t, tier_of(game, int(seat)))

    def check_obs(self, turn: Any, features: Any) -> float:
        """由观测 features 直接检查（离线/测试用；不读 game）。"""
        if not self.enabled:
            return 0.0
        try:
            t = int(turn)
        except (TypeError, ValueError):
            return 0.0
        if t in self.evaluated:
            return 0.0
        return self.check(t, tier_from_obs(features))

    # ── 待应用增量 ──────────────────────────────────────────────────────
    def queue(self, index: int, game_id: int, delta: float) -> bool:
        """把增量挂到 ``records[index]``（真正写入在 :meth:`flush`）。"""
        if not self.enabled:
            return False
        if float(delta) == 0.0:
            return False
        try:
            idx = int(index)
        except (TypeError, ValueError):
            return False
        if idx < 0:
            return False
        self.pending.append((idx, int(game_id), float(delta)))
        return True

    def flush(self, records: Sequence[Dict[str, Any]]) -> int:
        """把 pending 增量加到 ``record["reward"]``（默认 0.0），返回成功条数。

        校验 ``record["game_id"]``，防止多局共享 records 列表时串局；不匹配或越界
        只记 ``dropped``，不抛异常（采集不因单条记录异常而中断）。
        """
        if not self.enabled or not self.pending:
            return 0
        applied = 0
        for idx, gid, delta in self.pending:
            if not (0 <= idx < len(records)):
                self.dropped += 1
                continue
            rec = records[idx]
            if int(rec.get("game_id", -1)) != int(gid):
                self.dropped += 1
                continue
            rec["reward"] = float(rec.get("reward", 0.0)) + float(delta)
            applied += 1
        self.applied += applied
        self.pending = []
        return applied

    def stats(self) -> Dict[str, Any]:
        """采集 meta 里的 tier-target 字段；禁用时返回 ``{}``（旧路径零键增量）。"""
        if not self.enabled:
            return {}
        return {
            "tier_target_coef": float(self.coef),
            "tier_penalty": float(self.penalty),
            "tier_bonus": float(self.bonus),
            "tier_target_table": self.table_spec,
            "tier_checks": int(self.checks),
            "tier_hits": int(self.hits),
            "tier_misses": int(self.misses),
            "tier_bonus_sum": float(self.bonus_sum),
            "tier_penalty_sum": float(self.penalty_sum),
            "tier_target_reward_sum": float(self.reward_sum),
            "tier_target_applied": int(self.applied),
            "tier_target_dropped": int(self.dropped),
        }


def aggregate_tier_target(metas: Iterable[Any]) -> Dict[str, Any]:
    """把多个 worker/game 的 tier-target 统计汇总成 collect 段顶层字段。

    没有任一条带 ``tier_target_coef`` 的 meta（= 默认关闭）返回 ``{}``。
    """
    rows = [m for m in metas if isinstance(m, dict) and "tier_target_coef" in m]
    if not rows:
        return {}
    first = rows[0]
    checks = sum(int(m.get("tier_checks", 0)) for m in rows)
    hits = sum(int(m.get("tier_hits", 0)) for m in rows)
    misses = sum(int(m.get("tier_misses", 0)) for m in rows)
    out: Dict[str, Any] = {
        "tier_target_coef": float(first.get("tier_target_coef", 0.0)),
        "tier_penalty": float(first.get("tier_penalty", DEFAULT_TIER_PENALTY)),
        "tier_bonus": float(first.get("tier_bonus", DEFAULT_TIER_BONUS)),
        "tier_target_table": str(first.get("tier_target_table",
                                           DEFAULT_TIER_TARGET_TABLE_SPEC)),
        "tier_checks": int(checks),
        "tier_hits": int(hits),
        "tier_misses": int(misses),
        "tier_bonus_sum": float(sum(float(m.get("tier_bonus_sum", 0.0)) for m in rows)),
        "tier_penalty_sum": float(sum(float(m.get("tier_penalty_sum", 0.0))
                                      for m in rows)),
        "tier_target_reward_sum": float(sum(float(m.get("tier_target_reward_sum", 0.0))
                                            for m in rows)),
        "tier_target_applied": int(sum(int(m.get("tier_target_applied", 0)) for m in rows)),
        "tier_target_dropped": int(sum(int(m.get("tier_target_dropped", 0)) for m in rows)),
        "tier_hit_rate": (float(hits) / float(checks) if checks else 0.0),
    }
    return out


__all__ = [
    "DEFAULT_TIER_TARGET_TABLE",
    "DEFAULT_TIER_TARGET_TABLE_SPEC",
    "DEFAULT_TIER_PENALTY",
    "DEFAULT_TIER_BONUS",
    "parse_tier_target_table",
    "format_tier_target_table",
    "tier_target_for_turn",
    "tier_from_obs",
    "tier_from_player_json",
    "tier_of",
    "TierTargetTracker",
    "aggregate_tier_target",
]
