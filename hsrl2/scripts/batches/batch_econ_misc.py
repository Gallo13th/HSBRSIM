"""批次 econ_misc — 15 张事件触发型池随从（作业单 2026-08-21，含金色注册）。

事件契约（hsrl2/game.py + hero.py 核实）:
  - gold_spent(amount=, hero=): spend_gold 每次支出 fire 一次（购买/刷新/
    升级/Activate/Dark Gift 全走 spend_gold）; "Whenever you spend N Gold"
    阈值计数 = source 动态属性 _gold_progress 跨回合累积 + 取模
    （官方 "(N Gold left!)" 是本卡累计进度——per-card 计数器; 多张同名卡
    阈值相同结果等价，与阈值不同的 Air Revenant 并存时 per-card 才正确）
  - hero_damage_taken(hero=, amount=): Hero.take_damage 在护甲吸收+扣血
    后 fire，amount=全额（含护甲吸收）; 战斗败方伤害在快照恢复后施加
    （game.run_combat 尾部）→ rewind 触发器落在复原棋盘上
  - card_played(card=, target=): play_minion/_finish_play_spell 广播;
    法术带 target kwarg（Spellcraft 定向）; 磁力吸附路径同样广播
    （"play an Elemental" 含磁力打出）
  - tavern_spell_cast(spell=): 仅 is_pool_spell 法术、效果结算后 fire
  - after_attack(attacker=, defender=): 伤害与死亡结算后 fire
    （combat._execute_attack 与 recruit_phase_attack 双路径）

数据核实（2026-08-21，data/bg_cards.json 36.2.2 逐卡打印 +
hearthstone.wiki.gg 逐卡页）:
  BG23_009 Lava Lurker      n1=1（金 n1=2 = "first {0}" 计数）; 无 spellcraft_id
  BG25_354 Titus Rivendare  无模板参数
  BG26_174 Soul Rewinder    无模板参数（"+1 Health"/金 "+2" 文本字面量）
  BG26_505 Zesty Shaker     无模板参数（计数 1/金 2 文本字面量）
  BG26_810 Gunpowder Courier n1=5 n3=2 → {0}=num(0)=5 阈值 / {2}=num(2)=2 攻击
      （wiki 全 tags: TAG_SCRIPT_DATA_NUM_1=5 NUM_3=2 印证; @ 变体
      "+{2}/+{3}" 的 {3} 无数据 = 血分量 0，仅 improve 后显示态）
  BG27_005 Timecap'n Hooktail n1=1 → {0}=num(0)=1 攻击; 金 n1=1 +
      文本 "twice"（金色 grant×2 非 num 体现）
  BG28_741 Charging Czarina n1=4 → {0}=num(0)=4; 金 n1=8（num 体现，无 "twice"）
  BG29_816 Roaring Recruiter n1=3 n2=1 → {0}=num(0)=3 攻 {1}=num(1)=1 血
      （金 6/2）
  BG31_035 Groundbreaker    n1=3 n2=1 → {0}=num(0)=3 = "every 3" 除数
      （Showy Cyclist BG31_925 同构先例）、{1}=num(1)=1 = 增益（金 n2=2）;
      @ 变体 "Cast {2}/3 spells" 的 {2} 为动态进度（无 num(2) 参数）
  BG31_824 Dual-Wield Corsair n1=5 n3=4 n4=5 → {0}=num(0)=5 阈值 /
      {2}=num(2)=4 攻 / {3}=num(3)=5 血
  BG32_846 Unleashed Mana Surge n1=4 n2=4 → {0}/{1}=num(0)/num(1)=4/4;
      金 n1/n2=4/4 + 文本 "twice"（grant×2）
  BG32_873 Ashen Corruptor  n1=1 n2=1 → {0}/{1}=num(0)/num(1)=1/1（金 2/2）
  BG33_893 Primitive Painter n1=3 n2=3 → {0}/{1}=num(0)/num(1)=3/3（金 6/6）;
      "Tier 3 or below" 阈值 3 为文本字面量（无参数）
  BG34_692 Forsaken Weaver  n1=2 → {0}=num(0)=2（金 4）
  BG34_858 Air Revenant     n1=7 n3=7 → {2}=num(2)=7 = 阈值（"After you
      spend {2} Gold"）、{0}=num(0)=7 为进度显示参数; evolution_card_id
      126909 → BG34_444 Easterly Winds（n1/n2=8/8，is_pool_spell）

实现状态总览:
  OK:       BG26_174 Soul Rewinder / BG26_505 Zesty Shaker /
            BG26_810 Gunpowder Courier / BG27_005 Timecap'n Hooktail /
            BG28_741 Charging Czarina / BG29_816 Roaring Recruiter /
            BG31_035 Groundbreaker / BG31_824 Dual-Wield Corsair /
            BG32_846 Unleashed Mana Surge / BG32_873 Ashen Corruptor /
            BG33_893 Primitive Painter / BG34_692 Forsaken Weaver /
            BG34_858 Air Revenant（各含金色）
  DEFERRED: BG25_354 Titus Rivendare（引擎无 DEATHRATTLE_DOUBLER）、
            BG23_009 Lava Lurker（无 Spellcraft 永久化转换协议）

"rewind" 裁定（Soul Rewinder / Ashen Corruptor，CORRECT——2026-08-23
  查证维持）: 官方 rewind = 撤销该次伤害**含护甲**。证据:
  - us.forums.blizzard.com/en/hearthstone/t/bg-1-armor-with-demons-
    and-soul-rewinder/108498（官方论坛 Bug Report，2023-06）: 玩家
    描述 30hp+1armor 下每次受伤触发 "the broke armor animation, and
    because of the rewinder, the armor added animation"——护甲先破
    后回，多人复现（投诉点仅为动画耗时，非正确性）→ 护甲参与回退
  - reddit.com/r/BobsTavern/comments/13ifo7q: "The rewind wording is
    to say that you took the damage but you have the same health
    still"——回退到受伤前状态（血+甲）
  - 卡页 wiki.gg/wiki/Battlegrounds/Soul_Rewinder 无 Notes（全文
    核对）; 34.2 官方 patch notes 确认 Rewind 为正式关键词
  引擎 take_damage 在 fire 前已完成扣减且事件不携带护甲拆分 →
  脚本层快照协议: hero._rewind_snapshot=(health, armor) 由
  rewinder on_summon 初始化，监听器回调恢复到快照（set 语义幂等
  ——多张 rewinder 同事件多次恢复结果一致，官方"每张各触发但伤害
  只回退一次"成立）。快照不变式: 存活 rewinder 在场时英雄血/甲被
  冻结（一切 take_damage 都被回退）; 出售后监听器注销、快照由
  后续 rewinder 重新基线化。引擎不变式依赖: 护甲仅经 take_damage
  变动（grep 验证 game.py/hero.py 无其他 ARMOR 写点）。

Groundbreaker "every 3 spells" 计数裁定（沿用先例）:
  施法数 = TAVERN_SPELLS_CAST_THIS_GAME（引擎仅对 is_pool_spell 累计）
  ——Showy Cyclist BG31_925（batch_deathrattle，同款括号文本）作业单
  裁定先例，mult = 1 + casts // num(0)。⚠️ 社区证据（r/BobsTavern
  "Is Groundbreaker stronger than it seems?"）: 官方 "every spell means
  *every* spell. It includes spellcraft"——引擎无含 Spellcraft 的全量
  施法计数器（缺口 3，报告主线; 两卡实现保持一致待主线统一）。

引擎缺口（报告主线）:
  1. 无 DEATHRATTLE_DOUBLER tag/引擎支持: _process_single_death 对亡语
     钩子恒单次触发（game.py:1030），BATTLECRY_DOUBLER（tags.py:151 +
     game.py:559）有先例可循 → Titus Rivendare DEFERRED。
  2. 无 Spellcraft 永久化转换协议: Spellcraft 法术的临时性由法术
     on_play 内部的 entity.Buff(temporary=True) + TURN_START once
     精确移除监听器（scripts/spells.py _expire_at_next_turn）两层构成，
     施加点在法术脚本内部、事件流上无第三方可拦截点（spellcraft_cast
     先于 on_play 但不带 target; card_played 带目标但过期监听器已注册，
     且 EventBus 仅支持 unregister_owner 整体注销）→ Lava Lurker
     DEFERRED。需: 法术 on_play ctx 传入 "make_permanent" 标记、或
     buff temporary 翻转协议、或按监听器精细注销 API。
  3. "every 3 spells you've cast this game" 无全量计数器: 官方含
     Spellcraft（社区证据），引擎仅 TAVERN_SPELLS_CAST_THIS_GAME
     （is_pool_spell）。本批 Groundbreaker 与 Showy Cyclist 一致沿用
     引擎 tag；主线若 broaden 计数器需同步两卡。
  4. create_spell 不为法术定义设 SPELLCRAFT tag（仅随从 spellcraft_id
     链映射）——Zesty Shaker 复制路径手动 set（_make_spellcraft_spell
     先例）。
  5. Hero 伤害事件无"伤害前快照"——rewind 快照协议为脚本层方案
     （依赖"护甲仅经 take_damage 变动"引擎不变式，见上裁定）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2 import entity
from hsrl2.actions import Buff
from hsrl2.actions.racefx import ApplyRaceAura, tavern_spell_buff
from hsrl2.events import (
    AFTER_ATTACK,
    CARD_PLAYED,
    GOLD_SPENT,
    HERO_DAMAGE_TAKEN,
    TAVERN_REFRESH,
    TAVERN_SPELL_CAST,
    TURN_START,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# ALL 视为所有种族 (RULES §6.18)
_PIRATE_RACES = (Race.PIRATE, Race.ALL)
_DRAGON_RACES = (Race.DRAGON, Race.ALL)
_NAGA_RACES = (Race.NAGA, Race.ALL)
_ELEMENTAL_RACES = (Race.ELEMENTAL, Race.ALL)
_MURLOC_RACES = (Race.MURLOC, Race.ALL)
_UNDEAD_RACES = (Race.UNDEAD, Race.ALL)

# Primitive Painter "Tier 3 or below" 阈值（文本字面量，CardDef 无参数）
_PAINTER_MAX_TIER = 3


def _def(game, source):
    d = game.db.get(source.card_id)
    if d is None:
        raise GameStateError(f"unknown card {source.card_id!r}")
    return d


def _evolution_spell_id(game, source) -> str:
    """evolution_card_id 数据链解析关联法术 id（零硬编码卡 id）。"""
    d = _def(game, source)
    if d.evolution_card_id is None:
        raise GameStateError(
            f"{source.card_id}: evolution_card_id broken data chain")
    t = game.db.by_dbf(d.evolution_card_id)
    if t is None:
        raise GameStateError(
            f"{source.card_id}: evolution_card_id {d.evolution_card_id} "
            f"not in db")
    return t.id


# ── rewind 快照协议（Soul Rewinder / Ashen Corruptor 共用，见模块裁定）──

def _rebaseline_rewind_snapshot(hero: "Hero") -> None:
    """以当前 (health, armor) 为 rewind 基线。

    on_summon 时调用: 首个 rewinder 建立基线; 后续 rewinder 入场时英雄
    状态恒等于现行基线（存活 rewinder 冻结语义）→ 重写无害; 出售后
    新 rewinder 以受击后状态重新基线化。
    """
    hero._rewind_snapshot = (hero.health, hero.armor)


def _rewind(hero: "Hero", health_before: int = None,
            armor_before: int = None) -> None:
    """回退**本次**伤害实例（2026-08-22 修正: 事件携带伤害前
    health/armor——真正 Rewind 语义，逐实例撤销含护甲; 替代旧基线
    快照方案——基线随时间陈旧且多来源伤害混杂）。无 before 值（
    旧调用方兜底）→ 回退到基线快照（兼容）。"""
    if health_before is not None and armor_before is not None:
        hero.health = health_before
        hero.armor = armor_before
        return
    snap = getattr(hero, "_rewind_snapshot", None)
    if snap is not None:
        hero.health, hero.armor = snap


def _expire_buffs_next_turn(game: "Game", hero: "Hero", target,
                            buffs: list) -> None:
    """"+X/+Y this turn" 过期: 目标控制者下一招募阶段开始精确移除
    （scripts/spells.py _expire_at_next_turn 同款; 含生命封顶）。
    owner=target（离场自动注销; 移除已消失 buff 为无害 no-op）。"""
    buffs = list(buffs)

    def _on_turn_start(g, h=None, **kw):
        for b in buffs:
            target.remove_buff(b)
        if any(b.health > 0 for b in buffs):
            target.set(GameTag.HEALTH,
                       min(target.health, target.max_health))

    game.events.register(Listener(
        event=TURN_START,
        owner=target,
        once=True,
        # 默认参数捕获控制者引用（防 lambda 形参 hero 遮蔽外层闭包）
        condition=lambda hero=None, _ctrl=hero, **kw: hero is _ctrl,
        callback=_on_turn_start,
    ))


# ═══════════════════ BG25_354 Titus Rivendare（DEFERRED） ═══════════════════

class TitusRivendareScript:
    """
    Natural language: Your <b>Deathrattles</b> trigger an extra time.
    （金色: Your Deathrattles trigger 2 extra times.）

    Status: DEFERRED — requires DEATHRATTLE_DOUBLER 引擎支持

    Dependency: game._process_single_death 对亡语钩子恒单次触发
      （game.py:1030 run_script_hook(m, "deathrattle")），无 Brann 式
      翻倍判定（对照 BATTLECRY_DOUBLER: tags.py:151 + game.py:559
      _battlecry_doubled + _run_play_effects times 乘算先例）。需要:
      1) tags.py 新增 DEATHRATTLE_DOUBLER; 2) _process_single_death 亡语
      段按 hero.board 光环求 extra times 并逐次触发（磁力栈叠亡语同步
      翻倍; COUNTER_DEATHRATTLES/broadcast 计数同步）。主线专属修改
      （subagent 禁改引擎），补齐后注册实现。
      实现草案（裁决后）: on_summon set(GameTag.DEATHRATTLE_DOUBLER,
      2 if golden else 1)（引擎按最大值/叠加规则消费）。

    Params: 无模板参数（金色 "2 extra times" 为文本字面量）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        return None


