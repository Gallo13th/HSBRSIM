"""批次 choose_one — Choose One 清尾批 + Tavern-spell-extra 随从（作业单
2026-08-22，12 张）。

OK 11 张（含金色 id，金色=独立卡定义）:
  Choose One 随从: BG31_320 Crater Miner / BG36_330 Sly Infiltrator /
    BG36_332 Snare Trapper / BG36_341 Veteran Brigand / BG32_237 Intrepid
    Botanist
  Choose One 相关触发/光环: BG31_323 Turbo Hogrider / BG31_327 Thorned
    Trailblazer
  Tavern-spell-extra: BG32_341 Humon'gozz / BG35_341 Enchanted Sentinel
  Elemental-extra: BG32_841 Sand Swirler（batch_battlecry DEFERRED 解冻
    ——tags.py ELEMENTAL_EXTRA_ATK 1057 已入册）
  Improve 触发: BG35_602 Lurking Leviathan

AMBIGUOUS 1 张（不注册）: BG33_319 Rimescale Priestess —
  "Get a random Tavern spell that gives stats" 的候选集无权威分类
  （batch_misc 模块 docstring 引擎缺口 #3 同案; "gives stats" 资格
  标志需 generate_bg_data.py 导出或主线给出清单——按已注册脚本效果
  扫描不可靠，SOP 铁律禁止猜测实现）。详见文末占位类 docstring。

共性裁定:
  - **引擎 Choose One 协议**: 脚本类声明 choose_options → play_minion
    产生 PendingChoice(kind="choose_one")，选定 key 经 ctx["choose"]
    触发 battlecry（game.py:409）; **CHOOSE_BOTH 光环生效时引擎直接
    传 choose="both"**（game.py:443——Thorned Trailblazer 落地后该
    路径可达）→ 本批全部 Choose One 脚本显式处理 "both"（两分支
    并联执行）。
  - **金色战吼模型**: 引擎对金色触发 2 次 × 每次触发基础值
    （_per_trigger_def 金色实体回基础 CardDef）= 金色文本总额。
    本批 5 张 Choose One 均满足 2×基础 = 金色 num（data 核对）。
  - **每次触发值核对**（36.2.2）: Miner gems {0}=2（金 4）/ Infiltrator
    {0}=2 {1}=3（金 4/6）/ Trapper {0}=1（金 2）/ Brigand {0}=3 {1}=3
    （金 6/6）/ Botanist 无参数文本字面量 1/1（金 2/2）。
  - **"Choose One card" 判定**（Turbo Hogrider 触发条件）: 官方 =
    CardDefs CHOOSE_ONE tag。def.keywords 的 choose_one 标志不可靠
    （XML_KEYWORD_MAP 不含该 tag，标志仅文本兜底且法术导出路径不跑
    检测——Gem Day/BG30_117t 族 keywords 为空）→ 判定式 = 文本含
    Choose One 标题格式（"Choose One -"，dash 可在 </b> 外——BG31_842
    格式）∧ 非 Spellcraft 宿主（spellcraft_id 非空的随从其文案属于
    被授予的法术，如 BG30_117）。36.2.2 全库核对与 XML tag 集完全
    一致（见 test_batch_choose_one 漂移守护）。
  - **Humon'gozz / Enchanted Sentinel 在场光环裁定**（2026-08-23
    查证修正）: wiki Full tags 两卡均 ``AURA=1``（Sentinel 另有
    Wiki tags [Ongoing effect]）→ 增幅仅在场期间生效、离场撤销
    （_tavern_extra_aura: 出售/招募期死亡/吸附离场撤销; 战斗死亡
    由引擎战后棋盘恢复天然延续）。旧"永久叠加"读法与 AURA 证据
    矛盾，弃用; 与 Sand Swirler（[Playerbound] + "this game" 永久）
    构成对照。
  - **Blood Gem Barrage 直施**（Brigand 分支 2）: BG34_689 施放脚本已由
    batch_spells_final 注册（2026-08-22 落地）→ "cast ... {1} times" =
    对 REGISTRY 脚本 on_play 直施 num(1) 次（卡 id 经 Brigand 自身
    evolution_card_id 数据链解析 126676→BG34_689，零硬编码）。
  - **Lurking Leviathan Improve 公式**: "improve this permanently" 无
    显式增量 → 官方 Improve 惯例 = 每次触发后效果 + 自身 num
    （Tasty Lobster batch_deathrattle2 / Fire-forged Evoker batch_soc
    双先例同构）: 第 N 次触发给 num(1)×N。

引擎缺口报告（主线处理）:
  1. **存量 Choose One 脚本不处理 choose="both"**: batch_misc
     BG27_084 Sprightly Scarab / BG30_123 Fearless Foodie 的 battlecry
     对 key="both" 返回 None（效果全丢）; batch_spells4 手动
     PendingChoice 的 Choose One 法术（BG31_880/881/886/890 等）不受
     CHOOSE_BOTH 光环影响（仍弹选择）。Thorned Trailblazer 注册后
     该路径可达——本批文件禁改存量，需主线接线。
  2. BG31_893 Gem Day（Crater Miner / Gem Rat 产出物）施放脚本仍未
     注册——入手后打出无效果（法术批次待收口，audit 缺口盯）。
  3. BG33_319 Rimescale Priestess AMBIGUOUS（见上）。
  4. Thorned Trailblazer "One/Two ... each turn"（num(0)=1/2）= 每回合
     有限计数（wiki "(N left!)" 计数显示 + [Turn-related]，2026-08-23
     查证修正为每回合计数器模型，见类 docstring Evidence）。
"""

