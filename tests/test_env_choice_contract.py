"""``tests/test_env_choice_contract.py`` —— env ↔ ``PendingChoice`` / ``take_choice`` 契约（P1）。

覆盖：
- driver 的 choose 路径改用引擎原子入口 ``Game.take_choice(index, owner=)``
  （不再手写 pop+choose）：owner 不符/空队列/越界**不消费**选择；
- 结算回调抛错 → 引擎标记 ``failed + resolution_error``（终态不可重试），
  env ``ApplyResult.failed`` / ``info["choice_failed"]`` /
  ``info["resolution_error"]`` / ``stats["choice_resolution_errors"]`` /
  ``_errors`` 全链路留痕，且**刷新观测**（不返回仍显示已消费选择的旧 obs）；
- 自动结算路径（对手期/EoT/淘汰/终局清理，经 ``ChoiceQueue`` /
  ``resolve_pending_choices``）的 failed 同样进 stats/info/errors；
- 「可暂停性」探测：``Game.end_recruit_phase`` 是同步方法（无 generator/
  coroutine/续跑 API），阶段内产生的智能体选择只能用 ``ChoiceQueue`` 入队即
  结算（同回合 hold_fn 不生效）；新回合开始后的选择可 hold —— 与
  ``docs/ENV_SPEC.md`` §3「不可暂停阶段」结论一致。
"""

from __future__ import annotations

import inspect

import pytest

from hsrl2.game import Game, GameStateError, PendingChoice

from hsbg.env import BattlegroundsEnv, driver
from hsbg.env.spec import ActionKind, CandidateAction

from tests.test_env_support import make_engine_game


# ══════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════


def _choose_desc(option: int = 0) -> driver.ActionDescriptor:
    return driver.ActionDescriptor(kind=ActionKind.CHOOSE.value,
                                   option=int(option))


def _ok_choice(owner, kind: str = "unit_ok", options=("a", "b", "c"),
               sink=None) -> PendingChoice:
    def _resolve(pick):
        if sink is not None:
            sink.append(pick)
    return PendingChoice(owner, list(options), kind,
                         resolve_callback=_resolve)


def _failing_choice(owner, kind: str = "unit_fail", options=("a", "b")):
    def _raise(pick):
        raise ValueError(f"boom:{pick}")
    return PendingChoice(owner, list(options), kind, resolve_callback=_raise)


# ══════════════════════════════════════════════════════════════════════
# take_choice 原子入口接入
# ══════════════════════════════════════════════════════════════════════


def test_apply_choose_uses_take_choice_atomically():
    game, heroes = make_engine_game(seed=201)
    hero = heroes[0]
    calls = []
    orig = game.take_choice

    def _wrap(index=0, *, owner=None):
        calls.append((int(index), owner))
        return orig(index, owner=owner)

    game.take_choice = _wrap                    # 实例级 spy（无 __slots__）
    resolved = []
    choice = _ok_choice(hero, sink=resolved)
    game.pending_choices.append(choice)

    res = driver.apply_action(game, hero, _choose_desc(1))
    assert res.success, res.error
    assert calls == [(1, hero)], "choose 必须经 take_choice(index, owner=hero)"
    assert game.pending_choices == []
    assert choice.resolved is True and choice.failed is False
    assert resolved == ["b"]
    assert res.failed is False


def test_apply_choose_owner_mismatch_does_not_pop():
    game, heroes = make_engine_game(seed=202)
    agent, other = heroes[0], heroes[1]
    foreign = _ok_choice(other, kind="unit_other")
    game.pending_choices.append(foreign)

    res = driver.apply_action(game, agent, _choose_desc(0))
    assert not res.success
    assert res.error_type == "GameStateError"
    assert res.failed is False
    # owner 不符：不消费、不结算
    assert list(game.pending_choices) == [foreign]
    assert foreign.resolved is False and foreign.failed is False


