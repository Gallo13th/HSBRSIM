"""``scripts/human_arena.py``（人类对战 Web UI）行为测试。

覆盖（对应任务验收）：
1. 动作合法性映射：shop/hand/board/按钮给出的 action id 全部与 245 维掩码一致，
   且编码公式与 ``hsbg/env/action_space_std.py`` 逐位对得上；
2. 状态序列化：``/state`` JSON 可 dump、必填面板字段齐全、无 numpy 标量；
3. 非法动作：越界/掩码外动作抛 ``IllegalAction`` 且不改变对局；
4. replay 字段完整：meta/decision/summary 行，features 3227 + cards 124 + mask 245
   + action + turn，且 action 一定在 mask 内；
5. 完整对局：脚本化人类从 t1 打到结束（无卡死），placements 是 1..8 的排列；
6. replay -> BC npz：``scripts/train_compound_bc.py::load_npz`` 能直接解析；
7. HTTP 端点：GET /state、POST /act、POST /new、GET /replay 可用且非法动作 400。
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import os
import sys
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("hsbg_engine", reason="hsbg_engine 未安装（cd rust && pip install -e .）")

SPEC = importlib.util.spec_from_file_location(
    "human_arena", os.path.join(ROOT, "scripts", "human_arena.py"))
ha = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ha)

A = ha  # 别名，便于阅读


@pytest.fixture()
def session(tmp_path):
    return A.GameSession(seed=1234, seat=0, out_dir=str(tmp_path / "human_play"))


def _pick_hero(sess):
    st = sess.state()
    assert st["pending"] and st["pending"]["kind"] == "hero"
    return st["pending"]["options"][0]["action"]


# ── 1. 动作合法性映射 ─────────────────────────────────────────────────────


def test_action_mapping(session):
    st = session.state()
    assert st["phase"] == "hero_select"
    # 只允许 Choose(0)/Choose(1) 选英雄
    assert st["legal"] == [A.A_CHOOSE, A.A_CHOOSE + 1]
    assert [o["action"] for o in st["pending"]["options"]] == st["legal"]
    # 所有按钮 action 都在 0..244，且 enabled 与掩码一致
    for b in st["buttons"]:
        if b["action"] is None:
            continue
        assert 0 <= b["action"] < A.N_ACTIONS
        assert b["enabled"] == bool(st["mask"][b["action"]])

    session.act(_pick_hero(session))
    st = session.state()
    assert st["phase"] == "recruit"
    assert st["turn"] == 1
    # 酒馆槽位 -> Buy(slot) = 8 + slot
    for c in st["shop"]:
        if c["buy"] is None:
            assert not st["mask"][A.A_BUY + c["slot"]]
        else:
            assert c["buy"] == A.A_BUY + c["slot"]
            assert st["mask"][c["buy"]]
    # 买第一张牌，再打出手牌：Play{hand,pos} = 46 + hand*8 + pos
    buy = next(c["buy"] for c in st["shop"] if c["buy"] is not None)
    session.act(buy)
    st = session.state()
    assert st["hand"], "买牌后手牌应为空之外至少 1 张"
    card = st["hand"][0]
    assert card["play"], "刚买的手牌至少有一个合法打出位置"
    for p in card["play"]:
        assert p["action"] == A.A_PLAY + card["index"] * A.N_POS + p["pos"]
        assert st["mask"][p["action"]]
    play = card["play"][0]["action"]
    session.act(play)
    st = session.state()
    assert len(st["board"]) == 1
    # 场上 -> Sell(slot) = 16 + slot；Move{from,to} = 196 + from*7 + to
    for m in st["board"]:
        assert m["sell"] == A.A_SELL + m["index"]
        assert st["mask"][m["sell"]]
        for mv in m["move"]:
            assert mv["action"] == A.A_MOVE + m["index"] * A.N_BOARD + mv["to"]
            assert st["mask"][mv["action"]]


def test_pending_mapping_and_cancel():
    """target pending 的 Choose(i)=30+i、取消=7，均由掩码派生。"""
    mask = [0] * A.N_ACTIONS
    mask[A.A_CHOOSE] = 1
    mask[A.A_CHOOSE + 1] = 1
    mask[A.A_CANCEL] = 1
    out = A._pending_brief(
        {"kind": "target", "targets": [11, 12]}, mask, {11: "甲随从", 12: "乙随从"})
    assert out["kind"] == "target"
    assert [t["action"] for t in out["targets"]] == [A.A_CHOOSE, A.A_CHOOSE + 1]
    assert [t["name"] for t in out["targets"]] == ["甲随从", "乙随从"]
    assert out["cancel_action"] == A.A_CANCEL
    # 不在掩码里的选项 action 为 None（前端置灰而不是发非法动作）
    out2 = A._pending_brief({"kind": "discover", "options": [{}, {}]}, [0] * A.N_ACTIONS, {})
    assert [o["action"] for o in out2["options"]] == [None, None]
    assert out2["cancel_action"] is None


# ── 2. 状态序列化 ─────────────────────────────────────────────────────────
def test_state_serialization(session):
    st = session.state()
    payload = json.dumps(st, ensure_ascii=False)  # 不允许 numpy 类型漏出
    assert len(payload) > 1000
    for key in ("hud", "shop", "hand", "board", "buttons", "mask", "legal",
                "pending", "opponents", "replay", "phase", "turn"):
        assert key in st
    assert len(st["mask"]) == A.N_ACTIONS
    assert st["legal"] == [i for i, x in enumerate(st["mask"]) if x]
    for key in ("health", "gold", "tier", "upgrade_price", "refresh_price"):
        assert key in st["hud"]
    # 对手只暴露公开字段（不含 debug view 的实时 board）
    for o in st["opponents"]:
        assert "board" not in o
        assert "seen_board" in o and "hero" in o
    # 第一局每张牌都能拿到中文名
    session.act(_pick_hero(session))
    st = session.state()
    for c in st["shop"]:
        assert c["name_zh"]
        assert "buy" in c and "price" in c


# ── 3. 非法动作 ───────────────────────────────────────────────────────────


def test_illegal_actions_rejected(session):
    before = session.state()
    for bad in (-1, A.N_ACTIONS, 9999):
        with pytest.raises(A.IllegalAction):
            session.act(bad)
    illegal = [i for i, x in enumerate(before["mask"]) if not x][0]
    with pytest.raises(A.IllegalAction):
        session.act(illegal)
    assert session.decisions == 0
    assert session.state()["turn"] == before["turn"]
    # 选完英雄后 EndTurn 合法，但同一动作在 hero_select 阶段非法
    with pytest.raises(A.IllegalAction):
        session.act(A.A_END)


# ── 4. replay 字段 ────────────────────────────────────────────────────────


def test_replay_records(session):
    hero_action = _pick_hero(session)
    session.act(hero_action)
    st = session.state()
    buy = next(c["buy"] for c in st["shop"] if c["buy"] is not None)
    session.act(buy)
    st = session.state()
    play = next((c["play"][0]["action"] for c in st["hand"] if c["play"]), None)
    if play is not None:
        session.act(play)

    assert os.path.exists(session.replay_path)
    raw = session.replay_bytes()
    assert raw[:2] == b"\x1f\x8b"
    with gzip.open(session.replay_path, "rt", encoding="utf-8") as fh:
        lines = [json.loads(x) for x in fh if x.strip()]
    assert lines[0]["type"] == "meta"
    assert lines[0]["seed"] == 1234 and lines[0]["n_actions"] == A.N_ACTIONS
    dec = [r for r in lines if r.get("type") == "decision"]
    assert len(dec) == session.decisions == 2 + (1 if play is not None else 0)
    for i, r in enumerate(dec):
        assert r["decision"] == i
        assert len(r["features"]) == A.OBS_FLOATS
        assert len(r["cards"]) == A.OBS_CARDS
        assert len(r["mask"]) == A.N_ACTIONS
        assert r["action"] in range(A.N_ACTIONS)
        assert r["mask"][r["action"]] == 1
        assert np.isfinite(r["features"]).all()
        for key in ("turn", "tier", "gold", "phase", "seed", "seat"):
            assert key in r
    assert not [r for r in lines if r.get("type") == "summary"], "对局未结束时不应有 summary"


# ── 5. 完整对局 ───────────────────────────────────────────────────────────


def test_full_game_to_end(session):
    steps = 0
    while not session.over and steps < 4000:
        session.act(A.scripted_action(session.state()))
        steps += 1
    st = session.state()
    assert session.over and st["over"] and st["phase"] == "game_over"
    assert 5 <= session.decisions <= 3000
    assert sorted(st["placements"]) == list(range(1, 9))
    assert 1 <= st["placement"] <= 8
    with gzip.open(session.replay_path, "rt", encoding="utf-8") as fh:
        lines = [json.loads(x) for x in fh if x.strip()]
    summary = [r for r in lines if r.get("type") == "summary"]
    assert len(summary) == 1
    assert summary[0]["placements"] == st["placements"]
    assert summary[0]["placement"] == st["placement"]


# ── 6. replay -> BC npz（train_compound_bc.load_npz）────────────────────


def test_convert_replay_to_bc_npz(session, tmp_path):
    for _ in range(3):
        if session.over:
            break
        session.act(A.scripted_action(session.state()))
    out = tmp_path / "human_bc.npz"
    info = A.convert_replays(session.out_dir, str(out))
    assert info["decisions"] == session.decisions
    assert out.exists()

    spec = importlib.util.spec_from_file_location(
        "train_compound_bc", os.path.join(ROOT, "scripts", "train_compound_bc.py"))
    tcb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tcb)
    d = tcb.load_npz(str(out))
    n = info["decisions"]
    # load_npz 的契约：``obs`` 只含 3227 浮点，卡牌 id 单独在 ``cards``。
    assert d["obs"].shape == (n, A.OBS_FLOATS) and d["obs"].dtype == np.float32
    assert d["cards"].shape == (n, A.OBS_CARDS)
    assert d["mask"].shape == (n, A.N_ACTIONS) and d["mask"].dtype == np.bool_
    assert d["action"].shape == (n,)
    assert d["mask"][np.arange(n), d["action"]].all()
    assert d["mask"].any(axis=1).all()
    assert {"turn", "tier", "gold", "episode_id"} <= set(d)
    # 合并布局的卡牌 id 与独立 cards 字段逐值一致（>2048 的 id 不能丢精度）
    with np.load(out) as z:
        assert np.array_equal(np.rint(z["obs"][:, A.OBS_FLOATS:]).astype(np.int64),
                              d["cards"])
    # 英雄选择阶段可过滤
    info2 = A.convert_replays(session.out_dir, str(tmp_path / "no_hero.npz"),
                              skip_hero_select=True)
    assert info2["decisions"] == n - 1


# ── 7. HTTP 端点 ─────────────────────────────────────────────────────────


def test_http_endpoints(tmp_path):
    sess = A.GameSession(seed=777, seat=0, out_dir=str(tmp_path / "http"))
    srv = A.ArenaServer(("127.0.0.1", 0), sess)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"

    def call(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            base + path, data=data, method="POST" if data is not None else "GET",
            headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    try:
        code, raw = call("/")
        assert code == 200 and b"HSBRSIM" in raw
        code, raw = call("/health")
        assert code == 200 and json.loads(raw)["ok"] is True
        code, raw = call("/state")
        st = json.loads(raw)
        assert code == 200 and st["phase"] == "hero_select"
        code, raw = call("/act", {"action": st["pending"]["options"][0]["action"]})
        assert code == 200 and json.loads(raw)["turn"] == 1
        code, raw = call("/act", {"action": 999})
        assert code == 400 and "越界" in json.loads(raw)["error"]
        code, raw = call("/new", {"seed": 555})
        assert code == 200 and json.loads(raw)["seed"] == 555
        code, raw = call("/state")
        st = json.loads(raw)
        code, raw = call("/snapshot")
        assert code == 200 and b"/*STATE_JSON*/null" not in raw
        assert b'"shop"' in raw and b"HSBRSIM" in raw
        code, raw = call("/replay")
        assert code == 200 and raw[:2] == b"\x1f\x8b"
    finally:
        srv.shutdown()
        srv.server_close()
        th.join(timeout=5)
