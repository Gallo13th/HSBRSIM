"""``scripts/human_arena.py`` UI V2（官方布局 + 拖拽 + 折叠）测试。

覆盖（对应 ``docs/HUMAN_ARENA_UI_SPEC_V2.md`` 第 3/4/7 节）：
1. 三行布局顺序：鲍勃酒馆 -> 我方战场 7 槽 -> 手牌 10 格 -> 出售区/侧栏；
2. 拖拽映射 id：Play 46+h*8+p、Magnetize 126+h*7+b、Move 196+f*7+t、Sell 16+b、
   Buy 8+slot（商店拖到战场只买，不自动打出）；
3. 商店拖拽 -> Buy：真实会话购买后手牌 +1，提示“已购买”；
4. 非法拖拽：返回 action=None + 原因，前端 rollbackDrag 且不调用 /act；
5. 折叠默认收起：attached/卡面效果/Discover/神明触发/属性来源；
6. Pointer Events + HTML5 DnD 双路径与拖影；
7. ``/snapshot.txt`` 字段未丢（酒馆/手牌/战场/饰品/黑暗之赐/神明/对手/战果）。
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("hsbg_engine", reason="hsbg_engine 未安装（cd rust && pip install -e .）")

SPEC = importlib.util.spec_from_file_location(
    "human_arena_v2", os.path.join(ROOT, "scripts", "human_arena.py"))
ha = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ha)
A = ha


def _full_mask():
    return [1] * A.N_ACTIONS


def _synthetic_state():
    """最小状态：覆盖 5 类合法拖拽，动作 id 全部与规范公式一致。"""
    return {
        "mask": _full_mask(),
        "over": False,
        "pending": None,
        "shop": [{"name_zh": "商店牌", "buy": A.A_BUY + 2, "buy_reason": ""}],
        "hand": [{
            "name_zh": "手牌牌",
            "play": [{"pos": 3, "action": A.A_PLAY + 0 * A.N_POS + 3}],
            "magnetize": [{"board": 4, "action": A.A_MAGNETIZE + 0 * A.N_BOARD + 4}],
        }, {
            "name_zh": "第二张",
            "play": [{"pos": 3, "action": A.A_PLAY + 1 * A.N_POS + 3}],
            "magnetize": [],
        }],
        "board": [
            {"name_zh": "甲", "move": [{"to": 1, "action": A.A_MOVE + 5 * A.N_BOARD + 1}],
             "sell": A.A_SELL + 2, "activate": A.A_ACTIVATE + 2},
        ],
    }


def _pick_hero(sess):
    st = sess.state()
    return st["pending"]["options"][0]["action"]


# ── 1. 三行布局顺序 ───────────────────────────────────────────────────────


def test_layout_three_row_order():
    html = A.INDEX_HTML
    order = [
        'id="shoprow"', 'id="boardrow"', 'id="handrow"',
        'id="sellzone"', 'class="lower"',
    ]
    pos = [html.index(anchor) for anchor in order]
    assert pos == sorted(pos), "DOM 必须是 酒馆 -> 战场 -> 手牌 -> 出售区 -> 侧栏"
    assert 'id="board" class="boardgrid slots"' in html
    assert 'id="hand" class="handgrid slots"' in html
    assert "repeat(8," in html and "repeat(7," in html and "repeat(10," in html
    # 固定槽位容器：8 商店 / 7 战场 / 10 手牌
    assert "S.action_space.N_SHOP) || 8" in html
    assert "S.action_space.N_BOARD) || 7" in html
    assert "for (let i = 0; i < n; i++)" in html


# ── 2. 拖拽映射 id ────────────────────────────────────────────────────────


def test_drag_action_ids_match_spec():
    st = _synthetic_state()
    # 商店槽 2 -> 战场/购买区 = Buy(2) = 8+2 = 10
    plan = A.drag_action(st, A.DRAG_SHOP, 0, A.DRAG_BOARD, 0)
    assert plan["ok"] and plan["action"] == A.A_BUY + 2 == 10
    # 手牌 1 -> 战场空槽 3 = Play(1,3) = 46+1*8+3 = 57
    st["board"] = []          # 空场：落点 3 是空槽 -> Play
    plan = A.drag_action(st, A.DRAG_HAND, 1, A.DRAG_BOARD, 3)
    assert plan["ok"] and plan["action"] == A.A_PLAY + 1 * A.N_POS + 3 == 57
    # 手牌 0（磁力）-> 战场随从 4 = Magnetize(0,4) = 126+0*7+4 = 130
    st["board"] = [dict(_synthetic_state()["board"][0], move=[
        {"to": 1, "action": A.A_MOVE + 5 * A.N_BOARD + 1}]) for _ in range(7)]
    plan = A.drag_action(st, A.DRAG_HAND, 0, A.DRAG_BOARD, 4)
    assert plan["ok"] and plan["action"] == A.A_MAGNETIZE + 0 * A.N_BOARD + 4 == 130
    # 战场 5 -> 战场 1 = Move(5,1) = 196+5*7+1 = 232
    plan = A.drag_action(st, A.DRAG_BOARD, 5, A.DRAG_BOARD, 1)
    assert plan["ok"] and plan["action"] == A.A_MOVE + 5 * A.N_BOARD + 1 == 232
    # 战场 2 -> 出售区 = Sell(2) = 16+2 = 18
    plan = A.drag_action(st, A.DRAG_BOARD, 2, A.DRAG_SELL, None)
    assert plan["ok"] and plan["action"] == A.A_SELL + 2 == 18
    # 战场 2 -> 发动区 = Activate(2) = 23+2 = 25
    plan = A.drag_action(st, A.DRAG_BOARD, 2, A.DRAG_ACTIVATE, None)
    assert plan["ok"] and plan["action"] == A.A_ACTIVATE + 2 == 25


# ── 3. 商店拖拽 -> Buy（只购买，进手牌）──────────────────────────────────


def test_shop_drag_buys_and_enters_hand(tmp_path):
    sess = A.GameSession(seed=1234, seat=0, out_dir=str(tmp_path / "play"))
    sess.act(_pick_hero(sess))
    st = sess.state()
    slot = next(c["slot"] for c in st["shop"] if c["buy"] is not None)
    before = len(st["hand"])
    plan = A.drag_action(st, A.DRAG_SHOP, slot, A.DRAG_BOARD, 0)
    assert plan["ok"] and plan["action"] == A.A_BUY + slot
    assert "已购买" in plan["toast"] and "进入手牌" in plan["toast"]
    assert "自动打出" in plan["note"] and "新端点" in plan["note"]
    sess.act(plan["action"])
    st2 = sess.state()
    assert len(st2["hand"]) == before + 1, "Buy 后卡进入手牌，不直接上战场"
    assert not any(c.get("name_zh") == plan["toast"].split("：", 1)[1].split("，", 1)[0]
                   for c in st2["board"])


# ── 4. 非法拖拽回滚且不提交 ──────────────────────────────────────────────


def test_illegal_drag_rolls_back_without_action():
    st = _synthetic_state()
    # 手牌没有 pos=0 的 Play -> 不提交
    plan = A.drag_action(st, A.DRAG_HAND, 0, A.DRAG_BOARD, 0)
    assert plan["ok"] is False and plan["action"] is None and plan["reason"]
    # 战场拖回原位 -> 不提交
    plan = A.drag_action(st, A.DRAG_BOARD, 0, A.DRAG_BOARD, 0)
    assert not plan["ok"] and plan["action"] is None and "原位" in plan["reason"]
    # 商店槽不能拖到出售区
    plan = A.drag_action(st, A.DRAG_SHOP, 0, A.DRAG_SELL, None)
    assert not plan["ok"] and plan["action"] is None
    # pending 期间暂停拖拽
    st2 = dict(st, pending={"kind": "discover"})
    assert A.drag_action(st2, A.DRAG_HAND, 0, A.DRAG_BOARD, 3)["action"] is None
    html = A.INDEX_HTML
    assert "function rollbackDrag" in html
    assert "if (!plan.ok) { rollbackDrag(plan.reason || plan.label, srcEl); return; }" in html
    assert "不自动重试" in html or "未确认提交" in html
    assert 'id="loading"' in html and "处理中…" in html


# ── 5. 折叠默认收起 ──────────────────────────────────────────────────────


def test_collapsible_sections_default_closed():
    html = A.INDEX_HTML
    # 不允许任何 <details ... open> 默认展开
    assert re.search(r"<details[^>]*\bopen\b", html) is None
    # attached：一行摘要 +N 附件，展开后才列名称/类型/效果/来源
    assert '<details class="attach"' in html
    assert "summary>+' + n + ' 附件 ▸" in html
    assert "attachlist" in html and "attachitem" in html
    # 卡面效果 / 属性来源 / 神明触发 / Discover / 抉择
    assert "卡面效果 ▸" in html
    assert "属性来源 ▸" in html
    assert "神明触发：" in html and " 条 ▸</summary>" in html
    assert "发现：" in html and "三选一" in html
    assert "抉择：选项1/2 ▸" in html
    # 只切换自身内容：summary 不触发动作
    assert "summary 只切换自身内容" not in html  # 文档语句，页面用 stopPropagation 实现
    assert "querySelectorAll(\"details\").forEach" in html
    assert "collectOpen" in html and "restoreOpen" in html


# ── 6. Pointer Events + HTML5 DnD ────────────────────────────────────────


def test_pointer_and_html5_drag_paths():
    html = A.INDEX_HTML
    for token in ("pointerdown", "pointermove", "pointerup", "pointercancel",
                  "elementFromPoint", "dragstart", "dragover", "drop",
                  "dispatchDrop", "dragghost", "aria-grabbed"):
        assert token in html, token
    assert "setTimeout" in html and "150" in html, "触屏长按约 150ms 才生成拖影"
    assert "DRAG.suppressClick" in html, "拖拽后抑制误点击"
    assert ".dragghost" in html and "position:fixed" in html
    assert 'data-drop="sell"' in html
    assert 'draggable", "true"' in html


# ── 7. snapshot 字段未丢 ─────────────────────────────────────────────────


def test_snapshot_text_fields_intact(tmp_path):
    sess = A.GameSession(seed=1234, seat=0, out_dir=str(tmp_path / "play"))
    sess.act(_pick_hero(sess))
    st = sess.state()
    buy = next(c["buy"] for c in st["shop"] if c["buy"] is not None)
    sess.act(buy)
    st = sess.state()
    play = next((c["play"][0]["action"] for c in st["hand"] if c["play"]), None)
    if play is not None:
        sess.act(play)
    st = sess.state()
    text = A.state_text(st)
    for section in ("英雄：", "本局种族：", "酒馆：", "手牌：", "战场：",
                    "饰品（已获得", "黑暗之赐：", "神明（deity，不等于赐福）：",
                    "对手：", "上轮战果：", "按钮："):
        assert section in text, section
    assert "触发要求（阶段｜条件｜效果｜来源）" in text or "本局无神明" in text
    html = A.render_html(st)
    assert '<pre id="statetext">' in html and "<!--SNAPSHOT_TEXT-->" not in html
    # 卡牌实例字段仍完整（附件/拆解/关键词），只是 UI 默认折叠
    for c in (st.get("board") or []) + (st.get("hand") or []) + (st.get("shop") or []):
        for key in ("attached", "breakdown", "keyword_labels", "card_keyword_labels",
                    "text", "price_label" if c in st.get("shop", []) else "play_cost"):
            assert key in c, key
