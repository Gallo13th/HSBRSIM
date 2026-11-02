"""护甲系统实测 + 升本费用饰品出现/选择率（不改训练代码）。

A. 护甲：默认规则起 2 局，跑完英雄选择 → t1 打印 4 个座位的 `armor/hp`；
   再把 8 席全部 EndTurn 进第一场战斗 → t2 再打印，看伤害是否先扣护甲。
B. 饰品：CompoundPolicy 教师 12 局（sandbox, trinkets=True），逐次 trinket pending
   记录**选项 id 列表**与最终选择，统计
   `BG30_MagicItem_705`（Bartend-o-Tron's Oilcan，升本费用 −3）与所有升本类饰品的
   出现率 / 选择率，以及 top 选择。

用法：python scripts/armor_trinket_probe.py --games 12
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

#: 「降低升本费用」类饰品（引擎实现见 trinkets_p3.rs::reduce_upgrade）
UPGRADE_TRINKETS = {"BG30_MagicItem_705": "Bartend-o-Tron's Oilcan: 升本费用 -3/回合"}


def _armor_probe(seeds=(11, 12)) -> list:
    import hsbg_engine as E
    out = []
    for seed in seeds:
        g = E.Game(int(seed), E.default_config_json())
        # 英雄选择：每个座位选第一个合法英雄
        for _ in range(64):
            if int(g.turn) > 0 or g.is_over():
                break
            acted = False
            for p in range(int(g.num_players)):
                if not g.needs_action(p):
                    continue
                m = np.frombuffer(bytes(g.legal_mask(p)), dtype=np.uint8).astype(bool)
                legal = np.flatnonzero(m)
                if legal.size:
                    g.step(p, int(legal[0]))
                    acted = True
            if not acted:
                break
        rec = {"seed": seed, "t1": {}, "t2_after_combat": {}}
        for p in range(4):
            pj = json.loads(g.player_json(p))
            rec["t1"][p] = {"armor": int(pj.get("armor") or 0),
                            "hp": int(pj.get("health") or 0),
                            "hero": pj.get("hero")}
        # 全部 EndTurn，让引擎打完第一场战斗
        for _ in range(8 * 4):
            acted = False
            for p in range(int(g.num_players)):
                if not g.needs_action(p):
                    continue
                m = np.frombuffer(bytes(g.legal_mask(p)), dtype=np.uint8).astype(bool)
                if m.any() and bool(m[0]):
                    g.step(p, 0)
                    acted = True
            if int(g.turn) > 1 or g.is_over():
                break
            if not acted:
                break
        for p in range(4):
            pj = json.loads(g.player_json(p))
            rec["t2_after_combat"][p] = {"armor": int(pj.get("armor") or 0),
                                        "hp": int(pj.get("health") or 0)}
        out.append(rec)
    return out


def _trinket_probe(games: int) -> dict:
    from hsbg.az.train.economy_sandbox import EconomySandbox, SandboxConfig
    from compound_script import CompoundPolicy

    cfg = SandboxConfig(turns=15, gold_mode="fixed", gold_per_turn=30, action_cap=40,
                        num_players=8, trinkets=True, gold_cap=99, lobby_types=())
    offers = 0
    picks = collections.Counter()
    offer_ids = collections.Counter()
    up_offers = 0
    up_picks = 0
    games_with_up_offer = 0
    per_offer_detail = []
    for gi in range(games):
        env = EconomySandbox(cfg)
        obs = env.reset(880000 + gi)
        pol = CompoundPolicy(seed=880000 + gi)
        offered_this_game = set()
        while not env.done:
            v = json.loads(env.g.view(0))
            me = v.get("me") or {}
            pend = me.get("pending")
            is_trinket = isinstance(pend, dict) and str(pend.get("kind")) == "trinket"
            opt_ids = []
            if is_trinket:
                opt_ids = [str(o.get("id") or "") for o in (pend.get("options") or [])]
            a = int(pol.act(v, obs.mask))
            obs, _r, done, _info = env.step(a)
            if is_trinket and opt_ids:
                offers += 1
                for cid in opt_ids:
                    offer_ids[cid] += 1
                offered_this_game.update(opt_ids)
                up = [cid for cid in opt_ids if cid in UPGRADE_TRINKETS]
                if up:
                    up_offers += 1
                if 30 <= a <= 46:
                    j = a - 30
                    sel = opt_ids[j] if j < len(opt_ids) else ""
                    picks[sel] += 1
                    if sel in UPGRADE_TRINKETS:
                        up_picks += 1
                    per_offer_detail.append({"game": gi, "turn": int(v.get("turn") or 0),
                                             "options": opt_ids, "picked": sel,
                                             "up_offer": bool(up)})
        if any(cid in UPGRADE_TRINKETS for cid in offered_this_game):
            games_with_up_offer += 1
    return {
        "games": games, "offers": offers, "picks": sum(picks.values()),
        "upgrade_offers": up_offers,
        "upgrade_offer_rate": round(up_offers / max(1, offers), 3),
        "upgrade_picks": up_picks,
        "upgrade_pick_rate_when_offered": round(up_picks / max(1, up_offers), 3),
        "games_with_upgrade_offer": games_with_up_offer,
        "top_offered": offer_ids.most_common(10),
        "top_picked": picks.most_common(10),
        "details": per_offer_detail,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="armor + upgrade-cost trinket probe")
    ap.add_argument("--games", type=int, default=12)
    ap.add_argument("--json-out", default=os.path.join(ROOT, "runs", "sandbox_econ",
                                                       "armor_trinket.json"))
    args = ap.parse_args(argv)
    out = {"armor": _armor_probe(), "trinkets": _trinket_probe(int(args.games))}
    os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("=== ARMOR ===")
    for rec in out["armor"]:
        print(f"seed={rec['seed']} t1:", {p: (v["armor"], v["hp"]) for p, v in rec["t1"].items()})
        print(f"           t2:", {p: (v["armor"], v["hp"]) for p, v in rec["t2_after_combat"].items()})
    t = out["trinkets"]
    print("=== TRINKETS ===")
    print(json.dumps({k: v for k, v in t.items() if k not in ("details", "top_offered", "top_picked")},
                     ensure_ascii=False))
    print("top_offered:", t["top_offered"])
    print("top_picked:", t["top_picked"])
    print(f"WROTE {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
