"""批次 hero_actives — 主动英雄技能 16 张（作业单 2026-08-23）。

主动协议（game.py use_hero_power 核实）:
  - 脚本类注册于**技能卡 id**（hero_power_def(hero) 经 CardDef.hero_power_id
    链解析）; 主入口 ``hero_power(hero, game, ctx)``——source 是 Hero 非
    Minion! 引擎在 _finish_hero_power 中先扣费（power CardDef.cost）+
    计次（HERO_POWER_USED_THIS_TURN），脚本只负责效果
  - 声明协议: ``uses_per_turn = N``（"Twice per turn" 类）; ``needs_target
    = True`` + 可选 ``target_candidates(hero, game)``——无候选 →
    use_hero_power 返回 False（金币未扣，官方"无合法目标不可用"）
  - 定向流: PendingChoice(kind="hero_power_target") → choose(index) →
    resolve_callback → _finish_hero_power（扣费在选定之后）
  - ``on_bind(hero, game)``: 与 hero_passives 批同协议——计数器类技能
    的游戏开局接线点（主线缺口: start_game 需调
    REGISTRY[power.id].on_bind(hero, game)，脚本类带 on_bind 属性才调）
  - 被动技能（passive=True）恒不可点击——本批不涉及

选卡依据: 36.2.2 数据（116 英雄全量打印）+ hearthstone.wiki.gg 逐卡页
Wiki tags 校准（[Targeted]/[Random] 判别——SOP §9 目标语义裁决库）:
  - [Targeted] 实证: George(HP_010) / Xyrella(HP_101p) / Baz'hial
    (HP_049) / Hooktusk(HP_075) / Inge(HP_102p) / Edwin(HP_001)
  - Malygos(HP_052): wiki 仅标 [Random]，但官方 29.2 patch notes
    "This used to only target minions" 实证定向（dev comment 原文）
  - Jandice(HP_084): wiki 仅标 [Random]，社区实证定向
    （r/BobsTavern "using your hero power on the token generator";
    note.com 战记 "use your Hero Power on one of them to return it to
    the Tavern"——玩家自选友方随从）
  - Rafaam(HP_053): wiki Notes 实证——"triggers even when minions die
    from attacking the player's minions"（反击致死也算击杀）+ 顺劈
    同时多杀取最左（引擎死亡波次按板位序 = 首个 death 事件即最左）

实现状态总览:
  OK 16: Xyrella / Blackthorn / Edwin / George / Lich King / Pyramad /
         Maiev / Eudora / Malygos / Jandice / Baz'hial / Rafaam / Toki /
         Hooktusk / Chromie / Holli'dae
  AMBIGUOUS 1（不注册）: BG26_HERO_102p Inge "Major Hymn"——"Swaps to
      Health next turn!" 的奇偶锚点未公布（turn 1 = Attack? 无 wiki/
      patch notes 证据; Kelp Keeper 教训: 无证据不裁）
  DEFERRED（报告不注册，逐张见"跳过名单"段）

跳过名单（数据核实后 DEFERRED / 越界，均报告主线）:
  - 主动技能类:
    * Cariel BG21_HERO_000p: 主动部分 "Give {2} random friendly minions
      +{0}/+{1}"（num=1/1/1）可实现，但附带被动 "After each combat,
      choose an improvement"——improvement 选项集不在 CardDefs（客户端
      硬编码）→ 注册即"简化实现"，禁止
    * Tess TB_BaconShop_HP_077: 官方 27.0 bugfix "can no longer be
      activated if your last opponent had no minions"——引擎无技能
      可用性否决协议（脚本 hero_power 在扣费后调用，无法拒绝使用）
    * Snake Eyes BG28_HERO_400p: "Cannot be used again for that many
      turns" 多回合冷却——同上无可用性协议
    * Kragg HP_068? no——TB_BaconShop_HP_076 "Once per game" / Reno
      HP_046 / Zerek BG31_HERO_005p: 每局 N 次——同上（第 N+1 次使用
      无法拒绝，金币已扣）
    * Elise HP_047 "Costs (1) more after each use" / Togwaggle
      BG23_HERO_305p / Nobundo BG31_HERO_003p: 技能费动态修正——
      引擎 cost 恒读 power CardDef.cost，无覆写点
    * Alexstrasza HP_064 / Millificent HP_015 / Sylvanas BG23_HERO_306p /
      Shudderwock HP_022 / Yogg HP_039t / Jailer HP_702t / E.T.C.
      BG25_HERO_105p: "(Unlocks at Turn/Tier N)" 解锁门槛——无可用性
      协议（脚本无法按 tier/turn 拒绝使用）
    * Rat King HP_041: 官方实现 = 每回合**替换英雄技能**（wiki mechanics
      "Replace Hero Power"; 数据含 11 张 King of X 变体 HP_041a..k）——
      无技能替换协议 + 轮换顺序不在数据
    * Vol'jin BG20_HERO_201p "Choose 2 minions": 双目标选择协议缺失
      （PendingChoice 单目标）
    * Mutanus BG20_HERO_301p: 卖+溅射两步连招（先 Sell 再定向 Transfer）
      ——两步均有引擎原语但组合需双 PendingChoice 链，复杂度超本批
    * Cookie BG21_HERO_020p: 锅（跨回合收集 + Discover from their types）
      ——多回合状态机 + 类型集发现，复杂度超本批
    * Scabbs BG21_HERO_010p: "next opponent's warband"——配对在
      end_recruit_phase 才定（matchmaking.pair_players），招募期无
      "下一对手" API
    * Barov HP_081 / Murloc Holmes BG23_HERO_303p: 猜测类小游戏，模拟
      语义未定义
  - 被动技能（本批范围外，多数属 hero_passives 批）: Patchwerk
    HP_035 已由 hero_passives 批注册; Ragnaros HP_087 DEFERRED 于该批
    （Sulfuras 替换协议 + turn_end 未广播）; Saurfang BG20_HERO_102p /
    Rakanishu HP_085t / Tae'thelan BG28_HERO_800p / Enhance-o
    BG24_HERO_204p / Millhouse HP_054 为被动光环/计数——归被动批 +
    依赖 on_bind 接线与光环原语

引擎缺口汇总（报告主线）:
  1. **技能可用性协议**: use_hero_power 需咨询脚本声明（如
     ``available(hero, game) -> bool`` 或 needs_target 之外的门槛
     声明）——一条解冻: Tess（上对手无随从）/ Snake Eyes（冷却）/
     Kragg、Reno、Zerek（每局 N 次）/ 7 张 Unlocks 门槛卡
  2. **技能费动态覆写**: power CardDef.cost 静态——Elise 递增 /
     Togwaggle / Nobundo / Patches HP_072 "next Hero Power costs (1)
     less" 类阻塞
  3. **英雄技能替换协议**: hero_power_def 恒读 hero CardDef 静态链
     ——Rat King 轮换 / Ragnaros Sulfuras / Genn / Finley / Master
     Nguyen（hero_passives 批已报）
  4. **双目标选择**: PendingChoice 单目标——Vol'jin
  5. **"下一对手"查询**: 招募期配对未定——Scabbs
  6. on_bind 开局接线（hero_passives 批已报 #1）——本批 Edwin 依赖

池记账约定（本批裁定）:
  - 偷取（Xyrella/Pyramad/Baz'hial/Maieb）: 馆内实体本就占池——
    移入手牌**不 release 不 acquire**（净零，RULES §2.3 偷取语义）
  - 替换（Malygos）: 旧卡回池（minion release_minion_entity /
    spell release）、新卡 acquire——净零
  - 交换（Jandice）: 双方实体均已有主——零池操作
  - 生成金色（Eudora）: 基础卡 acquire min(3, available)（Lockbox
    _open_lockbox 先例; 金色出售经 TRIPLE_BASE_CARD_ID 返还 3 份闭环）
  - 复制（Rafaam）: 对局存在实体的 plain copy——不占池
    （game._plain_copy_to_hand 先例）
  - Remove（Hooktusk）: 友方随从移除不回池（consume SOP §4.12
    "友方不回池"先例）、不触发死亡/亡语（wiki mechanics
    "Remove from game"）
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2 import entity
from hsrl2.actions import Buff, GainKeyword
from hsrl2.actions.bloodgem import GetBloodGems
from hsrl2.actions.discover import Discover
from hsrl2.events import DEATH, MINION_BOUGHT, TURN_START, Listener
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Zone

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# events.py 未导出常量（引擎以字面量 fire，game.py:378 buy_from_tavern）
SPELL_BOUGHT = "spell_bought"


def _power_def(game: "Game", power_id: str):
    d = game.db.get(power_id)
    if d is None:
        raise GameStateError(f"unknown hero power {power_id!r}")
    return d


def _to_hand_from_tavern(game: "Game", hero: "Hero", target) -> None:
    """馆内实体移入手牌（偷取路径统一: 移出展示区 + 满手排队 P6）。"""
    if target in hero.tavern:
        hero.tavern.remove(target)
    game.pending_hand_add(hero, target)


def _weighted_exact_tier_draws(game: "Game", tier: int, count: int) -> list:
    """从池按剩余量加权抽取 count 张**恰好 tier** 随从 id。

    镜像 MinionPool.draw_tavern 的加权规则（RULES §2.4 剩余越少概率
    越低），但限定精确 tier（draw_tavern 是 ≤ tier 区间语义，不适合
    Toki "a Tier higher than yours"）。
    """
    drawn: list = []
    for _ in range(count):
        cands = game.minion_pool.candidates(max_tier=tier, min_tier=tier)
        if not cands:
            break
        weighted: list = []
        for cid in cands:
            weighted.extend([cid] * game.minion_pool.available(cid))
        pick = game.rng.choice(weighted, label="hero_active_tier_draw")
        if not game.minion_pool.acquire(pick):
            raise GameStateError(f"tier draw acquire failed for {pick}")
        drawn.append(pick)
    return drawn


# ═══════════════════ BG20_HERO_101p Xyrella — See the Light ═══════════════════


class XyrellaScript:
    """
    Natural language: [x]Choose a minion in the Tavern. Set its stats to
    2 and add it to your hand.

    Formal spec:
      1. 定向（wiki [Targeted]; needs_target）: 候选 = hero.tavern 中
         全部 Minion（"a minion in the Tavern"——馆内随从非棋盘）
      2. 效果: 选定随从移出酒馆（偷取语义: 池副本保持已消耗——本批
         模块 docstring 池记账约定）→ 属性 Set 为 2/2（wiki mechanics
         "Set attack"+"Set health": 逐个 remove_buff 剥离既有附魔后
         BASE_ATK/BASE_HEALTH/HEALTH 置 2——含酒馆持久 Buff 一并清除，
         Set 语义"设为该值"）→ pending_hand_add 入手（满手排队;
         入手自动三连检查）
      3. 扣费/计次由引擎完成（cost=2）

    Test: test_batch_hero_actives.py — 定向 PendingChoice 流 / 2/2 与
    buff 剥离 / 馆内移除 / 池净零 / 满手排队

    Params: stat=2（"Set its stats to 2"——文本字面量，CardDef 无模板
            参数; 攻/血同值）
    """

    needs_target = True

    @staticmethod
    def target_candidates(hero, game):
        return [e for e in hero.tavern if isinstance(e, Minion)]

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target not in hero.tavern:
            raise GameStateError("See the Light: target not in tavern")
        for b in target.buffs:
            target.remove_buff(b)
        target.set(GameTag.BASE_ATK, 2)
        target.set(GameTag.BASE_HEALTH, 2)
        target.set(GameTag.HEALTH, 2)
        _to_hand_from_tavern(game, hero, target)
        return None


# ═══════════════════ BG20_HERO_103p Blackthorn — Bloodbound ═══════════════════


class BlackthornScript:
    """
    Natural language: Get 2 <b>Blood Gems</b>. <i>(Twice per turn.)</i>

    Formal spec:
      1. uses_per_turn=2（"Twice per turn" 文本字面量; 引擎按
         HERO_POWER_USED_THIS_TURN 计次）
      2. hero_power: GetBloodGems(hero, 2)——2 颗血宝石进手牌（满手
         排队; 非池卡不占池; 数值经 BG20_GEM CardDef.num 权威，
         bloodgem 模块实现）

    Test: test_batch_hero_actives.py — 2 颗入手 + 扣 1 金 / 同回合第
    二次可用 / 第三次 False / 金币不足 False

    Params: count=2（"Get 2 Blood Gems"——文本字面量，CardDef 无模板
            参数）; uses=2（"Twice per turn" 文本字面量）
    """

    uses_per_turn = 2

    @staticmethod
    def hero_power(hero, game, ctx):
        return GetBloodGems(hero, 2)


# ═══════════════════ TB_BaconShop_HP_001 Edwin — Sharpen Blades ═══════════════════


class EdwinScript:
    """
    Natural language: [x]Give a minion +{1}/+{1}. Improves after you buy
    4 cards. <i>({0} left!)</i>

    Formal spec:
      1. 定向（wiki [Targeted]; needs_target）: 候选 = 友方棋盘存活
         随从（引擎默认）
      2. 计数: on_bind（与 hero_passives 批同协议——主线 start_game
         接线，测试显式调用）注册 minion_bought + spell_bought 双监听
         （owner=hero 整局存活）——"buy 4 cards" 官方 28.2 "minions"→
         "cards" 措辞修正后含法术; hero._edwin_buys 跨回合计数
      3. hero_power: 增量 = num(1) + hero._edwin_buys // num(0)（每
         满 num(0) 张 +1/+1——wiki mechanics "Upgradable"; patch 史
         "+1/+1 upgrade after 3" → 3/6/9 张时 +2/+3/+4 实证步长 1）
         → Buff(target, +增量/+增量)
      4. 未接线 on_bind 时计数恒 0（仅基础值）——主线缺口 #6

    Test: test_batch_hero_actives.py — 0 购买 buff=+num(1)/+num(1) /
    购买 num(0) 张后 +1（buff=3/3）/ 法术购买计入 / 敌方购买不计 /
    uses 与扣费

    Params: {0}=4（阈值=script_data_num_1; wiki TAG_SCRIPT_DATA_NUM_1=4
            印证） {1}=2（基础增益=script_data_num_2）; improve=1
            （步长文本字面量）
    """

    needs_target = True

    @staticmethod
    def on_bind(hero, game):
        # minion_bought 只带 minion=（不带 hero=）——控制者以闭包捕获的
        # 绑定英雄比对（spell_bought 带 hero= 但统一走实体 controller）
        def on_bought(g, minion=None, spell=None, _owner=hero, **kw):
            src = minion if minion is not None else spell
            if src is None or src.controller is not _owner:
                return
            _owner._edwin_buys = getattr(_owner, "_edwin_buys", 0) + 1

        game.events.register(Listener(
            event=MINION_BOUGHT, owner=hero, callback=on_bought))
        game.events.register(Listener(
            event=SPELL_BOUGHT, owner=hero, callback=on_bought))

    @staticmethod
    def hero_power(hero, game, ctx):
        d = _power_def(game, "TB_BaconShop_HP_001")
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion):
            raise GameStateError("Sharpen Blades: no target")
        gain = d.num(1) + getattr(hero, "_edwin_buys", 0) // d.num(0)
        return Buff(target, atk=gain, health=gain)


# ═══════════════════ TB_BaconShop_HP_010 George — Boon of Light ═══════════════════


class GeorgeScript:
    """
    Natural language: Give a minion <b>Divine Shield</b>.

    Formal spec:
      1. 定向（wiki [Targeted]; needs_target）: 候选 = 友方棋盘存活
         随从（引擎默认）; 空盘 → use_hero_power False（金币未扣——
         官方无合法目标不可用）
      2. hero_power: GainKeyword(target, DIVINE_SHIELD)——fire
         keyword_gained（可被第三方监听）

    Test: test_batch_hero_actives.py — PendingChoice 流 + 圣盾授予 +
    扣 1 金 / 空盘 False 金币不动

    Params: 无模板参数（关键词授予，无数值）
    """

    needs_target = True

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion):
            raise GameStateError("Boon of Light: no target")
        return GainKeyword(target, GameTag.DIVINE_SHIELD)


# ═══════════════════ TB_BaconShop_HP_022? no—024 Lich King — Reborn Rites ═══════════════════


class LichKingScript:
    """
    Natural language: [x]Give a minion <b>Reborn</b> until next turn.

    Formal spec:
      1. 定向（needs_target，引擎默认候选）: 友方棋盘存活随从
      2. hero_power: 目标已有 REBORN → 授予落空（不重复给、不注册
         过期监听——防止过期时误清其原生 Reborn; 官方对已复生目标
         使用的行为未公布，按无害落空）; 否则 GainKeyword(target,
         REBORN) + 过期链: 两个链式 TURN_START once 监听（owner=hero,
         condition hero is 控制者）——第 1 个控制者回合开始时注册第
         2 个、第 2 个触发时清除 REBORN（若仍持有; 战斗中已消耗则
         引擎自清）。"until next turn" = 下一个招募阶段开始（引擎
         "until next turn" 统一先例 scripts/spells _expire_at_next_
         turn; once 链自注销不残留）
      3. 金色/多目标: 每次使用独立监听链（幂等清除）

    Test: test_batch_hero_actives.py — 授予后战斗复生语义 tag 在位 /
    两个回合开始后清除 / 复生已消耗则无残留动作 / 已有 Reborn 目标
    不误清（第 2 回合开始仍持有）

    Params: turns=2（"until next turn" 到期 = 第 2 个回合开始——文本
            语义非数值参数）
    """

    needs_target = True

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion):
            raise GameStateError("Reborn Rites: no target")
        if target.has(GameTag.REBORN):
            return None
        ctrl = target.controller

        def tick2(g, hero=None, **kw):
            if target.has(GameTag.REBORN):
                target.clear(GameTag.REBORN)

        def tick1(g, hero=None, **kw):
            g.events.register(Listener(
                event=TURN_START, owner=ctrl, once=True,
                condition=lambda hero=None, _c=ctrl, **kw: hero is _c,
                callback=tick2))

        game.events.register(Listener(
            event=TURN_START, owner=ctrl, once=True,
            condition=lambda hero=None, _c=ctrl, **kw: hero is _c,
            callback=tick1))
        return GainKeyword(target, GameTag.REBORN)


# ═══════════════════ TB_BaconShop_HP_040 Pyramad — Brick by Brick ═══════════════════


class PyramadScript:
    """
    Natural language: [x]Steal a random minion from the Tavern.
    Double its Health.

    Formal spec:
      1. hero_power: 馆内 Minion 候选 rng.choice（"a random minion"——
         wiki mechanics Put into hand; 无候选 → 效果落空（金币已扣，
         GetRandomMinion 池空先例——馆内无法术实体时不可达的正常态）
      2. 偷取: 移出酒馆 → pending_hand_add（池净零——偷取不
         release/acquire，模块池记账约定）
      3. 翻倍: Buff(target, atk=0, health=target.max_health)——
         max_health 属性快照（SOP §3; 附魔叠加等效"上限×2"，当前
         血随 add_buff 同步 +旧上限 = 翻倍后满血）
      4. 金色馆内随从同规则（金色上限翻倍）

    Test: test_batch_hero_actives.py — 单随从馆确定性偷取 + 上限/当前
    血恰翻倍 / 攻击不变 / 池净零

    Params: 无模板参数（"Double"=×2 语义，无数值参数）
    """

    @staticmethod
    def hero_power(hero, game, ctx):
        cands = [e for e in hero.tavern if isinstance(e, Minion)]
        if not cands:
            return None
        pick = game.rng.choice(cands, label="brick_by_brick")
        _to_hand_from_tavern(game, hero, pick)
        return Buff(pick, atk=0, health=pick.max_health)


# ═══════════════════ TB_BaconShop_HP_068 Maiev — Imprison ═══════════════════


class MaievScript:
    """
    Natural language: [x]Choose a card in the Tavern to lock in your
    hand. After 2 turns, unlock it.

    Formal spec:
      1. 定向（"Choose" → PendingChoice; needs_target）: 候选 =
         hero.tavern 全部卡（随从+法术——"a card"）
      2. 偷取入手机: 移出酒馆 → LOCKED_IN_HAND=True（引擎 play 路径
         拒绝: play_minion/play_spell 均查锁）→ pending_hand_add
         （满手排队 P6; 池净零）
      3. 解锁: 链式 TURN_START once×2（Lich King 同款自注销链）——
         第 2 个控制者回合开始清除 LOCKED_IN_HAND（若仍持有; 卡已
         离手则无害 no-op）
      4. "After 2 turns": 使用回合 N（招募期）→ N+1 计 1 → N+2 解锁
         （锁定跨 N 剩余、N+1 全程，N+2 可用——wiki 无更细时序，按
         引擎 "until next turn" 家族对齐）

    Test: test_batch_hero_actives.py — 锁定卡入手中 LOCKED_IN_HAND /
    play_minion False / 2 个回合开始后可打出 / 解锁链不残留误解锁后续
    锁（第二次使用独立链）

    Params: turns=2（"After 2 turns"——文本字面量，CardDef 无模板参数）
    """

    needs_target = True

    @staticmethod
    def target_candidates(hero, game):
        return list(hero.tavern)

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if target is None or target not in hero.tavern:
            raise GameStateError("Imprison: target not in tavern")
        target.set(GameTag.LOCKED_IN_HAND, True)
        ctrl = hero

        def tick2(g, hero=None, **kw):
            if target.has(GameTag.LOCKED_IN_HAND):
                target.clear(GameTag.LOCKED_IN_HAND)

        def tick1(g, hero=None, **kw):
            g.events.register(Listener(
                event=TURN_START, owner=ctrl, once=True,
                condition=lambda hero=None, _c=ctrl, **kw: hero is _c,
                callback=tick2))

        game.events.register(Listener(
            event=TURN_START, owner=ctrl, once=True,
            condition=lambda hero=None, _c=ctrl, **kw: hero is _c,
            callback=tick1))
        _to_hand_from_tavern(game, hero, target)
        return None


# ═══════════════════ TB_BaconShop_HP_074 Eudora — Buried Treasure ═══════════════════


class EudoraScript:
    """
    Natural language: [x]_Dig for a Golden minion! <i>(@ |4(Dig, Digs)
    left.)</i>

    Formal spec:
      1. hero._eudora_digs_left 惰性初始化 num(0)（首次使用置 4;
      官方计数从开局展示即存在，惰性初始化不改变可观测行为——计数
      只在使用时递减）
      2. 每次 hero_power: 计数 -1; 归零时: 随机金色随从入手 + 计数
      重置 num(0)（官方行为: 挖到金色后继续下一轮，社区共识）
      3. 金色获取（Lockbox _open_lockbox 先例）: 候选 = 池内
      available>0 的全部池随从 id（全耗尽时退回全量池 id 仍给——
      作业单约定）; rng.choice → 基础卡 acquire min(3, available)
      份 → create_minion(基础 id, golden=True)（金色独立卡定义）
      → pending_hand_add; 不设 TRIPLE_REWARD_PENDING（非三连来源
      无三连奖励）
      4. 金色出售经 TRIPLE_BASE_CARD_ID 返还基础卡 3 份——池闭环

    Test: test_batch_hero_actives.py — 前 num(0)-1 次无金色 / 第
    num(0) 次金色入手且基础卡池 -3 / 计数重置（再挖 num(0) 次得第二
    个金色）/ 金色无三连奖励 tag

    Params: {0}=4（挖掘次数=script_data_num_1; wiki TAG_SCRIPT_DATA_
            NUM_1=4 印证，patch 30.4.3 5→4）
    """

    @staticmethod
    def hero_power(hero, game, ctx):
        d = _power_def(game, "TB_BaconShop_HP_074")
        left = getattr(hero, "_eudora_digs_left", None)
        if left is None:
            left = d.num(0)
        left -= 1
        if left > 0:
            hero._eudora_digs_left = left
            return None
        hero._eudora_digs_left = d.num(0)
        avail = [cid for cid in
                 (x.id for x in game.db.pool_minions())
                 if game.minion_pool.available(cid) > 0]
        cands = avail or [x.id for x in game.db.pool_minions()]
        if not cands:
            return None
        base_id = game.rng.choice(cands, label="buried_treasure")
        for _ in range(min(3, game.minion_pool.available(base_id))):
            if not game.minion_pool.acquire(base_id):
                raise GameStateError(
                    f"Buried Treasure acquire failed for {base_id}")
        golden = game.create_minion(base_id, controller=hero, golden=True)
        game.pending_hand_add(hero, golden)
        return None


# ═══════════════════ TB_BaconShop_HP_052 Malygos — Arcane Alteration ═══════════════════


class MalygosScript:
    """
    Natural language: [x]Replace a card with a  random one of the same
    Tier. <i>(Twice per turn.)</i>

    Formal spec:
      1. uses_per_turn=2（"Twice per turn" 文本字面量）
      2. 定向（官方 29.2 patch notes dev comment "This used to only
         target minions, now it ..." 实证; needs_target）: 候选 =
         hero.hand 全部卡（29.2 起 "minion"→"card" 含法术）
      3. 替换（类型保持裁定: 随从→同 tier 随从、法术→同 tier 法术
         ——"a random one of the same Tier" 从对应池抽取; 无候选 →
         保留原卡零池操作（池空落空，GetRandomMinion 先例））:
         - Minion: 旧实体 release_minion_entity 回池（金色 3 份/
           普通 1 份; token 不回池）→ candidates=池内同 tier 可用
           id（加权留给 acquire 语义: rng.choice 等权——官方权重
           未公布，池感知已足）→ acquire → create_minion 非金色
           基础版 → 手牌原位移除 + pending_hand_add（三连安全）
         - Spell: is_pool_spell 才可替换（血宝石/生成物无同 tier
           池语义 → 保留原卡）; spell_pool release 旧 + acquire 新
           同 tier → create_spell → pending_hand_add
      4. wiki mechanics Transform; Reddit "on a tier 7 minion"实证
         定向选择

    Test: test_batch_hero_actives.py — 手牌 T2 随从替换为 T2 池随从 +
    旧卡回池 / T2 法术→T2 法术 / 非 pool 法术保留 / 同回合 2 次第 3
    次 False / 金色旧卡回池 3 份

    Params: 无模板参数（同 tier 动态; uses=2 文本字面量）
    """

    uses_per_turn = 2
    needs_target = True

    @staticmethod
    def target_candidates(hero, game):
        return list(hero.hand)

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if target is None or target not in hero.hand:
            raise GameStateError("Arcane Alteration: target not in hand")
        d = game.db.get(target.card_id)
        if d is None:
            raise GameStateError(
                f"Arcane Alteration: unknown card {target.card_id!r}")
        tier = d.tech_level
        if isinstance(target, Minion):
            cands = game.minion_pool.candidates(max_tier=tier,
                                                min_tier=tier)
            if not cands:
                return None
            new_id = game.rng.choice(cands, label="arcane_alteration")
            if not game.minion_pool.acquire(new_id):
                raise GameStateError(
                    f"Arcane Alteration acquire failed for {new_id}")
            game.minion_pool.release_minion_entity(target)
            hero.hand.remove(target)
            target.zone = Zone.REMOVED
            new = game.create_minion(new_id, controller=hero)
        else:
            if not d.is_pool_spell:
                return None
            cands = [x.id for x in game.db.pool_spells()
                     if x.tech_level == tier
                     and game.spell_pool.available(x.id) > 0]
            if not cands:
                return None
            new_id = game.rng.choice(cands, label="arcane_alteration")
            if not game.spell_pool.acquire(new_id):
                raise GameStateError(
                    f"Arcane Alteration acquire failed for {new_id}")
            game.spell_pool.release(target.card_id)
            hero.hand.remove(target)
            target.zone = Zone.REMOVED
            new = game.create_spell(new_id, controller=hero)
        game.pending_hand_add(hero, new)
        return None


# ═══════════════════ TB_BaconShop_HP_084 Jandice — Swap, Lock, & Shop It ═══════════════════


class JandiceScript:
    """
    Natural language: [x]Swap a friendly non-Golden minion with a random
    one in the Tavern.

    Formal spec:
      1. 定向（社区实证定向友方——模块 docstring 选卡依据; needs_target）:
         候选 = 友方棋盘存活**非金色**随从（"non-Golden" 明确排除）
      2. 随机侧: 馆内 Minion rng.choice（"a random one in the
         Tavern"——馆内法术不可为交换对象）; 馆内无随从 → 交换落空
         （金币已扣，池空落空先例; 官方该状态可用性未公布）
      3. 交换 = 区域互换非召唤: 友方随从（含全部 buff/状态——社区
         实证 note.com "return it to the Tavern, ... then buy"）
         入馆占原馆位; 馆内随从上板占原板位; _update_positions;
         **不 fire summon/on_summon**（非召唤语义裁定——不触发
         "whenever you summon" 类）; 池零操作（双方实体均已有主）
      4. 上板随从满血已在（馆内实体无受损态）

    Test: test_batch_hero_actives.py — 交换后板/馆互置且 buff 保留 /
    金色随从不在候选 / 馆内无法术干扰 / 满板不适用（板位原位替换）

    Params: 无模板参数（无数值）
    """

    needs_target = True

    @staticmethod
    def target_candidates(hero, game):
        return [m for m in hero.board if not m.dead and not m.is_golden]

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target not in hero.board:
            raise GameStateError("Swap Lock & Shop It: bad target")
        tavern_minions = [e for e in hero.tavern
                          if isinstance(e, Minion)]
        if not tavern_minions:
            return None
        pick = game.rng.choice(tavern_minions, label="jandice_swap")
        board_idx = hero.board.index(target)
        tavern_idx = hero.tavern.index(pick)
        hero.board[board_idx] = pick
        pick.zone = Zone.PLAY
        pick.controller = hero
        hero.tavern[tavern_idx] = target
        target.zone = Zone.TAVERN
        game._update_positions(hero)
        return None


# ═══════════════════ TB_BaconShop_HP_049 Baz'hial — Graveyard Shift ═══════════════════


class BazhialScript:
    """
    Natural language: [x]Steal a card from the Tavern. Take 2 damage.

    Formal spec:
      1. 定向（wiki [Targeted]; needs_target）: 候选 = hero.tavern
         全部卡（31.2 起 "a card" 含法术）
      2. 偷取: 移出酒馆 → pending_hand_add（池净零; 满手排队）
      3. 自伤: hero.take_damage(2)——护甲先扣（RULES §1.3）; fire
         HERO_DAMAGE_TAKEN（Soul Rewinder 类监听照常触发）; "2" 为
         31.2 定值（27.0 前为"等同于其 tier"）
      4. 生命不足以承受（health+armor ≤ 2）: 官方可用性未公布——
         引擎 take_damage 无守卫，照常执行（可致死，与 Malchezaar
         健康刷新守卫不同的路径——记录为边缘）

    Test: test_batch_hero_actives.py — 偷卡入手 + 血-2 / 有护甲先扣 /
    扣 2 金 / PendingChoice 流

    Params: damage=2（"Take 2 damage"——文本字面量，CardDef 无模板参数）
    """

    needs_target = True

    @staticmethod
    def target_candidates(hero, game):
        return list(hero.tavern)

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if target is None or target not in hero.tavern:
            raise GameStateError("Graveyard Shift: target not in tavern")
        _to_hand_from_tavern(game, hero, target)
        hero.take_damage(2)
        return None


# ═══════════════════ TB_BaconShop_HP_053 Rafaam — I'll Take That! ═══════════════════


class RafaamScript:
    """
    Natural language: [x]Next combat, get a plain copy of the first
    minion you kill.

    Formal spec:
      1. hero_power: 装填 token（hero._rafaam_token = 本次序号）+
         注册两条 once 监听（owner=hero）:
         - DEATH: 条件 minion.controller is not hero（敌方死亡——
           wiki Notes "triggers even when minions die from attacking
           the player's minions"，反击致死亦算; 死亡波次按板位序
           → 首个 qualifying death = 最左（顺劈同时多杀取最左实证）;
           我方/馆内死亡不触发）; 回调: token 匹配（旧装填未 fired
           的监听因 token 已被新装填覆盖而失能）→ 清 token →
           create_minion(其 card_id, golden=is_golden) plain copy
           （不转移 buff——"plain"; 金色源→金色副本，Scabbs 同款
           官方语义）→ pending_hand_add（不占池——对局存在实体的
           副本，_plain_copy_to_hand 先例）
         - TURN_START: 条件控制者; token 仍为本次 → 清（"next
           combat" 窗口 = 使用回合的战斗; 该场无击杀则装填作废）
      2. 战斗期死亡产生副本进手牌（手牌不受战斗快照回滚影响）
      3. 幽灵战死亡同样触发（敌方 = ghost 临时实体）

    Test: test_batch_hero_actives.py — 战斗击杀首个敌方死亡 → plain
    副本入手（无 buff、不占池）/ 双杀只复制首个 / 下一回合开始后装填
    作废（后续死亡无副本）/ 再次使用重新装填

    Params: 无模板参数（无数值）
    """

    @staticmethod
    def hero_power(hero, game, ctx):
        token = object()
        hero._rafaam_token = token

        def on_death(g, minion=None, **kw):
            if hero._rafaam_token is not token or minion is None:
                return
            if minion.controller is hero:
                return
            hero._rafaam_token = None
            copy = g.create_minion(minion.card_id, controller=hero,
                                   golden=minion.is_golden)
            g.pending_hand_add(hero, copy)

        def on_turn_start(g, hero=None, **kw):
            if hero is not None and hero._rafaam_token is token:
                hero._rafaam_token = None

        # 条件过滤敌方死亡（条件不过 once 不消费——我方/馆内死亡不得
        # 烧掉装填; EventBus once 仅在 condition 通过时移除）
        game.events.register(Listener(
            event=DEATH, owner=hero, once=True,
            condition=lambda minion=None, _h=hero, **kw:
                minion is not None and minion.controller is not _h,
            callback=on_death))
        game.events.register(Listener(
            event=TURN_START, owner=hero, once=True,
            condition=lambda hero=None, _h=hero, **kw: hero is _h,
            callback=on_turn_start))
        return None


# ═══════════════════ TB_BaconShop_HP_028 Infinite Toki — Temporal Tavern ═══════════════════


class TokiScript:
    """
    Natural language: [x]<b>Refresh</b> the Tavern. _Include two minions
    from a Tier higher than yours.

    Formal spec:
      1. 刷新: game.refresh_tavern(hero, auto=False, free=True,
         spells_only=False)——Saloon's Finest 先例（技能费已含刷新;
         引擎路径先消耗 FREE_REFRESH_REMAINING 再 free 免金币——
         Nozdormu 免费次数协同为引擎语义）; 冻结整馆保留（P5）;
         旧内容回池（P1）由引擎保证
      2. 高 tier 注入: 刷新**新抽**的馆内随从（冻结保留项不动——
         冻结语义优先裁定）中 rng.sample 2 只 → 逐只移出+回池 →
         _weighted_exact_tier_draws(tier+1, 2) 恰好高一 tier 的
         加权抽取（RULES §2.4 剩余加权; 追加到馆尾）; 新抽随从不足
         2 只则替换不足 2 只; tier+1 池空（T6 无 T7）→ 注入落空
         （刷新照常——官方 T6 行为未公布，按池空落空先例）
      3. "a Tier higher" = 恰好 tier+1（非 tier+1..6 区间）

    Test: test_batch_hero_actives.py — T2 使用后馆内恰 2 只 T3 新随从 /
    被替换的旧随从回池 / T6 无 T7 注入落空但刷新成立

    Params: count=2（"two minions"——文本字面量，CardDef 无模板参数）
    """

    @staticmethod
    def hero_power(hero, game, ctx):
        keep = list(hero.tavern) if hero.frozen_tavern else []
        game.refresh_tavern(hero, auto=False, free=True)
        new_minions = [e for e in hero.tavern
                       if isinstance(e, Minion) and e not in keep]
        k = min(2, len(new_minions))
        replaced = game.rng.sample(new_minions, k,
                                   label="temporal_tavern_replace") \
            if k > 0 else []
        for e in replaced:
            hero.tavern.remove(e)
            game.minion_pool.release(e.card_id, 1)
        higher = hero.tavern_tier + 1
        for card_id in _weighted_exact_tier_draws(game, higher,
                                                  len(replaced)):
            m = game.create_minion(card_id, controller=hero)
            m.zone = Zone.TAVERN
            hero.tavern.append(m)
        return None


# ═══════════════════ TB_BaconShop_HP_075 Hooktusk — Trash for Treasure ═══════════════════


class HooktuskScript:
    """
    Natural language: [x]Remove a friendly minion. <b>Discover</b> one
    from a Tier lower to get.

    Formal spec:
      1. 定向（wiki [Targeted]; needs_target）: 候选 = 友方棋盘存活
         随从（引擎默认）
      2. Remove（wiki mechanics "Remove from game"）: 移出棋盘、
         zone=REMOVED、注销其监听器; **不触发 death/亡语/Avenge**
         （非 Destroy）; **不回池**（consume SOP §4.12 "友方不回池"
         先例——wiki Remove from game 语义）
      3. Discover(hero, min_tier=1, max_tier=被移除随从 tech_level-1)
         ——"from a Tier lower"= 严格低于其 tier; tier-1=0（T1 目标）
         → 无候选效果落空（官方 T1 目标行为未公布，池空落空先例）
      4. 发现池感知 + 选中 acquire（Discover Action 语义）

    Test: test_batch_hero_actives.py — T2 随从移除（板位消失、无亡语、
    池不变）→ Discover(kind=discover_minion) 限 T1 → resolve 入手占池

    Params: 无模板参数（tier-1 动态）
    """

    needs_target = True

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target not in hero.board:
            raise GameStateError("Trash for Treasure: bad target")
        tier = target.tech_level
        hero.board.remove(target)
        game._update_positions(hero)
        target.zone = Zone.REMOVED
        game.events.unregister_owner(target)
        return Discover(hero, min_tier=1, max_tier=tier - 1)


# ═══════════════════ BG34_HERO_001p Chromie — Mana Per Minute ═══════════════════


class ChromieScript:
    """
    Natural language: <b>Refresh</b> the Tavern with Tavern spells.

    Formal spec:
      1. hero_power: game.refresh_tavern(hero, auto=False, free=True,
         spells_only=True)——BG28_849 Saloon's Finest（batch_misc）
         同款引擎路径: 旧内容回池后只抽法术（数量 = TAVERN_OFFERS
         [tier] − 冻结保留数）; 冻结整馆保留/Fodder 附加/
         tavern_refresh 广播由引擎统一保证
      2. cost=3 已含刷新费（free=True 不另扣 1 金）

    Test: test_batch_hero_actives.py — 使用后馆内全为法术 / 数量=
    该 tier 展示数 / 不扣额外刷新费

    Params: 无模板参数（无数值）
    """

    @staticmethod
    def hero_power(hero, game, ctx):
        game.refresh_tavern(hero, auto=False, free=True, spells_only=True)
        return None


# ═══════════════════ BG28_HERO_801p Holli'dae — Blessing of the Nine Frogs ═══════════════════


class HollidaeScript:
    """
    Natural language: Get a random Tavern spell.

    Formal spec:
      1. hero_power: 候选 = 池内（spell_pool.available>0）tech_level ≤
         hero.tavern_tier 的酒馆法术（tier 范围官方未公布——Mystic
         Essence gift（game.py）同裁定: ≤ 当前酒馆等级，与
         SpellPool.draw_tavern 一致）; 池内该区间耗尽 → 退回全量
         池法术仍给（Lockbox/Mystic 先例）; 全空 → 落空
      2. rng.choice → spell_pool.acquire（占池）→ create_spell →
         pending_hand_add（满手排队）
      3. 打出后照常回池（play_spell is_pool_spell release 语义）

    Test: test_batch_hero_actives.py — 使用后手牌 +1 法术且为池法术 /
    该法术池占用 / tier 不超当前酒馆等级

    Params: 无模板参数（无数值）
    """

    @staticmethod
    def hero_power(hero, game, ctx):
        in_range = [x.id for x in game.db.pool_spells()
                    if x.tech_level <= hero.tavern_tier]
        cands = [sid for sid in in_range
                 if game.spell_pool.available(sid) > 0]
        if not cands:
            cands = [x.id for x in game.db.pool_spells()
                     if game.spell_pool.available(x.id) > 0]
        if not cands:
            return None
        sid = game.rng.choice(cands, label="nine_frogs_spell")
        if not game.spell_pool.acquire(sid):
            raise GameStateError(
                f"Nine Frogs acquire failed for {sid}")
        game.pending_hand_add(hero, game.create_spell(sid,
                                                      controller=hero))
        return None


def register() -> list[str]:
    """注册本批次 16 张主动技能（技能卡 id; AMBIGUOUS Inge 不注册）。"""
    from hsrl2.scripts.registry import register as reg

    registered: list[str] = []
    for power_id, script in (
        ("BG20_HERO_101p", XyrellaScript),
        ("BG20_HERO_103p", BlackthornScript),
        ("TB_BaconShop_HP_001", EdwinScript),
        ("TB_BaconShop_HP_010", GeorgeScript),
        ("TB_BaconShop_HP_024", LichKingScript),
        ("TB_BaconShop_HP_028", TokiScript),
        ("TB_BaconShop_HP_040", PyramadScript),
        ("TB_BaconShop_HP_049", BazhialScript),
        ("TB_BaconShop_HP_052", MalygosScript),
        ("TB_BaconShop_HP_053", RafaamScript),
        ("TB_BaconShop_HP_068", MaievScript),
        ("TB_BaconShop_HP_074", EudoraScript),
        ("TB_BaconShop_HP_075", HooktuskScript),
        ("TB_BaconShop_HP_084", JandiceScript),
        ("BG28_HERO_801p", HollidaeScript),
        ("BG34_HERO_001p", ChromieScript),
    ):
        reg(power_id, script)
        registered.append(power_id)
    return registered
