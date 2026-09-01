"""批次 battlecry（作业单 2026-08-21，17 张池随从——战吼主题）。

实现状态总览（详见各类 docstring）:
  OK:       BG23_002 Shell Collector / BG25_011 Nerubian Deathswarmer /
            BG25_034 Captain Sanders / BG26_135 Southsea Busker /
            BG26_814 Lovesick Balladist / BG27_002 Oozeling Gladiator /
            BG28_303 Disguised Graverobber / BG31_330 Ominous Seer /
            BG33_830 Azsharan Cutlassier / BG34_865 En-Djinn Blazer /
            BG35_140 Mama Mrrglton / BG35_141 Papa Mrrglton /
            BG35_150 Laboratory Assistant / BG35_152 Void Pup Trainer /
            BG36_520 Bilgewater Breakout / BGS_116 Refreshing Anomaly
            （含对应金色注册）
  DEFERRED: BG32_841 Sand Swirler（需 ELEMENTAL_EXTRA_ATK tag，见该类
            docstring 与批次报告）

金色模型约定（与 game.play_minion 触发次数模型、批次 1 先例对齐）:
  - battlecry 钩子实现"每次触发的**基础值**"（_battlecry_def 取基础
    CardDef）——金色打出时引擎触发 2 次，总额 = 2×基础值 = 金色文本
    总额（金色 def num = 2×基础 num，本批次 17 张全部核实成立）
  - 例外: 金色文本非 "twice" 语义（Bilgewater Breakout "opens {0} turns
    sooner" 单次总额）→ 金色类守卫一次结算（见该类 docstring）
  - 持久监听器（非 battlecry 钩子）单次注册; "twice" 类金色 = 每次战吼
    触发注册一个监听器，天然叠加
"""

from __future__ import annotations

from hsrl2.actions import Buff, GainGold, ScheduleNextTurn, Transform
from hsrl2.actions.racefx import ApplyRaceAura
from hsrl2.actions.tavern_buff import ApplyTavernBuff, BuffCurrentTavern, \
    TavernBuff
from hsrl2.constants import FODDER_CARD_ID, LOCKBOX_CARD_ID
from hsrl2.events import CARD_PLAYED, Listener, TAVERN_REFRESH
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

_UNDEAD_RACES = (Race.UNDEAD, Race.ALL)
_MURLOC_RACES = (Race.MURLOC, Race.ALL)
_PIRATE_RACES = (Race.PIRATE, Race.ALL)

# Mrrglton 家族 card_id（"each Mrrglton you played this game" 的计数范围;
# data 无家族字段，按卡名核实 = Mama/Papa + 金色变体，Cousin Errgl
# BG35_142 非 Mrrglton——其名为 Errgl，仅生成 Mrrglton）
_MRRGLTON_IDS = frozenset({
    "BG35_140", "BG35_140_G", "BG35_141", "BG35_141_G",
})


def _battlecry_def(game, source):
    """战吼每次触发取**基础** CardDef（金色战吼模型，见模块 docstring）。

    金色实体经 TRIPLE_BASE_CARD_ID 定位基础卡; 非金色直接取自身。
    数据完整性: 解析失败抛 GameStateError（fail-loud，禁止静默近似）。
    """
    base_id = (source.get(GameTag.TRIPLE_BASE_CARD_ID, None)
               if source.is_golden else None)
    d = game.db.get(base_id) if base_id else game.db.get(source.card_id)
    if d is None:
        raise GameStateError(
            f"_battlecry_def: unknown card {source.card_id!r}")
    return d


def _ctx_target(ctx):
    return (ctx or {}).get("target")


class ShellCollectorScript:
    """
    Natural language: <b>Battlecry:</b> Get a Tavern Coin.

    Formal spec:
      1. 打出时（battlecry，每次触发）: Tavern Coin（BG28_810，池法术
         is_pool_spell=True，36.2.2 数据核实）经 source CardDef 的
         evolution_card_id 数据链解析（80740→104436 dbf→BG28_810，
         同 Snarky Shark Fishbait 先例，零硬编码卡 id）
      2. 获取走 spell_pool 语义（池法术）: 池内有副本 →
         spell_pool.acquire（占池）+ create_spell + pending_hand_add
         （满手排队，RULES §3.3）; 池空（唯一副本被他人持有）→ 仍生成
         但不占池——Mystic Essence Dark Gift 先例（game.py
         _gift_mystic_essence "池空: 生成不占池（作业单约定）"）
      3. 金色版 "Get 2 Tavern Coins" = 引擎触发 2 次 × 每次 1 枚;
         第一枚占走池内唯一副本后第二枚走池空生成路径
      4. Tavern Coin "Gain 1 Gold." 的法术脚本不在本批次（on_play 由
         其自身注册负责，当前未注册=效果暂缺，由缺口审计盯）

    Test: test_batch_battlecry.py — 打出入手 1 枚 / 占用 spell_pool /
    池空仍生成 / 金色 2 枚

    Params: 无模板参数（Tavern Coin 卡 id 经 evolution_card_id 数据链解析）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _battlecry_def(game, source)
        coin_def = game.db.by_dbf(d.evolution_card_id) \
            if d.evolution_card_id else None
        if coin_def is None:
            raise GameStateError(
                f"{source.card_id}: evolution_card_id broken data chain")
        if not game.spell_pool.acquire(coin_def.id):
            pass   # 池空: 仍生成不占池（Mystic Essence 先例）
        coin = game.create_spell(coin_def.id, controller=hero)
        game.pending_hand_add(hero, coin)
        return None


class NerubianDeathswarmerScript:
    """
    Natural language: <b>Battlecry:</b> Your Undead have +1 Attack this game
    <i>(wherever they are)</i>.

    Formal spec:
      1. 打出时（battlecry，每次触发）: ApplyRaceAura(hero, UNDEAD,
         atk=1, health=0)——叠加式种族光环，经 Minion._aura_atk 对
         棋盘/手牌/未来获得的全部 Undead（含 ALL 种族）实时生效
         （"wherever they are"，RULES §6.4）
      2. 金色版 "+2 Attack" = 引擎触发 2 次 × +1（金色模型）
      3. 无实体创建

    Test: test_batch_battlecry.py — 打出后棋盘+手牌 Undead atk +1 /
    非 Undead 不变 / 金色 +2（光环叠加）

    Params: {0}=1（文本字面量——CardDef 无模板参数，金色文本 +2 由
             引擎 2 次触发自然体现）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return ApplyRaceAura(hero, Race.UNDEAD, atk=1, health=0,
                             source_id=source.card_id)


