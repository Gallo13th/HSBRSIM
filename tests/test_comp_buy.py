"""B11 复利买卡偏置（CompBuyBias）的单元测试。"""
import numpy as np
import pytest

from hsbg.az.train.comp_buy import CompBuyBias, load_bias_ids
from hsbg.env.action_space_std import A_BUY, A_END, A_REFRESH, A_SELL, A_UPGRADE
from hsbg.env.obs_std import SLICE_CARD_BOARD, SLICE_CARD_SHOP


def _cfg(bias=1.0, spec=""):
    return type("C", (), {"comp_buy_bias": bias, "comp_cards": spec})()


def _obs(shop_ids, board_ids=()):
    cards = np.zeros(200, dtype=np.int16)
    base = int(SLICE_CARD_SHOP.start)
    for i, cid in enumerate(shop_ids):
        cards[base + i] = cid
    bbase = int(SLICE_CARD_BOARD.start)
    for i, cid in enumerate(board_ids):
        cards[bbase + i] = cid
    mask = np.zeros(274, dtype=bool)
    mask[A_END] = True
    mask[A_REFRESH] = True
    mask[A_UPGRADE] = True
    for i in range(7):
        mask[A_BUY + i] = True
        mask[A_SELL + i] = True
    return np.zeros(3227, dtype=np.float32), cards, mask


def test_spec_loads_mult_cards():
    ids = load_bias_ids()
    assert len(ids) > 100
    assert min(ids) >= 1                      # cards 编码 = card_id+1，不含 0 号空槽
    spec_ids = load_bias_ids(include=("MULT",))
    assert 0 < len(spec_ids) <= 10            # 3 张放大器（含金色变体）


def test_blocks_other_buys_when_core_in_shop():
    ids = sorted(load_bias_ids(include=("MULT",)))
    target = ids[0]
    g = CompBuyBias(_cfg())
    f, c, m = _obs([990, target, 991], board_ids=[target])
    out, biased = g.rewrite(f, c, m)
    assert biased
    assert bool(out[A_BUY + 1])                       # 目标卡仍可买
    assert not bool(out[A_BUY + 0]) and not bool(out[A_BUY + 2])   # 其它购买被屏蔽
    assert not bool(out[A_SELL + 0])                  # 场上核心卡不能卖
    assert bool(out[A_END]) and bool(out[A_REFRESH]) and bool(out[A_UPGRADE])


def test_no_target_is_identity():
    g = CompBuyBias(_cfg())
    f, c, m = _obs([901, 902, 903], board_ids=[901])
    out, biased = g.rewrite(f, c, m)
    assert not biased and out is m


def test_disabled_is_identity():
    g = CompBuyBias(_cfg(bias=0.0))
    assert not g.enabled
    ids = sorted(load_bias_ids(include=("MULT",)))
    f, c, m = _obs([990, ids[0]])
    out, biased = g.rewrite(f, c, m)
    assert not biased and out is m


def test_env_enables(monkeypatch):
    monkeypatch.setenv("HSBRSIM_COMP_BUY_BIAS", "1")
    g = CompBuyBias(_cfg(bias=0.0))
    assert g.enabled and len(g.targets) > 100
    monkeypatch.delenv("HSBRSIM_COMP_BUY_BIAS")
    assert not CompBuyBias(_cfg(bias=0.0)).enabled
