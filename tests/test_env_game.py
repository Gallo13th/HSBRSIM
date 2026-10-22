"""``tests/test_env_game.py`` —— 对局级验收（ENV_SPEC §4/§5）。

覆盖：
- 8 人局可跑完（≥10 seeds）、名次正确、奖励有限（无 NaN/inf）；
- ``truncated``（max_turns / max_steps）生效；
- 确定性：同一 seed 两遍轨迹完全一致；
- ``auto_choice=True`` 不暴露选择步；
- 终局名次奖励公式；
- 性能基准（单步 / 单局耗时打印）。
"""

from __future__ import annotations

import math
import statistics

import pytest

from tests.test_env_support import run_game

from hsbg.env import BattlegroundsEnv
from hsbg.env.spec import ActionKind, RewardConfig, PHASE_CHOICE, PHASE_GAME_OVER

#: 多个用例共享的 10 局结果缓存（每局只跑一次）
_CACHE: dict = {}


def _result(seed: int) -> dict:
    if seed not in _CACHE:
        _CACHE[seed] = run_game(seed)
    return _CACHE[seed]


# ══════════════════════════════════════════════════════════════════════
# 对局完整性
# ══════════════════════════════════════════════════════════════════════


def test_full_games_ten_seeds():
    timings = []
    for seed in range(10):
        res = _result(seed)
        assert res["final_phase"] == PHASE_GAME_OVER
        assert res["terminated"] or res["truncated"]
        assert 1 <= res["rank"] <= 8
        assert res["steps"] > 5
        assert res["engine_errors"] == 0, res["info"].get("engine_error")
        assert res["invalid"] == 0
        assert res["steps"] <= 4000
        timings.append(res["elapsed_ms"])
    # 名次覆盖多个值（不是恒定）
    ranks = {_result(s)["rank"] for s in range(10)}
    assert len(ranks) >= 3, ranks
    print(f"\n[bench] 10 局耗时 ms: "
          f"min={min(timings):.0f} avg={statistics.mean(timings):.0f} "
          f"max={max(timings):.0f}")


def test_rank_recorded_by_elimination_order():
    """淘汰局：rank == 被淘汰时的存活人数 + 1。"""
    checked = 0
    for seed in range(10):
        res = _result(seed)
        info = res["info"]
        if info["terminated_reason"] != "eliminated":
            continue
        checked += 1
        assert res["rank"] == info["alive_count"] + 1, (seed, info)
        assert info["alive_count"] >= 1
    assert checked >= 5, f"应有多局淘汰样本，实际 {checked}"


def test_champion_rank_is_one():
    """**构造性**冠军局：2 人局、对手 1 血、己方必胜战团 → 终局 rank=1。

    历史教训：本测试原本是"在 0..14 seed 中找一局 rank=1"的统计断言；引擎
    新增卡脚本改变 RNG 流后就偶发红（全量红/单跑绿）。冠军语义（存活到
    最后、rank=1、game_over）不应依赖随机抽样，因此改为构造最小局面：
    对手只剩 1 点生命、己方放入 3 个必赢大随从，结束回合必然淘汰对手。
    """
    from hsrl2.minion import Minion

    env = BattlegroundsEnv(num_players=2, opponent="heuristic", seed=7)
    obs = env.reset(seed=7)
    game = env.game
    agent = env.agent_hero
    opponent = next(h for h in game.heroes if h is not agent)
    opponent.take_damage(int(opponent.health) + int(opponent.armor) - 1)
    assert int(opponent.health) + int(opponent.armor) == 1
    for i in range(3):                      # 必胜战团：不受买牌 RNG 影响
        m = Minion(f"TEST_CHAMPION_{i}", "Champion", atk=80, health=80)
        m.game = game
        m.controller = agent
        assert game.summon(agent, m)
    # 直接结束回合：走到 combat → 对手被淘汰 → 游戏结束
    obs, _r, term, trunc, info = _run_until_terminal(env, obs)
    assert term and not trunc, (term, trunc, info.get("terminated_reason"))
    assert info["terminated_reason"] == "game_over"
    assert int(info["rank"]) == 1
    assert int(info["agent_rank"]) == 1
    assert int(info["alive_count"]) == 1
    assert obs.phase == PHASE_GAME_OVER
    assert tuple(obs.candidates) == ()
    env.close()


def _run_until_terminal(env, obs):
    """用候选下标驱动（优先 end_turn）直到 terminated/truncated。"""
    info = {}
    while True:
        idx = next((i for i, c in enumerate(obs.candidates)
                    if c.kind == ActionKind.END_TURN.value), None)
        assert idx is not None, "recruit 阶段必有 end_turn 候选"
        obs, reward, term, trunc, info = env.step(idx)
        if term or trunc:
            return obs, reward, term, trunc, info


def test_rewards_finite():
    for seed in range(10):
        res = _result(seed)
        rewards = res["rewards"]
        assert all(math.isfinite(r) for r in rewards), seed
        assert math.isfinite(res["total_reward"])
        # 极端奖励不应出现（默认奖励尺度）
        assert abs(res["total_reward"]) < 100.0, (seed, res["total_reward"])


