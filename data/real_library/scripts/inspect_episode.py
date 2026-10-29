#!/usr/bin/env python
"""查看采集器产出的 JSONL 轨迹（调试环境/RL 接口用）。

用法::

    python scripts/inspect_episode.py runs/rl/heuristic_100.jsonl            # 汇总
    python scripts/inspect_episode.py runs/rl/heuristic_100.jsonl --episode 3 --trace
    python scripts/inspect_episode.py runs/rl/heuristic_100.jsonl --episode 3 --trace --max-steps 60
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List


def load(path: Path) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {"header": [], "step": [], "episode": [],
                                  "error": []}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.setdefault(rec.get("type", "other"), []).append(rec)
    return out


def summarize(data: Dict[str, List[dict]], path: Path) -> None:
    header = data["header"][0] if data["header"] else {}
    eps = data["episode"]
    steps = data["step"]
    print(f"file: {path}")
    print(f"header: {json.dumps(header, ensure_ascii=False)}")
    print(f"episodes={len(eps)} steps={len(steps)} errors={len(data['error'])}")
    if eps:
        ranks = Counter(e.get("rank") for e in eps)
        print(f"rank_dist: {dict(sorted(ranks.items()))}")
        reasons = Counter(e.get("reason") for e in eps)
        print(f"reasons: {dict(reasons)}")
        print(f"turns mean={sum(e.get('turns', 0) for e in eps) / len(eps):.1f} "
              f"steps mean={sum(e.get('steps', 0) for e in eps) / len(eps):.1f}")
    if steps:
        kinds = Counter(s.get("action_kind") for s in steps)
        print(f"action_kinds: {dict(kinds)}")
        invalids = sum(1 for s in steps if s.get("invalid"))
        print(f"invalid_steps={invalids}")


def trace_episode(data: Dict[str, List[dict]], episode_id: int,
                  max_steps: int = 0) -> None:
    steps = [s for s in data["step"] if s.get("episode_id") == episode_id]
    ep = next((e for e in data["episode"]
               if e.get("episode_id") == episode_id), None)
    print(f"\n=== episode {episode_id} ({len(steps)} steps) ===")
    if ep:
        print(f"seed={ep.get('seed')} rank={ep.get('rank')} "
              f"turn={ep.get('turns')} steps={ep.get('steps')} "
              f"reward={ep.get('total_reward')} reason={ep.get('reason')}")
    shown = 0
    for s in steps:
        if max_steps and shown >= max_steps:
            print(f"... ({len(steps) - shown} more steps)")
            break
        shown += 1
        obs = s.get("obs", {})
        def _fmt(items):
            out = []
            for c in items or []:
                if isinstance(c, dict):
                    out.append(f"{c.get('card_id','?')}"
                               f"({c.get('atk')}/{c.get('health')})")
                else:
                    out.append(str(c))
            return " ".join(out)

        board = _fmt(obs.get("board"))
        hand = _fmt(obs.get("hand"))
        tavern = _fmt(obs.get("tavern"))
        print(f"t={s.get('turn'):>2} {s.get('phase'):<7} "
              f"gold={obs.get('gold')} tier={obs.get('tier')} "
              f"hp={obs.get('health')} rank={s.get('rank')} "
              f"n_cand={s.get('n_candidates')}")
        print(f"   action={s.get('action_kind'):<12} {s.get('action_signature')}")
        if board:
            print(f"   board: {board}")
        if hand:
            print(f"   hand : {hand}")
        if tavern:
            print(f"   tav  : {tavern}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--episode", type=int, default=None)
    ap.add_argument("--trace", action="store_true")
    ap.add_argument("--max-steps", type=int, default=0)
    args = ap.parse_args(argv)
    path = Path(args.path)
    if not path.exists():
        print(f"not found: {path}")
        return 2
    data = load(path)
    summarize(data, path)
    if args.episode is not None:
        trace_episode(data, args.episode, args.max_steps)
    elif args.trace and data["episode"]:
        trace_episode(data, data["episode"][0].get("episode_id", 0),
                      args.max_steps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
