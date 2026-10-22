"""批次 family_races — RACES 家族类型身份改写（2026-09-21，4 张 Portrait）。

作业范围（ENGINE_BACKLOG §A1/§B2-4 与「C 组 RACES 权威核查」C 组 4 张）:
  `BG30_MagicItem_418` Bronzebeard Portrait — "Your Brann Bronzebeards are
      both Murlocs and Dragons."
  `BG32_MagicItem_179` Drakkari Portrait — "Your Drakkari Enchanters are
      both Mechs and Elementals."
  `BG30_MagicItem_971` Enforcer Portrait — "Your Lightfang Enforcers have
      all minion types."
  `BG30_MagicItem_825` Smuggler Portrait — "Your Whelp Smugglers are
      Dragons." + "Set its stats to 12/12."

═══════════════════════════════════════════════════════════════════════
权威（项目所有者权威序: wiki 详细说明 > 卡面自然语言解读）
═══════════════════════════════════════════════════════════════════════
[AUTHORITY FOUND] 类型身份模型（wiki 详细说明，非卡面推断）:
  - `Minion` revid **817925**（hearthstone.wiki.gg/wiki/Minion）:
    "Minions in Hearthstone can have one or two of the following minion
    types"; "Previously, minions could only have one minion type ... dual-
    type minions were introduced, allowing a minion to have two types. In
    any such case, these minions **benefit from the effects of both
    types**."; "Alternatively, minions can either have all minion types
    listed above at once, or no minion types at all: All — These minions
    benefit from and are affected by every type effect in the game.
    General — These minions do not benefit from any specific type effects."
  - `Multi-type minion` revid **855346**:
    "Multi-types are always additions, never exclusions."（Furious Felfin:
    "Murloc Warleader grants it +2 attack, and it can be drawn from Sense
    Demons."）; "If needed, multi-type minions can take on the role of
    either minion type."（N'Zoth 例）
  - `All` revid **893299**: "All minions can be found from random effects
    and Discover options that cover any specific type."; "All minions can
    have multiple type synergies for various types active at the same
    time."
  → 引擎表示: `CardDef.races`（CARDRACE ∪ per-race tag）/ `Minion.races`
    （实例集合）/ `Minion.has_race()`; `Race.ALL` 展开为 `STANDARD_RACES`
    （N6 表示契约 = 集合，不再用"单值匹配一切"哨兵）。

[AUTHORITY FOUND] 家族类型改写的**作用域**（wiki 详细说明）:
  - `Patch 30.2.0.205267` revid **814123**（Smuggler Portrait 条目下的
    官方 Dev Comment）: "This applies to Whelp Smugglers you see in the
    **Tavern or Discover** as well, not just the ones in your warband."
  → 读点 = `Minion.races`（owner 视角: 棋盘/手牌/酒馆）+
    `Game.effective_races`（酒馆/发现候选的 CardDef 过滤）; 对手与
    共享池本体不受影响。418/179/971 与 825 同文本族（"Your X are …"），
    按同一 owner 作用域落地（wiki 仅对 825 有明文 Dev Comment——
    对另三张卡这是"同文本族 + 卡面自然语言"的延伸，已在
    `docs/agents/ENGINE_BACKLOG.md` §C 记档）。

[AUTHORITY FOUND] 逐卡家族类型数（卡面逐字 + `data/bg_trinkets.json`）:
  - 418: "both Murlocs and Dragons" = {MURLOC, DRAGON}（卡面逐字）。
  - 179: "both Mechs and Elementals" = {MECH, ELEMENTAL}（卡面逐字）。
  - 971: "have all minion types" = ALL（卡面逐字 → 全 10 族）。
  - 825: "are Dragons" = {DRAGON}（卡面逐字; 单类型）。

载荷状态（AC-2: 四张载荷本体均**无类型**，故改写 = 完整身份）:
  `BG_LOE_077` Brann（+金色 `TB_BaconUps_045`）/ `BG26_ICC_901` Drakkari
  Enchanter（+金色）/ `BGS_009` Lightfang Enforcer（+金色
  `TB_BaconUps_082`）/ `BG21_013` Whelp Smuggler（+金色 `BG21_013_G`）
  ——全部已注册（`batch_doublers` / `batch_payload_minions` /
  `batch_stats_gained`）。关联卡一律走数据链
  `CardDef.evolution_card_id` → `CardDB.by_dbf`（零硬编码卡 id）。

**本批 4/4 CORRECT**（每张 = 数据链交付载荷 + 家族类型改写读取点）;
逐卡 Test 见各类 docstring。

**未随本批落地的相邻问题（精确记档，非静默）**
  - N3 饰品类型关联（RULES §7.4.2 T6/T9/Menagerie 阈值）: 多类型 / ALL
    随从对"2 个 / 3 个某类型"的贡献**无 wiki 明文**；`_type_association`
    维持既有语义（排除 ALL、按主类型计数），不在本批改动。
  - 饰品**可提供性**（wiki 渲染页 Availability）: Drakkari Portrait
    revid 921179 "This trinket can only appear in lobbies where Mechs or
    Elementals are present."（`BACON_SUBSET_MECH/ELEMENTALS`）; 425/179/
    971 的 "currently not available in games" 与"lobby 限定"是**饰品
    商店池**特性，与本批类型身份改写正交，未实现（不改全量饰品报价）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.actions.discover import _pool_candidates
from hsrl2.game import GameStateError
from hsrl2.scripts.batches.batch_spells2 import SetStats
from hsrl2.tags import GameTag, Race

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# ── 饰品 id（本批 4 张；数据核实 2026-09-21）──
BRONZEBEARD_PORTRAIT = "BG30_MagicItem_418"
DRAKKARI_PORTRAIT = "BG32_MagicItem_179"
ENFORCER_PORTRAIT = "BG30_MagicItem_971"
SMUGGLER_PORTRAIT = "BG30_MagicItem_825"

# ── 家族类型身份（卡面逐字）──
BRONZEBEARD_RACES = (Race.MURLOC, Race.DRAGON)
DRAKKARI_RACES = (Race.MECH, Race.ELEMENTAL)
#: "have all minion types" → `Race.ALL` 经 `race_set` 展开为全 10 族。
ENFORCER_RACES = (Race.ALL,)
SMUGGLER_RACES = (Race.DRAGON,)

#: Smuggler Portrait "Set its stats to 12/12"（卡面字面量，CardDef 无
#: 模板参数——`BG30_MagicItem_825` num(0..4) 全 None）。
SMUGGLER_STATS = 12


def _hero(ctx) -> "Hero | None":
    return (ctx or {}).get("hero")


def _related_or_raise(game: "Game", trinket_id: str):
    rel = game.trinket_related_card(trinket_id)
    if rel is None:
        raise GameStateError(
            f"{trinket_id}: evolution_card_id broken data chain")
    return rel


def _random_battlecry_minion(game: "Game", hero: "Hero") -> None:
    """池感知"Get a random **Battlecry** minion"（占池 + 满手排队）。

    候选 = `_pool_candidates(game, hero=hero)`（剩余量 / 本局禁用种族 /
    存在档 + 英雄视角类型身份）∩ `CardDef.keywords` 含 "battlecry"。
    池中无候选 → 落空（不近似）。
    """
    cands = [cid for cid in _pool_candidates(game, hero=hero)
             if "battlecry" in game.db.get(cid).keywords]
    if not cands:
        return
    cid = game.rng.choice(cands, label="bronzebeard_portrait_battlecry")
    if not game.minion_pool.acquire(cid):
        return
    game.pending_hand_add(hero, game.create_minion(cid, controller=hero))


# ══════════════════ BG30_MagicItem_418 Bronzebeard Portrait ══════════════════


class BronzebeardPortraitScript:
    """
    Natural language: [x]Get a Brann Bronzebeard and a random **Battlecry**
    minion. Your Brann Bronzebeards are both Murlocs and Dragons.

    Formal spec:
      1. on_bind: `game.grant_trinket_related_card(hero, source.card_id)`
         ——数据链 `evolution_card_id=96786` → `BG_LOE_077`（RULES §7.4.6）
      2. 第二条款: "a random **Battlecry** minion" → 池感知随机（`_pool_
         candidates` ∩ `CardDef.keywords` 含 "battlecry"；占池 + 满手排队
         RULES §3.3/§2.4）。候选空 → 落空
      3. 第三条款: `game.add_family_races(hero, BG_LOE_077, {MURLOC,
         DRAGON}, source=source)` ——家族类型改写读取点（`Minion.races` /
         `Game.effective_races`）。金色 `TB_BaconUps_045` 经基础卡 id
         归一同族命中; source 离场即失效（同 `add_family_flag`）
      4. 权威: 卡面逐字（两类型枚举）; 作用域见模块 docstring（825 的
         官方 Dev Comment 同文本族延伸）

    Test: test_batch_family_races.py — 真实 `grant_trinket` 后:
      交付 Brann（数据链）/ 交付一张 Battlecry 随从 / Brann（棋盘）同时
      具有 MURLOC 与 DRAGON 身份（轻量真实消费者: 种族光环同时命中
      鱼人光环与龙光环）/ 金色 Brann 同族命中 / 对照无饰品 = 无类型 /
      对手 Brann 不受影响 / 变异探针。

    Params: 无模板参数（BG30_MagicItem_418 num(0..4) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        rel = _related_or_raise(game, source.card_id)
        game.grant_trinket_related_card(h, source.card_id)
        _random_battlecry_minion(game, h)
        game.add_family_races(h, rel.id, BRONZEBEARD_RACES, source=source)
        return None


