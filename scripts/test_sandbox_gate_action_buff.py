"""闸门 1/2 的契约测试：``--action-cap-per-gold K`` 与 ``--tavern-buff-scale S``。

对应 ``docs/GATE_ACTION_BUFF.md``（结论）与 ``docs/COMPOUND_INCOME.md`` §5.2 的第 1/2 条：

**闸门 1（动作额度 ∝ 收入）**
- 语义：每回合有效动作上限 = ``action_cap + floor(回合开始金币 / K)``（``K=0`` = 关）；
- 词法：``K=0`` 时 ``engine_config()`` 与改动前逐位相同、动作流 sha 与改动前相同；
- 生效：``K>0`` 时额度按金币算、额度用尽后 mask 只剩 EndTurn；
- 组合：与 ``gold_mode``（fixed/add/growth）与 ``action_cap``（= 训练脚本的
  ``--sandbox-action-cap-ramp`` 切档后重建的环境）无冲突。

**闸门 2（酒馆永久 buff 的 S 倍）**
- 默认 ``S=1.0`` 逐位等价（不取 view、不改状态、action sha 相同）；
- ``tavern_aura_of()`` 与引擎 ``recruit.rs::tavern_aura`` 同口径（全体/元素/种族三项）；
- ``S>1`` 时酒馆随从的 buff 部分被补到 ``S×``（按槽 ``sid`` 记账，幂等）；
- 真引擎路径：``give_trinket`` 触发的 ``on_attach`` 酒馆 aura 会被按 S 放大。
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

pytest.importorskip("hsbg_engine")

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    ACTION_CAP_PER_GOLD_GOLD_BOUND, ACTION_CAP_PER_GOLD_MAX_EXTRA, END_TURN,
    EconomySandbox, SandboxConfig, SandboxPolicies, run_episode, summarize)


def _cfg(**kw):
    base = dict(turns=15, gold_per_turn=30, action_cap=40, trinkets=True)
    base.update(kw)
    return SandboxConfig(**base)


def _act(mask) -> int:
    if mask[END_TURN]:
        return END_TURN
    return int(np.flatnonzero(mask)[0])


def _sha(acts) -> str:
    return hashlib.sha256(",".join(str(a) for a in acts).encode()).hexdigest()


def _run_script(cfg, seed: int, policy: str):
    """跑一局并返回 (env, 动作流)。"""
    env = EconomySandbox(cfg)
    obs = env.reset(int(seed))
    pol = SandboxPolicies(env.g, policy, seed=0)
    acts = []
    while not env.done:
        a = pol.act(env.g, obs.mask)
        acts.append(int(a))
        obs, _r, _d, _i = env.step(int(a))
    return env, acts


# ── 0. 默认逐位等价（改动前的 sha 指纹）────────────────────────────────────

#: 改动前的动作流 sha（``git show HEAD:hsbg/az/train/economy_sandbox.py`` 那一版；
#: 引擎 37.0.0.255790）。默认 ``K=0`` / ``S=1.0`` 必须逐位复现。
FROZEN_SHA = {
    ("random", "fixed", 0): "b2b94ce9b09e060e1ccd5d47ddb2ac4626a6fc92f90031a7598ed994c35b73ed",
    ("spell", "fixed", 1): "8ea4c40a0dc2a5877791b40083cb5fa0892bd4bf3afc389d48e2effe0dafd5bf",
    ("greedy", "fixed", 2): "327bae9642d31a603ed0ff5d5b27ed2f234475c5ec873f46d9a39449a08979c3",
    ("teacher", "fixed", 0): "993bc7bdb78e8bad92e3831604dc639a86e8df4d8aeb34011f10e632eaf28f11",
}


@pytest.mark.parametrize("policy,seed", [("random", 0), ("spell", 1),
                                         ("greedy", 2), ("teacher", 0)])
def test_default_switch_off_keeps_bitwise_action_stream(policy, seed):
    """``K=0`` + ``S=1.0``（两个开关都默认关）的动作流与改动前逐位一致。"""
    env, acts = _run_script(_cfg(), seed, policy)
    assert _sha(acts) == FROZEN_SHA[(policy, "fixed", seed)]
    ep = env.episode_summary()
    # 两个开关默认关时**不新增**任何度量键（旧输出逐位不变）
    assert "actions_total" not in ep
    assert "tavern_extra_total" not in ep
    assert env._tavern_rescale_calls == 0


def test_default_growth_mode_sha_unchanged():
    """growth 收入档（G15 口径）下默认关的 sha 也不变。"""
    env, acts = _run_script(_cfg(gold_mode="growth", gold_growth_rate=0.15,
                                gold_per_carrier=2), 1, "spell")
    assert _sha(acts) == \
        "22639e648514d25b2d68ab53085a0dd4f64d46102ec0f8b532efb2fb88705ed1"
    assert env.episode_summary()["sigma_t15"] == 2498


def test_default_engine_config_unchanged():
    """``K=0`` 时 ``engine_config()`` 与改动前完全相同（turn_action_caps 全是 action_cap）。"""
    cfg = _cfg()
    eng = json.loads(cfg.engine_json())
    assert eng["turn_action_caps"] == [40] * 16
    assert eng["max_actions_per_turn"] == 40
    assert cfg.engine_cap() == 40


# ── 1. 闸门 1：额度公式 ────────────────────────────────────────────────────


def test_action_cap_per_gold_formula():
    """``cap(t) = action_cap + floor(gold_start / K)``；``K=0`` 恒为 ``action_cap``。"""
    c0 = _cfg(action_cap_per_gold=0)
    assert [c0.action_cap_for_turn(g) for g in (0, 9, 30, 99)] == [40, 40, 40, 40]
    c3 = _cfg(action_cap_per_gold=3)
    assert c3.action_cap_for_turn(0) == 40          # 没钱 = 基础额度
    assert c3.action_cap_for_turn(2) == 40          # 2//3 = 0
    assert c3.action_cap_for_turn(3) == 41          # 3 金 = +1 动作
    assert c3.action_cap_for_turn(30) == 50         # 任务口径：30 金 → +10 动作
    assert c3.action_cap_for_turn(99) == 73         # 99 金 → +33 动作
    # 负金币（引擎理论上不会给）不扣额度
    assert c3.action_cap_for_turn(-5) == 40


def test_engine_cap_relaxes_only_when_gate_on():
    """``K>0`` 时引擎额度被放宽到「最高可能金币 / K」，且不超过上限。"""
    assert _cfg(action_cap_per_gold=3).engine_cap() == 40 + 99 // 3
    assert _cfg(action_cap_per_gold=3, gold_cap=0).engine_cap() == \
        40 + min(ACTION_CAP_PER_GOLD_MAX_EXTRA, ACTION_CAP_PER_GOLD_GOLD_BOUND // 3)
    assert _cfg(action_cap_per_gold=1, gold_cap=0).engine_cap() == \
        40 + ACTION_CAP_PER_GOLD_MAX_EXTRA
    assert _cfg(action_cap_per_gold=3, action_cap=120).engine_cap() == 120 + 33


def test_action_cap_per_gold_binds_the_mask():
    """额度用尽 → mask 只剩 EndTurn（引擎额度被放宽，真上限由沙盒施加）。"""
    env = EconomySandbox(_cfg(action_cap=3, action_cap_per_gold=3, trinkets=False))
    obs = env.reset(3)
    # 本回合额度 = 3 + 30//3 = 13
    assert env._turn_cap == 13
    env._turn_actions = 12
    assert not obs.mask.all()
    m = env._apply_action_cap(env._mask(env.g, 0))
    assert m[END_TURN] and m.sum() > 1          # 还有额度：原样放行
    env._turn_actions = 13
    m = env._apply_action_cap(env._mask(env.g, 0))
    assert m[END_TURN] and m.sum() == 1         # 额度用尽：只剩 EndTurn
    # 默认关时**不**掩任何东西（原对象返回）
    env2 = EconomySandbox(_cfg(action_cap=3, trinkets=False))
    env2.reset(3)
    raw = env2._mask(env2.g, 0)
    assert env2._apply_action_cap(raw) is raw


def test_action_cap_per_gold_gets_more_actions_than_base_cap():
    """随机策略下：额度 13 的一档会真的用掉 > 基础额度 3 的动作。"""
    eps = {}
    for tag, kw in (("base", dict(action_cap=3)),
                    ("gate", dict(action_cap=3, action_cap_per_gold=3))):
        cfg = _cfg(trinkets=False, **kw)
        ep = run_episode(cfg, 5, "random")
        eps[tag] = ep
    # 决策数（含 EndTurn）与「自主动作数」（只在新口径下记录）
    assert eps["gate"]["decisions"] > eps["base"]["decisions"]
    assert eps["gate"]["turns_cap_bound"] > 0
    assert max(eps["gate"]["actions_hist"]) > 3
    # 每回合都不会超过按金币算的额度
    for acts, cap in zip(eps["gate"]["actions_hist"], eps["gate"]["action_cap_eff_hist"]):
        assert acts <= cap


def test_action_cap_per_gold_tracks_gold_modes():
    """额度跟着**回合开始金币**走：fixed 恒定、growth 递增、add 线性。"""
    for mode, kw, expect_inc in (
            ("fixed", {}, False),
            ("add", dict(gold_add=5), False),
            ("growth", dict(gold_growth_rate=0.15, gold_per_carrier=2), True)):
        cfg = _cfg(gold_mode=mode, action_cap_per_gold=3, trinkets=False, **kw)
        ep = run_episode(cfg, 2, "end")
        assert len(ep["action_cap_eff_hist"]) == 15
        for g, cap in zip(ep["gold_start_hist"], ep["action_cap_eff_hist"]):
            assert cap == 40 + g // 3
        if mode == "fixed":
            assert ep["action_cap_eff_hist"] == [50] * 15
        if expect_inc:
            assert ep["action_cap_eff_hist"][-1] > ep["action_cap_eff_hist"][0]
        assert ep["action_cap_eff_max"] == max(ep["action_cap_eff_hist"])


def test_action_cap_per_gold_no_conflict_with_cap_ramp_and_trinkets():
    """与「动作额度课程」（切档 = ``cfg.replaced(action_cap=…)`` 重建环境）及饰品开关组合。"""
    for trinkets in (None, True, False):
        for cap in (20, 40, 120):
            cfg = _cfg(action_cap=cap, action_cap_per_gold=3, trinkets=trinkets,
                       gold_mode="growth", gold_growth_rate=0.15, gold_per_carrier=2)
            cfg.validate()
            ep = run_episode(cfg, 11, "end")
            assert ep["turns"] == 15
            # 第 1 回合的额度按**回合开始的实际金币**算（add/growth 不覆写引擎补币：
            # growth 首回合 = 引擎 3 + 注入 30 = 33 → +11）
            assert ep["action_cap_eff_hist"][0] == cap + ep["gold_start_hist"][0] // 3
            for g, c in zip(ep["gold_start_hist"], ep["action_cap_eff_hist"]):
                assert c == cap + g // 3
            # 额度课程切档的路径：replaced() 保留闸门参数
            cfg2 = cfg.replaced(action_cap=80, gold_per_turn=45)
            assert cfg2.action_cap_per_gold == 3
            assert cfg2.action_cap_for_turn(45) == 80 + 15


def test_validate_rejects_bad_gate_args():
    for kw in (dict(action_cap_per_gold=-1), dict(tavern_buff_scale=0.5),
               dict(tavern_buff_scale=0.0)):
        with pytest.raises(ValueError):
            _cfg(**kw).validate()
    _cfg(action_cap_per_gold=3, tavern_buff_scale=1.0).validate()
    _cfg(action_cap_per_gold=0, tavern_buff_scale=4.0).validate()


# ── 2. 闸门 2：aura 复算 ───────────────────────────────────────────────────


def test_tavern_aura_of_matches_engine_composition():
    """``tavern_aura_of`` 与引擎同口径：全体 + 元素 + 种族掩码三项。"""
    st = {"tavern_atk": 3, "tavern_hp": 4,
          "tavern_elemental_atk": 5, "tavern_elemental_hp": 6,
          "tavern_race": [[1 << 1, 7, 8]]}          # DEMON
    f = EconomySandbox.tavern_aura_of
    assert f(st, ["BEAST"]) == (3, 4)
    assert f(st, ["ELEMENTAL"]) == (8, 10)
    assert f(st, ["DEMON"]) == (10, 12)
    assert f(st, ["DEMON", "ELEMENTAL"]) == (15, 18)
    assert f({}, ["BEAST"]) == (0, 0)


def test_tavern_buff_scale_injects_exactly_s_minus_one_times_aura(monkeypatch):
    """S=3：酒馆随从的 buff 部分被补到 3×；按槽幂等（冻结不会被重复加倍）。"""
    env = EconomySandbox(_cfg(tavern_buff_scale=3.0, trinkets=False))
    env.reset(4)
    # 用可控的 aura 替代引擎读数：每张酒馆随从的永久 buff = +2/+3
    monkeypatch.setattr(EconomySandbox, "tavern_aura_of",
                        staticmethod(lambda stats, races: (2, 3)))
    before = {s["sid"]: (s["atk"], s["hp"])
              for s in json.loads(env.g.view(0))["me"]["shop"]
              if s.get("type") == "minion"}
    assert before, "开局酒馆应该有随从"
    added = env.rescale_tavern_shop()
    after = {s["sid"]: (s["atk"], s["hp"])
             for s in json.loads(env.g.view(0))["me"]["shop"]
             if s.get("type") == "minion"}
    n = len(before)
    assert added == n * (2 * (3 - 1) + 3 * (3 - 1))       # (S−1)×(2+3) 每张
    for sid, (a, h) in before.items():
        assert after[sid] == (a + 4, h + 6)
    assert env._tavern_extra_atk == 4 * n
    assert env._tavern_extra_hp == 6 * n
    # 幂等：同一批随从再补一次不会再加
    assert env.rescale_tavern_shop() == 0
    assert env._tavern_extra_atk == 4 * n


def test_tavern_buff_scale_real_engine_trinket(monkeypatch):
    """真引擎路径：``give_trinket`` 的 on_attach 酒馆 aura（+2/+2）被按 S 放大。"""
    env = EconomySandbox(_cfg(tavern_buff_scale=3.0, trinkets=False))
    env.reset(7)
    env.g.debug(json.dumps({"cmd": "give_trinket", "p": 0,
                            "card": "BG30_MagicItem_879t"}))   # Dalaran Cheese Wheel
    st = json.loads(env.g.view(0))["me"]["stats"]
    assert (st["tavern_atk"], st["tavern_hp"]) == (2, 2)
    shop = [s for s in json.loads(env.g.view(0))["me"]["shop"]
            if s.get("type") == "minion"]
    assert shop and all((s["atk"], s["hp"]) for s in shop)
    added = env.rescale_tavern_shop()
    shop2 = {s["sid"]: (s["atk"], s["hp"]) for s in json.loads(env.g.view(0))["me"]["shop"]
             if s.get("type") == "minion"}
    assert added == len(shop) * (2 + 2) * (3 - 1)
    for s in shop:
        assert shop2[s["sid"]] == (s["atk"] + 4, s["hp"] + 4)
    # 默认 S=1.0 时同一条路径**不动**任何东西
    env1 = EconomySandbox(_cfg(tavern_buff_scale=1.0, trinkets=False))
    env1.reset(7)
    env1.g.debug(json.dumps({"cmd": "give_trinket", "p": 0,
                             "card": "BG30_MagicItem_879t"}))
    s0 = {s["sid"]: (s["atk"], s["hp"]) for s in json.loads(env1.g.view(0))["me"]["shop"]
          if s.get("type") == "minion"}
    assert env1.rescale_tavern_shop() == 0
    s1 = {s["sid"]: (s["atk"], s["hp"]) for s in json.loads(env1.g.view(0))["me"]["shop"]
          if s.get("type") == "minion"}
    assert s0 == s1
    assert env1._tavern_rescale_calls == 0


def test_tavern_buff_scale_episode_metrics():
    """S=3 的一局：注入量 > 0、t15 计量器按 S 折算、汇总里有对应键。"""
    cfg = _cfg(tavern_buff_scale=3.0, gold_per_turn=30)
    env, _acts = _run_script(cfg, 1, "spell")
    ep = env.episode_summary()
    assert ep["tavern_buff_scale"] == 3.0
    assert ep["tavern_buff_scaled_t15"] == 3 * ep["tavern_buff_t15"]
    assert ep["tavern_rescale_calls"] >= 15            # 每回合开始至少一次
    if ep["tavern_buff_t15"] > 0:                      # 有 buff 才有注入
        assert ep["tavern_extra_total"] > 0
    rep = summarize([ep])
    assert rep["tavern_extra_p50"] == float(ep["tavern_extra_total"])
    assert rep["tavern_buff_scaled_p50"] == float(ep["tavern_buff_scaled_t15"])


# ── 3. 两个闸门一起开 ──────────────────────────────────────────────────────


def test_both_gates_run_together():
    """K=3 + S=3 + growth + 饰品：15 回合跑完，动作合法，两套度量都在。"""
    cfg = _cfg(action_cap_per_gold=3, tavern_buff_scale=3.0, gold_mode="growth",
               gold_growth_rate=0.15, gold_per_carrier=2)
    env, acts = _run_script(cfg, 0, "spell")
    ep = env.episode_summary()
    assert ep["turns"] == 15
    assert all(0 <= a < 245 for a in acts)
    assert "actions_total" in ep and "tavern_extra_total" in ep
    assert ep["action_cap_eff_max"] > 40
    for acts_n, cap in zip(ep["actions_hist"], ep["action_cap_eff_hist"]):
        assert 0 <= acts_n <= cap
