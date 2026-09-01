"""EoT 批次（作业单 2026-08-21，11 张 EoT 池随从 + 金色注册）。

EoT 钩子无死亡重入问题（本批全部效果为 buff/入手，不产生死亡波次），
正常返回 Action 列表入队（区别于 batch_deathrattle 的直调惯例）。
金色模型: EoT 钩子每回合触发**一次**（引擎 end_recruit_phase 逐随从
触发一次），金色差异由金色 CardDef.num() 或独立金色类承载。

数据核实（2026-08-21，CardDB 加载 data/ 逐卡打印）:
  BG26_152 Utility Drone      num=4/4（金 8/8）; 磁力吸附数 =
      game._magnetic_stack.get(uuid, []) 长度（game.attach_magnetic
      追加 card_id 的列表，RULES §6.14）
  BG28_595 Ignition Specialist "2 random"（金 "4"）文本字面量，无模板参数
  BG31_326 Gem Rat            → evolution_card_id 116596 → BG31_893
      Gem Day（card_type=5 SPELL、Choose One、非池卡 → 不占池）
  BG32_235 Surfing Sylvar     num(0)=1（金 2）; 文本 "@" 后第二段是
      "+{0}/+{1}" 变体但 num(1)=None 无法填充 → 生效段为首段
      （仅 Attack; 与 enUS 官方文本一致）
  BG32_821 Felfire Conjurer   num=1/1（金 2/2）→ hero TAVERN_SPELL_EXTRA_*
      叠加（tags.py 1053/1054; 消费点 racefx.tavern_spell_buff）
  BG32_837 Fauna Whisperer    → evolution_card_id 104472 → BG28_845
      Natural Blessing（池法术 num=3/3; "Choose a minion. Give all
      minions that share a type with it +{0}/+{1}"; 未注册脚本 → 按文本
      实现并注明）; buff 走 tavern_spell_buff 出口（它是酒馆法术，
      受 TAVERN_SPELL_EXTRA_* 增幅）
  BG34_145 Futurefin          "left-most minion in your hand" =
      hero.hand 顺序首个 Minion; stats = atk + max_health
      （SOP §3 属性快照）; 金色 "double" ×2（is_golden 判定）
  BG34_684 Trench Fighter     → evolution_card_id 110642 → BG28_698
      Gem Confiscation（is_pool_spell → acquire 占池）
  BG35_123 Cataclysmic Harbinger  "last Tavern spell you cast" 引擎无
      全局追踪 → on_summon 自注册 TAVERN_SPELL_CAST 监听器记
      hero._last_tavern_spell_id（动态属性先例: fought_ghost_last）;
      "a copy" 副本语义不占池（作业单约定）
  BG35_142 Cousin Errgl       → evolution_card_id 131145 → BG35_140
      Mama Mrrglton; Papa Mrrglton BG35_141 无数据链 → id 常量
      （36.2.2 bg_cards.json 按名核实）; 两者均 is_pool_minion →
      minion_pool.acquire 占池
  BG36_764 Gearfin            "1-Cost" = CardDef.cost == 1（文本字面量）;
      "two"（金 "four"）文本字面量

引擎缺口（报告主线）:
  - 全局 "last spell you cast" 追踪缺失 → 本批脚本层自维护
    hero._last_tavern_spell_id（见 CataclysmicHarbingerScript;
    Harbinger 入场前施放的法术不可见——官方是全局追踪）
  - SpellPool 每法术仅 1 份: Trench Fighter 金色 "get 2 Gem
    Confiscations" 第 2 枚按作业单"落空则无"语义落空（官方应给 2 枚）
"""

from __future__ import annotations

from hsrl2.actions import Buff
from hsrl2.actions.racefx import tavern_spell_buff
from hsrl2.events import Listener, TAVERN_SPELL_CAST
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race

# ── 关联卡 id（数据核实见模块 docstring）──
_PAPA_MRRGLTON = "BG35_141"      # Papa Mrrglton（无 evolution 数据链）
_GEARFIN_SPELL_COST = 1          # "1-Cost"（文本字面量，无模板参数）


def _def(game, source):
    d = game.db.get(source.card_id)
    if d is None:
        raise GameStateError(f"unknown card {source.card_id!r}")
    return d


