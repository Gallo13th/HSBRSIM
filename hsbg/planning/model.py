"""计划 / 搜索（AlphaZero 类）所需的**引擎 clone / forward API**。

模块定位
--------
`hsrl2` 是对局模拟引擎（机制权威、但含大量状态：英雄/随从/事件监听/
PendingChoice/随机数流/卡池）。本包不修改引擎，只在其上提供**搜索原语**：

- :func:`clone` —— 快速、完整、可独立推进的状态副本（含 RNG 与选择队列）；
- :func:`legal_actions` —— 当前状态的合法引擎动作（招募期 / 选择步）；
- :func:`apply` —— 应用一个动作（可选自动结算选择）；
- :func:`random_rollout` —— 随机策略模拟若干回合（原地推进，调用方先 clone）；
- :func:`evaluate` —— 局面价值占位（待 policy-builder 接价值头）；
- :class:`RandomRolloutPolicy` —— 与引擎 RNG 解耦、可复现的 rollout 策略。

设计要点
--------
1. **CardDB 只读共享**：`copy.deepcopy(game)` 会连 11MB 卡表一起复制
   （实测 8 人局 140ms/份）；:func:`clone` 用 deepcopy memo 让所有副本共享
   同一个 `game.db`（`CardDef` 是 frozen dataclass，只读安全），实测降到
   ~2–4ms/份。这是让 MCTS 可行性的关键前提。
2. **RNG / 选择队列 / 延迟动作全部复制**：clone 与原始 game 完全解耦，
   同 seed 同动作序列可复现（见 `tests/test_planning.py`）。
3. **不模拟对手招募期**：`random_rollout` 只推进智能体自己的招募动作 +
   调用 `end_recruit_phase()`（对手用**当前**战团参战）。这符合搜索时的
   信息边界：对手下回合买什么不可见，不应在树里"偷看"。
"""

from __future__ import annotations

import copy
import enum as _enum
import functools
import random as _random
import types
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from hsrl2.defs import CardDef
from hsrl2.game import Game, PendingChoice
from hsrl2.hero import Hero
from hsrl2.rng import GameRNG

from hsbg.env import driver

__all__ = [
    "clone",
    "legal_actions",
    "apply",
    "drain_choices",
    "pending_choice",
    "is_terminal",
    "random_rollout",
    "evaluate",
    "simulate_combat",
    "simulate_turn_combat",
    "RolloutResult",
    "RandomRolloutPolicy",
]


# ══════════════════════════════════════════════════════════════════════
# clone
# ══════════════════════════════════════════════════════════════════════


#: ``_fast_copy`` 可直接共享的原子类型（不可变/进程级共享）
_FAST_ATOMIC_TYPES = frozenset((
    str, bytes, int, float, bool, complex, type(None), type,
    types.ModuleType, types.FunctionType, types.BuiltinFunctionType,
    types.BuiltinMethodType, types.MethodWrapperType,
    types.WrapperDescriptorType, types.MethodDescriptorType,
    types.CodeType, types.GeneratorType, types.CoroutineType,
))


