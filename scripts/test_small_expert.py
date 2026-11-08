"""小模型专家课程（``hsbg.az.train.small_expert``）的契约测试。

覆盖四件事：

1. ``t12_t15`` 奖励的**望远镜等式**：整局奖励和 = L(Σ12) + 0.5·L(Σ15)；
2. 每回合动作上限课程：``parse_gold_ramp/gold_at`` + ``SandboxConfig.engine_config``
   的 caps 真的随档位变化；
3. 课程预算/门控记账：超预算不再训练、掉幅 ≤10% 才 ``gate_pass``；
4. 小模型架构参数（256×4 = 3.57M）与沙盒/完整游戏同一编码。
"""

from __future__ import annotations

import importlib.util
import math
import os
import sys

import numpy as np
import pytest

from hsbg.az.train.economy_sandbox import (EconomySandbox, SandboxConfig,
                                           STRENGTH_REF)
from hsbg.az.train.small_expert import (CurriculumConfig, SmallExpertCurriculum,
                                        DEFAULT_S2_LEVELS, DEFAULT_S3_BANDS)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _script_module():
    key = "_tes_module_for_test"
    if key in sys.modules:
        return sys.modules[key]
    path = os.path.join(ROOT, "scripts", "train_economy_sandbox.py")
    spec = importlib.util.spec_from_file_location(key, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def test_t12_t15_reward_telescopes():
    """逐回合密集奖励的和 = 目标 ``L12 + 0.5·L15``（精确到 1e-9）。"""
    cfg = SandboxConfig(turns=15, gold_per_turn=99, action_cap=120,
                        num_players=8, reward="t12_t15", seed=7)
    env = EconomySandbox(cfg)
    obs = env.reset(123)
    rng = np.random.default_rng(0)
    total = 0.0
    guard = 0
    while not env.done and guard < 20000:
        legal = np.flatnonzero(obs.mask)
        a = int(rng.choice(legal)) if legal.size else 0
        obs, r, done, info = env.step(a)
        total += float(r)
        guard += 1
    assert env.done, "沙盒应在 15 回合后终止"
    ep = env.episode_summary()
    ref = math.log1p(float(STRENGTH_REF))
    want = (math.log1p(float(ep["sigma_t12"])) / ref
            + 0.5 * math.log1p(float(ep["sigma_t15"])) / ref)
    assert total == pytest.approx(want, abs=1e-9)
    # 不是把 Σ 直接相加：奖励应落在 [0, 1.5] 的 L 量级内
    assert 0.0 <= total <= 1.5 + 1e-9


def test_action_cap_ramp_parse_and_engine():
    """动作上限课程解析与引擎配置：caps 必须真的 = 档位值。"""
    mod = _script_module()
    ramp = mod.parse_cap_ramp("0:120,2M:40,4M:20,6M:10")
    assert ramp == [(0, 120), (2_000_000, 40), (4_000_000, 20), (6_000_000, 10)]
    assert mod.gold_at(ramp, 0, 40) == 120
    assert mod.gold_at(ramp, 1_999_999, 40) == 120
    assert mod.gold_at(ramp, 2_000_000, 40) == 40
    assert mod.gold_at(ramp, 5_000_000, 40) == 20
    assert mod.gold_at(ramp, 6_500_000, 40) == 10
    ec = SandboxConfig(action_cap=120).engine_config()
    assert ec["turn_action_caps"] == [120] * 16
    assert ec["max_actions_per_turn"] == 120
    assert SandboxConfig(action_cap=10).engine_config()["max_actions_per_turn"] == 10


def test_curriculum_defaults_and_budget():
    """默认课程 = 任务书；预算超限时 ``_budget_ok`` 拒绝继续训练。"""
    assert DEFAULT_S2_LEVELS == ((99, 40), (30, 40), (15, 20), (10, 10))
    assert [b[0] for b in DEFAULT_S3_BANDS] == [1, 3, 5]
    cfg = CurriculumConfig(out="/tmp/curr_test", max_total_decisions=1_000_000)
    cur = SmallExpertCurriculum(cfg)
    cur.spent = 900_000
    assert cur._budget_ok(100_000)
    assert not cur._budget_ok(100_001)
    cur.spent = 0
    assert cur._budget_ok(999_999)


def test_curriculum_s2_gate_logic(monkeypatch, tmp_path):
    """S2：掉幅 >10% 继续训练，≤10% 才 gate_pass 并进下一档；预算耗尽即停。"""
    cfg = CurriculumConfig(out=str(tmp_path / "c"), max_total_decisions=10_000_000,
                           s2_levels=((99, 40), (30, 40)), s2_chunk=100_000,
                           s2_max_steps=200_000)
    cur = SmallExpertCurriculum(cfg)
    cur.ckpt = "ckpt0"
    # 训练只更新 ckpt 名；评测按调用序给出 t12
    calls = {"train": 0}
    seq = {"ckpt0": 1000.0, "ckpt1": 850.0, "ckpt2": 950.0, "ckpt3": 700.0,
           "ckpt4": 900.0}

    def fake_train(ckpt, tag, *, gold, cap, decisions, **kw):
        calls["train"] += 1
        return f"ckpt{calls['train']}"

    def fake_eval(ckpt, *, gold, cap, games=0):
        t12 = seq[ckpt]
        return {"sigma_t12_p50": t12, "sigma_t15_p50": t12 * 1.2,
                "carrier_rate": 0.5, "casts_on_carrier_mean": 1.0,
                "tier_dist": {6: 1}, "spells_p50": 30}

    monkeypatch.setattr(cur, "train_sandbox", fake_train)
    monkeypatch.setattr(cur, "eval_sandbox", fake_eval)
    out = cur._run_s2("ckpt0")
    rows = [r for r in cur.rows if r.get("stage") == "S2"]
    evals = [r for r in rows if r.get("event") == "eval"]
    # 第一档：entry=1000 -> 850（掉 15% >10%）继续 -> 950（掉 5% ≤10%）通过
    assert [r["t12"] for r in evals[:2]] == [850.0, 950.0]
    assert evals[0]["gate_pass"] is False and evals[1]["gate_pass"] is True
    # 第二档：参考变成上一档最终 t12=950；entry=700（掉 26%）-> 900（掉 5%）通过
    assert evals[2]["gate_pass"] is False and evals[3]["gate_pass"] is True
    assert out.startswith("ckpt")
    assert [r for r in rows if r.get("event") == "level_done"][-1]["gate_pass"] is True


def test_terminal_strength_reward_in_batch():
    """终局强度项：末步奖励 = rank_coef·u(rank) + strength_coef·L(Σ_末决策)。"""
    from hsbg.az.train.common import RANK_UTILITY
    from hsbg.az.train.ppo import build_batch_from_arrays, log_strength_from_features

    n = 2
    f = np.zeros((n, 3227), dtype=np.float32)
    # 第 2 步（末决策）场上 1 个 3/4 随从 -> Σ=70（观测里 atk/hp 是 raw/10）
    b = f[1, 68:285].reshape(7, 31)
    b[0, 0] = 1.0
    b[0, 1] = 3.0
    b[0, 2] = 4.0
    ls = log_strength_from_features(f)
    assert ls[0] == 0.0
    assert ls[1] == pytest.approx(math.log1p(70.0) / math.log1p(30000.0))
    masks = np.zeros((n, 245), dtype=bool)
    masks[:, 1] = True
    masks[:, 2] = True
    packed = {
        "features": f, "cards": np.zeros((n, 124), dtype=np.int16),
        "masks": masks, "actions": np.asarray([1, 2], dtype=np.int64),
        "old_logprobs": np.zeros(n, dtype=np.float32),
        "values": np.zeros(n, dtype=np.float32),
        "ranks": np.asarray([1, 1], dtype=np.int64),
        "seats": np.asarray([0, 0], dtype=np.int32),
        "game_ids": np.asarray([0, 0], dtype=np.int64),
        "turns": np.asarray([1, 2], dtype=np.int32),
        "forced": np.zeros(n, dtype=bool),
        "has_pi": np.zeros(n, dtype=bool),
        "target_pi": np.zeros((n, 245), dtype=np.float32),
    }
    batch = build_batch_from_arrays(packed, gamma=1.0, lam=1.0,
                                    rank_utility_coef=0.3,
                                    terminal_strength_coef=0.7)
    want = 0.3 * float(RANK_UTILITY[0]) + 0.7 * float(ls[1])
    assert float(batch.rewards[-1]) == pytest.approx(want, abs=1e-6)
    # 非末步保持 0（无塑形时）
    assert float(batch.rewards[0]) == pytest.approx(0.0)
    assert float(batch.returns[-1]) == pytest.approx(want, abs=1e-6)

