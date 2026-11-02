#!/usr/bin/env python3
"""链条漏斗采集器（纯推理，不训练）：逐回合记录商店/amp 生命周期/gold-tier/强度。

回答「tier 4→5 卡在哪一环」：
  (a) 5/6 星关键牌与放大器从未出现在商店；
  (b) 出现了但没买；(c) 买了但没上场（还在手牌）；
  (d) 上场但没触发（用「在场且 Σ 增长」做代理）；(e) 都做了但 Σ 增量不够。

用法::

  PYTHONPATH=rust/python:. python scripts/chain_collector.py \
    --checkpoint runs/az_entity_s25/model.pt --games 200 --device cuda:6 \
    --out-dir runs/az_entity_s25/collector

产物：``<out-dir>/games.jsonl.gz``（逐局）与 ``<out-dir>/funnel35.json``（汇总）。
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from typing import Any, Dict, List, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hsbg.az.train.common import mask_from_bytes  # noqa: E402


def _card_of(x: Any) -> Optional[str]:
    """从 pending option（dict/nested dict/str）里尽力提取卡牌 id。"""
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        for k in ("card", "id", "card_id"):
            if k in x and isinstance(x[k], str):
                return x[k]
        for v in x.values():
            got = _card_of(v)
            if got:
                return got
    return None

from hsbg.env.action_space_std import (A_BUY, A_CHOOSE, A_END, A_FREEZE, A_MOVE,
                                      A_PLAY, A_REFRESH, A_SELL, A_UPGRADE,
                                      N_CHOICE, N_SHOP)  # noqa: E402

#: 三连奖励 spell id（Discover a minion of tier `data`）；见 rust/.../content/spells.rs:386
TRIPLE_REWARD_ID = "TB_BaconShop_Triples_01"

#: 放大器（docs/FULL_GAME_TRANSFER.md §2：Titus / Drakkari 是 t5，Gatekeeper 是 t6）
_AMP_NAME_KEYS = ("titus rivendare", "drakkari enchanter", "gatekeeper")

ACTION_NAME = {A_END: "end", A_REFRESH: "refresh", A_FREEZE: "freeze", A_UPGRADE: "upgrade"}


def _action_name(a: int) -> str:
    if a in ACTION_NAME:
        return ACTION_NAME[a]
    if A_BUY <= a < A_BUY + N_SHOP:
        return f"buy[{a - A_BUY}]"
    if A_SELL <= a < A_SELL + 7:
        return f"sell[{a - A_SELL}]"
    if A_PLAY <= a < A_PLAY + 10 * 8:
        h, p = divmod(a - A_PLAY, 8)
        return f"play[h{h}->p{p}]"
    if A_MOVE <= a < A_MOVE + 7 * 7:
        return f"move[{a - A_MOVE}]"
    return f"a{a}"


def load_cards() -> tuple:
    """→ (by_str_id, cid2id, amp_ids, key56_ids)。"""
    cards = json.load(open(os.path.join(ROOT, "data/p2/cards_37.json"), encoding="utf-8"))
    if isinstance(cards, dict):
        cards = cards.get("cards") or cards.get("data") or list(cards.values())
    cards = [c for c in cards if isinstance(c, dict) and c.get("id")]
    by_id = {str(c["id"]): c for c in cards}
    amp_ids = {str(c["id"]) for c in cards
               if any(k in str(c.get("name") or "").lower() for k in _AMP_NAME_KEYS)}
    key56 = {str(c["id"]) for c in cards
             if int(c.get("tier") or 0) >= 5 and str(c.get("kind") or "").lower() in
             ("minion", "battleground_minion", "")}
    import hsbg_engine as E
    cid2id = {int(c["cid"]): str(c["id"]) for c in json.loads(E.catalog_json())}
    return by_id, cid2id, amp_ids, key56


def _shop_rows(pj: dict, cid2id: dict, by_id: dict, amp_ids: set, key56: set) -> List[dict]:
    rows = []
    for slot, raw in enumerate(pj.get("shop") or []):
        item = (raw or {}).get("item") if isinstance(raw, dict) else None
        if not isinstance(item, dict):
            continue
        key = "Minion" if "Minion" in item else ("Spell" if "Spell" in item else None)
        m = item.get(key) if key else None
        if not isinstance(m, dict):
            continue
        cid = cid2id.get(int(m.get("card") or -1), "")
        meta = by_id.get(cid) or {}
        rows.append({
            "slot": slot, "card": cid, "name": meta.get("name"),
            "tier": int(meta.get("tier") or 0), "kind": key.lower(),
            "is_amp": cid in amp_ids, "is_key56": cid in key56,
        })
    return rows


def _resolve_targets(spec: str) -> set:
    """`amp,engine,all,<id>` → 目标卡集合（与 quality_monitor 同口径）。"""
    amp = {"BG25_354", "BG25_354_G", "BG26_ICC_901", "BG26_ICC_901_G",
           "BG36_640", "BG36_640_G"}
    eng = {"BG36_762", "BG36_762_G", "BG28_633", "BG28_633_G",
           "BG36_704", "BG36_704_G", "BG_LOE_077", "BG_LOE_077_G"}
    out: set = set()
    for tok in [x.strip() for x in str(spec or "").split(",") if x.strip()]:
        if tok == "amp":
            out |= amp
        elif tok in ("engine", "engines"):
            out |= eng
        elif tok == "all":
            out |= amp | eng
        else:
            out.add(tok)
    return out


def play_one(seed: int, policy, cid2id: dict, by_id: dict, amp_ids: set,
             key56: set, max_steps: int = 20000,
             discover_bias: float = 0.0,
             discover_targets: set = frozenset(),
             triple_bias: float = 0.0,
             pair_freeze: int = 0) -> Optional[dict]:
    import hsbg_engine as E
    game = E.Game(seed=int(seed))
    policy.reset()
    turns: List[dict] = []
    last_turn = -1
    steps = 0
    amp_events: List[dict] = []
    discovers: List[dict] = []
    goldens_seen: set = set()
    prev_strength = 0
    while not game.is_over() and steps < max_steps:
        t = int(game.turn)
        if t != last_turn:
            last_turn = t
            pj = json.loads(game.player_json(0))
            board = [cid2id.get(int(m.get("card") or -1), "") for m in (pj.get("board") or [])]
            hand = [cid2id.get(int(m.get("card") or -1), "") for m in (pj.get("hand") or [])]
            strength = sum(int(m.get("atk") or 0) + int(m.get("hp") or 0)
                           for m in (pj.get("board") or []))
            shop = _shop_rows(pj, cid2id, by_id, amp_ids, key56)
            for cid in board + hand:                      # goldens/局（'_G' 后缀即金色）
                if str(cid).endswith("_G"):
                    goldens_seen.add(str(cid))
            for r in shop:
                if r["is_amp"]:
                    amp_events.append({"card": r["card"], "turn": t, "stage": "appear",
                                       "slot": r["slot"]})
            for cid in hand:
                if cid in amp_ids:
                    amp_events.append({"card": cid, "turn": t, "stage": "hand"})
            if any(c in amp_ids for c in board):
                amp_events.append({"card": "|".join(c for c in board if c in amp_ids),
                                   "turn": t, "stage": "board"})
            turns.append({
                "turn": t, "gold": int(pj.get("gold") or 0), "tier": int(pj.get("tier") or 0),
                "health": int(pj.get("health") or 0), "alive": bool(pj.get("alive", True)),
                "strength": strength, "count": len(board), "board": board, "hand": hand,
                "shop": shop, "actions": [], "upgrade": False, "rolls": 0, "freezes": 0,
                "amp_on_board": [c for c in board if c in amp_ids],
                "strength_delta": strength - prev_strength,
            })
            prev_strength = strength
        acted = False
        for p in range(8):
            if game.is_over():
                break
            if not game.needs_action(p):
                continue
            acted = True
            steps += 1
            if p == 0:
                # ── pending Discover 捕获（只有出现 choose 合法位时才取 view，省时间）──
                _pend_idx = None
                try:
                    if bool(mask_from_bytes(game.legal_mask(0))[A_CHOOSE:A_CHOOSE + N_CHOICE].any()):
                        view = json.loads(game.view(0))
                        pend = (view.get("me") or {}).get("pending")
                        entries = pend if isinstance(pend, list) else ([pend] if pend else [])
                        for e in entries:
                            if isinstance(e, dict) and str(e.get("kind")) == "discover":
                                opts = [_card_of(x) for x in (e.get("options") or [])]
                                _src = e.get("source")
                                if isinstance(_src, dict):
                                    _src = _src.get("id") or _src.get("cid")
                                elif isinstance(_src, int):
                                    _src = cid2id.get(int(_src), f"#{_src}")
                                _pend_idx = len(discovers)
                                discovers.append({
                                    "turn": int(game.turn), "tier": int(turns[-1]["tier"]),
                                    "source": str(_src),
                                    "option_tiers": [int((by_id.get(c) or {}).get("tier") or 0)
                                                     for c in opts],
                                    "options": opts, "chosen": None})
                                # Discover 选牌先验：只对含目标卡的 choose 位加 bias
                                _ev = getattr(policy, "eval_fn", None)
                                if discover_bias > 0.0 and hasattr(_ev, "set_dynamic_bias"):
                                    _bias = {A_CHOOSE + i: float(discover_bias)
                                             for i, c in enumerate(opts)
                                             if c in discover_targets}
                                    _ev.set_dynamic_bias(_bias or None)
                                break
                except BaseException:  # noqa: BLE001 - 采集是尽力而为
                    _pend_idx = None
                # ── 三连/对子先验：必须在 decide 之前设置 ──────────────────────
                _froze = False
                if (triple_bias > 0.0 or pair_freeze) and cid2id:
                    try:
                        from quality_monitor import _triple_bias_map
                        _pj2 = json.loads(game.player_json(0))
                        _m2 = mask_from_bytes(game.legal_mask(0))
                        _ev3 = getattr(policy, "eval_fn", None)
                        if triple_bias > 0.0 and hasattr(_ev3, "set_dynamic_bias"):
                            _tb = _triple_bias_map(_pj2, cid2id, triple_bias)
                            if _tb:
                                _ev3.set_dynamic_bias(_tb)
                        if pair_freeze:
                            _own = {}
                            for k in ("board", "hand"):
                                for mm in (_pj2.get(k) or []):
                                    c = cid2id.get(int(mm.get("card") or -1), "")
                                    if c and not c.endswith("_G"):
                                        _own[c] = _own.get(c, 0) + 1
                            _need = False
                            for r in (_pj2.get("shop") or []):
                                item = (r or {}).get("item") if isinstance(r, dict) else None
                                mm = (item or {}).get("Minion") if isinstance(item, dict) else None
                                if not isinstance(mm, dict):
                                    continue
                                c = cid2id.get(int(mm.get("card") or -1), "")
                                if c and _own.get(c, 0) >= 2:
                                    _need = True
                                    break
                            if _need and int(_pj2.get("gold") or 0) < 3 and bool(_m2[3]):
                                a = 3            # A_FREEZE（本决策直接结束：冻一下留第三张）
                                _froze = True
                    except BaseException:  # noqa: BLE001
                        _froze = False
                a = int(3) if '_froze' in dir() and _froze else int(policy.decide(game, 0).action)
                _ev2 = getattr(policy, "eval_fn", None)
                if hasattr(_ev2, "set_dynamic_bias"):
                    _ev2.set_dynamic_bias(None)   # 用完即清
                rec = {"a": a, "name": _action_name(a)}
                if _pend_idx is not None and A_CHOOSE <= a < A_CHOOSE + N_CHOICE:
                    i = a - A_CHOOSE
                    opts = discovers[_pend_idx]["options"]
                    discovers[_pend_idx]["chosen"] = opts[i] if i < len(opts) else None
                if A_BUY <= a < A_BUY + N_SHOP:
                    slot = a - A_BUY
                    hit = [r for r in (turns[-1]["shop"] or []) if r["slot"] == slot]
                    rec["bought"] = hit[0]["card"] if hit else None
                    if hit and hit[0]["is_amp"]:
                        amp_events.append({"card": hit[0]["card"], "turn": int(game.turn),
                                           "stage": "bought", "slot": slot})
                if a == A_UPGRADE:
                    turns[-1]["upgrade"] = True
                if a == A_REFRESH:
                    turns[-1]["rolls"] += 1
                if a == A_FREEZE:
                    turns[-1]["freezes"] += 1
                turns[-1]["actions"].append(rec)
                game.step(0, a)
            else:
                game.bot_play(p)
        if not acted and not game.is_over():
            break
    if not game.is_over():
        return None
    placements = list(game.placements())
    pj = json.loads(game.player_json(0))
    return {
        "seed": int(seed),
        "placement": int(placements[0]),
        "turns": turns,
        "amp_events": amp_events,
        "discovers": discovers,
        "goldens": sorted(goldens_seen),
        "final_strength": sum(int(m.get("atk") or 0) + int(m.get("hp") or 0)
                              for m in (pj.get("board") or [])),
        #: 终局逐随从明细（用于算「t5+ 身材占比」：金卡/高星有没有真的用在身材上）
        "final_board": [{
            "card": cid2id.get(int(m.get("card") or -1), ""),
            "tier": int(((by_id.get(cid2id.get(int(m.get("card") or -1), ""))) or {}).get("tier") or 0),
            "atk": int(m.get("atk") or 0), "hp": int(m.get("hp") or 0),
            "golden": str(cid2id.get(int(m.get("card") or -1), "")).endswith("_G"),
        } for m in (pj.get("board") or [])],
        "final_tier": int(pj.get("tier") or 0),
        "death_turn": int(game.turn),
    }


def summarize_paths(games: List[dict], amp_ids: set,
                    targets: set = frozenset()) -> dict:
    """两条并列路径分开统计（不合并）：① 商店/刷新；② 三连奖励 Discover。"""
    n = max(1, len(games))
    # ── 路径①：tier≥5 回合的商店出现率 / 购买率 ──
    t5_turns = t5_slots = amp_slots = amp_buys = 0
    for g in games:
        for row in g["turns"]:
            if int(row.get("tier") or 0) >= 5:
                t5_turns += 1
                t5_slots += len(row.get("shop") or [])
                for r in row.get("shop") or []:
                    if r.get("is_amp"):
                        amp_slots += 1
            for act in row.get("actions") or []:
                if act.get("bought") in amp_ids:
                    amp_buys += 1
    # ── 路径②：三连 → Discover 选项/选择 ──
    disc_all = [d for g in games for d in g.get("discovers") or []]
    disc_triple = [d for d in disc_all
                   if str(d.get("source")) == TRIPLE_REWARD_ID
                   or (d.get("data") is not None and "Triples" in str(d.get("source")))]
    opt_slots = sum(len(d.get("options") or []) for d in disc_triple)
    opt_amp = sum(1 for d in disc_triple for c in (d.get("options") or []) if c in amp_ids)
    chosen_amp = sum(1 for d in disc_triple if d.get("chosen") in amp_ids)
    # 目标卡（放大器 + 引擎卡）口径
    _tg = set(targets) or set(amp_ids)
    opt_tg = sum(1 for d in disc_triple for c in (d.get("options") or []) if c in _tg)
    disc_with_tg = sum(1 for d in disc_triple
                       if any(c in _tg for c in (d.get("options") or [])))
    chosen_tg = sum(1 for d in disc_triple if d.get("chosen") in _tg)
    # ── goldens / tier≥5 回合占比 ──
    goldens = [len(g.get("goldens") or []) for g in games]
    all_turns = sum(len(g["turns"]) for g in games)
    t5_share = (100.0 * t5_turns / max(1, all_turns))
    return {
        "games": len(games),
        "path1_shop": {
            "tier5plus_turns": t5_turns,
            "slots_scanned": t5_slots,
            "amp_slots_seen": amp_slots,
            "amp_appear_per_slot_pct": round(100.0 * amp_slots / max(1, t5_slots), 3),
            "amp_appear_per_tier5_turn_pct": round(100.0 * amp_slots / max(1, t5_turns), 2),
            "amp_bought_total": amp_buys,
            "amp_bought_per_appear_pct": round(100.0 * amp_buys / max(1, amp_slots), 1),
        },
        "path2_triple_discover": {
            "discover_events_total": len(disc_all),
            "triple_discover_events": len(disc_triple),
            "triples_per_game": round(len(disc_triple) / n, 3),
            "games_with_triple_pct": round(100.0 * sum(1 for g in games
                                                     if any(str(d.get("source")) == TRIPLE_REWARD_ID
                                                            for d in (g.get("discovers") or []))) / n, 1),
            "option_slots": opt_slots,
            "option_slots_with_amp": opt_amp,
            "discover_with_amp_pct": round(100.0 * opt_amp / max(1, opt_slots), 2),
            "chosen_amp": chosen_amp,
            "select_amp_given_offered_pct": round(100.0 * chosen_amp / max(1, opt_amp), 1),
            # 目标卡（放大器 + 引擎卡）口径
            "option_slots_with_target": opt_tg,
            "discover_with_target_pct": round(100.0 * opt_tg / max(1, opt_slots), 2),
            "triples_with_target": disc_with_tg,
            "chosen_target": chosen_tg,
            "select_target_given_offered_pct": round(100.0 * chosen_tg / max(1, disc_with_tg), 1),
        },
        "goldens_per_game": round(float(np.mean(goldens)), 3),
        "goldens_p50": float(np.percentile(goldens, 50)),
        "tier5plus_turn_share_pct": round(t5_share, 1),
        "amp_ids": sorted(amp_ids),
    }


def summarize(games: List[dict], amp_ids: set, key56: set) -> dict:
    n = len(games)
    out: Dict[str, Any] = {"games": n, "amp_ids": sorted(amp_ids)}
    # 每局名次/Σ
    out["mean_rank"] = round(float(np.mean([g["placement"] for g in games])), 3)
    out["win_rate"] = round(float(np.mean([g["placement"] == 1 for g in games])), 3)
    out["t15_strength_p50"] = float(np.percentile([g["final_strength"] for g in games], 50))
    # 漏斗：amp
    appear = [g for g in games if any(e["stage"] == "appear" for e in g["amp_events"])]
    bought = [g for g in games if any(e["stage"] == "bought" for e in g["amp_events"])]
    board = [g for g in games if any(e["stage"] == "board" for e in g["amp_events"])]
    trig = [g for g in board if any(r.get("amp_on_board") and r.get("strength_delta", 0) > 0
                                    for r in g["turns"])]
    def _rate(xs):
        return {"games": len(xs), "pct": round(100.0 * len(xs) / max(1, n), 1)}
    out["funnel_amp"] = {"appear": _rate(appear), "bought": _rate(bought),
                         "board": _rate(board), "trigger_proxy": _rate(trig)}
    # 漏斗：5/6 星关键牌
    k_appear = [g for g in games if any(r["is_key56"] for row in g["turns"] for r in row["shop"])]
    k_bought = [g for g in games if any((a.get("bought") in key56)
                                        for row in g["turns"] for a in row["actions"])]
    out["funnel_key56"] = {"appear": _rate(k_appear), "bought": _rate(k_bought)}
    # 逐回合 gold / tier / 该回合是否升 tier
    per_turn: Dict[str, Any] = {}
    for t in range(1, 16):
        rows = [row for g in games for row in g["turns"] if row["turn"] == t]
        if not rows:
            continue
        per_turn[str(t)] = {
            "n": len(rows),
            "gold_p50": float(np.percentile([r["gold"] for r in rows], 50)),
            "tier_p50": float(np.percentile([r["tier"] for r in rows], 50)),
            "tier_ge5_pct": round(100.0 * float(np.mean([r["tier"] >= 5 for r in rows])), 1),
            "upgrade_turn_pct": round(100.0 * float(np.mean([r["upgrade"] for r in rows])), 1),
            "strength_p50": float(np.percentile([r["strength"] for r in rows], 50)),
            "amp_board_pct": round(100.0 * float(np.mean([bool(r.get("amp_on_board")) for r in rows])), 1),
        }
    out["per_turn"] = per_turn
    # 卡点判定
    stuck = []
    if out["funnel_amp"]["appear"]["pct"] < 5.0:
        stuck.append("(a) 放大器从未出现在商店")
    elif out["funnel_amp"]["bought"]["pct"] < 0.5 * out["funnel_amp"]["appear"]["pct"]:
        stuck.append("(b) 出现了但很少买（买/见 < 50%）")
    elif out["funnel_amp"]["board"]["pct"] < 0.8 * out["funnel_amp"]["bought"]["pct"]:
        stuck.append("(c) 买了但没上场")
    else:
        stuck.append("(d/e) 上场了但触发代理低或 Σ 增量不够")
    out["stuck_at"] = stuck
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--arch", default="entity")
    ap.add_argument("--device", default="cuda:6")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--seed-base", type=int, default=520000)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--out-dir", default="runs/az_entity_s25/collector")
    ap.add_argument("--discover-bias", type=float, default=0.0,
                    help="Discover 选牌先验（默认 0=关闭）：选项含目标卡时给对应 choose 位加该常数")
    ap.add_argument("--discover-targets", default="amp,engine",
                    help="目标卡集合：amp / engine / all / 逗号分隔卡 id（默认 amp,engine）")
    ap.add_argument("--tag", default="", help="输出文件名后缀（如 bias1p0）")
    ap.add_argument("--triple-bias", type=float, default=0.0,
                    help="三连/对子先验（默认 0=关闭）：商店里能凑三连(+2W)/对子(+W)时给 buy 位加常数")
    ap.add_argument("--pair-freeze", type=int, default=0, choices=[0, 1],
                    help="1=差一张三连且买不起时执行 freeze")
    args = ap.parse_args()

    from hsbg.az.train.model import load_checkpoint
    from hsbg.az.train.ppo import CollectConfig, PPOEvaluator, PPOSelfPlayPolicy

    os.makedirs(os.path.join(ROOT, args.out_dir), exist_ok=True)
    by_id, cid2id, amp_ids, key56 = load_cards()
    print(f"[collector] amp_ids={sorted(amp_ids)} key56_n={len(key56)}", flush=True)
    model, meta = load_checkpoint(args.checkpoint, device=args.device)
    ev = PPOEvaluator(model, device=args.device,
                      norm_mean=meta.get("norm_mean"), norm_std=meta.get("norm_std"))
    # Discover 选牌先验 / 三连先验：包装 evaluator（默认 0 = 不包装 ⇒ 逐位等价）
    _tg = _resolve_targets(args.discover_targets)
    _tw = float(getattr(args, "triple_bias", 0.0) or 0.0)
    _pf = int(getattr(args, "pair_freeze", 0) or 0)
    if float(args.discover_bias) > 0.0 or _tw > 0.0 or _pf:
        from quality_monitor import _LogitBiasEvaluator  # 同目录脚本
        ev = _LogitBiasEvaluator(ev, {})
        print(f"[collector] discover_bias={float(args.discover_bias)} triple_bias={_tw} "
              f"pair_freeze={_pf} targets={len(_tg)}", flush=True)
    cfg = CollectConfig(games=1, seed=int(args.seed_base), opponent="bot", behavior="net",
                        max_steps=int(args.max_steps), move_guard=True, move_cap=3,
                        move_repeat_limit=2)
    policy = PPOSelfPlayPolicy(model, device=args.device, config=cfg, eval_fn=ev,
                               seed=int(args.seed_base), move_model=False)

    games: List[dict] = []
    _suffix = f"_{args.tag}" if args.tag else ""
    path = os.path.join(ROOT, args.out_dir, f"games{_suffix}.jsonl.gz")
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for i in range(int(args.games)):
            g = play_one(int(args.seed_base) + i, policy, cid2id, by_id, amp_ids,
                         key56, max_steps=int(args.max_steps),
                         discover_bias=float(args.discover_bias),
                         discover_targets=_tg,
                         triple_bias=_tw, pair_freeze=_pf)
            if g is None:
                continue
            games.append(g)
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
            if (i + 1) % 20 == 0:
                print(f"[collector] {i + 1}/{args.games} games, mean_rank="
                      f"{np.mean([x['placement'] for x in games]):.3f}", flush=True)
    summary = summarize(games, amp_ids, key56)
    summary.update(summarize_paths(games, amp_ids))
    out = os.path.join(ROOT, args.out_dir, "funnel35.json")
    json.dump(summary, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    out2 = os.path.join(ROOT, args.out_dir, "triple_discover.json")
    json.dump({"games": len(games),
               "path1_shop": summary["path1_shop"],
               "path2_triple_discover": summary["path2_triple_discover"],
               "goldens_per_game": summary["goldens_per_game"],
               "tier5plus_turn_share_pct": summary["tier5plus_turn_share_pct"],
               "amp_ids": summary["amp_ids"],
               "mechanism": {
                   "triple_reward_spell": TRIPLE_REWARD_ID,
                   "engine_rule": "data=(player_tier+1).min(6); Discover 3 options with tier==data",
                   "source": "rust/crates/hsbg-engine/src/content/mod.rs:1610 triple_reward_item "
                             "+ content/spells.rs:386 (TB_BaconShop_Triples_01)"}},
              open(out2, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