from __future__ import annotations

import re

from hsrl2.actions import Buff, GetRandomMinion
from hsrl2.actions.bloodgem import GetBloodGems, PlayBloodGems
from hsrl2.events import (
    CARD_PLAYED,
    DEATH,
    MAGNETIZED,
    MINION_SOLD,
    Listener,
    SUMMON,
    TURN_START,
)
from hsrl2.game import GameStateError
from hsrl2.scripts.batches.batch_deathrattle import _per_trigger_def
from hsrl2.tags import GameTag, Race

# ── 通用帮助 ──

_QUILBOAR_RACES = (Race.QUILBOAR, Race.ALL)   # ALL 视为所有种族 (RULES §6.18)
_BEAST_RACES = (Race.BEAST, Race.ALL)

# Choose One 标题格式: "Choose One - "（dash 可落在 </b> 之外——BG31_842
# "<b>Choose One</b> - Give ..." 格式）
_CHOOSE_ONE_HEADER = re.compile(r"Choose One(?:</b>)?\s*-")


def _is_choose_one_card(game, card) -> bool:
    """"Choose One card" 判定（Turbo Hogrider 触发条件，模块 docstring 裁定）。

    官方 = CardDefs CHOOSE_ONE tag。可观测面 def.keywords 的 choose_one
    标志不可靠（XML_KEYWORD_MAP 不含 CHOOSE_ONE——标志仅来自文本兜底，
    而生成器法术导出路径不跑文本检测: BG31_893 Gem Day/BG30_117t 族
    keywords 为空）→ 判定式 = 文本含 Choose One 标题格式（"Choose One
    -"，dash 可在 </b> 外——BG31_842 格式）∧ 非 Spellcraft 宿主
    （spellcraft_id 非空的随从其 Choose One 文案属于被授予的法术本体，
    如 BG30_117——其授予的 BG30_117t 是真 Choose One 卡，随从不是）。
    36.2.2 全库核对与 XML tag 集完全一致（含提及型负例
    Hogrider/Trailblazer/BG31_329/BG36_331/BG31_892，见
    test_batch_choose_one 漂移守护）。
    """
    d = game.db.get(card.card_id)
    if d is None:
        return False
    if d.spellcraft_id is not None:
        return False   # Spellcraft 宿主: Choose One 文案属被授予法术 (BG30_117)
    return _CHOOSE_ONE_HEADER.search(d.text or "") is not None


def _num(d, index: int, card_id: str, what: str) -> int:
    """模板参数取值——缺失即 PARAM_MISSING，fail-loud 禁默认值近似。"""
    v = d.num(index)
    if v is None:
        raise GameStateError(
            f"{card_id}: template param {{{index}}} ({what}) missing "
            f"(PARAM_MISSING)")
    return v


def _both(key: str, branch: str) -> bool:
    """分支命中判定: 选定该分支，或 CHOOSE_BOTH 光环双效。"""
    return key == branch or key == "both"


# ══════════════════ BG31_320 Crater Miner（choose_one） ══════════════════


class CraterMinerScript:
    """
    Natural language: <b>Choose One - </b>Get {0} <b>Blood Gems</b>; or
    Get a Gem Day.（金色 BG31_320_G: Get {0} Blood Gems; or Get 2 Gem
    Days.）

    Formal spec:
      1. choose_options = [("gems", ...), ("gemday", ...)]; 引擎产生
         PendingChoice(kind="choose_one")，选定 key 经 ctx["choose"]
         触发 battlecry; CHOOSE_BOTH 光环传 "both"（两分支并联）。
      2. "gems" → GetBloodGems(hero, num(0))——num(0) 颗 vanilla 血宝石
         进手牌（满手排队; 非池卡不占池，actions/bloodgem 契约）。
      3. "gemday" → 1 张 Gem Day（BG31_320 自身 evolution_card_id 数据
         链解析 116596→BG31_893，Gem Rat/batch_eot_sot 同链先例; 非池
         卡不占池）create_spell + pending_hand_add。
      4. 每次触发值 = 基础 CardDef（_per_trigger_def）; 金色引擎触发
         2 次 → gems 总额 2×2=4 = 金色 num(0) ✓、gemday 总额 2×1=2
         = 金色文本 "2 Gem Days" ✓。
      5. hero 缺失 → 落空。

    Test: test_batch_choose_one.py — gems 分支手牌 +num(0) 张 BG20_GEM /
    gemday 分支 +1 张 BG31_893（数据链 id）/ 金色 gems 4、gemday 2 /
    选择前无效果 / both 双效

    Params: {0}=2（36.2.2 基线，金色 {0}=4; gemdays=1 每次触发——金色
    文本 "2 Gem Days" = 2 次触发，字面量）
    """

    choose_options = [
        ("gems", "Get {0} Blood Gems"),
        ("gemday", "Get a Gem Day"),
    ]

    gemdays_per_trigger = 1   # "a Gem Day"（文本字面量，无模板参数）

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        key = (ctx or {}).get("choose")
        if hero is None or key is None:
            return None
        d = _per_trigger_def(game, source)
        actions = []
        if _both(key, "gems"):
            actions.append(GetBloodGems(
                hero, _num(d, 0, source.card_id, "Blood Gems")))
        if _both(key, "gemday"):
            if d.evolution_card_id is None:
                raise GameStateError(
                    f"{source.card_id}: evolution_card_id broken data "
                    f"chain (Gem Day)")
            gem_day = game.db.by_dbf(d.evolution_card_id)
            if gem_day is None:
                raise GameStateError(
                    f"{source.card_id}: evolution_card_id "
                    f"{d.evolution_card_id} not in db")
            for _ in range(CraterMinerScript.gemdays_per_trigger):
                game.pending_hand_add(
                    hero, game.create_spell(gem_day.id, controller=hero))
        return actions or None


