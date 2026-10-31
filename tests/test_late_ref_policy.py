"""后期参考解修正（``--late-ref-policy fixed``）单测（``docs/BOARD_PROBLEMS.md`` §14）。

覆盖：

1. **动作族分类** ``ref_action_kind``（reroll/buy/play/sell/upgrade/end_turn/other）；
2. **人类购买频次表** ``build_human_buy_table``：按 tier 分桶、只统计 buy_*、
   ``min_freq`` 判据、摘要 JSON；
3. **reroll 封顶 + 买牌加权的数学**：候选层加权 -> top-k -> cap 在**最终分布**上生效，
   手算权重逐位核对（含 top-1 从 reroll 翻到 buy 的例子）；
4. **默认逐位等价**：``current`` 策略与 ``turn < turn_min`` 时返回的 ref 与不开开关
   完全相同（无新键、权重逐位相同）；
5. **严格层级**：``fixed`` 只用 ``turn_tier_gold``，匹配不到就是 ``no_support``
   （不偷偷退化成 ``(turn,tier)`` 桶）；
6. **已有题池重写** ``rewrite_problem_rows``：保留 ``ref_before``、严格未匹配行显式
   标 ``late_ref.applied=False``、``current`` 模式与原 ref 一致；
7. **参数校验**：非法 policy / cap / boost / 层级抛 ``ValueError``；CLI 非 0 退出。
"""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys

import numpy as np
import pytest

from hsbg.az.train.board_problems import (
    HumanBuyTable,
    LateRefConfig,
    ReferenceTable,
    build_human_buy_table,
    decode_obs,
    encode_obs,
    match_reference_actions,
    ref_action_card,
    ref_action_kind,
    ref_type_distribution,
    rewrite_problem_rows,
)
from hsbg.env import obs_std as O
from hsbg.az.train.common import N_ACTIONS, OBS_CARDS, OBS_FLOATS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CARD_IDS = ("", "CID1", "CID2")


def _features(turn: int = 14, tier: int = 4, gold: int = 5, *,
              with_shop: bool = True, with_hand: bool = True) -> np.ndarray:
    f = np.zeros(OBS_FLOATS, np.float32)
    g = f[O.SLICE_GLOBAL]
    g[O.GLOBAL_FIELD_INDEX["turn"]] = float(turn) / 20.0
    g[O.GLOBAL_FIELD_INDEX["tier"]] = float(tier) / 6.0
    g[O.GLOBAL_FIELD_INDEX["gold"]] = float(gold) / 10.0
    shop = f[O.SLICE_SHOP].reshape(O.N_SHOP, O.ITEM_F)
    if with_shop:
        shop[0, O.ITEM_PRESENT] = 1.0
        shop[0, O.ITEM_IS_MINION] = 1.0
        shop[0, O.ITEM_MINION + O.MINION_PRESENT] = 1.0
    hand = f[O.SLICE_HAND].reshape(O.N_HAND, O.ITEM_F)
    if with_hand:
        hand[0, O.ITEM_PRESENT] = 1.0
        hand[0, O.ITEM_IS_MINION] = 1.0
        hand[0, O.ITEM_MINION + O.MINION_PRESENT] = 1.0
    return f


def _cards(shop_card: int = 1, hand_card: int = 1) -> np.ndarray:
    c = np.zeros(OBS_CARDS, np.int32)
    c[O.SLICE_CARD_SHOP][0] = int(shop_card)
    c[O.SLICE_CARD_HAND][0] = int(hand_card)
    return c


def _mask(legal=(0, 1, 3, 8, 15, 46)) -> np.ndarray:
    m = np.zeros(N_ACTIONS, bool)
    for a in legal:
        m[int(a)] = True
    return m


