#!/usr/bin/env python3
"""复利教师流水线单测：``compound_script.group_configs(--gold-cap)`` +
``gen_compound_bc`` 的动作分类 / 数据自检 / 合并与验证集切分。

覆盖
----
1. **gold-cap 直通**：``group_configs(0)`` 的四组配置 ``gold_cap=0``（不封顶），默认 99；
   ``engine_cap()`` 在 ``action_cap_per_gold>0`` 时按上限放宽（否则动作额度不可达）。
2. **动作分类**：放大器/载体/法术/饰品位 → ``action_kind`` 与三个布尔位；
   非法/越界动作退化为 ``other``（不抛异常）。
3. **数据自检**：动作在 mask 上非法 → ``validate_arrays`` 必须抛；合法数据通过。
4. **合并与验证集**：``merge_shards`` 把各 shard 的 ``episode_id`` 全局重编号，
   ``ep_decisions`` 与逐决策计数一致，``ep_split`` 恰好 10%。
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "scripts"))

import compound_script as CS  # noqa: E402
import gen_compound_bc as GB  # noqa: E402


# ── 1. gold-cap 直通 ───────────────────────────────────────────────────────
def test_group_configs_gold_cap_default_and_uncapped():
    cfgs = CS.group_configs()
    assert set(cfgs) == {"S0", "S1", "S2", "S3"}
    assert all(cfg.gold_cap == 99 for cfg in cfgs.values())
    uncapped = CS.group_configs(gold_cap=0)
    assert all(cfg.gold_cap == 0 for cfg in uncapped.values())


def test_engine_cap_widened_when_action_budget_scales():
    """``action_cap_per_gold>0`` 的组必须放宽引擎额度，否则「金币→额外动作」永远不可达。"""
    cfgs = CS.group_configs(gold_cap=0)
    assert cfgs["S0"].engine_cap() == cfgs["S0"].action_cap    # K=0：不额外放宽
    assert cfgs["S3"].action_cap_per_gold == 3
    assert cfgs["S3"].engine_cap() > cfgs["S3"].action_cap


def test_triple_first_is_opt_in_and_default_off():
    """``triple_first``/``efficient`` 是实验变体：默认 False（正式教师逐位不变）。"""
    p = CS.CompoundPolicy()
    assert p.triple_first is False and p.efficient is False
    assert CS.CompoundPolicy(triple_first=True).triple_first is True
    assert CS.CompoundPolicy(efficient=True).efficient is True


# ── 2. 动作分类 ─────────────────────────────────────────────────────────────
def _view(shop=None, hand=None):
    return {"me": {"shop": shop or [], "hand": hand or []}, "turn": 3}


AMP_ID = GB.AMP_BY_ID  # 放大器 id → 短名（含放大器法术/饰品）
_PICK_AMP_ID = next(iter(AMP_ID))
_CARRIER_ID = next(cid for cid in CS.CARRIERS if cid not in AMP_ID)


def test_classify_buy_amp_carrier_spell_minion():
    v = _view(shop=[{"id": _PICK_AMP_ID, "type": "minion"},
                    {"id": _CARRIER_ID, "type": "minion"},
                    {"id": "SOME_SPELL", "type": "spell"},
                    {"id": "PLAIN_MINION", "type": "minion"}])
    kind, is_amp, is_car, is_spell, cid = GB.classify_action(GB.A_BUY + 0, v)
    assert (kind, is_amp) == (GB.K_BUY_AMP, True) and cid == _PICK_AMP_ID
    kind, is_amp, is_car, is_spell, _cid = GB.classify_action(GB.A_BUY + 1, v)
    assert kind == GB.K_BUY_CARRIER and is_car and not is_amp
    kind, _a, _c, is_spell, _cid = GB.classify_action(GB.A_BUY + 2, v)
    assert kind == GB.K_BUY_SPELL and is_spell
    kind, *_rest = GB.classify_action(GB.A_BUY + 3, v)
    assert kind == GB.K_BUY_MINION


def test_classify_play_spell_and_play_minion():
    v = _view(hand=[{"id": "S", "type": "spell"}, {"id": "M", "type": "minion"}])
    kind, _a, _c, is_spell, _cid = GB.classify_action(GB.A_PLAY, v)
    assert kind == GB.K_PLAY_SPELL and is_spell
    kind, _a, _c, is_spell, _cid = GB.classify_action(GB.A_PLAY + GB.N_POS, v)
    assert kind == GB.K_PLAY_MINION and not is_spell


def test_classify_out_of_range_is_other():
    kind, is_amp, is_car, is_spell, cid = GB.classify_action(244, _view())  # 扩展段
    assert (kind, is_amp, is_car, is_spell, cid) == (GB.K_OTHER, False, False, False, "")
    assert GB.classify_action(GB.END_TURN, _view())[0] == GB.K_END


# ── 3. 数据自检 ─────────────────────────────────────────────────────────────
def _arrays(action_legal: bool = True):
    n = 4
    mask = np.zeros((n, GB.N_ACTIONS), dtype=bool)
    mask[:, GB.END_TURN] = True
    act = np.zeros(n, dtype=np.uint8)
    if action_legal:
        act[:] = GB.END_TURN
    else:
        act[0] = 200                              # mask 上非法
        mask[0, GB.END_TURN] = False
        mask[0, 200] = True
        mask[0, 200] = False                      # 明确非法
    return {
        "action": act,
        "mask": mask,
        "episode_id": np.zeros(n, dtype=np.int32),
        "ep_seed": np.zeros(1, dtype=np.int64),
        "ep_decisions": np.asarray([n], dtype=np.int32),
    }


def test_validate_arrays_accepts_legal_and_rejects_illegal():
    assert GB.validate_arrays(_arrays(True), "t")["legal_rate"] == 1.0
    with pytest.raises(RuntimeError):
        GB.validate_arrays(_arrays(False), "t")


def test_validate_arrays_rejects_episode_count_mismatch():
    arr = _arrays(True)
    arr["ep_decisions"] = np.asarray([99], dtype=np.int32)
    with pytest.raises(AssertionError):
        GB.validate_arrays(arr, "t")


# ── 4. 合并 + 验证集切分 ────────────────────────────────────────────────────
def test_merge_shards_renumbers_episode_ids_and_splits(tmp_path):
    shards = []
    for si, n_ep in enumerate((2, 3)):
        n_dec = n_ep * 3
        path = str(tmp_path / f"shard_{si}.npz")
        np.savez(
            path,
            features=np.zeros((n_dec, GB.OBS_FLOATS), dtype=np.float16),
            cards=np.zeros((n_dec, GB.OBS_CARDS), dtype=np.int16),
            mask=np.zeros((n_dec, GB.N_ACTIONS), dtype=bool),
            action=np.zeros(n_dec, dtype=np.uint8),
            turn=np.ones(n_dec, dtype=np.uint8),
            tier=np.ones(n_dec, dtype=np.uint8),
            gold=np.zeros(n_dec, dtype=np.int16),
            episode_id=np.repeat(np.arange(n_ep, dtype=np.int32), 3),
            action_kind=np.zeros(n_dec, dtype=np.uint8),
            is_amp_buy=np.zeros(n_dec, dtype=bool),
            is_carrier_buy=np.zeros(n_dec, dtype=bool),
            is_spell_action=np.zeros(n_dec, dtype=bool),
            ep_seed=np.arange(100 * si, 100 * si + n_ep, dtype=np.int64),
            ep_sigma_t12=np.full(n_ep, 1000, dtype=np.int32),
            ep_sigma_t15=np.full(n_ep, 2000, dtype=np.int32),
            ep_r12_15=np.full(n_ep, 2.0, dtype=np.float32),
            ep_amp_total=np.full(n_ep, 5, dtype=np.int16),
            ep_amp_any=np.ones(n_ep, dtype=bool),
            ep_goldens_t15=np.ones(n_ep, dtype=np.int16),
            ep_carriers_t15=np.full(n_ep, 3, dtype=np.int16),
            ep_spells_t15=np.full(n_ep, 40, dtype=np.int32),
            ep_tavern_buff_t15=np.full(n_ep, 6, dtype=np.int32),
            ep_gold_total_income=np.full(n_ep, 450, dtype=np.int32),
            ep_decisions=np.full(n_ep, 3, dtype=np.int32),
        )
        shards.append({"shard": path})
    arr = GB.merge_shards(shards)
    assert arr["episode_id"].tolist() == [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4]
    assert arr["ep_seed"].tolist() == [0, 1, 100, 101, 102]
    assert arr["ep_split"].tolist() == [1, 0, 0, 0, 0]          # 每 10 局取 1 局做 val
    assert np.array_equal(np.bincount(arr["episode_id"]), arr["ep_decisions"])


# ── 5. 混采（mix_compound_bc）──────────────────────────────────────────────
def _write_ep_file(path, n_ep=2, seed0=0, n_dec=3, amp=5):
    """写一个最小合法 compound_bc npz（n_ep 局 × n_dec 决策/局）。"""
    n_total = n_ep * n_dec
    mask = np.zeros((n_total, GB.N_ACTIONS), dtype=bool)
    mask[:, GB.END_TURN] = True
    np.savez(
        str(path),
        features=np.zeros((n_total, GB.OBS_FLOATS), dtype=np.float16),
        cards=np.zeros((n_total, GB.OBS_CARDS), dtype=np.int16),
        mask=mask, action=np.zeros(n_total, dtype=np.uint8),
        turn=np.ones(n_total, dtype=np.uint8), tier=np.ones(n_total, dtype=np.uint8),
        gold=np.zeros(n_total, dtype=np.int16),
        episode_id=np.repeat(np.arange(n_ep, dtype=np.int32), n_dec),
        action_kind=np.zeros(n_total, dtype=np.uint8),
        is_amp_buy=np.zeros(n_total, dtype=bool),
        is_carrier_buy=np.zeros(n_total, dtype=bool),
        is_spell_action=np.zeros(n_total, dtype=bool),
        ep_seed=np.arange(seed0, seed0 + n_ep, dtype=np.int64),
        ep_sigma_t12=np.full(n_ep, 1000, dtype=np.int32),
        ep_sigma_t15=np.full(n_ep, 2000, dtype=np.int32),
        ep_r12_15=np.full(n_ep, 2.0, dtype=np.float32),
        ep_amp_total=np.full(n_ep, amp, dtype=np.int16),
        ep_amp_any=np.ones(n_ep, dtype=bool),
        ep_goldens_t15=np.ones(n_ep, dtype=np.int16),
        ep_carriers_t15=np.full(n_ep, 3, dtype=np.int16),
        ep_spells_t15=np.full(n_ep, 40, dtype=np.int32),
        ep_tavern_buff_t15=np.full(n_ep, 6, dtype=np.int32),
        ep_gold_total_income=np.full(n_ep, 450, dtype=np.int32),
        ep_decisions=np.full(n_ep, n_dec, dtype=np.int32),
    )


def test_mix_parts_keeps_ratio_and_remaps_episodes(tmp_path):
    import mix_compound_bc as MX
    a = tmp_path / "base.npz"
    b = tmp_path / "roll8.npz"
    _write_ep_file(a, n_ep=4, seed0=0, amp=9)
    _write_ep_file(b, n_ep=2, seed0=100, amp=13)
    out = tmp_path / "mix.npz"
    meta = MX.mix([(str(a), 2.0), (str(b), 1.0)], str(out), shuffle_seed=0)
    d = np.load(str(out))
    assert meta["episodes"] == 6 and meta["decisions"] == 18
    assert d["ep_source"].tolist().count(0) == 4      # 2:1 配比 → 4:2
    assert d["ep_source"].tolist().count(1) == 2
    assert d["episode_id"].tolist() == sum(
        [[e] * 3 for e in range(6)], [])              # 全局重编号且局内连续
    assert d["ep_split"].tolist() == [1, 0, 0, 0, 0, 0]
    assert np.array_equal(np.bincount(d["episode_id"]), d["ep_decisions"])
    assert meta["validation"]["legal_rate"] == 1.0

