"""场面强度辅助头单测（``docs/BOARD_PROBLEMS.md`` / ``docs/RESEARCH_PLAN_V2.md`` §4.1）。

覆盖：

1. **默认关闭逐位等价**：``strength_head=False`` 不建参数；``problem_bc_coef`` /
   ``strength_aux_coef`` 都为 0 时 ``ppo_losses`` 的 ``total`` 与键集合**逐位相同**，
   ``train_ppo`` 的权重逐位相同（给不给 ``problem_batch`` 都一样）；
2. **头的形状/梯度**：``forward_problem`` 输出 ``[n,2]``；辅助损失能把梯度传回 trunk
   （零初始化会切断梯度，这里用默认初始化 + 断言 trunk 权重变化）；
3. **损失数值**：masked MSE/BCE 与手算一致、无有效行返回 0、``pos_weight`` 生效；
4. **checkpoint 兼容**：旧 ckpt（无 ``strength_head.*``）加载不报错且不带头；追加头后
   其余权重逐位不变、``save→load`` 保留头与 ``strength_norm``；
5. **配置校验**：负系数/非法批量/非法周期报错；入口脚本暴露 ``--strength-aux-coef``；
6. **能学**：几十步 Adam 后强度辅助损失显著下降。
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys

import numpy as np
import pytest

from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 默认关闭时必须与旧版完全一致的 loss 键集合（与 test_az_seq_aux 同口径）。
LEGACY_LOSS_KEYS = frozenset({
    "total", "policy_loss", "value_loss", "aux_pi_loss", "anchor_kl", "entropy",
    "approx_kl", "clip_frac", "ratio_mean", "illegal_prob_max", "adv_mean",
    "value_pred_mean",
})


def _torch():
    return pytest.importorskip("torch")


def _tables(n=64):
    from hsbg.az.train.entity_model import CardTables, TEXT_DIM
    return CardTables(static=np.zeros((n, 56), np.float32),
                      text=np.zeros((n, TEXT_DIM), np.float32), n_cards=n)


def _entity(d_model=32, legacy=False):
    _torch()
    from hsbg.az.train.entity_model import build_entity_net
    return build_entity_net(d_model=d_model, n_layers=1, n_heads=4, dim_ff=64,
                            card_dim=8, tables=_tables(),
                            strength_head=not legacy)


def _policy_batch(model, n_games: int = 2, decisions_per_seat: int = 2,
                  seed: int = 7):
    """用**当前模型自己的** masked softmax 生成动作/old_logprob（ratio 起点=1）。

    走 ``build_batch_from_records``：episode 分组/done/GAE 都由它算，保证
    ``PPOBatch.validate()`` 通过（与 ``tests/test_az_ppo.py`` 同做法）。
    """
    torch = _torch()
    from hsbg.az.train.common import N_PLAYERS
    from hsbg.az.train.ppo import (build_batch_from_records, masked_probs_np,
                                   value_from_rank_logits_np)
    rng = np.random.default_rng(seed)
    records = []
    model.eval()
    for g in range(n_games):
        for seat in range(N_PLAYERS):
            rank = int((g * 3 + seat) % N_PLAYERS) + 1
            for t in range(decisions_per_seat):
                features = rng.normal(size=OBS_FLOATS).astype(np.float32)
                cards = np.zeros(OBS_CARDS, dtype=np.int32)
                mask = np.zeros(N_ACTIONS, dtype=bool)
                legal = rng.choice(np.arange(8, 60), size=5, replace=False)
                mask[legal] = True
                mask[0] = True
                x = torch.from_numpy(features.reshape(1, -1))
                c = torch.from_numpy(cards.astype(np.int64).reshape(1, -1))
                m = torch.from_numpy(mask.reshape(1, -1))
                with torch.no_grad():
                    out = model(x, c, m) if getattr(model, "uses_cards", False) \
                        else model(x, c)
                plog = out[0].numpy()[0]
                rank_logits = out[1].numpy()[0]
                probs = masked_probs_np(plog, mask)
                probs = probs / max(float(probs.sum()), 1e-12)
                action = int(rng.choice(N_ACTIONS, p=probs))
                records.append({
                    "features": features, "cards": cards, "mask": mask,
                    "action": action,
                    "old_logprob": float(np.log(max(float(probs[action]), 1e-12))),
                    "value": float(value_from_rank_logits_np(rank_logits)[0]),
                    "target_pi": None, "rank": rank, "seat": seat,
                    "game_id": g, "turn": t,
                })
    return build_batch_from_records(records, gamma=1.0, lam=0.95,
                                    step_penalty=1e-3)


def _problem_batch(n: int = 8, seed: int = 5):
    """用合成题池造一批题目（soft label + 强度标签）。"""
    from hsbg.az.train.board_problems import (BoardProblemBatch,
                                             problem_obs_batch)
    rng = np.random.default_rng(seed)
    masks = np.zeros((n, N_ACTIONS), dtype=bool)
    for i in range(n):
        legal = rng.choice(np.arange(0, 60), size=8, replace=False)
        masks[i, legal] = True
    soft = np.zeros((n, N_ACTIONS), np.float32)
    act = np.zeros((n, 3), np.int16)
    w = np.zeros((n, 3), np.float32)
    for i in range(n):
        legal = np.flatnonzero(masks[i])
        act[i] = legal[:3]
        w[i] = np.asarray([0.5, 0.3, 0.2], np.float32)
        soft[i, legal[:3]] = w[i]
    return BoardProblemBatch(
        features=rng.normal(size=(n, OBS_FLOATS)).astype(np.float32),
        cards=rng.integers(0, 300, size=(n, OBS_CARDS)).astype(np.int32),
        mask=masks, soft=soft, bc_valid=np.ones(n, bool),
        strength_target=rng.normal(size=n).astype(np.float32),
        tier_target=(rng.random(n) > 0.5).astype(np.float32),
        aux_valid=np.ones(n, bool), ref_top1=act[:, 0].copy(),
        policy_action=act[:, 1].copy())


def _cfg(**kw):
    from hsbg.az.train.ppo import PPOConfig
    base = dict(minibatch=4, epochs=1, lr=1e-3, pi_coef=0.0, entropy_coef=0.0,
                value_coef=0.5, device="cpu", seed=0, kl_early_stop=False,
                compile_train=0, max_grad_norm=10.0)
    base.update(kw)
    return PPOConfig(**base)


# ── 1. 默认关闭：逐位等价 ───────────────────────────────────────────────
def test_legacy_model_has_no_strength_head():
    net = _entity(legacy=True)
    assert getattr(net, "strength_head", None) is None
    assert not any(k.startswith("strength_head") for k in net.state_dict())


def test_strength_head_adds_exactly_two_outputs():
    torch = _torch()
    torch.manual_seed(1234)
    legacy = _entity(legacy=True)
    torch.manual_seed(1234)          # 同 seed：头在 __init__ 末尾创建，不影响其它参数
    net = _entity()
    p0 = sum(p.numel() for p in legacy.parameters())
    p1 = sum(p.numel() for p in net.parameters())
    assert p1 - p0 == 32 * 2 + 2  # d_model=32，两个输出（强度 + tier logit）
    assert net.strength_head.out_features == 2
    # 其余参数逐位一致（新头在 __init__ 末尾创建，不影响其它初始化）
    for k, v in legacy.state_dict().items():
        assert torch.equal(v, net.state_dict()[k]), k


def test_forward_problem_shapes_and_grad():
    torch = _torch()
    net = _entity()
    f = torch.randn(3, OBS_FLOATS)
    c = torch.zeros(3, OBS_CARDS, dtype=torch.long)
    c[:, 0] = 1
    m = torch.zeros(3, N_ACTIONS, dtype=torch.bool)
    m[:, 0] = True
    m[:, 8:16] = True
    logits, pred = net.forward_problem(f, c, m)
    assert logits.shape == (3, N_ACTIONS) and pred.shape == (3, 2)
    assert torch.isfinite(pred).all()
    assert torch.all(logits[:, 1] <= -1e8)
    # 梯度能从强度头回到 trunk（零初始化会切断，故用默认初始化）
    pred.sum().backward()
    g = net.trunk.layers[0].linear1.weight.grad
    assert g is not None and float(g.abs().sum()) > 0.0


def test_coef_zero_bitwise_ppo_losses():
    """coef=0 时给不给 problem_batch，``total`` 逐位相同、键集合与旧版一致。"""
    torch = _torch()
    from hsbg.az.train.ppo import ppo_losses
    from hsbg.az.train.model import build_net
    m = build_net(16)
    batch = _policy_batch(m)
    pb = _problem_batch()
    out0 = ppo_losses(m, batch, _cfg())
    out1 = ppo_losses(m, batch, _cfg(), problem_batch=pb)
    assert frozenset(out0) == LEGACY_LOSS_KEYS
    assert frozenset(out1) == LEGACY_LOSS_KEYS
    assert torch.equal(out0["total"], out1["total"])
    for k in LEGACY_LOSS_KEYS:
        assert torch.equal(out0[k], out1[k]), k


def test_coef_zero_bitwise_train_ppo():
    """coef=0 时 ``train_ppo`` 的权重逐位一致（与是否传题目批次无关）。"""
    torch = _torch()
    from hsbg.az.train.model import build_net
    from hsbg.az.train.ppo import train_ppo
    torch.manual_seed(0)
    m0 = build_net(16)
    m1 = copy.deepcopy(m0)
    batch = _policy_batch(m0)
    pb = _problem_batch()
    s0 = train_ppo(m0, batch, _cfg())
    s1 = train_ppo(m1, batch, _cfg(), problem_batch=pb)
    for (k, v0), (_k, v1) in zip(m0.state_dict().items(), m1.state_dict().items()):
        assert torch.equal(v0, v1), k
    assert set(s0) == set(s1)
    assert not any(k.startswith(("problem_", "strength_")) for k in s1)
    # config 回显里也不该出现新键（与旧版本 stats 结构一致）
    assert not any(k.startswith(("problem_", "strength_"))
                   for k in s1["config"])


def test_enabled_changes_weights_and_stats():
    """coef>0 时确实改变权重并写 stats（否则整个功能是空转）。"""
    torch = _torch()
    from hsbg.az.train.model import build_net
    from hsbg.az.train.ppo import train_ppo
    torch.manual_seed(0)
    m0 = build_net(16)
    m1 = copy.deepcopy(m0)
    batch = _policy_batch(m0)
    pb = _problem_batch()
    train_ppo(m0, batch, _cfg())
    s1 = train_ppo(m1, batch, _cfg(problem_bc_coef=0.5), problem_batch=pb)
    changed = any(not torch.equal(v, m1.state_dict()[k])
                  for k, v in m0.state_dict().items())
    assert changed
    assert "problem_bc_loss" in s1
    assert "problem_bc_top1_acc" in s1
    assert s1["config"]["problem_bc_coef"] == pytest.approx(0.5)


# ── 2. 损失数值 ─────────────────────────────────────────────────────────
def test_strength_aux_loss_matches_hand_computation():
    torch = _torch()
    import torch.nn.functional as F
    from hsbg.az.train.board_problems import strength_aux_loss
    pb = _problem_batch(n=4)
    pb.aux_valid = np.asarray([True, True, False, True])
    pred = torch.zeros(4, 2)
    st = strength_aux_loss(pred, pb, pos_weight=2.0)
    s = torch.from_numpy(pb.strength_target[[0, 1, 3]])
    t = torch.from_numpy(pb.tier_target[[0, 1, 3]])
    mse = F.mse_loss(torch.zeros(3), s)
    bce = F.binary_cross_entropy_with_logits(
        torch.zeros(3), t, pos_weight=torch.tensor(2.0))
    assert float(st["mse"]) == pytest.approx(float(mse), abs=1e-6)
    assert float(st["bce"]) == pytest.approx(float(bce), abs=1e-6)
    assert float(st["loss"]) == pytest.approx(float(mse + bce), abs=1e-6)
    assert st["n"] == 3
    # 无效行的标签怎么改都不影响
    pb2 = copy.deepcopy(pb)
    pb2.strength_target[2] = 999.0
    pb2.tier_target[2] = 1.0
    assert float(strength_aux_loss(pred, pb2, pos_weight=2.0)["loss"]) == \
        pytest.approx(float(st["loss"]), abs=1e-6)


def test_strength_aux_loss_empty_is_zero():
    torch = _torch()
    from hsbg.az.train.board_problems import strength_aux_loss
    pb = _problem_batch(n=3)
    pb.aux_valid = np.zeros(3, bool)
    out = strength_aux_loss(torch.randn(3, 2), pb)
    assert float(out["loss"]) == 0.0 and out["n"] == 0


def test_strength_head_learns():
    """几十步 Adam 后强度辅助损失下降（可学性，CPU 上 <5 s）。"""
    torch = _torch()
    from hsbg.az.train.board_problems import strength_aux_loss
    net = _entity()
    pb = _problem_batch(n=16)
    opt = torch.optim.Adam(net.parameters(), lr=5e-3)
    f = torch.from_numpy(pb.features)
    c = torch.from_numpy(pb.cards.astype(np.int64))
    m = torch.from_numpy(pb.mask)
    w_before = net.trunk.layers[0].linear1.weight.detach().clone()

    def _loss():
        _l, pred = net.forward_problem(f, c, m)
        return strength_aux_loss(pred, pb)

    first = float(_loss()["loss"])
    for _ in range(40):
        opt.zero_grad()
        _loss()["loss"].backward()
        opt.step()
    last = float(_loss()["loss"])
    assert last < first * 0.7, (first, last)
    assert not torch.equal(w_before, net.trunk.layers[0].linear1.weight)


# ── 3. checkpoint 兼容 ─────────────────────────────────────────────────
def test_attach_strength_head_keeps_other_weights_and_is_idempotent(tmp_path):
    torch = _torch()
    from hsbg.az.train.model import (attach_strength_head, load_checkpoint,
                                     save_checkpoint)
    from hsbg.az.train.model import build_net
    legacy = build_net(arch="entity", d_model=32, n_layers=1, n_heads=4)
    p = str(tmp_path / "legacy.pt")
    save_checkpoint(legacy, p, meta={"arch": "entity", "d_model": 32,
                                     "n_layers": 1, "n_heads": 4})
    model, meta = load_checkpoint(p, device="cpu")
    assert getattr(model, "strength_head", None) is None   # 旧 ckpt 自动跳过
    assert meta.get("strength_head") is False
    f = torch.randn(2, OBS_FLOATS)
    c = torch.zeros(2, OBS_CARDS, dtype=torch.long)
    m = torch.zeros(2, N_ACTIONS, dtype=torch.bool)
    m[:, 0] = True
    before = model(f, c, m)
    attach_strength_head(model, norm={"mean": 2.0, "std": 3.0})
    attach_strength_head(model)          # 幂等，不重置 norm
    assert model.strength_norm == {"mean": 2.0, "std": 3.0}
    after = model(f, c, m)
    assert all(torch.equal(a, b) for a, b in zip(before, after))
    p2 = str(tmp_path / "with_head.pt")
    save_checkpoint(model, p2, meta={"arch": "entity", "d_model": 32,
                                     "n_layers": 1, "n_heads": 4})
    model2, meta2 = load_checkpoint(p2, device="cpu")
    assert model2.strength_head is not None
    assert meta2["strength_norm"] == {"mean": 2.0, "std": 3.0}
    assert model2.strength_norm == {"mean": 2.0, "std": 3.0}
    for k, v in legacy.state_dict().items():
        assert torch.equal(v, model2.state_dict()[k]), k


def test_attach_strength_head_rejects_non_entity():
    from hsbg.az.train.model import attach_strength_head, build_net
    tiny = build_net(16)
    with pytest.raises(ValueError):
        attach_strength_head(tiny)


# ── 4. 配置校验 / CLI ──────────────────────────────────────────────────
@pytest.mark.parametrize("kw", [
    {"strength_aux_coef": -1.0},
    {"problem_bc_coef": -0.5},
    {"problem_bc_every": 0},
    {"strength_aux_every": 0},
    {"problem_batch": 0},
    {"strength_tier_pos_weight": 0.0},
])
def test_ppo_config_validation(kw):
    from hsbg.az.train.ppo import PPOConfig
    with pytest.raises(ValueError):
        PPOConfig(**kw)


def test_train_script_exposes_flags():
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "train_entity_sync.py"),
         "--help"], capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    for flag in ("--problem-bc-coef", "--problem-bc-every", "--problem-batch",
                 "--problem-pool", "--strength-aux-coef",
                 "--strength-aux-every", "--strength-tier-pos-weight"):
        assert flag in out.stdout, flag


def test_defaults_are_off():
    from hsbg.az.train.ppo import PPOConfig
    cfg = PPOConfig()
    assert cfg.problem_bc_coef == 0.0
    assert cfg.strength_aux_coef == 0.0
    # 默认关闭时训练器不加载题目池（不读 problems.jsonl）
    from hsbg.az.train.ppo_trainer import PPOTrainer
    from hsbg.az.train.model import build_net
    tr = PPOTrainer(build_net(8), PPOConfig(device="cpu"))
    assert tr.problem_pool is None
    assert tr._problem_batch() == (None, 0.0, 0.0)


def test_default_problem_paths_exist_in_repo():
    from hsbg.az.train.board_problems import DEFAULT_PROBLEM_PATH
    # 只断言常量指向仓库内的数据目录（文件由构造器产出，不强制存在于 CI）
    assert DEFAULT_PROBLEM_PATH.endswith(
        os.path.join("data", "board_problems", "problems.jsonl"))
    assert json.dumps(DEFAULT_PROBLEM_PATH)
