"""批次 anomalies — 异变系统第一批（作业单 2026-09-01，41 注册项）。

引擎三系统（主线本轮）: Game(anomaly=...) → start_game 应用 REGISTRY
[anomaly_id].on_bind(game)。异变脚本签名 = on_bind(game)（全局监听/
状态覆写，与英雄/随从脚本的 (source, game, ctx) 不同）。

引擎全局覆写（game.py/pools.py/hero.py）:
  _damage_cap_override / hero._damage_flat_cap / _tavern_race /
  _tavern_offer_override / _tavern_spell_extra / _tavern_golden /
  _notype_is_all / _minion_cost_is_tier / _block_manual_refresh /
  _upgrade_blocked / _extra_bc_dr / TRIPLE_NO_REWARD tag /
  max_tavern_tier（每局 T7）/ _tavern_min_tier（游戏级+英雄级）/
  _refresh_on_buy / refresh_tavern(races=)

2026-09-01 主线维修（接线审计 tools/audit_script_wiring.py 首跑命中）:
  - BG31_Anomaly_111 Elven Elite: `_tavern_offer_tier_only` 无引擎读取
    → refresh_tavern 接线（tier-only 抽取）
  - BG36_Anomaly_002 Dark Gifts!: available/cost/hero_power 是英雄技能
    协议，异变只分发 on_bind → 整类空转; 该效果实为 S14 基线机制
    （官方 36.2 公告），改为文档化 no-op
  - BG27_Anomaly_504 Secrets of Norgannon: 改写模块级
    constants.TAVERN_MAX_TIER 跨局污染 → 改 game.max_tavern_tier
  - BG27_Anomaly_718 Overseer's Orb: 算了 most-common race 却没传给
    刷新 → refresh_tavern(races=)
  - BG27_Anomaly_726 Blessed or Blighted: 文本是右-most 获 **Reborn**，
    旧实现给 +20/+20 → 修正
  - BG27_Anomaly_715 Gladiator's Spoils: 非胜应得"低一 tier"随机随从，
    旧实现同 tier 且漏 draw → 修正
  - BG27_Anomaly_104t10 Oops, All Pirates!: Cap'n Hoggarr 卡 id 应为
    BGS_072（旧 BG20_203 = Prophet of the Boar）; 池注入需支持池外卡
  - BG31_Anomaly_120 Scout's Honor: Patient Scout 应为 BG24_715
    （旧 BG25_001 = Risen Rider）
  - BG27_Anomaly_000/006/501 开局金币监听条件写反（`hero is not h`）
  - BG27_Anomaly_900 Golganneth's Tempest: 缺"买牌后自动刷新"
  - BG27_Anomaly_801 The Golden Arena: 酒馆金卡属性未翻倍
  - BG27_Anomaly_714 Everything's on Fire!: 回血上限硬编码 40（应为 30）
  - BG31_Anomaly_112 Incubation Mutation: 无类型→全类型仅在酒馆生效
    → 移到 create_minion（全局）

DEFERRED（撤注册，SOP §6b 第 4 步）:
  - BG27_Anomaly_556 Valuation Inflation: "Tavern Tier 1 does not exist"
    两种读法均无信源，且 31.6.0 已移出异变池 → 不猜

注册 41 张（其余 67 张未注册，台账见 AGENTS.md 与各卡 wiki Availability）。
"""

from __future__ import annotations

import hsrl2.constants as C
from hsrl2.actions import (
    Discover, GainGold, GainKeyword, GetRandomMinion,
)
from hsrl2.entity import Buff as BuffEnchant
from hsrl2.events import (
    COMBAT_END, DEATH, HERO_ELIMINATED, MINION_BOUGHT, MINION_SOLD,
    TURN_START, Listener,
)
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

# 种族白名单（Only X taverns）——与 MinionPool._race_ok 口径一致
_RACE_BY_ID = {
    "BG27_Anomaly_104t": Race.BEAST,
    "BG27_Anomaly_104t10": Race.PIRATE,
    "BG27_Anomaly_104t2": Race.DEMON,
    "BG27_Anomaly_104t3": Race.DRAGON,
    "BG27_Anomaly_104t4": Race.ELEMENTAL,
    "BG27_Anomaly_104t5": Race.MECH,
    "BG27_Anomaly_104t6": Race.MURLOC,
    "BG27_Anomaly_104t7": Race.NAGA,
    "BG27_Anomaly_104t8": Race.QUILBOAR,
    "BG27_Anomaly_104t9": Race.UNDEAD,
}


