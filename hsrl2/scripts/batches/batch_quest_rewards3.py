"""批次 quest_rewards3 — 任务奖励第三批（10 张奖励 + 6 张必需 token 法术）。

数据来源: `data/bg_quest_rewards.json` / `data/bg_cards.json`（CardDB）。
所有数值经 `CardDef.num(0..3)`（模板参数 {0}..{3} 的权威值）; 文本无
占位符的数值按 SOP §3 以文本字面量实现并在各类 `Params:` 行声明。

实现（10 张奖励 + 6 个 token id）:
  BG24_Reward_134   The Friends Along the Way — SoT: 获取 2 个随机 {0}
                      （num(0)=92=Race.NAGA——XML `BACON_MINION_TYPE_REWARD`
                      证实 {0} 是随从类型而非卡名）
  BG24_Reward_306   Cooked Book      — 买入随从后 +num(0)/+num(1) 并
                      "improve this"（每次买入增量 = 初始值，R361 先例）
  BG24_Reward_310   Partner in Crime — 获得本英雄的**金色伙伴**
                      （hero def → companion_id → golden_version）
  BG24_Reward_715   Enhance-a-matic  — SoT: 获得一张随机 Enhanced Part
                      （+5/+5 与随机附加关键词之一）; 4 张 token 法术一并
                      注册（BG24_Reward_715t/t2/t3/t4）
  BG24_Reward_718   Kidnap Sack      — Spellcraft 奖励（on_bind + SoT
                      各发一张 token 法术）; token BG24_Reward_718t
  BG28_Reward_505   Tumbling Disaster — 战斗中召唤随从 +@/+@; Avenge(4)
                      永久 improve（增量 = num(0)）
  BG28_Reward_509   Smelting Chamber — SoT: 使一个友方 Tier @ 随从金色化
                      并 improve（@ 每回合 +1，初始 num(0)=1）
  BG28_Reward_513   Open Auditions   — SoT: Discover 一个 Buddy
  BG33_Reward_006   Rushing Winds    — Spellcraft 奖励; token
                      BG33_Reward_006t（+Windfury +Divine Shield）
  BG33_Reward_020   Perpetual Incantation — 酒馆法术额外 +{3}/+{1}
                      （num(3)=2 攻 / num(1)=1 生命）

引擎接线核实（SOP §14 "假接线" 排查——读取方均为真实生产路径）:
  - SoT 分发: `game._begin_recruit_for` 对 `hero.quest_rewards` 逐个调用
    `run_script_hook(reward, "start_of_turn")`（game.py:236-240）
  - 买入事件: `buy_from_tavern` fire "minion_bought"（game.py:515）
  - 战斗召唤: `game.summon` fire "summon"（game.py:826），`game.in_combat`
    为战斗阶段标志
  - Avenge: `_process_single_death` 对 `hero.quest_rewards` 统一计数并调
    `avenge`（game.py:1625-1641; 仅 `in_combat or _active_combat`），
    CombatScheduler 每场开始清零 AVENGE_COUNTER
  - 金色化: `batch_quest_rewards._goldenize`（Reno/Sanders 同源; 打
    GILDED_NOT_TRIPLED 走非三连金回池口径）
  - 伙伴: `Hero` CardDef.companion_id（109 位英雄有值）→
    `CardDB.by_dbf` → `CardDB.golden_version`（`_Buddy` → `_Buddy_G`）
  - Spellcraft 奖励侧授予: `spellcraft.grant_spellcraft_spell(source, game)`
    只读 `CardDef.spellcraft_id` 与 `source.controller`（不要求 source 是
    随从）——先例 `batch_trinkets2.PreciousPearlScript`（饰品同款
    on_bind + SoT）；未使用法术由 `end_recruit_phase` 按 SPELLCRAFT tag
    统一丢弃（RULES §6.13）
  - 酒馆法术增幅: `racefx.tavern_spell_buff` 读 hero 的
    TAVERN_SPELL_EXTRA_ATK/HEALTH（生产调用点遍布池法术脚本）
  - Buddy 发现: buddy 不在共享池（RULES §2）→ 零池操作
    （batch_hero_actives2.ETCScript 同口径：全部 `_Buddy` 非金卡）

DEFERRED（15 张奖励 + 1 token，不注册; 依赖逐条列出——宁缺毋错）:
  BG24_Reward_113 Ritual Dagger      — "After a friendly Deathrattle
    minion dies, give it +5/+5 permanently." 死亡时点实体已被移出棋盘
    （zone=GRAVEYARD），且战斗期增益默认被战后快照恢复回滚。缺**逐 Buff
    的持久化标记**（引擎仅有实体级 PERSIST_COMBAT_CHANGES/PERSIST_DOUBLE，
    会保留该随从全部战斗期变化且须战前设置）; wiki 无 Notes 佐证
    "give it +5/+5"在死亡实体上的可观测语义 → 撤注册。
  BG24_Reward_130 Ghastly Mask        — 文本 "Get a copy of '{0}'" 的 {0}
    来自 XML Tag2673 `BACON_CARD_DBID_REWARD`（实测 dbf 59707 =
    Bgs_009 Lightfang Enforcer），但生成器未导出该字段（data 无权威）→
    Dependency: tools/generate_bg_data.py 导出 reward_card_id。
  BG24_Reward_135 Yogg-tastic Tasties — "spin the Wheel of Yogg-Saron"：
    轮盘结果表无任何数据权威（data 无 Wheel token/表），且缺轮盘子系统。
  BG24_Reward_313 Wondrous Wisdomball — "Occasionally gives helpful
    Refreshes"：触发概率与"helpful Refresh"类别表均无数据权威
    （XML 仅 TRIGGER_VISUAL; wiki 无 Notes）。
  BG24_Reward_362 Essence of Zerus    — 授予物 Shifter Zerus（BGS_029）
    存在于 bg_cards.json，但其"Each turn this is in your hand, transform
    it into a random minion"手牌变形脚本未实现，且该卡不在
    bg_pool_minions.json（非池卡）。Dependency: BGS_029 手牌变形脚本 +
    "a random minion"的 tier 口径权威。
  BG24_Reward_719 The Golden Hammer   — Spellcraft 法术为 "Make a
    friendly minion Golden **until next turn**"：缺"临时金色"原语
    （无 GOLDEN_UNTIL/temporary 金色 tag，金色化后无引擎级回滚点;
    引擎 clear_temporary_buffs 无调用点且不处理卡定义回退）。
  BG27_Reward_802 Gilnean War Horn    — {0}（同 130）。
  BG27_Reward_803 Turbulent Tombs     — {0}（同 130）。
  BG27_Reward_812 Scepter of Guidance — "The Tavern always offers 2 {0}
    (Naga) whenever it is Refreshed"：`refresh_tavern(races=...)` 只支持
    **全量**种族白名单（race_filter 过滤掉全部非该种族），无"保证 N 个
    展示位为该种族"的钩子。Dependency: refresh_tavern 的 per-slot 种族
    保证参数。
  BG28_Reward_500 Beyond the Mirage   — "Tavern spells cost (1) less"：
    缺**常驻**酒馆法术折扣钩子（引擎只有一次性
    NEXT_SPELL_COST_REDUCTION，成交即清零）。
  BG28_Reward_501 Temporal Tampering  — "Your Tavern spells cast an extra
    time"：SPELL_DOUBLER 只在 `_finish_play_spell` 扫**棋盘随从**且仅对
    "定向友方随从"法术生效（game.py:945-961），奖励实体不在扫描源且
    "Tavern spells"含非定向/非友方法术 → 注册即假接线。
  BG28_Reward_510 Secret Culprit      — {0}（同 130）。
  BG33_Reward_011 Magicfin Relic      — "Discover a Tavern spell to
    **teach** it"：无"教会随从法术"子系统（教会后的复读/施放语义与
    1/1 Murloc token 数据链均缺）。
  BG33_Reward_017 Cosmic Reward       — "Discover a second Hero Power"：
    无第二英雄技能槽子系统（Hero 只有单一 hero_power_def 通道）。
  BG33_Reward_021 Rallying Cry        — {0}（同 130），且第二句
    "Your Rallies trigger an extra time" 缺 RALLY 翻倍消费点
    （引擎仅 BATTLECRY/DEATHRATTLE doubler）。
  BG27_Anomaly_555t No Place Like Holmes — 猜谜 token："Guess which minion
    your next opponent had last combat" 的正确答案校验所需快照引擎已有
    （`next_opponent(hero).last_combat_board`，RULES §4.8a），但 token
    文本未载明**答对/答错的回报**（回报只出现在异常卡 555 的
    "…for a Coin"，本 token 无），"2 选 1 提供项 + 结算"协议亦无权威
    → 撤注册，等待回报数值/协议信源。
"""

