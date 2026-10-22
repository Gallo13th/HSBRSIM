"""批次 anomalies3 — 异变系统第三批（作业单 2026-09-02）。

异变只分发 `on_bind(game)`（EFFECT_SCRIPT_SOP §11 W1）; 所有每英雄
监听器一律默认参数绑定 `_h=h` 防闭包晚绑定（SOP §12 经典缺陷）;
随机一律走 `game.rng`; 数值优先 `CardDef.num(0/1)`，文本字面量逐处
注明出处。

注册 12 张
═══════════════════════════════════════════════════════════════════════
  - BG32_Anomaly_003 Impressive Foresight: Lesser T5 / Greater T8
    （`hero._trinket_early`，引擎 `_begin_recruit_for` 读取）
  - BG27_Anomaly_100 Big League: 酒馆起始 T3、下限 T3（只有 3~6 存在）、
    +10 护甲
  - BG27_Anomaly_101 What Are the Odds?: 存在档 {1,3,5}（起手 T1、
    升级落点 1→3→5、展示/发现白名单）+ 三连奖励 = 本人档
    （`game._tavern_tier_ladder` / `game._triple_reward_of_own_tier`）
  - BG27_Anomaly_102 How to Even??: 存在档 {2,4,6}（起手 **T2**——T1
    不存在，与 Big League 起始规则同源）+ 三连奖励 = 本人档
  - BG31_Anomaly_104 Rising Current: 升级后 Discover Tier num(1)+
    (turn-1)//num(0) 的酒馆法术（"Improves in {0} turns"）
  - BG31_Anomaly_105 Sin'dorei Mirror: 每回合第一张酒馆法术复制（T5 解锁）
  - BG31_Anomaly_109 Mystical Blossom: 每回合开始 Discover 酒馆法术
    （T3 解锁）
  - BG27_Anomaly_301 False Idols: 三连阈值 2 + 奖励替代 1× Tavern Coin
  - BG27_Anomaly_555 No Place Like Holmes: 每回合 Holmes 式二选一猜测
    （复用 `MurlocHolmesScript`，同一机制已由对抗审查裁定诱饵分布）
  - BG27_Anomaly_575 Eleventh Hour: 战斗中首次致命伤害免疫 +
    下回合 11 金
  - BG27_Anomaly_754 Path of the Treasure-Seeker: 每 num(0) 次刷新
    找到 Golden Monkey
  - BG27_Anomaly_558 Feline Fortune: 其他英雄淘汰时从其战团
    Discover（保留附魔）

DEFERRED 台账（撤注册 — SOP §6b; 逐条附具体缺失引擎原语/信源）
═══════════════════════════════════════════════════════════════════════
第二英雄技能族（**该族三条已解冻，台账订正 2026-09-17**）:
  - ~~BG32_Anomaly_001 Greater Pouches~~ / ~~BG32_Anomaly_002 Lesser
    Pouches~~ / ~~BG31_Anomaly_123 Cosmic Duality~~ — 已由
    `batch_anomalies4` 注册（RULES §9.5 `hero._second_power_id` 槽位
    机制落地后）; 本行原称"引擎无第二英雄技能槽位/分发协议"已过期。
  - BG31_Anomaly_106 Marin's Treasure Box — 全体英雄身份替换为
    Marin the Manager **且**给予第二英雄技能（槽位机制已就绪; 仅剩
    英雄身份替换缺口，见 `batch_anomalies_final` I 组）。

英雄身份/技能替换族（引擎无英雄身份替换 + 每回合重选技能协议）:
  - BG27_Anomaly_720 Nguyen's Shifting Disks — "All heroes are
    Master Nguyen"（Master Nguyen 的每回合换技能被动）。

酒馆等级阶梯族（**已解冻（2026-09-20）**——`_tavern_tier_ladder` +
`_triple_reward_of_own_tier` 两个原语落地后本批注册; 原"权威不足"裁定
的逐条复查见 `docs/ANOMALY_101_102_EVIDENCE.md`「最终裁定」节:
起手档/白名单/奖励档均按卡面自然语言解读落地，升级费按 wiki Tavern
Tier "Upgrading starts at 5 Coins, and each upgrade costs more than the
last." 的**步数序列**计价）:
  - ~~BG27_Anomaly_101 What Are the Odds?~~ — 已注册（存在档 {1,3,5}）
  - ~~BG27_Anomaly_102 How to Even??~~ — 已注册（存在档 {2,4,6}）

Darkmoon Prize 族（`data/` 无 prize 卡池与 tier 映射字段——无法确定
"Tier N Darkmoon Prize" 的候选集）:
  - BG27_Anomaly_716 Up-Prizing
  - BG27_Anomaly_755 A Faire Reward（另需三连奖励池覆写原语）

出售价覆写缺口（**已关闭，台账订正 2026-09-17**）:
  - ~~BG27_Anomaly_721 Uncompensated Upset~~ — 引擎已补英雄级
    `GameTag.SELL_VALUE_OVERRIDE`（`sell_minion` 以 `SELL_VALUE in
    tags` / `SELL_VALUE_OVERRIDE in tags` 存在性判定，0 值不再被吞）
    且 `TAVERN_MINION_COST_OVERRIDE` / `UPGRADE_COST_MOD` 既有 →
    该卡已由 `batch_discount_misc` 注册。

共享发现协议缺失（现 `Discover` 的**预留语义**要求每个选项独占一份池
副本; 8 英雄 × 3 选项 > Tier 6 每卡 `POOL_COPIES_BY_TIER[6]=7` 份 →
"同选项多英雄"要求"一次抽选项、多英雄共享、各自 resolve 占池"新协议）:
  - BG27_Anomaly_723 Summoning of Champions。

手牌持续转换协议缺口（"Each turn this is in your hand, transform it
…" 需要手牌实体的 `start_of_turn` 分发; 接线审计 W1 的 spell 分发集只有
{on_play, target_candidates}; 且 "a higher Tier" 的起点/链条在 wiki
无 Notes——`?action=raw` 仅 dbfId，无信源）:
  - BG31_Anomaly_102 Continuing Education（Evolving Scroll BG31_Anomaly_102t）。

载荷（授予物）本身 DEFERRED（SOP §12 第 14 条——机制就绪 ≠ 可兑现）:
  - BG27_Anomaly_577 No Face, No Case — 授予物 Faceless Manipulator
    `BG_EX1_564` 在 REGISTRY 无脚本（非池卡，"Choose a minion and become
    a copy of it" 无实现）→ 授予的是空转卡。
  - BG31_Anomaly_115 Magic Shop — "Spell Tickets are in the Tavern!" 的
    Spell Ticket 卡在 `data/` 中不存在（全库按名检索无果）。

玩家主动操作原语缺失（引擎无"招募期主动按钮/动作"协议建模）:
  - ~~BG31_Anomaly_117 Emergency Landing~~ **已解冻（2026-09-13）**:
    `MinionPool.purge` 永久移除原语落地后由 `batch_anomalies7` 注册
    （异变 + 载荷技能 `BG31_Anomaly_117t` Eject!）。

语义/数值无信源（SOP §6b 第 4 步；wiki `?action=raw` 无 Notes）:
  - BG27_Anomaly_302 Bring Home the Bacon — Piggy Bank
    `BG27_Anomaly_302t` 文本 "Gain @ Gold." 的 @ 为动态值且
    `data/` 无任何 num 参数/初始值权威。
  - ~~BG27_Anomaly_307 Oops, All EVIL!~~ **已解冻（`batch_anomalies_final`
    注册）**: `num(0)=92` 经 XML 反查 = `Race.NAGA`，"evil" 为风味词
    （多语言文本均作小兵类型名）→ 酒馆种族白名单 `game._tavern_race`。
    原称"与 evil 不符 → 不猜"已过期。
  - BG27_Anomaly_503 The Yogg-iseum — "spin the SAME Wheel of Yogg-Saron"
    的轮盘效果卡池/共享结果协议在 `data/` 与 `hsrl2/` 均不存在。
  - BG27_Anomaly_562 Anomalous Wisdomball — "occasionally get helpful
    Refreshes" 的触发概率无数据权威。
  - BG27_Anomaly_580 Audience's Choice — "one player chooses a card for
    ALL players" 的候选卡池未定义（num(1)=3 = 选项数，但无对应卡集），
    且需跨玩家共享选择协议。
  - BG27_Anomaly_556 Valuation Inflation — 已在 `batch_anomalies` 中
    DEFERRED（语义查无证据 + 31.6.0 移出异变池）。

子系统整体缺失（作业单明示排除）:
  - BG33_Anomaly_001~009 Buddy Button / Quest-Reward 子系统
    （001 Summoning Pact / 002 Spirit of Friendship / 003 Third Nature /
    005 Colorful Camaraderie / 008 Partner in Crime / 009 Amicable
    Amendment; 004/006/007 不在 `bg_anomalies.json`）。
  - BG34_Anomaly_800~809 Timewarp / Chronum 子系统
    （800/801/802/804/805/809 在库; 803/806/807/808 不在
    `bg_anomalies.json`）。

未在候选清单内的其它异变不在本作业单范围。
"""