def _start_gold(game, hero, amount, turn=1):
    """开局金币覆写: 第 `turn` 回合开始时把该英雄金币设为 amount。

    监听器 owner=hero（英雄淘汰即注销）; 事件在第 1 回合 `_begin_recruit_for`
    基础收入重置**之后**广播，故覆写生效（Money Match / Curse of Aggramar /
    Temperance of Aman'Thul）。
    """
    def on_ts(g, hero=None, turn=None, **kw):
        if hero is h and turn == turn_at:
            hero.gold = amount
    h = hero
    turn_at = turn
    game.events.register(Listener(event=TURN_START, owner=hero,
                                  callback=on_ts))


class MoneyMatchAnomaly:
    """Start at 10 Gold."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            _start_gold(game, h, 10)


class TierStartAnomaly:
    """Start at Tavern Tier 2."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            h.set(GameTag.TAVERN_TIER, 2)
            h.set(GameTag.UPGRADE_COST, 8)   # 升 T3 基准（RULES §3.1）


class UnspentCarryOverAnomaly:
    """Unspent Gold carries over. If you saved at least 5, gain 1 extra."""
    @staticmethod
    def on_bind(game):
        # 闭包捕获必须用默认参数绑定（`_h=h`）——`for h in heroes` 的
        # 闭包单元在循环结束后指向**最后一个**英雄，直接引用 h 会让
        # 所有监听器都作用于最后一位英雄（2026-09-01 修复）
        for h in game.heroes:
            h._carry_gold = 0

            def on_te(g, turn=None, _h=h, **kw):
                saved = _h.gold
                extra = 1 if saved >= 5 else 0
                _h._carry_gold = saved + extra
                _h.gold = 0

            def on_ts(g, hero=None, turn=None, _h=h, **kw):
                if hero is not _h:
                    return
                hero.gold += getattr(_h, "_carry_gold", 0)
                _h._carry_gold = 0
            game.events.register(Listener(event="turn_end", owner=h,
                                          callback=on_te))
            game.events.register(Listener(event=TURN_START, owner=h,
                                          callback=on_ts))


class AutoUpgradeAnomaly:
    """You cannot upgrade the Tavern with Gold. It upgrades itself every
    2 turns."""
    @staticmethod
    def on_bind(game):
        game._upgrade_blocked = True
        for h in game.heroes:
            def on_ts(g, hero=None, turn=None, _h=h, **kw):
                if hero is not _h:
                    return
                if turn >= 2 and turn % 2 == 0 and hero.tavern_tier < 6:
                    g.upgrade_tavern_free(hero)
            game.events.register(Listener(event=TURN_START, owner=h,
                                          callback=on_ts))


class OneDamageAtATimeAnomaly:
    """Start at 5 Health and 5 Gold. Your hero can only take 1 damage
    at a time."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            h.health = 5
            h._damage_flat_cap = 1
            _start_gold(game, h, 5)


class Tier3StartAnomaly:
    """Start at Tavern Tier 3 with 9 Gold. All cards in your first shop
    are Tier 3."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            h.set(GameTag.TAVERN_TIER, 3)
            h.set(GameTag.UPGRADE_COST, 9)   # 升 T4 基准
            _start_gold(game, h, 9)
        # 首个商店全 T3: 每英雄 hero 级 `_tavern_min_tier=3`，其**首次**
        # tavern_refresh 后清除（condition 过滤保证 once 只对该英雄消费）
        for h in game.heroes:
            h._tavern_min_tier = 3

            def clear(g, hero=None, _h=h, **kw):
                _h._tavern_min_tier = 1
            game.events.register(Listener(
                event="tavern_refresh", owner=h, callback=clear,
                condition=lambda hero=None, _h=h, **kw: hero is _h,
                once=True))