def _evolution_target(game, source):
    """evolution_card_id 数据链解析关联卡（Shell Collector 先例，
    零硬编码卡 id）。金色定义同链（金色 CardDef 亦带 evolution_card_id）。"""
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


def _adjacent(source, game):
    """棋盘左右相邻随从（引擎 _update_positions 维护 ZONE_POSITION）。"""
    hero = source.controller
    idx = source.zone_position
    board = hero.board if hero is not None else []
    if source not in board or idx >= len(board):
        return []
    return [board[i] for i in (idx - 1, idx + 1) if 0 <= i < len(board)]


def _shares_type(m: Minion, t: Minion) -> bool:
    """Natural Blessing "share a type": 种族相同，或任一方为 ALL
    （Amalgam 全种族，RULES §6.4 匹配规则）; 无种族不与任何共享。"""
    for x in (m.race, t.race):
        if x in (Race.NONE, Race.INVALID):
            return False
    return m.race == t.race or m.race == Race.ALL or t.race == Race.ALL


def _gain_random_pool_spells(source, game, count, label, cost=None):
    """获取 count 张随机池法术（Ignition / Gearfin 共用）:
    每次从 is_pool_spell 且 spell_pool.available>0 的 card_id 中
    rng.choice → acquire（每法术池内仅 1 份 → 多次获取自动不同）→
    create_spell + pending_hand_add（满手排队 RULES §3.3）。
    池空/不足则拿到的数量少（官方落空语义，作业单约定）。"""
    hero = source.controller
    if hero is None:
        return None
    gained = 0
    while gained < count:
        cands = [d.id for d in game.db.pool_spells()
                 if game.spell_pool.available(d.id) > 0
                 and (cost is None or d.cost == cost)]
        if not cands:
            break
        pick = game.rng.choice(cands, label=label)
        if not game.spell_pool.acquire(pick):
            continue   # 防御: candidates 与 acquire 间状态变化时重选
        game.pending_hand_add(hero, game.create_spell(pick, controller=hero))
        gained += 1
    return None


# ══════════════════════════ BG26_152 Utility Drone ══════════════════════════

class UtilityDroneScript:
    """
    Natural language: [x]At the end of your turn, give your minions
    +{0}/+{1} for each Magnetization they have.

    Formal spec:
      1. EoT: 对 hero.board 每个随从 m，按其磁力吸附数
         n = len(game._magnetic_stack.get(m.uuid, []))（RULES §6.14
         attach_magnetic 追加 card_id 的栈）给
         Buff(m, atk=num(0)*n, health=num(1)*n); n=0 不给
      2. "your minions" 含自身（Utility Drone 是 MECH，自身可被磁力）
      3. 金色 +8/+8 由金色 CardDef.num() 自然体现

    Test: test_batch_eot_sot.py — 2 个磁力吸附的随从 +8/+8 /
    无吸附随从不变 / 金色 num=8 → +16/+16

    Params: {0}=4 {1}=4（金色 {0}=8 {1}=8）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _def(game, source)
        out = []
        for m in list(hero.board):
            n = len(game._magnetic_stack.get(m.uuid, []))
            if n > 0:
                out.append(Buff(m, atk=d.num(0) * n, health=d.num(1) * n))
        return out


# ═══════════════════════ BG28_595 Ignition Specialist ═══════════════════════

class IgnitionSpecialistScript:
    """
    Natural language: [x]At the end of your turn, get 2 random
    Tavern spells.

    Formal spec:
      1. EoT: 获取 2 张随机酒馆法术（全池、无 tier 限制——作业单语义）:
         每张 rng.choice(池内 is_pool_spell 且 available>0) →
         spell_pool.acquire（每法术 1 份 → 两张自动不同）→
         create_spell + pending_hand_add; 池空/仅剩 1 张则少拿（落空）
      2. 无实体 buff

    Test: test_batch_eot_sot.py — EoT 入手 2 张不同池法术且占池 /
    池排空后 0 张 / 金色 4 张

    Params: count=2（文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        return _gain_random_pool_spells(source, game, count=2,
                                        label="ignition_specialist")


