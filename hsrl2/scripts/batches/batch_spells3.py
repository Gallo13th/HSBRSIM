"""批次 spells3 — 13 张池法术（作业单 2026-08-21）。

实现状态总览（详见各类 docstring）:
  OK:           BG28_882 Contracted Corpse / BG28_884 Overconfidence /
                BG28_886 Staff of Enrichment / BG28_888 Misplaced Tea Set /
                BG28_897 Tavern Dish Banana / BG28_966 Them Apples /
                BG28_GIL_836 Hired Headhunter / BG30_804 Robust Evolution /
                BG31_819 Temperature Shift / BG31_880 Alliance Flag
  OUT_OF_SCOPE: BG31_242 Bargain Bundle / BG31_243 Portal in a Fountain /
                BG31_244 Portal in a Crystal —— wiki 逐卡核实均为
                "available in Duos games **only**"（Pass = Duos 传递机制、
                "Your teammate" = Duos 队友）; AGENTS.md: Duos 一律
                OUT_OF_SCOPE → 不实现不注册。数据缺口: 生成器 v2 将
                Duos-only 池法术混入 Solo SpellPool（报告主线）。

金色: 本数据基线池法术无独立金色卡实体（batch_spells1 同批核实，
      bg_cards.json 无 *_G/TB_BaconUps 条目）→ 仅注册基础 id。

池法术 buff 纪律: "Give a minion +X/+Y" 一律经 racefx.tavern_spell_buff
（TAVERN_SPELL_EXTRA_* 联动）; 酒馆全体 buff（Staff/Them Apples）按
batch_battlecry/batch_deathrattle 的 TavernBuff 双件先例，增幅值在施放时
快照（依据 2026-08-23 查证: wiki.gg/wiki/Battlegrounds/Staff_of_
Enrichment 无 Notes（全文核对，文本史 33.6 "have"→34.2 "give"）;
TavernBuff 持久面为不可变附魔记录（引擎结构），施放后 extra 再增长
是否回灌未公布——按快照，边角上报主线）。

引擎缺口（见作业返回清单）:
  1. run_ghost_combat 不 fire "combat_end"（game.py:1157）——
     Overconfidence 的 "next combat" 在奇数人幽灵战时不结算
  2. play_spell 无 Choose One 协议（仅 play_minion 有）——Alliance Flag
     经手动 PendingChoice(kind="choose_one") 实现（引擎通用件，可行）
  3. SpellPool 含 Duos-only 卡（BG31_242/243/244）——Solo 模拟会错误
     供给; 需生成器按可用性标记过滤（数据侧）
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2 import entity
from hsrl2.actions import Discover, GainGold, ScheduleNextTurn, Transform
from hsrl2.actions.discover import _pool_candidates
from hsrl2.actions.racefx import tavern_spell_buff
from hsrl2.actions.tavern_buff import ApplyTavernBuff, BuffCurrentTavern, \
    TavernBuff
from hsrl2.events import COMBAT_END, Listener
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# "a friendly minion of each type" 的种族全集 = 10 个标准种族
# （batch_rally.ALL_BG_RACES 同源——The Last One Standing 同款文本，
# 2026-08-23 查证统一口径，见 MisplacedTeaSetScript docstring）
_ALL_STANDARD_RACES = (
    Race.UNDEAD, Race.MURLOC, Race.DEMON, Race.MECH, Race.ELEMENTAL,
    Race.BEAST, Race.PIRATE, Race.DRAGON, Race.QUILBOAR, Race.NAGA,
)

# Snow Baller: 无 evolution 数据链（BG31_819.evolution_card_id 仅指向
# Fire Baller 116736）→ id 常量（Papa Mrrglton / Water Droplet 先例;
# bg_cards.json 核实 BG31_818 "Snow Baller" 池随从）
_SNOW_BALLER_ID = "BG31_818"


def _spell_target(ctx):
    """on_play 目标解析（play_spell 协议: ctx={"target": ...}）。

    None（定向法术无候选落空路径）→ 效果落空返回 None，禁止随机近似。
    """
    return ctx.get("target") if ctx else None


def _kw_candidates(game: "Game", keyword: str) -> list[str]:
    """池内含指定关键词（deathrattle/battlecry）的池随从 card_id。

    过滤口径与 _pool_candidates 一致（剩余量 / active_races），
    RULES §6.18 "池中没有的随从不会出现在发现选项中"。
    """
    return [cid for cid in _pool_candidates(game)
            if keyword in game.db.get(cid).keywords]


# ══════════════════ BG28_882 Contracted Corpse ══════════════════


class ContractedCorpseScript:
    """
    Natural language: <b>Discover</b> a <b>Deathrattle</b> minion.

    Formal spec:
      1. on_play: Discover(hero, count=3, candidates=池过滤 keywords 含
         "deathrattle" 的随从)——选项生成已按池剩余量过滤（RULES
         §6.18），选中经 Discover.resolve acquire 占池（RULES §2.3）→
         create_minion → pending_hand_add（满手排队）
      2. 无候选（极端池状态）→ Discover.do 落空（官方池耗尽行为）
      3. 引擎侧: is_pool_spell → 计入 TAVERN_SPELLS_CAST_* 并广播
         tavern_spell_cast

    Test: test_batch_spells3.py — 三选项全带 deathrattle 关键词 /
    选中入手并占池 / 施放计数 +1

    Params: 无数值参数（文本无占位符）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return Discover(hero, count=3,
                        candidates=_kw_candidates(game, "deathrattle"),
                        kind="discover_minion")


