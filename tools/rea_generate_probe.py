#!/usr/bin/env python
"""rea_generate_probe.py — 用 255130 的官方 CardDefs 试跑 `generate_bg_data.py`。

目的：验证「新 build 数据能否被现有生成器消费」，且**不覆盖** `data/`。
做法：
  1. 以 importlib 加载 `tools/generate_bg_data.py`（不修改它）；
  2. 猴补丁：`HSDATA_XML` → 255130 XML，`DATA_DIR` → `reversed/data_255130/`，
     `ROOT` → 一个只含 `hsdata/README.md`（Version: 37.0.0.255130）的临时根，
     使 bg_summary.patch 记录正确版本；
  3. 调 `main()` 生成全部 bg_*.json；再与当前 `data/` 做条目数/摘要对比；
  4. 用 `hsrl2.db.CardDB.load()` 实际加载新数据，报告能否被引擎消费、
     有多少卡类型无法映射（CardDef.from_json 的 INVALID 兜底）、重复 id 冲突等。

用法:
    python tools/rea_generate_probe.py
    python tools/rea_generate_probe.py --xml reversed/hsdata_255130/CardDefs.xml

退出码: 0 = 生成成功并完成对比；2 = 输入缺失；3 = 生成器抛异常。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVERSED = ROOT / "reversed"
HSDATA_255130 = REVERSED / "hsdata_255130"
DEFAULT_XMLS = [HSDATA_255130 / "CardDefs.xml",
                HSDATA_255130 / "CardDefs.Bacon.xml"]
MERGED_XML = REVERSED / "data_255130_input" / "CardDefs.merged.xml"
DEFAULT_OUT = REVERSED / "data_255130"
PATCH = "37.0.0.255130.254477"

LIST_FILES = [
    "bg_cards.json", "bg_pool_minions.json", "bg_pool_spells.json",
    "bg_heroes.json", "bg_hero_powers.json", "bg_trinkets.json",
    "bg_anomalies.json", "bg_quest_rewards.json", "bg_tavern_spells.json",
    "bg_dark_gifts.json",
]


def load_generator():
    path = ROOT / "tools" / "generate_bg_data.py"
    spec = importlib.util.spec_from_file_location("rea_generate_bg_data", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_fake_root(src_dir: Path) -> Path:
    fake = src_dir / "hsdata"
    fake.mkdir(parents=True, exist_ok=True)
    (fake / "README.md").write_text(
        "Hearthstone Data\n\nVersion: " + PATCH + "\n", encoding="utf-8")
    return src_dir


def summarize(data_dir: Path) -> dict:
    out: dict = {"files": {}, "summary": None}
    for name in LIST_FILES + ["pool_minion_texts.json"]:
        p = data_dir / name
        if not p.exists():
            out["files"][name] = None
            continue
        try:
            v = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            out["files"][name] = "INVALID_JSON"
            continue
        out["files"][name] = len(v) if isinstance(v, (list, dict)) else None
    p = data_dir / "bg_summary.json"
    if p.exists():
        out["summary"] = json.loads(p.read_text(encoding="utf-8"))
    return out


def try_carddb(data_dir: Path) -> dict:
    """让引擎数据层真正加载一遍新数据（只读、不写）。"""
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from hsrl2.db import CardDB
        from hsrl2.defs import CardDef
        from hsrl2.tags import CardType

        db = CardDB.load(data_dir)
        invalid_types = []
        for d in db._by_id.values():
            if d.card_type == CardType.INVALID:
                invalid_types.append(d.id)
        return {
            "ok": True,
            "cards": len(db),
            "pool_minions": len(db.pool_minions()),
            "pool_spells": len(db.pool_spells()),
            "invalid_card_type_count": len(invalid_types),
            "invalid_card_type_sample": sorted(invalid_types)[:30],
        }
    except Exception as exc:  # noqa: BLE001 —— 探针要报告任何异常
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-4000:]}


def merge_xmls(sources: list[Path], out: Path) -> Path:
    """把多个 CardDefs XML 的 <Entity> 合并成一个 CardDefs 根。

    build 255130 起官方数据拆成 CardDefs.xml（构筑）+ CardDefs.Bacon.xml
    （酒馆战棋）；现有生成器只接受单文件，因此先合并再喂给生成器（不改生成器）。
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as w:
        w.write('<?xml version="1.0" encoding="utf-8"?>\n')
        w.write(f'<CardDefs build="{PATCH}">\n')
        for src in sources:
            with src.open(encoding="utf-8") as f:
                for line in f:
                    if line.startswith("<?xml") or line.startswith("<CardDefs"):
                        continue
                    if line.strip() == "</CardDefs>":
                        continue
                    w.write(line)
        w.write("</CardDefs>\n")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xml", action="append", default=None,
                    help="可重复；默认 CardDefs.xml + CardDefs.Bacon.xml")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--md", default=str(REVERSED / "data_255130_generator_report.md"))
    ap.add_argument("--json", default=str(REVERSED / "data_255130_generator_report.json"))
    args = ap.parse_args(argv)

    xmls = [Path(x) for x in args.xml] if args.xml else list(DEFAULT_XMLS)
    missing = [p for p in xmls if not p.exists()]
    if missing:
        print(f"[rea] 错误: 找不到 {missing}\n"
              f"       先运行 python tools/rea_fetch_hsdata.py --tag 255130",
              file=sys.stderr)
        return 2
    merged = merge_xmls(xmls, MERGED_XML)
    print(f"[rea] 合并输入 {[str(p) for p in xmls]} -> {merged} "
          f"({merged.stat().st_size:,} bytes)")
    xml = merged
    out_dir = Path(args.out)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fake_root = write_fake_root(REVERSED / "data_255130_src")

    # ── 1. 跑生成器（猴补丁输入/输出路径）──
    mod = load_generator()
    mod.ROOT = fake_root
    mod.HSDATA_XML = xml
    mod.DATA_DIR = out_dir
    argv_backup = sys.argv[:]
    sys.argv = ["generate_bg_data.py"]
    try:
        print(f"[rea] 运行 generate_bg_data.py: {xml} -> {out_dir}")
        rc = mod.main()
    except SystemExit as exc:       # pragma: no cover
        rc = exc.code or 0
    except Exception:                # noqa: BLE001
        err = traceback.format_exc()
        print(err, file=sys.stderr)
        write_report(args, xml, out_dir, {}, rc=3, error=err)
        return 3
    finally:
        sys.argv = argv_backup
    if rc not in (0, None):
        print(f"[rea] 生成器返回 {rc}", file=sys.stderr)
        write_report(args, xml, out_dir, {}, rc=rc)
        return 3

    # ── 2. 对比现有 data/ ──
    new_sum = summarize(out_dir)
    old_sum = summarize(ROOT / "data")
    db_new = try_carddb(out_dir)
    db_old = try_carddb(ROOT / "data")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "xml": str(xml),
        "out_dir": str(out_dir),
        "generator": "tools/generate_bg_data.py (未修改，经 importlib 猴补丁输入输出路径)",
        "generated": new_sum,
        "current_data": old_sum,
        "engine_load_new": db_new,
        "engine_load_current": db_old,
        "rc": rc,
    }
    Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    Path(args.md).write_text(render_md(report, xml), encoding="utf-8")
    print(f"[rea] 生成完成: {out_dir}")
    print(f"[rea] 报告: {args.md}\n[rea] JSON: {args.json}")
    return 0


