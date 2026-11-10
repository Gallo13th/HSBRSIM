#!/usr/bin/env python3
"""按 data/comp_exec.json（人工逐套形式化的可执行规格）在沙盒里跑套路。

与 comp_run.py 的区别：keep/cycle/受益者/循环阶段全部来自 comp_exec.json，
不再由我自动推导（自动推导会把"钢铁场地管理员"这种无关卡当 keep）。

沙盒前提（用户指定）：6 本、金币充足（999）、不被淘汰（血量 999）、
所需卡直接注入手牌（不考虑商店运气）。
"""
from __future__ import annotations
import argparse, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "rust", "python")); sys.path.insert(0, ROOT)
os.environ.setdefault("HSBRSIM_BAN_TRINKETS", "BG36_MagicItem_414")
import hsbg_engine as E  # noqa: E402
from hsbg.az.train.game_rules import game_config_json  # noqa: E402

SPECS = json.load(open(os.path.join(ROOT, "data", "comp_exec.json"), encoding="utf-8"))
CAT = {int(c["cid"]): c for c in json.loads(E.catalog_json())}
N2ID: dict[str, list[tuple[int, str]]] = {}
for cid, c in CAT.items():
    if c.get("name_zh") and c.get("in_pool") and c.get("kind") == "minion":
        N2ID.setdefault(c["name_zh"], []).append((cid, c.get("id")))
A_END, A_BUY, A_SELL, A_PLAY = 0, 8, 16, 46
SLOTS = 7


def dbg(g, **kw):
    return g.debug(json.dumps(kw, ensure_ascii=False))


def cid_of(m) -> int:
    it = (m or {}).get("item") or {}
    for k in ("Minion", "Spell"):
        v = it.get(k)
        if isinstance(v, dict) and v.get("card"):
            return int(v["card"]) + 1
    return 0


def pj(g, p=0):
    return json.loads(g.player_json(p))


def legal(g, p=0):
    return [i for i, v in enumerate(g.legal_mask(p)) if v]


def nm(cid):
    return (CAT.get(int(cid)) or {}).get("name_zh") or ""


def resolve_all(names):
    out, miss = set(), []
    for n in names or []:
        got = N2ID.get(n)
        if got:
            out.add(got[0][0] + 1)      # 统一用 obs 编码（cid+1）
        else:
            miss.append(n)
    return out, miss


def compile_spec(sp: dict) -> dict:
    keep, cycle, hold = set(), set(), set()
    for lp in sp.get("loops") or []:
        k, _ = resolve_all(lp.get("keep"))
        b, _ = resolve_all(lp.get("buy"))
        keep |= k
        if lp.get("play_then_sell"):
            cycle |= b - keep
        else:
            hold |= b - keep          # 磁力/吸附类：买了就打，留在场上
    amps, _ = resolve_all(sp.get("amplifiers"))
    econ, _ = resolve_all(sp.get("econ"))
    ben = sp.get("beneficiary") or {}
    bset, _ = resolve_all([ben.get("value")] if ben.get("kind") == "card" else [])
    return dict(spec=sp, keep=keep | (amps - cycle), cycle=cycle, hold=hold,
                amps=amps, econ=econ, ben=ben, ben_card=bset,
                min_count=int(ben.get("min_count") or 3))


def beneficiary_cnt(c, board_cids):
    ben = c["ben"]
    if ben.get("kind") == "race":
        return sum(1 for x in board_cids if ben["value"] in (CAT.get(int(x)) or {}).get("races", []))
    if ben.get("kind") == "card":
        return sum(1 for x in board_cids if x in c["ben_card"])
    if ben.get("kind") == "mechanic":
        kw = ben["value"]
        return sum(1 for x in board_cids if kw in ((CAT.get(int(x)) or {}).get("text_zh") or ""))
    return 0


def inject(g, c, p=0, n=7):
    st = pj(g, p)
    own = {int(m.get("card") or 0) + 1 for m in st.get("board") or []}
    own |= {cid_of(m) for m in st.get("hand") or []}
    order = (sorted(c["keep"] - own) + sorted(c["hold"] - own)
             + sorted(c["cycle"] - own) + sorted(c["econ"] - own))
    k = 0
    for cid in order:
        if k >= n:
            break
        sid = N2ID.get(nm(cid))
        if not sid:
            continue
        try:
            r = dbg(g, cmd="add_minion", p=p, zone="hand", card=sid[0][1])
        except Exception as exc:  # noqa: BLE001
            if "full" in str(exc):
                break
            continue
        if '"ok":true' in str(r).replace(" ", ""):
            k += 1
    return k


