#!/usr/bin/env python3
"""C0 冷启动 gate：单模型 vs 7 引擎 bot，严格 512 局 / 8 seat / 双封存面板。

正式协议（默认）：
- 512 局 = 8 seat × 64 局；模型与 bot 使用相同 seed/seat；
- 两个互不重叠的封存 seed 面板，各自必须通过；
- 主判据：配对 Δ=rank_model-rank_bot 的 95% bootstrap CI 上界 < 0；
- 0 illegal / 0 game truncation / 0 combat truncation；
- 记录 checkpoint sha256、引擎版本、逐 seat 原始 rank。

开发 smoke（--smoke）只用于管线自检，不产生可晋级结论。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import Any, Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.evaluate import EvalConfig, evaluate_policy  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.policies import make_policy  # noqa: E402
from hsbg.az.train.ppo import PPOEvaluator, PPOGreedyPolicy  # noqa: E402
from hsbg.eval.c0 import C0GateConfig, evaluate_gate  # noqa: E402


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
    payload = {"passed": False, "error": msg,
               "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    _dump(out, payload)
    print(f"[c0:error] {msg}", file=sys.stderr)
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
            _dump(out, {"passed": False, "error": f"argparse: {message}",
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


def _panel(seed_base: int, games: int, seats: int, per_seat: int, *,
           model_path: str, arch: str, device: str, bootstrap: int,
           max_steps: int, max_actions_per_turn: int,
           require_protocol: bool, tag: str) -> Dict[str, Any]:
    model, meta = load_checkpoint(model_path, device=device)
    evaluator = PPOEvaluator(model, device=device,
                             norm_mean=meta.get("norm_mean"),
                             norm_std=meta.get("norm_std"))
    net = PPOGreedyPolicy(evaluator, max_actions_per_turn=max_actions_per_turn)
    bot = make_policy("bot")
    model_ranks: List[int] = []
    bot_ranks: List[int] = []
    illegal = 0
    truncated = 0
    truncated_combats = 0
    per_seat_rows: Dict[str, Any] = {}
    t0 = time.time()
    for seat in range(seats):
        seed = int(seed_base) + seat * per_seat
        cfg = EvalConfig(games=per_seat, seed=seed, policy_seat=seat,
                         max_steps=max_steps)
        net.forced_actions = 0
        rm = evaluate_policy(net, cfg)
        rb = evaluate_policy(bot, cfg)
        rms = rm.get("rank_sequence")
        rbs = rb.get("rank_sequence")
        if rms is None or rbs is None:
            raise RuntimeError(f"{tag} seat {seat}: 缺少 rank_sequence（协议错误）")
        if len(rms) != per_seat or len(rbs) != per_seat:
            raise RuntimeError(f"{tag} seat {seat}: rank_sequence 长度错误")
        if int(rm.get("seed_start", -1)) != seed or int(rb.get("seed_start", -1)) != seed:
            raise RuntimeError(f"{tag} seat {seat}: seed_start 不一致")
        model_ranks.extend(rms)
        bot_ranks.extend(rbs)
        illegal += int(rm.get("illegal_actions", 0)) + int(rb.get("illegal_actions", 0))
        truncated += int(rm.get("truncated_games", 0)) + int(rb.get("truncated_games", 0))
        truncated_combats += int(rm.get("truncated_combats", 0)) + int(rb.get("truncated_combats", 0))
        per_seat_rows[f"seat_{seat}"] = {
            "seed_start": seed, "games": per_seat,
            "model": {k: rm.get(k) for k in
                      ("mean_rank", "top4_rate", "win_rate", "legal_action_rate",
                       "truncated_games", "truncated_combats", "rank_sequence")},
            "bot": {k: rb.get(k) for k in
                    ("mean_rank", "top4_rate", "win_rate", "legal_action_rate",
                     "truncated_games", "truncated_combats", "rank_sequence")},
            "forced_actions": int(getattr(net, "forced_actions", 0)),
        }
        print(f"[c0:{tag}] seat {seat}: net={rm.get('mean_rank')} bot={rb.get('mean_rank')}",
              flush=True)
    cfg_gate = C0GateConfig(games=int(games), seats=int(seats),
                            bootstrap=int(bootstrap), seed=int(seed_base),
                            require_protocol=require_protocol)
    res = evaluate_gate(model_ranks, bot_ranks, config=cfg_gate,
                        illegal=illegal, truncated=truncated,
                        truncated_combats=truncated_combats,
                        extra={"tag": tag, "seed_base": int(seed_base),
                               "checkpoint": model_path, "arch": meta.get("arch", arch),
                               "per_seat": per_seat_rows,
                               "seconds": round(time.time() - t0, 1)})
    return res.as_dict()


def main() -> int:
    ap = _Parser(description="C0 单模型 vs bot 严格配对 gate")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--arch", default="entity", choices=["tiny", "entity"])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--games", type=int, default=512)
    ap.add_argument("--seats", type=int, default=8)
    ap.add_argument("--seed-base", type=int, default=100000)
    ap.add_argument("--sealed-seed-base", type=int, default=-1,
                    help="第二个封存面板 seed；默认 seed-base+100000")
    ap.add_argument("--confirmations", type=int, default=2,
                    help="独立封存面板数；正式 gate 必须 >=2")
    ap.add_argument("--bootstrap", type=int, default=5000)
    ap.add_argument("--max-steps", type=int, default=50000)
    ap.add_argument("--max-actions-per-turn", type=int, default=40)
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
            return _error(args.out, "正式 gate 强制 --games 512 --seats 8；开发请加 --smoke")
        if args.confirmations < 2:
            return _error(args.out, "正式 gate 必须 --confirmations >=2")
        require_protocol = True
    if args.seats <= 0 or args.games % args.seats != 0:
        return _error(args.out, "--games 必须能被 --seats 整除且 seats>0")
    if args.bootstrap <= 0 or args.max_steps <= 0:
        return _error(args.out, "--bootstrap/--max-steps 必须 > 0")
    per_seat = args.games // args.seats
    sealed_base = (args.sealed_seed_base if args.sealed_seed_base >= 0
                   else args.seed_base + 100000)
    if args.confirmations >= 2 and sealed_base < args.seed_base + args.games:
        return _error(args.out, "封存 seed 面板必须与主面板不重叠")

    panels: List[Dict[str, Any]] = []
    try:
        for k in range(args.confirmations):
            base = args.seed_base + k * 100000 if k == 0 else sealed_base + (k - 1) * 100000
            panels.append(_panel(base, args.games, args.seats, per_seat,
                                 model_path=args.checkpoint, arch=args.arch,
                                 device=args.device, bootstrap=args.bootstrap,
                                 max_steps=args.max_steps,
                                 max_actions_per_turn=args.max_actions_per_turn,
                                 require_protocol=require_protocol,
                                 tag=f"panel{k}"))
    except Exception as exc:  # noqa: BLE001
        import traceback
        return _error(args.out, f"evaluation failed: {exc!r}\n{traceback.format_exc()}",
                      code=2)
    smoke_result = bool(panels) and all(bool(p.get("passed")) for p in panels)
    # smoke 只用于管线自检，绝不产生可晋级 passed
    passed = bool(not args.smoke and smoke_result)
    payload = {
        "protocol": "smoke" if args.smoke else "c0_gate_v1",
        "passed": passed,
        "smoke_result": smoke_result,
        "checkpoint": args.checkpoint,
        "checkpoint_sha256": _sha256(args.checkpoint),
        "engine": _engine_info(),
        "config": vars(args),
        "panels": panels,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    _dump(args.out, payload)
    print(json.dumps({"protocol": payload["protocol"], "passed": passed,
                      "smoke_result": smoke_result,
                      "panel0": {k: panels[0].get(k) for k in
                                 ("passed", "mean_diff", "ci_low", "ci_high",
                                  "model_mean_rank", "bot_mean_rank", "model_top4",
                                  "illegal", "truncated", "truncated_combats", "reasons")}
                      if panels else None},
                     ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
