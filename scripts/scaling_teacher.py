#!/usr/bin/env python3
"""离线缩放教师标注（DAgger 式）：在 learner rollout 的状态上查询教师。

教师定义在 :mod:`hsbg.az.train.scaling_teacher`（确定性、必合法）。本脚本用
learner checkpoint 跑 `1 learner vs 7 引擎 bot`，在每个 learner 决策处记录：

- 紧凑状态（turn / gold / tier / board / hand / shop / pending）；
- `teacher_action`（动作下标）与 `action_name`；
- `legal`（教师动作是否在合法掩码内；正常应恒为 True）；
- `window`（gold>=10 且 tier>=4，即在线 DAgger 的标注窗口）。

输出 `data/scaling_teacher/labels.jsonl`（逐行 JSON）与同名 `.meta.json` 摘要。
**不训练、不改权重、不写 checkpoint**；默认单进程，可 `--workers` 并行（按 seed 分片）。

用法::

    PYTHONPATH=rust/python:. python scripts/scaling_teacher.py \
        --checkpoint runs/az_entity_s15/model.pt --games 24 \
        --device cuda:7 --out data/scaling_teacher/labels.jsonl
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import mask_from_bytes  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import PPOEvaluator, PPOGreedyPolicy  # noqa: E402
from hsbg.az.train.scaling_teacher import (  # noqa: E402
    ScalingTeacher, in_scaling_window)

#: 动作类型名（与引擎 action_name 对齐的粗略分类；写标签用）
_ACT_NAMES = {
    0: "end_turn", 1: "refresh", 2: "freeze", 3: "upgrade", 4: "hero_power0",
    5: "hero_power1", 6: "dark_gift", 7: "cancel",
}


def action_name(a: int) -> str:
    a = int(a)
    if a in _ACT_NAMES:
        return _ACT_NAMES[a]
    if 8 <= a <= 15:
        return "buy"
    if 16 <= a <= 22:
        return "sell"
    if 23 <= a <= 29:
        return "activate"
    if 30 <= a <= 45:
        return "choose"
    if 46 <= a <= 125:
        return "play"
    if 126 <= a <= 195:
        return "magnetize"
    if 196 <= a <= 244:
        return "move"
    return "unknown"


def _compact_board(board):
    out = []
    for m in board or []:
        if not isinstance(m, dict):
            continue
        out.append({"id": m.get("id"), "name": m.get("name"),
                    "atk": int(m.get("atk") or 0), "hp": int(m.get("hp") or 0),
                    "tier": int(m.get("tier") or 0),
                    "golden": bool(m.get("golden", False))})
    return out


def _compact_shop(shop):
    out = []
    for m in shop or []:
        if not isinstance(m, dict):
            continue
        out.append({"id": m.get("id"), "type": m.get("type"),
                    "atk": int(m.get("atk") or 0), "hp": int(m.get("hp") or 0),
                    "price": int(m.get("price") or m.get("cost") or 3),
                    "tier": int(m.get("tier") or 0),
                    "text": (m.get("text") or "")[:120]})
    return out


def _compact_hand(hand):
    out = []
    for m in hand or []:
        if not isinstance(m, dict):
            continue
        out.append({"id": m.get("id"), "type": m.get("type"),
                    "atk": int(m.get("atk") or 0), "hp": int(m.get("hp") or 0)})
    return out


def _rollout(job) -> dict:
    """跑一局 learner rollout，返回标签行与统计。"""
    seed, ckpt, device, max_steps = job
    import hsbg_engine as E

    model, meta = load_checkpoint(ckpt, device=device)
    ev = PPOEvaluator(model, device=device, norm_mean=meta.get("norm_mean"),
                      norm_std=meta.get("norm_std"))
    policy = PPOGreedyPolicy(ev, max_actions_per_turn=40)
    teacher = ScalingTeacher()
    game = E.Game(seed=int(seed))
    rows = []
    steps = 0
    legal_bad = 0
    while not game.is_over() and steps < int(max_steps):
        acted = False
        for p in range(8):
            if not game.needs_action(p):
                continue
            if int(p) == 0:
                view = json.loads(game.view(0))
                me = view.get("me") or {}
                mask = mask_from_bytes(game.legal_mask(0))
                ta = teacher.act_view(view, mask=mask)
                legal = bool(0 <= ta < len(mask) and mask[ta])
                if not legal:
                    legal_bad += 1
                rows.append({
                    "game_id": int(seed), "seed": int(seed),
                    "turn": int(game.turn), "phase": view.get("phase"),
                    "gold": int(me.get("gold") or 0),
                    "tier": int(me.get("tier") or 0),
                    "health": int(me.get("health") or 0),
                    "window": bool(in_scaling_window(me.get("gold"), me.get("tier"))),
                    "board": _compact_board(me.get("board")),
                    "hand": _compact_hand(me.get("hand")),
                    "shop": _compact_shop(me.get("shop")),
                    "pending": (me.get("pending") or {}).get("kind"),
                    "teacher_action": int(ta),
                    "action_name": action_name(ta),
                    "legal": bool(legal),
                })
                d = policy.decide(game, 0)
                a = int(d.action)
                if not (0 <= a < len(mask) and mask[a]):
                    a = int(mask.nonzero()[0][0]) if mask.any() else 0
                game.step(0, a)
            else:
                game.bot_play(int(p))
            steps += 1
            acted = True
            if game.is_over():
                break
        if not acted:
            break
    placement = int(list(game.placements())[0]) if game.is_over() else 0
    return {"seed": int(seed), "rows": rows, "steps": int(steps),
            "legal_bad": int(legal_bad), "placement": placement,
            "truncated": int(not game.is_over())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--games", type=int, default=24)
    ap.add_argument("--seed-base", type=int, default=710000)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--out", default="data/scaling_teacher/labels.jsonl")
    args = ap.parse_args()
    t0 = time.time()
    jobs = [(args.seed_base + i, args.checkpoint, args.device, args.max_steps)
            for i in range(int(args.games))]
    results = []
    if int(args.workers) <= 1:
        for j in jobs:
            results.append(_rollout(j))
    else:
        with mp.Pool(int(args.workers)) as pool:
            for r in pool.imap_unordered(_rollout, jobs, chunksize=1):
                results.append(r)
    rows = []
    legal_bad = 0
    truncated = 0
    for r in results:
        rows.extend(r["rows"])
        legal_bad += int(r["legal_bad"])
        truncated += int(r["truncated"])
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, args.out)
    by_type = Counter(r["action_name"] for r in rows)
    win = [r for r in rows if r["window"]]
    meta = {
        "checkpoint": args.checkpoint,
        "games": int(args.games),
        "seed_base": int(args.seed_base),
        "labels": int(len(rows)),
        "window_labels": int(len(win)),
        "window_rate": round(float(len(win)) / max(1, len(rows)), 4),
        "legal_rate": round(1.0 - float(legal_bad) / max(1, len(rows)), 6),
        "illegal": int(legal_bad),
        "truncated_games": int(truncated),
        "action_types": dict(by_type),
        "window_action_types": dict(Counter(r["action_name"] for r in win)),
        "elapsed_s": round(time.time() - t0, 2),
        "out": args.out,
    }
    with open(args.out + ".meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    if legal_bad > 0:
        print(f"[error] 教师动作非法 {legal_bad} 条（应恒为 0）", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
