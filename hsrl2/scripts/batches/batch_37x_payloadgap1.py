"""批次 37x_payloadgap1 — 载荷先行（C 类 9 载荷 + 8 宿主）＋ E 类 5 张。

背景
═══════════════════════════════════════════════════════════════════════
37x_poolgap2 后池内脚本缺口 34 张。本批按 Lead 指示分两步：
  C. **载荷先行**（先注册 payload，再放宿主；SOP §12 item 14「载荷未
     注册的宿主不得注册」）——本批交付 9 个载荷 id + 8 张宿主；
  E. 语义明确、无子系统依赖的 5 张。

C 类载荷（REGISTRY 条目；is_pool_spell/金色独立卡按数据）
═══════════════════════════════════════════════════════════════════════
  BG32_337 Seafood Stew（池内 T3 酒馆法术，cost 2）
      Give a minion +{0}/+{1}. Repeat for each different
      <b>Bonus Keyword</b> in your warband.
  BG35_911 Arcane Absorption（非池 T4 酒馆法术，cost 1）
      Give a friendly Elemental half the stats of the highest-Health
      minion in the Tavern.
  BG36_301t Sludge Corrosion（池内 T4 酒馆法术，cost 1）
      Give your minions +{0}/+{1}. If you discard this, cast it twice.
  BG34_170t / _G  Red Volumizer（T2 3/1 Mech, Magnetic）
  BG34_170t2 / _G Blue Volumizer（T2 1/3 Mech, Magnetic）
  BG34_170t3 / _G Green Volumizer（T2 3/3 Mech, Magnetic）
      [x]<b>Magnetic</b>. The first time this is played or
      <b>Magnetized</b>, your Volumizers have +{1} Attack / +{1} Health /
      +{1}/+{2} this game <i>(wherever they are)</i>.
  **BG35_910 Conflagration 仍 DEFERRED**（见 §DEFERRED D 类：缺
  "本回合已打出元素数" 引擎通道）。

C 类宿主（8 张池内随从；金色独立 CardDef）
═══════════════════════════════════════════════════════════════════════
  BG32_336 / _G  Gormling Gourmet：Taunt. BC **and** DR: Get a Seafood
      Stew.（金色 "Get 2 Seafood Stews"——BC 由引擎金色双触发；DR 单次
      → 脚本 is_golden 给 2）
  BG35_881 / _G  Leyline Surfacer：BC and DR: Get an Arcane Absorption.
      （金色 2 份；BC 引擎双触发、DR 单次分支）
  BG36_112 / _G  Fetid Corroder：BC: Get a Sludge Corrosion.
  BG36_115 / _G  Nightmare Corroder：EoT: get a Sludge Corrosion.
      （金色 2 份——EoT 不翻倍，脚本分支）
  BG34_170 / _G  Auto Accelerator：BC: Get a random Magnetic Volumizer.
      （金色引擎双触发 = 2）
  BG34_171 / _G  Conveyor Construct：DR: Get a random Magnetic Volumizer.
      （金色 2 只——DR 单次分支）
  BG36_366 / _G  Resourceful Robot：EoT: Magnetize a random Volumizer to
      this. Get a copy of it.（金色：2 只 + 各 1 份副本）
  BG36_367 / _G  Auto Reveille：After you buy {2} cards, Magnetize a
      random Volumizer to this and get a copy of it. ({0} left!)
      （金色：1 只 + 该只的 2 份副本）

E 类 5 张（池内随从；金色独立 CardDef）
═══════════════════════════════════════════════════════════════════════
  BG32_231 / _G  Elite Navigator：BC: Make a friendly Pirate from Tier 4
      or below Golden.（金色 "**2** friendly Pirates"——两段目标选择链）
  BG36_362 / _G  Sacrificial Wrathguard：DR: Give minions in the Tavern
      +{0}/+{1} this game. Activate ({4}): Improve this.
  BG36_370 / _G  Victorious Geomant：Activate ({0}): Get {1} Blood Gems.
      Cast any that don't fit on your left-most minion.
  BG36_700 / _G  Sewer Escapee：Activate ({2}): Give another Murloc
      +{0}/+{1} and a random Bonus Keyword.
  BG32_860 / _G  Shoalfin Mystic：When you sell this, your Tavern spells
      give an extra +{0}/+{1} this game.

数值/语义权威
═══════════════════════════════════════════════════════════════════════
- 数值一律 `CardDef.num(i)`（37.0.0.255130；金色独立 CardDef 自然体现
  金色数值）；**金色战吼"总份数"**用 `_per_trigger_def`（引擎金色战吼
  触发 2 次；金色 CardDef 若已是总数则每次按基础值），**金色亡语/EoT/
  售出**不被引擎翻倍 → 按金色文本显式分支。
- 酒馆法术增益一律经 `actions.racefx.tavern_spell_buff`（自动叠加
  `TAVERN_SPELL_EXTRA_ATK/HEALTH` —— 本批 Shoalfin Mystic / 既有
  Dark Puppeteer / 酒馆法术家族统一口径）。
- "highest-Health minion in the Tavern" = 酒馆内**当前生命**最高者
  （SOP §16b #23），并列 `game.rng.choice`; "half the stats" = 攻/血
  各自 floor 一半（自然语言解读，记录边界）。
- "different Bonus Keyword in your warband" = 棋盘随从的六集 Bonus
  Keyword **并集大小**（RULES §9.6 六集：DS/Reborn/Stealth/Taunt/
  Venomous/Windfury）。
- "1-Cost"/"Tier 4 or below" 等按数据口径: cost / CardDef.tech_level。
- Volumizer "wherever they are"：引擎 `hero.card_auras` 的 source
  绑定语义要求 source 存活，而 Volumizer 可能在 Magnetize 后离场——
  因此改用**hero 级游戏长计数器**（`hero.volumizer_aura_atk/health`）
  + 各 Volumizer 脚本的 `atk`/`health` **动态属性钩子**（`entity.py`
  契约：返回 int 覆盖 base+buffs+aura 全量、None 回落）。计数器在
  grant 时累加，动态钩子对所有区域/未来副本实时生效；health 增量
  同步抬升当前在场 Volumizer 的血量（与 `ApplyRaceAura` 可观测行为
  同款）。"first time this is played or Magnetized" 用实体
  `_volumizer_done` 幂等闸；Magnetize 路径经 **hero-owned
  `magnetized` 监听器**触发（owner=source 会在 `zone=REMOVED` 时先
  注销，收不到事件——故监听器挂 hero，实体级 done 防重复）。
- 随机一律 `game.rng`；池约束: 池内法术 `grant_card_copy_to_hand`
  （spell_pool.acquire）；非池法术直接 create；Volumizer/血宝石 token
  零池记账。

DEFERRED 台账（本批后仍缺；类别沿用上批 + 本批新增）
═══════════════════════════════════════════════════════════════════════
A. ~~Deity 子系统缺失（10）~~ —— **已于 2026-10-18 关闭**: F-07
   `batch_37x_deity` 注册 7 张非 discard 依赖卡 + 载荷 Energizing
   Chamber；F-08 `batch_37x_discard` 注册剩余 3 张（BG36_099/106、
   BGFYM_005）。
B. ~~Discard 子系统缺失（9 + 3 张 Deity discard 卡）~~ —— **已于
   2026-10-18 由 `batch_37x_discard`（F-08）关闭**（Discard action/
   事件/on_discard/弃牌计数）。
C. 触发链无权威上限（1）: BG28_583 Geomagus Roogug（唯一剩余池内缺口）。
D. ~~缺"本回合已打出元素数"引擎通道（2）~~ —— **已于 2026-10-18 由
   `batch_37x_firelands` 关闭**: F-06 原语落地（
   `Hero.elementals_played_this_turn` + `_begin_recruit_for` 清零 +
   `Game.elementals_played_this_turn(hero)` 读取点，见
   `docs/ENGINE_NOTES.md` F-06）；BG35_910 Conflagration 与宿主
   BG35_882 Firelands Fugitive 已注册（原台账见 git 历史）。
E. 语义明确、可排下一批: 无（本批已清空 E 类）。

Test: `hsrl2/tests/test_batch_37x_payloadgap1.py`（真实 `play_spell` /
`play_minion` / `destroy_minion` / `sell_minion` / `end_recruit_phase`
EoT / `_finish_hero_power` / 真实磁力 `attach_magnetic` / 真实
`buy_from_tavern` 事件；每卡正负对照 + 金色独立 CardDef 断言）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from hsrl2 import constants as C
from hsrl2.actions import (
    Buff,
    GainKeyword,
    Transform,
)
from hsrl2.actions.bloodgem import PlayBloodGems
from hsrl2.actions.racefx import tavern_spell_buff
from hsrl2.actions.tavern_buff import (
    ApplyTavernBuff,
    BuffCurrentTavern,
    TavernBuff,
)
from hsrl2.events import (
    MAGNETIZED,
    SPELL_BOUGHT,
    Listener,
)
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

if TYPE_CHECKING:                                  # pragma: no cover
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# ── 载荷 id（CardDB 按名核实）──
SEAFOOD_STEW = "BG32_337"            # 池内 T3 酒馆法术
ARCANE_ABSORPTION = "BG35_911"       # 非池 T4 酒馆法术
SLUDGE_CORROSION = "BG36_301t"       # 池内 T4 酒馆法术
CONFLAGRATION = "BG35_910"           # DEFERRED（D 类）
RED_VOLUMIZER = "BG34_170t"
RED_VOLUMIZER_G = "BG34_170t_G"
BLUE_VOLUMIZER = "BG34_170t2"
BLUE_VOLUMIZER_G = "BG34_170t2_G"
GREEN_VOLUMIZER = "BG34_170t3"
GREEN_VOLUMIZER_G = "BG34_170t3_G"
BLOOD_GEM = "BG20_GEM"

_VOLUMIZER_BASE_IDS = (RED_VOLUMIZER, BLUE_VOLUMIZER, GREEN_VOLUMIZER)
_VOLUMIZER_IDS = frozenset({
    RED_VOLUMIZER, RED_VOLUMIZER_G,
    BLUE_VOLUMIZER, BLUE_VOLUMIZER_G,
    GREEN_VOLUMIZER, GREEN_VOLUMIZER_G,
})

# ── 宿主 id ──
GORMLING_GOURMET = "BG32_336"
GORMLING_GOURMET_G = "BG32_336_G"
LEYLINE_SURFACER = "BG35_881"
LEYLINE_SURFACER_G = "BG35_881_G"
FETID_CORRODER = "BG36_112"
FETID_CORRODER_G = "BG36_112_G"
NIGHTMARE_CORRODER = "BG36_115"
NIGHTMARE_CORRODER_G = "BG36_115_G"
AUTO_ACCELERATOR = "BG34_170"
AUTO_ACCELERATOR_G = "BG34_170_G"
CONVEYOR_CONSTRUCT = "BG34_171"
CONVEYOR_CONSTRUCT_G = "BG34_171_G"
RESOURCEFUL_ROBOT = "BG36_366"
RESOURCEFUL_ROBOT_G = "BG36_366_G"
AUTO_REVEILLE = "BG36_367"
AUTO_REVEILLE_G = "BG36_367_G"
FIRELANDS_FUGITIVE = "BG35_882"       # DEFERRED（D 类，载荷缺通道）

# ── E 类 id ──
ELITE_NAVIGATOR = "BG32_231"
ELITE_NAVIGATOR_G = "BG32_231_G"
SACRIFICIAL_WRATHGUARD = "BG36_362"
SACRIFICIAL_WRATHGUARD_G = "BG36_362_G"
VICTORIOUS_GEOMANT = "BG36_370"
VICTORIOUS_GEOMANT_G = "BG36_370_G"
SEWER_ESCAPEE = "BG36_700"
SEWER_ESCAPEE_G = "BG36_700_G"
SHOALFIN_MYSTIC = "BG32_860"
SHOALFIN_MYSTIC_G = "BG32_860_G"


# ══════════════════════════════════════════════════════════════════════
# 公共工具
# ══════════════════════════════════════════════════════════════════════


def _num(game: "Game", card_id: str, index: int) -> int:
    """`CardDef.num(index)` 权威取值; 缺失 fail-loud（禁止静默 0）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return int(value)


