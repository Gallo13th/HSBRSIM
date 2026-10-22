"""批次 quest_rewards — 任务奖励 42 注册项（作业单 2026-09-01）。

奖励实体经 game.complete_quest 发放 → hero.quest_rewards（SoC/EoT/SoT
钩子已全线接线）; 脚本挂 on_bind（一次性接线）与各事件监听。

2026-09-01 语义维修（主线审计 28 处缺陷，本批修复）:
  - 恒真 guard（`hero is not hero`）→ 默认绑定 `_h=hero`（R109/R111）
  - 错误 API / 不存在符号: R708 英雄上限生命（C.HERO_BASE_HEALTH）、
    R806 对手板快照（game.next_opponent_warband）、R815 血宝石真实 API、
    R514/R515 池法术真实来源 + scripts.needs_target + 入手续打
  - 一次性 vs 每回合: R311 无时机文本 → on_bind 立即结算;
    R014/R015 "next turn" → once + condition
  - 时序: R810 card_played 在召唤后 → 打出前类型集（排除刚打出者）
  - 快照/池: R309 候选重算 + ConsumeMinion（回池）、R308 增量应用
  - temporary 惰性: R312 脚本侧 SoC→战斗结束 Buff 过期
  - plain copy: R138/R502t/R506 不复制附魔/金色
  - 数值数据源: R311/R361/R508 读 CardDef.num(0)
  - 变体恒等式: R321/R321t 奇偶按卡牌文本（Even/Odd）分别注册
  - R331 Amalgam（Race.ALL）计入一个受控类型; R364 "die" = Destroy
  - R010 Norgannon's Reward 补实现（T7 解锁 + 下回合免费升级）

DEFERRED 31（台账; 73 奖励总数 − 42 注册）:
  {0} 占位符（客户端注入, data 无权威值）: BG24_Reward_130 /
    BG24_Reward_134 / BG24_Reward_306 / BG27_Reward_802 /
    BG27_Reward_803 / BG27_Reward_812 / BG28_Reward_510 /
    BG33_Reward_021;
  奖励实体上的 Avenge（引擎复仇计数仅扫棋盘随从）: BG27_Reward_502 /
    BG28_Reward_504 / BG28_Reward_518 / BG33_Reward_004;
  奖励实体上的 Spellcraft 法术实体: BG24_Reward_718 /
    BG24_Reward_719 / BG33_Reward_006;
  缺失子系统: BG24_Reward_135(Wheel of Yogg-Saron——2026-09-18 复核:
    wiki 无 Wheel 页、无 token、结果集与概率只记在别的卡页且与现行
    数据冲突) / BG24_Reward_715(Enhanced Part
    token) / BG27_Reward_504(Accelerator token) / BG28_Reward_513(Buddy);
  初始值/频率无权威: BG28_Reward_509(tier @) / BG28_Reward_505(@) /
    BG24_Reward_313(Occasionally——2026-09-18 复核: wiki 无 Notes、
    `insource:"helpful Refresh"` 0 命中、无概率) /
    BG28_Reward_500(持久法术折扣钩子) /
    BG28_Reward_501(法术双施钩子) / BG33_Reward_020(+{3}/+{1} 无值) /
    BG24_Reward_113(+5/+5 语义) / BG33_Reward_011(教法术) /
    BG33_Reward_017(第二技能槽) / BG24_Reward_310(Golden Buddy) /
    BG27_Anomaly_555t(对手历史——2026-09-18 复核: token 在 wiki 上
    **不存在**，`insource:"106440"`=0; 猜谜 UI/后果/Coin 全缺)。

  **已迁出（2026-09-18 第四十九轮）**: BG24_Reward_362(Essence of
    Zerus) → `batch_quest_rewards8`（载荷 `BGS_029` 一并注册; wiki 权威
    见该批 docstring）。

2026-09-01 对抗审计补录: BG33_Reward_010 Norgannon's Reward 已实现
（T7 解锁 + 下回合免费升级; 此前漏登记在 DEFERRED 台账中）。
"""

from __future__ import annotations

import hsrl2.constants as C
from hsrl2.actions import (
    Discover, GainGold, TriggerBattlecry,
)
from hsrl2.actions.bloodgem import GetBloodGems, ImproveBloodGems
from hsrl2.actions.consume import ConsumeMinion
from hsrl2.entity import Buff as BuffEnchant
from hsrl2.events import (
    COMBAT_END, MINION_BOUGHT, MINION_SOLD, SUMMON, TURN_START, Listener,
)
CARD_DISCOVERED = "card_discovered"   # game.PendingChoice.choose 触发
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.tags import CardType, GameTag, Race, Zone

_TAUNT = GameTag.TAUNT


def _plain_copy(game, ent):
    """官方 "plain copy": 无附魔、非金色（S14 用语）。

    - Minion: 回退基础卡 id（三连金/非三连金均走 TRIPLE_BASE_CARD_ID）
      后按**非金色**创建; 不复制 `_buffs`、不复制 GOLDEN 态
    - Spell: 同名法术实体（法术无附魔/金色态）
    """
    if isinstance(ent, Minion):
        base_id = ent.get(GameTag.TRIPLE_BASE_CARD_ID, None) or ent.card_id
        return game.create_minion(base_id, controller=ent.controller,
                                  golden=False)
    return game.create_spell(ent.card_id, controller=ent.controller)


# ══════════════ BG24 批（Season 11）══════════════

