#!/usr/bin/env python
"""rea_fetch_hsdata.py — 按 Hearthstone build tag 获取官方 CardDefs（幂等）。

数据源: HearthSim/hsdata（从官方客户端 `Data/Win/dbf.unity3d` 等资源提取的
CardXML/DBF 转储），每个游戏 build 对应一个 git tag。本机安装版本
`37.0.0.255130.254477` ↔ tag `255130`。

**重要**：从 build 255130 起，hsdata 把 CardDefs 拆成多个文件——
    CardDefs.xml          构筑模式卡（constructed）
    CardDefs.Bacon.xml    酒馆战棋卡（**本项目的核心数据**）
    CardDefs.Lettuce.xml  佣兵战纪卡
旧 build（如 249896）只有一个 `CardDefs.xml` 含全部卡。本工具会按 tag 的实际
文件清单自适应：先探测 `CardDefs.xml`，再探测 Bacon/Lettuce/RaceTagMap/README。

用法:
    python tools/rea_fetch_hsdata.py --tag 255130
    python tools/rea_fetch_hsdata.py --tag 255130 --deep     # 额外完整解析校验
    python tools/rea_fetch_hsdata.py --tag 249896            # 旧布局（单文件）
    python tools/rea_fetch_hsdata.py --check                 # 只校验，不下载
    python tools/rea_fetch_hsdata.py --with-lettuce          # 额外抓佣兵（19MB）

产物（全部在 reversed/ 下，不触碰 hsdata/ 与 data/）:
    reversed/hsdata_<tag>/CardDefs.xml              构筑卡
    reversed/hsdata_<tag>/CardDefs.Bacon.xml        酒馆战棋卡（若该 tag 提供）
    reversed/hsdata_<tag>/CardDefs.Lettuce.xml      佣兵卡（--with-lettuce）
    reversed/hsdata_<tag>/RaceTagMap.xml            种族 tag 表（若提供）
    reversed/hsdata_<tag>/README.md                 hsdata 的版本说明
    reversed/hsdata_<tag>/<file>.sha256             每个文件的 sha256 sidecar
    reversed/hsdata_<tag>/source.json               来源 URL / 大小 / sha256 / 时间

幂等语义:
    - sidecar 的 sha256 与磁盘文件一致 → 跳过；不一致/缺失 → 重新下载并原子替换。
    - 下载后校验: Content-Length、实际字节数、sha256、XML 头尾标记。
    - `KNOWN_HASHES` 里登记过的文件额外断言 sha256 精确匹配（上游重新打包会报警）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVERSED = ROOT / "reversed"
BASE_URL = "https://raw.githubusercontent.com/HearthSim/hsdata/{tag}/{name}"

CORE = "CardDefs.xml"
#: 探测顺序：(文件名, 是否默认下载)
CANDIDATES = [
    ("CardDefs.xml", True),
    ("CardDefs.Bacon.xml", True),
    ("RaceTagMap.xml", True),
    ("README.md", True),
    ("CardDefs.Lettuce.xml", False),
]

#: 首次抓取后记录，用于"同一 tag 内容永不变"的强断言。
#: 键 = "tag/文件名"；值 = {"size": int, "sha256": str}
KNOWN_HASHES: dict[str, dict] = {
    # 2026-10-18 首次抓取记录（37.0.0.255130.254477）
    "255130/CardDefs.xml": {
        "size": 70509381,
        "sha256": "c7863b8fc7dd109d3e67230bf2efda319b175f8bd9ddfa955b5f4cb5cb267f0f",
    },
    # 酒馆战棋卡（build 255130 起拆分；本项目核心数据）
    "255130/CardDefs.Bacon.xml": {
        "size": 15826018,
        "sha256": "c60d62b350f2d0361cd88b12e4941bfe6a9f24125c1af003858adb7728b3f413",
    },
    "255130/RaceTagMap.xml": {
        "size": 1443,
        "sha256": "3e3df0413390d8e47ce783812e8f56e3cd0f23c14bf9f67237659a55ebb5f0e9",
    },
    "255130/README.md": {
        "size": 291,
        "sha256": "36c8c8ed94d6a909cf5634d79e9883cd05c82c9f501cbb5673fd23aaf4e695e7",
    },
}

MIN_ENTITIES = 5000


class FetchError(RuntimeError):
    pass


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                  encoding="utf-8")
    os.replace(tmp, path)


def head(url: str, timeout: int = 60) -> dict | None:
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "hsbg-rea-fetch/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"status": r.status, "headers": dict(r.headers)}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def validate_xml_shape(path: Path) -> None:
    """按文件名推断 XML 根元素并校验头尾标记。"""
    base = path.name
    if base.startswith("CardDefs"):
        root_tag = "CardDefs"
    elif base.startswith("RaceTagMap"):
        root_tag = "RaceTagMap"
    else:
        root_tag = base.split(".")[0]
    with open(path, "rb") as f:
        head_bytes = f.read(4096)
        f.seek(max(0, path.stat().st_size - 4096))
        tail_bytes = f.read()
    if f"<{root_tag}".encode() not in head_bytes:
        raise FetchError(f"{path.name}: 头缺少 <{root_tag}> 标记")
    if f"</{root_tag}>".encode() not in tail_bytes:
        raise FetchError(f"{path.name}: 尾缺少 </{root_tag}> 标记")


def deep_validate(path: Path) -> dict:
    import xml.etree.ElementTree as ET

    root = ET.parse(str(path)).getroot()
    if root.tag != "CardDefs":
        raise FetchError(f"XML 根元素不是 CardDefs，而是 {root.tag!r}")
    entities = root.findall("Entity")
    with_card_id = [e for e in entities if e.get("CardID")]
    if len(with_card_id) < 100:
        raise FetchError(f"{path.name}: Entity 数量异常 {len(with_card_id)}")
    return {"file": path.name, "build": root.get("build"),
            "entities": len(entities),
            "entities_with_card_id": len(with_card_id)}


def download(url: str, dest: Path, timeout: int = 180) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    part.unlink(missing_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "hsbg-rea-fetch/1"})
    print(f"[rea] GET {url}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        status = r.status
        headers = dict(r.headers)
        expected = headers.get("Content-Length")
        expected = int(expected) if expected else None
        h = hashlib.sha256()
        size = 0
        t0 = time.time()
        with open(part, "wb") as f:
            while True:
                block = r.read(1 << 20)
                if not block:
                    break
                f.write(block)
                h.update(block)
                size += len(block)
    if status != 200:
        part.unlink(missing_ok=True)
        raise FetchError(f"HTTP {status}")
    if expected is not None and size != expected:
        part.unlink(missing_ok=True)
        raise FetchError(f"字节数不匹配: {size} != Content-Length {expected}")
    digest = h.hexdigest()
    if dest.suffix == ".xml" or dest.name.endswith(".xml"):
        validate_xml_shape(part)
    os.replace(part, dest)
    print(f"[rea]   完成 {size:,} bytes sha256={digest} "
          f"({time.time() - t0:.1f}s)")
    return {"size": size, "sha256": digest, "http_status": status,
            "etag": headers.get("ETag", "")}


def ensure_file(tag: str, name: str, dest_dir: Path, *,
                force: bool, check_only: bool) -> dict | None:
    """下载/校验单个文件。404 → None（该 tag 无此文件）。"""
    dest = dest_dir / name
    sidecar = dest.with_suffix(dest.suffix + ".sha256")
    key = f"{tag}/{name}"
    known = KNOWN_HASHES.get(key)
    url = BASE_URL.format(tag=tag, name=name)

    rec = read_json(sidecar)
    if dest.exists() and rec and not force:
        actual = sha256_of(dest)
        if actual == rec.get("sha256") and dest.stat().st_size == rec.get("size"):
            if known and (actual != known["sha256"]
                          or dest.stat().st_size != known["size"]):
                raise FetchError(f"{name}: 磁盘文件与 KNOWN_HASHES 不符 "
                                 f"sha256={actual}")
            print(f"[rea] {name}: 已存在且校验通过（跳过） "
                  f"{dest.stat().st_size:,} bytes")
            return {"name": name, "status": "cached",
                    "size": dest.stat().st_size, "sha256": actual}
        print(f"[rea] {name}: sidecar 不一致 → 重新下载")

    if check_only:
        return None

    info = head(url)
    if info is None:
        print(f"[rea] {name}: 该 tag 无此文件（404），跳过")
        return None
    meta = download(url, dest)
    digest, size = meta["sha256"], meta["size"]
    if known and (digest != known["sha256"] or size != known["size"]):
        raise FetchError(f"{name}: 下载内容与 KNOWN_HASHES 不符 "
                         f"size={size} sha256={digest}")
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json(sidecar, {"tag": tag, "name": name, "size": size,
                         "sha256": digest, "url": url,
                         "fetched_at": fetched_at})
    return {"name": name, "status": "downloaded", "size": size,
            "sha256": digest, "url": url, "etag": meta.get("etag", "")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", default="255130",
                    help="HearthSim/hsdata build tag（默认 255130）")
    ap.add_argument("--dest", default=None,
                    help="覆盖输出目录（默认 reversed/hsdata_<tag>/）")
    ap.add_argument("--check", action="store_true", help="只校验不下载")
    ap.add_argument("--deep", action="store_true", help="完整解析 XML 校验")
    ap.add_argument("--force", action="store_true", help="忽略 sidecar 强制重下")
    ap.add_argument("--with-lettuce", action="store_true",
                    help="额外抓佣兵 CardDefs.Lettuce.xml（~19MB）")
    args = ap.parse_args(argv)

    tag = str(args.tag)
    dest_dir = Path(args.dest) if args.dest else (REVERSED / f"hsdata_{tag}")
    print(f"[rea] tag={tag} dest_dir={dest_dir}")

    files = list(CANDIDATES)
    if args.with_lettuce:
        files = [(n, True if n == "CardDefs.Lettuce.xml" else d)
                 for n, d in files]
    results: list[dict] = []
    failures: list[str] = []
    try:
        for name, enabled in files:
            if not enabled:
                continue
            r = ensure_file(tag, name, dest_dir, force=args.force,
                            check_only=args.check)
            if r is not None:
                results.append(r)
    except (FetchError, OSError) as exc:
        print(f"[rea] 失败: {exc}", file=sys.stderr)
        failures.append(str(exc))

    # ── 核心文件必须有 ──
    core = dest_dir / CORE
    if not core.exists():
        print(f"[rea] 错误: 核心文件缺失 {core}", file=sys.stderr)
        return 2
    deep = None
    if args.deep:
        try:
            deep = [deep_validate(dest_dir / r["name"]) for r in results
                    if r["name"].endswith(".xml")
                    and (dest_dir / r["name"]).exists()]
            for d in deep:
                print(f"[rea] deep: {d}")
        except (FetchError, OSError) as exc:
            print(f"[rea] deep 校验失败: {exc}", file=sys.stderr)
            return 3

    source = dest_dir / "source.json"
    old = read_json(source) or {}
    downloaded = any(r.get("status") == "downloaded" for r in results)
    # 幂等：--check 或全部命中缓存时**不重写** source.json（避免无意义 churn）
    if not args.check and (downloaded or not source.exists()):
        payload = {
            "tag": tag,
            "base_url": BASE_URL.format(tag=tag, name="<file>"),
            "fetched_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            # 命中缓存的文件保留上次记录的 url/etag，避免信息退化
            "files": {
                name: {**old.get("files", {}).get(name, {}), **r}
                for name, r in ((x["name"], x) for x in results)
            },
            "previous": old.get("files", {}),
            "source": "HearthSim/hsdata（从官方客户端提取的 CardXML/DBF 转储）",
            "note": "build 255130 起 CardDefs 拆分为 constructed/bacon/lettuce "
                    "三份；酒馆战棋数据在 CardDefs.Bacon.xml",
            "usage": "仅供本项目内部规则核对/数据生成，不修改游戏目录",
            "deep": deep,
        }
        write_json(source, payload)
        print(f"[rea] 来源记录: {source}")
    else:
        print(f"[rea] 来源记录未变，保持 {source}（幂等）")

    # ── 汇总 ──
    print("[rea] 文件清单:")
    for p in sorted(dest_dir.glob("*")):
        if p.is_file():
            print(f"[rea]   {p.name:<24} {p.stat().st_size:>12,} bytes")
    if failures:
        return 1
    print(f"[rea] OK: {dest_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
