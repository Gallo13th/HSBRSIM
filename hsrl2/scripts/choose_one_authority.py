"""Choose One 卡权威判定（AUDIT_ENGINE_MECHANICS G-C5 唯一实现）。

问题背景（审计 G-C5）
----------------------
`data/*.json` 的 `choose_one` 布尔字段由生成器
`tools/generate_bg_data.py` 的**文本兜底**产生（`if "Choose One" in
text`），实际是"提及型"标志而非权威机制标签，实测：

- 标记 def **44** 个（含金色/变体）；
- 标题真值（"Choose One -" 标题格式 ∧ 非 Spellcraft 宿主）**36** 个；
- **9 个误报**（提及 "Choose One" 但本身不是抉择卡）:
  `BG31_323/_G` Turbo Hogrider、`BG31_327/_G` Thorned Trailblazer、
  `BG31_329/_G` Boar Gamer、`BG31_892` Fandral's Fortune、
  `BG36_331/_G` Bramble Tunneler；
- **3 个漏报**（真抉择卡但文本兜底未标记）: `BG30_117t` /
  `BG30_117_Gt` Escape Eruption（Spellcraft 法术侧导出路径不跑检测）、
  `BG31_893` Gem Day。

判定口径（唯一权威）
--------------------
1. 文本含 **标题格式** `"Choose One -"` / `"<b>Choose One</b> -"`
   （dash 可落在 `</b>` 之外——`BG31_842` 格式可用正则
   `Choose One(?:</b>)?\\s*-` 命中）；
2. **排除 Spellcraft 宿主**（`spellcraft_id` 非空的随从）——其文案
   属于被授予的法术本体（`BG30_117` Volcanic Visitor 是宿主，
   `BG30_117t` 才是真抉择卡）。

36.2.2/37.0 全库核对：本模块输出与 `hsdata/CardDefs.xml` 的
`CHOOSE_ONE` tag 集完全一致（漂移守卫见
`hsrl2/tests/test_batch_choose_one.py::TestChooseOneDriftGuard` 与
`hsrl2/tests/test_choose_one_authority.py`）。

调用方（2026-10-22 起）
-----------------------
- `batch_rally2.BrambleTunnelerScript` "Get a random Choose One card"
- `batch_unfreeze.FandralFortuneScript` "Discover a Choose One card"
- `batch_choose_one._is_choose_one_card`（Turbo Hogrider 触发条件）
- `scripts/audit_mechanism_coverage.py`（审计口径）

引擎 `CardDef.keywords` 里的 `choose_one` 标志**只作提示**，任何
新脚本不得直接读它做机制判定（G-C5）；统一走本模块。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, FrozenSet, Tuple

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注
    from hsrl2.db import CardDB
    from hsrl2.defs import CardDef

#: Choose One 标题格式（dash 可在 </b> 之外——BG31_842 的
#: "<b>Choose One</b> - Give ..." 布局）。
CHOOSE_ONE_TITLE_RE = re.compile(r"Choose One(?:</b>)?\s*-")


def is_choose_one_def(d: "CardDef | None") -> bool:
    """CardDef 是否为**真抉择卡**（标题正则 ∧ 非 Spellcraft 宿主）。

    非抉择实体（None / 提及型 / Spellcraft 宿主）一律 False。
    """
    if d is None:
        return False
    if getattr(d, "spellcraft_id", None) is not None:
        return False
    return CHOOSE_ONE_TITLE_RE.search(getattr(d, "text", "") or "") is not None


def is_choose_one_entity(game, entity) -> bool:
    """实体（手牌/棋盘/池定义）是否为真抉择卡——按 card_id 查 CardDB。"""
    if entity is None:
        return False
    card_id = getattr(entity, "card_id", None)
    if not card_id:
        return False
    return is_choose_one_def(game.db.get(card_id))


def choose_one_ids(db: "CardDB") -> FrozenSet[str]:
    """全库真抉择卡 id 全集（含金色/变体/非池卡）。"""
    return frozenset(
        d.id for d in db._by_id.values() if is_choose_one_def(d))


def choose_one_data_flag_ids(db: "CardDB") -> FrozenSet[str]:
    """数据 `choose_one` 文本兜底标志命中的 id 全集（**非权威**，仅供审计）。"""
    return frozenset(
        d.id for d in db._by_id.values() if "choose_one" in d.keywords)


def pool_choose_one_minion_ids(db: "CardDB") -> FrozenSet[str]:
    """池内随从中的真抉择卡 id 全集（"random Choose One card" 候选域）。"""
    return frozenset(d.id for d in db.pool_minions() if is_choose_one_def(d))


def pool_choose_one_spell_ids(db: "CardDB") -> FrozenSet[str]:
    """池内法术中的真抉择卡 id 全集（"random Choose One card" 候选域）。"""
    return frozenset(d.id for d in db.pool_spells() if is_choose_one_def(d))


def choose_one_flag_drift(db: "CardDB") -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """数据标志与权威判定的差异（审计用）: (误报集合, 漏报集合)。

    误报 = 数据标记 choose_one 但权威判定 False；
    漏报 = 权威判定 True 但数据未标记。
    """
    authoritative = choose_one_ids(db)
    flagged = choose_one_data_flag_ids(db)
    return flagged - authoritative, authoritative - flagged


def describe_drift(db: "CardDB") -> str:
    """人类可读的漂移摘要（audit 脚本输出用）。"""
    false_positives, misses = choose_one_flag_drift(db)
    return (
        f"choose_one data flag drift: false_positives={sorted(false_positives)} "
        f"misses={sorted(misses)}"
    )
