#!/usr/bin/env python3
"""以「法术缩放载体」为核心的确定性教师策略 + 200 局评测 CLI。

规则（可执行、确定性；输入 ``Game.view(seat)`` 的 board/hand/shop/gold/tier/
pending/mask，输出一个动作）：

1. **有载体可拿就先拿**：手牌里的载体随从立刻上场（满场先卖最弱非载体）；
   商店里的载体只要金币够（或能卖牌腾位置）就买；金币不够就**冻结**商店等下一回合。
2. **有载体就把法术打在载体上**：场上只要有主集合载体，手牌法术**全部**施放
   （酒馆法术买来后施放不花金币，只花 1 个动作）；``pending.kind == "target"``
   时优先选载体自己的 eid（对 ``cast_on_race`` 载体则优先选同种族随从）。
3. **没有载体就攒着**：手牌法术保留不空放；金币优先拿去升 tier（按 curve）与买
   身材，刷新（≤ ``refresh_cap`` 次/回合）只为找载体；只有在①手牌满、②
   ``turn >= cast_when_no_carrier_after``、③ 大厅根本没有载体种族 这三种情况下
   才把法术打出去换身材。
4. **其余按 greedy**：升本 curve、买最高身材、三连、英雄技能、结束回合。

合法性：每个首选动作都先过引擎 ``legal_mask``；万一非法才回退（``fallback``），
所以**实际执行合法率恒为 100%**；``first_choice_legal_rate`` 也单独统计。

用法::

  # 直接跑 200 局（默认 s15 训练同分布：5 席人类战团 + 2 席镜像 + bot）
  PYTHONPATH=rust/python:. python scripts/carrier_teacher.py \
      --games 200 --workers 8 --tag teacher_s15dist

  # 与 quality_monitor/s14_70M 的 566 同口径（7 个引擎 bot）
  PYTHONPATH=rust/python:. python scripts/carrier_teacher.py \
      --games 200 --workers 8 --tag teacher_bot --bot-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import carrier_common as C  # noqa: E402
from carrier_common import (A_BUY, A_CANCEL, A_CHOOSE, A_CHOOSE_END,  # noqa: E402
                            A_END, A_FREEZE, A_HERO_POWER, A_PLAY,
                            A_REFRESH, A_SELL, A_UPGRADE)


class CarrierTeacher:
    """载体优先的确定性教师（纯函数式：同 view + 同 mask → 同动作）。"""

    name = "carrier_teacher"

    def __init__(self, carriers_json: str = C.CATALOG_OUT, *,
                 refresh_cap: int = 2,
                 upgrade_curve=(4, 6, 8, 10),
                 cast_when_no_carrier_after: int = 11,
                 max_actions_per_turn: int = 40,
                 sell_cap: int = 3, buy_spells: bool = True,
                 spell_max_price: int = 2, replace_margin: int = 2):
        cat = C.load_or_build_catalog(carriers_json)
        self.catalog = cat
        self.emap = C.entry_map(cat)
        self.carrier_ids = C.ids_from_catalog(cat, "primary")
        self.narrow_ids = C.ids_from_catalog(cat, "narrow")
        self.prio = {cid: int(self.emap.get(cid, {}).get("priority") or 0)
                     for cid in self.carrier_ids}
        self.tier = {cid: int(self.emap.get(cid, {}).get("tier") or 0)
                     for cid in self.carrier_ids}
        self.races = {cid: list(self.emap.get(cid, {}).get("races") or [])
                      for cid in self.carrier_ids}
        self.trigger = {cid: str(self.emap.get(cid, {}).get("trigger") or "")
                        for cid in self.carrier_ids}
        self.refresh_cap = max(0, int(refresh_cap))
        self.upgrade_curve = tuple(int(x) for x in upgrade_curve)
        self.cast_late = int(cast_when_no_carrier_after)
        self.max_actions = max(1, int(max_actions_per_turn))
        self.sell_cap = max(0, int(sell_cap))
        self.buy_spells = bool(buy_spells)
        self.spell_max_price = int(spell_max_price)
        self.replace_margin = int(replace_margin)
        self.reset()

    # ── 生命周期 ─────────────────────────────────────────────────────────
    def reset(self) -> None:
        self._turn = -1
        self._actions = 0
        self._refreshes = 0
        self._sells = 0
        self._lobby: list = []
        self._available: set = set()
        self._counters = {
            "decisions": 0, "illegal_first_choice": 0, "fallbacks": 0,
            "carrier_buy_events": 0, "carrier_sell_events": 0,
            "spell_casts": 0, "carrier_target_casts": 0,
            "refreshes": 0, "freezes": 0, "upgrades": 0, "end_turns": 0,
            "cast_held": 0,
        }

    def meta(self) -> dict:
        d = dict(self._counters)
        d["available_carriers"] = sorted(self._available)
        return d

    def set_lobby(self, races, me=None) -> None:
        """登记大厅种族 → 本局**可能抽到**的载体集合（引擎按种族过滤池）。"""
        r = [str(x) for x in (races or [])]
        if r == self._lobby:
            return
        self._lobby = r
        races_set = set(r)
        avail = set()
        for cid in self.carrier_ids:
            card_races = set(self.races.get(cid) or [])
            if not card_races or "ALL" in card_races or (card_races & races_set):
                avail.add(cid)
        self._available = avail

    # ── 入口 ─────────────────────────────────────────────────────────────
    def decide(self, game, seat: int = 0):
        """从 ``Game`` 取 view + mask（独立驱动用）；返回动作下标。"""
        view = json.loads(game.view(int(seat)))
        mask = C._mask_np(game, int(seat))
        return self.decide_view(view, mask)

    def decide_view(self, view: dict, mask=None):
        me = view.get("me") or {}
        m = mask if mask is not None else (view.get("mask") or [])
        turn = int(view.get("turn") or 0)
        if turn != self._turn:
            self._turn = turn
            self._actions = 0
            self._refreshes = 0
            self._sells = 0
        if not self._lobby and view.get("lobby_races"):
            self.set_lobby(view.get("lobby_races"), me)
        self._actions += 1
        self._counters["decisions"] += 1
        if self._actions > self.max_actions:
            return self._legal(A_END, m)
        pend = me.get("pending")
        if pend:
            a = self._pending(view, me, m, pend)
        elif str(view.get("phase") or "recruit") != "recruit" or me.get("ended_turn"):
            a = A_END
        else:
            a = self._recruit(view, me, m)
        return self._ensure_legal(a, m)

    # ── 工具 ─────────────────────────────────────────────────────────────
    @staticmethod
    def _legal(a: int, m) -> bool:
        if a is None or a < 0:
            return False
        try:
            return 0 <= a < len(m) and bool(m[a])
        except TypeError:
            return False

    def _ensure_legal(self, a, m):
        if self._legal(a, m):
            return int(a)
        self._counters["fallbacks"] += 1
        self._counters["illegal_first_choice"] += 1
        for cand in (A_END,):
            if self._legal(cand, m):
                return int(cand)
        for i in range(len(m)):
            if bool(m[i]):
                return int(i)
        return A_END

    @staticmethod
    def _is_spell(it: dict) -> bool:
        return str((it or {}).get("kind") or "") in C.SPELL_KINDS

    @staticmethod
    def _is_minion(it: dict) -> bool:
        return not CarrierTeacher._is_spell(it)

    @staticmethod
    def _stats(it: dict) -> int:
        return int(it.get("atk") or 0) + int(it.get("hp") or 0)

    _KW_BONUS = {"DIVINE_SHIELD", "TAUNT", "REBORN", "WINDFURY", "VENOMOUS"}

    def _value(self, it: dict) -> int:
        """引擎 bot 同款身材估值：Σ + 3×tier + 关键词 + 金色。"""
        v = (self._stats(it) + 3 * int(it.get("tier") or 0)
             + (6 if it.get("golden") else 0))
        kws = set(str(x) for x in (it.get("keywords") or []))
        v += 3 * len(kws & self._KW_BONUS)
        return v

    @staticmethod
    def _price(it: dict) -> int:
        p = it.get("price")
        if isinstance(p, int) and p >= 0:
            return int(p)
        c = it.get("cost")
        if isinstance(c, int) and c >= 0:
            return int(c)
        return 3

    def _cid(self, it: dict) -> str:
        return str((it or {}).get("id") or "")

    def _is_carrier(self, it: dict) -> bool:
        return self._cid(it) in self.carrier_ids

    @staticmethod
    def _targets_minion(it: dict) -> bool:
        """法术是否会要求选一个随从目标（只有这类能触发「对本随从施法」）。"""
        t = f"{it.get('text') or ''} {it.get('text_zh') or ''}".lower()
        import re as _re
        return bool(_re.search(
            r"(?:give|choose|choose a|target|set|make|transform)\s+(?:a|an|one|another|"
            r"a random|a friendly|a different)\s+(?:friendly\s+|random\s+|different\s+)?minion"
            r"|(?:give|choose|target)\s+(?:a|an|one)\s+minion"
            r"|选择一个?随从|使一个随从|对一个随从", t))

    # ── pending（目标/发现/三选一/饰品/英雄）─────────────────────────────
    def _pending(self, view: dict, me: dict, m, pend) -> int:
        kind = str((pend or {}).get("kind") or "")
        opts = (pend or {}).get("options") or []
        legal = [i for i in range(C.N_CHOICE) if self._legal(A_CHOOSE + i, m)]
        if not legal:
            return self._legal(A_CANCEL, m) and A_CANCEL or A_END
        board = me.get("board") or []

        def _eid_of(i):
            if i >= len(opts):
                return None
            o = opts[i]
            return o.get("eid") if isinstance(o, dict) else o

        if kind == "target":
            board_c = {int(x.get("eid")): x for x in board
                       if self._is_carrier(x)}
            race_need = set()
            for x in board:
                cid = self._cid(x)
                if self._trigger(cid) == "cast_on_race":
                    race_need.update(self.races.get(cid) or [])
            best, best_score = None, None
            for i in legal:
                eid = _eid_of(i)
                if eid is None:
                    continue
                sc = 0.0
                if int(eid) in board_c:
                    sc += 1000 + 10 * self.prio.get(self._cid(board_c[int(eid)]), 0)
                else:
                    for x in board:
                        if int(x.get("eid") or -1) != int(eid):
                            continue
                        xr = set(x.get("races") or [])
                        if xr & race_need:
                            sc += 300
                        sc += self._stats(x)
                        break
                if best_score is None or sc > best_score:
                    best, best_score = i, sc
            if best is not None:
                self._counters["carrier_target_casts"] += (
                    1 if int(_eid_of(best) or 0) in board_c else 0)
                return A_CHOOSE + best
            return A_CHOOSE + legal[0]

        if kind == "choose_one" and me.get("casting") is not None:
            # 「选择一个随从」类：挑带 + 的属性选项；否则第一个
            best, best_score = None, None
            for i in legal:
                o = opts[i] if i < len(opts) else None
                txt = ""
                if isinstance(o, dict):
                    txt = (o.get("text") or "") + (o.get("name") or "")
                sc = 2.0 if ("+" in txt) else 0.0
                sc += 1.0 if ("minion" in txt.lower() or "随从" in txt) else 0.0
                sc -= 0.001 * i
                if best_score is None or sc > best_score:
                    best, best_score = i, sc
            return A_CHOOSE + (best if best is not None else legal[0])

        if kind in ("discover", "choose_one", "quest"):
            best, best_score = None, None
            for i in legal:
                o = opts[i] if i < len(opts) else None
                sc = 0.0
                if isinstance(o, dict):
                    cid = self._cid(o)
                    if cid in self.carrier_ids:
                        sc += 500 + 10 * self.prio.get(cid, 0)
                    if self._is_spell(o):
                        sc += 20
                    sc += self._stats(o) + int(o.get("tier") or 0)
                sc -= 0.001 * i
                if best_score is None or sc > best_score:
                    best, best_score = i, sc
            return A_CHOOSE + (best if best is not None else legal[0])

        if kind == "hero":
            best, best_score = None, None
            for i in legal:
                o = opts[i] if i < len(opts) else None
                armor = int(o.get("armor") or 0) if isinstance(o, dict) else 0
                if best_score is None or armor > best_score:
                    best, best_score = i, armor
            return A_CHOOSE + (best if best is not None else legal[0])

        if kind == "trinket":
            gold = int(me.get("gold") or 0)
            best, best_score = None, None
            for i in legal:
                o = opts[i] if i < len(opts) else None
                if not isinstance(o, dict):
                    continue
                cost = int(o.get("cost") or 0)
                if cost > gold:
                    continue
                txt = f"{o.get('text') or ''} {o.get('text_zh') or ''}".lower()
                sc = 3.0 if ("spell" in txt or "法术" in txt) else 0.0
                sc -= 0.01 * cost - 0.001 * i
                if best_score is None or sc > best_score:
                    best, best_score = i, sc
            return A_CHOOSE + (best if best is not None else legal[0])

        return A_CHOOSE + legal[0]

    def _trigger(self, cid: str) -> str:
        return self.trigger.get(cid, "")

    # ── 招募主循环 ───────────────────────────────────────────────────────
    def _recruit(self, view: dict, me: dict, m) -> int:
        gold = int(me.get("gold") or 0)
        tier = int(me.get("tier") or 1)
        turn = int(view.get("turn") or 0)
        board = me.get("board") or []
        hand = me.get("hand") or []
        shop = me.get("shop") or []
        hand_carriers = [(h, it) for h, it in enumerate(hand) if self._is_carrier(it)]
        hand_minions = [(h, it) for h, it in enumerate(hand)
                        if self._is_minion(it) and not self._is_carrier(it)]
        hand_spells = [(h, it) for h, it in enumerate(hand) if self._is_spell(it)]
        shop_carriers = [(s, it) for s, it in enumerate(shop)
                         if self._is_carrier(it)]
        shop_spells = [(s, it) for s, it in enumerate(shop) if self._is_spell(it)]
        shop_minions = [(s, it) for s, it in enumerate(shop)
                        if self._is_minion(it) and not self._is_carrier(it)]
        board_carriers = [x for x in board if self._is_carrier(x)]
        board_free = len(board) < C.N_BOARD
        hand_free = len(hand) < int(me.get("hand_limit") or 10)

        # 1) 手牌载体 → 上场（满场先卖最弱非载体）
        if hand_carriers:
            h, it = max(hand_carriers,
                        key=lambda x: (self.prio.get(self._cid(x[1]), 0), x[0]))
            a = self._play_hand(h, it, board, m)
            if a is not None:
                return a
            worst = self._worst_noncarrier(board)
            if worst is not None and self._legal(A_SELL + worst, m) \
                    and self._sells < self.sell_cap:
                self._counters["carrier_sell_events"] += 1
                self._sells += 1
                return A_SELL + worst

        # 2) 商店载体 → 买（金币够、有手牌位）；金币不够 → 冻结
        if shop_carriers:
            # 三连优先：同 id 已有 2 张
            owned = {}
            for x in board + [it for _, it in hand_carriers]:
                owned[self._cid(x)] = owned.get(self._cid(x), 0) + 1
            def _cprio(s, it):
                cid = self._cid(it)
                triple = 5 if owned.get(cid, 0) >= 2 else 0
                return (triple + self.prio.get(cid, 0), -self._price(it), -s)
            s, it = max(shop_carriers, key=lambda x: _cprio(*x))
            price = self._price(it)
            if gold >= price and hand_free:
                if board_free or self._worst_noncarrier(board) is not None:
                    self._counters["carrier_buy_events"] += 1
                    return A_BUY + s
            if gold < price:
                # 冻结等下一回合（免费；同回合不重复冻结）
                if self._legal(A_FREEZE, m) and not it.get("frozen"):
                    self._counters["freezes"] += 1
                    return A_FREEZE

        # 3) 手牌随从 → 上场（先铺满 7 席；满场用更强的替换最弱）
        if hand_minions:
            h, it = max(hand_minions, key=lambda x: (self._value(x[1]), -x[0]))
            a = self._play_hand(h, it, board, m)
            if a is not None:
                return a
            worst = self._worst_noncarrier(board)
            if worst is not None and self._legal(A_SELL + worst, m) \
                    and self._sells < self.sell_cap:
                if self._value(it) > self._value(board[worst]) + self.replace_margin:
                    self._sells += 1
                    return A_SELL + worst

        # 3b) 场上有载体：手牌法术全部打在载体上；再买便宜法术
        if board_carriers:
            for h, it in sorted(hand_spells,
                                key=lambda x: (0 if self._targets_minion(x[1]) else 1,
                                               self._price(x[1]), x[0])):
                if self._legal(A_PLAY + h * C.N_POS, m):
                    self._counters["spell_casts"] += 1
                    return A_PLAY + h * C.N_POS
            if hand_free:
                for s, it in sorted(shop_spells,
                                    key=lambda x: (0 if self._targets_minion(x[1]) else 1,
                                                   self._price(x[1]), x[0])):
                    price = self._price(it)
                    if gold >= price and self._legal(A_BUY + s, m):
                        return A_BUY + s

        # 3b2) 没有载体时也可以买便宜酒馆法术（买来施放不花金币，白嫖身材）
        if (not board_carriers) and hand_free and shop_spells and self.buy_spells:
            cheap = [(s, it) for s, it in shop_spells
                     if self._price(it) <= self.spell_max_price and gold >= self._price(it)
                     and self._legal(A_BUY + s, m)]
            if cheap and (len(board) >= 4 or int(view.get("turn") or 0) >= 5):
                s, it = min(cheap, key=lambda x: (self._price(x[1]), x[0]))
                return A_BUY + s

        # 3c) 有载体但商店没有法术：优先刷新找法术（每回合最多 1 次，且留钱买）
        if board_carriers and not shop_spells and self._refreshes < 1:
            rp = int(me.get("refresh_price") or 1)
            free = int(me.get("free_refreshes") or 0) > 0
            if gold >= max(4, rp + 3) and hand_free and self._legal(A_REFRESH, m):
                self._refreshes += 1
                self._counters["refreshes"] += 1
                return A_REFRESH

        # 4) 升 tier（按 curve；只在还需要更高 tier 才买得到载体时）
        target_tier = self._target_tier()
        if tier < target_tier and self._legal(A_UPGRADE, m):
            curve = self.upgrade_curve
            due = int(curve[min(tier - 1, len(curve) - 1)]) if curve else 99
            price_u = int(me.get("upgrade_cost") or me.get("upgrade_price") or 99)
            if (turn >= due or price_u <= 3) and gold >= price_u:
                self._counters["upgrades"] += 1
                return A_UPGRADE

        # 5) 买最高身材随从（有空位直接买；满场用更强的换掉最弱，≤2 次/回合）
        if hand_free and shop_minions:
            owned_n = {}
            for x in board + [it for _, it in hand_minions]:
                owned_n[self._cid(x)] = owned_n.get(self._cid(x), 0) + 1

            def _buy_score(x):
                s, it = x
                pair = 15 if owned_n.get(self._cid(it), 0) >= 1 else 0
                return (self._value(it) + pair, -x[0])

            s, it = max(shop_minions, key=_buy_score)
            price = self._price(it)
            n_minions = len(board) + len(hand_minions)
            pair = owned_n.get(self._cid(it), 0) >= 1
            if gold >= price and self._legal(A_BUY + s, m) \
                    and (n_minions < C.N_BOARD or pair):
                if board_free:
                    return A_BUY + s
                worst = self._worst_noncarrier(board)
                if worst is not None and self._sells < self.sell_cap:
                    if self._value(it) > self._value(board[worst]) + self.replace_margin:
                        self._sells += 1
                        return A_SELL + worst

        # 6) 激活随从（引擎 bot 同款：任何可激活的都点，通常是白嫖 buff/召唤）
        for i in range(min(len(board), C.N_BOARD)):
            if self._legal(C.A_ACTIVATE + i, m):
                return C.A_ACTIVATE + i

        # 7) 刷新找载体 / 找法术（只在买不动/买完还有余钱时）
        if self._refreshes < self.refresh_cap and self._legal(A_REFRESH, m):
            rp = int(me.get("refresh_price") or 1)
            free = int(me.get("free_refreshes") or 0) > 0
            afford = [x for x in shop_minions if gold >= self._price(x[1])]
            if board_carriers and not shop_spells:
                want = gold >= max(3, rp + 2) and hand_free
            else:
                want = (not afford) and self._want_refresh(
                    tier, board_carriers, shop_spells, gold)
            if want and (free or gold >= rp + 1):
                self._refreshes += 1
                self._counters["refreshes"] += 1
                return A_REFRESH

        # 7) 无载体时：极晚 / 手牌满 / 大厅根本没载体 → 把法术换成身材
        if hand_spells and not board_carriers:
            if self._should_dump_spells(view, me, hand):
                h, it = min(hand_spells, key=lambda x: (self._price(x[1]), x[0]))
                if self._legal(A_PLAY + h * C.N_POS, m):
                    self._counters["spell_casts"] += 1
                    return A_PLAY + h * C.N_POS
            else:
                self._counters["cast_held"] += 1

        # 8) 英雄技能（有就用；1 金）
        for slot in range(2):
            if self._legal(A_HERO_POWER + slot, m) and gold >= 1:
                return A_HERO_POWER + slot
        self._counters["end_turns"] += 1
        return A_END

    # ── 规则小件 ─────────────────────────────────────────────────────────
    def _play_hand(self, h: int, it: dict, board, m):
        if self._is_spell(it):
            a = A_PLAY + h * C.N_POS
            return a if self._legal(a, m) else None
        pos = len(board)
        for p in ([pos] + list(range(C.N_POS)))[:C.N_POS + 1]:
            if p >= C.N_POS:
                continue
            a = A_PLAY + h * C.N_POS + p
            if self._legal(a, m):
                return a
        return None

    def _worst_noncarrier(self, board):
        best_i, best_s = None, None
        for i, x in enumerate(board):
            if self._is_carrier(x):
                continue
            s = self._stats(x)
            if best_s is None or s < best_s:
                best_i, best_s = i, s
        return best_i

    def _target_tier(self) -> int:
        """升 tier 目标：按**可用载体的优先级**取最强那张的 tier（封顶 5）。"""
        avail = sorted(self._available or self.carrier_ids,
                       key=lambda cid: (-self.prio.get(cid, 0), self.tier.get(cid, 9)))
        for cid in avail:
            t = int(self.tier.get(cid, 0) or 0)
            if 0 < t <= 6:
                return max(4, min(5, t))
        return 4

    def _want_refresh(self, tier, board_carriers, shop_spells, gold) -> bool:
        if board_carriers:
            # 有载体：只想再找法术；且要留钱买（法术通常 1–3 金）
            return (not shop_spells) and gold >= 3 and self._refreshes < 2
        avail_tiers = [self.tier.get(cid, 0) for cid in self._available] or [0]
        need = min([t for t in avail_tiers if t] or [4])
        return tier >= need and gold >= 3

    def _should_dump_spells(self, view, me, hand) -> bool:
        if not self._available:
            return True                     # 大厅里根本没有载体种族
        if len(hand) >= int(me.get("hand_limit") or 10):
            return True                     # 手牌满，必须腾位置
        n_sp = sum(1 for it in hand if self._is_spell(it))
        if n_sp >= 2:
            return True                     # 只留 1 张等载体，多余的换成身材
        return int(view.get("turn") or 0) >= self.cast_late


# ── CLI ────────────────────────────────────────────────────────────────────
def build_cfg(args) -> dict:
    cat = C.load_or_build_catalog(args.carriers, rebuild=False)
    primary = C.ids_from_catalog(cat, "primary")
    names = {str(x.get("name")) for x in (cat.get("carriers") or [])
             if x.get("is_primary") or x.get("in_tavern_pool")}
    emap = C.entry_map(cat)
    races = set()
    for cid in primary:
        for r in (emap.get(cid, {}).get("races") or []):
            races.add(str(r))
    triggers = {cid: str(emap.get(cid, {}).get("trigger") or "")
                for cid in primary}
    bot_only = bool(args.bot_only)
    return {
        "policy": "teacher",
        "tag": str(args.tag),
        "seed_base": int(args.seed_base),
        "gold": int(args.gold),
        "max_steps": int(args.max_steps),
        "max_actions_per_turn": int(args.max_actions_per_turn),
        "record_log": int(args.record_log),
        "carriers_json": os.path.abspath(args.carriers),
        "carrier_ids": sorted(primary),
        "carrier_names": sorted(names),
        "carrier_races": sorted(races),
        "carrier_trigger": triggers,
        "teacher_refresh_cap": int(args.refresh_cap),
        "teacher_upgrade_curve": str(args.upgrade_curve),
        "teacher_cast_late_turn": int(args.cast_late_turn),
        "teacher_sell_cap": int(args.sell_cap),
        "human_boards": str(args.human_boards),
        "human_board_p": 0.0 if bot_only else float(args.human_board_p),
        "human_board_seats": int(args.human_board_seats),
        "human_board_sample": str(args.human_board_sample),
        "human_board_set_tier": int(args.human_board_set_tier),
        "human_board_fidelity": str(args.human_board_fidelity),
        "human_board_fast_inject": int(args.human_board_fast_inject),
        "mirror_snaps": str(args.mirror_snaps),
        "mirror_p": 0.0 if bot_only else float(args.mirror_p),
        "mirror_seats": int(args.mirror_seats),
        "mirror_sample": str(args.mirror_sample),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--carriers", default=C.CATALOG_OUT,
                    help="data/scaling/carriers.json（缺省自动构建）")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--seed-base", type=int, default=890000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--tag", default="teacher")
    ap.add_argument("--bot-only", action="store_true",
                    help="7 个引擎 bot 对手（与 runs/quality/s14_70M.json 同口径）")
    # 教师旋钮
    ap.add_argument("--refresh-cap", type=int, default=2)
    ap.add_argument("--upgrade-curve", default="4,6,8,10",
                    help="升到 tier2/3/4/5 的最早回合，逗号分隔")
    ap.add_argument("--sell-cap", type=int, default=3,
                    help="每回合最多卖几张换更强（引擎 bot 无硬上限，40 动作内）")
    ap.add_argument("--cast-late-turn", type=int, default=11,
                    help="无载体时第几回合起把法术打出去换身材")
    # 与 s15 采集同口径
    ap.add_argument("--gold", type=int, default=0)
    ap.add_argument("--max-actions-per-turn", type=int, default=40)
    ap.add_argument("--max-steps", type=int, default=20000)
    ap.add_argument("--record-log", type=int, default=1)
    ap.add_argument("--human-boards",
                    default="data/real_library/library_real_quasi_full.jsonl")
    ap.add_argument("--human-board-p", type=float, default=0.9)
    ap.add_argument("--human-board-seats", type=int, default=5)
    ap.add_argument("--human-board-sample", default="auto")
    ap.add_argument("--human-board-set-tier", type=int, default=1)
    ap.add_argument("--human-board-fidelity", default="full")
    ap.add_argument("--human-board-fast-inject", type=int, default=1)
    ap.add_argument("--mirror-snaps", default="runs/library/snaps_champ")
    ap.add_argument("--mirror-p", type=float, default=0.2)
    ap.add_argument("--mirror-seats", type=int, default=2)
    ap.add_argument("--mirror-sample", default="p75")
    ap.add_argument("--out-dir", default=C.ROLLOUT_DIR)
    args = ap.parse_args()

    cfg = build_cfg(args)
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    seeds = [int(args.seed_base) + i for i in range(int(args.games))]
    print(f"[carrier_teacher] games={len(seeds)} workers={args.workers} "
          f"tag={args.tag} bot_only={bool(args.bot_only)}", flush=True)
    rows = C.run_rollout(cfg, seeds, workers=int(args.workers))
    cat = C.load_or_build_catalog(args.carriers)
    summ = C.summarize(rows, cat)
    summ["gate"] = C.gate_check(summ)
    summ["config"] = {k: v for k, v in cfg.items()
                      if k not in ("carrier_ids", "carrier_names")}
    out_jsonl = os.path.join(out_dir, f"{args.tag}.jsonl")
    C.write_rollout(rows, out_jsonl, meta={
        "tag": args.tag, "policy": "teacher", "games": len(rows),
        "errors": summ["errors"], "bot_only": bool(args.bot_only),
        "carriers": os.path.abspath(args.carriers), "config": summ["config"],
    })
    out_json = os.path.join(out_dir, f"summary_{args.tag}.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summ, f, ensure_ascii=False, indent=1)
    brief = {k: summ[k] for k in ("games", "errors", "tag", "policy",
                                  "mean_rank", "top4", "win", "death_turn_p50",
                                  "fallback_actions")}
    print(json.dumps(brief, ensure_ascii=False))
    print(json.dumps(summ["carrier"], ensure_ascii=False, indent=1))
    print(json.dumps(summ["strength12"], ensure_ascii=False, indent=1))
    print(json.dumps(summ["corr_carrier_turns_str12"], ensure_ascii=False))
    print(json.dumps(summ["gate"], ensure_ascii=False))
    print(f"[out] {out_jsonl}")
    print(f"[out] {out_json}")
    return 0 if summ["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