def _sanders_candidates(source, game):
    """Captain Sanders 目标候选: 友方非金色、T≤6、有金色卡定义的随从。"""
    hero = source.controller
    if hero is None:
        return []
    out = []
    for m in hero.board:
        if m.dead or m is source or m.is_golden:
            continue
        if m.tech_level > 6:      # "from Tier 6 or below"; Sanders 自身 T7 天然排除
            continue
        d = game.db.get(m.card_id)
        if d is None or game.db.golden_version(d) is None:
            continue
        out.append(m)
    return out


def _goldenize(game, target):
    """Reno 式金色化: Transform 到金色卡定义，保留 buff; **不发三连奖励**
    （金色化 ≠ 三连——不置 TRIPLE_REWARD_PENDING、不 fire triple_combined）。

    - Transform(target, golden_def.id, keep_buffs=True) 后补 GOLDEN +
      TRIPLE_BASE_CARD_ID tag（Transform 以 golden=False 创建金色定义实体，
      tag 由本函数补齐，见 actions/stats.py Transform 契约）
    - 出售/淘汰回池按 1 份基础卡（RULES §2.3 Reno 条目——GILDED_
      NOT_TRIPLED 标记驱动 release_minion_entity，Gilding Dark Gift
      同构 2026-08-22 统一; Reno/Sanders 卡页无 Notes，已查）
    - 脚本重绑: Transform 内 create_minion 按金色 card_id 从 REGISTRY
      绑定金色脚本（金色行为差异生效）
    """
    base_def = game.db.get(target.card_id)
    golden_def = game.db.golden_version(base_def) if base_def is not None else None
    hero = target.controller
    if golden_def is None:
        return                          # 已金色（金色 def 无 triple_upgrade_id）→ 落空
    if hero is None or target not in hero.board:
        return   # 前序触发已金色化（旧实体被 Transform 替换离场）→ 幂等落空
    idx = hero.board.index(target)
    game.run_actions(Transform(target, golden_def.id, keep_buffs=True))
    new = hero.board[idx]
    new.set(GameTag.GOLDEN, True)
    new.set(GameTag.TRIPLE_BASE_CARD_ID, base_def.id)
    new.set(GameTag.GILDED_NOT_TRIPLED, True)   # Reno 式: 回池按 1 份


class CaptainSandersScript:
    """
    Natural language: <b>Battlecry:</b> Make a friendly minion from Tier 6
    or below Golden.

    目标选择裁定: v1 记录为 Reno 式定向（作业单）; 定向协议 =
    needs_target=True + target_candidates（引擎 play_minion 产生
    PendingChoice(kind="battlecry_target")，先入场后选择）。

    Formal spec:
      1. 候选 = 友方棋盘存活、非金色（Reno 先例: 已金色不可作为金色化
         目标）、tech_level ≤ 6、db.golden_version 存在的随从
      2. 选定后（ctx["target"]）: _goldenize——Transform 到金色卡定义
         保留 buff，不发三连奖励（Reno 语义，见 _goldenize docstring）
      3. 金色版 "Make **two** friendly minions ... Golden": 引擎对金色
         战吼触发 2 次且 ctx.target 相同——第 2 次触发时目标已金色 →
         由金色子类追加第二个 PendingChoice 选择另一只（见子类）

    Test: test_batch_battlecry.py — PendingChoice 流 / 金色化保留 buff /
    不发三连奖励 / T7 与已金色排除 / 无候选战吼落空仍入场

    Params: 无模板参数（"Tier 6" 为文本字面量）
    """

    needs_target = True
    target_candidates = staticmethod(_sanders_candidates)

    @staticmethod
    def battlecry(source, game, ctx):
        target = _ctx_target(ctx)
        if target is None:
            return None
        _goldenize(game, target)
        return None