def test_apply_choose_empty_queue_fails_gracefully():
    game, heroes = make_engine_game(seed=203)
    res = driver.apply_action(game, heroes[0], _choose_desc(0))
    assert not res.success
    assert res.error_type == "GameStateError"
    assert res.failed is False


def test_apply_choose_out_of_range_does_not_consume_choice():
    game, heroes = make_engine_game(seed=204)
    hero = heroes[0]
    choice = _ok_choice(hero, options=("only",))
    game.pending_choices.append(choice)
    res = driver.apply_action(game, hero, _choose_desc(5))
    assert not res.success
    assert res.error_type == "GameStateError"
    # 越界属于"未开始结算"错误：take_choice 之前就被拦截，队首保留
    assert list(game.pending_choices) == [choice]
    assert choice.resolved is False and choice.failed is False


def test_apply_choose_resolution_failure_marks_failed_and_reports():
    game, heroes = make_engine_game(seed=205)
    hero = heroes[0]
    choice = _failing_choice(hero, kind="unit_fail")
    game.pending_choices.append(choice)

    res = driver.apply_action(game, hero, _choose_desc(0))
    assert not res.success
    assert res.failed is True
    assert res.choice_kind == "unit_fail"
    assert res.choice_index == 0
    assert res.error_type == "ValueError"
    assert "boom" in res.resolution_error
    # 选择已被消费且标记 failed（终态，不重复结算）
    assert game.pending_choices == []
    assert choice.failed is True
    assert isinstance(choice.resolution_error, ValueError)
    assert choice.resolved is False
    with pytest.raises(GameStateError):
        choice.choose(0)


# ══════════════════════════════════════════════════════════════════════
# resolve_pending_choices / ChoiceQueue（自动结算路径）
# ══════════════════════════════════════════════════════════════════════


def test_resolve_pending_choices_uses_take_choice_with_owner():
    game, heroes = make_engine_game(seed=206)
    agent, other = heroes[0], heroes[1]
    calls = []
    orig = game.take_choice

    def _wrap(index=0, *, owner=None):
        calls.append((int(index), owner))
        return orig(index, owner=owner)

    game.take_choice = _wrap
    other_choice = _ok_choice(other, kind="unit_other")
    agent_choice = _ok_choice(agent, kind="unit_agent")
    game.pending_choices.extend([other_choice, agent_choice])

    pending = driver.resolve_pending_choices(game, agent)
    assert pending is agent_choice          # 智能体的选择不弹出、留给策略
    assert calls == [(0, other)], "非智能体选择也必须经 take_choice(owner=原 owner)"
    assert other_choice.resolved is True
    assert list(game.pending_choices) == [agent_choice]


def test_resolve_pending_choices_records_resolution_failure():
    game, heroes = make_engine_game(seed=207)
    agent, other = heroes[0], heroes[1]
    bad = _failing_choice(other, kind="unit_bad")
    agent_choice = _ok_choice(agent, kind="unit_agent")
    game.pending_choices.extend([bad, agent_choice])

    errors, failed = [], []
    pending = driver.resolve_pending_choices(
        game, agent, errors=errors, failed=failed)
    assert pending is agent_choice
    assert bad.failed is True
    assert len(failed) == 1
    rec = failed[0]
    assert rec["kind"] == "unit_bad"
    assert rec["owner_is_agent"] is False
    assert rec["failed"] is True
    assert rec["error_type"] == "ValueError"
    assert errors and "unit_bad" in errors[0]
    assert list(game.pending_choices) == [agent_choice]