def _table(bucket: dict, *, key_level: str = "turn_tier_gold",
           key=(1, 14, 4, 5), floors=(10000,),
           card_ids=CARD_IDS) -> ReferenceTable:
    tables = {int(f): {"by_turn_tier_gold": {}, "by_turn_tier": {},
                       "by_tier": {}, "by_turn": {}, "all": {}}
              for f in floors}
    tbl_name = {"turn_tier_gold": "by_turn_tier_gold",
                "turn_tier": "by_turn_tier", "tier": "by_tier",
                "turn": "by_turn", "all": "all"}[str(key_level)]
    tables[int(floors[0])][tbl_name][key] = dict(bucket)
    return ReferenceTable(floors=tuple(int(f) for f in floors), tables=tables,
                          rows={int(f): int(10 * f) for f in floors},
                          path="synthetic", card_ids=tuple(card_ids))


def _buy_table(high=("CID1",), tier: int = 4) -> HumanBuyTable:
    counts = {int(tier): {str(c): 1.0 for c in high}}
    totals = {int(tier): float(len(high)) or 1.0}
    return HumanBuyTable(path="synthetic", counts=counts, totals=totals,
                         high={int(tier): tuple(str(c) for c in high)},
                         min_freq=0.01, rows=int(len(high)))


def _rng_ref_weights(res: dict) -> list:
    return [round(float(x), 6) for x in (res.get("weights") or [])]


# ══════════════════════════════════════════════════════════════════════════
# 1. 动作族
# ══════════════════════════════════════════════════════════════════════════
def test_ref_action_kind():
    assert ref_action_kind(0) == "end_turn"
    assert ref_action_kind(1) == "reroll"
    assert ref_action_kind(3) == "upgrade"
    assert ref_action_kind(4) == "hero_power"
    assert ref_action_kind(5) == "hero_power"
    assert ref_action_kind(8) == "buy"
    assert ref_action_kind(15) == "buy"
    assert ref_action_kind(16) == "sell"
    assert ref_action_kind(22) == "sell"
    assert ref_action_kind(46) == "play"
    assert ref_action_kind(125) == "play"
    assert ref_action_kind(23) == "other"
    assert ref_action_kind(126) == "other"


def test_ref_action_card():
    f = _features()
    c = _cards(shop_card=1, hand_card=2)
    assert ref_action_card(f, c, 8, CARD_IDS) == ("CID1", 1)
    assert ref_action_card(f, c, 46, CARD_IDS) == ("CID2", 2)
    assert ref_action_card(f, c, 1, CARD_IDS) == ("", 0)


# ══════════════════════════════════════════════════════════════════════════
# 2. 人类高频购买表
# ══════════════════════════════════════════════════════════════════════════
def test_build_human_buy_table(tmp_path):
    path = tmp_path / "actions.jsonl.gz"
    rows = [
        {"action_type": "buy_minion", "card_id": "A", "tier": 4},
        {"action_type": "buy_minion", "card_id": "A", "tier": 4},
        {"action_type": "buy_minion", "card_id": "B", "tier": 4},
        {"action_type": "buy_spell", "card_id": "C", "tier": 4},
        {"action_type": "play_minion", "card_id": "A", "tier": 4},  # 不是购买
        {"action_type": "reroll", "card_id": None, "tier": 4},
        {"action_type": "buy_minion", "card_id": "D", "tier": 5},
        {"action_type": "buy_minion", "card_id": "D"},              # 缺 tier
    ]
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    t = build_human_buy_table(str(path), min_freq=0.30)
    assert t.rows == 5
    assert t.totals[4] == 4.0 and t.totals[5] == 1.0
    assert t.freq(4, "A") == pytest.approx(0.5)
    assert t.freq(4, "B") == pytest.approx(0.25)
    assert t.is_high(4, "A") is True          # 0.5 >= 0.30
    assert t.is_high(4, "B") is False         # 0.25 < 0.30
    assert t.is_high(5, "D") is True
    assert t.is_high(3, "A") is False         # 没有 tier 3
    summary = t.to_json()
    assert summary["tiers"]["4"]["buys"] == 4
    assert summary["tiers"]["4"]["high_cards"] == 1
    with pytest.raises(ValueError):
        build_human_buy_table(str(path), min_freq=1.5)


