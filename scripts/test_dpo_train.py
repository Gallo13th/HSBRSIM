"""upgrade 子集 DPO 接入 PPO 训练循环（``hsbg.az.train.ppo`` / ``ppo_trainer``）单测。

覆盖：

1. 配置：``dpo_*`` 默认值、``dpo_coef>=0``/``dpo_beta>0``/``dpo_batch>0``/``dpo_every>=1``
   的构造期校验；
2. ``dpo_coef=0`` 逐位等价：同 seed 下与「未接 DPO」的训练产出**逐字节相同**的
   ``model.pt``（SHA256 相同），且 stats/config 回显里不出现任何 ``dpo_*`` 键；
3. DPO 梯度口径：``coef * L_dpo`` 恰好落到参数上（PPO 项梯度为 0 时手算对照），
   并验证 ``grad_accum>1`` 时的 ``total/len(slices)`` 补偿；
4. ``dpo_coef>0``：stats 出现 ``dpo_loss/dpo_coef/dpo_accept_rate/dpo_samples``；
5. 池为空 / 池加载失败：自动跳过（不报错、不改权重、stats 无 ``dpo_*``）；
6. ``PPOTrainer``：``dpo_every`` 按 **iteration** 计数，DPO 采样用独立 RNG
   （不改变 PPO 的 permutation 序列）。
"""

from __future__ import annotations

import copy
import hashlib

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS  # noqa: E402
from hsbg.az.train.dpo_upgrade import (  # noqa: E402
    UPGRADE_ACTION,
    UpgradeSamples,
    dpo_pair_loss,
)
from hsbg.az.train.ppo import PPOBatch, PPOConfig, train_ppo  # noqa: E402
from hsbg.az.train.ppo_trainer import PPOTrainer  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
# 最小模型 / PPO 批次 / upgrade 池
# ══════════════════════════════════════════════════════════════════════════
class _TinyNet(torch.nn.Module):
    """tiny 结构（不吃 mask 之外的头）：forward -> (policy, rank, value)。"""

    def __init__(self, hidden: int = 16) -> None:
        super().__init__()
        self.fc = torch.nn.Linear(OBS_FLOATS, hidden)
        self.policy = torch.nn.Linear(hidden, N_ACTIONS)
        self.rank = torch.nn.Linear(hidden, 8)
        self.value = torch.nn.Linear(hidden, 1)
        # 默认让 action 10 明显高于 upgrade(=3)：保证 DPO 的 rejected != chosen
        with torch.no_grad():
            self.policy.bias.zero_()
            self.policy.bias[10] = 5.0

    def forward(self, features, cards=None, mask=None):
        h = torch.relu(self.fc(features))
        return self.policy(h), self.rank(h), torch.tanh(self.value(h)).squeeze(-1)


def _model(seed: int = 0) -> _TinyNet:
    torch.manual_seed(int(seed))
    return _TinyNet()


