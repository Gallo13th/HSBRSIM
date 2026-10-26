"""环境级精确存档 / 恢复（``snapshot`` / ``restore`` / ``clone_env``）。

定位
----
``hsbg.planning.checkpoint`` 提供的是**引擎层**快照（``Game`` 的 clone），
但 RL 环境（``hsbg.env.BattlegroundsEnv``）在引擎之上还有一层状态：
名次追踪（``_rank_by_hero`` / ``_elimination_order``）、大厅视图
（``_all_heroes``）、事件监听绑定、每步候选（``_step_actions``）、
观测缓存（``_obs``）、预算/无进展计数、统计与选择留痕。只 clone
``Game`` 无法恢复这些——恢复后的事件回调仍指向快照时的“幽灵 env”，
名次映射的 ``id(hero)`` 键全部失效。

本模块提供**环境级**精确存档/恢复契约（见 ``docs/ENV_SNAPSHOT.md``）：

.. code-block:: python

    snap = snapshot(env)          # O(几 ms)，不改变原 env
    ...                           # 任意推进（env 被 step 很多次）
    restore(env, snap)            # 原地恢复：obs/候选/统计/RNG 逐位一致
    obs, r, ... = env.step(...)   # 与“不 snapshot 的原始轨迹”逐步一致

    twin = clone_env(env)         # 独立 env 副本（共享只读 db/魔数配置）

快照覆盖范围
------------
* **引擎状态**：``clone(env.game)``（``hsbg.planning.model.clone``）——含
  RNG、PendingChoice、pending_hand_queue、deferred_actions、卡池、卡牌
  缓存、战斗记忆等；
* **名次追踪**：``_rank_by_hero`` 按 ``hero.uuid`` 存（``id()`` 在恢复后
  全变）；``_elimination_order`` 存被淘汰英雄最小重建信息
  （uuid/name/card_id/health/armor/tier）；
* **大厅视图**：``_all_heroes`` 与 ``game.heroes`` 在 ``reset`` 里是
  **同一个 list 对象**（实测；淘汰时一起原地缩短）——恢复时重建同一
  别名关系，否则后续淘汰的 ``remove`` 只改 ``game.heroes``，大厅视图漂移；
* **事件监听**：快照时把绑定到本 env 的监听器（``HERO_ELIMINATED`` /
  ``COMBAT_END``）从临时 clone 源上**剥离**（clone 前），记录
  ``(event, 位置, 回调函数名, owner uuid, once/survives_combat/_fired)``；
  恢复时重建为新 ``Listener``，回调绑到**目标 env**、owner 指向恢复后的
  智能体英雄。恢复末尾还会扫描一次监听器表，把任何仍指向旧 env 实例
  （“幽灵 env”）的回调重绑到目标 env（双保险）；
* **环境计数器/历史**：``_step_count`` / ``_turn_count`` / ``_done`` /
  ``_was_truncated`` / ``_budget_turn`` / ``_actions_this_turn`` /
  ``_no_progress`` / ``_stats`` / ``_turn_stats`` / ``_errors`` /
  ``_auto_resolved_choices`` / ``_choice_failures`` / ``_engine_error`` /
  ``_seed`` / ``_episode`` / ``_agent_index``；
* **观测与候选**：恢复后调用真实 ``env._observe()`` 重建 ``_obs`` 与
  ``_step_actions``——为不污染 ``_stats``，``_observe`` 期间把
  ``env._stats`` 临时替换为“丢弃写入”的统计袋，结束后恢复快照统计并
  把 ``obs.extra["env_stats"]`` 校正为快照值；因此恢复出的观测与快照
  时刻的观测**逐字段相等**（verify 默认开启，断言该性质）。

不覆盖 / 限制
-------------
1. **对手策略实例状态不重建**（``env._policies`` 保留目标 env 的实例）。
   ``HeuristicPolicy`` 的内部状态按 ``(id(hero), turn)`` 懒重置，决策步
   边界上必然已跨回合，故不影响逐步一致性；自定义**跨回合有状态**对手
   不在本契约内（见 docs）。
2. **事件监听器条件/partial 不支持**：env 自身的监听器目前均为普通绑定
   方法；若未来出现 ``condition`` 或 ``functools.partial`` 类型的
   env-owned 监听器，``snapshot`` 会抛 :class:`SnapshotError` 而不是静默
   丢监听器。
3. **终止后不可快照**：``env._done`` / ``_closed`` / 智能体已死亡时
   ``snapshot`` 抛 :class:`SnapshotError`（终局状态不进入训练回放）；
   需要回放终局请自行保存 ``obs``/``info``。
4. **快照只在决策步稳态有效**：要求 ``_turn_count == game.turn`` 且
   ``_budget_turn == game.turn``（正常 ``reset``/``step`` 返回后成立；
   外部直接改 game 状态后不保证）。不满足时抛错而不是产出不一致快照。
5. **快照不可跨构造配置恢复**：``restore`` 到 ``num_players`` /
   ``agent_index`` 不同的 env 抛错；``clone_env`` 只做浅拷贝 + restore。
6. **策略外部 RNG / 采样器状态**不在 env 状态内，需调用方自行管理。

性能（实测，macOS + CPython，8 人局；详见 ``docs/ENV_SNAPSHOT.md`` §6）
--------------------------------------------------------------------
snapshot ≈ 1 clone（1–3ms）+ digest（~2ms）+ obs 深拷贝（<0.5ms）；
restore ≈ clone + 重建 obs/候选（<1ms）+ 校验。T1/T5/T10 均在 20ms 内。
"""

from __future__ import annotations

import copy
import dataclasses
import enum as enum_Enum
import re
import types
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.tags import GameTag

from hsbg.env import driver
from hsbg.env.game_env import BattlegroundsEnv
from hsbg.env.invariants import state_digest
from hsbg.env.spec import (
    PHASE_CHOICE,
    PHASE_GAME_OVER,
    ActionKind,
    EnvConfig,
    Observation,
)
from hsbg.planning.model import clone

__all__ = [
    "EnvSnapshot",
    "SnapshotError",
    "snapshot",
    "restore",
    "clone_env",
    "canonical_observation",
    "SNAPSHOT_VERSION",
]

#: 快照格式版本（字段增删时递增；restore 拒绝更高版本）
SNAPSHOT_VERSION = 1

#: env 在引擎事件上注册的监听器（event -> 回调函数名）。snapshot 会扫描
#: 全部 env-owned 监听器并记录函数名，不依赖这份清单；这里仅用于文档与
#: 恢复后的必检项（缺失说明监听器被意外注销）。
_ENV_OWNED_LISTENERS = (
    ("hero_eliminated", "_on_hero_eliminated"),
    ("combat_end", "_on_combat_end"),
)


class SnapshotError(RuntimeError):
    """快照/恢复契约被违反（不可快照状态、快照被修改、目标 env 不兼容等）。"""


# ══════════════════════════════════════════════════════════════════════
# 快照数据结构
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class _HeroMeta:
    """被淘汰英雄的最小重建信息（hero 对象在恢复后需重建）。"""

    uuid: str
    name: str
    card_id: str
    health: int
    armor: int
    tier: int


@dataclass(frozen=True)
class _ListenerSpec:
    """env-owned 事件监听器的重建信息。"""

    event: str
    index: int
    callback_name: str
    owner_uuid: Optional[str]
    owner_name: str
    once: bool
    survives_combat: bool
    fired: bool