def _fast_copy(value: Any, memo: Dict[int, Any]) -> Any:
    """结构化拷贝（planning 专用，替代 ``copy.deepcopy`` 的通用慢路径）。

    设计：
    - 纯 Python 对象按 ``__dict__`` 重建（``copy`` 模块的
      ``__reduce_ex__``/``_keep_alive`` 开销占 deepcopy 90%+）；
    - **不可变值共享**：原子类型、Enum、``CardDef``（frozen）、以及元素全未
      变化的 tuple/frozenset 直接复用原对象（免分配）；
    - 可变容器（dict/list/set）与引擎对象（Game/Hero/Minion/Listener/
      PendingChoice/…）逐层拷贝，memo 处理共享引用与环；
    - ``random.Random`` 用 getstate/setstate 复制（GameRNG 随机流隔离）；
    - 未知/带自定义 ``__deepcopy__``/``__reduce__`` 的类型回退
      ``copy.deepcopy(value, memo)``，保证正确性兜底。

    实测（8 人局）：turn2 ~1.1ms、turn5 ~2.5ms（vs deepcopy 1.7/3.3ms）；
    正确性由 ``test_fast_clone_matches_deepcopy`` 等测试覆盖。
    """
    t = type(value)
    if t in _FAST_ATOMIC_TYPES:
        return value
    oid = id(value)
    hit = memo.get(oid)
    if hit is not None:
        return hit

    if t is dict:
        new_dict: Dict[Any, Any] = {}
        memo[oid] = new_dict
        atomic = _FAST_ATOMIC_TYPES
        for key, val in value.items():
            nk = key if type(key) in atomic else _fast_copy(key, memo)
            nv = val if type(val) in atomic else _fast_copy(val, memo)
            new_dict[nk] = nv
        return new_dict
    if t is list:
        new_list: List[Any] = []
        memo[oid] = new_list
        atomic = _FAST_ATOMIC_TYPES
        append = new_list.append
        for item in value:
            append(item if type(item) in atomic else _fast_copy(item, memo))
        return new_list
    if t is tuple:
        atomic = _FAST_ATOMIC_TYPES
        # 快速通道：元素全为原子/Enum 的 tuple 直接共享（无需递归）
        if all(type(item) in atomic or isinstance(item, _enum.Enum)
               for item in value):
            memo[oid] = value
            return value
        items = tuple(item if type(item) in atomic
                      else _fast_copy(item, memo) for item in value)
        if all(a is b for a, b in zip(items, value)):
            memo[oid] = value                 # 全部元素可共享 → 复用不可变对象
            return value
        memo[oid] = items
        return items
    if t is set:
        new_set: set = set()
        memo[oid] = new_set
        atomic = _FAST_ATOMIC_TYPES
        add = new_set.add
        for item in value:
            add(item if type(item) in atomic else _fast_copy(item, memo))
        return new_set
    if t is frozenset:
        atomic = _FAST_ATOMIC_TYPES
        if all(type(item) in atomic or isinstance(item, _enum.Enum)
               for item in value):
            memo[oid] = value
            return value
        items = frozenset(item if type(item) in atomic
                          else _fast_copy(item, memo) for item in value)
        if all(any(a is b for b in value) for a in items):
            memo[oid] = value
            return value
        memo[oid] = items
        return items
    if t is CardDef:                          # CardDB 卡定义（frozen，只读共享）
        memo[oid] = value
        return value
    if isinstance(value, _enum.Enum):         # GameTag/Race/Zone/...
        memo[oid] = value
        return value
    if isinstance(value, types.MethodType):
        new_method = types.MethodType(_fast_copy(value.__func__, memo),
                                      _fast_copy(value.__self__, memo))
        memo[oid] = new_method
        return new_method
    if isinstance(value, _random.Random):
        new_rng = _random.Random()
        new_rng.setstate(value.getstate())
        memo[oid] = new_rng
        return new_rng
    # 自定义 deepcopy/reduce 的对象：交给标准实现（正确性兜底）
    if getattr(t, "__deepcopy__", None) is not None:
        return copy.deepcopy(value, memo)
    attrs = getattr(value, "__dict__", None)
    if attrs is not None:
        try:
            new_obj = object.__new__(t)
        except TypeError:                     # 内置/扩展类型兜底
            return copy.deepcopy(value, memo)
        memo[oid] = new_obj
        atomic = _FAST_ATOMIC_TYPES
        try:
            # 直接整体替换 __dict__（比逐属性 setattr 快 ~20%）
            new_obj.__dict__ = {
                key: (val if type(val) in atomic
                      else _fast_copy(val, memo))
                for key, val in attrs.items()}
        except (AttributeError, TypeError):
            # frozen dataclass（如 TavernBuff）拒绝 `__dict__=`：绕开
            # 类 `__setattr__` 用 object.__setattr__ 逐字段写入
            for key, val in attrs.items():
                try:
                    object.__setattr__(new_obj, key, _fast_copy(val, memo))
                except (AttributeError, TypeError):
                    continue
        return new_obj
    # __slots__ 类（如 hsrl2.entity.Buff）：按 MRO 槽位拷贝
    slots = getattr(t, "__slots__", None)
    if slots is not None:
        try:
            new_obj = object.__new__(t)
        except TypeError:                     # 内置/扩展类型兜底
            return copy.deepcopy(value, memo)
        memo[oid] = new_obj
        for cls in t.__mro__:
            names = getattr(cls, "__slots__", ())
            if isinstance(names, str):
                names = (names,)
            for name in names:
                if name in ("__dict__", "__weakref__"):
                    continue
                try:
                    val = getattr(value, name)
                except AttributeError:
                    continue
                try:
                    object.__setattr__(new_obj, name, _fast_copy(val, memo))
                except (AttributeError, TypeError):
                    continue
        return new_obj
    return copy.deepcopy(value, memo)


