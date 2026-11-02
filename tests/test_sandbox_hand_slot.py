"""``--sandbox-hand-slot-mode {strict,swap}`` 契约测试。

语义（见 ``docs/SANDBOX_ECON.md`` §4）：

- ``strict``（**默认**）：只用引擎 ``legal_mask``；棋盘 7 + 手牌 10 都满时买牌被掩掉，
  输出/动作流与改动前**逐位一致**（不新增任何度量键）。
- ``swap``：买牌被「位置」卡死、但商店里有买得起的牌时，允许**一个决策**完成
  「卖最弱非核心 → 打出一张手牌随从腾手牌位 → 买」；只卖非载体/非核心牌，
  与 ``scripts/compound_script.py`` 规则 7 同源。

测试用「99 金 + 大 action-cap」把一个沙盒推到「7 棋盘 + 10 手牌」的满场状态，
再对照两种模式的 mask / 动作 / 度量。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

pytest.importorskip("hsbg_engine")

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    A_BUY, A_SELL, END_TURN, N_BOARD, N_HAND, EconomySandbox, SandboxConfig)

#: Play 动作段（手牌槽 × 位置）
A_PLAY = 46


def _cfg(**kw):
    base = dict(turns=6, gold_per_turn=99, action_cap=400, trinkets=False)
    base.update(kw)
    return SandboxConfig(**base)


def _player(env):
    return json.loads(env.g.player_json(0))


def _fill(env, max_steps: int = 8000):
    """把沙盒推到「棋盘 7 + 手牌 10 且商店非空」的满场状态。"""
    obs = env.reset(11)
    for _ in range(max_steps):
        if env.done:
            break
        p = _player(env)
        board, hand = p.get("board") or [], p.get("hand") or []
        shop = [it for it in (p.get("shop") or [])[:8] if it and it.get("item")]
        if len(board) >= N_BOARD and len(hand) >= N_HAND and shop:
            return obs
        m = obs.mask
        hand_minions = [i for i, it in enumerate(hand[:10])
                        if isinstance(it, dict) and "Minion" in (it.get("item") or {})]
        a = None
        if len(board) < N_BOARD:                       # 先把随从铺到 7
            for h in hand_minions:
                for pos in range(N_BOARD):
                    act = A_PLAY + h * 8 + pos
                    if act < 126 and m[act]:
                        a = act
                        break
                if a is not None:
                    break
        if a is None and len(board) >= N_BOARD and len(hand) >= N_HAND and m[1]:
            a = 1                                      # 满场：刷新酒馆，保证有牌可买
        if a is None:
            buys = [x for x in range(A_BUY, A_BUY + 8) if m[x]]
            if buys:
                a = buys[0]
        if a is None and m[1]:
            a = 1
        if a is None and m[END_TURN]:
            a = END_TURN
        if a is None:
            a = int(np.flatnonzero(m)[0])
        obs, _r, _d, _info = env.step(a)
    return obs


def test_default_mode_is_strict():
    """默认 ``strict``：不改默认行为，默认配置不新增度量键。"""
    assert SandboxConfig().hand_slot_mode == "strict"
    env = EconomySandbox(_cfg())
    _fill(env)
    ep = env.episode_summary()
    assert "hand_swaps" not in ep and "hand_slot_mode" not in ep


def test_validate_rejects_bad_mode():
    with pytest.raises(ValueError):
        _cfg(hand_slot_mode="shuffle").validate()


def test_strict_full_hand_masks_buys():
    """strict：满场（7+10）时引擎与沙盒 mask 都不给买牌。"""
    env = EconomySandbox(_cfg())
    obs = _fill(env)
    eng = env._mask(env.g, 0)
    assert not bool(eng[A_BUY:A_BUY + 8].any())
    assert not bool(obs.mask[A_BUY:A_BUY + 8].any())


def test_swap_augments_buys_and_picks_weakest_noncore():
    """swap：同样满场，mask 里出现买牌；victim = 非核心中 atk+hp 最小的棋盘随从。"""
    env = EconomySandbox(_cfg(hand_slot_mode="swap"))
    obs = _fill(env)
    eng = env._mask(env.g, 0)
    assert not bool(eng[A_BUY:A_BUY + 8].any())        # 引擎仍然认为买不了
    aug = [A_BUY + i for i in range(8) if obs.mask[A_BUY + i]]
    assert aug, "swap 模式应在满场时把可换位的买牌加回 mask"

    plan = env._swap_plan(eng)
    assert plan is not None
    victim_slot, play, buys = plan
    assert A_BUY + buys[0] in aug and play >= A_PLAY and play < 126
    # victim 必须是「非载体、非核心」里 atk+hp 最小的
    cid2id = env._cid_to_id_map()
    board = _player(env).get("board") or []
    scores = []
    for i, m in enumerate(board):
        cid = cid2id.get(int(m.get("card") or -1), "")
        if cid in env._carriers or (env._core is not None and cid in env._core):
            continue
        scores.append((int(m.get("atk") or 0) + int(m.get("hp") or 0), i))
    assert scores and victim_slot == min(scores)[1]


def test_swap_step_executes_and_frees_hand_slot():
    """swap：执行一次被加回的买牌 = 卖非核心 + 打出手中随从 + 买，只记 1 次换位。"""
    env = EconomySandbox(_cfg(hand_slot_mode="swap"))
    obs = _fill(env)
    before = _player(env)
    hand_before = len(before.get("hand") or [])
    board_before = len(before.get("board") or [])
    bought_before = int((before.get("stats") or {}).get("minions_bought") or 0)
    aug = [A_BUY + i for i in range(8) if obs.mask[A_BUY + i]]
    assert aug
    obs2, _r, done, info = env.step(aug[0])
    assert not done
    p = _player(env)
    assert env._hand_swaps == 1
    assert "swap_sold" in info and "swap_play" in info
    assert len(p.get("board") or []) <= N_BOARD
    assert len(p.get("hand") or []) <= N_HAND
    assert int((p.get("stats") or {}).get("minions_bought") or 0) > bought_before
    # 手牌位确实腾出来了：换位后手牌数 ≤ 换位前（买一张 +1，但打出一张 −1）
    assert len(p.get("hand") or []) <= hand_before
    # mask 仍是合法动作空间（每一步都能 step）
    assert obs2.mask.shape == (245,)
    assert bool(obs2.mask.any())
    ep = env.episode_summary()
    assert ep.get("hand_slot_mode") == "swap"
    assert ep.get("hand_swaps") == 1


def test_strict_full_state_can_still_finish_episode():
    """strict 在满场状态下也能正常跑完（swap 的默认关闭不破坏基线）。"""
    env = EconomySandbox(_cfg())
    obs = _fill(env)
    while not env.done:
        obs, _r, _d, info = env.step(int(np.flatnonzero(obs.mask)[0]))
    assert env.episode_summary()["turns"] == 6
