"""训练侧 ``torch.compile``（``PPOConfig.compile_train``）单测。

覆盖：

1. 配置规范化：``compile_train`` 只接受 0|1|2，``True→1``；0 时 ``build_train_forward``
   返回 ``None``（纯 eager，零开销）；
2. 数值等价：同一 checkpoint（同 seed 初始化）下 ``compile_train=0`` 与 ``=1`` 跑 1 个
   epoch，loss 数值与参数更新近似一致（1e-4 级）；
3. seq 辅助头路径（``forward_aux`` + ``seq_coef>0``）同样等价；
4. 尾批路由：``B == minibatch`` 走编译图，尾批 ``B < minibatch`` 走 eager（避免动态
   形状触发重编译）；
5. 回退：monkeypatch 让 ``torch.compile`` 抛异常时，训练照常完成、只 warn 一次、
   ``compile_active=False``、参数确实被更新。

这些用例用 CPU 小模型（tiny MLP + 4 输出 aux 头），不依赖引擎/GPU；CPU 上 inductor
同样会走一遍编译（比 GPU 慢几秒），因此只跑 1 个 epoch、16-20 条样本。
"""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from hsbg.az.train.ppo import (  # noqa: E402
    N_ACTIONS,
    OBS_CARDS,
    OBS_FLOATS,
    PPOBatch,
    PPOConfig,
    TrainForward,
    build_train_forward,
    compile_train_mode,
    train_ppo,
)


class _TinyTrainNet(torch.nn.Module):
    """最小 4 输出网络：``forward`` -> 3 元组，``forward_aux`` -> 4 元组（模仿 entity）。"""

    def __init__(self, hidden: int = 32) -> None:
        super().__init__()
        self.fc = torch.nn.Linear(OBS_FLOATS, hidden)
        self.policy = torch.nn.Linear(hidden, N_ACTIONS)
        self.rank = torch.nn.Linear(hidden, 8)
        self.value = torch.nn.Linear(hidden, 1)
        self.seq = torch.nn.Linear(hidden, N_ACTIONS)

    def _trunk(self, features):
        return torch.relu(self.fc(features))

    def forward(self, features, cards=None, mask=None):
        h = self._trunk(features)
        return self.policy(h), self.rank(h), torch.tanh(self.value(h)).squeeze(-1)

    def forward_aux(self, features, cards=None, mask=None):
        h = self._trunk(features)
        return (self.policy(h), self.rank(h),
                torch.tanh(self.value(h)).squeeze(-1), self.seq(h))


def _make_model(seed: int = 0) -> _TinyTrainNet:
    torch.manual_seed(int(seed))
    return _TinyTrainNet()