from __future__ import annotations

from hsrl2.actions import Buff, GainKeyword, GetRandomMinion
from hsrl2.entity import Buff as Enchant
from hsrl2.events import MINION_BOUGHT, SUMMON, Listener
from hsrl2.game import PendingChoice
from hsrl2.minion import Minion
from hsrl2.scripts.batches.batch_quest_rewards import _goldenize
from hsrl2.spellcraft import grant_spellcraft_spell
from hsrl2.tags import GameTag, Race

# ── token / 数据链常量（CardDB 按名核实——SOP §11 教训 5）──
ENHANCED_PART_IDS = (
    "BG24_Reward_715t",      # Mega Horn        +5/+5 & Taunt
    "BG24_Reward_715t2",     # Blazing Blades   +5/+5 & Windfury
    "BG24_Reward_715t3",     # Bunker Plating   +5/+5 & Divine Shield
    "BG24_Reward_715t4",     # Death Rewinder   +5/+5 & Reborn
)
KIDNAP_SACK_SPELL_ID = "BG24_Reward_718t"
RUSHING_WINDS_SPELL_ID = "BG33_Reward_006t"

# 随机 Bonus 的映射（token 文本核实: 4 张 token 各带一个关键词）
_ENHANCED_PART_KEYWORDS = {
    "BG24_Reward_715t": GameTag.TAUNT,
    "BG24_Reward_715t2": GameTag.WINDFURY,
    "BG24_Reward_715t3": GameTag.DIVINE_SHIELD,
    "BG24_Reward_715t4": GameTag.REBORN,
}


