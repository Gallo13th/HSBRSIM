"""饰品第 38 批 —— Tide Raiser Portrait 解冻（战斗内施法事件消费者，2026-09-17）

本批 1 张（全部 CORRECT，商店池 Lesser 档 `spell_school=11`, cost 4）:

  - `BG35_MagicItem_922` Tide Raiser Portrait — "Get a Tide Raiser. After
    you cast a spell in combat, get a copy of the spell. ({1} times per
    combat.)"

原 DEFERRED 阻塞（`batch_trinkets19` / `26` / `31` 台账「双重阻塞」）**两条
均已消除**——两条都是"台账写成后引擎/载荷才落地"的过期陈述:

  (a) 载荷未注册: 关联卡 `BG34_920` Tide Raiser（数据链
      `evolution_card_id=126629` → dbf 126629）及其金色 `BG34_920_G`
      均已由 `batch_payload_minions` 注册（`TideRaiserScript` /
      `TideRaiserGoldenScript`）。
  (b) "真实对局中无人在战斗内施法": `TideRaiserScript.deathrattle` 正是
      战斗内调用 `game.cast_spell_effect(hero, "BG32_815", target=...)`
      （`batch_payload_minions.py` L737/L762），而 `cast_spell_effect`
      无条件广播 `spell_resolving` / `spell_resolved`
      （`game.py` L1488/L1493，RULES §7.4.7b）；`spell_resolved` 是
      "结算后"时点（RULES §7.4.12），与"A**fter** you cast"精确对应。
      战斗上下文由 `game.in_combat` 判定——与已注册的
      `batch_misc.StalwartKodoScript`（触发条件 `g.in_combat`）同一既有
      口径，无需任何新引擎事件。

读法（零新增裁定）:
  - "Get a Tide Raiser" = 交付 1 张 `BG34_920`（文本无数量词; 数据链
    `evolution_card_id` → `db.by_dbf`; `is_pool_minion=False` → 零池
    操作），与 `batch_trinkets37` 同构。
  - "get a copy of the spell" = 当场施放法术的 **plain 副本**入本人手牌：
    `create_spell(spell.card_id)` + `pending_hand_add`（复制自有卡不占池
    副本 + 满手排队）——`batch_hero_passives2.RockMasterVooneScript` 就
    "Spell → create_spell 同 id plain 副本"的既有先例，逐字同类。
  - "({1} times per combat.)" = 每场上限 `num(1)=3`; 额度存饰品实体
    `_tide_left`，在 `start_of_combat`（引擎按英雄各 fire 一次，
    `combat.py::_start_of_combat_phase` 第 1 步分发饰品）重置——
    `StalwartKodoScript` 的"每场战斗重置剩余次数"同一模式。
  - 只作用于本人: 事件携带 `spell.controller`，与本人不同即忽略。

数值权威: `data/bg_trinkets.json BG35_MagicItem_922`
（`script_data_num_1=3` → `num(0)` = "left!" 显示值, `script_data_num_2=3`
→ `num(1)` = 每场次数）。文本 `{0}`/`{1}` 均为 3。

负面对照（测试内）: 无饰品不产生副本 / 招募期施法不触发 / 对手施法不
触发 / 额度 3 次用尽后第 4 次不再发放 / 下一场战斗重置 / 饰品离场后
监听停用。
"""

from __future__ import annotations

from hsrl2.events import Listener


class TideRaiserPortraitScript:
    """
    Natural language: [x]Get a Tide Raiser. After you
    cast a spell in combat,
    get a copy of the spell.
    <i>({1} times per combat.)</i>

    Evidence: `data/bg_trinkets.json BG35_MagicItem_922`（Lesser,
    `spell_school=11`, cost 4, `evolution_card_id=126629` → `BG34_920`
    Tide Raiser）; 载荷脚本 `batch_payload_minions.TideRaiserScript`
    （战斗内 `cast_spell_effect`）; 事件 `spell_resolved`
    （`game.py` L1493，RULES §7.4.12）; 战斗上下文口径
    `batch_misc.StalwartKodoScript`（`g.in_combat`）; plain 法术副本
    先例 `batch_hero_passives2.RockMasterVooneScript`。

    Formal spec:
      1. on_bind: `game.grant_trinket_related_card(hero, source.card_id)`
         —— 数据链解析 `BG34_920` 并入手（非池卡 → 不占池; 满手经
         `pending_hand_add` 排队）。随后把本场额度初始化为 `num(1)`。
      2. 注册持久 **`spell_resolved`** 监听（owner=饰品; 效果结算后
         广播，RULES §7.4.12）。条件: `game.in_combat` ∧
         `spell.controller is 本人`。命中且剩余额度 >0 →
         `pending_hand_add(hero, create_spell(spell.card_id))`
         —— plain 副本（不复制 buff）、不动法术池（复制自有卡先例），
         额度 -1。
      3. 每场战斗 `start_of_combat`（`hero=` 本人）把额度重置为
         `num(1)`（每场 3 次）。
      4. 只作用于本人（对手施法/对手棋盘不触发）; 饰品离场后
         `owner=source` 的监听器随引擎注销，效果停止。

    Test: test_batch_trinkets38.py — 真实饰品商店路径绑定后入手 1 张
      BG34_920 / 真实亡语路径在 `in_combat` 下施放 Shifting Tide → 本人
      手牌出现同 id plain 副本、法术池零变化 / 招募期（`in_combat=False`）
      同一施放**不**产生副本 / 对手战斗内施法不产生副本 / 3 次额度用尽
      后第 4 次不再发放 / 下一场 `start_of_combat` 重置后才能再次获得 /
      无饰品对照无副本 / 饰品移除后不再触发。

    Params: 无模板参数（额度经 `num(1)=3` 读取，非字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        if game.trinket_related_card(source.card_id) is not None:
            game.grant_trinket_related_card(hero, source.card_id)
        source._tide_left = game.db.get(source.card_id).num(1)

        def on_soc(g, hero=None, _s=source, **kw):
            if hero is _s.controller:
                _s._tide_left = g.db.get(_s.card_id).num(1)

        def on_resolved(g, spell=None, _s=source, **kw):
            h = _s.controller
            if h is None or not g.in_combat:
                return
            if spell is None or getattr(spell, "controller", None) is not h:
                return
            cid = getattr(spell, "card_id", None)
            if cid is None or getattr(_s, "_tide_left", 0) <= 0:
                return
            _s._tide_left -= 1
            # plain 副本（不占池、不复制 buff）+ 满手排队
            g.pending_hand_add(h, g.create_spell(cid, controller=h))

        game.events.register(Listener(event="start_of_combat", owner=source,
                                      callback=on_soc))
        game.events.register(Listener(event="spell_resolved", owner=source,
                                      callback=on_resolved))
        return None


def register() -> list[str]:
    """注册饰品第 38 批 1 张（全部 CORRECT，0 DEFERRED）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG35_MagicItem_922", TideRaiserPortraitScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