# ══════════════════ BG32_MagicItem_179 Drakkari Portrait ══════════════════


class DrakkariPortraitScript:
    """
    Natural language: [x]Get a Drakkari Enchanter. Your Drakkari Enchanters
    are both Mechs and Elementals.

    Formal spec:
      1. on_bind: 数据链 `evolution_card_id=101314` → `BG26_ICC_901` 交付
         （池随从 T5，占池; RULES §7.4.6）
      2. `game.add_family_races(hero, BG26_ICC_901, {MECH, ELEMENTAL},
         source=source)`——家族类型改写; 金色同族
      3. 真实消费者: "Your Elementals have +X/+Y this game"
         （`ApplyRaceAura` + `Minion._aura_atk/_aura_health`）现命中
         Drakkari Enchanter（身份集合含 ELEMENTAL）
      4. 权威: 卡面逐字两类型; wiki 渲染页 revid 921179 仅给出
         Availability/Notes（"currently not available in games" /
         "cannot be offered more than 1"）——与本卡类型改写无关

    Test: test_batch_family_races.py — 真实 `grant_trinket` 交付
      Drakkari Enchanter / 真实 `ApplyRaceAura(ELEMENTAL, +2/+2)` 后其
      atk 生效（对照无饰品不生效）/ 金色同族 / 对手不受影响 /
      变异探针（单类型 / 空集合 / 错家族 id）。

    Params: 无模板参数（BG32_MagicItem_179 num(0..4) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        rel = _related_or_raise(game, source.card_id)
        game.grant_trinket_related_card(h, source.card_id)
        game.add_family_races(h, rel.id, DRAKKARI_RACES, source=source)
        return None


# ══════════════════ BG30_MagicItem_971 Enforcer Portrait ══════════════════


class EnforcerPortraitScript:
    """
    Natural language: [x]Get a Lightfang Enforcer. Your Lightfang Enforcers
    have all minion types.

    Formal spec:
      1. on_bind: 数据链 `evolution_card_id=59707` → `BGS_009` 交付
         （池外专属卡，零池操作; RULES §7.4.6）
      2. `game.add_family_races(hero, BGS_009, {Race.ALL}, source=source)`
         ——"have all minion types" = `Race.ALL` → `race_set` 展开为全
         10 标准种族（wiki `All` revid 893299）; 金色 `TB_BaconUps_082`
         同族
      3. 真实消费者: "Discover a <race>" / 酒馆种族白名单 / 种族光环 /
         `_each_type_buffs`（"of each type"）现把 Lightfang Enforcer
         视为每一类型（多层命中——`All` 先例 AC-6）

    Test: test_batch_family_races.py — 真实 `grant_trinket` 后
      Lightfang Enforcer 身份 = 全 10 族（`has_race` 逐族 True）/
      真实 `ApplyRaceAura(DRAGON, +3/+3)` 与 `(MECH, +3/+3)` 同时命中 /
      `_pool_candidates(race=DRAGON, hero=...)` 可见 ALL 家族 / 金色同族 /
      对照无饰品（无类型 → 全部 False）/ 变异探针（ALL 当单值）。

    Params: 无模板参数（BG30_MagicItem_971 num(0..4) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        rel = _related_or_raise(game, source.card_id)
        game.grant_trinket_related_card(h, source.card_id)
        game.add_family_races(h, rel.id, ENFORCER_RACES, source=source)
        return None