# ═══════════════════ BG23_009 Lava Lurker（DEFERRED） ═══════════════════

class LavaLurkerScript:
    """
    Natural language: [x]The first <b>Spellcraft</b> spell
    _played from hand on this
    _each turn is permanent.
    <i>({0} left!)</i>
    （金色: The first 2 Spellcraft spells played on this each turn are
    permanent.）

    Status: DEFERRED — requires Spellcraft 永久化转换协议

    Dependency: "permanent" = 保留该法术附魔（wiki mechanics: Keep
      enchantment; 34.0 bugfix "retains Reborn from Weary Mage's
      Reinvigoration Spellcraft"——含关键词）。当前引擎下 Spellcraft
      法术的临时性由法术脚本 on_play 内部两层机制构成:
      1) entity.Buff(temporary=True)——施加上附魔内部标志
      2) TURN_START once 过期监听器（owner=目标随从，闭包精确移除，
         scripts/spells.py _expire_at_next_turn）
      第三方（本卡）无可行拦截点:
      - spellcraft_cast 事件先于 on_play 但不带 target——无法判定
        "on this"; card_played 带目标但过期监听器已注册
      - EventBus 仅 unregister_owner 整体注销（会连带注销本卡自身
        监听器），无按监听器精细注销; 篡改 _listeners 为读写引擎
        私有状态（SOP 禁止）
      需主线提供: 法术 on_play ctx "make_permanent" 标记协议 / buff
      temporary 事后翻转协议 / 精细监听器注销 API 之一。
      实现草案（协议就绪后）: on_summon 注册 card_played 监听
      （Spell + SPELLCRAFT + target is source + controller 匹配），
      每回合前 num(0) 次（金色 n1=2; 回合戳记数于 source 动态属性）
      标记该次施法永久化。

    Test: （协议就绪后补测——首个 Spellcraft 打在本体 → 附魔/关键词
      跨回合保留; 每回合重置; 金色 2 次）

    Params: {0}=1（每回合永久化计数; 金色 {0}=2）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        return None


# ═══════════════════ BG26_174 Soul Rewinder ═══════════════════

class SoulRewinderScript:
    """
    Natural language: After your hero takes damage, rewind it and give
    this +1 Health.
    （金色: After your hero takes damage, rewind it and give this
    +2 Health.）

    Formal spec:
      1. 入场（on_summon）: 建立英雄 rewind 快照 hero._rewind_snapshot
         =(health, armor)（模块 docstring 裁定: 官方 rewind 含护甲恢复，
         社区"loose armor/gain armor back"证据）+ 注册持久监听器
         Listener(HERO_DAMAGE_TAKEN, owner=source)
      2. 条件: kw["hero"] is source.controller（"your hero"）
      3. 触发: hero 恢复到快照（set 语义幂等——多张 Rewinder 同一次
         伤害各触发一次但只回退一次，官方行为）+ Buff(source,
         health=+1/+2)
      4. 每次受伤触发一次（护甲吸收也算受伤——引擎 HERO_DAMAGE_TAKEN
         全额 amount 语义）。**战败伤害不触发**（2026-08-22 修正）:
         战斗结束条件 = 败方棋盘全灭，伤害施加于战后棋盘时 Rewinder
         必然已死、监听器缺席——官方定位为招募期扣血联动（健康购买/
         自伤技能/法术），非战败免伤
      5. 引擎不变式依赖: 护甲仅经 take_damage 变动（快照协议成立前提，
         见模块 docstring 引擎缺口 5）

    Test: test_batch_econ_misc.py — 受伤后血/甲恢复原值且本体 +1 血 /
    敌方英雄受伤不触发 / 出售后受伤不再回退 / 金色 +2 / 多张只回退一次
    但各自 +1 血

    Params: 无模板参数（"+1 Health"=1、金色 "+2 Health"=2 为文本
            字面量——CardDef 无参数; 金色经 is_golden 分支）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        _rebaseline_rewind_snapshot(hero)

        def on_hero_damaged(g, hero=None, amount=0,
                            health_before=None, armor_before=None, **kw):
            if hero is not source.controller:
                return
            # 逐实例回退（引擎 HERO_DAMAGE_TAKEN 携带伤害前值——含护甲）
            _rewind(hero, health_before, armor_before)
            gain = 2 if source.is_golden else 1
            g.run_actions(Buff(source, atk=0, health=gain))

        game.events.register(Listener(
            event=HERO_DAMAGE_TAKEN, owner=source,
            callback=on_hero_damaged))
        return None


