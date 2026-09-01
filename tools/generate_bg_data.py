#!/usr/bin/env python
"""Regenerate all data/bg_*.json files from hsdata/CardDefs.xml.

Usage:
    python tools/generate_bg_data.py
    python tools/generate_bg_data.py --dry-run    # print stats only

Produces: data/bg_cards.json, bg_pool_minions.json, bg_pool_spells.json,
          bg_heroes.json, bg_hero_powers.json, bg_trinkets.json,
          bg_anomalies.json, bg_quest_rewards.json, bg_tavern_spells.json,
          bg_dark_gifts.json, bg_summary.json, pool_minion_texts.json

v2 changes (S14 / 36.2 refactor):
  - Always export TAG_SCRIPT_DATA_NUM_1/2 as script_data_num_1/2 (card text
    {0}/{1} template parameters were previously dropped except for Avenge —
    root cause of 16+ stale numeric literals in card scripts).
  - Export Activate keyword (INTERACTABLE_OBJECT 4089 + cost 4090).
  - Export Dark Gifts (tag 4855=1, 43 spell entities) to bg_dark_gifts.json.
  - Export BACON_EVOLUTION_CARD_ID (2519) token-generation links
    (e.g. Lurking Lionfish -> Fishbait, Bilgewater Breakout -> Lockbox).
  - Export BACON subset flags (chromadrake subsets etc.).
  - Export SPELL_SCHOOL (1635) for spells.
  - Export LITERALLY_UNPLAYABLE (1020) for hand-sitting tokens (Lockbox).
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HSDATA_XML = ROOT / "hsdata" / "CardDefs.xml"

# ── Correct XML enumID mappings ──
TAG = {
    "CARDNAME": 185,
    "CARDTEXT": 184,
    "HEALTH": 45,
    "ATK": 47,
    "COST": 48,
    "CARDRACE": 200,
    "CARD_SET": 183,
    "CARDTYPE": 202,
    "RARITY": 203,
    "ARMOR": 292,
    "HERO_POWER": 380,          # type=Card, refs hero power by DBF ID
    "TECH_LEVEL": 1440,
    "BACON_TRIPLE_UPGRADE_MINION_ID": 1429,
    "BACON_TRIPLED_BASE_MINION_ID": 1471,
    "BACON_HERO_CAN_BE_DRAFTED": 1491,
    "IS_BACON_POOL_MINION": 1456,
    "IS_BACON_POOL_SPELL": 3081,
    "BACON_SKIN": 2038,
    "BACON_SKIN_PARENT_ID": 2039,
    "BACON_COMPANION_ID": 2130,
    "BACON_SPELLCRAFT_ID": 2359,
    "BACON_TIMEWARPED": 4503,
    "BACON_BUDDY": 2154,
    "BACON_SUBSET_DRAGON": 1591,
    "BACON_SUBSET_MURLOC": 1592,
    "BACON_SUBSET_DEMON": 1593,
    "BACON_SUBSET_BEAST": 1594,
    "BACON_SUBSET_MECH": 1595,
    "BACON_SUBSET_PIRATE": 1596,
    "BACON_SUBSET_ELEMENTALS": 1688,
    "BACON_SUBSET_QUILLBOAR": 1845,
    "BACON_SUBSET_NAGA": 2272,
    "BACON_SUBSET_UNDEAD": 2347,
    "IS_BACON_DUOS_EXCLUSIVE": 3166,
    "BACON_TRINKET": 3407,
    "BACON_IS_MAGIC_ITEM_DISCOVER": 3565,
    "BACON_IS_POTENTIAL_TRINKET": 3705,
    "BACON_COSTS_HEALTH_TO_BUY": 2911,
    "BACON_SELL_VALUE": 1587,
    "BACON_HERO_POWER_ACTIVATED": 1398,
    "BACON_QUESTS_ACTIVE": 2468,
    "BACON_RALLY": 4204,
    "START_OF_COMBAT": 1531,
    "AVENGE": 2129,
    "TAG_SCRIPT_DATA_NUM_1": 2,   # parameter {0} in card text
    "TAG_SCRIPT_DATA_NUM_2": 3,   # parameter {1} in card text
    "TAG_SCRIPT_DATA_NUM_3": 2889,  # parameter {2} (Beetle 族等四参数卡)
    "TAG_SCRIPT_DATA_NUM_4": 2919,  # parameter {3}
    # Keyword tags (XML-authoritative — only set if card itself has the keyword)
    "WINDFURY": 189,
    "TAUNT": 190,
    "DIVINE_SHIELD": 194,
    "DEATHRATTLE": 217,
    "BATTLECRY": 218,
    "POISONOUS": 363,
    "MAGNETIC": 849,
    "REBORN": 1085,
    "VENOMOUS": 2853,
    # S14 additions
    "INTERACTABLE_OBJECT": 4089,           # Activate keyword
    "INTERACTABLE_OBJECT_COST": 4090,      # Activate gold cost
    "IS_DARK_GIFT": 4855,                  # 43 Dark Gift spell entities
    "BACON_EVOLUTION_CARD_ID": 2519,       # token generation link
    "SPELL_SCHOOL": 1635,
    "LITERALLY_UNPLAYABLE": 1020,
}

# ── XML keyword tag → JSON field name ──
XML_KEYWORD_MAP = {
    189: "windfury", 190: "taunt", 194: "divine_shield",
    217: "deathrattle", 218: "battlecry", 363: "poisonous",
    849: "magnetic", 1085: "reborn", 2853: "venomous",
    1531: "start_of_combat", 4204: "rally",
    4089: "activate", 19: "stealth",
}

# ── Race DBF ID → internal name ──
DBF_RACE_NAMES = {
    11: "UNDEAD", 14: "MURLOC", 15: "DEMON", 17: "MECHANICAL",
    18: "ELEMENTAL", 20: "BEAST", 23: "PIRATE", 24: "DRAGON",
    26: "ALL", 43: "QUILBOAR", 92: "NAGA",
}

SUBSET_TAGS = {
    1591: "subset_dragon", 1592: "subset_murloc", 1593: "subset_demon",
    1594: "subset_beast", 1595: "subset_mech", 1596: "subset_pirate",
    1688: "subset_elemental", 1845: "subset_quilboar",
    2272: "subset_naga", 2347: "subset_undead",
}


def parse_carddefs(xml_path):
    """Parse CardDefs.xml and return list of raw card dicts."""
    print(f"Parsing {xml_path} ...")
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    cards = []
    for entity in root.findall("Entity"):
        cid = entity.get("CardID", "")
        if not cid:
            continue
        dbf_id = int(entity.get("ID", 0))
        tags = {}
        for t in entity.findall("Tag"):
            enum_id = int(t.get("enumID", 0))
            t_name = t.get("name", "")
            t_type = t.get("type", "Int")
            value_str = t.get("value", "")

            if t_type == "Int":
                try:
                    value = int(value_str)
                except (ValueError, TypeError):
                    value = 0
            elif t_type == "LocString":
                en_us = t.find("enUS")
                value = en_us.text if en_us is not None and en_us.text else ""
            elif t_type == "Card":
                try:
                    value = int(value_str)
                except (ValueError, TypeError):
                    value = 0
            elif t_type == "String":
                value = value_str
            else:
                value = value_str
            tags[enum_id] = value

        cards.append({"id": cid, "dbf_id": dbf_id, "tags": tags})
    return cards


def tag(card, enum_id, default=None):
    """Get tag value by enumID."""
    return card["tags"].get(enum_id, default)


def has_tag(card, enum_id):
    """Check if tag exists and is truthy."""
    v = tag(card, enum_id)
    return v is not None and v != 0


def get_text(card, enum_id):
    """Get LocString text."""
    return tag(card, enum_id, "")


def build_card_info(card):
    """Extract standardized card info dict."""
    info = {
        "id": card["id"],
        "dbf_id": card["dbf_id"],
        "name": get_text(card, TAG["CARDNAME"]),
        "card_set": tag(card, TAG["CARD_SET"], 0),
        "card_type": tag(card, TAG["CARDTYPE"], 0),
    }

    text = get_text(card, TAG["CARDTEXT"])
    if text:
        info["text"] = text

    # Stats
    for key, tid in [("atk", TAG["ATK"]), ("health", TAG["HEALTH"]),
                     ("card_race", TAG["CARDRACE"]),
                     ("tech_level", TAG["TECH_LEVEL"]), ("rarity", TAG["RARITY"]),
                     ("armor", TAG["ARMOR"])]:
        v = tag(card, tid)
        if v is not None:
            info[key] = v

    # Cost: use explicit COST tag if present; 缺省——随从 3（购买价）、
    # 英雄技能 0（免费技能族无 COST tag，HIDE_COST 家族同; 2026-08-23
    # 修复: 原 CardDef 构造缺省 3 对技能是假值，批 hero_actives2 曾
    # 逐卡 cost_override 规避——现在数据层根治）
    cost = tag(card, TAG["COST"])
    if cost is not None:
        info["cost"] = cost
    elif tag(card, TAG["CARDTYPE"]) == 4:
        info["cost"] = 3  # default minion cost
    elif tag(card, TAG["CARDTYPE"]) == 10:
        info["cost"] = 0  # hero power without COST tag = free

    # ── Template parameters {0}/{1}/{2}/{3}: ALWAYS export when present ──
    # (Previously only exported for Avenge — caused 16+ stale numeric
    #  literals in hand-written card scripts.)
    n1 = tag(card, TAG["TAG_SCRIPT_DATA_NUM_1"])
    n2 = tag(card, TAG["TAG_SCRIPT_DATA_NUM_2"])
    n3 = tag(card, TAG["TAG_SCRIPT_DATA_NUM_3"])
    n4 = tag(card, TAG["TAG_SCRIPT_DATA_NUM_4"])
    if n1 is not None and n1 != 0:
        info["script_data_num_1"] = n1
    if n2 is not None and n2 != 0:
        info["script_data_num_2"] = n2
    if n3 is not None and n3 != 0:
        info["script_data_num_3"] = n3
    if n4 is not None and n4 != 0:
        info["script_data_num_4"] = n4

    # Triple
    triple_id = tag(card, TAG["BACON_TRIPLE_UPGRADE_MINION_ID"])
    if triple_id:
        info["triple_upgrade_id"] = triple_id
    triple_base = tag(card, TAG["BACON_TRIPLED_BASE_MINION_ID"])
    if triple_base:
        info["triple_base_id"] = triple_base

    # Hero-specific
    if tag(card, TAG["BACON_HERO_CAN_BE_DRAFTED"]):
        info["hero_draftable"] = True
    companion = tag(card, TAG["BACON_COMPANION_ID"])
    if companion:
        info["companion_id"] = companion
    # Hero → Hero Power 绑定（XML Tag380 = power 的 dbf id）
    hero_power = tag(card, TAG["HERO_POWER"])
    if hero_power:
        info["hero_power_dbf"] = hero_power

    # Spellcraft
    spellcraft = tag(card, TAG["BACON_SPELLCRAFT_ID"])
    if spellcraft:
        info["spellcraft_id"] = spellcraft

    # Health cost
    if tag(card, TAG["BACON_COSTS_HEALTH_TO_BUY"]):
        info["health_cost"] = True

    # Sell value override
    sell_value = tag(card, TAG["BACON_SELL_VALUE"])
    if sell_value:
        info["sell_value"] = sell_value

    # Avenge target — from XML tags
    if has_tag(card, TAG["AVENGE"]):
        info["avenge"] = True

    # ── S14: Activate keyword ──
    if has_tag(card, TAG["INTERACTABLE_OBJECT"]):
        info["activate"] = True
        activate_cost = tag(card, TAG["INTERACTABLE_OBJECT_COST"])
        if activate_cost:
            info["activate_cost"] = activate_cost

    # ── S14: Dark Gift flag ──
    if has_tag(card, TAG["IS_DARK_GIFT"]):
        info["dark_gift"] = True

    # ── S14: token evolution link (e.g. Lionfish -> Fishbait) ──
    evo = tag(card, TAG["BACON_EVOLUTION_CARD_ID"])
    if evo:
        info["evolution_card_id"] = evo

    # ── S13/S14: subset flags (Chromadrakes etc.) ──
    for enum_id, key in SUBSET_TAGS.items():
        if has_tag(card, enum_id):
            info[key] = True

    # Spell school
    school = tag(card, TAG["SPELL_SCHOOL"])
    if school:
        info["spell_school"] = school

    # Literally unplayable (Lockbox-style hand tokens)
    if has_tag(card, TAG["LITERALLY_UNPLAYABLE"]):
        info["unplayable"] = True

    return info


def detect_xml_keywords(card):
    """Detect keyword flags from XML tags (authoritative source).
    Only returns keywords that the card ITSELF has, not effect-description keywords.
    """
    kw = {}
    for xml_enum, json_key in XML_KEYWORD_MAP.items():
        if card["tags"].get(xml_enum):
            kw[json_key] = True
    return kw


def detect_text_keywords(text):
    """Detect keyword flags from card text (fallback for text-only keywords).
    Does NOT detect keywords that have XML equivalents — those come from XML.
    """
    kw = {}
    if not text:
        return kw

    # Cleave — only detected via text (no known XML tag)
    if "Cleave" in text:
        kw["cleave"] = True

    # Choose One — text-only keyword (no XML tag)
    if "Choose One" in text:
        kw["choose_one"] = True

    # Avenge (N) or Avenge ({0}) — text-only keyword; threshold from num param
    m = re.search(r"Avenge\s*\((\d+)\)", text)
    if m:
        kw["avenge"] = int(m.group(1))
    elif "Avenge" in text:
        kw["avenge"] = True

    return kw


def extract_name(text):
    """Extract clean minion name from text."""
    if not text:
        return ""
    name = text.replace("[x]", "").strip()
    name = re.sub(r"<[^>]+>", "", name)
    name = name.replace("\n", " ").replace("\r", "")
    return name.strip()


def main():
    dry_run = "--dry-run" in sys.argv
    all_cards = parse_carddefs(HSDATA_XML)

    # Filter BG cards (CARD_SET == 1453)
    bg_cards = [c for c in all_cards if tag(c, TAG["CARD_SET"]) == 1453]
    print(f"  Total BG entities: {len(bg_cards)}")

    # Build card info for all BG cards
    cards_info = [build_card_info(c) for c in bg_cards]

    # Categorize
    heroes = []
    hero_powers = []
    pool_minions = []
    pool_spells = []
    all_spells = []
    trinkets = []
    anomalies = []
    quest_rewards = []
    dark_gifts = []
    bg_cards_full = []

    for idx, card in enumerate(bg_cards):
        info = cards_info[idx]
        ct = info.get("card_type", 0)
        cid = info["id"]

        # Skip duos, enchantments
        if "BGDUO" in cid:
            continue
        if ct == 6:  # Enchantment — skip
            continue

        entry = {k: v for k, v in info.items()}

        if ct == 3:  # Hero
            # Only draftable heroes, not skins
            if has_tag(card, TAG["BACON_HERO_CAN_BE_DRAFTED"]):
                heroes.append(entry)
        elif ct == 10:  # Hero Power
            hero_powers.append(entry)
        elif ct == 4:  # Minion
            # 全部随从（含金色版本体）都检测关键词——金色卡无
            # IS_BACON_POOL_MINION 标志，之前只在池分支检测导致金色
            # keywords 导出为空（G3: 金色磁力随从无法吸附的根因）
            text = info.get("text", "")
            kw = detect_xml_keywords(card)
            kw.update(detect_text_keywords(text))
            entry.update(kw)
            bg_cards_full.append(entry)
            if has_tag(card, TAG["IS_BACON_POOL_MINION"]):
                entry["is_pool_minion"] = True
                pool_minions.append(entry)
        elif ct == 42:  # Spell
            text = info.get("text", "")
            kw = detect_xml_keywords(card)
            kw.update(detect_text_keywords(text))
            entry.update(kw)
            bg_cards_full.append(entry)
            all_spells.append(entry)
            if has_tag(card, TAG["IS_BACON_POOL_SPELL"]):
                entry["is_pool_spell"] = True
                pool_spells.append(entry)
            # S14: Dark Gift definitions (tag 4855)
            if has_tag(card, TAG["IS_DARK_GIFT"]):
                entry["dark_gift"] = True
                dark_gifts.append(entry)
        elif ct == 5:  # Plain spell (tokens, Dark Gifts, buttons)
            if has_tag(card, TAG["IS_DARK_GIFT"]):
                bg_cards_full.append(entry)
                entry["dark_gift"] = True
                dark_gifts.append(entry)
            else:
                bg_cards_full.append(entry)
        elif ct == 44:  # Trinket
            entry["trinket"] = True
            trinkets.append(entry)
            bg_cards_full.append(entry)
        elif ct == 43:  # Anomaly
            anomalies.append(entry)
            bg_cards_full.append(entry)
        elif ct == 40:  # Quest Reward
            quest_rewards.append(entry)
            bg_cards_full.append(entry)
        else:
            # Players, etc. — still include in full catalog
            bg_cards_full.append(entry)

    # Stats
    tier_counts = Counter(m.get("tech_level", 0) for m in pool_minions)
    race_counts = Counter(
        DBF_RACE_NAMES.get(m.get("card_race"), "NONE") for m in pool_minions
    )
    spell_tier_counts = Counter(s.get("tech_level", 0) for s in pool_spells)
    activate_count = sum(1 for m in pool_minions if m.get("activate"))

    # Read patch version from README
    version = "unknown"
    readme_path = ROOT / "hsdata" / "README.md"
    if readme_path.exists():
        for line in open(readme_path):
            if line.startswith("Version:"):
                version = line.split(":", 1)[1].strip()
                break

    summary = {
        "patch": version,
        "total_bg_cards": len(bg_cards_full),
        "pool_minions": {
            "count": len(pool_minions),
            "by_tier": {str(k): v for k, v in sorted(tier_counts.items())},
            "by_race": {k: v for k, v in sorted(race_counts.items())},
            "with_activate": activate_count,
        },
        "pool_spells": {
            "count": len(pool_spells),
            "by_tier": {str(k): v for k, v in sorted(spell_tier_counts.items())},
        },
        "dark_gifts": len(dark_gifts),
        "heroes": {"count": len(heroes)},
        "hero_powers": len(hero_powers),
        "tavern_spells": len(all_spells),
        "quest_rewards": len(quest_rewards),
        "anomalies": len(anomalies),
        "trinkets": len(trinkets),
    }

    # pool_minion_texts
    minion_texts = {m["id"]: m.get("text", "") for m in pool_minions if m.get("text")}

    # Print summary
    print(f"\n{'='*60}")
    print(f"Patch: {version}")
    print(f"{'='*60}")
    print(f"Total exported:    {len(bg_cards_full)}")
    print(f"Pool minions:      {len(pool_minions)} (activate: {activate_count})")
    for t_str, c in sorted(summary["pool_minions"]["by_tier"].items()):
        print(f"  Tier {t_str}: {c}")
    print(f"Pool spells:       {len(pool_spells)}")
    for t_str, c in sorted(summary["pool_spells"]["by_tier"].items()):
        print(f"  Tier {t_str}: {c}")
    print(f"Dark Gifts:        {len(dark_gifts)}")
    print(f"Tavern spells:     {len(all_spells)}")
    print(f"Heroes (draftable):{len(heroes)}")
    print(f"Hero powers:       {len(hero_powers)}")
    print(f"Trinkets:          {len(trinkets)}")
    print(f"Anomalies:         {len(anomalies)}")
    print(f"Quest rewards:     {len(quest_rewards)}")

    if dry_run:
        print("\n[Dry run — no files written]")
        return 0

    def write_json(filename, data):
        path = DATA_DIR / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  {filename}: {len(data) if isinstance(data, list) else 'dict'} entries")

    write_json("bg_cards.json", bg_cards_full)
    write_json("bg_pool_minions.json", pool_minions)
    write_json("bg_pool_spells.json", pool_spells)
    write_json("bg_heroes.json", heroes)
    write_json("bg_hero_powers.json", hero_powers)
    write_json("bg_trinkets.json", trinkets)
    write_json("bg_anomalies.json", anomalies)
    write_json("bg_quest_rewards.json", quest_rewards)
    write_json("bg_tavern_spells.json", all_spells)
    write_json("bg_dark_gifts.json", dark_gifts)
    write_json("bg_summary.json", summary)
    write_json("pool_minion_texts.json", minion_texts)

    print(f"\nDone. Generated JSON for patch {version}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
