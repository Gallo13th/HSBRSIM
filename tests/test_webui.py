"""Web 控制台只读接口的轻量测试（不启动 HTTP server）。"""

from __future__ import annotations

from hsbg.webui import server


def test_status_has_engine_and_backends():
    st = server.status()
    assert st["ok"] is True
    assert "engine" in st
    assert "backends" in st
    assert isinstance(st["backends"], list)


def test_runs_payload_is_jsonable():
    data = server.runs_payload(limit=5)
    assert data["ok"] is True
    assert isinstance(data["rows"], list)
    for row in data["rows"]:
        assert {"path", "mtime", "size", "summary"} <= set(row)


def test_tavernbench_snapshot_loads():
    data = server.tavernbench_payload()
    assert data["ok"] is True
    assert "tavernagent" in data["systems"]
    assert "play" in data["systems"]["tavernagent"]
