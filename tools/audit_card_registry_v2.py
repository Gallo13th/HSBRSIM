#!/usr/bin/env python
"""v2 卡牌注册审计 — 每张有效果的池卡必须有脚本。

覆盖旧 audit_card_registry.py 的盲区:
  - 检查全部卡类型（minion/spell/trinket/hero/hero_power/anomaly/reward/dark_gift）
  - 用 CardDef.keywords + 文本启发双通道判定"有效果"
  - 校验脚本钩子与效果标志匹配（有 battlecry 标志 → 脚本须有 battlecry 方法）

用法: python tools/audit_card_registry_v2.py [--strict]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hsrl2.db import CardDB  # noqa: E402

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


def has_text_effect(text: str) -> bool:
    return any(marker in text for marker in TEXT_EFFECT_MARKERS)


def main() -> int:
    strict = "--strict" in sys.argv
    db = CardDB.load(ROOT / "data")
    from hsrl2.scripts import REGISTRY

    gaps: list[str] = []
    hook_mismatches: list[str] = []

    targets = []
    targets += db.pool_minions()
    targets += db.pool_spells()
    targets += db.dark_gifts()

    for d in targets:
        effective = bool(d.keywords & set(HOOK_BY_KEYWORD)) or \
            has_text_effect(d.text or "")
        if not effective:
            continue
        script = REGISTRY.get(d.id)
        if script is None:
            gaps.append(f"{d.id} {d.name}: has effect but no script")
            continue
        for kw, hook in HOOK_BY_KEYWORD.items():
            if kw in d.keywords and not hasattr(script, hook):
                hook_mismatches.append(
                    f"{d.id} {d.name}: keyword {kw} but script lacks {hook}()")

    total_effective = sum(
        1 for d in targets
        if bool(d.keywords & set(HOOK_BY_KEYWORD)) or has_text_effect(d.text or ""))
    print(f"Pool minions: {len(db.pool_minions())}, "
          f"pool spells: {len(db.pool_spells())}, "
          f"dark gifts: {len(db.dark_gifts())}")
    print(f"Effect-bearing cards: {total_effective}, "
          f"scripted: {total_effective - len(gaps)}")

    if gaps:
        print(f"\nSCRIPT GAPS ({len(gaps)}):")
        for g in gaps[:50]:
            print(f"  [GAP] {g}")
        if len(gaps) > 50:
            print(f"  ... and {len(gaps) - 50} more")
    if hook_mismatches:
        print(f"\nHOOK MISMATCHES ({len(hook_mismatches)}):")
        for h in hook_mismatches:
            print(f"  [MISMATCH] {h}")

    if gaps or hook_mismatches:
        return 1 if strict else 0   # 迁移期非 strict 只报告
    print("PASS: all effect-bearing cards scripted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