class IgnitionSpecialistGoldenScript(IgnitionSpecialistScript):
    """
    Natural language: [x]At the end of your turn, get 4 random
    Tavern spells.

    Formal spec: 同基础类，计数 4。

    Test: 金色 EoT 入手 4 张（池充足时）。

    Params: count=4（金色文本字面量——金色 CardDef 无模板参数）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        return _gain_random_pool_spells(source, game, count=4,
                                        label="ignition_specialist_golden")


# ═══════════════════════════ BG31_326 Gem Rat ═══════════════════════════

class GemRatScript:
    """
    Natural language: At the end of your turn, get a Gem Day.

    Formal spec:
      1. EoT: Gem Day 经 evolution_card_id 数据链解析（116566→BG31_893，
         card_type=5 SPELL、Choose One 衍生法术、is_pool_spell=False）
      2. 非池卡 → 不占池，直接 create_spell + pending_hand_add
         （满手排队 RULES §3.3）; Choose One 结算由其自身脚本负责
         （未注册=缺口审计盯，非本批范围）

    Test: test_batch_eot_sot.py — EoT 入手 1 枚 Gem Day（数据链 id）/
    不占酒馆法术池 / 金色 2 枚

    Params: 无模板参数（卡 id 经 evolution_card_id 数据链解析; 计数
            1/2 为文本字面量）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        spell_id = _evolution_target(game, source).id
        game.pending_hand_add(hero, game.create_spell(spell_id,
                                                      controller=hero))
        return None


class GemRatGoldenScript(GemRatScript):
    """
    Natural language: At the end of your turn, get 2 Gem Days.

    Formal spec: 同基础类，计数 2（金色 CardDef 同 evolution 链）。

    Test: 金色 EoT 入手 2 枚 Gem Day。

    Params: count=2（金色文本字面量——金色 CardDef 无模板参数）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        spell_id = _evolution_target(game, source).id
        for _ in range(2):
            game.pending_hand_add(hero, game.create_spell(spell_id,
                                                          controller=hero))
        return None


# ═════════════════════════ BG32_235 Surfing Sylvar ═════════════════════════

class SurfingSylvarScript:
    """
    Natural language: [x]At the end of your turn, give adjacent minions
    +{0} Attack. Repeat for each friendly Golden minion.

    Formal spec:
      1. EoT: 左右相邻随从各获 +num(0) Attack; 应用次数 =
         1 + 棋盘金色随从数（含自身金色——"friendly Golden minion"）
      2. 文本 "@" 后 "+{0}/+{1}" 变体无 num(1) 参数可填 → 生效段为
         首段（仅 Attack，与官方 enUS 行为一致）
      3. 每相邻随从合计 Buff(atk=num(0) * 次数)

    Test: test_batch_eot_sot.py — 无金色时相邻各 +num(0) / 2 金色随从
    时 ×3 / 自身与远端随从不变 / 金色 num(0)=2

    Params: {0}=1（金色 {0}=2; 仅攻击分量）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _def(game, source)
        repeats = 1 + sum(1 for m in hero.board if m.is_golden)
        return [Buff(m, atk=d.num(0) * repeats)
                for m in _adjacent(source, game)]


# ════════════════════════ BG32_821 Felfire Conjurer ════════════════════════

