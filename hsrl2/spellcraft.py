"""Spellcraft 法术塑造系统 (RULES §6.13)。

生成入口两条:
  - 回合开始: generate_for_hero（game._begin_recruit_for 调用）——
    为棋盘上每个 SPELLCRAFT 随从生成一张临时法术
  - 打出/召唤随从: grant_spellcraft_spell（随从脚本 on_summon 调用，
    RULES §6.13 "打出法术塑造随从时立即获得第一张法术"）

金色模型: 金色随从是独立卡定义，其 spellcraft_id 直接指向金色法术
定义（如 BG23_000_G → BG23_000_Gt）。若数据回归出现"金色随从指向
普通法术"，尝试 db.golden_version(spell_def) 换金色版; 仍缺则记
MISSING_SPELLCRAFT_GOLDEN 审计日志并退回普通版（不静默）。

生命周期协议（脚本层契约，game.py 已实现）:
  - 法术实体带 SPELLCRAFT tag + spellcraft_source_uuid=来源随从.uuid
  - 满手时 pending_hand_add 排队等待不销毁
  - end_recruit_phase 丢弃未使用的 Spellcraft 法术; Sunken Persistence
    Dark Gift 的随从 uuid 在 game._permanent_spellcraft_uuids 中则豁免
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from hsrl2.tags import GameTag

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero
    from hsrl2.spell import Spell


def _make_spellcraft_spell(minion, game: "Game") -> Optional["Spell"]:
    """为单个 Spellcraft 随从创建一张临时法术并加入其控制者手牌。

    返回创建的法术实体; 满手时进入 pending_hand_queue（返回实体本身）。
    无 Spellcraft 定义 / 数据缺失时返回 None（缺定义已记审计日志）。
    """
    d = game.db.get(minion.card_id)
    if d is None or d.spellcraft_id is None:
        return None
    spell_def = game.db.by_dbf(d.spellcraft_id)
    if spell_def is None:
        game.dark_gift_audit_log.append(
            f"MISSING_SPELLCRAFT_DEF: {minion.card_id}")
        return None
    # 金色随从 → 金色法术。判定依据（2026-08-23 压测 audit 修复）:
    # 比较金色随从与基础随从的 spellcraft_id——
    #   不同 → 数据链已直指专属金色法术（BG27_514_G→103076 即
    #          BG27_514t_G），直接使用（法术侧无三连链，不能用
    #          spell_def.is_golden_def 判定——那是误判之源）;
    #   相同 → 金色随从共用普通法术定义 → 尝试 golden_version 换金，
    #          仍缺则退回普通版（审计日志，不静默）。
    if d.is_golden_def:
        base_def = None
        if d.triple_base_id:
            base_def = game.db.by_dbf(d.triple_base_id)
        if base_def is not None \
                and base_def.spellcraft_id == d.spellcraft_id:
            golden_spell = game.db.golden_version(spell_def)
            if golden_spell is None:
                game.dark_gift_audit_log.append(
                    f"MISSING_SPELLCRAFT_GOLDEN: {minion.card_id} "
                    f"-> fallback {spell_def.id}")
            else:
                spell_def = golden_spell
    spell = game.create_spell(spell_def.id, controller=minion.controller)
    # 引擎缺口: create_spell 未像 create_minion 那样绑定 REGISTRY 脚本
    # （game.py:1238 只对随从做）→ 此处补绑，on_play 效果才能触发
    from hsrl2.scripts import REGISTRY
    spell.scripts = REGISTRY.get(spell_def.id)
    spell.set(GameTag.SPELLCRAFT, True)
    spell.spellcraft_source_uuid = minion.uuid   # Sunken Persistence 协议
    game.pending_hand_add(minion.controller, spell)
    return spell


def generate_for_hero(hero: "Hero", game: "Game") -> None:
    """回合开始: 为 hero 棋盘上每个 Spellcraft 随从生成一张临时法术。

    RULES §6.13: 每个招募阶段开始时给予一张临时法术。
    引擎缺口注: create_minion 未从 CardDef.spellcraft_id 映射 SPELLCRAFT
    tag（_KEYWORD_TAG_MAP 无 spellcraft 项），tag 由随从脚本 on_summon
    自举——未经 on_summon 路径入场的随从不会被本函数看到。
    """
    for m in list(hero.board):
        if m.has(GameTag.SPELLCRAFT):
            _make_spellcraft_spell(m, game)


def grant_spellcraft_spell(minion, game: "Game") -> None:
    """打出/召唤 Spellcraft 随从时立即获得第一张法术（on_summon 调用）。

    金色随从产生金色法术（金色随从是独立卡定义，其 spellcraft_id
    指向金色法术定义——见 _make_spellcraft_spell）。
    """
    _make_spellcraft_spell(minion, game)
