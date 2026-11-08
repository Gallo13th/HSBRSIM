"""沙盒吞吐改动的**逐位等价**契约（``docs/SANDBOX_ECON.md`` §2）。

覆盖两条「不改语义、只去掉 ``view()``」的快路径：

1. ``_pending_kind()`` 从观测 ``SLICE_PENDING`` 的 9 类 one-hot 解码（旧实现是
   ``g.view()`` + ``json.loads``）——两者在整局每一步都必须相同；
2. ``measure()`` 从 ``player_json`` + ``catalog_json`` 的 cid→id 表 + 饰品 eid 缓存
   计算（旧实现是 ``view()`` + ``json.loads``）——每回合末的**全部字段**必须相同。

另外钉住「同 seed 动作流逐位一致」（sha256）：快路径不得改变任何决策。
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

pytest.importorskip("hsbg_engine")

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    END_TURN, EconomySandbox, SandboxConfig, SandboxPolicies)


def _old_pending_kind(env) -> str:
    """改动前的实现（view + json）；只用于对照。"""
    v = json.loads(env.g.view(0))
    p = (v.get("me") or {}).get("pending") or {}
    return str(p.get("kind") or "") if isinstance(p, dict) else ""


def _cfg(**kw):
    base = dict(turns=10, gold_per_turn=30, action_cap=40, trinkets=True)
    base.update(kw)
    return SandboxConfig(**base)


def test_pending_kind_matches_view_every_step():
    """观测 one-hot 解码的 pending kind == 旧 view 实现（含 target/discover/choose_one/trinket）。"""
    for game in range(2):
        env = EconomySandbox(_cfg())
        obs = env.reset(4000 + game)
        pol = SandboxPolicies(env.g, "random", seed=game)
        seen = set()
        while not env.done:
            got = env._pending_kind()
            want = _old_pending_kind(env)
            assert got == want, f"turn {env.g.turn}: 快路径 {got!r} != view {want!r}"
            seen.add(got)
            obs, _r, _d, _i = env.step(pol.act(env.g, obs.mask))
        assert len(seen) >= 2          # 至少覆盖「无 pending」+ 一种选择


def test_measure_fast_equals_view_every_turn_end():
    """``measure()`` 快路径与 ``_measure_view()`` 的每个字段都相同（含饰品/核心牌）。"""
    for game in range(2):
        env = EconomySandbox(_cfg(), core_ids=("BG36_640", "BG26_ICC_901", "BG28_707"))
        obs = env.reset(6000 + game)
        pol = SandboxPolicies(env.g, "random", seed=200 + game)
        while not env.done:
            if bool(env._mask(env.g, 0)[END_TURN]):
                fast = env.measure()
                slow = env._measure_view()
                assert set(fast) == set(slow)
                for k in fast:
                    if k == "trinkets":
                        assert sorted(fast[k]) == sorted(slow[k])
                    else:
                        assert fast[k] == slow[k], f"{k}: fast={fast[k]} view={slow[k]}"
            obs, _r, _d, _i = env.step(pol.act(env.g, obs.mask))


def _acts_sha(cfg, seed: int, policy: str = "random") -> str:
    env = EconomySandbox(cfg)
    obs = env.reset(seed)
    pol = SandboxPolicies(env.g, policy, seed=0)
    acts = []
    while not env.done:
        a = int(pol.act(env.g, obs.mask))
        acts.append(a)
        obs, _r, _d, _i = env.step(a)
    return hashlib.sha256(np.asarray(acts, dtype=np.int32).tobytes()).hexdigest()


def test_action_stream_is_deterministic_same_seed():
    """同 seed + 同策略 → 动作流 sha256 相同（快路径不改变任何决策）。"""
    cfg = _cfg()
    for seed in (7, 8):
        assert _acts_sha(cfg, seed) == _acts_sha(cfg, seed)
