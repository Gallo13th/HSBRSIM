"""批次 avenge_misc — 12 张 on_sell/受伤触发/Avenge/手牌联动池随从
（作业单 2026-08-21，含金色注册）。

实现状态总览（详见各类 docstring 与批次报告）:
  OK:       BG22_202 Tad / BG24_715 Patient Scout / BG31_816 Fire Baller /
            BG31_818 Snow Baller / BG31_835 Deathly Striker /
            BG32_324 Drustfallen Butcher / BG33_140 River Skipper /
            BG36_181 Air Baller / BG36_703 Twilight Tidehunter /
            BG36_704 Shamanic Tidecaller / BGS_115 Sellemental（含金色）
  DEFERRED: BG29_300 Very Hungry Winterfinner（战斗攻击路径不 fire
            "damage" 事件——引擎缺口，见模块尾"引擎缺口"）

数据核实（2026-08-21，data/bg_cards.json 36.2.2 逐卡打印 +
hearthstone.wiki.gg 逐卡页）:
  BG22_202 Tad            无模板参数（金 "2 random Murlocs" 文本字面量）
  BG24_715 Patient Scout  n1=1（=Tier 基值; 金 n1=1 同）; END_OF_TURN_TRIGGER
      wiki: Discover+Upgradable; TAG_SCRIPT_DATA_NUM_1=1 = Tier 1 基值
  BG29_300 Winterfinner   无模板参数（文本 "+2/+1"、金 "+4/+2" 字面量）;
      wiki Wiki tags 含 [Random] → "a minion in your hand" = 随机
  BG31_816 Fire Baller    n1=1（金 n1=2）; @ 变体文本 "+{0}/+{1}"
  BG31_818 Snow Baller    n2=1（金 n2=2）; @ 变体文本 "+{0}/+{1}"
  BG36_181 Air Baller     n1=2 n2=2（金 4/4）; 无 @ 变体（双分量恒非零）
  BG31_835 Deathly Striker avenge=n1=4（金同）; 金 "Get 2 random Undead...
      Summon them"（计数 2 文本字面量）
  BG32_324 Drustfallen Butcher avenge=n1=4（金同）; evolution_card_id
      110412 → BG28_604 Butchering（is_pool_spell、金链同 110412）
  BG33_140 River Skipper  无模板参数（"Tier 1" 文本字面量）
  BG36_703 Twilight Tidehunter n1=8 n2=8（金 16/16）
  BG36_704 Shamanic Tidecaller n1=3 n2=3（金 6/6）
  BGS_115 Sellemental     无模板参数; token = BGS_115t Water Droplet
      3/3 Elemental（bg_cards.json 核实; 无 evolution 数据链 → id 常量，
      Papa Mrrglton 先例）; 金色定义 id TB_BaconUps_156（dbf 64041，
      triple_base_id 指回 BGS_115）

Baller "Improve your future Ballers" 裁定（OK，非 AMBIGUOUS）:
  wiki 三张 Baller 页均含 [Playerbound]（Air 页另有 [Upgradable]）→
  improvement 是**英雄级共享**计数（Fire/Snow/Air 三兄弟互通）。增长量
  按 Tasty Lobster 先例（batch_deathrattle2，官方 Improve 关键词已裁定:
  "每次触发后 I += 触发副本自身 num 值"）: 卖出 Fire(+1 攻分量) →
  I 攻+1; 卖出 Snow → I 血+1; 卖出 Air → I +2/+2; 金色按金色 CardDef
  自身分量翻倍贡献。读数 = 各 Baller 自身 num + I 全额——与数据指纹
  吻合: Fire/Snow 的 @ 变体 "+{0}/+{1}"（另一分量被 improve 抬到非零
  后切换显示）、Air 无 @ 变体（双分量恒非零）、34.6.0 补丁 Snow
  "+0 Health"→"+1 Health"（基值独立于 improve）。拒绝的备选模型:
  "每次出售固定 +1/+1"（与 Lobster 先例及 Air 官方介绍 "+2/+2 buffs
  on all your future Ballers" 不符）。

Patient Scout "Improves each turn" 裁定（OK，非 AMBIGUOUS）:
  Tier = min(n1 + 当前回合数 - 1, 6)。依据: TAG_SCRIPT_DATA_NUM_1=1 =
  Tier 1 基值（wiki 渲染 "Discover a Tier 1 minion"）; END_OF_TURN_TRIGGER
  家族（Upgradable/Schemes 先例: 值随回合递增）; 社区佐证: r/BobsTavern
  "buy/sell it ... on turn 3"（turn 3 发现 Tier 3 才有价值）、TheGamer
  "After waiting a mere six turns ... free tier-six minion"（六回合
  封顶 T6）。拒绝的备选: "持有回合计数"（v1 旧解; turn 3 卖出仅 Tier 1
  与社区用法矛盾）。上限 6 = C.TAVERN_MAX_TIER。

Deathly Striker "Summon it from your hand for this combat only" 裁定:
  wiki Temporary summon 机制页: "Cards that are temporarily summoned are
  **copied** from the hand for that Combat only, while the original copy
  remains in the hand" → DR 从手牌**复制**召唤（原件留手）; 副本不占池
  （复制自有卡不消耗池副本，_plain_copy_to_hand 先例）; 战斗中召唤的
  副本由 run_combat 棋盘快照恢复自动移除（引擎既有语义）。招募期死亡
  （S14 recruit_phase_attack 可达）时副本不随后清除——引擎无"临时召唤
  生命周期"标记，按引擎语义存续（见"引擎缺口"4）。

Avenge/deathrattle 直接执行模式: avenge 钩子在 _process_single_death
步骤 5 内触发、deathrattle 在步骤 3 内触发——招募期 check_deaths 无
重入保护（batch_deathrattle2 模块 docstring 裁定），本批 avenge/DR
一律直接执行（实体方法/Action(...).do），不返回 Action 入队;
on_sell/on_summon 路径无死亡重入问题，照常返回 Action。

引擎缺口（报告主线）:
  1. DAMAGE 事件仅在 Hit Action 结算时 fire; combat.py _execute_attack
     主/副目标/顺劈与 game.recruit_phase_attack 直接调 take_damage
     不 fire → "Whenever this takes damage" 类触发器
     （BG29_300 Winterfinner）无法 CORRECT 实现，DEFERRED。
  2. PlayBloodGems（Rally/亡语直施宝石）不 fire card_played
     （bloodgem.py 已记录的既有缺口）→ Tidehunter/Tidecaller 对该路径
     施加的宝石不触发; 手牌打出宝石（play_spell 路径）正常触发。
  3. SpellPool 每法术 1 份: 金色 Butcher "Get 2 Butcherings" 第 2 份按
     batch_deathrattle2 裁定"池空生成不占池"达成总额（官方池模型未
     公布多副本语义）。
  4. 无"临时召唤"生命周期标记: Striker 招募期死亡时 DR 副本存续
     （战斗期由棋盘快照恢复覆盖，行为正确）。
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import hsrl2.constants as C
from hsrl2.actions import Buff, Discover, GetRandomMinion
from hsrl2.events import CARD_PLAYED, Listener
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import Race

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

_MURLOC_RACES = (Race.MURLOC, Race.ALL)   # ALL 视为所有种族 (RULES §6.18)
_UNDEAD_RACES = (Race.UNDEAD, Race.ALL)

# Sellemental token（身份标识非数值; bg_cards.json 核实唯一 3/3 Elemental
# token，无 evolution/spellcraft 数据链 → id 常量，Papa Mrrglton 先例）
WATER_DROPLET_ID = "BGS_115t"


def _def(game, source):
    d = game.db.get(source.card_id)
    if d is None:
        raise GameStateError(f"unknown card {source.card_id!r}")
    return d


def _evolution_target(game, source):
    """evolution_card_id 数据链解析关联卡（零硬编码卡 id，Shell Collector
    先例）。金色定义同链（BG32_324_G 亦带 evolution_card_id=110412）。"""
    d = _def(game, source)
    if d.evolution_card_id is None:
        raise GameStateError(
            f"{source.card_id}: evolution_card_id broken data chain")
    t = game.db.by_dbf(d.evolution_card_id)
    if t is None:
        raise GameStateError(
            f"{source.card_id}: evolution_card_id {d.evolution_card_id} "
            f"not in db")
    return t


def _get_pool_spell(game: "Game", hero: "Hero", spell_id: str,
                    count: int) -> None:
    """Get a <specific 池法术> ×count: acquire 优先占池、池空生成不占池
    （batch_deathrattle2 裁定: 金色 "Get 2" 文本总额必须可达成，
    Mystic Essence 先例）。"""
    for _ in range(count):
        if game.spell_pool.available(spell_id) > 0:
            if not game.spell_pool.acquire(spell_id):
                raise GameStateError(
                    f"pool spell acquire failed for {spell_id}")
        game.pending_hand_add(
            hero, game.create_spell(spell_id, controller=hero))


def _acquire_random_race_minion(game: "Game", hero: "Hero", race: Race,
                                label: str) -> Optional[str]:
    """池感知随机获取一张 race 随从进手牌，返回 card_id（None = 池空落空）。

    过滤语义与 actions.discover.GetRandomMinion 一致: 池剩余量>0、
    race 匹配或 ALL（Amalgam）、本局禁用种族排除。需要拿到**选中 id**
    （Deathly Striker 记录亡语召唤目标）故不走 Action。"""
    pool = game.minion_pool
    cands = []
    for dd in game.db.pool_minions():
        if pool.available(dd.id) <= 0:
            continue
        if dd.race != race and dd.race != Race.ALL:
            continue
        if (pool.active_races is not None
                and dd.race not in (Race.NONE, Race.ALL)
                and dd.race not in pool.active_races):
            continue
        cands.append(dd.id)
    if not cands:
        return None
    card_id = game.rng.choice(cands, label=label)
    if not pool.acquire(card_id):
        raise GameStateError(
            f"{label}: pool acquire failed for {card_id}")
    game.pending_hand_add(hero, game.create_minion(card_id, controller=hero))
    return card_id


def _baller_sell(source, game):
    """Baller 三兄弟共用 on_sell: 留存随从按 (自身分量 + Improve I) buff，
    然后 I += 自身分量（Tasty Lobster 先例，模块 docstring 裁定）。"""
    hero = source.controller
    if hero is None:
        return None
    d = _def(game, source)
    base_a = d.num(0) or 0     # num 缺失 = 该分量为 0（Fire num(1)=None）
    base_h = d.num(1) or 0
    imp_a, imp_h = getattr(hero, "baller_improvement", (0, 0))
    out = [Buff(m, atk=base_a + imp_a, health=base_h + imp_h)
           for m in hero.board if m is not source and not m.dead]
    hero.baller_improvement = (imp_a + base_a, imp_h + base_h)
    return out


# ═══════════════════════════ BG22_202 Tad ═══════════════════════════

class TadScript:
    """
    Natural language: When you sell this, get a random Murloc.
    （金色: When you sell this, get 2 random Murlocs.）

    Formal spec:
      1. on_sell: GetRandomMinion(hero, race=MURLOC)——池感知随机获取
         （占池 RULES §2.3，满手排队 RULES §3.3，Amalgam/ALL 匹配）
      2. 金色获取 2 张（两次独立 Action，可抽到同名第二份——池剩余量
         允许时官方行为）
      3. 出售本体回池/金币由引擎 sell_minion 处理

    Test: test_batch_avenge_misc.py — 卖出入手 1 张 Murloc/ALL 且该 id
    池减 1 / 金色 2 张

    Params: 无模板参数（计数 1/2 为文本字面量——CardDef 无参数;
            Murloc 种族为文本身份）
    """

    @staticmethod
    def on_sell(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        n = 2 if source.is_golden else 1
        return [GetRandomMinion(hero, race=Race.MURLOC) for _ in range(n)]


# ═══════════════════════ BG24_715 Patient Scout ═══════════════════════

class PatientScoutScript:
    """
    Natural language: [x]When you sell this, <b>Discover</b> a Tier @
    minion. <i>(Improves each turn!)</i>
    （金色: Discover two Tier @ minions.）

    Formal spec:
      1. on_sell: Discover(hero, min_tier=max_tier=T)——发现一张 T 阶
         随从（三选一 PendingChoice 队列化、选项池感知、选中占池，
         RULES §6.18）
      2. T = min(num(0) + game.turn - 1, C.TAVERN_MAX_TIER)，下限 1
         （num(0)=1 = Tier 1 基值; "Improves each turn" = 每经过一回合
         +1，封顶 T6——裁定依据见模块 docstring）
      3. 金色发现 2 次（两个独立 PendingChoice，队列化不互相覆盖）
      4. 池内该 tier 无候选 → Discover 落空（官方池耗尽行为）

    Test: test_batch_avenge_misc.py — turn=3 发现 Tier 3（选项全 T3、
    选中入手占池）/ turn=9 封顶 T6 / 金色 2 个待决

    Params: {0}=1（Tier 基值 = TAG_SCRIPT_DATA_NUM_1; 金色 {0}=1 同值）
    """

    @staticmethod
    def on_sell(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _def(game, source)
        tier = min(max(d.num(0) + game.turn - 1, 1), C.TAVERN_MAX_TIER)
        n = 2 if source.is_golden else 1
        return [Discover(hero, min_tier=tier, max_tier=tier,
                         kind="patient_scout_discover")
                for _ in range(n)]


# ═══════════════ BG29_300 Very Hungry Winterfinner ═══════════════

class VeryHungryWinterfinnerScript:
    """
    Natural language: <b>Taunt</b>
    Whenever this takes damage, give a minion in your hand +2/+1.
    （金色: ... give a minion in your hand +4/+2.）

    目标选择裁定: wiki 卡片页 Wiki tags 含 [Random] → "a minion in your
    hand" = 手牌中随机一只随从（玩家不可选）。

    Status: DEFERRED — requires "damage" 事件在战斗攻击路径 fire
    Dependency: combat.py _execute_attack（主/副目标/顺劈 take_damage）
      与 game.recruit_phase_attack 直接调 Minion.take_damage 而不 fire
      events.DAMAGE——"damage" 事件当前仅 Hit Action 结算时 fire
      （actions/damage.py）。本卡触发源以战斗受击为主，事件缺口下
      任何实现都是错误近似，按二态纪律 DEFERRED（不注册）。
      引擎补齐后实现（直接执行模式，avenge 类似时序约束不适用——
      damage 事件在 check_deaths 之前 fire，Actions 返回安全）:
        Listener(DAMAGE, owner=source, condition minion is source) →
        targets = [c for c in hero.hand if isinstance(c, Minion)];
        rng.choice → Buff(+num / 文本字面量 2/1、金 4/2——CardDef
        无模板参数)

    Test: （引擎补齐后补测——受击 1 次随机手牌随从 +2/+1）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        return None


