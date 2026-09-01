"""批次 spells2 — 13 张池法术（作业单 2026-08-21）。

覆盖: BG28_604 Butchering / BG28_606 Spitescale Special / BG28_607
Corrupted Cupcakes / BG28_698 Gem Confiscation / BG28_800 Careful
Investment / BG28_805 Strike Oil / BG28_810 Tavern Coin / BG28_825
Defender's Rites / BG28_827 Leaf Through the Pages / BG28_830 Golden
Touch / BG28_838 Perfect Vision / BG28_845 Natural Blessing /
BG28_849 Saloon's Finest。

状态: 10 OK / 3 DEFERRED（BG28_698 / BG28_805 / BG28_849 — 引擎缺口，
见各类 docstring 与 register() 尾注）。

法术金色版说明（本批通用裁定）: 数据基线 36.2.2 中池法术文本 "@" 后
为金色版文本，但法术 CardDef 无 triple_upgrade_id、data 无独立金色
法术定义（db.golden_version(法术) → None）——金色法术实体在引擎中
无获取路径、不可达。脚本一律从被施放法术自身 CardDef.num() 取值，
金色差异（如 Butchering "+{0}/{1}"）若未来数据补金色定义则自然生效。

引擎缺口报告（本批上报主线，均不近似实现）:
  1. income_cap: gold_base_income 全局封顶 10（constants.py:19），
     无 hero 级 "maximum Gold" 修正 → Strike Oil DEFERRED
  2. spells_only refresh: refresh_tavern 无 spells_only 参数
     （game.py:234）→ Saloon's Finest DEFERRED
  3. Blood Gem 记账: PlayBloodGems/BloodGemScript 产生的 Buff 无
     gem 来源标志（entity.Buff.source_id 为空）→ "steals all Blood
     Gems"（Gem Confiscation）无法区分宝石 buff 与其他 buff
     → DEFERRED
  4. Transform 仅支持棋盘目标（actions/stats.py:88 对酒馆实体抛
     GameStateError）→ Golden Touch 以 _goldenize_tavern 就地实现
     （本体逻辑与 Transform 同构），建议主线将 Transform 泛化到
     TAVERN zone 后回收本 helper
  5. 新 Action SetStats（Perfect Vision）定义于本文件——SOP §4 要求
     新 Action 落 scripts/_actions.py 并主线评审，因作业白名单仅
     2 文件而暂置于此，请主线归档
"""

from __future__ import annotations

from hsrl2.actions.consume import ConsumeRandomTavernMinion
from hsrl2.actions.economy import GainGold, ScheduleNextTurn
from hsrl2.actions.racefx import ApplyRaceAura, tavern_spell_buff
from hsrl2.actions.stats import GainKeyword
from hsrl2.queue import Action
from hsrl2.tags import GameTag, Race, Zone


# ═════════════════════════ 通用 helper ═════════════════════════


def _ctx_target(ctx):
    return (ctx or {}).get("target")


def _def(game, source):
    d = game.db.get(source.card_id)
    if d is None:
        raise ValueError(f"unknown card {source.card_id}")
    return d


_UNDEAD_RACES = (Race.UNDEAD, Race.ALL)
_DEMON_RACES = (Race.DEMON, Race.ALL)


# ═════════════════════ BG28_604 Butchering ═════════════════════