# ══════════════════ BG28_884 Overconfidence ══════════════════


class OverconfidenceScript:
    """
    Natural language: If you win your next combat, gain 3 Gold.
    If you tie, gain 1.

    Formal spec:
      1. on_play（法术施放即挂载）: 注册 once Listener(COMBAT_END,
         owner=hero——施放者恒在场，法术实体已 REMOVED 不可作 owner，
         Upper Hand BG28_573 先例）; condition: hero_a/hero_b 之一是
         施放者（他人战斗不消耗 "your next combat"）
      2. 触发（施放者参与的下一场战斗结束; combat_end 在快照恢复后
         广播——game.end_recruit_phase）: result.winner is 施放者 →
         ScheduleNextTurn(GainGold(3)); result.winner is None（平局）→
         ScheduleNextTurn(GainGold(1)); 败 → 无效果。once=True 无论
         胜负均消耗
      3. 金币经延迟执行（game.defer_until_next_turn）: 下一招募阶段
         开始、基础收入覆盖式重置**之后**叠加（Southsea Busker 先例）
         ——combat_end 时点直接加金会被 _begin_recruit_for 的重置清零
      4. 生命周期: once 监听器在战斗内注册/触发由引擎快照恢复管理
         （game.py:1284 _fired 过滤）; 本监听在招募期注册、战后事件
         档触发，无双触发面
      5. 引擎缺口: run_ghost_combat 不 fire combat_end——幽灵战胜/平
         不结算（报告主线）

    Test: test_batch_spells3.py — 胜 +3 / 平 +1 / 败 +0（下回合基础
    收入之上）/ 单次消耗（再胜不重复）

    Params: gold=3 gold_tie=1（文本字面量——CardDef 无模板参数）
    """

    _WIN_GOLD = 3     # "gain 3 Gold"
    _TIE_GOLD = 1     # "gain 1"

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None

        def on_combat_end(g, hero_a=None, hero_b=None, result=None, **kw):
            if result is None:
                return
            if result.winner is None:
                g.run_actions(ScheduleNextTurn(
                    hero, GainGold(hero, OverconfidenceScript._TIE_GOLD)))
            elif result.winner is hero:
                g.run_actions(ScheduleNextTurn(
                    hero, GainGold(hero, OverconfidenceScript._WIN_GOLD)))

        game.events.register(Listener(
            event=COMBAT_END,
            owner=hero,
            once=True,
            condition=lambda hero_a=None, hero_b=None, **kw:
                hero_a is hero or hero_b is hero,
            callback=on_combat_end,
        ))
        return None


# ══════════════════ BG28_886 Staff of Enrichment ══════════════════


