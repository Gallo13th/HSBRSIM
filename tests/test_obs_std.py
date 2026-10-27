"""标准观测（``hsbg.env.obs_std``）：3227 floats + 124 cards 契约回归。"""

from __future__ import annotations

import numpy as np
import pytest

engine = pytest.importorskip("hsbg_engine")

from hsbg.env import obs_std as o  # noqa: E402


def test_layout_matches_engine():
    ours = tuple(o.layout())
    theirs = tuple(tuple(x) for x in engine.layout())
    assert ours == theirs
    assert o.OBS_FLOATS == engine.OBS_FLOATS == 3227
    assert o.OBS_CARDS == engine.OBS_CARDS == 124
    assert engine.N_ACTIONS == 245


def test_decode_blocks_shapes():
    features = np.zeros(o.OBS_FLOATS, dtype=np.float32)
    cards = np.zeros(o.OBS_CARDS, dtype=np.int32)
    blocks = o.decode_blocks(features, cards)
    assert blocks["global"].shape == (o.GLOBAL_F,)
    assert blocks["board_minions"].shape == (o.N_BOARD, o.MINION_F)
    assert blocks["hand_items"].shape == (o.N_HAND, o.ITEM_F)
    assert blocks["shop_items"].shape == (o.N_SHOP, o.ITEM_F)
    assert blocks["opponent_boards"].shape == (o.N_OPP, o.N_BOARD, o.MINION_F)
    with pytest.raises(ValueError):
        o.decode_blocks(np.zeros(3, dtype=np.float32), cards)


def test_obs_std_declares_auto_tavern_contract():
    names = [name for name, _ in o.layout()]
    assert len(names) == 32
    assert names[0] == "MINION_F"
    assert "N_BOARD" in names and "N_HAND" in names and "N_SHOP" in names
