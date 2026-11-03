"""游戏规则覆盖（A/B 实验）：通过引擎配置 JSON 传参，默认无覆盖（逐位等价）。

目前只支持 ``tier_upgrade_discount``（docs/ECONOMY_CEILING.md §5 的「降升级费」实验）；
由环境变量 ``HSBG_TIER_UPGRADE_DISCOUNT`` 控制（未设置/0 = 原行为）。
"""
from __future__ import annotations

import json
import os


def tier_upgrade_discount() -> int:
    raw = os.environ.get("HSBG_TIER_UPGRADE_DISCOUNT", "").strip()
    try:
        return max(0, int(raw)) if raw else 0
    except ValueError:
        return 0


def tier_upgrade_discount_scope() -> str:
    return (os.environ.get("HSBG_TIER_UPGRADE_DISCOUNT_SCOPE", "") or "all").strip()


def gold_bonus_turns() -> list[list[int]]:
    """"5:1,7:1,9:3" -> [[5,1],[7,1],[9,3]]（空串 = 无加成）。"""
    raw = (os.environ.get("HSBG_GOLD_BONUS_TURNS", "") or "").strip()
    out: list[list[int]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        t, v = part.split(":", 1)
        try:
            out.append([int(t), int(v)])
        except ValueError:
            continue
    return out


def game_config_json() -> str | None:
    cfg: dict = {}
    d = tier_upgrade_discount()
    if d:
        cfg["tier_upgrade_discount"] = d
        scope = tier_upgrade_discount_scope()
        if scope and scope != "all":
            cfg["tier_upgrade_discount_scope"] = scope
    gb = gold_bonus_turns()
    if gb:
        cfg["gold_bonus_by_turn"] = gb
    return json.dumps(cfg) if cfg else None