def _per_trigger_def(game: "Game", source):
    """金色战吼"每次触发值"解析: 金色实体回基础 CardDef。

    引擎对金色随从战吼触发 2 次（`play_minion times *= 2`）；若金色
    CardDef 的 num 已是总份数（如 BG32_336_G / BG35_881_G 无 num → 不
    适用；本 helper 用于有 num 且金色为总值的卡），每次用基础值。
    """
    d = game.db.get(source.card_id)
    if d is not None and d.is_golden_def and d.triple_base_id is not None:
        base = game.db.by_dbf(d.triple_base_id)
        if base is not None:
            return base
    return d


def _get_card_copies(game: "Game", hero: "Hero", card_def,
                     count: int) -> int:
    """Get <卡> ×count: 白板副本入手（池法术占池/非池直造，满手排队）。

    返回实际交付数（池空/未知定义时少交付——官方落空语义）。
    """
    if card_def is None or count <= 0:
        return 0
    delivered = 0
    for _ in range(count):
        if game.grant_card_copy_to_hand(hero, card_def):
            delivered += 1
    return delivered


def _spell_target(ctx) -> Optional[Minion]:
    target = (ctx or {}).get("target")
    return target if isinstance(target, Minion) else None


def _random_volumizer_id(game: "Game") -> str:
    """随机一个 Volumizer 变体（官方 token 族；均匀三选一，零池记账）。"""
    return game.rng.choice(list(_VOLUMIZER_BASE_IDS),
                           label="random_volumizer")


