"""``tests/test_env_actions.py`` —— 驱动层/环境层动作语义与边界。

覆盖：
- 候选动作与 ``env.legal_actions`` / ``obs.candidates`` 一致；
- **候选动作全部可执行**（同 seed 重放后逐个应用，均不得 invalid）；
- buy / sell / play_minion / reroll / upgrade / freeze 的语义；
- 金币、手牌上限、棋盘满的边界；
- 非法动作不推进状态、引擎异常被捕获；
- PendingChoice 的 FIFO 结算契约。
"""

from __future__ import annotations

import pytest

from tests.test_env_support import (
    VANILLA_MINION,
    add_minion_to_board,
    add_minion_to_hand,
    make_engine_game,
)

from hsbg.env import BattlegroundsEnv, driver
from hsbg.env.spec import ActionKind, CandidateAction, RewardConfig
from hsrl2.game import GameStateError, PendingChoice


# ══════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════


def _kinds(descs):
    return [d.kind for d in descs]


def _first(descs, kind):
    for d in descs:
        if d.kind == kind:
            return d
    return None


def _choose_agent_action(env, obs) -> int:
    """确定性脚本动作：优先买第一个可买的随从，否则结束回合。"""
    cands = obs.candidates
    for i, c in enumerate(cands):
        if c.kind == ActionKind.BUY.value:
            return i
    for i, c in enumerate(cands):
        if c.kind == ActionKind.END_TURN.value:
            return i
    return 0


def _replay(seed: int, prefix, env_kwargs=None):
    kwargs = dict(env_kwargs or {})
    kwargs.pop("seed", None)
    env = BattlegroundsEnv(seed=seed, **kwargs)
    obs = env.reset(seed=seed)
    for idx in prefix:
        obs, _r, term, trunc, _info = env.step(idx)
        assert not term and not trunc, "prefix 意外结束了对局"
    return env, obs


# ══════════════════════════════════════════════════════════════════════
# 候选动作集
# ══════════════════════════════════════════════════════════════════════


def test_legal_actions_match_obs_and_unique():
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=3)
    obs = env.reset(seed=3)
    assert tuple(obs.candidates) == env.legal_actions()
    assert len(env.action_mask()) == len(obs.candidates)
    assert all(env.action_mask())
    kinds = {c.kind for c in obs.candidates}
    assert ActionKind.END_TURN.value in kinds
    assert ActionKind.BUY.value in kinds
    # 候选签名在本步内唯一（策略按 signature 比对动作）
    sigs = [c.signature() for c in obs.candidates]
    assert len(sigs) == len(set(sigs))
    env.close()


def test_all_candidates_executable_after_reset():
    seed = 11
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed,
                           max_steps=500)
    obs = env.reset(seed=seed)
    n = len(obs.candidates)
    assert 3 <= n <= 64
    prefix = []
    for idx in range(n):
        env2, obs2 = _replay(seed, prefix)
        assert obs2.candidates == obs.candidates
        out = env2.step(idx)
        info = out[4]
        assert not info.get("invalid"), (
            f"candidate {idx} {obs.candidates[idx]} 被拒绝: {info}")
        assert env2.stats["engine_errors"] == 0
        env2.close()
    env.close()


def test_all_candidates_executable_recruit_state():
    seed = 12
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed,
                           max_steps=500)
    obs = env.reset(seed=seed)
    prefix = []
    # 走到第 2 个招募回合（中间不结束对局）
    for _ in range(4):
        idx = _choose_agent_action(env, obs)
        prefix.append(idx)
        obs, _r, term, trunc, _i = env.step(idx)
        assert not term and not trunc
    n = len(obs.candidates)
    assert ActionKind.END_TURN.value in {c.kind for c in obs.candidates}
    for idx in range(n):
        env2, obs2 = _replay(seed, prefix)
        assert obs2.candidates == obs.candidates
        info = env2.step(idx)[4]
        assert not info.get("invalid"), (
            f"candidate {idx} {obs.candidates[idx]} 被拒绝: {info}")
        env2.close()
    env.close()