# ═══════════════════ BG31_816 Fire Baller ═══════════════════

class FireBallerScript:
    """
    Natural language: [x]When you sell this, give
    your minions +{0} Attack.
    Improve your future
    Ballers.@[x]...+{0}/+{1}...
    （金色: ...give your minions +{0} Attack. Improve...）

    Formal spec:
      1. on_sell: 留存友方棋盘随从（不含正被出售的 source）各获
         +(num(0)+I_a) Attack / +(num(1)+I_h) Health——num(1)=None
         时血分量为 0（@ 变体 "+{0}/+{1}" 为 improve 后双分量显示态）
      2. Improve: hero.baller_improvement（英雄级共享、Fire/Snow/Air
         互通，wiki [Playerbound]）(I_a, I_h) += (num(0), num(1))，
         本次出售先按旧值结算再累加（"future"）
      3. 金色 num(0)=2 自然体现（贡献也翻倍为 +2 攻分量）

    Test: test_batch_avenge_misc.py — 首卖 +1/+0 且 I=(1,0) /
    Snow 卖后 I=(1,1) 时 Fire 给 +2/+1 / 金色首卖 +2/+0

    Params: {0}=1（金色 {0}=2; {1} 无参数 = 血分量 0）
    """

    @staticmethod
    def on_sell(source, game, ctx):
        return _baller_sell(source, game)


