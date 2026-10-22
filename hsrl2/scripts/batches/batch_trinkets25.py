"""批次 trinkets25 — 饰品第二十五批（作业单 2026-09-14，20 张）。

台账来源: `docs/agents/TRINKET_LEDGER.md` 片 3/4（BG32_MagicItem_809 …
BG35_MagicItem_818）。20 张全部经运行核验在
`CardDB.trinket_offer_pool()` 中（20/20；商店本体，无内部 token / 升级
变体混入），且与 batch_trinkets1..24 的 id 集合互不相交（注册前
`REGISTRY` 核实：20/20 均未注册）。

**结果（2026-09-18 复核）: 1 张 CORRECT 注册 + 4 张 DEFERRED + 15 张
迁出注册**（原始快照为 1 + 19；逐轮迁移后收敛。SOP §6b 二态铁律——
语义不确定即撤注册，禁止"已注册但近似/空转"第三态）。

注册（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG35_MagicItem_702 Stegodon Portrait — "Get a Stomping Stegodon.
      **Start of Combat:** Give your two left-most Beasts **Divine
      Shield**."
      - `on_bind`: 交付关联卡**白板**副本进手牌（`grant_card_copy_to_hand`;
        满手排队 RULES §3.3）。关联卡解析见下节「关联卡解析」。
      - `start_of_combat`: 本人棋盘按位置取**最左两只**野兽
        （race ∈ (BEAST, ALL)——Amalgam 规则 RULES §8/§6.19）各
        `GainKeyword(DIVINE_SHIELD)`; 战斗期授予，战后由 `run_combat`
        战前快照回滚（RULES §3.5 "战斗阶段 Buff 战后消失"）。
      - `Params`: 无模板参数（`CardDef.num(0..3)` 全 None）; "two" 是
        文本字面量（SOP §3 允许并在 `_STEGODON_BEASTS` 声明）。
      - 池记账: 关联卡 `BG33_840` 在 36.2.2 是 `is_pool_minion=False`
        （池外卡）→ 交付/出售均**零池操作**（`MinionPool.release` 对
        池外卡 no-op）；RULES §2.3 未为效果副本设例外，但彼条只适用于
        池内卡。

关联卡解析（RULES §7.4.6 两段协议；本卡属"数据链缺失"例外情形）
═══════════════════════════════════════════════════════════════════════
  `BG35_MagicItem_702` 的 XML 实体（`hsdata/CardDefs.xml` L245446-245506,
  dbf 130897）**没有** `BACON_EVOLUTION_CARD_ID`(2519)（逐 tag 核实；
  对照同族 156 有 2519=126924）→ `game.trinket_related_card` 恒 None。
  本批的 `_related_card` 采用**两段解析**（零硬编码 id）:
    1. 数据链优先: `game.trinket_related_card(trinket_id)`（未来数据补齐
       后自动生效）;
    2. 数据链缺失 → 从本卡 `CardDef.text` 抠出 "Get a <名称>." 的名称，
       在 `CardDB` 全量定义中做**唯一名**匹配（`card_type == MINION`
       且非金卡定义）；命中数 ≠ 1 → 落空（不猜、不近似）并记审计日志。
  名称由 wiki 权威佐证: hearthstone.wiki.gg/Battlegrounds/Stegodon_Portrait
  的 "Related cards" 段明示生成 *Stomping Stegodon*（dbf 130897 页面）。
  36.2.2 数据核实该名称在 CardDB 中唯一命中 `BG33_840`（金卡本体
  `BG33_840_G` 被 `is_golden_def` 过滤）。
  **数据层缺口上报主线**: 补齐该卡的 `evolution_card_id`（或主线裁定
  引擎按唯一卡名回退解析）后，本卡自动走数据链。

近两轮新引擎原语逐张评估（SOP §15/§16c；本轮 20 张全过一遍）
═══════════════════════════════════════════════════════════════════════
  - `game.trigger_deathrattle(target, *, hero, position, count)` /
    `deathrattle_trigger` 事件: 431t（"After you trigger a
    **Deathrattle**"）本就监听事件即可，其阻塞项是数值通道（见下）;
    156 的 "trigger" 指**该随从的 EoT 吞噬触发**，不是亡语 → 不适用。
  - `game.grant_combat_deathrattle`: 本批 20 张无"战斗内授予亡语"文本
    → 不适用（该原语的阻塞卡已在 trinkets23 迁移）。
  - `game.add_tier_aura`: 本批无 "Tier N or lower" 文本 → 不适用。
  - ~~`game.add_permanent_spellcraft_rule`: 933 Weary Portrait 属此族。~~
    本批原记"双重阻塞（载荷未注册 + 规则缺拦截点）"**已全部消除**:
    载荷 2026-09-02 由 `batch_payload_minions` 注册; 关键词口径由
    `batch_trinkets37`（2026-09-14）+ 引擎施放期回写落地 → **已注册**
    （RULES §7.4.7a / §7.4.7a 关键词注 / `ENGINE_BACKLOG` #23/#26）。
  - `game.add_tavern_entity` / `tavern_entity_added`（RULES §7.4.9）:
    891 Finley's Helmet 的"入馆即结算"顺序问题可解，但其阻塞项是
    **Bonus Keyword 定义域**（RULES §9.6）→ 不解冻; 743 的**价格半场**
    可由该事件覆盖（连 Toki/Tess/Varden 注入路径一并覆盖，不再漏价），
    但"额外展示的**那一张**必须是 Magnetic Mech"无关键词限定抽取点 →
    整卡仍 DEFERRED（半实现 = 第三态）。
  - `game.cast_spell_effect`（RULES §7.4.7b）: 本批无"Cast X"文本；
    755 的 "Refresh the Tavern with Battlecry minions" 是**刷新内容**
    协议而非施法协议 → 不解冻。
  - `grant_card_copy_to_hand` 返回 True = 已产生（含入队）: 702 的交付
    路径即此（无额度语义）; 820/824/830/925/433 的阻塞是**关联卡
    脚本未迁移**（~~933~~ 载荷已注册 → 已注册 batch_trinkets37），返回
    值语义不改变该阻塞。
  - `Transform` / `on_transform`（RULES §6.21）: 本批无"变为"文本。
  - `card_gained` / `card_discovered(golden=)`: 本批无 "After you get a
    card" 文本；812 的 Triple Prize 阻断在 Darkmoon 子系统（见下）。
  - `spell_resolving`（per-cast，RULES §7.4.10）: 本批无 "After you
    **cast**" 文本；431t 是 deathrattle 域、892 无施放计数文本。
  - 结论: 近两轮原语**没有**解锁本批任何此前 DEFERRED 的卡；唯一新注册
    （702）的阻塞项属**数据层**（关联卡数据链缺失），本批以运行时唯一名
    解析闭环。

DEFERRED 4 张（**不注册**；逐张 Status / Dependency / Implementation
path 见下方各类 docstring，索引如下）。
本批 20 张作业范围的其余 16 张已迁出（1 张 CORRECT = 702; 15 张由
batch_unlock_final/30/31/37/39 注册）——**权威清单 = `test_batch_trinkets25.py`
的 `IMPLEMENTED` / `DEFERRED` / `MIGRATED` 三个元组**；下方 A–D 索引为
2026-09-15 复评快照，已迁出者在 2026-09-16/18 复核中标 ~~删除线~~。
═══════════════════════════════════════════════════════════════════════
  A. 语义无权威（SOP §6b 第 4 步；本轮已复查信源，无新证据）
     - BG32_MagicItem_809 Gem Donation（"plays its Blood Gems" 三种读法）
     - BG32_MagicItem_823 Wax Imprinter（"(if possible)" 限定对象）
  B. 载荷/读取点未就绪（RULES §7.4.6 例外条 / SOP §12 item 14）
     - ~~BG32_MagicItem_820 Impulsive Portrait~~（**已注册**
       batch_trinkets39, 2026-09-18: 载荷 `BG21_006`/`_G` 已由
       batch_payload_minions 注册; §7.4.16 `hero.family_flags` 目标集合
       改写 + 6/6 覆盖式交付。原"唯一真阻塞 = 数额语义无权威"按 owner
       权威序消除: wiki 页无 Notes → 卡面天然语言裁定 = **全额逐目标**
       （非均分; 文本无 "split"/"divided"），金色两个实例各打相邻集合）
     - BG32_MagicItem_824 Implicator Portrait（载荷 `BG29_140` 已注册;
       残余 = `ConsumeRandomTavernMinion` 无英雄级目标策略读取点）
     - BG35_MagicItem_812 Corrupted Tome（三连奖励替换钩子 + Darkmoon Prize）
     - ~~BG32_MagicItem_830 Felemental Portrait~~（**已注册**
       batch_trinkets31, 2026-09-15; 载荷 BG25_041 亦已注册）
     - ~~BG32_MagicItem_925 Hackerfin Portrait~~（**已注册**
       batch_trinkets30; 载荷 BG31_148 亦已注册）
     - ~~BG32_MagicItem_933 Weary Portrait~~（**已注册** batch_trinkets37, 2026-09-14）
     - ~~BG35_MagicItem_433 Vinespeaker Portrait~~（**已注册**; 载荷
       BG35_437 亦已注册）
  C. ~~引擎缺口（原语缺失）~~ — 以下 8 项**均已由 batch_unlock_final
     注册**（2026-09-15: consume 来源区域 / last_minion_died 触发点 /
     add_card_aura / 关键词限定价格·展示位 / 战吼刷新 / death 事件血宝石
     生命），仅存历史记录:
     - ~~BG32_MagicItem_902 Statue of Hir'eek~~
     - ~~BG32_MagicItem_907 S'Thara Sticker / BG35_MagicItem_732 Soul
       Fermenter~~
     - ~~BG35_MagicItem_156 Flaming Portrait~~
     - ~~BG35_MagicItem_743 Electrode Attractor~~
     - ~~BG35_MagicItem_755 Chillmere Mosaic~~
     - ~~BG35_MagicItem_818 Mysterious Orb~~
     - ~~BG35_MagicItem_431t Thornspike Pauldron~~
  D. ~~Bonus Keyword 定义域~~ — **已由 batch_trinkets30 注册**:
     - ~~BG32_MagicItem_891 Finley's Helmet / BG32_MagicItem_892 Vibrant
       Bubble（+ `BG32_MagicItem_892t` Spellcraft 法术）~~

关联卡台账（RULES §7.4.6 —— "Get a X" 交付正确即 CORRECT；被交付卡
自身脚本未迁移只登记、不阻塞，除非本卡效果**依赖**其行为）
═══════════════════════════════════════════════════════════════════════
  | 饰品 | 关联卡（数据链 dbf → id / 解析方式） | 被授予卡脚本状态 |
  |---|---|---|
  | BG32_MagicItem_702 | **无数据链** → 唯一名解析 `BG33_840` Stomping
  | Stegodon（非池 T4 4/4 野兽） | **未注册**（Rally 脚本缺失）——
  | 本卡只交付、不依赖其行为 → 不阻塞 |
  | BG32_MagicItem_820 | 72059 → BG21_006 Impulsive Trickster（非池）
  | | **未注册 → 整卡 DEFERRED**（§7.4.6 例外） |
  | BG32_MagicItem_824 | 108115 → BG29_140 False Implicator（非池）
  | | **未注册 → 整卡 DEFERRED**（§7.4.6 例外） |
  | BG32_MagicItem_830 | 97553 → BG25_041 Felemental（非池） |
  | **未注册 → 整卡 DEFERRED**（§7.4.6 例外） |
  | BG32_MagicItem_925 | 115848 → BG31_148 Hackerfin（非池） |
  | **未注册 → 整卡 DEFERRED**（§7.4.6 例外） |
  | BG32_MagicItem_933 | 119921 → BG31_830 Weary Mage（非池）+
  | spellcraft_id 120896 → BG31_830t Reinvigoration | ~~双双未注册 → 整卡
  | DEFERRED~~ → **已注册**（batch_trinkets37, 2026-09-14: 载荷已注册 +
  | 关键词永久化分支） |
  | BG35_MagicItem_156 | 126924 → BG34_500 Flaming Enforcer（池 T4） |
  | **已注册**（batch_consume）但触发扩展点缺失 → 整卡 DEFERRED |
  | BG35_MagicItem_433 | 130157 → BG35_437 Vinespeaker（非池） |
  | 未注册 → 整卡 DEFERRED（§7.4.6 例外） |
  | BG35_MagicItem_702 之外无 Spellcraft 本体需注册（892/755 的
  | Spellcraft 法术属 DEFERRED 卡，不注册） |
  说明: `BG32_MagicItem_809` / `_823` / `_891` / `_892` / `_902` /
  `_907` / `BG35_MagicItem_431t` / `_732` / `_743` / `_755` / `_812` /
  `_818` 在 CardDB 中 `evolution_card_id is None`（数据链无关联卡，
  36.2.2 逐条核实），无台账行。

接线审计读取点（W1/W2/W3/W5 核对）
═══════════════════════════════════════════════════════════════════════
  - W1: 本批仅 `BG35_MagicItem_702` 进 REGISTRY，只定义饰品白名单内的
    `on_bind` / `start_of_combat`; 19 张 DEFERRED 类**无任何钩子方法**
    （仅 docstring 台账），不产生死钩子。
  - W2: 不注册任何 `Listener`（无事件监听）。
  - W3: 不写 `game._x` / `hero._x` 私有标记。
  - W5: 导入符号 `CardDef`（hsrl2.defs）/ `GainKeyword`（hsrl2.actions）
    / `CardType`/`GameTag`/`Race`（hsrl2.tags）均存在。
  - 数值纪律: 本批唯一数值是文本字面量 "two"（`_STEGODON_BEASTS`）;
    其余全部来自 `CardDef.num(i)` / 运行时属性——无硬编码数值。
"""