def register() -> list[str]:
    """注册任务奖励批 3（10 张奖励 + 6 张必需 token 法术）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG24_Reward_134", FriendsAlongTheWayScript),
        ("BG24_Reward_306", CookedBookScript),
        ("BG24_Reward_310", PartnerInCrimeScript),
        ("BG24_Reward_715", EnhanceAMaticScript),
        ("BG24_Reward_715t", EnhancedPartTauntScript),
        ("BG24_Reward_715t2", EnhancedPartWindfuryScript),
        ("BG24_Reward_715t3", EnhancedPartDivineShieldScript),
        ("BG24_Reward_715t4", EnhancedPartRebornScript),
        ("BG24_Reward_718", KidnapSackScript),
        ("BG24_Reward_718t", KidnapSackSpellScript),
        ("BG28_Reward_505", TumblingDisasterScript),
        ("BG28_Reward_509", SmeltingChamberScript),
        ("BG28_Reward_513", OpenAuditionsScript),
        ("BG33_Reward_006", RushingWindsScript),
        ("BG33_Reward_006t", RushingWindsSpellScript),
        ("BG33_Reward_020", PerpetualIncantationScript),
    ]
    registered = []
    for rid, cls in pairs:
        reg(rid, cls)
        registered.append(rid)
    return registered


# ══════════════════ BG24_Reward_134 The Friends Along the Way ══════════

class FriendsAlongTheWayScript:
    """
    Natural language: At the start of each turn, get 2 random {0}.

    Formal spec:
      1. {0} 是**随从类型**而非卡名: XML Tag2571
         `BACON_MINION_TYPE_REWARD=1` + Tag2 `TAG_SCRIPT_DATA_NUM_1=92`
         （92 = Race.NAGA，与 DBF_RACE_TO_ENUM 一致）→ 每回合开始获取
         **2 个随机纳迦**
      2. start_of_turn（引擎按饰品 → 任务奖励 → 随从顺序分发，
         game.py:236-240）——只在本奖励控制者的招募回合开始触发
      3. "get 2 random" = 两次独立 `GetRandomMinion(race=NAGA)`：
         每次从池中按剩余量加权抽取并 `minion_pool.acquire` 占池
         （RULES §2.3/§2.4），经 `pending_hand_add` 入手（满手排队
         RULES §3.3）; 文本无 tier 子句 → 引擎随机获取缺省口径
         （池内全体，无 min/max tier 限定）
      4. 两次抽取独立（可抽出同一 card_id 的两个副本——"2 random"
         非"2 different"）
      5. 池空/无纳迦 → 该次落空（GetRandomMinion 语义，非静默截断）

    Test: test_batch_quest_rewards3.py — 真实 `_begin_recruit_for` 后
      手牌 +2 且两张均为 Naga（含 ALL）/ 直接 hook 调用恰好占池 2 份 /
      第二回合再 +2 / 对手回合与对手手牌不受影响

    Params: count=2 race=num(0)=92（Race.NAGA——XML 2571 证实 {0} 为类型）
    """

    @staticmethod
    def start_of_turn(source, game, ctx):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        race_val = d.num(0) if d is not None else None
        if race_val is None:
            return None       # 数据缺模板参数 → 不近似实现
        try:
            race = Race(race_val)
        except ValueError:
            return None       # 非种族枚举（数据漂移）→ 落空
        return [GetRandomMinion(hero, race=race),
                GetRandomMinion(hero, race=race)]


# ══════════════════ BG24_Reward_306 Cooked Book ══════════

class CookedBookScript:
    """
    Natural language: After you buy a minion, give it +{0}/+{1} and
    improve this.

    Formal spec:
      1. "improve this" = 效果数值每次触发递增（"Improve" 家族口径）;
         增量 = 初始模板值 num(0)/num(1)（R361 "gain @ Gold (Improves
         each turn!)" 已确立的引擎外脚本惯例——@/{N} 的当前值 = 初始值
         + n×初始值; 文本无第二个增量参数）
      2. on_bind: 监听 "minion_bought"（buy_from_tavern 在入手后 fire,
         game.py:515）——只对本奖励控制者买入的随从生效
         （minion.controller is hero）
      3. 每次触发: `Buff(bought, atk=当前值, health=当前值)` 作用于
         **刚买入的随从**（手牌实体，可携带附魔）; 随后当前值 +=
         num(0)/num(1)
      4. 已买入的旧随从不再受影响（仅"give **it**"）
      5. 招募期死亡/出售不在本效果范围（随从入手时点即结算）

    Test: test_batch_quest_rewards3.py — 真实 buy_from_tavern 两次:
      第一只 +2/+2、第二只 +4/+4（improve），第一只不再变化 /
      对手买入不触发 / 非本英雄奖励不沾

    Params: {0}=2 {1}=2（CardDef 模板参数; 增量同值——Improve 惯例）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero") if ctx else getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        if d is None:
            return None
        atk0, health0 = d.num(0), d.num(1)
        if atk0 is None or health0 is None:
            return None       # 模板参数缺失 → 不近似实现
        state = {"atk": atk0, "health": health0}

        def on_bought(g, minion=None, _h=hero, _st=state, **kw):
            if minion is None or minion.controller is not _h:
                return
            g.run_actions(Buff(minion, atk=_st["atk"], health=_st["health"]))
            _st["atk"] += atk0
            _st["health"] += health0

        game.events.register(Listener(event=MINION_BOUGHT, owner=source,
                                      callback=on_bought))
        return None


