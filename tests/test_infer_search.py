"""推理期搜索（``hsbg/az/train/infer_search.py``）的契约测试。

覆盖五件事（否则「评测侧接一层搜索」会静默失真）：

1. **enabled=0 是纯 pass-through**：与裸 base 策略逐动作一致（面板 A/B 的对照臂必须
   与历史评测口径逐位相同）；
2. **搜索不修改局面**：每条 rollout 都在 ``game.copy()`` 上；根 ``state_json`` 不变；
3. **叶值/π 契约**：``q == L(sigma_end)``、候选 ⊆ 合法非 Move、``pi`` 支撑 ⊆ 候选且
   和 = 1、EndTurn 候选的叶值 = 根状态 Σ、两次搜索逐位可复现；
4. **回合预算 + 回合守卫**：每回合最多 ``max_searches_per_turn`` 次；greedy rollout
   在病态先验下不会无限循环（``rollout_max_actions_per_turn`` 强制 EndTurn）；
5. **统计/轨迹**：``stats()`` 的 ``search_calls / search_ms_total / mean_ms_per_call``
   自洽，``game_rows()`` 带 ``sigma_by_turn``（t12/t15 强度比的数据源）。
"""

from __future__ import annotations

import numpy as np
import pytest

from hsbg.az.train.common import mask_from_bytes, obs_arrays
from hsbg.az.train.infer_search import (InferSearchConfig, InferSearchPolicy,
                                        InferSearcher, _Roll, leaf_score,
                                        leaf_value, trace_summary)
from hsbg.az.train.policies import Decision, Policy
from hsbg.az.train.sandbox_rollout import (FEAT_TIER, FEAT_TIER_SCALE, MOVE_HI,
                                           MOVE_LO, DecisionTags, pi_from_q,
                                           root_candidates, sigmas_from_features)

pytest.importorskip("hsbg_engine")

import hsbg_engine as E  # noqa: E402


# ── 测试替身 ────────────────────────────────────────────────────────────────
class _StubBase(Policy):
    """最简确定性策略：合法动作里取第一个（不依赖网络/GPU）。"""

    name = "stub"

    def __init__(self) -> None:
        self.calls = 0

    def reset(self) -> None:
        self.calls = 0

    def decide(self, game, seat: int) -> Decision:
        seat = int(seat)
        mask = mask_from_bytes(game.legal_mask(seat))
        self.calls += 1
        legal = np.flatnonzero(mask)
        a = int(legal[0]) if legal.size else 0
        pi = np.zeros(mask.size, dtype=np.float32)
        pi[a] = 1.0
        return Decision(a, pi, {"search": False, "policy": self.name})

    def act_batch(self, features, cards, mask, turn):  # pragma: no cover
        raise NotImplementedError


class _FakeEvaluator:
    """假叶评估器：``logits(f,c,m) -> (logits[n,245], rank_logits)``。

    ``avoid_endturn=True`` 时把 EndTurn 的 logit 压到 -50（专门用来测回合守卫，
    让 greedy rollout 不会一步就结束回合）。
    """

    def __init__(self, *, avoid_endturn: bool = False, target: int = -1) -> None:
        self.avoid_endturn = bool(avoid_endturn)
        self.target = int(target)
        self.calls = 0

    def logits(self, feats, cards=None, mask=None):
        m = np.atleast_2d(np.asarray(mask, dtype=bool))
        n = m.shape[0]
        self.calls += 1
        out = np.zeros((n, m.shape[1]), dtype=np.float32)
        for i in range(n):
            out[i, m[i]] = 0.0
            if self.avoid_endturn:
                out[i, 0] = -50.0
            if 0 <= self.target < out.shape[1]:
                out[i, self.target] += 5.0
            out[i, ~m[i]] = -1e9
        return out, np.zeros((n, 8), dtype=np.float32)


def _midgame(seed: int = 420000, min_turn: int = 5):
    """推进到「learner 需要动作」的中局（全部座位用引擎 bot）。"""
    g = E.Game(seed=int(seed))
    guard = 0
    while not g.is_over() and guard < 4000:
        guard += 1
        if int(g.turn) >= int(min_turn) and bool(g.needs_action(0)):
            return g
        acted = False
        for p in range(8):
            if bool(g.is_over()):
                break
            if bool(g.needs_action(p)):
                g.bot_play(p)
                acted = True
        if not acted:
            break
    pytest.skip(f"seed={seed} 在 turn>={min_turn} 找不到 learner 决策点")