from __future__ import annotations

import re
from typing import Optional

from hsrl2.actions import GainKeyword
from hsrl2.defs import CardDef
from hsrl2.tags import CardType, GameTag, Race

# ── 本批卡 id（CardDB 按名核实，禁止凭记忆写） ──
STEGODON_PORTRAIT = "BG35_MagicItem_702"    # Stegodon Portrait（Lesser）

# ── 文本字面量（CardDef num 全 None，SOP §3 允许并在此声明） ──
_STEGODON_BEASTS = 2        # "your two left-most Beasts" 的 "two"

# Amalgam 规则: ALL 视为一切种族（RULES §8 / §6.19 种族匹配）
_BEAST_RACES = (Race.BEAST, Race.ALL)

# "Get a <卡>." 名称抠取（数据链缺失时的唯一名回退解析）
_RELATED_NAME_RE = re.compile(r"Get (?:a|an) ([^.\n]+)\.")
_MARKUP_RE = re.compile(r"<[^>]*>|\[x\]")


def _hero(ctx):
    return (ctx or {}).get("hero")


def _strip_markup(text: str) -> str:
    """去掉卡片文本的 HTML 标记与 `[x]` 前缀（名称抠取用）。"""
    return _MARKUP_RE.sub("", text or "")


def _related_card(game, trinket_id: str) -> Optional[CardDef]:
    """解析 "Get a <卡>" 的关联卡定义（RULES §7.4.6 两段协议）。

    1. **数据链优先**: `game.trinket_related_card`（`CardDef.evolution_card_id`
       → `CardDB.by_dbf`）。
    2. **数据链缺失时的唯一名回退**（`BG35_MagicItem_702` 适用）:
       XML 无 `BACON_EVOLUTION_CARD_ID`(2519) → 从本卡 `CardDef.text` 抠出
       "Get a <名称>." 的名称，在 CardDB 全量定义中唯一名匹配随从定义
       （`card_type == MINION` 且非金卡定义）。
       - 命中数 ≠ 1 → 返回 None（落空，不猜、不近似）并记审计日志;
       - **不使用硬编码 card_id**（SOP §11 item 5）。

    wiki 佐证: https://hearthstone.wiki.gg/wiki/Battlegrounds/Stegodon_Portrait
    "Related cards" 段明示生成 Stomping Stegodon（36.2.2 CardDB 唯一命中
    `BG33_840`）。
    """
    card = game.trinket_related_card(trinket_id)
    if card is not None and card.card_type == CardType.MINION \
            and not card.is_golden_def:
        return card
    d = game.db.get(trinket_id)
    if d is None:
        return None
    m = _RELATED_NAME_RE.search(_strip_markup(d.text))
    if m is None:
        return None
    name = m.group(1).strip()
    hits = [x for x in game.db._by_id.values()
            if x.card_type == CardType.MINION
            and not x.is_golden_def and x.name == name]
    if len(hits) != 1:
        game.dark_gift_audit_log.append(
            f"STEGODON_RELATED_UNRESOLVED: {trinket_id} name={name!r} "
            f"hits={len(hits)}")
        return None
    return hits[0]