def test_choice_queue_records_failed_auto_resolved_choice():
    game, heroes = make_engine_game(seed=208)
    agent = heroes[0]
    failed: list = []
    queue = driver.ChoiceQueue(game, agent=agent, failed=failed)
    game.pending_choices = queue
    try:
        queue.append(_failing_choice(agent, kind="unit_queue_fail"))
        assert len(queue) == 0                     # 已消费（failed 终态）
        assert len(failed) == 1
        assert failed[0]["owner_is_agent"] is True
        assert failed[0]["failed"] is True
        assert failed[0]["error_type"] == "ValueError"
        auto = queue.auto_resolved_agent_choices[-1]
        assert auto["kind"] == "unit_queue_fail"
        assert auto["failed"] is True
    finally:
        game.pending_choices = []


def test_choice_queue_hold_still_prevents_auto_resolve():
    game, heroes = make_engine_game(seed=209)
    agent = heroes[0]
    queue = driver.ChoiceQueue(game, agent=agent,
                               hold_fn=lambda choice: True)
    game.pending_choices = queue
    try:
        choice = _ok_choice(agent, kind="unit_held", options=("x",))
        queue.append(choice)
        assert list(queue) == [choice]
        assert choice.resolved is False
        assert queue.auto_resolved_agent_choices == []
    finally:
        game.pending_choices = []


# ══════════════════════════════════════════════════════════════════════
# env：交互式 choose 失败的 info/stats/errors/观测刷新
# ══════════════════════════════════════════════════════════════════════


def _env_ready(seed: int = 210):
    env = BattlegroundsEnv(seed=seed)
    env.reset(seed=seed)
    driver.resolve_pending_choices(env.game, None)   # 清开局选择
    return env


def test_env_step_choice_failure_reports_and_refreshes_obs():
    env = _env_ready(seed=210)
    agent = env.agent_hero
    env.game.pending_choices.append(_failing_choice(agent, kind="unit_env_fail"))
    obs = env._observe()
    assert obs.phase == "choice"
    assert obs.candidates and obs.candidates[0].kind == ActionKind.CHOOSE.value

    obs2, reward, term, trunc, info = env.step(
        CandidateAction(kind="choose", option=0))
    assert not term and not trunc
    assert info["invalid"] is True
    assert info["choice_failed"] is True
    assert info["action_error_type"] == "ValueError"
    assert info["resolution_error"]["kind"] == "unit_env_fail"
    assert "boom" in info["resolution_error"]["resolution_error"]
    assert info["choice_resolution_errors"] == 1
    assert info["choice_failures"][-1]["where"] == "interactive_step"
    assert env.stats["choice_resolution_errors"] == 1
    assert any("choice_failed:interactive_step" in e for e in env._errors)
    assert reward == pytest.approx(float(env.config.reward.invalid_action))
    # 选择已被消费：必须刷新观测，不能返回还显示该选择的旧 obs
    assert obs2.phase != "choice"
    assert obs2.pending_choice is None
    assert obs2.extra["env_stats"]["choice_resolution_errors"] == 1
    # 对局仍可继续（不因结算失败卡死）
    idx = next(i for i, c in enumerate(obs2.candidates)
               if c.kind == ActionKind.END_TURN.value)
    obs3, _r, term, trunc, info3 = env.step(idx)
    assert info3["invalid"] is False
    assert not term and not trunc
    env.close()


def test_env_auto_resolved_failure_stats():
    env = _env_ready(seed=211)
    agent = env.agent_hero
    env.game.pending_choices.append(_failing_choice(agent, kind="unit_auto_fail"))
    env._drain_all_choices(where="unit_auto")
    assert env.stats["choice_resolution_errors"] == 1
    assert env.stats["agent_choice_autoresolved"] == 1
    assert env.stats["agent_choice_autoresolved_failed"] == 1
    assert env.stats["agent_choice_autoresolved_unit_auto"] == 1
    assert env._auto_resolved_choices[-1]["failed"] is True
    assert env._choice_failures[-1]["where"] == "unit_auto"
    info = env._make_info()
    assert info["choice_resolution_errors"] == 1
    assert info["agent_choice_autoresolved_failed"] == 1
    assert info["choice_failures"][-1]["kind"] == "unit_auto_fail"
    assert not env.game.pending_choices
    env.close()