def _is_volumizer(entity) -> bool:
    if entity is None:
        return False
    cid = getattr(entity, "card_id", None)
    bid = entity.get(GameTag.TRIPLE_BASE_CARD_ID, None) or cid
    return cid in _VOLUMIZER_IDS or bid in _VOLUMIZER_IDS


def _volumizer_variant(base_id: str):
    """base id → 变体脚本类（提供 atk/health 数值槽位）。"""
    return {
        RED_VOLUMIZER: RedVolumizerScript,
        BLUE_VOLUMIZER: BlueVolumizerScript,
        GREEN_VOLUMIZER: GreenVolumizerScript,
    }.get(base_id)


def _grant_volumizer_aura(game: "Game", entity) -> None:
    """Volumizer 首次打出/被 Magnetize 时授予 hero 级游戏长光环。

    - 实体级 `_volumizer_done` 幂等（"first time"）
    - 数值 = 该实体 CardDef 的对应槽位（金色独立 CardDef 自动翻倍）
    - 累计到 `hero.volumizer_aura_atk/health`，由各 Volumizer 脚本的
      `atk`/`health` 动态钩子实时读取（任意区域/未来副本）
    - health 增量同步抬升当前在场 Volumizer 的当前血量（与
      `ApplyRaceAura` 的可观测行为同款），避免"最大血涨、当前血不涨"
    """
    if entity is None or getattr(entity, "_volumizer_done", False):
        return
    hero = getattr(entity, "controller", None)
    if hero is None:
        return
    base_id = entity.get(GameTag.TRIPLE_BASE_CARD_ID, None) or entity.card_id
    variant = _volumizer_variant(base_id)
    if variant is None:
        return
    entity._volumizer_done = True
    d = game.db.get(entity.card_id)
    if d is None:
        return
    atk_gain = int(d.num(variant.atk_num_index)) \
        if variant.atk_num_index else 0
    health_gain = int(d.num(variant.health_num_index)) \
        if variant.health_num_index else 0
    if atk_gain:
        hero.volumizer_aura_atk = \
            getattr(hero, "volumizer_aura_atk", 0) + atk_gain
    if health_gain:
        hero.volumizer_aura_health = \
            getattr(hero, "volumizer_aura_health", 0) + health_gain
        for zone_list in (hero.board, hero.hand, hero.tavern):
            for e in list(zone_list):
                if _is_volumizer(e):
                    e.set(GameTag.HEALTH, e.health + health_gain)


def _ensure_volumizer_magnet_listener(game: "Game", hero: "Hero") -> None:
    """确保 hero 级 `magnetized` 监听器存在（owner=hero 跨实体存活）。

    owner 必须是 hero：Volumizer 自身在 `attach_magnetic` 里先
    `zone=REMOVED`（owner=source 的监听器会被注销）**再** fire
    `magnetized`；hero-owned 监听器才能收到事件，实体级
    `_volumizer_done` 保证同一实例只结算一次。
    """
    if hero is None or getattr(hero, "volumizer_magnet_hook", False):
        return
    hero.volumizer_magnet_hook = True

    def on_magnetized(g, host=None, attached=None, **kw):
        if attached is None or attached.controller is not hero:
            return
        if not _is_volumizer(attached):
            return
        _grant_volumizer_aura(g, attached)

    game.events.register(Listener(
        event=MAGNETIZED, owner=hero, callback=on_magnetized))


def _static_total_atk(source: "Minion") -> int:
    """覆盖式 atk 钩子的全量复算（base + buffs + aura）。"""
    return (source.get(GameTag.BASE_ATK, 0)
            + sum(b.atk for b in source.buffs)
            + source._aura_atk())


def _static_total_health(source: "Minion") -> int:
    """覆盖式 max_health 钩子的全量复算。"""
    return (source.get(GameTag.BASE_HEALTH, 0)
            + sum(b.health for b in source.buffs)
            + source._aura_health())


# ══════════════════════════════════════════════════════════════════════
# C 类载荷：酒馆法术
# ══════════════════════════════════════════════════════════════════════


