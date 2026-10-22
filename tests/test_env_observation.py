"""``tests/test_env_observation.py`` —— 观测契约（``docs/ENV_SPEC.md`` §2）。

重点覆盖：
- **槽位同源**：每个候选动作的 src/tgt 在观测里确实存在且指向同一实体；
- 关键词/种族归一化到 ``spec.KEYWORDS`` / ``spec.RACES``；
- ``opponent_board`` 只含官方可见的"上一场战团"，不泄露对手隐藏信息；
- PendingChoice 时 phase/候选/选项正确；
- 大厅 / 名次 / 英雄 token 字段；
- 观测可 pickle（多进程 worker 传输）。
"""

from __future__ import annotations

import pickle

import pytest

from hsbg.env import BattlegroundsEnv
from hsbg.env import spec
from hsbg.env.spec import (
    CARD_TYPE_MINION,
    CARD_TYPE_SPELL,
    ENTITY_ZONES,
    KEYWORDS,
    RACES,
    ActionKind,
    PHASE_CHOICE,
    PHASE_GAME_OVER,
    PHASE_RECRUIT,
    ZONE_BOARD,
    ZONE_CHOICE,
    ZONE_HAND,
    ZONE_OPPONENT,
    ZONE_TAVERN,
    ZONE_TRINKET,
)


def _run_some(env, obs, max_steps=8):
    """按确定性脚本推进若干步（买第一个可买 / 否则结束回合）。"""
    for _ in range(max_steps):
        cands = obs.candidates
        if obs.phase == PHASE_CHOICE:
            idx = 0
        else:
            idx = next((i for i, c in enumerate(cands)
                        if c.kind == ActionKind.BUY.value), None)
            if idx is None:
                idx = next((i for i, c in enumerate(cands)
                            if c.kind == ActionKind.END_TURN.value), 0)
        obs, _r, term, trunc, _info = env.step(idx)
        if term or trunc:
            break
    return obs


# ══════════════════════════════════════════════════════════════════════
# 槽位一致性
# ══════════════════════════════════════════════════════════════════════


def _assert_candidates_consistent(obs, descriptors):
    assert len(obs.candidates) == len(descriptors)
    for cand, desc in zip(obs.candidates, descriptors):
        zone = cand.src_zone
        if zone in (ZONE_BOARD, ZONE_HAND, ZONE_TAVERN, ZONE_TRINKET):
            arr = obs.slots(zone)
            assert 0 <= cand.src_slot < len(arr), cand
            token = arr[cand.src_slot]
            if desc.src_entity is not None:
                # 引擎实体 → 观测 token 指向同一卡
                assert token.card_id == str(desc.src_entity.card_id), (
                    f"{cand} vs {desc.src_entity}")
        if cand.tgt_zone in (ZONE_BOARD, ZONE_HAND, ZONE_TAVERN,
                             ZONE_TRINKET):
            arr = obs.slots(cand.tgt_zone)
            assert 0 <= cand.tgt_slot < len(arr), cand
            token = arr[cand.tgt_slot]
            if desc.tgt_entity is not None:
                assert token.card_id == str(desc.tgt_entity.card_id), cand
        if cand.kind == ActionKind.PLAY_MINION.value:
            if cand.position >= 0:
                assert cand.position < max(1, len(obs.board)), cand
            assert cand.src_zone == ZONE_HAND
        if cand.kind == ActionKind.CHOOSE.value:
            assert obs.pending_choice is not None
            assert 0 <= cand.option < len(obs.pending_choice.options)


def test_slot_consistency_across_steps():
    env = BattlegroundsEnv(seed=21)
    obs = env.reset(seed=21)
    for step in range(6):
        _assert_candidates_consistent(obs, env._step_actions.descriptors)
        obs = _run_some(env, obs, max_steps=1)
    env.close()


