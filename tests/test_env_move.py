"""``tests/test_env_move.py`` —— v3 棋盘重排动作（``ActionKind.MOVE_MINION``）。

覆盖：
- spec：``move_minion`` 注册在 ActionKind **末尾**（既有 12 类索引不变）、
  ``Observation.version`` 升为 3；
- driver：相邻交换候选枚举（槽位/position 正确、签名唯一、空/单随从不生成）；
- apply：任意目标槽位移动、board 顺序 + ``ZONE_POSITION`` 同步、金币/实体集合
  不变、不 fire 事件/不触发 on_summon；非法动作（越界/同槽/不在棋盘）被拒；
- env：``CandidateAction(kind="move_minion")`` 经 ``env.step`` 生效，观测
  board 顺序随之变化，``stats["move_minion_candidates"]`` 计数；
- 完整性：只用相邻交换即可把棋盘反转为任意排列（多次动作可达）；
- 候选上限：满场 7 随从时重排候选仍全部在 ``CANDIDATE_MAX`` 内且不丢。
"""

from __future__ import annotations

import pytest

from hsrl2.tags import GameTag

from tests.test_env_support import (
    VANILLA_MINION,
    add_minion_to_board,
    make_engine_game,
)

from hsbg.env import BattlegroundsEnv, driver, observation
from hsbg.env.spec import (
    ACTION_KIND_INDEX,
    CANDIDATE_MAX,
    NUM_ACTION_KINDS,
    ActionKind,
    CandidateAction,
)

MOVE = ActionKind.MOVE_MINION.value


# ══════════════════════════════════════════════════════════════════════
# spec 契约
# ══════════════════════════════════════════════════════════════════════


def test_move_kind_registered_at_end_and_old_indices_stable():
    assert NUM_ACTION_KINDS == 13
    assert ACTION_KIND_INDEX[MOVE] == 12                # 追加在末尾
    old = ("buy", "sell", "play_minion", "play_spell", "reroll", "upgrade",
           "freeze", "hero_power", "activate", "use_dark_gift", "end_turn",
           "choose")
    for i, kind in enumerate(old):
        assert ACTION_KIND_INDEX[kind] == i, f"{kind} 索引被改动"
    assert observation.ENTITY_TOKEN_VERSION == 3


def test_candidate_signature_includes_position():
    a = CandidateAction(kind=MOVE, src_zone="board", src_slot=0, position=1)
    b = CandidateAction(kind=MOVE, src_zone="board", src_slot=0, position=2)
    assert a.signature() != b.signature()
    assert a.kind_index == ACTION_KIND_INDEX[MOVE]


# ══════════════════════════════════════════════════════════════════════
# driver：枚举 / apply
# ══════════════════════════════════════════════════════════════════════


def _game_with_board(n: int, seed: int = 81):
    game, heroes = make_engine_game(seed=seed)
    hero = heroes[0]
    minions = [add_minion_to_board(game, hero, VANILLA_MINION)
               for _ in range(n)]
    return game, hero, minions


def _moves(game, hero):
    return [d for d in driver.enumerate_actions(game, hero)
            if d.kind == MOVE]


def test_move_candidates_enumerated_adjacent_only():
    game, hero, minions = _game_with_board(3)
    moves = _moves(game, hero)
    assert len(moves) == 2, "3 随从应生成 n-1=2 个相邻交换候选"
    assert {int(d.position) for d in moves} == {1, 2}
    for d, slot in zip(moves, (0, 1)):
        assert d.src_entity is minions[slot]
        assert d.src_zone == "board"
        assert d.src_slot == slot
        assert d.tgt_entity is None
        cand = d.to_candidate()
        assert cand.kind == MOVE
        assert (cand.src_zone, cand.src_slot) == ("board", slot)
        assert cand.position == slot + 1
        assert cand.cost == 0
    # 候选签名唯一（策略按签名比对动作）
    sigs = [d.signature() for d in moves]
    assert len(sigs) == len(set(sigs))


def test_move_not_enumerated_for_empty_or_single_board():
    game, hero, _ = _game_with_board(0)
    assert _moves(game, hero) == []
    game2, hero2, _ = _game_with_board(1)
    assert _moves(game2, hero2) == []


def test_move_apply_swaps_board_and_updates_positions():
    game, hero, minions = _game_with_board(3)
    gold0 = hero.gold
    d = _moves(game, hero)[0]                            # src slot0 → 1
    res = driver.apply_action(game, hero, d)
    assert res.success, res.error
    assert hero.board == [minions[1], minions[0], minions[2]]
    assert [m.get(GameTag.ZONE_POSITION) for m in hero.board] == [0, 1, 2]
    assert hero.gold == gold0                            # 重排免费
    assert len(hero.board) == 3                          # 不增不减
    assert not game.pending_choices                      # 不产生选择


def test_move_apply_supports_arbitrary_destination():
    """枚举只给相邻交换，但 apply 本身支持任意目标槽位（未来放宽枚举）。"""
    game, hero, minions = _game_with_board(3)
    desc = driver.ActionDescriptor(
        kind=MOVE, src_entity=minions[0], position=2)
    res = driver.apply_action(game, hero, desc)
    assert res.success, res.error
    assert hero.board == [minions[1], minions[2], minions[0]]
    assert [m.get(GameTag.ZONE_POSITION) for m in hero.board] == [0, 1, 2]