class R107:
    """EoT: 2 friendly minions trigger their Battlecries."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_te(g, turn=None, _h=hero, **kw):
            alive = [m for m in _h.board if not m.dead]
            if not alive:
                return
            picks = g.rng.sample(alive, min(2, len(alive)),
                                 label="r107_bc")
            for m in picks:
                g.run_actions(TriggerBattlecry(m))
        game.events.register(Listener(event="turn_end", owner=source,
                                      callback=on_te))


class R109:
    """SoC: left and right-most minions become Golden."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_soc(g, hero=None, _h=hero, **kw):
            if hero is not _h:      # owner 隔离（多英雄 SoC）
                return
            board = [m for m in _h.board if not m.dead]
            if not board:
                return
            targets = ([board[0]] if board[0] is board[-1]
                       else [board[0], board[-1]])
            for m in targets:
                _goldenize(g, m)
        game.events.register(Listener(event="start_of_combat",
                                      owner=source, callback=on_soc))


class R111:
    """SoC: Summon a copy of your highest-Health minion."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_soc(g, hero=None, _h=hero, **kw):
            if hero is not _h:      # owner 隔离（多英雄 SoC）
                return
            alive = [m for m in _h.board if not m.dead]
            if not alive or _h.board_full():
                return
            best = max(alive, key=lambda m: m.max_health)
            copy = g.create_minion(best.card_id, controller=_h,
                                   golden=best.is_golden)
            best.copy_buffs_to(copy)
            g.summon(_h, copy)
        game.events.register(Listener(event="start_of_combat",
                                      owner=source, callback=on_soc))


class R115:
    """EoT: right-most minion +Stealth until next turn and +8 Health.

    Params: health=8（文本字面量——CardDef 无模板参数）"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_te(g, turn=None, _h=hero, **kw):
            alive = [m for m in _h.board if not m.dead]
            if not alive:
                return
            m = alive[-1]
            # 仅 Stealth 是 "until next turn"; +8 Health 为永久（不得
            # 标 temporary——引擎无 temporary 清除点，语义会漂移）
            m.add_buff(BuffEnchant(atk=0, health=8))
            m.set(GameTag.STEALTH, True)

            def on_ts(g, hero=None, turn=None, _m=m, _h=_h, **kw):
                if hero is _h:
                    _m.clear(GameTag.STEALTH)
            # once + condition: 只在本英雄的下个回合开始清除一次，
            # 不累积监听器（旧实现每次 EoT 追加一个常驻监听）
            game.events.register(Listener(
                event=TURN_START, owner=m, callback=on_ts, once=True,
                condition=lambda hero=None, _h=_h, **kw: hero is _h))
        game.events.register(Listener(event="turn_end", owner=source,
                                      callback=on_te))


class R123:
    """Your first Battlecry each turn triggers 2 extra times."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        hero._r123_used = False

        def on_bc(g, minion=None, _h=hero, **kw):
            # 非本英雄的战吼不消耗次数; minion=None 不消耗
            if minion is None or minion.controller is not _h:
                return
            if getattr(_h, "_r123_used", False):
                return
            _h._r123_used = True
            g.run_actions(TriggerBattlecry(minion))
            g.run_actions(TriggerBattlecry(minion))

        def on_ts(g, hero=None, turn=None, _h=hero, **kw):
            if hero is _h:
                _h._r123_used = False
        game.events.register(Listener(event="battlecry_trigger",
                                      owner=source, callback=on_bc))
        game.events.register(Listener(event=TURN_START, owner=source,
                                      callback=on_ts))


class R125:
    """Your minions have +4 Attack（召唤即 +4 永久——光环等价的
    持久化实现, 变形/沉默边缘差异记档）。

    Params: atk=4（文本字面量——CardDef 无模板参数）"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_summon(g, minion=None, _h=hero, **kw):
            if minion is not None and minion.controller is _h:
                minion.add_buff(BuffEnchant(atk=4, health=0))
        for m in list(hero.board):
            m.add_buff(BuffEnchant(atk=4, health=0))
        game.events.register(Listener(event=SUMMON, owner=source,
                                      callback=on_summon))


class R128:
    """After the Tavern is Refreshed, give a random minion in it
    +6/+6 and Divine Shield.

    Params: atk=6 health=6（文本字面量——CardDef 无模板参数）"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_ref(g, hero=None, _h=hero, **kw):
            if hero is not _h:
                return
            t = [m for m in _h.tavern if isinstance(m, Minion)]
            if not t:
                return
            m = g.rng.choice(t, label="r128")
            m.add_buff(BuffEnchant(atk=6, health=6))
            m.set(GameTag.DIVINE_SHIELD, True)
        game.events.register(Listener(event="tavern_refresh",
                                      owner=source, callback=on_ref))


class R129:
    """After you Discover a card, get an extra copy of it.

    Formal spec: card_discovered 同时携带随从与法术 id——按 option 的
    卡牌类型分流，法术走 create_spell（旧实现一律 create_minion 会造出
    伪随从）。dark_gift 选项是 card_type 5 的**非卡牌效果实体**
    （BG36_MidGameEffect_*），必须排除。注意: data 中 BG 酒馆法术
    card_type=42（枚举外→CardType.INVALID），故并集 is_pool_spell，
    而非仅 card_type。
    """
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_disc(g, hero=None, option=None, kind=None, _h=hero, **kw):
            if hero is not _h or not isinstance(option, str):
                return
            if kind == "dark_gift":
                return       # 非卡牌效果实体，不得复制
            d = g.db.get(option)
            if d is None:
                return       # 未入册 option
            if d.is_pool_spell or d.card_type in (CardType.SPELL,
                                                  CardType.BACON_SPELL):
                g.pending_hand_add(_h, g.create_spell(option,
                                                      controller=_h))
            elif d.is_pool_minion or d.card_type == CardType.MINION:
                g.pending_hand_add(_h, g.create_minion(option,
                                                       controller=_h))
        game.events.register(Listener(event=CARD_DISCOVERED, owner=source,
                                      callback=on_disc))


class R131:
    """SoT: give a minion in your hand +12/+12.

    Params: atk=12 health=12（文本字面量——CardDef 无模板参数）"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_ts(g, hero=None, turn=None, _h=hero, **kw):
            if hero is not _h:
                return
            hand = [m for m in _h.hand if isinstance(m, Minion)]
            if not hand:
                return
            m = g.rng.choice(hand, label="r131")
            m.add_buff(BuffEnchant(atk=12, health=12))
        game.events.register(Listener(event=TURN_START, owner=source,
                                      callback=on_ts))