class ButcheringScript:
    """
    Natural language: Destroy a friendly Undead. Your Undead have +{0}
    Attack this game <i>(wherever they are).</i>@Destroy a friendly
    Undead. Your Undead have +{0}/+{1} this game <i>(wherever they
    are).</i>

    Formal spec:
      1. 定向（"Destroy a friendly Undead"——含 Choose 语义 → 引擎
         play_spell 产生 PendingChoice(kind="spell_target")）: 候选 =
         友方棋盘存活 Undead（含 Race.ALL——Amalgam 是 Undead）
      2. 选定后按文本序: a) 摧毁目标——health=0 + check_deaths 完整
         死亡链（death 事件→亡语→招募期死亡回池; Disguised Graverobber
         先例）; b) ApplyRaceAura(hero, UNDEAD, num(0), num(1, 0))——
         board/hand/未来 Undead 全生效（"wherever they are"）
      3. 无 Undead 候选: 法术落空但照常消耗（引擎 no-candidate 路径，
         ctx 无 target → return None）
      4. 防御: 显式 target 非 Minion / 非 Undead 种族 / 已离场 → None
         （引擎流不会送达非法目标; 显式 target 由调用方保证合法性）
      5. 金色段 "+"{0}/{1}"（@ 后）在当前数据无独立金色法术定义，
         不可达; num(1, 0) 写法使未来金色定义补齐时生命分量自然生效

    Test: test_batch_spells2.py — PendingChoice 仅 Undead 候选 /
    摧毁走死亡链（GRAVEYARD+回池）/ 手牌 Undead 也获光环 / 无 Undead
    落空不施光环

    Params: {0}=5 {1}=0
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in hero.board
                if not m.dead and m.race in _UNDEAD_RACES]

    @staticmethod
    def on_play(source, game, ctx):
        from hsrl2.minion import Minion
        hero = source.controller
        target = _ctx_target(ctx)
        if hero is None or not isinstance(target, Minion):
            return None
        if target.race not in _UNDEAD_RACES:
            return None                    # 防御（见 spec 4）
        d = _def(game, source)
        if target.dead or target not in hero.board:
            return None
        target.health = 0
        game.check_deaths()                # 完整死亡链（亡语/回池）
        return [ApplyRaceAura(hero, Race.UNDEAD, d.num(0), d.num(1, 0),
                              source_id=source.card_id)]


# ══════════════════ BG28_606 Spitescale Special ══════════════════


def _spellcraft_spell_ids(game) -> list[str]:
    """Spellcraft 法术池识别（数据链，无硬编码 id）:

    池内 Spellcraft 随从（db.pool_minions——已排除金色定义）的
    spellcraft_id（dbf）指向的法术定义 = 全部可获取的 Spellcraft 法术
    （36.2.2 基线共 9 张基础版; 金色法术仅由金色随从生成，不入候选）。
    排序保证 rng.sample 可复现。
    """
    ids: set[str] = set()
    for d in game.db.pool_minions():
        if d.spellcraft_id is None:
            continue
        t = game.db.by_dbf(d.spellcraft_id)
        if t is not None:
            ids.add(t.id)
    return sorted(ids)


class SpitescaleSpecialScript:
    """
    Natural language: Get 3 random <b>Spellcraft</b> spells.

    Formal spec:
      1. on_play: 候选 = _spellcraft_spell_ids（池 Spellcraft 随从
         spellcraft_id 数据链解析，非硬编码）; game.rng.sample 无放回
         抽 3 张**不同**法术（作业单裁定; 候选 9 ≥ 3）
      2. 每张: create_spell + 置 SPELLCRAFT tag（回合末丢弃协议，
         game.py end_recruit_phase 以该 tag 键控; 不设
         spellcraft_source_uuid——非随从生成，无 Sunken Persistence
         豁免）+ pending_hand_add（满手排队 P6）
      3. 非池 token（is_pool_spell 为空）: 不占 spell_pool
         （SOP §3 token 语义; 与 _make_spellcraft_spell 一致）
      4. 候选不足 3: 取 min(3, len)（数据缺口防御，当前 9 张不触发）

    Test: test_batch_spells2.py — 3 张互不相同且均在 Spellcraft 数据链
    内 / 全部带 SPELLCRAFT tag / 不占法术池

    Params: count=3（文本字面量——CardDef 无模板参数）
    """

    COUNT = 3    # "Get 3 random"（文本字面量）

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cands = _spellcraft_spell_ids(game)
        if not cands:
            return None
        k = min(SpitescaleSpecialScript.COUNT, len(cands))
        for sid in game.rng.sample(cands, k, label="spitescale_special"):
            s = game.create_spell(sid, controller=hero)
            s.set(GameTag.SPELLCRAFT, True)
            game.pending_hand_add(hero, s)
        return None


# ══════════════════ BG28_607 Corrupted Cupcakes ══════════════════


class CorruptedCupcakesScript:
    """
    Natural language: Choose a friendly Demon. It consumes 3 random
    minions in the Tavern to gain their stats.

    Formal spec:
      1. 定向（"Choose a friendly Demon"）: 候选 = 友方棋盘存活 Demon
         （含 Race.ALL）; 引擎 PendingChoice(kind="spell_target")
      2. 选定后: 3 次独立 ConsumeRandomTavernMinion(target)——每次从
         hero.tavern 随机吞 1 个（atk + max_health 快照并入; 酒馆来源
         回池; 不触发亡语——actions/consume.py 契约）; 馆内不足 3 个
         时后继次落空（Action 空候选 return，官方行为）
      3. 无 Demon 候选: 法术落空但照常消耗

    Test: test_batch_spells2.py — PendingChoice 仅 Demon 候选 / 3 连吞
    属性并入+回池 / 馆内仅 1 个时只吞 1 / 无 Demon 落空

    Params: count=3（文本字面量——CardDef 无模板参数）
    """

    COUNT = 3    # "consumes 3 random"（文本字面量）

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in hero.board
                if not m.dead and m.race in _DEMON_RACES]

    @staticmethod
    def on_play(source, game, ctx):
        from hsrl2.minion import Minion
        target = _ctx_target(ctx)
        if not isinstance(target, Minion) or target.dead:
            return None
        if target.race not in _DEMON_RACES:
            return None                    # 防御（同 Butchering spec 4）
        return [ConsumeRandomTavernMinion(target)
                for _ in range(CorruptedCupcakesScript.COUNT)]


# ══════════════════ BG28_698 Gem Confiscation（DEFERRED） ══════════════════


class GemConfiscationScript:
    """
    Natural language: [x]This plays 2 <b>Blood Gems</b> on a minion.
    It steals all <b>Blood Gems</b> from its neighbors.

    Status: DEFERRED — requires 血宝石逐随从记账
    Dependency: ① PlayBloodGems / BloodGemScript.on_play 产生的
    entity.Buff 无 gem 来源标志（source_id 为空），无法从邻居既有
    buff 中区分出 Blood Gem; 需主线为宝石 buff 打标（gem 标志或
    source_id="BG20_GEM"）。② 需 Steal 移转语义: 目标右/左邻的宝石
    buff 全部摘除并以 PlayBloodGems 等价次数转施于目标。
    """
    @staticmethod
    def on_play(source, game, ctx):
        return None


# ══════════════════ BG28_800 Careful Investment ══════════════════


class CarefulInvestmentScript:
    """
    Natural language: Gain 2 Gold next turn.

    Formal spec:
      1. on_play: ScheduleNextTurn(hero, GainGold(hero, amount=2))——
         game.defer_until_next_turn 队列化，下一招募回合开始时在
         基础收入重置**之后**结算（game._begin_recruit_for 官方顺序，
         "下回合获得 X 金"叠加在收入之上; Southsea Busker 先例）
      2. 当回合金币不变

    Test: test_batch_spells2.py — 当回合 +0 / 下回合开始 = 基础收入+2

    Params: amount=2（文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return [ScheduleNextTurn(hero, GainGold(hero, amount=2))]


