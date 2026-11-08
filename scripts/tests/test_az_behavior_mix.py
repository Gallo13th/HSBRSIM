"""搜索作为行为策略的 PPO（μ=(1−ε)π+ε·π_search）单测。

覆盖（≥10 项）：

1. ``μ`` 的逐元素定义与归一；
2. ``log μ(a) = log((1−ε)π(a)+ε·π_search(a))`` 手算对照；
3. ``KL(μ‖π)`` 手算对照；
4. 参数校验（eps / topk / turns / when）；
5. 触发口径（``carrier_or_spell`` 不匹配不搜）与每回合上限；
6. 搜索失败/超时回退（搜索器返回 None → 保留 π 采样、记 failed）；
7. ``ε`` 命中率与「按 μ 采样」的统计一致性（卡方 / 4σ）；
8. policy 层：records 同时写 ``logp_pi`` / ``logp_mu``，且 ``logp_mu`` 可手算复现；
9. **ε=0 与旧路径逐位等价**（同 seed 动作/logprob 序列相同、record 字段集合不变）；
10. 批次字段：默认关闭时不产出 ``behavior_logprobs``；启用时 ``pack→batch`` 与
    ``save/load`` 往返保真；
11. PPO 的 ratio 分母 = μ：``ratio_mean`` 起点 = 1（未混合）与常数放大的解析值；
12. 多 shard 统计聚合。
"""

from __future__ import annotations

import math
import types

import numpy as np
import pytest

from hsbg.az.train.behavior_mix import (BehaviorMixConfig, BehaviorMixer,
                                        aggregate_behavior_mix, kl_mu_pi,
                                        mix_distribution, mu_logprob)
from hsbg.az.train.ppo import (CollectConfig, PPOBatch, PPOSelfPlayPolicy,
                               build_batch_from_arrays, build_batch_from_records,
                               pack_records_arrays, ppo_losses, PPOConfig)
from hsbg.az.train.sandbox_rollout import DecisionTags

N_ACTIONS = 245
END_TURN = 0
BUY0 = 8
PLAY0 = 16

LEGACY_RECORD_KEYS = {"features", "cards", "mask", "action", "old_logprob",
                      "value", "target_pi", "seat", "turn", "game_id", "forced"}


# ── 小工具 ────────────────────────────────────────────────────────────────
def _mask(*actions: int) -> np.ndarray:
    m = np.zeros(N_ACTIONS, dtype=bool)
    for a in actions:
        m[int(a)] = True
    return m


def _dist(pairs) -> np.ndarray:
    p = np.zeros(N_ACTIONS, dtype=np.float64)
    for a, v in pairs:
        p[int(a)] = float(v)
    return p


class _FakeGame:
    """只提供 policy/searcher 需要的 observe/legal_mask/turn/copy。"""

    def __init__(self, mask, turn=1):
        self._mask = np.asarray(mask, dtype=bool)
        self.turn = int(turn)

    def observe(self, seat):
        return (np.zeros(3227, np.float32).tobytes(),
                np.zeros(124, np.int32).tobytes())

    def legal_mask(self, seat):
        return self._mask.astype(np.uint8).tobytes()

    def copy(self):
        return _FakeGame(self._mask, self.turn)


class _FakeSearcher:
    """可控 InferSearcher 替身：tags / prior_batch / search 三件套。"""

    def __init__(self, pi_search, *, prior=None, tags=None, fail=False,
                 evaluator=None):
        self.pi = np.asarray(pi_search, dtype=np.float64)
        #: 采集侧 π（先验/行为分布）；None = 每个状态上按 mask 均匀
        self.prior = None if prior is None else np.asarray(prior, dtype=np.float64)
        self.tags_obj = tags if tags is not None else DecisionTags(
            carrier_in_shop=1)
        self.fail = bool(fail)
        self.evaluator = evaluator
        self.calls = 0
        self.timeouts = 0
        self.ms_total = 0.0

    def tags(self, f, c):
        return self.tags_obj

    def prior_batch(self, feats, cards, masks):
        m2 = np.atleast_2d(np.asarray(masks, dtype=bool))
        if self.prior is not None:
            return np.repeat(self.prior[None, :], len(m2), axis=0)
        out = np.zeros(m2.shape, dtype=np.float64)
        cnt = np.maximum(m2.sum(axis=1, keepdims=True), 1)
        out[m2] = 1.0 / np.broadcast_to(cnt, m2.shape)[m2]
        return out

    def search(self, game, seat, *, prior=None, mask=None, rng=None):
        self.calls += 1
        if self.fail:
            self.timeouts += 1
            return None
        return types.SimpleNamespace(pi=self.pi.copy(), action=int(np.argmax(self.pi)),
                                     switch=False, elapsed_ms=0.1)


