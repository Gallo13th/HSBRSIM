#!/usr/bin/env python3
"""构造**场面题**（board problems）：在当前权重的自对弈关键局面上出题。

设计见 ``docs/RESEARCH_PLAN_V2.md`` §4.1 与 ``docs/BOARD_PROBLEMS.md``。核心不是「拿人类
轨迹做 BC」，而是：

1. 用**当前 s14 权重**按训练分布 rollout（人类战团 5 席 p0.9 + 镜像 2 席 p0.2 +
   move-guard 1），只在**关键局面**出题：每回合起点 + 决策分叉点（可升本 / 三连 /
   核心随从）；
2. 每道题存：观测（features+cards+合法动作，f32 可逐位复现）、当前策略动作、
   **人类参考动作 top-k**（按 ``(turn,tier)`` 从 Firestone/10k+ 动作分布匹配，且必须
   落在当前局面的合法掩码内、经过 move_guard）、以及 **t+3 回合的战团强度/tier 真实值**
   （rollout 后回填）；
3. 统计：题目数、覆盖 turn、参考解匹配率/缺失率、标签可用率、Move 守卫。

用法::

    PYTHONPATH=rust/python:. python scripts/build_board_problems.py \
      --checkpoint runs/az_entity_s14/model.pt --device cuda:7 \
      --games 16 --seed 20200 --out data/board_problems/problems.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from hsbg.az.train.board_problems import (  # noqa: E402
    DEFAULT_BC_SAMPLES,
    DEFAULT_FIRESTONE_ACTIONS,
    DEFAULT_PROBLEM_PATH,
    DEFAULT_REF_FLOORS,
    LATE_TURN_MIN,
    LateRefConfig,
    ProblemCollectConfig,
    build_human_buy_table,
    build_reference_table,
    collect_problems,
    parse_game_indices,
    parse_turn_ranges,
    ref_type_distribution,
    rewrite_problem_rows,
    write_problems,
)
from hsbg.az.train.common import engine_available  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402


def _parse_floors(spec: str):
    out = []
    for part in str(spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return tuple(sorted(set(out), reverse=True)) or DEFAULT_REF_FLOORS


def _load_jsonl(path: str):
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _file_sha256(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _print_ref_delta(name: str, before: dict, after: dict, *,
                     turns=(10, 11, 12, 13, 14, 15)) -> None:
    """打印逐 turn 的「修正前 -> 修正后」：reroll/buy 质量 + top-1 类型。"""
    for t in turns:
        a = (after.get("turns") or {}).get(str(int(t)))
        if not a:
            continue
        b = (before.get("turns") or {}).get(str(int(t))) or {}
        rb = float((b.get("mass_share") or {}).get("reroll", 0.0))
        ra = float((a.get("mass_share") or {}).get("reroll", 0.0))
        bb = float((b.get("mass_share") or {}).get("buy", 0.0))
        ba = float((a.get("mass_share") or {}).get("buy", 0.0))
        pb = float((b.get("mass_share") or {}).get("play", 0.0))
        pa = float((a.get("mass_share") or {}).get("play", 0.0))
        t1b = float(b.get("reroll_top1_share", 0.0))
        t1a = float(a.get("reroll_top1_share", 0.0))
        print(f"[ref:{name}] t{int(t):>2}: n={a['n']:>4} matched={a['matched']:>4} "
              f"| top1=reroll {t1b:.1%}->{t1a:.1%} "
              f"| mass reroll {rb:.3f}->{ra:.3f} buy {bb:.3f}->{ba:.3f} "
              f"play {pb:.3f}->{pa:.3f}", flush=True)


def _run_rewrite(args, floors, late_cfg) -> int:
    """``--rewrite-pool``：不重跑 rollout，只在已有题池上重算参考解。"""
    t0 = time.time()
    in_path = str(args.rewrite_pool)
    if not os.path.isfile(in_path):
        print(f"[error] --rewrite-pool 不存在：{in_path}", file=sys.stderr)
        return 2
    rows = _load_jsonl(in_path)
    if not rows:
        print(f"[error] --rewrite-pool 为空：{in_path}", file=sys.stderr)
        return 2
    table = build_reference_table(str(args.reference_samples), floors=floors,
                                  limit=(int(args.reference_limit) or None))
    print(f"[ref] 人类动作分布: path={table.path} floors={list(floors)} "
          f"rows={ {int(k): int(v) for k, v in table.rows.items()} }", flush=True)
    buy = (build_human_buy_table(str(args.ref_buy_table),
                                 min_freq=float(late_cfg.buy_min_freq))
           if late_cfg.enabled() else None)
    if buy is not None:
        print(f"[ref] 购买频次表: rows={buy.rows} "
              f"high={ {t: len(v) for t, v in sorted(buy.high.items())} }", flush=True)
    new_rows, rep = rewrite_problem_rows(
        rows, table, cfg=late_cfg, buy_table=buy, top_k=int(args.top_k),
        min_support=int(args.min_support), progress=True)
    before = ref_type_distribution(rows)
    after = ref_type_distribution(new_rows)
    # 诊断（只进报告，不改主结果）：top-k 截断与 cap 强度对 action 族分布的影响
    diag: Dict[str, Any] = {}
    if late_cfg.enabled():
        for kk in (16, 24):
            rr, _ = rewrite_problem_rows(
                rows, table, cfg=late_cfg, buy_table=buy, top_k=int(kk),
                min_support=int(args.min_support), progress=False)
            diag[f"top_k_{int(kk)}"] = ref_type_distribution(
                rr, turns=(13, 14, 15))
        for cap in (0.10, 0.05):
            cfg_cap = LateRefConfig(policy="fixed", turn_min=late_cfg.turn_min,
                                    reroll_cap=float(cap),
                                    buy_boost=late_cfg.buy_boost,
                                    buy_min_freq=late_cfg.buy_min_freq)
            rr, _ = rewrite_problem_rows(
                rows, table, cfg=cfg_cap, buy_table=buy,
                top_k=int(args.top_k), min_support=int(args.min_support),
                progress=False)
            diag[f"reroll_cap_{cap:.2f}"] = ref_type_distribution(
                rr, turns=(13, 14, 15))
    out_path = str(args.out)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in new_rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp, out_path)
    sha = _file_sha256(out_path)
    # 训练侧只依赖 strength_norm / horizon，其余字段从旧 meta 保留（不做统计假装）
    src_meta = os.path.splitext(in_path)[0] + ".meta.json"
    old_meta = {}
    if os.path.isfile(src_meta):
        try:
            with open(src_meta, "r", encoding="utf-8") as fh:
                old_meta = json.load(fh) or {}
        except (ValueError, OSError):
            old_meta = {}
    by_turn: dict = {}
    for r in new_rows:
        t = str(int(r.get("turn") or 0))
        by_turn[t] = int(by_turn.get(t, 0)) + 1
    meta = {
        "schema": str(old_meta.get("schema") or "board_problem_v1"),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "problems": int(len(new_rows)),
        "problems_path": out_path,
        "problems_sha256": sha,
        "by_turn": dict(sorted(by_turn.items(), key=lambda kv: int(kv[0]))),
        "strength_norm": old_meta.get("strength_norm"),
        "horizon": int(old_meta.get("horizon", 3) or 3),
        "source_pool": in_path,
        "late_ref_fix": {
            "policy": late_cfg.to_json(),
            "buy_table": (buy.to_json() if buy is not None else {}),
            "rewrite": rep,
        },
        "note": "参考解按 late_ref_policy 重算（ref_before 保留原解）；其余字段沿用旧 meta",
    }
    meta_path = os.path.splitext(out_path)[0] + ".meta.json"
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2, sort_keys=True)
    report = {
        "schema": "board_late_ref_fix_v1",
        "generated_at": meta["generated_at"],
        "pool_in": in_path, "pool_out": out_path,
        "problems_sha256": sha,
        "problems": int(len(new_rows)),
        "late_ref": late_cfg.to_json(),
        "buy_table": (buy.to_json() if buy is not None else {}),
        "reference": table.to_json(),
        "rewrite": rep,
        "before": before, "after": after,
        "diagnostics": diag,
        "seconds": round(time.time() - t0, 1),
    }
    report_path = str(args.ref_report or "") or (
        os.path.splitext(out_path)[0] + ".ref_report.json")
    os.makedirs(os.path.dirname(os.path.abspath(report_path)) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"[ref] rewrote {len(new_rows)} rows -> {out_path} (meta={meta_path}) "
          f"in {time.time() - t0:.1f}s", flush=True)
    print(f"[ref] report -> {report_path}", flush=True)
    print(json.dumps({"policy": late_cfg.to_json(), "rewrite": rep},
                     ensure_ascii=False, indent=2), flush=True)
    _print_ref_delta("fix", before, after)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="构造场面题（自对弈关键局面 + 人类参考解）")
    ap.add_argument("--checkpoint", default="runs/az_entity_s14/model.pt",
                    help="出题用的权重（默认 s14 当前权重）")
    ap.add_argument("--device", default="cuda:7")
    ap.add_argument("--games", type=int, default=16,
                    help="rollout 局数（默认 16 ≈ 200–600 道题）")
    ap.add_argument("--seed", type=int, default=20200)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--learner-seat", type=int, default=0)
    ap.add_argument("--horizon", type=int, default=3, help="短程标签视界（默认 t+3）")
    ap.add_argument("--min-turn", type=int, default=1,
                    help="最小出题回合（默认 1：跳过 turn 0 的选英雄局面）")
    ap.add_argument("--focus-turns", default="",
                    help="只在指定 turn 段出题（默认空 = 全部）：如 '10-15' 或 "
                         "'10-15,8'；非法输入报错退出")
    ap.add_argument("--min-delta", type=float, default=0.0,
                    help="出题时就按 rollout 的 t+3 归一化强度增量过滤（默认 0 = "
                         "不过滤）：只保留 log1p(after)-log1p(before) >= 阈值的题")
    ap.add_argument("--audit-games", default="",
                    help="质量审计：记录这些**局号**（0 起，'0-5,9' 语法）的整局状态"
                         "（每回合起始 state_json + learner 动作），供 "
                         "scripts/audit_board_problems.py 重放核对 label；默认空 = 关闭")
    ap.add_argument("--audit-out", default="",
                    help="审计记录输出（默认 <out 去扩展>.audit.jsonl；仅 --audit-games 非空时写）")
    ap.add_argument("--keep-turn-start", type=int, default=1, choices=[0, 1],
                    help="1=每回合起点必出一道题（默认）")
    ap.add_argument("--max-fork-per-turn", type=int, default=2,
                    help="每回合最多保留几个分叉点（默认 2）")
    ap.add_argument("--core-min-tier", type=int, default=3,
                    help="核心随从判据的最低 tier（默认 3）")
    ap.add_argument("--obs-dtype", default="f32", choices=["f32", "f16"],
                    help="观测存储精度（f32 可逐位复现；f16 体积减半）")
    ap.add_argument("--top-k", type=int, default=8, help="参考解保留的 top-k 动作数")
    ap.add_argument("--min-support", type=int, default=40,
                    help="参考分布某层级的最小样本支撑（不足则退化到更粗层级）")
    ap.add_argument("--reference-samples", default=DEFAULT_BC_SAMPLES,
                    help="人类动作来源（默认 data/firestone_bc/bc_samples.jsonl.gz）")
    ap.add_argument("--mmr-floors", default=",".join(str(f) for f in DEFAULT_REF_FLOORS),
                    help="参考解 MMR 阶梯（默认 10000,8000,6000：优先 10k+）")
    ap.add_argument("--reference-limit", type=int, default=0,
                    help="只扫前 N 条人类样本（0=全部；调试用）")
    # 训练分布（与 s14 一致）
    ap.add_argument("--human-boards",
                    default="data/real_library/library_real_quasi_full.jsonl")
    ap.add_argument("--human-board-p", type=float, default=0.9)
    ap.add_argument("--human-board-seats", type=int, default=5)
    ap.add_argument("--human-board-fidelity", default="full",
                    choices=["board", "hand", "full"])
    ap.add_argument("--mirror-snaps", default="runs/library/snaps_champ")
    ap.add_argument("--mirror-seats", type=int, default=2)
    ap.add_argument("--mirror-p", type=float, default=0.2)
    ap.add_argument("--mirror-sample", default="p75")
    ap.add_argument("--move-guard", type=int, default=1, choices=[0, 1])
    ap.add_argument("--move-cap", type=int, default=3)
    ap.add_argument("--move-repeat-limit", type=int, default=2)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--out", default=DEFAULT_PROBLEM_PATH)
    ap.add_argument("--stats-out", default="",
                    help="统计 JSON 路径（默认 <out 去扩展>.meta.json）")
    ap.add_argument("--limit-games", type=int, default=0,
                    help="只跑前 N 局（0=全部；调试用）")
    # ── 后期参考解修正（docs/BOARD_PROBLEMS.md §14；默认 current = 逐位等价）──
    ap.add_argument("--late-ref-policy", default="current",
                    choices=["current", "fixed"],
                    help="current=原参考解（默认，逐位等价）；fixed=t>=10 只用 "
                         "turn_tier_gold 严格层 + reroll 封顶 + 买牌加权")
    ap.add_argument("--ref-reroll-cap", type=float, default=0.25,
                    help="fixed 模式下 reroll 在该状态参考分布里的质量上限（默认 0.25）")
    ap.add_argument("--ref-buy-boost", type=float, default=2.0,
                    help="fixed 模式下 buy/play 命中「该 tier 人类高频购买」表的权重倍数"
                         "（默认 2.0）")
    ap.add_argument("--ref-buy-min-freq", type=float, default=0.01,
                    help="「高频购买」判据：该卡在本 tier 的购买占比下限（默认 0.01）")
    ap.add_argument("--ref-buy-table", default=DEFAULT_FIRESTONE_ACTIONS,
                    help="人类购买频次表来源（默认 firestone_recent_actions.jsonl.gz）")
    ap.add_argument("--rewrite-pool", default="",
                    help="**不重跑 rollout**：只在已有题池上重算参考解（fixed 时严格层 + "
                         "重加权），输出到 --out；与 --checkpoint 互斥")
    ap.add_argument("--ref-report", default="",
                    help="参考解修正报告 JSON（rewrite 模式默认 <out>.ref_report.json）")
    args = ap.parse_args()

    # 后期参考解修正参数：非法值**报错退出**（不静默降级）；默认 current 不改任何东西
    try:
        late_cfg = LateRefConfig(policy=str(args.late_ref_policy),
                                 turn_min=int(LATE_TURN_MIN),
                                 reroll_cap=float(args.ref_reroll_cap),
                                 buy_boost=float(args.ref_buy_boost),
                                 buy_min_freq=float(args.ref_buy_min_freq))
    except ValueError as exc:
        print(f"[error] late-ref 参数非法：{exc}", file=sys.stderr)
        return 2
    floors = _parse_floors(args.mmr_floors)
    if str(args.rewrite_pool):
        # 只重算参考解，不建引擎、不加载 checkpoint、不跑 rollout
        return _run_rewrite(args, floors=floors, late_cfg=late_cfg)

    if not engine_available():
        print("[error] hsbg_engine 不可用（需要 build/install rust 引擎）", file=sys.stderr)
        return 2
    if int(args.games) <= 0:
        print("[error] --games 必须 > 0", file=sys.stderr)
        return 2
    if int(args.horizon) <= 0:
        print("[error] --horizon 必须 > 0", file=sys.stderr)
        return 2
    # --focus-turns / --min-delta：非法输入**报错退出**，不静默降级
    try:
        focus_ranges = parse_turn_ranges(args.focus_turns)
    except ValueError as exc:
        print(f"[error] --focus-turns 非法：{exc}", file=sys.stderr)
        return 2
    try:
        audit_games = parse_game_indices(args.audit_games)
    except ValueError as exc:
        print(f"[error] --audit-games 非法：{exc}", file=sys.stderr)
        return 2
    if audit_games and int(args.games) > 0 and max(audit_games) >= int(args.games):
        print(f"[error] --audit-games 超出局数范围（games={args.games}）", file=sys.stderr)
        return 2
    if not math.isfinite(float(args.min_delta)) or float(args.min_delta) < 0.0:
        print(f"[error] --min-delta 必须是有限且 >= 0，得到 {args.min_delta!r}",
              file=sys.stderr)
        return 2

    t0 = time.time()
    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    norm_mean, norm_std = meta.get("norm_mean"), meta.get("norm_std")
    print(f"[net] checkpoint={args.checkpoint} arch={meta.get('arch')} "
          f"norm={'on' if norm_mean is not None else 'off'}", flush=True)

    _t = time.time()
    table = build_reference_table(str(args.reference_samples), floors=floors,
                                  limit=(int(args.reference_limit) or None))
    print(f"[ref] 人类动作分布: path={table.path} floors={list(floors)} "
          f"rows={ {int(k): int(v) for k, v in table.rows.items()} } "
          f"load={time.time() - _t:.1f}s", flush=True)
    if all(int(v) == 0 for v in table.rows.values()):
        print("[error] 参考动作分布为空（bc_samples 路径/MMR 过滤有问题）",
              file=sys.stderr)
        return 2
    buy = None
    if late_cfg.enabled():
        buy = build_human_buy_table(str(args.ref_buy_table),
                                    min_freq=float(late_cfg.buy_min_freq))
        print(f"[ref] 购买频次表: rows={buy.rows} "
              f"high={ {t: len(v) for t, v in sorted(buy.high.items())} }",
              flush=True)

    cfg = ProblemCollectConfig(
        games=int(args.games), seed=int(args.seed), max_steps=int(args.max_steps),
        learner_seat=int(args.learner_seat), horizon=int(args.horizon),
        min_turn=int(args.min_turn),
        max_fork_per_turn=int(args.max_fork_per_turn),
        keep_turn_start=bool(int(args.keep_turn_start)),
        core_min_tier=int(args.core_min_tier),
        human_boards=str(args.human_boards),
        human_board_p=float(args.human_board_p),
        human_board_seats=int(args.human_board_seats),
        human_board_fidelity=str(args.human_board_fidelity),
        mirror_snaps=str(args.mirror_snaps),
        mirror_seats=int(args.mirror_seats),
        mirror_p=float(args.mirror_p),
        mirror_sample=str(args.mirror_sample),
        temperature=float(args.temperature),
        move_guard=bool(int(args.move_guard)),
        move_cap=int(args.move_cap),
        move_repeat_limit=int(args.move_repeat_limit),
        obs_dtype=str(args.obs_dtype),
        focus_turns=str(args.focus_turns or ""),
        min_delta=float(args.min_delta),
        audit_games=str(args.audit_games or ""),
        late_ref_policy=str(args.late_ref_policy),
        ref_reroll_cap=float(args.ref_reroll_cap),
        ref_buy_boost=float(args.ref_buy_boost),
        ref_buy_min_freq=float(args.ref_buy_min_freq),
        ref_buy_table=str(args.ref_buy_table))
    if int(args.limit_games) > 0:
        cfg.games = min(cfg.games, int(args.limit_games))

    result = collect_problems(
        model, cfg, device=str(args.device), reference=table,
        top_k=int(args.top_k), min_support=int(args.min_support),
        norm_mean=norm_mean, norm_std=norm_std, late_ref=late_cfg,
        late_ref_buy_table=buy, progress=True)
    if not result.problems:
        print("[error] 没有产出任何题目（rollout 太短/参考表为空？）", file=sys.stderr)
        return 2

    path, meta_path = write_problems(result, str(args.out),
                                     (str(args.stats_out) or None))
    audit_path = ""
    if result.audits:
        audit_path = str(args.audit_out or "") or (
            os.path.splitext(str(args.out))[0] + ".audit.jsonl")
        os.makedirs(os.path.dirname(os.path.abspath(audit_path)) or ".",
                    exist_ok=True)
        tmp = audit_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for row in result.audits:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, audit_path)
        print(f"[audit] wrote {len(result.audits)} games "
              f"({sum(len(a['problems']) for a in result.audits)} problems) -> "
              f"{audit_path}", flush=True)
    with open(meta_path, "r", encoding="utf-8") as fh:
        stats = json.load(fh)
    stats["checkpoint"] = str(args.checkpoint)
    stats["checkpoint_arch"] = str(meta.get("arch"))
    stats["norm_applied"] = bool(norm_mean is not None)
    stats["reference"] = table.to_json()
    stats["late_ref"] = late_cfg.to_json()
    if buy is not None:
        stats["ref_buy_table"] = buy.to_json()
    if late_cfg.enabled():
        stats["ref_type_fixed"] = ref_type_distribution(result.problems)
    if str(args.ref_report or ""):
        rep_path = str(args.ref_report)
        os.makedirs(os.path.dirname(os.path.abspath(rep_path)) or ".",
                    exist_ok=True)
        rep = {
            "schema": "board_late_ref_fix_v1",
            "generated_at": stats["generated_at"],
            "pool_out": str(path), "policy": late_cfg.to_json(),
            "buy_table": (buy.to_json() if buy is not None else {}),
            "reference": table.to_json(), "rewrite": {},
            "after": ref_type_distribution(result.problems),
            "skipped": stats["skipped"],
        }
        with open(rep_path, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2, sort_keys=True)
        print(f"[ref] report -> {rep_path}", flush=True)
    stats["total_seconds"] = round(time.time() - t0, 1)
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"[problems] wrote {len(result.problems)} problems -> {path} "
          f"(meta={meta_path}) in {time.time() - t0:.1f}s", flush=True)
    print(f"[problems] focus_turns={focus_ranges} min_delta={float(args.min_delta):g} "
          f"skipped={json.dumps(stats['skipped'], ensure_ascii=False)}",
          flush=True)
    print(json.dumps({
        "problems": stats["problems"],
        "decisions": stats["decisions"],
        "turn_min": stats["turn_min"], "turn_max": stats["turn_max"],
        "by_turn": stats["by_turn"], "by_tag": stats["by_tag"],
        "late_turn_min": int(LATE_TURN_MIN),
        "late_turn_problems": stats["late_turn_problems"],
        "late_turn_by_turn": stats["late_turn_by_turn"],
        "strength_delta_p50": round(float(stats["strength_delta_p50"]), 4),
        "strength_delta_p90": round(float(stats["strength_delta_p90"]), 4),
        "strength_delta_mean": round(float(stats["strength_delta_mean"]), 4),
        "ref_match_rate": round(float(stats["ref_match_rate"]), 4),
        "ref_missing_rate": round(float(stats["ref_missing_rate"]), 4),
        "ref_level": stats["ref_level"], "ref_floor": stats["ref_floor"],
        "ref_mass_legal_mean": round(float(stats["ref_mass_legal_mean"]), 4),
        "policy_top1_in_ref_rate": round(
            float(stats["policy_top1_in_ref_rate"]), 4),
        "label_available": stats["label_available"],
        "label_missing": stats["label_missing"],
        "tier_up_rate": round(float(stats["tier_up_rate"]), 4),
        "strength_p50": [round(float(stats["strength_before_p50"]), 1),
                         round(float(stats["strength_after_p50"]), 1)],
        "move_n_p50": stats["move_n_p50"], "move_n_max": stats["move_n_max"],
        "human_board_applied": int(
            (stats.get("human_board") or {}).get("human_board_applied", 0)),
        "human_board_attempt": int(
            (stats.get("human_board") or {}).get("human_board_attempt", 0)),
        "mirror_applied": int((stats.get("mirror") or {}).get("mirror_applied", 0)),
        "skipped": stats["skipped"],
    }, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