# ══════════════════ BG24_Reward_310 Partner in Crime ══════════

class PartnerInCrimeScript:
    """
    Natural language: [x]Get your Golden <b>Buddy</b>.

    Formal spec:
      1. "your Buddy" = 本英雄的伙伴随从（Hero CardDef.companion_id —
         XML BACON_COMPANION_ID → dbf id; 109 位英雄有值）
      2. "Golden" = 伙伴的独立金色卡定义（`CardDB.golden_version`
         → `_Buddy_G`），经 `create_minion(golden=True)` 授予
         （引擎置 GOLDEN + TRIPLE_BASE_CARD_ID，非"数值×2"近似）
      3. 入手: `pending_hand_add`（满手排队等待不销毁，RULES §3.3）
      4. 伙伴不在共享池（RULES §9.4/§2）→ **零池操作**（不 acquire/
         release; 出售时按 MINION_SELL_VALUE 走一般路径但伙伴本就不
         占池——与 batch_hero_actives2 Buddy 发现同口径）
      5. 英雄定义缺失 companion_id / 无金色版本 → 落空（不近似）
      6. on_bind 一次性结算（文本无时机子句 = 获得奖励时立即）

    Test: test_batch_quest_rewards3.py — 真实 complete_quest 后手牌出现
      本英雄的 `_Buddy_G`（card_id/属性/TRIPLE_BASE_CARD_ID 与
      CardDef 一致）/ 池记账不变 / 对手手牌不变 / 无伙伴英雄落空

    Params: 无模板参数（伙伴 id 经 hero CardDef.companion_id 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero") if ctx else getattr(source, "controller", None)
        if hero is None:
            return None
        hero_def = game.db.get(hero.card_id)
        if hero_def is None or hero_def.companion_id is None:
            return None
        buddy = game.db.by_dbf(hero_def.companion_id)
        if buddy is None or game.db.golden_version(buddy) is None:
            return None       # 无金色独立定义 → 不近似
        m = game.create_minion(buddy.id, controller=hero, golden=True)
        if m is None:
            return None
        game.pending_hand_add(hero, m)
        return None


# ══════════════════ BG24_Reward_715 Enhance-a-matic ══════════

class EnhanceAMaticScript:
    """
    Natural language: [x]At the start of each turn, get an Enhanced Part
    that gives +5/+5 and a random bonus.

    Formal spec:
      1. "an Enhanced Part" = 4 张 token 法术之一（BG24_Reward_715t/t2/
         t3/t4——Mega Horn / Blazing Blades / Bunker Plating /
         Death Rewinder，各自文本 "Give a minion +5/+5 and <关键词>"）
      2. "a random bonus" = 四个关键词（Taunt / Windfury / Divine Shield
         / Reborn）中随机一个 → `game.rng.choice` 等权抽取 token id
         （各关键词无公布权重 → 等权，Malygos 裁定先例）
      3. start_of_turn: 每招募阶段开始发一张 → create_spell +
         `pending_hand_add`（满手排队 RULES §3.3）
      4. token 为非池法术（card_type=5，不在 bg_pool_spells.json）
         → **零池操作**（token 语义 SOP §3）
      5. 只发本奖励控制者（owner 隔离）

    Test: test_batch_quest_rewards3.py — 真实 `_begin_recruit_for` 后手牌
      +1 且 card_id ∈ 4 张 token / 连续两回合各 +1 / 池记账不变 /
      对手手牌不变 / 4 张 token 各自打出后目标 +5/+5 且获得对应关键词

    Params: 无模板参数（+5/+5 在 token 卡文本与 token 脚本 Params 中）
    """

    @staticmethod
    def start_of_turn(source, game, ctx):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        cid = game.rng.choice(list(ENHANCED_PART_IDS),
                              label="enhance_a_matic_part")
        spell = game.create_spell(cid, controller=hero)
        if spell is None:
            return None
        game.pending_hand_add(hero, spell)
        return None


class EnhancedPartTauntScript:
    """
    Natural language: Give a minion +5/+5 and <b>Taunt</b>.
    （BG24_Reward_715t "Mega Horn"——Enhance-a-matic 的 token 法术）

    Formal spec:
      1. needs_target=True → play_spell 产生 PendingChoice(
         kind="spell_target")（候选默认全体友方存活随从，game.py:923-934）
      2. on_play: 失活/越界 target 落空（SOP §16 模式 24——目标挂起期
         可能已离场）; 合法 target（友方棋盘存活随从）获得
         `Buff(+5/+5)` + `GainKeyword(TAUNT)`
      3. 非池法术 → 不占池; 不走 tavern_spell_buff（非 Tavern spell）

    Test: test_batch_quest_rewards3.py — 定向打出后目标 +5/+5 且带
      TAUNT（正对照: 无目标时落空不变）

    Params: atk=5 health=5（token 文本字面量——CardDef 无模板参数）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        return _enhanced_part_play(source, ctx, GameTag.TAUNT)