class _UniformEval:
    """stub evaluator：合法动作上的均匀 π（act 与 prior_batch 口径一致）。"""

    name = "stub-unif"

    @staticmethod
    def _probs(mask):
        m = np.asarray(mask, dtype=bool)
        p = np.zeros(N_ACTIONS, dtype=np.float64)
        legal = np.flatnonzero(m)
        p[legal] = 1.0 / float(legal.size)
        return p

    def act(self, f, c, mask, temperature=1.0, seed=None):
        p = self._probs(mask)
        rng = np.random.default_rng(int(seed) if seed is not None else 0)
        a = int(rng.choice(N_ACTIONS, p=p))
        return a, float(math.log(max(p[a], 1e-12))), 0.0

    def act_batch(self, features, cards, mask, temperature=1.0, seed=None):
        m2 = np.atleast_2d(np.asarray(mask, dtype=bool))
        rng0 = np.random.default_rng(int(seed) if seed is not None else 0)
        acts, lps = [], []
        for row in m2:
            p = self._probs(row)
            a = int(rng0.choice(N_ACTIONS, p=p))
            acts.append(a)
            lps.append(float(math.log(max(p[a], 1e-12))))
        return (np.asarray(acts, dtype=np.int64),
                np.asarray(lps, dtype=np.float32), np.zeros(len(acts), np.float32))


class _DummyModel:
    def eval(self):
        return self

    def to(self, device):
        return self


def _make_policy(*, behavior_mix=None, seed=1234, eval_fn=None):
    pytest.importorskip("torch")
    cfg = CollectConfig(behavior="net", fast_act=True, temperature=1.0,
                        max_actions_per_turn=40)
    return PPOSelfPlayPolicy(_DummyModel(), device="cpu", config=cfg,
                             eval_fn=eval_fn or _UniformEval(), seed=int(seed),
                             move_model=False, behavior_mix=behavior_mix)


# ══════════════════════════════════════════════════════════════════════════
# 1–4 纯函数
# ══════════════════════════════════════════════════════════════════════════
def test_mix_distribution_elementwise():
    pi = _dist([(END_TURN, 0.5), (BUY0, 0.3), (PLAY0, 0.2)])
    ps = _dist([(BUY0, 1.0)])
    mu = mix_distribution(pi, ps, 0.2)
    assert mu.sum() == pytest.approx(1.0, abs=1e-12)
    assert mu[END_TURN] == pytest.approx(0.8 * 0.5)
    assert mu[BUY0] == pytest.approx(0.8 * 0.3 + 0.2 * 1.0)
    assert mu[PLAY0] == pytest.approx(0.8 * 0.2)
    assert mu.sum() == pytest.approx(mu[END_TURN] + mu[BUY0] + mu[PLAY0])
    # ε=0 → 逐位等于 π
    mu0 = mix_distribution(pi, ps, 0.0)
    assert np.array_equal(mu0, pi)


