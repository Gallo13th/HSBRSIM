"""Move 头解耦（``move_head_split``）单测。

覆盖：
1. 关闭时 Move 段 logits 与旧实现（``hb_i · hb_j``）逐位相同；
2. 开启后 ``(i→j)`` 与 ``(j→i)`` 的 logit 差不再只由 ``move_bias`` 决定（>1e-2）；
3. checkpoint 往返（meta/state_dict/前向一致）；
4. 参数增量 = 2*(d_model^2 + d_model)（``move_from``/``move_to`` 各一个 Linear）。
"""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from hsbg.az.train.entity_model import (  # noqa: E402
    CardTables, N_ACTIONS, N_BOARD, TEXT_DIM, build_entity_net,
)
from hsbg.az.train.model import (  # noqa: E402
    attach_move_head_split, load_checkpoint, save_checkpoint,
)

D_MODEL = 32


def _tables(n: int = 64):
    static = np.zeros((n, 56), np.float32)
    text = np.zeros((n, TEXT_DIM), np.float32)
    return CardTables(static=static, text=text, n_cards=n)


def _net(**kw):
    # dim_ff 用默认 4*d_model；n_heads=4（显式写进 meta，避免依赖默认 8）
    return build_entity_net(d_model=D_MODEL, n_layers=1, n_heads=4,
                            tables=_tables(), dropout=0.0, **kw)


def _inputs(b: int = 3, seed: int = 0):
    g = torch.Generator().manual_seed(seed)
    features = torch.randn(b, 3227, generator=g)
    cards = torch.zeros(b, 124, dtype=torch.long)
    return features, cards


def _logits(model, features, cards):
    model.eval()
    with torch.no_grad():
        out = model(features, cards)
    return out[0]


def test_disabled_matches_symmetric_old_impl_bitwise():
    torch.manual_seed(0)
    model = _net(move_head_split=False)
    model.eval()
    features, cards = _inputs()
    captured = {}
    hook = model.trunk.register_forward_hook(
        lambda _m, _i, out: captured.setdefault("hs", out))
    try:
        logits = _logits(model, features, cards)
    finally:
        hook.remove()
    hs = captured["hs"]
    hb = hs[:, 1:1 + N_BOARD]
    # 旧实现逐项复算：pointer_scale * (hb_i · hb_j) + move_bias
    ref = (model.pointer_scale
           * torch.einsum("bid,bjd->bij", hb, hb).reshape(features.shape[0], -1)
           + model.move_bias.reshape(1, -1))
    assert torch.equal(logits[:, 196:245], ref)
    # 关闭时不创建任何新参数（旧 ckpt strict load 安全）
    assert not any(k.startswith("move_from.") or k.startswith("move_to.")
                   for k in model.state_dict())
    assert model.move_from is None and model.move_to is None


def test_split_makes_move_direction_state_dependent():
    torch.manual_seed(0)
    model = _net(move_head_split=True)
    model.eval()
    features, cards = _inputs(seed=1)
    # bias 初始为 0 -> 方向差完全来自新的有向投影
    assert int(torch.count_nonzero(model.move_bias)) == 0
    logits = _logits(model, features, cards)
    mv = logits[:, 196:245].reshape(-1, N_BOARD, N_BOARD)
    diff = mv - mv.transpose(1, 2)
    assert float(diff.abs().max()) > 1e-2
    # 至少一个非对角方向对明显不同（不是数值噪声）
    off = diff.reshape(-1)
    assert int((off.abs() > 1e-2).sum()) > 0


def test_checkpoint_roundtrip_split(tmp_path, monkeypatch):
    from hsbg.az.train import entity_model as EM

    # load_checkpoint 用默认卡表；单测用小卡表，避免依赖引擎/数据
    monkeypatch.setattr(EM, "load_card_tables", lambda: _tables())
    torch.manual_seed(0)
    model = _net(move_head_split=True)
    model.eval()
    features, cards = _inputs(seed=2)
    before = _logits(model, features, cards)
    path = str(tmp_path / "split.pt")
    save_checkpoint(model, path, meta={"arch": "entity", "n_heads": 4})
    loaded, meta = load_checkpoint(path, device="cpu")
    assert bool(meta.get("move_head_split")) is True
    sd0, sd1 = model.state_dict(), loaded.state_dict()
    assert set(sd0) == set(sd1)
    for key in sd0:
        assert torch.equal(sd0[key], sd1[key]), f"权重不一致: {key}"
    assert torch.equal(before, _logits(loaded, features, cards))


def test_param_delta_and_attach():
    torch.manual_seed(0)
    base = _net(move_head_split=False)
    torch.manual_seed(0)
    split = _net(move_head_split=True)
    p0 = sum(p.numel() for p in base.parameters())
    p1 = sum(p.numel() for p in split.parameters())
    expected = 2 * (D_MODEL * D_MODEL + D_MODEL)
    assert p1 - p0 == expected
    assert p0 == sum(p.numel() for p in base.parameters())
    # 旧 ckpt 追加路径：参数量增量相同，已有权重不变
    before = {k: v.detach().clone() for k, v in base.state_dict().items()}
    attach_move_head_split(base)
    p2 = sum(p.numel() for p in base.parameters())
    assert p2 - p0 == expected
    for key, value in before.items():
        assert torch.equal(base.state_dict()[key], value)
    assert base.move_head_split is True
    assert base.move_from is not None and base.move_to is not None
    # 幂等
    attach_move_head_split(base)
    assert sum(p.numel() for p in base.parameters()) == p2
    assert N_ACTIONS == 245