class StaffOfEnrichmentScript:
    """
    Natural language: Give minions in the Tavern +{0}/+{1} this game.

    Formal spec:
      1. on_play（双件，Void Pup Trainer / batch_deathrattle
         _tavern_buff_actions 同款）:
         a) 持久面: ApplyTavernBuff(hero, TavernBuff(+{0}/+{1}))——登记
            hero.tavern_buffs，refresh_tavern 对新入馆随从自动应用
            （引擎已接线，game.py:268）
         b) 立即面: BuffCurrentTavern(同一 buff)——当前酒馆全部随从
            （无种族/tier 过滤）立即获得永久增益，购买后随实体带走
      2. "this game" = 持久登记不随回合失效（hero 级数据）; 冻结保留
         项不重复应用（引擎保证）
      3. TAVERN_SPELL_EXTRA_*（"Your Tavern spells give an extra" 家族）
         增幅在施放时快照并入两面数值（即时面+持久面同值）。施放后
         extra 再增长不回灌已登记的持久面——TavernBuff 为不可变附魔
         记录（引擎结构; wiki 卡页无 Notes，2026-08-23 全文核对，
         边角上报主线）。

    Test: test_batch_spells3.py — 当前馆全体 +num(0)/num(1) / 刷新后
    新入馆自动 buff / extra 联动并入两面 / 持久登记存在

    Params: {0}=2 {1}=2（36.2.2 基线）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        atk, health = d.num(0), d.num(1)
        if atk is None or health is None:
            raise GameStateError(
                f"{source.card_id}: missing num(0)/num(1) template params")
        extra_atk = hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0)
        extra_health = hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0)
        tb = TavernBuff(atk=atk + extra_atk, health=health + extra_health,
                        source_id=source.card_id)
        return [ApplyTavernBuff(hero, tb), BuffCurrentTavern(hero, tb)]


# ══════════════════ BG28_888 Misplaced Tea Set ══════════════════


class MisplacedTeaSetScript:
    """
    Natural language: Give a friendly minion of each type +{0}/+{1}.

    目标选择裁定（2026-08-23 查证修正，Evidence 见下）: "a minion of
    each type" = 对**全部 10 个标准种族**各自独立随机选一只该种族
    （或 ALL）友方随从——Amalgam 是每个种族的合格候选且可被多族
    重复选中（每中一次一份 buff）。种族集合与 The Last One Standing
    （batch_rally ALL_BG_RACES，同款 "a friendly minion of each type"
    文本）统一。

    Formal spec:
      1. on_play: 对每个标准种族 r ∈ ALL_BG_RACES（10 种）:
         候选 = 棋盘存活、race ∈ (r, ALL) 的随从; 有候选 → rng.choice
         随机一只 → tavern_spell_buff(num(0), num(1)) 永久 buff
         （TAVERN_SPELL_EXTRA_* 联动）
      2. 同一随从可被多个种族的选取分别命中（Amalgam 场景可叠全部
         10 份——社区实测问句确认每族独立选取口径）;
         空棋盘/无任何候选 → 落空（法术照常消耗）
      3. Wiki tags [Area of effect] + [Minion type-related]（无 [Random]
         标注——选取随机性为社区实测口径，效果面为全体种族）

    Evidence:
      - r/BobsTavern（reddit.com/r/BobsTavern/comments/1vkv7h6）:
        "cast teaset on a board of 6 amalgams and 1 dragon — is it
        possible for the game to pick one of the amalgams as **the
        dragon** to buff..." ——问句预设每族**独立**在合格集中选取
        （Amalgam 对每族合格），同只可被多族命中
      - 官方同款文本族: The Last One Standing 34.6 "Rally: Give a
        friendly minion of each type +12/+12 permanently, twice."
        （blizzard 34.6 patch notes）——本实现两卡口径统一
      - 36.2.2: +2/+2→+4/+4（wiki 36.2.2 patch changes）

    Test: test_batch_spells3.py — 2 鱼 1 机械: 鱼族/机械族各命中（总量
    断言，随机无关）/ Amalgam 单随从: 10 份 buff（每族各一次）/
    施放计数 +1

    Params: {0}=4 {1}=4（36.2.2 基线）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        atk, health = d.num(0), d.num(1)
        if atk is None or health is None:
            raise GameStateError(
                f"{source.card_id}: missing num(0)/num(1) template params")
        living = [m for m in hero.board
                  if isinstance(m, Minion) and not m.dead]
        out = []
        for r in _ALL_STANDARD_RACES:
            cands = [m for m in living
                     if m.race == r or m.race == Race.ALL]
            if not cands:
                continue
            pick = game.rng.choice(cands, label="tea_set_target")
            out.append(tavern_spell_buff(pick, atk, health))
        return out or None