@dataclass(frozen=True)
class EnvSnapshot:
    """一个环境级不可变快照（由 :func:`snapshot` 生成）。

    字段全部为纯数据或**独立 clone** 的引擎对象；``restore`` 每次都会再
    ``clone(snap.game)``，因此同一快照可反复恢复、互不影响。
    """

    version: int
    game: Any                        # clone 出来的独立 Game（不可外部推进）
    game_digest: str                 # 快照时刻 state_digest(game)
    agent_uuid: str
    agent_name: str
    all_heroes_uuids: Tuple[str, ...]
    rank_by_uuid: Dict[str, int]
    elimination_order: Tuple[_HeroMeta, ...]
    counters: Dict[str, Any]
    stats: Dict[str, int]
    turn_stats: Dict[str, int]
    errors: Tuple[str, ...]
    auto_resolved_choices: Tuple[Dict[str, Any], ...]
    choice_failures: Tuple[Dict[str, Any], ...]
    listener_specs: Tuple[_ListenerSpec, ...]
    obs: Optional[Observation]
    candidates: Tuple[Tuple[Any, ...], ...]
    config: EnvConfig
    env_meta: Dict[str, Any] = field(default_factory=dict)

    # ── 便捷属性 ──

    @property
    def turn(self) -> int:
        return int(self.counters.get("turn_count", 0))

    @property
    def step_count(self) -> int:
        return int(self.counters.get("step_count", 0))

    def summary(self) -> Dict[str, Any]:
        """人类可读摘要（日志/断言失败信息用；不含引擎对象）。"""
        return {
            "version": int(self.version),
            "turn": self.turn,
            "step_count": self.step_count,
            "phase": getattr(self.obs, "phase", None),
            "num_candidates": len(self.candidates),
            "alive_heroes": len(self.all_heroes_uuids),
            "eliminated": len(self.elimination_order),
            "game_digest": self.game_digest[:16],
            "n_errors": len(self.errors),
        }

    def __repr__(self) -> str:                            # pragma: no cover
        s = self.summary()
        return (f"EnvSnapshot(turn={s['turn']}, steps={s['step_count']}, "
                f"phase={s['phase']!r}, cand={s['num_candidates']}, "
                f"alive={s['alive_heroes']}, elim={s['eliminated']})")


# ══════════════════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════════════════


def _entity_uuid(entity: Any) -> Optional[str]:
    try:
        uid = getattr(entity, "uuid", None)
        return uid if isinstance(uid, str) and uid else None
    except Exception:                                     # noqa: BLE001
        return None


def _hero_name(hero: Any) -> str:
    try:
        return str(getattr(hero, "name", "") or "")
    except Exception:                                     # noqa: BLE001
        return ""


def _bus_listeners(game: Any) -> Optional[Dict[str, List[Any]]]:
    bus = getattr(game, "events", None)
    listeners = getattr(bus, "_listeners", None) if bus is not None else None
    return listeners if isinstance(listeners, dict) else None


def _is_env_owned_callback(callback: Any, env: Any) -> bool:
    """回调是否为绑定到 ``env`` 的普通方法（快照时需剥离/恢复时需重绑）。"""
    return (isinstance(callback, types.MethodType)
            and getattr(callback, "__self__", None) is env)


def _detach_env_listeners(game: Any, env: Any
                          ) -> List[Tuple[str, int, Listener, _ListenerSpec]]:
    """把绑定到 ``env`` 的事件监听器从 ``game.events`` 临时剥离。

    返回 ``(event, 原下标, Listener, 重建 spec)``；调用方必须在
    ``finally`` 里用 :func:`_reattach_detached` 原样放回（快照不改变原
    env 状态），而 clone 出来的快照 game 里**不含** env 回调（避免
    clone 拷贝出“幽灵 env”，也避免把对手策略等 env 状态拖进快照）。
    """
    listeners = _bus_listeners(game)
    detached: List[Tuple[str, int, Listener, _ListenerSpec]] = []
    if listeners is None:
        return detached
    for event in list(listeners.keys()):
        items = list(listeners.get(event) or [])
        kept: List[Any] = []
        for index, listener in enumerate(items):
            callback = getattr(listener, "callback", None)
            if not _is_env_owned_callback(callback, env):
                kept.append(listener)
                continue
            func = getattr(callback, "__func__", None)
            name = getattr(func, "__name__", None)
            if not isinstance(name, str) or not name:
                raise SnapshotError(
                    f"无法记录 env 监听器回调（event={event!r}）：不是普通"
                    f"绑定方法")
            if getattr(listener, "condition", None) is not None:
                raise SnapshotError(
                    f"env 监听器带 condition（event={event!r}），"
                    f"当前快照契约不支持")
            owner = getattr(listener, "owner", None)
            detached.append((str(event), index, listener, _ListenerSpec(
                event=str(event),
                index=int(index),
                callback_name=str(name),
                owner_uuid=_entity_uuid(owner),
                owner_name=_hero_name(owner),
                once=bool(getattr(listener, "once", False)),
                survives_combat=bool(getattr(listener,
                                             "survives_combat", False)),
                fired=bool(getattr(listener, "_fired", False)),
            )))
        listeners[event] = kept
    return detached


def _reattach_detached(game: Any,
                       detached: List[Tuple[str, int, Listener, _ListenerSpec]]
                       ) -> None:
    """把 :func:`_detach_env_listeners` 剥离的监听器**原对象**放回原位。"""
    listeners = _bus_listeners(game)
    if listeners is None:
        return
    by_event: Dict[str, List[Tuple[int, Any]]] = {}
    for event, index, listener, _spec in detached:
        by_event.setdefault(str(event), []).append((int(index), listener))
    for event, pairs in by_event.items():
        arr = listeners.setdefault(event, [])
        for index, listener in sorted(pairs, key=lambda kv: kv[0]):
            arr.insert(min(int(index), len(arr)), listener)


def _resolve_hero(game: Any, uuid: Optional[str], name: str = "",
                  extra: Optional[List[Any]] = None) -> Optional[Any]:
    """按 uuid（首选）/ seat 名在 ``game.heroes`` 与 ``extra`` 中定位英雄。"""
    pools: List[Any] = [list(getattr(game, "heroes", None) or [])]
    if extra:
        pools.append(list(extra))
    if uuid:
        for pool in pools:
            for hero in pool:
                if _entity_uuid(hero) == uuid:
                    return hero
    if name:
        for pool in pools:
            for hero in pool:
                if _hero_name(hero) == name:
                    return hero
    return None


def _rebuild_eliminated_hero(meta: _HeroMeta, game: Any) -> Hero:
    """按最小信息重建已淘汰英雄（脱离 ``game.heroes``，仅名次/日志用）。"""
    hero = Hero(str(meta.card_id), str(meta.name))
    if meta.uuid:
        hero.uuid = str(meta.uuid)
    hero.game = game
    try:
        hero.health = max(0, int(meta.health))
    except Exception:                                     # noqa: BLE001
        hero.health = 0
    try:
        hero.armor = max(0, int(meta.armor))
    except Exception:                                     # noqa: BLE001
        hero.armor = 0
    try:
        hero.set(GameTag.TAVERN_TIER, max(1, int(meta.tier)))
    except Exception:                                     # noqa: BLE001
        pass
    return hero