class CaptainSandersGoldenScript(CaptainSandersScript):
    """
    Natural language: <b>Battlecry:</b> Make two friendly minions from
    Tier 6 or below Golden.

    Evidence: hearthstone.wiki.gg/wiki/Battlegrounds/Captain_Sanders —
      金色文本 "Make **two** friendly minions from Tier 6 or below
      Golden."（33.2.2 改版文本，卡页无 Notes）; 33.6.0 官方 bugfix
      "now functions properly when generated from the Secret Culprit
      Quest Reward"（生成路径功能修复先例，无重触发细节）。

    Formal spec:
      1. 引擎对金色战吼触发 2 次、ctx.target 相同。第 1 次触发: 金色化
         所选目标（同基础版）。第 2 次触发: 目标已金色 → 追加
         PendingChoice(kind="battlecry_target")，候选 = 剩余合法目标
         （同 _sanders_candidates 过滤），玩家选定后金色化——忠实建模
         "two friendly minions" 的两次独立选择
      2. 第二候选为空 → 落空（仅金色化 1 只，官方行为）
      3. Kelp Keeper/TriggerBattlecry 重触发金色 Sanders（ctx=None）:
         引擎 SPEC_GAP（本批 853 行同族台账）——TriggerBattlecry 对
         needs_target 脚本传 ctx=None 且无重定向协议，触发器族普遍
         落空/单发; 官方对重触发的目标重选未公布（wiki 无 Notes，
         已查）。本脚本按现状走第 2 分支单次选择——引擎层
         TriggerBattlecry 目标协议交付主线统一（见模块 docstring）。

    Test: test_batch_battlecry.py — 两只分别金色化（两次 PendingChoice）/
    仅一只候选时第二选择落空

    Params: 无模板参数
    """

    @staticmethod
    def battlecry(source, game, ctx):
        target = _ctx_target(ctx)
        hero = source.controller
        if target is None or hero is None:
            return None
        # 目标仍在棋盘且非金色 = 首次触发 → 金色化; 已被前序触发金色化
        # （旧实体 Transform 离场）或本就金色 → 第二次选择
        if target in hero.board and not target.is_golden:
            _goldenize(game, target)
            return None
        cands = _sanders_candidates(source, game)
        if not cands:
            return None

        def resolve(pick):
            _goldenize(game, pick)

        game.pending_choices.append(PendingChoice(
            source.controller, cands, "battlecry_target",
            resolve_callback=resolve))
        return None


class SouthseaBuskerScript:
    """
    Natural language: <b>Battlecry:</b> Gain 1 Gold next turn.

    Formal spec:
      1. 打出时（battlecry，每次触发）: ScheduleNextTurn(hero,
         GainGold(hero, 1))——下一个招募阶段开始、基础收入重置**之后**
         叠加执行（game._begin_recruit_for 顺序保证; Private Investigator
         先例）
      2. 不立即获得金币; 金色版 "2 Gold" = 引擎触发 2 次 × 1
      3. 金币持有上限 99 由 hero.gold setter 保证

    Test: test_batch_battlecry.py — 打出当回合不变 / 下回合基础收入 +1 /
    金色 +2

    Params: {0}=1（文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return ScheduleNextTurn(hero, GainGold(hero, 1))


class LovesickBalladistScript:
    """
    Natural language: <b>Battlecry:</b> Give a Pirate +{1} Health.
    <i>(Improved by each Gold you spent this turn!)</i>

    目标选择裁定: hearthstone.wiki.gg "Wiki tags" 含 [Targeted] →
    玩家选择目标（needs_target 协议），禁止随机近似。

    Improvement 公式裁定: "Improved by each Gold you spent this turn" =
    每 1 金 +1 Health，叠加在基值 num(1) 之上——每次触发
    Health = num(1) + GOLD_SPENT_THIS_TURN（tag 1030，回合开始清零）。
    依据: 34.6.0 补丁历史 "+0 Health"→"+1 Health" 基值独立于 improvement
    叠加; 卡面 @ 后 "+{0}/+{1}" 显示态为 Balladist Portrait 饰品
    ("Your Lovesick Balladists also give Attack") 专属——基础卡无
    Attack 给予，本脚本 atk=0。打出随从本身不消耗金币（BG 购买时已付），
    GOLD_SPENT_THIS_TURN 仅含刷新/购买/升级/Activate/Dark Gift 支出。

    Formal spec:
      1. 候选 = 友方棋盘存活 Pirate（含 ALL 种族、含 source 自身——文本
         无 "other"，战吼可自身为目标）
      2. 选定后: Buff(target, atk=0, health=基础 num(1) + gold_spent)
      3. 金色版 "+{1} Health twice" = 引擎触发 2 次 × 同一目标
         （单次选择，两次叠加）

    Test: test_batch_battlecry.py — 0 支出 +1 / 支出 3 金 +4 / 金色两次 /
    无 Pirate 落空 / 非 Pirate 不在候选

    Params: {1}=1（36.2.2 基线，金色同值×2 次）
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in hero.board
                if not m.dead and m.race in _PIRATE_RACES]

    @staticmethod
    def battlecry(source, game, ctx):
        target = _ctx_target(ctx)
        hero = source.controller
        if target is None or hero is None:
            return None
        d = _battlecry_def(game, source)
        base_health = d.num(1)
        if base_health is None:
            raise GameStateError(
                f"{source.card_id}: missing num(1) template param")
        spent = hero.get(GameTag.GOLD_SPENT_THIS_TURN, 0)
        return Buff(target, health=base_health + spent)