class EnhancedPartWindfuryScript:
    """
    Natural language: Give a minion +5/+5 and <b>Windfury</b>.
    （BG24_Reward_715t2 "Blazing Blades"）

    Formal spec: 同 EnhancedPartTauntScript，关键词 = WINDFURY。

    Test: test_batch_quest_rewards3.py — 目标 +5/+5 且带 WINDFURY

    Params: atk=5 health=5（token 文本字面量）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        return _enhanced_part_play(source, ctx, GameTag.WINDFURY)


class EnhancedPartDivineShieldScript:
    """
    Natural language: Give a minion +5/+5 and <b>Divine Shield</b>.
    （BG24_Reward_715t3 "Bunker Plating"）

    Formal spec: 同 EnhancedPartTauntScript，关键词 = DIVINE_SHIELD。

    Test: test_batch_quest_rewards3.py — 目标 +5/+5 且带 DIVINE_SHIELD

    Params: atk=5 health=5（token 文本字面量）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        return _enhanced_part_play(source, ctx, GameTag.DIVINE_SHIELD)


class EnhancedPartRebornScript:
    """
    Natural language: Give a minion +5/+5 and <b>Reborn</b>.
    （BG24_Reward_715t4 "Death Rewinder"）

    Formal spec: 同 EnhancedPartTauntScript，关键词 = REBORN。

    Test: test_batch_quest_rewards3.py — 目标 +5/+5 且带 REBORN

    Params: atk=5 health=5（token 文本字面量）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        return _enhanced_part_play(source, ctx, GameTag.REBORN)


def _enhanced_part_play(source, ctx, keyword):
    """Enhanced Part 公共效果体: 合法友方目标 +5/+5 并获关键词。"""
    target = (ctx or {}).get("target")
    hero = getattr(source, "controller", None)
    if hero is None or not isinstance(target, Minion) or target.dead \
            or target not in hero.board:
        return None       # 失活引用 → 落空（SOP §16 模式 24）
    return [Buff(target, atk=5, health=5),
            GainKeyword(target, keyword)]


# ══════════════════ BG24_Reward_718 Kidnap Sack ══════════

class KidnapSackScript:
    """
    Natural language: <b>Spellcraft:</b> Choose a non-Golden card. Move it
    to your hand.

    Formal spec:
      1. Spellcraft 奖励侧授予: on_bind（获得奖励时）经
         `grant_spellcraft_spell` 生成一张; 每回合的再生成由引擎
         `generate_for_hero` 负责（扫描域含 quest_rewards）
         BG24_Reward_718t（CardDef.spellcraft_id=97967 数据链）;
         先例 batch_trinkets2.PreciousPearlScript（饰品同源）
      2. 生成的法术带 SPELLCRAFT tag → 未使用时由 end_recruit_phase
         统一丢弃（RULES §6.13）
      3. 满手排队不销毁（pending_hand_add，RULES §3.3）
      4. 法术效果本体见 KidnapSackSpellScript

    Test: test_batch_quest_rewards3.py — 绑定即入手 1 张 718t 且带
      SPELLCRAFT tag / SoT 再得一张 / 对手手牌不变 / 未用出回合结束丢弃

    Params: 无模板参数（授予物 id 经 CardDef.spellcraft_id 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        grant_spellcraft_spell(source, game)     # 获得时立即给第一张
        return None

    # 每回合的再生成由引擎 `generate_for_hero`（quest_rewards 扫描域）
    # 负责（2026-09-02 扩展）——脚本不得再写 start_of_turn，否则双发


