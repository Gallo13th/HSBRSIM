"""批次 payload_minions — 池外随从载荷（饰品关联卡）第十三批。

背景: 一批 `is_pool_minion=False` 的随从至今未注册，它们是 13 张饰品的
"关联卡/交付物/改写对象"（`CardDef.evolution_card_id` 数据链，运行核验：
`BG30_MagicItem_944/971`、`BG32_MagicItem_274/803/804/820/824/830/925/933`、
`BG35_MagicItem_433/834/922`）。本批只迁移**随从本体 + 其必需 token**
（饰品本身留给后续 wave，见文末台账）。

实现 13 张（CORRECT）——全部数值来自 `CardDef.num(i)` 或卡面字面量
（数据无模板参数时）; 金色 = 独立卡定义（`db.golden_version` 逐张核实）：

  BG21_006 Impulsive Trickster（恶魔 T3 5/5）
      亡语: 把本体 max Health 给一个随机友方随从（wiki Wiki tags 含
      [Random]——随机目标，非 [Targeted]）。金色 "twice" 独立卡定义
      （`BG21_006_G`）：同一效果独立重抽 2 次。

  BG29_140 False Implicator（恶魔 T3 1/1）
      EoT: 吞噬酒馆中的一个随机随从（wiki tags [Random]）并获得其属性;
      金色 "gain double its stats" = `ConsumeMinion`（1×）+ 追加同额
      `Buff`（合计 2×）。酒馆来源回池（`ConsumeMinion` 既有语义）。

  BG25_041 Felemental（元素 T3 3/3）
      战吼: 馆内随从 +{0}/+{1} this game → `TavernBuff`（持久面，
      `refresh_tavern` 对新入馆随从自动应用）+ `BuffCurrentTavern`
      （立即面）。金色 `_G` 文本 "...this game twice."（num 同基础
      2/1）由引擎金色战吼 2 次触发体现（总额 4/2）。

  BG31_148 Hackerfin（鱼人 T5 5/3）
      战吼: 其他友方 +{0}/+{1}，每个**不同的 Bonus Keyword** 提升一次。
      Bonus Keyword 定义域 = 官方 wiki 页 6 集 {Divine Shield, Reborn,
      Stealth, Taunt, Venomous, Windfury}（与 RULES §9.6 / Enhance-o
      Mechano 先例一致）——统计棋盘上出现过的**不同**关键词数 c，
      每次触发值 = num(i)×(1+c)。金色 `_G` num=2/4（=2×基础）由
      `_per_trigger_def` 回基础值 + 引擎 2 次触发体现（总额 2/4）。

  BG31_830 Weary Mage（纳迦 T4 5/1）+ 法术塑造法术 BG31_830t
      Reinvigoration: 给一个随从 +2/+2; 若是纳迦（含 ALL），额外给
      Reborn **until next turn**（单个 TURN_START once 监听到期清除，
      Lich King "Reborn until next turn" 先例; 已有 Reborn 者落空不注册
      ——防过期误清原生关键词）。金色随从 `_G` 的 `spellcraft_id`
      直指金色法术 `BG31_830_Gt`（+4/+4，数据链核实 120897）。

  BG35_437 Vinespeaker（野猪人 T5 5/6）
      友方亡语随从死亡 → 血宝石永久额外 +{0} Attack（`death` 监听 +
      `ImproveBloodGems`，hero tag 跨战斗持久 = "this game"）。

  BG26_801 Rylak Metalhead（野兽 T4 5/3 Taunt+亡语）
      亡语: 触发一个随机相邻随从的战吼（`TriggerBattlecry`，Brann/
      计数/广播由其处理）。基础单数 "an adjacent minion" = 随机一只
      （同文件 Obsidian Ravager 先例：单数随机 / 复数全取），金色 `_G`
      文本复数 "Battlecries of adjacent minions" = 左右各一。

  BG34_920 Tide Raiser（纳迦 T2 2/1 Taunt+亡语）
      亡语: 对一个随机相邻随从**效果施放** Shifting Tide（`BG32_815`，
      `cast_spell_effect`——不动法术池/不计施放计数，RULES §7.4.7b）。
      金色 `_G` 文本复数 = 左右各一。

  BGS_078 Monstrous Macaw（野兽 T4 5/4 Rally）
      Rally: 触发**最左**友方亡语（排除自身）——`game.trigger_deathrattle`
      统一入口（Titus/`dr_extra`/`dr_first`/计数同源，RULES §6.20）。
      金色 `TB_BaconUps_135` 文本 "twice" = 同一最左亡语触发 2 次
      （Deathstrider `passes` 先例）。

  BG_OG_221 Selfless Hero（无类型 T2 2/1 亡语）
      亡语: 随机一个友方随从获得圣盾（`GainKeyword`）。金色
      `TB_BaconUps_014` "Give 2 random friendly minions" = 2 个互异随从。

  BG28_551 Nalaa the Redeemer（无类型 T5 5/6）
      每当施放酒馆法术 → 每类型一个随机友方 +{0}/+{1}。事件用
      `tavern_spell_cast`（per-cast，RULES §7.4.10 "cast" 域）；"of each
      type" 用 10 标准种族各自随机选取（Misplaced Tea Set /
      The Last One Standing 先例，ALL 随从每族合格）。

  BG26_157 Bristlebach（野猪人 T6 3/10 Avenge(2)）
      `avenge_target=2`（数据）；"plays 2 Blood Gems on all your Quilboar"
      → `PlayBloodGems`（含 `BLOOD_GEM_BONUS_*`）。金色文本 "plays 4"。

  BGS_009 Lightfang Enforcer（无类型 T5 8/8）
      EoT: 每类型一个随机友方 +4/+4（同上 10 种族口径）。金色
      `TB_BaconUps_082` 文本 "+8/+8"（无模板参数 → 独立金色脚本类
      字面量 8/8）。

DEFERRED: 0 张。

引擎缺口（本批上报，均**不**阻塞以上 13 张）:
  1. `BONUS_KEYWORDS`（XML ReferencedTag enumID=3423，本批 Hackerfin
     携带）生成器未导出——本批按官方 wiki 6 集硬编码并加漂移守护测试;
     若取得 XML 权威字段应改为数据驱动。
  2. "of each type" 的种族全集（10 标准种族）全仓为脚本层常量
     （batch_rally/batch_spells3 先例）——引擎无 `Race` 全集读取点。
  3. 相邻语义（Rylak/Tide Raiser）在死亡后依赖 `ctx["position"]`
     残值定位死者板位——若同一死亡波内更早的亡语已在死者板位召唤，
     "右邻"会读到新召唤物（引擎未提供"死者原左右邻居"快照）。

关联卡 → 饰品解锁台账（本批注册后**仍需**饰品 wave 迁移）:
  BG21_006 → BG32_MagicItem_820 Impulsive Portrait（载荷已就绪）
  BG29_140 → BG32_MagicItem_824 Implicator Portrait（载荷已就绪）
  BG25_041 → BG32_MagicItem_830 Felemental Portrait（载荷已就绪）
  BG31_148 → BG32_MagicItem_925 Hackerfin Portrait（载荷已就绪）
  BG31_830 → BG32_MagicItem_933 Weary Portrait（载荷已就绪）
  BG35_437 → BG35_MagicItem_433 Vinespeaker Portrait（载荷已就绪）
  BG26_801 → BG35_MagicItem_834 Rylak Portrait（载荷已就绪）
  BG34_920 → BG35_MagicItem_922 Tide Raiser Portrait（**另缺**: 战斗内
             施法事件/结算入口——饰品自身条款）
  BGS_078  → BG32_MagicItem_803 Macaw Portrait（**已闭环**: batch_trinkets36
             于 2026-09-13 落地 §7.4.17 条件化战吼第二消费者——本卡
             `rally` 读 `FLAG_MACAW_EXTRA_BATTLECRY` 追加最左战吼）
  BG_OG_221→ BG32_MagicItem_804 Selfless Portrait（载荷已就绪; 2026-09-13
             由 batch_trinkets35 写入 FLAG_SELFLESS_BATTLECRY 条件化
             战吼——RULES §7.4.17）
  BG28_551 → BG30_MagicItem_944 Redeemer Portrait（**另缺**: "give an
             extra +{0}/+{1}" 家族增量通道）
  BG26_157 → BG32_MagicItem_274 Bristlebach Portrait（**已闭环**: batch_trinkets34 于 2026-09-13 落地 §7.4.16 家族行为开关通道，本卡 `avenge` 消费 `FLAG_SCOPE_ALL_FRIENDLY`）; 历史上另一阻塞: "play
             Blood Gems on all friendly minions" 改写通道）
  BGS_009  → BG30_MagicItem_971 Enforcer Portrait（**另缺**: 多值种族
             `RACES`——"have all minion types"）

测试: `hsrl2/tests/test_batch_payload_minions.py`（行为层：亡语走真实
`_process_single_death` + Titus / Avenge 仅战斗内计数 / EoT 真实
`end_recruit_phase` / owner 隔离 / 池占返 / 确定性）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.actions import Buff, GainKeyword, TriggerBattlecry
from hsrl2.actions.bloodgem import ImproveBloodGems, PlayBloodGems
from hsrl2.actions.consume import ConsumeMinion
from hsrl2.actions.tavern_buff import (ApplyTavernBuff, BuffCurrentTavern,
                                       TavernBuff)
from hsrl2.events import DEATH, TAVERN_SPELL_CAST, TURN_START, Listener
from hsrl2.minion import Minion
from hsrl2.spellcraft import grant_spellcraft_spell
from hsrl2.tags import GameTag, Race

# 跨批复用（batch_counters → batch_deathrattle2 先例）：金色战吼"每次
# 触发值"解析——金色实体回基础 CardDef，引擎对金色战吼触发 2 次。
from hsrl2.scripts.batches.batch_deathrattle import _per_trigger_def

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# ── 卡 id（CardDB 按名核实——禁止凭记忆写 id） ──
IMPULSIVE = "BG21_006"
IMPULSIVE_G = "BG21_006_G"
FALSE_IMPLICATOR = "BG29_140"
FALSE_IMPLICATOR_G = "BG29_140_G"
FELEMENTAL = "BG25_041"
FELEMENTAL_G = "BG25_041_G"
HACKERFIN = "BG31_148"
HACKERFIN_G = "BG31_148_G"
WEARY_MAGE = "BG31_830"
WEARY_MAGE_G = "BG31_830_G"
REINVIGORATION = "BG31_830t"
REINVIGORATION_G = "BG31_830_Gt"
VINESPEAKER = "BG35_437"
VINESPEAKER_G = "BG35_437_G"
RYLAK = "BG26_801"
RYLAK_G = "BG26_801_G"
TIDE_RAISER = "BG34_920"
TIDE_RAISER_G = "BG34_920_G"
MACAW = "BGS_078"
MACAW_G = "TB_BaconUps_135"
SELFLESS_HERO = "BG_OG_221"
SELFLESS_HERO_G = "TB_BaconUps_014"
NALAA = "BG28_551"
NALAA_G = "BG28_551_G"
BRISTLEBACH = "BG26_157"
BRISTLEBACH_G = "BG26_157_G"
LIGHTFANG = "BGS_009"
LIGHTFANG_G = "TB_BaconUps_082"

# 池法术 Shifting Tide（RULES §3.6.1 每 tier 副本模型，T4）——效果施法
# 不占池（RULES §7.4.7b），id 为数据链身份标识
SHIFTING_TIDE = "BG32_815"

# BG 全部标准种族（"of each type" 枚举; batch_rally.ALL_BG_RACES /
# batch_spells3._ALL_STANDARD_RACES 同款——NONE/ALL 不是种族，ALL 随从
# 经候选匹配对每族合格）
_STANDARD_RACES = (
    Race.UNDEAD, Race.MURLOC, Race.DEMON, Race.MECH, Race.ELEMENTAL,
    Race.BEAST, Race.PIRATE, Race.DRAGON, Race.QUILBOAR, Race.NAGA,
)

# Bonus Keyword 定义域（官方 wiki: Battlegrounds/Bonus_Keyword——
# "one of 6 keywords ... Divine Shield, Reborn, Stealth, Taunt,
# Venomous, or Windfury"; 与 RULES §9.6 / Enhance-o Mechano 先例一致）
_BONUS_KEYWORD_TAGS = (
    GameTag.DIVINE_SHIELD, GameTag.REBORN, GameTag.STEALTH,
    GameTag.TAUNT, GameTag.VENOMOUS, GameTag.WINDFURY,
)

_NAGA_RACES = (Race.NAGA, Race.ALL)


def _living_friendly(hero: "Hero") -> list:
    return [m for m in hero.board if isinstance(m, Minion) and not m.dead]


def _each_type_buffs(game: "Game", hero: "Hero", atk: int, health: int,
                     label: str) -> list:
    """"give a friendly minion of each type +atk/+health"（Nalaa/Lightfang）。

    对**全部 10 个标准种族**各自在合格集（类型身份集合含 r）中
    独立随机选取一只 → 一份 `Buff`; 多类型随从对每一所属类型均合格、
    可被多族重复命中（AC-6 ALL 先例 + wiki `Multi-type minion`
    revid 855346 "multi-type minions can take on the role of either
    minion type"）。无候选的种族落空。返回 Action 列表（调用方
    run_actions）。
    """
    living = _living_friendly(hero)
    out = []
    for race in _STANDARD_RACES:
        cands = [m for m in living
                 if race in m.races]
        if not cands:
            continue
        pick = game.rng.choice(cands, label=label)
        out.append(Buff(pick, atk=atk, health=health))
    return out


def _has_deathrattle(m) -> bool:
    """挂有亡语的实体（关键词 tag 或脚本钩子——Deathstrider 先例口径）。"""
    return m.has(GameTag.DEATHRATTLE) or getattr(
        m.scripts, "deathrattle", None) is not None


def _adjacent_minions(source, ctx) -> list:
    """source 的存活相邻随从（左→右）——两种触发路径统一。

    路径 A（真实死亡/Rylak 本体亡语）: source 已离场 → 相邻 = 死者板位
    两侧的存活随从。`slot` = `ctx["position"]`（引擎在
    `_process_death_inner` 离场后传入的 `ZONE_POSITION` 残值）; 死者已
    从棋盘移除 → 原右邻现在位于 `slot`、原左邻仍在 `slot - 1`。

    路径 B（"Trigger a Deathrattle" 效果在 source **存活**时触发，如
    Monstrous Macaw 触发左-most 亡语）: source 仍在棋盘 → 直接用实际
    板位 ±1（`trigger_deathrattle` 默认 position=0，不可用）。

    已知边界（模块 docstring 引擎缺口 3）: 路径 A 中若同一死亡波内更早
    的亡语已在死者板位召唤，则"右邻"读到新召唤物。
    """
    hero = getattr(source, "controller", None)
    if hero is None:
        return []
    board = hero.board
    if source in board and not source.dead:
        pos = source.zone_position
        return [m for m in board
                if m is not source and not m.dead
                and abs(m.zone_position - pos) == 1]
    slot = (ctx or {}).get("position", source.zone_position)
    out = []
    if 0 <= slot - 1 < len(board):
        out.append(board[slot - 1])
    if 0 <= slot < len(board):
        out.append(board[slot])
    return [m for m in out if not m.dead]


# ══════════════════ BG21_006 Impulsive Trickster ══════════════════

#: 亡语目标集合开关（RULES §7.4.16 家族行为开关通道）——由
#: `BG32_MagicItem_820` Impulsive Portrait 写入 `hero.family_flags`
#: （batch_trinkets39）。常量定义在**载荷侧**（唯一消费点），饰品侧
#: import 同一常量（Bristlebach `FLAG_SCOPE_ALL_FRIENDLY` 同构）。
FLAG_IMPULSIVE_ADJACENT = "impulsive_trickster_target_adjacent"


class ImpulsiveTricksterScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Give this
    minion's maximum Health
    to another friendly minion.

    Formal spec:
      1. deathrattle（真实死亡路径或"Trigger a Deathrattle"统一入口）:
         候选 = 本体以外、棋盘存活的友方随从; 空候选 → 落空
      2. `rng.choice` 随机一只（wiki Wiki tags 含 [Random]——非
         [Targeted]，故为随机而非 PendingChoice），获得
         `Buff(health=source.max_health)`——**max_health 是属性值**
         （base+buffs，RULES §6.x 快照口径），非当前 health; 死亡实体
         仍在 GRAVEYARD 持有附魔，故快照可得
      3. 基础单次; 金色独立卡定义 `BG21_006_G` 文本 "twice"由
         `_applications` 表达（引擎不自动翻倍金色亡语）
      4. **目标集合改写读取点**（RULES §7.4.16 家族行为开关通道）:
         `ImpulsivePortraitScript`（`BG32_MagicItem_820`，
         batch_trinkets39）经 `game.add_family_flag(hero, 基础卡 id,
         FLAG_IMPULSIVE_ADJACENT, source=饰品)` 登记规则; 本钩子经
         `game.family_flag(hero, source.card_id, FLAG_IMPULSIVE_ADJACENT)`
         读取——命中则目标集合由"随机一名友方"改为**全部存活相邻随从**
         （`_adjacent_minions(source, ctx)`，左→右），未命中则逐位等于
         旧行为（随机单目标）。金色 `BG21_006_G` 按基础卡 id 归一命中。
      5. **"target adjacent minions" 的天然语言读法（全额逐目标）与边界**
         - 卡面引用——饰品: "Get a 6/6 Impulsive Trickster. Your
           Impulsive Tricksters' <b>Deathrattles</b> target adjacent
           minions."; 载荷: "Deathrattle: Give this minion's maximum
           Health to another friendly minion."（金色: "...to another
           friendly minion, twice."）。
         - 推导: 饰品句的谓语是 "target"，宾语是复数 "adjacent
           minions"——它**替换**载荷的目标短语 "another friendly
           minion"（单数），不动效果 "Give this minion's maximum
           Health"（给什么）与数额。于是载荷读作 "Give this minion's
           maximum Health to adjacent minions."。
         - "give X to <复数集合>" 的天然读法 = 集合内**每个**成员各得
           X（Hearthstone 的多目标 give 惯例; 全仓同类先例 = 多目标
           `PlayBloodGems(count=N)` 每个目标各得 N 颗、Bristlebach 每个
           目标各得 `_GEMS` 颗）。故 2 个相邻随从时每个各得全额
           `max_health`（合计 2×），而非均分。
         - 被否决的替代读法（**均分** = 合计 1×）: 两张卡文本均无
           "split"/"divided evenly" 之类**明确的分割措辞**; 数额
           "this minion's maximum Health" 是一个不可分的整体值。均分
           读法必须凭空发明"如何分、余数给谁"的规则（几何上两个目标
           可行但纯属附加假设），不符合 owner 权威序要求的"卡面天然
           语言"。
         - 金色: `_applications = 2` 的每个实例都是一次 "Deathrattle
           deal/give" 结算，饰品改写作用于每个实例 → 相邻集合各得
           **2 × max_health**（"twice" 仍是重复而非均分——载荷金色文本
           本身也是 "to another friendly minion, twice"）。
         - 边界: "adjacent" = 死者让位后的板位两侧存活随从
           （`_adjacent_minions` 路径 A 读 `ctx["position"]` 残值）;
           **已知引擎边界**（本模块 docstring 引擎缺口 3）: 同一死亡
           波内更早的亡语若已在死者板位召唤，则"右邻"读到新召唤物。
           无相邻随从（本体是唯一友方）→ 落空（不产生任何 Buff）。
           只作用于**本英雄**的 Trickster（owner 隔离）。
      6. 权威记录: `BG32_MagicItem_820` 卡面 + hearthstone.wiki.gg/
         Battlegrounds/Impulsive_Portrait（oldid=907061，2026-09-16
         复核: Availability/Related cards/Gallery/Patch changes/
         External links，**无 Notes 段** → wiki 对 both-vs-split 沉默）;
         载荷页 Battlegrounds/Impulsive_Trickster（oldid=800847）
         确认基础/金色文本与 [Random] tag。

    Test: test_batch_payload_minions.py — 真实 `_process_single_death`
    下随机友方获得恰好 max_health / 无其他友方落空 / Titus 在场翻倍 /
    对手随从不被影响 / 同 seed 确定性;
    test_batch_trinkets39.py — 无饰品随机单目标（4 份量不变）/
    有饰品两个相邻各得全额 max_health / 金色相邻各得 2×max_health /
    对手饰品不影响我方 / 非家族随从不受影响

    Params: 无数值模板参数（数额 = 本体 max_health 运行时值）
    """

    _applications = 1

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        amount = source.max_health
        if game.family_flag(hero, source.card_id,
                            FLAG_IMPULSIVE_ADJACENT):
            targets = _adjacent_minions(source, ctx)
            if not targets:
                return None
            return [Buff(m, health=amount)
                    for _ in range(source.scripts._applications)
                    for m in targets]
        others = [m for m in _living_friendly(hero) if m is not source]
        if not others:
            return None
        actions = []
        for _ in range(source.scripts._applications):
            pick = game.rng.choice(others, label="impulsive_trickster_target")
            actions.append(Buff(pick, health=amount))
        return actions