class _NullStats(dict):
    """``_observe`` 重建期间使用的统计袋：吞掉写入、缺失键读 0/默认值。

    目的：复用真实的 ``env._observe()``（保证候选/观测与引擎枚举逻辑零
    分叉），但不让重建动作污染 ``env._stats``（快照统计需逐位恢复）。
    """

    def __setitem__(self, key: Any, value: Any) -> None:  # noqa: D401
        return None

    def __getitem__(self, key: Any) -> Any:               # noqa: D401
        return 0

    def get(self, key: Any, default: Any = None) -> Any:  # noqa: D401
        return default

    def update(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401
        return None


def _rebuild_obs_and_actions(env: BattlegroundsEnv
                             ) -> Tuple[Observation, str]:
    """用真实 ``env._observe()`` 重建 ``_obs`` / ``_step_actions``（不污染统计）。

    返回 ``(obs, phase)``。``obs.extra["env_stats"]`` 在 ``_observe`` 内
    取的是临时统计袋（空）→ 这里校正为 ``env._stats``（= 快照统计），
    使结果与快照时刻的观测逐字段相等。
    """
    stats_backup = env._stats
    null_stats = _NullStats()
    env._stats = null_stats                          # type: ignore[assignment]
    try:
        obs = env._observe()
    finally:
        env._stats = stats_backup
    # 重建期 `_observe` 可能改动 `_budget_turn/_actions_this_turn/_no_progress`
    # ——快照要求 `_budget_turn == game.turn`（snapshot 已校验），故同步函数
    # 为空操作；这里再兜底校正一次，保证恢复后的计数逐位等于快照。
    extra = dict(obs.extra)
    extra["env_stats"] = dict(env._stats)
    obs.extra = extra
    return obs, str(obs.phase)


def _install_env_listeners(game: Any, env: BattlegroundsEnv, agent: Any,
                           specs: Tuple[_ListenerSpec, ...],
                           extra_heroes: Optional[List[Any]] = None) -> None:
    """在恢复后的 game 上重建 env-owned 监听器（回调绑到目标 env）。"""
    listeners = _bus_listeners(game)
    if listeners is None:
        raise SnapshotError("恢复目标 game 没有 EventBus，无法重建 env 监听器")
    # 先剔除任何仍指向**某个 env 实例**的回调（旧快照/幽灵 env 双保险）。
    # 注意：实体绑定的绑定方法（__self__ 是 Minion/Hero）**不能**剔除——
    # 它们的 __self__.game 就是本 game，曾因按 game 判定而误删全部实体监听
    # （导致恢复后战斗/EoT 效果顺序错乱）。
    for event in list(listeners.keys()):
        kept = []
        for listener in listeners.get(event) or []:
            callback = getattr(listener, "callback", None)
            if isinstance(getattr(callback, "__self__", None),
                          BattlegroundsEnv):
                continue
            kept.append(listener)
        listeners[event] = kept
    by_event: Dict[str, List[_ListenerSpec]] = {}
    for spec in specs:
        by_event.setdefault(str(spec.event), []).append(spec)
    extra_heroes = list(extra_heroes or [])
    for event, event_specs in by_event.items():
        arr = listeners.setdefault(event, [])
        for spec in sorted(event_specs, key=lambda s: (s.index, s.event)):
            callback = getattr(env, spec.callback_name, None)
            if not callable(callback):
                raise SnapshotError(
                    f"目标 env 缺少监听器回调 {spec.callback_name!r}"
                    f"（event={event!r}）")
            owner = _resolve_hero(game, spec.owner_uuid, spec.owner_name,
                                  extra=extra_heroes)
            if owner is None:
                owner = agent
            listener = Listener(event=str(event), owner=owner,
                                callback=callback, condition=None,
                                once=bool(spec.once),
                                survives_combat=bool(spec.survives_combat))
            listener._fired = bool(spec.fired)
            arr.insert(min(int(spec.index), len(arr)), listener)
    # 双保险：扫描所有监听器，把仍指向旧 env 实例的回调重绑到目标 env
    _rebind_ghost_env_callbacks(game, env, agent)


def _rebind_ghost_env_callbacks(game: Any, env: BattlegroundsEnv,
                                agent: Any) -> None:
    """把监听器中残留的“幽灵 env”绑定方法重绑到目标 env。"""
    listeners = _bus_listeners(game)
    if listeners is None:
        return
    for event, arr in listeners.items():
        for listener in list(arr):
            callback = getattr(listener, "callback", None)
            bound_to = getattr(callback, "__self__", None)
            if not isinstance(callback, types.MethodType):
                continue
            if not isinstance(bound_to, BattlegroundsEnv):
                continue
            if bound_to is env:
                continue
            name = getattr(getattr(callback, "__func__", None), "__name__", "")
            target = getattr(env, str(name), None)
            if not callable(target):
                continue
            listener.callback = target
            if event in dict(_ENV_OWNED_LISTENERS) or \
                    any(ev == event for ev, _fn in _ENV_OWNED_LISTENERS):
                if agent is not None:
                    listener.owner = agent


def _env_spec(env: BattlegroundsEnv) -> Dict[str, Any]:
    """构造配置摘要（用于目标兼容性校验/文档；不含策略实例）。"""
    cfg = env.config
    return {
        "num_players": int(getattr(cfg, "num_players", 0)),
        "agent_index": int(getattr(cfg, "agent_index", 0)),
        "opponent": str(getattr(cfg, "opponent", "")),
        "hero_id": getattr(cfg, "hero_id", None),
        "anomaly": getattr(cfg, "anomaly", None),
        "max_turns": int(getattr(cfg, "max_turns", 0)),
        "max_steps": int(getattr(cfg, "max_steps", 0)),
        "auto_choice": bool(getattr(cfg, "auto_choice", False)),
        "seed": getattr(env, "_seed", None),
        "data_dir": getattr(env, "_data_dir", None),
        "max_opponent_actions": int(
            getattr(env, "_max_opponent_actions", 0)),
        "max_actions_per_turn": int(
            getattr(env, "_max_actions_per_turn", 0)),
        "opponent_kwargs": dict(getattr(env, "_opponent_kwargs", None) or {}),
    }


def _candidate_signatures(env: BattlegroundsEnv
                          ) -> Tuple[Tuple[Any, ...], ...]:
    try:
        return tuple(tuple(c.signature()) for c in env.legal_actions())
    except Exception as exc:                              # noqa: BLE001
        raise SnapshotError(
            f"env.legal_actions() 读取失败: {type(exc).__name__}: {exc}"
            ) from exc


# ══════════════════════════════════════════════════════════════════════
# clone 的回调重绑补丁（完整闭包/默认参数/共享可变捕获）
# ══════════════════════════════════════════════════════════════════════
#
# 为什么需要补丁（2026-10-26 WS5 实测）：
# `hsbg.planning.model.clone` 的 ``_rebind_callback_containers`` 只做两件事：
#   ① 只重绑 ``__closure__`` cell，**不重绑函数默认参数**——引擎脚本大量
#      使用 ``def on_x(..., _owner=hero)``（hsrl2/scripts 内 20+ 处）捕获
#      绑定英雄，clone 后回调仍写**原** hero（实测 seed=42 P4 Edwin
#      `_edwin_buys` 计数在恢复后写进原对局对象 → hero_power 增益差 1）；
#   ② 对不在 clone memo 里的闭包可变捕获值**逐函数 deepcopy**——同一
#      ``state`` dict 被多个闭包共享时（Dark Gift ``_gift_replication`` /
#      ``_gift_incubation`` / ``_affinity`` 的 SoT+EoT 闭包对）被复制成
#      各自独立副本，共享计数被拆散（实测 seed=3 恢复后 EoT 复制效果
#      永不触发 → hand/pending_hand_queue 漂移）。
#
# 本补丁在 snapshot/restore 内用 ``clone(..., rebind=False)`` 拿到原始共享
# 函数对象后，自行做**完整重绑**：
#   * 共享映射 ``extra_memo``：同一源对象 → 同一个目标副本（保持闭包间
#     共享的可变状态/容器身份）；
#   * 实体按 uuid 映射到 clone 图（含默认参数里的 `_owner=hero`）；
#   * 覆盖 obj：env 监听器已提前剥离；引擎监听器 callback/condition、
#     pending_choice resolve_callback、deferred_actions/pending_hand_queue、
#     实体 ``_script_overrides``/``scripts``/其它私有属性里的函数、
#     game 私有属性里的容器（成本 ~0.3–1ms）。
# 规划模块修复后可回退为 model.clone，见 docs/ENV_SNAPSHOT.md「已知问题」。
_SHARED_MAX_DEPTH = 12

#: ``map_captured`` 直接共享的原子类型（不可变/进程级共享）
_ATOMIC_TYPES = (
    str, bytes, int, float, bool, complex, type(None), type,
    types.ModuleType, types.BuiltinFunctionType, types.BuiltinMethodType,
    types.MethodWrapperType, types.WrapperDescriptorType,
    types.MethodDescriptorType, types.CodeType, types.GeneratorType,
    types.CoroutineType,
)


def _make_cell(value: Any) -> Any:
    """构造一个持有 ``value`` 的标准 closure cell。"""

    def _cell() -> Any:                               # pragma: no cover
        return value

    return _cell.__closure__[0]


def _entity_uuid_map(game: Any) -> Dict[str, Any]:
    """game 图内 uuid → 实体映射（用于回调重绑的实体映射）。"""
    out: Dict[str, Any] = {}

    def add(entity: Any, depth: int = 0) -> None:
        if entity is None or depth > 6:
            return
        uid = _entity_uuid(entity)
        if uid:
            out.setdefault(uid, entity)
        for attr in ("board", "hand", "tavern", "trinkets",
                     "quest_rewards", "graveyard"):
            for child in list(getattr(entity, attr, None) or []):
                add(child, depth + 1)
        add(getattr(entity, "quest", None), depth + 1)

    for hero in list(getattr(game, "heroes", None) or []):
        add(hero)
    for record in list(getattr(game, "ghost_records", None) or []):
        if isinstance(record, dict):
            for minion in list(record.get("board") or []):
                add(minion)
    for choice in list(getattr(game, "pending_choices", None) or []):
        for option in list(getattr(choice, "options", None) or []):
            if isinstance(option, tuple):
                for part in option:
                    add(part)
            else:
                add(option)
    for item in list(getattr(game, "pending_hand_queue", None) or []):
        if isinstance(item, (tuple, list)):
            for part in item:
                add(part, 1)
    for item in list(getattr(game, "deferred_actions", None) or []):
        if isinstance(item, (tuple, list)):
            for part in item:
                add(part, 1)
    for log_name in ("combat_summon_log", "combat_death_log"):
        for entity in list(getattr(game, log_name, None) or []):
            add(entity)
    for mapping_name in ("_last_opponent_board", "_next_opponent"):
        mapping = getattr(game, mapping_name, None)
        if isinstance(mapping, dict):
            for key, val in mapping.items():
                add(key)
                if isinstance(val, (list, tuple)):
                    for child in val:
                        add(child)
                else:
                    add(val)
    for source in list(getattr(game, "_pending_pairs", None) or []):
        if isinstance(source, (tuple, list)):
            for part in source:
                add(part, 1)
    return out


def _build_graph_map(src_game: Any, dst_game: Any) -> Dict[int, Any]:
    """并行遍历 source/dst 图，建立 ``id(src 对象) → dst 对象`` 映射。

    ``clone(rebind=False)`` 的副本与源图**结构同构**（容器键/长度、实体
    属性一一对应），因此可按结构并行遍历拿到任意可变对象的对应副本。
    用途：闭包捕获的**图内**对象（如 hero 私有属性里的 state dict，同时
    也被回调闭包捕获）必须映射到副本图中的同一对象，否则「图内一份 +
    闭包一份」的共享状态会分裂（实测轨迹在恢复后漂移）。
    """
    mapping: Dict[int, Any] = {}
    seen: set = set()

    def walk(src: Any, dst: Any, depth: int = 0) -> None:
        if depth > 12 or src is None or dst is None or src is dst:
            return
        oid = id(src)
        if oid in seen:
            return
        if type(src) in _ATOMIC_TYPES or isinstance(src, enum_Enum.Enum):
            return
        if isinstance(src, (types.FunctionType, types.MethodType,
                            types.BuiltinFunctionType)):
            return
        seen.add(oid)
        if isinstance(getattr(src, "uuid", None), str):
            mapping[oid] = dst
            attrs_a = getattr(src, "__dict__", None)
            attrs_b = getattr(dst, "__dict__", None)
            if isinstance(attrs_a, dict) and isinstance(attrs_b, dict):
                for key, val in attrs_a.items():
                    if key in attrs_b:
                        walk(val, attrs_b[key], depth + 1)
            return
        if isinstance(src, dict) and isinstance(dst, dict):
            mapping[oid] = dst
            for key, val in src.items():
                if key in dst:
                    walk(val, dst[key], depth + 1)
            return
        if isinstance(src, (list, tuple)) and isinstance(dst, (list, tuple)) \
                and len(src) == len(dst):
            mapping[oid] = dst
            for item_a, item_b in zip(src, dst):
                walk(item_a, item_b, depth + 1)
            return
        if isinstance(src, (set, frozenset)):
            return
        attrs_a = getattr(src, "__dict__", None)
        attrs_b = getattr(dst, "__dict__", None)
        if isinstance(attrs_a, dict) and isinstance(attrs_b, dict) \
                and type(src) is type(dst):
            mapping[oid] = dst
            for key, val in attrs_a.items():
                if key in attrs_b:
                    walk(val, attrs_b[key], depth + 1)

    walk(src_game, dst_game)
    return mapping


class _CloneRebinder:
    """把 ``clone(rebind=False)`` 副本里的共享函数重绑到副本图。

    保证：同一源闭包捕获对象 → 同一副本（共享可变状态不被拆散）；
    源图实体（默认参数/闭包捕获）→ 副本图同 uuid 实体。
    """

    def __init__(self, src_game: Any, dst_game: Any) -> None:
        self.src_game = src_game
        self.dst_game = dst_game
        self.uuid_map = _entity_uuid_map(dst_game)
        self.dst_entity_ids = {id(e) for e in self.uuid_map.values()}
        #: 源图对象 id → 副本图对象（结构并行遍历；见 _build_graph_map）
        self.graph_map = _build_graph_map(src_game, dst_game)
        #: 源捕获对象 id → 目标副本（跨闭包共享）
        self.shared: Dict[int, Any] = {}
        #: 源函数 id → 重绑后的函数
        self.fn_memo: Dict[int, Any] = {}
        self.seen: set = set()
        self.imported_partial = None

    # ── 捕获值映射 ──

    def copy_detached_entity(self, entity: Any, depth: int = 0) -> Any:
        """把**不在目标图中**的实体（仅被回调捕获）复制为脱离副本。

        属性逐项经 :meth:`map_captured` 映射（controller → 目标图英雄、
        game → 目标 game、uuid 保持），并记录到 ``shared`` 保证同一实体
        被多个闭包捕获时共用同一副本。
        """
        oid = id(entity)
        hit = self.shared.get(oid)
        if hit is not None:
            return hit
        try:
            new_entity = object.__new__(type(entity))
        except TypeError:                              # pragma: no cover
            return entity
        self.shared[oid] = new_entity
        attrs = getattr(entity, "__dict__", None)
        if isinstance(attrs, dict):
            for key, val in attrs.items():
                try:
                    setattr(new_entity, key,
                            self.map_captured(val, depth + 1))
                except Exception:                         # noqa: BLE001
                    continue
        return new_entity

    def map_captured(self, value: Any, depth: int = 0) -> Any:
        if depth > _SHARED_MAX_DEPTH:
            return value
        if type(value) in _ATOMIC_TYPES:
            return value
        if value is self.src_game:
            return self.dst_game
        if value is self.dst_game:
            return value
        oid = id(value)
        if oid in self.dst_entity_ids:
            return value
        hit = self.shared.get(oid)
        if hit is not None:
            return hit
        graph_hit = self.graph_map.get(oid)
        if graph_hit is not None:
            # 闭包捕获的**图内**对象 → 副本图中的同一对象（保持图内/闭包
            # 共享状态的身份一致）
            self.shared[oid] = graph_hit
            return graph_hit
        import enum as _enum
        import functools as _functools
        if isinstance(value, _enum.Enum):
            return value
        if isinstance(value, types.MethodType):
            new_method = types.MethodType(
                value.__func__, self.map_captured(value.__self__, depth + 1))
            self.shared[oid] = new_method
            return new_method
        if isinstance(value, types.FunctionType):
            return self.rebind_function(value, depth + 1)
        if isinstance(value, _functools.partial):
            new_partial = _functools.partial(
                self.map_captured(value.func, depth + 1),
                *[self.map_captured(arg, depth + 1) for arg in value.args],
                **{k: self.map_captured(v, depth + 1)
                   for k, v in value.keywords.items()})
            self.shared[oid] = new_partial
            return new_partial
        if isinstance(value, dict):
            new_dict: Dict[Any, Any] = {}
            self.shared[oid] = new_dict
            for key, val in value.items():
                new_dict[self.map_captured(key, depth + 1)] = \
                    self.map_captured(val, depth + 1)
            return new_dict
        if isinstance(value, list):
            new_list: List[Any] = []
            self.shared[oid] = new_list
            new_list.extend(self.map_captured(item, depth + 1)
                            for item in value)
            return new_list
        if isinstance(value, tuple):
            new_tuple = tuple(self.map_captured(item, depth + 1)
                              for item in value)
            self.shared[oid] = new_tuple
            return new_tuple
        if isinstance(value, (set, frozenset)):
            mapped = [self.map_captured(item, depth + 1) for item in value]
            new_set = type(value)(mapped) if isinstance(value, frozenset) \
                else set(mapped)
            self.shared[oid] = new_set
            return new_set
        uid = _entity_uuid(value)
        if uid is not None:
            mapped = self.uuid_map.get(uid)
            if mapped is not None:
                self.shared[oid] = mapped
                return mapped
            # 图外实体（只被闭包/监听器捕获，如"承诺型"效果的已离场
            # 来源随从）：必须重建为**脱离副本**并映射其 controller/game
            # ——否则回调里的 `hero is source.controller` 永远为 False
            # （实测 Laboratory Assistant 的 Fodder 承诺在恢复后失效）。
            return self.copy_detached_entity(value, depth + 1)
        attrs = getattr(value, "__dict__", None)
        params = getattr(type(value), "__dataclass_params__", None)
        if params is not None and getattr(params, "frozen", False):
            # frozen dataclass（如 CardDef）：只读值对象 → 直接共享原对象，
            # 不复制（复制后无法 setattr，会得到空壳——曾导致 choose 结算
            # 回调里的 CardDef.name 变 ""，spell 效果漂移）
            self.shared[oid] = value
            return value
        if isinstance(attrs, dict):
            try:
                new_obj = object.__new__(type(value))
            except TypeError:                         # 内置/扩展类型兜底
                new_obj = None
            if new_obj is not None:
                self.shared[oid] = new_obj
                for key, val in attrs.items():
                    try:
                        object.__setattr__(new_obj, key,
                                           self.map_captured(val, depth + 1))
                    except Exception:                     # noqa: BLE001
                        continue
                return new_obj
        try:
            new_obj = copy.deepcopy(value)
        except Exception:                                 # noqa: BLE001
            return value
        self.shared[oid] = new_obj
        return new_obj

    # ── 函数重绑 ──

    def rebind_function(self, fn: Any, depth: int = 0) -> Any:
        if not isinstance(fn, types.FunctionType):
            return self.map_captured(fn, depth)
        if depth > _SHARED_MAX_DEPTH:
            return fn
        foid = id(fn)
        hit = self.fn_memo.get(foid)
        if hit is not None:
            return hit
        closure = fn.__closure__
        defaults = fn.__defaults__
        kwdefaults = fn.__kwdefaults__
        if not closure and not defaults and not kwdefaults:
            self.fn_memo[foid] = fn
            return fn
        # 先建“骨架”函数并登记 memo，再填 cell —— 处理**自引用/相互递
        # 归**的闭包（如 Game.play_spell 的 `_continue` 递归助手：其
        # closure 捕获自身；旧实现先递归后 memo → 无限展开成 12 层副本，
        # 恢复后 choose 结算回调行为漂移）。
        placeholder_cells = tuple(_make_cell(None) for _ in closure) \
            if closure else None
        new_fn = types.FunctionType(
            fn.__code__, fn.__globals__, fn.__name__,
            None if defaults is None else tuple(defaults),
            placeholder_cells)
        self.fn_memo[foid] = new_fn
        try:
            if defaults:
                new_fn.__defaults__ = tuple(
                    self.map_captured(value, depth + 1) for value in defaults)
            if kwdefaults:
                new_fn.__kwdefaults__ = {
                    key: self.map_captured(value, depth + 1)
                    for key, value in kwdefaults.items()}
            if closure:
                for source_cell, target_cell in zip(closure,
                                                    placeholder_cells):
                    try:
                        value = source_cell.cell_contents
                    except ValueError:                 # 空 cell
                        continue
                    target_cell.cell_contents = self.map_captured(
                        value, depth + 1)
            try:
                new_fn.__dict__.update(fn.__dict__)
            except Exception:                         # noqa: BLE001
                pass
            new_fn.__qualname__ = fn.__qualname__
            new_fn.__module__ = fn.__module__
            new_fn.__doc__ = fn.__doc__
        except Exception:                             # noqa: BLE001
            # 骨架创建后填充失败：退回原函数（保证不崩）
            self.fn_memo[foid] = fn
            return fn
        return new_fn

    # ── 目标图容器内替换函数（原地） ──

    def replace_in(self, value: Any, depth: int = 0) -> Any:
        if value is None or type(value) in _ATOMIC_TYPES:
            return value
        if depth > _SHARED_MAX_DEPTH:
            return value
        if isinstance(value, types.FunctionType):
            return self.rebind_function(value)
        if isinstance(value, types.MethodType):
            return value
        oid = id(value)
        if oid in self.dst_entity_ids or isinstance(value, Game):
            return value
        if isinstance(value, (dict, list, set, tuple, frozenset)):
            if oid in self.seen:
                return value
            self.seen.add(oid)
            if isinstance(value, dict):
                for key in list(value.keys()):
                    value[key] = self.replace_in(value[key], depth + 1)
                return value
            if isinstance(value, list):
                for index, item in enumerate(value):
                    value[index] = self.replace_in(item, depth + 1)
                return value
            if isinstance(value, set):
                items = [self.replace_in(item, depth + 1) for item in value]
                value.clear()
                value.update(items)
                return value
            return type(value)(self.replace_in(item, depth + 1)
                               for item in value)
        if isinstance(value, type):
            return value
        uid = _entity_uuid(value)
        if isinstance(uid, str):
            return value                      # 实体由 rebind_entity 单独处理
        attrs = getattr(value, "__dict__", None)
        if isinstance(attrs, dict):
            if oid in self.seen:
                return value
            self.seen.add(oid)
            for key in list(attrs.keys()):
                try:
                    attrs[key] = self.replace_in(attrs[key], depth + 1)
                except Exception:                     # noqa: BLE001
                    continue
            return value
        return value

    # ── 实体/监听器/回调容器遍历 ──

    def rebind_entity(self, entity: Any, depth: int = 0) -> None:
        if entity is None or depth > 8:
            return
        oid = id(entity)
        if oid in self.seen:
            return
        self.seen.add(oid)
        attrs = getattr(entity, "__dict__", None)
        if not isinstance(attrs, dict):
            return
        for key, val in list(attrs.items()):
            if key in ("game", "controller", "tags"):
                continue
            if key == "scripts":
                if val is not None:
                    self.rebind_object_attrs(val, depth + 1)
                continue
            new_val = self.replace_in(val, depth + 1)
            if new_val is not val:
                attrs[key] = new_val
        for zone in ("board", "hand", "tavern", "trinkets",
                     "quest_rewards", "graveyard"):
            arr = attrs.get(zone)
            if isinstance(arr, (list, tuple)):
                for item in list(arr):
                    self.rebind_entity(item, depth + 1)
        self.rebind_entity(attrs.get("quest"), depth + 1)

    def rebind_object_attrs(self, obj: Any, depth: int = 0) -> None:
        attrs = getattr(obj, "__dict__", None)
        if not isinstance(attrs, dict) or depth > 8:
            return
        oid = id(obj)
        if oid in self.seen:
            return
        self.seen.add(oid)
        for key in list(attrs.keys()):
            try:
                attrs[key] = self.replace_in(attrs[key], depth + 1)
            except Exception:                         # noqa: BLE001
                continue

    def rebind_callback(self, callback: Any) -> Any:
        if callback is None:
            return None
        if isinstance(callback, types.MethodType):
            return callback
        if isinstance(callback, types.FunctionType):
            return self.rebind_function(callback)
        import functools as _functools
        if isinstance(callback, _functools.partial):
            return self.map_captured(callback)
        return callback

    def run(self) -> None:
        dst = self.dst_game
        # 1) 引擎事件监听器
        listeners_map = _bus_listeners(dst) or {}
        for items in listeners_map.values():
            for listener in list(items or []):
                listener.callback = self.rebind_callback(
                    getattr(listener, "callback", None))
                if getattr(listener, "condition", None) is not None:
                    listener.condition = self.rebind_callback(
                        listener.condition)
        # 2) PendingChoice 结算回调
        for choice in list(getattr(dst, "pending_choices", None) or []):
            if getattr(choice, "resolve_callback", None) is not None:
                choice.resolve_callback = self.rebind_callback(
                    choice.resolve_callback)
            for option in list(getattr(choice, "options", None) or []):
                if isinstance(option, tuple):
                    for part in option:
                        self.rebind_entity(part)
                else:
                    self.rebind_entity(option)
        # 3) 延迟动作 / 满手队列（tuple 内函数替换）
        for holder_name in ("deferred_actions", "pending_hand_queue"):
            holder = getattr(dst, holder_name, None)
            if isinstance(holder, list):
                for index, item in enumerate(holder):
                    if isinstance(item, tuple):
                        replaced = tuple(
                            self.rebind_function(part)
                            if isinstance(part, types.FunctionType) else part
                            for part in item)
                        if any(a is not b for a, b in zip(replaced, item)):
                            holder[index] = replaced
                    elif isinstance(item, list):
                        for j, part in enumerate(item):
                            item[j] = self.replace_in(part)
        # 4) 实体树（英雄 + 所有可寻址实体 + 幽灵/队列实体）
        seen_entities = set()
        for hero in list(getattr(dst, "heroes", None) or []):
            self.rebind_entity(hero)
            seen_entities.add(id(hero))
        for entity in list(self.uuid_map.values()):
            if id(entity) not in seen_entities:
                seen_entities.add(id(entity))
                self.rebind_entity(entity)
        # 5) game 私有属性（函数/容器；Game/EventBus/池等跳过）
        attrs = getattr(dst, "__dict__", None)
        if isinstance(attrs, dict):
            for key, val in list(attrs.items()):
                if key in ("db", "events", "rng", "minion_pool",
                           "spell_pool", "heroes", "pending_choices",
                           "queue"):
                    continue
                new_val = self.replace_in(val)
                if new_val is not val:
                    attrs[key] = new_val


def _clone_engine_state(src_game: Any) -> Any:
    """``clone(rebind=False)`` + 完整回调重绑（见本节文档）。"""
    if src_game is None:
        raise SnapshotError("clone 源 game 为 None")
    dst_game = clone(src_game, rebind=False)
    try:
        _CloneRebinder(src_game, dst_game).run()
    except Exception as exc:                              # noqa: BLE001
        raise SnapshotError(
            f"回调重绑失败: {type(exc).__name__}: {exc}") from exc
    return dst_game


# ══════════════════════════════════════════════════════════════════════
# snapshot
# ══════════════════════════════════════════════════════════════════════


def snapshot(env: BattlegroundsEnv) -> EnvSnapshot:
    """保存环境级精确快照（**不改变** ``env`` 状态）。

    契约见模块 docstring / ``docs/ENV_SNAPSHOT.md``。以下状态不可快照
    （抛 :class:`SnapshotError`）：``reset`` 之前 / ``close`` 之后 /
    ``_done=True``（terminated/truncated 之后）/ 智能体已死亡 /
    非决策步稳态（``_turn_count``/``_budget_turn`` 与 ``game.turn`` 不一致）。

    成本：1 次 game clone（~1–3ms）+ ``state_digest``（~2ms）+
    obs 深拷贝（<0.5ms），与回合数弱相关。
    """
    if not isinstance(env, BattlegroundsEnv):
        raise TypeError(f"snapshot expects BattlegroundsEnv, got "
                        f"{type(env).__name__}")
    if bool(getattr(env, "_closed", False)):
        raise SnapshotError("env 已 close()，不可快照")
    game = getattr(env, "game", None)
    if game is None:
        raise SnapshotError("env.reset() 之前不可快照（game is None）")
    if bool(getattr(env, "_done", False)):
        raise SnapshotError(
            "episode 已终止（_done=True），不可快照；终局请保存 obs/info，"
            "或 reset 后重新开始")
    agent = getattr(env, "_agent", None)
    if agent is None:
        raise SnapshotError("env._agent is None（reset 之前不可快照）")
    try:
        agent_alive = bool(agent.is_alive)
    except Exception:                                     # noqa: BLE001
        agent_alive = True
    if not agent_alive:
        raise SnapshotError("智能体已死亡，不可快照（应在 _done 之前结束本局）")
    step_count = int(getattr(env, "_step_count", 0))
    turn_count = int(getattr(env, "_turn_count", 0))
    budget_turn = int(getattr(env, "_budget_turn", turn_count))
    game_turn = int(getattr(game, "turn", 0))
    if turn_count != game_turn or budget_turn != game_turn:
        raise SnapshotError(
            f"env 不处于决策步稳态：_turn_count={turn_count}、"
            f"_budget_turn={budget_turn}、game.turn={game_turn}；"
            f"快照只支持 reset()/step() 正常返回后的状态")
    all_heroes = list(getattr(env, "_all_heroes", None) or [])
    game_heroes = list(getattr(game, "heroes", None) or [])
    if len(all_heroes) != len(game_heroes) or any(
            a is not b for a, b in zip(all_heroes, game_heroes)):
        raise SnapshotError(
            "env._all_heroes 与 game.heroes 不一致（大厅视图漂移），"
            "拒绝产出不一致快照")
    obs = getattr(env, "_obs", None)
    if obs is None:
        raise SnapshotError("env._obs is None（决策步必须有观测）")

    # ── 名次追踪：id(hero) → uuid 映射（恢复后 id() 全变） ──
    elimination_meta: List[_HeroMeta] = []
    uuid_by_id: Dict[int, str] = {}
    for hero in all_heroes:
        uid = _entity_uuid(hero)
        if uid:
            uuid_by_id[id(hero)] = uid
        else:
            raise SnapshotError(f"英雄缺少 uuid: {_hero_name(hero)}")
    eliminated_objs = list(getattr(env, "_elimination_order", None) or [])
    for hero in eliminated_objs:
        uid = _entity_uuid(hero)
        if not uid:
            raise SnapshotError(f"淘汰英雄缺少 uuid: {_hero_name(hero)}")
        uuid_by_id.setdefault(id(hero), uid)
        elimination_meta.append(_HeroMeta(
            uuid=str(uid), name=_hero_name(hero),
            card_id=str(getattr(hero, "card_id", "") or ""),
            health=int(getattr(hero, "health", 0) or 0),
            armor=int(getattr(hero, "armor", 0) or 0),
            tier=int(getattr(hero, "tavern_tier", 1) or 1),
        ))
    rank_map = getattr(env, "_rank_by_hero", None)
    rank_by_uuid: Dict[str, int] = {}
    if isinstance(rank_map, dict):
        for key, rank in rank_map.items():
            uid = uuid_by_id.get(key)
            if uid is None:
                raise SnapshotError(
                    f"_rank_by_hero 含无法定位的英雄 key（id={key}），"
                    f"拒绝产出名次不可恢复的快照")
            rank_by_uuid[str(uid)] = int(rank)

    # ── 计数器/统计/留痕（全部拷贝，快照与原 env 解耦） ──
    counters: Dict[str, Any] = {
        "step_count": step_count,
        "turn_count": turn_count,
        "done": False,
        "was_truncated": bool(getattr(env, "_was_truncated", False)),
        "budget_turn": budget_turn,
        "actions_this_turn": int(getattr(env, "_actions_this_turn", 0)),
        "no_progress": int(getattr(env, "_no_progress", 0)),
        "engine_error": getattr(env, "_engine_error", None),
        "seed": getattr(env, "_seed", None),
        "episode": int(getattr(env, "_episode", 0)),
        "agent_index": int(getattr(env, "_agent_index",
                                   getattr(env.config, "agent_index", 0))),
        "closed": False,
    }
    stats = dict(getattr(env, "_stats", None) or {})
    turn_stats_obj = getattr(env, "_turn_stats", None)
    turn_stats: Dict[str, int] = {}
    if turn_stats_obj is not None:
        for name in ("dealt", "taken", "won", "lost"):
            turn_stats[name] = int(getattr(turn_stats_obj, name, 0) or 0)
    errors = tuple(str(e) for e in
                   (getattr(env, "_errors", None) or []))
    auto_resolved = tuple(dict(r) for r in
                          (getattr(env, "_auto_resolved_choices", None)
                           or []))
    choice_failures = tuple(dict(r) for r in
                            (getattr(env, "_choice_failures", None) or []))

    candidates = _candidate_signatures(env)
    obs_copy = copy.deepcopy(obs)

    # ── clone 引擎状态：先剥离 env-owned 监听器（避免幽灵 env 进快照） ──
    detached = _detach_env_listeners(game, env)
    try:
        game_copy = _clone_engine_state(game)
    except SnapshotError:
        raise
    except Exception as exc:                              # noqa: BLE001
        raise SnapshotError(
            f"game clone 失败: {type(exc).__name__}: {exc}") from exc
    finally:
        _reattach_detached(game, detached)
    listener_specs = tuple(spec for _ev, _idx, _lis, spec in detached)
    game_digest = state_digest(game_copy)

    if not listener_specs:
        # 防御：智能体存活时 env 监听器不应缺席（HERO_ELIMINATED /
        # COMBAT_END 在 reset 里注册；只有智能体淘汰会注销它）。
        raise SnapshotError(
            "未找到任何 env-owned 事件监听器（HERO_ELIMINATED / "
            "COMBAT_END 应绑定到 env）；拒绝产出无法恢复事件回调的快照")

    return EnvSnapshot(
        version=SNAPSHOT_VERSION,
        game=game_copy,
        game_digest=game_digest,
        agent_uuid=str(_entity_uuid(agent) or ""),
        agent_name=_hero_name(agent),
        all_heroes_uuids=tuple(str(_entity_uuid(h)) for h in all_heroes),
        rank_by_uuid=rank_by_uuid,
        elimination_order=tuple(elimination_meta),
        counters=counters,
        stats=stats,
        turn_stats=turn_stats,
        errors=errors,
        auto_resolved_choices=auto_resolved,
        choice_failures=choice_failures,
        listener_specs=listener_specs,
        obs=obs_copy,
        candidates=candidates,
        config=env.config,
        env_meta=_env_spec(env),
    )


# ══════════════════════════════════════════════════════════════════════
# restore
# ══════════════════════════════════════════════════════════════════════


def _check_snapshot_integrity(snap: EnvSnapshot,
                              *, check_digest: bool = True) -> None:
    """拒绝被外部修改/推演过的快照（含 game 被 step、stats 被改）。

    ``check_digest=False``（``restore(..., verify=False)`` 快路径）跳过
    ``state_digest`` 全图遍历——它是恢复耗时的主要成分（见 docs §6）。
    """
    if not isinstance(snap, EnvSnapshot):
        raise TypeError(f"restore expects EnvSnapshot, got "
                        f"{type(snap).__name__}")
    if int(snap.version) > SNAPSHOT_VERSION:
        raise SnapshotError(f"快照版本 {snap.version} 高于本模块支持的 "
                            f"{SNAPSHOT_VERSION}")
    if snap.game is None:
        raise SnapshotError("快照 game 为 None")
    if not check_digest:
        return
    current = state_digest(snap.game)
    if current != snap.game_digest:
        raise SnapshotError(
            "快照被外部修改（game_digest 不匹配）；快照 game 禁止直接推进"
            f"（期望 {snap.game_digest[:12]}…，实际 {current[:12]}…）")


def _validate_target_env(env: Any, snap: EnvSnapshot) -> None:
    if not isinstance(env, BattlegroundsEnv):
        raise TypeError(f"restore expects BattlegroundsEnv, got "
                        f"{type(env).__name__}")
    cfg = getattr(env, "config", None)
    target_players = int(getattr(cfg, "num_players", 0))
    target_agent = int(getattr(cfg, "agent_index", 0))
    snap_players = int(snap.config.num_players)
    snap_agent = int(snap.config.agent_index)
    if target_players != snap_players:
        raise SnapshotError(
            f"目标 env num_players={target_players} != 快照 {snap_players}")
    if target_agent != snap_agent:
        raise SnapshotError(
            f"目标 env agent_index={target_agent} != 快照 {snap_agent}")


def restore(env: BattlegroundsEnv, snap: EnvSnapshot, *,
            verify: bool = True) -> BattlegroundsEnv:
    """把 ``snap`` **原地恢复**到 ``env``（返回 ``env`` 便于链式调用）。

    语义（``docs/ENV_SNAPSHOT.md`` §2）：
    * 恢复后的 ``env._obs`` / ``env.legal_actions()`` / ``env._stats`` 与
      快照时刻**逐位相等**（``verify=True`` 默认断言）；
    * 快照本身不被修改，可反复恢复；
    * 恢复后继续 ``step`` 的观测/奖励/终止与“不快照的原始轨迹”一致
      （由 ``tests/test_env_snapshot.py`` 的逐步对拍覆盖）。

    ``verify=True`` 额外做 3 项校验（失败抛 :class:`SnapshotError`）：
    恢复 game 的 ``state_digest`` == 快照 digest；重建观测 == 快照观测；
    候选签名 == 快照候选。
    """
    if not isinstance(snap, EnvSnapshot):
        raise TypeError(f"restore expects EnvSnapshot, got "
                        f"{type(snap).__name__}")
    _check_snapshot_integrity(snap, check_digest=bool(verify))
    _validate_target_env(env, snap)

    # 1) 独立 clone（不改动快照本身）+ 完整回调重绑补丁
    game = _clone_engine_state(snap.game)

    # 2) 英雄：智能体 + 重建已淘汰英雄
    game_heroes = list(getattr(game, "heroes", None) or [])
    agent = _resolve_hero(game, snap.agent_uuid, snap.agent_name)
    if agent is None:
        raise SnapshotError(
            f"恢复失败：在 clone game 中找不到智能体英雄 "
            f"{snap.agent_name!r}（uuid={snap.agent_uuid!r}）")
    eliminated: List[Hero] = []
    for meta in snap.elimination_order:
        eliminated.append(_rebuild_eliminated_hero(meta, game))
    if verify:
        uuids = tuple(_entity_uuid(h) for h in game_heroes)
        if len(uuids) != len(snap.all_heroes_uuids):
            raise SnapshotError(
                f"恢复后 game.heroes 数量 {len(uuids)} != 快照 "
                f"{len(snap.all_heroes_uuids)}")
        if any(a != b for a, b in zip(uuids, snap.all_heroes_uuids)):
            raise SnapshotError("恢复后 game.heroes uuid 顺序与快照不一致")
    # 3) 名次映射：uuid → 恢复后的 hero 对象（id() 键重建）
    rank_by_hero: Dict[int, int] = {}
    for uid, rank in snap.rank_by_uuid.items():
        hero = _resolve_hero(game, uid, extra=eliminated)
        if hero is None:
            if verify:
                raise SnapshotError(
                    f"恢复名次失败：uuid={uid!r} 的英雄既不在 game.heroes "
                    f"也不在重建的淘汰英雄里")
            continue
        rank_by_hero[id(hero)] = int(rank)

    # 4) 环境标量/容器（全部拷贝，避免 env 与快照共享可变对象）
    env.game = game
    env.db = getattr(game, "db", getattr(env, "db", None))
    env._agent = agent
    env._agent_index = int(snap.counters.get("agent_index",
                                             snap.config.agent_index))
    # 大厅视图：保持与 reset 相同的**同一 list 对象**别名关系
    env._all_heroes = game.heroes
    env._elimination_order = eliminated
    env._rank_by_hero = rank_by_hero
    env._step_count = int(snap.counters.get("step_count", 0))
    env._turn_count = int(snap.counters.get("turn_count", 0))
    env._done = bool(snap.counters.get("done", False))
    env._was_truncated = bool(snap.counters.get("was_truncated", False))
    env._budget_turn = int(snap.counters.get("budget_turn", 0))
    env._actions_this_turn = int(snap.counters.get("actions_this_turn", 0))
    env._no_progress = int(snap.counters.get("no_progress", 0))
    env._engine_error = snap.counters.get("engine_error", None)
    env._seed = snap.counters.get("seed", None)
    env._episode = int(snap.counters.get("episode", 0))
    env._closed = bool(snap.counters.get("closed", False))
    env._stats = dict(snap.stats)
    env._errors = list(snap.errors)
    env._auto_resolved_choices = [dict(r)
                                  for r in snap.auto_resolved_choices]
    env._choice_failures = [dict(r) for r in snap.choice_failures]
    turn_stats = getattr(env, "_turn_stats", None)
    try:
        env._turn_stats = (type(turn_stats) if turn_stats is not None
                           else _SimpleTurnStats)(**dict(snap.turn_stats))
    except Exception:                                     # noqa: BLE001
        env._turn_stats = _SimpleTurnStats(**dict(snap.turn_stats))
    env._step_actions = None
    env._obs = None

    # 5) 重建 env 事件监听（先装监听再重建观测；观测生成不触发事件）
    _install_env_listeners(game, env, agent, snap.listener_specs,
                           extra_heroes=eliminated)
    if verify:
        present = {str(spec.event) for spec in snap.listener_specs}
        for event, callback_name in _ENV_OWNED_LISTENERS:
            if event not in present:
                continue
            found = False
            for listener in (_bus_listeners(game) or {}).get(event, []):
                callback = getattr(listener, "callback", None)
                if getattr(getattr(callback, "__self__", None), "game",
                           None) is game and getattr(callback, "__func__",
                                                     None) is not None:
                    found = True
                    break
            if not found:
                raise SnapshotError(
                    f"恢复后缺少 env 监听器 {event!r}/{callback_name!r}")

    # 6) 重建观测/候选（复用真实 _observe；不污染统计）
    obs, phase = _rebuild_obs_and_actions(env)
    env._obs = obs
    if phase not in (PHASE_CHOICE, PHASE_GAME_OVER):
        # 决策步稳态：_observe 已把 _step_actions 设为本次候选
        pass
    if env._step_actions is None:                         # pragma: no cover
        raise SnapshotError("恢复后 _step_actions 仍为 None")

    # 7) 校验（默认开启：恢复必须逐位一致，失败即报错而非静默漂移）
    if verify:
        if state_digest(env.game) != snap.game_digest:
            raise SnapshotError("恢复后 game digest 与快照不一致")
        if snap.obs is not None and env._obs != snap.obs:
            raise SnapshotError(
                "恢复后观测与快照观测不一致（rebuild 逻辑与 env._observe "
                "分叉）；请检查 env 版本与 snapshot 模块是否匹配")
        got = _candidate_signatures(env)
        if got != snap.candidates:
            raise SnapshotError(
                f"恢复后候选动作与快照不一致（{len(got)} vs "
                f"{len(snap.candidates)}）")
        if dict(env._stats) != dict(snap.stats):
            raise SnapshotError("恢复后 _stats 与快照不一致")
    return env


class _SimpleTurnStats:
    """``_TurnStats`` 的兜底替身（目标 env 版本变化时使用）。"""

    def __init__(self, dealt: int = 0, taken: int = 0,
                 won: int = 0, lost: int = 0) -> None:
        self.dealt = int(dealt)
        self.taken = int(taken)
        self.won = int(won)
        self.lost = int(lost)

    def as_dict(self) -> Dict[str, int]:
        return {"dealt": self.dealt, "taken": self.taken,
                "won": self.won, "lost": self.lost}


# ══════════════════════════════════════════════════════════════════════
# 跨轨迹观测比较（归一化随机实体 id）
# ══════════════════════════════════════════════════════════════════════


_UUID_SUFFIX_RE = re.compile(r":[0-9a-fA-F]{8,}$")


def _canonical_choice_kind(kind: Any) -> str:
    """归一化 PendingChoice.kind 中内嵌的随机 uuid（OBS-DET-1）。"""
    text = str(kind)
    return _UUID_SUFFIX_RE.sub(":<uuid>", text)


def canonical_observation(obs: Optional[Observation]) -> Optional[Observation]:
    """把观测中**随机生成**的 ``entity_id`` 归一化为“槽位顺序 id”。

    背景（引擎既有行为，见 docs/ENV_SNAPSHOT.md「已知问题登记」OBS-DET-1）：
    ``hsrl2.entity.Entity.__init__`` 的 ``uuid = uuid.uuid4()`` 不来自
    ``game.rng`` → **同一 seed 的两次 rollout** 在新建实体上得到不同
    uuid，而观测把 uuid 映射为 ``EntityToken.entity_id`` 并以它为
    ``extra["minion_flags"]`` 的键。因此“快照恢复后继续推进”的观测
    无法与另一条轨迹逐位相等（不 snapshot 的两次同 seed rollout 同样
    如此）。本函数把 entity_id 按**遍历顺序**重编号（棋盘→手牌→酒馆→
    饰品→对手→选择选项；extra 的 board_states/hand_states/minion_flags
    同步重编号），使“结构完全相同”的两条轨迹可比较；**不改变原观测**。

    用途：``tests/test_env_snapshot.py`` 的逐步对拍、外部诊断脚本。
    """
    if obs is None:
        return None
    mapping: Dict[int, int] = {}
    next_id = 1

    def canon(seq: Tuple[Any, ...]) -> Tuple[Any, ...]:
        nonlocal next_id
        out = []
        for token in seq:
            eid = int(getattr(token, "entity_id", 0) or 0)
            if eid and eid not in mapping:
                mapping[eid] = next_id
                next_id += 1
            out.append(dataclasses.replace(
                token, entity_id=int(mapping.get(eid, 0))))
        return tuple(out)

    board = canon(obs.board)
    hand = canon(obs.hand)
    tavern = canon(obs.tavern)
    trinkets = canon(obs.trinkets)
    opponent = canon(obs.opponent_board)
    quest = obs.quest
    if quest is not None:
        quest = canon((quest,))[0]
    pending = obs.pending_choice
    if pending is not None:
        # kind 里可能内嵌随机 uuid（如 "discover_portable_factory:<uuid>"，
        # 见 OBS-DET-1）→ 归一化后才能跨轨迹比较
        pending = dataclasses.replace(
            pending, kind=_canonical_choice_kind(pending.kind),
            options=canon(pending.options))
    extra = dict(obs.extra or {})
    for key in ("board_states", "hand_states"):
        states = extra.get(key)
        if isinstance(states, list):
            new_states = []
            for item in states:
                if not isinstance(item, dict):
                    new_states.append(item)
                    continue
                item = dict(item)
                eid = int(item.get("entity_id", 0) or 0)
                item["entity_id"] = int(mapping.get(eid, 0))
                new_states.append(item)
            extra[key] = new_states
    flags = extra.get("minion_flags")
    if isinstance(flags, dict):
        extra["minion_flags"] = {
            int(mapping.get(int(k), 0)) if isinstance(k, int) else k: v
            for k, v in flags.items()}
    return dataclasses.replace(
        obs, board=board, hand=hand, tavern=tavern, trinkets=trinkets,
        opponent_board=opponent, quest=quest, pending_choice=pending,
        extra=extra)


# ══════════════════════════════════════════════════════════════════════
# clone_env
# ══════════════════════════════════════════════════════════════════════


def clone_env(env: BattlegroundsEnv) -> BattlegroundsEnv:
    """返回 ``env`` 的**独立**环境副本（快照 + 原地恢复到新 env 外壳）。

    实现：``snapshot(env)`` → 浅拷贝 env 外壳（共享只读 ``db`` / 不可变
    ``config`` / **对手策略实例**）→ ``restore(new_env, snap)``。

    与快照一致的限制：对手策略实例共享（见模块 docstring §不覆盖/限制 1）；
    新 env 与源 env 的后续 step 互不影响（引擎状态、计数、监听器均为
    独立副本）。

    成本 ≈ snapshot + restore（8 人局 ~4–6ms；不做 reset，因此不重新
    加载卡库/英雄抽取）。
    """
    if not isinstance(env, BattlegroundsEnv):
        raise TypeError(f"clone_env expects BattlegroundsEnv, got "
                        f"{type(env).__name__}")
    snap = snapshot(env)
    new_env = object.__new__(type(env))
    # 浅拷贝外壳：可变容器随后由 restore 逐项替换；策略实例共享（文档限制）
    new_env.__dict__.update(env.__dict__)
    # 对手策略：优先深拷贝（heuristic/random 状态可独立推进）；不可拷贝时
    # 共享实例（文档限制：自定义有状态策略跨 env 可能互相影响）
    policies: List[Any] = []
    for policy in (getattr(env, "_policies", None) or []):
        try:
            policies.append(copy.deepcopy(policy))
        except Exception:                                 # noqa: BLE001
            policies.append(policy)
    new_env._policies = policies
    new_env._opponent_kwargs = dict(getattr(env, "_opponent_kwargs", None)
                                    or {})
    restore(new_env, snap)
    return new_env
