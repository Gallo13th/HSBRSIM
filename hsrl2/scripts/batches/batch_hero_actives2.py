"""批次 hero_actives2 — 主动英雄技能第二批 22 项（作业单 2026-08-23）。

此前 DEFERRED 于门槛/协议缺失（batch_hero_actives 跳过名单），引擎新协议
（use_hero_power: available / uses_per_game / cost_override /
replace_hero_power / target_count=2 双目标链 / next_opponent_warband 快照）
现已就绪，本批解冻。

查证总览（wiki 卡片页 Wiki tags/Notes + 官方 patch notes，2026-08-23）:
  OK 22: Alexstrasza / Millificent / Sylvanas / Shudderwock / Yogg / Jailer /
         E.T.C. / Elise / Togwaggle / Nobundo / Snake Eyes / Kragg / Reno /
         Zerek / Tess / Rat King(基础+10 变体) / Vol'jin / Scabbs / Mutanus /
         Cookie / Barov / Murloc Holmes
  DEFERRED 0 / AMBIGUOUS 0

逐卡 Evidence（门槛类型 Turn vs Tier 逐一核对）:
  - Alexstrasza TB_BaconShop_HP_064 "Queen of Dragons": wiki 卡页
    "(Unlocks at Tier 4.)" = **Tavern Tier 4**; "Discover a Dragon" 无 tier
    限定（29.6.2 起主动化，wiki Patch changes 实证）; cost=1（raw cost）
  - Millificent TB_BaconShop_HP_015 "Tinker": 33.6.2 重做文本
    "Discover a Magnetic Mech. (Unlocks at Tier 4.)" = **Tavern Tier 4**;
    候选 = 池内 Magnetic Mech（36.2.2 池共 6 只）; cost=1
  - Sylvanas BG23_HERO_306p "Reclaimed Souls": "(Unlocks on Turn 3.)" =
    **Turn 3**; 死亡集 = 上场战斗**双方**全部死亡（r/BobsTavern 两帖实证:
    "discover a copy of a minion that died last combat (enemy or friendly)" /
    "can discover from ANY minion, even your opponents"）; plain copy 金色
    源→金色副本（Rafaam 先例）; 满手不可用（官方 34.4.0 2026-01-20 bugfix
    "You can no longer use the Hero Power with a full hand", wiki 卡页
    Bug fixes 节实证）; cost=2
  - Shudderwock TB_BaconShop_HP_022 "Snicker-snack": wiki tags **[Targeted]**;
    "(Unlocks on Turn 3.)"（31.2 加入）= **Turn 3**; TriggerBattlecry 引擎
    原语; **cost=0**（raw 无 cost 键 = XML 无 COST tag; wiki 25.6 "Now costs
    0 (Down from 1)" 且其后无 cost 变更）
  - Yogg TB_BaconShop_HP_039t "Puzzle Box": wiki mechanics **"Passive Hero
    Power"** + HIDE_COST=1 → 被动（passive=True）; "(Unlocks on Turn 3.)" =
    **Turn 3** 起每个自己回合开始施放; "a random Tavern spell" 无 tier 限定
    （对照 Elise "from your Tier"/Toki "a Tier higher" 均显式限定——全 tier
    裁定）; 34.2.2 移除 "Passive" 前缀为措辞简化（wiki mechanics 仍标被动）
  - Jailer TB_BaconShop_HP_702t "Rune of Damnation": wiki tags **[Targeted]**;
    "(Unlocks at Tier 2.)" = **Tavern Tier 2**（官方 34.6.2 2026-02-26
    bugfix "Fixed an issue where Rune of Damnation could be used on Tavern
    Tier 1" 实证 tier 门槛）; Destroy 语义 = 亡语照常（wiki mechanics
    "Destroy"）; "a random Undead" 无 tier 限定; cost=1
  - E.T.C. BG25_HERO_105p "Sign a New Artist": "(Unlocks at Tier 2.)" =
    **Tavern Tier 2**; "Discover a Buddy"——buddy 不在共享池（RULES §2
    "Buddy cards are NOT in the pool"）→ 三选一后 create_minion 不占池;
    cost=3
  - Elise TB_BaconShop_HP_047 "Lead Explorer": "from your Tier" = **恰好
    当前酒馆 tier**（27.0 前文本 "from your Tavern tier" 实证; wiki tags
    Tavern Tier-related）; "Costs (1) more after each use" = 每次使用后
    永久 +1（wiki mechanics "Increment cost"）; cost 基础 1
  - Togwaggle BG23_HERO_305p "The Perfect Crime": 费用公式 = 官方 24.0
    patch notes Dev Comment 原文: "At the end of each Recruit phase, the
    cost of your next Hero Power will reduce by 1 automatically. Each time
    you use Togwaggle's Hero Power, its cost resets to the original 9 Gold
    cost and starts the cycle over again." → cost(T) = base − (T − 上次
    使用回合)，开局锚定 turn 1，下限 0; 28.2 起 "Steal all **cards**"
    （含法术）; base=11（raw cost; 28.2 "Now costs 11"）
  - Nobundo BG31_HERO_003p "The Galaxy's Lens": "Each turn, your next Hero
    Power costs (1) less" 与 Togwaggle 同句式 → 同一 24.0 Dev Comment 公式
    （base=3）; "the last Tavern spell you cast" 经 tavern_spell_cast 事件
    追踪（引擎 29.2.2 语义: 效果结算后广播）
  - Snake Eyes BG28_HERO_400p "Lucky Roll": 官方 35.0.0 bugfix "Lucky Roll
    did not notify players of its **next-turn unlock** when rolling a 1"
    （wiki 卡页 Bug fixes 实证）→ 掷 N 于回合 T 使用后 T+1..T+N-1 不可用、
    **T+N 回合解锁**（掷 1 → 下一回合即解锁）; d6 = rng.randint(1,6);
    cost=1
  - Kragg TB_BaconShop_HP_076 "Piggy Bank": num(0)=2（@ 模板参数,
    TAG_SCRIPT_DATA_NUM_1=2 wiki 印证）; 33.6 文本 "Gain 2 Gold. Increases
    by 1 each turn" → 回合 T 金额 = num(0)+(T−1)（回合 1 = 2 ✓ "Gain 2"）;
    uses_per_game=1; **cost=0**（raw 无 cost 键; wiki 卡页无 Cost 节 /
    社区 "[0 Gold]"）
  - Reno TB_BaconShop_HP_046 "Gonna Be Rich!": once per game; wiki Notes
    "cannot target Timewarped minions"（Timewarped = 异常模式专属，当前
    引擎无异常建模 → 排除条件空真）; 金色化 = _goldenize（batch_battlecry
    Captain Sanders 同构: Transform 保 buff、不发三连奖励、GILDED_NOT_
    TRIPLED 回池 1 份）; **cost=0**（raw 无 cost 键; wiki 18.0.2 "Now costs
    0 (Down from 2)" 且其后无 cost 变更）
  - Zerek BG31_HERO_005p "Cloning Gallery": wiki tags **[Targeted]** +
    once per game; "summon an exact copy"（上板非入手; buff 全量复制 =
    check_for_triple 三连并集先例）; Timewarped 排除同 Reno 空真;
    满板不可用（召唤无处安放——George "无合法目标不可用" 先例）;
    cost=3（raw cost）
  - Tess TB_BaconShop_HP_077 "Bob's Burgles": 官方 27.0 bugfix "Bob's
    Burgles can no longer be activated if your last opponent had no
    minions"（wiki 卡页 Bug fixes 实证）→ available = 上对手战前板快照
    存在且非空; "plain copies" = 不占池生成（复制体出售回池 = 官方复制
    体进出池不对称的既有口径, Rafaam/池记账先例）; cost=1
  - Rat King TB_BaconShop_HP_041: wiki Notes 原文实证: "A Tale of Kings
    is not available in gameplay"; "will not change into the same Hero
    Power twice in a row, but it is otherwise chosen **at random**. It
    will also not swap to minion types not available in the current
    match." → 开局随机换装一变体 + 每回合开始轮换（随机、排除当前类型、
    限 active_races）; 变体 10 张 HP_041a..k（无 e）数据在册
  - Vol'jin BG20_HERO_201p "Spirit Swap": wiki tags **[Targeted]** +
    "Next turn"; 28.2 文本 "They gain each other's Attack until next
    turn"（增攻非换攻）; "until next turn" = 下一招募阶段开始精确回收
    （scripts/spells _expire_at_next_turn 家族——Mini Myrmidon "+X Attack
    until next turn" 同构）; **cost=0**（raw 无 cost 键; wiki 卡页无
    Cost 节）
  - Scabbs BG21_HERO_010p "I Spy": next_opponent_warband 快照（引擎
    game.py:1467 配对时记录战前板）; plain copy 不占池（Sylvanas/Rafaam
    同口径）; cost=2
  - Mutanus BG20_HERO_301p "Devour": wiki Notes 原文实证: "'Spit' in this
    case means **'add', not 'replace'**. if you remove an X/Y minion,
    then another of your minions will receive +X/+Y. **You choose the
    minion to be removed. You do not get to choose the minion to be spat
    on.**" → 单定向（被吃者）+ 随机溅射; 33.2.0 起 "Sell"（正常出售语义:
    +1 金、回池）; **cost=0**（raw 无 cost 键）
  - Cookie BG21_HERO_020p "Stir the Pot": num(0)=3（@ = TAG_SCRIPT_
    DATA_NUM_1=3, wiki 印证）; throw = Remove 语义（非出售: 无 +1 金、
    不回池——Hooktusk "Remove from game" 先例）; 集 3 → Discover from
    their types（候选 = 池内该类型集 ∪ ALL）→ 锅清空循环;
    **cost=0**（raw 无 cost 键）
  - Barov TB_BaconShop_HP_081 "Friendly Wager": CHOICE_NAME_DISPLAY_TYPE/
    CHOICE_ACTOR_TYPE tags = 玩家二选一 UI; "which player will win their
    next combat" = 自己 vs 下一对手（34.2 现文本 "If you're correct" /
    历文本 "If they win" 实证胜利方猜测）; 严格 win 才得（平局不得）;
    奖励 3× Tavern Coin（wiki Related cards: BG28_810）; cost=1
  - Murloc Holmes BG23_HERO_303p2 "Detective for Hire": "Look at 2
    minions. Guess which one your next opponent had last combat" →
    二选一小游戏（恰一真一假——文本蕴含）; 真 = 下对手战前板快照随从;
    假 = 池随机随从（诱饵分布官方未公布——Malygos "官方权重未公布" 裁定
    先例，取池内可用等权）; 猜对得 1× Tavern Coin; cost=3

费用权威口径（本批裁定，主线数据缺口）:
  - power CardDef.cost 构造缺省 3 为**假值**——生成器仅在 XML COST tag
    存在时导出 cost（tools/generate_bg_data.py:211-215），英雄技能 XML
    无 COST tag = 免费 0。raw 缺 cost 键的技能经 ``cost_override`` 修正
    为 0（Reno/Shudderwock/Kragg/Vol'jin/Mutanus/Cookie——wiki 逐一
    印证）。已注册的其他免费技能若未声明 cost_override 会被引擎按 3
    扣费——主线缺口 #1。

池记账约定（本批）:
  - Discover/GetRandom（Alexstrasza/Millificent/Jailer/Cookie）: 走池
    Action 语义（候选池感知 + 选中 acquire）
  - plain copy（Sylvanas/Scabbs/Tess 馆内副本）: 不 acquire——对局存在
    实体的副本（Rafaam 先例; 官方复制体不消耗池副本）; 其出售/淘汰照常
    回池（复制体进出池不对称 = 官方口径）
  - Buddy（E.T.C.）: buddy 不在池（RULES §2）→ 零池操作
  - Togwaggle 偷取: 馆内实体本就占池——移入手牌净零（Xyrella 先例）
  - Mutanus 出售: sell_minion 正常回池
  - Cookie 投锅: Remove 语义不回池（Hooktusk 先例）
  - Tavern Coin 奖励（Barov/Holmes）: spell_pool.acquire 尽力 +
    create_spell（hero_passives Trade Prince Gallywix 先例）

引擎缺口汇总（报告主线）:
  1. **power CardDef.cost 缺省 3 假值**: raw 无 cost 键应按 0 计——
     本批以 cost_override 规避; 主线宜修 CardDef.from_json 英雄技能
     缺省或生成器显式导出 0
  2. Nobundo 依赖 on_bind 追踪 last tavern spell——start_game 已接线
     （game.py:171），但 Game.__init__ 直驱（不经 start_game）的测试/
     训练环境需显式调 on_bind（Edwin 同缺口）
  3. Sylvanas 依赖 COMBAT_END 快照 combat_death_log——多场战斗顺序
     结算时日志只保留最后一场（run_combat 入口清空），on_bind 监听在
     每场 combat_end 即时捕获，语义正确; 无需引擎改动
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2 import entity
from hsrl2.actions import Buff, GainGold, Transform, TriggerBattlecry
from hsrl2.actions.discover import Discover, GetRandomMinion
from hsrl2.events import COMBAT_END, TURN_START, Listener
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# 卡 id 字面量（无数据链可解析; hero_passives 批 _TAVERN_COIN_ID 先例）
_TAVERN_COIN_ID = "BG28_810"          # Tavern Coin（T1 池法术，已注册脚本）

# Rat King 变体（数据核实: HP_041a..k，无 e; 种族与卡名一一对应）
_KING_VARIANTS = (
    ("TB_BaconShop_HP_041a", Race.BEAST),
    ("TB_BaconShop_HP_041b", Race.MECH),
    ("TB_BaconShop_HP_041c", Race.MURLOC),
    ("TB_BaconShop_HP_041d", Race.DEMON),
    ("TB_BaconShop_HP_041f", Race.DRAGON),
    ("TB_BaconShop_HP_041g", Race.PIRATE),
    ("TB_BaconShop_HP_041h", Race.ELEMENTAL),
    ("TB_BaconShop_HP_041i", Race.QUILBOAR),
    ("TB_BaconShop_HP_041j", Race.NAGA),
    ("TB_BaconShop_HP_041k", Race.UNDEAD),
)

_MAGNETIC_KEYWORD = "magnetic"        # defs.py keywords frozenset 成员小写


def _power_def(game: "Game", power_id: str):
    d = game.db.get(power_id)
    if d is None:
        raise GameStateError(f"unknown hero power {power_id!r}")
    return d


def _gold_cost(d) -> int:
    """power 金币费: raw 缺 cost 键 = XML 无 COST tag = 免费 0。

    CardDef.cost=3 是构造器缺省假值（模块 docstring 费用权威口径）。
    """
    return d.raw.get("cost", 0)


def _free_cost(power_id: str):
    """raw 无 cost 键技能的 cost_override（修正引擎假值 3 → 0）。"""
    def _override(hero, game):
        return _gold_cost(_power_def(game, power_id))
    return staticmethod(_override)


def _plain_copy_pair(warband) -> list:
    """战前板快照 → 去重的 (card_id, golden) 对（Sylvanas/Scabbs 共用）。"""
    out: list = []
    seen = set()
    for m in warband:
        key = (m.card_id, m.is_golden)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _plain_copy_choice(game: "Game", hero: "Hero", pairs: list,
                       label: str):
    """三选一 plain copy（不占池）——Sylvanas/Scabbs 共用路径。"""
    if not pairs:
        return None
    k = min(3, len(pairs))
    options = game.rng.sample(pairs, k, label=label)

    def resolve(pick):
        card_id, golden = pick
        m = game.create_minion(card_id, controller=hero, golden=golden)
        game.pending_hand_add(hero, m)

    game.pending_choices.append(PendingChoice(
        hero, options, "discover_minion", resolve_callback=resolve))
    return None


def _gain_tavern_coins(game: "Game", hero: "Hero", count: int) -> None:
    """Tavern Coin ×count（hero_passives Gallywix 先例: 池 acquire 尽力）。"""
    for _ in range(count):
        game.spell_pool.acquire(_TAVERN_COIN_ID)
        game.pending_hand_add(
            hero, game.create_spell(_TAVERN_COIN_ID, controller=hero))


# ═══════════════════ TB_BaconShop_HP_064 Alexstrasza — Queen of Dragons ═══════════════════


class AlexstraszaScript:
    """
    Natural language: <b>Discover</b> a Dragon. <i>(Unlocks at Tier 4.)</i>

    Formal spec:
      1. available: hero.tavern_tier ≥ 4（"at Tier 4" = 酒馆等级门槛——
         wiki 卡页 "(Unlocks at Tier 4.)"; 对照 Yogg "on Turn 3" 措辞）
      2. hero_power: Discover(hero, race=DRAGON)——池感知（剩余量/
         active_races/ALL 三姓匹配），无 tier 限定（"a Dragon" 裸种族;
         29.6.2 主动化后历代文本均无 tier 词）
      3. cost=1（raw cost）

    Test: test_batch_hero_actives2.py — T3 拒绝金币不动 / T4 发现链入手
    占池 / 候选全 Dragon(含 ALL)

    Params: tier=4 / cost=1（均为 raw 数据; 文本无数值占位符）
    """

    @staticmethod
    def available(hero, game):
        return hero.tavern_tier >= 4

    @staticmethod
    def hero_power(hero, game, ctx):
        return Discover(hero, race=Race.DRAGON)


# ═══════════════════ TB_BaconShop_HP_015 Millificent — Tinker ═══════════════════


class MillificentScript:
    """
    Natural language: [x]<b>Discover</b> a <b>Magnetic</b> Mech.
    <i>(Unlocks at Tier 4.)</i>

    Formal spec:
      1. available: hero.tavern_tier ≥ 4（同 Alexstrasza——"at Tier 4"）
      2. 候选 = 池内（available>0、active_races 通过）种族 MECH/ALL 且
         keywords 含 magnetic 的随从 id（36.2.2 池 6 只: BG26_146/
         BG26_147/BG32_172/BG35_341/BG_BOT_911/BG_DEEP_015）——
         Discover 无 keyword 过滤参数 → 显式 candidates 传入
      3. cost=1（raw cost）

    Test: test_batch_hero_actives2.py — T3 拒绝 / T4 候选全部为磁力机械 /
    选中占池

    Params: tier=4 / cost=1（raw 数据）
    """

    @staticmethod
    def available(hero, game):
        return hero.tavern_tier >= 4

    @staticmethod
    def hero_power(hero, game, ctx):
        pool = game.minion_pool
        cands = [d.id for d in game.db.pool_minions()
                 if pool.available(d.id) > 0
                 and d.race in (Race.MECH, Race.ALL)
                 and _MAGNETIC_KEYWORD in d.keywords
                 and (pool.active_races is None
                      or d.race in (Race.NONE, Race.ALL)
                      or d.race in pool.active_races)]
        return Discover(hero, candidates=cands)


# ═══════════════════ BG23_HERO_306p Sylvanas — Reclaimed Souls ═══════════════════


class SylvanasScript:
    """
    Natural language: [x]<b>Discover</b> a plain copy of a minion that
    died last combat. <i>(Unlocks on Turn 3.)</i>

    Formal spec:
      1. on_bind: COMBAT_END 监听（owner=hero，条件 hero 参战）→
         hero._reclaimed_deaths = list(game.combat_death_log)（该场
         全部死亡——**双方**; r/BobsTavern 实证 enemy or friendly;
         combat_death_log 于每场 run_combat 入口清空，combat_end 时点
         恰为本场全集; 幽灵战 combat_end 同样捕获 = 语义正确）
      2. available: game.turn ≥ 3（"on Turn 3"）且有已记录的死亡集
         非空且手牌未满（官方 34.4.0 满手禁用 bugfix）
      3. hero_power: 去重 (card_id, golden) 对 → sample 3 →
         PendingChoice(discover_minion) → pick: create_minion plain
         copy（金色源→金色; 不占池——Rafaam 先例）→ pending_hand_add
      4. cost=2（raw cost）

    Test: test_batch_hero_actives2.py — turn<3 拒绝 / 敌方死亡入选项 /
    plain 无 buff 不占池 / 满手拒绝

    Params: turn=3 / cost=2（raw 数据; 文本无占位符）
    """

    @staticmethod
    def on_bind(hero, game):
        def on_combat_end(g, hero_a=None, hero_b=None, **kw):
            if hero_a is not hero and hero_b is not hero:
                return
            hero._reclaimed_deaths = list(g.combat_death_log)

        game.events.register(Listener(
            event=COMBAT_END, owner=hero, callback=on_combat_end))

    @staticmethod
    def available(hero, game):
        if game.turn < 3:
            return False
        deaths = getattr(hero, "_reclaimed_deaths", None)
        if not deaths:
            return False
        return not hero.hand_full()

    @staticmethod
    def hero_power(hero, game, ctx):
        deaths = getattr(hero, "_reclaimed_deaths", [])
        pairs = _plain_copy_pair(deaths)
        return _plain_copy_choice(game, hero, pairs, "reclaimed_souls")


# ═══════════════════ TB_BaconShop_HP_022 Shudderwock — Snicker-snack ═══════════════════


class ShudderwockScript:
    """
    Natural language: [x]Trigger a friendly minion's <b>Battlecry</b>.
    <i>(Unlocks on Turn 3.)</i>

    Formal spec:
      1. available: game.turn ≥ 3（"on Turn 3"，31.2 加入文本）
      2. needs_target（wiki tags [Targeted]）: 候选 = 友方棋盘存活随从
      3. hero_power: TriggerBattlecry(target)——引擎原语（触发次数含
         Brann 翻倍、COUNTER_BATTLECRIES 计数、BATTLECRY_TRIGGER 广播）
      4. **cost=0**（raw 无 cost 键; wiki 25.6 "Now costs 0"）→
         cost_override 修正

    Test: test_batch_hero_actives2.py — turn<3 拒绝 / Shell Collector
    战吼重触发得 Tavern Coin / 金币不扣（cost 0）

    Params: turn=3 / cost=0（cost 经 cost_override 从 raw 权威取）
    """

    cost_override = _free_cost("TB_BaconShop_HP_022")
    needs_target = True

    @staticmethod
    def available(hero, game):
        return game.turn >= 3

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target not in hero.board:
            raise GameStateError("Snicker-snack: bad target")
        return TriggerBattlecry(target)


# ═══════════════════ TB_BaconShop_HP_039t Yogg-Saron — Puzzle Box ═══════════════════


class YoggScript:
    """
    Natural language: At the start of your turn, cast a random Tavern
    spell. <i>(Unlocks on Turn 3.)</i>

    Formal spec:
      1. **被动**（wiki mechanics "Passive Hero Power" + HIDE_COST=1）:
         passive=True——use_hero_power 恒拒绝
      2. on_bind: TURN_START 监听（owner=hero，条件 hero is 绑定者）:
         game.turn ≥ 3（"Unlocks on Turn 3"）→ 直施 1 个随机池法术
      3. 直施语义（Runic Arcanist BG36_245 batch_soc 先例）: 不经手牌、
         不计 TAVERN_SPELLS_CAST、不广播 tavern_spell_cast; 但随机获取
         池感知（RULES §2.4）: 候选 = 池内 available>0 且 REGISTRY 已
         注册脚本的池法术（自动排除 3 张 Duos OUT_OF_SCOPE + 1 张
         DEFERRED——Unmasked Identity 注册后自动纳入分布）、全 tier
         （文本无 tier 限定词，对照 Elise/Toki 显式限定措辞）;
         spell_pool.acquire → needs_target 法术随机目标
         （target_candidates 无声明时友方棋盘; 无候选 → 该次落空）→
         run_script_hook on_play → zone=REMOVED → spell_pool.release
         （获取-施放-归还净零）
      4. cost: 无关（被动）

    Test: test_batch_hero_actives2.py — turn 1-2 无施放 / turn 3 起施放
    （Shell Collector 类无目标法术可施; 有目标法术随机目标生效）/
    不计 TAVERN_SPELLS_CAST

    Params: turn=3 / spells=1 per turn（文本字面量）
    """

    passive = True

    @staticmethod
    def on_bind(hero, game):
        def on_turn_start(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            if g.turn < 3:
                return
            YoggScript._cast_random_spell(g, _owner)

        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))

    @staticmethod
    def _cast_random_spell(game: "Game", hero: "Hero") -> None:
        from hsrl2.scripts import REGISTRY   # 延迟导入避免循环依赖
        cands = [d.id for d in game.db.pool_spells()
                 if game.spell_pool.available(d.id) > 0
                 and REGISTRY.get(d.id) is not None]
        if not cands:
            return
        sid = game.rng.choice(cands, label="puzzle_box_spell")
        if not game.spell_pool.acquire(sid):
            return
        s = game.create_spell(sid, controller=hero)
        script = s.scripts
        target = None
        if script is not None and getattr(script, "needs_target", False):
            cand_fn = getattr(script, "target_candidates", None)
            targets = (list(cand_fn(s, game)) if cand_fn is not None
                       else [m for m in hero.board if not m.dead])
            if targets:
                target = game.rng.choice(targets,
                                         label="puzzle_box_target")
        game.run_script_hook(s, "on_play", ctx={"target": target})
        s.zone = Zone.REMOVED
        game.spell_pool.release(sid)


# ═══════════════════ TB_BaconShop_HP_702t The Jailer — Rune of Damnation ═══════════════════


class JailerScript:
    """
    Natural language: Destroy a friendly Undead to get a random Undead.
    <i>(Unlocks at Tier 2.)</i>

    Formal spec:
      1. available: hero.tavern_tier ≥ 2（"at Tier 2"; 官方 34.6.2
         bugfix "could be used on Tavern Tier 1" 修复实证 = tier 门槛）
      2. needs_target（wiki tags [Targeted]）: 候选 = 友方棋盘存活
         UNDEAD（race ∈ {UNDEAD, ALL}）
      3. Destroy 语义（wiki mechanics "Destroy"）: HEALTH 置 0 →
         game.check_deaths()——death 事件/亡语/Avenge 照常（对照
         Hooktusk Remove 不触死亡），招募期死亡回池（引擎模型）
      4. GetRandomMinion(hero, race=UNDEAD)——池感知随机获取（无 tier
         限定，"a random Undead" 裸种族）
      5. cost=1（raw cost）

    Test: test_batch_hero_actives2.py — T1 拒绝 / 销毁+随机亡灵入手占池 /
    无亡灵候选不可用

    Params: tier=2 / cost=1（raw 数据）
    """

    needs_target = True

    @staticmethod
    def available(hero, game):
        return hero.tavern_tier >= 2

    @staticmethod
    def target_candidates(hero, game):
        return [m for m in hero.board
                if not m.dead and m.race in (Race.UNDEAD, Race.ALL)]

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target not in hero.board:
            raise GameStateError("Rune of Damnation: bad target")
        target.set(GameTag.HEALTH, 0)
        game.check_deaths()
        return GetRandomMinion(hero, race=Race.UNDEAD)


# ═══════════════════ BG25_HERO_105p E.T.C. — Sign a New Artist ═══════════════════


class ETCScript:
    """
    Natural language: <b>Discover</b> a <b>Buddy</b>. <i>(Unlocks at
    Tier 2.)</i>

    Formal spec:
      1. available: hero.tavern_tier ≥ 2（"at Tier 2"）
      2. 候选 = db 全部非金色 Buddy 卡（id 后缀 `_Buddy`，排除 `_Buddy_G`；
         任意英雄的 buddy 均可被发现——wiki 卡页生成池 "Friend of a
         Friend's Buddies" 为全量 buddy 池）; sample 3 → PendingChoice
         (discover_minion) → pick: create_minion → pending_hand_add
         ——buddy 不在共享池（RULES §2），零池操作
      3. cost=3（raw cost）

    Test: test_batch_hero_actives2.py — T1 拒绝 / 选项均为 _Buddy 卡 /
    入手不占池

    Params: tier=2 / cost=3 / count=3（raw 数据; "Discover" 三选一引擎惯例）
    """

    @staticmethod
    def available(hero, game):
        return hero.tavern_tier >= 2

    @staticmethod
    def hero_power(hero, game, ctx):
        buddies = [d.id for d in game.db._by_id.values()
                   if d.id.endswith("_Buddy")]
        if not buddies:
            return None
        options = game.rng.sample(buddies, min(3, len(buddies)),
                                  label="sign_a_new_artist")

        def resolve(pick_id):
            m = game.create_minion(pick_id, controller=hero)
            game.pending_hand_add(hero, m)

        game.pending_choices.append(PendingChoice(
            hero, options, "discover_minion", resolve_callback=resolve))
        return None


# ═══════════════════ TB_BaconShop_HP_047 Elise — Lead Explorer ═══════════════════


class EliseScript:
    """
    Natural language: [x]<b>Discover</b> a minion from your Tier.
    Costs (1) more after each use.

    Formal spec:
      1. cost_override = base(1) + 已用次数（hero._elise_uses;
         "Costs (1) more after each use" 永久累加，wiki mechanics
         "Increment cost"）; hero_power 内计数 +1（cost_override 在
         扣费前读取 → 第 N 次使用费 = base+N−1 ✓）
      2. hero_power: Discover(hero, min_tier=max_tier=hero.tavern_tier)
         ——"from your Tier" = **恰好**当前酒馆 tier（27.0 前文本
         "from your Tavern tier"; Toki "a Tier higher" 同族精确语义）
      3. cost 基础 1（raw cost）

    Test: test_batch_hero_actives2.py — 首用 1 金 / 次回合 2 金 /
    发现恰好本 tier / 候选池空落空不计数

    Params: base=1（raw cost）/ increment=1（"Costs (1) more" 文本字面量）
    """

    @staticmethod
    def cost_override(hero, game):
        d = _power_def(game, "TB_BaconShop_HP_047")
        return _gold_cost(d) + getattr(hero, "_elise_uses", 0)

    @staticmethod
    def hero_power(hero, game, ctx):
        hero._elise_uses = getattr(hero, "_elise_uses", 0) + 1
        return Discover(hero, min_tier=hero.tavern_tier,
                        max_tier=hero.tavern_tier)


# ═══════════════════ BG23_HERO_305p Togwaggle — The Perfect Crime ═══════════════════


class TogwaggleScript:
    """
    Natural language: [x]Steal all cards from the Tavern. Each turn,
    your next Hero Power costs (1) less.

    Formal spec:
      1. 费用公式（官方 24.0 patch notes Dev Comment 原文——模块
         docstring Evidence）: cost(T) = max(0, base − (T − 锚定回合));
         锚定回合开局 = 1，每次使用重置为当前回合; base=11（raw cost）
      2. hero_power: 偷取 = hero.tavern **全部**实体（随从+法术，28.2
         "all cards"; 冻结与否不影响——"Steal all"）逐个移出 →
         pending_hand_add（满手排队 P6; 池净零——馆内实体本就占池,
         Xyrella 先例）; 清空后重置锚定回合
      3. uses_per_turn=1（引擎默认）

    Test: test_batch_hero_actives2.py — 费用曲线 T1=11/T5=7 / 使用后
    重置（T5 用后 T6=10）/ 偷空酒馆入手 / 冻结馆同样偷空

    Params: base=11（raw cost; wiki 28.2 "Now costs 11"）
    """

    @staticmethod
    def cost_override(hero, game):
        d = _power_def(game, "BG23_HERO_305p")
        anchor = getattr(hero, "_perfect_crime_anchor", 1)
        return max(0, _gold_cost(d) - (game.turn - anchor))

    @staticmethod
    def hero_power(hero, game, ctx):
        for e in list(hero.tavern):
            hero.tavern.remove(e)
            game.pending_hand_add(hero, e)
        hero.clear(GameTag.FROZEN)
        hero._perfect_crime_anchor = game.turn
        return None


# ═══════════════════ BG31_HERO_003p Farseer Nobundo — The Galaxy's Lens ═══════════════════


class NobundoScript:
    """
    Natural language: [x]Get a copy of the last Tavern spell you cast.
    Each turn, your next Hero Power costs (1) less.

    Formal spec:
      1. on_bind: tavern_spell_cast 监听（owner=hero; 引擎于法术效果
         结算后广播, game.py:821; payload spell=）→ 记录
         hero._last_tavern_spell_id（spell.controller is hero 校验）
      2. 费用公式: 同 Togwaggle（同句式 "Each turn, your next Hero
         Power costs (1) less" → 24.0 Dev Comment 家族）; base=3
      3. available: 有已记录的 last spell（无 → 无效果目标不可用,
         George 先例）
      4. hero_power: sid 池可用（spell_pool.available>0）→ acquire →
         create_spell → pending_hand_add（"Get a copy" 池感知获取,
         Holli'dae 先例; 池耗尽 → 落空）; 重置锚定回合

    Test: test_batch_hero_actives2.py — 费用曲线 3/2/1/0 / 施放法术后
    副本入手占池 / 无施放记录不可用 / 使用后费用重置

    Params: base=3（raw cost）
    """

    @staticmethod
    def on_bind(hero, game):
        def on_cast(g, spell=None, **kw):
            if isinstance(spell, Spell) and spell.controller is hero:
                hero._last_tavern_spell_id = spell.card_id

        game.events.register(Listener(
            event="tavern_spell_cast", owner=hero, callback=on_cast))

    @staticmethod
    def available(hero, game):
        return getattr(hero, "_last_tavern_spell_id", None) is not None

    @staticmethod
    def cost_override(hero, game):
        d = _power_def(game, "BG31_HERO_003p")
        anchor = getattr(hero, "_galaxys_lens_anchor", 1)
        return max(0, _gold_cost(d) - (game.turn - anchor))

    @staticmethod
    def hero_power(hero, game, ctx):
        sid = getattr(hero, "_last_tavern_spell_id", None)
        hero._galaxys_lens_anchor = game.turn
        if sid is None:
            return None
        if game.spell_pool.available(sid) <= 0:
            return None
        if not game.spell_pool.acquire(sid):
            raise GameStateError(
                f"The Galaxy's Lens acquire failed for {sid}")
        game.pending_hand_add(
            hero, game.create_spell(sid, controller=hero))
        return None


# ═══════════════════ BG28_HERO_400p Snake Eyes — Lucky Roll ═══════════════════


class SnakeEyesScript:
    """
    Natural language: [x]Roll a 6-sided die. Gain that much Gold.
    <i>(Cannot be used again for that many turns!)</i>

    Formal spec:
      1. roll = rng.randint(1, 6)（"6-sided die"）
      2. GainGold(hero, roll)——99 上限由 gold setter 钳制
      3. 冷却: hero._lucky_roll_unlock = game.turn + roll; available:
         game.turn ≥ unlock（默认 0 = 立即可用）——掷 N 于回合 T 使用
         后 T+1..T+N−1 不可用、T+N 解锁（掷 1 → 下一回合解锁: 官方
         35.0.0 bugfix "next-turn unlock when rolling a 1" 实证）
      4. cost=1（raw cost）

    Test: test_batch_hero_actives2.py — 首用得金 1..6 / 冷却窗口内拒绝 /
    unlock 回合恢复 / 金币增量 = roll

    Params: sides=6 / cost=1（raw 数据; 文本字面量）
    """

    @staticmethod
    def available(hero, game):
        return game.turn >= getattr(hero, "_lucky_roll_unlock", 0)

    @staticmethod
    def hero_power(hero, game, ctx):
        roll = game.rng.randint(1, 6)
        hero._lucky_roll_unlock = game.turn + roll
        return GainGold(hero, amount=roll)


# ═══════════════════ TB_BaconShop_HP_076 Skycap'n Kragg — Piggy Bank ═══════════════════


class KraggScript:
    """
    Natural language: [x]Gain @ Gold. Increases by 1 each turn.
    <i>(Once per game.)</i>

    Formal spec:
      1. uses_per_game=1（"Once per game"; 引擎 HERO_POWER_USES_THIS_
         GAME 记账）
      2. hero_power: GainGold(hero, num(0) + (game.turn − 1))——回合 T
         金额 = num(0)+(T−1)（回合 1 = num(0) = 2 ✓ "Gain 2 Gold.
         Increases by 1 each turn", 33.6 文本+num(0)=2 权威）
      3. **cost=0**（raw 无 cost 键; wiki 卡页无 Cost 节）→
         cost_override 修正

    Test: test_batch_hero_actives2.py — 回合 5 得 num(0)+4 金 / 每局
    一次第二次拒绝 / cost 0 金币只增不减

    Params: {0}=2（num(0)——@ 模板参数）/ cost=0（raw 权威）
    """

    uses_per_game = 1
    cost_override = _free_cost("TB_BaconShop_HP_076")

    @staticmethod
    def hero_power(hero, game, ctx):
        d = _power_def(game, "TB_BaconShop_HP_076")
        return GainGold(hero, amount=d.num(0) + (game.turn - 1))


# ═══════════════════ TB_BaconShop_HP_046 Reno Jackson — Gonna Be Rich! ═══════════════════


class RenoScript:
    """
    Natural language: Once per game, make a friendly minion Golden.

    Formal spec:
      1. uses_per_game=1; **cost=0**（raw 无 cost 键; wiki 18.0.2 "Now
         costs 0"）→ cost_override 修正
      2. needs_target: 候选 = 友方棋盘存活、**非金色**、有金色卡定义
         的随从（Sanders/Reno 先例: 已金色不可为目标; 金色 def 无
         triple_upgrade_id → 落空防御）
      3. hero_power: _goldenize（batch_battlecry Captain Sanders 同构）:
         Transform 保 buff → GOLDEN + TRIPLE_BASE_CARD_ID +
         GILDED_NOT_TRIPLED（出售/淘汰回池按 1 份基础卡, RULES §2.3
         Reno 条目）; 不发三连奖励（金色化 ≠ 三连）; Timewarped 排除
         （wiki Notes）当前引擎无该 tag——空真
      4. token/无金色定义目标: 候选过滤天然排除

    Test: test_batch_hero_actives2.py — 金色化后 GOLDEN tag + buff 保留 +
    无三连奖励 / 已金色不在候选 / 每局一次

    Params: cost=0（raw 权威; 无数值占位符）
    """

    uses_per_game = 1
    cost_override = _free_cost("TB_BaconShop_HP_046")
    needs_target = True

    @staticmethod
    def target_candidates(hero, game):
        out = []
        for m in hero.board:
            if m.dead or m.is_golden:
                continue
            d = game.db.get(m.card_id)
            if d is None or game.db.golden_version(d) is None:
                continue
            out.append(m)
        return out

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target not in hero.board:
            raise GameStateError("Gonna Be Rich!: bad target")
        base_def = game.db.get(target.card_id)
        golden_def = (game.db.golden_version(base_def)
                      if base_def is not None else None)
        if golden_def is None or target.is_golden:
            return None
        idx = hero.board.index(target)
        game.run_actions(Transform(target, golden_def.id,
                                   keep_buffs=True))
        new = hero.board[idx]
        new.set(GameTag.GOLDEN, True)
        new.set(GameTag.TRIPLE_BASE_CARD_ID, base_def.id)
        new.set(GameTag.GILDED_NOT_TRIPLED, True)
        return None


# ═══════════════════ BG31_HERO_005p Zerek — Cloning Gallery ═══════════════════


class ZerekScript:
    """
    Natural language: [x]Once per game, summon an exact copy of a
    friendly minion. <i>(Except <b>Timewarped</b> minions.)</i>

    Formal spec:
      1. uses_per_game=1; cost=3（raw cost）
      2. needs_target（wiki tags [Targeted]）: 候选 = 友方棋盘存活随从
         （Timewarped 排除——wiki Notes; 引擎无异常建模，条件空真）
      3. available: 未满板（召唤无处安放不可用——George "无合法目标
         不可用" 先例; 官方满板行为未公布，裁定记录）
      4. hero_power: exact copy = create_minion(同 card_id,
         golden=is_golden) + 全量 buff 复制（check_for_triple 三连
         并集先例——"exact" 含既有增益）→ game.summon 板尾（官方副本
         位置未公布，取板尾——Summon 默认位先例; 当前血 = summon 满
         血规则）

    Test: test_batch_hero_actives2.py — 副本上板含 buff 与金色 /
    满板不可用 / 每局一次

    Params: cost=0（raw 无 cost 键——wiki 卡页无 Cost 节; "exact copy"
    非数值）
    """

    uses_per_game = 1
    cost_override = _free_cost("BG31_HERO_005p")
    needs_target = True

    @staticmethod
    def available(hero, game):
        return not hero.board_full()

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target not in hero.board:
            raise GameStateError("Cloning Gallery: bad target")
        copy = game.create_minion(target.card_id, controller=hero,
                                  golden=target.is_golden)
        for b in target._buffs:
            copy.add_buff(b)
        game.summon(hero, copy)
        return None


# ═══════════════════ TB_BaconShop_HP_077 Tess Greymane — Bob's Burgles ═══════════════════


class TessScript:
    """
    Natural language: [x]<b>Refresh</b> the Tavern with plain copies of
    your last opponent's warband.

    Formal spec:
      1. available: game.next_opponent_warband(hero) 快照存在且含 ≥1
         随从（官方 27.0 bugfix "can no longer be activated if your
         last opponent had no minions"; 幽灵战无记录 → 不可用）
      2. hero_power:
         - refresh_tavern(free=True)——旧内容回池（P1）/ 冻结整馆保留
           （P5）/ 不另扣刷新金（技能费已含）——Toki 先例
         - 新抽实体（非冻结保留项）全部移出并回池（随从 release 1/
           法术 release——镜像 refresh 的回池口径）
         - 快照逐只 create_minion(card_id, golden=is_golden) plain
           copy 入馆（zone=TAVERN; **不 acquire**——复制体不消耗池
           副本; 出售照常回池 = 官方复制体进出池不对称口径,
           Rafaam/池记账先例）
      3. cost=1（raw cost）

    Test: test_batch_hero_actives2.py — 无快照拒绝 / 刷新后馆内 =
    快照 plain copy（无 buff）/ 旧内容回池 / copy 不占池

    Params: cost=1（raw cost; "plain copies" 非数值）
    """

    @staticmethod
    def available(hero, game):
        snap = game.next_opponent_warband(hero)
        return bool(snap)

    @staticmethod
    def hero_power(hero, game, ctx):
        snap = game.next_opponent_warband(hero)
        if not snap:
            return None
        keep = list(hero.tavern) if hero.frozen_tavern else []
        game.refresh_tavern(hero, auto=False, free=True)
        for e in list(hero.tavern):
            if e in keep:
                continue
            hero.tavern.remove(e)
            if isinstance(e, Minion):
                game.minion_pool.release(e.card_id, 1)
            else:
                game.spell_pool.release(e.card_id)
        for m in snap:
            copy = game.create_minion(m.card_id, controller=hero,
                                      golden=m.is_golden)
            copy.zone = Zone.TAVERN
            hero.tavern.append(copy)
        return None


# ═══════════════════ TB_BaconShop_HP_041 The Rat King — A Tale of Kings ═══════════════════


def _king_active_variants(game: "Game"):
    pool = game.minion_pool
    if pool.active_races is None:
        return list(_KING_VARIANTS)
    return [(vid, race) for vid, race in _KING_VARIANTS
            if race in pool.active_races]


class RatKingScript:
    """
    Natural language: [x]<b>Discover</b> a minion of a specific minion
    type. Swaps type each turn.

    Formal spec:
      1. passive=True——基础技能"不可用于游戏"（wiki Notes: "A Tale of
         Kings is not available in gameplay; it is only used to
         represent the Hero Power when viewing the hero"）→ use_hero_
         power 恒拒绝，实际技能恒为变体
      2. on_bind（开局接线）: 轮换一次（_rotate）——从 active_races 变体
         集随机选一张 replace_hero_power（重置当回合使用计数 → 开局
         回合即可用，官方行为）
      3. TURN_START 监听（owner=hero，条件 hero is 绑定者）: _rotate——
         随机、**排除当前变体**（"will not change into the same Hero
         Power twice in a row"）、限 active_races（"not swap to minion
         types not available in the current match"）
      4. 变体脚本: KingOfXScript（race 参数化）——Discover(hero,
         race=race)，cost=2（各变体 raw cost）

    Test: test_batch_hero_actives2.py — on_bind 后生效技能为变体 /
    turn_start 轮换且不与当前相同 / active_races 过滤 / 变体发现占池

    Params: cost=2（变体 raw cost; 轮换随机性 = wiki Notes 实证）
    """

    passive = True

    @staticmethod
    def _rotate(hero, game):
        cands = _king_active_variants(game)
        current = getattr(hero, "_active_power_id", None)
        cand_ids = [vid for vid, _ in cands if vid != current]
        if not cand_ids:
            # 可用变体 ≤1（极端 active_races）——"不与上次相同"优先，
            # 保持现状（开局 current=None 不会落入此分支）
            return
        vid = game.rng.choice(cand_ids, label="rat_king_rotation")
        game.replace_hero_power(hero, vid)

    @staticmethod
    def on_bind(hero, game):
        RatKingScript._rotate(hero, game)

        def on_turn_start(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            RatKingScript._rotate(_owner, g)

        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))


def _make_king_variant(power_id: str, race: Race):
    """King of X 变体脚本工厂——Discover 该种族（cost=2 各变体 raw）。"""

    class _Variant:
        """Discover a {race}（变体卡文本; Swaps type each turn 由基础
        技能轮换驱动）。"""

        @staticmethod
        def hero_power(hero, game, ctx):
            return Discover(hero, race=race)

    _Variant.__doc__ = (
        f"Natural language: <b>Discover</b> a {race.name.title()}.\n"
        f"Swaps type each turn.  （{power_id}）\n\n"
        f"    Formal spec: Discover(hero, race={race.name})——池感知;\n"
        f"    cost=2（raw cost）; 轮换由 RatKingScript TURN_START 驱动。\n"
        f"    ")
    return _Variant


# ═══════════════════ BG20_HERO_201p Vol'jin — Spirit Swap ═══════════════════


class VoljinScript:
    """
    Natural language: Choose 2 minions. They gain each other's Attack
    until next turn.

    Formal spec:
      1. needs_target + target_count=2（引擎双目标链——两个
         PendingChoice 依次收集，ctx["target"]=[m1, m2]）; 候选 = 友方
         棋盘（<2 只 → 引擎拒绝，金币不动）
      2. hero_power: a1/a2 = 双方当前 atk 快照 → 各得 temporary
         entity.Buff(+对方 atk)（"gain each other's Attack" = 增攻
         非互换; 28.2 文本 + wiki mechanics "Set attack/Swap attribute"
         ——实现为等价增攻）
      3. 过期: "until next turn" = 下一招募阶段开始——per-target 一次性
         TURN_START 监听精确回收各自 buff 实例（scripts/spells
         _expire_at_next_turn 家族; temporary=True 供 Lava Lurker
         永久化拦截识别; owner=target 离场自注销、跨战斗快照存活）
      4. **cost=0**（raw 无 cost 键; wiki 卡页无 Cost 节）→
         cost_override 修正

    Test: test_batch_hero_actives2.py — 双目标链两连 PendingChoice /
    互得对方攻击 / 下一回合开始回退 / 不足 2 只拒绝

    Params: cost=0（raw 权威）/ turns=1（"until next turn" 文本语义）
    """

    cost_override = _free_cost("BG20_HERO_201p")
    needs_target = True
    target_count = 2

    @staticmethod
    def _expire(game, target, buff):
        def on_turn_start(g, hero=None, **kw):
            if buff in target._buffs:
                target.remove_buff(buff)

        game.events.register(Listener(
            event=TURN_START, owner=target, once=True,
            condition=lambda hero=None, _t=target, **kw:
                hero is _t.controller,
            callback=on_turn_start))

    @staticmethod
    def hero_power(hero, game, ctx):
        targets = ctx.get("target") if ctx else None
        if not isinstance(targets, list) or len(targets) != 2:
            raise GameStateError("Spirit Swap: need 2 targets")
        m1, m2 = targets
        if m1 is None and m2 is None:
            return None
        if m1 is not None and m2 is not None:
            a1, a2 = m1.atk, m2.atk
            b1 = entity.Buff(atk=a2, temporary=True)
            b2 = entity.Buff(atk=a1, temporary=True)
            m1.add_buff(b1)
            m2.add_buff(b2)
            VoljinScript._expire(game, m1, b1)
            VoljinScript._expire(game, m2, b2)
        return None


# ═══════════════════ BG21_HERO_010p Scabbs — I Spy ═══════════════════


class ScabbsScript:
    """
    Natural language: [x]<b>Discover</b> a plain copy of a minion from
    your next opponent's warband.

    Formal spec:
      1. available: game.next_opponent_warband(hero) 快照存在且非空
         （招募期可读的下一场对手战前板，game.py:1467 配对时记录;
         幽灵战/首回合无记录 → 不可用）
      2. hero_power: 快照 → 去重 (card_id, golden) → sample 3 →
         PendingChoice(discover_minion) → pick: plain copy
         create_minion（金色源→金色; **不占池**——战前板实体非池供
         给，Sylvanas/Rafaam 同口径）→ pending_hand_add
      3. cost=2（raw cost）

    Test: test_batch_hero_actives2.py — 无快照拒绝 / 选项 = 快照成员 /
    plain copy 无 buff 不占池

    Params: cost=2（raw cost; "plain copy" 非数值）
    """

    @staticmethod
    def available(hero, game):
        snap = game.next_opponent_warband(hero)
        return bool(snap)

    @staticmethod
    def hero_power(hero, game, ctx):
        snap = game.next_opponent_warband(hero)
        pairs = _plain_copy_pair(snap or [])
        return _plain_copy_choice(game, hero, pairs, "i_spy")


# ═══════════════════ BG20_HERO_301p Mutanus — Devour ═══════════════════


class MutanusScript:
    """
    Natural language: [x]Sell a friendly minion. Spit its stats onto
    another.

    Formal spec:
      1. needs_target: 候选 = 友方棋盘存活随从（被吃者——玩家选定）
      2. hero_power:
         - 快照 X/Y = target.atk / target.health（"Spit" = **add** 非
           replace: wiki Notes 原文实证）
         - game.sell_minion（33.2.0 起 "Sell" 语义: +1 金（SELL_VALUE
           覆写优先）、on_sell、回池、亡语不触发——出售非死亡）
         - 溅射目标 = **随机**其余友方随从（wiki Notes: "You do not
           get to choose the minion to be spat on"）→ Buff(+X/+Y);
           无其余随从 → 数值落空
      3. **cost=0**（raw 无 cost 键）→ cost_override 修正

    Test: test_batch_hero_actives2.py — 出售 +1 金回池 / 随机溅射
    +X/+Y / 仅一只随从时数值落空仍成立出售

    Params: cost=0（raw 权威; stats 快照非数值参数）
    """

    cost_override = _free_cost("BG20_HERO_301p")
    needs_target = True

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target not in hero.board:
            raise GameStateError("Devour: bad target")
        atk, health = target.atk, target.health
        game.sell_minion(hero, target)
        others = [m for m in hero.board if not m.dead]
        if not others:
            return None
        receiver = game.rng.choice(others, label="devour_spit")
        return Buff(receiver, atk=atk, health=health)


# ═══════════════════ BG21_HERO_020p Cookie — Stir the Pot ═══════════════════


class CookieScript:
    """
    Natural language: [x]Throw a minion in your pot. When you've
    gathered 3, <b>Discover</b> from their types. <i>(@ left!)</i>

    Formal spec:
      1. needs_target: 候选 = 友方棋盘存活随从（投锅对象）
      2. throw = Remove 语义: 板位移出 + zone=REMOVED + 监听器注销;
         **不回池**（"投锅"消耗——Hooktusk "Remove from game" 友方不
         回池先例）、无 +1 金（非出售）、不触发死亡
      3. 锅 = hero._cookie_pot: list[Race]; 满 num(0)=3 → 类型集 =
         锅内 race ∪ {ALL}（三姓匹配）→ Discover(candidates=池内该
         类型集) → **锅清空**（循环重置——社区共识: 持续循环使用）
      4. **cost=0**（raw 无 cost 键）→ cost_override 修正

    Test: test_batch_hero_actives2.py — 投锅移除不回池 / 第三投触发
    类型 Discover 且锅清空 / 候选限于锅类型∪ALL

    Params: {0}=3（num(0)——@ 模板参数）/ cost=0（raw 权威）
    """

    cost_override = _free_cost("BG21_HERO_020p")
    needs_target = True

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target not in hero.board:
            raise GameStateError("Stir the Pot: bad target")
        hero.board.remove(target)
        game._update_positions(hero)
        target.zone = Zone.REMOVED
        game.events.unregister_owner(target)
        pot = getattr(hero, "_cookie_pot", None)
        if pot is None:
            pot = []
            hero._cookie_pot = pot
        pot.append(target.race)
        d = _power_def(game, "BG21_HERO_020p")
        if len(pot) < d.num(0):
            return None
        races = set(pot) | {Race.ALL}
        hero._cookie_pot = []
        pool = game.minion_pool
        cands = [x.id for x in game.db.pool_minions()
                 if pool.available(x.id) > 0
                 and x.race in races
                 and (pool.active_races is None
                      or x.race in (Race.NONE, Race.ALL)
                      or x.race in pool.active_races)]
        return Discover(hero, candidates=cands)


# ═══════════════════ TB_BaconShop_HP_081 Lord Barov — Friendly Wager ═══════════════════


class BarovScript:
    """
    Natural language: [x]Guess which player will win their next combat.
    If you're correct, get 3 Tavern Coins.

    Formal spec:
      1. hero_power: PendingChoice(kind="friendly_wager",
         options=["me", "opponent"])——CHOICE_NAME_DISPLAY_TYPE/
         CHOICE_ACTOR_TYPE tags 的玩家二选一（自己 vs 下一对手; 功能
         上无需预知对手身份——结算按"胜者是否为猜中方"判定）
      2. resolve: 记录 hero._barov_wager + token → 注册 once COMBAT_END
         监听（owner=hero，条件 hero 参战）: 严格 win 才得（"will
         **win**"——平局/失败不得）; 猜 me: result.winner is hero;
         猜 opponent: result.winner is 另一方 → 3× Tavern Coin
         （_gain_tavern_coins）; token 失配（新赌局覆盖旧装填）→ 失能
      3. 幽灵战 combat_end 同样结算（hero_b=ghost; 官方幽灵战赌局
         行为未公布——按正常战斗语义，Rafaam 幽灵战先例）
      4. cost=1（raw cost）

    Test: test_batch_hero_actives2.py — 猜自己+战胜 → 3 Tavern Coin /
    猜自己+战败 → 无 / 平局无 / 二连使用旧赌局失能

    Params: cost=1 / coins=3（raw / 文本字面量）
    """

    @staticmethod
    def hero_power(hero, game, ctx):
        token = object()
        hero._barov_wager_token = token

        def resolve(pick):
            hero._barov_wager = pick
            hero._barov_wager_token = token

        game.pending_choices.append(PendingChoice(
            hero, ["me", "opponent"], "friendly_wager",
            resolve_callback=resolve))

        def on_combat_end(g, hero_a=None, hero_b=None, result=None, **kw):
            if hero._barov_wager_token is not token:
                return
            hero._barov_wager_token = None
            if result is None or result.winner is None:
                return
            wager = getattr(hero, "_barov_wager", None)
            other = hero_b if hero_a is hero else hero_a
            if (wager == "me" and result.winner is hero) or \
               (wager == "opponent" and result.winner is other):
                _gain_tavern_coins(g, hero, 3)

        game.events.register(Listener(
            event=COMBAT_END, owner=hero, once=True,
            condition=lambda hero_a=None, hero_b=None, _h=hero, **kw:
                hero_a is _h or hero_b is _h,
            callback=on_combat_end))
        return None


# ═══════════════════ BG23_HERO_303p2 Murloc Holmes — Detective for Hire ═══════════════════


class MurlocHolmesScript:
    """
    Natural language: [x]Look at 2 minions. Guess which one your next
    opponent had last combat for a Tavern Coin.    Formal spec:
      1. available: game.next_opponent_warband(hero) 快照存在且非空
         （"your next opponent had last combat" 的数据源 = 配对时
         记录的战前板快照——即其上一场战斗的阵容; 无记录不可用）
      2. hero_power: 真 = 快照去重 (card_id, golden) 随机一张; 假 =
         池内（available>0）非快照 id 随机一张（诱饵分布官方未公布
         ——Malygos "官方权重未公布" 裁定先例，池内可用等权; 池尽 →
         全池 id 兜底; 仍无 → 单选项必然猜对）; 两选项 rng.sample
         洗牌 → PendingChoice(kind="holmes_guess") → pick == 真 →
         1× Tavern Coin
      3. cost=3（raw cost）

    Test: test_batch_hero_actives2.py — 无快照拒绝 / 选项恰 2 且含
    快照成员 / 猜对得 Coin 猜错不得

    Params: cost=0（raw 无 cost 键——wiki 卡页无 Cost 节）/ coins=1
    """

    cost_override = _free_cost("BG23_HERO_303p2")

    @staticmethod
    def available(hero, game):
        snap = game.next_opponent_warband(hero)
        return bool(snap)

    @staticmethod
    def hero_power(hero, game, ctx):
        snap = game.next_opponent_warband(hero) or []
        reals = _plain_copy_pair(snap)
        if not reals:
            return None
        real = game.rng.choice(reals, label="holmes_real")
        snap_ids = {cid for cid, _ in reals}
        decoy_cands = [d.id for d in game.db.pool_minions()
                       if d.id not in snap_ids
                       and game.minion_pool.available(d.id) > 0]
        if not decoy_cands:
            decoy_cands = [d.id for d in game.db.pool_minions()
                           if d.id not in snap_ids]
        if decoy_cands:
            decoy = (game.rng.choice(decoy_cands,
                                     label="holmes_decoy"), False)
            options = game.rng.sample([real, decoy], 2,
                                      label="holmes_order")
        else:
            options = [real]

        def resolve(pick):
            if pick == real:
                _gain_tavern_coins(game, hero, 1)

        game.pending_choices.append(PendingChoice(
            hero, options, "holmes_guess", resolve_callback=resolve))
        return None


def register() -> list[str]:
    """注册本批次 22 项技能（基础+变体共 31 个技能卡 id）。"""
    from hsrl2.scripts.registry import register as reg

    registered: list[str] = []
    for power_id, script in (
        ("TB_BaconShop_HP_064", AlexstraszaScript),
        ("TB_BaconShop_HP_015", MillificentScript),
        ("BG23_HERO_306p", SylvanasScript),
        ("TB_BaconShop_HP_022", ShudderwockScript),
        ("TB_BaconShop_HP_039t", YoggScript),
        ("TB_BaconShop_HP_702t", JailerScript),
        ("BG25_HERO_105p", ETCScript),
        ("TB_BaconShop_HP_047", EliseScript),
        ("BG23_HERO_305p", TogwaggleScript),
        ("BG31_HERO_003p", NobundoScript),
        ("BG28_HERO_400p", SnakeEyesScript),
        ("TB_BaconShop_HP_076", KraggScript),
        ("TB_BaconShop_HP_046", RenoScript),
        ("BG31_HERO_005p", ZerekScript),
        ("TB_BaconShop_HP_077", TessScript),
        ("TB_BaconShop_HP_041", RatKingScript),
        ("BG20_HERO_201p", VoljinScript),
        ("BG21_HERO_010p", ScabbsScript),
        ("BG20_HERO_301p", MutanusScript),
        ("BG21_HERO_020p", CookieScript),
        ("TB_BaconShop_HP_081", BarovScript),
        ("BG23_HERO_303p2", MurlocHolmesScript),
    ):
        reg(power_id, script)
        registered.append(power_id)
    for vid, race in _KING_VARIANTS:
        reg(vid, _make_king_variant(vid, race))
        registered.append(vid)
    return registered