# ══════════════════ BG28_805 Strike Oil（DEFERRED） ══════════════════


class StrikeOilScript:
    """
    Natural language: Increase your maximum Gold by 1.

    Status: DEFERRED — requires hero 级收入上限修正
    Dependency: "maximum Gold" = 每回合自然增长上限（10 → 11）。
    引擎 constants.gold_base_income(turn) 全局 min(·, GOLD_INCOME_CAP=10)
    硬编码封顶，Hero 无 income_cap 修正位; GOLD_HOLD_CAP=99 是持有上限
    （另一概念）。需主线为 Hero 增加 max_gold 修正 tag 并在收入函数
    消费后本卡才可实现（GOLD_HOLD_CAP/收入函数均不可由脚本层修改）。
    """
    @staticmethod
    def on_play(source, game, ctx):
        return None


# ══════════════════ BG28_810 Tavern Coin ══════════════════


class TavernCoinScript:
    """
    Natural language: Gain 1 Gold.

    Formal spec:
      1. on_play: GainGold(hero, amount=1)——hero.gold setter 执行
         99 持有上限与 max(0,·)（RULES §1.4）

    Test: test_batch_spells2.py — 金币 +1（越过持有上限钳制）

    Params: amount=1（文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return [GainGold(hero, amount=1)]


# ══════════════════ BG28_825 Defender's Rites ══════════════════


class DefendersRitesScript:
    """
    Natural language: Give a minion +{0}/+{1} and <b>Taunt</b>.

    Formal spec:
      1. 定向（"Give a minion ..."）: 默认候选 = 友方棋盘存活随从
         （引擎 play_spell 缺省候选集，无需自定义 target_candidates）
      2. 选定后: tavern_spell_buff(target, num(0), num(1))——经
         racefx 统一出口，TAVERN_SPELL_EXTRA_ATK/HEALTH 增幅自动叠加
         （"Your Tavern spells give an extra +X" 家族）+
         GainKeyword(TAUNT)
      3. 无候选（空场）: 法术落空但照常消耗

    Test: test_batch_spells2.py — +num(0)/+num(1)+嘲讽 / EXTRA 增幅
    叠加 / 空场落空

    Params: {0}=7 {1}=7
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        from hsrl2.minion import Minion
        target = _ctx_target(ctx)
        if not isinstance(target, Minion) or target.dead:
            return None
        d = _def(game, source)
        return [tavern_spell_buff(target, atk=d.num(0), health=d.num(1)),
                GainKeyword(target, GameTag.TAUNT)]