def test_info_fields_per_spec():
    res = _result(0)
    info = res["info"]
    for key in ("turn", "rank", "health", "alive_count", "combat",
                "wrong_action", "terminated_reason", "seed",
                "episode_steps"):
        assert key in info, key
    assert isinstance(info["combat"], dict)
    assert set(("dealt", "taken", "won", "lost")) <= set(info["combat"])
    assert info["seed"] == 0
    assert info["episode_steps"] == res["steps"]


# ══════════════════════════════════════════════════════════════════════
# 截断
# ══════════════════════════════════════════════════════════════════════


def test_truncated_by_max_turns():
    env = BattlegroundsEnv(seed=40, max_turns=1,
                           reward=RewardConfig(timeout=-0.5))
    obs = env.reset(seed=40)
    total = 0.0
    for _ in range(50):
        idx = next(i for i, c in enumerate(obs.candidates)
                   if c.kind == ActionKind.END_TURN.value)
        obs, r, term, trunc, info = env.step(idx)
        total += r
        if term or trunc:
            break
    assert trunc and not term
    assert info["terminated_reason"] == "max_turns"
    assert obs.phase == PHASE_GAME_OVER
    env.close()


def test_truncated_by_max_steps():
    env = BattlegroundsEnv(seed=41, max_steps=5)
    obs = env.reset(seed=41)
    truncated = False
    for _ in range(50):
        if obs.phase == PHASE_CHOICE:
            idx = 0
        else:
            idx = next(i for i, c in enumerate(obs.candidates)
                       if c.kind == ActionKind.END_TURN.value)
        obs, _r, term, trunc, info = env.step(idx)
        if term or trunc:
            truncated = trunc
            break
    assert truncated
    assert info["terminated_reason"] == "max_steps"
    env.close()


# ══════════════════════════════════════════════════════════════════════
# 动作预算 / freeze-spam 保护（PPO 冒烟暴露的问题回归）
# ══════════════════════════════════════════════════════════════════════


def _run_with_policy(seed: int, pick, **env_kwargs):
    """用给定的候选选择函数跑一局，返回 (steps, terminated, truncated, info)。"""
    env = BattlegroundsEnv(seed=seed, **env_kwargs)
    obs = env.reset(seed=seed)
    steps = 0
    terminated = truncated = False
    info: dict = {}
    while True:
        steps += 1
        if steps > 5000:                              # 防御：测试自身护栏
            env.close()
            pytest.fail(f"seed={seed} 未在 5000 步内结束（no-op 死循环？）")
        idx = pick(obs)
        obs, _r, terminated, truncated, info = env.step(idx)
        if terminated or truncated:
            break
    env.close()
    return steps, terminated, truncated, info


def _freeze_only_pick(obs) -> int:
    """只选 freeze；没有 freeze 就结束回合（模拟最坏的 no-op 策略）。"""
    if obs.phase == PHASE_CHOICE:
        return 0
    for i, c in enumerate(obs.candidates):
        if c.kind == ActionKind.FREEZE.value:
            return i
    for i, c in enumerate(obs.candidates):
        if c.kind == ActionKind.END_TURN.value:
            return i
    return 0


def _first_action_pick(obs) -> int:
    """总是选第一个候选（随机初始化的 PPO 策略常见行为）。"""
    if obs.phase == PHASE_CHOICE:
        return 0
    return 0


def test_freeze_candidate_appears_once_per_turn():
    """freeze 是单向候选：冻结后同一回合不再出现。"""
    env = BattlegroundsEnv(seed=80)
    obs = env.reset(seed=80)
    freeze_idx = next(i for i, c in enumerate(obs.candidates)
                      if c.kind == ActionKind.FREEZE.value)
    obs, _r, term, trunc, _i = env.step(freeze_idx)
    assert not term and not trunc
    if obs.phase != PHASE_CHOICE:
        assert all(c.kind != ActionKind.FREEZE.value
                   for c in obs.candidates)
    env.close()


def test_freeze_spam_episode_ends_quickly():
    """只选 freeze 的策略不得跑满 max_steps；步数受回合预算约束。"""
    for seed in (0, 1):
        steps, terminated, truncated, info = _run_with_policy(
            seed, _freeze_only_pick, max_actions_per_turn=40)
        assert terminated or truncated
        turns = max(1, int(info.get("turn", 1)))
        # 每回合最多 max_actions_per_turn 个动作 + end_turn/选择步
        assert steps <= 40 * (turns + 2), (seed, steps, turns)
        assert steps < 4000, (seed, steps)
        assert info["terminated_reason"] != "max_steps"


def test_random_first_action_policy_does_not_hang():
    """总是选第一个候选（含 reroll/freeze 等 no-op）也不会拖满 4000 步。"""
    steps, terminated, truncated, info = _run_with_policy(
        3, _first_action_pick, max_actions_per_turn=12)
    assert terminated or truncated
    assert steps < 4000
    assert info["terminated_reason"] != "max_steps"


