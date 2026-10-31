#!/usr/bin/env python3
"""载体清单与识别 + s15 rollout 审计（离线、纯 CPU、不训练）。

三件事：

1. **生成 ``data/scaling/carriers.json``**：从
   ``rust/crates/hsbg-engine/data/cards.json``（文本正则）+
   ``rust/crates/hsbg-engine/src/content/*.rs``（``listens: ev::SPELL_CAST``）
   + ``hsbg_engine.catalog_json()``（``in_pool`` / ``implemented`` / ``tier``）
   三重取证，登记所有「施法时触发 / 被施法时成长」的随从，并给每张卡
   标上触发类、每施法期望收益、是否池内/已实现、金色 id。
2. **跑一批带载体追踪的 rollout**（``--run``）：默认用 s15 当前权重
   （``runs/az_entity_s15/model.pt``）+ s15 训练同分布（5 席人类战团 p0.9 +
   2 席镜像 p0.2 + bot），逐回合记录：战团 Σ、tier、金币、**场上载体**、
   **商店/手牌见过的载体**、**买过的载体**、引擎 ``record_log`` 解析出的
   **每次施法及其目标** → 对载体施法次数。
3. **审计已有 rollout**（``--source``）：兼容
   ``runs/scaling_signal/rollouts/real.jsonl``（历史行只有 ``board_cards`` 卡下标，
   本脚本会映射回卡 id；历史行没有逐次施法信息 → 对载体施法次数为 0，
   会显式标注）。

输出：``runs/scaling_carrier/audit_<tag>.json`` + ``.md``。

用法::

  # 1) 只生成/刷新载体清单
  PYTHONPATH=rust/python:. python scripts/carrier_audit.py --build-catalog

  # 2) 跑 200 局 s15 当前权重 + 完整审计
  PYTHONPATH=rust/python:. python scripts/carrier_audit.py --run \
      --checkpoint runs/az_entity_s15/model.pt --games 200 --workers 8 \
      --tag s15_current

  # 3) 审计历史 rollout（复现 6–9% 窄口径）
  PYTHONPATH=rust/python:. python scripts/carrier_audit.py \
      --source runs/scaling_signal/rollouts/real.jsonl --tag legacy_real
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import carrier_common as C  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
# 1. 清单
# ══════════════════════════════════════════════════════════════════════════

def write_catalog(catalog: dict, path: str = C.CATALOG_OUT) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def catalog_markdown(catalog: dict) -> str:
    emap = C.entry_map(catalog)
    prim = [emap[x] for x in catalog["primary_ids"] if x in emap]
    prim.sort(key=lambda x: (x.get("golden") or False, -int(x.get("priority") or 0),
                             int(x["tier"]), x["id"]))
    L = ["## 载体清单（主集合：池内 + 已实现 + tier≤6 + 成长）", "",
         "| 卡 | id | tier | 触发 | 每施法期望 Σ | 金色 | 复利 | 池内 |",
         "|---|---|---:|---|---:|---|---|---|"]
    for x in prim:
        per = x.get("per_cast")
        per_s = ("?" if per is None else
                 f"+{per.get('atk', 0)}/+{per.get('hp', 0)} ×{x.get('unit') or ''}")
        L.append(
            f"| {x.get('name')} | `{x['id']}` | {x['tier']} | {x['trigger']}"
            f"{('/' + str(x['trigger_race'])) if x.get('trigger_race') else ''} "
            f"| {per_s}（≈{x.get('expected_sigma_per_cast')} Σ） "
            f"| {'✓' if x.get('golden') else ''} "
            f"| {'✓' if x.get('compounding') else ''} "
            f"| {'✓' if x.get('in_tavern_pool') else ''} |")
    L += ["", "### 排除项（登记但不进主集合）", "",
          "| 卡 | id | tier | 触发 | 原因 |", "|---|---|---:|---|---|"]
    for x in sorted((y for y in catalog["carriers"] if not y["is_primary"]),
                    key=lambda y: (int(y["tier"]), y["id"])):
        L.append(f"| {x.get('name')} | `{x['id']}` | {x['tier']} | "
                 f"{x['trigger']} | {x.get('exclude_reason')} |")
    return "\n".join(L) + "\n"


# ══════════════════════════════════════════════════════════════════════════
# 2. 历史 rollout 适配
# ══════════════════════════════════════════════════════════════════════════

def adapt_legacy(rows: list, catalog: dict) -> list:
    """把 scaling_signal 的旧行（``board_cards`` 是卡下标）转成载体 id 口径。

    注意：``player_json`` 的 ``Minion.card`` 是 **0-based CardId**，而
    ``hsbg_engine.card_info(i)`` 是 **1-based**（``CardId(i-1)``）。历史脚本
    ``scaling_signal_analysis.card_id_of`` 直接用 ``card_info(i)``，**整体错位一张**，
    所以旧文档里的「载体 6–9%」是错映射的产物（详见 docs/CARRIER_SCALING.md §5）。
    这里用 ``catalog_json()`` 的 ``cid`` 做正确映射。
    """
    cids = C.ids_from_catalog(catalog, "primary")
    try:
        import hsbg_engine as E  # noqa: PLC0415
        cid2id = {int(c["cid"]): str(c["id"])
                  for c in json.loads(E.catalog_json())}
    except BaseException:  # noqa: BLE001
        E = None
        cid2id = {}

    def card_id(v) -> str:
        try:
            iv = int(v)
        except (TypeError, ValueError):
            return ""
        if iv in cid2id:
            return cid2id[iv]
        if E is not None:
            try:
                return str(E.card_info(iv + 1)[0] or "")   # 1-based
            except BaseException:  # noqa: BLE001
                return ""
        return ""

    out = []
    for r in rows:
        if r.get("error") or not r.get("turns"):
            out.append(r)
            continue
        turns = []
        for t in r.get("turns") or []:
            t = dict(t)
            if "board_carriers" not in t:
                bc = [card_id(v) for v in (t.get("board_cards") or [])]
                t["board_carriers"] = [x for x in bc if x in cids]
                t["board_ids"] = bc
            t.setdefault("shop_carrier_ids", [])
            t.setdefault("hand_carrier_ids", [])
            t.setdefault("casts_turn", 0)
            t.setdefault("casts_on_carrier_turn", 0)
            turns.append(t)
        r = dict(r)
        r["turns"] = turns
        r.setdefault("carrier_turns",
                     sum(1 for t in turns if t["board_carriers"]))
        r.setdefault("carrier_ever_on_board", bool(r["carrier_turns"]))
        r.setdefault("carrier_ever_in_shop", False)
        r.setdefault("carrier_bought", [])
        r.setdefault("casts_total", 0)
        r.setdefault("casts_on_carrier", 0)
        r.setdefault("casts_on_carrier_choice", 0)
        r["legacy_board_cards_mapped"] = True
        out.append(r)
    return out


# ══════════════════════════════════════════════════════════════════════════
# 3. 报告
# ══════════════════════════════════════════════════════════════════════════

def _fmt(v, nd=3):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def report_markdown(summ: dict, catalog: dict) -> str:
    c = summ["carrier"]
    s = summ["strength12"]
    corr = summ["corr_carrier_turns_str12"]
    gate = summ.get("gate") or {}
    L = [f"# 载体审计：{summ.get('tag')}", "",
         f"- 局数 {summ['games']}（错误 {summ['errors']}，truncated {summ['truncated']}）"
         f"，策略 `{summ.get('policy')}`，平均名次 {_fmt(summ.get('mean_rank'))}"
         f"，top4 {_fmt(summ.get('top4'))}",
         f"- 主集合 id 数 {c['primary_ids']}（含金色），窄口径 id 数 {c['narrow_ids']}",
         "", "## 载体出现率", "",
         "| 口径 | 值 |", "|---|---:|",
         f"| 局级（曾上场，主集合） | **{c['carrier_encounter_rate']:.1%}** |",
         f"| 局级（曾上场，窄口径 5+Felboar） | {c['carrier_encounter_rate_narrow']:.1%} |",
         f"| t9 在场（主集合） | {c['carrier_t9_rate']:.1%} |",
         f"| t9 在场（窄口径） | {c.get('carrier_t9_rate_narrow', 0):.1%} |",
         f"| t12 在场 | {c['carrier_t12_rate']:.1%} |",
         f"| 商店曾出现 | {c['carrier_shop_offer_rate']:.1%} |",
         f"| 手牌曾出现 | {c['carrier_hand_rate']:.1%} |",
         f"| 实际买过 | {c['carrier_bought_rate']:.1%} |",
         f"| 大厅有该种族（可抽到） | {c['carrier_race_available_rate']:.1%} |",
         f"| 可抽到时商店出现 | {c['carrier_offer_given_available_rate']:.1%} |",
         f"| 回合级（招募末在场回合占比） | {c['carrier_turn_rate']:.1%} |",
         f"| 回合级（可抽到时的回合占比） | {c['carrier_turn_rate_given_available']:.1%} |",
         f"| 平均在场回合数 | {_fmt(c['carrier_turns_mean'])} |",
         "", "## t12 Σ 分布（有载体 vs 无载体）", "",
         "| 组 | n | mean | p25 | p50 | p75 | p90 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for name in ("all", "with_carrier", "without_carrier",
                 "with_carrier_narrow", "without_carrier_narrow"):
        d = s.get(name) or {}
        L.append(f"| {name} | {d.get('n', 0)} | {_fmt(d.get('mean'))} | "
                 f"{_fmt(d.get('p25'))} | {_fmt(d.get('p50'))} | "
                 f"{_fmt(d.get('p75'))} | {_fmt(d.get('p90'))} |")
    L += ["", f"均值差（有−无）= {_fmt(s.get('mean_diff'))} Σ，"
              f"95%CI {s.get('mean_diff_ci95')}", "",
          "## 对载体施法", "",
          "| 指标 | 值 |", "|---|---:|",
          f"| 每局施法总数（mean） | {_fmt(c['casts_total_mean'], 2)} |",
          f"| 每局**触发载体**的施法（mean，全部局） | {_fmt(c['casts_on_carrier_mean'], 2)} |",
          f"| 触发载体施法（有载体的局，mean） | "
          f"{_fmt(c['casts_on_carrier_mean_given_carrier'], 2)} |",
          f"| 触发载体施法 p50/p90/max（全部局） | "
          f"{_fmt(c['casts_on_carrier_dist'].get('p50'), 1)} / "
          f"{_fmt(c['casts_on_carrier_dist'].get('p90'), 1)} / "
          f"{_fmt(c['casts_on_carrier_dist'].get('max'), 1)} |",
          f"| 每个载体在场回合的触发施法 | "
          f"{_fmt(c['casts_per_carrier_turn'], 2)} |",
          f"| strict：目标选择命中载体（mean） | "
          f"{_fmt(c['casts_on_carrier_choice_mean'], 2)} |",
          "", "## 相关（后期离线门）", "",
          f"- **r(载体在场回合数, Σ₁₂) = {_fmt(corr.get('pearson'))}**，"
          f"95%CI {corr.get('pearson_ci95')}（Pearson；n={corr.get('n')}）",
          f"- Spearman = {_fmt(corr.get('spearman'))}，95%CI {corr.get('spearman_ci95')}",
          f"- r(对载体施法次数, Σ₁₂) = "
          f"{_fmt((summ.get('corr_casts_on_carrier_str12') or {}).get('pearson'))}，"
          f"95%CI {(summ.get('corr_casts_on_carrier_str12') or {}).get('pearson_ci95')}",
          "", "## 退火门", "",
          f"- 载体率 {gate.get('carrier_encounter_rate', 0):.1%} "
          f"≥ {gate.get('carrier_target', 0.25):.0%}? "
          f"**{'✓' if gate.get('carrier_ok') else '✗'}**",
          f"- t12 Σ p50 {_fmt(gate.get('str12_p50'), 1)} "
          f"≥ {gate.get('str12_target')}? "
          f"**{'✓' if gate.get('str12_ok') else '✗'}**",
          f"- r(载体回合数, Σ₁₂) = {_fmt(gate.get('corr_carrier_turns_str12'))} > 0? "
          f"**{'✓' if gate.get('corr_ok') else '✗'}**",
          f"- 全门通过：**{'✓' if gate.get('all_ok') else '✗'}**", ""]
    # 每张载体
    per = c.get("per_carrier") or {}
    if per:
        L += ["## 每张载体的出现/购买", "",
              "| 卡 | tier | 触发 | 场上局数 | 商店局数 | 买过局数 | 在场回合 |",
              "|---|---:|---|---:|---:|---:|---:|"]
        for cid, rec in sorted(per.items(), key=lambda kv: -kv[1]["on_board_games"]):
            L.append(f"| {rec['name']} | {rec['tier']} | {rec['trigger']} | "
                     f"{rec['on_board_games']} | {rec['shop_games']} | "
                     f"{rec['bought_games']} | {rec['turns']} |")
    return "\n".join(L) + "\n"


# ══════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build-catalog", action="store_true",
                    help="只生成 data/scaling/carriers.json")
    ap.add_argument("--catalog", default=C.CATALOG_OUT)
    ap.add_argument("--rebuild", action="store_true", help="强制重建清单")
    ap.add_argument("--run", action="store_true", help="跑新的 s15 rollout")
    ap.add_argument("--checkpoint", default="runs/az_entity_s15/model.pt")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--seed-base", type=int, default=900000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--tag", default="s15_current")
    ap.add_argument("--bot-only", action="store_true",
                    help="7 个引擎 bot（与 quality_monitor 566 口径同）")
    ap.add_argument("--source", action="append", default=[],
                    help="已有 rollout jsonl（可多次）")
    ap.add_argument("--gold", type=int, default=0)
    ap.add_argument("--max-actions-per-turn", type=int, default=40)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--record-log", type=int, default=1)
    ap.add_argument("--human-boards",
                    default="data/real_library/library_real_quasi_full.jsonl")
    ap.add_argument("--human-board-p", type=float, default=0.9)
    ap.add_argument("--human-board-seats", type=int, default=5)
    ap.add_argument("--human-board-sample", default="auto")
    ap.add_argument("--human-board-set-tier", type=int, default=1)
    ap.add_argument("--human-board-fidelity", default="full")
    ap.add_argument("--human-board-fast-inject", type=int, default=1)
    ap.add_argument("--mirror-snaps", default="runs/library/snaps_champ")
    ap.add_argument("--mirror-p", type=float, default=0.2)
    ap.add_argument("--mirror-seats", type=int, default=2)
    ap.add_argument("--mirror-sample", default="p75")
    ap.add_argument("--out-dir", default="runs/scaling_carrier")
    args = ap.parse_args()

    os.makedirs(os.path.abspath(args.out_dir), exist_ok=True)
    catalog = C.build_catalog() if (args.rebuild or args.build_catalog
                                    or not os.path.isfile(args.catalog)) \
        else C.load_or_build_catalog(args.catalog)
    write_catalog(catalog, args.catalog)
    print(json.dumps(catalog["meta"], ensure_ascii=False, indent=1))
    if args.build_catalog and not (args.run or args.source):
        print(f"[out] {args.catalog}")
        return 0

    rows: list = []
    if args.run:
        cat = C.load_or_build_catalog(args.catalog)
        primary = C.ids_from_catalog(cat, "primary")
        names = {str(x.get("name")) for x in (cat.get("carriers") or [])
                 if x.get("is_primary") or x.get("in_tavern_pool")}
        emap = C.entry_map(cat)
        races = set()
        for cid in primary:
            for r in (emap.get(cid, {}).get("races") or []):
                races.add(str(r))
        triggers = {cid: str(emap.get(cid, {}).get("trigger") or "")
                    for cid in primary}
        bot_only = bool(args.bot_only)
        cfg = {
            "policy": "net", "tag": str(args.tag),
            "checkpoint": os.path.abspath(args.checkpoint),
            "device": str(args.device), "seed_base": int(args.seed_base),
            "gold": int(args.gold),
            "max_steps": int(args.max_steps),
            "max_actions_per_turn": int(args.max_actions_per_turn),
            "move_guard": 1, "move_cap": 3, "move_repeat_limit": 2,
            "record_log": int(args.record_log),
            "carrier_ids": sorted(primary), "carrier_names": sorted(names),
            "carrier_races": sorted(races), "carrier_trigger": triggers,
            "human_boards": str(args.human_boards),
            "human_board_p": 0.0 if bot_only else float(args.human_board_p),
            "human_board_seats": int(args.human_board_seats),
            "human_board_sample": str(args.human_board_sample),
            "human_board_set_tier": int(args.human_board_set_tier),
            "human_board_fidelity": str(args.human_board_fidelity),
            "human_board_fast_inject": int(args.human_board_fast_inject),
            "mirror_snaps": str(args.mirror_snaps),
            "mirror_p": 0.0 if bot_only else float(args.mirror_p),
            "mirror_seats": int(args.mirror_seats),
            "mirror_sample": str(args.mirror_sample),
        }
        seeds = [int(args.seed_base) + i for i in range(int(args.games))]
        print(f"[carrier_audit] run {len(seeds)} games workers={args.workers} "
              f"tag={args.tag} bot_only={bot_only}", flush=True)
        rows = C.run_rollout(cfg, seeds, workers=int(args.workers))
        out_jsonl = os.path.join(os.path.abspath(args.out_dir),
                                 f"{args.tag}.jsonl")
        C.write_rollout(rows, out_jsonl, meta={
            "tag": args.tag, "policy": "net", "games": len(rows),
            "checkpoint": cfg["checkpoint"], "bot_only": bot_only,
            "carriers": os.path.abspath(args.catalog),
            "config": {k: v for k, v in cfg.items()
                       if k not in ("carrier_ids", "carrier_names")},
        })
        print(f"[out] {out_jsonl}")

    srcs = list(args.source)
    if not rows and srcs:
        for s in srcs:
            for p in sorted(glob.glob(s)) or [s]:
                print(f"[read] {p}", flush=True)
                rows.extend(C.read_rollout(p))
        rows = adapt_legacy(rows, catalog)
    if not rows:
        print("[error] 没有 rollout 可审计（用 --run 或 --source）", file=sys.stderr)
        return 2

    summ = C.summarize(rows, catalog)
    summ["gate"] = C.gate_check(summ)
    out_json = os.path.join(os.path.abspath(args.out_dir),
                            f"audit_{args.tag}.json")
    out_md = os.path.join(os.path.abspath(args.out_dir),
                          f"audit_{args.tag}.md")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summ, f, ensure_ascii=False, indent=1)
    md = "# 载体清单（自动生成）\n\n" + catalog_markdown(catalog) + "\n\n" \
         + report_markdown(summ, catalog)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(md)
    brief = {k: summ[k] for k in ("games", "errors", "tag", "policy",
                                  "mean_rank", "top4")}
    brief["fallback_actions"] = summ.get("fallback_actions")
    print(json.dumps(brief, ensure_ascii=False))
    print(json.dumps(summ["carrier"], ensure_ascii=False, indent=1))
    print(json.dumps(summ["strength12"], ensure_ascii=False, indent=1))
    print(json.dumps(summ["corr_carrier_turns_str12"], ensure_ascii=False))
    print(json.dumps(summ["gate"], ensure_ascii=False))
    print(f"[out] {out_json}")
    print(f"[out] {out_md}")
    return 0 if summ["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
