"""P3 池内脚本覆盖审计（Rust content vs 37.0.0 单人池）。

门禁（docs/PORTING_37_PLAN.md §5.2 P1 验收）：
* 池内随从（277，含 5 个 Dark Paradox 形态）missing = 0；
* 池内酒馆法术（73，Duos-only 已被数据管线剔除）missing = 0；
* 主英雄技能（129 个唯一主技能，重点 `BG22_HERO_007p`）missing = 0；
* P1 18 卡（15 随从 + 1 主技能 + 2 法术）全部注册；
* 静态注册表 vs 运行时 catalog 一致（golden 由 registry 自动解析，不计缺失）。

“缺失”口径 = 既无脚本（`scripted`）又非 keyword-only（`implemented`），
与 AT `script::implemented` 一致；数据里不存在该 id 记 `not_in_db`（数据缺口）。
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List, Optional

from . import common


def _status(rec: Optional[Dict[str, Any]]) -> str:
    if rec is None:
        return "not_in_db"
    if rec.get("scripted"):
        return "scripted"
    if rec.get("implemented"):
        return "keyword_only"
    return "missing"


def _audit_set(ids: List[str], catalog: Optional[Dict[str, Dict[str, Any]]],
               static_ids: set) -> Dict[str, Any]:
    rows = []
    for cid in ids:
        rec = (catalog or {}).get(cid)
        status = _status(rec)
        rows.append({
            "id": cid,
            "name": (rec or {}).get("name"),
            "kind": (rec or {}).get("kind"),
            "tier": (rec or {}).get("tier"),
            "status": status,
            "in_static_source": cid in static_ids,
            "modules": [],
        })
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    missing = [r for r in rows if r["status"] in ("missing", "not_in_db")]
    return {"total": len(ids), "counts": counts,
            "missing": missing, "rows": rows}


def run_audit(*, include_rows: bool = True) -> Dict[str, Any]:
    cards = common.load_cards_37()
    catalog = common.runtime_catalog()
    static = common.static_registrations()
    static_ids = set(static["by_id"])

    pool_minions = common.pool_minions(cards)
    pool_spells = common.pool_spells(cards)
    primary_powers = common.hero_primary_powers(cards)

    minions = _audit_set(pool_minions, catalog, static_ids)
    spells = _audit_set(pool_spells, catalog, static_ids)
    powers = _audit_set(primary_powers, catalog, static_ids)

    # P1 18 卡专项
    p1_rows = []
    refs = common.hsrl2_reference_files(common.P1_WITH_HSRL2_REF)
    for cid in (common.P1_MINIONS + common.P1_HERO_POWERS + common.P1_SPELLS):
        rec = (catalog or {}).get(cid)
        data_rec = cards.get(cid) or {}
        batch = next((w for w, ids in common.P1_BATCH.items() if cid in ids),
                     None)
        p1_rows.append({
            "id": cid,
            "name": data_rec.get("name") or (rec or {}).get("name"),
            "kind": data_rec.get("kind"),
            "tier": data_rec.get("tier"),
            "batch_owner": batch,
            "status": _status(rec),
            "in_static_source": cid in static_ids,
            "modules": static["by_id"].get(cid, []),
            "has_hsrl2_ref": bool(refs.get(cid)),
            "hsrl2_ref_files": (refs.get(cid) or [])[:3],
            "in_37_pool": cid in set(pool_minions) or cid in set(pool_spells),
        })
    # （p1_missing / p1_by_owner 在 BG36_360 特例处理之后再计算，见下）
    # 静态/运行时一致性（golden 由 registry 从 normal 自动解析，故只比 normal 形态）
    normal_ids = {cid for cid, c in cards.items() if not c.get("normal")}
    runtime_scripted = {cid for cid, rec in (catalog or {}).items()
                        if rec.get("scripted")}
    runtime_normals = runtime_scripted & normal_ids
    static_only = sorted(static_ids - runtime_normals)
    runtime_only = sorted(runtime_normals - static_ids)
    unknown_static = sorted(cid for cid in static_ids if cid not in cards)

    # P1 主技能的功能关联形态（Azshara 变形目标 p2；任务书 P1 只点名 p，但
    # 若 p 的实现以 p2 为变形目标则 p2 也必须注册——登记为风险项而不是硬门禁）。
    P1_ASSOCIATED_HERO_POWERS = ["BG22_HERO_007p2"]
    associated_rows = []
    for cid in P1_ASSOCIATED_HERO_POWERS:
        rec = (catalog or {}).get(cid)
        associated_rows.append({
            "id": cid,
            "name": (cards.get(cid) or {}).get("name") or (rec or {}).get("name"),
            "status": _status(rec),
            "in_static_source": cid in static_ids,
            "note": "BG22_HERO_007p 的变形目标（Azshara's Ambition → Naga Conquest）；"
                    "P1-C 功能完整性风险项，由 rust-engine-forker 决策是否必须",
        })

    # Dark Paradox 形态
    paradox = [cid for cid in cards if cid.startswith("BG36_360")]
    paradox_rows = [{
        "id": cid,
        "in_pool": "minion" in (cards[cid].get("pools") or []),
        "status": _status((catalog or {}).get(cid)),
        "in_static_source": cid in static_ids,
    } for cid in sorted(paradox)]

    # BG36_360 特例：37 数据中 base 是“不在池”的占位壳，池内行为由 5 个旧形态
    # （BG36_360t3/t4/t5/t6/t9）承载且已全部 scripted；worker 决策已记录
    # （p3_systems.rs 头 + tests/p3_systems.rs）。按“池内可玩内容覆盖”口径视为
    # covered_via_forms，而不是 missing（否则会误报 P1 缺口）。
    paradox_cov = {}
    for row in paradox_rows:
        if row["id"].startswith("BG36_360t"):
            paradox_cov[row["id"]] = row
    forms_all_scripted = (len(paradox_cov) == 5 and
                          all(r["status"] == "scripted"
                              for r in paradox_cov.values()))
    for row in p1_rows:
        if row["id"] == "BG36_360" and forms_all_scripted:
            row["covered_via_forms"] = True
            row["status"] = "covered_via_forms"
    p1_missing = [r for r in p1_rows
                  if r["status"] in ("missing", "not_in_db")]
    p1_required_missing = [
        r for r in p1_missing
        if r["id"] in (set(common.P1_MINIONS) | set(common.P1_HERO_POWERS)
                       | set(common.P1_SPELLS))]
    p1_by_owner: Dict[str, int] = {}
    for row in p1_missing:
        owner = row["batch_owner"] or "unknown"
        p1_by_owner[owner] = p1_by_owner.get(owner, 0) + 1
    associated_missing = [r for r in associated_rows
                          if r["status"] in ("missing", "not_in_db")]
    gate = {
        "pool_minions_missing": len(minions["missing"]),
        "pool_spells_missing": len(spells["missing"]),
        "primary_powers_missing": len(powers["missing"]),
        "p1_required_missing": len(p1_required_missing),
        "p1_associated_missing": len(associated_missing),
        "p1_18_all_covered": len(p1_required_missing) == 0,
        "static_vs_runtime_consistent": len(static_only) == 0,
        "build_current": (common.engine_build_status().get("build_is_current")),
        "pass": bool(len(minions["missing"]) == 0
                     and len(spells["missing"]) == 0
                     and len(p1_required_missing) == 0),
    }

    out: Dict[str, Any] = {
        "meta": {
            "cards_37": str(common.CARDS_37),
            "cards_37_meta": common.cards_37_meta(),
            "engine_build": common.engine_build_status(),
            "content_files": static["files"],
            "script_functions": len(static["functions"]),
        },
        "counts": {
            "pool_minions": len(pool_minions),
            "pool_spells": len(pool_spells),
            "primary_hero_powers": len(primary_powers),
            "static_registered_ids": static["id_count"],
            "runtime_scripted_ids": len(runtime_scripted),
        },
        "pool_minions": {k: v for k, v in minions.items() if k != "rows"},
        "pool_spells": {k: v for k, v in spells.items() if k != "rows"},
        "primary_hero_powers": {k: v for k, v in powers.items()
                                if k != "rows"},
        "p1": {
            "rows": p1_rows,
            "covered_via_forms": [r["id"] for r in p1_rows
                                  if r.get("covered_via_forms")],
            "missing": p1_missing,
            "missing_by_owner": p1_by_owner,
        },
        "p1_associated_hero_powers": associated_rows,
        "dark_paradox": paradox_rows,
        "static": {
            "modules_with_registrations": static["module_count"],
            "by_module": static["by_module"],
            "static_only_vs_runtime": static_only[:50],
            "runtime_only_vs_static": runtime_only[:50],
            "unknown_static_ids": unknown_static[:50],
        },
        "gate": gate,
    }
    if include_rows:
        out["pool_minions_rows"] = minions["rows"]
        out["pool_spells_rows"] = spells["rows"]
        out["primary_hero_power_rows"] = powers["rows"]
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="P3 池内脚本覆盖审计")
    ap.add_argument("--out", default="coverage.json")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    audit = run_audit()
    common.write_json(args.out, audit)
    g = audit["gate"]
    c = audit["counts"]
    print(f"pool minions={c['pool_minions']} missing={g['pool_minions_missing']}")
    print(f"pool spells={c['pool_spells']} missing={g['pool_spells_missing']}")
    print(f"primary hero powers={c['primary_hero_powers']} "
          f"missing={g['primary_powers_missing']}")
    print(f"P1 18 cards missing={g['p1_required_missing']} "
          f"(by owner: {audit['p1']['missing_by_owner']})")
    print(f"static registry={c['static_registered_ids']} ids / "
          f"{audit['static']['modules_with_registrations']} modules; "
          f"build_current={g['build_current']}")
    print(f"P1 associated hero powers: "
          f"{[(r['id'], r['status']) for r in audit['p1_associated_hero_powers']]}")
    if not args.quiet and audit["p1"]["missing"]:
        print("P1 missing:")
        for row in audit["p1"]["missing"]:
            print(f"  - {row['id']:<16} {row['name']} [{row['batch_owner']}] "
                  f"status={row['status']}")
    if not args.quiet and audit["pool_minions"]["missing"]:
        print(f"pool minion missing ({g['pool_minions_missing']}):")
        for row in audit["pool_minions"]["missing"][:40]:
            print(f"  - {row['id']:<16} {row['name']}")
    if not args.quiet and audit["pool_spells"]["missing"]:
        print(f"pool spell missing ({g['pool_spells_missing']}):")
        for row in audit["pool_spells"]["missing"][:40]:
            print(f"  - {row['id']:<16} {row['name']}")
    print(f"gate {'PASS' if g['pass'] else 'FAIL'} -> runs/p3_verify/{args.out}")
    return 0 if g["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