class FelfireConjurerScript:
    """
    Natural language: [x]At the end of your turn, your Tavern spells give
    an extra +{0}/+{1} this game.

    Formal spec:
      1. EoT（每次触发都叠加——"At the end of your turn" 修饰词源，
         官方为每回合金币式累积）: hero.TAVERN_SPELL_EXTRA_ATK（1053）
         += num(0)、TAVERN_SPELL_EXTRA_HEALTH（1054）+= num(1)
      2. 消费点 racefx.tavern_spell_buff（酒馆法术 buff 统一出口，
         引擎已实现）; 本脚本只写 tag
      3. 金色 +2/+2 由金色 CardDef.num() 自然体现

    Test: test_batch_eot_sot.py — 单次 EoT tag 1/1 / 连续两次累积 2/2 /
    tavern_spell_buff 出口反映 / 金色 2/2

    Params: {0}=1 {1}=1（金色 {0}=2 {1}=2）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _def(game, source)
        hero.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) + d.num(0))
        hero.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0) + d.num(1))
        return None


# ════════════════════════ BG32_837 Fauna Whisperer ════════════════════════

class FaunaWhispererScript:
    """
    Natural language: [x]At the end of your turn, cast Natural Blessing
    on adjacent minions.

    Formal spec:
      1. EoT: 以每个左右相邻随从 T 为目标各施放一次 Natural Blessing
         （BG28_845，经 evolution_card_id 数据链解析，num=3/3;
         未注册脚本 → 按其文本实现: "Give all minions that share a
         type with it +{0}/+{1}"，共享判定 _shares_type: 同种族或
         任一方 Amalgam）
      2. 法术是酒馆法术 → buff 走 tavern_spell_buff 出口（受
         TAVERN_SPELL_EXTRA_* 增幅，与 Felfire Conjurer 联动）
      3. 目标域为施法者棋盘（BG 酒馆法术只影响己方）
      4. T 无种族（NONE）时该次施放落空（无随从与其共享类型）

    Test: test_batch_eot_sot.py — [兽, FW, 兽] 两兽各 +6/+6（两次施放
    × nb.num）/ FW 与不同族不变 / EXTRA_ATK=1 时每分量 +1 / 金色 twice

    Params: Natural Blessing {0}=3 {1}=3（经其 CardDef.num 取）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        return _cast_natural_blessing(source, game, times=1)

    @staticmethod
    def _nb_id(game, source):
        return _evolution_target(game, source).id


class FaunaWhispererGoldenScript(FaunaWhispererScript):
    """
    Natural language: [x]At the end of your turn, cast Natural Blessing
    on adjacent minions twice.

    Formal spec: 同基础类，每相邻随从施放 2 次。

    Test: 金色时两兽各 +12/+12（4 次施放 × nb.num）。

    Params: Natural Blessing {0}=3 {1}=3; 金色倍数=2（文本 "twice" 字面量）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        return _cast_natural_blessing(source, game, times=2)


def _cast_natural_blessing(source, game, times):
    hero = source.controller
    if hero is None:
        return None
    nb = _evolution_target(game, source)   # Natural Blessing CardDef
    atk, health = nb.num(0), nb.num(1)
    out = []
    for _ in range(times):
        for target in _adjacent(source, game):
            for m in list(hero.board):
                if _shares_type(m, target):
                    out.append(tavern_spell_buff(m, atk, health))
    return out


# ═══════════════════════════ BG34_145 Futurefin ═══════════════════════════

class FuturefinScript:
    """
    Natural language: [x]At the end of your turn, give this minion's
    stats to the left-most minion in your hand.

    Formal spec:
      1. EoT: 手牌最左随从 = hero.hand（左→右有序）中首个 Minion 实例
         （跳过更靠左的法术）; 无随从则落空
      2. stats = source.atk / source.max_health（SOP §3 属性快照用
         max_health 而非当前 health）→ Buff 等值给予
      3. 金色 "give double this minion's stats" → ×2（is_golden 判定，
         文本字面量倍数）
      4. 手牌 buff: Buff.do → add_buff（手牌实体合法，入场时按
         max_health 满血重算）

    Test: test_batch_eot_sot.py — 最左随从 +atk/+max_health、更左法术
    跳过 / 手牌无法术随从时落空 / 金色 ×2

    Params: 无模板参数（数值=source.atk/max_health 快照; 金色倍数=2
            为金色文本 "double" 字面量）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        target = next((c for c in hero.hand if isinstance(c, Minion)), None)
        if target is None:
            return None
        mult = 2 if source.is_golden else 1
        return [Buff(target, atk=source.atk * mult,
                     health=source.max_health * mult)]


# ═════════════════════════ BG34_684 Trench Fighter ═════════════════════════

