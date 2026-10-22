"""``tests/test_planning.py`` —— AlphaZero 类搜索的 clone / forward 原语测试。

覆盖 `hsbg/planning/model.py`：

1. **clone 隔离性**：副本与原对象无共享可变状态，推进副本不影响原对象；
2. **clone 一致性**：RNG 状态、PendingChoice、pending_hand_queue、
   deferred_actions、战斗期 `_active_combat` 等全部复制；
3. **确定性**：同 seed/同动作序列 → 两个 clone 的状态签名一致；
4. **API 可用性**：legal_actions / apply / drain_choices /
   random_rollout / evaluate；
5. **性能契约**：clone 必须走 CardDB 共享（< 原生 deepcopy 的 1/10），
   这是 MCTS 可行的前提（基准见 scripts/bench_planning.py）。
"""

from __future__ import annotations

import time

import pytest

from hsrl2.events import BEFORE_ATTACK, Listener
from hsrl2.game import PendingChoice
from hsrl2.tags import GameTag

from hsbg.agents.base import choose_option_index
from hsbg.env import BattlegroundsEnv, driver
from hsbg.planning import model
from tests.test_env_support import make_engine_game


# ══════════════════════════════════════════════════════════════════════
# 状态签名（用于"一致性/确定性"比较；不依赖 pickle 可序列化）
# ══════════════════════════════════════════════════════════════════════


def _clean_decision(d) -> str:
    """去掉 decisions 字符串里的实体内存地址（跨 clone 必然不同）。"""
    import re
    return re.sub(r"\([0-9a-f]{6,}\)", "", str(d))


def _canon_tag(value):
    """tag 值的规范化表示（frozenset/set 顺序无关，跨 clone 稳定）。"""
    from hsbg.planning.digest import _canon
    return _canon(value)


def _entity_sig(e) -> tuple:
    return (
        str(getattr(e, "card_id", "")),
        int(getattr(e, "atk", 0) or 0),
        int(getattr(e, "health", 0) or 0),
        int(getattr(e, "zone", 0) or 0),
        tuple(sorted(f"{k.name}={_canon_tag(v)}" for k, v in
                     sorted(e.tags.items(), key=lambda kv: kv[0].name))),
    )


def _state_signature(game) -> tuple:
    heroes = []
    for h in game.heroes:
        heroes.append((
            str(h.card_id),
            int(h.health), int(h.armor), int(h.gold),
            int(h.tavern_tier),
            bool(h.frozen_tavern),
            tuple(str(e.card_id) for e in h.hand),
            tuple(_entity_sig(m) for m in h.board),
            tuple(str(e.card_id) for e in h.tavern),
            tuple(str(t.card_id) for t in h.trinkets),
            str(getattr(h, "quest", None) and h.quest.card_id),
            dict(h._power_uses_this_turn),
            dict(h._power_uses_this_game),
        ))
    return (
        int(game.turn),
        bool(game.finished),
        bool(game.in_combat),
        tuple(heroes),
        tuple((c.kind, str(getattr(c.owner, "card_id", "")),
               tuple(str(getattr(o, "card_id", o)) for o in c.options))
              for c in game.pending_choices),
        tuple(str(getattr(h, "card_id", ""))
              for h, _e in getattr(game, "pending_hand_queue", [])),
        len(getattr(game, "deferred_actions", []) or []),
        tuple(sorted(str(k) for k in getattr(game, "_magnetic_stack", {}))),
        # RNG 状态（GameRNG 内部用 random.Random；decisions 为脚本决策记录）
        int(getattr(game.rng, "seed_value", 0)),
        game.rng._rng.getstate(),
        # decisions 内含 repr 字符串（带实体内存地址）→ 归一化后再比较
        tuple(_clean_decision(d) for d in game.rng.decisions),
    )


def _eight_player_game(seed: int = 0):
    """8 人真实局（start_game + 开局选择已结算）。"""
    return make_engine_game(seed=seed, num_players=8)


