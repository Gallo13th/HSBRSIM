"""批次 trinkets1 — 饰品第一批（作业单 2026-09-01, 主线审计维修）。

饰品实体经 _offer_trinkets 购买 → hero.trinkets（SoC/EoT/SoT 钩子
已接线）; 脚本挂 on_bind(ctx={"hero": hero})（购买即时效果）+ 事件
监听。余下饰品台账见 AGENTS.md。

实现 8 张（文本直读 + 主线审计修正, 2026-09-01）:
  BG30_MagicItem_996 / 998 / 433
  BG32_MagicItem_111 / 271 / 400 / 887
  BG30_MagicItem_543（旧 DEFERRED 理由有误——授予物是既有池法术
    EBG_Spell_032 "Channel the Devourer"）

DEFERRED 4（撤注册，台账见各类 docstring）:
  BG30_MagicItem_992 — requires dynamic per-turn tavern buff primitive
    （动态逐回合酒馆 +1/+1 读取/重算原语不存在）（2026-09-02 已落地）
    Status: 已由 batch_trinkets24 注册（动态逐回合酒馆 Buff 原语已于 2026-09-02 落地）
  BG32_MagicItem_802 — requires 元素 give-stats 统一消费点
    （ELEMENTAL_EXTRA_ATK/HEALTH 只有写入方，读取侧
    batch_consume.elemental_buff 无生产调用点——对抗审计实证 no-op）（2026-09-02 已落地）
    Status: 已由 batch_trinkets24 注册（元素 give-stats 统一消费点已于 2026-09-02 落地）
  BG32_MagicItem_823 — "(if possible)" 限定语义查无 wiki Notes/官方
    证据（SOP §6b 第 4 步）
  BG30_MagicItem_888 — "transforms into a copy" 需 trinket 购买事件
    （引擎缺口，class 不在本文件）
"""

from __future__ import annotations

from hsrl2.actions import Buff, GainGold, GainKeyword, Transform
from hsrl2.actions.discover import _pool_candidates
from hsrl2.events import (
    CARD_PLAYED, COMBAT_END, TURN_START, Listener,
)
from hsrl2.tags import GameTag, Race

# BG30_MagicItem_543 "Get a Channel the Devourer" 的授予物——CardDB
# 按名字核实存在的池法术（非 token）
_CHANNEL_THE_DEVOURER = "EBG_Spell_032"


def _hero(ctx):
    return ctx.get("hero") if ctx else None


class T996:
    """Gain 4 Gold. Increase your maximum Gold by 4.

    Params: gold=4（文本字面量——CardDef 无模板参数）
    """
    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        game.run_actions(GainGold(h, 4))
        h.set(GameTag.INCOME_CAP_BONUS,
              h.get(GameTag.INCOME_CAP_BONUS, 0) + 4)


class T998:
    """Gain 2 Gold. The Tavern no longer offers cards from Tier 1 or
    Tier 2.

    Formal spec:
      1. on_bind: GainGold(hero, 2)
      2. 英雄作用域 `hero._tavern_min_tier = 3`——引擎读取
         `max(game._tavern_min_tier, hero._tavern_min_tier)`
         （game.refresh_tavern）: 仅本人酒馆下限抬到 T3;
         禁止写 game 级（旧实现污染全体对手酒馆）
      3. 只影响本人: 对手 hero 无该 flag，其酒馆仍可展出 T1/T2

    Test: test_batch_trinkets1.py — 本人 flag=3 + 本人酒馆无 T1/T2 /
    对手 flag 仍为默认且对手酒馆仍出 T1

    Params: gold=2 tier=3（文本字面量"Tier 1 or Tier 2"→下限 3）
    """
    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        game.run_actions(GainGold(h, 2))
        h._tavern_min_tier = max(getattr(h, "_tavern_min_tier", 1), 3)


class T433:
    """The first time a friendly minion dies each combat, give its
    maximum stats to a random friendly minion.

    Formal spec:
      1. on_bind 注册 death 监听器（owner=饰品）。仅当
         `game._active_combat is not None`（战斗内）且死者为本人随从
         时触发——招募期死亡不触发、也不消耗本场次数
      2. 每场战斗首次: 从本人**存活**随从中随机 1 个
         （game.rng.choice，排除死者）授予死者 atk / max_health
         （属性快照用 max_health 而非当前 health）
      3. 一次性: 本场第二次死亡不再触发; COMBAT_END 重置标记
         （闭包 nonlocal —— 状态随饰品实例隔离）

    Test: test_batch_trinkets1.py — 招募期死亡不触发 / 战斗内首次死亡
    恰好 buff 1 个随机友方且数值 = 死者 atk/max_health / 同场第二次
    不再触发 / COMBAT_END 后再死亡重新触发

    Params: 无模板参数（增益 = 死者运行时属性）
    """
    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        used = False

        def on_death(g, minion=None, **kw):
            nonlocal used
            if minion is None or used:
                return
            if getattr(g, "_active_combat", None) is None:
                return
            if minion.controller is not h:
                return
            used = True
            cands = [m for m in h.board if m is not minion and not m.dead]
            if not cands:
                return
            target = g.rng.choice(cands, label="t433")
            g.run_actions(Buff(target, atk=minion.atk,
                               health=minion.max_health))

        def on_ce(g, **kw):
            nonlocal used
            used = False

        game.events.register(Listener(event="death", owner=source,
                                      callback=on_death))
        game.events.register(Listener(event=COMBAT_END, owner=source,
                                      callback=on_ce))


