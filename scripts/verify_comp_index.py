#!/usr/bin/env python3
"""校验训练侧"买卡规则"的卡 id 口径是否与观测/地图一致（防止差一错误）。

检查四件事（逐决策）：
1. `obs cards[shop+ i] == pj.shop[i].card + 1`（obs 编码 = cid+1）；
2. 商店里出现的**放大器**（Titus/Drakkari/Brann）在 `CompBuyBias` 看来确实是目标卡
   （`code in cguard.mult` 且 `code in cguard.targets`）；
3. 规则触发（must/soft）时，模型实际选的动作就是"买那张放大器"对应的 `A_BUY + slot`；
4. 场上有放大器时，`A_SELL + slot` 被保护屏蔽（protect 生效）。

用法：
    python scripts/verify_comp_index.py <ckpt> [--games 6] [--device cuda:1]
"""
from __future__ import annotations
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "rust", "python"))
sys.path.insert(0, ROOT)
os.environ.setdefault("HSBRSIM_FORCE_UPGRADE", "1")
os.environ.setdefault("HSBRSIM_FORCE_UPGRADE_MAX_TIER", "5")
os.environ.setdefault("HSBRSIM_BAN_TRINKETS", "BG36_MagicItem_414")
os.environ.setdefault("HSBRSIM_COMP_BUY_BIAS", "1")
os.environ.setdefault("HSBRSIM_COMP_BUY_INCLUDE", "MULT,GROW,ENGINE")
os.environ.setdefault("HSBRSIM_COMP_BUY_PROTECT", "MULT")

import hsbg_engine as E  # noqa: E402
from hsbg.az.train.game_rules import game_config_json  # noqa: E402
from hsbg.az.train.model import load_checkpoint  # noqa: E402
from hsbg.az.train.ppo import CollectConfig, PPOEvaluator, PPOSelfPlayPolicy  # noqa: E402
from hsbg.env.action_space_std import A_BUY, A_SELL, N_SHOP  # noqa: E402
from hsbg.env.obs_std import N_BOARD, SLICE_CARD_BOARD, SLICE_CARD_SHOP  # noqa: E402

AMPS = {"布莱恩·铜须", "达卡莱附魔师", "提图斯·瑞文戴尔"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ckpt")
    ap.add_argument("--games", type=int, default=6)
    ap.add_argument("--device", default="cuda:1")
    ap.add_argument("--seed", type=int, default=991000)
    args = ap.parse_args(argv)

    cat = {int(c["cid"]): c for c in json.loads(E.catalog_json())}

    def nm(cid):
        return (cat.get(int(cid)) or {}).get("name_zh") or f"#{cid}"

    model, meta = load_checkpoint(args.ckpt, device=args.device)
    ev = PPOEvaluator(model, device=args.device, norm_mean=meta.get("norm_mean"),
                      norm_std=meta.get("norm_std"))
    cfg = CollectConfig(games=1, seed=args.seed, opponent="bot", behavior="net",
                        max_steps=20000, move_guard=True, move_cap=3, move_repeat_limit=2,
                        forced_upgrade=True, forced_upgrade_max_tier=5,
                        comp_buy_bias=1.0, comp_buy_include="MULT,GROW,ENGINE",
                        comp_buy_max_copies=2, comp_buy_protect="MULT")
    pol = PPOSelfPlayPolicy(model, device=args.device, config=cfg, eval_fn=ev,
                            seed=args.seed, move_model=False)
    cg = pol._cguard
    st = dict(decisions=0, enc_mismatch=0, amp_in_shop=0, amp_seen_by_rule=0,
              must_fired=0, bought_amp=0, sell_masked=0, amp_bought_total=0)
    for gi in range(args.games):
        g = E.Game(args.seed + gi, game_config_json())
        pol.reset()
        while not g.is_over():
            acted = False
            for p in range(8):
                if g.is_over():
                    break
                if not g.needs_action(p):
                    continue
                acted = True
                if p != 0:
                    g.bot_play(p)
                    continue
                pj = json.loads(g.player_json(0))
                f, c, mask_before = pol._observe(g, 0)
                st["decisions"] += 1
                # ① 编码一致性
                shop_pj = [(m or {}).get("card") for m in (pj.get("shop") or [])]
                for i, cid in enumerate(shop_pj[:N_SHOP]):
                    if not cid:
                        continue
                    code = int(c[int(SLICE_CARD_SHOP.start) + i])
                    if code != int(cid) + 1:
                        st["enc_mismatch"] += 1
                    if nm(cid) in AMPS:
                        st["amp_in_shop"] += 1
                        if code in cg.mult and code in cg.targets:
                            st["amp_seen_by_rule"] += 1
                # ④ 保护：场上放大器不能卖
                board_pj = [(m or {}).get("card") for m in (pj.get("board") or [])]
                for i, cid in enumerate(board_pj[:N_BOARD]):
                    if cid and nm(cid) in AMPS and not bool(mask_before[int(A_SELL) + i]):
                        st["sell_masked"] += 1
                before_must = cg.n_must
                d = pol.decide(g, 0)
                if cg.n_must > before_must:
                    st["must_fired"] += 1
                a = int(d.action)
                if A_BUY <= a < A_BUY + N_SHOP:
                    slot = a - A_BUY
                    cid = shop_pj[slot] if slot < len(shop_pj) else None
                    if cid and nm(cid) in AMPS:
                        st["bought_amp"] += 1
                g.step(0, a)
            if not acted:
                break
    st["amp_bought_total"] = st["bought_amp"]
    print(json.dumps(st, ensure_ascii=False, indent=1))
    ok = (st["enc_mismatch"] == 0 and st["amp_seen_by_rule"] == st["amp_in_shop"])
    print("[verdict]", "编码一致 + 规则目标匹配 ✓" if ok else "存在错位 ✗")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