class SetHealth12Anomaly:
    """At the start of your turn, set your hero's Health to 12."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_ts(g, hero=None, turn=None, _h=h, **kw):
                if hero is _h:
                    hero.health = 12
            game.events.register(Listener(event=TURN_START, owner=h,
                                          callback=on_ts))


class Tier7ExistsAnomaly:
    """Tavern Tier 7 exists. Start with 10 extra Armor."""
    @staticmethod
    def on_bind(game):
        # 每局上限（**禁止**改写 constants.TAVERN_MAX_TIER——模块级
        # 单例会跨局污染，2026-09-01 接线审计 W3 命中）
        game.max_tavern_tier = 7
        for h in game.heroes:
            h.armor += 10


class MinionsCostTierAnomaly:
    """Tavern Tier 1 does not exist. Minions cost Gold equal to their
    Tier.

    Status: DEFERRED — 语义查无证据（SOP §6b 第 4 步撤注册）。
    "Tavern Tier 1 does not exist" 有两种读法: (A) 抽取下限 tier 2
    （则 tier 1 玩家商店为空，显然不符）; (B) 玩家开局即 tier 2（文本
    未述）。wiki 页面无 Notes，且该异变已于 31.6.0 (2025-02-18) 移出
    异变池（wiki "Availability: currently not available"）——不猜。
    "minions cost Gold equal to their Tier" 部分无歧义，但单独实现即
    第三态近似，故整卡 DEFERRED。
    """
    @staticmethod
    def on_bind(game):
        return None   # DEFERRED（未注册）


class MinionsCost2NoRefreshAnomaly:
    """Minions cost 2 Gold. You cannot Refresh the Tavern. It Refreshes
    itself after you buy a card."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            h.set(GameTag.TAVERN_MINION_COST_OVERRIDE, 2)
        game._block_manual_refresh = True
        game._refresh_on_buy = True


class FirstBuyFreeAnomaly:
    """The first minion you buy each turn is free."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_ts(g, hero=None, turn=None, _h=h, **kw):
                if hero is _h:
                    # 多来源独立配额（RULES §7.4.4，2026-09-02 主线原语）
                    g.set_free_minion_buys(
                        _h, 1, source="BG27_Anomaly_303")
            game.events.register(Listener(event=TURN_START, owner=h,
                                          callback=on_ts))


class OnlyRaceTavernAnomaly:
    """Only {race} are in the Tavern.（104t 族: 池种族白名单）"""
    @staticmethod
    def on_bind(game):
        race = _RACE_BY_ID.get(game.anomaly or "", Race.NONE)
        game._tavern_race = race
        if race == Race.PIRATE:
            # "Cap'n Hoggarr is in the minion pool"——BGS_072 已退出
            # 36.2 常驻池定义，按文本注入（数据核实 2026-09-01）
            game.minion_pool.ensure_available("BGS_072")


class AllTypesTavernAnomaly:
    """All minion types are in the Tavern. It always has 7 cards."""
    @staticmethod
    def on_bind(game):
        game._tavern_offer_override = 7


class SevenCardsAnomaly:
    """The Tavern always has 7 cards."""
    @staticmethod
    def on_bind(game):
        game._tavern_offer_override = 7


class AllGoldenNoRewardsAnomaly:
    """ALL minions are Golden, but you do not get Triple Rewards."""
    @staticmethod
    def on_bind(game):
        game._tavern_golden = True
        for h in game.heroes:
            h.set(GameTag.TRIPLE_NO_REWARD, True)


class ExtraBCDRAnomaly:
    """Your Battlecries and Deathrattles trigger an extra time."""
    @staticmethod
    def on_bind(game):
        game._extra_bc_dr = True


class NoTypeIsAllAnomaly:
    """Minions with no type have all minion types."""
    @staticmethod
    def on_bind(game):
        game._notype_is_all = True


class ExtraTavernSpellAnomaly:
    """The Tavern offers an extra Tavern spell whenever it is Refreshed."""
    @staticmethod
    def on_bind(game):
        game._tavern_spell_extra = 1


class OnlyYourTierAnomaly:
    """The Tavern only offers cards of your Tier."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_ts(g, hero=None, turn=None, _h=h, **kw):
                if hero is _h:
                    hero._tavern_offer_tier_only = True
            game.events.register(Listener(event=TURN_START, owner=h,
                                          callback=on_ts))


