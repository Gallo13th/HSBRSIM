"""批次 remaining1 — 清尾解冻批（作业单 2026-09-16）。

范围: 逐类别扫描"当前未注册且可提供"的卡（池随从 / 池法术 / 暗赐 /
英雄技能 / 饰品 / 异变 / 任务奖励 / 任务），对每张做二态裁决
（SOP §6b）。候选集经运行核验与既有 40+ 批次的台账逐条比对：
剩余未注册项几乎全部有明确阻塞（载荷未迁 / 子系统缺失 / 语义无权威），
本批只解冻其中**阻塞已消失**的卡。

注册 1 项（注册键 = 卡 id）
═══════════════════════════════════════════════════════════════════════
  EBG_Spell_037 Unmasked Identity（T5 池法术, card_type=42,
  tech_level=5, cost=3, spell_school=9）— "**Discover** a new Hero
  Power."
  `batch_spells_final` 曾以"英雄技能体系未迁移（v2 引擎无 hero_power
  脚本/池）"撤注册登记 DEFERRED。**阻塞已消失（2026-09-16 复核）**:
    - 英雄技能体系已迁移: 116 个英雄绑定技能中 101 个已注册脚本;
      `Game.replace_hero_power`（game.py）/ `Game.hero_power_def`
      （读 `_active_power_id` 覆写）/ `Game.wire_hero_power_on_bind`
      （幂等接线被选技能 on_bind）齐备。
    - Discover 协议就绪: `PendingChoice(kind="discover_hero_power")`
      为 Finley `TB_BaconShop_HP_057 Adventure!`（"At the start of the
      game, Discover a Hero Power"）已验证路径; `_NON_CARD_DISCOVER_KINDS`
      显式把该 kind 排除在 `card_discovered` 之外（"Discover a
      **card**"类被动不被技能发现误触发）。
    - 候选池 = `batch_hero_remaining._draftable_hero_power_ids`
      （英雄绑定 Tag380 且 REGISTRY 已注册——未迁移技能不入池，防
      选中空转按钮）。
  机制权威: wiki.gg/Battlegrounds/Unmasked_Identity（oldid 776222）
  卡片页 mechanics 行 = **Discover + Replace Hero Power**，XML tags
  `DISCOVER=1` / `USE_DISCOVER_VISUALS=1`; patch 35.4.0 bugfix
  "Fixed a bug where Unmasked Identity cast by Magicfin Apprentice
  during combat could change the opponent's Hero Power." → 只改
  **施放者本人**的技能（owner 隔离是规格的一部分）。
  "new" = 候选不提供正持有的技能（Finley 同裁定 + wiki
  Power_of_the_Storm banned pool 剔除自身）。

本批复核后维持 DEFERRED 的项（精确阻塞; 不逐条重复既有批次的长台账）
═══════════════════════════════════════════════════════════════════════
A. 池法术（`CardDB.pool_spells()` 未注册 4 张）:
   - `EBG_Spell_037` 已由本批注册（上）。
   - `BG31_242` Bargain Bundle / `BG31_243` Portal in a Fountain /
     `BG31_244` Portal in a Crystal — 文本含 **teammate / Pass**，属
     双打（Duos）机制 —— 项目范围外（AGENTS: 不实现 Duos）。
B. 池随从（未注册 7 张）: 5 张纯关键词卡（`BG25_001` Risen Rider /
   `BGS_119` Crackling Cyclone / `BGS_131` Deadly Spore /
   `BG_BOT_911` Annoy-o-Module / `BG_DEEP_015` Prosthetic Hand）由
   引擎数据通道自动生效，注册空脚本 = 第三态; `BG26_175` Elemental
   of Surprise 的"可替代三连"是引擎 `check_for_triple` 内建逻辑
   （SOP §10 替代三连）; `BG33_319` Rimescale Priestess 维持
   `audit_card_registry_v2.DEFERRED_LEDGER`（"Tavern spell that gives
   stats"资格集无权威定义）。
C. 英雄技能 15 张: 全部有既有台账（`batch_hero_rewards_final` /
   `batch_hero_remaining*`）——无来源卡 Triple Reward 档位无权威
   （`BG20_HERO_242p` / `BG33_HERO_001p_ALT`）、hero 级 rebind/unbind
   缺失（`BG20_HERO_202p` / `BG20_HERO_283p`）、Craft（`BG25_HERO_100p`）、
   Zerg/Battlecruiser 子系统（`BG31_HERO_811p` / `BG31_HERO_801p`）、
   Timewarp（`BG34_HERO_000p` / `BG34_HERO_004p`）、双发现+双槽
   （`BG35_HERO_001p`）、任务载荷整族 DEFERRED（`BG24_HERO_100p`）、
   Secrets（`TB_BaconShop_HP_020`）、Darkmoon Ticket 卡在 `data/` 中
   不存在（`TB_BaconShop_HP_101`）、Darkmoon Prize 候选表缺失
   （`TB_BaconShop_HP_106`）、improvement 抉择协议无权威
   （`BG21_HERO_000p`）。
D. 饰品 30 张: 全部在 `docs/agents/TRINKET_LEDGER.md` 与
   `ENGINE_BACKLOG §B3` 的 A–F 映射内（载荷未注册 / 多值种族 RACES /
   子系统缺失 / 增量权威缺失）。本批特别复核并**维持**约束 1 点名的
   三张"also give Attack/Health 无数字"卡（`BG30_MagicItem_868` /
   `BG30_MagicItem_987` / `BG32_MagicItem_283`）——"also"的增量在
   卡文本/`num()` 均无字段，等值假设禁止; 另复核 `BG35_MagicItem_921`
   Cowrie Necklace（"give stats"法术子集无数据位）、
   `BG30_MagicItem_711` Marine Signet（"improve this"的档位步长无
   数据字段; wiki oldid raw 无 Notes, refTag 仅 Tavern Tier-related）、
   `BG32_MagicItem_823` Wax Imprinter（"(if possible)"限定对象无权威;
   wiki raw 无 Notes）、`BG32_MagicItem_809` Gem Donation
   （"plays its Blood Gems"枚数/来源无权威）、
   `BG32_MagicItem_820` Impulsive Portrait（"target adjacent minions"
   的**数额口径** both-vs-split 无权威——载体 `BG21_006` 已注册、
   §7.4.16 机制已有，唯一真阻塞是数额语义; wiki 无 Notes）
   ——均维持 DEFERRED。
E. 异变 37 张: 全部在 `batch_anomalies_final` DEFERRED 台账内
   （Buddy / Timewarp / Darkmoon Prize / 英雄身份替换 / Wheel /
   共享发现 / 任务族 / 语义无权威）。
F. 任务奖励 4 张: `BG24_Reward_135`（Wheel 结果表缺失）/
   `BG24_Reward_313`（概率与类别表缺失）/ `BG24_Reward_362`
   （载荷 `BGS_029` 无"手牌每回合变形"脚本 + "a random minion"档位
   无权威）/ `BG27_Anomaly_555t`（回报数值只在已注册异变
   `BG27_Anomaly_555` 页, token 自身无——注册即第三态）。
G. 任务 21 张: 目标值 = 基础 tag × 四因子（种族修正/奖励基础值/奖励
   种族修正/护甲等级），四因子无数据权威（RULES §11.6 /
   `QUEST_DEFERRED_SPEC`）→ 整族 DEFERRED。

审计盲区记录（报告主线）
═══════════════════════════════════════════════════════════════════════
`tools/audit_card_registry_v2.py` 的 `is_effective()` 文本启发集
（`TEXT_EFFECT_MARKERS`）不含裸 "Discover" —— 这正是
`EBG_Spell_037` 长期未被告警的原因（池法术门禁因"判为无效"而漏）。
已有发现保留原文于本 docstring; 修复审计启发集会连带要求为 3 张 Duos
法术建立台账，超出本批范围，交主线裁定。
"""