class T992:
    """Minions in the Tavern have +1/+1 for each minion you've sold
    this turn.

    Status: 已由 batch_trinkets24 注册（动态逐回合酒馆 Buff 原语已于 2026-09-02 落地）

    Status: DEFERRED — requires dynamic per-turn tavern buff primitive
      （动态逐回合酒馆 buff 原语）。旧实现是"刷新时一次性 add_buff"：
      出售后不更新、冻结保留项重复叠加、回合中授予/新入馆随从拿不到
      当前计数——语义错误且无法用现有 ApplyTavernBuff/BuffCurrentTavern
      （只有"入馆一次性应用"语义）表达。按 SOP §6b 第 4 步撤注册。
    Dependency: 引擎需提供酒馆随从动态属性读取钩子（如按
      tavern_sold_this_turn 实时重算，或在 minion_sold 时对全馆重算并
      让后续入馆继承当前计数）

    Params: atk=1 health=1（文本字面量"for each minion you've sold"）
    """
    @staticmethod
    def on_bind(source, game, ctx):
        return None


class T111:
    """At the end of each turn, give a random friendly Murloc +8/+8
    and Venomous.

    Formal spec:
      1. 走饰品自身 end_of_turn 钩子（引擎 EoT 分发: 饰品 → 奖励 →
         随从）——不用全局 turn_end 监听器
      2. 候选 = 本人棋盘存活 Murloc（含 ALL 种族）; 随机 1 个
         （game.rng.choice）; 无候选则落空
      3. Buff(+8/+8) + GainKeyword(VENOMOUS)（关键词走 Action，广播
         keyword_gained）

    Test: test_batch_trinkets1.py — EoT 恰好 buff 1 个 Murloc +8/+8 且
    获得 Venomous / 非 Murloc 不触发 / 无 Murloc 落空

    Params: atk=8 health=8（文本字面量——CardDef 无模板参数）
    """
    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        cands = [m for m in h.board
                 if not m.dead and m.race in (Race.MURLOC, Race.ALL)]
        if not cands:
            return None
        m = game.rng.choice(cands, label="t111")
        return [Buff(m, atk=8, health=8),
                GainKeyword(m, GameTag.VENOMOUS)]


class T271:
    """Gain 2 Gold. Buy your Greater Trinket next turn instead of
    Turn 9.

    Formal spec:
      1. on_bind: GainGold(hero, 2)
      2. `hero._trinket_early = {"greater": 当前回合 + 1}`——引擎在
         `_begin_recruit_for` 读取，下一回合发放 Greater offer
         （offer 按 (hero, kind) 记账，不受 T6 Lesser 影响）

    Test: test_batch_trinkets1.py — 绑定后次回合确实出现
    `trinket_offer`（owner=本人）且 `(hero, "greater")` 入账

    Params: gold=2（文本字面量）
    """
    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        game.run_actions(GainGold(h, 2))
        h._trinket_early = {"greater": game.turn + 1}


class T400:
    """Transform all your minions into random Tier 4 minions.

    Formal spec:
      1. on_bind: 对本人棋盘每个存活随从，候选 =
         `_pool_candidates(min_tier=4, max_tier=4)`——只含池剩余 > 0
         且未被本局 active_races 禁用的 T4 随从; 无候选则跳过该随从
      2. 选中后先 `minion_pool.acquire(cid)` 占池（RULES §2.3），再
         `Transform(m, cid)`（保留原位置/buff/金色）
      3. 随机走 game.rng

    Test: test_batch_trinkets1.py — 全部随从变形为 T4 / active_races
    限制（禁龙时结果必为龙或全种族/无种族）/ 选中卡池余量 -1

    Params: tier=4（文本字面量"Tier 4"）
    """
    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        for m in list(h.board):
            if m.dead:
                continue
            cands = _pool_candidates(game, min_tier=4, max_tier=4)
            if not cands:
                continue
            cid = game.rng.choice(cands, label="t400")
            if not game.minion_pool.acquire(cid):
                continue
            game.run_actions(Transform(m, cid))