def test_mu_logprob_hand_computed():
    pi = _dist([(END_TURN, 0.5), (BUY0, 0.3), (PLAY0, 0.2)])
    ps = _dist([(BUY0, 1.0)])
    eps = 0.2
    # a=BUY0：μ = 0.8·0.3 + 0.2·1.0 = 0.44
    assert mu_logprob(pi, ps, eps, BUY0) == pytest.approx(math.log(0.44))
    # a=END_TURN：μ = 0.8·0.5 = 0.4
    assert mu_logprob(pi, ps, eps, END_TURN) == pytest.approx(math.log(0.4))
    # a 的 π_search 质量为 0 时退化为 (1−ε)π(a)
    assert mu_logprob(pi, ps, eps, PLAY0) == pytest.approx(math.log(0.8 * 0.2))
    # ε=1 非法（不允许 π 完全消失）
    with pytest.raises(ValueError):
        mu_logprob(pi, ps, 1.0, BUY0)
    # 维度不符
    with pytest.raises(ValueError):
        mu_logprob(np.ones(3), ps, 0.2, 1)


def test_kl_mu_pi_hand_computed():
    pi = _dist([(END_TURN, 0.5), (BUY0, 0.5)])
    ps = _dist([(BUY0, 1.0)])
    mu = mix_distribution(pi, ps, 0.5)          # [0.25, 0.75]
    want = 0.25 * math.log(0.25 / 0.5) + 0.75 * math.log(0.75 / 0.5)
    assert kl_mu_pi(mu, pi) == pytest.approx(want, rel=1e-12)
    # ε=0 → KL=0
    assert kl_mu_pi(pi, pi) == pytest.approx(0.0, abs=1e-15)
    # π 在 μ 的支撑上为 0 → inf
    pi_zero = _dist([(END_TURN, 1.0)])
    assert kl_mu_pi(_dist([(BUY0, 1.0)]), pi_zero) == float("inf")


def test_config_validation():
    with pytest.raises(ValueError):
        BehaviorMixConfig(eps=-0.1).validate()
    with pytest.raises(ValueError):
        BehaviorMixConfig(eps=1.0).validate()
    with pytest.raises(ValueError):
        BehaviorMixConfig(eps=0.2, topk=1).validate()
    with pytest.raises(ValueError):
        BehaviorMixConfig(eps=0.2, turns=0).validate()
    with pytest.raises(ValueError):
        BehaviorMixConfig(eps=0.2, when="not_a_tag").validate()
    with pytest.raises(ValueError):
        BehaviorMixConfig(eps=0.2, max_per_turn=-1).validate()
    BehaviorMixConfig(eps=0.2).validate()       # 合法默认
    # mix_distribution 参数校验
    with pytest.raises(ValueError):
        mix_distribution(np.ones(245), np.ones(245), -0.5)
    bad = np.ones(245)
    bad[0] = np.nan
    with pytest.raises(ValueError):
        mix_distribution(bad, np.ones(245), 0.2)


# ══════════════════════════════════════════════════════════════════════════
# 5–7 触发 / 回退 / 统计
# ══════════════════════════════════════════════════════════════════════════
def _mixer(pi_search, *, prior=None, eps=0.2, when="carrier_or_spell",
           max_per_turn=6, fail=False, tags=None, seed=7):
    searcher = _FakeSearcher(pi_search, prior=prior, fail=fail, tags=tags)
    return BehaviorMixer(searcher, BehaviorMixConfig(
        eps=eps, when=when, max_per_turn=max_per_turn, seed=seed)), searcher


