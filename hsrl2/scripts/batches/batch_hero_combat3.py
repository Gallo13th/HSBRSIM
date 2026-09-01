"""批次 hero_combat3 — 战斗机制/开局随从/银行奖励类英雄技能 17 项
（作业单 2026-09-01）。

数据侦察（36.2.2 bg_hero_powers.json + hsdata/CardDefs.xml 逐卡核对）+
wiki 查证（hearthstone.wiki.gg 卡页 Wiki mechanics/Notes/Patch changes，
2026-09-01）:

  OK 14（注册键 = 技能 card_id; 支撑 token 脚本一并注册）:
    TB_BaconShop_HP_069  Illidan Stormrage — Wingmen
    BG22_HERO_305p       Onyxia — Broodmother（Avenge(4) Whelp 先攻）
    BG20_HERO_282p       Tamsin Roame — Fragrant Phylactery（嵌套亡语）
    BG25_HERO_103p       Teron Gorefiend — Rapid Reanimation（exact copy）
    BG22_HERO_002p       Drek'Thar — Frostwolf Fervor（space-in-combat）
    BG22_HERO_003p       Vanndar Stormpike — Stormpike Strength（同族）
    BG23_HERO_201p       Ozumat — Tentacular（Tentacle + sell 计数）
    BG22_HERO_007p(+p2)  Queen Azshara — Azshara's Ambition → Naga Conquest
    BG22_HERO_001p       Bru'kan — Embrace the Elements（4 元素祈咒）
    BG21_HERO_030p(+t+G) Sneed — Pilot the Shredder（开局 2/1 + 亡语 token）
    BG27_HERO_801p2      Thorim — Choose Your Champion（T7 银行 + 60 金）
    BG36_HERO_101p       Tras'tath — Void Power（T5 Dark Gift 锁至 T7）
    BG36_HERO_105p       Xavius — Feel Devastation（每 4 回合 Dark Gift）
    TB_BaconShop_HP_011  Galakrond — Galakrond's Greed（链式替换）
    BG26_HERO_102p       Inge — Major Hymn（攻/血交替 × 每回合 2 次）
    BG31_HERO_802p       Artanis — Warp Gate（2 选 1 Protoss + 买 14 张）

  DEFERRED 3（不注册——二态铁律 SOP §6b，台账见各类 docstring）:
    BG22_HERO_004p  Varden — Twice as Nice（随从级冻结粒度缺口，
                     hero_passives2 批台账结转）
    BG31_HERO_801p  Jim Raynor — Lift Off（Battlecruiser Upgrade 商店
                     子系统未实现）
    BG31_HERO_811p  Kerrigan — Spawning Pool（Zerg 解锁链/变形子系统
                     语义无官方记载）

费用口径（主线已修）: CardDef.from_json 对 card_type=10（英雄技能）
缺 cost 键时缺省 **0**（defs.py:107）——hero_actives2 批的 cost_override
规避不再需要; 本批全部走 CardDef.cost 缺省。

引擎缺口汇总（新上报主线，见各条详注）:
  1. SoC 阶段英雄技能后于随从触发: 官方 Illidan "Hero Power takes
     effect before other Start of Combat effects"（wiki 卡页 Notes;
     r/BobsTavern 1f12q9t 实证含饰品在内均后于技能）——引擎 C12 顺序
     饰品→任务奖励→随从→英雄技能为全局裁定，本批按引擎顺序实现，
     偏差记档（仅影响友方随从 SoC 先致死/移位时 Wingmen 目标选取）。
  2. 生成器未导出 SCORE_VALUE_1（Onyxia Avenge 阈值 4 的 XML 权威
     字段; 随从侧阈值走 script_data_num_1，英雄技能侧两字段分工不同）
     → 本批以文本字面量 + XML 引注实现，漂移风险由补丁数据更新流程
     覆盖。
  3. 无通用"属性变化"事件（Azshara "reaches 30 total Attack" 官方为
     实时判定）→ 本批以能改变己方棋盘总攻的全部引擎事件做检查点集
     （见 AzsharaScript docstring 完备性论证）。
  4. 随从级冻结缺失（Varden）——hero_passives2 台账 #6 结转。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import hsrl2.constants as C
from hsrl2 import darkgifts as DG
from hsrl2.actions import Buff, Discover, GainKeyword, Hit
from hsrl2.combat import execute_immediate_attack
from hsrl2.events import (
    AFTER_ATTACK,
    CARD_PLAYED,
    COMBAT_END,
    DARK_GIFT_GIVEN,
    DEATH,
    GOLD_SPENT,
    MAGNETIZED,
    MINION_BOUGHT,
    MINION_SOLD,
    START_OF_COMBAT,
    SUMMON,
    TRIPLE_COMBINED,
    TURN_START,
    Listener,
)
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# 事件名常量 events.py 未声明（引擎以字面量 fire）——hero_passives2 同款
SPELL_BOUGHT = "spell_bought"
HERO_POWER_USED = "hero_power_used"

# ── token 卡 id（无数据链字段的字面量——Firescale Hoarder/SHINY_RING_ID
#    先例; 数值/文本由 token CardDef 权威）──
WHELP_ID = "BG22_HERO_305t"          # Onyxian Whelp 1/1 Dragon
TENTACLE_ID = "BG23_HERO_201pt"      # Ozumat's Tentacle 2/2 Taunt Beast
SHREDDER_ID = "BG21_HERO_030t"       # Sneed's New Shredder 2/1 Mech
STONE_ELEMENTAL_ID = "BG22_HERO_001p_t1et"   # 1/1 Elemental（Earth 祈咒）

# Bru'kan 四元素祈咒卡（wiki Embrace the Elements Related cards 权威;
# power CardDef 无 evolution 链 → id 字面量）
ELEMENT_IDS = (
    "BG22_HERO_001p_t1",   # Earth Invocation
    "BG22_HERO_001p_t2",   # Fire Invocation
    "BG22_HERO_001p_t3",   # Water Invocation
    "BG22_HERO_001p_t4",   # Lightning Invocation
)

# Artanis 候选 Protoss（wiki Warp Gate Related cards: Colossus/Carrier/
# Immortal/Void Ray/Mothership; Interceptor(pt1t) 为 Carrier 的 token
# 不在列——db 无筛选字段 → id 字面量 + wiki 引注）
PROTOSS_IDS = (
    "BG31_HERO_802pt",     # Colossus
    "BG31_HERO_802pt1",    # Carrier
    "BG31_HERO_802pt4",    # Immortal
    "BG31_HERO_802pt5",    # Void Ray
    "BG31_HERO_802pt7",    # Mothership
)


def _power_def(game: "Game", power_id: str):
    d = game.db.get(power_id)
    if d is None:
        raise GameStateError(f"unknown hero power {power_id!r}")
    return d


def _opponent_of(game: "Game", hero: "Hero") -> Optional["Hero"]:
    """当前战斗对手（combat.run 暴露 game._active_combat——Boom-in-a-Box
    缺口的主线修复; SoC 阶段保证非 None）。"""
    ac = getattr(game, "_active_combat", None)
    if ac is None:
        return None
    a, b = ac
    return b if a is hero else a


def _random_enemy_target(game: "Game", opponent: "Hero") -> Optional[Minion]:
    """敌方攻击目标选择（RULES §4.4: 随机、嘲讽强制优先、潜行不可击——
    CombatScheduler._choose_target 同构本地实现，禁触引擎私有方法）。"""
    living = [m for m in opponent.living_minions()
              if not m.has(GameTag.STEALTH)]
    if not living:
        return None
    taunts = [m for m in living if m.taunt]
    pool = taunts if taunts else living
    return game.rng.choice(pool, label="force_attack_target")


def _exact_copy(game: "Game", hero: "Hero",
                src: Minion) -> Optional[Minion]:
    """精确副本（Zerek/Reno 先例: 同 card_id + golden 同源 + 全量 buff
    并集; 满血入场由 game.summon 保证）。"""
    copy = game.create_minion(src.card_id, controller=hero,
                              golden=src.is_golden)
    for b in src._buffs:
        copy.add_buff(b)
    return copy


def _pick_extreme(game: "Game", board: list, key, label: str,
                  highest: bool = True) -> Optional[Minion]:
    """board 上 key 最大化/最小化随从（并列 rng 任选——Diremuck 先例）。"""
    living = [m for m in board if not m.dead]
    if not living:
        return None
    best = (max if highest else min)(key(m) for m in living)
    tied = [m for m in living if key(m) == best]
    return tied[0] if len(tied) == 1 else game.rng.choice(tied, label=label)


def _grant_combat_deathrattle(game: "Game", hero: "Hero", m: Minion,
                              dr_fn) -> None:
    """战斗内授予亡语（Tamsin/Bru'kan Earth; game._chain_hook 同构——
    原生亡语先触发、追加效果后置，官方 Dark Gift 亡语附加顺序）。

    生命周期: DEATHRATTLE tag 由战斗快照恢复战后回滚（RULES §3.5）;
    _script_overrides 不在快照范围 → 由 on_bind 注册的持久 COMBAT_END
    监听恢复授予前状态（战斗中注册的监听器会被 run_combat 的监听器表
    快照复原清除——不能用于本清理）。"""
    saved = dict(m._script_overrides)
    prev_override = m._script_overrides.get("deathrattle")
    scripts_fn = (getattr(m.scripts, "deathrattle", None)
                  if m.scripts is not None else None)

    def chained(source, g, ctx):
        if prev_override is not None:
            result = (prev_override(source, g, ctx)
                      if callable(prev_override) else prev_override)
        elif scripts_fn is not None:
            result = scripts_fn(source, g, ctx)
        else:
            result = None
        dr_fn(source, g, ctx)
        return result

    m.set_script_override("deathrattle", chained)
    m.set(GameTag.DEATHRATTLE, True)
    granted = getattr(hero, "_combat_dr_grants", None)
    if granted is None:
        granted = []
        hero._combat_dr_grants = granted
    granted.append((m, saved))


def _restore_granted_deathrattles(game: "Game", hero: "Hero") -> None:
    """COMBAT_END 时恢复全部战斗内授予的亡语 override（tag 部分由引擎
    快照恢复处理）。"""
    for m, saved in getattr(hero, "_combat_dr_grants", None) or []:
        m._script_overrides.clear()
        m._script_overrides.update(saved)
    hero._combat_dr_grants = []


def _pair_gift_options(game: "Game", hero: "Hero",
                       trio: list) -> list:
    """trio 随从各配一个互不相同的合法 Dark Gift（use_dark_gift 的
    _pair_gifts 同构: 加权抽取、已用排除、无合法 gift 者落空）。"""
    if not trio:
        return []
    min_tier = min(game.db.get(cid).tech_level for cid in trio)
    used: set = set()
    options = []
    for cid in trio:
        opts = DG.eligible_gifts(
            game.db, game.db.get(cid), turn=game.turn, hero=hero,
            lobby_dragons_ok=game._lobby_dragons_ok(),
            minion_pool=game.minion_pool,
            offering_min_tier=min_tier)
        opts = [(g, w) for g, w in opts if g not in used]
        if not opts:
            continue
        gift = DG.weighted_choice(game.rng, opts)
        used.add(gift)
        options.append((cid, gift))
    return options


# ══════════════════ TB_BaconShop_HP_069 Illidan — Wingmen ══════════════════


class IllidanWingmenScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Your left-
    and right-most minions
    gain +2/+1 and attack
    immediately.

    依据（2026-09-01 查证）: wiki Battlegrounds/Wingmen——36.2.2 现行
    文本 +2/+1（CardDef 无模板参数 → 文本字面量）; wiki Illidan 卡页
    Notes: "The left-most minion will get to attack again after the Hero
    Power resolves if it survives" / "takes effect before other Start of
    Combat effects" / "Minions that can't normally attack (0-Attack
    minions) will be forced to attack"——立即攻击不消耗轮转攻击资格、
    0 攻随从也被迫攻击（承受反击）、攻击目标为常规选择（随机/嘲讽
    优先/潜行不可击）。

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: start_of_combat (hero=)
         ——hero is 绑定英雄（引擎 C12: 英雄技能 SoC 在随从之后——
         官方顺序为技能最先，偏差记引擎缺口 #1）
      2. 目标 = 去重 {board[0], board[-1]} 存活随从（单随从棋盘左右
         同一实体 → 单次 buff 单次攻击，Sulfuras 单随从边角先例）;
         各 Buff(+2/+1)（战斗内 plain buff，战后快照回滚）
      3. 依次（先最左）立即攻击: 目标 = 敌方（game._active_combat 对
         手）常规目标选择; 无有效目标（全潜行/空板）→ 攻击落空 buff
         保留; execute_immediate_attack 完整单次攻击语义（同时双向
         伤害/圣盾/剧毒/AFTER_ATTACK）——**0 攻随从照常执行**（wiki
         Notes 实证; 引擎 _execute_attack 0 攻不造成伤害但承受反击）
      4. 立即攻击不消耗轮转攻击资格（engine 游标模型天然满足——
         execute_immediate_attack 不触 EXHAUSTED 语义）

    Test: test_batch_hero_combat3.py — 双端随从各 +2/+1 且立即对敌方
    随从造成伤害 / 单随从板单次 / 空板落空 / 攻击后敌方受击

    Params: atk=2 health=1（"+2/+1" 文本字面量——CardDef 无模板参数）
    """

    passive = True
    _ATK_GAIN = 2     # "+2/+1"（wiki 36.2.2 现行文本字面量）
    _HP_GAIN = 1

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_soc(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            atk_gain = IllidanWingmenScript._ATK_GAIN
            hp_gain = IllidanWingmenScript._HP_GAIN
            targets = []
            if _owner.board:
                targets.append(_owner.board[0])
                if _owner.board[-1] is not _owner.board[0]:
                    targets.append(_owner.board[-1])
            targets = [m for m in targets if not m.dead]
            for m in targets:
                g.run_actions(Buff(m, atk=atk_gain, health=hp_gain))
            opponent = _opponent_of(g, _owner)
            if opponent is None:
                return
            for m in targets:
                if m.dead or m.zone != Zone.PLAY:
                    continue
                defender = _random_enemy_target(g, opponent)
                if defender is None:
                    return
                execute_immediate_attack(g, m, defender)

        game.events.register(Listener(
            event=START_OF_COMBAT, owner=hero, callback=on_soc))


# ══════════════════ BG22_HERO_305p Onyxia — Broodmother ══════════════════


class OnyxiaBroodmotherScript:
    """
    Natural language: [x]<b>Avenge (4):</b> Summon a
    {0}/{0} Whelp that attacks
    immediately. Improve this
    by +1/+1.

    依据（2026-09-01 查证）: wiki Battlegrounds/Broodmother——33.6 起
    "Avenge (4): Summon a 1/1 Whelp that attacks immediately. Improve
    this by +1/+1"（此前 3/1 无 improve）; mechanics: Avenge / **Force
    attack** / Passive / Summon / Upgradable。XML: TAG_SCRIPT_DATA_NUM_1
    =1（Whelp {0}/{0} 基值）、SCORE_VALUE_1=4（Avenge 阈值——英雄技能
    侧阈值字段，生成器未导出 → 字面量 + 引注，引擎缺口 #2）、AVENGE=1。

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: death (minion=)——
         minion.controller is hero 计数（RULES §6.11 任何友方死亡含
         复生死亡; 引擎随从侧 Avenge 同口径——死亡事件每实际死亡一次
         fire 一次）
      2. 计数达 4: 归零并触发——I = hero._onyxia_improve（英雄级持久
         计数，跨战斗累积）: 召唤 Onyxian Whelp（token XML 1/1 基值
         == num(0)）+ Buff 差值使属性恰为 (num(0)+I, num(0)+I)（数据
         驱动——token 基值经 db 读取，漂移免疫）; 满板 game.summon
         落空（minion_overflow，不攻击）; 召唤成功 → execute_immediate
         _attack 对随机敌方目标完整攻击（Force attack）
      3. 触发后 I += 1（"Improve this by +1/+1"——改善作用于**后续**
         召唤; +1/+1 文本字面量）; 触发与改善不受召唤落空影响
      4. 死亡处理路径内直接执行（add_buff/summon/execute_immediate_
         attack，禁 Action 入队——batch_avenge_misc 直接执行模式）

    Test: test_batch_hero_combat3.py — 4 次友方死亡后板面出现 1/1
    Whelp 且 Whelp 立即攻击敌方 / 第二次触发 2/2 / 改善跨战斗保留

    Params: avenge=4（SCORE_VALUE_1 XML 权威，未导出）/ improve=1
            （"+1/+1" 文本字面量）/ {0}=1（Whelp 基值 script_data_num_1）
    """

    passive = True
    _AVENGE_THRESHOLD = 4    # XML SCORE_VALUE_1=4（生成器未导出）
    _IMPROVE_STEP = 1        # "+1/+1"（文本字面量）

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        threshold = OnyxiaBroodmotherScript._AVENGE_THRESHOLD
        state = {"count": 0}

        def on_death(g, minion=None, **kw):
            if not isinstance(minion, Minion) or minion.controller is \
                    not hero:
                return
            state["count"] += 1
            if state["count"] < threshold:
                return
            state["count"] = 0
            d = _power_def(g, "BG22_HERO_305p")
            base = d.num(0)
            improved = getattr(hero, "_onyxia_improve", 0)
            whelp_def = g.db.get(WHELP_ID)
            if base is None or whelp_def is None:
                raise GameStateError(
                    "BG22_HERO_305p: broken whelp data chain")
            whelp = g.create_minion(WHELP_ID, controller=hero)
            delta_a = base + improved - whelp_def.atk
            delta_h = base + improved - whelp_def.health
            if delta_a > 0 or delta_h > 0:
                whelp.add_buff(Buff(atk=max(0, delta_a),
                                    health=max(0, delta_h)))
            if g.summon(hero, whelp):
                opponent = _opponent_of(g, hero)
                if opponent is not None and whelp.atk > 0:
                    defender = _random_enemy_target(g, opponent)
                    if defender is not None:
                        execute_immediate_attack(g, whelp, defender)
            hero._onyxia_improve = improved + \
                OnyxiaBroodmotherScript._IMPROVE_STEP

        game.events.register(Listener(
            event=DEATH, owner=hero, callback=on_death))


# ══════════════════ BG20_HERO_282p Tamsin — Fragrant Phylactery ══════════════════


class TamsinPhylacteryScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Give your
    lowest-Attack minion
    \"<b>Deathrattle:</b> Give your other
    minions this minion's stats.\"

    依据（2026-09-01 查证）: wiki Battlegrounds/Fragrant_Phylactery——
    33.6.2 起 "stats"（此前仅 Attack）→ 攻击力+生命双分量; mechanics:
    Passive / Start of Combat / Deathrattle-granting。官方对死亡时点
    "stats" 读法无 Notes——按 SOP §3 属性快照纪律取 **max_health**
    （当前攻击力 + 最大生命; 攻击力取亡语结算时现值，"this minion's
    stats" 触发时点读法），边角上报主线备实测。

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: start_of_combat——
         目标 = 己方存活最低攻随从（并列 rng 任选，Diremuck 同裁）
      2. 授予战斗内亡语（_grant_combat_deathrattle: 原生亡语先触发、
         追加效果后置——Dark Gift 亡语附加官方顺序）; DEATHRATTLE
         tag 战后由快照恢复回滚、override 由 COMBAT_END 持久监听恢复
      3. 亡语效果（直接执行——死亡处理路径禁 Action 入队）: 其他友方
         存活随从各 add_buff(+死者现攻击力, +死者 max_health)——战斗内
         plain buff 战后回滚（官方 SoC 授予的亡语仅本场）
      4. 复生者再次死亡时亡语照常再触发（死亡即触发语义）

    Test: test_batch_hero_combat3.py — 最低攻随从获得亡语标记 / 其
    死亡后其他随从 +其攻/+其 max_health / 战后 DEATHRATTLE 回滚 /
    原生亡语先于追加效果

    Params: 无数值参数（"this minion's stats" 为运行时聚合，无模板参数）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_soc(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            target = _pick_extreme(g, _owner.board, lambda m: m.atk,
                                   "tamsin_lowest_atk", highest=False)
            if target is None:
                return

            def dr(source, g2, ctx):
                atk_gain = source.atk
                hp_gain = source.max_health
                for m in source.controller.board:
                    if m is source or m.dead:
                        continue
                    m.add_buff(Buff(atk=atk_gain, health=hp_gain))

            _grant_combat_deathrattle(g, _owner, target, dr)

        def on_combat_end(g, hero_a=None, hero_b=None, _owner=hero, **kw):
            if hero_a is _owner or hero_b is _owner:
                _restore_granted_deathrattles(g, _owner)

        game.events.register(Listener(
            event=START_OF_COMBAT, owner=hero, callback=on_soc))
        game.events.register(Listener(
            event=COMBAT_END, owner=hero, callback=on_combat_end))


# ══════════════════ BG25_HERO_103p Teron — Rapid Reanimation ══════════════════


class TeronReanimationScript:
    """
    Natural language: [x]Choose a friendly minion.
    <b>Start of Combat:</b> Destroy it.
    When you have space,
    ___resummon an exact copy.

    依据（2026-09-01 查证）: wiki Battlegrounds/Rapid_Reanimation——
    27.6 起 "When you have space"（此前 "Once"）→ 战斗内腾位补召唤
    族（batch_soc Diremuck Evidence 同族: 官方 33.6 patch notes 同款
    句式）; mechanics: Copy / Destroy / Start of Combat / Summon;
    tags [Targeted]; 33.4 bugfix "summoned minions in the wrong place"
    （官方位置语义敏感，引擎取板尾——Summon 默认位先例）。

    Formal spec:
      1. 主动面: needs_target（友方棋盘存活随从）、cost=0（XML 无
         COST tag; defs 缺省 0）、每回合 1 次——每次使用覆写
         hero._teron_uuid（最新选择生效，可每回合重选）
      2. SoC（持久监听）: 按 uuid 定位当前棋盘目标; 已离场（售出/
         三连消耗）→ 落空; 快照 (card_id, golden, snapshot_state)
         → HEALTH=0 + check_deaths（Destroy 语义: 亡语/复生照常，
         Jailer 先例）
      3. 复活: "when you have space"——摧毁释放板位（亡语召唤可能回
         填）后有空位即召唤精确副本（_exact_copy: 同 id/golden/
         buff 并集; 满血入场）; 仍满板 → AFTER_ATTACK 战斗内腾位
         补召（Diremuck 模式; persistent 监听 + in_combat 守卫）
      4. 每场战斗至多一次（选择在下一场 SoC 重新结算; 亡语触发是
         本卡核心收益——Destroy 官方语义触发亡语）

    Test: test_batch_hero_combat3.py — 选定→战斗摧毁+亡语触发+副本
    回归（保 buff/金色）/ 满亡语回填板位时 AFTER_ATTACK 腾位补召 /
    目标已售出落空 / 每回合可重选

    Params: cost=0（raw 权威——XML 无 COST tag; defs card_type=10
            缺省 0）/ 次数=每回合 1（引擎默认）
    """

    needs_target = True

    @staticmethod
    def hero_power(hero: "Hero", game: "Game", ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target not in hero.board:
            raise GameStateError("Rapid Reanimation: bad target")
        hero._teron_uuid = target.uuid
        return None

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        state: dict = {"pending": None}

        def _try_resummon(g) -> None:
            pending = state["pending"]
            if pending is not None and not hero.board_full():
                copy = g.create_minion(pending["card_id"],
                                       controller=hero,
                                       golden=pending["golden"])
                copy.restore_state(pending["snap"])
                if g.summon(hero, copy):
                    state["pending"] = None
            # 满板: 留待 AFTER_ATTACK 腾位（in_combat 守卫在监听器内）

        def on_soc(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            uuid = getattr(_owner, "_teron_uuid", None)
            if uuid is None:
                return
            target = next((m for m in _owner.board
                           if m.uuid == uuid and not m.dead), None)
            if target is None:
                return
            state["pending"] = {
                "card_id": target.card_id,
                "golden": target.is_golden,
                "snap": target.snapshot_state(),
            }
            target.set(GameTag.HEALTH, 0)
            g.check_deaths()
            _try_resummon(g)

        def on_after_attack(g, **kw):
            if g.in_combat and state["pending"] is not None:
                _try_resummon(g)

        game.events.register(Listener(
            event=START_OF_COMBAT, owner=hero, callback=on_soc))
        game.events.register(Listener(
            event=AFTER_ATTACK, owner=hero, callback=on_after_attack))


# ══════════════════ BG22_HERO_002p / BG22_HERO_003p Drek'Thar / Vanndar ══════════════════


def _space_in_combat_bind(hero: "Hero", game: "Game",
                          pick_fn, gate_turn: Optional[int]):
    """Drek'Thar/Vanndar 共用: "When you have space in combat, summon
    a copy of your highest-X minion"（33.6 重做族; wiki mechanics Copy
    = 精确副本含附魔——Zerek 口径）。腾位检查点: SoC + 每次 AFTER_
    ATTACK（死亡波次完毕，Diremuck 模式）; while-space 连续补满
    （"when you have space" 每次腾位触发——官方 Drek'Thar/Ozumat
    板面常满的实况语义）。"""

    def _try_fill(g) -> None:
        if gate_turn is not None and g.turn < gate_turn:
            return
        while not hero.board_full():
            src = pick_fn(g, hero)
            if src is None:
                return
            if not g.summon(hero, _exact_copy(g, hero, src)):
                return

    def on_soc(g, hero=None, _owner=hero, **kw):
        if hero is _owner:
            _try_fill(g)

    def on_after_attack(g, **kw):
        if g.in_combat:
            _try_fill(g)

    game.events.register(Listener(
        event=START_OF_COMBAT, owner=hero, callback=on_soc))
    game.events.register(Listener(
        event=AFTER_ATTACK, owner=hero, callback=on_after_attack))


class DrekTharScript:
    """
    Natural language: [x]When you have space in
    combat, summon a copy of
    your highest-Attack minion.
    <i>(Unlocks on Turn 7.)</i>

    依据（2026-09-01 查证）: wiki Battlegrounds/Frostwolf_Fervor——
    33.6 重做为现文本（此前 Avenge(2) +1 Attack）; mechanics: Copy /
    Passive / Summon; num(0)=1（每腾位召唤数）; "Unlocks on Turn 7"
    （Turn 门槛——对照 "at Tier X" 酒馆等级措辞，actives2 Alexstrasza
    Evidence 同裁）。

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: start_of_combat（turn
         ≥ 7 门槛）+ after_attack（in_combat 守卫）双检查点
      2. 触发: while-空位循环——最高攻存活随从（并列 rng）精确副本
         （_exact_copy: buff 并集/golden 同源; 战斗中快照外的召唤物
         战后随棋盘恢复消失）上板; 空板无源落空
      3. 副本含战斗内已获 buff（"a copy" 无 "plain" 限定——wiki Copy
         机制页精确副本口径）

    Test: test_batch_hero_combat3.py — turn 6 战斗不触发 / turn 7 空
    位被最高攻副本填满（含 buff）/ 腾位（亡语留空）后补召

    Params: turn=7（"Unlocks on Turn 7" 文本字面量）/ {0}=1（每腾位
            召唤数 script_data_num_1）
    """

    passive = True
    _UNLOCK_TURN = 7     # "Unlocks on Turn 7"（文本字面量）

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def pick(g, owner):
            return _pick_extreme(g, owner.board, lambda m: m.atk,
                                 "frostwolf_highest_atk")

        _space_in_combat_bind(hero, game, pick,
                              DrekTharScript._UNLOCK_TURN)


class VanndarScript:
    """
    Natural language: [x]When you have space in
    combat, summon a copy of
    your highest-Health minion.
    <i>(Unlocks on Turn 7.)</i>

    依据（2026-09-01 查证）: wiki Battlegrounds/Stormpike_Strength——
    Drek'Thar 同族镜像（最高血分量）; mechanics: Copy / Passive /
    Summon; num(0)=1。

    Formal spec: 同 DrekTharScript，选取键 = max_health（SOP §3 属性
    快照纪律——战斗中受伤随从按最大生命排序）。

    Test: test_batch_hero_combat3.py — 最高 max_health 随从副本填位
    （攻低血高者优先于攻高血低者）

    Params: turn=7（文本字面量）/ {0}=1（script_data_num_1）
    """

    passive = True
    _UNLOCK_TURN = 7     # "Unlocks on Turn 7"（文本字面量）

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def pick(g, owner):
            return _pick_extreme(g, owner.board, lambda m: m.max_health,
                                 "stormpike_highest_hp")

        _space_in_combat_bind(hero, game, pick,
                              VanndarScript._UNLOCK_TURN)


# ══════════════════ BG23_HERO_201p Ozumat — Tentacular ══════════════════


class OzumatScript:
    """
    Natural language: [x]When you have space in
    combat, summon a @/@
    Tentacle with <b>Taunt</b>. <i>(Gains
    +1/+1 after you sell a minion!)</i>

    依据（2026-09-01 查证）: wiki Battlegrounds/Tentacular——30.4.3
    起 "When you have space in combat"（此前 SoC 一次性）+ 2/2 Tentacle
    （30.4.3 1/1→2/2; 36.2.2 现行）; token BG23_HERO_201pt XML 2/2
    Taunt Beast（pt2..pt6 为皮肤变体同值）; num(0)=2（Tentacle 基值，
    @/@ 双占位同参——wiki 渲染 "2/2" 实证）、num(1)=1（"+1/+1 after
    you sell" 增量）。

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: minion_sold（controller
         is hero，含卖 Tentacle 自身）→ hero._ozumat_bonus += num(1)
         （攻/血双分量同值——文本 "+1/+1"; 跨战斗持久）
      2. 腾位召唤（SoC + AFTER_ATTACK 双检查点 while-空位，_space_
         in_combat_bind 同构）: Tentacle 副本 = create token（XML 2/2
         Taunt 基值）+ Buff 差值至 (num(0)+B, num(0)+B)，B = 已累积
         出售次数 × num(1)（数据驱动——token 基值经 db 读取）
      3. 无 Turn/Tier 门槛（30.4.3 起战斗开始即触发）

    Test: test_batch_hero_combat3.py — 空位被 2/2 Taunt Tentacle 填
    满 / 卖 2 只后下一场战斗 Tentacle 4/4 / 卖出计数含 Tentacle 自身

    Params: {0}=2（Tentacle 基值 script_data_num_1）/ {1}=1（每出售
            增量 script_data_num_2）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        d = _power_def(game, "BG23_HERO_201p")

        def on_sold(g, minion=None, **kw):
            if not isinstance(minion, Minion) or minion.controller is \
                    not hero:
                return
            hero._ozumat_bonus = getattr(hero, "_ozumat_bonus", 0) + \
                (d.num(1) or 0)

        def pick(g, owner):
            living = [m for m in owner.board if not m.dead]
            return living[0] if living else None

        def _try_fill(g) -> None:
            improved = getattr(hero, "_ozumat_bonus", 0)
            t_def = g.db.get(TENTACLE_ID)
            target_stat = (d.num(0) or 0) + improved
            while not hero.board_full():
                src = pick(g, hero)
                if src is None:
                    return
                tentacle = g.create_minion(TENTACLE_ID, controller=hero)
                delta = target_stat - t_def.atk
                delta_h = target_stat - t_def.health
                if delta > 0 or delta_h > 0:
                    tentacle.add_buff(Buff(atk=max(0, delta),
                                           health=max(0, delta_h)))
                if not g.summon(hero, tentacle):
                    return

        def on_soc(g, hero=None, _owner=hero, **kw):
            if hero is _owner:
                _try_fill(g)

        def on_after_attack(g, **kw):
            if g.in_combat:
                _try_fill(g)

        game.events.register(Listener(
            event=MINION_SOLD, owner=hero, callback=on_sold))
        game.events.register(Listener(
            event=START_OF_COMBAT, owner=hero, callback=on_soc))
        game.events.register(Listener(
            event=AFTER_ATTACK, owner=hero, callback=on_after_attack))


# ══════════════════ BG22_HERO_007p(+p2) Queen Azshara ══════════════════


class AzsharaScript:
    """
    Natural language: [x]When your warband
    reaches 30 total Attack,
    begin your Naga Conquest.

    依据（2026-09-01 查证）: wiki Battlegrounds/Azshara's_Ambition——
    31.2.2 起 30（num(1)=script_data_num_2 权威）; mechanics: Passive
    + **Replace Hero Power**; BACON_EVOLUTION_CARD_ID=80007 → Naga
    Conquest（BG22_HERO_007p2 "Discover a Naga"，cost 1）。

    Formal spec:
      1. on_bind 注册持久检查点监听器（owner=hero）于**能改变己方棋盘
         总攻的全部引擎事件**: minion_bought / card_played（法术+随从
         打出 buff 面）/ minion_sold / summon（板面组成）/ death /
         turn_end（先于 EoT 效果——EoT 增益由 combat_end 检查点收口）/
         combat_end（战斗内永久化增益 + EoT 增益）/ magnetized /
         dark_gift_given / triple_combined / hero_power_used /
         spell_bought（字面量 fire）。完备性: 引擎中总攻上升路径 =
         buff 写入（源自动作/购买/打出/技能/磁力/gift/三连）+ 新随从
         入板（summon/bought/triple）——全覆盖; 战斗内变化经 combat_end
         收口（可用性视角等价官方实时变身: Naga Conquest 的使用窗口
         是招募期，变身时点差异仅影响显示——记档）
      2. 检查: Σ 存活随从 atk ≥ num(1) → 一次性 replace_hero_power
         （evolution_card_id 数据链解析，零硬编码）+ done 标记
      3. 30 为**总攻**阈值（攻的和，非攻血合计——"30 total Attack"）

    Test: test_batch_hero_combat3.py — 29 攻不变 / 买 buff 后达 30 →
    技能替换为 Naga Conquest / 替换后可用（Discover a Naga 占池）/
    EoT 增益经 combat_end 收口触发

    Params: {1}=30（script_data_num_2——总攻阈值）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        d = _power_def(game, "BG22_HERO_007p")
        threshold = d.num(1)
        if threshold is None or d.evolution_card_id is None:
            raise GameStateError(
                "BG22_HERO_007p: broken data chain "
                f"(num1={threshold}, evo={d.evolution_card_id})")
        conquest_def = game.db.by_dbf(d.evolution_card_id)
        if conquest_def is None:
            raise GameStateError(
                f"BG22_HERO_007p: evolution dbf {d.evolution_card_id} "
                "not in db")
        state = {"done": False}

        def _check(g, **kw):
            if state["done"]:
                return
            total = sum(m.atk for m in hero.board if not m.dead)
            if total < threshold:
                return
            state["done"] = True
            g.replace_hero_power(hero, conquest_def.id)

        for ev in (MINION_BOUGHT, CARD_PLAYED, MINION_SOLD, SUMMON, DEATH,
                   "turn_end", COMBAT_END, MAGNETIZED, DARK_GIFT_GIVEN,
                   TRIPLE_COMBINED, HERO_POWER_USED, SPELL_BOUGHT):
            game.events.register(Listener(
                event=ev, owner=hero, callback=_check))


class NagaConquestScript:
    """
    Natural language: [x]<b>Discover</b> a Naga.

    依据: wiki Battlegrounds/Azshara's_Ambition Related cards → Naga
    Conquest（BG22_HERO_007p2，cost=1 raw 权威; Azshara 变身终态技能，
    actives2 替换技能族——Sulfuras 同构独立注册）。

    Formal spec:
      1. 主动: Discover(hero, race=NAGA)——池感知（剩余量/active_races/
         ALL 三姓匹配），选中占池（RULES §2.3）
      2. cost=1（raw cost）; 每回合 1 次（引擎默认; 官方无限次每回合
         一次的常规技能）

    Test: test_batch_hero_combat3.py — 变身后使用发现 Naga（含 ALL）
    入手占池 / 费用 1 金

    Params: cost=1（raw cost; "a Naga" 裸种族无数值占位符）
    """

    @staticmethod
    def hero_power(hero: "Hero", game: "Game", ctx):
        return Discover(hero, race=Race.NAGA)


# ══════════════════ BG22_HERO_001p Bru'kan — Embrace the Elements ══════════════════


class BrukanScript:
    """
    Natural language: [x]Choose an Element.
    <b>Start of Combat:</b> Call
    upon that Element.

    依据（2026-09-01 查证）: wiki Battlegrounds/Embrace_the_Elements +
    四祈咒卡页（Earth/Fire/Water/Lightning Invocation，BG22_HERO_001p
    _t1..t4）——文本无数值占位符（各祈咒数值为文本字面量）; 无 "Once
    per game" 限定（对照 Kragg "Once per game" 显式措辞）→ 主动技能
    每回合 1 次、每次使用可重选元素、最新选择持续生效至改选。

    Formal spec:
      1. 主动面（cost=0 raw 缺省）: hero_power 产生 PendingChoice
         (kind="choose_element"，options=四祈咒 card id——RL 动作
         空间) → resolve 存 hero._brukan_element
      2. SoC（持久监听）: 按 _brukan_element 分发——
         - Earth（t1）: 4 只随机不同友方随从获战斗内亡语"召唤 1/1
           Stone Elemental"（_grant_combat_deathrattle; 战后回滚同
           Tamsin; token BG22_HERO_001p_t1et XML 1/1 Elemental）
         - Fire（t2）: 最左随从攻击力翻倍（Buff(atk=现值) 战斗内）
         - Water（t3）: 最右随从获得圣盾+嘲讽（战斗内 tag，战后回滚）
         - Lightning（t4）: 对 5 个随机不同敌方随从各造成 1 伤害
           （Hit; 敌方经 game._active_combat 定位）
      3. 未选择过元素时 SoC 落空（"that Element" 未定义）

    Test: test_batch_hero_combat3.py — 选 Fire 后战斗中最左攻翻倍 /
    选 Water 最右得圣盾+嘲讽 / 选 Lightning 敌方恰 5 个各受 1 伤 /
    选 Earth 4 随从获亡语且死亡召唤 1/1 / 重选后下一场切换

    Params: earth_count=4（"4 random friendly" 文本字面量）/
            lightning_count=5 lightning_damage=1（"1 damage to 5
            random enemy" 文本字面量）/ cost=0（raw 缺省）
    """

    _EARTH_COUNT = 4
    _LIGHTNING_COUNT = 5
    _LIGHTNING_DAMAGE = 1

    @staticmethod
    def hero_power(hero: "Hero", game: "Game", ctx):
        def resolve(pick):
            hero._brukan_element = pick

        game.pending_choices.append(PendingChoice(
            hero, list(ELEMENT_IDS), "choose_element",
            resolve_callback=resolve))
        return None

    @staticmethod
    def _earth(g: "Game", hero: "Hero") -> None:
        living = [m for m in hero.board if not m.dead]
        k = min(BrukanScript._EARTH_COUNT, len(living))
        picks = (list(living) if k == len(living)
                 else g.rng.sample(living, k, label="brukan_earth"))

        def dr(source, g2, ctx):
            pos = (ctx or {}).get("position")
            elem = g2.create_minion(STONE_ELEMENTAL_ID,
                                    controller=source.controller)
            g2.summon(source.controller, elem, pos)

        for m in picks:
            _grant_combat_deathrattle(g, hero, m, dr)

    @staticmethod
    def _fire(g: "Game", hero: "Hero") -> None:
        if hero.board:
            left = hero.board[0]
            if not left.dead:
                g.run_actions(Buff(left, atk=left.atk, health=0))

    @staticmethod
    def _water(g: "Game", hero: "Hero") -> None:
        if hero.board:
            right = hero.board[-1]
            if not right.dead:
                g.run_actions([GainKeyword(right, GameTag.DIVINE_SHIELD),
                               GainKeyword(right, GameTag.TAUNT)])

    @staticmethod
    def _lightning(g: "Game", hero: "Hero") -> None:
        opponent = _opponent_of(g, hero)
        if opponent is None:
            return
        living = [m for m in opponent.living_minions()]
        k = min(BrukanScript._LIGHTNING_COUNT, len(living))
        if k <= 0:
            return
        picks = (list(living) if k == len(living)
                 else g.rng.sample(living, k, label="brukan_lightning"))
        g.run_actions([Hit(m, BrukanScript._LIGHTNING_DAMAGE)
                       for m in picks if not m.dead])

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        dispatch = {
            ELEMENT_IDS[0]: BrukanScript._earth,
            ELEMENT_IDS[1]: BrukanScript._fire,
            ELEMENT_IDS[2]: BrukanScript._water,
            ELEMENT_IDS[3]: BrukanScript._lightning,
        }

        def on_soc(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            element = getattr(_owner, "_brukan_element", None)
            fn = dispatch.get(element)
            if fn is not None:
                fn(g, _owner)

        def on_combat_end(g, hero_a=None, hero_b=None, _owner=hero, **kw):
            if hero_a is _owner or hero_b is _owner:
                _restore_granted_deathrattles(g, _owner)

        game.events.register(Listener(
            event=START_OF_COMBAT, owner=hero, callback=on_soc))
        game.events.register(Listener(
            event=COMBAT_END, owner=hero, callback=on_combat_end))


# ══════════════════ BG21_HERO_030p Sneed — Pilot the Shredder ══════════════════


class SneedScript:
    """
    Natural language: [x]Start the game with a 2/1
    _Shredder that summons a
    minion from your hand and
    gives it <b>Divine Shield</b>.

    依据（2026-09-01 查证）: wiki Battlegrounds/Pilot_the_Shredder——
    33.6.2 起现文本（被动; HIDE_COST）; token Sneed's New Shredder
    （BG21_HERO_030t，XML 2/1 Mech T1）卡面细化 "summons" 语义:
    "<b>Deathrattle:</b> Summon the highest-Health minion from your
    hand and give it <b>Divine Shield</b> for this combat."——
    mechanics: **Temporary summon**（wiki Temporary summon 机制页:
    "copied from the hand for that Combat only, while the original
    copy remains in the hand"——Deathly Striker 同口径）+ Put into
    battlefield; 金色版（_G，4/2）"the 2 highest-Health minions"。

    Formal spec:
      1. on_bind（开局接线，start_game 于首回合开始前）: 召唤 2/1
         Sneed's New Shredder（token XML 数值权威; 非池卡不占池）
      2. token 亡语（直接执行——死亡处理路径）: 手牌最高 max_health
         随从（并列 rng）**副本**召唤（create + restore_state 保
         buff/golden——Diremuck 战斗副本先例; 原件留手）+ 圣盾
         （战斗内 tag，战后回滚; "for this combat"）; 金色 token
         依序取 2 只不同最高血; 手牌无随从 → 落空
      3. 亡语召唤位 = ctx["position"] 起（Striker 同构）

    Test: test_batch_hero_combat3.py — 开局板面 2/1 Shredder / 死亡
    后手牌最高血随从的副本（保 buff）上板+圣盾且原件留手 / 手牌空
    落空 / 金色 token 召 2 只

    Params: token 2/1 与金色 4/2 由 token CardDef 权威（非本卡模板
            参数）; 金色计数 2 为金色文本字面量
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        shredder = game.create_minion(SHREDDER_ID, controller=hero)
        game.summon(hero, shredder)


class SneedsNewShredderScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Summon the
    highest-Health minion from
    your hand and give it <b>Divine
    ____Shield</b> for this combat.__
    （金色 BG21_HERO_030t_G: ... the 2 highest-Health minions ...）

    Formal spec: 见 SneedScript（token 支撑脚本）。金色 = 2 只不同
    最高血（is_golden 分支计数 2——金色文本字面量）。

    Test: test_batch_hero_combat3.py — 同 SneedScript token 面

    Params: 金色计数 2（金色文本 "the 2 highest-Health" 字面量）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        n = 2 if source.is_golden else 1
        pos = (ctx or {}).get("position")
        picked = []
        for _ in range(n):
            cands = [c for c in hero.hand
                     if isinstance(c, Minion) and c not in picked
                     and not c.dead]
            if not cands:
                break
            top = max(c.max_health for c in cands)
            tied = [c for c in cands if c.max_health == top]
            origin = tied[0] if len(tied) == 1 \
                else game.rng.choice(tied, label="shredder_hand_pick")
            picked.append(origin)
            copy = game.create_minion(origin.card_id, controller=hero,
                                      golden=origin.is_golden)
            copy.restore_state(origin.snapshot_state())
            copy.set(GameTag.DIVINE_SHIELD, True)
            game.summon(hero, copy, pos)
            if pos is not None:
                pos += 1
        return None


# ══════════════════ BG27_HERO_801p2 Thorim — Choose Your Champion ══════════════════


class ThorimScript:
    """
    Natural language: [x]<b><b>Passive</b>.</b> At the start of the
    game, <b>Discover</b> a Tier 7
    minion to get after you
    __spend 60 Gold. <i>({0} left!)</i>

    依据（2026-09-01 查证）: wiki Battlegrounds/Choose_Your_Champion
    （现文本 60 金——num(0)=60 权威; 此前 65）; mechanics: Discover /
    Passive; T7 池随从 12 只在册（data bg_pool_minions tech_level=7;
    C.TAVERN_MAX_TIER=6 "Tier 7 仅特殊效果可达"——常规酒馆抽取/
    Discover 不触达，本技能即该"特殊效果"）; r/BobsTavern 165igfd:
    花费计数跨技能替换持续（官方行为实证）。

    Formal spec:
      1. on_bind: T7 候选 = 池内 tech_level==7、available>0、
         active_races 通过; 无候选 → 落空（池无 T7——诚实缺省）;
         sample ≤3 → PendingChoice("discover_minion") → pick 即
         minion_pool.acquire（**预订**——Discover 选中占池标准口径;
         授予时不再重复扣池）存 hero._thorim_champion
      2. 持久监听 gold_spent (amount=, hero=): hero is 绑定者 →
         累计 ≥ num(0)=60 且已有 champion 且未授予 → create_minion
         + pending_hand_add（入组队手牌，一次完成）
      3. 银行不在手牌（未授予前不可打出/不可见——"to get after"）

    Test: test_batch_hero_combat3.py — 开局三选一全为 T7 / 选中即
    占池 / 花 59 金不授予 / 第 60 金授予入手 / 无 champion 时不授予

    Params: {0}=60（script_data_num_1——花费阈值）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        d = _power_def(game, "BG27_HERO_801p2")
        threshold = d.num(0)
        if threshold is None:
            raise GameStateError("BG27_HERO_801p2: missing template "
                                 "params")
        pool = game.minion_pool
        cands = [x.id for x in game.db.pool_minions()
                 if x.tech_level == 7 and pool.available(x.id) > 0
                 and (pool.active_races is None
                      or x.race in (Race.NONE, Race.ALL)
                      or x.race in pool.active_races)]
        state = {"spent": 0, "champion": None, "granted": False}

        if cands:
            k = min(3, len(cands))
            options = game.rng.sample(cands, k,
                                      label="thorim_champion_options") \
                if k < len(cands) else list(cands)

            def resolve(pick_id):
                if not game.minion_pool.acquire(pick_id):
                    raise GameStateError(
                        f"Thorim pick {pick_id} no longer available")
                state["champion"] = pick_id

            game.pending_choices.append(PendingChoice(
                hero, options, "discover_minion",
                resolve_callback=resolve))

        def on_gold_spent(g, amount=0, hero=None, _owner=hero, **kw):
            if hero is not _owner or amount <= 0:
                return
            state["spent"] += amount
            if (state["granted"] or state["champion"] is None
                    or state["spent"] < threshold):
                return
            state["granted"] = True
            m = g.create_minion(state["champion"], controller=_owner)
            g.pending_hand_add(_owner, m)

        game.events.register(Listener(
            event=GOLD_SPENT, owner=hero, callback=on_gold_spent))


# ══════════════════ BG36_HERO_101p Tras'tath — Void Power ══════════════════


class TrastathScript:
    """
    Natural language: [x]At the start of the game,
    <b>Discover</b> a Tier 5 minion
    with a <b>Dark Gift</b>. It unlocks
    on Turn 7. <i>({0} |4(turn, turns) left!)</i>

    依据（2026-09-01 查证）: wiki Battlegrounds/Void_Power（36.2.0
    新增）——mechanics: Discover / Generate / **Lock in hand** / Start
    of Game; num(0)=6（"6 turns left" → Turn 7 解锁 = num(0)+1）;
    tags DISCOVER / DARK_GIFT / USE_DISCOVER_VISUALS。

    Formal spec:
      1. on_bind: T5 候选（池感知）sample ≤3 → _pair_gift_options 各配
         不同合法 Dark Gift（use_dark_gift 同构加权抽取）→ PendingChoice
         (kind="dark_gift"，options=(card_id, gift_id)) → pick:
         acquire + create_minion + apply_dark_gift + **LOCKED_IN_HAND**
         （tag 1068——引擎 play_minion/play_spell 双闸口）+ 手牌
      2. 解锁: 持久 turn_start 监听——game.turn ≥ num(0)+1 时清除该
         随从 LOCKED_IN_HAND（uuid 记账; 之后回合幂等）
      3. 满手: pending_hand_add 排队（锁清除时点与入手机制正交）

    Test: test_batch_hero_combat3.py — 开局三选一全 T5 且各带不同
    gift / 选中入手含 gift 效果且锁定不可打出 / Turn 7 解锁可打出

    Params: {0}=6（script_data_num_1——解锁剩余回合数; 解锁回合 =
            num(0)+1）/ tier=5（"Tier 5" 文本字面量）
    """

    passive = True
    _TIER = 5     # "Tier 5"（文本字面量）

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        d = _power_def(game, "BG36_HERO_101p")
        unlock_turn = (d.num(0) or 0) + 1
        pool = game.minion_pool
        cands = [x.id for x in game.db.pool_minions()
                 if x.tech_level == TrastathScript._TIER
                 and pool.available(x.id) > 0
                 and (pool.active_races is None
                      or x.race in (Race.NONE, Race.ALL)
                      or x.race in pool.active_races)]
        if not cands:
            return
        k = min(3, len(cands))
        trio = game.rng.sample(cands, k,
                               label="trastath_trio") \
            if k < len(cands) else list(cands)
        options = _pair_gift_options(game, hero, trio)
        if not options:
            return

        def resolve(pick):
            card_id, gift_id = pick
            if not game.minion_pool.acquire(card_id):
                raise GameStateError(
                    f"Void Power pick {card_id} no longer available")
            m = game.create_minion(card_id, controller=hero)
            game.apply_dark_gift(m, gift_id)
            m.set(GameTag.LOCKED_IN_HAND, True)
            game.pending_hand_add(hero, m)
            hero._trastath_locked_uuid = m.uuid

        game.pending_choices.append(PendingChoice(
            hero, options, "dark_gift", resolve_callback=resolve))

        def on_turn_start(g, turn=0, hero=None, _owner=hero, **kw):
            if hero is not _owner or turn < unlock_turn:
                return
            uuid = getattr(_owner, "_trastath_locked_uuid", None)
            if uuid is None:
                return
            for card in _owner.hand:
                if card.uuid == uuid:
                    card.clear(GameTag.LOCKED_IN_HAND)
            _owner._trastath_locked_uuid = None

        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))


# ══════════════════ BG36_HERO_105p Xavius — Feel Devastation ══════════════════


class XaviusScript:
    """
    Natural language: [x]Every 4 turns, <b>Discover</b> a
    minion with a <b>Dark Gift</b>.
    <i>({0} turns left!)</i>

    依据（2026-09-01 查证）: wiki Battlegrounds/Feel_Devastation
    （36.2.0 新增）——mechanics: Discover / Generate / Triggered
    effect; num(0)=3（"3 turns left" → 周期 4 = num(0)+1: Turn 4/
    8/12… 触发）; tags DISCOVER / DARK_GIFT / BACON_TRIGGER_UPBEAT
    （回合开始触发族）。

    Formal spec:
      1. on_bind 持久监听 turn_start (turn=, hero=): hero is 绑定者
         且 turn > 0 且 turn % (num(0)+1) == 0 → 触发（Rock Master
         Voone 周期同构——事件 turn 参数权威无计数器漂移）
      2. 触发: DG.eligible_minions（S14 Dark Gift 提供资格全集——
         tier 曲线/池剩余/激活种族/黑名单; "a minion with a Dark
         Gift" 与 use_dark_gift 同一资格模型）sample ≤3 →
         _pair_gift_options 配对不同 gift → PendingChoice("dark_
         gift") → pick: acquire + create + apply_dark_gift +
         pending_hand_add（**无锁**——对照 Tras'tath 显式 "unlocks"
         措辞，本卡无锁定语义）
      3. 池耗尽/无合法配对 → 该次落空（官方效果落空行为）

    Test: test_batch_hero_combat3.py — turn 3 不触发 / turn 4 三选
    一各带不同 gift / 选中入手含 gift 且不锁定 / turn 8 再触发

    Params: {0}=3（script_data_num_1——周期余数; 周期 = num(0)+1）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        d = _power_def(game, "BG36_HERO_105p")
        period = (d.num(0) or 0) + 1

        def on_turn_start(g, turn=0, hero=None, _owner=hero, **kw):
            if hero is not _owner or turn <= 0 or turn % period != 0:
                return
            cands = DG.eligible_minions(g.db, g.minion_pool, _owner,
                                        g.turn)
            if not cands:
                return
            k = min(3, len(cands))
            trio = g.rng.sample(cands, k,
                                label="xavius_trio") \
                if k < len(cands) else list(cands)
            options = _pair_gift_options(g, _owner, trio)
            if not options:
                return

            def resolve(pick):
                card_id, gift_id = pick
                if not g.minion_pool.acquire(card_id):
                    raise GameStateError(
                        f"Feel Devastation pick {card_id} no longer "
                        "available")
                m = g.create_minion(card_id, controller=_owner)
                g.apply_dark_gift(m, gift_id)
                g.pending_hand_add(_owner, m)

            g.pending_choices.append(PendingChoice(
                _owner, options, "dark_gift", resolve_callback=resolve))

        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))


# ══════════════════ TB_BaconShop_HP_011 Galakrond — Galakrond's Greed ══════════════════


class GalakrondScript:
    """
    Natural language: [x]Choose a minion in the
    Tavern. Then choose a
    higher Tier minion to
    replace it.

    依据（2026-09-01 查证）: wiki Battlegrounds/Galakrond's_Greed——
    30.6.2 去 "Discover" 关键词为措辞简化（27.0-30.6.2 文本即
    "Discover a higher Tier minion"; 21.0 bugfix "missing a tooltip
    for Discover" 实证选择面板为 Discover 形态）→ 第二步按 Discover
    三选一实现; tags [Targeted]; cost=1（XML COST=1 权威）。

    Formal spec:
      1. 主动面（cost=1）: available = 馆内有随从; hero_power 产生
         第一个 PendingChoice(kind="galakrond_tavern"，options=馆内
         Minion 实体——RL 动作空间)
      2. resolve(第一选): 候选 = 池内 tech_level > 所选随从 tier 且
         ≤ C.TAVERN_MAX_TIER（T7 为特殊效果专属——Thorim 口径，常规
         获取不触达）+ 池剩余/激活种族过滤; 无候选 → 整体落空（旧
         随从保留）; sample ≤3 → 第二个 PendingChoice("galakrond_
         replacement")
      3. resolve(第二选): 池记账——旧随从移出酒馆回池（release 1，
         Tess 镜像口径）→ 新随从 acquire 占池 → create_minion 入馆
         （zone=TAVERN，原槽位插入）
      4. 两步选择经 pending_choices 队列化（链式 PendingChoice——
         resolve 内追加，v1 单槽覆盖 bug 修复语义）

    Test: test_batch_hero_combat3.py — 第一选馆内随从 / 第二选全为
    更高 tier / 替换后旧回池新占池且槽位保留 / 无更高 tier 候选时
    旧随从保留

    Params: cost=1（raw cost）/ options=3（Discover 三选一惯例——
            wiki patch history 实证）
    """

    @staticmethod
    def available(hero, game):
        return any(isinstance(e, Minion) for e in hero.tavern)

    @staticmethod
    def hero_power(hero: "Hero", game: "Game", ctx):
        options = [e for e in hero.tavern if isinstance(e, Minion)]

        def resolve_first(pick):
            if pick not in hero.tavern:
                return   # 选择挂起期间被买走——落空
            pool = game.minion_pool
            cands = [x.id for x in game.db.pool_minions()
                     if pick.tech_level < x.tech_level
                     <= C.TAVERN_MAX_TIER
                     and pool.available(x.id) > 0
                     and (pool.active_races is None
                          or x.race in (Race.NONE, Race.ALL)
                          or x.race in pool.active_races)]
            if not cands:
                return
            k = min(3, len(cands))
            repl = game.rng.sample(cands, k,
                                   label="galakrond_replacement") \
                if k < len(cands) else list(cands)

            def resolve_second(new_id):
                if pick not in hero.tavern:
                    return
                idx = hero.tavern.index(pick)
                hero.tavern.remove(pick)
                game.minion_pool.release(pick.card_id, 1)
                if not game.minion_pool.acquire(new_id):
                    raise GameStateError(
                        f"Galakrond acquire failed for {new_id}")
                m = game.create_minion(new_id, controller=hero)
                m.zone = Zone.TAVERN
                hero.tavern.insert(idx, m)

            game.pending_choices.append(PendingChoice(
                hero, repl, "discover_minion",
                resolve_callback=resolve_second))

        game.pending_choices.append(PendingChoice(
            hero, options, "galakrond_tavern",
            resolve_callback=resolve_first))
        return None


# ══════════════════ BG26_HERO_102p Inge — Major Hymn ══════════════════


class IngeScript:
    """
    Natural language: [x]Twice per turn, give a
    minion Attack equal to
    your Tier. <i>(Swaps to
    Health next turn!)</i>

    依据（2026-09-01 查证）: wiki Battlegrounds/Major_Hymn——36.2.2
    起 "Twice per turn"（36.2.2 patch notes 官方改文; 此前每回合
    1 次）; wiki mechanics: Increment attack; tags [Targeted] /
    Tavern Tier-related; 交替锚点: 印刷面即 Attack 面（卡牌默认态，
    "Swaps to Health **next** turn" 以当前 Attack 面为参照）→ 回合
    奇偶交替: 奇数回合 Attack / 偶数回合 Health（Minor Hymn
    BG26_HERO_102p2 为 Health 面 Related card 实证双面结构）;
    数值 = 当前酒馆 tier（运行时读，无模板参数）。

    Formal spec:
      1. 主动面: uses_per_turn=2（"Twice per turn"）、needs_target
         （友方棋盘）、cost=0（raw cost 0）
      2. hero_power: amount = hero.tavern_tier; game.turn 奇数 →
         Buff(target, atk=amount) / 偶数 → Buff(target, health=
         amount)（永久 buff——回合内招募期增益）
      3. 交替锚点 game.turn 奇偶（开局 turn 1 = Attack 面）

    Test: test_batch_hero_combat3.py — 回合 1 两次使用分别 +tier 攻 /
    回合 2 转 +tier 血 / 每回合第 3 次拒绝 / tier 提升后数值随动

    Params: uses=2（"Twice per turn" 文本字面量）/ cost=0（raw
            cost）/ 数值 = 运行时 tier（无数值占位符）
    """

    uses_per_turn = 2
    needs_target = True

    @staticmethod
    def hero_power(hero: "Hero", game: "Game", ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target not in hero.board:
            raise GameStateError("Major Hymn: bad target")
        amount = hero.tavern_tier
        if game.turn % 2 == 1:
            return Buff(target, atk=amount, health=0)
        return Buff(target, atk=0, health=amount)


# ══════════════════ BG31_HERO_802p Artanis — Warp Gate ══════════════════


class ArtanisScript:
    """
    Natural language: [x]At the start of the game,
    choose from 2 Protoss
    minions to get after you
    buy 14 cards. <i>({0} left!)</i>

    依据（2026-09-01 查证）: wiki Battlegrounds/Warp_Gate（31.6.0
    新增; 31.6.2 16→14）——mechanics: Generate + Passive; Related
    cards = 5 只 Protoss（Colossus/Carrier/Immortal/Void Ray/
    Mothership，BG31_HERO_802pt/pt1/pt4/pt5/pt7——db 无种族标记 →
    id 字面量 + wiki 引注）; num(0)=14（购卡阈值）; "buy 14 cards" =
    任何购买（随从+酒馆法术——Ragnaros BUY, INSECT! "12 cards"
    wiki Buying-related 同口径）。

    Formal spec:
      1. on_bind: rng.sample(PROTOSS_IDS, 2) → PendingChoice(kind=
         "choose_protoss") → pick 存 hero._artanis_champion
      2. 持久监听 minion_bought（controller is hero）+ spell_bought
         （hero is 绑定者）: 计数 ≥ num(0)=14 且未授予 → create_
         minion + pending_hand_add（token 非池卡零池操作——E.T.C.
         Buddy 同口径）
      3. Protoss 自身效果脚本（Rally/Avenge/SoC）不在本批 17 卡
         范围（缺口审计盯）

    Test: test_batch_hero_combat3.py — 开局恰 2 个 Protoss 选项 /
    买 13 张不授予 / 第 14 张（随从+法术混合计数）授予选中卡入手 /
    不占池

    Params: {0}=14（script_data_num_1——购卡阈值）/ options=2（"from
            2 Protoss" 文本字面量）
    """

    passive = True
    _OPTION_COUNT = 2     # "choose from 2 Protoss"（文本字面量）

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        d = _power_def(game, "BG31_HERO_802p")
        threshold = d.num(0)
        if threshold is None:
            raise GameStateError("BG31_HERO_802p: missing template "
                                 "params")
        state = {"bought": 0, "champion": None, "granted": False}
        options = game.rng.sample(PROTOSS_IDS,
                                  ArtanisScript._OPTION_COUNT,
                                  label="warp_gate_options")

        def resolve(pick):
            state["champion"] = pick

        game.pending_choices.append(PendingChoice(
            hero, list(options), "choose_protoss",
            resolve_callback=resolve))

        def _maybe_grant(g):
            if (state["granted"] or state["champion"] is None
                    or state["bought"] < threshold):
                return
            state["granted"] = True
            m = g.create_minion(state["champion"], controller=hero)
            g.pending_hand_add(hero, m)

        def on_minion_bought(g, minion=None, **kw):
            if not isinstance(minion, Minion):
                return
            if minion.controller is not hero:
                return
            state["bought"] += 1
            _maybe_grant(g)

        def on_spell_bought(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            state["bought"] += 1
            _maybe_grant(g)

        game.events.register(Listener(
            event=MINION_BOUGHT, owner=hero, callback=on_minion_bought))
        game.events.register(Listener(
            event=SPELL_BOUGHT, owner=hero, callback=on_spell_bought))


# ══════════════════ 以下为 DEFERRED（不注册 REGISTRY） ══════════════════


class VardenScript:
    """
    Natural language: [x]After the Tavern is
    <b>Refreshed</b>, copy its
    highest-Tier minion and
    <b>Freeze</b> them both.

    Status: DEFERRED — requires 随从级冻结粒度

    Dependency: TAVERN_REFRESH 事件已就绪（hero_passives2 Enhance-o
    消费中），"copy its highest-Tier minion" 可实现（Tess 入馆先例），
    但 "Freeze them both" 需**单随从级**冻结（两份冻结跨越下一次刷新
    保留、其余馆内随从照常回池）——引擎冻结模型仅整馆 FROZEN tag
    （game.freeze_tavern），冻结局部子集不可表达; 整馆冻结近似会改变
    其余随从的命运（刷新回池面错误）。二态纪律（SOP §6b）→ DEFERRED
    （hero_passives2 台账结转）。需主线: 随从级冻结 tag + refresh 回池
    豁免协议。

    Params: 无数值参数（"highest-Tier" 为运行时聚合）
    """

    @staticmethod
    def on_bind(hero, game):
        return None


class JimRaynorScript:
    """
    Natural language: [x]Start the game with a 2/2
    _Battlecruiser. Whenever the
    Tavern is <b>Refreshed</b>, add a
    __Battlecruiser Upgrade to it.

    Status: DEFERRED — requires Battlecruiser Upgrade 商店子系统

    Dependency: 数据侦察完备: Battlecruiser token BG31_HERO_801pt
    （XML 2/2）+ ~50 张 Upgrade 卡在册（Hyperflight Rotors/Smart
    Servos/Yamato Cannon/Advanced Ballistics/Caduceus Reactor/
    Advanced Construction/Fortified Bunker/Missile Pod/Ultra-
    Capacitor 九族 × 每 tier 变体，card_type 42）。官方机制
    （r/BobsTavern 1jkkusz: "the upgrades that appear in the shop
    linked to raynor's hero power"; amalgadon.com: "Upgrades scale
    in power with your tavern tier"）: 刷新时**向酒馆添加**一张随
    tier 升档的 Upgrade 售卖卡，购买后附着到 Battlecruiser 生效。
    需要引擎: 非池卡售卖实体入馆协议 + Upgrade 购买/附着/九族效果
    （SoC 伤害/Rally/亡语/EoT 随机磁力/免费购买/复生满血…）——
    "开局 2/2 + 刷新钩子"孤立注册是不产生 Upgrade 经济的半成品
    （第三态），整卡 DEFERRED。

    Params: 2/2 由 token XML 权威（非本卡模板参数）
    """

    @staticmethod
    def on_bind(hero, game):
        return None


class KerriganScript:
    """
    Natural language: [x]Unlock Tier 2 Zerg.
    Costs (1) less each turn.
    <b><b>Passive</b>:</b> Start the game
    with a 2/2 Larva.

    Status: DEFERRED — requires Zerg 解锁链/变形子系统官方语义

    Dependency: 数据侦察: 三段链在册（811p Spawning Pool cost=6 /
    811p2 Evolution Chamber cost=8 "Unlock Tier 3 Zerg ... Your Zerg
    can morph into Tier 2 Zerg" / 811p3 Ultralisk Cavern "Your Zerg
    can morph into Tier 3 Zerg"）+ Larva token BG31_HERO_811t（XML
    2/2，"At the start of each turn, choose a Zerg minion to morph
    into. It keeps stats and enchantments."）+ Zerg 池 10 只（t2..
    t10，T1-T3）。可解构面: cost=max(0, 6-(T-1))（Togwaggle 24.0
    Dev Comment 同句式）、开局召唤 Larva。缺口: (a) "Unlock Tier 2
    Zerg" 的使用语义（使用→解锁→replace 到 p2? 官方无记载; wiki
    Spawning Pool 页无 Notes）; (b) Larva 变形协议（每回合开始
    PendingChoice → Transform 保 stats/enchantments——选择集 =
    已解锁 tier 的 Zerg）依赖解锁状态模型; (c) 全 Zerg 池卡效果
    脚本未迁移。三缺一下任何注册均为近似 → DEFERRED（作业单
    "数据侦察后裁决" 条款）。

    Params: cost=6（raw）/ Larva 2/2 由 token XML 权威
    """

    @staticmethod
    def on_bind(hero, game):
        return None


# ══════════════════ 注册 ══════════════════

# （Sneed token 含金色 id——金色=独立卡定义; Naga Conquest 为 Azshara
#  变身终态独立注册——Sulfuras 先例）
_REGISTRATIONS = [
    ("TB_BaconShop_HP_069", IllidanWingmenScript),
    ("BG22_HERO_305p", OnyxiaBroodmotherScript),
    ("BG20_HERO_282p", TamsinPhylacteryScript),
    ("BG25_HERO_103p", TeronReanimationScript),
    ("BG22_HERO_002p", DrekTharScript),
    ("BG22_HERO_003p", VanndarScript),
    ("BG23_HERO_201p", OzumatScript),
    ("BG22_HERO_007p", AzsharaScript),
    ("BG22_HERO_007p2", NagaConquestScript),      # 变身终态
    ("BG22_HERO_001p", BrukanScript),
    ("BG21_HERO_030p", SneedScript),
    ("BG21_HERO_030t", SneedsNewShredderScript),   # token 支撑脚本
    ("BG21_HERO_030t_G", SneedsNewShredderScript),  # "2 highest-Health"
    ("BG27_HERO_801p2", ThorimScript),
    ("BG36_HERO_101p", TrastathScript),
    ("BG36_HERO_105p", XaviusScript),
    ("TB_BaconShop_HP_011", GalakrondScript),
    ("BG26_HERO_102p", IngeScript),
    ("BG31_HERO_802p", ArtanisScript),
    # DEFERRED 未注册: BG22_HERO_004p Varden（随从级冻结）/
    # BG31_HERO_801p Jim Raynor（Upgrade 商店子系统）/
    # BG31_HERO_811p Kerrigan（Zerg 解锁/变形语义）——台账见各类
]


def register() -> list[str]:
    """注册本批次全部脚本，返回注册的 card_id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []
    for card_id, script_cls in _REGISTRATIONS:
        _register(card_id, script_cls)
        registered.append(card_id)
    return registered