def _searcher(**kw):
    """构造一个用假评估器的 searcher（``avoid_endturn``/``target`` 只给评估器）。"""
    ev_kw = {k: kw.pop(k) for k in list(kw) if k in ("avoid_endturn", "target")}
    cfg = InferSearchConfig(**kw)
    cfg.validate()
    return InferSearcher(_FakeEvaluator(**ev_kw), cfg)


# ── 1. pass-through ────────────────────────────────────────────────────────
def test_disabled_is_passthrough_identical_actions():
    """enabled=0 的包装层与裸 base 逐动作一致（含 8 座完整一局）。"""
    def _acts(wrap: bool):
        base = _StubBase()
        pol = (InferSearchPolicy(base, config=InferSearchConfig(enabled=0))
               if wrap else base)
        g = E.Game(seed=424242)
        pol.reset()
        out = []
        guard = 0
        while not g.is_over() and guard < 4000:
            guard += 1
            acted = False
            for p in range(8):
                if bool(g.is_over()):
                    break
                if not bool(g.needs_action(p)):
                    continue
                acted = True
                if int(p) == 0:
                    a = int(pol.decide(g, int(p)).action)
                    m = mask_from_bytes(g.legal_mask(0))
                    if not bool(m[a]):
                        nz = np.flatnonzero(m)
                        a = int(nz[0]) if nz.size else 0
                    out.append(a)
                    g.step(0, a)
                else:
                    g.bot_play(int(p))
            if not acted:
                break
        return out, (list(g.placements()) if g.is_over() else None)

    a0, r0 = _acts(False)
    a1, r1 = _acts(True)
    assert len(a0) >= 5, "一局的动作数应足够多（stub 几乎每回合直接 EndTurn）"
    assert a0 == a1, "enabled=0 必须逐动作等于裸 base 策略"
    assert r0 == r1


def test_disabled_records_trace_without_search():
    """enabled=0 也记录 Σ(turn) 轨迹（两臂强度口径一致），且不产生搜索。"""
    pol = InferSearchPolicy(_StubBase(), config=InferSearchConfig(enabled=0))
    g = _midgame()
    pol.reset()
    mask = mask_from_bytes(g.legal_mask(0))
    dec = pol.decide(g, 0)
    assert bool(mask[int(dec.action)])
    pol.flush()
    rows = pol.game_rows()
    assert len(rows) == 1
    assert rows[0]["sigma_by_turn"], "Σ(turn) 轨迹缺失"
    st = pol.stats()
    assert st["search_calls"] == 0 and st["mean_ms_per_call"] is None
    assert st["games"] == 1


# ── 2/3. 搜索本体契约 ──────────────────────────────────────────────────────
def test_search_contract_leaf_pi_and_no_mutation():
    g = _midgame(min_turn=5)
    s0 = g.state_json()
    sr = _searcher(enabled=1, turns=1, search_when="any", topk=6)
    mask = mask_from_bytes(g.legal_mask(0))
    f, c = obs_arrays(g.observe(0))
    prior = sr.prior_batch(f[None], c[None], mask[None])[0]
    out = sr.search(g, 0, prior=prior, mask=mask)
    assert out is not None
    # 局面未被修改
    assert g.state_json() == s0
    n = int(out.cands.size)
    assert 2 <= n <= 6
    # 候选 ⊆ 合法 且 非 Move 段
    assert np.all(mask[np.asarray(out.cands, dtype=int)])
    assert not np.any((out.cands >= MOVE_LO) & (out.cands < MOVE_HI))
    # pi 支撑 ⊆ 候选、和 = 1
    assert abs(float(out.pi.sum()) - 1.0) < 1e-5
    supp = set(np.flatnonzero(out.pi > 0).tolist())
    assert supp <= set(int(x) for x in out.cands)
    # q == L(sigma_end)
    for qv, sv in zip(out.q.tolist(), out.sigma_end.tolist()):
        assert abs(float(qv) - leaf_value(float(sv))) < 1e-12
    # base = 候选里先验最高、best = argmax Q
    assert int(out.base) == int(out.cands[int(np.argmax(prior[out.cands]))])
    assert int(out.best) == int(out.cands[int(np.argmax(out.q))])
    # EndTurn 候选的叶值 = 根状态 Σ（EndTurn 不改盘面）
    if 0 in out.cands.tolist():
        i = out.cands.tolist().index(0)
        assert int(out.sigma_end[i]) == int(out.sigma_root)
    # 确定性：再搜一次逐位相同
    out2 = sr.search(g, 0, prior=prior, mask=mask)
    assert out2 is not None
    assert np.array_equal(out.q, out2.q) and np.array_equal(out.sigma_end, out2.sigma_end)
    assert np.array_equal(out.cands, out2.cands)
    assert sr.calls == 2 and sr.ms_total > 0.0


