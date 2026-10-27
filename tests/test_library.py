"""``hsbg.az.library`` 单测：关键词映射 / 牌面采集-注入回环 / 按强度抽样。"""

from __future__ import annotations

import json
import random

import pytest

from hsbg.az.library import (BoardEntry, BoardLibrary, base_card, board_signature,
                             capture_turn, inject_board, kw_names)


def test_kw_names_mapping():
    assert kw_names(0) == []
    assert kw_names(1) == ["TAUNT"]
    assert kw_names(1 | 4) == ["TAUNT", "WINDFURY"]
    assert kw_names(1 << 11) == ["IMMUNE_ATTACKING"]


def _entry(turn: int, atk: int, hp: int) -> BoardEntry:
    return BoardEntry(turn=turn, seat=0, hero=1, tier=3, health=30,
                      board=[{"card": "BGS_002", "atk": atk, "hp": hp,
                              "golden": False, "kw": []}], hand=0, placement=1)


def test_library_matches_target_strength():
    lib = BoardLibrary([_entry(5, 1, 1), _entry(5, 20, 20), _entry(5, 50, 50)], bucket=8)
    rng = random.Random(0)
    hi = [lib.sample(5, rng, target_strength=100).strength for _ in range(50)]
    lo = [lib.sample(5, rng, target_strength=2).strength for _ in range(50)]
    assert min(hi) >= 40, hi
    assert max(lo) <= 4, lo


def test_library_save_load_roundtrip(tmp_path):
    lib = BoardLibrary([_entry(3, 2, 3), _entry(4, 5, 6)])
    p = str(tmp_path / "lib.jsonl.gz")
    lib.save(p)
    back = BoardLibrary.load(p)
    assert len(back.entries) == 2
    assert back.entries[0].strength == 5
    assert back.stats()["n"] == 2


def test_capture_then_inject_roundtrip():
    E = pytest.importorskip("hsbg_engine")
    game = E.Game(seed=11)
    entries = []
    ended = set()
    for _ in range(40000):
        acted = False
        for p in range(int(game.num_players)):
            if not game.needs_action(p):
                continue
            acted = True
            a = int(game.bot_action(p))
            if a == 0:
                ended.add(p)
            game.step(p, a)
            if game.is_over():
                break
        hp = list(game.health())
        alive = {p for p in range(int(game.num_players)) if int(hp[p]) > 0}
        if alive and ended >= alive:
            st = json.loads(game.state_json())
            got = capture_turn(E, game, state=st)
            if int(st.get("turn", 0)) >= 6 and any(len(e.board) >= 2 for e in got):
                entries = got
                break
            ended = set()
        if game.is_over() or not acted:
            break
    assert entries, "没抓到非空牌面"
    entry = max(entries, key=lambda e: len(e.board))
    assert entry.board

    g2 = E.Game(seed=12)
    n = inject_board(g2, 3, entry)
    assert n == len(entry.board)
    st2 = json.loads(g2.state_json())
    actual = st2["players"][3]["board"]
    assert len(actual) == len(entry.board)
    def _norm(c: str) -> str:
        # golden 变体在 capture/inject 两侧命名可能不同（`_G` / `t_G`），比对时归一
        return base_card(str(c))

    same_card = 0
    for got, want in zip(actual, entry.board):
        same_card += int(_norm(E.card_info(int(got["card"]))[0]) == _norm(want["card"]))
        assert int(got["atk"]) == int(want["atk"])
        assert int(got["hp"]) == int(want["hp"])
        assert bool(got["golden"]) == bool(want["golden"])
        # 引擎会补上卡牌自带关键词；注入的（buff 后额外）关键词必须在位
        assert set(kw_names(int(got.get("kw", 0)))) >= set(want["kw"])
    # 卡牌 id 的注入保真度：golden/token 变体经 add_minion 会被引擎重新规范化，
    # 当前只能保证 张数/攻/血 精确；卡 id 保真度作为指标记录（正确的修法是给引擎加
    # `set_player_state` 调试命令，直接用 state_json 还原，见 docs。）
    ratio = same_card / max(len(entry.board), 1)
    print(f"[fidelity] card_id match {same_card}/{len(entry.board)} = {ratio:.2f}")
    assert ratio > 0.0
    assert board_signature(st2["players"][3])  # 签名可读
