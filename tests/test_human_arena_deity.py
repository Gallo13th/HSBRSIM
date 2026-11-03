"""``scripts/human_arena.py`` 神明（Deity）面板测试。

覆盖：
1. 有神明：名字/atk/hp/效果全文/种族/星级/卡图齐全；
2. 无神明：“本局无神明”提示出现在 ``hud.deity``、``/snapshot.txt`` 文本与快照 HTML；
3. 触发要求结构化：阶段（招募/战斗/回合结束）+ 条件 + 效果 + 来源（卡面/脚本/推断）；
4. 两个神明的脚本行为：克苏恩均分属性、亚煞极亡语复活数量；
5. 快照一致：``render_html`` 的 ``<pre id="statetext">`` == ``state_text``，
   且 ``/snapshot`` 与 ``/snapshot.txt`` 同源；
6. 金卡/复生标识与来源标注。

只读 ``scripts/human_arena.py`` + 引擎 view + 静态卡表；不训练、不占 GPU。
"""

from __future__ import annotations

import html as html_mod
import importlib.util
import json
import os
import re
import sys
import threading
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("hsbg_engine", reason="hsbg_engine 未安装（cd rust && pip install -e .）")

SPEC = importlib.util.spec_from_file_location(
    "human_arena_deity", os.path.join(ROOT, "scripts", "human_arena.py"))
ha = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ha)
A = ha

#: 强制大厅含畸变怪（引擎要求 lobby_types 里不能再写 ABERRATION）。
ABERRATION_CONFIG = {"aberration_forced": True}
SOURCE_LABELS = {"卡面", "脚本", "推断"}
SNAPSHOT_RE = re.compile(r'<pre id="statetext">(.*?)</pre>', re.S)


# ── helpers ──────────────────────────────────────────────────────────────


def _session(tmp_path, seed, config_json=None):
    return A.GameSession(seed=int(seed), seat=0,
                         out_dir=str(tmp_path / ("play_%s" % seed)),
                         config_json=config_json)


def _session_with_deity(tmp_path, want=None, seeds=range(1, 13)):
    """在强制畸变怪大厅里找一个有神明（可指定 id）的对局。"""
    for seed in seeds:
        sess = _session(tmp_path, seed, ABERRATION_CONFIG)
        d = sess.state()["hud"]["deity"]
        if d.get("present") and (want is None or d.get("card_id") == want):
            return sess, d
    pytest.fail("强制畸变怪大厅仍未找到神明（want=%r）" % (want,))


def _session_without_deity(tmp_path):
    for seed in range(1, 13):
        sess = _session(tmp_path, seed)
        if not sess.state()["hud"]["deity"].get("present"):
            return sess
    pytest.fail("默认配置下 1..12 seed 全都有神明，无法测试无神明提示")


def _pre_text(html: str) -> str:
    m = SNAPSHOT_RE.search(html)
    assert m, "快照 HTML 缺少 <pre id=\"statetext\">"
    return html_mod.unescape(m.group(1))


def _http_get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=30) as resp:
        return resp.status, resp.read()


# ── 1. 有神明：名字 / atk/hp / 效果 ──────────────────────────────────────


def test_deity_present_name_stats_effect(tmp_path):
    sess, d0 = _session_with_deity(tmp_path)
    st = sess.state()
    d = st["hud"]["deity"]
    assert d["card_id"] == d0["card_id"]
    for key in ("name", "name_zh", "atk", "hp", "card_id", "art", "text", "text_note",
                "golden", "reborn", "tier", "tier_label", "races", "race_text",
                "triggers", "numbers", "present", "hint"):
        assert key in d, key
    assert d["present"] is True
    assert d["card_id"].startswith("BGFYM_")
    assert d["name_zh"] and d["name"]
    assert isinstance(d["atk"], int) and isinstance(d["hp"], int)
    assert d["atk"] >= 1 and d["hp"] >= 1
    assert "神明" in d["text"] and d["text_note"] in ("卡面", "金卡卡面", "脚本")
    assert "畸变怪" in d["race_text"]
    assert d["art"].endswith("%s.png" % d["card_id"])
    # 状态可 JSON 序列化（/state 白名单）
    payload = json.loads(json.dumps(st, ensure_ascii=False))
    assert payload["hud"]["deity"]["name_zh"] == d["name_zh"]


# ── 2. 无神明：提示 ──────────────────────────────────────────────────────


def test_no_deity_placeholder(tmp_path):
    sess = _session_without_deity(tmp_path)
    st = sess.state()
    d = st["hud"]["deity"]
    assert d["present"] is False and d["label"] == "本局无神明"
    assert "畸变怪" in d["hint"]
    text = A.state_text(st)
    assert "本局无神明" in text
    assert "神明（deity，不等于赐福）：本局无神明" in text
    html = A.render_html(st)
    assert "本局无神明" in html
    # HTML 里有独立面板容器与渲染函数（/snapshot 与实时页共用）
    assert 'id="deity"' in A.INDEX_HTML and "function renderDeity" in A.INDEX_HTML


# ── 3. 触发要求结构化 ────────────────────────────────────────────────────