def _play_heuristic_turns(env, turns: int):
    """用启发式策略推进 env 若干回合（构造中后期局面用）。"""
    from hsbg.agents.heuristic import HeuristicPolicy
    policy = HeuristicPolicy()
    obs = env._obs
    while int(env.game.turn) <= turns:
        if obs.phase == "choice":
            action = obs.candidates[choose_option_index(policy, obs, env.game)]
        else:
            desc = policy.choose(env.game, env.agent_hero)
            if desc is None:
                idx = next(i for i, c in enumerate(obs.candidates)
                           if c.kind == "end_turn")
                action = obs.candidates[idx]
            else:
                action = desc.to_candidate()
        obs, _r, term, trunc, _i = env.step(action)
        if term or trunc:
            break
    return env


# ══════════════════════════════════════════════════════════════════════
# clone：隔离性 / 一致性
# ══════════════════════════════════════════════════════════════════════


def test_clone_shares_db_but_isolates_entities():
    game, heroes = _eight_player_game(seed=1)
    dup = model.clone(game)
    assert dup is not game
    assert dup.db is game.db                       # CardDB 只读共享（性能前提）
    assert dup.heroes is not game.heroes
    assert dup.heroes[0] is not game.heroes[0]
    assert dup.rng is not game.rng
    # 副本推进：结束一个招募回合，原对象状态不得变化
    before = _state_signature(game)
    dup.end_recruit_phase()
    driver.resolve_pending_choices(dup, None)
    after = _state_signature(game)
    assert before == after, "推进 clone 影响了原 game"
    assert _state_signature(dup) != before


def test_clone_same_state_after_no_actions():
    game, _heroes = _eight_player_game(seed=2)
    a = model.clone(game)
    b = model.clone(game)
    assert _state_signature(a) == _state_signature(b) == _state_signature(game)


def test_clone_deterministic_after_same_actions():
    game, heroes = _eight_player_game(seed=3)
    a = model.clone(game)
    b = model.clone(game)
    for g in (a, b):
        for _ in range(3):
            end = next(d for d in model.legal_actions(g, g.heroes[0])
                       if d.kind == driver.ActionKind.END_TURN.value)
            assert model.apply(g, g.heroes[0], end).success
            g.end_recruit_phase()
            driver.resolve_pending_choices(g, None)
    assert _state_signature(a) == _state_signature(b), "clone 非确定"
    # 原对象仍未推进
    assert int(game.turn) == 1


def test_clone_rng_isolated():
    game, _heroes = _eight_player_game(seed=4)
    clone = model.clone(game)
    # 副本消耗 RNG 不影响原对象：原对象与另一份 clone 的下一个随机数一致
    clone.rng.random()
    game2 = model.clone(game)
    assert game.rng.random() == game2.rng.random()
    # 两个副本同序消耗 RNG → 取值序列一致
    a = model.clone(game)
    b = model.clone(game)
    seq_a = [a.rng.random() for _ in range(5)]
    seq_b = [b.rng.random() for _ in range(5)]
    assert seq_a == seq_b
    # rng 状态完全被复制：两份 clone 的 RNG 内部状态相等
    assert a.rng._rng.getstate() == b.rng._rng.getstate()


def test_clone_pending_choice_isolated():
    game, heroes = _eight_player_game(seed=5)
    hero = heroes[0]
    m1 = game.create_minion("BG25_001", controller=hero)
    game.summon(hero, m1)
    m2 = game.create_minion("BG25_001", controller=hero)
    game.summon(hero, m2)
    game.pending_choices.append(
        PendingChoice(hero, [m1, m2], "test_choice"))
    clone = model.clone(game)
    assert len(clone.pending_choices) == 1
    original_before = _state_signature(game)
    # 在副本里选第一个选项（clone 的 legal_actions 应暴露 choose 候选）
    choices = model.legal_actions(clone, clone.heroes[0])
    assert choices and all(d.kind == driver.ActionKind.CHOOSE.value
                           for d in choices)
    assert model.apply(clone, clone.heroes[0],
                       choices[0]).success
    assert clone.pending_choices == []
    # 原对象的选择队列与状态不变
    assert len(game.pending_choices) == 1
    assert _state_signature(game) == original_before


