"""金色农场探针（task-8）：对子台账 + 三连优先 + 冻结，旁路不改 `compound_script.py`。

动机：机制审计（§9）证明引擎忠实，缺的是频率——教师 `goldens_p50` 0–2，而真实 62.1%
身材来自 `_G`。本脚本在 `CompoundPolicy` 外面包一层**对子台账**：

1. 每步统计 `board + hand` 每个 minion id 的拥有数；商店里出现「第 3 张」时**优先买**；
2. `pair_aware_freeze` 变体：第 3 张出现但当下买不起/手牌满 → **冻结**（A_FREEZE），
   下回合优先回买；
3. 手牌满时先**打出**一张非核心随从（或先卖非核心腾棋位）再买第 3 张；
4. 不覆盖基策略买放大器/载体/法术的优先级。

三组同 seed：`base` / `pair_aware` / `pair_aware_freeze`；两种收入口径 fixed20 / fixed30。
报告：golden 数/局、t15 Σ p50、Σ/N、r12_15、花费率、放大器触发次数/局。

用法：
    python scripts/golden_farm_probe.py --games 24 --workers 12
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    A_BUY, END_TURN, EconomySandbox, SandboxConfig)
from compound_script import AMP_BY_ID, CompoundPolicy, _is_carrier  # noqa: E402

A_PLAY_LO, A_PLAY_HI = 46, 126
#: 冻结整馆（动作 2，与 ACTION_SPACE_STD 一致）
A_FREEZE = 2
AMPS = {
    "Brann": {"BG_LOE_077", "TB_BaconUps_045", "BG_LOE_077_G", "TB_BaconUps_045_t"},
    "Titus": {"BG25_354", "BG25_354_G"},
    "Gatekeeper": {"BG36_640", "BG36_640_G"},
}
TRIGGER_STAT = {"Brann": "battlecries_triggered", "Titus": "deathrattles_triggered",
                "Gatekeeper": "spells_cast"}
NAME_TO_AMP = {"Brann Bronzebeard": "Brann", "Titus Rivendare": "Titus",
               "Gatekeeper Amalgam": "Gatekeeper"}


class PairPolicy(CompoundPolicy):
    """在基策略之上：对子台账 → 优先第 3 张；可选冻结；满手先腾位。"""

    def __init__(self, *, freeze: bool = False, camping: bool = False,
                 camp_until: Optional[Dict[int, int]] = None, **kw: Any) -> None:
        super().__init__(**kw)
        self.freeze = bool(freeze)
        self.camping = bool(camping)
        #: 目标 tier → 在该 turn 之前不允许升上去（tier-camping）
        self.camp_until = dict(camp_until or {5: 8, 6: 11})
        self.triple_buys = 0
        self.pair_freezes = 0
        self.camp_blocked = 0
        self._freeze_turn = -1
        self._last_turn = -1

    @staticmethod
    def _counts(me: dict) -> Dict[str, int]:
        cnt: Dict[str, int] = {}
        for m in (me.get("board") or []):        # 棋盘只可能是随从
            cid = str(m.get("id") or "")
            cnt[cid] = cnt.get(cid, 0) + 1
        for it in (me.get("hand") or []):
            if str(it.get("type")) == "minion":
                cid = str(it.get("id") or "")
                cnt[cid] = cnt.get(cid, 0) + 1
        return cnt

    def act(self, v: dict, mask: np.ndarray) -> int:
        me = v.get("me") or {}
        base = int(super().act(v, mask))
        if me.get("pending") or v.get("phase") != "recruit" or me.get("ended_turn"):
            return base
        cnt = self._counts(me)
        shop = me.get("shop") or []
        hand = me.get("hand") or []
        # 第 3 张：owned==2 且商店有同 id
        third: List[int] = []
        pair_one: List[int] = []
        for i, it in enumerate(shop[:8]):
            if str(it.get("type")) != "minion":
                continue
            cid = str(it.get("id") or "")
            n = cnt.get(cid, 0)
            if n >= 2:
                third.append(i)
            elif n == 1:
                pair_one.append(i)
        if not third:
            return self._maybe_camp(v, me, mask, base)
        # 商店的第 3 张：能买就买
        for i in third:
            if bool(mask[A_BUY + i]):
                self.triple_buys += 1
                return int(A_BUY + i)
        # 买不起/手牌满：先腾手牌位（打出一张非核心随从），或卖非核心腾棋位
        hand_full = len(hand) >= 10
        if hand_full:
            board = me.get("board") or []
            for h, it in enumerate(hand[:10]):
                if str(it.get("type")) != "minion":
                    continue
                cid = str(it.get("id") or "")
                if cid in AMP_BY_ID or _is_carrier(it):
                    continue
                for pos in range(len(board) + 1):
                    a = A_PLAY_LO + h * 8 + pos
                    if a < A_PLAY_HI and bool(mask[a]):
                        return int(a)
            if len(board) >= 7:
                for j, m in enumerate(board):
                    cid = str(m.get("id") or "")
                    if cid in AMP_BY_ID or _is_carrier(m):
                        continue
                    if 16 <= 16 + j < 23 and bool(mask[16 + j]):
                        return int(16 + j)
        # 冻结：第 3 张还在商店且买不到 → 冻住（每回合最多一次；下一回合再买）
        t = int(v.get("turn") or 0)
        if t != self._last_turn:
            self._last_turn = t
        if self.freeze and self._freeze_turn != t and int(me.get("gold") or 0) < 3 \
                and bool(mask[A_FREEZE]):
            self._freeze_turn = t
            self.pair_freezes += 1
            return int(A_FREEZE)
        # tier-camping：基策略想升级、但目标 tier 的「最早回合」还没到 → 换别的动作
        return self._maybe_camp(v, me, mask, base)

    def _maybe_camp(self, v: dict, me: dict, mask: np.ndarray, base: int) -> int:
        if not self.camping or int(base) != 3:      # A_UPGRADE
            return int(base)
        t = int(v.get("turn") or 0)
        tier = int(me.get("tier") or 0)
        limit = self.camp_until.get(tier + 1)
        if limit is not None and t < int(limit):
            alt = self._camp_fallback(v, me, mask)
            if alt is not None:
                self.camp_blocked += 1
                return int(alt)
        return int(base)

    def _camp_fallback(self, v: dict, me: dict, mask: np.ndarray) -> Optional[int]:
        """不升级时做什么：买（优先对子）→ 打出手牌随从 → 刷新 → 结束回合。"""
        shop = me.get("shop") or []
        board = me.get("board") or []
        hand = me.get("hand") or []
        for i, it in enumerate(shop[:8]):
            if str(it.get("type")) == "minion" and bool(mask[A_BUY + i]):
                self.triple_buys += 0
                return int(A_BUY + i)
        for h, it in enumerate(hand[:10]):
            if str(it.get("type")) != "minion":
                continue
            for pos in range(len(board) + 1):
                a = A_PLAY_LO + h * 8 + pos
                if a < A_PLAY_HI and bool(mask[a]):
                    return int(a)
        if int(me.get("gold") or 0) >= 1 and bool(mask[1]) \
                and int(getattr(self, "refreshes", 0)) < int(self.max_refresh):
            self.refreshes = int(getattr(self, "refreshes", 0)) + 1
            return 1
        if bool(mask[END_TURN]):
            return int(END_TURN)
        return None


TRIG_KEYS = {"Brann": ("battlecries_triggered", None), "Titus": ("deathrattles_triggered", None),
             "Gatekeeper": ("spells_cast", None), "Drakkari": (None, "end of turn:")}


def _run_arm(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    arm = payload["arm"]
    cfg = payload["cfg"]
    games = int(payload["games"])
    seed0 = int(payload["seed0"])
    freeze = bool(payload["freeze"])
    camping = bool(payload.get("camping"))
    out: List[Dict[str, Any]] = []
    for gi in range(games):
        seed = seed0 + gi
        env = EconomySandbox(cfg)
        obs = env.reset(seed)
        env.g.set_record_log(True)
        if arm == "base":
            pol = CompoundPolicy(seed=seed)
        else:
            pol = PairPolicy(seed=seed, freeze=freeze, camping=camping)
        prev = json.loads(env.g.view(0))
        prev_stats = dict(prev["me"].get("stats") or {})
        prev_log = len(env.g.log())
        last_turn = int(env.g.turn)
        amp_trig = {a: 0 for a in TRIGGER_STAT}
        eot = 0
        max_goldens = 0
        third_slots = 0          # 商店里「第 3 张」出现的槽次数/局
        third_steps = 0          # 至少出现一次第 3 张的决策步数
        dwell = {t: 0 for t in range(1, 8)}   # 各 tier 的回合数（回合开始记）
        seen_turns = set()
        while not env.done:
            v = json.loads(env.g.view(0))
            me = v.get("me") or {}
            t = int(v.get("turn") or 0)
            tier_now = int(me.get("tier") or 0)
            if t not in seen_turns:
                seen_turns.add(t)
                dwell[tier_now] = dwell.get(tier_now, 0) + 1
            # 第 3 张可见性：商店里 owned>=2 的同名牌
            cnt = {}
            for m in (me.get("board") or []):
                cid = str(m.get("id") or "")
                cnt[cid] = cnt.get(cid, 0) + 1
            for it in (me.get("hand") or []):
                if str(it.get("type")) == "minion":
                    cid = str(it.get("id") or "")
                    cnt[cid] = cnt.get(cid, 0) + 1
            n3 = sum(1 for it in (me.get("shop") or [])[:8]
                     if str(it.get("type")) == "minion"
                     and cnt.get(str(it.get("id") or ""), 0) >= 2)
            third_slots += n3
            if n3:
                third_steps += 1
            board_ids = {str(m.get("id") or "") for m in (me.get("board") or [])}
            present = {a: bool(AMPS[a] & board_ids) for a in AMPS}
            a = int(pol.act(v, obs.mask))
            obs, _r, done, _info = env.step(a)
            v2 = json.loads(env.g.view(0))
            board2 = (v2.get("me") or {}).get("board") or []
            max_goldens = max(max_goldens, sum(1 for m in board2 if bool(m.get("golden"))))
            st2 = dict((v2.get("me") or {}).get("stats") or {})
            for amp, key in TRIGGER_STAT.items():
                d = int(st2.get(key) or 0) - int(prev_stats.get(key) or 0)
                if d > 0 and present[amp]:
                    amp_trig[amp] += d
            t2 = int(env.g.turn)
            if t2 != last_turn or env.done:
                logs = env.g.log()
                new = logs[prev_log:]
                prev_log = len(logs)
                if present.get("Drakkari"):
                    eot += sum(1 for ln in new if "end of turn:" in str(ln))
                last_turn = t2
            prev_stats = st2
        ep = env.episode_summary()
        p = json.loads(env.g.player_json(0))
        board = p.get("board") or []
        goldens = sum(1 for m in board if bool(m.get("golden")))
        s12 = int(ep.get("sigma_t12") or 0)
        s15 = int(ep.get("sigma_t15") or 0)
        n15 = len(board)
        income = int(ep.get("gold_total_income") or 0)
        spent = int((p.get("stats") or {}).get("gold_spent_total") or 0)
        out.append({"seed": seed, "goldens_t15": goldens,
                    "goldens_max": max_goldens,
                    "golden_played": int((p.get("stats") or {}).get("golden_played") or 0),
                    "sigma_t12": s12, "sigma_t15": s15, "n15": n15,
                    "sigma_per_n": s15 / n15 if n15 else 0.0,
                    "r12_15": s15 / max(1, s12),
                    "spend_rate": spent / income if income > 0 else 0.0,
                    "amp_triggers": dict(amp_trig), "drakkari_eot": eot,
                    "third_slots": third_slots, "third_steps": third_steps,
                    "dwell_t4": dwell.get(4, 0), "dwell_t5": dwell.get(5, 0),
                    "dwell_t6": dwell.get(6, 0),
                    "dwell45": dwell.get(4, 0) + dwell.get(5, 0),
                    "triple_buys": int(getattr(pol, "triple_buys", 0)),
                    "camp_blocked": int(getattr(pol, "camp_blocked", 0)),
                    "pair_freezes": int(getattr(pol, "pair_freezes", 0))})
    return out


def _pct(v: Sequence[float], q: float) -> float:
    return float(np.percentile(np.asarray(v, dtype=np.float64), q)) if v else 0.0


def _summarize(eps: List[Dict[str, Any]]) -> Dict[str, Any]:
    def col(k: str) -> List[float]:
        return [float(e.get(k) or 0) for e in eps]

    xs = col("dwell45")
    ys = col("goldens_max")
    corr = 0.0
    if len(xs) >= 3 and np.std(xs) > 0 and np.std(ys) > 0:
        corr = float(np.corrcoef(np.asarray(xs), np.asarray(ys))[0, 1])
    buckets: Dict[str, Any] = {}
    for lo, hi in ((0, 2), (3, 4), (5, 99)):
        sel = [e for e in eps if lo <= int(e.get("dwell45") or 0) <= hi]
        if sel:
            buckets[f"{lo}-{hi if hi < 99 else '+'}"] = {
                "games": len(sel),
                "goldens_max_mean": round(float(statistics.mean(
                    [float(e.get("goldens_max") or 0) for e in sel])), 2),
                "sigma_t15_p50": _pct([float(e.get("sigma_t15") or 0) for e in sel], 50),
            }
    return {
        "games": len(eps),
        "goldens_mean": round(float(statistics.mean(col("goldens_t15"))), 2),
        "goldens_p50": _pct(col("goldens_t15"), 50),
        "goldens_max_mean": round(float(statistics.mean(col("goldens_max"))), 2),
        "goldens_max_p50": _pct(col("goldens_max"), 50),
        "golden_played_mean": round(float(statistics.mean(col("golden_played"))), 2),
        "golden_rate": round(float(np.mean([1.0 if g > 0 else 0.0 for g in col("goldens_t15")])), 3),
        "sigma_t15_p50": _pct(col("sigma_t15"), 50),
        "sigma_t15_p90": _pct(col("sigma_t15"), 90),
        "N15_p50": _pct(col("n15"), 50),
        "sigma_per_N_p50": _pct(col("sigma_per_n"), 50),
        "r12_15_p50": _pct(col("r12_15"), 50),
        "spend_rate_mean": round(float(statistics.mean(col("spend_rate"))), 3),
        "third_slots_mean": round(float(statistics.mean(col("third_slots"))), 2),
        "third_steps_mean": round(float(statistics.mean(col("third_steps"))), 1),
        "dwell_t4_mean": round(float(statistics.mean(col("dwell_t4"))), 2),
        "dwell_t5_mean": round(float(statistics.mean(col("dwell_t5"))), 2),
        "dwell_t6_mean": round(float(statistics.mean(col("dwell_t6"))), 2),
        "dwell45_mean": round(float(statistics.mean(col("dwell45"))), 2),
        "corr_dwell45_goldens": round(corr, 3),
        "dwell_buckets": buckets,
        "triple_buys_mean": round(float(statistics.mean(col("triple_buys"))), 2),
        "camp_blocked_mean": round(float(statistics.mean(col("camp_blocked"))), 2),
        "pair_freezes_mean": round(float(statistics.mean(col("pair_freezes"))), 2),
        "amp_triggers_mean": {
            a: round(float(statistics.mean([e["amp_triggers"].get(a, 0) for e in eps])), 2)
            for a in ("Brann", "Titus", "Gatekeeper")},
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="golden farm probe: pair ledger + freeze")
    ap.add_argument("--games", type=int, default=24)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed0", type=int, default=880000)
    ap.add_argument("--gold-per-turn", dest="gpt", default="20,30",
                    help="逗号分隔的收入口径（fixed N 金/回合）")
    ap.add_argument("--lobby-races", dest="lobby_races", type=int, default=5,
                    help="大厅种族数（默认 5；越小同类牌越密 → 三连越容易）")
    ap.add_argument("--arms", default="base,pair_aware,pair_aware_freeze")
    ap.add_argument("--json-out", default=os.path.join(ROOT, "runs", "sandbox_econ",
                                                       "golden_farm.json"))
    args = ap.parse_args(argv)
    import multiprocessing as mp

    arms = [s.strip() for s in str(args.arms).split(",") if s.strip()]
    gpts = [int(x) for x in str(args.gpt).split(",") if x.strip()]
    payloads = []
    for gpt in gpts:
        extra = ()
        if int(args.lobby_races) != 5:
            # SandboxConfig.engine_config() 只在 lobby_types 非空时才写 lobby_races；
            # 这里用 extra 直接覆盖引擎 RulesConfig 的 lobby_races（纯配置，不改 Rust）
            extra = (("lobby_races", int(args.lobby_races)),)
        cfg = SandboxConfig(turns=15, gold_mode="fixed", gold_per_turn=gpt,
                            action_cap=40, num_players=8, trinkets=True,
                            gold_cap=99, lobby_types=(), extra=extra)
        for arm in arms:
            camping = arm == "pair_camp"
            freeze = arm != "base"
            payloads.append({"arm": arm, "cfg": cfg, "games": int(args.games),
                             "seed0": int(args.seed0), "freeze": freeze,
                             "camping": camping, "gpt": gpt, "offset": 0})
    with mp.get_context("fork").Pool(max(1, int(args.workers))) as pool:
        results = pool.map(_run_arm, payloads)
    cells: Dict[str, Any] = {}
    eps_all: Dict[str, Any] = {}
    for p, eps in zip(payloads, results):
        key = f"gpt{p['gpt']}_{p['arm']}"
        cells[key] = _summarize(eps)
        eps_all[key] = eps
    out: Dict[str, Any] = {"config": {"games": int(args.games), "seed0": int(args.seed0),
                                      "gold_per_turn": gpts,
                                      "teacher": "CompoundPolicy / PairPolicy",
                                      "criteria": {"golden_ge": 5,
                                                   "sigma_t15_p50_fixed30": 2500,
                                                   "sigma_t15_p50_fixed20": 2000}},
                           "cells": cells}
    for key, c in cells.items():
        gold_ok = c["goldens_max_p50"] >= 5
        shape_ok = c["r12_15_p50"] >= 2.0
        c["pass"] = bool(gold_ok or shape_ok)   # 判据：golden>=5 或 r12>=2
        c["pass_golden"] = gold_ok
        c["pass_shape"] = shape_ok
    out["verdict"] = {
        "pass_cells": [k for k, c in cells.items() if c["pass"]],
        "golden_ge_5": [k for k, c in cells.items() if c["pass_golden"]],
        "r12_ge_2": [k for k, c in cells.items() if c["pass_shape"]],
        "note": "pass = (goldens>=5) OR (r12_15>=2); 'golden not sufficient' only if goldens>=5 and r12 flat",
    }
    out["episodes"] = eps_all
    os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for key, c in cells.items():
        print(f"{key:26s} goldens_max={c['goldens_max_mean']:5.2f} (p50 {c['goldens_max_p50']:.1f}) "
              f"goldens_t15={c['goldens_mean']:5.2f} S15p50={c['sigma_t15_p50']:7.1f} "
              f"S/N={c['sigma_per_N_p50']:7.1f} r12={c['r12_15_p50']:.3f} "
              f"spend={c['spend_rate_mean']:.2f} third={c['third_slots_mean']:.1f} "
              f"dwell45={c['dwell45_mean']:.1f} camp={c['camp_blocked_mean']:.1f} "
              f"pass={c['pass']}", flush=True)
    print(f"WROTE {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