# ═══════════════════ BG31_818 Snow Baller ═══════════════════

class SnowBallerScript:
    """
    Natural language: [x]When you sell this, give
    your minions +{1} Health.
    Improve your future
    Ballers.@[x]...+{0}/+{1}...
    （金色: ...give your minions +{1} Health. Improve...）

    Formal spec:
      1. on_sell: 留存友方棋盘随从各获 +(num(0)+I_a)/(num(1)+I_h)——
         num(0)=None 时攻分量为 0（注意模板索引: 本卡文本用 **{1}**
         = script_data_num_2，数据核实 num(1)=1）
      2. Improve 同 FireBallerScript（共享 hero.baller_improvement）
      3. 金色 num(1)=2 自然体现

    Test: test_batch_avenge_misc.py — 首卖 +0/+1 且 I=(0,1) /
    Fire 卖后 I=(1,0) 时 Snow 给 +1/+1

    Params: {1}=1（金色 {1}=2; {0} 无参数 = 攻分量 0）
    """

    @staticmethod
    def on_sell(source, game, ctx):
        return _baller_sell(source, game)


# ═══════════════════ BG36_181 Air Baller ═══════════════════

class AirBallerScript:
    """
    Natural language: When you sell this, give
    your minions +{0}/+{1}.
    Improve your future
    Ballers.
    （金色: ...give your minions +{0}/+{1}. Improve...）

    Formal spec:
      1. on_sell: 留存友方棋盘随从各获 +(num(0)+I_a)/(num(1)+I_h)
      2. Improve 同 FireBallerScript（共享计数，贡献 (2,2)）
      3. 金色 num 4/4 自然体现

    Test: test_batch_avenge_misc.py — 首卖 +2/+2 且 I=(2,2)

    Params: {0}=2 {1}=2（金色 {0}=4 {1}=4）
    """

    @staticmethod
    def on_sell(source, game, ctx):
        return _baller_sell(source, game)