from __future__ import annotations

import hsrl2.constants as C
from hsrl2.actions import GainGold
from hsrl2.events import (
    HERO_DAMAGE_TAKEN, HERO_ELIMINATED, SPELL_BOUGHT, TAVERN_REFRESH,
    TURN_START, Listener,
)
from hsrl2.game import PendingChoice
from hsrl2.minion import Minion
from hsrl2.tags import CardType, GameTag

# ── 文本字面量（CardDef 无对应模板参数; 逐处注明出处）──

# Impressive Foresight: "Buy your Lesser Trinket on Turn 5, and your
# Greater Trinket on Turn 8."（标准档位 T6/T9 各提前 1 回合）
_IMPRESSIVE_FORESIGHT_TURNS = {"lesser": 5, "greater": 8}

# Big League: "Only Tavern Tiers 3, 4, 5, and 6 exist. Start with 10
# extra Armor."（deDE: "Gasthausstufen 1 und 2 gibt es nicht."——T1/T2
# 不存在 → 起始 Tier 3、抽取下限 Tier 3; 上限 6 = 引擎标准
# `C.TAVERN_MAX_TIER`，无需覆写）
_BIG_LEAGUE_FLOOR_TIER = 3
_BIG_LEAGUE_EXTRA_ARMOR = 10

# What Are the Odds? / How to Even??: "Only Tavern Tiers 1, 3, and 5
# exist." / "Only Tavern Tiers 2, 4, and 6 exist."（文本字面量 → 存在档
# 阶梯; 起手档 = 阶梯首档——Big League"T1/T2 不存在 → 起始 T3"同规则）
_ODDS_TIER_LADDER = (1, 3, 5)
_EVEN_TIER_LADDER = (2, 4, 6)

# 解锁回合（文本字面量）
_SINDOREI_UNLOCK_TURN = 5      # "…(Unlocks on Turn 5.)"
_MYSTICAL_UNLOCK_TURN = 3      # "…(Unlocks on Turn 3.)"

