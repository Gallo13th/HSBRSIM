"""Astra V2 F 龙链脚本的门槛与兼容性测试。"""
import numpy as np

from scripts.comp_scripts import A_END, A_REFRESH, A_UPGRADE, A_BUY, COMPS, CompPolicy


def _mask(*actions):
    m = np.zeros(245, dtype=bool)
    for a in actions:
        m[a] = True
    return m


def _me(**kw):
    base = {"health": 30, "gold": 10, "upgrade_price": 7, "tier": 4,
            "board": [], "hand": [], "shop": [], "refresh_price": 1}
    base.update(kw)
    return base


def test_f_dragon_is_opt_in_and_core_priority():
    assert "f_dragon" in COMPS
    p = CompPolicy(COMPS["f_dragon"])
    v = {"turn": 3, "phase": "recruit", "me": _me(), "_mask": _mask(A_BUY)}
    v["me"]["shop"] = [{"id": "BG29_813", "type": "minion", "cost": 3}]
    assert p.act(v, v["_mask"]) == A_BUY


def test_f_dragon_low_health_stops_roll():
    p = CompPolicy(COMPS["f_dragon"])
    me = _me(health=20, gold=20, hand=[{"id": "BG21_015", "type": "minion"}])
    assert not p._f_can_roll(me)


def test_f_dragon_reserves_upgrade_plus_three():
    p = CompPolicy(COMPS["f_dragon"])
    me = _me(gold=9, upgrade_price=7, hand=[{"id": "BG21_015", "type": "minion"}])
    assert not p._f_can_roll(me)


def test_f_dragon_roll_requires_core():
    p = CompPolicy(COMPS["f_dragon"])
    assert not p._f_can_roll(_me(gold=20, upgrade_price=7))


def test_upgrade_action_precedes_triple_or_refresh():
    p = CompPolicy(COMPS["f_dragon"])
    board = [{"id": f"x{i}", "type": "minion", "races": ["DRAGON"], "atk": 1, "hp": 1} for i in range(4)]
    me = _me(gold=10, upgrade_price=7, tier=4, board=board,
             hand=[{"id": "BG21_015", "type": "minion"}],
             shop=[{"id": "BG21_015", "type": "minion", "cost": 3}])
    mask = _mask(A_UPGRADE, A_REFRESH)
    v = {"turn": 8, "phase": "recruit", "me": me}
    assert p.act(v, mask) == A_UPGRADE


def test_legacy_comp_keys_remain_present():
    for key in "ABCDEFGHIJKLMN":
        assert key in COMPS
    assert COMPS["J"].core == ("BG36_366", "BG26_152", "BG26_ICC_901")