# ══════════════════ BG28_897 Tavern Dish Banana ══════════════════


class TavernDishBananaScript:
    """
    Natural language: Give a minion +{0}/+{1}.

    Formal spec:
      1. needs_target=True（"Give a minion" 定向法术，play_spell 产生
         PendingChoice(kind="spell_target")，默认候选=友方棋盘存活
         随从）; 无候选 → 落空但法术照常消耗（官方语义）
      2. 选定（ctx["target"]）: tavern_spell_buff(num(0), num(1)) 永久
         buff——酒馆法术 buff 统一出口，TAVERN_SPELL_EXTRA_* 联动
         （Azsharan Cutlassier / Felfire Conjurer 家族）

    Test: test_batch_spells3.py — 定向 PendingChoice 流 / +num(0)/
    num(1) / extra 联动 / 空棋盘落空仍消耗

    Params: {0}=2 {1}=2（36.2.2 基线）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        target = _spell_target(ctx)
        if target is None:
            return None
        d = game.db.get(source.card_id)
        atk, health = d.num(0), d.num(1)
        if atk is None or health is None:
            raise GameStateError(
                f"{source.card_id}: missing num(0)/num(1) template params")
        return tavern_spell_buff(target, atk, health)


# ══════════════════ BG28_966 Them Apples ══════════════════


class ThemApplesScript:
    """
    Natural language: Give minions in the Tavern +{0}/+{1}.

    Formal spec:
      1. on_play（一次性，无 "this game"——与 Staff of Enrichment 的
         差异即持久面缺失）: 对当前酒馆全部 Minion 各施加
         tavern_spell_buff(num(0), num(1)) 永久 buff（购买后随实体
         带走; TAVERN_SPELL_EXTRA_* 联动——逐目标经统一出口，非
         TavernBuff 快照路径）
      2. 无持久登记: 刷新入馆的新随从**不**获得增益
      3. 酒馆无法术可被 buff——仅 Minion

    Test: test_batch_spells3.py — 当前馆全体 +num(0)/num(1) / 刷新后
    新入馆不 buff（非持久）

    Params: {0}=1 {1}=2（36.2.2 基线）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        atk, health = d.num(0), d.num(1)
        if atk is None or health is None:
            raise GameStateError(
                f"{source.card_id}: missing num(0)/num(1) template params")
        out = [tavern_spell_buff(m, atk, health)
               for m in hero.tavern if isinstance(m, Minion)]
        return out or None


# ══════════════════ BG28_GIL_836 Hired Headhunter ══════════════════