# False Idols: "You only need 2 copies to make minions Golden. They give
# Tavern Coins instead of Triple Rewards."
# 2 = 文本字面量; Tavern Coin 张数沿用同文 Clocksworth
# （batch_hero_econ3.ClocksworthScript: TRIPLE_REWARD_COINS=1，官方
# 36.2 每三连 1 张 Tavern Coin）——同一句文案的同一数值，非新猜。
_FALSE_IDOLS_THRESHOLD = 2
_FALSE_IDOLS_COINS = 1

# Eleventh Hour: "…gain 11 Gold next turn instead."（文本字面量）
_ELEVENTH_HOUR_GOLD = 11


def _card_id_by_name(game, name, card_type=None):
    """按名字查 card_id（禁止凭记忆写 id——SOP §11 教训 5）。"""
    for d in game.db._by_id.values():
        if d.name == name and (card_type is None or d.card_type == card_type):
            return d.id
    return None


def _golden_monkey_card_id(game):
    """Golden Monkey token 的 card_id。

    异变 BG27_Anomaly_754 自身无 evolution 指针，但**同效果**随从卡
    Treasure-Seeker Elise（BG23_353）携带 `evolution_card_id` → 授予物
    （数据核实: dbf 93101 = BG23_353_Gt，金色 6/6 Taunt "Golden
    Monkey"）。按名字解析而非硬编码 id。
    """
    elise = _card_id_by_name(game, "Treasure-Seeker Elise", CardType.MINION)
    if elise is None:
        return None
    d = game.db.get(elise)
    if d is None or d.evolution_card_id is None:
        return None
    token = game.db.by_dbf(d.evolution_card_id)
    return token.id if token is not None else None


# ══════════════ BG32_Anomaly_003 Impressive Foresight ══════════════


class ImpressiveForesightAnomaly:
    """
    Natural language: Buy your Lesser Trinket on Turn 5, and your Greater
    Trinket on Turn 8.

    Evidence: data/bg_anomalies.json BG32_Anomaly_003（无模板参数）;
    标准档位 `C.TRINKET_OFFER_TURNS = {6: lesser, 9: greater}`
    （RULES §7.4.1）→ 本异变把两档各提前 1 回合。引擎
    `_begin_recruit_for` 读取 `hero._trinket_early = {kind: turn}`
    并在对应回合发放该档位 offer（BG32_MagicItem_271 同款协议），
    offer 按 `(hero, kind)` 记账 → 标准 T6/T9 不再重复发放。

    Formal spec:
      1. on_bind: 每英雄 `_trinket_early = {"lesser": 5, "greater": 8}`
         （文本字面量; 相对标准档位各提前 1 回合）
      2. 引擎在 `game.turn == 5` 发放 Lesser / `== 8` 发放 Greater;
         标准 T6/T9 因 `_trinket_offered` 已有 `(hero, kind)` 而不发放

    Test: test_batch_anomalies3.py — 第 4 回合无 offer / 第 5 回合
    Lesser（选项 spell_school=11）/ 第 6 回合不再发放 / 第 8 回合
    Greater（spell_school=12）/ 对照组（无异变）第 5 回合无 offer、
    第 6 回合 Lesser、第 9 回合 Greater

    Params: 无模板参数; turn=5/8 为文本字面量
    """

    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            h._trinket_early = dict(_IMPRESSIVE_FORESIGHT_TURNS)
        return None


# ══════════════ BG27_Anomaly_100 Big League ══════════════


class BigLeagueAnomaly:
    """
    Natural language: Only Tavern Tiers 3, 4, 5, and 6 exist. Start with
    10 extra Armor.

    Evidence: data/bg_anomalies.json BG27_Anomaly_100（无模板参数）;
    hsdata/CardDefs.xml CARDTEXT deDE "Gasthausstufen 1 und 2 gibt es
    nicht." = "Tiers 1 and 2 do not exist" → 英雄起始 Tier 3、酒馆抽取
    下限 Tier 3（T1/T2 随从不存在）; 上限 6 即引擎标准
    `C.TAVERN_MAX_TIER`（无需覆写）。升级费按引擎档位表
    `C.BASE_UPGRADE_COSTS[T3→T4]`（同 Temperance of Aman'Thul 的
    T3 起始先例 batch_anomalies.Tier3StartAnomaly）。

    Formal spec:
      1. on_bind: `game._tavern_min_tier = 3`（引擎 refresh_tavern 读
         game 级下限; 本异变对全体生效故用 game 级）——T1/T2 随从不再
         出现在酒馆
      2. 每英雄 `TAVERN_TIER = 3`、`UPGRADE_COST =
         C.BASE_UPGRADE_COSTS[4]`（3→4 档位费）、`armor += 10`

    Test: test_batch_anomalies3.py — 起始 T3 / 升级费 = 档位表值 /
    护甲 +10 / 首个酒馆只含 Tier≥3 随从（对照组 T1 馆只含 T1）/ 可
    正常升到 T4

    Params: 无模板参数; tier=3 与 armor=10 为文本/多语言字面量
    """

    @staticmethod
    def on_bind(game):
        game._tavern_min_tier = _BIG_LEAGUE_FLOOR_TIER
        for h in game.heroes:
            h.set(GameTag.TAVERN_TIER, _BIG_LEAGUE_FLOOR_TIER)
            h.set(GameTag.UPGRADE_COST,
                  C.BASE_UPGRADE_COSTS[_BIG_LEAGUE_FLOOR_TIER + 1])
            h.armor += _BIG_LEAGUE_EXTRA_ARMOR
        return None


# ══════════════ BG27_Anomaly_101/102 酒馆等级阶梯族 ══════════════


