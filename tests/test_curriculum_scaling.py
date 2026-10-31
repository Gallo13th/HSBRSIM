"""经济课程 / 缩放教师 / 过程价值 的单测。

覆盖：
1. ``curriculum.gold_mult_at`` 三阶段边界与 ``gold_for_turn`` 恒等（mult=1）；
2. lockstep 采集默认关闭（none+1.0）与显式 none+1.0 **逐位一致**（同 seed 2 iteration）；
3. 缩放教师：真实引擎状态上动作 100% 合法、同状态确定性；
4. ``teacher_bc_coef=0`` 逐位等价：有/无教师标签的 PPO 更新 weights/stats 完全相同；
5. 过程价值：目标提取、masked MSE、``process_head`` 不影响策略前向、coef=0 不动 head；
6. 入口脚本暴露三个新 CLI 开关。
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys

import numpy as np
import pytest

from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS
from hsbg.az.train.curriculum import (anneal_progress, gold_for_turn,
                                      gold_mult_at, curriculum_schedule)
from hsbg.az.train.ppo import (CollectConfig, PPOConfig, build_batch_from_arrays,
                               pack_records_arrays, train_ppo)
from hsbg.az.train.process_value import (consume_count, process_target,
                                         tavern_perm_buff)
from hsbg.az.train.scaling_teacher import (ScalingTeacher, in_scaling_window)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _needs_engine():
    return pytest.importorskip("hsbg_engine")


def _needs_torch():
    return pytest.importorskip("torch")


def _hash_arrays(packed: dict) -> str:
    h = hashlib.sha256()
    for k in sorted(packed):
        a = np.ascontiguousarray(packed[k])
        h.update(k.encode())
        h.update(str(a.dtype).encode())
        h.update(str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()


# ── 1. 课程 schedule ──────────────────────────────────────────────────────
def test_gold_schedule_boundaries():
    assert gold_mult_at(0, stage="none", mult=3.0) == 1.0
    assert gold_mult_at(10 ** 9, stage="none", mult=3.0) == 1.0
    # warmup：从 mult 线性降到 1.0
    assert gold_mult_at(0, stage="warmup", mult=3.0, anneal_decisions=100) == 3.0
    assert gold_mult_at(50, stage="warmup", mult=3.0, anneal_decisions=100) == 2.0
    assert gold_mult_at(100, stage="warmup", mult=3.0, anneal_decisions=100) == 1.0
    assert gold_mult_at(1000, stage="warmup", mult=3.0, anneal_decisions=100) == 1.0
    # anneal：前半保持，后半线性降
    assert gold_mult_at(0, stage="anneal", mult=3.0, anneal_decisions=100) == 3.0
    assert gold_mult_at(50, stage="anneal", mult=3.0, anneal_decisions=100) == 3.0
    assert gold_mult_at(75, stage="anneal", mult=3.0, anneal_decisions=100) == 2.0
    assert gold_mult_at(100, stage="anneal", mult=3.0, anneal_decisions=100) == 1.0
    # mult=1 时任何阶段都恒等
    for st in ("warmup", "anneal"):
        assert gold_mult_at(0, stage=st, mult=1.0) == 1.0
    assert anneal_progress(50, 100) == 0.5
    assert anneal_progress(200, 100) == 1.0
    with pytest.raises(ValueError):
        gold_mult_at(0, stage="warmup", mult=0.5)
    assert curriculum_schedule(stage="none")["curriculum_gold_mult"] == 1.0


def test_gold_for_turn_identity_and_multiplier():
    assert gold_for_turn(gold_now=10, carry=0, mult=1.0) == 10
    assert gold_for_turn(gold_now=13, carry=3, mult=1.0) == 13
    # 10 金收入 + 3 结余，×3 -> 3 + 30
    assert gold_for_turn(gold_now=13, carry=3, mult=3.0) == 33
    # 异常（gold_now < carry）按 0 收入，只留 carry
    assert gold_for_turn(gold_now=2, carry=5, mult=3.0) == 5


# ── 2. 默认关闭逐位等价（同 seed 2 iteration 采集）──────────────────────
def test_lockstep_default_bit_equivalent():
    _needs_engine()
    torch = _needs_torch()
    from hsbg.az.train.model import build_net
    from hsbg.az.train.parallel_collect import collect_ppo_lockstep
    from hsbg.az.train.ppo import PPOEvaluator

    torch.manual_seed(7)
    model = build_net(hidden=32, arch="tiny")
    ev = PPOEvaluator(model, device="cpu")

    def run(*, explicit: bool):
        hashes = []
        for it in range(2):
            cfg = CollectConfig(games=1, seed=1000 + it, opponent="bot",
                                behavior="net", lockstep=True, fast_act=False,
                                max_steps=20000)
            if explicit:
                cfg.curriculum_stage = "none"
                cfg.curriculum_gold_mult = 1.0
                cfg.teacher_bc = False
                cfg.process_value = False
            recs, _meta = collect_ppo_lockstep(
                model, cfg, eval_fn=ev, device="cpu",
                seed=1000 + it, gamemode="bot")
            hashes.append(_hash_arrays(pack_records_arrays(recs)))
        return hashes

    assert run(explicit=False) == run(explicit=True)


def test_curriculum_off_two_train_iters_bit_equivalent():
    """同 seed 2 个完整 iteration（采集+PPO 更新）在最坏情况下也逐位一致。"""
    _needs_engine()
    torch = _needs_torch()
    from hsbg.az.train.model import build_net
    from hsbg.az.train.parallel_collect import collect_ppo_lockstep
    from hsbg.az.train.ppo import PPOEvaluator

    def run(*, explicit: bool):
        torch.manual_seed(13)
        model = build_net(hidden=32, arch="tiny")
        ev = PPOEvaluator(model, device="cpu")
        cfgp = PPOConfig(epochs=1, minibatch=64, lr=1e-3, device="cpu",
                         seed=17, compile_train=0)
        hs = []
        for it in range(2):
            cfg = CollectConfig(games=1, seed=3000 + it, opponent="bot",
                                behavior="net", lockstep=True, fast_act=False,
                                max_steps=20000)
            if explicit:
                cfg.curriculum_stage = "none"
                cfg.curriculum_gold_mult = 1.0
            recs, _ = collect_ppo_lockstep(model, cfg, eval_fn=ev, device="cpu",
                                           seed=3000 + it, gamemode="bot")
            batch = build_batch_from_arrays(pack_records_arrays(recs),
                                            gamma=1.0, lam=0.95)
            train_ppo(model, batch, cfgp,
                      rng=np.random.default_rng(17))
            h = hashlib.sha256()
            for p in model.parameters():
                h.update(p.detach().numpy().tobytes())
            hs.append(h.hexdigest())
        return hs

    assert run(explicit=False) == run(explicit=True)


# ── 3. 教师合法率 / 确定性 ────────────────────────────────────────────────
def test_scaling_teacher_legal_and_deterministic():
    E = _needs_engine()
    sys.path.insert(0, ROOT)
    from scripts.engine_ceiling_probe import ScriptPolicy

    teacher = ScalingTeacher()
    pol = ScriptPolicy(mode="spell", curve="mid", cheat="tier6")
    g = E.Game(24680)
    n = 0
    bad = 0
    windows = 0
    while not g.is_over() and g.turn <= 12 and n < 400:
        t = g.turn
        for p in range(8):
            while g.needs_action(p) and g.turn == t:
                if p == 0:
                    view = json.loads(g.view(0))
                    mask = np.frombuffer(g.legal_mask(0), dtype=np.uint8).astype(bool)
                    ta1 = teacher.act_view(view)
                    ta2 = teacher.act_view(view)
                    assert ta1 == ta2, "教师必须确定性"
                    n += 1
                    if not (0 <= ta1 < len(mask) and mask[ta1]):
                        bad += 1
                    me = view.get("me") or {}
                    if in_scaling_window(me.get("gold"), me.get("tier")):
                        windows += 1
                    try:
                        g.step(0, pol.act(g, 0))
                    except Exception:
                        g.bot_play(0)
                        break
                else:
                    g.bot_play(p)
            if g.turn != t:
                break
        if g.turn == t:
            break
    assert n > 50
    assert bad == 0, f"{bad}/{n} 教师动作非法"
    assert windows > 0, "tier6 作弊局应至少进入一次缩放窗口"


# ── 4. teacher_bc_coef=0 逐位等价 ─────────────────────────────────────────
def _tiny_batch(with_teacher: bool):
    _needs_engine()
    try:
        from hsbg.az.train.model import build_net
        from hsbg.az.train.parallel_collect import collect_ppo_lockstep
        from hsbg.az.train.ppo import PPOEvaluator
    except Exception as exc:  # pragma: no cover
        pytest.skip(str(exc))
    model = build_net(hidden=32, arch="tiny")
    ev = PPOEvaluator(model, device="cpu")
    cfg = CollectConfig(games=1, seed=777, opponent="bot", behavior="net",
                        lockstep=True, fast_act=False, max_steps=20000,
                        teacher_bc=bool(with_teacher))
    recs, _ = collect_ppo_lockstep(model, cfg, eval_fn=ev, device="cpu",
                                   seed=777, gamemode="bot")
    packed = pack_records_arrays(recs)
    batch = build_batch_from_arrays(packed, gamma=1.0, lam=0.95)
    return batch


def test_teacher_bc_coef_zero_bit_equivalent():
    torch = _needs_torch()
    from hsbg.az.train.model import build_net

    b0 = _tiny_batch(with_teacher=False)
    # 人工注入一半教师标签（模拟 teacher_bc=1 的采集结果）
    b1 = copy.deepcopy(b0)
    ta = np.full(len(b1), -1, dtype=np.int16)
    ta[::2] = b1.actions[::2].astype(np.int16)
    b1.teacher_action = ta

    torch.manual_seed(11)
    m0 = build_net(hidden=32, arch="tiny")
    torch.manual_seed(11)
    m1 = build_net(hidden=32, arch="tiny")
    cfg = PPOConfig(epochs=1, minibatch=16, lr=1e-3, device="cpu", seed=3,
                    teacher_bc_coef=0.0)
    s0 = train_ppo(m0, b0, cfg)
    s1 = train_ppo(m1, b1, cfg)
    assert "teacher_bc_loss" not in s0 and "teacher_bc_loss" not in s1
    h = hashlib.sha256()
    for p0, p1 in zip(m0.parameters(), m1.parameters()):
        h.update(p0.detach().numpy().tobytes())
        assert np.array_equal(p0.detach().numpy(), p1.detach().numpy())
    # 有标签 + coef=0 时 stats 数值也不受影响（忽略耗时字段）
    for k in ("samples", "processed_samples", "updates"):
        assert s0[k] == s1[k]


# ── 5. 过程价值 ───────────────────────────────────────────────────────────
def test_process_targets_and_consume():
    player = {
        "stats": {"spells_cast": 7},
        "shop": [
            {"type": "minion", "atk": 5, "hp": 6, "base_atk": 3, "base_hp": 3,
             "breakdown": {"this_game_bonus": [2, 3]}},
            {"type": "minion", "atk": 4, "hp": 4, "base_atk": 4, "base_hp": 4,
             "breakdown": {"this_game_bonus": [0, 0]}},
        ],
    }
    assert tavern_perm_buff(player) == 5
    t = process_target(player, consume=4)
    assert len(t) == 3
    assert abs(t[0] - float(np.log1p(5))) < 1e-6
    assert abs(t[1] - float(np.log1p(7))) < 1e-6
    assert abs(t[2] - float(np.log1p(4))) < 1e-6
    log = ["a consumes b (1/2)", "x", "y consumes z (3/4)"]
    assert consume_count(log) == 2
    assert consume_count(log, prev=3) == 3


def test_process_head_does_not_change_policy_forward():
    _needs_engine()
    torch = _needs_torch()
    from hsbg.az.train.model import attach_process_head, build_net

    torch.manual_seed(5)
    model = build_net(arch="entity", d_model=32, n_layers=1, n_heads=4,
                      dropout=0.0, process_head=False)
    x = torch.randn(2, OBS_FLOATS)
    c = torch.randint(0, 10, (2, OBS_CARDS))
    m = torch.ones(2, N_ACTIONS, dtype=torch.bool)
    out0 = model(x, c, m)
    attach_process_head(model)
    assert model.process_head is not None
    out1 = model(x, c, m)
    for a, b in zip(out0, out1):
        assert np.array_equal(a.detach().numpy(), b.detach().numpy())
    logits, pred = model.forward_process(x, c, m)
    assert tuple(pred.shape) == (2, 3)
    assert np.array_equal(logits.detach().numpy(), out0[0].detach().numpy())


def test_process_value_coef_zero_and_positive():
    _needs_engine()
    torch = _needs_torch()
    from hsbg.az.train.model import build_net

    b = _tiny_batch(with_teacher=False)
    n = len(b)
    pt = np.full((n, 3), np.nan, dtype=np.float32)
    pt[: max(1, n // 2)] = np.asarray([[1.0, 2.0, 0.5]], dtype=np.float32)
    b.process_target = pt

    def make():
        torch.manual_seed(31)
        return build_net(arch="entity", d_model=32, n_layers=1, n_heads=4,
                         dropout=0.0, process_head=True)

    m0 = make()
    cfg0 = PPOConfig(epochs=1, minibatch=16, lr=1e-3, device="cpu", seed=4,
                     process_value_coef=0.0)
    head0 = [p.detach().clone() for p in m0.process_head.parameters()]
    s0 = train_ppo(m0, b, cfg0)
    assert "process_value_loss" not in s0
    for a, c in zip(head0, m0.process_head.parameters()):
        assert torch.equal(a, c.detach())
    m1 = make()
    cfg1 = PPOConfig(epochs=1, minibatch=16, lr=1e-3, device="cpu", seed=4,
                     process_value_coef=0.05)
    s1 = train_ppo(m1, b, cfg1)
    assert "process_value_loss" in s1 and s1["process_samples"] > 0


# ── 6. CLI 开关 ───────────────────────────────────────────────────────────
def test_train_cli_exposes_scaling_flags():
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "train_entity_sync.py"), "--help"],
        capture_output=True, text=True, timeout=120)
    assert out.returncode == 0
    for flag in ("--gold-curriculum", "--curriculum-stage",
                 "--curriculum-gold-mult", "--curriculum-anneal-decisions",
                 "--teacher-bc-coef", "--process-value-coef"):
        assert flag in out.stdout