# ═══════════════════ BG31_835 Deathly Striker ═══════════════════

class DeathlyStrikerScript:
    """
    Natural language: [x]<b>Avenge ({0}):</b> Get a random
    Undead. <b>Deathrattle:</b>
    Summon it from your hand
    for this combat only.
    （金色: Avenge ({0}): Get 2 random Undead. Deathrattle: Summon them
    from your hand for this combat only.）

    Formal spec:
      1. avenge（阈值 {0}=num(0) 引擎计数）: 池感知随机获取 1 只
         Undead（含 ALL; 占池）进手牌，card_id 记录于 source 动态属性
         _striker_undead_ids（列表，多次 Avenge 累积——金色单次即 2 只）
      2. deathrattle: 对每个记录 id，手牌存在该 card_id 的 Minion 时
         **复制**召唤（create_minion 同 id——复制自有手牌卡不占池;
         原件留手，wiki Temporary summon）到死者让出的板位
         （ctx["position"] 起始，依次 +1）; 手牌无原件则该份落空
      3. "for this combat only": 战斗期副本由 run_combat 棋盘快照恢复
         自动移除（引擎既有语义）; 招募期死亡时副本存续（引擎无临时
         召唤标记，见模块 docstring 引擎缺口 4）
      4. 直接执行模式（avenge/DR 均在死亡处理内触发，禁 Action 入队）

    Test: test_batch_avenge_misc.py — 4 次友方死亡触发入手 Undead 且
    占池 / DR 从手牌复制召唤且原件留手 / 金色 2 只 / 无记录 DR 落空

    Params: {0}=4（Avenge 阈值; 金色计数 2 为金色文本字面量）
    """

    @staticmethod
    def avenge(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        n = 2 if source.is_golden else 1
        got = getattr(source, "_striker_undead_ids", None)
        if got is None:
            got = []
            source._striker_undead_ids = got
        for _ in range(n):
            card_id = _acquire_random_race_minion(
                game, hero, Race.UNDEAD, label="deathly_striker_avenge")
            if card_id is None:
                break   # Undead 池空: 该份落空（官方效果落空行为）
            got.append(card_id)
        return None

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        pos = (ctx or {}).get("position")
        for card_id in list(getattr(source, "_striker_undead_ids", [])):
            original = next((c for c in hero.hand
                             if isinstance(c, Minion)
                             and c.card_id == card_id), None)
            if original is None:
                continue   # 原件已打出/消耗——无复制来源
            copy = game.create_minion(card_id, controller=hero)
            game.summon(hero, copy, pos)
            if pos is not None:
                pos += 1
        return None


# ═══════════════ BG32_324 Drustfallen Butcher ═══════════════

class DrustfallenButcherScript:
    """
    Natural language: <b>Avenge ({0}):</b> Get a Butchering.
    （金色: Avenge ({0}): Get 2 Butcherings.）

    Formal spec:
      1. avenge（阈值 {0}=num(0) 引擎计数）: 获取 1 张 Butchering
         （BG28_604，经 evolution_card_id 数据链 110412 解析，金色链同）
         进手牌——is_pool_spell → spell_pool.acquire 占池、create_spell、
         pending_hand_add（满手排队 RULES §3.3）
      2. 金色获取 2 张: 第一张 acquire 占池，第二张按池空生成不占池
         （batch_deathrattle2 _get_pool_spell 裁定: 金色 "Get 2" 总额
         必须可达成）
      3. 直接执行模式（avenge 在死亡处理内触发）
      4. Butchering 自身法术效果（Destroy a friendly Undead...）不在
         本批次——缺口审计盯

    Test: test_batch_avenge_misc.py — 4 次友方死亡入手 1 张 BG28_604
    且法术池该 id 不可再取 / 金色 2 张

    Params: {0}=4（Avenge 阈值; 金色计数 2 为金色文本字面量）
    """

    @staticmethod
    def avenge(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        spell_id = _evolution_target(game, source).id
        _get_pool_spell(game, hero, spell_id,
                        2 if source.is_golden else 1)
        return None


# ═══════════════════ BG33_140 River Skipper ═══════════════════

class RiverSkipperScript:
    """
    Natural language: When you sell this, get a random Tier 1 minion.
    （金色: When you sell this, get two random Tier 1 minions.）

    Formal spec:
      1. on_sell: GetRandomMinion(hero, min_tier=1, max_tier=1)——池
         感知随机获取（占池，满手排队）
      2. 金色获取 2 张（两次独立 Action）
      3. "Tier 1" 无模板参数 → 字面量 1（数据核实 num 均缺失）

    Test: test_batch_avenge_misc.py — 卖出入手 1 张 T1 随从且占池 /
    金色 2 张

    Params: 无模板参数（tier=1、计数 1/2 为文本字面量）
    """

    @staticmethod
    def on_sell(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        n = 2 if source.is_golden else 1
        return [GetRandomMinion(hero, min_tier=1, max_tier=1)
                for _ in range(n)]


# ═══════════════ BG36_703 Twilight Tidehunter ═══════════════

class TwilightTidehunterScript:
    """
    Natural language: Whenever you cast a spell on this, give the
    left-most minion in your hand +{0}/+{1}.

    Formal spec:
      1. 入场（on_summon）注册持久监听器（owner=source，离场自动注销）:
         事件 card_played（play_spell fire 时带 target kwarg——引擎
         Wave2 G2 已接线; play_minion 路径无 target kwarg，天然不触发）
      2. 条件: card 是 Spell、card.controller is source.controller
         （"you cast"）、target is source（"on this"）
      3. 触发: 手牌最左随从 = hero.hand 顺序首个 Minion（跳过更靠左的
         法术，Futurefin 先例）获 +num(0)/+num(1) 永久 Buff; 手牌无
         随从则落空
      4. 手牌打出的任意法术均计（酒馆法术/血宝石/Spellcraft——
         play_spell 统一路径）; PlayBloodGems 直施路径不 fire（引擎
         缺口 2）
      5. 金色 num 16/16 自然体现（同一脚本类复用）

    Test: test_batch_avenge_misc.py — 对本体制放法术 → 最左手牌随从
    +num(0)/num(1) / 无目标施放或目标为他人不触发 / 金色 +16/16

    Params: {0}=8 {1}=8（金色 {0}=16 {1}=16）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, target=None, **kw):
            if not isinstance(card, Spell):
                return
            if card.controller is not source.controller:
                return
            if target is not source:
                return
            hero = source.controller
            hand_target = next((c for c in hero.hand
                                if isinstance(c, Minion)), None)
            if hand_target is None:
                return
            d = g.db.get(source.card_id)
            g.run_actions(Buff(hand_target, atk=d.num(0),
                               health=d.num(1)))

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source, callback=on_played))
        return None


# ═══════════════ BG36_704 Shamanic Tidecaller ═══════════════

class ShamanicTidecallerScript:
    """
    Natural language: Whenever you cast a spell on a Murloc, give
    Murlocs in your hand and board +{0}/+{1}.

    Formal spec:
      1. 入场（on_summon）注册持久监听器（owner=source）: 事件 card_played
      2. 条件: card 是 Spell、card.controller is source.controller、
         target 是 Minion 且 race ∈ {MURLOC, ALL}（Amalgam 视为 Murloc，
         RULES §6.18）
      3. 触发: 手牌 + 棋盘全部 Murloc/ALL 随从（含 source 自身——文本
         无 "other"; 含施法目标本身）各获 +num(0)/+num(1) 永久 Buff;
         无 Murloc 时落空
      4. 金色 num 6/6 自然体现

    Test: test_batch_avenge_misc.py — 对 Murloc 施放 → 手牌+棋盘 Murloc
    各 +num(0)/num(1) 且非 Murloc 不变 / 对 Beast 施放不触发

    Params: {0}=3 {1}=3（金色 {0}=6 {1}=6）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, target=None, **kw):
            if not isinstance(card, Spell):
                return
            if card.controller is not source.controller:
                return
            if not (isinstance(target, Minion)
                    and target.race in _MURLOC_RACES):
                return
            hero = source.controller
            d = g.db.get(source.card_id)
            targets = [c for c in hero.hand
                       if isinstance(c, Minion)
                       and c.race in _MURLOC_RACES]
            targets += [m for m in hero.board
                        if not m.dead and m.race in _MURLOC_RACES]
            g.run_actions([Buff(t, atk=d.num(0), health=d.num(1))
                           for t in targets])

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source, callback=on_played))
        return None


