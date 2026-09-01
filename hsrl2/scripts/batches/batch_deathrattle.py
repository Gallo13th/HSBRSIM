"""死亡语批次（作业单 2026-08-21，19 张池随从 + 金色注册）。

实现状态: 19/19 OK，无 DEFERRED / AMBIGUOUS 卡。

token id 数据核实（2026-08-21，bg_cards.json 按名搜索）:
  BG25_008  Eternal Knight（池卡；战斗召唤不占池——Summon 语义）
  BG25_008_G 金色 Eternal Knight（金色 DR 文本 "a Golden Eternal Knight"）
  BG25_010t Helping Hand 2/1 Reborn（金色文本 "two 2/1 Hands" = 基础 token ×2，
            非金色 token BG25_010_Gt 4/2）
  BG_ICC_026t Skeleton 1/1 / _G 2/2
  BG_BOT_312t Microbot 1/1 / 金色链 → TB_BaconUps_032t 2/2
  BG28_603t Beetle 2/2 BEAST（Beetle 系卡自带 {0}/{1} 参数覆盖属性）
  BG28_888 Misplaced Tea Set（is_pool_spell——获取走 spell_pool.acquire）
  EBG_Spell_014 Pointy Arrow（非池法术——直接 create）

金色战吼模型（与 minions.py 批次 1 约定一致，引擎 play_minion 对金色
触发 2 次）: battlecry 钩子实现"每次触发的基础值"（金色实体经
triple_base_id 解析回基础 CardDef 取 num），非 battlecry 钩子
（deathrattle 单次触发）直接实现金色文本总额。

⚠ 引擎约束（本批次实测发现，已报告主线——见作业返回的引擎缺口清单）:
  game._process_single_death 在亡语钩子**之后**才把濒死随从移出棋盘，
  而 ActionQueue.resolve 每动作后调用 check_deaths → 亡语钩子返回的
  Action 会触发重入收集，濒死随从被**二次处理**（双亡语/双墓地/双回池）。
  因此本批次全部 deathrattle 钩子采用引擎既有死亡语惯例（Golemancy /
  Locked-up Mutineer / Mystic Essence 先例）: 直接调用 Action.do(game)
  或等价状态变更、返回 None; 死亡波次由外层 check_deaths 驱动。
  battlecry 钩子无此约束（正常返回 Action 入队）。

位置语义: 亡语钩子在移除之前执行（引擎 C6 "亡语先"）→
source.zone_position 仍有效，token 召唤于宿主原位（多个 token 从
宿主位起右移连续插入; 复生随从被挤到右侧原地复活）。
"""

from __future__ import annotations

from hsrl2.actions import Buff, GainKeyword
from hsrl2.actions.discover import _pool_candidates   # 池过滤唯一权威（Amalgam/active_races 一致）
from hsrl2.actions.racefx import ApplyRaceAura
from hsrl2.actions.tavern_buff import ApplyTavernBuff, BuffCurrentTavern, TavernBuff
from hsrl2.game import GameStateError
from hsrl2.queue import Action
from hsrl2.tags import GameTag, Race, Zone

# ── token / 关联卡 id（数据核实见模块 docstring）──
_TOKEN_ETERNAL_KNIGHT = "BG25_008"
_TOKEN_HELPING_HAND = "BG25_010t"
_TOKEN_SKELETON = "BG_ICC_026t"
_TOKEN_MICROBOT = "BG_BOT_312t"
_TOKEN_BEETLE = "BG28_603t"
_SPELL_TEA_SET = "BG28_888"
_SPELL_POINTY_ARROW = "EBG_Spell_014"

# 全部真实种族（Motley Phalanx "of each type" 迭代域; ALL/NONE 非类型）
_ALL_MINION_RACES = tuple(
    r for r in Race if r not in (Race.INVALID, Race.NONE, Race.ALL)
)


def _per_trigger_def(game, source):
    """金色战吼"每次触发值"解析: 金色实体回基础 CardDef（引擎触发 2 次
    → 总额 = 2×基础值 = 金色文本总额）; 基础实体返回自身定义。"""
    d = game.db.get(source.card_id)
    if d is not None and d.is_golden_def and d.triple_base_id is not None:
        base = game.db.by_dbf(d.triple_base_id)
        if base is not None:
            return base
    return d


def _summon_token_run(source, game, card_id, count, golden=False):
    """在宿主亡语位置连续召唤 count 个 token（宿主位 + 0..count-1）。

    亡语钩子执行时宿主仍在棋盘（引擎 C6 "亡语先"），zone_position 有效;
    宿主随后被移除，token 恰好填入死者原位（官方死亡召唤位置规则）。
    满场由 game.summon 处理（minion_overflow 后丢弃该 token）。
    """
    hero = source.controller
    if hero is None:
        return []
    base = source.zone_position
    out = []
    for i in range(count):
        m = game.create_minion(card_id, controller=hero, golden=golden)
        game.summon(hero, m, base + i)
        out.append(m)
    return out


def _summon_beetles_now(source, game, atk, health, count):
    """Beetle 系亡语召唤: token + 属性覆盖为召唤卡 num(0)/num(1)，
    直接执行（死亡语直调惯例，见模块 docstring）。"""
    hero = source.controller
    if hero is None:
        return
    base = source.zone_position
    for i in range(count):
        SummonTokenSetStats(hero, _TOKEN_BEETLE, atk, health,
                            position=base + i).do(game)


def _tavern_buff_actions(hero, atk, health, race_filter, source_id):
    """"Give <X> in the Tavern +a/+h this game": 持久登记（refresh 自动
    应用新入馆随从，game.refresh_tavern 已接线）+ 立即应用于当前馆。
    （battlecry 路径: 返回 Action 入队）"""
    tb = TavernBuff(atk=atk, health=health, race_filter=race_filter,
                    source_id=source_id)
    return [ApplyTavernBuff(hero, tb), BuffCurrentTavern(hero, tb)]


