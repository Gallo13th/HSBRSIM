#!/usr/bin/env python3
"""人类战团对手面板：单模型 vs 7 个「真实 10k+ 分位战团」座位，严格 512 局 / 8 seat。

**与 ``c0_gate.py`` 同口径**（``docs/EVAL_PANELS.md``）：

- 512 局 = 8 seat × 64 局；模型与 bot 基线使用相同 seed/seat；
- 两个互不重叠的封存 seed 面板（正式）/ 单面板（``--smoke``）；
- 主统计：配对 Δ=rank_model-rank_bot 的 95% bootstrap CI；
- 0 illegal / 0 game truncation / 0 combat truncation；记录 checkpoint sha256。

**与 bot 面板的唯一区别**：对手座位（除 learner 外的全部座位）在**每回合开始、任何座位
行动前**被注入该 turn 分位的人类战团（``data/real_library/library_real_degraded.jsonl``，
``source=human_board_approx``，board-only）。这是**近似对手强度**，不是忠实对手状态：
人类数据没有 hand / shop / 金币 / 共享池差量 / 英雄技能计数，注入只替换 board（+ 按 turn
派生的 tier），对手本回合照常行动。人类数据里没有 pending choice，所以「饰品选择回合」
（t=6/9 等）注入会被引擎以 ``pending_choice`` 拒绝 —— 计数如实写入 ``injection``。

用法::

    # 正式 512 局面板（auto 难度曲线）
    python scripts/human_panel_eval.py --checkpoint runs/champion_c0_1746.pt \
        --games 512 --device cuda:7 --out runs/eval/human_panel.json

    # 开发 smoke（64 局，单面板）
    python scripts/human_panel_eval.py --checkpoint runs/champion_c0_1746.pt \
        --games 64 --smoke --device cuda:7 --quantile p90 --out /tmp/human_p90.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.evaluate import EvalConfig, evaluate_policy  # noqa: E402
from hsbg.az.train.human_board_pool import (  # noqa: E402
    SAMPLE_MODES,
    HumanBoardPool,
    load_pool,
)
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.policies import make_policy  # noqa: E402
from hsbg.az.train.ppo import PPOEvaluator, PPOGreedyPolicy  # noqa: E402
from hsbg.eval.c0 import C0GateConfig, evaluate_gate  # noqa: E402

#: 注入计数里需要跨座位求和的键。
_INJ_SUM = ("human_board_attempt", "human_board_applied", "human_board_rejected",
            "human_board_missing", "human_board_errors", "human_board_pool_unbalanced",
            "human_board_nearest_bucket", "human_board_tier_set",
            "human_board_skipped_by_mirror")

#: 每 seat 的指标键（写进 ``details.per_seat``；null 表示该字段不适用）。
_METRIC_KEYS = ("mean_rank", "top4_rate", "win_rate", "legal_action_rate",
                "truncated_games", "truncated_combats", "rank_sequence",
                "decisions", "decisions_per_game", "human_board_turns",
                "seconds", "human_board")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _dump(path: str, payload: Dict[str, Any]) -> None:
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)


def _error(out: str, msg: str, code: int = 2) -> int:
    payload = {"passed": False, "error": msg, "panel": "human_board",
               "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    _dump(out, payload)
    print(f"[human:error] {msg}", file=sys.stderr)
    return code


def _find_out(argv: List[str]) -> str:
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--out="):
            return a.split("=", 1)[1]
    return ""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # argparse 类型/必填错误也要落 JSON
        out = _find_out(sys.argv)
        if out:
            _dump(out, {"passed": False, "panel": "human_board",
                        "error": f"argparse: {message}",
                        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        super().error(message)


def _engine_info() -> Dict[str, Any]:
    try:
        import hsbg_engine as E
        return {"version": E.version(), "game_version": E.game_version(),
                "server_rules_version": E.server_rules_version(),
                "build_info": E.build_info(), "data_info": E.data_info()}
    except Exception as exc:  # noqa: BLE001
        return {"error": repr(exc)}


def _metrics(res: Dict[str, Any]) -> Dict[str, Any]:
    """从 ``evaluate_policy`` 结果里抽出面板要保留的字段（含注入计数）。"""
    return {k: res.get(k) for k in _METRIC_KEYS}


def _merge_injection(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """聚合多座位/多策略的注入计数（``rows`` 是若干 ``human_board`` meta）。"""
    out: Dict[str, Any] = {"human_board_source": "human_board_approx"}
    reasons: Dict[str, int] = {}
    for m in rows:
        if not isinstance(m, dict):
            continue
        for k in _INJ_SUM:
            if k in m:
                out[k] = int(out.get(k, 0)) + int(m[k])
        for k, v in (m.get("human_board_rejected_by_reason") or {}).items():
            reasons[str(k)] = reasons.get(str(k), 0) + int(v)
    if reasons:
        out["human_board_rejected_by_reason"] = dict(sorted(reasons.items()))
    return out


def _panel(seed_base: int, games: int, seats: int, per_seat: int, *,
           model_path: str, arch: str, device: str, bootstrap: int,
           max_steps: int, max_actions_per_turn: int,
           pool: Optional[HumanBoardPool], quantile: str,
           baseline_bot: bool, require_protocol: bool,
           tag: str) -> Dict[str, Any]:
    """跑一个 seed 面板：learner（seat 逐座位轮换）+ 可选 bot 基线，同人类战团注入。"""
    model, meta = load_checkpoint(model_path, device=device)
    evaluator = PPOEvaluator(model, device=device,
                             norm_mean=meta.get("norm_mean"),
                             norm_std=meta.get("norm_std"))
    net = PPOGreedyPolicy(evaluator, max_actions_per_turn=max_actions_per_turn)
    bot = make_policy("bot") if baseline_bot else None
    model_ranks: List[int] = []
    bot_ranks: List[int] = []
    illegal = 0
    truncated = 0
    truncated_combats = 0
    injections: List[Dict[str, Any]] = []
    model_decisions = 0
    model_seconds = 0.0
    per_seat_rows: Dict[str, Any] = {}
    t0 = time.time()
    for seat in range(seats):
        seed = int(seed_base) + seat * per_seat
        cfg = EvalConfig(games=per_seat, seed=seed, policy_seat=seat,
                         max_steps=max_steps, human_board_pool=pool)
        net.forced_actions = 0
        rm = evaluate_policy(net, cfg)
        rms = rm.get("rank_sequence")
        if rms is None or len(rms) != per_seat:
            raise RuntimeError(f"{tag} seat {seat}: rank_sequence 缺失/长度错误")
        if int(rm.get("seed_start", -1)) != seed:
            raise RuntimeError(f"{tag} seat {seat}: seed_start 不一致")
        if pool is not None and int(rm.get("human_board_applied", 0)) <= 0 and \
                int(rm.get("human_board", {}).get("human_board_attempt", 0)) <= 0:
            raise RuntimeError(f"{tag} seat {seat}: 人类战团注入完全没触发")
        model_ranks.extend(int(r) for r in rms)
        model_decisions += int(rm.get("decisions", 0))
        model_seconds += float(rm.get("seconds", 0.0))
        illegal += int(rm.get("illegal_actions", 0))
        truncated += int(rm.get("truncated_games", 0))
        truncated_combats += int(rm.get("truncated_combats", 0))
        injections.append(rm.get("human_board") or {})
        row: Dict[str, Any] = {"seed_start": seed, "games": per_seat,
                               "model": _metrics(rm)}
        if bot is not None:
            rb = evaluate_policy(bot, cfg)
            rbs = rb.get("rank_sequence")
            if rbs is None or len(rbs) != per_seat:
                raise RuntimeError(f"{tag} seat {seat}: bot rank_sequence 缺失/长度错误")
            bot_ranks.extend(int(r) for r in rbs)
            illegal += int(rb.get("illegal_actions", 0))
            truncated += int(rb.get("truncated_games", 0))
            truncated_combats += int(rb.get("truncated_combats", 0))
            injections.append(rb.get("human_board") or {})
            row["bot"] = _metrics(rb)
        row["forced_actions"] = int(getattr(net, "forced_actions", 0))
        per_seat_rows[f"seat_{seat}"] = row
        print(f"[human:{tag}] seat {seat}: net={rm.get('mean_rank')} "
              f"bot={(row.get('bot') or {}).get('mean_rank')} "
              f"inj={int((rm.get('human_board') or {}).get('human_board_applied', 0))}/"
              f"{int((rm.get('human_board') or {}).get('human_board_attempt', 0))}",
              flush=True)
    injection = _merge_injection(injections)
    extra = {"tag": tag, "seed_base": int(seed_base),
             "checkpoint": model_path, "arch": meta.get("arch", arch),
             "per_seat": per_seat_rows, "injection": injection,
             "baseline_bot": bool(baseline_bot),
             "seconds": round(time.time() - t0, 1)}
    if baseline_bot:
        cfg_gate = C0GateConfig(games=int(games), seats=int(seats),
                                bootstrap=int(bootstrap), seed=int(seed_base),
                                require_protocol=require_protocol)
        grid = evaluate_gate(model_ranks, bot_ranks, config=cfg_gate,
                             illegal=illegal, truncated=truncated,
                             truncated_combats=truncated_combats, extra=extra)
        panel = grid.as_dict()
        panel["reasons"] = [r for r in panel.get("reasons", [])
                            if "击败 bot" not in r]
    else:
        # 没有 bot 基线：保留与 c0_gate 完全相同的面板键，bot_* / CI 置 null；
        # passed 只表示「协议干净」（0 illegal / 0 truncation）。
        known = [int(r) for r in model_ranks if int(r) >= 1]
        n = len(known)
        reasons: List[str] = []
        if int(illegal) != 0:
            reasons.append(f"illegal={illegal} != 0")
        if int(truncated) != 0:
            reasons.append(f"truncated={truncated} != 0")
        if int(truncated_combats) != 0:
            reasons.append(f"truncated_combats={truncated_combats} != 0")
        if int(per_seat * seats) != int(games):
            reasons.append(f"有效局数 {len(model_ranks)} != games={games}")
        panel = {
            "passed": not reasons,
            "n": int(n),
            "mean_diff": None, "ci_low": None, "ci_high": None,
            "model_mean_rank": (sum(known) / n) if n else None,
            "bot_mean_rank": None,
            "model_top4": (sum(1 for r in known if r <= 4) / n) if n else None,
            "bot_top4": None,
            "model_win": (sum(1 for r in known if r == 1) / n) if n else None,
            "illegal": int(illegal), "truncated": int(truncated),
            "truncated_combats": int(truncated_combats),
            "reasons": reasons, "details": {"pair_missing": 0, **extra},
        }
    panel.update({
        "panel": "human_board",
        # learner 侧聚合：每局决策数（含早退/截断局，按 games 平均）与总决策数。
        "model_decisions": int(model_decisions),
        "model_decisions_per_game": float(model_decisions / max(int(games), 1)),
        "model_seconds": round(float(model_seconds), 1),
        "quantile": str(quantile),
        "opponent": "human_board_approx",
        "human_board_pool_stats": (pool.stats() if pool is not None else None),
        "injection": injection,
    })
    return panel


def main() -> int:
    ap = _Parser(description="人类战团对手面板（board-only，10k+ 分位）")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--arch", default="entity", choices=["tiny", "entity", "entity18m"])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--games", type=int, default=512)
    ap.add_argument("--seats", type=int, default=8)
    ap.add_argument("--seed-base", type=int, default=100000)
    ap.add_argument("--sealed-seed-base", type=int, default=-1,
                    help="第二个封存面板 seed；默认 seed-base+100000")
    ap.add_argument("--confirmations", type=int, default=2,
                    help="独立封存面板数；正式面板必须 >=2")
    ap.add_argument("--bootstrap", type=int, default=5000)
    ap.add_argument("--max-steps", type=int, default=50000)
    ap.add_argument("--max-actions-per-turn", type=int, default=40)
    ap.add_argument("--quantile", default="auto", choices=list(SAMPLE_MODES),
                    help="人类战团桶内分位：auto=t<=8 p50 / 9-12 p75 / >=13 p90")
    ap.add_argument("--human-boards", default="",
                    help="人类战团 JSONL（默认 data/real_library/"
                         "library_real_degraded.jsonl）")
    ap.add_argument("--baseline-bot", type=int, default=1,
                    help="1=同 seed/seat 再跑 bot 基线（配对 Δ/CI；默认 1）")
    ap.add_argument("--set-tier", type=int, default=1,
                    help="1=注入时同时写入按 turn 派生的 tier（人类数据无 tier）")
    ap.add_argument("--smoke", action="store_true",
                    help="开发自检：小样本、单面板，不产生晋级结论")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if args.out and os.path.isfile(args.out):
        os.unlink(args.out)

    if args.smoke:
        args.confirmations = 1
        require_protocol = False
    else:
        if args.games != 512 or args.seats != 8:
            return _error(args.out, "正式面板强制 --games 512 --seats 8；开发请加 --smoke")
        if args.confirmations < 2:
            return _error(args.out, "正式面板必须 --confirmations >=2")
        require_protocol = True
    if args.seats <= 0 or args.games % args.seats != 0:
        return _error(args.out, "--games 必须能被 --seats 整除且 seats>0")
    if args.bootstrap <= 0 or args.max_steps <= 0:
        return _error(args.out, "--bootstrap/--max-steps 必须 > 0")
    if args.quantile not in SAMPLE_MODES:
        return _error(args.out, f"未知 --quantile {args.quantile}")
    if args.seats > 8:
        return _error(args.out, "--seats 最多 8")
    human_boards = str(args.human_boards or
                       os.path.join(ROOT, "data", "real_library",
                                    "library_real_degraded.jsonl"))
    if not os.path.isfile(human_boards):
        return _error(args.out, f"人类战团数据不存在: {human_boards}")
    pool = load_pool(human_boards, sample=str(args.quantile))
    if pool is None:
        return _error(args.out, f"人类战团池为空/全被过滤: {human_boards}")
    print(f"[human] pool={human_boards} kept={pool.kept} "
          f"quantile={args.quantile} "
          f"baseline_bot={bool(int(args.baseline_bot))}", flush=True)

    per_seat = args.games // args.seats
    sealed_base = (args.sealed_seed_base if args.sealed_seed_base >= 0
                   else args.seed_base + 100000)
    if args.confirmations >= 2 and sealed_base < args.seed_base + args.games:
        return _error(args.out, "封存 seed 面板必须与主面板不重叠")

    panels: List[Dict[str, Any]] = []
    try:
        for k in range(args.confirmations):
            base = args.seed_base + k * 100000 if k == 0 else sealed_base + (k - 1) * 100000
            panels.append(_panel(
                base, args.games, args.seats, per_seat,
                model_path=args.checkpoint, arch=args.arch, device=args.device,
                bootstrap=args.bootstrap, max_steps=args.max_steps,
                max_actions_per_turn=args.max_actions_per_turn,
                pool=pool, quantile=str(args.quantile),
                baseline_bot=bool(int(args.baseline_bot)),
                require_protocol=require_protocol, tag=f"panel{k}"))
    except Exception as exc:  # noqa: BLE001
        import traceback
        return _error(args.out, f"evaluation failed: {exc!r}\n{traceback.format_exc()}",
                      code=2)
    smoke_result = bool(panels) and all(bool(p.get("passed")) for p in panels)
    passed = bool(not args.smoke and smoke_result)
    payload = {
        "protocol": "human_panel_smoke" if args.smoke else "human_panel_v1",
        "panel": "human_board",
        "quantile": str(args.quantile),
        "passed": passed,
        "smoke_result": smoke_result,
        "checkpoint": args.checkpoint,
        "checkpoint_sha256": _sha256(args.checkpoint),
        "engine": _engine_info(),
        "config": vars(args),
        "panels": panels,
        "human_board_pool_stats": pool.stats(),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    _dump(args.out, payload)
    print(json.dumps({
        "protocol": payload["protocol"], "panel": "human_board",
        "quantile": str(args.quantile), "passed": passed,
        "smoke_result": smoke_result,
        "panel0": ({k: panels[0].get(k) for k in
                    ("passed", "model_mean_rank", "bot_mean_rank", "model_top4",
                     "model_win", "mean_diff", "ci_low", "ci_high",
                     "illegal", "truncated", "injection")}
                   if panels else None),
    }, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
