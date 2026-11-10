#!/usr/bin/env python3
"""套路实验室：在"6 本 + 10 金币 + 不被淘汰"的沙盒里，按攻略逐步执行一套阵容，
记录每回合的盘面与强度，用来验证"套路实现是否正确 / 成长是否够快"。

用法：
    python scripts/comp_lab.py --plan 30 --turns 10 --seeds 2
    python scripts/comp_lab.py --all --turns 10 --seeds 1 --out runs/comp_lab
"""
from __future__ import annotations
import argparse, json, os, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "rust", "python")); sys.path.insert(0, ROOT)
for _k, _v in (("HSBRSIM_FORCE_UPGRADE", "0"), ("HSBRSIM_BAN_TRINKETS", "BG36_MagicItem_414")):
    os.environ.setdefault(_k, _v)
import hsbg_engine as E  # noqa: E402
from hsbg.az.train.game_rules import game_config_json  # noqa: E402

PLANS = json.load(open(os.path.join(ROOT, "data", "comp_plans.json"), encoding="utf-8"))["plans"]
CAT = {int(c["cid"]): c for c in json.loads(E.catalog_json())}
NAME2ID: dict[str, list[tuple[int, str]]] = {}
for cid, c in CAT.items():
    nm = c.get("name_zh")
    if nm:
        NAME2ID.setdefault(nm, []).append((cid, c.get("id")))
POOL = {int(c["cid"]) for c in json.loads(E.catalog_json()) if c.get("in_pool")}


def dbg(g, **kw):
    g.debug(json.dumps(kw, ensure_ascii=False))


def tier_of(cid: int) -> int:
    return int((CAT.get(int(cid)) or {}).get("tier") or 0)


def nm(cid: int) -> str:
    return (CAT.get(int(cid)) or {}).get("name_zh") or f"#{cid}"


def txt(cid: int) -> str:
    return (CAT.get(int(cid)) or {}).get("text_zh") or ""


def mech(cid: int) -> set[str]:
    t = txt(cid)
    out = set()
    if "亡语" in t:
        out.add("亡语")
    if "战吼" in t:
        out.add("战吼")
    if "回合结束" in t:
        out.add("回合结束")
    if "磁力" in t:
        out.add("磁力")
    return out


def plan_cards(plan: dict) -> dict[str, set[str]]:
    """角色 → 卡名集合（只保留卡池里有的）。"""
    out = {}
    for role in ("econ", "start", "pay", "amp", "syn", "flex"):
        out[role] = {x for x in (plan.get(role) or []) if x in NAME2ID}
    return out


def resolve(name: str) -> int | None:
    for cid, _sid in NAME2ID.get(name, []):
        if cid in POOL:
            return cid
    return None


def plan_ids(plan: dict) -> dict[str, set[int]]:
    out = {}
    for role, names in plan_cards(plan).items():
        ids = {c for c in (resolve(x) for x in names) if c}
        out[role] = ids
    return out


def amp_synergy_mechs(plan: dict) -> set[str]:
    m = set()
    for a in plan.get("amp") or []:
        if a == "提图斯·瑞文戴尔":
            m.add("亡语")
        elif a == "达卡莱附魔师":
            m.add("回合结束")
        elif a == "布莱恩·铜须":
            m.add("战吼")
    return m


def to_recruit(g) -> None:
    """把 HeroSelect 阶段推完（本座选第一个英雄，其它座位用引擎 bot）。"""
    for _ in range(400):
        if json.loads(g.state_json()).get("phase") != "HeroSelect":
            break
        acted = False
        for q in range(8):
            if not g.needs_action(q):
                continue
            a = [i for i, v in enumerate(g.legal_mask(q)) if v]
            if not a:
                continue
            acted = True
            if q == 0:
                g.step(0, a[0])
            else:
                g.bot_play(q)
        if not acted:
            break


def shop_card(entry: dict) -> int:
    """商店条目 → cards 编码（cid+1）。兼容 Minion/Spell 两种 item。"""
    it = (entry or {}).get("item") or {}
    for k in ("Minion", "Spell"):
        v = it.get(k)
        if isinstance(v, dict) and v.get("card"):
            return int(v["card"]) + 1
    return 0