def test_clone_rebind_quest_callbacks_do_not_touch_original():
    """回归：quest_offer 的 resolve 闭包捕获原 hero/game，clone 必须重绑。

    旧实现（纯 deepcopy）在副本上结算 quest_offer 会把任务装到**原对局**
    英雄身上（2026-10-19 实测），是搜索"分支互相污染"的隐蔽 bug。
    """
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=10)
    env.reset(seed=10)
    _play_heuristic_turns(env, 3)
    game = env.game
    assert game.pending_choices, "第 4 回合应有 quest_offer 待选"
    assert all(c.kind == "quest_offer" for c in game.pending_choices)
    before = _state_signature(game)
    assert all(getattr(h, "quest", None) is None for h in game.heroes)
    dup = model.clone(game)
    assert dup.pending_choices[0] is not game.pending_choices[0]
    driver.resolve_pending_choices(dup, None)
    # 副本结算后：原局任务仍为空、状态不变；副本英雄拿到任务
    assert _state_signature(game) == before
    assert all(getattr(h, "quest", None) is None for h in game.heroes)
    assert any(getattr(h, "quest", None) is not None for h in dup.heroes)
    env.close()


def test_clone_rebind_constructed_lambda_isolated():
    """构造闭包回调：clone(rebind=True) 只影响副本；rebind=False 是反例。"""
    captured = {}

    def _make():
        game, heroes = _eight_player_game(seed=20)
        hero = heroes[0]
        m = game.create_minion("BG25_001", controller=hero)
        game.summon(hero, m)

        def on_choose(pick):
            # 闭包捕获 **原** hero —— 正是引擎里的回调写法
            hero.take_damage(1)
            captured["pick"] = pick

        game.pending_choices.append(
            PendingChoice(hero, [m], "test_choice",
                          resolve_callback=on_choose))
        return game, hero, m

    game, hero, _m = _make()
    health_before = int(hero.health)
    dup = model.clone(game)
    actions = model.legal_actions(dup, dup.heroes[0])
    assert model.apply(dup, dup.heroes[0], actions[0]).success
    assert int(hero.health) == health_before, "clone 的回调污染了原对局"
    assert int(dup.heroes[0].health) == health_before - 1

    # 反例：不重绑时闭包仍指向原 hero（证明 rebind 的必要性）
    game2, hero2, _m2 = _make()
    health2 = int(hero2.health)
    dup2 = model.clone(game2, rebind=False)
    actions2 = model.legal_actions(dup2, dup2.heroes[0])
    assert model.apply(dup2, dup2.heroes[0], actions2[0]).success
    assert int(hero2.health) == health2 - 1, \
        "rebind=False 应复现闭包污染（否则本测试失去意义）"


def test_clone_rebind_listener_closures_isolated():
    """事件 Listener 的闭包（引擎内 event 回调同款）也必须重绑。"""
    game, heroes = _eight_player_game(seed=21)
    hero = heroes[0]
    m = game.create_minion("BG25_001", controller=hero)
    game.summon(hero, m)
    base = int(m.health)
    hits = []

    def on_event(g, **kw):
        hits.append(1)
        m.take_damage(1)                 # 闭包捕获原随从

    game.events.register(Listener(event="test_event", owner=m,
                                  callback=on_event))
    dup = model.clone(game)
    assert dup.events._listeners["test_event"][0].callback is not on_event
    dup.events.fire(dup, "test_event")
    assert int(m.health) == base, "clone 的 Listener 闭包污染原随从"
    assert int(dup.heroes[0].board[0].health) == base - 1


def test_clone_pending_hand_queue_isolated():
    game, heroes = _eight_player_game(seed=6)
    hero = heroes[0]
    for _ in range(10):
        m = game.create_minion("BG25_001", controller=hero)
        assert hero.add_to_hand(m)
    assert hero.hand_full()
    game.pending_hand_queue.append(
        (hero, game.create_minion("BG25_001", controller=hero)))
    clone = model.clone(game)
    assert len(clone.pending_hand_queue) == 1
    clone.pending_hand_queue.clear()
    assert len(game.pending_hand_queue) == 1
    assert len(clone.heroes[0].hand) == len(hero.hand)