# ══════════════════ BG28_827 Leaf Through the Pages ══════════════════


class LeafThroughThePagesScript:
    """
    Natural language: Gain 2 free <b>Refreshes</b>.

    Formal spec:
      1. on_play: hero.FREE_REFRESH_REMAINING += 2（叠加式）; 消费点
         game.refresh_tavern（手动刷新优先扣免费次数再扣金币;
         En-Djinn Blazer / Refreshing Anomaly 先例）

    Test: test_batch_spells2.py — tag 0→2 / 刷新先扣免费次数不扣金币

    Params: count=2（文本字面量——CardDef 无模板参数）
    """

    COUNT = 2    # "Gain 2 free Refreshes"（文本字面量）

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        hero.set(GameTag.FREE_REFRESH_REMAINING,
                 hero.get(GameTag.FREE_REFRESH_REMAINING, 0)
                 + LeafThroughThePagesScript.COUNT)
        return None


# ══════════════════ BG28_830 Golden Touch ══════════════════


def _goldenize_tavern(game, target):
    """酒馆内实体金色化（Reno 语义同 batch_battlecry._goldenize）:

    Transform Action 仅支持棋盘目标（actions/stats.py 对非 board 抛
    GameStateError）→ 此处同构实现: 换金色卡定义（create_minion
    golden=True 补 GOLDEN + TRIPLE_BASE_CARD_ID tag）、buff 并集保留、
    原位替换 hero.tavern、fire "transform"、不发三连奖励。上报主线:
    Transform 泛化到 TAVERN zone 后本 helper 应回收（模块 docstring
    缺口 4）。
    """
    from hsrl2.minion import Minion
    if not isinstance(target, Minion) or target.is_golden:
        return False
    hero = target.controller
    if hero is None or target not in hero.tavern:
        return False
    base_def = game.db.get(target.card_id)
    golden_def = (game.db.golden_version(base_def)
                  if base_def is not None else None)
    if golden_def is None:
        return False
    new = game.create_minion(golden_def.id, controller=hero, golden=True)
    new._buffs = list(target._buffs)          # buff 并集（Transform 同构）
    new.set(GameTag.HEALTH, new.max_health)
    new.set(GameTag.GILDED_NOT_TRIPLED, True)  # Reno 式: 回池按 1 份
    idx = hero.tavern.index(target)
    new.zone = Zone.TAVERN
    hero.tavern[idx] = new
    target.zone = Zone.REMOVED
    game.events.unregister_owner(target)
    game.events.fire(game, "transform", old=target, new=new)
    return True


