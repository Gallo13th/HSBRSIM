"""AT (TavernGym) 数据/动作布局契约测试。

AT 与 HSBRSIM 使用同一 3227/124 observation、245 动作布局。任何改变 N_CHOICE、
N_POS、N_ACTIONS 或段起点的改动都必须同步改 AT 并显式更新本测试。
"""

from __future__ import annotations

import pytest


def test_at_action_layout_matches_engine():
    E = pytest.importorskip("hsbg_engine")
    layout = dict(E.layout())
    expected = {
        "N_SHOP": 8, "N_BOARD": 7, "N_HAND": 10, "N_CHOICE": 16, "N_POS": 8,
        "N_POWERS": 2, "N_OPP": 7, "PENDING_KINDS": 9,
        "A_END": 0, "A_REFRESH": 1, "A_FREEZE": 2, "A_UPGRADE": 3,
        "A_HERO_POWER": 4, "A_DARK_GIFT": 6, "A_CANCEL": 7,
        "A_BUY": 8, "A_SELL": 16, "A_ACTIVATE": 23, "A_CHOOSE": 30,
        "A_PLAY": 46, "A_MAGNETIZE": 126, "A_MOVE": 196,
        "N_ACTIONS": 245, "OBS_FLOATS": 3227, "OBS_CARDS": 124,
    }
    for k, v in expected.items():
        assert layout[k] == v, (k, layout.get(k), v)

    assert E.action_name(0) == "EndTurn"
    assert E.action_name(1) == "Refresh"
    assert E.action_name(7) == "Cancel"
    assert E.action_name(8) == "Buy(0)"
    assert E.action_name(16) == "Sell(0)"
    assert E.action_name(23) == "Activate(0)"
    assert E.action_name(30) == "Choose(0)"
    assert E.action_name(46) == "Play { hand: 0, pos: 0 }"
    assert E.action_name(126) == "Magnetize { hand: 0, board: 0 }"
    assert E.action_name(196) == "Move { from: 0, to: 0 }"
    assert E.action_name(244) == "Move { from: 6, to: 6 }"


def test_at_obs_layout_matches_common():
    from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS
    from hsbg.env import obs_std as O
    assert N_ACTIONS == 245
    assert OBS_FLOATS == 3227
    assert OBS_CARDS == 124
    assert O.N_CHOICE == 16
    assert O.N_POS == 8
    assert O.N_ACTION == 245 if hasattr(O, "N_ACTION") else True