def test_open_candidates_include_base_top1():
    g = _midgame(min_turn=6)
    sr = _searcher(enabled=1, search_when="any", topk=4)
    mask = mask_from_bytes(g.legal_mask(0))
    f, c = obs_arrays(g.observe(0))
    prior = sr.prior_batch(f[None], c[None], mask[None])
    cands = root_candidates(mask, prior[0], 4, skip_move=True)
    assert cands.size >= 1
    assert int(cands[0]) == int(np.argmax(np.where(mask, prior[0], -1.0)))


# ── 4. 预算 / 守卫 ─────────────────────────────────────────────────────────
def test_turn_budget_and_trigger():
    sr = _searcher(enabled=1, search_when="carrier_or_spell",
                   max_searches_per_turn=3)
    tags = DecisionTags(sigma=500, tier=5, carriers_board=1, carrier_in_shop=1,
                        carrier_in_hand=0, spell_in_hand=0)
    assert sr.should_search(tags, searched_this_turn=0)
    assert sr.should_search(tags, searched_this_turn=2)
    assert not sr.should_search(tags, searched_this_turn=3)
    off = DecisionTags(sigma=500, tier=5, carriers_board=1, carrier_in_shop=0,
                       carrier_in_hand=0, spell_in_hand=0)
    assert not sr.should_search(off, searched_this_turn=0)
    any_sr = _searcher(enabled=1, search_when="any", max_searches_per_turn=0)
    assert any_sr.should_search(off, searched_this_turn=99)
    tier_sr = _searcher(enabled=1, search_when="tier4plus",
                        max_searches_per_turn=3)
    assert tier_sr.should_search(off, searched_this_turn=0)
    low = DecisionTags(sigma=10, tier=3)
    assert not tier_sr.should_search(low, searched_this_turn=0)


def test_greedy_rollout_guard_terminates():
    """病态先验（永不选 EndTurn）下 rollout 仍会在回合守卫处收尾。"""
    g = _midgame(min_turn=5)
    cfg = InferSearchConfig(enabled=1, turns=1, search_when="any", topk=3,
                            rollout_max_actions_per_turn=6)
    sr = InferSearcher(_FakeEvaluator(avoid_endturn=True), cfg)
    out = sr.search(g, 0)
    assert out is not None
    # 每条候选最多 6 步 learner 动作 ⇒ 总步数 <= 3*6
    assert int(out.leaf_steps) <= 3 * 6
    assert int(out.truncated) == 0


def test_turns3_deeper_than_turns1():
    """turns=3 的 rollout 覆盖更长 horizon（同一局面 leaf_steps 应更多）。"""
    g = _midgame(min_turn=5)
    sr1 = InferSearcher(_FakeEvaluator(avoid_endturn=True),
                        InferSearchConfig(enabled=1, turns=1, search_when="any",
                                          topk=3, rollout_max_actions_per_turn=6))
    sr3 = InferSearcher(_FakeEvaluator(avoid_endturn=True),
                        InferSearchConfig(enabled=1, turns=3, search_when="any",
                                          topk=3, rollout_max_actions_per_turn=6))
    o1 = sr1.search(g, 0)
    o3 = sr3.search(g, 0)
    assert o1 is not None and o3 is not None
    assert int(o3.leaf_steps) > int(o1.leaf_steps)


