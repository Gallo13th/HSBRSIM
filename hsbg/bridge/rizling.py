"""rizling（AgenticAssistant 运营方）发行包版本跟踪 + 与本项目数据的对齐统计。

背景
----
`AgenticAssistant` 是第三方远程提示客户端（参考项目，不是本项目的依赖）。它的
发行包带三样对"版本跟踪"有用的东西：

1. `release-manifest.json`：客户端版本号、built 时间、`game_version`（规则/数据
   版本）、模块清单、文件哈希、`offline_smoke`；
2. `_internal/bgassistant/data/catalog.json`：线上卡池公共元数据快照，新版本
   （0.6.1）还带 atk/hp/armor/cost/text/pool 标记，可用来交叉校验本项目
   `data/*.json`；
3. `_internal/bgcontroller/data/game_tags.json`：python-hearthstone 的
   GameTag/CardType/Race/Zone 枚举，可与官方 `GAME_TAG` 枚举对照。

本模块只做**只读**解析/对比，**不执行发行包**、不联网、不读游戏内存；所有函数返回
JSON 可序列化的 dict，便于写入报告与测试断言。

注意：rizling 的 `game_version` 是其**自报**的规则版本；它未必跟随最新游戏补丁
（实测 0.6.1 仍写 `36.6.3.253932`，而本机游戏/本项目数据已是
`37.0.0.255130`）。它只能作为"参考信号"，不能当权威数据源。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .catalog import (
    AACatalog,
    DEFAULT_ENGINE_DATA_DIR,
    compare_with_engine_data,
    load_engine_cards,
    read_engine_patch,
)

# ── 默认路径（只读）─────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
#: 本仓库保存的 rizling 关键文件目录（由 `reversed/rizling_latest/` 提供）
RIZLING_DIR = ROOT / "reversed" / "rizling_latest"
#: 本地参考旧包（0.5.3）
LOCAL_AGENTIC_DIR = ROOT / "AgenticAssistant"
#: 只读的游戏安装目录（仅用于读 `.product.db`）
DEFAULT_GAME_DIR = Path(r"C:\Program Files (x86)\Hearthstone")
DEFAULT_PRODUCT_DB = DEFAULT_GAME_DIR / ".product.db"
#: 官方枚举提取物（rea-analyst 产物）
DEFAULT_OFFICIAL_ENUMS = ROOT / "reversed" / "net" / "Assembly-CSharp" / "enums.json"

#: 发行包内相对路径
RIZLING_MANIFEST_REL = "release-manifest.json"
RIZLING_README_REL = "使用说明.txt"
RIZLING_CATALOG_REL = "bgassistant/data/catalog.json"
RIZLING_GAME_TAGS_REL = "bgcontroller/data/game_tags.json"
#: 本地 0.5.3 包内相对路径（与上面相同，只是根目录不同）
LOCAL_CATALOG_REL = "_internal/bgassistant/data/catalog.json"
LOCAL_GAME_TAGS_REL = "_internal/bgcontroller/data/game_tags.json"

#: 版本号（3~5 段，按段解析）；`.product.db` 里是 `37.0.0.255130.254477`
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?")
#: 旧版《使用说明》末尾曾有"当前规则版本 36.6.3.253932"；新版删掉了这一行
README_RULE_VERSION_RE = re.compile(
    r"规则版本\s*[:：]?\s*(\d+(?:\.\d+){1,4})"
)
#: rizling `game_tags.json` 的枚举名 -> 官方提取物里的枚举名
OFFICIAL_ENUM_KEYS: Mapping[str, str] = {
    "GameTag": "GAME_TAG",
    "CardType": "TAG_CARDTYPE",
    "Race": "TAG_RACE",
    "Zone": "TAG_ZONE",
    "ChoiceType": "CHOICE_TYPE",
    "PlayState": "TAG_PLAYSTATE",
    "State": "TAG_STATE",
    "Step": "TAG_STEP",
}

TEXT_TAG_RE = re.compile(r"<[^>]+>")


# ══════════════════════════════════════════════════════════════════════
# 基础工具
# ══════════════════════════════════════════════════════════════════════


def sha256_file(path: Path | str, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_version(value: Any) -> Tuple[int, ...]:
    """把 ``37.0.0.255130.254477`` / ``0.6.1`` 等解析为整数元组。

    解析失败返回空元组（调用方自行决定是否视为 unknown）。
    """
    if isinstance(value, (tuple, list)):
        return tuple(int(x) for x in value)
    if value is None:
        return ()
    match = VERSION_RE.search(str(value))
    if not match:
        return ()
    parts = [int(g) for g in match.groups() if g is not None]
    return tuple(parts)


def compare_versions(a: Any, b: Any) -> int:
    """语义化比较两个版本串（逐段整数比较，缺段补 0）。"""
    va, vb = parse_version(a), parse_version(b)
    length = max(len(va), len(vb))
    va = va + (0,) * (length - len(va))
    vb = vb + (0,) * (length - len(vb))
    return (va > vb) - (va < vb)


def _load_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path | str, value: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return target


def write_json_report(path: Path | str, value: Any) -> Path:
    """把统计结果写成 UTF-8 JSON（公开辅助函数，供脚本/测试使用）。"""
    return _write_json(path, value)


def _sample(rows: Sequence[Any], limit: int = 20) -> List[Any]:
    return list(rows)[: max(0, int(limit))]


def _prefix(card_id: str) -> str:
    head = str(card_id).split("_", 1)[0]
    return "BGDUO" if head.startswith("BGDUO") else head


# ══════════════════════════════════════════════════════════════════════
# 1) 版本信号：游戏补丁 / rizling 自报版本 / hsdata tag
# ══════════════════════════════════════════════════════════════════════


def read_product_db(path: Optional[Path | str] = None) -> Optional[Dict[str, Any]]:
    """只读解析游戏目录 ``.product.db`` 里的版本号。

    Hearthstone 的 `.product.db` 是 protobuf 风格的二进制文件，其中直接包含
    ASCII 版本串（本机为 ``37.0.0.255130.254477``）。这里不做完整 protobuf
    解析，只在字节里正则匹配版本串，够用且不依赖第三方库。

    文件不存在时返回 ``None``（其它机器/未安装游戏时测试应 skip）。
    """
    target = Path(path or DEFAULT_PRODUCT_DB)
    if not target.is_file():
        return None
    data = target.read_bytes()
    match = VERSION_RE.search(data.decode("latin-1"))
    if not match:
        return None
    parts = [int(g) for g in match.groups() if g is not None]
    version4 = ".".join(str(p) for p in parts[:4])
    return {
        "path": str(target),
        "raw": match.group(0),
        "version": version4,
        "build": parts[3],
        "revision": parts[4] if len(parts) > 4 else None,
    }


def load_manifest(path_or_root: Path | str) -> Dict[str, Any]:
    """读取发行包 ``release-manifest.json``（传目录则自动拼文件名）。"""
    path = Path(path_or_root)
    if path.is_dir():
        path = path / RIZLING_MANIFEST_REL
    raw = _load_json(path)
    if not isinstance(raw, dict):
        raise ValueError(f"release-manifest 结构异常: {path}")
    return raw


def manifest_summary(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """提取 manifest 中与版本跟踪相关的字段。"""
    files = manifest.get("files") or {}
    return {
        "version": manifest.get("version"),
        "built": manifest.get("built"),
        "game_version": manifest.get("game_version"),
        "python_version": manifest.get("python_version"),
        "public_release": manifest.get("public_release"),
        "files_count": len(files) if isinstance(files, Mapping) else None,
        "client_sources": list(manifest.get("client_sources") or []),
        "bundled_project_modules": list(manifest.get("bundled_project_modules") or []),
        "offline_smoke": dict(manifest.get("offline_smoke") or {}),
        "contract_id": manifest.get("contract_id"),
    }


def read_readme_rule_version(root: Optional[Path | str] = None) -> Optional[str]:
    """从《使用说明》里提取"当前规则版本"。

    0.5.3 的说明里有 ``当前规则版本 36.6.3.253932 单人酒馆``；0.6.1 改版后
    删掉了这一行（版本只写在 manifest/catalog 里），因此返回 ``None``。
    """
    path = Path(root or RIZLING_DIR)
    if path.is_dir():
        path = path / RIZLING_README_REL
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    match = README_RULE_VERSION_RE.search(text)
    return match.group(1) if match else None


def catalog_meta(path: Path | str) -> Dict[str, Any]:
    """读取 catalog.json 的版本/规模/字段覆盖（不返回全部卡牌，避免超大返回值）。"""
    raw = _load_json(path)
    cards = raw.get("cards")
    if not isinstance(cards, list):
        raise ValueError(f"catalog 结构异常: {path}")
    fields: set = set()
    kinds: Dict[str, int] = {}
    solo_pool = 0
    stat_cards = 0
    for card in cards:
        if not isinstance(card, Mapping):
            continue
        fields.update(str(k) for k in card)
        kind = str(card.get("kind") or "")
        kinds[kind] = kinds.get(kind, 0) + 1
        if card.get("available_in_solo_pool"):
            solo_pool += 1
        if "atk" in card or "hp" in card:
            stat_cards += 1
    return {
        "path": str(Path(path)),
        "game_version": raw.get("game_version"),
        "pool_scope": raw.get("pool_scope"),
        "card_count": len(cards),
        "skin_count": len(raw.get("skins") or {}),
        "kind_counts": dict(sorted(kinds.items())),
        "fields": sorted(fields),
        "has_stats": "atk" in fields and "hp" in fields,
        "stat_cards": stat_cards,
        "solo_pool_count": solo_pool,
    }


def game_tags_meta(path: Path | str) -> Dict[str, Any]:
    """读取 game_tags.json 的枚举规模 + 文件哈希。"""
    raw = _load_json(path)
    enums = raw.get("enums")
    if not isinstance(enums, Mapping):
        raise ValueError(f"game_tags 结构异常: {path}")
    return {
        "path": str(Path(path)),
        "sha256": sha256_file(path),
        "source": raw.get("source"),
        "commit": raw.get("commit"),
        "enum_counts": {str(k): len(v) for k, v in enums.items() if isinstance(v, Mapping)},
    }


def package_summary(
    root: Optional[Path | str] = None,
    local_root: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """汇总一个 rizling 发行包（默认取 `reversed/rizling_latest/`）的版本信息。"""
    base = Path(root or RIZLING_DIR)
    manifest = manifest_summary(load_manifest(base))
    catalog = catalog_meta(base / RIZLING_CATALOG_REL)
    tags = game_tags_meta(base / RIZLING_GAME_TAGS_REL)
    summary: Dict[str, Any] = {
        "root": str(base),
        "manifest": manifest,
        "readme_rule_version": read_readme_rule_version(base),
        "catalog": catalog,
        "game_tags": tags,
        "rule_version_signal": {
            "manifest_game_version": manifest.get("game_version"),
            "catalog_game_version": catalog.get("game_version"),
            "readme_rule_version": read_readme_rule_version(base),
        },
    }
    local_base = Path(local_root or LOCAL_AGENTIC_DIR)
    if (local_base / RIZLING_MANIFEST_REL).is_file():
        try:
            local_manifest = manifest_summary(load_manifest(local_base))
            local_tags = game_tags_meta(local_base / LOCAL_GAME_TAGS_REL)
            local_catalog_path = local_base / LOCAL_CATALOG_REL
            local_catalog = (
                catalog_meta(local_catalog_path) if local_catalog_path.is_file() else None
            )
            new_effective = (
                manifest.get("game_version")
                or catalog.get("game_version")
            )
            local_effective = (
                local_manifest.get("game_version")
                or (local_catalog or {}).get("game_version")
            )
            summary["local_reference"] = {
                "root": str(local_base),
                "version": local_manifest.get("version"),
                "game_version": local_manifest.get("game_version"),
                "catalog": local_catalog,
                "game_tags_sha256": local_tags.get("sha256"),
            }
            summary["vs_local"] = {
                "version_cmp": compare_versions(
                    manifest.get("version"), local_manifest.get("version")
                ),
                "newer": compare_versions(
                    manifest.get("version"), local_manifest.get("version")
                )
                > 0,
                "version_newer": compare_versions(
                    manifest.get("version"), local_manifest.get("version")
                )
                > 0,
                "game_version_changed": new_effective != local_effective,
                "game_tags_identical": tags.get("sha256")
                == local_tags.get("sha256"),
            }
        except (OSError, ValueError):  # 参考旧包损坏不影响主分析
            summary["local_reference"] = None
    return summary


def detect_version_signals(
    *,
    project_data_dir: Optional[Path | str] = None,
    rizling_root: Optional[Path | str] = None,
    product_db: Optional[Path | str] = None,
    hsdata_root: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """汇总"游戏补丁 / 本项目数据 / rizling / hsdata"四个版本信号。

    返回 dict 里包含每个信号的原始值、两两是否一致，以及便于人读的 ``notes``。
    """
    project_patch = read_engine_patch(project_data_dir)
    rizling = package_summary(rizling_root) if Path(rizling_root or RIZLING_DIR).is_dir() else None
    product = read_product_db(product_db)
    rizling_game_version = (
        (rizling or {}).get("manifest", {}).get("game_version") if rizling else None
    )
    project_build = None
    if project_patch:
        parts = parse_version(project_patch)
        project_build = parts[3] if len(parts) > 3 else None
    product_build = (product or {}).get("build")

    # hsdata：reversed/hsdata_<tag>/source.json
    hsdata: Optional[Dict[str, Any]] = None
    hsroot = Path(hsdata_root or (ROOT / "reversed"))
    candidates = sorted(hsroot.glob("hsdata_*/source.json"))
    if candidates:
        # 优先选 build 与游戏/项目一致的快照，否则选文件名最大的
        chosen = candidates[-1]
        for path in candidates:
            try:
                raw = _load_json(path)
            except (OSError, ValueError):
                continue
            tag = str(raw.get("tag") or "")
            if (product_build and str(product_build) == tag) or (
                project_build and str(project_build) == tag
            ):
                chosen = path
                break
        try:
            raw = _load_json(chosen)
            hsdata = {"path": str(chosen), "tag": raw.get("tag"), "files": raw.get("files")}
        except (OSError, ValueError):
            hsdata = {"path": str(chosen), "tag": None, "files": None}

    checks: Dict[str, Any] = {
        "product_db_build": product_build,
        "project_data_build": project_build,
        "rizling_game_version": rizling_game_version,
        "hsdata_tag": (hsdata or {}).get("tag"),
    }
    checks["product_matches_project"] = bool(
        product_build and project_build and product_build == project_build
    )
    checks["rizling_matches_project"] = bool(
        rizling_game_version and project_patch and compare_versions(
            rizling_game_version, project_patch
        ) == 0
    )
    checks["hsdata_matches_project"] = bool(
        hsdata and (hsdata.get("tag") and project_build)
        and str(hsdata.get("tag")) == str(project_build)
    )
    notes: List[str] = []
    if checks["product_matches_project"]:
        notes.append(
            f"游戏补丁与项目数据一致：build {product_build} ({project_patch})"
        )
    elif product_build and project_build:
        notes.append(
            f"游戏补丁 build {product_build} 与项目数据 build {project_build} 不一致：需要升级数据"
        )
    if rizling_game_version and project_patch and not checks["rizling_matches_project"]:
        notes.append(
            f"rizling 自报 game_version={rizling_game_version}，"
            f"落后于本项目数据 {project_patch}；rizling 只能作参考信号"
        )
    return {
        "schema": "hsbg.version_signals.v1",
        "project": {"patch": project_patch, "build": project_build},
        "product_db": product,
        "rizling": {
            "version": (rizling or {}).get("manifest", {}).get("version"),
            "game_version": rizling_game_version,
            "rule_version_signal": (rizling or {}).get("rule_version_signal"),
        },
        "hsdata": hsdata,
        "checks": checks,
        "notes": notes,
    }


# ══════════════════════════════════════════════════════════════════════
# 2) 两个 rizling 包的差异（0.5.3 vs 0.6.1）
# ══════════════════════════════════════════════════════════════════════


def _load_catalog_cards(path: Path | str) -> Dict[str, Dict[str, Any]]:
    raw = _load_json(path)
    cards = raw.get("cards")
    if not isinstance(cards, list):
        raise ValueError(f"catalog 结构异常: {path}")
    return {str(c["id"]): dict(c) for c in cards if isinstance(c, Mapping) and c.get("id")}


def compare_catalogs(old_path: Path | str, new_path: Path | str) -> Dict[str, Any]:
    """比较两个 catalog.json：id/kind/字段集合/共享字段取值。"""
    old_raw = _load_json(old_path)
    new_raw = _load_json(new_path)
    old_cards = {str(c["id"]): dict(c) for c in old_raw.get("cards") or [] if c.get("id")}
    new_cards = {str(c["id"]): dict(c) for c in new_raw.get("cards") or [] if c.get("id")}
    old_ids, new_ids = set(old_cards), set(new_cards)
    shared_fields = sorted(
        set().union(*(c.keys() for c in old_cards.values())).intersection(
            set().union(*(c.keys() for c in new_cards.values()))
        )
    ) if old_cards and new_cards else []
    all_old_fields = set().union(*(c.keys() for c in old_cards.values())) if old_cards else set()
    all_new_fields = set().union(*(c.keys() for c in new_cards.values())) if new_cards else set()

    field_diffs: Dict[str, Dict[str, Any]] = {}
    for field in shared_fields:
        changed = [
            cid
            for cid in sorted(old_ids & new_ids)
            if old_cards[cid].get(field) != new_cards[cid].get(field)
        ]
        if changed:
            field_diffs[field] = {
                "count": len(changed),
                "ids": changed[:20],
            }

    def kind_counts(cards: Mapping[str, Mapping[str, Any]]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for card in cards.values():
            kind = str(card.get("kind") or "")
            out[kind] = out.get(kind, 0) + 1
        return dict(sorted(out.items()))

    return {
        "old_path": str(Path(old_path)),
        "new_path": str(Path(new_path)),
        "old_game_version": old_raw.get("game_version"),
        "new_game_version": new_raw.get("game_version"),
        "ids_identical": old_ids == new_ids,
        "old_card_count": len(old_ids),
        "new_card_count": len(new_ids),
        "only_old_ids": sorted(old_ids - new_ids)[:50],
        "only_new_ids": sorted(new_ids - old_ids)[:50],
        "old_kind_counts": kind_counts(old_cards),
        "new_kind_counts": kind_counts(new_cards),
        "fields_added": sorted(all_new_fields - all_old_fields),
        "fields_removed": sorted(all_old_fields - all_new_fields),
        "field_value_diffs": field_diffs,
        "skins_identical": (old_raw.get("skins") or {}) == (new_raw.get("skins") or {}),
    }


def compare_game_tags(path_a: Path | str, path_b: Path | str) -> Dict[str, Any]:
    """比较两个 game_tags.json：文件哈希、各枚举规模、GameTag 增删/取值差异。"""
    raw_a = _load_json(path_a)
    raw_b = _load_json(path_b)
    enums_a = raw_a.get("enums") or {}
    enums_b = raw_b.get("enums") or {}
    sha_a = sha256_file(path_a)
    sha_b = sha256_file(path_b)
    out: Dict[str, Any] = {
        "path_a": str(Path(path_a)),
        "path_b": str(Path(path_b)),
        "sha_a": sha_a,
        "sha_b": sha_b,
        "identical": sha_a == sha_b,
        "enum_counts_a": {str(k): len(v) for k, v in enums_a.items() if isinstance(v, Mapping)},
        "enum_counts_b": {str(k): len(v) for k, v in enums_b.items() if isinstance(v, Mapping)},
    }
    tag_a = enums_a.get("GameTag") or {}
    tag_b = enums_b.get("GameTag") or {}
    if isinstance(tag_a, Mapping) and isinstance(tag_b, Mapping):
        names_a, names_b = set(tag_a), set(tag_b)
        common = names_a & names_b
        out["game_tag"] = {
            "count_a": len(names_a),
            "count_b": len(names_b),
            "common": len(common),
            "added": sorted(names_b - names_a)[:50],
            "removed": sorted(names_a - names_b)[:50],
            "value_mismatches": [
                {"name": n, "a": tag_a[n], "b": tag_b[n]}
                for n in sorted(common)
                if tag_a[n] != tag_b[n]
            ][:50],
            "value_mismatch_count": sum(
                1 for n in common if tag_a[n] != tag_b[n]
            ),
        }
    return out


def compare_packages(
    local_root: Optional[Path | str] = None,
    new_root: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """比较两个完整发行包（默认 0.5.3 → 0.6.1）的版本/模块/数据差异。"""
    old_base = Path(local_root or LOCAL_AGENTIC_DIR)
    new_base = Path(new_root or RIZLING_DIR)
    old_manifest = manifest_summary(load_manifest(old_base))
    new_manifest = manifest_summary(load_manifest(new_base))

    def added(old: Iterable[str], new: Iterable[str]) -> List[str]:
        return sorted(set(new) - set(old))

    old_modules = old_manifest.get("bundled_project_modules") or []
    new_modules = new_manifest.get("bundled_project_modules") or []
    old_sources = old_manifest.get("client_sources") or []
    new_sources = new_manifest.get("client_sources") or []

    result: Dict[str, Any] = {
        "schema": "hsbg.rizling_package_diff.v1",
        "old": {
            "root": str(old_base),
            "version": old_manifest.get("version"),
            "built": old_manifest.get("built"),
            "game_version": old_manifest.get("game_version"),
        },
        "new": {
            "root": str(new_base),
            "version": new_manifest.get("version"),
            "built": new_manifest.get("built"),
            "game_version": new_manifest.get("game_version"),
        },
        "version_changed": old_manifest.get("version") != new_manifest.get("version"),
        "version_newer": compare_versions(
            new_manifest.get("version"), old_manifest.get("version")
        )
        > 0,
        "game_version_changed": old_manifest.get("game_version")
        != new_manifest.get("game_version"),
        "old_readme_rule_version": read_readme_rule_version(old_base),
        "new_readme_rule_version": read_readme_rule_version(new_base),
        "modules_added": added(old_modules, new_modules),
        "modules_removed": added(new_modules, old_modules),
        "client_sources_added": added(old_sources, new_sources),
        "client_sources_removed": added(new_sources, old_sources),
        "offline_smoke_old": old_manifest.get("offline_smoke"),
        "offline_smoke_new": new_manifest.get("offline_smoke"),
        "files_count_old": old_manifest.get("files_count"),
        "files_count_new": new_manifest.get("files_count"),
    }
    try:
        result["catalog"] = compare_catalogs(
            old_base / LOCAL_CATALOG_REL, new_base / RIZLING_CATALOG_REL
        )
    except (OSError, ValueError) as exc:  # pragma: no cover - 文件缺失时保留说明
        result["catalog"] = {"error": f"{type(exc).__name__}: {exc}"}
    # 0.5.3 的 manifest 没有 game_version 字段（只写在 catalog/说明里），
    # 因此"有效规则版本"取 manifest 优先、catalog 兜底再比较。
    catalog_diff = result.get("catalog") or {}
    old_effective = old_manifest.get("game_version") or catalog_diff.get("old_game_version")
    new_effective = new_manifest.get("game_version") or catalog_diff.get("new_game_version")
    result["old"]["game_version_effective"] = old_effective
    result["new"]["game_version_effective"] = new_effective
    result["game_version_changed"] = old_effective != new_effective
    try:
        result["game_tags"] = compare_game_tags(
            old_base / LOCAL_GAME_TAGS_REL, new_base / RIZLING_GAME_TAGS_REL
        )
    except (OSError, ValueError) as exc:  # pragma: no cover
        result["game_tags"] = {"error": f"{type(exc).__name__}: {exc}"}
    return result


# ══════════════════════════════════════════════════════════════════════
# 3) game_tags 与官方 GAME_TAG 枚举对照
# ══════════════════════════════════════════════════════════════════════


def compare_game_tags_with_official(
    game_tags_path: Optional[Path | str] = None,
    official_enums_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """把 rizling 的枚举与官方程序集提取的枚举逐项对照。

    官方枚举来自 `reversed/net/Assembly-CSharp/enums.json`（rea-analyst 用
    Mono.Cecil 从 `Assembly-CSharp.dll` 提取）。rizling 的 `game_tags.json`
    来自 python-hearthstone，因此会有"别名/旧名"差异——重点看**同名是否同值**。
    """
    tags_path = Path(game_tags_path or (RIZLING_DIR / RIZLING_GAME_TAGS_REL))
    official_path = Path(official_enums_path or DEFAULT_OFFICIAL_ENUMS)
    raw = _load_json(tags_path)
    official = _load_json(official_path)
    rizling_enums = raw.get("enums") or {}
    out: Dict[str, Any] = {
        "schema": "hsbg.tag_enum_compare.v1",
        "rizling_tags_path": str(tags_path),
        "official_enums_path": str(official_path),
        "rizling_commit": raw.get("commit"),
        "enums": {},
    }
    for riz_key, official_key in OFFICIAL_ENUM_KEYS.items():
        riz = rizling_enums.get(riz_key)
        off_entry = official.get(official_key)
        if not isinstance(riz, Mapping) or not isinstance(off_entry, Mapping):
            continue
        off = off_entry.get("values")
        if not isinstance(off, Mapping):
            continue
        common = set(off) & set(riz)
        mismatches = [
            {"name": n, "official": off[n], "rizling": riz[n]}
            for n in sorted(common)
            if off[n] != riz[n]
        ]
        out["enums"][riz_key] = {
            "official_count": len(off),
            "rizling_count": len(riz),
            "common": len(common),
            "value_mismatch_count": len(mismatches),
            "value_mismatches": mismatches[:50],
            "official_only": sorted(set(off) - set(riz))[:80],
            "official_only_count": len(set(off) - set(riz)),
            "rizling_only": sorted(set(riz) - set(off))[:80],
            "rizling_only_count": len(set(riz) - set(off)),
        }
    return out


# ══════════════════════════════════════════════════════════════════════
# 4) rizling catalog ↔ 本项目 data/ 对齐
# ══════════════════════════════════════════════════════════════════════


def _normalize_text(text: Any) -> str:
    value = TEXT_TAG_RE.sub("", str(text or ""))
    value = value.replace("[x]", "").replace("_", "").replace("\n", " ")
    return re.sub(r"\s+", " ", value).strip().casefold()


def _engine_raw_ids(data_dir: Path) -> set:
    """项目 data/ 目录下所有生成 JSON 里的原始 id（含 `_G` 金色变体）。"""
    ids: set = set()
    for path in sorted(data_dir.glob("bg_*.json")):
        if path.name == "bg_summary.json":
            continue
        try:
            data = _load_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(data, list):
            continue
        for row in data:
            if isinstance(row, Mapping) and row.get("id"):
                ids.add(str(row["id"]))
    return ids


def _load_pool_ids(data_dir: Path, filename: str) -> set:
    path = data_dir / filename
    if not path.is_file():
        return set()
    raw = _load_json(path)
    if not isinstance(raw, list):
        return set()
    return {str(x["id"]) for x in raw if isinstance(x, Mapping) and x.get("id")}


def compare_catalog_with_project(
    catalog_path: Optional[Path | str] = None,
    data_dir: Optional[Path | str] = None,
    *,
    sample_limit: int = 20,
) -> Dict[str, Any]:
    """rizling catalog（自报规则版本）↔ 本项目 `data/`（当前生成数据）对齐统计。

    覆盖：id 覆盖、按 kind 缺失、数值（atk/hp/cost/armor）、文本（规范化后）、
    金色变体指向、卡池标记。注意 catalog 的 `cost` 对酒馆随从是**印刷费用**
    （通常 0），与引擎的"商店购买价"不是一个口径——数值对比只对法术/饰品/
    英雄技能等有印刷费用的类型比较 cost，随从只比 atk/hp。
    """
    cat = AACatalog(catalog_path or (RIZLING_DIR / RIZLING_CATALOG_REL))
    engine, engine_files, engine_raw_union = load_engine_cards(
        data_dir, canonical_map={c.id: c.normal for c in cat.cards if c.normal}
    )
    cat_cards = cat.canonical_cards
    engine_ids = set(engine)
    common = sorted(set(cat_cards) & engine_ids)
    only_catalog = sorted(set(cat_cards) - engine_ids)
    only_engine = sorted(engine_ids - set(cat_cards))

    base = compare_with_engine_data(
        data_dir=data_dir,
        catalog_path=catalog_path or (RIZLING_DIR / RIZLING_CATALOG_REL),
        include_timestamp=False,
    )

    # ── 数值差异 ──
    numeric_rows: List[Dict[str, Any]] = []
    for cid in common:
        card = cat_cards[cid]
        row = engine[cid]
        kind = card.kind
        reference = bool(card.raw.get("is_reference_only"))
        pairs: List[Tuple[str, Any, Any]] = []
        if kind == "minion":
            pairs = [("atk", card.raw.get("atk"), row.get("atk")),
                     ("hp", card.raw.get("hp"), row.get("health"))]
        elif kind == "hero":
            pairs = [("hp", card.raw.get("hp"), row.get("health")),
                     ("armor", card.raw.get("armor"), row.get("armor"))]
        elif kind in ("spell", "tavern_spell", "trinket_lesser", "trinket_greater",
                      "hero_power"):
            c_cost = card.raw.get("cost")
            if isinstance(c_cost, int) and c_cost > 0:
                pairs = [("cost", c_cost, row.get("cost"))]
        for field_name, cv, ev in pairs:
            if isinstance(cv, int) and isinstance(ev, int) and cv != ev:
                numeric_rows.append(
                    {
                        "id": cid,
                        "kind": kind,
                        "field": field_name,
                        "catalog": cv,
                        "engine": ev,
                        "reference_only": reference,
                    }
                )
    reference_diffs = sum(1 for r in numeric_rows if r["reference_only"])
    numeric = {
        "checked_cards": len(common),
        "count": len(numeric_rows),
        "by_field": dict(
            sorted(
                {
                    f: sum(1 for r in numeric_rows if r["field"] == f)
                    for f in {r["field"] for r in numeric_rows}
                }.items()
            )
        ),
        "reference_only_count": reference_diffs,
        "non_reference_count": len(numeric_rows) - reference_diffs,
        "samples": _sample(numeric_rows, sample_limit),
        "notes": [
            "catalog 的 cost 对酒馆随从是印刷费用（通常 0），与商店购买价口径不同；"
            "随从只比较 atk/hp，cost 只对法术/饰品/英雄技能比较。",
            "is_reference_only=true 的是构造/历史引用卡（非当前酒馆池），其 BG "
            "CardDefs 覆盖值与卡面印刷值可能不同，不应算作本项目数据错误。",
        ],
    }

    # ── 文本（规范化后）──
    text_equal = text_diff = 0
    text_samples: List[Dict[str, Any]] = []
    for cid in common:
        a = _normalize_text(cat_cards[cid].raw.get("text"))
        b = _normalize_text(engine[cid].get("text"))
        if not a or not b:
            continue
        if a == b:
            text_equal += 1
        else:
            text_diff += 1
            if len(text_samples) < sample_limit:
                text_samples.append(
                    {
                        "id": cid,
                        "catalog": cat_cards[cid].raw.get("text"),
                        "engine": engine[cid].get("text"),
                    }
                )
    text = {
        "compared": text_equal + text_diff,
        "equal": text_equal,
        "diff": text_diff,
        "samples": text_samples,
        "notes": [
            "catalog 文本是面向展示的'已替换值'版本（+1/+1、@ 计数等），"
            "引擎 text 是 CardDefs 原始模板（+{0}/+{1}、[x] 标记），"
            "规范化后仍有差异属预期；文本不能作为一致性判据，数值/枚举才是。",
        ],
    }

    # ── 金色变体指向 ──
    raw_ids = _engine_raw_ids(Path(data_dir or DEFAULT_ENGINE_DATA_DIR))
    missing_golden = [
        card.raw.get("golden")
        for card in cat.cards
        if card.raw.get("golden") and str(card.raw["golden"]) not in raw_ids
    ]
    golden_prefix: Dict[str, int] = {}
    for gid in missing_golden:
        prefix = _prefix(gid)
        golden_prefix[prefix] = golden_prefix.get(prefix, 0) + 1
    golden = {
        "catalog_golden_links": sum(1 for c in cat.cards if c.raw.get("golden")),
        "engine_missing": len(missing_golden),
        "engine_missing_by_prefix": dict(sorted(golden_prefix.items())),
        "samples": sorted(missing_golden)[:sample_limit],
        "notes": [
            "缺失集中在 BGDUO/TB 前缀：单人模式数据不含双人卡，属预期。",
        ],
    }

    # ── 卡池标记 ──
    pools = pool_alignment(cat, data_dir)
    bg36_ids = sorted(cid for cid in cat_cards if cid.startswith("BG36"))
    bg36 = {
        "catalog_canonical": len(bg36_ids),
        "matched": len([cid for cid in bg36_ids if cid in engine_ids]),
        "missing": sorted(cid for cid in bg36_ids if cid not in engine_ids),
    }

    return {
        "schema": "hsbg.rizling_catalog_alignment.v1",
        "catalog": {
            "path": str(cat.path),
            "game_version": cat.version,
            "card_count": cat.card_count,
            "canonical_count": len(cat_cards),
            "skin_count": len(cat.skins),
        },
        "project": {
            "data_dir": str(Path(data_dir or DEFAULT_ENGINE_DATA_DIR)),
            "patch": read_engine_patch(data_dir),
            "file_counts": dict(sorted(engine_files.items())),
            "raw_union": engine_raw_union,
            "canonical_count": len(engine_ids),
        },
        "ids": {
            "intersection": len(common),
            "only_catalog": len(only_catalog),
            "only_engine": len(only_engine),
            "only_catalog_by_prefix": dict(
                sorted(
                    {
                        p: sum(1 for i in only_catalog if _prefix(i) == p)
                        for p in {_prefix(i) for i in only_catalog}
                    }.items()
                )
            ),
            "only_catalog_ids": only_catalog,
            "only_engine_ids": only_engine,
            "coverage": round(len(common) / len(cat_cards), 4) if cat_cards else 0.0,
        },
        "by_kind": base.get("by_kind", {}),
        "bg36": bg36,
        "numeric": numeric,
        "text": text,
        "golden": golden,
        "pools": pools,
        "base_field_diffs": base.get("field_diffs", {}),
        "notes": [
            "rizling catalog 是它自报 game_version 的快照；若落后于项目数据，"
            "only_catalog/only_engine 与卡池差异反映的是**两个版本之间**的差，"
            "不能直接当成项目数据错误。",
            "真正的数据一致性验收以官方 CardDefs（build tag）为准；rizling 只做"
            "版本信号与公共元数据交叉校验。",
        ],
    }


def pool_alignment(
    catalog: Optional[AACatalog] = None,
    data_dir: Optional[Path | str] = None,
    *,
    sample_limit: int = 20,
) -> Dict[str, Any]:
    """rizling catalog 的 solo-pool 标记 ↔ 本项目池文件（minion/spell/hero）。"""
    cat = catalog or AACatalog(RIZLING_DIR / RIZLING_CATALOG_REL)
    root = Path(data_dir or DEFAULT_ENGINE_DATA_DIR)
    solo: Dict[str, set] = {}
    for card in cat.cards:
        if not card.raw.get("available_in_solo_pool"):
            continue
        solo.setdefault(card.kind, set()).add(card.id)

    project_pools = {
        "minion": _load_pool_ids(root, "bg_pool_minions.json"),
        "tavern_spell": _load_pool_ids(root, "bg_pool_spells.json"),
        "hero": _load_pool_ids(root, "bg_heroes.json"),
    }
    out: Dict[str, Any] = {
        "catalog_pool_scope": _load_json(cat.path).get("pool_scope"),
        "kinds": {},
        "trinkets": {
            "catalog_solo_selection": len(solo.get("trinket_lesser", set()))
            + len(solo.get("trinket_greater", set())),
            "project_bg_trinkets": len(_load_pool_ids(root, "bg_trinkets.json")),
            "note": "catalog 的库存池是'可被饰品选择'的子集，项目 bg_trinkets.json "
                    "是全部饰品定义；两者口径不同，只记录不做法判。",
        },
    }
    for kind, filename in (
        ("minion", "bg_pool_minions.json"),
        ("tavern_spell", "bg_pool_spells.json"),
        ("hero", "bg_heroes.json"),
    ):
        catalog_ids = solo.get(kind, set())
        project_ids = project_pools[kind]
        out["kinds"][kind] = {
            "catalog": len(catalog_ids),
            "project": len(project_ids),
            "intersection": len(catalog_ids & project_ids),
            "catalog_only": sorted(catalog_ids - project_ids)[:sample_limit],
            "catalog_only_count": len(catalog_ids - project_ids),
            "project_only": sorted(project_ids - catalog_ids)[:sample_limit],
            "project_only_count": len(project_ids - catalog_ids),
        }
    return out


# ══════════════════════════════════════════════════════════════════════
# CLI（默认只打印；`diff` 会写报告文件）
# ══════════════════════════════════════════════════════════════════════


def _default_out_dir() -> Path:
    return RIZLING_DIR


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="rizling 发行包版本跟踪 / 与本项目数据对齐（只读）"
    )
    sub = parser.add_subparsers(dest="command")
    p_sum = sub.add_parser("summary", help="打印版本信号 + 包概况")
    p_sum.add_argument("--rizling-root", default=str(RIZLING_DIR))
    p_sum.add_argument("--product-db", default=None)

    p_diff = sub.add_parser("diff", help="生成 0.5.3→0.6.1 与 0.6.1↔项目数据 报告")
    p_diff.add_argument("--rizling-root", default=str(RIZLING_DIR))
    p_diff.add_argument("--local-root", default=str(LOCAL_AGENTIC_DIR))
    p_diff.add_argument("--data-dir", default=None)
    p_diff.add_argument("--out-dir", default=str(_default_out_dir()))

    args = parser.parse_args(argv)
    if args.command in (None, "summary"):
        signals = detect_version_signals(
            rizling_root=args.rizling_root if args.command else None,
            product_db=args.product_db if args.command else None,
        )
        print(json.dumps(signals, ensure_ascii=False, indent=1))
        return 0
    if args.command == "diff":
        out_dir = Path(args.out_dir)
        package_diff = compare_packages(args.local_root, args.rizling_root)
        alignment = compare_catalog_with_project(
            Path(args.rizling_root) / RIZLING_CATALOG_REL, args.data_dir
        )
        write_json_report(out_dir / "diff_061_vs_053.json", package_diff)
        write_json_report(out_dir / "diff_vs_project.json", alignment)
        print(json.dumps(
            {
                "package": {
                    "old": package_diff["old"],
                    "new": package_diff["new"],
                    "version_newer": package_diff["version_newer"],
                    "game_version_changed": package_diff["game_version_changed"],
                    "modules_added": package_diff["modules_added"],
                    "catalog_ids_identical": package_diff.get("catalog", {}).get("ids_identical"),
                    "game_tags_identical": package_diff.get("game_tags", {}).get("identical"),
                },
                "alignment": {
                    "catalog_version": alignment["catalog"]["game_version"],
                    "project_patch": alignment["project"]["patch"],
                    "ids": {
                        k: alignment["ids"][k]
                        for k in ("intersection", "only_catalog", "only_engine")
                    },
                    "bg36": alignment["bg36"],
                    "numeric": {
                        k: alignment["numeric"][k]
                        for k in ("count", "reference_only_count",
                                  "non_reference_count")
                    },
                    "pools": {
                        k: {kk: v[kk] for kk in ("catalog", "project", "intersection")}
                        for k, v in alignment["pools"]["kinds"].items()
                    },
                },
            },
            ensure_ascii=False,
            indent=1,
        ))
        print(f"written: {out_dir / 'diff_061_vs_053.json'}")
        print(f"written: {out_dir / 'diff_vs_project.json'}")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