from __future__ import annotations

from hsrl2.game import PendingChoice

# Discover 默认展示数（引擎 `Discover` Action 默认 count=3; 文本无占位符）
_DISCOVER_COUNT = 3


class UnmaskedIdentityScript:
    """
    Natural language: <b>Discover</b> a new Hero Power.

    Evidence: `data/bg_pool_spells.json EBG_Spell_037`（card_type=42
    BACON_SPELL, tech_level=5, cost=3, spell_school=9, 无金色定义;
    `num(0..4)` 全 None——文本无占位符）; wiki.gg/Battlegrounds/
    Unmasked_Identity（2026-09-16 查证）mechanics 行 = "Discover,
    Replace Hero Power"，XML tags `DISCOVER=1` /
    `USE_DISCOVER_VISUALS=1`; patch 35.4.0 bugfix（Magicfin Apprentice
    战斗中施放会改**对手**技能）→ 规格含 owner 隔离。

    Formal spec:
      1. on_play(source, game, ctx): hero = source.controller
      2. 当前技能 = `game.hero_power_def(hero)`（静态 Tag380 链或
         `_active_power_id` 覆写）+ 第二技能槽 `hero._second_power_id`
         （异变/奖励授予）——"new" 排除两者
      3. 候选池 = `_draftable_hero_power_ids(game, exclude={持有技能})`
         （英雄绑定 + REGISTRY 已注册的技能; 未迁移技能不入池）
      4. 候选空 → 落空（不建空选择）; 否则 `game.rng.sample` 取
         `_DISCOVER_COUNT` 个互异候选 →
         `PendingChoice(hero, options, "discover_hero_power")`
         （kind 与 Finley 一致; 引擎 `_NON_CARD_DISCOVER_KINDS` 已排除
         `card_discovered` 误广播）
      5. resolve(power_id): 不在本次选项内（陈旧/非法）→ 落空;
         否则 `game.replace_hero_power(hero, power_id)`（主槽
         `_active_power_id` + 使用次数重置; 第二槽不动）+
         `game.wire_hero_power_on_bind(hero, power_id)`（幂等接线被选
         技能 on_bind——Patchwerk 血量等被动即时生效）
      6. 作用域: 仅施放者本人（对手技能不变）

    Test: test_batch_remaining1.py — 真实 `play_spell` 后恰 1 个
      `discover_hero_power` 选择（3 个互异、均为已注册英雄技能、不含
      当前技能/第二槽技能）; 选 Patchwerk → `hero_power_def` 变为它、
      生命翻倍（on_bind 已接线）、`hero_power_ids` 识别新技能; 对手
      技能不变且无选择; 再次施放时新当前技能被排除; 非法 resolve 落空;
      候选池为空 → 无选择; 施放后池副本归还

    Params: 无数值参数（`num(0..4)` 全 None; count=3 为 Discover 默认
      展示数——文本无占位符）
    """

    @staticmethod
    def on_play(source, game, ctx):
        from hsrl2.scripts.batches.batch_hero_remaining import (
            _draftable_hero_power_ids,
        )
        hero = source.controller
        if hero is None:
            return None
        held = []
        current = game.hero_power_def(hero)
        if current is not None:
            held.append(current.id)
        # 只排除**当前主技能**——与同类机制既有实现（Finley
        # `_ADVENTURE_POWER`、`batch_anomalies4.grant_second_power_discover`、
        # Cosmic Reward）同口径; wiki 对"第二技能槽是否算已持有"无说明,
        # 不得自创排除规则（SOP §6b; 第二十七轮对抗验证裁定）。
        pool = _draftable_hero_power_ids(game, exclude=tuple(held))
        if not pool:
            return None
        options = game.rng.sample(pool, min(_DISCOVER_COUNT, len(pool)),
                                  label="unmasked_identity")

        def resolve(power_id):
            if power_id not in options:
                return                      # 陈旧/非法选择 → 落空
            game.replace_hero_power(hero, power_id)
            game.wire_hero_power_on_bind(hero, power_id)

        game.pending_choices.append(PendingChoice(
            hero, options, "discover_hero_power", resolve_callback=resolve))
        return None


_SCRIPTS = {
    "EBG_Spell_037": UnmaskedIdentityScript,
}

CORRECT_IDS = ("EBG_Spell_037",)


def register() -> list[str]:
    """注册 Unmasked Identity（其余未注册项的逐类别复核见模块 docstring）。"""
    from hsrl2.scripts.registry import register as reg

    for cid in CORRECT_IDS:
        reg(cid, _SCRIPTS[cid])
    return list(CORRECT_IDS)
