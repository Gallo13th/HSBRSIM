"""放大器「配合」旁路探针（不改 `compound_script.py`）。

背景：`docs/SANDBOX_ECON.md` §5 的审计显示，教师买了放大器却几乎不触发
（Brann 0.9–1.9 次/局、Titus 0–0.12、Drakkari 0），且「有放大器局」t15 Σ 更低。
本脚本在 `CompoundPolicy` 外面包一层**最小配合包**，同 seed 对照 base vs synergy：

1. Brann（战吼两次）→ 优先买/打**战吼**随从；
2. Titus（亡语两次）→ 优先买/打**亡语**随从；
3. Drakkari（回合末两次）→ 优先买/打**回合结束**随从；
4. Gatekeeper（施法给茶具）→ 优先买**法术**（并保持载体的施法目标）。

placement：放大器由基策略优先买；配合牌只在「基策略这一步不是买放大器/载体/法术」
时注入（避免破坏核心优先级）；满场卖随从时优先卖**不含配合文本**的那个。

报告：触发次数/局（引擎计量器，不是购买数）、ΔΣ/触发、触发器局 vs 无放大器局的
t15 Σ、r12_15、以及「每多 1 次触发 → ΔΣ」的边际价值（OLS 斜率）。

用法：
    python scripts/amp_synergy_probe.py --games 32 --gold-per-turn 15
    python scripts/amp_synergy_probe.py --games 32 --arms base,synergy --json-out runs/sandbox_econ/amp_synergy.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    A_BUY, END_TURN, EconomySandbox, SandboxConfig)
from compound_script import (  # noqa: E402
    AMP_BY_ID, CompoundPolicy, _is_carrier, catalog)

#: 放大器 id 集合（含金色）
AMPS = {
    "Brann": {"BG_LOE_077", "TB_BaconUps_045", "BG_LOE_077_G", "TB_BaconUps_045_t"},
    "Titus": {"BG25_354", "BG25_354_G"},
    "Drakkari": {"BG26_ICC_901", "BG26_ICC_901_G"},
    "Gatekeeper": {"BG36_640", "BG36_640_G"},
}
#: 触发计量器（Titus/Brann/Gatekeeper 有引擎计数器；Drakkari 用日志 EOT 行）
TRIGGER_STAT = {"Brann": "battlecries_triggered", "Titus": "deathrattles_triggered",
                "Gatekeeper": "spells_cast"}
#: 各放大器的「配合」文本
SYNERGY_TEXT = {"Brann": "battlecry", "Titus": "deathrattle", "Drakkari": "end of turn"}
NAME_TO_AMP = {"Brann Bronzebeard": "Brann", "Titus Rivendare": "Titus",
               "Drakkari Enchanter": "Drakkari", "Gatekeeper Amalgam": "Gatekeeper"}


def _synergy_sets() -> Dict[str, set]:
    """文本匹配出的配合牌 id 集合（只取 implemented & in_pool 的随从）。"""
    cat = catalog()
    out: Dict[str, set] = {a: set() for a in SYNERGY_TEXT}
    for cid, c in cat.items():
        if str(c.get("kind")) != "minion" or not c.get("implemented") or not c.get("in_pool"):
            continue
        text = str(c.get("text") or "").lower()
        for amp, pat in SYNERGY_TEXT.items():
            if pat in text:
                out[amp].add(cid)
    return out


SYN = _synergy_sets()
ALL_SYN = set().union(*SYN.values())


def _is_amp(cid: str) -> bool:
    return any(cid in ids for ids in AMPS.values())


def _stats_of(it: dict) -> int:
    return int(it.get("atk") or 0) + int(it.get("hp") or 0)


class SynergyPolicy(CompoundPolicy):
    """包装 ``CompoundPolicy``：在基策略不买核心时，优先补「放大器→配合牌」。"""

    def __init__(self, *, synergy_scale: float = 1.0, min_syn_stats: int = 0,
                 **kw: Any) -> None:
        super().__init__(**kw)
        self.synergy_scale = float(synergy_scale)
        #: 只买 ``atk+hp >= min_syn_stats`` 的配合随从（0 = 不限；防「低身材战吼」稀释战团）
        self.min_syn_stats = int(min_syn_stats)
        self.bought_syn = 0
        self.played_syn = 0

    def _amps_on_board(self, me: dict) -> List[str]:
        ids = {str(m.get("id") or "") for m in (me.get("board") or [])}
        return [a for a in AMPS if AMPS[a] & ids]

    def _target_ids(self, amps: Sequence[str]) -> set:
        t: set = set()
        for a in amps:
            if a in SYN:
                t |= SYN[a]
        if "Gatekeeper" in amps:
            t |= {cid for cid, c in catalog().items()
                  if str(c.get("kind")) != "minion" and c.get("implemented")}
        return t

    @staticmethod
    def _base_kind(a: int, me: dict) -> str:
        shop = me.get("shop") or []
        hand = me.get("hand") or []
        if A_BUY <= a < A_BUY + 8:
            i = a - A_BUY
            if i < len(shop):
                cid = str(shop[i].get("id") or "")
                if _is_amp(cid):
                    return "buy_amp"
                if _is_carrier(shop[i]):
                    return "buy_carrier"
                return "buy_other"
        if a == END_TURN:
            return "end"
        if A_PLAY_LO <= a < A_PLAY_HI:
            h = (a - A_PLAY_LO) // 8
            if h < len(hand):
                it = hand[h]
                return "play_spell" if str(it.get("type")) != "minion" else "play_minion"
        if 16 <= a < 23:
            return "sell"
        return "other"

    def act(self, v: dict, mask: np.ndarray) -> int:
        me = v.get("me") or {}
        base = int(super().act(v, mask))    # 基策略照常推进其内部计数
        if me.get("pending") or v.get("phase") != "recruit" or me.get("ended_turn"):
            return base
        amps = self._amps_on_board(me)
        if not amps:
            return base
        targets = self._target_ids(amps)
        if not targets:
            return base
        kind = self._base_kind(base, me)
        inj = self._inject(v, me, mask, amps, targets, kind, base)
        return int(inj) if inj is not None else base

    def _inject(self, v: dict, me: dict, mask: np.ndarray, amps: Sequence[str],
                targets: set, base_kind: str, base_a: int) -> Optional[int]:
        board = me.get("board") or []
        hand = me.get("hand") or []
        shop = me.get("shop") or []
        # 1) 手上已有配合随从 → 打出去（放大器在场时）
        for h, it in enumerate(hand[:10]):
            if str(it.get("type")) != "minion":
                continue
            cid = str(it.get("id") or "")
            if cid not in targets or _is_amp(cid):
                continue
            for pos in range(len(board) + 1):
                a = A_PLAY_LO + h * 8 + pos
                if a < A_PLAY_HI and bool(mask[a]):
                    self.played_syn += 1
                    return int(a)
        # 2) 商店有配合牌：只在基策略不是买核心时注入
        if base_kind in ("buy_amp", "buy_carrier", "play_spell"):
            return None
        best = None
        for i, it in enumerate(shop[:8]):
            cid = str(it.get("id") or "")
            if cid not in targets or _is_amp(cid):
                continue
            if not bool(mask[A_BUY + i]):
                continue
            score = _stats_of(it)
            if score < self.min_syn_stats:
                continue
            if best is None or score > best[0]:
                best = (score, i)
        if best is not None:
            self.bought_syn += 1
            return int(A_BUY + best[1])
        # 3) 基策略要卖的是「配合随从」→ 改卖没有配合文本的最弱随从
        if base_kind == "sell" and 16 <= base_a < 23:
            idx = base_a - 16
            if 0 <= idx < len(board):
                sold = str(board[idx].get("id") or "")
                if sold in ALL_SYN:
                    for j, m in enumerate(board):
                        cid = str(m.get("id") or "")
                        if cid in ALL_SYN or _is_amp(cid) or _is_carrier(m):
                            continue
                        if bool(mask[16 + j]):
                            return int(16 + j)
        return None


A_PLAY_LO = 46
A_PLAY_HI = 126


# ── 审计 ────────────────────────────────────────────────────────────────────
def run_arm(arm: str, cfg: SandboxConfig, games: int, seed0: int,
            *, synergy: bool, min_syn_stats: int = 0
            ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    agg = {a: {"triggers": 0, "dSigma": 0, "games_with": 0, "bought": 0}
           for a in AMPS}
    eps: List[Dict[str, Any]] = []
    for gi in range(games):
        seed = seed0 + gi
        env = EconomySandbox(cfg)
        obs = env.reset(seed)
        env.g.set_record_log(True)
        pol = (SynergyPolicy(seed=seed, min_syn_stats=int(min_syn_stats))
               if synergy else CompoundPolicy(seed=seed))
        prev = json.loads(env.g.view(0))
        prev_stats = dict(prev["me"].get("stats") or {})
        prev_log = len(env.g.log())
        last_turn = int(env.g.turn)
        turns_on = {a: 0 for a in AMPS}
        trig_game = {a: 0 for a in AMPS}
        while not env.done:
            v = json.loads(env.g.view(0))
            me = v.get("me") or {}
            board_ids = [str(m.get("id") or "") for m in (me.get("board") or [])]
            present = {a: bool(AMPS[a] & set(board_ids)) for a in AMPS}
            for a in AMPS:
                if present[a]:
                    turns_on[a] += 1
            sigma_pre = sum(_stats_of(m) for m in (me.get("board") or []))
            a = int(pol.act(v, obs.mask))
            obs, _r, done, _info = env.step(a)
            v2 = json.loads(env.g.view(0))
            me2 = v2.get("me") or {}
            st2 = dict(me2.get("stats") or {})
            sigma_post = sum(_stats_of(m) for m in (me2.get("board") or []))
            dsigma = sigma_post - sigma_pre
            for amp, key in TRIGGER_STAT.items():
                d = int(st2.get(key) or 0) - int(prev_stats.get(key) or 0)
                if d > 0 and present[amp]:
                    agg[amp]["triggers"] += d
                    agg[amp]["dSigma"] += dsigma
                    trig_game[amp] += d
            t2 = int(env.g.turn)
            if t2 != last_turn or env.done:
                logs = env.g.log()
                new_lines = logs[prev_log:]
                prev_log = len(logs)
                for ln in new_lines:
                    s = str(ln)
                    if " buys " in s:
                        for nm, amp in NAME_TO_AMP.items():
                            if (" " + nm + " ") in s:
                                agg[amp]["bought"] += 1
                last_turn = t2
            prev_stats = st2
        ep = env.episode_summary()
        s12 = int(ep.get("sigma_t12") or 0)
        s15 = int(ep.get("sigma_t15") or 0)
        rec = {"game": gi, "seed": seed, "sigma_t12": s12, "sigma_t15": s15,
               "r12_15": round(s15 / max(1, s12), 3),
               "gold_total": int(ep.get("gold_total_income") or 0),
               "amps_on_board": [a for a in AMPS if turns_on[a] > 0],
               "triggers": {a: trig_game[a] for a in AMPS},
               "turns_on": dict(turns_on)}
        eps.append(rec)
        for a in AMPS:
            if turns_on[a] > 0:
                agg[a]["games_with"] += 1
    per: Dict[str, Any] = {}
    for a in AMPS:
        g = max(1, agg[a]["games_with"])
        per[a] = {
            "bought_per_game": round(agg[a]["bought"] / games, 2),
            "games_with_amp": agg[a]["games_with"],
            "turns_on_board_mean": round(sum(e["turns_on"][a] for e in eps) / g, 2),
            "triggers_per_game": round(sum(e["triggers"][a] for e in eps) / games, 2),
            "triggers_per_game_when_present": round(
                sum(e["triggers"][a] for e in eps) / g, 2),
            "dSigma_per_trigger": round(agg[a]["dSigma"] / max(1, agg[a]["triggers"]), 3),
        }
    sig = [e["sigma_t15"] for e in eps]
    r = [e["r12_15"] for e in eps]
    with_amp = [e["sigma_t15"] for e in eps if e["amps_on_board"]]
    without = [e["sigma_t15"] for e in eps if not e["amps_on_board"]]
    # 边际价值：Σ ~ a + b×总触发（只在有放大器的局上拟合）
    xs = [sum(e["triggers"].values()) for e in eps if e["amps_on_board"]]
    ys = [e["sigma_t15"] for e in eps if e["amps_on_board"]]
    slope = 0.0
    if len(xs) >= 3 and np.std(xs) > 0:
        slope = float(np.polyfit(np.asarray(xs, float), np.asarray(ys, float), 1)[0])
    summary = {
        "arm": arm, "games": games, "seed0": seed0,
        "cfg": {"gold_mode": cfg.gold_mode, "gold_per_turn": cfg.gold_per_turn,
                "gold_cap": cfg.gold_cap, "action_cap": cfg.action_cap,
                "hand_slot_mode": cfg.hand_slot_mode},
        "sigma_t15_p50": float(np.percentile(sig, 50)) if sig else 0,
        "sigma_t15_mean": float(statistics.mean(sig)) if sig else 0,
        "r12_15_p50": float(np.percentile(r, 50)) if r else 0,
        "sigma_per_gold_p50": float(np.percentile(
            [e["sigma_t15"] / max(1, e["gold_total"]) for e in eps], 50)) if eps else 0,
        "trigger_games": len(with_amp),
        "sigma_t15_trigger_games_p50": float(np.percentile(with_amp, 50)) if with_amp else 0,
        "sigma_t15_no_amp_games_p50": float(np.percentile(without, 50)) if without else 0,
        "marginal_sigma_per_trigger": round(slope, 3),
        "amps": per,
    }
    return summary, eps


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="放大器配合包 base vs synergy 对照")
    ap.add_argument("--games", type=int, default=32)
    ap.add_argument("--seed0", type=int, default=880000)
    ap.add_argument("--gold-per-turn", type=int, default=15)
    ap.add_argument("--gold-mode", default="fixed", choices=["fixed", "add", "growth"])
    ap.add_argument("--gold-add", type=int, default=0)
    ap.add_argument("--gold-growth-rate", type=float, default=0.0)
    ap.add_argument("--gold-per-carrier", type=int, default=0)
    ap.add_argument("--gold-cap", type=int, default=99)
    ap.add_argument("--action-cap", type=int, default=40)
    ap.add_argument("--action-cap-per-gold", dest="action_cap_per_gold", type=int,
                    default=0)
    ap.add_argument("--tavern-buff-scale", dest="tavern_buff_scale", type=float,
                    default=1.0)
    ap.add_argument("--trinkets", type=int, default=1)
    ap.add_argument("--arms", default="base,synergy")
    ap.add_argument("--min-syn-stats", dest="min_syn_stats", type=int, default=0,
                    help="只买 atk+hp >= 该值的配合随从（防低身材战吼稀释战团；0=不限）")
    ap.add_argument("--json-out", default=os.path.join(ROOT, "runs", "sandbox_econ",
                                                       "amp_synergy.json"))
    args = ap.parse_args(argv)
    cfg = SandboxConfig(turns=15, gold_mode=args.gold_mode,
                        gold_per_turn=int(args.gold_per_turn),
                        gold_add=int(args.gold_add),
                        gold_growth_rate=float(args.gold_growth_rate),
                        gold_per_carrier=int(args.gold_per_carrier),
                        gold_cap=int(args.gold_cap),
                        action_cap=int(args.action_cap),
                        action_cap_per_gold=int(args.action_cap_per_gold),
                        tavern_buff_scale=float(args.tavern_buff_scale),
                        num_players=8,
                        trinkets=bool(args.trinkets), lobby_types=())
    out: Dict[str, Any] = {"config": {"games": args.games, "seed0": args.seed0,
                                      "gold_mode": args.gold_mode,
                                      "gold_per_turn": args.gold_per_turn,
                                      "gold_growth_rate": args.gold_growth_rate,
                                      "gold_per_carrier": args.gold_per_carrier,
                                      "gold_cap": args.gold_cap,
                                      "action_cap_per_gold": args.action_cap_per_gold,
                                      "tavern_buff_scale": args.tavern_buff_scale},
                           "synergy_sets": {a: len(s) for a, s in SYN.items()},
                           "arms": {}}
    eps_all: Dict[str, List[Dict[str, Any]]] = {}
    for name in [s.strip() for s in str(args.arms).split(",") if s.strip()]:
        summary, eps = run_arm(name, cfg, int(args.games), int(args.seed0),
                               synergy=(name != "base"),
                               min_syn_stats=int(args.min_syn_stats))
        out["arms"][name] = summary
        eps_all[name] = eps
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    out["episodes"] = eps_all
    os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"WROTE {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
