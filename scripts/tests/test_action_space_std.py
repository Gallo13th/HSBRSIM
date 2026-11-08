"""标准动作空间（``hsbg.env.action_space_std``）回归。

AutoTavern 兼容契约：前 245 项与 ``hsbg_engine`` 逐位一致；扩展段只追加
（245 == Unfreeze，246..249 备用技能槽，250..265 备用选择槽，266..273 FreezeSlot）。
"""

from __future__ import annotations

import pytest

engine = pytest.importorskip("hsbg_engine")

from hsbg.env import action_space_std as a  # noqa: E402


def test_constants_are_frozen():
    assert a.N_ACTIONS == 245
    assert a.N_STD_ACTIONS == 245
    assert a.N_TOTAL_ACTIONS == 274
    assert a.A_END == 0 and a.A_REFRESH == 1 and a.A_FREEZE == 2 and a.A_UPGRADE == 3
    assert a.A_HERO_POWER == 4 and a.N_POWERS == 2
    assert a.A_DARK_GIFT == 6 and a.A_CANCEL == 7
    assert (a.A_BUY, a.N_SHOP) == (8, 8)
    assert a.A_SELL == 16
    assert a.A_ACTIVATE == 23
    assert a.A_CHOOSE == 30 and a.N_CHOICE == 16
    assert a.A_PLAY == 46 and a.N_POS == 8 and a.N_HAND == 10
    assert a.A_MAGNETIZE == 126 and a.N_BOARD == 7
    assert a.A_MOVE == 196
    assert a.A_UNFREEZE == 245
    assert a.A_FREEZE_SLOT == 266


def test_action_names_match_engine_0_244():
    mismatches = [
        (i, a.action_name(i), engine.action_name(i))
        for i in range(245)
        if a.action_name(i) != engine.action_name(i)
    ]
    assert mismatches == []
    assert a.action_name(0) == "EndTurn"
    assert a.action_name(7) == "Cancel"
    assert a.action_name(46) == "Play { hand: 0, pos: 0 }"
    assert a.action_name(244) == "Move { from: 6, to: 6 }"


def test_encode_decode_roundtrip_all_indices():
    for index in range(a.N_TOTAL_ACTIONS):
        action = a.decode(index)
        assert a.encode(action) == index


def test_extension_actions_do_not_overlap_std():
    assert a.is_std_index(0) and a.is_std_index(244)
    assert not a.is_std_index(245)
    assert a.is_extension_index(245) and a.is_extension_index(273)
    for action in (a.Unfreeze(), a.HeroPower(2), a.Choose(16), a.FreezeSlot(0), a.FreezeSlot(7)):
        index = a.encode(action)
        assert 245 <= index < a.N_TOTAL_ACTIONS
        assert a.decode(index) == action


def test_invalid_indices_raise():
    for bad in (-1, a.N_TOTAL_ACTIONS):
        with pytest.raises(ValueError):
            a.decode(bad)
        with pytest.raises(ValueError):
            a.action_name(bad)
