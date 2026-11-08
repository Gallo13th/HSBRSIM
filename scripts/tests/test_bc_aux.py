"""真实人类 BC 辅助正则（``hsbg.az.train.bc_aux``）单测。

覆盖：
1. ``load_bc_samples``：动作白名单 / action_index 合法 / MMR 下限 / 缺失字段跳过；
2. MMR 权重（默认 1.0；6000–8000 线性增强可选）；
3. class-balanced 权重与 CE 数值（手算对照）；
4. ``BC_OBS_LAYOUT`` 叶子切片不重叠、不越界；
5. ``bc_obs_batch`` 部分观测：已知槽位填值、未知槽位 0 + mask False；
6. ``bc_coef=0`` 零影响：同 seed 前后权重逐位相同（即使传了 BC 池）；
7. ``bc_coef>0`` 时 stats 出现 bc_loss/bc_coef/bc_samples。
"""

from __future__ import annotations

import gzip
import json
import os

import numpy as np
import pytest

from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS
from hsbg.az.train.bc_aux import (
    BC_ACTION_TYPES,
    BC_OBS_LAYOUT,
    bc_ce_loss,
    bc_class_balance_weights,
    bc_obs_batch,
    load_bc_samples,
    mmr_weight,
    parse_bc_class_weights,
    parse_bc_coef_ramp,
)
from hsbg.az.train.seq_aux import parse_coef_ramp
from hsbg.env import obs_std as O


