#!/usr/bin/env python
"""Scan active in-scope card scripts for DEFERRED/TODO/Simplified markers.

Uses actual module imports to correctly detect inherited methods,
eliminating false positives from AST-only analysis.

Usage:
    python tools/audit_for_simplified_scripts.py
    python tools/audit_for_simplified_scripts.py --strict   # fail on any WARN
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Card IDs that are allowed to be DEFERRED (require major engine subsystems) ──
ALLOWED_DEFERRED = {
    # ── Trinkets needing major engine subsystems ──
    "BG30_MagicItem_707",
    "BG30_MagicItem_426", "BG30_MagicItem_426t",  # Colorful Compass
    "BG30_MagicItem_703",   # Mystery Cube
    "BG30_MagicItem_705",   # Bartend-o-Tron's Oilcan
    "BG30_MagicItem_930",   # Burgling Claw
    "BG30_MagicItem_994",   # Yogg-Tastic Pastry (returns None)
    "BG30_MagicItem_416",   # Token of the Old Gods
    "BG35_MagicItem_812",   # Corrupted Tome
    "BG32_MagicItem_931",   # Azsharan Statuette
    "BG32_MagicItem_950",   # Gritty Portrait
    "BG32_MagicItem_951",   # Gold Pendant
    "BG35_MagicItem_712",   # Privateer Portrait
    "BG35_MagicItem_863",   # Avalanche Sticker
    "BG32_MagicItem_300",   # Putricide Sticker (returns None)
    "BG30_MagicItem_402",   # Conductor Portrait (discard system TODO)
    "BG30_MagicItem_991",   # Felbat Portrait (7-card tavern TODO)
    "BG32_MagicItem_271",   # Ornate Clock (greater trinket timing TODO)
    "BG32_MagicItem_824",   # Implicator Portrait (consume targeting TODO)
    "BG35_MagicItem_848t",  # Egg of the Endtimes Portrait
    "BG35_MagicItem_922",   # Tide Raiser Portrait (combat spell copy TODO)
    # ── Anomalies needing engine subsystems ──
    # BG27_Anomaly_716, 755, 820 now implemented
    # BG27_Anomaly_Prizes2 now implemented: PrizeEvery4TurnsScript
    # BG31_Anomaly_102 now implemented: SoTGetEvolvingScrollScript
    # BG31_Anomaly_106 now implemented: AllHeroesMarinScript
    # BG31_Anomaly_111 now implemented: ElvenEliteScript
    # BG31_Anomaly_112 now implemented: IncubationMutationScript
    # BG31_Anomaly_114 now implemented: CopyLeftmostEvery2TurnsScript
    # ── Rewards ──
    "BG33_Reward_021",      # Rallying Cry (rally doubler)
    "BG26_135",             # Southsea Busker (Gold per friendly Pirate attack)
    # ── Keyword-only / tag-only minions ──
    "BG26_817",             # Blade Collector (CLEAVE tag)
    # ── Hero Powers ──
    "TB_BaconShop_HP_037a", # Wax Warband
    "TB_BaconShop_HERO_14", # Queen Wagtoggle
    # ── Trinket tokens ──
    "BG30_MagicItem_821t2", # Fishy Sticker (has SoC method)
    # ── Rewards (DEFERRED with methods) ──
    "BG33_Reward_006",      # Rushing Winds (spellcraft → DEFERRED)
    "BG33_Reward_010",      # Norgannon's Reward (Tier 7 → DEFERRED)
    # ── Patch 35.6.0 — New trinkets with Spellcraft (DEFERRED) ──
    "BG35_MagicItem_755",   # Chillmere Mosaic (spellcraft)
    "BG35_MagicItem_838",   # Double Stitch Needle (spellcraft)
    # ── Patch 35.6.0 — New anomalies (effects pending) ──
    # BG35_Anomaly_001 now implemented: FlyTheFlagScript
    # BG35_Anomaly_002 now implemented: AnomalousCubeScript
    # BG35_Anomaly_004 now implemented: AnomalousConfluxScript
    # BG35_Anomaly_005 now implemented: AnomalousTimelineScript
    # BG35_Anomaly_006 now implemented: AnomalousExpeditionScript
    # BG35_Anomaly_007 now implemented: LesserFortuneScript
    # BG35_Anomaly_008 now implemented: GreaterFortuneScript
}

# ── Known script hooks (methods that scripts can define) ──
SCRIPT_HOOKS = [
    # Minion hooks
    'battlecry', 'deathrattle', 'start_of_combat', 'end_of_turn',
    'start_of_turn', 'avenge', 'rally', 'on_sell', 'spellcraft',
    'on_summon', 'on_play', 'frenzy', 'atk', 'health', 'on_enter_hand',
    # Trinket hooks
    'on_buy', 'on_spend_gold', 'on_magnetized', 'on_tavern_refresh',
    'on_minion_bought', 'on_minion_sold', 'on_summon_in_combat',
    'on_friendly_death_combat', 'on_turn_begin', 'on_cast_spell',
    # Reward hooks
    'on_unlock',
    # Anomaly hooks
    'on_apply', 'on_upgrade',
    # Hero / Hero Power hooks
    'on_use', 'hero_power',
    # Counter / trigger
    'on_trigger', 'effect',
    # Combat
    'on_lose_divine_shield', 'on_friendly_attack', 'on_lose_venomous',
]

PROXY_MARKERS = ("Simplified", "approximation", "approx proxy")

# ── UI-only / token indicator classes (no gameplay effect needed) ──
UI_ONLY_CLASSES = {"UITimerScript"}


def scan_active_cards():
    """Import all card modules and check active script classes.

    Returns: list of (card_id, card_name, cls_name, issue_type, description)
    """
    # Import all card modules
    import hsrl.cards.minions  # noqa
    import hsrl.cards.spells  # noqa
    import hsrl.cards.trinkets  # noqa
    import hsrl.cards.rewards  # noqa  # noqa
    import hsrl.cards.anomalies  # noqa
    import hsrl.cards.heroes  # noqa

    from hsrl.core.card_db import CARDS
    from hsrl.core.enums import CardType

    issues = []

    for card_id, data in CARDS._cards.items():
        # Skip examples, tokens, duos
        if card_id.startswith(("EXAMPLE_", "BGDUO_", "TOKEN_")):
            continue

        cls = data.scripts
        if cls is None:
            # Some cards don't need scripts (keyword-only, UI)
            continue

        cls_name = cls.__name__
        doc = (cls.__doc__ or "").lower()

        # ── Check 1: DEFERRED/TODO markers in docstring ──
        has_deferred = "deferred" in doc
        has_todo = "todo" in doc
        has_proxy = any(m.lower() in doc for m in PROXY_MARKERS)

        if has_proxy:
            # Proxy/simplified markers are always flagged
            issues.append((card_id, data.name, cls_name, "PROXY",
                           f"Contains Simplified/approximation marker"))
        elif has_deferred or has_todo:
            if card_id not in ALLOWED_DEFERRED:
                issues.append((card_id, data.name, cls_name, "DEFERRED",
                               f"DEFERRED/TODO not in ALLOWED_DEFERRED whitelist"))

        # ── Check 2: Truly empty scripts (no inherited methods) ──
        if cls_name in UI_ONLY_CLASSES:
            continue
        if cls_name.startswith("_") or "Example" in cls_name:
            continue
        if card_id in ALLOWED_DEFERRED:
            continue  # Known deferred, empty is expected

        methods = [m for m in SCRIPT_HOOKS if hasattr(cls, m)]
        if not methods:
            # Verify it's not a keyword-only card (these are fine)
            keyword_only_types = {CardType.MINION}  # minions can be keyword-only
            if data.cardtype not in keyword_only_types or not _has_keyword_tag(data):
                issues.append((card_id, data.name, cls_name, "EMPTY",
                               f"No script hooks defined (no inherited methods)"))

    return issues


def _has_keyword_tag(data) -> bool:
    """Check if a card has keyword tags that don't need scripts."""
    from hsrl.core.enums import GameTag
    keyword_tags = {
        GameTag.TAUNT, GameTag.DIVINE_SHIELD, GameTag.POISONOUS,
        GameTag.VENOMOUS, GameTag.REBORN, GameTag.WINDFURY, GameTag.CLEAVE,
        GameTag.MAGNETIC, GameTag.BATTLECRY, GameTag.DEATHRATTLE,
        GameTag.START_OF_COMBAT, GameTag.RALLY, GameTag.Avenge,
        GameTag.SPELLCRAFT, GameTag.HEALTH_COST_DEMON, GameTag.HEALTH_COST_SPELL,
    }
    return any(t in data.tags for t in keyword_tags)


def main():
    strict = "--strict" in sys.argv

    try:
        issues = scan_active_cards()
    except Exception as e:
        print(f"[ERROR] Failed to scan: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Group by issue type
    from collections import Counter
    by_type = Counter(t for _, _, _, t, _ in issues)

    if issues:
        print(f"\nFound {len(issues)} issue(s): {dict(by_type)}")
        print()

        # Print by category
        for issue_type in ("PROXY", "DEFERRED", "EMPTY"):
            group = [(cid, name, cls, desc) for cid, name, cls, t, desc in issues
                     if t == issue_type]
            if group:
                print(f"─── {issue_type} ({len(group)}) ───")
                for cid, name, cls, desc in group:
                    print(f"  {cid}: {name} → {cls}")
                    print(f"       {desc}")
                print()

        if strict or by_type.get("PROXY", 0) > 0:
            print(f"[FAIL] {len(issues)} issue(s)")
            return 1

        print(f"[WARN] {len(issues)} issue(s) — review manually")
        return 0

    print("[PASS] No issues in active in-scope scripts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
