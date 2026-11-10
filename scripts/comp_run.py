#!/usr/bin/env python3
"""按 comp_exec 编译出的 keep/cycle/受益者，在沙盒里跑一套（或全部）套路。

与旧版区别（就是上次的三个硬伤）：
1. **会卖卡**：cycle 件打出（触发战吼/亡语）后立刻卖掉腾格；场满时卖最无用的非 keep 卡
2. **会循环**：一直 buy→play→sell，直到本回合没有可循环的牌
3. **保受益者**：keep 只留"对受益机制/种族有用"的卡；受益者数量不足时优先补
"""
from __future__ import annotations
import argparse, json, os, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "rust", "python")); sys.path.insert(0, ROOT)
os.environ.setdefault("HSBRSIM_BAN_TRINKETS", "BG36_MagicItem_414")
import hsbg_engine as E  # noqa: E402
from hsbg.az.train.game_rules import game_config_json  # noqa: E402
import comp_exec as CE  # noqa: E402

A_END, A_REFRESH, A_BUY, A_SELL, A_PLAY = 0, 1, 8, 16, 46
SLOTS = 7


def dbg(g, **kw):
    return g.debug(json.dumps(kw, ensure_ascii=False))


def cid_of_item(m) -> int:
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


def to_recruit(g):
    for _ in range(400):
        if json.loads(g.state_json()).get("phase") != "HeroSelect":
            break
        acted = False
        for q in range(8):
            if not g.needs_action(q):
                continue
            a = legal(g, q)
            if not a:
                continue
            acted = True
            g.step(0, a[0]) if q == 0 else g.bot_play(q)
        if not acted:
            break


def score(b: dict, cid: int) -> float:
    ids = b["ids"]
    if b["target_race"] and b["target_race"] in CE.races(cid):
        return 99.0 if cid in b["keep"] else 88.0
    if b["target_mech"] and (b["target_mech"] & CE.mech(cid)):
        return 95.0 if cid in b["keep"] else 86.0
    if cid in ids["start"]:
        return 100.0
    if cid in ids["pay"]:
        return 97.0
    if cid in ids["amp"]:
        return 94.0
    if cid in b["keep"]:
        return 90.0
    if cid in b["cycle"]:
        return 60.0
    if cid in ids["econ"]:
        return 40.0
    return 0.0


def inject(g, b: dict, p=0, n=7):
    st = pj(g, p)
    own = {int(m.get("card") or 0) + 1 for m in st.get("board") or []}
    own |= {cid_of_item(m) for m in st.get("hand") or []}
    want = [c for c in sorted(b["keep"], key=lambda c: -score(b, c)) if c not in own]
    want += [c for c in sorted(b["cycle"], key=lambda c: -score(b, c)) if c not in own]
    k = 0
    for cid in want:
        if k >= n:
            break
        sid = CE.NAME2ID.get(CE.nm(cid))
        if not sid:
            continue
        try:
            r = dbg(g, cmd="add_minion", p=p, zone="hand", card=sid[0][1])
        except Exception as exc:  # noqa: BLE001
            if "full" in str(exc):
                break
            raise
        if '"ok":true' in str(r).replace(" ", ""):
            k += 1
    return k


def beneficiaries(b: dict, board_cids: list[int]) -> int:
    n = 0
    for cid in board_cids:
        if b["target_race"] and b["target_race"] in CE.races(cid):
            n += 1
        elif b["target_mech"] and (b["target_mech"] & CE.mech(cid)):
            n += 1
    return n