def _apply_tavern_buff_now(game, hero, atk, health, race_filter, source_id):
    """同 _tavern_buff_actions，但直接执行（死亡语直调惯例）。"""
    tb = TavernBuff(atk=atk, health=health, race_filter=race_filter,
                    source_id=source_id)
    ApplyTavernBuff(hero, tb).do(game)
    BuffCurrentTavern(hero, tb).do(game)


# ══════════════════ 批次内 Action（queue.Action 子类，主线评审候选上移） ══════════════════


class SummonTokenSetStats(Action):
    """召唤 token 并覆盖式设定属性（"Set its stats to {0}/{1}" 家族 /
    Beetle "{0}/{1} Beetle"——Beetle 基础 token 2/2，属性以召唤卡参数为权威）。"""

    def __init__(self, hero, card_id: str, atk: int, health: int,
                 position=None) -> None:
        self.hero = hero
        self.card_id = card_id
        self.atk = atk
        self.health = health
        self.position = position

    def do(self, game) -> None:
        m = game.create_minion(self.card_id, controller=self.hero)
        m.set(GameTag.BASE_ATK, self.atk)
        m.set(GameTag.BASE_HEALTH, self.health)
        m.set(GameTag.HEALTH, self.health)
        game.summon(self.hero, m, self.position)


class SummonRandomBeastSetStats(Action):
    """Sly Raptor: 池内随机 Beast（含 ALL，Amalgam 规则）+ acquire 占池
    （作业单裁定: "Summon a random Beast" 的候选/占池语义）+ 覆盖属性 +
    召唤至亡语宿主位。无候选 → 落空（真实池空行为）。"""

    def __init__(self, hero, atk: int, health: int, position=None) -> None:
        self.hero = hero
        self.atk = atk
        self.health = health
        self.position = position

    def do(self, game) -> None:
        cands = _pool_candidates(game, race=Race.BEAST)
        if not cands:
            return
        cid = game.rng.choice(cands, label="sly_raptor_beast")
        if not game.minion_pool.acquire(cid):
            raise GameStateError(
                f"Sly Raptor: pool acquire failed for {cid}")
        m = game.create_minion(cid, controller=self.hero)
        m.set(GameTag.BASE_ATK, self.atk)
        m.set(GameTag.BASE_HEALTH, self.health)
        m.set(GameTag.HEALTH, self.health)
        game.summon(self.hero, m, self.position)


class GetRandomMagneticMechs(Action):
    """Scrap Scraper: 从池获取 count 个随机 Magnetic Mech 进手牌
    （keywords 含 magnetic + MECH/ALL 种族过滤; acquire 占池;
    pending_hand_add 满手排队）。无候选 → 落空。同 id 可重复命中
    （池内多副本，官方 "Get 2 random" 语义）。"""

    def __init__(self, hero, count: int) -> None:
        self.hero = hero
        self.count = count

    def do(self, game) -> None:
        pool = game.minion_pool
        cands = []
        for d in game.db.pool_minions():
            if "magnetic" not in d.keywords:
                continue
            if d.race not in (Race.MECH, Race.ALL):
                continue
            if pool.available(d.id) <= 0:
                continue
            if (pool.active_races is not None
                    and d.race not in (Race.NONE, Race.ALL)
                    and d.race not in pool.active_races):
                continue
            cands.append(d.id)
        for _ in range(self.count):
            if not cands:
                return
            cid = game.rng.choice(cands, label="scrap_scraper_mech")
            if not pool.acquire(cid):
                raise GameStateError(
                    f"Scrap Scraper: pool acquire failed for {cid}")
            game.pending_hand_add(
                self.hero, game.create_minion(cid, controller=self.hero))


class GetSpellCard(Action):
    """Get <spell>（Misplaced Tea Set / Pointy Arrow）获取路径（作业单裁定）:
    is_pool_spell 且 spell_pool.available>0 → acquire 占池; 否则直接 create
    （池无副本时仍生成——茶会/箭不因池耗尽落空）。满手 pending_hand_add。"""

    def __init__(self, hero, card_id: str) -> None:
        self.hero = hero
        self.card_id = card_id

    def do(self, game) -> None:
        d = game.db.get(self.card_id)
        if (d is not None and d.is_pool_spell
                and game.spell_pool.available(self.card_id) > 0):
            if not game.spell_pool.acquire(self.card_id):
                raise GameStateError(
                    f"GetSpellCard: spell pool acquire failed for "
                    f"{self.card_id}")
        game.pending_hand_add(
            self.hero, game.create_spell(self.card_id, controller=self.hero))


# ══════════════════ BG23_318 Leeroy the Reckless ══════════════════


class LeeroyTheRecklessScript:
    """
    Natural language: <b>Deathrattle:</b> Destroy the minion that killed this.

    Formal spec:
      1. 死亡时（deathrattle，直调模式）: 读 source 的 GameTag.KILLER
         （Minion.take_damage 结算实际伤害>0 时写入，含攻击/顺劈/招募期
         攻击路径）。KILLER 为 None（无来源伤害，如 EoT 自残）→ 无效果
      2. 击杀者已死亡或已离场（zone != PLAY，含同波次先结算的同时死亡者）
         → 无效果（官方: 目标不存在时消灭落空）
      3. 否则 Destroy: killer.health = 0（setter 同步置 DEAD）——非伤害
         实例，无视圣盾（官方: 消灭效果不经伤害结算）; 击杀者的死亡链
         （亡语/复生）由外层 check_deaths 后续波次驱动（引擎波次模型）
      4. 金色版文本同文（仅属性差异）→ 同一脚本类复用

    Test: test_batch_deathrattle.py — 击杀者被消灭且其死亡正常结算 /
    无 KILLER 无效果 / 圣盾不抵挡 Destroy / 已死亡的击杀者不再触发 /
    金色同效

    Params: 无模板参数（文本无占位符）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        killer = source.get(GameTag.KILLER, None)
        if killer is None:
            return None
        if getattr(killer, "dead", True) or killer.zone != Zone.PLAY:
            return None
        killer.health = 0   # Destroy 语义（无视圣盾）; 外层波次处理其死亡链
        return None


# ══════════════════ BG25_009 Eternal Summoner ══════════════════


class EternalSummonerScript:
    """
    Natural language: [x]<b><b>Reborn</b>.</b> <b>Deathrattle:</b>
    Summon 1 Eternal Knight.

    Formal spec:
      1. 死亡时: 在宿主原位召唤 1 个 Eternal Knight（BG25_008，池卡但为
         战斗召唤——create_minion 不占池，Summon 语义与官方一致）
      2. Reborn 关键词由 CardDef→引擎映射，脚本不处理; 亡语先于复生
         （引擎 C6）: 骑士插入宿主位，复生的 Summoner 右移原地复活
      3. token 属性 = BG25_008 CardDef（4/2 Undead T2）

    Test: 宿主位出现 BG25_008（属性=def）/ 复生后 [A, Knight, 宿主, B] /
    金色召唤金色骑士 BG25_008_G（8/4）

    Params: 无模板参数（"1" 为文本字面量; 骑士属性来自 token CardDef）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        _summon_token_run(source, game, _TOKEN_ETERNAL_KNIGHT, 1)
        return None


