#!/usr/bin/env python3
"""人类式「复利脚本」：放大器优先 + 载体施法 + 三连 + 酒馆 buff + 饰品收入优先。

三件事
------
1. ``--mode amps``：用**现有权重**（默认 s14-BC ``runs/compound_prior/prep_bc/model_bc.pt``，
   或 ``--policy spell`` 脚本基线）跑 24 局，统计每张放大器「出现率 / 平均购买数」，
   回答「当前模型买不买放大器」。
2. ``--mode groups``：四组环境配置（S0..S3）× 28 局，量「环境能表达多少复利」：
   ``t12/t15 Σ p50/p90/max``、``r12_15 = Σ15/Σ12``（形状）、``Σ/金``、goldens、
   tavern_buff、放大器购买数、施法数、饰品命中。规则见 :class:`CompoundPolicy`。
3. 动作合法性：每一步都校验引擎 ``mask``（``legal_rate`` 必须 1.0）。

为什么手写而不用 BC 模型
------------------------
``docs/COMPOUND_CHAINS.md`` 的结论是模型在沙盒里几乎不买放大器、元音成长接近线性。
这里把「人类怎么打复利」写成显式优先级，用来区分两件事：
**环境表达不出复利** 还是 **策略没学会复利**。

规则优先级（高 → 低）
----------------------
1. 手牌法术优先对**载体**施放（``data/scaling/carriers.json`` 的 11 张 primary）。
   无载体时留 1 张，其余到 turn>=11 再打（``--spell-hold``）。
2. 商店有**放大器**（Brann / Titus-Rivendare / Drakkari / Ashen / Gatekeeper）立即买。
3. 商店有**载体** / **酒馆永久 buff farm**（``income_probe.json`` 的 tavern_buff 类）优先买。
4. **三连**：持有对子时买第三张（``goldens`` 是真实身材 62% 的来源）；刷新上限 ≤4/回合。
5. **t1–t5 curve 升级**：升到 tier+1 后保留 4/6/8/10 金（``--upgrade-reserve``），
   tier5→6 不再保留。
6. **t6/t9 饰品**：gold_generation > spell_generation > spell_amplify > tavern_buff。
7. 满场时卖掉**非核心**（非放大器/非载体/非 tavern-buff）里身材最小的，给核心腾位置。
8. 剩余金币买最强身材；仍花不掉则刷新（≤4 次/回合）；最后英雄技能 / EndTurn。

用法::

    # 第一步：放大器购买率（24 局，BC 权重，cuda:7）
    python scripts/compound_script.py --mode amps --games 24 --workers 8 \
        --checkpoint runs/compound_prior/prep_bc/model_bc.pt --device cuda:7

    # 第三步：四组环境上限（4×28 局）
    python scripts/compound_script.py --mode groups --games 28 --workers 12 \
        --json-out runs/compound_script/groups.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import hsbg_engine as E  # noqa: E402

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    CARRIER_IDS, END_TURN, EconomySandbox, SandboxConfig, VectorEconomySandbox,
    summarize)

# ── 动作布局（rust/crates/hsbg-engine/src/actions.rs）───────────────────────
A_END = 0
A_REFRESH = 1
A_FREEZE = 2
A_UPGRADE = 3
A_HERO_POWER = 4
A_DARK_GIFT = 6
A_CANCEL = 7
A_BUY = 8
A_SELL = 16
A_CHOOSE = 30
A_PLAY = 46
A_MOVE = 196
N_CHOICE = 16
N_POS = 8
N_BOARD = 7
N_SHOP = 8

BUY_RANGE = range(A_BUY, A_BUY + N_SHOP)
SELL_RANGE = range(A_SELL, A_SELL + N_BOARD)
PLAY_RANGE = range(A_PLAY, A_PLAY + 10 * N_POS)

# ── 放大器清单（卡名匹配 → 实际 card id；见 docs/COMPOUND_SCRIPT.md）───────
#   卡名匹配结果（37.0.0.255790 引擎卡表）：
#     "Brann Bronzebeard"        → BG_LOE_077（普通）/ TB_BaconUps_045（金色 3 次）
#     "Titus Rivendare"          → BG25_354 / BG25_354_G
#     "Drakkari Enchanter"       → BG26_ICC_901 / BG26_ICC_901_G
#     "Ashen Corruptor"          → BG32_873 / BG32_873_G
#     "Gatekeeper Amalgam"       → BG36_640 / BG36_640_G
#     "Barinda"                  → **卡表里不存在**（0 张）；法术放大用 inventory.spell_amp 代理
AMPLIFIERS: Dict[str, Tuple[str, ...]] = {
    "Brann": ("BG_LOE_077", "TB_BaconUps_045", "TB_BaconUps_045t"),
    "Titus/Rivendare": ("BG25_354", "BG25_354_G"),
    "Drakkari": ("BG26_ICC_901", "BG26_ICC_901_G"),
    "Ashen": ("BG32_873", "BG32_873_G"),
    "Gatekeeper": ("BG36_640", "BG36_640_G"),
}
# 临时/一次性的放大器效果（法术 / 饰品）：出现即买（规则 3 的延伸）
AMP_EFFECT_IDS: Dict[str, Tuple[str, ...]] = {
    "Brann's Blessing(spell)": ("BG28_509",),
    "Titus' Tribute(spell)": ("BG28_843",),
    "Big Brann Play(spell)": ("BGS_Treasures_030",),
    "Rivendare Portrait(trinket)": ("BG30_MagicItem_310",),
    "Drakkari Portrait(trinket)": ("BG32_MagicItem_179",),
}
AMP_IDS: Tuple[str, ...] = tuple(
    [i for ids in AMPLIFIERS.values() for i in ids]
    + [i for ids in AMP_EFFECT_IDS.values() for i in ids])
AMP_BY_ID: Dict[str, str] = {
    i: tag for tag, ids in {**AMPLIFIERS, **AMP_EFFECT_IDS}.items() for i in ids}
AMP_SHORT: Dict[str, str] = {
    "Brann": "Brann", "Titus/Rivendare": "Titus", "Drakkari": "Drakkari",
    "Ashen": "Ashen", "Gatekeeper": "Gatekeeper",
    "Brann's Blessing(spell)": "BrannSpell", "Titus' Tribute(spell)": "TitusSpell",
    "Big Brann Play(spell)": "BigBrannSpell",
    "Rivendare Portrait(trinket)": "TitusPic", "Drakkari Portrait(trinket)": "DrakkariPic",
}
CARRIERS = set(CARRIER_IDS)          # 11 张 primary + 金色（22 个 id）
SPELL_SYNERGY: set = set()           # “cast a spell on this” 类（catalog 载入后填充）
TRINKET_GRANT_AMP = set(AMP_EFFECT_IDS["Rivendare Portrait(trinket)"]
                        + AMP_EFFECT_IDS["Drakkari Portrait(trinket)"])

INCOME_JSON = os.path.join(ROOT, "runs", "comp_lines", "income_probe.json")


# ── 卡表 / 清单 ─────────────────────────────────────────────────────────────
def catalog() -> Dict[str, dict]:
    return {c["id"]: c for c in json.loads(E.catalog_json())}


def _init_spell_synergy() -> None:
    """“cast a spell on this / whenever you cast a (Tavern) spell” 类：法术落点载体。"""
    global SPELL_SYNERGY
    for cid, c in catalog().items():
        t = (c.get("text") or "").lower()
        if str(c.get("kind")) != "minion":
            continue
        if ("cast a spell on this" in t or "whenever you cast a spell" in t
                or "whenever you cast a tavern spell" in t):
            SPELL_SYNERGY.add(cid)
    CARRIERS.update(SPELL_SYNERGY)


_init_spell_synergy()


def load_inventory(path: str = INCOME_JSON) -> Dict[str, List[str]]:
    """从 ``runs/comp_lines/income_probe.json`` 取四类 card id（g/sg/sa/tb）。"""
    out: Dict[str, List[str]] = {"gold": [], "spell_gen": [], "spell_amp": [],
                                 "tavern_buff": []}
    try:
        inv = json.load(open(path, encoding="utf-8"))["inventory"]["summary"]["by_category"]
        for k in out:
            out[k] = [str(x) for x in (inv.get(k, {}).get("ids") or ())]
    except Exception:  # noqa: BLE001 - 清单缺失时退化为空表（脚本仍可跑）
        pass
    return out


INVENTORY = load_inventory()
INV_SETS = {k: set(v) for k, v in INVENTORY.items()}
TRINKET_PRIORITY = {
    "gold": 100, "spell_gen": 80, "spell_amp": 60, "tavern_buff": 40,
}


def price_of(item: dict) -> int:
    for k in ("price", "cost"):
        v = item.get(k)
        if isinstance(v, int) and v >= 0:
            return v
    return 3


def stats_of(m: dict) -> int:
    return int(m.get("atk") or 0) + int(m.get("hp") or 0)


def tier_of(c: dict) -> int:
    return int(c.get("tier") or 0)


def _is_tavern_buff_card(c: dict) -> bool:
    """「每次施法给酒馆 +X/+X」/「酒馆随从永久 +」类 farm 牌。

    只认 ``income_probe.json`` 挖出来的 tavern_buff 清单（15 个 id）；清单缺失时才退化为
    文本正则。**不要**用宽正则：``tavern`` + ``+`` + ``this game`` 会把大量普通牌误判成
    核心牌，导致满场时卖不掉、手牌卡死（实测会把 t15 Σ 压到 ~780）。
    """
    cid = str(c.get("id"))
    if INV_SETS["tavern_buff"]:
        return cid in INV_SETS["tavern_buff"]
    t = (c.get("text") or "").lower()
    return ("minions in the tavern" in t) and ("this game" in t) and ("+" in t)


def _is_carrier(c: dict) -> bool:
    return str(c.get("id")) in CARRIERS


# ── 策略 ────────────────────────────────────────────────────────────────────
class CompoundPolicy:
    """显式优先级的复利脚本；``act(view, mask)`` 只返回合法动作。"""

    def __init__(self, *, curve: str = "mid", spell_hold: int = 1,
                 max_refresh: int = 4, upgrade_reserve: Sequence[int] = (4, 6, 8, 10),
                 spawn_turn: int = 11, weights: Optional[Dict[str, float]] = None,
                 triple_first: bool = False, efficient: bool = False,
                 seed: int = 0):
        self.curve = curve
        #: 实验变体：三连/攒对子优先于载体/法术（默认 False = 正式教师逐位不变）
        self.triple_first = bool(triple_first)
        #: 实验变体：动作效率（无载体也早施法、放开买法术）
        self.efficient = bool(efficient)
        self.spell_hold = int(spell_hold)
        self.max_refresh = int(max_refresh)
        self.upgrade_reserve = tuple(int(x) for x in upgrade_reserve)
        self.spawn_turn = int(spawn_turn)
        self.w = {"amp": 3.0, "carrier": 2.0, "tavern_buff": 1.5, "triple": 2.5,
                  "stats": 1.0}
        if weights:
            self.w.update({k: float(v) for k, v in weights.items()})
        self.rng = np.random.default_rng(int(seed))
        self.turn = -1
        self.refreshes = 0
        self.actions = 0
        self.illegal = 0
        self.amp_buys: Counter = Counter()
        self.buys: Counter = Counter()
        self.casts = 0
        self.cast_on_carrier = 0

    # -- 入口 ---------------------------------------------------------------
    def act(self, v: dict, mask: np.ndarray) -> int:
        me = v.get("me") or {}
        t = int(v.get("turn") or 0)
        if t != self.turn:
            self.turn = t
            self.refreshes = 0
            self.actions = 0
        pend = me.get("pending")
        if pend:
            return self._safe(self._pending(v, me, pend), mask)
        if v.get("phase") != "recruit" or me.get("ended_turn"):
            return self._safe(A_END, mask)
        self.actions += 1
        if self.actions > 120:
            return self._safe(A_END, mask)
        return self._safe(self._recruit(v, me, mask), mask)

    def _safe(self, a: int, mask: np.ndarray) -> int:
        if 0 <= int(a) < 245 and bool(mask[int(a)]):
            return int(a)
        self.illegal += 1
        legal = np.flatnonzero(mask)
        if legal.size == 0:
            return END_TURN
        if bool(mask[END_TURN]):
            return END_TURN
        return int(legal[0])

    # -- 强制选择 -----------------------------------------------------------
    def _pending(self, v: dict, me: dict, pend: dict) -> int:
        mask = v["mask"]
        legal = [i for i in range(N_CHOICE) if mask[A_CHOOSE + i]]
        if not legal:
            return A_CHOOSE
        kind = str(pend.get("kind"))
        opts = list(pend.get("options") or pend.get("targets") or [])
        board = me.get("board") or []

        if kind in ("target", "targets"):
            # 优先载体：法术全打载体（规则 5）
            ceids = [int(m["eid"]) for m in board if _is_carrier(m)] \
                if opts and isinstance(opts[0], int) else []
            want = ceids[0] if ceids else None
            if want is not None:
                for i in legal:
                    if i < len(opts) and int(opts[i]) == want:
                        self.cast_on_carrier += 1
                        return A_CHOOSE + i
            if board:
                best = max(board, key=stats_of)
                for i in legal:
                    if i < len(opts) and int(opts[i]) == int(best["eid"]):
                        return A_CHOOSE + i
            return A_CHOOSE + legal[0]

        if kind == "hero":
            best = None
            for i in legal:
                if i >= len(opts) or not isinstance(opts[i], dict):
                    continue
                hp = opts[i].get("hero_power") or {}
                txt = (hp.get("text") or "").lower()
                sc = (3 if "+" in txt else 0) + (1 if "stats" in txt else 0)
                sc -= int(hp.get("cost") or 0)
                key = (sc, int(opts[i].get("armor") or 0))
                if best is None or key > best[0]:
                    best = (key, i)
            return A_CHOOSE + (best[1] if best else legal[0])

        if kind == "trinket":
            # 规则 2/6：gold > spell_gen > spell_amp > tavern_buff；放大器饰品再抬一档
            gold = int(me.get("gold") or 0)
            best = None
            for i in legal:
                if i >= len(opts) or not isinstance(opts[i], dict):
                    continue
                o = opts[i]
                cid = str(o.get("id") or "")
                sc = 0.0
                for cat, w in TRINKET_PRIORITY.items():
                    if cid in INV_SETS[cat]:
                        sc = max(sc, float(w))
                if cid in TRINKET_GRANT_AMP:
                    sc = max(sc, 95.0)
                sc -= 0.2 * max(0, int(o.get("cost") or 0))
                if int(o.get("cost") or 0) > gold:
                    sc -= 50.0
                if best is None or sc > best[0]:
                    best = (sc, i)
            return A_CHOOSE + (best[1] if best else legal[0])

        # discover / choose_one：放大器 > 载体 > 身材
        best = None
        for i in legal:
            if i >= len(opts) or not isinstance(opts[i], dict):
                continue
            o = opts[i]
            cid = str(o.get("id") or "")
            sc = float(stats_of(o)) if str(o.get("kind")) == "minion" else 0.0
            if cid in AMP_BY_ID:
                sc += 100.0
            elif cid in CARRIERS:
                sc += 60.0
            elif _is_tavern_buff_card(o):
                sc += 30.0
            if best is None or sc > best[0]:
                best = (sc, i)
        return A_CHOOSE + (best[1] if best else legal[0])

    # -- 招募 ---------------------------------------------------------------
    def _recruit(self, v: dict, me: dict, mask) -> int:
        gold = int(me.get("gold") or 0)
        board = me.get("board") or []
        hand = me.get("hand") or []
        shop = me.get("shop") or []
        tier = int(me.get("tier") or 1)
        turn = int(v.get("turn") or 1)

        def legal(a: int) -> bool:
            return 0 <= a < 245 and bool(mask[a])

        buys = [i for i in range(N_SHOP) if legal(A_BUY + i) and i < len(shop)]
        carriers_on_board = [m for m in board if _is_carrier(m)]
        hand_spells = [(h, it) for h, it in enumerate(hand[:10])
                       if it.get("type") != "minion"]
        hand_minions = [(h, it) for h, it in enumerate(hand[:10])
                        if it.get("type") == "minion"]

        # 0) 满场且商店有核心 → 先卖掉最弱非核心（规则 7）
        want_shop = [i for i in buys
                     if str(shop[i].get("id")) in AMP_BY_ID
                     or _is_carrier(shop[i]) or _is_tavern_buff_card(shop[i])]
        if want_shop and len(board) >= N_BOARD:
            victim = self._worst_noncore(board)
            if victim is not None and legal(A_SELL + victim):
                return A_SELL + victim

        # 1) 手牌法术 → 载体（规则 5）；无载体时留 1 张，turn>=11 再打
        if hand_spells:
            if carriers_on_board or (self.efficient and board):
                if carriers_on_board:
                    pos = board.index(carriers_on_board[0])
                else:      # efficient：无载体也打，落点=在场最强
                    pos = int(np.argmax([stats_of(m) for m in board]))
                for h, _it in hand_spells:
                    # 引擎里「打法术」用 pos=0，目标在 pending 阶段选（与 ScriptPolicy 同口径）
                    for a in (A_PLAY + h * N_POS, A_PLAY + h * N_POS + pos):
                        if legal(a):
                            self.casts += 1
                            return a
            elif turn >= self.spawn_turn:
                keep = 0 if len(hand_spells) <= self.spell_hold else self.spell_hold
                for h, _it in hand_spells[keep:]:
                    pos = int(np.argmax([stats_of(m) for m in board])) if board else 0
                    for a in (A_PLAY + h * N_POS, A_PLAY + h * N_POS + pos):
                        if legal(a):
                            self.casts += 1
                            return a

        # 1b) 手牌随从上场：核心（放大器/载体/tavern buff）优先；空位直接上，
        #     满场时卖掉最弱非核心腾位置（规则 7）
        if hand_minions:
            def keep_rank(kv):
                it = kv[1]
                cid = str(it.get("id") or "")
                core = 0 if (cid in AMP_BY_ID or _is_carrier(it)
                             or _is_tavern_buff_card(it)) else 1
                return (core, -stats_of(it))
            for h, it in sorted(hand_minions, key=keep_rank)[:4]:
                if len(board) < N_BOARD:
                    if legal(A_PLAY + h * N_POS + len(board)):
                        return A_PLAY + h * N_POS + len(board)
                else:
                    victim = self._worst_swap(board, self._core_rank(it),
                                              stats_of(it))
                    if victim is not None and legal(A_SELL + victim):
                        return A_SELL + victim

        # 2) 放大器：出现即买（规则 3）；只在「买得起 + 有位置放下」时买
        hand_free = len(hand) < 9
        # 手牌里等着上场的随从最终会占掉棋盘格；买牌前把这块也算进去，否则手牌 10 张卡死
        slots_left = N_BOARD - len(board) - len(hand_minions)
        can_host = slots_left > 0 or any(self._core_rank(m) < 3 for m in board)
        on_hand_ids = {str(it.get("id")) for it in hand}
        on_board_ids = {str(m.get("id")) for m in board}
        owned_all = on_hand_ids | on_board_ids

        def _buy_ok(item: dict) -> bool:
            """核心牌去重（同名不重复买，三连除外）+ 有位置放下。"""
            cid = str(item.get("id"))
            return hand_free and can_host and cid not in owned_all

        amps = [i for i in buys if str(shop[i].get("id")) in AMP_BY_ID
                and _buy_ok(shop[i])] if hand_free else []
        amps = [i for i in buys if str(shop[i].get("id")) in AMP_BY_ID]
        if amps:
            i = amps[0]
            if gold >= price_of(shop[i]):
                self._note_buy(shop[i])
                return A_BUY + i

        # 2b) ``triple_first`` 变体：三连优先（棋盘+手牌已 2 张 → 买第三张），
        #     再攒核心牌对子（第 2 张）。放大器已经在上面买过了，所以本数据集
        #     的主体目标（放大器购买率）不受影响。
        if self.triple_first and hand_free and can_host:
            owned_cnt = Counter(m["id"] for m in board)
            owned_cnt.update(it["id"] for it in hand if it.get("type") == "minion")

            def _owned(item: dict) -> int:
                return int(owned_cnt.get(str(item.get("id")), 0))

            trip = [i for i in buys if shop[i].get("type") == "minion"
                    and _owned(shop[i]) >= 2]
            if trip:
                i = max(trip, key=lambda k: stats_of(shop[k]))
                if gold >= price_of(shop[i]):
                    self._note_buy(shop[i])
                    return A_BUY + i
            if slots_left > 0:
                pair = [i for i in buys if shop[i].get("type") == "minion"
                        and _owned(shop[i]) == 1
                        and (str(shop[i].get("id")) in AMP_BY_ID
                             or _is_carrier(shop[i]))]
                if pair:
                    i = min(pair, key=lambda k: price_of(shop[k]))
                    if gold >= price_of(shop[i]):
                        self._note_buy(shop[i])
                        return A_BUY + i

        # 3) 载体：出现即买（规则 5 的核心；无载体 = 法术无处可打）
        carrier_buys = [i for i in buys if _is_carrier(shop[i]) and _buy_ok(shop[i])]
        if carrier_buys:
            i = min(carrier_buys, key=lambda k: price_of(shop[k]))
            if gold >= price_of(shop[i]):
                self._note_buy(shop[i])
                return A_BUY + i

        # 4) 酒馆永久 buff farm 牌（规则 6）
        tb_buys = [i for i in buys if _is_tavern_buff_card(shop[i]) and _buy_ok(shop[i])]
        if tb_buys:
            i = min(tb_buys, key=lambda k: price_of(shop[k]))
            if gold >= price_of(shop[i]):
                self._note_buy(shop[i])
                return A_BUY + i

        # 5) 买法术：有载体时就是缩放引擎（规则 5）；无载体则 t>=6 起囤 1 张
        spells = [i for i in buys if shop[i].get("type") != "minion"] if hand_free else []
        if spells:
            i = min(spells, key=lambda k: price_of(shop[k]))
            if gold >= price_of(shop[i]):
                n_hand_sp = sum(1 for _h, it in hand_spells)
                if carriers_on_board or n_hand_sp < 1 or gold >= 12 or self.efficient:
                    self._note_buy(shop[i])
                    return A_BUY + i

        # 6) 三连：对子 + 商店第三张 → 必买（规则 4）
        owned = Counter(m["id"] for m in board)
        owned.update(it["id"] for it in hand if it.get("type") == "minion")
        triples = [i for i in buys if shop[i].get("type") == "minion"
                   and owned.get(shop[i]["id"], 0) >= 2] if can_host else []
        if triples:
            i = max(triples, key=lambda k: stats_of(shop[k]))
            if gold >= price_of(shop[i]):
                self._note_buy(shop[i])
                return A_BUY + i

        # 5) curve 升级（t1–t5，保留 4/6/8/10 金；tier5→6 不保留）
        price = int(me.get("upgrade_price") or 99)
        if tier < 6 and legal(A_UPGRADE):
            reserve = 0 if tier >= 5 else self.upgrade_reserve[min(tier - 1,
                                                                   len(self.upgrade_reserve) - 1)]
            if gold >= price + reserve:
                return A_UPGRADE

        # 6) 手牌随从：空位就上；满场只换明显更强（非核心）
        if hand_minions:
            h, sitem = max(hand_minions, key=lambda kv: stats_of(kv[1]))
            s = stats_of(sitem)
            if len(board) < N_BOARD:
                pos = len(board)
                if legal(A_PLAY + h * N_POS + pos):
                    return A_PLAY + h * N_POS + pos
            else:
                victim = self._worst_noncore(board)
                if victim is not None and s > stats_of(board[victim]) + 8 \
                        and legal(A_SELL + victim):
                    return A_SELL + victim

        # 7) 买最强身材（规则 1）；满场时用「明显更强」门槛
        minions = [i for i in buys if shop[i].get("type") == "minion"]
        if minions:
            i = max(minions, key=lambda k: stats_of(shop[k]) + 2 * tier_of(shop[k]))
            s = shop[i]
            if gold >= price_of(s):
                if slots_left > 0:
                    self._note_buy(s)
                    return A_BUY + i
                victim = self._worst_swap(board, self._core_rank(s), stats_of(s))
                if victim is not None and stats_of(s) > stats_of(board[victim]) + 8 \
                        and legal(A_SELL + victim):
                    return A_SELL + victim

        # 8) 刷新（≤4 次/回合，规则 4）
        rp = int(me.get("refresh_price") or 1)
        if self.refreshes < self.max_refresh and legal(A_REFRESH) \
                and gold >= rp + 2:
            self.refreshes += 1
            return A_REFRESH

        # 9) 英雄技能（有就点，通常正收益）
        for slot in range(2):
            if legal(A_HERO_POWER + slot) and gold >= 1:
                return A_HERO_POWER + slot

        return A_END

    # -- 工具 ---------------------------------------------------------------
    @staticmethod
    def _core_rank(m: dict) -> int:
        """留场优先级：载体 3 > 放大器 2 > tavern-buff 1 > 普通 0（越大越该留）。"""
        if _is_carrier(m):
            return 3
        if str(m.get("id")) in AMP_BY_ID:
            return 2
        if _is_tavern_buff_card(m):
            return 1
        return 0

    def _worst_noncore(self, board: Sequence[dict]) -> Optional[int]:
        cands = [(stats_of(m), i) for i, m in enumerate(board)
                 if self._core_rank(m) == 0]
        if not cands:
            return None
        return min(cands)[1]

    def _worst_swap(self, board: Sequence[dict], inc_rank: int,
                    inc_stats: int) -> Optional[int]:
        """给「手里/商店的牌」找一个可卖的位（载体绝不卖；核心只在明显更优时换）。"""
        best = None
        for i, m in enumerate(board):
            r = self._core_rank(m)
            if r >= 3:
                continue
            s = stats_of(m)
            if inc_rank == 0:
                # 普通身材牌只换「明显更大」的：同是普通 +5，核心位 +20
                better = inc_stats > s + (5 if r == 0 else 20)
            else:
                better = (inc_rank > r) or (inc_rank == r and inc_stats > s + 5)
            if not better:
                continue
            key = (r, s)
            if best is None or key < best[0]:
                best = (key, i)
        return best[1] if best else None

    def _note_buy(self, item: dict) -> None:
        cid = str(item.get("id") or "")
        self.buys[cid] += 1
        if cid in AMP_BY_ID:
            self.amp_buys[AMP_SHORT[AMP_BY_ID[cid]]] += 1


# ── 一局驱动（可插任意策略，顺便记购买账本）────────────────────────────────
class Ledger:
    """按 A_BUY 动作 → 商店槽 card id 记账（精确，不依赖棋盘推断）。"""

    def __init__(self):
        self.buys: Counter = Counter()
        self.amp: Counter = Counter()
        self.spells_bought = 0
        self.legit = 0
        self.illegal = 0
        self.decisions = 0

    def note(self, a: int, shop: Sequence[dict]) -> None:
        self.decisions += 1
        if int(a) in BUY_RANGE:
            i = int(a) - A_BUY
            if 0 <= i < len(shop):
                cid = str(shop[i].get("id") or "")
                self.buys[cid] += 1
                if cid in AMP_BY_ID:
                    self.amp[AMP_SHORT[AMP_BY_ID[cid]]] += 1
                if shop[i].get("type") != "minion":
                    self.spells_bought += 1


def _shop_of(env) -> List[dict]:
    v = json.loads(env.g.view(0))
    return (v.get("me") or {}).get("shop") or []


def run_games(cfg: SandboxConfig, games: int, policy_kind: str, *,
              seed0: int, n_envs: int, checkpoint: str = "", device: str = "cpu",
              sample: bool = True, policy: Optional[CompoundPolicy] = None,
              ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """跑 ``games`` 局，返回 (episodes, ledger 汇总)。``policy_kind`` ∈ compound|spell|bc。"""
    model = None
    if policy_kind == "bc":
        from hsbg.az.train.model import load_checkpoint  # noqa: PLC0415
        model, _meta = load_checkpoint(checkpoint, device=str(device))
    n = max(1, min(n_envs, games))
    companies: Optional[List[Any]] = None
    if policy_kind == "spell":
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from engine_ceiling_probe import ScriptPolicy  # noqa: PLC0415
        companies = [ScriptPolicy(mode="spell", curve="mid") for _ in range(n)]
    elif policy_kind == "compound":
        companies = [policy or CompoundPolicy(seed=i) for i in range(n)]

    vec = VectorEconomySandbox(cfg, n_envs=n, seed0=seed0)
    obs = vec.reset()
    ledgers = [Ledger() for _ in range(vec.n_envs)]
    eps: List[Dict[str, Any]] = []
    pol_turn = [-1] * vec.n_envs
    t0 = time.time()
    while len(eps) < games:
        acts: List[int] = []
        if policy_kind == "bc":
            from hsbg.az.train.economy_sandbox import batch_act, stack_obs  # noqa: PLC0415
            f, c, m = stack_obs(obs)
            a, _lp, _v = batch_act(model, f, c, m, device, sample=bool(sample))
            for i in range(vec.n_envs):
                ai = int(a[i])
                v = json.loads(vec.envs[i].g.view(0))
                acts.append(ai)
                ledgers[i].note(ai, (v.get("me") or {}).get("shop") or [])
                ledgers[i].legit += 1
                if not bool(m[i][ai]):
                    ledgers[i].illegal += 1
        else:
            for i, env in enumerate(vec.envs):
                pol = companies[i]  # type: ignore[index]
                v = json.loads(env.g.view(0))
                me = v.get("me") or {}
                t = int(v.get("turn") or 0)
                if t != pol_turn[i]:      # 每回合重置脚本计数器（刷新上限等）
                    pol.turn, pol.actions, pol.refreshes, pol.casts = t, 0, 0, 0
                    pol_turn[i] = t
                if policy_kind == "compound":
                    a = pol.act(v, obs[i].mask)
                elif me.get("pending"):
                    a = pol._pending(v, 0, me["pending"])
                else:
                    a = pol._recruit(v, me, obs[i].mask)
                if not (0 <= int(a) < 245 and bool(obs[i].mask[int(a)])):
                    ledgers[i].illegal += 1
                    a = END_TURN
                a = int(a)
                ledgers[i].legit += 1
                ledgers[i].note(a, me.get("shop") or [])
                acts.append(a)
        obs, _r, dones, infos = vec.step(acts)
        for i, d in enumerate(dones):
            if not d:
                continue
            ep = dict(infos[i].get("episode") or {})
            lg = ledgers[i]
            ep["bought_ids"] = dict(lg.buys)
            ep["amp_buys"] = dict(lg.amp)
            ep["amp_total"] = int(sum(lg.amp.values()))
            ep["spells_bought"] = int(lg.spells_bought)
            eps.append(ep)
            ledgers[i] = Ledger()
            pol_turn[i] = -1
        if time.time() - t0 > 1200:
            break
    agg = {
        "illegal": int(sum(l.illegal for l in ledgers)),
        "legit": int(sum(l.legit for l in ledgers)),
        "amp_hist": dict(sum((Counter(e.get("amp_buys") or {}) for e in eps), Counter())),
        "amp_any_rate": float(np.mean([1.0 if int(e.get("amp_total") or 0) > 0 else 0.0
                                       for e in eps])) if eps else 0.0,
        "amp_mean": float(np.mean([int(e.get("amp_total") or 0) for e in eps])) if eps else 0.0,
    }
    return eps, agg


# ── 第一步：放大器购买率 ────────────────────────────────────────────────────
def amp_report(eps: Sequence[Dict[str, Any]], agg: Dict[str, Any]) -> Dict[str, Any]:
    n = len(eps)
    out: Dict[str, Any] = {"games": n, "amp_any_rate": agg.get("amp_any_rate", 0.0),
                           "amp_mean": agg.get("amp_mean", 0.0), "per_card": {}}
    all_bought = Counter()
    for e in eps:
        all_bought.update(e.get("bought_ids") or {})
    for tag, ids in AMPLIFIERS.items():
        short = AMP_SHORT[tag]
        buys = sum(int((e.get("bought_ids") or {}).get(i, 0)) for e in eps for i in ids)
        appears = sum(1 for e in eps if any(int((e.get("bought_ids") or {}).get(i, 0)) > 0
                                           for i in ids))
        out["per_card"][short] = {
            "ids": list(ids),
            "buy_rate": (buys / n) if n else 0.0,          # 平均每局购买数
            "appear_rate": (appears / n) if n else 0.0,    # 每局至少买 1 张的比例
            "total_buys": buys,
        }
    for tag, ids in AMP_EFFECT_IDS.items():
        short = AMP_SHORT[tag]
        buys = sum(int((e.get("bought_ids") or {}).get(i, 0)) for e in eps for i in ids)
        appears = sum(1 for e in eps if any(int((e.get("bought_ids") or {}).get(i, 0)) > 0
                                           for i in ids))
        out["per_card"][short] = {"ids": list(ids), "buy_rate": buys / n if n else 0.0,
                                  "appear_rate": appears / n if n else 0.0,
                                  "total_buys": buys}
    out["spells_mean"] = float(np.mean([int(e.get("spells_t15") or 0) for e in eps])) if n else 0.0
    out["sigma_t15_p50"] = float(np.median([int(e.get("sigma_t15") or 0) for e in eps])) if n else 0.0
    out["goldens_p50"] = float(np.median([int(e.get("goldens_t15") or 0) for e in eps])) if n else 0.0
    out["tavern_buff_p50"] = float(np.median([int(e.get("tavern_buff_t15") or 0)
                                             for e in eps])) if n else 0.0
    out["legal_rate"] = float(agg["legit"] / max(1, agg["legit"] + agg["illegal"]))
    return out


# ── 第三步：四组 ────────────────────────────────────────────────────────────
def group_configs(gold_cap: int = 99) -> Dict[str, SandboxConfig]:
    base = dict(turns=15, gold_mode="fixed", gold_per_turn=30, action_cap=40,
                num_players=8, trinkets=True, gold_cap=int(gold_cap),
                lobby_types=())
    s0 = SandboxConfig(**base)
    s1 = SandboxConfig(**{**base, "gold_mode": "growth", "gold_growth_rate": 0.15,
                          "gold_per_carrier": 2})
    s2 = SandboxConfig(**{**base, "gold_mode": "growth", "gold_growth_rate": 0.15,
                          "gold_per_carrier": 2, "action_cap_per_gold": 3})
    s3 = SandboxConfig(**{**base, "gold_mode": "growth", "gold_growth_rate": 0.15,
                          "gold_per_carrier": 2, "action_cap_per_gold": 3,
                          "tavern_buff_scale": 3.0})
    return {"S0": s0, "S1": s1, "S2": s2, "S3": s3}


def _pct(vals: Sequence[float], q: float) -> float:
    return float(np.percentile(np.asarray(vals, dtype=np.float64), q)) if len(vals) else 0.0


def group_report(eps: Sequence[Dict[str, Any]], agg: Dict[str, Any],
                 cfg: SandboxConfig) -> Dict[str, Any]:
    rep = summarize(eps)
    n = len(eps)
    s12 = [float(e.get("sigma_t12") or 0) for e in eps]
    s15 = [float(e.get("sigma_t15") or 0) for e in eps]
    gi = [float(e.get("gold_total_income") or 0) for e in eps]
    ratios = [a / b for a, b in zip(s15, s12) if b > 0]
    hits = 0
    hit_games = 0
    trinket_targets = set(INVENTORY["gold"] + INVENTORY["spell_gen"]
                          + INVENTORY["spell_amp"] + list(TRINKET_GRANT_AMP))
    for e in eps:
        picked = set(str(x) for x in (e.get("trinket_ids") or ()))
        h = picked & trinket_targets
        hits += len(h)
        hit_games += 1 if h else 0
    rep.update({
        "games": n,
        "r12_15_p50": _pct(ratios, 50),
        "r12_15_p90": _pct(ratios, 90),
        "r12_15_max": max(ratios) if ratios else 0.0,
        "sigma15_per_gold_p50": _pct([a / b for a, b in zip(s15, gi) if b > 0], 50),
        "amp_buys_mean": agg.get("amp_mean", 0.0),
        "amp_any_rate": agg.get("amp_any_rate", 0.0),
        "amp_by_card": agg.get("amp_hist", {}),
        "spells_p50": _pct([float(e.get("spells_t15") or 0) for e in eps], 50),
        "goldens_p50": _pct([float(e.get("goldens_t15") or 0) for e in eps], 50),
        "tavern_buff_p50": _pct([float(e.get("tavern_buff_t15") or 0) for e in eps], 50),
        "trinket_hits_mean": hits / n if n else 0.0,
        "trinket_hit_game_rate": hit_games / n if n else 0.0,
        "legal_rate": (agg["legit"] / max(1, agg["legit"] + agg["illegal"])),
        "config": cfg.engine_config(),
    })
    return rep


# ── 多进程 ──────────────────────────────────────────────────────────────────
_G: Dict[str, Any] = {}


def _init_worker(payload: Dict[str, Any]) -> None:
    _G.clear()
    _G.update(payload)


def _worker(job: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _G["cfg"]
    eps, agg = run_games(cfg, int(job["games"]), _G["policy_kind"],
                         seed0=int(job["seed0"]), n_envs=int(job["games"]),
                         checkpoint=_G.get("checkpoint", ""),
                         device=_G.get("device", "cpu"),
                         policy=_G.get("policy"))
    return {"episodes": eps, "agg": agg}


def run_pool(cfg: SandboxConfig, games: int, workers: int, policy_kind: str, *,
             seed0: int, checkpoint: str = "", device: str = "cpu",
             policy: Optional[CompoundPolicy] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    import multiprocessing as mp
    # 把 games 均分给 workers（每 worker 一个 VectorEconomySandbox，n_envs=分到的局数）
    n = max(1, min(int(workers), games))
    chunks = [(games + i) // n for i in range(n)]
    chunks = [c for c in chunks if c > 0]
    jobs = [{"games": c, "seed0": seed0 + 1000 * i} for i, c in enumerate(chunks)]
    payload = {"cfg": cfg, "policy_kind": policy_kind, "checkpoint": checkpoint,
               "device": device, "policy": policy}
    t0 = time.time()
    with mp.get_context("fork").Pool(len(jobs), initializer=_init_worker,
                                     initargs=(payload,)) as pool:
        outs = pool.map(_worker, jobs)
    eps: List[Dict[str, Any]] = []
    agg = {"illegal": 0, "legit": 0, "amp_hist": Counter(), "amp_any_rate": 0.0,
           "amp_mean": 0.0}
    for o in outs:
        eps.extend(o["episodes"])
        agg["illegal"] += o["agg"]["illegal"]
        agg["legit"] += o["agg"]["legit"]
        agg["amp_hist"] = dict(Counter(agg["amp_hist"]) + Counter(o["agg"]["amp_hist"]))
    if eps:
        agg["amp_any_rate"] = float(np.mean([1.0 if int(e.get("amp_total") or 0) > 0 else 0.0
                                             for e in eps]))
        agg["amp_mean"] = float(np.mean([int(e.get("amp_total") or 0) for e in eps]))
    agg["seconds"] = time.time() - t0
    return eps, agg


# ── CLI ─────────────────────────────────────────────────────────────────────
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="人类式复利脚本 + 环境上限探针")
    ap.add_argument("--mode", default="groups", choices=["amps", "groups", "one"])
    ap.add_argument("--games", type=int, default=24)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed0", type=int, default=770000)
    ap.add_argument("--policy", default="bc", choices=["bc", "spell", "compound"])
    ap.add_argument("--checkpoint", default="runs/compound_prior/prep_bc/model_bc.pt")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--sample", type=int, default=1)
    ap.add_argument("--gold-per-turn", type=int, default=30)
    ap.add_argument("--action-cap", type=int, default=40)
    ap.add_argument("--gold-cap", type=int, default=99,
                    help="注入后的金币上限（0 = 不封顶；见 docs/COMPOUND_INCOME.md）")
    ap.add_argument("--turn", type=int, default=15)
    ap.add_argument("--max-refresh", type=int, default=4)
    ap.add_argument("--spell-hold", type=int, default=1)
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv)

    t_start = time.time()
    if args.mode == "amps":
        cfg = SandboxConfig(turns=int(args.turn), gold_per_turn=int(args.gold_per_turn),
                            action_cap=int(args.action_cap), num_players=8,
                            trinkets=True, gold_cap=int(args.gold_cap))
        eps, agg = run_pool(cfg, int(args.games), int(args.workers), str(args.policy),
                            seed0=int(args.seed0), checkpoint=str(args.checkpoint),
                            device=str(args.device))
        rep = amp_report(eps, agg)
        rep.update({"policy": args.policy, "checkpoint": args.checkpoint,
                    "illegal": agg["illegal"], "legit": agg["legit"],
                    "seconds": agg.get("seconds", 0.0),
                    "config": cfg.engine_config()})
        print(json.dumps({k: rep[k] for k in ("games", "amp_any_rate", "amp_mean",
                                              "spells_mean", "sigma_t15_p50",
                                              "goldens_p50", "tavern_buff_p50",
                                              "legal_rate") if k in rep},
                         ensure_ascii=False, indent=1))
        print("\n放大器（ids | 平均购买/局 | 出现率 | 总购买）")
        for k, r in rep["per_card"].items():
            print(f"  {k:16s} {','.join(r['ids'])[:60]:62s} "
                  f"{r['buy_rate']:6.3f}  {r['appear_rate']:5.2f}  {r['total_buys']:4d}")
    elif args.mode == "one":
        cfg = SandboxConfig(turns=int(args.turn), gold_per_turn=int(args.gold_per_turn),
                            action_cap=int(args.action_cap), num_players=8,
                            trinkets=True, gold_cap=int(args.gold_cap))
        pol = CompoundPolicy(max_refresh=int(args.max_refresh),
                             spell_hold=int(args.spell_hold))
        eps, agg = run_games(cfg, int(args.games), "compound", seed0=int(args.seed0),
                             n_envs=int(args.games), policy=pol)
        rep = group_report(eps, agg, cfg)
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        cfgs = group_configs(gold_cap=int(args.gold_cap))
        out: Dict[str, Any] = {"groups": {}, "seconds": 0.0}
        for name, cfg in cfgs.items():
            pol = CompoundPolicy(max_refresh=int(args.max_refresh),
                                 spell_hold=int(args.spell_hold))
            eps, agg = run_pool(cfg, int(args.games), int(args.workers), "compound",
                                seed0=int(args.seed0), policy=pol)
            out["groups"][name] = group_report(eps, agg, cfg)
            g = out["groups"][name]
            print(f"[{name}] t12 p50/p90/max={g['sigma_t12_p50']:.0f}/"
                  f"{g['sigma_t12_p90']:.0f}/{g['sigma_t12_max']:.0f} "
                  f"t15 p50/p90/max={g['sigma_t15_p50']:.0f}/"
                  f"{g['sigma_t15_p90']:.0f}/{g['sigma_t15_max']:.0f} "
                  f"r12_15={g['r12_15_p50']:.2f} Σ/金={g['sigma15_per_gold_p50']:.1f} "
                  f"amp={g['amp_buys_mean']:.2f} spells={g['spells_p50']:.0f} "
                  f"goldens={g['goldens_p50']:.0f} tav={g['tavern_buff_p50']:.0f} "
                  f"legal={g['legal_rate']:.3f}", flush=True)
        out["seconds"] = time.time() - t_start
        rep = out
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1, default=float)
        print(f"[compound] 写出 {args.json_out}")
    print(f"[compound] 总耗时 {time.time() - t_start:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
