"""Spellcraft 法术 on_play 脚本 — 批次 1（2026-08-21 作业单，3 张）。

覆盖: BG23_000t Mini-Myrmidon 法术 / BG23_007t Waverider 法术 /
BG23_008t Glowscale 法术（各含金色法术 id 注册——金色法术是独立卡
定义，同一脚本类经 source.card_id 的 CardDef.num() 自然体现数值差异）。

"until next turn" 生命周期 (RULES §6.13): 临时法术提供的增益持续到
**下一个招募阶段开始**。实现为 TURN_START once 监听器（owner=目标随从，
condition=控制者匹配）。引擎缺口注: entity.clear_temporary_buffs 无引擎
调用点（招募期 temporary buff 无全局清除机制），故由脚本层按来源精确
移除; 若主线日后在 _begin_recruit_for 统一清除，本方案的 remove_buff
对已消失的 buff 是无害 no-op。
"""

from __future__ import annotations

from hsrl2 import entity
from hsrl2.actions import GainKeyword, LoseKeyword
from hsrl2.events import TURN_START, Listener
from hsrl2.tags import GameTag, Race

_NAGA_RACES = (Race.NAGA, Race.ALL)      # ALL 视为所有种族 (RULES §6.18)


def _spell_target(ctx):
    """on_play 目标解析。

    引擎缺口: play_spell 无 needs_target/PendingChoice 分流（仅
    play_minion 有），target 由调用方直接传入; None 时效果落空
    （返回 None，禁止随机近似——SOP 裁定先例）。
    """
    return ctx.get("target") if ctx else None


def _expire_at_next_turn(game, spell, target, *, buffs=None, keywords=None):
    """注册"持续到下一个招募阶段开始"的过期监听器 (RULES §6.13)。

    - buffs: 到期**精确**移除的 entity.Buff 对象列表（闭包引用，非
      全量 clear_temporary_buffs——不动其他来源的临时/永久 buff）;
      含生命值的 buff 移除后 HEALTH 封顶到 max_health
    - keywords: {GameTag: 施加前目标是否已持有} —— 施加前没有的才在
      到期时移除（防误删目标自带的永久关键词）
    - 生命周期: owner=target（离场自动注销）; once=True +
      condition hero is target.controller（只在目标控制者的下一个
      招募阶段开始触发，其他英雄的 turn_start 不消耗 once）;
      监听器随战斗快照恢复跨战斗存活（game.run_combat）
    """
    buffs = list(buffs or [])
    keywords = dict(keywords or {})

    def _on_turn_start(g, hero=None, **kw):
        for b in buffs:
            # Lava Lurker 永久化翻转后的 buff 不回收（temporary=False）
            if not b.temporary:
                continue
            target.remove_buff(b)
        if any(b.health > 0 for b in buffs):
            target.set(GameTag.HEALTH,
                       min(target.health, target.max_health))
        for tag, had_before in keywords.items():
            if not had_before:
                g.run_actions(LoseKeyword(target, tag))

    game.events.register(Listener(
        event=TURN_START,
        owner=target,
        once=True,
        condition=lambda hero=None, **kw: hero is target.controller,
        callback=_on_turn_start,
    ))


class MiniMyrmidonSpellScript:
    """
    Natural language: [x]Give a minion +2_Attack until next turn.
    （金色 BG23_000_Gt: +4_Attack until next turn.）

    Formal spec:
      1. on_play（play_spell 已移出手牌/施放计数后）: ctx["target"]
         获得 temporary 属性 buff（atk=CardDef.num(0)，temporary=True,
         source_id=法术 card_id）
      2. 过期: 目标控制者的下一个招募阶段开始时精确移除该 buff
         （TURN_START once 监听器，RULES §6.13 "持续到下一个招募
         阶段开始"）
      3. target=None（定向法术无 PendingChoice 分流，引擎缺口）→
         效果落空（法术仍被消耗——play_spell 语义）

    Test: test_spellcraft.py — atk +num(0) 立即生效 / 下一回合开始
    回落 / 金色 BG23_000_Gt 为 +4 / 无模板参数时字面量回落

    Params: {0}=2（BG23_000t 文本字面量——CardDef 无模板参数，
    num(0,2) 回落）; 金色 {0}=4
    """

    @staticmethod
    def on_play(source, game, ctx):
        target = _spell_target(ctx)
        if target is None:
            return None
        d = game.db.get(source.card_id)
        buff = entity.Buff(atk=d.num(0, 2), temporary=True,
                           source_id=source.card_id)
        target.add_buff(buff)
        _expire_at_next_turn(game, source, target, buffs=[buff])
        return None