class R136:
    """EoT: +3/+3 to 3 friendly minions of Tier 3 or lower.

    Params: atk=3 health=3 count=3（文本字面量——CardDef 无模板参数）"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_te(g, turn=None, _h=hero, **kw):
            cands = [m for m in _h.board
                     if not m.dead and m.tech_level <= 3]
            if not cands:
                return
            for m in g.rng.sample(cands, min(3, len(cands)),
                                  label="r136"):
                m.add_buff(BuffEnchant(atk=3, health=3))
        game.events.register(Listener(event="turn_end", owner=source,
                                      callback=on_te))


class R138:
    """After each combat, get a plain copy of the last friendly minion
    that died."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_ce(g, hero_a=None, hero_b=None, _h=hero, **kw):
            if _h is not hero_a and _h is not hero_b:
                return       # 只结算本英雄参与的战斗
            last = None
            for m in reversed(g.combat_death_log):
                if m.controller is _h:
                    last = m
                    break
            if last is not None:
                g.pending_hand_add(_h, _plain_copy(g, last))
        game.events.register(Listener(event=COMBAT_END, owner=source,
                                      callback=on_ce))


class R305:
    """After you sell a minion, give its stats to a minion in the
    Tavern."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_sold(g, minion=None, _h=hero, **kw):
            if minion is None or minion.controller is not _h:
                return
            t = [m for m in _h.tavern if isinstance(m, Minion)]
            if not t:
                return
            m = g.rng.choice(t, label="r305")
            m.add_buff(BuffEnchant(atk=minion.atk, health=minion.health))
        game.events.register(Listener(event=MINION_SOLD, owner=source,
                                      callback=on_sold))


class R308:
    """Minions in the Tavern have +1/+1 for each time it was Refreshed
    this turn."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_ref(g, hero=None, _h=hero, **kw):
            if hero is not _h:
                return
            n = getattr(_h, "_r308_refs", 0) + 1
            _h._r308_refs = n
            for m in [m for m in _h.tavern if isinstance(m, Minion)]:
                # 只补本次刷新相较该随从上次应用以来的增量——幸存随从
                # 跨两次刷新得 +2 而非 +3
                applied = getattr(m, "_r308_applied", 0)
                delta = n - applied
                if delta > 0:
                    m.add_buff(BuffEnchant(atk=delta, health=delta))
                    m._r308_applied = n

        def on_ts(g, hero=None, turn=None, _h=hero, **kw):
            if hero is not _h:
                return
            _h._r308_refs = 0
            for m in [m for m in _h.tavern if isinstance(m, Minion)]:
                m._r308_applied = 0
        game.events.register(Listener(event="tavern_refresh",
                                      owner=source, callback=on_ref))
        game.events.register(Listener(event=TURN_START, owner=source,
                                      callback=on_ts))


class R309:
    """EoT: left and right-most minions consume a minion in the Tavern
    to gain its stats.

    目标选择走 `game.pick_consume_victim(m, ...)`（RULES §7.4.16b:
    Implicator Portrait 命中且消费者为恶魔时 = 最高 max_health，否则
    均匀随机）。
    """
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_te(g, turn=None, _h=hero, **kw):
            # 淘汰者不再行动（引擎 `_process_eliminations` 会清空其区域并
            # 注销监听器；此为第二道防线——2026-09-13 压测 seed 5066）
            if _h not in g.heroes:
                return
            alive = [m for m in _h.board if not m.dead]
            if not alive:
                return
            targets = ([alive[0]] if alive[0] is alive[-1]
                       else [alive[0], alive[-1]])
            for m in targets:
                if m.dead:
                    continue
                # 每次**重算**候选（上一次吞噬已移除受害者）; 走
                # ConsumeMinion：吃 max_health 快照 + 酒馆来源回池
                t = [x for x in _h.tavern
                     if isinstance(x, Minion) and not x.dead
                     and x.zone == Zone.TAVERN]
                if not t:
                    return
                food = g.pick_consume_victim(m, t, label="r309_food")
                ConsumeMinion(m, food).do(g)
        game.events.register(Listener(event="turn_end", owner=source,
                                      callback=on_te))