class KidnapSackSpellScript:
    """
    Natural language: Choose a non-Golden card to move to your hand.
    （BG24_Reward_718t——Kidnap Sack 的 Spellcraft 法术 token）

    Formal spec:
      1. needs_target=True + 自定义 `target_candidates` = 控制者**酒馆**中
         的全部非金色卡牌（随从与酒馆法术——28.6 补丁由 "non-Golden
         minion" 改为 "non-Golden card"，且 33.6 修复记载"对冻结随从
         使用可致三连金被冻结" ⇒ 目标域是酒馆展示位）
      2. on_play: 目标已不在酒馆（挂起期被买走/刷新）或已金色 →
         落空（法术照常消耗，SOP §16 模式 24）; 否则移出手牌视图:
         从 `hero.tavern` 移除 + 清除实体级 FROZEN（33.6 修复语义）+
         `pending_hand_add`（满手排队，随从路径自动 check_for_triple）
      3. 池记账: 该副本本就从池中取出（刷新时 acquire）→ 移入手中
         等价于"买入"，**不 release / 不 acquire**; 后续出售/施放按
         常规回池
      4. 仅限本人酒馆（owner 隔离）

    Test: test_batch_quest_rewards3.py — 真实刷新后定向移动: 随从从
      酒馆消失并入手、池记账不变 / 金色酒馆卡不在候选中 / 对手酒馆
      实体不可选 / 目标离场后落空

    Params: 无模板参数（"non-Golden" 为文本限定，无数值）
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = getattr(source, "controller", None)
        if hero is None:
            return []
        return [e for e in hero.tavern
                if not getattr(e, "is_golden", False)]

    @staticmethod
    def on_play(source, game, ctx):
        hero = getattr(source, "controller", None)
        target = (ctx or {}).get("target")
        if hero is None or target is None:
            return None
        if target not in hero.tavern:
            return None       # 挂起期离场/刷新 → 落空
        if getattr(target, "is_golden", False):
            return None       # "non-Golden card"
        hero.tavern.remove(target)
        target.clear(GameTag.FROZEN)
        game.pending_hand_add(hero, target)
        return None


# ══════════════════ BG28_Reward_505 Tumbling Disaster ══════════

class TumblingDisasterScript:
    """
    Natural language: [x]Whenever you summon a minion in combat, give it
    +@/+@. <b>Avenge (4):</b> Improve this permanently.

    Formal spec:
      1. on_bind: `source._tumbling_bonus = num(0)`（@ 的初始值）;
         `_tumbling_step = num(0)`（"Improve this" 的增量 = 初始值——
         R361/Improve 家族惯例，文本无第二个增量参数）; 注册 "summon"
         监听（战斗召唤的唯一广播点 = game.summon，game.py:826）
      2. 战斗守卫: 仅 `game.in_combat` 为真时施加（文本 "in combat"）;
         招募期召唤（买入/打出/亡语外召唤）不触发
      3. 只对本奖励控制者的召唤物生效（minion.controller is hero）
      4. 附魔为普通 `entity.Buff`（战斗期增益由战后快照恢复自然回滚
         RULES §3.5）; 值 = 当前 bonus（@）
      5. Avenge(4)（avenge_threshold=4，文本字面量）: 引擎在战斗内
         每 4 次友方死亡（含复生死亡）调用一次 `avenge`
         （game.py:1625-1641）→ bonus += step，**永久**（跨战斗保留，
         存在奖励实体属性上）; 计数每场战斗清零（CombatScheduler）
      6. 落空语义: bonus=0（理论不可达——num(0)≥1）时不施加 Buff

    Test: test_batch_quest_rewards3.py — 战斗内召唤 +1/+1、招募期召唤
      不吃（正对照: 同 setup 战斗内召唤生效）/ 4 次友方死亡后 bonus
      提升为 2（improve 永久）且后续战斗召唤 +2/+2 / 真实 run_combat
      内 4 死触发 improve / 对手召唤不吃

    Params: avenge_threshold=4 bonus=num(0)=1（CardDef 模板参数 + 文本
            "Avenge (4)" 字面量）
    """

    avenge_threshold = 4    # 文本字面量 "Avenge (4)"（data 仅标 avenge=true）

    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero") if ctx else getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        bonus = d.num(0) if d is not None else None
        if bonus is None:
            return None       # 模板参数缺失 → 不近似实现
        # 奖励实体上的持久状态（跨战斗保留; 非 hero/game 级 → 不污染他人）
        source._tumbling_bonus = bonus
        source._tumbling_step = bonus

        def on_summon(g, minion=None, _h=hero, _src=source, **kw):
            if not getattr(g, "in_combat", False):
                return        # "in combat" 守卫
            if minion is None or minion.controller is not _h:
                return
            val = getattr(_src, "_tumbling_bonus", 0)
            if val > 0:
                minion.add_buff(Enchant(atk=val, health=val))

        game.events.register(Listener(event=SUMMON, owner=source,
                                      callback=on_summon))
        return None

    @staticmethod
    def avenge(source, game, ctx):
        step = getattr(source, "_tumbling_step", None)
        if step is None:
            d = game.db.get(source.card_id)
            step = d.num(0) if d is not None else None
        if step is None:
            return None
        source._tumbling_bonus = getattr(source, "_tumbling_bonus", 0) + step
        return None


# ══════════════════ BG28_Reward_509 Smelting Chamber ══════════

class SmeltingChamberScript:
    """
    Natural language: [x]At the start of each turn, make a friendly Tier
    @ minion Golden and improve this.

    Formal spec:
      1. on_bind: `source._smelting_tier = num(0)`（@ 的初始 tier;
         CardDef.num(0)=1 —— 保留 CardDefs.xml TAG_SCRIPT_DATA_NUM_1=1）
      2. start_of_turn: 候选 = 控制者棋盘**恰好** Tier @ 且非金色的存活
         随从（已金者不再金色化——R013/R508 先例）; 无候选 → 本次
         金色化落空
      3. 金色化经 `batch_quest_rewards._goldenize`（Reno/Captain Sanders
         同源实现: 保留附魔与关键词、换金色独立卡定义、打
         GILDED_NOT_TRIPLED 走非三连金回池口径 RULES §2.3）
      4. "improve this" = @ 每回合 +1（增量 = num(0)=1; 无第二个数值
         参数，@ 是 tier 整数）——**在触发时无条件推进**（文本把
         "and improve this" 与回合触发器绑定，而非与金色化成功绑定;
         否则一旦缺 Tier @ 随从奖励永久卡死在初始档，与"improve"
         的渐进设计矛盾）
      5. 随机选择目标走 `game.rng.choice`（文本无 "Choose"/[Targeted]
         → 随机，Play Dead 先例 SOP §9）
      6. 只作用于本奖励控制者棋盘; 影响范围不涉及酒馆/手牌

    Test: test_batch_quest_rewards3.py — T1 友方随从 SoT 后变金色（金色
      独立卡定义/保留附魔）/ 下一回合 tier 推进到 2 且 T2 随从被金色化
      （improve 的产物身份断言）/ 已金者被跳过 / 对手棋盘不变 /
      无候选时仍推进 tier（正对照证明 improve 不是 no-op）

    Params: tier=num(0)=1（CardDef 模板参数 @ 的初始值）;
            improve_step=1（同初始值——tier 递增单位）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero") if ctx else getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        tier = d.num(0) if d is not None else None
        if tier is None:
            return None
        source._smelting_tier = tier
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        tier = getattr(source, "_smelting_tier", None)
        if tier is None:
            d = game.db.get(source.card_id)
            tier = d.num(0) if d is not None else None
        if tier is None:
            return None
        cands = [m for m in hero.board
                 if not m.dead and m.tech_level == tier and not m.is_golden]
        if cands:
            _goldenize(game, game.rng.choice(cands, label="smelting_chamber"))
        # improve this（无条件推进 @）
        source._smelting_tier = tier + 1
        return None


