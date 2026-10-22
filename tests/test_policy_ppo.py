"""PPO 训练管线测试：MockVecEnv / buffer+GAE / update / 冒烟训练 / checkpoint。"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from hsbg.env.spec import CANDIDATE_MAX, Observation, StepResult
from hsbg.policy.encoder import ENCODED_KEYS, CardVocab, ObservationEncoder
from hsbg.policy.model import PolicyConfig, build_policy, load_policy_and_encoder
from hsbg.policy.synthetic import FAKE_CARD_IDS, random_observation
from hsbg.train.buffer import RolloutBuffer
from hsbg.train.evaluate import (
    HeuristicAgent,
    RandomAgent,
    evaluate_agent,
    evaluate_policy,
    make_agent,
)
from hsbg.train.ppo import PPOConfig, PPOTrainer
from hsbg.train.vec_env import (
    MockVecEnv,
    SyncVecEnv,
    make_vec_env,
    normalize_step_result,
)


# ══════════════════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def encoder() -> ObservationEncoder:
    return ObservationEncoder(CardVocab(FAKE_CARD_IDS))


@pytest.fixture()
def env() -> MockVecEnv:
    e = MockVecEnv(
        2, seed=0, card_ids=FAKE_CARD_IDS,
        episode_steps_range=(6, 12), candidate_max=CANDIDATE_MAX + 4,
    )
    yield e
    e.close()


@pytest.fixture()
def tiny_policy(encoder):
    torch.manual_seed(0)
    cfg = PolicyConfig.for_encoder(encoder, dim=32, layers=1, heads=4, ff_dim=64)
    return build_policy(encoder, config=cfg)


def _make_batch(encoder: ObservationEncoder, n: int = 1):
    rng = np.random.default_rng(11)
    return encoder.collate(
        [random_observation(rng, card_ids=FAKE_CARD_IDS) for _ in range(n)]
    )


# ══════════════════════════════════════════════════════════════════════
# Mock / Sync 向量环境
# ══════════════════════════════════════════════════════════════════════


def test_mock_env_contract(env) -> None:
    obs_list = env.reset()
    assert env.num_envs == 2
    assert len(obs_list) == 2
    assert all(isinstance(o, Observation) for o in obs_list)
    actions = [0, 0]
    obs, rewards, dones, infos = env.step(actions)
    assert len(obs) == 2
    assert rewards.shape == (2,)
    assert dones.shape == (2,)
    assert len(infos) == 2
    assert all("reward" in info for info in infos)
    # 非法动作：不崩溃、info["invalid"]=True、episode 不结束
    obs, rewards, dones, infos = env.step([10 ** 6, -3])
    assert bool(infos[0]["invalid"]) and bool(infos[1]["invalid"])
    assert not bool(dones.any())


def test_mock_env_deterministic_by_seed() -> None:
    def rollout(seed: int):
        e = MockVecEnv(2, seed=seed, card_ids=FAKE_CARD_IDS,
                       episode_steps_range=(6, 10))
        obs = e.reset()
        records = []
        for _ in range(20):
            records.append(tuple(o.turn for o in obs))
            obs, rewards, dones, infos = e.step([0, 0])
            records.append(tuple(np.asarray(rewards).round(6).tolist()))
            records.append(tuple(bool(d) for d in dones))
        e.close()
        return records

    assert rollout(3) == rollout(3)


def test_mock_env_terminates_and_reports_rank() -> None:
    e = MockVecEnv(2, seed=0, card_ids=FAKE_CARD_IDS, episode_steps_range=(5, 8))
    e.reset()
    ranks = []
    for _ in range(100):
        _, _, dones, infos = e.step([0, 0])
        for i, done in enumerate(dones):
            if done:
                ranks.append(int(infos[i]["rank"]))
    e.close()
    assert len(ranks) >= 4
    assert all(1 <= r <= 8 for r in ranks)


class _FakeSingleEnv:
    """模拟真环境的单环境（5 元组返回，第 3 步 done）。"""

    def __init__(self) -> None:
        self.steps = 0
        self.closed = False
        self.obs = Observation(turn=1)

    def reset(self, seed=None) -> Observation:
        self.steps = 0
        self.obs = Observation(turn=1, log=f"reset:{seed}")
        return self.obs

    def step(self, action):
        self.steps += 1
        done = self.steps >= 3
        return StepResult(
            observation=Observation(turn=self.steps + 1),
            reward=1.0,
            terminated=done,
            truncated=False,
            info={"rank": 2} if done else {},
        )

    def close(self) -> None:
        self.closed = True


def test_sync_vec_env_adapter() -> None:
    env = SyncVecEnv([_FakeSingleEnv(), _FakeSingleEnv()], seeds=[0, 1])
    obs = env.reset()
    assert len(obs) == 2 and env.num_envs == 2
    all_dones = []
    for _ in range(3):
        obs, rewards, dones, infos = env.step([0, 1])
        all_dones.append(list(dones))
        assert len(obs) == 2
        assert np.allclose(rewards, 1.0)
    assert all_dones == [[False, False], [False, False], [True, True]]
    # auto-reset：done 之后返回的是新局观测
    assert obs[0].turn == 1
    env.close()
    assert all(e.closed for e in env.envs)


def test_normalize_step_result_variants() -> None:
    obs = Observation(turn=3)
    r = normalize_step_result(StepResult(obs, 1.5, True, False, {"rank": 1}))
    assert r[0] is obs and r[1] == 1.5 and r[2] and not r[3] and r[4]["rank"] == 1
    r = normalize_step_result((obs, 0.5, True, False, {"rank": 2}))
    assert r[1] == 0.5 and r[2] and not r[3]
    r = normalize_step_result((obs, 0.5, True, {"rank": 3}))
    assert r[2] and not r[3] and r[4]["rank"] == 3
    with pytest.raises(TypeError):
        normalize_step_result("nope")


def test_make_vec_env_mock_mode() -> None:
    env = make_vec_env(2, mode="mock", seed=0)
    assert isinstance(env, MockVecEnv)
    obs = env.reset()
    assert len(obs) == 2
    env.close()


# ══════════════════════════════════════════════════════════════════════
# Buffer / GAE
# ══════════════════════════════════════════════════════════════════════


def test_buffer_flatten_and_minibatches(encoder, tiny_policy) -> None:
    env = MockVecEnv(2, seed=0, card_ids=FAKE_CARD_IDS, episode_steps_range=(5, 9))
    trainer = PPOTrainer(tiny_policy, encoder, PPOConfig(n_steps=8, seed=1))
    buf, obs_list, stats = trainer.collect_rollout(env, env.reset(), n_steps=8)
    env.close()
    assert len(buf) == 8
    assert len(obs_list) == 2
    assert torch.isfinite(buf.advantages).all()
    assert torch.isfinite(buf.returns).all()
    data = buf.flatten()
    assert data["actions"].shape == (16,)
    assert data["advantages"].shape == (16,)
    for key in ENCODED_KEYS:
        assert data["obs"][key].shape[0] == 16
    sizes = []
    for mb in buf.iterate_minibatches(8, generator=torch.Generator().manual_seed(0)):
        sizes.append(int(mb["actions"].shape[0]))
        assert torch.isfinite(mb["advantages"]).all()
    assert sum(sizes) == 16
    assert all(s <= 8 for s in sizes)
    # 统计量有限
    for key, value in stats.items():
        assert np.isfinite(value), key


def test_gae_matches_manual_computation(encoder) -> None:
    buf = RolloutBuffer(n_steps=3, num_envs=1, device="cpu")
    obs_batch = _make_batch(encoder, n=1)
    values = [1.0, 2.0, 3.0]
    rewards = [0.5, -0.2, 1.0]
    dones = [0.0, 0.0, 1.0]
    for t in range(3):
        buf.add(
            obs_batch,
            actions=torch.tensor([0]),
            logp=torch.tensor([-1.0]),
            values=torch.tensor([values[t]]),
            rewards=np.asarray([rewards[t]]),
            dones=np.asarray([dones[t]]),
            infos=[{}],
        )
    gamma, lam = 0.9, 0.8
    adv, ret = buf.compute_gae(torch.tensor([10.0]), gamma=gamma, lam=lam)
    # 手算：v3 后 done，不 bootstrap
    gae2 = rewards[2] - values[2]  # -2.0
    gae1 = rewards[1] + gamma * values[2] - values[1] + gamma * lam * gae2
    gae0 = rewards[0] + gamma * values[1] - values[0] + gamma * lam * gae1
    expected = torch.tensor([[gae0], [gae1], [gae2]])
    assert torch.allclose(adv, expected, atol=1e-6)
    assert torch.allclose(ret, expected + torch.tensor(values).unsqueeze(-1), atol=1e-6)
    buf.normalize_advantages()
    assert abs(float(buf.advantages.mean())) < 1e-5
    assert torch.isfinite(buf.advantages).all()


def test_buffer_empty_errors() -> None:
    buf = RolloutBuffer(n_steps=2, num_envs=1)
    with pytest.raises(RuntimeError):
        buf.compute_gae(torch.zeros(1))
    with pytest.raises(RuntimeError):
        buf.flatten()


# ══════════════════════════════════════════════════════════════════════
# PPO 更新 / 训练
# ══════════════════════════════════════════════════════════════════════


def test_ppo_update_changes_parameters(encoder, tiny_policy, env) -> None:
    cfg = PPOConfig(
        lr=3e-3, n_steps=16, epochs=2, minibatch_size=16,
        target_kl=1.0, seed=0, device="cpu",
    )
    trainer = PPOTrainer(tiny_policy, encoder, cfg)
    before = [p.detach().clone() for p in tiny_policy.parameters()]
    buf, _, _ = trainer.collect_rollout(env, env.reset(), n_steps=16)
    stats = trainer.update(buf)
    changed = any(
        not torch.allclose(b, p.detach()) for b, p in zip(before, tiny_policy.parameters())
    )
    assert changed
    for key in ("policy_loss", "value_loss", "rank_ce", "entropy",
                "approx_kl", "clipfrac", "grad_norm", "lr"):
        assert key in stats
        assert np.isfinite(stats[key]), key
    assert stats["entropy"] >= 0.0
    assert 0.0 <= stats["clipfrac"] <= 1.0
    # 更新后继续采集仍然正常
    buf2, _, _ = trainer.collect_rollout(env, env.reset(), n_steps=8)
    assert torch.isfinite(buf2.advantages).all()


def test_rejected_action_guard(encoder, tiny_policy) -> None:
    """引擎拒绝某个候选时必须屏蔽该动作，避免"拒绝→同一动作"死循环。"""
    from hsbg.train.ppo import _obs_key

    obs = random_observation(np.random.default_rng(0), card_ids=FAKE_CARD_IDS)
    trainer = PPOTrainer(tiny_policy, encoder, PPOConfig(n_steps=4, seed=0))
    trainer._reset_banned(1)
    batch = encoder.collate([obs])
    key = _obs_key(obs)
    assert int(batch["cand_mask"].sum(-1)[0]) == min(len(obs.candidates), CANDIDATE_MAX)
    trainer._remember_rejected(0, key, 1)
    trainer._apply_rejected_mask(batch, [key])
    assert float(batch["cand_mask"][0, 1]) == 0.0
    # 观测变化后屏蔽自动失效
    trainer._apply_rejected_mask(encoder.collate([obs]), [("different",)])
    assert trainer._banned[0] is None
    # 全部候选都被拒的极端情况：仍保留一个可选动作，不死锁
    batch = encoder.collate([obs])
    n_valid = int(batch["cand_mask"].sum(-1)[0])
    for a in range(n_valid):
        trainer._remember_rejected(0, key, a)
    trainer._apply_rejected_mask(batch, [key])
    assert float(batch["cand_mask"][0].sum()) == 1.0


def test_ppo_short_run_changes_and_records(encoder, tmp_path) -> None:
    """两次相同 seed 的短训练：loss 曲线应完全一致（可复现）。"""
    from hsbg.train.setup import seed_everything

    cfg = PPOConfig(n_steps=16, epochs=1, minibatch_size=16, seed=7, device="cpu")
    results = []
    for i in range(2):
        seed_everything(7)
        policy = build_policy(encoder, config=PolicyConfig.for_encoder(
            encoder, dim=32, layers=1, heads=4, ff_dim=64))
        trainer = PPOTrainer(policy, encoder, cfg)
        run_env = MockVecEnv(2, seed=0, card_ids=FAKE_CARD_IDS,
                             episode_steps_range=(6, 10))
        out = tmp_path / f"run{i}"
        result = trainer.train(run_env, total_steps=64, out_dir=out, verbose=False)
        run_env.close()
        results.append([
            (row["policy_loss"], row["value_loss"], row["entropy"])
            for row in result["history"]
        ])
    assert results[0] == results[1]


def test_ppo_train_smoke_artifacts_and_reload(encoder, tiny_policy, env, tmp_path) -> None:
    cfg = PPOConfig(
        lr=1e-3, n_steps=16, epochs=2, minibatch_size=16,
        target_kl=1.0, seed=0, device="cpu",
    )
    out = tmp_path / "run"
    trainer = PPOTrainer(tiny_policy, encoder, cfg)
    result = trainer.train(env, total_steps=128, out_dir=out, verbose=False)
    assert result["steps"] >= 128
    assert (out / "policy_final.pt").exists()
    assert (out / "train_log.csv").exists()
    assert (out / "summary.json").exists()
    history = result["history"]
    assert len(history) >= 1
    for row in history:
        for key in ("policy_loss", "value_loss", "entropy", "approx_kl", "step"):
            assert np.isfinite(float(row[key])), key
    # checkpoint 可再加载并复现输出
    policy2, encoder2 = load_policy_and_encoder(out / "policy_final.pt")
    assert policy2.count_parameters() == tiny_policy.count_parameters()
    batch = _make_batch(encoder2, n=4)
    tiny_policy.eval()
    policy2.eval()
    with torch.no_grad():
        logits_a, value_a = tiny_policy(batch)
        logits_b, value_b = policy2(batch)
    assert torch.allclose(logits_a, logits_b, atol=1e-6)
    assert torch.allclose(value_a, value_b, atol=1e-6)
    # 续训入口
    trainer2 = PPOTrainer.load(out / "policy_final.pt", device="cpu")
    assert isinstance(trainer2, PPOTrainer)
    assert trainer2.config.n_steps == cfg.n_steps


def test_ppo_checkpoint_has_metadata(encoder, tiny_policy, env, tmp_path) -> None:
    trainer = PPOTrainer(tiny_policy, encoder, PPOConfig(n_steps=8, seed=3, device="cpu"))
    trainer.train(env, total_steps=16, out_dir=tmp_path, verbose=False)
    policy, _ = load_policy_and_encoder(tmp_path / "policy_final.pt")
    meta = policy.meta
    assert meta["trainer"] == "ppo"
    assert meta["seed"] == 3
    assert "ppo_config" in meta
    assert meta["ppo_config"]["n_steps"] == 8


# ══════════════════════════════════════════════════════════════════════
# 评测
# ══════════════════════════════════════════════════════════════════════


def test_evaluate_policy_and_baselines(encoder, tiny_policy) -> None:
    env = MockVecEnv(2, seed=0, card_ids=FAKE_CARD_IDS, episode_steps_range=(5, 10))
    result = evaluate_policy(tiny_policy, encoder, env, games=4, device="cpu")
    env.close()
    assert result.games >= 4
    assert 1.0 <= result.mean_rank <= 8.0
    assert 0.0 <= result.win_rate <= 1.0
    assert result.mean_steps > 0

    env = MockVecEnv(2, seed=1, card_ids=FAKE_CARD_IDS, episode_steps_range=(5, 10))
    random_agent = make_agent("random", seed=0)
    r1 = evaluate_agent(random_agent, env, games=4, seed=1)
    heuristic = HeuristicAgent(seed=0)
    r2 = evaluate_agent(heuristic, env, games=4, seed=1)
    env.close()
    for r in (r1, r2):
        assert r.games >= 4
        assert 1.0 <= r.mean_rank <= 8.0
        for v in (r.mean_return, r.mean_steps):
            assert np.isfinite(v)


def test_evaluate_agent_timeout_guard() -> None:
    """策略不会 end_turn 时必须由超时保护终止评测（returns 有限、有负场）。"""

    class _LoopPolicy:
        name = "loop"

        def act(self, obs_list):
            # 永远选第一个候选（模拟陷入循环）
            return [0 for _ in obs_list]

    env = MockVecEnv(2, seed=0, card_ids=FAKE_CARD_IDS, episode_steps_range=(1000, 1001))
    try:
        result = evaluate_agent(
            _LoopPolicy(), env, games=2, max_steps_per_episode=50
        )
    finally:
        env.close()
    assert result.games >= 1
    assert result.timeout_games >= 1
    assert result.mean_rank == 8.0


def test_agent_factories() -> None:
    assert isinstance(make_agent("random", seed=0), RandomAgent)
    assert isinstance(make_agent("heuristic", seed=0), HeuristicAgent)
    with pytest.raises(ValueError):
        make_agent("not-an-agent")
    # HeuristicAgent 有死循环保护状态且可重置
    agent = HeuristicAgent(seed=0)
    agent.reset()
    assert agent.name == "heuristic"