def test_all_candidates_executable_choice_state():
    seed = 7
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=seed,
                           max_steps=500)
    obs = env.reset(seed=seed)
    prefix = []
    for _ in range(400):
        if obs.phase == "choice":
            break
        idx = _choose_agent_action(env, obs)
        prefix.append(idx)
        obs, _r, term, trunc, _i = env.step(idx)
        assert not term and not trunc
    else:                                                 # pragma: no cover
        pytest.skip("该 seed 在 400 步内没有出现选择步")
    assert obs.phase == "choice"
    assert obs.pending_choice is not None
    n = len(obs.candidates)
    assert n == len(obs.pending_choice.options) >= 1
    for idx in range(n):
        env2, obs2 = _replay(seed, prefix)
        assert obs2.phase == "choice"
        info = env2.step(idx)[4]
        assert not info.get("invalid")
        env2.close()
    env.close()


# ══════════════════════════════════════════════════════════════════════
# 语义与边界（驱动层，构造引擎对局）
# ══════════════════════════════════════════════════════════════════════


def test_buy_semantics():
    game, heroes = make_engine_game(seed=1)
    hero = heroes[0]
    zones = driver.collect_zones(game, hero)
    descs = driver.enumerate_actions(game, hero, zones)
    buy = _first(descs, ActionKind.BUY.value)
    assert buy is not None and buy.src_zone == "tavern"
    gold0, tavern0, hand0 = hero.gold, len(hero.tavern), len(hero.hand)
    entity = buy.src_entity
    res = driver.apply_action(game, hero, buy)
    assert res.success, res.error
    assert entity not in hero.tavern
    assert len(hero.tavern) == tavern0 - 1
    assert len(hero.hand) == hand0 + 1
    assert hero.gold == gold0 - buy.cost


def test_sell_semantics():
    game, heroes = make_engine_game(seed=2)
    hero = heroes[0]
    add_minion_to_board(game, hero)
    add_minion_to_board(game, hero, "BGS_119")
    gold0, board0 = hero.gold, len(hero.board)
    zones = driver.collect_zones(game, hero)
    descs = driver.enumerate_actions(game, hero, zones)
    sells = [d for d in descs if d.kind == ActionKind.SELL.value]
    assert len(sells) == board0
    res = driver.apply_action(game, hero, sells[0])
    assert res.success and len(hero.board) == board0 - 1
    assert hero.gold == gold0 + 1


def test_play_minion_semantics():
    game, heroes = make_engine_game(seed=3)
    hero = heroes[0]
    add_minion_to_board(game, hero)                  # 已有 1 个随从
    m = add_minion_to_hand(game, hero)
    assert len(hero.hand) == 1
    zones = driver.collect_zones(game, hero)
    descs = driver.enumerate_actions(game, hero, zones)
    plays = [d for d in descs
             if d.kind == ActionKind.PLAY_MINION.value and not d.magnetic]
    assert plays
    # 位置变体：-1（追加）+ 0..len(board)-1
    positions = {d.position for d in plays}
    assert -1 in positions and 0 in positions
    res = driver.apply_action(game, hero, plays[0])
    assert res.success, res.error
    assert m in hero.board and m not in hero.hand
    assert len(hero.board) == 2


def test_reroll_semantics():
    game, heroes = make_engine_game(seed=4)
    hero = heroes[0]
    gold0 = hero.gold
    zones = driver.collect_zones(game, hero)
    descs = driver.enumerate_actions(game, hero, zones)
    reroll = _first(descs, ActionKind.REROLL.value)
    assert reroll is not None
    old_ids = [e.card_id for e in hero.tavern]
    res = driver.apply_action(game, hero, reroll)
    assert res.success
    assert hero.gold == gold0 - 1
    assert len(hero.tavern) == len(old_ids)          # 展示位数量不变
    assert [e.card_id for e in hero.tavern] != old_ids