class EternalSummonerGoldenScript:
    """
    Natural language: [x]<b>Reborn</b>. <b>Deathrattle:</b> Summon a Golden
    Eternal Knight.

    Formal spec:
      1. 同基础版，但召唤**金色** Eternal Knight（金色文本行为差异）:
         create_minion(BG25_008, golden=True) → 金色卡定义 BG25_008_G
         （8/4），非数值×2 近似

    Test: 金色召唤物 card_id == BG25_008_G 且 GOLDEN tag、属性 8/4

    Params: 无模板参数（金色骑士属性来自金色 CardDef BG25_008_G）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        _summon_token_run(source, game, _TOKEN_ETERNAL_KNIGHT, 1, golden=True)
        return None


# ══════════════════ BG25_010 Handless Forsaken ══════════════════


class HandlessForsakenScript:
    """
    Natural language: <b>Deathrattle:</b> Summon a 2/1 Hand with <b>Reborn</b>.

    Formal spec:
      1. 死亡时: 宿主原位召唤 Helping Hand token（BG25_010t，2/1 Undead
         Reborn——属性来自 token CardDef，无硬编码）
      2. REBORN tag 自举（DATA 缺口）: BG25_010t 文本 "<b>Reborn</b>"
         但数据导出缺 reborn 关键词标志（generate_bg_data 未导出该
         token 的 tag1085），召唤点显式置 tag（Spellcraft tag 自举
         同款先例，批次 1）
      3. 金色文本 "Summon two 2/1 Hands with Reborn" = 基础 token ×2
         （金色 token BG25_010_Gt 为 4/2，与金色文本 "2/1" 不符——
         金色召唤的是两个普通手，数据核实 2026-08-21）

    Test: 宿主位出现 BG25_010t（2/1 + REBORN tag）/ 金色出现两个

    Params: 无模板参数（token 属性来自 CardDef; 数量为文本字面量 1/2）
    """

    hand_count = 1   # 文本字面量 "a"

    @staticmethod
    def deathrattle(source, game, ctx):
        hands = _summon_token_run(source, game, _TOKEN_HELPING_HAND,
                                  source.scripts.hand_count)
        for h in hands:
            h.set(GameTag.REBORN, True)   # DATA 缺口自举（见 spec 2）
        return None


class HandlessForsakenGoldenScript(HandlessForsakenScript):
    """
    Natural language: <b>Deathrattle:</b> Summon two 2/1 Hands with
    <b>Reborn</b>.

    Formal spec:
      1. 同基础版，hand_count=2——两个**基础** BG25_010t（2/1 Reborn，
         金色文本原文 "two 2/1 Hands"），连续插入宿主位右侧

    Test: 金色亡语出 2 个 BG25_010t（均 2/1 + REBORN）

    Params: 无模板参数（token 属性来自 CardDef; 数量为文本字面量 2）
    """

    hand_count = 2   # 金色文本字面量 "two"


# ══════════════════ BG25_022 Scarlet Skull ══════════════════


class ScarletSkullScript:
    """
    Natural language: <b>Reborn</b>
    <b>Deathrattle:</b> Give a friendly Undead +1/+2.

    Formal spec:
      1. 死亡时（直调模式）: 从控制者棋盘存活随从中随机选一个 Undead
         （含 ALL 种族，Amalgam 规则; source 已死自然排除），给它
         +atk_bonus/+health_bonus 永久 Buff（Buff.do 直调）
      2. 无 "Choose"/无 [Targeted]（经验库判别法）→ 随机选取
      3. 无候选（无其他存活 Undead）→ 落空
      4. Reborn 关键词由引擎处理（首次死亡触发亡语后复生，二次死亡再触发）

    Test: 两个候选之一获得 +1/+2（合计增量断言）/ 无候选落空 / 金色 +2/+4

    Params: 文本字面量 {0}=1 {1}=2（CardDef 无模板参数，文本原文数值）
    """

    atk_bonus = 1    # 文本字面量
    health_bonus = 2  # 文本字面量

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cands = [m for m in hero.board
                 if not m.dead and m.race in (Race.UNDEAD, Race.ALL)]
        if not cands:
            return None
        pick = game.rng.choice(cands, label="scarlet_skull_target")
        cls = source.scripts
        Buff(pick, atk=cls.atk_bonus, health=cls.health_bonus).do(game)
        return None


class ScarletSkullGoldenScript(ScarletSkullScript):
    """
    Natural language: <b>Reborn</b>
    <b>Deathrattle:</b> Give a friendly Undead +2/+4.

    Formal spec:
      1. 同基础版，数值为金色文本字面量 +2/+4（金色 CardDef 无模板参数）

    Test: 金色亡语候选获得 +2/+4

    Params: 文本字面量 {0}=2 {1}=4（金色 CardDef 文本原文数值）
    """

    atk_bonus = 2    # 金色文本字面量
    health_bonus = 4  # 金色文本字面量


# ══════════════════ BG25_806 Sly Raptor ══════════════════


class SlyRaptorScript:
    """
    Natural language: <b>Deathrattle:</b> Summon a random Beast. Set its
    stats to {0}/{1}.

    Formal spec:
      1. 死亡时（直调模式）: 候选 = 池内 Beast（race=BEAST 含 ALL，池
         剩余量与 active_races 过滤，_pool_candidates 权威）; 无候选 →
         落空
      2. 选中 card_id: minion_pool.acquire 占池（作业单裁定）→
         create_minion → **覆盖式**设 BASE_ATK/BASE_HEALTH/HEALTH 为
         num(0)/num(1)（"Set its stats" 覆盖原值，非 buff 叠加）
      3. 召唤至亡语宿主原位
      4. 金色版文本同文仅数值差异（金色 num 12/12）→ 同一脚本类复用

    Test: 召唤物种族 ∈ (BEAST, ALL) 且 BASE_ATK/HEALTH == num(0)/num(1)、
    池对应 id 减 1 / 无候选落空 / 金色 12/12

    Params: {0}=6 {1}=6（36.2.2 基线，金色 12/12）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        SummonRandomBeastSetStats(
            hero, d.num(0), d.num(1),
            position=source.zone_position).do(game)
        return None


