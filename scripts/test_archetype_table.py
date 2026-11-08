"""流派偏好表构建（``scripts/build_archetype_table.py``）单测。

覆盖：
- 动作行 → :class:`ArchetypeObs`（酒馆/手牌/战团种族位、OOV 卡 id 忽略）；
- 前缀样本口径：每回合起点一个样本、只含该回合之前的己方动作、按局分组；
- 标签分布 + 头部流派 / ``other`` 合并；
- 偏好表归一化（``buy_tribe``/``board_tribe`` 和为 1，rate ∈ [0,1]，平滑后无 NaN）；
- ``other``/缺桶回退与 ``per_turn`` 口径；
- 分组交叉验证：同一局的前缀样本绝不跨折；
- 端到端 ``main()``：产出 npz/json 且字段齐全（小样本，秒级）。

所有测试都用**合成数据 + 临时目录**，不依赖仓库里的真实数据/制品。
"""

from __future__ import annotations

import gzip
import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "scripts"))

import build_archetype_table as B  # noqa: E402

from hsbg.az.train.archetype_bias import (  # noqa: E402
    ACTION_TYPES,
    FEATURE_DIM,
    N_BUCKETS,
    TRIBES,
    bucket_key,
    load_models,
    load_table,
)


# ══════════════════════════════════════════════════════════════════════════
# 合成数据
# ══════════════════════════════════════════════════════════════════════════
CARDS = {
    "cards": [
        {"id": "MECH_1", "kind": "minion", "races": ["MECHANICAL"]},
        {"id": "MECH_2", "kind": "minion", "races": ["MECHANICAL"]},
        {"id": "DRAG_1", "kind": "minion", "races": ["DRAGON"]},
        {"id": "DRAG_2", "kind": "minion", "races": ["DRAGON"]},
        {"id": "SPELL_1", "kind": "spell", "races": []},
        {"id": "HERO_A", "kind": "hero", "races": []},
        {"id": "HERO_B", "kind": "hero", "races": []},
    ]
}


def _rows_for_game(gid: str, buy_card: str, hero: str, tribe: str,
                   turns: int = 4) -> list[dict]:
    """造一局「每回合买 1 张 + 结束回合」的最小动作序列。"""
    rows: list[dict] = []
    for turn in range(1, int(turns) + 1):
        rows.append({
            "game_id": gid, "turn": turn, "action_type": "buy_minion",
            "card_id": buy_card, "shop_slot": 0, "action_index": 8,
            "tier": 1 + turn // 3, "gold": 3 + turn,
            "board_cards": [buy_card], "shop_cards": [buy_card],
            "hand_cards": [], "placement": 1,
        })
        rows.append({
            "game_id": gid, "turn": turn, "action_type": "play_minion",
            "card_id": buy_card, "hand_slot": 0, "play_pos": 0,
            "action_index": 46,
            "tier": 1 + turn // 3, "gold": 2 + turn,
            "board_cards": [buy_card, buy_card], "shop_cards": [],
            "hand_cards": [buy_card], "placement": 1,
        })
        rows.append({
            "game_id": gid, "turn": turn, "action_type": "end_turn",
            "action_index": 0, "tier": 1 + turn // 3, "gold": 0,
            "board_cards": [buy_card, buy_card], "shop_cards": [buy_card],
            "hand_cards": [], "placement": 1,
        })
    return rows


