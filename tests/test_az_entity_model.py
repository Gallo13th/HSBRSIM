"""AutoTavern-style entity transformer 单测（无引擎依赖）。"""
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from hsbg.az.train.entity_model import (  # noqa: E402
    build_entity_net, CardTables, N_ACTIONS, TEXT_DIM,
)


def _tables(n=64):
    # 列数需与 card_static 一致：10+5+11+11+12+11+1+4+1 = 66? 实际用 56 也行测试
    static = np.zeros((n, 56), np.float32)
    text = np.zeros((n, TEXT_DIM), np.float32)
    return CardTables(static=static, text=text, n_cards=n)


def test_entity_forward_shapes_and_mask():
    net = build_entity_net(d_model=32, n_layers=1, n_heads=4, dim_ff=64,
                           card_dim=8, tables=_tables())
    f = torch.randn(2, 3227)
    c = torch.zeros(2, 124, dtype=torch.long)
    c[0, 0] = 1
    mask = torch.zeros(2, N_ACTIONS, dtype=torch.bool)
    mask[:, 0] = True
    mask[:, 8:16] = True
    logits, rank, value = net(f, c, mask)
    assert logits.shape == (2, N_ACTIONS)
    assert rank.shape == (2, 8)
    assert value.shape == (2,)
    # 非法位被 mask 成 -1e9
    assert torch.all(logits[:, 1] <= -1e8)
    assert torch.isfinite(logits[mask]).all()
    assert torch.isfinite(rank).all() and torch.isfinite(value).all()


def test_entity_pointer_segments_cover_245():
    from hsbg.az.train.common import ACTION_SEGMENTS
    total = sum(hi - lo + 1 for lo, hi in ACTION_SEGMENTS.values())
    assert total == N_ACTIONS