def clone(game: Game, *, rebind: bool = True,
          strategy: str = "fast") -> Game:
    """拷贝一个可**独立推进**的 ``Game``。

    一致性/隔离保证（`tests/test_planning.py` 覆盖）：

    - 英雄/随从/事件监听/PendingChoice/`pending_hand_queue`/
      `deferred_actions`/`_magnetic_stack` 等可变状态全部复制；
    - `game.rng`（GameRNG 内部状态）复制 → 同 seed 同动作可复现；
    - `game.db`（CardDB，只读，`CardDef` frozen）**共享**——否则 deepcopy
      会把整张卡表也复制（实测单份 ~140ms / 11MB，不可用）；
    - 副本与原对象无共享可变引用：任意推进副本不影响原对象。

    **为什么需要 ``rebind``**（重要，2026-10-19 实测）：引擎的
    `PendingChoice.resolve_callback` 与事件 `Listener.callback` 是
    **闭包**（如 `Game._offer_quests.<locals>.resolve` 捕获 `hero/game`），
    而 ``copy.deepcopy`` 把函数当原子对象（返回同一函数）→ 直接 deepcopy 的
    副本里，回调仍指向**原** game/hero：在副本上结算任务选择会改写原对局
    （测试 ``test_clone_rebind_quest_callbacks_do_not_touch_original`` 复现）。
    因此 clone 拷贝后做一次**闭包重绑**：按 memo 的 original→copy 映射重建
    函数闭包（新函数对象，捕获值替换为副本）。

    ``strategy``:
    - ``"fast"``（默认，2026-10-19 起）：:func:`_fast_copy` 结构化拷贝，
      比 ``copy.deepcopy`` 快 1.3–1.6x（8 人局 recruit 中位 ~1.1–2.5ms）；
    - ``"deepcopy"``：标准 ``copy.deepcopy + memo``（正确性基准/对照）。
    ``rebind=False`` 仅供基准对照/只读快照（会复用原回调，**不可**用于会
    结算选择的搜索分支）。
    """
    if game is None:
        raise ValueError("clone(None)")
    db = getattr(game, "db", None)
    if db is None:
        # 理论上 Game 必有 db；缺失时退回原生 deepcopy（慢但正确）
        return copy.deepcopy(game)
    memo: Dict[int, Any] = {id(db): db}
    if strategy == "deepcopy":
        dup = copy.deepcopy(game, memo)
    elif strategy == "fast":
        dup = _fast_copy(game, memo)
    else:
        raise ValueError(f"unknown clone strategy: {strategy!r}")
    if rebind:
        rebind_mode = "targeted" if rebind is True else str(rebind)
        if rebind_mode == "full":
            _rebind_graph(dup, memo, skip_ids={id(db)})
        else:
            # 引擎的回调闭包只存放在这些容器里（`Game._offer_quests` 的
            # PendingChoice.resolve_callback、EventBus 的 Listener、
            # deferred_actions/pending_hand_queue）；定向重绑比全图遍历快
            _rebind_callback_containers(dup, memo)
    return dup


def _rebind_callback_containers(game: Game, memo: Dict[int, Any]) -> None:
    """重绑引擎内存储的闭包回调（PendingChoice / EventBus / 延迟队列）。

    只访问"回调容器"，不遍历整棵实体图（性能：8 人局 <0.1ms vs 全图
    ~1.5ms）。`rebind="full"` 时退回 :func:`_rebind_graph` 兜底。
    """
    fn_seen: Dict[int, Any] = {}

    def rebind(fn):
        return _rebind_function(fn, memo, fn_seen) \
            if callable(fn) else fn

    for ch in list(getattr(game, "pending_choices", []) or []):
        cb = getattr(ch, "resolve_callback", None)
        if cb is not None:
            try:
                ch.resolve_callback = rebind(cb)
            except Exception:                             # noqa: BLE001
                pass
    bus = getattr(game, "events", None)
    listeners = getattr(bus, "_listeners", None) if bus is not None else None
    if isinstance(listeners, dict):
        for _event, items in listeners.items():
            for lis in list(items or ()):
                try:
                    lis.callback = rebind(lis.callback)
                    if getattr(lis, "condition", None) is not None:
                        lis.condition = rebind(lis.condition)
                except Exception:                         # noqa: BLE001
                    continue
    for holder_name in ("deferred_actions", "pending_hand_queue"):
        for item in list(getattr(game, holder_name, []) or []):
            if isinstance(item, tuple):
                for part in item:
                    if isinstance(part, types.FunctionType):
                        rebind(part)