# ══════════════════ BG26_148 Scrap Scraper ══════════════════


class ScrapScraperScript:
    """
    Natural language: <b>Deathrattle:</b> Get a random <b>Magnetic</b> Mech.

    Formal spec:
      1. 死亡时（直调模式）: 候选 = 池内 keywords 含 magnetic 的 MECH/ALL
         随从（池剩余量 + active_races 过滤）; 无候选 → 落空（真实池空
         行为）
      2. Get = 进手牌: 随机选 id → minion_pool.acquire 占池 →
         create_minion → pending_hand_add（满手排队，RULES §3.3）
      3. 基础文本 "a" = 1 个（字面量; 基础 CardDef num(0)=2 与文本 "a"
         冲突，以文本为权威——金色文本 "2" 与金色 num(0)=2 一致）

    Test: 手牌出现 1 个 magnetic Mech 且池对应 id 减 1 / 无候选手牌不变 /
    金色 2 个

    Params: 基础数量 = 文本字面量 1（"a"，无占位符）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        GetRandomMagneticMechs(hero, 1).do(game)
        return None


class ScrapScraperGoldenScript(ScrapScraperScript):
    """
    Natural language: <b>Deathrattle:</b> Get 2 random <b>Magnetic</b> Mechs.

    Formal spec:
      1. 同基础版，数量 = 金色 CardDef num(0) = 2（与金色文本 "2" 一致）
      2. 两次独立随机选取（同 id 可重复——池内多副本）

    Test: 金色亡语手牌出现 2 个 magnetic Mech

    Params: {0}=2（金色 CardDef，与金色文本一致）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        GetRandomMagneticMechs(hero, d.num(0)).do(game)
        return None


# ══════════════════ BG26_162 Dancing Barnstormer ══════════════════


class DancingBarnstormerScript:
    """
    Natural language: [x]<b>Battlecry and Deathrattle:</b>
    Give Elementals in the Tavern +{0}/+{1} this game.

    Formal spec:
      1. BC（每次触发，Action 入队）与 DR（单次触发，直调模式）: 对当前
         酒馆全部 Elemental（含 ALL 种族）立即 +num(0)/num(1) 永久 Buff
         （BuffCurrentTavern，购买后随实体带走），并登记持久酒馆 Buff
         （ApplyTavernBuff → hero.tavern_buffs，refresh_tavern 新入馆
         元素自动应用——引擎已接线）
      2. "in the Tavern" 仅指当前馆内随从（hero.tavern），不含棋盘/手牌
      3. BC 金色引擎触发 2 次，每次触发按**基础** CardDef num（8/8）→
         金色打出总额 16/16 = 金色文本 "+8/+8 twice"; DR 单次触发由
         金色注册类实现 twice
      4. 基础 DR 按 num(0)/num(1) 应用 1 次

    Test: 馆内元素 +8/+8、机械不变、tavern_buffs 登记 1 条 / DR 同效 /
    金色 BC（play 路径）16/16 与 2 条登记 / 金色 DR 16/16

    Params: {0}=8 {1}=8（36.2.2 基线，金色同值 ×2 次）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _per_trigger_def(game, source)
        return _tavern_buff_actions(hero, d.num(0), d.num(1),
                                    Race.ELEMENTAL, source.card_id)

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        _apply_tavern_buff_now(game, hero, d.num(0), d.num(1),
                               Race.ELEMENTAL, source.card_id)
        return None


class DancingBarnstormerGoldenScript(DancingBarnstormerScript):
    """
    Natural language: [x]<b>Battlecry and Deathrattle:</b>
    Give Elementals in the Tavern +{0}/+{1} this game twice.

    Formal spec:
      1. BC: 继承基础版（每次触发按基础 CardDef 8/8，引擎金色触发 2 次
         → 总额 16/16）
      2. DR: 单次触发，按金色文本 "twice" 应用 **2 次** 8/8（当前馆
         +16/+16，tavern_buffs 登记 2 条 → 新入馆元素共 +16/+16）

    Test: 金色 DR 馆内元素 +16/+16、2 条持久登记

    Params: {0}=8 {1}=8（金色 CardDef）×2 次（"twice"）
    """

    times = 2   # 金色文本 "twice"

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        for _ in range(DancingBarnstormerGoldenScript.times):
            _apply_tavern_buff_now(game, hero, d.num(0), d.num(1),
                                   Race.ELEMENTAL, source.card_id)
        return None


# ══════════════════ BG27_016 Champion of Sargeras ══════════════════


class ChampionOfSargerasScript:
    """
    Natural language: [x]<b>Battlecry and Deathrattle:</b>
    Give minions in the Tavern +{0}/+{1} this game.

    Formal spec:
      1. 同 Dancing Barnstormer 模式，但无种族过滤（馆内全部随从）:
         BC（Action 入队）/ DR（直调模式）→ BuffCurrentTavern（立即）+
         ApplyTavernBuff（持久）
      2. BC 金色引擎触发 2 次、每次按基础 CardDef num（8/8）→ 金色打出
         总额 16/16 = 金色文本 {0}/{1}=16/16
      3. DR 单次触发按本卡 CardDef num → 基础 8/8 / 金色 16/16（金色
         文本同文仅数值差异）→ 同一脚本类复用

    Test: 馆内全部随从（元素+机械）+8/+8 / DR 同效 / 金色 BC 16/16（2 条
    登记）/ 金色 DR 16/16（1 条 16/16 登记）

    Params: {0}=8 {1}=8（36.2.2 基线，金色 16/16 经金色 CardDef 体现）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _per_trigger_def(game, source)
        return _tavern_buff_actions(hero, d.num(0), d.num(1),
                                    None, source.card_id)

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        _apply_tavern_buff_now(game, hero, d.num(0), d.num(1),
                               None, source.card_id)
        return None