def test_upgrade_semantics():
    game, heroes = make_engine_game(seed=5)
    hero = heroes[0]
    hero.gold = 10
    zones = driver.collect_zones(game, hero)
    upgrade = _first(driver.enumerate_actions(game, hero, zones),
                     ActionKind.UPGRADE.value)
    assert upgrade is not None
    gold0, tier0 = hero.gold, hero.tavern_tier
    cost = upgrade.cost
    res = driver.apply_action(game, hero, upgrade)
    assert res.success
    assert hero.tavern_tier == tier0 + 1
    assert hero.gold == gold0 - cost


def test_freeze_candidate_one_way():
    """freeze 只在未冻结时生成（避免免费无限 toggle）。"""
    game, heroes = make_engine_game(seed=6)
    hero = heroes[0]
    freeze = _first(driver.enumerate_actions(game, hero),
                    ActionKind.FREEZE.value)
    assert freeze is not None and not hero.frozen_tavern
    assert driver.apply_action(game, hero, freeze).success
    assert hero.frozen_tavern
    # 已冻结 → 不再生成 freeze（也没有"解冻"候选）
    descs = driver.enumerate_actions(game, hero)
    assert all(d.kind != ActionKind.FREEZE.value for d in descs)
    # 回合开始的自动刷新会消耗冻结标记 → 下一回合 freeze 候选重新出现
    game.refresh_tavern(hero, auto=True)
    assert not hero.frozen_tavern
    assert _first(driver.enumerate_actions(game, hero),
                  ActionKind.FREEZE.value) is not None


def test_turn_action_budget_limits_candidates():
    """达到每回合动作预算后，候选只剩 end_turn（选择步除外）。"""
    budget = 3
    env = BattlegroundsEnv(seed=70, max_actions_per_turn=budget)
    obs = env.reset(seed=70)
    used = 0
    for _ in range(200):
        if obs.phase == "choice":
            obs, _r, term, trunc, _i = env.step(0)
            assert not term and not trunc
            continue
        kinds = [c.kind for c in obs.candidates]
        if used >= budget:
            assert kinds == [ActionKind.END_TURN.value], kinds
            break
        idx = next((i for i, c in enumerate(obs.candidates)
                    if c.kind not in (ActionKind.END_TURN.value,
                                      ActionKind.CHOOSE.value)), None)
        assert idx is not None, kinds
        obs, _r, term, trunc, _i = env.step(idx)
        assert not term and not trunc
        used += 1
    else:                                                 # pragma: no cover
        pytest.fail("未在 200 步内达到动作预算上限")
    # 计数在回合切换时重置：结束回合后候选恢复多样
    idx = next(i for i, c in enumerate(obs.candidates)
               if c.kind == ActionKind.END_TURN.value)
    obs, _r, term, trunc, _i = env.step(idx)
    if not (term or trunc):
        assert len(obs.candidates) > 1
        assert [c.kind for c in obs.candidates] != [ActionKind.END_TURN.value]
    env.close()


def test_no_progress_guard_forces_end_turn():
    """连续无进展计数达到阈值后，候选只剩 end_turn（防御 no-op 死循环）。

    历史教训：原实现扫 `seed 0..29` 找"初始候选 >1"的局；RNG 流位移时可能
    整段扫不到（对引擎随机流过度耦合）。开局（第 1 回合）必然有"买随从"
    候选（3 金 + 4 张酒馆随从），因此固定 seed 0 即可，附少量兜底 seed。
    """
    env = None
    obs = None
    for seed in (0, 1, 2):
        candidate = BattlegroundsEnv(seed=seed)
        obs_try = candidate.reset(seed=seed)
        # 跳过开局选择步（少数英雄绑定时会挂 PendingChoice）
        for _ in range(5):
            if obs_try.phase != "choice":
                break
            obs_try, _r, term, trunc, _i = candidate.step(0)
            assert not term and not trunc
        if obs_try.phase == "recruit" and len(obs_try.candidates) > 1:
            env, obs = candidate, obs_try
            break
        candidate.close()
    assert env is not None, "开局应存在多个候选动作（买随从/刷新/结束回合）"
    fp1 = env._progress_fingerprint()
    assert fp1
    # 真实动作会改变指纹
    idx = next(i for i, c in enumerate(obs.candidates)
               if c.kind not in (ActionKind.END_TURN.value,
                                 ActionKind.CHOOSE.value))
    env.step(idx)
    assert env._progress_fingerprint() != fp1
    assert env._no_progress == 0
    # 模拟连续无进展：达到阈值后候选只剩 end_turn
    env._no_progress = env._no_progress_limit
    obs2 = env._observe()
    assert [c.kind for c in obs2.candidates] == [ActionKind.END_TURN.value]
    # 结束回合（回合切换）后计数重置
    env.step(0)
    assert env._no_progress == 0
    env.close()


