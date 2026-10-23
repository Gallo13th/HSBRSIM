"""15-turn recruit-only search benchmark (single hero; no 8-player game).

搜索变量：
- width  : 每层保留的动作数（beam width）
- depth  : 动作 ply 深度（search depth）
- horizon: 跨回合预期（leaf 后继续用 heuristic 走 N 个整回合，再用 value 网评分）

终局强度：
- warband value network score
- 引擎 pairwise 战斗（所有 config×seed 的终局阵容互打）平均胜率
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import torch

from hsbg.agents.heuristic import HeuristicPolicy
from hsbg.env import driver
from hsbg.planning.live_warband import build_warband, simulate_combat_warbands
from hsbg.search.forward import EngineForwardModel
from hsbg.value.warband_model import WarbandEncoder
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero

DEFAULT_HERO = "TB_BaconShop_HERO_14"
VALUE_CK = "runs/warband_value/model_60k/checkpoint.pt"
META_JSON = "runs/warband_value/pairs_20k.json"


def _tier(m: Any) -> int:
    for attr in ("tier", "tech_level"):
        v = getattr(m, attr, None)
        if v is not None:
            try:
                return int(v)
            except Exception:
                pass
    return 1


def _keywords(m: Any) -> List[str]:
    return sorted(str(k) for k in (getattr(m, "keywords", ()) or ()))


class WarbandScorer:
    def __init__(self, checkpoint: str = VALUE_CK, meta_path: str = META_JSON,
                 device: str = "cpu") -> None:
        self.device = torch.device(device)
        self.meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
        ck = torch.load(checkpoint, map_location=self.device)
        a = ck["args"]
        self.model = WarbandEncoder(
            len(self.meta["card_ids"]), len(self.meta["keywords"]),
            dim=int(a["dim"]), layers=int(a["layers"])).to(self.device)
        self.model.load_state_dict(ck["model"])
        self.model.eval()
        self.cards = {c: i for i, c in enumerate(self.meta["card_ids"])}
        self.kw = {k: i for i, k in enumerate(self.meta["keywords"])}

    @torch.no_grad()
    def score_board(self, board: Sequence[Any], max_len: int = 7) -> float:
        n = min(max_len, len(board))
        cards = torch.zeros(1, max_len, dtype=torch.long, device=self.device)
        atk = torch.zeros(1, max_len, dtype=torch.float32, device=self.device)
        hp = torch.zeros_like(atk)
        tier = torch.zeros(1, max_len, dtype=torch.long, device=self.device)
        kws = torch.zeros(1, max_len, len(self.kw), dtype=torch.float32,
                          device=self.device)
        for i, m in enumerate(board[:n]):
            cards[0, i] = self.cards.get(str(getattr(m, "card_id", "")), 0)
            atk[0, i] = float(getattr(m, "atk", 0) or 0)
            hp[0, i] = float(getattr(m, "health", 1) or 1)
            tier[0, i] = max(0, min(7, _tier(m)))
            for k in _keywords(m):
                j = self.kw.get(k)
                if j is not None:
                    kws[0, i, j] = 1.0
        length = torch.tensor([n], dtype=torch.long, device=self.device)
        s, _ = self.model(cards, atk, hp, tier, kws, length)
        return float(s.item())

    def score_model(self, model: EngineForwardModel) -> float:
        return self.score_board(model.hero.board)


def _specs(board: Sequence[Any]) -> List[Dict[str, Any]]:
    return [{"card": str(getattr(m, "card_id", "")),
             "atk": int(getattr(m, "atk", 0) or 0),
             "hp": int(getattr(m, "health", 1) or 1),
             "keywords": _keywords(m), "tier": _tier(m),
             "golden": bool(getattr(m, "golden", False))} for m in board]


def _resolve_choices(game: Game, hero: Hero, max_choice: int = 8) -> None:
    for _ in range(max_choice):
        if not getattr(game, "pending_choices", None):
            return
        descs = driver.enumerate_actions(game, hero)
        choose = [d for d in descs if str(d.kind) == "choose"]
        if not choose:
            return
        driver.apply_action(game, hero, choose[0])


def _heuristic_action(model: EngineForwardModel, policy: HeuristicPolicy):
    try:
        d = policy.choose(model.game, model.hero)
        if d is None:
            return None
        sig = d.to_candidate().signature()
        for c in model.candidates():
            if c.signature() == sig:
                return c
    except Exception:
        pass
    return None


def _rollout_future(model: EngineForwardModel, *, horizon: int,
                    scorer: WarbandScorer, seed: int = 0) -> float:
    """leaf 后继续用 heuristic 走 horizon 个完整回合，再 value 评分。"""
    if horizon <= 0:
        return scorer.score_model(model)
    m = model.clone()
    pol = HeuristicPolicy()
    for _ in range(int(horizon)):
        _resolve_choices(m.game, m.hero)
        # 当前回合启发式动作（不 end_turn）——限制步数，只作为“跨回合预期”的廉价代理
        for _ in range(2):
            a = _heuristic_action(m, pol)
            if a is None or str(a.kind) == "end_turn":
                break
            if not m.apply(a):
                break
            _resolve_choices(m.game, m.hero)
        # 手动推进一个招募回合（不跑战斗）
        m.game.turn += 1
        m.game._begin_recruit_for(m.hero)
        _resolve_choices(m.game, m.hero)
    return scorer.score_model(m)


def _search(model: EngineForwardModel, *, depth: int, width: int,
            horizon: int, scorer: WarbandScorer) -> float:
    if depth <= 0 or model.is_terminal():
        return _rollout_future(model, horizon=horizon, scorer=scorer)
    cands = [c for c in model.candidates()
             if str(c.kind) != "end_turn"]
    if not cands:
        return _rollout_future(model, horizon=horizon, scorer=scorer)
    # 先按立即 value 排序，保留 top-W
    scored: List[Tuple[float, Any]] = []
    for c in cands:
        try:
            dup = model.clone()
            ok = dup.apply(c)
            scored.append((scorer.score_model(dup) if ok else -1e9, c))
        except Exception:
            scored.append((-1e9, c))
    scored.sort(key=lambda x: -x[0])
    best = -1e9
    for _, c in scored[:max(1, int(width))]:
        try:
            dup = model.clone()
            if not dup.apply(c):
                continue
            v = _search(dup, depth=depth - 1, width=width,
                        horizon=horizon, scorer=scorer)
            best = max(best, v)
        except Exception:
            continue
    return best


def _best_action(model: EngineForwardModel, *, depth: int, width: int,
                 horizon: int, scorer: WarbandScorer):
    cands = [c for c in model.candidates()
             if str(c.kind) != "end_turn"]
    if not cands:
        return None
    # beam 化：先按立即 value 截到 top-W，再只对 top-W 做递归（避免全展开）
    ranked: List[Tuple[float, Any]] = []
    for c in cands:
        try:
            dup = model.clone()
            ok = dup.apply(c)
            ranked.append((scorer.score_model(dup) if ok else -1e9, c))
        except Exception:
            ranked.append((-1e9, c))
    ranked.sort(key=lambda x: -x[0])
    best_v = -1e9
    best_c = None
    for _, c in ranked[:max(1, int(width))]:
        try:
            dup = model.clone()
            if not dup.apply(c):
                continue
            v = _search(dup, depth=depth - 1, width=width,
                        horizon=horizon, scorer=scorer)
            if v > best_v:
                best_v, best_c = v, c
        except Exception:
            continue
    return best_c, best_v


def _run_one(*, seed: int, turns: int, width: int, depth: int,
             horizon: int, value_ck: str) -> Dict[str, Any]:
    db = CardDB.load("data")
    game = Game([Hero(DEFAULT_HERO, "agent")], db, seed=int(seed))
    game.start_game()
    hero = game.heroes[0]
    scorer = WarbandScorer(value_ck, device="cpu")
    t0 = time.perf_counter()
    decisions = 0
    for turn in range(1, int(turns) + 1):
        if int(game.turn) != turn:
            game.turn = turn
            game._begin_recruit_for(hero)
        _resolve_choices(game, hero)
        for _ in range(80):
            model = EngineForwardModel.from_game(game, hero, total_players=1,
                                                 clone=False)
            item = _best_action(model, depth=max(1, int(depth)),
                                width=max(1, int(width)),
                                horizon=max(0, int(horizon)), scorer=scorer)
            if item is None:
                break
            cand, _ = item
            if not model.apply(cand):
                break
            decisions += 1
            _resolve_choices(game, hero)
            if str(getattr(cand, "kind", "")) == "end_turn":
                break
        if turn < int(turns):
            game.turn = turn + 1
            game._begin_recruit_for(hero)
            _resolve_choices(game, hero)
    board = list(hero.board or ())
    return {"seed": int(seed), "turns": int(turns), "width": int(width),
            "depth": int(depth), "horizon": int(horizon),
            "final_board": _specs(board),
            "board_value": scorer.score_board(board),
            "board_stats": sum(int(m.atk or 0) + int(m.health or 0) for m in board),
            "tier": int(getattr(hero, "tavern_tier", 0) or 0),
            "gold": int(getattr(hero, "gold", 0) or 0),
            "decisions": decisions,
            "elapsed_s": round(time.perf_counter() - t0, 2)}


def _board_key(board: List[Dict[str, Any]]) -> str:
    return json.dumps(board, ensure_ascii=False, sort_keys=True)


def _pairwise(rows: List[Dict[str, Any]], db: CardDB, samples: int = 9) -> None:
    # 按唯一终局阵容做 pairwise，避免相同阵容的重复行互相“刷胜率”
    keys = [_board_key(r["final_board"]) for r in rows]
    uniq: List[str] = []
    first: Dict[str, int] = {}
    for k in keys:
        if k not in first:
            first[k] = len(uniq)
            uniq.append(k)
    n = len(uniq)
    wins = [0.0] * n
    games = [0] * n
    for i in range(n):
        for j in range(i + 1, n):
            wi_sum = 0.0
            ok = False
            for k in range(max(1, int(samples))):
                try:
                    a = build_warband({"board": rows[keys.index(uniq[i])]["final_board"]},
                                      "board", db=db)
                    b = build_warband({"board": rows[keys.index(uniq[j])]["final_board"]},
                                      "board", db=db)
                    r = simulate_combat_warbands(a, b, seed=i * 131 + j * 17 + k,
                                                 alive_count=2, damage_cap=15)
                    wi_sum += 1.0 if r.winner_side == "a" else 0.0
                    ok = True
                except Exception:
                    pass
            if not ok:
                continue
            wi = wi_sum / max(1, samples)
            wins[i] += wi
            wins[j] += 1.0 - wi
            games[i] += 1
            games[j] += 1
    uniq_wr = [wins[i] / max(1, games[i]) for i in range(n)]
    for row, k in zip(rows, keys):
        row["pair_winrate_unique"] = uniq_wr[first[k]]
        row["pair_winrate"] = uniq_wr[first[k]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--widths", default="1,3")
    ap.add_argument("--depths", default="1,2")
    ap.add_argument("--horizons", default="0,1")
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--turns", type=int, default=15)
    ap.add_argument("--out", default="runs/search_15turn_bench")
    args = ap.parse_args()
    widths = [int(x) for x in args.widths.split(",") if x.strip()]
    depths = [int(x) for x in args.depths.split(",") if x.strip()]
    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    rows: List[Dict[str, Any]] = []
    t0 = time.perf_counter()
    for width in widths:
        for depth in depths:
            for horizon in horizons:
                for seed in seeds:
                    row = _run_one(seed=seed, turns=args.turns, width=width,
                                   depth=depth, horizon=horizon,
                                   value_ck=VALUE_CK)
                    rows.append(row)
                    print(json.dumps({k: row[k] for k in
                                      ("width", "depth", "horizon", "seed",
                                       "board_value", "board_stats", "tier",
                                       "elapsed_s")}, ensure_ascii=False),
                          flush=True)
    db = CardDB.load("data")
    _pairwise(rows, db)
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(f"w{r['width']}_d{r['depth']}_h{r['horizon']}", []).append(r)
    summary = []
    for key, rs in sorted(groups.items()):
        summary.append({"config": key, "n": len(rs),
                        "mean_value": statistics.fmean(r["board_value"] for r in rs),
                        "mean_pair_winrate": statistics.fmean(r["pair_winrate"] for r in rs),
                        "mean_stats": statistics.fmean(r["board_stats"] for r in rs),
                        "mean_tier": statistics.fmean(r["tier"] for r in rs),
                        "mean_s": statistics.fmean(r["elapsed_s"] for r in rs)})
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    data = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "turns": args.turns, "rows": rows, "summary": summary,
            "total_elapsed_s": round(time.perf_counter() - t0, 2)}
    (out / "results.json").write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    md = ["# 15-turn recruit-only search benchmark", "",
          f"- turns={args.turns}; rows={len(rows)}; total={data['total_elapsed_s']}s",
          "- 单英雄 recruit-only；无 8 人对局/战斗；终局用 value 网 + pairwise 评估",
          "", "| config | n | value | pairwise winrate | stats | tier | s/run |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for s in summary:
        md.append(f"| {s['config']} | {s['n']} | {s['mean_value']:.3f} | "
                  f"{s['mean_pair_winrate']:.3f} | {s['mean_stats']:.1f} | "
                  f"{s['mean_tier']:.1f} | {s['mean_s']:.1f} |")
    (out / "README.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