# ── clone 后处理：把闭包/回调里捕获的原始对象引用重绑到副本 ──

_ATOMIC_TYPES = (str, bytes, int, float, bool, complex, type(None),
                 type, types.ModuleType, types.BuiltinFunctionType,
                 types.BuiltinMethodType, types.GeneratorType,
                 types.CoroutineType)


def _make_cell(value: Any):
    """构造一个持有 ``value`` 的标准 closure cell。"""

    def _cell() -> Any:                               # pragma: no cover
        return value

    return _cell.__closure__[0]


def _rebind_closure_value(value: Any, memo: Dict[int, Any],
                          fn_seen: Dict[int, Any]) -> Any:
    """闭包变量 → 副本对应对象（memo 未收录的可变对象则就地深拷贝）。"""
    if value is None or isinstance(value, _ATOMIC_TYPES):
        return value
    if isinstance(value, types.MethodType):
        return value
    if isinstance(value, types.FunctionType):
        return _rebind_function(value, memo, fn_seen)
    if isinstance(value, functools.partial):
        return functools.partial(
            _rebind_closure_value(value.func, memo, fn_seen),
            *[_rebind_closure_value(a, memo, fn_seen) for a in value.args],
            **{k: _rebind_closure_value(v, memo, fn_seen)
               for k, v in value.keywords.items()})
    if id(value) in memo:
        return memo[id(value)]
    if isinstance(value, (list, dict, tuple, set, frozenset)) \
            or hasattr(value, "__dict__"):
        try:
            return copy.deepcopy(value, memo)
        except Exception:                                     # noqa: BLE001
            return value
    return value


def _rebind_function(fn: Any, memo: Dict[int, Any],
                     fn_seen: Dict[int, Any]) -> Any:
    """返回"闭包引用已替换为副本对象"的新函数；无需替换则原样返回。"""
    if not isinstance(fn, types.FunctionType) or fn.__closure__ is None:
        return fn
    if id(fn) in fn_seen:
        return fn_seen[id(fn)]
    new_cells = []
    changed = False
    for cell in fn.__closure__:
        try:
            value = cell.cell_contents
        except ValueError:                                    # 空 cell
            new_cells.append(cell)
            continue
        new_value = _rebind_closure_value(value, memo, fn_seen)
        if new_value is not value:
            changed = True
        new_cells.append(_make_cell(new_value))
    if not changed:
        fn_seen[id(fn)] = fn
        return fn
    new_fn = types.FunctionType(fn.__code__, fn.__globals__, fn.__name__,
                                fn.__defaults__, tuple(new_cells))
    new_fn.__kwdefaults__ = fn.__kwdefaults__
    try:
        new_fn.__dict__.update(fn.__dict__)
    except Exception:                                         # noqa: BLE001
        pass
    new_fn.__qualname__ = fn.__qualname__
    new_fn.__module__ = fn.__module__
    fn_seen[id(fn)] = new_fn
    return new_fn