# ═══════════════════ BG26_505 Zesty Shaker ═══════════════════

class ZestyShakerScript:
    """
    Natural language: [x]Once per turn, when a
    <b>Spellcraft</b> spell is played on
    _this, get a new copy of it.
    （金色: Once per turn, when a Spellcraft spell is played on this,
    get 2 new copies of it.）

    Formal spec:
      1. 入场注册持久监听器（owner=source）: 事件 card_played（法术
         路径带 target kwarg——引擎 Wave2 G2 接线）
      2. 条件: card 是 Spell、card.has(SPELLCRAFT)、card.controller
         is source.controller（"played"=你打出）、target is source
         （"on this"）; 且本回合未触发过（source 动态属性 _shaker_turn
         记录 game.turn——"Once per turn" 按游戏回合）
      3. 触发（并消耗本回合额度）: 创建 num 份新法术副本——
         create_spell(同 card_id)（自动绑定 REGISTRY 脚本）+
         手动 set SPELLCRAFT tag（引擎缺口 4: create_spell 不设该 tag，
         _make_spellcraft_spell 先例）+ 复制原法术
         spellcraft_source_uuid（Sunken Persistence 永久化豁免随原件
         语义）+ pending_hand_add（满手排队 RULES §3.3）
      4. 副本是 Spellcraft 法术: 回合结束按 SPELLCRAFT tag 丢弃
         （end_recruit_phase 既有语义）; "from hand" 打出路径经
         play_spell 正常生效
      5. 金色 2 份（金色文本 "2 new copies" 字面量，is_golden 分支）

    Test: test_batch_econ_misc.py — Spellcraft 打在本体 → 手牌出现同 id
    副本（SPELLCRAFT tag）/ 同回合第二次不再复制 / 打在其他随从不触发 /
    非Spellcraft法术不触发 / 跨回合重置 / 金色 2 份

    Params: 无模板参数（计数 1/2 为文本字面量; 副本身份=原法术 card_id）
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
            if not card.has(GameTag.SPELLCRAFT):
                return
            if getattr(source, "_shaker_turn", None) == g.turn:
                return
            source._shaker_turn = g.turn
            hero = source.controller
            copies = 2 if source.is_golden else 1
            for _ in range(copies):
                copy = g.create_spell(card.card_id, controller=hero)
                copy.set(GameTag.SPELLCRAFT, True)
                copy.spellcraft_source_uuid = getattr(
                    card, "spellcraft_source_uuid", None)
                g.pending_hand_add(hero, copy)

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source, callback=on_played))
        return None


# ═══════════════════ BG26_810 Gunpowder Courier ═══════════════════

class GunpowderCourierScript:
    """
    Natural language: [x]Whenever you spend 5 Gold,
    give your Pirates +{2} Attack.
    <i>({0} Gold left!)</i>
    （金色: ...give your Pirates +{2} Attack twice. <i>({0} Gold left!)</i>）

    Formal spec:
      1. 入场注册持久监听器（owner=source）: 事件 gold_spent
         (amount=, hero=)
      2. 条件: hero is source.controller; 累计计数 source._gold_progress
         += amount（跨回合累积，取模消费: while p >= 阈值: p -= 阈值并
         触发——单次大额支出跨边界只按倍数触发，作业单"达阈值触发+
         取模"裁定; per-card 计数器=官方 "(N Gold left!)" 逐卡显示模型）
      3. 触发: 全体友方存活 Pirates（PIRATE/ALL，含自身——"your
         Pirates"无 "other"; 仅棋盘）各 Buff +num(2) Attack（金色文本
         "twice" → 同次触发 grant×2，两笔独立 buff）
      4. 金色 num(2)=2 与基础同值（金色差异仅在 grant 次数）

    Test: test_batch_econ_misc.py — 累计 5 金触发全海盗 +num(2) 攻 /
    4 金不触发 / 一次 12 金触发 2 次余 2 / 非海盗不获 / 敌方支出不触发 /
    金色同次触发 ×2

    Params: {0}=5（阈值=script_data_num_1; "spend 5 Gold" 文本与参数
            一致，wiki NUM_1=5 印证） {2}=2（攻击=script_data_num_3）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_gold_spent(g, hero=None, amount=0, **kw):
            if hero is not source.controller or amount <= 0:
                return
            d = g.db.get(source.card_id)
            threshold = d.num(0)
            p = getattr(source, "_gold_progress", 0) + amount
            grants = 2 if source.is_golden else 1
            while p >= threshold:
                p -= threshold
                for _ in range(grants):
                    g.run_actions([
                        Buff(m, atk=d.num(2))
                        for m in hero.board
                        if not m.dead and m.race in _PIRATE_RACES])
            source._gold_progress = p

        game.events.register(Listener(
            event=GOLD_SPENT, owner=source, callback=on_gold_spent))
        return None