def test_hand_full_blocks_buy():
    game, heroes = make_engine_game(seed=7)
    hero = heroes[0]
    for _ in range(10):
        add_minion_to_hand(game, hero, VANILLA_MINION)
    assert hero.hand_full()
    descs = driver.enumerate_actions(game, hero)
    assert all(d.kind != ActionKind.BUY.value for d in descs)


def test_board_full_blocks_play_but_allows_sell():
    game, heroes = make_engine_game(seed=8)
    hero = heroes[0]
    for _ in range(7):
        add_minion_to_board(game, hero, VANILLA_MINION)
    assert hero.board_full()
    m = add_minion_to_hand(game, hero, "BGS_119")     # 非磁力
    descs = driver.enumerate_actions(game, hero)
    assert all(d.kind != ActionKind.PLAY_MINION.value for d in descs)
    assert any(d.kind == ActionKind.SELL.value for d in descs)
    # 卖一个之后就能打出
    sell = _first(descs, ActionKind.SELL.value)
    assert driver.apply_action(game, hero, sell).success
    descs2 = driver.enumerate_actions(game, hero)
    plays = [d for d in descs2 if d.kind == ActionKind.PLAY_MINION.value]
    assert plays
    assert driver.apply_action(game, hero, plays[0]).success
    assert m in hero.board


def test_no_gold_blocks_purchase_and_reroll():
    game, heroes = make_engine_game(seed=9)
    hero = heroes[0]
    hero.gold = 0
    descs = driver.enumerate_actions(game, hero)
    kinds = _kinds(descs)
    assert ActionKind.BUY.value not in kinds
    assert ActionKind.REROLL.value not in kinds
    assert ActionKind.UPGRADE.value not in kinds
    assert ActionKind.END_TURN.value in kinds


def test_apply_action_captures_engine_error():
    """金币不足的刷新会抛 GameStateError → 必须被捕获为失败结果。"""
    game, heroes = make_engine_game(seed=10)
    hero = heroes[0]
    hero.gold = 0
    desc = driver.ActionDescriptor(kind=ActionKind.REROLL.value)
    res = driver.apply_action(game, hero, desc)
    assert not res.success
    assert res.error_type == "GameStateError"
    assert isinstance(res.error, str) and res.error


def test_invalid_action_does_not_advance():
    env = BattlegroundsEnv(seed=13, reward=RewardConfig(invalid_action=-0.07))
    obs = env.reset(seed=13)
    before = (obs.turn, obs.hero.gold, tuple(obs.candidates))
    bad = CandidateAction(kind=ActionKind.SELL.value, src_zone="board",
                          src_slot=99)
    obs2, reward, term, trunc, info = env.step(bad)
    assert info["invalid"] is True and info["wrong_action"] is True
    assert reward == pytest.approx(-0.07)
    assert not term and not trunc
    assert (obs2.turn, obs2.hero.gold, tuple(obs2.candidates)) == before
    env.close()


def test_engine_rejection_is_invalid_not_crash():
    """引擎返回 False 的候选（理论上不该出现）→ invalid，不崩溃。"""
    env = BattlegroundsEnv(seed=14)
    env.reset(seed=14)
    # 伪造一个"卖出不在棋盘上的实体"的动作描述符
    from hsrl2.minion import Minion
    fake = Minion("BG25_001", "fake", atk=1, health=1)
    desc = driver.ActionDescriptor(kind=ActionKind.SELL.value, src_entity=fake,
                                   src_zone="board", src_slot=0)
    env._step_actions.descriptors[0] = desc
    obs, reward, term, trunc, info = env.step(0)
    assert info["invalid"] is True
    assert info["action_error_type"] == "Rejected"
    assert not term
    env.close()