def test_clone_combat_state_copied():
    """战斗期（in_combat / _active_combat / 战斗日志）clone 后保持一致。"""
    game, heroes = _eight_player_game(seed=7)
    a, b = heroes[0], heroes[1]
    for h in (a, b):
        h.health, h.armor = 40, 0
        h.gold = 10
        game.refresh_tavern(h)
        for cid in ("BG25_001", "BGS_119", "BG25_008"):
            game.summon(h, game.create_minion(cid, controller=h))
    captured = {}

    def on_attack(g, **_kw):
        if "clone" not in captured:
            captured["clone"] = model.clone(g)
            captured["in_combat"] = bool(g.in_combat)
            captured["active"] = getattr(g, "_active_combat", None) is not None
            captured["deaths"] = len(g.combat_death_log)
            return None
        return None

    game.events.register(Listener(event=BEFORE_ATTACK, owner=a,
                                  callback=on_attack, once=True))
    game.run_combat(a, b, alive_count=8)
    clone = captured.get("clone")
    assert clone is not None, "未在战斗期捕获 clone"
    assert captured["in_combat"] and captured["active"]
    assert bool(clone.in_combat) is True
    assert getattr(clone, "_active_combat", None) is not None
    assert len(clone.combat_death_log) == captured["deaths"]
    # 副本继续推进不影响原对象
    before = _state_signature(game)
    clone.run_combat(a, b, alive_count=8) if not clone.finished else None
    assert _state_signature(game) == before


# ══════════════════════════════════════════════════════════════════════
# API：legal_actions / apply / drain_choices / rollout / evaluate
# ══════════════════════════════════════════════════════════════════════


def test_legal_actions_and_apply():
    game, heroes = _eight_player_game(seed=8)
    hero = heroes[0]
    actions = model.legal_actions(game, hero)
    assert actions
    kinds = {d.kind for d in actions}
    assert driver.ActionKind.END_TURN.value in kinds
    assert driver.ActionKind.BUY.value in kinds
    # 应用买一个随从 / 或任意非 end 动作
    non_end = [d for d in actions if d.kind != "end_turn"]
    res = model.apply(game, hero, non_end[0])
    assert res.success, res.error
    # apply 支持下标 / CandidateAction
    actions2 = model.legal_actions(game, hero)
    assert model.apply(game, hero, len(actions2) - 1).success
    actions3 = model.legal_actions(game, hero)
    cand = actions3[0].to_candidate()
    assert model.apply(game, hero, cand).success
    # 非法下标 → 失败但不抛异常
    for bad in (999, -1, "x", None):
        r = model.apply(game, hero, bad)
        assert not r.success


def test_apply_auto_choice():
    game, heroes = _eight_player_game(seed=9)
    hero = heroes[0]
    m1 = game.create_minion("BG25_001", controller=hero)
    game.summon(hero, m1)
    m2 = game.create_minion("BG25_001", controller=hero)
    game.summon(hero, m2)
    game.pending_choices.append(
        PendingChoice(hero, [m1, m2], "test_choice"))
    choice_actions = model.legal_actions(game, hero)
    assert choice_actions
    res = model.apply(game, hero, choice_actions[0], auto_choice=True)
    assert res.success
    assert game.pending_choices == []


def test_random_rollout_deterministic_and_isolated():
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=10)
    env.reset(seed=10)
    _play_heuristic_turns(env, 3)
    game = env.game
    before = _state_signature(game)

    a = model.clone(game)
    b = model.clone(game)
    r1 = model.random_rollout(a, a.heroes[0],
                              model.RandomRolloutPolicy(seed=17))
    r2 = model.random_rollout(b, b.heroes[0],
                              model.RandomRolloutPolicy(seed=17))
    assert r1.steps > 0
    assert r1.turns == 1
    assert r1.as_dict() == r2.as_dict()
    assert _state_signature(a) == _state_signature(b)
    assert _state_signature(game) == before      # 原对局不被 rollout 改动
    assert 1 <= r1.rank <= 8
    env.close()