# ══════════════════════════════════════════════════════════════════════════
# 3. reroll 封顶 + 买牌加权（手算）
# ══════════════════════════════════════════════════════════════════════════
def test_reroll_cap_and_buy_boost_math():
    # 严格层桶：reroll 6 / buy_minion(CID1) 3 / buy_spell 1
    table = _table({("reroll", ""): 6.0,
                    ("buy_minion", "CID1"): 3.0,
                    ("buy_spell", ""): 1.0})
    f, c, m = _features(), _cards(), _mask()
    # ── 不开修正：默认（reroll 0.6 / buy 0.3 / spell 0.1）─────────────────
    base = match_reference_actions(f, c, m, table, min_support=1)
    assert base["matched"] is True and base["level"] == "turn_tier_gold"
    assert base["actions"] == [1, 8, 15]
    assert _rng_ref_weights(base) == [0.6, 0.3, 0.1]
    assert "late_ref" not in base
    # ── fixed：买牌 ×2，再对最终 top-k 分布 cap=0.25 ─────────────────────
    cfg = LateRefConfig(policy="fixed", reroll_cap=0.25, buy_boost=2.0)
    fixed = match_reference_actions(f, c, m, table, min_support=1,
                                    late_ref=cfg, buy_table=_buy_table())
    audit = fixed["late_ref"]
    assert audit["applied"] is True
    assert audit["boosted"] >= 1
    assert audit["capped_topk"] is True
    assert audit["reroll_topk_after"] == pytest.approx(0.25)
    assert fixed["actions"][0] == 8          # top-1 从 reroll 翻到 buy
    assert _rng_ref_weights(fixed) == [pytest.approx(0.642857),
                                      pytest.approx(0.25),
                                      pytest.approx(0.107143)]
    # ── 只有加权、不封顶（cap=1.0）：放大倍数可见 ────────────────────────
    cfg2 = LateRefConfig(policy="fixed", reroll_cap=1.0, buy_boost=2.0)
    boosted = match_reference_actions(f, c, m, table, min_support=1,
                                      late_ref=cfg2, buy_table=_buy_table())
    assert _rng_ref_weights(boosted) == [pytest.approx(0.461538),
                                        pytest.approx(0.461538),
                                        pytest.approx(0.076923)]
    # ── 没有购买表时只有 cap：0.6 -> 0.25，其余按质量重归一 ───────────────
    # scale_o = (1-0.25)/(1-0.6) = 1.875 -> buy 0.3*1.875 = 0.5625、spell 0.1875
    cfg3 = LateRefConfig(policy="fixed", reroll_cap=0.25, buy_boost=2.0)
    nocap = match_reference_actions(f, c, m, table, min_support=1,
                                    late_ref=cfg3, buy_table=None)
    assert _rng_ref_weights(nocap) == [pytest.approx(0.5625),
                                       pytest.approx(0.25),
                                       pytest.approx(0.1875)]


def test_reroll_cap_zero_and_one():
    table = _table({("reroll", ""): 6.0, ("buy_minion", "CID1"): 3.0,
                    ("buy_spell", ""): 1.0})
    f, c, m = _features(), _cards(), _mask()
    cfg0 = LateRefConfig(policy="fixed", reroll_cap=0.0, buy_boost=1.0)
    r0 = match_reference_actions(f, c, m, table, min_support=1, late_ref=cfg0)
    kinds = [ref_action_kind(a) for a in r0["actions"]]
    assert "reroll" not in kinds            # cap=0 时 reroll 权重为 0
    cfg1 = LateRefConfig(policy="fixed", reroll_cap=1.0, buy_boost=1.0)
    r1 = match_reference_actions(f, c, m, table, min_support=1, late_ref=cfg1)
    assert _rng_ref_weights(r1) == [0.6, 0.3, 0.1]