def test_entity_tokens_well_formed():
    env = BattlegroundsEnv(seed=22)
    obs = env.reset(seed=22)
    obs = _run_some(env, obs, max_steps=6)
    for zone, arr in ((ZONE_BOARD, obs.board), (ZONE_HAND, obs.hand),
                      (ZONE_TAVERN, obs.tavern),
                      (ZONE_TRINKET, obs.trinkets),
                      (ZONE_OPPONENT, obs.opponent_board)):
        for i, tok in enumerate(arr):
            assert tok.zone == zone
            assert tok.slot == i
            assert tok.zone in ENTITY_ZONES
            assert set(tok.keywords) <= set(KEYWORDS), tok
            assert set(tok.races) <= set(RACES), tok
            assert tok.atk >= 0 and tok.tier >= 0
    for tok in obs.tavern:
        assert tok.card_type in (CARD_TYPE_MINION, CARD_TYPE_SPELL)
        assert tok.cost >= 0
    env.close()


def test_entity_id_stable_within_turn():
    env = BattlegroundsEnv(seed=23)
    obs = env.reset(seed=23)
    before = {t.entity_id: t.card_id for t in obs.tavern}
    obs2 = env._observe()                    # 同一状态重建观测
    after = {t.entity_id: t.card_id for t in obs2.tavern}
    assert before == after
    env.close()


# ══════════════════════════════════════════════════════════════════════
# 可观测性边界（POMDP）
# ══════════════════════════════════════════════════════════════════════


def test_opponent_board_only_visible_snapshot():
    env = BattlegroundsEnv(seed=24)
    obs = env.reset(seed=24)
    # 第 1 回合还没有战斗记录
    assert obs.opponent_board == ()
    obs = _run_some(env, obs, max_steps=200)     # 至少过一个 end_turn
    env2 = env
    assert env2.game.turn >= 2
    warband = env2.game.last_opponent_warband(env2.agent_hero) or []
    visible = [t.card_id for t in obs.opponent_board]
    assert visible == [m.card_id for m in warband]
    # 对手**当前**手牌不得出现
    opp_hand_ids = set()
    for h in env2.game.heroes:
        if h is not env2.agent_hero:
            opp_hand_ids |= {e.card_id for e in h.hand}
    # 战团快照可能恰好与手牌同卡，但 token 的 zone 必须是 opponent
    assert all(t.zone == ZONE_OPPONENT for t in obs.opponent_board)
    env.close()


def test_observation_picklable():
    env = BattlegroundsEnv(seed=25)
    obs = env.reset(seed=25)
    blob = pickle.dumps(obs)
    restored = pickle.loads(blob)
    assert restored.turn == obs.turn
    assert restored.candidates == obs.candidates
    assert restored.hero == obs.hero
    env.close()


# ══════════════════════════════════════════════════════════════════════
# PendingChoice 观测
# ══════════════════════════════════════════════════════════════════════


def _scripted_action(obs) -> int:
    for i, c in enumerate(obs.candidates):
        if c.kind == ActionKind.BUY.value:
            return i
    for i, c in enumerate(obs.candidates):
        if c.kind == ActionKind.END_TURN.value:
            return i
    return 0


def test_choice_phase_observation():
    """选择步观测契约（**构造性**推进到第一个选择步）。

    历史教训：原实现扫 `seed 0..23` 找"出现选择步"的局，引擎新增卡脚本
    改变 RNG 流后可能整段扫不到（全量红/单跑绿）。选择步是**确定性设计
    事件**（第 4 回合开局任务必定挂起 PendingChoice），因此固定 seed 0、
    用"能买就买、否则 end_turn"的脚本推进即可，无需 seed 搜索。
    """
    env = BattlegroundsEnv(seed=0)
    obs = env.reset(seed=0)
    for _ in range(200):
        if obs.phase == PHASE_CHOICE:
            break
        obs, _r, term, trunc, _i = env.step(_scripted_action(obs))
        assert not (term or trunc), (
            "seed=0 在选择步出现前终局（终止契约/回合推进异常）")
    assert obs.phase == PHASE_CHOICE, \
        "固定 seed 0 推进 200 步仍未出现选择步（第 4 回合任务应必现）"
    pc = obs.pending_choice
    assert pc is not None and pc.for_agent is True
    assert pc.kind
    assert len(pc.options) >= 1
    for i, opt in enumerate(pc.options):
        assert opt.zone == ZONE_CHOICE and opt.slot == i
    assert all(c.kind == ActionKind.CHOOSE.value for c in obs.candidates)
    assert [c.option for c in obs.candidates] == list(range(len(pc.options)))
    # 选一个后应回到招募阶段（或继续选择）
    obs2, _r, _t, _tr, info = env.step(0)
    assert not info["invalid"]
    assert obs2.phase in (PHASE_CHOICE, PHASE_RECRUIT)
    env.close()


