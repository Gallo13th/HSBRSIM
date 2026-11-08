"""轻量战斗沙盒（``hsbg/az/train/combat_sandbox.py``）的契约测试。

只测**契约**，不测强度：
1. 配置是加法（默认值不改变 ``SandboxConfig`` 的旧行为）；
2. 引擎配置真的**去掉伤害封印**且 ``num_players=2``；
3. ``_inject_gold`` **不再把血回满**（否则战斗伤害没有后果）；
4. 真跑 3 回合：每回合有 1 场战斗、伤害/胜负记账自洽、``hp`` 单调不增；
5. 同 seed 同动作序列逐位一致（确定性）；
6. ``summarize_combat`` 的字段齐备。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("hsbg_engine")

from hsbg.az.train.combat_sandbox import (CombatConfig, CombatSandbox,  # noqa: E402
                                          HP_START, summarize_combat)
from hsbg.az.train.economy_sandbox import END_TURN, SandboxConfig  # noqa: E402


def _cfg(**kw):
    base = dict(turns=3, gold_mode="fixed", gold_per_turn=10, action_cap=40,
                num_players=8, trinkets=True, lobby_types=(), reward="log_strength",
                seed=7)
    base.update(kw)
    return CombatConfig(**base)


def test_config_is_additive():
    """CombatConfig 对 SandboxConfig 是加法：默认值必须等于旧行为。"""
    old = SandboxConfig(turns=3, gold_mode="fixed", gold_per_turn=10)
    new = CombatConfig(turns=3, gold_mode="fixed", gold_per_turn=10)
    for k, v in old.__dict__.items():
        assert getattr(new, k) == v, k
    assert new.opponent_quantile in ("p50", "p75", "p90")
    assert new.hp_start == HP_START == 30
    assert new.refresh_opponent is True and new.combat_reward_coef == 1.0


def test_engine_config_removes_damage_caps():
    env = CombatSandbox(_cfg())
    cfg = env.cfg.engine_config()
    assert "damage_caps" not in cfg and "damage_cap_until_alive" not in cfg
    assert int(cfg["num_players"]) == 2
    assert int(cfg["max_turns"]) == 3
    # 旧的 EconomySandbox 仍然是封印状态（证明我们没有改父类语义）
    from hsbg.az.train.economy_sandbox import EconomySandbox
    assert "damage_caps" in SandboxConfig(turns=3).engine_config()


def test_inject_gold_does_not_heal():
    """金币注入不能写 ``health``：否则每回合回满、战斗伤害被抹掉。"""
    env = CombatSandbox(_cfg())
    env.reset()
    # 先人为把血打低，再走一次回合开始注入
    env.g.debug('{"cmd": "set_player", "p": 0, "health": 11}')
    assert env._hp(0) == 11
    env._inject_gold(2)
    assert env._hp(0) == 11, "回合开始不能回血"


def test_three_turns_have_combat_and_consistent_bookkeeping():
    env = CombatSandbox(_cfg())
    obs = env.reset()
    assert obs.features.shape == (3227,) and obs.mask.shape == (245,)
    hp_prev = env._hp(0)
    for _ in range(400):
        if env.done:
            break
        obs = env.step(END_TURN)[0]
        hp_now = env._hp(0) if not env.done else env._combat["hp"]
        assert hp_now <= hp_prev or env.done, "血量不能回升"
        hp_prev = hp_now
    ep = env.episode_summary()
    assert ep["combat"] is True
    assert 1 <= ep["combats"] <= 3
    assert ep["wins"] + ep["losses"] + ep["ties"] == ep["combats"]
    assert abs(ep["win_rate"] - ep["wins"] / ep["combats"]) < 1e-9
    assert ep["damage_taken"] >= 0 and ep["damage_dealt"] >= 0
    assert len(ep["combat_turns"]) == ep["combats"]
    # Σ 口径仍在（父类）
    assert "sigma_t15" in ep and "tier_t15" in ep


def test_deterministic_same_seed():
    def run():
        env = CombatSandbox(_cfg())
        env.reset()
        sig = []
        for _ in range(200):
            if env.done:
                break
            env.step(END_TURN)
            sig.append((env._hp(0), env._combat["wins"], env._combat["losses"]))
        ep = env.episode_summary()
        return sig, ep["sigma_t15"], ep["damage_taken"]

    a = run()
    b = run()
    assert a == b, "同 seed 同动作序列必须逐位一致"


def test_summarize_combat_fields():
    eps = [{"sigma_t15": 100, "sigma_t12": 50, "win_rate": 1.0, "wins": 3,
            "damage_taken": 0, "damage_dealt": 12, "killed": False, "hp_end": 30},
           {"sigma_t15": 60, "sigma_t12": 30, "win_rate": 0.0, "wins": 0,
            "damage_taken": 20, "damage_dealt": 0, "killed": True, "hp_end": 0}]
    rep = summarize_combat(eps)
    assert rep["games"] == 2
    assert rep["win_rate"] == pytest.approx(0.5)
    assert rep["damage_taken_mean"] == pytest.approx(10.0)
    assert rep["killed_rate"] == pytest.approx(0.5)
    assert rep["hp_end_mean"] == pytest.approx(15.0)
    assert math.isfinite(rep["sigma_t15_p50"])