# ── 5. 统计 / 轨迹 ─────────────────────────────────────────────────────────
def test_stats_and_trace_summary_consistent():
    pol = InferSearchPolicy(_StubBase(),
                            evaluator=_FakeEvaluator(),
                            config=InferSearchConfig(enabled=1, turns=1,
                                                     search_when="any",
                                                     max_searches_per_turn=1,
                                                     topk=3))
    g = _midgame(min_turn=5)
    pol.reset()
    dec = pol.decide(g, 0)
    assert bool(dec.info.get("search")) is True, "search_when=any 应触发搜索"
    st = pol.stats()
    assert st["search_calls"] == 1
    assert st["mean_ms_per_call"] is not None and st["mean_ms_per_call"] > 0.0
    # 两个统计量各自按 1 位小数四舍五入，差值上界是 0.05 + 舍入误差；
    # 用严格 `< 0.05` 会偶发卡在 0.05000000000000004（既有 flaky，非搜索逻辑）。
    assert abs(float(st["search_ms_total"]) - float(st["mean_ms_per_call"])) <= 0.051
    pol.flush()
    summ = trace_summary(pol.game_rows(), turns=(1, 12))
    assert summ["games"] == 1
    assert summ["per_turn_end"], "Σ(turn) 汇总缺失"
    # 走一次真实评测路径（evaluate_policy 会逐局 reset）
    from hsbg.az.train.evaluate import EvalConfig, evaluate_policy
    pol2 = InferSearchPolicy(_StubBase(), evaluator=_FakeEvaluator(),
                             config=InferSearchConfig(enabled=1, turns=1,
                                                      search_when="any",
                                                      max_searches_per_turn=3,
                                                      topk=3))
    res = evaluate_policy(pol2, EvalConfig(games=2, seed=424242, policy_seat=0,
                                           max_steps=400))
    pol2.flush()
    assert res["games"] == 2
    assert len(pol2.game_rows()) == 2
    st2 = pol2.stats()
    assert st2["search_calls"] > 0
    assert st2["games"] == 2
    assert st2["search_ms_per_game"] is not None


def test_snapshot_since_delta():
    pol = InferSearchPolicy(_StubBase(), evaluator=_FakeEvaluator(),
                            config=InferSearchConfig(enabled=1, turns=1,
                                                     search_when="any", topk=3))
    g = _midgame(min_turn=5)
    pol.reset()
    snap = pol.snapshot()
    pol.decide(g, 0)
    d = pol.since(snap)
    assert d["search_calls"] == 1 and d["games"] == 0
    assert d["mean_ms_per_call"] is not None
    pol.flush()
    assert pol.since(snap)["games"] == 1


# ── 6. 叶值附加项（tier / health）──────────────────────────────────────────
def test_leaf_score_weights_contract():
    """``leaf_score``：权重 0 逐位等于 ``leaf_value``；正权重按文档归一叠加。"""
    for s in (0, 42, 963, 30000):
        for t in (0, 3, 6):
            for h in (None, 1, 30):
                assert leaf_score(s, tier=t, health=h) == leaf_value(s)
    # tier：+w·(tier/6)
    assert leaf_score(500, tier=6, tier_bonus=0.02) - leaf_value(500) == \
        pytest.approx(0.02)
    assert leaf_score(500, tier=3, tier_bonus=0.02) - leaf_value(500) == \
        pytest.approx(0.01)
    # health：+w·(health/30)；health=None / -1 时（引擎不可用）不加
    assert leaf_score(500, health=30, health_bonus=0.02) - leaf_value(500) == \
        pytest.approx(0.02)
    assert leaf_score(500, health=0, health_bonus=0.02) == leaf_value(500)
    assert leaf_score(500, health=None, health_bonus=0.02) == leaf_value(500)
    assert leaf_score(500, health=-1, health_bonus=0.02) == leaf_value(500)
    # 负权重（惩罚高 tier）也允许
    assert leaf_score(500, tier=6, tier_bonus=-0.03) - leaf_value(500) == \
        pytest.approx(-0.03)