def test_trigger_requires_matching_tags():
    mask = _mask(END_TURN, BUY0)
    game = _FakeGame(mask)
    pi = _dist([(END_TURN, 0.5), (BUY0, 0.5)])
    ps = _dist([(BUY0, 1.0)])
    # tags 全 0 → carrier_or_spell 不匹配 → 一次都不搜
    mix, searcher = _mixer(ps, prior=pi, when="carrier_or_spell", tags=DecisionTags())
    for _ in range(20):
        out = mix.propose(game, 0, 1, action=END_TURN, logprob=math.log(0.5),
                          f=np.zeros(3227, np.float32),
                          c=np.zeros(124, np.int32), mask=mask,
                          rng=np.random.default_rng(3), temperature=1.0)
        assert out is None
    st = mix.stats()
    assert st["eligible"] == 0 and st["searched"] == 0 and st["decisions"] == 20
    assert searcher.calls == 0
    # when="any" → 匹配
    mix2, _ = _mixer(ps, prior=pi, when="any", tags=DecisionTags())
    out = mix2.propose(game, 0, 1, action=END_TURN, logprob=math.log(0.5),
                       f=np.zeros(3227, np.float32), c=np.zeros(124, np.int32),
                       mask=mask, rng=np.random.default_rng(3), temperature=1.0)
    assert out is not None and mix2.stats()["eligible"] == 1
    # 未命中 ε 时（exact=1）仍返回 MixOutcome：动作沿用 π，但 logp_mu 仍是 μ(a)
    st2 = mix2.stats()
    if not out.used_search:
        assert out.action == END_TURN
    # 省钱模式（exact=0）：未命中直接返回 None
    mix3, _ = _mixer(ps, prior=pi, eps=0.0, when="any")
    mix3.cfg.exact = 0
    assert mix3.propose(game, 0, 1, action=END_TURN, logprob=0.0,
                        f=np.zeros(3227, np.float32), c=np.zeros(124, np.int32),
                        mask=mask, rng=np.random.default_rng(3)) is None


def test_per_turn_cap():
    mask = _mask(END_TURN, BUY0)
    game = _FakeGame(mask, turn=2)
    pi = _dist([(END_TURN, 0.5), (BUY0, 0.5)])
    ps = _dist([(BUY0, 1.0)])
    mix, searcher = _mixer(ps, prior=pi, eps=1.0 - 1e-9, max_per_turn=1)
    rng = np.random.default_rng(11)
    o1 = mix.propose(game, 0, 5, action=END_TURN, logprob=0.0,
                     f=np.zeros(3227, np.float32), c=np.zeros(124, np.int32),
                     mask=mask, rng=rng)
    assert o1 is not None
    o2 = mix.propose(game, 0, 5, action=END_TURN, logprob=0.0,
                     f=np.zeros(3227, np.float32), c=np.zeros(124, np.int32),
                     mask=mask, rng=rng)
    assert o2 is None                     # 同回合上限
    assert mix.stats()["cap_skipped"] == 1 and searcher.calls == 1
    assert mix.stats()["searched"] == 1
    # 新回合（turn 变化）重置上限
    o3 = mix.propose(_FakeGame(mask, turn=3), 0, 5, action=END_TURN, logprob=0.0,
                     f=np.zeros(3227, np.float32), c=np.zeros(124, np.int32),
                     mask=mask, rng=rng)
    assert o3 is not None and mix.stats()["searched"] == 2


def test_search_failure_falls_back():
    mask = _mask(END_TURN, BUY0)
    game = _FakeGame(mask)
    pi = _dist([(END_TURN, 0.5), (BUY0, 0.5)])
    ps = _dist([(BUY0, 1.0)])
    mix, searcher = _mixer(ps, prior=pi, eps=1.0 - 1e-9, fail=True)
    out = mix.propose(game, 0, 1, action=END_TURN, logprob=math.log(0.5),
                      f=np.zeros(3227, np.float32), c=np.zeros(124, np.int32),
                      mask=mask, rng=np.random.default_rng(5))
    assert out is None                     # 超时/失败 → 调用方保留 π 采样
    st = mix.stats()
    assert st["failed"] == 1 and st["searched"] == 0
    assert st["search_timeouts"] == 1
    assert searcher.calls == 1


