"""人类战团混池脚本 ``scripts/mix_human_libraries.py`` 的单测（纯 CPU，无 torch/引擎依赖）。

覆盖任务清单要求：

1. **去重**：``(game_id, turn, frame_signature)`` 帧级去重（同局同回合同帧；跨库按源顺序
   先出现者胜），且 ``golden/kw`` 不同 → 不是同一帧；
2. **权重**：``proportional`` 口径下输出占比 = 权重（不超采样），可用行数不足的源被削平；
   ``keep-all`` 保留全部行；
3. **空输入**：空文件 / 全空库不崩溃，输出 0 行且统计自洽；
4. **幂等**：同输入 + 同 seed 两次运行 → 输出 JSONL 逐字节一致；
5. **按 turn 分层**：配额按各源 turn 行数比例分配（不被行数最多的 turn 带偏）。

脚本不是包内模块，测试用 ``importlib`` 按路径加载。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mix_human_libraries.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("mix_human_libraries", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclass 需要在 ``sys.modules`` 里能找到模块（Python 3.14 起强制）。
    import sys

    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


MIX = _load_module()


# ────────────────────────── 工具 ──────────────────────────


def row(turn: int, board, *, game_id: str = "g1", strength=None,
        gold=None, hero_hp=None, main_placement=None, detail: bool = True,
        tier=3, perspective: str = "self", golden: bool = False, kw: int = 0,
        hand=None, source: str = "synthetic"):
    """构造一条与准完整库同构的行（``board`` 为 ``[(card, atk, hp), ...]``）。"""
    flat = [[int(c), int(a), int(h)] for (c, a, h) in board]
    if strength is None:
        strength = sum(int(a) + int(h) for (_c, a, h) in board)
    out = {
        "turn": int(turn),
        "strength": int(strength),
        "board": flat,
        "hand": list(hand or []),
        "hand_available": True,
        "tier": int(tier) if tier is not None else None,
        "hero": 371,
        "source": str(source),
        "schema": "hsbg.human_state_quasi_full",
        "schema_version": 1,
        "game_id": str(game_id),
        "split": "train",
        "perspective": str(perspective),
    }
    if detail:
        out["board_detail"] = [
            {"card": int(c), "atk": int(a), "hp": int(h), "golden": bool(golden),
             "kw": int(kw), "bonus_kw": 0, "shield_max": 1}
            for (c, a, h) in board
        ]
    if gold is not None:
        out["gold"] = int(gold)
    if hero_hp is not None:
        out["hero_hp"] = int(hero_hp)
    if main_placement is not None:
        out["main_placement"] = int(main_placement)
    return out


def write_jsonl(path: Path, rows) -> str:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")
    return str(path)


def source(name: str, path: str, weight: float):
    return MIX.Source(name=name, path=path, weight=weight)


def read_jsonl(path: Path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


# ────────────────────────── 1. 去重 ──────────────────────────


def test_dedupe_same_frame_within_and_across_sources(tmp_path: Path):
    """同 (game_id, turn, 战团/手牌/tier/视角) 的帧只保留**先出现**的一条。"""
    a = row(9, [(100, 10, 10)], game_id="gA", hand=[{"card": 5, "kind": "minion"}])
    a_dup = dict(a)                        # 完全重复
    b = row(9, [(100, 10, 10)], game_id="gA", hand=[{"card": 5, "kind": "minion"}],
            source="synthetic2")           # 跨库同帧
    b_other_turn = row(10, [(100, 10, 10)], game_id="gA",
                       hand=[{"card": 5, "kind": "minion"}])
    b_other_game = row(9, [(100, 10, 10)], game_id="gB",
                       hand=[{"card": 5, "kind": "minion"}])
    b_other_board = row(9, [(100, 11, 10)], game_id="gA",
                        hand=[{"card": 5, "kind": "minion"}])

    p1 = write_jsonl(tmp_path / "a.jsonl", [a, a_dup, b_other_turn, b_other_game])
    p2 = write_jsonl(tmp_path / "b.jsonl", [b, b_other_board])
    out = tmp_path / "mixed.jsonl"
    res = MIX.mix_libraries([source("a", p1, 0.5), source("b", p2, 0.5)],
                            out=str(out), stats_out=str(tmp_path / "stats.json"),
                            sizing="keep-all", seed=1)
    assert res.stats["totals"]["rows_input"] == 6
    # a 里 a_dup 被去重；b 里 b 与 a 同帧被去重；b_other_board 不重复。
    assert res.stats["sources"][0]["dedup_removed"] == 1
    assert res.stats["sources"][1]["dedup_removed"] == 1
    assert res.stats["totals"]["rows_out"] == 4
    # 保留的是先出现的 a（source 顺序 = 优先级）：b 被丢，但 b 的其它帧照常保留。
    kept = read_jsonl(out)
    assert sum(1 for r in kept if r["source"] == "synthetic") == 4
    assert sum(1 for r in kept if r["source"] == "synthetic2") == 0  # 与 a 同帧，被丢
    assert sorted(r["board"][0][1] for r in kept) == [10, 10, 10, 11]


def test_detail_bits_are_part_of_signature(tmp_path: Path):
    """同一战团但 ``golden`` / ``kw`` 不同 → 不同帧（隐藏状态位参与签名）。"""
    a = row(8, [(10, 2, 2)], game_id="g1", golden=False, kw=0)
    b = row(8, [(10, 2, 2)], game_id="g1", golden=True, kw=1)
    c = row(8, [(10, 2, 2)], game_id="g1", golden=False, kw=0, detail=False)

    p = write_jsonl(tmp_path / "x.jsonl", [a, b, c])
    out = tmp_path / "mixed.jsonl"
    res = MIX.mix_libraries([source("x", p, 1.0)], out=str(out),
                            stats_out=str(tmp_path / "s.json"), sizing="keep-all")
    kept = read_jsonl(out)
    assert len(kept) == 2, "a 与 b 是两个不同帧（golden/kw 不同）；c 是 a 的低信息版本 -> 被丢"
    assert {bool(r["board_detail"][0]["golden"]) for r in kept} == {False, True}
    assert res.stats["sources"][0]["dedup_low_detail"] == 1
    assert MIX.frame_signature(a) != MIX.frame_signature(b)
    assert MIX.frame_signature(a) != MIX.frame_signature(c)


def test_frame_signature_ignores_provenance_fields():
    """``source`` / ``strength`` / ``file`` / ``mmr`` 等来源字段不进签名。"""
    a = row(5, [(3, 4, 5)], game_id="g")
    b = dict(a, source="firestone_pms+xml", strength=999, file="x.jsonl", mmr=9000)
    assert MIX.frame_signature(a) == MIX.frame_signature(b)


def test_degraded_known_hand_counts_as_hand(tmp_path: Path):
    """degraded 的 ``known_hand`` 与准完整的 ``hand`` 视为同一手牌（同粗键）。"""
    a = row(6, [(3, 4, 5)], game_id="g", hand=[{"card": 7, "kind": "minion"}])
    b = row(6, [(3, 4, 5)], game_id="g", detail=False, hand=None)
    del b["hand"]                       # degraded 库没有 hand 字段，只有 known_hand
    b["known_hand"] = [{"card": 7, "card_id": "BG_X"}]
    assert MIX.coarse_key(a) == MIX.coarse_key(b)
    p = write_jsonl(tmp_path / "x.jsonl", [a, b])
    out = tmp_path / "o.jsonl"
    res = MIX.mix_libraries([source("x", p, 1.0)], out=str(out), sizing="keep-all")
    kept = read_jsonl(out)
    assert len(kept) == 1 and "board_detail" in kept[0], "只保留信息更全的那条"
    assert res.stats["totals"]["dedup_low_detail"] == 1


# ────────────────────────── 2. 权重 ──────────────────────────


def test_proportional_quotas_follow_weights(tmp_path: Path):
    """``proportional``：占比 = 权重，且可用行数不足的源被削平（不超采样）。"""
    mk = lambda name, n: write_jsonl(
        tmp_path / f"{name}.jsonl",
        [row(5 + (i % 3), [(100 + i, 2 + i, 3)], game_id=f"{name}{i}") for i in range(n)])
    p_a, p_b, p_c = mk("a", 1000), mk("b", 600), mk("c", 400)
    out = tmp_path / "mixed.jsonl"
    res = MIX.mix_libraries(
        [source("a", p_a, 0.5), source("b", p_b, 0.6), source("c", p_c, 0.2)],
        out=str(out), stats_out=str(tmp_path / "s.json"), sizing="proportional", seed=7)
    # N = floor(min(1000/0.5, 600/0.6, 400/0.2)) = 1000 -> quota 500 / 600 / 200
    quotas = [s["quota"] for s in res.stats["sources"]]
    assert quotas == [500, 600, 200]
    assert res.stats["totals"]["rows_out"] == sum(quotas) == 1300
    assert len(read_jsonl(out)) == 1300


def test_proportional_quota_shares_match_weights(tmp_path: Path):
    """大库充裕时，输出占比 = 权重（误差来自取整，<=1 行/源）。"""
    mk = lambda name, n: write_jsonl(
        tmp_path / f"{name}.jsonl",
        [row(6, [(100 + i, 2, 3)], game_id=f"{name}{i}") for i in range(n)])
    p_a, p_b, p_c = mk("a", 5000), mk("b", 5000), mk("c", 5000)
    out = tmp_path / "mixed.jsonl"
    res = MIX.mix_libraries(
        [source("a", p_a, 0.5), source("b", p_b, 0.3), source("c", p_c, 0.2)],
        out=str(out), stats_out="", sizing="proportional", seed=3)
    total = res.stats["totals"]["rows_out"]
    shares = [s["rows_out"] / total for s in res.stats["sources"]]
    assert shares[0] == pytest.approx(0.5, abs=0.01)
    assert shares[1] == pytest.approx(0.3, abs=0.01)
    assert shares[2] == pytest.approx(0.2, abs=0.01)
    assert total == 10000  # 5000/0.5


def test_keep_all_uses_every_row(tmp_path: Path):
    """``keep-all``：只去重，不因权重丢行。"""
    p1 = write_jsonl(tmp_path / "a.jsonl", [row(5, [(1, 1, 1)], game_id=f"a{i}")
                                            for i in range(3)])
    p2 = write_jsonl(tmp_path / "b.jsonl", [row(5, [(2, 2, 2)], game_id=f"b{i}")
                                            for i in range(4)])
    out = tmp_path / "mixed.jsonl"
    res = MIX.mix_libraries([source("a", p1, 0.9), source("b", p2, 0.1)],
                            out=str(out), sizing="keep-all", seed=1)
    assert res.stats["totals"]["rows_out"] == 7


def test_max_rows_caps_output(tmp_path: Path):
    p1 = write_jsonl(tmp_path / "a.jsonl", [row(5, [(1, 1, 1)], game_id=f"a{i}")
                                            for i in range(100)])
    p2 = write_jsonl(tmp_path / "b.jsonl", [row(5, [(2, 2, 2)], game_id=f"b{i}")
                                            for i in range(100)])
    out = tmp_path / "mixed.jsonl"
    res = MIX.mix_libraries([source("a", p1, 0.5), source("b", p2, 0.5)],
                            out=str(out), sizing="keep-all", seed=1, max_rows=40)
    assert res.stats["totals"]["rows_out"] == 40


def test_zero_weight_source_contributes_nothing(tmp_path: Path):
    p1 = write_jsonl(tmp_path / "a.jsonl", [row(5, [(1, 1, 1)], game_id="a0")])
    p2 = write_jsonl(tmp_path / "b.jsonl", [row(5, [(2, 2, 2)], game_id="b0")])
    out = tmp_path / "mixed.jsonl"
    res = MIX.mix_libraries([source("a", p1, 1.0), source("b", p2, 0.0)],
                            out=str(out), sizing="proportional", seed=1)
    assert res.stats["sources"][1]["quota"] == 0
    assert res.stats["totals"]["rows_out"] == 1


# ────────────────────────── 3. 空输入 ──────────────────────────


def test_empty_libraries(tmp_path: Path):
    """空文件：不崩溃，输出 0 行，统计自洽。"""
    p1 = write_jsonl(tmp_path / "a.jsonl", [])
    p2 = write_jsonl(tmp_path / "b.jsonl", [])
    out = tmp_path / "mixed.jsonl"
    res = MIX.mix_libraries([source("a", p1, 0.5), source("b", p2, 0.5)],
                            out=str(out), stats_out=str(tmp_path / "s.json"),
                            sizing="proportional")
    assert res.stats["totals"]["rows_out"] == 0
    assert out.read_text(encoding="utf-8") == ""
    stats = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert stats["totals"]["rows_input"] == 0
    assert stats["totals"]["turn_min"] == 0


def test_one_empty_source_zeroes_proportional_pool(tmp_path: Path):
    """空源 + proportional：N=0（不能凭空放大其它源），keep-all 仍可用。"""
    p1 = write_jsonl(tmp_path / "a.jsonl", [row(5, [(1, 1, 1)], game_id="a0")])
    p2 = write_jsonl(tmp_path / "b.jsonl", [])
    out = tmp_path / "mixed.jsonl"
    res = MIX.mix_libraries([source("a", p1, 0.5), source("b", p2, 0.5)],
                            out=str(out), sizing="proportional")
    assert res.stats["totals"]["rows_out"] == 0
    res2 = MIX.mix_libraries([source("a", p1, 0.5), source("b", p2, 0.5)],
                             out=str(out), sizing="keep-all")
    assert res2.stats["totals"]["rows_out"] == 1


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        MIX.mix_libraries([source("a", str(tmp_path / "nope.jsonl"), 1.0)],
                          out=str(tmp_path / "o.jsonl"))


def test_no_sources_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        MIX.mix_libraries([], out=str(tmp_path / "o.jsonl"))


def test_bad_lines_are_counted_not_fatal(tmp_path: Path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"turn": 5, "board": [[1, 1, 1]], "game_id": "g", "strength": 2}\n'
                 'not json\n\n', encoding="utf-8")
    res = MIX.mix_libraries([source("a", str(p), 1.0)], out=str(tmp_path / "o.jsonl"),
                            sizing="keep-all")
    assert res.stats["sources"][0]["bad_lines"] == 1
    assert res.stats["totals"]["rows_out"] == 1


# ────────────────────────── 4. 幂等 ──────────────────────────


def test_idempotent_bytes_and_stats(tmp_path: Path):
    """同输入同 seed 两次运行：JSONL 逐字节一致，统计（去掉时间戳）一致。"""
    rows_a = [row(5 + (i % 4), [(100 + i, 2, 3)], game_id=f"a{i}")
              for i in range(200)]
    rows_b = [row(5 + (i % 3), [(500 + i, 3, 4)], game_id=f"b{i}") for i in range(150)]
    p1 = write_jsonl(tmp_path / "a.jsonl", rows_a)
    p2 = write_jsonl(tmp_path / "b.jsonl", rows_b)

    out1, out2 = tmp_path / "m1.jsonl", tmp_path / "m2.jsonl"
    s1, s2 = tmp_path / "s1.json", tmp_path / "s2.json"
    srcs = [source("a", p1, 0.5), source("b", p2, 0.5)]
    MIX.mix_libraries(srcs, out=str(out1), stats_out=str(s1), seed=11)
    MIX.mix_libraries(srcs, out=str(out2), stats_out=str(s2), seed=11)
    assert out1.read_bytes() == out2.read_bytes()

    d1 = json.loads(s1.read_text(encoding="utf-8"))
    d2 = json.loads(s2.read_text(encoding="utf-8"))
    for d in (d1, d2):
        d.pop("generated_at", None)
        d.pop("elapsed_s", None)
        d.pop("out", None)
        if isinstance(d.get("pool_check"), dict):
            d["pool_check"].pop("error", None)
    assert d1 == d2


# ────────────────────────── 5. 分层 / CLI ──────────────────────────


def test_turn_stratified_sampling(tmp_path: Path):
    """配额按源内 turn 行数比例分配：t1 与 t9 各 100 行、quota 50 -> 各 25 行。"""
    rows = ([row(1, [(i + 1, 1, 1)], game_id=f"t1_{i}") for i in range(100)]
            + [row(9, [(i + 1, 1, 1)], game_id=f"t9_{i}") for i in range(100)])
    p = write_jsonl(tmp_path / "a.jsonl", rows)
    out = tmp_path / "m.jsonl"
    res = MIX.mix_libraries([source("a", p, 1.0)], out=str(out), seed=5, max_rows=50,
                            sizing="proportional")
    hist = res.stats["turn_hist"]
    assert hist.get("1") == 25 and hist.get("9") == 25


def test_parse_source_spec():
    s = MIX._parse_source("high=data/real_library/library_real_quasi_full.jsonl:0.6")
    assert s.name == "high" and s.weight == 0.6
    assert s.path.endswith("library_real_quasi_full.jsonl")
    s2 = MIX._parse_source("data/real_library/library_firestone_recent.jsonl:0.3")
    assert s2.name == "firestone_recent" and s2.weight == 0.3
    with pytest.raises(ValueError):
        MIX._parse_source("no-weight.jsonl")
    with pytest.raises(ValueError):
        MIX._parse_source("x.jsonl:notafloat")
    with pytest.raises(ValueError):
        MIX._parse_source("x.jsonl:-1")


def test_cli_end_to_end(tmp_path: Path):
    p1 = write_jsonl(tmp_path / "a.jsonl", [row(5, [(1, 1, 1)], game_id="a0"),
                                            row(6, [(2, 2, 2)], game_id="a1")])
    p2 = write_jsonl(tmp_path / "b.jsonl", [row(5, [(3, 3, 3)], game_id="b0")])
    out = tmp_path / "out.jsonl"
    stats = tmp_path / "stats.json"
    rc = MIX.main(["--source", f"a={p1}:0.5", "--source", f"b={p2}:0.5",
                   "--out", str(out), "--stats-out", str(stats),
                   "--sizing", "keep-all", "--seed", "2", "--quiet"])
    assert rc == 0
    assert len(read_jsonl(out)) == 3
    st = json.loads(stats.read_text(encoding="utf-8"))
    assert st["sizing"] == "keep-all" and st["totals"]["rows_out"] == 3
    assert [s["name"] for s in st["sources"]] == ["a", "b"]
    # 统计里有强度 p50 对比（每源 + 混池）
    assert "5" in st["strength_by_turn_mixed"]
    assert st["sources"][0]["strength_by_turn_in"]["5"]["p50"] == 2


def test_turn_filter_keeps_only_high_turns(tmp_path: Path):
    """``min_turn/max_turn``：只保留高端回合（「Firestone 只补 t>=10 上限」配方）。"""
    rows = [row(t, [(100 + t, 2, 3)], game_id=f"g{t}") for t in (5, 9, 10, 12, 15)]
    p = write_jsonl(tmp_path / "a.jsonl", rows)
    out = tmp_path / "m.jsonl"
    res = MIX.mix_libraries([source("a", p, 1.0)], out=str(out), sizing="keep-all",
                            min_turn=10)
    kept = read_jsonl(out)
    assert [r["turn"] for r in kept] == [10, 12, 15]
    assert res.stats["sources"][0]["rows_out_of_turn"] == 2
    assert res.stats["turn_filter"] == [10, 0]
    res2 = MIX.mix_libraries([source("a", p, 1.0)], out=str(out), sizing="keep-all",
                             min_turn=9, max_turn=12)
    assert [r["turn"] for r in read_jsonl(out)] == [9, 10, 12]


def test_parse_source_turn_window():
    """``--source NAME=PATH:WEIGHT@MIN-MAX``：单源 turn 窗口解析（两端可省略）。"""
    s = MIX._parse_source("fs=a.jsonl:0.3@10-")
    assert (s.min_turn, s.max_turn) == (10, 0)
    s = MIX._parse_source("fs=a.jsonl:0.3@-12")
    assert (s.min_turn, s.max_turn) == (0, 12)
    s = MIX._parse_source("fs=a.jsonl:0.3@9-12")
    assert (s.min_turn, s.max_turn) == (9, 12)
    s = MIX._parse_source("a.jsonl:0.3")
    assert (s.min_turn, s.max_turn) == (0, 0)
    with pytest.raises(ValueError):
        MIX._parse_source("a.jsonl:0.3@x-y")


def test_per_source_turn_window_only_filters_that_source(tmp_path: Path):
    """单源窗口只作用于该源：quasi 保留全回合，Firestone 只取 t>=10。"""
    high = write_jsonl(tmp_path / "high.jsonl",
                       [row(t, [(100 + t, 2, 3)], game_id=f"h{t}") for t in (5, 9, 10, 12)])
    fs = write_jsonl(tmp_path / "fs.jsonl",
                     [row(t, [(200 + t, 2, 3)], game_id=f"f{t}") for t in (5, 9, 10, 12)])
    out = tmp_path / "m.jsonl"
    res = MIX.mix_libraries([MIX.Source("high", high, 0.8),
                             MIX._parse_source(f"fs={fs}:0.2@10-")],
                            out=str(out), sizing="keep-all")
    kept = read_jsonl(out)
    assert [r["turn"] for r in kept if str(r["game_id"]).startswith("h")] == [5, 9, 10, 12]
    assert [r["turn"] for r in kept if str(r["game_id"]).startswith("f")] == [10, 12]
    assert res.stats["sources"][1]["turn_window"] == [10, 0]
    assert res.stats["sources"][1]["rows_out_of_turn"] == 2
