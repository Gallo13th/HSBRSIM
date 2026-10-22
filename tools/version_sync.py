#!/usr/bin/env python
"""version_sync.py — 游戏版本 <-> 项目数据 一键检查 / 预演 / 应用流水线。

背景
----
炉石客户端更新频繁；本项目的数值权威是 **HearthSim/hsdata** 的 CardDefs
（每个游戏 build 对应一个 git tag）。本工具把「发现新版本 → 取数 → 生成 →
差分 → （可选）应用」串成一条可执行流水线，并汇总四个版本信号：

1. 本机游戏 build：`C:\\Program Files (x86)\\Hearthstone\\.product.db`（只读）；
2. 项目数据：`data/bg_summary.json` 的 `patch`；
3. HearthSim/hsdata 最新 tag（GitHub API；离线时用缓存/本地目录降级）；
4. rizling（AgenticAssistant）最新发行包 `release-manifest.json`
   （HTTP Range 只读 ZIP 中央目录 + 该文件，不下载 54MB 全包）。

用法
----
    python tools/version_sync.py --check            # 四信号 + 结论（默认动作）
    python tools/version_sync.py --dry-run          # 预演: 取数/合并/生成/差分（不写 data/）
    python tools/version_sync.py --apply --yes      # 应用: 备份→复制→回归→（失败自动回滚）

常用选项
--------
    --offline           不联网；只用 runs/version_sync/cache 与 reversed/hsdata_*
    --build X           覆盖「本机游戏 build」信号（模拟，仅测试/演练）
    --project-patch X   覆盖「项目数据 patch」信号（模拟，仅测试/演练）
    --target-tag X      指定目标 hsdata tag（默认取最新；模拟/离线用）
    --root DIR          指定仓库根（默认本脚本上级目录）
    --json              只输出 JSON（stdout）
    --no-tests          应用时跳过 pytest（不推荐）
    --no-smoke          应用时跳过 smoke_random_games

产物
----
    runs/version_sync/<timestamp>.json          四信号检查报告
    runs/version_sync/dryrun_<tag>.json|.md     预演结论
    runs/version_sync/apply_<tag>.json          应用结果（含回滚标记）
    tmp_version_sync/data_<tag>/                新数据生成目录（**不写 data/**）
    tmp_version_sync/CardDefs.merged.<tag>.xml  合并口径输入
    tmp_version_sync/report_<tag>.json|.md      官方数据差分

安全边界
--------
- 除 `--apply --yes` 外**不写** `data/` 与 `hsdata/`；
- `--apply` 会先备份到 `data/backup_<old_build>/` 与 `hsdata/backup_<old_build>/`，
  回归/压测失败自动回滚；不运行任何下载的可执行文件、不修改游戏目录。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
RUNS_DIR = ROOT / "runs" / "version_sync"
CACHE_DIR = RUNS_DIR / "cache"
TMP_SYNC = ROOT / "tmp_version_sync"

DEFAULT_GAME_DIR = Path(r"C:\Program Files (x86)\Hearthstone")
DEFAULT_PRODUCT_DB = DEFAULT_GAME_DIR / ".product.db"

HSDATA_TAGS_API = "https://api.github.com/repos/HearthSim/hsdata/tags?per_page=5"
RIZLING_ZIP_URL = "https://rizling.top/assistant/updates/latest.zip"

USER_AGENT = "hsagent-version-sync/1.0"
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?")

#: `generate_bg_data.py` 的产物清单（应用时复制；顺序无关）
DATA_FILES = [
    "bg_cards.json", "bg_pool_minions.json", "bg_pool_spells.json",
    "bg_heroes.json", "bg_hero_powers.json", "bg_trinkets.json",
    "bg_anomalies.json", "bg_quest_rewards.json", "bg_tavern_spells.json",
    "bg_dark_gifts.json", "bg_summary.json", "pool_minion_texts.json",
]

Status = str  # "up-to-date" / "update-available" / "waiting-for-hsdata" / "unknown"


# ══════════════════════ 通用工具 ══════════════════════

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path | str, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_version(value: Any) -> Tuple[int, ...]:
    """``37.0.0.255130.254477`` → ``(37,0,0,255130,254477)``。"""
    if isinstance(value, (tuple, list)):
        try:
            return tuple(int(x) for x in value)
        except (TypeError, ValueError):
            return ()
    if value is None:
        return ()
    match = VERSION_RE.search(str(value))
    if not match:
        return ()
    return tuple(int(g) for g in match.groups() if g is not None)


def compare_versions(a: Any, b: Any) -> int:
    """版本比较（短尾补 0）。a<b → -1，相等 → 0，a>b → 1。"""
    pa, pb = parse_version(a), parse_version(b)
    if not pa or not pb:
        return 0 if pa == pb else (-1 if not pa else 1)
    n = max(len(pa), len(pb))
    pa = pa + (0,) * (n - len(pa))
    pb = pb + (0,) * (n - len(pb))
    return (pa > pb) - (pa < pb)


def build_number(value: Any) -> Optional[int]:
    """取游戏 build 号：通常为版本第 4 段（37.0.0.**255130**）。"""
    parts = parse_version(value)
    return parts[3] if len(parts) > 3 else None


def _version_str(parts: Sequence[int]) -> str:
    return ".".join(str(x) for x in parts)


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, value: Any) -> Path:
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ══════════════════════ 信号 1: 本机游戏 build ══════════════════════

def read_client_build(product_db: Optional[Path | str] = None) -> Optional[dict]:
    """只读解析 `.product.db` 中的版本串。

    优先复用 `hsbg.bridge.rizling.read_product_db()`（已在产品中验证）；
    导入失败时用本地正则兜底。文件缺失 → None（不视为错误）。
    """
    path = Path(product_db or DEFAULT_PRODUCT_DB)
    if not path.is_file():
        return None
    try:  # 复用 bridge-analyst 的解析实现
        sys.path.insert(0, str(ROOT))
        from hsbg.bridge.rizling import read_product_db  # type: ignore

        info = read_product_db(path)
        if info:
            info["source"] = "hsbg.bridge.rizling"
            return info
    except Exception:  # noqa: BLE001 - 降级到本地解析
        pass
    raw = path.read_bytes().decode("latin-1")
    match = VERSION_RE.search(raw)
    if not match:
        return None
    parts = [int(g) for g in match.groups() if g is not None]
    return {
        "path": str(path),
        "raw": match.group(0),
        "version": _version_str(parts[:4]),
        "build": parts[3],
        "revision": parts[4] if len(parts) > 4 else None,
        "source": "local-regex",
    }


# ══════════════════════ 信号 2: 项目数据 patch ══════════════════════

def read_project_patch(root: Path = ROOT) -> Optional[dict]:
    path = Path(root) / "data" / "bg_summary.json"
    if not path.is_file():
        return None
    try:
        patch = _load_json(path).get("patch")
    except (OSError, ValueError):
        return None
    if not patch:
        return None
    return {"path": str(path), "patch": str(patch),
            "build": build_number(patch)}


# ══════════════════════ 信号 3: HearthSim/hsdata tags ══════════════════════

def read_local_hsdata_tags(root: Path = ROOT) -> List[str]:
    """本地已抓取的 `reversed/hsdata_<tag>/` tag 列表（离线降级用）。"""
    tags: List[str] = []
    for path in sorted(Path(root, "reversed").glob("hsdata_*/source.json")):
        try:
            tag = str(_load_json(path).get("tag") or "")
        except (OSError, ValueError):
            tag = path.parent.name.removeprefix("hsdata_")
        if tag.isdigit():
            tags.append(tag)
    # 目录存在但 source.json 缺失也算
    for path in Path(root, "reversed").glob("hsdata_*"):
        if path.is_dir() and path.name.removeprefix("hsdata_").isdigit():
            tag = path.name.removeprefix("hsdata_")
            if tag not in tags:
                tags.append(tag)
    return sorted(set(tags), key=int)


def _default_http_json(url: str, timeout: int = 20,
                       headers: Optional[dict] = None) -> Any:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_hsdata_tags(
    *, offline: bool = False, timeout: int = 20,
    http_json: Optional[Callable[..., Any]] = None,
    cache_dir: Optional[Path] = None, root: Path = ROOT,
) -> dict:
    """获取 hsdata 最新 tags。网络失败/离线 → 缓存 → 本地目录，永不抛异常。"""
    cache = (cache_dir or CACHE_DIR) / "hsdata_tags.json"
    result: dict = {"tags": [], "source": "none", "fetched_at": None,
                    "error": None, "cached": False}
    if not offline:
        try:
            getter = http_json or _default_http_json
            raw = getter(HSDATA_TAGS_API, timeout=timeout,
                         headers={"Accept": "application/vnd.github+json"})
            tags = []
            for item in raw if isinstance(raw, list) else []:
                name = str(item.get("name") or "") if isinstance(item, dict) else ""
                if name.isdigit():
                    tags.append(name)
            if tags:
                tags = sorted(set(tags), key=int, reverse=True)
                result.update(tags=tags, source="github",
                              fetched_at=now_iso(), cached=False)
                try:
                    _write_json(cache, {"fetched_at": result["fetched_at"],
                                        "source": "github", "tags": tags})
                except OSError:
                    pass
                return result
            result["error"] = "GitHub API 返回空 tag 列表"
        except Exception as exc:  # noqa: BLE001 - 网络问题必须降级
            result["error"] = f"{type(exc).__name__}: {exc}"
    if cache.is_file():
        try:
            cached = _load_json(cache)
            tags = [str(t) for t in cached.get("tags") or [] if str(t).isdigit()]
            if tags:
                result.update(tags=sorted(set(tags), key=int, reverse=True),
                              source="cache", cached=True,
                              fetched_at=cached.get("fetched_at"))
                return result
        except (OSError, ValueError):
            pass
    local = read_local_hsdata_tags(root)
    if local:
        result.update(tags=sorted(local, key=int, reverse=True),
                      source="local-reversed", cached=False)
    return result


# ══════════════════════ 信号 4: rizling 最新包 ══════════════════════

def _default_http_range(url: str, start: int, end: int,
                        timeout: int = 90, retries: int = 3) -> bytes:
    """HTTP Range GET（Cloudflare 偶发 404/超时 → 重试）。"""
    last: Optional[Exception] = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT,
                          "Range": f"bytes={start}-{end}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.5 * (attempt + 1))
    raise last if last else RuntimeError("range request failed")


def _default_remote_size(url: str, timeout: int = 60,
                         retries: int = 3) -> int:
    """用 Range 0-0 的 `Content-Range` 读远程文件总大小（不依赖 HEAD）。"""
    last: Optional[Exception] = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content_range = resp.headers.get("Content-Range") or ""
                resp.read()
            if "/" in content_range:
                return int(content_range.rsplit("/", 1)[1])
            raise ValueError(f"缺少 Content-Range: {content_range!r}")
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.5 * (attempt + 1))
    raise last if last else RuntimeError("size probe failed")


def remote_zip_manifest(
    url: str = RIZLING_ZIP_URL,
    *, range_get: Optional[Callable[..., bytes]] = None,
    size_get: Optional[Callable[[], int]] = None,
) -> dict:
    """用 Range 读远程 ZIP 的 `release-manifest.json`（不下载全包）。

    只下载：尾部 64KB（找 EOCD）+ 中央目录 + 目标条目本地头/压缩数据
    （实测 rizling 最新包约 0.3–0.5MB，而非 54MB）。

    返回 ``{"manifest": dict, "bytes_downloaded": int, "zip_size": int}``。
    """
    getter = range_get or _default_http_range
    downloaded = 0

    def get(start: int, end: int) -> bytes:
        nonlocal downloaded
        data = getter(url, start, end)
        downloaded += len(data)
        return data

    size = size_get() if size_get else _default_remote_size(url)
    # 1) 尾部窗口找 EOCD（ZIP 注释为空时在最后 22 字节）
    tail_len = min(65536, size)
    tail = get(max(0, size - tail_len), size - 1)
    idx = tail.rfind(b"PK\x05\x06")
    if idx < 0:
        raise ValueError("远程 ZIP 未找到 EOCD（可能不是 ZIP）")
    eocd = tail[idx:idx + 22]
    (_sig, _disk, _cd_disk, _n_disk, _n_total, cd_size,
     cd_off, _comment) = struct.unpack("<IHHHHIIH", eocd)
    if cd_off + cd_size > size:
        raise ValueError("远程 ZIP 中央目录越界（Range 读取异常）")
    # 2) 中央目录
    cd = get(cd_off, cd_off + cd_size - 1)
    pos = 0
    entry = None
    while pos <= len(cd) - 46:
        if cd[pos:pos + 4] != b"PK\x01\x02":
            break
        (_sig2, _made, _need, _flags, method, _mt, _md,
         _crc, csize, usize, nlen, xlen, clen, _disk_start, _iattr,
         _eattr, lho) = struct.unpack("<IHHHHHHIIIHHHHHII", cd[pos:pos + 46])
        name = cd[pos + 46:pos + 46 + nlen].decode("utf-8", "replace")
        if name.endswith("release-manifest.json"):
            entry = {"name": name, "method": method, "csize": csize,
                     "usize": usize, "lho": lho}
        pos += 46 + nlen + xlen + clen
    if entry is None:
        raise ValueError("远程包中没有 release-manifest.json")
    # 3) 本地头 + 压缩数据
    local = get(entry["lho"], entry["lho"] + 29)
    (_lsig, _ver, _flags3, method, _mt3, _md3, _crc3, csize, usize,
     nlen, xlen) = struct.unpack("<IHHHHHIIIHH", local)
    data_start = entry["lho"] + 30 + nlen + xlen
    raw = get(data_start, data_start + csize - 1)
    if method == 8:
        payload = zlib.decompress(raw, -15)
    elif method == 0:
        payload = raw
    else:
        raise ValueError(f"不支持的 ZIP 压缩方法 {method}")
    return {"manifest": json.loads(payload.decode("utf-8")),
            "bytes_downloaded": downloaded, "zip_size": size}


def read_local_rizling_manifest(root: Path = ROOT) -> Optional[dict]:
    path = Path(root) / "reversed" / "rizling_latest" / "release-manifest.json"
    if not path.is_file():
        return None
    try:
        raw = _load_json(path)
        return {"manifest": raw, "source": "local-reversed",
                "fetched_at": None, "error": None}
    except (OSError, ValueError):
        return None


def fetch_rizling_manifest(
    *, offline: bool = False, range_get: Optional[Callable[..., bytes]] = None,
    size_get: Optional[Callable[[], int]] = None,
    cache_dir: Optional[Path] = None, root: Path = ROOT,
) -> dict:
    """获取 rizling 最新 release-manifest。失败 → 缓存 → 本地副本，永不抛异常。"""
    cache = (cache_dir or CACHE_DIR) / "rizling_manifest.json"
    result: dict = {"manifest": None, "source": "none",
                    "fetched_at": None, "error": None,
                    "bytes_downloaded": 0}
    if not offline:
        try:
            got = remote_zip_manifest(RIZLING_ZIP_URL, range_get=range_get,
                                      size_get=size_get)
            manifest = got["manifest"]
            result.update(manifest=manifest, source="rizling-remote",
                          fetched_at=now_iso(),
                          bytes_downloaded=got["bytes_downloaded"])
            try:
                _write_json(cache, {"fetched_at": result["fetched_at"],
                                    "source": "rizling-remote",
                                    "manifest": manifest})
            except OSError:
                pass
            return result
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"
    if cache.is_file():
        try:
            cached = _load_json(cache)
            if isinstance(cached.get("manifest"), dict):
                result.update(manifest=cached["manifest"], source="cache",
                              fetched_at=cached.get("fetched_at"))
                return result
        except (OSError, ValueError):
            pass
    local = read_local_rizling_manifest(root)
    if local:
        result.update(local)
    return result


# ══════════════════════ 四信号汇总 + 决策 ══════════════════════

def collect_signals(
    root: Path = ROOT, *, offline: bool = False,
    product_db: Optional[Path | str] = None,
    build_override: Optional[str] = None,
    project_patch_override: Optional[str] = None,
    target_tag_override: Optional[str] = None,
    http_json: Optional[Callable[..., Any]] = None,
    range_get: Optional[Callable[..., bytes]] = None,
    size_get: Optional[Callable[[], int]] = None,
    cache_dir: Optional[Path] = None,
) -> dict:
    client = read_client_build(product_db)
    if build_override:
        parts = parse_version(build_override)
        client = {"path": "<--build override>", "raw": build_override,
                  "version": _version_str(parts[:4]) if parts else build_override,
                  "build": build_number(build_override),
                  "revision": parts[4] if len(parts) > 4 else None,
                  "source": "override"} if parts else {
            "path": "<--build override>", "raw": build_override,
            "version": None, "build": None, "revision": None,
            "source": "override"}
    project = read_project_patch(root)
    if project_patch_override:
        project = {"path": "<--project-patch override>",
                   "patch": project_patch_override,
                   "build": build_number(project_patch_override)}
    hsdata = fetch_hsdata_tags(offline=offline, http_json=http_json,
                               cache_dir=cache_dir, root=root)
    local_tags = read_local_hsdata_tags(root)
    if target_tag_override:
        hsdata["tags"] = sorted(set(hsdata["tags"] + [str(target_tag_override)]),
                                key=int, reverse=True)
        hsdata["source"] = (hsdata["source"] + "+override")
    rizling = fetch_rizling_manifest(offline=offline, range_get=range_get,
                                     size_get=size_get,
                                     cache_dir=cache_dir, root=root)
    game_version = None
    if rizling.get("manifest"):
        game_version = rizling["manifest"].get("game_version")
        rizling["version"] = rizling["manifest"].get("version")
        rizling["game_version"] = game_version
        rizling["build"] = build_number(game_version)
    else:
        rizling["version"] = rizling["game_version"] = rizling["build"] = None
    return {
        "generated_at": now_iso(),
        "client": client,
        "project": project,
        "hsdata": hsdata,
        "hsdata_local_tags": local_tags,
        "rizling": rizling,
    }


def decide(signals: Optional[Mapping] = None) -> dict:
    """根据四信号给出状态与目标 tag。纯函数（无 IO），便于测试。"""
    sig = signals or {}
    client_build = (sig.get("client") or {}).get("build")
    project = sig.get("project") or {}
    project_build = project.get("build")
    hsdata = sig.get("hsdata") or {}
    tags = [int(t) for t in hsdata.get("tags") or [] if str(t).isdigit()]
    target = max(tags) if tags else None
    rizling_build = (sig.get("rizling") or {}).get("build")
    local_tags = [int(t) for t in sig.get("hsdata_local_tags") or []
                  if str(t).isdigit()]
    local_latest = max(local_tags) if local_tags else None
    warnings: List[str] = []
    errors: List[str] = []

    if target is None:
        if local_latest is not None:
            target = local_latest
            warnings.append("hsdata tag 不可用（离线/网络失败）→ 使用本地已抓取最大 tag")
        else:
            errors.append("无法确定 hsdata 最新 tag（网络失败且无缓存/本地数据）")

    if project_build is None:
        errors.append("项目数据缺失或 bg_summary.json 无 patch")

    if target is not None and project_build is not None:
        if target > project_build:
            status = "update-available"
        elif target == project_build:
            status = "up-to-date"
        else:  # target < project_build
            status = "up-to-date"
            warnings.append("项目数据比 hsdata 最新 tag 新（本地先行/源滞后）")
    elif target is not None and project_build is None:
        status = "unknown"
    else:
        status = "unknown"

    # 客户端领先项目数据 → 等待 hsdata 发布（游戏更新早于数据源的常态）
    if client_build is not None and project_build is not None:
        if client_build > project_build:
            if target is not None and target >= client_build:
                status = "update-available"
                warnings.append(f"客户端 build {client_build} 已有 hsdata tag "
                                f"{target}，可升级")
            else:
                if status != "update-available":
                    status = "waiting-for-hsdata"
                warnings.append(
                    f"客户端 build {client_build} 比项目数据 "
                    f"{project_build} 新：等待 HearthSim 发布 tag "
                    f"{client_build}（当前最新 {target}）")
        elif client_build < project_build:
            warnings.append(
                f"项目数据 build {project_build} 比本机客户端 "
                f"{client_build} 新（项目先行/客户端未更新）")

    if rizling_build is not None and project_build is not None:
        if rizling_build > project_build:
            warnings.append(f"rizling 参考版本 {rizling_build} 比项目数据新"
                            "（参考信号，不驱动数据升级）")
        elif rizling_build < project_build:
            warnings.append(f"rizling 参考版本 {rizling_build} 落后于项目数据 "
                            f"{project_build}（rizling 未跟进，正常）")

    if hsdata.get("error"):
        warnings.append(f"hsdata 网络降级: {hsdata['error']}")
    if (sig.get("rizling") or {}).get("error"):
        warnings.append(f"rizling 网络降级: {sig['rizling']['error']}")

    return {
        "status": status,
        "target_tag": str(target) if target is not None else None,
        "project_build": project_build,
        "client_build": client_build,
        "hsdata_latest": str(max(tags)) if tags else None,
        "local_hsdata_latest": str(local_latest) if local_latest else None,
        "rizling_game_version": (sig.get("rizling") or {}).get("game_version"),
        "rizling_build": rizling_build,
        "warnings": warnings,
        "errors": errors,
    }


# ══════════════════════ 代码差分 / 生成（复用 rea_* 工具） ══════════════════════

def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_generator():
    return _load_module("version_sync_generate_bg_data",
                        TOOLS / "generate_bg_data.py")


def load_data_diff():
    return _load_module("version_sync_rea_data_diff",
                        TOOLS / "rea_data_diff.py")


def run_command(cmd: Sequence[str], *, cwd: Path = ROOT,
                timeout: Optional[int] = None) -> dict:
    started = time.time()
    try:
        proc = subprocess.run(list(map(str, cmd)), cwd=str(cwd),
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout)
        return {"cmd": [str(x) for x in cmd], "rc": proc.returncode,
                "stdout": proc.stdout, "stderr": proc.stderr,
                "seconds": round(time.time() - started, 2)}
    except Exception as exc:  # noqa: BLE001
        return {"cmd": [str(x) for x in cmd], "rc": -1,
                "stdout": "", "stderr": f"{type(exc).__name__}: {exc}",
                "seconds": round(time.time() - started, 2)}


def ensure_hsdata(tag: str, *, root: Path = ROOT, offline: bool = False,
                  fetch_log: Optional[Path] = None) -> dict:
    """确保 `reversed/hsdata_<tag>/` 存在；缺失且非离线时调用抓取工具。"""
    tag = str(tag)
    hdir = Path(root) / "reversed" / f"hsdata_{tag}"
    core = hdir / "CardDefs.xml"
    if core.is_file():
        return {"ok": True, "tag": tag, "dir": str(hdir),
                "action": "already-cached"}
    if offline:
        return {"ok": False, "tag": tag, "dir": str(hdir),
                "action": "offline-missing",
                "error": f"离线模式且本地无 reversed/hsdata_{tag}/"}
    log_path = fetch_log or (RUNS_DIR / f"fetch_{tag}.log")
    _ensure_dir(log_path.parent)
    run = run_command([sys.executable, TOOLS / "rea_fetch_hsdata.py",
                       "--tag", tag], cwd=str(root), timeout=1800)
    log_path.write_text(
        " ".join(run["cmd"]) + "\n\n[stdout]\n" + run["stdout"]
        + "\n[stderr]\n" + run["stderr"], encoding="utf-8")
    ok = run["rc"] == 0 and (hdir / "CardDefs.xml").is_file()
    return {"ok": ok, "tag": tag, "dir": str(hdir),
            "action": "fetched" if ok else "fetch-failed",
            "rc": run["rc"], "log": str(log_path),
            "error": None if ok else (run["stderr"] or "fetch failed")[-800:]}


def merge_carddefs(sources: Sequence[Path], dest: Path,
                   build: Optional[str] = None) -> Path:
    """合并拆分 CardDefs（255130+ 的 constructed + Bacon）为单文件口径。

    与 `rea_generate_probe.merge_xmls` 同构：逐行拼接并剥掉 XML 头/根标签，
    流式处理（~90MB 内存友好）。
    """
    sources = [Path(p) for p in sources]
    missing = [str(p) for p in sources if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"合并输入缺失: {missing}")
    _ensure_dir(dest.parent)
    build_attr = build or "merged"
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as out:
        out.write('<?xml version="1.0" encoding="utf-8"?>\n')
        out.write(f'<CardDefs build="{build_attr}">\n')
        for src in sources:
            with open(src, encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("<?xml") or line.startswith("<CardDefs"):
                        continue
                    if line.strip() == "</CardDefs>":
                        continue
                    out.write(line)
        out.write("</CardDefs>\n")
    os.replace(tmp, dest)
    return dest


def read_hsdata_version(tag: str, root: Path = ROOT) -> Optional[str]:
    """从 `reversed/hsdata_<tag>/README.md` 的 Version 行取本项目 patch 口径。"""
    readme = Path(root) / "reversed" / f"hsdata_{tag}" / "README.md"
    if readme.is_file():
        for line in readme.read_text(encoding="utf-8",
                                      errors="replace").splitlines():
            if line.startswith("Version:"):
                value = line.split(":", 1)[1].strip()
                if parse_version(value):
                    return value
    xml = Path(root) / "reversed" / f"hsdata_{tag}" / "CardDefs.xml"
    if xml.is_file():
        with open(xml, encoding="utf-8", errors="replace") as handle:
            head = handle.readline() + handle.readline()
        match = VERSION_RE.search(head)
        if match:
            return match.group(0)
    return None


def generate_data(tag: str, *, root: Path = ROOT, merged: Optional[Path] = None,
                  out_dir: Optional[Path] = None,
                  version: Optional[str] = None) -> dict:
    """用 `generate_bg_data.py`（猴补丁路径）把合并 XML 生成为 JSON。

    输出到 `tmp_version_sync/data_<tag>/`，**不触碰 root/data/**。
    """
    tag = str(tag)
    root = Path(root)
    merged = Path(merged) if merged else (TMP_SYNC / f"CardDefs.merged.{tag}.xml")
    out_dir = Path(out_dir) if out_dir else (TMP_SYNC / f"data_{tag}")
    version = version or read_hsdata_version(tag, root) or tag
    if out_dir.exists():
        shutil.rmtree(out_dir)
    _ensure_dir(out_dir)
    fake_root = TMP_SYNC / f"fake_root_{tag}"
    hsdata_fake = _ensure_dir(fake_root / "hsdata")
    (hsdata_fake / "README.md").write_text(
        "Hearthstone Data\n\nVersion: " + version + "\n",
        encoding="utf-8")
    module = load_generator()
    module.ROOT = fake_root
    module.HSDATA_XML = merged
    module.DATA_DIR = out_dir
    argv_backup = sys.argv[:]
    sys.argv = ["generate_bg_data.py"]
    try:
        rc = module.main()
    except SystemExit as exc:  # pragma: no cover
        rc = exc.code or 0
    finally:
        sys.argv = argv_backup
    files = {name: (out_dir / name).is_file() for name in DATA_FILES}
    summary = None
    if (out_dir / "bg_summary.json").is_file():
        summary = _load_json(out_dir / "bg_summary.json")
    return {"ok": rc == 0 and all(files.values()), "rc": rc,
            "out_dir": str(out_dir), "merged": str(merged),
            "version": version, "files": files, "summary": summary}


def _race_map_from_tags(tags: Mapping) -> Dict[int, int]:
    """从 CardDefs tags 里取 CARDRACE(200) 计数。"""
    counts: Dict[int, int] = {}
    for card in tags.values():
        race = card["tags"].get("200")
        if isinstance(race, int):
            counts[race] = counts.get(race, 0) + 1
    return counts


def diff_official_data(old_xml: Path, new_xmls: Sequence[Path], *,
                       tag: str, root: Path = ROOT,
                       out_prefix: Optional[Path] = None) -> dict:
    """官方 CardDefs 差分（复用 `rea_data_diff.parse/diff`），输出通用报告。"""
    module = load_data_diff()
    old_parsed = module.parse([Path(old_xml)])
    new_parsed = module.parse([Path(p) for p in new_xmls])
    module.OLD_PATH = Path(old_xml)
    module.NEW_PATHS = [Path(p) for p in new_xmls]
    data = module.diff(old_parsed, new_parsed)
    tag_names = module.load_tag_names()

    # 种族变化（CARDRACE 分布 + 公共卡 race 变更）
    old_races = _race_map_from_tags(old_parsed["bg"])
    new_races = _race_map_from_tags(new_parsed["bg"])
    race_changes = []
    for cid in sorted(set(old_parsed["bg"]) & set(new_parsed["bg"])):
        old_race = old_parsed["bg"][cid]["tags"].get("200")
        new_race = new_parsed["bg"][cid]["tags"].get("200")
        if old_race != new_race:
            race_changes.append({"id": cid, "old": old_race, "new": new_race})
    engine_race_values: Dict[int, str] = {}
    try:
        sys.path.insert(0, str(root))
        from hsrl2.tags import CardType, Race  # type: ignore

        engine_race_values = {int(r): r.name for r in Race}
        engine_card_types = {int(c): c.name for c in CardType}
    except Exception:  # noqa: BLE001
        engine_card_types = {}
    new_race_values = sorted(set(new_races) - set(old_races))
    unknown_races = [r for r in new_race_values if r not in engine_race_values]
    new_tag_ids = [{**item,
                    "name": tag_names.get(item["enumID"])}
                   for item in data["new_tag_enum_ids"]]
    # 新 card_type
    card_type_counts = new_parsed["bg_card_type_counts"]
    new_card_types = [{"value": v, "name": engine_card_types.get(v)}
                      for v in sorted(card_type_counts)
                      if v not in (old_parsed["bg_card_type_counts"] or {})
                      and v not in engine_card_types]
    # 生成数据汇总
    generated_summary = None
    gen_summary_path = TMP_SYNC / f"data_{tag}" / "bg_summary.json"
    if gen_summary_path.is_file():
        generated_summary = _load_json(gen_summary_path)
    item: dict = {
        "tag": tag,
        "generated_at": now_iso(),
        "old": {"path": str(old_xml), **data["old"]},
        "new": {"paths": [str(p) for p in new_xmls], **data["new"]},
        "delta": data["delta"],
        "bg_added_count": len(data["bg_added"]),
        "bg_added": data["bg_added"],
        "bg_removed_count": len(data["bg_removed"]),
        "bg_removed": data["bg_removed"],
        "id_renumbers": data["id_renumbers"],
        "name_changed_count": data["name_changed_count"],
        "value_change_counts": data["value_change_counts"],
        "value_change_total": sum(data["value_change_counts"].values()),
        "new_tag_enum_ids": new_tag_ids,
        "new_race_values": new_race_values,
        "new_race_names": [engine_race_values.get(r) for r in new_race_values],
        "unknown_race_values": unknown_races,
        "race_changed_count": len(race_changes),
        "race_changes": race_changes[:50],
        "race_distribution_old": {str(k): v for k, v in old_races.items()},
        "race_distribution_new": {str(k): v for k, v in new_races.items()},
        "new_card_types": new_card_types,
        "generated_summary": generated_summary,
        "current_summary": _load_json(root / "data" / "bg_summary.json")
        if (root / "data" / "bg_summary.json").is_file() else None,
    }
    prefix = Path(out_prefix) if out_prefix else (TMP_SYNC / f"report_{tag}")
    _write_json(prefix.with_suffix(".json"), item)
    prefix.with_suffix(".md").write_text(render_diff_md(item),
                                         encoding="utf-8")
    return item


def render_diff_md(d: Mapping) -> str:  # type: ignore[valid-type]
    lines: List[str] = []
    lines.append(f"# 官方数据差分预演：tag {d['tag']} vs 项目当前数据\n")
    lines.append("> 自动生成（`tools/version_sync.py --dry-run`），勿手改。\n")
    lines.append(f"- 生成时间: {d['generated_at']}")
    lines.append(f"- 旧: `{d['old']['path']}` — {d['old']['total_entities']:,} 实体"
                 f"（BG {d['old']['bg_entities']:,}，池内随从 "
                 f"{d['old']['bg_pool_minions']:,}）")
    lines.append(f"- 新: `{d['new']['paths']}` — {d['new']['total_entities']:,} 实体"
                 f"（BG {d['new']['bg_entities']:,}，池内随从 "
                 f"{d['new']['bg_pool_minions']:,}）")
    lines.append("")
    lines.append("## 1. 总量\n")
    lines.append("| 指标 | 旧 | 新 | Δ |")
    lines.append("|------|----|----|---|")
    for key, label in (("total_entities", "实体总数"),
                       ("bg_entities", "BG 集实体"),
                       ("bg_pool_minions", "池内随从")):
        lines.append(f"| {label} | {d['old'][key]:,} | {d['new'][key]:,} | "
                     f"{d['delta'][key]:+,} |")
    lines.append("")
    lines.append("## 2. BG 卡 id 变化\n")
    lines.append(f"- 新增 **{d['bg_added_count']}**，删除 **{d['bg_removed_count']}**")
    lines.append("")
    lines.append("## 3. 数值变化\n")
    if d["value_change_counts"]:
        lines.append("| tag | 变化卡数 |")
        lines.append("|-----|----------|")
        for key, count in d["value_change_counts"].items():
            lines.append(f"| `{key}` | {count} |")
        lines.append("")
        lines.append(f"合计 **{d['value_change_total']}** 处。")
    else:
        lines.append("无。")
    lines.append("")
    lines.append("## 4. 种族 / card_type / 新 tag\n")
    lines.append(f"- 种族取值变化（公共卡）: **{d['race_changed_count']}** 张")
    if d["new_race_values"]:
        lines.append(f"- 新出现 CARDRACE 取值: {d['new_race_values']}"
                     f"（{d['new_race_names']}）")
        if d["unknown_race_values"]:
            lines.append(f"- **引擎 Race 未收录**: {d['unknown_race_values']}"
                         " → 需在 `hsrl2/tags.py` 补录（fail-loud 会阻止加载）")
    lines.append(f"- 新 tag enumID: {len(d['new_tag_enum_ids'])} 个"
                 f"（前 20: {[x['enumID'] for x in d['new_tag_enum_ids'][:20]]}）")
    if d["new_card_types"]:
        lines.append(f"- **新 card_type**: {d['new_card_types']}"
                     " → 需在 `hsrl2/tags.py::CardType` 补录")
    lines.append("")
    lines.append("## 5. 生成数据摘要（`tmp_version_sync/data_<tag>/`）\n")
    gen, cur = d.get("generated_summary"), d.get("current_summary")
    if gen and cur:
        keys = ["patch", "total_bg_cards", "dark_gifts", "hero_powers",
                "tavern_spells", "quest_rewards", "anomalies", "trinkets"]
        lines.append("| 字段 | 新生成 | 当前 data/ |")
        lines.append("|------|--------|------------|")
        for key in keys:
            lines.append(f"| `{key}` | {gen.get(key)} | {cur.get(key)} |")
        for key in ("pool_minions", "pool_spells", "heroes"):
            g, c = gen.get(key), cur.get(key)
            if isinstance(g, dict) and isinstance(c, dict):
                lines.append(f"| `{key}.count` | {g.get('count')} | "
                             f"{c.get('count')} |")
        if isinstance(gen.get("pool_minions"), dict):
            lines.append("")
            lines.append(f"- by_race(新): `{gen['pool_minions'].get('by_race')}`")
    else:
        lines.append("（生成数据缺失）")
    lines.append("")
    lines.append("## 6. 迁移影响提示\n")
    lines.append("- 新卡默认无效果脚本（引擎以白板存在）——按 `REGISTRY` 缺口另列；")
    lines.append("- 未收录 race/card_type 必须先补 `hsrl2/tags.py`，否则 `--apply` "
                 "会被 fail-loud 拦截并自动回滚；")
    lines.append("- Dark Gift / 新机制 tag 若在 `new_tag_enum_ids` 中出现，需评估 "
                 "`hsrl2/darkgifts.py` 与 `tools/generate_bg_data.py` 白名单。")
    lines.append("")
    return "\n".join(lines)


def print_signals(signals: Mapping, decision: Mapping) -> None:  # type: ignore[valid-type]
    def fmt(value, suffix=""):
        return "—" if value is None else f"{value}{suffix}"

    client = signals.get("client") or {}
    project = signals.get("project") or {}
    hsdata = signals.get("hsdata") or {}
    rizling = signals.get("rizling") or {}
    print("=" * 78)
    print("版本同步检查（四信号）")
    print("=" * 78)
    print(f"  1) 本机游戏 build     : {fmt(client.get('raw'))}")
    print(f"       .product.db       : {fmt(client.get('path'))}")
    print(f"  2) 项目数据 patch     : {fmt(project.get('patch'))}"
          f"   ({fmt(project.get('path'))})")
    tags = hsdata.get("tags") or []
    print(f"  3) hsdata 最新 tag    : {fmt(tags[0] if tags else None)}"
          f"   [source={hsdata.get('source')}, "
          f"fetched={fmt(hsdata.get('fetched_at'))}]")
    print(f"       tags(前5)         : {tags[:5]}")
    manifest = rizling.get("manifest") or {}
    print(f"  4) rizling 最新包     : version={fmt(rizling.get('version'))}, "
          f"game_version={fmt(rizling.get('game_version'))}")
    print(f"       manifest 下载      : {rizling.get('bytes_downloaded', 0)} bytes"
          f"   [source={rizling.get('source')}]")
    print("-" * 78)
    status_label = {
        "up-to-date": "已是最新（UP-TO-DATE）",
        "update-available": "有可用更新（UPDATE-AVAILABLE）",
        "waiting-for-hsdata": "等待数据源发布（WAITING-FOR-HSDATA）",
        "unknown": "无法判定（UNKNOWN）",
    }.get(decision.get("status"), decision.get("status"))
    print(f"  结论: {status_label}")
    if decision.get("target_tag"):
        print(f"  目标 hsdata tag: {decision['target_tag']}")
    for warning in decision.get("warnings") or []:
        print(f"  [warn] {warning}")
    for error in decision.get("errors") or []:
        print(f"  [error] {error}")
    if decision.get("status") == "update-available":
        print("  下一步: python tools/version_sync.py --dry-run")
    elif decision.get("status") == "waiting-for-hsdata":
        print("  下一步: 等 HearthSim/hsdata 发布对应 tag 后重跑 --check")
    else:
        print("  下一步: 无需操作")
    print("=" * 78)


# ══════════════════════ --check ══════════════════════

def cmd_check(args, *, signals: Optional[dict] = None) -> int:
    signals = signals or collect_signals(
        Path(args.root), offline=args.offline,
        product_db=args.product_db, build_override=args.build,
        project_patch_override=args.project_patch,
        target_tag_override=args.target_tag)
    decision = decide(signals)
    if args.json:
        print(json.dumps({"signals": _jsonify_signals(signals),
                          "decision": decision}, ensure_ascii=False, indent=2))
    else:
        print_signals(signals, decision)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {"schema": "version_sync.check.v1",
              "generated_at": signals["generated_at"],
              "signals": _jsonify_signals(signals),
              "decision": decision}
    out = Path(args.root) / "runs" / "version_sync" / f"{stamp}.json"
    _write_json(out, report)
    if not args.json:
        print(f"报告: {out}")
    return 0


def _jsonify_signals(signals: Mapping) -> dict:  # type: ignore[valid-type]
    """信号里可能有 Path / 异常对象 / 完整 rizling manifest → 转轻量纯 JSON。

    完整 `release-manifest.json` 约 270KB（含 2000+ 文件哈希），报告里只保留
    version/game_version/built/public_release 摘要，避免每次 check 写 285KB。
    """
    def conv(value):
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(k): conv(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [conv(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    data = conv(dict(signals))
    rizling = data.get("rizling")
    if isinstance(rizling, dict) and isinstance(rizling.get("manifest"), dict):
        manifest = rizling.pop("manifest")
        rizling["manifest_summary"] = {
            key: manifest.get(key) for key in
            ("version", "game_version", "built", "public_release")}
    return data


# ══════════════════════ --dry-run ══════════════════════

def prepare_update(target_tag: str, *, root: Path = ROOT,
                   offline: bool = False) -> dict:
    """取数 → 合并 → 生成 → 差分。返回各步骤结果（不写 root/data）。"""
    tag = str(target_tag)
    root = Path(root)
    global TMP_SYNC, RUNS_DIR, CACHE_DIR, TOOLS, ROOT  # noqa: PLW0603
    ROOT = root
    TOOLS = root / "tools"
    RUNS_DIR = root / "runs" / "version_sync"
    CACHE_DIR = RUNS_DIR / "cache"
    TMP_SYNC = root / "tmp_version_sync"
    _ensure_dir(TMP_SYNC)
    steps: List[dict] = []

    fetched = ensure_hsdata(tag, root=root, offline=offline)
    steps.append({"step": "fetch_hsdata", **fetched})
    if not fetched["ok"]:
        return {"ok": False, "tag": tag, "steps": steps,
                "error": fetched.get("error")}

    hdir = Path(fetched["dir"])
    sources = [hdir / "CardDefs.xml"]
    if (hdir / "CardDefs.Bacon.xml").is_file():
        sources.append(hdir / "CardDefs.Bacon.xml")
    version = read_hsdata_version(tag, root) or tag
    merged = TMP_SYNC / f"CardDefs.merged.{tag}.xml"
    try:
        merge_carddefs(sources, merged, build=version)
        # 合并校验：Entity 行计数 > 5000
        entity_lines = sum(1 for line in open(merged, encoding="utf-8")
                           if "<Entity " in line and 'CardID="' in line)
        if entity_lines < 5000:
            raise ValueError(f"合并后实体行数异常: {entity_lines}")
    except Exception as exc:  # noqa: BLE001
        steps.append({"step": "merge", "ok": False,
                      "error": f"{type(exc).__name__}: {exc}"})
        return {"ok": False, "tag": tag, "steps": steps,
                "error": str(exc)}
    steps.append({"step": "merge", "ok": True, "merged": str(merged),
                  "sources": [str(p) for p in sources],
                  "entity_lines": entity_lines, "version": version})

    gen = generate_data(tag, root=root, merged=merged, version=version)
    steps.append({"step": "generate", **gen})
    if not gen["ok"]:
        return {"ok": False, "tag": tag, "steps": steps,
                "error": f"生成失败 rc={gen['rc']}"}

    old_xml = root / "hsdata" / "CardDefs.xml"
    if not old_xml.is_file():
        steps.append({"step": "diff", "ok": False,
                      "error": f"当前权威 XML 不存在: {old_xml}"})
        return {"ok": False, "tag": tag, "steps": steps,
                "error": "missing hsdata/CardDefs.xml"}
    try:
        diff = diff_official_data(old_xml, sources, tag=tag, root=root,
                                  out_prefix=TMP_SYNC / f"report_{tag}")
    except Exception as exc:  # noqa: BLE001
        steps.append({"step": "diff", "ok": False,
                      "error": f"{type(exc).__name__}: {exc}"})
        return {"ok": False, "tag": tag, "steps": steps,
                "error": str(exc)}
    steps.append({"step": "diff", "ok": True,
                  "json": str(TMP_SYNC / f"report_{tag}.json"),
                  "md": str(TMP_SYNC / f"report_{tag}.md"),
                  "bg_added": diff["bg_added_count"],
                  "bg_removed": diff["bg_removed_count"],
                  "value_change_total": diff["value_change_total"],
                  "new_tag_enum_ids": len(diff["new_tag_enum_ids"]),
                  "new_race_values": diff["new_race_values"],
                  "unknown_race_values": diff["unknown_race_values"]})
    # 可选: tag 枚举对比（有本地反编译枚举时）
    enums = root / "reversed" / "net" / "key_enums.json"
    enums2 = root / "reversed" / "net" / "Assembly-CSharp" / "enums.json"
    if enums.is_file() or enums2.is_file():
        run = run_command([sys.executable, TOOLS / "rea_tag_compare.py",
                           "--tags-py", root / "hsrl2" / "tags.py",
                           "--out", TMP_SYNC / f"tag_diff_{tag}.md",
                           "--json", TMP_SYNC / f"tag_diff_{tag}.json"],
                          cwd=str(root), timeout=600)
        steps.append({"step": "tag_compare", "ok": run["rc"] == 0,
                      "rc": run["rc"], "log_tail": run["stderr"][-400:]})
    else:
        steps.append({"step": "tag_compare", "ok": True,
                      "skipped": "无本地官方枚举（reversed/net）"})

    result = {"ok": True, "tag": tag, "version": version,
              "steps": steps,
              "generated_dir": gen["out_dir"],
              "generated_summary": gen["summary"],
              "diff": {k: diff[k] for k in (
                  "bg_added_count", "bg_removed_count",
                  "value_change_counts", "value_change_total",
                  "new_tag_enum_ids", "new_race_values",
                  "unknown_race_values", "race_changed_count",
                  "new_card_types", "generated_summary",
                  "current_summary")}}
    out = RUNS_DIR / f"dryrun_{tag}.json"
    _write_json(out, {"schema": "version_sync.dryrun.v1", **result})
    result["report"] = str(out)
    return result


def cmd_dry_run(args, *, signals: Optional[dict] = None) -> int:
    signals = signals or collect_signals(
        Path(args.root), offline=args.offline,
        product_db=args.product_db, build_override=args.build,
        project_patch_override=args.project_patch,
        target_tag_override=args.target_tag)
    decision = decide(signals)
    print_signals(signals, decision)
    if decision["status"] == "up-to-date":
        print("已是最新（目标 tag == 项目 build），dry-run 为 no-op。")
        return 0
    if decision["status"] == "waiting-for-hsdata":
        print("等待 HearthSim 发布对应数据 tag；dry-run 不执行。"
              "（可用 --target-tag 指定已有 tag 演练）")
        return 0
    if decision["status"] != "update-available" or not decision.get("target_tag"):
        print("无法确定目标 tag，dry-run 中止。")
        return 2
    result = prepare_update(decision["target_tag"], root=Path(args.root),
                            offline=args.offline)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("-" * 78)
        print("预演结果:", "OK" if result.get("ok") else "FAILED")
        for step in result.get("steps", []):
            name = step.get("step")
            ok = step.get("ok")
            extra = ""
            if name == "diff" and ok:
                extra = (f" 新增 {step['bg_added']} / 删除 {step['bg_removed']}"
                         f" / 数值变化 {step['value_change_total']}"
                         f" / 新 tag {step['new_tag_enum_ids']}"
                         f" / 新 race {step['new_race_values']}")
            print(f"  [{('ok' if ok else 'FAIL'):4s}] {name}{extra}")
        if result.get("ok"):
            print(f"  生成目录: {result['generated_dir']}")
            print(f"  差分报告: {TMP_SYNC / ('report_' + result['tag'] + '.md')}")
            print(f"  预演记录: {result['report']}")
            print("  注意: 未写 data/；确认无误后执行 "
                  "`--apply --yes`。")
        else:
            print(f"  错误: {result.get('error')}")
    return 0 if result.get("ok") else 3


# ══════════════════════ --apply ══════════════════════

def _copy_with_tracking(src: Path, dst: Path, created: List[Path]) -> None:
    if not dst.exists():
        created.append(dst)
    _ensure_dir(dst.parent)
    shutil.copy2(src, dst)


def _restore(backups: List[Tuple[Path, Path]],
             created: List[Path]) -> List[str]:
    restored: List[str] = []
    for src_backup, dst in backups:
        if Path(src_backup).is_file():
            _ensure_dir(Path(dst).parent)
            shutil.copy2(src_backup, dst)
            restored.append(str(dst))
    for path in created:
        try:
            if Path(path).is_file():
                Path(path).unlink()
        except OSError:
            pass
    return restored


def apply_update(target_tag: str, *, root: Path = ROOT,
                 run_tests: bool = True, run_smoke: bool = True,
                 offline: bool = False) -> dict:
    """备份 → 复制 → 更新 bg_summary → 回归/压测 →（失败自动回滚）。"""
    root = Path(root)
    global ROOT, TOOLS, RUNS_DIR, CACHE_DIR, TMP_SYNC  # noqa: PLW0603
    ROOT = root
    TOOLS = root / "tools"
    RUNS_DIR = root / "runs" / "version_sync"
    CACHE_DIR = RUNS_DIR / "cache"
    TMP_SYNC = root / "tmp_version_sync"
    _ensure_dir(RUNS_DIR)

    project = read_project_patch(root) or {}
    old_patch = project.get("patch")
    old_build = project.get("build")
    out_dir = TMP_SYNC / f"data_{target_tag}"
    if not (out_dir / "bg_summary.json").is_file():
        prep = prepare_update(target_tag, root=root, offline=offline)
        if not prep.get("ok"):
            return {"ok": False, "stage": "prepare", "error": prep.get("error"),
                    "steps": prep.get("steps")}
    new_patch = None
    try:
        new_patch = _load_json(out_dir / "bg_summary.json").get("patch")
    except (OSError, ValueError):
        new_patch = None
    if not new_patch:
        return {"ok": False, "stage": "prepare",
                "error": f"{out_dir}/bg_summary.json 缺失或无 patch"}
    if build_number(new_patch) == old_build:
        return {"ok": True, "noop": True,
                "reason": f"项目数据已是 build {old_build}（patch={old_patch}）",
                "target_tag": target_tag}

    backup_tag = str(old_build or old_patch or "old").replace(".", "_")
    data_backup = root / "data" / f"backup_{backup_tag}"
    hsdata_backup = root / "hsdata" / f"backup_{backup_tag}"
    _ensure_dir(data_backup)
    _ensure_dir(hsdata_backup)
    backups: List[Tuple[Path, Path]] = []
    created: List[Path] = []
    # 备份当前 data/ 生成产物
    for name in DATA_FILES:
        src = root / "data" / name
        if src.is_file():
            dst = data_backup / name
            if not dst.exists():
                shutil.copy2(src, dst)
            backups.append((dst, src))
    # 备份当前 hsdata 权威文件
    for name in ("CardDefs.xml", "RaceTagMap.xml", "README.md",
                 "VERSION_NOTE.md"):
        src = root / "hsdata" / name
        if src.is_file():
            dst = hsdata_backup / name
            if not dst.exists():
                shutil.copy2(src, dst)
            backups.append((dst, src))

    # 复制新数据
    for name in DATA_FILES:
        src = out_dir / name
        if src.is_file():
            _copy_with_tracking(src, root / "data" / name, created)
    # 复制新 hsdata（合并口径 + RaceTagMap + README + 版本说明）
    hdir = root / "reversed" / f"hsdata_{target_tag}"
    merged = TMP_SYNC / f"CardDefs.merged.{target_tag}.xml"
    version = read_hsdata_version(target_tag, root) or new_patch
    if merged.is_file():
        _copy_with_tracking(merged, root / "hsdata" / "CardDefs.xml", created)
    for name in ("RaceTagMap.xml", "README.md"):
        src = hdir / name
        if src.is_file():
            _copy_with_tracking(src, root / "hsdata" / name, created)
    client = read_client_build()
    revision = client.get("revision") if client else None
    note = (
        f"# hsdata 版本说明（tag {target_tag}）\n\n"
        f"- 本文件由 `tools/version_sync.py --apply --yes` 生成于 {now_iso()}\n"
        f"- 数据来源: HearthSim/hsdata tag `{target_tag}`"
        f"（CardDefs.xml"
        + (" + CardDefs.Bacon.xml" if (hdir / "CardDefs.Bacon.xml").is_file()
           else "") + " 合并口径）\n"
        f"- 项目 patch: `{new_patch}`（旧: `{old_patch}`）\n"
        f"- CardDefs build: `{version}`"
        + (f"（客户端完整版本 {version}.{revision}）"
           if revision and str(version).count(".") == 3 else "") + "\n"
        + "- 完整官方拆分文件: `reversed/hsdata_%s/`\n" % target_tag
    )
    note_path = root / "hsdata" / "VERSION_NOTE.md"
    if not note_path.exists():
        created.append(note_path)
    note_path.write_text(note, encoding="utf-8")

    # 显式更新 bg_summary.patch（生成器已写入，此处做契约校验）
    summary_path = root / "data" / "bg_summary.json"
    try:
        summary = _load_json(summary_path)
        summary["patch"] = new_patch
        _write_json(summary_path, summary)
    except (OSError, ValueError) as exc:
        _restore(backups, created)
        return {"ok": False, "stage": "update_summary",
                "error": f"{type(exc).__name__}: {exc}", "rolled_back": True}

    result: dict = {
        "schema": "version_sync.apply.v1",
        "applied_at": now_iso(),
        "target_tag": target_tag,
        "old_patch": old_patch,
        "new_patch": new_patch,
        "backup": {"data": str(data_backup),
                   "hsdata": str(hsdata_backup)},
        "files_copied": [str(p.relative_to(root)) for p in created],
        "tests": None, "smoke": None, "rolled_back": False,
    }
    if run_tests:
        run = run_command([sys.executable, "-m", "pytest",
                           "hsrl2/tests", "tests", "-q",
                           "-o", "addopts=", "-p", "no:cacheprovider"],
                          cwd=str(root), timeout=3600)
        log = RUNS_DIR / f"apply_{target_tag}_pytest.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(run["stdout"] + "\n[stderr]\n" + run["stderr"],
                       encoding="utf-8")
        result["tests"] = {"rc": run["rc"], "log": str(log),
                           "tail": (run["stdout"] or "").splitlines()[-3:]}
        if run["rc"] != 0:
            restored = _restore(backups, created)
            result.update(ok=False, stage="tests", rolled_back=True,
                          restored=restored)
            _write_json(RUNS_DIR / f"apply_{target_tag}.json", result)
            return result
    if run_smoke:
        run = run_command([sys.executable, root / "tools" /
                           "smoke_random_games.py", "--games", "4",
                           "--seed", "7"], cwd=str(root), timeout=1800)
        result["smoke"] = {"rc": run["rc"],
                           "tail": (run["stdout"] or "").splitlines()[-2:]}
        if run["rc"] != 0:
            restored = _restore(backups, created)
            result.update(ok=False, stage="smoke", rolled_back=True,
                          restored=restored)
            _write_json(RUNS_DIR / f"apply_{target_tag}.json", result)
            return result
    result["ok"] = True
    _write_json(RUNS_DIR / f"apply_{target_tag}.json", result)
    return result


def cmd_apply(args, *, signals: Optional[dict] = None) -> int:
    signals = signals or collect_signals(
        Path(args.root), offline=args.offline,
        product_db=args.product_db, build_override=args.build,
        project_patch_override=args.project_patch,
        target_tag_override=args.target_tag)
    decision = decide(signals)
    print_signals(signals, decision)
    target = decision.get("target_tag")
    if decision["status"] == "up-to-date":
        print("已是最新，apply 为 no-op（不写任何文件）。")
        return 0
    if decision["status"] != "update-available" or not target:
        print("当前状态不可应用（等待数据源/无法判定）。")
        return 2
    if not args.yes:
        print(f"[拒绝] --apply 会写 data/ 与 hsdata/ 并运行回归；"
              f"确认后加 --yes。目标 tag={target}")
        return 2
    result = apply_update(target, root=Path(args.root),
                          run_tests=not args.no_tests,
                          run_smoke=not args.no_smoke,
                          offline=args.offline)
    print("-" * 78)
    if result.get("ok"):
        if result.get("noop"):
            print("应用 no-op:", result.get("reason"))
        else:
            print(f"应用成功: {result['old_patch']} → {result['new_patch']}"
                  f"（tag {target}）")
            print(f"备份: {result['backup']}")
            print(f"pytest: rc={result['tests']['rc'] if result.get('tests') else 'skipped'}")
            print(f"结果文件: {Path(args.root) / 'runs' / 'version_sync' / ('apply_' + target + '.json')}")
        return 0
    print(f"应用失败（stage={result.get('stage')}），已回滚: "
          f"{result.get('rolled_back')}")
    if result.get("error"):
        print("错误:", result["error"])
    if result.get("tests"):
        print("pytest tail:", result["tests"].get("tail"))
    return 1


# ══════════════════════ CLI ══════════════════════

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="游戏版本 ↔ 项目数据 同步流水线（检查/预演/应用）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("用法")[-1][:1200])
    action = ap.add_mutually_exclusive_group(required=False)
    action.add_argument("--check", action="store_true",
                        help="只检查四信号并给结论（默认）")
    action.add_argument("--dry-run", action="store_true",
                        help="预演: 取数/合并/生成/差分（不写 data/）")
    action.add_argument("--apply", action="store_true",
                        help="应用: 备份→复制→回归（需 --yes）")
    ap.add_argument("--yes", action="store_true", help="--apply 的确认开关")
    ap.add_argument("--offline", action="store_true",
                    help="不联网（用缓存/本地 reversed 数据）")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    ap.add_argument("--no-tests", action="store_true", help="应用时跳过 pytest")
    ap.add_argument("--no-smoke", action="store_true", help="应用时跳过 smoke")
    ap.add_argument("--root", default=str(ROOT), help="仓库根（默认脚本上级）")
    ap.add_argument("--product-db", default=None, help=".product.db 路径覆盖")
    ap.add_argument("--build", default=None,
                    help="覆盖本机游戏 build 信号（模拟，如 37.1.0.260000）")
    ap.add_argument("--project-patch", default=None,
                    help="覆盖项目数据 patch 信号（模拟，如 36.2.2.249896）")
    ap.add_argument("--target-tag", default=None,
                    help="指定目标 hsdata tag（覆盖最新 tag；离线演练用）")
    return ap


def _utf8_stdio() -> None:
    """Windows 控制台默认 GBK：统一 stdout/stderr 为 UTF-8，避免中文/符号崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    _utf8_stdio()
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.apply and not args.yes:
        # 提前拒绝，避免误触；同时打印当前状态便于决策（退出码 2 = 被拒绝）
        print("[拒绝] --apply 需要 --yes 确认（会写 data/ 与 hsdata/）。")
        if not args.json:
            cmd_check(args)
        return 2
    if args.apply:
        return cmd_apply(args)
    if args.dry_run:
        return cmd_dry_run(args)
    return cmd_check(args)


if __name__ == "__main__":
    raise SystemExit(main())