# ══════════════════ BG36_330 Sly Infiltrator（choose_one） ══════════════════


class SlyInfiltratorScript:
    """
    Natural language: <b>Choose One -</b> Gain {0} free <b>Refreshes</b>;
    or Get {1} <b>Blood Gems</b>.

    Formal spec:
      1. choose_options = [("refreshes", ...), ("gems", ...)]; key 经
         ctx["choose"] 触发 battlecry; "both" 双分支并联。
      2. "refreshes" → hero.FREE_REFRESH_REMAINING(1034) += num(0)——
         refresh_tavern 消费点（game.py:266 免费次数优先于金币）。
      3. "gems" → GetBloodGems(hero, num(1))。
      4. 每次触发值 = 基础 CardDef; 金色引擎 ×2 → 2×2=4 刷新 /
         2×3=6 宝石 = 金色 num（4/6）✓。
      5. hero 缺失 → 落空。

    Test: test_batch_choose_one.py — refreshes 分支 tag +num(0) 且被
    refresh_tavern 消费 / gems 分支手牌 +num(1) / 金色 4 刷新 6 宝石

    Params: {0}=2 {1}=3（36.2.2 基线，金色 {0}=4 {1}=6; 每次触发值=基础
    CardDef）
    """

    choose_options = [
        ("refreshes", "Gain {0} free Refreshes"),
        ("gems", "Get {1} Blood Gems"),
    ]

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        key = (ctx or {}).get("choose")
        if hero is None or key is None:
            return None
        d = _per_trigger_def(game, source)
        actions = []
        if _both(key, "refreshes"):
            hero.set(GameTag.FREE_REFRESH_REMAINING,
                     hero.get(GameTag.FREE_REFRESH_REMAINING, 0)
                     + _num(d, 0, source.card_id, "free Refreshes"))
        if _both(key, "gems"):
            actions.append(GetBloodGems(
                hero, _num(d, 1, source.card_id, "Blood Gems")))
        return actions or None


# ══════════════════ BG36_332 Snare Trapper（choose_one） ══════════════════


class SnareTrapperScript:
    """
    Natural language: <b>Choose One -</b> Get a random Quilboar; or
    Increase your maximum Gold by {0}.（金色: Get 2 random Quilboar; or
    ... by {0}，金色 num(0)=2）

    Formal spec:
      1. choose_options = [("quilboar", ...), ("maxgold", ...)]; key 经
         ctx["choose"] 触发 battlecry; "both" 双分支并联。
      2. "quilboar" → GetRandomMinion(hero, race=QUILBOAR)——池感知
         （acquire 占池 + 满手排队; ALL 种族含 Quilboar）。
      3. "maxgold" → hero.INCOME_CAP_BONUS(1059) += num(0)
         （Strike Oil/batch_misc 同构; hero.income_cap = 基础 + tag）。
      4. 每次触发值 = 基础 CardDef; 金色引擎 ×2 → 2 只随机 Quilboar /
         +2 最大金币 = 金色文本（"2 random Quilboar" / num(0)=2）✓。
      5. hero 缺失 → 落空。

    Test: test_batch_choose_one.py — quilboar 分支入手 Quilboar（ALL 亦可）
    且占池 / maxgold 分支 income_cap +num(0) / 金色 maxgold +2

    Params: {0}=1（36.2.2 基线，金色 {0}=2; quilboars=1 每次触发——金色
    "2 random Quilboar" = 2 次触发，字面量）
    """

    choose_options = [
        ("quilboar", "Get a random Quilboar"),
        ("maxgold", "Increase your maximum Gold by {0}"),
    ]

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        key = (ctx or {}).get("choose")
        if hero is None or key is None:
            return None
        d = _per_trigger_def(game, source)
        actions = []
        if _both(key, "quilboar"):
            actions.append(GetRandomMinion(hero, race=Race.QUILBOAR))
        if _both(key, "maxgold"):
            hero.set(GameTag.INCOME_CAP_BONUS,
                     hero.get(GameTag.INCOME_CAP_BONUS, 0)
                     + _num(d, 0, source.card_id, "maximum Gold"))
        return actions or None


# ══════════════════ BG36_341 Veteran Brigand（choose_one） ══════════════════