# ══════════════════ BG35_MagicItem_702 Stegodon Portrait（CORRECT） ══════════════════


class StegodonPortraitScript:
    """
    Natural language: [x]Get a Stomping Stegodon.
    <b>Start of Combat:</b> Give
    your two left-most Beasts
    <b>Divine Shield</b>.

    Formal spec:
      1. on_bind: 解析关联卡（数据链优先 / 唯一名回退，见 `_related_card`）
         并交付一张**白板**副本进控制者手牌（`grant_card_copy_to_hand`;
         满手 → `pending_hand_queue` 等待，RULES §3.3）; 解析失败 → 落空
         （不抛错）。关联卡 `BG33_840` 池外（`is_pool_minion=False`）→
         零池操作。
      2. start_of_combat（**饰品** SoC 钩子，先于棋盘随从与英雄技能——
         RULES §6.12 顺序: 饰品 → 任务奖励 → 棋盘 → 手牌 hand_soc）:
         目标 = 控制者棋盘中 race ∈ (BEAST, ALL) 的存活随从，按棋盘
         从左到右取**前 2 个**（不足 2 个 → 全部）; 空/无野兽 → 落空。
      3. 每个目标 `GainKeyword(DIVINE_SHIELD)`（战斗期授予——`run_combat`
         的战前快照在 SoC 之前采集，战后回滚，RULES §3.5）。
      4. 只作用于控制者本人棋盘（owner 隔离）。

    Test: test_batch_trinkets25.py — 绑定后本人手牌恰 1 张 Stomping
      Stegodon（正对照: 未绑定 0 张）/ 真实 `run_combat` 的
      `start_of_combat` 探针读到最左两只野兽带圣盾、第三只野兽与非野兽
      不带 / 战后回滚 / 对手手牌与对手野兽不变 / 满手入队 / 同 seed 重跑
      一致。

    Params: 无模板参数（`CardDef.num(0..3)` 全 None）; "two" = 文本字面量
    （`_STEGODON_BEASTS`，36.2.2 卡面原文 "your two left-most Beasts"）。
    金色: 饰品无金色本体（`triple_upgrade_id=None`）; 交付物是**基础**
    Stomping Stegodon（文本无 Golden → 金卡定义被 `_related_card` 过滤）。
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        card = _related_card(game, source.card_id)
        if card is None:
            return None
        game.grant_card_copy_to_hand(h, card)
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        beasts = [m for m in h.board
                  if not m.dead and m.race in _BEAST_RACES]
        if not beasts:
            return None
        return [GainKeyword(m, GameTag.DIVINE_SHIELD)
                for m in beasts[:_STEGODON_BEASTS]]


# ══════════ DEFERRED（不注册；每类 docstring = Status/Dependency/实现路径） ══════════
#
# 说明: 下列 19 个类**没有任何钩子方法**——它们是台账载体（SOP §6 的
# DEFERRED 格式），不对应任何 REGISTRY 条目。注册它们才是违规。


class GemDonationScript:
    """
    Natural language: [x]The first minion you sell
    each turn plays its <b>Blood
    Gems</b> on the 3 highest-Tier
    minions in the Tavern.

    Status: DEFERRED — "plays its Blood Gems" 的**宝石枚数/来源**无权威
      读法，三种候选在野猪人高宝石局面数值差异巨大:
        (a) 按 `GEMS_PLAYED_ON` 枚数、每颗对 3 个目标各施放一次（3×N 颗）;
        (b) 共 N 颗轮转分配到 3 个目标;
        (c) 每目标固定 1 颗（共 3 颗）。
    Dependency: 官方 Notes / 实测录像（非引擎缺口——`minion_sold` 事件
      与 `GEMS_PLAYED_ON` + `PlayBloodGems` 均已就绪，裁定后分钟级实现）。
    Implementation path: 监听 `minion_sold`（`game.sell_minion` 广播）+
      每回合 first-sell 记账（hero 级/source 级闭包）→ 取本人酒馆
      `tech_level` 最高的 3 只（并列按既有 rng/位置口径）→ 按裁定读法施放。
    Test: 未实现（不注册）。
    """


class WaxImprinterScript:
    """
    Natural language: [x]Gain 2 Gold and take
    2 damage. At the start
    of each turn, repeat this
    <i>(if possible)</i>.

    Status: DEFERRED — `(if possible)` 的**限定对象**无权威读法
      （金币上限 / 生命不足以承受 2 点伤害 / 仅未阵亡）。
    Dependency: 官方裁定或实测（非引擎缺口）。本轮复查信源:
      - hearthstone.wiki.gg/Battlegrounds/Wax_Imprinter（无 Notes 段）;
      - 32.2.0 / 32.4.2 / 33.0.0 补丁历史（32.4.2 只把"立即获得"从句首
        移到句首，未澄清限定对象; 33.0.0 修的是"回合开始而非战斗开始"）;
      - 12 语种文本（全部同义 "(if possible)"）。
      与 batch_trinkets1 / batch_trinkets7 / batch_trinkets15 的既有裁定
      一致（无新证据）。
    Implementation path: 裁定后 `on_bind` + 每回合 `start_of_turn` 执行
      `GainGold(h, 2)` + `h.take_damage(2)`（2 为文本字面量，CardDef 无
      模板参数），并按裁定加守卫（如 `h.health + h.armor > 2`）。
    Test: 未实现（不注册）。
    """


class ImpulsivePortraitScript:
    """
    Natural language: [x]Get a 6/6 Impulsive
    Trickster. Your Impulsive
    Tricksters' <b>Deathrattles</b>
    target adjacent minions.

    Status: ✅ **已迁出 → batch_trinkets39**（2026-09-18）。

    迁移依据（owner 权威序）: 原唯一阻塞 = "target adjacent minions" 的
    数额口径无权威（全额 vs 均分）。复核确认
    hearthstone.wiki.gg/Battlegrounds/Impulsive_Portrait（oldid=907061）
    **无 Notes 段** → 按卡面天然语言裁定: 饰品句的 "target" 替换载荷的
    目标短语 "another friendly minion"（单数）→ 复数集合; "give X to
    <集合>" = 每个成员各得全额 X（非均分——两张卡文本均无
    "split"/"divided" 字样，均分读法必须凭空发明拆分规则）。完整推导与
    边界见 `batch_payload_minions.ImpulsiveTricksterScript` docstring
    §4–6。
    实现: 饰品 `on_bind` 经数据链 `evolution_card_id`(72059) 交付 6/6
    本体（`create_minion` + BASE_ATK/HEALTH/HEALTH=6，CuratorSticker 先例）
    + 写 `FLAG_IMPULSIVE_ADJACENT`; 载荷经 `game.family_flag` 读取后把
    目标集合改为 `_adjacent_minions(source, ctx)`。守卫见
    `hsrl2/tests/test_batch_trinkets39.py`。
    Test: 已实现（见 test_batch_trinkets39.py）。
    """


class ImplicatorPortraitScript:
    """
    Natural language: Get 2 False Implicators. Your Demons always consume
    the highest-Health minion in the Tavern.

    Status: ✅ **已迁出 → batch_trinkets31**（2026-09-19，owner 权威序: wiki 页无 Notes → 卡面天然语言）; 原阻塞 — **吞噬目标策略读取点缺失**。
    Dependency: (a) 关联卡 `BG29_140`/`BG29_140_G` False Implicator 已由
      batch_payload_minions 注册（2026-09-16 复核）→ 本项阻塞关闭;
      (b) "Your Demons **always** consume the highest-Health minion" 是
      `ConsumeRandomTavernMinion` 的选择策略改写，引擎该 Action 恒
      `rng.choice(hero.tavern)`，无 hero 级策略读取点（脚本自行预选目标
      无法改变引擎的随机选择）。
    Implementation path: (a) 先迁 `BG29_140`（+金色 `BG29_140_G`，交付
      2 份）; (b) 引擎在吞噬目标选择处读取 hero 级策略（如
      `hero.consume_target_rule == "highest_health"` → `max(m.max_health)`，
      并用 `game.rng` 处理并列）后本卡 on_bind 写该策略。
    Test: 未实现（不注册）。
    """


class FelementalPortraitScript:
    """
    Natural language: [x]Get a Felemental.
    Your Felementals give
    an extra +{0}/+{1}.

    Status: 已注册（batch_trinkets31, 2026-09-15）——历史台账，保留备查。
    Dependency（已关闭）: 关联卡 `BG25_041` Felemental 已由
      batch_payload_minions 注册（其战吼经 `TavernBuff` 落地）; 本卡的
      "give an extra +{0}/+{1}" 经家族 give 通道在 batch_trinkets31 落地
      → 不再存在"写 hero 级标记 = W3 空转"的问题（SOP §11 item 3 /
      §14 item 1 的假接线教训，当时据此 DEFERRED）。
    Implementation path（已执行）: `BG25_041` 已迁; 本饰品 on_bind 写
      `(num(0), num(1)) = (2, 2)`（36.2.2 数据核实）。
    Test: `test_batch_trinkets31.py`（本批台账守卫不再覆盖本卡）。
    """


class FinleysHelmetScript:
    """
    Natural language: [x]After the Tavern is
    <b>Refreshed</b>, give Murlocs
    in it +5/+5 and a random
    <b>Bonus Keyword</b>.

    Status: DEFERRED — **Bonus Keyword 定义域无数据字段**（RULES §9.6
      2026-09-02 主线裁定钉死）。
    Dependency: (1) 官方/patch notes 佐证 `BONUS_KEYWORD_SET`（"Bonus
      Keyword" 相对随从天生关键词的定义域）; (2) 新 tag
      `BONUS_KEYWORDS_GRANTED`（逐实体记录被授予的 bonus 关键词）。
      注: "入馆即结算"的顺序问题**已由引擎解决**（`game.add_tavern_entity`
      / `tavern_entity_added`，RULES §7.4.9）——本卡的阻塞项只剩 Bonus
      Keyword 定义域（"+5/+5" 侧可直接实现，但半实现 = 第三态）。
    Implementation path: `BONUS_KEYWORD_SET` 落地后，on_bind 注册
      `tavern_entity_added(hero=, entity=)` 监听（或 `tavern_refresh`
      后对馆内 Murloc 结算）→ `Buff(+5/+5)`（文本字面量，CardDef num
      全 None）+ `GainKeyword(随机一枚)` 并追加 `BONUS_KEYWORDS_GRANTED`。
    Test: 未实现（不注册）。
    """


class VibrantBubbleScript:
    """
    Natural language: [x]<b>Spellcraft:</b> Give a
    Murloc a random
    <b>Bonus Keyword</b>.

    Status: DEFERRED — **Bonus Keyword 定义域无数据字段**（RULES §9.6）。
    Dependency: 同 `BG32_MagicItem_891`; 另需注册其 Spellcraft 法术本体
      `BG32_MagicItem_892t`（`spellcraft_id=121139`，36.2.2 数据核实）
      ——该法术的 on_play 同样依赖 `BONUS_KEYWORD_SET`。饰品实体的
      Spellcraft 生成点**已就绪**（`spellcraft.generate_for_hero` 扫描
      `hero.trinkets`，2026-09-02 扩展）。
    Implementation path: 定义域落地后，饰品类 on_bind 无需额外动作（引擎
      回合开始生成法术）; 注册 `BG32_MagicItem_892t` 的 `on_play`:
      目标 = 单只鱼人（含 Race.ALL），授予随机 bonus 关键词并记账;
      未声明 `needs_target`（文本无 "Choose"、wiki 无 [Targeted]）→
      随机取一只友方鱼人，无候选落空。
    Test: 未实现（不注册）。
    """


class StatueOfHireekScript:
    """
    Natural language: [x]After 2 minions in the
    Tavern are consumed, get
    a random Tavern spell.
    <i>({0} left!)</i>

    Status: DEFERRED — **`minion_consumed` 事件无来源区域字段**。
    Dependency: `minion_consumed`（actions/consume.py）载荷只有
      `(demon=, minion=)`，且受害实体在广播**之前**已被置
      `zone = REMOVED` → "酒馆中吞噬"与棋盘/手牌吞噬无法区分（棋盘吞噬
      亦会触发本卡 = 过触发）。需事件载荷增 `zone=` / `from_tavern=True`
      （batch_trinkets8/16 台账同条目，本轮复核仍缺失）。
    Implementation path: 事件补齐来源区域后，on_bind 注册
      `minion_consumed` 监听（owner=饰品实体，condition: `from_tavern`
      且 demon.controller 为本饰品控制者）→ 计数 `num(0)=2`（36.2.2
      数据核实）→ 达标后随机入手一张 Tavern spell（`spell_pool` 加权/
      `SpellPool.draw_tavern` 同口径，落空不计数）并清零滚动。
    Test: 未实现（不注册）。
    """


class STharaStickerScript:
    """
    Natural language: [x]After your last minion dies
    each combat, summon your
    first Demon that died with
    its maximum stats.

    Status: DEFERRED — **"最后一只随从死亡"触发点 + 战斗内 max-stats
      快照协议缺失**。
    Dependency: (a) 引擎只有逐次 DEATH 事件（`_process_death_inner`），
      无"该次死亡结算（含亡语补场）后己方棋盘为空"的官方时点/顺序权威
      ——`death` 事件在离场**之前**广播，此时查询"是否最后一只"会忽略
      亡语召唤物; (b) `game.combat_death_log` 只按序记录实体，无 max-stats
      快照字段与"首个恶魔"筛选的文档化口径; (c) 战斗内召唤的 max-stats
      回放协议未定义。ENGINE_BACKLOG §A 同条目（阻塞 907 + 732）。
    Implementation path: 引擎提供"最后随从死亡"钩子（死亡结算尾部 +
      己方棋盘空判定，含亡语补场之后）与本场按序 death log 的公开读取
      API（含死亡时 max-stats 快照）后，on_bind 注册该钩子 → 取本场
      **最先死亡**的己方恶魔 → 以其 max-stats 召唤。
    Test: 未实现（不注册）。
    """


class HackerfinPortraitScript:
    """
    Natural language: Get a Hackerfin. At the end of each turn, trigger
    your Hackerfins' <b>Battlecries</b>.

    Status: 已注册（batch_trinkets30）——历史台账，保留备查。
    Dependency（已关闭）: 关联卡 `BG31_148`/`BG31_148_G` Hackerfin 已由
      batch_payload_minions 注册（36.2.2 非池，`TriggerBattlecry` 有真实
      战吼可触发）; 且该战吼本身
      "Give your other minions +1/+2 (Improved by each different **Bonus
      Keyword** in your warband!)" 还依赖 RULES §9.6 的 Bonus Keyword
      定义域（双重阻塞）。
    Implementation path: 先迁 `BG31_148`（+金色 `BG31_148_G`）与 Bonus
      Keyword 定义域; 之后本卡 on_bind 交付关联卡 +
      `end_of_turn`: 对本人棋盘中 card_id ∈ {BG31_148, BG31_148_G} 的随从
      逐个走**统一战吼入口**（`TriggerBattlecry`，`battlecry_trigger`
      广播与 `COUNTER_BATTLECRIES` 记账随引擎路径）。
    Test: 未实现（不注册）。
    """


class WearyPortraitScript:
    """
    Natural language: [x]Get a Weary Mage. Your
    Weary Mages' <b>Spellcrafts</b>
    are permanent.

    Status: **已迁出** — 本类为历史 DEFERRED 骨架，**不再引用**；实现见
      `batch_trinkets37.WearyPortraitScript`（2026-09-14）。原状:
      DEFERRED — **载荷未就绪**（RULES §7.4.6 例外条，明文点名
      "Your X's **Spellcrafts** are permanent" 需 X 有 Spellcraft 脚本）。
    Dependency: (a) 关联卡 `BG31_830` Weary Mage **未注册**（36.2.2
      REGISTRY 核实）; (b) 其 Spellcraft 法术 `BG31_830t` Reinvigoration
      （"Give a minion +2/+2. If it's a Naga, also give it **Reborn**
      until next turn."）**亦未注册** → 交付物与 "permanent" 条款双双
      空转。**引擎规则已就绪**: `game.add_permanent_spellcraft_rule
      (hero, source, predicate)`（RULES §7.4.7a），本轮原语评估的结论是
      "规则有了、载荷没有"。
    Implementation path: 先迁 `BG31_830` + `BG31_830t`（其 temporary 附魔
      经 `_finish_play_spell` 的永久化拦截窗口）; 之后本卡 on_bind 交付
      关联卡并调 `add_permanent_spellcraft_rule(h, source,
      predicate=lambda game, m: m.card_id in {BG31_830, BG31_830_G})`。
    Test: 未实现（不注册）。
    """


class FlamingPortraitScript:
    """
    Natural language: [x]Get a Flaming Enforcer.
    Whenever your Flaming
    Enforcers trigger, also give
    the stats to their neighbors.

    Status: DEFERRED — **"某随从钩子触发"观察点缺失**（ENGINE_BACKLOG
      §B7e）。
    Dependency: 关联卡 `BG34_500` Flaming Enforcer **已注册**
      （batch_consume，EoT 吞噬最高生命馆内随从）; 但引擎无"该随从的
      触发已发生（含本次增量）"的广播。唯一间接信号
      `minion_consumed(demon=, minion=)` 无法区分"**该随从自身 EoT
      触发**"与"别的卡让它吞噬"（Ur'zul Sticker `BG35_MagicItem_154`
      的"另一个友方恶魔吞噬"、Methodical Madness `BG36_880` 等路径都会
      广播同一事件）→ 监听该事件会**过触发**（近似实现，SOP §6b 禁止）。
    Implementation path: 引擎新增 `minion_triggered(hook=, source=,
      value=…)` 观察点（EoT 吞噬的增量），或 `ConsumeMinion` 事件载荷增
      `gained_atk/gained_health` 且带"触发来源=自身 EoT"判定位; 之后本卡
      监听并对随从两侧相邻随从 `Buff(atk=gained_atk, health=gained_health)`。
    Test: 未实现（不注册）。
    """


class ThornspikePauldronScript:
    """
    Natural language: [x]After you trigger a
    <b>Deathrattle</b>, your
    <b>Blood Gems</b> give an extra
    +{2}/+{4} until next combat.

    Status: DEFERRED — **数值数据通道缺口**（`{4}` → TAG_SCRIPT_DATA_NUM_5
      无导出）。
    Dependency: 印面值 +2/+1（XML 核实 `TAG_SCRIPT_DATA_NUM_3=2`、
      `TAG_SCRIPT_DATA_NUM_5=1`），但生成器只导出 `TAG_SCRIPT_DATA_NUM_1..4`
      → `CardDef.num(3) is None`、`num(4)` 不存在、`CardDef.raw` 亦只有
      已导出字段 → health 半边**无任何读取通道**。硬编码 1 违反"数值一律
      `CardDef.num()`"纪律 → 整卡 DEFERRED（SOP §6b 第 4 步）。
    Implementation path: 生成器导出 `TAG_SCRIPT_DATA_NUM_5` →
      `script_data_num_5`（+ `CardDef.num()` 支持 index 4）后: on_bind
      注册 `deathrattle_trigger`（`minion.controller is 本人`）→
      `ImproveBloodGems(hero, num(2), num(4))` 并记本回合增量; 下一次
      `start_of_combat` 回退该增量（"until next combat" = 持续到下一场
      战斗开始，官方 bug 报告 us.forums.blizzard.com/en/hearthstone/t/160488）。
    Test: 未实现（不注册）。
    """


class VinespeakerPortraitScript:
    """
    Natural language: [x]Get a Vinespeaker.
    Your Vinespeakers also
    improve the Health given
    by your <b>Blood Gems</b>.

    Status: 已注册（batch_unlock_final, 2026-09-15）——历史台账，保留备查。
    Dependency: (a) 关联卡 `BG35_437`/`BG35_437_G` Vinespeaker 已由
      batch_payload_minions 注册（36.2.2 非池;
      "After a friendly **Deathrattle** minion dies, your Blood Gems give
      an extra +2 Attack this game" 无脚本）→ "your Vinespeakers" 没有任何
      触发行为; (b) "also improve the **Health**" 需要 Vinespeaker 脚本的
      `ImproveBloodGems` 出口读取 hero 级"额外 Health"标记（生产消费点，
      否则 W3 空转）。
    Implementation path: 先迁 `BG35_437`（+金色 `BG35_437_G`，num(0)=4）与
      其读取点（例 `hero._vinespeaker_bonus_health` 由 Vinespeaker 的
      Improve 出口消费）; 之后本卡 on_bind 交付关联卡并写该标记。
    Test: 未实现（不注册）。
    """


class SoulFermenterScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Destroy
    your 3 left-most minions.
    After your last minion dies,
    resummon them.

    Status: DEFERRED — **"最后一只随从死亡"触发点 + 战斗内 max-stats
      快照/回放协议缺失**（与 `BG32_MagicItem_907` 同一缺口，ENGINE_BACKLOG
      §A）。
    Dependency: (a) 无"死亡结算（含亡语补场）后己方棋盘为空"的官方时点;
      (b) "resummon them" 需战前 3 只的属性快照 + 战斗内召唤回放协议
      （`game.combat_death_log` 只记录实体，无 max-stats 字段）; (c) SoC
      阶段的"消灭己方随从"需专用摧毁入口（`HEALTH=0` + `check_deaths`
      可表达但无 `minion_destroyed` 语义区分）。
    Implementation path: 引擎提供"最后随从死亡"钩子与战斗内 max-stats
      快照/回放 API 后: `start_of_combat` 记录最左 3 只的快照并消灭之
      （填位规则按引擎既有死亡顺序）; 钩子触发时按快照重召 3 只（有板位
      则召唤，满场按 MINION_OVERFLOW）。
    Test: 未实现（不注册）。
    """


