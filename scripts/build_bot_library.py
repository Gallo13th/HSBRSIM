#!/usr/bin/env python3
"""用引擎 bot 对局构建牌面镜像库（library seats 的第一步：没有真人数据时的引导库）。

用法：
  P=/home/data/users/gaoletian/.conda/envs/hiermolgen/bin/python
  PYTHONPATH=rust/python:. $P scripts/build_bot_library.py \
      --games 200 --out runs/library/bot_lib.jsonl.gz

产物：
- `<out>`：所有座位所有回合的 entry（含 placement）；
- `<out 前缀>_champions.jsonl.gz`：只保留冠军（placement=1）座位的牌面；
- `<out 前缀>_meta.json`：规模/回合分布/强度分位数。

说明：全程只用**引擎脚本 bot**（不需要 GPU / 神经网络），因此可以在训练占满 GPU 时构建。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))

from hsbg.az.library import BoardLibrary, capture_turn  # noqa: E402


def play_and_capture(engine, seed: int) -> tuple[List, Dict[int, int]]:
    """跑一局 bot 对局；在每个回合「招募结束」时抓一次全座位牌面。"""
    game = engine.Game(seed=int(seed))
    entries = []
    ended: set = set()
    cur_turn = None
    guard = 0
    while not game.is_over() and guard < 200000:
        guard += 1
        acted = False
        for p in range(int(game.num_players)):
            if not game.needs_action(p):
                continue
            acted = True
            action = int(game.bot_action(p))
            if action == 0:  # EndTurn：该座位本回合牌面已定
                ended.add(p)
            game.step(p, action)
            if game.is_over():
                break
        # 所有存活座位都结束回合 -> 抓一次（每回合一次 state_json）
        alive = {p for p in range(int(game.num_players)) if _alive(game, p)}
        if alive and ended >= alive:
            st = json.loads(game.state_json())
            if cur_turn != int(st.get("turn", 0)):
                cur_turn = int(st.get("turn", 0))
                entries.extend(capture_turn(engine, game, state=st))
            ended = set()
        if not acted:
            break
    placements = {i: int(r) for i, r in enumerate(game.placements())}
    return entries, placements


def _alive(game, p: int) -> bool:
    """``Game.health()`` 返回全部座位的血量列表（无参数）。"""
    try:
        return int(list(game.health())[int(p)]) > 0
    except Exception:  # noqa: BLE001 - 取不到时退回「存活」
        return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="runs/library/bot_lib.jsonl.gz")
    args = ap.parse_args()
    args.out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    import hsbg_engine as engine

    t0 = time.time()
    lib = BoardLibrary()
    n_entries = 0
    for g in range(int(args.games)):
        try:
            entries, placements = play_and_capture(engine, int(args.seed) + g)
        except Exception as exc:  # noqa: BLE001 - 单局失败不放弃整批
            print(f"[warn] seed {args.seed + g} failed: {exc!r}", flush=True)
            continue
        for e in entries:
            e.placement = int(placements.get(e.seat, 0))
        lib.add(entries)
        n_entries += len(entries)
        if (g + 1) % 10 == 0:
            print(f"[capture] games={g + 1} entries={n_entries} "
                  f"({time.time() - t0:.0f}s)", flush=True)

    lib.save(args.out)
    champ_path = args.out.replace(".jsonl.gz", "_champions.jsonl.gz")
    champions = lib.filter_champions((1,))
    champions.save(champ_path)
    meta = {
        "source": "engine scripted bots (no human data)",
        "games": int(args.games), "seed0": int(args.seed),
        "all": lib.stats(), "champions": champions.stats(),
        "seconds": round(time.time() - t0, 1),
        "out": args.out, "out_champions": champ_path,
        "limitations": ["只还原牌面（不含手牌内容/酒馆/任务/饰品/技能计数）",
                        "强度 = sum(atk+hp)，未做分回合强度曲线",
                        "champions = placement 1"],
    }
    meta_path = args.out.replace(".jsonl.gz", "_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("[done] " + json.dumps({k: meta[k] for k in ("games", "seconds")},
                                 ensure_ascii=False), flush=True)
    print("[stats] all=" + json.dumps(meta["all"], ensure_ascii=False), flush=True)
    print("[stats] champions=" + json.dumps(meta["champions"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