class R311:
    """Discover a minion of your Tier. (Can be earned endlessly!)

    Formal spec: 文本无时机子句（wiki: 立即 Discover）→ on_bind 一次性
    结算，非常驻 TURN_START。选项数 = CardDef.num(0)。

    Params: 无模板参数（Discover 选项数恒为引擎默认 3——`num(0)` 非
            选项数，2026-09-01 对抗审计修正 count=1 退化 bug）"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        tier = hero.tavern_tier
        # 即时 Discover 一次（3 选 1）——`Discover.count` 是**选项数**
        # 不是发现次数; 旧实现传 num(0)=1 导致单选退化
        game.run_actions(Discover(hero, min_tier=tier,
                                  max_tier=tier, kind="discover_minion"))


class R312:
    """SoC: Give your minions +12/+12.

    Formal spec: SoC 施加 +12/+12；战斗结束（COMBAT_END，本英雄参战）
    由脚本侧过期：移除**本次施加的精确 Buff 对象**，不依赖 temporary
    （引擎无 temporary 清除调用点）。监听器在 on_bind 注册（战斗快照
    前），故战斗监听器表复原不会丢失过期钩子。

    Params: atk=12 health=12（文本字面量——CardDef 无模板参数）"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        applied = []

        def on_soc(g, hero=None, _h=hero, **kw):
            if hero is not _h:
                return
            for m in _h.board:
                if m.dead:
                    continue
                b = BuffEnchant(atk=12, health=12)
                m.add_buff(b)
                applied.append((m, b))

        def on_ce(g, hero_a=None, hero_b=None, _h=hero, **kw):
            if _h is not hero_a and _h is not hero_b:
                return
            for m, b in applied:
                m.remove_buff(b)
            applied.clear()
        game.events.register(Listener(event="start_of_combat",
                                      owner=source, callback=on_soc))
        game.events.register(Listener(event=COMBAT_END, owner=source,
                                      callback=on_ce))


class R321:
    """Even-Tier minions in the Tavern have +7/+7.
    (Swaps to Odd next turn!)

    Formal spec: 奇偶从卡牌文本读取（Even-Tier/Odd-Tier）——321 与 321t
    是两个独立定义的 id，禁止同一类硬编码分支。光环在 on_bind 立即施加
    当前酒馆，tavern_refresh 对入馆随从补施，TURN_START 交换奇偶时移除
    仍在酒馆者身上的精确 Buff 并重施。

    Params: atk=7 health=7（文本字面量——CardDef 无模板参数）"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        d = game.db.get(source.card_id)
        text = d.text if d is not None else ""
        if "Even-Tier" in text:
            even = True
        elif "Odd-Tier" in text:
            even = False
        else:
            return       # 文本无奇偶证据 → 不近似实现
        state = {"even": even, "applied": {}}

        def matching():
            return [m for m in hero.tavern
                    if isinstance(m, Minion) and not m.dead
                    and (m.tech_level % 2 == 0) == state["even"]]

        def apply_all():
            for m in matching():
                if m in state["applied"]:
                    continue
                b = BuffEnchant(atk=7, health=7)
                m.add_buff(b)
                state["applied"][m] = b

        def on_refresh(g, hero=None, _h=hero, **kw):
            if hero is not _h:
                return
            apply_all()

        def on_ts(g, hero=None, turn=None, _h=hero, **kw):
            if hero is not _h:
                return
            for m, b in list(state["applied"].items()):
                if m in _h.tavern:      # 已被购买者保留（永久）
                    m.remove_buff(b)
            state["applied"].clear()
            state["even"] = not state["even"]
            apply_all()

        apply_all()
        game.events.register(Listener(event="tavern_refresh",
                                      owner=source, callback=on_refresh))
        game.events.register(Listener(event=TURN_START, owner=source,
                                      callback=on_ts))


class R321t(R321):
    """Odd-Tier minions in the Tavern have +7/+7.
    (Swaps to Even next turn!)

    Formal spec: 同 R321——奇偶由本卡文本（Odd-Tier）解析，独立注册项。

    Params: atk=7 health=7（文本字面量——CardDef 无模板参数）"""


class R331:
    """EoT: +1/+1 for each different friendly minion type."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_te(g, turn=None, _h=hero, **kw):
            # Amalgam（Race.ALL）算一个受控类型（R331 裁定）; NONE 不计
            types = {m.race for m in _h.board
                     if not m.dead and m.race != Race.NONE}
            if not types:
                return
            for m in _h.board:
                if not m.dead:
                    m.add_buff(BuffEnchant(atk=len(types), health=len(types)))
        game.events.register(Listener(event="turn_end", owner=source,
                                      callback=on_te))


class R350:
    """You only need 2 copies of a minion to make it Golden."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        hero.set(GameTag.TRIPLE_THRESHOLD, 2)


class R361:
    """SoT: gain @ Gold. (Improves each turn!)

    Formal spec: 首次发放 = CardDef.num(0)（@ 的初始值）; 每过一个
    回合发放量 +num(0)。

    Params: {0}=1"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        d = game.db.get(source.card_id)
        base = d.num(0) if d is not None else None
        if base is None:
            return
        hero._r361_turns = 0

        def on_ts(g, hero=None, turn=None, _h=hero, **kw):
            if hero is not _h:
                return
            turns = getattr(_h, "_r361_turns", 0)
            _h._r361_turns = turns + 1
            g.run_actions(GainGold(_h, base + turns * base))
        game.events.register(Listener(event=TURN_START, owner=source,
                                      callback=on_ts))


