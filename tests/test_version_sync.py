"""`tools/version_sync.py` 单元测试 —— 四信号解析/决策/预演与网络注入。

约束：**不联网**。所有网络调用都通过注入的 fake 函数或 `--offline` 覆盖；
`.product.db` 用临时样本字节构造；所有写操作只落在 pytest `tmp_path`。
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "version_sync.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("version_sync", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VS = load_tool()


# ── 工具函数 ──────────────────────────────────────────────────────────

def make_root(tmp: Path, patch: str = "37.0.0.255130",
              local_tags=("255130",)) -> Path:
    """最小仓库骨架: data/bg_summary.json + reversed/hsdata_<tag>/source.json。"""
    (tmp / "data").mkdir(parents=True, exist_ok=True)
    (tmp / "data" / "bg_summary.json").write_text(
        json.dumps({"patch": patch, "pool_minions": {"count": 0}}),
        encoding="utf-8")
    for tag in local_tags:
        hdir = tmp / "reversed" / f"hsdata_{tag}"
        hdir.mkdir(parents=True, exist_ok=True)
        (hdir / "source.json").write_text(
            json.dumps({"tag": str(tag)}), encoding="utf-8")
        (hdir / "CardDefs.xml").write_text("<CardDefs/>", encoding="utf-8")
    return tmp


def make_product_db(tmp: Path, version: str = "37.0.0.255130.254477") -> Path:
    path = tmp / ".product.db"
    path.write_bytes(b"\x00\x01protobuf-junk " + version.encode() + b"\x00tail")
    return path


def fake_zip(manifest: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("AgenticAssistant/release-manifest.json",
                    json.dumps(manifest))
        zf.writestr("AgenticAssistant/other.txt", "x" * 100)
    return buf.getvalue()


def make_args(tmp: Path, **overrides) -> argparse.Namespace:
    base = dict(
        root=str(tmp), offline=True, product_db=None, build=None,
        project_patch=None, target_tag=None, json=False, yes=False,
        no_tests=True, no_smoke=True,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


# ── 1. 版本解析/比较 ──────────────────────────────────────────────────

def test_parse_and_compare_versions():
    assert VS.parse_version("37.0.0.255130.254477") == (37, 0, 0, 255130,
                                                        254477)
    assert VS.parse_version(None) == ()
    assert VS.build_number("37.0.0.255130") == 255130
    assert VS.compare_versions("37.0.0.255130", "37.0.0.255130.254477") == -1
    assert VS.compare_versions("37.0.0.255130", "37.0.0.255130") == 0
    assert VS.compare_versions("37.0.0.255130", "36.2.2.249896") == 1


# ── 2. `.product.db` 解析 ────────────────────────────────────────────

def test_read_client_build_from_sample(tmp_path):
    path = make_product_db(tmp_path)
    info = VS.read_client_build(path)
    assert info is not None
    assert info["version"] == "37.0.0.255130"
    assert info["build"] == 255130
    assert info["revision"] == 254477
    assert info["raw"] == "37.0.0.255130.254477"


def test_read_client_build_missing_file(tmp_path):
    assert VS.read_client_build(tmp_path / "nope.db") is None


# ── 3. 决策逻辑（纯函数） ────────────────────────────────────────────

def _signals(client=255130, project=255130, tags=("255130",),
             rizling=None):
    return {
        "client": {"build": client},
        "project": {"build": project, "patch": f"0.0.0.{project}"},
        "hsdata": {"tags": list(tags)},
        "hsdata_local_tags": list(tags),
        "rizling": {"build": rizling},
    }


def test_decide_up_to_date():
    d = VS.decide(_signals())
    assert d["status"] == "up-to-date"
    assert d["target_tag"] == "255130"


def test_decide_update_available():
    d = VS.decide(_signals(project=249896, tags=("255130", "255026")))
    assert d["status"] == "update-available"
    assert d["target_tag"] == "255130"


def test_decide_waiting_for_hsdata_when_client_ahead():
    d = VS.decide(_signals(client=260000, project=255130))
    assert d["status"] == "waiting-for-hsdata"
    assert any("等待 HearthSim" in w for w in d["warnings"])


def test_decide_client_ahead_but_tag_exists_is_update():
    d = VS.decide(_signals(client=255130, project=249896,
                           tags=("255130",)))
    assert d["status"] == "update-available"


def test_decide_unknown_without_signals():
    d = VS.decide({"client": None, "project": None, "hsdata": {"tags": []},
                   "hsdata_local_tags": [], "rizling": {}})
    assert d["status"] == "unknown"
    assert d["errors"]


def test_decide_rizling_lag_is_only_warning():
    d = VS.decide(_signals(rizling=253932))
    assert d["status"] == "up-to-date"
    assert any("rizling" in w for w in d["warnings"])


# ── 4. hsdata tag 抓取（注入网络） ───────────────────────────────────

def test_fetch_hsdata_tags_injected_http(tmp_path):
    def fake_http(url, timeout=20, headers=None):
        assert "HearthSim/hsdata" in url
        return [{"name": "255026"}, {"name": "255130"},
                {"name": "not-a-tag"}]

    got = VS.fetch_hsdata_tags(http_json=fake_http,
                               cache_dir=tmp_path / "cache")
    assert got["tags"] == ["255130", "255026"]
    assert got["source"] == "github"
    cache = tmp_path / "cache" / "hsdata_tags.json"
    assert cache.is_file()


def test_fetch_hsdata_tags_offline_uses_cache(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "hsdata_tags.json").write_text(
        json.dumps({"tags": ["255130"], "fetched_at": "x"}), encoding="utf-8")

    def boom(*a, **k):
        raise AssertionError("offline 不应联网")

    got = VS.fetch_hsdata_tags(offline=True, http_json=boom, cache_dir=cache)
    assert got["tags"] == ["255130"]
    assert got["source"] == "cache"


def test_fetch_hsdata_tags_network_error_falls_back(tmp_path):
    def boom(*a, **k):
        raise OSError("network down")

    got = VS.fetch_hsdata_tags(http_json=boom, cache_dir=tmp_path / "cache")
    assert got["error"] and "network down" in got["error"]


# ── 5. rizling 远程 ZIP（注入 Range） ─────────────────────────────────

def test_remote_zip_manifest_via_injected_ranges():
    data = fake_zip({"version": "0.7.0",
                     "game_version": "37.0.0.255130.254477"})
    calls = []

    def range_get(url, start, end):
        calls.append((start, end))
        return data[start:end + 1]

    got = VS.remote_zip_manifest(size_get=lambda: len(data),
                                 range_get=range_get)
    assert got["manifest"]["version"] == "0.7.0"
    assert got["manifest"]["game_version"] == "37.0.0.255130.254477"
    # 小样本 ZIP 的 Range 会重叠（尾部窗口覆盖全文件），只验证"未整包下载"
    # 的语义：读取量级仍是 KB 级，而不是 54MB。
    assert got["bytes_downloaded"] < 1_000_000
    assert calls


def test_remote_zip_manifest_missing_manifest_raises():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("only.txt", "x")
    data = buf.getvalue()
    with pytest.raises(ValueError):
        VS.remote_zip_manifest(size_get=lambda: len(data),
                               range_get=lambda u, s, e: data[s:e + 1])


# ── 6. collect_signals 注入组合 ──────────────────────────────────────

def test_collect_signals_with_injected_network(tmp_path):
    root = make_root(tmp_path)
    product = make_product_db(tmp_path)
    data = fake_zip({"version": "0.6.1",
                     "game_version": "36.6.3.253932"})

    def fake_http(url, timeout=20, headers=None):
        return [{"name": "255130"}]

    def range_get(url, start, end):
        return data[start:end + 1]

    got = VS.collect_signals(root, product_db=product,
                             http_json=fake_http,
                             range_get=range_get,
                             size_get=lambda: len(data),
                             cache_dir=tmp_path / "cache")
    assert got["client"]["build"] == 255130
    assert got["project"]["build"] == 255130
    assert got["hsdata"]["tags"] == ["255130"]
    assert got["rizling"]["version"] == "0.6.1"
    assert got["rizling"]["game_version"] == "36.6.3.253932"
    decision = VS.decide(got)
    assert decision["status"] == "up-to-date"


# ── 7. CLI --check / --apply 安全护栏（离线，不联网） ─────────────────

def test_cli_check_offline_writes_report(tmp_path):
    root = make_root(tmp_path)
    rc = VS.main(["--check", "--offline", "--root", str(root)])
    assert rc == 0
    reports = list((root / "runs" / "version_sync").glob("*.json"))
    assert len(reports) == 1
    payload = json.loads(reports[0].read_text(encoding="utf-8"))
    assert payload["decision"]["status"] == "up-to-date"
    assert payload["signals"]["project"]["build"] == 255130


def test_cli_apply_without_yes_refuses(tmp_path, capsys):
    root = make_root(tmp_path)
    rc = VS.main(["--apply", "--offline", "--root", str(root)])
    assert rc == 2       # 拒绝（不写 data/）
    # 不写 data/（bg_summary 未变）
    patch = json.loads((root / "data" / "bg_summary.json").read_text(
        encoding="utf-8"))["patch"]
    assert patch == "37.0.0.255130"
    out = capsys.readouterr().out
    assert "--yes" in out or "拒绝" in out


def test_cli_apply_up_to_date_is_noop(tmp_path):
    root = make_root(tmp_path)
    before = {p.name: p.read_bytes()
              for p in (root / "data").glob("*.json")}
    rc = VS.main(["--apply", "--yes", "--offline", "--root", str(root)])
    assert rc == 0
    after = {p.name: p.read_bytes()
             for p in (root / "data").glob("*.json")}
    assert before == after
    assert not (root / "data" / "backup_255130").exists()


# ── 8. dry-run 决策 → prepare 接线（monkeypatch 重活） ───────────────

def test_dry_run_update_available_calls_prepare(tmp_path, monkeypatch):
    calls = {}

    def fake_prepare(tag, *, root=VS.ROOT, offline=False):
        calls["tag"] = tag
        calls["root"] = str(root)
        return {"ok": True, "tag": tag,
                "generated_dir": str(Path(root) / "tmp_version_sync" /
                                     f"data_{tag}"),
                "report": str(Path(root) / "runs" / "version_sync" /
                              f"dryrun_{tag}.json"),
                "steps": [{"step": "fetch_hsdata", "ok": True},
                          {"step": "diff", "ok": True, "bg_added": 1,
                           "bg_removed": 0, "value_change_total": 2,
                           "new_tag_enum_ids": 0, "new_race_values": [],
                           "unknown_race_values": []}]}

    monkeypatch.setattr(VS, "prepare_update", fake_prepare)
    signals = {
        "generated_at": "2026-10-18T00:00:00+00:00",
        "client": {"build": 255130, "raw": "37.0.0.255130.254477"},
        "project": {"build": 249896, "patch": "36.2.2.249896"},
        "hsdata": {"tags": ["255130"]},
        "hsdata_local_tags": ["255130"],
        "rizling": {"build": None},
    }
    args = make_args(tmp_path, dry_run=True)
    rc = VS.cmd_dry_run(args, signals=signals)
    assert rc == 0
    assert calls["tag"] == "255130"


def test_dry_run_up_to_date_is_noop(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("up-to-date 不应触发 prepare")

    monkeypatch.setattr(VS, "prepare_update", boom)
    signals = {
        "generated_at": "x", "client": {"build": 255130},
        "project": {"build": 255130, "patch": "37.0.0.255130"},
        "hsdata": {"tags": ["255130"]}, "hsdata_local_tags": ["255130"],
        "rizling": {"build": None},
    }
    rc = VS.cmd_dry_run(make_args(tmp_path, dry_run=True),
                        signals=signals)
    assert rc == 0


# ── 9. 合并 / 回滚辅助 ───────────────────────────────────────────────

def test_merge_carddefs(tmp_path):
    a = tmp_path / "a.xml"
    b = tmp_path / "b.xml"
    a.write_text('<?xml version="1.0" encoding="utf-8"?>\n'
                 '<CardDefs build="1">\n<Entity CardID="A" ID="1"/>\n'
                 '</CardDefs>\n', encoding="utf-8")
    b.write_text('<?xml version="1.0" encoding="utf-8"?>\n'
                 '<CardDefs build="1">\n<Entity CardID="B" ID="2"/>\n'
                 '</CardDefs>\n', encoding="utf-8")
    dest = VS.merge_carddefs([a, b], tmp_path / "merged.xml", build="37.0.0.1")
    text = dest.read_text(encoding="utf-8")
    assert 'build="37.0.0.1"' in text
    assert "CardID=\"A\"" in text and "CardID=\"B\"" in text
    assert text.count("<CardDefs") == 1
    assert text.count("</CardDefs>") == 1


def test_restore_backup_and_remove_created(tmp_path):
    keep = tmp_path / "keep.json"
    keep.write_text("new", encoding="utf-8")
    backup = tmp_path / "backup.json"
    backup.write_text("old", encoding="utf-8")
    created = tmp_path / "created.md"
    created.write_text("x", encoding="utf-8")
    restored = VS._restore([(backup, keep)], [created])
    assert keep.read_text(encoding="utf-8") == "old"
    assert not created.exists()
    assert str(keep) in restored