def test_random_rollout_multiple_turns_and_terminal_guard():
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=11)
    env.reset(seed=11)
    _play_heuristic_turns(env, 4)
    game = model.clone(env.game)
    result = model.random_rollout(
        game, game.heroes[0],
        model.RandomRolloutPolicy(seed=3, end_turn_prob=3.0),
        max_turns=2)
    assert result.turns >= 1
    assert result.steps > 0
    assert isinstance(result.terminated, bool)
    # 已经终局的局面再 rollout → terminated 且步数 0
    dead = model.clone(env.game)
    hero = dead.heroes[0]
    hero.take_damage(int(hero.health) + int(hero.armor))
    r = model.random_rollout(dead, hero)
    assert r.terminated and r.steps == 0
    env.close()


def test_rollout_policy_rng_independent():
    """rollout 策略 RNG 独立：同一策略 seed 但不同政策不影响引擎判定？"""
    policy = model.RandomRolloutPolicy(seed=5)
    a = model.RandomRolloutPolicy(seed=5)
    b = model.RandomRolloutPolicy(seed=5)
    vals_a = [a.rng.random() for _ in range(5)]
    vals_b = [b.rng.random() for _ in range(5)]
    assert vals_a == vals_b
    assert isinstance(policy.rng.random(), float)


def test_evaluate_placeholder():
    game, heroes = _eight_player_game(seed=12)
    hero = heroes[0]
    ev = model.evaluate(game, hero)
    for key in ("value", "board_power", "health", "armor", "tier", "hand",
                "alive", "rank_estimate"):
        assert key in ev, key
        assert isinstance(ev[key], float)
    assert -1.0 <= ev["value"] <= 1.0
    assert ev["rank_estimate"] >= 1
    # 死亡局面 value 应更低（同一局面构造：扣光生命）
    dead = model.clone(game)
    d_hero = dead.heroes[0]
    d_hero.take_damage(int(d_hero.health) + int(d_hero.armor))
    assert not d_hero.is_alive
    assert model.evaluate(dead, d_hero)["value"] < model.evaluate(
        game, hero)["value"]


def test_clone_is_fast_when_db_shared():
    """clone 必须显著快于原生 deepcopy（共享 CardDB 是 MCTS 可行前提）。"""
    import copy
    game, _heroes = _eight_player_game(seed=13)
    t0 = time.perf_counter()
    for _ in range(3):
        model.clone(game)
    fast = (time.perf_counter() - t0) / 3.0
    t0 = time.perf_counter()
    copy.deepcopy(game)
    raw = time.perf_counter() - t0
    assert fast < raw / 5.0, f"clone={fast*1000:.2f}ms raw={raw*1000:.2f}ms"


# ══════════════════════════════════════════════════════════════════════
# clone v1（fast/deepcopy 等价）、checkpoint、rng、combat、digest、hidden
# ══════════════════════════════════════════════════════════════════════


def _combat_pair(seed: int = 30):
    """2 人战斗局面（双方 3 随从、40 血）。"""
    from tests.test_env_support import make_engine_game
    game, heroes = make_engine_game(seed=seed, num_players=2)
    a, b = heroes[0], heroes[1]
    for h in (a, b):
        h.health, h.armor = 40, 0
        h.gold = 10
        game.refresh_tavern(h)
        for cid in ("BG25_001", "BGS_119", "BG25_008"):
            game.summon(h, game.create_minion(cid, controller=h))
    return game, a, b


def test_fast_clone_matches_deepcopy():
    """fast 结构化拷贝与 deepcopy 策略在多种局面下状态等价。"""
    from hsbg.planning.digest import digest as dg
    cases = [("T1", 1), ("T4", 4)]
    for label, turns in cases:
        env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=3)
        obs = env.reset(seed=3)
        _play_heuristic_turns(env, turns)
        game = env.game
        fast = model.clone(game)
        deep = model.clone(game, strategy="deepcopy")
        assert _state_signature(fast) == _state_signature(deep) \
            == _state_signature(game), label
        assert dg(fast) == dg(deep) == dg(game), label
        assert dg(fast, "full") == dg(game, "full"), label
        # 同动作推进后行为一致
        for dup in (fast, deep):
            end = next(d for d in model.legal_actions(dup, dup.heroes[0])
                       if d.kind == driver.ActionKind.END_TURN.value)
            assert model.apply(dup, dup.heroes[0], end).success
            dup.end_recruit_phase()
            driver.resolve_pending_choices(dup, None)
        assert _state_signature(fast) == _state_signature(deep), label
        env.close()