class OozelingGladiatorScript:
    """
    Natural language: <b>Battlecry:</b> Get two Slimy_Shields that give
    +1/+1 and <b>Taunt</b>.

    Formal spec:
      1. 打出时（battlecry，每次触发）: 2 张 Slimy Shield（BG27_002t，
         card_type=5 法术、非池法术——token，不占 spell_pool）入手:
         create_spell ×2 + pending_hand_add ×2（满手排队，RULES §3.3）
      2. Slimy Shield 的 "Give a minion +1/+1 and Taunt" 法术效果不在
         本批次（on_play 脚本待后续批次; 卡 id 硬编码注明: 文本
         "Slimy_Shields" 是名字，数据链无 evolution/spellcraft 字段，
         bg_cards.json 核实唯一 token id）
      3. 金色版 "four" = 引擎触发 2 次 × 每次 2 张

    Test: test_batch_battlecry.py — 入手 2 张 BG27_002t / 金色 4 张

    Params: count=2（文本字面量 "two"; token id BG27_002t 为身份标识
             非数值，数据链缺失、bg_cards.json 核实）
    """

    SLIMY_SHIELD_ID = "BG27_002t"

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        for _ in range(2):
            shield = game.create_spell(
                OozelingGladiatorScript.SLIMY_SHIELD_ID, controller=hero)
            game.pending_hand_add(hero, shield)
        return None


class DisguisedGraverobberScript:
    """
    Natural language: <b>Battlecry:</b> Destroy a friendly Undead to get
    a plain copy of it.

    目标选择裁定（作业单）: 定向——needs_target + candidates=友方 Undead。

    Formal spec:
      1. 候选 = 友方棋盘存活 Undead（含 ALL 种族，排除 source——source
         为无种族随从，过滤天然排除; 显式排除防 Amalgamation gift 等
         种族改写场景）
      2. 选定后（每次触发，按序）:
         a) 快照 base card_id（金色目标经 TRIPLE_BASE_CARD_ID 定位基础卡）
            与 is_golden——**先记录再摧毁**
         b) 目标未死时: health=0 + game.check_deaths()——完整死亡链
            （官方 Destroy 触发亡语: fire "death" → deathrattle →
            招募期死亡回池，引擎 _process_single_death 保证）
         c) plain copy 入手: create_minion(base_id, golden=快照值) +
            pending_hand_add——白板复制（不带 buff/受击状态，
            _plain_copy_to_hand 同构; 复制自有随从不占池副本）
      3. 金色版 "get 2 plain copies" = 引擎触发 2 次: 第 2 次触发时目标
         已死 → 跳过摧毁、再复制 1 张（摧毁一次、共 2 张，官方语义）

    Test: test_batch_battlecry.py — PendingChoice 流（仅 Undead 候选）/
    摧毁走死亡链（亡语触发+回池）/ plain copy 无 buff / 金色 2 张

    Params: 无模板参数
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in hero.board
                if not m.dead and m is not source and m.race in _UNDEAD_RACES]

    @staticmethod
    def battlecry(source, game, ctx):
        target = _ctx_target(ctx)
        hero = source.controller
        if target is None or hero is None:
            return None
        base_id = (target.get(GameTag.TRIPLE_BASE_CARD_ID, None)
                   or target.card_id)
        golden = target.is_golden
        if not target.dead and target.zone == Zone.PLAY:
            target.health = 0          # 先记录后摧毁（上方快照）
            game.check_deaths()        # 完整死亡链: 亡语/回池/移除
        copy = game.create_minion(base_id, controller=hero, golden=golden)
        game.pending_hand_add(hero, copy)
        return None


class OminousSeerScript:
    """
    Natural language: <b>Battlecry:</b> The next Tavern spell you buy
    costs (1) less.

    Formal spec:
      1. 打出时（battlecry，每次触发）: hero.NEXT_SPELL_COST_REDUCTION
         （tag 1056）+1——叠加式; 消费点在 game.buy_from_tavern（购买
         池法术时整体抵扣后清零，引擎已实现）
      2. 金色版 "(2) less" = 引擎触发 2 次 × 1（叠加 2，下一次购买
         共便宜 2）
      3. 只影响**购买**（buy_from_tavern），不影响手牌中法术施放

    Test: test_batch_battlecry.py — tag 置 1 / 购买酒馆法术折扣生效且
    清零 / 金色折扣 2

    Params: {0}=1（文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        hero.set(GameTag.NEXT_SPELL_COST_REDUCTION,
                 hero.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0) + 1)
        return None