def _rebind_graph(root: Any, memo: Dict[int, Any],
                  skip_ids: Optional[set] = None) -> None:
    """遍历副本属性树，把闭包函数/partial 替换为已重绑版本（原地）。"""
    skip = set(skip_ids or ())
    skip.add(id(root))
    fn_seen: Dict[int, Any] = {}
    seen: Dict[int, Any] = {}

    def walk(value: Any) -> Any:
        if value is None or isinstance(value, _ATOMIC_TYPES):
            return value
        if isinstance(value, types.FunctionType):
            return _rebind_function(value, memo, fn_seen)
        if isinstance(value, functools.partial):
            return functools.partial(
                walk(value.func),
                *[walk(a) for a in value.args],
                **{k: walk(v) for k, v in value.keywords.items()})
        if isinstance(value, types.MethodType):
            return value                     # deepcopy 已把 __self__ 绑到副本
        if id(value) in skip:
            return value
        if isinstance(value, list):
            for i, item in enumerate(value):
                value[i] = walk(item)
            return value
        if isinstance(value, dict):
            for key in list(value.keys()):
                value[key] = walk(value[key])
            return value
        if isinstance(value, set):
            items = [walk(item) for item in value]
            value.clear()
            value.update(items)
            return value
        if isinstance(value, (tuple, frozenset)):
            return type(value)(walk(item) for item in value)
        oid = id(value)
        if oid in seen:
            return seen[oid]
        if hasattr(value, "__dict__"):
            seen[oid] = value
            for key, val in list(value.__dict__.items()):
                try:
                    setattr(value, key, walk(val))
                except (AttributeError, TypeError):           # noqa: BLE001
                    continue
        return value

    for key, val in list(root.__dict__.items()):
        if id(val) in skip or key == "db":
            continue
        try:
            setattr(root, key, walk(val))
        except (AttributeError, TypeError):                   # noqa: BLE001
            continue


# ══════════════════════════════════════════════════════════════════════
# 合法动作 / 动作应用
# ══════════════════════════════════════════════════════════════════════


def _default_hero(game: Game, hero: Optional[Hero]) -> Hero:
    if hero is not None:
        return hero
    if not game.heroes:
        raise ValueError("game 没有英雄")
    return game.heroes[0]


def pending_choice(game: Game,
                   hero: Optional[Hero] = None) -> Optional[PendingChoice]:
    """该英雄当前需要决策的 PendingChoice（队列头且 owner 匹配）。"""
    hero = _default_hero(game, hero)
    if not game.pending_choices:
        return None
    head = game.pending_choices[0]
    return head if getattr(head, "owner", None) is hero else None


def legal_actions(game: Game, hero: Optional[Hero] = None
                  ) -> List[driver.ActionDescriptor]:
    """当前合法动作（引擎描述符）。

    - 若该英雄有 PendingChoice → 返回 ``choose`` 候选（option=下标）；
    - 否则返回招募期动作（buy/play/sell/技能/刷新/升级/冻结/end_turn …）。
    """
    hero = _default_hero(game, hero)
    choice = pending_choice(game, hero)
    if choice is not None:
        return driver.enumerate_choice(game, choice)
    return driver.enumerate_actions(game, hero)


def apply(game: Game, hero: Optional[Hero],
          action: Any, *, auto_choice: bool = False,
          choice_policy: Optional[Callable[[PendingChoice, Game], int]] = None
          ) -> driver.ApplyResult:
    """应用动作并返回 ``ApplyResult``（非法动作不抛异常）。

    ``action`` 支持：
    - ``int`` —— :func:`legal_actions` 的下标；
    - :class:`hsbg.env.driver.ActionDescriptor` —— 直接使用；
    - :class:`hsbg.env.spec.CandidateAction` —— 按签名在合法动作中解析。

    ``auto_choice=True`` 时动作成功后自动结算选择（该英雄的选择用
    ``choice_policy``，缺省 ``driver.default_pick_index``）。
    """
    hero = _default_hero(game, hero)
    action_list = legal_actions(game, hero)
    if isinstance(action, bool):
        return driver.ApplyResult(False, "", "bool 不是动作", "TypeError")
    if isinstance(action, int):
        if not 0 <= action < len(action_list):
            return driver.ApplyResult(
                False, "", f"action index {action} out of range", "IndexError")
        desc = action_list[action]
    elif isinstance(action, driver.ActionDescriptor):
        desc = action
    else:
        # CandidateAction / tuple：按签名匹配
        try:
            sig = action.signature() if hasattr(action, "signature") \
                else driver.CandidateAction(*action).signature()
        except Exception:                                 # noqa: BLE001
            return driver.ApplyResult(False, "", "bad action", "TypeError")
        desc = next((d for d in action_list
                     if d.to_candidate().signature() == sig), None)
        if desc is None:
            return driver.ApplyResult(
                False, "", "action not in legal_actions", "ValueError")
    result = driver.apply_action(game, hero, desc)
    if result.success and auto_choice:
        drain_choices(game, hero, choice_policy)
    return result