class GoldenTouchScript:
    """
    Natural language: Make a random minion in the Tavern Golden.

    Formal spec:
      1. 候选 = hero.tavern 中的 Minion 实体（法术不可金色化）、非金色
         （Reno 先例）、db.golden_version 存在; 空候选 → 落空
      2. game.rng.choice 随机选定 → _goldenize_tavern: 换金色卡定义、
         buff 保留、**不发三连奖励**（金色化 ≠ 三连）、不占池不动池
      3. 原位替换（保留馆内顺序）

    Test: test_batch_spells2.py — 随机一只变金色（buff 保留、无三连
    奖励、池不动）/ 已金色与无金色定义排除 / 空馆落空

    Params: 无数值参数（无模板参数）
    """

    @staticmethod
    def on_play(source, game, ctx):
        from hsrl2.minion import Minion
        hero = source.controller
        if hero is None:
            return None
        cands = []
        for e in hero.tavern:
            if not isinstance(e, Minion) or e.dead or e.is_golden:
                continue
            d = game.db.get(e.card_id)
            if d is None or game.db.golden_version(d) is None:
                continue
            cands.append(e)
        if not cands:
            return None
        pick = game.rng.choice(cands, label="golden_touch")
        _goldenize_tavern(game, pick)
        return None


# ══════════════════ BG28_838 Perfect Vision ══════════════════


class SetStats(Action):
    """目标属性**设为** atk/health（覆盖式）。

    语义裁定（"Set a minion's stats to X/Y"）: 附魔全部清除
    （含 debuff/temporary/dark_gift）、BASE_ATK/BASE_HEALTH 覆盖为
    X/Y、HEALTH 同步 Y——"set" 后随从恰为 X/Y，后续 buff 正常叠加。
    种族光环（race_auras）独立于实体附魔，不受影响（"this game
    wherever they are" 家族与 set 正交）。

    新 Action 暂置于本批次文件（白名单约束），请主线归档至
    scripts/_actions.py（模块 docstring 缺口 5）。
    """

    def __init__(self, target, atk: int, health: int) -> None:
        self.target = target
        self.atk = atk
        self.health = health

    def do(self, game) -> None:
        for b in self.target.buffs:
            self.target.remove_buff(b)
        self.target.set(GameTag.BASE_ATK, self.atk)
        self.target.set(GameTag.BASE_HEALTH, self.health)
        self.target.set(GameTag.HEALTH, self.health)


