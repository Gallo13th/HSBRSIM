"""Extract zhCN card names and texts from CardDefs.xml into a compact JSON map.

Output: data/card_zhcn.json  —  {card_id: {"n": "中文名", "t": "中文描述"}}
Short keys to keep the file small (~5K entries at ~150 bytes avg = ~750KB).
"""
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

def main():
    xml_path = Path(__file__).resolve().parent.parent / "hsdata" / "CardDefs.xml"
    out_path = Path(__file__).resolve().parent.parent / "data" / "card_zhcn.json"

    if not xml_path.exists():
        print(f"ERROR: {xml_path} not found. Run: git submodule update --init hsdata")
        sys.exit(1)

    result = {}
    count = 0
    current_card_id = None
    in_cardname = False
    in_cardtext = False
    name_zh = ""
    text_zh = ""

    for event, elem in ET.iterparse(str(xml_path), events=("start", "end")):
        if event == "start":
            tag_name = elem.tag if "}" not in elem.tag else elem.tag.split("}", 1)[1]

            if tag_name == "Entity":
                current_card_id = elem.get("CardID", "")

            elif tag_name == "Tag":
                enum_id = elem.get("enumID", "")
                if enum_id == "185":  # CARDNAME
                    in_cardname = True
                    name_zh = ""
                elif enum_id == "184":  # CARDTEXT
                    in_cardtext = True
                    text_zh = ""

            elif tag_name == "zhCN":
                if in_cardname:
                    name_zh = elem.text or ""
                elif in_cardtext:
                    text_zh = elem.text or ""

        elif event == "end":
            tag_name = elem.tag if "}" not in elem.tag else elem.tag.split("}", 1)[1]
            if tag_name == "Tag":
                if in_cardname and current_card_id:
                    if name_zh:
                        entry = result.setdefault(current_card_id, {})
                        entry["n"] = name_zh
                        count += 1
                elif in_cardtext and current_card_id:
                    if text_zh:
                        entry = result.setdefault(current_card_id, {})
                        entry["t"] = text_zh
                in_cardname = False
                in_cardtext = False
            elif tag_name == "Entity":
                current_card_id = None

            elem.clear()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"Extracted {count} zhCN entries → {out_path} ({out_path.stat().st_size:,} bytes)")

if __name__ == "__main__":
    main()