def drain_choices(game: Game, hero: Optional[Hero] = None,
                  choice_policy: Optional[Callable[[PendingChoice, Game], int]]
                  = None) -> Optional[PendingChoice]:
    """结算所有 PendingChoice：英雄自己的选择用 ``choice_policy``（缺省
    引擎默认策略 ``default_pick_index``），其余（对手/发现）自动结算。

    返回结算后队列中下一个属于该英雄的 PendingChoice（无则 None）。
    """
    hero = _default_hero(game, hero)

    def _policy(choice: PendingChoice) -> int:
        if getattr(choice, "owner", None) is hero and choice_policy is not None:
            try:
                return int(choice_policy(choice, game))
            except Exception:                             # noqa: BLE001
                pass
        return int(driver.default_pick_index(choice, game))

    errors: List[str] = []
    driver.resolve_pending_choices(game, hero, _policy, errors=errors)
    return pending_choice(game, hero)


def is_terminal(game: Game, hero: Optional[Hero] = None) -> bool:
    """该英雄视角是否终局（死亡或游戏结束）。"""
    hero = _default_hero(game, hero)
    return (not hero.is_alive) or bool(game.finished)


# ══════════════════════════════════════════════════════════════════════
# 战斗模拟（无副作用）
# ══════════════════════════════════════════════════════════════════════


def simulate_combat(game: Game, hero_a: Hero, hero_b: Hero,
                    *, alive_count: Optional[int] = None,
                    keep_state: bool = False,
                    ) -> tuple:
    """**无副作用**的战斗裁决：在 clone 上跑 ``run_combat``。

    引擎 ``run_combat`` 会改双方英雄生命、战团、战斗日志与 `combat_memory`
    —— 直接调用会污染搜索树节点/原对局。本函数：

    1. ``dup = clone(game)``；
    2. 按 ``game.heroes.index`` 把 ``hero_a/hero_b`` 映射到副本实体；
    3. ``dup.run_combat(a, b, alive_count=...)``；
    4. 返回 ``(summary: dict, dup_or_None)``；``keep_state=True`` 时返回
       推进后的副本（可继续 forward/作为子节点）。

    ``summary`` 键：``winner/loser``（hero card_id）、``damage_dealt``、
    ``capped_damage``、``rounds``、``hero_a_alive/hero_b_alive``、
    ``hero_index_a/hero_index_b``、``finished``。
    """
    if game is None:
        raise ValueError("simulate_combat(None)")
    try:
        idx_a = game.heroes.index(hero_a)
        idx_b = game.heroes.index(hero_b)
    except ValueError as exc:
        raise ValueError("hero 不属于该 game") from exc
    dup = clone(game)
    # 战斗前把待选选择结算掉（否则 run_combat 内部可能因 owner 已死而挂起）
    try:
        drain_choices(dup, None)
    except Exception:                                     # noqa: BLE001
        pass
    result = dup.run_combat(dup.heroes[idx_a], dup.heroes[idx_b],
                            alive_count=alive_count)
    summary = {
        "winner": str(getattr(getattr(result, "winner", None), "card_id", "") or ""),
        "loser": str(getattr(getattr(result, "loser", None), "card_id", "") or ""),
        "damage_dealt": int(getattr(result, "damage_dealt", 0) or 0),
        "capped_damage": int(getattr(result, "capped_damage", 0) or 0),
        "rounds": int(getattr(result, "rounds", 0) or 0),
        "hero_a_alive": bool(dup.heroes[idx_a].is_alive),
        "hero_b_alive": bool(dup.heroes[idx_b].is_alive),
        "hero_index_a": int(idx_a),
        "hero_index_b": int(idx_b),
        "finished": bool(dup.finished),
    }
    return summary, (dup if keep_state else None)



# ══════════════════════════════════════════════════════════════════════
# rollout
# ══════════════════════════════════════════════════════════════════════


@dataclass
class RolloutResult:
    """一次 rollout 的结果（终局/截断/名次/存活/回合与步数）。"""

    terminated: bool = False
    truncated: bool = False
    rank: int = 0
    health: int = 0
    turns: int = 0
    steps: int = 0
    alive: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {"terminated": self.terminated, "truncated": self.truncated,
                "rank": int(self.rank), "health": int(self.health),
                "turns": int(self.turns), "steps": int(self.steps),
                "alive": bool(self.alive)}


