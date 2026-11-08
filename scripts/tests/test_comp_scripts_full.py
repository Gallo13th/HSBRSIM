"""全阵容脚本的完整性与合法性测试（CPU，<120s）。

覆盖：
1. 注册表完整性：``runs/comp_scripts/roles.json`` 里 26 套 implementable 的名字
   全部能在 ``COMPS`` 找到，且 name↔key 是 1:1（映射表显式写死，新增套必须同步）；
2. 每套阵容各跑 1 局（固定 seed）：不抛异常、``illegal == 0``、同 seed 二次结果相同；
3. ``view_of(game, seat)`` 返回含 ``me/turn/phase`` 的 dict；
4. ``comp_keys()`` 稳定排序；``CompPolicy.reset()`` 可复位复用。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import comp_scripts as CS  # noqa: E402

ROLES = json.load(open(os.path.join(ROOT, "runs/comp_scripts/roles.json"),
                       encoding="utf-8"))["comps"]
IMPL_NAMES = [str(c["name"]) for c in ROLES if c.get("implementable")]

#: roles.json 名称 → COMPS key（1:1，显式写死；新增/改名必须同步本表）
NAME_TO_KEY = {
    "Neutral Tea Set": "A",
    "Undead APM": "undead_apm",
    "Murloc Scam": "murloc_scam",
    "Aberration Discard": "aberration_discard",
    "Dragon Shield": "dragon_shield",
    "Demon Boost Shop": "C",
    "Murloc Handbuff": "M",
    "Mech APM": "I",
    "Undead Butcher": "undead_butcher",
    "Quilboar Choose One": "quilboar_choose_one",
    "Murloc End Of Turn": "H",
    "Quilboar Felboar Spam": "B",
    "Elemental Azerite": "D",
    "Beast Lobster": "beast_lobster",
    "Mech Volumizer": "J",
    "Aberration Deathrattle": "aberration_deathrattle",
    "Pirate Discover": "pirate_discover",
    "Demon Self Damage": "demon_self_damage",
    "Elemental Tempest": "elemental_tempest",
    "Beast Beetle": "G",
    "Beast Leviathan": "K",
    "Dragon Kalecgos": "dragon_kalecgos",
    "Dragon Spell Power": "F",
    "Mech Glambot": "E",
    "Quilboar Gem Spam": "L",
    "Pirate Bounty": "pirate_bounty",
}

SEED = 971000


def test_registry_covers_all_implementable_roles():
    assert len(IMPL_NAMES) == 26, f"roles.json implementable 数变了：{len(IMPL_NAMES)}"
    missing = [n for n in IMPL_NAMES if n not in NAME_TO_KEY]
    assert not missing, f"roles.json 有、映射表缺：{missing}"
    not_in_comps = [n for n in IMPL_NAMES if NAME_TO_KEY[n] not in CS.COMPS]
    assert not not_in_comps, f"映射到不存在的 key：{not_in_comps}"
    # 1:1：映射表内的 key 与 name 都不重复，且 COMPS 里 name 一致
    keys = list(NAME_TO_KEY.values())
    assert len(keys) == len(set(keys))
    for name, key in NAME_TO_KEY.items():
        assert CS.COMPS[key].name == name, f"{key}: {CS.COMPS[key].name} != {name}"


def test_all_roles_comps_registered_and_extended():
    # 26 套 + A–N 里 roles 不含的 N + f_dragon 扩展
    assert len(CS.COMPS) == 28, f"注册数 {len(CS.COMPS)}（期望 28）"
    assert "N" in CS.COMPS and "f_dragon" in CS.COMPS
    assert CS.UNIMPLEMENTABLE == {} and len(CS.LEGACY_GAPS) == 13


def test_comp_keys_stable_sorted():
    ks = CS.comp_keys()
    assert ks == sorted(CS.COMPS.keys())
    assert len(ks) == len(set(ks)) == 28


def test_spec_fields_sane():
    for k, s in CS.COMPS.items():
        assert s.core, f"{k} 没有 core"
        assert s.carrier, f"{k} 没有 carrier"
        assert set(s.cast_on) <= set(s.carrier) | set(s.core), f"{k} cast_on 不在载体/核心内"
        assert 1 <= s.type_min <= 5, f"{k} type_min={s.type_min}"
        assert len(s.curve) >= 15, f"{k} curve 长度 {len(s.curve)}"
        assert s.trinkets, f"{k} 没有饰品"
        assert s.tribe in CS.TRIBES, f"{k} tribe={s.tribe}"


@pytest.mark.parametrize("key", CS.comp_keys())
def test_one_game_legal_and_deterministic(key):
    spec = CS.COMPS[key]
    a = CS.play_one(SEED, spec, hybrid=True)
    b = CS.play_one(SEED, spec, hybrid=True)
    assert a is not None, f"{key}: 对局未结束（超步数）"
    assert a["illegal"] == 0, f"{key}: 非法动作 {a['illegal']}"
    assert a["decisions"] > 0
    sa = json.dumps(a, sort_keys=True, default=float)
    sb = json.dumps(b, sort_keys=True, default=float)
    assert sa == sb, f"{key}: 同 seed 两次结果不一致"


def test_view_of_shape():
    game = CS.E.Game(int(SEED), CS._config_json(CS.COMPS["J"], SEED))
    CS.EA.finish_hero_select(game)
    v = CS.view_of(game, 0)
    assert isinstance(v, dict)
    for field in ("me", "turn", "phase"):
        assert field in v, f"view 缺字段 {field}"
    assert isinstance(v["me"], dict)
    assert "board" in v["me"] and "shop" in v["me"] and "health" in v["me"]


def test_policy_reset_reusable():
    spec = CS.COMPS["J"]
    pol = CS.CompPolicy(spec, seed=SEED)
    game = CS.E.Game(int(SEED), CS._config_json(spec, SEED))
    CS.EA.finish_hero_select(game)
    for _ in range(5):
        if not game.needs_action(0):
            break
        mask = CS.mask_from_bytes(game.legal_mask(0))
        a = pol.act(CS.view_of(game, 0), mask)
        game.step(0, a)
    pol.reset()
    assert pol.spec is spec and pol.turn == -1 and pol.snaps == []
    assert pol.core_seen == {} and pol.illegal == 0 and not pol.exited


def test_v2_gates_monotone():
    """V2 门槛的边界：hp≤20 不许 roll；金币不足不许 roll；t≤7 无核心也允许。"""
    spec = CS.COMPS["J"]
    pol = CS.CompPolicy(spec, seed=SEED)
    me = {"health": 30, "gold": 20, "upgrade_price": 6, "tier": 3,
          "board": [], "hand": [], "shop": []}
    pol.turn = 5
    assert pol._v2_can_roll(me) is True
    assert pol._v2_can_roll(dict(me, health=20)) is False
    assert pol._v2_can_roll(dict(me, gold=2)) is False
    pol.turn = 9
    assert pol._v2_can_roll(me) is False          # t≥8 无核心 → 不 roll（应退出）
    pol.turn = 5
    assert pol._v2_can_upgrade(dict(me, gold=6, tier=1), 4) is True   # t5 按 curve 升本
    assert pol._v2_can_upgrade(dict(me, gold=6, tier=2), 4) is True
    assert pol._v2_can_upgrade(dict(me, gold=6, tier=4), 4) is False   # 5 本最早 t8
    pol.turn = 8
    assert pol._v2_can_upgrade(dict(me, gold=8, tier=4, upgrade_price=8), 5) is False  # t8+ 无核心
    assert pol._v2_can_upgrade(dict(me, gold=2), 4) is False          # 金币不够
    pol.turn = 9
    assert pol._v2_can_upgrade(dict(me, gold=20, tier=4), 5) is False  # t8+ 无核心不许转本
