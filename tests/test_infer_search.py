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
                                        InferSearcher, leaf_value,
                                        trace_summary)
from hsbg.az.train.policies import Decision, Policy
from hsbg.az.train.sandbox_rollout import (MOVE_HI, MOVE_LO, DecisionTags,
                                           root_candidates)

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
    assert abs(float(st["search_ms_total"]) - float(st["mean_ms_per_call"])) < 0.05
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
