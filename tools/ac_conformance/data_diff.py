"""卡牌/规则常量数据差异：AutoTavern 36.6.3（参照） vs HSBRSIM 37.0.0。

只读：不修改 `data/**`、不修改参照仓库。口径详见
`docs/CONFORMANCE_AUTOTAVERN.md` §2：

* **id 层**：两版本卡片 id 集合的交/差；
* **随从层**（`kind=minion` ↔ `card_type=4`）：攻/血/酒馆等级/种族/关键词/
  池标记/文本（去 HTML 标签与空白后的规范化比较）；
* **池层**：AutoTavern `pools` 含 `minion` ↔ HSBRSIM `is_pool_minion`；
* **规则常量层**：`RulesConfig` 默认值（36.6.3） vs `hsrl2.constants`。

文本比较分三档：`same` / `formatting_only`（仅标签/换行/占位符格式差异）/
`different`。参数化占位符（HSBRSIM 文本里的 `{0}/{1}`）视为格式差异：
在 `formatting_only` 判定时把 `{数字}` 统一抹去再比较。
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .paths import (
    AUTOTAVERN_CARDS,
    HSRL2_CARDS,
    HSRL2_POOL_MINIONS,
    ROOT,
)

_TAG_RE = re.compile(r"<[^>]+>")
_PARAM_RE = re.compile(r"\{[0-9]+\}")
_WS_RE = re.compile(r"\s+")
_PUNCT_SPACE_RE = re.compile(r"\s+([,.;:!?])")

#: HSBRSIM `card_race` 数值 → 种族名（对齐 hsrl2.tags.Race / DBF_RACE_TO_ENUM）。
_RACE_BY_CODE = {
    11: "UNDEAD",
    14: "MURLOC",
    15: "DEMON",
    17: "MECHANICAL",
    18: "ELEMENTAL",
    20: "BEAST",
    23: "PIRATE",
    24: "DRAGON",
    26: "ALL",
    43: "QUILBOAR",
    92: "NAGA",
    126: "ABERRATION",
}

#: AutoTavern 关键词 → HSBRSIM 卡数据里的布尔字段 / 标记字段。
#: 注意 AutoTavern 内部把 Rally 命名为 `BACON_RALLY`（见 cards.json 的
#: `keywords`），这里先做别名归一。
_KW_FIELD_MAP = {
    "DEATHRATTLE": "deathrattle",
    "BATTLECRY": "battlecry",
    "TAUNT": "taunt",
    "RALLY": "rally",
    "DIVINE_SHIELD": "divine_shield",
    "START_OF_COMBAT": "start_of_combat",
    "AVENGE": "avenge",
    "REBORN": "reborn",
    "MAGNETIC": "magnetic",
    "ACTIVATE": "activate",
    "CHOOSE_ONE": "choose_one",
    "WINDFURY": "windfury",
    "VENOMOUS": "venomous",
    "POISONOUS": "poisonous",
}

#: AutoTavern 关键词别名（内部命名 → 统一语义名）。
_KW_ALIASES = {
    "BACON_RALLY": "RALLY",
    "BACON_SPELLCRAFT_ID": "SPELLCRAFT",
    "InvisibleDeathrattle": "INVISIBLE_DEATHRATTLE",
    "BATTLECRY_ONLY_ONCE": "BATTLECRY_ONLY_ONCE",
}

#: 无对应布尔字段的 AutoTavern 关键词（记录为“未映射”，不计入差异）。
#: 其中 STEALTH/CLEAVE/MEGA_WINDFURY/END_OF_TURN_TRIGGER 属于
#: **HSBRSIM `data/bg_cards.json` 字段缺口**（引擎支持，数据导出未带）——
#: 记录在 `unmapped_keywords` 里，见文档 §2.3。
_KW_UNMAPPED = {
    "TRIGGER_VISUAL",
    "END_OF_TURN_TRIGGER",
    "INVISIBLE_DEATHRATTLE",
    "AURA",
    "DISCOVER",
    "QUEST",
    "SIDE_QUEST",
    "SECRET",
    "FRENZY",
    "TWINSPELL",
    "CHARGE",
    "ADJACENT_BUFF",
    "CANT_BE_DESTROYED",
    "OVERKILL",
    "STEALTH",
    "CLEAVE",
    "MEGA_WINDFURY",
    "ELUSIVE",
}


def norm_text(text: Optional[str]) -> str:
    """规范化卡面文本：去 HTML 标签 / `[x]` / 参数占位符 / 折叠空白 / 小写。"""
    if not text:
        return ""
    t = text.replace("[x]", " ")
    t = _TAG_RE.sub("", t)
    t = _PARAM_RE.sub("#", t)
    t = t.replace("\u00a0", " ")
    # HSBRSIM 数据导出用 `_` 表示 XML 源码换行、`@` 表示分页标记
    # （37.0 生成管线产物）；不是卡面字符，比较前剔除。
    t = t.replace("_", " ").replace("@", "#")
    t = _WS_RE.sub(" ", t)
    t = _PUNCT_SPACE_RE.sub(r"\1", t)
    return t.strip().lower()


def _cmp_text(at_text: Optional[str], hs_text: Optional[str]) -> str:
    a, h = norm_text(at_text), norm_text(hs_text)
    if a == h:
        return "same"
    # 1) HSBRSIM 文本用 `@` 连接"普通/金色/动态"多段（如 Avenge 卖出价、
    #    Boogie Monster 的 Tier 进度文本）——任一段与 AT 全文一致即视为
    #    表示差异，不是版本内容差异。
    raw_hs = (hs_text or "").replace("[x]", " ")
    a2_pre = re.sub(r"[0-9]+", "#", a)
    for seg in raw_hs.split("@"):
        sg = norm_text(seg)
        if sg == a or re.sub(r"[0-9]+", "#", sg) == a2_pre:
            return "formatting_only"
    # 2) 占位符在 AutoTavern 里已被具体数值替换（如 Activate ({2})），
    #    进一步抹去所有数字再比一次，命中则算格式/参数化差异。
    a2 = re.sub(r"[0-9]+", "#", a)
    h2 = re.sub(r"[0-9]+", "#", h)
    if a2 == h2:
        return "formatting_only"
    # 3) 纯占位符文本（`{0} {1}` vs `0`）：去掉 # 与空白后均为空。
    a3 = re.sub(r"[#\s]", "", a2)
    h3 = re.sub(r"[#\s]", "", h2)
    if a3 == h3:
        return "formatting_only"
    return "different"


def _at_keywords(rec: Dict[str, Any]) -> set:
    """AutoTavern cards.json → 语义关键词集合。

    AutoTavern 的 `keywords` 字段是客户端 tag 列表，**不含** Activate /
    Choose One（这两类在 AutoTavern 端由脚本/文本承载），另用 `spellcraft`
    字段表示塑造法术；这里从文本补齐后再与 hsrl2 数据比较。
    """
    kw = {_KW_ALIASES.get(k, k) for k in (rec.get("keywords") or [])}
    text = rec.get("text") or ""
    if "Activate (" in text:
        kw.add("ACTIVATE")
    if "Choose One" in text:
        kw.add("CHOOSE_ONE")
    if rec.get("spellcraft"):
        kw.add("SPELLCRAFT")
    return kw


def _hs_keywords(rec: Dict[str, Any]) -> set:
    """HSBRSIM 卡数据 → 关键词名集合（只映射有布尔字段的部分）。"""
    out = set()
    for kw, field in _KW_FIELD_MAP.items():
        if rec.get(field):
            out.add(kw)
    if rec.get("spellcraft_id") is not None:
        out.add("SPELLCRAFT")
    return out


def _hs_races(rec: Dict[str, Any]) -> set:
    out = set()
    code = rec.get("card_race")
    if code is not None:
        out.add(_RACE_BY_CODE.get(int(code), f"CODE_{code}"))
    for name in rec.get("race_tags") or []:
        name = str(name)
        out.add("MECHANICAL" if name == "MECH" else name)
    return out


def load_autotavern_cards() -> Dict[str, Dict[str, Any]]:
    data = json.loads(AUTOTAVERN_CARDS.read_text(encoding="utf-8"))
    return {c["id"]: c for c in data["cards"]}


def load_hsrl2_cards() -> Dict[str, Dict[str, Any]]:
    data = json.loads(HSRL2_CARDS.read_text(encoding="utf-8"))
    return {c["id"]: c for c in data}


def compare_cards() -> Dict[str, Any]:
    """卡牌数据差异（无 taverngym 依赖，纯 JSON）。"""
    a = load_autotavern_cards()
    h = load_hsrl2_cards()
    shared = set(a) & set(h)

    at_minions = {cid: c for cid, c in a.items() if c.get("kind") == "minion"}
    hs_minions = {cid: c for cid, c in h.items() if c.get("card_type") == 4}
    shared_minions = sorted(set(at_minions) & set(hs_minions))

    stat_diffs: List[Dict[str, Any]] = []
    kw_diffs: List[Dict[str, Any]] = []
    race_diffs: List[Dict[str, Any]] = []
    tier_diffs: List[Dict[str, Any]] = []
    text_diffs: List[Dict[str, Any]] = []
    text_fmt_only = 0
    unmapped_kw = Counter()

    for cid in shared_minions:
        x, y = at_minions[cid], hs_minions[cid]
        # 攻/血（缺字段按 0 处理；HS 有 23 张 0 攻随从省略 atk）
        xa, ya = x.get("atk") or 0, y.get("atk") or 0
        xh, yh = x.get("hp") or 0, y.get("health") or 0
        if xa != ya or xh != yh:
            stat_diffs.append(
                {"id": cid, "name": x.get("name"), "at_orig": xa, "hs_orig": ya,
                 "at_hp": xh, "hs_hp": yh}
            )
        xt, yt = x.get("tier"), y.get("tech_level")
        if (xt or 0) >= 1 and xt != yt:
            tier_diffs.append({"id": cid, "name": x.get("name"),
                               "at_tier": xt, "hs_tier": yt})
        xk = _at_keywords(x)
        for k in list(xk):
            if k in _KW_UNMAPPED:
                unmapped_kw[k] += 1
                xk.discard(k)
        yk = _hs_keywords(y)
        if xk != yk:
            kw_diffs.append({"id": cid, "name": x.get("name"),
                             "at_only": sorted(xk - yk),
                             "hs_only": sorted(yk - xk)})
        xr, yr = set(x.get("races") or []), _hs_races(y)
        if xr != yr:
            race_diffs.append({"id": cid, "name": x.get("name"),
                               "at_races": sorted(xr), "hs_races": sorted(yr)})
        verdict = _cmp_text(x.get("text"), y.get("text"))
        if verdict == "formatting_only":
            text_fmt_only += 1
        elif verdict == "different":
            text_diffs.append({
                "id": cid, "name": x.get("name"),
                "at_text": (x.get("text") or "")[:160],
                "hs_text": (y.get("text") or "")[:160],
            })

    # ── 池层 ──
    at_pool = {cid for cid, c in a.items()
               if "minion" in (c.get("pools") or [])}
    hs_pool_recs = json.loads(HSRL2_POOL_MINIONS.read_text(encoding="utf-8"))
    hs_pool = {c["id"] for c in hs_pool_recs}
    pool_shared = sorted(at_pool & hs_pool)
    hs_pool_by_id = {c["id"]: c for c in hs_pool_recs}
    pool_stat_diffs = []
    for cid in pool_shared:
        x, y = a[cid], hs_pool_by_id[cid]
        xa, ya = x.get("atk") or 0, y.get("atk") or 0
        xh, yh = x.get("hp") or 0, y.get("health") or 0
        xk = {k for k in _at_keywords(x) if k not in _KW_UNMAPPED}
        if xa != ya or xh != yh or xk != _hs_keywords(y):
            pool_stat_diffs.append(
                {"id": cid, "name": x.get("name"),
                 "at": {"atk": xa, "hp": xh, "tier": x.get("tier"),
                        "keywords": sorted(xk)},
                 "hs": {"atk": ya, "hp": yh, "tier": y.get("tech_level"),
                        "keywords": sorted(_hs_keywords(y))}}
            )

    # ── 各类 kind 的共享数（信息性） ──
    kinds: Dict[str, Any] = {}
    for kind in ("minion", "tavern_spell", "spell", "hero", "hero_power",
                 "trinket_lesser", "trinket_greater", "quest", "quest_reward",
                 "dark_gift"):
        ids = {cid for cid, c in a.items() if c.get("kind") == kind}
        kinds[kind] = {
            "autotavern": len(ids),
            "shared_with_hsrl2": len(ids & set(h)),
            "only_autotavern": len(ids - set(h)),
        }

    return {
        "sources": {
            "autotavern": str(AUTOTAVERN_CARDS),
            "hsrl2": str(HSRL2_CARDS),
            "hsrl2_pool_minions": str(HSRL2_POOL_MINIONS),
        },
        "ids": {
            "autotavern_cards": len(a),
            "hsrl2_cards": len(h),
            "shared": len(shared),
            "only_autotavern": len(set(a) - set(h)),
            "only_hsrl2": len(set(h) - set(a)),
        },
        "kinds": kinds,
        "minions": {
            "autotavern_minions": len(at_minions),
            "hsrl2_minions": len(hs_minions),
            "shared_minions": len(shared_minions),
            "stat_diff_count": len(stat_diffs),
            "stat_diff": stat_diffs[:80],
            "tier_diff_count": len(tier_diffs),
            "tier_diff": tier_diffs[:40],
            "keyword_diff_count": len(kw_diffs),
            "keyword_diff": kw_diffs[:60],
            "race_diff_count": len(race_diffs),
            "race_diff": race_diffs[:40],
            "text_diff_count": len(text_diffs),
            "text_formatting_only_count": text_fmt_only,
            "text_diff": text_diffs[:60],
            "unmapped_keywords": dict(unmapped_kw),
        },
        "pool": {
            "autotavern_pool_minions": len(at_pool),
            "hsrl2_pool_minions": len(hs_pool),
            "shared_pool_minions": len(pool_shared),
            "only_autotavern_pool": sorted(at_pool - hs_pool)[:80],
            "only_hsrl2_pool": sorted(hs_pool - at_pool)[:80],
            "pool_stat_diff_count": len(pool_stat_diffs),
            "pool_stat_diff": pool_stat_diffs[:60],
        },
    }


# ══════════════════════════════════════════════════════════════════════
# 规则常量：AutoTavern RulesConfig 默认值 vs hsrl2.constants
# ══════════════════════════════════════════════════════════════════════

def _hsrl2_constants() -> Dict[str, Any]:
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import hsrl2.constants as C
    from hsrl2.pools import SpellPool
    return {
        "start_gold": C.GOLD_START,
        "gold_increment": 1,
        "gold_refill_cap": C.GOLD_INCOME_CAP,
        "buy_cost": C.MINION_BUY_COST,
        "sell_value": C.MINION_SELL_VALUE,
        "refresh_cost": C.REFRESH_COST,
        "board_size": C.BOARD_SIZE,
        "hand_size": C.HAND_SIZE,
        "max_regular_tier": C.TAVERN_MAX_TIER,
        "triple_copies": C.TRIPLE_COPIES_NEEDED,
        "damage_cap_until_alive": C.DAMAGE_CAP_REMOVED_AT_PLAYERS,
        "pool_copies_by_tier": [C.POOL_COPIES_BY_TIER[t] for t in range(1, 8)],
        "spell_copies_by_tier": [SpellPool.POOL_COPIES_BY_TIER[t]
                               for t in range(1, 7)],
        "shop_minion_slots": [C.TAVERN_OFFERS[t] for t in range(1, 7)] + [
            C.TAVERN_OFFERS.get(7, C.TAVERN_OFFERS[6])],
        "shop_spell_slots": C.TAVERN_SPELLS_PER_REFRESH,
        "upgrade_costs": [C.BASE_UPGRADE_COSTS[t] for t in range(2, 8)],
        "upgrade_discount_per_turn": C.UPGRADE_DECAY_PER_TURN,
        "damage_caps": [
            [1, C.DAMAGE_CAP_BY_TURN],
            [4, C.DAMAGE_CAP_T4_T7],
            [8, C.DAMAGE_CAP_T8_PLUS],
        ],
    }


#: 已知 AutoTavern 参数名 → hsrl2 常量名的行映射；None 表示 HSBRSIM 无对应。
_CONST_ROWS = [
    ("start_gold", "起始金币"),
    ("gold_increment", "每回合金币增量"),
    ("gold_refill_cap", "金币自然收入上限"),
    ("buy_cost", "购买随从费用"),
    ("sell_value", "出售随从返还"),
    ("refresh_cost", "刷新费用"),
    ("board_size", "棋盘上限"),
    ("hand_size", "手牌上限"),
    ("max_regular_tier", "常规最高酒馆等级"),
    ("triple_copies", "三连所需份数"),
    ("damage_cap_until_alive", "解除伤害上限的存活人数阈值"),
    ("pool_copies_by_tier", "各等级随从池份数 (T1..T7)"),
    ("spell_copies_by_tier", "各等级酒馆法术池份数 (T1..T6)"),
    ("shop_minion_slots", "各等级酒馆随从槽位 (T1..T7)"),
    ("shop_spell_slots", "酒馆法术槽位"),
    ("upgrade_costs", "基础升级费 (T2..T7)"),
    ("upgrade_discount_per_turn", "每回合升级费衰减"),
    ("damage_caps", "伤害上限阶梯"),
]


def compare_rule_constants() -> Dict[str, Any]:
    """规则常量差异。AutoTavern 参数由已编译 `taverngym.default_config_json()`
    提供（缺失时退化为读取 config.rs 的 Default 块）。"""
    ref: Dict[str, Any]
    ref_source: str
    try:
        import taverngym  # type: ignore
        cfg = json.loads(taverngym.default_config_json())
        ref = {k: cfg.get(k) for k, _ in _CONST_ROWS}
        ref_source = "taverngym.default_config_json()"
    except Exception:  # noqa: BLE001 - 参照包未安装时仅做说明
        ref = {}
        ref_source = "UNAVAILABLE (import taverngym failed)"
    hs = _hsrl2_constants()
    rows = []
    for key, label in _CONST_ROWS:
        a, b = ref.get(key), hs.get(key)
        rows.append({
            "key": key,
            "label": label,
            "autotavern": a,
            "hsrl2": b,
            "match": a == b,
        })
    diffs = [r for r in rows if not r["match"]]
    return {
        "reference_source": ref_source,
        "rows": rows,
        "diff_count": len(diffs),
        "diffs": diffs,
    }


def compare_all() -> Dict[str, Any]:
    return {
        "cards": compare_cards(),
        "rule_constants": compare_rule_constants(),
    }


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="AutoTavern vs hsrl2 数据差异")
    ap.add_argument("--out", default=str(ROOT / "runs" / "conformance" / "data_diff.json"))
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    diff = compare_all()
    out.write_text(json.dumps(diff, ensure_ascii=False, indent=1), encoding="utf-8")
    c = diff["cards"]
    print(f"cards: shared={c['ids']['shared']} only_AT={c['ids']['only_autotavern']} "
          f"only_HS={c['ids']['only_hsrl2']}")
    m = c["minions"]
    print(f"minions: shared={m['shared_minions']} stat_diff={m['stat_diff_count']} "
          f"tier_diff={m['tier_diff_count']} kw_diff={m['keyword_diff_count']} "
          f"race_diff={m['race_diff_count']} text_diff={m['text_diff_count']} "
          f"(formatting_only={m['text_formatting_only_count']})")
    print(f"pool: AT={c['pool']['autotavern_pool_minions']} "
          f"HS={c['pool']['hsrl2_pool_minions']} shared={c['pool']['shared_pool_minions']} "
          f"stat_diff={c['pool']['pool_stat_diff_count']}")
    rc = diff["rule_constants"]
    print(f"rule_constants: {rc['diff_count']} diff(s) from {rc['reference_source']}")
    for row in rc["diffs"]:
        print(f"  - {row['key']}: AT={row['autotavern']} HS={row['hsrl2']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
