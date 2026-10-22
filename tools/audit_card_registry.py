#!/usr/bin/env python
"""Audit active pool cards: check every effect-tagged card has a script class.

Usage:
    python tools/audit_card_registry.py
    python tools/audit_card_registry.py --verbose

Returns exit code 0 if all active cards with effects have scripts, 1 otherwise.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hsrl.core.card_db import CARDS
from hsrl.core.enums import CardType, GameTag

TRIGGER_TAGS = {
    GameTag.BATTLECRY: "Battlecry",
    GameTag.DEATHRATTLE: "Deathrattle",
    GameTag.Avenge: "Avenge",
    GameTag.RALLY: "Rally",
    GameTag.START_OF_COMBAT: "Start of Combat",
    GameTag.END_OF_TURN: "End of Turn",
    GameTag.START_OF_TURN: "Start of Turn",
    GameTag.ON_SELL: "On Sell",
    GameTag.SPELLCRAFT: "Spellcraft",
    GameTag.FODDER: "Fodder",
}

INACTIVE_PREFIXES = ("EXAMPLE_", "BGDUO_", "TOKEN_")


def main():
    _ = __import__("hsrl.cards.minions", fromlist=["_"])
    _ = __import__("hsrl.cards.spells", fromlist=["_"])
    _ = __import__("hsrl.cards.trinkets", fromlist=["_"])

    issues = []
    for card_id, data in sorted(CARDS._cards.items()):
        # Skip examples, duos, tokens
        if any(card_id.startswith(p) for p in INACTIVE_PREFIXES):
            continue
        if data.cardtype not in (CardType.MINION, CardType.SPELL, CardType.TRINKET):
            continue
        # Skip minions not in the shared pool
        if data.cardtype == CardType.MINION and not any(
            card_id.startswith(p) for p in ("BG", "BGS_", "EBG_")
        ):
            continue

        triggers = [name for tag, name in TRIGGER_TAGS.items()
                    if data.tags.get(tag)]
        if not triggers:
            continue  # vanilla — no script needed

        has_bc_data = data.tags.get(GameTag.BATTLECRY)
        has_dr_data = data.tags.get(GameTag.DEATHRATTLE)
        has_av_data = data.tags.get(GameTag.Avenge)
        num_triggers = len(triggers)

        if data.scripts is None:
            # Heuristic: Spells with discover/data effects sometimes have triggers in
            # tags without scripts because the effect detection is text-based rather
            # than JSON-boolean. Filter out SPELL types.
            if data.cardtype == CardType.SPELL and has_bc_data:
                # "Battlecry" on spells means "Battlecry: " appears in text as an example
                continue
            if data.cardtype == CardType.SPELL and has_dr_data and num_triggers == 1:
                continue
            issues.append((card_id, data.name, data.cardtype.name, triggers))
            continue

        # Check trinkets: if they have effects in data tags but no matching script methods
        missing_handlers = []
        for tag, name in TRIGGER_TAGS.items():
            if data.tags.get(tag):
                handler_map = {
                    GameTag.BATTLECRY: ("battlecry",),
                    GameTag.DEATHRATTLE: ("deathrattle",),
                    GameTag.Avenge: ("avenge",),
                    GameTag.RALLY: ("rally",),
                    GameTag.START_OF_COMBAT: ("start_of_combat",),
                    GameTag.END_OF_TURN: ("end_of_turn",),
                    GameTag.START_OF_TURN: ("start_of_turn",),
                    GameTag.ON_SELL: ("on_sell",),
                    GameTag.SPELLCRAFT: ("spellcraft",),
                    GameTag.FODDER: ("battlecry", "deathrattle", "on_summon"),
                }
                methods = handler_map.get(tag, ())
                if not any(hasattr(data.scripts, m) and callable(getattr(data.scripts, m, None))
                           for m in methods):
                    missing_handlers.append(name)
        if missing_handlers:
            issues.append((card_id, data.name, data.cardtype.name,
                           f"script class exists but missing methods: {missing_handlers}"))

    if issues:
        print(f"\n[FAIL] {len(issues)} issues found:\n")
        for item in issues:
            print(f"  {item[0]:30s} {item[1]:40s} {item[2]:12s} {'; '.join(item[3]) if isinstance(item[3], list) else item[3]}")
        print()
        return 1

    print("[PASS] All active pool cards with effects have scripts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