def _cast_blood_gem_barrage(game, hero, brigand_id: str, times: int) -> None:
    """直施 Blood Gem Barrage 效果 times 次（BG36_341 evolution 数据链
    126676→BG34_689，零硬编码）。

    效果本体复用 REGISTRY 已注册的施放脚本（batch_spells_final
    BloodGemBarrageScript，2026-08-22 落地）: 每次 cast = create_spell
    绑定脚本实体 + run_script_hook("on_play")——注册持久 TAVERN_REFRESH
    监听（owner=施放者英雄 = "this game"），刷新后酒馆全体 Minion 各
    +Barrage.num(0)/+num(1) gem Buff + GEMS_PLAYED_ON 记账 +
    blood_gem_played 事件（SOP §10 宝石记账）。多次 cast 各自独立
    监听（叠加）。脚本未注册时 fail-loud（GameStateError——效果唯一
    权威不可内联近似）。
    """
    brigand_def = game.db.get(brigand_id)
    if brigand_def is None or brigand_def.evolution_card_id is None:
        raise GameStateError(
            f"{brigand_id}: evolution_card_id broken data chain "
            f"(Blood Gem Barrage)")
    barrage = game.db.by_dbf(brigand_def.evolution_card_id)
    if barrage is None:
        raise GameStateError(
            f"{brigand_id}: evolution_card_id "
            f"{brigand_def.evolution_card_id} not in db")
    from hsrl2.scripts import REGISTRY   # 延迟导入避免循环依赖
    if REGISTRY.get(barrage.id) is None:
        raise GameStateError(
            f"{barrage.id} cast script not registered (effect authority "
            f"required for {brigand_id})")
    for _ in range(times):
        spell = game.create_spell(barrage.id, controller=hero)
        game.run_script_hook(spell, "on_play", None)


class VeteranBrigandScript:
    """
    Natural language: [x]<b>Choose One -</b> This plays
    {0} <b>Blood Gems</b> on all your
    minions; or cast Blood Gem
    Barrage {1} times.（金色 BG36_341_G 同文，num 6/6）

    Formal spec:
      1. choose_options = [("gems", ...), ("barrage", ...)]; key 经
         ctx["choose"] 触发 battlecry; "both" 双分支并联。
      2. "gems" → 对每个友方存活随从（含 Brigand 自身——play_minion
         先入场后战吼，"all your minions" 无排除词）各
         PlayBloodGems(m, num(0))——立即生效（数值 = BG20_GEM CardDef
         + hero 加成 tags; GEMS_PLAYED_ON 记账 + blood_gem_played
         事件由 Action 统一保证）。
      3. "barrage" → _cast_blood_gem_barrage(game, hero, id, num(1))——
         num(1) 次 Blood Gem Barrage 效果直施: 复用 REGISTRY 施放脚本
         （batch_spells_final.BloodGemBarrageScript——刷新监听 + 酒馆
         全体 +Barrage.num(0)/num(1) gem Buff + 宝石记账，效果唯一
         权威; 见函数 docstring）。
      4. 每次触发值 = 基础 CardDef; 金色引擎 ×2 → gems 2×3=6、
         barrage 2×3=6 casts = 金色 num（6/6）✓。
      5. hero 缺失 → 落空。

    Test: test_batch_choose_one.py — gems 分支全体随从 +num(0) 颗宝石
    （含自身，GEMS_PLAYED_ON）/ barrage 分支刷新后酒馆随从 +1/+1×cast
    数且卖出后仍生效（this game）/ 金色 barrage 6 casts

    Params: {0}=3 {1}=3（36.2.2 基线，金色 6/6）; Barrage 侧
    BG34_689 {0}=1 {1}=1（经其 CardDef.num 取）
    """

    choose_options = [
        ("gems", "This plays {0} Blood Gems on all your minions"),
        ("barrage", "cast Blood Gem Barrage {1} times"),
    ]

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        key = (ctx or {}).get("choose")
        if hero is None or key is None:
            return None
        d = _per_trigger_def(game, source)
        actions = []
        if _both(key, "gems"):
            n = _num(d, 0, source.card_id, "Blood Gems")
            actions.extend(PlayBloodGems(m, n)
                           for m in hero.board if not m.dead)
        if _both(key, "barrage"):
            _cast_blood_gem_barrage(
                game, hero, d.id,
                _num(d, 1, source.card_id, "Barrage casts"))
        return actions or None


# ══════════════════ BG31_323 Turbo Hogrider（Choose One 触发） ══════════════════


