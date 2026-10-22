"""策略注册表 / 适配器（观测级 ``Policy`` 协议的官方实现）。

支持四类"策略规格"（policy spec）：

1. **内置观测级名字**：``random`` / ``heuristic`` / ``first`` / ``end_turn``
   （只读 ``Observation``，可移植；gym/mock/离线分析均可用）；
2. **内置引擎感知教师**：``teacher``（绑定到真实环境后调用
   ``hsbg.agents.heuristic.HeuristicPolicy``，棋力接近环境自带对手，
   **仅真环境**可用，用于高质量离线采集 / BC 教师）；
3. **checkpoint 路径**：``runs/train/policy_final.pt``（含词表，自包含；
   ``hsbg.policy.model.load_policy_and_encoder`` 延迟加载，推理默认贪心）；
4. **任意 callable / Policy-like 对象**：``fn(obs)``、``fn(obs, rng)``、
   或实现 ``act(obs, *, deterministic=False, rng=None) -> int`` 的对象。

需要 env 内部状态的策略（目前只有 ``teacher``）实现 ``bind_env(env)``；
:func:`hsbg.rl.api.run_episode` 会在每局开始前自动调用（collector/evaluate
因此无需额外处理）。多进程采集时 policy 必须是字符串（worker 内重建）或模块
级可 pickle 对象；``teacher`` 用字符串 spec 最省事。
"""

from __future__ import annotations

import inspect
import pickle
import random
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, Union

from hsbg.env.spec import ActionKind, CandidateAction, Observation
from hsbg.rl.api import fallback_index, resolve_action

PolicyLike = Any

#: 内置策略名
BUILTIN_NAMES: Tuple[str, ...] = (
    "random", "heuristic", "first", "end_turn", "teacher",
)

#: 动作类型偏好（启发式打分；数值越大越优先）
_HEURISTIC_KIND_SCORE: Dict[str, float] = {
    "buy": 3.0,
    "play_minion": 2.6,
    "play_spell": 2.1,
    "upgrade": 1.6,
    "activate": 1.3,
    "choose": 2.0,
    "hero_power": 1.0,
    "reroll": 0.55,
    "use_dark_gift": 0.5,
    "sell": 0.3,
    "freeze": 0.1,
    "end_turn": 0.05,
}

_CHECKPOINT_SUFFIXES = (".pt", ".pth", ".ckpt")


# ══════════════════════════════════════════════════════════════════════
# 内置策略
# ══════════════════════════════════════════════════════════════════════


class BasePolicy:
    """策略基类：``name`` + ``act`` + ``reset``（+ 可选 ``bind_env``）。"""

    name: str = "base"
    #: 是否需要访问 env 内部状态（引擎感知策略 = True）
    requires_engine: bool = False

    def reset(self) -> None:  # noqa: D401 - 协议要求
        """每局开始前清理内部状态（默认无事可做）。"""

    def bind_env(self, env: Any) -> None:  # noqa: D401 - 协议要求
        """绑定当前环境（只有需要引擎状态的策略才实现；默认 no-op）。

        :func:`hsbg.rl.api.run_episode` 会在每局开始前调用该方法。
        """

    def act(
        self,
        obs: Observation,
        *,
        deterministic: bool = False,
        rng: Optional[random.Random] = None,
    ) -> Union[int, CandidateAction]:
        raise NotImplementedError

    def __call__(self, obs: Observation, rng: Optional[random.Random] = None):
        """兼容 ``policy(obs, rng)`` 调用风格（``hsbg.eval.runner``）。"""
        return self.act(obs, rng=rng)

    def __repr__(self) -> str:  # pragma: no cover - 调试
        return f"{type(self).__name__}(name={self.name!r})"


class RandomPolicy(BasePolicy):
    """在合法候选中均匀随机。

    可复现性：collector/evaluate 每局传入独立 ``rng``（由 episode seed 播种），
    因此同 seed 两次采集动作序列完全一致。``deterministic=True`` 对该策略
    仍使用 rng（随机策略没有"确定版本"），但 rng 由调用方固定。
    """

    def __init__(self, seed: int = 0, name: str = "random") -> None:
        self.name = name
        self._rng = random.Random(int(seed))

    def act(
        self,
        obs: Observation,
        *,
        deterministic: bool = False,
        rng: Optional[random.Random] = None,
    ) -> int:
        n = len(obs.candidates or ())
        if n <= 0:
            return 0
        source = rng if rng is not None else self._rng
        return int(source.randrange(n))