# ═══════════════════ BG27_005 Timecap'n Hooktail ═══════════════════

class TimecapnHooktailScript:
    """
    Natural language: [x]Whenever you cast a
    Tavern spell, give your
    minions +{0} Attack.
    （金色: ...give your minions +{0} Attack twice.）
    （@ 变体 "+{0}/+{1}" 为 improve 后双分量显示态; num(1) 无数据=血 0）

    Formal spec:
      1. 入场注册持久监听器（owner=source）: 事件 tavern_spell_cast
         (spell=)——引擎仅对 is_pool_spell 法术、效果结算后 fire
         （官方 29.2.2 bugfix 语义; Spellcraft/血宝石不计——"Tavern
         spell" 严格词）
      2. 条件: spell.controller is source.controller（"you cast"）
      3. 触发: 全体友方存活随从（含自身）各 Buff +num(0) Attack;
         金色文本 "twice" → grant×2（金色 num(0)=1 与基础同值，
         差异仅在次数）
      4. 每施放一计一次（多次施放多次触发）

    Test: test_batch_econ_misc.py — 施放池法术 → 全队 +num(0) 攻 /
    Spellcraft 法术不触发 / 敌方施放不触发 / 金色 ×2

    Params: {0}=1（金色 {0}=1 同值 + "twice"=2 次文本字面量）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_tavern_spell(g, spell=None, **kw):
            if spell is None or spell.controller is not source.controller:
                return
            d = g.db.get(source.card_id)
            grants = 2 if source.is_golden else 1
            for _ in range(grants):
                g.run_actions([
                    Buff(m, atk=d.num(0))
                    for m in source.controller.board if not m.dead])

        game.events.register(Listener(
            event=TAVERN_SPELL_CAST, owner=source,
            callback=on_tavern_spell))
        return None


# ═══════════════════ BG28_741 Charging Czarina ═══════════════════

class ChargingCzarinaScript:
    """
    Natural language: [x]<b>Divine Shield</b>
    Whenever you cast a Tavern
    spell, give your minions with
    ___<b>Divine Shield</b> +{0} Attack.

    Formal spec:
      1. 本体自带 Divine Shield（CardDef 关键词，引擎 create_minion 映射）
      2. 入场注册持久监听器（owner=source）: 事件 tavern_spell_cast
      3. 条件: spell.controller is source.controller
      4. 触发: 全体友方**当前持有** DIVINE_SHIELD 的存活随从（含自身）
         各 Buff +num(0) Attack（无圣盾随从 → 落空）
      5. 金色 num(0)=8 数据体现（金色文本无 "twice"）

    Test: test_batch_econ_misc.py — 施放后圣盾随从 +num(0) 攻、无圣盾
    不变 / 无圣盾随从时全落空 / 金色 +num(0)=8 / 敌方施放不触发

    Params: {0}=4（金色 {0}=8）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_tavern_spell(g, spell=None, **kw):
            if spell is None or spell.controller is not source.controller:
                return
            d = g.db.get(source.card_id)
            g.run_actions([
                Buff(m, atk=d.num(0))
                for m in source.controller.board
                if not m.dead and m.has(GameTag.DIVINE_SHIELD)])

        game.events.register(Listener(
            event=TAVERN_SPELL_CAST, owner=source,
            callback=on_tavern_spell))
        return None


