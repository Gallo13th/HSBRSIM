"""流派偏置：完整 ``bias()`` 与优化前实现的**逐位等价**对照（端到端特征/分类/偏好/偏置）。

``test_bias_matches_reference`` 用 ``*_ref``（优化前逐行拷贝的实现 + 独立 history）跑同一条
决策序列，逐决策比较 245 维 bias 与统计计数；并断言检测/应用确实发生过（否则测例无意义）。
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

pytest.importorskip("hsbg_engine")

from hsbg.az.train import archetype_bias as AB  # noqa: E402
from tests.test_archetype_fast import (  # noqa: E402
    _observations, bias_from_pref_ref, build_vector_ref, parse_obs_ref)


class _RefBias:
    """优化前 ``ArchetypeBias.bias`` 的等价实现（独立 history + ref 特征/偏好）。"""

    def __init__(self, proto: AB.ArchetypeBias):
        self.p = proto
        self.history = AB.ArchetypeHistory()
        self.stats = AB.ArchetypeBiasStats()

    def bias(self, features, cards, mask, *, game_id, seat):
        obs = parse_obs_ref(features, cards, hero_id_of=self.p.card_id_of)
        self.history.observe(game_id, seat, obs)
        st = self.history._get(game_id, seat)
        x = build_vector_ref(st, obs, hero_vocab=self.p.hero_vocab)
        p_t = self.p.tribe_model.probs(x)[0]
        p_a = self.p.arch_model.probs(x)[0]
        self.stats.decisions += 1
        i_a = int(np.argmax(p_a))
        i_t = int(np.argmax(p_t))
        name_a = str(self.p.arch_model.classes[i_a])
        prob_a = float(p_a[i_a])
        name_t = str(self.p.tribe_model.classes[i_t])
        prob_t = float(p_t[i_t])
        b = AB.bucket_of(obs.turn)
        level, name, prob, got = "none", "", 0.0, None
        if name_a != "other" and prob_a >= self.p.min_prob:
            got = self.p._pref_for(name_a, level="archetype", b=b)
            if got is not None:
                level, name, prob = "archetype", name_a, prob_a
        if got is None and prob_t >= self.p.min_prob:
            got = self.p._pref_for(name_t, level="tribe", b=b)
            if got is not None:
                level, name, prob = "tribe", name_t, prob_t
        if got is None:
            self.stats.lvl_none += 1
            return None
        self.stats.detected += 1
        self.stats.prob_sum += float(prob)
        self.stats.name_counts[name] = self.stats.name_counts.get(name, 0) + 1
        if level == "archetype":
            self.stats.lvl_archetype += 1
        else:
            self.stats.lvl_tribe += 1
        pref, base = got
        bias = bias_from_pref_ref(pref, base, obs, mask, coef=self.p.coef,
                                  card_index_of=self.p.card_id_of, cards=cards)
        n_pos = int((bias > 0).sum())
        if n_pos == 0:
            return None
        self.stats.applied += 1
        self.stats.bias_actions += n_pos
        self.stats.bias_sum += float(bias.sum())
        return bias

    def note_action(self, action, *, game_id, seat):
        self.history.note_action(game_id, seat, action)


def test_bias_matches_reference():
    obs_list = _observations(n_seeds=3, steps=200)
    assert len(obs_list) > 50
    new = AB.ArchetypeBias(coef=0.5, min_prob=0.6)
    ref = _RefBias(new)
    acts = [0, 1, 40, 100, 200, 5, 6, 15, 3, 22]
    applied = 0
    for k, (f, c, m) in enumerate(obs_list):
        gid = f"g{k // 60}"
        seat = k % 8
        a = new.bias(f, c, m, game_id=gid, seat=seat)
        b = ref.bias(f, c, m, game_id=gid, seat=seat)
        if a is None:
            assert b is None, f"决策 {k}: new=None 但 ref 非空"
        else:
            assert b is not None, f"决策 {k}: ref=None 但 new 非空"
            assert np.array_equal(a, b), f"决策 {k}: bias 不一致"
            applied += 1
        act = acts[k % len(acts)]
        new.note_action(act, game_id=gid, seat=seat)
        ref.note_action(act, game_id=gid, seat=seat)
    assert applied > 0, "测例没有覆盖到任何「实际应用偏置」的决策"
    assert new.stats.decisions == ref.stats.decisions
    assert new.stats.detected == ref.stats.detected
    assert new.stats.applied == ref.stats.applied
    assert new.stats.lvl_archetype == ref.stats.lvl_archetype
    assert new.stats.lvl_tribe == ref.stats.lvl_tribe
    assert new.stats.lvl_none == ref.stats.lvl_none
    assert new.stats.name_counts == ref.stats.name_counts
    assert abs(new.stats.prob_sum - ref.stats.prob_sum) == 0.0
    assert abs(new.stats.bias_sum - ref.stats.bias_sum) == 0.0
    assert new.stats.bias_actions == ref.stats.bias_actions