# ══════════════════════════════════════════════════════════════════════════
# 4. 默认逐位等价
# ══════════════════════════════════════════════════════════════════════════
def test_current_policy_is_bitwise_identical():
    table = _table({("reroll", ""): 6.0, ("buy_minion", "CID1"): 3.0,
                    ("buy_spell", ""): 1.0})
    f, c, m = _features(), _cards(), _mask()
    base = match_reference_actions(f, c, m, table, min_support=1)
    cur = match_reference_actions(f, c, m, table, min_support=1,
                                  late_ref=LateRefConfig(policy="current"),
                                  buy_table=_buy_table())
    assert cur == base
    # turn < turn_min（9）：即使 policy=fixed 也不动
    f9 = _features(turn=9)
    table9 = _table({("reroll", ""): 6.0, ("buy_minion", "CID1"): 3.0,
                     ("buy_spell", ""): 1.0}, key=(1, 9, 4, 5))
    base9 = match_reference_actions(f9, c, m, table9, min_support=1)
    fixed9 = match_reference_actions(
        f9, c, m, table9, min_support=1,
        late_ref=LateRefConfig(policy="fixed"), buy_table=_buy_table())
    assert fixed9 == base9
    assert "late_ref" not in fixed9


# ══════════════════════════════════════════════════════════════════════════
# 5. 严格层级（fixed 不退化）
# ══════════════════════════════════════════════════════════════════════════
def test_fixed_requires_turn_tier_gold_level():
    # 只有 (turn,tier) 桶、没有 gold 桶
    table = _table({("reroll", ""): 6.0, ("buy_minion", "CID1"): 3.0},
                   key_level="turn_tier", key=(1, 14, 4))
    f, c, m = _features(), _cards(), _mask()
    coarser = match_reference_actions(f, c, m, table, min_support=1)
    assert coarser["matched"] is True and coarser["level"] == "turn_tier"
    strict = match_reference_actions(f, c, m, table, min_support=1,
                                     levels=("turn_tier_gold",))
    assert strict["matched"] is False
    assert strict["reason"] == "no_support"
    fixed = match_reference_actions(
        f, c, m, table, min_support=1, levels=("turn_tier_gold",),
        late_ref=LateRefConfig(policy="fixed"), buy_table=_buy_table())
    assert fixed["matched"] is False and "late_ref" not in fixed


# ══════════════════════════════════════════════════════════════════════════
# 6. 已有题池重写
# ══════════════════════════════════════════════════════════════════════════
def _row(turn: int = 14, tier: int = 4, gold: int = 5) -> dict:
    f = _features(turn=turn, tier=tier, gold=gold)
    c, m = _cards(), _mask()
    return {
        "problem_id": "bp-000000", "turn": int(turn),
        "obs": encode_obs(f, c, m), "state": {"tier": tier, "gold": gold},
        "ref": {"actions": [1, 8], "weights": [2.0 / 3.0, 1.0 / 3.0],
                "matched": True, "level": "turn_tier", "floor": 8000,
                "support": 99, "mass_legal": 0.5, "reason": "ok"},
    }


