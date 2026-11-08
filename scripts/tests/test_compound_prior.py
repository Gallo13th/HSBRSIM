#!/usr/bin/env python3
"""``hsbg/az/train/compound_prior.py`` 单测：默认关 / 只在对应动作上 / 确定性。

覆盖
----
1. **默认关**：``coef=0 且 penalty=0`` 时不读卡表、``bias()`` 恒 ``None``（逐位等价旧路径）；
2. **落点正确**：正偏置只出现在「当前流派核心牌」的 Buy/Choose 槽位，其它动作整排 0；
3. **背景惩罚**：其它流派核心牌（非公用牌）拿 ``-penalty``，``common_ids`` 里的公用牌
   永不惩罚；
4. **非法位清零**：mask=False 的槽位即使有核心牌也不写值；
5. **确定性**：同一输入重复调用逐位相同（forced 路径 + 分类器自动路径都测）；
6. **退化判定**：无分类器时用「场上最多种族」判定。
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hsbg.az.train import compound_prior as CP  # noqa: E402
from hsbg.env.action_space_std import A_BUY, A_CHOOSE, N_ACTIONS  # noqa: E402
from hsbg.env.obs_std import (  # noqa: E402
    MINION_PRESENT,
    MINION_RACES,
    OBS_CARDS,
    OBS_FLOATS,
    SLICE_BOARD,
    SLICE_CARD_CHOICES,
    SLICE_CARD_SHOP,
)

#: 测试夹具的卡牌下标 → 卡 id（真实引擎里由 ``hsbg_engine.card_info`` 提供）
CARD_INDEX = {11: "CORE_A", 12: "CORE_B", 13: "COMMON", 14: "CORE_A2"}


def _payload() -> dict:
    """最小 ``compound_cards.json``：两个种族各 1-2 张核心牌 + 1 张公用牌。"""
    return {
        "meta": {"rules_version": 1, "counts": {"mined_total": 4}},
        "core": {
            "global": [
                {"id": "CORE_A", "name": "a", "name_zh": "甲", "tier": 2,
                 "races": ["BEAST"], "classes": ["accumulator"], "score": 10.0,
                 "mechanisms": [], "in_pool": True, "snippet": ""},
                {"id": "CORE_B", "name": "b", "name_zh": "乙", "tier": 3,
                 "races": ["DEMON"], "classes": ["multiplier"], "score": 8.0,
                 "mechanisms": [], "in_pool": True, "snippet": ""},
            ],
            "by_tribe": {
                "BEAST": [
                    {"id": "CORE_A", "name": "a", "name_zh": "甲", "tier": 2,
                     "races": ["BEAST"], "classes": ["accumulator"], "score": 10.0,
                     "mechanisms": [], "in_pool": True, "snippet": ""},
                    {"id": "CORE_A2", "name": "a2", "name_zh": "甲二", "tier": 3,
                     "races": ["BEAST"], "classes": ["multiplier"], "score": 5.0,
                     "mechanisms": [], "in_pool": True, "snippet": ""},
                ],
                "DEMON": [
                    {"id": "CORE_B", "name": "b", "name_zh": "乙", "tier": 3,
                     "races": ["DEMON"], "classes": ["multiplier"], "score": 8.0,
                     "mechanisms": [], "in_pool": True, "snippet": ""},
                ],
            },
            "by_archetype": {
                "beast_lobster": {"tribe_family": "BEAST", "mechanism": "",
                                  "head": True, "support": 9,
                                  "core": [
                                      {"id": "CORE_A", "name": "a", "name_zh": "甲",
                                       "tier": 2, "races": ["BEAST"],
                                       "classes": ["accumulator"], "score": 10.0,
                                       "mechanisms": [], "in_pool": True,
                                       "snippet": ""}]},
            },
            "common_ids": ["COMMON"],
        },
    }


@pytest.fixture()
def compound_json(tmp_path) -> str:
    p = tmp_path / "compound_cards.json"
    p.write_text(json.dumps(_payload(), ensure_ascii=False), encoding="utf-8")
    return str(p)


def _obs(shop_ids=(), choice_ids=(), *, features=None, mask=None):
    """构造一份 ``(features, cards, mask)``；shop/choice 槽位只填卡牌下标。"""
    f = np.zeros(OBS_FLOATS, dtype=np.float32)
    if features is not None:
        f[:] = features
    c = np.zeros(OBS_CARDS, dtype=np.int64)
    for slot, idx in enumerate(shop_ids):
        if idx:
            c[SLICE_CARD_SHOP.start + slot] = int(idx)
    for j, idx in enumerate(choice_ids):
        if idx:
            c[SLICE_CARD_CHOICES.start + j] = int(idx)
    m = np.ones(N_ACTIONS, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    return f, c, m


def _prior(compound_json, **kw):
    """测试用偏置器：``card_index_of`` 用固定表（不需要引擎）。"""
    kw.setdefault("archetype", "BEAST")
    kw.setdefault("use_model", False)
    return CP.CompoundPrior(compound_path=compound_json,
                            card_index_of=lambda i: CARD_INDEX.get(int(i), ""), **kw)


# ── 1. 默认关 ─────────────────────────────────────────────────────────────
def test_disabled_by_default_no_bias(compound_json):
    """``coef=0 / penalty=0``（默认）：不读卡表、不产 bias。"""
    p = CP.CompoundPrior(compound_path=compound_json)
    assert p.enabled is False
    assert p.core.by_tribe == {}          # 卡表根本没读
    f, c, m = _obs(shop_ids=[11, 12])
    assert p.bias(f, c, m) is None
    # 统计也不污染（decisions 保持 0 → 默认关时 meta 不新增键）
    assert p.stats.decisions == 0
    assert p.to_meta()["compound_decisions"] == 0


def test_aggregate_returns_empty_when_disabled():
    """没有任何带 ``compound_prior`` 的 meta 时聚合返回 ``{}``（不新增训练 meta 键）。"""
    assert CP.aggregate_compound_prior([{"a": 1}, {}]) == {}


# ── 2. 正偏置只落在当前流派核心牌的 Buy/Choose ────────────────────────────
def test_positive_bias_only_on_core_buy_and_choose(compound_json):
    p = _prior(compound_json, coef=1.0, background_penalty=0.0)
    # slot0=CORE_A(核心), slot1=CORE_B(他流派, 无惩罚), slot2=COMMON(公用牌)
    f, c, m = _obs(shop_ids=[11, 12, 13], choice_ids=[14])
    b = p.bias(f, c, m, game_id=1, seat=0)
    assert b is not None and b.shape == (N_ACTIONS,)
    assert float(b[A_BUY + 0]) == pytest.approx(1.0)     # 核心牌 → +coef
    assert float(b[A_BUY + 1]) == 0.0                     # 无惩罚 → 0
    assert float(b[A_BUY + 2]) == 0.0                     # 公用牌 → 0
    assert float(b[A_CHOOSE + 0]) == pytest.approx(1.0)   # Choose 选项也可以偏置
    # 其它动作整排 0（不碰节奏/卖/换位/EndTurn）
    touched = np.flatnonzero(b)
    assert set(touched.tolist()) == {A_BUY + 0, A_CHOOSE + 0}
    # 只加不减
    assert float(b.min()) >= 0.0


def test_other_archetype_core_gets_zero_without_penalty(compound_json):
    """``penalty=0`` 时他流派核心牌只是「不加」，绝不减。"""
    p = _prior(compound_json, coef=1.0, background_penalty=0.0)
    f, c, m = _obs(shop_ids=[12])            # 只有 DEMON 的核心牌
    assert p.bias(f, c, m) is None           # 一个动作位都没加 → None（零成本）


# ── 3. 背景惩罚 ───────────────────────────────────────────────────────────
def test_background_penalty_on_other_tribe_core(compound_json):
    p = _prior(compound_json, coef=1.0, background_penalty=1.0)
    f, c, m = _obs(shop_ids=[11, 12, 13])
    b = p.bias(f, c, m)
    assert b is not None
    assert float(b[A_BUY + 0]) == pytest.approx(1.0)      # 本流派核心 → +1
    assert float(b[A_BUY + 1]) == pytest.approx(-1.0)     # 他流派非公用牌 → -1
    assert float(b[A_BUY + 2]) == 0.0                     # 公用牌豁免


def test_background_penalty_scale(compound_json):
    """惩罚系数独立可调：penalty=0.5 → -0.5，且不超过 ``max_bias``。"""
    p = _prior(compound_json, coef=0.0, background_penalty=0.5)
    f, c, m = _obs(shop_ids=[11, 12])
    b = p.bias(f, c, m)
    assert b is not None
    assert float(b[A_BUY + 0]) == 0.0                     # coef=0 → 不加
    assert float(b[A_BUY + 1]) == pytest.approx(-0.5)


# ── 4. 非法位清零 ─────────────────────────────────────────────────────────
def test_illegal_positions_zeroed(compound_json):
    p = _prior(compound_json, coef=1.0)
    f, c, _ = _obs(shop_ids=[11])
    m = np.zeros(N_ACTIONS, dtype=bool)
    m[A_BUY + 1] = True                     # 合法的只有 slot1（空的）
    b = p.bias(f, c, m)
    assert b is None or float(b[A_BUY + 0]) == 0.0


def test_mask_dimension_checked(compound_json):
    p = _prior(compound_json, coef=1.0)
    f, c, _ = _obs(shop_ids=[11])
    with pytest.raises(ValueError):
        p.bias(f, c, np.ones(10, dtype=bool))


# ── 5. 确定性 ─────────────────────────────────────────────────────────────
def test_deterministic_same_input(compound_json):
    p = _prior(compound_json, coef=1.0, background_penalty=0.7)
    f, c, m = _obs(shop_ids=[11, 12, 13], choice_ids=[14, 11])
    b1 = p.bias(f, c, m, game_id=7, seat=0)
    b2 = p.bias(f, c, m, game_id=7, seat=0)
    assert np.array_equal(b1, b2)            # 逐位相同


def test_deterministic_across_instances(compound_json):
    f, c, m = _obs(shop_ids=[11, 12], choice_ids=[14])
    a = _prior(compound_json, coef=1.0, background_penalty=1.0).bias(f, c, m)
    b = _prior(compound_json, coef=1.0, background_penalty=1.0).bias(f, c, m)
    assert np.array_equal(a, b)


def test_deterministic_with_model_path(compound_json):
    """自动判定（分类器）路径：同一决策重复调用也逐位相同（幂等 observe）。"""
    if not os.path.exists(CP.DEFAULT_MODEL):
        pytest.skip("archetype_model.npz 缺失")
    p = CP.CompoundPrior(compound_path=compound_json, coef=1.0,
                         card_index_of=lambda i: CARD_INDEX.get(int(i), ""))
    f, c, m = _obs(shop_ids=[11, 12])
    b1 = p.bias(f, c, m, game_id=3, seat=0)
    b2 = p.bias(f, c, m, game_id=3, seat=0)
    assert np.array_equal(b1, b2)


# ── 6. 退化判定（场上最多种族）─────────────────────────────────────────────
def test_majority_tribe_fallback(compound_json):
    """分类器不可用 → 用场上最多种族；BEAST 在场上 → 核心集 = BEAST。"""
    f, c, m = _obs(shop_ids=[11])
    off = int(SLICE_BOARD.start)
    f[off + MINION_PRESENT] = 1.0
    # 引擎 RACE 顺序里 BEAST 的下标
    from hsbg.env.obs_std import RACE_NAMES
    f[off + MINION_RACES + int(RACE_NAMES.index("BEAST"))] = 1.0
    assert CP.majority_tribe(f) == "BEAST"

    p = CP.CompoundPrior(compound_path=compound_json, coef=1.0, use_model=False,
                         card_index_of=lambda i: CARD_INDEX.get(int(i), ""))
    name, prob, level = p.detect(f, c)
    assert name == "BEAST" and level == "majority" and prob == 1.0
    bb = p.bias(f, c, m)
    assert float(bb[A_BUY + 0]) == pytest.approx(1.0)


def test_global_fallback_when_no_tribe(compound_json):
    """无种族信息且无分类器 → 退回 ``core.global``（不崩、仍能给核心牌加分）。"""
    p = CP.CompoundPrior(compound_path=compound_json, coef=1.0, use_model=False,
                         card_index_of=lambda i: CARD_INDEX.get(int(i), ""))
    f, c, m = _obs(shop_ids=[11])
    name, _prob, level = p.detect(f, c)
    assert name == "" and level == "global"
    b = p.bias(f, c, m)
    assert float(b[A_BUY + 0]) == pytest.approx(1.0)   # CORE_A 在 global 里


# ── 7. 卡表解析 / 便捷函数 ────────────────────────────────────────────────
def test_core_ids_for_and_all(compound_json):
    assert CP.core_ids_for("BEAST", path=compound_json) == ["CORE_A", "CORE_A2"]
    assert CP.core_ids_for("demon", path=compound_json) == ["CORE_B"]
    assert CP.core_ids_for("beast_lobster", path=compound_json) == ["CORE_A"]
    assert CP.core_ids_for("nonexistent", path=compound_json) == ["CORE_A", "CORE_B"]
    assert CP.all_core_ids(path=compound_json) == ["CORE_A", "CORE_A2", "CORE_B"]


def test_meta_fields(compound_json):
    p = _prior(compound_json, coef=1.0, background_penalty=1.0)
    f, c, m = _obs(shop_ids=[11, 12])
    p.bias(f, c, m, game_id=1, seat=0)
    meta = p.to_meta()
    assert meta["compound_prior"] is True
    assert meta["compound_forced_archetype"] == "BEAST"
    assert meta["compound_pos_actions"] == 1
    assert meta["compound_neg_actions"] == 1
    assert meta["compound_applied"] == 1
    agg = CP.aggregate_compound_prior([meta, meta])
    assert agg["compound_pos_actions"] == 2
    assert agg["compound_neg_actions"] == 2
    assert agg["compound_archetype"] == "BEAST"
