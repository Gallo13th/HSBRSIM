from __future__ import annotations

import torch

from hsbg.value.warband_model import WarbandEncoder, pairwise_loss


def _batch(b=4, n=7, kw=8):
    return {
        "cards": torch.randint(0, 20, (b, n)),
        "atk": torch.rand(b, n) * 10,
        "hp": torch.rand(b, n) * 10,
        "tier": torch.randint(0, 7, (b, n)).float(),
        "kw": (torch.rand(b, n, kw) < 0.1).float(),
        "lengths": torch.tensor([n, n - 1, 1, 3][:b]),
    }


def test_forward_shapes_and_embedding():
    m = WarbandEncoder(n_cards=20, n_keywords=8, dim=32, layers=1)
    x = _batch()
    s, z = m(**x)
    assert s.shape == (4,)
    assert z.shape == (4, 32)
    assert torch.isfinite(s).all()


def test_pairwise_loss_gradient():
    m = WarbandEncoder(n_cards=20, n_keywords=8, dim=32, layers=1)
    x = _batch()
    s, _ = m(**x)
    win = torch.tensor([1.0, 0.5, 0.0, 1.0])
    loss = pairwise_loss(s[:2], s[2:], win[:2])
    assert torch.isfinite(loss)
    loss.backward()
    assert any(p.grad is not None for p in m.parameters())


def test_padding_is_masked():
    """Changing padded slots must not change the output."""
    m = WarbandEncoder(n_cards=20, n_keywords=8, dim=16, layers=1)
    m.eval()
    x = _batch()
    y = {k: v.clone() for k, v in x.items()}
    y["cards"][3, 3:] = 0
    y["atk"][3, 3:] = 123.0
    y["hp"][3, 3:] = 123.0
    y["kw"][3, 3:] = 1.0
    s1, _ = m(**x)
    s2, _ = m(**y)
    assert torch.allclose(s1[3], s2[3], atol=1e-3)