class FirstLegalPolicy(BasePolicy):
    """总是选第一个候选（最小闭环/冒烟用）。"""

    name = "first"

    def act(self, obs: Observation, *, deterministic: bool = False,
            rng: Optional[random.Random] = None) -> int:
        return 0


class EndTurnPolicy(BasePolicy):
    """优先 ``end_turn``（测试回合推进/最小步数用）。"""

    name = "end_turn"

    def act(self, obs: Observation, *, deterministic: bool = False,
            rng: Optional[random.Random] = None) -> int:
        for i, cand in enumerate(obs.candidates or ()):
            if str(getattr(cand.kind, "value", cand.kind)) == "end_turn":
                return i
        return max(len(obs.candidates or ()) - 1, 0)


class HeuristicPolicy(BasePolicy):
    """观测级贪心启发式（评测/采集参照系，不读引擎隐藏状态）。

    规则：优先购买/打出（按目标实体质量加分）、血量危险时更激进、
    棋盘过小时不卖；**每回合决策数超过上限后强制 end_turn**（防 freeze
    循环；环境层也有 ``max_actions_per_turn`` 预算，这里是双保险）。
    """

    name = "heuristic"

    def __init__(
        self,
        seed: int = 0,
        name: str = "heuristic",
        *,
        max_decisions_per_turn: int = 24,
        max_no_progress: int = 3,
    ) -> None:
        self.name = name
        self._rng = random.Random(int(seed))
        self.max_decisions_per_turn = int(max_decisions_per_turn)
        self.max_no_progress = int(max_no_progress)
        self._turn: int = -1
        self._turn_count: int = 0
        self._progress_fp: Optional[tuple] = None
        self._no_progress: int = 0

    def reset(self) -> None:
        self._turn = -1
        self._turn_count = 0
        self._progress_fp = None
        self._no_progress = 0

    def _progress_key(self, obs: Observation, turn: int) -> tuple:
        hero = getattr(obs, "hero", None)
        return (
            turn,
            int(getattr(hero, "gold", -1)) if hero is not None else -1,
            int(getattr(hero, "tier", -1)) if hero is not None else -1,
            len(getattr(obs, "hand", ()) or ()),
            len(getattr(obs, "board", ()) or ()),
            len(getattr(obs, "tavern", ()) or ()),
            len(getattr(obs, "trinkets", ()) or ()),
        )

    def act(
        self,
        obs: Observation,
        *,
        deterministic: bool = False,
        rng: Optional[random.Random] = None,
    ) -> int:
        cands = tuple(obs.candidates or ())
        if not cands:
            return 0
        turn = int(getattr(obs, "turn", 0) or 0)
        if turn != self._turn:
            self._turn = turn
            self._turn_count = 0
            self._progress_fp = None
            self._no_progress = 0
        self._turn_count += 1
        fp = self._progress_key(obs, turn)
        if fp == self._progress_fp:
            self._no_progress += 1
        else:
            self._progress_fp = fp
            self._no_progress = 0
        # 死循环保护：决策数超预算 / 连续多步无进展 → 强制 end_turn
        if (self._turn_count > self.max_decisions_per_turn
                or self._no_progress >= self.max_no_progress):
            for i, cand in enumerate(cands):
                if str(getattr(cand.kind, "value", cand.kind)) == "end_turn":
                    return i
        scores = [heuristic_score(obs, cand) for cand in cands]
        best = max(scores)
        top = [i for i, s in enumerate(scores) if s >= best - 1e-9]
        if deterministic or len(top) == 1:
            return int(top[0])
        source = rng if rng is not None else self._rng
        return int(source.choice(top))