class ImpulsiveTricksterGoldenScript(ImpulsiveTricksterScript):
    """
    Natural language: [x]<b>Deathrattle:</b> Give this
    minion's maximum Health
    to another friendly minion,
    twice.

    Formal spec: 同基础版，`_applications = 2`——每次独立重抽目标
    （同一随从可被两次选中，叠加 2 份）。目标集合开关
    （`FLAG_IMPULSIVE_ADJACENT`，基础版 §4–5）命中时: 每个实例对**全部
    相邻随从**各给全额 max_health，故相邻集合各得 2 × max_health。

    Test: test_batch_payload_minions.py — 金色恰好 2 份（同目标叠加或
    分给两只，总量守恒 = 2×max_health）;
    test_batch_trinkets39.py — 金色 + 饰品: 两个相邻各得 2×max_health

    Params: 无数值模板参数（数额 = 本体 max_health 运行时值）
    """

    _applications = 2


# ══════════════════ BG29_140 False Implicator ══════════════════


class FalseImplicatorScript:
    """
    Natural language: [x]At the end of your turn,
    consume a minion in the
    Tavern to gain its stats.

    Formal spec:
      1. end_of_turn（引擎 `end_recruit_phase` 对棋盘随从分发）:
         候选 = 控制者酒馆内的 Minion 实体; 空候选 → 落空（不消耗、
         不产生任何状态变更）
      2. 目标选择走 `game.pick_consume_victim(source, cands,
         label="false_implicator_victim")`（RULES §7.4.16 扩展读取点）:
         无策略时 = 均匀随机（wiki Wiki tags 含 [Random]——
         "a minion" 非玩家指定）; Implicator Portrait `BG32_MagicItem_824`
         命中时 = 馆内**最高 max_health**（并列走 rng），`ConsumeMinion(source, victim)`：
         本体永久获得受害者 atk/max_health; 酒馆来源**回池**
         （`ConsumeMinion` 既有语义 + RULES §2.3），不触发亡语
      3. 金色独立卡定义 `BG29_140_G` "gain double its stats" =
         `_extra_factor` 追加同额 `Buff`（合计 2×，受害者属性在
         吞噬前快照）

    Test: test_batch_payload_minions.py — 真实 EoT 下属性增加 = 受害者
    属性 / 馆内受害者消失且池份数 +1 / 空馆落空零变更 / 金色 2× /
    owner 隔离 / 同 seed 确定性。test_batch_trinkets31.py — 绑定
    Implicator Portrait 后真实 EoT 恰吞**最高生命**者（并列走 rng）;
    对照无饰品仍随机。

    Params: 无数值模板参数（数额 = 受害者运行时属性）
    """

    _extra_factor = 1   # 金色 "double its stats" → 2（追加 1 份额外）

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cands = [m for m in hero.tavern if isinstance(m, Minion)]
        if not cands:
            return None
        victim = game.pick_consume_victim(
            source, cands, label="false_implicator_victim")
        actions = [ConsumeMinion(source, victim)]
        for _ in range(source.scripts._extra_factor - 1):
            actions.append(Buff(source, atk=victim.atk,
                                health=victim.max_health))
        return actions