def _bind_tier_ladder(game, ladder) -> None:
    """存在档阶梯 on_bind 公共体（101/102 同机制，仅档集合不同）。

    - `game._tavern_tier_ladder` = 存在档升序元组（升级落点/抽取白名单/
      发现候选三处读取的**唯一**声明）
    - `max_tavern_tier` = 阶梯末档（与既有"本局最高档"读取点一致）
    - `game._triple_reward_of_own_tier` = 文本第二句 "Triple Rewards
      Discover a minion of your Tier."
    - 起手档 = 阶梯首档（"Only Tavern Tiers X…Y exist" 下不存在更低档;
      与 Big League "T1/T2 不存在 → 起始 T3" 同一规则）；挂起升级费 =
      `BASE_UPGRADE_COSTS[2]` = 5 金（wiki Tavern Tier "Upgrading starts
      at 5 Coins"；首次升级与标准局同价）
    """
    game._tavern_tier_ladder = tuple(ladder)
    game.max_tavern_tier = ladder[-1]
    game._triple_reward_of_own_tier = True
    for h in game.heroes:
        h.set(GameTag.TAVERN_TIER, ladder[0])
        h.set(GameTag.UPGRADE_COST, C.BASE_UPGRADE_COSTS[2])


class WhatAreTheOddsAnomaly:
    """
    Natural language: Only Tavern Tiers 1, 3, and 5 exist. Triple
    Rewards Discover a minion of your Tier.

    Evidence: `data/bg_anomalies.json BG27_Anomaly_101` +
    `hsdata/CardDefs.xml`（enUS 原文，16 语言一致:"Nur ungerade Stufen
    existieren" / zhCN "仅存在等级1，3，5"）→ 存在档 = {1,3,5}。
    wiki 页 `Battlegrounds/What Are the Odds?`（revid 836162，
    2025-01-22）与官方 27.6 patch notes 只有同一句卡面文字，
    **无 Notes/Strategy/升级费用/起手档说明**（逐条查证见
    `docs/ANOMALY_101_102_EVIDENCE.md`）→ 其余全部按自然语言解读:

      1. 起手档 = 阶梯首档 1（T1 存在; 标准局起手即 T1，无需覆写，
         但显式写入以免依赖初始化顺序）
      2. 升级落点 = 下一存在档（1→3→5）；5 之后无存在档 → 不可再升
         （即使他卡解锁 T7——"T6/T7 不存在"）
      3. 酒馆展示 = [下限, 本人档] ∩ {1,3,5}（"only tiers exist" 的
         自然读法; 非存在档随从与酒馆法术都不出现）
      4. 三连奖励档 = 本人当前档位（卡面第二句的**字面**要求，非
         "被三连随从档 + 1"）

    被否决的替代读法:
      - "起手 T3"/"起手 T5"（跳档）: 卡面未写"Start at Tavern Tier N"，
        而 T1 存在 → 起手 T1（Little League 同规则的反面: 文本若要求
        非常规起手会像 Finicky Hourglass "Start at Tavern Tier 2." 明说）
      - 升级费按**目标档**计价（1→3 付 T3 价 `BASE[3]=7`）: 与 wiki
        "Upgrading starts at 5 Coins, and each upgrade costs more than
        the last." 冲突（首次升级应为 5 金）——按**升级步数**计价
        （第 k 次升级用序列第 k 档基价: 5 → 7）
      - 三连奖励档 = 非存在档（如被三连随从 tier+1 = 2）: 卡面明写
        "of your Tier"，且 T2 不存在（发现候选为空 → 落空），故取本人档

    Formal spec:
      1. on_bind: `_bind_tier_ladder(game, (1, 3, 5))`
      2. 引擎读取点: `Game._next_existing_tier` / `Game._upgrade_cost_after`
         （升级）、`Game._ladder_tier_filter`（refresh_tavern 随从+法术）、
         `actions.discover._pool_candidates`（发现候选）、
         `Game._grant_triple_reward`（奖励档）

    Test: test_batch_anomalies3.py TestTierLadder — 起手 T1 + 升级费 5 /
      1→3→5 且第 4 次升级 False / 落点后基价 = `BASE[3]`（步数口径）/
      真实刷新只出 T1/T3/T5 随从与法术（对照标准局同种子出现 T2）/ 真实
      三连（三份入手→金卡打出）奖励候选全为本人档 T3（对照: 若无异变
      同 T1 三连给 T2）

    Params: 无模板参数; 档集合 {1,3,5} 为文本字面量
    """

    @staticmethod
    def on_bind(game):
        _bind_tier_ladder(game, _ODDS_TIER_LADDER)
        return None


class HowToEvenAnomaly:
    """
    Natural language: Only Tavern Tiers 2, 4, and 6 exist. Triple
    Rewards Discover a minion of your Tier.

    Evidence: `data/bg_anomalies.json BG27_Anomaly_102` +
    `hsdata/CardDefs.xml`（enUS 原文; deDE "Nur gerade Stufen
    existieren" / zhCN "仅存在等级2，4，6"）→ 存在档 = {2,4,6}。
    wiki 页 `Battlegrounds/How to Even??`（revid 805286，2024-07-05）
    与 101 同构: 只有卡面模板，**无 Notes**（`docs/ANOMALY_101_102_
    EVIDENCE.md` 逐条 NO AUTHORITY FOUND）→ 按自然语言解读:

      1. 起手档 = 阶梯首档 **2**（T1 **不存在** → 玩家不能处于非存在档;
         与 Big League "T1/T2 不存在 → 起始 T3" 同一规则。被否决的
         替代读法: 起手 T1 后再跳到 T2——那会让起手处于"不存在"的
         T1，且首个酒馆无任何存在档随从可展示）
      2. 升级落点 = 下一存在档（2→4→6）；6 为末档
      3. 展示/发现白名单 = {2,4,6}（T1/T3/T5 随从与法术都不出现）
      4. 三连奖励档 = 本人当前档位（2/4/6）

    与 101 的唯一差异 = 档集合与起手档（T6 为最高档，全程无 T1 随从）。

    Formal spec:
      1. on_bind: `_bind_tier_ladder(game, (2, 4, 6))`
      2. 引擎读取点同 WhatAreTheOddsAnomaly（同一套阶梯原语）

    Test: test_batch_anomalies3.py TestTierLadder — 起手 T2 + 升级费 5 /
      2→4→6 且第 4 次升级 False / 真实刷新只出 T2/T4/T6（对照: 标准局
      同种子出现 T1 随从、T1 法术）/ 真实三连奖励档 = 本人档（T4 时
      三连 T2 得 T4 候选）

    Params: 无模板参数; 档集合 {2,4,6} 为文本字面量
    """

    @staticmethod
    def on_bind(game):
        _bind_tier_ladder(game, _EVEN_TIER_LADDER)
        return None


