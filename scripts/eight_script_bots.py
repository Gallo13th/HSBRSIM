#!/usr/bin/env python3
"""8 席全脚本对弈：看终局冠军的阵容强度与阵容构成。

用法：
  PYTHONPATH=rust/python:. python scripts/eight_script_bots.py --games 60 --mode script \
      --json-out runs/eight_script_bots/script60.json

模式：
  script = 8 席全部由固定阵容脚本（hybrid：阵容动作优先、其余引擎 bot）驱动；
  bot    = 8 席全部引擎 bot（对照基线）；
  mixed  = 4 席脚本（1..4）+ 4 席 bot（0,5,6,7）。

记录：每局冠军（rank=1）的终局盘面 Σ(atk+hp)、盘面大小、tier、种族、
核心命中、分配到的阵容；以及冠军/亚军强度分布与各阵容的冠军次数/平均名次。
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import random
import statistics as st
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))

import hsbg_engine as E  # noqa: E402

from hsbg.az.train.common import mask_from_bytes  # noqa: E402

TRIBES = ["BEAST", "DEMON", "DRAGON", "ELEMENTAL", "MECHANICAL", "MURLOC",
          "NAGA", "PIRATE", "QUILBOAR", "UNDEAD", "ABERRATION"]


def _load_cs():
    path = os.path.join(ROOT, "scripts", "comp_scripts.py")
    spec = importlib.util.spec_from_file_location("comp_scripts_eight", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["comp_scripts_eight"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


CS = _load_cs()
CATALOG = getattr(CS, "CATALOG", {})

# 引擎 cid(int) -> 卡牌字符串 id；player_json 的 board 用数字 ``card`` 字段。
_CID2ID = {int(c["cid"]): str(c["id"]) for c in json.loads(E.catalog_json())}
# data/p2 卡表（name/races/tier），以字符串 id 为键。
_cards = json.load(open(os.path.join(ROOT, "data/p2/cards_37.json"), encoding="utf-8"))
if isinstance(_cards, dict):
    _cards = _cards.get("cards") or _cards.get("data") or []
CARDS = {str(c["id"]): c for c in _cards if isinstance(c, dict) and c.get("id")}
for _id, _c in CATALOG.items():
    CARDS.setdefault(str(_id), _c)



def lobby_config(seed: int, n_types: int = 5):
    rng = random.Random(int(seed) * 7919 + 13)
    types = list(TRIBES)
    rng.shuffle(types)
    types = types[:n_types]
    return json.dumps({"lobby_types": types}), types


def _card_id(m) -> str:
    """player_json board item：``card`` 是数字 cid；返回字符串卡牌 id。"""
    try:
        return _CID2ID.get(int(m.get("card")), "")
    except Exception:
        return ""


def _minion_ids(board):
    return [_card_id(m) for m in (board or [])]


def _strength(board) -> int:
    return sum(int(m.get("atk") or 0) + int(m.get("hp") or 0) for m in (board or []))


def _tier_of_card(cid: str) -> int:
    base = cid[:-2] if cid.endswith("_G") else cid
    c = CARDS.get(base) or CARDS.get(cid) or {}
    try:
        return int(c.get("tier") or 0)
    except Exception:
        return 0


def _races(board):
    out = set()
    for cid in _minion_ids(board):
        base = cid[:-2] if cid.endswith("_G") else cid
        c = CARDS.get(base) or CARDS.get(cid) or {}
        for r in c.get("races") or []:
            out.add(str(r))
    return sorted(out)


def _names(board):
    out = []
    for m in board or []:
        cid = _card_id(m)
        base = cid[:-2] if cid.endswith("_G") else cid
        c = CARDS.get(base) or CARDS.get(cid) or {}
        name = str(c.get("name") or cid or m.get("card") or "?")
        out.append(f"{name} {int(m.get('atk') or 0)}/{int(m.get('hp') or 0)}")
    return out



def _core_hit(spec, board) -> float:
    if spec is None:
        return 0.0
    ids = set()
    for cid in _minion_ids(board):
        ids.add(cid[:-2] if cid.endswith("_G") else cid)
    core = set(spec.core or ())
    return (len(core & ids) / len(core)) if core else 0.0


def play_game(seed: int, mode: str, no_exit: bool = False) -> dict:
    cfg, lobby_types = lobby_config(seed)
    game = E.Game(int(seed), cfg)
    try:
        import hsbg_engine as _E
        if hasattr(_E, "finish_hero_select"):
            _E.finish_hero_select(game)
    except Exception:
        pass

    n = int(getattr(game, "num_players", 8))
    keys = CS.comp_keys()
    # 只给「本局大厅包含其主族」的阵容上桌；否则脚本拿不到核心会退出成 bot。
    eligible = [k for k in keys if str(CS.COMPS[k].tribe) in lobby_types]
    if len(eligible) < 2:
        eligible = list(keys)
    specs = []
    if mode == "script":
        for s in range(n):
            specs.append(CS.COMPS[eligible[(int(seed) * 8 + s) % len(eligible)]])
    elif mode == "mixed":
        for s in range(n):
            specs.append(CS.COMPS[eligible[(int(seed) * 8 + s) % len(eligible)]]
                         if s in (1, 2, 3, 4) else None)
    else:
        specs = [None] * n

    pols = []
    for s in range(n):
        if specs[s] is not None:
            pols.append(CS.CompPolicy(specs[s], auto=False, seed=int(seed) * 17 + s,
                                      exit_on_miss=not bool(no_exit)))
        else:
            pols.append(None)

    steps = 0
    max_steps = 20000
    while not game.is_over() and steps < max_steps:
        acted = False
        for p in range(n):
            if game.is_over():
                break
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            if pols[p] is None:
                game.bot_play(p)
                continue
            mask = mask_from_bytes(game.legal_mask(p))
            v = CS.view_of(game, p)
            pols[p].observe(v, mask)
            ca = pols[p].comp_action(v, mask)
            if ca is not None and 0 <= int(ca) < 245 and bool(mask[int(ca)]):
                a = int(ca)
            else:
                a = int(game.bot_action(p))
                if not (0 <= a < 245 and bool(mask[a])):
                    nz = np.flatnonzero(mask)
                    a = int(nz[0]) if nz.size else 0
            game.step(p, a)
        if not acted and not game.is_over():
            break
    if not game.is_over():
        return {"seed": int(seed), "ok": False, "reason": "not_finished", "steps": steps}

    placements = [int(x) for x in game.placements()]  # placements[seat] = rank
    records = []
    for s in range(n):
        pj = json.loads(game.player_json(s))
        board = pj.get("board") or []
        rec = {
            "seat": s,
            "rank": int(placements[s]),
            "comp": (specs[s].key if specs[s] is not None else "bot"),
            "comp_name": (specs[s].name if specs[s] is not None else "engine_bot"),
            "strength": _strength(board),
            "board_size": len(board),
            "tier_max": max((_tier_of_card(c) for c in _minion_ids(board)), default=0),
            "races": _races(board),
            "core_hit": round(float(_core_hit(specs[s], board)), 4),
            "board": [{"id": _card_id(m), "atk": int(m.get("atk") or 0),
                       "hp": int(m.get("hp") or 0),
                       "tier": int(m.get("tier") or 0),
                       "golden": bool(m.get("golden") or False)}
                      for m in board],
            "board_names": _names(board),
            "player_tier": int(pj.get("tier") or 0),
            "health": int(pj.get("health") or 0),
        }
        records.append(rec)
    champ = [r for r in records if r["rank"] == 1][0]
    runner = [r for r in records if r["rank"] == 2]
    runner = runner[0] if runner else None
    return {"seed": int(seed), "ok": True, "steps": steps, "lobby_types": lobby_types,
            "champion": champ,
            "runner_up": ({"comp": runner["comp"], "strength": runner["strength"]}
                          if runner else None),
            "seats": records}


def pct(vals, q):
    if not vals:
        return None
    v = sorted(vals)
    k = max(0, min(len(v) - 1, int(round((q / 100.0) * (len(v) - 1)))))
    return v[k]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=60)
    ap.add_argument("--seed", type=int, default=910000)
    ap.add_argument("--mode", default="script", choices=["script", "bot", "mixed"])
    ap.add_argument("--json-out", default="")
    ap.add_argument("--no-exit", action="store_true",
                    help="固定阵容不因抓不到核心而退出（老口径；默认允许回退 bot）")
    args = ap.parse_args(argv)

    games = []
    for g in range(int(args.games)):
        games.append(play_game(int(args.seed) + g, str(args.mode),
                               no_exit=bool(args.no_exit)))

    ok = [g for g in games if g.get("ok")]
    champs = [g["champion"] for g in ok]
    strengths = [c["strength"] for c in champs]
    runners = [g["runner_up"]["strength"] for g in ok if g.get("runner_up")]

    print(f"[eight_script_bots] mode={args.mode} games={len(games)} ok={len(ok)}")
    print(f"champion strength: p10={pct(strengths,10)} p50={pct(strengths,50)} "
          f"p90={pct(strengths,90)} max={max(strengths) if strengths else None} "
          f"mean={st.mean(strengths):.1f}" if strengths else "no champions")
    if runners:
        print(f"runner-up strength: p50={pct(runners,50)} mean={st.mean(runners):.1f}")
    print(f"champion board size p50={pct([c['board_size'] for c in champs],50)} "
          f"tier p50={pct([c['tier_max'] for c in champs],50)} "
          f"core_hit mean={st.mean([c['core_hit'] for c in champs]):.3f} "
          f"core_hit>0={sum(1 for c in champs if c['core_hit'] > 0)}/{len(champs)}")
    comp_counts = {}
    for c in champs:
        comp_counts[c["comp"]] = comp_counts.get(c["comp"], 0) + 1
    print("champion comp counts:", dict(sorted(comp_counts.items(),
                                               key=lambda kv: -kv[1])[:10]))
    print("\ntop-8 champion boards:")
    for c in sorted(champs, key=lambda x: -x["strength"])[:8]:
        print(f"  seed? comp={c['comp']:>20s} strength={c['strength']:5d} "
              f"tier={c['tier_max']} races={','.join(c['races'])[:40]} "
              f"core_hit={c['core_hit']:.2f} board={c['board_names']}")

    out = {
        "mode": args.mode, "games": len(games), "ok": len(ok),
        "seed": int(args.seed),
        "champion_strength": {"p10": pct(strengths, 10), "p50": pct(strengths, 50),
                              "p90": pct(strengths, 90), "max": max(strengths) if strengths else None,
                              "mean": st.mean(strengths) if strengths else None},
        "runner_up_strength": {"p50": pct(runners, 50), "mean": st.mean(runners) if runners else None},
        "champion_comp_counts": comp_counts,
        "champions": [{"comp": c["comp"], "strength": c["strength"],
                       "board_size": c["board_size"], "tier_max": c["tier_max"],
                       "races": c["races"], "core_hit": c["core_hit"],
                       "board_names": c["board_names"]} for c in champs],
        "games": games,
    }
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
        json.dump(out, open(args.json_out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n[json] -> {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