def test_move_does_not_fire_summon_or_play_events():
    """重排只改顺序：不触发 summon/card_played，不消耗 RNG。"""
    game, hero, minions = _game_with_board(2)
    fired = []
    from hsrl2.events import Listener

    for event in ("summon", "card_played", "minion_played"):
        game.events.register(Listener(
            event=event, owner=hero,
            callback=lambda g, event=event, **kw: fired.append(event)))
    rng_before = len(game.rng.decisions)
    hand_before = [e.card_id for e in hero.hand]
    d = _moves(game, hero)[0]
    assert driver.apply_action(game, hero, d).success
    assert fired == []
    assert len(game.rng.decisions) == rng_before
    assert [e.card_id for e in hero.hand] == hand_before


@pytest.mark.parametrize("position", [-1, 3, 99, "bad"])
def test_move_invalid_position_rejected(position):
    game, hero, minions = _game_with_board(3)
    desc = driver.ActionDescriptor(
        kind=MOVE, src_entity=minions[0], position=position)
    res = driver.apply_action(game, hero, desc)
    assert not res.success
    assert res.error_type == "GameStateError"
    # 状态未被改动
    assert hero.board == minions


def test_move_same_position_rejected():
    game, hero, minions = _game_with_board(3)
    desc = driver.ActionDescriptor(
        kind=MOVE, src_entity=minions[0], position=0)
    res = driver.apply_action(game, hero, desc)
    assert not res.success
    assert res.error_type == "GameStateError"


def test_move_src_not_on_board_rejected():
    game, hero, minions = _game_with_board(3)
    from tests.test_env_support import add_minion_to_hand
    in_hand = add_minion_to_hand(game, hero, VANILLA_MINION)
    desc = driver.ActionDescriptor(kind=MOVE, src_entity=in_hand, position=1)
    res = driver.apply_action(game, hero, desc)
    assert not res.success
    assert res.error_type == "GameStateError"
    assert hero.board == minions


def test_adjacent_swaps_can_reverse_board():
    """相邻交换的**可达性**：多次动作可达成任意排列（这里验证反转）。"""
    game, hero, minions = _game_with_board(4)
    desired = list(reversed(minions))

    def swap(i: int) -> None:
        moves = _moves(game, hero)
        match = [d for d in moves
                 if d.src_entity is hero.board[i] and d.position == i + 1]
        assert match, f"no swap candidate at {i}: {[d.note for d in moves]}"
        assert driver.apply_action(game, hero, match[0]).success

    for target_idx in range(4):
        while hero.board[target_idx] is not desired[target_idx]:
            # 把 desired[target_idx] 逐步左移到 target_idx
            cur = hero.board.index(desired[target_idx])
            assert cur > target_idx
            swap(cur - 1)
    assert hero.board == desired
    assert [m.get(GameTag.ZONE_POSITION) for m in hero.board] == [0, 1, 2, 3]


# ══════════════════════════════════════════════════════════════════════
# env：候选 + step + 观测
# ══════════════════════════════════════════════════════════════════════


def _env_with_board(n: int = 3, seed: int = 91):
    env = BattlegroundsEnv(seed=seed)
    obs = env.reset(seed=seed)
    # 清掉开局 on_bind 选择（不阻塞招募期观测）
    driver.resolve_pending_choices(env.game, None)
    for _ in range(n):
        add_minion_to_board(env.game, env.agent_hero, VANILLA_MINION)
    obs = env._observe()
    return env, obs


def test_env_step_move_minion_changes_observation_order():
    env, obs = _env_with_board(3)
    agent = env.agent_hero
    before = [m.card_id for m in agent.board]
    move_cands = [c for c in obs.candidates if c.kind == MOVE]
    assert len(move_cands) == 2
    cand = move_cands[0]                                  # src board[0] → 1
    assert (cand.src_zone, cand.src_slot, cand.position) == ("board", 0, 1)

    obs2, _reward, term, trunc, info = env.step(cand)
    assert not term and not trunc
    assert info["invalid"] is False, info
    assert [m.card_id for m in agent.board] == [before[1], before[0], before[2]]
    assert [t.card_id for t in obs2.board] == [before[1], before[0], before[2]]
    assert [(t.slot) for t in obs2.board] == [0, 1, 2]
    # 换位后仍可继续换位（候选随新顺序重建）
    assert any(c.kind == MOVE for c in obs2.candidates)
    assert env.stats["move_minion_candidates"] > 0
    env.close()


def test_env_move_candidate_not_confused_with_play_position():
    """play_minion 的 position（插入位置）与 move 的 position（目标槽位）
    是不同动作语义，签名/kinds 必须可区分。"""
    env, obs = _env_with_board(2)
    kinds = {c.kind for c in obs.candidates}
    assert MOVE in kinds
    assert any(c.kind == ActionKind.SELL.value for c in obs.candidates)
    move = next(c for c in obs.candidates if c.kind == MOVE)
    assert move.tgt_zone == ""
    assert move.position == 1
    env.close()


def test_move_candidates_respect_candidate_max_on_full_board():
    env = BattlegroundsEnv(seed=92)
    env.reset(seed=92)
    driver.resolve_pending_choices(env.game, None)
    hero = env.agent_hero
    for _ in range(7):
        add_minion_to_board(env.game, hero, VANILLA_MINION)
    from tests.test_env_support import add_minion_to_hand
    for _ in range(10):
        add_minion_to_hand(env.game, hero, VANILLA_MINION)
    descs = driver.enumerate_actions(env.game, hero)
    assert len(descs) <= CANDIDATE_MAX
    move_descs = [d for d in descs if d.kind == MOVE]
    assert len(move_descs) == 6, "满场 7 随从应有 6 个相邻交换候选"
    assert any(d.kind == ActionKind.END_TURN.value for d in descs)
    env.close()