def test_leaf_bonus_wired_into_search():
    """searcher 的叶分 = ``leaf_score(叶位置 sigma/tier/health)``，且默认 0 权重不动分。"""
    g = _midgame(min_turn=5)
    mask = mask_from_bytes(g.legal_mask(0))
    o0 = _searcher(enabled=1, turns=1, search_when="any", topk=6).search(g, 0)
    o1 = _searcher(enabled=1, turns=1, search_when="any", topk=6,
                   tier_bonus=0.02, health_bonus=0.02).search(g, 0)
    assert o0 is not None and o1 is not None
    assert np.allclose(o0.q, np.asarray([leaf_value(s) for s in o0.sigma_end]))
    # 叶位置 tier/health 已记录，且附加项按文档叠加
    assert o1.tier_end.shape == o1.cands.shape and o1.health_end.shape == o1.cands.shape
    want = [leaf_score(int(s), tier=int(t), health=(int(h) if int(h) >= 0 else None),
                       tier_bonus=0.02, health_bonus=0.02)
            for s, t, h in zip(o1.sigma_end, o1.tier_end, o1.health_end)]
    assert np.allclose(o1.q, np.asarray(want))
    assert np.all(np.isfinite(o1.q))
    # 血量项确实能改变选择（w 大时：health=0 的候选被压到最低）
    big = _searcher(enabled=1, turns=1, search_when="any", topk=6,
                    health_bonus=10.0).search(g, 0)
    assert big is not None and np.all(np.isfinite(big.q))


# ── 7. 随机性感知搜索（StochasticSearcher：K 次采样）──────────────────────
def _legacy_reference_search(sr: InferSearcher, game, seat: int = 0):
    """K=1 旧路径的独立复刻（greedy rollout，用于逐位等价回归）。

    刻意不复用 ``InferSearcher.search``，否则测试变成同义反复：这里按修改前的
    实现（单副本、argmax rollout、叶值 = 单次 L(Σ)）重写一遍。
    """
    f, c = obs_arrays(game.observe(seat))
    mask = mask_from_bytes(game.legal_mask(seat))
    p = sr.prior_batch(f[None, :], c[None, :], mask[None, :])[0]
    cands = root_candidates(mask, p, int(sr.cfg.topk), skip_move=bool(sr.cfg.skip_move))
    if cands.size < 2:
        return None
    root_turn = int(game.turn)
    target = root_turn + max(0, int(sr.cfg.turns) - 1)
    sigma_root = sr.sigma(f)
    rolls = []
    for a in cands.tolist():
        g = game.copy()
        r = _Roll(cand=int(a), game=g, root_turn=root_turn, target_turn=int(target),
                  sigma=int(sigma_root), tier=max(0, int(round(float(
                      f[FEAT_TIER]) * FEAT_TIER_SCALE))), health=sr.health(game, seat))
        r.turn_actions = 1
        try:
            g.step(seat, int(a))
        except (RuntimeError, ValueError):
            r.truncated = r.done = True
        if not r.done and bool(g.is_over()):
            r.done = True
        rolls.append(r)
    max_steps = int(sr.cfg.max_rollout_steps) or (64 * int(sr.cfg.turns) + 64)
    steps = 0
    for _ in range(max_steps):
        todo = [r for r in rolls if not r.done]
        if not todo:
            break
        batch = []
        for r in todo:
            g = r.game
            if bool(g.is_over()) or int(g.turn) > int(r.target_turn):
                r.done = True
                continue
            if bool(g.needs_action(seat)):
                gf, gc = obs_arrays(g.observe(seat))
                gm = mask_from_bytes(g.legal_mask(seat))
                batch.append((r, gf, gc, gm))
                continue
            if int(sr.cfg.turns) <= 1:
                r.done = True
                continue
            if not sr._alive(g, seat):
                r.done = True
                continue
            if not sr._advance_others(g, seat):
                r.truncated = r.done = True
                continue
        if not batch:
            continue
        fmat = np.stack([b[1] for b in batch])
        cmat = np.stack([b[2] for b in batch])
        mmat = np.stack([b[3] for b in batch])
        pri = sr.prior_batch(fmat, cmat, mmat)
        sig = sigmas_from_features(fmat)
        tiers = np.rint(np.asarray(fmat, dtype=np.float64)[:, FEAT_TIER]
                        * FEAT_TIER_SCALE).astype(np.int64)
        for k, (r, _gf, _gc, gm) in enumerate(batch):
            r.sigma = int(round(float(sig[k])))
            r.tier = max(0, int(tiers[k]))
            r.health = sr.health(r.game, seat)
            r.steps += 1
            steps += 1
            a = int(np.argmax(pri[k]))
            r.turn_actions += 1
            if int(sr.cfg.rollout_max_actions_per_turn) > 0 \
                    and r.turn_actions > int(sr.cfg.rollout_max_actions_per_turn) \
                    and bool(gm[0]):
                a = 0
            try:
                r.game.step(seat, int(a))
            except (RuntimeError, ValueError):
                r.truncated = r.done = True
                continue
            if bool(r.game.is_over()):
                r.done = True
    q = np.asarray([sr.leaf_q(r) for r in rolls], dtype=np.float64)
    sg = np.asarray([int(r.sigma) for r in rolls], dtype=np.int64)
    from hsbg.az.train.sandbox_rollout import pi_from_q
    pi, _tau, value = pi_from_q(p, cands, q, sr._rc)
    return {"q": q, "sigma_end": sg, "pi": pi, "cands": np.asarray(cands),
            "leaf_steps": int(steps)}