class TurboHogriderScript:
    """
    Natural language: [x]After you play a <b>Choose One</b>
    card, this plays a <b>Blood
    Gem</b> on all your other
    Quilboar.（金色: plays 2 Blood Gems）

    Formal spec:
      1. on_summon 注册持久 card_played 监听器（owner=source: 出售/
         招募期死亡自动注销; 战斗快照恢复语义）。
      2. 条件: 打出的卡是 Choose One card（_is_choose_one_card 判定式，
         模块 docstring——XML CHOOSE_ONE tag 等价; Hogrider 自身/
         Trailblazer 等提及型卡不计）且 card.controller 友方。
         Choose One 随从与法术（Gem Day/池法术）的 card_played 均触发
         （引擎两路径都广播）。
      3. 触发: 对每个其他友方存活 Quilboar（race ∈ (QUILBOAR, ALL)，
         排除 source 自身——"your other"）各 PlayBloodGems(m, times)。
      4. times=1（"a Blood Gem" 文本字面量，无模板参数）; 监听器触发
         非战吼，引擎不翻倍——金色子类 times=2。
      5. 无其他 Quilboar → 落空; source.controller 缺失 → 落空。

    Test: test_batch_choose_one.py — 打出 Choose One 卡后其他 Quilboar
    各 +times 颗宝石 / 非 Quilboar 与自身不变 / 打出非 Choose One 卡不
    触发 / 打出另一张 Hogrider 不触发 / 金色 2 颗

    Params: times=1（"a Blood Gem" 文本字面量——CardDef 无模板参数;
    宝石数值唯一来源 BG20_GEM CardDef）
    """

    times = 1   # "a Blood Gem"（文本字面量，无模板参数）

    @staticmethod
    def on_summon(source, game, ctx):
        def _cond(card=None, **kw):
            return (card is not None
                    and getattr(card, "controller", None)
                    is source.controller
                    and _is_choose_one_card(game, card))

        def _on_played(g, card=None, **kw):
            hero = source.controller
            if hero is None:
                return
            for m in hero.board:
                if m is source or m.dead or m.race not in _QUILBOAR_RACES:
                    continue
                g.run_actions(PlayBloodGems(m, source.scripts.times))

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source,
            condition=_cond, callback=_on_played))
        return None


class TurboHogriderGoldenScript(TurboHogriderScript):
    """
    Natural language: [x]After you play a <b>Choose One</b>
    card, this plays 2 <b>Blood
    Gems</b> on all your other
    Quilboar.

    Formal spec: 同基础版，times=2（监听器触发非战吼，引擎不翻倍——
    金色子类显式加倍）。

    Test: 金色触发后其他 Quilboar 各 2 颗宝石 buff

    Params: times=2（"2" 为金色文本字面量）
    """

    times = 2


# ══════════════════ BG31_327 Thorned Trailblazer（CHOOSE_BOTH 光环） ══════════════════


