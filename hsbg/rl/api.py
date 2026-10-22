"""RL 接口层稳定契约（``hsbg.rl`` 的核心类型/协议/单局驱动）。

设计目标
--------
把「环境 ↔ 采集 ↔ 评测 ↔（后续）训练」之间的边界收敛成一组**稳定的、
可独立测试的**协议与数据类：

* :class:`Policy` —— 观测级策略协议：``act(obs) -> 候选下标``（或
  ``CandidateAction``），``reset()`` 在每局开始时清理内部状态；
* :class:`EnvLike` —— 与 ``docs/ENV_SPEC.md`` §4 一致的单环境五元组协议；
* :class:`Transition` / :class:`EpisodeRecord` —— 轨迹与整局记录（含 seed /
  终局名次 / 终止原因 / 非法动作计数），可直接转 JSONL（见 :data:`SCHEMA_VERSION`）；
* :func:`run_episode` —— **唯一**的顺序单局驱动实现，collector / evaluate /
  gym 录制共用，避免三处各写一套循环导致行为漂移。

本模块**不依赖引擎、torch、gymnasium**，只依赖 ``hsbg.env.spec``。
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Protocol, Sequence, Tuple, Union, runtime_checkable

from hsbg.env.spec import (
    CANDIDATE_MAX,
    CandidateAction,
    EntityToken,
    Observation,
)

#: 单步记录 / 整局记录的 JSONL schema 版本（字段不兼容时 +1）
SCHEMA_VERSION = 1
#: RL 接口层协议版本（Policy / EnvLike / 记录结构）
API_VERSION = 1

#: 观测协议版本（``Observation.version``），写进 header 便于回溯
OBS_VERSION = int(getattr(Observation(), "version", 1))

#: 策略返回的动作类型
ActionLike = Union[int, CandidateAction, None]


# ══════════════════════════════════════════════════════════════════════
# 协议
# ══════════════════════════════════════════════════════════════════════


@runtime_checkable
class Policy(Protocol):
    """观测级策略协议。

    ``act`` 返回 ``obs.candidates`` 的下标（``int``）或 ``CandidateAction``；
    返回 ``None``/越界下标视为非法动作，由 :func:`run_episode` 兜底处理。
    ``deterministic=True`` 时表示"评测/演示"，策略应尽量消除随机性。
    """

    name: str

    def act(
        self,
        obs: Observation,
        *,
        deterministic: bool = False,
        rng: Optional[random.Random] = None,
    ) -> ActionLike:  # pragma: no cover - 协议定义
        ...

    def reset(self) -> None:  # pragma: no cover - 协议定义
        ...


@runtime_checkable
class EnvLike(Protocol):
    """单环境协议（``docs/ENV_SPEC.md`` §4）。

    ``step`` 接受 ``CandidateAction`` 或候选下标；返回
    ``(obs, reward, terminated, truncated, info)``。``info["rank"]`` 在终局
    应给出名次（1..num_players）。
    """

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Observation:  # pragma: no cover - 协议定义
        ...

    def step(
        self, action: Any
    ) -> Tuple[Observation, float, bool, bool, Dict[str, Any]]:  # pragma: no cover
        ...

    def close(self) -> None:  # pragma: no cover - 协议定义
        ...


# ══════════════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════════════


def _kind_of(cand: Optional[CandidateAction]) -> str:
    if cand is None:
        return ""
    return str(getattr(cand.kind, "value", cand.kind))


def _signature_of(cand: Optional[CandidateAction]) -> Tuple[Any, ...]:
    if cand is None:
        return ()
    try:
        return tuple(cand.signature())
    except Exception:  # pragma: no cover - 防御自定义候选对象
        return ()


#: JSONL 中每步保留的 ``info`` 字段白名单（真实环境的 ``info`` 可能很大，
#: 例如 ``obs_extra`` 含全部引擎标签；落盘只保留分析常用的紧凑字段）。
JSONL_INFO_KEYS: Tuple[str, ...] = (
    "turn", "phase", "rank", "health", "armor", "alive_count",
    "combat", "invalid", "wrong_action", "terminated_reason",
    "seed", "episode_steps", "episode",
)

#: ``Observation.extra``（ENV_SPEC v2）中适合放进 JSONL 摘要的紧凑字段。
#: 默认**不落盘**（extra 可能含 powers/board_states 等大结构，实测 ~12KB/步）；
#: ``obs_summary(..., include_extra=True)`` / collector ``--include-extra`` 才写。
SUMMARY_EXTRA_KEYS: Tuple[str, ...] = (
    "frozen_tavern", "free_refresh_left", "refresh_cost",
    "gold_spent_this_turn", "cards_played_this_turn",
    "minions_sold_this_turn", "tavern_spells_cast_this_turn",
    "quest_progress", "quest_target", "quest_completed",
)


@dataclass
class Transition:
    """一步转移（含前后观测，便于 BC / 离线分析）。

    注意：``next_obs`` 保留整条 :class:`Observation`，大批量采集时内存占用
    与步数线性相关；collector 默认**只把摘要写 JSONL**，不落盘完整观测。
    """

    obs: Observation
    action: int
    action_kind: str = ""
    action_signature: Tuple[Any, ...] = ()
    reward: float = 0.0
    next_obs: Optional[Observation] = None
    terminated: bool = False
    truncated: bool = False
    info: Dict[str, Any] = field(default_factory=dict)
    episode_id: int = 0
    seed: int = 0
    #: 终局名次（仅整局最后一步填充；-1 = 未知）
    rank: int = -1
    step: int = 0
    invalid: bool = False

    def to_dict(
        self,
        *,
        include_obs: bool = True,
        include_extra: bool = False,
        info_keys: Optional[Sequence[str]] = JSONL_INFO_KEYS,
    ) -> Dict[str, Any]:
        """转成 JSONL 行（``type="step"``）。

        ``info_keys``：``None`` = 全部 JSON-safe 字段；``()`` = 不写 info；
        默认只写 :data:`JSONL_INFO_KEYS` 白名单（避免环境把大字典塞进 info）。
        ``include_extra``：是否把 ``Observation.extra`` 白名单字段写进 obs 摘要。
        """
        if info_keys is None:
            info = {k: v for k, v in (self.info or {}).items()
                    if _is_jsonable(v)}
        else:
            info = {k: (self.info or {})[k] for k in info_keys
                    if k in (self.info or {}) and _is_jsonable((self.info or {})[k])}
        row: Dict[str, Any] = {
            "type": "step",
            "v": SCHEMA_VERSION,
            "episode_id": int(self.episode_id),
            "seed": int(self.seed),
            "step": int(self.step),
            "turn": int(getattr(self.obs, "turn", 0) or 0),
            "phase": str(getattr(self.obs, "phase", "")),
            "action": int(self.action),
            "action_kind": self.action_kind,
            "action_signature": list(self.action_signature),
            "reward": float(self.reward),
            "terminated": bool(self.terminated),
            "truncated": bool(self.truncated),
            "invalid": bool(self.invalid),
            "rank": int(self.rank),
            "n_candidates": len(getattr(self.obs, "candidates", ()) or ()),
            "candidate_max": CANDIDATE_MAX,
        }
        if include_obs:
            row["obs"] = obs_summary(self.obs, include_extra=include_extra)
        if info:
            row["info"] = info
        return row


@dataclass
class EpisodeRecord:
    """一整局的轨迹与汇总。"""

    episode_id: int = 0
    seed: int = 0
    rank: int = 0
    total_reward: float = 0.0
    turns: int = 0
    steps: int = 0
    terminated: bool = False
    truncated: bool = False
    reason: str = ""
    num_players: int = 8
    invalid_actions: int = 0
    policy: str = ""
    wall_seconds: float = 0.0
    transitions: List[Transition] = field(default_factory=list)
    error: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    # ── 便捷访问 ──
    def __len__(self) -> int:
        return len(self.transitions)

    @property
    def episode_key(self) -> Tuple[int, int]:
        """断点续采主键：(episode_id, seed)。"""
        return (int(self.episode_id), int(self.seed))

    def action_kinds(self) -> Dict[str, int]:
        hist: Dict[str, int] = {}
        for tr in self.transitions:
            hist[tr.action_kind] = hist.get(tr.action_kind, 0) + 1
        return hist

    def summary_dict(self) -> Dict[str, Any]:
        """整局汇总（不含逐步数据；JSONL ``type="episode"``）。"""
        return {
            "type": "episode",
            "v": SCHEMA_VERSION,
            "episode_id": int(self.episode_id),
            "seed": int(self.seed),
            "rank": int(self.rank),
            "total_reward": float(self.total_reward),
            "turns": int(self.turns),
            "steps": int(self.steps),
            "terminated": bool(self.terminated),
            "truncated": bool(self.truncated),
            "reason": self.reason,
            "invalid_actions": int(self.invalid_actions),
            "policy": self.policy,
            "num_players": int(self.num_players),
            "wall_ms": round(float(self.wall_seconds) * 1000.0, 3),
            **({"error": self.error} if self.error else {}),
        }

    def to_jsonl_lines(
        self,
        *,
        per_step: bool = True,
        include_board: bool = True,
        include_extra: bool = False,
        info_keys: Optional[Sequence[str]] = JSONL_INFO_KEYS,
    ) -> Iterator[Dict[str, Any]]:
        """产出 JSONL 行：若干 ``type="step"`` + 一条 ``type="episode"``。"""
        if per_step:
            for tr in self.transitions:
                row = tr.to_dict(include_obs=True, include_extra=include_extra,
                                 info_keys=info_keys)
                if not include_board and isinstance(row.get("obs"), dict):
                    row["obs"].pop("board", None)
                    row["obs"].pop("hand", None)
                    row["obs"].pop("tavern", None)
                yield row
        yield self.summary_dict()

    def observations(self) -> List[Observation]:
        return [tr.obs for tr in self.transitions]


# ══════════════════════════════════════════════════════════════════════
# 动作解析 / 观测摘要 / 单局驱动
# ══════════════════════════════════════════════════════════════════════


def candidate_index(action: ActionLike, obs: Observation) -> Optional[int]:
    """把 ``int`` / ``CandidateAction`` 归一成候选下标；非法返回 ``None``。"""
    cands = tuple(getattr(obs, "candidates", ()) or ())
    if action is None:
        return None
    if isinstance(action, bool):
        return None
    if isinstance(action, int):
        return action if 0 <= action < len(cands) else None
    # numpy 整数 / 其他数值类型
    try:
        idx = int(action)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        idx = -1
    else:
        return idx if 0 <= idx < len(cands) else None
    sig = _signature_of(action)  # type: ignore[arg-type]
    if sig:
        for i, cand in enumerate(cands):
            if _signature_of(cand) == sig:
                return i
    return None


def fallback_index(obs: Observation, *, prefer: str = "end_turn") -> int:
    """非法动作的兜底：优先 ``end_turn``，否则最后一个候选，最后 0。"""
    cands = tuple(getattr(obs, "candidates", ()) or ())
    if not cands:
        return 0
    for i, cand in enumerate(cands):
        if _kind_of(cand) == prefer:
            return i
    return len(cands) - 1


def resolve_action(action: ActionLike, obs: Observation) -> Tuple[int, Optional[CandidateAction], bool]:
    """返回 ``(index, candidate, invalid)``；无候选时 index=0 / candidate=None。"""
    cands = tuple(getattr(obs, "candidates", ()) or ())
    idx = candidate_index(action, obs)
    invalid = idx is None
    if invalid:
        idx = fallback_index(obs)
    cand = cands[idx] if 0 <= idx < len(cands) else None
    return int(idx), cand, bool(invalid)


def _is_jsonable(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_jsonable(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_jsonable(v) for k, v in value.items())
    return False


def _entity_ids(tokens: Sequence[EntityToken], limit: int = 8) -> List[str]:
    out: List[str] = []
    for tok in list(tokens or ())[:limit]:
        card_id = getattr(tok, "card_id", "")
        out.append(str(card_id) if card_id else "")
    return out


def obs_summary(
    obs: Observation,
    *,
    include_board: bool = True,
    include_extra: bool = False,
) -> Dict[str, Any]:
    """观测的 JSON 安全摘要（用于 JSONL 与分析；**不含**完整实体特征）。

    ``include_extra=True`` 时额外带上 :data:`SUMMARY_EXTRA_KEYS` 白名单里的
    ``Observation.extra`` 字段（ENV_SPEC v2：frozen/任务进度等），默认关闭以
    避免 JSONL 膨胀（真实环境 extra 可达 ~12KB/步）。
    """
    hero = getattr(obs, "hero", None)
    pending = getattr(obs, "pending_choice", None)
    board = tuple(getattr(obs, "board", ()) or ())
    hand = tuple(getattr(obs, "hand", ()) or ())
    tavern = tuple(getattr(obs, "tavern", ()) or ())
    trinkets = tuple(getattr(obs, "trinkets", ()) or ())
    opponent = tuple(getattr(obs, "opponent_board", ()) or ())
    candidates = tuple(getattr(obs, "candidates", ()) or ())
    summary: Dict[str, Any] = {
        "turn": int(getattr(obs, "turn", 0) or 0),
        "phase": str(getattr(obs, "phase", "")),
        "gold": int(getattr(hero, "gold", 0) or 0) if hero is not None else 0,
        "tier": int(getattr(hero, "tier", 0) or 0) if hero is not None else 0,
        "health": int(getattr(hero, "health", 0) or 0) if hero is not None else 0,
        "armor": int(getattr(hero, "armor", 0) or 0) if hero is not None else 0,
        "rank": int(getattr(obs, "rank", 0) or 0),
        "alive": int(getattr(obs, "alive_count", 0) or 0),
        "total": int(getattr(obs, "total_players", 0) or 0),
        "pending_choice": str(getattr(pending, "kind", "") if pending is not None else ""),
        "board_size": len(board),
        "hand_size": len(hand),
        "tavern_size": len(tavern),
        "trinket_size": len(trinkets),
        "opponent_size": len(opponent),
        "has_quest": bool(getattr(obs, "quest", None) is not None),
        "n_candidates": len(candidates),
        "candidate_kinds": [_kind_of(c) for c in candidates],
    }
    if include_board:
        summary["board"] = _entity_ids(board)
        summary["hand"] = _entity_ids(hand)
        summary["tavern"] = _entity_ids(tavern)
    if include_extra:
        extra = getattr(obs, "extra", None)
        if isinstance(extra, dict):
            picked = {
                key: extra[key] for key in SUMMARY_EXTRA_KEYS
                if key in extra and _is_jsonable(extra[key])
            }
            if picked:
                summary["extra"] = picked
    return summary


def obs_digest(obs: Observation) -> str:
    """观测摘要的短哈希（去重/对齐分析用，稳定跨进程）。"""
    payload = json.dumps(obs_summary(obs), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def header_record(**meta: Any) -> Dict[str, Any]:
    """JSONL 头行（每个文件一条，记录采集配置）。"""
    row: Dict[str, Any] = {
        "type": "header",
        "v": SCHEMA_VERSION,
        "api_version": API_VERSION,
        "obs_version": OBS_VERSION,
        "candidate_max": CANDIDATE_MAX,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    for key, value in meta.items():
        row[str(key)] = value if _is_jsonable(value) else str(value)
    return row


def error_record(
    *, episode_id: int = -1, seed: int = -1, error: str, worker: int = -1
) -> Dict[str, Any]:
    return {
        "type": "error",
        "v": SCHEMA_VERSION,
        "episode_id": int(episode_id),
        "seed": int(seed),
        "worker": int(worker),
        "error": str(error),
    }


def run_episode(
    env: EnvLike,
    policy: Any,
    *,
    seed: Optional[int] = None,
    episode_id: int = 0,
    max_steps: int = 2000,
    deterministic: bool = False,
    rng: Optional[random.Random] = None,
    collect_transitions: bool = True,
    include_next_obs: bool = True,
    on_step: Optional[Callable[[Transition], None]] = None,
    num_players: Optional[int] = None,
) -> EpisodeRecord:
    """跑完一局，返回 :class:`EpisodeRecord`（collector/evaluate 共用）。

    参数
    ----
    env : EnvLike
        单环境实例（会被 ``reset(seed=...)``）。
    policy : 任意 Policy-like
        需要有 ``act(obs, deterministic=..., rng=...) -> int|CandidateAction``；
        也接受纯 ``callable(obs [, rng])``（内部包成 :class:`CallableAdapter`）。
    max_steps : int
        单局步数硬上限；超过后 ``truncated=True``（防御性，防止策略死循环）。
    rng : random.Random
        策略随机源；不传则用 ``random.Random(seed)``，保证同 seed 可复现。
    """
    from hsbg.rl.policies import as_policy  # 延迟导入避免循环

    policy_impl = as_policy(policy)
    if rng is None:
        rng = random.Random(seed if seed is not None else 0)
    # 需要 env 内部状态的策略（如 teacher）先绑定当前环境，再 reset 内部状态
    bind_fn = getattr(policy_impl, "bind_env", None)
    if callable(bind_fn):
        bind_fn(env)
    reset_fn = getattr(policy_impl, "reset", None)
    if callable(reset_fn):
        reset_fn()
    if num_players is None:
        num_players = int(getattr(env, "num_players", 0) or 8)

    t0 = time.perf_counter()
    transitions: List[Transition] = []
    obs = env.reset(seed=seed)
    total_reward = 0.0
    steps = 0
    invalid_steps = 0
    terminated = truncated = False
    reason = ""
    info: Dict[str, Any] = {}
    turns = int(getattr(obs, "turn", 0) or 0)
    while True:
        candidates = tuple(getattr(obs, "candidates", ()) or ())
        if not candidates:
            truncated = True
            reason = "no_candidates"
            break
        action_obj = policy_impl.act(obs, deterministic=deterministic, rng=rng)
        idx, cand, invalid = resolve_action(action_obj, obs)
        if invalid:
            invalid_steps += 1
        next_obs, reward, terminated, truncated, info = env.step(cand)
        info = dict(info or {})
        transition = Transition(
            obs=obs,
            action=int(idx),
            action_kind=_kind_of(cand),
            action_signature=_signature_of(cand),
            reward=float(reward),
            next_obs=next_obs if include_next_obs else None,
            terminated=bool(terminated),
            truncated=bool(truncated),
            info=info,
            episode_id=int(episode_id),
            seed=int(seed if seed is not None else 0),
            rank=int(info.get("rank", -1) or -1),
            step=steps,
            invalid=bool(invalid),
        )
        if collect_transitions:
            transitions.append(transition)
        if on_step is not None:
            on_step(transition)
        total_reward += float(reward)
        steps += 1
        turns = int(info.get("turn", getattr(next_obs, "turn", turns)) or turns)
        obs = next_obs
        if terminated or truncated:
            reason = str(info.get("terminated_reason", "") or
                         ("terminated" if terminated else "truncated"))
            break
        if steps >= max_steps:
            truncated = True
            reason = "step_cap"
            break
    rank = int(info.get("rank", 0) or 0)
    if rank <= 0:
        rank = int(getattr(obs, "rank", 0) or 0)
    wall = time.perf_counter() - t0
    record = EpisodeRecord(
        episode_id=int(episode_id),
        seed=int(seed if seed is not None else 0),
        rank=rank,
        total_reward=float(total_reward),
        turns=int(turns),
        steps=int(steps),
        terminated=bool(terminated),
        truncated=bool(truncated),
        reason=reason,
        num_players=int(num_players),
        invalid_actions=int(invalid_steps),
        policy=str(getattr(policy_impl, "name", type(policy_impl).__name__)),
        wall_seconds=float(wall),
        transitions=transitions,
    )
    return record


# ══════════════════════════════════════════════════════════════════════
# 供 JSONL 读取/校验使用
# ══════════════════════════════════════════════════════════════════════

#: JSONL 各类型行的必需字段（tests / 下游工具校验用）
REQUIRED_FIELDS: Dict[str, Tuple[str, ...]] = {
    "header": ("type", "v", "api_version", "obs_version", "candidate_max"),
    "step": (
        "type", "v", "episode_id", "seed", "step", "turn", "phase",
        "action", "action_kind", "action_signature", "reward",
        "terminated", "truncated", "invalid", "rank", "n_candidates", "obs",
    ),
    "episode": (
        "type", "v", "episode_id", "seed", "rank", "total_reward",
        "turns", "steps", "terminated", "truncated", "reason",
        "invalid_actions", "policy", "num_players",
    ),
    "error": ("type", "v", "episode_id", "seed", "error"),
}


def validate_record(row: Mapping[str, Any]) -> None:
    """校验一条 JSONL 行；字段/类型不符抛 :class:`ValueError`。"""
    kind = row.get("type")
    if kind not in REQUIRED_FIELDS:
        raise ValueError(f"未知记录类型: {kind!r}")
    missing = [k for k in REQUIRED_FIELDS[kind] if k not in row]
    if missing:
        raise ValueError(f"{kind} 记录缺少字段: {missing}")
    if kind == "step":
        if not isinstance(row["action"], int) or row["action"] < 0:
            raise ValueError(f"非法 action: {row['action']!r}")
        obs = row["obs"]
        if not isinstance(obs, dict) or "turn" not in obs:
            raise ValueError("step.obs 摘要不合法")


__all__ = [
    "SCHEMA_VERSION",
    "API_VERSION",
    "OBS_VERSION",
    "JSONL_INFO_KEYS",
    "SUMMARY_EXTRA_KEYS",
    "ActionLike",
    "Policy",
    "EnvLike",
    "Transition",
    "EpisodeRecord",
    "REQUIRED_FIELDS",
    "candidate_index",
    "fallback_index",
    "resolve_action",
    "obs_summary",
    "obs_digest",
    "header_record",
    "error_record",
    "run_episode",
    "validate_record",
]