class TrenchFighterScript:
    """
    Natural language: At the end of your turn, get a Gem Confiscation.

    Formal spec:
      1. EoT: Gem Confiscation 经 evolution_card_id 数据链解析
         （110642→BG28_698，is_pool_spell=True）→ spell_pool.acquire
         （占池）+ create_spell + pending_hand_add
      2. 池空（唯一副本被他人持有）→ 落空则无（作业单语义; 区别于
         Shell Collector 金币铸造先例）

    Test: test_batch_eot_sot.py — EoT 入手 1 枚且占池 / 池空落空 /
    金色 2 枚（第 2 枚池仅 1 份时落空——见报告）

    Params: count=1（文本字面量; 卡 id 经 evolution_card_id 数据链;
             金色版计数见子类声明）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        return _get_pool_spell_copies(source, game, count=1)


class TrenchFighterGoldenScript(TrenchFighterScript):
    """
    Natural language: At the end of your turn, get 2 Gem Confiscations.

    Formal spec: 同基础类，计数 2; 每枚独立 acquire，池仅 1 份时第 2
    枚落空（引擎缺口: SpellPool 单副本模型 vs 官方 "get 2 copies"，
    见模块 docstring / 作业返回）。

    Test: 金色 EoT 池充足时入手 2 枚。

    Params: count=2（金色文本字面量——金色 CardDef 无模板参数）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        return _get_pool_spell_copies(source, game, count=2)


def _get_pool_spell_copies(source, game, count):
    hero = source.controller
    if hero is None:
        return None
    spell_id = _evolution_target(game, source).id
    for _ in range(count):
        if not game.spell_pool.acquire(spell_id):
            break   # 池空落空则无（作业单语义）
        game.pending_hand_add(hero, game.create_spell(spell_id,
                                                      controller=hero))
    return None


# ═════════════════════ BG35_123 Cataclysmic Harbinger ═════════════════════

class CataclysmicHarbingerScript:
    """
    Natural language: [x]At the end of your turn, get a copy of the last
    Tavern spell you cast.

    Formal spec:
      1. on_summon: 注册 Listener(TAVERN_SPELL_CAST, owner=source)——
         每次己方施放酒馆法术（spell.controller is source.controller）
         记 hero._last_tavern_spell_id = spell.card_id（动态属性先例:
         fought_ghost_last; 随从离场自动注销）
      2. EoT: 若有记录 → create_spell(last_id) + pending_hand_add，
         **不 acquire**（"a copy" 副本语义不占池，作业单约定; 副本
         之后被施放时 spell_pool.release 为集合幂等操作，无池泄漏）;
         无记录（入场后未施放过）→ 落空
      3. 金色 "get 2 copies" → 2 份（is_golden 判定）

    Test: test_batch_eot_sot.py — 施放后 EoT 得副本且不占池 /
    未施放则无 / 监听器只记己方施放 / 金色 2 份

    Params: 无模板参数（卡 id 为运行时记录; 金色份数=2 为金色文本
            字面量）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def record(g, spell=None, **kw):
            if spell is not None and spell.controller is source.controller:
                source.controller._last_tavern_spell_id = spell.card_id
        game.events.register(Listener(
            event=TAVERN_SPELL_CAST, owner=source, callback=record))
        return None

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        last = getattr(hero, "_last_tavern_spell_id", None)
        if last is None or game.db.get(last) is None:
            return None
        copies = 2 if source.is_golden else 1
        for _ in range(copies):
            game.pending_hand_add(hero, game.create_spell(last,
                                                          controller=hero))
        return None


# ═════════════════════════ BG35_142 Cousin Errgl ═══════════════════════════

class CousinErrglScript:
    """
    Natural language: [x]At the end of your turn, get a Mama Mrrglton
    or a Papa Mrrglton.

    Formal spec:
      1. EoT: rng.choice([Mama, Papa])（Mama 经 evolution_card_id 数据链
         131145→BG35_140; Papa BG35_141 无数据链 → id 常量，模块
         docstring 数据核实）50/50 选一
      2. 两者均 is_pool_minion → minion_pool.acquire（占池）+
         create_minion + pending_hand_add; 池空落空则无
      3. "get" = 进手牌（SOP §3 动词表; 入手随从的三连检查在打出
         路径由引擎处理）

    Test: test_batch_eot_sot.py — EoT 入手 1 只 ∈ {Mama, Papa} 且该 id
    池减 1 / 两池排空后落空 / 金色两只全拿

    Params: 无模板参数（卡 id 经数据链/常量; 二选一无数值）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        mama = _evolution_target(game, source).id
        pick = game.rng.choice([mama, _PAPA_MRRGLTON],
                               label="cousin_errgl")
        return _acquire_minion_to_hand(source, game, pick)