class SandSwirlerScript:
    """
    Natural language: <b>Battlecry:</b> Your Elementals give an extra
    +{0} Attack this game.

    Status: DEFERRED — requires ELEMENTAL_EXTRA_ATK player tag + 消费点

    Dependency（引擎缺口，报告主线）:
      - "Your Elementals give an extra +{0} Attack this game" 是元素
        give-Attack 效果增幅——与 tags.py 1055 ELEMENTAL_EXTRA_HEALTH
        （give-Health 版）对应的 atk 版。tags.py 无 ELEMENTAL_EXTRA_ATK
        （1055 语义不同不可复用; TAVERN_SPELL_EXTRA_ATK 是酒馆法术增幅
        语义不同）; 且引擎无任何 "Elemental give-attack" 消费点可挂
      - 需主线: tags.py 入册 ELEMENTAL_EXTRA_ATK + 元素 give-Attack
        效果族（如 Elemental 派随从的 give-X-Attack 战吼/触发）统一
        出口（racefx.tavern_spell_buff 同构）后本脚本接线

    Params: {0}=2（金色 4——数据已核实，接线时经 CardDef.num(0) 取）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        return None


class AzsharanCutlassierScript:
    """
    Natural language: <b>Battlecry:</b> Your Tavern spells give an extra
    +1 Attack this game.

    Formal spec:
      1. 打出时（battlecry，每次触发）: hero.TAVERN_SPELL_EXTRA_ATK
         （tag 1053）+1——叠加式; 消费点 racefx.tavern_spell_buff
         （法术脚本对随从施加增益的统一出口，引擎已实现）
      2. 金色版 "+2 Attack" = 引擎触发 2 次 × 1
      3. 只增幅 give-Attack 分量（health 分量走 TAVERN_SPELL_EXTRA_HEALTH，
         本卡不动）

    Test: test_batch_battlecry.py — tag 置 1 / tavern_spell_buff 出口
    反映增幅 / 金色 2

    Params: {0}=1（文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        hero.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) + 1)
        return None


class EnDjinnBlazerScript:
    """
    Natural language: <b>Battlecry:</b> After the Tavern is
    <b>Refreshed</b> this game, give a random minion in it +{0}/+{1}.

    Formal spec:
      1. 打出时（battlecry，每次触发）: 注册持久监听器
         Listener(TAVERN_REFRESH, owner=hero)——"this game" 全局持续
         （owner=hero 永不注销; 随从离场不终止，官方 this game 语义）
      2. 触发条件: kw hero= 是 source 控制者（仅自己的酒馆刷新）
      3. 回调: hero.tavern 中随机 Minion（game.rng.choice）获得
         Buff(+基础 num(0)/+基础 num(1))，永久（temporary=False）——
         购买后随实体带走（BuffCurrentTavern 同语义）; 酒馆无随从时
         落空（return，真实行为）
      4. 金色版 "twice" = 引擎触发 2 次 → 注册 2 个独立监听器 →
         每次刷新两次独立随机 +10/+10（可同目标叠加）
      5. 数值经 _battlecry_def 取基础 def（金色模型; 本卡基础/金色
         num 均 10/10）

    Test: test_batch_battlecry.py — 刷新后酒馆随机随从 +10/+10 / 再刷
    再触发 / 出售后仍生效（this game）/ 酒馆空不崩 / 金色每次刷新 +20

    Params: {0}=10 {1}=10（36.2.2 基线，金色同值 ×2 触发）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _battlecry_def(game, source)
        atk, health = d.num(0), d.num(1)
        if atk is None or health is None:
            raise GameStateError(
                f"{source.card_id}: missing num(0)/num(1) template params")

        def on_refresh(g, hero=None, **kw):
            if hero is not source.controller:
                return
            minions = [e for e in source.controller.tavern
                       if isinstance(e, Minion) and not e.dead]
            if not minions:
                return
            m = g.rng.choice(minions, label="en_djinn_blazer_target")
            g.run_actions(Buff(m, atk=atk, health=health))

        game.events.register(Listener(
            event=TAVERN_REFRESH, owner=hero, callback=on_refresh))
        return None


def _mrrglton_watcher(game, source):
    """确保 hero 上注册唯一的 Mrrglton 打出计数监听器（幂等）。

    计数存储 = hero 动态属性 _mrrglton_count（作业单裁定: 对象属性而非
    GameTag——tags.py 无 MRRGLTON 计数 tag 且 subagent 禁改; hero 对象
    允许 setattr，tavern_buffs/race_auras 同先例; 无序列化需求）。
    监听器 owner=hero（"this game" 持续，随从离场不注销; 多只 Mrrglton
    幂等共享一个 watcher，避免重复计数）。
    """
    hero = source.controller
    if hero is None:
        return
    if getattr(hero, "_mrrglton_watcher", None) is not None:
        return

    def on_played(g, card=None, **kw):
        if card is None or card.controller is not hero:
            return
        if card.card_id not in _MRRGLTON_IDS:
            return
        hero._mrrglton_count = getattr(hero, "_mrrglton_count", 0) + 1
        card._mrrglton_own_counted = True   # 自身打出已计入（战吼后置）

    lst = Listener(event=CARD_PLAYED, owner=hero, callback=on_played)
    hero._mrrglton_watcher = lst
    game.events.register(lst)


def _mrrglton_effective_count(hero, source):
    """战吼时点的有效 Mrrglton 打出数（含当前这张——见裁定）。

    裁定: "Improved by each Mrrglton you played this game"（wiki
    hearthstone.wiki.gg/wiki/Battlegrounds/Mama_Mrrglton——36.2.2
    文本 +2→+3）自身计入（打出动作先于战吼结算完成; Balladist
    "Gold you spent" 同构——支付/打出即计数）。引擎 card_played 事件
    晚于战吼触发 → 自身经 _mrrglton_own_counted 标志检测（watcher 在
    事件中对 card is source 置位）。已打出过的重触发（Kelp Keeper 等）
    不重复计数。**召唤入场（从未打出）的 Mrrglton 被重触发时不计
    自身**（"played" 文本口径——2026-08-23 修正: 经 _in_play_effects
    栈帧检测区分自然打出路径（play_minion → _run_play_effects）与
    TriggerBattlecry 直调路径，后者不计自身）。
    """
    n = getattr(hero, "_mrrglton_count", 0)
    if source.card_id in _MRRGLTON_IDS \
            and not getattr(source, "_mrrglton_own_counted", False) \
            and _in_play_effects():
        n += 1
    return n


def _in_play_effects() -> bool:
    """当前调用链是否位于引擎 _run_play_effects（自然打出的战吼路径）。

    play_minion → _run_play_effects → battlecry 钩子（金色×2/Brann 均
    在内）; TriggerBattlecry（Kelp Keeper 等）直接 call_script——不在
    链上。脚本层区分两路径的唯一可靠信号（引擎 ctx 无路径标记，
    引擎层缺口上报主线）。
    """
    import inspect
    frame = inspect.currentframe()
    try:
        while frame is not None:
            if frame.f_code.co_name == "_run_play_effects":
                return True
            frame = frame.f_back
    finally:
        del frame
    return False


def _mrrglton_buffs(source, game, ctx, is_mama: bool):
    """Mrrglton 战吼公共实现: 其他友方棋盘 Murloc 各 +（基础 num(0) +
    有效计数）的单维 Buff（is_mama: True=Attack / False=Health）。"""
    hero = source.controller
    if hero is None:
        return None
    d = _battlecry_def(game, source)
    base = d.num(0)
    if base is None:
        raise GameStateError(
            f"{source.card_id}: missing num(0) template param")
    n = base + _mrrglton_effective_count(hero, source)
    out = []
    for m in hero.board:
        if m is source or m.dead or m.race not in _MURLOC_RACES:
            continue
        out.append(Buff(m, atk=n) if is_mama else Buff(m, health=n))
    return out or None


class MamaMrrgltonScript:
    """
    Natural language: <b>Battlecry:</b> Give your other Murlocs +{0} Attack.
    <i>(Improved by each Mrrglton you played this game!)</i>

    Formal spec:
      1. on_summon: 注册 hero 级唯一计数 watcher（_mrrglton_watcher，
         card_played 事件，Mama/Papa 共享计数——"Mrrglton" 家族 =
         BG35_140/141 + 金色变体，Cousin Errgl 除外）
      2. battlecry（每次触发）: 其他友方棋盘 Murloc（含 ALL、排除
         source）各 +（基础 num(0) + 有效计数）Attack; 计数含当前打出
         （_mrrglton_effective_count 裁定）
      3. 金色版 "+6" = 引擎触发 2 次 ×（3 + 计数）——金色模型
         （金色 def num(0)=6 = 2×基础 3）
      4. 每次"打出"计数 +1（Brann/金色多触发不重复计数——计数在
         card_played 事件，每打出一卡只 fire 一次）

    Test: test_batch_battlecry.py — 首只 +3+1=+4（自身计入裁定）/
    第二只 +3+2 / 非 Murloc 不受 / Papa 共享计数 / 金色 ×2 触发

    Params: {0}=3（36.2.2 基线，金色 =6 经 2 次触发自然体现）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        _mrrglton_watcher(game, source)
        return None

    @staticmethod
    def battlecry(source, game, ctx):
        return _mrrglton_buffs(source, game, ctx, is_mama=True)