class RandomRolloutPolicy:
    """确定性随机 rollout 策略（**独立 RNG**，不扰动引擎随机流）。

    - 招募期：以 ``end_turn_prob`` 结束回合，否则在非 end_turn 合法动作中
      等概率选一个；
    - 选择步：在选项中等概率选一个；
    - RNG 用独立 :class:`GameRNG`（seed 化），因此同一局面 + 同一策略 seed
      的 rollout 完全可复现，且不改变 ``game.rng`` 的后续取值。
    """

    def __init__(self, seed: int = 0, end_turn_prob: float = 0.2):
        self.rng = GameRNG(int(seed))
        self.end_turn_prob = float(end_turn_prob)

    def choose_action(self, game: Game, hero: Hero
                      ) -> Optional[driver.ActionDescriptor]:
        actions = legal_actions(game, hero)
        if not actions:
            return None
        if pending_choice(game, hero) is not None:
            return actions[self.rng.randint(0, len(actions) - 1)]
        end = [d for d in actions
               if d.kind == driver.ActionKind.END_TURN.value]
        others = [d for d in actions
                  if d.kind != driver.ActionKind.END_TURN.value]
        if end and (not others or self.rng.random() < self.end_turn_prob):
            return end[0]
        if not others:
            return end[0] if end else None
        return others[self.rng.randint(0, len(others) - 1)]

    def choose_option_index(self, choice: PendingChoice, game: Game) -> int:
        n = len(getattr(choice, "options", ()) or ())
        return 0 if n <= 1 else int(self.rng.randint(0, n - 1))


def random_rollout(game: Game, hero: Optional[Hero] = None,
                   policy: Optional[RandomRolloutPolicy] = None,
                   *, max_turns: int = 1, max_steps: int = 400
                   ) -> RolloutResult:
    """从当前局面**原地**随机推进 ``max_turns`` 个招募回合并返回结果。

    - 调用方应先 :func:`clone`（本函数不负责隔离）；
    - 每步：策略选动作 → :func:`apply` → 结算所有 PendingChoice
      （英雄选择用策略，其余自动）；遇到 end_turn 调
      ``game.end_recruit_phase()``（对手用当前战团参战，不模拟其买牌）；
    - 终局（英雄死亡/游戏结束）或步数上限即停；``max_turns`` 为已完成的
      end_turn 次数上限。
    """
    hero = _default_hero(game, hero)
    policy = policy or RandomRolloutPolicy(seed=0)
    result = RolloutResult(health=int(hero.health), alive=bool(hero.is_alive))
    if is_terminal(game, hero):
        result.terminated = True
        result.rank = _rank(game, hero)
        result.health = int(hero.health)
        result.alive = bool(hero.is_alive)
        return result

    turns = 0
    for _step in range(max_steps):
        result.steps += 1
        choice = pending_choice(game, hero)
        if choice is not None:
            option = policy.choose_option_index(choice, game)
            if not game.pending_choices or game.pending_choices[0] is not choice:
                continue
            game.pending_choices.pop(0)
            try:
                choice.choose(option)
            except Exception:                             # noqa: BLE001
                pass
            drain_choices(game, hero, policy.choose_option_index)
            if is_terminal(game, hero):
                result.terminated = True
                break
            continue

        action = policy.choose_action(game, hero)
        if action is None:
            result.truncated = True
            break
        res = apply(game, hero, action)
        if not res.success:
            # 策略与驱动枚举不一致（理论上不发生）：换 end_turn 兜底
            ends = [d for d in legal_actions(game, hero)
                    if d.kind == driver.ActionKind.END_TURN.value]
            if not ends:
                result.truncated = True
                break
            action = ends[0]
            if not apply(game, hero, action).success:
                result.truncated = True
                break
        drain_choices(game, hero, policy.choose_option_index)
        if action.kind == driver.ActionKind.END_TURN.value:
            if is_terminal(game, hero):
                result.terminated = True
                break
            # 回合推进：drive 招募结束（对手用当前战团、战斗、淘汰、下一回合）
            game.end_recruit_phase()
            drain_choices(game, hero, policy.choose_option_index)
            turns += 1
            if is_terminal(game, hero):
                result.terminated = True
                break
            if turns >= int(max_turns):
                break
    else:                                                 # pragma: no cover
        result.truncated = True

    result.turns = turns
    result.health = int(hero.health) if hero.is_alive else 0
    result.alive = bool(hero.is_alive)
    result.rank = _rank(game, hero)
    return result