def hand_card(entry: dict) -> int:
    it = (entry or {}).get("item") or {}
    for k in ("Minion", "Spell"):
        v = it.get(k)
        if isinstance(v, dict) and v.get("card"):
            return int(v["card"]) + 1
    return 0


def board_card(entry: dict) -> int:
    cid = (entry or {}).get("card")
    return int(cid) + 1 if cid else 0


def setup(g, p=0, tier=6, gold=10, health=999):
    to_recruit(g)
    dbg(g, cmd="set_player", p=p, tier=tier, gold=gold, health=health,
        max_gold_bonus=0, free_refreshes=99, upgrade_cost=0)
    dbg(g, cmd="refresh_shop", p=0)


def state(g, p=0):
    st = json.loads(g.player_json(p))
    return st


def snapshot(g, p=0):
    st = state(g, p)
    board = st.get("board") or []
    tot = sum(int(m.get("atk") or 0) + int(m.get("hp") or 0) for m in board)
    return dict(turn=int(st.get("turn") or 0), tier=int(st.get("tier") or 0),
                gold=int(st.get("gold") or 0), strength=tot,
                board=[(nm(int(m["card"]) + 1), int(m.get("atk") or 0), int(m.get("hp") or 0),
                        bool(m.get("golden")), sorted(mech(int(m["card"]) + 1))) for m in board])


def legal(g, p=0):
    m = g.legal_mask(p)
    return [i for i, v in enumerate(m) if v]


def inject_shop(g, plan: dict, p=0, n=4):
    """把这套阵容缺的关键卡注入商店（模拟"该来的牌都来了"，专注验证套路本身）。"""
    ids = plan_ids(plan)
    st = state(g, p)
    own = set()
    for m in (st.get("board") or []):
        own.add(int(m.get("card") or 0) + 1)
    for m in (st.get("hand") or []):
        own.add(hand_card(m))
    order = ["start", "pay", "amp", "syn", "econ", "flex"]
    want = []
    for role in order:
        for cid in ids.get(role) or set():
            if cid not in own:
                want.append(cid)
    # 补足：机制协同卡（亡语/战吼/回合结束）
    syn_mech = amp_synergy_mechs(plan)
    if syn_mech:
        for cid in POOL:
            if cid in own or cid in want:
                continue
            if syn_mech & mech(cid) and tier_of(cid) <= 6:
                want.append(cid)
                if len(want) > 12:
                    break
    dbg(g, cmd="clear_zone", p=p, zone="shop")
    k = 0
    for cid in want[: int(n)]:
        sid = NAME2ID.get(C(cid), [])
        if not sid:
            continue
        dbg(g, cmd="add_minion", p=p, zone="shop", card=sid[0][1], pos=k)
        k += 1
    return k


def C(cid: int) -> str:
    return (CAT.get(int(cid)) or {}).get("name_zh") or ""


def play_turn(g, plan: dict, p=0, max_buys=40, max_steps=300):
    """按攻略角色优先级：买 syn/start/pay 优先，其次 amp，再次 econ/flex；
    买到的牌若场上能放就放上去；放大器尽量与协同件相邻。"""
    ids = plan_ids(plan)
    syn_mech = amp_synergy_mechs(plan)
    inject_shop(g, plan, p, n=4)
    buys = 0
    steps = 0
    while buys < max_buys and g.needs_action(p) and not g.is_over():
        steps += 1
        if steps > int(max_steps):
            a = legal(g, p)
            if 0 in a:
                g.step(p, 0)
            return
        a = legal(g, p)
        st = state(g, p)
        shop = [shop_card(m) for m in (st.get("shop") or [])]
        hand = [hand_card(m) for m in (st.get("hand") or [])]
        board = st.get("board") or []
        # 1) 场上可用的牌先打出去（手牌 → 场面）
        play_act = None
        for i, cid in enumerate(hand):
            if cid and 46 + i in a:   # A_PLAY = 46
                play_act = 46 + i
                break
        if play_act is not None:
            g.step(p, play_act)
            continue
        # 2) 从商店按优先级买
        def score(cid: int) -> float:
            if cid in ids.get("syn"):
                return 100.0
            if cid in ids.get("start"):
                return 95.0
            if cid in ids.get("pay"):
                return 90.0
            if cid in ids.get("amp"):
                return 85.0
            if cid in ids.get("econ"):
                return 60.0
            if cid in ids.get("flex"):
                return 40.0
            if syn_mech & mech(cid):
                return 70.0     # 机制协同（攻略没列但机制相同）
            return 0.0
        best, best_s = None, 0.0
        for i, cid in enumerate(shop[:7]):
            c = 8 + i
            if not cid or c not in a:
                continue
            s = score(cid)
            if s > best_s:
                best, best_s = c, s
        if best is not None and best_s > 0:
            g.step(p, best)
            buys += 1
            continue
        # 3) 没有想买的 → 刷新（免费）再试一次；仍未命中就结束回合
        if 0 < len(shop) and (st.get("gold") or 0) > 0:
            if 1 in a and buys < 12:
                dbg(g, cmd="set_player", p=p, free_refreshes=99)
                g.step(p, 1)      # A_REFRESH
                continue
        if 0 in a:
            g.step(p, 0)          # A_END
            return
        # 兜底：随便走一步
        g.step(p, a[0])