class PapaMrrgltonScript:
    """
    Natural language: <b>Battlecry:</b> Give your other Murlocs +{0} Health.
    <i>(Improved by each Mrrglton you played this game!)</i>

    Formal spec:
      1. 同 Mama（共享 watcher 与计数）; battlecry 为 Health 分量
         （add_buff 联动 HEALTH 当前值）
      2. 金色版 "+6" = 2 次触发 ×（3 + 计数）

    Test: test_batch_battlecry.py — Health 分量 / 与 Mama 共享计数

    Params: {0}=3（36.2.2 基线，金色 =6 经 2 次触发自然体现）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        _mrrglton_watcher(game, source)
        return None

    @staticmethod
    def battlecry(source, game, ctx):
        return _mrrglton_buffs(source, game, ctx, is_mama=False)


class LaboratoryAssistantScript:
    """
    Natural language: <b>Battlecry:</b> Add a <b>Fodder</b> to your
    next {0} <b>Refreshes</b>.

    Formal spec:
      1. 打出时（battlecry，每次触发）: 注册一个 TAVERN_REFRESH 监听器
         （owner=hero——承诺型效果，随从离场不终止; 每监听器自带
         num(0) 次配额闭包）
      2. 触发条件: kw hero= 是 source 控制者; 回调: 配额 > 0 时
         create_minion(FODDER_CARD_ID)（token 非池卡不占池）置
         TAVERN 区 append 到 hero.tavern，配额 -1（与引擎
         refresh_tavern 的 Fodder 附加行为同构）
      3. 引擎协议说明（作业单偏离报告）: game._fodder_refresh_pending
         是 Dict[Hero, int]（每次刷新固定附加 1 枚），**无法表达金色
         "two Fodders"×每刷新** 的乘数组合——本脚本改用每触发注册
         一个监听器的可叠加模型: 基础 1 触发 = 3 次刷新各 +1（与引擎
         协议观察等价）; 金色 2 触发 = 3 次刷新各 +2（官方金色语义，
         引擎协议下会错成 6 次刷新各 +1）; Brann 组合同理正确
      4. Fodder 自身 "feeds itself" 行为（BG35_150t）不在本批次
      5. 金色 num(0)=3 与基础相同（金色差异仅在触发次数）

    Test: test_batch_battlecry.py — 3 次刷新各 1 枚 / 第 4 次不再附加 /
    金色每次刷新 2 枚（共 3 次刷新）

    Params: {0}=3（36.2.2 基线，金色同值; 触发次数差异由引擎金色模型
             处理）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _battlecry_def(game, source)
        refreshes = d.num(0)
        if refreshes is None:
            raise GameStateError(
                f"{source.card_id}: missing num(0) template param")
        state = {"left": refreshes}

        def on_refresh(g, hero=None, **kw):
            if hero is not source.controller or state["left"] <= 0:
                return
            fodder = g.create_minion(FODDER_CARD_ID,
                                     controller=source.controller)
            fodder.zone = Zone.TAVERN
            source.controller.tavern.append(fodder)
            state["left"] -= 1

        game.events.register(Listener(
            event=TAVERN_REFRESH, owner=hero, callback=on_refresh))
        return None