class HiredHeadhunterScript:
    """
    Natural language: <b>Discover</b> a <b>Battlecry</b> minion.

    Formal spec:
      1. on_play: Discover(hero, count=3, candidates=池过滤 keywords 含
         "battlecry" 的随从)——选项按池剩余量过滤（RULES §6.18），
         选中 acquire 占池 → pending_hand_add
      2. 无候选 → Discover.do 落空

    Test: test_batch_spells3.py — 三选项全带 battlecry 关键词 /
    选中入手并占池

    Params: 无数值参数（文本无占位符）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return Discover(hero, count=3,
                        candidates=_kw_candidates(game, "battlecry"),
                        kind="discover_minion")


# ══════════════════ BG30_804 Robust Evolution ══════════════════


class RobustEvolutionScript:
    """
    Natural language: Choose a minion. Transform it into a random minion
    of a higher Tier. It keeps its stats.

    Tier 语义裁定: "a higher Tier" = **恰好高一级**（tier+1）。依据
    hsdata/CardDefs.xml 多语言: zhCN "高一级的随从" / deDE "eine Stufe
    höher" / jaJP "グレードの1高い" / zhTW "高一級"——enUS 措辞最宽，
    其余四个 locale 均为"一级"。

    Formal spec:
      1. needs_target=True（"Choose a minion" = 友方棋盘定向; 无候选 →
         落空但法术照常消耗）
      2. 选定: 候选 = 池内 tier == target.tier+1 的池随从
         （_pool_candidates 口径: 剩余量/active_races; T6 目标 → T7
         池存在 12 张可达）; rng.choice 随机一张 new_id
      3. 占池（P2）: acquire（金色 target → 结果金色，按金色语义取
         min(3, 剩余) 份——Lockbox 先例; 普通 1 份）; 无候选（tier+1
         池空）→ 落空不占池
      4. Transform(target, new_id, keep_buffs=True)——保留附魔/金色;
         新卡关键词按新定义（官方 Transform 全量换文）
      5. "It keeps its stats"（wiki mechanics: Set attack + Set health）
         ——变形后校正: new.atk == 旧 atk、new.max_health == 旧
         max_health（差值 Buff，含负值）、new.health == 旧 health
         （当前受损状态保留）

    Test: test_batch_spells3.py — T1+buff 目标 → T2 随机卡且
    atk/health/max 全保留 / 占池 / T6→T7 / 金色目标占 3 份

    Params: tier_step=1（zhCN/deDE/jaJP "一级" 文本字面量）
    """

    needs_target = True

    _TIER_STEP = 1     # "higher Tier" = 恰好 +1（多语言 locale 裁定）

    @staticmethod
    def on_play(source, game, ctx):
        target = _spell_target(ctx)
        hero = source.controller
        if target is None or hero is None:
            return None
        new_tier = target.tech_level + RobustEvolutionScript._TIER_STEP
        cands = _pool_candidates(game, min_tier=new_tier, max_tier=new_tier)
        if not cands:
            return None    # tier+1 池空 → 落空（法术照常消耗）
        new_id = game.rng.choice(cands, label="robust_evolution_target")

        copies = 3 if target.is_golden else 1
        for _ in range(min(copies, game.minion_pool.available(new_id))):
            if not game.minion_pool.acquire(new_id):
                raise GameStateError(
                    f"Robust Evolution: acquire failed for {new_id}")

        old_atk = target.atk
        old_health = target.health
        old_max = target.max_health
        idx = hero.board.index(target)
        game.run_actions(Transform(target, new_id, keep_buffs=True))
        new = hero.board[idx]
        # Set attack / Set health（wiki mechanics）: 校正到变形前数值
        d_atk = old_atk - new.atk
        d_health = old_max - new.max_health
        if d_atk or d_health:
            new.add_buff(entity.Buff(d_atk, d_health,
                                     source_id=source.card_id))
        new.set(GameTag.HEALTH, old_health)
        return None


# ══════════════════ BG31_819 Temperature Shift ══════════════════


class TemperatureShiftScript:
    """
    Natural language: Get a Fire Baller and a Snow Baller.

    Formal spec:
      1. on_play: 各获取一张进手牌（"Get" = 进手牌不召唤）:
         - Fire Baller: 经 source CardDef 的 evolution_card_id 数据链
           解析（116736 → BG31_816，Snarky Shark / Shell Collector 先例）
         - Snow Baller: 无数据链 → id 常量 _SNOW_BALLER_ID
           （Papa Mrrglton / Water Droplet 先例）
      2. 两张均为池随从（bg_cards.json 核实 is_pool_minion）→ 各自
         minion_pool.acquire 占池（P2）+ create_minion +
         pending_hand_add（满手排队 RULES §3.3; 两卡互异非 "Get N"
         复数语义，各占 1 份）
      3. 池空（该 Baller 唯余副本被他人持有）→ 仍生成不占池
         （Shell Collector / Mystic Essence 先例）

    Test: test_batch_spells3.py — 入手 Fire/Snow 各一 / 各占池 1 份 /
    两卡自身脚本已注册（Improve 家族可用）

    Params: 无数值参数（token 经数据链/常量解析）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        fire_def = game.db.by_dbf(d.evolution_card_id) \
            if d.evolution_card_id else None
        if fire_def is None or fire_def.name != "Fire Baller":
            raise GameStateError(
                f"{source.card_id}: evolution_card_id broken data chain")
        for card_id in (fire_def.id, _SNOW_BALLER_ID):
            if not game.minion_pool.acquire(card_id):
                pass   # 池空: 仍生成不占池（Shell Collector 先例）
            m = game.create_minion(card_id, controller=hero)
            game.pending_hand_add(hero, m)
        return None


