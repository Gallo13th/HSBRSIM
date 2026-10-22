"""从 turn-search 数据重建“我方战团”，采样同 turn/tier 对照池，打 pairwise 胜率标签。

对每个有非空 board 的样本：
- 用 obs.board token 重建我方 board；
- 从同 (turn,tier) 的其他样本采样 K 个对照 board（不足则同 turn）；
- 每对用引擎 `run_combat` 打一场（公共 seed），标签 = 平均胜率（draw=0.5）。

输出 npz：indices（原 dataset 下标）、winrate、turn、tier、episode_id、n_combats。
只读数据/引擎；不训练。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np

from hsbg import planning
from hsbg.env.game_env import BattlegroundsEnv
from hsbg.planning import hidden
from hsbg.train.bc import BCDataset


def _specs(obs) -> List[Dict[str, Any]]:
    out = []
    for m in obs.board:
        try:
            out.append({"card_id": str(m.card_id), "golden": bool(m.golden),
                        "atk": int(m.atk), "health": int(m.health),
                        "keywords": tuple(getattr(m, "keywords", ()) or ())})
        except Exception:  # noqa: BLE001
            continue
    return out


def _combat_win(template_game, specs_a, specs_b, seed: int) -> Optional[float]:
    """返回 1/0/0.5；无法模拟返回 None。"""
    try:
        g = planning.clone(template_game)
        a, b = g.heroes[0], g.heroes[1]
        hidden.inject_hidden_state(g, a, board=specs_a, clear=True)
        hidden.inject_hidden_state(g, b, board=specs_b, clear=True)
        if not a.board or not b.board:
            return None
        try:
            g.rng = planning.rng_fork(g.rng, seed=int(seed))
        except Exception:  # noqa: BLE001
            pass
        res = g.run_combat(a, b, alive_count=8)
        if res.winner is a:
            return 1.0
        if res.winner is b:
            return 0.0
        return 0.5
    except Exception:  # noqa: BLE001
        return None


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="build pairwise winrate labels")
    p.add_argument("--data", default="runs/value_data/turn_search_20k.pkl")
    p.add_argument("--out", default="runs/value_data/turn_search_winrate_labels.npz")
    p.add_argument("--meta", default="runs/value_data/turn_search_winrate_labels.json")
    p.add_argument("--k", type=int, default=8)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--limit", type=int, default=0, help="0=all；>0 smoke")
    p.add_argument("--min-board", type=int, default=1)
    p.add_argument("--workers", type=int, default=0,
                   help="保留；当前单进程（引擎对象不可跨进程）")
    args = p.parse_args(argv)

    t0 = time.perf_counter()
    ds = BCDataset.load(args.data)
    idx_all = list(range(len(ds.samples)))
    if args.limit:
        idx_all = idx_all[:args.limit]
    template_env = BattlegroundsEnv(seed=int(args.seed) + 1, opponent="heuristic")
    template_env.reset(seed=int(args.seed) + 1)
    template_game = planning.clone(template_env.game)

    specs: Dict[int, List[Dict[str, Any]]] = {}
    meta_state: Dict[int, Dict[str, Any]] = {}
    pool: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for i in idx_all:
        obs, _ = ds.samples[i]
        try:
            sp = _specs(obs)
            turn = int(getattr(obs, "turn", 0))
            tier = int(getattr(obs.hero, "tier", 0))
            eps = int(ds.episode_ids[i])
        except Exception:  # noqa: BLE001
            continue
        if len(sp) < int(args.min_board):
            continue
        specs[i] = sp
        meta_state[i] = {"turn": turn, "tier": tier, "episode": eps}
        pool[(turn, tier)].append(i)
        pool[(turn, -1)].append(i)  # 同 turn 回退
    candidates = sorted(specs)
    print(f"states_with_board={len(candidates)} / limit={len(idx_all)} "
          f"pool_keys={len(pool)}", flush=True)

    rng = random.Random(int(args.seed))
    out_idx, out_wr, out_turn, out_tier, out_eps, out_n = [], [], [], [], [], []
    failures = 0
    t1 = time.perf_counter()
    for n, i in enumerate(candidates):
        m = meta_state[i]
        key = (m["turn"], m["tier"])
        cand_pool = pool.get(key) or pool.get((m["turn"], -1)) or []
        choices = [j for j in cand_pool if j != i]
        if not choices:
            failures += 1
            continue
        k = min(int(args.k), len(choices))
        picked = rng.sample(choices, k)
        wins = []
        for j in picked:
            w = _combat_win(template_game, specs[i], specs[j],
                            seed=int(args.seed) * 1_000_003 + i * 97 + j * 13)
            if w is not None:
                wins.append(w)
        if not wins:
            failures += 1
            continue
        out_idx.append(i)
        out_wr.append(float(np.mean(wins)))
        out_turn.append(m["turn"])
        out_tier.append(m["tier"])
        out_eps.append(m["episode"])
        out_n.append(len(wins))
        if (n + 1) % 500 == 0:
            print(f"  {n+1}/{len(candidates)} states, "
                  f"{(time.perf_counter()-t1):.1f}s", flush=True)
    template_env.close()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path, indices=np.asarray(out_idx, dtype=np.int64),
        winrate=np.asarray(out_wr, dtype=np.float32),
        turn=np.asarray(out_turn, dtype=np.int16),
        tier=np.asarray(out_tier, dtype=np.int16),
        episode_id=np.asarray(out_eps, dtype=np.int64),
        n_combats=np.asarray(out_n, dtype=np.int16))
    meta = {
        "data": args.data, "out": str(out_path), "k": args.k, "seed": args.seed,
        "limit": args.limit, "n_samples_dataset": len(ds.samples),
        "n_labeled": len(out_idx), "n_failed": failures,
        "board_coverage": len(out_idx) / max(1, len(idx_all)),
        "wall_s": round(time.perf_counter() - t0, 1),
        "label_hist": {"mean": float(np.mean(out_wr)) if out_wr else None,
                       "std": float(np.std(out_wr)) if out_wr else None},
        "note": "同 turn/tier 对照池 pairwise 胜率；draw=0.5；只读不训练",
    }
    Path(args.meta).write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
