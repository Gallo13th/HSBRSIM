"""BC 训练管线测试：数据集收集/序列化、教师协议、训练收敛、checkpoint。"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from hsbg.env.spec import CANDIDATE_MAX
from hsbg.policy.encoder import CardVocab, ObservationEncoder
from hsbg.policy.model import PolicyConfig, build_policy, load_policy_and_encoder
from hsbg.policy.synthetic import (
    FAKE_CARD_IDS,
    random_observation,
    teacher_choose,
    teacher_score,
)
from hsbg.train.bc import (
    BCDataset,
    BCConfig,
    BCTrainer,
    collect_bc_dataset,
    make_policy_teacher,
    train_bc,
)
from hsbg.train.evaluate import HeuristicAgent
from hsbg.train.vec_env import MockVecEnv


@pytest.fixture(scope="module")
def encoder() -> ObservationEncoder:
    return ObservationEncoder(CardVocab(FAKE_CARD_IDS))


@pytest.fixture(scope="module")
def tiny_policy(encoder):
    torch.manual_seed(0)
    cfg = PolicyConfig.for_encoder(encoder, dim=32, layers=1, heads=4, ff_dim=64)
    return build_policy(encoder, config=cfg)


@pytest.fixture()
def env() -> MockVecEnv:
    e = MockVecEnv(
        2, seed=0, card_ids=FAKE_CARD_IDS, episode_steps_range=(10, 20),
        candidate_max=CANDIDATE_MAX + 4,
    )
    yield e
    e.close()


@pytest.fixture(scope="module")
def dataset() -> BCDataset:
    env = MockVecEnv(2, seed=1, card_ids=FAKE_CARD_IDS, episode_steps_range=(10, 18))
    ds = collect_bc_dataset(env, teacher=teacher_choose, episodes=8)
    env.close()
    return ds


# ══════════════════════════════════════════════════════════════════════
# 数据集
# ══════════════════════════════════════════════════════════════════════


def test_collect_bc_dataset(dataset: BCDataset) -> None:
    assert len(dataset) > 40
    assert dataset.num_episodes() >= 8
    assert len(dataset.ranks) == len(dataset)
    assert len(dataset.episode_ids) == len(dataset)
    # 大多数样本所在 episode 有终局名次
    known = [r for r in dataset.ranks if r >= 1]
    assert len(known) >= len(dataset) * 0.5
    assert all(1 <= r <= 8 for r in known)
    for obs, action in dataset.samples:
        assert 0 <= action < max(len(obs.candidates), 1)
    assert dataset.meta["episodes_collected"] >= 8
    assert isinstance(dataset.action_kind_histogram(), dict)


def test_dataset_random_accuracy(dataset: BCDataset) -> None:
    acc = dataset.random_accuracy()
    assert 0.0 < acc <= 1.0
    assert acc < 0.5  # 随机基线明显低于 1（候选通常 >2 个）


def test_dataset_save_load_roundtrip(dataset: BCDataset, tmp_path) -> None:
    path = dataset.save(tmp_path / "ds.pkl")
    loaded = BCDataset.load(path)
    assert len(loaded) == len(dataset)
    assert loaded.ranks == dataset.ranks
    assert loaded.episode_ids == dataset.episode_ids
    assert loaded.meta == dataset.meta
    # 观测内容一致（dataclass 相等）
    assert loaded.samples[0][0] == dataset.samples[0][0]
    assert loaded.samples[0][1] == dataset.samples[0][1]


def test_dataset_split_by_episode_no_leak(dataset: BCDataset) -> None:
    train, val = dataset.split_by_episode(val_frac=0.25, seed=0)
    assert len(train) > 0 and len(val) > 0
    assert len(train) + len(val) == len(dataset)
    assert not (set(train.episode_ids) & set(val.episode_ids))


def test_dataset_encoded(encoder, dataset) -> None:
    data = dataset.encoded(encoder)
    n = len(dataset)
    for key in ("entity_card", "cand_mask", "actions", "ranks"):
        assert data[key].shape[0] == n
    assert data["cand_mask"].shape[1] == CANDIDATE_MAX
    assert torch.isfinite(data["global"]).all()
    # actions 一定落在有效候选范围内
    assert bool((data["actions"] < data["num_candidates"].clamp_min(1)).all())


def test_empty_dataset_errors(encoder) -> None:
    ds = BCDataset()
    with pytest.raises(ValueError):
        ds.encoded(encoder)


def test_collect_dataset_with_agent_teacher(env) -> None:
    ds = collect_bc_dataset(env, teacher=HeuristicAgent(seed=0), episodes=3)
    assert len(ds) > 10


def test_teacher_score_prefers_buy() -> None:
    from hsbg.env.spec import CandidateAction

    buy = CandidateAction(kind="buy", src_zone="tavern", src_slot=0, cost=3)
    freeze = CandidateAction(kind="freeze")
    assert teacher_score(buy) > teacher_score(freeze)
    obs = random_observation(np.random.default_rng(0), card_ids=FAKE_CARD_IDS)
    assert 0 <= teacher_choose(obs) < max(len(obs.candidates), 1)


# ══════════════════════════════════════════════════════════════════════
# BC 训练
# ══════════════════════════════════════════════════════════════════════


def test_bc_trainer_beats_random_baseline(encoder, tiny_policy, dataset) -> None:
    torch.manual_seed(0)
    cfg = BCConfig(lr=3e-3, epochs=15, batch_size=32, seed=0, val_frac=0.2)
    trainer = BCTrainer(tiny_policy, encoder, cfg)
    result = trainer.fit(dataset, verbose=False)
    assert result["val_accuracy"] > result["random_baseline"]
    assert len(result["history"]) == 15
    # loss 应下降
    first = result["history"][0]["train_loss"]
    last = result["history"][-1]["train_loss"]
    assert last <= first
    for row in result["history"]:
        for key in ("train_loss", "train_ce", "train_accuracy"):
            assert np.isfinite(row[key])
    # 训练后参数确实变了
    metrics = trainer.evaluate_dataset(dataset)
    assert metrics["accuracy"] > result["random_baseline"]


def test_bc_trainer_load_policy_teacher(encoder, tiny_policy, env) -> None:
    """用策略当教师（自蒸馏）走通一遍，验证协议适配。"""
    teacher = make_policy_teacher(tiny_policy, encoder, device="cpu", greedy=True)
    ds = collect_bc_dataset(env, teacher=teacher, episodes=2)
    assert len(ds) > 5
    trainer = BCTrainer(tiny_policy, encoder, BCConfig(epochs=2, batch_size=16, seed=0))
    result = trainer.fit(ds, verbose=False)
    assert np.isfinite(result["history"][0]["train_loss"])


def test_train_bc_end_to_end(encoder, tiny_policy, env, tmp_path) -> None:
    out = tmp_path / "bc_run"
    result = train_bc(
        env,
        tiny_policy,
        encoder,
        teacher=teacher_choose,
        episodes=5,
        config=BCConfig(epochs=6, batch_size=32, seed=0),
        out_dir=out,
        verbose=False,
    )
    assert (out / "policy_bc.pt").exists()
    assert (out / "bc_dataset.pkl").exists()
    assert (out / "bc_train_log.csv").exists()
    assert (out / "summary.json").exists()
    assert result["train_samples"] > 20
    assert result["val_accuracy"] > result["random_baseline"]
    # checkpoint 能加载并直接推理
    policy2, encoder2 = load_policy_and_encoder(out / "policy_bc.pt")
    assert policy2.meta["trainer"] == "bc"
    assert policy2.meta["bc_config"]["epochs"] == 6
    obs = random_observation(np.random.default_rng(0), card_ids=FAKE_CARD_IDS)
    batch = encoder2.collate([obs])
    policy2.eval()
    with torch.no_grad():
        actions, logp, value = policy2.act(batch, greedy=True)
        logits, _ = policy2(batch)
    assert int(actions[0]) < max(len(obs.candidates), 1)
    assert torch.isfinite(logits).all()
    assert torch.isfinite(logp).all() and torch.isfinite(value).all()
    # 数据集可从文件再加载
    ds = BCDataset.load(out / "bc_dataset.pkl")
    assert len(ds) == result["train_samples"] + result["val_samples"]


def test_bc_trainer_checkpoint_roundtrip(encoder, tiny_policy, dataset, tmp_path) -> None:
    trainer = BCTrainer(tiny_policy, encoder, BCConfig(epochs=2, batch_size=32, seed=0))
    trainer.fit(dataset, verbose=False)
    path = trainer.save_checkpoint(tmp_path / "bc.pt", meta={"note": "bc-test"})
    trainer2 = BCTrainer.load(path)
    assert trainer2.policy.meta["note"] == "bc-test"
    assert trainer2.policy.count_parameters() == tiny_policy.count_parameters()
    m1 = trainer.evaluate_dataset(dataset)
    m2 = trainer2.evaluate_dataset(dataset)
    assert pytest.approx(m1["accuracy"], abs=1e-6) == m2["accuracy"]
    assert pytest.approx(m1["loss"], abs=1e-5) == m2["loss"]


def test_bc_config_roundtrip() -> None:
    cfg = BCConfig(epochs=3, lr=1e-4, seed=5)
    assert BCConfig.from_dict(cfg.to_dict()) == cfg


def test_trainer_rejects_empty_dataset(encoder, tiny_policy) -> None:
    trainer = BCTrainer(tiny_policy, encoder, BCConfig(epochs=1))
    with pytest.raises(ValueError):
        trainer.fit(BCDataset(), verbose=False)