class FalseImplicatorGoldenScript(FalseImplicatorScript):
    """
    Natural language: [x]At the end of your turn,
    consume a minion in the
    Tavern to gain double
    its stats.

    Formal spec: 同基础版，`_extra_factor = 2`——吞噬后追加一份同额
    `Buff`，净效果 = 2× 受害者属性。

    Test: test_batch_payload_minions.py — 金色获得 2×(atk, max_health)

    Params: 无数值模板参数（数额 = 受害者运行时属性）
    """

    _extra_factor = 2


# ══════════════════ BG25_041 Felemental ══════════════════


class FelementalScript:
    """
    Natural language: [x]<b>Battlecry:</b> Give minions
    in the Tavern +{0}/+{1}
    this game.

    Formal spec:
      1. battlecry: `TavernBuff(atk=num(0), health=num(1))` 登记持久
         面（`hero.tavern_buffs`，`refresh_tavern` 对之后入馆的随从
         自动应用）+ `BuffCurrentTavern` 立即面（当前馆内全部匹配随从）
      2. "this game" = 持久，非 "this turn"（无回合过期监听）
      3. 馆内无随从时持久面照常登记（之后入馆的随从仍获得）——
         非"落空"
      4. 金色 `_G` 文本 "...this game twice."（num 同为基础 2/1）由
         引擎金色战吼 2 次触发体现 → 总额 2×（4/2）

    Test: test_batch_payload_minions.py — 当前馆内 +num(0)/+num(1) /
    刷新后新入馆随从同样获得 / 对手酒馆不受影响 / 金色总额 2×num

    Params: {0}=2 {1}=1（36.2.2 基线; 金色 num 同值，总额由引擎
             2 次触发体现）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        buff = TavernBuff(atk=d.num(0), health=d.num(1),
                          source_id=source.card_id)
        return [ApplyTavernBuff(hero, buff), BuffCurrentTavern(hero, buff)]


# ══════════════════ BG31_148 Hackerfin ══════════════════


class HackerfinScript:
    """
    Natural language: [x]<b>Battlecry:</b> Give your other
    minions +{0}/+{1}. <i>(Improved
    by each different <b>Bonus
    Keyword</b> in your warband!)</i>

    Formal spec:
      1. battlecry（每次触发）: 按 `_per_trigger_def` 取**基础** CardDef
         （金色引擎触发 2 次 → 总额 = 2×基础 = 金色 CardDef 2/4）
      2. c = 棋盘上出现过的**不同** Bonus Keyword 数——对 6 集
         {DIVINE_SHIELD, REBORN, STEALTH, TAUNT, VENOMOUS, WINDFURY}
         逐 tag 扫描 `m.has(tag)`（"each different" = 去重计数;
         官方定义域见模块 docstring）
      3. 每个"其他友方随从"获得 `Buff(atk=num(0)×(1+c),
         health=num(1)×(1+c))`——"Improved by" = 增量取印面值
         （Inductive Gyroblade / "Has +X for each Y" 家族惯例）
      4. 无其他友方随从 → 落空

    Test: test_batch_payload_minions.py — 0/1/2 个不同关键词时增量分别
    为 num×1/2/3、同关键词不同随从只计 1、金色总额 2×、owner 隔离

    Params: {0}=1 {1}=2（每次触发值 = 基础 CardDef; 金色 2/4 由
             `_per_trigger_def` + 引擎 2 次触发体现）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = _per_trigger_def(game, source)
        others = [m for m in _living_friendly(hero) if m is not source]
        if not others:
            return None
        bonus = sum(1 for tag in _BONUS_KEYWORD_TAGS
                    if any(m.has(tag) for m in hero.board))
        return [Buff(m, atk=d.num(0) * (1 + bonus),
                     health=d.num(1) * (1 + bonus)) for m in others]


