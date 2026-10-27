"""``hsbg.az.train.ppo`` 单测（MCTS 引导的 PPO）。

覆盖（引擎无关部分）：
1. masked log-softmax / masked softmax：合法概率和=1、非法动作概率**严格**为 0；
2. GAE(λ) / reward-to-go：与手算一致、不跨 episode bootstrap；
3. clip surrogate：ratio 裁剪公式与裁剪比例手算一致；
4. 轨迹批次：按 (game_id, seat) 分组、终局 utility reward、done、校验/存取；
5. 短 synthetic PPO update：ratio 起点=1、rank/mse 两种 value loss 有限、
   patch 后策略在非法动作上的概率仍为 0、KL 早停可触发。

需要真实引擎的 smoke 用 ``pytest.importorskip("hsbg_engine")``；torch 缺失时相关
用例 skip，numpy 用例照常运行。
"""

from __future__ import annotations

import os
import subprocess
import sys

import numpy as np
import pytest

from hsbg.az.train.common import (
    N_ACTIONS,
    N_PLAYERS,
    OBS_CARDS,
    OBS_FLOATS,
    utility_from_rank,
)
from hsbg.az.train.ppo import (
    BATCH_FIELDS,
    CollectConfig,
    PPOBatch,
    PPOConfig,
    build_batch_from_records,
    clipped_surrogate,
    compute_gae,
    masked_log_softmax_np,
    masked_probs_np,
    ppo_losses,
    reward_to_go_np,
    train_ppo,
    value_from_rank_logits_np,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _needs_torch():
    """torch 相关用例统一 skip 口径。"""
    return pytest.importorskip("torch")


# ── 1. masked logprob / 非法概率 ─────────────────────────────────────────
def _random_legal_mask(rng: np.random.Generator, n_legal: int = 6) -> tuple[np.ndarray, np.ndarray]:
    mask = np.zeros(N_ACTIONS, dtype=bool)
    legal = rng.choice(N_ACTIONS, size=int(n_legal), replace=False)
    mask[legal] = True
    logits = rng.normal(size=N_ACTIONS).astype(np.float32)
    return logits, mask


def test_masked_logprob_matches_manual_softmax():
    rng = np.random.default_rng(0)
    logits, mask = _random_legal_mask(rng, 6)
    logp = masked_log_softmax_np(logits, mask)
    probs = masked_probs_np(logits, mask)

    # 非法动作概率严格 0，合法概率和 = 1
    assert np.all(probs[~mask] == 0.0)
    assert float(probs.sum()) == pytest.approx(1.0, abs=1e-7)
    # 合法位与手算 softmax 一致
    legal = np.flatnonzero(mask)
    ref = np.exp(logits[legal] - logits[legal].max())
    ref = ref / ref.sum()
    assert np.allclose(probs[legal], ref, atol=1e-6)
    assert np.allclose(logp[legal], np.log(ref), atol=1e-6)
    assert np.isfinite(logp[legal]).all()
    assert np.all(logp[~mask] == -np.inf)

    # 温度：τ=0.5 更尖
    p05 = masked_probs_np(logits, mask, temperature=0.5)
    assert np.all(p05[~mask] == 0.0)
    assert float(p05.max()) >= float(probs.max()) - 1e-9


def test_masked_logprob_rejects_illegal_action():
    from hsbg.az.train.ppo import action_logprob_np

    rng = np.random.default_rng(1)
    logits, mask = _random_legal_mask(rng)
    illegal = int(np.flatnonzero(~mask)[0])
    with pytest.raises(ValueError):
        action_logprob_np(logits, mask, illegal)
    legal = int(np.flatnonzero(mask)[0])
    lp = action_logprob_np(logits, mask, legal)
    assert np.isfinite(lp) and lp <= 1e-6


def test_masked_softmax_empty_mask_is_all_illegal():
    logits = np.zeros(N_ACTIONS, dtype=np.float32)
    mask = np.zeros(N_ACTIONS, dtype=bool)
    logp = masked_log_softmax_np(logits, mask)
    assert np.all(np.isneginf(logp))
    assert np.all(masked_probs_np(logits, mask) == 0.0)


def test_torch_masked_softmax_illegal_prob_zero():
    torch = _needs_torch()
    generator = torch.Generator().manual_seed(0)
    logits = torch.randn(4, N_ACTIONS, generator=generator)
    mask = torch.zeros(4, N_ACTIONS, dtype=torch.bool)
    mask[:, [0, 8, 46]] = True
    mask[1, 100] = True
    mask[2, 196:245] = True
    from hsbg.az.train.ppo import masked_probs_torch

    probs = masked_probs_torch(logits, mask)
    # 非法位（~mask）概率严格 0；合法位概率和 = 1
    assert float(probs.masked_fill(mask, 0.0).abs().max()) == 0.0
    assert torch.allclose(probs.sum(dim=-1), torch.ones(4), atol=1e-6)
    # 与 numpy 实现一致
    for i in range(4):
        ref = masked_probs_np(logits[i].numpy(), mask[i].numpy())
        assert np.allclose(probs[i].numpy(), ref, atol=1e-6)


# ── 2. GAE / reward-to-go ────────────────────────────────────────────────
def test_gae_matches_hand_computation():
    rewards = np.array([0.0, 0.0, 1.0, 0.0, 1.0])
    values = np.array([0.5, 0.2, 0.1, 0.3, 0.0])
    dones = np.array([0.0, 0.0, 1.0, 0.0, 1.0])
    adv, returns = compute_gae(rewards, values, dones, gamma=1.0, lam=1.0)
    assert np.allclose(adv, [0.5, 0.8, 0.9, 0.7, 1.0], atol=1e-6)
    assert np.allclose(returns, [1.0, 1.0, 1.0, 1.0, 1.0], atol=1e-6)
    # λ=0 -> TD 误差；末步无 bootstrap，不跨 episode 借下一局价值
    adv0, _ = compute_gae(rewards, values, dones, gamma=1.0, lam=0.0)
    assert np.allclose(adv0, [-0.3, -0.1, 0.9, -0.3, 1.0], atol=1e-6)


def test_reward_to_go_does_not_cross_episode():
    rewards = np.array([1.0, 1.0, 1.0, 1.0])
    dones = np.array([0.0, 0.0, 1.0, 0.0])
    rtg = reward_to_go_np(rewards, dones, gamma=0.5)
    assert np.allclose(rtg, [1.75, 1.5, 1.0, 1.0], atol=1e-6)


# ── 3. clip surrogate ───────────────────────────────────────────────────
def test_clipped_surrogate_matches_formula():
    torch = _needs_torch()
    ratio = torch.tensor([0.5, 0.9, 1.1, 2.0], dtype=torch.float32)
    adv = torch.ones(4)
    loss, frac = clipped_surrogate(ratio, adv, clip=0.2)
    assert float(loss) == pytest.approx(-float(np.mean([0.5, 0.9, 1.1, 1.2])), abs=1e-6)
    assert float(frac) == pytest.approx(0.5)  # 0.5 与 2.0 被裁
    # 负优势方向
    loss_neg, _ = clipped_surrogate(ratio, -adv, clip=0.2)
    assert float(loss_neg) == pytest.approx(
        float(np.mean([0.8, 0.9, 1.1, 2.0])), abs=1e-6)
    with pytest.raises(ValueError):
        clipped_surrogate(ratio, adv, clip=0.0)


# ── 4. 轨迹批次：分组 / reward / done / 校验 / 存取 ──────────────────────
def _synthetic_records(*, seed: int = 0, n_games: int = 2,
                       decisions_per_seat: int = 3) -> list:
    rng = np.random.default_rng(seed)
    records = []
    for g in range(n_games):
        for seat in range(N_PLAYERS):
            rank = int((g * 5 + seat) % N_PLAYERS) + 1
            for t in range(decisions_per_seat):
                logits, mask = _random_legal_mask(rng, int(rng.integers(2, 8)))
                legal = np.flatnonzero(mask)
                action = int(legal[int(rng.integers(legal.size))])
                probs = masked_probs_np(logits, mask)
                probs = probs / probs.sum()
                target_pi = None
                if (g + seat + t) % 2 == 0:
                    target_pi = np.zeros(N_ACTIONS, dtype=np.float32)
                    target_pi[legal] = rng.random(legal.size).astype(np.float32)
                    target_pi /= target_pi.sum()
                records.append({
                    "features": rng.normal(size=OBS_FLOATS).astype(np.float32),
                    "cards": rng.integers(0, 4000, size=OBS_CARDS).astype(np.int32),
                    "mask": mask,
                    "action": action,
                    "old_logprob": float(np.log(max(float(probs[action]), 1e-12))),
                    "value": float(rng.uniform(-1.0, 1.0)),
                    "target_pi": target_pi,
                    "rank": rank,
                    "seat": seat,
                    "game_id": 100 + g,
                    "turn": int(t),
                })
    return records


def test_build_batch_groups_episodes_and_rewards():
    records = _synthetic_records(n_games=2, decisions_per_seat=3)
    penalty = 1e-3
    batch = build_batch_from_records(records, gamma=1.0, lam=0.95,
                                     step_penalty=penalty, meta={"tag": "unit"})
    assert len(batch) == 2 * N_PLAYERS * 3
    assert batch.validate() == [], batch.validate()
    assert batch.meta["tag"] == "unit"
    # 每个 (game_id, seat) 一个 episode，恰好一个 done 且在末步
    assert int(np.unique(batch.episode_ids).size) == 2 * N_PLAYERS
    for ep in np.unique(batch.episode_ids):
        idx = np.flatnonzero(batch.episode_ids == ep)
        assert int(batch.dones[idx].sum()) == 1
        assert batch.dones[idx[-1]] == pytest.approx(1.0)
    # 末步 reward = u(rank) - penalty，其余 = -penalty
    for ep in np.unique(batch.episode_ids):
        idx = np.flatnonzero(batch.episode_ids == ep)
        expected = float(utility_from_rank([int(batch.ranks[idx[-1]])])[0]) - penalty
        assert batch.rewards[idx[-1]] == pytest.approx(expected, abs=1e-6)
        assert np.allclose(batch.rewards[idx[:-1]], -penalty, atol=1e-7)
    # returns = advantages + values
    assert np.allclose(batch.returns, batch.advantages + batch.values, atol=1e-6)
    # 可选 MCTS π：只在 target_pi 非空的样本上启用，且无非法质量
    expect_pi = (2 * N_PLAYERS * 3) // 2
    assert int(batch.has_pi.sum()) == expect_pi
    assert float(batch.target_pi[~batch.has_pi].sum()) == 0.0
    pi = batch.target_pi.astype(np.float64)
    assert np.allclose(pi[batch.has_pi].sum(axis=1), 1.0, atol=1e-6)
    assert float((pi[batch.has_pi] * (~batch.masks[batch.has_pi])).sum()) == 0.0


def test_batch_validate_catches_illegal_action():
    batch = build_batch_from_records(_synthetic_records(), gamma=1.0, lam=0.95)
    illegal = int(np.flatnonzero(~batch.masks[0])[0])
    bad_actions = batch.actions.copy()
    bad_actions[0] = illegal
    bad = PPOBatch(**{k: getattr(batch, k) for k in BATCH_FIELDS}, meta=dict(batch.meta))
    bad.actions = bad_actions
    errs = bad.validate()
    assert any("合法掩码" in e or "掩码" in e for e in errs), errs


def test_build_batch_rejects_empty_or_truncated_only():
    records = _synthetic_records(n_games=1, decisions_per_seat=1)
    for rec in records:
        rec["rank"] = 0
    with pytest.raises(ValueError):
        build_batch_from_records(records)


def test_batch_save_load_roundtrip(tmp_path):
    batch = build_batch_from_records(_synthetic_records(), gamma=1.0, lam=0.95)
    path = os.path.join(tmp_path, "ppo_batch.npz")
    batch.save(path)
    assert os.path.isfile(path)
    loaded = PPOBatch.load(path)
    assert len(loaded) == len(batch)
    for name in BATCH_FIELDS:
        assert np.array_equal(getattr(loaded, name), getattr(batch, name)), name
    assert loaded.validate() == []
    assert loaded.meta["gamma"] == pytest.approx(1.0)


# ── 5. synthetic PPO update（需要 torch，不需要引擎）───────────────────
def _batch_from_model(model, *, seed: int = 7, n_games: int = 2,
                      decisions_per_seat: int = 2):
    """用**当前模型**自己的 masked softmax 生成动作/old_logprob，保证 ratio 起点=1。"""
    torch = _needs_torch()
    rng = np.random.default_rng(seed)
    records = []
    model.eval()
    for g in range(n_games):
        for seat in range(N_PLAYERS):
            rank = int((g * 3 + seat) % N_PLAYERS) + 1
            for t in range(decisions_per_seat):
                features = rng.normal(size=OBS_FLOATS).astype(np.float32)
                cards = np.zeros(OBS_CARDS, dtype=np.int32)
                _logits, mask = _random_legal_mask(rng, int(rng.integers(2, 8)))
                x = torch.from_numpy(features.reshape(1, -1))
                c = torch.from_numpy(cards.astype(np.int64).reshape(1, -1))
                with torch.no_grad():
                    out = model(x, c)
                plog = out[0].numpy()[0]
                rank_logits = out[1].numpy()[0]
                probs = masked_probs_np(plog, mask)
                probs = probs / max(float(probs.sum()), 1e-12)
                action = int(rng.choice(N_ACTIONS, p=probs))
                target_pi = None
                if (g + seat + t) % 2 == 0:
                    target_pi = np.zeros(N_ACTIONS, dtype=np.float32)
                    legal = np.flatnonzero(mask)
                    target_pi[legal] = rng.random(legal.size).astype(np.float32)
                    target_pi /= target_pi.sum()
                records.append({
                    "features": features,
                    "cards": cards,
                    "mask": mask,
                    "action": action,
                    "old_logprob": float(np.log(max(float(probs[action]), 1e-12))),
                    "value": float(value_from_rank_logits_np(rank_logits)[0]),
                    "target_pi": target_pi,
                    "rank": rank,
                    "seat": seat,
                    "game_id": g,
                    "turn": t,
                })
    return build_batch_from_records(records, gamma=1.0, lam=0.95, step_penalty=1e-3)


def test_ppo_loss_ratio_starts_at_one_and_aux_pi_direction():
    torch = _needs_torch()
    from hsbg.az.train.model import build_net

    torch.manual_seed(0)
    model = build_net(16)
    batch = _batch_from_model(model)
    base = ppo_losses(model, batch, PPOConfig(device="cpu", value_loss="rank", pi_coef=0.0))
    assert float(base["ratio_mean"]) == pytest.approx(1.0, abs=1e-5)
    assert float(base["clip_frac"]) == 0.0
    assert float(base["illegal_prob_max"]) == 0.0
    assert float(base["aux_pi_loss"]) == 0.0  # pi_coef=0 -> 关闭辅助 CE

    with_pi = ppo_losses(model, batch, PPOConfig(device="cpu", value_loss="rank", pi_coef=0.5))
    assert float(with_pi["aux_pi_loss"]) > 0.0
    assert np.isfinite(float(with_pi["total"]))
    # value loss 两种模式都有限
    for mode in ("rank", "mse"):
        out = ppo_losses(model, batch, PPOConfig(device="cpu", value_loss=mode))
        assert np.isfinite(float(out["value_loss"]))


def test_train_ppo_synthetic_update_masks_and_finiteness():
    torch = _needs_torch()
    from hsbg.az.train.model import build_net
    from hsbg.az.train.ppo import masked_probs_torch

    torch.manual_seed(0)
    model = build_net(16)
    batch = _batch_from_model(model)
    before = [p.detach().clone() for p in model.parameters()]
    stats = train_ppo(model, batch, PPOConfig(
        epochs=2, minibatch=8, lr=1e-3, seed=0, target_kl=10.0,
        value_loss="rank", pi_coef=0.5))
    assert stats["samples"] == len(batch)
    assert stats["updates"] == 8  # 2 epochs × (32 / 8)
    assert len(stats["epochs"]) == 2
    for rec in stats["epochs"]:
        for key in ("total", "policy_loss", "value_loss", "aux_pi_loss", "entropy",
                    "approx_kl", "clip_frac", "ratio_mean", "illegal_prob_max"):
            assert np.isfinite(rec[key]), (key, rec[key])
        assert rec["illegal_prob_max"] == 0.0
    # 参数确实更新
    changed = sum(1 for p, q in zip(model.parameters(), before)
                  if not torch.equal(p.detach(), q))
    assert changed > 0
    # 更新后非法动作概率仍严格为 0（mask 必须杜绝非法动作）
    with torch.no_grad():
        logits = model(torch.from_numpy(batch.features[:8]),
                       torch.from_numpy(batch.cards[:8].astype(np.int64)))[0]
        probs = masked_probs_torch(logits, torch.from_numpy(batch.masks[:8]))
    illegal = probs.masked_fill(torch.from_numpy(batch.masks[:8]), 0.0)
    assert float(illegal.abs().max()) == 0.0
    assert torch.allclose(probs.sum(dim=-1), torch.ones(8), atol=1e-6)

    # mse value loss 也跑得通
    stats_mse = train_ppo(model, batch, PPOConfig(
        epochs=1, minibatch=16, lr=1e-4, seed=1, target_kl=10.0, value_loss="mse"))
    assert np.isfinite(stats_mse["epochs"][-1]["value_loss"])


def test_train_ppo_kl_early_stop():
    torch = _needs_torch()
    from hsbg.az.train.model import build_net

    torch.manual_seed(0)
    model = build_net(16)
    batch = _batch_from_model(model)
    stats = train_ppo(model, batch, PPOConfig(
        epochs=5, minibatch=8, lr=1e-2, seed=0, target_kl=1e-8, kl_early_stop=True))
    assert stats["stopped_early"] is True
    # 早停按 epoch 均值判断（首 epoch 的近似 KL 可能为负噪声），最多多跑 1 个 epoch
    assert 1 <= len(stats["epochs"]) <= 2
    assert stats["epochs"][-1]["kl_early_stopped"] is True


# ── 6. 入口脚本（不需要引擎：--help 在引擎检查前返回）───────────────────
def test_entry_script_help():
    script = os.path.join(ROOT, "scripts", "train_az_ppo.py")
    proc = subprocess.run([sys.executable, script, "--help"], cwd=ROOT,
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr
    for flag in ("--games", "--epochs", "--arch", "--device", "--out", "--seed",
                 "--sims", "--determinizations", "--lr", "--clip", "--collect-only"):
        assert flag in proc.stdout, f"入口脚本缺少参数 {flag}"


# ── 7. 引擎 smoke：1 局 MCTS 自对弈 + 1 epoch PPO + 固定 seed 评测 ──────
def test_engine_mcts_selfplay_ppo_smoke():
    pytest.importorskip("hsbg_engine")
    torch = _needs_torch()
    from hsbg.az import SearchConfig, search as az_search
    from hsbg.az.train.evaluate import EvalConfig, evaluate_policy
    from hsbg.az.train.model import build_net
    from hsbg.az.train.policies import make_policy
    from hsbg.az.train.ppo import PPOEvaluator, collect_ppo_batch

    torch.manual_seed(0)
    model = build_net(32)  # tiny：CPU 上 1 局 < ~10s
    evaluator = PPOEvaluator(model)
    cfg = CollectConfig(games=1, seed=123, max_steps=20000, behavior="net")
    search_cfg = SearchConfig(simulations=1, determinizations=1,
                              temperature=1.0, seed=0, dirichlet_epsilon=0.0)
    batch, meta = collect_ppo_batch(
        model, cfg, search_fn=az_search, search_config=search_cfg,
        eval_fn=evaluator, engine_backend="auto", seed=123)
    assert meta["truncated_games"] == 0, meta
    assert len(batch) > 0
    assert meta["search_calls"] > 0
    assert batch.validate() == [], batch.validate()
    # MCTS visit π 已作为辅助目标进入批次
    assert int(batch.has_pi.sum()) > 0

    stats = train_ppo(model, batch, PPOConfig(
        epochs=1, minibatch=32, lr=1e-3, seed=0, target_kl=10.0))
    assert np.isfinite(stats["epochs"][-1]["total"])
    assert stats["epochs"][-1]["illegal_prob_max"] == 0.0

    # 固定 seed 评测（search-off net vs 引擎 bot）；1 局可能 truncated，但必须合法
    pol = make_policy("net", evaluator=PPOEvaluator(model))
    res = evaluate_policy(pol, EvalConfig(games=1, seed=99001, max_steps=5000))
    assert res["games"] == 1
    assert res["games_finished"] + res["truncated_games"] == 1
    assert res["legal_action_rate"] == pytest.approx(1.0)
    assert res["decisions"] > 0

def test_forced_endturn_excluded_from_policy_objective():
    """forced EndTurn 是确定性守卫：记录 logprob=0，且 policy/aux 目标排除。"""
    records = _synthetic_records(n_games=1, decisions_per_seat=2)
    for rec in records:
        rec["forced"] = False
    records[0]["forced"] = True
    batch = build_batch_from_records(records)
    assert bool(batch.forced[0])
    assert not bool(batch.has_pi[0])
    # weighted clip surrogate：weight=0 的 forced 样本不影响 policy loss
    import torch
    ratio = torch.tensor([1.5, 1.2], dtype=torch.float32)
    adv = torch.tensor([1.0, 2.0], dtype=torch.float32)
    loss, _ = clipped_surrogate(ratio, adv, 0.2, weight=torch.tensor([0.0, 1.0]))
    solo, _ = clipped_surrogate(ratio[1:], adv[1:], 0.2)
    assert torch.allclose(loss, solo)


# ── 6. persistent PPOTrainer（Adam/LR/RNG 跨 update）────────────────────
def test_ppo_trainer_persists_adam_and_scheduler():
    _needs_torch()
    from hsbg.az.train.model import build_net
    from hsbg.az.train.ppo_trainer import PPOTrainer

    model = build_net(16)
    cfg = PPOConfig(device="cpu", epochs=1, minibatch=8, seed=11,
                    kl_early_stop=False, target_kl=0.0)
    trainer = PPOTrainer(model, cfg, lr_min_ratio=0.5, max_updates=10)
    batch = _batch_from_model(model, n_games=2, decisions_per_seat=3)
    lr0 = trainer.optimizer.param_groups[0]["lr"]
    s1 = trainer.update(batch)
    assert trainer.updates == 1
    assert s1["trainer_updates"] == 1
    assert s1["lr"] < lr0
    # Adam 状态已产生，不是每轮重建
    assert len(trainer.optimizer.state_dict()["state"]) > 0
    s2 = trainer.update(batch)
    assert trainer.updates == 2
    assert s2["trainer_updates"] == 2
    assert trainer.scheduler.last_epoch == 2


def test_ppo_trainer_state_roundtrip(tmp_path):
    _needs_torch()
    from hsbg.az.train.model import build_net
    from hsbg.az.train.ppo_trainer import PPOTrainer

    model = build_net(16)
    cfg = PPOConfig(device="cpu", epochs=1, minibatch=8, seed=23,
                    kl_early_stop=False, target_kl=0.0)
    trainer = PPOTrainer(model, cfg, lr_min_ratio=0.5, max_updates=10)
    batch = _batch_from_model(model, n_games=1, decisions_per_seat=2)
    trainer.update(batch)
    path = str(tmp_path / "trainer.pt")
    trainer.save(path)

    model2 = build_net(16)
    loaded = PPOTrainer.load(model2, path, device="cpu")
    assert loaded.updates == 1
    assert loaded.scheduler.last_epoch == 1
    assert loaded.lr_min_ratio == trainer.lr_min_ratio
    assert loaded.max_updates == trainer.max_updates
    assert loaded.optimizer.param_groups[0]["lr"] == pytest.approx(
        trainer.optimizer.param_groups[0]["lr"])
    assert loaded.rng.bit_generator.state == trainer.rng.bit_generator.state
    # 继续更新，optimizer/scheduler 状态延续
    loaded.update(batch)
    assert loaded.updates == 2


def test_kl_anchor_zero_at_stage_start_and_penalizes_drift():
    """KL anchor：stage 起点 KL≈0；策略漂移后 KL>0；anchor 参数自身不被更新。"""
    torch = _needs_torch()
    from hsbg.az.train.model import build_net
    from hsbg.az.train.ppo import forward_model, masked_log_softmax_torch, split_model_outputs
    from hsbg.az.train.ppo_trainer import PPOTrainer

    torch.manual_seed(0)
    model = build_net(16)
    batch = _batch_from_model(model)
    cfg = PPOConfig(device="cpu", value_loss="rank", pi_coef=0.0, anchor_coef=0.1)
    trainer = PPOTrainer(model, cfg)
    trainer.set_anchor()
    anchor_params = [p.detach().clone() for p in trainer.anchor_model.parameters()]

    mask_t = torch.from_numpy(np.ascontiguousarray(batch.masks.astype(bool)))
    cards_t = torch.from_numpy(np.ascontiguousarray(batch.cards.astype(np.int64)))
    feat_t = torch.from_numpy(np.ascontiguousarray(batch.features.astype(np.float32)))

    def _cur_logp() -> "torch.Tensor":
        with torch.no_grad():
            logits, _, _ = split_model_outputs(forward_model(model, feat_t, cards_t, mask_t))
            return masked_log_softmax_torch(logits, mask_t)

    def _kl(cur) -> float:
        a = trainer._anchor_logp(batch)
        kl = (cur.exp() * (cur - a)).masked_fill(~mask_t, 0.0).sum(dim=-1)
        return float(kl.mean())

    # 1) 起点：当前策略 == anchor -> KL ≈ 0
    assert _kl(_cur_logp()) == pytest.approx(0.0, abs=1e-4)
    # 2) 走一步 PPO：anchor 参数必须不变
    stats = trainer.update(batch)
    assert "anchor_kl" in stats["epochs"][0]
    for before, after in zip(anchor_params, trainer.anchor_model.parameters()):
        assert torch.equal(before, after), "anchor 不应被训练"
    # 3) 人为漂移后 KL 显著 > 0
    with torch.no_grad():
        for p in model.parameters():
            p.add_(torch.randn_like(p) * 0.05)
    assert _kl(_cur_logp()) > 1e-3
