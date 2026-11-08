"""B10 终局强度辅助头（ceiling_head）的单元测试。"""
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from hsbg.az.train.entity_model import (  # noqa: E402
    attach_ceiling_head, forward_ceiling_model)
from hsbg.az.train.ppo import PPOBatch, pack_records_arrays  # noqa: E402


class _FakeEntity:
    d_model = 8
    ceiling_head = None


def test_attach_ceiling_head_zero_init():
    m = _FakeEntity()
    out = attach_ceiling_head(m)
    assert out is m and isinstance(m.ceiling_head, torch.nn.Linear)
    assert m.ceiling_head.out_features == 1
    assert float(m.ceiling_head.weight.abs().sum()) == 0.0
    # 幂等：已存在时不重建
    h = m.ceiling_head
    assert attach_ceiling_head(m).ceiling_head is h


def test_attach_requires_d_model():
    class _Bare:
        pass
    with pytest.raises(ValueError):
        attach_ceiling_head(_Bare())


def test_forward_ceiling_model_contract():
    # 有 forward_ceiling 但没 attach 头 -> (logits, None)
    class _NoHead:
        def forward_ceiling(self, f, c, m=None):
            return "logits", None
    out = forward_ceiling_model(_NoHead(), None, None, None)
    assert out == ("logits", None)

    # 完全没有 forward_ceiling（tiny 模型/测试替身）-> None，调用方据此跳过
    class _Plain:
        pass
    assert forward_ceiling_model(_Plain(), None, None, None) is None


def test_pack_and_batch_carry_final_strength():
    n, fd, nc = 2, 4, 2
    recs = []
    for i in range(n):
        recs.append({
            "features": np.zeros(fd, dtype=np.float32),
            "cards": np.zeros(nc, dtype=np.int16),
            "mask": np.ones(3, dtype=bool),
            "action": 0, "old_logprob": 0.0, "value": 0.0,
            "seat": 0, "game_id": i, "rank": 1, "turn": 1,
            "final_strength": 5.5 + i,
        })
    out = pack_records_arrays(recs)
    assert "final_strength" in out
    assert np.allclose(out["final_strength"], [5.5, 6.5])

    b = PPOBatch(
        features=out["features"], cards=out["cards"], masks=out["masks"],
        actions=out["actions"], old_logprobs=out["old_logprobs"],
        values=out["values"], rewards=np.zeros(n, dtype=np.float32),
        dones=np.ones(n, dtype=np.float32),
        advantages=np.zeros(n, dtype=np.float32),
        returns=np.zeros(n, dtype=np.float32), seats=out["seats"],
        game_ids=out["game_ids"], ranks=out["ranks"], turns=out["turns"],
        target_pi=np.zeros((n, 3), dtype=np.float32),
        has_pi=np.zeros(n, dtype=bool),
        episode_ids=np.zeros(n, dtype=np.int32),
        final_strength=out["final_strength"])
    assert b.final_strength is not None
    assert b.final_strength.dtype == np.float32
    assert np.allclose(b.final_strength, [5.5, 6.5])
