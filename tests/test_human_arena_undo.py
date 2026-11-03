"""撤回及新版默认展示的回归测试。"""
import importlib.util
import pathlib
import json
import gzip
import pytest

pytest.importorskip("hsbg_engine")
SPEC = importlib.util.spec_from_file_location("arena_undo", pathlib.Path(__file__).resolve().parents[1] / "scripts/human_arena.py")
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)


def session(tmp_path):
    s = A.GameSession(1234, out_dir=str(tmp_path))
    st = s.state()
    s.act(st["pending"]["options"][0]["action"])
    return s


def test_undo_depth_and_exact_restore(tmp_path):
    s = session(tmp_path)
    original = s.game.state_json()
    # 首回合只有一次 Freeze；以真实序列化快照构造 12 层，单独验证栈容量与恢复。
    for i in range(12):
        s.undo_stack.append({"state_json": original, "decisions": s.decisions,
                             "steps": s.steps, "decision": s.decisions,
                             "action": A.A_FREEZE, "turn": s.game.turn,
                             "phase": "recruit", "last_my_combat": None})
    assert len(s.undo_stack) >= 12
    for _ in range(12):
        s.undo()
    assert s.game.state_json() == original


def test_undo_deterministic_reapply(tmp_path):
    s = session(tmp_path)
    before = s.state()
    first = s.act(A.A_FREEZE)
    s.undo()
    restored = s.state()
    for key in ("hud", "shop", "board", "hand", "mask", "turn", "phase"):
        assert restored[key] == before[key]
    again = s.act(A.A_FREEZE)
    for key in ("hud", "shop", "board", "hand", "mask"):
        assert first[key] == again[key]


def test_undo_disable_after_end_turn(tmp_path):
    s = session(tmp_path)
    s.act(A.A_END)
    assert not s.state()["undo"]["enabled"]
    assert "结算" in s.state()["undo"]["reason"]
    with pytest.raises(A.IllegalAction):
        s.undo()


def test_replay_decision_marked_undone(tmp_path):
    s = session(tmp_path)
    s.act(A.A_FREEZE)
    s.undo()
    rows = [json.loads(x) for x in gzip.decompress(s.replay_bytes()).decode().splitlines()]
    assert any(r.get("type") == "decision" and r.get("undone") is True for r in rows)


def test_sell_mapping():
    assert A.A_SELL == 16
    assert 'if (dk === "sell")' in A.INDEX_HTML
    assert 'const a = num(b.sell)' in A.INDEX_HTML


def test_card_effect_defaults_expanded():
    assert 'document.querySelectorAll("details.fx")' in A.INDEX_HTML
    assert 'd.open = true' in A.INDEX_HTML
    assert 'max-height:86px' not in A.INDEX_HTML


def test_attachments_and_power_defaults_collapsed():
    assert '<summary>+' in A.INDEX_HTML
    assert ' 附件 ▸</summary>' in A.INDEX_HTML
    assert 'd.className = "power-description"' in A.INDEX_HTML
    assert 'd.open = true' not in A.INDEX_HTML.split('d.className = "power-description"')[1].split('wrap.appendChild(d)')[0]