# ══════════════════ BG27_080 Motley Phalanx ══════════════════


class MotleyPhalanxScript:
    """
    Natural language: [x]<b>Taunt</b>
    <b>Deathrattle:</b> Give a friendly minion
    of each type __+{0}/+{1} permanently.

    Formal spec:
      1. 死亡时（直调模式）: 对每个真实种族（UNDEAD/MURLOC/DEMON/MECH/
         ELEMENTAL/BEAST/PIRATE/DRAGON/QUILBOAR/NAGA，共 10 类——
         ALL/NONE 非类型）: 候选 = 棋盘存活友方该种族随从（含 ALL 种族
         ——Amalgam 是每个类型的随从，单一 Amalgam 时每个类型都命中它，
         官方已知交互）
      2. 每类型独立随机选 1 个 → +num(0)/num(1) 永久 Buff（Buff.do 直调;
         同一随从可被多个类型分别命中，各得一份）
      3. 某类型无候选 → 该类型跳过; source 已死自然排除
      4. Taunt 由 CardDef→引擎映射; 金色文本同构仅数值差异（6/6）→
         同一脚本类复用

    Test: Beast+Demon+Amalgam 场景全棋盘合计 +10×num(0)/+10×num(1) 且
    Amalgam 至少得 9 份 / 无友方随从落空 / 金色合计 +60/+60

    Params: {0}=3 {1}=3（36.2.2 基线，金色 6/6）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        for race in _ALL_MINION_RACES:
            cands = [m for m in hero.board
                     if m is not source and not m.dead
                     and (m.race == race or m.race == Race.ALL)]
            if not cands:
                continue
            pick = game.rng.choice(cands, label="motley_phalanx_target")
            Buff(pick, atk=d.num(0), health=d.num(1)).do(game)
        return None


# ══════════════════ BG28_300 Harmless Bonehead ══════════════════


class HarmlessBoneheadScript:
    """
    Natural language: <b>Deathrattle:</b> Summon
    two 1/1 Skeletons.

    Formal spec:
      1. 死亡时: 宿主原位连续召唤 skeleton_count 个 Skeleton token
         （BG_ICC_026t，1/1 Undead——属性来自 token CardDef）
      2. 金色文本 "four" → 4 个（金色注册类）

    Test: [A, 宿主, B] → [A, S, S, B]（位置与数量）/ token 1/1 /
    金色 4 个

    Params: 无模板参数（token 属性来自 CardDef; 数量为文本字面量 2/4）
    """

    skeleton_count = 2   # 文本字面量 "two"

    @staticmethod
    def deathrattle(source, game, ctx):
        _summon_token_run(source, game, _TOKEN_SKELETON,
                          source.scripts.skeleton_count)
        return None


class HarmlessBoneheadGoldenScript(HarmlessBoneheadScript):
    """
    Natural language: <b>Deathrattle:</b> Summon
    four 1/1 Skeletons.

    Formal spec:
      1. 同基础版，skeleton_count=4（金色文本 "four"）

    Test: 金色亡语出 4 个 BG_ICC_026t（1/1）

    Params: 无模板参数（token 属性来自 CardDef; 数量为金色文本字面量 4）
    """

    skeleton_count = 4   # 金色文本字面量 "four"


# ══════════════════ BG28_309 Mummifier ══════════════════


class MummifierScript:
    """
    Natural language: <b>Deathrattle:</b> Give a different friendly Undead
    <b>Reborn</b>.

    Formal spec:
      1. 死亡时（直调模式）: 候选 = 棋盘存活友方 Undead（含 ALL 种族），
         排除 source 自身（"different"，已死自然排除）
      2. 随机选 target_count 个（金色 2 个，**互不相同**——rng.sample
         无放回; 候选不足时全给，官方 "尽可能执行"）
      3. 每个选中者 GainKeyword(REBORN).do（含 keyword_gained 广播）;
         无候选 → 落空

    Test: 恰 1 个 Undead 获得 REBORN、机械不受影响 / 无候选落空 /
    金色恰 2 个互不相同

    Params: 无模板参数（数量为文本字面量 1/2）
    """

    target_count = 1   # 文本字面量 "a"

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cands = [m for m in hero.board
                 if m is not source and not m.dead
                 and m.race in (Race.UNDEAD, Race.ALL)]
        if not cands:
            return None
        k = min(source.scripts.target_count, len(cands))
        picks = game.rng.sample(cands, k, label="mummifier_targets")
        for p in picks:
            GainKeyword(p, GameTag.REBORN).do(game)
        return None


class MummifierGoldenScript(MummifierScript):
    """
    Natural language: <b>Deathrattle:</b> Give 2 different friendly Undead
    <b>Reborn</b>.

    Formal spec:
      1. 同基础版，target_count=2——rng.sample 无放回抽 2 个**互不相同**
         的友方 Undead（金色文本 "2 different"）; 候选仅 1 个时只给 1 个

    Test: 金色亡语恰 2 个不同 Undead 获得 REBORN

    Params: 无模板参数（数量为金色文本字面量 2）
    """

    target_count = 2   # 金色文本字面量 "2"


# ══════════════════ BG29_611 Cord Puller ══════════════════


class CordPullerScript:
    """
    Natural language: [x]<b>Divine Shield</b>
    <b>Deathrattle:</b> Summon a
    1/1 Microbot.

    Formal spec:
      1. 死亡时: 宿主原位召唤 1 个 Microbot token（BG_BOT_312t，1/1
         Mech——属性来自 token CardDef）
      2. Divine Shield 关键词由 CardDef→引擎映射（本卡 def keywords
         已含 divine_shield），脚本不处理
      3. 金色文本 "Summon a 2/2 Microbot" → 金色 Microbot 独立卡定义
         TB_BaconUps_032t（db.golden_version(BG_BOT_312t) 数据链）

    Test: 宿主位出现 BG_BOT_312t（1/1 MECH）/ DS tag 在场 / 金色出
    TB_BaconUps_032t（2/2）

    Params: 无模板参数（token 属性来自 CardDef）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        _summon_token_run(source, game, _TOKEN_MICROBOT, 1)
        return None