class VoidPupTrainerScript:
    """
    Natural language: <b>Battlecry:</b> Give minions in the Tavern from
    Tier 3 and below +{0}/+{1} this game.

    Formal spec:
      1. 打出时（battlecry，每次触发，两面）:
         a) 持久面: ApplyTavernBuff(hero, TavernBuff(+num(0)/+num(1),
            max_tier=3))——登记 hero.tavern_buffs，refresh_tavern 对
            新入馆随从自动应用（引擎已接线; 冻结保留项不重复应用）
         b) 立即面: BuffCurrentTavern(同一 buff)——当前酒馆内 T≤3
            随从立即 +num(0)/+num(1)（永久，购买带走）
      2. 匹配: TavernBuff.matches 按 CardDef.tech_level ≤ 3（tier 过滤
         与 _pool_candidates 一致）
      3. 金色版 "+6/+6" = 引擎触发 2 次 ×（3/3）: 当前酒馆 buff 两次
         +3/+3，持久登记两条 → 未来刷新 +6/+6（金色 def num=6=2×3，
         每触发取基础值，金色模型）
      4. "this game" = 持久登记不随随从离场失效（hero 级数据）

    Test: test_batch_battlecry.py — 当前馆 T≤3 +3/+3、T4+ 不变 / 刷新后
    新入馆 T≤3 自动 +3/+3 / 冻结项不重复 / 金色 +6 总额

    Params: {0}=3 {1}=3（36.2.2 基线，金色 6/6 经 2 次触发自然体现）;
             max_tier=3 为文本字面量（"Tier 3 and below"）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _battlecry_def(game, source)
        atk, health = d.num(0), d.num(1)
        if atk is None or health is None:
            raise GameStateError(
                f"{source.card_id}: missing num(0)/num(1) template params")
        tb = TavernBuff(atk=atk, health=health, max_tier=3,
                        source_id=source.card_id)
        return [ApplyTavernBuff(hero, tb), BuffCurrentTavern(hero, tb)]


class BilgewaterBreakoutScript:
    """
    Natural language: <b>Battlecry:</b> Get a Lockbox. If you already have
    one, it opens {0} turn(s) sooner instead.

    Formal spec:
      1. 打出时（battlecry，每次触发）:
         分支 A（手牌已有 Lockbox，card_id == LOCKBOX_CARD_ID）:
         game.open_lockbox_early(hero, 基础 num(0))——已有 Lockbox 倒计时
         提前，归零即开（随机有种族金色随从，引擎 _open_lockbox 保证）
         分支 B: create_spell(LOCKBOX_CARD_ID)（初始倒计时 = Lockbox
         CardDef num(0)=5，create_spell 保证）+ pending_hand_add
      2. 金色模型（基础类）: Brann 等多触发时逐次结算——第 1 次入手
         Lockbox、第 2 次走分支 A 提前开启（官方 Brann 交互同理）
      3. 金色子类（"opens {0}=2 turns sooner" 单次总额，非 twice 语义）
         见 BilgewaterBreakoutGoldenScript

    Test: test_batch_battlecry.py — 无 Lockbox 入手（倒计时=Lockbox
    num(0)）/ 已有走 early 路径倒计时 -1 / 金色 -2 且新 Lockbox 不被
    误提前

    Params: {0}=1（36.2.2 基线，金色 =2）
    """

    @staticmethod
    def _already_has_lockbox(hero):
        return any(card.card_id == LOCKBOX_CARD_ID for card in hero.hand)

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _battlecry_def(game, source)
        turns = d.num(0)
        if turns is None:
            raise GameStateError(
                f"{source.card_id}: missing num(0) template param")
        if BilgewaterBreakoutScript._already_has_lockbox(hero):
            game.open_lockbox_early(hero, turns)
            return None
        lockbox = game.create_spell(LOCKBOX_CARD_ID, controller=hero)
        game.pending_hand_add(hero, lockbox)
        return None


class BilgewaterBreakoutGoldenScript(BilgewaterBreakoutScript):
    """
    Natural language: <b>Battlecry:</b> Get a Lockbox. If you already have
    one, it opens {0} turn(s) sooner instead.（金色 num(0)=2）

    Formal spec:
      1. 金色文本是**单次总额**（"opens 2 turns sooner"），非 "twice"
         ——引擎对金色战吼触发 2 次会错误地把刚入手的 Lockbox 再提前
         2 回合（基础类逐次结算模型对金色不成立）。故守卫: 每实体仅
         首次触发结算完整金色效果（金色 def num(0)=2），后续触发 no-op
         （实体级 _breakout_resolved 动态属性，作业单 setattr 模式）
      2. Brann + 金色 = 官方应双倍（-4）——本守卫模型不放大（SPEC_GAP
         报告主线: 需引擎区分"金色总额型"战吼的触发计数）
      3. Kelp Keeper 重触发金色: 守卫后 no-op（同上 SPEC_GAP）

    Test: test_batch_battlecry.py — 金色无 Lockbox 入手且倒计时不提前 /
    金色已有 Lockbox 提前 2

    Params: {0}=2（金色 CardDef，36.2.2 基线）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        if getattr(source, "_breakout_resolved", False):
            return None
        source._breakout_resolved = True
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        turns = d.num(0)
        if turns is None:
            raise GameStateError(
                f"{source.card_id}: missing num(0) template param")
        if BilgewaterBreakoutScript._already_has_lockbox(hero):
            game.open_lockbox_early(hero, turns)
            return None
        lockbox = game.create_spell(LOCKBOX_CARD_ID, controller=hero)
        game.pending_hand_add(hero, lockbox)
        return None