def heuristic_score(obs: Observation, cand: CandidateAction) -> float:
    """启发式打分（可被外部复用/扩展；纯函数）。"""
    kind = str(getattr(cand.kind, "value", cand.kind))
    score = _HEURISTIC_KIND_SCORE.get(kind, 0.0)
    board = tuple(getattr(obs, "board", ()) or ())
    hand = tuple(getattr(obs, "hand", ()) or ())
    tavern = tuple(getattr(obs, "tavern", ()) or ())
    hero = getattr(obs, "hero", None)
    # 注意：slot 0 是合法下标，不能用 `value or -1`（会把 0 吞成 -1）
    src_raw = getattr(cand, "src_slot", -1)
    tgt_raw = getattr(cand, "tgt_slot", -1)
    src_slot = -1 if src_raw is None else int(src_raw)
    tgt_slot = -1 if tgt_raw is None else int(tgt_raw)
    tgt_zone = str(getattr(cand, "tgt_zone", "") or "")

    if kind == "buy" and 0 <= src_slot < len(tavern):
        token = tavern[src_slot]
        score += token.atk / 40.0 + token.health / 40.0 + token.tier / 20.0
    elif kind in ("play_minion", "play_spell") and 0 <= src_slot < len(hand):
        token = hand[src_slot]
        score += token.atk / 40.0 + token.health / 40.0
        if tgt_zone == "board" and 0 <= tgt_slot < len(board):
            score += 0.1
    elif kind == "sell" and 0 <= src_slot < len(board):
        token = board[src_slot]
        score -= (token.atk + token.health) / 60.0
        if len(board) <= 3:
            score -= 1.0
    # 指向不存在目标的动作价值很低（正规环境不应出现，防御性打折）
    if tgt_zone == "tavern" and not (0 <= tgt_slot < len(tavern)):
        score -= 0.5
    # 血量危险时更倾向于发育
    health = int(getattr(hero, "health", 999) or 999) if hero is not None else 999
    if health <= 10 and kind in ("buy", "play_minion", "upgrade"):
        score += 0.3
    return float(score)


# ══════════════════════════════════════════════════════════════════════
# 适配器
# ══════════════════════════════════════════════════════════════════════


class CallableAdapter(BasePolicy):
    """把 ``fn(obs)`` / ``fn(obs, rng)`` 包装成 Policy 协议。"""

    def __init__(self, fn: Callable[..., Any], name: Optional[str] = None) -> None:
        if not callable(fn):
            raise TypeError(f"CallableAdapter 需要 callable，得到 {type(fn)!r}")
        self._fn = fn
        self.name = name or getattr(fn, "__name__", type(fn).__name__) or "callable"
        self._takes_rng = _callable_takes_rng(fn)

    def act(self, obs: Observation, *, deterministic: bool = False,
            rng: Optional[random.Random] = None):
        if self._takes_rng:
            return self._fn(obs, rng)
        return self._fn(obs)

    def __getstate__(self) -> Dict[str, Any]:
        return {"_fn": self._fn, "name": self.name, "_takes_rng": self._takes_rng}

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.__dict__.update(state)


class PolicyAdapter(BasePolicy):
    """把"有 act 但缺 reset/name"的对象补齐成 Policy。"""

    def __init__(self, obj: Any, name: Optional[str] = None) -> None:
        if not hasattr(obj, "act"):
            raise TypeError(f"PolicyAdapter 需要带 act() 的对象，得到 {type(obj)!r}")
        self._obj = obj
        self.name = name or getattr(obj, "name", type(obj).__name__)

    def reset(self) -> None:
        reset = getattr(self._obj, "reset", None)
        if callable(reset):
            reset()

    def bind_env(self, env: Any) -> None:
        bind = getattr(self._obj, "bind_env", None)
        if callable(bind):
            bind(env)

    def act(self, obs: Observation, *, deterministic: bool = False,
            rng: Optional[random.Random] = None):
        try:
            return self._obj.act(obs, deterministic=deterministic, rng=rng)
        except TypeError:
            try:
                return self._obj.act(obs, rng=rng)
            except TypeError:
                return self._obj.act(obs)

    def __getstate__(self) -> Dict[str, Any]:
        return {"_obj": self._obj, "name": self.name}

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.__dict__.update(state)