class ElectrodeAttractorScript:
    """
    Natural language: [x]<b>Magnetic</b> Mechs cost (2).
    The Tavern offers an
    extra one whenever it is
    <b>Refreshed</b>.

    Status: DEFERRED — **关键词限定的价格/展示位协议缺失**。
    Dependency: (a) 价格侧 `GameTag.TAVERN_MINION_COST_OVERRIDE` 是 hero 级
      **无条件**平价覆写（Sindragosa/Millhouse），无"仅 Magnetic Mech"
      限定; 逐实体写 `COST=2` 的方案**在新原语下已基本可行**
      （`tavern_entity_added` 覆盖 Toki/Tess/Varden 注入与 Golden Touch
      等全部入馆路径，RULES §7.4.9——不再是旧台账所说的"漏价近似"），
      但仍属"脚本镜像引擎刷新语义"; (b) "The Tavern offers an **extra
      one**"要求额外展示位是**一张 Magnetic Mech**，`TAVERN_OFFER_MOD`
      只加通用位数、`minion_pool.draw_tavern` 只支持种族白名单
      （无关键词过滤）→ 手写候选采样会绕过池权重（近似，禁止）。
      半实现（只改价）＝第三态，故整卡 DEFERRED。
    Implementation path: 引擎增"关键词限定的额外展示位抽取点"（如
      `refresh_tavern(..., keyword=MAGNETIC)` 或
      `hero._tavern_offer_keyword_only`）后，on_bind 写该限定 + 接入
      价格覆写（`num` 全 None → "cost (2)" 为文本字面量 2）。
    Test: 未实现（不注册）。
    """