# ══════════════════ BG31_830 Weary Mage / BG31_830t Reinvigoration ══════════════════


class WearyMageScript:
    """
    Natural language: [x]<b>Spellcraft:</b> Give a minion
    +2/+2. If it's a Naga,
    also give it <b>Reborn</b>
    until next turn.

    Formal spec:
      1. on_summon: SPELLCRAFT tag 自举（`create_minion` 已由 CardDef
         spellcraft_id 设置，幂等）+ `grant_spellcraft_spell` 立即获得
         第一张法术（RULES §6.13）; 后续每招募阶段由
         `spellcraft.generate_for_hero` 生成
      2. 法术效果本体见 `ReinvigorationScript` / 金色 `_Gt`
      3. 数据链: 基础 spellcraft_id=120896 → `BG31_830t`;
         金色 `_G` spellcraft_id=120897 → `BG31_830_Gt`（+4/+4）

    Test: test_batch_payload_minions.py — 打出后手牌出现 BG31_830t 且带
    SPELLCRAFT tag / 真实 `end_recruit_phase` 后下回合再生成一张

    Params: 无数值模板参数（法术数值在法术脚本内）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        source.set(GameTag.SPELLCRAFT, True)
        grant_spellcraft_spell(source, game)
        return None


class ReinvigorationScript:
    """
    Natural language: Give a minion +2/+2.
    If it's a Naga, also give it <b>Reborn</b> until next turn.

    Formal spec:
      1. needs_target=True（"Give a minion" 定向 → spell_target
         PendingChoice 分流; 无候选则落空）
      2. on_play: 目标 +`_ATK`/+`_HEALTH`; 目标 race ∈ (NAGA, ALL) 时
         额外 `GainKeyword(REBORN)` + 单个 TURN_START once 监听
         （owner=target，condition 控制者匹配）在**下一次招募阶段
         开始**清除 REBORN —— "until next turn" 单 tick 语义
         （Lich King 先例 / RULES §6.13）。
         **永久化分支**（2026-09-14 第二十三轮）: `source.permanent_spellcraft`
         为真（Weary Portrait `BG32_MagicItem_933` 经 `add_permanent_
         spellcraft_rule` 在**生成时**打标，见 `spellcraft.generate_for_
         hero`）→ **不注册**过期监听，Reborn 永久保留。权威: 34.0 官方
         bugfix "retains Reborn from Weary Mage's Reinvigoration
         Spellcraft"（`batch_econ_misc.LavaLurkerScript` 台账同引）。
      3. 目标**已持有** REBORN → 不授予、不注册过期监听（防到期误清
         原生 Reborn）
      4. 非纳迦目标只得 +2/+2（无 Reborn）
      5. 数值来源: 卡面字面量（`BG31_830t`/`_Gt` CardDef 无模板参数，
         文本即权威）

    Test: test_batch_payload_minions.py — 纳迦 +2/+2+Reborn / 非纳迦
    +2/+2 无 Reborn / 下一回合开始 Reborn 清除 / 原生 Reborn 不被误清

    Params: atk=2 health=2（卡面字面量，36.2.2 数据无模板参数）
    """

    needs_target = True

    _ATK = 2
    _HEALTH = 2

    @staticmethod
    def target_candidates(source, game):
        hero = getattr(source, "controller", None)
        if hero is None:
            return []
        return [m for m in hero.board if not m.dead]

    @classmethod
    def on_play(cls, source, game, ctx):
        target = (ctx or {}).get("target")
        if not isinstance(target, Minion):
            return None
        actions = [Buff(target, atk=cls._ATK, health=cls._HEALTH)]
        if target.race in _NAGA_RACES and not target.has(GameTag.REBORN):
            # 永久化命中（Weary Portrait `BG32_MagicItem_933` "Your Weary
            # Mages' Spellcrafts are permanent"）→ Reborn **不注册过期
            # 监听**（+2/+2 本就不带 "until next turn"，唯一临时项是
            # Reborn）。权威: 34.0 官方 bugfix "retains Reborn from Weary
            # Mage's Reinvigoration Spellcraft"（`batch_econ_misc.
            # LavaLurkerScript` 台账同引; "permanent" = keep enchantment）。
            if not getattr(source, "permanent_spellcraft", False):
                def _expire(g, hero=None, **kw):
                    if target.has(GameTag.REBORN):
                        target.clear(GameTag.REBORN)

                game.events.register(Listener(
                    event=TURN_START, owner=target, once=True,
                    condition=lambda hero=None, **kw: hero is target.controller,
                    callback=_expire))
            actions.append(GainKeyword(target, GameTag.REBORN))
        return actions


class ReinvigorationGoldenScript(ReinvigorationScript):
    """
    Natural language: Give a minion +4/+4.
    If it's a Naga, also give it <b>Reborn</b> until next turn.

    Formal spec: 同基础版，`_ATK = _HEALTH = 4`（金色法术
    `BG31_830_Gt` 卡面字面量; 数据链 120897）。

    Test: test_batch_payload_minions.py — 金色法术给 +4/+4（非纳迦）

    Params: atk=4 health=4（卡面字面量，36.2.2 数据无模板参数）
    """

    _ATK = 4
    _HEALTH = 4


# ══════════════════ BG35_437 Vinespeaker ══════════════════


class VinespeakerScript:
    """
    Natural language: [x]After a friendly <b>Deathrattle</b>
    minion dies, your <b>Blood Gems</b>
    give an extra +{0} Attack
    this game.

    Formal spec:
      1. on_summon 注册持久 `death` 监听（owner=source → 出售/招募期
         死亡自动注销; 战斗中战死由引擎监听器快照在战后恢复）
      2. 回调过滤: `minion.controller is hero`（"friendly"）且死者挂有
         亡语（DEATHRATTLE tag 或 deathrattle 脚本钩子）
      3. `ImproveBloodGems(hero, atk=num(0), health=0)`——hero 级
         `BLOOD_GEM_BONUS_ATK` 永久叠加（"this game"; 对之后手牌打出与
         `PlayBloodGems` 两路径的宝石同时生效）
      4. 金色 `_G` num(0)=4（独立卡定义，无需分支）

    Test: test_batch_payload_minions.py — 真实 `_process_single_death`
    下 tag 增加 num(0) 且后续宝石实际 +num(0) / 非亡语随从死亡不触发 /
    对手亡语随从死亡不触发 / 战斗内死亡同样触发 / owner 隔离

    Params: {0}=2（36.2.2 基线; 金色 4 由其 CardDef 自然体现）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_death(g, minion=None, **kw):
            if minion is None:
                return
            hero = source.controller
            if hero is None or minion.controller is not hero:
                return
            if not _has_deathrattle(minion):
                return
            d = g.db.get(source.card_id)
            ImproveBloodGems(hero, atk=d.num(0), health=0).do(g)

        game.events.register(Listener(event=DEATH, owner=source,
                                      callback=on_death))
        return None


