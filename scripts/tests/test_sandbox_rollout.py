"""rollout 叶评估搜索（``hsbg/az/train/sandbox_rollout.py``）的契约测试。

四条契约（否则 v2 标签会静默失真）：

1. **叶值 = 回合末真实 Σ**：rollout 的 ``sigma_end`` 必须与「同一条 greedy 策略
   手动滚到 EndTurn」得到的回合末 Σ 逐项相等；
2. **π 只落在候选上**（合法、非 Move、≤top-k），和 = 1，确定性可复现；
3. **search_when** 的每个原子标签都能从观测事实正确判定（与 ``view(0)`` 对账）；
4. **DAgger 语义**：``base`` = π_base top-1，``best`` = argmax Q，二者与
   ``sigma_end`` 对齐（可以直接算「搜索动作 vs 策略动作的回合末 Σ 差」）。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from hsbg.az.train.economy_sandbox import (END_TURN, N_ACTIONS, EconomySandbox,
                                           SandboxConfig, stack_obs)
from hsbg.az.train.sandbox_rollout import (MOVE_HI, MOVE_LO, CARD_HAND,
                                           CARD_SHOP, RolloutConfig,
                                           RolloutSearcher, card_tables,
                                           pi_from_q, root_candidates,
                                           search_when_names, sigmas_from_features,
                                           tag_matches)

pytest.importorskip("hsbg_engine")


# ── 测试用确定性策略（不依赖网络）──────────────────────────────────────────


def _uniform_policy(feats, cards, masks):
    """合法动作均匀先验（非 Move 优先），value 恒 0。"""
    masks = np.asarray(masks, dtype=bool)
    n = len(masks)
    prior = np.zeros((n, N_ACTIONS), dtype=np.float32)
    for i in range(n):
        legal = np.flatnonzero(masks[i])
        pool = legal[(legal < MOVE_LO) | (legal >= MOVE_HI)]
        if pool.size == 0:
            pool = legal
        w = np.zeros(pool.size, dtype=np.float64)
        # 确定性权重：动作下标越大越优先（便于复现），EndTurn 最低
        w = 1.0 + np.asarray(pool, dtype=np.float64) / max(1.0, float(N_ACTIONS))
        w[np.asarray(pool) == END_TURN] = 0.05
        prior[i, pool] = (w / w.sum()).astype(np.float32)
    return prior, np.zeros(n, dtype=np.float32)


def _env(turn_walk: int = 0, gold: int = 10, seed: int = 910000):
    env = EconomySandbox(SandboxConfig(gold_per_turn=int(gold)))
    obs = env.reset(seed=int(seed))
    for _ in range(int(turn_walk)):
        if env.done:
            break
        obs = env.obs()
        legal = np.flatnonzero(obs.mask)
        # 走到回合中段的一个普通决策点
        a = int(legal[0])
        env.step(a)
    return env, env.obs()


def _manual_turn_end(env, cand: int, prior_fn, seed: int = 0) -> int:
    """参考实现：执行 cand 后按 greedy 滚到本回合末，返回回合末 Σ。"""
    e = env.clone()
    root_turn = int(e.obs().turn)
    e.search_step(int(cand))
    if bool(e.g.is_over()) or int(e.obs().turn) != root_turn:
        return int(sigmas_from_features(env.obs().features[None, :])[0])
    obs = e.obs()
    for _ in range(256):
        f, c, m = stack_obs([obs])
        p, _v = prior_fn(f, c, m)
        a = int(np.argmax(p[0]))
        pre = int(sigmas_from_features(obs.features[None, :])[0])
        adv = bool(e.search_step(a))
        if adv or bool(e.g.is_over()):
            return pre
        obs = e.obs()
    raise AssertionError("参考 rollout 没有在 256 步内结束回合")


# ── 1. 叶值 = 回合末真实 Σ ─────────────────────────────────────────────────


def test_leaf_equals_turn_end_sigma():
    env, obs = _env(turn_walk=0)
    cfg = RolloutConfig(topk=3, turns=1, rollout_mode="greedy", max_steps=256)
    sr = RolloutSearcher(cfg=cfg, policy_fn=_uniform_policy)
    f, c, m = stack_obs([obs])
    prior, _v = sr.policy(f, c, m)
    res = sr.search([env], f, c, m, prior)[0]
    assert len(res.cands) >= 2
    for j, a in enumerate(res.cands.tolist()):
        ref = _manual_turn_end(env, int(a), _uniform_policy)
        assert int(res.sigma_end[j]) == int(ref), (
            f"候选 {a}: 搜索叶值 {int(res.sigma_end[j])} != 参考回合末 Σ {ref}")
        # 叶分 = L(Σ)（无 bonus）
        from hsbg.az.train.sandbox_rollout import _L
        assert abs(float(res.q[j]) - _L(ref)) < 1e-9
    # base / best 对齐
    base_j = int(np.flatnonzero(res.cands == res.base)[0])
    assert int(res.sigma_base) == int(res.sigma_end[base_j])
    best_j = int(np.argmax(res.q))
    assert int(res.best) == int(res.cands[best_j])
    assert int(res.sigma_best) == int(res.sigma_end[best_j])


def test_leaf_turn_end_can_be_later_turn():
    """turns=2 的叶值仍等于「第 2 个回合末」的真实 Σ（而不是第 1 个）。"""
    env, obs = _env(turn_walk=0, gold=10)
    cfg = RolloutConfig(topk=2, turns=2, rollout_mode="greedy", max_steps=512)
    sr = RolloutSearcher(cfg=cfg, policy_fn=_uniform_policy)
    f, c, m = stack_obs([obs])
    prior, _v = sr.policy(f, c, m)
    res = sr.search([env], f, c, m, prior)[0]
    root_turn = int(obs.turn)

    # 参考：执行候选后滚到 target_turn 末（= root_turn + 1）
    def ref(cand):
        e = env.clone()
        e.search_step(int(cand))
        target = root_turn + 1
        obs2 = e.obs()
        for _ in range(1024):
            p, _v = _uniform_policy(*stack_obs([obs2]))
            a = int(np.argmax(p[0]))
            pre = int(sigmas_from_features(obs2.features[None, :])[0])
            t = int(obs2.turn)
            adv = bool(e.search_step(a))
            if adv or bool(e.g.is_over()):
                if t >= target or bool(e.g.is_over()):
                    return pre
                obs2 = e.obs()
                continue
            obs2 = e.obs()
        raise AssertionError("参考 2 回合 rollout 未结束")

    for j, a in enumerate(res.cands.tolist()[:2]):
        assert int(res.sigma_end[j]) == int(ref(int(a))), f"turns=2 候选 {a} 叶值不符"


# ── 2. π 契约 ───────────────────────────────────────────────────────────────


def test_pi_support_and_determinism():
    env, obs = _env(turn_walk=0)
    cfg = RolloutConfig(topk=4, turns=1)
    sr = RolloutSearcher(cfg=cfg, policy_fn=_uniform_policy)
    f, c, m = stack_obs([obs])
    prior, _v = sr.policy(f, c, m)
    f2, c2, m2 = stack_obs([obs])
    r1 = sr.search([env], f, c, m, prior)[0]
    r2 = sr.search([env], f2, c2, m2, prior)[0]
    assert np.array_equal(r1.pi, r2.pi)
    assert np.array_equal(r1.q, r2.q)
    assert np.array_equal(r1.sigma_end, r2.sigma_end)
    s = float(r1.pi.sum())
    assert abs(s - 1.0) < 1e-5
    supp = np.flatnonzero(r1.pi > 0)
    assert set(int(x) for x in supp) <= set(int(x) for x in r1.cands)
    assert bool(np.all(m[0][supp])), "π 必须落在合法动作上"
    assert bool(np.all((supp < MOVE_LO) | (supp >= MOVE_HI))), "π 不能落在 Move"
    assert supp.size <= 4
    # top-1 概率质量在 (0,1]
    assert 0.0 < float(r1.pi.max()) <= 1.0 + 1e-6


def test_pi_from_q_favours_higher_q_and_keeps_prior_support():
    prior = np.zeros(N_ACTIONS, dtype=np.float32)
    cands = np.asarray([10, 20, 30], dtype=np.int64)
    prior[cands] = [0.6, 0.3, 0.1]
    q = np.asarray([0.10, 0.20, 0.15])
    cfg = RolloutConfig(q_temp=0.01, pi_mode="advantage")
    pi, tau, V = pi_from_q(prior, cands, q, cfg)
    assert abs(float(pi.sum()) - 1.0) < 1e-5
    assert int(np.argmax(pi)) == 20, "Q 最高的动作应拿到最多质量"
    assert abs(tau - 0.01) < 1e-9
    assert abs(V - (0.6 * 0.10 + 0.3 * 0.20 + 0.1 * 0.15)) < 1e-9
    # 自适应温度：Q 全相等 => π = 先验
    pi2, _t2, _v2 = pi_from_q(prior, cands, np.full(3, 0.3), RolloutConfig())
    assert np.allclose(pi2[cands], prior[cands] / prior[cands].sum(), atol=1e-6)


def test_root_candidates_topk_and_base():
    mask = np.zeros(N_ACTIONS, dtype=bool)
    mask[[0, 8, 9, 46, 47, 48, 196, 197]] = True
    prior = np.zeros(N_ACTIONS, dtype=np.float32)
    prior[[0, 8, 9, 46, 47, 48, 196, 197]] = [0.05, 0.1, 0.5, 0.2, 0.1, 0.03, 0.01, 0.01]
    cands = root_candidates(mask, prior, 3)
    assert int(cands[0]) == 9, "候选按先验降序，第一位 = π_base top-1"
    assert 196 not in set(int(x) for x in cands), "默认剔除 Move"
    assert len(cands) == 3


# ── 3. search_when 判定 ────────────────────────────────────────────────────


def test_search_when_names_aliases():
    assert search_when_names("any") == ("any",)
    names = search_when_names("carrier_or_spell")
    assert set(names) == {"carrier_in_shop", "carrier_in_hand", "spell_in_hand"}
    assert set(search_when_names("tier4plus,carrier_in_shop")) == {"tier4plus",
                                                                  "carrier_in_shop"}
    with pytest.raises(ValueError):
        search_when_names("nope")


def test_tags_match_against_view():
    """观测解码的 tier / Σ / 载体 / 法术必须与引擎 view(0) 对账。"""
    env, obs = _env(turn_walk=3, gold=10)
    sr = RolloutSearcher(cfg=RolloutConfig(), policy_fn=_uniform_policy)
    tags = sr.tags(obs.features, obs.cards)
    v = json.loads(env.g.view(0))
    me = v.get("me") or {}
    board = me.get("board") or []
    sigma = sum(int(m.get("atk") or 0) + int(m.get("hp") or 0) for m in board)
    assert int(tags.sigma) == int(sigma) >= 0
    assert int(tags.tier) == int(me.get("tier") or 0)

    tab = card_tables()
    carriers = set(__import__("hsbg.az.train.economy_sandbox", fromlist=["x"])
                   .carrier_ids())
    want_board = sum(1 for m in board if str(m.get("id")) in carriers)
    assert int(tags.carriers_board) == want_board
    hand_ids = [str(m.get("id")) for m in (me.get("hand") or [])]
    shop_ids = [str(m.get("id")) for m in (me.get("shop") or [])]
    assert int(tags.carrier_in_shop) == sum(1 for x in shop_ids if x in carriers)
    assert int(tags.carrier_in_hand) == sum(1 for x in hand_ids if x in carriers)
    # 手牌法术（酒馆法术 / 普通法术）
    want_spells = sum(1 for x in hand_ids
                      if tab["id2kind"].get(x) in ("tavern_spell", "spell"))
    assert int(tags.spell_in_hand) == want_spells
    # 卡牌块下标自检（避免布局漂移）
    assert CARD_HAND.start == 26 and CARD_SHOP.start == 36


def test_should_search_budget_and_tags():
    from hsbg.az.train.sandbox_rollout import DecisionTags
    sr = RolloutSearcher(cfg=RolloutConfig(search_when="carrier_or_spell",
                                           max_searches_per_turn=1),
                         policy_fn=_uniform_policy)
    tags = DecisionTags(carrier_in_shop=1)
    assert sr.should_search(tags, searched_this_turn=0)
    assert not sr.should_search(tags, searched_this_turn=1), "每回合预算生效"
    assert not sr.should_search(DecisionTags(carrier_in_shop=0), searched_this_turn=0)
    assert sr.should_search(DecisionTags(spell_in_hand=1), searched_this_turn=0)
    any_sr = RolloutSearcher(cfg=RolloutConfig(search_when="any",
                                              max_searches_per_turn=0),
                             policy_fn=_uniform_policy)
    assert any_sr.should_search(DecisionTags(), searched_this_turn=99)
    tier_sr = RolloutSearcher(cfg=RolloutConfig(search_when="tier4plus"),
                              policy_fn=_uniform_policy)
    assert tier_sr.should_search(DecisionTags(tier=4), searched_this_turn=0)
    assert not tier_sr.should_search(DecisionTags(tier=3), searched_this_turn=0)
    for name in ("carrier_in_shop", "carrier_in_hand", "spell_in_hand",
                 "carrier_on_board", "tier4plus"):
        assert tag_matches(DecisionTags(carrier_in_shop=1, carrier_in_hand=1,
                                        spell_in_hand=1, carriers_board=1, tier=5),
                           (name,)), name
