#!/usr/bin/env python
"""rea_data_diff.py — 官方 CardDefs 差分（build 255130 vs 本地 249896）。

纯只读：只解析 XML、只写 `reversed/`。不修改 `hsdata/` 或 `data/`。

用法:
    python tools/rea_data_diff.py
    python tools/rea_data_diff.py --new reversed/hsdata_255130/CardDefs.xml \
        --old hsdata/CardDefs.xml \
        --out reversed/data_diff_255130_vs_249896.md \
        --json reversed/data_diff_255130_vs_249896.json

产出:
    - 总量 / BG 实体数 / 池内随从数
    - BG 卡 id 新增、删除、同名改 id（dbf 相同）
    - 公共 id 的数值变化（ATK/HEALTH/COST/TECH_LEVEL/RARITY/ARMOR/script_num_1..5）
    - 同一 CardID 的卡名变化
    - 新出现的 card_type / 新出现的 tag enumID（BG 卡范围内）
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVERSED = ROOT / "reversed"

# XML enumID（与 hsrl2/tools 生成器一致）
T = {
    "CARDNAME": 185, "CARDTEXT": 184, "HEALTH": 45, "ATK": 47, "COST": 48,
    "CARDRACE": 200, "CARD_SET": 183, "CARDTYPE": 202, "RARITY": 203,
    "ARMOR": 292, "TECH_LEVEL": 1440, "PREMIUM": 12,
    "SPELL_SCHOOL": 1635,
    "NUM_1": 2, "NUM_2": 3, "NUM_3": 2889, "NUM_4": 2919, "NUM_5": 2920,
    "IS_BACON_POOL_MINION": 1456, "IS_BACON_POOL_SPELL": 3081,
}
NUMERIC_KEYS = ["ATK", "HEALTH", "COST", "TECH_LEVEL", "RARITY", "ARMOR",
                "NUM_1", "NUM_2", "NUM_3", "NUM_4", "NUM_5", "SPELL_SCHOOL"]
BG_SET = 1453


def parse(xml_paths) -> dict:
    """流式解析一个或多个 CardDefs XML，返回总量 + BG 卡明细（只留 int tags）。

    build 255130 起官方数据拆成 CardDefs.xml + CardDefs.Bacon.xml：
    同时传入两个文件，按 CardID 合并（重复 CardID 会记录在 duplicates）。
    """
    from lxml import etree

    if isinstance(xml_paths, (str, Path)):
        xml_paths = [xml_paths]
    total = 0
    bg: dict[str, dict] = {}
    duplicates: list[str] = []
    per_file: dict[str, int] = {}
    card_type_counts: Counter = Counter()
    set_counts: Counter = Counter()
    for xml_path in xml_paths:
        xml_path = Path(xml_path)
        n_file = 0
        ctx = etree.iterparse(str(xml_path), events=("end",), tag="Entity")
        for _event, elem in ctx:
            cid = elem.get("CardID")
            if not cid:
                elem.clear()
                continue
            n_file += 1
            total += 1
            tags: dict[int, int | str] = {}
            for t in elem.findall("Tag"):
                enum = t.get("enumID")
                if enum is None:
                    continue
                try:
                    enum_i = int(enum)
                except ValueError:
                    continue
                if t.get("type") == "LocString":
                    if enum_i in (T["CARDNAME"], T["CARDTEXT"]):
                        loc = t.find("enUS")
                        tags[enum_i] = (loc.text if loc is not None
                                        and loc.text else "")
                    continue
                try:
                    tags[enum_i] = int(t.get("value", "0"))
                except (TypeError, ValueError):
                    continue
            card_set = tags.get(T["CARD_SET"], 0)
            ct = tags.get(T["CARDTYPE"], 0)
            set_counts[card_set] += 1
            if card_set == BG_SET:
                if cid in bg:
                    duplicates.append(cid)
                bg[cid] = {
                    "dbf": int(elem.get("ID", 0)),
                    "tags": {str(k): v for k, v in tags.items()
                             if isinstance(v, int)},
                    "name": tags.get(T["CARDNAME"], ""),
                }
                card_type_counts[ct] += 1
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]
        per_file[xml_path.name] = n_file
    return {"total_entities": total, "bg": bg,
            "bg_card_type_counts": dict(card_type_counts),
            "set_counts": dict(set_counts), "per_file": per_file,
            "duplicate_card_ids": duplicates}


def num(tags: dict, enum_id: int):
    return tags.get(str(enum_id))


def diff(old: dict, new: dict) -> dict:
    ob, nb = old["bg"], new["bg"]
    old_ids, new_ids = set(ob), set(nb)
    common = sorted(old_ids & new_ids)
    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)

    def pref(ids):
        c: Counter = Counter()
        for i in ids:
            if i.startswith("BGDUO"):
                c["BGDUO"] += 1
            elif i.startswith("TB_Bacon"):
                c["TB_Bacon"] += 1
            elif i.startswith("BG"):
                c["BG"] += 1
            else:
                c["other"] += 1
        return dict(c)

    # dbf 相同但 CardID 变化（改名/重做）
    dbf_old = {v["dbf"]: k for k, v in ob.items()}
    dbf_new = {v["dbf"]: k for k, v in nb.items()}
    id_renumbers = [{"dbf": d, "old_id": dbf_old[d], "new_id": dbf_new[d]}
                    for d in sorted(set(dbf_old) & set(dbf_new))
                    if dbf_old[d] != dbf_new[d]]

    name_changed = []
    value_changes: dict[str, list] = defaultdict(list)
    type_changed = []
    for cid in common:
        o, n = ob[cid], nb[cid]
        if o["name"] != n["name"]:
            name_changed.append({"id": cid, "old": o["name"], "new": n["name"]})
        for key in NUMERIC_KEYS:
            enum = T[key]
            ov, nv = num(o["tags"], enum), num(n["tags"], enum)
            if ov != nv:
                value_changes[key].append({"id": cid, "old": ov, "new": nv})
        oc = num(o["tags"], T["CARDTYPE"])
        nc = num(n["tags"], T["CARDTYPE"])
        if oc != nc:
            type_changed.append({"id": cid, "old": oc, "new": nc})

    # 新 tag enumID（BG 卡使用）
    old_tag_ids: Counter = Counter()
    new_tag_ids: Counter = Counter()
    for c in ob.values():
        old_tag_ids.update(c["tags"].keys())
    for c in nb.values():
        new_tag_ids.update(c["tags"].keys())
    new_tags = [{"enumID": int(k), "cards": new_tag_ids[k]}
                for k in sorted(new_tag_ids, key=int) if k not in old_tag_ids]
    gone_tags = [{"enumID": int(k), "cards": old_tag_ids[k]}
                 for k in sorted(old_tag_ids, key=int) if k not in new_tag_ids]

    # 池内数量（生成器同口径）
    pool_old = sum(1 for c in ob.values()
                   if num(c["tags"], T["IS_BACON_POOL_MINION"]))
    pool_new = sum(1 for c in nb.values()
                   if num(c["tags"], T["IS_BACON_POOL_MINION"]))

    return {
        "old": {
            "path": str(OLD_PATH), "total_entities": old["total_entities"],
            "bg_entities": len(ob),
            "bg_pool_minions": pool_old,
            "bg_card_type_counts": old["bg_card_type_counts"],
        },
        "new": {
            "path": " + ".join(str(p) for p in NEW_PATHS),
            "total_entities": new["total_entities"],
            "bg_entities": len(nb),
            "bg_pool_minions": pool_new,
            "bg_card_type_counts": new["bg_card_type_counts"],
            "per_file": new.get("per_file", {}),
        },
        "delta": {
            "total_entities": new["total_entities"] - old["total_entities"],
            "bg_entities": len(nb) - len(ob),
            "bg_pool_minions": pool_new - pool_old,
        },
        "bg_added": added,
        "bg_added_by_prefix": pref(added),
        "bg_removed": removed,
        "bg_removed_by_prefix": pref(removed),
        "id_renumbers": id_renumbers,
        "name_changed_count": len(name_changed),
        "name_changed": name_changed,
        "value_change_counts": {k: len(v) for k, v in value_changes.items()},
        "value_changes": {k: v for k, v in value_changes.items()},
        "card_type_changed": type_changed,
        "new_tag_enum_ids": new_tags,
        "gone_tag_enum_ids": gone_tags,
    }


def load_tag_names() -> dict[int, str]:
    """从 rea_net_extract 的 key_enums.json（或 enums.json）取 enumID→GAME_TAG 名。"""
    for p in (REVERSED / "net" / "key_enums.json",
              REVERSED / "net" / "Assembly-CSharp" / "enums.json"):
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        if "game_tag" in d:
            vals = d["game_tag"]["values"]
        else:
            cand = [e for e in d.values() if e.get("name") == "GAME_TAG"]
            vals = cand[0]["values"] if cand else {}
        return {int(v): k for k, v in vals.items()}
    return {}


def render_md(d: dict, old_meta: dict, new_meta: dict) -> str:
    L: list[str] = []
    L.append("# 官方 CardDefs 差分：build 255130 vs 249896\n")
    L.append("> 自动生成，勿手改。复现：`python tools/rea_data_diff.py`\n")
    L.append(f"- 生成时间: {d['_generated_at']}")
    L.append(f"- 旧: `{d['old']['path']}` — {d['old']['total_entities']:,} 实体，"
             f"BG 集 {d['old']['bg_entities']:,}，池内随从 "
             f"{d['old']['bg_pool_minions']:,}")
    L.append(f"- 新: `{d['new']['path']}` — {d['new']['total_entities']:,} 实体，"
             f"BG 集 {d['new']['bg_entities']:,}，池内随从 "
             f"{d['new']['bg_pool_minions']:,}")
    L.append("")
    L.append("## 1. 总量\n")
    L.append("| 指标 | 249896 | 255130 | Δ |")
    L.append("|------|--------|--------|----|")
    for key, label in (("total_entities", "实体总数"), ("bg_entities", "BG 集实体"),
                       ("bg_pool_minions", "池内随从")):
        L.append(f"| {label} | {d['old'][key]:,} | {d['new'][key]:,} | "
                 f"{d['delta'][key]:+,} |")
    L.append("")
    L.append("> 口径：本节「池内随从」= CardDefs 中 `IS_BACON_POOL_MINION`(1456) "
             "为真的实体数；生成器统计会再排除 enchantment / 双打专属，"
             "见 `reversed/data_255130_generator_report.md`。")
    L.append("")
    L.append("## 2. BG 卡 id 变化\n")
    L.append(f"- 新增 **{len(d['bg_added'])}** 个，删除 **{len(d['bg_removed'])}** 个，"
             f"公共 **{d['new']['bg_entities'] - len(d['bg_added'])}** 个")
    L.append(f"- 新增前缀分布: {d['bg_added_by_prefix']}")
    L.append(f"- 删除前缀分布: {d['bg_removed_by_prefix']}")
    L.append("")
    L.append("### 2.1 新增 BG 卡（全部）\n")
    if d["bg_added"]:
        L.append(", ".join(f"`{x}`" for x in d["bg_added"]))
    else:
        L.append("无。")
    L.append("")
    L.append("### 2.2 删除 BG 卡（全部）\n")
    if d["bg_removed"]:
        L.append(", ".join(f"`{x}`" for x in d["bg_removed"]))
    else:
        L.append("无。")
    L.append("")
    L.append("### 2.3 同一 dbf id 的 CardID 变化（重做/改名）\n")
    if d["id_renumbers"]:
        L.append("| dbf | 旧 id | 新 id |")
        L.append("|-----|-------|-------|")
        for x in d["id_renumbers"][:50]:
            L.append(f"| {x['dbf']} | `{x['old_id']}` | `{x['new_id']}` |")
    else:
        L.append("无。")
    L.append("")
    L.append(f"### 2.4 同一 CardID 卡名变化：{d['name_changed_count']} 张\n")
    if d["name_changed"]:
        L.append("| id | 旧名 | 新名 |")
        L.append("|----|------|------|")
        for x in d["name_changed"][:50]:
            L.append(f"| `{x['id']}` | {x['old']} | {x['new']} |")
        if d["name_changed_count"] > 50:
            L.append(f"\n> 仅列前 50；完整列表见 JSON。")
    L.append("")
    L.append("## 3. 数值变化（公共 id）\n")
    L.append("| tag | 变化卡数 |")
    L.append("|-----|----------|")
    for k in NUMERIC_KEYS:
        L.append(f"| {k} | {d['value_change_counts'].get(k, 0)} |")
    L.append("")
    for k in NUMERIC_KEYS:
        changes = d["value_changes"].get(k) or []
        if not changes:
            continue
        L.append(f"### 3.{NUMERIC_KEYS.index(k) + 1} {k}（{len(changes)}）\n")
        L.append("| id | 旧 | 新 |")
        L.append("|----|----|----|")
        for x in changes[:40]:
            L.append(f"| `{x['id']}` | {x['old']} | {x['new']} |")
        if len(changes) > 40:
            L.append(f"\n> 仅列前 40；完整 {len(changes)} 条见 JSON。")
        L.append("")
    L.append("## 4. card_type 变化\n")
    if d["card_type_changed"]:
        L.append("| id | 旧 card_type | 新 card_type |")
        L.append("|----|--------------|--------------|")
        for x in d["card_type_changed"]:
            L.append(f"| `{x['id']}` | {x['old']} | {x['new']} |")
    else:
        L.append("无。")
    L.append("")
    L.append("## 5. BG 卡使用的新 tag enumID（数据/生成器兼容性风险）\n")
    tag_names = load_tag_names()
    if d["new_tag_enum_ids"]:
        L.append("| enumID | GAME_TAG 名 | 出现卡数 |")
        L.append("|--------|-------------|----------|")
        for x in d["new_tag_enum_ids"]:
            name = tag_names.get(x["enumID"], "（客户端未命名/内部）")
            L.append(f"| {x['enumID']} | `{name}` | {x['cards']} |")
        L.append("\n> 生成器 `tools/generate_bg_data.py` 的 `TAG` 白名单只导出已知 "
                 "enumID；新 enumID 默认被忽略（不会报错），需要人工判断是否影响机制。")
        L.append("> 37.0 新增机制相关的 tag（BACON_OLD_GOD / BACON_DEITY_SIGIL / "
                 "BACON_MYSTERY_* / HAS_DARK_GIFT 等）目前**未**进入引擎数据层。")
    else:
        L.append("无新 enumID。")
    L.append("")
    if d["gone_tag_enum_ids"]:
        L.append("### 5.1 249896 使用、255130 BG 卡不再出现的 enumID\n")
        L.append("| enumID | 旧出现卡数 |")
        L.append("|--------|------------|")
        for x in d["gone_tag_enum_ids"]:
            L.append(f"| {x['enumID']} | {x['cards']} |")
        L.append("")
    L.append("## 6. 结论与升级影响\n")
    L.append(f"- 需要新增/更新 **{len(d['bg_added'])}** 张 BG 卡、"
             f"**{sum(d['value_change_counts'].values())}** 处数值变化；"
             f"删除 {len(d['bg_removed'])} 张（多为轮换/历史 token）。")
    L.append("- 数值变化集中在 ATK/HEALTH/COST/TECH_LEVEL 时，"
             "直接影响 `data/bg_*.json` 与引擎脚本的数值断言。")
    L.append("- 先跑 `tools/rea_generate_probe.py` 生成到 `reversed/data_255130/`，"
             "对比 `data/` 后再决定是否替换（流程见 `docs/OFFICIAL_EXACTNESS.md`）。")
    L.append("")
    return "\n".join(L)


OLD_PATH = ROOT / "hsdata" / "CardDefs.xml"
NEW_PATHS = [REVERSED / "hsdata_255130" / "CardDefs.xml",
             REVERSED / "hsdata_255130" / "CardDefs.Bacon.xml"]


def main(argv: list[str] | None = None) -> int:
    global OLD_PATH, NEW_PATHS
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", default=str(OLD_PATH))
    ap.add_argument("--new", action="append", default=None,
                    help="可重复；build 255130 需要 CardDefs.xml + "
                         "CardDefs.Bacon.xml 两个文件")
    ap.add_argument("--out", default=str(REVERSED / "data_diff_255130_vs_249896.md"))
    ap.add_argument("--json", default=str(REVERSED / "data_diff_255130_vs_249896.json"))
    args = ap.parse_args(argv)
    OLD_PATH = Path(args.old)
    NEW_PATHS = [Path(x) for x in args.new] if args.new else NEW_PATHS
    for p in [OLD_PATH] + NEW_PATHS:
        if not p.exists():
            print(f"[rea] 错误: 找不到 {p}", file=sys.stderr)
            return 2

    print(f"[rea] 解析旧 build: {OLD_PATH} ...")
    old = parse(OLD_PATH)
    print(f"[rea]   实体 {old['total_entities']:,} / BG {len(old['bg']):,}"
          f" / 分文件 {old['per_file']}")
    print(f"[rea] 解析新 build: {[str(p) for p in NEW_PATHS]} ...")
    new = parse(NEW_PATHS)
    print(f"[rea]   实体 {new['total_entities']:,} / BG {len(new['bg']):,}"
          f" / 分文件 {new['per_file']}")
    if new["duplicate_card_ids"]:
        print(f"[rea] 警告: 跨文件重复 CardID {len(new['duplicate_card_ids'])} 个")

    d = diff(old, new)
    d["_generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    d["old"]["path"] = str(OLD_PATH)
    d["new"]["path"] = " + ".join(str(p) for p in NEW_PATHS)
    d["old"]["per_file"] = old["per_file"]
    d["new"]["per_file"] = new["per_file"]
    d["new"]["duplicate_card_ids"] = new["duplicate_card_ids"]
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    Path(args.out).write_text(render_md(d, {}, {}) + "\n", encoding="utf-8")
    print(f"[rea] 新增 {len(d['bg_added'])} / 删除 {len(d['bg_removed'])} / "
          f"数值变化 {sum(d['value_change_counts'].values())} / "
          f"卡名变化 {d['name_changed_count']}")
    print(f"[rea] 报告: {args.out}\n[rea] JSON: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
