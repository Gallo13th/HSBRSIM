"""多局并行 PPO 采集（P0 训练 actor 组件）。

与 `collect_ppo_batch` 的串行逐局不同：每个线程一个独立 Game + PPOSelfPlayPolicy，
共享只读模型；若传入 `BatchPPOEvaluator`，多个线程的叶/决策请求会由 BatchLeafServer
聚批。它不改变单局逻辑，只改采集调度。

限制：
- 每个 policy 独立 records，线程安全；
- 引擎 Game 独立；模型只读；
- 这是采集并行；Rust MCTS 仍逐叶回调，但多个搜索线程可共享 batch eval；
- 截断/非法仍按单局汇总。

对外两个入口：

- `collect_ppo_records_parallel(...)`：只返回 `records` 与 meta（进程级 actor pool
  用它把轨迹落盘回传，避免在 worker 里白建 batch）；
- `collect_ppo_batch_parallel(...)`：records -> `PPOBatch`（GAE 在这里算）的包装。
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from .common import (N_ACTIONS, N_PLAYERS, load_engine, mask_from_bytes,
                     to_jsonable)
from .ppo import (CollectConfig, PPOBatch, PPOSelfPlayPolicy, _attach_rank,
                  build_batch_from_records, _weak_bot_action)
from .library_pool import board_signature
from .human_board_pool import HumanBoardStats, SOURCE as HUMAN_BOARD_SOURCE
from .human_board_pool import inject_turn as inject_human_boards
from .mirror_snapshots import (MirrorStats, inject_turn, mirror_seats,
                               mirror_seats_random)
from .move_guard import aggregate_move_guard
from .reward_shaping import RewardShaper, aggregate_shaping
from .tier_target import TierTargetTracker, aggregate_tier_target


def _one_game(model: Any, cfg: CollectConfig, gi: int, *, search_fn: Any,
              search_config: Any, eval_fn: Any, engine_backend: str, device: str,
              seed: int, gamemode: str, norm_mean: Any = None,
              norm_std: Any = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    policy = PPOSelfPlayPolicy(
        model, device=device, config=cfg, search_fn=search_fn,
        search_config=search_config, eval_fn=eval_fn,
        engine_backend=engine_backend, seed=int(seed) + gi,
        norm_mean=norm_mean, norm_std=norm_std, move_model=False)
    policy.game_id = int(cfg.game_id_offset) + gi
    records: List[Dict[str, Any]] = []
    shaper = RewardShaper(cfg)
    tracker = TierTargetTracker(cfg)
    illegal = 0
    truncated = 0
    decisions = 0
    if gamemode == "self":
        if shaper.enabled:
            raise ValueError(
                "奖励塑形只支持 opponent=bot|weak（单 learner seat）；"
                "self 模式（8 座都是 learner）请设 shaping_coef=0")
        if tracker.enabled:
            raise ValueError(
                "等级进度奖励只支持 opponent=bot|weak（单 learner seat）；"
                "self 模式（8 座都是 learner）请设 tier_target_coef=0")
        from .selfplay import play_selfplay_game
        _samples, meta = play_selfplay_game(
            policy, seed=int(cfg.seed) + gi, game_id=policy.game_id,
            sample_stride=1, max_steps=int(cfg.max_steps))
        decisions += int(meta["decisions"])
        illegal += int(meta["illegal_actions"])
        if bool(meta["truncated"]):
            truncated = 1
        else:
            placements = list(meta["placements"])
            for seat in range(len(placements)):
                seat_recs = [r for r in policy.records if int(r["seat"]) == seat]
                if seat_recs:
                    _attach_rank(seat_recs, int(placements[seat]))
            records.extend(policy.records)
        meta = dict(meta)
        meta["collected_records"] = len(policy.records)
    else:
        E = load_engine()
        policy.reset()
        weak_rng = np.random.default_rng(int(seed) + gi)
        game = E.Game(seed=int(cfg.seed) + gi)
        # 塑形：上一决策的 Φ(s') 复用为本决策的 Φ(s)；局末/截断用 Φ(terminal)=0。
        rec_prev: Optional[int] = None
        phi_prev = 0.0
        steps = 0
        while not game.is_over() and steps < int(cfg.max_steps):
            acted = False
            for p in range(N_PLAYERS):
                if not game.needs_action(p):
                    continue
                if int(p) == int(cfg.learner_seat):
                    # 等级进度奖励：本回合第一条 decision 前检查一次 tier
                    tier_delta = tracker.observe(game, int(p))
                    phi_now = 0.0
                    if shaper.enabled:
                        phi_now = shaper.potential(game, int(p))
                        if rec_prev is not None:
                            shaper.attach(policy.records, rec_prev, policy.game_id,
                                          phi_prev, phi_now)
                    dec = policy.decide(game, int(p))
                    mask = mask_from_bytes(game.legal_mask(int(p)))
                    action = int(dec.action)
                    if not (0 <= action < N_ACTIONS and bool(mask[action])):
                        illegal += 1
                        action = int(np.flatnonzero(mask)[0]) if mask.any() else 0
                    game.step(int(p), action)
                    if shaper.enabled:
                        rec_prev = len(policy.records) - 1
                        phi_prev = phi_now
                    if tier_delta:
                        tracker.queue(len(policy.records) - 1, policy.game_id, tier_delta)
                    decisions += 1
                elif gamemode == "weak":
                    game.step(int(p), _weak_bot_action(game, int(p), weak_rng))
                else:
                    game.bot_play(int(p))
                steps += 1
                acted = True
                if game.is_over():
                    break
            if not acted:
                break
        if shaper.enabled and rec_prev is not None:
            # 局末/截断：Φ(terminal)=0（有限时域目标；保证 F 望远镜求和）。
            shaper.attach(policy.records, rec_prev, policy.game_id, phi_prev, 0.0)
        # tier-target 增量统一在势函数回填之后叠加（避免覆盖写互相踩）
        tracker.flush(policy.records)
        if game.is_over():
            rank = int(list(game.placements())[int(cfg.learner_seat)])
            _attach_rank(policy.records, rank)
            records.extend(policy.records)
            meta = {"game_id": policy.game_id, "seed": int(cfg.seed) + gi,
                    "steps": int(steps), "decisions": int(decisions),
                    "truncated": 0, "records": len(policy.records), "rank": rank}
        else:
            truncated = 1
            meta = {"game_id": policy.game_id, "seed": int(cfg.seed) + gi,
                    "steps": int(steps), "decisions": int(decisions),
                    "truncated": 1, "records": 0, "rank": None}
    meta["illegal_actions"] = int(illegal)
    meta["truncated"] = int(truncated)
    if illegal:
        # 非法动作兜底会改写真实 action/logprob；该局整局丢弃，禁止进入 PPO。
        records = []
        meta["dropped_invalid"] = 1
    meta["search_calls"] = int(policy.search_calls)
    meta["search_failures"] = int(policy.search_failures)
    meta["forced_end_turns"] = int(policy.forced_actions)
    meta.update(shaper.stats())
    meta.update(tracker.stats())
    meta.update(policy.move_guard_meta())
    return records, meta


def collect_ppo_records_parallel(
        model: Any, config: Optional[CollectConfig] = None, *,
        workers: int = 16,
        search_fn: Optional[Callable[..., Any]] = None,
        search_config: Any = None,
        eval_fn: Optional[Callable[..., Any]] = None,
        engine_backend: str = "auto", device: str = "cpu",
        seed: int = 0,
        norm_mean: Optional[np.ndarray] = None,
        norm_std: Optional[np.ndarray] = None,
        progress: bool = False) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """多线程采集轨迹，返回 ``(records, meta)``；不构建 PPOBatch。"""
    cfg = config or CollectConfig()
    mode = str(cfg.opponent).strip().lower()
    if mode not in ("self", "bot", "weak"):
        raise ValueError(f"opponent 只能是 self|bot|weak，得到 {cfg.opponent!r}")
    workers = max(1, int(workers))
    t0 = time.time()
    results: List[Any] = [None] * int(cfg.games)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_one_game, model, cfg, gi, search_fn=search_fn,
                          search_config=search_config, eval_fn=eval_fn,
                          engine_backend=engine_backend, device=device,
                          seed=int(seed), gamemode=mode,
                          norm_mean=norm_mean, norm_std=norm_std): gi
                for gi in range(int(cfg.games))}
        for f in as_completed(futs):
            gi = futs[f]
            results[gi] = f.result()
            if progress:
                meta = results[gi][1]
                print(f"[parallel] gid={gi} decisions={meta.get('decisions')} "
                      f"trunc={meta.get('truncated')}", flush=True)
    records: List[Dict[str, Any]] = []
    games_meta: List[Dict[str, Any]] = []
    decisions = illegal = truncated = search_calls = search_fail = forced = 0
    invalid_games = 0
    dropped_decisions = 0
    for recs, meta in results:
        records.extend(recs)
        games_meta.append(meta)
        decisions += int(meta.get("decisions", 0))
        if int(meta.get("dropped_invalid", 0)):
            invalid_games += 1
            dropped_decisions += int(meta.get("decisions", 0))
        illegal += int(meta.get("illegal_actions", 0))
        truncated += int(meta.get("truncated", 0))
        search_calls += int(meta.get("search_calls", 0))
        search_fail += int(meta.get("search_failures", 0))
        forced += int(meta.get("forced_end_turns", 0))
    if not records:
        raise RuntimeError(f"并行采集无有效轨迹（{truncated}/{len(games_meta)} 截断）")
    elapsed_s = time.time() - t0
    meta_out: Dict[str, Any] = {
        "mode": ("vs_bot" if mode == "bot" else ("vs_weak" if mode == "weak" else "selfplay")),
        "parallel_workers": workers,
        "requested_games": int(cfg.games),
        "games": len(games_meta) - truncated,
        "truncated_games": truncated,
        "decisions": decisions,
        "illegal_actions": illegal,
        "invalid_games": int(invalid_games),
        "dropped_decisions": int(dropped_decisions),
        "seed": int(seed),
        "behavior": str(cfg.behavior),
        "search_calls": search_calls,
        "search_failures": search_fail,
        "forced_end_turns": forced,
        "search_enabled": bool(search_fn is not None),
        "elapsed_s": elapsed_s,
        "samples_per_game": len(records) / max(len(games_meta) - truncated, 1),
        "games_meta": to_jsonable(games_meta),
    }
    # 势函数塑形统计（默认关闭 -> 空 dict，不新增键）
    meta_out.update(aggregate_shaping(games_meta, elapsed_s=elapsed_s))
    # 等级进度奖励统计（默认关闭 -> 空 dict，不新增键）
    meta_out.update(aggregate_tier_target(games_meta))
    # 换位去抖守卫统计（默认关闭 -> 空 dict，不新增键）
    meta_out.update(aggregate_move_guard(games_meta))
    return records, meta_out


def collect_ppo_batch_parallel(model: Any, config: Optional[CollectConfig] = None, *,
                               workers: int = 16,
                               search_fn: Optional[Callable[..., Any]] = None,
                               search_config: Any = None,
                               eval_fn: Optional[Callable[..., Any]] = None,
                               engine_backend: str = "auto", device: str = "cpu",
                               seed: int = 0, gamma: float = 1.0, lam: float = 0.95,
                               step_penalty: float = 0.0,
                               norm_mean: Optional[np.ndarray] = None,
                               norm_std: Optional[np.ndarray] = None,
                               progress: bool = False) -> Tuple[PPOBatch, Dict[str, Any]]:
    t0 = time.time()
    records, meta_out = collect_ppo_records_parallel(
        model, config, workers=workers, search_fn=search_fn,
        search_config=search_config, eval_fn=eval_fn,
        engine_backend=engine_backend, device=device, seed=seed,
        norm_mean=norm_mean, norm_std=norm_std, progress=progress)
    batch = build_batch_from_records(records, gamma=gamma, lam=lam,
                                     step_penalty=step_penalty, meta=meta_out,
                                     seq_aux=bool(getattr(config, "seq_aux", False)))
    batch.meta.update({"collect_seconds": time.time() - t0,
                       "collect": {k: v for k, v in meta_out.items()
                                   if k != "games_meta"}})
    return batch, batch.meta


__all__ = ["collect_ppo_records_parallel", "collect_ppo_batch_parallel"]


def collect_ppo_lockstep(model: Any, cfg: CollectConfig, *, eval_fn: Any,
                         device: str = "cpu", seed: int = 0,
                         games: Optional[int] = None, gamemode: str = "bot",
                         engine_backend: str = "auto",
                         norm_mean: Any = None, norm_std: Any = None,
                         library_pool: Any = None, library_p: float = 0.0,
                         library_rng: Any = None,
                         trajectory_pool: Any = None, trajectory_p: float = 0.0,
                         opponent_policy: Any = None,
                         mirror_pool: Any = None, mirror_seats_count: int = 0,
                         mirror_p: float = 0.0, mirror_p_ramp: str = "",
                         mirror_seat_random: bool = False,
                         human_board_pool: Any = None,
                         human_board_p: float = 0.0,
                         human_board_seats: int = 2,
                         human_board_sample: str = "auto",
                         human_board_set_tier: bool = True,
                         ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """lock-step 采集：N 局同步推进，每轮把所有待决策局拼成一个 batch 前向一次。

    与 ``_one_game`` 的逐局循环等价（同样的对手推进、守卫、截断与名次回填），
    区别只在调度：决策请求摊薄成「每轮一次批量前向」，batch fill 从 ~0.1 提到 ~1.0。

    只支持 ``gamemode in {"bot", "weak"}``（自对弈 8 座仍走逐局路径）。

    回合末场面快照镜像（``mirror_pool`` 非空且 ``mirror_p>0``）：在每个**新回合**开始、
    任何座位行动前，按概率给 seat ``1..mirror_seats_count`` 注入该 turn 的快照
    （缺帧跳过；引擎拒绝的座位保持原 bot 状态）。默认关闭（``mirror_p=0``）。

    **人类战团注入**（``human_board_pool`` 非空且 ``human_board_p>0``）：同样在**新回合**
    开始、任何座位行动前，从全部非 learner 座位里随机抽 ``human_board_seats`` 个，按
    ``human_board_p`` 逐个注入该 turn 的人类战团（board-only；见
    ``docs/HUMAN_BOARD_OPPONENT.md``）。与镜像快照可同时开，但**同座位同回合只允许一个**：
    镜像快照优先（镜像注过 / 被它置 ``ended_turn`` 的座位记 ``skipped_by_mirror``）。
    被注入了人类战团的座位**本回合照常行动**（bot 在人类战团之上继续打），这与镜像
    「整场面 = 回合末 → ended_turn」的语义不同。

    课程模式（``mirror_seat_random=True``）：每回合用 :func:`mirror_seats_random` 从全部
    非 learner 座位重抽 ``mirror_seats_count`` 个（learner 一定不在其中）；默认 False 时
    仍用固定 ``seat 1..N``，行为与旧版一致。``mirror_p_ramp`` 只用于 meta 记录（有效 p 由
    训练入口按 iteration 求值后写入 ``mirror_p``）。

    **势函数奖励塑形**（``cfg.shaping_coef != 0``；默认 0 = 零影响）：每个 learner 决策
    前读一次 Φ(s)（``observe`` 快路径，约 1.5–2 µs），它同时是上一决策的 Φ(s')；把
    ``F = λ(γΦ(s') - Φ(s))`` 写到该决策 record 的 ``reward`` 字段（局末 Φ=0）。
    见 ``docs/REWARD_SHAPING.md``。

    **等级进度奖励**（``cfg.tier_target_coef != 0``；默认 0 = 零影响）：每局一个
    :class:`~hsbg.az.train.tier_target.TierTargetTracker`；learner 每个新回合起点读一次
    ``tier``，未达 ``tier_target_table[turn]`` 时给该回合第一条 decision 扣
    ``coef*tier_penalty``，首次达标一次性加 ``coef*tier_bonus``（每档一次）。增量在
    势函数终局回填之后统一叠加到 ``record["reward"]``。见 ``docs/TIER_TARGET.md``。
    """
    if str(gamemode) not in ("bot", "weak"):
        raise ValueError(f"lockstep 只支持 bot/weak，收到 {gamemode!r}")
    E = load_engine()
    t_start = time.time()
    shaper = RewardShaper(cfg)
    n = int(games if games is not None else cfg.games)
    policy = PPOSelfPlayPolicy(
        model, device=device, config=cfg, search_fn=None, search_config=None,
        eval_fn=eval_fn, engine_backend=engine_backend, seed=int(seed),
        norm_mean=norm_mean, norm_std=norm_std, move_model=False)
    policy.reset()
    seat = int(cfg.learner_seat)
    max_steps = int(cfg.max_steps)
    states: List[Dict[str, Any]] = []
    for gi in range(n):
        g0 = E.Game(seed=int(cfg.seed) + gi)
        states.append({
            "gi": gi, "gid": int(cfg.game_id_offset) + gi,
            "game": g0,
            "rng": np.random.default_rng(int(seed) + gi),
            "steps": 0, "decisions": 0, "illegal": 0, "done": False, "truncated": 0,
            "rec_start": 0,
            # 回合末快照镜像：当前 turn 记作「已处理」→ 只在**新**回合注入
            "mirror_turn": int(g0.turn),
            "mirror_rng": __import__("random").Random(int(cfg.seed) + int(seed) + gi * 31),
            "mirror_stats": MirrorStats(),
            # 本回合镜像快照实际注入的座位（人类战团据此让路 → skipped_by_mirror）
            "mirror_applied_seats": [],
            # 人类战团（board-only）注入：独立的 turn 游标 / RNG / 计数
            "human_turn": int(g0.turn),
            "human_rng": __import__("random").Random(
                int(cfg.seed) + int(seed) + gi * 53 + 11),
            "human_stats": HumanBoardStats(),
            # 等级进度奖励状态机（每局独立；coef=0 时 disabled = 零开销）
            "tier_target": TierTargetTracker(cfg),
        })
    rounds = 0
    tier_on = any(bool(st["tier_target"].enabled) for st in states)
    trajectory_p = max(0.0, min(1.0, float(trajectory_p)))
    lib_traj_used = 0
    if trajectory_pool is not None and trajectory_p > 0.0:
        import random as _random
        trng = _random.Random(int(cfg.seed) + int(seed) + 17)
        from .trajectory_pool import ReplayScript
        for st in states:
            if trng.random() >= trajectory_p:
                continue
            new_game = None
            traj = None
            for _try in range(4):                  # 重采样：恢复点必须让 learner 活着
                cand = trajectory_pool.sample(trng)
                if cand is None:
                    break
                try:
                    g2 = E.Game.from_json(cand.frames[0]["state"])
                except BaseException:  # noqa: BLE001
                    continue
                if int(list(g2.placements())[seat]) != 0:
                    st["traj_skipped"] = st.get("traj_skipped", 0) + 1
                    continue
                traj, new_game = cand, g2
                break
            if traj is None or new_game is None:
                continue
            st["game"] = new_game
            st["traj"] = ReplayScript(traj, learner_seat=seat)
            st["traj_turn"] = int(traj.frames[0]["turn"])
            st["steps"] = 0
            st["rng"] = np.random.default_rng(int(seed) + st["gi"] + 7919)
            st["mirror_turn"] = int(new_game.turn)
            lib_traj_used += 1
    n_frozen = max(0, min(7, int(getattr(cfg, "frozen_seats", 0))))
    frozen_set = tuple(range(1, 1 + n_frozen)) if opponent_policy is not None else ()
    for st in states:
        st["frozen_set"] = frozen_set
    # ── 回合末场面快照镜像（默认关闭） ──────────────────────────────────────
    mirror_p = max(0.0, min(1.0, float(mirror_p)))
    mirror_on = mirror_pool is not None and mirror_p > 0.0 and int(mirror_seats_count) > 0
    mirror_targets = (mirror_seats(int(mirror_seats_count), N_PLAYERS, seat)
                      if mirror_on else [])
    # ── 人类战团（board-only）注入（默认关闭） ──────────────────────────────
    human_p = max(0.0, min(1.0, float(human_board_p)))
    human_on = (human_board_pool is not None and human_p > 0.0
                and int(human_board_seats) > 0)
    human_targets = int(human_board_seats) if human_on else 0
    human_set_tier = bool(human_board_set_tier)
    # 引擎能力校验：注入 API 只在较新的 hsbg_engine 构建里；缺失时**必须显式失败**，
    # 否则每回合都会静默计 errors、注入实际上完全没生效（历史上曾因此白跑）。
    _probe = states[0]["game"]
    if mirror_on and not hasattr(_probe, "apply_turn_snapshots"):
        raise RuntimeError(
            "hsbg_engine.Game 缺少 apply_turn_snapshots：当前 import 的引擎是旧构建"
            f"（{getattr(__import__('hsbg_engine'), '__file__', '?')}）。"
            "请用 `PYTHONPATH=rust/python:.` 或 `pip install -e rust/python` 后重跑。")
    if human_on and not hasattr(_probe, "inject_board"):
        raise RuntimeError(
            "hsbg_engine.Game 缺少 inject_board：当前 import 的引擎是旧构建"
            f"（{getattr(__import__('hsbg_engine'), '__file__', '?')}）。"
            "请用 `PYTHONPATH=rust/python:.` 或 `pip install -e rust/python` 后重跑。")

    def _maybe_mirror(st: Dict[str, Any]) -> None:
        """新回合开始、任何座位行动前注入该 turn 的快照（每 turn 只尝试一次）。"""
        if not mirror_on:
            return
        g = st["game"]
        t = int(g.turn)
        if t == int(st.get("mirror_turn", t)):
            return
        st["mirror_turn"] = t
        st["mirror_applied_seats"] = []
        # 课程模式：每回合从全部非 learner 座位重抽；默认仍用固定 1..N。
        targets = (mirror_seats_random(int(mirror_seats_count), st["mirror_rng"],
                                       N_PLAYERS, seat)
                   if mirror_seat_random else mirror_targets)
        inject_turn(g, mirror_pool, t, seats=targets, p=mirror_p,
                    rng=st["mirror_rng"], learner_seat=seat,
                    stats=st["mirror_stats"],
                    applied_out=st["mirror_applied_seats"])

    def _maybe_human_board(st: Dict[str, Any]) -> None:
        """新回合开始、任何座位行动前注入人类战团（每 turn 只尝试一次）。

        必须在 :func:`_maybe_mirror` **之后**调用：镜像快照占用过的座位（本回合已
        ``ended_turn``）一律让路，并记 ``skipped_by_mirror``。
        """
        if not human_on:
            return
        g = st["game"]
        t = int(g.turn)
        if t == int(st.get("human_turn", t)):
            return
        st["human_turn"] = t
        inject_human_boards(
            g, human_board_pool, t, seats_count=human_targets, p=human_p,
            rng=st["human_rng"], learner_seat=seat, stats=st["human_stats"],
            mirror_seats=st.get("mirror_applied_seats") or (),
            num_players=N_PLAYERS, set_tier=human_set_tier)

    def _maybe_inject(st: Dict[str, Any]) -> None:
        """新回合注入总入口（顺序固定：镜像快照 → 人类战团）。"""
        _maybe_mirror(st)
        _maybe_human_board(st)

    library_p = max(0.0, min(1.0, float(library_p)))
    if library_pool is not None and library_p > 0.0:
        raise RuntimeError(
            "v1 单座位镜像注入未通过终审，禁止在训练中使用；请改用 "
            "--trajectory-pool/--trajectory-p（整局状态轨迹库）")
        import random as _random
        library_rng = library_rng or _random.Random(int(cfg.seed) + int(seed))
        for st in states:
            st["lib_done"] = set()
            st["lib_attempt"] = 0
            st["lib_injected"] = 0
            st["lib_mismatch"] = 0
            st["lib_error"] = 0
    while True:
        pending = []
        for st in states:
            if st["done"]:
                continue
            # 新回合（上一轮 learner 的 EndTurn 可能已推进）：任何座位行动前注入
            # （镜像快照 → 人类战团）。
            _maybe_inject(st)
            g = st["game"]
            guard = 0
            while (not g.is_over()) and (not g.needs_action(seat)) and guard < 10 ** 6:
                # 回合可能在 bot 推进中切换（最后一个座位结束后立刻战斗 + 进入下一回合）。
                _maybe_inject(st)
                q = next((p for p in range(N_PLAYERS) if g.needs_action(p)), None)
                if q is None:
                    break
                # 镜像库注入：在该 bot 座位**本回合第一次行动之前**注入（严格 turn 起点）
                if library_pool is not None and float(library_p) > 0.0 and int(q) != seat:
                    key = (int(q), int(g.turn))
                    if key not in st["lib_done"]:
                        st["lib_done"].add(key)
                        st["lib_attempt"] += 1
                        try:
                            placements = list(g.placements())
                            alive_q = int(placements[int(q)]) == 0
                            if alive_q and library_rng.random() < float(library_p):
                                entry = library_pool.sample(int(g.turn), rng=library_rng)
                                if entry is not None:
                                    before = g.player_json(int(q))
                                    g.set_player_from_json(int(q), json.dumps(entry.player),
                                                           True, True)
                                    after = json.loads(g.player_json(int(q)))
                                    want = dict(entry.player)
                                    # 只校验「我们想替换的内容」，大厅簿记字段按当前局保留
                                    ok = all(after.get(k) == want.get(k) for k in
                                             ("board", "hand", "tier", "health", "gold",
                                              "trinkets", "quests", "hero"))
                                    if ok:
                                        st["lib_injected"] += 1
                                    else:
                                        st["lib_mismatch"] += 1
                                        g.set_player_from_json(int(q), before, True, True)
                        except BaseException as exc:  # noqa: BLE001
                            st["lib_error"] += 1
                            st.setdefault("lib_error_last", repr(exc))
                replayed = False
                if st.get("traj") is not None and int(q) != seat:
                    a_rec = st["traj"].next_action(int(q), int(g.turn))
                    if a_rec is not None:
                        st["traj_attempt"] = st.get("traj_attempt", 0) + 1
                        mq = mask_from_bytes(g.legal_mask(int(q)))
                        if 0 <= a_rec < N_ACTIONS and bool(mq[a_rec]):
                            g.step(int(q), int(a_rec))
                            replayed = True
                            st["traj_replayed"] = st.get("traj_replayed", 0) + 1
                        else:
                            st["traj_illegal"] = st.get("traj_illegal", 0) + 1
                if not replayed and st.get("traj") is not None and int(q) != seat:
                    st["traj_fallback"] = st.get("traj_fallback", 0) + 1
                if replayed:
                    pass
                elif opponent_policy is not None and int(q) in st.get("frozen_set", ()):
                    # 冻结对手模型：由它替这个座位决策（分裂模型/自对弈）
                    try:
                        dec = opponent_policy.decide(g, int(q))
                        game_action = int(dec.action)
                        mq = mask_from_bytes(g.legal_mask(int(q)))
                        if not (0 <= game_action < N_ACTIONS and bool(mq[game_action])):
                            game_action = int(np.flatnonzero(mq)[0]) if mq.any() else 0
                        g.step(int(q), game_action)
                    except BaseException:  # noqa: BLE001 - 失败退回 bot，保证对局继续
                        g.bot_play(int(q))
                elif str(gamemode) == "weak":
                    g.step(int(q), _weak_bot_action(g, int(q), st["rng"]))
                else:
                    g.bot_play(int(q))
                st["steps"] += 1
                guard += 1
            if g.is_over() or st["steps"] >= max_steps:
                st["done"] = True
                st["truncated"] = int(not g.is_over())
                continue
            # 缺口：最后一个 bot 动作可能已推进到新回合，while 条件随即让 learner 变为可行动而退出，
            # 于是 learner 会在"注入之前"做出新回合的第一个决策。这里在交给 learner 前无条件再注入一次
            # （_maybe_inject 按 turn 幂等），并重新判断座位状态。
            _maybe_inject(st)
            if g.is_over() or st["steps"] >= max_steps:
                st["done"] = True
                st["truncated"] = int(not g.is_over())
                continue
            if not g.needs_action(seat):
                st["done"] = True
                st["truncated"] = int(not g.is_over())
                continue
            pending.append(st)
        if not pending:
            break
        _rec_base = len(policy.records)
        for k, st in enumerate(pending):
            st["rec_start"] = _rec_base + k
        # 势函数塑形：本决策的 Φ(s) 同时是上一决策的 Φ(s')（learner MDP 一步 =
        # 本决策动作 + 对手回应到下一次 learner 决策）。每决策只读一次状态。
        phi_now = ([shaper.potential(st["game"], seat) for st in pending]
                   if shaper.enabled else [])
        # 等级进度奖励：本回合第一条 learner decision 前检查一次 tier（同 turn 幂等）
        tier_deltas = ([st["tier_target"].observe(st["game"], seat) for st in pending]
                       if tier_on else [])
        decisions = policy.decide_batch([(st["game"], seat, st["gid"]) for st in pending])
        for k, (st, dec) in enumerate(zip(pending, decisions)):
            g = st["game"]
            if shaper.enabled:
                prev = st.get("shape_rec")
                if prev is not None:
                    shaper.attach(policy.records, prev, st["gid"],
                                  float(st.get("shape_phi", 0.0)), phi_now[k])
                st["shape_phi"] = phi_now[k]
                st["shape_rec"] = int(st["rec_start"])
            if tier_on and tier_deltas[k]:
                st["tier_target"].queue(int(st["rec_start"]), int(st["gid"]),
                                        tier_deltas[k])
            mask = mask_from_bytes(g.legal_mask(seat))
            a = int(dec.action)
            if not (0 <= a < N_ACTIONS and bool(mask[a])):
                st["illegal"] += 1
                a = int(np.flatnonzero(mask)[0]) if mask.any() else 0
            g.step(seat, a)
            st["steps"] += 1
            st["decisions"] += 1
        rounds += 1
        if rounds > 10 * max_steps:
            break

    # 局末/截断：最后一决策的 Φ(s') 按 Φ(terminal)=0（有限时域；保证 F 望远镜求和）。
    if shaper.enabled:
        for st in states:
            prev = st.get("shape_rec")
            if prev is not None:
                shaper.attach(policy.records, prev, st["gid"],
                              float(st.get("shape_phi", 0.0)), 0.0)
    # tier-target 增量统一在势函数回填之后叠加（避免覆盖写互相踩）。
    if tier_on:
        for st in states:
            st["tier_target"].flush(policy.records)

    records: List[Dict[str, Any]] = []
    metas = []
    illegal = truncated = decisions_total = 0
    by_game: Dict[int, List[Dict[str, Any]]] = {}
    for r in policy.records:
        by_game.setdefault(int(r["game_id"]), []).append(r)
    for st in states:
        g = st["game"]
        recs = by_game.get(int(st["gid"]), [])
        n_rec = len(recs)
        rank = int(list(g.placements())[seat]) if g.is_over() else 0
        if recs and rank:
            _attach_rank(recs, rank)
        records.extend(recs)
        illegal += int(st["illegal"])
        truncated += int(st["truncated"])
        decisions_total += int(st["decisions"])
        metas.append({"game_id": st["gid"], "seed": int(cfg.seed) + st["gi"],
                      "steps": int(st["steps"]), "decisions": int(st["decisions"]),
                      "truncated": int(st["truncated"]), "records": int(n_rec),
                      "rank": rank, "illegal_actions": int(st["illegal"])})
        if tier_on:
            metas[-1].update(st["tier_target"].stats())
    meta = {"mode": "lockstep", "games": n, "pool_games": n,
            "rounds": int(rounds), "decisions": int(decisions_total),
            "library_attempt": int(sum(st.get("lib_attempt", 0) for st in states)),
            "library_injected": int(sum(st.get("lib_injected", 0) for st in states)),
            "library_mismatch": int(sum(st.get("lib_mismatch", 0) for st in states)),
            "library_error": int(sum(st.get("lib_error", 0) for st in states)),
            "library_p": float(library_p),
            "trajectory_p": float(trajectory_p),
            "trajectory_games": int(lib_traj_used),
            "trajectory_skipped": int(sum(st.get("traj_skipped", 0) for st in states)),
            "trajectory_replay_attempt": int(sum(st.get("traj_attempt", 0) for st in states)),
            "trajectory_replayed": int(sum(st.get("traj_replayed", 0) for st in states)),
            "trajectory_replay_illegal": int(sum(st.get("traj_illegal", 0) for st in states)),
            "trajectory_fallback": int(sum(st.get("traj_fallback", 0) for st in states)),
            "frozen_opponent": bool(opponent_policy is not None),
            "frozen_seats": int(len(frozen_set)),
            "mirror_on": bool(mirror_on), "mirror_p": float(mirror_p),
            "mirror_seats": int(len(mirror_targets)),
            "mirror_targets": list(mirror_targets),
            "mirror_seat_random": bool(mirror_seat_random),
            "mirror_sample": (str(getattr(mirror_pool, "sample_mode", ""))
                              if mirror_pool is not None else ""),
            "mirror_p_ramp": str(mirror_p_ramp),
            "mirror_frames": int(getattr(mirror_pool, "frames", 0)) if mirror_on else 0,
            # 人类战团（board-only）注入：开关 / 参数 / 数据源
            "human_board_on": bool(human_on), "human_board_p": float(human_p),
            "human_board_seats": int(human_targets),
            "human_board_sample": (str(getattr(human_board_pool, "sample_mode", ""))
                                   if human_board_pool is not None else ""),
            "human_board_set_tier": bool(human_set_tier),
            "human_board_boards": (int(getattr(human_board_pool, "kept", 0))
                                   if human_on else 0),
            "human_board_source": HUMAN_BOARD_SOURCE,
            "records": int(len(records)), "illegal_actions": int(illegal),
            "truncated_games": int(truncated),
            "games_meta": metas, "forced_end_turns": int(policy.forced_actions)}
    # 回合末快照镜像是「每座位每回合」事件：逐局计数后汇总写入 meta。
    mstats = MirrorStats()
    for st in states:
        mstats.add(st.get("mirror_stats") or MirrorStats())
    meta.update(mstats.to_meta())
    # 人类战团注入同样按「每座位每回合」计数（source=human_board_approx）。
    hstats = HumanBoardStats()
    for st in states:
        hstats.add(st.get("human_stats") or HumanBoardStats())
    hmeta = hstats.to_meta()
    meta.update(hmeta)
    # 势函数塑形统计（默认关闭 -> 空 dict，不新增键）。
    meta.update(shaper.stats(elapsed_s=time.time() - t_start))
    # 等级进度奖励统计（默认关闭 -> 空 dict，不新增键）。
    meta.update(aggregate_tier_target(metas))
    # 换位去抖守卫统计（默认关闭 -> 空 dict，不新增键；policy 服务全部 N 局）。
    meta.update(policy.move_guard_meta())
    return records, meta