# ══════════════════ BG31_880 Alliance Flag ══════════════════


class AllianceFlagScript:
    """
    Natural language: <b>Choose One - </b>Give a minion +{0}/+{1}; or
    +{2}/+{3}.

    Formal spec:
      1. needs_target=True: play_spell 产生 PendingChoice(kind=
         "spell_target")，选定目标后 on_play 以 ctx["target"] 触发
         （引擎缺口: play_spell 无 Choose One 协议——目标先于分支，
         官方 UI 分支先于目标; 两层玩家决策均队列化，顺序无引擎可
         观测差异）
      2. on_play: 手动产生 PendingChoice(kind="choose_one", options=
         ["atk_first", "health_first"])——引擎通用件（play_minion 的
         choose_one 同 kind）
      3. 选定: "atk_first" → tavern_spell_buff(target, num(0), num(1));
         "health_first" → tavern_spell_buff(target, num(2), num(3))
         （统一出口，TAVERN_SPELL_EXTRA_* 联动）
      4. 无目标（空棋盘落空路径）→ 不产生分支选择

    Test: test_batch_spells3.py — 目标选择 → choose_one 二选一 →
    分支 A +num(0)/num(1) / 分支 B +num(2)/num(3)

    Params: {0}=3 {1}=1 {2}=1 {3}=3（36.2.2 基线）
    """

    needs_target = True

    _OPT_ATK = "atk_first"        # +{0}/+{1}（攻分量大）
    _OPT_HEALTH = "health_first"  # +{2}/+{3}（血分量大）

    @staticmethod
    def on_play(source, game, ctx):
        target = _spell_target(ctx)
        hero = source.controller
        if target is None or hero is None:
            return None
        d = game.db.get(source.card_id)
        vals = (d.num(0), d.num(1), d.num(2), d.num(3))
        if any(v is None for v in vals):
            raise GameStateError(
                f"{source.card_id}: missing num(0..3) template params")

        def resolve(key: str) -> None:
            if key == AllianceFlagScript._OPT_ATK:
                game.run_actions(tavern_spell_buff(target, vals[0], vals[1]))
            elif key == AllianceFlagScript._OPT_HEALTH:
                game.run_actions(tavern_spell_buff(target, vals[2], vals[3]))

        game.pending_choices.append(PendingChoice(
            hero,
            [AllianceFlagScript._OPT_ATK, AllianceFlagScript._OPT_HEALTH],
            "choose_one",
            resolve_callback=resolve,
        ))
        return None


# ══════════════════ OUT_OF_SCOPE（Duos-only，不注册） ══════════════════
#
# BG31_242 Bargain Bundle "Discover a minion. Your teammate gets the
#   other options." —— wiki Availability: Duos games only
# BG31_243 Portal in a Fountain "Pass a minion in the Tavern."
#   —— Duos only; Pass = Duos 传递机制（BACON_PASS_TOOLTIP）
# BG31_244 Portal in a Crystal "Pass a friendly non-Golden minion."
#   —— Duos only


def register() -> list[str]:
    """注册本批次全部脚本，返回注册的 card_id 列表。

    OUT_OF_SCOPE（Duos-only）不注册: BG31_242 / BG31_243 / BG31_244。
    """
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []

    def _add(card_id: str, script_cls) -> None:
        _register(card_id, script_cls)
        registered.append(card_id)

    _add("BG28_882", ContractedCorpseScript)
    _add("BG28_884", OverconfidenceScript)
    _add("BG28_886", StaffOfEnrichmentScript)
    _add("BG28_888", MisplacedTeaSetScript)
    _add("BG28_897", TavernDishBananaScript)
    _add("BG28_966", ThemApplesScript)
    _add("BG28_GIL_836", HiredHeadhunterScript)
    _add("BG30_804", RobustEvolutionScript)
    _add("BG31_819", TemperatureShiftScript)
    _add("BG31_880", AllianceFlagScript)
    return registered