class ChillmereMosaicScript:
    """
    Natural language: [x]<b>Spellcraft:</b> <b>Refresh</b> the
    Tavern with <b>Battlecry</b>
    minions. They cost (1).

    Status: DEFERRED — **关键词限定刷新原语缺失**（法术本体
      `BG35_MagicItem_755t` 一并 DEFERRED，SOP §12 item 14）。
    Dependency: `refresh_tavern` 支持 `races=`（种族白名单）与
      `spells_only=`，**无关键词白名单**; "Refresh the Tavern **with
      Battlecry minions**" 要求馆内展示项全部带 BATTLECRY。脚本侧"先普通
      刷新再逐项替换"会重写引擎刷新语义（冻结保留集 / 金馆金色化 /
      Elven Elite 档位 / 池权重抽样 / `tavern_refresh` 标记）——
      batch_trinkets18 已将该旁路定为近似; batch_spells_final 也把同类
      手写镜像收口回引擎。"They cost (1)" 侧已就绪（实体级 `COST` 被
      `buy_from_tavern` 读取）。饰品 Spellcraft 生成点已就绪
      （`spellcraft.generate_for_hero` 扫描 `hero.trinkets`）。
    Implementation path: 引擎新增 `refresh_tavern(keyword_filter={...})`
      （抽取时按 `CardDef.keywords` 过滤，含池权重与入馆统一入口）后，
      注册 `BG35_MagicItem_755t` 的 `on_play`: 以该过滤刷新本人酒馆并对
      新入馆实体写 `COST=1`（文本字面量）。
    Test: 未实现（不注册）。
    """


