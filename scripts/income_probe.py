#!/usr/bin/env python3
"""收入机制探针：把沙盒的「每金币价值产出」推到接近真实 10k+ 的口径。

为什么需要
----------
``docs/COMP_LINES_TINY.md`` §4 的结论是：沙盒的 t15 Σ 脚本上限只有 1,400，
**Σ/金币 = 2.9**，而真实 10k+ 战团是 **9.9**（3.4 倍）。差额的三个候选来源：
金币生成饰品/法术、法术生成（每回合多一张酒馆法术 = 多一次缩放）、三连/金色、
酒馆永久 buff × 场上 N。本脚本做两件事：

1. **机制清单**（``inventory()``）：从引擎卡表（``hsbg_engine.catalog_json()``）里把
   所有与「金币生成 / 法术生成 / 法术放大 / 酒馆永久 buff / 三连奖励」相关的卡抓出来，
   给出 id / kind / tier / 效果文本 / 引擎是否实现（``implemented``/``scripted``）/
   **预估每回合额外收入**（粗估口径写在 ``inventory()["method"]`` 里）。
2. **三档探针**（脚本策略，200 局/档，纯 CPU）：

   | 档 | 收入口径 | 饰品选择 | 买牌偏好 |
   |---|---|---|---|
   | ``I0``  | ``fixed``：每回合重置 30 金（= 现状） | 第一个买得起的（基线） | 基线 ``spell`` |
   | ``I0e`` | ``engine``：引擎自然补币 30/回合（**不覆写**，饰品的回合开始金币/max-gold 全部保留） | 同基线 | 基线 ``spell`` |
   | ``I1``  | 同 ``I0e`` | **优先金币生成饰品** | 基线 ``spell`` |
   | ``I2``  | 同 ``I0e`` | 优先金币 > 法术生成 > 法术放大 | + 优先买金币/法术生成牌 |

   ``I0e`` 是对照组：把「引擎收入不被覆写」这一件事单独隔离出来，否则 ``I1`` 与
   ``I0`` 的差异同时混了收入口径与饰品偏好两个变量。

   ``I3``/``I4`` 是**复利收入**档（沙盒侧 ``--gold-mode growth``）：``I3`` 用 15%/回合
   + 每载体 2 金（与训练臂 G15 同口径），``I4`` 是上界（35%/回合、无金币上限、动作额度
   120，与训练臂 G35u 同口径）。它们回答「不加训练、只改收入时脚本能到多少」，也就是
   模型要学的目标天花板。

判据（``docs/COMPOUND_INCOME.md``）：Σ/金币 能否从 2.9 推到 **≥6**（真实 9.9 的 60%）；
若三档都 < 4，则说明引擎的经济上限与线上不一致，要报告缺什么。

用法::

    python scripts/income_probe.py --games 200 --workers 16 \
        --json-out runs/comp_lines/income_probe.json
    python scripts/income_probe.py --inventory-only --json-out /tmp/inc.json
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import re
import sys
import time
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hsbg_engine as E  # noqa: E402

from hsbg.az.train.economy_sandbox import (  # noqa: E402
    END_TURN, EconomySandbox, SandboxConfig, SandboxPolicies, summarize)

from engine_ceiling_probe import (  # noqa: E402
    A_BUY, A_CHOOSE, A_END, A_PLAY, A_REFRESH, A_SELL, A_UPGRADE, N_BOARD, N_CHOICE,
    ScriptPolicy, card_of, minion_stats, price_of)

GOLD_REF = 30          # 基线每回合金币（与 docs/COMP_LINES_TINY.md / ceiling probe 同口径）
TURNS_REF = 15
BASE_GOLD_TOTAL = GOLD_REF * TURNS_REF      # 450（Σ/金币 的分母）

# ── 卡表分类 ────────────────────────────────────────────────────────────────

_GOLD = re.compile(r"gold", re.I)
_SPELL_GEN = re.compile(
    r"(get (?:a |two |three |four |\d+ )?(?:random )?(?:tavern )?spell"
    r"|get (?:a )?copy of the last (?:tavern )?spell"
    r"|get (\d+) copies of the last (?:tavern )?spell"
    r"|discover (?:a |two |\d+ )?(?:tavern )?spell"
    r"|add (?:a )?(?:random )?(?:tavern )?spell"
    r"|teach it that spell|cast a random tavern spell|spell to your hand)", re.I)
_SPELL_AMP = re.compile(
    r"(tavern spells give|your tavern spells|cast a spell on a friendly minion"
    r"|casts it on another|after you cast a spell on a (?:friendly|tavern))", re.I)
_TAVERN_BUFF = re.compile(r"in the Tavern .{0,20}this game", re.I)
_GOLD_GEN = re.compile(
    r"(gain \d+ gold|gain gold|increase your maximum gold|maximum gold by"
    r"|\d+ gold for each|gold for each)", re.I)

#: 触发频率的经验估计（每回合次数）。分母来自沙盒实测：~8 次买牌/回合、
#: 每回合花 ~30 金、~4-5 次施法/回合（``runs/comp_lines/ceiling.json``）。
_TRIGGERS: Tuple[Tuple[str, float, str], ...] = (
    (r"at the start of every two turns", 0.5, "开局/每两回合"),
    (r"at the start of (?:your|each) turn", 1.0, "回合开始"),
    (r"at the end of (?:your|each) turn", 1.0, "回合结束"),
    (r"every two turns", 0.5, "每两回合"),
    (r"(?:twice|2 times) per turn", 2.0, "每回合两次"),
    (r"(?:three times|3 times) per turn", 3.0, "每回合三次"),
    (r"whenever you buy|after you buy a minion", 8.0, "每次买牌（~8/回合）"),
    (r"after you spend 7 gold|when you spend 7 gold", 4.0, "每花 7 金（~4/回合）"),
    (r"after you spend 50 gold", 0.6, "每花 50 金（~0.6/回合）"),
    (r"when you spend 20 gold", 1.5, "每花 20 金（~1.5/回合）"),
    (r"after you cast 3 spells", 1.0, "每 3 次施法（~1/回合）"),
    (r"after you cast 4 spells", 0.8, "每 4 次施法（~0.8/回合）"),
    (r"after you cast 5 spells", 0.6, "每 5 次施法（~0.6/回合）"),
    (r"each turn", 1.0, "每回合"),
)


def _catalog() -> Dict[str, Dict[str, Any]]:
    return {c["id"]: c for c in json.loads(E.catalog_json())}


def _text(c: Dict[str, Any]) -> str:
    return str(c.get("text") or "")


def _multiplier(t: str) -> Tuple[float, str, str]:
    """(每回合触发次数, 触发口径说明, 置信度)。一次性效果按 1/15 摊。"""
    low = t.lower()
    if "once per game" in low:
        return 1.0 / TURNS_REF, "每局一次", "low"
    if "then swap" in low:
        return 1.0 / TURNS_REF, "触发一次后换掉", "low"
    # "(N left!)" = 本局总共还能触发 N 次 → 摊到 15 回合
    limit = None
    m = re.search(r"\((\d+) left!\)", low)
    if m:
        limit = int(m.group(1))
    for pat, rate, why in _TRIGGERS:
        if re.search(pat, low):
            conf = "high" if ("start of" in pat or "end of" in pat
                              or "each turn" in pat) else "medium"
            if limit is not None:
                return min(rate, limit / TURNS_REF), f"{why}（限 {limit} 次）", "medium"
            return rate, why, conf
    return 1.0 / TURNS_REF, "一次性（按 15 回合摊）", "low"


def _amount(t: str, kind: str) -> Tuple[int, int]:
    """(每次触发的金币数, 每次触发的法术数) —— 粗估：取文本里第一个数字。"""
    low = t.lower()
    gold = 0
    m = re.search(r"gain (\d+) gold", low)
    if m:
        gold = int(m.group(1))
    elif "gain gold" in low or "gold for each" in low:
        gold = 1
    m = re.search(r"increase your maximum gold by (\d+)", low)
    if m:
        gold = max(gold, int(m.group(1)))
    if "for each different friendly minion type" in low:
        gold = max(gold, 3)          # 大厅 5 个种族，场上通常 3 种
    spells = 0
    m = re.search(r"(?:get|discover|add) (\d+) (?:random )?(?:tavern )?spells?", low)
    if m:
        spells = int(m.group(1))
    elif _SPELL_GEN.search(t):
        spells = 1
    return gold, spells


def classify(c: Dict[str, Any]) -> Tuple[List[str], Dict[str, Any]]:
    """给一张卡打上收入类别 + 预估。返回 (categories, estimate)。"""
    t = _text(c)
    kind = str(c.get("kind") or "")
    cats: List[str] = []
    gold, spells = _amount(t, kind)
    mult, why, conf = _multiplier(t)
    if gold > 0 and _GOLD_GEN.search(t):
        cats.append("gold")
    if spells > 0 and _SPELL_GEN.search(t):
        cats.append("spell_gen")
    if _SPELL_AMP.search(t):
        cats.append("spell_amp")
    if _TAVERN_BUFF.search(t):
        cats.append("tavern_buff")
    est = {
        "trigger_per_turn": round(mult, 3),
        "trigger_rule": why,
        "est_gold_per_turn": round(gold * mult, 2),
        "est_spells_per_turn": round(spells * mult, 2),
        "confidence": conf,
    }
    return cats, est


#: 类别 → 中文名（写进 JSON/文档）
CATEGORY_ZH = {
    "gold": "金币生成",
    "spell_gen": "法术生成",
    "spell_amp": "法术放大",
    "tavern_buff": "酒馆永久 buff",
}

#: 参与清单的卡种（只保留「可能在沙盒里出现」的：trinket / tavern_spell / minion / hero_power）
INVENTORY_KINDS = ("trinket_lesser", "trinket_greater", "tavern_spell", "spell",
                   "minion", "hero_power")


def inventory() -> Dict[str, Any]:
    """金币/法术生成机制清单（含预估每回合收入）。"""
    cat = _catalog()
    cards: List[Dict[str, Any]] = []
    for cid, c in cat.items():
        kind = str(c.get("kind") or "")
        if kind not in INVENTORY_KINDS:
            continue
        cats, est = classify(c)
        if not cats:
            continue
        # 只留可达 / 在池 / 已实现的（其余是历史卡或未实现桩）
        if not (c.get("implemented") and c.get("reachable")):
            continue
        cards.append({
            "id": cid, "name": c.get("name"), "name_zh": c.get("name_zh"),
            "kind": kind, "tier": int(c.get("tier") or 0),
            "cost": c.get("cost"), "in_pool": bool(c.get("in_pool")),
            "scripted": bool(c.get("scripted")), "implemented": bool(c.get("implemented")),
            "categories": cats, "text": _text(c), "text_zh": c.get("text_zh"),
            **est,
        })
    # 汇总：按类别 / 按卡种的计数 + 预估收入
    by_cat: Dict[str, List[str]] = {}
    for r in cards:
        for c in r["categories"]:
            by_cat.setdefault(c, []).append(r["id"])
    summary = {
        "cards_total": len(cards),
        "by_category": {k: {"n": len(v), "ids": sorted(v)} for k, v in by_cat.items()},
        "by_kind": dict(Counter(r["kind"] for r in cards)),
        "est_gold_per_turn_top": sorted(
            ({"id": r["id"], "name": r["name"], "kind": r["kind"],
              "est_gold_per_turn": r["est_gold_per_turn"],
              "est_spells_per_turn": r["est_spells_per_turn"],
              "confidence": r["confidence"]} for r in cards),
            key=lambda x: -(x["est_gold_per_turn"] or 0))[:15],
        "est_spells_per_turn_top": sorted(
            ({"id": r["id"], "name": r["name"], "kind": r["kind"],
              "est_spells_per_turn": r["est_spells_per_turn"],
              "est_gold_per_turn": r["est_gold_per_turn"],
              "confidence": r["confidence"]} for r in cards),
            key=lambda x: -(x["est_spells_per_turn"] or 0))[:15],
    }
    # 机制级条目（不是单张卡）：三连奖励 / 酒馆永久 buff 的乘性来源
    mechanics = [
        {"id": "_triple_reward",
         "name": "Triple reward（三连奖励 / 金色卡）",
         "text": "3 张同名 → 金色（身材 ×2、金色效果）+ Discover 一张高 1 级的随从",
         "engine": "recruit.rs::merge_golden + content::triple_reward_item；"
                   "``stats.tavern_*`` 之外的另一条乘性来源：真实高强战团 62.1% 身材来自 ``_G``",
         "est_note": "每回合能拿到的三连数 ∝ 买牌数（金币）× 池子宽度；金币翻倍时线性增长"},
        {"id": "_tavern_buff",
         "name": "酒馆永久 buff（tavern_atk/tavern_hp）",
         "text": "「使酒馆中的随从本局 +X/+Y」类效果：每张被 buff 的酒馆随从把增益永久带进战团",
         "engine": "``stats.tavern_atk``/``tavern_hp``（measure() 的 ``tavern_buff``）；"
                   "乘性在于「每回合买 N 张 = N 份永久 buff」叠加",
         "est_note": f"清单里 tavern_buff 类卡 {summary['by_category'].get('tavern_buff', {}).get('n', 0)} 张"},
    ]
    return {
        "method": {
            "gold_estimate": "est_gold_per_turn = 单次金币数 × 每回合触发次数（一次性效果按 1/15 摊）",
            "spell_estimate": "est_spells_per_turn = 单次法术数 × 每回合触发次数",
            "trigger_rates": {why: rate for _p, rate, why in _TRIGGERS},
            "caveat": "粗估（假设每次触发都命中）；真实值由三档探针实测，见 arms",
        },
        "summary": summary,
        "cards": sorted(cards, key=lambda r: (r["kind"], -float(r["est_gold_per_turn"] or 0),
                                              -float(r["est_spells_per_turn"] or 0))),
        "mechanics": mechanics,
    }


# ── 探针策略：在基线 spell 脚本上，优先金币/法术生成 ────────────────────────

class IncomePolicy(ScriptPolicy):
    """基线 ``spell`` 脚本 + 两类偏好（可分别关掉，用来做三档归因）。

    * ``trinket_classes``：饰品候选里优先这些类别的卡（``gold`` > ``spell_gen`` >
      ``spell_amp``，同级取更便宜的）；
    * ``buy_income``：酒馆里有金币/法术生成牌时优先买（**不清空基线策略**：
      满场且身材不占优时不做替换，避免为了收入把战团拆了）。
    """

    def __init__(self, *, trinket_classes: Sequence[str] = (), buy_income: bool = False,
                 unlock_refresh: bool = False, **kw: Any):
        super().__init__(**kw)
        self.trinket_classes = list(trinket_classes)
        self.buy_income = bool(buy_income)
        self.unlock_refresh = bool(unlock_refresh)
        self.offered_trinkets: List[str] = []
        self.picked_trinkets: List[str] = []
        self.gold_ids: Dict[str, int] = {}
        self.spell_ids: Dict[str, int] = {}
        for cid, c in _catalog().items():
            if not (c.get("implemented") and c.get("reachable")):
                continue
            cats, _est = classify(c)
            if "gold" in cats:
                self.gold_ids[cid] = 3
            if "spell_gen" in cats:
                self.spell_ids[cid] = 1

    # -- 饰品：按类别优先 ------------------------------------------------------
    def _trinket_value(self, cid: str) -> float:
        """按清单里的预估给饰品排序（金币 > 法术 > 放大；都用「每回合额外」折算）。"""
        if not self.trinket_classes:
            return 0.0
        cats, est = classify(card_of(cid))
        if not any(c in cats for c in self.trinket_classes):
            return 0.0
        v = 0.0
        if "gold" in self.trinket_classes and "gold" in cats:
            v += 3.0 + float(est["est_gold_per_turn"])
        if "spell_gen" in self.trinket_classes and "spell_gen" in cats:
            v += 2.0 + float(est["est_spells_per_turn"])
        if "spell_amp" in self.trinket_classes and "spell_amp" in cats:
            v += 1.0
        return v

    def _pending(self, v, seat, pend):
        if pend.get("kind") == "trinket":
            opts = pend.get("options") or []
            self.offered_trinkets.extend(
                str(o.get("id") or "") for o in opts if isinstance(o, dict))
            if self.trinket_classes:
                mask = v["mask"]
                legal = [i for i in range(N_CHOICE) if mask[A_CHOOSE + i]]
                gold = int((v["me"] or {}).get("gold") or 0)
                best = None
                for i in legal:
                    if i >= len(opts) or not isinstance(opts[i], dict):
                        continue
                    cost = int(opts[i].get("cost") or 0)
                    if cost > gold:
                        continue
                    sc = self._trinket_value(str(opts[i].get("id") or ""))
                    cand = (sc, -cost, -i)
                    if best is None or cand > best[0]:
                        best = (cand, i)
                if best is not None and best[0][0] > 0:
                    return A_CHOOSE + best[1]
        return super()._pending(v, seat, pend)

    # -- 买牌：优先金币/法术生成 ----------------------------------------------
    def _recruit(self, v, me, mask):
        if self.unlock_refresh:
            gold = int(me.get("gold") or 0)
            # 钱多时解除 ScriptPolicy 的「每局 40 次刷新」上限：否则 growth 模式下
            # 多出来的金币根本花不出去（酒馆每轮只有 7 张牌），会把「收入没用」误读成
            # 「环境没有复利」。只在 gold 富余时松绑，基线行为不变。
            if gold >= 30 and self.refreshes >= 39:
                self.refreshes = 39
        if self.buy_income:
            a = self._income_buy(me, mask)
            if a is not None:
                return a
        return super()._recruit(v, me, mask)

    def _income_buy(self, me, mask) -> Optional[int]:
        gold = int(me.get("gold") or 0)
        shop = me.get("shop") or []
        board = me.get("board") or []
        cands = []
        for i in range(8):
            a = A_BUY + i
            if not (0 <= a < 245 and bool(mask[a])) or i >= len(shop):
                continue
            it = shop[i]
            if not isinstance(it, dict):
                continue
            cid = str(it.get("id") or "")
            score = self.gold_ids.get(cid, 0) or self.spell_ids.get(cid, 0)
            if not score:
                continue
            if gold < price_of(it):
                continue
            is_minion = str(it.get("type") or "") == "minion"
            if is_minion and len(board) >= N_BOARD:
                # 满场：只有身材明显更好才替换（收入卡优先于身材 -> 阈值放低）
                worst = min((minion_stats(m) for m in board), default=-1)
                if minion_stats(it) < worst - 2:
                    continue
            cands.append((score, minion_stats(it) if is_minion else 0, -i, i))
        if not cands:
            return None
        cands.sort(reverse=True)
        best = cands[0]
        if str(shop[best[3]].get("type") or "") == "minion" and len(board) >= N_BOARD:
            worst_i = min(range(len(board)), key=lambda k: minion_stats(board[k]))
            if not (0 <= A_SELL + worst_i < 245 and bool(mask[A_SELL + worst_i])):
                return None
            return A_SELL + worst_i
        return A_BUY + best[3]


# ── 档位定义 ────────────────────────────────────────────────────────────────

class IncomeSandboxPolicies(SandboxPolicies):
    """``SandboxPolicies(kind='spell')`` 的包装：把内部 ``ScriptPolicy`` 换成
    :class:`IncomePolicy`（同样走 ``_pending``/``_recruit`` 两条路径，**不经过**
    ``ScriptPolicy.act`` 的 120 次总动作门 — 那个门是 ceiling probe 自己的口径）。
    """

    def __init__(self, game: Any, *, trinket_classes: Sequence[str] = (),
                 buy_income: bool = False, unlock_refresh: bool = False, seed: int = 0):
        super().__init__(game, "spell", seed=seed)
        self._script = IncomePolicy(mode="spell", curve="mid",
                                    trinket_classes=trinket_classes,
                                    buy_income=buy_income,
                                    unlock_refresh=unlock_refresh)

    @property
    def script(self) -> IncomePolicy:
        return self._script

#: 引擎口径的「不覆写金币」配置：自然补币固定 30/回合（start_gold=30, increment=0）
_ENGINE_30 = (("start_gold", GOLD_REF), ("gold_increment", 0), ("gold_refill_cap", 99))

ARMS: Dict[str, Dict[str, Any]] = {
    "I0": {
        "desc": "现状：每回合重置 30 金（fixed）；基线 spell 脚本；饰品取第一个买得起的",
        "cfg": dict(gold_mode="fixed", gold_per_turn=GOLD_REF),
        "policy": dict(trinket_classes=(), buy_income=False),
    },
    "I0u": {
        "desc": "现状 + 不早结束（解除脚本每局 40 次刷新上限）：隔离「刷新上限」本身的影响",
        "cfg": dict(gold_mode="fixed", gold_per_turn=GOLD_REF),
        "policy": dict(trinket_classes=(), buy_income=False, unlock_refresh=True),
    },
    "I0e": {
        "desc": "对照：引擎自然补币 30/回合（不覆写）；基线 spell 脚本；饰品同 I0",
        "cfg": dict(gold_mode="add", gold_per_turn=0, extra=_ENGINE_30),
        "policy": dict(trinket_classes=(), buy_income=False, unlock_refresh=True),
    },
    "I1": {
        "desc": "I0e + 饰品优先「金币生成」类（禁止其他类别的加分）",
        "cfg": dict(gold_mode="add", gold_per_turn=0, extra=_ENGINE_30),
        "policy": dict(trinket_classes=("gold",), buy_income=False, unlock_refresh=True),
    },
    "I2": {
        "desc": "I1 + 法术生成/放大饰品 + 优先买金币/法术生成牌（保持手牌有法术配合载体）",
        "cfg": dict(gold_mode="add", gold_per_turn=0, extra=_ENGINE_30),
        "policy": dict(trinket_classes=("gold", "spell_gen", "spell_amp"),
                       buy_income=True, unlock_refresh=True),
    },
    "I3": {
        "desc": "复利收入：growth 0.15 + per_carrier 2（cap 99）+ I2 的偏好（沙盒侧收入不覆写引擎）",
        "cfg": dict(gold_mode="growth", gold_per_turn=GOLD_REF, gold_growth_rate=0.15,
                    gold_per_carrier=2, gold_cap=99),
        "policy": dict(trinket_classes=("gold", "spell_gen", "spell_amp"),
                       buy_income=True, unlock_refresh=True),
    },
    "I4": {
        "desc": "上界 A：growth 0.35 + per_carrier 2 + 无金币上限 + 动作额度 120，"
                "策略只用 spell 基线（不专门买收入牌；实测「为收入买牌」反而挤掉载体）",
        "cfg": dict(gold_mode="growth", gold_per_turn=GOLD_REF, gold_growth_rate=0.35,
                    gold_per_carrier=2, gold_cap=0, action_cap=120),
        "policy": dict(trinket_classes=("gold", "spell_gen", "spell_amp"),
                       buy_income=False, unlock_refresh=True),
    },
    "I5": {
        "desc": "上界 B：growth 0.45 + per_carrier 2 + 无金币上限 + 动作额度 120"
                "（找「t12→t15 ≥3×」需要多快的收入增长）",
        "cfg": dict(gold_mode="growth", gold_per_turn=GOLD_REF, gold_growth_rate=0.45,
                    gold_per_carrier=2, gold_cap=0, action_cap=120),
        "policy": dict(trinket_classes=("gold", "spell_gen", "spell_amp"),
                       buy_income=False, unlock_refresh=True),
    },
}


def _arm_cfg(name: str) -> SandboxConfig:
    kw = dict(turns=TURNS_REF, action_cap=40, trinkets=True, reward="log_strength")
    kw.update(ARMS[name]["cfg"])
    return SandboxConfig(**kw)


def run_games(arm: str, seeds: Sequence[int]) -> List[Dict[str, Any]]:
    """跑一批种子，返回每局 episode_summary（+ 饰品报价/命中统计）。"""
    cfg = _arm_cfg(arm)
    pol_kw = ARMS[arm]["policy"]
    out: List[Dict[str, Any]] = []
    for s in seeds:
        env = EconomySandbox(cfg)
        obs = env.reset(int(s))
        pol = IncomeSandboxPolicies(env.g, seed=0, **pol_kw)
        steps = 0
        while not env.done:
            a = pol.act(env.g, obs.mask)
            obs, _r, _d, _info = env.step(int(a))
            steps += 1
        ep = dict(env.episode_summary())
        ep["decisions"] = steps
        ep["return"] = 0.0
        ep["arm"] = arm
        ep["offered_trinkets"] = sorted(set(pol.script.offered_trinkets))
        ep["picked_trinkets"] = list(ep.get("trinket_ids") or [])
        out.append(ep)
    return out


def _gold_ids() -> Dict[str, int]:
    cat = _catalog()
    out = {}
    for cid, c in cat.items():
        if not (c.get("implemented") and c.get("reachable")):
            continue
        cats, _ = classify(c)
        if "gold" in cats:
            out[cid] = 1
    return out


def _spell_ids() -> Dict[str, int]:
    cat = _catalog()
    out = {}
    for cid, c in cat.items():
        if not (c.get("implemented") and c.get("reachable")):
            continue
        cats, _ = classify(c)
        if "spell_gen" in cats:
            out[cid] = 1
    return out


def aggregate(arm: str, eps: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """一档的汇总（在 summarize 之上补收入/饰品命中口径）。"""
    rep = summarize(eps)
    gi = [float(e.get("gold_total_income") or 0) for e in eps]
    s12 = [float(e.get("sigma_t12") or 0) for e in eps]
    s15 = [float(e.get("sigma_t15") or 0) for e in eps]
    gold_ids = _gold_ids()
    spell_ids = _spell_ids()

    def _rate(fn) -> float:
        return float(np.mean([1.0 if fn(e) else 0.0 for e in eps])) if eps else 0.0

    rep.update({
        "arm": arm,
        "desc": ARMS[arm]["desc"],
        "games": len(eps),
        "gold_total_income_p50": rep.get("gold_total_income_p50"),
        "gold_total_income_mean": rep.get("gold_total_income_mean"),
        "gold_income_ratio": (float(np.mean(gi)) / BASE_GOLD_TOTAL) if gi else 0.0,
        "sigma12_per_gold_p50": rep.get("sigma12_per_gold_p50"),
        "sigma15_per_gold_p50": rep.get("sigma15_per_gold_p50"),
        "sigma12_per_gold_mean": float(np.mean(
            [a / b for a, b in zip(s12, gi) if b > 0])) if gi else 0.0,
        "golden_trinket_offer_rate": _rate(
            lambda e: any(x in gold_ids for x in (e.get("offered_trinkets") or ()))),
        "golden_trinket_pick_rate": _rate(
            lambda e: any(x in gold_ids for x in (e.get("picked_trinkets") or ()))),
        "spell_trinket_pick_rate": _rate(
            lambda e: any(x in spell_ids for x in (e.get("picked_trinkets") or ()))),
        # 重尾读数：t15 Σ 的分布（p50 是主判据，但「能否摸到人类量级」看尾）
        "t15_p99": float(np.percentile(np.asarray(s15, dtype=np.float64), 99))
        if s15 else 0.0,
        "t15_ge_4k_rate": float(np.mean([1.0 if v >= 4000 else 0.0 for v in s15]))
        if s15 else 0.0,
        "t15_ge_10k_rate": float(np.mean([1.0 if v >= 10000 else 0.0 for v in s15]))
        if s15 else 0.0,
    })
    return rep


def _chunks(items: Sequence[int], n: int) -> List[List[int]]:
    k = max(1, int(math.ceil(len(items) / max(1, n))))
    return [list(items[i:i + k]) for i in range(0, len(items), k)]


def _worker(task):
    arm, seeds = task
    return arm, run_games(arm, seeds)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="收入机制探针（脚本策略，纯 CPU）")
    ap.add_argument("--games", type=int, default=200, help="每档局数（默认 200）")
    ap.add_argument("--seed", type=int, default=810000)
    ap.add_argument("--arms", default="I0,I0u,I0e,I1,I2,I3,I4,I5")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--inventory-only", action="store_true")
    ap.add_argument("--json-out", default="runs/comp_lines/income_probe.json")
    args = ap.parse_args(argv)

    inv = inventory()
    print(f"[inventory] {inv['summary']['cards_total']} 张相关卡；"
          f"类别 {[(k, v['n']) for k, v in inv['summary']['by_category'].items()]}")
    for r in inv["summary"]["est_gold_per_turn_top"][:8]:
        print(f"  gold {r['est_gold_per_turn']:5.2f}/turn  spell {r['est_spells_per_turn']:4.2f}"
              f"  {r['kind']:16s} {r['id']:22s} {r['name']}")
    if args.inventory_only:
        if args.json_out:
            os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
            with open(args.json_out, "w", encoding="utf-8") as f:
                json.dump(inv, f, ensure_ascii=False, indent=1)
            print(f"[inventory] → {args.json_out}")
        return 0

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for a in arms:
        if a not in ARMS:
            raise SystemExit(f"未知档位 {a!r}（可选 {sorted(ARMS)}）")
    seeds = [int(args.seed) + i for i in range(int(args.games))]
    tasks = [(a, c) for a in arms for c in _chunks(seeds, max(1, int(args.workers)))]
    t0 = time.perf_counter()
    eps_by_arm: Dict[str, List[Dict[str, Any]]] = {a: [] for a in arms}
    if int(args.workers) > 1:
        ctx = mp.get_context("fork")
        with ctx.Pool(int(args.workers)) as pool:
            for arm, eps in pool.imap_unordered(_worker, tasks):
                eps_by_arm[arm].extend(eps)
                print(f"  [{arm}] +{len(eps)} 局 ({len(eps_by_arm[arm])}/{len(seeds)}) "
                      f"{time.perf_counter() - t0:.0f}s", flush=True)
    else:
        for task in tasks:
            arm, eps = _worker(task)
            eps_by_arm[arm].extend(eps)
    arms_rep = {}
    print(f"\n{'arm':5s} {'t12 p50':>8s} {'t15 p50':>8s} {'Σ12/金':>7s} {'gold':>6s} "
          f"{'r12_15':>6s} {'goldens':>7s} {'spells':>6s} {'trk_gold':>8s} {'kind'}")
    for a in arms:
        rep = aggregate(a, eps_by_arm[a])
        arms_rep[a] = rep
        print(f"{a:5s} {rep['sigma_t12_p50']:8.0f} {rep['sigma_t15_p50']:8.0f} "
              f"{rep.get('sigma12_per_gold_p50') or 0:7.2f} "
              f"{rep.get('gold_total_income_p50') or 0:6.0f} "
              f"{rep.get('growth_ratio_12_15_p50') or 0:6.2f} "
              f"{rep.get('goldens_p50') or 0:7.0f} {rep['spells_p50']:6.0f} "
              f"{rep['golden_trinket_pick_rate']:8.2f} {a}")
    best = max(arms_rep.values(), key=lambda r: float(r.get("sigma12_per_gold_p50") or 0))
    print(f"\n[verdict] 最高 Σ12/金币 = {best.get('sigma12_per_gold_p50'):.2f} "
          f"@ {best['arm']}（基线 2.9；真实 9.9；判据 ≥6，<4 视为引擎经济上限不足）")
    if args.json_out:
        out = os.path.abspath(args.json_out)
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        payload = {
            "meta": {"generated_by": "scripts/income_probe.py",
                     "games_per_arm": int(args.games), "seed0": int(args.seed),
                     "workers": int(args.workers), "turns": TURNS_REF,
                     "gold_ref": GOLD_REF, "base_gold_total": BASE_GOLD_TOTAL,
                     "seconds": round(time.perf_counter() - t0, 1),
                     "note": "脚本策略（spell 基线 + 收入偏好）下的三档收入探针"},
            "inventory": inv,
            "arms": arms_rep,
            "verdict": {"best_arm": best["arm"],
                        "best_sigma12_per_gold": best.get("sigma12_per_gold_p50"),
                        "baseline": 2.9, "real_10k": 9.9,
                        "target": 6.0, "floor": 4.0},
        }
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print(f"[probe] → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