class CheckpointPolicy(BasePolicy):
    """加载 ``hsbg.policy`` checkpoint 做推理（不训练）。

    * checkpoint 自包含词表/编码器尺寸/网络 config；
    * ``greedy_default=True`` 时 ``deterministic`` 参数不改变行为（贪心）；
      构造时传 ``greedy_default=False`` 则 ``deterministic=False`` 会采样；
    * torch / 模型只在构造时导入，本模块 import 不引入 torch 依赖。
    """

    def __init__(
        self,
        path: Union[str, Path],
        *,
        device: str = "cpu",
        greedy_default: bool = True,
        name: Optional[str] = None,
    ) -> None:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"checkpoint 不存在: {path}")
        import torch  # 延迟导入

        from hsbg.policy.model import load_policy_and_encoder

        self.path = path
        self.device = torch.device(device)
        self.policy, self.encoder = load_policy_and_encoder(path, map_location="cpu")
        self.policy.to(self.device)
        self.policy.eval()
        self.greedy_default = bool(greedy_default)
        self.name = name or f"checkpoint:{path.stem}"
        self._torch = torch

    def act(self, obs: Observation, *, deterministic: bool = False,
            rng: Optional[random.Random] = None) -> int:
        torch = self._torch
        n = len(obs.candidates or ())
        if n <= 0:
            return 0
        greedy = bool(deterministic) or self.greedy_default
        batch = self.encoder.collate([obs], device=self.device)
        with torch.no_grad():
            actions, _, _ = self.policy.act(batch, greedy=greedy)
        return int(actions[0].item())

    def __getstate__(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "device": str(self.device),
            "greedy_default": self.greedy_default,
            "name": self.name,
        }

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.__init__(  # type: ignore[misc]
            state["path"],
            device=state["device"],
            greedy_default=state["greedy_default"],
            name=state["name"],
        )


# ══════════════════════════════════════════════════════════════════════
# 引擎感知教师（quality baseline / BC 教师）
# ══════════════════════════════════════════════════════════════════════


def _match_candidate(obs: Observation, target: Optional[CandidateAction]) -> Optional[int]:
    """把目标 ``CandidateAction`` 映射回 ``obs.candidates`` 下标（多级匹配）。

    1. 精确 ``signature()``；
    2. 同 ``kind`` + 同 ``option``（choose 步）；
    3. 同 ``kind`` + 同 ``src_zone/src_slot/tgt_zone/tgt_slot``；
    4. 只要同 ``kind``（环境候选与引擎描述符字段略有出入时兜底）；
    匹配不到返回 ``None``。
    """
    if target is None:
        return None
    cands = tuple(getattr(obs, "candidates", ()) or ())
    if not cands:
        return None
    sig = target.signature()
    for i, cand in enumerate(cands):
        if cand.signature() == sig:
            return i
    kind = str(getattr(target.kind, "value", target.kind))
    option = int(getattr(target, "option", -1) or -1)
    if option >= 0:
        for i, cand in enumerate(cands):
            if (str(getattr(cand.kind, "value", cand.kind)) == kind
                    and int(getattr(cand, "option", -1) or -1) == option):
                return i
    src_zone = str(getattr(target, "src_zone", "") or "")
    src_slot = int(getattr(target, "src_slot", -1) or -1)
    tgt_zone = str(getattr(target, "tgt_zone", "") or "")
    tgt_slot = int(getattr(target, "tgt_slot", -1) or -1)
    for i, cand in enumerate(cands):
        if (str(getattr(cand.kind, "value", cand.kind)) == kind
                and str(getattr(cand, "src_zone", "") or "") == src_zone
                and int(getattr(cand, "src_slot", -1) or -1) == src_slot
                and str(getattr(cand, "tgt_zone", "") or "") == tgt_zone
                and int(getattr(cand, "tgt_slot", -1) or -1) == tgt_slot):
            return i
    for i, cand in enumerate(cands):
        if str(getattr(cand.kind, "value", cand.kind)) == kind:
            return i
    return None