class ThornedTrailblazerScript:
    """
    Natural language: One <b>Choose One</b> card each turn has both
    effects combined. <i>(@ left!)</i>（金色: Two ... each turn）

    Evidence: hearthstone.wiki.gg/wiki/Battlegrounds/Thorned_Trailblazer
      — 卡面计数器 "(1 left!)" / 金色 "(2 left!)"（Full tags
      TAG_SCRIPT_DATA_NUM_1=1/2）+ Wiki tags [Turn-related] → **每回合
      有限计数**: 每回合前 num(0) 张 Choose One 卡（随从或法术）双效
      合并，耗尽后恢复二选一，回合开始重置。恒光环读法与 "(N left!)"
      计数显示矛盾，2026-08-23 查证弃用。

    Formal spec:
      1. on_summon: 置 GameTag.CHOOSE_BOTH 于自身 + 初始化每回合余量
         source._trailblazer_left = num(0)。引擎 play_minion/play_spell
         棋盘扫描任一 CHOOSE_BOTH 随从 → Choose One 卡跳过选择、以
         choose="both" 双效结算; 离场（出售/死亡移除）即不再被扫描
         = 光环失效。
      2. CARD_PLAYED 监听（owner=source，出售/招募期死亡自动注销）:
         友方打出 Choose One 卡（scripts.choose_options 存在）且本回合
         未被其他 Trailblazer 计数（实体标记 _trailblazer_turn ==
         game.turn 防多张重复扣减）→ 余量 -1，归零即 clear(
         CHOOSE_BOTH)（本回合光环停摆）。
      3. TURN_START 监听（hero is source.controller）: 余量重置 num(0)
         并重设 CHOOSE_BOTH。
      4. 自身非 Choose One 卡（XML 无 CHOOSE_ONE tag，判定式 False）;
         多张 Trailblazer 独立计数（基础 1 + 金色 2 = 每回合最多
         3 张双效，任一有余量即引擎扫描生效）。

    Test: test_batch_choose_one.py — 每回合首张 Choose One 不弹选择且
    双效 / 同回合第二张恢复选择 / 下一回合重置 / 金色每回合 2 张 /
    卖出后恢复选择 / 非 Choose One 卡不受影响

    Params: {0}=1（金色 {0}=2——每回合计数，见 Evidence）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        d = game.db.get(source.card_id)
        per_turn = d.num(0) if d is not None and d.num(0) is not None else 1

        def _refresh(g):
            source._trailblazer_left = per_turn
            source.set(GameTag.CHOOSE_BOTH, True)

        def on_turn_start(g, hero=None, **kw):
            if hero is None or hero is source.controller:
                _refresh(g)

        def on_played(g, card=None, **kw):
            if card is None or getattr(card, "controller", None) \
                    is not source.controller:
                return
            if getattr(card, "_trailblazer_turn", -1) == g.turn:
                return    # 已被另一张 Trailblazer 就本张计数
            script = getattr(card, "scripts", None)
            if script is None or not getattr(script, "choose_options", None):
                return
            card._trailblazer_turn = g.turn
            if getattr(source, "_trailblazer_left", per_turn) <= 0:
                return
            source._trailblazer_left -= 1
            if source._trailblazer_left <= 0:
                source.clear(GameTag.CHOOSE_BOTH)

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source, callback=on_played))
        game.events.register(Listener(
            event=TURN_START, owner=source, callback=on_turn_start))
        _refresh(game)
        return None


# ══════════════════ BG32_237 Intrepid Botanist（choose_one） ══════════════════


class IntrepidBotanistScript:
    """
    Natural language: [x]<b>Choose One -</b> Your Tavern
    spells give an extra
    +1 Attack this game;
    or +1 Health.（金色: +2 Attack; or +2 Health）

    Formal spec:
      1. choose_options = [("atk", ...), ("health", ...)]; key 经
         ctx["choose"] 触发 battlecry; "both" 双分支并联。
      2. "atk" → hero.TAVERN_SPELL_EXTRA_ATK(1053) += 1; "health" →
         TAVERN_SPELL_EXTRA_HEALTH(1054) += 1（"this game" 永久叠加;
         消费点 racefx.tavern_spell_buff——Felfire Conjurer/
         batch_eot_sot 同构）。
      3. "+1/+1" = 文本字面量（CardDef 无模板参数）; 金色引擎 ×2 →
         每分支总额 +2 = 金色文本 "+2 Attack / +2 Health" ✓（同一
         脚本类注册两个 id）。
      4. hero 缺失 → 落空。

    Test: test_batch_choose_one.py — atk 分支 tag +1 且 tavern_spell_buff
    反映 / health 分支 +1 / 金色单分支总额 +2

    Params: atk=1 health=1（文本字面量——CardDef 无模板参数; 金色 2/2
    = 引擎 ×2 触发）
    """

    extra = 1   # "+1 Attack / +1 Health"（文本字面量，无模板参数）

    choose_options = [
        ("atk", "Your Tavern spells give an extra +1 Attack this game"),
        ("health", "+1 Health"),
    ]

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        key = (ctx or {}).get("choose")
        if hero is None or key is None:
            return None
        n = source.scripts.extra
        if _both(key, "atk"):
            hero.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
                     hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) + n)
        if _both(key, "health"):
            hero.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                     hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0) + n)
        return None


# ══════════════════ BG32_341 Humon'gozz（Tavern-spell-extra 光环） ══════════════════


def _tavern_extra_aura(source, game, atk, health):
    """TAVERN_SPELL_EXTRA_* **在场光环**登记（Humon'gozz / Sentinel 共用）。

    Evidence（wiki Full tags，2026-08-23 查证）: 两卡均带 ``AURA=1``
    （Enchanted Sentinel Wiki tags 另含 [Ongoing effect]）→ 增幅仅在
    随从在场期间生效，离场即撤销——与 Sand Swirler（[Playerbound] +
    文本 "this game" → 永久叠加）构成对照。v2 曾按 on_summon 永久
    叠加实现，与本证据矛盾，已修正。

    撤销时机（事件均在引擎 unregister_owner 之前广播，owner=source
    监听器可收到——game.py sell_minion:408 / _process_single_death:1239）:
      - minion_sold: 出售
      - death: 招募期死亡（战斗死亡不撤销——引擎战后棋盘整体恢复，
        随从回归=光环延续）
      - magnetized: Sentinel 吸附离场（attached 置 REMOVED）
    """
    hero = source.controller
    if hero is None:
        return
    hero.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
             hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) + atk)
    hero.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
             hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0) + health)

    def _revoke(g, **kw):
        h = source.controller
        if h is None:
            return
        h.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
              max(0, h.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) - atk))
        h.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
              max(0, h.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0) - health))

    game.events.register(Listener(
        event=MINION_SOLD, owner=source,
        callback=lambda g, minion=None, **kw:
            _revoke(g) if minion is source else None))
    game.events.register(Listener(
        event=DEATH, owner=source,
        callback=lambda g, minion=None, **kw:
            (_revoke(g) if minion is source and not g.in_combat
             else None)))
    game.events.register(Listener(
        event=MAGNETIZED, owner=source,
        callback=lambda g, host=None, attached=None, **kw:
            _revoke(g) if attached is source else None))


class HumongozzScript:
    """
    Natural language: [x]<b>Divine Shield</b>
    Your Tavern spells give
    an extra +1/+2.（金色: an extra +2/+4）

    Formal spec:
      1. on_summon（非战吼——文本无 Battlecry）: _tavern_extra_aura
         （TAVERN_SPELL_EXTRA_ATK += 1 / HEALTH += 2）——**在场光环**，
         出售/招募期死亡/吸附离场即撤销（Evidence: wiki Full tags
         ``AURA=1``; 34.2.0 前文本 "...that give stats grant an extra"
         的限定词已删，现行文本无 "this game"——与 Sand Swirler 的
         [Playerbound] 永久型相区分）。
      2. "+1/+2" = 文本字面量（CardDef 无模板参数）; on_summon 非战吼
         引擎不翻倍——金色子类显式 2/4（金色文本字面量）。
      3. Divine Shield 由 create_minion 关键词映射（CardDef 权威）。
      4. hero 缺失 → 落空。

    Test: test_batch_choose_one.py — 入场 tag +1/+2 且 tavern_spell_buff
    反映 / 金色 +2/+4 / 圣盾关键词在身 / **卖出后 tag 撤销（光环语义）**

    Params: extra_atk=1 extra_health=2（文本字面量——CardDef 无模板
    参数; 金色 2/4 金色文本字面量）
    """

    extra_atk = 1     # "+1"（文本字面量，无模板参数）
    extra_health = 2  # "+2"（文本字面量，无模板参数）

    @staticmethod
    def on_summon(source, game, ctx):
        s = source.scripts
        _tavern_extra_aura(source, game, s.extra_atk, s.extra_health)
        return None


class HumongozzGoldenScript(HumongozzScript):
    """
    Natural language: [x]<b>Divine Shield</b>
    Your Tavern spells give
    an extra +2/+4.

    Formal spec: 同基础版，extra_atk=2 / extra_health=4（金色文本
    字面量）。

    Test: 金色入场 tag +2/+4

    Params: extra_atk=2 extra_health=4（金色文本字面量——CardDef 无
    模板参数）
    """

    extra_atk = 2
    extra_health = 4


# ══════════════════ BG35_341 Enchanted Sentinel（磁力 + extra） ══════════════════


class EnchantedSentinelScript:
    """
    Natural language: <b>Magnetic</b>
    Your Tavern spells give
    an extra +{1}/+{2}.（金色 {1}/{2}=2/2）

    Formal spec:
      1. on_summon: _tavern_extra_aura（TAVERN_SPELL_EXTRA_ATK += num(1)、
         TAVERN_SPELL_EXTRA_HEALTH += num(2)）——**索引 {1}/{2}**（{0}
         空缺: TAG_SCRIPT_DATA_NUM_1 未导出——生成器不导出 0 值参数，
         wiki Full tags NUM_1=0 核对）; **在场光环**（Evidence: wiki
         Full tags ``AURA=1`` + Wiki tags [Ongoing effect]——离场撤销，
         含吸附离场（magnetized attached 置 REMOVED））。
      2. 同一脚本类注册基础/金色 id——source 在场实体即本体定义，
         num(1)/num(2) 按实体 CardDef 自然区分（基础 1/1、金色 2/2）。
      3. Magnetic 由引擎 play_minion 磁力路径 + create_minion 关键词
         映射处理（吸附路径不经 on_summon——不登记; 官方对吸附后的
         持续效果无记载，按"吸附=离场"保守读法撤销面为恒 null 的
         幂等操作）。
      4. hero 缺失 → 落空。

    Test: test_batch_choose_one.py — 入场 tag +num(1)/num(2) / 金色
    +2/+2 / 磁力关键词在身 / **卖出后 tag 撤销（光环语义）**

    Params: {1}=1 {2}=1（36.2.2 基线，金色 {1}=2 {2}=2; {0} 未导出=
    生成器 0 值参数省略）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        _tavern_extra_aura(
            source, game,
            _num(d, 1, source.card_id, "extra Attack"),
            _num(d, 2, source.card_id, "extra Health"))
        return None