class CordPullerGoldenScript(CordPullerScript):
    """
    Natural language: [x]<b>Divine Shield</b>
    <b>Deathrattle:</b> Summon a
    2/2 Microbot.

    Formal spec:
      1. 同基础版，但经 golden=True 解析金色 Microbot 卡定义
         （TB_BaconUps_032t，2/2）——金色=独立卡定义，非数值近似

    Test: 金色亡语出 TB_BaconUps_032t（2/2）

    Params: 无模板参数（金色 token 属性来自金色 CardDef）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        _summon_token_run(source, game, _TOKEN_MICROBOT, 1, golden=True)
        return None


# ══════════════════ BG30_125 Cadaver Caretaker ══════════════════


class CadaverCaretakerScript:
    """
    Natural language: <b>Deathrattle:</b> Summon three 1/1 Skeletons.

    Formal spec:
      1. 同 Harmless Bonehead 模式: 宿主原位连续召唤 skeleton_count 个
         BG_ICC_026t（1/1 Undead）; 金色文本 "six" → 6 个

    Test: [A, 宿主, B] → [A, S, S, S, B] / 金色 6 个

    Params: 无模板参数（token 属性来自 CardDef; 数量为文本字面量 3/6）
    """

    skeleton_count = 3   # 文本字面量 "three"

    @staticmethod
    def deathrattle(source, game, ctx):
        _summon_token_run(source, game, _TOKEN_SKELETON,
                          source.scripts.skeleton_count)
        return None


class CadaverCaretakerGoldenScript(CadaverCaretakerScript):
    """
    Natural language: <b>Deathrattle:</b> Summon six 1/1 Skeletons.

    Formal spec:
      1. 同基础版，skeleton_count=6（金色文本 "six"）

    Test: 金色亡语出 6 个 BG_ICC_026t

    Params: 无模板参数（token 属性来自 CardDef; 数量为金色文本字面量 6）
    """

    skeleton_count = 6   # 金色文本字面量 "six"


# ══════════════════ BG31_801 Forest Rover ══════════════════


class ForestRoverScript:
    """
    Natural language: [x]<b>Battlecry:</b> Your Beetles
    have +{2}/+{3} this game.
    <b>Deathrattle:</b> Summon a
    {0}/{1} Beetle.

    Formal spec:
      1. BC（每次触发，Action 入队）: ApplyRaceAura(控制者, Race.BEAST,
         num(2), num(3))——Beetle token（BG28_603t）种族为 BEAST（作业单
         裁定: 经种族光环建模; 局限: 同样惠及其他 Beast，Beetle 专属
         跟踪需引擎卡 id 级光环支持，已报告主线）。金色 BC 引擎触发
         2 次、每次按基础 CardDef（2/1）→ 总额 4/2 = 金色文本 {2}/{3}
      2. DR（单次触发，直调模式）: 宿主原位召唤 beetle_count 个 Beetle
         token，属性覆盖为本卡 num(0)/num(1)（金色注册类为 2 个——
         金色文本 "two"）
      3. 光环对已召唤 Beetle 经 _aura_atk/_aura_health 生效（叠加于
         覆盖后的基础值之上，官方: Beetle 2/2 + 光环 2/1 = 4/3）

    Test: BC 后友方 Beast atk/max_health +num(2)/+num(3) / DR 出
    BG28_603t 且 BASE == num(0)/num(1) / 金色 BC（play）合计 +4/+2 /
    金色 DR 出 2 个 Beetle

    Params: {0}=2 {1}=2 {2}=2 {3}=1（36.2.2 基线，金色 2/2/4/2）
    """

    beetle_count = 1   # 文本字面量 "a"

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _per_trigger_def(game, source)
        return ApplyRaceAura(hero, Race.BEAST, d.num(2), d.num(3),
                             source_id=source.card_id)

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        _summon_beetles_now(source, game, d.num(0), d.num(1),
                            source.scripts.beetle_count)
        return None


class ForestRoverGoldenScript(ForestRoverScript):
    """
    Natural language: [x]<b>Battlecry:</b> Your Beetles
    have +{2}/+{3} this game.
    <b>Deathrattle:</b> Summon two
    {0}/{1} Beetles.

    Formal spec:
      1. BC: 继承基础版（每次触发按基础 CardDef 2/1，引擎金色触发 2 次
         → 总额 4/2 = 金色文本 {2}/{3}=4/2）
      2. DR: beetle_count=2——两个 Beetle，各按金色 num(0)/num(1)（2/2）
         覆盖属性，连续插入宿主位右侧

    Test: 金色 BC（play 路径）合计 +4/+2 / 金色 DR 出 2 个 BG28_603t

    Params: {0}=2 {1}=2 {2}=4 {3}=2（金色 CardDef，36.2.2 基线）
    """

    beetle_count = 2   # 金色文本字面量 "two"


# ══════════════════ BG31_803 Buzzing Vermin ══════════════════


class BuzzingVerminScript:
    """
    Natural language: [x]<b>Taunt</b>
    <b>Deathrattle:</b> Summon a
    {0}/{1} Beetle.

    Formal spec:
      1. 死亡时（直调模式）: 宿主原位召唤 beetle_count 个 Beetle token
         （BG28_603t），属性覆盖为本卡 num(0)/num(1); 金色文本 "two"
         → 2 个（金色注册类）
      2. Taunt 由 CardDef→引擎映射

    Test: DR 出 BG28_603t 且 BASE == num(0)/num(1)、Taunt tag 在场 /
    金色 2 个

    Params: {0}=2 {1}=2（36.2.2 基线，金色同值 ×2 个）
    """

    beetle_count = 1   # 文本字面量 "a"

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        _summon_beetles_now(source, game, d.num(0), d.num(1),
                            source.scripts.beetle_count)
        return None


class BuzzingVerminGoldenScript(BuzzingVerminScript):
    """
    Natural language: [x]<b>Taunt</b>
    <b>Deathrattle:</b> Summon
    two {0}/{1} Beetles.

    Formal spec:
      1. 同基础版，beetle_count=2（金色文本 "two"），各按金色 num(0)/
         num(1)（2/2）覆盖属性

    Test: 金色亡语出 2 个 BG28_603t

    Params: {0}=2 {1}=2（金色 CardDef）×2 个
    """

    beetle_count = 2   # 金色文本字面量 "two"


# ══════════════════ BG31_809 Turquoise Skitterer ══════════════════


class TurquoiseSkittererScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Your Beetles
    have +{2}/+{3} this game.
    Summon a {0}/{1} Beetle.

    Formal spec:
      1. 死亡时（单次触发，按本卡 CardDef，直调模式）:
         a) ApplyRaceAura(控制者, Race.BEAST, num(2), num(3)).do——
            Beetle=BEAST 种族（作业单裁定，同 Forest Rover 局限已报告）
         b) 宿主原位召唤 beetle_count 个 Beetle，属性覆盖为 num(0)/num(1)
      2. 金色注册类: 光环 10/10（金色 num）+ 2 个 Beetle（金色文本 "two"）

    Test: DR 后友方 Beast +num(2)/+num(3)（5/5）且出 1 个 BASE 2/2 的
    Beetle / 金色 +10/+10 且 2 个

    Params: {0}=2 {1}=2 {2}=5 {3}=5（36.2.2 基线，金色 2/2/10/10）
    """

    beetle_count = 1   # 文本字面量 "a"

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        ApplyRaceAura(hero, Race.BEAST, d.num(2), d.num(3),
                      source_id=source.card_id).do(game)
        _summon_beetles_now(source, game, d.num(0), d.num(1),
                            source.scripts.beetle_count)
        return None