# ══════════════════ BG30_MagicItem_825 Smuggler Portrait ══════════════════


class SmugglerPortraitScript:
    """
    Natural language: [x]Get a Whelp Smuggler. Set its stats to 12/12.
    Your Whelp Smugglers are Dragons.

    Formal spec:
      1. on_bind: 数据链 `evolution_card_id=72072` → `BG21_013` 交付**并
         取回该副本实体**（`grant_trinket_related_card_entity`），随后
         `SetStats(副本, 12, 12)`——覆盖式设属性（清除附魔 + BASE 覆盖，
         `batch_spells2.SetStats` 语义; 文本字面量 12/12）
      2. `game.add_family_races(hero, BG21_013, {DRAGON}, source=source)`
         ——单类型家族改写; 金色 `BG21_013_G` 同族命中
      3. 作用域（wiki `Patch 30.2.0.205267` revid 814123 官方 Dev
         Comment）: "This applies to Whelp Smugglers you see in the
         **Tavern or Discover** as well, not just the ones in your
         warband." → `Minion.races`（棋盘/手牌/酒馆）+ `Game.effective_
         races`（发现候选）。对手 / 共享池本体不受影响
      4. 真实消费者: 载荷 `BG21_013` 自身 "Whenever a friendly **Dragon**
         gains Attack, give it +1 Health"（`batch_stats_gained`）现按
         类型身份命中本家族军

    Test: test_batch_family_races.py — 真实 `grant_trinket` 后:
      副本为 Whelp Smuggler 且 stats 12/12 / 副本 + 后来入场的同族
      （棋盘）身份含 DRAGON / 真实 `stats_gained`（Whelp 得攻击力）
      触发 +1 生命 / 真实 `refresh_tavern(races={DRAGON})` 白名单下
      Whelp Smuggler 可见（Tavern 作用域）/ 金色 `BG21_013_G` 同族 /
      对照无饰品 = 无类型 / 对手 Whelp 不受影响 / 变异探针。

    Params: 12/12（"Set its stats to 12/12" 卡面字面量，CardDef 无模板
            参数——BG30_MagicItem_825 num(0..4) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        rel = _related_or_raise(game, source.card_id)
        copy = game.grant_trinket_related_card_entity(h, source.card_id)
        if copy is not None:
            game.run_actions(SetStats(copy, SMUGGLER_STATS, SMUGGLER_STATS))
        game.add_family_races(h, rel.id, SMUGGLER_RACES, source=source)
        return None


# ══════════════════ 注册 ══════════════════


def register() -> list[str]:
    """注册本批 4 张 Portrait（RACES 家族类型身份改写）。"""
    from hsrl2.scripts.registry import register as _reg

    _reg(BRONZEBEARD_PORTRAIT, BronzebeardPortraitScript)
    _reg(DRAKKARI_PORTRAIT, DrakkariPortraitScript)
    _reg(ENFORCER_PORTRAIT, EnforcerPortraitScript)
    _reg(SMUGGLER_PORTRAIT, SmugglerPortraitScript)
    return [BRONZEBEARD_PORTRAIT, DRAKKARI_PORTRAIT, ENFORCER_PORTRAIT,
            SMUGGLER_PORTRAIT]