class TeacherPolicy(BasePolicy):
    """引擎感知启发式教师（复用 ``hsbg.agents.heuristic.HeuristicPolicy``）。

    定位：**离线高质量数据采集 / BC 教师 / 强基线**。它需要 env 内部状态
    （``env.game`` / ``env.agent_hero``），因此：

    * **只支持真实环境**（``backend="real"`` 或实际可用的 ``auto``）；
      mock 后端会明确报错；
    * 使用前必须 ``bind_env(env)``：手动调用，或交给
      ``hsbg.rl.api.run_episode``（collector/evaluate 自动处理）；
    * 多进程请用字符串 spec ``"teacher"``（worker 内重建并各自 bind）。

    动作来源：引擎教师的 ``choose(game, hero, ctx)`` → ``ActionDescriptor``
    → ``to_candidate()`` → 与 ``obs.candidates`` 做签名匹配；``None`` =
    结束回合；``choice`` 阶段用教师的 ``choose_option_index(obs)``。
    """

    name = "teacher"
    requires_engine = True

    #: 引擎教师的合法构造参数（其余 kwargs 忽略/报错）
    ENGINE_KWARGS: Tuple[str, ...] = (
        "upgrade_turns", "max_rerolls", "max_upgrades_per_turn",
        "buy_spells", "spell_gold_reserve",
    )

    def __init__(self, *, name: str = "teacher", **engine_kwargs: Any) -> None:
        if name:
            self.name = name
        self._engine_kwargs: Dict[str, Any] = {
            k: v for k, v in engine_kwargs.items() if k in self.ENGINE_KWARGS
        }
        unknown = sorted(set(engine_kwargs) - set(self.ENGINE_KWARGS))
        if unknown:
            raise TypeError(
                f"TeacherPolicy 不支持参数 {unknown}；"
                f"可选 {self.ENGINE_KWARGS}")
        self._env: Any = None
        self._engine: Any = None
        self.fallbacks: int = 0

    # ── 绑定 / 生命周期 ──
    def bind_env(self, env: Any) -> None:
        if not hasattr(env, "game") or not hasattr(env, "agent_hero"):
            raise RuntimeError(
                "teacher 策略需要真实环境（env.game / env.agent_hero）。"
                "当前环境不支持：mock 后端请用 heuristic/random/checkpoint；"
                "真环境请用 backend='real' 或 backend='auto'。"
            )
        self._env = env

    def reset(self) -> None:
        engine = self._engine
        states = getattr(engine, "_states", None)
        if isinstance(states, dict):
            states.clear()

    # ── 引擎教师 ──
    def _make_engine(self) -> Any:
        from hsbg.agents.heuristic import HeuristicPolicy as EngineHeuristic

        return EngineHeuristic(**self._engine_kwargs)

    def engine(self) -> Any:
        if self._engine is None:
            self._engine = self._make_engine()
        return self._engine

    # ── 决策 ──
    def act(self, obs: Observation, *, deterministic: bool = False,
            rng: Optional[random.Random] = None) -> int:
        env = self._env
        if env is None:
            raise RuntimeError(
                "TeacherPolicy 未绑定环境：请先调用 bind_env(env)。"
                "（collector/evaluate/run_episode 会自动绑定；"
                "手动逐 obs 调用时必须自己 bind）"
            )
        if not getattr(obs, "candidates", ()):
            return 0
        engine = self.engine()
        pending = getattr(obs, "pending_choice", None)
        phase = str(getattr(obs, "phase", ""))
        # 1) choice 阶段：教师自带选项启发式
        if pending is not None or phase == "choice":
            option = 0
            fn = getattr(engine, "choose_option_index", None)
            if callable(fn):
                try:
                    option = int(fn(obs))
                except Exception:  # noqa: BLE001 - 教师异常不拖垮采集
                    option = 0
            idx = _match_candidate(obs, CandidateAction(
                kind=ActionKind.CHOOSE.value, option=option))
            if idx is not None:
                return idx
            self.fallbacks += 1
            return fallback_index(obs)
        # 2) 招募阶段：引擎教师 choose() → descriptor → candidate 匹配
        game = getattr(env, "game", None)
        hero = getattr(env, "agent_hero", None)
        if game is None or hero is None:
            raise RuntimeError(
                "TeacherPolicy: env 尚未 reset（game/agent_hero 为空）。"
                "请在 env.reset(seed=...) 之后调用 act。"
            )
        descriptor = self._choose_descriptor(env, game, hero, obs)
        if descriptor is None:
            target: Optional[CandidateAction] = CandidateAction(
                kind=ActionKind.END_TURN.value)
        else:
            try:
                target = descriptor.to_candidate()
            except Exception:  # noqa: BLE001
                target = None
        idx = _match_candidate(obs, target)
        if idx is not None:
            return idx
        self.fallbacks += 1
        return fallback_index(obs)

    def _choose_descriptor(
        self, env: Any, game: Any, hero: Any, obs: Observation
    ) -> Any:
        """引擎教师的动作选择（优先复用环境已枚举的候选，避免二次枚举）。"""
        engine = self.engine()
        descriptors = None
        step_actions = getattr(env, "_step_actions", None)
        cands = getattr(step_actions, "candidates", None) if step_actions else None
        if cands is not None and len(cands) == len(getattr(obs, "candidates", ())):
            descriptors = getattr(step_actions, "descriptors", None)
        if descriptors:
            # 快路径：复用环境刚才枚举的 ActionDescriptor 列表（与 obs.candidates 同源），
            # 只跑引擎教师的"选牌"逻辑，省掉一次 enumerate_actions（~1.5–2× 单步开销）。
            try:
                state_for = getattr(engine, "_state_for")
                select = getattr(engine, "_select")
                st = state_for(game, hero)
                return select(game, hero, st, descriptors)
            except Exception:  # noqa: BLE001 - 引擎内部接口变化时回退公开路径
                pass
        try:
            from hsbg.agents.base import EnvContext

            ctx = EnvContext(
                game=game, env=env, agent_hero=hero,
                turn=int(getattr(game, "turn", 0) or 0),
            )
            return engine.choose(game, hero, ctx)
        except Exception:  # noqa: BLE001 - 教师内部异常 → 保守结束回合
            return None

    # ── 序列化（不含 env/引擎实例；多进程 worker 内重建）──
    def __getstate__(self) -> Dict[str, Any]:
        return {"name": self.name, "engine_kwargs": dict(self._engine_kwargs)}

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.__init__(name=state.get("name", "teacher"),
                      **state.get("engine_kwargs", {}))  # type: ignore[misc]