# ══════════════ BG31_Anomaly_104 Rising Current ══════════════


class RisingCurrentAnomaly:
    """
    Natural language: After you upgrade the Tavern, Discover a Tier {1}
    Tavern spell. (Improves in {0} turns!)

    Evidence: data/bg_anomalies.json BG31_Anomaly_104 —
    `script_data_num_1=2`（{0} 倒计时）/`script_data_num_2=1`（{1} 起始
    Tier）; 文本变体 2（无倒计时）同文。"Improves in {0} turns" 的
    递增模型沿用 `Patient Scout`（batch_avenge_misc）"Improves each
    turn" 的既有裁定（基数 + 回合数），此处周期为 num(0) 回合:
    tier = num(1) + (turn−1)//num(0)，封顶 `game.max_tavern_tier`。

    Formal spec:
      1. on_bind: 每英雄注册 `tavern_upgraded` 常驻监听（condition/
         guard 锁英雄）——引擎 `upgrade_tavern`/`upgrade_tavern_free`
         均在成功升级后 fire (hero=, tier=)
      2. 每次升级: `DiscoverTavernSpellOfTier(hero, T)`（batch_spells4
         的酒馆法术发现 Action——池感知 + 预留语义）;
         T = min(num(1) + (game.turn − 1)//num(0), game.max_tavern_tier)
      3. num(0)/num(1) 缺失 → 整卡不接线（不猜）

    Test: test_batch_anomalies3.py — 第 1 回合升级给 Tier num(1)=1 三选
    一（选项 tier 全等于期望值）/ 第 3 回合给 num(1)+1 / 第 5 回合
    num(1)+2 / 封顶 max_tavern_tier / 英雄隔离

    Params: {0}=2 {1}=1（BG31_Anomaly_104）
    """

    @staticmethod
    def on_bind(game):
        d = game.db.get(game.anomaly) if game.anomaly else None
        if d is None:
            return None
        base, every = d.num(1), d.num(0)
        if base is None or not every:
            return None
        from hsrl2.scripts.batches.batch_spells4 import (
            DiscoverTavernSpellOfTier,
        )
        for h in game.heroes:
            def on_up(g, hero=None, tier=None, _h=h, _base=base,
                      _n=every, **kw):
                if hero is not _h:
                    return
                t = min(_base + (g.turn - 1) // _n, g.max_tavern_tier)
                g.run_actions(DiscoverTavernSpellOfTier(_h, t))

            game.events.register(Listener(
                event="tavern_upgraded", owner=h, callback=on_up))
        return None


# ══════════════ BG31_Anomaly_105 Sin'dorei Mirror ══════════════


class SindoreiMirrorAnomaly:
    """
    Natural language: After you buy your first Tavern spell each turn,
    get an extra copy of it. (Unlocks on Turn 5.)

    Evidence: data/bg_anomalies.json BG31_Anomaly_105（无模板参数）;
    文本变体 2 无 "(Unlocks on Turn 5.)" → 解锁回合 = 5（文本字面量）。
    购买事件 = `SPELL_BOUGHT`（game.buy_from_tavern 对池法术 fire，
    带 spell=/hero=——Magicfin Mycologist 同款数据源）。

    Formal spec:
      1. on_bind: 每英雄 `_sindorei_mirror_used = False` + 注册
         SPELL_BOUGHT 常驻监听 + TURN_START 重置一次性标记
      2. 条件: `hero is _h`（owner 隔离）+ `game.turn >= 5` +
         本回合首次 + 该法术是池法术（`CardDef.is_pool_spell`）
      3. 效果: `create_spell(同一 card_id)` → `pending_hand_add`
         （plain copy——Double Header BG27_Anomaly_711 同款
          "get an extra copy of it" 先例，不占池; 满手排队不销毁）

    Test: test_batch_anomalies3.py — 第 5 回合购买得 2 张（原 + 副本）/
    同回合第二张无副本 / 下回合再次生效 / 第 4 回合无副本（正对照:
    同 setup 第 5 回合确有副本）/ 英雄隔离

    Params: 无模板参数; 解锁回合 5 为文本字面量
    """

    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            h._sindorei_mirror_used = False

            def on_bought(g, spell=None, hero=None, _h=h, **kw):
                if hero is not _h or spell is None:
                    return
                if g.turn < _SINDOREI_UNLOCK_TURN:
                    return
                d = g.db.get(spell.card_id)
                if d is None or not d.is_pool_spell:
                    return
                if getattr(_h, "_sindorei_mirror_used", False):
                    return
                _h._sindorei_mirror_used = True
                copy = g.create_spell(spell.card_id, controller=_h)
                if copy is not None:
                    g.pending_hand_add(_h, copy)

            def on_ts(g, hero=None, _h=h, **kw):
                if hero is _h:
                    _h._sindorei_mirror_used = False

            game.events.register(Listener(event=SPELL_BOUGHT, owner=h,
                                          callback=on_bought))
            game.events.register(Listener(event=TURN_START, owner=h,
                                          callback=on_ts))
        return None


# ══════════════ BG31_Anomaly_109 Mystical Blossom ══════════════


class MysticalBlossomAnomaly:
    """
    Natural language: At the start of each turn, Discover a Tavern spell.
    (Unlocks on Turn 3.)

    Evidence: data/bg_anomalies.json BG31_Anomaly_109（无模板参数）;
    文本变体 2 无 "(Unlocks on Turn 3.)" → 解锁回合 = 3（文本字面量）。
    "a Tavern spell" 未给 tier → 采用酒馆法术发现既有口径
    `DiscoverTavernSpellOfTier(hero, hero.tavern_tier)`（batch_spells4
    的 Holli'dae/随机施放统一口径: tech_level ≤ 酒馆等级）。

    Formal spec:
      1. on_bind: 每英雄注册 TURN_START 常驻监听（"each turn" 重复效果，
         非 once）
      2. turn ≥ 3: `DiscoverTavernSpellOfTier(hero, hero.tavern_tier,
         min_tier=1)`（"a Tavern spell" 默认范围 = ≤ 酒馆等级——2026-09-02
         对抗审查 D2 裁定，与引擎 SpellPool.draw_tavern / Mystic Essence /
         Holli'dae / Yogg 同口径）
         → PendingChoice(kind="discover_tavern_spell")，选项占法术池、
         resolve 保留选中/释放其余
      3. 池内该 tier 无候选 → Action 落空（真实游戏行为）

    Test: test_batch_anomalies3.py — 第 2 回合无发现 / 第 3 回合每英雄
    各一份三选一且选项 tier 全 ≤ 酒馆等级 / 选中后入手 / 第 4 回合再给
    （每回合语义）/ 英雄隔离

    Params: 无模板参数; 解锁回合 3 为文本字面量
    """

    @staticmethod
    def on_bind(game):
        from hsrl2.scripts.batches.batch_spells4 import (
            DiscoverTavernSpellOfTier,
        )
        for h in game.heroes:
            def on_ts(g, hero=None, turn=None, _h=h, **kw):
                if hero is not _h:
                    return
                t = g.turn if turn is None else turn
                if t < _MYSTICAL_UNLOCK_TURN:
                    return
                # "a Tavern spell" = tech_level ≤ 酒馆等级（RULES §3.6.1
                # note; 2026-09-02 对抗审查 D2 裁定）
                g.run_actions(DiscoverTavernSpellOfTier(
                    _h, _h.tavern_tier, min_tier=1))

            game.events.register(Listener(event=TURN_START, owner=h,
                                          callback=on_ts))
        return None


# ══════════════ BG27_Anomaly_301 False Idols ══════════════


class FalseIdolsAnomaly:
    """
    Natural language: You only need 2 copies to make minions Golden.
    They give Tavern Coins instead of Triple Rewards.

    Evidence: data/bg_anomalies.json BG27_Anomaly_301（无模板参数）。
    引擎协议: `TRIPLE_THRESHOLD`（check_for_triple 读，默认 3）+
    `TRIPLE_REWARD_COINS`（三连合成时改发 N 张 Tavern Coin
    BG28_810，见 game.check_for_triple 的 `_grant_tavern_coins` 分支）。
    同一句文案的同数值实现先例 = Clocksworth
    `BG34_HERO_002p`（batch_hero_econ3: 2 / 1，官方 36.2 每三连 1 张
    Tavern Coin）——非新猜。

    Formal spec:
      1. on_bind: 每英雄 `TRIPLE_THRESHOLD = 2`（只需 2 份合成金色）
      2. 每英雄 `TRIPLE_REWARD_COINS = 1`——手牌合成路径即时发 1 张
         Tavern Coin（不再打 `TRIPLE_REWARD_PENDING`）; 棋盘合成路径
         同样发 Coin 而非发现奖励

    Test: test_batch_anomalies3.py — 2 份同 id 即合成金色且入手 1 张
    Tavern Coin、金色无 TRIPLE_REWARD_PENDING / 对照（无异变）2 份不
    合成、3 份合成金色但打 TRIPLE_REWARD_PENDING 且无 Coin

    Params: 无模板参数; threshold=2 为文本字面量, coins=1 沿用同文
            Clocksworth 先例
    """

    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            h.set(GameTag.TRIPLE_THRESHOLD, _FALSE_IDOLS_THRESHOLD)
            h.set(GameTag.TRIPLE_REWARD_COINS, _FALSE_IDOLS_COINS)
        return None


# ══════════════ BG27_Anomaly_555 No Place Like Holmes ══════════════


class NoPlaceLikeHolmesAnomaly:
    """
    Natural language: Each turn, look at 2 minions. Guess which one your
    next opponent had last combat for a Coin.

    Evidence: data/bg_anomalies.json BG27_Anomaly_555（无模板参数）。
    与英雄技能 Murloc Holmes `BG23_HERO_303p2` "Detective for Hire"
    同机制（wiki 同文案）——该实现已于 2026-09-02 对抗审查裁定:
      - 真选项 = `game.next_opponent(hero).last_combat_board` 去重
        (card_id, golden) 随机一张（RULES §4.8a: 下一对手 × 其**上一场
        战斗**）;
      - 诱饵 = 池内（available>0）非快照 id 随机一张（官方权重未公布
        ——Malygos 裁定先例等权）;
      - 猜对 → 1× Tavern Coin。
    本异变只是把该技能改为"每回合自动"（原技能为主动、需花费），故
    **直接复用** `MurlocHolmesScript.hero_power`（同一代码路径，避免
    语义漂移），不重复实现。

    Formal spec:
      1. on_bind: 每英雄注册 TURN_START 常驻监听（"Each turn"）
      2. 每次本人回合开始: 调用 Holmes 猜测路径——无下一对手/无上一场
         战斗阵容 → 落空（第 1 回合必然落空）; 否则追加
         PendingChoice(kind="holmes_guess")，2 选项; 选中真选项者得
         1× Tavern Coin
      3. 每英雄独立（闭包 `_h=h` 绑定）

    Test: test_batch_anomalies3.py — 下一对手 last_combat_board 为空 →
    无选择（负）; 注入快照后本人回合产生恰 2 选项且其一来自快照（正
    对照）; 猜对得 Tavern Coin、猜错不得; 英雄隔离

    Params: 无模板参数
    """

    @staticmethod
    def on_bind(game):
        from hsrl2.scripts.batches.batch_hero_actives2 import (
            MurlocHolmesScript,
        )
        for h in game.heroes:
            def on_ts(g, hero=None, _h=h, **kw):
                if hero is not _h:
                    return
                MurlocHolmesScript.hero_power(_h, g, {})

            game.events.register(Listener(event=TURN_START, owner=h,
                                          callback=on_ts))
        return None


# ══════════════ BG27_Anomaly_575 Eleventh Hour ══════════════


class EleventhHourAnomaly:
    """
    Natural language: The first time your hero takes fatal damage in
    combat, prevent it and gain 11 Gold next turn instead.

    Evidence: data/bg_anomalies.json BG27_Anomaly_575（无模板参数）。
    引擎契约: `Hero.take_damage` 在扣减**之后** fire
    `HERO_DAMAGE_TAKEN(hero=, amount=, health_before=, armor_before=)`
    （SOP §8; 伤害窗口内监听器可全量回溯该伤害实例——Soul Rewinder
    同款协议）; 战斗败方伤害施加于 `run_combat` 内（`game.in_combat=True`），
    此后才 `_process_eliminations` → 此刻把生命/护甲回溯即可阻止淘汰。
    "next turn" 用 `game.defer_until_next_turn`（下个招募阶段金币重置
    后执行 = 官方"下回合获得"）; 11 为文本字面量。

    Formal spec:
      1. on_bind: 每英雄注册 HERO_DAMAGE_TAKEN 常驻监听
      2. 触发条件: `hero is _h` + `game.in_combat`（"in combat"——
         招募期自伤/健康购买不触发）+ 本局尚未触发过 +
         扣减后 `health + armor == 0`（致命）
      3. 效果: 打标记 → 生命=health_before、护甲=armor_before（"prevent
         it"）→ `defer_until_next_turn(hero, GainGold(hero, 11))`
      4. 仅首次（per-hero 一次/局）

    Test: test_batch_anomalies3.py — 真实 run_combat 中败方致命伤害被
    阻止（生命回溯、仍存活）、下回合金币含 +11（正对照）; 招募期致命
    伤害不阻止（负）; 第二次战斗致命伤害不再阻止（once 语义）

    Params: 无模板参数; gold=11 为文本字面量
    """

    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_dmg(g, hero=None, amount=0, health_before=0,
                       armor_before=0, _h=h, **kw):
                if hero is not _h or not g.in_combat:
                    return
                if getattr(_h, "_eleventh_hour_used", False):
                    return
                if _h.health + _h.armor > 0:
                    return          # 非致命伤害不触发
                _h._eleventh_hour_used = True
                _h.health = health_before
                _h.armor = armor_before
                g.defer_until_next_turn(
                    _h, GainGold(_h, _ELEVENTH_HOUR_GOLD))

            game.events.register(Listener(event=HERO_DAMAGE_TAKEN, owner=h,
                                          callback=on_dmg))
        return None


# ══════════════ BG27_Anomaly_754 Path of the Treasure-Seeker ═════════


class PathOfTheTreasureSeekerAnomaly:
    """
    Natural language: Whenever you Refresh 5 times, find the Golden
    Monkey! (@ left!)

    Evidence: data/bg_anomalies.json BG27_Anomaly_754 —
    `script_data_num_1=5`（刷新阈值）`script_data_num_2=5`（计数显示）;
    wiki 卡片页（?action=raw）无 Notes。授予物由**同效果随从卡**
    Treasure-Seeker Elise `BG23_353` 的 `evolution_card_id`（dbf
    93101 → `BG23_353_Gt`，金色 6/6 Taunt "Golden Monkey"）解析
    （`_golden_monkey_card_id`，按名字查卡不硬编码 id）。
    "find" = 入手（HS 术语: 生成卡入手），按 `pending_hand_add` 排队
    （满手不销毁）。
    引擎刷新事件 = `tavern_refresh`（game.refresh_tavern 尾部 fire）;
    该事件对自动/手动刷新皆 fire（无 auto 标记）→ 沿用同批
    Light the Way（BG31_Anomaly_116）"Refresh 计数"先例按全部刷新计数。

    Formal spec:
      1. on_bind: 阈值 = num(0)（缺 → 不接线）; 授予物由 Elise 的
         evolution 指针解析（缺 → 不接线）
      2. 每英雄 `_treasure_seeker_refreshes = 0` + TAVERN_REFRESH 常驻
         监听; 每次本人刷新 +1，达到 num(0) 清零并
         `create_minion(金猴 token, golden=True)` → `pending_hand_add`
      3. 每英雄独立计数（闭包 `_h=h` 绑定）

    Test: test_batch_anomalies3.py — 真实 refresh_tavern num(0)−1 次无
    猴 / 第 num(0) 次得 1 只（金卡本体、GOLDEN）/ 再过 num(0) 次第 2 只
    （周期语义）/ 下限守卫: 若把计数留在 num(0)−1，未达阈值负断言配
    正对照 / 英雄隔离

    Params: {0}=5（阈值）{1}=5（显示用计数上限）
    """

    @staticmethod
    def on_bind(game):
        d = game.db.get(game.anomaly) if game.anomaly else None
        n = d.num(0) if d is not None else None
        token = _golden_monkey_card_id(game)
        if not n or token is None:
            return None
        for h in game.heroes:
            h._treasure_seeker_refreshes = 0

            def on_refresh(g, hero=None, _h=h, _n=n, _tok=token, **kw):
                if hero is not _h:
                    return
                done = getattr(_h, "_treasure_seeker_refreshes", 0) + 1
                if done >= _n:
                    done = 0
                    monkey = g.create_minion(_tok, controller=_h,
                                             golden=True)
                    if monkey is not None:
                        g.pending_hand_add(_h, monkey)
                _h._treasure_seeker_refreshes = done

            game.events.register(Listener(event=TAVERN_REFRESH, owner=h,
                                          callback=on_refresh))
        return None


# ══════════════ BG27_Anomaly_558 Feline Fortune ══════════════


class FelineFortuneAnomaly:
    """
    Natural language: After another hero dies, Discover a minion from
    their warband. It keeps enchantments.

    Evidence: data/bg_anomalies.json BG27_Anomaly_558（无模板参数）。
    同文案先例 = 任务奖励 R806（batch_quest_rewards）"Discover a
    non-Golden minion from your last opponent's warband. It keeps
    enchantments."——其实现（实体选项 + `copy_buffs_to`）已入库;
    本卡差异: 触发源是 `HERO_ELIMINATED` 而非 `COMBAT_END`，且候选
    来自**淘汰者**的战团（保留附魔 → 逐实体复制）。引擎
    `_process_eliminations` 在 fire `hero_eliminated` 前已把淘汰者棋盘
    回池但**实体仍在 `hero.board` 列表中且 buff 完整**（可读取）。

    Formal spec:
      1. on_bind: 注册 game 级 `HERO_ELIMINATED` 常驻监听（owner=None）
      2. 淘汰者战团（`dead.board` 中 Minion）非空时，对每个**存活且
         非淘汰者**英雄: `game.rng.sample(warband, min(3, len))` →
         PendingChoice(kind="discover_minion"，选项为实体)
      3. resolve: `create_minion(m.card_id, golden=m.is_golden)`（plain
         copy 不占池——R806/Rafaam 先例）→ `m.copy_buffs_to(copy)`
         （"keeps enchantments"，独立 Buff 实例）→ `pending_hand_add`
         （满手排队）
      4. 多个英雄淘汰 → 每次独立触发

    Test: test_batch_anomalies3.py — 淘汰者的带 buff 随从进入每个存活
    英雄的发现选项、选中副本保留附魔（atk/max_health = 基础 + buff）;
    对照（无异变）无选择; 淘汰者本人不获得选择

    Params: 无模板参数
    """

    @staticmethod
    def on_bind(game):
        def on_elim(g, hero=None, **kw):
            dead = hero
            if dead is None:
                return
            warband = [m for m in getattr(dead, "board", [])
                       if isinstance(m, Minion)]
            if not warband:
                return
            for h in list(g.heroes):
                if h is dead or not h.is_alive:
                    continue
                opts = g.rng.sample(warband, min(3, len(warband)),
                                    label="feline_fortune")

                def resolve(m, _h=h):
                    if m not in warband:
                        return
                    copy = g.create_minion(m.card_id, controller=_h,
                                           golden=m.is_golden)
                    if copy is None:
                        return
                    if m.is_golden:
                        # 非三连金（plain copy）→ 出售/淘汰回池按 1 份
                        # （RULES §2.3 Reno 口径; 否则金副本按 3 份回池
                        # 净增——SOP §16 第 19 条配平）
                        copy.set(GameTag.GILDED_NOT_TRIPLED, True)
                    m.copy_buffs_to(copy)
                    g.pending_hand_add(_h, copy)

                g.pending_choices.append(PendingChoice(
                    h, list(opts), "discover_minion",
                    resolve_callback=resolve))

        game.events.register(Listener(event=HERO_ELIMINATED, owner=None,
                                      callback=on_elim))
        return None


def register() -> list[str]:
    """注册异变 12 张（DEFERRED 台账见模块 docstring）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG32_Anomaly_003", ImpressiveForesightAnomaly),
        ("BG27_Anomaly_100", BigLeagueAnomaly),
        ("BG27_Anomaly_101", WhatAreTheOddsAnomaly),
        ("BG27_Anomaly_102", HowToEvenAnomaly),
        ("BG31_Anomaly_104", RisingCurrentAnomaly),
        ("BG31_Anomaly_105", SindoreiMirrorAnomaly),
        ("BG31_Anomaly_109", MysticalBlossomAnomaly),
        ("BG27_Anomaly_301", FalseIdolsAnomaly),
        ("BG27_Anomaly_555", NoPlaceLikeHolmesAnomaly),
        ("BG27_Anomaly_575", EleventhHourAnomaly),
        ("BG27_Anomaly_754", PathOfTheTreasureSeekerAnomaly),
        ("BG27_Anomaly_558", FelineFortuneAnomaly),
    ]
    registered = []
    for aid, cls in pairs:
        reg(aid, cls)
        registered.append(aid)
    return registered
