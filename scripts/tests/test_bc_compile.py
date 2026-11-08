"""分层 BC 的 ``torch.compile`` 接线、``--bc-every`` 周期与等价性单测。

覆盖：

1. ``bc_batch`` 默认 128 / ``bc_every`` 默认 1，非法 ``bc_every`` 构造期失败；
2. `--bc-every N`：只在第 0, N, 2N... 个 PPO 微批做 BC，``bc_coef`` 按 N 折算；
   跳过步的其他 loss 与 ``bc_coef=0`` 逐位一致（BC 采样用独立 RNG，不扰动 PPO 序列）；
3. ``TrainForward`` 单独编译 BC 固定形状图（``bc_compiled``/``bc_size``），
   形状不符自动走 eager；编译失败只 warn 一次并回退 eager；
4. 编译 BC 与 eager BC 的 loss/参数更新数值一致（CPU tiny，1 epoch）。
"""

from __future__ import annotations

import gzip
import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS  # noqa: E402
from hsbg.az.train.ppo import (  # noqa: E402
    PPOBatch,
    PPOConfig,
    build_train_forward,
    ppo_losses,
    train_ppo,
)


# ══════════════════════════════════════════════════════════════════════════
# 最小模型 / 批次 / BC 池
# ══════════════════════════════════════════════════════════════════════════
class _TinyBCNet(torch.nn.Module):
    """带 ``forward_aux`` 与 ``forward_bc`` 的最小网络（模仿 entity 的头结构）。"""

    CARD_DIM = 8

    def __init__(self, hidden: int = 16) -> None:
        super().__init__()
        self.fc = torch.nn.Linear(OBS_FLOATS, hidden)
        self.policy = torch.nn.Linear(hidden, N_ACTIONS)
        self.rank = torch.nn.Linear(hidden, 8)
        self.value = torch.nn.Linear(hidden, 1)
        self.seq = torch.nn.Linear(hidden, N_ACTIONS)
        self.card_head = torch.nn.Linear(hidden, self.CARD_DIM)

    def _trunk(self, features):
        return torch.relu(self.fc(features))

    def forward(self, features, cards=None, mask=None):
        h = self._trunk(features)
        return self.policy(h), self.rank(h), torch.tanh(self.value(h)).squeeze(-1)

    def forward_aux(self, features, cards=None, mask=None):
        h = self._trunk(features)
        return (self.policy(h), self.rank(h),
                torch.tanh(self.value(h)).squeeze(-1), self.seq(h))

    def forward_bc(self, features, cards=None, mask=None):
        h = self._trunk(features)
        return self.policy(h), self.card_head(h)


def _make_model(seed: int = 0) -> _TinyBCNet:
    torch.manual_seed(int(seed))
    return _TinyBCNet()


def _make_batch(n: int = 8, seed: int = 0) -> PPOBatch:
    rng = np.random.default_rng(int(seed))
    masks = rng.random((n, N_ACTIONS)) < 0.3
    masks[:, 0] = True
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


def _write_cards(path):
    cards = [
        {"id": "TEST_MINION", "kind": "minion", "tier": 1, "atk": 2, "hp": 3,
         "cost": 3, "races": ["BEAST"], "keywords": ["TAUNT"]},
        {"id": "TEST_SPELL", "kind": "spell", "tier": 2, "atk": 0, "hp": 0,
         "cost": 2, "races": [], "keywords": []},
        {"id": "TEST_MINION_G", "kind": "minion", "tier": 2, "atk": 4, "hp": 6,
         "cost": 3, "races": ["BEAST"], "keywords": []},
        {"id": "TEST_HERO", "kind": "hero", "tier": 0, "atk": 0, "hp": 0,
         "cost": 0, "races": [], "keywords": []},
    ]
    path.write_text(json.dumps({"meta": {"count": len(cards)},
                                "cards": cards}), encoding="utf-8")
    return str(path)


def _row(**kw):
    base = {
        "game_id": "g", "turn": 5, "mmr": "7000", "action_type": "sell",
        "action_index": 16, "gold": 5, "tier": 2, "health": 30, "armor": 0,
        "hero": "TEST_HERO", "board_cards": ["TEST_MINION"],
        "board_pos": [0], "hand_cards": [], "hand_pos": [],
        "shop_cards": ["TEST_MINION", "TEST_SPELL"], "shop_pos": [0, 7],
        "card_id": "TEST_MINION",
    }
    base.update(kw)
    return base


