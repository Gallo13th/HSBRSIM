"""B10 终局"上限"辅助头（ceiling_head）的单元测试。"""
import numpy as np
import torch

from hsbg.az.train.entity_model import (attach_ceiling_head, forward_ceiling_model)
from hsbg.az.train.ppo import (CollectConfig, PPOBatch, PPOConfig, build_batch_from_records,
                               ppo_losses)
from hsbg.env.obs_std import OBS_CARDS as N_CARDS, OBS_FLOATS as N_FEATURES


def _model():
    from hsbg.az.train.entity_model import build_entity_net
    torch.manual_seed(0)
    return build_entity_net(d_model=32, n_layers=1, n_heads=2)


def _batch(n=8, *, strength=None, tier=None):
    rng = np.random.default_rng(0)
    recs = []
    for i in range(n):
        r = {
            "features": rng.standard_normal(N_FEATURES).astype(np.float32),
            "cards": rng.integers(0, 100, size=N_CARDS).astype(np.int16),
            "action": int(rng.integers(0, 245)),
            "old_logprob": -3.0,
            "value": 0.0,
            "reward": 0.0,
            "done": False,
            "seat": i % 8,
            "game_id": i // 8,
            "rank": (i % 8) + 1,
            "turn": 5,
            "mask": np.ones(245, dtype=bool),
        }
        if strength is not None:
            r["final_strength"] = float(strength[i])
        if tier is not None:
            r["final_tier"] = float(tier[i])
        recs.append(r)
    return build_batch_from_records(recs, gamma=1.0, lam=1.0)


def test_attach_is_idempotent_and_zero_init():
    m = _model()
    assert getattr(m, "ceiling_head", None) is None
    attach_ceiling_head(m)
    h = m.ceiling_head
    assert h is not None and h.out_features == 4
    assert float(h.weight.abs().sum()) == 0.0 and float(h.bias.abs().sum()) == 0.0
    first = m.ceiling_head
    attach_ceiling_head(m)
    assert m.ceiling_head is first          # 幂等


def test_zero_init_does_not_change_policy_logits():
    m = _model().eval()
    rng = np.random.default_rng(1)
    f = torch.from_numpy(rng.standard_normal((3, N_FEATURES)).astype(np.float32))
    c = torch.from_numpy(rng.integers(0, 100, size=(3, N_CARDS)).astype(np.int64))
    mask = torch.ones((3, 245), dtype=torch.bool)
    with torch.no_grad():
        logits0, pred0 = forward_ceiling_model(m, f, c, mask) if getattr(m, "forward_ceiling", None) else (None, None)
        base = m(f, c, mask)[0]
        attach_ceiling_head(m)
        logits1, pred1 = forward_ceiling_model(m, f, c, mask)
    assert torch.allclose(base, logits1, atol=0.0)   # 零初始化不动策略
    assert pred1 is not None and pred1.shape == (3, 4)
    assert float(pred1.abs().sum()) == 0.0
    assert pred0 is None


def test_ppo_loss_uses_ceiling_targets():
    m = _model()
    attach_ceiling_head(m)
    n = 8
    fs = np.log1p(np.arange(n) * 100.0)
    ft = np.linspace(0.5, 1.0, n)
    batch = _batch(n, strength=fs, tier=ft)
    cfg0 = PPOConfig(epochs=1, minibatch=n, ceiling_aux_coef=0.0)
    cfg1 = PPOConfig(epochs=1, minibatch=n, ceiling_aux_coef=0.1)
    r0 = ppo_losses(m, batch, cfg0)
    r1 = ppo_losses(m, batch, cfg1)
    assert "ceiling_aux_loss" not in r0                      # 默认关闭 -> 字段不出现
    assert "ceiling_aux_loss" in r1
    assert r1["ceiling_rows"] > 0
    # 目标 = [log1p(s), tier/6]；零初始化 pred=0 -> loss = |log1p(s)| + tier/6 的 smooth_l1
    expect = (torch.nn.functional.smooth_l1_loss(torch.zeros(n), torch.as_tensor(fs, dtype=torch.float32))
              + torch.nn.functional.smooth_l1_loss(torch.zeros(n), torch.as_tensor(ft, dtype=torch.float32)))
    assert abs(float(r1["ceiling_aux_loss"]) - float(expect)) < 1e-3
    assert float(r1["total"]) > float(r0["total"])            # 总损失多出这一项


def test_batch_carries_both_targets():
    b = _batch(4, strength=[1.0, 2.0, 3.0, 4.0], tier=[0.5, 0.5, 1.0, 1.0])
    assert b.final_strength is not None and b.final_tier is not None
    assert np.allclose(b.final_strength, [1, 2, 3, 4])
    assert np.allclose(b.final_tier, [0.5, 0.5, 1.0, 1.0])
    b2 = _batch(4)
    assert b2.final_strength is None and b2.final_tier is None


def test_ceiling_head_survives_save_load(tmp_path):
    """checkpoint 往返：load_checkpoint 必须按 state_dict 里的 ceiling_head.* 重建头。"""
    from hsbg.az.train.entity_model import build_entity_net
    from hsbg.az.train.model import load_checkpoint, save_checkpoint
    torch.manual_seed(0)
    m = build_entity_net(d_model=32, n_layers=1, n_heads=2)
    attach_ceiling_head(m)
    with torch.no_grad():
        m.ceiling_head.weight.normal_(0, 0.1)
        m.ceiling_head.bias.fill_(0.5)
    p = tmp_path / "c.pt"
    save_checkpoint(m, str(p), meta={"arch": "entity", "d_model": 32, "n_layers": 1, "n_heads": 2})
    m2, meta = load_checkpoint(str(p), device="cpu")
    assert getattr(m2, "ceiling_head", None) is not None
    assert m2.ceiling_head.out_features == 4
    assert torch.allclose(m2.ceiling_head.weight, m.ceiling_head.weight)
    assert torch.allclose(m2.ceiling_head.bias, m.ceiling_head.bias)
    assert meta.get("d_model") == 32