# ═══════════════════ BGS_115 Sellemental ═══════════════════

class SellementalScript:
    """
    Natural language: [x]When you sell this,
    get a 3/3 Elemental.
    （金色 TB_BaconUps_156: When you sell this, get two 3/3 Elementals.）

    Formal spec:
      1. on_sell: 获取 1 只 Water Droplet（BGS_115t，3/3 Elemental
         token）进手牌——非池卡不占池（token 语义），create_minion +
         pending_hand_add（满手排队 RULES §3.3）
      2. token id 为身份标识非数值: 无 evolution/spellcraft 数据链，
         bg_cards.json 核实唯一 "3/3 Elemental" token（模块常量
         WATER_DROPLET_ID，Papa Mrrglton 先例）
      3. 金色获取 2 只（金色定义 TB_BaconUps_156 注册同脚本，
         is_golden 分支计数 2——金色文本 "two" 字面量）
      4. token 三连不触发（is_pool_minion=False，引擎 check_for_triple
         直接返回）

    Test: test_batch_avenge_misc.py — 卖出入手 1 只 BGS_115t（3/3
    Elemental）且池无变化 / 金色 2 只

    Params: 无模板参数（"3/3" 为 token 卡面定义非本卡模板参数;
            计数 1/2 为文本字面量）
    """

    @staticmethod
    def on_sell(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        n = 2 if source.is_golden else 1
        for _ in range(n):
            game.pending_hand_add(
                hero, game.create_minion(WATER_DROPLET_ID,
                                         controller=hero))
        return None


def register() -> list[str]:
    """注册本批次脚本（含金色 id）。

    OK 11/12; DEFERRED 1（BG29_300(+_G) Winterfinner 不注册——
    战斗攻击路径 damage 事件缺口，缺口审计盯）。"""
    from hsrl2.scripts.registry import register as reg

    registered: list[str] = []
    for card_id, script in (
        ("BG22_202", TadScript),
        ("BG22_202_G", TadScript),                # 2 random Murlocs
        ("BG24_715", PatientScoutScript),
        ("BG24_715_G", PatientScoutScript),       # two Tier @ discoveries
        ("BG31_816", FireBallerScript),
        ("BG31_816_G", FireBallerScript),         # num(0)=2 自然体现
        ("BG31_818", SnowBallerScript),
        ("BG31_818_G", SnowBallerScript),         # num(1)=2 自然体现
        ("BG36_181", AirBallerScript),
        ("BG36_181_G", AirBallerScript),          # num 4/4 自然体现
        ("BG31_835", DeathlyStrikerScript),
        ("BG31_835_G", DeathlyStrikerScript),     # 2 Undead via is_golden
        ("BG32_324", DrustfallenButcherScript),
        ("BG32_324_G", DrustfallenButcherScript),  # 2 Butcherings
        ("BG33_140", RiverSkipperScript),
        ("BG33_140_G", RiverSkipperScript),       # two Tier 1 minions
        ("BG36_703", TwilightTidehunterScript),
        ("BG36_703_G", TwilightTidehunterScript),  # num 16/16 自然体现
        ("BG36_704", ShamanicTidecallerScript),
        ("BG36_704_G", ShamanicTidecallerScript),  # num 6/6 自然体现
        ("BGS_115", SellementalScript),
        ("TB_BaconUps_156", SellementalScript),   # two 3/3 Elementals
    ):
        reg(card_id, script)
        registered.append(card_id)
    return registered