# ══════════════════ BG26_801 Rylak Metalhead ══════════════════


class RylakMetalheadScript:
    """
    Natural language: [x]<b>Taunt</b>
    <b>Deathrattle:</b> Trigger the
    <b>Battlecry</b> of an
    adjacent minion.

    Formal spec:
      1. deathrattle: 相邻候选 = 死者让位后板位两侧的存活随从
         （`_adjacent_minions`——真实死亡走 ctx["position"] 残值，存活触发走实际板位）
      2. 空候选 → 落空; 单数 "an adjacent minion" = `rng.choice` 随机
         一只（Obsidian Ravager 同款裁定: 单数随机 / 复数全取，
         batch_rally 先例）
      3. `TriggerBattlecry(pick)`——统一战吼重触发入口（Brann 式
         `BATTLECRY_DOUBLER` 翻倍 / COUNTER_BATTLECRIES / 
         `battlecry_trigger` 广播均由其处理）; 目标无战吼 = 自然落空
      4. Taunt 由 CardDef 关键词映射（数据权威标签）

    Test: test_batch_payload_minions.py — 真实 `_process_single_death`
    触发相邻战吼 / 无相邻落空 / 金色左右两邻均触发 / Titus 在场亡语
    翻倍（战吼触发 2 次）/ 对手随从战吼不触发

    Params: 无数值模板参数
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cands = _adjacent_minions(source, ctx)
        if not cands:
            return None
        pick = game.rng.choice(cands, label="rylak_adjacent")
        return TriggerBattlecry(pick)


class RylakMetalheadGoldenScript(RylakMetalheadScript):
    """
    Natural language: [x]<b>Taunt</b>
    <b>Deathrattle:</b> Trigger the
    <b>Battlecries</b> of adjacent
    minions.

    Formal spec: 同基础版，但取**全部**存活相邻随从（"adjacent
    minions" 复数——左右各一，逐个 `TriggerBattlecry`）。

    Test: test_batch_payload_minions.py — 金色左右两邻战吼各触发一次

    Params: 无数值模板参数
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return [TriggerBattlecry(m)
                for m in _adjacent_minions(source, ctx)] or None


# ══════════════════ BG34_920 Tide Raiser ══════════════════


class TideRaiserScript:
    """
    Natural language: [x]<b>Taunt</b>
    <b>Deathrattle:</b> Cast Shifting
    Tide on an adjacent
    minion.

    Formal spec:
      1. deathrattle: 相邻候选 = 死者让位后板位两侧的存活随从;
         单数 "an adjacent minion" = `rng.choice` 随机一只（Rylak 同款
         裁定 / Obsidian Ravager 先例）
      2. `game.cast_spell_effect(hero, "BG32_815", target=pick)`——
         效果施法统一入口（RULES §7.4.7b）: **不动法术池**、不计
         `TAVERN_SPELLS_CAST_*`、不广播 `card_played`，但广播
         `spell_resolving`/`spell_resolved`; Shifting Tide 自身脚本
         按目标是否纳迦给 2×/4× num
      3. 空候选 → 落空（不施放）
      4. Taunt 由 CardDef 关键词映射

    Test: test_batch_payload_minions.py — 真实死亡路径下相邻随从获得
    Shifting Tide 效果（非纳迦 +2/+2）/ 纳迦 +4/+4 / 无相邻落空 /
    法术池零变化 / 金色左右两邻均被施放

    Params: 无数值模板参数（数额在 Shifting Tide 脚本内）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cands = _adjacent_minions(source, ctx)
        if not cands:
            return None
        pick = game.rng.choice(cands, label="tide_raiser_adjacent")
        game.cast_spell_effect(hero, SHIFTING_TIDE, target=pick)
        return None


class TideRaiserGoldenScript(TideRaiserScript):
    """
    Natural language: [x]<b>Taunt</b>
    <b>Deathrattle:</b> Cast Shifting
    Tide on adjacent
    minions.

    Formal spec: 同基础版，但取**全部**存活相邻随从（复数文本——左右
    各一，逐个 `cast_spell_effect`）。

    Test: test_batch_payload_minions.py — 金色左右两邻均被施放

    Params: 无数值模板参数（数额在 Shifting Tide 脚本内）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        for m in _adjacent_minions(source, ctx):
            game.cast_spell_effect(hero, SHIFTING_TIDE, target=m)
        return None


# ══════════════════ BGS_078 Monstrous Macaw ══════════════════