class MiniMyrmidonGoldenSpellScript(MiniMyrmidonSpellScript):
    """
    Natural language: [x]Give a minion +4_Attack until next turn.
    （BG23_000_Gt; 基础版 BG23_000t 为 +2）

    Formal spec: 同 MiniMyrmidonSpellScript，仅 CardDef 无模板参数时
    的文本字面量回落不同（金色 +4）。

    Test: test_spellcraft.py — 金色 +4 / 下一回合开始回落

    Params: {0}=4（BG23_000_Gt 文本字面量，num(0,4) 回落）
    """

    @staticmethod
    def on_play(source, game, ctx):
        target = _spell_target(ctx)
        if target is None:
            return None
        d = game.db.get(source.card_id)
        buff = entity.Buff(atk=d.num(0, 4), temporary=True,
                           source_id=source.card_id)
        target.add_buff(buff)
        _expire_at_next_turn(game, source, target, buffs=[buff])
        return None


class WaveriderSpellScript:
    """
    Natural language: [x]Give a minion +{0}/+{1}. If it's a Naga, also give
    it <b>Windfury</b> until next turn.

    Formal spec:
      1. on_play: target 获得 temporary +num(0)/+num(1) buff
      2. target.race 为 Naga（含 ALL 种族）时: 额外获得 Windfury——
         临时关键词，与属性 buff 同一过期时点
      3. 过期监听器: 属性 buff 精确移除 + HEALTH 封顶; Windfury 仅当
         施加前目标未持有才移除（自带永久风怒不误删）
      4. "until next turn" 适用于关键词部分——RULES §6.13 "临时法术
         提供的增益持续到下一个招募阶段开始"（增益含关键词）
      5. target=None → 落空

    Test: test_spellcraft.py — +num(0)/+num(1) 生效 / Naga 目标获得
    风怒且下回合开始消失 / 非 Naga 目标无风怒 / 自带风怒目标过期后
    仍保留 / 金色 BG23_007_Gt 为 +4/+4

    Params: {0}=2 {1}=2（BG23_007t）; 金色 {0}=4 {1}=4（BG23_007_Gt）
    """

    @staticmethod
    def on_play(source, game, ctx):
        target = _spell_target(ctx)
        if target is None:
            return None
        d = game.db.get(source.card_id)
        buff = entity.Buff(atk=d.num(0), health=d.num(1), temporary=True,
                           source_id=source.card_id)
        target.add_buff(buff)
        keywords = {}
        if target.race in _NAGA_RACES:
            keywords[GameTag.WINDFURY] = target.has(GameTag.WINDFURY)
            game.run_actions(GainKeyword(target, GameTag.WINDFURY))
        _expire_at_next_turn(game, source, target,
                             buffs=[buff], keywords=keywords)
        return None


class GlowscaleSpellScript:
    """
    Natural language: Give a minion <b>Divine_Shield</b> until next turn.
    （金色 BG23_008_Gt 同文——DS 无数值差异，仅来源随从金色。）

    Formal spec:
      1. on_play: target 获得 Divine Shield（若此前没有）
      2. 过期: 目标控制者的下一个招募阶段开始时移除（施加前已持有
         则保留）
      3. 战斗交互: 招募期授予的 DS 被战斗消耗后，引擎快照恢复会复原
         tag（run_combat restore_state），随后由过期监听器在下一
         回合开始统一清除——恢复与清除之间无玩家操作窗口，语义等价
      4. target=None → 落空

    Test: test_spellcraft.py — DS 立即获得 / 下一回合开始消失 /
    自带 DS 目标过期后仍保留 / 金色 BG23_008_Gt 同效

    Params: 无数值参数（文本无占位符）
    """

    @staticmethod
    def on_play(source, game, ctx):
        target = _spell_target(ctx)
        if target is None:
            return None
        keywords = {GameTag.DIVINE_SHIELD: target.has(GameTag.DIVINE_SHIELD)}
        game.run_actions(GainKeyword(target, GameTag.DIVINE_SHIELD))
        _expire_at_next_turn(game, source, target, keywords=keywords)
        return None