class StartDamage25Anomaly:
    """At the start of the game, take 25 damage. After another hero
    dies, regain 5 Health."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            h.take_damage(25)

        def on_elim(g, hero=None, **kw):
            if hero is None:
                return
            for h in game.heroes:
                if h is not hero and h.is_alive:
                    # "regain 5 Health"——封顶在英雄基础生命（30;
                    # 旧实现硬编码 40 = 双打生命，Solo 越界）
                    h.health = min(h.health + 5, C.HERO_BASE_HEALTH)
        game.events.register(Listener(event=HERO_ELIMINATED,
                                      owner=None, callback=on_elim))


class SocLeftRightAnomaly:
    """Start of Combat: Give your left-most minion Divine Shield and
    your right-most minion Reborn."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_soc(g, hero=None, _h=h, **kw):
                if hero is not _h:
                    return
                board = [m for m in _h.board if not m.dead]
                if not board:
                    return
                g.run_actions(GainKeyword(board[0], GameTag.DIVINE_SHIELD))
                # 单个随从同时是最左与最右 → 两个关键词都给
                g.run_actions(GainKeyword(board[-1], GameTag.REBORN))
            game.events.register(Listener(event="start_of_combat",
                                          owner=h, callback=on_soc))


class SocHighestHealthCopyAnomaly:
    """Start of Combat: Summon a copy of your highest-Health minion."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_soc(g, hero=None, _h=h, **kw):
                if hero is not _h:
                    return
                alive = [m for m in _h.board if not m.dead]
                if not alive:
                    return
                best = max(alive, key=lambda m: m.health)
                if _h.board_full():
                    return
                copy = g.create_minion(best.card_id, controller=_h,
                                       golden=best.is_golden)
                best.copy_buffs_to(copy)
                g.summon(_h, copy)
            game.events.register(Listener(event="start_of_combat",
                                          owner=h, callback=on_soc))


class SellGiveStatsAnomaly:
    """After you sell a minion, give its stats to a minion in the
    Tavern."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_sold(g, minion=None, _h=h, **kw):
                if minion is None or minion.controller is not _h:
                    return
                tavern = [m for m in _h.tavern if isinstance(m, Minion)]
                if not tavern:
                    return
                t = g.rng.choice(tavern, label="sell_stats_target")
                t.add_buff(BuffEnchant(atk=minion.atk, health=minion.health,
                                       source_id="BG27_Anomaly_561"))
            game.events.register(Listener(event=MINION_SOLD, owner=h,
                                          callback=on_sold))


class FirstBuyExtraCopyAnomaly:
    """The first time you buy a card each turn, get an extra copy of it."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_bought(g, minion=None, spell=None, _h=h, **kw):
                ent = minion or spell
                if ent is None or ent.controller is not _h:
                    return
                if getattr(_h, "_first_buy_used", False):
                    return
                _h._first_buy_used = True
                g.pending_hand_add(_h, _plain_copy(g, ent))

            def on_ts(g, hero=None, turn=None, _h=h, **kw):
                if hero is _h:
                    _h._first_buy_used = False
            game.events.register(Listener(event=MINION_BOUGHT, owner=h,
                                          callback=on_bought))
            game.events.register(Listener(event="spell_bought", owner=h,
                                          callback=on_bought))
            game.events.register(Listener(event=TURN_START, owner=h,
                                          callback=on_ts))


class WinDiscoverAnomaly:
    """After you win a combat, Discover a minion of your Tier.
    Otherwise, get a random one of a Tier lower.

    Params: 无模板参数（Discover 选项数恒为引擎默认 3）"""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_end(g, hero_a=None, hero_b=None, _h=h, **kw):
                r = getattr(_h, "_last_combat_result", None)
                tier = _h.tavern_tier
                if r == "win":
                    # `Discover.count` 是选项数（恒 3），不是发现次数
                    g.run_actions(Discover(_h, min_tier=tier,
                                           max_tier=tier,
                                           kind="discover_minion"))
                elif r is not None:      # 非胜（败/平）= "Otherwise"
                    lower = max(1, tier - 1)
                    g.run_actions(GetRandomMinion(_h, min_tier=lower,
                                                  max_tier=lower))
            game.events.register(Listener(event=COMBAT_END, owner=h,
                                          callback=on_end))


class UpgradeRefreshCommonTypeAnomaly:
    """After you upgrade the Tavern, Refresh it with minions of your
    most common type."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_up(g, hero=None, tier=None, _h=h, **kw):
                if hero is not _h:
                    return
                counts = {}
                for m in _h.board:
                    if not m.dead and m.race not in (Race.NONE, Race.ALL):
                        counts[m.race] = counts.get(m.race, 0) + 1
                if not counts:
                    return
                top = max(counts, key=counts.get)
                # 必须把 most-common race 传入刷新（旧实现丢掉 top →
                # 与文本不符，2026-09-01 修复）
                g.refresh_tavern(_h, free=True, races={top, Race.ALL})
            game.events.register(Listener(event="tavern_upgraded",
                                          owner=h, callback=on_up))


