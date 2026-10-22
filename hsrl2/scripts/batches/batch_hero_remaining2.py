"""批次 hero_remaining2 — 剩余英雄技能终批（作业单 2026-09-02）。

作业范围: `data/bg_hero_powers.json`（162 项）中 REGISTRY 无脚本的技能
card_id（逐一用作业单探针列表核对）。铁律: **CORRECT 或 DEFERRED，没有
第三态**（SOP §6b）——语义/时机/载荷无权威证据的一律不注册。

查证方式（2026-09-02）: hsdata/CardDefs.xml（Tag380 绑定 + COST +
TAG_SCRIPT_DATA_NUM_* 逐条核对）; hearthstone.wiki.gg 卡片页
`?action=raw`（custom_mechanicTags / custom_refTags / custom_hiddenTags /
Patch changes）; 数据链 `evolution_card_id`（生成物 token）。

实现 11 技能 + 1 支撑 token（CORRECT）:
  BG22_HERO_004p  Varden Dawngrasp  Twice as Nice（被动）
      刷新后复制馆内最高 tier 随从并冻结两者（实体级 FROZEN）
  TB_BaconShop_HP_009  Bartendotron  Skilled Bartender（被动）
      升级费 -1（UPGRADE_COST_MOD）
  TB_BaconShop_HP_018  Patches?  Rage Potion（主动/定向）
      友方随从 +10 攻击直到下回合（单 tick 过期）
  TB_BaconShop_HP_019  Ragnaros(旧)  DIE, INSECTS!（被动 SoC）
      8 伤害随机 2 个敌方随从
  TB_BaconShop_HP_027  (旧)  Fire the Cannons!（被动 SoC）
      4 伤害随机 2 个敌方随从
  TB_BaconShop_HP_043  (旧)  Nefarious Fire（被动 SoC）
      1 伤害全体敌方随从
  TB_BaconShop_HP_050  (旧)  Banshee's Blessing（主动/定向）
      移除友方随从，相邻 +1/+1
  TB_BaconShop_HP_051  (旧)  Honorable Warband（主动）
      无类型友方随从 +1/+1
  TB_BaconShop_HP_065t2  Illidan Stormrage  Spectral Sight（被动）
      每回合购买的第一个随从免费
  TB_BaconShop_HP_085  Rakanishu(旧)  Tavern Lighting（主动）
      获得 Lantern Light（BG28_885——数据链 evolution_card_id）
  TB_BaconShop_HP_702  (旧)  Runic Empowerment（主动/定向）
      +{1}/+{1}，每五名友方随从死亡升级一次
  BG28_885  Lantern Light（token 法术，Tavern Lighting 的生成物）
      "Give a minion stats equal to your Tier" = 定向 +tier/+tier

DEFERRED 台账（不注册——依赖逐条列出；宁缺毋错）:
  BG20_HERO_202p  Master Nguyen "At the start of every turn, choose from 2
      new Hero Powers"——候选集缺口已由 `_draftable_hero_power_ids` 解决
      （Finley 先例），但**每回合轮换的注销语义**缺引擎协议: 引擎无
      hero 级 unbind（被替换被动技能的 on_bind 监听器/hero tag 常驻——
      Millhouse 费用覆写 / Patchwerk 血量 / Curator 随从换走后仍生效）。
      Dependency: hero 级技能 rebind/unbind（监听器随技能身份注销 +
      hero tag 回滚），否则每次轮换都产生残留被动 = 第三态。
  BG20_HERO_242p  Guff Runetotem "Natural Balance" / BG33_HERO_001p_ALT
      Loh "Heroic Inspiration" "get a Triple Reward"——购买 tier 累加 /
      after_attack 计数面可实现（num(0)=20 / num(0)=num(1)=15），但
      **无来源 Triple Reward 的档位规则**无权威: 常规三连奖励档 =
      被三连卡 tier+1（RULES §10.3），引擎 `_grant_triple_reward(hero,
      golden)` 锚定金色实体; 英雄技能授予场景**无来源卡**。wiki
      Triple Reward token 文本 "Discover a minion from Tier {动态}" 未给
      规则，patch notes 无（2026-09-02 复核 Loh / Heroic Inspiration /
      Natural Balance 三页 custom_refTags=Tavern Tier-related 但无 Notes）。
      Dependency: 主线给"无来源 Triple Reward"的档位裁定 + 脱锚授予原语。
  BG20_HERO_283p  Galewing "Dungar's Gryphon"（+ t1 Westfall / t2
      Ironforge / t3 Eastern Plaguelands，wiki custom_mechanicTags =
      Choose One，derived_choiceCardDbfIds 实证三选一）——三条航线各自
      效果可表达，但 **(a) 完成时点**（"In N turns" 是第 T+N 回合开始
      还是结束）与 **(b) 完成后是否回到基础技能以再选** 均无公开证据
      （三张变体 wiki 页仅 mechanicTags，无 Notes/Patch changes）;
      (c) t1 "a random 1-Cost Tavern spell" 的 "1-Cost" 是法术金币费还是
      tier 无裁定。Dependency: 官方时机/回退证据或主线裁定。
  BG22_HERO_000p  Tavish Stormpike "Deadeye"（+ 瞄准态 t1 Aim Left! /
      t2 Aim Low! / t3 Aim High! / t4 Aim Right!，wiki custom_mechanicTags
      = Deal damage + Start of Combat + Passive Hero Power）——四个瞄准
      态各自效果明确（99 伤害打最左/最低血/最高血/最右敌方随从），但
      "Take aim!" 的**选择协议与再瞄准语义**无证据（瞄准态为被动=不可
      点击，无法回到基础态重新瞄准）。Dependency: 官方瞄准选择/再瞄
      准协议（含基础态是否保留）。瞄准态本身可达性依赖该协议 → 整族
      DEFER。
  BG20_HERO_201p2  Spirit Swap（变体面）"Choose a minion. Gain Attack
      with {0}."——未绑定任何英雄（Tag380 无指向），{0} 无
      TAG_SCRIPT_DATA_NUM 值，语义（gain Attack *with*?）无 wiki 页
      （dbf 71644 无卡页）。Dependency: 官方文本/{0} 数值。
  BG24_HERO_100p  Sire Denathrius "Whodunit?"——**2026-09-18 第四十九轮
      订正**: 任务卡已全部落地（`batch_quests`，19 张; 目标值权威 = 各卡
      wiki 页 "baseline requirement"，见 `docs/agents/QUEST_DEFERRED_SPEC.md`）
      → 旧理由「选到的任务永不推进/完成」失效。当前缺口 = **接线**
      （`WhodunitScript.on_bind` 候选池写死 `BG24_Quest_*` 前缀，须改用
      `game.quest_offer_pool()` 以排除 DEFERRED 的 328 与公告 token）。
      机制本身已验证（2026-09-01 对抗审计）。
  BG25_HERO_100p  Professor Putricide "Build-An-Undead"——多步部件
      选择/缝合链（种族+关键词+属性）无引擎建模。
  BG31_HERO_801p  Jim Raynor "Lift Off"——10 张 Battlecruiser Upgrade
      （BG31_HERO_801pta..j, card_type 42）全部无脚本且含关键词赋予/
      Yamato/Rally 等叠加语义 → 载荷未就绪（"引擎机制就绪" ≠ "效果
      可兑现"，SOP §12.14）。
  BG31_HERO_811p / 811p2 / 811p3  Kerrigan "Spawning Pool" / "Evolution
      Chamber" / "Ultralisk Cavern"——Zerg 分级解锁（Unlock Tier 2/3
      Zerg）+ Larva 每回合变形选择（BG31_HERO_811t "choose a Zerg
      minion to morph into"）子系统未建。
  BG34_HERO_000p / BG34_HERO_004p  Murozond "Alternate Timeline" /
      Morchie "Warped Conflux"——Timewarp（Major/Minor Timewarp 商店）
      子系统无引擎实现（BG34_BlackMarket_Skip 等 356 张卡无脚本）。
  BG35_HERO_001p  Genn "King of Duality"——"Discover two Hero Powers to
      replace this"; "second Hero Power"（34.2 Timewarped Power 概念）
      与二选一语义**均无公开细节**（2026-09-17 复核 wiki oldid 904461
      无 Notes）。**原注"引擎单槽 `_active_power_id`"已陈旧**: 引擎现另
      有 `set_second_hero_power`/`hero._second_power_id` 第二槽
      （RULES §9.5，batch_anomalies4/5 已在用）→ 两种读法都有落点，
      缺口纯在语义权威。
  TB_BaconShop_HP_017  (旧) "Murloc King"——亡语授予面可表达
      （`_grant_combat_deathrattle` 家族），但 **"Summon a 1/1 Murloc"
      token 不在 CardDB**（dbf 1078 未导出; 全库无 1/1 Murloc 随从）。
      Dependency: 1/1 Murloc token 数据链。
  TB_BaconShop_HP_020  Akazamzarak "Prestidigitation"——Secret 子系统
      （BG 无 Secret 区/触发协议）。
  TB_BaconShop_HP_101  Silas "Come One, Come All!"——Darkmoon Ticket
      token + 馆内计数 + 集 3 发现子系统（CardDB 内 "Ticket" 仅 buddy）。
  TB_BaconShop_HP_106  Tickatus "Prize Wall"——Darkmoon Prize 子系统
      （CardDB 内 "Darkmoon Prize" 零卡池定义）。

变体台账（"inspect and decide"——**不重复注册**，原因逐条）:
  BG26_HERO_102p2  Minor Hymn——Inge "Major Hymn"（BG26_HERO_102p，
      batch_hero_combat3 已注册）的 Health 面 Related card（dbf 相邻、
      文本 "Swaps to Attack next turn!"）; 已注册基础脚本以 `game.turn`
      奇偶实现两面交替（奇数 Attack / 偶数 Health），本变体是其镜像面，
      非独立技能 → 不再注册（重复 = 第三态）。未绑定任何英雄。
  BG28_HERO_400p2  Lucky Roll——Snake Eyes 基础技能 BG28_HERO_400p
      （batch_hero_actives2 已注册）的新文本态（"Can be used again in @
      turns" 取代 "Cannot be used again for that many turns"，效果与
      冷却模型完全一致）; 未绑定英雄 → 记档不注册。
  BG22_HERO_001p_t1..t4  Earth/Fire/Water/Lightning Invocation——
      Bru'kan "Embrace the Elements"（BG22_HERO_001p，batch_hero_combat3
      已注册）的四个祈咒形态; 基础脚本 `hero_power` 直接以 `ELEMENT_IDS`
      五选一并对四形态 SoC 分发（含 Earth 战斗内亡语 / Lightning 5×1
      伤害）→ 已由基础脚本完整处理，不重复注册。
  BG27_Anomaly_805t  Match Fixing——与已注册 Barov "Friendly Wager"
      （TB_BaconShop_HP_081）效果一致（猜下一场胜者得 3 金币），且其
      **基础异变** BG27_Anomaly_805 未注册 → 异变子系统载荷缺失。
  ~~BG31_Anomaly_117t  Eject!~~——**已迁出（2026-09-13）**:
  batch_anomalies7 注册（配 `MinionPool.purge` 永久移除原语）。
  原文: 基础异变 BG31_Anomaly_117 "Emergency
      Landing" 未注册; 属异变子系统（非英雄自带技能）。
  BG35_Anomaly_002t / 007t / 008t  Mystery Cube / Lesser·Greater Crystal
      Ball——基础异变 BG35_Anomaly_002/007/008 未注册，且全部为
      "second Hero Power" 语义（34.2 双技能槽协议缺失）→ 同 Genn。

引擎需求汇总（报告主线）:
  1. hero 级技能 rebind/unbind（Nguyen 每回合轮换——残留被动注销）
  2. 无来源 Triple Reward 的档位裁定 + 脱锚授予原语（Guff/Loh）
  3. 1/1 Murloc token 数据链（Murloc King dbf 1078 未导出）
  4. Battlecruiser Upgrade 卡脚本（Lift Off）/ Zerg morph（Spawning
     Pool）/ Timewarp（Murozond/Morchie）/ Secret（Akazamzarak）/
     Ticket（Silas）/ Darkmoon Prize（Tickatus）子系统
  5. 多技能槽协议（Genn / Anomalous Cube / Crystal Ball）
  6. Dungar's Gryphon 航线完成时点与回退裁定 / Deadeye 瞄准选择协议
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from hsrl2 import entity
from hsrl2.actions import Buff, Hit
from hsrl2.events import DEATH, START_OF_COMBAT, TAVERN_REFRESH, TURN_START, \
    Listener
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.scripts.spells import _expire_at_next_turn
from hsrl2.tags import GameTag, Race, Zone

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# 卡 id 字面量（数据链解析; 禁止凭记忆写 id）
_LANTERN_LIGHT_ID = "BG28_885"          # Tavern Lighting 生成物
_SKILLED_BARTENDER = "TB_BaconShop_HP_009"
_RAGE_POTION = "TB_BaconShop_HP_018"
_DIE_INSECTS = "TB_BaconShop_HP_019"
_FIRE_THE_CANNONS = "TB_BaconShop_HP_027"
_NEFARIOUS_FIRE = "TB_BaconShop_HP_043"
_BANSHEES_BLESSING = "TB_BaconShop_HP_050"
_HONORABLE_WARBAND = "TB_BaconShop_HP_051"
_SPECTRAL_SIGHT = "TB_BaconShop_HP_065t2"
_TAVERN_LIGHTING = "TB_BaconShop_HP_085"
_RUNIC_EMPOWERMENT = "TB_BaconShop_HP_702"
_TWICE_AS_NICE = "BG22_HERO_004p"


def _power_def(game: "Game", power_id: str):
    d = game.db.get(power_id)
    if d is None:
        raise GameStateError(f"unknown hero power {power_id!r}")
    return d


def _combat_opponent(game: "Game", hero: "Hero") -> Optional["Hero"]:
    """当前战斗对手（combat.run 暴露 game._active_combat; SoC 阶段非 None）。"""
    ac = getattr(game, "_active_combat", None)
    if ac is None:
        return None
    a, b = ac
    return b if a is hero else a


# ═══════════════════ BG22_HERO_004p Varden — Twice as Nice ═══════════════════


class TwiceAsNiceScript:
    """
    Natural language: After the Tavern is <b>Refreshed</b>, copy its
    highest-Tier minion and <b>Freeze</b> them both.

    依据（2026-09-02 查证）: wiki Battlegrounds/Twice_as_Nice——Wiki tags
    `BACON_FREEZE` / `BACON_REFRESH_TOOLTIP`，mechanics Copy/Freeze/
    Passive hero Power/Summon，refTags Refresh-related + Tavern
    Tier-related; Patch changes 证实 "Passive." 前缀（27.0 起）→ 被动
    技能（不可点击）。**Bug fixes 原文**（22.4.3）: "Fixed a bug where the
    Twice as Nice Hero Power could give buffs to minions in Bob's Tavern
    (such as when a Mama Bear is in Bob's Tavern and a Beast is copied)"
    → 复制体必须是 **plain copy（不带馆内附魔）**。并列最高 tier 取
    rng 任选（Diremuck "并列 rng 任选" 先例）。

    Formal spec:
      1. passive=True; on_bind 注册持久 TAVERN_REFRESH 监听（owner=hero，
         条件 hero is 绑定者——闭包 `_owner` 默认绑定，防晚绑定）。
      2. 触发（refresh_tavern 末尾 fire，新抽已入馆）:
         - 候选 = hero.tavern 内非死亡 Minion; 空 → 落空
         - top = max(tech_level); 并列 → game.rng.choice
         - copy = create_minion(src.card_id, golden=src.is_golden)
           （**plain**: 不复制 buff、不应用 tavern_buffs——wiki bugfix）
           → zone=TAVERN → 追加馆内（**不 acquire**——复制体不消耗池
           副本; 出售照常回池 = Rafaam/Tess 复制体进出池不对称先例）
         - src 与 copy 各打实体级 `GameTag.FROZEN`（下一次刷新保留两者
           ——引擎 refresh_tavern 读取实体 FROZEN 集，SOP §16 item 18）
      3. 每次刷新各触发一次（"After the Tavern is Refreshed" 逐次语义）。

    Test: test_batch_hero_remaining2.py — 刷新后复制体入馆且卡 id = 最高
    tier、原体带 buff 而复制体 plain（bugfix）、两者 FROZEN 且下次刷新
    保留、并列只复制一份、空馆落空、未绑定英雄刷新不产生复制体
    （owner 隔离）。

    Params: 无模板参数（"highest-Tier"/"both" 非数值; 复制语义与冻结由
            wiki tags 权威）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_refresh(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            mins = [e for e in _owner.tavern
                    if isinstance(e, Minion) and not e.dead]
            if not mins:
                return
            top = max(m.tech_level for m in mins)
            tied = [m for m in mins if m.tech_level == top]
            src = (tied[0] if len(tied) == 1
                   else g.rng.choice(tied, label="twice_as_nice_source"))
            # 统一酒馆注入入口（金馆金色化 + tavern_buffs; 金色源保金色）
            copy = g.inject_tavern_minion(_owner, src.card_id,
                                          golden=src.is_golden or None)
            src.set(GameTag.FROZEN, True)
            copy.set(GameTag.FROZEN, True)

        game.events.register(Listener(
            event=TAVERN_REFRESH, owner=hero, callback=on_refresh))


# ═══════════════ TB_BaconShop_HP_009 Bartendotron — Skilled Bartender ═══════════════


class SkilledBartenderScript:
    """
    Natural language: [x]Reduce the Cost of upgrading the Tavern by (1).

    依据（2026-09-02 查证）: wiki Battlegrounds/Skilled_Bartender——
    custom_mechanicTags = "Passive Hero Power&&Decrement cost";
    custom_refTags = Tavern Tier-related → 被动、永久降低升级费。

    Formal spec:
      1. passive=True（不可点击）; on_bind: hero `UPGRADE_COST_MOD` -= 1
         （game.upgrade_tavern 读取点: `hero.upgrade_cost +
         hero.get(UPGRADE_COST_MOD, 0)`，下限 UPGRADE_COST_FLOOR）。
      2. 只在绑定英雄生效（hero 级 tag——不污染对手）。

    Test: test_batch_hero_remaining2.py — 绑定后真实 upgrade_tavern 支付
    base−1（对照未绑定英雄付 base）; 对手不共享。

    Params: discount=1（"(1)" 文本字面量——CardDef 无模板参数）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        hero.set(GameTag.UPGRADE_COST_MOD,
                 hero.get(GameTag.UPGRADE_COST_MOD, 0) - 1)


# ═══════════════════ TB_BaconShop_HP_018 — Rage Potion ═══════════════════


class RagePotionScript:
    """
    Natural language: [x]Give a friendly minion +10 Attack until next
    turn.

    依据（2026-09-02 查证）: wiki Battlegrounds/Rage_Potion——
    custom_mechanicTags = Increment attack; custom_refTags = Next turn &&
    Targeted && Triggered effect → 定向、临时增益持续到下回合。
    数据库无模板参数（CardDef.num 全 None）→ "+10" 为文本字面量
    （SOP §3 "模板参数缺失且文本无占位符时可字面量"）。

    Formal spec:
      1. needs_target=True（[Targeted]）; 候选默认 = 友方棋盘存活随从。
      2. hero_power: 目标添加 `entity.Buff(atk=10, temporary=True,
         source_id=本技能 id)`; 过期经 `scripts.spells.
         _expire_at_next_turn(buffs=[b])`——单 tick（目标控制者的下一个
         招募阶段开始精确移除，SOP §16 item 16; temporary 无引擎清除点，
         必须脚本层回收，SOP §12.6）。
      3. 陈旧/离场目标 → return None 落空（引擎 `_hero_power_target_ok`
         前置复查; 脚本再自守卫，SOP §16 item 24——不抛异常中断回合）。
      4. cost=1（raw cost）。

    Test: test_batch_hero_remaining2.py — +10 攻击立即生效 / 目标控制者
    下回合开始回落（正对照同 setup 本回合生效）/ 对手回合不回落
    （owner 隔离）/ 陈旧目标落空且金币不动。

    Params: atk=10（文本字面量——CardDef 无模板参数）/ cost=1（raw）
    """

    needs_target = True

    @staticmethod
    def hero_power(hero: "Hero", game: "Game", ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target.dead \
                or target not in hero.board:
            return None
        b = entity.Buff(atk=10, temporary=True,
                        source_id=_RAGE_POTION)
        target.add_buff(b)
        _expire_at_next_turn(game, None, target, buffs=[b])
        return None


# ═══════════════ TB_BaconShop_HP_019 — DIE, INSECTS! ═══════════════


class DieInsectsScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Deal 8 damage to two
    random enemy minions.

    依据（2026-09-02 查证）: 旧 Ragnaros 技能（wiki DIE,_INSECTS! 重定向
    至 BUY,_INSECT!——现行 Ragnaros 主动面已重做; 本卡为技能文本权威）。
    同族 Fire the Cannons!/Nefarious Fire 的 wiki custom_mechanicTags =
    "Deal damage&&Start of Combat" + refTags Random/Triggered effect，
    custom_hiddenTags "Triggered effect - At the start of next combat"。
    数值为文本字面量（CardDef.num 全 None）。

    Formal spec:
      1. passive=True; on_bind 注册持久 START_OF_COMBAT 监听（owner=hero，
         条件 hero is 绑定者）。
      2. 触发: 对手 = `_combat_opponent`（game._active_combat）; 存活
         敌方随从 rng.sample 取 min(2, N) 个不同目标 → 各 Hit 8
         （`g.run_actions`——圣盾/剧毒/死亡波次走引擎）。
      3. 空敌板 → 落空（无候选不抛）。

    Test: test_batch_hero_remaining2.py — SoC 战斗内探针: 恰 2 只敌方各
    -8 / 仅 1 只时只打 1 / 空敌板不抛 / 恰一次（owner 隔离: 对手 SoC
    不二次触发）。

    Params: damage=8 targets=2（文本字面量——CardDef 无模板参数）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_soc(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            opponent = _combat_opponent(g, _owner)
            if opponent is None:
                return
            living = [m for m in opponent.board if not m.dead]
            if not living:
                return
            k = min(2, len(living))
            picks = (list(living) if k == len(living)
                     else g.rng.sample(living, k, label="die_insects"))
            g.run_actions([Hit(m, 8) for m in picks])

        game.events.register(Listener(
            event=START_OF_COMBAT, owner=hero, callback=on_soc))


# ═══════════════ TB_BaconShop_HP_027 — Fire the Cannons! ═══════════════


class FireTheCannonsScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Deal 4 damage to two
    random enemy minions.

    依据（2026-09-02 查证）: wiki Battlegrounds/Fire_the_Cannons!——
    custom_mechanicTags = "Deal damage&&Start of Combat"，refTags =
    Random&&Triggered effect。数值文本字面量。

    Formal spec: 同 DieInsectsScript，伤害 4（Hit）。

    Test: test_batch_hero_remaining2.py — SoC 探针恰 2 只敌方各 -4。

    Params: damage=4 targets=2（文本字面量——CardDef 无模板参数）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_soc(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            opponent = _combat_opponent(g, _owner)
            if opponent is None:
                return
            living = [m for m in opponent.board if not m.dead]
            if not living:
                return
            k = min(2, len(living))
            picks = (list(living) if k == len(living)
                     else g.rng.sample(living, k,
                                       label="fire_the_cannons"))
            g.run_actions([Hit(m, 4) for m in picks])

        game.events.register(Listener(
            event=START_OF_COMBAT, owner=hero, callback=on_soc))


# ═══════════════ TB_BaconShop_HP_043 — Nefarious Fire ═══════════════


class NefariousFireScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Deal 1 damage to all
    enemy minions.

    依据（2026-09-02 查证）: wiki Battlegrounds/Nefarious_Fire——
    custom_mechanicTags = "Deal damage&&Start of Combat"，refTags =
    Area of effect&&Triggered effect。数值文本字面量。

    Formal spec: 同 DieInsectsScript 但**全体**（无随机）——对每个存活
    敌方随从 Hit 1。

    Test: test_batch_hero_remaining2.py — SoC 探针全体敌方各 -1（3 只
    全部）/ 空敌板不抛。

    Params: damage=1（文本字面量——CardDef 无模板参数）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_soc(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            opponent = _combat_opponent(g, _owner)
            if opponent is None:
                return
            living = [m for m in opponent.board if not m.dead]
            if not living:
                return
            g.run_actions([Hit(m, 1) for m in living])

        game.events.register(Listener(
            event=START_OF_COMBAT, owner=hero, callback=on_soc))


# ═══════════════ TB_BaconShop_HP_050 — Banshee's Blessing ═══════════════


class BansheesBlessingScript:
    """
    Natural language: [x]Remove a friendly minion. Give adjacent minions
    +1/+1.

    依据（2026-09-02 查证）: wiki Battlegrounds/Banshee's_Blessing——
    custom_mechanicTags = "Increment attack&&Increment health"，
    custom_refTags = Positional effect → 相邻位置效果。数值文本字面量。
    "Remove" = 非死亡、非出售（Cookie "投锅"/Hooktusk "Remove from
    game" 先例: 板位移出 + zone=REMOVED + 监听器注销，不回池、无 +1 金）。

    Formal spec:
      1. needs_target=True; 候选默认 = 友方棋盘存活随从。
      2. hero_power: 先按当前板位快照左右邻居 → 移除目标
         （board.remove + `game._update_positions` + zone=REMOVED +
         `events.unregister_owner`）→ 返回 [Buff(邻居, atk=1, health=1)]
         （永久增益）。
      3. 左/右边界只有单侧邻居; 空侧忽略。陈旧目标 → 落空。
      4. cost=0（raw cost）。

    Test: test_batch_hero_remaining2.py — 中间目标移除（zone=REMOVED、
    不在棋盘、池不回收）且左右各 +1/+1、边界只单侧、对手随从不可为
    目标（金币不动）、陈旧目标落空。

    Params: atk=1 health=1（文本字面量——CardDef 无模板参数）
    """

    needs_target = True

    @staticmethod
    def hero_power(hero: "Hero", game: "Game", ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target.dead \
                or target not in hero.board:
            return None
        idx = hero.board.index(target)
        neighbors = []
        if idx > 0:
            neighbors.append(hero.board[idx - 1])
        if idx + 1 < len(hero.board):
            neighbors.append(hero.board[idx + 1])
        hero.board.remove(target)
        game._update_positions(hero)
        target.zone = Zone.REMOVED
        game.events.unregister_owner(target)
        return [Buff(m, atk=1, health=1) for m in neighbors if not m.dead]


# ═══════════════ TB_BaconShop_HP_051 — Honorable Warband ═══════════════


class HonorableWarbandScript:
    """
    Natural language: [x]Give your minions with no type +1/+1.

    依据（2026-09-02 查证）: wiki Battlegrounds/Honorable_Warband——
    custom_mechanicTags = "Increment attack&&Increment health"，refTags =
    Area of effect&&Minion type-related → 全体"无类型"随从 +1/+1。
    数值文本字面量。"no type" = Race.NONE（ALL 是"全类型"不是"无类型"，
    RULES §8 种族匹配口径）。

    Formal spec:
      1. 主动（cost=2 raw）; hero_power 返回
         [Buff(m, atk=1, health=1) for m 棋盘非死亡且 race is NONE]。
      2. 零无类型随从 → 空列表（无效果但技能照常结算——合法目标域
         是"你的随从"，非"必须存在无类型随从"）。

    Test: test_batch_hero_remaining2.py — 无类型 +1/+1、有类型不变、
    金币 -2（raw）、对手棋盘不受影响（owner 隔离）。

    Params: atk=1 health=1（文本字面量——CardDef 无模板参数）/
            cost=2（raw cost）
    """

    @staticmethod
    def hero_power(hero: "Hero", game: "Game", ctx):
        return [Buff(m, atk=1, health=1)
                for m in hero.board
                if not m.dead and not m.races]


# ═══════════════ TB_BaconShop_HP_065t2 Illidan — Spectral Sight ═══════════════


class SpectralSightScript:
    """
    Natural language: The first minion you buy each turn is free.

    依据（2026-09-02 查证）: wiki Battlegrounds/Spectral_Sight——
    custom_mechanicTags = Passive Hero Power; custom_refTags =
    Buying-related → 被动；每回合首个随从购买免费。

    Formal spec:
      1. passive=True; on_bind 注册 TURN_START 监听（owner=hero，条件
         hero is 绑定者）→ `FREE_MINION_BUYS_THIS_TURN = 1`。
      2. 引擎消费点: `buy_from_tavern` 对 Minion 优先读该 tag（置 0 价
         并递减; 法术不适用——"minion" 限定）。
      3. 每回合重置为 1（未使用不累积——"the first minion ... each
         turn"）。

    Test: test_batch_hero_remaining2.py — turn_start 后首个随从购买 0 金、
    第二个正常价 / 未绑定不免费（正对照）/ 对手回合不置 tag（owner
    隔离）/ 法术购买不消耗免费次数。

    Params: free_buys=1（"the first minion" 语义——文本字面量）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_turn_start(g, hero=None, turn=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            # 多来源独立配额（RULES §7.4.4，2026-09-02 主线原语）
            g.set_free_minion_buys(
                _owner, 1, source="TB_BaconShop_HP_065t2")

        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))


# ═══════════════ TB_BaconShop_HP_085 Rakanishu — Tavern Lighting ═══════════════


class TavernLightingScript:
    """
    Natural language: [x]Get a Lantern Light that gives a minion stats
    equal to your Tier.

    依据（2026-09-02 查证）: 数据链 `evolution_card_id=105269` → CardDB
    `BG28_885` "Lantern Light"（card_type 42 酒馆法术 token; 非池
    `is_pool_spell=False`），wiki Battlegrounds/Lantern_Light——
    custom_mechanicTags = "Increment attack&&Increment health"，refTags =
    Tavern Tier-related。**注**: Rakanishu 现行技能为被动
    `TB_BaconShop_HP_085t`（batch_hero_passives2 已注册）; 本卡为旧版
    主动面（Tag380 无英雄指向），效果本身完全可表达且生成物 token
    在库/已随本批注册脚本。

    Formal spec:
      1. 主动（cost=1 raw）; hero_power: 经 `evolution_card_id` 解析
         token id（`game.db.by_dbf`——禁止硬编码）→
         `create_spell(token_id, controller=hero)` → `pending_hand_add`
         （满手排队 P6）。token 非池 → 零池操作（Sneed token 先例）。
      2. token 脚本 LanternLightScript: 定向 +tier/+tier（运行时读
         `hero.tavern_tier`）。

    Test: test_batch_hero_remaining2.py — 使用后手牌得 BG28_885 法术 /
    金币 -1 / token 不占法术池 / evolution 数据链解析; 打出 +tier/+tier
    （Lantern Light 测试节）。

    Params: cost=1（raw cost; 生成物 id 走数据链）
    """

    @staticmethod
    def hero_power(hero: "Hero", game: "Game", ctx):
        d = _power_def(game, _TAVERN_LIGHTING)
        token_def = (game.db.by_dbf(d.evolution_card_id)
                     if d.evolution_card_id else None)
        token_id = token_def.id if token_def is not None \
            else _LANTERN_LIGHT_ID
        s = game.create_spell(token_id, controller=hero)
        if s is not None:
            game.pending_hand_add(hero, s)
        return None


class LanternLightScript:
    """
    Natural language: Give a minion stats equal to your Tier.

    依据: 数据 BG28_885（Lantern Light，token 法术，无模板参数）; wiki
    custom_mechanicTags = "Increment attack&&Increment health"，refTags =
    Tavern Tier-related → +tier/+tier（攻防同值）。

    Formal spec:
      1. needs_target=True（"Give a minion" 定向——play_spell 产生
         PendingChoice kind="spell_target"，默认候选 = 友方棋盘存活
         随从; 无候选 → 落空但法术照常消耗）。
      2. on_play: target.add_buff(entity.Buff(atk=tier, health=tier))，
         tier = source.controller.tavern_tier 运行时读取（无模板参数）。

    Test: test_batch_hero_remaining2.py — 打出后目标 +tier/+tier（tier 2
    与 tier 4 两档）/ 无候选落空不抛。

    Params: 无数值字面量（数值 = 运行时酒馆 tier）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game: "Game", ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion):
            return None
        tier = source.controller.tavern_tier if source.controller else 1
        target.add_buff(entity.Buff(atk=tier, health=tier,
                                    source_id=_LANTERN_LIGHT_ID))
        return None


# ═══════════════ TB_BaconShop_HP_702 — Runic Empowerment ═══════════════


class RunicEmpowermentScript:
    """
    Natural language: [x]Give a minion +{1}/+{1}. Improves after five
    friendly minions die. <i>({0} left!)</i>

    依据（2026-09-02 查证）: wiki Battlegrounds/Runic_Empowerment——
    XML tags `TAG_SCRIPT_DATA_NUM_1=5`（{0} 剩余死亡数阈值）/
    `TAG_SCRIPT_DATA_NUM_2=1`（{1} 当前增益）; custom_mechanicTags =
    "Increment attack&&Increment health&&Upgradable"，refTags =
    Death-related&&Targeted&&Triggered effect。Patch changes 证实
    "Improves"/"Upgrades after five" 措辞（34.2）; 每升级一次 {1}+1
    （初始增益 = 增幅 = num(1)=1——客户端动态显示 {1}，数据无独立增幅
    字段）。

    Formal spec:
      1. needs_target=True（[Targeted]）; 候选默认 = 友方棋盘存活随从。
      2. on_bind: `hero._runic_deaths = 0`、`hero._runic_bonus =
         num(1)`; 注册持久 DEATH 监听（owner=hero）——minion.controller
         is 绑定者 时计数 +1; 每满 num(0) 次 → 计数清零、bonus += num(1)
         （可处理一次结算内多次死亡——while）。
      3. hero_power: Buff(target, atk=bonus, health=bonus)（永久;
         "Improves" 后所有后续使用数值提升，已施加增益不回改）。
      4. 陈旧目标 → 落空（金币已扣——引擎语义; 与 SOP §16 item 24 一致
         的落空不抛）。cost=1（raw cost）。

    Test: test_batch_hero_remaining2.py — 初始 +num(1)/+num(1) / 4 次
    友方死亡不升级 / 第 5 次升级后 +2·num(1) / 敌方死亡不计数（owner
    隔离）/ 陈旧目标落空不抛。

    Params: {0}=5 {1}=1（script_data_num_1/2——阈值/增益与增幅）/
            cost=1（raw cost）
    """

    needs_target = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        d = _power_def(game, _RUNIC_EMPOWERMENT)
        threshold = d.num(0)
        gain = d.num(1)
        hero._runic_deaths = 0
        hero._runic_bonus = gain

        def on_death(g, minion=None, _owner=hero, **kw):
            if minion is None or minion.controller is not _owner:
                return
            _owner._runic_deaths += 1
            while _owner._runic_deaths >= threshold:
                _owner._runic_deaths -= threshold
                _owner._runic_bonus += gain

        game.events.register(Listener(
            event=DEATH, owner=hero, callback=on_death))

    @staticmethod
    def hero_power(hero: "Hero", game: "Game", ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target.dead \
                or target not in hero.board:
            return None
        d = _power_def(game, _RUNIC_EMPOWERMENT)
        bonus = getattr(hero, "_runic_bonus", None)
        if bonus is None:
            bonus = d.num(1)
        return Buff(target, atk=bonus, health=bonus)


def register() -> list[str]:
    """注册本批 11 技能 + 1 支撑 token（技能/token card_id）。

    DEFERRED 台账见模块 docstring（Nguyen / Guff / Loh / Dungar /
    Deadeye 族 / Spirit Swap 变体 / Whodunit / Putricide / Raynor /
    Kerrigan×3 / Murozond / Morchie / Genn / Murloc King /
    Akazamzarak / Silas / Tickatus——依赖逐条列出）。
    """
    from hsrl2.scripts.registry import register as reg

    registered: list[str] = []
    for card_id, script in (
        (_TWICE_AS_NICE, TwiceAsNiceScript),
        (_SKILLED_BARTENDER, SkilledBartenderScript),
        (_RAGE_POTION, RagePotionScript),
        (_DIE_INSECTS, DieInsectsScript),
        (_FIRE_THE_CANNONS, FireTheCannonsScript),
        (_NEFARIOUS_FIRE, NefariousFireScript),
        (_BANSHEES_BLESSING, BansheesBlessingScript),
        (_HONORABLE_WARBAND, HonorableWarbandScript),
        (_SPECTRAL_SIGHT, SpectralSightScript),
        (_TAVERN_LIGHTING, TavernLightingScript),
        (_RUNIC_EMPOWERMENT, RunicEmpowermentScript),
        (_LANTERN_LIGHT_ID, LanternLightScript),
    ):
        reg(card_id, script)
        registered.append(card_id)
    return registered