# ══════════════════ BG28_Reward_513 Open Auditions ══════════

class OpenAuditionsScript:
    """
    Natural language: At the start of each turn, <b>Discover</b> a
    <b>Buddy</b>.

    Formal spec:
      1. start_of_turn（本奖励控制者的招募阶段开始）
      2. 候选 = CardDB 全部非金色伙伴卡（id 后缀 `_Buddy`；`_Buddy_G`
         不匹配该后缀 → 自动排除）——任意英雄的伙伴均可被发现
         （"Discover a Buddy" 无"your"限定; wiki 卡池
         "Friend of a Friend's Buddies" 为全量伙伴池，
         batch_hero_actives2.ETCScript 同口径）
      3. "Discover" = 三选一（引擎惯例 `count=3`; 候选不足全给）→
         `PendingChoice(kind="discover_minion")`，选定后 create_minion +
         pending_hand_add（满手排队 RULES §3.3）
      4. 伙伴不在共享池（RULES §2/§9.4）→ **零池操作**（不 acquire/
         release）
      5. 每个招募阶段恰好一次（start_of_turn 分发保证）; 未解析的选择
         留在 pending_choices 队列（不覆盖、不丢失）

    Test: test_batch_quest_rewards3.py — 真实 `_begin_recruit_for` 后恰好
      1 个 discover 选择且选项全为 `_Buddy` / 选一项后手牌 +1 且池记账
      不变 / 对手回合不产生选择 / 对手手牌不变

    Params: count=3（"Discover" 引擎三选一惯例——CardDef 无模板参数）
    """

    @staticmethod
    def start_of_turn(source, game, ctx):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        buddies = [d.id for d in game.db._by_id.values()
                   if d.id.endswith("_Buddy")]
        if not buddies:
            return None
        options = game.rng.sample(buddies, min(3, len(buddies)),
                                  label="open_auditions")

        def resolve(pick_id, _h=hero, _g=game):
            m = _g.create_minion(pick_id, controller=_h)
            if m is None:
                return
            _g.pending_hand_add(_h, m)

        game.pending_choices.append(PendingChoice(
            hero, options, "discover_minion", resolve_callback=resolve))
        return None