class Every2TurnsLeftCopyAnomaly:
    """At the end of every 2 turns, get a plain copy of your left-most
    minion."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_te(g, turn=None, _h=h, **kw):
                if turn % 2 != 0:
                    return
                alive = [m for m in _h.board if not m.dead]
                if not alive:
                    return
                g.pending_hand_add(_h, _plain_copy(g, alive[0]))
            game.events.register(Listener(event="turn_end", owner=h,
                                          callback=on_te))


class Refresh2GoldAnomaly:
    """After you Refresh two times, gain 1 Gold next turn."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_ts(g, hero=None, turn=None, _h=h, **kw):
                if hero is _h:
                    _h._refresh_count = 0

            def on_ref(g, hero=None, _h=h, **kw):
                if hero is _h:
                    n = getattr(_h, "_refresh_count", 0) + 1
                    _h._refresh_count = n
                    if n % 2 == 0:
                        g.defer_until_next_turn(_h, GainGold(_h, 1))
            game.events.register(Listener(event=TURN_START, owner=h,
                                          callback=on_ts))
            game.events.register(Listener(event="tavern_refresh", owner=h,
                                          callback=on_ref))


class GoldenPatientScoutAnomaly:
    """Start with a Golden Patient Scout in play."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            # Patient Scout = BG24_715（数据核实 2026-09-01；旧值
            # BG25_001 是 Risen Rider——凭记忆硬编码的漂移）
            m = game.create_minion("BG24_715", controller=h, golden=True)
            if m is not None and not h.board_full():
                game.summon(h, m)


class MostCommonTypeAnomaly:
    """At the start of each turn, get a random minion of your most
    common type. (Unlocks on Turn 2.)"""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_ts(g, hero=None, turn=None, _h=h, **kw):
                if hero is not _h or turn < 2:
                    return
                counts = {}
                for m in _h.board:
                    if not m.dead and m.race not in (Race.NONE, Race.ALL):
                        counts[m.race] = counts.get(m.race, 0) + 1
                if not counts:
                    return
                top = max(counts, key=counts.get)
                g.run_actions(GetRandomMinion(_h, race=top))
            game.events.register(Listener(event=TURN_START, owner=h,
                                          callback=on_ts))


class ThreeTier2StartAnomaly:
    """Start with 3 different Tier 2 minions in hand."""
    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            got = set()
            while len(got) < 3:
                from hsrl2.actions.discover import _pool_candidates
                cands = _pool_candidates(game, None, 2, 2)
                cands = [c for c in cands if c not in got]
                if not cands:
                    break
                cid = game.rng.choice(cands, label="t2_start")
                if game.minion_pool.acquire(cid):
                    got.add(cid)
            for cid in got:
                m = game.create_minion(cid, controller=h)
                if m is not None:
                    game.pending_hand_add(h, m)


class DarkGiftDiscoverAnomaly:
    """Starting Turn 3, you may spend 3 Gold to Discover a minion with
    a Dark Gift. (3 times per game!)"""
    @staticmethod
    def on_bind(game):
        # S14 Dark Gift 是**赛季基线机制**（官方 36.2 公告: "Starting
        # on Turn 3, you can use the Dark Gift button to spend 3 Gold
        # and Discover a minion with a Dark Gift ... up to 3 times per
        # game"）——game.use_dark_gift 已全局限定 turn≥3 / 3 金 / 每局
        # 3 次，故选中该异变无叠加效果（等价于基线）。
        # 2026-09-01 接线审计: 旧实现定义 available/cost/hero_power
        # （英雄技能协议）但异变只分发 on_bind → 整类空转，已移除。
        return None


def _plain_copy(game, ent):
    """不占池副本（Rafaam 先例）。"""
    if isinstance(ent, Minion):
        m = game.create_minion(ent.card_id, controller=ent.controller,
                               golden=ent.is_golden)
        ent.copy_buffs_to(m)
        return m
    s = game.create_spell(ent.card_id, controller=ent.controller)
    return s


def register() -> list[str]:
    """注册异变 41 张（Valuation Inflation DEFERRED 未注册）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG27_Anomaly_000", MoneyMatchAnomaly),
        ("BG27_Anomaly_001", TierStartAnomaly),
        ("BG27_Anomaly_002", UnspentCarryOverAnomaly),
        ("BG27_Anomaly_005", AutoUpgradeAnomaly),
        ("BG27_Anomaly_006", OneDamageAtATimeAnomaly),
        ("BG27_Anomaly_501", Tier3StartAnomaly),
        ("BG27_Anomaly_502", SetHealth12Anomaly),
        ("BG27_Anomaly_504", Tier7ExistsAnomaly),
        # BG27_Anomaly_556 Valuation Inflation — DEFERRED（语义查无证据,
        # 且 31.6.0 已移出异变池; 见类 docstring）
        ("BG27_Anomaly_900", MinionsCost2NoRefreshAnomaly),
        ("BG27_Anomaly_303", FirstBuyFreeAnomaly),
        ("BG27_Anomaly_104t", OnlyRaceTavernAnomaly),
        ("BG27_Anomaly_104t10", OnlyRaceTavernAnomaly),
        ("BG27_Anomaly_104t2", OnlyRaceTavernAnomaly),
        ("BG27_Anomaly_104t3", OnlyRaceTavernAnomaly),
        ("BG27_Anomaly_104t4", OnlyRaceTavernAnomaly),
        ("BG27_Anomaly_104t5", OnlyRaceTavernAnomaly),
        ("BG27_Anomaly_104t6", OnlyRaceTavernAnomaly),
        ("BG27_Anomaly_104t7", OnlyRaceTavernAnomaly),
        ("BG27_Anomaly_104t8", OnlyRaceTavernAnomaly),
        ("BG27_Anomaly_104t9", OnlyRaceTavernAnomaly),
        ("BG27_Anomaly_103", AllTypesTavernAnomaly),
        ("BG27_Anomaly_750", SevenCardsAnomaly),
        ("BG27_Anomaly_801", AllGoldenNoRewardsAnomaly),
        ("BG27_Anomaly_802", ExtraBCDRAnomaly),
        ("BG31_Anomaly_112", NoTypeIsAllAnomaly),
        ("BG31_Anomaly_101", ExtraTavernSpellAnomaly),
        ("BG31_Anomaly_111", OnlyYourTierAnomaly),
        ("BG27_Anomaly_714", StartDamage25Anomaly),
        ("BG27_Anomaly_726", SocLeftRightAnomaly),
        ("BG27_Anomaly_560", SocHighestHealthCopyAnomaly),
        ("BG27_Anomaly_561", SellGiveStatsAnomaly),
        ("BG27_Anomaly_711", FirstBuyExtraCopyAnomaly),
        ("BG27_Anomaly_715", WinDiscoverAnomaly),
        ("BG27_Anomaly_718", UpgradeRefreshCommonTypeAnomaly),
        ("BG31_Anomaly_114", Every2TurnsLeftCopyAnomaly),
        ("BG31_Anomaly_116", Refresh2GoldAnomaly),
        ("BG31_Anomaly_120", GoldenPatientScoutAnomaly),
        ("BG31_Anomaly_126", MostCommonTypeAnomaly),
        ("BG31_Anomaly_127", ThreeTier2StartAnomaly),
        ("BG36_Anomaly_002", DarkGiftDiscoverAnomaly),
    ]
    registered = []
    for aid, cls in pairs:
        reg(aid, cls)
        registered.append(aid)
    return registered