def test_action_budget_respected_per_turn():
    """每回合动作数不超过预算；已达预算时候选只能 end_turn。"""
    budget = 4
    env = BattlegroundsEnv(seed=81, max_actions_per_turn=budget)
    obs = env.reset(seed=81)
    counts: dict = {}
    guard = 0
    while True:
        guard += 1
        assert guard < 3000
        if obs.phase == PHASE_CHOICE:
            obs, _r, term, trunc, _i = env.step(0)
            if term or trunc:
                break
            continue
        used = counts.get(obs.turn, 0)
        if used >= budget:
            assert [c.kind for c in obs.candidates] == \
                [ActionKind.END_TURN.value]
            idx = 0
        else:
            cand = next(((i, c) for i, c in enumerate(obs.candidates)
                         if c.kind not in (ActionKind.END_TURN.value,
                                           ActionKind.CHOOSE.value)), None)
            if cand is None:
                end_idx = next(i for i, c in enumerate(obs.candidates)
                               if c.kind == ActionKind.END_TURN.value)
                cand = (end_idx, obs.candidates[end_idx])
            idx = cand[0]
            if cand[1].kind not in (ActionKind.END_TURN.value,
                                    ActionKind.CHOOSE.value):
                counts[obs.turn] = used + 1
        obs, _r, term, trunc, _i = env.step(idx)
        if term or trunc:
            break
    assert counts, "应至少记录到一个动作"
    assert all(v <= budget for v in counts.values()), counts
    env.close()


# ══════════════════════════════════════════════════════════════════════
# 确定性
# ══════════════════════════════════════════════════════════════════════


def test_determinism_same_seed_same_trajectory():
    a = run_game(3)
    b = run_game(3)
    assert a["trace"] == b["trace"]
    assert a["rewards"] == b["rewards"]
    assert a["rank"] == b["rank"]
    assert a["turn"] == b["turn"]
    assert a["steps"] == b["steps"]


def test_different_seed_different_trajectory():
    a = run_game(3, max_steps=2000)
    b = run_game(4, max_steps=2000)
    assert a["trace"] != b["trace"]


# ══════════════════════════════════════════════════════════════════════
# auto_choice / 奖励公式
# ══════════════════════════════════════════════════════════════════════


def test_auto_choice_never_exposes_choice():
    from tests.test_env_support import play_game
    env, obs, info, trace, flags = play_game(5, env_kwargs={"auto_choice": True})
    assert all(phase != PHASE_CHOICE for _turn, phase, *_ in trace)
    assert flags[0] or flags[1]
    env.close()


def test_placement_reward_formula():
    """只有 placement 权重时，累计奖励 == 名次映射值。"""
    reward = RewardConfig(placement=1.0, health_delta=0.0,
                          combat_damage=0.0, board_power_delta=0.0,
                          survival=0.0, invalid_action=0.0, timeout=0.0,
                          step_penalty=0.0)
    res = run_game(2, env_kwargs={"reward": reward})
    rank = res["rank"]
    expected = 1.0 - 2.0 * (rank - 1) / 7.0
    assert res["total_reward"] == pytest.approx(expected, abs=1e-9)


# ══════════════════════════════════════════════════════════════════════
# 性能基准（打印实测值；阈值宽松防 CI 抖动）
# ══════════════════════════════════════════════════════════════════════


def test_step_performance():
    env = BattlegroundsEnv(seed=42)
    obs = env.reset(seed=42)
    recruit_times = []
    end_turn_times = []
    n = 0
    while n < 300:
        n += 1
        if obs.phase == PHASE_CHOICE:
            idx = 0
        else:
            idx = next((i for i, c in enumerate(obs.candidates)
                        if c.kind == ActionKind.BUY.value), None)
            if idx is None:
                idx = next(i for i, c in enumerate(obs.candidates)
                           if c.kind == ActionKind.END_TURN.value)
        is_end = obs.phase != PHASE_CHOICE and \
            obs.candidates[idx].kind == ActionKind.END_TURN.value
        import time as _time
        t0 = _time.perf_counter()
        obs, _r, term, trunc, _info = env.step(idx)
        dt = (_time.perf_counter() - t0) * 1000.0
        (end_turn_times if is_end else recruit_times).append(dt)
        if term or trunc:
            break
    env.close()
    assert recruit_times
    avg_recruit = statistics.mean(recruit_times)
    print(f"\n[bench] 招募步 avg={avg_recruit:.2f}ms "
          f"max={max(recruit_times):.2f}ms n={len(recruit_times)}; "
          f"end_turn avg={statistics.mean(end_turn_times):.1f}ms "
          f"max={max(end_turn_times):.1f}ms n={len(end_turn_times)}")
    assert avg_recruit < 10.0        # 目标 < 5ms，留 2× 余量防抖动


def test_episode_performance():
    timings = [_result(seed)["elapsed_ms"] for seed in range(10)]
    avg = statistics.mean(timings)
    print(f"\n[bench] 单局耗时 avg={avg:.0f}ms max={max(timings):.0f}ms")
    assert avg < 3000.0              # 目标 < 500ms，阈值仅作回归护栏