# ═══════════════════ BG29_816 Roaring Recruiter ═══════════════════

class RoaringRecruiterScript:
    """
    Natural language: Whenever another friendly Dragon attacks, give it
    +{0}/+{1}.

    Formal spec:
      1. 入场注册持久监听器（owner=source）: 事件 after_attack
         (attacker=, defender=)——伤害与死亡结算后广播（combat C4;
         recruit_phase_attack 同样广播 → 招募期攻击照常触发）
      2. 条件（Prodigious Tusker batch_bloodgem 先例）:
         a) attacker is not source（"another"）
         b) attacker.controller is source.controller（"friendly"）
         c) attacker 已战死 → 跳过（Buff 目标须为有效存活随从;
            AFTER_ATTACK 无论存活与否都广播）
         d) attacker.race ∈ {DRAGON, ALL}
      3. 触发: Buff(attacker, +num(0)/+num(1))——战斗内触发经快照战后
         回滚（RULES §3.5）; 招募期攻击（Fishbait 路径）的 buff 持久
      4. 金色 num 6/2 数据体现（同一脚本类复用）

    Test: test_batch_econ_misc.py — 友方龙攻击后 +num(0)/num(1) /
    本体攻击不触发 / 非龙攻击不触发 / 敌方龙不触发 / 战死 attacker
    跳过 / 金色 +6/+2

    Params: {0}=3 {1}=1（金色 {0}=6 {1}=2）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_after_attack(g, attacker=None, defender=None, **kw):
            if attacker is None or attacker is source:
                return
            if attacker.controller is not source.controller:
                return
            if attacker.dead:
                return
            if attacker.race not in _DRAGON_RACES:
                return
            d = g.db.get(source.card_id)
            g.run_actions(Buff(attacker, atk=d.num(0), health=d.num(1)))

        game.events.register(Listener(
            event=AFTER_ATTACK, owner=source, callback=on_after_attack))
        return None


# ═══════════════════ BG31_035 Groundbreaker ═══════════════════

class GroundbreakerScript:
    """
    Natural language: [x]After you play a Naga, gain
    +{1}/+{1}. <i>(Improved by
    every 3 spells you've cast
    this game!)</i>
    （金色: After you play a Naga, gain +{1}/+{1}. ...——num(1)=2）

    Formal spec:
      1. 入场注册持久监听器（owner=source）: 事件 card_played
         （play_minion/_run_play_effects 广播; 磁力吸附路径同样广播）
      2. 条件: card 是 Minion、card.controller is source.controller
         （"you play"; 无 "another"——后续打出的 Groundbreaker 副本也计）、
         card.race ∈ {NAGA, ALL}
      3. 触发: mult = 1 + 施法数 // num(0)（"every 3" 整除递进: 0-2 次
         ×1、3-5 次 ×2 …——Showy Cyclist BG31_925 同款括号文本先例）;
         Buff(source, +num(1)*mult/+num(1)*mult)
      4. 施法数 = hero.TAVERN_SPELLS_CAST_THIS_GAME（引擎 tag，仅
         is_pool_spell 累计——Showy Cyclist 作业单裁定沿用; ⚠️ 社区证据
         官方含 Spellcraft，模块 docstring 引擎缺口 3，主线统一）
      5. 文本第二变体 "(Cast {2}/3 spells to improve!)" 为动态进度提示
         （{2} 非静态参数，CardDef 无 num(2)），不影响结算
      6. 金色 num(1)=2 数据体现（mult 同式）

    Test: test_batch_econ_misc.py — 0 施法打 Naga +num(1)/num(1) /
    3 施法后 ×2 / 打非 Naga 不触发 / 敌方打 Naga 不触发 / 金色 +2/+2 基值

    Params: {0}=3（"every 3" 除数=script_data_num_1; 金色同值）
            {1}=1（增益=script_data_num_2; 金色 {1}=2）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, **kw):
            if not isinstance(card, Minion):
                return
            if card.controller is not source.controller:
                return
            if card.race not in _NAGA_RACES:
                return
            hero = source.controller
            d = g.db.get(source.card_id)
            casts = hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0)
            mult = 1 + casts // d.num(0)
            g.run_actions(Buff(source, atk=d.num(1) * mult,
                               health=d.num(1) * mult))

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source, callback=on_played))
        return None


