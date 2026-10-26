"""``tests/test_env_invariants.py`` —— 环境/引擎结构不变量（WS5）。

覆盖（AutoTavern ``crates/taverngym/src/invariants.rs`` 移植验收）：

1. 20+ 局随机/启发式对局，每 N 步 :func:`check_env` **0 违反**；
   （F-31 Volumizer ``health>max_health`` 已由 engine-fixer 修复 →
     本文件**不再保留** KNOWN-1 allowlist）
2. 终局面（agent 被淘汰后）:func:`check_env` 仍 0 违反（终局出口契约）；
3. 只读性：连续调用不改变 game digest / RNG / 合法候选 / obs；
4. ``strict_unique_ranks`` / ``strict_tavern_slots`` 开关语义（默认关闭
   的两类「已知偏差」见 ``docs/ENV_SNAPSHOT.md`` §5：
   同回合多淘汰名次并列、酒馆展示位可因额外机制 >7）；
5. ``reset`` 之前调用返回违反项而不是抛异常（防御式）；
6. :func:`state_digest` 稳定（clone 前后一致、step 后变化）。
"""

from __future__ import annotations

import pytest

from hsbg.env import driver
from hsbg.env.game_env import BattlegroundsEnv
from hsbg.env.invariants import (
    check_env,
    check_game,
    effective_tavern_capacity,
    state_digest,
)
from hsbg.planning.model import clone

#: 确定性动作优先级（测试不引入额外随机源；与 snapshot 测试同款）
_ACTION_PRIORITY = (
    "buy", "play_minion", "play_spell", "reroll", "upgrade",
    "hero_power", "activate", "use_dark_gift", "freeze",
    "move_minion", "end_turn",
)


def pick_action(env: BattlegroundsEnv) -> int | None:
    """按优先级选择候选下标（确定性、无外部随机源）。"""
    actions = env.legal_actions()
    if not actions:
        return None
    for kind in _ACTION_PRIORITY:
        for index, candidate in enumerate(actions):
            if candidate.kind == kind:
                return index
    return len(actions) - 1


def run_steps(env: BattlegroundsEnv, count: int, *,
              check_every: int = 3) -> int:
    """推进若干动作，每 ``check_every`` 步做一次不变量检查。"""
    bad: list[str] = []
    done = 0
    for step in range(count):
        index = pick_action(env)
        if index is None:
            break
        obs, _reward, terminated, truncated, _info = env.step(index)
        done += 1
        if (step + 1) % check_every == 0 and not (terminated or truncated):
            bad.extend(check_env(env))
        if terminated or truncated:
            break
    assert not bad, f"不变量违反: {bad[:5]}"
    # 终局面也要 0 违反（terminal-aware 检查路径）
    bad = check_env(env)
    assert not bad, f"终止时不变量违反: {bad[:5]}"
    return done


# ══════════════════════════════════════════════════════════════════════
# 1) 多局 0 违反（20+ 对局，F-31 已修复 → 无 allowlist）
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("opponent", ["heuristic", "random"])
def test_check_env_zero_violations_many_games(opponent: str) -> None:
    """20 局（10 seed × 2 对手）随机推进：每 3 步检查，0 违反。"""
    total_steps = 0
    for seed in range(10):
        env = BattlegroundsEnv(num_players=8, opponent=opponent,
                               seed=seed, max_turns=40)
        try:
            env.reset(seed=seed)
            total_steps += run_steps(env, 90, check_every=3)
            # 每局结束时再检查一次原始引擎结构（check_game 不依赖 env）
            assert check_game(env.game, agent=env.agent_hero) == []
        finally:
            env.close()
    assert total_steps >= 300, f"样本过少: {total_steps}"


def test_check_env_before_reset() -> None:
    env = BattlegroundsEnv(num_players=4, seed=0)
    problems = check_env(env)
    assert problems == ["env.game is None（reset 之前不可检查）"]
    env.close()


# ══════════════════════════════════════════════════════════════════════
# 2) 只读性 / digest 稳定性
# ══════════════════════════════════════════════════════════════════════


def test_check_env_is_read_only() -> None:
    """check_env 不得改变状态/RNG/候选/obs。"""
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=3,
                           max_turns=40)
    try:
        env.reset(seed=3)
        for _ in range(12):
            index = pick_action(env)
            if index is None:
                break
            _obs, _r, terminated, truncated, _i = env.step(index)
            if terminated or truncated:
                break
        digest0 = state_digest(env.game)
        rng0 = env.game.rng._rng.getstate()
        cand0 = tuple(c.signature() for c in env.legal_actions())
        obs0 = env.current_observation
        for _ in range(20):
            assert check_env(env) == []
        assert state_digest(env.game) == digest0
        assert env.game.rng._rng.getstate() == rng0
        assert tuple(c.signature() for c in env.legal_actions()) == cand0
        assert env.current_observation is obs0
    finally:
        env.close()