class SeafoodStewScript:
    """
    Natural language: Give a minion +{0}/+{1}. Repeat for each different
    <b>Bonus Keyword</b> in your warband.

    依据: CardDefs 37.0 BG32_337（池内 T3 酒馆法术，NUM_1=NUM_2=1；
    无金色独立 CardDef——池法术单定义）。

    Formal spec:
      1. needs_target=True（"Give a minion"）: `target_candidates` =
         己方棋盘全部存活随从; 无候选时引擎落空但法术消耗。
      2. "different Bonus Keyword in your warband": 统计己方棋盘
         **存活随从**的 Bonus Keyword **并集**大小 k（RULES §9.6 六集:
         Divine Shield / Reborn / Stealth / Taunt / Venomous /
         Windfury；来源 = CardDef 关键词 tag 或
         `GameTag.BONUS_KEYWORDS` 授予记录）。
      3. 目标获得 (1 + k) 次 +NUM_1/+NUM_2（"Give ... Repeat for each"
         = 首次 + 每个不同关键词再重复一次）；经
         `racefx.tavern_spell_buff` 叠加 TAVERN_SPELL_EXTRA_*。
      4. 无目标 → 落空（法术仍消耗）。

    Test: test_batch_37x_payloadgap1.py — 0 关键词 +1/+1 / DS+Taunt 两
    关键词 → +3/+3 / 非目标不增益 / 定向 PendingChoice / 无候选落空 /
    Shoalfin EXTRA 叠加。

    Params: {0}=1 {1}=1
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in hero.board if not m.dead]

    @staticmethod
    def on_play(source, game, ctx):
        target = _spell_target(ctx)
        if target is None:
            return None
        from hsrl2.game import BONUS_KEYWORD_TAGS
        hero = source.controller
        distinct = set()
        for m in hero.board:
            if m.dead:
                continue
            granted = m.get(GameTag.BONUS_KEYWORDS, frozenset()) or frozenset()
            distinct |= set(granted)
            for tag in BONUS_KEYWORD_TAGS:
                if m.has(tag):
                    distinct.add(tag)
        mult = 1 + len(distinct)
        d = game.db.get(source.card_id)
        return [tavern_spell_buff(target,
                                  int(d.num(0)) * mult,
                                  int(d.num(1)) * mult)]


class ArcaneAbsorptionScript:
    """
    Natural language: Give a friendly Elemental half the stats of the
    highest-Health minion in the Tavern.

    依据: CardDefs 37.0 BG35_911（非池 T4 酒馆法术，无数值参数）。

    Formal spec:
      1. needs_target=True（"Give a friendly Elemental"）:
         `target_candidates` = 己方棋盘存活元素（类型身份集合
         `has_race(ELEMENTAL)`，含 ALL/双类型）。
      2. 参照 = `hero.tavern` 内全部 Minion（法术除外）中**当前生命**
         最高者（SOP §16b #23），并列 `game.rng.choice`; 酒馆空 → 落空。
      3. 目标获得 +floor(参照.atk/2) / +floor(参照.max_health/2)
         （"half the stats" = 攻/血各半、向下取整——自然语言解读，边界
         记档）；经 `tavern_spell_buff` 叠加 TAVERN_SPELL_EXTRA_*。
      4. 无目标/无 Tavern 随从 → 落空（法术消耗）。

    Test: test_batch_37x_payloadgap1.py — 酒馆 8/8 参照 → 目标 +4/+4 /
    当前生命最高者被选（而非最大生命）/ 非元素不可选 / 空酒馆落空 /
    定向 PendingChoice。

    Params: 无数值参数（运行时聚合）
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in hero.board
                if not m.dead and m.has_race(Race.ELEMENTAL)]

    @staticmethod
    def on_play(source, game, ctx):
        target = _spell_target(ctx)
        hero = source.controller
        if target is None or hero is None:
            return None
        tavern_minions = [m for m in hero.tavern if isinstance(m, Minion)]
        if not tavern_minions:
            return None
        top = max(m.health for m in tavern_minions)
        tied = [m for m in tavern_minions if m.health == top]
        ref = game.rng.choice(tied, label="arcane_absorption_ref")
        return [tavern_spell_buff(target,
                                  ref.atk // 2, ref.max_health // 2)]


class SludgeCorrosionScript:
    """
    Natural language: Give your minions +{0}/+{1}. If you discard this,
    cast it twice.

    依据: CardDefs 37.0 BG36_301t（池内 T4 酒馆法术，NUM_1=NUM_2=1）。

    Formal spec:
      1. on_play: 己方棋盘全部存活随从各获 +NUM_1/+NUM_2；经
         `tavern_spell_buff` 叠加 TAVERN_SPELL_EXTRA_*。
      2. **discard 分支（F-08 已接线）**: `on_discard`（`Game.discard_card`
         唯一分发点）→ 结算基础效果 **2 次**（"If you discard this, cast
         it twice"）；弃置本身不触发 on_play/不回池（见 F-08）。
      3. 无目标（"your minions" 全体）。

    Test: test_batch_37x_payloadgap1.py — 全板 +1/+1 / 回合外/手牌
    不可达分支不崩 / Shoalfin EXTRA 联动 / 对手随从不变；
    test_batch_37x_discard.py — 弃置后效果结算 2 次。

    Params: {0}=1 {1}=1
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        return [tavern_spell_buff(m, int(d.num(0)), int(d.num(1)))
                for m in hero.board if not m.dead]

    @staticmethod
    def on_discard(source, game, ctx=None):
        """"If you discard this, cast it twice"（F-08）。"""
        for _ in range(2):
            actions = SludgeCorrosionScript.on_play(source, game, None)
            if actions:
                game.run_actions(actions)
        return None


# ══════════════════════════════════════════════════════════════════════
# C 类载荷：Volumizer 三变体（+ 金色）
# ══════════════════════════════════════════════════════════════════════


class _VolumizerBase:
    """Volumizer 公共协议: 首次打出/被 Magnetize → hero 级光环。

    - `atk_num_index` / `health_num_index`: 该变体授予的数值槽位
      （Red: atk=num(1)；Blue: health=num(1)；Green: atk=num(1)
      health=num(2)；金色独立 CardDef 数值翻倍）。
    - `on_summon`: 打出/召唤路径（首次即 grant）+ 确保 hero 级
      magnetized 监听器存在。
    - `on_enter_hand`: 入手即确保监听器存在（Magnetize 可以在
      从未召唤的情况下直接由手牌吸附）。
    - `atk` / `health` 动态钩子: 全量复算 + hero 计数器。
    """

    atk_num_index: Optional[int] = None
    health_num_index: Optional[int] = None

    @classmethod
    def on_summon(cls, source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        _ensure_volumizer_magnet_listener(game, hero)
        _grant_volumizer_aura(game, source)
        return None

    @classmethod
    def on_enter_hand(cls, source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is not None:
            _ensure_volumizer_magnet_listener(game, hero)
        return None

    @staticmethod
    def atk(source):
        return None

    @staticmethod
    def health(source):
        return None


class RedVolumizerScript(_VolumizerBase):
    """
    Natural language: [x]<b>Magnetic</b>. The first time this is played
    or <b>Magnetized</b>, your Volumizers have +{1} Attack this game
    <i>(wherever they are)</i>.

    依据: CardDefs 37.0 BG34_170t（T2 3/1 Mech，NUM_1=3）; 金色
    BG34_170t_G NUM_1=6。

    Formal spec:
      1. 首次打出（on_summon）或被 Magnetize（hero-owned
         `magnetized` 监听 + 实体级 `_volumizer_done` 幂等）:
         `hero.volumizer_aura_atk += NUM_1`（游戏长，跨战斗持久）。
      2. atk 动态钩子: 计数 > 0 → 全量复算 + 计数; 计数 0 → None
         回落引擎默认。任意区域生效（"wherever they are"）。
      3. 金色 NUM_1=6 由金色 CardDef 自然体现。

    Test: test_batch_37x_payloadgap1.py — 打出后自身与所有 Volumizer
    +3 Attack / 第二次打出不重复 / Magnetize 路径触发 / 金色 +6 /
    非 Volumizer 不增益 / 敌方 Volumizer 不共享。

    Params: {1}=3（金色 =6）
    """

    atk_num_index = 1

    @staticmethod
    def atk(source):
        hero = getattr(source, "controller", None)
        if hero is None or source.game is None:
            return None
        gain = getattr(hero, "volumizer_aura_atk", 0)
        if not gain:
            return None
        return _static_total_atk(source) + gain


class BlueVolumizerScript(_VolumizerBase):
    """
    Natural language: [x]<b>Magnetic</b>. The first time this is played
    or <b>Magnetized</b>, your Volumizers have +{1} Health this game
    <i>(wherever they are)</i>.

    依据: CardDefs 37.0 BG34_170t2（T2 1/3 Mech，NUM_1=3）; 金色
    BG34_170t2_G NUM_1=6。

    Formal spec: 同 Red，但授予 `hero.volumizer_aura_health`，health
    动态钩子生效；grant 时同步抬升当前在场 Volumizer 的当前血量。

    Test: test_batch_37x_payloadgap1.py — 打出后所有 Volumizer 最大/
    当前血量 +3 / 金色 +6 / Magnetize 路径。

    Params: {1}=3（金色 =6）
    """

    health_num_index = 1

    @staticmethod
    def health(source):
        hero = getattr(source, "controller", None)
        if hero is None or source.game is None:
            return None
        gain = getattr(hero, "volumizer_aura_health", 0)
        if not gain:
            return None
        return _static_total_health(source) + gain


class GreenVolumizerScript(_VolumizerBase):
    """
    Natural language: [x]<b>Magnetic</b>. The first time this is played
    or <b>Magnetized</b>, your Volumizers have +{1}/+{2} this game
    <i>(wherever they are)</i>.

    依据: CardDefs 37.0 BG34_170t3（T2 3/3 Mech，NUM_1=1 NUM_2=1）;
    金色 BG34_170t3_G NUM_1=NUM_2=2。

    Formal spec: 同时授予 atk/health 两个 hero 计数器（同 Red/Blue）。

    Test: test_batch_37x_payloadgap1.py — +1/+1 / 金色 +2/+2 / 三次
    不同变体叠加。

    Params: {1}=1 {2}=1（金色 =2/=2）
    """

    atk_num_index = 1
    health_num_index = 2

    @staticmethod
    def atk(source):
        hero = getattr(source, "controller", None)
        if hero is None or source.game is None:
            return None
        gain = getattr(hero, "volumizer_aura_atk", 0)
        if not gain:
            return None
        return _static_total_atk(source) + gain

    @staticmethod
    def health(source):
        hero = getattr(source, "controller", None)
        if hero is None or source.game is None:
            return None
        gain = getattr(hero, "volumizer_aura_health", 0)
        if not gain:
            return None
        return _static_total_health(source) + gain


# ══════════════════════════════════════════════════════════════════════
# C 类宿主：Get 载荷
# ══════════════════════════════════════════════════════════════════════


class GormlingGourmetScript:
    """
    Natural language: <b>Taunt</b> <b>Battlecry and Deathrattle:</b> Get
    a Seafood Stew.

    依据: CardDefs 37.0 BG32_336（T4 4/3 Murloc，BATTLECRY/DEATHRATTLE
    /TAUNT）；金色 BG32_336_G 文本 "Get 2 Seafood Stews"。

    Formal spec:
      1. battlecry: Get 1 张 Seafood Stew（池内法术 →
         `grant_card_copy_to_hand` 占 spell_pool；满手 pending 队列）。
      2. deathrattle: Get 1 张（基础）/ 2 张（金色——亡语不被引擎
         翻倍，脚本按金色文本分支）。
      3. 金色 battlecry 由**引擎金色战吼触发 2 次**实现总额 2。

    Test: test_batch_37x_payloadgap1.py — BC 1 张 / 金色 BC 2 张（引擎
    双触发）/ 真实 `destroy_minion` DR 1 张 / 金色 DR 2 张 / 池记账 /
    满手排队。

    Params: 无数值参数（份数 = 文本字面量 1/2）
    """

    @staticmethod
    def battlecry(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        _get_card_copies(game, hero, game.db.get(SEAFOOD_STEW), 1)
        return None

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        count = 2 if source.is_golden else 1
        _get_card_copies(game, hero, game.db.get(SEAFOOD_STEW), count)
        return None


class LeylineSurfacerScript:
    """
    Natural language: <b>Battlecry and Deathrattle:</b> Get an Arcane
    Absorption.

    依据: CardDefs 37.0 BG35_881（T4 4/6 Elemental）；金色
    BG35_881_G 文本 "Get 2 Arcane Absorptions"。

    Formal spec:
      1. BC: Get 1 张 Arcane Absorption（**非池**法术 → create_spell
         直造，零池记账；满手 pending 队列）。
      2. DR: 1 张（基础）/ 2 张（金色，亡语不翻倍）。
      3. 金色 BC 由引擎双触发实现 2 张。

    Test: test_batch_37x_payloadgap1.py — BC 1 / 金 BC 2 / DR 1 / 金 DR 2
    / 非池法术不占 spell_pool。

    Params: 无数值参数
    """

    @staticmethod
    def battlecry(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        _get_card_copies(game, hero, game.db.get(ARCANE_ABSORPTION), 1)
        return None

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        count = 2 if source.is_golden else 1
        _get_card_copies(game, hero, game.db.get(ARCANE_ABSORPTION), count)
        return None


class FetidCorroderScript:
    """
    Natural language: <b>Battlecry:</b> Get a Sludge Corrosion.

    依据: CardDefs 37.0 BG36_112（T3 3/3 Aberration）；金色
    BG36_112_G 文本 "Get 2 Sludge Corrosions"。

    Formal spec: BC get 1 张 Sludge Corrosion（池内法术 →
    `grant_card_copy_to_hand` 占 spell_pool；金色由引擎战吼双触发 = 2）。

    Test: test_batch_37x_payloadgap1.py — BC 1 / 金色 2 / 池副本 -1/-2。

    Params: 无数值参数
    """

    @staticmethod
    def battlecry(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        _get_card_copies(game, hero, game.db.get(SLUDGE_CORROSION), 1)
        return None


class NightmareCorroderScript:
    """
    Natural language: At the end of your turn, get a Sludge Corrosion.

    依据: CardDefs 37.0 BG36_115（T4 4/5 Aberration，无关键词）；金色
    BG36_115_G 文本 "get 2 Sludge Corrosions"。

    Formal spec: end_of_turn get 1 张（基础）/ 2 张（金色——EoT 钩子
    引擎不翻倍，脚本分支）；池内法术占 spell_pool、满手排队。

    Test: test_batch_37x_payloadgap1.py — 真实 `end_recruit_phase` EoT
    后入手 1 张 Sludge / 金色 2 张 / 池 -1/-2。

    Params: 无数值参数
    """

    @staticmethod
    def end_of_turn(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        count = 2 if source.is_golden else 1
        _get_card_copies(game, hero, game.db.get(SLUDGE_CORROSION), count)
        return None


class AutoAcceleratorScript:
    """
    Natural language: <b>Battlecry:</b> Get a random <b>Magnetic</b>
    Volumizer.

    依据: CardDefs 37.0 BG34_170（T3 3/3 Mech）；金色 BG34_170_G 文本
    "Get 2 random Magnetic Volumizers"（引擎金色战吼双触发 = 2）。

    Formal spec: BC: `game.rng.choice` 三变体之一 → `create_minion`
    （官方 token 族，零池记账）→ `pending_hand_add`。金色单次触发 1 只，
    引擎双触发合计 2 只（可重复变体）。

    Test: test_batch_37x_payloadgap1.py — BC 入手 1 只（变体 ∈ 三族）/
    金色 2 只 / 非磁力卡不产出 / 池不消耗。

    Params: 无数值参数
    """

    @staticmethod
    def battlecry(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        cid = _random_volumizer_id(game)
        vol = game.create_minion(cid, controller=hero)
        if vol is not None:
            game.pending_hand_add(hero, vol)
        return None


class ConveyorConstructScript:
    """
    Natural language: <b>Deathrattle:</b> Get a random <b>Magnetic</b>
    Volumizer.

    依据: CardDefs 37.0 BG34_171（T4 5/2 Mech）；金色 BG34_171_G 文本
    "Get 2 random Magnetic Volumizers"。

    Formal spec: deathrattle: 1 只（基础）/ 2 只（金色——亡语不翻倍）；
    随机三变体 token，零池记账，pending_hand_add。

    Test: test_batch_37x_payloadgap1.py — 真实 destroy: 1 只 / 金色 2 只。

    Params: 无数值参数
    """

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        count = 2 if source.is_golden else 1
        for _ in range(count):
            cid = _random_volumizer_id(game)
            vol = game.create_minion(cid, controller=hero)
            if vol is not None:
                game.pending_hand_add(hero, vol)
        return None


def _magnetize_and_copy(game: "Game", hero: "Hero", host: Minion,
                        magnetize_count: int, copies_each: int) -> None:
    """Magnetize random Volumizer(s) to host，并获得对应副本进手牌。

    - 每个磁力体经**真实** `game.attach_magnetic`（属性/关键词/亡语栈/
      `magnetized` 事件），随即 `create_minion` 白板副本
      → `pending_hand_add`（"Get a copy of it"）。
    - `copies_each` 份副本来自同一变体（同名 token）。
    - host 已离场/死亡 → 落空（EoT/买卡触发器保护）。
    - 磁力体由脚本直接 create（未经过 `on_enter_hand`）→ 先确保 hero
      级 `magnetized` 监听器存在，否则其 "first time Magnetized" 光环
      不会结算。
    """
    if host is None or host.dead or host.zone != Zone.PLAY:
        return
    _ensure_volumizer_magnet_listener(game, hero)
    for _ in range(max(0, magnetize_count)):
        cid = _random_volumizer_id(game)
        vol = game.create_minion(cid, controller=hero)
        if vol is None:
            continue
        game.attach_magnetic(hero, vol, host)
        for _ in range(max(0, copies_each)):
            copy = game.create_minion(cid, controller=hero)
            if copy is not None:
                game.pending_hand_add(hero, copy)


class ResourcefulRobotScript:
    """
    Natural language: At the end of your turn, <b>Magnetize</b> a random
    Volumizer to this. Get a copy of it.

    依据: CardDefs 37.0 BG36_366（T5 4/8 Mech）；金色 BG36_366_G 文本
    "Magnetize 2 random Volumizers to this. Get copies of them."

    Formal spec:
      1. end_of_turn: 1 只（基础）/ 2 只（金色）随机 Volumizer 以
         `game.attach_magnetic` 吸附到本体，并各获得 1 份白板副本进
         手牌（"Get copies of them"）。
      2. 磁力体经真实 `magnetized` 事件触发其 "first time" 光环。
      3. 本体离场/死亡 → 落空（引擎 EoT 只对棋盘随从分发，防御式守卫）。

    Test: test_batch_37x_payloadgap1.py — EoT 后本体属性/关键词吸收
    （磁力真实路径）+ 手牌 1 份副本 / 金色 2 只 + 2 份 / 副本可再次
    触发首次光环。

    Params: 无数值参数（只数 = 文本字面量 1/2）
    """

    @staticmethod
    def end_of_turn(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        if source.is_golden:
            _magnetize_and_copy(game, hero, source, 2, 1)
        else:
            _magnetize_and_copy(game, hero, source, 1, 1)
        return None


class AutoReveilleScript:
    """
    Natural language: [x]After you buy {2} cards, <b>Magnetize</b> a
    random Volumizer to this and get a copy of it. <i>({0} left!)</i>

    依据: CardDefs 37.0 BG36_367（T6 4/8 Mech，NUM_1=3 NUM_3=3）；
    金色 BG36_367_G 文本 "... and get **two** copies of it."（同 nums）。

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）: 事件
         `minion_bought` / `spell_bought`——条件是购买者是 source 的
         控制者（minion.controller / spell.controller is hero）。
         计数存 `source._auto_reveille_buys`（实体属性；离场即失效 =
         文案 "After you buy" 只在该随从在场时计数）。
      2. 每累计 NUM_3（=3，文本 `{2}` 的模板参数）次购买 → 触发一次：
         随机 1 只 Volumizer 以 `attach_magnetic` 吸附到本体 + 副本
         入手（基础 1 份 / 金色 **2 份**），计数归零（"({0} left!)"
         循环文案）。
      3. 金色数值只有份数差异（文本 "two copies"）→ 行为分支。

    Test: test_batch_37x_payloadgap1.py — 真实 `buy_from_tavern` 3 次
    触发 / 2 次不触发 / 第 6 次再触发（计数重置）/ 买法术同样计数 /
    金色 2 份副本 / 本体离场后不计数。

    Params: {0}=3 {2}=3（阈值 = NUM_3；金色同值）
    """

    @staticmethod
    def on_summon(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        threshold = _num(game, source.card_id, 2)

        def _count(_g, entity=None, **kw):
            if source is None or source.dead or source.zone != Zone.PLAY:
                return
            if entity is None or getattr(entity, "controller", None) is not hero:
                return
            n = getattr(source, "_auto_reveille_buys", 0) + 1
            if n < threshold:
                source._auto_reveille_buys = n
                return
            source._auto_reveille_buys = 0
            copies = 2 if source.is_golden else 1
            _magnetize_and_copy(_g, hero, source, 1, copies)

        game.events.register(Listener(
            event="minion_bought", owner=source,
            callback=lambda g, minion=None, **kw: _count(g, minion)))
        game.events.register(Listener(
            event=SPELL_BOUGHT, owner=source,
            callback=lambda g, spell=None, **kw: _count(g, spell)))
        return None

    #: Transform 后按新卡面重新接线（SOP §16c 模式 40）
    on_transform = on_summon


# ══════════════════════════════════════════════════════════════════════
# E 类：Elite Navigator
# ══════════════════════════════════════════════════════════════════════


def _make_pirate_golden(game: "Game", minion) -> bool:
    """Make a friendly Pirate Golden（真实 Transform；保留附魔）。"""
    if minion is None or getattr(minion, "dead", False):
        return False
    hero = getattr(minion, "controller", None)
    if hero is None or minion not in hero.board:
        return False
    if getattr(minion, "is_golden", False):
        return False
    base_id = minion.get(GameTag.TRIPLE_BASE_CARD_ID, None) or minion.card_id
    game.run_actions([Transform(
        minion, base_id, keep_buffs=True,
        gilded_not_tripled=True, force_golden=True)])
    return True


class EliteNavigatorScript:
    """
    Natural language: <b>Battlecry:</b> Make a friendly Pirate from
    Tier 4 or below Golden.

    依据: CardDefs 37.0 BG32_231（T5 5/5 Pirate，BATTLECRY）；金色
    BG32_231_G 文本 "Make **2** friendly Pirates from Tier 4 or below
    Golden"。

    Formal spec:
      1. needs_target=True（"Make a friendly Pirate ... Golden" 为定向）:
         `target_candidates` = 己方棋盘存活、Tier ≤ 4（
         `CardDef.tech_level`）、**非金** Pirate（类型身份集合含
         PIRATE，ALL 命中）。
      2. 目标经真实 `Transform(force_golden=True,
         gilded_not_tripled=True, keep_buffs=True)` 变金色（非三连金
         → 出售/淘汰回池 1 份口径；保留附魔）。
      3. 金色 "2 friendly Pirates": 首次目标选定后，若仍有合法候选 →
         脚本追加第二段 `PendingChoice(kind="battlecry_target",
         owner=hero)`；第二段 resolve 再 Transform。仅 1 个候选时只金化
         1 个（官方 "2" 在不足时按可得数量）。
      4. 无候选 → 战吼落空；已金/超 Tier/非 Pirate 不可选。

    Test: test_batch_37x_payloadgap1.py — 基础金化 1 个 Pirate 且保留
    buff / Tier 5 不可选 / 非海盗不可选 / 金色两段选择金化 2 个 /
    仅 1 候选时 1 个 / 非三连金回池 1 份标记。

    Params: 无数值参数（"2" 为金色文本字面量）
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        out = []
        for m in hero.board:
            if m.dead or m.is_golden or not m.has_race(Race.PIRATE):
                continue
            d = game.db.get(m.card_id)
            if d is not None and d.tech_level <= 4:
                out.append(m)
        return out

    @staticmethod
    def battlecry(source, game, ctx=None):
        target = _spell_target(ctx)
        if target is None:
            return None
        # 引擎对金色随从会**触发战吼 2 次**（同一 ctx target）:
        # 金色文本 "Make 2 friendly Pirates" 已由脚本的第二段选择链表达
        # → 第二次引擎触发必须跳过（否则重复排队/重复金化同一目标）。
        if getattr(source, "_elite_chain_queued", False):
            return None
        _make_pirate_golden(game, target)
        if not source.is_golden:
            return None
        hero = source.controller
        remaining = [m for m in EliteNavigatorScript.target_candidates(
            source, game) if not m.is_golden]
        if not remaining:
            return None
        source._elite_chain_queued = True

        def resolve(pick):
            _make_pirate_golden(game, pick)
            source._elite_chain_queued = False

        game.pending_choices.append(PendingChoice(
            hero, remaining, "battlecry_target", resolve_callback=resolve))
        return None


# ══════════════════════════════════════════════════════════════════════
# E 类：Sacrificial Wrathguard
# ══════════════════════════════════════════════════════════════════════


class SacrificialWrathguardScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Give minions in the Tavern
    +{0}/+{1} this game. <b>Activate ({4}):</b> Improve this.

    依据: CardDefs 37.0 BG36_362（T4 5/3 Demon；NUM_1=2 NUM_2=2
    NUM_5=1=activate cost；ACTIVATE）；金色 NUM_1=4 NUM_2=4。

    Formal spec:
      1. deathrattle: `TavernBuff(atk=NUM_1×M, health=NUM_2×M,
         race_filter=None, source_id)` → `ApplyTavernBuff` +
         `BuffCurrentTavern`（"minions in the Tavern" = 全部随从；
         M = 1 + 已 Improve 次数）。
      2. Activate ({4}=1 由引擎扣费/计次): "Improve this" —— 无独立增量
         参数 → Improve 家族口径 = 每次 +印面值 NUM_1/NUM_2
         （count += 1；金色按金色 CardDef 4/4）。
         计数存 `source._wrathguard_improves`（实体属性；离场重入场
         归零，同 FireForgedEvoker 先例）。
      3. 无目标、无随机。

    Test: test_batch_37x_payloadgap1.py — DR 馆内全随从 +2/+2、金 +4/+4 /
    真实 `use_activate` 后 DR 变 +4/+4（金 +8/+8）/ 激活扣 1 金且每回合
    一次 / 法术不 Buff。

    Params: {0}=2 {1}=2 {4}=1（金色 4/4；Improve 增量 = 印面值）
    """

    improves_attr = "_wrathguard_improves"

    @staticmethod
    def activate(source, game, ctx=None):
        count = getattr(source, SacrificialWrathguardScript.improves_attr, 0)
        setattr(source, SacrificialWrathguardScript.improves_attr, count + 1)
        return None

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        mult = 1 + getattr(
            source, SacrificialWrathguardScript.improves_attr, 0)
        tb = TavernBuff(atk=int(d.num(0)) * mult,
                        health=int(d.num(1)) * mult,
                        race_filter=None, source_id=source.card_id)
        return [ApplyTavernBuff(hero, tb), BuffCurrentTavern(hero, tb)]


# ══════════════════════════════════════════════════════════════════════
# E 类：Victorious Geomant
# ══════════════════════════════════════════════════════════════════════


class VictoriousGeomantScript:
    """
    Natural language: <b>Activate ({0}):</b> Get {1} <b>Blood Gems</b>.
    Cast any that don't fit on your left-most minion.

    依据: CardDefs 37.0 BG36_370（T6 10/10 Quilboar；NUM_1=2=activate
    cost，NUM_2=6=数量）；金色 NUM_2=12。

    Formal spec:
      1. Activate（引擎扣 NUM_1 金/计次）: 取 NUM_2 颗血宝石
         （`BG20_GEM`，vanilla；脚本手动绑定 REGISTRY——`create_spell`
         不自动绑定，见 `actions/bloodgem.GetBloodGems` 同款注释）。
      2. 手牌容量 = `HAND_SIZE - len(hero.hand)`；放得下的进手牌
         （`pending_hand_add` 语义），**放不下的**用
         `PlayBloodGems(leftmost, excess)` 施放在最左随从上
         （"Cast any that don't fit on your left-most minion"）。
      3. 棋盘无随从 → 放不下的部分落空（无处可施放）。
      4. GEMS_PLAYED_ON / `blood_gem_played` 事件由 PlayBloodGems 记账
         （Jailbird/Gem Confiscation 读取点）。

    Test: test_batch_37x_payloadgap1.py — 空手牌入手 6 颗并真实施放
    （手牌 6 颗且 GEMS_PLAYED_ON=0）/ 手牌 8 空位 2 → 2 颗入手指 4 颗
    施放（GEMS_PLAYED_ON=4）/ 金色 12 / 满手 0 空位 → 全部施放 / 无
    棋盘 → 全部落空不崩。

    Params: {0}=2 {1}=6（金色 {1}=12）
    """

    @staticmethod
    def activate(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        count = int(d.num(1))
        script = REGISTRY.get(BLOOD_GEM)
        free = max(0, C.HAND_SIZE - len(hero.hand))
        to_hand = min(count, free)
        for _ in range(to_hand):
            gem = game.create_spell(BLOOD_GEM, controller=hero)
            if gem is None:
                break
            gem.scripts = script
            game.pending_hand_add(hero, gem)
        excess = count - to_hand
        if excess > 0 and hero.board:
            leftmost = hero.board[0]
            if not leftmost.dead:
                game.run_actions([PlayBloodGems(leftmost, excess)])
        return None


# ══════════════════════════════════════════════════════════════════════
# E 类：Sewer Escapee
# ══════════════════════════════════════════════════════════════════════


class SewerEscapeeScript:
    """
    Natural language: [x]<b>Activate ({2}):</b> Give another Murloc
    +{0}/+{1} and a random <b>Bonus Keyword</b>.

    依据: CardDefs 37.0 BG36_700（T5 7/7 Murloc；NUM_1=NUM_2=7，
    NUM_3=1=activate cost）；金色 NUM 14/14。

    Formal spec:
      1. Activate（引擎扣 NUM_3 金/计次）: 候选 = 己方棋盘存活、
         **另一只**（排除 source）Murloc（类型身份集合含 MURLOC，
         ALL 命中）。无候选 → 落空（费用已扣，官方无合法目标语义）。
      2. 有候选 → `PendingChoice(kind="activate_target",
         owner=hero)`（Kelp Keeper 先例：Activate 定向由自动化层决策，
         非随机近似）；resolve: 目标 +NUM_1/+NUM_2（永久 Buff）+
         `game.grant_bonus_keyword(target, game.random_bonus_keyword())`。
      3. 金色数值由金色 CardDef 体现（14/14）。

    Test: test_batch_37x_payloadgap1.py — 真实 `use_activate`: 扣金 +
      挂起 activate_target / 选中后目标 +7/+7 且获得 1 个 Bonus
      Keyword / 无其他 Murloc 落空不崩 / 金色 +14/+14 / 自身不可选。

    Params: {0}=7 {1}=7 {2}=1（金色 14/14）
    """

    @staticmethod
    def activate(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        candidates = [m for m in hero.board
                      if m is not source and not m.dead
                      and m.has_race(Race.MURLOC)]
        if not candidates:
            return None
        d = game.db.get(source.card_id)

        def resolve(pick):
            if pick is None or getattr(pick, "dead", False):
                return
            game.run_actions([Buff(pick, atk=int(d.num(0)),
                                   health=int(d.num(1)))])
            game.grant_bonus_keyword(pick, game.random_bonus_keyword())

        game.pending_choices.append(PendingChoice(
            hero, candidates, "activate_target", resolve_callback=resolve))
        return None


# ══════════════════════════════════════════════════════════════════════
# E 类：Shoalfin Mystic
# ══════════════════════════════════════════════════════════════════════


class ShoalfinMysticScript:
    """
    Natural language: [x]When you sell this, your Tavern spells give an
    extra +{0}/+{1} this game.

    依据: CardDefs 37.0 BG32_860（T3 4/4 Murloc，NUM_1=NUM_2=1）；
    金色 BG32_860_G NUM_1=NUM_2=2。

    Formal spec:
      1. on_sell（真实 `game.sell_minion` 售出钩子，先于离场/回池）:
         `hero.TAVERN_SPELL_EXTRA_ATK += NUM_1`、
         `hero.TAVERN_SPELL_EXTRA_HEALTH += NUM_2`（"this game" 永久；
         消费点 = `actions.racefx.tavern_spell_buff`，本批 3 张酒馆法术
         载荷全部经该出口）。
      2. 金色 NUM=2/2 → +2/+2（数值由金色 CardDef 体现，无行为分支）。

    Test: test_batch_37x_payloadgap1.py — 真实 sell 后 tag +1/+1 / 金色
    +2/+2 / 叠加两只 / 之后 Seafood Stew 实际多给 1/1（端到端联动）。

    Params: {0}=1 {1}=1（金色 =2/=2）
    """

    @staticmethod
    def on_sell(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        hero.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0)
                 + int(d.num(0)))
        hero.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0)
                 + int(d.num(1)))
        return None


# ══════════════════════════════════════════════════════════════════════
# 注册
# ══════════════════════════════════════════════════════════════════════


def register() -> list[str]:
    """注册 35 张（10 载荷 id + 16 宿主 id + 10 E 类 id；0 DEFERRED 注册）。

    载荷: Seafood Stew / Arcane Absorption / Sludge Corrosion（3）+ 
          Volumizer 6（三变体 × 基础/金色）。
    宿主: 8 张池内随从 × 基础/金色 = 16。
    E 类: 5 张池内随从 × 基础/金色 = 10。
    """
    from hsrl2.scripts.registry import register as reg

    pairs = [
        # ── 载荷: 酒馆法术 ──
        (SEAFOOD_STEW, SeafoodStewScript),
        (ARCANE_ABSORPTION, ArcaneAbsorptionScript),
        (SLUDGE_CORROSION, SludgeCorrosionScript),
        # ── 载荷: Volumizer 三变体 ──
        (RED_VOLUMIZER, RedVolumizerScript),
        (RED_VOLUMIZER_G, RedVolumizerScript),
        (BLUE_VOLUMIZER, BlueVolumizerScript),
        (BLUE_VOLUMIZER_G, BlueVolumizerScript),
        (GREEN_VOLUMIZER, GreenVolumizerScript),
        (GREEN_VOLUMIZER_G, GreenVolumizerScript),
        # ── 宿主: Get 载荷 ──
        (GORMLING_GOURMET, GormlingGourmetScript),
        (GORMLING_GOURMET_G, GormlingGourmetScript),
        (LEYLINE_SURFACER, LeylineSurfacerScript),
        (LEYLINE_SURFACER_G, LeylineSurfacerScript),
        (FETID_CORRODER, FetidCorroderScript),
        (FETID_CORRODER_G, FetidCorroderScript),
        (NIGHTMARE_CORRODER, NightmareCorroderScript),
        (NIGHTMARE_CORRODER_G, NightmareCorroderScript),
        (AUTO_ACCELERATOR, AutoAcceleratorScript),
        (AUTO_ACCELERATOR_G, AutoAcceleratorScript),
        (CONVEYOR_CONSTRUCT, ConveyorConstructScript),
        (CONVEYOR_CONSTRUCT_G, ConveyorConstructScript),
        (RESOURCEFUL_ROBOT, ResourcefulRobotScript),
        (RESOURCEFUL_ROBOT_G, ResourcefulRobotScript),
        (AUTO_REVEILLE, AutoReveilleScript),
        (AUTO_REVEILLE_G, AutoReveilleScript),
        # ── E 类 ──
        (ELITE_NAVIGATOR, EliteNavigatorScript),
        (ELITE_NAVIGATOR_G, EliteNavigatorScript),
        (SACRIFICIAL_WRATHGUARD, SacrificialWrathguardScript),
        (SACRIFICIAL_WRATHGUARD_G, SacrificialWrathguardScript),
        (VICTORIOUS_GEOMANT, VictoriousGeomantScript),
        (VICTORIOUS_GEOMANT_G, VictoriousGeomantScript),
        (SEWER_ESCAPEE, SewerEscapeeScript),
        (SEWER_ESCAPEE_G, SewerEscapeeScript),
        (SHOALFIN_MYSTIC, ShoalfinMysticScript),
        (SHOALFIN_MYSTIC_G, ShoalfinMysticScript),
    ]
    registered: list[str] = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