def test_checkpoint_push_pop_isolated():
    from hsbg.planning import checkpoint
    from hsbg.planning.digest import digest as dg
    game, _heroes = _eight_player_game(seed=41)
    cp = checkpoint.push_checkpoint(game, label="root")
    assert cp.turn == game.turn
    restored = checkpoint.pop_checkpoint(cp)
    assert restored is not cp.game
    assert dg(restored) == dg(game)
    # 推进 restored 不影响快照/原局
    snap_before = dg(cp.game)
    orig_before = dg(game)
    restored.end_recruit_phase()
    driver.resolve_pending_choices(restored, None)
    assert dg(cp.game) == snap_before
    assert dg(game) == orig_before
    # 快照可重复恢复（每次独立）
    r1 = checkpoint.pop_checkpoint(cp)
    r2 = checkpoint.pop_checkpoint(cp)
    assert r1 is not r2
    r1.end_recruit_phase()
    driver.resolve_pending_choices(r1, None)
    assert dg(r2) == snap_before


def test_checkpoint_stack_lifo():
    from hsbg.planning import checkpoint
    game, _heroes = _eight_player_game(seed=42)
    stack = checkpoint.CheckpointStack(game)
    stack.push()
    first = checkpoint.pop_checkpoint(stack.peek())
    first.end_recruit_phase()
    driver.resolve_pending_choices(first, None)
    stack.push(first)
    assert stack.depth == 2
    back_mid = stack.pop()
    assert back_mid.turn == first.turn
    back_root = stack.pop()
    assert back_root.turn == game.turn
    assert stack.depth == 0
    with pytest.raises(IndexError):
        stack.pop()


def test_rng_get_set_fork():
    from hsbg.planning import rng as planning_rng
    game, _heroes = _eight_player_game(seed=43)
    rng = game.rng
    st = planning_rng.get_state(rng)
    assert st["seed"] == 43
    # fork 同状态 → 同未来
    f1 = planning_rng.fork(rng)
    f2 = planning_rng.fork(rng)
    assert planning_rng.state_equal(f1, f2)
    draws1 = [f1.random() for _ in range(6)]
    draws2 = [f2.random() for _ in range(6)]
    assert draws1 == draws2
    # set_state 恢复：恢复后与 fork 同流
    planning_rng.set_state(f2, st)
    assert planning_rng.state_equal(f2, planning_rng.fork(rng))
    # 带 seed 的 fork 独立（decisions 清空）
    seeded = planning_rng.fork(rng, seed=7)
    assert seeded.seed_value == 7 and seeded.decisions == []
    # clone 的 RNG 状态与原件一致
    dup = model.clone(game)
    assert dup.rng._rng.getstate() == game.rng._rng.getstate()
    dup.rng.random()
    assert game.rng._rng.getstate() != dup.rng._rng.getstate()


def test_rng_api_cost():
    from hsbg.planning import rng as planning_rng
    game, _heroes = _eight_player_game(seed=44)
    rng = game.rng
    st = planning_rng.get_state(rng)
    t0 = time.perf_counter()
    for _ in range(200):
        planning_rng.get_state(rng)
        f = planning_rng.fork(rng)
        planning_rng.set_state(f, st)
    mean_ms = (time.perf_counter() - t0) / 200 * 1000.0
    assert mean_ms < 0.5, f"rng get+set+fork too slow: {mean_ms:.3f}ms"