@pytest.fixture()
def bc_data(tmp_path):
    cards = _write_cards(tmp_path / "cards.json")
    rows = [
        _row(),
        _row(action_type="play_spell", action_index=46, mmr="6200",
             hand_cards=["TEST_SPELL"], hand_pos=[0], board_cards=[],
             board_pos=[], shop_cards=[], shop_pos=[]),
        _row(action_type="buy_minion", action_index=8, mmr=9000,
             shop_cards=["TEST_MINION"], shop_pos=[0]),
    ]
    path = tmp_path / "bc.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return str(path), cards


def _pool(bc_data):
    from hsbg.az.train.bc_aux import load_bc_samples
    path, cards = bc_data
    pool = load_bc_samples(path, mmr_min=6000, cards_path=cards)
    assert len(pool) == 3
    return pool


def _cfg(**kw) -> PPOConfig:
    base = dict(epochs=1, minibatch=2, lr=1e-3, seed=0, device="cpu",
                target_kl=0.0, amp="off", compile_train=0,
                value_loss="rank", pi_coef=0.0)
    base.update(kw)
    return PPOConfig(**base)


# ══════════════════════════════════════════════════════════════════════════
# 1. 配置默认值 / 校验
# ══════════════════════════════════════════════════════════════════════════
def test_bc_batch_default_and_every_validation():
    cfg = PPOConfig()
    assert cfg.bc_batch == 128
    assert cfg.bc_every == 1
    with pytest.raises(ValueError):
        PPOConfig(bc_every=0)
    with pytest.raises(ValueError):
        PPOConfig(bc_batch=0)


# ══════════════════════════════════════════════════════════════════════════
# 2. 跳过步 == 无 BC（其他 loss 逐位一致）
# ══════════════════════════════════════════════════════════════════════════
def test_skip_step_matches_no_bc_step(bc_data):
    pool = _pool(bc_data)
    model = _make_model(0)
    batch = _make_batch(n=4)
    idx = np.arange(4, dtype=np.int64)
    cfg0 = _cfg(bc_coef=0.0)
    cfg1 = _cfg(bc_coef=0.01, bc_batch=2, bc_every=2)
    out0 = ppo_losses(model, batch, cfg0, indices=idx)
    # 跳过步：传 bc_batch=None + 等效权重，但 BC 分支整体不执行
    out1 = ppo_losses(model, batch, cfg1, indices=idx, bc_batch=None,
                      bc_coef_override=cfg1.bc_coef * cfg1.bc_every)
    assert "bc_loss" not in out1
    for key in ("total", "policy_loss", "value_loss", "entropy",
                "approx_kl", "clip_frac", "ratio_mean"):
        assert torch.allclose(out0[key], out1[key], atol=0.0, rtol=0.0), key


def test_bc_every_schedules_only_alternate_steps(bc_data):
    pool = _pool(bc_data)
    model = _make_model(1)
    batch = _make_batch(n=8)
    cfg = _cfg(bc_coef=0.01, bc_batch=2, bc_every=2)
    stats = train_ppo(model, batch, cfg, bc_pool=pool,
                      rng=np.random.default_rng(0))
    # n=8/minibatch=2 -> 4 个微批；bc_every=2 -> 第 0、2 步做 BC
    assert stats["updates"] == 4
    assert stats["bc_every"] == 2
    assert stats["bc_steps"] == 2
    assert stats["bc_coef"] == pytest.approx(0.01)
    assert stats["bc_coef_effective"] == pytest.approx(0.02)
    assert stats["bc_samples"] == pytest.approx(2.0)
    assert np.isfinite(stats["bc_loss"])
    assert np.isfinite(stats["bc_type_loss"])


def test_bc_every_scales_coef_when_not_divisible(bc_data):
    """N 不整除微批数时，系数按 m_total/n_bc 精确折算（总权重不变）。"""
    pool = _pool(bc_data)
    model = _make_model(6)
    batch = _make_batch(n=8)
    cfg = _cfg(bc_coef=0.01, bc_batch=2, bc_every=3)
    stats = train_ppo(model, batch, cfg, bc_pool=pool,
                      rng=np.random.default_rng(0))
    # n=8/minibatch=2 -> 4 个微批；bc_every=3 -> 第 0、3 步做 BC（2 次）
    assert stats["updates"] == 4
    assert stats["bc_steps"] == 2
    # 2 * eff = 4 * 0.01 -> eff = 0.02（而不是 3 * 0.01）
    assert stats["bc_coef_effective"] == pytest.approx(0.02)
    assert stats["epochs"][0]["bc_coef"] == pytest.approx(0.02)