def _make_batch(n: int = 20, seed: int = 0, seq: bool = False) -> PPOBatch:
    """合法 PPO 批次：每 episode 一个 done、动作在 mask 内、ranks 1..8。"""
    rng = np.random.default_rng(int(seed))
    masks = rng.random((n, N_ACTIONS)) < 0.3
    masks[:, 0] = True
    actions = np.array([rng.choice(np.flatnonzero(m)) for m in masks], dtype=np.int64)
    ep_len = 5
    episode_ids = (np.arange(n) // ep_len).astype(np.int32)
    dones = np.zeros(n, dtype=np.float32)
    dones[ep_len - 1::ep_len] = 1.0
    dones[-1] = 1.0
    seq_target = None
    if seq:
        seq_target = (rng.random((n, N_ACTIONS)) < 0.02).astype(np.uint8)
        seq_target[np.arange(n), actions] = 1  # 标签必须包含本步动作
    return PPOBatch(
        features=(0.1 * rng.standard_normal((n, OBS_FLOATS))).astype(np.float32),
        cards=rng.integers(0, 400, (n, OBS_CARDS), dtype=np.int16),
        masks=masks,
        actions=actions,
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
        episode_ids=episode_ids,
        forced=np.zeros(n, dtype=bool),
        seq_target=seq_target,
    )


def _cfg(compile_train: int, **kw) -> PPOConfig:
    base = dict(epochs=1, minibatch=8, lr=1e-3, seed=0, device="cpu",
                target_kl=0.0, amp="off", compile_train=compile_train)
    base.update(kw)
    return PPOConfig(**base)


# ── 1. 配置 ────────────────────────────────────────────────────────────────
def test_compile_train_config_normalization():
    assert PPOConfig().compile_train == 0
    assert PPOConfig(compile_train=True).compile_train == 1
    assert PPOConfig(compile_train=1).compile_train == 1
    assert PPOConfig(compile_train=2).compile_train == 2
    assert compile_train_mode(False) == 0
    with pytest.raises(ValueError):
        PPOConfig(compile_train=3)
    # 0 = 纯 eager：不构造包装对象
    assert build_train_forward(_make_model(), _cfg(0), warmup=False) is None


# ── 2. 数值等价（主前向）──────────────────────────────────────────────────
def test_compile_train_matches_eager():
    batch = _make_batch(n=20)
    model0 = _make_model(0)
    model1 = _make_model(0)
    model1.load_state_dict(model0.state_dict())

    base = train_ppo(model0, batch, _cfg(0))
    comp = train_ppo(model1, batch, _cfg(1))
    assert comp["compile_active"] is True
    assert comp["compile"]["main_compiled"] is True
    assert comp["compile"]["warnings"] == []

    # 1 个 epoch、2 个满 minibatch + 1 个尾批（走 eager）
    assert comp["compile"]["compiled_calls"] == 2
    assert comp["compile"]["eager_calls"] == 1
    assert base["updates"] == comp["updates"] > 0

    b, c = base["epochs"][0], comp["epochs"][0]
    for key in ("total", "policy_loss", "value_loss", "entropy", "approx_kl"):
        assert abs(c[key] - b[key]) <= 1e-4, (key, b[key], c[key])
    for p0, p1 in zip(model0.parameters(), model1.parameters()):
        assert torch.allclose(p0, p1, atol=1e-4, rtol=0.0), (
            f"参数更新不一致: max|Δ|={float((p0 - p1).abs().max()):.2e}")


# ── 3. 数值等价（seq 辅助头 / forward_aux 路径）───────────────────────────
def test_compile_train_aux_matches_eager():
    batch = _make_batch(n=16, seq=True)
    model0 = _make_model(1)
    model1 = _make_model(1)
    model1.load_state_dict(model0.state_dict())

    base = train_ppo(model0, batch, _cfg(0, seq_coef=0.02))
    comp = train_ppo(model1, batch, _cfg(1, seq_coef=0.02))
    assert comp["compile_active"] is True
    assert comp["compile"]["aux_compiled"] is True

    b, c = base["epochs"][0], comp["epochs"][0]
    assert "seq_loss" in b and "seq_loss" in c
    for key in ("total", "policy_loss", "seq_loss"):
        assert abs(c[key] - b[key]) <= 1e-4, (key, b[key], c[key])
    for p0, p1 in zip(model0.parameters(), model1.parameters()):
        assert torch.allclose(p0, p1, atol=1e-4, rtol=0.0)


# ── 4. 尾批路由（固定形状，不因尾批重编译）────────────────────────────────
def test_compile_tail_batch_uses_eager():
    model = _make_model(2)
    cfg = _cfg(1, minibatch=8)
    tf = build_train_forward(model, cfg)
    assert isinstance(tf, TrainForward) and tf.main_compiled

    x = torch.zeros(8, OBS_FLOATS)
    c = torch.zeros(8, OBS_CARDS, dtype=torch.long)
    m = torch.ones(8, N_ACTIONS, dtype=torch.bool)
    tf.main(x, c, m)
    assert tf.compiled_calls == 1 and tf.eager_calls == 0

    # 尾批：B != minibatch -> 直接 eager（不触发第二次编译）
    x4 = torch.zeros(4, OBS_FLOATS)
    tf.main(x4, c[:4], m[:4])
    assert tf.compiled_calls == 1 and tf.eager_calls == 1


# ── 5. 编译失败自动回退 eager（只 warn 一次，训练继续）───────────────────
def test_compile_failure_falls_back(monkeypatch, capsys):
    model = _make_model(3)
    batch = _make_batch(n=16)
    before = [p.detach().clone() for p in model.parameters()]

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated compile failure")

    monkeypatch.setattr(torch, "compile", _boom)
    stats = train_ppo(model, batch, _cfg(1))

    assert stats["compile_active"] is False
    assert stats["compile"]["main_compiled"] is False
    assert stats["updates"] > 0
    out = capsys.readouterr().out
    assert "回退 eager" in out
    assert "simulated compile failure" in out
    # 同一路径只 warn 一次
    assert out.count("torch.compile 训练前向（main）") == 1
    # 回退后训练仍然真的更新了参数
    assert any(not torch.equal(a, b) for a, b in zip(before, model.parameters()))