class CousinErrglGoldenScript(CousinErrglScript):
    """
    Natural language: [x]At the end of your turn, get a Mama Mrrglton
    and a Papa Mrrglton.

    Formal spec: 同基础类，确定性各获取一只（金色文本 "and"——无随机）。

    Test: 金色 EoT 入手 Mama+Papa 各 1 且两池各减 1。

    Params: 无模板参数（金色确定性双获取）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        mama = _evolution_target(game, source).id
        out = []
        for cid in (mama, _PAPA_MRRGLTON):
            out.append(_acquire_minion_to_hand(source, game, cid))
        return None


def _acquire_minion_to_hand(source, game, card_id):
    hero = source.controller
    if not game.minion_pool.acquire(card_id):
        return None   # 池空落空则无
    game.pending_hand_add(hero, game.create_minion(card_id, controller=hero))
    return None


# ═══════════════════════════ BG36_764 Gearfin ═══════════════════════════

class GearfinScript:
    """
    Natural language: At the end of your turn, get two 1-Cost Tavern spells.

    Formal spec:
      1. EoT: 获取 2 张随机 1 费酒馆法术（CardDef.cost == 1，文本
         字面量 "1-Cost"）: 池内 available>0 的 cost==1 池法术中
         rng.choice → acquire（每法术 1 份 → 两张自动不同）→
         create_spell + pending_hand_add; 池空/不足则少拿（落空）
      2. 无 tier 限制（作业单语义; cost 过滤独立于 tech_level）

    Test: test_batch_eot_sot.py — EoT 入手 2 张不同 cost==1 池法术 /
    1 费法术排空后 0 张（其余法术仍在池） / 金色 4 张

    Params: count=2（文本字面量——CardDef 无模板参数; 费用 1 见
            _GEARFIN_SPELL_COST）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        return _gain_random_pool_spells(source, game, count=2,
                                        label="gearfin",
                                        cost=_GEARFIN_SPELL_COST)


class GearfinGoldenScript(GearfinScript):
    """
    Natural language: At the end of your turn, get four 1-Cost Tavern spells.

    Formal spec: 同基础类，计数 4。

    Test: 金色 EoT 入手 4 张（池充足时）。

    Params: count=4（金色文本字面量——金色 CardDef 无模板参数;
             费用 1 同基础类 _GEARFIN_SPELL_COST）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        return _gain_random_pool_spells(source, game, count=4,
                                        label="gearfin_golden",
                                        cost=_GEARFIN_SPELL_COST)


def register() -> list[str]:
    """注册本批次脚本（含金色 id）。本批 11/11 OK，无 DEFERRED/AMBIGUOUS。"""
    from hsrl2.scripts.registry import register as reg

    registered: list[str] = []
    for card_id, script in (
        ("BG26_152", UtilityDroneScript),
        ("BG26_152_G", UtilityDroneScript),          # num 8/8 自然体现
        ("BG28_595", IgnitionSpecialistScript),
        ("BG28_595_G", IgnitionSpecialistGoldenScript),   # 4 random
        ("BG31_326", GemRatScript),
        ("BG31_326_G", GemRatGoldenScript),          # 2 Gem Days
        ("BG32_235", SurfingSylvarScript),
        ("BG32_235_G", SurfingSylvarScript),         # num(0)=2 自然体现
        ("BG32_821", FelfireConjurerScript),
        ("BG32_821_G", FelfireConjurerScript),       # num 2/2 自然体现
        ("BG32_837", FaunaWhispererScript),
        ("BG32_837_G", FaunaWhispererGoldenScript),  # cast twice
        ("BG34_145", FuturefinScript),
        ("BG34_145_G", FuturefinScript),             # double via is_golden
        ("BG34_684", TrenchFighterScript),
        ("BG34_684_G", TrenchFighterGoldenScript),   # 2 Gem Confiscations
        ("BG35_123", CataclysmicHarbingerScript),
        ("BG35_123_G", CataclysmicHarbingerScript),  # 2 copies via is_golden
        ("BG35_142", CousinErrglScript),
        ("BG35_142_G", CousinErrglGoldenScript),     # Mama and Papa
        ("BG36_764", GearfinScript),
        ("BG36_764_G", GearfinGoldenScript),         # four 1-Cost
    ):
        reg(card_id, script)
        registered.append(card_id)
    return registered