def test_env_end_recruit_phase_records_failure():
    env = _env_ready(seed=212)
    agent = env.agent_hero
    real = env.game.end_recruit_phase

    def _end_with_failing_choice():
        # 模拟 EoT/淘汰/战斗内产生一个会结算失败的智能体选择
        env.game.pending_choices.append(
            _failing_choice(agent, kind="unit_eot_fail"))
        return real()

    env.game.end_recruit_phase = _end_with_failing_choice
    try:
        env._run_end_recruit_phase()
    finally:
        env.game.end_recruit_phase = real
    assert env.stats["choice_resolution_errors"] == 1
    assert env.stats["agent_choice_autoresolved_failed"] == 1
    rec = env._choice_failures[-1]
    assert rec["where"] == "end_recruit_phase"
    assert rec["kind"] == "unit_eot_fail"
    assert rec["auto_resolved"] is True
    assert any("choice_failed:end_recruit_phase" in e for e in env._errors)
    assert not env.game.pending_choices
    env.close()


# ══════════════════════════════════════════════════════════════════════
# 可暂停性探测（EoT/淘汰/对手期）
# ══════════════════════════════════════════════════════════════════════


def test_probe_end_recruit_phase_is_synchronous_no_resume_api():
    """引擎的 end_recruit_phase 是**同步不可暂停**方法（无续跑/协程 API）。

    因此 EoT/淘汰/战斗（均在 end_recruit_phase 内部）产生的智能体选择
    无法暴露成 ``phase="choice"`` 决策步，只能经 ``ChoiceQueue`` 就地
    结算（见 docs/ENV_SPEC.md §3「不可暂停阶段」）。
    """
    assert not inspect.isgeneratorfunction(Game.end_recruit_phase)
    assert not inspect.iscoroutinefunction(Game.end_recruit_phase)
    # 无 "恢复/续跑" 入口（若未来引擎改协程/状态机，这里会失败提醒更新 env）
    for attr in ("resume_end_recruit_phase", "continue_end_recruit_phase",
                 "end_recruit_phase_gen"):
        assert not hasattr(Game, attr)
    src = inspect.getsource(Game.end_recruit_phase)
    assert "yield" not in src and "await " not in src


def test_probe_mid_phase_choice_cannot_be_held_by_turn_hold_fn():
    """ChoiceQueue 的 hold 判据是「新回合开始后」→ 阶段内（同回合）选择必被
    自动结算；这是 EoT/淘汰期无法暂停的直接原因（env 侧唯一注入点）。"""
    game, heroes = make_engine_game(seed=213)
    agent = heroes[0]
    turn_before = int(game.turn)
    queue = driver.ChoiceQueue(
        game, agent=agent, hold_fn=lambda c: int(game.turn) > turn_before)
    game.pending_choices = queue
    try:
        resolved = []
        queue.append(_ok_choice(agent, kind="unit_mid_phase",
                                options=("a", "b"), sink=resolved))
        assert len(queue) == 0, "同回合（EoT/淘汰内部）选择无法被 hold"
        assert resolved == ["a"]           # default_pick_index 选 0
        assert queue.auto_resolved_agent_choices[-1]["kind"] == "unit_mid_phase"
        # 新回合开始后的选择（任务/饰品三选一）可以 hold → choice 决策步
        game.turn = turn_before + 1
        held = _ok_choice(agent, kind="unit_new_turn", options=("x",))
        queue.append(held)
        assert list(queue) == [held]
    finally:
        game.pending_choices = []


def test_info_contains_choice_contract_keys():
    env = _env_ready(seed=214)
    info = env._make_info()
    for key in ("choice_resolution_errors", "agent_choice_autoresolved_failed",
                "choice_failures", "choice_failed"):
        assert key in info, key
    assert isinstance(info["choice_failures"], list)
    assert info["choice_failed"] is False
    env.close()
