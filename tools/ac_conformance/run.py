"""一键跑全部跨引擎一致性场景 → runs/conformance/report.json。

用法::

    python3 -m tools.ac_conformance.run                    # 全部场景，48 seeds
    python3 -m tools.ac_conformance.run --seeds 16 --only C01,K05
    python3 -m tools.ac_conformance.run --out runs/conformance/report.json

输出：
* stdout：逐场景判定表 + 分类统计 + ENGINE_BUG 清单；
* JSON：meta（版本/参照 hash）、data_diff 摘要、逐场景观察与证据、统计。

只读两个引擎；不写 `hsrl2/**`、`data/**`、参照仓库。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import compare, data_diff, hsrl2_api, paths, scenarios, tavern_api


def _load_reference_index() -> Dict[str, Any]:
    """卡牌可比性索引：哪些共享卡在两版本间卡面数据一致。"""
    cards = data_diff.compare_cards()
    m = cards["minions"]
    bad = set()
    for group in ("stat_diff", "tier_diff", "keyword_diff", "race_diff"):
        for row in m[group]:
            bad.add(row["id"])
    at = data_diff.load_autotavern_cards()
    hs = data_diff.load_hsrl2_cards()
    shared = set(at) & set(hs)
    return {
        "shared": shared,
        "bad": bad,
        "data_diff": cards,
    }


def _run_duel(sc, seeds: int, idx: Dict[str, Any]) -> Dict[str, Any]:
    row: Dict[str, Any] = {"id": sc.id, "title": sc.title, "kind": sc.kind,
                           "group": sc.group, "expected": sc.expected,
                           "why": sc.why}
    tavern_err = hs_err = None
    try:
        g = tavern_api.build_duel(
            0, sc.a, sc.b, turn=sc.turn, tier_a=sc.tier_a,
            tier_b=sc.tier_b)
        t_obs = tavern_api.combat_trials(g, seeds)
        t_sample = tavern_api.combat_sample(g)
        t_obs["sample"] = t_sample
    except Exception as exc:  # noqa: BLE001
        tavern_err = f"{type(exc).__name__}: {exc}"
        t_obs = {"n": 0, "wins": {"a": 0, "b": 0, "tie": 0},
                 "damage_by_winner": {"a": [], "b": []}, "truncated": 0,
                 "sample": {}}
    try:
        h_obs = hsrl2_api.run_trials(
            sc.a, sc.b, seeds=seeds, turn=sc.turn, tier_a=sc.tier_a,
            tier_b=sc.tier_b, alive=sc.alive)
    except Exception as exc:  # noqa: BLE001
        hs_err = f"{type(exc).__name__}: {exc}"
        h_obs = {"n": 0, "wins": {"a": 0, "b": 0, "tie": 0},
                 "damage_by_winner": {"a": [], "b": []},
                 "attacker_first": {}, "truncated": 0, "errors": [hs_err]}

    fa_detail = None
    if sc.check_first_attacker:
        t_attackers: List[str] = []
        for s in range(6):
            try:
                gs = tavern_api.build_duel(
                    s, sc.a, sc.b, turn=sc.turn, tier_a=sc.tier_a,
                    tier_b=sc.tier_b)
                smp = tavern_api.combat_sample(gs)
                if smp.get("first_attacker"):
                    t_attackers.append(smp["first_attacker"])
            except Exception:  # noqa: BLE001
                pass
        fa_detail = compare.compare_first_attacker(
            t_attackers, h_obs.get("attacker_first") or {},
            int(h_obs.get("n") or 0))
    detail = compare.compare_duel(t_obs, h_obs)
    if fa_detail is not None:
        detail["first_attacker"] = fa_detail
    classification, reason = compare.classify_duel(sc, detail, fa_detail)
    row.update(
        classification=classification, reason=reason, detail=detail,
        tavern={"sample": t_obs.get("sample"), "wins": t_obs["wins"]},
        hsrl2={"sample": h_obs.get("sample"), "wins": h_obs["wins"]},
        error=tavern_err or hs_err,
    )
    return row


def _run_card_duel(sc, seeds: int, idx: Dict[str, Any]) -> Dict[str, Any]:
    row: Dict[str, Any] = {"id": sc.id, "title": sc.title, "kind": sc.kind,
                           "group": sc.group, "expected": sc.expected,
                           "why": sc.why}
    missing = [cid for cid in sc.card_a + sc.card_b
               if cid not in idx["shared"]]
    bad = [cid for cid in sc.card_a + sc.card_b
           if cid in idx["bad"]]
    if missing or bad:
        row.update(classification="DATA_GAP",
                   reason=f"missing={missing} data_diff={bad}",
                   detail={"missing_cards": missing, "data_diff_cards": bad})
        return row
    try:
        g = tavern_api.build_duel(
            0, sc.units_a, sc.units_b, turn=sc.turn, tier_a=sc.tier_a,
            tier_b=sc.tier_b,
            card_a=sc.card_a, card_b=sc.card_b,
            golden_a=sc.golden_a, golden_b=sc.golden_b)
        t_obs = tavern_api.combat_trials(g, seeds)
        t_obs["sample"] = tavern_api.combat_sample(g)
    except Exception as exc:  # noqa: BLE001
        row.update(classification="UNSUPPORTED",
                   reason=f"AutoTavern construct failed: {exc}")
        return row
    try:
        h_obs = hsrl2_api.run_trials(
            sc.units_a, sc.units_b, seeds=seeds, turn=sc.turn,
            tier_a=sc.tier_a, tier_b=sc.tier_b, alive=sc.alive,
            card_a=sc.card_a, card_b=sc.card_b,
            golden_a=sc.golden_a, golden_b=sc.golden_b)
    except Exception as exc:  # noqa: BLE001
        row.update(classification="UNSUPPORTED",
                   reason=f"hsrl2 construct failed: {exc}")
        return row
    detail = compare.compare_duel(t_obs, h_obs)
    classification, reason = compare.classify_duel(sc, detail)
    row.update(
        classification=classification, reason=reason, detail=detail,
        tavern={"sample": t_obs.get("sample"), "wins": t_obs["wins"]},
        hsrl2={"sample": h_obs.get("sample"), "wins": h_obs["wins"]},
    )
    return row


def _run_economy(sc, t_probe: Dict[str, Any], h_probe: Dict[str, Any]) -> Dict[str, Any]:
    detail, classification = compare.compare_economy(sc, t_probe, h_probe)
    return {"id": sc.id, "title": sc.title, "kind": sc.kind,
            "group": sc.group, "expected": sc.expected,
            "why": sc.why, "classification": classification,
            "reason": (sc.why if classification != "MATCH"
                       else "autotavern == hsrl2"),
            "detail": detail}


def _run_flow(sc, tavern_seeds=(5, 6), hsrl2_seed=2000) -> Dict[str, Any]:
    problems: List[str] = []
    tavern_games = []
    try:
        for seed in tavern_seeds:
            obs = tavern_api.run_bot_game(int(seed))
            tavern_games.append(obs)
            pl = sorted(obs.get("placements") or [])
            if not obs.get("over"):
                problems.append(f"tavern seed={seed} game not over")
            if pl != list(range(1, len(pl) + 1)):
                problems.append(f"tavern seed={seed} placements invalid: {pl}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"tavern exception: {exc}")
    hs_games = []
    try:
        obs_h = hsrl2_api.full_game_invariants(hsrl2_seed)
        hs_games.append(obs_h)
        if not (obs_h.get("finished") or int(obs_h.get("turn") or 0) <= 50):
            problems.append(f"hsrl2 seed={hsrl2_seed} unfinished: {obs_h}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"hsrl2 exception: {exc}")
    detail = {
        "tavern": tavern_games,
        "hsrl2": hs_games,
        "problems": problems,
        "verdict": "exact_match" if not problems else "mismatch",
    }
    return {"id": sc.id, "title": sc.title, "kind": sc.kind,
            "group": sc.group, "expected": sc.expected, "why": sc.why,
            "classification": "MATCH" if not problems else "ENGINE_BUG",
            "reason": "; ".join(problems) if problems else
            "整局不变量两引擎均成立（名次唯一/对局结束/无崩溃）",
            "detail": detail}


def run_all(seeds: int = paths.DEFAULT_SEEDS,
            only: Optional[List[str]] = None,
            progress: bool = True) -> Dict[str, Any]:
    t0 = time.time()
    idx = _load_reference_index()
    selected = [s for s in scenarios.ALL_SCENARIOS
                if not only or s.id in only]
    rows: List[Dict[str, Any]] = []
    t_probe = h_probe = None
    for sc in selected:
        if sc.kind == "duel":
            row = _run_duel(sc, seeds, idx)
        elif sc.kind == "card_duel":
            row = _run_card_duel(sc, seeds, idx)
        elif sc.kind == "economy":
            if t_probe is None:
                t_probe = tavern_api.economy_probe(7)
                h_probe = hsrl2_api.economy_probe(42)
            row = _run_economy(sc, t_probe, h_probe)
        elif sc.kind == "flow":
            row = _run_flow(sc)
        else:  # pragma: no cover - 场景表写死
            raise ValueError(f"unknown scenario kind {sc.kind}")
        rows.append(row)
        if progress:
            print(f"  {row['id']:<4} {row['classification']:<15} "
                  f"{row['title'][:52]}", flush=True)

    summary = compare.summarize(rows)
    bugs = [r for r in rows if r["classification"] == "ENGINE_BUG"]
    report = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "seeds_per_distribution_scenario": seeds,
            "elapsed_s": round(time.time() - t0, 2),
            "paths": {
                "repo": str(paths.ROOT),
                "autotavern": str(paths.AUTOTAVERN_ROOT),
            },
            "versions": _versions(),
            "data_diff_summary": _data_diff_summary(idx["data_diff"]),
        },
        "rows": rows,
        "summary": summary,
        "bugs": [{"id": b["id"], "title": b["title"],
                  "reason": b["reason"]} for b in bugs],
        "notes": [
            "RNG 流与随机目标顺序是两引擎的约定差异，不计为 bug；"
            "比较语义不变量（胜负/死亡/伤害/属性/合法动作集合语义）。",
            "分布类场景每个引擎 N 个独立 trial/seed；确定性场景要求"
            "胜负与伤害完全一致。",
            "卡牌级场景只使用两版本共享且卡面数据一致的卡（data_diff）。",
        ],
    }
    report["tavern_economy_probe"] = t_probe
    report["hsrl2_economy_probe"] = h_probe
    return report


def _versions() -> Dict[str, Any]:
    import taverngym
    patch = None
    try:
        summary = json.loads((paths.HSRL2_DATA / "bg_summary.json")
                             .read_text(encoding="utf-8"))
        patch = summary.get("patch")
    except Exception:  # noqa: BLE001
        pass
    return {
        "autotavern": {
            "package_version": taverngym.version(),
            "game_version": taverngym.game_version(),
            "server_rules_version": taverngym.server_rules_version(),
            "n_actions": int(taverngym.N_ACTIONS),
            "n_cards": int(taverngym.N_CARDS),
            "source_hash": taverngym.build_info().get("source_hash"),
        },
        "hsrl2": {
            "data_patch": patch,
            "n_cards_data": len(data_diff.load_hsrl2_cards()),
        },
    }


def _data_diff_summary(diff_cards: Dict[str, Any]) -> Dict[str, Any]:
    m = diff_cards["minions"]
    p = diff_cards["pool"]
    return {
        "ids": diff_cards["ids"],
        "minions": {
            "shared": m["shared_minions"],
            "stat_diff": m["stat_diff_count"],
            "tier_diff": m["tier_diff_count"],
            "keyword_diff": m["keyword_diff_count"],
            "race_diff": m["race_diff_count"],
            "text_diff": m["text_diff_count"],
            "text_formatting_only": m["text_formatting_only_count"],
        },
        "pool": {
            "autotavern": p["autotavern_pool_minions"],
            "hsrl2": p["hsrl2_pool_minions"],
            "shared": p["shared_pool_minions"],
            "only_autotavern": len(p["only_autotavern_pool"]),
            "only_hsrl2": len(p["only_hsrl2_pool"]),
            "stat_diff": p["pool_stat_diff_count"],
        },
        "unmapped_keywords": m["unmapped_keywords"],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, default=paths.DEFAULT_SEEDS,
                    help="分布类场景每引擎 trial/seed 数（默认 48）")
    ap.add_argument("--only", default="", help="逗号分隔场景 id，如 C01,K05")
    ap.add_argument("--out", default=str(paths.RUNS_DIR / "report.json"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    only = [x.strip() for x in args.only.split(",") if x.strip()] or None
    report = run_all(seeds=args.seeds, only=only, progress=not args.quiet)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    summary = report["summary"]
    print(f"\n统计: total={summary['total']} " +
          " ".join(f"{k}={v}" for k, v in sorted(summary["counts"].items())))
    if report["bugs"]:
        print("ENGINE_BUG 清单:")
        for b in report["bugs"]:
            print(f"  {b['id']}: {b['title']} — {b['reason']}")
    print(f"耗时 {report['meta']['elapsed_s']}s → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