class MonstrousMacawScript:
    """
    Natural language: [x]<b>Rally:</b> Trigger your
    left-most <b>Deathrattle</b>
    <i>(except this minion's)</i>.

    Formal spec:
      1. rally（攻击宣告时、伤害前）: bearers = 控制者棋盘存活、挂有
         亡语的随从，**排除本体**（"except this minion's"）;
         空 → 落空
      2. "left-most" = 棋盘顺序（左→右）首个合格者
      3. `game.trigger_deathrattle(left, hero=hero)`——统一亡语入口
         （RULES §6.20: Titus `DEATHRATTLE_DOUBLER` / `dr_extra` /
         `dr_first` / `COUNTER_DEATHRATTLES` / `deathrattle_trigger`
         全部生效）; 无死亡发生（目标仍存活——Deathstrider 同构）
      4. `passes` 次（金色 `TB_BaconUps_135` 文本 "twice" = 同一最左
         亡语触发 2 次，Deathstrider 先例）
      5. **条件化追加**（`BG32_MagicItem_803` Macaw Portrait，RULES
         §7.4.17 同一开关通道）: `family_flag(hero, 本卡 id,
         FLAG_MACAW_EXTRA_BATTLECRY)` 生效时，**同一 Rally** 追加
         "trigger your left-most Battlecry" 一次:
           - 候选 = 存活友方中 `game.has_battlecry(m)` 者（**资格集
             口径**，见下），左→右首个; 空 → 该项落空（亡语项照常）
           - 触发 **1 次**——饰品文本无 "twice"；金色文本的 "twice"
             只修饰亡语（`passes=2` 管亡语，本项恒 1）
           - 走 `game.run_actions(TriggerBattlecry(target))` **统一入口**
             （Brann 翻倍 / `COUNTER_BATTLECRIES` / `battlecry_trigger`
             广播 / 无战吼门禁全生效）
           - 时序: 先亡语（`passes` 次）后战吼（"also" 追加项）
           - 含本体: 文本无 "except this minion's"（Macaw 本体无战吼，
             实际无影响）; §7.4.17 门禁保证**无饰品时**本项不存在
         **资格集权威**（为什么不是"字面最左随从"）: 32.2 官方论坛
         复现串 "[32.2] Macaw Portrait + Glowgullet Warlord"
         （2025-05-15）棋盘 `M G x B y z` 明确 Macaw 攻击**同时**触发
         最左亡语 G 与最左**战吼** B，跳过了中间的非战吼 x——即
         "your left-most Battlecry" = 最左**带战吼的**随从（与本体
         卡面 "your left-most Deathrattle" 同构）。

    Test: test_batch_payload_minions.py — 真实攻击路径
    (`CombatScheduler._execute_attack`) 下最左亡语触发 / 排除本体 /
    无亡语落空 / 金色两次 / 对手亡语不触发 / owner 隔离;
    test_batch_trinkets36.py — 追加最左战吼（资格集跳过非战吼者 /
    无饰品负对照 / 金色战吼 1 次 / 统一入口计数）

    Params: 无数值模板参数
    """

    passes = 1

    @staticmethod
    def rally(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        bearers = [m for m in _living_friendly(hero)
                   if m is not source and _has_deathrattle(m)]
        if bearers:
            left = bearers[0]
            for _ in range(source.scripts.passes):
                game.trigger_deathrattle(left, hero=hero)
        # 条件化追加"最左战吼"（Macaw Portrait，RULES §7.4.17）
        if game.family_flag(hero, source.card_id,
                            FLAG_MACAW_EXTRA_BATTLECRY):
            bc = [m for m in _living_friendly(hero)
                  if game.has_battlecry(m)]
            if bc:
                game.run_actions(TriggerBattlecry(bc[0]))
        return None


class MonstrousMacawGoldenScript(MonstrousMacawScript):
    """
    Natural language: [x]<b>Rally:</b> Trigger your left-most
    <b>Deathrattle</b> twice
    <i>(except this minion's)</i>.

    Formal spec: 同基础版，`passes = 2`——最左判定一次，同一亡语连续
    触发 2 次（与 Titus 叠加则每次再翻倍）。

    Test: test_batch_payload_minions.py — 金色一次 Rally 触发同一亡语 2 次

    Params: 无数值模板参数
    """

    passes = 2


#: 条件化"追加最左战吼"开关（RULES §7.4.17）——由 `BG32_MagicItem_803`
#: Macaw Portrait 写入 `hero.family_flags`；常量定义在**载荷侧**（唯一
#: 消费点），饰品侧 import 同一常量。
FLAG_MACAW_EXTRA_BATTLECRY = "macaw_extra_battlecry"


# ══════════════════ BG_OG_221 Selfless Hero ══════════════════


#: 条件化战吼开关（RULES §7.4.17）——由 `BG32_MagicItem_804` Selfless
#: Portrait 写入 `hero.family_flags`（家族行为开关通道 §7.4.16）。
#: 常量定义在**载荷侧**（唯一消费点），饰品侧 import 同一常量。
FLAG_SELFLESS_BATTLECRY = "selfless_hero_extra_battlecry"


class SelflessHeroScript:
    """
    Natural language: <b>Deathrattle:</b> Give a random friendly minion
    <b>Divine Shield</b>.

    Formal spec:
      1. deathrattle: 候选 = 棋盘存活友方随从（本体已离场）;
         空 → 落空
      2. `rng.choice` 随机一只 → `GainKeyword(target, DIVINE_SHIELD)`
         （`GainKeyword` 广播 `keyword_gained`; 已有圣盾者重复授予
         为幂等——圣盾是布尔状态）
      3. 金色独立卡定义 `TB_BaconUps_014` "Give 2 random friendly
         minions" → `rng.sample` 取 min(2, 候选数) 个**互异**目标
         （圣盾为布尔状态，互异采样与"两次独立随机"可观测等价）
      4. **条件化战吼**（RULES §7.4.17）: 本类声明
         `battlecry_flag = FLAG_SELFLESS_BATTLECRY`，`battlecry` 钩子的
         效果与亡语**同一结算函数**（每次触发取 `battlecry_targets` = 基础
         文本 1 只; 金色由引擎触发 2 次 → 总额 2 只，见"金色模型约定"）。
         持 `BG32_MagicItem_804` 时本卡
         **具有战吼**（本体已在场 → 候选含本体）; 无饰品时
         `game.granted_battlecry` 为假 → 钩子落空，且引擎门禁
         `has_battlecry` 亦为假（不消费 War Drum `bc_first`、
         不计入"战吼随从"、不被"触发战吼"效果选中）。
         权威: 32.4 补丁说明（2025-06-02, playhearthstone.com blog
         24205006）Snicker Snacks 条目——"it has a Battlecry from
         Selfless Portrait"。

    Test: test_batch_payload_minions.py — 真实死亡路径下唯一友方获得
    圣盾 / 无友方落空 / 金色两只各获圣盾 / Titus 翻倍后 2 只均有 /
    对手随从不被授予。条件化战吼路径见 test_batch_trinkets35.py
    （真实 play_minion 与 Snicker Snacks R107 触发）。

    Params: 无数值模板参数
    """

    _targets = 1

    #: **每次战吼触发**的目标数 = 基础文本字面量（"a random friendly
    #: minion" = 1）。引擎金色模型约定（`scripts/minions.py` 模块
    #: docstring）: 金色战吼**每次触发用基础值**、由引擎触发 2 次 →
    #: 总额 = 金色文本 "2 random friendly minions"。故本属性不随金色
    #: 覆盖（金色 `_targets=2` 只服务**单次触发**的亡语路径）。
    battlecry_targets = 1

    #: 条件化战吼开关名（None = 无条件战吼）
    battlecry_flag = FLAG_SELFLESS_BATTLECRY

    @staticmethod
    def _give_divine_shield(source, game, k: int):
        """亡语与条件化战吼的**同一结算**（随机 k 只友方获得圣盾）。"""
        hero = source.controller
        if hero is None:
            return None
        cands = _living_friendly(hero)
        if not cands:
            return None
        k = min(k, len(cands))
        picks = game.rng.sample(cands, k, label="selfless_hero_targets")
        return [GainKeyword(m, GameTag.DIVINE_SHIELD) for m in picks]

    @staticmethod
    def deathrattle(source, game, ctx):
        return SelflessHeroScript._give_divine_shield(
            source, game, source.scripts._targets)

    @staticmethod
    def battlecry(source, game, ctx):
        # 条件化战吼的**载荷侧**守卫: 开关未生效（无饰品）→ 落空。
        # 引擎门禁 `has_battlecry` 已按开关过滤，但"触发战吼"类效果
        # （`TriggerBattlecry` / `_gift_echoing_voice`）会直接调脚本钩子，
        # 故此处必须自守——「也触发」不等于「总是触发」。
        if not game.granted_battlecry(source):
            return None
        return SelflessHeroScript._give_divine_shield(
            source, game, source.scripts.battlecry_targets)


class SelflessHeroGoldenScript(SelflessHeroScript):
    """
    Natural language: <b>Deathrattle:</b> Give 2 random friendly minions
    <b>Divine Shield</b>.

    Formal spec: 同基础版，`_targets = 2`——互异随机 2 只（不足 2 只
    时全部获得）。条件化战吼继承基础类（同一函数，`_targets` 动态读取
    → 金色战吼同样"给 2 只随机友方"）。

    Test: test_batch_payload_minions.py — 金色两只友方各获圣盾;
    金色条件化战吼见 test_batch_trinkets35.py

    Params: 无数值模板参数
    """

    _targets = 2


# ══════════════════ BG28_551 Nalaa the Redeemer ══════════════════


class NalaaTheRedeemerScript:
    """
    Natural language: [x]Whenever you cast a Tavern
    spell, give a friendly minion
    of each type +{0}/+{1}.

    Formal spec:
      1. on_summon 注册持久 `tavern_spell_cast` 监听（owner=source →
         离场自动注销）: 事件每次**施放**酒馆法术各广播一次
         （RULES §7.4.10 "cast" 域; 仅 is_pool_spell 法术，
         Spellcraft/血宝石不计）
      2. 回调按 `spell.controller is source.controller` 过滤
         （**owner 隔离**——`tavern_spell_cast` 载荷无 hero 字段，
         对手施放同样广播，必须按法术施放者判定；SOP §12 item 1 的
         "恒真 guard" 陷阱）→ `_each_type_buffs`（10 标准种族各自
         随机一只，ALL 随从每族合格、可重复命中）
      3. `game.run_actions(...)` 施加 `Buff(+num(0)/+num(1))`（永久）
      4. 无可选种族（空棋盘）→ 无 Buff（法术本身照常结算）

    Test: test_batch_payload_minions.py — 真实 `play_spell` 池法术下
    每族代表各 +num(0)/+num(1) / 对手施放不触发 / 非酒馆法术
    （血宝石）不触发 / 金色 num 8/6 / 同 seed 确定性

    Params: {0}=4 {1}=3（36.2.2 基线; 金色 8/6 由其 CardDef 自然体现）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_cast(g, spell=None, **kw):
            hero = source.controller
            if hero is None or spell is None \
                    or spell.controller is not hero:
                return
            d = g.db.get(source.card_id)
            fb = g.giver_bonus(hero, source.card_id)   # Redeemer Portrait
            g.run_actions(_each_type_buffs(
                g, hero, d.num(0) + fb["atk"], d.num(1) + fb["health"],
                "nalaa_target"))

        game.events.register(Listener(event=TAVERN_SPELL_CAST, owner=source,
                                      callback=on_cast))
        return None


# ══════════════════ BG26_157 Bristlebach ══════════════════

# 家族行为开关名（RULES §7.4.16）: Bristlebach Portrait
# `BG32_MagicItem_274` "Your Bristlebachs play Blood Gems on **all
# friendly minions**"（本饰品 `evolution_card_id` → 本卡，数据链已核实）
# → 载荷 avenge 的目标集合由"你的野猪人"放宽为"全体友方随从"。
# 开关名常量定义在**载荷**侧（唯一消费点），饰品侧导入后写入。
FLAG_SCOPE_ALL_FRIENDLY = "bristlebach_scope_all_friendly"


class BristlebachScript:
    """
    Natural language: <b>Avenge (2):</b> This plays 2 <b>Blood Gems</b>
    on all your Quilboar.

    Formal spec:
      1. `avenge_target=2` 由数据（CardDef.avenge_target）经
         `create_minion` 置 `AVENGE_TARGET` tag——引擎在**仅战斗内**
         的友方死亡（含复生死亡）计数达标后调用 `avenge` 并清零
         （RULES §6.11）
      2. avenge: 对控制者棋盘上全部 Quilboar（race == QUILBOAR 或
         ALL）各 `PlayBloodGems(count=_GEMS)`——立即施加 N 颗
         vanilla 血宝石（读 `BLOOD_GEM_BONUS_*` tag；不经手牌、
         不耗金币）
      3. "This plays" = 本体作为来源（`source` 参数，仅追溯）
      4. 金色 `_G` 文本 "plays 4 Blood Gems" → `_GEMS = 4`
      5. **目标集合开关**（RULES §7.4.16）: 若本英雄的家族行为开关
         `FLAG_SCOPE_ALL_FRIENDLY` 命中本卡家族（Bristlebach Portrait
         `BG32_MagicItem_274` 写入）→ 目标 = **全体存活友方随从**
         （不再限定野猪人）; 颗数不变（仍 `_GEMS`）。读取经
         `game.family_flag(hero, source.card_id, ...)`（SOP §12）;
         金色按基础卡 id 归一命中; 对手本卡不受影响（规则在本英雄身上）

    Test: test_batch_payload_minions.py — 战斗内 2 次友方死亡触发、
    Quilboar 各 +2 颗宝石量 / **招募期**死亡不计数不触发 / 未达阈值
    不触发 / 对手 Quilboar 不受影响 / 金色 4 颗 / 开关命中时非野猪人
    友方随从同样 +2 颗（对手仍不受影响）

    Params: count=2（卡面字面量"plays 2"，CardDef 无模板参数）
    """

    _GEMS = 2

    @staticmethod
    def avenge(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        scope_all = game.family_flag(
            hero, source.card_id, FLAG_SCOPE_ALL_FRIENDLY)
        targets = [m for m in _living_friendly(hero)
                   if scope_all or m.race in (Race.QUILBOAR, Race.ALL)]
        if not targets:
            return None
        return [PlayBloodGems(m, source.scripts._GEMS, source=source)
                for m in targets]


class BristlebachGoldenScript(BristlebachScript):
    """
    Natural language: <b>Avenge (2):</b> This plays 4 <b>Blood Gems</b>
    on all your Quilboar.

    Formal spec: 同基础版，`_GEMS = 4`（金色 CardDef 卡面字面量）;
    目标集合开关（§7.4.16）经基础卡 id 归一同样命中（金色 Bristlebach
    吃 Bristlebach Portrait 的"全体友方"改写）。

    Test: test_batch_payload_minions.py — 金色每个 Quilboar +4 颗宝石量；
    开关命中时金色同样作用于全体友方随从（仍 4 颗）

    Params: count=4（卡面字面量"plays 4"，CardDef 无模板参数）
    """

    _GEMS = 4


# ══════════════════ BGS_009 Lightfang Enforcer ══════════════════


class LightfangEnforcerScript:
    """
    Natural language: [x]At the end of your turn,
    give a friendly minion
    of each type +4/+4.

    Formal spec:
      1. end_of_turn: `_each_type_buffs`（10 标准种族各自随机一只，
         ALL 随从每族合格可重复命中——Misplaced Tea Set 先例）;
         每份 `Buff(+4/+4)` 永久
      2. 无友方随从 → 落空
      3. 数值来源: 卡面字面量（CardDef 无模板参数）; 金色独立卡定义
         `TB_BaconUps_082` 文本 "+8/+8" → 独立金色脚本类

    Test: test_batch_payload_minions.py — 真实 EoT 下每个现存种族各一只
    +4/+4 / 同种族两只只 buff 一只（总量 = num）/ 无类型随从不被选中 /
    对手随从不被 buff / 金色 +8/+8 / 同 seed 确定性

    Params: atk=4 health=4（卡面字面量，CardDef 无模板参数）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return _each_type_buffs(game, hero, 4, 4,
                                "lightfang_target") or None


class LightfangEnforcerGoldenScript(LightfangEnforcerScript):
    """
    Natural language: [x]At the end of your turn,
    give a friendly minion
    of each type +8/+8.

    Formal spec: 同基础版，数值 +8/+8（金色 CardDef 卡面字面量）。

    Test: test_batch_payload_minions.py — 金色每个现存种族代表 +8/+8

    Params: atk=8 health=8（卡面字面量，CardDef 无模板参数）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return _each_type_buffs(game, hero, 8, 8,
                                "lightfang_golden_target") or None


# ══════════════════ BG29_873 / BG29_877 Felblood ══════════════════

#: 家族行为开关（RULES §7.4.16）——由 `BG30_MagicItem_869` Felblood
#: Portrait 写入 `hero.family_flags`（batch_trinkets31）。常量定义在
#: **载荷侧**（唯一消费点），饰品侧 import 同一常量（Bristlebach
#: `FLAG_SCOPE_ALL_FRIENDLY` / Impulsive `FLAG_IMPULSIVE_ADJACENT` 同构）。
#: "Your **Fiery and Slimy Felbloods give Attack and Health**"——命中后
#: 两个载荷各自在原有单属性 give 之外再 give 另一属性，数值 = 该卡自身
#: 印面额（2 基础 / 4 金色; 权威推导见 batch_trinkets31
#: `FelbloodPortraitScript` docstring）。
FLAG_FELBLOOD_ALSO = "felblood_give_attack_and_health"

#: Fiery Felblood 家族金色 id（`BG29_877` 的 `triple_upgrade_id`=109744 →
#: `BG29_877_G`）。**非数值身份标识**: "Your Fiery and Slimy Felbloods"
#: 点名两个家族，而饰品数据链 `evolution_card_id=109418` 只给出 Slimy
#: （`BG29_873`）——第二家族 id 由卡面点名 + `bg_cards.json` 逐卡核实
#: （全库仅两张 "Felblood": `BG29_873` Slimy / `BG29_877` Fiery，
#: dbf 109418/109744）确定，非经验值（OozelingGladiatorScript 的
#: `BG27_002t` 先例）。
SLIMY_FELBLOOD = "BG29_873"
SLIMY_FELBLOOD_G = "BG29_873_G"
FIERY_FELBLOOD = "BG29_877"
FIERY_FELBLOOD_G = "BG29_877_G"


class SlimyFelbloodScript:
    """
    Natural language: <b>Battlecry:</b> Minions in the Tavern have +2
    Health this game.

    Formal spec:
      1. battlecry: `TavernBuff(health=_AMOUNT)` 登记持久面
         （`hero.tavern_buffs`，`refresh_tavern` 对之后入馆的随从自动
         应用）+ `BuffCurrentTavern` 立即面（当前馆内全部随从）
      2. "this game" = 持久，非 "this turn"（无回合过期监听）;
         馆内无随从时持久面照常登记（之后入馆的随从仍获得）——非落空
      3. **家族行为开关**（RULES §7.4.16，2026-09-19）: 若本英雄命中
         `FLAG_FELBLOOD_ALSO`（Felblood Portrait `BG30_MagicItem_869`
         写入）→ 同一次 TavernBuff 追加 `atk=_AMOUNT`（"also give
         Attack"，数值 = 本卡自己的印面额; 推导见 batch_trinkets31
         `FelbloodPortraitScript` docstring）。读取经
         `game.family_flag(hero, source.card_id, ...)`（SOP §12）
      4. 金色 `_G` "+4 Health"（卡面字面量）: 引擎金色战吼触发 2 次 ×
         基础 `_AMOUNT=2` → 总额 +4（`FelementalScript` 同口径; 故金色
         注册复用**基础类**而非独立类）

    Test: test_batch_payload_minions.py — 当前馆内 +2 血 / 刷新后新入馆
    随从同样获得 / 对手酒馆不受影响 / 金色总额 2×。test_batch_trinkets31.py
    （Felblood Portrait 行为层）— 命中开关时同一次战吼 +2/+2 / 对照
    无饰品 +0/+2。

    Params: health=_AMOUNT=2（卡面字面量"+2 Health"，CardDef 无模板参数）
    """

    _AMOUNT = 2

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        amount = source.scripts._AMOUNT
        also = game.family_flag(hero, source.card_id, FLAG_FELBLOOD_ALSO)
        buff = TavernBuff(atk=amount if also else 0, health=amount,
                          source_id=source.card_id)
        return [ApplyTavernBuff(hero, buff), BuffCurrentTavern(hero, buff)]


class FieryFelbloodScript:
    """
    Natural language: <b>Deathrattle:</b> Minions in the Tavern have +2
    Attack this game.

    Formal spec:
      1. deathrattle: `TavernBuff(atk=_AMOUNT)` 登记持久面 + 立即面
         （与 `SlimyFelbloodScript.battlecry` 同构，仅属性面相反）
      2. "this game" 持久; 馆内无随从时持久面照常登记（非落空）
      3. **家族行为开关**（RULES §7.4.16）: 命中 `FLAG_FELBLOOD_ALSO`
         时同一次 TavernBuff 追加 `health=_AMOUNT`（"also give Health"）
      4. 金色独立卡定义 `BG29_877_G` "+4 Attack": **引擎不自动翻倍金色
         亡语**（`Game._trigger_deathrattle` 仅 Titus/配额倍率）→ 独立
         金色类 `_AMOUNT=4`（对照 `ImpulsiveTricksterGoldenScript`
         `_applications=2` 先例）

    Test: test_batch_payload_minions.py — 真实死亡路径馆内 +2 攻 /
    招募期死亡同样触发（亡语非战斗内专属）/ 对手不受影响 / 金色 +4。
    test_batch_trinkets31.py — 命中开关时同一次亡语 +2/+2 / 对照
    无饰品 +2/+0。

    Params: atk=_AMOUNT=2（卡面字面量"+2 Attack"，CardDef 无模板参数;
             金色 _AMOUNT=4）
    """

    _AMOUNT = 2

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        amount = source.scripts._AMOUNT
        also = game.family_flag(hero, source.card_id, FLAG_FELBLOOD_ALSO)
        buff = TavernBuff(atk=amount, health=amount if also else 0,
                          source_id=source.card_id)
        return [ApplyTavernBuff(hero, buff), BuffCurrentTavern(hero, buff)]


class FieryFelbloodGoldenScript(FieryFelbloodScript):
    """
    Natural language: <b>Deathrattle:</b> Minions in the Tavern have +4
    Attack this game.

    Formal spec: 同基础版，`_AMOUNT = 4`（金色 CardDef 卡面字面量; 金色
    亡语不被引擎自动翻倍）。家族行为开关命中时同样追加 `+4 Health`。

    Test: test_batch_payload_minions.py — 金色馆内 +4 攻; 开关命中 +4/+4。

    Params: atk=_AMOUNT=4（卡面字面量"+4 Attack"）
    """

    _AMOUNT = 4


# ══════════════════ 注册 ══════════════════

# （含金色 id——金色 = 独立卡定义; 逐张经 db.golden_version 核实）
_REGISTRATIONS = [
    (IMPULSIVE, ImpulsiveTricksterScript),
    (IMPULSIVE_G, ImpulsiveTricksterGoldenScript),
    (FALSE_IMPLICATOR, FalseImplicatorScript),
    (FALSE_IMPLICATOR_G, FalseImplicatorGoldenScript),
    (FELEMENTAL, FelementalScript),
    (FELEMENTAL_G, FelementalScript),           # num 同基础，引擎 2 次触发
    (HACKERFIN, HackerfinScript),
    (HACKERFIN_G, HackerfinScript),             # _per_trigger_def 回基础
    (WEARY_MAGE, WearyMageScript),
    (WEARY_MAGE_G, WearyMageScript),            # spellcraft_id 直指金法术
    (REINVIGORATION, ReinvigorationScript),
    (REINVIGORATION_G, ReinvigorationGoldenScript),
    (VINESPEAKER, VinespeakerScript),
    (VINESPEAKER_G, VinespeakerScript),         # num(0)=4 自然体现
    (RYLAK, RylakMetalheadScript),
    (RYLAK_G, RylakMetalheadGoldenScript),
    (TIDE_RAISER, TideRaiserScript),
    (TIDE_RAISER_G, TideRaiserGoldenScript),
    (MACAW, MonstrousMacawScript),
    (MACAW_G, MonstrousMacawGoldenScript),
    (SELFLESS_HERO, SelflessHeroScript),
    (SELFLESS_HERO_G, SelflessHeroGoldenScript),
    (NALAA, NalaaTheRedeemerScript),
    (NALAA_G, NalaaTheRedeemerScript),          # num 8/6 自然体现
    (BRISTLEBACH, BristlebachScript),
    (BRISTLEBACH_G, BristlebachGoldenScript),
    (SLIMY_FELBLOOD, SlimyFelbloodScript),
    (SLIMY_FELBLOOD_G, SlimyFelbloodScript),    # "+4" = 引擎金色战吼 2 次
    (FIERY_FELBLOOD, FieryFelbloodScript),
    (FIERY_FELBLOOD_G, FieryFelbloodGoldenScript),
    (LIGHTFANG, LightfangEnforcerScript),
    (LIGHTFANG_G, LightfangEnforcerGoldenScript),
]


def register() -> list[str]:
    """注册本批 13 张载荷随从（+ 法术塑造法术 2 id），返回注册 id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []
    for card_id, script_cls in _REGISTRATIONS:
        _register(card_id, script_cls)
        registered.append(card_id)
    return registered