def play_turn(g, b, p=0, max_steps=600):
    steps = cycles = 0
    while g.needs_action(p) and not g.is_over():
        steps += 1
        if steps > max_steps:
            a = legal(g, p)
            if A_END in a:
                g.step(p, A_END)
            return cycles
        a = legal(g, p)
        st = pj(g, p)
        hand = [cid_of_item(m) for m in (st.get("hand") or [])]
        board = [int(m.get("card") or 0) + 1 for m in (st.get("board") or [])]
        shop = [cid_of_item(m) for m in (st.get("shop") or [])]
        # 1) 手牌：keep 先上场；cycle 上场后立刻卖掉（触发即走）
        order = sorted(range(len(hand)), key=lambda i: -score(b, hand[i]))
        acted = False
        for i in order:
            if not hand[i] or (A_PLAY + i) not in a:
                continue
            cid = hand[i]
            g.step(p, A_PLAY + i)
            acted = True
            if cid in b["cycle"] and cid not in b["keep"]:
                # 打出后卖掉：找它现在在场上的位置
                st2 = pj(g, p)
                for k, m in enumerate(st2.get("board") or []):
                    if int(m.get("card") or 0) + 1 == cid and (A_SELL + k) in legal(g, p):
                        g.step(p, A_SELL + k)
                        cycles += 1
                        break
            break
        if acted:
            continue
        # 2) 买：keep 缺牌优先；否则 cycle
        target = None
        best = 0.0
        for i, cid in enumerate(shop[:7]):
            if not cid or (A_BUY + i) not in a:
                continue
            s = score(b, cid)
            if s > best:
                target, best = A_BUY + i, s
        if target is not None and best > 0:
            g.step(p, target)
            continue
        # 3) 场满且手上有 keep 进不来 → 卖最差的非 keep
        if len(board) >= SLOTS and A_SELL in a:
            worst, worst_s = None, 1e9
            for k, cid in enumerate(board):
                if cid in b["keep"]:
                    continue
                s = score(b, cid)
                if s < worst_s:
                    worst, worst_s = k, s
            if worst is not None:
                g.step(p, A_SELL + worst)
                cycles += 1
                continue
        # 4) 商店没好牌 → 注入需要的牌（测试前提：所需卡都能拿到）
        if 3 <= int(st.get("gold") or 0) and inject(g, b, p, n=7):
            continue
        if A_END in a:
            g.step(p, A_END)
        return cycles
    return cycles


def run(pid: str, turns: int = 10, seed_base: int = 500) -> dict:
    b = CE.ALL[pid]
    plan = b["plan"]
    need = set(b["keep"]) | set(b["cycle"])
    seed = 0
    for s in range(1, 120):
        uni = {int(x) for x in (json.loads(E.Game(s * 1000, game_config_json()).state_json())
                                .get("universe") or [])}
        if need <= uni:
            seed = s * 1000
            break
    g = E.Game(seed or seed_base * 1000, game_config_json())
    to_recruit(g)
    dbg(g, cmd="set_player", p=0, tier=6, gold=999, health=999, free_refreshes=99)
    dbg(g, cmd="refresh_shop", p=0)
    hist = []
    for t in range(int(turns)):
        dbg(g, cmd="set_player", p=0, gold=999, health=999, free_refreshes=99)
        if not g.needs_action(0):
            break
        inject(g, b, 0, n=7)
        cyc = play_turn(g, b, 0)
        st = pj(g, 0)
        board = [int(m.get("card") or 0) + 1 for m in (st.get("board") or [])]
        strength = sum(int(m.get("atk") or 0) + int(m.get("hp") or 0)
                       for m in (st.get("board") or []))
        hist.append(dict(turn=t + 1, strength=strength, cycles=cyc,
                         benef=beneficiaries(b, board),
                         board=[CE.nm(c) for c in board]))
        for _ in range(60):
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
    return dict(plan="%s %s" % (pid, plan["name"]), turns=len(hist),
                strength=[h["strength"] for h in hist],
                final=last["strength"], benef=last["benef"],
                target=(b["target_race"] or "") + "/" + "/".join(sorted(b["target_mech"])),
                board=last["board"], cycles=sum(h["cycles"] for h in hist))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--turns", type=int, default=10)
    ap.add_argument("--out", default="runs/comp_run.json")
    a = ap.parse_args(argv)
    ids = list(CE.ALL) if a.all else [a.plan]
    res = []
    for pid in ids:
        r = run(pid, a.turns)
        res.append(r)
        ok_benef = r["benef"] >= 3
        grow = r["strength"][-1] > 2 * (r["strength"][0] or 1)
        print("%-4s %-18s 终局%5d 受益%2d 循环%3d 判断=%s | %s" % (
            pid, r["plan"][3:], r["final"], r["benef"], r["cycles"],
            "OK" if (ok_benef and grow) else ("受益不足" if not ok_benef else "成长不足"),
            "、".join(r["board"][:7])))
    json.dump(res, open(a.out, "w"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
