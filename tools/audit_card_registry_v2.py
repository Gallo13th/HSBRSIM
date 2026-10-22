#!/usr/bin/env python
"""v2 卡牌注册审计 — 每张有效果的卡必须有脚本，或登记在 DEFERRED 台账。

覆盖旧 audit_card_registry.py 的盲区:
  - 检查全部卡类型（minion/spell/trinket/hero/hero_power/anomaly/reward/dark_gift）
  - 用 CardDef.keywords + 文本启发双通道判定"有效果"
  - 校验脚本钩子与效果标志匹配（有 battlecry 标志 → 脚本须有 battlecry 方法）
  - Dark Gift 由引擎分派表（game._DARK_GIFT_EFFECTS）实现，非 REGISTRY

门禁（--strict 退出码）覆盖**迁移已完成**的三类:
  pool_minion / pool_spell / dark_gift
其余类别（英雄技能/饰品/异变/任务奖励/任务）以覆盖率报告形式输出，
不参与退出码——迁移期它们是进度仪表而非验收门。

用法: python tools/audit_card_registry_v2.py [--strict]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hsrl2.db import CardDB  # noqa: E402
from hsrl2.game import quest_defs_from_db  # noqa: E402
from hsrl2.tags import CardType  # noqa: E402

# 效果标志 → 必须存在的钩子
HOOK_BY_KEYWORD = {
    "battlecry": "battlecry",
    "deathrattle": "deathrattle",
    "start_of_combat": "start_of_combat",
    "rally": "rally",
    "activate": "activate",
}

# 文本启发: 出现这些短语即认为有效果（关键词兜底，防数据缺标志）
TEXT_EFFECT_MARKERS = [
    "Battlecry", "Deathrattle", "Start of Combat", "Avenge",
    "Rally:", "Activate (", "At the end of your turn",
    "At the start of your turn", "When you sell this",
    "After you", "Whenever", "Spellcraft", "spellcraft",
]

# ── DEFERRED 台账（门禁类别）──
# 有效果但确无权威语义/引擎依赖，按 SOP §6b 第 4 步撤注册并登记于此。
DEFERRED_LEDGER = {
    "BG33_319": "Rimescale Priestess — 'gives stats' 资格集无权威定义"
                "（wiki 无 Notes）; 撤注册等待实测/新信源",
}


def has_text_effect(text: str) -> bool:
    return any(marker in text for marker in TEXT_EFFECT_MARKERS)


def is_effective(d) -> bool:
    return bool(d.keywords & set(HOOK_BY_KEYWORD)) or \
        has_text_effect(d.text or "")


def _dark_gift_implemented() -> set[str]:
    """引擎分派表覆盖的 Dark Gift（game._DARK_GIFT_EFFECTS）∪ DEFERRED。"""
    import hsrl2.game as G
    from hsrl2 import darkgifts as DG
    return set(G._DARK_GIFT_EFFECTS) | set(DG.DEFERRED_GIFTS)


def _hero_power_ids(db: CardDB) -> list:
    """116 位英雄绑定的英雄技能（Tag380 → hero_power_id）。"""
    heroes = [d for d in db._by_id.values()
              if d.card_type == CardType.HERO and d.hero_power_id]
    return sorted({d.hero_power_id for d in heroes})


def check_gate(db, registry, dark_gifts_impl) -> list[str]:
    """门禁类别缺口。"""
    gaps: list[str] = []
    targets = []
    targets += [(d, "pool_minion") for d in db.pool_minions()]
    targets += [(d, "pool_spell") for d in db.pool_spells()]
    targets += [(d, "dark_gift") for d in db.dark_gifts()]
    for d, kind in targets:
        if kind == "dark_gift":
            effective = True       # Dark Gift 存在即有效果
            implemented = d.id in dark_gifts_impl
        else:
            effective = is_effective(d)
            implemented = d.id in registry
        if not effective:
            continue
        if implemented or d.id in DEFERRED_LEDGER:
            continue
        gaps.append(f"{d.id} {d.name}: has effect but no script [{kind}]")
    return gaps


def check_hooks(db, registry) -> list[str]:
    mismatches: list[str] = []
    targets = [d for d in db.pool_minions() if is_effective(d)]
    targets += [d for d in db.pool_spells() if is_effective(d)]
    targets += [d for d in db.dark_gifts()]
    for d in targets:
        script = registry.get(d.id)
        if script is None:
            continue
        for kw, hook in HOOK_BY_KEYWORD.items():
            if kw in d.keywords and not hasattr(script, hook):
                mismatches.append(
                    f"{d.id} {d.name}: keyword {kw} but script lacks {hook}()")
    return mismatches


# 任务**卡**口径: 直接调用引擎同源实现 `game.quest_defs_from_db()`
# （谓词 = `game.is_quest_card`: SPELL + tag 535 + id 含 "quest" +
# 非公告 token）。2026-09-18 对抗审查: 旧实现用 id 正则
# `_Quest_\d+$|_Quest$`，与 `audit_script_wiring.category_of` 的
# id 前缀/junction 口径**互异**（registry 含 `BG33_Anomaly_008_Quest`、
# wiring 含 `BG24_Quest_Bob`）——两处现在共用唯一谓词。
def _quest_defs(db) -> list:
    return quest_defs_from_db(db)


def report_coverage(db, registry, dark_gifts_impl) -> None:
    """非门禁类别的覆盖率（迁移进度仪表）。

    口径（2026-09-14 第二十二轮订正——仪表与**可实现集**对齐）:
      - `trinket` = `CardDB.trinket_offer_pool()`（商店可提供集）——
        此前用"全域 card_type=44"，把 `BG30_Trinket_1st/2nd` 内部报价
        token 与 `_t/_t2` 载荷升级变体也算进分母（379 里 48 张不是可
        实现项）。同口径见 `docs/agents/TRINKET_LEDGER.md`（331 张）。
      - `quest` = `hsrl2.game.quest_defs_from_db()`（**与引擎
        `Game.quest_defs()` 同源**，2026-09-18 对抗审查订正）——全族
        可进度化任务卡 20 张 = 19 注册 + `BG24_Quest_328`（DEFERRED）。
        两张公告 Spell token（`BG24_Quest_Bob` /
        `BG33_Anomaly_008_Quest`）与 task 无关，由 `_QUEST_ANNOUNCE_TOKENS`
        排除（旧 id 正则口径曾把它们之一计入分母 → 21）。
      - `quest_reward` 分母含两张**已注册父卡的载荷 token**
        （`BG28_Reward_518t` / `_G`，由 `batch_quest_rewards2` 的
        `BG28_Reward_518` 脚本 `create_minion` 生成）——非可实现缺口，
        沿用分母但在输出中标注。
    """
    groups: list[tuple[str, list]] = [
        ("hero_power", [db.get(i) for i in _hero_power_ids(db)]),
        ("trinket", list(db.trinket_offer_pool())),
        ("anomaly", [d for d in db._by_id.values()
                     if d.card_type == CardType.BACON_ANOMALY
                     and not d.is_golden_def]),
        ("quest_reward", [d for d in db._by_id.values()
                          if d.card_type == CardType.BACON_QUEST_REWARD
                          and not d.is_golden_def]),
        ("quest", _quest_defs(db)),
    ]
    print("\n覆盖率（非门禁——迁移进度）:")
    for name, items in groups:
        items = [d for d in items if d is not None]
        if not items:
            continue
        scripted = sum(1 for d in items if d.id in registry)
        note = ""
        if name == "trinket":
            all_t = [d for d in db._by_id.values()
                     if d.card_type == CardType.BACON_TRINKET
                     and not d.is_golden_def]
            note = (f"  （全域含 token/升级变体: "
                    f"{sum(1 for d in all_t if d.id in registry)}"
                    f"/{len(all_t)}）")
        elif name == "quest_reward":
            note = "  （含 2 张已注册父卡的载荷 token: 518t/_G）"
        print(f"  {name:14s}: {scripted}/{len(items)} 注册"
              f"（{100 * scripted // max(1, len(items))}%）{note}")


def main() -> int:
    strict = "--strict" in sys.argv
    db = CardDB.load(ROOT / "data")
    from hsrl2.scripts import REGISTRY

    dark_gifts_impl = _dark_gift_implemented()
    gaps = check_gate(db, REGISTRY, dark_gifts_impl)
    hook_mismatches = check_hooks(db, REGISTRY)

    print(f"Pool minions: {len(db.pool_minions())}, "
          f"pool spells: {len(db.pool_spells())}, "
          f"dark gifts: {len(db.dark_gifts())}")
    n_eff = sum(1 for d in list(db.pool_minions()) + list(db.pool_spells())
                if is_effective(d)) + len(db.dark_gifts())
    print(f"Gate effective cards: {n_eff}, "
          f"implemented/ledgered: {n_eff - len(gaps)}")

    if gaps:
        print(f"\nSCRIPT GAPS ({len(gaps)}):")
        for g in gaps[:50]:
            print(f"  [GAP] {g}")
        if len(gaps) > 50:
            print(f"  ... and {len(gaps) - 50} more")
    if hook_mismatches:
        print(f"\nHOOK MISMATCHES ({len(hook_mismatches)}):")
        for h in hook_mismatches[:50]:
            print(f"  [MISMATCH] {h}")

    report_coverage(db, REGISTRY, dark_gifts_impl)
    if DEFERRED_LEDGER:
        print(f"\nDEFERRED 台账 ({len(DEFERRED_LEDGER)}):")
        for cid, why in DEFERRED_LEDGER.items():
            print(f"  [DEFERRED] {cid}: {why}")

    if gaps or hook_mismatches:
        return 1 if strict else 0   # 迁移期非 strict 只报告
    print("\nPASS: all gate effect-bearing cards scripted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
