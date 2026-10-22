"""实体 Transformer 策略网络测试：形状 / mask / 采样 / checkpoint / 性能。"""

from __future__ import annotations

import time

import numpy as np
import pytest
import torch

from hsbg.env.spec import CANDIDATE_MAX, NUM_ACTION_KINDS
from hsbg.policy.encoder import CardVocab, ObservationEncoder
from hsbg.policy.model import (
    MASKED_LOGIT,
    EntityTransformerPolicy,
    PolicyConfig,
    build_policy,
    load_policy_and_encoder,
)
from hsbg.policy.synthetic import FAKE_CARD_IDS, random_observation

DEVICE = "cpu"


@pytest.fixture(scope="module")
def encoder() -> ObservationEncoder:
    return ObservationEncoder(CardVocab(FAKE_CARD_IDS))


@pytest.fixture(scope="module")
def small_policy(encoder: ObservationEncoder) -> EntityTransformerPolicy:
    torch.manual_seed(0)
    cfg = PolicyConfig.for_encoder(encoder, dim=32, layers=1, heads=4, ff_dim=64)
    return build_policy(encoder, config=cfg)


@pytest.fixture(scope="module")
def batch(encoder: ObservationEncoder):
    rng = np.random.default_rng(7)
    obs_list = [random_observation(rng, card_ids=FAKE_CARD_IDS) for _ in range(8)]
    # 保证每个样本至少 2 个候选，便于测试 mask
    for obs in obs_list:
        if len(obs.candidates) < 2:
            obs.candidates = obs.candidates + (
                type(obs.candidates[0])(kind="end_turn"),
            )
    return encoder.collate(obs_list)


def test_forward_shapes_and_finiteness(small_policy, batch) -> None:
    small_policy.eval()
    with torch.no_grad():
        logits, value = small_policy(batch)
        out = small_policy.forward_full(batch)
    n = batch["global"].shape[0]
    assert logits.shape == (n, CANDIDATE_MAX)
    assert value.shape == (n,)
    assert torch.isfinite(logits).all()
    assert torch.isfinite(value).all()
    assert value.min().item() >= -1.0 - 1e-5
    assert value.max().item() <= 1.0 + 1e-5
    assert out["rank_logits"].shape == (n, small_policy.config.num_players)
    assert torch.isfinite(out["rank_logits"]).all()
    assert out["expected_rank"].min().item() >= 1.0 - 1e-5
    assert out["expected_rank"].max().item() <= small_policy.config.num_players + 1e-5


def test_masked_candidates_get_masked_logit(small_policy, batch) -> None:
    small_policy.eval()
    b = {k: v.clone() for k, v in batch.items()}
    # 人为屏蔽一部分候选（真实场景里 = 非法候选）
    mask = b["cand_mask"].clone()
    mask[:, :2] = 0.0
    mask[:, -3:] = 0.0
    # 保证每行仍有有效候选
    mask[:, 2] = 1.0
    b["cand_mask"] = mask
    with torch.no_grad():
        logits, value = small_policy(b)
    invalid = mask < 0.5
    assert torch.allclose(logits[invalid], torch.full_like(logits[invalid], MASKED_LOGIT))
    assert torch.isfinite(logits).all()
    assert torch.isfinite(value).all()
    # 采样只会落在有效候选上
    with torch.no_grad():
        actions, logp, _ = small_policy.act(b)
    chosen_mask = mask.gather(1, actions.unsqueeze(-1)).squeeze(-1)
    assert bool((chosen_mask > 0.5).all())
    assert torch.isfinite(logp).all()


def test_all_masked_row_fallback(small_policy, batch) -> None:
    """整行无有效候选时不能出 NaN（兜底放开 0 号候选）。"""
    b = {k: v.clone() for k, v in batch.items()}
    b["cand_mask"][0] = 0.0
    small_policy.eval()
    with torch.no_grad():
        logits, value = small_policy(b)
        actions, logp, _ = small_policy.act(b)
    assert torch.isfinite(logits).all()
    assert torch.isfinite(logp).all()
    assert int(actions[0].item()) == 0
    assert torch.isfinite(value).all()


def test_greedy_and_sampled_actions_are_valid(small_policy, batch) -> None:
    small_policy.eval()
    mask = batch["cand_mask"]
    with torch.no_grad():
        greedy, greedy_logp, greedy_value = small_policy.act(batch, greedy=True)
        sampled, sampled_logp, sampled_value = small_policy.act(batch, greedy=False)
    for acts in (greedy, sampled):
        assert acts.shape == (batch["global"].shape[0],)
        assert acts.dtype == torch.int64
        assert bool((mask.gather(1, acts.unsqueeze(-1)).squeeze(-1) > 0.5).all())
    assert torch.isfinite(greedy_logp).all() and torch.isfinite(sampled_logp).all()
    assert torch.isfinite(greedy_value).all() and torch.isfinite(sampled_value).all()
    # 贪心是确定性的
    with torch.no_grad():
        greedy2, _, _ = small_policy.act(batch, greedy=True)
    assert torch.equal(greedy, greedy2)


def test_evaluate_actions_consistent_with_act(small_policy, batch) -> None:
    small_policy.eval()
    with torch.no_grad():
        actions, logp, value = small_policy.act(batch)
        logp2, entropy, value2, rank_logits = small_policy.evaluate_actions(
            batch, actions, return_rank_logits=True
        )
        logp3, entropy3, value3 = small_policy.evaluate_actions(batch, actions)
    assert torch.allclose(logp, logp2, atol=1e-5)
    assert torch.allclose(value, value2, atol=1e-5)
    assert torch.allclose(value, value3, atol=1e-5)
    assert torch.isfinite(entropy).all() and torch.isfinite(entropy3).all()
    assert entropy.min().item() >= -1e-6
    assert rank_logits.shape == (batch["global"].shape[0], small_policy.config.num_players)