# ═══════════════════ BG31_824 Dual-Wield Corsair ═══════════════════

class DualWieldCorsairScript:
    """
    Natural language: [x]Whenever you spend 5 Gold,
    give two friendly Pirates
    +{2}/+{3}. <i>({0} Gold left!)</i>
    （金色: ...give two friendly Pirates +{2}/+{3} twice. ...）

    Formal spec:
      1. 入场注册持久监听器（owner=source）: 事件 gold_spent——累计
         source._gold_progress 跨回合计数 + 取模消费（Gunpowder
         Courier 同款，per-card 计数器）
      2. 触发: 随机两只友方 Pirate（PIRATE/ALL，含自身，仅棋盘）
         各 Buff +num(2)/+num(3)——"two friendly Pirates" 无选择词
         且无 wiki [Targeted] → 随机二（v1 先例 + SOP 目标裁决库:
         无 "Choose"/[Targeted] 的 "a friendly X" 型随机; 随机必走
         game.rng.sample）; 只有一只时该只获 buff（k=min(2, 数量)），
         无海盗落空
      3. 金色文本 "twice" → grant×2（两次独立随机选取）
      4. 阈值 num(0)=5 与 Courier 同值

    Test: test_batch_econ_misc.py — 累计 5 金 → 两只海盗各 +num(2)/
    num(3)（共恰 2 只时全覆盖）/ 仅 1 只海盗时该只得 / 4 金不触发 /
    非海盗不受 / 金色同次 ×2

    Params: {0}=5（阈值） {2}=4（攻=script_data_num_3）
            {3}=5（血=script_data_num_4）; count=2（"two" 文本字面量;
            金色 twice=2 次文本字面量）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_gold_spent(g, hero=None, amount=0, **kw):
            if hero is not source.controller or amount <= 0:
                return
            d = g.db.get(source.card_id)
            threshold = d.num(0)
            p = getattr(source, "_gold_progress", 0) + amount
            grants = 2 if source.is_golden else 1
            while p >= threshold:
                p -= threshold
                for _ in range(grants):
                    pirates = [m for m in hero.board
                               if not m.dead and m.race in _PIRATE_RACES]
                    if not pirates:
                        continue
                    k = min(2, len(pirates))
                    picks = g.rng.sample(
                        pirates, k, label="dual_wield_corsair")
                    g.run_actions([
                        Buff(m, atk=d.num(2), health=d.num(3))
                        for m in picks])
            source._gold_progress = p

        game.events.register(Listener(
            event=GOLD_SPENT, owner=source, callback=on_gold_spent))
        return None


# ═══════════════════ BG32_846 Unleashed Mana Surge ═══════════════════

class UnleashedManaSurgeScript:
    """
    Natural language: After you play an Elemental, give your Elementals
    +{0}/+{1}.
    （金色: ...give your Elementals +{0}/+{1} twice.）

    Formal spec:
      1. 入场注册持久监听器（owner=source）: 事件 card_played
         （磁力 Elemental 吸附路径同样广播——打出即计入，官方语义）
      2. 条件: card 是 Minion、card.controller is source.controller、
         card.race ∈ {ELEMENTAL, ALL}
      3. 触发: 全体友方存活 Elementals（ELEMENTAL/ALL——含刚打出者与
         本体，"your Elementals" 无 "other"; 仅棋盘）各 Buff
         +num(0)/+num(1); 金色文本 "twice" → grant×2
         （金色 num 4/4 与基础同值，差异仅次数）
      4. 无 Elemental 落空; 本体在场恒至少 1 只（自身是 Elemental）

    Test: test_batch_econ_misc.py — 打出 Elemental → 全体 Elementals
    含本体与打出者各 +num(0)/num(1) / 打非 Elemental 不触发 / 敌方打
    Elemental 不触发 / 金色 ×2

    Params: {0}=4 {1}=4（金色 {0}=4 {1}=4 同值 + "twice"=2 次文本字面量）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, **kw):
            if not isinstance(card, Minion):
                return
            if card.controller is not source.controller:
                return
            if card.race not in _ELEMENTAL_RACES:
                return
            d = g.db.get(source.card_id)
            grants = 2 if source.is_golden else 1
            for _ in range(grants):
                g.run_actions([
                    Buff(m, atk=d.num(0), health=d.num(1))
                    for m in source.controller.board
                    if not m.dead and m.race in _ELEMENTAL_RACES])

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source, callback=on_played))
        return None