# ══════════════════════════════════════════════════════════════════════
# 规格解析 / 工具
# ══════════════════════════════════════════════════════════════════════


def _callable_takes_rng(fn: Callable[..., Any]) -> bool:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):  # 内建函数等
        return False
    params = list(sig.parameters.values())
    if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in params):
        return True
    positional = [
        p for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                      inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if "rng" in sig.parameters:
        return True
    return len(positional) >= 2


def _looks_like_checkpoint(spec: str) -> bool:
    path = Path(spec)
    if path.suffix.lower() in _CHECKPOINT_SUFFIXES:
        return True
    return path.exists() and path.is_file() and path.suffix.lower() not in (".json", ".jsonl")


def as_policy(obj: Any, *, seed: int = 0, device: str = "cpu",
              name: Optional[str] = None) -> BasePolicy:
    """把任意 policy-like 归一成 :class:`BasePolicy` 实例。"""
    if isinstance(obj, BasePolicy):
        return obj
    if isinstance(obj, str):
        return make_policy(obj, seed=seed, device=device, name=name)
    if hasattr(obj, "act"):
        if hasattr(obj, "reset") and hasattr(obj, "name"):
            return obj  # 已满足协议，直接用（省一层包装）
        return PolicyAdapter(obj, name=name)
    if callable(obj):
        return CallableAdapter(obj, name=name)
    raise TypeError(
        f"无法把 {type(obj)!r} 当作策略：需要内置名字/checkpoint 路径/"
        f"带 act() 的对象/callable(obs)"
    )


def make_policy(
    spec: PolicyLike,
    *,
    seed: int = 0,
    device: str = "cpu",
    name: Optional[str] = None,
    **kwargs: Any,
) -> BasePolicy:
    """按 policy spec 创建策略实例。

    ``spec`` 可以是内置名字、checkpoint 路径、callable、Policy-like 对象。
    其它 kwargs 透传给内置策略构造函数（如 ``max_decisions_per_turn``）。
    """
    if isinstance(spec, str):
        key = spec.strip()
        low = key.lower()
        if low in BUILTIN_NAMES:
            if low == "random":
                return RandomPolicy(seed=seed, name=name or "random")
            if low == "heuristic":
                allowed = {k: v for k, v in kwargs.items()
                           if k in ("max_decisions_per_turn",)}
                return HeuristicPolicy(seed=seed, name=name or "heuristic", **allowed)
            if low == "first":
                return FirstLegalPolicy()
            if low == "end_turn":
                return EndTurnPolicy()
            if low == "teacher":
                unknown = sorted(set(kwargs) - set(TeacherPolicy.ENGINE_KWARGS))
                if unknown:
                    raise TypeError(
                        f"teacher 不支持参数 {unknown}；"
                        f"可选 {TeacherPolicy.ENGINE_KWARGS}")
                return TeacherPolicy(name=name or "teacher", **kwargs)
        if _looks_like_checkpoint(key):
            try:
                return CheckpointPolicy(key, device=device, name=name)
            except FileNotFoundError as exc:
                raise ValueError(f"checkpoint 不存在: {key}") from exc
        raise ValueError(
            f"未知策略 {spec!r}：可选内置 {BUILTIN_NAMES}、"
            f"checkpoint 路径（.pt/.pth/.ckpt）、callable 或 Policy 对象"
        )
    return as_policy(spec, seed=seed, device=device, name=name)


def policy_requires_engine(spec: PolicyLike) -> bool:
    """该策略是否需要 env 内部状态（目前只有 ``teacher``）。

    collector/evaluate 用它做前置校验：mock 后端无法提供 ``env.game``，
    应在开始采集前就给出清晰错误，而不是逐局失败。
    """
    if isinstance(spec, str):
        return spec.strip().lower() == "teacher"
    return bool(getattr(spec, "requires_engine", False))


def describe_policy(spec: PolicyLike) -> str:
    """给 CLI/日志用的策略描述（不构造 checkpoint 模型）。"""
    if isinstance(spec, str):
        return spec
    name = getattr(spec, "name", None)
    if name:
        return str(name)
    if callable(spec):
        return getattr(spec, "__name__", type(spec).__name__)
    return type(spec).__name__


def is_picklable(obj: Any) -> bool:
    """多进程采集前检查 policy 是否可 pickle（spawn 必须可 pickle）。"""
    try:
        pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
        return True
    except Exception:  # noqa: BLE001
        return False


def ensure_picklable(obj: Any, *, what: str = "policy") -> None:
    """不可 pickle 时给出可操作的错误信息。"""
    if is_picklable(obj):
        return
    raise ValueError(
        f"{what} 无法 pickle，多进程采集需要以下之一：\n"
        f"  1) 字符串 spec（如 'heuristic' / 'random' / 'runs/.../policy_final.pt'）\n"
        f"  2) 模块级函数（不是 lambda / 闭包）\n"
        f"  3) 模块级类的实例\n"
        f"或使用 num_envs=1（单进程）。当前类型：{type(obj)!r}"
    )


# ══════════════════════════════════════════════════════════════════════
# 便捷：单局/多局直接跑
# ══════════════════════════════════════════════════════════════════════


def act_index(policy: PolicyLike, obs: Observation, *,
              deterministic: bool = False,
              rng: Optional[random.Random] = None) -> int:
    """取动作下标（越界/None 时兜底 ``end_turn``）。"""
    impl = as_policy(policy)
    return resolve_action(impl.act(obs, deterministic=deterministic, rng=rng), obs)[0]


__all__ = [
    "PolicyLike",
    "BUILTIN_NAMES",
    "BasePolicy",
    "RandomPolicy",
    "FirstLegalPolicy",
    "EndTurnPolicy",
    "HeuristicPolicy",
    "TeacherPolicy",
    "heuristic_score",
    "CallableAdapter",
    "PolicyAdapter",
    "CheckpointPolicy",
    "as_policy",
    "make_policy",
    "describe_policy",
    "policy_requires_engine",
    "is_picklable",
    "ensure_picklable",
    "act_index",
]