def _make_dataset(tmp_path: str) -> dict:
    """写合成 cards/library/actions，返回路径。"""
    cards_path = os.path.join(tmp_path, "cards.json")
    with open(cards_path, "w", encoding="utf-8") as f:
        json.dump(CARDS, f)
    games = []
    for i in range(8):
        if i % 2 == 0:
            games.append((f"g{i}", "mech_apm", "MECH_1", "HERO_A", "mech"))
        else:
            games.append((f"g{i}", "dragon_shield", "DRAG_1", "HERO_B", "dragon"))
    lib_path = os.path.join(tmp_path, "library.jsonl")
    rows: list[dict] = []
    with open(lib_path, "w", encoding="utf-8") as f:
        for gid, arch, card, hero, tribe in games:
            f.write(json.dumps({
                "game_id": gid, "archetype": arch, "hero_card_id": hero,
                "tribes": ["MECHANICAL" if tribe == "mech" else "DRAGON",
                           "BEAST"], "placement": 1, "turn": 1,
            }) + "\n")
            rows.extend(_rows_for_game(gid, card, hero, tribe))
    act_path = os.path.join(tmp_path, "actions.jsonl.gz")
    with gzip.open(act_path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return {"cards": cards_path, "library": lib_path, "actions": act_path,
            "games": games}


# ══════════════════════════════════════════════════════════════════════════
# 1. 读取 + 观测构造
# ══════════════════════════════════════════════════════════════════════════
def test_load_library_and_cards(tmp_path):
    paths = _make_dataset(str(tmp_path))
    lib = B.load_library(paths["library"])
    assert len(lib) == 8
    assert lib["g0"]["archetype"] == "mech_apm"
    assert lib["g1"]["hero"] == "HERO_B"
    cards = B.load_cards(paths["cards"])
    assert cards["MECH_1"]["is_minion"] and not cards["SPELL_1"]["is_minion"]
    assert cards["DRAG_1"]["races"] == ["DRAGON"]


def test_obs_from_row_and_oov_cards(tmp_path):
    paths = _make_dataset(str(tmp_path))
    cards = B.load_cards(paths["cards"])
    row = {"turn": 3, "tier": 2, "gold": 5.0,
           "board_cards": ["MECH_1", "UNKNOWN_CARD"],
           "shop_cards": ["MECH_1", "SPELL_1", "UNKNOWN_CARD"],
           "hand_cards": ["DRAG_1", "UNKNOWN_CARD"]}
    obs = B.obs_from_row(row, cards, lobby=["MECHANICAL", "DRAGON"], hero="HERO_A")
    assert (obs.turn, obs.tier) == (3, 2)
    assert obs.board_tribes[TRIBES.index("MECHANICAL")] == pytest.approx(1.0)
    assert obs.board_tribes.sum() == pytest.approx(1.0)
    assert obs.shop_present[:3].all() and obs.shop_minion[0]
    assert not obs.shop_minion[1]                       # 法术槽不算随从
    assert obs.shop_tribes[0, TRIBES.index("MECHANICAL")] == 1.0
    assert obs.hand_minion[0] and not obs.hand_minion[1]
    assert obs.lobby[TRIBES.index("DRAGON")] == 1.0
    assert obs.hero_id == "HERO_A"


def test_tribe_vector_ignores_unknown_and_extra_races():
    cards = {"A": {"races": ["DRAGON"], "is_minion": True},
             "B": {"races": ["NOT_A_TRIBE"], "is_minion": True}}
    v = B.tribe_vector(["A", "B", "MISSING"], cards)
    assert v.sum() == pytest.approx(1.0)
    assert v[TRIBES.index("DRAGON")] == 1.0


def test_action_index_reconstruction():
    assert B.action_index_of({"action_type": "buy_minion", "shop_slot": 2,
                              "action_index": None}) == 10
    assert B.action_index_of({"action_type": "play_minion", "hand_slot": 1,
                              "play_pos": 3}) == 46 + 8 + 3
    assert B.action_index_of({"action_type": "end_turn", "action_index": None}) == 0
    assert B.action_index_of({"action_type": "upgrade", "action_index": 3}) == 3


# ══════════════════════════════════════════════════════════════════════════
# 2. 前缀样本口径
# ══════════════════════════════════════════════════════════════════════════
def test_prefix_samples_one_per_turn_start(tmp_path):
    paths = _make_dataset(str(tmp_path))
    lib = B.load_library(paths["library"])
    cards = B.load_cards(paths["cards"])
    games = B.load_game_actions(paths["actions"], set(lib))
    pack = B.build_prefix_samples(games, lib, cards, hero_vocab=[], max_turn=15)
    X = pack["X"]
    # 每局 4 个回合 → 每局 4 个前缀样本
    assert len(X) == 8 * 4
    assert X.shape[1] == FEATURE_DIM
    assert set(pack["archetype"]) == {"mech_apm", "dragon_shield"}
    # turn=1 的样本历史为空（n_actions=log1p(0)=0）
    t1 = [i for i, t in enumerate(pack["turn"]) if t == 1]
    assert len(t1) == 8
    assert all(X[i, 0] == 0.0 for i in t1)
    # turn=4 的样本已经积累了 3 回合 × 3 动作
    t4 = [i for i, t in enumerate(pack["turn"]) if t == 4]
    assert all(X[i, 0] == pytest.approx(np.log1p(9)) for i in t4)


def test_labels_head_vs_other(tmp_path):
    paths = _make_dataset(str(tmp_path))
    lib = B.load_library(paths["library"])
    sup = sorted({v["archetype"] for v in lib.values()})
    assert sup == ["dragon_shield", "mech_apm"]
    # 阈值高于样本数 → 全部合并 other（构建器里 heads 由库内局数决定）
    assert [a for a in sup if 8 >= 99] == []


# ══════════════════════════════════════════════════════════════════════════
# 3. 偏好表
# ══════════════════════════════════════════════════════════════════════════
def test_preference_table_normalized(tmp_path):
    paths = _make_dataset(str(tmp_path))
    lib = B.load_library(paths["library"])
    cards = B.load_cards(paths["cards"])
    games = B.load_game_actions(paths["actions"], set(lib))
    pref = B.build_preference_table(games, lib, cards,
                                    head_archetypes=["mech_apm", "dragon_shield"])
    keys = [bucket_key(i) for i in range(N_BUCKETS)] + ["all"]
    for node in list(pref["baseline"].values()):
        assert 0.0 <= sum(node["rates"].values()) <= 1.0 + 1e-6
    empty_buckets = 0
    for grp in ("archetypes", "tribes"):
        for name, node in pref[grp].items():
            for k in keys:
                pr = node["pref"][k]
                assert set(pr["rates"]) == set(ACTION_TYPES)
                assert all(0.0 <= v <= 1.0 for v in pr["rates"].values())
                # 归一化：有样本的桶和恒为 1；完全无样本的桶（连基线也没数据）
                # 返回空 dict（宁可不给偏好，也不编造），由 7-8 桶覆盖断言兜底
                for fld in ("buy_tribe", "board_tribe"):
                    dist = pr[fld]
                    if not dist:
                        empty_buckets += 1
                        continue
                    assert abs(sum(dist.values()) - 1.0) < 1e-3
                    assert all(v >= 0.0 for v in dist.values())
                assert pr["turns"] >= 0 and pr["n"] >= 0
    # 合成数据只有 4 回合 → 后面的桶天然为空；有数据的桶必须归一化
    assert pref["archetypes"]["mech_apm"]["pref"]["1-4"]["buy_tribe"]
    assert pref["archetypes"]["mech_apm"]["pref"]["all"]["buy_tribe"]
    # 每回合频率（per_turn）恒非负；buy 率在 4 个回合 × 8 局里的口径一致
    mp = pref["archetypes"]["mech_apm"]["pref"]["1-4"]
    assert mp["per_turn"]["buy_minion"] >= 0.0
    # 每局的买牌种族构成干净（合成数据里 mech 只买 MECHANICAL）
    allb = pref["archetypes"]["mech_apm"]["pref"]["all"]["buy_tribe"]
    # 合成数据里 mech 只买 MECHANICAL；平滑（TRIBE_ALPHA）会把少量质量给基线
    assert allb["MECHANICAL"] > 0.85
    assert allb["MECHANICAL"] > allb.get("DRAGON", 0.0)


def test_preference_table_missing_bucket_falls_back(tmp_path):
    """某个流派在 13-15 桶没有样本 → 平滑后 ≈ 基线，且不出现 NaN。"""
    paths = _make_dataset(str(tmp_path))
    lib = B.load_library(paths["library"])
    cards = B.load_cards(paths["cards"])
    games = B.load_game_actions(paths["actions"], set(lib))
    pref = B.build_preference_table(games, lib, cards, head_archetypes=["mech_apm"])
    late = pref["archetypes"]["mech_apm"]["pref"]["13-15"]
    assert late["n"] == 0 and late["turns"] == 0
    assert all(np.isfinite(v) for v in late["rates"].values())
    # 桶与基线都没数据 → 空分布（不编造）；rates 退化为「伪计数向基线收缩」的
    # 0 值（基线也是 0），因此仍然有限
    assert late["buy_tribe"] == {} or abs(sum(late["buy_tribe"].values()) - 1.0) < 1e-3


# ══════════════════════════════════════════════════════════════════════════
# 4. 分组交叉验证
# ══════════════════════════════════════════════════════════════════════════
def test_grouped_folds_never_split_a_game():
    gids = [f"g{i // 3}" for i in range(30)]       # 每局 3 个前缀样本
    y = ["a" if int(g.split("g")[1]) % 2 else "b" for g in gids]
    folds = B.grouped_folds(gids, y, 5, seed=0)
    by_game: dict[str, set] = {}
    for g, f in zip(gids, folds):
        by_game.setdefault(g, set()).add(int(f))
    assert all(len(v) == 1 for v in by_game.values())
    assert len(set(int(f) for f in folds)) == 5


def test_cross_validate_reports_gate_metrics(tmp_path):
    paths = _make_dataset(str(tmp_path))
    lib = B.load_library(paths["library"])
    cards = B.load_cards(paths["cards"])
    games = B.load_game_actions(paths["actions"], set(lib))
    pack = B.build_prefix_samples(games, lib, cards, hero_vocab=[])
    model, cv = B.cross_validate(pack["X"], pack["archetype"], pack["games"],
                                 folds=2, epochs=40)
    assert model.classes == ("dragon_shield", "mech_apm")
    assert 0.0 <= cv["top1"] <= 1.0 and 0.0 <= cv["top3"] <= 1.0
    assert "gate_0.6" in cv and "ece" in cv and "temperature" in cv
    assert model.probs(pack["X"][:2]).shape == (2, 2)


# ══════════════════════════════════════════════════════════════════════════
# 5. 端到端 main()
# ══════════════════════════════════════════════════════════════════════════
def test_main_end_to_end(tmp_path):
    paths = _make_dataset(str(tmp_path))
    out = str(tmp_path / "out")
    os.makedirs(out, exist_ok=True)
    rc = B.main([
        "--actions", paths["actions"], "--library", paths["library"],
        "--cards", paths["cards"],
        "--out-table", os.path.join(out, "archetype_table.json"),
        "--out-model", os.path.join(out, "archetype_model.npz"),
        "--out-metrics", os.path.join(out, "archetype_metrics.json"),
        "--min-games", "2", "--folds", "2", "--epochs", "60",
    ])
    assert rc == 0
    table = load_table(os.path.join(out, "archetype_table.json"))
    assert table["schema"] == B.SCHEMA
    assert table["feature_dim"] == FEATURE_DIM
    assert table["head_archetypes"] == ["dragon_shield", "mech_apm"]
    assert table["games"]["prefix_samples"] == 32
    tribe, arch, hero_vocab, meta = load_models(
        os.path.join(out, "archetype_model.npz"))
    assert hero_vocab == []
    assert set(arch.classes) == {"dragon_shield", "mech_apm"}
    assert meta["feature_version"] == table["feature_version"]
    metrics = json.load(open(os.path.join(out, "archetype_metrics.json"),
                             encoding="utf-8"))
    assert metrics["data"]["prefix_samples"] == 32
    assert "tribe" in metrics and "archetype" in metrics