class TurquoiseSkittererGoldenScript(TurquoiseSkittererScript):
    """
    Natural language: [x]<b>Deathrattle:</b> Your Beetles
    have +{2}/+{3} this game.
    Summon two {0}/{1} Beetles.

    Formal spec:
      1. 同基础版，金色 CardDef num: 光环 {2}/{3}=10/10、Beetle
         {0}/{1}=2/2 ×2 个

    Test: 金色 DR 后友方 Beast +10/+10 且出 2 个 BASE 2/2 Beetle

    Params: {0}=2 {1}=2 {2}=10 {3}=10（金色 CardDef，36.2.2 基线）
    """

    beetle_count = 2   # 金色文本字面量 "two"


# ══════════════════ BG31_925 Showy Cyclist ══════════════════


class ShowyCyclistScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Give all your
    Naga +{1}/+{3}. <i>(Improved
    by every 3 spells you've
    cast this game!)</i>

    Formal spec:
      1. 死亡时（单次触发，按本卡 CardDef，直调模式）: 攻击 = num(1)、
         生命 = num(3)（文本占位符 {1}/{3} 映射 script_data_num_2/4）;
         增益倍数 mult = 1 + 施法数 // num(0)（"every 3" 整除递进:
         0-2 次 ×1、3-5 次 ×2、6-8 次 ×3 …）
      2. 施法数 = source.controller 的 TAVERN_SPELLS_CAST_THIS_GAME
         （作业单裁定: 酒馆法术计数，引擎仅对 is_pool_spell 法术累计）
      3. 目标 = 棋盘全部存活友方 Naga（含 ALL 种族），各得
         +num(1)*mult/+num(3)*mult 永久 Buff（Buff.do 直调）; 无 Naga →
         落空
      4. 文本第二变体 "(Cast {2}/3 spells to improve!)" 为动态进度
         提示（{2} 非静态参数，CardDef 无 num(2)），不影响结算
      5. 金色文本同构仅数值差异（num(1)/num(3)=4/2）→ 同一脚本类复用

    Test: 0 施法 +2/+1、3 施法 +4/+2、7 施法 +6/+3、非 Naga 不受影响 /
    无 Naga 落空 / 金色 0 施法 +4/+2

    Params: {0}=3（"every 3"） {1}=2 {3}=1（36.2.2 基线，金色
            {1}=4 {3}=2 经金色 CardDef 体现）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        casts = hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0)
        mult = 1 + casts // d.num(0)
        for m in hero.board:
            if not m.dead and m.race in (Race.NAGA, Race.ALL):
                Buff(m, atk=d.num(1) * mult,
                     health=d.num(3) * mult).do(game)
        return None


# ══════════════════ BG32_111 Nightmare Par-tea Guest ══════════════════