def run(sp: dict, turns=12) -> dict:
    c = compile_spec(sp)
    need = c["keep"] | c["cycle"] | c["hold"]
    seed = 0
    for s in range(1, 150):
        uni = {int(x) for x in (json.loads(E.Game(s * 1000, game_config_json()).state_json())
                                .get("universe") or [])}
        if need <= uni:
            seed = s * 1000
            break
    g = E.Game(seed or 1000, game_config_json())
    for _ in range(400):
        if json.loads(g.state_json()).get("phase") != "HeroSelect":
            break
        for q in range(8):
            if not g.needs_action(q):
                continue
            a = legal(g, q)
            if a:
                g.step(0, a[0]) if q == 0 else g.bot_play(q)
    dbg(g, cmd="set_player", p=0, tier=6, gold=999, health=999, free_refreshes=99)
    dbg(g, cmd="refresh_shop", p=0)
    hist, cyc_total = [], 0
    for t in range(int(turns)):
        dbg(g, cmd="set_player", p=0, gold=999, health=999, free_refreshes=99)
        if not g.needs_action(0):
            break
        inject(g, c, 0, n=7)
        steps = cyc = 0
        while g.needs_action(0) and steps < 500:
            steps += 1
            a = legal(g, 0)
            st = pj(g, 0)
            hand = [cid_of(m) for m in st.get("hand") or []]
            board = [int(m.get("card") or 0) + 1 for m in st.get("board") or []]
            # 手牌：keep/hold 优先留下；cycle 打出后立刻卖
            order = sorted(range(len(hand)),
                           key=lambda i: (hand[i] not in c["keep"], hand[i] not in c["hold"]))
            moved = False
            for i in order:
                if not hand[i] or (A_PLAY + i) not in a:
                    continue
                cid = hand[i]
                g.step(0, A_PLAY + i)
                moved = True
                if cid in c["cycle"] and cid not in c["keep"]:
                    for k2, m in enumerate(pj(g, 0).get("board") or []):
                        if int(m.get("card") or 0) + 1 == cid and (A_SELL + k2) in legal(g, 0):
                            g.step(0, A_SELL + k2)
                            cyc += 1
                            break
                break
            if moved:
                continue
            # 场满 → 卖掉最差的非 keep（优先 cycle/无关卡）
            if len(board) >= SLOTS and (A_SELL) in a:
                worst, ws = None, 1e9
                for k2, cid in enumerate(board):
                    if cid in c["keep"]:
                        continue
                    sc = 10 if cid in c["cycle"] else (30 if cid in c["hold"] else 0)
                    if sc < ws:
                        worst, ws = k2, sc
                if worst is not None:
                    g.step(0, A_SELL + worst)
                    cyc += 1
                    continue
            # 再注入（保证"需要的卡都能拿到"）
            if inject(g, c, 0, n=7):
                continue
            if A_END in a:
                g.step(0, A_END)
            break
        cyc_total += cyc
        st = pj(g, 0)
        board = [int(m.get("card") or 0) + 1 for m in st.get("board") or []]
        strength = sum(int(m.get("atk") or 0) + int(m.get("hp") or 0) for m in st.get("board") or [])
        hist.append(dict(turn=t + 1, strength=strength, cycles=cyc,
                         benef=beneficiary_cnt(c, board), board=[nm(x) for x in board]))
        for _ in range(80):
            acted = False
            for q in range(1, 8):
                if g.needs_action(q):
                    acted = True
                    g.bot_play(q)
            if not acted:
                break
        if g.is_over():
            break
    last = hist[-1] if hist else dict(strength=0, benef=0, board=[], cycles=0)
    return dict(id=sp["id"], name=sp["name"], turns=len(hist),
                strengths=[h["strength"] for h in hist],
                final=last["strength"], benef=last["benef"],
                min_count=c["min_count"], cycles=cyc_total,
                board=last["board"], target=(c["ben"].get("kind"), c["ben"].get("value")))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--turns", type=int, default=12)
    ap.add_argument("--out", default="runs/comp_run2.json")
    a = ap.parse_args(argv)
    todo = SPECS if a.all else [s for s in SPECS if s["id"] == a.plan]
    res = []
    for sp in todo:
        r = run(sp, a.turns)
        res.append(r)
        growth = (r["strengths"][-1] / max(1, r["strengths"][0])) if r["strengths"] else 0
        verdict = ("OK" if (r["benef"] >= r["min_count"] and growth >= 2.0)
                   else ("受益不足" if r["benef"] < r["min_count"] else "成长不足"))
        print("%-3s %-18s 终局%5d 受益%2d/%d 循环%4d 斜率%4.1fx %-6s | %s" % (
            r["id"], r["name"], r["final"], r["benef"], r["min_count"],
            r["cycles"], growth, verdict, "、".join(r["board"][:7])))
    json.dump(res, open(a.out, "w"), ensure_ascii=False, indent=1)
    ok = sum(1 for r in res if r["benef"] >= r["min_count"]
             and (r["strengths"][-1] / max(1, r["strengths"][0])) >= 2.0)
    print("\n汇总：%d/%d OK" % (ok, len(res)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