def test_eps_hit_rate_and_mu_sampling_statistics():
    """ε 命中率 ≈ ε；动作频率 ≈ μ=（1−ε)π + ε·π_search（4σ / 卡方）。"""
    mask = _mask(END_TURN, BUY0)
    game = _FakeGame(mask)
    pi = _dist([(END_TURN, 0.6), (BUY0, 0.4)])
    ps = _dist([(BUY0, 1.0)])
    eps = 0.25
    mix, _ = _mixer(ps, prior=pi, eps=eps, max_per_turn=0)
    rng = np.random.default_rng(2026)
    n = 6000
    counts = {END_TURN: 0, BUY0: 0}
    for _ in range(n):
        # 与真实 policy 同序：先按 π 采样动作，再交给 mixer（命中 ε 时换成 π_S 采样）
        a_pi = int(rng.choice(N_ACTIONS, p=pi))
        out = mix.propose(game, 0, 1, action=a_pi, logprob=math.log(pi[a_pi]),
                          f=np.zeros(3227, np.float32),
                          c=np.zeros(124, np.int32), mask=mask,
                          rng=rng, temperature=1.0)
        counts[int(out.action) if out is not None else a_pi] += 1
    st = mix.stats()
    # exact=1（默认）：每个匹配决策都搜索；ε 只决定「动作从 π_S 采样」的概率
    assert st["searched"] == n
    hit = st["eps_hits"] / n
    assert abs(hit - eps) < 4.0 * math.sqrt(eps * (1 - eps) / n)
    assert st["actions_from_search"] == st["eps_hits"]
    assert abs(st["actions_from_search"] / n - eps) < 4.0 * math.sqrt(
        eps * (1 - eps) / n)
    mu = (1 - eps) * pi + eps * ps
    for a in (END_TURN, BUY0):
        p_hat = counts[a] / n
        assert abs(p_hat - float(mu[a])) < 4.0 * math.sqrt(
            float(mu[a]) * (1 - float(mu[a])) / n), (a, p_hat, mu[a])
    # 卡方（1 dof）经验阈值 ~10.8 @ p<0.001
    chi2 = sum((counts[a] - n * float(mu[a])) ** 2 / (n * float(mu[a]))
               for a in (END_TURN, BUY0))
    assert chi2 < 10.8, chi2
    # μ 与 π 的 KL 是正值且有限
    assert 0.0 < st["kl_mu_pi_mean"] < 5.0


# ══════════════════════════════════════════════════════════════════════════
# 8–9 policy 层：records 字段 / logp 可复现 / ε=0 逐位等价
# ══════════════════════════════════════════════════════════════════════════
def test_policy_records_logp_mu_and_pi():
    mask = _mask(END_TURN, BUY0, PLAY0)
    game = _FakeGame(mask)
    pi = _UniformEval._probs(mask)          # 1/3 each
    ps = _dist([(BUY0, 1.0)])
    eps = 0.5
    mix, _ = _mixer(ps, eps=eps, when="any", max_per_turn=0)
    pol = _make_policy(behavior_mix=mix)
    # 两次决策：一次会走到混合（ε 命中），一次不会；两者都必须有 logp_mu/logp_pi
    for _ in range(20):
        pol.decide(game, 0)
    recs = pol.records
    assert len(recs) == 20
    assert any(r["action_source"] == "search_mix" for r in recs)
    assert any(r["action_source"] == "pi_mix" for r in recs)
    for r in recs:
        assert "logp_mu" in r and "logp_pi" in r and "action_source" in r
        a = int(r["action"])
        assert r["logp_pi"] == pytest.approx(float(r["old_logprob"]))
        assert r["logp_pi"] == pytest.approx(math.log(float(pi[a])))
        want = (1 - eps) * float(pi[a]) + eps * float(ps[a])
        assert r["logp_mu"] == pytest.approx(math.log(want), abs=1e-12)
        # μ(a) >= (1−ε)π(a) ⇒ logp_mu >= logp_pi + log(1−ε)
        assert r["logp_mu"] >= r["logp_pi"] + math.log(1 - eps) - 1e-12
    st = mix.stats()
    assert st["searched"] > 0 and st["decisions"] == 20
    # 记录里的动作与 logp 一致：logp_mu = log μ(a)，μ 的支撑是 mask
    assert pol.behavior_mix_meta()["eps"] == pytest.approx(eps)