# ══════════════════════════════════════════════════════════════════════════
# 3. TrainForward：BC 独立固定形状图 + 形状路由 + 失败回退
# ══════════════════════════════════════════════════════════════════════════
def test_train_forward_compiles_bc_batch_and_routes_by_shape():
    model = _make_model(2)
    cfg = _cfg(compile_train=1, minibatch=4, bc_coef=0.01, bc_batch=2)
    tf = build_train_forward(model, cfg)
    assert tf is not None and tf.bc_compiled is True
    assert tf.bc_size == 2
    x2 = torch.zeros(2, OBS_FLOATS)
    c2 = torch.zeros(2, OBS_CARDS, dtype=torch.long)
    m2 = torch.ones(2, N_ACTIONS, dtype=torch.bool)
    logits, card_logits = tf.bc(x2, c2, m2)
    assert logits.shape == (2, N_ACTIONS) and card_logits.shape == (2, 8)
    assert tf.bc_calls == 1 and tf.bc_eager_calls == 0
    # 形状 != bc_batch（尾批/池不足）-> eager，不触发重编译
    logits, card_logits = tf.bc(x2[:1], c2[:1], m2[:1])
    assert logits.shape == (1, N_ACTIONS)
    assert tf.bc_calls == 1 and tf.bc_eager_calls == 1
    assert tf.describe()["bc_compiled"] is True


def test_bc_compile_failure_falls_back(monkeypatch, capsys, bc_data):
    pool = _pool(bc_data)
    model = _make_model(3)
    batch = _make_batch(n=8)
    before = [p.detach().clone() for p in model.parameters()]

    def _boom(*_a, **_kw):
        raise RuntimeError("simulated bc compile failure")

    monkeypatch.setattr(torch, "compile", _boom)
    stats = train_ppo(model, batch, _cfg(compile_train=1, bc_coef=0.01,
                                         bc_batch=2), bc_pool=pool,
                      rng=np.random.default_rng(0))
    assert stats["compile_active"] is False
    assert stats["compile"]["bc_compiled"] is False
    assert stats["updates"] > 0
    out = capsys.readouterr().out
    assert "simulated bc compile failure" in out
    # main/aux/bc 各自只 warn 一次；BC 分支仍以 eager 算出有限 loss
    assert out.count("torch.compile 训练前向（bc）") == 1
    assert np.isfinite(stats["bc_loss"])
    assert any(not torch.equal(a, b) for a, b in zip(before, model.parameters()))


def test_bc_compile_off_keeps_bc_eager():
    model = _make_model(5)
    cfg = _cfg(compile_train=1, minibatch=4, bc_coef=0.01, bc_batch=2,
               bc_compile=0)
    tf = build_train_forward(model, cfg)
    assert tf is not None and tf.main_compiled is True
    assert tf.bc_compiled is False and tf.bc_size == 2
    x2 = torch.zeros(2, OBS_FLOATS)
    c2 = torch.zeros(2, OBS_CARDS, dtype=torch.long)
    m2 = torch.ones(2, N_ACTIONS, dtype=torch.bool)
    logits, card_logits = tf.bc(x2, c2, m2)
    assert logits.shape == (2, N_ACTIONS) and card_logits.shape == (2, 8)
    assert tf.bc_eager_calls == 1 and tf.bc_calls == 0


# ══════════════════════════════════════════════════════════════════════════
# 4. 编译 BC 与 eager 数值一致
# ══════════════════════════════════════════════════════════════════════════
def test_compiled_bc_matches_eager(bc_data):
    pool = _pool(bc_data)
    batch = _make_batch(n=6)
    model0 = _make_model(4)
    model1 = _make_model(4)
    model1.load_state_dict(model0.state_dict())
    kw = dict(bc_coef=0.01, bc_batch=2, bc_type_weight=1.0, bc_card_weight=0.5)
    base = train_ppo(model0, batch, _cfg(compile_train=0, **kw), bc_pool=pool,
                     rng=np.random.default_rng(0))
    comp = train_ppo(model1, batch, _cfg(compile_train=1, **kw), bc_pool=pool,
                     rng=np.random.default_rng(0))
    assert comp["compile"]["bc_compiled"] is True
    assert comp["compile"]["bc_calls"] > 0
    b, c = base["epochs"][0], comp["epochs"][0]
    for key in ("total", "policy_loss", "value_loss", "bc_loss",
                "bc_type_loss", "bc_card_loss"):
        assert abs(c[key] - b[key]) <= 1e-4, (key, b[key], c[key])
    for p0, p1 in zip(model0.parameters(), model1.parameters()):
        assert torch.allclose(p0, p1, atol=1e-4, rtol=0.0), (
            f"参数更新不一致: max|Δ|={float((p0 - p1).abs().max()):.2e}")