class R363:
    """SoT: choose from 2 new Rewards.

    Formal spec: 每个回合开始提供**恰好 2** 个新奖励（无 None 放弃项，
    文本 "choose from 2 new Rewards"）; 选定后**替换**上一回合由本奖励
    选出的那个奖励（实体列表轮换——旧奖励离场并注销其监听器），本奖励
    实体自身保留以持续每回合触发。

    Params: 无（"2" 为文本字面量——CardDef 无模板参数）"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        hero._r363_current = None

        def on_ts(g, hero=None, turn=None, _h=hero, **kw):
            if hero is not _h:
                return
            cur = getattr(_h, "_r363_current", None)
            cur_id = cur.card_id if cur is not None else None
            cands = [d.id for d in g.db._by_id.values()
                     if d.id.startswith("BG24_Reward_")
                     and d.id != source.card_id
                     and d.id != cur_id]
            if len(cands) < 2:
                return
            opts = g.rng.sample(cands, 2, label="r363")

            def resolve(rid):
                old = getattr(_h, "_r363_current", None)
                if old is not None:
                    if old in _h.quest_rewards:
                        _h.quest_rewards.remove(old)
                    g.events.unregister_owner(old)
                new = g.create_entity(rid, controller=_h)
                _h.quest_rewards.append(new)
                g.run_on_bind(new, ctx={"hero": _h})
                _h._r363_current = new

            g.pending_choices.append(PendingChoice(
                _h, opts, "reward_replace", resolve_callback=resolve))
        game.events.register(Listener(event=TURN_START, owner=source,
                                      callback=on_ts))


class R364:
    """Your minions have +7/+7. After they attack, they die. Horribly.

    Params: atk=7 health=7（文本字面量——CardDef 无模板参数）"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_summon(g, minion=None, _h=hero, **kw):
            if minion is not None and minion.controller is _h:
                minion.add_buff(BuffEnchant(atk=7, health=7))

        def on_aa(g, attacker=None, _h=hero, **kw):
            if attacker is None or attacker.controller is not _h \
                    or attacker.dead:
                return
            # Destroy 语义（无视圣盾）——统一入口 + minion_destroyed 广播
            g.destroy_minion(attacker, source=source)
        for m in list(hero.board):
            m.add_buff(BuffEnchant(atk=7, health=7))
        game.events.register(Listener(event=SUMMON, owner=source,
                                      callback=on_summon))
        game.events.register(Listener(event="after_attack", owner=source,
                                      callback=on_aa))


class R708:
    """EoT: right-most minion gains Attack equal to your missing
    Health."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        hero_def = game.db.get(hero.card_id)
        base = (hero_def.health
                if hero_def is not None and hero_def.health > 0
                else C.HERO_BASE_HEALTH)

        def on_te(g, turn=None, _h=hero, **kw):
            alive = [m for m in _h.board if not m.dead]
            if not alive:
                return
            missing = base - _h.health
            if missing > 0:
                alive[-1].add_buff(BuffEnchant(atk=missing, health=0))
        game.events.register(Listener(event="turn_end", owner=source,
                                      callback=on_te))


class R712:
    """After you play a minion, give 2 other friendly minions of its
    Tier +4/+4.

    Params: atk=4 health=4 count=2（文本字面量——CardDef 无模板参数）"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_played(g, card=None, _h=hero, **kw):
            if card is None or card.controller is not _h \
                    or not isinstance(card, Minion):
                return
            cands = [m for m in _h.board
                     if m is not card and not m.dead
                     and m.tech_level == card.tech_level]
            if not cands:
                return
            for m in g.rng.sample(cands, min(2, len(cands)), label="r712"):
                m.add_buff(BuffEnchant(atk=4, health=4))
        game.events.register(Listener(event="card_played", owner=source,
                                      callback=on_played))


# ══════════════ BG27/BG28 批（Season 11.5-12）══════════════

class R503:
    """When you buy a minion, give its stats to a random friendly
    minion."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_bought(g, minion=None, _h=hero, **kw):
            if minion is None or minion.controller is not _h:
                return
            alive = [m for m in _h.board if not m.dead]
            if not alive:
                return
            t = g.rng.choice(alive, label="r503")
            t.add_buff(BuffEnchant(atk=minion.atk, health=minion.health))
        game.events.register(Listener(event=MINION_BOUGHT, owner=source,
                                      callback=on_bought))


class R804:
    """EoT: minions without Taunt +1/+2 for each friendly Taunt."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_te(g, turn=None, _h=hero, **kw):
            n = sum(1 for m in _h.board
                    if not m.dead and m.has(_TAUNT))
            if not n:
                return
            for m in _h.board:
                if not m.dead and not m.has(_TAUNT):
                    m.add_buff(BuffEnchant(atk=n, health=2 * n))
        game.events.register(Listener(event="turn_end", owner=source,
                                      callback=on_te))


