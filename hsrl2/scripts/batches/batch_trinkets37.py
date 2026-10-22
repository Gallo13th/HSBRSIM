"""饰品第 37 批 —— Weary Portrait 解冻（Spellcraft 永久化第二消费者，2026-09-14）

本批 1 张（全部 CORRECT，商店池 Lesser 档 spell_school=11, cost 5）:

  - `BG32_MagicItem_933` Weary Portrait — "Get a Weary Mage. Your Weary
    Mages' **Spellcrafts** are permanent."

原 DEFERRED 阻塞（`batch_trinkets16` / `25` / `31` 台账「双重阻塞」）**两条
均已消除**:
  (a) 载荷未注册: 关联卡 `BG31_830` Weary Mage（数据链
      `evolution_card_id=119921` → dbf 119921）与其 Spellcraft 法术
      `BG31_830t` Reinvigoration 均已由 `batch_payload_minions` 注册
      （金色 `BG31_830_G` / `BG31_830_Gt` 亦已注册）;
  (b) 永久化通道缺失: `game.add_permanent_spellcraft_rule(hero, source,
      predicate)` 已由 `batch_trinkets23`（Thaumaturgist Portrait
      `BG32_MagicItem_920`）落地——**同族文本、同一条规则**，引擎侧
      `_permanent_spellcraft_matches` 在**生成** Spellcraft 法术时对来源
      随从求值，命中则标记 `permanent_spellcraft`（RULES §6.13）。

      注意本卡的临时项与 920 不同: Thaumaturgist 的法术是
      "+{1}/+{1} **until next turn**"（临时 buff → 引擎通用通道直接
      翻转），而 Reinvigoration 是 "+2/+2; 若是纳迦额外给 **Reborn**
      until next turn"——**临时项是关键词**。故本批同时给
      `batch_payload_minions.ReinvigorationScript.on_play` 加永久化分支:
      `permanent_spellcraft` 命中时**不注册** Reborn 过期监听（关键词
      跨回合保留）。权威: 34.0 官方 bugfix "retains Reborn from Weary
      Mage's Reinvigoration Spellcraft"（`batch_econ_misc.LavaLurkerScript`
      台账同引; "permanent" = keep enchantment）。

读法（与已注册同族卡 920 完全同构，零新增裁定）:
  - 交付 `1` 张 Weary Mage（"Get a Weary Mage" = 入手 1 张; 文本无数量词，
    不走池占（`BG31_830` 非池卡，`is_pool_minion=False`））。
  - 资格集 = `card_id ∈ {关联卡, 其金色本体}`（`db.golden_version` 解析
    得 `BG31_830_G`，零硬编码卡 id）。
  - 只作用于本人（predicate 挂在英雄的 `permanent_spellcraft_rules` 上，
    且 `source` 离场即失效——引擎侧生命周期校验）。

AMBIGUOUS 留档（记录，不据此改动）:
  1. 金色 Weary Mage 的 Spellcraft 是否也应永久（文本"Your Weary Mages"
     不区分金/非金）——按同族 920 先例：金色本体一并匹配（本批照做）。
  2. Reinvigoration 第二句 "also give it **Reborn** until next turn" 的
     临时关键词**已按权威裁定为保留**（见上"（b）"引 34.0.1 官方
     hotfix）; 实现方式不是引擎通用通道（那条只翻转 temporary buff，
     关键词过期由载荷脚本自己注册的 `TURN_START once` 监听清除），而是
     载荷脚本读 `permanent_spellcraft` 后**跳过**注册该监听。
     另一处已知**引擎级**缺口（本轮对抗审查 BUG-2，非本卡引入）:
     `cast_spell_effect`（RULES §7.4.7b）新建的法术既无生成期标记也无
     来源反查 → 该入口下"永久 Spellcraft"对 920/933 **两族**都不生效;
     见 `ENGINE_BACKLOG` #26。

Params: 无模板参数（`num(0..4)` 全 None；"Get a Weary Mage" = 1 张，文本
字面量）。
"""

from __future__ import annotations


class WearyPortraitScript:
    """
    Natural language: [x]Get a Weary Mage.
    Your Weary Mages'
    <b>Spellcrafts</b> are permanent.

    Evidence: `data/bg_trinkets.json BG32_MagicItem_933`（Lesser,
    `spell_school=11`, cost 5, `evolution_card_id=119921` → `BG31_830`
    Weary Mage 3 费 T4（`data/bg_cards.json` cost=3））。同族先例 `BG32_MagicItem_920` Thaumaturgist
    Portrait（已注册，`batch_trinkets23`）文本逐字同构
    （"Your Thaumaturgists' Spellcrafts are permanent"），引擎侧规则
    通道即为其落地。

    Formal spec:
      1. on_bind: `game.grant_trinket_related_card(hero, source.card_id)`
         —— 数据链 `evolution_card_id` → `db.by_dbf` 解析 `BG31_830`
         并入手（非池卡 → 不占池; 满手经 `pending_hand_add` 排队）。
      2. 规则注册: `game.add_permanent_spellcraft_rule(hero, source,
         predicate)` —— predicate 匹配 `card_id ∈ {BG31_830, BG31_830_G}`
         （零硬编码卡 id，金色经 `db.golden_version` 解析）。引擎在
         **生成** Spellcraft 法术时对来源随从求值 → 命中则该次施放把
         目标身上的 temporary buff 翻转为永久（RULES §6.13），下一代
         `_expire_at_next_turn` 不回收。
      3. `source` 离场（饰品被替换）后 `_permanent_spellcraft_matches`
         的生命周期校验使规则失效（引擎侧保证）。
      4. 只作用于本人（对手的 Weary Mage 不被标记）。

    Test: test_batch_trinkets37.py — 绑定后入手 1 张 BG31_830（非池卡不占
      池）/ 本人 Weary Mage 的 Reinvigoration `permanent_spellcraft=True`
      且施放后 +2/+2 为永久、跨回合不回收（无饰品对照回收）/ 非 Weary
      Mage 来源不标记 / 金色 Weary Mage 匹配 / 饰品离场规则失效 /
      对手来源不标记 / 两份副本各交付 1 张且规则互不干扰。

    Params: 无模板参数（文本字面量 1 张）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        game.grant_trinket_related_card(hero, source.card_id)
        related = game.trinket_related_card(source.card_id)
        if related is None:
            return None
        ids = {related.id}
        golden = game.db.golden_version(related)
        if golden is not None:
            ids.add(golden.id)

        def matches(minion, _ids=ids):
            return getattr(minion, "card_id", None) in _ids

        game.add_permanent_spellcraft_rule(hero, source, matches)
        return None


def register() -> list[str]:
    """注册饰品第 37 批 1 张（全部 CORRECT，0 DEFERRED）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG32_MagicItem_933", WearyPortraitScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