# ══════════════════ BG32_841 Sand Swirler（Elemental-extra） ══════════════════


class SandSwirlerScript:
    """
    Natural language: [x]<b>Battlecry:</b> Your Elementals
    give an extra +{0} Attack
    this game.

    Formal spec:
      1. battlecry（每次触发）: hero.ELEMENTAL_EXTRA_ATK(1057) +=
         num(0)——**永久叠加**（"this game"）。消费点 batch_consume.
         elemental_buff（元素 give-效果出口，Moat Custodian/
         Glowing Cinder 同栈）。
      2. 每次触发值 = 基础 CardDef（_per_trigger_def）; 金色引擎 ×2 →
         2+2=4 = 金色 num(0) ✓（同一脚本类注册两个 id）。
      3. hero 缺失 → 落空。

    Evidence: hearthstone.wiki.gg/wiki/Battlegrounds/Sand_Swirler —
      Wiki mechanics **[Playerbound]**（效果绑定玩家、随从离场不失效）
      + 文本 "this game"（36.2.2: +1→+2 Attack，与 num(0)=2/金色 4
      吻合; wiki 金色框文本 "+2 Health" 为 34.6.0 前旧文未更新，
      XML 36.2.2 权威）; 32.4.0 bugfix "didn't buff Windfall Tornado"
      印证消费点在 give-效果出口。

    Test: test_batch_choose_one.py — 战吼 tag +num(0) / 金色 +4 /
    elemental_buff 出口集成反映

    Params: {0}=2（36.2.2 基线，金色 {0}=4; 每次触发值=基础 CardDef）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _per_trigger_def(game, source)
        hero.set(GameTag.ELEMENTAL_EXTRA_ATK,
                 hero.get(GameTag.ELEMENTAL_EXTRA_ATK, 0)
                 + _num(d, 0, source.card_id, "Elemental extra Attack"))
        return None


# ══════════════════ BG35_602 Lurking Leviathan（Improve 触发） ══════════════════


class LurkingLeviathanScript:
    """
    Natural language: Whenever you summon a Beast, give it +{1}_Attack
    and improve this permanently.（金色 +{1}_Attack，num(1)=4）

    Formal spec:
      1. on_summon 注册持久 summon 监听器（owner=source，出售/招募期
         死亡注销; 战斗快照恢复——战斗中亡语召唤的 Beast 照常触发，
         战斗内 buff 战后快照回滚为 RULES §3.5 默认）。
      2. 条件: minion.controller 友方 且 race ∈ (BEAST, ALL)。自身
         召唤不触发（引擎 summon 事件先于 on_summon 注册——官方
         Tidecaller 类裁定）。
      3. 触发: Buff(minion, atk=num(1) × (1 + improve_count))，
         improve_count = source 实体动态属性（Evoker _improve_count
         同构——restore_state 不回滚 = "this game"; 离场重入归零）。
      4. Improve 公式: 每次触发后效果 + 自身 num（Tasty Lobster
         batch_deathrattle2 / Fire-forged Evoker batch_soc 双先例——
         第 N 次给 num(1)×N; "improve this permanently" 无显式增量，
         按 Improve 惯例取自身 num）。
      5. num 经 source 本体定义取（基础 2 / 金色 4——监听器触发非
         战吼不翻倍，金色实体 CardDef 自然区分; 同一脚本类注册两 id）。
      6. source.controller 缺失 → 落空。

    Test: test_batch_choose_one.py — 第 1/2 只 Beast 各 +num(1)/
    +2×num(1) 攻 / 非 Beast 不触发 / 自身入场不自 buff / 金色 4、8

    Params: {1}=2（36.2.2 基线，金色 {1}=4; {0} 未导出=生成器 0 值
    参数省略——wiki Full tags NUM_1=0）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def _cond(minion=None, **kw):
            return (minion is not None
                    and getattr(minion, "controller", None)
                    is source.controller
                    and minion.race in _BEAST_RACES)

        def _on_summon(g, minion=None, **kw):
            hero = source.controller
            if hero is None or minion is None:
                return
            d = g.db.get(source.card_id)
            base = _num(d, 1, source.card_id, "Beast Attack")
            n = getattr(source, "_leviathan_improves", 0)
            g.run_actions(Buff(minion, atk=base * (1 + n)))
            source._leviathan_improves = n + 1   # improve this permanently

        game.events.register(Listener(
            event=SUMMON, owner=source,
            condition=_cond, callback=_on_summon))
        return None