class R806:
    """After each combat, Discover a non-Golden minion from your last
    opponent's warband. It keeps enchantments."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_ce(g, hero_a=None, hero_b=None, _h=hero, **kw):
            if _h is not hero_a and _h is not hero_b:
                return       # 只有本英雄的战斗结算才触发 Discover
            # "your last opponent's warband" → last_opponent_warband
            # （战前战团快照; 幽灵战记幽灵阵容——RULES §4.8a。旧实现读
            # next_opponent_warband，在配对提前确定的契约下语义已分离）
            board = g.last_opponent_warband(_h)
            if not board:
                return
            cands = [m for m in board
                     if isinstance(m, Minion) and not m.is_golden]
            if not cands:
                return
            opts = g.rng.sample(cands, min(3, len(cands)), label="r806")

            def resolve(m):
                copy = g.create_minion(m.card_id, controller=_h,
                                       golden=False)
                m.copy_buffs_to(copy)
                g.pending_hand_add(_h, copy)

            g.pending_choices.append(PendingChoice(
                _h, opts, "discover_minion", resolve_callback=resolve))
        game.events.register(Listener(event=COMBAT_END, owner=source,
                                      callback=on_ce))


class R810:
    """After you play a minion of a type you don't control, give a
    friendly minion of each type +2/+2.

    Formal spec: card_played 在召唤**之后**广播 → "你控制的其他类型"
    为棋盘排除刚打出者后的类型集（R712 同构）。

    Params: atk=2 health=2（文本字面量——CardDef 无模板参数）"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_played(g, card=None, _h=hero, **kw):
            if card is None or card.controller is not _h \
                    or not isinstance(card, Minion):
                return
            if card.race in (Race.NONE, Race.ALL):
                return
            others = [m for m in _h.board
                      if not m.dead and m is not card
                      and m.race not in (Race.NONE, Race.ALL)]
            types = {m.race for m in others}
            if card.race in types:
                return       # 已控制该类型
            for r in types:
                cands = [m for m in others if m.race == r]
                if cands:
                    t = g.rng.choice(cands, label="r810")
                    t.add_buff(BuffEnchant(atk=2, health=2))
        game.events.register(Listener(event="card_played", owner=source,
                                      callback=on_played))


class R811:
    """Minions in the Tavern cost 2 Gold."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        hero.set(GameTag.TAVERN_MINION_COST_OVERRIDE, 2)


class R815:
    """Your Blood Gems give an extra +1/+1. SoT: get two Blood Gems.

    Formal spec: on_bind 经 ImproveBloodGems 永久递增
    BLOOD_GEM_BONUS_ATK/HEALTH; 每回合开始 GetBloodGems 入手 2 颗。

    Params: atk=1 health=1（文本 "an extra +1/+1" 字面量——CardDef 无
    模板参数）
    """
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        game.run_actions(ImproveBloodGems(hero, atk=1, health=1))

        def on_ts(g, hero=None, turn=None, _h=hero, **kw):
            if hero is not _h:
                return
            g.run_actions(GetBloodGems(_h, 2))
        game.events.register(Listener(event=TURN_START, owner=source,
                                      callback=on_ts))


class R502t:
    """Whenever you buy a Tavern spell that costs (3) or more, get an
    extra copy of it."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_sb(g, spell=None, hero=None, _h=hero, **kw):
            if spell is None or spell.controller is not _h:
                return
            d = g.db.get(spell.card_id)
            if d is None or (d.cost or 0) < 3:
                return
            g.pending_hand_add(_h, _plain_copy(g, spell))
        game.events.register(Listener(event="spell_bought", owner=source,
                                      callback=on_sb))


class R506:
    """The first time you buy a card each turn, get an extra copy of
    it."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        hero._r506_used = False

        def on_bought(g, minion=None, spell=None, hero=None, _h=hero, **kw):
            ent = minion if minion is not None else spell
            if ent is None or ent.controller is not _h:
                return
            if getattr(_h, "_r506_used", False):
                return
            _h._r506_used = True
            g.pending_hand_add(_h, _plain_copy(g, ent))

        def on_ts(g, hero=None, turn=None, _h=hero, **kw):
            if hero is _h:
                _h._r506_used = False
        game.events.register(Listener(event=MINION_BOUGHT, owner=source,
                                      callback=on_bought))
        game.events.register(Listener(event="spell_bought", owner=source,
                                      callback=on_bought))
        game.events.register(Listener(event=TURN_START, owner=source,
                                      callback=on_ts))


class R508:
    """After you Refresh 5 times, make the highest-Tier minion in the
    Tavern Golden.

    Formal spec: 阈值 = CardDef.num(0); 候选排除已金者（不重复金色化）。

    Params: {0}=5"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        d = game.db.get(source.card_id)
        need = d.num(0) if d is not None else None
        if need is None:
            return

        def on_ref(g, hero=None, _h=hero, **kw):
            if hero is not _h:
                return
            n = getattr(_h, "_r508_refs", 0) + 1
            _h._r508_refs = n
            if n >= need:
                _h._r508_refs = 0
                t = [m for m in _h.tavern
                     if isinstance(m, Minion) and not m.is_golden]
                if t:
                    best = max(t, key=lambda m: m.tech_level)
                    _goldenize(g, best)
        game.events.register(Listener(event="tavern_refresh",
                                      owner=source, callback=on_ref))


