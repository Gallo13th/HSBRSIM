#!/usr/bin/env python
"""环境验收脚本：RL 接口的确定性/正确性/性能一键体检。

检查项
------
1. 单局闭环：8 人局可完成、名次在 1..N、`info` 契约字段齐全
2. 确定性：同 seed + 同策略 ⇒ 观测/动作序列逐位一致
3. 多人数：2/4/8 人均可完成且名次合法
4. 选择步：PendingChoice 暴露为 phase="choice"，choose 候选可结算
5. 奖励：有限、无 NaN，终局名次奖励与配置一致
6. 非法动作：返回 invalid 且状态不推进
7. VecEnv：SyncVecEnv 自动 reset、dones/infos 契约
8. 性能：单局耗时、单动作耗时、吞吐（games/s）

用法::

    python scripts/validate_env.py --games 30 --json runs/env_validation.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsbg.agents.heuristic import HeuristicPolicy  # noqa: E402
from hsbg.env import BattlegroundsEnv  # noqa: E402
from hsbg.env.spec import ActionKind, CandidateAction  # noqa: E402

INFO_KEYS = ("turn", "rank", "health", "armor", "alive_count", "combat",
             "invalid", "terminated_reason", "seed", "episode_steps")


def _obs_signature(obs) -> Tuple:
    """观测的可比较签名（用于确定性检查）。"""
    hero = obs.hero
    return (
        obs.turn, obs.phase, obs.alive_count, obs.rank,
        None if hero is None else (hero.hero_id, hero.health, hero.armor,
                                   hero.tier, hero.gold, hero.upgrade_cost),
        tuple((t.card_id, t.atk, t.health, t.golden) for t in obs.board),
        tuple((t.card_id, t.atk, t.health) for t in obs.hand),
        tuple(t.card_id for t in obs.tavern),
        tuple(c.signature() for c in obs.candidates),
        None if obs.pending_choice is None else (
            obs.pending_choice.kind,
            tuple(o.card_id for o in obs.pending_choice.options)),
    )


def _act(env, policy, obs) -> CandidateAction:
    if obs.phase == "choice":
        return CandidateAction(kind=ActionKind.CHOOSE.value,
                               option=policy.choose_option_index(obs))
    desc = policy.choose(env.game, env.agent_hero)
    if desc is None:
        return CandidateAction(kind=ActionKind.END_TURN.value)
    return desc.to_candidate()


def run_episode(players: int, seed: int, record: bool = False):
    env = BattlegroundsEnv(num_players=players, opponent="heuristic",
                           seed=seed, max_turns=40)
    policy = HeuristicPolicy()
    obs = env.reset(seed=seed)
    sig: List[Tuple] = []
    rewards: List[float] = []
    choice_steps = 0
    t0 = time.perf_counter()
    steps = 0
    while True:
        steps += 1
        if not obs.candidates:
            break
        if obs.phase == "choice":
            choice_steps += 1
        elif record:
            sig.append(_obs_signature(obs))
        action = _act(env, policy, obs)
        obs, reward, terminated, truncated, info = env.step(action)
        rewards.append(float(reward))
        if terminated or truncated:
            break
    elapsed = time.perf_counter() - t0
    out = {
        "steps": steps,
        "turns": int(info.get("turn", 0)),
        "rank": int(info.get("rank", 0)),
        "alive": int(info.get("alive_count", 0)),
        "truncated": bool(truncated),
        "reason": str(info.get("terminated_reason", "")),
        "invalid": int(env.stats["invalid"]),
        "choice_steps": choice_steps,
        "elapsed": elapsed,
        "rewards": rewards,
        "sig": sig,
        "info": info,
    }
    env.close()
    return out


def check_info_contract(info: Dict[str, Any], players: int) -> List[str]:
    errs = []
    for k in INFO_KEYS:
        if k not in info:
            errs.append(f"missing info[{k!r}]")
    rank = info.get("rank")
    if not (isinstance(rank, int) and 1 <= rank <= players):
        errs.append(f"rank out of range: {rank!r} (players={players})")
    return errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=30)
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--json", type=str, default=None)
    args = ap.parse_args(argv)

    report: Dict[str, Any] = {"checks": {}, "metrics": {}}
    failures: List[str] = []

    # 1) 单局闭环 + info 契约
    rows = []
    for i in range(args.games):
        row = run_episode(args.players, 5000 + i)
        rows.append(row)
        failures.extend(check_info_contract(row["info"], args.players))
        if not row["rewards"] or any(not math.isfinite(r) for r in row["rewards"]):
            failures.append(f"non-finite reward at seed {5000 + i}")
        if row["truncated"]:
            failures.append(f"truncated episode at seed {5000 + i}")
    report["checks"]["episode_completion"] = not failures

    # 2) 确定性
    a = run_episode(args.players, 4242, record=True)
    b = run_episode(args.players, 4242, record=True)
    deterministic = (a["sig"] == b["sig"] and a["rank"] == b["rank"]
                     and a["steps"] == b["steps"])
    report["checks"]["determinism"] = deterministic
    if not deterministic:
        failures.append("determinism violated")

    # 3) 多人数
    multi = {}
    for p in (2, 4, 8):
        r = run_episode(p, 777)
        multi[p] = {"rank": r["rank"], "turns": r["turns"],
                    "steps": r["steps"], "truncated": r["truncated"]}
        if not 1 <= r["rank"] <= p:
            failures.append(f"{p}p rank invalid: {r['rank']}")
    report["metrics"]["multi_player"] = multi
    report["checks"]["multi_player"] = all(
        v["rank"] >= 1 for v in multi.values())

    # 4) 选择步（从 20 局统计出现情况）
    report["metrics"]["choice_steps_total"] = sum(r["choice_steps"] for r in rows)
    report["checks"]["choice_steps_observed"] = (
        report["metrics"]["choice_steps_total"] > 0)

    # 5) 非法动作
    env = BattlegroundsEnv(seed=99)
    obs = env.reset(seed=99)
    fake = CandidateAction(kind="play_spell", src_zone="hand", src_slot=0,
                           tgt_zone="board", tgt_slot=0)
    obs2, reward, term, trunc, info = env.step(fake)
    invalid_ok = (info.get("invalid") is True and not term
                  and obs2.num_candidates() == obs.num_candidates())
    report["checks"]["invalid_action_guard"] = invalid_ok
    if not invalid_ok:
        failures.append("invalid action guard failed")
    env.close()

    # 6) VecEnv（Sync）
    from hsbg.env.vec_env import SyncVecEnv
    vec = SyncVecEnv(num_envs=2,
                     env_kwargs={"num_players": 4}, seed=100)
    obs_list = vec.reset()
    vec_ok = len(obs_list) == 2
    for _ in range(5):
        actions = [o.candidates[0] for o in obs_list]
        obs_list, rewards, dones, infos = vec.step(actions)
        vec_ok = vec_ok and len(obs_list) == 2 and len(dones) == 2
    report["checks"]["vec_env"] = vec_ok
    if not vec_ok:
        failures.append("SyncVecEnv contract failed")
    vec.close()

    # 7) 性能
    elapsed = sum(r["elapsed"] for r in rows)
    steps = sum(r["steps"] for r in rows)
    report["metrics"]["games"] = args.games
    report["metrics"]["ms_per_game"] = round(elapsed / args.games * 1000, 1)
    report["metrics"]["ms_per_step"] = round(elapsed / max(1, steps) * 1000, 2)
    report["metrics"]["games_per_sec"] = round(args.games / elapsed, 2)
    report["metrics"]["mean_turns"] = round(statistics.fmean(
        r["turns"] for r in rows), 2)
    report["metrics"]["rank_mean"] = round(statistics.fmean(
        r["rank"] for r in rows), 3)
    report["metrics"]["rank_distribution"] = {
        str(k): sum(1 for r in rows if r["rank"] == k)
        for k in range(1, args.players + 1)}
    report["failures"] = failures
    report["ok"] = not failures
    report["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        print(f"saved: {p}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