class RefreshingAnomalyScript:
    """
    Natural language: <b>Battlecry:</b> Gain 2 free <b>Refreshes</b>.

    Formal spec:
      1. 打出时（battlecry，每次触发）: hero.FREE_REFRESH_REMAINING
         （tag 1034）+2——refresh_tavern 消费（优先于金币扣减，引擎
         已实现）; Fresh Perspective Dark Gift 同构
      2. 金色版 "4 free Refreshes"（TB_BaconUps_167）= 引擎触发 2 次 × 2

    Test: test_batch_battlecry.py — tag +2 / 刷新优先消耗免费次数 /
    金色 +4

    Params: {0}=2（文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        hero.set(GameTag.FREE_REFRESH_REMAINING,
                 hero.get(GameTag.FREE_REFRESH_REMAINING, 0) + 2)
        return None


def register() -> list[str]:
    """注册本批次脚本（含金色 id）。DEFERRED 卡不注册（缺口审计盯）。"""
    from hsrl2.scripts.registry import register as reg

    registered: list[str] = []
    for card_id, script in (
        ("BG23_002", ShellCollectorScript),
        ("BG23_002_G", ShellCollectorScript),            # 2×1 枚
        ("BG25_011", NerubianDeathswarmerScript),
        ("BG25_011_G", NerubianDeathswarmerScript),      # 2×+1 = +2
        ("BG25_034", CaptainSandersScript),
        ("BG25_034_G", CaptainSandersGoldenScript),      # two friendly minions
        ("BG26_135", SouthseaBuskerScript),
        ("BG26_135_G", SouthseaBuskerScript),            # 2×1 金
        ("BG26_814", LovesickBalladistScript),
        ("BG26_814_G", LovesickBalladistScript),         # twice 同目标
        ("BG27_002", OozelingGladiatorScript),
        ("BG27_002_G", OozelingGladiatorScript),         # 2×2 = four
        ("BG28_303", DisguisedGraverobberScript),
        ("BG28_303_G", DisguisedGraverobberScript),      # 2 plain copies
        ("BG31_330", OminousSeerScript),
        ("BG31_330_G", OminousSeerScript),               # (2) less
        ("BG33_830", AzsharanCutlassierScript),
        ("BG33_830_G", AzsharanCutlassierScript),        # +2 Attack
        ("BG34_865", EnDjinnBlazerScript),
        ("BG34_865_G", EnDjinnBlazerScript),             # twice/refresh
        ("BG35_140", MamaMrrgltonScript),
        ("BG35_140_G", MamaMrrgltonScript),              # 2×(3+count)
        ("BG35_141", PapaMrrgltonScript),
        ("BG35_141_G", PapaMrrgltonScript),              # 2×(3+count)
        ("BG35_150", LaboratoryAssistantScript),
        ("BG35_150_G", LaboratoryAssistantScript),       # 2 枚/刷新×3 次
        ("BG35_152", VoidPupTrainerScript),
        ("BG35_152_G", VoidPupTrainerScript),            # 2×3/3 = 6/6
        ("BG36_520", BilgewaterBreakoutScript),
        ("BG36_520_G", BilgewaterBreakoutGoldenScript),  # 单次总额 num=2
        ("BGS_116", RefreshingAnomalyScript),
        ("TB_BaconUps_167", RefreshingAnomalyScript),    # 2×2 = 4
    ):
        reg(card_id, script)
        registered.append(card_id)
    # DEFERRED（不注册）: BG32_841 / BG32_841_G Sand Swirler —
    # 需 ELEMENTAL_EXTRA_ATK tag + 元素 give-Attack 消费点（见类 docstring）
    return registered