def test_pending_choice_fifo_contract():
    game, heroes = make_engine_game(seed=11)
    a, b = heroes[0], heroes[1]
    resolved = []

    def _mk(owner, tag):
        def _resolve(pick):
            resolved.append((tag, pick))
        return PendingChoice(owner, ["x", "y", "z"], f"test_{tag}",
                             resolve_callback=_resolve)

    game.pending_choices.append(_mk(b, "b"))
    game.pending_choices.append(_mk(a, "a"))
    # 只结算非 a 的选择 → 队首 a 不弹出并返回
    pending = driver.resolve_pending_choices(game, a)
    assert pending is not None and pending.kind == "test_a"
    assert [c.kind for c in game.pending_choices] == ["test_a"]
    assert resolved == [("b", "x")]                  # FIFO + 默认选项
    # 给出 policy_fn → a 的选择也结算并出队
    pending = driver.resolve_pending_choices(game, a, lambda c: 2)
    assert pending is None
    assert not game.pending_choices
    assert resolved[-1] == ("a", "z")


def test_pending_choice_choose_action_applies_and_pops():
    env = BattlegroundsEnv(seed=15)
    obs = env.reset(seed=15)
    # 构造一个属于智能体的待决选择（不依赖具体英雄技能）
    agent = env.agent_hero
    env.game.pending_choices.append(PendingChoice(
        agent, ["o0", "o1"], "unit_test", resolve_callback=lambda x: None))
    obs = env._observe()
    assert obs.phase == "choice"
    assert [(c.kind, c.option) for c in obs.candidates] == [
        ("choose", 0), ("choose", 1)]
    obs2, _r, term, trunc, info = env.step(CandidateAction(kind="choose",
                                                           option=1))
    assert not info["invalid"]
    assert not term
    assert not env.game.pending_choices
    assert obs2.phase == "recruit"
    env.close()


def test_choice_option_out_of_range_is_invalid():
    env = BattlegroundsEnv(seed=16)
    env.reset(seed=16)
    agent = env.agent_hero
    env.game.pending_choices.append(PendingChoice(
        agent, ["only"], "unit_test", resolve_callback=lambda x: None))
    obs = env._observe()
    assert len(obs.candidates) == 1
    bad = CandidateAction(kind="choose", option=5)
    _obs, reward, term, trunc, info = env.step(bad)
    assert info["invalid"] is True
    assert not term
    env.close()


def test_dark_gift_candidate_and_resolution():
    game, heroes = make_engine_game(seed=17)
    hero = heroes[0]
    game.turn = 3
    hero.gold = 3
    descs = driver.enumerate_actions(game, hero)
    gift = _first(descs, ActionKind.USE_DARK_GIFT.value)
    assert gift is not None
    res = driver.apply_action(game, hero, gift)
    assert res.success
    assert hero.gold == 0
    # dark gift 会产生属于该英雄的选择 → FIFO 结算
    pending = driver.resolve_pending_choices(game, hero, lambda c: 0)
    assert pending is None
    assert not game.pending_choices


def test_hero_power_candidate_present_for_active_power():
    game, heroes = make_engine_game(seed=18)
    found = False
    for hero in heroes:
        zones = driver.collect_zones(game, hero)
        descs = driver.enumerate_actions(game, hero, zones)
        power = _first(descs, ActionKind.HERO_POWER.value)
        if power is None:
            continue
        found = True
        gold0 = hero.gold
        res = driver.apply_action(game, hero, power)
        assert res.success, res.error
        assert hero.gold == gold0 - max(0, power.cost)
        driver.resolve_pending_choices(game, None)
        break
    assert found, "8 名英雄里应至少有一个可用主动英雄技能"
