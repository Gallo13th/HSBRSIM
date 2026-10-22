"""只读机制覆盖审计：卡牌数据 × 脚本注册表 × 引擎动作。

用法：
  python scripts/audit_mechanism_coverage.py
  python scripts/audit_mechanism_coverage.py --out runs/audit/mechanism_coverage.json

不修改任何数据；用于 docs/AUDIT_LIVE_TO_SIM.md 的可复现审计。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hsrl2.scripts.registry import REGISTRY


def _script(card_id: str):
    try:
        return REGISTRY[card_id]()
    except Exception:
        return None


def _ids(path: str):
    data = json.loads((ROOT / path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            cid = item.get("id") or item.get("card_id")
            if cid:
                out.append(str(cid))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    cards = json.loads((ROOT / "data" / "bg_cards.json").read_text(encoding="utf-8"))
    if not isinstance(cards, list):
        raise SystemExit("bg_cards.json 不是 list")
    by_id = {c["id"]: c for c in cards if isinstance(c, dict) and c.get("id")}

    choose = [i for i, c in by_id.items() if c.get("choose_one")]
    activate = [i for i, c in by_id.items() if c.get("activate")]
    dark = [i for i, c in by_id.items() if c.get("dark_gift")]
    battlecry = [i for i, c in by_id.items() if c.get("battlecry")]

    choose_scripts = [i for i in choose if getattr(_script(i), "choose_options", None)]
    choose_missing = [i for i in choose if i not in choose_scripts]
    activate_reg = [i for i in activate if i in REGISTRY]
    activate_hook = [i for i in activate if hasattr(_script(i), "activate")]
    battlecry_reg = [i for i in battlecry if i in REGISTRY]
    battlecry_target = [i for i in battlecry
                        if getattr(_script(i), "needs_target", False)]

    pool = _ids("data/bg_pool_minions.json")
    spells = _ids("data/bg_pool_spells.json")
    result = {
        "cards_total": len(cards),
        "registry_total": len(REGISTRY),
        "choose_one": {
            "cards": len(choose),
            "scripts": len(choose_scripts),
            "missing": choose_missing,
        },
        "activate": {
            "cards": len(activate),
            "registry": len(activate_reg),
            "hook": len(activate_hook),
            "missing_registry": [i for i in activate if i not in REGISTRY],
        },
        "dark_gift": {"cards": len(dark)},
        "battlecry": {
            "cards": len(battlecry),
            "registry": len(battlecry_reg),
            "needs_target": len(battlecry_target),
        },
        "pool_minions": {
            "cards": len(pool),
            "no_script": [i for i in pool if i not in REGISTRY],
        },
        "pool_spells": {
            "cards": len(spells),
            "no_script": [i for i in spells if i not in REGISTRY],
        },
        "targeted_battlecry": [i for i in battlecry_target],
    }
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
