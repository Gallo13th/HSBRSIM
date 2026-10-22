"""CardDB — 从 data/*.json 加载全部卡牌定义（含金色本体）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from hsrl2.defs import CardDef
from hsrl2.tags import CardType

DBF_ID_FIELD = "dbf_id"


class CardDB:
    def __init__(self) -> None:
        self._by_id: Dict[str, CardDef] = {}
        self._by_dbf: Dict[int, CardDef] = {}

    # ── 加载 ──

    @classmethod
    def load(cls, data_dir: Path | str) -> "CardDB":
        """从 data/ 目录加载全部 bg_*.json。"""
        db = cls()
        data_dir = Path(data_dir)
        for fname in (
            "bg_cards.json",          # 全量目录（含 token / 金色版 / 法术 / 按钮）
            "bg_pool_minions.json",
            "bg_pool_spells.json",
            "bg_heroes.json",
            "bg_hero_powers.json",
            "bg_trinkets.json",
            "bg_anomalies.json",
            "bg_quest_rewards.json",
            "bg_dark_gifts.json",
        ):
            path = data_dir / fname
            if not path.exists():
                continue
            entries = json.loads(path.read_text(encoding="utf-8"))
            for entry in entries:
                db.register(CardDef.from_json(entry))
        # hero_power_dbf（XML Tag380）→ power card_id 二次映射
        for d in list(db._by_id.values()):
            raw_dbf = d.raw.get("hero_power_dbf")
            if raw_dbf:
                power = db._by_dbf.get(raw_dbf)
                if power is not None:
                    object.__setattr__(d, "hero_power_id", power.id)
        return db

    def register(self, definition: CardDef) -> None:
        existing = self._by_id.get(definition.id)
        if existing is not None:
            if existing.card_type != definition.card_type:
                # 类型冲突 = 注册覆盖 bug（旧引擎 BG28_601 教训）
                raise ValueError(
                    f"Duplicate card id {definition.id} with conflicting type: "
                    f"{existing.card_type} vs {definition.card_type}"
                )
            # 同类型重复（全量目录 + 池子集）→ 幂等合并池标志/关键词
            if definition.is_pool_minion and not existing.is_pool_minion:
                object.__setattr__(existing, "is_pool_minion", True)
            if definition.is_pool_spell and not existing.is_pool_spell:
                object.__setattr__(existing, "is_pool_spell", True)
            if definition.keywords - existing.keywords:
                object.__setattr__(
                    existing, "keywords",
                    existing.keywords | definition.keywords)
            if definition.avenge_target and not existing.avenge_target:
                object.__setattr__(
                    existing, "avenge_target", definition.avenge_target)
            return
        self._by_id[definition.id] = definition
        if definition.dbf_id:
            self._by_dbf[definition.dbf_id] = definition

    # ── 查询 ──

    def get(self, card_id: str) -> Optional[CardDef]:
        return self._by_id.get(card_id)

    def by_dbf(self, dbf_id: int) -> Optional[CardDef]:
        return self._by_dbf.get(dbf_id)

    def golden_version(self, definition: CardDef) -> Optional[CardDef]:
        """金色本体定义（triple_upgrade_id → dbf 查找）。"""
        if definition.triple_upgrade_id is None:
            return None
        golden = self.by_dbf(definition.triple_upgrade_id)
        if golden is None:
            return None
        return golden

    def pool_minions(self) -> list[CardDef]:
        return [d for d in self._by_id.values()
                if d.is_pool_minion and d.card_type == CardType.MINION
                and not d.is_golden_def]

    def pool_spells(self) -> list[CardDef]:
        return [d for d in self._by_id.values()
                if d.is_pool_spell and not d.is_golden_def]

    def dark_gifts(self) -> list[CardDef]:
        return [d for d in self._by_id.values() if d.dark_gift]

    def trinket_offer_pool(self) -> list[CardDef]:
        """可被饰品商店**提供**的饰品（排除内部 token 与升级变体）。

        依据（2026-09-01 数据核实）:
          - 排除 `BG30_Trinket_*`（引擎内部 token 族）
          - 排除"升级变体": id 尾部形如 `t`/`t2` 且存在**同名本体**
            （如 Kodo Leather Pouch `BG30_MagicItem_414` 本体 /
            `_414t` 升级形态——升级形态由升级类效果获得，不是商店提供项；
            51 个 t 变体中 46 个有同名本体）
        档位过滤（Lesser/Greater）由 `spell_school` 表达（11/12），
        在 `Game._offer_trinkets` 按 kind 施加。
        """
        import re as _re
        all_t = [d for d in self._by_id.values()
                 if d.card_type == CardType.BACON_TRINKET
                 and not d.is_golden_def]
        by_name: dict = {}
        for d in all_t:
            by_name.setdefault(d.name, []).append(d)
        out: list[CardDef] = []
        for d in all_t:
            if d.id.startswith("BG30_Trinket_"):
                continue
            suffix = d.id.rsplit("_", 1)[-1]
            if _re.search(r"t\d*$", suffix):
                if any(x is not d for x in by_name.get(d.name, [])):
                    continue      # 有同名本体 → 升级变体，商店不提供
            out.append(d)
        return out

    def __len__(self) -> int:
        return len(self._by_id)
