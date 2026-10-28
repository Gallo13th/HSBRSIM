"""Rust BatchEnv 驱动的全采集器（spike）：引擎/观测/mask/step/对手推进全在 Rust。

Python 侧只剩「NN 前向 + 采样 + 记录写数组」，目标把 collect 从 ~6.3 s 压到 ~2 s。

与 `collect_ppo_lockstep` 的语义对齐：
- 学习座位每回合决策数守卫（`max_actions_per_turn`）；`forced` 样本的 action=0/logprob=0，
  只参与 value；
- 名次回填（`rank`）与 truncation 语义；
- 记录以 **SoA 数组**返回（字段与 `pack_records_arrays` 一致），可直接喂
  `build_batch_from_arrays`。

用法（内部）::

    arrays, meta = collect_ppo_batchenv(model, cfg, eval_fn=evaluator,
                                        device="cuda:0", seed=0, games=192)
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import numpy as np

from .common import N_ACTIONS, N_PLAYERS, mask_from_bytes, to_jsonable
from .ppo import CollectConfig

N_OBS = 3227
N_CARDS = 124


def _empty(n: int, target_pi: bool) -> Dict[str, np.ndarray]:
    return {
        "features": np.empty((n, N_OBS), dtype=np.float32),
        "cards": np.empty((n, N_CARDS), dtype=np.int16),
        "masks": np.empty((n, N_ACTIONS), dtype=bool),
        "actions": np.empty(n, dtype=np.int64),
        "old_logprobs": np.empty(n, dtype=np.float32),
        "values": np.empty(n, dtype=np.float32),
        "ranks": np.full(n, -1, dtype=np.int64),
        "seats": np.empty(n, dtype=np.int32),
        "game_ids": np.empty(n, dtype=np.int64),
        "turns": np.empty(n, dtype=np.int32),
        "forced": np.empty(n, dtype=bool),
        "has_pi": np.zeros(n, dtype=bool),
        "target_pi": np.zeros((n, N_ACTIONS), dtype=np.float32) if target_pi
                     else np.zeros((0,), dtype=np.float32),
    }


def collect_ppo_batchenv(model: Any, cfg: CollectConfig, *, eval_fn: Any,
                         device: str = "cpu", seed: int = 0,
                         games: Optional[int] = None, gamemode: str = "bot",
                         threads: int = 1,
                         norm_mean: Any = None, norm_std: Any = None
                         ) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
    """用 Rust `BatchEnv` 跑 N 局（同步槽位），返回 SoA 记录 + meta。"""
    from hsbg_engine import BatchEnv

    if str(gamemode) != "bot":
        raise ValueError(f"batchenv 采集只支持 bot 对手，收到 {gamemode!r}")
    t_start = time.time()
    n = int(games if games is not None else cfg.games)
    seat = int(cfg.learner_seat)
    max_steps = int(cfg.max_steps)
    limit = int(getattr(cfg, "max_actions_per_turn", 0) or 0)
    n_slots = n  # 每局一个受控座位
    env = BatchEnv(n, seed=int(cfg.seed) + int(seed), controlled=(seat,), threads=int(threads))

    cap = n * max(64, max_steps // 8)
    buf = _empty(cap, target_pi=False)
    cnt = 0
    turn_counts: Dict[Tuple[int, int], int] = {}
    per_slot_first = np.full(n_slots, -1, dtype=np.int64)   # 该 slot 首条记录下标
    per_slot_last = np.full(n_slots, -1, dtype=np.int64)
    ranks = np.zeros(n_slots, dtype=np.int64)
    finished = np.zeros(n_slots, dtype=bool)
    illegal = 0
    rejected = 0
    rounds = 0
    do_fwd = getattr(eval_fn, "act_batch", None)

    while True:
        obs = env.observe()
        # 只处理「ready 且本局尚未结束」的 slot：BatchEnv 会在受控座位全部结束后
        # 自动开新局，不排除会无限采集
        ready = obs["ready"] & (~finished)
        if not bool(ready.any()):
            break
        idx = np.flatnonzero(ready)
        turns = env.turns()[idx]
        feats = obs["features"][idx]
        cards = obs["cards"][idx]
        masks = obs["action_mask"][idx]
        if do_fwd is None:
            raise RuntimeError("collect_ppo_batchenv 需要支持 act_batch 的 evaluator")
        acts, lps, vals = do_fwd(feats, cards, masks,
                                 float(getattr(cfg, "temperature", 1.0)),
                                 seed=int(seed) + rounds)
        # 记录（含回合守卫）：先按 slot 写，再统一 step
        step_actions = np.zeros(n_slots, dtype=np.int64)
        for j, slot in enumerate(idx):
            slot = int(slot)
            gid = int(cfg.game_id_offset) + slot
            turn = int(turns[j])
            key = (gid, turn)
            n_turn = turn_counts.get(key, 0) + 1
            turn_counts[key] = n_turn
            mask = masks[j]
            forced = bool(limit > 0 and n_turn > limit and bool(mask[0]))
            a = int(acts[j])
            lp = float(lps[j])
            if not bool(mask[a]) if 0 <= a < N_ACTIONS else True:
                illegal += 1
                legal = np.flatnonzero(mask)
                a = int(legal[0]) if legal.size else 0
            if forced:
                a, lp = 0, 0.0
            step_actions[slot] = a
            if cnt >= cap:
                cap *= 2
                for k, v in _empty(cap - len(buf["actions"]), target_pi=False).items():
                    if v.ndim == 1:
                        buf[k] = np.concatenate([buf[k], v])
                    elif v.size == 0:
                        continue
                    else:
                        buf[k] = np.concatenate([buf[k], v], axis=0)
            buf["features"][cnt] = feats[j]
            buf["cards"][cnt] = cards[j].astype(np.int16, copy=False)
            buf["masks"][cnt] = mask
            buf["actions"][cnt] = a
            buf["old_logprobs"][cnt] = lp
            buf["values"][cnt] = float(vals[j])
            buf["seats"][cnt] = seat
            buf["game_ids"][cnt] = gid
            buf["turns"][cnt] = turn
            buf["forced"][cnt] = forced
            if per_slot_first[slot] < 0:
                per_slot_first[slot] = cnt
            per_slot_last[slot] = cnt
            cnt += 1
        _, dones, info = env.step(step_actions)
        rejected += int(info["rejected"].sum())
        for slot in np.flatnonzero(dones):
            slot = int(slot)
            if finished[slot]:
                continue
            finished[slot] = True
            ranks[slot] = int(info["placement"][slot])
        rounds += 1
        if bool(finished.all()) or rounds > 20 * max_steps:
            break

    # 名次回填（每个 slot 的记录区间），未结束的局 rank=-1（会被 build_batch 丢弃）
    for slot in range(n_slots):
        if per_slot_first[slot] < 0:
            continue
        a = per_slot_first[slot]
        b = per_slot_last[slot] + 1
        if ranks[slot] > 0:
            buf["ranks"][a:b] = ranks[slot]
    out = {k: v[:cnt] for k, v in buf.items()}
    meta = {
        "mode": "rust_batchenv",
        "games": n, "decisions": int(cnt), "rounds": int(rounds),
        "illegal_actions": int(illegal), "rejected_actions": int(rejected),
        "truncated_games": int((ranks == 0).sum()),
        "forced_end_turns": int(out["forced"].sum()),
        "wall_s": time.time() - t_start,
    }
    return out, to_jsonable(meta)