def write_report(args, xml: Path, out_dir: Path, _unused, rc: int,
                 error: str = "") -> None:
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "xml": str(xml), "out_dir": str(out_dir), "rc": rc,
              "error": error}
    Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    Path(args.md).write_text(f"# 生成器探针失败\n\n- xml: `{xml}`\n- rc: {rc}\n\n"
                             f"```\n{error}\n```\n", encoding="utf-8")


def render_md(rep: dict, xml: Path) -> str:
    new, old = rep["generated"], rep["current_data"]
    L: list[str] = []
    L.append("# `generate_bg_data.py` 消费 255130 数据 — 试跑报告\n")
    L.append("> 自动生成，勿手改。复现：`python tools/rea_generate_probe.py`\n")
    L.append(f"- 生成时间: {rep['generated_at']}")
    L.append(f"- 输入 XML: `{xml}`")
    L.append(f"- 输出目录: `{rep['out_dir']}`（**未触碰 `data/`**）")
    L.append(f"- 生成器: {rep['generator']}")
    L.append(f"- 返回码: {rep['rc']}")
    L.append("")
    L.append("## 1. 生成结果（vs 当前 `data/`）\n")
    L.append("| 文件 | 255130 条目 | 当前 data/ 条目 | Δ |")
    L.append("|------|-------------|-----------------|----|")
    for name in LIST_FILES + ["pool_minion_texts.json"]:
        a = new["files"].get(name)
        b = old["files"].get(name)
        delta = (a - b) if isinstance(a, int) and isinstance(b, int) else "—"
        L.append(f"| `{name}` | {a} | {b} | {delta} |")
    L.append("")
    sn, so = new.get("summary"), old.get("summary")
    if sn and so:
        L.append("### 1.1 bg_summary 对比\n")
        keys = ["patch", "total_bg_cards", "dark_gifts", "hero_powers",
                "tavern_spells", "quest_rewards", "anomalies", "trinkets"]
        L.append("| 字段 | 255130 | 当前 |")
        L.append("|------|--------|------|")
        for k in keys:
            L.append(f"| `{k}` | {sn.get(k)} | {so.get(k)} |")
        for k in ("pool_minions", "pool_spells", "heroes"):
            a, b = sn.get(k), so.get(k)
            if isinstance(a, dict) and isinstance(b, dict):
                L.append(f"| `{k}.count` | {a.get('count')} | {b.get('count')} |")
                if k == "pool_minions":
                    L.append(f"| `pool_minions.by_tier` | {a.get('by_tier')} | "
                             f"{b.get('by_tier')} |")
    L.append("")
    L.append("## 2. 引擎能否加载新数据（`CardDB.load`）\n")
    for label, key in (("255130 生成数据", "engine_load_new"),
                       ("当前 data/", "engine_load_current")):
        r = rep[key]
        if r.get("ok"):
            L.append(f"- **{label}**: 加载成功 — {r['cards']} 张卡、"
                     f"池内随从 {r['pool_minions']}、池内法术 {r['pool_spells']}、"
                     f"无法映射 card_type {r['invalid_card_type_count']}")
            if r["invalid_card_type_sample"]:
                L.append(f"  - INVALID 类型样例: "
                         f"{', '.join('`'+x+'`' for x in r['invalid_card_type_sample'])}")
        else:
            L.append(f"- **{label}**: 加载失败 — {r.get('error')}")
    L.append("")
    L.append("## 3. 结论\n")
    ok = rep["rc"] == 0 and rep["engine_load_new"].get("ok")
    if ok:
        L.append("- 生成器**无需修改**即可消费 255130 的 CardDefs（结构兼容）。")
        L.append(f"- 差异主要体现在条目数/数值：例如池内随从 "
                 f"{new['summary'].get('pool_minions', {}).get('count')} vs "
                 f"{old['summary'].get('pool_minions', {}).get('count')}。")
        L.append("- 若 INVALID card_type 数量上升，说明出现生成器未收录的新 CardType；"
                 "需在 `generate_bg_data.py` 增补分支（本轮不改工具，仅记录）。")
    else:
        L.append("- 生成失败：需按 `docs/OFFICIAL_EXACTNESS.md` 的升级流程人工定位；"
                 "最小修复只动 `tools/generate_bg_data.py` 的解析/白名单，不动 `hsrl2/`。")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