def run_game(plan: dict, seed: int, turns: int, p=0):
    g = E.Game(seed, game_config_json())
    setup(g, p)
    hist = [snapshot(g, p)]
    for t in range(int(turns)):
        # 每回合补满金币并保持不被淘汰
        dbg(g, cmd="set_player", p=p, gold=10, health=999, free_refreshes=99)
        if not g.needs_action(p):
            break
        inject_shop(g, plan, p, n=4)
        play_turn(g, plan, p)
        # 其他座位让引擎 bot 行动，推进回合
        guard = 0
        while not g.is_over() and guard < 4000:
            acted = False
            for q in range(8):
                if q == p or not g.needs_action(q):
                    continue
                acted = True
                g.bot_play(q)
                guard += 1
                if g.is_over():
                    break
            if not acted:
                break
            if g.needs_action(p):
                play_turn(g, plan, p)
        if g.is_over():
            print("[lab] 游戏结束（沙盒里不应发生）")
            break
        hist.append(snapshot(g, p))
    return hist


def summarize(plan: dict, hist: list[dict]) -> dict:
    ids = plan_ids(plan)
    syn_mech = amp_synergy_mechs(plan)
    last = hist[-1]
    names = [b[0] for b in last["board"]]
    amps = [n for n in names if n in (plan.get("amp") or [])]
    syn = [n for n in names if n in (plan.get("syn") or [])]
    syn_by_mech = [b for b in last["board"] if (syn_mech & set(b[4]))]
    return dict(
        plan=plan["id"] + " " + plan["name"],
        turns=len(hist) - 1,
        strengths=[h["strength"] for h in hist],
        final_strength=last["strength"],
        final_board=[f"{b[0]}{'金' if b[3] else ''}({b[1]}/{b[2]})" for b in last["board"]],
        amps=amps, syn_list=syn, syn_mech_cnt=len(syn_by_mech),
        t5=sum(1 for b in last["board"] if tier_of(int(next((c for c, _ in NAME2ID.get(b[0], [(0, "")])), 0))) >= 5),
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="", help="套路编号，如 30")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--turns", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--out", default="runs/comp_lab")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    todo = PLANS if a.all else [p for p in PLANS if p["id"] == a.plan or p["name"] == a.plan]
    if not todo:
        print("没有匹配的套路"); return 2
    res = []
    for plan in todo:
        rows = []
        for s in range(a.seeds):
            hist = run_game(plan, 700000 + int(plan["id"]) * 10 + s, a.turns)
            rows.append(summarize(plan, hist))
        best = max(rows, key=lambda r: r["final_strength"])
        res.append(best)
        print("%s | 回合 %d | 终局强度 %d | 放大器 %s | 攻略协同 %s | 机制协同 %d | 盘面 %s" % (
            best["plan"], best["turns"], best["final_strength"],
            ",".join(best["amps"]) or "无", ",".join(best["syn_list"]) or "无",
            best["syn_mech_cnt"], "、".join(best["final_board"])))
    json.dump(res, open(os.path.join(a.out, "lab_%s.json" % ("all" if a.all else a.plan)), "w"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