class NightmareParteaGuestScript:
    """
    Natural language: <b>Battlecry and Deathrattle:</b> Get a Misplaced
    Tea Set.

    Formal spec:
      1. BC（每次触发，Action 入队）与 DR（单次触发，直调模式）:
         GetSpellCard(BG28_888)——Misplaced Tea Set 为**池法术**
         （is_pool_spell）: spell_pool 有副本 → acquire 占池（RULES
         §2.3）; 无副本 → 直接 create（作业单裁定: 不因池耗尽落空）;
         pending_hand_add 满手排队
      2. BC 基础每次触发 1 张（金色引擎触发 2 次 → 总额 2 张 = 金色
         文本 "Get 2 Misplaced Tea Sets"）; DR 由金色注册类实现 2 张
      3. Tea Set 本体效果（"Give a friendly minion of each type
         +{0}/+{1}"，num 4/4）属法术脚本，不在本批次范围

    Test: BC/DR 后手牌出现 BG28_888 且 spell_pool.available==0 /
    金色 BC（play）2 张 / 金色 DR 2 张（第二张池空仍生成）

    Params: 无模板参数（数量为文本字面量 1; 金色 2）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return GetSpellCard(hero, _SPELL_TEA_SET)

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        GetSpellCard(hero, _SPELL_TEA_SET).do(game)
        return None


class NightmareParteaGuestGoldenScript(NightmareParteaGuestScript):
    """
    Natural language: <b>Battlecry and Deathrattle:</b> Get 2 Misplaced
    Tea Sets.

    Formal spec:
      1. BC: 继承基础版（每次触发 1 张，引擎金色触发 2 次 → 2 张）
      2. DR: 单次触发 2 张（金色文本 "2"）——第一张 acquire 占池、
         第二张池已无副本则直接 create（作业单裁定）

    Test: 金色 DR 后手牌 2 张 BG28_888

    Params: 无模板参数（数量为金色文本字面量 2）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        for _ in range(2):
            GetSpellCard(hero, _SPELL_TEA_SET).do(game)
        return None


# ══════════════════ BG32_170 Metallic Hunter ══════════════════


class MetallicHunterScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Get a
    Pointy Arrow.

    Formal spec:
      1. 死亡时（直调模式）: GetSpellCard(EBG_Spell_014)——Pointy Arrow
         为**非池**法术（is_pool_spell=False）→ 直接 create +
         pending_hand_add，不与 spell_pool 交互（作业单裁定路径）
      2. 金色文本 "Get 2 Pointy Arrows" → 金色注册类 2 张
      3. Arrow 本体效果（"Give a minion +{0} Attack"，num(0)=4）属
         法术脚本，不在本批次范围

    Test: DR 后手牌出现 1 张 EBG_Spell_014 且 spell_pool 不变 /
    金色 2 张

    Params: 无模板参数（数量为文本字面量 1; 金色 2）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        GetSpellCard(hero, _SPELL_POINTY_ARROW).do(game)
        return None


class MetallicHunterGoldenScript(MetallicHunterScript):
    """
    Natural language: [x]<b>Deathrattle:</b> Get 2
    Pointy Arrows.

    Formal spec:
      1. 同基础版，数量 = 金色文本字面量 2（非池法术连发两张均直接
         create）

    Test: 金色 DR 后手牌 2 张 EBG_Spell_014

    Params: 无模板参数（数量为金色文本字面量 2）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        for _ in range(2):
            GetSpellCard(hero, _SPELL_POINTY_ARROW).do(game)
        return None


# ══════════════════ 注册 ══════════════════


def register() -> list[str]:
    from hsrl2.scripts.registry import register as _register

    _register("BG23_318", LeeroyTheRecklessScript)
    _register("BG23_318_G", LeeroyTheRecklessScript)
    _register("BG25_009", EternalSummonerScript)
    _register("BG25_009_G", EternalSummonerGoldenScript)
    _register("BG25_010", HandlessForsakenScript)
    _register("BG25_010_G", HandlessForsakenGoldenScript)
    _register("BG25_022", ScarletSkullScript)
    _register("BG25_022_G", ScarletSkullGoldenScript)
    _register("BG25_806", SlyRaptorScript)
    _register("BG25_806_G", SlyRaptorScript)
    _register("BG26_148", ScrapScraperScript)
    _register("BG26_148_G", ScrapScraperGoldenScript)
    _register("BG26_162", DancingBarnstormerScript)
    _register("BG26_162_G", DancingBarnstormerGoldenScript)
    _register("BG27_016", ChampionOfSargerasScript)
    _register("BG27_016_G", ChampionOfSargerasScript)
    _register("BG27_080", MotleyPhalanxScript)
    _register("BG27_080_G", MotleyPhalanxScript)
    _register("BG28_300", HarmlessBoneheadScript)
    _register("BG28_300_G", HarmlessBoneheadGoldenScript)
    _register("BG28_309", MummifierScript)
    _register("BG28_309_G", MummifierGoldenScript)
    _register("BG29_611", CordPullerScript)
    _register("BG29_611_G", CordPullerGoldenScript)
    _register("BG30_125", CadaverCaretakerScript)
    _register("BG30_125_G", CadaverCaretakerGoldenScript)
    _register("BG31_801", ForestRoverScript)
    _register("BG31_801_G", ForestRoverGoldenScript)
    _register("BG31_803", BuzzingVerminScript)
    _register("BG31_803_G", BuzzingVerminGoldenScript)
    _register("BG31_809", TurquoiseSkittererScript)
    _register("BG31_809_G", TurquoiseSkittererGoldenScript)
    _register("BG31_925", ShowyCyclistScript)
    _register("BG31_925_G", ShowyCyclistScript)
    _register("BG32_111", NightmareParteaGuestScript)
    _register("BG32_111_G", NightmareParteaGuestGoldenScript)
    _register("BG32_170", MetallicHunterScript)
    _register("BG32_170_G", MetallicHunterGoldenScript)

    return [
        "BG23_318", "BG23_318_G",
        "BG25_009", "BG25_009_G",
        "BG25_010", "BG25_010_G",
        "BG25_022", "BG25_022_G",
        "BG25_806", "BG25_806_G",
        "BG26_148", "BG26_148_G",
        "BG26_162", "BG26_162_G",
        "BG27_016", "BG27_016_G",
        "BG27_080", "BG27_080_G",
        "BG28_300", "BG28_300_G",
        "BG28_309", "BG28_309_G",
        "BG29_611", "BG29_611_G",
        "BG30_125", "BG30_125_G",
        "BG31_801", "BG31_801_G",
        "BG31_803", "BG31_803_G",
        "BG31_809", "BG31_809_G",
        "BG31_925", "BG31_925_G",
        "BG32_111", "BG32_111_G",
        "BG32_170", "BG32_170_G",
    ]
