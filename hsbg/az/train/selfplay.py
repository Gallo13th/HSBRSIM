"""8 座自对弈与轨迹采集。

两条路径（任务板 task-3 第 1 条）：

1. ``mode="batch"``：``BatchEnv(controlled=range(8))`` 批量 8 座自对弈（快速，
   用于纯策略/轻量网络的 (obs, action, rank) 轨迹）；策略必须实现 ``act_batch``。
2. ``mode="game"``：``Game`` 逐步驱动 8 座（可接搜索策略），收集
   (features, cards, mask, pi, z) 轨迹；搜索策略的 ``pi`` 为 visit 分布。

两条路径都把终局名次转成效用 ``z = u(rank) = 1-2*(rank-1)/7``。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from .common import (
    N_ACTIONS,
    N_PLAYERS,
    load_engine,
    mask_from_bytes,
    obs_arrays,
    to_jsonable,
    utility_from_rank,
)
from .data import AZDataset
from .policies import Policy


@dataclass
class SelfPlayConfig:
    """自对弈配置。"""

    games: int = 2
    seed: int = 0
    mode: str = "game"          # game | batch
    n_games: int = 1            # batch 模式的并行局数
    sample_stride: int = 1      # 每座位每 k 次决策采一条样本
    max_steps: int = 50000      # 单局步数守卫（超过 = truncated）
    game_id_offset: int = 0
    extra_meta: Dict[str, Any] = field(default_factory=dict)


def _fix_action(action: int, mask: np.ndarray) -> tuple[int, bool]:
    """动作非法时兜底到第一个合法动作；返回 (action, was_illegal)。"""
    a = int(action)
    if 0 <= a < N_ACTIONS and bool(mask[a]):
        return a, False
    legal = np.flatnonzero(mask)
    return (int(legal[0]) if legal.size else 0), True


def play_selfplay_game(policy: Policy, *, seed: int, game_id: int = 0,
                       sample_stride: int = 1, max_steps: int = 50000,
                       collect: bool = True) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """单局 8 座自对弈（Game 路径，可接搜索策略）。

    返回 ``(samples, game_meta)``；samples 的 ``rank/utility`` 在终局后回填。
    """
    E = load_engine()
    game = E.Game(seed=int(seed))
    policy.reset()
    samples: List[Dict[str, Any]] = []
    decisions = 0
    illegal = 0
    seat_counts = [0] * N_PLAYERS
    t0 = time.time()
    steps = 0
    while not game.is_over() and steps < int(max_steps):
        acted = False
        for p in range(N_PLAYERS):
            if not game.needs_action(p):
                continue
            seat = int(p)
            f, c = obs_arrays(game.observe(seat))
            mask = mask_from_bytes(game.legal_mask(seat))
            dec = policy.decide(game, seat)
            action, was_illegal = _fix_action(dec.action, mask)
            illegal += int(was_illegal)
            if collect:
                cnt = seat_counts[seat]
                seat_counts[seat] = cnt + 1
                if sample_stride <= 1 or (cnt % int(sample_stride)) == 0:
                    samples.append({
                        "features": f,
                        "cards": c,
                        "mask": mask,
                        "action": action,
                        "pi": dec.pi,
                        "seat": seat,
                        "turn": int(game.turn),
                        "game_id": int(game_id),
                        "source": 1 if dec.info.get("search") else 0,
                    })
            game.step(seat, action)
            decisions += 1
            steps += 1
            acted = True
            if game.is_over():
                break
        if not acted:  # 没有座位需要动作但未终局（理论不应出现）
            break
    elapsed = time.time() - t0
    over = bool(game.is_over())
    placements = list(game.placements()) if over else [0] * N_PLAYERS
    for smp in samples:
        rank = int(placements[int(smp["seat"])]) if over else 0
        smp["rank"] = rank
        smp["utility"] = float(utility_from_rank([rank])[0])
    meta = {
        "game_id": int(game_id),
        "seed": int(seed),
        "decisions": int(decisions),
        "samples": int(len(samples)),
        "illegal_actions": int(illegal),
        "truncated": int(not over),
        "steps": int(steps),
        "placements": [int(x) for x in placements],
        "elapsed_s": float(elapsed),
        "policy": getattr(policy, "name", "unknown"),
    }
    return samples, meta


def collect_selfplay_game(policy: Policy, config: SelfPlayConfig) -> tuple[AZDataset, Dict[str, Any]]:
    """多局 Game 路径自对弈采集。"""
    all_samples: List[Dict[str, Any]] = []
    games_meta: List[Dict[str, Any]] = []
    t0 = time.time()
    for gi in range(int(config.games)):
        single = SelfPlayConfig(games=1, seed=config.seed + gi, mode="game",
                                sample_stride=config.sample_stride,
                                max_steps=config.max_steps,
                                game_id_offset=config.game_id_offset)
        samples, meta = play_selfplay_game(
            policy, seed=single.seed, game_id=config.game_id_offset + gi,
            sample_stride=config.sample_stride, max_steps=config.max_steps)
        all_samples.extend(samples)
        games_meta.append(meta)
    elapsed = time.time() - t0
    dataset = AZDataset.from_samples(all_samples, meta={
        "mode": "game", "games": int(config.games), "seed": int(config.seed),
        "sample_stride": int(config.sample_stride),
        "policy": getattr(policy, "name", "unknown"),
        "supports_pi": bool(getattr(policy, "supports_pi", False)),
        "decisions": int(sum(m["decisions"] for m in games_meta)),
        "samples": int(len(all_samples)),
        "illegal_actions": int(sum(m["illegal_actions"] for m in games_meta)),
        "truncated_games": int(sum(m["truncated"] for m in games_meta)),
        "elapsed_s": float(elapsed),
        "games_per_s": float(config.games / max(elapsed, 1e-9)),
        **config.extra_meta,
    })
    dataset.meta["games_meta"] = to_jsonable(games_meta)
    return dataset, dataset.meta


def collect_selfplay_batch(policy: Policy, config: SelfPlayConfig) -> tuple[AZDataset, Dict[str, Any]]:
    """``BatchEnv(controlled=range(8))`` 批量 8 座自对弈（策略需 ``act_batch``）。

    每个 slot 是一个（局, 座位）episode：slot 结束时记录该座位整条轨迹与名次；
    一个 lobby 的 8 个受控座位全部结束后 ``BatchEnv`` 自动开新局。
    """
    E = load_engine()
    n_games = max(1, int(config.n_games))
    env = E.BatchEnv(n_games, int(config.seed), list(range(N_PLAYERS)), None, 1)
    n_slots = env.n_slots
    obs = env.observe()
    active: List[List[Dict[str, Any]]] = [[] for _ in range(n_slots)]
    slot_counts = [0] * n_slots
    game_done = [0] * n_games
    all_samples: List[Dict[str, Any]] = []
    completed_lobbies = 0
    decisions = 0
    illegal = 0
    truncated_seats = 0
    steps = 0
    t0 = time.time()
    while completed_lobbies < int(config.games) and steps < int(config.max_steps):
        turns = [int(env.game(g).turn) for g in range(n_games)]
        episodes = [int(env.episode_index(g)) for g in range(n_games)]
        actions = np.zeros(n_slots, dtype=np.int64)
        for i in range(n_slots):
            if not bool(obs["ready"][i]):
                continue
            mask = obs["action_mask"][i]
            g, seat = env.slot(i)
            a = policy.act_batch(obs["features"][i], obs["cards"][i], mask, turns[int(g)])
            action, was_illegal = _fix_action(a, mask)
            illegal += int(was_illegal)
            actions[i] = action
            cnt = slot_counts[i]
            slot_counts[i] = cnt + 1
            decisions += 1
            if config.sample_stride <= 1 or (cnt % int(config.sample_stride)) == 0:
                game_id = int(episodes[int(g)]) * n_games + int(g) + int(config.game_id_offset)
                active[i].append({
                    "features": obs["features"][i].copy(),
                    "cards": obs["cards"][i].copy(),
                    "mask": mask.copy(),
                    "action": action,
                    "pi": None,
                    "seat": int(seat),
                    "turn": int(turns[int(g)]),
                    "game_id": game_id,
                    "source": 0,
                })
        rewards, dones, info = env.step(actions)
        steps += 1
        for i in np.flatnonzero(dones):
            g, _seat = env.slot(i)
            rank = int(info["placement"][i])
            if rank <= 0:
                truncated_seats += 1
            for smp in active[i]:
                smp["rank"] = rank
                smp["utility"] = float(utility_from_rank([rank])[0])
            all_samples.extend(active[i])
            active[i] = []
            slot_counts[i] = 0
            game_done[int(g)] += 1
            if game_done[int(g)] >= N_PLAYERS:
                game_done[int(g)] = 0
                completed_lobbies += 1
        obs = env.observe()
    elapsed = time.time() - t0
    dataset = AZDataset.from_samples(all_samples, meta={
        "mode": "batch", "games": int(completed_lobbies),
        "requested_games": int(config.games), "n_games": n_games,
        "seed": int(config.seed), "sample_stride": int(config.sample_stride),
        "policy": getattr(policy, "name", "unknown"),
        "supports_pi": bool(getattr(policy, "supports_pi", False)),
        "decisions": int(decisions), "samples": int(len(all_samples)),
        "illegal_actions": int(illegal),
        "truncated_seats": int(truncated_seats),
        "elapsed_s": float(elapsed),
        "games_per_s": float(completed_lobbies / max(elapsed, 1e-9)),
        "decisions_per_game": float(decisions / max(completed_lobbies, 1)),
        **config.extra_meta,
    })
    if completed_lobbies < int(config.games):
        dataset.meta["truncated_lobbies"] = int(config.games - completed_lobbies)
    return dataset, dataset.meta


def collect_selfplay(policy: Policy, config: SelfPlayConfig) -> tuple[AZDataset, Dict[str, Any]]:
    """按 ``config.mode`` 分派到 Game / BatchEnv 采集。"""
    mode = str(config.mode).strip().lower()
    if mode == "game":
        return collect_selfplay_game(policy, config)
    if mode == "batch":
        return collect_selfplay_batch(policy, config)
    raise ValueError(f"未知自对弈模式: {config.mode!r}（game|batch）")


__all__ = [
    "SelfPlayConfig",
    "play_selfplay_game",
    "collect_selfplay_game",
    "collect_selfplay_batch",
    "collect_selfplay",
]