def test_trigger_requirements_structured(tmp_path):
    _, d = _session_with_deity(tmp_path)
    triggers = d["triggers"]
    assert triggers, "神明必须有至少 1 条结构化触发要求"
    phases = set()
    for t in triggers:
        for key in ("phase", "phase_label", "condition", "condition_source",
                    "effect", "effect_source", "source", "source_ref"):
            assert key in t, key
        assert t["phase"] in A.DEITY_PHASE_ZH
        assert t["phase_label"] == A.DEITY_PHASE_ZH[t["phase"]]
        assert t["condition"].strip() and t["effect"].strip()
        assert t["source"] in SOURCE_LABELS, "来源只能是 卡面/脚本/推断"
        assert t["condition_source"] in SOURCE_LABELS
        assert t["effect_source"] in SOURCE_LABELS
        phases.add(t["phase"])
    # 唤醒/亡语在战斗阶段；属性成长在招募阶段
    assert "combat" in phases and "recruit" in phases
    # 唤醒门槛来自引擎默认配置，不是写死在 UI 里
    cfg = json.loads(A.load_engine().default_config_json())
    assert d["threshold"] == int(cfg["deity_threshold"])
    cond = next(t for t in triggers if t["phase"] == "combat")
    assert str(d["threshold"]) in cond["condition"]
    assert cond["source"] == "脚本"
    # 数值字段也齐全
    assert d["numbers"]
    for n in d["numbers"]:
        assert {"key", "label", "value", "source"} <= set(n)


# ── 4. 两个神明的脚本行为 ────────────────────────────────────────────────


def test_two_deities_scripted_effects(tmp_path):
    _, cthun = _session_with_deity(tmp_path, want="BGFYM_000")
    _, yshaarj = _session_with_deity(tmp_path, want="BGFYM_011")

    ctext = " ".join(t["effect"] for t in cthun["triggers"])
    assert "均分" in ctext and "其他随从" in ctext
    cnums = {n["key"]: n["value"] for n in cthun["numbers"]}
    assert cnums["threshold"] == "4" and cnums["golden_mult"] == "×2"

    ytext = " ".join(t["effect"] for t in yshaarj["triggers"])
    assert "前 2 个畸变怪" in ytext and "最大属性值" in ytext
    ynums = {n["key"]: n["value"] for n in yshaarj["numbers"]}
    assert "2 只（金卡 4 只）" == ynums["revive"]
    assert "金卡均分倍率" not in ynums, "亚煞极没有均分倍率数值"


# ── 5. 快照：state_text == <pre>，/snapshot 与 /snapshot.txt 同源 ────────


def test_snapshot_matches_html_and_http(tmp_path):
    sess, d = _session_with_deity(tmp_path)
    st = sess.state()
    text = A.state_text(st)
    html = A.render_html(st)
    assert _pre_text(html) == text
    assert "<!--SNAPSHOT_TEXT-->" not in html
    # 注入的 state JSON 与文本都带神明
    assert d["name_zh"] in html and d["name_zh"] in text
    assert '"present": true' in html
    assert "触发要求（阶段｜条件｜效果｜来源）" in text

    srv = A.ArenaServer(("127.0.0.1", 0), sess)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = "http://127.0.0.1:%d" % port
    try:
        code, raw = _http_get(base, "/snapshot.txt")
        assert code == 200
        txt = raw.decode("utf-8")
        assert txt == text + "\n"
        assert d["name_zh"] in txt and "本局无神明" not in txt
        code, raw = _http_get(base, "/snapshot")
        assert code == 200
        snap = raw.decode("utf-8")
        assert _pre_text(snap) == text
        assert d["name_zh"] in snap
    finally:
        srv.shutdown()
        srv.server_close()


# ── 6. 金卡 / 复生标识 + 来源标注 ────────────────────────────────────────


def test_golden_reborn_badges_and_sources():
    raw = {
        "card": {"id": "BGFYM_000", "name": "C'Thun", "name_zh": "克苏恩",
                 "kind": "minion", "races": ["ABERRATION"], "tier": 1},
        "atk": 5, "hp": 7, "golden": True, "reborn": True,
    }
    d = A.deity_brief(raw)
    assert d["present"] is True
    assert d["golden"] is True and d["golden_label"] == "金色"
    assert d["reborn"] is True and d["reborn_label"] == "复生"
    assert (d["atk"], d["hp"]) == (5, 7)
    # 金卡用 _G 卡面文本（双倍属性值）
    assert "双倍" in d["text"]
    names = {n["key"] for n in d["numbers"]}
    assert {"atk_hp", "base", "threshold", "golden_mult", "buff_cards"} <= names
    trigger = next(t for t in d["triggers"] if t["phase"] == "combat")
    assert trigger["source"] == "脚本"
    assert "deity_awakened" in trigger["source_ref"]
    # 无神明（None / 空）也返回可渲染结构
    for empty in (None, {}, {"card": None}):
        e = A.deity_brief(empty)
        assert e["present"] is False and e["label"] == "本局无神明"
        assert e["triggers"] == [] and e["atk"] is None
