#!/usr/bin/env python3
"""复利链条（compound chains）文本挖矿：从**卡牌文本**里挖出「乘数 / 累加 / 触发链」核心牌。

动机
====
用户洞察（``docs/COMPOUND_CHAINS.md`` §1）：酒馆战棋的强度不是线性的，而是**复利**的。
复利链条只有两大类：

1. **乘数效应**（multiplier）：某个效果「每触发一次就再乘一层」。
   文本证据：``double`` / ``triple`` / ``twice`` / ``for each`` / ``each time`` /
   ``every time`` / ``repeat for each``。典型：``Your end of turn effects trigger
   twice``、``Has +7/+7 for each Golden minion you've played this game``。
2. **几何级数 / 累加**（accumulator）：一次性把某个量**永久**抬高一格，之后每次触发都
   从更高的基线起步。文本证据：``permanently`` / ``this game`` / ``an extra +1/+1`` /
   ``consume`` / ``grow`` / ``increase`` / ``improved by``。典型：
   ``Whenever you cast a Tavern spell, give Elementals in the Tavern +4/+3 this game.``
   —— 法术越多，之后买的每一只元素都更强（``data/scaling/carriers.json`` 的 11 张载体）。

第 3 类 ``trigger_chain``（``whenever you`` / ``after you`` / ``Rally`` / ``Deathrattle`` /
``Battlecry`` / ``Avenge``）本身不产生复利，但它是「让乘数/累加**多次**触发」的**引信**，
所以单独记一类，用较低权重进入打分。

产出
====
``data/scaling/compound_cards.json``：

- ``cards``：命中的卡（并集）逐张记录 —— tier / 种族 / kind / 是否在池 / 是否已实现 /
  命中类 / 各规则命中次数 / 分数分解 / 文本片段；
- ``by_class``：三类各自的 id 清单；
- ``core``：**流派核心牌集**（``core = tier<=5 + 在池 + 已实现 + 该组内分数最强``）：
  ``by_tribe``（11 个种族）、``by_archetype``（``archetype_table.json`` 的 17 个头部流派）、
  ``global``（通用核心）、``common_ids``（出现在 >=2 组核心集里的「公用牌」）；
- ``carrier_overlap``：与 ``data/scaling/carriers.json`` 的重叠（这是先验最该抓的那批）；
- ``meta``：各类数量、按种族分布、规则表版本。

口径（硬约束）
--------------
- 数据源：``rust/crates/hsbg-engine/data/cards.json``（文本/种族/tier）+
  ``hsbg_engine.catalog_json()``（``in_pool`` / ``implemented`` / ``tier7``，运行时可用性）。
  引擎不可用时退化为「只有卡表」（``--no-engine``，此时 ``in_pool`` 记为 None）。
- **纯文本挖矿**：不改引擎、不训练、不写 checkpoint；同一输入逐位确定（``--check`` 幂等）。
- 核心牌集只从 ``kind == "minion"`` 里选（随从才是「买来站场」的载体；法术/饰品/任务
  进三类清单但**不进**核心集，避免先验把金币投到一次性牌上）。

用法
----
    python scripts/mine_compound_cards.py                 # 写 data/scaling/compound_cards.json
    python scripts/mine_compound_cards.py --report        # 额外打印 markdown 摘要
    python scripts/mine_compound_cards.py --check         # 幂等自检（不落盘）
    python scripts/mine_compound_cards.py --max-core 8    # 每组核心牌上限
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARDS_JSON = os.path.join(ROOT, "rust", "crates", "hsbg-engine", "data", "cards.json")
OUT_JSON = os.path.join(ROOT, "data", "scaling", "compound_cards.json")
CARRIERS_JSON = os.path.join(ROOT, "data", "scaling", "carriers.json")
ARCH_TABLE = os.path.join(ROOT, "data", "archetype", "archetype_table.json")

#: 规则表版本：改动任何正则/权重都必须自增（写进 meta，读取方校验）。
RULES_VERSION = 1

# ══════════════════════════════════════════════════════════════════════════
# 1. 规则表（正则 + 权重）
# ══════════════════════════════════════════════════════════════════════════
# 每条 = (name, 英文正则, 中文正则, 权重, 说明)。英文在 ``text.lower()`` 上匹配，
# 中文在 ``text_zh`` 原文上匹配；两条任一命中即算命中（双重取证，与 carrier_common 同口径）。
Rule = Tuple[str, str, str, float, str]

#: **乘数效应**：每触发一次就再乘一层。
MULTIPLIER_RULES: Tuple[Rule, ...] = (
    ("triple", r"\btriple[sd]?\b(?! reward)", r"三倍", 4.0, "三倍（最强乘数）"),
    ("double", r"\bdouble[sd]?\b", r"双倍", 3.0, "双倍"),
    ("repeat_for_each", r"\brepeat (?:this )?(?:for|once for) each\b",
     r"每有一个就重复|重复.*每", 3.0, "按数量重复（几何级数）"),
    ("twice", r"\btwice\b", r"两次", 2.5, "触发两次"),
    ("for_each", r"\bfor each\b", r"每个|每有", 2.0, "按数量线性乘"),
    ("each_time", r"\beach time\b", r"每次", 2.0, "每次触发"),
    ("every_time", r"\bevery time\b", r"每一次", 2.0, "每次触发"),
    ("for_every", r"\bfor every\b", r"每有一?个", 2.0, "按数量线性乘"),
    ("per_each", r"\bper (?:each )?(?:friendly |golden )?", r"每有", 1.0,
     "per 计数（弱乘数）"),
)

#: **累加 / 几何级数**：把某个量永久抬高，之后每次触发从更高基线起步。
ACCUMULATOR_RULES: Tuple[Rule, ...] = (
    ("permanently", r"\bpermanent(?:ly)?\b", r"永久", 3.0, "永久（不随回合衰减）"),
    ("this_game", r"\bthis game\b", r"本局对战", 3.0, "本局永久（跨回合复利）"),
    ("an_extra", r"\ban extra \+", r"额外(?:获得|给)?\+", 2.5, "乘法增量（'an extra +1/+1'）"),
    ("improved_by", r"\bimprove[sd]? (?:this|by)\b", r"提高|增强", 2.5,
     "永久改进（每次触发 +1 层）"),
    ("consume", r"\bconsume[sd]?\b", r"消耗", 2.5, "consume 吞噬身材（累加）"),
    ("this_gains", r"\bthis (?:minion )?gain(?:s)?\b", r"本随从(?:便)?获得", 2.5,
     "本随从获得（自成长）"),
    ("blood_gem_extra", r"blood gems? give an extra", r"血宝石.*额外", 2.5,
     "血宝石永久加成（几何级数）"),
    ("keeps_gained", r"\bkeep(?:s)? (?:bonus keywords|\S+ \S+ \S+)\b",
     r"永久保留", 2.0, "永久保留战斗中获得的身材/关键词"),
    ("gain_xx", r"gain(?:s)? \+(\d+)/\+(\d+)", r"获得\+(\d+)/\+(\d+)", 2.0,
     "获得 +X/+X（幅度进分数）"),
    ("grow", r"\bgrow(?:s|n)?\b", r"成长", 2.0, "grow/成长"),
    ("increase", r"\bincrease[sd]?\b", r"提高|增加", 1.5, "increase（上限/数值）"),
    ("golden_keep", r"\bgolden ones? keep\b", r"金色.*永久", 2.0, "金色永久保留"),
)

#: **触发链**（引信）：让乘数/累加多次触发，本身不产生复利 → 低权重。
TRIGGER_RULES: Tuple[Rule, ...] = (
    ("whenever_you", r"\bwhenever you\b", r"每当你", 2.0, "每当你…（高频触发）"),
    ("rally", r"\brally\b", r"集结", 2.0, "Rally 集结（每次攻击触发）"),
    ("avenge", r"\bavenge\b", r"复仇", 2.0, "Avenge 复仇（死亡触发）"),
    ("whenever_friendly", r"\bwhenever a friendly\b|\bwhenever an? \w+ (?:dies|attacks)\b",
     r"每当一个友方", 1.5, "每当友方…"),
    ("after_you", r"\bafter you\b", r"在(?:你|你使用|你施放).*之后", 1.5, "在你…之后"),
    ("deathrattle", r"\bdeathrattle\b", r"亡语", 1.5, "亡语"),
    ("battlecry", r"\bbattlecry\b", r"战吼", 1.0, "战吼"),
    ("end_of_turn", r"\bend of (?:your |each )?turn\b", r"回合结束时", 1.0, "回合结束时"),
    ("start_of_combat", r"\bstart of combat\b", r"战斗开始时", 1.0, "战斗开始时"),
    ("activate", r"\bactivate\b", r"激活", 1.0, "Activate（主动触发）"),
)

#: **噪声模式**：文本里这些短语会让「乘数/累加」的正则误命中，但它们描述的是
#: **经济/奖励**机制（金币上限、用血量支付、三连奖励、发现），不产生战斗复利。
#: 命中一次把分数乘 ``NOISE_PENALTY``，并标记 ``noise: true``（核心牌集排除）。
NOISE_RULES: Tuple[Tuple[str, str], ...] = (
    ("max_gold", r"\bmaximum gold\b|铸币上限"),
    ("health_cost", r"costs? health instead of gold|消耗生命值，而非铸币"),
    ("triple_reward", r"triple reward|三连奖励"),
    ("discover", r"^\s*discover|\bdiscover a\b|发现一张"),
    ("bounty", r"\bbounties\b|悬赏令"),
)
NOISE_PENALTY = 0.25

#: 机制分组（用于 ``by_mechanism`` 与流派核心牌的机制加成）。
MECHANISM_RULES: Tuple[Tuple[str, str, str], ...] = (
    ("deathrattle", r"\bdeathrattle\b", r"亡语"),
    ("battlecry", r"\bbattlecry\b", r"战吼"),
    ("rally", r"\brally\b", r"集结"),
    ("avenge", r"\bavenge\b", r"复仇"),
    ("choose_one", r"\bchoose one\b", r"抉择"),
    ("spell_scaling", r"\btavern spell\b|\bcast a spell\b|\bspells?\b(?: you cast)?",
     r"酒馆法术|施放法术"),
    ("tavern_buff", r"\bminions in the tavern\b", r"酒馆中的随从"),
    ("blood_gem", r"\bblood gems?\b", r"血宝石"),
    ("consume", r"\bconsume[sd]?\b", r"消耗"),
    ("discard", r"\bdiscard", r"弃"),
    ("golden", r"\bgolden\b", r"金色"),
    ("end_of_turn", r"\bend of your turn\b", r"回合结束时"),
    ("magnetic", r"\bmagnetic\b", r"磁力"),
    ("divine_shield", r"\bdivine shield\b", r"圣盾"),
    ("self_damage", r"\bdamage\b", r"伤害"),
)

#: 权重（分数 = 三类的加权和；乘数/累加是复利本体，触发链只是引信）。
W_MULT = 1.0
W_ACC = 1.0
W_TRIG = 0.35
#: 幅度归一：``+X/+X`` 的 (X+Y) 除以该值进分，上限 :data:`MAG_CAP`。
MAG_SCALE = 10.0
MAG_CAP = 3.0
#: tier 可得性加成（tier 越低越早成型）：``1 + TIER_W * max(0, 6 - tier)``。
TIER_W = 0.10
#: 核心牌集的硬门槛。
CORE_MAX_TIER = 5

#: archetype 名字里的机制线索 → 机制组（用于给流派核心牌排序时加成）。
ARCH_MECHANISM_TOKENS: Tuple[Tuple[str, str], ...] = (
    ("deathrattle", "deathrattle"), ("butcher", "deathrattle"),
    ("eternal_knight", "deathrattle"), ("choose_one", "choose_one"),
    ("gem", "blood_gem"), ("felboar", "spell_scaling"), ("lobster", "spell_scaling"),
    ("azerite", "elemental_tavern"), ("boost_shop", "tavern_buff"),
    ("self_damage", "self_damage"), ("shield", "divine_shield"),
    ("apm", "magnetic"), ("volumizer", "magnetic"), ("discover", "golden"),
    ("scam", "battlecry"), ("tea_set", "spell_scaling"), ("kalecgos", "spell_scaling"),
)


# ══════════════════════════════════════════════════════════════════════════
# 2. 数据载入
# ══════════════════════════════════════════════════════════════════════════
def load_cards(path: str = CARDS_JSON) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    cards = d["cards"] if isinstance(d, dict) else d
    return {"meta": (d.get("meta") if isinstance(d, dict) else {}) or {},
            "cards": list(cards)}


def load_catalog(*, use_engine: bool = True) -> Dict[str, Dict[str, Any]]:
    """``id -> {in_pool, implemented, tier7, ...}``（引擎 ``catalog_json``）。

    引擎不可用时返回 ``{}``（此时 ``in_pool`` 记为 ``None``，核心集退化为「卡表全量」，
    但统计口径会显式标注 ``engine: false``，避免把两套口径混着比）。
    """
    if not use_engine:
        return {}
    try:
        import hsbg_engine as E  # type: ignore  # noqa: PLC0415
        raw = E.catalog_json()
        rows = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:  # noqa: BLE001 - 引擎缺失/未编译都退化为纯文本
        return {}
    return {str(x.get("id")): x for x in rows if isinstance(x, dict)}


# ══════════════════════════════════════════════════════════════════════════
# 3. 文本挖矿
# ══════════════════════════════════════════════════════════════════════════
def _snippet(text: str, m: "re.Match[str]", *, width: int = 46) -> str:
    """取命中位置附近的一段（尽量对齐到句号/分号边界），用于文档引用。"""
    s = max(0, int(m.start()) - width)
    e = min(len(text), int(m.end()) + width)
    frag = text[s:e].strip()
    if s > 0:
        cut = max(frag.rfind(". "), frag.rfind("; "))
        if 0 <= cut < len(frag) // 2:
            frag = frag[cut + 2:]
        elif frag:
            frag = "…" + frag
    if e < len(text) and frag:
        frag += "…"
    return frag


def match_rules(text_en: str, text_zh: str,
                rules: Sequence[Rule]) -> Tuple[float, Dict[str, int], List[str]]:
    """按规则表匹配一段卡牌文本：返回 ``(加权分, {规则名: 命中次数}, 片段列表)``。"""
    low = str(text_en or "").lower()
    zh = str(text_zh or "")
    score = 0.0
    hits: Dict[str, int] = {}
    frags: List[str] = []
    for name, pat_en, pat_zh, w, _note in rules:
        n = 0
        for m in re.finditer(pat_en, low):
            n += 1
            if len(frags) < 1:          # 每类只留 1 句证据（控制 JSON 体积）
                frags.append(_snippet(str(text_en or ""), m))
        for m in re.finditer(pat_zh, zh):
            n += 1
            if len(frags) < 1:
                frags.append(_snippet(zh, m))
        if n:
            hits[name] = n
            score += float(w) * min(n, 3)          # 同类多次命中有边际递减
    return score, hits, frags


def buff_magnitude(text_en: str, text_zh: str) -> int:
    """抽取文本里最大的 ``+X/+Y`` 幅度（X+Y）；没有则 0。"""
    best = 0
    for src in (str(text_en or ""), str(text_zh or "")):
        for m in re.finditer(r"\+(\d+)/\+(\d+)", src):
            best = max(best, int(m.group(1)) + int(m.group(2)))
    return best


def classify_card(card: Dict[str, Any], cat: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """单卡 → 命中记录（三类都未命中返回 ``None``）。"""
    cid = str(card.get("id") or "")
    en = str(card.get("text") or "")
    zh = str(card.get("text_zh") or "")
    m_score, m_hits, m_frag = match_rules(en, zh, MULTIPLIER_RULES)
    a_score, a_hits, a_frag = match_rules(en, zh, ACCUMULATOR_RULES)
    t_score, t_hits, t_frag = match_rules(en, zh, TRIGGER_RULES)
    if not (m_hits or a_hits or t_hits):
        return None
    info = cat.get(cid) or {}
    tier = int(card.get("tier") or 0)
    races = [str(r) for r in (card.get("races") or [])]
    kind = str(card.get("kind") or "")
    mag = buff_magnitude(en, zh)
    mag_score = min(MAG_CAP, float(mag) / MAG_SCALE)
    raw = W_MULT * (m_score + mag_score) + W_ACC * a_score + W_TRIG * t_score
    noise = sorted({name for name, pat in NOISE_RULES
                    if re.search(pat, en.lower()) or re.search(pat, zh)})
    if noise:
        raw *= NOISE_PENALTY
    tier_factor = 1.0 + TIER_W * max(0, 6 - tier) if tier > 0 else 1.0
    mechanisms = [name for name, pat_en, pat_zh in MECHANISM_RULES
                  if re.search(pat_en, en.lower()) or re.search(pat_zh, zh)]
    classes = []
    if m_hits:
        classes.append("multiplier")
    if a_hits:
        classes.append("accumulator")
    if t_hits:
        classes.append("trigger_chain")
    return {
        "id": cid,
        "name": str(card.get("name") or ""),
        "name_zh": str(card.get("name_zh") or ""),
        "tier": tier,
        "kind": kind,
        "races": races,
        "atk": int(card.get("atk") or 0),
        "hp": int(card.get("hp") or 0),
        "cost": int(card.get("cost") or 0),
        "golden": str(card.get("golden") or ""),
        "normal": str(card.get("normal") or ""),
        "in_pool": (bool(info["in_pool"]) if "in_pool" in info else None),
        "implemented": (bool(info["implemented"]) if "implemented" in info else None),
        "tier7_only": bool(info.get("tier7", False)),
        "classes": classes,
        "score": round(float(raw * tier_factor), 4),
        "score_raw": round(float(raw), 4),
        "tier_factor": round(float(tier_factor), 4),
        "multiplier": {"score": round(float(m_score), 4), "hits": m_hits},
        "accumulator": {"score": round(float(a_score), 4), "hits": a_hits},
        "trigger_chain": {"score": round(float(t_score), 4), "hits": t_hits},
        "buff_magnitude": int(mag),
        "noise": noise,
        "mechanisms": mechanisms,
        # 只留前 200 字符的预览（完整文本在 cards.json；这样 2759 张卡的清单从 3.5MB 降到 ~1MB）
        "text": en[:200],
        "snippets": {"multiplier": m_frag, "accumulator": a_frag,
                     "trigger_chain": t_frag},
    }


# ══════════════════════════════════════════════════════════════════════════
# 4. 核心牌集（按流派分组）
# ══════════════════════════════════════════════════════════════════════════
def _core_ok(rec: Dict[str, Any]) -> bool:
    """核心牌资格：随从 + tier<=5 + 在池 + 已实现 + 非经济噪声（引擎缺失时只要求随从+tier）。"""
    if str(rec["kind"]) != "minion":
        return False
    if not (0 < int(rec["tier"]) <= CORE_MAX_TIER):
        return False
    if rec["in_pool"] is False or rec["implemented"] is False:
        return False
    if rec["tier7_only"]:
        return False
    if rec.get("noise"):
        return False
    return float(rec["score"]) > 0.0


def _first_frag(rec: Dict[str, Any]) -> str:
    """代表文本片段（优先乘数 → 累加 → 触发链）。"""
    sn = rec.get("snippets") or {}
    for cls in ("multiplier", "accumulator", "trigger_chain"):
        rows = sn.get(cls) or []
        if rows:
            return str(rows[0])[:140]
    return str(rec.get("text") or "")[:140]


def _rank(recs: Iterable[Dict[str, Any]], *, bonus: Optional[Dict[str, float]] = None,
          max_n: int = 6) -> List[Dict[str, Any]]:
    """按 ``score + bonus[id]`` 排序取前 ``max_n``；输出精简记录。"""
    b = bonus or {}
    rows = sorted(recs, key=lambda r: (-(float(r["score"]) + float(b.get(r["id"], 0.0))),
                                       int(r["tier"]), str(r["id"])))
    out = []
    for r in rows[:int(max_n)]:
        out.append({
            "id": str(r["id"]), "name": r["name"], "name_zh": r["name_zh"],
            "tier": int(r["tier"]), "races": list(r["races"]),
            "classes": list(r["classes"]),
            "score": float(r["score"]) + float(b.get(r["id"], 0.0)),
            "mechanisms": list(r["mechanisms"]),
            "in_pool": r["in_pool"],
            "snippet": _first_frag(r),
        })
    return out


def _tribe_of(rec: Dict[str, Any]) -> List[str]:
    """卡的种族标签；``ALL``（融合怪）与空种族都归 ``NEUTRAL`` 之外各自保留。"""
    races = [str(r) for r in rec["races"]]
    if not races:
        return ["NEUTRAL"]
    return races


def build_mechanisms(recs: Sequence[Dict[str, Any]], *, max_core: int) -> Dict[str, Any]:
    """按**机制**分组（与种族正交）：亡语/战吼/进击/复仇/抉择/酒馆法术/血宝石…"""
    eligible = [r for r in recs if _core_ok(r)]
    out: Dict[str, Any] = {}
    for name, _pat_en, _pat_zh in MECHANISM_RULES:
        rows = [r for r in eligible if name in r["mechanisms"]]
        if rows:
            out[name] = _rank(rows, max_n=max_core)
    return out


def build_core(recs: Sequence[Dict[str, Any]], *, max_core: int,
               arch_table: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """构造核心牌集：``global`` / ``by_tribe`` / ``by_archetype`` / ``common_ids``。"""
    eligible = [r for r in recs if _core_ok(r)]
    by_id = {r["id"]: r for r in eligible}
    tribes: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
    for r in eligible:
        for t in _tribe_of(r):
            tribes[t].append(r)
    by_tribe = {t: _rank(rows, max_n=max_core) for t, rows in sorted(tribes.items())}

    # 种族族（archetype_table 的 tribe_family 是单数小写：beast / demon / ...）
    by_arch: Dict[str, Any] = {}
    if isinstance(arch_table, dict):
        for arch, node in (arch_table.get("archetypes") or {}).items():
            fam = str((node or {}).get("tribe_family") or "").upper()
            rows = list(tribes.get(fam, []))
            if not rows:                     # 族内没有候选 → 退回全部（如 neutral_*）
                rows = list(eligible)
            mech = ""
            for token, mname in ARCH_MECHANISM_TOKENS:
                if token in str(arch):
                    mech = mname
                    break
            bonus: Dict[str, float] = {}
            if mech:
                for r in rows:
                    if mech in r["mechanisms"]:
                        bonus[r["id"]] = 1.5      # 机制匹配加成（排序用，不改 score 本体）
            top = _rank(rows, bonus=bonus, max_n=max_core)
            by_arch[str(arch)] = {
                "tribe_family": fam, "mechanism": mech,
                "head": bool((node or {}).get("head", False)),
                "support": int((node or {}).get("support", 0) or 0),
                "core": top}

    # 公用牌（先验的「背景惩罚」只打**非公用牌**，所以这张表是硬边界）：
    #   (a) 种族为空或含 ALL（融合怪）→ 任何阵容都能用；
    #   (b) 出现在 >=2 个种族核心集里（多族卡，例如 DRAGON/DEMON 的邪火咒龙）。
    # 注意：**不**把 global 前几名算进来 —— 全流派最强的部落牌（如野猪人 BG30_123）
    # 仍然是「部落专属」，给定其它流派时必须能被惩罚，否则背景权重拉不下去。
    neutral_ids = sorted({str(r["id"]) for r in eligible
                          if not r["races"] or "ALL" in [str(x) for x in r["races"]]})
    seen: Dict[str, int] = collections.Counter()
    for _t, rows in by_tribe.items():
        for r in rows:
            seen[str(r["id"])] += 1
    multi = [cid for cid, n in seen.items() if n >= 2]
    glob = _rank(eligible, max_n=max(int(max_core) * 2, 12))
    common = sorted(set(neutral_ids) | set(multi))
    return {"global": glob, "by_tribe": by_tribe, "by_archetype": by_arch,
            "common_ids": common, "eligible_count": len(eligible), "by_id": by_id}


# ══════════════════════════════════════════════════════════════════════════
# 5. 汇总 / 报告
# ══════════════════════════════════════════════════════════════════════════
def _tribe_dist(recs: Sequence[Dict[str, Any]], cls: str) -> Dict[str, int]:
    """某一类的种族分布（``ALL`` 与空种族都单独成桶）。"""
    out: Dict[str, int] = collections.Counter()
    for r in recs:
        if cls not in r["classes"]:
            continue
        races = [str(x) for x in r["races"]] or ["NEUTRAL"]
        for t in races:
            out[t] += 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def mine(*, use_engine: bool = True, max_core: int = 6,
         cards_path: str = CARDS_JSON,
         carriers_path: str = CARRIERS_JSON,
         arch_table_path: str = ARCH_TABLE) -> Dict[str, Any]:
    """跑一遍挖矿，返回 ``compound_cards.json`` 的完整 payload（不含 generated_at）。"""
    data = load_cards(cards_path)
    cat = load_catalog(use_engine=use_engine)
    recs = [r for r in (classify_card(c, cat) for c in data["cards"]) if r is not None]
    recs.sort(key=lambda r: (-float(r["score"]), int(r["tier"]), str(r["id"])))

    by_class = {"multiplier": [], "accumulator": [], "trigger_chain": [], "both": []}
    for r in recs:
        for cls in ("multiplier", "accumulator", "trigger_chain"):
            if cls in r["classes"]:
                by_class[cls].append(str(r["id"]))
        if "multiplier" in r["classes"] and "accumulator" in r["classes"]:
            by_class["both"].append(str(r["id"]))
    for k in by_class:
        by_class[k] = sorted(set(by_class[k]))

    arch_table: Dict[str, Any] = {}
    try:
        with open(arch_table_path, "r", encoding="utf-8") as f:
            arch_table = json.load(f)
    except Exception:  # noqa: BLE001 - 表缺失时 by_archetype 为空
        arch_table = {}
    core = build_core(recs, max_core=int(max_core), arch_table=arch_table)
    by_id = core.pop("by_id")
    by_mechanism = build_mechanisms(recs, max_core=int(max_core))

    # 载体重叠（先验最该抓的那批：载体本身是「累加」引擎）
    carriers: Dict[str, Any] = {}
    try:
        with open(carriers_path, "r", encoding="utf-8") as f:
            carriers = json.load(f)
    except Exception:  # noqa: BLE001
        carriers = {}
    cids = [str(x) for x in (carriers.get("primary_ids") or ())]
    # 「进核心集」= 进**任何**一组（global / 种族 / 头部流派）的核心牌集
    core_any = {x["id"] for x in core["global"]}
    for _t, rows in core["by_tribe"].items():
        core_any |= {x["id"] for x in rows}
    for _a, node in core["by_archetype"].items():
        core_any |= {x["id"] for x in (node.get("core") or ())}
    overlap = {
        "carrier_ids": cids,
        "in_cards": sorted([c for c in cids if c in by_id or any(
            r["id"] == c for r in recs)]),
        "with_class": {
            cls: sorted([c for c in cids
                         if any(r["id"] == c and cls in r["classes"] for r in recs)])
            for cls in ("multiplier", "accumulator", "trigger_chain")},
        "in_core": sorted([c for c in cids if c in core_any]),
        "n_primary": len(cids),
    }
    overlap["n_mined"] = len(set(overlap["in_cards"]))

    counts = {
        "cards_total": len(data["cards"]),
        "mined_total": len(recs),
        "multiplier": len(by_class["multiplier"]),
        "accumulator": len(by_class["accumulator"]),
        "trigger_chain": len(by_class["trigger_chain"]),
        "multiplier_and_accumulator": len(by_class["both"]),
        "in_pool_mined": sum(1 for r in recs if r["in_pool"] is True),
        "in_pool_multiplier": sum(1 for r in recs
                                  if r["in_pool"] is True and "multiplier" in r["classes"]),
        "in_pool_accumulator": sum(1 for r in recs if r["in_pool"] is True
                                   and "accumulator" in r["classes"]),
        "in_pool_trigger_chain": sum(1 for r in recs if r["in_pool"] is True
                                     and "trigger_chain" in r["classes"]),
        "core_eligible": core["eligible_count"],
        "core_tribes": len(core["by_tribe"]),
        "core_archetypes": len(core["by_archetype"]),
        "common_ids": len(core["common_ids"]),
    }
    return {
        "meta": {
            "generated_by": "scripts/mine_compound_cards.py",
            "rules_version": int(RULES_VERSION),
            "source": "rust/crates/hsbg-engine/data/cards.json + hsbg_engine.catalog_json()",
            "cards_json": os.path.relpath(cards_path, ROOT),
            "carriers_json": os.path.relpath(carriers_path, ROOT),
            "archetype_table": os.path.relpath(arch_table_path, ROOT),
            "engine_catalog": bool(cat),
            "core_max_tier": int(CORE_MAX_TIER),
            "max_core": int(max_core),
            "definition": (
                "核心牌 = 该组内 tier<=5 + 在池 + 已实现 + 复利分数最强者；"
                "复利分数 = 1.0*乘数 + 1.0*累加 + 0.35*触发链，乘 tier 可得性加成"),
            "counts": counts,
            "tribe_dist": {
                "multiplier": _tribe_dist(recs, "multiplier"),
                "accumulator": _tribe_dist(recs, "accumulator"),
                "trigger_chain": _tribe_dist(recs, "trigger_chain"),
            },
            "counts_in_pool": {
                "multiplier": _tribe_dist([r for r in recs if r["in_pool"] is True],
                                          "multiplier"),
                "accumulator": _tribe_dist([r for r in recs if r["in_pool"] is True],
                                           "accumulator"),
                "trigger_chain": _tribe_dist([r for r in recs if r["in_pool"] is True],
                                             "trigger_chain"),
            },
        },
        "rules": {
            "multiplier": [{"name": n, "en": e, "zh": z, "weight": w, "note": note}
                           for n, e, z, w, note in MULTIPLIER_RULES],
            "accumulator": [{"name": n, "en": e, "zh": z, "weight": w, "note": note}
                            for n, e, z, w, note in ACCUMULATOR_RULES],
            "trigger_chain": [{"name": n, "en": e, "zh": z, "weight": w, "note": note}
                              for n, e, z, w, note in TRIGGER_RULES],
            "weights": {"multiplier": W_MULT, "accumulator": W_ACC,
                        "trigger_chain": W_TRIG, "mag_scale": MAG_SCALE,
                        "tier_w": TIER_W},
        },
        "by_class": by_class,
        "cards": recs,
        "core": {"global": core["global"], "by_tribe": core["by_tribe"],
                 "by_archetype": core["by_archetype"],
                 "by_mechanism": by_mechanism,
                 "common_ids": core["common_ids"], "eligible_count": core["eligible_count"]},
        "carrier_overlap": overlap,
    }


def report(payload: Dict[str, Any], *, top: int = 12) -> str:
    """生成 markdown 摘要（``--report`` 用；文档里直接引用同一口径）。"""
    m = payload["meta"]
    c = m["counts"]
    lines = ["## 复利链条文本挖矿", "",
             f"- 卡表 {c['cards_total']} 张，命中 {c['mined_total']} 张"
             f"（引擎 catalog: {'是' if m['engine_catalog'] else '否'}）",
             f"- **乘数 multiplier**: {c['multiplier']} 张（池内 {c['in_pool_multiplier']}）",
             f"- **累加 accumulator**: {c['accumulator']} 张（池内 {c['in_pool_accumulator']}）",
             f"- **触发链 trigger_chain**: {c['trigger_chain']} 张"
             f"（池内 {c['in_pool_trigger_chain']}）",
             f"- 乘数∩累加（真·复利）: {c['multiplier_and_accumulator']} 张",
             f"- 核心牌资格（随从/tier<=5/在池/已实现）: {c['core_eligible']} 张；"
             f"公用牌 {c['common_ids']} 张", "",
             f"### 代表卡（按复利分数，tier<=5 池内，top {top}）", "",
             "| id | 名称 | tier | 种族 | 类 | 分数 | 文本 |",
             "|---|---|---|---|---|---|---|"]
    recs = [r for r in payload["cards"]
            if r["in_pool"] is True and 0 < r["tier"] <= CORE_MAX_TIER]
    for r in recs[:int(top)]:
        frags = (r["snippets"]["multiplier"] or r["snippets"]["accumulator"]
                 or r["snippets"]["trigger_chain"] or [])
        txt = (frags[0] if frags else r["text"])[:70]
        lines.append(f"| {r['id']} | {r['name_zh']} | {r['tier']} | "
                     f"{'/'.join(r['races']) or '-'} | {'+'.join(r['classes'])} | "
                     f"{r['score']:.2f} | {txt} |")
    lines += ["", "### 载体重叠（carriers.json primary）", ""]
    ov = payload["carrier_overlap"]
    lines.append(f"- 主载体 {ov['n_primary']} 个，挖到 {ov['n_mined']} 个；"
                 f"进核心集 {len(ov['in_core'])} 个")
    for cls in ("multiplier", "accumulator", "trigger_chain"):
        if ov["with_class"][cls]:
            lines.append(f"- {cls}: {', '.join(ov['with_class'][cls])}")
    lines += ["", "### 各流派核心牌", "",
              "| 流派 | 核心牌（id:名称 tier 分数） |", "|---|---|"]
    for t, rows in payload["core"]["by_tribe"].items():
        s = "; ".join(f"{x['id']}:{x['name_zh']} t{x['tier']} {x['score']:.1f}"
                      for x in rows)
        lines.append(f"| {t} | {s} |")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# 6. CLI
# ══════════════════════════════════════════════════════════════════════════
def _strip_volatile(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = json.loads(json.dumps(payload))
    p.get("meta", {}).pop("generated_at", None)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="复利链条卡牌文本挖矿（乘数/累加/触发链）")
    ap.add_argument("--cards", default=CARDS_JSON)
    ap.add_argument("--carriers", default=CARRIERS_JSON)
    ap.add_argument("--archetype-table", default=ARCH_TABLE)
    ap.add_argument("--json-out", default=OUT_JSON)
    ap.add_argument("--max-core", type=int, default=6, help="每组核心牌上限")
    ap.add_argument("--no-engine", action="store_true",
                    help="不读引擎 catalog（in_pool 记为 None；仅调试用）")
    ap.add_argument("--report", action="store_true", help="打印 markdown 摘要")
    ap.add_argument("--check", action="store_true",
                    help="幂等自检：重新挖矿并与 --json-out 比对（不落盘）")
    args = ap.parse_args(argv)

    payload = mine(use_engine=not bool(args.no_engine), max_core=int(args.max_core),
                   cards_path=args.cards, carriers_path=args.carriers,
                   arch_table_path=args.archetype_table)
    if args.check:
        with open(args.json_out, "r", encoding="utf-8") as f:
            old = json.load(f)
        a = json.dumps(_strip_volatile(payload), ensure_ascii=False, sort_keys=True)
        b = json.dumps(_strip_volatile(old), ensure_ascii=False, sort_keys=True)
        if a != b:
            print(f"[check] 不一致：{args.json_out} 需要重跑 "
                  f"python scripts/mine_compound_cards.py", file=sys.stderr)
            return 1
        print(f"[check] OK（{args.json_out} 与当前挖矿结果逐位一致）")
        return 0

    import datetime
    payload["meta"]["generated_at"] = datetime.datetime.now().astimezone().strftime(
        "%Y-%m-%dT%H:%M:%S%z")
    os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
    tmp = args.json_out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, args.json_out)
    c = payload["meta"]["counts"]
    print(f"[mine] 命中 {c['mined_total']} 张：乘数 {c['multiplier']} / "
          f"累加 {c['accumulator']} / 触发链 {c['trigger_chain']}"
          f"（∩ {c['multiplier_and_accumulator']}）；"
          f"池内 {c['in_pool_mined']}；核心资格 {c['core_eligible']}"
          f"；公用牌 {c['common_ids']}")
    print(f"[mine] 写出 {os.path.relpath(args.json_out, ROOT)}")
    if args.report:
        print(report(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
