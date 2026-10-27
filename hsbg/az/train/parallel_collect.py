"""多局并行 PPO 采集（P0 训练 actor 组件）。

与 `collect_ppo_batch` 的串行逐局不同：每个线程一个独立 Game + PPOSelfPlayPolicy，
共享只读模型；若传入 `BatchPPOEvaluator`，多个线程的叶/决策请求会由 BatchLeafServer
聚批。它不改变单局逻辑，只改采集调度。

限制：
- 每个 policy 独立 records，线程安全；
- 引擎 Game 独立；模型只读；
- 这是采集并行；Rust MCTS 仍逐叶回调，但多个搜索线程可共享 batch eval；
- 截断/非法仍按单局汇总。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from .common import (N_ACTIONS, N_PLAYERS, load_engine, mask_from_bytes,
                     to_jsonable)
from .ppo import (CollectConfig, PPOBatch, PPOSelfPlayPolicy, _attach_rank,
                  build_batch_from_records, _weak_bot_action)


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
    illegal = 0
    truncated = 0
    decisions = 0
    if gamemode == "self":
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
        steps = 0
        while not game.is_over() and steps < int(cfg.max_steps):
            acted = False
            for p in range(N_PLAYERS):
                if not game.needs_action(p):
                    continue
                if int(p) == int(cfg.learner_seat):
                    dec = policy.decide(game, int(p))
                    mask = mask_from_bytes(game.legal_mask(int(p)))
                    action = int(dec.action)
                    if not (0 <= action < N_ACTIONS and bool(mask[action])):
                        illegal += 1
                        action = int(np.flatnonzero(mask)[0]) if mask.any() else 0
                    game.step(int(p), action)
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
    return records, meta


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
    cfg = config or CollectConfig()
    mode = str(cfg.opponent).strip().lower()
    if mode not in ("self", "bot", "weak"):
        raise ValueError(f"opponent 只能是 self|bot|weak，得到 {cfg.opponent!r}")
    workers = max(1, int(workers))
    t0 = time.time()
    results: List[Tuple[List[Dict[str, Any]], Dict[str, Any]]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_one_game, model, cfg, gi, search_fn=search_fn,
                          search_config=search_config, eval_fn=eval_fn,
                          engine_backend=engine_backend, device=device,
                          seed=int(seed), gamemode=mode,
                          norm_mean=norm_mean, norm_std=norm_std)
                for gi in range(int(cfg.games))]
        for f in futs:
            results.append(f.result())
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
        if progress:
            print(f"[parallel] gid={meta.get('game_id')} decisions={meta.get('decisions')} "
                  f"trunc={meta.get('truncated')}", flush=True)
    if not records:
        raise RuntimeError(f"并行采集无有效轨迹（{truncated}/{len(games_meta)} 截断）")
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
        "elapsed_s": time.time() - t0,
        "samples_per_game": len(records) / max(len(games_meta) - truncated, 1),
        "games_meta": to_jsonable(games_meta),
    }
    batch = build_batch_from_records(records, gamma=gamma, lam=lam,
                                     step_penalty=step_penalty, meta=meta_out)
    batch.meta.update({"collect_seconds": time.time() - t0,
                       "collect": {k: v for k, v in meta_out.items()
                                   if k != "games_meta"}})
    return batch, batch.meta


__all__ = ["collect_ppo_batch_parallel"]
