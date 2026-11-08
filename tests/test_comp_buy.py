"""B11 条件式买卡规则（CompBuyBias v2）的单元测试。"""
import numpy as np

from hsbg.az.train.comp_buy import CompBuyBias, CompSpec
from hsbg.env.action_space_std import A_BUY, A_END, A_REFRESH, A_SELL, A_UPGRADE
from hsbg.env.obs_std import (GLOBAL_FIELD_INDEX, GLOBAL_FIELD_SCALE, SLICE_CARD_BOARD,
                              SLICE_CARD_HAND, SLICE_CARD_SHOP)


def _cfg(bias=1.0, spec="", max_copies=3, floor=12.0, opening=20.0, late=17):
    return type("C", (), {"comp_buy_bias": bias, "comp_cards": spec,
                          "comp_buy_max_copies": max_copies,
                          "comp_buy_health_floor": floor,
                          "comp_buy_opening_health": opening,
                          "comp_buy_late_turn": late})()


def _spec():
    return CompSpec()


def _obs(shop_ids=(), board_ids=(), hand_ids=(), health=30, turn=6):
    cards = np.zeros(260, dtype=np.int16)
    base = int(SLICE_CARD_SHOP.start)
    for i, cid in enumerate(shop_ids):
        cards[base + i] = cid
    b = int(SLICE_CARD_BOARD.start)
    for i, cid in enumerate(board_ids):
        cards[b + i] = cid
    h = int(SLICE_CARD_HAND.start)
    for i, cid in enumerate(hand_ids):
        cards[h + i] = cid
    f = np.zeros(3227, dtype=np.float32)
    f[GLOBAL_FIELD_INDEX["health"]] = health / GLOBAL_FIELD_SCALE["health"]
    f[GLOBAL_FIELD_INDEX["turn"]] = turn / GLOBAL_FIELD_SCALE["turn"]
    mask = np.zeros(274, dtype=bool)
    mask[A_END] = mask[A_REFRESH] = mask[A_UPGRADE] = True
    for i in range(7):
        mask[A_BUY + i] = True
        mask[A_SELL + i] = True
    return f, cards, mask


def _names_for(cat):
    spec = _spec()
    return [(i, spec.card_name[i]) for i in sorted(spec.card_comp) if spec.card_cat.get(i) == cat]


def test_spec_has_multipliers():
    spec = _spec()
    names = {spec.card_name[i] for i in spec.mult}
    assert "布莱恩·铜须" in names and "达卡莱附魔师" in names and "提图斯·瑞文戴尔" in names
    assert len(spec.card_name) > 100


def test_must_buy_when_committed():
    """场上已有某阵容核心 ⇒ 商店出现同阵容核心时必须买（mask 只剩它）。"""
    spec = _spec()
    grow = [(i, spec.card_name[i]) for i in spec.grow if spec.card_comp.get(i)]
    core_a, _ = grow[0]
    comps = spec.card_comp[core_a]
    # 找一个同阵容、不同卡的第二个核心
    core_b = next(i for i, _ in grow if i != core_a and (spec.card_comp.get(i) or set()) & comps)
    g = CompBuyBias(_cfg())
    f, c, m = _obs(shop_ids=[core_b], board_ids=[core_a], health=30, turn=8)
    out, biased = g.rewrite(f, c, m)
    assert biased and g.n_must == 1
    assert list(np.flatnonzero(out)) == [int(A_BUY) + 0]


def test_release_when_low_health():
    spec = _spec()
    grow = [(i, spec.card_name[i]) for i in spec.grow if spec.card_comp.get(i)]
    core_a, _ = grow[0]
    comps = spec.card_comp[core_a]
    core_b = next(i for i, _ in grow if i != core_a and (spec.card_comp.get(i) or set()) & comps)
    g = CompBuyBias(_cfg())
    f, c, m = _obs(shop_ids=[core_b], board_ids=[core_a], health=8, turn=8)
    out, biased = g.rewrite(f, c, m)
    assert not biased and out is m and g.n_release == 1


def test_release_when_late_turn_or_too_many_copies():
    spec = _spec()
    grow = [(i, spec.card_name[i]) for i in spec.grow if spec.card_comp.get(i)]
    core_a, _ = grow[0]
    comps = spec.card_comp[core_a]
    core_b = next(i for i, _ in grow if i != core_a and (spec.card_comp.get(i) or set()) & comps)
    g = CompBuyBias(_cfg(late=10))
    f, c, m = _obs(shop_ids=[core_b], board_ids=[core_a], health=30, turn=12)
    _, biased = g.rewrite(f, c, m)
    assert not biased                                   # 回合太晚
    g2 = CompBuyBias(_cfg(max_copies=1))
    # 同一张卡：own 已有 1 张，max_copies=1 ⇒ 不再强制
    f, c, m = _obs(shop_ids=[core_a], board_ids=[core_a], health=30, turn=8)
    _, biased2 = g2.rewrite(f, c, m)
    assert not biased2                                   # 已达 max_copies


def test_opening_soft_bias_on_multiplier():
    spec = _spec()
    mult = sorted(spec.mult)[0]
    # 选一张"既不是放大器也不是成长核心"的目标卡（例如纯经济/功能卡）作为对照
    other = next(i for i in sorted(spec.card_comp)
                 if i not in spec.mult and i not in spec.grow)
    g = CompBuyBias(_cfg())
    f, c, m = _obs(shop_ids=[other, mult], health=30, turn=4)
    out, biased = g.rewrite(f, c, m)
    assert biased and g.n_soft == 1
    assert bool(out[int(A_BUY) + 1]) and not bool(out[int(A_BUY) + 0])
    assert bool(out[A_REFRESH]) and bool(out[A_END])


def test_release_when_two_comps_committed():
    spec = _spec()
    grow = [(i, spec.card_name[i]) for i in spec.grow if spec.card_comp.get(i)]
    a, _ = grow[0]
    b = next(i for i, _ in grow[1:] if not (spec.card_comp.get(i) or set()) & (spec.card_comp.get(a) or set()))
    g = CompBuyBias(_cfg())
    f, c, m = _obs(shop_ids=[grow[2][0]], board_ids=[a, b], health=30, turn=9)
    _, biased = g.rewrite(f, c, m)
    assert not biased                                    # 已在别的线上成型


def test_no_target_is_identity_and_disabled():
    g = CompBuyBias(_cfg())
    f, c, m = _obs(shop_ids=[900, 901], health=30, turn=5)
    out, biased = g.rewrite(f, c, m)
    assert not biased and out is m
    g2 = CompBuyBias(_cfg(bias=0.0))
    assert not g2.enabled