def test_k1_is_bit_identical_to_legacy_path():
    """K=1（auto→greedy）必须与旧实现逐位一致：q / sigma_end / π / 候选。"""
    from hsbg.az.train.sandbox_rollout import pi_from_q  # noqa: F401
    g = _midgame(min_turn=5)
    sr = _searcher(enabled=1, turns=1, search_when="any", topk=5)
    out = sr.search(g, 0)
    ref = _legacy_reference_search(sr, g)
    assert out is not None and ref is not None
    assert np.array_equal(out.cands, ref["cands"])
    assert np.array_equal(out.q, ref["q"])
    assert np.array_equal(out.sigma_end, ref["sigma_end"])
    assert np.array_equal(out.pi, ref["pi"])
    assert int(out.rollouts) == 1
    assert np.all(out.q_se == 0.0)


def test_stochastic_rollouts_mean_se_and_seed_determinism():
    """K>1：叶值 = K 次均值；SE = std/√K；同 seed 逐位可复现、换 seed 有差异。"""
    g = _midgame(min_turn=5)
    kw = dict(enabled=1, turns=1, search_when="any", topk=5, rollouts=4,
              rollout_mode="sample", rollout_seed=12345)
    o1 = _searcher(**kw).search(g, 0)
    o2 = _searcher(**kw).search(g, 0)
    o3 = _searcher(**{**kw, "rollout_seed": 999}).search(g, 0)
    assert o1 is not None and o2 is not None and o3 is not None
    for o in (o1, o2, o3):
        assert int(o.rollouts) == 4
        assert o.q_samples.shape == (int(o.cands.size), 4)
        # 均值 / 标准误契约
        assert np.allclose(o.q, o.q_samples.mean(axis=1), atol=1e-12)
        want_se = o.q_samples.std(axis=1, ddof=1) / np.sqrt(4.0)
        assert np.allclose(o.q_se, want_se, atol=1e-12)
        assert np.all(o.q_se >= 0.0)
    # 同 seed / 同调用序 ⇒ 逐位相同
    assert np.array_equal(o1.q, o2.q)
    assert np.array_equal(o1.q_samples, o2.q_samples)
    # 换 seed ⇒ 至少一条候选的样本序列不同（引擎无重播种 API，用动作采样流近似）
    assert not np.array_equal(o1.q_samples, o3.q_samples)
    # K 次采样确实不同（同一候选内部至少一处方差 > 0）
    assert np.any(o1.q_se > 0.0), "K=4 的采样副本完全一致：独立性没生效"


def test_rollouts_gt1_greedy_is_rejected():
    """greedy + K>1 的副本必然相同 ⇒ 配置层直接拒绝（不静默浪费算力）。"""
    with pytest.raises(ValueError):
        InferSearchConfig(enabled=1, rollouts=4, rollout_mode="greedy").validate()
    # auto 在 K=1/K>1 下分别解析为 greedy/sample
    assert InferSearchConfig(rollouts=1).effective_rollout_mode() == "greedy"
    assert InferSearchConfig(rollouts=4).effective_rollout_mode() == "sample"


def test_search_timeout_falls_back_to_none():
    """``--infer-search-max-ms`` 超时：立即放弃本次搜索、调用方退回 π_base。"""
    g = _midgame(min_turn=5)
    sr = _searcher(enabled=1, turns=1, search_when="any", topk=6,
                   max_ms_per_search=1e-9)
    assert sr.search(g, 0) is None
    assert sr.timeouts == 1
    assert sr.calls == 0