class PerfectVisionScript:
    """
    Natural language: Set a minion's stats to {0}/{1}.

    Formal spec:
      1. 定向（默认候选 = 友方棋盘存活随从）
      2. 选定后: SetStats(target, num(0), num(1))——覆盖式重置
         （buff 清除、BASE 覆盖、HEALTH 同步; 见 SetStats docstring）
      3. 无候选: 法术落空但照常消耗

    Test: test_batch_spells2.py — buff 后随从被重置为 num(0)/num(1) /
    空场落空

    Params: {0}=20 {1}=20
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        from hsrl2.minion import Minion
        target = _ctx_target(ctx)
        if not isinstance(target, Minion) or target.dead:
            return None
        d = _def(game, source)
        return [SetStats(target, d.num(0), d.num(1))]


# ══════════════════ BG28_845 Natural Blessing ══════════════════


def _shares_type(minion_race: Race, target_race: Race) -> bool:
    """随从是否与目标共享至少一个种族（ChefsChoiceScript 同族裁定）:

    - 目标 ALL: 一切**有类型**随从共享（NONE 无类型不共享）
    - 目标 NONE: 仅 NONE 共享
    - 目标 R: race ∈ (R, ALL) 共享（Amalgam 是一切种族）
    """
    if target_race == Race.ALL:
        return minion_race != Race.NONE
    if target_race == Race.NONE:
        return minion_race == Race.NONE
    return minion_race in (target_race, Race.ALL)


class NaturalBlessingScript:
    """
    Natural language: Choose a minion. Give all minions that share a
    type with it +{0}/+{1}.

    Formal spec:
      1. 定向（"Choose a minion"）: 默认候选 = 友方棋盘存活随从
      2. 选定后: 受体 = 友方棋盘全部与目标共享至少一个种族的存活
         随从（**含目标自身**——目标与自己共享; _shares_type: 目标
         ALL → 一切有类型随从; 目标 NONE → 仅无类型; 目标 R →
         race ∈ (R, ALL)）
      3. 每个受体经 tavern_spell_buff(+num(0), +num(1))——酒馆法术
         EXTRA 增幅出口
      4. 无候选（空场）: 法术落空但照常消耗

    Test: test_batch_spells2.py — Murloc 目标 buff 含自身的 Murloc+
    Amalgam、Beast/无类型不变 / ALL 目标覆盖全体有类型 / NONE 目标仅
    无类型 / EXTRA 增幅叠加

    Params: {0}=3 {1}=3
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        from hsrl2.minion import Minion
        hero = source.controller
        target = _ctx_target(ctx)
        if hero is None or not isinstance(target, Minion) or target.dead:
            return None
        d = _def(game, source)
        return [tavern_spell_buff(m, atk=d.num(0), health=d.num(1))
                for m in hero.board
                if not m.dead and _shares_type(m.race, target.race)]


# ══════════════════ BG28_849 Saloon's Finest（DEFERRED） ══════════════════


class SaloonsFinestScript:
    """
    Natural language: <b>Refresh</b> the Tavern with Tavern spells.

    Status: DEFERRED — requires refresh_tavern spells_only 模式
    Dependency: game.refresh_tavern(game.py:234) 无 spells_only 参数
    ——固定抽取随从 offers + TAVERN_SPELLS_PER_REFRESH 张法术。"刷新
    且馆内全为法术"需主线扩展刷新原语（含冻结保留/回池/tavern_refresh
    事件/Fodder 附加的一致语义，脚本层复制引擎刷新逻辑属违规近似）。
    """
    @staticmethod
    def on_play(source, game, ctx):
        return None


# ═════════════════════════ 注册 ═════════════════════════


def register() -> list[str]:
    """注册本批次脚本。DEFERRED 卡不注册（缺口审计盯）。"""
    from hsrl2.scripts.registry import register as reg

    registered: list[str] = []
    for card_id, script in (
        ("BG28_604", ButcheringScript),
        ("BG28_606", SpitescaleSpecialScript),
        ("BG28_607", CorruptedCupcakesScript),
        ("BG28_800", CarefulInvestmentScript),
        ("BG28_810", TavernCoinScript),
        ("BG28_825", DefendersRitesScript),
        ("BG28_827", LeafThroughThePagesScript),
        ("BG28_830", GoldenTouchScript),
        ("BG28_838", PerfectVisionScript),
        ("BG28_845", NaturalBlessingScript),
    ):
        reg(card_id, script)
        registered.append(card_id)
    # DEFERRED（不注册）:
    #   BG28_698 Gem Confiscation — 血宝石逐随从记账缺失
    #   BG28_805 Strike Oil — hero 级收入上限修正缺失
    #   BG28_849 Saloon's Finest — refresh_tavern spells_only 缺失
    return registered
