#!/usr/bin/env python
"""rea_tag_compare.py — 对比「官方客户端枚举」与 `hsrl2/tags.py`。

官方来源: `Assembly-CSharp.dll` 的 `GAME_TAG` / `TAG_CARDTYPE` / `TAG_ZONE` /
`TAG_RACE` / `TAG_SPELL_SCHOOL` / `TAG_PLAYSTATE` / `TAG_STEP` 枚举，
由 `tools/rea_net_extract.py`（Mono.Cecil）导出到 `reversed/net/<asm>/enums.json`。

用法:
    python tools/rea_tag_compare.py
    python tools/rea_tag_compare.py --enums reversed/net/Assembly-CSharp/enums.json \
        --out reversed/tag_diff.md --json reversed/tag_diff.json
    python tools/rea_tag_compare.py --allow-missing   # 缺提取物时只告警（测试用）

退出码:
    0  报告已生成（差异本身不算失败——差异是产出）
    2  输入缺失/无法生成报告
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVERSED = ROOT / "reversed"
DEFAULT_ENUMS = REVERSED / "net" / "Assembly-CSharp" / "enums.json"
DEFAULT_OUT = REVERSED / "tag_diff.md"
DEFAULT_JSON = REVERSED / "tag_diff.json"
GAME_DIR = Path(r"C:\Program Files (x86)\Hearthstone")

#: 引擎 `GameTag` 里明确标注为「引擎内部（非协议）」的 tag——它们不参与
#: 与官方枚举的「缺失」统计，只做撞号（numeric collision）风险检查。
INTERNAL_MARKERS = ("引擎内部", "非协议")

#: 与酒馆战棋直接相关的官方 tag 名片段（用于「BG 相关缺失」摘要）。
BG_HINTS = ("BACON", "BATTLEGROUND", "TAVERN", "TRINKET", "QUEST",
            "ANOMALY", "SPELLCRAFT", "DUO")


def load_enums(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def find_enum(enums: dict, name: str) -> dict | None:
    for e in enums.values():
        if e.get("name") == name:
            return e
    return None


def ensure_enums(path: Path) -> bool:
    """提取物缺失时，尝试调用 rea_net_extract 只提取 Assembly-CSharp。"""
    if path.exists():
        return True
    script = ROOT / "tools" / "rea_net_extract.py"
    if not script.exists():
        return False
    print(f"[rea] {path} 缺失，尝试运行 {script.name} ...")
    try:
        cp = subprocess.run(
            [sys.executable, str(script), "--assemblies", "Assembly-CSharp"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=900)
        print(cp.stdout[-2000:])
        if cp.returncode != 0:
            print(cp.stderr[-2000:], file=sys.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[rea] 自动提取失败: {exc}", file=sys.stderr)
    return path.exists()


def read_engine_tags(tags_py: Path) -> tuple[dict, dict]:
    """解析 hsrl2/tags.py 的 GameTag 成员 → {name: value} + {name: 是否内部}。"""
    import ast

    src = tags_py.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    values: dict[str, int] = {}
    internal: dict[str, bool] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "GameTag":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                continue
            try:
                val = ast.literal_eval(stmt.value)
            except (ValueError, SyntaxError):
                continue
            if not isinstance(val, int):
                continue
            name = stmt.targets[0].id
            values[name] = val
            lineno = stmt.lineno
            window = "\n".join(lines[max(0, lineno - 2):lineno + 2])
            internal[name] = any(m in window for m in INTERNAL_MARKERS)
    return values, internal


def compare_named(official: dict, engine: dict, engine_internal: dict | None = None
                  ) -> dict:
    """按「成员名」对比两个 {name: value} 表。"""
    official = dict(official)
    engine = dict(engine)
    common = sorted(set(official) & set(engine))
    mism = [{"name": n, "official": official[n], "engine": engine[n]}
            for n in common if official[n] != engine[n]]
    official_only = [{"name": n, "value": official[n]}
                     for n in sorted(set(official) - set(engine),
                                     key=lambda x: official[x])]
    engine_only = [{"name": n, "value": engine[n]} for n in
                   sorted(set(engine) - set(official), key=lambda x: engine[x])]
    by_value: dict[int, list[str]] = {}
    for n, v in official.items():
        by_value.setdefault(v, []).append(n)
    collisions = []
    for item in engine_only:
        others = [n for n in by_value.get(item["value"], []) if n != item["name"]]
        if others:
            collisions.append({**item, "official_names": sorted(others)})
    internal_only = [x for x in engine_only
                     if (engine_internal or {}).get(x["name"])]
    return {
        "official_count": len(official),
        "engine_count": len(engine),
        "name_matched": len(common),
        "value_mismatch_count": len(mism),
        "value_mismatches": mism,
        "official_only_count": len(official_only),
        "official_only": official_only,
        "engine_only_count": len(engine_only),
        "engine_only": engine_only,
        "engine_only_numeric_collision_count": len(collisions),
        "engine_only_numeric_collisions": collisions,
        "engine_internal_only_count": len(internal_only),
    }


def engine_enum_members(cls) -> dict:
    return {m.name: int(m.value) for m in cls}


def compare_semantic(official: dict, engine: dict, rename: dict | None = None
                     ) -> dict:
    """按语义名对比（把引擎名映射到官方名，如 TAVERN→? 由调用方给 rename）。"""
    rename = rename or {}
    eng = {rename.get(k, k): v for k, v in engine.items()}
    out = compare_named(official, eng)
    out["rename_applied"] = rename
    return out


def build_report(ac_enums: dict, engine_tags: dict, engine_internal: dict,
                 tags_py: Path, enums_path: Path) -> dict:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from hsrl2.tags import CardType, Race, Zone

    g = find_enum(ac_enums, "GAME_TAG")
    if g is None:
        raise SystemExit("[rea] 错误: enums.json 中没有 GAME_TAG 枚举")
    game_tag = compare_named(g["values"], engine_tags, engine_internal)

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {
            "official_assembly": str(GAME_DIR / "Hearthstone_Data" / "Managed" /
                                     "Assembly-CSharp.dll"),
            "official_enum": "GAME_TAG",
            "extracted_enums": str(enums_path),
            "engine_tags": str(tags_py),
            "extraction_tool": "tools/rea_net_extract.py (Mono.Cecil)",
        },
        "game_tag": game_tag,
        "other_enums": {},
    }

    # BG 相关官方缺失摘要
    bg_missing = [x for x in game_tag["official_only"]
                  if any(h in x["name"] for h in BG_HINTS)]
    game_tag["official_only_bg_relevant"] = bg_missing

    # ── CardType / Zone / Race 语义对比 ──
    ct = find_enum(ac_enums, "TAG_CARDTYPE")
    if ct:
        report["other_enums"]["card_type"] = compare_semantic(
            ct["values"], engine_enum_members(CardType),
            rename={"BACON_TRINKET": "BATTLEGROUND_TRINKET",
                    "BACON_ANOMALY": "BATTLEGROUND_ANOMALY",
                    "BACON_SPELL": "BATTLEGROUND_SPELL",
                    "BACON_QUEST_REWARD": "BATTLEGROUND_QUEST_REWARD"})
    zone = find_enum(ac_enums, "TAG_ZONE")
    if zone:
        report["other_enums"]["zone"] = compare_semantic(
            zone["values"], engine_enum_members(Zone),
            rename={"REMOVED": "REMOVEDFROMGAME"})
    race = find_enum(ac_enums, "TAG_RACE")
    if race:
        report["other_enums"]["race"] = compare_semantic(
            race["values"], engine_enum_members(Race),
            rename={"MECH": "MECHANICAL"})
    for key, official_name in (("spell_school", "TAG_SPELL_SCHOOL"),
                               ("play_state", "TAG_PLAYSTATE"),
                               ("step", "TAG_STEP"),
                               ("premium", "TAG_PREMIUM")):
        e = find_enum(ac_enums, official_name)
        if e:
            report["other_enums"][key] = {
                "official_name": official_name,
                "names": sorted(e["values"], key=lambda n: e["values"][n]),
                "values": dict(sorted(e["values"].items(),
                                      key=lambda kv: kv[1])),
                "engine_has_enum": False,
            }
    report["other_enums"]["race"]["official_count"] = len(race["values"]) if race else 0
    return report


def fmt_list_md(items: list[dict], value_key: str, limit: int | None = None,
                extra: str = "") -> str:
    rows = []
    for x in (items[:limit] if limit else items):
        rows.append(f"| `{x['name']}` | {x[value_key]} |{x.get(extra, '')} |"
                    if extra else f"| `{x['name']}` | {x[value_key]} |")
    return "\n".join(rows)


def render_md(rep: dict) -> str:
    g = rep["game_tag"]
    o = rep["other_enums"]
    L: list[str] = []
    L.append("# 官方客户端枚举 vs `hsrl2/tags.py` 差异报告\n")
    L.append("> 自动生成，勿手改。复现命令："
             "`python tools/rea_net_extract.py` → `python tools/rea_tag_compare.py`\n")
    L.append(f"- 生成时间: {rep['generated_at']}")
    L.append(f"- 官方程序集: `{rep['sources']['official_assembly']}`")
    L.append(f"- 官方枚举: `{rep['sources']['official_enum']}`"
             f"（{g['official_count']} 个成员）")
    L.append(f"- 引擎枚举: `{rep['sources']['engine_tags']}`"
             f"（{g['engine_count']} 个成员）")
    L.append("")
    L.append("## 1. GameTag 汇总\n")
    L.append("| 指标 | 数量 |")
    L.append("|------|------|")
    L.append(f"| 官方成员 | {g['official_count']} |")
    L.append(f"| 引擎成员 | {g['engine_count']} |")
    L.append(f"| 同名成员 | {g['name_matched']} |")
    L.append(f"| **同名数值不一致** | **{g['value_mismatch_count']}** |")
    L.append(f"| 官方有 / 引擎无（缺失） | {g['official_only_count']} |")
    L.append(f"| 引擎有 / 官方无（多余） | {g['engine_only_count']} |")
    L.append(f"| 其中引擎内部 tag（注释标注） | {g['engine_internal_only_count']} |")
    L.append(f"| 多余 tag 与官方数值撞号 | {g['engine_only_numeric_collision_count']} |")
    L.append("")
    L.append("## 2. 同名数值不一致（真正的协议 bug 面）\n")
    if g["value_mismatches"]:
        L.append("| tag | 官方值 | 引擎值 | 差值 |")
        L.append("|-----|--------|--------|------|")
        for x in g["value_mismatches"]:
            L.append(f"| `{x['name']}` | {x['official']} | {x['engine']} | "
                     f"{x['engine'] - x['official']:+d} |")
    else:
        L.append("无。")
    L.append("")
    L.append("## 3. 引擎多余 tag（官方枚举无此名）\n")
    L.append(f"共 {g['engine_only_count']} 个（其中 {g['engine_internal_only_count']} "
             "个在源码注释里标注为「引擎内部/非协议」）。前 10 个（按数值）：\n")
    L.append("| tag | 引擎值 |")
    L.append("|-----|--------|")
    L.append(fmt_list_md(g["engine_only"], "value", limit=10))
    if g["engine_only_numeric_collisions"]:
        L.append("\n### 3.1 数值撞号（引擎 tag 的数值 = 另一个官方 tag）\n")
        L.append("| 引擎 tag | 值 | 撞到的官方 tag |")
        L.append("|---------|----|---------------|")
        for x in g["engine_only_numeric_collisions"][:20]:
            L.append(f"| `{x['name']}` | {x['value']} | "
                     f"{', '.join('`' + n + '`' for n in x['official_names'])} |")
        L.append(f"\n> 共 {g['engine_only_numeric_collision_count']} 个撞号。"
                 "引擎内部 tag 段（1000–1099）与官方协议 tag 大面积重叠，"
                 "真实日志桥必须按 **tag 名** 映射，绝不能按数值互转。")
    L.append("")
    L.append("## 4. 官方有而引擎缺（前 30，按数值）\n")
    L.append("| 官方 tag | 值 |")
    L.append("|---------|----|")
    L.append(fmt_list_md(g["official_only"], "value", limit=30))
    bg = g.get("official_only_bg_relevant", [])
    L.append(f"\n**酒馆战棋相关缺失 {len(bg)} 个**（名称含 "
             f"{'/'.join(BG_HINTS)}）：\n")
    L.append("| 官方 tag | 值 |")
    L.append("|---------|----|")
    L.append(fmt_list_md(bg, "value", limit=40))
    L.append("")
    L.append("## 5. 其它关键枚举\n")
    labels = {
        "card_type": "CardType（TAG_CARDTYPE）",
        "zone": "Zone（TAG_ZONE）",
        "race": "Race（TAG_RACE）",
    }
    for key, label in labels.items():
        if key not in o:
            continue
        e = o[key]
        L.append(f"### {label}\n")
        L.append(f"- 官方 {e['official_count']} / 引擎 {e['engine_count']}，"
                 f"同名 {e['name_matched']}，数值不一致 {e['value_mismatch_count']}"
                 f"，官方独有 {e['official_only_count']}")
        if e["value_mismatches"]:
            L.append("\n| 名称 | 官方值 | 引擎值 |")
            L.append("|------|--------|--------|")
            for x in e["value_mismatches"]:
                L.append(f"| `{x['name']}` | {x['official']} | {x['engine']} |")
        if e["engine_only"]:
            L.append(f"\n引擎独有：{', '.join('`'+x['name']+'`' for x in e['engine_only'])}")
        L.append("")
    L.append("### SpellSchool / PlayState / Step / Premium（引擎未定义枚举，仅参考）\n")
    for key in ("spell_school", "play_state", "step", "premium"):
        e = o.get(key)
        if not e:
            continue
        pairs = ", ".join(f"{n}={v}" for n, v in e["values"].items())
        L.append(f"- **{e['official_name']}**: {pairs}")
    L.append("")
    L.append("## 6. 结论\n")
    L.append("- 引擎 `GameTag` 只是官方 1214 个 tag 的**小子集**；"
             "模拟器实际用到的 tag 名基本存在，但新版 BG tag 大量未收录。")
    L.append("- 同名数值不一致是**可执行的 bug 清单**：协议 numeric tag 一旦取值错误，"
             "Power.log 差分/真实对局桥会直接对不上。")
    L.append("- 引擎内部 tag 段（1000+）与官方协议 tag **撞号**，"
             "因此真实日志桥必须按 **tag 名**而非数值映射（详见 "
             "`docs/OFFICIAL_EXACTNESS.md`）。")
    L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--enums", default=str(DEFAULT_ENUMS))
    ap.add_argument("--tags-py", default=str(ROOT / "hsrl2" / "tags.py"))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--json", default=str(DEFAULT_JSON))
    ap.add_argument("--allow-missing", action="store_true",
                    help="输入缺失时告警并退出 0（pytest skip 用）")
    args = ap.parse_args(argv)

    enums_path = Path(args.enums)
    tags_py = Path(args.tags_py)
    if not tags_py.exists():
        print(f"[rea] 错误: 找不到 {tags_py}", file=sys.stderr)
        return 2
    if not ensure_enums(enums_path):
        msg = f"官方枚举提取物缺失: {enums_path}"
        if args.allow_missing:
            print(f"[rea] 警告: {msg}（--allow-missing，跳过）")
            return 0
        print(f"[rea] 错误: {msg}\n"
              f"       先运行: python tools/rea_net_extract.py", file=sys.stderr)
        return 2

    ac_enums = load_enums(enums_path)
    engine_tags, engine_internal = read_engine_tags(tags_py)
    if not engine_tags:
        print("[rea] 错误: 未能从 tags.py 解析出 GameTag 成员", file=sys.stderr)
        return 2

    rep = build_report(ac_enums, engine_tags, engine_internal, tags_py, enums_path)
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    Path(args.out).write_text(render_md(rep) + "\n", encoding="utf-8")

    g = rep["game_tag"]
    print(f"[rea] GameTag: 官方 {g['official_count']} / 引擎 {g['engine_count']} / "
          f"同名 {g['name_matched']} / 数值不一致 {g['value_mismatch_count']} / "
          f"缺失 {g['official_only_count']} / 多余 {g['engine_only_count']}")
    print(f"[rea] 报告: {args.out}\n[rea] JSON: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