# ── fixtures：小卡表 + 小 JSONL ───────────────────────────────────────────
def _write_cards(path):
    """4 张卡：index 1=随从, 2=法术, 3=金色随从, 4=英雄。"""
    cards = [
        {"id": "TEST_MINION", "kind": "minion", "tier": 1, "atk": 2, "hp": 3,
         "cost": 3, "races": ["BEAST"], "keywords": ["TAUNT"]},
        {"id": "TEST_SPELL", "kind": "spell", "tier": 2, "atk": 0, "hp": 0,
         "cost": 2, "races": [], "keywords": []},
        {"id": "TEST_MINION_G", "kind": "minion", "tier": 2, "atk": 4, "hp": 6,
         "cost": 3, "races": ["BEAST"], "keywords": []},
        {"id": "TEST_HERO", "kind": "hero", "tier": 0, "atk": 0, "hp": 0,
         "cost": 0, "races": [], "keywords": []},
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": {"count": len(cards)}, "cards": cards}, f)
    return path


def _row(**kw):
    base = {
        "game_id": "g", "turn": 5, "mmr": "7000", "action_type": "sell",
        "action_index": 16, "gold": 5, "tier": 2, "health": 30, "armor": 0,
        "hero": "TEST_HERO", "board_cards": ["TEST_MINION"],
        "board_pos": [0], "hand_cards": [], "hand_pos": [],
        "shop_cards": ["TEST_MINION", "TEST_SPELL"], "shop_pos": [0, 7],
        "card_id": "TEST_MINION",
    }
    base.update(kw)
    return base


def _write_jsonl(path, rows):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            if isinstance(r, str):
                f.write(r + "\n")
            else:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


@pytest.fixture()
def bc_data(tmp_path):
    cards = _write_cards(tmp_path / "cards.json")
    rows = [
        _row(),                                              # keep sell
        _row(action_type="play_spell", action_index=46, mmr="6200",
             hand_cards=["TEST_SPELL"], hand_pos=[0], board_cards=[],
             board_pos=[], shop_cards=[], shop_pos=[]),      # keep play_spell
        _row(action_type="buy_minion", action_index=8, mmr=9000,
             shop_cards=["TEST_MINION"], shop_pos=[0]),      # keep buy_minion
        _row(action_type="freeze", action_index=2),          # 白名单外
        _row(action_type="reroll", action_index=None),       # 无 action_index
        _row(action_type="reroll", action_index=999),        # 越界
        _row(action_type="sell", action_index=16, mmr=5999), # MMR 不足
        _row(action_type="sell", action_index=16, mmr=None), # MMR 缺失
        _row(action_type=None, action_index=1),              # action_type 缺失
        "{not json",                                        # 坏行
    ]
    path = _write_jsonl(tmp_path / "bc.jsonl.gz", rows)
    return path, cards


# ── 1. 加载 / 过滤 ───────────────────────────────────────────────────────
def test_load_filters_whitelist_mmr_and_invalid(bc_data):
    path, cards = bc_data
    s = load_bc_samples(path, mmr_min=6000, cards_path=cards)
    assert len(s) == 3
    assert set(s.class_distribution()) == set(BC_ACTION_TYPES)
    assert int(s.class_counts.sum()) == 3
    assert s.class_distribution()["sell"] == 1
    assert s.class_distribution()["play_spell"] == 1
    assert s.class_distribution()["buy_minion"] == 1
    assert s.meta["lines"] == 10
    assert s.meta["kept"] == 3
    assert s.meta["skipped"]["action_type"] == 2  # freeze + None
    assert s.meta["skipped"]["action_index"] == 2  # None + 999
    assert s.meta["skipped"]["mmr_low"] == 1       # 5999
    assert s.meta["skipped"]["mmr"] == 1           # MMR 缺失
    assert s.meta["skipped"]["bad_json"] == 1
    assert np.allclose(s.weight, 1.0)
    assert np.array_equal(s.action_index, [16, 46, 8])
    # hero 映射：TEST_HERO 是卡表第 4 张 -> 下标 4
    assert int(s.hero[0]) == 4

    # actions 允许集合过滤
    only = load_bc_samples(path, mmr_min=6000, cards_path=cards,
                           actions=[16])
    assert len(only) == 1
    assert only.action_index.tolist() == [16]

    # limit
    one = load_bc_samples(path, mmr_min=6000, cards_path=cards, limit=1)
    assert len(one) == 1


def test_load_missing_state_fields_kept_but_mask_false(bc_data):
    path, cards = bc_data
    rows = [_row(gold=None, tier=None, health=None, turn=None, armor=None)]
    p = _write_jsonl(path.parent / "missing_state.jsonl.gz", rows)
    s = load_bc_samples(p, mmr_min=6000, cards_path=cards)
    assert len(s) == 1
    assert not bool(s.gold_known[0])
    assert not bool(s.tier_known[0])
    assert not bool(s.health_known[0])
    assert not bool(s.turn_known[0])
    b = bc_obs_batch(s)
    assert float(b.features[0, O.SLICE_GLOBAL.start + 7]) == 0.0  # gold
    assert not bool(b.feature_mask[0, O.SLICE_GLOBAL.start + 7])


# ── 2. MMR 权重 ──────────────────────────────────────────────────────────
def test_mmr_weight_default_and_linear_boost():
    assert mmr_weight(5000, mmr_min=6000) == 0.0
    assert mmr_weight(6000, mmr_min=6000) == 1.0
    assert mmr_weight(9000, mmr_min=6000) == 1.0
    # 6000..8000 线性增强（可选）
    assert mmr_weight(6000, mmr_min=6000, boost=1.5) == pytest.approx(1.0)
    assert mmr_weight(7000, mmr_min=6000, boost=1.5) == pytest.approx(1.25)
    assert mmr_weight(8000, mmr_min=6000, boost=1.5) == pytest.approx(1.5)
    assert mmr_weight(9000, mmr_min=6000, boost=1.5) == pytest.approx(1.5)
    assert mmr_weight(None) == 0.0


# ── 3. class-balanced + CE 数值 ──────────────────────────────────────────
def test_class_balance_weights_normalized():
    # count=9 的类别 w=1/9，count=1 的类别 w=1；均值=5/9 -> [0.2, 1.8]
    w = bc_class_balance_weights([0, 0, 1, 1, 1, 1, 1, 1, 1, 1], [9, 1])
    assert np.allclose(w[:2], 0.2)
    assert np.allclose(w[2:], 1.8)
    # “归一”是类别级（每个类别总权重相同），不是样本级 mean=1
    cw = bc_class_balance_weights([0, 1], [9, 1])
    assert np.allclose(cw, [0.2, 1.8])
    assert float(cw.mean()) == pytest.approx(1.0, abs=1e-12)


def test_bc_ce_loss_matches_manual():
    torch = pytest.importorskip("torch")
    import torch.nn.functional as F

    logits = torch.tensor([
        [2.0, 0.0, -1.0],
        [0.0, 1.0, 0.0],
        [1.0, 1.0, 1.0],
        [3.0, 0.0, 0.0],
    ])
    target = torch.tensor([0, 1, 2, 0])
    weights = torch.tensor([1.0, 2.0, 1.0, 1.0])
    mask = torch.tensor([True, True, False, True])
    got = bc_ce_loss(logits, target, weights=weights, mask=mask)
    per = F.cross_entropy(logits, target, reduction="none")
    w = weights * mask.float()
    ref = (per * w).sum() / w.sum()
    assert float(got) == pytest.approx(float(ref), abs=1e-6)

    # class-balanced 手算：类别 0/1 各 2 条，权重相同 -> 不改变量级
    got_cls = bc_ce_loss(logits, target, weights=weights, mask=mask,
                         class_ids=torch.tensor([0, 1, 0, 1]),
                         class_counts=torch.tensor([2, 2]))
    assert float(got_cls) == pytest.approx(float(ref), abs=1e-6)

    # 全 mask 掉 / 权重全 0 -> 0（且不 NaN）
    zero = bc_ce_loss(logits, target, weights=weights,
                      mask=torch.zeros(4, dtype=torch.bool))
    assert float(zero) == 0.0 and torch.isfinite(zero)
    zero2 = bc_ce_loss(logits, target, weights=torch.zeros(4))
    assert float(zero2) == 0.0 and torch.isfinite(zero2)


def test_parse_bc_coef_ramp_reuses_seq_parser():
    spec = "0.02@0.5,0.01@0,0.03@1.0"
    assert parse_bc_coef_ramp(spec) == parse_coef_ramp(spec)
    with pytest.raises(ValueError):
        parse_bc_coef_ramp("bad")


# ── 4. 布局切片 ──────────────────────────────────────────────────────────
def _overlaps(a: slice, b: slice) -> bool:
    return max(a.start, b.start) < min(a.stop, b.stop)


def test_bc_obs_layout_leaf_slices_disjoint_and_in_bounds():
    leaves = BC_OBS_LAYOUT.leaf_slices
    assert leaves
    for i, a in enumerate(leaves):
        assert 0 <= a.start < a.stop <= OBS_FLOATS
        for b in leaves[i + 1:]:
            assert not _overlaps(a, b), (a, b)
    # 卡牌块单独验证（features/cards 是两个数组，索引可以相同）
    card_leaves = BC_OBS_LAYOUT.card_leaf_slices
    for i, a in enumerate(card_leaves):
        assert 0 <= a.start < a.stop <= OBS_CARDS
        for b in card_leaves[i + 1:]:
            assert not _overlaps(a, b), (a, b)
    # 与 obs_std 常量同源（不是硬编码偏移）
    assert BC_OBS_LAYOUT.global_slice == O.SLICE_GLOBAL
    assert BC_OBS_LAYOUT.board_slice == O.SLICE_BOARD
    assert BC_OBS_LAYOUT.hand_slice == O.SLICE_HAND
    assert BC_OBS_LAYOUT.shop_slice == O.SLICE_SHOP
    # 卡牌块不重叠且不越界
    for a in (BC_OBS_LAYOUT.card_hero, BC_OBS_LAYOUT.card_board,
              BC_OBS_LAYOUT.card_hand, BC_OBS_LAYOUT.card_shop):
        assert 0 <= a.start < a.stop <= OBS_CARDS
    assert BC_OBS_LAYOUT.card_hero == O.SLICE_CARD_HERO
    assert BC_OBS_LAYOUT.card_board == O.SLICE_CARD_BOARD
    assert BC_OBS_LAYOUT.card_hand == O.SLICE_CARD_HAND
    assert BC_OBS_LAYOUT.card_shop == O.SLICE_CARD_SHOP


# ── 5. 部分观测编码 ──────────────────────────────────────────────────────
def test_bc_obs_batch_partial_observation(bc_data):
    path, cards = bc_data
    s = load_bc_samples(path, mmr_min=6000, cards_path=cards)
    b = bc_obs_batch(s)
    assert b.features.shape == (3, OBS_FLOATS)
    assert b.cards.shape == (3, OBS_CARDS)
    assert b.feature_mask.shape == (3, OBS_FLOATS)
    assert b.card_mask.shape == (3, OBS_CARDS)
    assert b.action_mask.shape == (3, N_ACTIONS)
    assert np.isfinite(b.features).all()
    assert b.cards.dtype == np.int32

    # 第 0 行是 sell：棋盘 1 张、商店 2 张，卡槽有值
    assert int(b.cards[0, O.SLICE_CARD_BOARD.start]) == 1
    assert int(b.cards[0, O.SLICE_CARD_SHOP.start]) == 1
    assert int(b.cards[0, O.SLICE_CARD_SHOP.start + 7]) == 2
    assert not bool(b.card_mask[0, O.SLICE_CARD_SHOP.start + 1])
    # global：turn/health/gold/tier 已知；opponent 全未知
    g = b.features[0]
    assert g[O.SLICE_GLOBAL.start + O.GLOBAL_FIELD_INDEX["turn"]] == \
        pytest.approx(5 / 20.0)
    assert g[O.SLICE_GLOBAL.start + O.GLOBAL_FIELD_INDEX["gold"]] == \
        pytest.approx(5 / 10.0)
    assert not b.feature_mask[0, O.SLICE_OPPONENTS].any()
    assert not b.feature_mask[0, O.SLICE_OPP_BOARDS].any()
    assert not b.features[0, O.SLICE_OPPONENTS].any()
    # 目标动作一定在 mask 内；sell 动作也在
    assert bool(b.action_mask[0, 16])
    # 第 2 行是 buy_minion(8)：商店只有 1 张 -> 只应有 8 号 buy
    assert bool(b.action_mask[2, 8])
    # 第 1 行是 play_spell(46)：法术只允许 pos=0
    assert bool(b.action_mask[1, 46])
    assert not b.action_mask[1, 47]


# ── 6/7. PPO 集成：零影响 + 正系数 stats ─────────────────────────────────
def _needs_torch():
    return pytest.importorskip("torch")


def _synthetic_batch(model, n=8, seed=0):
    """用模型自身分布生成一个合法 PPO 批次（无需引擎）。"""
    from hsbg.az.train.ppo import build_batch_from_records, masked_probs_np, \
        value_from_rank_logits_np

    torch = _needs_torch()
    rng = np.random.default_rng(seed)
    records = []
    model.eval()
    for i in range(n):
        features = rng.normal(size=OBS_FLOATS).astype(np.float32)
        cards = np.zeros(OBS_CARDS, dtype=np.int32)
        mask = np.zeros(N_ACTIONS, dtype=bool)
        mask[[0, 1, 8, 16, 46]] = True
        x = torch.from_numpy(features.reshape(1, -1))
        c = torch.from_numpy(cards.astype(np.int64).reshape(1, -1))
        with torch.no_grad():
            out = model(x, c)
        probs = masked_probs_np(out[0].numpy()[0], mask)
        probs = probs / max(float(probs.sum()), 1e-12)
        action = int(rng.choice(N_ACTIONS, p=probs))
        records.append({
            "features": features, "cards": cards, "mask": mask,
            "action": action,
            "old_logprob": float(np.log(max(float(probs[action]), 1e-12))),
            "value": float(value_from_rank_logits_np(out[1].numpy()[0])[0]),
            "rank": 1 + (i % 8), "seat": i % 8, "game_id": i // 8,
            "turn": 1,
        })
    return build_batch_from_records(records, gamma=1.0, lam=0.95)


def _tiny_models():
    from hsbg.az.train.model import build_net
    torch = _needs_torch()
    torch.manual_seed(0)
    a = build_net(16)
    torch.manual_seed(0)
    b = build_net(16)
    return a, b


def test_bc_coef_zero_bit_identical_even_with_pool(bc_data):
    torch = _needs_torch()
    from hsbg.az.train.ppo import PPOConfig, train_ppo

    path, cards = bc_data
    pool = load_bc_samples(path, mmr_min=6000, cards_path=cards)
    m0, m1 = _tiny_models()
    batch = _synthetic_batch(m0, n=8, seed=0)
    cfg0 = PPOConfig(epochs=1, minibatch=4, lr=1e-3, seed=0,
                     target_kl=10.0, value_loss="rank", pi_coef=0.0,
                     bc_coef=0.0)
    cfg1 = PPOConfig(epochs=1, minibatch=4, lr=1e-3, seed=0,
                     target_kl=10.0, value_loss="rank", pi_coef=0.0,
                     bc_coef=0.0, bc_samples_path=path)
    stats0 = train_ppo(m0, batch, cfg0,
                       rng=np.random.default_rng(0))
    stats1 = train_ppo(m1, batch, cfg1, bc_pool=pool,
                       rng=np.random.default_rng(0))
    sd0, sd1 = m0.state_dict(), m1.state_dict()
    assert set(sd0) == set(sd1)
    for k in sd0:
        assert torch.equal(sd0[k], sd1[k]), f"权重不一致: {k}"
    # 不出现 bc 字段，且 config 回显里也去掉（与旧版结构一致）
    for st in (stats0, stats1):
        assert "bc_loss" not in st
        assert "bc_coef" not in st
        assert "bc_coef" not in st["config"]
    # 只有 elapsed_s 是墙钟，其余逐项相同
    e0 = [{k: v for k, v in rec.items() if k != "elapsed_s"}
          for rec in stats0["epochs"]]
    e1 = [{k: v for k, v in rec.items() if k != "elapsed_s"}
          for rec in stats1["epochs"]]
    assert e0 == e1
    assert stats0["updates"] == stats1["updates"]
    assert stats0["samples"] == stats1["samples"]


def test_bc_coef_positive_adds_stats_and_loss(bc_data):
    _needs_torch()
    from hsbg.az.train.ppo import PPOConfig, train_ppo

    path, cards = bc_data
    pool = load_bc_samples(path, mmr_min=6000, cards_path=cards)
    m0, _m1 = _tiny_models()
    batch = _synthetic_batch(m0, n=8, seed=0)
    cfg = PPOConfig(epochs=1, minibatch=4, lr=1e-4, seed=0,
                    target_kl=10.0, value_loss="rank", pi_coef=0.0,
                    bc_coef=0.01, bc_batch=4, bc_samples_path=path)
    stats = train_ppo(m0, batch, cfg, bc_pool=pool,
                      rng=np.random.default_rng(0))
    assert "bc_loss" in stats
    assert np.isfinite(stats["bc_loss"])
    assert stats["bc_coef"] == pytest.approx(0.01)
    # 池只有 3 条 -> 每 minibatch 抽 min(bc_batch=4, 3)=3
    assert stats["bc_samples"] == pytest.approx(3.0)
    assert stats["config"]["bc_coef"] == pytest.approx(0.01)
    assert stats["bc_pool_samples"] == len(pool)


def test_real_bc_pool_smoke():
    from hsbg.az.train.bc_aux import DEFAULT_BC_SAMPLES_PATH, bc_pool_summary

    if not os.path.isfile(DEFAULT_BC_SAMPLES_PATH):
        pytest.skip("真实 BC 数据不存在")
    s = load_bc_samples(DEFAULT_BC_SAMPLES_PATH, mmr_min=6000, limit=500)
    assert len(s) == 500
    assert s.class_counts.sum() == 500
    summary = bc_pool_summary(s)
    assert summary["samples"] == 500
    assert summary["mmr_min"] == 6000


# ── 8. 稀有动作类别权重覆盖（class_weight_overrides）──────────────────────
def _class_weight_rows():
    return [
        _row(action_type="upgrade", action_index=3, mmr="7000"),
        _row(action_type="sell", action_index=16, mmr="7000"),
        _row(action_type="hero_power", action_index=4, mmr="7000"),
    ]


def test_parse_bc_class_weights():
    assert parse_bc_class_weights("") == {}
    assert parse_bc_class_weights("  ") == {}
    got = parse_bc_class_weights("upgrade=4,hero_power=2")
    assert got == {"upgrade": 4.0, "hero_power": 2.0}
    with pytest.raises(ValueError):
        parse_bc_class_weights("move=4")            # 不在 9 类白名单
    with pytest.raises(ValueError):
        parse_bc_class_weights("upgrade")           # 缺 =
    with pytest.raises(ValueError):
        parse_bc_class_weights("upgrade=0")         # 非正
    with pytest.raises(ValueError):
        parse_bc_class_weights("upgrade=nan")


def test_class_weight_overrides_multiply_on_top_of_class_balance(bc_data):
    path, cards = bc_data
    p = _write_jsonl(path.parent / "class_weight.jsonl.gz", _class_weight_rows())
    base = load_bc_samples(p, mmr_min=6000, cards_path=cards)
    over = load_bc_samples(
        p, mmr_min=6000, cards_path=cards,
        class_weight_overrides={"upgrade": 4.0, "hero_power": 2.0})
    assert np.allclose(base.class_weight, 1.0)
    assert over.class_weight.tolist() == [4.0, 1.0, 2.0]
    assert over.meta["class_weight_overrides"] == {
        "upgrade": 4.0, "hero_power": 2.0}

    mb = bc_obs_batch(base)
    mo = bc_obs_batch(over)
    assert mb.class_weight.tolist() == [1.0, 1.0, 1.0]
    assert mo.class_weight.tolist() == [4.0, 1.0, 2.0]
    # 有效权重 = MMR * class-balanced * override；upgrade 恰为默认的 4 倍
    cb = bc_class_balance_weights(mb.class_ids, mb.class_counts)
    co = bc_class_balance_weights(mo.class_ids, mo.class_counts)
    assert np.allclose(cb, co)
    eff_b = mb.weights * cb
    eff_o = mo.weights * co * mo.class_weight
    assert eff_o[0] / eff_b[0] == pytest.approx(4.0, rel=1e-6)
    assert eff_o[2] / eff_b[2] == pytest.approx(2.0, rel=1e-6)
    assert eff_o[1] == pytest.approx(eff_b[1], rel=1e-6)


def test_class_weight_applied_in_ce_loss():
    torch = pytest.importorskip("torch")
    import torch.nn.functional as F

    logits = torch.tensor([[4.0, 0.0], [0.0, 3.0], [1.0, 1.0]])
    target = torch.tensor([0, 1, 0])
    class_ids = torch.tensor([0, 1, 0])
    class_counts = torch.tensor([2, 1])
    cw = torch.tensor([4.0, 1.0, 4.0])
    got = bc_ce_loss(logits, target, class_ids=class_ids,
                     class_counts=class_counts, class_weight=cw)
    per = F.cross_entropy(logits, target, reduction="none")
    cb = torch.as_tensor(bc_class_balance_weights(
        class_ids.numpy(), class_counts.numpy()), dtype=per.dtype)
    ref = (per * cb * cw).sum() / (cb * cw).sum()
    assert float(got) == pytest.approx(float(ref), abs=1e-6)


def test_empty_class_weight_overrides_bitwise_equivalent(bc_data):
    torch = pytest.importorskip("torch")
    path, cards = bc_data
    rows = _class_weight_rows()
    p = _write_jsonl(path.parent / "class_weight_empty.jsonl.gz", rows)
    base = load_bc_samples(p, mmr_min=6000, cards_path=cards)
    empty = load_bc_samples(p, mmr_min=6000, cards_path=cards,
                            class_weight_overrides={})
    assert np.array_equal(base.class_weight, empty.class_weight)
    assert np.array_equal(base.weight, empty.weight)
    assert base.meta["class_weight_overrides"] == {}
    b0, b1 = bc_obs_batch(base), bc_obs_batch(empty)
    for attr in ("features", "cards", "weights", "class_weight",
                 "class_ids", "type_ids"):
        assert np.array_equal(getattr(b0, attr), getattr(b1, attr)), attr

    logits = torch.tensor([[2.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
    target = torch.tensor([0, 1])
    cls = torch.tensor([0, 1])
    counts = torch.tensor([1, 1])
    l_none = bc_ce_loss(logits, target, class_ids=cls, class_counts=counts)
    l_ones = bc_ce_loss(logits, target, class_ids=cls, class_counts=counts,
                        class_weight=torch.ones(2))
    assert torch.equal(l_none, l_ones)