def test_scalar_value_mode(encoder, batch) -> None:
    torch.manual_seed(1)
    cfg = PolicyConfig.for_encoder(
        encoder, dim=32, layers=1, heads=4, ff_dim=64, value_mode="scalar"
    )
    policy = build_policy(encoder, config=cfg)
    policy.eval()
    with torch.no_grad():
        logits, value = policy(batch)
    assert logits.shape == (batch["global"].shape[0], CANDIDATE_MAX)
    assert value.shape == (batch["global"].shape[0],)
    assert torch.isfinite(value).all()
    assert value.abs().max().item() <= 1.0 + 1e-5


def test_default_config_param_count_in_range(encoder) -> None:
    """默认配置（d=128/L=4/heads=4/ff=256）参数量应落在 0.5M~2M。"""
    real_encoder = ObservationEncoder(CardVocab.from_data_dir())
    policy = build_policy(real_encoder)
    n = policy.count_parameters()
    assert policy.config.dim == 128
    assert policy.config.layers == 4
    assert policy.config.heads == 4
    assert policy.config.ff_dim == 256
    assert 500_000 <= n <= 2_000_000, n


def test_forward_latency_batch64(encoder) -> None:
    """CPU 上 batch=64 单次 forward 应 < 50ms（RTX 机器实测 ~20ms）。"""
    real_encoder = ObservationEncoder(CardVocab.from_data_dir())
    policy = build_policy(real_encoder)
    policy.eval()
    rng = np.random.default_rng(8)
    obs_list = [random_observation(rng) for _ in range(64)]
    batch = real_encoder.collate(obs_list)
    with torch.no_grad():
        for _ in range(3):
            policy(batch)  # warmup
        times = []
        for _ in range(7):
            t0 = time.perf_counter()
            policy(batch)
            times.append((time.perf_counter() - t0) * 1000.0)
    median = sorted(times)[len(times) // 2]
    print(f"\n[bench] forward batch=64 median={median:.2f}ms min={min(times):.2f}ms")
    assert median < 50.0, f"forward 太慢: {median:.2f}ms"


def test_checkpoint_roundtrip(tmp_path, small_policy, batch) -> None:
    path = tmp_path / "policy.pt"
    small_policy.save(path, meta={"note": "unit-test"})
    loaded, loaded_encoder = load_policy_and_encoder(path)
    assert loaded.count_parameters() == small_policy.count_parameters()
    assert loaded.config == small_policy.config
    assert loaded.vocab == small_policy.vocab
    assert loaded.meta.get("note") == "unit-test"
    assert loaded_encoder.vocab == small_policy.vocab
    small_policy.eval()
    loaded.eval()
    with torch.no_grad():
        logits_a, value_a = small_policy(batch)
        logits_b, value_b = loaded(batch)
    assert torch.allclose(logits_a, logits_b, atol=1e-6)
    assert torch.allclose(value_a, value_b, atol=1e-6)
    # checkpoint 里的编码器能独立重建输入（词表一致 → 编码一致）
    single = random_observation(np.random.default_rng(0), card_ids=FAKE_CARD_IDS)
    from hsbg.policy.encoder import ENCODED_KEYS

    enc_a = small_policy.make_encoder()
    enc_b = loaded_encoder
    for key in ENCODED_KEYS:
        assert np.array_equal(enc_a.encode_obs(single)[key], enc_b.encode_obs(single)[key])


def test_checkpoint_rejects_garbage(tmp_path) -> None:
    path = tmp_path / "bad.pt"
    torch.save({"foo": 1}, path)
    with pytest.raises(ValueError):
        EntityTransformerPolicy.load(path)


def test_resize_card_embedding_keeps_old_weights(encoder, batch) -> None:
    torch.manual_seed(2)
    cfg = PolicyConfig.for_encoder(encoder, dim=32, layers=1, heads=4, ff_dim=64)
    policy = build_policy(encoder, config=cfg)
    policy.eval()
    with torch.no_grad():
        logits_before, _ = policy(batch)
    extra = ["NEW_CARD_%d" % i for i in range(16)]
    new_vocab = CardVocab(list(FAKE_CARD_IDS) + extra)
    policy.resize_card_embedding(new_vocab)
    assert policy.config.vocab_size == len(new_vocab)
    assert policy.card_emb.num_embeddings == len(new_vocab)
    policy.eval()
    with torch.no_grad():
        logits_after, _ = policy(batch)
    # 旧卡下标未变，因此旧观测的 logit 完全一致
    assert torch.allclose(logits_before, logits_after, atol=1e-6)


def test_invalid_config_rejected() -> None:
    with pytest.raises(ValueError):
        PolicyConfig(dim=30, heads=4)  # 30 不能被 4 整除
    with pytest.raises(ValueError):
        PolicyConfig(value_mode="nope")
    with pytest.raises(ValueError):
        PolicyConfig(num_players=1)


def test_policy_config_roundtrip(encoder) -> None:
    cfg = PolicyConfig.for_encoder(encoder, dim=32, layers=1, heads=4, ff_dim=64)
    assert PolicyConfig.from_dict(cfg.to_dict()) == cfg
    # 未知字段被忽略（向后兼容）
    d = cfg.to_dict()
    d["future_field"] = 123
    assert PolicyConfig.from_dict(d) == cfg


def test_num_action_kinds_used_by_kind_embedding(small_policy) -> None:
    assert small_policy.kind_emb.num_embeddings == NUM_ACTION_KINDS
    assert small_policy.config.num_action_kinds == NUM_ACTION_KINDS
