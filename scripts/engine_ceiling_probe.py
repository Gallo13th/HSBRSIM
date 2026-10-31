#!/usr/bin/env python3
"""环境强度上限离线探测（不训练、不占 GPU）。

回答一个问题：**在 hsbg_engine（37.0.0.255790）里，一条策略最高能把战团
Σ(atk+hp) 打到多少？** 结果与真实 10k+ p50（t12 4458 / t13 9446 / t14 20889 /
t15 26194，来自 `data/real_library/library_real_quasi_full.jsonl`）对比。

四种模式（都只驱动 seat 0，其余 7 席用引擎自带 bot，不做人类战团注入）：

  greedy  规则化“强度最大化”脚本策略（见 `ScriptPolicy`）：按 curve 升级、买当前
          tier 最大身材、对子（三连）优先、不做无意义换位。
  bot     引擎自带启发式 bot 基线；`--cheat gold|tier6` 可放开经济/等级。
  spell   法术缩放流（Devilish Distractor / “cast a spell on this” 引擎）——
          用于测「机制上限」：买光酒馆法术、全部施放在缩放随从上、再买被永久
          buff 的酒馆随从。
  beam    浅层 beam search（宽度 `--width`，深度 `--depth`）在指定 turn 上搜
          单回合最大身材增益，然后继续用 greedy 推进到 t12/t13。

口径与真实库一致：在 **recruit 阶段结束** 时记录 seat 0 的战团 Σ(atk+hp)。

用法：
  python scripts/engine_ceiling_probe.py greedy --games 200 --workers 32
  python scripts/engine_ceiling_probe.py bot --games 200
  python scripts/engine_ceiling_probe.py bot --games 100 --cheat tier6
  python scripts/engine_ceiling_probe.py spell --games 100 --cheat tier6
  python scripts/engine_ceiling_probe.py beam --games 4 --turns 9,11 --width 12 --depth 3
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import statistics
import sys
import time
from collections import Counter, defaultdict

import hsbg_engine as E

# --- 动作布局（与 rust/crates/hsbg-engine/src/actions.rs 一致） -----------------
A_END = 0
A_REFRESH = 1
A_FREEZE = 2
A_UPGRADE = 3
A_HERO_POWER = 4
A_DARK_GIFT = 6
A_CANCEL = 7
A_BUY = 8
A_SELL = 16
A_ACTIVATE = 23
A_CHOOSE = 30
A_PLAY = 46
A_MAGNETIZE = 126
A_MOVE = 196
N_CHOICE = 16
N_POS = 8
N_BOARD = 7

REAL_P50 = {9: 547, 10: 1132, 11: 2211, 12: 4458, 13: 9446, 14: 20889, 15: 26194}

_CATALOG: dict[str, dict] | None = None


def catalog() -> dict[str, dict]:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = {c["id"]: c for c in json.loads(E.catalog_json())}
    return _CATALOG


def card_of(cid: str) -> dict:
    return catalog().get(cid) or {}


def bsum(board) -> int:
    return sum(int(m["atk"]) + int(m["hp"]) for m in board)


def minion_stats(m: dict) -> int:
    return int(m["atk"]) + int(m["hp"])


def is_spell_synergy(m: dict) -> bool:
    """“whenever you cast a spell on this” 类缩放随从。"""
    t = (card_of(m.get("id", "")).get("text") or "").lower()
    return "cast a spell on this" in t


def price_of(item: dict) -> int:
    for k in ("price", "cost"):
        v = item.get(k)
        if isinstance(v, int) and v >= 0:
            return v
    return 3


class ScriptPolicy:
    """规则化“强度最大化”策略；`mode` 决定买什么、法术怎么用。

    mode='greedy': 只按身材（atk+hp）+ 三连（对子）价值买随从，法术顺手施放。
    mode='spell' : 买光酒馆法术并施放在“cast a spell on this”随从上，再买被永久
                   buff 过的酒馆随从（机制上限探测）。
    curve='aggr' | 'mid' | 'late': 升级（tier up）激进度。
    """

    def __init__(self, mode: str = "greedy", curve: str = "mid",
                 lobby: str | None = None, cheat: str | None = None,
                 cheat_gold: int = 99):
        self.mode = mode
        self.curve = curve
        self.lobby = lobby
        self.cheat = cheat
        self.cheat_gold = int(cheat_gold)
        self.gold_given = 0
        self.actions = 0
        self.refreshes = 0
        self.casts = 0

    # -- 每次决策：pending 优先 ----------------------------------------------------
    def act(self, g, seat: int) -> int:
        v = json.loads(g.view(seat))
        me = v["me"]
        mask = v["mask"]
        pend = me.get("pending")
        if pend:
            return self._pending(v, seat, pend)
        if v["phase"] != "recruit" or me.get("ended_turn"):
            return A_END
        self.actions += 1
        if self.actions > 120:
            return A_END
        return self._recruit(v, me, mask)

    # -- 菜单/发现：确定性、偏强度 --------------------------------------------------
    def _pending(self, v, seat: int, pend: dict) -> int:
        mask = v["mask"]
        legal = [i for i in range(N_CHOICE) if mask[A_CHOOSE + i]]
        if not legal:
            return A_CHOOSE
        kind = pend.get("kind")
        opts = pend.get("options") or []
        me = v["me"]
        if kind == "target":
            # 优先选“施法缩放”随从，其次最强随从
            board = me.get("board") or []
            want = None
            for m in board:
                if is_spell_synergy(m):
                    want = m["eid"]
                    break
            if want is not None:
                for i in legal:
                    if i < len(opts) and opts[i] == want:
                        return A_CHOOSE + i
            ranked = sorted(range(len(board)), key=lambda i: -minion_stats(board[i]))
            if ranked:
                eid = board[ranked[0]]["eid"]
                for i in legal:
                    if i < len(opts) and opts[i] == eid:
                        return A_CHOOSE + i
            return A_CHOOSE + legal[0]
        if kind == "hero":
            best = None
            for i in legal:
                if i >= len(opts):
                    continue
                o = opts[i]
                hp = o.get("hero_power") or {}
                txt = (hp.get("text") or "").lower()
                sc = (3 if "+" in txt else 0) + (1 if "stats" in txt else 0)
                sc -= int(hp.get("cost") or 0)
                sc = (sc, int(o.get("armor") or 0))
                if best is None or sc > best[0]:
                    best = (sc, i)
            return A_CHOOSE + (best[1] if best else legal[0])
        if kind in ("discover", "choose_one"):
            best = None
            for i in legal:
                if i >= len(opts):
                    continue
                o = opts[i]
                sc = minion_stats(o) if isinstance(o, dict) and o.get("kind") == "minion" else 0
                if best is None or sc > best[0]:
                    best = (sc, i)
            return A_CHOOSE + (best[1] if best else legal[0])
        if kind == "trinket":
            # 取第一个能负担的（通常越便宜越早吃到收益）
            for i in legal:
                if i < len(opts) and int(opts[i].get("cost") or 0) <= int(me.get("gold") or 0):
                    return A_CHOOSE + i
            return A_CHOOSE + legal[0]
        return A_CHOOSE + legal[0]

    # -- 招募阶段 ------------------------------------------------------------------
    def _recruit(self, v, me: dict, mask) -> int:
        gold = int(me.get("gold") or 0)
        board = me.get("board") or []
        hand = me.get("hand") or []
        shop = me.get("shop") or []
        tier = int(me.get("tier") or 1)
        spell_mode = self.mode == "spell"

        def legal(a: int) -> bool:
            return 0 <= a < 245 and bool(mask[a])

        # 1) 手牌法术：全部施放（目标在 pending 阶段选：缩放随从优先，其次最强）
        for h, it in enumerate(hand[:10]):
            if it.get("type") != "minion" and legal(A_PLAY + h * N_POS):
                self.casts += 1
                return A_PLAY + h * N_POS

        buys = [i for i in range(8) if legal(A_BUY + i) and i < len(shop)]

        # 2) 买法术：spell 模式里法术就是缩放引擎（酒馆永久 buff / 消耗），优先买
        spells = [i for i in buys if shop[i].get("type") == "spell"]
        if spells:
            i = min(spells, key=lambda k: price_of(shop[k]))
            if gold >= price_of(shop[i]):
                return A_BUY + i

        worst_i = min(range(len(board)), key=lambda k: minion_stats(board[k])) if board else None
        worst_s = minion_stats(board[worst_i]) if worst_i is not None else -1

        # 3) 手牌随从：只换“明显更强”的（严禁把大身材换掉 —— churn 是身材杀手）
        best_hand = None
        for h, it in enumerate(hand[:10]):
            if it.get("type") == "minion":
                s = minion_stats(it)
                if best_hand is None or s > best_hand[0]:
                    best_hand = (s, h)
        if best_hand is not None:
            s, h = best_hand
            if len(board) < N_BOARD:
                pos = len(board)
                if legal(A_PLAY + h * N_POS + pos):
                    return A_PLAY + h * N_POS + pos
            elif worst_i is not None and s > worst_s + max(5, worst_s // 5):
                if legal(A_SELL + worst_i):
                    return A_SELL + worst_i

        # 4) 三连：买会凑成三个的同名随从
        owned = Counter(m["id"] for m in board)
        owned.update(it["id"] for it in hand if it.get("type") == "minion")
        triples = [i for i in buys if shop[i].get("type") == "minion"
                   and owned.get(shop[i]["id"], 0) >= 2]
        if triples:
            i = max(triples, key=lambda k: minion_stats(shop[k]))
            if gold >= price_of(shop[i]):
                return A_BUY + i

        # 5) 买随从：只换明显更强的
        cands = [i for i in buys if shop[i].get("type") == "minion"]
        if cands:
            i = max(cands, key=lambda k: minion_stats(shop[k]) + int(shop[k].get("tier") or 0))
            s = shop[i]
            if gold >= price_of(s):
                if len(board) < N_BOARD:
                    return A_BUY + i
                if worst_i is not None and minion_stats(s) > worst_s + max(5, worst_s // 5):
                    if legal(A_SELL + worst_i):
                        return A_SELL + worst_i

        # 6) 升级：curve 规则（“留 3 金升级”）
        price = int(me.get("upgrade_price") or 99)
        if tier < 6 and legal(A_UPGRADE):
            ok = False
            if self.curve == "aggr":
                ok = gold >= price
            elif self.curve == "mid":
                ok = gold >= price and (price <= 3 or gold - price >= 3 or tier * 2 < v["turn"])
            else:  # late
                ok = gold >= price and (price <= 3 or gold >= price + 6)
            if ok:
                return A_UPGRADE

        # 7) 刷新：spell 模式更积极（每次刷新多一张酒馆法术 = 一次缩放）
        refresh_price = int(me.get("refresh_price") or 1)
        cap = 40 if spell_mode else 15
        need = 2 if spell_mode else 3
        if legal(A_REFRESH) and gold >= refresh_price + need and self.refreshes < cap:
            self.refreshes += 1
            return A_REFRESH

        # 8) 英雄技能（有就用，通常是正收益）
        for slot in range(2):
            if legal(A_HERO_POWER + slot) and gold >= 1:
                return A_HERO_POWER + slot

        return A_END


# ---------------------------------------------------------------------------------
# 驱动一局
# ---------------------------------------------------------------------------------
def drive(seed: int, policy: ScriptPolicy, max_turn: int = 20,
          inject_cheat: bool = True) -> dict:
    """跑一局：seat 0 用 policy，其余 7 席引擎 bot。返回每 turn 的 seat0 战团数值。"""
    cfg = None
    if policy.lobby:
        cfg = json.dumps({"lobby_races": len(policy.lobby.split(",")),
                          "lobby_types": policy.lobby.split(",")})
    g = E.Game(seed, cfg)
    out: dict[int, int] = {}
    while not g.is_over() and g.turn <= max_turn:
        t = g.turn
        policy.actions = 0
        policy.refreshes = 0
        policy.casts = 0
        if policy.cheat and t >= 1:
            cmd = {"cmd": "set_player", "p": 0, "gold": int(policy.cheat_gold)}
            if policy.cheat == "tier6":
                cmd.update({"tier": 6, "upgrade_cost": 0})
            elif policy.cheat == "tier5":
                cmd.update({"tier": 5})
            g.debug(json.dumps(cmd))
        for p in range(8):
            while g.needs_action(p) and g.turn == t:
                if p == 0:
                    a = policy.act(g, 0)
                    try:
                        g.step(0, a)
                    except Exception:
                        # 兜底：让引擎 bot 收尾，避免死锁
                        g.bot_play(0)
                        break
                else:
                    g.bot_play(p)
            if g.turn != t:
                break
            if p == 0:
                v = json.loads(g.view(0))
                out[t] = bsum(v["me"]["board"])
        if g.turn == t:  # 没有任何推进：结束
            break
    return out


def drive_bot(seed: int, cheat: str | None, lobby: str | None = None,
              max_turn: int = 20) -> dict:
    """基线：seat 0 也交给引擎 bot；可放开经济/等级。"""
    cfg = None
    if lobby:
        cfg = json.dumps({"lobby_races": len(lobby.split(",")),
                          "lobby_types": lobby.split(",")})
    g = E.Game(seed, cfg)
    out: dict[int, int] = {}
    while not g.is_over() and g.turn <= max_turn:
        t = g.turn
        if cheat and t >= 1:
            cmd = {"cmd": "set_player", "p": 0, "gold": int(policy.cheat_gold)}
            if cheat == "tier6":
                cmd.update({"tier": 6, "upgrade_cost": 0})
            g.debug(json.dumps(cmd))
        for p in range(8):
            while g.needs_action(p) and g.turn == t:
                g.bot_play(p)
            if g.turn != t:
                break
            if p == 0:
                v = json.loads(g.view(0))
                out[t] = bsum(v["me"]["board"])
        if g.turn == t:
            break
    return out


# ---------------------------------------------------------------------------------
# 浅层 beam search（单回合最大身材增益）
# ---------------------------------------------------------------------------------
def _cand_actions(v) -> list[int]:
    """单步候选：买/卖/升级/刷新/结束（不含换位）。"""
    mask = v["mask"]
    out = []
    for i in range(8):
        if mask[A_BUY + i]:
            out.append(A_BUY + i)
    for i in range(N_BOARD):
        if mask[A_SELL + i]:
            out.append(A_SELL + i)
    if mask[A_UPGRADE]:
        out.append(A_UPGRADE)
    if mask[A_REFRESH]:
        out.append(A_REFRESH)
    out.append(A_END)
    return out


def _complete_bot(g, seat: int = 0) -> int:
    """叶节点用引擎 bot 收尾本回合（不依赖脚本策略强弱）。"""
    g.bot_play(seat)
    return bsum(json.loads(g.view(seat))["me"]["board"])


def _complete(g, policy: ScriptPolicy, seat: int = 0, guard: int = 80) -> int:
    """用 policy 把本回合剩余动作走完（不结束回合），返回战团 Σ。"""
    for _ in range(guard):
        v = json.loads(g.view(seat))
        me = v["me"]
        if me.get("ended_turn") or v["phase"] != "recruit":
            break
        a = policy.act(g, seat)
        if a == A_END:
            break
        try:
            g.step(seat, a)
        except Exception:
            break
    return bsum(json.loads(g.view(seat))["me"]["board"])


def beam_turn(g, policy: ScriptPolicy, width: int = 12, depth: int = 3,
              seat: int = 0, completion: str = "script") -> dict:
    """从当前 mid-turn 状态出发，beam 搜 depth 步；叶节点用 policy 补完并评身材。"""
    start = bsum(json.loads(g.view(seat))["me"]["board"])
    beam = [(start, g.copy(), [])]
    for d in range(depth):
        cand = []
        for sc, g2, seq in beam:
            v = json.loads(g2.view(seat))
            for a in _cand_actions(v):
                g3 = g2.copy()
                try:
                    g3.step(seat, a)
                except Exception:
                    continue
                score = (_complete_bot(g3, seat) if completion == "bot"
                         else _complete(g3, policy, seat))
                cand.append((score, g3, seq + [a]))
        if not cand:
            break
        cand.sort(key=lambda x: -x[0])
        beam = cand[:width]
    best = beam[0]
    return {"gain": best[0] - start, "end": best[0], "start": start,
            "seq": [E.action_name(a) for a in best[2]], "game": best[1]}


def _beam_job(args):
    seed, turn, width, depth, curve, completion = args
    pol = ScriptPolicy(mode="greedy", curve=curve)
    g = E.Game(seed)
    # 用 greedy 推进到 turn
    while not g.is_over() and g.turn < turn:
        t = g.turn
        for p in range(8):
            while g.needs_action(p) and g.turn == t:
                if p == 0:
                    try:
                        g.step(0, pol.act(g, 0))
                    except Exception:
                        g.bot_play(0)
                        break
                else:
                    g.bot_play(p)
            if g.turn != t:
                break
        if g.turn == t:
            break
    if g.turn != turn:
        return None
    res = beam_turn(g, pol, width=width, depth=depth, completion=completion)
    # 继续 greedy 推进到 t+4，报告后续曲线
    g2 = res.pop("game")
    after = {}
    while not g2.is_over() and g2.turn <= turn + 4:
        t = g2.turn
        for p in range(8):
            while g2.needs_action(p) and g2.turn == t:
                if p == 0:
                    try:
                        g2.step(0, pol.act(g2, 0))
                    except Exception:
                        g2.bot_play(0)
                        break
                else:
                    g2.bot_play(p)
            if g2.turn != t:
                break
            if p == 0:
                after[t] = bsum(json.loads(g2.view(0))["me"]["board"])
        if g2.turn == t:
            break
    res["after"] = after
    res["seed"] = seed
    res["turn"] = turn
    return res


# ---------------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------------
def pct(vals, p):
    if not vals:
        return 0
    s = sorted(vals)
    return s[min(len(s) - 1, int(p * len(s)))]


def summarize(rows: dict[int, list[int]], label: str) -> dict:
    out = {"label": label, "turns": {}}
    print(f"\n== {label}")
    print(f"{'turn':>4} {'n':>5} {'p50':>7} {'p90':>8} {'max':>8} {'real_p50':>9} {'ceil/real':>9}")
    for t in sorted(rows):
        v = rows[t]
        p50, p90, mx = pct(v, 0.5), pct(v, 0.9), max(v)
        real = REAL_P50.get(t)
        ratio = f"{p90 / real:9.3f}" if real else " " * 9
        print(f"{t:4d} {len(v):5d} {p50:7d} {p90:8d} {mx:8d} {real or 0:9d} {ratio}")
        out["turns"][t] = {"n": len(v), "p50": p50, "p90": p90, "max": mx,
                           "mean": round(statistics.mean(v), 1),
                           "real_p50": real,
                           "p50_over_real": round(p50 / real, 4) if real else None,
                           "p90_over_real": round(p90 / real, 4) if real else None,
                           "max_over_real": round(mx / real, 4) if real else None}
    return out


def _job(args):
    seed, cfg = args
    mode, curve, lobby, cheat, cheat_gold = cfg
    if mode == "bot":
        return drive_bot(seed, cheat, lobby)
    pol = ScriptPolicy(mode=mode, curve=curve, lobby=lobby, cheat=cheat,
                       cheat_gold=cheat_gold)
    return drive(seed, pol)


def run_parallel(mode: str, games: int, workers: int, curve: str,
                 lobby: str | None, cheat: str | None, seed0: int,
                 cheat_gold: int = 99) -> dict[int, list[int]]:
    jobs = [(seed0 + i, (mode, curve, lobby, cheat, int(cheat_gold)))
            for i in range(games)]
    rows: dict[int, list[int]] = defaultdict(list)
    if workers <= 1:
        for j in jobs:
            for t, s in _job(j).items():
                if t >= 1:
                    rows[t].append(s)
    else:
        with mp.Pool(workers) as pool:
            for res in pool.imap_unordered(_job, jobs, chunksize=4):
                for t, s in res.items():
                    if t >= 1:
                        rows[t].append(s)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["greedy", "bot", "spell", "beam"])
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--workers", type=int, default=min(32, os.cpu_count() or 1))
    ap.add_argument("--curve", choices=["aggr", "mid", "late"], default="mid")
    ap.add_argument("--lobby", default=None, help="强制类型（逗号分隔，如 DEMON,BEAST）")
    ap.add_argument("--cheat", choices=["gold", "tier5", "tier6"], default=None)
    ap.add_argument("--cheat-gold", type=int, default=99,
                    help="cheat 模式每回合设置的金币（默认 99=∞；用于测不同金币课程上限）")
    ap.add_argument("--seed0", type=int, default=90000)
    ap.add_argument("--turns", default="9,11", help="beam 的 turn 列表")
    ap.add_argument("--width", type=int, default=12)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--completion", choices=["script", "bot"], default="script",
                    help="beam 叶节点补完方式")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    t0 = time.time()
    label = f"{args.mode}"
    if args.mode != "beam":
        if args.curve != "mid":
            label += f"/curve={args.curve}"
        if args.cheat:
            label += f"/cheat={args.cheat}"
        if args.lobby:
            label += f"/lobby={args.lobby}"
        rows = run_parallel(args.mode, args.games, args.workers, args.curve,
                            args.lobby, args.cheat, args.seed0,
                            cheat_gold=int(args.cheat_gold))
        summary = summarize(rows, label)
        summary["games"] = args.games
        summary["config"] = {"mode": args.mode, "curve": args.curve, "lobby": args.lobby,
                             "cheat": args.cheat, "cheat_gold": int(args.cheat_gold),
                             "seed0": args.seed0,
                             "build": E.build_info().get("source_hash"),
                             "version": E.game_version()}
    else:
        turns = [int(x) for x in args.turns.split(",") if x]
        jobs = [(args.seed0 + i, t, args.width, args.depth, args.curve, args.completion)
                for t in turns for i in range(args.games)]
        results = []
        with mp.Pool(min(args.workers, len(jobs))) as pool:
            for r in pool.imap_unordered(_beam_job, jobs, chunksize=1):
                if r:
                    results.append(r)
        summary = {"label": f"beam w={args.width} d={args.depth} c={args.completion}",
                   "results": results}
        print(f"\n== beam w={args.width} d={args.depth}  games={len(results)}")
        for r in results:
            print(f"seed {r['seed']:6d} t{r['turn']:2d} start={r['start']:6d} "
                  f"end={r['end']:6d} gain={r['gain']:6d} seq={r['seq'][:6]}")
        agg: dict[int, list[int]] = defaultdict(list)
        for r in results:
            agg[r["turn"]].append(r["end"])
        summary["agg"] = {t: {"n": len(v), "p50": pct(v, .5), "max": max(v)} for t, v in agg.items()}
        after: dict[int, list[int]] = defaultdict(list)
        for r in results:
            for t, s in r["after"].items():
                after[t].append(s)
        summary["after"] = summarize(after, "beam 之后 greedy 推进")["turns"]

    summary["elapsed_sec"] = round(time.time() - t0, 2)
    out = args.out or f"runs/ceiling_probe/{args.mode}_{label.replace('/', '_')}.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(summary, f, indent=1, ensure_ascii=False)
    print(f"\n[{out}]  {summary['elapsed_sec']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