def test_simulate_combat_no_side_effect():
    from hsbg.planning.digest import digest as dg
    game, a, b = _combat_pair(seed=45)
    before = dg(game)
    summary1, dup1 = model.simulate_combat(game, a, b, alive_count=2,
                                           keep_state=True)
    after = dg(game)
    assert before == after, "simulate_combat 修改了原 game"
    assert dup1 is not None and dup1 is not game
    summary2, _ = model.simulate_combat(game, a, b, alive_count=2)
    assert summary1 == summary2, "simulate_combat 不确定"
    assert set(summary1) >= {"winner", "loser", "damage_dealt",
                             "capped_damage", "rounds"}
    assert summary1["capped_damage"] >= 0
    # 与直接 run_combat 结果一致（在独立 clone 上）
    direct = model.clone(game)
    res = direct.run_combat(direct.heroes[0], direct.heroes[1],
                            alive_count=2)
    assert summary1["capped_damage"] == int(res.capped_damage)
    assert summary1["winner"] == str(getattr(res.winner, "card_id", ""))


def test_digest_stable_and_sensitive():
    from hsbg.planning.digest import digest as dg
    game, heroes = _eight_player_game(seed=46)
    hero = heroes[0]
    dup = model.clone(game)
    assert dg(dup) == dg(game)
    assert dg(dup, "full") == dg(game, "full")
    before = dg(game)
    # 合法动作改变状态 → 摘要改变
    actions = [d for d in model.legal_actions(game, hero)
               if d.kind == driver.ActionKind.BUY.value]
    if actions:
        assert model.apply(game, hero, actions[0]).success
        assert dg(game) != before
    t0 = time.perf_counter()
    for _ in range(100):
        dg(game)
    assert (time.perf_counter() - t0) / 100 * 1000.0 < 2.0


def test_hidden_injection_v0():
    from hsbg.planning.digest import digest as dg
    from hsbg.planning import hidden
    game, hero = _eight_player_game(seed=47)
    dup = model.clone(game)
    target = dup.heroes[1]
    before = dg(dup)
    counts = hidden.inject_hidden_state(
        dup, target,
        board=["BG25_001", {"card_id": "BGS_119", "atk": 5, "health": 7,
                            "keywords": ["TAUNT"]}],
        hand=["BG25_001"],
        tavern=["BGS_119"],
        clear=True)
    assert counts == {"board": 2, "hand": 1, "tavern": 1}
    assert [m.card_id for m in target.board] == ["BG25_001", "BGS_119"]
    assert target.board[1].atk == 5 and target.board[1].health == 7
    assert target.board[1].has(GameTag.TAUNT)
    assert len(target.hand) == 1 and len(target.tavern) == 1
    assert dg(dup) != before
    # 原地是副本，原局不受影响
    assert len(game.heroes[1].hand) == 0


def test_clone_and_digest_performance_smoke():
    """宽松性能冒烟（CI/共享机器噪声大，仅防数量级退化）。"""
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=48)
    env.reset(seed=48)
    game = env.game
    times = []
    for _ in range(15):
        t0 = time.perf_counter()
        model.clone(game)
        times.append((time.perf_counter() - t0) * 1000.0)
    times.sort()
    assert times[len(times) // 2] < 10.0, times
    from hsbg.planning.digest import digest as dg
    t0 = time.perf_counter()
    for _ in range(50):
        dg(game)
    assert (time.perf_counter() - t0) / 50 * 1000.0 < 5.0
    env.close()

def test_simulate_turn_combat_fast_forward():
    """快速 forward：只战斗裁决、无副作用、可复现、value 可用。"""
    from hsbg.planning.digest import digest as dg
    env = BattlegroundsEnv(num_players=8, opponent="heuristic", seed=49)
    env.reset(seed=49)
    _play_heuristic_turns(env, 3)
    game = env.game
    hero = game.heroes[0]
    before = dg(game)
    summary1, dup1 = model.simulate_turn_combat(game, hero,
                                                keep_state=True)
    summary2, dup2 = model.simulate_turn_combat(game, hero,
                                                keep_state=False)
    assert dg(game) == before, "simulate_turn_combat 修改了原 game"
    assert dup1 is not None and dup1 is not game
    assert dup2 is None
    for key in ("winner", "capped_damage", "value", "winner_is_hero",
                "hero_alive_after"):
        assert key in summary1, key
    assert -1.0 <= summary1["value"] <= 1.0
    assert summary1["winner"] == summary2["winner"]
    assert summary1["capped_damage"] == summary2["capped_damage"]
    env.close()
