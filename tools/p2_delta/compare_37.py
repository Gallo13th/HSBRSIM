#!/usr/bin/env python3
"""37.0.0 内容覆盖矩阵：AutoTavern 36.6.3 已实现 vs HSBRSIM 37.0.0 数据。

输入（全部只读）
  * `runs/p2_delta/at_content.json`（``extract_at_content.py`` 产物）
  * `data/bg_*.json`（官方 37.0.0.255130 数据升级产物）
  * `hsrl2/scripts/**`（37.x 的 Python 参考实现，用于“移植参考”列）

输出（`runs/p2_delta/`，gitignore）
  * ``coverage_matrix.json`` —— 全量机器可读矩阵（本工具唯一事实来源）
  * ``summary.md`` —— 覆盖统计/缺失清单 markdown 表（写入文档时逐表引用）
  * ``missing_pool_minions.md`` —— 池内缺失随从逐条表（id/名/文本/tier/种族/难度/参考）

覆盖判定口径（写进 docs/PORTING_37_PLAN.md §2）：
  * AT 侧“已实现”：卡 id 在 content 注册表（scripted），或卡面文本去掉关键词后
    为空（keyword-only，复刻上游 ``implemented_uncached``）。
  * 37 侧“池集合”一律用数据标志：池内随从 ``is_pool_minion``、池内酒馆法术
    ``is_pool_spell``、饰品/黑暗赠礼/任务奖励/异变来自各自 ``data/bg_*.json``。
  * 金色/变体按本体归一（37 的 ``_G`` / AT 的 ``normal`` 链），只比较本体。
  * “changed” = 两版本都存在且 AT 侧已实现（脚本或纯关键词）的卡，其
    tier/atk/hp/cost/种族/文本结构/数字任一项不同。

用法::

    python3 tools/p2_delta/compare_37.py            # 生成全部输出
    python3 tools/p2_delta/compare_37.py --check    # 只校验、不写文件
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as C  # noqa: E402

#: 触发型 hook（决定 S/M/L 难度：0 触发=静态/纯数值；1=单 hook；≥2=多 hook/复合）
TRIGGER_HOOKS = {
    "battlecry",
    "deathrattle",
    "start_of_combat",
    "rally",
    "avenge",
    "activate",
    "end_of_turn",
    "start_of_turn",
    "on_sell",
    "on_event",
    "after_attack",
    "deity_awakened",
    "spellcraft",
    "choose_one",
}

#: 这些 kind 的卡在 AT 数据里 cost 字段约定为 0（BG 购买价固定），不与 37 cost 比较
MINION_LIKE_KINDS = {"pool_minions", "tier7", "timewarp", "buddies", "heroes"}

STOPWORDS = {
    "a", "an", "the", "of", "to", "and", "or", "your", "you", "this", "that",
    "it", "its", "for", "in", "on", "with", "from", "get", "gets", "give",
    "gives", "gain", "gains", "all", "each", "every", "other", "than", "then",
    "when", "whenever", "after", "before", "at", "the", "is", "are", "be",
    "minion", "minions", "card", "cards", "spell", "spells", "tavern", "friendly",
}


# ══════════════════════════════════════════════════════════════════════
# 37 数据侧集合
# ══════════════════════════════════════════════════════════════════════
def load_hsrl2_extras() -> Dict[str, Any]:
    """可选的 hsrl2 侧信息：REGISTRY、id→脚本文件、饰品可提供池、任务定义。"""
    reg_ids, files, err = C.load_hsrl2_registry()
    out: Dict[str, Any] = {
        "registry_ok": reg_ids is not None,
        "registry_error": err,
        "registry_size": len(reg_ids) if reg_ids else None,
        "ids": reg_ids or set(),
        "script_files": files,
        "trinket_offerable": None,
        "quest_ids": None,
    }
    try:
        if str(C.REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(C.REPO_ROOT))
        from hsrl2.db import CardDB  # type: ignore
        from hsrl2.game import quest_defs_from_db  # type: ignore

        db = CardDB.load(C.DATA_DIR)
        out["trinket_offerable"] = sorted(d.id for d in db.trinket_offer_pool())
        out["quest_ids"] = sorted(d.id for d in quest_defs_from_db(db))
    except Exception as exc:  # pragma: no cover
        out["hsrl2_db_error"] = f"{type(exc).__name__}: {exc}"
    return out


def build_ds37(ds: Dict[str, Any], extras: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """构建 37 侧分 kind 集合与说明。"""
    raw = ds["raw"]
    pool_minions = sorted(c["id"] for c in raw["bg_pool_minions"])
    heroes = sorted(c["id"] for c in raw["bg_heroes"])
    hero_powers = sorted(c["id"] for c in raw["bg_hero_powers"])
    # hero → 主英雄技能（dbf 映射）
    power_by_dbf = {p["dbf_id"]: p["id"] for p in raw["bg_hero_powers"]}
    hero_main_power = {
        h["id"]: power_by_dbf.get(h.get("hero_power_dbf")) for h in raw["bg_heroes"]
    }
    pool_spells = sorted(c["id"] for c in raw["bg_pool_spells"])
    tavern_spells_all = sorted(c["id"] for c in raw["bg_tavern_spells"])
    trinkets_all = sorted(c["id"] for c in raw["bg_trinkets"])
    quest_rewards = sorted(c["id"] for c in raw["bg_quest_rewards"])
    dark_gifts = sorted(c["id"] for c in raw["bg_dark_gifts"])
    anomalies = sorted(c["id"] for c in raw["bg_anomalies"])

    tier7 = sorted(
        c["id"] for c in raw["bg_pool_minions"] if (c.get("tech_level") or 0) >= 7
    )
    buddies_all = sorted(
        c["id"] for c in raw["bg_cards"] if "_Buddy" in c["id"] and not c["id"].endswith("_G")
    )
    kinds: Dict[str, Any] = {
        "pool_minions": {
            "definition": "37 数据 IS_BACON_POOL_MINION 随从（data/bg_pool_minions.json，含 T7）",
            "set": pool_minions,
        },
        "heroes": {
            "definition": "37 数据可抽英雄（data/bg_heroes.json，118）",
            "set": heroes,
        },
        "hero_powers": {
            "definition": "37 数据英雄技能定义（data/bg_hero_powers.json，165；含变体）",
            "set": hero_powers,
        },
        "pool_spells": {
            "definition": "37 数据当前酒馆法术池（is_pool_spell，76）",
            "set": pool_spells,
        },
        "tavern_spells_all": {
            "definition": "37 数据全部酒馆法术定义（card_type 42，205；含 token/非池）",
            "set": tavern_spells_all,
        },
        "trinkets": {
            "definition": "37 数据全部饰品定义（data/bg_trinkets.json，409）",
            "set": trinkets_all,
        },
        "quest_rewards": {
            "definition": "37 数据任务奖励（data/bg_quest_rewards.json，73）",
            "set": quest_rewards,
        },
        "dark_gifts": {
            "definition": "37 数据黑暗赠礼（data/bg_dark_gifts.json，47）",
            "set": dark_gifts,
        },
        "anomalies": {
            "definition": "37 数据异变定义（data/bg_anomalies.json，108；历史定义，见系统评估）",
            "set": anomalies,
        },
        "tier7": {
            "definition": "37 池内 T7 随从（tech_level==7）",
            "set": tier7,
        },
        "buddies": {
            "definition": "37 数据伙伴卡定义（非池，任务/饰品/英雄技能可引用）",
            "set": buddies_all,
        },
    }
    if extras.get("quest_ids") is not None:
        kinds["quests"] = {
            "definition": "37 数据任务卡（hsrl2.game.is_quest_card 同源谓词）",
            "set": sorted(extras["quest_ids"]),
        }
    kinds["hero_main_power"] = {
        "definition": "37 英雄的主技能（hero_power_dbf → hero_power id，118）",
        "set": sorted({p for p in hero_main_power.values() if p}),
    }
    meta = {k: v["definition"] for k, v in kinds.items()}
    return {
        "kinds": kinds,
        "meta": meta,
        "hero_main_power": hero_main_power,
        "trinket_offerable": extras.get("trinket_offerable"),
        "by_id": ds["by_id"],
    }


# ══════════════════════════════════════════════════════════════════════
# AT 侧集合（含 golden/本体归一、keyword-only）
# ══════════════════════════════════════════════════════════════════════
def build_at(at_doc: Dict[str, Any], at_cards: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    registry = at_doc["registry"]
    scripted = set(registry)

    def at_has_script(cid: str) -> bool:
        seen: Set[str] = set()
        cur = at_cards.get(cid)
        while cur is not None and cur["id"] not in seen:
            seen.add(cur["id"])
            if cur["id"] in scripted:
                return True
            nxt = cur.get("normal")
            cur = at_cards.get(nxt) if nxt else None
        return False

    def at_implemented(cid: str) -> bool:
        card = at_cards.get(cid)
        if card is None:
            return False
        if at_has_script(cid):
            return True
        return C.keyword_only(card.get("text"))

    # AT 自身“已实现集合”的分 kind（上游 content_report 口径）
    pools: Dict[str, List[str]] = {
        "pool_minions": [],
        "heroes": [],
        "hero_powers": [],
        "pool_spells": [],
        "tavern_spells_all": [],
        "trinkets": [],
        "quest_rewards": [],
        "dark_gifts": [],
        "anomalies": [],
        "timewarp": [],
        "tier7": [],
        "buddies": [],
        "quests": [],
    }
    for cid, card in at_cards.items():
        p = card.get("pools", []) or []
        kind = card.get("kind")
        if "minion" in p and (card.get("pool_tag") or 0) <= 1:
            pools["pool_minions"].append(cid)
        if "hero" in p and kind == "hero":
            pools["heroes"].append(cid)
        if kind == "hero_power":
            pools["hero_powers"].append(cid)
        if "spell" in p and kind == "tavern_spell":
            pools["pool_spells"].append(cid)
        if kind == "tavern_spell":
            pools["tavern_spells_all"].append(cid)
        if "trinket" in p:
            pools["trinkets"].append(cid)
        if kind == "quest_reward":
            pools["quest_rewards"].append(cid)
        if kind == "dark_gift" and card.get("window") is not None:
            pools["dark_gifts"].append(cid)
        if "timewarp" in p:
            pools["timewarp"].append(cid)
        if "tier7" in p:
            pools["tier7"].append(cid)
        if kind == "quest":
            pools["quests"].append(cid)
        if "_Buddy" in cid and not cid.endswith("_G"):
            pools["buddies"].append(cid)
    for k in pools:
        pools[k] = sorted(set(pools[k]))
    # AT 的 420 个饰品定义（kind=trinket_lesser/greater）
    trinket_defs = sorted(
        cid for cid, c in at_cards.items() if c.get("kind") in ("trinket_lesser", "trinket_greater")
    )
    return {
        "registry": registry,
        "scripted": scripted,
        "at_has_script": at_has_script,
        "at_implemented": at_implemented,
        "pools": pools,
        "trinket_defs": trinket_defs,
    }


# ══════════════════════════════════════════════════════════════════════
# 难度 / 最近脚本 / 移植参考
# ══════════════════════════════════════════════════════════════════════
def classify_difficulty(card: Dict[str, Any], hooks: List[str]) -> Tuple[str, List[str]]:
    """S/M/L 难度（规则确定性，写进文档 §5.2）。

    * S = 纯关键词/纯数值：卡面去关键词后为空，或没有任何触发型 hook；
    * M = 单一 hook（战吼/亡语/复仇/开始战斗/回合结束/出售/Activate/...）；
    * L = ≥2 个触发型 hook（跨阶段复合），或命中「AT 无对应原语」的系统词。
    """
    text = C.solo_text(card.get("text"))
    reasons: List[str] = []
    missing = C.at_missing_primitives(card)
    if missing:
        return "L", [f"AT 无原语: {m}" for m in missing]
    if C.keyword_only(text):
        return "S", ["keyword_only（纯关键词/白板，只需数据+关键词映射）"]
    trig = [h for h in hooks if h in TRIGGER_HOOKS]
    static_hooks = [h for h in hooks if h not in TRIGGER_HOOKS]
    if not trig:
        reasons.append("no_trigger_hook（静态/光环/纯数值修正）")
        if static_hooks:
            reasons.append("static_hooks=" + ",".join(static_hooks))
        return "M" if text else "S", reasons
    if len(trig) == 1:
        return "M", [f"single_hook={trig[0]}"]
    return "L", ["multi_hook=" + ",".join(trig)]


def _tokens(text: str) -> Set[str]:
    t = C.normalize_text(text)
    t = re.sub(r"[^a-z0-9+/\- ]", " ", t)
    return {w for w in t.split() if w and w not in STOPWORDS and len(w) > 1}


def build_at_similarity_index(at_cards: Dict[str, Dict[str, Any]], registry: Dict[str, Any]):
    """为“AT 最接近可复用脚本”建立 (id, tokens, race, tier, hooks, file) 索引。"""
    index: List[Dict[str, Any]] = []
    for cid, info in registry.items():
        card = at_cards.get(cid)
        if card is None:
            continue
        index.append(
            {
                "id": cid,
                "name": card.get("name"),
                "file": info["file"],
                "tokens": _tokens(card.get("text") or ""),
                "race": tuple(sorted(card.get("races") or [])),
                "tier": card.get("tier") or 0,
                "hooks": tuple(info.get("hooks") or []),
            }
        )
    return index


def nearest_at_script(
    card: Dict[str, Any], hooks: List[str], index: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """按文本 Jaccard + 同种族/同 tier/同 hook 签名挑最接近的 AT 脚本（确定性）。"""
    target = _tokens(card.get("text") or "")
    target_race = tuple(sorted(C.race_name(card.get("card_race")) for _ in [0]))
    target_tier = card.get("tech_level") or 0
    target_hooks = set(hooks)
    best: Optional[Dict[str, Any]] = None
    best_key: Tuple[float, str] = (-1.0, "")
    for cand in index:
        if not cand["tokens"] and not target:
            jac = 0.0
        else:
            inter = len(target & cand["tokens"])
            union = len(target | cand["tokens"]) or 1
            jac = inter / union
        score = jac
        if cand["tier"] == target_tier:
            score += 0.03
        if cand["hooks"] and target_hooks:
            score += 0.05 * (len(set(cand["hooks"]) & target_hooks) / max(1, len(target_hooks)))
        key = (round(score, 6), cand["id"])
        if key > best_key:
            best_key = key
            best = cand
    if best is None:
        return None
    return {
        "id": best["id"],
        "name": best["name"],
        "file": best["file"],
        "similarity": round(best_key[0], 4),
        "hooks": list(best["hooks"]),
    }


def hsrl2_ref(cid: str, extras: Dict[str, Any]) -> Dict[str, Any]:
    ids: Set[str] = extras.get("ids") or set()
    files = extras.get("script_files") or {}
    normal = C.normal_form(cid)
    targets = [cid] if cid == normal else [cid, normal]
    hit_files: List[str] = []
    scripted = False
    for t in targets:
        if t in ids:
            scripted = True
        for f in files.get(t, []):
            if f not in hit_files:
                hit_files.append(f)
    return {"scripted": scripted, "files": sorted(hit_files)}


# ══════════════════════════════════════════════════════════════════════
# changed 判定
# ══════════════════════════════════════════════════════════════════════
def compare_shared(
    cid: str,
    at_card: Dict[str, Any],
    ds37_card: Dict[str, Any],
    compare_cost: bool = True,
) -> Optional[Dict[str, Any]]:
    """比较同 id 卡在 36.6.3 / 37.0.0 两版数据的差异；无差异返回 None。

    ``compare_cost``: 随从的 AT cost 字段是 0（BG 购买价固定 3 金币，AT 数据
    约定），与 37 的 cost=3 不可比 → 随从类 kind 传 False。
    """
    fields: List[str] = []
    detail: Dict[str, Any] = {}
    # tier（AT: tier / 37: tech_level）
    at_tier = at_card.get("tier")
    ds_tier = ds37_card.get("tech_level")
    if ds_tier is not None and at_tier is not None and int(ds_tier) != int(at_tier):
        fields.append("tier")
        detail["tier"] = [at_tier, ds_tier]
    # atk/hp/cost
    pairs = [("atk", "atk", "atk"), ("hp", "hp", "health")]
    if compare_cost:
        pairs.append(("cost", "cost", "cost"))
    for name, at_key, ds_key in pairs:
        a, b = at_card.get(at_key), ds37_card.get(ds_key)
        if a is not None and b is not None and int(a) != int(b):
            fields.append(name)
            detail[name] = [a, b]
    # 种族（AT races 名列表 vs 37 card_race ∪ race_tags；MECH ↔ MECHANICAL 归一）
    at_races = sorted(at_card.get("races") or [])
    ds_races = C.ds37_races(ds37_card)
    if at_races or ds_races:
        norm_at = sorted("MECHANICAL" if r == "MECH" else r for r in at_races)
        if norm_at != ds_races:
            fields.append("races")
            detail["races"] = [norm_at, ds_races]
    # 文本（结构 / 数字 / 占位符可解性三态；37 的 {i} 用 script_data_num 还原）
    nums = C.ds37_nums(ds37_card)
    cmp = C.compare_texts(at_card.get("text"), ds37_card.get("text"), nums)
    text_same = cmp["text_same"]
    unverified: Optional[Dict[str, Any]] = None
    if not text_same:
        if cmp["structure_same"] and cmp["numbers_state"] == "unverified":
            # 结构相同、但 37 有解不出的占位符 → 无法断言数字变化，单列 unverified
            unverified = {
                "id": cid,
                "fields": fields,
                "reason": "37 文本含未解析的 {i} 占位符（script_data_num 缺失），数字无法对拍",
                "at_text": at_card.get("text"),
                "ds37_text": C.solo_text(ds37_card.get("text")),
            }
        else:
            fields.append("text")
            if cmp["structure_same"]:
                detail["text"] = "numbers_changed"
            elif cmp["numbers_state"] == "same":
                detail["text"] = "wording_changed"
            else:
                detail["text"] = "text_changed"
            detail["at_text"] = at_card.get("text")
            detail["ds37_text"] = C.solo_text(ds37_card.get("text"))
    if not fields:
        return {"unverified": unverified} if unverified else None
    return {"id": cid, "fields": fields, "detail": detail, "unverified": unverified}


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════
#: 37 缺失卡文本里出现的“机制族关键词” → AT 侧对应原语/系统（源码核实位置）
SYSTEM_KEYWORDS = (
    ("Deity", "AT 有 Deity 系统：state.rs Player.deity + content/mod.rs::buff_deity/deity_awakened"),
    ("discard", "AT 有 Discard：event.rs ev::DISCARDED + content/mod.rs::on_discard"),
    ("Discard", "AT 有 Discard：event.rs ev::DISCARDED + content/mod.rs::on_discard"),
    ("Spellcraft", "AT 有 Spellcraft：cards.rs spellcraft_id/engine.rs"),
    ("Quest", "AT 有任务系统：state.rs Pending::Quest + content/quests.rs"),
    ("Buddy", "AT 有伙伴系统：content/buddies_*.rs + buddy_pool()"),
    ("Trinket", "AT 有饰品系统：state.rs Pending::Trinket + content/trinkets_p*.rs"),
    ("Timewarp", "AT 有 Timewarp 系统：content/timewarp.rs + state.rs Pending::Timewarp"),
    ("Aberration", "AT 有 Aberration 种族：types.rs Races::ABERRATION + content/aberrations.rs"),
    ("Anomaly", "**AT 无**异变系统（crates/taverngym/src 0 命中 anomaly 实现）"),
    ("Pass", "Duos 语义（37 文本仅出现在 @ 后段 Duos 变体；hsrl2 F-08 裁定不实现）"),
    ("Chronum", "Timewarp 货币（AT experimental.rs / content/timewarp.rs）"),
)


def _p1_must_have(
    kinds_out: Dict[str, Any],
    ds37_kinds: Dict[str, Any],
    at: Dict[str, Any],
    by_id: Dict[str, Dict[str, Any]],
    extras: Dict[str, Any],
) -> Dict[str, Any]:
    """P1 must-have（“37.0.0 可用”最小内容集）的脚本化计算。"""

    def ids(kind: str) -> List[str]:
        e = kinds_out.get(kind) or {}
        return [mc["id"] for mc in e.get("missing_cards") or []]

    duos_artifacts = {
        d["id"]
        for d in []
    }
    # 37 池里混入的 Duos-only 卡（BG31_242/243/244）单独剔除
    duos_pool_spells = {"BG31_242", "BG31_243", "BG31_244"}
    pool_minions = ids("pool_minions")
    hero_powers = ids("hero_main_power")
    pool_spells_all = ids("pool_spells")
    pool_spells_real = [c for c in pool_spells_all if c not in duos_pool_spells]
    tier7 = ids("tier7")
    dark_gifts = ids("dark_gifts")
    trinkets_all = ids("trinkets")
    trinkets_37_new = [c for c in trinkets_all if c.startswith("BG36")]
    offerable = set(extras.get("trinket_offerable") or [])
    trinkets_offerable_missing = sorted(
        c for c in trinkets_all if (not offerable) or c in offerable
    )
    # 去重后的严格 P1 卡数（BG27_514 同时属于 T7 与池内随从）
    strict = len(
        set(pool_minions + hero_powers + pool_spells_real + tier7 + dark_gifts)
    )
    # 严格 P1 工作量：按 strict id 逐卡统计难度（饰品单列）
    difficulty_of: Dict[str, str] = {}
    for kind, e in kinds_out.items():
        for mc in e.get("missing_cards") or []:
            difficulty_of[mc["id"]] = mc["difficulty"]
    strict_ids = sorted(
        set(pool_minions + hero_powers + pool_spells_real + tier7 + dark_gifts)
    )
    workload: Dict[str, int] = {}
    for cid in strict_ids:
        d = difficulty_of.get(cid, "?")
        workload[d] = workload.get(d, 0) + 1
    trinket_workload = dict(
        sorted((kinds_out.get("trinkets") or {}).get("missing_by_difficulty", {}).items())
    )
    return {
        "definition": "P1 最小内容集 = 37 池内随从 + 主英雄技能 + 池内酒馆法术（剔除 Duos-only 数据伪影）+ T7 + 黑暗赠礼；饰品按 37 新增(BG36)+可提供池两档统计",
        "pool_minions": {"count": len(pool_minions), "ids": pool_minions},
        "hero_main_powers": {"count": len(hero_powers), "ids": hero_powers},
        "pool_spells_real": {
            "count": len(pool_spells_real),
            "ids": pool_spells_real,
            "excluded_duos_only": sorted(duos_pool_spells & set(pool_spells_all)),
        },
        "tier7": {"count": len(tier7), "ids": tier7},
        "dark_gifts": {"count": len(dark_gifts), "ids": dark_gifts},
        "trinkets_37_new_bg36": {
            "count": len(trinkets_37_new),
            "ids": trinkets_37_new,
        },
        "trinkets_offerable_missing": {
            "count": len(trinkets_offerable_missing),
            "note": "hsrl2 db.trinket_offer_pool() 口径（357）；37 轮换池标志不在数据里，需人工裁减",
        },
        "strict_total_cards": strict,
        "workload_by_difficulty": dict(sorted(workload.items())),
        "trinkets_workload_by_difficulty": trinket_workload,
    }


def _trigger_inventory(
    kinds_out: Dict[str, Any],
    by_id: Dict[str, Dict[str, Any]],
    at_cards: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """37 缺失/新增卡文本里的机制族关键词 → AT 原语对照（计数 + 样例）。"""
    counts: Dict[str, int] = {}
    examples: Dict[str, List[str]] = {}
    for kind in ("pool_minions", "pool_spells", "tavern_spells_all", "trinkets",
                 "hero_powers", "dark_gifts", "quest_rewards", "anomalies", "tier7"):
        e = kinds_out.get(kind) or {}
        for mc in e.get("missing_cards") or []:
            card = by_id.get(mc["id"]) or {}
            text = C.solo_text(card.get("text"))
            for word, why in SYSTEM_KEYWORDS:
                if word in text:
                    counts[word] = counts.get(word, 0) + 1
                    examples.setdefault(word, [])
                    if len(examples[word]) < 5 and mc["id"] not in examples[word]:
                        examples[word].append(mc["id"])
    return {
        "keywords": [
            {"word": w, "why": why, "missing_cards_hits": counts.get(w, 0),
             "examples": examples.get(w, [])}
            for w, why in SYSTEM_KEYWORDS
            if counts.get(w, 0) > 0
        ],
        "no_hit_keywords": [w for w, _ in SYSTEM_KEYWORDS if not counts.get(w, 0)],
    }


def compute(at_doc: Dict[str, Any], ds37: Dict[str, Any]) -> Dict[str, Any]:
    at = build_at(at_doc, ds37["at_cards"])
    extras = load_hsrl2_extras()
    at_cards = ds37["at_cards"]
    by_id = ds37["by_id"]

    # hero 主技能映射（37 侧）与 AT 侧 hero_power 字段
    hero_main_power = build_ds37(ds37, extras)["hero_main_power"]

    def covered(kind: str, cid: str) -> bool:
        if kind == "heroes":
            power = hero_main_power.get(cid)
            return bool(power) and at["at_has_script"](power)
        return at["at_implemented"](cid)

    at_hook_hist: Dict[str, int] = {}
    for info in at["registry"].values():
        for h in info.get("hooks") or []:
            at_hook_hist[h] = at_hook_hist.get(h, 0) + 1

    sim_index = build_at_similarity_index(at_cards, at["registry"])

    kinds_out: Dict[str, Any] = {}
    summary_rows: List[Dict[str, Any]] = []
    missing_pool_minions_rows: List[Dict[str, Any]] = []
    ds37_kinds = build_ds37(ds37, extras)["kinds"]

    at_pools = at["pools"]
    # timewarp：37 数据无池标志，用“AT Timewarp 池 ∩ 37 数据存在”定义（253/253 存在）
    ds37_kinds["timewarp"] = {
        "definition": "37 数据中存在的 AT Timewarp 池卡（AT pools.timewarp ∩ 37 卡表；253）",
        "set": sorted(cid for cid in at_pools["timewarp"] if cid in by_id),
    }
    at_total_override = {
        "pool_minions": len(at_pools["pool_minions"]),
        "heroes": len(at_pools["heroes"]),
        "hero_powers": len(at_pools["hero_powers"]),
        "pool_spells": len(at_pools["pool_spells"]),
        "tavern_spells_all": len(at_pools["tavern_spells_all"]),
        "trinkets": len(at["trinket_defs"]),
        "quest_rewards": len(at_pools["quest_rewards"]),
        "dark_gifts": len(at_pools["dark_gifts"]),
        "anomalies": 0,
        "timewarp": len(at_pools["timewarp"]),
        "tier7": len(at_pools["tier7"]),
        "buddies": len(at_pools["buddies"]),
        "quests": len(at_pools["quests"]),
        "hero_main_power": len(at_pools["hero_powers"]),
    }
    at_impl_override = {
        "pool_minions": sum(1 for c in at_pools["pool_minions"] if at["at_implemented"](c)),
        "heroes": sum(
            1
            for h in at_pools["heroes"]
            if (at_cards.get(h, {}).get("hero_power") or "") in at["scripted"]
        ),
        "hero_powers": sum(1 for c in at_pools["hero_powers"] if at["at_has_script"](c)),
        "pool_spells": sum(1 for c in at_pools["pool_spells"] if at["at_implemented"](c)),
        "tavern_spells_all": sum(
            1 for c in at_pools["tavern_spells_all"] if at["at_has_script"](c)
        ),
        "trinkets": sum(1 for c in at["trinket_defs"] if at["at_has_script"](c)),
        "quest_rewards": sum(1 for c in at_pools["quest_rewards"] if at["at_implemented"](c)),
        "dark_gifts": sum(1 for c in at_pools["dark_gifts"] if at["at_has_script"](c)),
        "anomalies": 0,
        "timewarp": sum(1 for c in at_pools["timewarp"] if at["at_implemented"](c)),
        "tier7": sum(1 for c in at_pools["tier7"] if at["at_implemented"](c)),
        "buddies": sum(1 for c in at_pools["buddies"] if at["at_has_script"](c)),
        "quests": sum(1 for c in at_pools["quests"] if at["at_has_script"](c)),
        "hero_main_power": sum(
            1
            for h in at_pools["heroes"]
            if (at_cards.get(h, {}).get("hero_power") or "") in at["scripted"]
        ),
    }

    for kind, spec in ds37_kinds.items():
        if kind == "hero_main_power":
            continue
        ds_ids = spec["set"]
        # timewarp/buddies/quests 在 37 侧无池标志：限制为“37 数据中存在的 AT 池 id”
        if kind in ("timewarp", "buddies"):
            ds_ids = [cid for cid in ds_ids if cid in by_id]
        ds_set = set(ds_ids)
        at_set = set(at_pools.get(kind, []))
        shared = sorted(ds_set & at_set)
        missing = sorted(cid for cid in ds_set if not covered(kind, cid))
        extra = sorted(at_set - ds_set)
        changed: List[Dict[str, Any]] = []
        unverified: List[Dict[str, Any]] = []
        for cid in shared:
            if not covered(kind, cid):
                continue
            at_card = at_cards.get(cid)
            ds_card = by_id.get(cid)
            if at_card is None or ds_card is None:
                continue
            diff = compare_shared(
                cid, at_card, ds_card, compare_cost=kind not in MINION_LIKE_KINDS
            )
            if diff is None:
                continue
            if diff.get("unverified"):
                unverified.append(diff["unverified"])
            if "fields" not in diff:
                continue
            diff.pop("unverified", None)
            diff["at_scripted"] = at["at_has_script"](cid)
            diff["at_keyword_only"] = C.keyword_only(at_card.get("text"))
            changed.append(diff)
        changed.sort(key=lambda d: d["id"])

        missing_cards: List[Dict[str, Any]] = []
        for cid in missing:
            card = by_id.get(cid) or {}
            hooks = C.hook_families(card)
            difficulty, reasons = classify_difficulty(card, hooks)
            if kind == "anomalies":
                difficulty, reasons = "L", ["AT 无异变系统（全局开局覆写），需 Rust 新系统"]
            name = card.get("name")
            if kind == "heroes":
                power = hero_main_power.get(cid)
                power_card = by_id.get(power or "") or {}
                name = f"{name} / {power_card.get('name')}"
                hooks = C.hook_families(power_card)
                difficulty, reasons = classify_difficulty(power_card, hooks)
            missing_cards.append(
                {
                    "id": cid,
                    "name": name,
                    "text": C.solo_text(card.get("text")),
                    "tier": card.get("tech_level"),
                    "races": [C.race_name(card.get("card_race"))]
                    if card.get("card_race") is not None
                    else [],
                    "cost": card.get("cost"),
                    "atk": card.get("atk"),
                    "hp": card.get("health"),
                    "hooks": hooks,
                    "difficulty": difficulty,
                    "difficulty_reasons": reasons,
                    "at_missing_primitives": C.at_missing_primitives(card),
                    "hsrl2": hsrl2_ref(cid, extras),
                    "at_nearest_script": nearest_at_script(card, hooks, sim_index),
                    "new_in_37": cid not in at_cards,
                }
            )
        extra_cards = [
            {
                "id": cid,
                "name": (at_cards.get(cid) or {}).get("name"),
                "at_kind": (at_cards.get(cid) or {}).get("kind"),
                "in_37_data": cid in by_id,
                "in_37_kind_set": cid in ds_set,
            }
            for cid in extra
        ]
        # 37 新增（不在 36.6.3 数据里）的卡
        new_in_37 = sorted(cid for cid in ds_set if cid not in at_cards)
        diff_counter: Dict[str, int] = {}
        for d in changed:
            for f in d["fields"]:
                diff_counter[f] = diff_counter.get(f, 0) + 1
        diff_by_difficulty: Dict[str, int] = {}
        for mc in missing_cards:
            k = mc["difficulty"]
            diff_by_difficulty[k] = diff_by_difficulty.get(k, 0) + 1
        entry = {
            "definition": spec["definition"],
            "at_total": at_total_override.get(kind),
            "at_implemented": at_impl_override.get(kind),
            "ds37_total": len(ds_set),
            "shared": len(shared),
            "covered": len(ds_set) - len(missing),
            "missing": len(missing),
            "extra": len(extra),
            "changed": len(changed),
            "changed_by_field": dict(sorted(diff_counter.items())),
            "missing_by_difficulty": dict(sorted(diff_by_difficulty.items())),
            "new_in_37": len(new_in_37),
            "missing_cards": missing_cards,
            "extra_cards": extra_cards,
            "changed_cards": changed,
            "unverified_cards": sorted(unverified, key=lambda d: d["id"]),
            "new_in_37_ids": new_in_37,
        }
        kinds_out[kind] = entry
        summary_rows.append(
            {
                "kind": kind,
                "at_implemented": entry["at_implemented"],
                "ds37_total": entry["ds37_total"],
                "covered": entry["covered"],
                "missing": entry["missing"],
                "extra": entry["extra"],
                "changed": entry["changed"],
                "new_in_37": entry["new_in_37"],
                "missing_by_difficulty": entry["missing_by_difficulty"],
            }
        )
        if kind == "pool_minions":
            for mc in missing_cards:
                missing_pool_minions_rows.append(mc)

    # ── 主英雄技能覆盖（118 个主技能，heroes 口径的底层集合）──
    main_ids = ds37_kinds.get("hero_main_power", {}).get("set", [])
    main_missing = sorted(cid for cid in main_ids if not at["at_has_script"](cid))
    kinds_out["hero_main_power"] = {
        "definition": ds37_kinds["hero_main_power"]["definition"],
        "at_total": at_total_override.get("hero_main_power"),
        "at_implemented": at_impl_override.get("hero_main_power"),
        "ds37_total": len(main_ids),
        "shared": len(main_ids),
        "covered": len(main_ids) - len(main_missing),
        "missing": len(main_missing),
        "extra": 0,
        "changed": 0,
        "changed_by_field": {},
        "missing_by_difficulty": {},
        "new_in_37": 0,
        "missing_cards": [
            {
                "id": cid,
                "name": (by_id.get(cid) or {}).get("name"),
                "text": C.solo_text((by_id.get(cid) or {}).get("text")),
                "hooks": C.hook_families(by_id.get(cid) or {}),
                "difficulty": classify_difficulty(by_id.get(cid) or {}, C.hook_families(by_id.get(cid) or {}))[0],
                "hsrl2": hsrl2_ref(cid, extras),
                "new_in_37": cid not in at_cards,
            }
            for cid in main_missing
        ],
        "extra_cards": [],
        "changed_cards": [],
        "new_in_37_ids": [],
    }
    _mp = kinds_out["hero_main_power"]["missing_cards"]
    kinds_out["hero_main_power"]["missing_by_difficulty"] = dict(
        sorted(
            {
                d: sum(1 for mc in _mp if mc["difficulty"] == d)
                for d in {mc["difficulty"] for mc in _mp}
            }.items()
        )
    )

    # ── 37 侧“新增 id”分类（37 数据有、36.6.3 AT 数据无）──
    new_ids = sorted(cid for cid in by_id if cid not in at_cards)
    new_anomaly = [c for c in new_ids if "Anomaly" in c]
    new_ui = [
        c for c in new_ids
        if "Button" in c or "BuddyMeter" in c or "DragBuy" in c or "DragSell" in c
    ]
    new_other = [c for c in new_ids if c not in set(new_anomaly) | set(new_ui)]
    new_in_37_all = {
        "total": len(new_ids),
        "anomaly": new_anomaly,
        "ui_button_token": new_ui,
        "other": new_other,
        "other_cards": [
            {
                "id": cid,
                "name": (by_id.get(cid) or {}).get("name"),
                "card_type": (by_id.get(cid) or {}).get("card_type"),
                "sources": ds37["source"].get(cid, []),
            }
            for cid in new_other
        ],
    }

    # ── AT 脚本引用的 id 在 37 数据中不存在（真正“已移除内容”）──
    absent = sorted(cid for cid in at["registry"] if cid not in by_id)
    at_scripts_absent = [
        {
            "id": cid,
            "at_kind": (at_cards.get(cid) or {}).get("kind"),
            "at_pools": (at_cards.get(cid) or {}).get("pools", []),
            "at_name": (at_cards.get(cid) or {}).get("name"),
            "at_file": at["registry"][cid].get("file"),
        }
        for cid in absent
    ]

    # ── 池子成员变化（37 vs AT 同 kind 池集合）──
    pool_membership: Dict[str, Any] = {}
    for kind in ("pool_minions", "pool_spells", "trinkets", "tier7", "heroes"):
        spec = ds37_kinds.get(kind)
        if not spec:
            continue
        at_set = set(at_pools.get(kind, []))
        ds_set = set(spec["set"])
        added = sorted(ds_set - at_set)
        removed = sorted(at_set - ds_set)
        pool_membership[kind] = {
            "ds37_only": added,
            "at_only": removed,
            "ds37_only_cards": [
                {
                    "id": cid,
                    "name": (by_id.get(cid) or {}).get("name"),
                    "tier": (by_id.get(cid) or {}).get("tech_level"),
                    "races": [C.race_name((by_id.get(cid) or {}).get("card_race"))]
                    if (by_id.get(cid) or {}).get("card_race") is not None
                    else [],
                    "at_has_script": at["at_has_script"](cid),
                }
                for cid in added
            ],
            "at_only_cards": [
                {
                    "id": cid,
                    "name": (at_cards.get(cid) or {}).get("name"),
                    "in_37_data": cid in by_id,
                }
                for cid in removed
            ],
        }

    # ── 数据伪影：37 池里混入 Duos-only 卡（文本含 teammate / Pass）──
    data_artifacts = []
    for kind in ("pool_spells", "pool_minions", "trinkets", "tavern_spells_all"):
        spec = ds37_kinds.get(kind)
        if not spec:
            continue
        for cid in spec["set"]:
            card = by_id.get(cid) or {}
            text = C.solo_text(card.get("text"))
            if re.search(r"teammate|\bPass\b", text) or cid.startswith("BGDUO"):
                data_artifacts.append(
                    {
                        "kind": kind,
                        "id": cid,
                        "name": card.get("name"),
                        "reason": "Duos-only 文本（teammate/Pass）混入单人池集合",
                        "text": text,
                    }
                )

    # 饰品“可提供池”附加统计
    offerable = extras.get("trinket_offerable")
    trinket_offerable_stats = None
    if offerable:
        ds_offer = set(offerable)
        cov = sum(1 for cid in ds_offer if at["at_has_script"](cid))
        trinket_offerable_stats = {
            "ds37_offerable": len(ds_offer),
            "covered_by_at": cov,
            "missing": len(ds_offer) - cov,
            "at_offer_pool": len(at_pools["trinkets"]),
            "at_offer_pool_implemented": at_impl_override["trinkets"],
        }

    return {
        "schema": "p2_delta/coverage_matrix/v1",
        "inputs": {
            "at": {
                "root": at_doc["at_root"],
                "client_version": at_doc["at_meta"].get("client_version"),
                "cards_json_sha256": at_doc["cards_json_sha256"],
                "registry_size": len(at["registry"]),
            },
            "ds37": {
                "patch": ds37["summary"].get("patch"),
                "total_bg_cards": ds37["summary"].get("total_bg_cards"),
            },
            "hsrl2": {
                "registry_ok": extras.get("registry_ok"),
                "registry_error": extras.get("registry_error"),
                "registry_size": extras.get("registry_size"),
                "trinket_offerable": len(offerable) if offerable else None,
                "quest_defs": len(extras["quest_ids"]) if extras.get("quest_ids") else None,
            },
        },
        "definitions": {
            "at_implemented": "content scripts() 注册（scripted）或 keyword-only（复刻 script.rs::implemented_uncached）",
            "coverage": "37 集合中，卡 id 在 AT 注册表 + 金色/本体归一后可见（heroes 用主技能判定）",
            "difficulty": "S=纯关键词/无触发 hook；M=单触发 hook；L=多触发 hook 或 AT 无对应原语（规则见 compare_37.py::classify_difficulty）",
            "changed": "两版都存在且 AT 已实现；tier/atk/hp/cost/种族/文本结构/文本数字任一不同",
            "kinds": build_ds37(ds37, extras)["meta"],
        },
        "at_hook_histogram": dict(sorted(at_hook_hist.items())),
        "summary": summary_rows,
        "kinds": kinds_out,
        "p1_must_have": _p1_must_have(kinds_out, ds37_kinds, at, by_id, extras),
        "trigger_inventory": _trigger_inventory(kinds_out, by_id, at_cards),
        "trinket_offerable": trinket_offerable_stats,
        "new_in_37_all": new_in_37_all,
        "at_scripts_absent_from_37": at_scripts_absent,
        "pool_membership": pool_membership,
        "data_artifacts": data_artifacts,
        "at_implemented_report": at_doc["implemented_report"],
        "at_summary": at_doc["summary"],
    }


# ══════════════════════════════════════════════════════════════════════
# markdown 输出
# ══════════════════════════════════════════════════════════════════════
KIND_LABEL = {
    "pool_minions": "池内随从",
    "heroes": "英雄（主技能）",
    "hero_powers": "英雄技能（含变体）",
    "pool_spells": "池内酒馆法术",
    "tavern_spells_all": "酒馆法术全量",
    "trinkets": "饰品",
    "quest_rewards": "任务奖励",
    "dark_gifts": "黑暗赠礼",
    "anomalies": "异变",
    "timewarp": "Timewarp（AT 池）",
    "tier7": "Tier 7 随从",
    "buddies": "伙伴（非池）",
    "quests": "任务卡",
}


def md_escape(s: Optional[str], limit: int = 160) -> str:
    if not s:
        return ""
    t = re.sub(r"\s+", " ", s).replace("|", "\\|")
    return t[:limit] + ("…" if len(t) > limit else "")


def render_summary_md(matrix: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# P2-C 覆盖矩阵摘要（脚本生成，勿手改）\n")
    lines.append(
        f"> 由 `tools/p2_delta/compare_37.py` 生成。AT 数据 = TavernGym 1.0.0 / "
        f"客户端 {matrix['inputs']['at']['client_version']}；37 数据 = "
        f"{matrix['inputs']['ds37']['patch']}。\n"
    )
    lines.append("## 1. 分 kind 覆盖统计\n")
    lines.append("| kind | AT 已实现 | 37 总数 | AT 覆盖 | 缺失 | AT 独有(extra) | 变更(changed) | 37 新增(new) |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in matrix["summary"]:
        label = KIND_LABEL.get(row["kind"], row["kind"])
        lines.append(
            "| {label} (`{kind}`) | {ai} | {dt} | {cov} | {miss} | {ex} | {ch} | {new} |".format(
                label=label,
                kind=row["kind"],
                ai=row["at_implemented"],
                dt=row["ds37_total"],
                cov=row["covered"],
                miss=row["missing"],
                ex=row["extra"],
                ch=row["changed"],
                new=row["new_in_37"],
            )
        )
    lines.append("")
    t = matrix.get("trinket_offerable")
    if t:
        lines.append("### 饰品“商店可提供”子口径（hsrl2 `db.trinket_offer_pool()`）\n")
        lines.append("| 指标 | 值 |")
        lines.append("| --- | ---: |")
        for k, v in t.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    lines.append("## 2. 池内缺失随从（逐条）\n")
    pool = matrix["kinds"].get("pool_minions", {})
    lines.append("| # | Card ID | 名称 | Tier | 种族 | 难度 | 文本 | hsrl2 参考 | AT 最近脚本 |")
    lines.append("| ---: | --- | --- | ---: | --- | --- | --- | --- | --- |")
    for i, mc in enumerate(pool.get("missing_cards", []), 1):
        ref = mc["hsrl2"]
        ref_s = "; ".join(ref["files"][:2]) if ref["files"] else "—（hsrl2 也无脚本）"
        near = mc.get("at_nearest_script") or {}
        lines.append(
            "| {i} | `{id}` | {name} | {tier} | {races} | {diff} | {text} | {ref} | `{near}` ({sim}) |".format(
                i=i,
                id=mc["id"],
                name=md_escape(mc.get("name"), 40),
                tier=mc.get("tier") or "",
                races=", ".join(mc.get("races") or []),
                diff=mc["difficulty"],
                text=md_escape(mc.get("text"), 120),
                ref=md_escape(ref_s, 90),
                near=near.get("id", "—"),
                sim=near.get("similarity", ""),
            )
        )
    lines.append("")

    # P1 must-have
    p1 = matrix.get("p1_must_have") or {}
    if p1:
        lines.append("## 3. P1 must-have（“37.0.0 可用”最小内容集）\n")
        lines.append("| 子集 | 数量 | ids |")
        lines.append("| --- | ---: | --- |")
        for key in ("pool_minions", "hero_main_powers", "pool_spells_real", "tier7", "dark_gifts"):
            item = p1.get(key) or {}
            lines.append(
                f"| {key} | {item.get('count')} | " + ", ".join(f"`{i}`" for i in item.get("ids") or []) + " |"
            )
        lines.append(
            f"| **严格 P1 合计** | **{p1.get('strict_total_cards')}** | 工作量 {p1.get('workload_by_difficulty')} |"
        )
        t37 = p1.get("trinkets_37_new_bg36") or {}
        lines.append(
            f"| 饰品（37 新增 BG36） | {t37.get('count')} | "
            + ", ".join(f"`{i}`" for i in t37.get("ids") or [])
            + " |"
        )
        to = p1.get("trinkets_offerable_missing") or {}
        lines.append(f"| 饰品（可提供池口径缺脚本） | {to.get('count')} | 需人工按 37 轮换裁减 |")
        lines.append(f"| 饰品工作量（全 409 定义） | {p1.get('trinkets_workload_by_difficulty')} | |")
        lines.append("")

    # 池子成员变化
    pm = matrix.get("pool_membership") or {}
    if pm:
        lines.append("## 4. 池子成员变化（37 vs AT 36.6.3）\n")
        lines.append("| kind | 37 新增入池 | AT 出池 | 说明 |")
        lines.append("| --- | ---: | ---: | --- |")
        for kind, v in pm.items():
            lines.append(
                f"| {kind} | {len(v['ds37_only'])} | {len(v['at_only'])} | "
                f"37 入池: {', '.join('`'+c+'`' for c in v['ds37_only'][:8])}"
                f"{'…' if len(v['ds37_only'])>8 else ''} |"
            )
        lines.append("")

    # 37 新增 id / 数据伪影 / AT 已移除
    n37 = matrix.get("new_in_37_all") or {}
    lines.append("## 5. 37 数据侧新增 id 与数据伪影\n")
    lines.append(
        f"- 37 数据有、36.6.3 AT 数据无的 id 共 **{n37.get('total')}**："
        f"异变 {len(n37.get('anomaly') or [])}、UI 按钮/token {len(n37.get('ui_button_token') or [])}、"
        f"其它 {len(n37.get('other') or [])}。"
    )
    lines.append(f"- AT 脚本引用但 37 数据不存在的 id：{len(matrix.get('at_scripts_absent_from_37') or [])} "
                 f"（{', '.join('`'+c['id']+'`' for c in matrix.get('at_scripts_absent_from_37') or [])}）")
    artifacts = matrix.get("data_artifacts") or []
    artifact_ids = sorted({a["id"] for a in artifacts})
    lines.append(f"- Duos-only 文本混入单人池集合的卡：{len(artifact_ids)} 张，"
                 f"提示数据管线需剔除：{', '.join('`'+i+'`' for i in artifact_ids)}")
    lines.append("")

    # 机制族关键词对照
    ti = matrix.get("trigger_inventory") or {}
    if ti.get("keywords"):
        lines.append("## 6. 缺失卡文本中的机制族关键词 → AT 原语对照\n")
        lines.append("| 关键词 | 命中缺失卡数 | AT 对应原语/系统 | 样例 |")
        lines.append("| --- | ---: | --- | --- |")
        for kw in ti["keywords"]:
            lines.append(
                f"| {kw['word']} | {kw['missing_cards_hits']} | {kw['why']} | "
                + ", ".join(f"`{i}`" for i in kw["examples"]) + " |"
            )
        lines.append("")

    lines.append("## 7. 分 kind 缺失/变更清单\n")
    for kind, entry in matrix["kinds"].items():
        label = KIND_LABEL.get(kind, kind)
        lines.append(f"### {label} (`{kind}`)\n")
        lines.append(
            f"- AT 已实现 {entry['at_implemented']} / 37 共 {entry['ds37_total']}；"
            f"覆盖 {entry['covered']}，**缺失 {entry['missing']}**，"
            f"AT 独有 {entry['extra']}，变更 {entry['changed']}，37 新增 {entry['new_in_37']}。\n"
        )
        if entry["missing_cards"]:
            lines.append("| Card ID | 名称 | 难度 | hooks | hsrl2 参考 | AT 最近脚本 |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for mc in entry["missing_cards"]:
                ref = mc["hsrl2"]
                ref_s = "; ".join(ref["files"][:1]) if ref["files"] else "—"
                near = mc.get("at_nearest_script") or {}
                lines.append(
                    "| `{id}` | {name} | {diff} | {hooks} | {ref} | `{near}` |".format(
                        id=mc["id"],
                        name=md_escape(mc.get("name"), 40),
                        diff=mc["difficulty"],
                        hooks=",".join(mc.get("hooks") or []),
                        ref=md_escape(ref_s, 80),
                        near=near.get("id", "—"),
                    )
                )
            lines.append("")
        if entry.get("unverified_cards"):
            lines.append(f"未对拍（37 占位符无数据可解）：{len(entry['unverified_cards'])} 张 "
                         + ", ".join('`'+c['id']+'`' for c in entry['unverified_cards'][:20]))
            lines.append("")
        if entry["changed_cards"]:
            lines.append("| Card ID | 变化字段 | AT 脚本 | 详情 |")
            lines.append("| --- | --- | --- | --- |")
            for ch in entry["changed_cards"]:
                lines.append(
                    "| `{id}` | {fields} | {scripted} | {detail} |".format(
                        id=ch["id"],
                        fields=",".join(ch["fields"]),
                        scripted="script" if ch["at_scripted"] else "keyword-only",
                        detail=md_escape(json.dumps(ch["detail"], ensure_ascii=False), 140),
                    )
                )
            lines.append("")
    return "\n".join(lines) + "\n"


def render_missing_pool_minions_md(matrix: Dict[str, Any]) -> str:
    pool = matrix["kinds"]["pool_minions"]
    patch = matrix["inputs"]["ds37"]["patch"]
    at_ver = matrix["inputs"]["at"]["client_version"]
    lines = [
        "# 池内缺失随从逐条清单（37.0.0 池内、AT 36.6.3 未实现）\n",
        f"> 37 数据 = {patch}；AT = {at_ver}。"
        "覆盖判定与难度口径见 `docs/PORTING_37_PLAN.md` §2/§5。\n",
        "| # | Card ID | 名称 | Tier | 种族 | 攻/血 | 文本 | 难度 | hooks | hsrl2 参考脚本 | AT 最近可复用 | sim |",
        "| ---: | --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for i, mc in enumerate(pool["missing_cards"], 1):
        ref = mc["hsrl2"]
        ref_s = "<br>".join(f"`{f}`" for f in ref["files"][:2]) if ref["files"] else "—"
        near = mc.get("at_nearest_script") or {}
        stats = f"{mc.get('atk','')}/{mc.get('hp','')}" if mc.get("atk") is not None else ""
        lines.append(
            "| {i} | `{id}` | {name} | {tier} | {races} | {stats} | {text} | {diff} | {hooks} | {ref} | `{near}` | {sim} |".format(
                i=i,
                id=mc["id"],
                name=md_escape(mc.get("name"), 36),
                tier=mc.get("tier") or "",
                races=", ".join(mc.get("races") or []),
                stats=stats,
                text=md_escape(mc.get("text"), 110),
                diff=mc["difficulty"],
                hooks=",".join(mc.get("hooks") or []),
                ref=ref_s,
                near=near.get("id", "—"),
                sim=near.get("similarity", ""),
            )
        )
    lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--at-root", default=None)
    ap.add_argument("--at-content", default=str(C.RUNS_DIR / "at_content.json"))
    ap.add_argument("--out-dir", default=str(C.RUNS_DIR))
    ap.add_argument("--check", action="store_true", help="只校验输入、不写输出")
    args = ap.parse_args(argv)

    at_path = Path(args.at_content)
    if not at_path.exists():
        raise SystemExit(
            f"缺少 {at_path}，先运行 python3 tools/p2_delta/extract_at_content.py"
        )
    at_doc = C.read_json(at_path)
    ds = C.load_ds37()
    ds["at_cards"] = C.load_at_cards(C.at_root(args.at_root))["cards"]
    matrix = compute(at_doc, ds)

    out_dir = Path(args.out_dir)
    if args.check:
        print("[compare_37] --check: 输入与计算通过（未写文件）")
        for row in matrix["summary"]:
            print(
                f"  {row['kind']}: AT={row['at_implemented']} DS37={row['ds37_total']} "
                f"covered={row['covered']} missing={row['missing']} extra={row['extra']} "
                f"changed={row['changed']} new={row['new_in_37']}"
            )
        return 0

    C.write_json(out_dir / "coverage_matrix.json", matrix)
    (out_dir / "summary.md").write_text(render_summary_md(matrix), encoding="utf-8")
    (out_dir / "missing_pool_minions.md").write_text(
        render_missing_pool_minions_md(matrix), encoding="utf-8"
    )
    print(f"[compare_37] 输出目录: {out_dir}")
    for row in matrix["summary"]:
        print(
            f"  {row['kind']}: AT已实现={row['at_implemented']} 37总数={row['ds37_total']} "
            f"覆盖={row['covered']} 缺失={row['missing']} extra={row['extra']} "
            f"changed={row['changed']} 新增={row['new_in_37']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