# ══════════════════ BG33_Reward_006 Rushing Winds ══════════

class RushingWindsScript:
    """
    Natural language: <b>Spellcraft:</b> Give a minion <b>Windfury</b> and
    <b>Divine Shield</b>.

    Formal spec:
      1. Spellcraft 奖励侧授予（同 KidnapSackScript）: on_bind →
         `grant_spellcraft_spell` 生成（每回合由引擎生成）
         BG33_Reward_006t（CardDef.spellcraft_id=123601）
      2. 未使用的法术由 end_recruit_phase 按 SPELLCRAFT tag 丢弃
         （RULES §6.13）; 满手排队不销毁
      3. 法术效果本体见 RushingWindsSpellScript

    Test: test_batch_quest_rewards3.py — 绑定即入手 1 张 006t（带
      SPELLCRAFT）/ SoT 再得一张 / 对手手牌不变

    Params: 无模板参数（授予物 id 经 CardDef.spellcraft_id 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        grant_spellcraft_spell(source, game)     # 获得时立即给第一张
        return None

    # 每回合的再生成由引擎 `generate_for_hero`（quest_rewards 扫描域）
    # 负责（2026-09-02 扩展）——脚本不得再写 start_of_turn，否则双发


class RushingWindsSpellScript:
    """
    Natural language: Give a minion <b>Windfury</b> and <b>Divine
    Shield</b>. （BG33_Reward_006t——Rushing Winds 的 Spellcraft 法术）

    Formal spec:
      1. needs_target=True → PendingChoice(kind="spell_target")，候选默认
         全体友方存活随从
      2. on_play: 失活/越界 target 落空（SOP §16 模式 24）; 合法目标获得
         `GainKeyword(WINDFURY)` + `GainKeyword(DIVINE_SHIELD)`
         （fire keyword_gained，圣盾走既有击破计数系统）
      3. 纯关键词效果（无属性变化）; 非池法术不占池

    Test: test_batch_quest_rewards3.py — 定向打出后目标带 WINDFURY 与
      DIVINE_SHIELD（无目标时落空不变——正对照配对）

    Params: 无模板参数（关键词效果无数值）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        target = (ctx or {}).get("target")
        hero = getattr(source, "controller", None)
        if hero is None or not isinstance(target, Minion) or target.dead \
                or target not in hero.board:
            return None
        return [GainKeyword(target, GameTag.WINDFURY),
                GainKeyword(target, GameTag.DIVINE_SHIELD)]


# ══════════════════ BG33_Reward_020 Perpetual Incantation ══════════

class PerpetualIncantationScript:
    """
    Natural language: Your Tavern spells give an extra +{3}/+{1}.
    <i>(+2/+1 can be earned endlessly!)</i>

    Formal spec:
      1. {3}=num(3)=2 攻击 / {1}=num(1)=1 生命（CardDefs.xml
         TAG_SCRIPT_DATA_NUM_4=2、TAG_SCRIPT_DATA_NUM_2=1——文本
         "+{3}/+{1}" 的模板序号直取）
      2. on_bind: `hero.TAVERN_SPELL_EXTRA_ATK += 2`、
         `hero.TAVERN_SPELL_EXTRA_HEALTH += 1`（叠加式——该奖励可被
         重复获得"earned endlessly"，重复获取应累加）
      3. 消费点（真实生产路径）: `racefx.tavern_spell_buff(target, ...)`
         对**酒馆法术**（is_pool_spell）读出该 hero 的额外值并叠加到
         Buff 上; 池法术脚本（BG28_168/169/897、BG31_880/881 等）均经
         此出口
      4. 括号内 "+2/+1 can be earned endlessly" 是任务奖励池的重复
         可获得性说明，**不是**额外效果（无数值可加）
      5. 只写本奖励控制者的 hero tag（owner 隔离——不污染对手）

    Test: test_batch_quest_rewards3.py — 绑定后 tag = (2,1) 且真实池法术
      BG28_897（文本 +2/+2）打出的实际增益为 +4/+3 / 对手无奖励时
      同一法术仍为 +2/+2 且对手 tag = 0

    Params: {1}=1 {3}=2（CardDef 模板参数——攻击走 num(3)、生命走 num(1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero") if ctx else getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        if d is None:
            return None
        atk, health = d.num(3), d.num(1)
        if atk is None or health is None:
            return None       # 模板参数缺失 → 不近似实现
        hero.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) + atk)
        hero.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0) + health)
        return None