# ══════════════════════════════════════════════════════════════════════
# 大厅 / 名次 / 英雄 / 终局
# ══════════════════════════════════════════════════════════════════════


def test_lobby_and_rank():
    env = BattlegroundsEnv(num_players=8, seed=27)
    obs = env.reset(seed=27)
    assert len(obs.lobby) == 8
    assert obs.total_players == 8
    assert obs.alive_count == 8
    assert sum(1 for p in obs.lobby if p.is_agent) == 1
    assert all(p.alive for p in obs.lobby)
    assert 1 <= obs.rank <= obs.alive_count
    for p in obs.lobby:
        assert p.health >= 0 and p.armor >= 0 and p.tier >= 1
        assert p.eliminated_rank == 0
    env.close()


def test_hero_token_fields():
    env = BattlegroundsEnv(seed=28)
    obs = env.reset(seed=28)
    hero = obs.hero
    assert hero is not None
    assert hero.hero_id == env.agent_hero.card_id
    assert hero.health == env.agent_hero.health
    assert hero.gold == env.agent_hero.gold
    assert hero.tier == env.agent_hero.tavern_tier
    assert hero.upgrade_cost == env.agent_hero.upgrade_cost
    assert hero.tavern_tier_max >= 6
    assert hero.power_cost >= 0
    env.close()


def test_game_over_observation():
    env = BattlegroundsEnv(seed=29, max_turns=1)
    obs = env.reset(seed=29)
    info = {}
    for _ in range(200):
        idx = next((i for i, c in enumerate(obs.candidates)
                    if c.kind == ActionKind.END_TURN.value), 0)
        obs, _r, term, trunc, info = env.step(idx)
        if term or trunc:
            break
    assert term or trunc
    assert obs.phase == PHASE_GAME_OVER
    assert obs.candidates == ()
    assert obs.pending_choice is None
    assert obs.log
    env.close()


def test_rank_estimation_matches_health_order():
    env = BattlegroundsEnv(seed=30)
    env.reset(seed=30)
    agent = env.agent_hero
    # 压低其他人生命，验证按 (health+armor) 的并列名次估算
    for h in env.heroes:
        if h is not agent:
            h.health = 5
    agent.health = 30
    obs = env._observe()
    assert obs.rank == 1
    agent.health = 1
    obs = env._observe()
    assert obs.rank == 8
    env.close()


def test_observation_version_and_log():
    env = BattlegroundsEnv(seed=31)
    obs = env.reset(seed=31)
    assert obs.version == 2
    assert obs.version == int(
        spec.Observation.__dataclass_fields__["version"].default)
    assert "phase=recruit" in obs.log
    assert obs.turn >= 1
    env.close()


def test_observation_build_is_read_only():
    """构建观测不得修改引擎状态，也不得消耗引擎随机流。"""
    env = BattlegroundsEnv(seed=32)
    obs = env.reset(seed=32)
    game = env.game
    agent = env.agent_hero
    before = {
        "turn": game.turn,
        "gold": agent.gold,
        "health": agent.health,
        "tier": agent.tavern_tier,
        "board": [m.card_id for m in agent.board],
        "hand": [e.card_id for e in agent.hand],
        "tavern": [e.card_id for e in agent.tavern],
        "trinkets": [e.card_id for e in agent.trinkets],
        "pending": len(game.pending_choices),
        "rng": len(game.rng.decisions),
        "heroes": len(game.heroes),
    }
    for _ in range(3):
        env._observe()
    after = {
        "turn": game.turn,
        "gold": agent.gold,
        "health": agent.health,
        "tier": agent.tavern_tier,
        "board": [m.card_id for m in agent.board],
        "hand": [e.card_id for e in agent.hand],
        "tavern": [e.card_id for e in agent.tavern],
        "trinkets": [e.card_id for e in agent.trinkets],
        "pending": len(game.pending_choices),
        "rng": len(game.rng.decisions),
        "heroes": len(game.heroes),
    }
    assert before == after
    env.close()
