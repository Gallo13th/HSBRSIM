#!/usr/bin/env python3
"""量测 B13 ceiling 头第 3 维（"终局是否持有放大器"）的预测质量（AUC）。

做法：用当前策略跑 N 局，逐决策记录 (features, cards) 与该局终局 has_amp 标签，
再一次性前向 ceiling 头算 sigmoid(pred[:,2])，输出 AUC / 平均预测 / 正样本率。
"""
from __future__ import annotations
import argparse, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "rust", "python")); sys.path.insert(0, ROOT)
for _k, _v in (("HSBRSIM_FORCE_UPGRADE", "1"), ("HSBRSIM_FORCE_UPGRADE_MAX_TIER", "5"),
               ("HSBRSIM_BAN_TRINKETS", "BG36_MagicItem_414"),
               ("HSBRSIM_COMP_BUY_BIAS", "1"), ("HSBRSIM_COMP_BUY_INCLUDE", "MULT,GROW,ENGINE"),
               ("HSBRSIM_COMP_BUY_PROTECT", "MULT"), ("HSBRSIM_COMP_BUY_PARTNER", "1")):
    os.environ.setdefault(_k, _v)
import numpy as np
import torch
import hsbg_engine as E
from hsbg.az.train.game_rules import game_config_json
from hsbg.az.train.model import load_checkpoint
from hsbg.az.train.ppo import CollectConfig, PPOEvaluator, PPOSelfPlayPolicy

AMPS = {"布莱恩·铜须", "达卡莱附魔师", "提图斯·瑞文戴尔"}

def auc(y, s):
    y = np.asarray(y); s = np.asarray(s)
    pos = s[y == 1]; neg = s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    # 秩和法（处理并列）
    order = np.argsort(np.concatenate([pos, neg]))
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(order) + 1)
    rp = ranks[:len(pos)].sum()
    return float((rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ckpt"); ap.add_argument("--games", type=int, default=6)
    ap.add_argument("--device", default="cuda:1"); ap.add_argument("--seed", type=int, default=881000)
    a = ap.parse_args(argv)
    cat = {int(c["cid"]): c for c in json.loads(E.catalog_json())}
    model, meta = load_checkpoint(a.ckpt, device=a.device)
    ev = PPOEvaluator(model, device=a.device, norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    cfg = CollectConfig(games=1, seed=a.seed, opponent="bot", behavior="net", max_steps=20000,
                        move_guard=True, move_cap=3, move_repeat_limit=2,
                        forced_upgrade=True, forced_upgrade_max_tier=5,
                        comp_buy_bias=1.0, comp_buy_include="MULT,GROW,ENGINE",
                        comp_buy_max_copies=2, comp_buy_protect="MULT", comp_buy_partner=1)
    pol = PPOSelfPlayPolicy(model, device=a.device, config=cfg, eval_fn=ev, seed=a.seed, move_model=False)
    feats, cards_l, ys = [], [], []
    pos_games = 0
    for gi in range(a.games):
        g = E.Game(a.seed + gi, game_config_json()); pol.reset()
        rows = []
        while not g.is_over():
            acted = False
            for p in range(8):
                if g.is_over(): break
                if not g.needs_action(p): continue
                acted = True
                if p != 0:
                    g.bot_play(p); continue
                f, c, _m = pol._observe(g, 0)
                rows.append((np.asarray(f, dtype=np.float32).copy(), np.asarray(c).copy()))
                g.step(0, int(pol.decide(g, 0).action))
            if not acted: break
        pj = json.loads(g.player_json(0))
        has = int(any((cat.get(int(m.get("card") or -1)) or {}).get("name_zh") in AMPS
                      for m in (pj.get("board") or [])))
        pos_games += has
        for f, c in rows:
            feats.append(f); cards_l.append(c); ys.append(has)
    X = torch.from_numpy(np.stack(feats)).to(a.device)
    C = torch.from_numpy(np.stack(cards_l).astype(np.int64)).to(a.device)
    probs = []
    with torch.no_grad():
        for i in range(0, len(X), 512):
            out = model.forward_ceiling(X[i:i+512], C[i:i+512], None)
            pred = out[1]
            probs.append(torch.sigmoid(pred[:, 2]).cpu().numpy())
    s = np.concatenate(probs)
    print(json.dumps({"ckpt": os.path.basename(a.ckpt), "games": a.games,
                      "decisions": int(len(ys)), "pos_games": int(pos_games),
                      "pos_rate": round(float(np.mean(ys)), 3),
                      "auc": round(auc(ys, s), 3),
                      "mean_pred_pos": round(float(s[np.asarray(ys) == 1].mean()), 3) if pos_games else None,
                      "mean_pred_neg": round(float(s[np.asarray(ys) == 0].mean()), 3)}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