def _ppo_batch(n: int = 8, seed: int = 0) -> PPOBatch:
    rng = np.random.default_rng(int(seed))
    masks = rng.random((n, N_ACTIONS)) < 0.3
    masks[:, 0] = True
    masks[:, UPGRADE_ACTION] = True
    masks[:, 10] = True
    actions = np.array([rng.choice(np.flatnonzero(m)) for m in masks], dtype=np.int64)
    ep_len = 4
    dones = np.zeros(n, dtype=np.float32)
    dones[ep_len - 1::ep_len] = 1.0
    dones[-1] = 1.0
    return PPOBatch(
        features=(0.1 * rng.standard_normal((n, OBS_FLOATS))).astype(np.float32),
        cards=rng.integers(0, 400, (n, OBS_CARDS), dtype=np.int16),
        masks=masks, actions=actions,
        old_logprobs=np.full(n, -4.0, dtype=np.float32),
        values=rng.standard_normal(n).astype(np.float32),
        rewards=rng.standard_normal(n).astype(np.float32),
        dones=dones,
        advantages=rng.standard_normal(n).astype(np.float32),
        returns=rng.standard_normal(n).astype(np.float32),
        seats=(np.arange(n) % 8).astype(np.int32),
        game_ids=(np.arange(n) // ep_len).astype(np.int64),
        ranks=rng.integers(1, 9, n).astype(np.int64),
        turns=(np.arange(n) % ep_len).astype(np.int32),
        target_pi=np.zeros((n, N_ACTIONS), dtype=np.float32),
        has_pi=np.zeros(n, dtype=bool),
        episode_ids=(np.arange(n) // ep_len).astype(np.int32),
        forced=np.zeros(n, dtype=bool),
    )


def _pool(n: int = 32, seed: int = 1) -> UpgradeSamples:
    rng = np.random.default_rng(int(seed))
    mask = np.zeros((n, N_ACTIONS), dtype=bool)
    for a in (0, UPGRADE_ACTION, 10):
        mask[:, int(a)] = True
    return UpgradeSamples(
        features=(0.1 * rng.standard_normal((n, OBS_FLOATS))).astype(np.float32),
        cards=rng.integers(0, 400, (n, OBS_CARDS), dtype=np.int64),
        action_index=np.full(n, UPGRADE_ACTION, dtype=np.int64),
        action_mask=mask,
        tier=rng.integers(2, 6, n).astype(np.int16),
        turn=rng.integers(1, 20, n).astype(np.int16),
        mmr=rng.integers(6000, 9000, n).astype(np.int32),
        tier_known=np.ones(n, dtype=bool),
        turn_known=np.ones(n, dtype=bool),
        path="<unit>",
    )


def _cfg(**kw) -> PPOConfig:
    base = dict(epochs=1, minibatch=4, lr=1e-3, seed=0, device="cpu",
                target_kl=0.0, amp="off", compile_train=0, value_loss="rank",
                pi_coef=0.0, entropy_coef=0.0, max_grad_norm=1e9)
    base.update(kw)
    return PPOConfig(**base)


def _sha256_state(model: torch.nn.Module, path) -> str:
    """把 state_dict 存成 model.pt 并返回文件 SHA256（逐位等价判据）。"""
    torch.save(model.state_dict(), str(path))
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ══════════════════════════════════════════════════════════════════════════
# 1. 配置默认值 / 校验
# ══════════════════════════════════════════════════════════════════════════
def test_dpo_config_defaults_and_validation():
    cfg = PPOConfig()
    assert cfg.dpo_coef == 0.0
    assert cfg.dpo_beta == pytest.approx(0.1)
    assert cfg.dpo_batch == 128
    assert cfg.dpo_every == 4
    assert cfg.dpo_samples == "data/firestone_bc/bc_samples.jsonl.gz"
    for kw in (dict(dpo_coef=-1e-3), dict(dpo_beta=0.0), dict(dpo_beta=-0.1),
               dict(dpo_beta=float("nan")), dict(dpo_batch=0), dict(dpo_every=0)):
        with pytest.raises(ValueError):
            PPOConfig(**kw)


# ══════════════════════════════════════════════════════════════════════════
# 2. dpo_coef=0 逐位等价
# ══════════════════════════════════════════════════════════════════════════
def test_dpo_coef_zero_is_bitwise_identical(tmp_path):
    pool = _pool(16)
    batch = _ppo_batch(16)

    def run(cfg, dpo_batch):
        model = _model(seed=5)
        # 同 seed、同 batch、同 rng：唯一差别是是否传入 DPO 池/批次
        train_ppo(model, copy.deepcopy(batch), cfg,
                  rng=np.random.default_rng(5), dpo_batch=dpo_batch)
        return model

    base = run(_cfg(), None)
    zero = run(_cfg(dpo_coef=0.0, dpo_batch=128), pool)
    # 同一个文件名（torch.save 的 zip 前缀含文件名，必须同路径才逐字节可比）
    p = tmp_path / "model.pt"
    h0 = _sha256_state(base, p)
    h1 = _sha256_state(zero, p)
    assert h0 == h1, "dpo_coef=0 必须与未接 DPO 的训练逐位等价"

    # stats / config 回显里不能出现任何 dpo_* 键
    stats = train_ppo(_model(seed=5), copy.deepcopy(batch),
                      _cfg(dpo_coef=0.0, dpo_batch=128),
                      rng=np.random.default_rng(5), dpo_batch=pool)
    assert not any(k.startswith("dpo_") for k in stats), sorted(stats)
    assert not any(k.startswith("dpo_") for k in stats["config"])


# ══════════════════════════════════════════════════════════════════════════
# 3. DPO 梯度口径（含 grad_accum 补偿）
# ══════════════════════════════════════════════════════════════════════════
def _dpo_only_step(coef: float, accum: int):
    """PPO 项梯度为 0（adv=0、value_coef=0）时，一步 SGD 的参数增量。"""
    pool = _pool(24, seed=2)
    dpo = pool.take(np.arange(8, dtype=np.int64))
    batch = _ppo_batch(4, seed=3)
    batch.advantages[:] = 0.0
    model = _model(seed=7)
    cfg = _cfg(minibatch=(4 if accum == 1 else 2), grad_accum=accum,
               value_coef=0.0, dpo_coef=float(coef))
    opt = torch.optim.SGD(model.parameters(), lr=1.0, momentum=0.0)
    before = {k: v.detach().clone() for k, v in model.state_dict().items()}
    stats = train_ppo(model, batch, cfg, optimizer=opt,
                      rng=np.random.default_rng(0), dpo_batch=dpo)
    assert "dpo_loss" in stats
    delta = {k: model.state_dict()[k].detach() - before[k]
             for k in before}
    return model, dpo, delta, stats


def test_dpo_gradient_matches_coef_times_pair_loss():
    coef = 0.125
    # 手算：coef * ∇L_dpo（模型副本、同一批样本）
    ref = _model(seed=7)
    ref.eval()
    loss, rate = dpo_pair_loss(ref, _pool(24, seed=2).take(
        np.arange(8, dtype=np.int64)), 0.1)
    assert rate == pytest.approx(1.0)  # argmax=10 != chosen=3 -> 全部接受
    loss.backward()
    manual = {k: float(coef) * v.grad.detach() if v.grad is not None
              else torch.zeros_like(v) for k, v in ref.named_parameters()}

    for accum in (1, 2):
        model, _dpo, delta, _stats = _dpo_only_step(coef, accum)
        for name, d in delta.items():
            # SGD(lr=1) 且只有 DPO 梯度：Δθ = -coef·∇L_dpo（两种 accum 完全一致）
            assert torch.allclose(d, -manual[name], atol=1e-6, rtol=1e-5), \
                (accum, name, float(d.abs().max()), float(manual[name].abs().max()))


# ══════════════════════════════════════════════════════════════════════════
# 4. coef>0：stats 出现 + 参数确实被更新
# ══════════════════════════════════════════════════════════════════════════
def test_dpo_positive_coef_stats_and_update():
    pool = _pool(64, seed=4)
    dpo = pool.take(np.arange(32, dtype=np.int64))
    batch = _ppo_batch(16, seed=6)
    model = _model(seed=9)
    before = {k: v.detach().clone() for k, v in model.state_dict().items()}
    stats = train_ppo(model, copy.deepcopy(batch),
                      _cfg(dpo_coef=0.005, dpo_batch=32, dpo_every=4),
                      rng=np.random.default_rng(0), dpo_batch=dpo)
    assert stats["dpo_coef"] == pytest.approx(0.005)
    assert stats["dpo_beta"] == pytest.approx(0.1)
    assert stats["dpo_every"] == 4
    assert stats["dpo_samples"] == pytest.approx(32.0)
    assert stats["dpo_steps"] == 1
    assert 0.0 <= stats["dpo_accept_rate"] <= 1.0
    assert stats["dpo_loss"] >= 0.0
    changed = [k for k, v in model.state_dict().items()
               if not torch.equal(v.detach(), before[k])]
    assert changed, "dpo_coef>0 应该产生参数更新"


# ══════════════════════════════════════════════════════════════════════════
# 5. 池为空 / 加载失败：自动跳过
# ══════════════════════════════════════════════════════════════════════════
def _empty_pool() -> UpgradeSamples:
    return UpgradeSamples(
        features=np.zeros((0, OBS_FLOATS), dtype=np.float32),
        cards=np.zeros((0, OBS_CARDS), dtype=np.int64),
        action_index=np.zeros(0, dtype=np.int64),
        action_mask=np.zeros((0, N_ACTIONS), dtype=bool),
        tier=np.zeros(0, dtype=np.int16), turn=np.zeros(0, dtype=np.int16),
        mmr=np.zeros(0, dtype=np.int32), tier_known=np.zeros(0, dtype=bool),
        turn_known=np.zeros(0, dtype=bool), path="<empty>")


def test_ppo_trainer_skips_when_pool_empty(tmp_path):
    batch = _ppo_batch(8, seed=8)
    cfg = _cfg(dpo_coef=0.01, dpo_batch=4, dpo_every=1)
    cfg0 = _cfg(dpo_coef=0.0, dpo_batch=4, dpo_every=1)

    base = PPOTrainer(_model(seed=3), cfg0)          # 未接 DPO 的基线
    skipped = PPOTrainer(_model(seed=3), cfg, dpo_pool=_empty_pool())
    assert len(skipped.dpo_pool) == 0
    stats0 = base.update(copy.deepcopy(batch))
    stats1 = skipped.update(copy.deepcopy(batch))
    assert "dpo_loss" not in stats1
    assert not any(k.startswith("dpo_") for k in stats1)
    # 池空 = 完全不参与：参数与 baseline 逐位一致
    p = tmp_path / "model.pt"
    h0 = _sha256_state(base.model, p)
    h1 = _sha256_state(skipped.model, p)
    assert h0 == h1
    # baseline（无池）同样不含 dpo 键
    assert not any(k.startswith("dpo_") for k in stats0)


def test_ppo_trainer_disables_dpo_when_pool_load_fails(tmp_path, capsys):
    cfg = _cfg(dpo_coef=0.01, dpo_batch=4, dpo_every=1,
               dpo_samples=str(tmp_path / "missing.jsonl.gz"))
    trainer = PPOTrainer(_model(seed=3), cfg)
    assert trainer.dpo_pool is None
    assert trainer.config.dpo_coef == 0.0          # 自动关闭
    stats = trainer.update(_ppo_batch(8, seed=8))
    assert "dpo_loss" not in stats
    assert "[ppo][warn] upgrade DPO 样本加载失败" in capsys.readouterr().out


# ══════════════════════════════════════════════════════════════════════════
# 6. PPOTrainer：dpo_every 按 iteration 计 + 独立 RNG
# ══════════════════════════════════════════════════════════════════════════
def test_ppo_trainer_dpo_every_counts_iterations():
    batch = _ppo_batch(8, seed=11)
    cfg = _cfg(dpo_coef=0.01, dpo_batch=4, dpo_every=2)
    trainer = PPOTrainer(_model(seed=4), cfg, dpo_pool=_pool(32, seed=12))
    fired = [("dpo_loss" in trainer.update(copy.deepcopy(batch)))
             for _ in range(4)]
    # updates = 0,2 才做 DPO（iteration 级周期）
    assert fired == [True, False, True, False]

    # 独立 RNG：DPO 开启/跳过都不改变 PPO 的 permutation 序列
    cfg0 = _cfg(dpo_coef=0.0, dpo_batch=4, dpo_every=2)
    t0 = PPOTrainer(_model(seed=4), cfg0, dpo_pool=_pool(32, seed=12))
    t1 = PPOTrainer(_model(seed=4), cfg, dpo_pool=_pool(32, seed=12))
    t0.update(copy.deepcopy(batch))
    t1.update(copy.deepcopy(batch))
    assert (t0.rng.bit_generator.state["state"]["state"]
            == t1.rng.bit_generator.state["state"]["state"])
    # dpo_rng 只在 DPO 步前进；bc_rng 完全不受影响
    assert t0.dpo_rng.bit_generator.state["state"]["state"] \
        != t1.dpo_rng.bit_generator.state["state"]["state"]