def test_policy_eps_zero_is_bitwise_legacy():
    """ε=0（甚至传了 mixer 对象）与完全不传 mixer 的动作/logprob 序列逐位相同。"""
    mask = _mask(END_TURN, BUY0, PLAY0)
    game = _FakeGame(mask)
    ps = _dist([(BUY0, 1.0)])
    p0 = _make_policy(behavior_mix=None, seed=99)
    mix0, searcher0 = _mixer(ps, eps=0.0, when="any")
    p1 = _make_policy(behavior_mix=mix0, seed=99)
    for _ in range(12):
        d0 = p0.decide(game, 0)
        d1 = p1.decide(game, 0)
        assert int(d0.action) == int(d1.action)
        assert float(d0.info["logprob"]) == float(d1.info["logprob"])
        assert float(d0.info["value"]) == float(d1.info["value"])
    assert searcher0.calls == 0                      # 不搜、不耗 RNG
    # record 字段集合与旧路径完全一致（不新增 logp_mu/logp_pi/action_source）
    for rec in p1.records:
        assert set(rec.keys()) == LEGACY_RECORD_KEYS
    assert p1.behavior_mix_meta() == {}
    # RNG 状态也没被多消耗：后续采样的动作仍逐位相同
    for _ in range(5):
        assert int(p0.decide(game, 0).action) == int(p1.decide(game, 0).action)


# ══════════════════════════════════════════════════════════════════════════
# 10 批次字段 / 往返
# ══════════════════════════════════════════════════════════════════════════
def _records(mu_delta=None, episodes=2, steps=3):
    out = []
    for ep in range(episodes):
        for t in range(steps):
            m = _mask(END_TURN, BUY0, PLAY0)
            f = np.zeros(3227, dtype=np.float32)
            f[0] = float(t)
            c = np.zeros(124, dtype=np.int32)
            lp = math.log(1.0 / 3.0)
            rec = {"features": f, "cards": c, "mask": m, "action": BUY0,
                   "old_logprob": lp, "value": 0.0, "target_pi": None,
                   "seat": 0, "turn": int(t), "game_id": int(ep),
                   "forced": False, "rank": 1 + ep}
            if mu_delta is not None:
                rec["logp_pi"] = lp
                rec["logp_mu"] = lp - float(mu_delta)
                rec["action_source"] = "search_mix"
            out.append(rec)
    return out


def test_pack_has_no_behavior_fields_by_default():
    recs = _records()
    packed = pack_records_arrays(recs)
    assert "behavior_logprobs" not in packed and "pi_logprobs" not in packed
    batch = build_batch_from_arrays(packed)
    assert batch.behavior_logprobs is None and batch.pi_logprobs is None
    batch2 = build_batch_from_records(recs)
    assert batch2.behavior_logprobs is None
    # summary 不出现 behavior_mix 段
    assert "behavior_mix" not in batch.summary()


def test_pack_build_and_roundtrip_with_mu(tmp_path):
    recs = _records(mu_delta=math.log(1.5))
    packed = pack_records_arrays(recs)
    assert packed["behavior_logprobs"].shape == (len(recs),)
    assert packed["pi_logprobs"].shape == (len(recs),)
    batch = build_batch_from_arrays(packed)
    assert batch.behavior_logprobs is not None and batch.pi_logprobs is not None
    want = np.asarray([r["old_logprob"] - math.log(1.5) for r in recs], np.float32)
    # 批次按 (game_id, seat) 稳定排序；本例顺序不变
    assert np.allclose(batch.behavior_logprobs, want, atol=1e-6)
    assert np.allclose(batch.pi_logprobs, batch.old_logprobs, atol=1e-6)
    assert batch.validate() == []
    summ = batch.summary()["behavior_mix"]
    assert summ["weight_mean"] == pytest.approx(1.5, rel=1e-5)
    assert summ["ess_ratio"] == pytest.approx(1.0, rel=1e-5)
    # save/load 往返
    path = batch.save(str(tmp_path / "b.npz"))
    back = PPOBatch.load(path)
    assert back.behavior_logprobs is not None
    assert np.allclose(back.behavior_logprobs, batch.behavior_logprobs)
    assert np.allclose(back.pi_logprobs, batch.pi_logprobs)