def test_state_digest_clone_stable_and_step_sensitive() -> None:
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=4,
                           max_turns=40)
    try:
        env.reset(seed=4)
        digest = state_digest(env.game)
        assert state_digest(clone(env.game)) == digest, "clone 后 digest 应一致"
        index = pick_action(env)
        assert index is not None
        env.step(index)
        assert state_digest(env.game) != digest, "step 后 digest 应变化"
    finally:
        env.close()


# ══════════════════════════════════════════════════════════════════════
# 3) 两个已知偏差开关（默认关闭，显式开启时必须报出）
# ══════════════════════════════════════════════════════════════════════


def _make_env_with_three_simultaneous_deaths() -> BattlegroundsEnv:
    """构造「同回合 3 名对手同时淘汰」→ 名次并列（env 当前公式语义）。"""
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=7,
                           max_turns=40)
    env.reset(seed=7)
    driver.resolve_pending_choices(env.game, None, None)
    victims = [h for h in env.game.heroes if h is not env.agent_hero][:3]
    for hero in victims:
        hero.health = 0
    env.game._process_eliminations()
    # 淘汰发生在 step 之外 → 刷新观测/候选，让 env 回到一致状态
    # （check_env 会如实报告「obs 与引擎不一致」，这里先让 env 自洽）
    env._obs = env._observe()
    return env


def test_rank_ties_default_allowed_strict_flags() -> None:
    """同回合多淘汰 → 名次并列：默认不报；strict_unique_ranks 报。

    参照约定差异（CONVENTION_DIFF）：AutoTavern 断言名次不重复，HSBRSIM
    环境名次公式为「被淘汰时存活人数+1」，同批死亡名次相同（见
    docs/ENV_SNAPSHOT.md §5.2）。
    """
    env = _make_env_with_three_simultaneous_deaths()
    try:
        assert len(env._elimination_order) == 3
        assert check_env(env) == [], check_env(env)
        strict = check_env(env, strict_unique_ranks=True)
        assert any("名次并列" in item for item in strict), strict
    finally:
        env.close()


def test_tavern_slots_default_allowed_strict_flags() -> None:
    """酒馆展示位可合法 > spec.TAVERN_MAX=7（额外机制）→ 默认不报。"""
    env = BattlegroundsEnv(num_players=2, opponent="heuristic", seed=7,
                           max_turns=40)
    try:
        env.reset(seed=7)
        driver.resolve_pending_choices(env.game, None, None)
        agent = env.agent_hero
        while len(agent.tavern) <= 7:
            minion = env.game.create_minion("BG25_001", controller=agent)
            env.game.add_tavern_entity(agent, minion)
        capacity = effective_tavern_capacity(agent, env.game)
        assert capacity is not None and capacity >= 0
        assert check_env(env) == [], check_env(env)
        strict = check_env(env, strict_tavern_slots=True)
        assert any("TAVERN_MAX=7" in item for item in strict), strict
    finally:
        env.close()


# ══════════════════════════════════════════════════════════════════════
# 4) F-37 回归（不变量门禁捕获的真实引擎 bug）：Reborn 满盘不返回
# ══════════════════════════════════════════════════════════════════════


def test_reborn_full_board_keeps_board_cap() -> None:
    """Reborn 复生体受棋盘上限约束（F-37；env 层再锁一次 board≤7）。

    链路（修复前失败）：6 白板 + 1 个「Reborn + 亡语召唤」随从 → 摧毁它
    → 亡语召唤填满 7 格 → 旧引擎 Reborn 分支仍 insert → board=8。
    修复后：满盘时复生体**不返回**（普通死亡处理），``check_game`` 无违反。
    引擎层回归见 ``hsrl2/tests/test_reborn_board_cap_f37.py``。
    """
    from hsrl2.game import Game
    from hsrl2.hero import Hero
    from hsrl2.tags import GameTag

    from tests.test_env_support import make_engine_game

    game, heroes = make_engine_game(seed=37, num_players=2)
    hero = heroes[0]
    plain = "BG33_140"          # River Skipper 1/1 白板（引擎测试同款 fixture）

    def summon(*, reborn: bool = False, filler: bool = False):
        minion = game.create_minion(plain, controller=hero)
        if reborn:
            minion.set(GameTag.REBORN, True)
        if filler:
            def _deathrattle(source, g, ctx=None):
                token = g.create_minion(plain, controller=hero)
                g.summon(hero, token)
                return None
            minion.set_script_override("deathrattle", _deathrattle)
        assert game.summon(hero, minion)
        return minion

    for _ in range(6):
        summon()
    victim = summon(reborn=True, filler=True)
    assert len(hero.board) == 7
    assert game.destroy_minion(victim) is True
    assert len(hero.board) <= 7, f"F-37 回归：board={len(hero.board)}"
    assert check_game(game) == [], check_game(game)
