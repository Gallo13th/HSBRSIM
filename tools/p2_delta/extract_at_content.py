#!/usr/bin/env python3
"""抽取 AutoTavern（TavernGym 1.0.0 / 客户端 36.6.3.253932）content 脚本注册表。

上游每个 ``crates/taverngym/src/content/<module>.rs`` 暴露
``pub fn scripts() -> Vec<(&'static str, Script)>``，``content/mod.rs::all_scripts()``
把 54 个模块的脚本拼成完整注册表（``script.rs::registry()`` 逐个 ``db().id(id)``，
重复/未知 id 直接 panic）。本脚本**静态解析 Rust 源码**抽取：

  * 每个模块注册的 card id（按文件归类）；
  * 每个脚本用到的 hook / flag / TargetSpec / 监听事件（用于“AT 最接近可复用脚本”；
  * 以及按上游 ``examples/content_report.rs`` 同款口径算出的分 kind 覆盖数。

之所以不复用 ``docs/CONTENT.md``：它是生成快照，本脚本要求可从源码**重算**，
并用 CONTENT.md 的数字做交叉校验（见 ``--check-content-md``）。

用法::

    python3 tools/p2_delta/extract_at_content.py \\
        --at-root /Users/letiangao/HSAgent/repos/AutoTavern \\
        --out runs/p2_delta/at_content.json

输出确定性（无时间戳、固定排序），重复运行逐字节一致。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as C  # noqa: E402

# ── Rust 词法辅助 ────────────────────────────────────────────────────
FUNC_SCRIPTS_RE = re.compile(
    r"pub fn scripts(?:_p\d+)?\s*\(\s*\)\s*->\s*Vec<\(&\s*'static\s*str\s*,\s*Script\)>\s*\{"
)

#: 模块级字符串常量：``const NAME: &str = "BGxx";``
STR_CONST_RE = re.compile(
    r"(?:pub\s+)?const\s+(?P<name>[A-Z_][A-Z0-9_]*)\s*:\s*&\s*(?:'static\s+)?str\s*=\s*\"(?P<val>[A-Za-z][A-Za-z0-9_]*)\"\s*;"
)
#: 模块级字符串数组常量：``const NAME: [&str; N] = ["a", "b"];``
STR_ARRAY_RE = re.compile(
    r"(?:pub\s+)?const\s+(?P<name>[A-Z_][A-Z0-9_]*)\s*:\s*\[\s*&\s*(?:'static\s+)?str\s*;\s*(?P<n>\d+)\s*\]\s*=\s*\[(?P<body>[^\]]*)\]\s*;",
    re.S,
)
STR_LITERAL_RE = re.compile(r'"([A-Za-z][A-Za-z0-9_]*)"')


def parse_consts(src: str) -> Dict[str, Any]:
    """解析源码里的模块级卡 id 常量（标量与定长数组）。"""
    consts: Dict[str, Any] = {}
    for m in STR_CONST_RE.finditer(src):
        consts[m.group("name")] = m.group("val")
    for m in STR_ARRAY_RE.finditer(src):
        vals = STR_LITERAL_RE.findall(m.group("body"))
        if len(vals) == int(m.group("n")):
            consts[m.group("name")] = vals
    return consts


def resolve_entry_id(expr: str, consts: Dict[str, Any]) -> Optional[str]:
    """把 vec 条目首元素表达式解析成 card id（字面量 / 常量 / 数组下标）。"""
    expr = re.sub(r"//[^\n]*", "", expr).strip()
    m = re.fullmatch(r'"([A-Za-z][A-Za-z0-9_]*)"', expr)
    if m:
        return m.group(1)
    m = re.fullmatch(r"([A-Z_][A-Z0-9_]*)", expr)
    if m:
        v = consts.get(m.group(1))
        return v if isinstance(v, str) else None
    m = re.fullmatch(r"([A-Z_][A-Z0-9_]*)\s*\[\s*(\d+)\s*\]", expr)
    if m:
        v = consts.get(m.group(1))
        idx = int(m.group(2))
        if isinstance(v, list) and idx < len(v):
            return v[idx]
    return None

#: Script 结构体字段 → 归一化 hook 名（取值 Some(...) 才算）
HOOK_FIELDS = {
    "battlecry": "battlecry",
    "choose_one": "choose_one",  # bool=true
    "deathrattle": "deathrattle",
    "start_of_combat": "start_of_combat",
    "rally": "rally",
    "avenge": "avenge",
    "on_sell": "on_sell",
    "hand_start_of_combat": "hand_start_of_combat",
    "start_of_turn": "start_of_turn",
    "end_of_turn": "end_of_turn",
    "activate": "activate",
    "persistent_event": "persistent_event",
    "on_fill_shop": "on_fill_shop",
    "on_event": "on_event",
    "on_attach": "on_attach",
    "spell": "spell",
    "hero_power": "hero_power",
    "scheduled": "scheduled",
    "on_create": "on_create",
    "on_merge": "on_merge",
    "discover_pick": "discover_pick",
    "after_attack": "after_attack",
    "on_stats": "on_stats",
    "followup": "followup",
    "offer_ok": "offer_ok",
    "shown": "shown",
}

FLAG_RE = re.compile(r"flag::([A-Z_]+)")
EV_RE = re.compile(r"ev::([A-Z_]+)")
TARGET_RE = re.compile(r"TargetSpec::([A-Za-z]+)")
INNATE_RE = re.compile(r"innate\s*:\s*Kw::([A-Z_]+)")
HP_USES_RE = re.compile(r"hero_power_uses\s*:\s*(\d+)")
KW_RE = re.compile(r"Kw::([A-Z_]+)")


def _skip_line_comment(src: str, i: int) -> int:
    j = src.find("\n", i)
    return len(src) if j < 0 else j + 1


def _skip_block_comment(src: str, i: int) -> int:
    depth = 1
    j = i + 2
    while j < len(src) and depth:
        if src.startswith("/*", j):
            depth += 1
            j += 2
        elif src.startswith("*/", j):
            depth -= 1
            j += 2
        else:
            j += 1
    return j


def _skip_string(src: str, i: int) -> Tuple[int, Optional[str]]:
    """i 指向开引号；返回 (结束位置, 字符串内容)。处理 Rust 原始字符串与转义。"""
    assert src[i] == '"'
    j = i + 1
    buf: List[str] = []
    while j < len(src):
        ch = src[j]
        if ch == "\\" and j + 1 < len(src):
            buf.append(src[j + 1])
            j += 2
            continue
        if ch == '"':
            return j + 1, "".join(buf)
        buf.append(ch)
        j += 1
    return j, "".join(buf)


def _fn_body(src: str, start: int) -> str:
    """从函数签名的 ``{`` 处截出配平的花括号体（跳过字符串/注释）。"""
    brace = src.find("{", start)
    if brace < 0:
        return ""
    depth = 0
    i = brace
    while i < len(src):
        ch = src[i]
        if ch == "/" and src.startswith("//", i):
            i = _skip_line_comment(src, i)
            continue
        if ch == "/" and src.startswith("/*", i):
            i = _skip_block_comment(src, i)
            continue
        if ch == '"':
            i, _ = _skip_string(src, i)
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[brace + 1 : i]
        i += 1
    return src[brace + 1 :]


def parse_scripts_fn(body: str, consts: Dict[str, Any]) -> Tuple[List[Tuple[str, str]], List[str]]:
    """解析 ``scripts()`` 函数体里的 vec 条目。

    返回 ``(entries, warnings)``；entry = (card_id, 该条目源码片段)。
    条目形态：``( "ID", Script { ... } ),`` / ``( "ID", E ),``，首元素也允许是
    模块常量或常量数组下标（如 ``ELEMENTS[0]``、``FODDER``）。
    """
    entries: List[Tuple[str, str]] = []
    warnings: List[str] = []
    stack: List[str] = []
    i = 0
    n = len(body)
    entry_start = -1
    entry_comma = -1
    while i < n:
        ch = body[i]
        if ch == "/" and body.startswith("//", i):
            i = _skip_line_comment(body, i)
            continue
        if ch == "/" and body.startswith("/*", i):
            i = _skip_block_comment(body, i)
            continue
        if ch == '"':
            i, _ = _skip_string(body, i)
            continue
        if ch == "(":
            if stack == ["["] and entry_start < 0:
                entry_start = i
                entry_comma = -1
            stack.append("(")
        elif ch == "[":
            stack.append("[")
        elif ch == "{":
            stack.append("{")
        elif ch in ")]}":
            if stack:
                stack.pop()
            if ch == ")" and stack == ["["] and entry_start >= 0:
                snippet = body[entry_start : i + 1]
                expr = body[entry_start + 1 : entry_comma] if entry_comma > 0 else ""
                cid = resolve_entry_id(expr, consts)
                if cid is None:
                    warnings.append(f"无法解析的 vec 条目: {snippet[:120]!r}")
                else:
                    entries.append((cid, snippet))
                entry_start = -1
                entry_comma = -1
        elif ch == "," and stack == ["[", "("] and entry_start >= 0 and entry_comma < 0:
            entry_comma = i
        i += 1
    # 动态注册：`for id in ["A", "B"] { v.push((id, power_of())) }`
    seen = {cid for cid, _ in entries}
    for m in re.finditer(r"for\s+(\w+)\s+in\s+\[(.*?)\]\s*\{", body, re.S):
        var = m.group(1)
        items = STR_LITERAL_RE.findall(m.group(2))
        tail = body[m.end() : m.end() + 400]
        if not re.search(rf"v\.push\(\s*\(\s*{re.escape(var)}\s*,", tail):
            continue
        for cid in items:
            if cid not in seen:
                entries.append((cid, tail[:200]))
                seen.add(cid)
    return entries, warnings


def hooks_of(entry_src: str) -> Dict[str, Any]:
    """从脚本条目源码抽取 hook/flag/target 使用情况。"""
    hooks: List[str] = []
    for field, name in HOOK_FIELDS.items():
        if field == "choose_one":
            if re.search(r"\bchoose_one\s*:\s*true", entry_src):
                hooks.append(name)
            continue
        if re.search(rf"\b{field}\s*:\s*Some", entry_src):
            hooks.append(name)
    if re.search(r"\blistens\s*:\s*[^,\n]+", entry_src):
        hooks.append("on_event_listens")
    if re.search(r"\blistens_in_hand\s*:\s*true", entry_src):
        hooks.append("listens_in_hand")
    if re.search(r"\bpersistent_listens\s*:\s*[^,\n]+", entry_src):
        hooks.append("persistent_event")
    flags = sorted(set(FLAG_RE.findall(entry_src)))
    events = sorted(set(EV_RE.findall(entry_src)))
    targets = sorted(set(TARGET_RE.findall(entry_src)))
    innate = sorted(set(INNATE_RE.findall(entry_src)) | set(KW_RE.findall(entry_src)))
    hp_uses = HP_USES_RE.search(entry_src)
    return {
        "hooks": sorted(set(hooks)),
        "flags": flags,
        "events": events,
        "target_specs": targets,
        "keywords": innate,
        "hero_power_uses": int(hp_uses.group(1)) if hp_uses else None,
    }


def load_content_sources(at: Path) -> List[Path]:
    crates = [p for p in (at / "crates").iterdir() if p.is_dir()]
    if not crates:
        raise SystemExit(f"找不到 crates/：{at}")
    for crate in crates:
        content = crate / "src" / "content"
        if content.is_dir() and (content / "mod.rs").exists() and any(content.glob("*.rs")):
            return sorted(p for p in content.glob("*.rs") if p.name != "mod.rs")
    raise SystemExit(f"找不到 content/*.rs：{at}")


ALL_SCRIPTS_FN_RE = re.compile(r"pub fn all_scripts\s*\(\s*\)\s*->\s*Vec<\(&\s*'static\s*str\s*,\s*Script\)>\s*\{")


def parse_all_scripts_order(mod_rs: str) -> List[str]:
    """解析 ``mod.rs::all_scripts()`` 里模块拼接顺序（用于校验）。"""
    m = ALL_SCRIPTS_FN_RE.search(mod_rs)
    body = _fn_body(mod_rs, m.start()) if m else ""
    return re.findall(r"\bv\.extend\((\w+)::scripts", body) + re.findall(
        r"let mut v = (\w+)::scripts", body
    )


# ── 上游 content_report 口径的覆盖统计 ────────────────────────────────
def at_implemented_report(cards: Dict[str, Dict[str, Any]], scripted: set) -> Dict[str, Any]:
    """复刻上游 ``examples/content_report.rs`` 的分 kind 覆盖口径。

    金色/变体卡在 ``script.rs::registry()`` 里解析到本体脚本（``normal`` 链），
    因此 ``scripted`` 判定要沿 ``card['normal']`` 回溯，与上游 ``script(cid)`` 一致。
    """

    def has_script(card: Dict[str, Any]) -> bool:
        seen = set()
        cur = card
        while cur is not None and cur["id"] not in seen:
            seen.add(cur["id"])
            if cur["id"] in scripted:
                return True
            nxt = cur.get("normal")
            cur = cards.get(nxt) if nxt else None
        return False

    def impl(card: Dict[str, Any]) -> bool:
        return has_script(card) or C.keyword_only(card.get("text"))

    pool = [
        c
        for c in cards.values()
        if "minion" in c.get("pools", []) and (c.get("pool_tag") or 0) <= 1
    ]
    heroes = [
        c for c in cards.values() if "hero" in c.get("pools", []) and c.get("kind") == "hero"
    ]
    spells = [
        c
        for c in cards.values()
        if "spell" in c.get("pools", []) and c.get("kind") == "tavern_spell"
    ]
    trinkets = [c for c in cards.values() if "trinket" in c.get("pools", [])]
    gifts = [
        c
        for c in cards.values()
        if c.get("kind") == "dark_gift" and c.get("window") is not None
    ]
    timewarp = [c for c in cards.values() if "timewarp" in c.get("pools", [])]
    tier7 = [c for c in cards.values() if "tier7" in c.get("pools", [])]

    def heroes_ok() -> int:
        n = 0
        for h in heroes:
            hp = h.get("hero_power")
            if hp and has_script(cards.get(hp, {"id": hp})):
                n += 1
        return n

    return {
        "shop_minions": {
            "total": len(pool),
            "scripted": sum(1 for c in pool if has_script(c)),
            "implemented": sum(1 for c in pool if impl(c)),
            "ids": sorted(c["id"] for c in pool),
        },
        "heroes": {
            "total": len(heroes),
            "implemented": heroes_ok(),
            "ids": sorted(c["id"] for c in heroes),
        },
        "tavern_spells": {
            "total": len(spells),
            "implemented": sum(1 for c in spells if has_script(c)),
            "ids": sorted(c["id"] for c in spells),
        },
        "trinkets": {
            "total": len(trinkets),
            "implemented": sum(1 for c in trinkets if has_script(c)),
            "ids": sorted(c["id"] for c in trinkets),
        },
        "dark_gifts": {
            "total": len(gifts),
            "implemented": sum(1 for c in gifts if has_script(c)),
            "ids": sorted(c["id"] for c in gifts),
        },
        "timewarp": {
            "total": len(timewarp),
            "implemented": sum(1 for c in timewarp if impl(c)),
            "ids": sorted(c["id"] for c in timewarp),
        },
        "tier7": {
            "total": len(tier7),
            "implemented": sum(1 for c in tier7 if impl(c)),
            "ids": sorted(c["id"] for c in tier7),
        },
    }


#: docs/CONTENT.md 表头快照（用于交叉校验；解析不到就跳过）
CONTENT_MD_PATTERNS = (
    ("shop_minions", re.compile(r"\| Shop minions.*?\| (\d+) \((\d+) scripted\) \| (\d+) \|")),
    ("heroes", re.compile(r"\| Heroes \(hero power scripted\) \| (\d+) \| (\d+) \|")),
    ("tavern_spells", re.compile(r"\| Tavern spells \| (\d+) \| (\d+) \|")),
    ("trinkets", re.compile(r"\| Trinkets \| (\d+) \| (\d+) \|")),
    ("dark_gifts", re.compile(r"\| Dark Gifts \| (\d+) \| (\d+) \|")),
    ("timewarp", re.compile(r"\| Timewarp \(normal and golden\) \| (\d+) \| (\d+) \|")),
    ("tier7", re.compile(r"\| Tier 7 \| (\d+) \| (\d+) \|")),
)


def check_content_md(at: Path, report: Dict[str, Any]) -> Dict[str, Any]:
    md = at / "docs" / "CONTENT.md"
    if not md.exists():
        return {"status": "skipped", "reason": "docs/CONTENT.md 不存在"}
    text = md.read_text(encoding="utf-8", errors="ignore")
    flat: Dict[str, Tuple[int, int]] = {}
    for name, pat in CONTENT_MD_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        nums = tuple(int(x) for x in m.groups())
        if name == "shop_minions":
            flat[name] = (nums[1], nums[2])  # implemented(scripted), candidates
        else:
            flat[name] = (nums[0], nums[1])
    mismatches = []
    for name, (impl, total) in flat.items():
        mine = report[name]
        # shop minions 的 CONTENT.md 表头第一个数是 scripted（括号内），其它是 implemented
        my_impl = mine.get("scripted") if name == "shop_minions" else mine.get("implemented")
        my_total = mine.get("total")
        if my_impl != impl or my_total != total:
            mismatches.append(
                {
                    "kind": name,
                    "content_md": [impl, total],
                    "recomputed": [my_impl, my_total],
                }
            )
    return {
        "status": "match" if not mismatches else "mismatch",
        "content_report_header": {k: list(v) for k, v in sorted(flat.items())},
        "mismatches": mismatches,
    }


# ── main ─────────────────────────────────────────────────────────────
def build(at: Path) -> Dict[str, Any]:
    cards_path = at / "crates" / "taverngym" / "data" / "cards.json"
    if not cards_path.exists():
        raise SystemExit(f"找不到 AT cards.json：{cards_path}")
    at_data = C.load_at_cards(at)
    cards: Dict[str, Dict[str, Any]] = at_data["cards"]

    sources = load_content_sources(at)
    content_dir = sources[0].parent
    mod_rs = (content_dir / "mod.rs").read_text(encoding="utf-8")
    order = parse_all_scripts_order(mod_rs)

    files: List[Dict[str, Any]] = []
    registry: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    unknown_ids: List[str] = []
    dups: List[Dict[str, Any]] = []
    mod_consts = parse_consts(mod_rs)
    for path in sources:
        src = path.read_text(encoding="utf-8")
        # 文件内常量优先，其次 mod.rs（`use super::*;` 可见）——同名时文件内覆盖
        consts = dict(mod_consts)
        consts.update(parse_consts(src))
        entries: List[Tuple[str, str]] = []
        for m in FUNC_SCRIPTS_RE.finditer(src):
            body = _fn_body(src, m.start())
            got, warns = parse_scripts_fn(body, consts)
            entries.extend(got)
            warnings.extend(f"{path.name}: {w}" for w in warns)
        hooks_hist: Dict[str, int] = {}
        for cid, snippet in entries:
            if cid not in cards:
                unknown_ids.append(cid)
            if cid in registry:
                dups.append({"id": cid, "first": registry[cid]["file"], "again": path.name})
            info = hooks_of(snippet)
            info.update({"id": cid, "file": path.name})
            registry[cid] = info
            for h in info["hooks"]:
                hooks_hist[h] = hooks_hist.get(h, 0) + 1
        files.append(
            {
                "file": path.name,
                "n_scripts": len(entries),
                "ids": sorted(cid for cid, _ in entries),
                "hooks_histogram": dict(sorted(hooks_hist.items())),
            }
        )

    # 上游 registry() 断言：内容脚本必须能在 card db 解析
    computed_order = order
    module_names = sorted(p.stem for p in sources)
    missing_from_all_scripts = sorted(
        name for name in module_names if name not in computed_order
    )
    extra_in_all_scripts = sorted(
        name for name in computed_order if name not in module_names
    )

    report = at_implemented_report(cards, set(registry))

    # kind 分布（按 AT card db 的 kind/pools 归类）
    def classify(cid: str) -> str:
        card = cards.get(cid)
        if card is None:
            return "unknown"
        pools = card.get("pools", [])
        kind = card.get("kind")
        if kind == "hero":
            return "hero"
        if kind == "hero_power":
            return "hero_power"
        if kind == "dark_gift":
            return "dark_gift"
        if kind == "quest":
            return "quest"
        if kind == "quest_reward":
            return "quest_reward"
        if "timewarp" in pools:
            return "timewarp"
        if "tier7" in pools:
            return "tier7"
        if "minion" in pools:
            return "pool_minion"
        if "spell" in pools:
            return "pool_spell"
        if "trinket" in pools:
            return "trinket"
        if kind == "trinket_lesser" or kind == "trinket_greater":
            return "trinket_def"
        if kind == "minion":
            return "minion_other"
        if kind == "tavern_spell":
            return "tavern_spell_other"
        if kind == "spell":
            return "spell_other"
        return kind or "unknown"

    kind_counts: Dict[str, int] = {}
    for cid in registry:
        k = classify(cid)
        kind_counts[k] = kind_counts.get(k, 0) + 1

    return {
        "schema": "p2_delta/at_content/v1",
        "at_root": str(at),
        "at_meta": at_data["meta"],
        "cards_json_sha256": C.sha256_of(cards_path),
        "summary": {
            "content_files": len(sources),
            "registry_size": len(registry),
            "known_card_ids": len(registry) - len(set(unknown_ids)),
            "unknown_ids": sorted(set(unknown_ids)),
            "duplicate_ids": dups,
            "kind_counts": dict(sorted(kind_counts.items())),
            "all_scripts_modules": len(computed_order),
            "modules_missing_from_all_scripts": missing_from_all_scripts,
            "modules_extra_in_all_scripts": extra_in_all_scripts,
            "warnings": sorted(warnings),
        },
        "files": files,
        "registry": registry,
        "implemented_report": report,
        "cross_check_content_md": check_content_md(at, report),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--at-root", default=None, help="AutoTavern 仓库根（只读）")
    ap.add_argument(
        "--out",
        default=str(C.RUNS_DIR / "at_content.json"),
        help="输出 JSON 路径（默认 runs/p2_delta/at_content.json）",
    )
    args = ap.parse_args(argv)
    at = C.at_root(args.at_root)
    result = build(at)
    C.write_json(args.out, result)
    s = result["summary"]
    print(f"[extract_at_content] 输出: {args.out}")
    print(
        f"  AT client_version={result['at_meta'].get('client_version')} "
        f"content_files={s['content_files']} registry={s['registry_size']}"
    )
    print(f"  kind_counts={s['kind_counts']}")
    chk = result["cross_check_content_md"]
    print(f"  CONTENT.md 交叉校验: {chk['status']}")
    if chk["status"] == "mismatch":
        print(f"    mismatches={chk['mismatches']}")
    if s["unknown_ids"]:
        print(f"  !! unknown ids: {s['unknown_ids'][:10]}")
    if s["duplicate_ids"]:
        print(f"  !! duplicate ids: {s['duplicate_ids'][:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