# ══════════════════════════════════════════════════════════════════════════
# 11 PPO ratio 分母 = μ
# ══════════════════════════════════════════════════════════════════════════
def _tiny_model():
    from hsbg.az.train.model import build_net
    return build_net(hidden=32, arch="tiny")


def _model_logp(model, batch):
    """模型（采集侧权重）在该批次动作上的 log π(a)（与 ppo_losses 同一前向口径）。"""
    from hsbg.az.train.ppo import PPOEvaluator, masked_log_softmax_np
    ev = PPOEvaluator(model, device="cpu")
    plog, _rlog = ev.logits(batch.features, batch.cards.astype(np.int64),
                            batch.masks)
    acts = batch.actions.astype(np.int64)
    out = np.empty(len(acts), dtype=np.float64)
    for i in range(len(acts)):
        out[i] = masked_log_softmax_np(plog[i], batch.masks[i])[acts[i]]
    return out


def _losses(batch, model):
    cfg = PPOConfig(device="cpu", epochs=1, minibatch=8, clip=0.2,
                    value_coef=0.5, entropy_coef=0.0, pi_coef=0.0,
                    normalize_advantage=False, kl_early_stop=False,
                    compile_train=0, amp="off", seed=5)
    return ppo_losses(model, batch, cfg)


def test_ppo_ratio_starts_at_one_when_mu_equals_pi():
    """起点 ratio ≡ 1：old_logprob = 模型自己的 log π(a) 时与旧路径逐位同一张量。"""
    model = _tiny_model()
    base = build_batch_from_records(_records())
    old = _model_logp(model, base)
    base.old_logprobs = old.astype(np.float32)          # 采集侧同权重
    out = _losses(base, model)
    assert float(out["ratio_mean"]) == pytest.approx(1.0, abs=1e-6)
    # behavior_logprobs == old_logprobs（μ=π）时策略损失逐位不变
    same = build_batch_from_records(_records(mu_delta=0.0))
    same.old_logprobs = old.astype(np.float32)
    same.behavior_logprobs = old.astype(np.float32)
    same.pi_logprobs = old.astype(np.float32)
    out_same = _losses(same, model)
    assert float(out_same["ratio_mean"]) == pytest.approx(1.0, abs=1e-6)
    assert float(out_same["policy_loss"]) == pytest.approx(
        float(out["policy_loss"]), rel=1e-7, abs=1e-9)
    # 未混合样本的权重（summary）恒为 1
    assert same.summary()["behavior_mix"]["weight_mean"] == pytest.approx(1.0)


def test_ppo_ratio_denominator_uses_mu():
    """μ = π/1.2 ⇒ 起点 ratio=1.2（clip 两支都等于 1.2·A ⇒ 策略损失 ×1.2）。"""
    model = _tiny_model()
    base = build_batch_from_records(_records())
    old = _model_logp(model, base)
    base.old_logprobs = old.astype(np.float32)
    base_out = _losses(base, model)
    widened = build_batch_from_records(_records())
    widened.old_logprobs = old.astype(np.float32)
    widened.behavior_logprobs = (old - math.log(1.2)).astype(np.float32)
    widened.pi_logprobs = old.astype(np.float32)
    w_out = _losses(widened, model)
    assert float(w_out["ratio_mean"]) == pytest.approx(1.2, rel=1e-5)
    assert float(w_out["policy_loss"]) == pytest.approx(
        1.2 * float(base_out["policy_loss"]), rel=1e-4)
    # 若错用 π_old 当分母（=旧路径），ratio 仍是 1 —— 证明分母真的换了
    naive = build_batch_from_records(_records())
    naive.old_logprobs = old.astype(np.float32)
    assert float(_losses(naive, model)["ratio_mean"]) == pytest.approx(1.0, abs=1e-6)


