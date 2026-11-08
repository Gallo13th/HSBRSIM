"""``scripts/human_arena.py`` 人类对战 UI 信息升级测试（对应 docs/HUMAN_ARENA_UI_SPEC.md）。

覆盖 8 项：
1. 单卡展示字段：种族/关键词（动态+卡面）/金卡/tier/效果/价格/附件/数值拆解/卡图 URL；
2. 卡图 URL 与 HTML ``onerror`` 文字占位回退；
3. 商店/手牌/战场的实际价格、原因、位置与附件字段；
4. 第 6 回合饰品四选一（pending）与已获得饰品（hud.trinkets）；
5. 黑暗之赐 cost/uses/max_uses/tiers + 按钮价格/原因；
6. 对手栏（英雄/血/甲/上次所见战团）与自己上轮战果（胜/负/平+伤害）；
7. ``/snapshot`` 注入的中局状态文本含种族/关键词/饰品；
8. 非法动作给出原因，HTTP 400 回包带 action。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("hsbg_engine", reason="hsbg_engine 未安装（cd rust && pip install -e .）")

SPEC = importlib.util.spec_from_file_location(
    "human_arena_ui", os.path.join(ROOT, "scripts", "human_arena.py"))
ha = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ha)
A = ha


# ── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def mid_session(tmp_path_factory):
    """打到第 6 回合的饰品 pending（确定性 seed=1234；之后测试会选中饰品）。"""
    out = tmp_path_factory.mktemp("human_ui")
    sess = A.GameSession(seed=1234, seat=0, out_dir=str(out))
    for _ in range(4000):
        st = sess.state()
        pend = st.get("pending") or {}
        if pend.get("kind") == "trinket":
            return sess
        sess.act(A.scripted_action(st))
        if sess.over:
            break
    pytest.fail("seed=1234 未出现第 6 回合饰品选择")


def _fresh_session(tmp_path, seed=1234):
    return A.GameSession(seed=seed, seat=0, out_dir=str(tmp_path / "play"))


def _pick_hero(sess):
    st = sess.state()
    return st["pending"]["options"][0]["action"]


# ── 1. 单卡展示字段 ───────────────────────────────────────────────────────


def test_card_brief_fields():
    """种族/关键词/金卡/tier/效果/价格/附件/拆解/卡图 字段齐全且语义正确。"""
    raw = {
        "id": "BGS_121", "name": "Gentle Djinni", "name_zh": "温和的灯神",
        "kind": "minion", "type": "minion", "tier": 6,
        "atk": 7, "hp": 9, "max_hp": 11, "base_atk": 5, "base_hp": 6,
        "golden": True, "races": ["ELEMENTAL", "DRAGON"],
        "keywords": ["TAUNT", "DIVINE_SHIELD"],
        "text_zh": "嘲讽，圣盾。战吼：随机获取一张元素牌。",
        "attached": [{"id": "BG36_MagicItem_404", "name_zh": "腐蚀的节杖",
                      "kind": "dark_gift", "text": "使你的神明获得+4/+4。"}],
        "breakdown": {
            "base": [5, 6],
            "mods": [{"kind": "magnetic", "atk": 2, "hp": 3,
                      "src": {"id": "BGS_121", "name_zh": "磁力来源"}}],
            "this_game_bonus": [0, 0], "temporary": [0, 0], "other": [0, 0], "damage": 0,
        },
    }
    c = A._card_brief(raw)
    assert c["name_zh"] == "温和的灯神"
    assert c["card_id"] == "BGS_121"
    assert c["art"] == "https://art.hearthstonejson.com/v1/orig/BGS_121.png"
    assert c["is_minion"] is True
    assert c["tier_label"] == "★6"
    assert c["race_labels"] == ["元素", "龙"] and c["race_text"] == "元素/龙"
    assert c["golden"] is True and c["golden_label"] == "金色"
    assert c["atk"] == 7 and c["hp"] == 9 and c["max_hp"] == 11
    assert c["keyword_labels"] == ["嘲讽", "圣盾"]
    # 卡面静态关键词不含动态 12 位；静态表可用时应补出战吼
    assert "TAUNT" not in c["card_keywords"] and "DIVINE_SHIELD" not in c["card_keywords"]
    if A._static_card_db():
        assert "BATTLECRY" in c["card_keywords"]
        assert "战吼" in c["card_keyword_labels"]
    assert c["text_note"] == "卡面" and "战吼" in c["text"]
    assert c["attached"][0]["kind_label"] == "黑暗之赐"
    assert c["attached"][0]["art"].endswith("/BG36_MagicItem_404.png")
    if A._static_card_db():
        mag = next((cid for cid, d in A._static_card_db().items()
                    if "MAGNETIC" in (d.get("keywords") or [])), None)
        assert mag, "静态卡表应存在磁力随从"
        att = A._attached_brief([
            {"id": mag, "name_zh": "磁力随从", "kind": "minion"},
            {"id": "BG20_GEM", "name_zh": "鲜血宝石", "kind": "spell"},
        ])
        assert [x["kind_label"] for x in att] == ["磁力", "鲜血宝石"]
    assert c["breakdown"]["mods"][0]["src_name"] == "磁力来源"
    assert "基础 5/6" in c["breakdown_text"] and "磁力来源" in c["breakdown_text"]
    # 空卡不会抛异常
    assert A._card_brief(None)["card_id"] == ""


# ── 2. 卡图 URL / 占位回退 ────────────────────────────────────────────────


def test_card_art_url_and_fallback():
    assert A.art_url("BGS_121") == "https://art.hearthstonejson.com/v1/orig/BGS_121.png"
    assert A.art_url("BG20_HERO_103").endswith("/BG20_HERO_103.png")
    assert A.art_url("") == "" and A.art_url(None) == ""
    html = A.INDEX_HTML
    # 卡图 URL 由 /state 的 art 字段提供；页面只负责 <img onerror> 回退
    assert "onerror" in html and "artph" in html
    # 卡图是可选增强：JS 渲染不依赖图片加载成功
    assert "this.remove()" in html


# ── 3. 商店/手牌/战场字段 ─────────────────────────────────────────────────


def test_shop_hand_board_fields(tmp_path):
    sess = _fresh_session(tmp_path)
    sess.act(_pick_hero(sess))
    st = sess.state()
    assert st["shop"], "t1 酒馆应有牌"
    for c in st["shop"]:
        assert c["price_label"] and ("金" in c["price_label"] or "不可" in c["price_label"])
        if c["buy"] is not None:
            assert c["buy_reason"] == ""
        else:
            assert c["buy_reason"], "不可购买的槽位必须给出原因"
        assert c["race_text"] and c["tier_label"]
        assert c["art"].startswith("https://art.hearthstonejson.com")
        assert "text" in c and "keyword_labels" in c
    buy = next(c["buy"] for c in st["shop"] if c["buy"] is not None)
    sess.act(buy)
    st = sess.state()
    hand = st["hand"]
    assert hand and hand[0]["play_cost_label"]
    assert hand[0]["play"] and hand[0]["play_reason"] == ""
    sess.act(hand[0]["play"][0]["action"])
    st = sess.state()
    m = st["board"][0]
    assert m["position_label"] == "1 号位"
    assert m["max_hp"] is not None and isinstance(m["breakdown"], dict)
    assert isinstance(m["attached"], list) and "attached_names" in m
    assert m["sell"] is not None and m["sell_reason"] == ""
    assert m["tier_label"] == "★%d" % m["tier"]


# ── 4. 饰品（pending + 已获得）─────────────────────────────────────────────


def test_trinket_pending_and_owned(mid_session):
    st = mid_session.state()
    pend = st["pending"]
    assert pend and pend["kind"] == "trinket"
    assert pend["kind_label"] == "选择饰品" and "四选一" in pend["hint"]
    assert len(pend["options"]) == 4
    for o in pend["options"]:
        assert o["name_zh"] and o["text"], "饰品必须带效果说明"
        assert o["kind"] in ("trinket_lesser", "trinket_greater")
        assert o["price_label"]
        assert o["action"] is not None
    assert st["hud"]["trinkets"] == [] or isinstance(st["hud"]["trinkets"], list)
    # 选中一个饰品后常驻 hud.trinkets
    mid_session.act(pend["options"][0]["action"])
    st = mid_session.state()
    trs = st["hud"]["trinkets"]
    assert len(trs) == 1
    t = trs[0]
    assert t["name_zh"] and t["text"] and t["slot_tag"] in ("小饰品", "大饰品")
    assert t["kind"] in ("trinket_lesser", "trinket_greater")


# ── 5. 黑暗之赐 + 按钮价格/原因 ───────────────────────────────────────────


def test_dark_gift_and_buttons(mid_session, tmp_path):
    st = mid_session.state()
    dg = st["hud"]["dark_gift"]
    for key in ("cost", "uses", "max_uses", "tiers", "next_tiers", "available",
                "unlock_turn", "used_this_turn", "action", "enabled", "reason"):
        assert key in dg
    assert dg["action"] == A.A_DARK_GIFT and isinstance(dg["tiers"], list)
    assert dg["cost_label"].endswith("金") and "/" in dg["uses_label"]
    btn = next(b for b in st["buttons"] if b["key"] == "dark_gift")
    assert btn["label"] == "黑暗之赐" and btn["price"] == dg["cost"]
    assert "已用" in btn["hint"] and btn["enabled"] == bool(st["mask"][A.A_DARK_GIFT])
    # 每个按钮都有动作/价格/提示/原因；禁用时必须给原因
    for b in st["buttons"]:
        for key in ("key", "label", "action", "enabled", "price", "hint", "reason"):
            assert key in b
        if not b["enabled"]:
            assert b["reason"], "禁用按钮必须给出原因"
    # t1 金币 3 < 升级 5：升级按钮禁用并给出金币原因
    sess = _fresh_session(tmp_path, seed=999)
    sess.act(_pick_hero(sess))
    st = sess.state()
    up = next(b for b in st["buttons"] if b["key"] == "upgrade")
    assert up["price"] == st["hud"]["upgrade_price"]
    assert "当前 T" in up["hint"]
    if not up["enabled"]:
        assert "金币不足" in up["reason"]
    ref = next(b for b in st["buttons"] if b["key"] == "refresh")
    assert ref["label"] == "刷新酒馆" and ref["price"] == st["hud"]["refresh_price"]


# ── 6. 对手栏 + 自己上轮战果 ──────────────────────────────────────────────


def test_opponents_and_my_combat(mid_session):
    st = mid_session.state()
    opps = st["opponents"]
    assert len(opps) == 7
    for o in opps:
        assert "board" not in o, "不得泄露对手实时棋盘"
        for key in ("hero", "health", "armor", "tier", "seen_board", "seen_turn",
                    "seen_label", "last_warband", "trinkets", "is_next"):
            assert key in o
        assert isinstance(o["seen_board"], list)
        if o["seen_turn"]:
            assert "交战时所见" in o["seen_label"]
        else:
            assert "未知" in o["seen_label"]
    mc = st["my_combat"]
    assert mc["mine"] is True
    assert mc["result"] in ("win", "loss", "tie") and mc["result_label"] in ("胜", "负", "平")
    assert isinstance(mc["damage"], int) and mc["summary"].startswith("第")
    assert st["seat"] in (mc["a"], mc["b"])
    assert mc["opponent"] is not None and mc["opponent_label"]
    # 最近战斗列表带 seat 视角标记，与 my_combat 一致
    mine = [c for c in st["combats"] if c["mine"]]
    assert mine and mine[-1]["result"] == mc["result"]


# ── 7. /snapshot 中局状态文本 ─────────────────────────────────────────────


def test_snapshot_text_has_races_keywords_trinkets(mid_session):
    st = mid_session.state()
    text = A.state_text(st)
    assert "本局种族：" in text and "无" != text.split("本局种族：")[1].splitlines()[0]
    assert "饰品（已获得" in text and "黑暗之赐：" in text
    assert "[卡面]" in text and "关键词：" in text
    assert "上轮战果：" in text and "对手：" in text
    html = A.render_html(st)
    assert '<pre id="statetext">' in html
    assert "<!--SNAPSHOT_TEXT-->" not in html
    assert "本局种族：" in html


# ── 8. 非法动作原因 + HTTP 400 ────────────────────────────────────────────


def test_illegal_action_reasons_and_http(tmp_path):
    sess = _fresh_session(tmp_path, seed=321)
    st = sess.state()
    with pytest.raises(A.IllegalAction) as exc:
        sess.act(A.N_ACTIONS)
    assert "越界" in str(exc.value)
    with pytest.raises(A.IllegalAction) as exc:
        sess.act(A.A_END)  # hero_select 阶段只允许 Choose
    assert "非法" in str(exc.value) and "选英雄" in str(exc.value)
    assert st["phase"] == "hero_select"

    srv = A.ArenaServer(("127.0.0.1", 0), sess)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"

    def get(path):
        with urllib.request.urlopen(base + path, timeout=30) as resp:
            return resp.status, resp.read()

    try:
        code, raw = get("/snapshot.txt")
        assert code == 200
        assert "种族" in raw.decode("utf-8") and "黑暗之赐" in raw.decode("utf-8")
        code, raw = get("/snapshot")
        assert code == 200 and b'<pre id="statetext">' in raw
        req = urllib.request.Request(
            base + "/act", data=json.dumps({"action": 0}).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                code = resp.status
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            code = exc.code
            payload = json.loads(exc.read())
        assert code == 400 and payload["action"] == 0
        assert "非法" in payload["error"] and "选英雄" in payload["error"]
    finally:
        srv.shutdown()
        srv.server_close()
        th.join(timeout=5)
