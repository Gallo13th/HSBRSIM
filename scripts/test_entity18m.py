"""entity18m 结构/参数/checkpoint 往返测试。"""

from __future__ import annotations

import numpy as np
import pytest

from hsbg.az.train.common import OBS_CARDS, OBS_FLOATS


def test_entity18m_params_and_forward():
    torch = pytest.importorskip("torch")
    from hsbg.az.train.model import build_net

    model = build_net(arch="entity18m")
    n = sum(p.numel() for p in model.parameters())
    # 论文约 18M；当前配置应为 17.98M
    assert 17_800_000 <= n <= 18_200_000, n
    assert model.n_extra == 8
    assert tuple(model.pos_emb.weight.shape) == (24, 384)
    assert tuple(model.type_emb.weight.shape) == (7, 384)
    x = torch.zeros(2, OBS_FLOATS)
    c = torch.zeros(2, OBS_CARDS, dtype=torch.long)
    logits, rank, value = model(x, c)
    assert tuple(logits.shape) == (2, 245)
    assert tuple(rank.shape) == (2, 8)
    assert tuple(value.shape) == (2,)


def test_entity18m_checkpoint_roundtrip(tmp_path):
    pytest.importorskip("torch")
    from hsbg.az.train.model import build_net, load_checkpoint, save_checkpoint

    model = build_net(arch="entity18m")
    p = str(tmp_path / "m18.pt")
    save_checkpoint(model, p, meta={"arch": "entity18m"})
    loaded, meta = load_checkpoint(p, device="cpu")
    assert meta["arch"] == "entity18m"
    assert loaded.n_extra == 8
    assert sum(x.numel() for x in loaded.parameters()) == sum(
        x.numel() for x in model.parameters())
