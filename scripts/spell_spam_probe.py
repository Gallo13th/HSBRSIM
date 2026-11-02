"""「金币 → buff 实例」转化探针（spell-spam / buy-sell churn）。

问题：3/4 金币花不掉，是「商店没东西可买」还是「策略买完就停」？
- 每回合末统计：金币结余、**可负担项数**（shop 随从+法术里 price ≤ gold 的数量）；
- `spell_spam`：优先买法术 → 立刻施放（优先对载体，pending 交给基策略）；
  没有法术可买就刷新找法术；把金币尽量转成施法实例；
- `spell_spam_churn`：在 spell-spam 基础上，没东西可买时「买随从 → 打出 → 卖掉」刷触发（APM 模拟）。

三组同 seed，fixed30 与 fixed20 各一次。报告：buff 实例/局（施法+战吼+亡语+EOT）、
花费率、Σ15 p50、Σ/N、r12_15、**每金币→Σ**。

判据：花费率 ≥70% 且 Σ/金 ≥7（现 4.04，真实 9.9）。

用法：
    python scripts/spell_spam_probe.py --games 24 --workers 6 --gold-per-turn 20,30
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
    A_BUY, A_REFRESH, END_TURN, EconomySandbox, SandboxConfig)
from compound_script import AMP_BY_ID, CompoundPolicy, _is_carrier  # noqa: E402

A_PLAY_LO, A_PLAY_HI = 46, 126
A_SELL = 16

#: 已知「法术生成」卡（COMPOUND_INCOME §1.3 的 25 张 + 饰品），文本匹配之外的兜底
SPELL_GEN_KNOWN = {
    "BG36_MagicItem_852", "BG30_MagicItem_420", "BG30_MagicItem_420t",
    "BG35_MagicItem_851", "BG35_MagicItem_750", "BG36_MagicItem_372",
    "BG36_764", "BG36_764_G", "BG35_123", "BG35_123_G", "BG33_891", "BG33_891_G",
    "BG32_821", "BG32_821_G", "BG32_873", "BG32_873_G",
    "BG28_509", "BGS_Treasures_030",
}


def _spell_gen_ids() -> set:
    """法术生成卡集合：已知 id + 严格文本匹配（tavern spell + get/discover/add/teach）。

    注意排除「cast a Tavern spell」类（那是**消耗**法术的牌，如 Living Azerite），
    只保留**生成**法术的牌，避免把普通 buff 卡当 spell_gen 买。
    """
    import hsbg_engine as E
    cat = json.loads(E.catalog_json())
    out = set(SPELL_GEN_KNOWN)
    for e in cat:
        cid = str(e.get("id") or "")
        if not e.get("implemented") or not e.get("in_pool"):
            continue
        text = str(e.get("text") or "").lower()
        if "tavern spell" not in text:
            continue
        if any(w in text for w in ("get a", "get 2", "get two", "discover", "add a",
                                   "add 2", "teach it")):
            out.add(cid)
    return out


SPELL_GEN = _spell_gen_ids()


def _price(it: dict) -> int:
    for k in ("cost", "price"):
        try:
            return int(it.get(k))
        except (TypeError, ValueError):
            continue
    return 99


def _gold(me: dict) -> int:
    try:
        return int(me.get("gold") or 0)
    except (TypeError, ValueError):
        return 0


class SpellSpamPolicy(CompoundPolicy):
    """法术优先 + （可选）买-打-卖 churn。"""

    def __init__(self, *, churn: bool = False, gen: bool = False,
                 max_spells_per_turn: int = 24, **kw: Any) -> None:
        super().__init__(**kw)
        self.churn = bool(churn)
        self.gen = bool(gen)
        self.max_spells_per_turn = int(max_spells_per_turn)
        self._spells_turn = 0
        self._last_turn = -1
        self._churn_id = ""
        self.spell_buys = 0
        self.spell_casts = 0
        self.gen_buys = 0
        self.churn_buys = 0
        self.churn_sells = 0

    def act(self, v: dict, mask: np.ndarray) -> int:
        me = v.get("me") or {}
        base = int(super().act(v, mask))
        if me.get("pending") or v.get("phase") != "recruit" or me.get("ended_turn"):
            return base
        t = int(v.get("turn") or 0)
        if t != self._last_turn:
            self._last_turn = t
            self._spells_turn = 0
        hand = me.get("hand") or []
        shop = me.get("shop") or []
        board = me.get("board") or []
        # 1) 手牌法术 → 立刻打（pos=0；目标走 pending，由基策略选）
        for h, it in enumerate(hand[:10]):
            if str(it.get("type")) == "minion":
                continue
            a = A_PLAY_LO + h * 8
            if a < A_PLAY_HI and bool(mask[a]):
                self.spell_casts += 1
                self._spells_turn += 1
                return int(a)
        # 2) spell_gen 优先：买法术生成卡（Willbreaker/Book/Gearfin/Water Wheel…）
        if self.gen:
            for i, it in enumerate(shop[:8]):
                if str(it.get("id") or "") in SPELL_GEN and bool(mask[A_BUY + i]):
                    self.gen_buys += 1
                    return int(A_BUY + i)
        # 3) 买法术（有法术可买且手牌/金币允许）
        for i, it in enumerate(shop[:8]):
            if str(it.get("type")) == "minion":
                continue
            if bool(mask[A_BUY + i]):
                self.spell_buys += 1
                return int(A_BUY + i)
        # 3) churn：买随从 → 打出（触发战吼）→ 卖掉（1 次触发 = 3 动作 / ~2 金）
        if self.churn:
            if self._churn_id:
                # 先打出（在手牌里）
                for h, it in enumerate(hand[:10]):
                    if str(it.get("id") or "") == self._churn_id:
                        for pos in range(len(board) + 1):
                            a = A_PLAY_LO + h * 8 + pos
                            if a < A_PLAY_HI and bool(mask[a]):
                                return int(a)
                # 已在棋盘 → 卖掉
                for j, m in enumerate(board):
                    if str(m.get("id") or "") == self._churn_id \
                            and bool(mask[A_SELL + j]):
                        self._churn_id = ""
                        self.churn_sells += 1
                        return int(A_SELL + j)
                self._churn_id = ""
            cand = [i for i, it in enumerate(shop[:8])
                    if str(it.get("type")) == "minion" and bool(mask[A_BUY + i])]
            if cand:
                i = min(cand, key=lambda k: _price(shop[k]))
                self._churn_id = str(shop[i].get("id") or "")
                self.churn_buys += 1
                return int(A_BUY + i)
        # 5) 刷新：gen 模式在「有生成源但商店没法术」时多 roll 找法术（上限 6）；
        #    其它情况只在**完全没东西可买**时刷新
        limit_refresh = 6 if self.gen else int(self.max_refresh)
        if _gold(me) >= 1 and bool(mask[A_REFRESH]) \
                and int(getattr(self, "refreshes", 0)) < limit_refresh:
            has_gen = any(str(m.get("id") or "") in SPELL_GEN
                          for m in (me.get("board") or []))
            has_spell_shop = any(str(it.get("type")) != "minion" for it in shop[:8])
            if self.gen:
                ok = has_gen and not has_spell_shop
            else:
                ok = not bool(mask[A_BUY:A_BUY + 8].any())
            if ok:
                self.refreshes = int(getattr(self, "refreshes", 0)) + 1
                return int(A_REFRESH)
        return base


BUFF_KEYS = {"spells": "spells_cast", "battlecries": "battlecries_triggered",
             "deathrattles": "deathrattles_triggered"}


def _run_arm(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    arm = payload["arm"]
    cfg = payload["cfg"]
    games = int(payload["games"])
    seed0 = int(payload["seed0"])
    out: List[Dict[str, Any]] = []
    for gi in range(games):
        seed = seed0 + gi
        env = EconomySandbox(cfg)
        obs = env.reset(seed)
        env.g.set_record_log(True)
        if arm == "base":
            pol = CompoundPolicy(seed=seed)
        else:
            pol = SpellSpamPolicy(seed=seed, churn=arm.endswith("churn"),
                                  gen=arm.endswith("gen"))
        prev = json.loads(env.g.view(0))
        prev_stats = dict(prev["me"].get("stats") or {})
        prev_log = len(env.g.log())
        last_turn = int(env.g.turn)
        eot = 0
        end_turns: List[Dict[str, Any]] = []
        generated_spells = 0
        while not env.done:
            v = json.loads(env.g.view(0))
            me = v.get("me") or {}
            shop = me.get("shop") or []
            gold_pre = _gold(me)
            buyable = sum(1 for it in shop[:8] if _price(it) <= gold_pre)
            spells_before = sum(1 for it in (me.get("hand") or [])
                                if str(it.get("type")) != "minion")
            a = int(pol.act(v, obs.mask))
            is_end = (a == END_TURN and bool(obs.mask[END_TURN]))
            obs, _r, done, _info = env.step(a)
            v2 = json.loads(env.g.view(0))
            me2 = v2.get("me") or {}
            spells_after = sum(1 for it in (me2.get("hand") or [])
                               if str(it.get("type")) != "minion")
            # 法术来源：非「买法术」动作导致的手牌法术增加 = 生成（含饰品）
            if A_BUY <= a < A_BUY + 8:
                bought_is_spell = False
                i = a - A_BUY
                if i < len(shop):
                    bought_is_spell = str(shop[i].get("type")) != "minion"
            else:
                bought_is_spell = False
            if not bought_is_spell and spells_after > spells_before:
                generated_spells += spells_after - spells_before
            st2 = dict((me2.get("stats") or {}))
            t2 = int(env.g.turn)
            if t2 != last_turn or done:
                if is_end:
                    end_turns.append({"turn": int(v.get("turn") or 0),
                                      "gold_end": gold_pre, "buyable_end": buyable})
                logs = env.g.log()
                new = logs[prev_log:]
                prev_log = len(logs)
                eot += sum(1 for ln in new if "end of turn:" in str(ln))
                last_turn = t2
            prev_stats = st2
        ep = env.episode_summary()
        p = json.loads(env.g.player_json(0))
        st = p.get("stats") or {}
        s12 = int(ep.get("sigma_t12") or 0)
        s15 = int(ep.get("sigma_t15") or 0)
        board = p.get("board") or []
        income = int(ep.get("gold_total_income") or 0)
        spent = int(st.get("gold_spent_total") or 0)
        buffs = {k: int(st.get(v) or 0) for k, v in BUFF_KEYS.items()}
        buffs["eot"] = int(eot)
        out.append({
            "seed": seed, "sigma_t12": s12, "sigma_t15": s15,
            "n15": len(board), "sigma_per_n": s15 / len(board) if board else 0.0,
            "r12_15": s15 / max(1, s12),
            "gold_total_income": income, "gold_spent_total": spent,
            "spend_rate": spent / income if income else 0.0,
            "sigma_per_gold": s15 / income if income else 0.0,
            "buffs": buffs,
            "buff_instances": int(sum(buffs.values())),
            "end_turns": end_turns,
            "spell_buys": int(getattr(pol, "spell_buys", 0)),
            "spell_casts": int(getattr(pol, "spell_casts", 0)),
            "gen_buys": int(getattr(pol, "gen_buys", 0)),
            "generated_spells": int(generated_spells),
            "churn_buys": int(getattr(pol, "churn_buys", 0)),
            "churn_sells": int(getattr(pol, "churn_sells", 0)),
        })
    return out


def _pct(v: Sequence[float], q: float) -> float:
    return float(np.percentile(np.asarray(v, dtype=np.float64), q)) if v else 0.0


def _summarize(eps: List[Dict[str, Any]]) -> Dict[str, Any]:
    def col(k: str) -> List[float]:
        return [float(e.get(k) or 0) for e in eps]

    turn_rows = [r for e in eps for r in e.get("end_turns", [])]
    buyable = [r["buyable_end"] for r in turn_rows]
    gold_end = [r["gold_end"] for r in turn_rows]
    idle = [1.0 for r in turn_rows if r["gold_end"] >= 1 and r["buyable_end"] >= 3]
    return {
        "games": len(eps),
        "sigma_t15_p50": _pct(col("sigma_t15"), 50),
        "sigma_t15_p90": _pct(col("sigma_t15"), 90),
        "N15_p50": _pct(col("n15"), 50),
        "sigma_per_N_p50": _pct(col("sigma_per_n"), 50),
        "r12_15_p50": _pct(col("r12_15"), 50),
        "spend_rate_mean": round(float(statistics.mean(col("spend_rate"))), 3),
        "sigma_per_gold_p50": _pct(col("sigma_per_gold"), 50),
        "buff_instances_mean": round(float(statistics.mean(col("buff_instances"))), 1),
        "spells_mean": round(float(statistics.mean([e["buffs"]["spells"] for e in eps])), 1),
        "battlecries_mean": round(float(statistics.mean([e["buffs"]["battlecries"] for e in eps])), 1),
        "deathrattles_mean": round(float(statistics.mean([e["buffs"]["deathrattles"] for e in eps])), 2),
        "eot_mean": round(float(statistics.mean([e["buffs"]["eot"] for e in eps])), 2),
        "gold_end_p50": _pct(gold_end, 50),
        "buyable_end_p50": _pct(buyable, 50),
        "turns_measured": len(turn_rows),
        "idle_turns_frac": round(len(idle) / max(1, len(turn_rows)), 3),
        "spell_buys_mean": round(float(statistics.mean(col("spell_buys"))), 1),
        "spell_casts_mean": round(float(statistics.mean(col("spell_casts"))), 1),
        "gen_buys_mean": round(float(statistics.mean(col("gen_buys"))), 2),
        "generated_spells_mean": round(float(statistics.mean(col("generated_spells"))), 1),
        "shop_spell_buys_mean": round(float(statistics.mean(col("spell_buys"))), 1),
        "churn_buys_mean": round(float(statistics.mean(col("churn_buys"))), 1),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="gold -> buff instances (spell spam)")
    ap.add_argument("--games", type=int, default=24)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--seed0", type=int, default=880000)
    ap.add_argument("--gold-per-turn", dest="gpt", default="20,30")
    ap.add_argument("--arms", default="base,spell_spam,spell_spam_gen")
    ap.add_argument("--json-out", default=os.path.join(ROOT, "runs", "sandbox_econ",
                                                       "spell_spam.json"))
    args = ap.parse_args(argv)
    import multiprocessing as mp

    arms = [s.strip() for s in str(args.arms).split(",") if s.strip()]
    gpts = [int(x) for x in str(args.gpt).split(",") if x.strip()]
    payloads = []
    for gpt in gpts:
        cfg = SandboxConfig(turns=15, gold_mode="fixed", gold_per_turn=gpt,
                            action_cap=40, num_players=8, trinkets=True,
                            gold_cap=99, lobby_types=())
        for arm in arms:
            payloads.append({"arm": arm, "cfg": cfg, "games": int(args.games),
                             "seed0": int(args.seed0), "gpt": gpt})
    with mp.get_context("fork").Pool(max(1, int(args.workers))) as pool:
        results = pool.map(_run_arm, payloads)
    cells: Dict[str, Any] = {}
    eps_all: Dict[str, Any] = {}
    for p, eps in zip(payloads, results):
        key = f"gpt{p['gpt']}_{p['arm']}"
        c = _summarize(eps)
        c["pass"] = bool(c["spend_rate_mean"] >= 0.70 and c["sigma_per_gold_p50"] >= 7.0)
        cells[key] = c
        eps_all[key] = eps
    out = {"config": {"games": int(args.games), "seed0": int(args.seed0),
                      "gold_per_turn": gpts,
                      "criteria": {"spend_rate": 0.70, "sigma_per_gold": 7.0,
                                   "current_sigma_per_gold": 4.04, "real": 9.9},
                      "teacher": "CompoundPolicy / SpellSpamPolicy"},
           "cells": cells, "episodes": eps_all}
    out["verdict"] = {"pass_cells": [k for k, c in cells.items() if c["pass"]],
                      "note": "pass = spend_rate>=0.70 AND sigma_per_gold>=7"}
    os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for k, c in cells.items():
        print(f"{k:28s} S15p50={c['sigma_t15_p50']:7.1f} S/gold={c['sigma_per_gold_p50']:5.2f} "
              f"spend={c['spend_rate_mean']:.2f} buffs={c['buff_instances_mean']:6.1f} "
              f"(spell {c['spells_mean']:.0f}/bc {c['battlecries_mean']:.1f}) "
              f"gold_end={c['gold_end_p50']:.0f} buyable={c['buyable_end_p50']:.0f} "
              f"idle={c['idle_turns_frac']:.2f} r12={c['r12_15_p50']:.2f} pass={c['pass']}",
              flush=True)
    print(f"WROTE {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