class R514:
    """SoT: cast 5 random Tavern spells.

    Formal spec: 每回合施放 5 个随机酒馆法术（池来源 + 占池/回池配平）;
    施放前从 scripts.target_candidates（未声明则友方存活棋盘）随机取
    一个合法目标——覆盖声明 needs_target 与未声明但要求目标的脚本;
    完全无候选时按引擎 play_spell 语义落空（未声明 needs_target 的
    定向法术脚本 fail-loud，见下防御分支）。

    Cross-batch gap: BG28_518 Chef's Choice 文本 "Choose a minion" 却未
    声明 needs_target，play_spell 无目标时抛 GameStateError（batch_rally2
    缺陷，非本批范围）。本脚本仅在**无候选**时吞该异常并回滚池记账，
    有目标时一律重新抛出（fail-loud 不掩盖真实错误）。

    Params: count=5（文本字面量——CardDef 无模板参数）"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_ts(g, hero=None, turn=None, _h=hero, **kw):
            if hero is not _h:
                return
            for _ in range(5):
                cid = _random_pool_spell(g, require_script=True)
                if cid is None:
                    break
                if not g.spell_pool.acquire(cid):
                    continue
                s = g.create_spell(cid, controller=_h)
                if s is None or not _h.add_to_hand(s):
                    g.spell_pool.release(cid)
                    continue
                sc = s.scripts
                cand_fn = getattr(sc, "target_candidates", None) \
                    if sc is not None else None
                if cand_fn is not None:
                    cands = list(cand_fn(s, g))
                else:
                    cands = [m for m in _h.board if not m.dead]
                cands = [c for c in cands if not getattr(c, "dead", False)]
                target = (g.rng.choice(cands, label="r514_target")
                          if cands else None)
                try:
                    g.play_spell(_h, s, target=target)
                except GameStateError:
                    if target is not None:
                        raise
                    # 无合法目标 + 未声明 needs_target 的定向脚本
                    if s in _h.hand:
                        _h.hand.remove(s)
                    s.zone = Zone.REMOVED
                    g.spell_pool.release(cid)
        game.events.register(Listener(event=TURN_START, owner=source,
                                      callback=on_ts))


class R515:
    """SoT: get 3 random Tavern spells.

    Params: count=3（文本字面量——CardDef 无模板参数）"""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_ts(g, hero=None, turn=None, _h=hero, **kw):
            if hero is not _h:
                return
            for _ in range(3):
                cid = _random_pool_spell(g)
                if cid is None:
                    break
                if not g.spell_pool.acquire(cid):
                    continue
                s = g.create_spell(cid, controller=_h)
                if s is None:
                    g.spell_pool.release(cid)
                    continue
                g.pending_hand_add(_h, s)
        game.events.register(Listener(event=TURN_START, owner=source,
                                      callback=on_ts))


# ══════════════ BG33 批（Season 13）══════════════

class R003:
    """SoC: left-most minion gains Divine Shield and attacks
    immediately."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_soc(g, hero=None, _h=hero, **kw):
            if hero is not _h:
                return
            alive = [m for m in _h.board if not m.dead]
            if not alive:
                return
            m = alive[0]
            m.set(GameTag.DIVINE_SHIELD, True)
            ac = getattr(g, "_active_combat", None)
            if ac is None:
                return
            a, b = ac
            opp = b if a is _h else a
            from hsrl2.combat import execute_immediate_attack
            target = _random_enemy(g, opp)
            if target is not None:
                execute_immediate_attack(g, m, target)
        game.events.register(Listener(event="start_of_combat",
                                      owner=source, callback=on_soc))


class R010:
    """Unlock Tier 7 this game. At the start of your next turn only,
    upgrade the Tavern.

    Formal spec:
      1. on_bind: `game.max_tavern_tier = 7`（每局 T7 解锁——与异变
         Secrets of Norgannon 同一引擎钩子，**不是**改写 constants）
      2. 下一次本人回合开始（once + condition 锁本英雄）:
         `game.upgrade_tavern_free(hero)`——免费升一级（"upgrade the
         Tavern"）; 只在该回合发生一次
      3. 读取口径: "at the start of your next turn only" = 仅下回合开始
         时升级一次（非"仅下回合可升级"——后者无免费/折扣语义）
    """
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        game.max_tavern_tier = 7

        def on_ts(g, hero=None, turn=None, _h=hero, **kw):
            if hero is not _h:
                return
            g.upgrade_tavern_free(_h)
        game.events.register(Listener(
            event=TURN_START, owner=source, callback=on_ts, once=True,
            condition=lambda hero=None, _h=hero, **kw: hero is _h))