# ═══════════════════ BG32_873 Ashen Corruptor ═══════════════════

class AshenCorruptorScript:
    """
    Natural language: [x]After your hero takes
    damage, rewind it and
    give minions in the Tavern
    +{0}/+{1} this turn.

    Formal spec:
      1. 入场: 建立 rewind 快照（Soul Rewinder 同款协议，模块 docstring
         裁定）+ 注册 Listener(HERO_DAMAGE_TAKEN, owner=source)
      2. 条件: kw["hero"] is source.controller
      3. 触发: hero 恢复到快照（幂等）+ 酒馆（hero.tavern）全部 Minion
         各 temporary Buff +num(0)/+num(1) + 逐目标 TURN_START once
         过期（owner=目标随从，精确移除+生命封顶; scripts/spells.py
         同款——"this turn" 官方期末过期与 "until next turn" 下一招募
         开始在引擎内无观测差（战斗介于其间两模型均保留），按既有
         过期协议实现）
      4. 购入的受 buff 随从: 过期监听器随实体走（owner=目标）→ 买入后
         下一回合开始照常过期; 冻结/刷新滞留的馆内随从同样过期
      5. 金色 num 2/2 数据体现

    Test: test_batch_econ_misc.py — 受伤后血/甲恢复 + 馆内随从
    +num(0)/num(1) / 下一回合开始过期回落 / 未受伤馆内不变 / 敌方受伤
    不触发 / 金色 +2/+2

    Params: {0}=1 {1}=1（金色 {0}=2 {1}=2）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        _rebaseline_rewind_snapshot(hero)

        def on_hero_damaged(g, hero=None, amount=0, **kw):
            if hero is not source.controller:
                return
            _rewind(hero)
            d = g.db.get(source.card_id)
            for e in list(hero.tavern):
                if not isinstance(e, Minion):
                    continue
                buffs = [entity.Buff(atk=d.num(0), health=d.num(1),
                                     temporary=True)]
                e.add_buff(buffs[0])
                _expire_buffs_next_turn(g, hero, e, buffs)

        game.events.register(Listener(
            event=HERO_DAMAGE_TAKEN, owner=source,
            callback=on_hero_damaged))
        return None


# ═══════════════════ BG33_893 Primitive Painter ═══════════════════

class PrimitivePainterScript:
    """
    Natural language: After you play a card from Tier 3 or below, give
    your Murlocs +{0}/+{1}.

    Formal spec:
      1. 入场注册持久监听器（owner=source）: 事件 card_played
         （随从/法术均广播——"a card" 泛指; 磁力路径同样广播）
      2. 条件: card.controller is source.controller、CardDef.tech_level
         ≤ 3（"Tier 3 or below"——含 T0 token/血宝石等无阶卡; 阈值 3 为
         文本字面量，CardDef 无对应参数）
      3. 触发: 全体友方存活 Murlocs（MURLOC/ALL，含本体; 仅棋盘）各
         Buff +num(0)/+num(1)
      4. 金色 num 6/6 数据体现

    Test: test_batch_econ_misc.py — 打出 T≤3 随从 → 全体 Murlocs
    +num(0)/num(1) / 打出 T4+ 随从不触发 / 施放 T≤3 池法术触发 /
    非 Murloc 不受 / 敌方打出不触发 / 金色 +6/+6

    Params: {0}=3 {1}=3（金色 {0}=6 {1}=6）; tier=3（"Tier 3 or below"
            文本字面量）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_played(g, card=None, **kw):
            if card is None:
                return
            if getattr(card, "controller", None) is not source.controller:
                return
            played_def = g.db.get(card.card_id)
            if played_def is None:
                return
            if played_def.tech_level > _PAINTER_MAX_TIER:
                return
            d = g.db.get(source.card_id)
            g.run_actions([
                Buff(m, atk=d.num(0), health=d.num(1))
                for m in source.controller.board
                if not m.dead and m.race in _MURLOC_RACES])

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source, callback=on_played))
        return None


# ═══════════════════ BG34_692 Forsaken Weaver ═══════════════════