class CorruptedTomeScript:
    """
    Natural language: Get a Triple Prize. Whenever you would get a Triple
    Reward, get a Triple Prize instead.

    Status: DEFERRED — **三连奖励替换钩子缺失 + Darkmoon Prize 子系统
      缺失**。
    Dependency: (a) `_grant_triple_reward`（game.py:1071）是引擎内部固定
      路径（直接 `Discover(kind="triple_reward")`），无
      `hero._triple_reward_override` 之类读取点，也没有可在奖励发放前
      拦截的事件（`card_discovered` 在选项结算后才广播）; (b) 授予物
      `BG35_MagicItem_812t` Triple Prize 的 "Discover a Tier 3 Darkmoon
      Prize" 依赖 **Darkmoon Prize 子系统**（RULES §11.4，全仓无 Prize
      候选表/结算实现）。
    Implementation path: 引擎增三连奖励分支点（如
      `hero._triple_reward_card_id`，`check_for_triple` 读取并用
      `grant_card_copy_to_hand` 替代 Discover）+ Darkmoon Prize 候选池
      数据后，注册 812 与 812t。
    Test: 未实现（不注册）。
    """


class MysteriousOrbScript:
    """
    Natural language: [x]Gain {0} Gold.
    Your next <b>Trinket</b> is a
    Lesser <b>Trinket</b>.

    Status: DEFERRED — **"下一次饰品档位覆写"读取点缺失**。
    Dependency: `_offer_trinkets(hero, kind)`（game.py:3091）的 kind 由
      回合推导（T6→lesser / T9→greater，外加 `hero._trinket_early` 提前
      档），无 `hero._next_trinket_kind` 之类覆写字段; 脚本自行写字段属
      "写入后无人读取"的空转标记（audit_script_wiring W3，SOP §11
      item 3）。金币半场（`GainGold(h, num(0)=10)`，36.2.2 数据核实）
      已就绪但**不得单独注册**（半实现 = 第三态）。
    Implementation path: 引擎在 offer 判定处读取并消费
      `hero._next_trinket_kind`（消费后清零）后，on_bind 写
      `GainGold(h, num(0))` + 该字段。
    Test: 未实现（不注册）。
    """


# ═════════════════════════ 注册 ═════════════════════════


def register() -> list[str]:
    """注册本批 CORRECT 卡（1 张）。

    DEFERRED 19 张见模块 docstring 与各类 docstring 的台账
    （Status / Dependency / Implementation path）——**不注册**。
    """
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (STEGODON_PORTRAIT, StegodonPortraitScript),
    ]
    for cid, cls in pairs:
        reg(cid, cls)
    return [cid for cid, _cls in pairs]