class R012:
    """Get a 5-Gold Coin Pouch. Increase your maximum Gold by 5."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        game.run_actions(GainGold(hero, 5))
        hero.set(GameTag.INCOME_CAP_BONUS,
                 hero.get(GameTag.INCOME_CAP_BONUS, 0) + 5)


class R013:
    """SoT: make the highest-Tier minion in the Tavern Golden."""
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_ts(g, hero=None, turn=None, _h=hero, **kw):
            if hero is not _h:
                return
            t = [m for m in _h.tavern
                 if isinstance(m, Minion) and not m.is_golden]
            if t:
                best = max(t, key=lambda m: m.tech_level)
                _goldenize(g, best)
        game.events.register(Listener(event=TURN_START, owner=source,
                                      callback=on_ts))


class R014:
    """SoT next turn: gain 4 Gold and choose a Lesser Trinket to buy.

    Formal spec: "your next turn" = 一次性——once 监听 + condition 锁本
    英雄（释放 TURN_START 先于本英雄触发的其它英雄不会消耗该次）。
    """
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_ts(g, hero=None, turn=None, _h=hero, **kw):
            if hero is not _h:
                return
            g.run_actions(GainGold(_h, 4))
            g._offer_trinkets(_h, "lesser")
        game.events.register(Listener(
            event=TURN_START, owner=source, callback=on_ts, once=True,
            condition=lambda hero=None, _h=hero, **kw: hero is _h))


class R015:
    """SoT next turn: gain 4 Gold and choose a Greater Trinket to buy.

    Formal spec: 同 R014——once + condition（Greater 档位）。
    """
    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero")
        if hero is None:
            return
        def on_ts(g, hero=None, turn=None, _h=hero, **kw):
            if hero is not _h:
                return
            g.run_actions(GainGold(_h, 4))
            g._offer_trinkets(_h, "greater")
        game.events.register(Listener(
            event=TURN_START, owner=source, callback=on_ts, once=True,
            condition=lambda hero=None, _h=hero, **kw: hero is _h))


# ── 工具 ──

def _random_pool_spell(game, *, require_script: bool = False):
    """随机酒馆法术 card_id（db.pool_spells ∩ spell_pool 有剩余副本）。

    require_script=True 时还要求已注册效果脚本（"cast" 路径——无脚本
    法术施放为 no-op，不进随机施放池）。无候选返回 None（效果落空）。
    经 `Game.tavern_spell_candidates()` 施加**存在档白名单**（异变
    101/102 非存在档法术不可达）。
    """
    from hsrl2.scripts import REGISTRY
    # 统一入口: 全池 + 存在档白名单（异变 101/102 非存在档不可达）
    cands = [cid for cid in game.tavern_spell_candidates()
             if not require_script or cid in REGISTRY]
    if not cands:
        return None
    return game.rng.choice(cands, label="random_pool_spell")


def _random_enemy(game, opponent):
    living = [m for m in opponent.living_minions()
              if not m.has(GameTag.STEALTH)]
    if not living:
        return None
    taunts = [m for m in living if m.has(_TAUNT)]
    pool = taunts if taunts else living
    return game.rng.choice(pool, label="reward_target")


def _goldenize(game, m):
    """随从金色化（Sanders 同构: 保 buff/关键词; 非三连金标记）。

    **卡身份必须同时更新 `Entity.card_id`/`name` 与 CARD_ID tag**
    （2026-09-02 对抗审查 D1 MAJOR）: `Entity.card_id` 是独立属性，
    脚本读 `game.db.get(source.card_id).num()` 取模板参数; 只改 tag 会让
    金色实体继续用**基础卡**参数（实测 BG26_524 金色化后
    HEALTH_REFRESHES_LEFT 仍 =2 而非金卡的 4; 同族 BG33_891/BG36_508）。
    引擎 `create_minion(golden=True)` 两处一致，此处对齐。
    """
    if m.is_golden or m.card_id is None:
        return
    d = game.db.get(m.card_id)
    if d is None:
        return
    gd = game.db.golden_version(d)
    if gd is None:
        return
    base_id = m.card_id
    m.card_id = gd.id          # 实体身份（脚本 num() 读取点）
    m.set(GameTag.NAME, gd.name)
    m.set(GameTag.CARD_ID, gd.id)
    m.set(GameTag.GOLDEN, True)
    m.set(GameTag.TRIPLE_BASE_CARD_ID, base_id)
    m.set(GameTag.GILDED_NOT_TRIPLED, True)
    from hsrl2.scripts import REGISTRY
    m.scripts = REGISTRY.get(gd.id)
    # 金色属性并集（原实体 buff 保留; 基础值走金卡 def）
    m.set(GameTag.BASE_ATK, gd.atk)
    m.set(GameTag.BASE_HEALTH, gd.health)
    m.set(GameTag.HEALTH, max(m.health, gd.health))


def register() -> list[str]:
    """注册任务奖励 41 张。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG24_Reward_107", R107), ("BG24_Reward_109", R109),
        ("BG24_Reward_111", R111), ("BG24_Reward_115", R115),
        ("BG24_Reward_123", R123), ("BG24_Reward_125", R125),
        ("BG24_Reward_128", R128), ("BG24_Reward_129", R129),
        ("BG24_Reward_131", R131), ("BG24_Reward_136", R136),
        ("BG24_Reward_138", R138), ("BG24_Reward_305", R305),
        ("BG24_Reward_308", R308), ("BG24_Reward_309", R309),
        ("BG24_Reward_311", R311), ("BG24_Reward_312", R312),
        ("BG24_Reward_321", R321), ("BG24_Reward_321t", R321t),
        ("BG24_Reward_331", R331), ("BG24_Reward_350", R350),
        ("BG24_Reward_361", R361), ("BG24_Reward_363", R363),
        ("BG24_Reward_364", R364), ("BG24_Reward_708", R708),
        ("BG24_Reward_712", R712),
        ("BG27_Reward_503", R503), ("BG27_Reward_804", R804),
        ("BG27_Reward_806", R806), ("BG27_Reward_810", R810),
        ("BG27_Reward_811", R811), ("BG27_Reward_815", R815),
        ("BG28_Reward_502", R502t), ("BG28_Reward_506", R506),
        ("BG28_Reward_508", R508), ("BG28_Reward_514", R514),
        ("BG28_Reward_515", R515),
        ("BG33_Reward_003", R003), ("BG33_Reward_010", R010),
        ("BG33_Reward_012", R012),
        ("BG33_Reward_013", R013), ("BG33_Reward_014", R014),
        ("BG33_Reward_015", R015),
    ]
    registered = []
    for rid, cls in pairs:
        reg(rid, cls)
        registered.append(rid)
    return registered