# ══════════════════════════════════════════════════════════════════════════
# 12 聚合
# ══════════════════════════════════════════════════════════════════════════
def test_aggregate_behavior_mix():
    assert aggregate_behavior_mix([]) == {}
    assert aggregate_behavior_mix([{}, {"x": 1}]) == {}
    a = {"behavior_mix": {"decisions": 100, "eligible": 40, "eps_hits": 8,
                          "searched": 8, "failed": 0, "cap_skipped": 1,
                          "switched": 2, "kl_mu_pi_mean": 0.10,
                          "kl_mu_pi_p95": 0.2, "kl_mu_pi_max": 0.3,
                          "search_ms_mean": 100.0, "search_ms_p95": 200.0,
                          "search_ms_total": 800.0, "search_calls": 8,
                          "search_timeouts": 0}}
    b = {"behavior_mix": {"decisions": 300, "eligible": 160, "eps_hits": 32,
                          "searched": 24, "failed": 8, "cap_skipped": 0,
                          "switched": 6, "kl_mu_pi_mean": 0.20,
                          "kl_mu_pi_p95": 0.4, "kl_mu_pi_max": 0.5,
                          "search_ms_mean": 300.0, "search_ms_p95": 400.0,
                          "search_ms_total": 7200.0, "search_calls": 32,
                          "search_timeouts": 3}}
    agg = aggregate_behavior_mix([a, b])
    assert agg["decisions"] == 400 and agg["searched"] == 32
    assert agg["searched_ratio"] == pytest.approx(32 / 400)
    assert agg["eps_hit_rate"] == pytest.approx(40 / 200)
    assert agg["search_success_rate"] == pytest.approx(32 / 40)
    # 均值按 searched 加权： (0.10*8 + 0.20*24)/32
    assert agg["kl_mu_pi_mean"] == pytest.approx((0.10 * 8 + 0.20 * 24) / 32)
    assert agg["kl_mu_pi_max"] == pytest.approx(0.5)
    assert agg["search_timeouts"] == 3 and agg["shards"] == 2


# ══════════════════════════════════════════════════════════════════════════
# 16 真搜索器的超时回退（需要引擎；缺失时 skip）
# ══════════════════════════════════════════════════════════════════════════
def test_real_searcher_timeout_falls_back():
    pytest.importorskip("torch")
    pytest.importorskip("hsbg_engine")
    from hsbg.az.train.common import (load_engine, mask_from_bytes, obs_arrays)
    from hsbg.az.train.infer_search import InferSearchConfig, InferSearcher
    from hsbg.az.train.model import build_net
    from hsbg.az.train.ppo import PPOEvaluator

    E = load_engine()
    game = E.Game(seed=4242)
    seat = 0
    model = build_net(hidden=16, arch="tiny")
    ev = PPOEvaluator(model, device="cpu")
    # max_ms 极小 -> 第一次预算检查就放弃（模拟「搜索超时」）
    searcher = InferSearcher(ev, InferSearchConfig(
        enabled=1, turns=1, topk=8, search_when="any", action="pi_argmax",
        max_ms_per_search=1e-9).validate())
    f, c = obs_arrays(game.observe(seat))
    mask = mask_from_bytes(game.legal_mask(seat))
    assert int(mask.sum()) >= 2
    out = searcher.search(game, seat, prior=None, mask=mask)
    assert out is None
    assert int(searcher.timeouts) == 1
    # 同一状态在无预算上限时能给出 π_S，且支撑只在合法动作上
    searcher.cfg.max_ms_per_search = 0.0
    out2 = searcher.search(game, seat, prior=None, mask=mask)
    assert out2 is not None
    pi = np.asarray(out2.pi, dtype=np.float64)
    assert pi.sum() == pytest.approx(1.0, abs=1e-6)
    assert float(pi[~np.asarray(mask, dtype=bool)].sum()) == 0.0
    # μ 的 logprob 对 π_S 的支撑动作必须有限且在 (1−ε)π 与 1 之间
    pi0 = _UniformEval._probs(mask)
    a = int(out2.action)
    v = mu_logprob(pi0, pi, 0.2, a)
    assert math.isfinite(v)
    assert math.log(0.8 * float(pi0[a])) - 1e-9 <= v <= 0.0