class T802:
    """Your Elementals that give stats grant an extra +2/+1.

    Status: 已由 batch_trinkets24 注册（元素 give-stats 统一消费点已于 2026-09-02 落地）

    Status: DEFERRED — 需要**元素 give-stats 统一消费点**（SOP §6b 第 4 步）。
    Dependency: `ELEMENTAL_EXTRA_ATK/HEALTH`（1057/1055）当前只有写入方
      （本卡 / Moat Custodian / Sand Swirler / Glowing Cinder），读取侧
      `batch_consume.elemental_buff()` **无任何生产调用点**（2026-09-01
      对抗审计实证: 绑定本卡前后真实元素 give-效果数值不变）（2026-09-02 已落地）——按旧
      `buff_applied`+`source_id` 启发式实现又是 no-op 第三态，故撤注册。
    撤注册前记录: 写入 tag 的代码保留（消费点建成后可直接复用）。
    """
    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        h.set(GameTag.ELEMENTAL_EXTRA_ATK,
              h.get(GameTag.ELEMENTAL_EXTRA_ATK, 0) + 2)
        h.set(GameTag.ELEMENTAL_EXTRA_HEALTH,
              h.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0) + 1)


class T823:
    """Gain 2 Gold and take 2 damage. At the start of each turn,
    repeat this (if possible).

    Status: DEFERRED — "(if possible)" 限定语义未证实。已查
      hearthstone.wiki.gg 卡片页（无 Notes/Wiki tags）与 36.2.2
      patch notes，无证据裁定限定对象：是"金币已达持有上限则跳过"、
      "生命不足以支付则跳过"，还是仅表示"仍有合法目标（未阵亡）"。
      不同读法在多回合/残血场景产生不同结果 → 按 SOP §6b 第 4 步
      撤注册，等待实测/新信源。
    Dependency: 无（语义裁决问题，非引擎缺口）
    """
    @staticmethod
    def on_bind(source, game, ctx):
        return None


class T887:
    """Gain 5 Armor. After you play a Demon, deal 1 damage to your
    hero.

    Params: armor=5 damage=1（文本字面量——CardDef 无模板参数）
    """
    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        h.armor += 5

        def on_played(g, card=None, **kw):
            if card is None or card.controller is not h:
                return
            # card_played 对随从与法术都广播（getattr 守卫——法术无 race）
            if getattr(card, "race", None) in (Race.DEMON, Race.ALL):
                h.take_damage(1)

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))


class T543:
    """[x]Get a Channel the Devourer. At the start of each turn, get
    another.

    Formal spec:
      1. on_bind: `game.pending_hand_add(hero,
         game.create_spell("EBG_Spell_032", controller=hero))`
         ——满手牌排队等待（RULES §3.3），禁止直接 append
      2. 注册 TURN_START 监听器（owner=饰品）: 本人每个回合开始再获得
         一张，同样走 pending_hand_add; 对手不受影响
      3. 授予物 = 既有池法术 EBG_Spell_032 "Channel the Devourer"
         （CardDB 按 id 核实存在且有脚本——旧 DEFERRED "token 不在 db"
         理由有误）

    Test: test_batch_trinkets1.py — 绑定入手 1 张 / 回合推进后再入手
    1 张且仍是 EBG_Spell_032 / 对手手牌不受影响

    Params: 无模板参数
    """
    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        game.pending_hand_add(
            h, game.create_spell(_CHANNEL_THE_DEVOURER, controller=h))

        def on_ts(g, hero=None, turn=None, **kw):
            if hero is h:
                g.pending_hand_add(
                    h, g.create_spell(_CHANNEL_THE_DEVOURER,
                                      controller=h))

        game.events.register(Listener(event=TURN_START, owner=source,
                                      callback=on_ts))


def register() -> list[str]:
    """注册饰品第一批 8 张（992/802/823 已按 SOP §6b 撤注册）。

    Status: BG30_MagicItem_992 / BG32_MagicItem_802 已由 batch_trinkets24 注册
      （动态逐回合酒馆 Buff 原语 / 元素 give-stats 统一消费点已于 2026-09-02
      落地; 上述撤注册保留为历史台账）。
    """
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG30_MagicItem_996", T996),
        ("BG30_MagicItem_998", T998),
        ("BG30_MagicItem_433", T433),
        ("BG32_MagicItem_111", T111),
        ("BG32_MagicItem_271", T271),
        ("BG32_MagicItem_400", T400),
        # ("BG32_MagicItem_802", T802) — DEFERRED: 元素 give-stats
        # 统一消费点缺失（ELEMENTAL_EXTRA_* 无生产读取方; 见类 docstring）（2026-09-02 已落地）
        # Status: 已由 batch_trinkets24 注册（元素 give-stats 统一消费点已于 2026-09-02 落地）
        ("BG32_MagicItem_887", T887),
        ("BG30_MagicItem_543", T543),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