class ForsakenWeaverScript:
    """
    Natural language: [x]After you cast a Tavern
    spell, your Undead have
    +{0} Attack this game
    <i>(wherever they are)</i>.

    Formal spec:
      1. 入场注册持久监听器（owner=source）: 事件 tavern_spell_cast
         （仅 is_pool_spell 法术; 效果结算后 fire）
      2. 条件: spell.controller is source.controller（"you cast"）
      3. 触发: ApplyRaceAura(hero, UNDEAD, +num(0), 0)——叠加式永久
         种族光环（board/hand/未来获得的 Undead 全生效 "wherever they
         are"; health 分量 0 无血量抬升）; 金色 num(0)=4 数据体现
      4. 多次施放多次叠加; 多张 Weaver 光环累加

    Test: test_batch_econ_misc.py — 施放后棋盘/手牌 Undead 攻击
    +num(0)、随后新召唤的 Undead 同样生效 / Spellcraft 法术不触发 /
    敌方施放不触发 / 金色 +num(0)=4

    Params: {0}=2（金色 {0}=4）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_tavern_spell(g, spell=None, **kw):
            if spell is None or spell.controller is not source.controller:
                return
            d = g.db.get(source.card_id)
            g.run_actions(ApplyRaceAura(
                source.controller, Race.UNDEAD, d.num(0), 0))

        game.events.register(Listener(
            event=TAVERN_SPELL_CAST, owner=source,
            callback=on_tavern_spell))
        return None


# ═══════════════════ BG34_858 Air Revenant ═══════════════════

class AirRevenantScript:
    """
    Natural language: After you spend {2} Gold, cast Easterly Winds.
    <i>({0} left!)</i>
    （金色: After you spend {2} Gold, cast two Easterly Winds. ...）

    Formal spec:
      1. 入场注册持久监听器（owner=source）: 事件 gold_spent——累计
         source._gold_progress 跨回合计数 + 取模消费（阈值 = num(2)=7，
         文本 "After you spend {2} Gold" 的 {2}=script_data_num_3;
         num(0)=7 为 "(N left!)" 进度显示参数，非结算阈值）
      2. 触发 = "cast Easterly Winds" 效果直施（Runic Arcanist
         batch_soc 先例: 不经手牌/不占法术池/不计 TAVERN_SPELLS_CAST/
         不广播 tavern_spell_cast）; Easterly Winds 定义经本卡
         evolution_card_id=126909 数据链解析（BG34_444）: "After the
         Tavern is Refreshed this game, give a random minion in it
         +{0}/+{1}"（其 num(0)/num(1) 为唯一数值来源）→ 注册
         Listener(TAVERN_REFRESH, owner=hero)（"this game" 持久——
         owner=hero 不随本卡离场注销）: 每次刷新后馆内随机一只 Minion
         （rng.choice）经 tavern_spell_buff 获 +num/+num（法术 buff 统一
         出口，TAVERN_SPELL_EXTRA_* 修饰符正确叠加）; 馆内无随从落空
      3. 多次施放多次注册（光环叠加）; 金色文本 "two" → 同次触发
         cast×2
      4. BG34_444 自身 on_play 脚本未注册（法术批次缺口 73 张清单内）
         ——本实现为其效果的直施副本; 法术批次注册后无需改动本卡
         （数值/行为同源 CardDef）

    Test: test_batch_econ_misc.py — 累计 num(2) 金 → 此后每次刷新馆内
    恰一只随从 +BG34_444 num(0)/num(1) / 6 金不触发 / 分次支出累计 /
    敌方支出不触发 / 金色同次双倍（每次刷新两笔）

    Params: {2}=7（阈值=script_data_num_3; 金色同值） {0}=7（进度
            显示参数=script_data_num_1）; Easterly Winds 侧 {0}=8
            {1}=8（BG34_444 CardDef 权威）; casts=1（金色 "two"=2
            文本字面量）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        spell_id = _evolution_spell_id(game, source)
        threshold = _def(game, source).num(2)

        def cast_easterly_winds(g, caster):
            sd = g.db.get(spell_id)
            if sd is None:
                raise GameStateError(
                    f"easterly winds def {spell_id!r} missing in db")

            def on_refresh(g2, hero=None, **kw2):
                if hero is not caster:
                    return
                cands = [e for e in caster.tavern
                         if isinstance(e, Minion) and not e.dead]
                if not cands:
                    return
                m = g2.rng.choice(cands, label="easterly_winds")
                g2.run_actions(tavern_spell_buff(
                    m, atk=sd.num(0), health=sd.num(1)))

            g.events.register(Listener(
                event=TAVERN_REFRESH, owner=caster, callback=on_refresh))

        def on_gold_spent(g, hero=None, amount=0, **kw):
            if hero is not source.controller or amount <= 0:
                return
            p = getattr(source, "_gold_progress", 0) + amount
            casts = 2 if source.is_golden else 1
            while p >= threshold:
                p -= threshold
                for _ in range(casts):
                    cast_easterly_winds(g, hero)
            source._gold_progress = p

        game.events.register(Listener(
            event=GOLD_SPENT, owner=source, callback=on_gold_spent))
        return None


def register() -> list[str]:
    """注册本批次脚本（含金色 id）。

    OK 13/15（26 id）; DEFERRED 2 不注册: BG25_354(+_G) Titus
    Rivendare（DEATHRATTLE_DOUBLER 引擎缺口）、BG23_009(+_G) Lava
    Lurker（Spellcraft 永久化协议缺口）——缺口审计盯。"""
    from hsrl2.scripts.registry import register as reg

    registered: list[str] = []
    for card_id, script in (
        ("BG26_174", SoulRewinderScript),
        ("BG26_174_G", SoulRewinderScript),          # +2 Health
        ("BG26_505", ZestyShakerScript),
        ("BG26_505_G", ZestyShakerScript),           # 2 copies
        ("BG26_810", GunpowderCourierScript),
        ("BG26_810_G", GunpowderCourierScript),      # "twice"
        ("BG27_005", TimecapnHooktailScript),
        ("BG27_005_G", TimecapnHooktailScript),      # "twice"
        ("BG28_741", ChargingCzarinaScript),
        ("BG28_741_G", ChargingCzarinaScript),       # num(0)=8 自然体现
        ("BG29_816", RoaringRecruiterScript),
        ("BG29_816_G", RoaringRecruiterScript),      # num 6/2 自然体现
        ("BG31_035", GroundbreakerScript),
        ("BG31_035_G", GroundbreakerScript),         # num(1)=2 自然体现
        ("BG31_824", DualWieldCorsairScript),
        ("BG31_824_G", DualWieldCorsairScript),      # "twice"
        ("BG32_846", UnleashedManaSurgeScript),
        ("BG32_846_G", UnleashedManaSurgeScript),    # "twice"
        ("BG32_873", AshenCorruptorScript),
        ("BG32_873_G", AshenCorruptorScript),        # num 2/2 自然体现
        ("BG33_893", PrimitivePainterScript),
        ("BG33_893_G", PrimitivePainterScript),      # num 6/6 自然体现
        ("BG34_692", ForsakenWeaverScript),
        ("BG34_692_G", ForsakenWeaverScript),        # num(0)=4 自然体现
        ("BG34_858", AirRevenantScript),
        ("BG34_858_G", AirRevenantScript),           # "two" casts
    ):
        reg(card_id, script)
        registered.append(card_id)
    return registered