def simulate_turn_combat(game: Game, hero: Hero,
                         opponent: Optional[Hero] = None, *,
                         alive_count: Optional[int] = None,
                         keep_state: bool = False) -> tuple:
    """**快速 forward**：agent 回合只有战斗裁决（不初始化下一回合）。

    与 ``simulate_combat`` 的区别：自动选择当前配对对手（``next_opponent``
    或首个存活对手），适合搜索的"叶节点价值"——省掉
    ``end_recruit_phase`` 里对 8 个英雄的下一回合初始化（实测 ERP 20ms
    中 ~14ms 是 `_offer_trinkets` 的 pool 过滤；搜索叶节点通常不需要）。

    返回 ``(summary, dup_or_None)``；``keep_state=True`` 时 dup 为战后状态，
    可继续读 ``evaluate(dup, hero)``/做浅层评估。代价 ≈ clone + run_combat
    （8p 实测 ~3–5ms，见 ``scripts/bench_planning.py``）。
    """
    if opponent is None:
        try:
            opponent = game.next_opponent(hero)
        except Exception:                                 # noqa: BLE001
            opponent = None
        if opponent is None or opponent is hero:
            opponent = next((h for h in game.heroes
                              if h is not hero and h.is_alive), None)
    if opponent is None:
        raise ValueError("simulate_turn_combat: 没有可对战的存活对手")
    summary, dup = simulate_combat(game, hero, opponent,
                                   alive_count=alive_count,
                                   keep_state=True)
    hero_after = dup.heroes[summary["hero_index_a"]]
    summary["value"] = float(evaluate(dup, hero_after)["value"])
    summary["winner_is_hero"] = (
        summary["winner"] == str(getattr(hero, "card_id", "")))
    summary["hero_alive_after"] = bool(hero_after.is_alive)
    return summary, (dup if keep_state else None)


def _rank(game: Game, hero: Hero) -> int:
    """估计名次（淘汰后按存活数；存活按血量粗估；终局冠军=1）。"""
    if not hero.is_alive:
        return max(1, sum(1 for h in game.heroes if h.is_alive) + 1)
    if game.finished:
        return 1
    my_hp = int(hero.health) + int(hero.armor)
    better = sum(1 for h in game.heroes
                 if h is not hero and h.is_alive
                 and int(h.health) + int(h.armor) > my_hp)
    return 1 + better


# ══════════════════════════════════════════════════════════════════════
# 价值占位
# ══════════════════════════════════════════════════════════════════════


def evaluate(game: Game, hero: Optional[Hero] = None) -> Dict[str, float]:
    """局面价值**占位**（待 policy-builder 的价值头替换）。

    返回::

        {"value": float(-1..1), "board_power": int, "health": int,
         "armor": int, "tier": int, "hand": int, "alive": int,
         "rank_estimate": int}

    当前 value 是手工归一化的局面强度（场面战力 + 生命 + 科技 + 手牌），
    仅用于 MCTS 冒烟/基准，**不可用于训练评估**。
    """
    from math import tanh

    hero = _default_hero(game, hero)
    board_power = 0
    for m in hero.board:
        board_power += int(getattr(m, "atk", 0) or 0)
        board_power += int(getattr(m, "health", 0) or 0)
    health = int(hero.health)
    armor = int(hero.armor)
    tier = int(hero.tavern_tier)
    hand = len(hero.hand)
    alive = sum(1 for h in game.heroes if h.is_alive)
    rank = _rank(game, hero)
    # 归一化占位（scale 与 ENV_SPEC 的 board_power/health 同量级）
    raw = (board_power / 60.0) + (health + armor) / 40.0 \
        + tier / 6.0 + hand / 10.0 - 1.0
    if not hero.is_alive:
        raw -= 2.0
    elif game.finished and rank == 1:
        raw += 1.0
    return {
        "value": float(tanh(raw)),
        "board_power": float(board_power),
        "health": float(health),
        "armor": float(armor),
        "tier": float(tier),
        "hand": float(hand),
        "alive": float(alive),
        "rank_estimate": float(rank),
    }