def test_rewrite_problem_rows_fixed_and_current():
    table = _table({("reroll", ""): 6.0, ("buy_minion", "CID1"): 3.0})
    rows = [_row(14), _row(14, tier=2, gold=3)]   # 第二行没有严格桶
    fixed, rep = rewrite_problem_rows(
        rows, table, cfg=LateRefConfig(policy="fixed"), buy_table=_buy_table(),
        min_support=1, card_ids=CARD_IDS)
    assert rep["late_rows"] == 2
    assert rep["late_strict_matched"] == 1
    assert rep["late_strict_unmatched"] == 1
    assert rep["applied"] == 1
    assert fixed[0]["ref"]["matched"] is True
    assert fixed[0]["late_ref"]["applied"] is True
    assert fixed[0]["ref_before"]["actions"] == [1, 8]
    assert fixed[0]["ref_before"]["weights"] == [pytest.approx(2.0 / 3.0),
                                                pytest.approx(1.0 / 3.0)]
    # 未匹配：ref 显式 unmatched（不退回 coarser 桶）、late_ref 标 no_support
    assert fixed[1]["ref"]["matched"] is False
    assert fixed[1]["ref"]["reason"] == "no_support"
    assert fixed[1]["late_ref"]["applied"] is False
    assert fixed[1]["late_ref"]["reason"] == "no_support"
    # current 模式：与旧 ref 逐位一致（同一张表重新匹配）
    cur, rep_c = rewrite_problem_rows(
        rows[:1], table, cfg=LateRefConfig(policy="current"), min_support=1,
        card_ids=CARD_IDS)
    assert rep_c["applied"] == 0
    assert cur[0]["ref"]["actions"] == [1, 8]
    assert cur[0]["ref"]["weights"] == [pytest.approx(2.0 / 3.0),
                                        pytest.approx(1.0 / 3.0)]
    # decode round-trip（题池可复现）
    f2, c2, m2 = decode_obs(cur[0]["obs"])
    assert np.allclose(f2, _features()) and np.array_equal(c2, _cards())
    assert np.array_equal(m2, _mask())


def test_ref_type_distribution():
    rows = [
        {"turn": 14, "ref": {"matched": True, "level": "turn_tier_gold",
                             "actions": [1, 8], "weights": [0.6, 0.4]}},
        {"turn": 14, "ref": {"matched": True, "level": "turn_tier_gold",
                             "actions": [1], "weights": [1.0]}},
        {"turn": 14, "ref": {"matched": False, "level": "none"}},
    ]
    dist = ref_type_distribution(rows, turns=(14,))
    cell = dist["turns"]["14"]
    assert cell["n"] == 3 and cell["matched"] == 2
    assert cell["level"]["turn_tier_gold"] == 2
    assert cell["mass_share"]["reroll"] == pytest.approx((0.6 + 1.0) / 2)
    assert cell["top1"]["reroll"] == 2
    assert cell["reroll_top1_share"] == pytest.approx(1.0)
    assert cell["mean_reroll_mass"] == pytest.approx((0.6 + 1.0) / 2)
    assert dist["overall"]["matched"] == 2


# ══════════════════════════════════════════════════════════════════════════
# 7. 参数校验 + CLI
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("kwargs", [
    {"policy": "nope"},
    {"policy": "fixed", "reroll_cap": 1.5},
    {"policy": "fixed", "reroll_cap": -0.1},
    {"policy": "fixed", "buy_boost": 0.5},
    {"policy": "fixed", "buy_boost": float("nan")},
    {"policy": "fixed", "strict_levels": ("turn_tier_xyz",)},
])
def test_late_ref_config_validation(kwargs):
    with pytest.raises(ValueError):
        LateRefConfig(**kwargs)


def test_build_script_exposes_late_ref_flags():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(ROOT, "rust", "python"), ROOT, env.get("PYTHONPATH", "")])
    script = os.path.join(ROOT, "scripts", "build_board_problems.py")
    help_txt = subprocess.run([sys.executable, script, "--help"],
                              capture_output=True, text=True, env=env,
                              timeout=120)
    assert help_txt.returncode == 0
    assert "--late-ref-policy" in help_txt.stdout
    assert "--ref-reroll-cap" in help_txt.stdout
    assert "--ref-buy-boost" in help_txt.stdout
    assert "--rewrite-pool" in help_txt.stdout
    # 非法 cap：在加载引擎/checkpoint 之前就以退出码 2 报错
    bad = subprocess.run(
        [sys.executable, script, "--late-ref-policy", "fixed",
         "--ref-reroll-cap", "2.0", "--rewrite-pool", "/nonexistent.jsonl"],
        capture_output=True, text=True, env=env, timeout=120)
    assert bad.returncode == 2
    assert "late-ref" in (bad.stderr or "")
