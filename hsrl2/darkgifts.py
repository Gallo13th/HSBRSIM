"""S14 Dark Gifts — 数据表 + 纯过滤/匹配函数（无副作用、无随机）。

权威信源（冲突时上层胜出）:
  1. data/bg_dark_gifts.json（hsdata CardDefs.xml 生成）— 数值/关键词
  2. 官方 36.2 dev post "Dark Gifts of Dalaran" — 可用窗口/提供限制/tier 曲线
  3. 36.2.1 hotfix — Charisma 窗口 7+ → 6-9、Steady Growth 窗口 → 3-5、
     Battle Scars / Death's Embrace / Spell Siphon 弱化版 max turn 10、
     计数类三选一"只给已触发次数最多的一类（并列都给）"、
     Hostility 增加 Venomous/Poisonous 随从禁令

本模块只做数据与过滤；随机抽样（game.rng）与效果分派（apply_dark_gift）
在 game.py。所有 AMBIGUOUS 点见函数内注释与作业报告。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple

import hsrl2.constants as C
from hsrl2.tags import GameTag, Race

if TYPE_CHECKING:
    from hsrl2.db import CardDB
    from hsrl2.defs import CardDef
    from hsrl2.entity import Entity
    from hsrl2.pools import MinionPool
    from hsrl2.rng import GameRNG

# ── card_id 常量（data/bg_dark_gifts.json 实际 id，43 张全部入册）──

_P = "BG36_MidGameEffect_"

OFFENSIVE_SACRIFICE = _P + "000t"        # +10 Attack. DR: 攻击力给另一友方
DEFENSIVE_SACRIFICE = _P + "000t2"       # +10 Health. DR: 最大生命给另一友方
ECHOING_VOICE = _P + "000t10"            # EoT 触发自身战吼
DOUBLE_VISION = _P + "000t11"            # Get an extra copy of this
PERSISTING_HORROR = _P + "000t12"        # Reborn，满状态复活
HARPYS_TALONS = _P + "000t13"            # Divine Shield + Windfury
GILDING = _P + "000t14"                  # 金色但无三连奖励
TORETHS_BLESSING = _P + "000t15"         # 圣盾需 3 次击破
JAWS_OF_DEATH = _P + "000t16"            # SoC 触发自身亡语
REPLICATION = _P + "000t18"              # 每 2 回合 EoT plain copy 入手
TIME_TURNING = _P + "000t21"             # EoT 效果也在 SoT 触发
AMALGAMATION = _P + "000t22"             # 获得全部种族
BATTLE_SCARS_BIG = _P + "000t28"         # +3/+3 × 已触发战吼数
BATTLE_SCARS_SMALL = _P + "000t28t"      # +2/+2 × 已触发战吼数
DEATHS_EMBRACE_BIG = _P + "000t29"       # +2/+2 × 已触发亡语数
DEATHS_EMBRACE_SMALL = _P + "000t29t"    # +1/+1 × 已触发亡语数
SPELL_SIPHON_BIG = _P + "000t30"         # +3/+3 × 本局酒馆法术数
SPELL_SIPHON_SMALL = _P + "000t30t"      # +2/+2 × 本局酒馆法术数
CHARISMA = _P + "000t3"                  # Rally: 获取最常见种族随机随从
INCUBATION = _P + "000t4"                # +4/+4，2 回合后翻倍
MYSTIC_ESSENCE = _P + "000t5"            # DR: 随机酒馆法术入手
TARECGOSAS_BLESSING = _P + "000t50"      # 战斗增益永久保留
STEADY_GROWTH = _P + "000t51"            # EoT +X/+Y（按获得回合）
FRESH_PERSPECTIVE = _P + "000t52"        # DR: 2 次免费刷新
INVULNERABILITY = _P + "000t60"          # 攻击时免疫
GOLEMANCY = _P + "000t61"                # DR: 召唤同属性 Golem
SUNKEN_PERSISTENCE = _P + "000t62"       # 该随从的 Spellcraft 永久
DEXTERITY_SMALL = _P + "000t64"          # 每打一张牌 +2/+2
DEXTERITY_BIG = _P + "000t64t"           # 每打一张牌 +4/+4
POLARIZATION = _P + "000t65"             # EoT 磁力吸附随机机械
DEMONOLOGY = _P + "000t66"               # Rally: 下 3 次刷新附加 Fodder
TOXICITY = _P + "000t69"                 # Venomous
RESISTANCE = _P + "000t7"                # SoC 生命翻倍
HOSTILITY = _P + "000t71"                # SoC 攻击翻倍
TITANIC_STRENGTH = _P + "000t72"         # +1000 攻击
FORTITUDE = _P + "000t73"                # +5/+5（XML 文本，见下）
SHARPENED_SWORD = _P + "000t74"          # 每打一张牌 +3 攻击
TOUGHENED_SHIELD = _P + "000t75"         # 每打一张牌 +3 生命
FURTIVENESS = _P + "000t79"              # Stealth
CONSANGUINITY = _P + "000t80"            # Rally: 2 颗 Blood Gem
TRANSCENDENCE = _P + "000t81"            # SoC 属性三倍
AFFINITY = _P + "000t82"                 # 每 2 回合 EoT 获取本种族随机随从
ADMIRATION = _P + "000t9"                # SoC 获得左侧随从攻击力

# ── A1. 可用窗口表（min_turn, max_turn；None = 无上限）──
# 来源: 官方 36.2 dev post + 36.2.1 hotfix:
#   - Charisma (6,9)【hotfix: 原 7-None 改 6-9】
#   - Steady Growth (3,5)【hotfix 收窄】
#   - Battle Scars +2/+2 / Death's Embrace +1/+1 / Spell Siphon +2/+2
#     弱化版 max 6【hotfix: 原 max 10 收窄 → 表值 (4,6)】
GIFT_WINDOWS: dict[str, tuple[Optional[int], Optional[int]]] = {
    STEADY_GROWTH: (3, 5),
    FORTITUDE: (3, 3),
    AFFINITY: (3, 4),
    SHARPENED_SWORD: (3, 5),
    TOUGHENED_SHIELD: (3, 5),
    TIME_TURNING: (3, 9),
    SUNKEN_PERSISTENCE: (3, None),
    HARPYS_TALONS: (3, None),
    JAWS_OF_DEATH: (3, None),
    FURTIVENESS: (4, None),
    CONSANGUINITY: (4, 5),
    FRESH_PERSPECTIVE: (4, 5),
    REPLICATION: (4, 6),
    BATTLE_SCARS_SMALL: (4, 6),
    DEATHS_EMBRACE_SMALL: (4, 6),
    SPELL_SIPHON_SMALL: (4, 6),
    GILDING: (4, 8),
    DOUBLE_VISION: (5, None),
    TORETHS_BLESSING: (5, None),
    AMALGAMATION: (5, None),
    DEMONOLOGY: (5, 8),
    POLARIZATION: (5, 8),
    MYSTIC_ESSENCE: (5, 8),
    TARECGOSAS_BLESSING: (6, None),
    DEXTERITY_SMALL: (6, 7),
    INCUBATION: (6, 8),
    ECHOING_VOICE: (6, None),
    OFFENSIVE_SACRIFICE: (6, 9),
    DEFENSIVE_SACRIFICE: (6, 9),
    TRANSCENDENCE: (7, None),
    BATTLE_SCARS_BIG: (7, None),
    DEATHS_EMBRACE_BIG: (7, None),
    SPELL_SIPHON_BIG: (7, None),
    ADMIRATION: (7, None),
    TOXICITY: (7, None),
    CHARISMA: (6, 9),          # hotfix 36.2.1: 7-None → 6-9
    RESISTANCE: (7, 10),
    HOSTILITY: (7, 10),
    DEXTERITY_BIG: (8, 9),
    GOLEMANCY: (9, 10),
    PERSISTING_HORROR: (10, None),
    TITANIC_STRENGTH: (11, None),
    INVULNERABILITY: (12, None),
}

# ── A2. Steady Growth 数值表（dev post 原文; hotfix 后窗口 3-5，
#    6 档保留数据以防回滚）──
STEADY_GROWTH_VALUES: dict[int, tuple[int, int]] = {
    3: (1, 2), 4: (2, 2), 5: (3, 3), 6: (4, 4),
}

# ── 稀有 gift（dev post: Gilding / Persisting Horror / Titanic Strength /
#    Invulnerability 更稀有）→ 权重 0.5，供加权抽样 ──
RARE_GIFTS = frozenset({GILDING, PERSISTING_HORROR, TITANIC_STRENGTH,
                        INVULNERABILITY})
RARE_GIFT_WEIGHT = 0.5

# ── DEFERRED: 引擎缺 Magnetic 合并子系统，无法精确实现 Polarization
#    （"At the end of your turn, Magnetize a random Mech to this"）。
#    apply_dark_gift 对其记审计日志、不生效——唯一允许的未实现形态。──
DEFERRED_GIFTS = frozenset({POLARIZATION})

# ── 数值型 gift 集合（亡语随从禁; 例外见下）──
_STAT_GIFTS = frozenset({
    STEADY_GROWTH, FORTITUDE, SHARPENED_SWORD, TOUGHENED_SHIELD,
    BATTLE_SCARS_SMALL, BATTLE_SCARS_BIG, SPELL_SIPHON_SMALL, SPELL_SIPHON_BIG,
    DEXTERITY_SMALL, DEXTERITY_BIG, INCUBATION,
    OFFENSIVE_SACRIFICE, DEFENSIVE_SACRIFICE, TITANIC_STRENGTH,
})
# dev post: 亡语随从不可获数值型 gift，例外 = Sharpened Sword 与
# Death's Embrace（两种版本）
_DEATHRATTLE_STAT_ALLOWED = frozenset(
    {SHARPENED_SWORD, DEATHS_EMBRACE_SMALL, DEATHS_EMBRACE_BIG})
# dev post: 战吼/Choose One 随从只可获这四个
_BATTLECRY_MINION_ALLOWED = frozenset(
    {DOUBLE_VISION, REPLICATION, GILDING, ECHOING_VOICE})

# ── 随从侧黑名单（dev post 明示不提供的随从; 按名字精确匹配，
#    Leeroy 按子串匹配池内 BGS 版 "Leeroy the Reckless"）──
_BLACKLIST_NAMES = frozenset({"Deadly Spore", "Stitched Salvager"})

_EOT_TEXT_RE = re.compile(r"end of\b.{0,24}\bturns?\b", re.IGNORECASE)


# ── CardDef 谓词（纯函数，供过滤复用）──

def _text(d: "CardDef") -> str:
    return (d.text or "").lower()


def is_battlecry_minion(d: "CardDef") -> bool:
    """战吼随从: XML keywords 权威标签。"""
    return "battlecry" in d.keywords


def is_choose_one_minion(d: "CardDef") -> bool:
    """Choose One: 无独立 tag，文本检测（dev post 限制同样适用）。"""
    return "choose one" in _text(d)


def is_deathrattle_minion(d: "CardDef") -> bool:
    return "deathrattle" in d.keywords


def is_avenge_minion(d: "CardDef") -> bool:
    return d.avenge_target is not None


def is_activate_minion(d: "CardDef") -> bool:
    return d.activate_cost is not None


def is_spellcraft_minion(d: "CardDef") -> bool:
    return d.spellcraft_id is not None or "spellcraft" in _text(d)


def is_eot_minion(d: "CardDef") -> bool:
    """带 end-of-turn 效果文本的随从（Time Turning 资格）。"""
    return bool(_EOT_TEXT_RE.search(d.text or ""))


def has_race(d: "CardDef") -> bool:
    """有种族（Race.NONE/INVALID=0 视为无种族; Race.ALL 视为有）。"""
    return d.race is not None and d.race != 0


def _race(name: str) -> Race:
    return Race[name]


def _race_active(minion_pool: "MinionPool", race: Race) -> bool:
    """本局该种族是否激活（active_races None = 全部可用）。"""
    if minion_pool is None or minion_pool.active_races is None:
        return True
    return race in minion_pool.active_races


def _blacklisted(d: "CardDef") -> bool:
    name = d.name or ""
    if name in _BLACKLIST_NAMES:
        return True
    if "leeroy" in name.lower():
        # dev post 黑名单 Leeroy（池内为 "Leeroy the Reckless" BG23_318）
        return True
    return False


# ── A4. 随从侧资格 ──

def eligible_minions(db: "CardDB", minion_pool: "MinionPool",
                     hero: "Entity", turn: int) -> List[str]:
    """Dark Gift 可提供的随从 card_id 列表。

    过滤条件（全部出处: 官方 36.2 dev post）:
      1. tier 曲线: turn3:[2] 4:[2,3] 5:[3] 6:[3,4] 7:[4] 8:[4,5]
         9:[4,5,6] 10:[5,6] 11+:[6]（constants.DARK_GIFT_TIERS）
      2. 池剩余量 > 0（RULES §2.4 池中没有的随从不可被获取）
      3. 本局激活种族（active_races; NONE/ALL 永远可用）
      4. turn < 5: 不提供战吼 / Choose One 随从
      5. 不提供 Magnetic 随从
      6. 不提供 "When you sell this" 文本随从
      7. 不提供手牌滞留型（文本含 "in your hand"）
      8. 硬编码黑名单: Leeroy（名字子串）/ Deadly Spore / Stitched Salvager
    """
    tiers = C.DARK_GIFT_TIERS.get(turn, C.DARK_GIFT_TIERS_DEFAULT)
    out: List[str] = []
    for d in db.pool_minions():
        if d.tech_level not in tiers:
            continue
        if minion_pool.available(d.id) <= 0:
            continue
        if not minion_pool._race_ok(d):
            continue
        if turn < 5 and (is_battlecry_minion(d) or is_choose_one_minion(d)):
            continue
        if "magnetic" in d.keywords:
            continue
        t = _text(d)
        if "when you sell" in t:
            continue
        if "in your hand" in t:
            continue
        if _blacklisted(d):
            continue
        out.append(d.id)
    return out


# ── A3. gift 侧配对资格 ──

def eligible_gifts(db: "CardDB", minion_def: "CardDef", *, turn: int,
                   hero: "Entity", lobby_dragons_ok: bool,
                   minion_pool: "MinionPool",
                   offering_min_tier: Optional[int] = None
                   ) -> List[Tuple[str, float]]:
    """给定随从定义，返回合法 (gift_id, weight) 列表。

    每条限制的出处标注在各分支。权重: 普通 1.0，稀有 gift 0.5
    （dev post: Gilding / Persisting Horror / Titanic Strength /
    Invulnerability 更稀有——官方未公布具体权重，0.5 为约定值,
    AMBIGUOUS: 稀有度权重未公开）。

    offering_min_tier: 当前提供三选一中最低 tier（Gilding 仅给当次提供中
    tier 最低的随从——依赖提供集，由 game.use_dark_gift 传入；
    None = 提供集未知 → Gilding 不合格）。
    """
    md = minion_def
    has_dr = is_deathrattle_minion(md)
    is_bc = is_battlecry_minion(md) or is_choose_one_minion(md)
    md_race_all = md.race is not None and md.race.name == "ALL"

    def race_is(name: str) -> bool:
        return md.race is not None and md.race.name == name

    # 计数类资格（36.2.1: Battle Scars / Death's Embrace / Spell Siphon
    # 需对应计数 > 0，且三类中只提供已触发次数最多的一类; 并列都给）
    n_bc = hero.get(GameTag.COUNTER_BATTLECRIES, 0) if hero else 0
    n_dr = hero.get(GameTag.COUNTER_DEATHRATTLES, 0) if hero else 0
    n_sp = hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0) if hero else 0
    top = max(n_bc, n_dr, n_sp)

    out: List[Tuple[str, float]] = []
    for gift_id, (tmin, tmax) in GIFT_WINDOWS.items():
        if tmin is not None and turn < tmin:
            continue
        if tmax is not None and turn > tmax:
            continue

        ok = True
        # ---- 逐 gift 随从匹配限制（dev post）----
        if gift_id == SUNKEN_PERSISTENCE:
            ok = is_spellcraft_minion(md)            # 仅 Spellcraft 随从
        elif gift_id == HARPYS_TALONS:
            # 无随从侧限制; dev post: 在 Rally 随从上权重更高——
            # 官方未公布权重数值，本引擎不实现该加权
            # （AMBIGUOUS: Rally 加权数值未公开）
            ok = True
        elif gift_id == JAWS_OF_DEATH:
            ok = has_dr                              # 仅亡语随从
        elif gift_id == AFFINITY:
            ok = has_race(md)                        # 仅有种族随从
        elif gift_id == SHARPENED_SWORD:
            ok = not is_avenge_minion(md)            # 不可给 Avenge 随从
        elif gift_id == TOUGHENED_SHIELD:
            # Quilboar/Naga 均未激活的局不可提供
            ok = (_race_active(minion_pool, _race("QUILBOAR"))
                  or _race_active(minion_pool, _race("NAGA")))
        elif gift_id == TIME_TURNING:
            ok = is_eot_minion(md)                   # 仅 end-of-turn 文本随从
        elif gift_id == FURTIVENESS:
            ok = is_avenge_minion(md)                # 仅 Avenge 随从
        elif gift_id == CONSANGUINITY:
            ok = race_is("QUILBOAR") or md_race_all  # 仅 Quilboar（含全种族）
        elif gift_id == GILDING:
            # 仅当次提供中 tier 最低的随从，且不可给 Activate 随从
            ok = (offering_min_tier is not None
                  and md.tech_level == offering_min_tier
                  and not is_activate_minion(md))
        elif gift_id == TORETHS_BLESSING:
            ok = "divine_shield" in md.keywords      # 仅圣盾随从
        elif gift_id == AMALGAMATION:
            ok = not has_race(md)                    # 仅无种族随从
        elif gift_id == DEMONOLOGY:
            ok = race_is("DEMON") or md_race_all     # 仅恶魔（含全种族）
        elif gift_id == POLARIZATION:
            # 仅机械（含全种族）且玩家 tavern_tier >= 3
            ok = ((race_is("MECH") or md_race_all)
                  and hero is not None
                  and hero.get(GameTag.TAVERN_TIER, 1) >= 3)
        elif gift_id == TARECGOSAS_BLESSING:
            ok = race_is("DRAGON") or md_race_all    # 仅龙（含全种族）
        elif gift_id in (DEXTERITY_SMALL, DEXTERITY_BIG, INCUBATION,
                         OFFENSIVE_SACRIFICE, DEFENSIVE_SACRIFICE,
                         PERSISTING_HORROR):
            ok = has_race(md)                        # 仅有种族随从
        elif gift_id == GOLEMANCY:
            # 仅有种族随从; 另禁 Stitched Salvager（dev post 黑名单）
            ok = has_race(md) and (md.name or "") != "Stitched Salvager"
        elif gift_id == ECHOING_VOICE:
            ok = is_battlecry_minion(md)             # 仅战吼随从
        elif gift_id == TRANSCENDENCE:
            ok = not has_race(md)                    # 仅无种族随从
        elif gift_id == TOXICITY:
            # 仅鱼人（含全种族）且无 Venomous/Poisonous
            ok = ((race_is("MURLOC") or md_race_all)
                  and "venomous" not in md.keywords
                  and "poisonous" not in md.keywords)
        elif gift_id == CHARISMA:
            # 不可给嘲讽 / Avenge 随从; hotfix 36.2.1: Tier 7 随从不可
            ok = ("taunt" not in md.keywords
                  and not is_avenge_minion(md)
                  and md.tech_level < 7)
        elif gift_id == RESISTANCE:
            # 不可给野兽/亡灵/无种族; lobby 禁: 无龙的局不提供
            # AMBIGUOUS: "龙局禁" 按"无龙的局禁"实现（与 Toughened Shield
            # "未激活的局不可提供"同构）; 另一读法"有龙的局禁"列于报告
            ok = (not race_is("BEAST") and not race_is("UNDEAD")
                  and has_race(md) and lobby_dragons_ok)
        elif gift_id == HOSTILITY:
            # 不可给 Avenge / 无种族; 36.2.1: Venomous/Poisonous 随从禁
            ok = (not is_avenge_minion(md) and has_race(md)
                  and "venomous" not in md.keywords
                  and "poisonous" not in md.keywords)
        elif gift_id == TITANIC_STRENGTH:
            ok = not (race_is("DRAGON") or md_race_all)  # 不可给龙（含全种族）
        elif gift_id == INVULNERABILITY:
            ok = "taunt" not in md.keywords and has_race(md)  # 不可给嘲讽/无种族
        elif gift_id in (BATTLE_SCARS_SMALL, BATTLE_SCARS_BIG):
            ok = n_bc > 0 and n_bc == top            # 战吼计数门（36.2.1）
        elif gift_id in (DEATHS_EMBRACE_SMALL, DEATHS_EMBRACE_BIG):
            ok = n_dr > 0 and n_dr == top            # 亡语计数门（36.2.1）
        elif gift_id in (SPELL_SIPHON_SMALL, SPELL_SIPHON_BIG):
            ok = n_sp > 0 and n_sp == top            # 酒馆法术计数门（36.2.1）

        if not ok:
            continue

        # ---- 全局配对规则（dev post）----
        if has_dr and gift_id in _STAT_GIFTS \
                and gift_id not in _DEATHRATTLE_STAT_ALLOWED:
            continue
        if is_bc and gift_id not in _BATTLECRY_MINION_ALLOWED:
            continue

        weight = RARE_GIFT_WEIGHT if gift_id in RARE_GIFTS else 1.0
        out.append((gift_id, weight))
    return out


def most_common_board_race(hero: "Entity", rng: "GameRNG"):
    """棋盘最常见种族（Turn>=6 的提供保证用）。

    - 只统计有种族的棋盘随从; Race.ALL（全种族）计入自身桶、
      不参与众数匹配（AMBIGUOUS: 全种族随从对"最常见种族"的
      贡献官方未说明，按不计入处理）
    - 并列时 rng 任选其一（AMBIGUOUS: 官方并列打破规则未公布）
    - 无有种族随从 → None（跳过保证）
    """
    counts = Counter()
    for m in hero.board:
        race = m.race
        if race is None or race.name in ("NONE", "ALL", "INVALID"):
            continue
        counts[race] += 1
    if not counts:
        return None
    top = max(counts.values())
    modes = [r for r, n in counts.items() if n == top]
    if len(modes) == 1:
        return modes[0]
    return rng.choice(modes, label="dark_gift_common_race")


def weighted_choice(rng: "GameRNG",
                    options: Sequence[Tuple[str, float]]) -> str:
    """[(gift_id, weight)] 加权抽取（权重和为 0 时由调用方保证非空）。"""
    total = sum(w for _, w in options)
    r = rng.random() * total
    acc = 0.0
    for gid, w in options:
        acc += w
        if r < acc:
            return gid
    return options[-1][0]