# ══════════════════ 以下 AMBIGUOUS（不注册 REGISTRY） ══════════════════


class RimescalePriestessScript:
    """
    Natural language: <b>Spellcraft:</b> Get a random Tavern spell that
    gives stats.（金色: Get 2 random ...）

    Status: AMBIGUOUS — 候选集 "Tavern spell that gives stats" 无权威
    分类，禁止猜测实现（SOP 铁律）。

    Ambiguity（候选解释）:
      A. "gives stats" = 对随从施加攻/血增益的池法术（Buff 类）——但
         "gives stats" 也可能含 summon-stats / set-stats / 血宝石类
         （宝石给 stats?）等边界; 按已注册脚本效果扫描不可靠（脚本
         注册状态与卡资格无关）。
      B. 官方实现按内部卡牌标签（wiki Full tags 无导出; generate_
         bg_data.py 未导出该资格标志——batch_misc 模块 docstring
         引擎缺口 #3 同案）。
    解冻条件: generate_bg_data.py 导出 gives-stats 标志，或主线给出
    权威清单（data 权威信源优先级 1）。

    Spellcraft 数据链（解冻时用）: spellcraft_id 122259（金色 122260）
    ——grant_spellcraft_spell 授予法术本体（法术脚本同 AMBIGUOUS）。
    """

    @staticmethod
    def on_summon(source, game, ctx):
        return None


def register() -> list[str]:
    """注册本批次全部脚本（含金色 id），返回注册的 card_id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []

    def _add(card_id: str, script_cls) -> None:
        _register(card_id, script_cls)
        registered.append(card_id)

    _add("BG31_320", CraterMinerScript)
    _add("BG31_320_G", CraterMinerScript)          # ×2 触发 → 4 gems/2 Gem Days
    _add("BG36_330", SlyInfiltratorScript)
    _add("BG36_330_G", SlyInfiltratorScript)       # ×2 → 4 刷新/6 宝石
    _add("BG36_332", SnareTrapperScript)
    _add("BG36_332_G", SnareTrapperScript)         # ×2 → 2 Quilboar/+2 金
    _add("BG36_341", VeteranBrigandScript)
    _add("BG36_341_G", VeteranBrigandScript)       # ×2 → 6 gems/6 casts
    _add("BG31_323", TurboHogriderScript)
    _add("BG31_323_G", TurboHogriderGoldenScript)  # times=2
    _add("BG31_327", ThornedTrailblazerScript)
    _add("BG31_327_G", ThornedTrailblazerScript)   # num(0)=2 每回合 2 张
    _add("BG32_237", IntrepidBotanistScript)
    _add("BG32_237_G", IntrepidBotanistScript)     # ×2 → +2
    _add("BG32_341", HumongozzScript)
    _add("BG32_341_G", HumongozzGoldenScript)      # +2/+4
    _add("BG35_341", EnchantedSentinelScript)
    _add("BG35_341_G", EnchantedSentinelScript)    # num(1)/num(2) 自然区分
    _add("BG32_841", SandSwirlerScript)
    _add("BG32_841_G", SandSwirlerScript)          # ×2 → +4
    _add("BG35_602", LurkingLeviathanScript)
    _add("BG35_602_G", LurkingLeviathanScript)     # num(1)=4 自然区分
    return registered
