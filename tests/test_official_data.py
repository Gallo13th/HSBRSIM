"""官方数据一致性测试（build 255130）。

不在测试里联网：只校验已经用
`python tools/rea_fetch_hsdata.py --tag 255130` 抓取/记录的本地产物。
产物缺失 → skip（CI 没有抓数据时不会红灯）。

运行:
    python -m pytest tests/test_official_data.py -q
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
HSDATA = ROOT / "reversed" / "hsdata_255130"
CARD_DEFS = HSDATA / "CardDefs.xml"
BACON_DEFS = HSDATA / "CardDefs.Bacon.xml"
SOURCE = HSDATA / "source.json"

#: 2026-10-18 首次抓取时记录（与 tools/rea_fetch_hsdata.py 的 KNOWN_HASHES 一致）
KNOWN = {
    "CardDefs.xml": {
        "size": 70509381,
        "sha256": "c7863b8fc7dd109d3e67230bf2efda319b175f8bd9ddfa955b5f4cb5cb267f0f",
        "entities": 23452,
    },
    "CardDefs.Bacon.xml": {
        "size": 15826018,
        "sha256": "c60d62b350f2d0361cd88b12e4941bfe6a9f24125c1af003858adb7728b3f413",
        "entities": 5787,
    },
}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_tool(name: str, rel: str):
    path = ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} 不存在")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def entities_and_build(path: Path) -> tuple[str, int]:
    root = None
    n = 0
    for event, elem in ET.iterparse(str(path), events=("start", "end")):
        if event == "start" and root is None:
            root = elem
            continue
        if event == "end" and elem.tag == "Entity" and elem.get("CardID"):
            n += 1
        if event == "end" and elem.tag == "Entity":
            elem.clear()
    build = root.get("build") if root is not None else None
    return build, n


pytestmark = pytest.mark.skipif(
    not CARD_DEFS.exists(),
    reason="缺少 reversed/hsdata_255130/CardDefs.xml（先跑 tools/rea_fetch_hsdata.py）")


def test_split_layout_files_exist():
    """255130 时代 CardDefs 拆分：构筑 + 酒馆战棋 + 种族表。"""
    for name in ("CardDefs.xml", "CardDefs.Bacon.xml", "RaceTagMap.xml",
                 "README.md", "source.json"):
        assert (HSDATA / name).exists(), f"缺少 {name}"
    assert BACON_DEFS.exists()


def test_hashes_and_sizes_match_recorded_source():
    """磁盘哈希必须等于 source.json 记录，且等于 KNOWN 常量（防上游重新打包）。"""
    src = json.loads(SOURCE.read_text(encoding="utf-8"))
    for name, known in KNOWN.items():
        path = HSDATA / name
        assert path.exists(), name
        assert path.stat().st_size == known["size"], f"{name} 大小变化"
        digest = sha256_of(path)
        assert digest == known["sha256"], f"{name} sha256 变化: {digest}"
        rec = src.get("files", {}).get(name)
        assert rec is not None, f"source.json 未记录 {name}"
        assert rec["sha256"] == digest, f"source.json 记录与磁盘 {name} 不一致"


def test_build_and_entity_counts():
    """build 属性 = 255130；实体数与首次抓取一致。"""
    for name, known in KNOWN.items():
        build, n = entities_and_build(HSDATA / name)
        assert build == "255130", f"{name} build={build}"
        assert n == known["entities"], f"{name} 实体数 {n} != {known['entities']}"


def test_fetch_tool_check_mode_is_offline_and_passes():
    """`rea_fetch_hsdata.py --check` 只做本地哈希校验，退出码 0。"""
    mod = load_tool("rea_fetch_hsdata", "tools/rea_fetch_hsdata.py")
    assert mod.main(["--tag", "255130", "--check"]) == 0


def test_data_diff_report():
    """数据差分报告存在且核心统计与产物一致。"""
    md = ROOT / "reversed" / "data_diff_255130_vs_249896.md"
    js = ROOT / "reversed" / "data_diff_255130_vs_249896.json"
    if not js.exists():
        pytest.skip("data diff 未生成（先跑 tools/rea_data_diff.py）")
    assert md.exists()
    d = json.loads(js.read_text(encoding="utf-8"))
    assert d["new"]["bg_entities"] == KNOWN["CardDefs.Bacon.xml"]["entities"]
    assert d["old"]["bg_entities"] > 5000
    assert len(d["bg_added"]) + len(d["bg_removed"]) > 0
    assert d["value_change_counts"]["ATK"] > 0
    assert "dbf id" in md.read_text(encoding="utf-8")


def test_generator_consumed_255130():
    """生成器试跑报告：合并 XML 后可被 generate_bg_data 消费并被 CardDB 加载。"""
    js = ROOT / "reversed" / "data_255130_generator_report.json"
    if not js.exists():
        pytest.skip("生成器试跑报告不存在（先跑 tools/rea_generate_probe.py）")
    rep = json.loads(js.read_text(encoding="utf-8"))
    assert rep["rc"] == 0
    assert rep["engine_load_new"]["ok"] is True
    assert rep["generated"]["summary"]["patch"] == "37.0.0.255130.254477"
    assert rep["generated"]["summary"]["pool_minions"]["count"] > 0
    # 新数据必须真的包含酒馆战棋卡（拆分文件被正确合并）
    assert rep["generated"]["summary"]["total_bg_cards"] > 3000
    assert rep["engine_load_new"]["invalid_card_type_count"] == \
        rep["engine_load_current"]["invalid_card_type_count"], \
        "新数据引入了新的无法映射 card_type（需要更新 CardType 分支）"


def test_255130_aberration_race_supported():
    """37.0 新种族 ABERRATION(126)：官方数据存在，且引擎已正式收录。

    升级前（36.2.2 引擎）本测试断言 "126 未收录"=升级风险；S3 结构修复后
    反转为**已支持**守卫：Race/DBF 映射/池数据三者必须一致。
    """
    js = ROOT / "reversed" / "data_255130_generator_report.json"
    if not js.exists():
        pytest.skip("生成器试跑报告不存在")
    pool = ROOT / "reversed" / "data_255130" / "bg_pool_minions.json"
    if not pool.exists():
        pytest.skip("生成数据不存在")
    cards = json.loads(pool.read_text(encoding="utf-8"))
    aberration = [c for c in cards if c.get("card_race") == 126]
    assert len(aberration) >= 20, "预期 37.0 新种族 ABERRATION(126) 有 ≥20 张池内随从"
    from hsrl2.tags import DBF_RACE_TO_ENUM, STANDARD_RACES, Race
    assert int(Race.ABERRATION) == 126, "引擎 Race.ABERRATION 必须 = 官方 126"
    assert DBF_RACE_TO_ENUM[126] is Race.ABERRATION
    assert Race.ABERRATION in STANDARD_RACES, "ABERRATION 必须是标准种族（ALL 展开域）"
    # 池内 ABERRATION 随从可被 CardDB 正确映射（不允许静默降级为 NONE）
    from hsrl2.db import CardDB
    data_dir = ROOT / "data"
    if (data_dir / "bg_pool_minions.json").exists():
        db = CardDB.load(data_dir)
        got = [d for d in db.pool_minions() if d.race == Race.ABERRATION]
        assert len(got) >= 20, f"新建 data/ 池内 ABERRATION 随从 {len(got)} < 20"
